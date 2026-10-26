"""《零起点 Python 大数据与量化交易》(zwQuant)第 8~9 章策略规则, 放进本项目回测口径做事件检验(只读本地缓存).
书中口径: 单只股票、信号日收盘价成交、持有到反向信号、不扣成本、2014/2015 起回测(含 2015 牛市).
本检验口径(同 backtest_daily.py): 全股票池, 信号"首次成立日"(状态由否转是) T+1 开盘买, T+h 收盘卖(h = 1/3/5/20), 未扣成本,
超额 = 减同日全池均值; 同时给"信号日收盘买"口径(书中口径, 涨停收盘剔除).
规则(书中原文):
  TUR  海龟: 收盘 > 前 30 日最高价(书: 买入; 卖出 = 收盘 < 前 15 日最低)
  KDJ1 K 值 > 90 买(书 9.3.1, 用国内 KDJ(9,3,3) 口径, 与 KChartView 一致)
  KDJ2 K 上穿 D(书 9.3.3)
  RSI  RSI14 > 70 买(书 9.4.2, 动量口径, 非超卖抄底)
  MACD1 MACD 柱(DIF−DEA) 由负转正(书 9.2.1 macd>0 买)
  MACD2 DIF 上穿 DEA(书 9.2.3)
输出: skills/market-skill/references/kline_study/backtest_zwquant.md
"""
from pathlib import Path

import numpy as np
import pandas as pd

import kline_defs as K

CACHE = Path("C:/Users/admin/dev/_kline_extract/cache")
DOCS = Path(__file__).resolve().parents[2] / "skills" / "market-skill" / "references" / "kline_study"
START, END, SPLIT = pd.Timestamp("2024-10-24"), pd.Timestamp("2026-10-15"), pd.Timestamp("2025-10-23")
H = (1, 3, 5, 20)
CN = {"TUR": "海龟: 收盘突破前 30 日最高", "KDJ1": "KDJ: K 上穿 90", "KDJ2": "KDJ: K 上穿 D",
      "RSI": "RSI14 上穿 70", "MACD1": "MACD 柱由负转正", "MACD2": "DIF 上穿 DEA(同 MACD1, 书中两种写法)"}


def process(g):
    g = K.base_features(g)
    c, h, l = g["aclose"], g["ahigh"], g["alow"]
    lo9, hi9 = l.rolling(9).min(), h.rolling(9).max()
    rsv = 100 * (c - lo9) / (hi9 - lo9)
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    d = k.ewm(alpha=1 / 3, adjust=False).mean()
    diff = c.diff()
    up = diff.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    dn = (-diff).clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rsi = 100 - 100 / (1 + up / dn)
    dif = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    hist = dif - dea
    cross = lambda s: s & ~s.shift(1, fill_value=True)
    ok = ~g["one_word"]
    S = pd.DataFrame({
        "TUR": cross(c > h.rolling(30).max().shift(1)),
        "KDJ1": cross(k > 90), "KDJ2": cross(k > d), "RSI": cross(rsi > 70),
        "MACD1": cross(hist > 0), "MACD2": cross(dif > dea),
    }).fillna(False) & ok.values[:, None]
    out = pd.concat([g[["symbol", "name", "trade_date"]], S], axis=1)
    o1 = g["aopen"].shift(-1)
    unbuy = (g["one_word"] & g["close_lu"]).shift(-1, fill_value=False)
    badw = g["bad"].astype(int).rolling(2, min_periods=1).max()
    for hh in H:
        bad_f = g["bad"].astype(int)[::-1].rolling(hh, min_periods=1).max()[::-1].shift(-1)
        gapd = (g["trade_date"].shift(-hh) - g["trade_date"]).dt.days
        valid = (badw == 0) & (bad_f == 0) & (gapd <= 1.6 * hh + 9)
        out[f"r{hh}"] = (c.shift(-hh) / o1 - 1).where(valid & ~unbuy)
        out[f"c{hh}"] = (c.shift(-hh) / c - 1).where(valid & ~g["close_lu"])
    uni = (g["is_st"] == 0) & (g["idx"] >= 130) & (g["close"] >= 2) & (g["amt20"] >= 3e7) & (~g["bad"]) & \
        (g["trade_date"] >= START) & (g["trade_date"] <= END)
    return out[uni]


def main():
    d = pd.read_parquet(CACHE / "kline_day_2023-06-01_2026-10-23.parquet")
    ev = pd.concat([process(g) for _, g in d.groupby("symbol", sort=False) if len(g) >= 200], ignore_index=True)
    for hh in H:
        ev[f"ex{hh}"] = ev[f"r{hh}"] - ev.groupby("trade_date")[f"r{hh}"].transform("mean")
        ev[f"exc{hh}"] = ev[f"c{hh}"] - ev.groupby("trade_date")[f"c{hh}"].transform("mean")
    ev.to_parquet(CACHE / "zw_events.parquet")
    L = ["<!-- 由 scripts/kline_study/backtest_zwquant.py 生成 -->\n",
         "口径: 信号首次成立日; T+1 开盘买、T+h 收盘卖; 超额 = 减同日全池均值; 按日 = 先按日期平均; t = 按日均值/标准误; "
         "收盘入场 = 信号日收盘买(书中口径, 涨停收盘剔除)的按日超额; **未扣成本**; 单位 %。\n",
         "| 规则 | h | n | 原始均值 | 中位 | P10 | P90 | 胜率 | 按日超额 | t | P1 按日 | P2 按日 | 收盘入场按日超额 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s, cn in CN.items():
        e0 = ev[ev[s]]
        for hh in H:
            e = e0.dropna(subset=[f"r{hh}"])
            r = e[f"r{hh}"] * 100
            dd = e.groupby("trade_date")[f"ex{hh}"].mean() * 100
            t = dd.mean() / (dd.std(ddof=1) / np.sqrt(len(dd)))
            p1 = dd[dd.index <= SPLIT].mean()
            p2 = dd[dd.index > SPLIT].mean()
            cc = e0.groupby("trade_date")[f"exc{hh}"].mean().mean() * 100
            L.append(f"| {cn} | {hh} | {len(e)} | {r.mean():.2f} | {r.median():.2f} | {r.quantile(.1):.2f} | {r.quantile(.9):.2f} | "
                     f"{(r > 0).mean() * 100:.1f} | {dd.mean():.2f} | {t:.1f} | {p1:.2f} | {p2:.2f} | {cc:.2f} |")
        e = e0.dropna(subset=["r5"])
        fm = lambda x: "；".join(f"{r.name}({r.symbol}) {r.trade_date:%Y-%m-%d} {r.r5 * 100:+.1f}%" for r in x.itertuples())
        L.append(f"| ↳ h5 最好: {fm(e.nlargest(2, 'r5'))}；最差: {fm(e.nsmallest(2, 'r5'))} |||||||||||||")
    (DOCS / "backtest_zwquant.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
