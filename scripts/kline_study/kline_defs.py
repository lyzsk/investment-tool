"""K 线 / 威科夫 / 箱体 机械定义(草案实现, 与 skills/market-skill/references/kline_study/definitions.md 一一对应).

约定:
- 输入: 单只股票按日期升序的 DataFrame, 列 open/high/low/close/pre_close/volume/board_type/is_st/limit_up/limit_down.
- 所有"阈值"都相对个股自身: ATR、近 N 日均量/分位、近 N 日平均实体; 只在无法相对化处用常数, 常数集中在 P 里.
- 事件在 t 日收盘后才可知; 所有窗口统计一律 shift(1)(只用 t-1 及以前), 箱体只用 t-1 以前已确认的摆动点.
- 一字板(最高=最低)当天不产生任何形态信号; 涨跌停收盘的 K 线单独标记.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numba import njit

# ---------------- 参数(唯一出处; definitions.md 同步) ----------------
P = dict(
    atr_n=20,             # ATR 窗口
    vol_n=20,             # 均量窗口
    q_n=120,              # 个股自身分位数窗口
    body_n=10,            # 平均实体窗口(Morris: 5~10)
    trend_n=10,           # 前置趋势窗口
    trend_z=1.0,          # 前置趋势强度: 10 日涨跌 / (ATR% * sqrt(10)) 的阈值
    long_body_mult=1.3,   # 长实体: 实体 >= 1.3 * 近 10 日平均实体 且 实体/振幅 >= 0.5 (Morris 方法 2+3)
    small_body_mult=0.5,  # 小实体: 实体 <= 0.5 * 近 10 日平均实体
    doji_body_rng=0.1,    # 十字: 实体 <= 10% 振幅 (Morris 1~3% 对 A 股 0.01 元最小变动太严, 放宽)
    doji_body_avg=0.25,   # 且 实体 <= 0.25 * 近 10 日平均实体 (十字稀缺才有意义)
    hammer_shadow=2.0,    # 锤子: 下影 >= 2 * 实体 (Morris)
    hammer_upper=0.1,     # 上影 <= 10% 振幅 (Morris 5~10%)
    min_rng_atr=0.8,      # 形态 K 线振幅至少 0.8 ATR(过滤无波动的小 K)
    engulf_ratio=0.7,     # 吞没: 前一根实体 <= 0.7 * 后一根实体 (Morris)
    pivot_k=3,            # 摆动点: 左右各 3 根 (WyckoffAgent swing_window=3)
    box_lookback=60,      # 箱体回看
    box_min_width_atr=2.5,
    box_max_width_atr=12.0,
    box_contain=0.8,      # 箱体期间收盘落在 [S-0.5ATR, R+0.5ATR] 的比例
    spring_min_pen_atr=0.1,
    spring_max_pen_atr=1.5,  # WyckoffPro
    sc_ret_z=-1.0,        # SC 前置跌势: 20 日跌幅 / (ATR% * sqrt(20)) <= -1.0 (约跌 4.5 个 ATR)
    st_win=(5, 40),       # SC 后第 5~40 根内找 ST
    st_vol_ratio=0.6,     # ST 量 <= 0.6 * SC 量 (孟洪涛"明显缩小", WyckoffPro 0.6)
    joc_pen_atr=0.3,      # JOC 收盘越过箱顶 0.3 ATR ("清晰水流")
    lps_win=10,           # JOC 后 10 根内找 LPS
    gap_min_atr=0.3,      # 窗口最小 0.3 ATR
    newhigh_count=8,      # 迭创新高 8 根 (尼森 8~10)
)


def limit_pct(board: str, is_st: int) -> float:
    if board in ("GEM", "STAR"):
        return 0.20
    if board == "BSE":
        return 0.30
    return 0.05 if is_st else 0.10


# ---------------- 基础特征 ----------------
def base_features(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("trade_date").reset_index(drop=True).copy()
    pc_raw = g["pre_close"].fillna(g["close"].shift(1))
    # 后复权到最后一天口径: 除权因子 = 今日昨收 / 昨日收盘
    f = (pc_raw / g["close"].shift(1)).fillna(1.0).clip(0.05, 20)
    mult = f[::-1].cumprod()[::-1].shift(-1).fillna(1.0)
    for c in ["open", "high", "low", "close"]:
        g["a" + c] = g[c] * mult
    g["apc"] = g["aclose"].shift(1)
    g["avol"] = g["volume"] / mult
    g["ret"] = g["close"] / pc_raw - 1

    o, h, l, c, pc = g["aopen"], g["ahigh"], g["alow"], g["aclose"], g["apc"]
    g["rng"] = h - l
    g["body"] = (c - o).abs()
    g["upper"] = h - np.maximum(o, c)
    g["lower"] = np.minimum(o, c) - l
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    g["atr"] = tr.rolling(P["atr_n"], min_periods=P["atr_n"]).mean().shift(1)   # 昨日为止的 ATR
    g["atr_pct"] = g["atr"] / pc
    g["vol20"] = g["avol"].rolling(P["vol_n"], min_periods=P["vol_n"]).mean().shift(1)
    g["vr"] = g["avol"] / g["vol20"]
    g["vq80"] = g["avol"].rolling(P["q_n"], min_periods=60).quantile(0.80).shift(1)
    g["vq85"] = g["avol"].rolling(P["q_n"], min_periods=60).quantile(0.85).shift(1)
    g["vq95"] = g["avol"].rolling(P["q_n"], min_periods=60).quantile(0.95).shift(1)
    g["rng_atr"] = g["rng"] / g["atr"]
    g["rq80"] = g["rng_atr"].rolling(P["q_n"], min_periods=60).quantile(0.80).shift(1)
    g["avg_body"] = g["body"].rolling(P["body_n"], min_periods=P["body_n"]).mean().shift(1)
    g["clpos"] = ((c - l) / g["rng"]).where(g["rng"] > 0, 0.5)    # 收盘在当日区间位置 0~1
    g["amt20"] = (g["volume"] * g["close"]).rolling(20, min_periods=20).mean().shift(1)
    g["ema10"] = c.ewm(span=10, adjust=False).mean()
    g["ma20"] = c.rolling(20, min_periods=20).mean()
    g["bias20"] = c / g["ma20"] - 1
    g["bias_q10"] = g["bias20"].rolling(250, min_periods=120).quantile(0.10).shift(1)
    # 前置趋势(到昨日): 10 日涨跌按自身波动标准化
    r10 = c.shift(1) / c.shift(1 + P["trend_n"]) - 1
    g["z10"] = r10 / (g["atr_pct"] * np.sqrt(P["trend_n"]))
    r20 = c.shift(1) / c.shift(21) - 1
    g["z20"] = r20 / (g["atr_pct"] * np.sqrt(20))
    g["down_ctx"] = (g["z10"] <= -P["trend_z"]) & (c.shift(1) < g["ema10"].shift(1))
    g["up_ctx"] = (g["z10"] >= P["trend_z"]) & (c.shift(1) > g["ema10"].shift(1))
    g["low20"] = l.rolling(20, min_periods=20).min().shift(1)
    g["low60"] = l.rolling(60, min_periods=60).min().shift(1)
    g["high20"] = h.rolling(20, min_periods=20).max().shift(1)
    g["high60"] = h.rolling(60, min_periods=60).max().shift(1)

    # 涨跌停
    lp = np.array([limit_pct(b, s) for b, s in zip(g["board_type"], g["is_st"])])
    lu = np.where(g["limit_up"].notna(), g["limit_up"], np.round(pc_raw * (1 + lp), 2))
    ld = np.where(g["limit_down"].notna(), g["limit_down"], np.round(pc_raw * (1 - lp), 2))
    g["lu"], g["ld"] = lu, ld
    g["close_lu"] = g["close"] >= lu - 0.005
    g["close_ld"] = g["close"] <= ld + 0.005
    g["one_word"] = (g["high"] - g["low"]).abs() < 1e-9
    g["bad"] = g["ret"].abs() > lp + 0.015            # 超出涨跌幅 = 数据异常/未除权
    g["idx"] = np.arange(len(g))
    return g


# ---------------- 摆动点与箱体 ----------------
@njit(cache=True)
def _box_numba(high, low, close, atr, k, lookback, minw, maxw, contain):
    n = len(high)
    R = np.full(n, np.nan)
    S = np.full(n, np.nan)
    ph = np.zeros(n, np.bool_)
    pl = np.zeros(n, np.bool_)
    for i in range(k, n - k):
        hh = high[i]
        ll = low[i]
        okh = True
        okl = True
        for j in range(i - k, i + k + 1):
            if j == i:
                continue
            if high[j] > hh or (high[j] == hh and j < i):
                okh = False
            if low[j] < ll or (low[j] == ll and j < i):
                okl = False
        ph[i] = okh
        pl[i] = okl
    for t in range(lookback + k + 1, n):
        a = atr[t]
        if not (a > 0):
            continue
        # 只用 t-1 已确认的摆动点: 摆动点 i 在 i+k 确认, 需 i+k <= t-1
        hv = np.empty(8)
        lv = np.empty(8)
        nh = 0
        nl = 0
        first = t - 1 - k
        i = first
        while i >= t - lookback and (nh < 3 or nl < 3):
            if ph[i] and nh < 3:
                hv[nh] = high[i]
                nh += 1
            if pl[i] and nl < 3:
                lv[nl] = low[i]
                nl += 1
            i -= 1
        if nh < 2 or nl < 2:
            continue
        r = np.median(hv[:nh])
        s = np.median(lv[:nl])
        w = (r - s) / a
        if w < minw or w > maxw:
            continue
        cnt = 0
        tot = 0
        for j in range(t - lookback, t):
            tot += 1
            if close[j] >= s - 0.5 * a and close[j] <= r + 0.5 * a:
                cnt += 1
        if cnt < contain * tot:
            continue
        R[t] = r
        S[t] = s
    return R, S, ph, pl


def add_box(g: pd.DataFrame, lookback=None) -> pd.DataFrame:
    lb = lookback or P["box_lookback"]
    R, S, ph, pl = _box_numba(g["ahigh"].values.astype(np.float64), g["alow"].values.astype(np.float64),
                              g["aclose"].values.astype(np.float64), g["atr"].fillna(0).values.astype(np.float64),
                              P["pivot_k"], lb, P["box_min_width_atr"], P["box_max_width_atr"], P["box_contain"])
    g["boxR"], g["boxS"] = R, S
    g["pivot_h"], g["pivot_l"] = ph, pl
    return g


# ---------------- 迭创新高计数(尼森) ----------------
@njit(cache=True)
def _newhigh_count(high, low, atr, max_gap, reset_atr):
    n = len(high)
    cnt = np.zeros(n, np.int64)
    c = 0
    runmax = high[0]
    last_new = 0
    for t in range(1, n):
        if high[t] > runmax:
            c += 1
            runmax = high[t]
            last_new = t
        else:
            # 期间大幅回撤(> reset_atr 个 ATR)或超过 max_gap 根无新高 => 以当前为新起点重新计数
            if (atr[t] > 0 and runmax - low[t] > reset_atr * atr[t]) or (t - last_new > max_gap):
                c = 0
                runmax = high[t]
                last_new = t
        cnt[t] = c
    return cnt


# ---------------- 信号 ----------------
def signals(g: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = g["aopen"], g["ahigh"], g["alow"], g["aclose"]
    body, rng, up, lo = g["body"], g["rng"], g["upper"], g["lower"]
    ab, atr = g["avg_body"], g["atr"]
    ok0 = (~g["one_word"]) & atr.notna()                       # 测试类事件(ST/Spring/LPS)只排除一字板
    ok = ok0 & (rng >= P["min_rng_atr"] * atr)                    # 形态类事件要求振幅 >= 0.8 ATR
    bull, bear = c > o, c < o
    long_body = (body >= P["long_body_mult"] * ab) & (body >= 0.5 * rng)
    small_body = body <= P["small_body_mult"] * ab
    doji = (body <= P["doji_body_rng"] * rng) & (body <= P["doji_body_avg"] * ab)
    sh = lambda s, k=1: s.shift(k, fill_value=False) if s.dtype == bool else s.shift(k)
    S = pd.DataFrame(index=g.index)

    # K1 锤子线: 下跌背景 + 20 日新低 + 下影>=2实体 + 上影<=10%振幅
    S["K1_hammer"] = ok & g["down_ctx"] & (l <= g["low20"]) & (lo >= P["hammer_shadow"] * np.maximum(body, 0.05 * rng)) \
        & (up <= P["hammer_upper"] * rng)
    # K2 看涨吞没: 下跌背景, 前阴后阳, 后实体包前实体, 前实体<=0.7后实体
    S["K2_bull_engulf"] = ok & g["down_ctx"] & sh(bear) & bull & (o <= sh(c)) & (c >= sh(o)) & \
        ~((o == sh(c)) & (c == sh(o))) & (sh(body) <= P["engulf_ratio"] * body)
    # K3 启明星: t-2 下跌背景长阴, t-1 小实体且实体低于 t-2 收盘, t 阳线收在 t-2 实体中点以上
    b2 = sh(body, 2)
    S["K3_morning_star"] = ok & sh(g["down_ctx"], 2) & sh(bear, 2) & sh(long_body, 2) & \
        (sh(body) <= 0.3 * b2) & (np.maximum(sh(o), sh(c)) <= sh(c, 2) + 0.1 * b2) & bull & \
        (c >= (sh(o, 2) + sh(c, 2)) / 2) & ~sh(g["one_word"])
    # K4 超卖十字: 十字星 + 20 日乖离 <= 个股自身近 250 日 10 分位
    S["K4_doji_oversold"] = ok & doji & (g["bias20"] <= g["bias_q10"])
    # K5 看跌吞没(上涨背景) —— 风险信号, 期望为负
    S["K5_bear_engulf"] = ok & g["up_ctx"] & sh(bull) & bear & (o >= sh(c)) & (c <= sh(o)) & \
        ~((o == sh(c)) & (c == sh(o))) & (sh(body) <= P["engulf_ratio"] * body)
    # K6 乌云盖顶(上涨背景): 前长阳, 今开 > 前收, 收 < 前实体中点但 > 前开
    S["K6_dark_cloud"] = ok & g["up_ctx"] & sh(bull) & sh(long_body) & bear & (o > sh(c)) & \
        (c < (sh(o) + sh(c)) / 2) & (c > sh(o))

    # W1 SC 恐慌抛售: 20 日跌势 z<=-1.0, 创 60 日新低, 量>=自身 120 日 95 分位, 振幅/ATR>=自身 80 分位
    sc = ok & (g["z20"] <= P["sc_ret_z"]) & (l <= g["low60"]) & (g["avol"] >= g["vq95"]) & (g["rng_atr"] >= g["rq80"])
    S["W1_SC"] = sc
    # W2 停止行为②(放量不跌): 下跌背景、接近 20 日低点, 量>=1.2 倍昨量且>=20 日均量, 振幅<=0.7 倍昨振幅, 收在上半区
    S["W2_stop_vol"] = ok0 & g["down_ctx"] & (l <= g["low20"] + 0.5 * atr) & (g["avol"] >= 1.2 * sh(g["avol"])) & \
        (g["avol"] >= g["vol20"]) & (rng <= 0.7 * sh(rng)) & (g["clpos"] >= 0.5)
    # W3 ST 二次测试(SC 确认): SC 后 5~40 根, 低点在 [SC低-0.5ATR, SC低+1ATR], 量<=0.6*SC量 且 <=均量, 收>=SC低,
    #     且 SC 与本日之间出现过 AR(最高价 >= SC收盘 + 2ATR). 每个 SC 只取第一个 ST.
    st = np.zeros(len(g), bool)
    sc_idx = np.where(sc.values)[0]
    lo_a, hi_a, av, v20, cl, at = l.values, h.values, g["avol"].values, g["vol20"].values, c.values, atr.values
    okv = ok0.values
    for i in sc_idx:
        a0 = at[i]
        for t in range(i + P["st_win"][0], min(i + P["st_win"][1] + 1, len(g))):
            if not okv[t]:
                continue
            if hi_a[i + 1:t].max() < cl[i] + 2 * a0 if t > i + 1 else True:
                continue
            if lo_a[t] >= lo_a[i] - 0.5 * a0 and lo_a[t] <= lo_a[i] + 1.0 * a0 and av[t] <= P["st_vol_ratio"] * av[i] \
                    and av[t] <= v20[t] and cl[t] >= lo_a[i]:
                st[t] = True
                break
    S["W3_SC_ST"] = st
    # W4/W5 Spring(箱体): 低点刺破箱底 0.1~1.5 ATR, 收盘收回箱底上方; 按量分 缩量(<=均量) / 放量(>=1.5 均量)
    R, Sb = g["boxR"], g["boxS"]
    spring = ok0 & R.notna() & (l <= Sb - P["spring_min_pen_atr"] * atr) & (l >= Sb - P["spring_max_pen_atr"] * atr) & (c > Sb)
    S["W4_spring_lowvol"] = spring & (g["vr"] <= 1.0)
    S["W5_spring_hivol"] = spring & (g["vr"] >= 1.5)
    # W6 JOC: 收盘越过箱顶 0.3 ATR, 量>=自身 85 分位, 阳线收在上 1/4, 前 10 日无收盘在箱顶上方
    above_prev = (c > R).astype(float).rolling(10, min_periods=1).max().shift(1).fillna(0) > 0
    joc = ok & R.notna() & (c >= R + P["joc_pen_atr"] * atr) & (g["avol"] >= g["vq85"]) & bull & (g["clpos"] >= 0.75) & ~above_prev
    S["W6_JOC"] = joc
    # W7 LPS: JOC 后 10 根内第一次回踩: 低点 <= 箱顶+0.5ATR, 收盘 >= 箱顶-0.25ATR, 量<=0.7*JOC量 且 <=均量
    lps = np.zeros(len(g), bool)
    for i in np.where(joc.values)[0]:
        r0 = R.values[i]
        for t in range(i + 1, min(i + P["lps_win"] + 1, len(g))):
            if not okv[t]:
                continue
            if lo_a[t] <= r0 + 0.5 * at[i] and cl[t] >= r0 - 0.25 * at[i] and av[t] <= 0.7 * av[i] and av[t] <= v20[t]:
                lps[t] = True
                break
            if cl[t] < r0 - 0.25 * at[i]:
                break   # 跌回箱内 = JOC 失败, 不再找 LPS
    S["W7_LPS"] = lps
    # W8 UT 上冲回落(风险): 高点越过箱顶 0.2ATR 后收回箱顶下, 量>=1.3 均量, 上影>=40% 振幅
    S["W8_UT"] = ok & R.notna() & (h >= R + 0.2 * atr) & (c < R) & (g["vr"] >= 1.3) & (up >= 0.4 * rng)
    # W9 SOW 破冰(风险): 收盘跌破箱底 0.3 ATR, 量>=自身 85 分位, 长阴
    S["W9_SOW"] = ok & Sb.notna() & (c <= Sb - 0.3 * atr) & (g["avol"] >= g["vq85"]) & bear & long_body

    # N1 上升窗口 3 日不补(尼森): t-3 跳空(低>前高, 缺口>=0.3ATR, 非一字), t-2..t 收盘都不低于缺口下沿
    gap_dn = sh(h, 4)   # 缺口下沿 = 跳空前一日最高
    gap_day = (sh(l, 3) > gap_dn) & ((sh(l, 3) - gap_dn) >= P["gap_min_atr"] * sh(atr, 3)) & ~sh(g["one_word"], 3)
    hold = (sh(c, 2) >= gap_dn) & (sh(c, 1) >= gap_dn) & (c >= gap_dn)
    S["N1_gap_hold3"] = gap_day & hold & ~g["one_word"]
    # N2 迭创新高 8 根(风险): 尼森计数, 中间无新高 <=3 根, 回撤 >2ATR 重置
    cnt = _newhigh_count(h.values.astype(np.float64), l.values.astype(np.float64), atr.fillna(0).values.astype(np.float64), 3, 2.0)
    S["N2_newhigh8"] = ok & (cnt == P["newhigh_count"])
    return S.fillna(False).astype(bool)
