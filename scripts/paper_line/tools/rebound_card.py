# -*- coding: utf-8 -*-
"""rebound_card.py — 「反抽卡」(10/27 晚用户批: 让模型说"反抽"时必须填四样, 数值范围由代码按本票自己的分时算好给它; 零 token)

四样(用户原话的定义, 全部按本票近 N 个交易日的 1 分钟路径动态算, 没有固定常数):
  ① 起点      = 这段下跌后的当天最低(盘中实时: 到此刻为止的日内最低)
  ② 反抽起算  = 从起点涨多少才算"进入反抽" = 本票 5 分钟收益 σ5 × 2(噪音以上; 低于它只是抖动)
  ③ 反抽结束  = 从反抽高点回落多少算结束 = 本票历史"反抽途中正常回撤"的 P75(超过 = 不再是途中抖动); 或跌回均价线下
  ④ 走强改判  = 站上昨收 + 放量(近 3 分钟量 ≥ 本票平时同长度 2 倍) + 创出新的反抽高 → 不再算反抽, 改判"弱转强"
另给两个防「只冲高一次就一路跌、一直等二次冲高」的量(用户 10/27 22:4x 问):
  首波高度    = 本票历史"开盘后第一个低点 → 第一波反抽高"的高度分布 P25 / P50 / P75(相对昨收, 百分点) —— 第一份到 P50 就卖, 不等二次
  首波用时    = 从低点到首波高点的分钟数 P75 —— 超过还没新高 = 反抽到头
历史上「首波之后还有更高的二次冲高」的比例也给出(二次冲高率), 模型据此决定留几成等第二波
数据: downloads/quotes/{stock,cb}/minute_path/<日>.jsonl(1 分钟收盘 + 量) + downloads/market/<日>/kline_minute.jsonl(minute_path 没有的日子)
用法: python rebound_card.py 002307 2026-10-28 [--days 30]
不自信点: "第一个低点"取开盘后 60 分钟内的最低; 首波结束 = 从首波高回落超过 ③ 的那一刻; 30 天样本里一字 / 停牌日跳过, 有效天数 <10 时只给提示
"""
import argparse
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MP = {"stock": ROOT / "downloads" / "quotes" / "stock" / "minute_path", "cb": ROOT / "downloads" / "quotes" / "cb" / "minute_path"}
MKT = ROOT / "downloads" / "market"
_CACHE = {}


def _q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))] if xs else None


def _sym(c):
    return ("sh" if c[:1] in ("6", "9", "5") or c[:2] == "11" else "bj" if c[:1] in ("4", "8") or c[:2] == "92" else "sz") + c


def paths(code, D, days=30):
    """→ [(日, 昨收, [分钟收盘], [分钟量])], D 之前最近 days 个交易日"""
    kind = "cb" if code[:2] in ("11", "12") else "stock"
    key = (code, D, days)
    if key in _CACHE:
        return _CACHE[key]
    got = {}
    for f in sorted(MP[kind].glob("*.jsonl")):
        if f.stem >= D:
            continue
        for l in f.open(encoding="utf-8"):
            if f'"{code}"' not in l[:30]:
                continue
            r = json.loads(l)
            if r.get("prev") and r.get("p"):
                got[f.stem] = (float(r["prev"]), [float(x) for x in r["p"]], [float(x or 0) for x in (r.get("v") or [0] * len(r["p"]))])
            break
    sym = _sym(code)
    for dd in sorted(p.name for p in MKT.glob("20*") if p.name < D)[-days - 5:]:
        if dd in got:
            continue
        f = MKT / dd / "kline_minute.jsonl"
        if not f.exists():
            continue
        p, v = [], []
        for l in f.open(encoding="utf-8"):
            if l.startswith(f'{{"symbol": "{sym}"'):
                r = json.loads(l)
                p.append(float(r["close"]))
                v.append(float(r.get("volume") or 0))
        if len(p) >= 200:
            kd = MKT / dd / "kline_day.jsonl"
            prev = None
            if kd.exists():
                for l in kd.open(encoding="utf-8"):
                    if f'"{sym}"' in l[:30]:
                        prev = float(json.loads(l).get("preClose") or 0) or None
                        break
            if prev:
                got[dd] = (prev, p, v)
    out = [(d,) + got[d] for d in sorted(got)[-days:]]
    _CACHE[key] = out
    return out


def sigma5(ps):
    rs = [ps[i + 5] / ps[i] - 1 for i in range(0, len(ps) - 5, 5) if ps[i] > 0]
    return statistics.pstdev(rs) if len(rs) >= 20 else None


def first_wave(prev, p, start_k, end_dd):
    """开盘后 60 分钟内的最低点 → 第一波反抽高(从高点回落超过 end_dd 就算结束) → (低, 低时刻, 高, 高时刻, 途中最大回撤, 之后有没有更高的二次冲高)"""
    n = len(p)
    if n < 120 or max(p) == min(p):
        return None
    i_lo = min(range(min(60, n)), key=lambda i: p[i])
    lo = p[i_lo]
    hi, i_hi, dd_in = lo, i_lo, 0.0
    started = False
    for i in range(i_lo + 1, n):
        if not started:
            if (p[i] - lo) / prev >= start_k:
                started = True
                hi, i_hi = p[i], i
            continue
        if p[i] > hi:
            hi, i_hi = p[i], i
        else:
            d_ = (hi - p[i]) / prev
            if d_ >= end_dd:
                break
            dd_in = max(dd_in, d_)
    if not started:
        return None
    second = max(p[i_hi + 1:] or [hi]) > hi * 1.0 + 0.5 * end_dd * prev
    return lo, i_lo, hi, i_hi, dd_in, second


def card(code, D, days=30):
    ps = paths(code, D, days)
    if len(ps) < 10:
        return {"code": code, "err": f"分钟路径只有 {len(ps)} 天(<10), 不给数值, 只按「首波到昨收附近」定性"}
    sig = [s for s in (sigma5(p) for _, _, p, _ in ps) if s]
    s5 = statistics.median(sig) if sig else 0.005
    start_k = 2 * s5
    # 先用 σ5 × 3 当临时结束阈值跑一遍, 拿到"途中回撤"分布, 再用它的 P75 作为正式结束阈值重跑
    tmp = [first_wave(pv, p, start_k, 3 * s5) for _, pv, p, _ in ps]
    dds = [w[4] for w in tmp if w]
    end_dd = max(_q(dds, .75) or 0, 1.5 * s5)
    W = [(d, pv, first_wave(pv, p, start_k, end_dd)) for d, pv, p, _ in ps]
    W = [(d, pv, w) for d, pv, w in W if w]
    if len(W) < 8:
        return {"code": code, "err": f"有效首波只有 {len(W)} 天"}
    hts = [(w[2] - w[0]) / pv * 100 for _, pv, w in W]
    mins = [w[3] - w[1] for _, _, w in W]
    tops = [(w[2] / pv - 1) * 100 for _, pv, w in W]
    sec = sum(1 for _, _, w in W if w[5]) / len(W)
    v1 = [statistics.fmean(v) for *_, v in ps if v and any(v)]
    return {"code": code, "D": D, "样本天数": len(W), "σ5%": round(s5 * 100, 2),
            "②反抽起算(从当天最低涨)%": round(start_k * 100, 2),
            "③反抽结束(从反抽高回落)%": round(end_dd * 100, 2),
            "首波高度%(相对昨收,百分点) P25/P50/P75": [round(_q(hts, x), 2) for x in (.25, .5, .75)],
            "首波高点位置%(相对昨收) P25/P50/P75": [round(_q(tops, x), 2) for x in (.25, .5, .75)],
            "首波用时(分钟) P50/P75": [_q(mins, .5), _q(mins, .75)],
            "首波后还有更高二次冲高的比例": round(sec, 2),
            "④走强改判": "站上昨收 + 近 3 分钟量 ≥ 平时 3 分钟量 × 2 + 创出新的反抽高",
            "平时每分钟量": round(statistics.median(v1)) if v1 else None}


def text(c):
    if c.get("err"):
        return f"- {c['code']}: 反抽卡 {c['err']}"
    h, t, m = c["首波高度%(相对昨收,百分点) P25/P50/P75"], c["首波高点位置%(相对昨收) P25/P50/P75"], c["首波用时(分钟) P50/P75"]
    return (f"- {c['code']} 反抽卡(近 {c['样本天数']} 天 1 分钟路径, σ5 {c['σ5%']}%): ①起点=当天最低 ②从最低涨 ≥{c['②反抽起算(从当天最低涨)%']}% 算进入反抽 "
            f"③从反抽高回落 ≥{c['③反抽结束(从反抽高回落)%']}%(或跌回均价线下)= 反抽结束 ④站上昨收+放量 2 倍+新反抽高 = 改判弱转强 | "
            f"首波高度 P25/P50/P75 {h[0]}/{h[1]}/{h[2]} 个点(高点在昨收 {t[0]:+}/{t[1]:+}/{t[2]:+}%) · 首波用时 中位 {m[0]} / P75 {m[1]} 分钟 · 首波后还有更高二次冲高 {c['首波后还有更高二次冲高的比例']:.0%}")


def block(codes, D):
    L = ["## 反抽卡(10/27 用户令: 写「反抽」必须填四样 —— 起点 / 起算 / 结束 / 走强改判, 数值从这里取; 首波到 P50 先卖一份, 不等二次冲高; 超过首波用时 P75 没新高 = 反抽到头)"]
    for c in codes:
        try:
            L.append(text(card(c, D)))
        except Exception as e:   # noqa: BLE001
            L.append(f"- {c}: 反抽卡算失败 {type(e).__name__}")
    return "\n".join(L)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("D")
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args()
    print(json.dumps(card(a.code, a.D, a.days), ensure_ascii=False, indent=1))
    print(block(a.code.split(","), a.D))
