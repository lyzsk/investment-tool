# -*- coding: utf-8 -*-
"""analyze.py — 不吃土豆0 竞价选债规则搜索(10/18 建; 零 token, 零网络, 只读 cache/panel.json)

规则族(全部只用 09:25 前可知信息; 'gap' 类 = 09:25 竞价撮合结果, 当刻可见):
  A 单因子排序: 按某特征降/升序取 top1/top3(含"近 20 日池内正股开盘最高"的旧朴素规则作对照)
  B 成交额龙头: 全市场按 T-1 成交额排名, 可加价位/上市天数过滤
  C 粘性+龙头: 若"粘性集合"(上一个竞价票 / 昨天做过的债 / 近 k 日做过的债)里有债进了 T-1 成交额前 K, 选它; 否则选成交额第 1
  D 打分: log(成交额) + w·[昨天做过] + v·[上个竞价票] + u·gap (小网格)
  E 条件 logit(numpy 手写, 6 特征)作上限参照
评估: 全样本(IS) / 时间切分(前 62 天训练选参, 后 41 天测试) / 逐日前推(walk-forward: 每天只用此前的日子选参)
口径: 默认候选池=库内现存券 ∪ 他做过的 51 只(含已退市); 另报"仅库内"口径(只看他的票在库内的日子, 池子只用库内券)。
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/tudou_select/analyze.py [--json out.json]
"""
import json, math, sys, argparse
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
P = json.loads((HERE / "cache" / "panel.json").read_text(encoding="utf-8"))["panel"]
NTRAIN = 62


def order_by(cands, key, rev=True):
    xs = [c for c in cands if c.get(key) is not None]
    return [c["code"] for c in sorted(xs, key=lambda c: c[key], reverse=rev)]


# ---------------- 规则族 ----------------
def r_single(key, rev=True, flt=None):
    def f(day, cands):
        cs = [c for c in cands if (flt is None or flt(c))]
        return order_by(cs, key, rev)
    return f


def r_amt(pmin=0, amin=0):
    def f(day, cands):
        cs = [c for c in cands if c["pc"] >= pmin and c["age"] >= amin]
        return order_by(cs, "amt1")
    return f


STICKY = {
    "上个竞价票": lambda c: c["is_last_auc"],
    "昨日首笔债": lambda c: c["is_prev_first"],
    "昨日末笔债": lambda c: c["is_last_bond"],
    "昨日做过": lambda c: c["he_k"] == 1,
    "近2日做过": lambda c: c["he_k"] is not None and c["he_k"] <= 2,
    "近5日做过": lambda c: c["he_k"] is not None and c["he_k"] <= 5,
}


def r_sticky(kind, K, pmin=0):
    s = STICKY[kind]
    def f(day, cands):
        cs = [c for c in cands if c["pc"] >= pmin]
        o = sorted(cs, key=lambda c: -c["amt1"])
        top = o[:K]
        st = [c for c in top if s(c)]
        lead = [c["code"] for c in st]
        return lead + [c["code"] for c in o if c["code"] not in lead]
    return f


def r_score(w_y, w_auc, w_gap, w_ret):
    def f(day, cands):
        def sc(c):
            return (math.log(max(c["amt1"], 1)) + w_y * (c["he_k"] == 1) + w_auc * c["is_last_auc"]
                    + w_gap * (c["gap"] or 0) * 100 + w_ret * (c["ret1"] or 0) * 100)
        return [c["code"] for c in sorted(cands, key=lambda c: -sc(c))]
    return f


def naive_pool_stkgap(day, cands):
    """旧朴素规则: 近 20 交易日做过的池子里, 正股开盘缺口最高"""
    cs = [c for c in cands if c["he_k"] is not None and c["he_k"] <= 20 and c.get("s_gap") is not None]
    return order_by(cs, "s_gap")


def build_rules():
    R = {}
    for key, nm in [("amt1", "T-1成交额"), ("amp1", "T-1振幅"), ("ret1", "T-1涨幅"), ("ret5", "5日涨幅"), ("gap", "转债竞价缺口"),
                    ("s_gap", "正股竞价缺口"), ("s_ret1", "正股T-1涨幅"), ("pc", "价位(T-1收)"), ("he_n5", "他近5日RT数")]:
        R[f"A|{nm}↓"] = r_single(key)
    R["A|价位↑(低价优先)"] = r_single("pc", rev=False)
    R["A|5日均额排名"] = r_single("arank5", rev=False)
    R["A|旧朴素:近20日池+正股开盘最高"] = naive_pool_stkgap
    for pmin in (0, 120, 130, 150):
        for amin in (0, 5):
            R[f"B|成交额龙头 价≥{pmin} 上市≥{amin}日"] = r_amt(pmin, amin)
    for kind in STICKY:
        for K in (2, 3, 4, 5, 8):
            R[f"C|{kind}∈额前{K} 否则额第1"] = r_sticky(kind, K)
    for wy in (0, 0.25, 0.5, 1.0):
        for wa in (0, 0.25, 0.5, 1.0):
            for wg in (0, 0.05, 0.1):
                for wr in (0, 0.02):
                    R[f"D|log额+{wy}昨做+{wa}上竞价+{wg}gap+{wr}ret1"] = r_score(wy, wa, wg, wr)
    return R


def hits(rule, days, db_only=False):
    h1 = h3 = n = 0
    per = []
    for x in days:
        cands = x["cands"]
        if db_only:
            if not x["pick_in_db"]:
                continue
            cands = [c for c in cands if c["in_db"]]
        o = rule(x, cands)
        n += 1
        a = o[:1] == [x["pick"]]; b = x["pick"] in o[:3]
        h1 += a; h3 += b
        per.append((x["d"], a, b, o[:3]))
    return h1, h3, n, per


def pct(a, n):
    return f"{a}/{n}={a / n * 100:.0f}%" if n else "-"


# ---------------- 条件 logit ----------------
FE = ["lamt", "lrank", "y", "auc", "gap", "ret1", "lpc", "amp1"]


def fx(c):
    return [math.log(max(c["amt1"], 1)) / 10, -math.log(c["arank1"]), float(c["he_k"] == 1), float(c["is_last_auc"]),
            (c["gap"] or 0) * 10, (c["ret1"] or 0) * 10, math.log(c["pc"]) - 5, (c["amp1"] or 0) * 10]


def clogit_fit(days, l2=0.01, it=3000, lr=0.5):
    Xs = [(np.array([fx(c) for c in x["cands"]]), [c["code"] for c in x["cands"]].index(x["pick"])) for x in days]
    w = np.zeros(len(FE))
    for _ in range(it):
        g = -l2 * w
        for X, y in Xs:
            z = X @ w; z -= z.max(); p = np.exp(z); p /= p.sum()
            g += X[y] - p @ X
        w += lr * g / len(Xs)
    return w


def clogit_rule(w):
    def f(day, cands):
        X = np.array([fx(c) for c in cands])
        return [cands[i]["code"] for i in np.argsort(-(X @ w))]
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    R = build_rules()
    tr, te = P[:NTRAIN], P[NTRAIN:]
    rows = []
    for nm, f in R.items():
        i1, i3, n, _ = hits(f, P)
        t1, t3, nt, _ = hits(f, tr)
        o1, o3, no, _ = hits(f, te)
        d1, d3, nd, _ = hits(f, P, db_only=True)
        rows.append({"rule": nm, "is1": i1, "is3": i3, "n": n, "tr1": t1, "tr3": t3, "te1": o1, "te3": o3, "nte": no, "db1": d1, "db3": d3, "ndb": nd})
    # 时间切分: 在训练段按 top1(并列看 top3, 再并列取规则名短的=更简单)选参
    best_tr = sorted(rows, key=lambda r: (-r["tr1"], -r["tr3"], len(r["rule"])))[:15]
    # walk-forward: 第 t 天(t≥30)只用前 t 天选规则
    names = list(R)
    per_rule = {nm: hits(R[nm], P)[3] for nm in names}
    wf1 = wf3 = wn = 0
    wf_pick = Counter()
    for t in range(30, len(P)):
        sc = {nm: (sum(p[1] for p in per_rule[nm][:t]), sum(p[2] for p in per_rule[nm][:t])) for nm in names}
        b = sorted(names, key=lambda nm: (-sc[nm][0], -sc[nm][1], len(nm)))[0]
        wf_pick[b] += 1
        wf1 += per_rule[b][t][1]; wf3 += per_rule[b][t][2]; wn += 1
    # 条件 logit
    w = clogit_fit(tr)
    c_te = hits(clogit_rule(w), te)
    c_tr = hits(clogit_rule(w), tr)
    w_all = clogit_fit(P)
    c_all = hits(clogit_rule(w_all), P)
    # 粘性/连做统计
    seq = [x["pick"] for x in P]
    runs = []
    cur = 1
    for i in range(1, len(seq)):
        if seq[i] == seq[i - 1]:
            cur += 1
        else:
            runs.append((seq[i - 1], cur)); cur = 1
    runs.append((seq[-1], cur))
    pk = [next(c for c in x["cands"] if c["code"] == x["pick"]) for x in P]
    stick = {"same_as_last_auc": sum(c["is_last_auc"] for c in pk), "traded_T-1": sum(c["he_k"] == 1 for c in pk),
             "traded_le5": sum(c["he_k"] is not None and c["he_k"] <= 5 for c in pk), "traded_le20": sum(c["he_k"] is not None and c["he_k"] <= 20 for c in pk),
             "never_or_gt20": sum(c["he_k"] is None or c["he_k"] > 20 for c in pk),
             "n_days": len(P), "distinct": len(set(seq)), "top_bonds": Counter(x["pick_name"] for x in P).most_common(8),
             "runs_len_dist": sorted(Counter(r[1] for r in runs).items()), "longest": sorted(runs, key=lambda r: -r[1])[:5]}
    # 选中票的 T-1 成交额排名分布 + 分段
    rk = Counter(min(c["arank1"], 6) for c in pk)
    seg = {}
    for lab, lo, hi in [("1月", "2026-01", "2026-02"), ("2月", "2026-02", "2026-03"), ("3月", "2026-03", "2026-04"), ("4月", "2026-04", "2026-05"),
                        ("5-6月", "2026-05", "2026-07"), ("7月", "2026-07", "2026-08"), ("9-10月", "2026-09", "2026-11")]:
        ds = [x for x in P if lo <= x["d"] < hi]
        seg[lab] = (sum(1 for x in ds if next(c for c in x["cands"] if c["code"] == x["pick"])["arank1"] == 1), len(ds),
                    round(float(np.median([x["n_cand"] for x in ds])), 0) if ds else None)
    # 粘性 vs 新票 分开看成交额龙头命中
    amt = R["B|成交额龙头 价≥0 上市≥0日"]
    sub = {}
    for lab, cond in [("昨天做过的", lambda c: c["he_k"] == 1), ("2~20日前做过", lambda c: c["he_k"] is not None and 2 <= c["he_k"] <= 20),
                      ("新票(>20日或从没做过)", lambda c: c["he_k"] is None or c["he_k"] > 20)]:
        ds = [x for x, c in zip(P, pk) if cond(c)]
        h = hits(amt, ds)
        sub[lab] = (h[0], h[1], h[2])
    out = {"rows": rows, "best_tr": best_tr, "wf": (wf1, wf3, wn, wf_pick.most_common(5)), "clogit": {"w_tr": dict(zip(FE, np.round(w, 2).tolist())),
           "tr": c_tr[:3], "te": c_te[:3], "all": c_all[:3], "w_all": dict(zip(FE, np.round(w_all, 2).tolist()))},
           "stick": stick, "rank_dist": sorted(rk.items()), "seg": seg, "sub": sub}
    # ---- 打印 ----
    key_rules = ["B|成交额龙头 价≥0 上市≥0日", "A|旧朴素:近20日池+正股开盘最高", "C|上个竞价票∈额前3 否则额第1", "C|昨日做过∈额前3 否则额第1",
                 "C|昨日做过∈额前4 否则额第1", "C|上个竞价票∈额前4 否则额第1"]
    print(f"日数 {len(P)}  训练 {NTRAIN}({P[0]['d']}~{P[NTRAIN - 1]['d']})  测试 {len(te)}({te[0]['d']}~{te[-1]['d']})")
    print("\n== 全部规则(按全样本 top1 排序前 40) ==")
    for r in sorted(rows, key=lambda r: (-r["is1"], -r["is3"], len(r["rule"])))[:40]:
        print(f"{r['rule'][:58]:60s} IS {pct(r['is1'], r['n'])} top3 {pct(r['is3'], r['n'])} | 训练 {pct(r['tr1'], NTRAIN)} 测试 {pct(r['te1'], r['nte'])} top3 {pct(r['te3'], r['nte'])} | 仅库内 {pct(r['db1'], r['ndb'])} top3 {pct(r['db3'], r['ndb'])}")
    print("\n== 单因子(A 族) ==")
    for r in rows:
        if r["rule"].startswith("A|"):
            print(f"{r['rule']:40s} IS {pct(r['is1'], r['n'])} top3 {pct(r['is3'], r['n'])} | 测试 {pct(r['te1'], r['nte'])} | 仅库内 {pct(r['db1'], r['ndb'])}")
    print("\n== 训练段选出的前 15 ==")
    for r in best_tr:
        print(f"{r['rule'][:58]:60s} 训练 {pct(r['tr1'], NTRAIN)}/{pct(r['tr3'], NTRAIN)} → 测试 {pct(r['te1'], r['nte'])} top3 {pct(r['te3'], r['nte'])}")
    print(f"\n== walk-forward(第31天起每日用历史选规则) top1 {pct(wf1, wn)} top3 {pct(wf3, wn)}; 选中规则 {wf_pick.most_common(5)}")
    print(f"\n== 条件 logit: 训练内 {pct(c_tr[0], c_tr[2])}  测试 {pct(c_te[0], c_te[2])} top3 {pct(c_te[1], c_te[2])}; 全样本拟合 IS {pct(c_all[0], c_all[2])} top3 {pct(c_all[1], c_all[2])}")
    print("   w(train)", out["clogit"]["w_tr"]); print("   w(all)", out["clogit"]["w_all"])
    print("\n== 粘性统计 ==", json.dumps(stick, ensure_ascii=False))
    print("== 选中票 T-1 成交额排名分布(6=≥6) ==", sorted(rk.items()))
    print("== 分段(龙头命中, 天数, 候选池中位数) ==", seg)
    print("== 按新旧票分: 成交额龙头 top1/top3/n ==", sub)
    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
