"""日线回测: 对 kline_defs.signals() 的每个信号统计 T+1 开盘买入、持有到 T+h 收盘(h=1/3/5)的收益分布.
只读本地缓存(由 load_daily.py 从 investment_market.kline_day SELECT 得到). 不写任何业务库.

口径:
- 信号日 t 收盘后可知; 入场 = t+1 开盘价(后复权); 出场 = t+h 收盘(后复权). 未扣交易成本(往返约 0.2%).
- t+1 一字涨停(买不到)的样本剔除; 窗口 [t-1, t+h] 内有数据异常日(涨跌幅超限)剔除.
- 股票池: 主板/创业板/科创板, 当前非 ST(security_master.is_st=0, 无历史 ST 标记, 有幸存偏差), 上市满 130 根,
  收盘价>=2, 近 20 日日均成交额(量*价) >= 3000 万.
- 样本期: 信号日 2024-10-24 ~ 2026-10-15; P1 = ~2025-10-23, P2 = 2025-10-24~.
- 基准: ①无条件: 同期股票池全部股票日; ②条件基准: 与信号同背景但不满足形态核心条件的股票日(见 CONTROLS).
  超额 = 信号收益 - 同一日期无条件基准均值.
输出: skills/market-skill/references/kline_study/backtest_tables.md(由本脚本生成的原始表) + _cache/events.parquet
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

import kline_defs as K

CACHE = Path("C:/Users/admin/dev/_kline_extract/cache")
DOCS = Path(__file__).resolve().parents[2] / "skills" / "market-skill" / "references" / "kline_study"
H = (1, 3, 5)
START, END, SPLIT = pd.Timestamp("2024-10-24"), pd.Timestamp("2026-10-15"), pd.Timestamp("2025-10-23")

SIG_CN = {
    "K1_hammer": "K1 锤子线(下跌背景+20日新低)",
    "K2_bull_engulf": "K2 看涨吞没(下跌背景)",
    "K3_morning_star": "K3 启明星(下跌背景)",
    "K4_doji_oversold": "K4 十字星+乖离超卖",
    "K5_bear_engulf": "K5 看跌吞没(上涨背景)[风险]",
    "K6_dark_cloud": "K6 乌云盖顶(上涨背景)[风险]",
    "W1_SC": "W1 SC 恐慌抛售",
    "W2_stop_vol": "W2 停止行为②放量不跌",
    "W3_SC_ST": "W3 SC 后缩量二次测试 ST",
    "W4_spring_lowvol": "W4 Spring 缩量(<=均量)",
    "W5_spring_hivol": "W5 Spring 放量(>=1.5均量)",
    "W6_JOC": "W6 JOC 放量突破箱顶",
    "W7_LPS": "W7 JOC 后缩量回踩 LPS",
    "W8_UT": "W8 UT 上冲回落[风险]",
    "W9_SOW": "W9 SOW 放量破箱底[风险]",
    "N1_gap_hold3": "N1 上升窗口3日不补",
    "N2_newhigh8": "N2 迭创新高第8根[风险]",
}
# 信号 -> 条件基准列
CONTROLS = {
    "K1_hammer": "C_down_low20", "K2_bull_engulf": "C_down", "K3_morning_star": "C_down2",
    "K4_doji_oversold": "C_oversold", "K5_bear_engulf": "C_up", "K6_dark_cloud": "C_up",
    "W1_SC": "C_sc_ctx", "W2_stop_vol": "C_down_low20", "W3_SC_ST": "C_down_low20",
    "W4_spring_lowvol": "C_pierce", "W5_spring_hivol": "C_pierce", "W6_JOC": "C_break", "W7_LPS": "C_box",
    "W8_UT": "C_poke", "W9_SOW": "C_breakdn", "N1_gap_hold3": "C_gap", "N2_newhigh8": "C_up",
}
CTRL_CN = {
    "C_down": "下跌背景全部日", "C_down2": "前2日为下跌背景的全部日", "C_down_low20": "下跌背景且触及20日低点的全部日",
    "C_oversold": "乖离<=自身10分位的全部日", "C_up": "上涨背景全部日", "C_sc_ctx": "20日跌势z<=-1.0且创60日新低的全部日",
    "C_pierce": "刺破箱底0.1~1.5ATR的全部日(含收不回)", "C_break": "收盘越过箱顶0.3ATR的全部日(不论量)",
    "C_box": "有效箱体存在的全部日", "C_poke": "高点越过箱顶0.2ATR的全部日(不论收盘)",
    "C_breakdn": "收盘跌破箱底0.3ATR的全部日(不论量)", "C_gap": "出现>=0.3ATR上升缺口的全部日",
}


def controls(g: pd.DataFrame) -> pd.DataFrame:
    C = pd.DataFrame(index=g.index)
    atr, l, h, c = g["atr"], g["alow"], g["ahigh"], g["aclose"]
    R, S = g["boxR"], g["boxS"]
    nw = ~g["one_word"]
    C["C_down"] = nw & g["down_ctx"]
    C["C_down2"] = nw & g["down_ctx"].shift(2, fill_value=False)
    C["C_down_low20"] = nw & g["down_ctx"] & (l <= g["low20"] + 0.5 * atr)
    C["C_oversold"] = nw & (g["bias20"] <= g["bias_q10"])
    C["C_up"] = nw & g["up_ctx"]
    C["C_sc_ctx"] = nw & (g["z20"] <= K.P["sc_ret_z"]) & (l <= g["low60"])
    C["C_pierce"] = nw & R.notna() & (l <= S - 0.1 * atr) & (l >= S - 1.5 * atr)
    C["C_break"] = nw & R.notna() & (c >= R + 0.3 * atr)
    C["C_box"] = nw & R.notna()
    C["C_poke"] = nw & R.notna() & (h >= R + 0.2 * atr)
    C["C_breakdn"] = nw & S.notna() & (c <= S - 0.3 * atr)
    gap = (l > h.shift(1)) & ((l - h.shift(1)) >= 0.3 * atr)
    C["C_gap"] = nw & gap
    return C.fillna(False).astype(bool)


def fwd(g: pd.DataFrame) -> pd.DataFrame:
    F = pd.DataFrame(index=g.index)
    o1 = g["aopen"].shift(-1)
    unbuy = (g["one_word"] & g["close_lu"]).shift(-1, fill_value=False)
    badw = g["bad"].astype(int).rolling(2, min_periods=1).max()   # t-1..t
    for hh in H:
        ret = g["aclose"].shift(-hh) / o1 - 1
        bad_f = g["bad"].astype(int)[::-1].rolling(hh, min_periods=1).max()[::-1].shift(-1)  # t+1..t+h
        gapd = (g["trade_date"].shift(-hh) - g["trade_date"]).dt.days
        valid = (~unbuy) & (badw == 0) & (bad_f == 0) & (gapd <= 2 * hh + 7)
        F[f"r{hh}"] = ret.where(valid)
        # 收盘入场口径(信号日尾盘买, 14:57 集合竞价可实现; 涨停收盘视为买不到)
        rc = g["aclose"].shift(-hh) / g["aclose"] - 1
        F[f"c{hh}"] = rc.where((badw == 0) & (bad_f == 0) & (gapd <= 2 * hh + 7) & (~g["close_lu"]))
    return F


def process(g: pd.DataFrame):
    g = K.base_features(g)
    g = K.add_box(g)
    S = K.signals(g)
    C = controls(g)
    F = fwd(g)
    uni = (g["is_st"] == 0) & (g["idx"] >= 130) & (g["close"] >= 2) & (g["amt20"] >= 3e7) & (~g["bad"]) & \
        (g["trade_date"] >= START) & (g["trade_date"] <= END)
    keep = uni
    c = g["aclose"]
    ma60 = c.rolling(60, min_periods=60).mean()
    feat = pd.DataFrame({
        "clpos": g["clpos"], "vr": g["vr"], "rng_atr": g["rng_atr"], "body_rel": g["body"] / g["avg_body"],
        "bull": c > g["aopen"], "up_ctx": g["up_ctx"], "down_ctx": g["down_ctx"],
        "above_ma60": c > ma60, "ma60_up": ma60 > ma60.shift(10), "close_lu": g["close_lu"], "close_ld": g["close_ld"],
        "one_word": g["one_word"], "z20": g["z20"], "board": g["board_type"],
    }, index=g.index)
    out = pd.concat([g.loc[keep, ["symbol", "name", "board_type", "trade_date"]], F[keep], S[keep], C[keep],
                     feat.loc[keep].drop(columns=["board"])], axis=1)
    return out


def stats(r: np.ndarray, ex: np.ndarray):
    r = r[~np.isnan(r)]
    ex = ex[~np.isnan(ex)]
    if len(r) == 0:
        return dict(n=0)
    return dict(n=len(r), mean=r.mean() * 100, median=np.median(r) * 100, p10=np.percentile(r, 10) * 100,
                p90=np.percentile(r, 90) * 100, win=(r > 0).mean() * 100,
                ex_mean=ex.mean() * 100 if len(ex) else np.nan, ex_median=np.median(ex) * 100 if len(ex) else np.nan)


def main(limit=None):
    t0 = time.time()
    if limit == "report":
        ev = pd.read_parquet(CACHE / "events.parquet")
        report(ev)
        return
    d = pd.read_parquet(CACHE / "kline_day_2023-06-01_2026-10-23.parquet")
    syms = d["symbol"].unique()
    if limit:
        syms = syms[: int(limit)]
    parts = []
    for i, (sym, g) in enumerate(d[d["symbol"].isin(syms)].groupby("symbol", sort=False)):
        if len(g) < 200:
            continue
        parts.append(process(g))
        if i % 500 == 0:
            print(i, round(time.time() - t0, 1), flush=True)
    ev = pd.concat(parts, ignore_index=True)
    # 无条件基准: 每日横截面均值
    for hh in H:
        bm = ev.groupby("trade_date")[f"r{hh}"].transform("mean")
        ev[f"ex{hh}"] = ev[f"r{hh}"] - bm
        bmc = ev.groupby("trade_date")[f"c{hh}"].transform("mean")
        ev[f"exc{hh}"] = ev[f"c{hh}"] - bmc
    ev.to_parquet(CACHE / ("events_sample.parquet" if limit else "events.parquet"))
    print("events rows", len(ev), round(time.time() - t0, 1))
    report(ev, limit)


def fmt(x, nd=2):
    return "" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


def date_cluster(es: pd.DataFrame, col: str):
    """按日期聚合: 先算每个日期的平均超额, 再对日期求均值和 t 值(同日多只股票不算独立样本)."""
    x = es[["trade_date", col]].dropna().groupby("trade_date")[col].mean()
    if len(x) < 3:
        return np.nan, np.nan
    m = x.mean()
    se = x.std(ddof=1) / np.sqrt(len(x))
    return m * 100, (m / se if se > 0 else np.nan)


def report(ev: pd.DataFrame, limit=None):
    lines = []
    lines.append(f"<!-- 由 scripts/kline_study/backtest_daily.py 生成; 行数 {len(ev)}; 生成于 {pd.Timestamp.now():%Y-%m-%d %H:%M} -->\n")
    periods = {"全期": ev, "P1": ev[ev.trade_date <= SPLIT], "P2": ev[ev.trade_date > SPLIT]}
    lines.append("P1 = 信号日 2024-10-24~2025-10-23; P2 = 2025-10-24~2026-10-15。收益单位 %, 未扣成本(往返约 0.2%)。\n")
    lines.append("列说明: 均值/中位/P10/P90/胜率 = T+1 开盘买、T+h 收盘卖的原始收益; 超额 = 减去同日全股票池均值; "
                 "按日超额 = 先按日期平均再平均(同日样本不独立), t = 按日超额 / 标准误; 条件基准超额 = 同背景对照组的超额均值; "
                 "收盘入场 = 信号日收盘买(涨停收盘剔除)的超额均值。\n")
    # 无条件基准
    lines.append("## 无条件基准(股票池全部股票日, T+1 开盘买)\n")
    lines.append("| 期间 | h | n | 均值% | 中位% | P10% | P90% | 胜率% | 超额中位%(随机股票的参照) |\n|---|---|---|---|---|---|---|---|---|")
    for pn, e in periods.items():
        for hh in H:
            s = stats(e[f"r{hh}"].values, e[f"ex{hh}"].values)
            lines.append(f"| {pn} | {hh} | {s['n']} | {fmt(s['mean'])} | {fmt(s['median'])} | {fmt(s['p10'])} | {fmt(s['p90'])} | {fmt(s['win'],1)} | {fmt(s['ex_median'])} |")
    lines.append("")
    summary = []
    # 每个信号
    for sig, cn in SIG_CN.items():
        lines.append(f"## {cn}  (`{sig}`)\n")
        ctrl = CONTROLS[sig]
        lines.append(f"条件基准: {CTRL_CN[ctrl]}(`{ctrl}`)\n")
        lines.append("| 期间 | h | n | 日期数 | 均值% | 中位% | P10% | P90% | 胜率% | 超额均值% | 按日超额% | t | 条件基准超额% | 收盘入场超额% |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for pn, e in periods.items():
            es = e[e[sig]]
            ec = e[e[ctrl]]
            for hh in H:
                s = stats(es[f"r{hh}"].values, es[f"ex{hh}"].values)
                sc = stats(ec[f"r{hh}"].values, ec[f"ex{hh}"].values)
                if s["n"] == 0:
                    lines.append(f"| {pn} | {hh} | 0 |")
                    continue
                nd = es.loc[es[f"r{hh}"].notna(), "trade_date"].nunique()
                dm, dt = date_cluster(es, f"ex{hh}")
                cm = es[f"exc{hh}"].mean() * 100
                lines.append(f"| {pn} | {hh} | {s['n']} | {nd} | {fmt(s['mean'])} | {fmt(s['median'])} | {fmt(s['p10'])} | {fmt(s['p90'])} | "
                             f"{fmt(s['win'],1)} | {fmt(s['ex_mean'])} | {fmt(dm)} | {fmt(dt,1)} | {fmt(sc.get('ex_mean'))} | {fmt(cm)} |")
                summary.append(dict(sig=sig, cn=cn, period=pn, h=hh, n=s["n"], nd=nd, mean=s["mean"], median=s["median"],
                                    p10=s["p10"], p90=s["p90"], win=s["win"], ex=s["ex_mean"], dex=dm, t=dt,
                                    ctrl_ex=sc.get("ex_mean"), close_ex=cm))
        es = ev[ev[sig] & ev["r5"].notna()]
        if len(es):
            b = es.nlargest(3, "r5")
            w = es.nsmallest(3, "r5")
            fmtc = lambda x: "；".join(f"{r.name_}({r.symbol}) {r.trade_date:%Y-%m-%d} {r.r5*100:+.1f}%" for r in x.assign(name_=x["name"]).itertuples())
            lines.append(f"\n- 最好(h=5): {fmtc(b)}")
            lines.append(f"- 最差(h=5): {fmtc(w)}\n")
    out = DOCS / ("backtest_tables_sample.md" if limit else "backtest_tables.md")
    out.write_text("\n".join(lines), encoding="utf-8")
    pd.DataFrame(summary).to_csv(CACHE / "summary.csv", index=False, encoding="utf-8-sig")
    print("written", out)


if __name__ == "__main__":
    main(*sys.argv[1:])
