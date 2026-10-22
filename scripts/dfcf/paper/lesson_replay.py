# -*- coding: utf-8 -*-
"""lesson_replay.py — 教训预演: 用户 / 盘中得出的教训, 先在历史分钟线上回放验证, 再进规则(10/21 用户: "不能通过赔钱来吸取教训"; 零 token、零请求)

每条教训 = 一个"事件定义 + 两种执行方式"的回放: 找出历史上所有同类事件, 两种方式各算一遍成交价, 按条件分桶比差价 / 概率 / 赔率。
  结论写 results/lesson_replay/<教训>.md + .json; 规则(order-skill lessons、执行器止损)引用这里的数字, 不再只靠单个样本。
数据: downloads/tzzb/_minutes/<日>.jsonl(导师真人成交日的 1 分钟线, 2025-09 起约 5900 只·日) + downloads/market/<日>/kline_minute.jsonl(10/09 起关注集约 900 只·日)
     字段 symbol / barTime / open high low close / volume / avgPrice(当日累计均价 = 分时均线)

教训 L13 breakdown(10/21 澳弘): 跌破"日内前低"后怎么卖
  事件: 10:00~14:30, 某分钟最低价跌破 09:31 起到上一分钟的日内最低(且这个前低已守住 ≥15 分钟); 每只·日取第一次
  量比 vr = 破位分钟量 / 前 20 分钟均量; 续跌 = 破位后 3 分钟内收盘再低于前低 0.5%
  A 立刻走 = 破位分钟收盘价卖
  B 用户规则 = 放量(vr≥2)且续跌 → 第一个续跌分钟收盘卖; 否则等反抽: 之后第一个最高价 ≥ 分时均线×0.998 的分钟, 按 均线×0.998 卖;
              硬底线: 先跌到 前低×0.99 → 按 前低×0.99 卖; 等满 W 分钟都没反抽也没破底线 → 第 W 分钟收盘卖(W = 15 / 30)
  输出: 按 vr 分桶(缩量 <1 / 平量 1~2 / 放量 ≥2)的 B 比 A 多卖的幅度(中位 / 均值 / 胜率)、反抽到均线的概率、触底线的概率
用法: python lesson_replay.py breakdown [--since 2025-09-01]
"""
import argparse
import glob
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "results" / "lesson_replay"


def load_days(since):
    """{(日, 代码): [bar...]}; 两个源重叠时以行情库 kline_minute 为准"""
    days = defaultdict(list)
    files = sorted(glob.glob(str(ROOT / "downloads" / "tzzb" / "_minutes" / "*.jsonl"))) + \
        sorted(glob.glob(str(ROOT / "downloads" / "market" / "*" / "kline_minute.jsonl")))
    seen = set()
    for f in files:
        src = "mkt" if "kline_minute" in f else "tzzb"
        rows = defaultdict(list)
        with open(f, encoding="utf-8") as fh:
            for l in fh:
                try:
                    r = json.loads(l)
                except ValueError:
                    continue
                s = r.get("symbol") or ""
                if s.startswith(("sh000", "sz399")) or not r.get("barTime") or r.get("close") is None:   # 指数 / 坏行不算
                    continue
                d = r.get("tradeDate") or r["barTime"][:10]
                if d < since:
                    continue
                rows[(d, s)].append(r)
        for k, v in rows.items():
            if src == "mkt" or k not in seen:
                days[k] = sorted(v, key=lambda r: r["barTime"])
                seen.add(k)
    return days


def breakdown(bars, W):
    t = [b["barTime"][11:16] for b in bars]
    if len(bars) < 120:
        return None
    for i in range(1, len(bars)):
        if not ("10:00" <= t[i] <= "14:30"):
            continue
        prior = bars[1:i]   # 09:31 起(09:30 那根是集合竞价)
        if len(prior) < 20:
            continue
        lo = min(b["low"] for b in prior)
        j = max(k for k, b in enumerate(prior) if b["low"] == lo) + 1   # 前低出现的位置
        if bars[i]["low"] >= lo or i - j < 15 or lo <= 0:
            continue
        v20 = [b["volume"] for b in bars[max(1, i - 20):i]]
        vr = bars[i]["volume"] / (sum(v20) / len(v20)) if sum(v20) else None
        if vr is None:
            return None
        a = bars[i]["close"]
        floor = lo * 0.99
        heavy = vr >= 2
        follow = next((k for k in range(i + 1, min(i + 4, len(bars))) if bars[k]["close"] <= lo * 0.995), None)
        how, b = None, None
        if heavy and follow is not None:
            how, b = "放量续跌立刻走", bars[follow]["close"]
        else:
            for k in range(i + 1, min(i + 1 + W, len(bars))):
                x = bars[k]
                if x["low"] <= floor:
                    how, b = "触底线", floor
                    break
                vw = x.get("avgPrice") or 0
                if vw and x["high"] >= vw * 0.998:
                    how, b = "反抽到均线", max(vw * 0.998, x["low"])
                    break
            if b is None:
                k = min(i + W, len(bars) - 1)
                how, b = "等满没反抽", bars[k]["close"]
        later = bars[i + 1:]
        return {"t": t[i], "lo": lo, "vr": round(vr, 2), "A": a, "B": round(b, 4), "how": how, "d": round((b / a - 1) * 100, 3),
                "rebound_max": round((max(x["high"] for x in later[:30]) / a - 1) * 100, 3) if later else 0,
                "close": round((bars[-1]["close"] / a - 1) * 100, 3)}
    return None


def run_breakdown(since):
    days = load_days(since)
    res = {}
    for W in (15, 30):
        evs = []
        for (d, s), bars in days.items():
            e = breakdown(bars, W)
            if e:
                evs.append({"date": d, "sym": s, **e})
        res[W] = evs
    L = [f"# 教训预演 L13: 跌破日内前低后 立刻走(A) vs 用户规则(B)", "",
         f"数据: {since} 起 1 分钟线 {len(days)} 只·日(导师成交日缓存 + 行情库关注集); 事件 = 10:00~14:30 首次跌破守了 ≥15 分钟的日内前低, 每只·日一次",
         "B = 放量(量比≥2)且 3 分钟内续跌 0.5% → 立刻走; 否则等反抽到分时均线(×0.998)卖, 先跌到前低 −1% 按底线卖, 等满 W 分钟按收盘卖", ""]
    out = {}
    for W, evs in res.items():
        L += [f"## 等待上限 W = {W} 分钟(事件 {len(evs)} 个)", "",
              "| 量比分桶 | 事件数 | B 比 A 多卖 中位 | 均值 | B 更好占比 | 反抽到均线 | 触底线 | 放量续跌立刻走 | 等满没反抽 | A 之后 30 分钟最大反弹 中位 | A 到收盘 中位 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for name, f in (("缩量 <1", lambda v: v < 1), ("平量 1~2", lambda v: 1 <= v < 2), ("放量 ≥2", lambda v: v >= 2), ("全部", lambda v: True)):
            g = [e for e in evs if f(e["vr"])]
            if not g:
                continue
            ds = [e["d"] for e in g]
            c = defaultdict(int)
            for e in g:
                c[e["how"]] += 1
            row = {"n": len(g), "med": round(st.median(ds), 3), "mean": round(st.mean(ds), 3), "win": round(sum(x > 0 for x in ds) / len(g), 3),
                   **{k: round(c[k] / len(g), 3) for k in ("反抽到均线", "触底线", "放量续跌立刻走", "等满没反抽")},
                   "reb": round(st.median(e["rebound_max"] for e in g), 3), "cls": round(st.median(e["close"] for e in g), 3)}
            out[f"W{W}_{name}"] = row
            L.append(f"| {name} | {row['n']} | {row['med']:+.2f}% | {row['mean']:+.2f}% | {row['win']:.0%} | {row['反抽到均线']:.0%} | {row['触底线']:.0%} | "
                     f"{row['放量续跌立刻走']:.0%} | {row['等满没反抽']:.0%} | {row['reb']:+.2f}% | {row['cls']:+.2f}% |")
        L.append("")
    ex = [e for e in res[30] if e["sym"] == "sh111024" and e["date"] == "2026-10-21"]
    L += ["## 读法", "- B 比 A 多卖 > 0 = 等反抽的规则比破位立刻卖强; 看缩量桶是否明显为正、放量桶是否接近 0 或为负(放量就该立刻走)",
          "- 赔率: 反抽到均线的概率 × 反抽幅度 vs 触底线概率 × 1% —— 就是\"低概率但赔率不对称也值得\"的量化版",
          "- 局限: 导师成交日缓存偏热门票; 3 分钟续跌 / 量比 2 / 均线 ×0.998 / 底线 1% 是用户口述的初版参数, 敏感性待扫"]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "L13_breakdown.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (OUT / "L13_breakdown.json").write_text(json.dumps({"summary": out, "events_W30": res[30]}, ensure_ascii=False), encoding="utf-8")
    print("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lesson", choices=["breakdown"])
    ap.add_argument("--since", default="2025-09-01")
    a = ap.parse_args()
    if a.lesson == "breakdown":
        run_breakdown(a.since)


if __name__ == "__main__":
    main()
