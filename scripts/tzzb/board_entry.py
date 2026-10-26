# -*- coding: utf-8 -*-
"""board_entry.py — 导师买点 × 当天板型(10/25 用户: 学了板的思维和 K 线思维, 给导师指纹加打法, 让机械层多选项; 零 token, 只读)

每个买入事件(导师 × 日 × 票, 取当天第一笔买的时刻和全部买的均价)按当天怎么走 + 买在哪一段, 分成:
  一字排板    当天一字(开盘 = 最低 = 涨停价), 买在涨停价
  T字板买     开盘即涨停, 盘中开板(最低 < 涨停价)再回封; 买在开板期间或回封时
  厂字板买    开盘没涨停, 一路拉板封住没开过(开盘后最低 ≥ 开盘 − 1.5%); 买在封板前(半路)或封板时(打板)
  烂板回封买  封住前开板 ≥ 2 次(要分钟路径); 买在回封 / 开板期间
  回封板买    开板 1 次后回封
  炸板买      当天封过涨停后开板, 买在开板后的涨停价下方(收盘回封 = 炸板接成功, 没回封 = 炸板接失败)
  深V低吸     当天最低 ≤ −5%(20cm 票 −8%)、收盘较最低回升 ≥ 6%, 买价在当天区间下 30%
  反包板买    前一天跌 ≤ −5% / 炸板 / 跌停, 当天封住涨停
  打板(其他)  买在涨停价但不属以上
  非板日      当天没碰涨停, 也不是深V
口径: 有分钟路径(downloads/quotes/stock/minute_path, 8/06 起部分票; 行情库 kline_minute 10/09 起)就按分钟判开板次数和买的时刻在哪一段;
      没有就按日线降级(开板次数未知 → 回封统称"回封(日线口径)")
结果: 每类 笔数 / 占比 + 买入后 当天收盘 / 次日最高 / 次日收盘 / T+2 收盘(都相对买价)的中位 + 胜率(次日收盘 > 买价)
用法: python board_entry.py <ledger> [--md]    · 被 mentor_fingerprint.write_fingerprint 调 section(ledger) 写进 fingerprint.md 第十节
"""
import bisect
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "backfill_bilibili")]
MP = ROOT / "downloads" / "quotes" / "stock" / "minute_path"
ORDER = ["一字排板", "T字板买", "厂字板买", "烂板回封买", "回封板买", "回封(日线口径)", "炸板买·回封", "炸板买·没回封", "炸板日(日线口径)", "打板·没封住", "深V低吸", "反包板买", "打板(其他)", "非板日"]
_MP = {}


def cur():
    import manual_backfill as mb
    return mb.db().cursor()


def sym(code):
    return ("sh" if code.startswith(("6", "9", "11", "5")) else "sz") + code


def lim(code, name=""):
    if "ST" in (name or "").upper():
        return 0.05
    return 0.20 if code.startswith(("300", "301", "688", "689")) else 0.10


def zt(pc, p):
    return round(pc * (1 + p) + 1e-9, 2)


def minute(code, d):
    """当天 1 分钟收盘价序列(240 点 + 时刻) → [(HH:MM, p)]; 先 minute_path 存档, 再行情库"""
    if d not in _MP:
        f = MP / f"{d}.jsonl"
        m = {}
        if f.exists():
            for l in f.open(encoding="utf-8"):
                try:
                    j = json.loads(l)
                    m[j["code"]] = j["p"]
                except (ValueError, KeyError):
                    continue
        _MP[d] = m
    p = _MP[d].get(code)
    if p:
        ts = [f"{9 + (30 + i) // 60:02d}:{(30 + i) % 60:02d}" if i < 120 else f"{13 + (i - 120) // 60:02d}:{(i - 120) % 60:02d}" for i in range(len(p))]
        return list(zip(ts, p))
    c = cur()
    c.execute("select bar_time, close from investment_market.kline_minute where symbol=%s and trade_date=%s and is_deleted=0 order by bar_time", (sym(code), d))
    r = [(str(t)[11:16], float(v)) for t, v in c.fetchall() if v]
    return r if len(r) >= 120 else None


def classify(code, name, day, prev, t_buy, px):
    """day / prev = (o, h, l, c, pc); t_buy 'HH:MM'; → (标签, 是否分钟口径)"""
    o, h, l_, c, pc = day[:5]
    p = lim(code, name)
    up = zt(pc, p)
    at = lambda x: x >= up - 0.005   # noqa: E731
    sealed, touched = at(c), at(h)
    prev_bad = False
    if prev:
        po, ph, pl, pcl, ppc = prev[:5]
        pup, pdn = zt(ppc, p), round(ppc * (1 - p) + 1e-9, 2)
        prev_bad = (pcl / ppc - 1) <= -0.05 or (ph >= pup - 0.005 and pcl < pup - 0.005) or pcl <= pdn + 0.005
    m = minute(code, day[5]) if len(day) > 5 else None
    if sealed and o >= up - 0.005 and l_ >= up - 0.005:
        return "一字排板", bool(m)
    if prev_bad and sealed:
        return "反包板买", bool(m)
    if touched:
        if m:
            seq = [at(x) for _, x in m]
            first = next((i for i, z in enumerate(seq) if z), None)
            opens = sum(1 for a, b in zip(seq, seq[1:]) if a and not b)
            ib = max(0, bisect.bisect_right([t for t, _ in m], t_buy) - 1)
            after_open = first is not None and ib > first and any(not z for z in seq[first:ib + 1])
            if o >= up - 0.005:
                return "T字板买", True
            if not sealed and at(px):
                return "打板·没封住", True
            if not sealed and after_open and px < up - 0.005:
                return "炸板买·没回封", True
            if sealed and after_open and px < up - 0.005:
                return "炸板买·回封", True
            if sealed and opens >= 2:
                return "烂板回封买", True
            if sealed and opens == 1:
                return "回封板买", True
            if sealed and opens == 0 and (o - l_) / pc <= 0.015:
                return "厂字板买", True
            if at(px):
                return "打板(其他)", True
        else:
            if o >= up - 0.005:
                return "T字板买", False
            if sealed and (o - l_) / pc <= 0.015:
                return "厂字板买", False
            if sealed:
                return "回封(日线口径)", False
            if at(px):
                return "打板·没封住", False
            return "炸板日(日线口径)", False   # 没分钟路径分不清是开板后接的还是封板前半路买的
    deep = -0.08 if p > 0.15 else -0.05
    if (l_ / pc - 1) <= deep and (c - l_) / pc >= 0.06 and h > l_ and (px - l_) / (h - l_) <= 0.3:
        return "深V低吸", bool(m)
    return "非板日", bool(m)


def events(ledger):
    """导师全部买入事件(日 × 票): 第一笔买时刻 + 买均价 + 当天 / 前一天日线 + 之后 2 天"""
    c = cur()
    c.execute("select date(record_time), time(record_time), stock_code, stock_name, price, qty from investment_tool.tzzb_record where record_type='bs_leg' and is_deleted=0 "
              "and ledger=%s and side like '%%买%%' order by record_time", (ledger,))
    ev = {}
    for d, t, code, nm, px, q in c.fetchall():
        code = str(code or "")
        if len(code) != 6 or not code[:1] in "036" or code.startswith(("11", "12", "15", "5")):
            continue   # 只看股票(转债 / ETF 没有涨停板型)
        k = (str(d), code)
        e = ev.setdefault(k, {"d": str(d), "code": code, "name": nm or "", "t": str(t).zfill(8)[:5], "v": 0.0, "q": 0})
        e["v"] += float(px or 0) * float(q or 0)
        e["q"] += float(q or 0)
    out = list(ev.values())
    by = {}
    for e in out:
        by.setdefault(e["code"], []).append(e)
    for code, es in by.items():
        c.execute("select trade_date, open, high, low, close, pre_close from investment_market.kline_day where symbol=%s and is_deleted=0 and trade_date>=%s order by trade_date",
                  (sym(code), min(e["d"] for e in es)))
        K = [(str(a), *(float(x or 0) for x in r)) for a, *r in c.fetchall()]
        ix = {k[0]: i for i, k in enumerate(K)}
        for e in es:
            i = ix.get(e["d"])
            if i is None or not e["q"]:
                continue
            e["px"] = e["v"] / e["q"]
            o, h, l_, cl, pc = K[i][1:]
            if not pc:
                continue
            e["day"] = (o, h, l_, cl, pc, e["d"])
            e["prev"] = K[i - 1][1:] if i >= 1 else None
            e["r0"] = (cl / e["px"] - 1) * 100
            if i + 1 < len(K):
                e["h1"] = (K[i + 1][2] / e["px"] - 1) * 100
                e["r1"] = (K[i + 1][4] / e["px"] - 1) * 100
            if i + 2 < len(K):
                e["r2"] = (K[i + 2][4] / e["px"] - 1) * 100
    return [e for e in out if e.get("day")]


def stats(ledger):
    E = events(ledger)
    for e in E:
        e["cls"], e["min"] = classify(e["code"], e["name"], e["day"], e["prev"], e["t"], e["px"])
    return E


def section(ledger):
    """fingerprint.md 第十节(Markdown 行列表)"""
    E = stats(ledger)
    L = ["## 十、板型买点(当天怎么走 × 买在哪一段; 10/25 新增, 零 token, scripts/tzzb/board_entry.py)", ""]
    if not E:
        return L + ["没有股票买入记录。", ""]
    n = len(E)
    nm = sum(1 for e in E if e["min"])
    L.append(f"> 买入事件 {n}(日 × 票, 只算股票); 有分钟路径的 {nm}({nm / n:.0%}, 开板次数和买点时段按分钟判), 其余按日线降级。收益都相对买入均价, 不扣费。")
    L.append("")
    L.append("| 板型买点 | 笔数 | 占比 | 当天收盘 中位 | 次日最高 中位 | 次日收盘 中位 | 次日收盘 > 买价 | T+2 收盘 中位 | 最近一笔 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    med = lambda xs: f"{st.median(xs):+.1f}%" if xs else "—"   # noqa: E731
    for k in ORDER:
        g = [e for e in E if e["cls"] == k]
        if not g:
            continue
        r1 = [e["r1"] for e in g if "r1" in e]
        last = max(g, key=lambda e: e["d"])
        L.append(f"| {k} | {len(g)} | {len(g) / n:.0%} | {med([e['r0'] for e in g])} | {med([e['h1'] for e in g if 'h1' in e])} | {med(r1)} | "
                 f"{(sum(1 for x in r1 if x > 0) / len(r1)):.0%} | {med([e['r2'] for e in g if 'r2' in e])} | {last['name']} {last['d'][5:]} {last['t']} |" if r1 else
                 f"| {k} | {len(g)} | {len(g) / n:.0%} | {med([e['r0'] for e in g])} | — | — | — | — | {last['name']} {last['d'][5:]} {last['t']} |")
    top = sorted(((k, sum(1 for e in E if e["cls"] == k)) for k in ORDER if k != "非板日"), key=lambda x: -x[1])
    top = [f"{k} {v}" for k, v in top if v][:3]
    L.append("")
    L.append(f"板型打法前 3: {' / '.join(top) or '无'}(非板日 {sum(1 for e in E if e['cls'] == '非板日') / n:.0%})")
    L.append("定义: 一字排板 / T字板(一字开板再回封)/ 厂字板(开盘后一路拉板没开过)/ 烂板回封(开板 ≥2 次再封)/ 回封板(开 1 次)/ 炸板买(封过之后开板, 买在涨停价下方; 按收盘回没回封分两类; 没分钟路径的记「炸板日(日线口径)」)/ 打板·没封住(买在涨停价, 收盘没封住)/ 深V低吸(最低 ≤ −5%, 收盘较最低回升 ≥ 6%, 买在当天区间下 30%)/ 反包板(前一天跌 ≤ −5% / 炸板 / 跌停, 当天封板)")
    L.append("")
    return L


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("\n".join(section(sys.argv[1])))
