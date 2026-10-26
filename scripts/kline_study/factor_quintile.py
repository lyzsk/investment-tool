"""《量化投资策略》(托托里罗)第 9 章价格动量因子在 A 股的五分位检验(只读本地缓存, 不写业务库).

因子(只用价格, 本库可算; 全部用到 t 日收盘为止的数据):
  R52   52 周价格范围位置 = (收 − 250 日最低) / (250 日最高 − 250 日最低)          书: 最强最稳的动量因子
  RS7   7 个月相对强弱 = 收 / 147 根前收 − 1, 按日横截面排名                        书: 短期 RS 最优周期
  RSI28W 28 周 RSI(周线收盘, 只用已收完的周)                                        书: 28 周最高分位
  R20   20 日价格范围位置(A 股短线对照, 非书中因子)
口径同 backtest_daily.py: T+1 开盘买, T+h 收盘卖(h = 1/3/5/20), 未扣成本; 股票池同(主板/创业板/科创板、当前非 ST、上市满 260 根、
收盘 >= 2、20 日均额 >= 3000 万); 信号日 2024-10-24 ~ 2026-10-15; 每个交易日横截面分 5 组(Q1 = 因子最高), 超额 = 减同日全池均值;
按日 t = 每日 Q 组平均超额的均值 / 标准误. 注意: 书中持有期 12 个月且每年/每季度调仓, 本检验是短线持有, 口径不同.
输出: skills/market-skill/references/kline_study/backtest_factor.md
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

import kline_defs as K

CACHE = Path("C:/Users/admin/dev/_kline_extract/cache")
DOCS = Path(__file__).resolve().parents[2] / "skills" / "market-skill" / "references" / "kline_study"
START, END, SPLIT = pd.Timestamp("2024-10-24"), pd.Timestamp("2026-10-15"), pd.Timestamp("2025-10-23")
H = (1, 3, 5, 20)
FACT = {"R52": "52 周价格范围位置", "RS7": "7 个月相对强弱(147 根涨幅)", "RSI28W": "28 周 RSI(周线)", "R20": "20 日价格范围位置(短线对照)"}


def weekly_rsi(g: pd.DataFrame, n: int = 28) -> pd.Series:
    c = g.set_index("trade_date")["aclose"]
    wk = c.resample("W-FRI").last().dropna()
    d = wk.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d).clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rsi = 100 - 100 / (1 + up / dn)
    # 只用已收完的周: 某日可用的是"上一个周五及之前"的 RSI, 周五当天收盘后本周完成可用
    rsi_daily = rsi.reindex(c.index, method="ffill")
    return pd.Series(rsi_daily.values, index=g.index)


def process(g: pd.DataFrame) -> pd.DataFrame:
    g = K.base_features(g)
    c, h, l = g["aclose"], g["ahigh"], g["alow"]
    hi250, lo250 = h.rolling(250, min_periods=250).max(), l.rolling(250, min_periods=250).min()
    hi20, lo20 = h.rolling(20, min_periods=20).max(), l.rolling(20, min_periods=20).min()
    out = pd.DataFrame({
        "symbol": g["symbol"], "name": g["name"], "trade_date": g["trade_date"],
        "R52": (c - lo250) / (hi250 - lo250),
        "RS7": c / c.shift(147) - 1,
        "RSI28W": weekly_rsi(g),
        "R20": (c - lo20) / (hi20 - lo20),
    })
    o1 = g["aopen"].shift(-1)
    unbuy = (g["one_word"] & g["close_lu"]).shift(-1, fill_value=False)
    badw = g["bad"].astype(int).rolling(2, min_periods=1).max()
    for hh in H:
        bad_f = g["bad"].astype(int)[::-1].rolling(hh, min_periods=1).max()[::-1].shift(-1)
        gapd = (g["trade_date"].shift(-hh) - g["trade_date"]).dt.days
        ok = (~unbuy) & (badw == 0) & (bad_f == 0) & (gapd <= 1.6 * hh + 9)
        out[f"r{hh}"] = (c.shift(-hh) / o1 - 1).where(ok)
    uni = (g["is_st"] == 0) & (g["idx"] >= 260) & (g["close"] >= 2) & (g["amt20"] >= 3e7) & (~g["bad"]) & \
        (g["trade_date"] >= START) & (g["trade_date"] <= END)
    return out[uni]


def main():
    t0 = time.time()
    d = pd.read_parquet(CACHE / "kline_day_2023-06-01_2026-10-23.parquet")
    parts = [process(g) for _, g in d.groupby("symbol", sort=False) if len(g) >= 300]
    ev = pd.concat(parts, ignore_index=True)
    print("rows", len(ev), round(time.time() - t0, 1), flush=True)
    for hh in H:
        ev[f"ex{hh}"] = ev[f"r{hh}"] - ev.groupby("trade_date")[f"r{hh}"].transform("mean")
    for f in FACT:
        ev[f"q_{f}"] = ev.groupby("trade_date")[f].transform(
            lambda s: pd.qcut(s.rank(method="first", ascending=False), 5, labels=False) + 1 if s.notna().sum() >= 50 else np.nan)
    ev.to_parquet(CACHE / "factor_events.parquet")
    L = ["<!-- 由 scripts/kline_study/factor_quintile.py 生成 -->\n",
         "口径: 每个交易日横截面按因子分 5 组, Q1 = 因子值最高; T+1 开盘买、T+h 收盘卖; 超额 = 减同日全池均值; 按日 = 先按日期平均再平均; "
         "t = 按日均值 / 标准误; **未扣成本**(往返约 0.2%)。信号日 2024-10-24~2026-10-15(h20 实际截至约 2026-09-15)。单位 %。\n"]
    for f, cn in FACT.items():
        L.append(f"## {cn} (`{f}`)\n")
        L.append("| 组 | h | n | 原始均值 | 中位 | P10 | P90 | 胜率 | 按日超额 | t | P1 按日 | P2 按日 |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for hh in H:
            for q in (1, 2, 3, 4, 5):
                e = ev[ev[f"q_{f}"] == q].dropna(subset=[f"r{hh}"])
                r = e[f"r{hh}"] * 100
                dd = e.groupby("trade_date")[f"ex{hh}"].mean() * 100
                t = dd.mean() / (dd.std(ddof=1) / np.sqrt(len(dd)))
                p1 = e[e.trade_date <= SPLIT].groupby("trade_date")[f"ex{hh}"].mean().mean() * 100
                p2 = e[e.trade_date > SPLIT].groupby("trade_date")[f"ex{hh}"].mean().mean() * 100
                L.append(f"| Q{q} | {hh} | {len(e)} | {r.mean():.2f} | {r.median():.2f} | {r.quantile(.1):.2f} | {r.quantile(.9):.2f} | "
                         f"{(r > 0).mean() * 100:.1f} | {dd.mean():.2f} | {t:.1f} | {p1:.2f} | {p2:.2f} |")
            # Q1 − Q5 多空
            a = ev[ev[f"q_{f}"] == 1].groupby("trade_date")[f"ex{hh}"].mean()
            b = ev[ev[f"q_{f}"] == 5].groupby("trade_date")[f"ex{hh}"].mean()
            ls = (a - b).dropna() * 100
            L.append(f"| **Q1−Q5** | {hh} | {len(ls)} 日 |  |  |  |  |  | {ls.mean():.2f} | {ls.mean() / (ls.std(ddof=1) / np.sqrt(len(ls))):.1f} | "
                     f"{ls[ls.index <= SPLIT].mean():.2f} | {ls[ls.index > SPLIT].mean():.2f} |")
        e = ev[ev[f"q_{f}"] == 1].dropna(subset=["r5"])
        b, w = e.nlargest(3, "r5"), e.nsmallest(3, "r5")
        fm = lambda x: "；".join(f"{r.name}({r.symbol}) {r.trade_date:%Y-%m-%d} {r.r5 * 100:+.1f}%" for r in x.itertuples())
        L.append(f"\n- Q1 最好(h=5): {fm(b)}\n- Q1 最差(h=5): {fm(w)}\n")
    (DOCS / "backtest_factor.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(round(time.time() - t0, 1))


if __name__ == "__main__":
    main()
