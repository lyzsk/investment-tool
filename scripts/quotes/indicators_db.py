# -*- coding: utf-8 -*-
"""indicators_db.py — 均线 / 三态(趋势·区间·无规则)/ 风险仓位 机械层(零 token; 10/18 晚用户定 A + C)

为什么: 右侧交易的核心 = 胜率 × 盈亏比 × 仓位; 先要知道每只票每天处在什么状态(上涨趋势 / 下跌趋势 / 交易区间 / 无规则),
        再看各导师在每种状态下赚不赚钱(B: regime_trades.py), 仓位按风险倒推(C: sizing)。原 indicators.mjs 只有 MA5~60 且没有任何流程调用。
数据: 行情库 kline_day(2018-07 起), 前复权 = 用 close/pre_close 链乘(交易所的昨收已按除权调整, 等价前复权, 不依赖复权因子表)
算什么(都只用 ≤ 当日收盘的数据):
  EMA 5/10/20/30/60/120/144/169/388 · MA 5/10/20/60/120/144/250 · ATR14 · ER20(效率比 = 20 日净位移 / 20 日逐日位移之和, 1 = 直线, 0 = 来回)
  三态(初值阈值, 由 B 的结果回头校准):
    上涨趋势  ER20 ≥ 0.30 且 收 > EMA20 > EMA60 且 EMA20 比 5 日前高      下跌趋势  镜像
    交易区间  ER20 < 0.30 且 20 日收盘箱体宽度 ≤ 25% 且 收盘在上沿附近(顶部 15%)、下沿附近(底部 15%)各 ≥ 2 次 → 给箱体上下沿(按收盘价, 防单根影线)
    无规则    其余
  长周期可靠性: EMA 需要约 3×N 根 K 线才收敛, 不足的标 bars_ok=false(上市不满 ~4.5 年的票 EMA388 不可信)
  C 风险仓位: 止损候选 = 箱体下沿 / EMA20 / 收 − 2×ATR; 每笔风险 = 账户 1%(可调) → 股数 = 风险金额 / (入场 − 止损), 单票上限 30%, 100 股取整, 费用每笔最低 5 元
产物: downloads/market/<D>/indicators.jsonl(一票一行, 全市场; 每晚 check md 跑) —— 消费方见 README「indicators 消费方」
函数(给 regime_trades / 盯盘 / 做 T / 私有 skill 用): series(sym) → DataFrame(按日全指标) · regime_at(df, D) · sizing(...)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/quotes/indicators_db.py [--date D] [--codes 002714,601988] [--validate]
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", message=".*pandas only supports SQLAlchemy.*")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from kline_db import db   # noqa: E402

EMA_N = [5, 10, 20, 30, 60, 120, 144, 169, 388]
MA_N = [5, 10, 20, 60, 120, 144, 250]
ER_TREND, BOX_W, EDGE, TOUCH = 0.30, 0.25, 0.15, 2
RISK_PCT, MAX_POS = 0.01, 0.30


def load(syms=None, d0="2018-01-01", d1=None):
    c = db()
    try:
        q = ("select symbol, trade_date, cast(open as double) o, cast(high as double) h, cast(low as double) l, cast(close as double) c, "
             "cast(pre_close as double) pc, cast(volume as double) v from kline_day where is_deleted=0 and trade_date>=%s" + (" and trade_date<=%s" if d1 else ""))
        args = [d0] + ([d1] if d1 else [])
        if syms:
            q += f" and symbol in ({','.join(['%s'] * len(syms))})"
            args += list(syms)
        return pd.read_sql(q, c, params=args)
    finally:
        c.close()


def compute(g):
    """单只票: 原始日线 → 前复权 + 全部指标(按日)"""
    g = g.sort_values("trade_date").reset_index(drop=True)
    g = g[(g["c"] > 0) & (g["pc"] > 0)]
    if len(g) < 25:
        return None
    r = (g["c"] / g["pc"]).to_numpy()
    # 10/19: 单日涨跌超 ±35%(A 股最大涨跌幅 30%)= 拆分 / 合并等昨收没调整的公司行为(实测 588200 拆分后 EMA144 偏离 -55%) → 当日按不变链接
    r = np.where(np.abs(r - 1) > 0.35, 1.0, r)
    adj = np.cumprod(r)
    adj = adj / adj[-1] * g["c"].iloc[-1]        # 前复权: 最新一天 = 实际价
    k = adj / g["c"].to_numpy()
    d = pd.DataFrame({"date": g["trade_date"].astype(str).to_numpy(), "o": g["o"].to_numpy() * k, "h": g["h"].to_numpy() * k,
                      "l": g["l"].to_numpy() * k, "c": adj, "raw_c": g["c"].to_numpy(), "v": g["v"].to_numpy()})
    for n in EMA_N:
        d[f"ema{n}"] = d["c"].ewm(span=n, adjust=False).mean()
    for n in MA_N:
        d[f"ma{n}"] = d["c"].rolling(n).mean()
    tr = pd.concat([d["h"] - d["l"], (d["h"] - d["c"].shift()).abs(), (d["l"] - d["c"].shift()).abs()], axis=1).max(axis=1)
    d["atr14"] = tr.rolling(14).mean()
    d["er20"] = (d["c"] - d["c"].shift(20)).abs() / d["c"].diff().abs().rolling(20).sum()
    d["box_hi"] = d["c"].rolling(20).max()   # 箱体按收盘价定(单日长影线不撑大箱体; 10/18: 牧原 10/15 盘中 38.30 一根针)
    d["box_lo"] = d["c"].rolling(20).min()
    w = d["box_hi"] - d["box_lo"]
    top = (d["c"] >= d["box_hi"] - EDGE * w).astype(int).rolling(20).sum()
    bot = (d["c"] <= d["box_lo"] + EDGE * w).astype(int).rolling(20).sum()
    up = (d["er20"] >= ER_TREND) & (d["c"] > d["ema20"]) & (d["ema20"] > d["ema60"]) & (d["ema20"] > d["ema20"].shift(5))
    dn = (d["er20"] >= ER_TREND) & (d["c"] < d["ema20"]) & (d["ema20"] < d["ema60"]) & (d["ema20"] < d["ema20"].shift(5))
    box = (d["er20"] < ER_TREND) & (w / d["c"] <= BOX_W) & (top >= TOUCH) & (bot >= TOUCH)
    d["regime"] = np.select([up, dn, box], ["上涨趋势", "下跌趋势", "交易区间"], "无规则")
    d.loc[d["er20"].isna(), "regime"] = "数据不足"
    d["box_pos"] = (d["c"] - d["box_lo"]) / w.replace(0, np.nan)
    d["bars"] = np.arange(1, len(d) + 1)
    return d


def series(sym, asof=None):
    raw = load([sym], d1=asof)
    return compute(raw) if not raw.empty else None


def sizing(equity, entry, stop, risk_pct=RISK_PCT, max_pos=MAX_POS, lot=100):
    """C: 按风险倒推股数(入场 − 止损 = 每股风险; 风险金额 = 账户 × risk_pct; 单票上限 max_pos; 来回最低 5 元费用计入风险)"""
    if not entry or not stop or stop >= entry:
        return 0
    per = entry - stop
    q = (equity * risk_pct - 10) / per
    q = min(q, equity * max_pos / entry)
    return max(0, int(q // lot * lot))


def kelly(p, b, frac=0.25, cap=0.3):
    """凯利分数(胜率 p, 盈亏比 b) × frac(默认 1/4 凯利), 上限 cap; ≤0 = 期望为负, 不该做"""
    if not p or not b or b <= 0:
        return None
    f = p - (1 - p) / b
    return round(max(0.0, min(cap, f * frac)), 4)


def row_of(sym, d, i):
    x = d.iloc[i]
    c, raw = float(x["c"]), float(x["raw_c"])
    s = raw / c   # 历史日的前复权价换回当日实际价(当日为最新时 s=1)
    out = {"symbol": sym, "date": x["date"], "close": round(raw, 3), "regime": x["regime"], "er20": None if pd.isna(x["er20"]) else round(float(x["er20"]), 3),
           "atr14_pct": None if pd.isna(x["atr14"]) else round(float(x["atr14"]) / c, 4)}
    for n in EMA_N:
        out[f"ema{n}"] = round(float(x[f"ema{n}"]) * s, 3)
    for n in MA_N:
        out[f"ma{n}"] = None if pd.isna(x[f"ma{n}"]) else round(float(x[f"ma{n}"]) * s, 3)
    out["bars"] = int(x["bars"])
    out["ema_ok"] = {n: bool(x["bars"] >= 3 * n) for n in (120, 144, 169, 388)}
    out["vs_ema144"] = round(c / float(x["ema144"]) - 1, 4)
    out["vs_ema169"] = round(c / float(x["ema169"]) - 1, 4)
    if not pd.isna(x["box_hi"]):
        out["box_lo"], out["box_hi"] = round(float(x["box_lo"]) * s, 3), round(float(x["box_hi"]) * s, 3)
        out["box_pos"] = None if pd.isna(x["box_pos"]) else round(float(x["box_pos"]), 3)
    stops = {"box_lo": out.get("box_lo"), "ema20": round(float(x["ema20"]) * s, 3),
             "atr2": round((c - 2 * float(x["atr14"])) * s, 3) if not pd.isna(x["atr14"]) else None}
    out["stops"] = {k: v for k, v in stops.items() if v and v < raw}
    out["size_1pct_10w"] = {k: sizing(100000, raw, v) for k, v in out["stops"].items()}   # 10 万账户、风险 1% 时的建议股数
    return out


def snapshot(D, codes=None):
    syms = None
    if codes:
        import a_rules as AR
        syms = [AR.symbol(c) for c in codes]
    t0 = dt.datetime.now()
    raw = load(syms, d0=(dt.date.fromisoformat(D) - dt.timedelta(days=2000)).isoformat(), d1=D)
    rows = []
    for sym, g in raw.groupby("symbol"):
        d = compute(g)
        if d is None or d["date"].iloc[-1] != D:
            continue
        rows.append(row_of(sym, d, len(d) - 1))
    if codes:
        return rows
    out = ROOT / "downloads" / "market" / D
    out.mkdir(parents=True, exist_ok=True)
    with (out / "indicators.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    cnt = pd.Series([r["regime"] for r in rows]).value_counts().to_dict()
    print(f"indicators {D}: {len(rows)} 只, 三态分布 {cnt}, 用时 {(dt.datetime.now() - t0).seconds}s → {out / 'indicators.jsonl'}")
    return rows


def validate(n_sym=600, seed=7):
    """三态分类器自检: 被标成某状态之后 5 日, 是否表现出该状态应有的样子(趋势延续 / 区间回归)"""
    c = db()
    try:
        syms = pd.read_sql("select distinct symbol from kline_day where is_deleted=0 and trade_date<='2019-01-02' and (symbol like 'sh60%%' or symbol like 'sz00%%' or symbol like 'sz30%%')", c)["symbol"].tolist()
    finally:
        c.close()
    rng = np.random.default_rng(seed)
    pick = list(rng.choice(syms, size=min(n_sym, len(syms)), replace=False))
    raw = load(pick, d0="2018-01-01")
    parts = []
    for _, g in raw.groupby("symbol"):
        d = compute(g)
        if d is None:
            continue
        for h in (1, 5, 20, 60):
            d[f"f{h}"] = d["c"].shift(-h) / d["c"] - 1
        d["in_box5"] = (d["c"].shift(-5) <= d["box_hi"]) & (d["c"].shift(-5) >= d["box_lo"])
        parts.append(d.iloc[400:-60])
    A = pd.concat(parts)
    L = ["| 状态 | 样本(票·日) | 占比 | 之后 1 / 5 / 20 / 60 日收益均值 | 之后 1 / 5 / 20 / 60 日为正 | 5 日后仍在箱体内 | 箱体位置 vs 之后 5 / 20 日 IC |", "|---|---|---|---|---|---|---|"]
    for k, s in list(A.groupby("regime")) + [("全体", A)]:
        ic = " / ".join(f"{s[['box_pos', f'f{h}']].corr(method='spearman').iloc[0, 1]:+.3f}" for h in (5, 20)) if k == "交易区间" else ""
        L.append(f"| {k} | {len(s)} | {len(s) / len(A):.0%} | " + " / ".join(f"{s[f'f{h}'].mean() * 100:+.2f}%" for h in (1, 5, 20, 60)) + " | "
                 + " / ".join(f"{(s[f'f{h}'] > 0).mean():.0%}" for h in (1, 5, 20, 60)) + f" | {s['in_box5'].mean():.0%} | {ic} |")
    md = [f"# 三态分类器自检({len(pick)} 只老票随机抽样, 2019~今, indicators_db.py --validate)", "",
          "> 应有的样子: 上涨趋势之后 5 日为正占比 > 全体; 下跌趋势 < 全体; 交易区间 5 日后仍在箱体内的比例高, 且箱体位置越高之后越跌(IC 为负 = 区间里高抛低吸成立)。", ""] + L
    rp = ROOT / "scripts" / "dfcf" / "paper" / "reports" / f"regime_validate_{dt.date.today():%Y%m%d}.md"
    rp.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(L))
    print(f"→ {rp.relative_to(ROOT)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--codes")
    ap.add_argument("--validate", action="store_true")
    a = ap.parse_args()
    if a.validate:
        return validate()
    if not a.date:
        c = db()
        try:
            cur = c.cursor()
            cur.execute("select max(trade_date) from kline_day where symbol='sh000001' and is_deleted=0")
            a.date = str(cur.fetchone()[0])
        finally:
            c.close()
    rows = snapshot(a.date, a.codes.split(",") if a.codes else None)
    if a.codes:
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
