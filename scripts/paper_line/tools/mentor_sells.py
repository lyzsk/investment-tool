# -*- coding: utf-8 -*-
"""mentor_sells.py — 导师相似卖点(v3 命名查询工具; 零 token, 只读本地; 10/22 晚用户令 "1、2、3 先做")

回答: "我现在拿着一只票, 浮盈 x%、拿了 n 天、今天开盘 g% —— 这位导师历史上同样状态下, 今天卖不卖? 卖的话几点卖、卖在哪、卖完后悔没?"
为什么不只看卖出样本: 只看卖出会把 "拿着没卖" 的同状态日子漏掉, P(卖) 就无从谈起; 所以建 "持仓日面板" = 每个持有日一行, 标 卖 / 没卖
来源(都是本地):
  skills/<导师>-skill/persona/cases_auto.jsonl 卖出行: vwap / sell_kind / result.pnl(按数量 FIFO 配对, mentor_fingerprint 算) / hold_days(交易日)
  行情库 kline_day: 开高低收(补 开盘幅度 / 卖时涨跌 / 卖后走势)
  成本 = 卖出均价 / (1 + pnl) —— 账本无逐笔数量也能还原加权成本; 持有区间 = 卖出日往前 hold_days 个交易日
面板一行(持有第 t 天, 都是 t 日开盘时已知): pnl_prev = 昨收浮盈, days = 已持有交易日, gap = 今开相对昨收; 标签 sold = 当天有没有卖
卖出样本另记: 卖出时刻 / 卖价相对开盘 / 卖价相对昨收 / 卖出类型 / 卖后当日收盘、3 日内最高、5 日收盘(相对卖价) → "卖飞" 程度
日内 T(当天买当天卖, hold_days=0)单独一组: 只回答 "开盘后多快卖、卖在开盘上方多少"
用法:
  python mentor_sells.py --skill liuyiqing --date 2026-10-23 --pnl 5.2 --days 2 [--gap -1.5] [--asset stock|cb] [--k 40]
  python mentor_sells.py --skill buchitudou0 --date 2026-10-23 --intraday [--gap 1.2]
  python mentor_sells.py --skill liuyiqing --stats          (面板规模自检)
"""
import argparse
import bisect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))


def sym(code):
    return ("sh" if code.startswith(("6", "9", "11", "5")) else "sz") + code


def asset(code):
    return "cb" if code.startswith(("11", "12")) else "etf" if code.startswith(("5", "15", "16")) else "stock"


def load_kline(codes):
    import manual_backfill as mb
    cur = mb.db().cursor()
    cur.execute("use investment_market")
    syms = sorted({sym(c) for c in codes})
    K = {}
    for i in range(0, len(syms), 400):
        part = syms[i:i + 400]
        cur.execute(f"select symbol, trade_date, open, high, low, close from kline_day where is_deleted=0 and trade_date >= '2025-08-01' "
                    f"and symbol in ({','.join(['%s'] * len(part))}) order by symbol, trade_date", part)
        for s, d, o, h, l, c in cur.fetchall():
            if o and c:
                K.setdefault(s[2:], []).append((str(d), float(o), float(h), float(l), float(c)))
    return K


def minute_day(code, d):
    """downloads/quotes/cb/minute/<code>/<d>.json(cb_minute_backfill 逐笔合成) → ([(昨, 昨收×4), (d, 开高低收)], 1); 没有 → ([], 0)"""
    f = ROOT / "downloads" / "quotes" / "cb" / "minute" / code / f"{d}.json"
    if not f.exists():
        return [], 0
    j = json.loads(f.read_text(encoding="utf-8")) or {}
    bars, pc = j.get("bars") or [], j.get("prev")
    if not bars or not pc:
        return [], 0
    o = j.get("open_auction") or bars[0]["o"]
    return [("", pc, pc, pc, pc), (d, o, max(b["h"] for b in bars), min(b["l"] for b in bars), bars[-1]["c"])], 1


def sells_of(skill):
    f = ROOT / "skills" / f"{skill}-skill" / "persona" / "cases_auto.jsonl"
    return [r for r in (json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()) if r.get("side") == "卖" and r.get("vwap")]


def build(skill):
    """→ (panel 持仓日面板, sold 卖出样本, intra 日内T 样本); 只依赖本地文件 + 行情库"""
    S = sells_of(skill)
    K = load_kline({str(r["code"]) for r in S})
    panel, sold, intra = {}, [], []
    for r in S:
        code, d = str(r["code"]), r["date"]
        k = K.get(code) or []
        ds = [x[0] for x in k]
        i = bisect.bisect_left(ds, d)
        if i >= len(k) or ds[i] != d or i < 1:
            k, i = minute_day(code, d)   # 退市转债行情库没日线 → 用逐笔合成的分钟线兜底(只有当天, 卖后走势为空)
            if not k:
                res = r.get("result") or {}
                if res.get("hold_days") == 0 or res.get("same_day"):   # 日内 T 没行情也留: 卖出时刻 / 盈亏照样能统计, 开盘相关字段为空
                    intra.append({"code": code, "name": r.get("name"), "d": d, "t": r.get("time", "")[:5], "kind": r.get("sell_kind"), "asset": asset(code),
                                  "pnl": None if res.get("pnl") is None else round(res["pnl"] * 100, 2), "days": 0, "gap": None, "vs_open": None,
                                  "vs_prev": None, "r_close": None, "max3": None, "r5": None})
                continue
        o, h, l, c = k[i][1:]
        pc = k[i - 1][4]
        res = r.get("result") or {}
        pnl, hd = res.get("pnl"), res.get("hold_days")
        v = r["vwap"]
        after = {"r_close": round((c / v - 1) * 100, 2),
                 "max3": round((max(x[2] for x in k[i + 1:i + 4]) / v - 1) * 100, 2) if i + 1 < len(k) else None,
                 "r5": round((k[i + 5][4] / v - 1) * 100, 2) if i + 5 < len(k) else None}
        ev = {"code": code, "name": r.get("name"), "d": d, "t": r.get("time", "")[:5], "kind": r.get("sell_kind"), "asset": asset(code),
              "pnl": None if pnl is None else round(pnl * 100, 2), "days": hd, "gap": round((o / pc - 1) * 100, 2),
              "vs_open": round((v / o - 1) * 100, 2), "vs_prev": round((v / pc - 1) * 100, 2), **after}
        if hd == 0 or res.get("same_day"):
            intra.append(ev)
            continue
        if pnl is None or hd is None or hd < 1 or i - hd < 0:
            continue
        sold.append(ev)
        cost = v / (1 + pnl)
        for t in range(i - hd + 1, i + 1):   # 买入次日 .. 卖出日; 每个持有日在开盘时的状态
            key = (code, k[t][0])
            row = {"code": code, "d": k[t][0], "asset": asset(code), "days": t - (i - hd), "pnl_prev": round((k[t - 1][4] / cost - 1) * 100, 2),
                   "gap": round((k[t][1] / k[t - 1][4] - 1) * 100, 2), "sold": t == i}
            if key not in panel or row["sold"]:
                panel[key] = row
    return list(panel.values()), sold, intra


_CACHE = {}


def data(skill):
    if skill not in _CACHE:
        _CACHE[skill] = build(skill)
    return _CACHE[skill]


def q(xs, p):
    xs = sorted(x for x in xs if x is not None)
    return round(xs[min(len(xs) - 1, int(len(xs) * p))], 2) if xs else None


def tbucket(t):
    return "09:25~09:31" if t <= "09:31" else "09:31~09:45" if t <= "09:45" else "09:45~10:30" if t <= "10:30" else "10:30~11:30" if t <= "11:30" else "13:00~14:30" if t <= "14:30" else "14:30 后"


def mix(xs):
    out = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    n = len(xs) or 1
    return {a: f"{b}({b / n:.0%})" for a, b in sorted(out.items(), key=lambda z: -z[1])}


def query(skill, D, pnl, days, gap=None, kind=None, k=40):
    """持仓状态 → 导师历史同状态的 P(当天卖) + 卖的样子; 只用 D 之前的样本"""
    panel, sold, _ = data(skill)
    P = [r for r in panel if r["d"] < D and (kind is None or r["asset"] == kind)]
    if not P:
        return {"err": f"{skill} 在 {D} 前没有可用持仓日样本"}
    # 距离: 浮盈每 3 个点 ≈ 持有天数差 log2 一档 ≈ 开盘幅度每 2 个点
    import math
    def dist(r):
        dd = ((r["pnl_prev"] - pnl) / 3) ** 2 + (math.log2(1 + r["days"]) - math.log2(1 + days)) ** 2
        if gap is not None:
            dd += ((r["gap"] - gap) / 2) ** 2
        return dd ** 0.5
    nb = sorted(P, key=dist)[:k]
    sold_keys = {(r["code"], r["d"]) for r in nb if r["sold"]}
    sx = [s for s in sold if (s["code"], s["d"]) in sold_keys]
    out = {"skill": skill, "D": D, "此刻状态": {"昨收浮盈%": pnl, "已持有交易日": days, "今开幅度%": gap, "品种": kind},
           "样本": f"持仓日面板 {len(P)} 行(其中卖出日 {sum(r['sold'] for r in P)}), 取最像的 {len(nb)} 行",
           "最像的这些日子里 当天卖出比例": f"{len(sold_keys) / len(nb):.0%}",
           "邻居范围": {"浮盈": (q([r['pnl_prev'] for r in nb], .1), q([r['pnl_prev'] for r in nb], .9)), "持有天数": (min(r["days"] for r in nb), max(r["days"] for r in nb))}}
    if sx:
        out["卖的那些次"] = {"n": len(sx), "卖出类型": mix([s["kind"] or "?" for s in sx]), "卖出时段": mix([tbucket(s["t"]) for s in sx]),
                          "卖价相对开盘 P25/中位/P75": [q([s["vs_open"] for s in sx], p) for p in (.25, .5, .75)],
                          "卖价相对昨收 中位": q([s["vs_prev"] for s in sx], .5),
                          "卖后: 当日收盘相对卖价 中位": q([s["r_close"] for s in sx], .5),
                          "卖后: 3 日内最高相对卖价 中位 / ≥5% 比例": (q([s["max3"] for s in sx], .5),
                                                         f"{sum(1 for s in sx if (s['max3'] or 0) >= 5) / len(sx):.0%}"),
                          "卖后: 5 日收盘相对卖价 中位": q([s["r5"] for s in sx], .5),
                          "最像的 5 次": [f"{s['d']} {s['t']} {s['name']}({s['kind']}) 卖出盈亏{s['pnl']}% 持{s['days']}天 开{s['gap']:+}% 卖在开盘{s['vs_open']:+}% → 3日最高{s['max3']}%"
                                       for s in sorted(sx, key=lambda s: dist({**s, 'pnl_prev': s['pnl']}))[:5]]}
    return out


def query_intraday(skill, D, gap=None, kind=None, k=40):
    """日内 T(当天买当天卖): 开盘后多快卖、卖在开盘上方多少; gap 给了就按开盘幅度找最像的"""
    _, _, intra = data(skill)
    X = [s for s in intra if s["d"] < D and (kind is None or s["asset"] == kind)]
    if gap is not None:
        X = sorted((s for s in X if s["gap"] is not None), key=lambda s: abs(s["gap"] - gap))[:k]
    if not X:
        return {"err": f"{skill} 在 {D} 前没有日内 T 样本"}
    return {"skill": skill, "D": D, "今开幅度%": gap, "n": len(X), "开盘幅度范围": (q([s['gap'] for s in X], .1), q([s['gap'] for s in X], .9)),
            "卖出时段": mix([tbucket(s["t"]) for s in X]), "卖价相对开盘 P25/中位/P75": [q([s["vs_open"] for s in X], p) for p in (.25, .5, .75)],
            "单笔盈亏 中位 / 胜率": (q([s["pnl"] for s in X], .5), f"{sum(1 for s in X if (s['pnl'] or 0) > 0) / len(X):.0%}"),
            "卖后当日收盘相对卖价 中位": q([s["r_close"] for s in X], .5)}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--date", default="9999-12-31")
    ap.add_argument("--pnl", type=float)
    ap.add_argument("--days", type=int)
    ap.add_argument("--gap", type=float)
    ap.add_argument("--asset", choices=["stock", "cb", "etf"])
    ap.add_argument("--k", type=int, default=40)
    ap.add_argument("--intraday", action="store_true")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    if a.stats:
        panel, sold, intra = data(a.skill)
        raw = len(sells_of(a.skill))
        print(json.dumps({"卖出行": raw, "隔日卖出(进面板)": len(sold), "日内T": len(intra), "丢弃(无行情 / 无盈亏)": raw - len(sold) - len(intra),
                          "持仓日面板": len(panel), "其中卖出日": sum(r["sold"] for r in panel)}, ensure_ascii=False))
        return
    out = query_intraday(a.skill, a.date, a.gap, a.asset, a.k) if a.intraday else query(a.skill, a.date, a.pnl, a.days, a.gap, a.asset, a.k)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
