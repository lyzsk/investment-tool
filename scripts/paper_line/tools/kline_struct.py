# -*- coding: utf-8 -*-
"""kline_struct.py — 必查「K线结构」(10/25 用户: K 线进 06 输出, 和统计概率一起给后市看法; 零 token, 只读行情库)

给一只票在 D 开盘前(只用 D 之前的数据; 盘中触发时 15 分钟用当天已走出来的分钟线):
  日线箱体: 段式(横盘 ≥8 根起箱; 上沿 = 箱内实体顶 90% 分位 / 下沿 = 实体底 10% 分位; 收盘越界 0.5 ATR 连续 >2 根才算离箱)+ 现价在箱体百分位 / 已离箱方向
  15 分钟箱体: 同算法, 用近 5 个交易日 15 分钟 K(行情库 kline_minute 合成; 10/09 起只有采集名单里的票)
  ATR14(日线)/ 近 20 日 zigzag 结构(按 1.5 ATR 分段: 高点 / 低点是否抬高 → 上升 / 下降 / 震荡)
口径和术语表一致(scripts/live/glossary.yaml 箱体上沿 / 下沿; 用户 10/25 定级别 日线 / 1 / 5 / 15 / 30 / 60 / 120 分钟)
用法: python kline_struct.py <代码> <D>
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "backfill_bilibili")]


def cur():
    import manual_backfill as mb
    return mb.db().cursor()


def sym(code):
    if code[:2] in ("sh", "sz", "bj"):   # 10/25: 指数直接给带前缀的 symbol(sh000001 上证 / sz399303 国证2000 / sz399006 创业板指)
        return code
    return ("sh" if code.startswith(("6", "9", "11", "5")) else "sz") + code


def atr14(h, l_, c, pc):
    tr = np.maximum(h - l_, np.maximum(abs(h - pc), abs(l_ - pc)))
    return np.array([tr[max(0, i - 13):i + 1].mean() for i in range(len(tr))])


def seg_boxes(o, h, l_, cl, atr, minb=8, minw=1.5, maxw=8.0, tol=0.5, fake=2):
    """段式箱体(和 scripts/kline_study/draw_box.seg_boxes 同口径; 这里不 import 它, 免得拖 matplotlib 进 venv)"""
    n = len(cl)
    top, bot = np.maximum(o, cl), np.minimum(o, cl)
    out, i = [], 0
    while i + minb <= n:
        a = atr[i + minb - 1]
        R, S = np.quantile(top[i:i + minb], 0.9), np.quantile(bot[i:i + minb], 0.1)
        if not a or not (minw <= (R - S) / a <= maxw):
            i += 1
            continue
        j, out_n = i + minb, 0
        while j < n:
            out_n = 0 if S - tol * a <= cl[j] <= R + tol * a else out_n + 1
            if out_n > fake:
                break
            j += 1
            seg = slice(i, j - out_n)
            R, S = np.quantile(top[seg], 0.9), np.quantile(bot[seg], 0.1)
        end = j - out_n - 1
        if end - i + 1 >= minb:
            out.append((i, end, float(R), float(S)))
            i = end + 1
        else:
            i += 1
    return out


def zigzag(h, l_, th):
    """按绝对阈值 th(价格单位)分段 → [(i, 价, 'H'/'L')]"""
    piv, d, ext_i = [], 0, 0
    for i in range(1, len(h)):
        if d >= 0 and h[i] >= h[ext_i]:
            ext_i = i if d >= 0 else ext_i
        if d <= 0 and l_[i] <= l_[ext_i]:
            ext_i = i if d <= 0 else ext_i
        if d >= 0 and h[ext_i] - l_[i] >= th:
            piv.append((ext_i, float(h[ext_i]), "H"))
            d, ext_i = -1, i
        elif d <= 0 and h[i] - l_[ext_i] >= th:
            piv.append((ext_i, float(l_[ext_i]), "L"))
            d, ext_i = 1, i
    return piv


def daily(code, D, n=160):
    c = cur()
    c.execute("select trade_date, open, high, low, close, pre_close from investment_market.kline_day where symbol=%s and is_deleted=0 and trade_date<%s "
              "order by trade_date desc limit %s", (sym(code), D, n))
    r = c.fetchall()[::-1]
    if len(r) < 30:
        return None
    d = [str(x[0]) for x in r]
    o, h, l_, cl, pc = (np.array([float(x[i] or 0) for x in r]) for i in range(1, 6))
    return d, o, h, l_, cl, pc


def m15(code, D, days=5, at=None):
    c = cur()
    c.execute("select distinct trade_date from investment_market.kline_minute where symbol=%s and is_deleted=0 and trade_date<=%s order by trade_date desc limit %s",
              (sym(code), D, days))
    ds = sorted(str(x[0]) for x in c.fetchall())
    if not ds:
        return None
    c.execute("select trade_date, bar_time, open, high, low, close from investment_market.kline_minute where symbol=%s and is_deleted=0 and trade_date>=%s and trade_date<=%s "
              "order by bar_time", (sym(code), ds[0], D))
    bars = {}
    for d, t, o, h, l_, cl in c.fetchall():
        hm = str(t)[11:16]
        if at and str(d) == D and hm > at[:5]:   # 10/25 修回放偷看: 盘中 / 回放只用 ≤ 此刻的分钟
            continue
        mins = int(hm[:2]) * 60 + int(hm[3:5])
        k = (str(d), (mins - 570 - 1) // 15 if mins < 720 else 8 + (mins - 780 - 1) // 15)   # 09:31~11:30 → 0~7, 13:01~15:00 → 8~15
        b = bars.get(k)
        o, h, l_, cl = float(o or cl), float(h or cl), float(l_ or cl), float(cl)
        bars[k] = [b[0], max(b[1], h), min(b[2], l_), cl] if b else [o, h, l_, cl]
    ks = sorted(bars)
    if len(ks) < 20:
        return None
    A = np.array([bars[k] for k in ks])
    return [f"{k[0][5:]}#{k[1]}" for k in ks], A[:, 0], A[:, 1], A[:, 2], A[:, 3]


def struct(code, D, px=None, at=None):
    R = daily(code, D)
    if not R:
        return {"err": "日线不足"}
    d, o, h, l_, cl, pc = R
    atr = atr14(h, l_, cl, pc)
    a = float(atr[-1])
    p = float(px or cl[-1])
    out = {"ATR14": round(a, 3), "ATR%": round(a / cl[-1] * 100, 2)}
    bx = seg_boxes(o, h, l_, cl, atr)
    last = bx[-1] if bx else None
    if last and last[1] >= len(cl) - 3:   # 最近 3 根内还在箱里
        R_, S_ = last[2], last[3]
        pos = (p - S_) / (R_ - S_) * 100 if R_ > S_ else None
        out["日线箱体"] = {"上沿": round(R_, 3), "下沿": round(S_, 3), "起": d[last[0]], "天数": last[1] - last[0] + 1, "宽(ATR)": round((R_ - S_) / a, 1),
                        "现价位置%": round(pos) if pos is not None else None, "离上沿%": round((R_ / p - 1) * 100, 2), "离下沿%": round((S_ / p - 1) * 100, 2)}
    elif last:
        R_, S_ = last[2], last[3]
        out["日线箱体"] = {"状态": "已离箱(趋势段)", "最近箱体": f"{d[last[0]]}~{d[last[1]]} 上沿 {R_:.3f} 下沿 {S_:.3f}", "方向": "向上" if p > R_ else "向下" if p < S_ else "回到箱内"}
    else:
        out["日线箱体"] = "近 160 天没有成形的箱体"
    zz = zigzag(h[-60:], l_[-60:], 1.5 * a)
    H = [x[1] for x in zz if x[2] == "H"][-3:]
    L = [x[1] for x in zz if x[2] == "L"][-3:]
    if len(H) >= 2 and len(L) >= 2:
        up, dn = H[-1] > H[-2] and L[-1] > L[-2], H[-1] < H[-2] and L[-1] < L[-2]
        out["近60日结构"] = ("高点低点都抬高(上升)" if up else "高点低点都降低(下降)" if dn else "高低点交错(震荡)") + f"; 最近高点 {H[-1]:.2f} 低点 {L[-1]:.2f}(按 1.5 ATR 分段)"
    M = m15(code, D, at=at)
    if M:
        t, o2, h2, l2, c2 = M
        pc2 = np.concatenate([[o2[0]], c2[:-1]])
        a2 = atr14(h2, l2, c2, pc2)
        bx2 = seg_boxes(o2, h2, l2, c2, a2)
        if bx2 and bx2[-1][1] >= len(c2) - 3:
            R2, S2 = bx2[-1][2], bx2[-1][3]
            out["15分钟箱体"] = {"上沿": round(R2, 3), "下沿": round(S2, 3), "起": t[bx2[-1][0]], "根数": bx2[-1][1] - bx2[-1][0] + 1,
                              "现价位置%": round((p - S2) / (R2 - S2) * 100) if R2 > S2 else None}
        elif bx2:
            out["15分钟箱体"] = f"已离箱; 最近一个 {t[bx2[-1][0]]}~{t[bx2[-1][1]]} 上沿 {bx2[-1][2]:.3f} 下沿 {bx2[-1][3]:.3f}"
        else:
            out["15分钟箱体"] = "近 5 日没有成形的箱体"
    else:
        out["15分钟箱体"] = "没有分钟线(不在采集名单)"
    return out


def line(code, D, px=None, at=None):
    """必查一行"""
    s = struct(code, D, px, at)
    if s.get("err"):
        return s["err"]
    b = s.get("日线箱体")
    note = ""
    if isinstance(b, dict) and b.get("现价位置%") is not None and not (0 <= b["现价位置%"] <= 100):
        note = "(已越过" + ("上沿" if b["现价位置%"] > 100 else "下沿") + ", 还没满 3 根收盘确认离箱)"
    bt = (f"日线箱体 {b['下沿']}~{b['上沿']}({b['起']} 起 {b['天数']} 天, 宽 {b['宽(ATR)']} ATR), 现价在 {b['现价位置%']}% 位置{note}" if isinstance(b, dict) and "上沿" in b
          else f"日线{b['状态']} {b['方向']}({b['最近箱体']})" if isinstance(b, dict) else str(b))
    m = s.get("15分钟箱体")
    mt = (f"15 分钟箱体 {m['下沿']}~{m['上沿']}(现价 {m['现价位置%']}%)" if isinstance(m, dict) else f"15 分钟: {m}")
    return f"{bt}; {mt}; ATR14 {s['ATR14']}({s['ATR%']}%); {s.get('近60日结构', '')}"


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(struct(sys.argv[1], sys.argv[2]))
    print(line(sys.argv[1], sys.argv[2]))
