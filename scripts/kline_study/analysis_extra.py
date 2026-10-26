"""补充分析(只读本地缓存 events.parquet): 检验书中关键主张.
A. Spring/JOC/LPS 是否只在"上升背景"有效(孟洪涛: 熊市中的 Spring 是陷阱)
B. 收盘位置(当日收在区间哪里)与次日表现(Morris: 上吊线/倒锤优于锤子/流星)
C. 库林"确认/异常"格子: 实体相对大小 × 成交量相对大小
输出: skills/market-skill/references/kline_study/backtest_extra.md
"""
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path("C:/Users/admin/dev/_kline_extract/cache")
DOCS = Path(__file__).resolve().parents[2] / "skills" / "market-skill" / "references" / "kline_study"
SPLIT = pd.Timestamp("2025-10-23")


def agg(e, col="ex5"):
    x = e[["trade_date", col]].dropna()
    if len(x) == 0:
        return dict(n=0)
    d = x.groupby("trade_date")[col].mean()
    t = d.mean() / (d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 2 and d.std() > 0 else np.nan
    return dict(n=len(x), nd=len(d), ex=x[col].mean() * 100, dex=d.mean() * 100, t=t,
                med=x[col].median() * 100, p10=x[col].quantile(.1) * 100, p90=x[col].quantile(.9) * 100)


def row(name, e, cols=("ex1", "ex3", "ex5")):
    p1, p2 = e[e.trade_date <= SPLIT], e[e.trade_date > SPLIT]
    cells = []
    for c in cols:
        a = agg(e, c)
        if a["n"] == 0:
            cells.append(" | | ")
            continue
        cells.append(f"{a['ex']:.2f} | {a['dex']:.2f} | {a['t']:.1f}")
    a1, a2 = agg(p1, "ex5"), agg(p2, "ex5")
    f = lambda a: f"{a['dex']:.2f}" if a["n"] else ""
    return f"| {name} | {len(e)} | " + " | ".join(cells) + f" | {f(a1)} | {f(a2)} |"


HDR = ("| 分组 | n | h1 超额 | h1 按日 | h1 t | h3 超额 | h3 按日 | h3 t | h5 超额 | h5 按日 | h5 t | P1 h5 按日 | P2 h5 按日 |\n"
       "|---|---|---|---|---|---|---|---|---|---|---|---|---|")


def main():
    ev = pd.read_parquet(CACHE / "events.parquet")
    ev = ev[~ev["one_word"]]
    L = ["<!-- 由 scripts/kline_study/analysis_extra.py 生成 -->\n",
         "口径同 backtest_tables.md: T+1 开盘买, 超额=减同日全股票池均值, 按日=先按日期平均再平均, t=按日均值/标准误; 单位 %。\n"]

    L.append("## A. 背景依赖: 同一事件在\"上升背景\"(收盘>60日均线且均线10日上行) vs 其它\n")
    L.append(HDR)
    trend = ev["above_ma60"] & ev["ma60_up"]
    for sig, cn in [("W4_spring_lowvol", "Spring 缩量"), ("W5_spring_hivol", "Spring 放量"), ("W6_JOC", "JOC"),
                    ("W7_LPS", "LPS"), ("W8_UT", "UT"), ("K1_hammer", "锤子线"), ("K2_bull_engulf", "看涨吞没")]:
        L.append(row(f"{cn} · 上升背景", ev[ev[sig] & trend]))
        L.append(row(f"{cn} · 非上升背景", ev[ev[sig] & ~trend]))
    L.append(row("全部股票日 · 上升背景(对照)", ev[trend]))
    L.append(row("全部股票日 · 非上升背景(对照)", ev[~trend]))
    L.append("")

    L.append("## B. 收盘位置(收盘在当日高低区间的位置 0=最低 1=最高), 排除涨跌停收盘\n")
    L.append(HDR)
    e2 = ev[~ev["close_lu"] & ~ev["close_ld"] & (ev["rng_atr"] >= 0.8)]
    bins = [0, .1, .3, .5, .7, .9, 1.0001]
    lab = ["0~0.1", "0.1~0.3", "0.3~0.5", "0.5~0.7", "0.7~0.9", "0.9~1"]
    e2 = e2.assign(cp=pd.cut(e2["clpos"], bins, labels=lab, right=False))
    for b in lab:
        L.append(row(f"收盘位置 {b}", e2[e2.cp == b]))
    L.append("")
    L.append("### B2. 收盘位置 × 前置趋势(长下影/长上影在不同背景)\n")
    L.append(HDR)
    for ctx, cn in [("down_ctx", "下跌背景"), ("up_ctx", "上涨背景")]:
        for b in ["0~0.1", "0.9~1"]:
            L.append(row(f"{cn} · 收盘位置 {b}", e2[e2[ctx] & (e2.cp == b)]))
    L.append("")

    L.append("## C. 库林\"确认/异常\": 实体相对大小(实体/近10日平均实体) × 量比(量/20日均量), 仅阳线, 排除涨跌停收盘\n")
    L.append(HDR)
    e3 = e2[e2["bull"]]
    big = e3["body_rel"] >= 1.5
    small = e3["body_rel"] <= 0.5
    hv = e3["vr"] >= 1.5
    lv = e3["vr"] <= 0.8
    for m, cn in [(big & hv, "长阳+放量(确认)"), (big & lv, "长阳+缩量(异常: 库林称陷阱)"),
                  (small & hv, "小阳+放量(异常: 顶部吃力)"), (small & lv, "小阳+缩量(确认)")]:
        L.append(row(cn, e3[m]))
    e4 = e2[~e2["bull"]]
    big4, small4 = e4["body_rel"] >= 1.5, e4["body_rel"] <= 0.5
    hv4, lv4 = e4["vr"] >= 1.5, e4["vr"] <= 0.8
    for m, cn in [(big4 & hv4, "长阴+放量(确认)"), (big4 & lv4, "长阴+缩量(异常)"),
                  (small4 & hv4, "小阴+放量(异常: 下方有承接)"), (small4 & lv4, "小阴+缩量(确认)")]:
        L.append(row(cn, e4[m]))
    L.append("")
    (DOCS / "backtest_extra.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
