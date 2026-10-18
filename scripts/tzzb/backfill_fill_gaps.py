# -*- coding: utf-8 -*-
"""backfill_fill_gaps.py — 补 backfill_fill_minutes.py 缺的导师成交分钟线(10/16 晚, 零 token)
缺口五类(按 (交易日, 票) 计): CB 可转债(原脚本直接跳过) / HK 港股 / BJ 北交所 10/09 前(行情库无日线) /
  LOF 场内基金(行情库无日线) / MISS 通达信取不到或校验不过(缓存里 {"code","miss":true} 的行)
补法(10/16 实测, 报告 10/18 已删, 要点在本 docstring):
  CB/BJ/LOF/MISS  通达信历史逐笔→1 分钟 bar(口径同 collect_minute.py), 服务器轮换(一台不全/无数据换下一台, 最多 --max-servers 台);
                  校验 = 末笔≈日线收盘 ±1% 且全部成交价在日线[低,高]±1% 内 且 逐笔量≈日线量 ±3%(单位不明时容许 ×100/÷100)
                  日线: 行情库 kline_day(只读) → 没有则 downloads/tzzb/_daily_extra/<symbol>.json(腾讯 fqkline → 新浪 getKLineData 兜底, 懒取)
                  单位: 转债 逐笔量 手×10=张, 价 pytdx 按 2 位解析放大 10 倍 → 按日线收盘自动 ×0.1; LOF 量 手×100=份, 价同样 ×0.1;
                        北交所 量 手×100=股(market=2, 价不缩放)
  HK              通达信扩展行情 TdxExHq_API(119.97.142.130:7721 等, market=31 港股主板 / 48 创业板):
                  get_history_instrument_bars_range(当日) = 330 根 1 分钟 OHLC(标签 09:31~12:00, 13:01~16:00, 同 A 股"分钟末"口径),
                  量 = trade×100 股; 额由 get_history_minute_time_data 的累计均价差分得到; 日线 get_instrument_bars(4) → _daily_extra/hk<代码>.json
输出: 追加写 downloads/tzzb/_minutes/<日>.jsonl(不改已有行); 每对的尝试记录 downloads/tzzb/_gaps/fill_log.jsonl; 统计 downloads/tzzb/_gaps/stats_<tag>.json
  摘牌 A 股(通达信历史已清)  baostock 5 分钟 K → downloads/tzzb/_minutes_5m/<日>.jsonl(粒度不同, 不混进 _minutes)  [--bs5m]
  退市转债日线              腾讯 fqkline → _daily_extra(只供日线级特征/昨收)                                 [--cb-daily]
  退市转债分钟线(10/18)     新浪 getKLineData 尾窗按代码取: 退市前约 4 日 1 分钟 → _minutes, 约 21 日 5 分钟 → _minutes_5m  [--sina-tail]
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/backfill_fill_gaps.py [--stats TAG] [--fill] [--only cb,hk,bj,lof,miss] [--max-pairs N] [--bs5m] [--cb-daily] [--sina-tail] [--rerun]
   --fill 之后加 --rerun = 调 backfill_fill_minutes.py --features --report 重算 fills_rt 与报告
外部请求: 通达信 0.15~0.35s 随机间隔; 腾讯/新浪日线 2~3s 随机间隔(≤0.5 次/秒), 只在逐笔拿到后才懒取
"""
import argparse, datetime as dt, json, random, socket, subprocess, sys, time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "market"))
sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
sys.path.insert(0, str(ROOT / "scripts" / "tzzb"))
import collect_minute as cm          # noqa: E402
import backfill_fill_minutes as bf   # noqa: E402
from pytdx.config.hosts import hq_hosts   # noqa: E402
from pytdx.hq import TdxHq_API             # noqa: E402
from pytdx.exhq import TdxExHq_API         # noqa: E402

CACHE = ROOT / "downloads" / "tzzb" / "_minutes"
EXTRA = ROOT / "downloads" / "tzzb" / "_daily_extra"
GAPS = ROOT / "downloads" / "tzzb" / "_gaps"
FILL_LOG = GAPS / "fill_log.jsonl"
EX_HOSTS = [("119.97.142.130", 7721), ("112.74.214.43", 7727), ("61.152.107.141", 7727), ("119.147.86.171", 7727), ("47.107.75.159", 7727)]
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://finance.sina.com.cn"}
socket.setdefaulttimeout(15)


def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


def nap(a=0.15, b=0.35):
    time.sleep(random.uniform(a, b))


# ---------- 分类 ----------
def is_cb(code, asset):
    return asset == "CB" or code[:2] in ("11", "12")


def is_bj(code):
    return code.startswith(("92", "4", "8"))


def classify(code, asset, d, dm, have, miss):
    """补前口径(与 backfill_fill_minutes.fetch 的跳过逻辑一致)"""
    if code in have:
        return "OK"
    if len(code) == 5 or asset == "HK":
        return "HK"
    if is_cb(code, asset):
        return "CB"
    if code in miss:
        return "MISS"
    if (d, code) not in dm:
        return "BJ" if is_bj(code) else "LOF" if code.startswith(("15", "16", "50", "51")) else "NODAILY"
    return "NOTFETCHED"


def symbol_of(code):
    if len(code) == 5:
        return "hk" + code
    return cm.symbol_of_code(code)


def load_fill_log():
    out = {}
    if FILL_LOG.exists():
        for l in FILL_LOG.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                out[(r["date"], r["code"])] = r
    return out


def all_pairs(C):
    """(日, 票) → {asset, ledgers:Counter(笔数)}"""
    P = {}
    for sk, cs in C.items():
        for c in cs:
            code = str(c.get("code") or "")
            if not code or code == "None" or c.get("side") not in ("买", "卖"):
                continue
            e = P.setdefault((c["date"], code), {"asset": (c.get("feat") or {}).get("asset"), "name": c.get("name"), "n": Counter()})
            e["n"][sk] += 1
            if not e["asset"]:
                e["asset"] = (c.get("feat") or {}).get("asset")
    return P


def stats(tag, C, dm=None):
    P = all_pairs(C)
    dm = dm if dm is not None else bf.daily_map({p for p in P if len(p[1]) == 6})
    fl = load_fill_log()
    cache = {}
    pair_cnt, trade_cnt, total_p, total_t = defaultdict(Counter), defaultdict(Counter), Counter(), Counter()
    for (d, code), e in P.items():
        if d not in cache:
            cache[d] = bf.cache_load(d)
        have, miss = cache[d]
        k = "OK" if (code in have or ("hk" + code)[-6:] in have) else None
        if k is None:
            k = classify(code, e["asset"], d, dm, have, miss)
        if k != "OK" and (d, code) in fl and fl[(d, code)].get("reason"):
            k = k + ":" + fl[(d, code)]["reason"]
        for sk, n in e["n"].items():
            pair_cnt[sk][k] += 1
            trade_cnt[sk][k] += n
            total_p[sk] += 1
            total_t[sk] += n
    rt = {}
    for f in sorted(ROOT.glob("skills/*-skill/persona/fills_rt.jsonl")):
        sk = f.parts[-3].replace("-skill", "")
        xs = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        rt[sk] = [sum(1 for x in xs if x.get("rt")), len(xs)]
    out = {"tag": tag, "at": dt.datetime.now().isoformat(timespec="seconds"),
           "pairs": {k: dict(v) for k, v in pair_cnt.items()}, "trades": {k: dict(v) for k, v in trade_cnt.items()},
           "pairs_total": dict(total_p), "trades_total": dict(total_t), "rt": rt}
    GAPS.mkdir(parents=True, exist_ok=True)
    (GAPS / f"stats_{tag}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    cats = sorted({k for v in pair_cnt.values() for k in v})
    print(f"## 缺口统计 [{tag}] (日,票)对 / 成交笔")
    print("| 导师 | 对总数 | " + " | ".join(cats) + " | fills_rt 有实时特征 |")
    for sk in sorted(pair_cnt):
        print(f"| {sk} | {total_p[sk]} | " + " | ".join(f"{pair_cnt[sk].get(c, 0)}/{trade_cnt[sk].get(c, 0)}" for c in cats)
              + f" | {rt.get(sk, ['-', '-'])[0]}/{rt.get(sk, ['-', '-'])[1]} |")
    tp, tt = Counter(), Counter()
    for sk in pair_cnt:
        tp.update(pair_cnt[sk]); tt.update(trade_cnt[sk])
    print(f"| 合计 | {sum(total_p.values())} | " + " | ".join(f"{tp.get(c, 0)}/{tt.get(c, 0)}" for c in cats) + " | |")
    return out


# ---------- 外部日线(腾讯 → 新浪), 写 _daily_extra ----------
def _get_json(url):
    import requests
    r = requests.get(url, timeout=12, headers=UA)
    r.raise_for_status()
    return r.json()


def daily_from_web(sym, beg, end):
    """返回 ([{date,open,high,low,close,volume}], source); 腾讯 fqkline(不复权 day) 优先, 空则新浪(最近 N 根)"""
    rows, src = [], None
    try:
        j = _get_json(f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,{beg},{end},640,")
        d = ((j.get("data") or {}).get(sym) or {})
        ks = d.get("day") or []
        rows = [{"date": k[0], "open": float(k[1]), "close": float(k[2]), "high": float(k[3]), "low": float(k[4]),
                 "volume": float(k[5]) if len(k) > 5 else None} for k in ks]
        src = "tencent_fqkline_day"
    except Exception as e:   # noqa: BLE001
        log(f"腾讯日线失败 {sym}: {e}")
    nap(2.0, 3.0)
    if not rows:
        try:
            n = min(1023, max(60, (dt.date.today() - dt.date.fromisoformat(beg)).days))
            j = _get_json(f"https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol={sym}&scale=240&ma=no&datalen={n}")
            rows = [{"date": k["day"][:10], "open": float(k["open"]), "close": float(k["close"]), "high": float(k["high"]),
                     "low": float(k["low"]), "volume": float(k["volume"])} for k in (j or []) if beg <= k["day"][:10] <= end]
            src = "sina_getKLineData"
        except Exception as e:   # noqa: BLE001
            log(f"新浪日线失败 {sym}: {e}")
        nap(2.0, 3.0)
    rows.sort(key=lambda r: r["date"])
    for i, r in enumerate(rows):
        r["preClose"] = rows[i - 1]["close"] if i else None
    return rows, src


def extra_load(sym):
    f = EXTRA / f"{sym}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def extra_save(sym, rows, src, note=""):
    EXTRA.mkdir(parents=True, exist_ok=True)
    (EXTRA / f"{sym}.json").write_text(json.dumps({"symbol": sym, "source": src, "note": note, "fetchedAt": dt.datetime.now().isoformat(timespec="seconds"),
                                                   "bars": rows}, ensure_ascii=False), encoding="utf-8")


class DailyBook:
    """日线查询: 行情库 kline_day(dm) → _daily_extra(没有就按需从网上取, 一票一次)"""

    def __init__(self, dm, span):
        self.dm, self.span, self.tried, self.vol = dm, span, set(), {}

    def db_volume(self, sym, d):
        """bf.daily_map 不带量; 这里单查 kline_day.volume(只读)用于量校验"""
        if (sym, d) not in self.vol:
            from kline_db import db
            conn = db()
            try:
                cur = conn.cursor()
                cur.execute("select volume from kline_day where symbol=%s and trade_date=%s", (sym, d))
                r = cur.fetchone()
                self.vol[(sym, d)] = float(r[0]) if r and r[0] else None
            finally:
                conn.close()
        return self.vol[(sym, d)]

    def get(self, sym, d):
        k = self.dm.get((d, sym[-6:]))
        if k and k["symbol"] == sym:
            return {**k, "volume": self.db_volume(sym, d)}, "kline_day"
        ex = extra_load(sym)
        if (ex is None or not any(r["date"] == d for r in ex["bars"])) and sym not in self.tried:
            self.tried.add(sym)
            beg, end = self.span[sym]
            b0 = (dt.date.fromisoformat(beg) - dt.timedelta(days=20)).isoformat()
            rows, src = daily_from_web(sym, b0, end)
            if rows:
                extra_save(sym, rows, src, "导师成交补分钟线的日线校验/昨收用; 价=不复权; preClose=序列前一根收盘(未做除权调整)")
                ex = extra_load(sym)
        if ex:
            for r in ex["bars"]:
                if r["date"] == d:
                    return r, "daily_extra:" + ex["source"]
        return None, None


# ---------- 通达信标准行情(A 股/转债/北交所/LOF), 多服务器轮换 ----------
class TdxPool:
    def __init__(self):
        self.hosts = list(hq_hosts)
        self.apis = []          # [(name, api)]
        self.idx = 0

    def _connect_next(self):
        while self.idx < len(self.hosts):
            name, ip, port = self.hosts[self.idx]
            self.idx += 1
            api = TdxHq_API(raise_exception=False)
            try:
                if api.connect(ip, port, time_out=3) and api.get_security_count(1):
                    log(f"通达信 +{name} {ip}:{port}")
                    self.apis.append([f"{name} {ip}", api, ip, port])
                    return True
            except Exception:   # noqa: BLE001
                pass
        return False

    def server(self, i):
        while len(self.apis) <= i:
            if not self._connect_next():
                return None
        return self.apis[i]

    def reconnect(self, i):
        s = self.apis[i]
        try:
            s[1].disconnect()
        except Exception:   # noqa: BLE001
            pass
        api = TdxHq_API(raise_exception=False)
        try:
            api.connect(s[2], s[3], time_out=3)
        except Exception:   # noqa: BLE001
            pass
        s[1] = api

    def close(self):
        for s in self.apis:
            try:
                s[1].disconnect()
            except Exception:   # noqa: BLE001
                pass


def vol_ok(ticks, unit, k):
    """逐笔量×单位 ≈ 日线量 ±3%; 日线量单位不明(股/手/张; 科创板 10/09 前库内放大 100 倍)时容许 ×100/÷100"""
    dv = k.get("volume")
    if not dv:
        return True, None
    tv = sum(x["vol"] for x in ticks) * unit
    r = tv / float(dv)
    return any(abs(r / m - 1) <= 0.03 for m in (1, 0.01, 100, 0.1, 10)), round(r, 4)


def fetch_tdx_pair(pool, sym, d, unit, daily, max_servers):
    """返回 (bars, diag)"""
    ymd = int(d.replace("-", ""))
    diag = []
    for i in range(max_servers):
        s = pool.server(i)
        if s is None:
            break
        for attempt in range(2):
            try:
                ticks = cm.all_ticks(s[1], sym, ymd)
            except Exception as e:   # noqa: BLE001
                diag.append({"srv": s[0], "err": str(e)[:80]})
                pool.reconnect(i)
                ticks = None
                continue
            nap()
            if not ticks:
                diag.append({"srv": s[0], "n": 0})
                break
            k, ksrc = daily(sym, d)
            if not k:
                diag.append({"srv": s[0], "n": len(ticks), "nodaily": True})
                return [], diag, "无日线可校验"
            sc = cm.price_scale(ticks, k["close"])
            pok = cm.ticks_ok(ticks, k, sc)
            vok, vr = vol_ok(ticks, unit, k)
            diag.append({"srv": s[0], "n": len(ticks), "scale": sc, "last": round(ticks[-1]["price"] * sc, 3), "close": k["close"], "price_ok": pok, "vol_ratio": vr, "daily": ksrc})
            if pok and vok:
                pc = k.get("preClose")
                return cm.bars_from_ticks(sym, d, ticks, unit, pc, sc), diag, None
            if not pok and attempt == 0:   # 疑流错位: 断开重连同一台重取一次
                pool.reconnect(i)
                continue
            break
    if diag and all(x.get("n") == 0 for x in diag):
        return [], diag, "通达信各服务器均无该日逐笔"
    return [], diag, "校验不过"


# ---------- 通达信扩展行情(港股) ----------
class ExConn:
    def __init__(self):
        self.api = None

    def get(self):
        if self.api is not None:
            return self.api
        for ip, port in EX_HOSTS:
            api = TdxExHq_API(raise_exception=False)
            try:
                if api.connect(ip, port, time_out=4) and api.get_instrument_quote(31, "00700"):
                    log(f"通达信扩展行情 {ip}:{port}")
                    self.api = api
                    return api
            except Exception:   # noqa: BLE001
                pass
        raise RuntimeError("通达信扩展行情服务器全部不可用")

    def reset(self):
        try:
            self.api.disconnect()
        except Exception:   # noqa: BLE001
            pass
        self.api = None


def hk_daily(ex, code):
    sym = "hk" + code
    have = extra_load(sym)
    if have and have.get("bars"):
        return have
    for mk in (31, 48):
        rows = []
        for start in (0, 700):
            r = ex.get().get_instrument_bars(4, mk, code, start, 700) or []
            nap()
            rows = [{"date": x["datetime"][:10], "open": round(x["open"], 3), "high": round(x["high"], 3), "low": round(x["low"], 3),
                     "close": round(x["close"], 3), "volume": int(x["trade"]) * 100, "amount": x.get("amount")} for x in r] + rows
            if len(r) < 700 or (rows and rows[0]["date"] < "2025-09-01"):
                break
        if rows:
            rows.sort(key=lambda z: z["date"])
            for i, z in enumerate(rows):
                z["preClose"] = rows[i - 1]["close"] if i else None
            extra_save(sym, rows, f"tdx_ex_market{mk}", "港股日线(港元, 不复权, 量=股); preClose=序列前一根收盘")
            out = extra_load(sym)
            out["market"] = mk
            return out
    return None


def fetch_hk_pair(ex, code, d, dly):
    sym, ymd = "hk" + code, int(d.replace("-", ""))
    mk = 48 if dly.get("source", "").endswith("48") else 31
    k = next((r for r in dly["bars"] if r["date"] == d), None)
    if not k:
        return [], {"note": "扩展行情日线无该日(停牌/非港股交易日)"}, "港股该日无日线(停牌?)"
    diag = {}
    for attempt in range(2):
        try:
            r = ex.get().get_history_instrument_bars_range(mk, code, ymd, ymd) or []
            nap()
            m = ex.get().get_history_minute_time_data(mk, code, ymd) or []
            nap()
        except Exception as e:   # noqa: BLE001
            ex.reset()
            diag = {"err": str(e)[:80]}
            continue
        r = [x for x in r if x["datetime"][:10] == d]
        diag = {"n_bars": len(r), "n_mt": len(m), "close": k["close"]}
        if not r:
            return [], diag, "扩展行情无该日分钟线"
        ps = [x["close"] for x in r] + [x["high"] for x in r] + [x["low"] for x in r]
        last = r[-1]["close"]
        ok = abs(last / k["close"] - 1) <= 0.01 and max(ps) <= k["high"] * 1.01 and min(ps) >= k["low"] * 0.99
        diag.update(last=round(last, 3), price_ok=ok)
        if ok:
            break
        ex.reset()
    else:
        return [], diag, "校验不过"
    if not diag.get("price_ok"):
        return [], diag, "校验不过"
    # 额: 分时累计均价差分(分时 09:30.. 起标, 与 bar 09:31.. 一一对应, 330 点)
    cum = None
    if len(m) == len(r):
        cum, cv = [], 0
        for x in m:
            cv += x["volume"]
            cum.append((cv, x["avg_price"] * cv))
    bars, prev_a = [], 0.0
    for i, x in enumerate(r):
        v = int(x["trade"]) * 100
        if cum:
            a = cum[i][1] - prev_a
            prev_a = cum[i][1]
            avg = round(cum[i][1] / cum[i][0], 4) if cum[i][0] else None
        else:
            a, avg = x["close"] * v, None
        bars.append({"symbol": sym, "tradeDate": d, "barTime": f"{d}T{x['datetime'][11:16]}:00", "open": round(x["open"], 3), "high": round(x["high"], 3),
                     "low": round(x["low"], 3), "close": round(x["close"], 3), "volume": v, "amount": round(a, 2), "avgPrice": avg, "source": "tdx_ex"})
    return bars, diag, None


# ---------- 主流程 ----------
def fill(C, only, max_pairs, max_servers):
    P = all_pairs(C)
    dm = bf.daily_map({p for p in P if len(p[1]) == 6})
    fl = load_fill_log()
    span = {}
    for d, code in P:
        s = symbol_of(code)
        b, e = span.get(s, (d, d))
        span[s] = (min(b, d), max(e, d))
    book = DailyBook(dm, span)
    todo = defaultdict(list)
    caches = {}
    for (d, code), e in sorted(P.items()):
        if d not in caches:
            caches[d] = bf.cache_load(d)
        have, miss = caches[d]
        k = classify(code, e["asset"], d, dm, have, miss)
        if k in ("OK", "NOTFETCHED"):
            continue
        cat = {"CB": "cb", "HK": "hk", "BJ": "bj", "LOF": "lof", "NODAILY": "lof", "MISS": "miss"}[k]
        if only and cat not in only:
            continue
        if (d, code) in fl and fl[(d, code)].get("final"):
            continue   # 已尝试过且结论为不可补(断点续跑)
        todo[cat].append((d, code))
    log("待补: " + ", ".join(f"{c}={len(v)}" for c, v in todo.items()))
    GAPS.mkdir(parents=True, exist_ok=True)
    pool, ex, n_req = TdxPool(), ExConn(), 0
    res = Counter()
    flog = FILL_LOG.open("a", encoding="utf-8")
    try:
        for cat in ("miss", "cb", "bj", "lof", "hk"):
            hk_dly = {}
            for d, code in todo.get(cat, []):
                if max_pairs is not None and n_req >= max_pairs:
                    raise StopIteration
                n_req += 1
                sym = symbol_of(code)
                try:
                    if cat == "hk":
                        if code not in hk_dly:
                            hk_dly[code] = hk_daily(ex, code)
                        if not hk_dly[code]:
                            bars, diag, reason = [], {}, "扩展行情无此港股"
                        else:
                            bars, diag, reason = fetch_hk_pair(ex, code, d, hk_dly[code])
                    else:
                        unit = bf.AR.volume_unit("tdx", code)   # 10/16: 统一规则模块(通达信: 股票/ETF/LOF/北交所=手×100, 转债 1 手=10 张; 科创板也是手)
                        bars, diag, reason = fetch_tdx_pair(pool, sym, d, unit, book.get, max_servers if cat in ("miss", "bj", "lof") else min(max_servers, 3))
                except StopIteration:
                    raise
                except Exception as e:   # noqa: BLE001
                    bars, diag, reason = [], {"err": str(e)[:120]}, "异常"
                if bars:
                    with (CACHE / f"{d}.jsonl").open("a", encoding="utf-8") as fh:
                        for b in bars:
                            fh.write(json.dumps(b, ensure_ascii=False) + "\n")
                res[(cat, "ok" if bars else reason)] += 1
                flog.write(json.dumps({"date": d, "code": code, "symbol": sym, "cat": cat, "ok": bool(bars), "reason": None if bars else reason,
                                       "final": True, "diag": diag, "at": dt.datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")
                flog.flush()
                if n_req % 25 == 0:
                    log(f"进度 {n_req}: " + ", ".join(f"{a}/{b}={n}" for (a, b), n in sorted(res.items())))
    except StopIteration:
        pass
    finally:
        flog.close()
        pool.close()
        if ex.api is not None:
            ex.reset()
    log("补缺完成: " + ", ".join(f"{a}/{b}={n}" for (a, b), n in sorted(res.items())))


def bs_fallback():
    """通达信各服务器都无逐笔的 A 股(实测=已摘牌的 *ST, 通达信历史随证券表清除) → baostock 5 分钟 K(不复权)兜底;
    5 分钟粒度与 1 分钟缓存混放会让 rt_feat 的 mom5/当前 bar 口径失真 → 单独写 downloads/tzzb/_minutes_5m/<日>.jsonl, 不进 _minutes"""
    import baostock as bs
    fl = load_fill_log()
    todo = sorted((d, c) for (d, c), r in fl.items() if not r["ok"] and r["cat"] == "miss" and r["reason"] == "通达信各服务器均无该日逐笔")
    if not todo:
        return
    out_dir = ROOT / "downloads" / "tzzb" / "_minutes_5m"
    out_dir.mkdir(parents=True, exist_ok=True)
    done = set()
    for f in out_dir.glob("*.jsonl"):
        for l in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(l)
            done.add((r["tradeDate"], r["symbol"][-6:]))
    lg = bs.login()
    if lg.error_code != "0":
        log(f"baostock 登录失败 {lg.error_msg}")
        return
    n_ok = 0
    try:
        for d, code in todo:
            if (d, code) in done:
                continue
            sym = cm.symbol_of_code(code)
            rs = bs.query_history_k_data_plus(f"{sym[:2]}.{code}", "date,time,open,high,low,close,volume,amount", start_date=d, end_date=d,
                                              frequency="5", adjustflag="3")
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())
            nap(0.3, 0.6)
            if not rows:
                continue
            with (out_dir / f"{d}.jsonl").open("a", encoding="utf-8") as fh:
                cv, ca = 0, 0.0
                for _d, t, o, h, l, c, v, a in rows:
                    cv += int(float(v)); ca += float(a or 0)
                    fh.write(json.dumps({"symbol": sym, "tradeDate": d, "barTime": f"{d}T{t[8:10]}:{t[10:12]}:00", "open": float(o), "high": float(h),
                                         "low": float(l), "close": float(c), "volume": int(float(v)), "amount": round(float(a or 0), 2),
                                         "avgPrice": round(ca / cv, 4) if cv else None, "source": "baostock_5m"}, ensure_ascii=False) + "\n")
            n_ok += 1
    finally:
        bs.logout()
    log(f"baostock 5 分钟兜底: {n_ok}/{len(todo)} 对 → {out_dir}")


def cb_daily_extra(C):
    """行情库无日线的转债(已到期/退市) → 腾讯 fqkline 日线写 _daily_extra(供日线级特征/昨收; 分钟线仍不可得)"""
    P = all_pairs(C)
    dm = bf.daily_map({p for p in P if len(p[1]) == 6})
    span = {}
    for (d, code), e in P.items():
        if is_cb(code, e["asset"]) and (d, code) not in dm:
            s = cm.symbol_of_code(code)
            b, x = span.get(s, (d, d))
            span[s] = (min(b, d), max(x, d))
    n_ok = 0
    for s, (b, e) in sorted(span.items()):
        if extra_load(s):
            n_ok += 1
            continue
        rows, src = daily_from_web(s, (dt.date.fromisoformat(b) - dt.timedelta(days=20)).isoformat(), e)
        if rows:
            extra_save(s, rows, src, "已到期/退市转债日线(元/张, 不复权; 量: 沪市=张, 深市=手(10 张), 腾讯口径); 分钟线见 --sina-tail; preClose=序列前一根收盘")
            n_ok += 1
        else:
            log(f"转债日线取不到 {s}")
    log(f"退市转债日线: {n_ok}/{len(span)} 只 → {EXTRA}")


def _sina_bars(sym, scale):
    """新浪 getKLineData 分钟 K: 按代码取"最近 1023 根"——已退市/到期/强赎的转债也照样返回, 窗口止于最后交易日
    (10/18 实测 sh113618 美诺转债 04-29 退市: 1 分钟约末 4.2 个交易日、5 分钟约末 21 个交易日; 日量合计与日线逐日 1.0000, 单位=张)"""
    j = _get_json(f"https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol={sym}&scale={scale}&ma=no&datalen=1023")
    by = defaultdict(list)
    for k in j or []:
        by[k["day"][:10]].append(k)
    return by


def sina_tail():
    """10/18 用户提议"按代码补": 通达信历史随证券表清掉的退市/到期/强赎转债 → 新浪分钟 K 尾窗(土豆偏好强赎前后, 缺口集中在退市前 0~24 个交易日)。
    该日在 1 分钟窗口内且整天齐(≥235 根) → 写 _minutes(source=sina_1m, 集合竞价量并在 09:31 根, 无单独 09:30 根);
    否则在 5 分钟窗口内 → 写 _minutes_5m(source=sina_5m, 与 baostock 兜底同目录同口径)。校验: 日量合计≈_daily_extra 日线 ±3%, 末根收盘≈日线收盘 ±1%。
    请求: 每只票最多 2 次(1m/5m), 间隔 2~3.5s(≤0.5 次/秒)"""
    fl = load_fill_log()
    todo = defaultdict(list)
    for (d, code), r in fl.items():
        if not r["ok"] and r["cat"] == "cb" and r.get("gran") != "5m":
            todo[r["symbol"]].append(d)
    if not todo:
        log("新浪尾窗: 无待补退市转债")
        return
    out5 = ROOT / "downloads" / "tzzb" / "_minutes_5m"
    out5.mkdir(parents=True, exist_ok=True)
    res = Counter()
    with FILL_LOG.open("a", encoding="utf-8") as flog:
        for sym, days in sorted(todo.items()):
            ex = {b["date"]: b for b in (extra_load(sym) or {}).get("bars", [])}
            got = {}
            for scale in (1, 5):
                need = [d for d in days if d not in got]
                if not need:
                    break
                try:
                    by = _sina_bars(sym, scale)
                except Exception as e:   # noqa: BLE001
                    log(f"新浪 {sym} scale={scale} 失败: {e}")
                    by = {}
                nap(2.0, 3.5)
                for d in need:
                    rows = by.get(d) or []
                    if len(rows) < (235 if scale == 1 else 47):
                        continue
                    if scale == 1 and min(by) >= d:
                        continue   # 窗口起点那天可能只有半天(已按根数挡), 再挡一次"窗口首日"
                    k = ex.get(d)
                    v = sum(float(x["volume"]) for x in rows)
                    xu = 10 if sym.startswith("sz") else 1   # 10/18 实测: _daily_extra 的腾讯日线 深市转债量=手(10 张), 沪市=张; 新浪分钟两市都是张(额/量≈价)
                    if not k or not k.get("volume") or abs(v / (k["volume"] * xu) - 1) > 0.03 or abs(float(rows[-1]["close"]) / k["close"] - 1) > 0.01:
                        res["校验不过"] += 1
                        continue
                    got[d] = (scale, rows, round(v / (k["volume"] * xu), 4))
            for d in days:
                if d not in got:
                    res["窗口外"] += 1
                    continue
                scale, rows, vr = got[d]
                cv, ca, recs = 0, 0.0, []
                for x in rows:
                    cv += int(float(x["volume"])); ca += float(x["amount"] or 0)
                    recs.append({"symbol": sym, "tradeDate": d, "barTime": f"{d}T{x['day'][11:16]}:00", "open": float(x["open"]), "high": float(x["high"]),
                                 "low": float(x["low"]), "close": float(x["close"]), "volume": int(float(x["volume"])), "amount": round(float(x["amount"] or 0), 2),
                                 "avgPrice": round(ca / cv, 4) if cv else None, "source": f"sina_{scale}m"})
                f = (CACHE if scale == 1 else out5) / f"{d}.jsonl"
                with f.open("a", encoding="utf-8") as fh:
                    fh.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
                res[f"{scale}m"] += 1
                flog.write(json.dumps({"date": d, "code": sym[2:], "symbol": sym, "cat": "cb", "ok": scale == 1,
                                       "reason": None if scale == 1 else "仅5分钟线(新浪尾窗)", "gran": f"{scale}m", "final": True,
                                       "diag": {"src": f"sina_{scale}m", "n_bars": len(rows), "vol_ratio": vr}, "at": dt.datetime.now().isoformat(timespec="seconds")},
                                      ensure_ascii=False) + "\n")
            flog.flush()
    log("新浪尾窗补退市转债: " + ", ".join(f"{k}={n}" for k, n in sorted(res.items())))


def rerun():
    py = ROOT / "scripts" / "venv" / "Scripts" / "python.exe"
    cmd = [str(py), "-X", "utf8", str(ROOT / "scripts" / "tzzb" / "backfill_fill_minutes.py"), "--features", "--report"]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(cmd, cwd=str(ROOT), creationflags=flags, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout[-3000:])
    if r.returncode:
        print(r.stderr[-2000:])
    return r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", metavar="TAG")
    ap.add_argument("--fill", action="store_true")
    ap.add_argument("--only", help="cb,hk,bj,lof,miss 逗号分隔")
    ap.add_argument("--max-pairs", type=int)
    ap.add_argument("--max-servers", type=int, default=6)
    ap.add_argument("--rerun", action="store_true")
    ap.add_argument("--bs5m", action="store_true", help="摘牌 A 股 baostock 5 分钟兜底(写 _minutes_5m)")
    ap.add_argument("--cb-daily", action="store_true", help="退市转债日线写 _daily_extra")
    ap.add_argument("--sina-tail", action="store_true", help="退市/到期/强赎转债: 新浪分钟 K 尾窗按代码补(1m→_minutes, 5m→_minutes_5m)")
    a = ap.parse_args()
    C = bf.cases()
    if a.fill:
        fill(C, set(a.only.split(",")) if a.only else None, a.max_pairs, a.max_servers)
    if a.bs5m:
        bs_fallback()
    if a.cb_daily:
        cb_daily_extra(C)
    if a.sina_tail:
        sina_tail()
    if a.rerun:
        rerun()
    if a.stats:
        stats(a.stats, C)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
