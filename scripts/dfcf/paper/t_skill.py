# -*- coding: utf-8 -*-
"""t_skill.py — 品种 skill 的机械数据画像(零 token; 10/18 用户定: 银行 / 纳指 做 T 沉淀成两个独立 skill 方便进化)

skill: skills/bank-skill(银行股 skill, 现标的 中国银行 601988) / skills/nasdaq-skill(纳指 skill, 现标的 纳指ETF 广发 159941)
本脚本只重写各 skill persona/profile.md 里 <!-- AUTO:数据画像 --> ... <!-- /AUTO --> 之间的内容, 其余手写 / 蒸馏内容不动。
算什么(日线 kline_day, 收益一律 close/pre_close 链乘 = 已含分红除权):
  ① 振幅分布: 近 30 / 120 / 250 日 最高涨幅中位、最大跌幅中位、日内高低区间中位
  ② 机械 T 回测近似(不偷看未来: 每天用"之前 30 日"中位数挂高抛 / 低吸): 两腿都成交的天数占比、单腿成交占比、两腿都成交时的价差扣费
     (日线看不到高低点先后, 两腿都成交 = T 做成的上限近似)
  ③ 开盘缺口 vs 日内: 高开 / 低开后日内(收/开)延续还是回补 —— 决定开盘先卖还是先买
  ④ 银行专有: 护盘检验 = 上证大跌日(≤-1.5% / ≤-2.5%)本品种当天收益 vs 上证; 熊市段(上证区间回撤最深的几段)本品种同段收益
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/t_skill.py [--date D]
"""
import argparse
import datetime as dt
import re
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "quotes"))

LEG = 10000 * 0.5 / 3   # 10/18 晚: 用户 1 万做 T、底仓 50%、1/3 档一笔约 1667 元; 券商每笔最低 5 元(不免五)
SKILLS = {"bank": {"symbol": "sh601988", "name": "中国银行", "fee": 0.0005 + 5 * 2 / LEG, "bank": True},   # 印花税 + 双边佣金(万2 估) + 过户
          "nasdaq": {"symbol": "sz159941", "name": "纳指ETF(广发)", "fee": 5 * 2 / LEG, "bank": False},
          # 10/18 晚: 用户实盘持仓牧原(私有 skill 在 snapshots/; 用户规模下一笔 T 约 100~300 股 ≈ 1 万元, 费用按每笔 5 元 + 卖出印花税估)
          "muyuan": {"symbol": "sz002714", "name": "牧原股份", "fee": 0.0005 + 5 * 2 / 8000, "bank": False,
                     "dir": ROOT / "scripts" / "dfcf" / "snapshots" / "muyuan-skill"}}
INDEX = "sh000001"
MARK0, MARK1 = "<!-- AUTO:数据画像 -->", "<!-- /AUTO -->"


def load(sym, D):
    from kline_db import db
    c = db()
    try:
        cur = c.cursor()
        cur.execute("select trade_date, cast(open as double), cast(high as double), cast(low as double), cast(close as double), cast(pre_close as double) "
                    "from kline_day where symbol=%s and is_deleted=0 and trade_date<%s order by trade_date", (sym, D))
        return [r for r in cur.fetchall() if r[5]]
    finally:
        c.close()


def med(xs):
    xs = list(xs)
    return st.median(xs) if xs else 0.0


def pct(x):
    return f"{x * 100:+.2f}%"


def amp_block(K):
    out = ["**① 振幅分布(相对昨收)**", "", "| 窗口 | 最高涨幅中位 | 最大跌幅中位 | 日内高低区间中位 | 收盘涨跌绝对值中位 |", "|---|---|---|---|---|"]
    for n in (30, 120, 250):
        R = K[-n:]
        out.append(f"| 近 {n} 日 | {pct(med(r[2] / r[5] - 1 for r in R))} | {pct(-med(1 - r[3] / r[5] for r in R))} | "
                   f"{med((r[2] - r[3]) / r[5] for r in R) * 100:.2f}% | {med(abs(r[4] / r[5] - 1) for r in R) * 100:.2f}% |")
    return out


def mech_block(K, fee):
    rows = []
    for i in range(30, len(K)):
        W = K[i - 30:i]
        up, dn = med(r[2] / r[5] - 1 for r in W), med(1 - r[3] / r[5] for r in W)
        r = K[i]
        hs, hb = r[2] >= r[5] * (1 + up), r[3] <= r[5] * (1 - dn)
        rows.append((r[0], hs, hb, (1 + up) / (1 - dn) - 1 - fee))
    out = ["**② 机械 T 回测近似(每天用之前 30 日中位挂高抛 / 低吸; 日线看不出先后, 两腿都成交 = 上限)**", "",
           "| 区间 | 天数 | 两腿都成交 | 只成交高抛 | 只成交低吸 | 都没成交 | 两腿成交时价差(扣 1 万规模 1/3 档真实费用)中位 |", "|---|---|---|---|---|---|---|"]
    for lab, R in (("近 60 日", rows[-60:]), ("近 250 日", rows[-250:]), ("全部(2018-07 起)", rows)):
        n = len(R) or 1
        both = [x for x in R if x[1] and x[2]]
        out.append(f"| {lab} | {len(R)} | {len(both) / n:.0%} | {sum(1 for x in R if x[1] and not x[2]) / n:.0%} | {sum(1 for x in R if x[2] and not x[1]) / n:.0%} | "
                   f"{sum(1 for x in R if not x[1] and not x[2]) / n:.0%} | {pct(med(x[3] for x in both))} |")
    out += ["", "读法: 只成交一腿的天 = 收盘被迫收口(卖了买回 / 买了留隔夜), 这部分是机械 T 的主要亏损来源; 决策 T 要赢机械 T, 就要在开盘判断今天更可能走哪一腿。"]
    return out


def gap_block(K):
    out = ["**③ 开盘缺口 vs 日内(近 250 日; 日内 = 收/开 − 1)**", "", "| 开盘 | 天数 | 日内收益中位 | 日内收涨占比 | 当天最高再涨(相对开盘)中位 | 当天最低再跌中位 |", "|---|---|---|---|---|---|"]
    R = K[-250:]
    for lab, f in (("高开 ≥ +0.5%", lambda g: g >= 0.005), ("平开 ±0.5%", lambda g: abs(g) < 0.005), ("低开 ≤ −0.5%", lambda g: g <= -0.005)):
        S = [r for r in R if f(r[1] / r[5] - 1)]
        if not S:
            continue
        out.append(f"| {lab} | {len(S)} | {pct(med(r[4] / r[1] - 1 for r in S))} | {sum(1 for r in S if r[4] > r[1]) / len(S):.0%} | "
                   f"{pct(med(r[2] / r[1] - 1 for r in S))} | {pct(-med(1 - r[3] / r[1] for r in S))} |")
    return out


def guard_block(K, I):
    ix = {r[0]: r[4] / r[5] - 1 for r in I}
    me = {r[0]: r[4] / r[5] - 1 for r in K}
    out = ["**④ 护盘检验(上证大跌日本品种表现; 收益含分红)**", "", "| 上证当天 | 天数 | 本品种当天收益中位 | 本品种跑赢上证占比 | 本品种当天收涨占比 |", "|---|---|---|---|---|"]
    for lab, th in (("≤ −1.5%", -0.015), ("≤ −2.5%", -0.025)):
        S = [(ix[d], me[d]) for d in ix if d in me and ix[d] <= th]
        if S:
            out.append(f"| {lab} | {len(S)} | {pct(med(b for _, b in S))} | {sum(1 for a, b in S if b > a) / len(S):.0%} | {sum(1 for _, b in S if b > 0) / len(S):.0%} |")
    # 熊市段: 上证回撤段(前高 → 创新高前的最低点), 取最深 3 段, 同段本品种链乘收益
    ds = [r[0] for r in I if r[0] in me]
    curve, v = [], 1.0
    for d in ds:
        v *= 1 + ix[d]
        curve.append(v)
    eps, pk, tr = [], 0, 0
    for j in range(1, len(curve) + 1):
        if j == len(curve) or curve[j] > curve[pk]:
            if tr > pk:
                eps.append((curve[tr] / curve[pk] - 1, pk, tr))
            if j < len(curve):
                pk = tr = j
        elif curve[j] < curve[tr]:
            tr = j
    segs = []
    for dd, a0, b0 in sorted(eps)[:3]:
        if dd > -0.1:
            break
        mine = 1.0
        for k in range(a0 + 1, b0 + 1):
            mine *= 1 + me[ds[k]]
        segs.append((ds[a0], ds[b0], dd, mine - 1))
    if segs:
        out += ["", "| 上证熊市段(前高→低点) | 上证 | 本品种同段(含分红) |", "|---|---|---|"]
        for a, b, x, y in sorted(segs):
            out.append(f"| {a} → {b} | {pct(x)} | {pct(y)} |")
    out += ["", "读法: '护盘' 的可检验后果 = 大跌日跌得比指数少、熊市段回撤明显小于指数; 不等于不跌。"]
    return out


def regime_block(sym, D):
    """⑤ 均线与三态(indicators_db.py 同口径): 用户判断牧原看 MA120 / MA144; 决策 T 按状态选打法(区间做高抛低吸, 趋势别逆着 T)"""
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
        import indicators_db as ID
        rows = ID.snapshot(D, codes=[sym[2:]])
    except Exception as e:   # noqa: BLE001
        return [f"**⑤ 均线与三态**: 计算失败 {e}"]
    if not rows:
        return ["**⑤ 均线与三态**: 当日无数据"]
    x = rows[0]
    ema = " / ".join(f"EMA{n} {x[f'ema{n}']}" for n in (20, 60, 120, 144, 169, 388))
    ma = " / ".join(f"MA{n} {x[f'ma{n}']}" for n in (5, 20, 60, 120, 144, 250) if x.get(f"ma{n}"))
    box = f"箱体(20 日收盘) {x.get('box_lo')}~{x.get('box_hi')}, 现在位置 {x.get('box_pos')}" if x.get("box_lo") else "箱体: —"
    stops = " / ".join(f"{k} {v}" for k, v in (x.get("stops") or {}).items())
    return [f"**⑤ 均线与三态(截至 {x['date']} 收盘 {x['close']})**", "",
            f"- 状态: **{x['regime']}**(ER20 {x['er20']}; ATR14 约 {x['atr14_pct'] * 100:.1f}%) · 相对 EMA144 {x['vs_ema144'] * 100:+.1f}% / EMA169 {x['vs_ema169'] * 100:+.1f}%",
            f"- {ema}", f"- {ma}", f"- {box}", f"- 止损候选: {stops or '—'}",
            "- 读法: 交易区间 → 箱体下沿附近吸、上沿附近抛; 上涨趋势 → 别做先卖后买(反 T)卖飞; 下跌趋势 → 别连续接回; 无规则 → 降档或观望。三态全市场自检显示\"趋势标签本身不是优势\", 只当情景参考"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    I = load(INDEX, a.date)
    for sk, cfg in SKILLS.items():
        K = load(cfg["symbol"], a.date)
        L = [MARK0, f"_(t_skill.py 机械生成, 数据截至 {K[-1][0]}, 每晚 check md 重算; 标的 {cfg['name']} {cfg['symbol']})_", ""]
        L += amp_block(K) + [""] + mech_block(K, cfg["fee"]) + [""] + gap_block(K) + [""]
        if cfg["bank"]:
            L += guard_block(K, I) + [""]
        L += regime_block(cfg["symbol"], str(K[-1][0])) + [""]
        L.append(MARK1)
        f = Path(cfg.get("dir") or ROOT / "skills" / f"{sk}-skill") / "persona" / "profile.md"
        if not f.exists():
            continue
        t = f.read_text(encoding="utf-8")
        t = re.sub(re.escape(MARK0) + r"[\s\S]*?" + re.escape(MARK1), lambda _: "\n".join(L), t) if MARK0 in t else t.rstrip() + "\n\n" + "\n".join(L) + "\n"
        f.write_text(t, encoding="utf-8")
        print(f"{sk}-skill 数据画像 {len(L)} 行 → {f.relative_to(ROOT)}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
