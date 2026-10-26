# -*- coding: utf-8 -*-
"""scen_v2_feat.py — 情景 v2 的全市场特征表(10/26 用户令: 多因子 + 极端情景; 零 token, 业务库只读)

一行 = (票, 交易日 T); 特征只用 T 收盘(含 T 晚上公布的龙虎榜)前已知的信息; 标签 = T+1 / T+2 走法 + 开高低收路径
范围: 主板 60 / 00 + 创业板 30(科创 68 / 北交没做); T 从 2024-01 起(日线从 2023-06 起拉, 留 120 天预热)
因子组(GROUPS, 解释 / 消融按组):
  票型   10 类票型 + 连板高度 + 近 5/10/20 日涨停次数 + 距上次涨停天数 + 20cm
  K形    当天涨跌 / 开盘缺口 / 最高最低 / 收在当天位置 / 上下影线 / 振幅(20cm 票除以 2 归一)
  走势   3/5/10/20 日涨幅、距 20 / 60 日高低点、5/10/20 日均线偏离、连阳天数、ATR%
  量能   量比(÷前 5 日均量)、成交额 / 20 日均额、换手率、换手 / 20 日均换手、成交额对数
  箱体   段式箱体(draw_box.seg_boxes 同口径, 改成逐日因果版: 每天只用到当天为止的数据) 在箱 / 箱内位置 / 箱宽 ATR / 箱龄 / 越界天数 / 最近离箱方向 + 天数;
         另给 60 日收盘分位(近似口径)
  情绪   全市场涨停 / 跌停 / 炸板 / 炸板率 / 最高连板 / 晋级率 / 昨日涨停今日均涨 / 上涨家数占比 / 中位涨幅 + 涨停家数较昨日变化
  指数   上证 / 国证2000 / 创业板指 当日涨跌 + 5 日涨跌 + 20 日区间位置
  龙虎榜 (2025-01-07 起) 上榜 / 净买占成交额 / 机构净买 / 游资(有别名)净买 / 一日游 / 打板型 / 低吸型 席位净买(风格 = 席位 T 之前的历史, peers.seat_style 口径) /
         今天净买席位的历史次日收盘均值(席位质量)
  导师   (tzzb bs_leg, 2025-09 起) 当天 / 近 5 日 买入 / 卖出的账本数(正样本 / 负样本账本分开)、按逐笔腿累计的持有账本数、距最近一次导师卖出天数
  分时   (minute_path 100 天, 2026-05-28 起; 其余日子缺失) 最高 / 最低出现时刻、尾盘拉升、早盘 30 分钟冲高、收盘距日内高点、封板分钟数、开板次数、首封时刻、形态
  题材   (md 涨停分析, 2026-01 起) 本票近 20 日所挂题材当天涨停家数 / 较昨日变化 / 本波第几天、本票当天是否在涨停分析表里
  电报   (cls_telegraph, 2026-03 起) 当天被电报点名次数(按股票简称匹配)
用法: python scen_v2_feat.py [--since 2023-06-01]   → results/kline/_scen_v2/feat.parquet(约 6~10 分钟, 24 核)
"""
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]
OUT = ROOT / "results" / "kline" / "_scen_v2"
MP_DIR = ROOT / "downloads" / "quotes" / "stock" / "minute_path"
WAYS = ["涨停", "冲高A杀", "高开低走", "单边上涨", "震荡", "深V", "单边下跌", "跌停"]
TYPES = ["连板中", "首板", "炸板", "断板", "跌停", "跌停失败", "大涨", "大跌", "箱体震荡", "趋势"]
IDX = {"sh000001": "上证", "sz399303": "国证2000", "sz399006": "创业板指"}
SHAPES = ["窄幅震荡", "单边上涨", "单边下跌", "冲高回落", "探底回升", "宽幅震荡", "尾盘拉升", "一路走低"]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def conn(db="investment_market"):
    import db_ro
    return db_ro.connect(db)


def sql_df(sql, args=None, db="investment_market"):
    c = conn(db)
    try:
        with c.cursor() as cur:
            cur.execute(sql, args)
            cols = [d[0] for d in cur.description]
            return pd.DataFrame(list(cur.fetchall()), columns=cols)
    finally:
        c.close()


# ---------------------------------------------------------------- 日线
def _load_month(a):
    d0, d1 = a
    return sql_df("select symbol, trade_date, open, high, low, close, pre_close, volume, amount, turnover_rate, limit_up, limit_down from kline_day "
                  "where is_deleted=0 and trade_date >= %s and trade_date < %s and open > 0 and pre_close > 0 "
                  "and (symbol like 'sh60%%' or symbol like 'sz00%%' or symbol like 'sz30%%' or symbol in ('sh000001','sz399303','sz399006'))", (d0, d1))


def load_daily(since="2023-06-01", until=None):
    ms = pd.date_range(since, until or pd.Timestamp.today() + pd.Timedelta(days=31), freq="MS")
    ranges = [(str(a.date()), str(b.date())) for a, b in zip(ms[:-1], ms[1:])]
    with Pool(8) as p:
        parts = p.map(_load_month, ranges)
    df = pd.concat(parts, ignore_index=True)
    df["trade_date"] = df["trade_date"].astype(str)
    for c in ["open", "high", "low", "close", "pre_close", "amount", "turnover_rate", "limit_up", "limit_down"]:
        df[c] = df[c].astype(float)
    df["volume"] = df["volume"].astype(float)
    # 10/26 实测: kline_day 的 amount / turnover_rate 只有 2026-10 才有 → 成交额用 量 × (开高低收均价) 估; 换手率没有流通股本, 不用
    est = df["volume"] * (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    df["amount"] = df["amount"].where(df["amount"] > 0, est)
    return df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def st_set():
    s = sql_df("select symbol from security_master where sec_type='STOCK' and upper(name) like '%%ST%%'")
    return set(s.symbol)


def way_vec(o, h, l_, c, base, up, dn, m):
    """T+1 走法(相对 base = 前一日收盘 %); 定义同 scen_v2 初版; m = 1(10cm) / 2(20cm)"""
    o, h, l_, c = [(x / base - 1) * 100 for x in (o, h, l_, c)]
    rng = np.maximum(h - l_, 1e-9)
    w = np.full(len(o), "震荡", dtype=object)
    cond = [
        ("单边下跌", (c <= -3 * m) & ((h - c) / rng >= 0.75)),
        ("单边上涨", (c >= 3 * m) & ((c - l_) / rng >= 0.75)),
        ("高开低走", (o >= 2 * m) & (c < o - 3 * m)),
        ("深V", (l_ <= -5 * m) & (c >= l_ + 5 * m)),
        ("冲高A杀", (h >= 5 * m) & (c <= h - 6 * m)),
        ("跌停", dn),
        ("涨停", up),
    ]   # 倒序赋值 = 越往下优先级越高(和 scen_v2 初版 if 链顺序一致)
    for nm, cd in cond:
        w[np.asarray(cd, bool)] = nm
    return w


# ---------------------------------------------------------------- 段式箱体(因果版)
def seg_state(o, h, l_, cl, atr, minb=8, minw=1.5, maxw=8.0, tol=0.5, fake=2):
    """draw_box.seg_boxes 同参数, 但逐日记录"当天收盘时看到的箱体状态"(第一次写入的为准 = 不偷看):
    返回 inbox(1 在箱 / 0.5 越界未满 fake 天 / 0 无箱), pos(收盘在箱内位置 0~1, 越界可 <0 或 >1), width(ATR), age(天), outn(越界天数, 带方向), exitdir(离箱当天 ±1)"""
    n = len(cl)
    inbox = np.zeros(n)
    pos, width, age, outn, exitdir = (np.full(n, np.nan) for _ in range(5))
    done = np.zeros(n, bool)
    top, bot = np.maximum(o, cl), np.minimum(o, cl)

    def put(t, ib, R, S, a, ag, on):
        if t < n and not done[t]:
            done[t] = True
            inbox[t] = ib
            pos[t] = (cl[t] - S) / (R - S) if R > S else np.nan
            width[t] = (R - S) / a if a > 0 else np.nan
            age[t] = ag
            outn[t] = on
    i = 14
    while i + minb <= n:
        a = atr[i + minb - 1]
        if not (a > 0):
            i += 1
            continue
        R, S = np.quantile(top[i:i + minb], 0.9), np.quantile(bot[i:i + minb], 0.1)
        if not (minw <= (R - S) / a <= maxw):
            i += 1
            continue
        put(i + minb - 1, 1, R, S, a, minb, 0)
        j, out_n, sgn = i + minb, 0, 0
        while j < n:
            if S - tol * a <= cl[j] <= R + tol * a:
                out_n = 0
            else:
                out_n += 1
                sgn = 1 if cl[j] > R else -1
                if out_n > fake:
                    if not done[j]:
                        done[j] = True
                        exitdir[j] = sgn
                    break
            j += 1
            seg = slice(i, j - out_n)
            R, S = np.quantile(top[seg], 0.9), np.quantile(bot[seg], 0.1)
            put(j - 1, 1 if out_n == 0 else 0.5, R, S, a, j - i, out_n * sgn)
        end = j - out_n - 1
        i = end + 1 if end - i + 1 >= minb else i + 1
    return inbox, pos, width, age, outn, exitdir


def _box_one(args):
    idx, o, h, l_, cl, atr = args
    return idx, seg_state(o, h, l_, cl, atr)


# ---------------------------------------------------------------- 主体: 日线派生
def base_features(df, st):
    g = df.groupby("symbol", sort=False)
    sym = df["symbol"].values
    is_idx = df["symbol"].isin(list(IDX)).values
    is20 = df["symbol"].str[2:4].eq("30").values
    is_st = df["symbol"].isin(st).values
    lim = np.where(is20, 0.2, np.where(is_st, 0.05, 0.1))
    pc = df["pre_close"].values
    up_calc = np.floor(pc * (1 + lim) * 100 + 0.5 + 1e-6) / 100
    dn_calc = np.floor(pc * (1 - lim) * 100 + 0.5 + 1e-6) / 100
    up = np.where(df["limit_up"].fillna(0).values > 0, df["limit_up"].fillna(0).values, up_calc)
    dn = np.where(df["limit_down"].fillna(0).values > 0, df["limit_down"].fillna(0).values, dn_calc)
    o, h, l_, c = (df[k].values for k in ("open", "high", "low", "close"))
    df["m"] = np.where(is20, 2.0, 1.0)
    df["is20"] = is20.astype(np.int8)
    df["is_st"] = is_st.astype(np.int8)
    df["zt"] = (c >= up - 0.005).astype(np.int8)
    df["touch"] = (h >= up - 0.005).astype(np.int8)
    df["dt"] = (c <= dn + 0.005).astype(np.int8)
    df["touch_dn"] = (l_ <= dn + 0.005).astype(np.int8)
    df["up_px"], df["dn_px"] = up, dn
    m = df["m"].values
    g = df.groupby("symbol", sort=False)
    df["pct"] = (c / pc - 1) * 100
    df["k_pct"] = df["pct"] / m
    df["k_gap"] = (o / pc - 1) * 100 / m
    df["k_hi"] = (h / pc - 1) * 100 / m
    df["k_lo"] = (l_ / pc - 1) * 100 / m
    rng = np.maximum(h - l_, 1e-9)
    df["k_clv"] = (c - l_) / rng
    df["k_upsh"] = (h - np.maximum(o, c)) / pc * 100 / m
    df["k_dnsh"] = (np.minimum(o, c) - l_) / pc * 100 / m
    df["k_body"] = (c - o) / pc * 100 / m
    df["k_amp"] = (h - l_) / pc * 100 / m
    # 连板高度(含当天): 连续 zt 计数
    z = df["zt"].values.astype(int)
    grp_start = (sym != np.roll(sym, 1))
    run = np.zeros(len(z), int)
    for k in range(len(z)):   # 一遍线性
        run[k] = (0 if grp_start[k] else run[k - 1]) + 1 if z[k] else 0
    df["boards"] = run
    g = df.groupby("symbol", sort=False)
    df["prev_zt"] = g["zt"].shift(1).fillna(0).astype(np.int8)
    df["prev_boards"] = g["boards"].shift(1).fillna(0)
    df["prev_pct_k"] = g["k_pct"].shift(1)
    df["prev_touch"] = g["touch"].shift(1).fillna(0).astype(np.int8)
    for w in (5, 10, 20):
        df[f"zt_n{w}"] = g["zt"].transform(lambda s: s.rolling(w, min_periods=1).sum())
    # 距上次涨停(不含当天)天数
    rowi = g.cumcount().values
    lastzt = pd.Series(np.where(z == 1, rowi, np.nan)).groupby(sym).ffill().values
    prev_last = pd.Series(lastzt).groupby(sym).shift(1).values
    df["days_since_zt"] = np.nan_to_num(np.clip(rowi - prev_last, 0, 120), nan=120)
    df["age"] = rowi
    # 走势
    for w in (3, 5, 10, 20):
        df[f"r{w}"] = (c / g["close"].shift(w).values - 1) * 100 / m
    for w in (20, 60):
        hh = g["high"].transform(lambda s: s.rolling(w, min_periods=5).max()).values
        ll = g["low"].transform(lambda s: s.rolling(w, min_periods=5).min()).values
        df[f"d_hi{w}"] = (c / hh - 1) * 100 / m
        df[f"d_lo{w}"] = (c / ll - 1) * 100 / m
        df[f"pos{w}"] = (c - ll) / np.maximum(hh - ll, 1e-9)
    for w in (5, 10, 20):
        ma = g["close"].transform(lambda s: s.rolling(w, min_periods=w).mean()).values
        df[f"ma{w}"] = (c / ma - 1) * 100 / m
    upd = (c > pc).astype(int)
    run = np.zeros(len(upd), int)
    for k in range(len(upd)):
        run[k] = (0 if grp_start[k] else run[k - 1]) + 1 if upd[k] else 0
    df["up_run"] = run
    tr = np.maximum(h - l_, np.maximum(np.abs(h - pc), np.abs(l_ - pc)))
    df["_tr"] = tr
    df["atr14"] = df.groupby("symbol", sort=False)["_tr"].transform(lambda s: s.rolling(14, min_periods=1).mean()).values
    df["atr_pct"] = df["atr14"] / c * 100 / m
    # 60 日收盘分位(近似箱体口径)
    df["cl_q60"] = g["close"].transform(lambda s: s.rolling(60, min_periods=30).rank(pct=True)).values
    # 量能
    v = df["volume"].values
    vm5 = g["volume"].transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean()).values
    df["vr5"] = v / np.maximum(vm5, 1)
    am20 = g["amount"].transform(lambda s: s.shift(1).rolling(20, min_periods=5).mean()).values
    df["ar20"] = df["amount"].values / np.maximum(am20, 1)
    vm20 = g["volume"].transform(lambda s: s.shift(1).rolling(20, min_periods=5).mean()).values
    df["vr20"] = v / np.maximum(vm20, 1)
    df["lamt"] = np.log10(np.maximum(df["amount"].values, 1))
    df.drop(columns=["_tr"], inplace=True)
    df["is_idx"] = is_idx
    return df


def add_box(df):
    stock = df[~df["is_idx"]]
    tasks = []
    for s, ix in stock.groupby("symbol", sort=False).indices.items():
        ii = stock.index.values[ix]
        tasks.append((ii, df["open"].values[ii], df["high"].values[ii], df["low"].values[ii], df["close"].values[ii], df["atr14"].values[ii]))
    cols = ["box_in", "box_pos", "box_w", "box_age", "box_outn", "_exit"]
    arr = {k: np.full(len(df), np.nan) for k in cols}
    with Pool(20) as p:
        for ii, res in p.imap_unordered(_box_one, tasks, chunksize=40):
            for k, v in zip(cols, res):
                arr[k][ii] = v
    for k in cols:
        df[k] = arr[k]
    # 最近一次离箱方向 + 天数
    sym = df["symbol"].values
    rowi = df.groupby("symbol", sort=False).cumcount().values
    ex = pd.Series(np.where(np.isnan(df["_exit"].values), np.nan, rowi))
    last_ex_row = ex.groupby(sym).ffill().values
    last_ex_dir = pd.Series(df["_exit"].values).groupby(sym).ffill().values
    df["box_exit_days"] = np.clip(rowi - last_ex_row, 0, 60)
    df["box_exit_dir"] = np.where(df["box_exit_days"] <= 60, last_ex_dir, 0)
    df.drop(columns=["_exit"], inplace=True)
    return df


def add_type(df):
    """10 类票型(优先级同 scen_v2 初版)"""
    p, m = df["pct"].values, df["m"].values
    near_dn_fail = (df["low"].values <= df["dn_px"].values * 1.02) & (df["close"].values >= df["dn_px"].values * 1.03)
    conds = [
        df["zt"].eq(1) & df["prev_zt"].eq(1),
        df["zt"].eq(1),
        df["touch"].eq(1),
        df["prev_zt"].eq(1),
        df["dt"].eq(1),
        pd.Series(near_dn_fail, index=df.index),
        pd.Series(p >= 7 * m, index=df.index),
        pd.Series(p <= -7 * m, index=df.index),
        df["box_in"].eq(1) & (df["zt_n20"] - df["zt"] == 0),
    ]
    df["typ"] = np.select([c.values for c in conds], list(range(9)), 9)
    return df


def market_features(df):
    s = df[(~df["is_idx"]) & (df["is_st"] == 0)]
    g = s.groupby("trade_date")
    mk = pd.DataFrame({"mk_zt": g["zt"].sum(), "mk_dt": g["dt"].sum(), "mk_touch": g["touch"].sum(),
                       "mk_maxb": g["boards"].max(), "mk_up": g["pct"].apply(lambda x: (x > 0).mean()), "mk_med": g["pct"].median()})
    mk["mk_zab"] = (mk["mk_touch"] - mk["mk_zt"]) / mk["mk_touch"].clip(lower=1)
    pz = s[s["prev_zt"] == 1].groupby("trade_date")
    mk["mk_jin"] = pz["zt"].mean()
    mk["mk_prem"] = pz["pct"].mean()
    mk["mk_zt_chg"] = mk["mk_zt"].diff()
    mk["mk_ge2"] = s[s["boards"] >= 2].groupby("trade_date").size().reindex(mk.index).fillna(0)
    for sym_, nm in IDX.items():
        x = df[df["symbol"] == sym_].set_index("trade_date")
        c = x["close"]
        mk[f"ix_{nm}"] = (c / x["pre_close"] - 1) * 100
        mk[f"ix5_{nm}"] = (c / c.shift(5) - 1) * 100
        hh, ll = c.rolling(20).max(), c.rolling(20).min()
        mk[f"ixp_{nm}"] = (c - ll) / (hh - ll).clip(lower=1e-9)
    return mk


def labels(df, days):
    """T+1 / T+2 走法 + 路径(相对 T 收盘 %); 停牌(下一行不是下一交易日)= 缺"""
    g = df.groupby("symbol", sort=False)
    nxt = {d: days[i + 1] for i, d in enumerate(days[:-1])}
    d = df["trade_date"]
    for k in (1, 2):
        for col in ("trade_date", "open", "high", "low", "close", "zt", "dt"):
            df[f"_{col}{k}"] = g[col].shift(-k)
    ok1 = df["_trade_date1"].values == d.map(nxt).values
    ok2 = ok1 & (df["_trade_date2"].values == df["_trade_date1"].map(nxt).values)
    c0 = df["close"].values
    m = df["m"].values
    w1 = way_vec(df["_open1"].values, df["_high1"].values, df["_low1"].values, df["_close1"].values, c0, df["_zt1"].values == 1, df["_dt1"].values == 1, m)
    w2 = way_vec(df["_open2"].values, df["_high2"].values, df["_low2"].values, df["_close2"].values, df["_close1"].values, df["_zt2"].values == 1, df["_dt2"].values == 1, m)
    wi = {w: i for i, w in enumerate(WAYS)}
    df["y1"] = np.where(ok1, pd.Series(w1).map(wi).values, -1).astype(np.int8)
    df["y2"] = np.where(ok2, pd.Series(w2).map(wi).values, -1).astype(np.int8)
    for k in (1, 2):
        for col, nm in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c")):
            df[f"p{k}{nm}"] = np.where(ok1 if k == 1 else ok2, (df[f"_{col}{k}"].values / c0 - 1) * 100, np.nan).astype(np.float32)
    df["d1"] = np.where(ok1, df["_trade_date1"], None)
    df["d2"] = np.where(ok2, df["_trade_date2"], None)
    df.drop(columns=[c for c in df.columns if c.startswith("_")], inplace=True)
    return df


# ---------------------------------------------------------------- 龙虎榜
def lhb_features(df):
    seat = sql_df("select trade_date, symbol, direction, dept_code, net_amt, buy_amt, sell_amt, is_institution, youzi_alias from lhb_seat where is_deleted=0")
    stk = sql_df("select trade_date, symbol, net_amt, deal_amount, reason from lhb_stock where is_deleted=0")
    for x in (seat, stk):
        x["trade_date"] = x["trade_date"].astype(str)
    for c in ("net_amt", "buy_amt", "sell_amt"):
        seat[c] = seat[c].astype(float)
    stk["net_amt"] = stk["net_amt"].astype(float)
    k = df[["symbol", "trade_date", "zt", "pct", "amount", "p1h", "p1c", "d1"]]
    days = sorted(df["trade_date"].unique())
    nxt = {d: days[i + 1] for i, d in enumerate(days[:-1])}
    # 席位-日 净买事件(同一席位同日同票多行合并; 买卖方向两张表各出现一次的去重: 按 (dept, symbol, date) 取 max 绝对值行)
    sd = seat.groupby(["dept_code", "symbol", "trade_date"], as_index=False).agg(net=("net_amt", "first"), inst=("is_institution", "max"),
                                                                                 yz=("youzi_alias", "first"))
    sells = set(zip(seat.loc[seat.direction == "SELL", "dept_code"], seat.loc[seat.direction == "SELL", "symbol"], seat.loc[seat.direction == "SELL", "trade_date"]))
    listed = set(zip(stk.symbol, stk.trade_date))
    ev = sd.merge(k, on=["symbol", "trade_date"], how="left")
    buy = ev[ev.net > 0].copy()
    buy["nd"] = buy["trade_date"].map(nxt)
    buy["on_next"] = [(s, d) in listed for s, d in zip(buy.symbol, buy.nd)]
    buy["sold_next"] = [(dc, s, d) in sells for dc, s, d in zip(buy.dept_code, buy.symbol, buy.nd)]
    buy["lowbuy"] = buy["pct"] < 5
    # 席位截至 T 之前的累计(按日聚合后 cumsum, 再 shift 一天 = 不含当天)
    agg = buy.groupby(["dept_code", "trade_date"]).agg(n=("net", "size"), lim=("zt", "sum"), low=("lowbuy", "sum"), on=("on_next", "sum"),
                                                       so=("sold_next", "sum"), co=("p1c", "sum"), con=("p1c", "count")).reset_index().sort_values(["dept_code", "trade_date"])
    cg = agg.groupby("dept_code")
    for c in ("n", "lim", "low", "on", "so", "co", "con"):
        agg["c_" + c] = cg[c].cumsum() - agg[c]
    # 次日相关量(on / so / co)在 T 当天还不知道最后一天的 → 再扣掉昨天那一行(保守, 只用 T−1 之前买入的次日结果)
    for c in ("on", "so", "co", "con"):
        agg["c_" + c] = agg["c_" + c] - cg[c].shift(1).fillna(0)
    st_ = agg.set_index(["dept_code", "trade_date"])
    ev = ev.join(st_[["c_n", "c_lim", "c_low", "c_on", "c_so", "c_co", "c_con"]], on=["dept_code", "trade_date"])
    # 当天不是该席位买入日的(净卖), 用它最近一次的累计 → 简化: 只给净买席位打风格(卖出席位风格对次日影响不在这一版)
    nn = ev["c_n"].fillna(0)
    ev["s_board"] = (nn >= 10) & (ev["c_lim"] / nn.clip(lower=1) >= 0.6)
    ev["s_low"] = (nn >= 10) & ~ev["s_board"] & (ev["c_low"] / nn.clip(lower=1) >= 0.5)
    ev["s_oneday"] = (ev["c_on"].fillna(0) >= 5) & (ev["c_so"] / ev["c_on"].clip(lower=1) >= 0.6)
    ev["s_q"] = np.where(ev["c_con"].fillna(0) >= 5, ev["c_co"] / ev["c_con"].clip(lower=1), np.nan)
    amt = ev["amount"].clip(lower=1)
    ev["r_net"] = (ev["net"] / amt * 100).clip(-100, 100)   # 3 日累计上榜的净买会超过当天成交额 → 截断
    out = pd.DataFrame({
        "lhb_inst": ev["r_net"].where(ev.inst == 1, 0),
        "lhb_yz": ev["r_net"].where(ev.yz.notna() & (ev.yz != ""), 0),
        "lhb_oneday": ev["r_net"].where(ev.s_oneday & (ev.net > 0), 0),
        "lhb_board": ev["r_net"].where(ev.s_board & (ev.net > 0), 0),
        "lhb_lowbuy": ev["r_net"].where(ev.s_low & (ev.net > 0), 0),
        "_qw": (ev["s_q"] * ev["net"]).where(ev.net > 0),
        "_w": ev["net"].where((ev.net > 0) & ev["s_q"].notna()),
        "symbol": ev.symbol, "trade_date": ev.trade_date})
    agg2 = out.groupby(["symbol", "trade_date"]).sum(min_count=1)
    agg2["lhb_seatq"] = agg2["_qw"] / agg2["_w"]
    agg2 = agg2.drop(columns=["_qw", "_w"])
    s2 = stk.groupby(["symbol", "trade_date"]).agg(net=("net_amt", "first"), nr=("reason", "nunique"))
    agg2 = agg2.join(s2, how="outer")
    agg2 = agg2.reset_index().merge(k[["symbol", "trade_date", "amount"]], on=["symbol", "trade_date"], how="left")
    agg2["lhb_on"] = 1
    agg2["lhb_net"] = (agg2["net"] / agg2["amount"].clip(lower=1) * 100).clip(-100, 100)
    agg2["lhb_nr"] = agg2["nr"]
    cols = ["lhb_on", "lhb_net", "lhb_nr", "lhb_inst", "lhb_yz", "lhb_oneday", "lhb_board", "lhb_lowbuy", "lhb_seatq"]
    agg2 = agg2[["symbol", "trade_date"] + cols]
    df = df.merge(agg2, on=["symbol", "trade_date"], how="left")
    on = df["trade_date"] >= "2025-01-07"
    for c in cols[:-1]:   # 龙虎榜数据期内没上榜 = 0; 数据期外 = 缺
        df.loc[on, c] = df.loc[on, c].fillna(0)
    return df


# ---------------------------------------------------------------- 导师(tzzb)
def mentor_features(df):
    L = json.loads((ROOT / "scripts" / "tzzb" / "tzzb_ledgers.json").read_text(encoding="utf-8"))
    kind = {x["ledger"]: x.get("kind", "pos") for x in L}
    r = sql_df("select ledger, record_time, stock_code, side, qty from tzzb_record where is_deleted=0 and record_type='bs_leg'", db="investment_tool")
    r = r[r.stock_code.str.match(r"^(60|00|30)\d{4}$")].copy()
    r["symbol"] = np.where(r.stock_code.str.startswith("6"), "sh", "sz") + r.stock_code
    r["trade_date"] = pd.to_datetime(r.record_time).dt.strftime("%Y-%m-%d")
    r["q"] = r["qty"].astype(float) * np.where(r.side.str.contains("买"), 1, -1)
    r["kind"] = r.ledger.map(kind).fillna("pos")
    first = r.groupby("ledger")["trade_date"].min()
    d = r.groupby(["ledger", "symbol", "trade_date"], as_index=False).agg(q=("q", "sum"), b=("q", lambda x: (x > 0).any()), s=("q", lambda x: (x < 0).any()), kind=("kind", "first"))
    d = d.sort_values(["ledger", "symbol", "trade_date"])
    d["posq"] = d.groupby(["ledger", "symbol"])["q"].cumsum().clip(lower=0)   # 账本起点之前的老仓看不到 → 卖出多于买入时截 0
    days = sorted(df["trade_date"].unique())
    di = {x: i for i, x in enumerate(days)}
    d = d[d.trade_date.isin(di)]
    d["di"] = d.trade_date.map(di)
    out = {}
    for c, cond in (("m_buy", d.b), ("m_sell", d.s)):
        for kd in ("pos", "neg"):
            x = d[cond & (d.kind == kd)].groupby(["symbol", "di"]).size()
            out[f"{c}_{kd}"] = x
    # 持有账本数: 每个(账本, 票)从持仓>0 的那天到下一次变化 → 展开到每日(量不大, 直接展开)
    hold_rows = []
    for (lg, s), x in d.groupby(["ledger", "symbol"]):
        di_ = x.di.values
        pq = x.posq.values
        for k in range(len(di_)):
            if pq[k] > 0:
                e = di_[k + 1] if k + 1 < len(di_) else min(len(days), di_[k] + 60)   # 最后一笔之后最多算 60 天(账本没逐日快照)
                hold_rows.append((s, np.arange(di_[k], e)))
    H = pd.Series(0, dtype=float)
    if hold_rows:
        hs = np.concatenate([[s] * len(a) for s, a in hold_rows])
        ha = np.concatenate([a for _, a in hold_rows])
        H = pd.DataFrame({"symbol": hs, "di": ha}).groupby(["symbol", "di"]).size()
    df["_di"] = df["trade_date"].map(di)
    key = pd.MultiIndex.from_arrays([df["symbol"], df["_di"]])
    for nm, ser in out.items():
        df[nm] = ser.reindex(key).fillna(0).values
    df["m_hold"] = H.reindex(key).fillna(0).values if len(H) else 0
    g = df.groupby("symbol", sort=False)
    for nm in list(out):
        df[nm + "5"] = g[nm].transform(lambda s: s.rolling(5, min_periods=1).sum())
    sold = (df["m_sell_pos"] + df["m_sell_neg"]) > 0
    rowi = g.cumcount().values
    last = pd.Series(np.where(sold, rowi, np.nan)).groupby(df["symbol"].values).ffill().values
    df["m_days_since_sell"] = np.clip(rowi - last, 0, 30)
    on = df["trade_date"] >= first.min()
    mcols = list(out) + [n + "5" for n in out] + ["m_hold", "m_days_since_sell"]
    df.loc[~on, mcols] = np.nan
    df.loc[on, "m_days_since_sell"] = df.loc[on, "m_days_since_sell"].fillna(30)
    df.drop(columns=["_di"], inplace=True)
    return df


# ---------------------------------------------------------------- 分时
def _mp_file(f):
    out = []
    for line in open(f, encoding="utf-8"):
        try:
            j = json.loads(line)
        except ValueError:
            continue
        p = np.array(j.get("p") or [], float)
        pc = j.get("prev")
        if len(p) < 200 or not pc or (p <= 0).any():
            continue
        code = j["code"]
        if not code.startswith(("60", "00", "30")):
            continue
        lim = 0.2 if code.startswith("30") else 0.1
        m = 2 if lim == 0.2 else 1
        up = np.floor(pc * (1 + lim) * 100 + 0.5 + 1e-6) / 100
        r = (p / pc - 1) * 100 / m
        o = r[0]
        ih, il = int(np.argmax(r)), int(np.argmin(r))
        at = p >= up - 0.005
        seal = int(at.sum())
        opens = int(((at[:-1]) & (~at[1:])).sum())
        first_seal = int(np.argmax(at)) if at.any() else -1
        tail = r[-1] - r[-30:].min()
        e30 = r[:30].max() - o
        dd = r[-1] - r.max()
        rb = r[-1] - r.min()
        # 10/26 改: 不再以第一分钟收盘当"开盘"(秒板票第一分钟就在涨停价, 会把"秒板后回落"判成探底回升);
        # 看收盘离日内最高的回撤 dd 和离日内最低的反弹 rb 谁大(单位: 相对昨收 %, 20cm ÷2)
        c, o = r[-1], r[0]
        thr = 2.0
        if r.max() - r.min() < thr:
            sh = 0                                   # 窄幅震荡
        elif c - o >= thr and dd >= -thr / 2:
            sh = 1                                   # 单边上涨
        elif o - c >= thr and rb <= thr / 2:
            sh = 7 if il >= 200 else 2               # 一路走低(最低在 14:20 后) / 单边下跌
        elif -dd >= thr and -dd >= rb:
            sh = 3                                   # 冲高回落
        elif rb >= thr:
            sh = 4                                   # 探底回升
        else:
            sh = 5                                   # 宽幅震荡
        if tail >= 2 and il >= 200:
            sh = 6                                   # 尾盘拉升(最低在 14:20 后, 收盘较尾段低点 +2% 以上)
        out.append((("sh" if code.startswith("6") else "sz") + code, j["d"], ih, il, tail, e30, dd, rb, seal, opens, first_seal, sh))
    return out


def minute_features(df):
    fs = sorted(MP_DIR.glob("20*.jsonl"))
    with Pool(12) as p:
        parts = p.map(_mp_file, fs)
    rows = [x for part in parts for x in part]
    m = pd.DataFrame(rows, columns=["symbol", "trade_date", "mi_thi", "mi_tlo", "mi_tail", "mi_e30", "mi_dd", "mi_rb", "mi_seal", "mi_opens", "mi_first", "mi_shape"])
    m = m.drop_duplicates(["symbol", "trade_date"])
    return df.merge(m, on=["symbol", "trade_date"], how="left"), (fs[0].stem if fs else None)


# ---------------------------------------------------------------- 题材(md 涨停分析)
def theme_features(df):
    sys.path.insert(0, str(ROOT / "scripts" / "paper_line" / "tools"))
    import theme_life as TL   # 只读: rows_canon 读 md + catalog/theme_alias.json
    rows = TL.rows_canon()
    R = pd.DataFrame(rows, columns=["trade_date", "theme", "name", "code", "b", "zt", "t", "lg"])
    nm = sql_df("select symbol, code, name from security_master where sec_type='STOCK'")
    n2s = dict(zip(nm.name, nm.symbol))
    c2s = dict(zip(nm.code, nm.symbol))
    R["symbol"] = [c2s.get(c) if c else n2s.get(n) for c, n in zip(R.code, R.name)]
    R = R.dropna(subset=["symbol"])
    days = sorted(df["trade_date"].unique())
    di = {x: i for i, x in enumerate(days)}
    R = R[R.trade_date.isin(di)]
    R["di"] = R.trade_date.map(di).astype(int)
    tz = R[R.zt].groupby(["theme", "di"]).size().rename("n").reset_index()
    T = tz.pivot(index="di", columns="theme", values="n").reindex(range(len(days))).fillna(0)
    # 本波第几天: 断档 ≤2 天算同一波
    on = (T > 0).values
    wave = np.zeros(T.shape)
    gap = np.full(T.shape[1], 99)
    for i in range(len(T)):
        prev = wave[i - 1] if i else np.zeros(T.shape[1])
        wave[i] = np.where(on[i], np.where(gap <= 2, prev + 1, 1), np.where(gap + 1 <= 2, prev, 0))
        gap = np.where(on[i], 0, gap + 1)
    W = pd.DataFrame(wave, index=T.index, columns=T.columns)
    first_d = R.di.min()
    # 本票近 20 日挂过的题材(含当天) → 取当天涨停最多的那个
    st_th = R[["symbol", "theme", "di"]].drop_duplicates()
    recs = []
    for k in range(20):
        x = st_th.copy()
        x["di"] = x["di"] + k
        recs.append(x)
    X = pd.concat(recs).drop_duplicates()
    X = X[X.di < len(days)]
    X["di"] = X["di"].astype(int)
    tv, wv = T.values, W.values
    col = {t: i for i, t in enumerate(T.columns)}
    X = X[X.theme.isin(col)]
    ci = X.theme.map(col).values.astype(int)
    X["th_zt"] = tv[X.di.values, ci]
    X["th_zt_prev"] = np.where(X.di.values > 0, tv[np.maximum(X.di.values - 1, 0), ci], 0)
    X["th_wave"] = wv[X.di.values, ci]
    X["th_zt5"] = [tv[max(0, d - 4):d + 1, c].sum() for d, c in zip(X.di.values, ci)]
    X = X.sort_values("th_zt", ascending=False).drop_duplicates(["symbol", "di"])
    X["th_chg"] = X.th_zt - X.th_zt_prev
    X["th_n"] = 1
    today = R[["symbol", "di"]].drop_duplicates()
    today["th_in_md"] = 1
    df["_di"] = df["trade_date"].map(di)
    df = df.merge(X[["symbol", "di", "th_zt", "th_chg", "th_wave", "th_zt5"]].rename(columns={"di": "_di"}), on=["symbol", "_di"], how="left")
    df = df.merge(today.rename(columns={"di": "_di"}), on=["symbol", "_di"], how="left")
    on_ = df["_di"] >= first_d
    for c in ("th_zt", "th_chg", "th_wave", "th_zt5", "th_in_md"):
        df.loc[on_, c] = df.loc[on_, c].fillna(0)
    df.drop(columns=["_di"], inplace=True)
    return df, days[first_d] if len(R) else None


# ---------------------------------------------------------------- 电报点名
def telegraph_features(df):
    t = sql_df("select date_format(publish_time,'%Y-%m-%d') d, date_format(publish_time,'%H:%i') hm, coalesce(title,'') ti, coalesce(content, brief, '') tx, level "
               "from cls_telegraph where is_deleted=0", db="investment_tool")
    nm = sql_df("select symbol, name from security_master where sec_type='STOCK'")
    nm = nm[nm.symbol.str.match(r"^(sh60|sz00|sz30)") & (nm.name.str.len() >= 3)]
    names = sorted(set(nm.name), key=len, reverse=True)
    n2s = dict(zip(nm.name, nm.symbol))
    days = sorted(df["trade_date"].unique())
    import bisect
    # 归属: 日历日 d 的电报 → 最近一个 ≤ d 的交易日 T(T 晚上 / 周末的消息在预测 T+1 时已知; T 盘前的消息当然也已知)
    t["T"] = [days[bisect.bisect_right(days, d) - 1] if bisect.bisect_right(days, d) else None for d in t["d"]]
    t = t.dropna(subset=["T"])
    t["txt"] = t["ti"] + " " + t["tx"].str[:600]
    rows = []
    for T_, x in t.groupby("T"):
        allt = "|".join(x["txt"])
        red = "|".join(x.loc[x.level.isin(["A", "B"]), "txt"])
        for n in names:
            k = allt.count(n)
            if k:
                rows.append((n2s[n], T_, k, red.count(n)))
    X = pd.DataFrame(rows, columns=["symbol", "trade_date", "tg_n", "tg_red"]).groupby(["symbol", "trade_date"]).sum().reset_index()
    df = df.merge(X, on=["symbol", "trade_date"], how="left")
    first = t["d"].min()
    on = df["trade_date"] >= first
    for c in ("tg_n", "tg_red"):
        df.loc[on, c] = df.loc[on, c].fillna(0)
    return df, first


GROUPS = {
    "票型": ["typ", "boards", "prev_zt", "prev_boards", "prev_touch", "zt_n5", "zt_n10", "zt_n20", "days_since_zt", "is20", "is_st"],
    "K形": ["k_pct", "k_gap", "k_hi", "k_lo", "k_clv", "k_upsh", "k_dnsh", "k_body", "k_amp", "prev_pct_k"],
    "走势": ["r3", "r5", "r10", "r20", "d_hi20", "d_lo20", "pos20", "d_hi60", "d_lo60", "pos60", "ma5", "ma10", "ma20", "up_run", "atr_pct"],
    "量能": ["vr5", "vr20", "ar20", "lamt"],
    "箱体": ["box_in", "box_pos", "box_w", "box_age", "box_outn", "box_exit_days", "box_exit_dir", "cl_q60"],
    "情绪": ["mk_zt", "mk_dt", "mk_touch", "mk_zab", "mk_maxb", "mk_jin", "mk_prem", "mk_up", "mk_med", "mk_zt_chg", "mk_ge2"],
    "指数": [f"{a}_{b}" for b in IDX.values() for a in ("ix", "ix5", "ixp")],
    "龙虎榜": ["lhb_on", "lhb_net", "lhb_nr", "lhb_inst", "lhb_yz", "lhb_oneday", "lhb_board", "lhb_lowbuy", "lhb_seatq"],
    "导师": ["m_buy_pos", "m_buy_neg", "m_sell_pos", "m_sell_neg", "m_buy_pos5", "m_buy_neg5", "m_sell_pos5", "m_sell_neg5", "m_hold", "m_days_since_sell"],
    "分时": ["mi_thi", "mi_tlo", "mi_tail", "mi_e30", "mi_dd", "mi_rb", "mi_seal", "mi_opens", "mi_first", "mi_shape"],
    "题材": ["th_zt", "th_chg", "th_wave", "th_zt5", "th_in_md"],
    "电报": ["tg_n", "tg_red"],
}
FEATS = [c for v in GROUPS.values() for c in v]
CATS = ["typ", "mi_shape"]


def build(since="2023-06-01", t0="2024-01-01"):
    t_all = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    df = load_daily(since)
    log("日线", len(df))
    st = st_set()
    df = base_features(df, st)
    log("基础特征")
    df = add_box(df)
    log("箱体")
    df = add_type(df)
    days = sorted(df.loc[df.symbol == "sh000001", "trade_date"])
    mk = market_features(df)
    df = labels(df, days)
    df = df[~df["is_idx"]].drop(columns=["is_idx"])
    df = df.join(mk, on="trade_date")
    log("情绪 / 指数 / 标签")
    meta = {"since": since, "t0": t0}
    for nm, fn in (("龙虎榜", lhb_features), ("导师", mentor_features)):
        try:
            df = fn(df)
            log(nm)
        except Exception as e:   # noqa: BLE001
            log(nm, "失败", repr(e))
            meta[nm] = repr(e)
    for nm, fn in (("分时", minute_features), ("题材", theme_features), ("电报", telegraph_features)):
        try:
            df, first = fn(df)
            meta[nm + "_起"] = first
            log(nm, first)
        except Exception as e:   # noqa: BLE001
            log(nm, "失败", repr(e))
            meta[nm] = repr(e)
    for c in FEATS:
        if c not in df.columns:
            df[c] = np.nan
    df = df[(df["trade_date"] >= t0) & (df["age"] >= 20)].reset_index(drop=True)
    for c in FEATS:
        if df[c].dtype == bool:
            df[c] = df[c].astype(np.int8)
        if df[c].dtype.kind == "f":
            df[c] = df[c].astype(np.float32)
    df.to_parquet(OUT / "feat.parquet", index=False)
    meta.update({"rows": len(df), "max_date": df["trade_date"].max(), "built": time.strftime("%Y-%m-%d %H:%M"), "secs": round(time.time() - t_all)})
    (OUT / "feat_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log("写出", OUT / "feat.parquet", meta)
    return df


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = sys.argv[1:]
    build(*(a[a.index("--since") + 1:a.index("--since") + 2] if "--since" in a else []))
