"""collect_minute.py — 行情库第 3 段: 关注集 + 分时(1 分钟 K)采集(2026-10-11 建)
链路: MarketDailyHandler(15:35, 第 1 段 collect_daily.mjs 之后) → 本脚本 → downloads/market/<交易日>/{watchlist_info,kline_minute}.jsonl
      + DONE_watchlist / DONE_kline_minute → Java MarketImportService 按交易日先删后插入库(脚本不直接写库)
关注集(当日并集, 每只记入选原因):
  HOLD   paper 各账本(scripts/dfcf/paper/books)持仓 + 未成挂单       PLAN   当日计划单(plans/<日>_*.md) + 当日链 04/05/06 契约里的 code
  POOL   skills/taoge-skill/persona/pools.json 低吸池               MENTOR 导师当日 tzzb 持仓/操作(downloads/tzzb/*/day_positions.json, 剔逆回购)
  ZT/DT  当日收盘=涨停价/跌停价(由第 1 段 kline_day.jsonl 本地判定, 零网络)
  MD     当日 md 提及(6 位代码 + ≥3 字证券名)                       FIXED  固定指数(上证/深成/创业板指/科创50/沪深300/中证1000)
  STICKY 粘滞: 最后一次命中后再保留 10 个交易日(读前 10 个交易日的 watchlist_info.jsonl)
分时来源(10/11 夜实测): 东财 push2/push2his 整个 IP 被断连; 通达信 K 线命令对现服务器全部失效, 但逐笔成交与历史分时可用 →
  股票/转债/ETF = 通达信逐笔聚合成 1 分钟 OHLC(茅台 10/09 实测: 量 3511300 vs 日线 3511051 股, 误差 0.007%; 额误差 0.01%)
  指数 = 通达信历史分时(只有价/量, OHLC 均取该分钟价, source=tdx_mt)
分钟标签(与 kline_minute.bar_time 口径一致, 共 241 根): 09:25 撮合 → 09:30; 09:30~11:29 的成交 → +1 分钟; 11:30 → 11:30;
  13:00~14:59 → +1 分钟; 15:00 → 15:00; 15:00 之后(盘后)剔除; 无成交的分钟用上一根收盘价补平(量额为 0)
单位: 股票/ETF 逐笔量=手 ×100 → 股; 转债 1 手=10 张 ×10 → 张; 额=价×量 累加(元); 转债/ETF 价格按日线收盘自动校正 pytdx 的 10 倍缩放
范围: 只收 A 股 6 位代码; 北交所(bj)通达信市场码不支持, 暂缺(10/11 实测)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/market/collect_minute.py [--date yyyy-MM-dd] [--force] [--only-watchlist]
出口: 0=成功 1=失败"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import socket
import sys
from pathlib import Path

from pytdx.config.hosts import hq_hosts
from pytdx.hq import TdxHq_API

ROOT = Path(__file__).resolve().parents[2]
MARKET = ROOT / "downloads" / "market"
STICKY_DAYS = 10
FIXED_INDEX = ["sh000001", "sz399001", "sz399006", "sh000688", "sh000300", "sh000852"]
REPO_RE = re.compile(r"^(204|1318)")   # 国债逆回购
socket.setdefaulttimeout(30)


def log(*a):
    print(f"[{dt.datetime.now():%H:%M:%S}]", *a, flush=True)


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text("utf-8").splitlines() if l.strip()]


def write_jsonl(path, recs):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def symbol_of_code(code):
    """6 位代码 → 带市场前缀 symbol(无 security_master 命中时的兜底规则)"""
    if code.startswith(("60", "68", "90", "11", "5")):
        return "sh" + code
    if code.startswith(("92", "4", "8")):
        return "bj" + code
    return "sz" + code


def trading_days_before(day, n):
    """day 之前已有采集目录的最近 n 个交易日(以 downloads/market/<日>/kline_day.jsonl 存在为准)"""
    ds = sorted(d.name for d in MARKET.iterdir() if re.match(r"\d{4}-\d{2}-\d{2}$", d.name) and d.name < day
                and (d / "kline_day.jsonl").exists())
    return ds[-n:]


def build_watchlist(day):
    """返回 {symbol: {reasons:set, detail:list}}; 依赖第 1 段已产出 <日>/security_master.jsonl + kline_day.jsonl"""
    sec = read_jsonl(MARKET / day / "security_master.jsonl")
    kl = read_jsonl(MARKET / day / "kline_day.jsonl")
    if not sec or not kl:
        raise RuntimeError(f"{day} 第 1 段产物缺失(security_master/kline_day.jsonl), 先跑 collect_daily.mjs")
    by_code = {}
    for s in sec:
        by_code.setdefault(s["code"], s["symbol"])   # 同代码多市场(000001 平安/上证指数)时 STOCK 先入优先
    names = {s["name"]: s["symbol"] for s in sec if s["secType"] in ("STOCK", "CB", "ETF") and len(s["name"]) >= 3}
    wl = {}

    def add(code_or_sym, reason, detail):
        if not re.match(r"^((sh|sz|bj)\d{6}|\d{6})$", code_or_sym):
            return   # 只收 A 股 6 位代码(tzzb 港股为 5 位, 不在本段范围)
        sym = code_or_sym if re.match(r"^(sh|sz|bj)", code_or_sym) else by_code.get(code_or_sym) or symbol_of_code(code_or_sym)
        e = wl.setdefault(sym, {"reasons": set(), "detail": []})
        e["reasons"].add(reason)
        if detail and len(e["detail"]) < 6:
            e["detail"].append(detail)

    # HOLD: 账本持仓 + 未成挂单
    for f in glob.glob(str(ROOT / "scripts/dfcf/paper/books/*.json")):
        try:
            b = json.loads(Path(f).read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        src = Path(f).stem
        for code in (b.get("positions") or {}):
            add(code, "HOLD", f"{src} 持仓")
        for o in b.get("orders") or []:
            if o.get("status") == "open":
                add(o["code"], "HOLD", f"{src} 挂单")
    # PLAN: 当日计划单 + 当日链 04/05/06 契约
    for f in glob.glob(str(ROOT / f"scripts/dfcf/paper/plans/{day}_*.md")):
        for code in re.findall(r"\|\s*(\d{6})\s*\|", Path(f).read_text("utf-8", errors="replace")):
            add(code, "PLAN", Path(f).stem.split("_", 1)[1] + " 计划单")
    for f in glob.glob(str(ROOT / f"results/*_chain/live-{day.replace('-', '')}/0[456]_*.md")):
        for code in set(re.findall(r'"code"\s*:\s*"(\d{6})"', Path(f).read_text("utf-8", errors="replace"))):
            add(code, "PLAN", Path(f).parent.parent.name.replace("_chain", "") + " 链候选")
    # POOL
    try:
        pools = json.loads((ROOT / "skills/taoge-skill/persona/pools.json").read_text("utf-8")).get("directions", {})
        for dname, dv in pools.items():
            for s in dv.get("stocks", []):
                if s.get("code"):
                    add(s["code"], "POOL", f"低吸池·{dname}")
    except (OSError, json.JSONDecodeError):
        pass
    # MENTOR: 导师当日持仓/操作
    ymd = day.replace("-", "")
    for f in glob.glob(str(ROOT / "downloads/tzzb/*/day_positions.json")):
        try:
            dp = json.loads(Path(f).read_text("utf-8")).get(ymd) or {}
        except (OSError, json.JSONDecodeError):
            continue
        for x in dp.get("list") or []:
            code = str(x.get("code") or "")
            if code and not REPO_RE.match(code):
                add(code, "MENTOR", f"{Path(f).parent.name} 当日持仓/操作")
    # ZT/DT: 收盘 = 涨停价/跌停价
    for k in kl:
        if k.get("limitUp") and abs(k["close"] - k["limitUp"]) < 1e-6:
            add(k["symbol"], "ZT", "当日涨停")
        elif k.get("limitDown") and abs(k["close"] - k["limitDown"]) < 1e-6:
            add(k["symbol"], "DT", "当日跌停")
    # MD: 当日 md 提及
    y, m, _ = day.split("-")
    md = ROOT / "md" / f"{y}S{(int(m) - 1) // 3 + 1}" / f"{day}.md"
    if md.exists():
        text = md.read_text("utf-8", errors="replace")
        for code in set(re.findall(r"(?<!\d)(6\d{5}|0\d{5}|3\d{5}|92\d{4}|1[12]\d{4})(?!\d)", text)):
            if code in by_code:
                add(code, "MD", "当日 md 提及代码")
        for nm, sym in names.items():
            if nm in text:
                add(sym, "MD", f"当日 md 提及「{nm}」")
    # FIXED
    for sym in FIXED_INDEX:
        add(sym, "FIXED", "固定指数")
    # STICKY: 前 10 个交易日入选且粘滞未到期
    for d in trading_days_before(day, STICKY_DAYS):
        for r in read_jsonl(MARKET / d / "watchlist_info.jsonl"):
            if r.get("stickyUntil") and r["stickyUntil"] >= day and r["symbol"] not in wl:
                add(r["symbol"], "STICKY", f"{d} 入选粘滞至 {r['stickyUntil']}")
    return wl, {s["symbol"]: s for s in sec}


def sticky_until(day, wl_reasons):
    """非 STICKY 命中: 粘滞到 day 之后第 10 个交易日(按自然日 ×1.5 近似, 入库后由下一次计算覆盖为准)"""
    if wl_reasons == {"STICKY"}:
        return None
    return (dt.date.fromisoformat(day) + dt.timedelta(days=int(STICKY_DAYS * 1.5))).isoformat()


# ---------- 通达信 ----------
def connect(ymd=None, skip=()):
    """连第一个可用的通达信服务器; 给了 ymd 时还要求该服务器有这一天的逐笔(探 002714/600000),
    10/12 实录: 上证云成都电信一能连但收盘后当日逐笔为空, 396 只缺 390"""
    for name, ip, port in hq_hosts:
        if ip in skip:   # 10/16 晚 健壮性 H1: 缺失补抓时换一台服务器
            continue
        api = TdxHq_API(raise_exception=False)
        try:
            if api.connect(ip, port, time_out=3) and api.get_security_count(1):
                # 10/16 修: 原为 sz 或 sh 任一有逐笔即通过; 10/16 连上的服务器只有深市逐笔, 沪市 358 只全缺 → 改为两市都要有
                if ymd and not (api.get_history_transaction_data(0, "002714", 0, 5, ymd)
                                and api.get_history_transaction_data(1, "600000", 0, 5, ymd)):
                    log(f"通达信 {name} {ip}:{port} 无 {ymd} 逐笔, 换下一台")
                    api.disconnect()
                    continue
                log(f"通达信 {name} {ip}:{port}")
                api._ip = ip
                return api
        except Exception:   # noqa: BLE001
            continue
    raise RuntimeError("通达信服务器全部不可用" + (f"(或都没有 {ymd} 逐笔)" if ymd else ""))


def tdx_market(sym):
    return {"sh": 1, "sz": 0, "bj": 2}[sym[:2]]


def all_ticks(api, sym, ymd):
    out, start = [], 0
    while True:
        r = api.get_history_transaction_data(tdx_market(sym), sym[2:], start, 2000, ymd)
        if not r:
            break
        out = list(r) + out
        start += len(r)
        if len(r) < 2000:
            break
    return out


LABELS = ["09:30"] + [f"{h:02d}:{m:02d}" for h in (9, 10, 11) for m in range(60)
                      if "09:31" <= f"{h:02d}:{m:02d}" <= "11:30"] + \
         [f"{h:02d}:{m:02d}" for h in (13, 14, 15) for m in range(60) if "13:01" <= f"{h:02d}:{m:02d}" <= "15:00"]


def label_of(t):
    """成交时刻 HH:MM → 分钟 K 标签; None=不计入(竞价指示/盘后)"""
    if t == "09:25":
        return "09:30"
    if "09:30" <= t <= "11:29" or "13:00" <= t <= "14:59":
        h, m = map(int, t.split(":"))
        m += 1
        return f"{h + m // 60:02d}:{m % 60:02d}"
    if t in ("11:30", "15:00"):
        return t
    return None


def price_scale(ticks, day_close):
    """pytdx 对 3 位小数品种(转债/ETF)按 2 位解析, 逐笔价放大 10 倍(10/11 实测澳弘转债 1948.97 vs 日线 194.897);
    用当日日线收盘价比对末笔成交价判定缩放, 无日线则不缩放"""
    last = next((x["price"] for x in reversed(ticks) if x["vol"] > 0), None)
    if not last or not day_close:
        return 1.0
    r = last / day_close
    return 0.1 if 8 < r < 12 else 0.01 if 80 < r < 120 else 1.0


def ticks_ok(ticks, k, scale):
    """逐笔与当日日线对得上才算本票的数据: 末笔(缩放后)≈收盘 ±1%, 全部价格在 [最低, 最高] ±1% 内"""
    ps = [x["price"] * scale for x in ticks if x["vol"] > 0]
    if not ps:
        return True
    c, h, l = k.get("close"), k.get("high"), k.get("low")
    if c and abs(ps[-1] / c - 1) > 0.01:
        return False
    if h and l and (max(ps) > h * 1.01 or min(ps) < l * 0.99):
        return False
    return True


def bars_from_ticks(sym, day, ticks, unit, pre_close, scale=1.0):
    if scale != 1.0:
        ticks = [{**x, "price": round(x["price"] * scale, 4)} for x in ticks]
    buckets = {}
    for x in ticks:
        lab = label_of(x["time"])
        if lab is None or x["vol"] <= 0:
            continue
        buckets.setdefault(lab, []).append(x)
    bars, last, cum_v, cum_a = [], pre_close, 0, 0.0
    for lab in LABELS:
        b = buckets.get(lab)
        if b:
            ps = [x["price"] for x in b]
            v = sum(x["vol"] for x in b) * unit
            a = sum(x["price"] * x["vol"] * unit for x in b)
            o, h, l, c = ps[0], max(ps), min(ps), ps[-1]
        else:
            o = h = l = c = last
            v, a = 0, 0.0
        if c is None:
            continue
        cum_v += v
        cum_a += a
        bars.append({"symbol": sym, "tradeDate": day, "barTime": f"{day}T{lab}:00", "open": o, "high": h, "low": l, "close": c,
                     "volume": int(v), "amount": round(a, 2), "avgPrice": round(cum_a / cum_v, 4) if cum_v else None,
                     "source": "tdx"})
        last = c
    return bars


def flow_from_ticks(sym, day, ticks, unit):
    """10/18 晚(用户定 P1): 逐笔的主动买卖方向不再丢弃 → 每分钟 主动买量 / 主动卖量 / 中性量 / 笔数(只写有成交的分钟)。
    pytdx buyorsell: 0=主动买(外盘) 1=主动卖(内盘) 2=中性(集合竞价/平盘) 其他(实测少量 5)=记中性。方向是按成交价对买一/卖一推的, 不是交易所原始标记。
    单独写 tick_flow.jsonl, 不进 kline_minute.jsonl(Java 入库格式不动)"""
    bk = {}
    for x in ticks:
        lab = label_of(x["time"])
        if lab is None or x["vol"] <= 0:
            continue
        r = bk.setdefault(lab, {"symbol": sym, "barTime": f"{day}T{lab}:00", "buyVol": 0, "sellVol": 0, "neuVol": 0, "n": 0, "buyN": 0, "sellN": 0})
        v = int(x["vol"]) * unit
        side = x.get("buyorsell")
        if side == 0:
            r["buyVol"] += v
            r["buyN"] += 1
        elif side == 1:
            r["sellVol"] += v
            r["sellN"] += 1
        else:
            r["neuVol"] += v
        r["n"] += 1
    return [bk[k] for k in LABELS if k in bk]


def bars_from_minute_time(api, sym, day, ymd):
    r = api.get_history_minute_time_data(tdx_market(sym), sym[2:], int(ymd))
    if not r or len(r) < 200:
        return []
    labels = LABELS[1:]   # 历史分时 240 点 = 09:31~11:30 + 13:01~15:00
    bars = []
    for lab, x in zip(labels, r):
        p = x["price"]
        bars.append({"symbol": sym, "tradeDate": day, "barTime": f"{day}T{lab}:00", "open": p, "high": p, "low": p, "close": p,
                     "volume": int(x["vol"]) * 100, "amount": None, "avgPrice": None, "source": "tdx_mt"})
    return bars


def flow_only(day, out, force):
    """补历史 tick_flow.jsonl: 读当日已有 watchlist_info.jsonl(非指数), 逐笔重取 + 同样的串票校验, 只写 tick_flow.jsonl"""
    f = out / "tick_flow.jsonl"
    if f.exists() and not force:
        log(f"{day} 已有 tick_flow.jsonl, 跳过")
        return 0
    syms = [r["symbol"] for r in read_jsonl(out / "watchlist_info.jsonl") if r["symbol"] not in FIXED_INDEX]
    kl = {k["symbol"]: k for k in read_jsonl(out / "kline_day.jsonl")}
    ymd = int(day.replace("-", ""))
    api, flows, miss = connect(ymd), [], 0
    try:
        for i, sym in enumerate(syms, 1):
            k = kl.get(sym) or {}
            unit = 10 if sym[2:5] in ("110", "111", "113", "118", "123", "127", "128") else 100   # 转债 1 手=10 张
            try:
                ticks = all_ticks(api, sym, ymd)
                sc = price_scale(ticks, k.get("close")) if ticks else 1.0
                if not ticks or (k.get("close") and not ticks_ok(ticks, k, sc)):
                    miss += 1
                    if ticks:
                        api.disconnect()
                        api = connect(ymd)
                    continue
                flows.extend(flow_from_ticks(sym, day, ticks, unit))
            except Exception as e:   # noqa: BLE001
                miss += 1
                log(f"失败 {sym}: {e}")
                try:
                    api.disconnect()
                except Exception:   # noqa: BLE001
                    pass
                api = connect(ymd)
            if i % 200 == 0:
                log(f"flow 进度 {i}/{len(syms)} 缺 {miss}")
    finally:
        api.disconnect()
    write_jsonl(f, flows)
    log(f"tick_flow {day}: {len(syms)} 只, {len(flows)} 行, 缺 {miss}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="交易日 yyyy-MM-dd(缺省=downloads/market 下最新一个已有 kline_day 的日期)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only-watchlist", action="store_true")
    ap.add_argument("--flow-only", action="store_true", help="10/18: 只补 tick_flow.jsonl(主动买卖), 读已有关注集, 不动 kline_minute / DONE")
    a = ap.parse_args()
    day = a.date or max(d.name for d in MARKET.iterdir() if (d / "kline_day.jsonl").exists())
    out = MARKET / day
    if a.flow_only:
        return flow_only(day, out, a.force)
    if (out / "DONE_kline_minute").exists() and not a.force:
        log(f"{day} 已有 DONE_kline_minute, 跳过(--force 重做)")
        return 0
    wl, sec = build_watchlist(day)
    recs = []
    for sym, e in sorted(wl.items()):
        reasons = sorted(e["reasons"])
        recs.append({"tradeDate": day, "symbol": sym, "reasons": ",".join(reasons),
                     "reasonDetail": "; ".join(e["detail"])[:500] or None, "stickyUntil": sticky_until(day, set(reasons))})
    write_jsonl(out / "watchlist_info.jsonl", recs)
    (out / "DONE_watchlist").write_text(dt.datetime.now().isoformat())
    cnt = {}
    for r in recs:
        for x in r["reasons"].split(","):
            cnt[x] = cnt.get(x, 0) + 1
    log(f"关注集 {day}: {len(recs)} 只 {cnt}")
    if a.only_watchlist:
        return 0

    kl = {k["symbol"]: k for k in read_jsonl(out / "kline_day.jsonl")}
    ymd = int(day.replace("-", ""))
    t0 = dt.datetime.now()

    def one_pass(recs, api_skip=()):
      api, bars, miss, bad, flows = connect(ymd, api_skip), [], [], [], []
      used = getattr(api, "_ip", "")
      try:
        for i, r in enumerate(recs, 1):
            sym = r["symbol"]
            s = sec.get(sym, {})
            try:
                if s.get("secType") == "INDEX":
                    b = bars_from_minute_time(api, sym, day, ymd)
                    # 10/18 健壮性 M2: 通达信历史分时的指数量和日线量对不上(上证/深成分钟合计只有日线 15%, 科创50 却≈100%, 单位/口径不明)
                    #   → 按当日日线量等比校准, 让分钟量合计 = 日线量(分时形状保留, 量比/量能可用); 记 volScale 便于追溯; 日线缺=不校准
                    dv = (kl.get(sym) or {}).get("volume")
                    sv = sum(x["volume"] for x in b)
                    if b and dv and sv:
                        k_ = dv / sv
                        for x in b:
                            x["volume"] = int(round(x["volume"] * k_))
                            x["volScale"] = round(k_, 4)
                else:
                    unit = 10 if s.get("secType") == "CB" else 100
                    k = kl.get(sym) or {}
                    # 10/14 修: 通达信 TCP 流在超时/重连后会错位, 读到的是上一只票的回包(10/14 184 只里 107 只价格串票, 如 002172
                    #   收 5.65 被写成 13.07)。校验: 缩放后末笔≈日线收盘(±1%)且全部成交价落在日线[最低, 最高]±1% 内;
                    #   不过=断开重连重取一次, 仍不过=记缺失不写(宁缺毋错)
                    for _try in range(2):
                        ticks = all_ticks(api, sym, ymd)
                        sc = price_scale(ticks, k.get("close")) if ticks else 1.0
                        if not ticks or not k.get("close") or ticks_ok(ticks, k, sc):
                            break
                        log(f"校验不过 {sym}(疑通达信流错位), 重连重取")
                        try:
                            api.disconnect()
                        except Exception:   # noqa: BLE001
                            pass
                        api = connect(ymd)
                    else:
                        ticks = []
                        bad.append(sym)
                    b = bars_from_ticks(sym, day, ticks, unit, k.get("preClose"), sc) if ticks else []
                    if b:
                        flows.extend(flow_from_ticks(sym, day, ticks, unit))
                if b:
                    bars.extend(b)
                else:
                    miss.append(sym)
            except Exception as e:   # noqa: BLE001  单票失败不阻断; 连接断则重连
                miss.append(sym)
                log(f"失败 {sym}: {e}")
                try:
                    api.disconnect()
                except Exception:   # noqa: BLE001
                    pass
                api = connect(ymd)
            if i % 100 == 0:
                log(f"进度 {i}/{len(recs)} 分钟线 {len(bars)} 根 缺 {len(miss)}")
      finally:
        api.disconnect()
      return bars, miss, bad, used, flows

    bars, miss, bad, used, flows = one_pass(recs)
    # 10/16 晚 健壮性 H1: 缺得多(平时个位数)=服务器缺数据 → 换一台只补缺的票; 仍超阈值 → 写已取到的数据但不写 DONE, 退出码 1(Java 记失败, 对账重试)
    tries = {used}
    for _round in range(2):
        if len(miss) <= max(20, len(recs) * 0.05):
            break
        rec_by = {r["symbol"]: r for r in recs}
        log(f"缺 {len(miss)}/{len(recs)} 只超阈值, 换服务器补抓缺的票(已用 {sorted(tries)})")
        try:
            b2, m2, bad2, u2, f2 = one_pass([rec_by[s] for s in miss if s in rec_by], tuple(tries))
        except RuntimeError as e:
            log(f"换服务器失败: {e}")
            break
        tries.add(u2)
        bars += b2
        flows += f2
        bad = [x for x in bad if x in m2] + [x for x in bad2 if x not in bad]
        miss = m2
    write_jsonl(out / "kline_minute.jsonl", bars)
    write_jsonl(out / "tick_flow.jsonl", flows)   # 10/18: 主动买卖(独立文件, Java 不读)
    complete = len(miss) <= max(20, len(recs) * 0.05)
    if complete:
        (out / "DONE_kline_minute").write_text(dt.datetime.now().isoformat())
    mf = out / "manifest.json"
    m = json.loads(mf.read_text("utf-8")) if mf.exists() else {}
    m.setdefault("stages", {})["kline_minute"] = {"symbols": len(recs), "bars": len(bars), "missing": miss[:50],
                                                  "missingCount": len(miss), "badRejected": bad[:50], "badCount": len(bad),
                                                  "finishedAt": dt.datetime.now().isoformat()}
    m["stages"]["watchlist"] = {"count": len(recs), "byReason": cnt}
    mf.write_text(json.dumps(m, ensure_ascii=False, indent=1), "utf-8")
    log(f"{'完成' if complete else '未完成(缺失超阈值, 不写 DONE)'} {day}: 关注集 {len(recs)} 只, 分钟线 {len(bars)} 根, 无数据 {len(miss)} 只(其中校验不过丢弃 {len(bad)} 只), 用时 {(dt.datetime.now() - t0).seconds}s")
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main())
