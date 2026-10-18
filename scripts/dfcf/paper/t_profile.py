# -*- coding: utf-8 -*-
"""t_profile.py — 做T型导师 T 法画像(TODO 三-2e, 10/17 ② agent; 零 token, 只读)

T 定义: 同一导师同一交易日同一只票既有买又有卖(逐笔腿 downloads/tzzb/<ledger>/change_bs_*.json, gen_tzzb_profile.load_legs)。
每笔 T(票-日)机械量:
  类型      正T=当日第一腿是买(先买后卖, 需现金) / 倒T=第一腿是卖(先卖后买, 用昨日底仓, 符合 T+1)
  底仓占比  前一记录日收盘该票仓位(day_positions position_percent, 占总资产); 0=无底仓(转债 T+0 可以, 股票=数据缺口)
  规模      回转量 min(买量,卖量)×均价 / 前一日该票持仓市值(底仓=0 时记占总资产)
  触发      第一腿时刻(开盘后分钟)、第一腿时相对昨收/相对截至当时均价(skills/<x>-skill/persona/fills_rt.jsonl, 有分钟线的日子才有)
  回补价差  倒T: (卖均价−买均价)/卖均价 = 卖高接低的差; 正T: (卖均价−买均价)/买均价; 扣费后 >0 = 成功
  为什么T   触发类别分布(合计 100%): 冲高先卖 / 急跌先买 / 开盘急动 / 尾盘回转 / 均价附近 / 无分钟数据
画像 = 长期全历史 × 近 20 个交易日(收缩混合, 同 slot_profile 口径), 每天按 as-of 重算; 期望 = 每笔 T 扣费后收益(占回转额)均值 + t 值。
判定: 样本 ≥ MIN_T 且 长期均值>0 且 t>T_MIN → "执行T"(子链按其 T 法执行); 长期均值<0 且 t<−T_MIN → "不学T"(只学方向和仓位); 否则 "观察"。
  先做 antoo / 量化小号 / 高概率, 其余导师同口径输出供参考(用户 10/16 晚 B2)。

产物: scripts/dfcf/paper/t_profile/<D>.json; 驱动器经 quality_hooks 读(开关 CHAIN_T_PROFILE, 默认 0)。
CLI(scripts/venv/Scripts/python.exe -X utf8):
  t_profile.py --build [--date 2026-10-19] | --show [--date D] [--skill antoo] | --selftest
"""
import argparse
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date as _date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TZ = ROOT / "downloads" / "tzzb"
SKILLS = ROOT / "skills"
OUT = Path(__file__).resolve().parent / "t_profile"
sys.path.insert(0, str(ROOT / "scripts" / "tzzb"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

FIRST = ("antoo", "lianghuaxiaohao", "gaogailvfuli")
MIN_T = 15
T_MIN = 1.0
RECENT_DAYS = 20
KAPPA = 20.0
FEE = {"rate": 0.00025, "min": 5.0, "stamp": 0.0005}
REPO = re.compile(r"^(204|131|888)")
WHY = ("冲高先卖", "急跌先买", "开盘急动", "尾盘回转", "均价附近", "无分钟数据")


def _jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def _is_stock(code):
    try:
        import a_rules as AR
        return AR.board(code) in ("MAIN", "GEM", "STAR", "BSE")
    except Exception:   # noqa: BLE001
        return not str(code).startswith(("11", "12", "5", "15", "16"))


def fee(side, amt, code):
    f = max(FEE["min"], amt * FEE["rate"])
    return f + (amt * FEE["stamp"] if side == "S" and _is_stock(code) else 0.0)


def _q(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def rt_index(skill):
    """fills_rt.jsonl → {(date, HH:MM:SS, code, 买/卖): rt}"""
    idx = {}
    f = SKILLS / f"{skill}-skill" / "persona" / "fills_rt.jsonl"
    if not f.exists():
        return idx
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        idx[(r.get("date"), r.get("time"), str(r.get("code")), r.get("side"))] = r.get("rt") or {}
    return idx


def why_of(first_side, hm, rt):
    if not rt:
        return "无分钟数据"
    m = rt.get("mins_from_open")
    vpc, vav = rt.get("vs_prev_close"), rt.get("vs_avg_so_far")
    if hm >= "14:30":
        return "尾盘回转"
    if m is not None and m <= 10 and vpc is not None and abs(vpc) >= 0.015:
        return "开盘急动"
    if first_side == "S" and ((vav is not None and vav >= 0.005) or (vpc is not None and vpc >= 0.02)):
        return "冲高先卖"
    if first_side == "B" and ((vav is not None and vav <= -0.005) or (vpc is not None and vpc <= -0.02)):
        return "急跌先买"
    return "均价附近"


def t_events(ledger, asof, legs=None, dp=None, nav=None, rt=None):
    """→ (T 事件 list, 记录日 list)"""
    if legs is None:
        from gen_tzzb_profile import load_legs
        legs = load_legs(ledger)
    legs = [t for t in legs if t.get("op") in ("1", "2") and t["trans_date"][:10] < asof and not REPO.match(str(t.get("stock_code") or ""))]
    dp = dp if dp is not None else (_jl(TZ / ledger / "day_positions.json", {}) or {})
    if nav is None:
        nl = ((_jl(TZ / ledger / "nav_daily.json", {}) or {}).get("ex_data") or {}).get("index_list") or []
        nav = {f"{x['date'][:4]}-{x['date'][4:6]}-{x['date'][6:]}": float(x.get("asset") or 0) for x in nl}
    rt = rt if rt is not None else rt_index(ledger)
    pos = {f"{k[:4]}-{k[4:6]}-{k[6:]}": {str(x.get("code")): float(x.get("position_percent") or 0) for x in (v or {}).get("list") or []}
           for k, v in dp.items()}
    rec_days = sorted(d for d in set(pos) | set(nav) | {t["trans_date"][:10] for t in legs} if d < asof)
    prev_of = {rec_days[i]: rec_days[i - 1] for i in range(1, len(rec_days))}
    g = defaultdict(list)
    for t in legs:
        g[(t["trans_date"][:10], str(t["stock_code"]))].append(t)
    ev = []
    for (d, code), ts in g.items():
        ts.sort(key=lambda t: t["trans_date"])
        bq = sum(float(t.get("trans_count") or 0) for t in ts if t["op"] == "1")
        sq = sum(float(t.get("trans_count") or 0) for t in ts if t["op"] == "2")
        if bq <= 0 or sq <= 0:
            continue
        ba = sum(float(t.get("trans_count") or 0) * float(t.get("trans_price") or 0) for t in ts if t["op"] == "1")
        sa = sum(float(t.get("trans_count") or 0) * float(t.get("trans_price") or 0) for t in ts if t["op"] == "2")
        bp, sp = ba / bq, sa / sq
        if bp <= 0 or sp <= 0:
            continue
        mq = min(bq, sq)
        first = "B" if ts[0]["op"] == "1" else "S"
        hm = ts[0]["trans_date"][11:16]
        pd_ = prev_of.get(d)
        base_w = (pos.get(pd_) or {}).get(code, 0.0)
        asset = nav.get(pd_) or nav.get(d) or 0
        notional = mq * (bp + sp) / 2
        cost = fee("B", mq * bp, code) + fee("S", mq * sp, code)
        pnl = mq * (sp - bp) - cost
        r = rt.get((d, ts[0]["trans_date"][11:19], code, "买" if first == "B" else "卖"))
        ev.append({"date": d, "code": code, "type": "正T" if first == "B" else "倒T", "hm": hm, "base_w": round(base_w, 4),
                   "size": round(notional / (base_w * asset), 4) if base_w > 0 and asset > 0 else None,
                   "size_asset": round(notional / asset, 4) if asset > 0 else None,
                   "spread": round((sp - bp) / (sp if first == "S" else bp), 5), "ret": round(pnl / notional, 5) if notional else 0.0,
                   "pnl_asset": round(pnl / asset, 6) if asset > 0 else None, "ok": pnl > 0, "why": why_of(first, hm, r),
                   "vs_prev": (r or {}).get("vs_prev_close"), "vs_avg": (r or {}).get("vs_avg_so_far"), "mins": (r or {}).get("mins_from_open"),
                   "net_qty": bq - sq})
    ev.sort(key=lambda e: (e["date"], e["code"]))
    return ev, rec_days


def summarize(ev, n_days):
    if not ev:
        return None
    rets = [e["ret"] for e in ev]
    mean = statistics.fmean(rets)
    sd = statistics.pstdev(rets) if len(rets) > 1 else 0.0
    t = mean / (sd / math.sqrt(len(rets))) if sd > 0 else 0.0
    days = {e["date"] for e in ev}
    typ = Counter(e["type"] for e in ev)
    why = Counter(e["why"] for e in ev)
    sizes = [e["size"] for e in ev if e["size"] is not None]
    based = [e for e in ev if e["base_w"] > 0]
    dao = [e for e in ev if e["type"] == "倒T"]
    zheng = [e for e in ev if e["type"] == "正T"]
    pick = lambda xs, k: [x[k] for x in xs if x.get(k) is not None]
    return {"n": len(ev), "t_days": len(days), "freq": round(len(days) / max(1, n_days), 3),
            "type": {k: round(v / len(ev), 3) for k, v in typ.items()},
            "base_share": round(len(based) / len(ev), 3), "base_w_p50": _r(_q([e["base_w"] for e in based], 0.5)),
            "size_p25": _r(_q(sizes, 0.25)), "size_p50": _r(_q(sizes, 0.5)), "size_p75": _r(_q(sizes, 0.75)),
            "win": round(sum(e["ok"] for e in ev) / len(ev), 3), "ret_mean": round(mean, 5), "ret_p50": _r(_q(rets, 0.5), 5), "t": round(t, 2),
            "pnl_asset_sum": _r(sum(pick(ev, "pnl_asset")), 5),
            "dao": {"n": len(dao), "spread_p50": _r(_q(pick(dao, "spread"), 0.5), 5), "first_hm_p50": _hm_med([e["hm"] for e in dao]),
                    "trig_vs_prev_p50": _r(_q(pick(dao, "vs_prev"), 0.5), 4), "trig_vs_avg_p50": _r(_q(pick(dao, "vs_avg"), 0.5), 4),
                    "win": round(sum(e["ok"] for e in dao) / len(dao), 3) if dao else None, "ret_mean": _r(statistics.fmean(pick(dao, "ret")), 5) if dao else None},
            "zheng": {"n": len(zheng), "spread_p50": _r(_q(pick(zheng, "spread"), 0.5), 5), "first_hm_p50": _hm_med([e["hm"] for e in zheng]),
                      "trig_vs_prev_p50": _r(_q(pick(zheng, "vs_prev"), 0.5), 4), "trig_vs_avg_p50": _r(_q(pick(zheng, "vs_avg"), 0.5), 4),
                      "win": round(sum(e["ok"] for e in zheng) / len(zheng), 3) if zheng else None,
                      "ret_mean": _r(statistics.fmean(pick(zheng, "ret")), 5) if zheng else None},
            "why": {k: round(why.get(k, 0) / len(ev), 3) for k in WHY if why.get(k)}}


def _r(x, nd=4):
    return None if x is None else round(x, nd)


def _hm_med(hms):
    if not hms:
        return None
    m = sorted(int(h[:2]) * 60 + int(h[3:5]) for h in hms)[len(hms) // 2]
    return f"{m // 60:02d}:{m % 60:02d}"


def mixed(long_s, rec_s):
    """长期 × 近期 收缩混合(数值字段; 分布字段按同权重混)"""
    if not long_s:
        return None
    if not rec_s:
        return dict(long_s, alpha=0.0)
    a = rec_s["n"] / (rec_s["n"] + KAPPA)
    out = dict(long_s)
    for k in ("freq", "base_share", "size_p50", "win", "ret_mean"):
        if long_s.get(k) is not None and rec_s.get(k) is not None:
            out[k] = round((1 - a) * long_s[k] + a * rec_s[k], 5)
    for k in ("type", "why"):
        ks = set(long_s.get(k) or {}) | set(rec_s.get(k) or {})
        out[k] = {x: round((1 - a) * (long_s.get(k) or {}).get(x, 0) + a * (rec_s.get(k) or {}).get(x, 0), 3) for x in ks}
    out["alpha"] = round(a, 3)
    return out


def verdict(long_s):
    if not long_s or long_s["n"] < MIN_T:
        return "数据不足"
    if long_s["ret_mean"] > 0 and long_s["t"] > T_MIN:
        return "执行T"
    if long_s["ret_mean"] < 0 and long_s["t"] < -T_MIN:
        return "不学T"
    return "观察"


def build(asof, ledgers=None):
    L = ledgers or [x["ledger"] for x in (_jl(ROOT / "scripts" / "tzzb" / "tzzb_ledgers.json", []) or []) if (TZ / x["ledger"]).exists()]
    out = {"date": asof, "generated_by": "scripts/dfcf/paper/t_profile.py", "first_batch": list(FIRST), "mentors": {}}
    for l in L:
        try:
            ev, days = t_events(l, asof)
        except Exception as e:   # noqa: BLE001
            out["mentors"][l] = {"error": str(e)[:200]}
            continue
        if not ev:
            continue
        recent = set(days[-RECENT_DAYS:])
        ls = summarize(ev, len(days))
        rs = summarize([e for e in ev if e["date"] in recent], len(recent))
        out["mentors"][l] = {"long": ls, "recent": rs, "mix": mixed(ls, rs), "verdict": verdict(ls), "n_days": len(days),
                             "window": [days[0], days[-1]] if days else None}
    return out


def load(asof):
    d = _jl(OUT / f"{asof}.json")
    if d:
        return d
    olds = sorted(p for p in OUT.glob("20??-??-??.json") if p.stem < asof) if OUT.exists() else []
    if olds:
        d = _jl(olds[-1]) or {}
        d["stale_from"] = olds[-1].stem
        return d
    return None


def mentor(skill, asof):
    return ((load(asof) or {}).get("mentors") or {}).get(skill)


def _pct(x, nd=1):
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def text_block(skill, asof, sub):
    p = mentor(skill, asof)
    if not p or not p.get("mix"):
        return ""
    m, v = p["mix"], p["verdict"]
    L = [f"- 本导师 T 法画像(t_profile, 长期×近 20 日 α={m.get('alpha', 0):.2f}; 判定=**{v}**): 做T日占 {m['freq']:.0%} 交易日, 共 {p['long']['n']} 笔; "
         f"正T {m['type'].get('正T', 0):.0%} / 倒T {m['type'].get('倒T', 0):.0%}; 有底仓的 T 占 {m['base_share']:.0%}, 规模 P50 = 底仓的 {_pct(m.get('size_p50'), 0).lstrip('+')}; "
         f"成功率 {m['win']:.0%}, 每笔扣费后均值 {_pct(m['ret_mean'], 2)}(长期 t={p['long']['t']})"]
    d, z = p["long"].get("dao") or {}, p["long"].get("zheng") or {}
    if d.get("n"):
        L.append(f"  - 倒T(先卖后买, 用昨日底仓): 首腿中位 {d.get('first_hm_p50')}, 触发时相对昨收 {_pct(d.get('trig_vs_prev_p50'))}/相对均价 {_pct(d.get('trig_vs_avg_p50'))}, "
                 f"卖高接低价差 P50 {_pct(d.get('spread_p50'), 2)}, 成功率 {d.get('win') or 0:.0%}")
    if z.get("n"):
        L.append(f"  - 正T(先买后卖, 需留现金): 首腿中位 {z.get('first_hm_p50')}, 触发时相对昨收 {_pct(z.get('trig_vs_prev_p50'))}/相对均价 {_pct(z.get('trig_vs_avg_p50'))}, "
                 f"低买高卖价差 P50 {_pct(z.get('spread_p50'), 2)}, 成功率 {z.get('win') or 0:.0%}")
    if m.get("why"):
        L.append("  - 为什么T(触发分布, 合计 100%): " + " / ".join(f"{k} {x:.0%}" for k, x in sorted(m["why"].items(), key=lambda kv: -kv[1])))
    if v == "不学T":
        L.append("  - **本导师做T是负期望 → 不学 T, 只学方向和仓位**: 同一只票同一天不做反向回转(今天买过的票不卖、今天卖过的票不买回); 想减就减、想加就加")
    elif v == "执行T" and sub:
        L.append("  - **本时段可按本导师 T 法执行**: 倒T=先卖出昨日底仓的一部分(规模参考上面 P50), 再挂接回买单(价差参考上面 P50); "
                 "正T=先用现金买入, 再卖出等量的昨日底仓(卖的是底仓, T+1 下成立; 无底仓的股票当日不能回转, 转债 T+0 除外)"
                 "——收盘前没接回/没卖出的那一腿按情景处理(可浮动收盘股数)")
    return "\n".join(L)


def check_no_t(skill, asof, acts, book, date_dash):
    """不学T 导师: 本单若与今日已成交形成同票反向回转 → 违规文本"""
    p = mentor(skill, asof)
    if not p or p.get("verdict") != "不学T":
        return None
    tb, ts = set(), set()
    for t in (book or {}).get("trades") or []:
        if str(t.get("id", ""))[:10] == date_dash:
            (tb if t.get("side") == "BUY" else ts).add(str(t.get("code")))
    bad = []
    for a in acts:
        c = str(a.get("code"))
        if a.get("op") in ("卖", "开盘卖") and c in tb:
            bad.append(f"{a.get('name') or c} 今天已买入又卖")
        if a.get("op") == "买" and c in ts:
            bad.append(f"{a.get('name') or c} 今天已卖出又买回")
    buys = {str(a.get("code")) for a in acts if a.get("op") == "买"}
    sells = {str(a.get("code")) for a in acts if a.get("op") in ("卖", "开盘卖")}
    bad += [f"{c} 本单同时挂买和卖" for c in buys & sells]
    if bad:
        return ("本导师做T是负期望(t_profile 判定 不学T: 只学方向和仓位), 不做同票日内回转: " + "; ".join(bad) + "——保留一个方向")
    return None


def selftest():
    fails = []

    def chk(n, c):
        print(("PASS " if c else "FAIL ") + n)
        if not c:
            fails.append(n)

    L = lambda d, hm, op, code, q, px: {"trans_date": f"{d} {hm}:00", "op": op, "stock_code": code, "trans_count": str(q), "trans_price": str(px)}
    days = [f"2026-09-{i:02d}" for i in range(1, 29)]
    legs, dp, nav = [], {}, {}
    for i, d in enumerate(days):
        dp[d.replace("-", "")] = {"list": [{"code": "600001", "position_percent": 0.5}]}
        nav[d] = 100000.0
        if i == 0:
            continue
        # 倒T: 10:00 卖 1000@10.2, 13:30 买回 1000@10.0 (赚); 每 4 天一笔正T 亏
        legs += [L(d, "10:00", "2", "600001", 1000, 10.2), L(d, "13:30", "1", "600001", 1000, 10.0)]
        if i % 4 == 0:
            legs += [L(d, "09:40", "1", "600002", 500, 20.0), L(d, "14:00", "2", "600002", 500, 19.8)]
    rt = {(days[1], "10:00:00", "600001", "卖"): {"mins_from_open": 30, "vs_prev_close": 0.025, "vs_avg_so_far": 0.01}}
    ev, rd = t_events("x", "2026-10-01", legs, dp, nav, rt)
    chk("识别 T 事件数", len(ev) == 27 + 6)
    dao = [e for e in ev if e["type"] == "倒T"]
    chk("倒T 价差 (10.2-10.0)/10.2", abs(dao[0]["spread"] - 0.2 / 10.2) < 1e-4 and dao[0]["ok"])
    chk("倒T 规模=回转额/底仓市值", abs(dao[0]["size"] - (1000 * 10.1) / 50000) < 1e-3)
    chk("触发分类 冲高先卖", dao[0]["why"] == "冲高先卖" and dao[1]["why"] == "无分钟数据")
    chk("正T 亏损判失败", all(not e["ok"] for e in ev if e["type"] == "正T"))
    s = summarize(ev, len(rd))
    chk("汇总: 倒T 占比", abs(s["type"]["倒T"] - 27 / 33) < 1e-3 and s["dao"]["win"] == 1.0)
    chk("为什么T 合计 100%", abs(sum(s["why"].values()) - 1) < 0.01)
    chk("判定 执行T", verdict(s) == "执行T")
    neg = [dict(e, ret=-abs(e["ret"]) - 0.001 * (1 + i % 3)) for i, e in enumerate(ev)]
    chk("负期望=不学T", verdict(summarize(neg, len(rd))) == "不学T")
    chk("样本少=数据不足", verdict(summarize(ev[:5], 5)) == "数据不足")
    ev2, _ = t_events("x", "2026-09-10", legs, dp, nav, rt)
    chk("as-of 不看未来", all(e["date"] < "2026-09-10" for e in ev2))
    m = mixed(s, summarize(ev[-5:], 5))
    chk("混合 α∈(0,1)", 0 < m["alpha"] < 1)
    # check_no_t / text_block 用临时产物
    import tempfile
    global OUT
    old = OUT
    OUT = Path(tempfile.mkdtemp(prefix="tprof_"))
    try:
        (OUT / "2026-10-19.json").write_text(json.dumps({"mentors": {"neg": {"verdict": "不学T", "mix": m, "long": s}, "pos": {"verdict": "执行T", "mix": m, "long": s}}}), encoding="utf-8")
        book = {"trades": [{"id": "2026-10-19-A-neg-001", "side": "BUY", "code": "600001"}]}
        chk("不学T: 今天买过又卖=拦", check_no_t("neg", "2026-10-19", [{"op": "卖", "code": "600001"}], book, "2026-10-19") is not None)
        chk("不学T: 别的票卖=放", check_no_t("neg", "2026-10-19", [{"op": "卖", "code": "600009"}], book, "2026-10-19") is None)
        chk("不学T: 同单买卖同票=拦", check_no_t("neg", "2026-10-19", [{"op": "买", "code": "600003"}, {"op": "卖", "code": "600003"}], {}, "2026-10-19") is not None)
        chk("执行T 导师不拦", check_no_t("pos", "2026-10-19", [{"op": "卖", "code": "600001"}], book, "2026-10-19") is None)
        chk("text 不学T 提示", "不学 T" in text_block("neg", "2026-10-19", True))
        chk("text 执行T 子链提示", "按本导师 T 法执行" in text_block("pos", "2026-10-19", True) and "按本导师 T 法执行" not in text_block("pos", "2026-10-19", False))
    finally:
        OUT = old
    print("SELFTEST " + ("PASS" if not fails else f"FAIL {fails}"))
    return 0 if not fails else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--date", default=_date.today().isoformat())
    ap.add_argument("--skill")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if a.build:
        d = build(a.date)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{a.date}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"t_profile → {OUT / (a.date + '.json')}")
    if a.show or a.build:
        d = load(a.date) or {}
        print("| 导师 | 判定 | T 笔数 | 做T日占比 | 正T/倒T | 有底仓 | 规模P50(底仓) | 成功率 | 每笔均值 | t | 近20日笔数 |\n|---|---|---|---|---|---|---|---|---|---|---|")
        for sk, p in sorted((d.get("mentors") or {}).items(), key=lambda kv: -((kv[1].get("long") or {}).get("n") or 0)):
            if a.skill and sk != a.skill or not p.get("long"):
                continue
            s = p["long"]
            print(f"| {sk} | {p['verdict']} | {s['n']} | {s['freq']:.0%} | {s['type'].get('正T', 0):.0%}/{s['type'].get('倒T', 0):.0%} | {s['base_share']:.0%} | "
                  f"{'—' if s['size_p50'] is None else format(s['size_p50'], '.0%')} | {s['win']:.0%} | {s['ret_mean']:+.2%} | {s['t']} | {(p.get('recent') or {}).get('n', 0)} |")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
