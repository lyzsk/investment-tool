# -*- coding: utf-8 -*-
"""slot_profile.py — 出手时段跟真人走、动态(TODO 三-2c, 10/17 ② agent; 零 token, 只读)

每位导师的"买入时段分布" = 长期全历史 × 近 20 个交易日(时间衰减)的收缩混合, 每天按 as-of 重算(只用 D 之前的数据):
  mix = (1−α)·长期 + α·近期, α = n近期/(n近期+KAPPA)(近期样本少时向长期收缩); 近期权重 = 0.5^(距今交易日/HALF_LIFE)。
  口径: 新开仓买单(当日首笔买入且前一记录日收盘不持有); 新开仓样本 < MIN_NEW 时退回全部买单。同票同日多腿=一张单(取首笔时刻)。
数据:
  tzzb 导师  downloads/tzzb/<ledger>/change_bs_*.json 逐笔腿时分秒(gen_tzzb_profile.load_legs, 只读) + day_positions.json(判新开仓)
  桃哥/卢本圆 md 本人小节「今日操作」时段词(scripts/bilibili/up_ops_stats.parse_day, 只读): 竞价→09:20 开盘→09:32 盘中/上午→10:15 午后→13:45 尾盘→14:50; "未说时段"不计
  趋势天哥/对照组/样本不足者  全体 tzzb 导师合并分布(每人等权)当先验
时段映射: 时刻落在 [slot, 下一 slot) 归该 slot(09:15~09:30 竞价归 0915); 导师 slot 集 = scripts/dfcf/paper/slot_activity.json 里该导师的键(=排程),
  没有就用驱动器的全集。0915 份额 = 首个子链 slot 之前的买单占比; open_share = 09:35 前(竞价+开盘 5 分钟)占比。
0915 开仓预算(tzzb 导师): budget = share_0915 × 典型日新开仓额(近 120 个记录日里有新开仓那天的 新开仓额/前一日总资产 P75) × nav。

产物: scripts/dfcf/paper/slot_profile/<D>.json(--build); 驱动器经 quality_hooks 读(开关 CHAIN_SLOT_BUDGET, 默认 0)。
CLI(scripts/venv/Scripts/python.exe -X utf8):
  slot_profile.py --build [--date 2026-10-19]     生成当日产物(默认=今天; 收盘后跑=给次日用请传次日日期)
  slot_profile.py --show [--date D] [--skill x]
  slot_profile.py --selftest
"""
import argparse
import json
import math
import re
import sys
from collections import defaultdict
from datetime import date as _date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TZ = ROOT / "downloads" / "tzzb"
MD = ROOT / "md"
OUT = Path(__file__).resolve().parent / "slot_profile"
SLOT_ACT = Path(__file__).resolve().parent / "slot_activity.json"
sys.path.insert(0, str(ROOT / "scripts" / "tzzb"))
sys.path.insert(0, str(ROOT / "scripts" / "bilibili"))

RECENT_DAYS = 20
HALF_LIFE = 10.0
KAPPA = 20.0
PRIOR_K = 10.0           # 本人样本向全体先验收缩的伪计数
MIN_NEW = 20
BUDGET_WIN = 120
OPEN_END = "09:35"
UP_SKILLS = {"taoge", "lubenyuan", "qushitiange"}
PRIOR_ONLY = {"qushitiange", "control"}
ALL_SLOTS = ["0915", "0927", "0945", "1000", "1030", "1100", "1127", "1230", "1300", "1400", "1430", "1455"]
TAOGE_SLOTS = ["0915", "0927", "0945", "1000", "1030", "1127", "1230", "1400", "1430", "1455"]
WORD_TIME = {"竞价": "09:20", "开盘": "09:32", "盘中": "10:15", "午后": "13:45", "尾盘": "14:50"}
REPO = re.compile(r"^(204|131|888)")


sys.path.insert(0, str(Path(__file__).resolve().parent))
import slot_rule as SR  # noqa: E402  10/17 A8 开盘阶段归属口径

def _jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def tzzb_ledgers():
    L = _jl(ROOT / "scripts" / "tzzb" / "tzzb_ledgers.json", [])
    return [x["ledger"] for x in L if (TZ / x["ledger"]).exists()]


def slots_of(skill):
    sa = (_jl(SLOT_ACT, {}) or {}).get(skill)
    if sa:
        return sorted(sa)
    return TAOGE_SLOTS if skill == "taoge" else ALL_SLOTS


def slot_of(hm, slots):
    """HH:MM → 所在 slot(时刻 ≥ slot 起点的最后一个); 09:30 前=0915"""
    key = hm.replace(":", "")
    cur = slots[0]
    for s in slots:
        if key >= s:
            cur = s
    return cur


def _hm_ok(hm):
    return "09:15" <= hm <= "15:00"


# ---------------------------------------------------------------- 原料: 每单(日, 时刻, 新开仓?, 金额/前日资产)
def tzzb_orders(ledger, asof):
    from gen_tzzb_profile import load_legs
    legs = [t for t in load_legs(ledger) if t.get("op") in ("1", "2") and t["trans_date"][:10] < asof
            and not REPO.match(str(t.get("stock_code") or ""))]
    dp = _jl(TZ / ledger / "day_positions.json", {}) or {}
    held = {f"{k[:4]}-{k[4:6]}-{k[6:]}": {str(x.get("code")) for x in (v or {}).get("list") or [] if float(x.get("position_percent") or 0) > 0}
            for k, v in dp.items()}
    nav = ((_jl(TZ / ledger / "nav_daily.json", {}) or {}).get("ex_data") or {}).get("index_list") or []
    asset = {f"{x['date'][:4]}-{x['date'][4:6]}-{x['date'][6:]}": float(x.get("asset") or 0) for x in nav}
    rec_days = sorted(set(held) | set(asset) | {t["trans_date"][:10] for t in legs})
    prev_of = {rec_days[i]: rec_days[i - 1] for i in range(1, len(rec_days))}
    qty = defaultdict(float)
    by_day = defaultdict(list)
    for t in sorted(legs, key=lambda t: t["trans_date"]):
        by_day[t["trans_date"][:10]].append(t)
    orders = []
    for d in sorted(by_day):
        pre = {c for c, q in qty.items() if q > 1e-9} | held.get(prev_of.get(d), set())
        first = {}
        for t in by_day[d]:
            c, q = str(t["stock_code"]), float(t.get("trans_count") or 0)
            if t["op"] == "1":
                first.setdefault(c, {"t": t["trans_date"][11:16], "amt": 0.0})
                first[c]["amt"] += q * float(t.get("trans_price") or 0)
                qty[c] += q
            else:
                qty[c] -= q
        a0 = asset.get(prev_of.get(d)) or 0
        for c, e in first.items():
            orders.append({"date": d, "hm": e["t"], "new": c not in pre, "frac": (e["amt"] / a0) if a0 > 0 else None,
                           "p915": SR.p915(ledger, d, c, "B", e["t"])})   # 10/17 A8: 开盘阶段没改单的买单算 0915
    return orders, rec_days


def up_orders(skill, asof):
    import up_ops_stats as U
    head = U.UPS[skill][0]
    orders, days = [], []
    for f in sorted(MD.rglob("20??-??-??.md")):
        if f.stem >= asof:
            continue
        try:
            r = U.parse_day(f.read_text(encoding="utf-8", errors="replace"), head)
        except Exception:   # noqa: BLE001
            r = None
        if r is None:
            continue
        days.append(f.stem)
        for o in r["ops"]:
            if o["side"] == "买" and o.get("time") in WORD_TIME:
                orders.append({"date": f.stem, "hm": WORD_TIME[o["time"]], "new": None, "frac": None, "word": o["time"]})
    return orders, days


# ---------------------------------------------------------------- 分布
def _dist(orders, slots, w=None):
    acc = defaultdict(float)
    tot = 0.0
    for i, o in enumerate(orders):
        if not _hm_ok(o["hm"]):
            continue
        x = w[i] if w else 1.0
        pp = o.get("p915") if "0915" in slots else None   # 10/17 A8(用户定): 开盘阶段成交 没改单=0915 盘前单负责, 改单/盘中追价=归成交时刻的子链
        if pp:
            acc["0915"] += x * pp
            acc[slot_of(o["hm"], slots)] += x * (1 - pp)
        else:
            acc[slot_of(o["hm"], slots)] += x
        tot += x
    return ({s: acc.get(s, 0.0) / tot for s in slots} if tot > 0 else None), tot


def _open_share(orders, w=None):
    num = den = 0.0
    for i, o in enumerate(orders):
        if not _hm_ok(o["hm"]):
            continue
        x = w[i] if w else 1.0
        den += x
        num += x if o["hm"] < OPEN_END else 0.0
    return num / den if den > 0 else None


def mix_profile(orders, rec_days, asof, slots):
    """长期 × 近 20 交易日(衰减) 收缩混合"""
    orders = [o for o in orders if o["date"] < asof]
    new = [o for o in orders if o.get("new")]
    use = new if len(new) >= MIN_NEW else orders
    basis = "新开仓买单" if use is new else "全部买单(新开仓样本不足)"
    days = [d for d in rec_days if d < asof]
    recent = days[-RECENT_DAYS:]
    rank = {d: len(recent) - 1 - i for i, d in enumerate(recent)}
    rec = [o for o in use if o["date"] in rank]
    wr = [0.5 ** (rank[o["date"]] / HALF_LIFE) for o in rec]
    long_d, n_long = _dist(use, slots)
    rec_d, n_rec = _dist(rec, slots, wr)
    alpha = n_rec / (n_rec + KAPPA) if rec_d else 0.0
    if not long_d:
        return None
    mix = {s: (1 - alpha) * long_d[s] + alpha * (rec_d or long_d)[s] for s in slots}
    op_l, op_r = _open_share(use), _open_share(rec, wr)
    open_share = (1 - alpha) * (op_l or 0) + alpha * (op_r if op_r is not None else (op_l or 0))
    return {"slots": {s: round(v, 4) for s, v in mix.items()}, "long": {s: round(v, 4) for s, v in long_d.items()},
            "recent": {s: round(v, 4) for s, v in (rec_d or {}).items()}, "alpha": round(alpha, 3), "n_long": len(use), "n_recent": len(rec),
            "open_share": round(open_share, 4), "basis": basis, "recent_window": [recent[0], recent[-1]] if recent else None}


def map_prior(prior, sl):
    agg = defaultdict(float)
    for s, v in (prior or {}).items():
        agg[slot_of(f"{s[:2]}:{s[2:]}", sl)] += v
    return {s: agg.get(s, 0.0) for s in sl}


def shrink(p, prior, sl):
    """小样本向全体先验收缩: w = n/(n+PRIOR_K)"""
    if not prior or not p.get("slots"):
        return p
    w = p["n_long"] / (p["n_long"] + PRIOR_K)
    pm = map_prior(prior, sl)
    p["own_weight"] = round(w, 3)
    p["slots"] = {s: round(w * p["slots"].get(s, 0.0) + (1 - w) * pm.get(s, 0.0), 4) for s in sl}
    return p


def new_open_budget(orders, rec_days, asof):
    """典型日新开仓额 = 近 BUDGET_WIN 个记录日里有新开仓的日子 Σ新开仓额/前日总资产 的 P75"""
    days = set([d for d in rec_days if d < asof][-BUDGET_WIN:])
    per = defaultdict(float)
    for o in orders:
        if o.get("new") and o["date"] in days and o.get("frac") is not None:
            per[o["date"]] += o["frac"]
    xs = sorted(v for v in per.values() if v > 0)
    if len(xs) < 5:
        return None
    k = (len(xs) - 1) * 0.75
    lo, hi = math.floor(k), math.ceil(k)
    return round(min(1.5, xs[lo] + (xs[hi] - xs[lo]) * (k - lo)), 4), len(xs)


def build(asof):
    out = {"date": asof, "generated_by": "scripts/dfcf/paper/slot_profile.py", "mentors": {}}
    pooled_acc = defaultdict(float)
    n_pool = 0
    raw = {}
    for l in tzzb_ledgers():
        try:
            orders, days = tzzb_orders(l, asof)
        except Exception as e:   # noqa: BLE001
            out["mentors"][l] = {"error": str(e)[:200]}
            continue
        raw[l] = (orders, days)
        pd, _ = _dist(orders, ALL_SLOTS)
        if pd:
            for s, v in pd.items():
                pooled_acc[s] += v
            n_pool += 1
    prior = {s: pooled_acc[s] / n_pool for s in ALL_SLOTS} if n_pool else None
    out["prior"] = {"slots": {s: round(v, 4) for s, v in (prior or {}).items()}, "n_mentors": n_pool,
                    "src": "全体 tzzb 导师买单时段(每人等权)"}
    for l, (orders, days) in raw.items():
        sl = slots_of(l)
        p = mix_profile(orders, days, asof, sl)
        if not p:
            continue
        b = new_open_budget(orders, days, asof)
        p.update(src="tzzb 逐笔腿时分秒", slot_list=sl, budget_frac=b[0] if b else None, budget_days=b[1] if b else 0)
        out["mentors"][l] = shrink(p, prior, sl)
    for up in ("taoge", "lubenyuan"):
        try:
            orders, days = up_orders(up, asof)
        except Exception as e:   # noqa: BLE001
            orders, days = [], []
            out.setdefault("warn", []).append(f"{up}: {e}")
        sl = slots_of(up)
        p = mix_profile(orders, days, asof, sl) if len(orders) >= 5 else None
        if p:
            p.update(src="md「今日操作」时段词(口述+画面 BS 点; 未说时段不计)", slot_list=sl, budget_frac=None)
            out["mentors"][up] = shrink(p, prior, sl)
    for sk in ("qushitiange", "control", "taoge", "lubenyuan"):
        if sk in out["mentors"] and out["mentors"][sk].get("slots"):
            continue
        sl = slots_of(sk)
        if prior:
            out["mentors"][sk] = {"slots": {s: round(v, 4) for s, v in map_prior(prior, sl).items()}, "src": "全体导师先验(本人无时段数据)", "slot_list": sl,
                                  "open_share": None, "alpha": 0.0, "n_long": 0, "n_recent": 0, "budget_frac": None, "prior": True}
    return out


def path_of(asof):
    return OUT / f"{asof}.json"


def load(asof, build_if_missing=False):
    """当日产物; 缺=最近一份更早的(标 stale); 都没有且 build_if_missing=现场生成(不落盘失败也返回)"""
    f = path_of(asof)
    d = _jl(f)
    if d:
        return d
    olds = sorted(p for p in OUT.glob("20??-??-??.json") if p.stem < asof) if OUT.exists() else []
    if olds:
        d = _jl(olds[-1])
        if d:
            d["stale_from"] = olds[-1].stem
            return d
    if build_if_missing:
        d = build(asof)
        try:
            OUT.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
        return d
    return None


def mentor(skill, asof):
    d = load(asof) or {}
    return (d.get("mentors") or {}).get(skill)


def next_slot_after(slot, sl):
    later = [s for s in sl if s > slot]
    return later[0] if later else None


def top_slots(p, k=3, exclude=("0915",)):
    return [s for s, v in sorted((p.get("slots") or {}).items(), key=lambda kv: -kv[1]) if s not in exclude and v > 0.05][:k]


def text_block(skill, asof, slot, nav=None, sub=False):
    p = mentor(skill, asof)
    if not p or not p.get("slots"):
        return ""
    sl = p.get("slot_list") or slots_of(skill)
    dist = " / ".join(f"{s} {v:.0%}" for s, v in p["slots"].items() if v >= 0.005)
    L = [f"- 本导师买入时段分布({p.get('src')}; 长期×近 20 日加权 α={p.get('alpha', 0):.2f}, 样本 {p.get('n_long', 0)} 单/近期 {p.get('n_recent', 0)} 单): {dist}"
         + (f"; 其中 09:35 前(竞价+开盘 5 分钟) {p['open_share']:.0%}" if p.get("open_share") is not None else "")]
    if not sub and slot == "0915":
        ts = top_slots(p)
        nxt = next_slot_after("0915", sl)
        share = float(p["slots"].get("0915") or 0)
        if p.get("budget_frac") and nav:
            bud = share * p["budget_frac"] * nav
            L.append(f"- **0915 开仓预算**: 本导师历史上 0915 窗口(到 {nxt[:2] + ':' + nxt[2:] if nxt else '收盘'})出手的份额 {share:.0%} × 典型日新开仓额 {p['budget_frac']:.0%} nav"
                     f" = **{bud:.0f} 元**: 本次新开仓里立即生效(不带 not_before 或 not_before 早于 {nxt[:2] + ':' + nxt[2:] if nxt else '收盘'})的买单合计不超过它(1 手不受限); "
                     f"其余新开仓写 not_before 挂到本导师常出手的时段({'、'.join(s[:2] + ':' + s[2:] for s in ts) or '盘中'}), 或留给盘中子链再决定")
        else:
            L.append(f"- 0915 窗口出手份额 {share:.0%}; 本导师常出手时段: {'、'.join(s[:2] + ':' + s[2:] for s in ts) or '—'}"
                     "(新开仓不必都在开盘挂出, 可写 not_before 或留给盘中子链)")
    elif sub:
        share = float(p["slots"].get(slot) or 0)
        L.append(f"- 本时段 {slot[:2]}:{slot[2:]} 是本导师 {share:.0%} 买单出手的窗口" + ("(很少在这时出手: 没有强理由就不新开仓)" if share < 0.05 else ""))
    return "\n".join(L)


def check_0915(skill, asof, acts, nav, lot_amt=None):
    """0915 主链: 立即生效的新开仓买单金额 ≤ 预算。返回 (违规文本|None, 统计)。acts=v06 校验后的 actions(带 _px/_nb); 新开仓判定由调用方给 a['_new']"""
    p = mentor(skill, asof)
    if not p or not p.get("budget_frac") or not nav:
        return None, {"skip": "无预算(非 tzzb 或样本不足)"}
    sl = p.get("slot_list") or slots_of(skill)
    nxt = next_slot_after("0915", sl)
    nxt_hm = f"{nxt[:2]}:{nxt[2:]}" if nxt else "15:00"
    share = float(p["slots"].get("0915") or 0)
    bud = share * p["budget_frac"] * nav
    now = [a for a in acts if a.get("op") == "买" and a.get("_new") and (not a.get("_nb") or a["_nb"] < nxt_hm)]
    amt = sum(float(a.get("_px") or 0) * int(a.get("qty") or 0) for a in now)
    S = {"budget": round(bud, 2), "share": share, "budget_frac": p["budget_frac"], "now_amt": round(amt, 2), "n_now": len(now), "next": nxt_hm}
    one_lot = len(now) == 1 and int(now[0].get("qty") or 0) <= 100
    if amt > bud and not one_lot:
        ts = top_slots(p)
        return (f"0915 开仓预算: 立即生效的新开仓买单 {amt:.0f} 元 > 预算 {bud:.0f} 元(本导师 0915 窗口出手份额 {share:.0%} × 典型日新开仓额 {p['budget_frac']:.0%} nav)——"
                f"把超出部分改成 not_before 挂到 {('、'.join(s[:2] + ':' + s[2:] for s in ts)) or nxt_hm}(本导师常出手时段), 或减量/留给盘中子链"), S
    return None, S


# ---------------------------------------------------------------- CLI
def selftest():
    fails = []

    def chk(n, c):
        print(("PASS " if c else "FAIL ") + n)
        if not c:
            fails.append(n)

    sl = ["0915", "1000", "1300", "1455"]
    chk("slot_of 竞价归 0915", slot_of("09:25", sl) == "0915" and slot_of("09:59", sl) == "0915" and slot_of("10:00", sl) == "1000")
    chk("slot_of 午后", slot_of("14:10", sl) == "1300" and slot_of("14:56", sl) == "1455")
    days = [f"2026-09-{i:02d}" for i in range(1, 31)]
    # 长期: 全在 09:31(0915 窗); 近 20 日: 全在 13:10 → 混合后 1300 份额 >0 且 <近期
    orders = [{"date": d, "hm": "09:31", "new": True, "frac": 0.2} for d in days[:10] for _ in range(3)]
    orders += [{"date": d, "hm": "13:10", "new": True, "frac": 0.1} for d in days[10:]]
    p = mix_profile(orders, days, "2026-10-01", sl)
    chk("长期×近期混合: 1300 份额在 (0,1)", 0 < p["slots"]["1300"] < 1 and p["recent"]["1300"] == 1.0)
    chk("α 随近期样本收缩", 0 < p["alpha"] < 1)
    chk("open_share 只算 09:35 前", 0 < p["open_share"] < 1)
    p2 = mix_profile(orders, days, "2026-09-11", sl)
    chk("as-of 不看未来(9/11 前只有早盘单)", p2["slots"]["0915"] == 1.0)
    b = new_open_budget(orders, days, "2026-10-01")
    chk("预算 P75", b and abs(b[0] - 0.6) < 1e-9)
    few = [dict(o, new=False) for o in orders]
    chk("新开仓不足退全部买单", "全部买单" in mix_profile(few, days, "2026-10-01", sl)["basis"])
    # check_0915 用临时产物
    import tempfile
    global OUT
    old = OUT
    OUT = Path(tempfile.mkdtemp(prefix="slotprof_"))
    try:
        (OUT / "2026-10-19.json").write_text(json.dumps({"mentors": {"x": {"slots": {"0915": 0.25, "1000": 0.5, "1300": 0.25},
                                                                          "slot_list": ["0915", "1000", "1300"], "budget_frac": 0.4}}}), encoding="utf-8")
        A = lambda px, q, nb=None, new=True: {"op": "买", "_px": px, "qty": q, "_nb": nb, "_new": new}
        e, S = check_0915("x", "2026-10-19", [A(10, 1000)], 100000)
        chk("0915 预算 10000 元: 买 1 万放行", e is None and abs(S["budget"] - 10000) < 1e-6)
        e, S = check_0915("x", "2026-10-19", [A(10, 1000), A(10, 500)], 100000)
        chk("超预算=拦", e is not None and "not_before" in e)
        e, S = check_0915("x", "2026-10-19", [A(10, 1000), A(10, 3000, "10:30")], 100000)
        chk("not_before 晚于下一 slot 不计", e is None)
        e, S = check_0915("x", "2026-10-19", [A(10, 1000), A(10, 3000, "09:45")], 100000)
        chk("not_before 早于下一 slot 照计", e is not None)
        e, _ = check_0915("x", "2026-10-19", [A(200, 100)], 100000)
        chk("单只 1 手不受限", e is None)
        e, _ = check_0915("x", "2026-10-19", [A(10, 3000, new=False)], 100000)
        chk("加仓不算新开仓", e is None)
        chk("text_block 0915 含预算", "0915 开仓预算" in text_block("x", "2026-10-19", "0915", 100000))
        chk("text_block 子链含本时段", "10:00" in text_block("x", "2026-10-19", "1000", 100000, sub=True))
        chk("缺当日产物回退旧产物", (load("2026-10-20") or {}).get("stale_from") == "2026-10-19")
        chk("无导师=空串", text_block("nobody", "2026-10-19", "0915", 1e5) == "")
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
        path_of(a.date).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"slot_profile → {path_of(a.date)} ({len(d['mentors'])} 位)")
    if a.show or a.build:
        d = load(a.date) or {}
        for sk, p in sorted((d.get("mentors") or {}).items()):
            if a.skill and sk != a.skill or not p.get("slots"):
                continue
            dist = " ".join(f"{s}:{v:.0%}" for s, v in p["slots"].items() if v >= 0.005)
            print(f"{sk:24s} α={p.get('alpha', 0):.2f} n={p.get('n_long', 0)}/{p.get('n_recent', 0)} open≤09:35={p.get('open_share') if p.get('open_share') is None else format(p['open_share'], '.0%')} "
                  f"budget={p.get('budget_frac')} | {dist} | {p.get('src')}")
        return
    if not a.build:
        ap.print_help()


if __name__ == "__main__":
    main()
