# -*- coding: utf-8 -*-
"""theme_phase.py — 题材阶段(10/27 晚用户令重写: 只比一天作废, 改成 近 3 天趋势 + 相对峰值 + 梯队完整度 + 晋级率; 零 token)

为什么改: 老的 theme_life.life 只拿最近两个出现日比家数 / 最高板, 用户 10/27 说"3 种不够多, 分歧/退潮/退潮后回流/高潮 n 日 都分不出来"。
新口径只算四个连续量, 标签是展示层, 判断必须引数字(不引标签):
  ① 近 3 天趋势: 本波最近 3 个出现日的涨停家数 t3 = [n-2, n-1, n] 的斜率(线性回归斜率, 按家数/日), 以及最近 3 个自然交易日(含没出现的日子)的家数序列
  ② 相对峰值: 今天家数 / 本波峰值(0~1); 以及离峰值几天
  ③ 梯队完整度: 本波最高板 down 到 1 板, 有票的档数 / 应有档数(如最高 5 板 → 5 档, 实际有 5/4/2/1 = 4 档 → 0.8); 以及"最高板是否还在今天出现"
  ④ 晋级率: 该题材 T−1 涨停的票今天连板的比例(和全市场晋级率对比)
标签(5 个, 全部带机械条件, 条件之间互斥, 按顺序判):
  断档      最近 2 个交易日没出现
  首日      本波只有 1 个出现日
  发酵      家数 3 日斜率 > 0 且 相对峰值 ≥ 0.8
  高潮      相对峰值 ≥ 0.95 且 家数 ≥ 本段(近 60 日)分位 P75 且 晋级率 ≥ 本段 P50
  分歧      家数 3 日斜率 ≤ 0 但 梯队完整度 ≥ 0.6 或 晋级率 ≥ 本段 P50(家数退、高度/接力没退 → 同概念内竞争连板、连板转趋势、高位转低位)
  退潮      家数 3 日斜率 < 0 且 相对峰值 ≤ 0.6 且 梯队完整度 < 0.6 且 晋级率 < 本段 P50
  退潮后回流 之前判过退潮、今天家数回升 ≥ 1.5 倍 且 梯队重建(完整度 ≥ 上次)
不自信点: 阈值全部改成「本题材自己 < D 的历史分位」(相对峰值 P33/P50/P85、家数 P75、晋级率 P50、梯队完整度 P50), 不再有固定常数, 但分位档位本身是选的; 梯队完整度把"1 板"算进应有档, 只看日 K 封板
"""
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "paper_line" / "tools"))
import theme_life as TL  # noqa: E402


def _q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))] if xs else None


def _slope(ys):
    n = len(ys)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0


def _rows():
    if not hasattr(_rows, "c"):
        _rows.c = TL.rows_canon()
    return _rows.c


def phase(theme, D):
    rows = [r for r in _rows() if r[1] == theme and r[0] <= D]
    if not rows:
        return {"题材": theme, "D": D, "标签": "无数据"}
    days = sorted({r[0] for r in _rows() if r[0] <= D})
    cnt, top = defaultdict(int), defaultdict(int)
    seal = defaultdict(set)
    for r in rows:
        if r[0] in days and r[5]:
            cnt[r[0]] += 1
            top[r[0]] = max(top[r[0]], r[4] or 1)
            seal[r[0]].add((r[3] or r[2], r[4] or 1))
    on = [i for i, d in enumerate(days) if cnt[d] > 0]
    if not on:
        return {"题材": theme, "D": D, "标签": "从未出现"}
    j = len(on) - 1
    while j > 0 and on[j] - on[j - 1] <= 3:   # 同 theme_life: 断档 ≤2 个交易日算同一波
        j -= 1
    wave_days = [days[i] for i in on[j:]]
    gap = len(days) - 1 - on[-1]
    seq3 = [cnt[d] for d in wave_days[-3:]]
    peak = max(cnt[d] for d in wave_days)
    peak_day = max(wave_days, key=lambda d: cnt[d])
    rel = cnt[D] / peak if peak else 0
    # ③ 梯队完整度
    hi = top[D] if cnt[D] else 0
    have = len({b for _, b in seal[D]})
    ladder = (have / hi) if hi else 0.0
    # ④ 晋级率: 该题材 T−1 涨停的票今天连板(≥2 板)的比例
    prev_d = [d for d in days if d < D][-1] if [d for d in days if d < D] else None
    y_seal = seal.get(prev_d) or set()
    if y_seal:
        promoted = {c for c, b in seal[D] if b >= 2} & {c for c, _ in y_seal}
        promo = len(promoted) / len(y_seal)
    else:
        promo = None
    hist = [cnt[d] for d in days[-60:] if cnt[d] > 0]
    p75 = _q(hist, .75)
    # 10/27 晚用户"禁止拍脑袋, 多用动态参数": 阈值不用固定常数, 取本题材自己的历史分位(只用 < D 的日子)
    rels, lads = [], []
    for d in [x for x in days if x < D and cnt[x] > 0]:
        i_ = days.index(d)
        jj = i_
        while jj > 0 and cnt[days[jj - 1]] > 0 and all(cnt[days[k]] > 0 for k in range(max(0, jj - 3), jj)):
            jj -= 1
        wdays = days[jj:i_ + 1]
        pk = max(cnt[k] for k in wdays)
        if pk:
            rels.append(cnt[d] / pk)
        hh = top[d]
        lads.append(len({b for _, b in seal[d]}) / hh if hh else 0.0)
    rel_p33, rel_p50, rel_p85 = _q(rels, .33), _q(rels, .50), _q(rels, .85)
    lad_p50 = _q(lads, .50)
    proms = []
    for d in days[-60:]:
        dv = [x for x in days if x < d]
        if not dv:
            continue
        ys = seal.get(dv[-1]) or set()
        if ys:
            proms.append(len({c for c, b in seal[d] if b >= 2} & {c for c, _ in ys}) / len(ys))
    p50p = _q(proms, .50)
    sl = _slope(seq3)
    if gap >= 2:
        lab = f"断档(最近 {gap} 个交易日没出现)"
    elif cnt[D] == 0:
        lab = f"今天没出现(距上次 {gap + 1} 个交易日)"
    elif len(wave_days) == 1 and wave_days[0] == D:
        lab = "首日"
    elif rel_p85 is not None and rel >= rel_p85 and p75 is not None and cnt[D] >= p75 and (promo or 0) >= (p50p or 0):
        lab = "高潮" if len(wave_days) <= 3 else f"高潮第 {len(wave_days)} 天"
    elif sl < 0 and rel_p33 is not None and rel <= rel_p33 and promo is not None and promo < (p50p or 0):
        lab = "疑似退潮"
    elif sl > 0 and rel_p50 is not None and rel >= rel_p50:
        lab = "发酵(N 日新高)" if len(wave_days) >= 3 else "发酵"
    elif sl <= 0 and (lad_p50 is None or ladder >= lad_p50 or (promo is not None and promo >= (p50p or 0))):
        lab = "分歧"
    elif sl <= 0:
        lab = "退潮(家数和高度都降)"
    else:
        lab = "弱发酵"
    return {"题材": theme, "D": D, "标签": lab, "本波第几天": len(wave_days), "本波起点": wave_days[0],
            "近3个出现日家数": seq3, "3日斜率": round(sl, 2), "今天家数": cnt[D], "本波峰值": peak, "峰值日": peak_day,
            "相对峰值": round(rel, 2), "离峰天数": len([d for d in wave_days if d > peak_day]),
            "梯队完整度": round(ladder, 2), "今天封板档位": sorted({b for _, b in seal[D]}, reverse=True), "最高板": hi,
            "晋级率": None if promo is None else round(promo, 2), "本段晋级率P50": p50p, "本段家数P75": p75,
            "本题材相对峰值P33/P50/P85": [rel_p33, rel_p50, rel_p85], "本题材梯队完整度P50": lad_p50,
            "不自信点": "阈值(0.8/0.95/0.6/P75)是按历史分位定的初值, 未做样本外; 梯队完整度把 1 板算进应有档"}


def block(themes, D):
    L = [f"## 题材阶段(新口径: 3 日趋势 + 相对峰值 + 梯队完整度 + 晋级率; 标签只是展示, 判断要引数字) {D}"]
    for th in themes:
        p = phase(th, D)
        if p.get("标签") in ("无数据", "从未出现", None):
            L.append(f"- **{th}**: 无数据")
            continue
        L.append(f"- **{th}**: {p['标签']} · 今天 {p['今天家数']} 家 / 峰值 {p['本波峰值']}({p['峰值日'][5:]}, 相对 {p['相对峰值']:.0%}) · 近 3 个出现日 {p['近3个出现日家数']} 斜率 {p['3日斜率']:+.1f}"
                 f" · 梯队 {p['今天封板档位']} 完整度 {p['梯队完整度']:.0%} · 晋级率 {('%.0f%%' % (p['晋级率'] * 100)) if p['晋级率'] is not None else '—'}(本段 P50 {(('%.0f%%' % (p['本段晋级率P50'] * 100)) if p['本段晋级率P50'] is not None else '—')})")
    return "\n".join(L)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ths = sys.argv[1].split(",") if len(sys.argv) > 1 else ["机器人", "商业零售", "食品饮料"]
    D = sys.argv[2] if len(sys.argv) > 2 else "2026-10-27"
    print(block(ths, D))
