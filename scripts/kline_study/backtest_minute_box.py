"""分钟级箱体试验(只读): 从 investment_market.kline_minute(1 分钟, 2026-10-09~10-23, 约 1100 只) 合成 15/30 分钟 K 线,
用与日线相同的箱体算法(摆动点中位数 + ATR 宽度约束 + 收盘包含率), 统计:
  - 放量突破箱顶(JOC 型) / 无量突破 / 刺破箱底收回(Spring 型) / 收盘跌破箱底
  后 4、8 根 K 线的收益(以信号 K 线收盘价入场), 与同周期全部 K 线基准对比.
样本只有 11 个交易日, 结论仅作方向参考(低置信).
"""
from pathlib import Path

import numpy as np
import pandas as pd

import db_ro
import kline_defs as K

CACHE = Path("C:/Users/admin/dev/_kline_extract/cache")
DOCS = Path(__file__).resolve().parents[2] / "skills" / "market-skill" / "references" / "kline_study"


def load():
    f = CACHE / "kline_minute.parquet"
    if f.exists():
        return pd.read_parquet(f)
    d = db_ro.query("select symbol, bar_time, open, high, low, close, volume from kline_minute where is_deleted=0")
    for c in ["open", "high", "low", "close", "volume"]:
        d[c] = pd.to_numeric(d[c]).astype(float)
    d["bar_time"] = pd.to_datetime(d["bar_time"])
    d.to_parquet(f)
    return d


def resample(g, rule):
    g = g.set_index("bar_time")
    # A 股 09:30 那根为集合竞价, 并入第一根; 按自然 15/30 分钟切, 午休自然断开
    r = g.resample(rule, label="right", closed="right", offset="0min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])
    return r.reset_index()


def study(bars: pd.DataFrame, lookback: int, k: int = 2):
    out = []
    for sym, g in bars.groupby("symbol", sort=False):
        g = g.sort_values("bar_time").reset_index(drop=True)
        if len(g) < lookback + 20:
            continue
        h, l, c, o, v = (g[x].values.astype(float) for x in ["high", "low", "close", "open", "volume"])
        pc = np.r_[np.nan, c[:-1]]
        tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
        atr = pd.Series(tr).rolling(14, min_periods=14).mean().shift(1).values
        vma = pd.Series(v).rolling(20, min_periods=20).mean().shift(1).values
        R, S, _, _ = K._box_numba(h, l, c, np.nan_to_num(atr), k, lookback, 1.5, 8.0, 0.8)
        f4 = pd.Series(c).shift(-4).values / c - 1
        f8 = pd.Series(c).shift(-8).values / c - 1
        df = pd.DataFrame({"symbol": sym, "t": g["bar_time"], "f4": f4, "f8": f8, "R": R, "S": S, "atr": atr,
                           "vr": v / vma, "c": c, "h": h, "l": l, "o": o})
        out.append(df)
    e = pd.concat(out, ignore_index=True)
    e = e[e["atr"] > 0]
    has = e["R"].notna()
    above_prev = e.groupby("symbol")["c"].shift(1) > e.groupby("symbol")["R"].shift(1)
    ev = {
        "全部K线(基准)": np.ones(len(e), bool),
        "有效箱体内全部K线": has.values,
        "放量突破箱顶(收盘>R+0.3ATR, 量>=1.5倍)": (has & (e.c >= e.R + 0.3 * e.atr) & (e.vr >= 1.5) & ~above_prev).values,
        "无量突破箱顶(量<1.0倍)": (has & (e.c >= e.R + 0.3 * e.atr) & (e.vr < 1.0) & ~above_prev).values,
        "刺破箱底收回(Spring型)": (has & (e.l <= e.S - 0.1 * e.atr) & (e.l >= e.S - 1.5 * e.atr) & (e.c > e.S)).values,
        "收盘跌破箱底(>0.3ATR)": (has & (e.c <= e.S - 0.3 * e.atr)).values,
        "触及箱底附近(低<=S+0.25ATR, 收>S)": (has & (e.l <= e.S + 0.25 * e.atr) & (e.c > e.S)).values,
        "触及箱顶附近(高>=R-0.25ATR, 收<R)": (has & (e.h >= e.R - 0.25 * e.atr) & (e.c < e.R)).values,
    }
    e["day"] = e["t"].dt.normalize()
    rows = []
    for name, m in ev.items():
        x = e[m]
        r = []
        for col in ["f4", "f8"]:
            y = x[["day", col]].dropna()
            dd = y.groupby("day")[col].mean()
            r += [len(y), y[col].mean() * 100, y[col].median() * 100, y[col].quantile(.1) * 100, y[col].quantile(.9) * 100,
                  (y[col] > 0).mean() * 100, dd.mean() * 100, len(dd)]
        rows.append([name] + r)
    return rows


def main():
    d = load()
    print("minute rows", len(d), d.symbol.nunique(), d.bar_time.dt.date.nunique())
    L = ["<!-- 由 scripts/kline_study/backtest_minute_box.py 生成 -->\n",
         f"数据: kline_minute 1 分钟, {d.bar_time.min():%Y-%m-%d}~{d.bar_time.max():%Y-%m-%d}, {d.symbol.nunique()} 只, "
         f"{d.bar_time.dt.date.nunique()} 个交易日(前几日覆盖股票少)。入场 = 信号 K 线收盘价; 收益 = 后 4/8 根 K 线收盘; 未扣成本; "
         "**A 股 T+1: 当日买入当日不能卖, 分钟级结论只适用于有底仓做 T 或次日了结。** 单位 %。\n"]
    for rule, lb, cn in [("15min", 32, "15 分钟(箱体回看 32 根≈2 天)"), ("30min", 24, "30 分钟(箱体回看 24 根≈3 天)"),
                         ("5min", 48, "5 分钟(箱体回看 48 根≈1 天)")]:
        bars = d.groupby("symbol", group_keys=False).apply(lambda g: resample(g, rule).assign(symbol=g.name))
        rows = study(bars, lb)
        L.append(f"## {cn}\n")
        L.append("| 事件 | n(4根) | 均值 | 中位 | P10 | P90 | 胜率 | 按日均值 | 日数 | n(8根) | 均值 | 中位 | P10 | P90 | 胜率 | 按日均值 | 日数 |")
        L.append("|---|" + "---|" * 16)
        for r in rows:
            L.append("| " + r[0] + " | " + " | ".join(f"{x:.0f}" if i in (0, 7, 8, 15) else f"{x:.2f}" for i, x in enumerate(r[1:])) + " |")
        L.append("")
        print("\n".join(L[-len(rows) - 3:]))
    (DOCS / "backtest_minute.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
