# -*- coding: utf-8 -*-
"""fill_prob.py — 挂单"今天触及概率"(10/23 01:4x 用户批: 模型爱挂够不着的价, 理由里从不算能不能成交 → 给一个客观数, 不让模型主观估)

只用历史分布 + 此刻盘面, 不调模型, 毫秒级; 用"相对昨收的百分比"(振幅口径), 不用绝对价格 —— 不同价位、不同票可比
三个口径(都给, 不合成一个数):
  ①开盘前口径 = 近 N 日(5 / 15)里, 当日最低(买)/ 最高(卖)相对昨收 达到这个幅度的天数占比
  ②此刻口径(用价格位置) = 今天已经走出的最低 L0 / 最高 H0 之后还要再走多远: P(最低 ≤ x | 最低 ≤ L0) = P(最低 ≤ x) / P(最低 ≤ L0)(盘中越晚越高估, 尾盘要打折)
  ③此刻口径(用振幅) = 今天已出的最高 H0 往下, 一天振幅能不能覆盖到这个价: P(日振幅 ≥ (H0 − 挂价) / 昨收)(卖单对称用 L0); 振幅大的票高开后也能跌到
样本: 行情库日线, 只用 D 之前的数据; 不足 5 天给不出
用法: python fill_prob.py 601988 2026-10-23 BUY 7.12 [--lo 7.16 --hi 7.25]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
_K = {}


def hist(code, D, n=15):
    if (code, D) not in _K:
        import manual_backfill as mb
        cur = mb.db().cursor()
        cur.execute("use investment_market")
        sym = ("sh" if code.startswith(("6", "5", "11")) else "sz") + code
        cur.execute("select high, low, pre_close, close from kline_day where is_deleted=0 and symbol=%s and trade_date < %s order by trade_date desc limit %s", (sym, D, n))
        rows = [(float(h), float(l), float(pc), float(c)) for h, l, pc, c in cur.fetchall() if h and l and pc and c]
        _K[(code, D)] = rows   # 新在前
    return _K[(code, D)]


def prob(code, D, side, px, lo=None, hi=None):
    """→ {"prev": 昨收, "need": 相对昨收 %, "p5": , "p15": , "now_px": , "now_amp": , "touched": bool}"""
    R = hist(code, D)
    if len(R) < 5:
        return {"err": "日线不足 5 天"}
    pc = R[0][3]   # 昨收 = 前一交易日收盘
    x = px / pc - 1
    buy = str(side).upper() == "BUY"
    lows = [l / p - 1 for h, l, p, c in R]
    highs = [h / p - 1 for h, l, p, c in R]
    amps = [(h - l) / p for h, l, p, c in R]

    def frac(xs):
        return sum(1 for v in xs if (v <= x + 1e-9 if buy else v >= x - 1e-9)) / len(xs)
    out = {"prev": pc, "need": round(x * 100, 2), "p5": frac((lows if buy else highs)[:5]), "p15": frac(lows if buy else highs)}
    if buy and lo is not None and lo <= px or (not buy and hi is not None and hi >= px):
        out["touched"] = True
        return out
    ref = lo if buy else hi
    if ref is not None:
        r0 = ref / pc - 1
        base = [v for v in (lows if buy else highs) if (v <= r0 + 1e-9 if buy else v >= r0 - 1e-9)]
        hit = [v for v in base if (v <= x + 1e-9 if buy else v >= x - 1e-9)]
        out["now_px"] = len(hit) / len(base) if base else None
    far = (hi if buy else lo)
    if far is not None:
        need = (far - px) / pc if buy else (px - far) / pc
        out["now_amp"] = sum(1 for a in amps if a >= need) / len(amps)
    return out


def fmt(r):
    if r.get("err"):
        return r["err"]
    if r.get("touched"):
        return "今天已经到过这个价"
    s = f"需走到昨收 {r['need']:+.2f}%: 近 5 日 {r['p5']:.0%} / 近 15 日 {r['p15']:.0%} 的天数到过"
    if r.get("now_px") is not None:
        s += f"; 按今天已走出的高低点 {r['now_px']:.0%}"
    if r.get("now_amp") is not None:
        s += f"; 按振幅 {r['now_amp']:.0%}"
    return s


def ladder(code, D, ref_px, lo=None, hi=None, steps=(0.5, 1, 1.5, 2, 3, 5)):
    """一只票的"挂在这里今天能不能成交"价梯(相对 ref_px ± 档), 给 06 挑价用; 每格 = 近 15 日口径 / 此刻口径(盘中有今天高低点才有)"""
    R = hist(code, D)
    if len(R) < 5 or not ref_px:
        return ""
    cells = []
    for side, sg in (("买", -1), ("卖", 1)):
        for st in steps:
            px = ref_px * (1 + sg * st / 100)
            r = prob(code, D, "BUY" if sg < 0 else "SELL", px, lo, hi)
            if r.get("err"):
                continue
            if r.get("touched"):
                v = "已到"
            else:
                v = f"{r['p15']:.0%}" + (f"/此刻{r['now_px']:.0%}" if r.get("now_px") is not None else "")
            cells.append(f"{side}{'−' if sg < 0 else '+'}{st}%→{v}")
    return " · ".join(cells)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("date")
    ap.add_argument("side")
    ap.add_argument("px", type=float)
    ap.add_argument("--lo", type=float)
    ap.add_argument("--hi", type=float)
    a = ap.parse_args()
    r = prob(a.code, a.date, a.side, a.px, a.lo, a.hi)
    print(json.dumps(r, ensure_ascii=False), "|", fmt(r))


if __name__ == "__main__":
    main()
