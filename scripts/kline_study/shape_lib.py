# -*- coding: utf-8 -*-
"""kline_study/shape_lib.py — K 线类库第一版(10/28 晚用户提: 图只当入口, 沉淀数字 + 用户的话; 零 token, anaconda)

① 形状向量: 强势异动票(scen_v2 票型 0~7: 连板中 / 首板 / 炸板 / 断板 / 跌停 / 跌停失败 / 大涨 / 大跌)的每个 票 × 截止日,
   取近 10 根日 K 的 开 / 高 / 低 / 收(相对截止日收盘 %, 再除以本票 ATR14%)= 40 维; 只用截止日及以前(不偷看)
② 形状拓扑: 标准化 → PCA 12 维 → KMeans K 个「形态族」; 每族: 样本数 / 票型构成 / 中心形状(10 根中位 K 线)/ 次日走法分布 / 次日收 · 最高分布(全期 · 近 60 个交易日)
③ 走势拓扑: 同一只票相邻两个交易日都在库里 → 族 A → 族 B 转移计数(只记 n ≥ 30 的边)
④ 用户案例: results/kline/cases.jsonl(用户发过截图的 票 × 截止日)→ 落在哪个族 + 同族最像的历史样本
产物: results/kline/_shape/{vec.parquet, families.json} + skills/market-skill/persona/kline_families.md(给人看, 等用户命名)
用法: C:/Users/admin/anaconda3/python.exe -X utf8 scripts/kline_study/shape_lib.py [--k 40]
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FEAT = ROOT / "results" / "kline" / "_scen_v2" / "feat.parquet"
OUT = ROOT / "results" / "kline" / "_shape"
MD = ROOT / "skills" / "market-skill" / "persona" / "kline_families.md"
TYPES = ["连板中", "首板", "炸板", "断板", "跌停", "跌停失败", "大涨", "大跌", "箱体震荡", "趋势"]
WALK = ["涨停", "冲高A杀", "高开低走", "单边上涨", "震荡", "深V", "单边下跌", "跌停"]   # = scen_v2_feat.WAYS(y1 编码顺序)
N = 10


def build_vec():
    cols = ["symbol", "trade_date", "open", "high", "low", "close", "atr_pct", "typ", "y1", "p1c", "p1h", "p1l"]
    df = pd.read_parquet(FEAT, columns=cols).sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    df = df[~df["symbol"].str[2:4].isin(["11", "12"])]
    g = df.groupby("symbol", sort=False)
    sh = {}
    for k in range(N):
        for c in ("open", "high", "low", "close"):
            sh[f"{c}_{k}"] = g[c].shift(k)
    S = pd.DataFrame(sh)
    keep = (df["typ"] <= 7) & S[f"close_{N - 1}"].notna() & (df["atr_pct"] > 0)
    S, D = S[keep], df[keep]
    base = D["close"].values[:, None]
    atr = D["atr_pct"].values[:, None]
    X = np.stack([((S[f"{c}_{k}"].values[:, None] / base - 1) * 100 / atr)[:, 0] for k in range(N - 1, -1, -1) for c in ("open", "high", "low", "close")], axis=1).astype("float32")
    X = np.clip(X, -8, 8)
    meta = D[["symbol", "trade_date", "typ", "y1", "p1c", "p1h", "p1l", "atr_pct"]].reset_index(drop=True)
    return X, meta


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=40)
    a = ap.parse_args()
    from sklearn.cluster import MiniBatchKMeans
    from sklearn.decomposition import PCA
    X, meta = build_vec()
    print("样本", X.shape)
    pca = PCA(12, random_state=0).fit(X)
    Z = pca.transform(X)
    km = MiniBatchKMeans(a.k, random_state=0, batch_size=8192, n_init=5).fit(Z)
    meta["fam"] = km.labels_
    meta["d2"] = ((Z - km.cluster_centers_[km.labels_]) ** 2).sum(1)
    OUT.mkdir(parents=True, exist_ok=True)
    pd.concat([meta, pd.DataFrame(X, columns=[f"x{i}" for i in range(X.shape[1])])], axis=1).to_parquet(OUT / "vec.parquet")
    dates = sorted(meta["trade_date"].unique())
    recent = dates[-60] if len(dates) >= 60 else dates[0]
    allw = meta["y1"].value_counts(normalize=True)
    fams = {}
    for f in range(a.k):
        m = meta[meta["fam"] == f]
        Xf = X[meta["fam"].values == f]
        shape = np.median(Xf, axis=0).reshape(N, 4)
        def dist(mm):
            mm = mm[mm["y1"] >= 0]
            if not len(mm):
                return None
            w = mm["y1"].value_counts(normalize=True)
            return {"n": int(len(mm)), "走法%": {WALK[int(i)] if 0 <= int(i) < len(WALK) else str(i): round(float(v) * 100, 1) for i, v in w.sort_values(ascending=False).head(4).items()},
                    "次日收 P25/中/P75": [round(float(x), 2) for x in mm["p1c"].quantile([.25, .5, .75])],
                    "次日最高 P25/中/P75": [round(float(x), 2) for x in mm["p1h"].quantile([.25, .5, .75])]}
        lift = {WALK[int(i)] if 0 <= int(i) < len(WALK) else str(i): round(float(v / allw.get(i, 1)), 2) for i, v in m["y1"].value_counts(normalize=True).items() if allw.get(i)}
        fams[f] = {"n": int(len(m)), "票型": {TYPES[int(t)]: int(c) for t, c in Counter(m["typ"]).most_common(3)}, "中心形状(近10根 o/h/l/c, 单位 ATR)": shape.round(2).tolist(),
                   "全期": dist(m), "近60日": dist(m[m["trade_date"] >= recent]), "相对全体倍数(走法)": dict(sorted(lift.items(), key=lambda x: -x[1])[:3])}
    trans = Counter()
    mm = meta.sort_values(["symbol", "trade_date"])
    di = {d: i for i, d in enumerate(dates)}
    s_, d_, f_ = mm["symbol"].values, mm["trade_date"].map(di).values, mm["fam"].values
    for i in range(1, len(mm)):
        if s_[i] == s_[i - 1] and d_[i] == d_[i - 1] + 1:
            trans[(int(f_[i - 1]), int(f_[i]))] += 1
    tr = {f"{x}->{y}": n for (x, y), n in trans.most_common() if n >= 30}
    cases = []
    cf = ROOT / "results" / "kline" / "cases.jsonl"
    if cf.exists():
        key = {(r.symbol[2:], r.trade_date): (int(r.fam), i) for i, r in enumerate(meta[["symbol", "trade_date", "fam"]].itertuples())}
        for l in cf.read_text(encoding="utf-8").splitlines():
            c = json.loads(l)
            k_ = key.get((c["code"], c["截止日"]))
            if k_:
                cases.append({"code": c["code"], "name": c.get("name"), "d": c["截止日"], "fam": k_[0]})
    json.dump({"k": a.k, "N": N, "recent_from": recent, "families": fams, "transitions": tr, "user_cases": cases}, open(OUT / "families.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    by = {}
    for c in cases:
        by.setdefault(c["fam"], []).append(f"{c['name']}({c['code']}) {c['d'][5:]}")
    L = [f"# K 线形态族(第一版, 10/28 晚; 等用户命名)", "",
         f"> 脚本 `scripts/kline_study/shape_lib.py`。样本 = 强势异动票(连板中 / 首板 / 炸板 / 断板 / 跌停 / 跌停失败 / 大涨 / 大跌)每个 票 × 截止日, 近 {N} 根日 K 按截止收盘 + ATR 归一 → 聚成 {a.k} 族; 共 {len(meta)} 个样本, 2024-01 起。",
         "> 每族: 票型构成 · 次日走法(全期 / 近 60 日)· 次日收 / 最高 P25·中·P75(%) · 你发过截图的案例。**名字空着 = 等你起**。", ""]
    for f, v in sorted(fams.items(), key=lambda x: -x[1]["n"]):
        g, r = v["全期"], v["近60日"]
        L += [f"## 族 {f} · 名字: ___ · n={v['n']}", f"- 票型: {v['票型']}",
              f"- 次日走法(全期): {g['走法%']} · 收 {g['次日收 P25/中/P75']} · 最高 {g['次日最高 P25/中/P75']}",
              (f"- 近 60 日: n={r['n']} {r['走法%']} · 收 {r['次日收 P25/中/P75']}" if r else "- 近 60 日: 无"),
              f"- 比全体多出来的走法(倍数): {v['相对全体倍数(走法)']}",
              f"- 你发过的: {'、'.join(by.get(f, [])) or '无'}", ""]
    L += ["## 走势拓扑(相邻两天都在库里的族转移, n ≥30, 前 30 条)", ""] + [f"- {k}: {n}" for k, n in list(tr.items())[:30]]
    MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("族", a.k, "用户案例落族", len(cases), "转移边", len(tr))


if __name__ == "__main__":
    main()
