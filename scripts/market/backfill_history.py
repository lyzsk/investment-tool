"""backfill_history.py — 行情库第 2 段: 一次性历史回补(2026-10-11 建, 10/12 凌晨改主源为 腾讯日线+新浪复权因子)
产出(downloads/market/history/, Java MarketImportServiceImpl.importHistory 读入库; 脚本不直接写库):
  security_basic.jsonl          证券基本资料(含已退市): symbol/code/exchange/secType/boardType/name/listDate/delistDate
                                → 补 security_master 的上市/退市日, 退市股补行(防幸存者偏差); 10/11 已由 baostock 产出 6157 条, 腾讯源不重写
  kline_day/<symbol>.jsonl      每只标的全部日线(不复权, 停牌日不出行)
  adjustment_factor/<symbol>.jsonl  除权除息日因子(累积后复权口径, 只在变化日一行; 首行=首根 K 线日)
  manifest_*.json               统计; 单票两个文件都在=跳过(断了原样重跑即续)

--source tencent(默认, 10/12 实测可验证):
  日线 = 腾讯 fqkline 不复权 day, 按 end 日期往前翻页(每页 ≤2000 根)直到上市首日; 覆盖 沪深股票(含退市)/ETF/转债/指数, 北交所腾讯返回空=跳过
       10/12 验证: 5 只 OHLC 与新浪快照逐位一致; volume 源单位=手 → 股票/ETF/指数 ×100, 转债 ×10(张)
       源不给 amount/换手率 → NULL(每日快照段从上线日起有)
  因子 = 新浪 hfq.js(股票专用; ETF 格式不同=暂不出因子, 指数/转债无因子)
       10/12 验证: 与 baostock 4 只比 2018-07 起前复权收盘偏差 ≤0.012%; 平安银行 baostock 在 2020-12-31 无事件凭空掉因子(119.96→99.79), 新浪无此错
       茅台 2005-08~2006-05 两源不同=股权分置改革送股, 新浪计入(正确口径)
  preClose = 推导: close(前一交易日) × F(前一交易日) / F(当日), 按价格精度四舍五入(10/12 实测与 baostock 交易所昨收一致)
  涨跌停 = 只算 ST 与否不影响规则的: 科创板 20% / 创业板 2020-08-24 起 20%(ST 同为 20%); 上市前 5 个交易日 NULL;
           主板/创业板改革前 NULL(源无历史 ST 区间, 5%/10% 无法确定, 宁缺勿错)
  防封: 腾讯/新浪也是每日链路在用的源 → 两个 host 各自限速(默认 2~3s 抖动 ≈0.4 次/秒; 10/12 00:39 实测 ≈1.6 次/秒约 600 次后
        腾讯 ifzq 整 IP 返 501, qt.gtimg 实时不受影响); 熔断=同 host 连续 5 次失败停 10 分钟, 3 次熔断无恢复=整体退出;
        --until HH:MM 到点优雅停(早盘前让路), 下次原样重跑续

--source baostock(保留备选, 10/11 夜实测 baostock 无限挂起后停用; 因子有上述错例, 恢复前须先复核):
  type=1 股票 + type=2 指数(含退市), 不复权日线+backAdjustFactor; 写 security_basic.jsonl

用法: scripts/venv/Scripts/python.exe -X utf8 scripts/market/backfill_history.py [--source tencent|baostock]
        [--codes sh600519,sz000001] [--codes-file f] [--limit N] [--shard k/n] [--force] [--until 06:30] [--max-pages 1]
  10/12 跑法: 第一轮 --max-pages 1(全市场最近 8 年, ~2h) → 之后 --force --codes-file downloads/market/history/truncated.txt 补 8 年前(断了先把已补完的从清单剔掉)
--day yyyy-MM-dd(第 6 段补采): 某交易日日线快照错过(停机/断电跨过了次日 09:15)时, 腾讯逐只取该日 1 根 → downloads/market/<day>/ 同第 1 段格式, Java 照常 importDaily
出口: 0=完成 1=有失败(manifest 记原因) 2=熔断/到点中止(重跑续)"""
import argparse
import datetime as dt
import json
import os
import random
import re
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
socket.setdefaulttimeout(60)
OUT = ROOT / "downloads" / "market" / "history"
GEM_20PCT_FROM = "2020-08-24"   # 创业板注册制改革后涨跌幅 20%
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def log(*a):
    print(f"[{dt.datetime.now():%H:%M:%S}]", *a, flush=True)


def board_type_of(code, exchange):
    if exchange == "BJ":
        return "BSE"
    if code.startswith(("688", "689")):
        return "STAR"
    if code.startswith(("300", "301", "302")):
        return "GEM"
    return "MAIN"


def limit_pct(board, trade_date, is_st):
    if is_st:
        return None
    if board == "BSE":
        return Decimal("0.30")
    if board == "STAR":
        return Decimal("0.20")
    if board == "GEM":
        return Decimal("0.20") if trade_date >= GEM_20PCT_FROM else Decimal("0.10")
    return Decimal("0.10")


def limit_pct_no_st(board, trade_date):
    """源无历史 ST 区间时: 只返回 ST 与否规则相同的情形, 其余 None"""
    if board == "STAR":
        return Decimal("0.20")
    if board == "GEM" and trade_date >= GEM_20PCT_FROM:
        return Decimal("0.20")
    return None


def rnd(x, places="0.01"):
    return float(Decimal(str(x)).quantize(Decimal(places), rounding=ROUND_HALF_UP))


def write_jsonl(path, recs):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def read_jsonl(path):
    return [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()]


# ---------------- 腾讯日线 + 新浪因子 ----------------
class Breaker(Exception):
    pass


class Host:
    """单 host 限速+熔断: 请求间隔 0.6~1.2s 抖动; 连续 5 败停 10 分钟, 3 次熔断期间无一成功=抛 Breaker"""

    def __init__(self, name, lo=0.4, hi=0.8):
        self.name, self.lo, self.hi = name, lo, hi
        self.lock = threading.Lock()
        self.last = 0.0
        self.fails = 0
        self.trips = 0

    def get(self, sess, url, headers):
        for attempt in range(3):
            with self.lock:
                wait = self.last + random.uniform(self.lo, self.hi) - time.time()
                if wait > 0:
                    time.sleep(wait)
                self.last = time.time()
            try:
                r = sess.get(url, headers={**UA, **headers}, timeout=20)
                if r.status_code == 404:
                    self._ok()
                    return None
                r.raise_for_status()
                self._ok()
                return r
            except Exception as e:   # noqa: BLE001  网络/限频: 计数, 熔断阈值内重试
                self._fail(e)
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"{self.name} 3 次重试失败: {url}")

    def _ok(self):
        with self.lock:
            self.fails = 0
            self.trips = 0

    def _fail(self, e):
        with self.lock:
            self.fails += 1
            if self.fails < 5:
                return
            self.fails = 0
            self.trips += 1
            if self.trips >= 3:
                raise Breaker(f"{self.name} 连续 3 次熔断无恢复: {e}")
            log(f"{self.name} 连续 5 次失败, 熔断 10 分钟(第 {self.trips} 次): {e}")
            time.sleep(600)


def price_places(sec_type):
    return "0.001" if sec_type in ("ETF", "CB", "INDEX") else "0.01"


def volume_mult(sec_type, symbol=""):
    """腾讯日线 volume 单位: 普通股票/ETF/指数=手(×100), 转债=手(×10 张); 10/16 晚发现科创板(688/689)腾讯已是股, 原统一 ×100 → 10/09 前科创板量放大 100 倍"""
    if str(symbol)[-6:].startswith(("688", "689")):
        return 1
    return 10 if sec_type == "CB" else 100


def tencent_bars(sess, host, sym, list_date, max_pages=0):
    """腾讯不复权日线往前翻页(单页上限 2000 根, 10/12 实测 count>2000 报 param error);
    返回 (按日期升序的 [date, open, close, high, low, vol(手)], 是否因 max_pages 截断)"""
    rows, end, pages = {}, "", 0
    while True:
        pages += 1
        r = host.get(sess, f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,{end},2000,", {})
        data = (r.json().get("data") or {}).get(sym) if r is not None else None
        page = (data or {}).get("day") or [] if isinstance(data, dict) else []
        for k in page:
            rows[k[0]] = k[:6]
        if len(page) < 2000:
            break
        first = min(k[0] for k in page)
        if list_date and first <= list_date:
            break
        if max_pages and pages >= max_pages:
            return [rows[d] for d in sorted(rows)], True
        end = (dt.date.fromisoformat(first) - dt.timedelta(days=1)).isoformat()
    return [rows[d] for d in sorted(rows)], False


def sina_factors(sess, host, sym):
    r = host.get(sess, f"https://finance.sina.com.cn/realstock/company/{sym}/hfq.js",
                 {"Referer": "https://finance.sina.com.cn"})
    if r is None:
        return []
    t = r.text
    m = re.search(r"\{.*\}", t[:t.find("/*")] if "/*" in t else t, re.S)
    if not m:
        return []
    out = []
    for x in json.loads(m.group(0)).get("data") or []:
        if "u" in x:   # ETF 格式(f 恒 1, s/u=拆分/分红), 非累积因子 → 暂不出
            return []
        out.append((x["d"], float(x["f"])))
    return sorted(out)


def build_symbol(t, kraw, fraw):
    sym, sec = t["symbol"], t["secType"]
    places, vm = price_places(sec), volume_mult(sec, sym)
    dates = [k[0] for k in kraw]
    factors = []
    if fraw and dates:
        first, last = dates[0], dates[-1]
        base = [f for d, f in fraw if d <= first]
        if base:
            factors.append({"symbol": sym, "exDate": first, "factor": base[-1], "source": "sina"})
        for d, f in fraw:
            if first < d <= last and (not factors or f != factors[-1]["factor"]):
                factors.append({"symbol": sym, "exDate": d, "factor": f, "source": "sina"})
        if factors and factors[0]["exDate"] != first:   # 新浪首个事件晚于首根 K 线且无 1900 基准行: 首日补 1.0 基准
            factors.insert(0, {"symbol": sym, "exDate": first, "factor": 1.0, "source": "sina"})
    fmap = {}
    fi, cur = 0, None
    for d in dates:
        while fi < len(factors) and factors[fi]["exDate"] <= d:
            cur = factors[fi]["factor"]
            fi += 1
        fmap[d] = cur
    bars, prev = [], None
    for n, (d, o, c, h, low, v) in enumerate(kraw, 1):
        o, c, h, low = float(o), float(c), float(h), float(low)
        if o <= 0:
            continue
        pc = None
        if prev is not None:
            pc = prev[1] * (fmap[prev[0]] / fmap[d]) if fmap.get(d) and fmap.get(prev[0]) else prev[1]
            pc = rnd(pc, places)
        lu = ld = None
        if sec == "STOCK" and pc and n > 5:
            pct = limit_pct_no_st(t["boardType"], d)
            if pct is not None:
                lu, ld = rnd(pc * (1 + float(pct))), rnd(pc * (1 - float(pct)))
        bars.append({"symbol": sym, "tradeDate": d, "open": o, "high": h, "low": low, "close": c, "preClose": pc,
                     "volume": round(float(v) * vm) if v not in (None, "") else None, "amount": None,
                     "turnoverRate": None, "limitUp": lu, "limitDown": ld, "source": "tencent"})
        prev = (d, c)
    return bars, factors


def tencent_targets():
    """当日 security_master(最近一个快照日, 去北交所) + baostock 基本资料里的已退市股票; 价值高的先做"""
    snaps = sorted(p for p in (ROOT / "downloads" / "market").glob("20*-*-*") if (p / "security_master.jsonl").exists())
    if not snaps:
        raise RuntimeError("无 security_master 快照, 先跑 collect_daily.mjs")
    cur = [r for r in read_jsonl(snaps[-1] / "security_master.jsonl") if r["exchange"] != "BJ"]
    seen = {r["symbol"] for r in cur}
    basic = {r["symbol"]: r for r in read_jsonl(OUT / "security_basic.jsonl")} if (OUT / "security_basic.jsonl").exists() else {}
    for r in cur:
        r["listDate"] = (basic.get(r["symbol"]) or {}).get("listDate")
    delisted = [r for r in basic.values() if r["secType"] == "STOCK" and r.get("delistDate")
                and r["exchange"] != "BJ" and r["symbol"] not in seen]
    order = {"STOCK": 0, "INDEX": 1, "ETF": 2, "CB": 3}
    cur.sort(key=lambda r: (order.get(r["secType"], 9), r["symbol"]))
    return cur + sorted(delisted, key=lambda r: r["symbol"]), snaps[-1].name


def run_tencent(a, mf, mf_path):
    import requests

    targets, snap = tencent_targets()
    if a.codes_file:
        a.codes = ",".join(filter(None, [a.codes] + Path(a.codes_file).read_text("utf-8").split()))
    if a.codes:
        want = {x.replace(".", "") for x in a.codes.split(",")}
        targets = [t for t in targets if t["symbol"] in want]
    k_shard, n_shard = (int(x) for x in a.shard.split("/"))
    targets = [t for i, t in enumerate(targets) if i % n_shard == k_shard - 1]
    if a.limit:
        targets = targets[:a.limit]
    log(f"腾讯源: 目标 {len(targets)} 只(快照 {snap}, 已退市 {sum(bool(t.get('delistDate')) for t in targets)})")
    until = dt.datetime.combine(dt.date.today() if dt.datetime.now().hour < int(a.until[:2]) else dt.date.today() + dt.timedelta(days=1),
                                dt.time.fromisoformat(a.until)) if a.until else None
    lo, hi = (float(x) for x in a.gap.split(","))
    tx, sn = Host("tencent", lo, hi), Host("sina", lo, hi)
    s_tx, s_sn = requests.Session(), requests.Session()
    done = skipped = failed = rows_total = 0
    fails, stop = [], ""
    t0 = time.time()
    with ThreadPoolExecutor(2) as pool:
        for i, t in enumerate(targets, 1):
            if until and dt.datetime.now() >= until:
                stop = f"到点 {a.until} 停"
                break
            sym = t["symbol"]
            kf, af = OUT / "kline_day" / f"{sym}.jsonl", OUT / "adjustment_factor" / f"{sym}.jsonl"
            if kf.exists() and af.exists() and not a.force:
                skipped += 1
                continue
            try:
                fk = pool.submit(tencent_bars, s_tx, tx, sym, t.get("listDate"), a.max_pages)
                ff = pool.submit(sina_factors, s_sn, sn, sym) if t["secType"] == "STOCK" else None
                kraw, cut = fk.result()
                fraw = ff.result() if ff else []
                bars, factors = build_symbol(t, kraw, fraw)
                if not bars:
                    raise RuntimeError("腾讯无日线")
                write_jsonl(kf, bars)
                write_jsonl(af, factors)
                if cut:
                    with (OUT / "truncated.txt").open("a", encoding="utf-8") as f:
                        f.write(sym + "\n")
                done += 1
                rows_total += len(bars)
            except Breaker as e:
                stop = str(e)
                break
            except Exception as e:   # noqa: BLE001  单票失败不阻断, 下轮重跑
                failed += 1
                fails.append(sym)
                log(f"失败 {sym}: {e}")
            if i % 100 == 0:
                log(f"进度 {i}/{len(targets)} 新做 {done} 跳过 {skipped} 失败 {failed} 日线行 {rows_total} 用时 {(time.time() - t0) / 60:.1f}min")
    mf.update({"source": "tencent+sina", "snapshot": snap, "finishedAt": dt.datetime.now().isoformat(),
               "targets": len(targets), "done": done, "skipped": skipped, "failed": failed, "failedSymbols": fails[:200],
               "klineRows": rows_total, "stopped": stop or None})
    mf_path.write_text(json.dumps(mf, ensure_ascii=False, indent=1), "utf-8")
    log(f"{'中止: ' + stop if stop else '完成'}: 目标 {len(targets)} / 新做 {done} / 跳过 {skipped} / 失败 {failed} / 日线行 {rows_total}")
    return 2 if stop else (1 if failed else 0)


# ---------------- 补采指定日(第 6 段对账用: 某交易日快照错过且已过了快照可取的时间) ----------------
def limit_now(sec, pc):
    """与 collect_daily.mjs limits() 同口径(现行规则: ST 同板块, 用户 10/11 校正); 新股 N/C 前缀不算"""
    if not pc:
        return None, None
    if sec["secType"] == "STOCK":
        if (sec.get("name") or "")[:1] in ("N", "C"):
            return None, None
        pct = 0.30 if sec.get("boardType") == "BSE" else 0.20 if sec.get("boardType") in ("GEM", "STAR") else 0.10
        return rnd(pc * (1 + pct)), rnd(pc * (1 - pct))
    if sec["secType"] == "CB":
        return rnd(pc * 1.2, "0.001"), rnd(pc * 0.8, "0.001")
    return None, None


def local_factor(sym, d):
    f = OUT / "adjustment_factor" / f"{sym}.jsonl"
    if not f.exists():
        return None
    cur = None
    for r in read_jsonl(f):
        if r["exDate"] <= d:
            cur = r["factor"]
    return cur


def run_day(a):
    """补采单日全市场日线 → downloads/market/<day>/ 与 collect_daily.mjs 同格式(+ security_master 抄最近快照), 每只 1 次腾讯请求;
    昨收=前一根 close × 本地回补因子比(本地因子缺当日除权事件时昨收会偏, 记 manifest.preCloseNoFactor 数量)"""
    import requests

    day = a.day
    out = ROOT / "downloads" / "market" / day
    if (out / "DONE_kline_day").exists() and not a.force:
        log(f"{day} 已有 DONE_kline_day, 跳过")
        return 0
    snaps = sorted(p for p in (ROOT / "downloads" / "market").glob("20*-*-*") if (p / "security_master.jsonl").exists() and p.name != day)
    if not snaps:
        raise RuntimeError("无 security_master 快照可抄")
    secs = [r for r in read_jsonl(snaps[-1] / "security_master.jsonl") if r["exchange"] != "BJ"]
    if a.limit:
        secs = secs[:a.limit]   # 测试用
    begin = (dt.date.fromisoformat(day) - dt.timedelta(days=20)).isoformat()
    lo, hi = (float(x) for x in a.gap.split(","))
    host, sess = Host("tencent", lo, hi), requests.Session()
    bars, missing, no_factor, lagging = [], 0, 0, 0
    # 10/17 健壮性 M9: 期望行数=目标日之前最近快照里有成交的票(停牌票不计), 用来区分"停牌"和"源还没更新"
    _prev = sorted(p for p in (ROOT / "downloads" / "market").glob("20*-*-*") if p.name < day and (p / "kline_day.jsonl").exists())
    active_prev = {r["symbol"] for r in read_jsonl(_prev[-1] / "kline_day.jsonl") if (r.get("volume") or 0) > 0} if _prev else set()
    for i, sec in enumerate(secs, 1):
        sym = sec["symbol"]
        try:
            r = host.get(sess, f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,{begin},{day},30,", {})
            data = (r.json().get("data") or {}).get(sym) if r is not None else None
            page = [k[:6] for k in ((data or {}).get("day") or [] if isinstance(data, dict) else [])]
        except Breaker:
            raise
        except Exception as e:   # noqa: BLE001
            log(f"失败 {sym}: {e}")
            missing += 1
            continue
        idx = next((j for j, k in enumerate(page) if k[0] == day), None)
        if idx is None:
            if sym in active_prev and (not page or page[-1][0] < day):
                lagging += 1   # 10/17 M9: 前一日还在交易、源里最后一根早于目标日 = 源滞后, 不是停牌
            continue   # 停牌/未上市/已退市
        d, o, c, h, low, v = page[idx]
        pc = None
        if idx > 0:
            prev = page[idx - 1]
            fp, fd = local_factor(sym, prev[0]), local_factor(sym, day)
            if sec["secType"] == "STOCK" and not (fp and fd):
                no_factor += 1
            pc = rnd(float(prev[2]) * (fp / fd if fp and fd else 1.0), price_places(sec["secType"]))
        lu, ld = limit_now(sec, pc)
        bars.append({"symbol": sym, "tradeDate": day, "open": float(o), "high": float(h), "low": float(low), "close": float(c),
                     "preClose": pc, "volume": round(float(v) * volume_mult(sec["secType"], sym)), "amount": None, "turnoverRate": None,
                     "limitUp": lu, "limitDown": ld, "source": "tencent"})
        if i % 500 == 0:
            log(f"补采 {day} 进度 {i}/{len(secs)} 有行情 {len(bars)}")
    if len(bars) < len(secs) * 0.5:
        raise RuntimeError(f"补采 {day} 只拿到 {len(bars)}/{len(secs)} 行, 疑似非交易日或源异常, 不落 DONE")
    exp = len(active_prev & {s["symbol"] for s in secs}) if active_prev and not a.limit else 0
    if exp and len(bars) < exp * 0.97:
        raise RuntimeError(f"补采 {day} 只拿到 {len(bars)} 行 < 前一交易日有成交 {exp} 只的 97%(源滞后 {lagging} / 请求失败 {missing}), 不落 DONE")
    if no_factor > 20:
        raise RuntimeError(f"补采 {day} 昨收无本地因子 {no_factor} 只 > 20(除权事件缺, 昨收/涨停价会偏), 先跑因子刷新再补, 不落 DONE")
    out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "security_master.jsonl", secs)
    write_jsonl(out / "kline_day.jsonl", bars)
    now = dt.datetime.now().isoformat()
    (out / "manifest.json").write_text(json.dumps({"tradeDate": day, "source": "tencent-catchup", "securityFrom": snaps[-1].name,
                                                   "klineRows": len(bars), "requestFailed": missing, "preCloseNoFactor": no_factor, "sourceLagging": lagging,
                                                   "at": now}, ensure_ascii=False, indent=1), "utf-8")
    (out / "DONE_security").write_text(now)
    (out / "DONE_kline_day").write_text(now)
    log(f"补采 {day} 完成: kline_day {len(bars)} 行 / 请求失败 {missing} / 昨收无因子 {no_factor}")
    return 0


# ---------------- baostock(备选, 10/11 夜停用) ----------------
def run_baostock(a, mf, mf_path):
    import baostock as bs

    def rows_of(rs):
        out = []
        while rs.error_code == "0" and rs.next():
            out.append(rs.get_row_data())
        if rs.error_code != "0":
            raise RuntimeError(f"baostock {rs.error_code} {rs.error_msg}")
        return out

    def with_retry(fn, tries=3):
        last = None
        for i in range(tries):
            try:
                return fn()
            except Exception as e:   # noqa: BLE001  baostock 偶发断连: 重登再试
                last = e
                time.sleep(2 * (i + 1))
                try:
                    bs.logout()
                except Exception:   # noqa: BLE001
                    pass
                bs.login()
        raise last

    lg = bs.login()
    if lg.error_code != "0":
        log("baostock 登录失败", lg.error_msg)
        return 1
    try:
        basic = with_retry(lambda: rows_of(bs.query_stock_basic()))   # code,code_name,ipoDate,outDate,type,status
        recs = []
        for code, name, ipo, out, typ, status in basic:
            if typ not in ("1", "2"):
                continue
            ex = code[:2].upper()
            c = code[3:]
            sec_type = "STOCK" if typ == "1" else "INDEX"
            recs.append({"symbol": code.replace(".", ""), "code": c, "exchange": ex, "secType": sec_type,
                         "boardType": board_type_of(c, ex) if sec_type == "STOCK" else None, "name": name,
                         "listDate": ipo or None, "delistDate": out or None, "source": "baostock"})
        if a.shard.startswith("1/"):   # 只由分片 1 写基本资料, 防多进程并发写同一文件
            write_jsonl(OUT / "security_basic.jsonl", recs)
            (OUT / "DONE_basic").write_text(dt.datetime.now().isoformat())
        log(f"基本资料 {len(recs)} 条")
        targets = [r for r in recs if not a.codes or r["symbol"] in {x.replace(".", "") for x in a.codes.split(",")}]
        k_shard, n_shard = (int(x) for x in a.shard.split("/"))
        targets = [r for i, r in enumerate(targets) if i % n_shard == k_shard - 1]
        if a.limit:
            targets = targets[:a.limit]
        end = dt.date.today().isoformat()
        done = skipped = failed = rows_total = 0
        for i, r in enumerate(targets, 1):
            sym, bs_code = r["symbol"], f"{r['symbol'][:2]}.{r['symbol'][2:]}"
            kf, af = OUT / "kline_day" / f"{sym}.jsonl", OUT / "adjustment_factor" / f"{sym}.jsonl"
            if kf.exists() and af.exists() and not a.force:
                skipped += 1
                continue
            try:
                start = r["listDate"] or "1990-12-19"
                k = with_retry(lambda: rows_of(bs.query_history_k_data_plus(
                    bs_code, "date,open,high,low,close,preclose,volume,amount,turn,tradestatus,isST",
                    start_date=start, end_date=end, frequency="d", adjustflag="3")))
                bars, n_traded = [], 0
                for d, o, h, l, c, pc, v, amt, turn, ts, st in k:
                    if ts != "1" or not o or float(o) <= 0:
                        continue   # 停牌不出行
                    n_traded += 1
                    lu = ld = None
                    if r["secType"] == "STOCK" and n_traded > 5 and pc:
                        pct = limit_pct(r["boardType"], d, st == "1")
                        if pct is not None:
                            lu, ld = rnd(float(pc) * (1 + float(pct))), rnd(float(pc) * (1 - float(pct)))
                    bars.append({"symbol": sym, "tradeDate": d, "open": float(o), "high": float(h), "low": float(l),
                                 "close": float(c), "preClose": float(pc) if pc else None,
                                 "volume": int(float(v)) if v else None, "amount": rnd(float(amt)) if amt else None,
                                 "turnoverRate": float(turn) if turn else None, "limitUp": lu, "limitDown": ld,
                                 "source": "baostock"})
                factors = []
                if r["secType"] == "STOCK":
                    f = with_retry(lambda: rows_of(bs.query_adjust_factor(code=bs_code, start_date=start, end_date=end)))
                    factors = [{"symbol": sym, "exDate": x[1], "factor": float(x[3]), "source": "baostock"} for x in f]
                write_jsonl(kf, bars)
                write_jsonl(af, factors)
                done += 1
                rows_total += len(bars)
            except Exception as e:   # noqa: BLE001  单票失败不阻断, 记账下轮重跑
                failed += 1
                log(f"失败 {sym}: {e}")
            if i % 200 == 0:
                log(f"进度 {i}/{len(targets)} 完成 {done} 跳过 {skipped} 失败 {failed} 日线行 {rows_total}")
        mf.update({"source": "baostock", "finishedAt": dt.datetime.now().isoformat(), "targets": len(targets),
                   "done": done, "skipped": skipped, "failed": failed, "klineRows": rows_total})
        mf_path.write_text(json.dumps(mf, ensure_ascii=False, indent=1), "utf-8")
        log(f"完成: 目标 {len(targets)} / 新做 {done} / 跳过 {skipped} / 失败 {failed} / 日线行 {rows_total}")
        return 1 if failed else 0
    finally:
        bs.logout()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="tencent", choices=["tencent", "baostock"])
    ap.add_argument("--codes", default="", help="只回补这些代码(逗号分隔, sh600519 或 sh.600519), 测试用")
    ap.add_argument("--limit", type=int, default=0, help="最多回补 N 只(测试用)")
    ap.add_argument("--force", action="store_true", help="已有单票文件也重做")
    ap.add_argument("--shard", default="1/1", help="分片 k/n: 只做序号 mod n == k-1 的标的")
    ap.add_argument("--until", default="", help="HH:MM 到点优雅停(腾讯源), 如 06:30")
    ap.add_argument("--max-pages", type=int, default=0, help="腾讯源每只最多翻 N 页(1 页=最近 2000 根≈8 年), 截断的记 truncated.txt, 之后 --force --codes-file 补全")
    ap.add_argument("--codes-file", default="", help="代码清单文件(每行一个), 与 --codes 合并")
    ap.add_argument("--gap", default="2.0,3.0", help="每 host 请求间隔秒数范围 lo,hi(10/12 实测 ~1.6 次/秒 6 分钟后腾讯 ifzq 封 IP 返 501)")
    ap.add_argument("--day", default="", help="yyyy-MM-dd: 补采该日全市场日线到 downloads/market/<day>/(对账补采用), 与回补模式互斥")
    a = ap.parse_args()
    if a.day:
        return run_day(a)
    (OUT / "kline_day").mkdir(parents=True, exist_ok=True)
    (OUT / "adjustment_factor").mkdir(parents=True, exist_ok=True)
    mf_path = OUT / f"manifest_{a.source}_{a.shard.replace('/', 'of')}.json"
    mf = json.loads(mf_path.read_text("utf-8")) if mf_path.exists() else {}
    return run_tencent(a, mf, mf_path) if a.source == "tencent" else run_baostock(a, mf, mf_path)


if __name__ == "__main__":
    sys.exit(main())
