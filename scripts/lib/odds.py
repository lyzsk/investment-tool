# -*- coding: utf-8 -*-
"""odds.py — 赔率思维的机械层(10/21 用户: 概率 × 赔率不对称时低概率也值得; 零 token)
输入一组同类历史样本的收益(%, 按"这样做比不做多赚多少"算), 输出 胜率 / 平均赚 / 平均亏 / 盈亏比 / 期望 / 1/4 凯利仓位 / 判定。
谁用: lesson_replay(教训预演结论) · 给单 / 判断回复("尾盘接、次日冲高"这类先按用户口径取样本再算) · 执行器选止损方式
判定: 期望 > 成本(默认 0.1%, 含手续费滑点) 且 样本 ≥ 15 → "值得"; 胜率低但盈亏比 ≥ 2 且期望为正 → "低概率高赔率, 值得小仓"; 期望 ≤ 成本 → "不值得"
"""
import statistics as st


def odds(xs, cost=0.1, min_n=15):
    xs = [float(x) for x in xs if x is not None]
    if not xs:
        return {"n": 0, "verdict": "无样本"}
    w = [x for x in xs if x > 0]
    l = [-x for x in xs if x < 0]
    p = len(w) / len(xs)
    aw, al = (st.mean(w) if w else 0.0), (st.mean(l) if l else 0.0)
    b = aw / al if al else float("inf")
    ev = st.mean(xs)
    kelly = (p - (1 - p) / b) if b not in (0, float("inf")) else (1.0 if ev > 0 else 0.0)
    if len(xs) < min_n:
        v = f"样本不足({len(xs)}<{min_n}), 只作参考"
    elif ev <= cost:
        v = "不值得(期望不超过成本)"
    elif p < 0.5 and b >= 2:
        v = "低概率高赔率, 值得小仓"
    else:
        v = "值得"
    return {"n": len(xs), "p_win": round(p, 3), "avg_win": round(aw, 3), "avg_loss": round(al, 3), "payoff": round(b, 2) if b != float("inf") else None,
            "ev": round(ev, 3), "median": round(st.median(xs), 3), "kelly_q": round(max(0.0, kelly) / 4, 3), "verdict": v}


if __name__ == "__main__":
    r = odds([1.31, 3.29, 1.26, -1.42, -0.02, 2.54, 2.7, -0.59])
    assert r["n"] == 8 and 0 < r["p_win"] < 1 and "样本不足" in r["verdict"], r
    r = odds([-1] * 70 + [3] * 30)   # 胜率 30%、盈亏比 3 → 期望 +0.2%
    assert r["verdict"] == "低概率高赔率, 值得小仓" and abs(r["ev"] - 0.2) < 1e-9, r
    r = odds([0.5] * 60 + [-1] * 40)   # 胜率 60% 但期望 −0.1%
    assert r["verdict"].startswith("不值得"), r
    print("SELFTEST PASS")


# ================= 概率与置信度(10/21 用户立法: 两者都用百分比, 且是两件事) =================
# 概率 p    = 事件发生的可能性, 从同口径历史样本频率算, 向"更大参照组"的基准率收缩(样本越少收得越多)
# 置信度 c  = 我对 p 这个估计本身有多可靠: 样本够不够 × 当前和样本像不像 × 样本新不新 × 前后两半稳不稳
def prob(k, n, p0=None, a=10):
    """收缩频率: p = (k + a·p0) / (n + a); p0 = 参照组基准率(同类票 / 全市场同形态), 没有就不收缩。
    返回 (p, 90% 区间低, 高) —— 区间用 Beta(k + a·p0 + 1, n − k + a·(1−p0) + 1) 的分位数"""
    if n <= 0 and p0 is None:
        return None, None, None
    if p0 is None:
        a, p0 = 0, 0.5
    al, be = k + a * p0 + 1, (n - k) + a * (1 - p0) + 1
    p = (k + a * p0) / (n + a) if n + a else p0
    try:
        from scipy.stats import beta as B   # noqa: PLC0415
        lo, hi = B.ppf(0.05, al, be), B.ppf(0.95, al, be)
    except Exception:   # noqa: BLE001  无 scipy: 正态近似
        m, v = al / (al + be), al * be / ((al + be) ** 2 * (al + be + 1))
        lo, hi = max(0.0, m - 1.645 * v ** 0.5), min(1.0, m + 1.645 * v ** 0.5)
    return round(p, 3), round(lo, 3), round(hi, 3)


def confidence(n, sim, recent=1.0, halves=None, n0=20):
    """置信度百分比 = 100 × 样本分 × 相似分 × 时效分 × 稳定分
    样本分 = n / (n + n0)(n0=20: 20 个样本时 50%)
    相似分 = 当前情形和样本条件逐项对照(位置 / 市况 / 形态 / 板块身份 / 量能 …)符合的比例, 0~1, 由分析时列清单打分
    时效分 = 0.5 + 0.5 × 近 12 个月样本占比(全是老样本最多打 5 折)
    稳定分 = 1 − |前半样本概率 − 后半样本概率|(halves=(p前, p后); 规律前后变了就打折)
    档位: ≥70% 高 / 40~70% 中 / <40% 低"""
    f_n = n / (n + n0) if n > 0 else 0.0
    f_t = 0.5 + 0.5 * max(0.0, min(1.0, recent))
    f_s = 1 - abs(halves[0] - halves[1]) if halves else 1.0
    c = 100 * f_n * max(0.0, min(1.0, sim)) * f_t * max(0.0, f_s)
    return {"conf": round(c), "level": "高" if c >= 70 else "中" if c >= 40 else "低",
            "parts": {"样本": round(f_n, 2), "相似": round(sim, 2), "时效": round(f_t, 2), "稳定": round(f_s, 2)}}


def _selftest_conf():
    p, lo, hi = prob(27, 49)
    assert abs(p - 27 / 49) < 1e-3 and lo < p < hi
    p2, _, _ = prob(3, 4, p0=0.4)   # 样本少 → 被拉向基准率
    assert 0.4 < p2 < 0.75, p2
    c = confidence(49, 0.5, recent=0.4, halves=(0.6, 0.5))
    assert c["level"] == "低" and 0 < c["conf"] < 40, c
    c = confidence(200, 1.0, recent=1.0, halves=(0.55, 0.55))
    assert c["level"] == "高", c
    print("CONF SELFTEST PASS")


if __name__ == "__main__":
    _selftest_conf()
