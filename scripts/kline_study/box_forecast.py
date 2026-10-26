# -*- coding: utf-8 -*-
"""box_forecast.py — 箱体内某位置之后 N 天怎么走(本票自身历史, 段式箱体 draw_box.seg_boxes; 只用当时已知的箱体: 箱体起点 +8 根之后才算"在箱里")
输出: 样本 n / 之后 N 天收益 P10 / 中位 / P90 / 均值 / 最好最差, 以及 N 天内 收盘离箱向上 / 向下 / 仍在箱内 的比例
用法: python box_forecast.py <代码> <日> [N=5] [位置下限 位置上限]
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import draw_box as DB   # noqa: E402


def stats(code, end, N=5, lo=None, hi=None, days=900):
    name, d, o, h, l_, cl, pc, v = DB.load(code, end, days)
    R, S, ph, pl, atr = DB.boxes(h, l_, cl, pc)
    segs = DB.seg_boxes(o, h, l_, cl, atr, 0)
    cur = segs[-1] if segs and segs[-1][1] == len(cl) - 1 else None
    pos_now = (cl[-1] - cur[3]) / (cur[2] - cur[3]) if cur else None
    lo = pos_now - 0.15 if lo is None and pos_now is not None else lo
    hi = pos_now + 0.15 if hi is None and pos_now is not None else hi
    rets, up, dn, inn = [], 0, 0, 0
    if cur is None:   # 不在箱体里(趋势段): 用本票历史"也不在箱里、近 5 日涨跌幅相近(±0.5 ATR%×√5)"的日子
        inbox = np.zeros(len(cl), bool)
        for a_, b_, *_ in segs:
            inbox[a_ + 8:b_ + 1] = True
        m5 = lambda t: (cl[t] / cl[t - 5] - 1) * 100   # noqa: E731
        now5, band = m5(len(cl) - 1), atr[-1] / cl[-1] * 100 * 0.5 * 5 ** 0.5
        for t in range(25, len(cl) - N - 1):
            if not inbox[t] and abs(m5(t) - now5) <= band:
                rets.append((cl[t + N] / cl[t] - 1) * 100)
        r = np.array(rets)
        out = {"name": name, "code": code, "end": d[-1], "N": N, "box": None, "pos_now": None, "n": len(r), "口径": f"不在箱体: 近5日 {now5:+.1f}% ±{band:.1f}% 的历史日"}
        if len(r):
            out.update({"P10": round(np.percentile(r, 10), 2), "中位": round(np.median(r), 2), "P90": round(np.percentile(r, 90), 2), "均值": round(r.mean(), 2), "最好": round(r.max(), 2), "最差": round(r.min(), 2)})
        return out, (d, o, h, l_, cl, atr, segs)
    for a_, b_, r, s, _, _ in segs[:-1]:   # 历史箱体(不含当前这个, 防偷看)
        for t in range(a_ + 8, b_ + 1):
            if t + N >= len(cl):
                continue
            # 当时已知的上下沿: 只用 [a_, t] 这段
            top, bot = np.maximum(o, cl)[a_:t + 1], np.minimum(o, cl)[a_:t + 1]
            rt, st = np.quantile(top, 0.9), np.quantile(bot, 0.1)
            if rt <= st:
                continue
            p = (cl[t] - st) / (rt - st)
            if not (lo <= p <= hi):
                continue
            rets.append((cl[t + N] / cl[t] - 1) * 100)
            fut = cl[t + 1:t + N + 1]
            a = atr[t]
            if (fut > rt + 0.5 * a).any():
                up += 1
            elif (fut < st - 0.5 * a).any():
                dn += 1
            else:
                inn += 1
    r = np.array(rets)
    out = {"name": name, "code": code, "end": d[-1], "N": N, "box": cur and {"上沿": round(cur[2], 2), "下沿": round(cur[3], 2), "起": d[cur[0]]},
           "pos_now": None if pos_now is None else round(pos_now * 100), "pos_range": [round(lo * 100), round(hi * 100)] if lo is not None else None, "n": len(r)}
    if len(r):
        out.update({"P10": round(np.percentile(r, 10), 2), "中位": round(np.median(r), 2), "P90": round(np.percentile(r, 90), 2), "均值": round(r.mean(), 2),
                    "最好": round(r.max(), 2), "最差": round(r.min(), 2), "向上离箱": round(up / len(r) * 100), "向下离箱": round(dn / len(r) * 100), "仍在箱内": round(inn / len(r) * 100)})
    return out, (d, o, h, l_, cl, atr, segs)


if __name__ == "__main__":
    a = sys.argv[1:]
    o, _ = stats(a[0], a[1], int(a[2]) if len(a) > 2 else 5)
    print(o)
