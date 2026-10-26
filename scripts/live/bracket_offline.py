# -*- coding: utf-8 -*-
"""bracket_offline.py — 条件单组离线测试(10/25 夜; 只用现有数据, 零 token, 不调模型, 不接实盘)

  python bracket_offline.py cases                 A. 10/23 五个案例: 模型固定价 vs 条件单组 vs 导师真人
  python bracket_offline.py batch [--days 2026-10-12:2026-10-23]   B. 批量: 开盘后急跌情境的卖 / 低吸买 + 涨停回落条件单 + 参数敏感性
结果: results/_bracket/cases_<ts>.json / batch_<ts>.json + 同名 .md 表格(报告 docs/research/bracket_offline_20261026.md 从这里抄)
"""
import argparse
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import range_engine as R   # noqa: E402
import bracket_sim as B    # noqa: E402

ROOT = R.ROOT
OUT = ROOT / "results" / "_bracket"
COST = 0.001


# ---------------------------------------------------------------- 方案库 ----------------------------------------------------------------
STOP_Q = {"q": 10, "h": "60", "key": "最低", "min": 0.5}


def _stop(kind, gate=None, after=None):
    """破位止损: q10 = 跌破'同状态之后 60 分钟最低'的 P10(区间引擎给距离, 地板 0.5%); low = 跌破生效时日内最低 −0.5%"""
    if kind == "q10":
        r = {"id": "stop", "type": "cond", "qty": 1.0, "ref": "@px", "dir": "down", "pct": dict(STOP_Q), "book": "b1"}
    else:
        r = {"id": "stop", "type": "cond", "qty": 1.0, "ref": "@low", "dir": "down", "pct": 0.5, "book": "b1"}
    if gate:
        r["gate"] = gate
    if after:
        r["after"] = after
    return r


def sell_rebound(red=3, rsi=80, t1q=50, trail_k=0.5, stop="q10", hard_k=None, t2=None, h="60"):
    """卖: 等反抽(红柱≥red + RSI6>rsi + 价≥均价−0.2%) → 第一档挂区间引擎 P{t1q} 卖一半; 卖掉后剩余用"日内最高回落 trail_k×振幅"移动止盈(防卖飞);
    反抽后跌破止损(默认: 同状态 60 分钟最低 P10) = 破位全卖; hard_k = 反抽出现前的硬止损(开盘价回落 hard_k×振幅); 14:56 卖剩余"""
    g = {"type": "rebound", "red": red, "rsi": rsi}
    rules = [{"id": "t1", "type": "limit", "qty": 0.5, "px_from": {"h": h, "key": "最高", "q": t1q}, "gate": g}]
    if t2:
        rules.append({"id": "t2", "type": "limit", "qty": 0.5, "px_from": {"h": h, "key": "最高", "q": t2}, "gate": g})
    else:
        rules.append({"id": "trail", "type": "cond", "qty": 0.5, "ref": "日内最高", "dir": "down", "pct": {"amp_k": trail_k}, "book": "b1", "after": "t1"})
    if stop:
        rules.append(_stop(stop, gate=g))
    if hard_k:
        rules.append({"id": "stop_hard", "type": "cond", "qty": 1.0, "ref": "开盘价", "dir": "down", "pct": {"amp_k": hard_k}, "book": "b1"})
    return {"side": "SELL", "deadline": "14:56", "rules": rules}


def sell_now(t1q=50, t2q=75, trail_k=None, stop="q10", h="60"):
    """卖: 立即按此刻状态挂两档(区间引擎 最高 P{t1q} / P{t2q}), 或第二档换成移动止盈; 止损从现在起生效"""
    rules = [{"id": "t1", "type": "limit", "qty": 0.5, "px_from": {"h": h, "key": "最高", "q": t1q}}]
    if trail_k:
        rules.append({"id": "trail", "type": "cond", "qty": 0.5, "ref": "日内最高", "dir": "down", "pct": {"amp_k": trail_k}, "book": "b1", "after": "t1"})
    else:
        rules.append({"id": "t2", "type": "limit", "qty": 0.5, "px_from": {"h": h, "key": "最高", "q": t2q}})
    if stop:
        rules.append(_stop(stop))
    return {"side": "SELL", "deadline": "14:56", "rules": rules}


def sell_panic(nolow=3, t1q=50, t2q=75, trail_k=None, stop="q10", h="60"):
    """卖: 恐慌盘卖完(不再创新低 nolow 根 + MACD 红) → P{t1q} / P{t2q} 两档各一半(或第二档换移动止盈); 止损同上"""
    g = {"type": "panic_done", "nolow": nolow}
    rules = [{"id": "t1", "type": "limit", "qty": 0.5, "px_from": {"h": h, "key": "最高", "q": t1q}, "gate": g}]
    if trail_k:
        rules.append({"id": "trail", "type": "cond", "qty": 0.5, "ref": "日内最高", "dir": "down", "pct": {"amp_k": trail_k}, "book": "b1", "after": "t1"})
    else:
        rules.append({"id": "t2", "type": "limit", "qty": 0.5, "px_from": {"h": h, "key": "最高", "q": t2q}, "gate": g})
    if stop:
        rules.append(_stop(stop, gate=g))
    return {"side": "SELL", "deadline": "14:56", "rules": rules}


def sell_board(pct=3.0, rest="rebound", n_open=None, trail_k=0.5):
    """封板票: 封住就拿着; 涨停价回落 pct%(条件单, 先碰涨停才算) → 卖一半; 剩余等反抽挂 P50 卖 / 或移动止盈; 收盘前没卖完: rest=hold 拿过夜"""
    r1 = {"id": "b1", "type": "cond", "qty": 0.5, "ref": "涨停价", "dir": "down", "pct": pct, "book": "b1"}
    if n_open:
        r1["gate"] = {"type": "n_open", "n": n_open}
    rules = [r1]
    if rest == "rebound":
        g = {"type": "rebound", "red": 3, "rsi": 80}
        rules.append({"id": "t2", "type": "limit", "qty": 0.5, "px_from": {"h": "60", "key": "最高", "q": 50}, "after": "b1", "gate": g})
        rules.append(_stop("q10", gate=g, after="b1"))
        eod = "sell"
    elif rest == "now":   # 卖掉一半后立刻按那一刻状态挂 P50(不等反抽信号), 止损同上
        rules.append({"id": "t2", "type": "limit", "qty": 0.5, "px_from": {"h": "60", "key": "最高", "q": 50}, "after": "b1"})
        rules.append(_stop("q10", after="b1"))
        eod = "sell"
    elif rest == "all":
        rules[0]["qty"] = 1.0
        eod = "hold"
    else:   # trail
        rules.append({"id": "trail", "type": "cond", "qty": 0.5, "ref": "日内最高", "dir": "down", "pct": {"amp_k": trail_k}, "book": "b1", "after": "b1"})
        eod = "sell"
    return {"side": "SELL", "deadline": "14:56", "eod": eod, "rules": rules}


def buy_dip(nolow=3, q1=50, q2=25, chase=("cond", 0.5), fail=-3.0, h="60"):
    """低吸: 恐慌盘卖完 → 区间引擎 最低 P{q1} / P{q2} 两档各一半; 跌破恐慌低点 fail% 撤单(失败止损: 不接飞刀);
    防踏空: chase=("cond", k) = 日内最低反弹 k×振幅 且前两档都没买到 → 追一半; ("vwap", vr) = 站上均价且量能≥vr → 追一半; None = 不追"""
    g = {"type": "panic_done", "nolow": nolow}
    rules = [{"id": "b1", "type": "limit", "qty": 0.5, "px_from": {"h": h, "key": "最低", "q": q1}, "gate": g, "cancel_below": f"@low{fail}"},
             {"id": "b2", "type": "limit", "qty": 0.5, "px_from": {"h": h, "key": "最低", "q": q2}, "gate": g, "cancel_below": f"@low{fail}"}]
    if chase and chase[0] == "cond":
        rules.append({"id": "chase", "type": "cond", "side": "BUY", "qty": 0.5, "ref": "日内最低", "dir": "up", "pct": {"amp_k": chase[1]}, "book": "a1",
                      "gate": g, "unless_filled": ["b1", "b2"]})
    elif chase and chase[0] == "vwap":
        rules.append({"id": "chase", "type": "market", "side": "BUY", "qty": 0.5, "gate": {"type": "vwap_vol", "vr": chase[1]}, "unless_filled": ["b1", "b2"]})
    return {"side": "BUY", "deadline": "14:50", "eod": "cancel", "rules": rules}


def base_sell(kind, x=None):
    if kind == "now":
        return {"side": "SELL", "deadline": "14:56", "rules": [{"id": "m", "type": "market", "qty": 1.0}]}
    if kind == "fixed":
        return {"side": "SELL", "deadline": "14:56", "rules": [{"id": "f", "type": "limit", "qty": 1.0, "px": x}]}
    if kind == "close":
        return {"side": "SELL", "deadline": "14:56", "rules": []}


def base_buy(kind, x=None):
    if kind == "now":
        return {"side": "BUY", "deadline": "14:50", "eod": "cancel", "rules": [{"id": "m", "type": "market", "qty": 1.0}]}
    if kind == "fixed":
        return {"side": "BUY", "deadline": "14:50", "eod": "cancel", "rules": [{"id": "f", "type": "limit", "qty": 1.0, "px": x}]}
    if kind == "close":
        return {"side": "BUY", "deadline": "14:56", "eod": "cancel", "rules": [{"id": "c", "type": "market", "qty": 1.0, "gate": {"type": "time", "at": "14:55"}}]}


# ---------------------------------------------------------------- 工具 ----------------------------------------------------------------
def nd_row(code, D):
    n = R.next_day(D)
    if not n:
        return None
    d = R.load_day(n)
    if code not in d.idx:
        return None
    i = d.idx[code]
    return {"open": float(d.open[i]), "high": float(np.max(d.H[i])), "close": float(d.C[i, -1]), "D": n}


def sim(P, spec, k0, E):
    r = B.run(P, spec, k0, E)
    ev = B.evaluate(P, r, k0, spec["side"])
    return r, ev


def fills_txt(r):
    return "; ".join(f"{R.k2hm(f[0]) if f[0] >= 0 else '09:30'} {f[3]} {f[1]}×{f[2]}({f[4]})" for f in r["fills"]) or "没成交"


# ---------------------------------------------------------------- A. 案例 ----------------------------------------------------------------
REPLAYS = ["2026-10-23_newskill_bugfill", "2026-10-23_newskill"]
LINE_NM = {"liuyiqing": "刘忆青", "zhiyingjuexin": "芷影", "buchitudou0": "不吃土豆0", "lubenyuan": "卢本圆", "taoge": "桃哥", "zuoshoudeirong": "左手"}


def model_actions(code):
    out = []
    for rp in REPLAYS:
        for f in sorted((ROOT / "results" / "_replay" / rp / "2026-10-23").glob("live_*/actions.jsonl")):
            line = f.parent.name[5:]
            for l in f.open(encoding="utf-8"):
                a = json.loads(l)
                if a["code"] == code:
                    out.append({"replay": rp.replace("2026-10-23_", ""), "line": LINE_NM.get(line, line), "t": a["t"], "side": a["side"], "px": a["px"], "qty": a["qty"], "rule": a.get("rule"),
                                "why": (a.get("why") or "")[:70]})
    return out


def mentor_legs(code, D="2026-10-23"):
    try:
        import plan_review as PR
        c = PR.db().cursor()
        c.execute("select ledger, record_time, side, price, qty from tzzb_record where record_type='bs_leg' and is_deleted=0 and stock_code=%s "
                  "and record_time >= %s and record_time < date_add(%s, interval 1 day) order by record_time", (code, D, D))
        return [{"ledger": a, "t": b.strftime("%H:%M:%S"), "side": "BUY" if "买" in s else "SELL", "px": float(p), "qty": float(q)} for a, b, s, p, q in c.fetchall()]
    except Exception as e:   # noqa: BLE001
        return [{"err": repr(e)[:150]}]


def wavg(xs):
    q = sum(x[1] for x in xs)
    return round(sum(x[0] * x[1] for x in xs) / q, 3) if q else None


CASES = [
    {"code": "600851", "name": "海欣股份", "side": "SELL", "k0": "09:31", "why": "低开 −0.5% 后急跌到 7.85, 14:07 涨停; 模型 09:36 在 8.16(绿柱、均价下方)卖"},
    {"code": "002696", "name": "百洋股份", "side": "SELL", "k0": "09:31", "why": "高开 +2.9% 冲到 10.61 后回落; 模型开盘第一跳卖"},
    {"code": "002307", "name": "北新路桥", "side": "SELL", "k0": "09:31", "board": True, "why": "首板次日 3.60 开, 09:31 封板, 09:34 开板 09:35 回封(二封), 09:39 再炸板单边下杀, 收 3.46"},
    {"code": "003029", "name": "吉大正元", "side": "BUY", "k0": "09:36", "why": "跌停开盘 21.33, 09:36 开板; 芷影线 09:41 在 21.8 低吸"},
    {"code": "002368", "name": "太极股份", "side": "BUY", "k0": "09:34", "why": "低开 −8.2%(14.08)冲到 15.03 后回落, 11:16 跌停 13.80, 收 14.51; 芷影线挂 14.30 等二次探底"},
]


def cases():
    E = R.RangeEngine()
    D = "2026-10-23"
    rep, md = [], ["# A. 10/23 案例(条件单组离线模拟)", ""]
    for cs in CASES:
        P = B.Path(cs["code"], D)
        k0 = R.hm2k(cs["k0"])
        close = float(P.C[-1])
        md += [f"## {cs['name']} {cs['code']}({cs['why']})", f"开 {P.open} 高 {P.H.max()} 低 {P.L.min()} 收 {close}; 20 日振幅中位 {round(P.amp() * 100, 2)}%; 方案从 {cs['k0']} 收盘起生效", ""]
        q0 = E.query(st=R.state_at(cs["code"], D, k=k0))
        md += ["区间引擎(此刻): " + R.fmt(q0).replace("\n", "  \n"), ""]
        variants = []
        if cs["side"] == "SELL":
            variants += [("反抽卖(红3 RSI80, P50 一半 + 移动止盈 0.5×振幅)", sell_rebound()),
                         ("反抽卖(同上, 移动止盈 1.0×振幅)", sell_rebound(trail_k=1.0)),
                         ("反抽卖 + 硬止损(开盘价回落 1.5×振幅)", sell_rebound(hard_k=1.5)),
                         ("恐慌盘卖完卖(P50 / P75 两档)", sell_panic()),
                         ("恐慌盘卖完卖(P50 + 移动止盈 1.0×振幅)", sell_panic(trail_k=1.0)),
                         ("立即挂两档(P50 / P75)", sell_now()),
                         ("立即挂 P50 + 移动止盈 1.0×振幅", sell_now(trail_k=1.0)),
                         ("对照: 立即卖", base_sell("now")), ("对照: 收盘卖", base_sell("close"))]
            if cs.get("board"):
                variants = [("封板拿着, 涨停价回落 1% 全卖(批量最优档)", sell_board(1, rest="all")),
                            ("封板拿着, 涨停价回落 1% 卖一半, 剩余立刻挂 P50", sell_board(1, rest="now")),
                            ("封板拿着, 涨停价回落 3% 卖一半, 剩余等反抽 P50(破反抽前低止损)", sell_board(3)),
                            ("封板拿着, 涨停价回落 2% 卖一半, 剩余等反抽", sell_board(2)),
                            ("封板拿着, 涨停价回落 3% 卖一半, 剩余立刻挂 P50", sell_board(3, rest="now")),
                            ("封板拿着, 第 2 次开板后涨停价回落 2% 卖一半, 剩余等反抽", sell_board(2, n_open=2)),
                            ("封板拿着, 涨停价回落 3% 卖一半, 剩余移动止盈 0.5×振幅", sell_board(3, rest="trail")),
                            ("封板拿着, 涨停价回落 3% 全卖", sell_board(3, rest="all"))] + variants
        else:
            variants += [("低吸: 恐慌盘卖完 → 最低 P50 / P25 两档 + 防踏空(日内最低反弹 0.5×振幅追一半)", buy_dip()),
                         ("低吸: 同上, 防踏空改'站上均价且量能≥1.5'", buy_dip(chase=("vwap", 1.5))),
                         ("低吸: 同上, 不追", buy_dip(chase=None)),
                         ("对照: 立即买", base_buy("now")), ("对照: 收盘买", base_buy("close"))]
        rows = []
        for nm, spec in variants:
            r, ev = sim(P, spec, k0, E)
            rows.append({"方案": nm, "成交": fills_txt(r), "均价": ev.get("avg"), "成交比例": ev.get("filled"), "相对收盘%": ev.get("vs_close", ev.get("to_close")),
                         "区间位置": ev.get("pos"), "卖后最高%": ev.get("卖后最高%"), "卖飞": ev.get("卖飞"), "踏空": ev.get("踏空"), "notes": r["notes"]})
        ma = model_actions(cs["code"])
        ml = mentor_legs(cs["code"])
        md += ["| 方案 | 成交 | 均价 | 成交比例 | " + ("卖价相对收盘(扣 0.1%)" if cs["side"] == "SELL" else "买入到收盘(扣双边 0.1%)") + " | 区间位置(0 低 1 高) | " + ("卖后最高" if cs["side"] == "SELL" else "踏空") + " |",
               "|---|---|---|---|---|---|---|"]
        for x in rows:
            md.append(f"| {x['方案']} | {x['成交']} | {x['均价']} | {x['成交比例']} | {x['相对收盘%']} | {x['区间位置']} | {x['卖后最高%'] if cs['side'] == 'SELL' else x['踏空']} |")
        md.append("")
        for x in rows:
            if x["notes"]:
                md.append(f"- {x['方案']}: " + " / ".join(x["notes"]))
        md += ["", "模型(回放)实际成交:"]
        by = defaultdict(list)
        for a in ma:
            by[(a["replay"], a["line"])].append(a)
        for (rp, ln), xs in by.items():
            av = wavg([(a["px"], a["qty"]) for a in xs if a["side"] == cs["side"]])
            md.append(f"- {rp} / {ln}: " + "; ".join(f"{a['t']} {a['side']} {a['px']}×{a['qty']}" for a in xs) + (f" → {cs['side']} 均价 {av}(相对收盘 {round((av / close - 1) * 100, 2)}%)" if av else ""))
        md += ["", "导师真人 10/23(tzzb bs_leg):"]
        if not ml:
            md.append("- 当天没有导师在这只票上的逐笔")
        by = defaultdict(list)
        for a in ml:
            by[a.get("ledger")].append(a)
        for led, xs in by.items():
            if "err" in xs[0]:
                md.append(f"- 读取失败 {xs[0]['err']}")
                continue
            s_ = wavg([(a["px"], a["qty"]) for a in xs if a["side"] == "SELL"])
            b_ = wavg([(a["px"], a["qty"]) for a in xs if a["side"] == "BUY"])
            md.append(f"- {led}: " + "; ".join(f"{a['t'][:5]} {'买' if a['side'] == 'BUY' else '卖'} {a['px']}×{int(a['qty'])}" for a in xs)
                      + (f" → 卖均价 {s_}(相对收盘 {round((s_ / close - 1) * 100, 2)}%)" if s_ else "") + (f" 买均价 {b_}(相对收盘 {round((close / b_ - 1) * 100, 2)}%)" if b_ else ""))
        md.append("")
        rep.append({"case": cs, "range_now": {k: v for k, v in q0.items() if k != "state"}, "rows": rows, "model": ma, "mentor": ml})
    ts = dt.datetime.now().strftime("%m%d_%H%M")
    (OUT / f"cases_{ts}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (OUT / f"cases_{ts}.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


# ---------------------------------------------------------------- B. 批量 ----------------------------------------------------------------
def samples(days, drop=0.03, kmax=59):
    """主板非 ST、有 OHLC 的票; 开盘后 kmax 根内第一次 收盘 ≤ 开盘 × (1 − drop) 的那根 = 决策时刻 t0(不在跌停)"""
    out = []
    st = R.st_codes()
    for D in days:
        d = R.load_day(D)
        for c, i in d.idx.items():
            if c[:2] not in ("00", "60") or c in st or d.src[i] != 1 or not np.isfinite(d.prev[i]):
                continue
            C, o = d.C[i], d.open[i]
            if not (o > 0) or np.nansum(d.V[i]) <= 0:
                continue
            hit = np.where(C[:kmax + 1] <= o * (1 - drop))[0]
            if not len(hit):
                continue
            k = int(hit[0])
            if C[k] <= d.dn[i] + 0.005 or o >= d.up[i] - 0.005:
                continue
            out.append((D, c, k))
    return out


def board_samples(days, kmax=200):
    """主板非 ST: 当天第一次碰涨停的那根 = t0(排除一字板: 全天 高 = 低 = 涨停)"""
    out = []
    st = R.st_codes()
    for D in days:
        d = R.load_day(D)
        for c, i in d.idx.items():
            if c[:2] not in ("00", "60") or c in st or d.src[i] != 1:
                continue
            H, L = d.H[i], d.L[i]
            up = d.up[i]
            hit = np.where(H[:kmax + 1] >= up - 0.005)[0]
            if not len(hit) or (L.min() >= up - 0.005):
                continue
            out.append((D, c, int(hit[0]) - 1))   # 决策在碰板之前一根(涨停价卖单 / 条件单提前挂好)
    return out


def summarize(evs, side):
    """evs: list of ev dict → 汇总"""
    def pct(a, q):
        return round(float(np.percentile(a, q)), 2) if len(a) else None
    n = len(evs)
    got = [e for e in evs if e.get("avg") is not None]
    if side == "SELL":
        v = np.array([e["vs_close"] for e in got])
        pos = np.array([e["pos"] for e in got if e.get("pos") is not None])
        nd = np.array([e["nd_open"] for e in got if e.get("nd_open") is not None])
        return {"n": n, "相对收盘均值%": round(float(v.mean()), 2), "中位": pct(v, 50), "P10": pct(v, 10), "P90": pct(v, 90), "最差": pct(v, 0),
                "胜过收盘卖%": round(float((v > 0).mean() * 100), 1), "区间位置均值": round(float(pos.mean()), 3) if len(pos) else None, "区间位置中位": pct(pos, 50),
                "卖飞%": round(100 * np.mean([e["卖飞"] for e in got]), 1), "止损%": round(100 * np.mean([e.get("止损", False) for e in got]), 1),
                "移动止盈%": round(100 * np.mean([e.get("trail", False) for e in got]), 1), "收盘才卖的仓位均值": round(float(np.mean([e.get("eod_part", 0) for e in got])), 3),
                "相对次日开盘均值%": round(float(nd.mean()), 2) if len(nd) else None,
                "卖后回封%": round(100 * np.mean([e.get("卖后回封", False) for e in got]), 1), "拿过夜仓位均值": round(float(np.mean([e.get("hold_part", 0) for e in got])), 3)}
    v = np.array([e["to_close"] for e in got]) if got else np.array([])
    pos = np.array([e["pos"] for e in got]) if got else np.array([])
    ndo = np.array([e["nd_open"] for e in got if e.get("nd_open") is not None])
    ndh = np.array([e["nd_high"] for e in got if e.get("nd_high") is not None])
    return {"n": n, "买到%": round(100 * len(got) / max(n, 1), 1), "成交比例均值": round(float(np.mean([e["filled"] for e in evs])), 3),
            "到收盘均值%": round(float(v.mean()), 2) if len(v) else None, "中位": pct(v, 50), "P10": pct(v, 10), "P90": pct(v, 90), "最差": pct(v, 0),
            "区间位置均值": round(float(pos.mean()), 3) if len(pos) else None, "踏空%": round(100 * np.mean([e.get("踏空", False) for e in evs]), 1),
            "失败(收盘<买价−3%)%": round(100 * np.mean([e.get("失败", False) for e in got]), 1) if got else None,
            "追买%": round(100 * np.mean([e.get("chase", 0) > 0 for e in got]), 1) if got else None,
            "次日开盘均值%": round(float(ndo.mean()), 2) if len(ndo) else None, "次日最高中位%": pct(ndh, 50)}


def run_set(smp, specs, side, E, label):
    res = {nm: [] for nm, _ in specs}
    for D, c, k in smp:
        try:
            P = B.Path(c, D)
        except KeyError:
            continue
        nd = nd_row(c, D)
        for nm, spec in specs:
            sp = spec(P, k) if callable(spec) else spec
            r = B.run(P, sp, k, E)
            if sp.get("eod") == "hold" and r["pos"] > 1e-6:   # 拿过夜的剩余按次日开盘估值; 没有次日数据 → 按收盘
                r["fills"].append((239, nd["open"] if nd else float(P.C[-1]), round(r["pos"], 4), "HOLD", "拿过夜按次日开盘"))
            ev = B.evaluate(P, r, k, side)
            if ev.get("avg") is not None and nd:
                if side == "SELL":
                    ev["nd_open"] = round((ev["avg"] * (1 - COST) / nd["open"] - 1) * 100, 3)   # >0 = 卖得比次日开盘好
                else:
                    ev["nd_open"] = round((nd["open"] * (1 - COST) / (ev["avg"] * (1 + COST)) - 1) * 100, 3)
                    ev["nd_high"] = round((nd["high"] / ev["avg"] - 1) * 100, 3)
            ev.update({"D": D, "code": c, "k": k})
            res[nm].append(ev)
    print(label, "done", len(smp), flush=True)
    return res


def reseal_samples(days):
    """主板非 ST: 封过 → 开板 → 第一次回封(收盘价 = 涨停价)的那一根 = t0(北新路桥 10/23 09:35 这种'二封'情境)"""
    out = []
    st = R.st_codes()
    for D in days:
        d = R.load_day(D)
        for c, i in d.idx.items():
            if c[:2] not in ("00", "60") or c in st or d.src[i] != 1:
                continue
            up = d.up[i]
            sealed = d.C[i] >= up - 0.005
            opened = False
            was = False
            for k in range(239):
                if sealed[k] and opened:
                    out.append((D, c, k))
                    break
                if was and d.L[i, k] < up - 0.005 and not sealed[k]:
                    opened = True
                was = was or sealed[k]
    return out


def batch_board(days, reseal=False):
    E = R.RangeEngine()
    bsmp = reseal_samples(days) if reseal else board_samples(days)
    bspecs = [("涨停价卖(第一次碰板就卖)", lambda P, k: base_sell("fixed", P.up)), ("拿到收盘卖", base_sell("close")),
              ("拿过夜(次日开盘卖)", {"side": "SELL", "deadline": "14:56", "eod": "hold", "rules": []})]
    for pct in (1, 2, 3, 5):
        bspecs.append((f"涨停价回落{pct}% 全卖(没触发拿过夜)", sell_board(pct, rest="all")))
        bspecs.append((f"涨停价回落{pct}% 卖一半 + 剩余等反抽", sell_board(pct)))
        bspecs.append((f"涨停价回落{pct}% 卖一半 + 剩余立刻挂P50", sell_board(pct, rest="now")))
    for ak in (0.3, 0.5, 0.8, 1.2):
        bspecs.append((f"涨停价回落{ak}×振幅 全卖(没触发拿过夜)", lambda P, k, ak=ak: sell_board(max(0.5, round(ak * P.amp() * 100, 2)), rest="all")))
    bspecs.append(("第2次开板后 涨停价回落2% 全卖(没触发拿过夜)", sell_board(2, rest="all", n_open=2)))
    res_z = run_set(bsmp, bspecs, "SELL", E, "board")
    ts = dt.datetime.now().strftime("%m%d_%H%M")
    raw = {"days": days, "n_board": len(bsmp), "board": res_z}
    ts = ("reseal_" if reseal else "") + ts
    (OUT / f"board_{ts}.json").write_text(json.dumps(raw, ensure_ascii=False, default=str), encoding="utf-8")
    md = [f"## 封板票 · {'第一次回封(二封)那一根起' if reseal else '第一次碰涨停的前一根起'} n={len(bsmp)}", ""]
    rows = [(nm, summarize(evs, "SELL")) for nm, evs in res_z.items() if evs]
    keys = list(rows[0][1].keys())
    md += ["| 方案 | " + " | ".join(keys) + " |", "|---|" + "---|" * len(keys)]
    md += [f"| {nm} | " + " | ".join(str(s_[k]) for k in keys) + " |" for nm, s_ in rows]
    (OUT / f"board_{ts}.md").write_text(chr(10).join(md), encoding="utf-8")
    print(chr(10).join(md))


def exec_sell(z=0.5, trail_k=0.8, first=0.5):
    """只用 executor 10/25 已有字段的卖法: 条件单 '日内最低反弹 z×振幅' 卖 first(代替反抽信号), 之后剩余 '日内最高回落 trail_k×振幅' 移动止盈"""
    return {"side": "SELL", "deadline": "14:56", "rules": [
        {"id": "rb", "type": "cond", "qty": first, "ref": "日内最低", "dir": "up", "pct": {"amp_k": z}, "book": "b1"},
        {"id": "trail", "type": "cond", "qty": 1 - first, "ref": "日内最高", "dir": "down", "pct": {"amp_k": trail_k}, "book": "b1", "after": "rb"}]}


def exec_buy(q1=50, q2=25, z=0.5, h="60"):
    """只用 executor 已有字段的低吸: 限价 最低 P{q1} / P{q2}(区间引擎给价) + 条件单 '日内最低反弹 z×振幅' 追一半; executor 没有 unless_filled → 追单总会生效(总量封顶 1)"""
    return {"side": "BUY", "deadline": "14:50", "eod": "cancel", "rules": [
        {"id": "b1", "type": "limit", "qty": 0.5, "px_from": {"h": h, "key": "最低", "q": q1}},
        {"id": "b2", "type": "limit", "qty": 0.5, "px_from": {"h": h, "key": "最低", "q": q2}},
        {"id": "chase", "type": "cond", "qty": 0.5, "ref": "日内最低", "dir": "up", "pct": {"amp_k": z}, "book": "a1"}]}


def batch_exec(days):
    E = R.RangeEngine()
    smp = samples(days)
    half = {"side": "SELL", "deadline": "14:56", "rules": [{"id": "m", "type": "market", "qty": 0.5}]}
    ss = [("一半立即 + 一半收盘(时间分散基线)", half),
          ("E1 日内最低反弹0.3×振幅卖一半 + 移动0.8", exec_sell(0.3)), ("E2 日内最低反弹0.5×振幅卖一半 + 移动0.8", exec_sell(0.5)),
          ("E3 日内最低反弹0.8×振幅卖一半 + 移动0.8", exec_sell(0.8)), ("E4 日内最低反弹0.5×振幅全卖", exec_sell(0.5, first=1.0)),
          ("E5 立即挂P50一半 + 移动0.8", sell_now(trail_k=0.8, stop=None)), ("E6 立即挂P50/P75 两档", sell_now(stop=None))]
    bs = [("X1 低吸P50/P25 + 追(反弹0.5×振幅, 总会生效)", exec_buy()), ("X2 低吸P50/P25 + 追(反弹0.8×振幅)", exec_buy(z=0.8)),
          ("X3 低吸P75/P50 + 追(反弹0.5×振幅)", exec_buy(75, 50))]
    rs = run_set(smp, ss, "SELL", E, "exec_sell")
    rb = run_set(smp, bs, "BUY", E, "exec_buy")
    ts = dt.datetime.now().strftime("%m%d_%H%M")
    (OUT / f"exec_{ts}.json").write_text(json.dumps({"sell": rs, "buy": rb}, ensure_ascii=False, default=str), encoding="utf-8")
    md = []
    for title, res, side in (("卖 · 只用 executor 现有字段", rs, "SELL"), ("买 · 只用 executor 现有字段", rb, "BUY")):
        rows = [(nm, summarize(evs, side)) for nm, evs in res.items() if evs]
        keys = list(rows[0][1].keys())
        md += [f"## {title}", "", "| 方案 | " + " | ".join(keys) + " |", "|---|" + "---|" * len(keys)]
        md += [f"| {nm} | " + " | ".join(str(s_[k]) for k in keys) + " |" for nm, s_ in rows] + [""]
    (OUT / f"exec_{ts}.md").write_text(chr(10).join(md), encoding="utf-8")
    print(chr(10).join(md))


def batch(days):
    E = R.RangeEngine()
    smp = samples(days)
    print("急跌样本", len(smp), flush=True)
    by_day = defaultdict(int)
    for D, _, _ in smp:
        by_day[D] += 1

    def fixed(x):
        return lambda P, k: base_sell("fixed", B.ce(P.C[k] * (1 + x)))

    def fixed_b(x):
        return lambda P, k: base_buy("fixed", B.fl(P.C[k] * (1 + x)))

    sell_specs = [("开盘卖(参照, 急跌前就卖)", lambda P, k: base_sell("now")), ("立即卖(急跌那一刻)", base_sell("now")), ("固定价 +1%", fixed(0.01)), ("固定价 +2%", fixed(0.02)),
                  ("收盘卖", base_sell("close")),
                  ("A 反抽卖 红3 RSI80 P50+移动0.5", sell_rebound()),
                  ("A' 反抽卖 + 硬止损1.5×振幅", sell_rebound(hard_k=1.5)),
                  ("B 恐慌盘卖完 P50/P75", sell_panic()),
                  ("C 恐慌盘卖完 P50+移动0.5", sell_panic(trail_k=0.5)),
                  ("D 恐慌盘卖完 P25/P50", sell_panic(t1q=25, t2q=50))]
    sens = []
    for red in (2, 3, 5):
        for rsi in (None, 70, 80):
            sens.append((f"反抽 红{red} RSI{rsi or '不要求'} 移动0.5", sell_rebound(red=red, rsi=rsi)))
    for tk in (0.25, 0.5, 0.8, 1.2):
        sens.append((f"反抽 红3 RSI80 移动{tk}×振幅", sell_rebound(trail_k=tk)))
    for q in (25, 75):
        sens.append((f"反抽 红3 RSI80 第一档P{q} 移动0.5", sell_rebound(t1q=q)))
    sens.append(("反抽 红3 RSI80 两档 P50/P75 不移动", sell_rebound(t2=75)))
    # 开盘卖参照要从 k=-1 开始, 单独跑
    res_s = {}
    open_res = run_set([(D, c, -1) for D, c, k in smp], [("开盘卖(参照, 急跌前就卖)", base_sell("now"))], "SELL", E, "open")
    # 开盘卖的区间位置要和别的同口径(t0 之后的区间) → 重新按 k 评估
    res_s.update(run_set(smp, sell_specs[1:] + sens, "SELL", E, "sell"))
    buy_specs = [("立即买", base_buy("now")), ("固定价 −1%", fixed_b(-0.01)), ("固定价 −2%", fixed_b(-0.02)), ("收盘买", base_buy("close")),
                 ("G 低吸 P50/P25 + 防踏空(最低反弹0.5×振幅)", buy_dip()),
                 ("G' 低吸 + 防踏空(站上均价且量≥1.5)", buy_dip(chase=("vwap", 1.5))),
                 ("G0 低吸 不追", buy_dip(chase=None))]
    bsens = []
    for z in (0.25, 0.5, 0.8, 1.2):
        bsens.append((f"低吸 防踏空 最低反弹{z}×振幅", buy_dip(chase=("cond", z))))
    for vr in (1.0, 1.5, 2.0):
        bsens.append((f"低吸 防踏空 站上均价且量≥{vr}", buy_dip(chase=("vwap", vr))))
    for nl in (2, 5):
        bsens.append((f"低吸 恐慌盘卖完 nolow={nl}", buy_dip(nolow=nl)))
    bsens.append(("低吸 两档 P75/P50(挂近一点)", buy_dip(q1=75, q2=50)))
    res_b = run_set(smp, buy_specs + bsens, "BUY", E, "buy")
    # 封板
    bsmp = board_samples(days)
    print("触板样本", len(bsmp), flush=True)
    bspecs = [("涨停价卖(第一次碰板就卖)", base_sell("fixed", None)), ("收盘卖", base_sell("close"))]
    bspecs = [("涨停价卖(第一次碰板就卖)", lambda P, k: base_sell("fixed", P.up)), ("拿到收盘卖", base_sell("close")),
              ("拿过夜(次日开盘卖)", {"side": "SELL", "deadline": "14:56", "eod": "hold", "rules": []})]
    for pct in (1, 2, 3, 5):
        bspecs.append((f"涨停价回落{pct}% 全卖(没触发拿过夜)", sell_board(pct, rest="all")))
        bspecs.append((f"涨停价回落{pct}% 卖一半 + 剩余等反抽", sell_board(pct)))
    for ak in (0.3, 0.5, 0.8):
        bspecs.append((f"涨停价回落{ak}×振幅 全卖", lambda P, k, ak=ak: sell_board(max(0.5, round(ak * P.amp() * 100, 2)), rest="all")))
    bspecs.append(("第2次开板后 涨停价回落2% 全卖", sell_board(2, rest="all", n_open=2)))
    res_z = run_set(bsmp, bspecs, "SELL", E, "board")
    # 拿过夜的: 估值 = 次日开盘(剩余部分)
    for nm, evs in res_z.items():
        for e in evs:
            pass
    ts = dt.datetime.now().strftime("%m%d_%H%M")
    raw = {"days": days, "n_sell": len(smp), "by_day": by_day, "sell": res_s, "open": open_res, "buy": res_b, "board": res_z}
    (OUT / f"batch_{ts}.json").write_text(json.dumps(raw, ensure_ascii=False, default=str), encoding="utf-8")
    return ts, raw


def board_value(evs_path):
    pass


def report(raw, ts):
    md = [f"# B. 批量离线测试 {raw['days'][0]}~{raw['days'][-1]}", "", f"急跌样本 n={raw['n_sell']}(按日 {dict(raw['by_day'])})", ""]

    def table(res, side, title, extra=None):
        rows = [(nm, summarize(evs, side)) for nm, evs in res.items() if evs]
        if not rows:
            return
        keys = list(rows[0][1].keys())
        md.extend([f"## {title}", "", "| 方案 | " + " | ".join(keys) + " |", "|---|" + "---|" * len(keys)])
        for nm, s in rows:
            md.append(f"| {nm} | " + " | ".join(str(s[k]) for k in keys) + " |")
        md.append("")

    table(raw["open"], "SELL", "卖 · 参照: 开盘就卖(注意: 样本按'之后急跌'挑出来, 对开盘卖有利)")
    table(raw["sell"], "SELL", "卖 · 急跌那一刻起的各方案")
    table(raw["buy"], "BUY", "买 · 低吸(急跌那一刻起)")
    table(raw["board"], "SELL", "封板票 · 第一次碰涨停起的各方案(拿过夜的剩余按次日开盘估值见'相对次日开盘')")
    (OUT / f"batch_{ts}.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--days", default="2026-10-12:2026-10-23")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reseal", action="store_true")
    a = ap.parse_args()
    if a.cmd == "cases":
        cases()
    elif a.cmd == "exec":
        lo, hi = a.days.split(":")
        batch_exec([d for d in R.trade_days() if lo <= d <= hi])
    elif a.cmd == "board":
        lo, hi = a.days.split(":")
        batch_board([d for d in R.trade_days() if lo <= d <= hi], reseal="--reseal" in sys.argv)
    elif a.cmd == "batch":
        lo, hi = a.days.split(":")
        days = [d for d in R.trade_days() if lo <= d <= hi]
        ts, raw = batch(days)
        report(raw, ts)


if __name__ == "__main__":
    main()
