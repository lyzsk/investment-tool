# -*- coding: utf-8 -*-
"""draw_box.py — 画日线箱体示意图(10/24 用户要: 箱体怎么定, 画张图看)
口径 = skills/market-skill/references/kline_study/definitions.md §2.1(草案): 摆动高/低点 = 最高/最低严格高(低)于左右各 k 根; 箱体上沿 / 下沿 = 最近 3 个已确认摆动高 / 低点的中位数;
宽度 2.5~12 ATR; 回看期 ≥80% 收盘落在 [下沿−0.5ATR, 上沿+0.5ATR]; 只用 t−1 前已确认的摆动点(不偷看)
用法: python draw_box.py 002714 [结束日] [根数] [输出png]
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "backfill_bilibili")]
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False
K, LB, MINW, MAXW, CONTAIN = 3, 60, 2.5, 12.0, 0.8


def load(code, end, n):
    import manual_backfill as mb
    c = mb.db().cursor()
    c.execute("select symbol, name from investment_market.security_master where code=%s and sec_type in ('STOCK', 'CB', 'ETF') limit 1", (code,))
    sym, name = c.fetchone()
    c.execute("select trade_date, open, high, low, close, pre_close, volume from investment_market.kline_day where symbol=%s and is_deleted=0 and trade_date <= %s "
              "order by trade_date desc limit %s", (sym, end, n + LB + 20))
    r = c.fetchall()[::-1]
    d = np.array([str(x[0]) for x in r])
    o, h, l_, cl, pc, a = (np.array([float(x[i] or 0) for x in r]) for i in range(1, 7))
    return name, d, o, h, l_, cl, pc, a


def boxes(h, l_, cl, pc):
    n = len(h)
    tr = np.maximum(h - l_, np.maximum(abs(h - pc), abs(l_ - pc)))
    atr = np.array([tr[max(0, i - 13):i + 1].mean() for i in range(n)])
    ph = np.zeros(n, bool)
    pl = np.zeros(n, bool)
    for i in range(K, n - K):
        w = list(range(i - K, i)) + list(range(i + 1, i + K + 1))
        ph[i] = all(h[i] > h[j] for j in w)
        pl[i] = all(l_[i] < l_[j] for j in w)
    R, S = np.full(n, np.nan), np.full(n, np.nan)
    for t in range(LB + K + 1, n):
        a = atr[t - 1]
        hv = [h[i] for i in range(t - 1 - K, t - LB - 1, -1) if ph[i]][:3]
        lv = [l_[i] for i in range(t - 1 - K, t - LB - 1, -1) if pl[i]][:3]
        if len(hv) < 2 or len(lv) < 2:
            continue
        r, s = float(np.median(hv)), float(np.median(lv))
        if not (MINW <= (r - s) / a <= MAXW):
            continue
        win = cl[t - LB:t]
        if np.mean((win >= s - 0.5 * a) & (win <= r + 0.5 * a)) < CONTAIN:
            continue
        R[t], S[t] = r, s
    return R, S, ph, pl, atr


def seg_boxes(o, h, l_, cl, atr, s0, minb=8, minw=1.5, maxw=8.0, tol=0.5, fake=2):
    """段式箱体(10/24 改; 滚动中位数口径在趋势+横盘混合的 60 天里包含率过不了, 牧原 3 个月只认出 4 天):
    从某根起取 minb 根, 上沿 = 实体顶 90% 分位、下沿 = 实体底 10% 分位(去单根长影线), 宽度在 minw~maxw ATR → 起箱;
    往后延伸: 收盘在 [下沿 − tol·ATR, 上沿 + tol·ATR] 内就算还在箱里; 收盘越界但 fake 根内收回 = 假突破 / 假跌破(UT / Spring), 箱体不断;
    连续越界 > fake 根 = 离箱。每延伸一根重算上下沿。返回 [(起, 止, 上沿, 下沿, 假突破, 假跌破)]"""
    n = len(cl)
    out, i = [], s0
    while i + minb <= n:
        a = atr[i + minb - 1]
        top = np.maximum(o, cl)
        bot = np.minimum(o, cl)
        R, S = np.quantile(top[i:i + minb], 0.9), np.quantile(bot[i:i + minb], 0.1)
        if not (minw <= (R - S) / a <= maxw):
            i += 1
            continue
        j, out_n, ut, sp = i + minb, 0, 0, 0
        while j < n:
            if S - tol * a <= cl[j] <= R + tol * a:
                out_n = 0
            else:
                out_n += 1
                if out_n > fake:
                    break
            if out_n == 0 and j > i + minb:   # 刚收回: 之前的越界算假突破 / 假跌破
                if h[j - 1] > R + tol * a and cl[j - 1] > R + tol * a:
                    ut += 1
                if l_[j - 1] < S - tol * a and cl[j - 1] < S - tol * a:
                    sp += 1
            j += 1
            seg = slice(i, j - out_n)
            R, S = np.quantile(top[seg], 0.9), np.quantile(bot[seg], 0.1)
        end = j - out_n - 1
        if end - i + 1 >= minb:
            out.append((i, end, float(R), float(S), ut, sp))
            i = end + 1
        else:
            i += 1
    return out


def main(code, end="2026-10-23", n=90, out=None):
    name, d, o, h, l_, cl, pc, amt = load(code, end, n)
    R, S, ph, pl, atr = boxes(h, l_, cl, pc)
    s0 = len(d) - n
    x = np.arange(n)
    fig, (ax, av) = plt.subplots(2, 1, figsize=(13, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    fig.patch.set_facecolor("white")
    for i in range(n):
        j = s0 + i
        up = cl[j] >= o[j]
        col = "#e03131" if up else "#1c9c5a"
        ax.vlines(i, l_[j], h[j], color=col, lw=1)
        ax.add_patch(plt.Rectangle((i - 0.35, min(o[j], cl[j])), 0.7, max(abs(cl[j] - o[j]), 0.01), color=col, fill=not up, lw=1))
        av.bar(i, amt[j] / 1e4, color=col, width=0.7)
        if ph[j]:
            ax.plot(i, h[j] + 0.25 * atr[j], "v", color="#7048e8", ms=5)
        if pl[j]:
            ax.plot(i, l_[j] - 0.25 * atr[j], "^", color="#1971c2", ms=5)
    segs = seg_boxes(o, h, l_, cl, atr, s0)
    for k_, (a_, b_, r, s_, ut, sp) in enumerate(segs):
        xa, xb = a_ - s0, b_ - s0
        ax.add_patch(plt.Rectangle((xa - 0.5, s_), xb - xa + 1, r - s_, color="#ffd43b", alpha=0.22, lw=0))
        ax.hlines([r], xa - 0.5, xb + 0.5, color="#f08c00", lw=1.8)
        ax.hlines([s_], xa - 0.5, xb + 0.5, color="#1971c2", lw=1.8)
        ax.text(xb + 0.6, r, f"上沿 {r:.2f}", color="#f08c00", fontsize=9, va="center")
        ax.text(xb + 0.6, s_, f"下沿 {s_:.2f}", color="#1971c2", fontsize=9, va="center")
        ax.text((xa + xb) / 2, r + 0.15 * atr[b_], f"箱体{k_ + 1}: {d[a_][5:]}~{d[b_][5:]}({b_ - a_ + 1}天, 宽 {(r - s_) / atr[b_]:.1f}ATR)", ha="center", fontsize=8.5, color="#495057")
    last = n - 1
    a = atr[-1]
    cur = segs[-1] if segs and segs[-1][1] == len(cl) - 1 else None
    txt = (f"最后一根 {d[-1]} 收 {cl[-1]:.2f}({(cl[-1] / pc[-1] - 1) * 100:+.2f}%)  ATR14={a:.2f}\n"
           + (f"当前在日线箱体{len(segs)}里: 上沿 {cur[2]:.2f} / 下沿 {cur[3]:.2f}, 现价在箱体 {(cl[-1] - cur[3]) / (cur[2] - cur[3]) * 100:.0f}% 位置" if cur else "当前不在箱体里(已离箱 = 趋势段)"))
    ax.text(0.01, 0.98, txt, transform=ax.transAxes, va="top", fontsize=10, bbox=dict(fc="white", ec="#adb5bd"))
    ax.set_title(f"{name}({code}) 日线箱体示意 — 段式: 起箱 8 根 / 上沿=实体顶 90% 分位 / 下沿=实体底 10% 分位 / 收盘越界 0.5ATR 连续 >2 根才算离箱(1~2 根收回 = 假突破 / 假跌破)", fontsize=10)
    ax.grid(alpha=0.2)
    av.set_ylabel("成交量(万)")
    av.grid(alpha=0.2)
    tick = list(range(0, n, 10)) + [last]
    av.set_xticks(tick)
    av.set_xticklabels([d[s0 + t][5:] for t in tick], fontsize=8)
    ax.plot([], [], "v", color="#7048e8", label="摆动高点")
    ax.plot([], [], "^", color="#1971c2", label="摆动低点")
    ax.legend(loc="lower right", fontsize=9)
    plt.tight_layout()
    out = out or str(ROOT / "skills" / "market-skill" / "references" / "kline_study" / "img" / f"box_{code}_{end}.png")
    fig.savefig(out, dpi=110)
    print(out)
    print(txt)
    for a_, b_, r, s_, ut, sp in segs:
        print(f"  箱体 {d[a_]}~{d[b_]}: 上沿 {r:.2f} 下沿 {s_:.2f}({b_ - a_ + 1} 天, 假突破 {ut} 假跌破 {sp})")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], *(a[1:2] or ["2026-10-23"]), *([int(a[2])] if len(a) > 2 else []), *(a[3:4]))
