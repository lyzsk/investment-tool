# -*- coding: utf-8 -*-
"""open_bins.py — 开盘档 13 档(10/26 用户定; 规则体检 rule_exam 的 M2 基线和 B 默认动作表共用这一份, 改档位只改这里)

档位(主板口径, 涨跌幅 %): 涨停 / >8 / 6~8 / 4~6 / 2~4 / 0~2 / 平 / 0~−2 / −2~−4 / −4~−6 / −6~−8 / <−8 / 跌停
  · 写法照 scripts/market/similar_days.py 的 b13(stk_prev 13 档): 档距按 lim/10 缩放 → 创业板 / 科创板(±20%)、北交所(±30%)、转债(±20%)按比例换算;
    涨停 / 跌停 = 距涨跌停 0.2 个档距以内(同 b13)
  · 和 b13 的唯一差别: 用户列的 13 档里有「平」, b13 没有(b13 实际是 12 个标签: 0~2 含 0, −2~0)。这里「平」= |涨跌| < 0.2 个档距(主板 ±0.2%),
    0~2 / 0~−2 只收「平」以外的部分。【不自信: 「平」的宽度是我定的, b13 没有可抄的】
  · 档名一律用主板口径(创业板开 +13% 记「6~8」), 这样不同板的票能进同一格
查表: lookup(tab, key, base) — 格内样本 <3 → 依次并上相邻 1 档、2 档 ... 直到 ≥3, 都不够 → base(默认动作)
"""
from collections import Counter

ORDER = ["跌停", "<−8", "−8~−6", "−6~−4", "−4~−2", "−2~0", "平", "0~2", "2~4", "4~6", "6~8", ">8", "涨停"]
MIN_N = 3


def lim_of(code, kind=None):
    """涨跌停幅度(%): 主板 10 / 创业板·科创板 20 / 北交所 30 / 转债 20; ETF 按 10"""
    c = str(code or "")
    c = c[2:] if c[:2] in ("sh", "sz", "bj") else c
    if kind == "cb" or c.startswith(("11", "12")):   # 转债: 沪 110/111/113/118, 深 123/127/128(A 股没有 11 / 12 开头的股票)
        return 20
    if c.startswith(("300", "301", "688", "689")):
        return 20
    if c.startswith(("8", "4", "92")):
        return 30
    return 10


def bin13(p, lim=10):
    """p = 涨跌幅(%), lim = 涨跌停幅度(%); 返回 ORDER 里的档名(主板口径)"""
    if p is None:
        return None
    u = lim / 10
    if p >= lim - 0.2 * u:
        return "涨停"
    if p <= -lim + 0.2 * u:
        return "跌停"
    if abs(p) < 0.2 * u:
        return "平"
    for e, nm in ((8, ">8"), (6, "6~8"), (4, "4~6"), (2, "2~4"), (0, "0~2")):
        if p >= e * u:
            return nm
    for e, nm in ((-2, "−2~0"), (-4, "−4~−2"), (-6, "−6~−4"), (-8, "−8~−6")):
        if p >= e * u:
            return nm
    return "<−8"


def bin13_frac(x, code=None, kind=None):
    """x = 小数口径的涨跌(0.05 = +5%)"""
    return None if x is None else bin13(x * 100, lim_of(code, kind))


def fit(pairs):
    """pairs = [(档名, 标签)] → {档名: Counter}"""
    tab = {}
    for k, y in pairs:
        tab.setdefault(k, Counter())[y] += 1
    return tab


def lookup(tab, key, base):
    """格内 n<3 → 并相邻档(±1, ±2, ...)直到 n≥3; 都不够 → base"""
    if key not in ORDER:
        c = tab.get(key)
        return c.most_common(1)[0][0] if c and sum(c.values()) >= MIN_N else base
    i = ORDER.index(key)
    for w in range(0, len(ORDER)):
        c = Counter()
        for j in range(max(0, i - w), min(len(ORDER), i + w + 1)):
            c.update(tab.get(ORDER[j], Counter()))
        if sum(c.values()) >= MIN_N:
            return c.most_common(1)[0][0]
    return base
