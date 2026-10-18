# -*- coding: utf-8 -*-
"""signal_lab.py — 分钟级信号实验室(零 token; 10/18 晚用户定 P2): 哪些微观结构 / 价量信号在我们"分时 + 等 API 回传"的节奏下真有用

数据: downloads/market/<日>/kline_minute.jsonl(关注集约 830 只的 1 分钟 OHLC + 累计均价) + tick_flow.jsonl(逐笔主动买卖, collect_minute.py 10/18 起; 缺 = 只测价量类)
信号(都在 t 分钟收盘时可知, 不偷看):
  MOM_k   动量      = close_t / close_{t-k} − 1(k = 5 / 15 / 30 分钟); IC 为负 = 该尺度是"反转"(REV = −MOM, 不重复列)
  VWAP    均价偏离  = close_t / 当日累计均价_t − 1; IC 为负 = "VWAP 回归"成立
  TFI_k   主动成交失衡 = Σ(主动买量 − 主动卖量) / Σ(主动买量 + 主动卖量), 过去 k 分钟(k = 5 / 15); TFI_D = 开盘至今
  RAND    随机因子(正态噪声) = 抛硬币对照: 它的 IC 波动范围就是"噪声带", 别的信号落在带内 = 没信号
  BASE    不判断基准 = 全关注集等权的同期收益(表里"市场均值"列, 用来看信号赚的是不是大盘的钱)
  (QI / DI / OFI 要盘口快照, P3 攒数据后接进来; 集合竞价失衡另见 auction_live_open)
评估(每 5 分钟取一个截面, 每个截面 ≥30 只票; 剔除开盘前 5 分钟和成交量为 0 的分钟):
  未来收益 h = 5 / 15 / 30 分钟 / 到收盘; 横截面秩相关 IC(Spearman) → 按日平均 = 日 IC
  均值 / t 值(跨日) / 日 IC 为正占比 / 多空价差(信号最高 10% − 最低 10% 的未来收益, 基点) — 价差 < 来回成本(约 15 基点)= 有统计意义也赚不到钱
  滚动验证: 每天用"之前的日子"(最多 40 天)的 IC 符号预测当天符号, 命中率 = 方向是否稳定(数据只有几天时只看方向)
产物: scripts/dfcf/paper/reports/signal_lab_<日>.md + scripts/dfcf/paper/signal_lab.json
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/signal_lab.py [--days 40]
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MKT = ROOT / "downloads" / "market"
H = {"5分": 5, "15分": 15, "30分": 30, "到收盘": None}
COST_BP = 15   # 来回成本(佣金 + 印花税 + 滑点)约 15 基点, 只作量级参考
INDEX = {"sh000001", "sz399001", "sz399006", "sh000688", "sh000300", "sh000852"}


def load_day(d):
    km = MKT / d / "kline_minute.jsonl"
    if not km.exists():
        return None
    k = pd.read_json(km, lines=True, dtype={"symbol": str})
    k = k[~k["symbol"].isin(INDEX)][["symbol", "barTime", "close", "volume", "avgPrice"]]
    tf = MKT / d / "tick_flow.jsonl"
    if tf.exists():
        f = pd.read_json(tf, lines=True, dtype={"symbol": str})[["symbol", "barTime", "buyVol", "sellVol"]]
        k = k.merge(f, on=["symbol", "barTime"], how="left")
        k[["buyVol", "sellVol"]] = k[["buyVol", "sellVol"]].fillna(0)
    k["barTime"] = pd.to_datetime(k["barTime"])
    return k.sort_values(["symbol", "barTime"]).reset_index(drop=True)


def factors(k, rng):
    g = k.groupby("symbol", sort=False)
    c = k["close"]
    out = pd.DataFrame(index=k.index)
    for n in (5, 15, 30):
        out[f"MOM_{n}"] = c / g["close"].shift(n) - 1
    out["VWAP"] = c / k["avgPrice"] - 1
    if "buyVol" in k:
        imb = k["buyVol"] - k["sellVol"]
        tot = k["buyVol"] + k["sellVol"]
        for n in (5, 15):
            num = imb.groupby(k["symbol"]).transform(lambda s: s.rolling(n, min_periods=n).sum())
            den = tot.groupby(k["symbol"]).transform(lambda s: s.rolling(n, min_periods=n).sum())
            out[f"TFI_{n}"] = num / den.replace(0, np.nan)
        out["TFI_D"] = imb.groupby(k["symbol"]).cumsum() / tot.groupby(k["symbol"]).cumsum().replace(0, np.nan)
    out["RAND"] = rng.standard_normal(len(k))
    for lab, h in H.items():
        out[f"fwd_{lab}"] = (g["close"].transform("last") if h is None else g["close"].shift(-h)) / c - 1
    out["barTime"] = k["barTime"]
    out["volume"] = k["volume"]
    return out


def day_stats(F, fac_cols):
    hm = F["barTime"].dt.strftime("%H:%M")
    F = F[(F["volume"] > 0) & (hm >= "09:35") & (F["barTime"].dt.minute % 5 == 0)]
    res = {}
    for lab in H:
        y = f"fwd_{lab}"
        sub = F.dropna(subset=[y])
        ics, spreads, mkt = {c: [] for c in fac_cols}, {c: [] for c in fac_cols}, []
        for _, s in sub.groupby("barTime"):
            if len(s) < 30:
                continue
            mkt.append(s[y].mean())
            ry = s[y].rank()
            for c in fac_cols:
                x = s[c]
                ok = x.notna()
                if ok.sum() < 30:
                    continue
                ics[c].append(np.corrcoef(x[ok].rank(), ry[ok])[0, 1])
                q = x[ok].quantile([0.1, 0.9])
                spreads[c].append(s.loc[ok & (x >= q[0.9]), y].mean() - s.loc[ok & (x <= q[0.1]), y].mean())
        res[lab] = {c: (np.nanmean(ics[c]) if ics[c] else np.nan, np.nanmean(spreads[c]) * 1e4 if spreads[c] else np.nan) for c in fac_cols}
        res[lab]["_mkt"] = np.mean(mkt) * 1e4 if mkt else np.nan
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=40)
    a = ap.parse_args()
    days = sorted(d.name for d in MKT.iterdir() if (d / "kline_minute.jsonl").exists())[-a.days:]
    rng = np.random.default_rng(20261018)
    per = {}
    has_flow = {}
    for d in days:
        k = load_day(d)
        if k is None or k.empty:
            continue
        F = factors(k, rng)
        cols = [c for c in F.columns if c.split("_")[0] in ("MOM", "VWAP", "TFI", "RAND")]
        per[d] = day_stats(F, cols)
        has_flow[d] = "TFI_5" in F
        print(f"{d}: {len(k['symbol'].unique())} 只, 信号 {len(cols)} 个{'(含主动买卖)' if has_flow[d] else '(无 tick_flow, 只测价量)'}")
    if not per:
        sys.exit("没有分钟线数据")
    facs = sorted({c for v in per.values() for c in v["5分"] if not c.startswith("_")}, key=lambda c: (c == "RAND", c))
    out = {"updated": dt.datetime.now().isoformat(timespec="seconds"), "days": list(per), "flow_days": [d for d, v in has_flow.items() if v], "result": {}}
    md = [f"# 分钟级信号实验室({min(per)} ~ {max(per)}, {len(per)} 个交易日; 主动买卖有 {sum(has_flow.values())} 天; signal_lab.py 机械生成)", "",
          "> 读法: **IC** = 信号和未来收益的横截面秩相关(按日平均), 正 = 信号高的票之后涨得多; MOM 的 IC 为负 = 该尺度是反转; VWAP 的 IC 为负 = 均价回归成立。",
          f"> **t** = 日 IC 均值 / 标准差 × √天数(|t|>2 才算有点意思); **正占比** = 日 IC 为正的天数比例; **滚动命中** = 用之前的日子的符号猜当天符号的命中率;",
          f"> **多空价差** = 信号最高 10% 减最低 10% 的未来收益(基点), < 来回成本约 {COST_BP} 基点 = 就算有统计意义也赚不到钱; **RAND** 一行是噪声带参照。", ""]
    for lab in H:
        md += [f"## 未来 {lab}(市场等权均值 {np.nanmean([per[d][lab]['_mkt'] for d in per]):+.1f} 基点 / 截面)", "",
               "| 信号 | IC 均值 | t | 正占比 | 滚动命中 | 多空价差(基点) | 天数 |", "|---|---|---|---|---|---|---|"]
        out["result"][lab] = {}
        for c in facs:
            ds = [d for d in per if c in per[d][lab] and not np.isnan(per[d][lab][c][0])]
            ic = np.array([per[d][lab][c][0] for d in ds])
            sp = np.array([per[d][lab][c][1] for d in ds])
            if not len(ic):
                continue
            t = ic.mean() / ic.std(ddof=1) * np.sqrt(len(ic)) if len(ic) > 1 and ic.std(ddof=1) > 0 else np.nan
            hits = [np.sign(ic[:i][-40:].mean()) == np.sign(ic[i]) for i in range(1, len(ic))]
            hit = np.mean(hits) if hits else np.nan
            out["result"][lab][c] = {"ic": round(float(ic.mean()), 4), "t": None if np.isnan(t) else round(float(t), 2), "pos": round(float((ic > 0).mean()), 2),
                                     "hit": None if np.isnan(hit) else round(float(hit), 2), "spread_bp": round(float(np.nanmean(sp)), 1), "n": len(ic)}
            md.append(f"| {c} | {ic.mean():+.3f} | {'—' if np.isnan(t) else f'{t:+.1f}'} | {(ic > 0).mean():.0%} | {'—' if np.isnan(hit) else f'{hit:.0%}'} | {np.nanmean(sp):+.1f} | {len(ic)} |")
        md.append("")
    md += ["## 口径限制", "",
           "- 分笔数据: 通达信\"逐笔\"实际是约 3 秒一档的分笔成交, 主动买卖方向是按成交价对买一 / 卖一推出来的, 不是交易所原始标记",
           "- 关注集不是全市场(约 830 只: paper 持仓 / 计划 / 导师操作 / 涨跌停 / md 提及), 有选择偏差",
           "- 天数少时只看方向; 价差未扣涨跌停买不到 / 卖不掉的情况"]
    rp = HERE / "reports" / f"signal_lab_{dt.date.today():%Y%m%d}.md"
    rp.write_text("\n".join(md) + "\n", encoding="utf-8")
    (HERE / "signal_lab.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(md[6:]))
    print(f"→ {rp.relative_to(ROOT)}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
