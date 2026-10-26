"""《Python 金融大数据分析》第 6/10/11 章方法 → 本库实证(只读本地缓存, 不写业务库).
A. 收益分布与尾部: 股票池日对数收益的偏度/峰度/JB 检验; 经验分位 vs 同均值同标准差正态分位; 历史 VaR / ES(条件 VaR)
   (1 日 close-close, 5 日 T+1 开盘 → T+5 收盘); 分板块(10cm / 20cm).
B. 做 T 振幅预测与区间覆盖: 次日振幅 amp = (高−低)/昨收. 用 t−1 及以前的信息预测:
   ATR20%、近 30 日振幅中位、EWMA(λ=0.94, RiskMetrics) 振幅; 评估 |log(实际/预测)| 中位误差、
   近 30 日振幅 [P10, P90] 区间的实际覆盖率(应为 80%)、正态假设 1.28σ 区间覆盖率;
   条件: 昨日振幅分位(波动聚集)、前 5 日涨跌(杠杆效应).
口径: 股票池同 backtest_daily(主板/创业板/科创板, 当前非 ST, 上市满 130 根, 收盘 >= 2, 20 日均额 >= 3000 万);
日期 2024-10-24 ~ 2026-10-15; 一字板日不计入振幅评估(无振幅); 未扣成本(本节不涉及交易).
输出: skills/market-skill/references/kline_study/stat_tails_amplitude.md
"""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

CACHE = Path("C:/Users/admin/dev/_kline_extract/cache")
DOCS = Path(__file__).resolve().parents[2] / "skills" / "market-skill" / "references" / "kline_study"
START, END = pd.Timestamp("2024-10-24"), pd.Timestamp("2026-10-15")


def prep():
    d = pd.read_parquet(CACHE / "kline_day_2023-06-01_2026-10-23.parquet")
    d = d.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    g = d.groupby("symbol", sort=False)
    pc = d["pre_close"].fillna(g["close"].shift(1))
    d["lr"] = np.log(d["close"] / pc)
    d["amp"] = (d["high"] - d["low"]) / pc
    tr = np.maximum.reduce([d["high"] - d["low"], (d["high"] - pc).abs(), (d["low"] - pc).abs()]) / pc
    d["trp"] = tr
    d["idx"] = g.cumcount()
    lim = np.where(d["board_type"].isin(["GEM", "STAR"]), 0.2, np.where(d["is_st"] == 1, 0.05, 0.1))
    d["bad"] = (d["close"] / pc - 1).abs() > lim + 0.015
    d["one_word"] = (d["high"] - d["low"]).abs() < 1e-9
    d["amt20"] = g["amount"].transform(lambda s: s) if False else (d["volume"] * d["close"])
    d["amt20"] = d.groupby("symbol")["amt20"].transform(lambda s: s.rolling(20, min_periods=20).mean().shift(1))
    # 预测量(只用 t−1 及以前)
    d["p_atr"] = d.groupby("symbol")["trp"].transform(lambda s: s.rolling(20, min_periods=20).mean().shift(1))
    d["p_med30"] = d.groupby("symbol")["amp"].transform(lambda s: s.rolling(30, min_periods=30).median().shift(1))
    d["p_q10"] = d.groupby("symbol")["amp"].transform(lambda s: s.rolling(30, min_periods=30).quantile(0.1).shift(1))
    d["p_q90"] = d.groupby("symbol")["amp"].transform(lambda s: s.rolling(30, min_periods=30).quantile(0.9).shift(1))
    d["p_ewma"] = d.groupby("symbol")["amp"].transform(lambda s: s.ewm(alpha=0.06, adjust=False, min_periods=20).mean().shift(1))
    d["p_sd30"] = d.groupby("symbol")["amp"].transform(lambda s: s.rolling(30, min_periods=30).std().shift(1))
    d["p_mu30"] = d.groupby("symbol")["amp"].transform(lambda s: s.rolling(30, min_periods=30).mean().shift(1))
    d["amp_rank_prev"] = d.groupby("symbol")["amp"].transform(lambda s: s.rolling(60, min_periods=60).rank(pct=True).shift(1))
    d["r5_prev"] = d.groupby("symbol")["close"].transform(lambda s: s.shift(1) / s.shift(6) - 1)
    # 5 日持有收益: T+1 开盘 → T+5 收盘(复权用 close/pre_close 链: 这里用原始价并剔除窗口内有除权的日子近似)
    d["fac"] = (pc / d.groupby("symbol")["close"].shift(1)).fillna(1.0)
    d["xr"] = (d["fac"] - 1).abs() > 1e-4   # 当日除权
    o1 = d.groupby("symbol")["open"].shift(-1)
    c5 = d.groupby("symbol")["close"].shift(-5)
    xr5 = d.groupby("symbol")["xr"].transform(lambda s: s[::-1].rolling(5, min_periods=1).max()[::-1].shift(-1)).fillna(1) > 0
    d["r5"] = (c5 / o1 - 1).where(~xr5)
    uni = (d["is_st"] == 0) & (d["idx"] >= 130) & (d["close"] >= 2) & (d["amt20"] >= 3e7) & (~d["bad"]) & \
        (d["trade_date"] >= START) & (d["trade_date"] <= END)
    return d[uni].copy()


def tail_table(x, name):
    x = x.dropna().values
    mu, sd = x.mean(), x.std()
    qs = [0.01, 0.05, 0.10, 0.90, 0.95, 0.99]
    emp = np.quantile(x, qs)
    nor = stats.norm.ppf(qs, mu, sd)
    var95, var99 = -np.quantile(x, 0.05), -np.quantile(x, 0.01)
    es95, es99 = -x[x <= -var95].mean(), -x[x <= -var99].mean()
    nv95, nv99 = -(mu + sd * stats.norm.ppf(0.05)), -(mu + sd * stats.norm.ppf(0.01))
    row = [name, len(x), mu * 100, sd * 100, stats.skew(x), stats.kurtosis(x)] + list(emp * 100) + list(nor * 100) + \
          [var95 * 100, nv95 * 100, es95 * 100, var99 * 100, nv99 * 100, es99 * 100]
    return row


def main():
    d = prep()
    L = ["<!-- 由 scripts/kline_study/stat_tails_amplitude.py 生成 -->\n",
         f"股票池同 backtest_daily, {d.trade_date.min():%Y-%m-%d}~{d.trade_date.max():%Y-%m-%d}, {len(d)} 个股票日。单位 %。\n"]
    # ---------- A ----------
    L.append("## A. 收益分布与尾部(经验 vs 同均值同标准差的正态)\n")
    L.append("| 序列 | n | 均值 | 标准差 | 偏度 | 超额峰度 | 经验 P1 | P5 | P10 | P90 | P95 | P99 | 正态 P1 | P5 | P10 | P90 | P95 | P99 | 历史 VaR95 | 正态 VaR95 | ES95 | 历史 VaR99 | 正态 VaR99 | ES99 |")
    L.append("|---|" + "---|" * 23)
    rows = []
    for name, m in [("日对数收益·全部", slice(None)), ("日对数收益·主板(10cm)", d.board_type == "MAIN"),
                    ("日对数收益·创业板/科创板(20cm)", d.board_type.isin(["GEM", "STAR"]))]:
        rows.append(tail_table(d.loc[m, "lr"], name))
    rows.append(tail_table(d["r5"], "5 日持有(T+1 开 → T+5 收)·全部"))
    # 信号级: 读 events.parquet 的关键信号
    ev = pd.read_parquet(CACHE / "events.parquet")
    for sig, cn in [("N1_gap_hold3", "信号 N1 上升窗口 h5"), ("W8_UT", "信号 W8 UT h5")]:
        rows.append(tail_table(ev.loc[ev[sig], "r5"], cn))
    for r in rows:
        L.append("| " + r[0] + " | " + str(r[1]) + " | " + " | ".join(f"{v:.2f}" for v in r[2:]) + " |")
    jb = stats.jarque_bera(d["lr"].dropna().values)
    L.append(f"\nJarque-Bera(全部日对数收益): 统计量 {jb.statistic:.0f}, p = {jb.pvalue:.2g} → 强烈拒绝正态。\n")

    # ---------- B ----------
    e = d[(~d["one_word"]) & d["p_atr"].notna() & d["p_med30"].notna() & d["p_ewma"].notna()].copy()
    a = e["amp"]
    L.append("## B. 做 T: 次日振幅的预测误差与区间覆盖(一字板剔除)\n")
    L.append(f"次日振幅 n = {len(e)}, 中位 {a.median() * 100:.2f}%, 均值 {a.mean() * 100:.2f}%, P10 {a.quantile(.1) * 100:.2f}%, P90 {a.quantile(.9) * 100:.2f}%\n")
    L.append("| 预测量(t−1 可知) | 实际/预测 中位 | 实际/预测 P10 | P90 | \\|log(实际/预测)\\| 中位 | 与实际振幅的秩相关 |")
    L.append("|---|---|---|---|---|---|")
    for p, cn in [("p_atr", "ATR20%(真实波幅 20 日均)"), ("p_med30", "近 30 日振幅中位"), ("p_ewma", "EWMA 振幅(λ=0.94)")]:
        ratio = a / e[p]
        L.append(f"| {cn} | {ratio.median():.2f} | {ratio.quantile(.1):.2f} | {ratio.quantile(.9):.2f} | "
                 f"{np.abs(np.log(ratio)).median():.3f} | {stats.spearmanr(a, e[p]).statistic:.3f} |")
    cov_emp = ((a >= e["p_q10"]) & (a <= e["p_q90"])).mean()
    lo_n, hi_n = e["p_mu30"] - 1.2816 * e["p_sd30"], e["p_mu30"] + 1.2816 * e["p_sd30"]
    cov_nor = ((a >= lo_n) & (a <= hi_n)).mean()
    below = (a < e["p_q10"]).mean()
    above = (a > e["p_q90"]).mean()
    L.append(f"\n**80% 区间覆盖率**: 近 30 日振幅经验 [P10, P90] → 实际覆盖 {cov_emp * 100:.1f}%(低于下沿 {below * 100:.1f}%, 高于上沿 {above * 100:.1f}%); "
             f"正态 μ±1.28σ(30 日) → 覆盖 {cov_nor * 100:.1f}%。\n")
    L.append("### B2. 条件: 波动聚集(昨日振幅在自身近 60 日的分位) 与 杠杆效应(前 5 日涨跌)\n")
    L.append("| 条件 | n | 次日振幅中位 | 实际/近30日中位 的中位 | 次日振幅 > 近 30 日 P90 的比例 |")
    L.append("|---|---|---|---|---|")
    e["amp_bucket"] = pd.cut(e["amp_rank_prev"], [0, .2, .4, .6, .8, 1.0001], labels=["0~20%", "20~40%", "40~60%", "60~80%", "80~100%"], right=False)
    for b in ["0~20%", "20~40%", "40~60%", "60~80%", "80~100%"]:
        x = e[e.amp_bucket == b]
        L.append(f"| 昨日振幅分位 {b} | {len(x)} | {x.amp.median() * 100:.2f}% | {(x.amp / x.p_med30).median():.2f} | {(x.amp > x.p_q90).mean() * 100:.1f}% |")
    for cn, m in [("前 5 日跌 > 5%", e.r5_prev < -0.05), ("前 5 日 −5%~0", (e.r5_prev >= -0.05) & (e.r5_prev < 0)),
                  ("前 5 日 0~+5%", (e.r5_prev >= 0) & (e.r5_prev < 0.05)), ("前 5 日涨 > 5%", e.r5_prev >= 0.05)]:
        x = e[m]
        L.append(f"| {cn} | {len(x)} | {x.amp.median() * 100:.2f}% | {(x.amp / x.p_med30).median():.2f} | {(x.amp > x.p_q90).mean() * 100:.1f}% |")
    (DOCS / "stat_tails_amplitude.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
