"""统计推断稳健性(《Python 金融大数据分析》第 10/11 章: 蒙特卡洛 / 正态性检验 / 自助法思路), 只读本地缓存.
对已有关键结论(h5 超额), 比较 4 种显著性口径:
  1) 按日聚类 t(现行): 每个信号日的平均超额 → 均值 / 标准误
  2) 按周聚类 t: 同一自然周的信号合并(h5 持有期跨周, 相邻日相关)
  3) 按日块自助法(block bootstrap, 块长 10 个交易日, 2000 次): 按日平均超额序列重采样 → 95% 置信区间与 P(均值 >= 0)
  4) 同日随机安慰剂(蒙特卡洛, 1000 次): 每个信号样本换成"同一天股票池里随机一只"→ 安慰剂均值分布 → 经验 p 值
     (控制"同日市场整体涨跌"这一共同因素; 回答"同一天随便买一只会不会也这样")
另报 h5 原始收益的偏度/峰度与 Jarque-Bera(说明为何不能用正态 t 当精确 p).
未扣成本. 输出: skills/market-skill/references/kline_study/stat_inference.md
"""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

CACHE = Path("C:/Users/admin/dev/_kline_extract/cache")
DOCS = Path(__file__).resolve().parents[2] / "skills" / "market-skill" / "references" / "kline_study"
rng = np.random.default_rng(20261024)


def block_boot(x: np.ndarray, block=10, B=2000):
    n = len(x)
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(B, nb))
    idx = (starts[:, :, None] + np.arange(block)).reshape(B, -1)[:, :n]
    m = x[idx].mean(axis=1)
    return np.percentile(m, [2.5, 97.5]), (m >= 0).mean()


def placebo(sig_dates: pd.Series, pool: pd.DataFrame, B=1000):
    # pool: trade_date -> array of ex5 for all stocks that day
    cnt = sig_dates.value_counts()
    means = np.zeros(B)
    arrs = {d: pool[d] for d in cnt.index if d in pool}
    tot = sum(cnt[d] for d in arrs)
    for b in range(B):
        s = 0.0
        for d, a in arrs.items():
            s += a[rng.integers(0, len(a), cnt[d])].sum()
        means[b] = s / tot
    return means


def analyze(name, e, pool):
    e = e.dropna(subset=["ex5"])
    x = e["ex5"].values
    dd = e.groupby("trade_date")["ex5"].mean()
    t_day = dd.mean() / (dd.std(ddof=1) / np.sqrt(len(dd)))
    wk = e.groupby(e["trade_date"].dt.to_period("W"))["ex5"].mean()
    t_wk = wk.mean() / (wk.std(ddof=1) / np.sqrt(len(wk)))
    ci, ppos = block_boot(dd.values)
    pl = placebo(e["trade_date"], pool)
    obs = x.mean()
    p_pl = ((pl <= obs).mean() if obs < 0 else (pl >= obs).mean())
    r = e["r5"].dropna().values
    jb = stats.jarque_bera(r)
    return [name, len(x), len(dd), len(wk), obs * 100, dd.mean() * 100, t_day, t_wk, ci[0] * 100, ci[1] * 100, ppos,
            pl.mean() * 100, np.percentile(pl, 2.5) * 100, np.percentile(pl, 97.5) * 100, p_pl, stats.skew(r), stats.kurtosis(r), jb.pvalue]


def main():
    ev = pd.read_parquet(CACHE / "events.parquet")
    ev = ev[~ev["one_word"]]
    pool = {d: g["ex5"].dropna().values for d, g in ev[["trade_date", "ex5"]].groupby("trade_date")}
    zw = pd.read_parquet(CACHE / "zw_events.parquet")
    e2 = ev[~ev.close_lu & ~ev.close_ld & (ev.rng_atr >= 0.8)]
    cases = [
        ("N1 上升窗口 3 日不补", ev[ev.N1_gap_hold3]),
        ("长阳+放量(非涨停收盘)", e2[e2.bull & (e2.body_rel >= 1.5) & (e2.vr >= 1.5)]),
        ("收盘在最高 10%(非涨停)", e2[e2.clpos >= 0.9]),
        ("UT · 上升背景", ev[ev.W8_UT & ev.above_ma60 & ev.ma60_up]),
        ("看涨吞没 K2", ev[ev.K2_bull_engulf]),
        ("放量 Spring W5", ev[ev.W5_spring_hivol]),
        ("JOC W6", ev[ev.W6_JOC]),
        ("SC W1", ev[ev.W1_SC]),
        ("海龟突破 30 日高(零起点)", zw[zw.TUR]),
        ("RSI14 上穿 70(零起点)", zw[zw.RSI]),
    ]
    zpool = {d: g["ex5"].dropna().values for d, g in zw[["trade_date", "ex5"]].groupby("trade_date")}
    rows = []
    for name, e in cases:
        rows.append(analyze(name, e, zpool if "零起点" in name else pool))
        print(rows[-1][:9], flush=True)
    L = ["<!-- 由 scripts/kline_study/stat_inference.py 生成 -->\n",
         "h5 超额(T+1 开盘买, 第 5 日收盘卖, 减同日全池均值), 未扣成本。单位 %。块自助: 按日平均超额序列, 块长 10 日, 2000 次; "
         "安慰剂: 每个样本换成同日随机一只股票, 1000 次。\n",
         "| 信号 | n | 日数 | 周数 | 样本超额均值 | 按日超额 | 按日 t | 按周 t | 块自助 95% 区间 | P(按日均值≥0) | 安慰剂均值 | 安慰剂 95% 区间 | 安慰剂 p | h5 偏度 | h5 超额峰度 | JB p |",
         "|---|" + "---|" * 15]
    for r in rows:
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]:.2f} | {r[5]:.2f} | {r[6]:.1f} | {r[7]:.1f} | [{r[8]:.2f}, {r[9]:.2f}] | "
                 f"{r[10]:.3f} | {r[11]:.2f} | [{r[12]:.2f}, {r[13]:.2f}] | {r[14]:.3f} | {r[15]:.2f} | {r[16]:.1f} | {r[17]:.1g} |")
    (DOCS / "stat_inference.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
