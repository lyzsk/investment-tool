# -*- coding: utf-8 -*-
"""telegraph_nextday.py — 加红电报点名票"次日"表现(10/23 凌晨用户令: 次日高于买价的概率也是可沉淀的素材)

接 telegraph_validate.py 的逐事件产物(results/inv-stock/test/telegraph/<日>.jsonl: 点名分钟、点名前涨幅 up_to_t、点名时是否已见顶 peaked)
买点 = 点名那一分钟的价格(当日开盘 × (1 + up_to_t)); 次日结果用行情库日线(只用 D+1 已收盘的事件)
算: 次日 开盘 / 最高 / 最低 / 收盘 相对买点的分布; 次日最高 ≥ +1% / +3% / +5% 的概率; "次日挂 +N% 卖、没到收盘卖"的扣费期望
对照: 同期"当天收盘涨停的票、收盘价买"(注意: 封死涨停收盘买不进, 对照组和点名组都偏乐观)
产物: results/inv-stock/test/telegraph/nextday.md(累计, 每次重算)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/test/telegraph_nextday.py
"""
import glob
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "test"), str(ROOT / "scripts" / "market")]
OUT = ROOT / "results" / "inv-stock" / "test" / "telegraph"
FEE = 0.15


def ev(pairs, th):
    out = []
    for ent, (o, h, lo, c) in pairs:
        if o >= ent * (1 + th / 100):
            r = (o / ent - 1) * 100
        elif h >= ent * (1 + th / 100):
            r = th
        else:
            r = (c / ent - 1) * 100
        out.append(r - FEE)
    return round(st.mean(out), 2), f"{sum(x > 0 for x in out) / len(out):.0%}"


def limit_pct(sym, name=""):
    if "ST" in (name or ""):
        return 0.05
    return 0.2 if sym[2:].startswith(("300", "301", "688", "689")) else 0.1


def dist(rows, k):
    xs = sorted(r[k] for r in rows)
    return [round(xs[int(len(xs) * p)], 2) for p in (.25, .5, .75)] if xs else None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    R = collect()
    if not R:
        return print("没有事件")
    rows, pairs, base, sealed, nomin = R
    write_md(rows, pairs, base, sealed, nomin)


def collect():
    """→ (rows 可成交事件[次日开 / 高 / 低 / 收相对买点 %], pairs [(买点, 次日开高低收)], base 对照, sealed 剔除的封死事件, nomin 没分钟数据数)"""
    import manual_backfill as mb
    E = [json.loads(l) for f in sorted(glob.glob(str(OUT / "2026-*.jsonl"))) for l in open(f, encoding="utf-8")]
    E = [e for e in E if e.get("has_min") and e.get("up_to_t") is not None]
    if not E:
        return None
    c = mb.db().cursor()
    c.execute("use investment_market")
    d0 = min(e["D"] for e in E)
    c.execute("select k.symbol, k.trade_date, k.open, k.high, k.low, k.close, k.pre_close from kline_day k join security_master s on s.symbol=k.symbol and s.sec_type='STOCK' "
              "where k.is_deleted=0 and k.trade_date >= %s order by k.symbol, k.trade_date", (d0,))
    K = {}
    for s, d, o, h, lo, cl, pc in c.fetchall():
        if o and cl:
            K.setdefault(s, []).append((str(d), float(o), float(h), float(lo), float(cl), float(pc or 0)))
    # 10/22 23:4x 用户令: 点名时已涨停封死 = 买不进, 剔除后再算概率
    # 买点 = 点名后下一根分钟K(看到电报、一分钟内下单); 这根K 最低价 < 涨停价 = 当时有低于涨停的成交 → 可成交, 买价 = 这根收盘(收在涨停价就按涨停价)
    #        最低价 ≥ 涨停价 = 整分钟封死在板上 → 买不进, 剔除(单独计数)
    rows, pairs, sealed, nomin = [], [], [], 0
    for e in E:
        k = K.get(e["sym"]) or []
        ds = [x[0] for x in k]
        if e["D"] not in ds or ds.index(e["D"]) + 1 >= len(k):
            continue
        i = ds.index(e["D"])
        lim = round(k[i][5] * (1 + limit_pct(e["sym"], e.get("name"))) + 1e-9, 2)
        c.execute("select date_format(bar_time,'%%H:%%i'), low, close from kline_minute where trade_date=%s and symbol=%s and is_deleted=0 and date_format(bar_time,'%%H:%%i') > %s order by bar_time limit 1",
                  (e["D"], e["sym"], e["t"]))
        b = c.fetchone()
        if not b:   # 10/23: 回补缓存(只有每分钟价格 → 低 = 价, 更保守: 那一分钟价格 < 涨停价才算买得进)
            import telegraph_validate as TV
            nxt = next(((tt, pp, pp) for tt, pp, _ in TV.tg_min(e["D"]).get(e["sym"], []) if tt > e["t"]), None)
            b = nxt
        if not b:
            nomin += 1
            continue
        n = k[i + 1]
        if float(b[1]) >= lim - 0.005:
            sealed.append(e["sym"])
            continue
        ent = min(float(b[2]), lim)
        rows.append({"D": e["D"], "t": e.get("t"), "sym": e["sym"], "name": e.get("name"), "up": e.get("up_to_t"), "peaked": e.get("peaked"), "gap": (n[1] / ent - 1) * 100, "hi": (n[2] / ent - 1) * 100, "lo": (n[3] / ent - 1) * 100, "co": (n[4] / ent - 1) * 100})
        pairs.append((ent, n[1:5]))
    base = []   # 对照(可成交): 当天收盘涨 ≥5% 但没封死涨停的票, 收盘价买
    for s, k in K.items():
        if s[:2] not in ("sh", "sz"):
            continue
        lp = limit_pct(s)
        for i in range(len(k) - 1):
            pc = k[i][5]
            if pc and k[i][0] >= d0 and k[i][4] >= pc * 1.05 and k[i][4] < round(pc * (1 + lp) + 1e-9, 2) - 0.005:
                base.append((k[i][4], k[i + 1][1:5]))
    return rows, pairs, base, sealed, nomin


def write_md(rows, pairs, base, sealed, nomin):
    days = sorted({r["D"] for r in rows})
    L = [f"# 加红电报点名票 · 次日表现(累计 {days[0]} ~ {days[-1]}, {len(days)} 个点名日; 可成交事件 {len(rows)} 个)", "",
         f"剔除: 点名后那一分钟封死在涨停板上(买不进) {len(sealed)} 个; 没有分钟数据 {nomin} 个", "",
         "买点 = 点名后下一根分钟K 的收盘(那一分钟有低于涨停价的成交才算买得进); 下表都是相对买点的 %; 扣费 0.15%", "",
         "| 组 | n | 次日开盘 P25/中位/P75 | 次日最高 P25/中位/P75 | 次日最低 中位 | 次日收盘 中位 | 次日最高 ≥+1% | ≥+3% | ≥+5% |", "|---|---|---|---|---|---|---|---|---|"]
    for name, R in (("全部点名", rows), ("点名时还没见顶", [r for r in rows if not r["peaked"]]), ("点名时已见顶", [r for r in rows if r["peaked"]])):
        if R:
            L.append(f"| {name} | {len(R)} | {dist(R, 'gap')} | {dist(R, 'hi')} | {dist(R, 'lo')[1]} | {dist(R, 'co')[1]} | "
                     f"{sum(r['hi'] >= 1 for r in R) / len(R):.0%} | {sum(r['hi'] >= 3 for r in R) / len(R):.0%} | {sum(r['hi'] >= 5 for r in R) / len(R):.0%} |")
    L += ["", "**次日挂 +N% 卖、没到就收盘卖(扣费)**: 期望 / 胜率", "", "| 卖单 | 点名后一分钟买入(可成交) | 对照: 当天收盘涨 ≥5% 未封板、收盘买 |", "|---|---|---|"]
    for th in (1, 2, 3, 5):
        L.append(f"| +{th}% | {ev(pairs, th)} (n={len(pairs)}) | {ev(base, th)} (n={len(base)}) |")
    L += ["", "读法 / 不自信点:",
          "- 已剔除点名后一分钟封死在板上的; 但'那一分钟最低价 < 涨停价'不等于一定排得到(板上反复开封时偏乐观)",
          "- 对照组是同期强势未封板股收盘买, 用来看电报有没有带来额外信息; 两组买点时刻不同(盘中 vs 收盘), 只能粗比",
          "- 样本只有几个交易日, 结论受这段行情影响大; 每天重算累计"]
    (OUT / "nextday.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
