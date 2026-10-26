# -*- coding: utf-8 -*-
"""scen_v2.py — K 线续画情景 v2(10/26 用户令: 旧版只有"强 / 震荡 / 弱"三档没意义 → 分票型、极端情景单列、top3、尽量用上本地所有数据; 零 token)

结构(高内聚低耦合):
  scen_v2_feat.py  全市场特征表(票型 / 板高 / K形 / 走势 / 量能 / 段式箱体 / 情绪 / 指数 / 龙虎榜 / 导师 / 分时 / 题材 / 电报) + 标签 → results/kline/_scen_v2/feat.parquet
  scen_v2.py       ① 模型: 多分类 GBDT(sklearn HistGradientBoosting), 两段:
                      M1: P(T+1 走法 | 特征) 8 类;  M2: P(T+2 走法 | 特征, T+1 走法) 8 类;  两日组合 P(a → b) = M1(a) × M2(b | a)
                      混合(默认): 强势异动票(票型 0~7)用 stronghot_core 模型(只在强势 / 活跃票上训练, 情绪 / 指数按每日五分位分档 + 交互约束);
                                  平常票(箱体震荡 / 趋势)用 nomkt_core 模型(不含情绪 / 指数); _core = 龙虎榜 / 导师 / 分时 / 题材 / 电报 / 情绪 不进模型(见 SPARSE / CORE_DROP 注释) —— 两种都是 10/26 样本外对比后选的, 见 docs/research/scen_v2_20261026.md
                   ② 样本外: 训练 T < 2026-06-29, 测试 T ≥ 2026-07-01; 对比 基线① 全市场基础概率 / 基线② 只按票型的条件概率(票型 10 类 × 10cm/20cm × ST/非ST);
                      指标 log-loss / top1 / top3 命中 / 极端情景校准(按预测概率分档看实际发生率)
                   ③ scen(code, T): top3 单日 + top3 两日组合 + 极端情景概率 + 每个情景的代表样本(加权 kNN 找"最像的真实样本", 带真实日 K 路径, 有分钟线带分时)
                      + 因子贡献(按因子组 / 单因子消融) + 同类样本证据(n) + 导师卖出同票后的历史走势 + 样本外指标摘要
T+1 走法 8 种(相对 T 收盘 %, 20cm 阈值 ×2; 涨停 / 跌停按真实涨跌停价):
   涨停 · 冲高A杀(最高 ≥ +5% 且收盘 ≤ 最高 −6%) · 高开低走(开 ≥ +2% 且收 < 开 −3%) · 单边上涨(收 ≥ +3% 且收在当天上 1/4) ·
   深V(最低 ≤ −5% 且收盘 ≥ 最低 +5%) · 单边下跌(收 ≤ −3% 且收在下 1/4) · 跌停 · 震荡(其余)
   T+2 走法同口径, 相对 T+1 收盘
用法(必须用 anaconda python, 项目 venv 没装 sklearn):
  python scen_v2.py all              每晚一条: 重建特征表 + 训练 stronghot_core / nomkt_core(eval + prod)+ 混合样本外评估(实测约 6 分钟, 24 核)
  python scen_v2.py build                       只重建特征表(约 2 分钟)
  python scen_v2.py train --variant stronghot   训练一个变体(eval: 训练期最后 40 天早停 + 样本外; prod: 全部有标签数据, 轮数取 eval ×1.1); 变体 bin / nomkt / strong / stronghot, 加 _core = 去掉 5 个稀疏组 + 情绪组(默认用 stronghot_core + nomkt_core)
  python scen_v2.py eval_hybrid                 混合样本外评估 → meta_eval_hybrid.json(scen 的"样本外"摘要读它)
  python scen_v2.py 002307 2026-10-23           预测(打印 JSON, 分钟数组只打点数)
每晚: 收盘数据(日线 / 龙虎榜 / 账本 / 分钟)入库后跑 all; 全量重建就够快, 不做真正的增量; 模型文件 model_prod_stronghot_core.pkl / model_prod_nomkt_core.pkl
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE)]
import scen_v2_feat as F   # noqa: E402

OUT = F.OUT
WAYS = F.WAYS
TYPES = F.TYPES
EXTREME = ["涨停", "跌停", "冲高A杀", "深V"]
TEST_FROM = "2026-07-01"
FEATS = F.FEATS
GROUPS = F.GROUPS
COMBOS = [f"{a}→{b}" for a in WAYS for b in WAYS]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


_FEAT = {}


def feat():
    if "df" not in _FEAT:
        _FEAT["df"] = pd.read_parquet(OUT / "feat.parquet")
    return _FEAT["df"]


# ---------------------------------------------------------------- 模型
# 10/26 第一版教训: 情绪 / 指数是"全市场同一天同一个值"的列, 原值喂进去 = 给每一天发了身份证, 树会把那一天(训练期)真实的 T+1 大盘走势背下来
# (随机切验证集也发现不了, 因为同一天的票同时在训练和验证里) → 样本外深V 预测 60% 实际 3%。改法(SPEC):
#   bin: 情绪 / 指数列按训练期"每日值"的五分位切 5 档; 交互约束 = 一条树枝最多用一个市场列(和任意个股列组合), 拼不出"某一天"
#   nomkt: 消融 = 情绪 / 指数整组拿掉
#   早停用时间切分: 训练期最后 40 个交易日当验证集
MKT = GROUPS["情绪"] + GROUPS["指数"]
SPEC = {"variant": "bin", "feats": FEATS, "bins": {}}


SPARSE = ["龙虎榜", "导师", "分时", "题材", "电报"]   # 数据只覆盖后半段(2025-01 / 2025-09 / 2026-05 / 2026-01 / 2026-03 起)
# 10/26 消融(ablation_strong.json / ablation_sparse.json): 全期训练时这 5 组让强势票样本外 logloss 1.471 → 1.499(变差) ——
# 缺失值 = "数据期之前" 成了时代标记; 只在有数据的时期公平比较, 各组 ±0.007 以内(噪声级), 而缩短训练期本身代价 +0.05 以上
# → 默认变体 *_core 不进模型, 改在 scen 输出的"同类证据 / 导师卖出后走势"里按真实样本给分布(带 n), 供人工判断


CORE_DROP = ["情绪"]   # 10/26 消融(ablation_core.json, 两个随机种子): 核心设定下拿掉情绪组, 强势票样本外 logloss 1.4735 → 1.4641(种子噪声约 0.004);
# 拿掉指数组变差 +0.025 → 指数留, 情绪出模型、改在"同类证据"里给"同情绪档"的真实分布


def base_variant(variant):
    return variant[:-5] if variant.endswith("_core") else variant


def make_spec(tr, variant="bin"):
    bv = base_variant(variant)
    drop = {c for g in SPARSE + CORE_DROP for c in GROUPS[g]} if variant.endswith("_core") else set()
    feats = [c for c in FEATS if not (bv == "nomkt" and c in MKT) and c not in drop]
    bins = {}
    if bv in ("bin", "strong", "stronghot"):
        day = tr.groupby("trade_date")[MKT].first()
        for c in MKT:
            v = day[c].dropna().values
            bins[c] = np.unique(np.quantile(v, [.2, .4, .6, .8])).tolist() if len(v) else []
    return {"variant": variant, "feats": feats, "bins": bins}


def set_spec(sp):
    SPEC.clear()
    SPEC.update(sp)


def cat_idx():
    return [SPEC["feats"].index(c) for c in F.CATS if c in SPEC["feats"]]


def _hgb(seed=0):
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=400, learning_rate=0.08, max_leaf_nodes=32, min_samples_leaf=800, l2_regularization=1.0,
                                          early_stopping=True, n_iter_no_change=25, scoring="loss", random_state=seed)


def _cst(extra=()):
    """交互约束: 每个集合 = 全部个股列 + 一个市场列(+ extra)"""
    fs = SPEC["feats"]
    mk = [i for i, c in enumerate(fs) if c in MKT]
    if base_variant(SPEC["variant"]) not in ("bin", "strong", "stronghot") or not mk:
        return None
    st = [i for i, c in enumerate(fs) if c not in MKT] + list(extra)
    return [st + [j] for j in mk]


def _sample(tr, seed=0, keep_plain=0.25):
    """平常日(箱体震荡 / 趋势且 |涨跌| < 3%)太多 → 抽 25%, 样本权重 1/0.25 补回(概率校准不变)"""
    rng = np.random.default_rng(seed)
    plain = tr["typ"].isin([8, 9]).values & (np.abs(tr["k_pct"].values) < 3)
    keep = ~plain | (rng.random(len(tr)) < keep_plain)
    w = np.where(plain, 1 / keep_plain, 1.0)[keep]
    return tr[keep], w


def X1(df):
    fs = SPEC["feats"]
    x = df[fs].to_numpy(np.float32)
    for j, c in enumerate(fs):
        e = SPEC["bins"].get(c)
        if e:
            col = x[:, j]
            x[:, j] = np.where(np.isnan(col), np.nan, np.searchsorted(np.asarray(e, np.float32), col))
    return x


def X2(df, y1):
    return np.column_stack([X1(df), np.asarray(y1, np.float32)])


def fit_pair(tr, seed=0, n_val_days=40, n_iter=None):
    """n_iter=None: 训练期最后 n_val_days 个交易日当验证集早停(eval 用);
    n_iter=(轮数1, 轮数2): 不留验证集、按给定轮数在全部数据上训练(prod 用, 轮数取 eval 早停结果 ×1.1 —— 不然 prod 学不到最近两个月)"""
    t0 = time.time()
    s, w = _sample(tr, seed)
    if n_iter:
        a, wa = s, w
        b = None
    else:
        days = sorted(s["trade_date"].unique())
        vcut = days[-n_val_days]
        isv = (s["trade_date"] >= vcut).values
        a, b = s[~isv], s[isv]
        wa, wb = w[~isv], w[isv]
    m1 = _hgb(seed)
    m1.set_params(categorical_features=cat_idx(), interaction_cst=_cst())
    if n_iter:
        m1.set_params(early_stopping=False, max_iter=max(10, int(n_iter[0] * 1.1)))
        m1.fit(X1(a), a["y1"].values, sample_weight=wa)
    else:
        m1.fit(X1(a), a["y1"].values, sample_weight=wa, X_val=X1(b), y_val=b["y1"].values, sample_weight_val=wb)
    log("M1", len(a), "行", "" if n_iter else f"+ 验证 {len(b)} 行({vcut} 起)", m1.n_iter_, "轮", round(time.time() - t0), "秒")
    a2 = a[a["y2"] >= 0]
    wa2 = wa[(a["y2"] >= 0).values]
    m2 = _hgb(seed + 1)
    n = len(SPEC["feats"])
    m2.set_params(categorical_features=cat_idx() + [n], interaction_cst=_cst([n]))
    if n_iter:
        m2.set_params(early_stopping=False, max_iter=max(10, int(n_iter[1] * 1.1)))
        m2.fit(X2(a2, a2["y1"].values), a2["y2"].values, sample_weight=wa2)
    else:
        b2 = b[b["y2"] >= 0]
        wb2 = wb[(b["y2"] >= 0).values]
        m2.fit(X2(a2, a2["y1"].values), a2["y2"].values, sample_weight=wa2, X_val=X2(b2, b2["y1"].values), y_val=b2["y2"].values, sample_weight_val=wb2)
    log("M2", len(a2), "行", m2.n_iter_, "轮", round(time.time() - t0), "秒")
    return m1, m2


def proba(m, X):
    p = np.zeros((len(X), len(WAYS)))
    p[:, m.classes_] = m.predict_proba(X)
    return p


def proba_combo(m1, m2, df):
    """→ P1 (n×8), P2 (n×8×8: [i, a, b] = P(T+2=b | T+1=a)), PC (n×64)"""
    P1 = proba(m1, X1(df))
    P2 = np.stack([proba(m2, X2(df, np.full(len(df), a))) for a in range(len(WAYS))], axis=1)
    PC = (P1[:, :, None] * P2).reshape(len(df), -1)
    return P1, P2, PC


# ---------------------------------------------------------------- 评估
def metrics(P, y, names, extreme=None):
    P = np.clip(P, 1e-6, 1)
    P = P / P.sum(1, keepdims=True)
    n = len(y)
    ll = float(-np.mean(np.log(P[np.arange(n), y])))
    rank = np.argsort(-P, 1)
    top1 = float(np.mean(rank[:, 0] == y))
    top3 = float(np.mean((rank[:, :3] == y[:, None]).any(1)))
    out = {"n": n, "logloss": round(ll, 4), "top1": round(top1, 4), "top3": round(top3, 4)}
    if extreme:
        cal = {}
        bins = [0, .02, .05, .1, .2, .3, .5, 1.01]
        for e in extreme:
            k = names.index(e)
            p, hit = P[:, k], (y == k)
            rows = []
            for a, b in zip(bins[:-1], bins[1:]):
                msk = (p >= a) & (p < b)
                if msk.sum() >= 20:
                    rows.append({"档": f"{a:.0%}~{min(b, 1):.0%}", "n": int(msk.sum()), "预测均值": round(float(p[msk].mean()) * 100, 1), "实际": round(float(hit[msk].mean()) * 100, 1)})
            # Brier 及区分度: 预测最高 5% 那批的实际发生率 vs 全体
            top = p >= np.quantile(p, 0.95)
            cal[e] = {"分档": rows, "全体发生率%": round(float(hit.mean()) * 100, 2), "预测前5%那批实际%": round(float(hit[top].mean()) * 100, 2),
                      "brier": round(float(np.mean((p - hit) ** 2)), 5)}
        out["极端校准"] = cal
    return out


def base_tables(tr):
    """基线概率: 全市场 / 按票型(typ × 20cm); 单日和两日组合"""
    g1 = np.bincount(tr["y1"], minlength=8).astype(float)
    t2 = tr[tr["y2"] >= 0]
    gc = np.bincount(t2["y1"] * 8 + t2["y2"], minlength=64).astype(float)
    by1, byc = {}, {}
    for (t, z, st_), x in tr.groupby(["typ", "is20", "is_st"]):   # 10/26: 加 ST 维(炸板票 26% 是 ST, 跌停率差一截)
        by1[(int(t), int(z), int(st_))] = (np.bincount(x["y1"], minlength=8) + g1 / g1.sum() * 20) / (len(x) + 20)
    for (t, z, st_), x in t2.groupby(["typ", "is20", "is_st"]):
        byc[(int(t), int(z), int(st_))] = (np.bincount(x["y1"] * 8 + x["y2"], minlength=64) + gc / gc.sum() * 20) / (len(x) + 20)
    return {"g1": g1 / g1.sum(), "gc": gc / gc.sum(), "by1": by1, "byc": byc}


def base_proba(B, df, kind="1"):
    g = B["g1"] if kind == "1" else B["gc"]
    tb = B["by1"] if kind == "1" else B["byc"]
    return np.array([tb.get((int(t), int(z), int(st_)), g) for t, z, st_ in zip(df["typ"], df["is20"], df["is_st"])])


def evaluate(m1, m2, B, te, pc_fn=None):
    P1, P2, PC = pc_fn(te) if pc_fn else proba_combo(m1, m2, te)
    y1 = te["y1"].values.astype(int)
    yc = (te["y1"] * 8 + te["y2"]).values.astype(int)
    strong = te["typ"].values <= 7
    res = {}
    for nm, msk in (("全部", np.ones(len(te), bool)), ("强势异动票(票型 0~7)", strong), ("平常票(箱体震荡 / 趋势)", ~strong)):
        if not msk.any():
            continue
        r = {}
        r["单日_模型"] = metrics(P1[msk], y1[msk], WAYS, EXTREME)
        r["单日_基线全市场"] = metrics(np.tile(B["g1"], (msk.sum(), 1)), y1[msk], WAYS, EXTREME)
        r["单日_基线票型"] = metrics(base_proba(B, te[msk], "1"), y1[msk], WAYS, EXTREME)
        r["两日_模型"] = metrics(PC[msk], yc[msk], COMBOS)
        r["两日_基线全市场"] = metrics(np.tile(B["gc"], (msk.sum(), 1)), yc[msk], COMBOS)
        r["两日_基线票型"] = metrics(base_proba(B, te[msk], "c"), yc[msk], COMBOS)
        res[nm] = r
    # 按票型的样本外 top3 命中(给 scen 的置信度用)
    by = {}
    for t in range(10):
        msk = te["typ"].values == t
        if msk.sum() >= 50:
            by[TYPES[t]] = {"n": int(msk.sum()), "单日top3_模型": metrics(P1[msk], y1[msk], WAYS)["top3"], "单日top3_票型基线": metrics(base_proba(B, te[msk], "1"), y1[msk], WAYS)["top3"],
                            "单日logloss_模型": metrics(P1[msk], y1[msk], WAYS)["logloss"], "单日logloss_票型基线": metrics(base_proba(B, te[msk], "1"), y1[msk], WAYS)["logloss"],
                            "两日top3_模型": metrics(PC[msk], yc[msk], COMBOS)["top3"], "两日top3_票型基线": metrics(base_proba(B, te[msk], "c"), yc[msk], COMBOS)["top3"]}
    res["按票型"] = by
    return res


def group_importance(m1, te, B, n=60000, seed=0):
    """样本外按因子组的置换重要性: 打乱一组 → log-loss 涨多少(越大越重要)"""
    rng = np.random.default_rng(seed)
    s = te.sample(min(n, len(te)), random_state=seed)
    s = pd.concat([s, te[te["typ"] <= 7]]).drop_duplicates(subset=["symbol", "trade_date"])
    X = X1(s)
    y = s["y1"].values.astype(int)
    base = metrics(proba(m1, X), y, WAYS)["logloss"]
    out = {}
    for g, cols in GROUPS.items():
        Xp = X.copy()
        perm = rng.permutation(len(X))
        for c in cols:
            if c not in SPEC["feats"]:
                continue
            j = SPEC["feats"].index(c)
            Xp[:, j] = X[perm, j]
        out[g] = round(metrics(proba(m1, Xp), y, WAYS)["logloss"] - base, 5)
    return dict(sorted(out.items(), key=lambda kv: -kv[1])), base


def train(test_from=TEST_FROM, prod=True, variant="bin"):
    import joblib
    t0 = time.time()
    df = feat()
    df = df[df["y1"] >= 0]
    days = sorted(df["trade_date"].unique())
    cut = days[max(0, days.index(next(d for d in days if d >= test_from)) - 2)]   # 训练样本的 T+2 也要在测试期之前
    tr = df[df["trade_date"] < cut]
    te = df[(df["trade_date"] >= test_from) & (df["y2"] >= 0)]
    if base_variant(variant) in ("strong", "stronghot"):   # 只用强势异动票训练 / 测试(stronghot 另含"近 20 日 ≥2 次涨停的活跃票")
        ROUTE["hot"] = base_variant(variant) == "stronghot"
        df, tr, te = df[is_strong(df)], tr[is_strong(tr)], te[is_strong(te)]
    set_spec(make_spec(tr, variant))
    log("训练", len(tr), "测试", len(te), "切点", cut, test_from, "变体", variant)
    m1, m2 = fit_pair(tr)
    B = base_tables(tr)
    res = evaluate(m1, m2, B, te)
    imp, base_ll = group_importance(m1, te, B)
    meta = {"训练": f"T {tr['trade_date'].min()} ~ {tr['trade_date'].max()}, {len(tr)} 行", "测试": f"T {te['trade_date'].min()} ~ {te['trade_date'].max()}, {len(te)} 行",
            "样本外": res, "因子组置换重要性(样本外 log-loss 增加)": imp, "置换基准 logloss": base_ll, "M1 轮数": int(m1.n_iter_), "M2 轮数": int(m2.n_iter_)}
    meta["变体"] = variant
    sfx = "" if variant == "bin" else "_" + variant
    joblib.dump({"m1": m1, "m2": m2, "B": B, "spec": dict(SPEC)}, OUT / f"model_eval{sfx}.pkl")
    (OUT / f"meta_eval{sfx}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log("eval 模型完成", round(time.time() - t0), "秒")
    if prod:
        all_ = df[df["y1"] >= 0]
        set_spec(make_spec(all_, variant))
        m1p, m2p = fit_pair(all_, seed=7, n_iter=(m1.n_iter_, m2.n_iter_))
        Bp = base_tables(all_)
        joblib.dump({"m1": m1p, "m2": m2p, "B": Bp, "spec": dict(SPEC), "label_until": all_["trade_date"].max()}, OUT / f"model_prod{sfx}.pkl")
        log("prod 模型完成", round(time.time() - t0), "秒")
    meta["耗时秒"] = round(time.time() - t0)
    (OUT / f"meta_eval{sfx}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


STRONG = 7   # 票型 0~7 = 强势异动票
ROUTE = {"hot": True}   # True: 强势异动 = 票型 0~7 或 近 20 日 ≥2 次涨停(活跃票); False: 只看票型 0~7


def is_strong(df):
    m = df["typ"].values <= STRONG
    if ROUTE["hot"]:
        m = m | (df["zt_n20"].values >= 2)
    return m


def hybrid_pc(Ms, Mn):
    """混合: 强势异动票(票型 0~7)用 strong 模型(含情绪 / 指数, 分档 + 交互约束), 平常票用 nomkt 模型(不含情绪 / 指数)"""
    def fn(df):
        st = is_strong(df)
        P1, P2, PC = np.zeros((len(df), 8)), np.zeros((len(df), 8, 8)), np.zeros((len(df), 64))
        for M, msk in ((Ms, st), (Mn, ~st)):
            if msk.any():
                use(M)
                a, b, c = proba_combo(M["m1"], M["m2"], df[msk])
                P1[msk], P2[msk], PC[msk] = a, b, c
        return P1, P2, PC
    return fn


def eval_hybrid(strong_name="stronghot_core", route_hot=False, plain_name="nomkt_core"):
    """样本外: strong + nomkt 两个 eval 模型拼起来(各自已在 train 里存好), 基线同 bin 变体(全量训练期)"""
    import joblib
    df = feat()
    df = df[df["y1"] >= 0]
    days = sorted(df["trade_date"].unique())
    cut = days[max(0, days.index(next(d for d in days if d >= TEST_FROM)) - 2)]
    tr = df[df["trade_date"] < cut]
    te = df[(df["trade_date"] >= TEST_FROM) & (df["y2"] >= 0)]
    ROUTE["hot"] = route_hot
    Ms, Mn = joblib.load(OUT / f"model_eval_{strong_name}.pkl"), joblib.load(OUT / f"model_eval_{plain_name}.pkl")
    B = base_tables(tr)
    res = evaluate(None, None, B, te, hybrid_pc(Ms, Mn))
    st = te[is_strong(te)]
    use(Ms)
    imp_s, ll_s = group_importance(Ms["m1"], st, B)
    use(Mn)
    imp_n, ll_n = group_importance(Mn["m1"], te[~is_strong(te)], B, n=40000)
    hot = te[(te["typ"] > STRONG) & (te["zt_n20"] >= 2)]
    res["活跃平常票(票型 8~9 且近20日≥2次涨停)"] = {k: v for k, v in evaluate(None, None, B, hot, hybrid_pc(Ms, Mn))["全部"].items()}
    meta = {"训练": f"T {tr['trade_date'].min()} ~ {tr['trade_date'].max()}, {len(tr)} 行", "测试": f"T {te['trade_date'].min()} ~ {te['trade_date'].max()}, {len(te)} 行",
            "样本外": res, "因子组置换重要性(样本外 log-loss 增加)": {"强势异动票(strong 模型)": imp_s, "平常票(nomkt 模型)": imp_n},
            "置换基准 logloss": {"强势": ll_s, "平常": ll_n}, "变体": f"hybrid = {strong_name}(分流: {'票型 0~7 或近20日≥2次涨停' if route_hot else '票型 0~7'}) + {plain_name}(其余)"}
    (OUT / f"meta_eval_hybrid{'' if (strong_name == 'stronghot_core' and plain_name == 'nomkt_core' and not route_hot) else '_' + strong_name + '_' + plain_name + ('_hotroute' if route_hot else '')}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log("hybrid 样本外写出")
    return meta


# ---------------------------------------------------------------- 预测接口
_M = {}


def model(kind="prod"):
    if kind not in _M:
        import joblib
        f = OUT / f"model_{kind}.pkl"
        if not f.exists():
            raise FileNotFoundError(f)
        _M[kind] = joblib.load(f)
    return _M[kind]


def use(M):
    set_spec(M.get("spec") or {"variant": "raw", "feats": FEATS, "bins": {}})
    return M


KNN_COLS = {"k_pct": 1.5, "k_gap": 1, "k_hi": 1, "k_lo": 1, "k_clv": 1, "boards": 2, "prev_boards": 1.5, "zt_n20": 1, "r5": 1, "r20": 1, "pos60": 1,
            "vr5": 1, "box_pos": 0.7, "box_in": 0.7, "mk_zt": 1, "mk_zab": 0.7, "mk_jin": 0.7, "ix_国证2000": 0.7, "lhb_net": 0.7, "is20": 3, "is_st": 3}


def _name(sym):
    if ("nm", sym) not in _M:
        try:
            r = F.sql_df("select name from security_master where symbol=%s limit 1", (sym,))
            _M[("nm", sym)] = r.iloc[0, 0] if len(r) else ""
        except Exception:   # noqa: BLE001
            _M[("nm", sym)] = ""
    return _M[("nm", sym)]


def minute_of(sym, d):
    """minute_path 当天 240 根分钟价 → [相对前收 %]; 没有 → None"""
    f = F.MP_DIR / f"{d}.jsonl"
    if not f.exists():
        return None
    code = sym[2:]
    key = f'"code": "{code}"'
    for line in open(f, encoding="utf-8"):
        if key in line[:40]:
            j = json.loads(line)
            pc = j.get("prev")
            if pc and j.get("p"):
                return [round((x / pc - 1) * 100, 3) for x in j["p"]]
    return None


def _knn_pool(T, cur):
    df = feat()
    pool = df[(df["d2"].notna()) & (df["d2"] <= T) & (df["y2"] >= 0)]
    cols = list(KNN_COLS)
    Z = pool[cols].astype(float)
    med = Z.median()
    sd = (Z.quantile(0.9) - Z.quantile(0.1)).replace(0, 1) / 2.56
    w = np.array([KNN_COLS[c] for c in cols])
    zp = ((Z.fillna(med) - med) / sd).to_numpy() * w
    zc = ((cur[cols].astype(float).fillna(med) - med) / sd).to_numpy() * w
    dist = np.sqrt(((zp - zc) ** 2).sum(1)) + np.where(pool["typ"].values == cur["typ"], 0, 3.0)
    return pool, dist


def _rep(pool, dist, msk, close):
    """在满足 msk 的样本里取最像的; 有分钟线的优先(距离不超过最近的 1.5 倍)"""
    idx = np.where(msk)[0]
    if not len(idx):
        return None, {}
    order = idx[np.argsort(dist[idx])]
    near = pool.iloc[order[:50]]
    best = order[0]
    mp_days = {p.stem for p in F.MP_DIR.glob("20*.jsonl")}
    for k in order[:30]:
        r = pool.iloc[k]
        if dist[k] <= dist[best] * 1.5 + 0.3 and r["d1"] in mp_days and r["d2"] in mp_days:
            best = k
            break
    r = pool.iloc[best]
    path = [{"d": r["d1"], "o": float(r["p1o"]), "h": float(r["p1h"]), "l": float(r["p1l"]), "c": float(r["p1c"])},
            {"d": r["d2"], "o": float(r["p2o"]), "h": float(r["p2h"]), "l": float(r["p2l"]), "c": float(r["p2c"])}]
    mins = {}
    for k_, dd in (("T+1", r["d1"]), ("T+2", r["d2"])):
        mp = minute_of(r["symbol"], dd)
        if mp:
            # 分钟价相对"样本当天前收" → 换成相对样本 T 收盘
            base = 0 if k_ == "T+1" else float(r["p1c"])
            mins[k_] = [round(((1 + base / 100) * (1 + x / 100) - 1) * 100, 3) for x in mp]
    rep = {"code": r["symbol"][2:], "sym": r["symbol"], "name": _name(r["symbol"]), "d": r["trade_date"], "票型": TYPES[int(r["typ"])], "距离": round(float(dist[best]), 2),
           "path": path, "分钟(相对样本T收盘%)": mins or None,
           "套到本票的价格": [{k: round(close * (1 + p[k] / 100), 2) for k in "ohlc"} | {"d": p["d"]} for p in path]}

    def q(col):
        v = near[col].astype(float).values
        return [round(float(np.percentile(v, x)), 2) for x in (25, 50, 75)]
    st = {"近邻n": int(len(near)), "T+1收 P25/中位/P75": q("p1c"), "T+1高": q("p1h"), "T+1低": q("p1l"), "T+2收(相对T收) P25/中位/P75": q("p2c")}
    return rep, st


FEAT_CN = {
    "typ": "票型", "boards": "连板高度", "prev_zt": "昨天涨停", "prev_boards": "昨天板高", "prev_touch": "昨天摸板", "zt_n5": "近5日涨停次数", "zt_n10": "近10日涨停次数",
    "zt_n20": "近20日涨停次数", "days_since_zt": "距上次涨停天数", "is20": "20cm", "is_st": "ST",
    "k_pct": "当天涨跌", "k_gap": "开盘缺口", "k_hi": "当天最高", "k_lo": "当天最低", "k_clv": "收在当天位置", "k_upsh": "上影线", "k_dnsh": "下影线", "k_body": "实体",
    "k_amp": "振幅", "prev_pct_k": "昨天涨跌",
    "r3": "3日涨幅", "r5": "5日涨幅", "r10": "10日涨幅", "r20": "20日涨幅", "d_hi20": "距20日最高", "d_lo20": "距20日最低", "pos20": "20日区间位置",
    "d_hi60": "距60日最高", "d_lo60": "距60日最低", "pos60": "60日区间位置", "ma5": "偏离5日线", "ma10": "偏离10日线", "ma20": "偏离20日线", "up_run": "连阳天数",
    "atr_pct": "ATR%", "vr5": "量比(÷前5日均量)", "vr20": "量比(÷前20日均量)", "ar20": "成交额÷20日均额", "lamt": "成交额(对数)",
    "box_in": "在箱体内", "box_pos": "箱内位置", "box_w": "箱宽ATR", "box_age": "箱龄", "box_outn": "越界天数", "box_exit_days": "离箱天数", "box_exit_dir": "离箱方向",
    "cl_q60": "60日收盘分位",
    "mk_zt": "全市场涨停家数", "mk_dt": "全市场跌停家数", "mk_touch": "摸板家数", "mk_zab": "炸板率", "mk_maxb": "最高连板", "mk_jin": "晋级率", "mk_prem": "昨日涨停今日均涨",
    "mk_up": "上涨家数占比", "mk_med": "全市场中位涨幅", "mk_zt_chg": "涨停家数较昨日", "mk_ge2": "连板家数",
    "lhb_on": "上龙虎榜", "lhb_net": "龙虎榜净买占成交额", "lhb_nr": "上榜原因数", "lhb_inst": "机构净买", "lhb_yz": "知名游资净买", "lhb_oneday": "一日游席位净买",
    "lhb_board": "打板型席位净买", "lhb_lowbuy": "低吸型席位净买", "lhb_seatq": "净买席位历史次日均收益",
    "m_buy_pos": "正样本导师当天买", "m_buy_neg": "负样本导师当天买", "m_sell_pos": "正样本导师当天卖", "m_sell_neg": "负样本导师当天卖", "m_buy_pos5": "正样本导师近5日买",
    "m_buy_neg5": "负样本导师近5日买", "m_sell_pos5": "正样本导师近5日卖", "m_sell_neg5": "负样本导师近5日卖", "m_hold": "导师持有账本数", "m_days_since_sell": "距导师上次卖出天数",
    "mi_thi": "最高点时刻(分钟)", "mi_tlo": "最低点时刻(分钟)", "mi_tail": "尾盘拉升", "mi_e30": "早盘30分钟冲高", "mi_dd": "收盘距日内最高", "mi_rb": "收盘距日内最低",
    "mi_seal": "封板分钟数", "mi_opens": "开板次数", "mi_first": "首封时刻(分钟)", "mi_shape": "分时形态",
    "th_zt": "所挂题材当天涨停数", "th_chg": "题材涨停数较昨日", "th_wave": "题材本波第几天", "th_zt5": "题材近5日涨停数", "th_in_md": "当天进涨停分析表",
    "tg_n": "电报点名次数", "tg_red": "加红电报点名",
}
for _g in ("指数",):
    for _c in GROUPS[_g]:
        _a, _b = _c.split("_", 1)
        FEAT_CN[_c] = f"{_b}{ {'ix': '当日涨跌', 'ix5': '5日涨跌', 'ixp': '20日区间位置'}[_a] }"


def _fmt(c, v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "缺"
    if c == "typ":
        return TYPES[int(v)]
    if c == "mi_shape":
        return F.SHAPES[int(v)]
    return f"{v:.2f}" if abs(v) < 100 else f"{v:.0f}"


def _contrib_feat(m1, x_row, ref, p_now, ks, top=5):
    """单因子消融: 只把一个因子换成参照样本的值 → 这个因子把每个情景推高 / 压低了多少 pp; 每个情景给绝对值最大的 top 个"""
    X = X1(ref)
    xr = X1(x_row)[0]
    raw = x_row.iloc[0]
    res = []
    for j, c in enumerate(SPEC["feats"]):
        if c in ("is_st", "is20"):   # 票的属性, 换成参照样本的值是反事实(主板票当 20cm 算), 不列
            continue
        Xg = np.tile(xr, (len(X), 1))
        Xg[:, j] = X[:, j]
        res.append((c, (p_now - proba(m1, Xg).mean(0)) * 100))
    out = {}
    for k in ks:
        best = sorted(res, key=lambda z: -abs(z[1][k]))[:top]
        out[WAYS[k]] = [f"{FEAT_CN.get(c, c)}={_fmt(c, raw[c])} → {v[k]:+.1f}pp" for c, v in best if abs(v[k]) >= 0.3]
    return out


def _contrib(m1, x_row, ref, p_now):
    """因子组消融: 把这一组的值换成参照样本(全市场近一年随机 300 行)的值, 平均后的概率 vs 现在 → 这一组把概率推高 / 压低了多少 pp"""
    X = X1(ref)
    xr = X1(x_row)[0]
    out = {}
    for g, cols in GROUPS.items():
        js = [SPEC["feats"].index(c) for c in cols if c in SPEC["feats"]]
        if not js:
            continue
        Xg = np.tile(xr, (len(X), 1))
        Xg[:, js] = X[:, js]
        out[g] = (p_now - proba(m1, Xg).mean(0)) * 100
    return out


def _evidence(T, cur, pool_all):
    """同类样本证据(只用 T 之前标签已知的): 每个"异常信号"在同票型里的实际 T+1 走法分布"""
    base = pool_all[(pool_all["typ"] == cur["typ"]) & (pool_all["is20"] == cur["is20"]) & (pool_all["is_st"] == cur["is_st"])]   # 同票型 = 同 10 类 × 10cm/20cm × ST/非ST
    sig = []
    if cur.get("lhb_on", 0) == 1:
        sig.append(("今天上龙虎榜", base["lhb_on"] == 1))
    for c, nm in (("lhb_net", "龙虎榜净买"), ("lhb_oneday", "一日游席位净买"), ("lhb_board", "打板型席位净买"), ("lhb_lowbuy", "低吸型席位净买"), ("lhb_inst", "机构净买")):
        v = cur.get(c, 0) or 0
        if abs(v) >= 1:   # 同号且幅度 ≥ 当前值的一半(一日游席位太普遍: 上榜票 89% 都有一日游席位净买, 只看 >0 没区分度)
            sig.append((f"{nm} {v:+.1f}% 成交额(取同票型里 {'≥' if v > 0 else '≤'} {v / 2:+.1f}% 的)", (base[c] >= v / 2) if v > 0 else (base[c] <= v / 2)))
    for c, nm in (("m_sell_pos5", "近 5 日有正样本导师卖出同票"), ("m_sell_neg5", "近 5 日有负样本导师卖出同票"),
                  ("m_buy_pos5", "近 5 日有正样本导师买入同票"), ("m_buy_neg5", "近 5 日有负样本导师买入同票")):
        if (cur.get(c, 0) or 0) > 0:
            sig.append((nm, base[c].fillna(0) > 0))
    if (cur.get("m_hold", 0) or 0) > 0:
        sig.append(("有导师持有(按逐笔腿推算)", base["m_hold"].fillna(0) > 0))
    if cur.get("box_in") == 1:
        sig.append(("在段式箱体内", base["box_in"] == 1))
    elif cur.get("box_in") == 0.5:
        sig.append(("箱体越界未满 3 天", base["box_in"] == 0.5))
    if (cur.get("tg_n", 0) or 0) > 0:
        sig.append(("当天被电报点名", base["tg_n"] > 0))
    if cur.get("mk_zt") is not None:   # 当时市况: 同票型 + 同情绪档(全市场涨停家数三分位)
        q = pool_all.groupby("trade_date")["mk_zt"].first().quantile([1 / 3, 2 / 3]).values
        lv = int(np.searchsorted(q, cur["mk_zt"]))
        sig.append((f"同情绪档(全市场涨停家数{['低', '中', '高'][lv]}三分位, 今天 {int(cur['mk_zt'])} 家)",
                    pd.Series(np.searchsorted(q, base["mk_zt"].values) == lv, index=base.index)))
    out = []
    for nm, msk in sig:
        x = base[msk.values]
        n = len(x)
        if n < 5:
            out.append({"信号": nm, "同票型样本n": n, "说明": "样本太少不给分布"})
            continue
        dist = np.bincount(x["y1"].astype(int), minlength=8) / n * 100
        b = np.bincount(base["y1"].astype(int), minlength=8) / max(len(base), 1) * 100
        top = np.argsort(-(dist - b))[:2]
        out.append({"信号": nm, "同票型样本n": n, "同票型全体n": len(base),
                    "T+1走法%": {WAYS[k]: round(float(dist[k]), 1) for k in np.argsort(-dist)[:4]},
                    "相对同票型全体偏离最大": [f"{WAYS[k]} {dist[k] - b[k]:+.1f}pp" for k in top]})
    return out


def mentor_sell_after(cur, pool_all):
    """导师卖出同票之后的历史走势(全部票型, 卖出日 = T): T+1 走法 / T+2 收盘分布, 按 正负样本账本 × 当时情绪档 × 强势/平常 分开"""
    sold = pool_all[((pool_all["m_sell_pos"].fillna(0) + pool_all["m_sell_neg"].fillna(0)) > 0) & (pool_all["is_st"] == cur["is_st"])]
    if sold.empty:
        return {"说明": "导师数据期内没有卖出样本"}
    q = pool_all.groupby("trade_date")["mk_zt"].first().quantile([1 / 3, 2 / 3]).values
    lv = np.searchsorted(q, sold["mk_zt"].values)
    st = is_strong(sold)
    out = {}
    for nm, msk in (("全部卖出日", np.ones(len(sold), bool)), ("正样本导师卖", sold["m_sell_pos"].values > 0), ("负样本导师卖", sold["m_sell_neg"].values > 0),
                    (f"同情绪档({['低', '中', '高'][int(np.searchsorted(q, cur['mk_zt']))]})", lv == np.searchsorted(q, cur["mk_zt"])),
                    ("强势异动票被卖" if bool(is_strong(pd.DataFrame([cur]))[0]) else "平常票被卖", st == bool(is_strong(pd.DataFrame([cur]))[0]))):
        x = sold[msk]
        if len(x) < 10:
            continue
        d = np.bincount(x["y1"].astype(int), minlength=8) / len(x) * 100
        c2 = x["p2c"].dropna()
        out[nm] = {"n": int(len(x)), "T+1走法%": {WAYS[k]: round(float(d[k]), 1) for k in np.argsort(-d)[:4]},
                   "T+2收(相对卖出日收盘) P25/中位/P75": [round(float(c2.quantile(p)), 2) for p in (.25, .5, .75)] if len(c2) else None}
    return out


def scen(code, T, horizon=2, kind="prod"):
    """→ dict: top3 单日 / top3 两日组合 / 极端情景 / 代表样本(真实路径 + 分钟) / 因子贡献 / 同类证据 / 样本外摘要"""
    df = feat()
    sym = ("sh" if code.startswith("6") else "sz") + code
    row = df[(df["symbol"] == sym) & (df["trade_date"] == T)]
    if row.empty:
        raise ValueError(f"{code} {T} 不在特征表里(特征表最新 {df['trade_date'].max()}; 先 python scen_v2.py build)")
    cur = row.iloc[0]
    ROUTE["hot"] = False   # 10/26 消融: 活跃平常票(票型 8~9 但近 20 日 ≥2 次涨停)用 nomkt 模型更好(样本外 logloss 1.233 vs 1.247), 所以分流只看票型
    strong = bool(is_strong(row)[0])
    try:   # 默认 = 混合: 强势异动 / 活跃票用 stronghot 模型, 平常票用 nomkt 模型; 缺文件退回单模型
        M = use(model(kind + ("_stronghot_core" if strong else "_nomkt_core")))
        Bfull = model(kind + "_nomkt_core")["B"]
    except FileNotFoundError:
        M = use(model(kind))
        Bfull = M["B"]
    m1, m2, B = M["m1"], M["m2"], Bfull
    P1, P2, PC = proba_combo(m1, m2, row)
    p1, p2, pc = P1[0], P2[0], PC[0]
    close = float(cur["close"])
    b1 = B["g1"]
    bt1 = B["by1"].get((int(cur["typ"]), int(cur["is20"]), int(cur["is_st"])), b1)
    btc = B["byc"].get((int(cur["typ"]), int(cur["is20"]), int(cur["is_st"])), B["gc"])
    pool, dist = _knn_pool(T, cur)
    # 因子贡献(参照 = 近一年全市场随机 300 行)
    ref = df[(df["trade_date"] < T) & (df["trade_date"] >= str(pd.Timestamp(T) - pd.Timedelta(days=365))[:10])]
    ref = ref[is_strong(ref) == strong].sample(300, random_state=1)   # 参照 = 同大类(强势异动 / 平常)近一年随机 300 行
    con = _contrib(m1, row, ref, p1)
    top1 = np.argsort(-p1)[:3]
    cf = _contrib_feat(m1, row, ref, p1, sorted(set(top1) | {0, 7, 1, 5}))
    ref_p = proba(m1, X1(ref)).mean(0)
    top1 = np.argsort(-p1)[:3]
    out = {"code": code, "name": _name(sym), "T": T, "收盘": close, "模型": kind + (f"(标签截至 {M.get('label_until')})" if M.get("label_until") else ""),
           "票型": TYPES[int(cur["typ"])], "连板高度": int(cur["boards"]), "20cm": bool(cur["is20"]),
           "状态摘要": {"当天涨跌%": round(float(cur["pct"]), 2), "收在当天位置": round(float(cur["k_clv"]), 2), "量比5日": round(float(cur["vr5"]), 2),
                    "近20日涨停次数": int(cur["zt_n20"]), "20日涨幅%": round(float(cur["r20"] * cur["m"]), 1),
                    "箱体": ({1: "在箱内", 0.5: "越界未满 3 天", 0: "不在箱内"}.get(float(cur["box_in"]), "?") +
                           (f", 箱内位置 {cur['box_pos']:.2f}(0=下沿 1=上沿), 箱宽 {cur['box_w']:.1f}ATR" if pd.notna(cur["box_pos"]) else "")),
                    "60日收盘分位": round(float(cur["cl_q60"]), 2) if pd.notna(cur["cl_q60"]) else None,
                    "市场": f"涨停 {int(cur['mk_zt'])} 跌停 {int(cur['mk_dt'])} 炸板率 {cur['mk_zab']:.0%} 最高 {int(cur['mk_maxb'])} 板 晋级率 {cur['mk_jin']:.0%}",
                    "龙虎榜": (f"上榜, 净买 {cur['lhb_net']:+.1f}% 成交额; 一日游 {cur['lhb_oneday']:+.1f}% 打板型 {cur['lhb_board']:+.1f}% 低吸型 {cur['lhb_lowbuy']:+.1f}% 机构 {cur['lhb_inst']:+.1f}%"
                             if cur.get("lhb_on") == 1 else "未上榜"),
                    "导师": f"持有账本≈{int(cur['m_hold'] or 0)} 近5日买 {int((cur['m_buy_pos5'] or 0) + (cur['m_buy_neg5'] or 0))} 卖 {int((cur['m_sell_pos5'] or 0) + (cur['m_sell_neg5'] or 0))}" if pd.notna(cur["m_hold"]) else "无数据",
                    "分时": (F.SHAPES[int(cur["mi_shape"])] + f", 封板 {int(cur['mi_seal'])} 分钟, 开板 {int(cur['mi_opens'])} 次" if pd.notna(cur["mi_shape"]) else "无分钟数据"),
                    "题材": (f"所挂题材当天涨停 {int(cur['th_zt'])} 家(较昨日 {int(cur['th_chg']):+d}), 本波第 {int(cur['th_wave'])} 天" if pd.notna(cur["th_zt"]) else "无"),
                    "电报点名": int(cur["tg_n"]) if pd.notna(cur["tg_n"]) else None},
           "全部走法%": {WAYS[k]: {"模型": round(p1[k] * 100, 1), "票型基线": round(bt1[k] * 100, 1), "全市场基线": round(b1[k] * 100, 1)} for k in range(8)},
           "top3_单日": [], "top3_两日": [], "极端": {}, "因子贡献": {}, "同类证据": [], "样本外": {}}
    for k in top1:
        rep, st = _rep(pool, dist, pool["y1"].values == k, close)
        drv = sorted(((g, float(v[k])) for g, v in con.items()), key=lambda z: -abs(z[1]))[:3]
        out["top3_单日"].append({"名": WAYS[k], "概率": round(p1[k] * 100, 1), "票型基线": round(bt1[k] * 100, 1), "全市场基线": round(b1[k] * 100, 1),
                               "因子贡献top3": [f"{g} {v:+.1f}pp" for g, v in drv], "单因子top3": cf[WAYS[k]][:3], "近邻路径": st, "代表样本": rep})
    if horizon >= 2:
        for kc in np.argsort(-pc)[:3]:
            a, b = divmod(int(kc), 8)
            rep, st = _rep(pool, dist, (pool["y1"].values == a) & (pool["y2"].values == b), close)
            out["top3_两日"].append({"名": COMBOS[kc], "概率": round(pc[kc] * 100, 1), "票型基线": round(btc[kc] * 100, 1), "全市场基线": round(B["gc"][kc] * 100, 1),
                                   "T+1=" + WAYS[a] + " 时 T+2 分布%": {WAYS[j]: round(p2[a, j] * 100, 1) for j in np.argsort(-p2[a])[:4]},
                                   "近邻路径": st, "代表样本": rep})
    pt2 = (p1[:, None] * p2).sum(0)
    out["极端"] = {"T+1": {e: {"模型": round(p1[WAYS.index(e)] * 100, 1), "票型基线": round(bt1[WAYS.index(e)] * 100, 1)} for e in EXTREME},
                 "T+2": {e: round(pt2[WAYS.index(e)] * 100, 1) for e in EXTREME},
                 "两天内至少一次涨停%": round((p1[0] + sum(p1[a] * p2[a, 0] for a in range(1, 8))) * 100, 1),
                 "两天内至少一次跌停%": round((p1[7] + sum(p1[a] * p2[a, 7] for a in range(0, 7))) * 100, 1)}
    for e in EXTREME:
        if WAYS.index(e) not in top1:
            k = WAYS.index(e)
            if p1[k] >= 0.03:
                rep, st = _rep(pool, dist, pool["y1"].values == k, close)
                out["极端"].setdefault("极端代表样本", {})[e] = {"代表样本": rep, "近邻路径": st}
    out["因子贡献"] = {"说明": "把这一组因子(或单个因子)换成同大类(强势异动 / 平常)近一年随机 300 个样本的值后概率会变成多少 → 差值 = 这一组把概率推高(+)/压低(−)了多少 pp; 组间有交互, 加起来不严格等于总偏离",
                   "参照样本平均概率%": {WAYS[k]: round(ref_p[k] * 100, 1) for k in range(8)},
                   "按情景": {WAYS[k]: {g: round(float(v[k]), 1) for g, v in sorted(con.items(), key=lambda z: -abs(z[1][k]))[:5]} for k in sorted(set(top1) | {0, 7, 1, 5})},
                   "单因子(按情景, 绝对值最大 5 个)": cf}
    pool_all = feat()
    pool_all = pool_all[(pool_all["d2"].notna()) & (pool_all["d2"] <= T) & (pool_all["y1"] >= 0)]
    out["同类证据"] = _evidence(T, cur, pool_all)
    out["导师卖出同票后的历史走势"] = mentor_sell_after(cur, pool_all)
    out["导师卖出同票后的历史走势"]["本票"] = (f"近 5 日正样本导师卖 {int(cur['m_sell_pos5'] or 0)} 次 / 负样本导师卖 {int(cur['m_sell_neg5'] or 0)} 次"
                                      if pd.notna(cur["m_sell_pos5"]) else "无导师数据")
    try:
        mf = OUT / "meta_eval_hybrid.json"
        me = json.loads((mf if mf.exists() else OUT / "meta_eval.json").read_text(encoding="utf-8"))
        a = me["样本外"]["全部"]
        bt = me["样本外"].get("按票型", {}).get(TYPES[int(cur["typ"])], {})
        act = me["样本外"].get("活跃平常票(票型 8~9 且近20日≥2次涨停)")
        if not strong and cur["zt_n20"] >= 2 and act:   # 票型是箱体震荡 / 趋势但近 20 日 ≥2 次涨停: 全体趋势票的命中率(95%)会高估, 用活跃平常票这一档
            bt = {"口径": "活跃平常票(票型 8~9 且近20日≥2次涨停)", "n": act["单日_模型"]["n"], "单日top3_模型": act["单日_模型"]["top3"],
                  "单日top3_票型基线": act["单日_基线票型"]["top3"], "单日logloss_模型": act["单日_模型"]["logloss"], "单日logloss_票型基线": act["单日_基线票型"]["logloss"],
                  "两日top3_模型": act["两日_模型"]["top3"], "两日top3_票型基线": act["两日_基线票型"]["top3"]}
        out["样本外"] = {"测试期": me["测试"], "单日 top3 命中 模型 / 票型基线 / 全市场基线": [a["单日_模型"]["top3"], a["单日_基线票型"]["top3"], a["单日_基线全市场"]["top3"]],
                      "单日 logloss 模型 / 票型基线 / 全市场基线": [a["单日_模型"]["logloss"], a["单日_基线票型"]["logloss"], a["单日_基线全市场"]["logloss"]],
                      "两日 top3 命中 模型 / 票型基线": [a["两日_模型"]["top3"], a["两日_基线票型"]["top3"]],
                      "本票型": bt}
        conf_top3 = sum(p1[k] for k in top1)
        h = bt.get("单日top3_模型", 0)
        out["置信"] = ("高" if conf_top3 >= 0.85 and h >= 0.85 else "中" if conf_top3 >= 0.65 and h >= 0.65 else "低") + \
            f"(top3 合计 {conf_top3:.0%}; 本票型样本外 top3 命中 {h:.0%}, n={bt.get('n', '?')})"
    except Exception as e:   # noqa: BLE001
        out["样本外"] = {"err": repr(e)}
    return out


def brief(o):
    """打印用: 分钟数组只留点数"""
    if isinstance(o, dict):
        return {k: (f"{len(v)} 点" if isinstance(v, list) and len(v) > 50 else brief(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [brief(x) for x in o]
    return o


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    return str(o)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = sys.argv[1:]
    if a and a[0] == "build":
        F.build()
    elif a and a[0] == "all":   # 每晚: 特征表全量重建 + 两个模型(eval + prod) + 混合样本外评估, 约 6 分钟
        F.build()
        _FEAT.clear()
        train(variant="stronghot_core")
        train(variant="nomkt_core")
        eval_hybrid()
    elif a and a[0] == "eval_hybrid":
        eval_hybrid(a[1] if len(a) > 1 and not a[1].startswith("--") else "stronghot_core", "--hotroute" in a,
                    a[2] if len(a) > 2 and not a[2].startswith("--") else "nomkt_core")
    elif a and a[0] == "train":
        train(prod="--no-prod" not in a, variant=a[a.index("--variant") + 1] if "--variant" in a else "bin")
    else:
        print(json.dumps(brief(scen(a[0], a[1])), ensure_ascii=False, indent=1, default=_json_default))
