# -*- coding: utf-8 -*-
"""ontology/case_retrieval_k3.py — 重点案例 K3 的补充统计(只读): 不吃土豆0 在"正在做的那只转债"上, 每个交易日竞价买没买 × 转债 / 正股开盘方向
为什么要补: 案例库只收"做了的"(买 / 卖), 没收"那天他没做"; 问"双双低开要不要竞价买", 只看买入案例会有选择偏差
"在做"= 这只转债在他账本里前后 5 个交易日内有成交; 竞价买 = 09:25:00 的买腿; 结果 = 竞价买价 → 当天第一笔卖价
用法: python case_retrieval_k3.py [截止日 D(不含)]   → 打印 markdown 表
"""
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ontology"))
import case_retrieval as CR   # noqa: E402


def main(D="2026-10-23"):
    c = CR.cur()
    c.execute("select date(record_time), time(record_time), stock_code, side, price, qty from investment_tool.tzzb_record where record_type='bs_leg' and is_deleted=0 "
              "and ledger='buchitudou0' and record_time < %s order by record_time", (D,))
    L = [(str(d), str(t).zfill(8), code, "买" in sd, float(px), float(q)) for d, t, code, sd, px, q in c.fetchall()]
    cbm = CR.cb_map()
    by = collections.defaultdict(list)
    for x in L:
        by[x[2]].append(x)
    rows = []
    for code, xs in by.items():
        if code[:2] not in ("11", "12"):
            continue
        sc = cbm.get(code)
        K = CR.load_kline(c, [code] + ([sc] if sc else []), "2025-12-01")
        kc, ks = K.get(code, []), {k[0]: k for k in K.get(sc, [])} if sc else {}
        days = [k[0] for k in kc]
        tdays = sorted({x[0] for x in xs})
        for j, k in enumerate(kc):
            d = k[0]
            if d >= D:
                break
            near = [t for t in tdays if abs(days.index(t) - j) <= 5] if True else []
            if not near:
                continue
            g = (k[1] / k[5] - 1) * 100
            s = ks.get(d)
            sg = (s[1] / s[5] - 1) * 100 if s else None
            day = [x for x in xs if x[0] == d]
            ab = [x for x in day if x[3] and x[1] == "09:25:00"]
            res = None
            if ab:
                sell = next((x for x in day if not x[3] and x[1] > "09:25:00"), None)
                res = (sell[4] / ab[0][4] - 1) * 100 if sell else None
            rows.append({"code": code, "d": d, "g": g, "sg": sg, "auc": bool(ab), "traded": bool(day), "res": res, "pc": k[5]})
    cell = collections.defaultdict(list)
    for r in rows:
        if r["sg"] is None:
            continue
        key = ("转债低开" if r["g"] < 0 else "转债平高开") + " × " + ("正股低开" if r["sg"] < 0 else "正股平高开")
        cell[key].append(r)
    out = [f"| 格子(截至 {D} 前, 不吃土豆0 在做的转债) | 交易日 n | 竞价买了 | 竞价买率 | 竞价买 → 当天首笔卖 均值 / 最差 / 最好 |", "|---|---|---|---|---|"]
    for key in sorted(cell):
        v = cell[key]
        a = [r for r in v if r["auc"]]
        rs = [r["res"] for r in a if r["res"] is not None]
        out.append(f"| {key} | {len(v)} | {len(a)} | {len(a) / len(v):.0%} | " + (f"n={len(rs)} 均{sum(rs) / len(rs):+.2f}% 最差{min(rs):+.2f}% 最好{max(rs):+.2f}%" if rs else "-") + " |")
    both = [r for r in cell.get("转债低开 × 正股低开", [])]
    out.append("")
    out.append("双双低开的日子(最近 15 个): " + "; ".join(f"{r['d'][5:]} {r['code']} 债{r['g']:+.1f}/股{r['sg']:+.1f} " + (f"竞价买→{r['res']:+.2f}%" if r["auc"] and r["res"] is not None else "竞价买" if r["auc"] else "没竞价买" + ("(当天有别的成交)" if r["traded"] else ""))
                                                   for r in both[-15:]))
    big = [r for r in both if r["g"] <= -3 and r["sg"] <= -3]
    a = [r for r in big if r["auc"]]
    rs = [r["res"] for r in a if r["res"] is not None]
    out.append(f"其中双双低开 ≥3%: n={len(big)}, 竞价买 {len(a)}" + (f", 结果 均{sum(rs) / len(rs):+.2f}% 最差{min(rs):+.2f}%" if rs else ""))
    print("\n".join(out))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(*(sys.argv[1:2]))
