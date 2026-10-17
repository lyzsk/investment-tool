# -*- coding: utf-8 -*-
"""order_inference.py — 从"只有成交 + 分钟线"反推导师的挂单行为(10/16 晚用户提出; 零 token, 只读)

问题: 同花顺投资账本只给成交腿(时分秒/价/量), 挂了没成交的单、盯盘撤单改单看不到 → 直接拿成交价分布当挂价分布有幸存者偏差
     (挂得深的低吸单没成交就不出现 → 低吸深度被低估)。
方法(详见 docs/research/order_inference_20261016.md):
  ① 成交方式分类(每笔一组概率, 合计 100%): 集合竞价 / 排板 / 被动限价成交 / 主动追价 / 改单追上 / 其他(证据不足)
     证据=成交价 vs 上一分钟收盘(tick test, Lee-Ready 1991 思路)、在成交分钟 K 内的位置、是否创近 10 分钟新低(买)/新高(卖)、
     前 3 分钟是否已有价格穿过他的价(穿过=他那时还没挂这个价)、近 15 分钟是否曾明显更便宜(追价语境)
  ② 被动单的"挂单时刻窗口": 上一次价格穿过成交价(买: 最低≤价-1 tick)之后才可能挂上这个价 → 挂单存续上界 = 成交分钟 - 穿价分钟;
     挂单时刻 τ0 在窗口内, 挂价深度 d = (τ0 时价格 - 挂价)/τ0 时价格(买; 卖取反)。τ0 规则用用户实盘真值选(见 --validate)
  ③ 去偏: 假想挂单首达概率 π(d) (Handa-Schwartz 1996 / Lo-MacKinlay-Zhang 2002 的 first-passage 口径, 按当日波动 σ√H 归一),
     被动成交按 1/π 加权(Horvitz-Thompson / Vardi 1985 选择偏差 NPMLE 的已知权重形式), 得"想挂的单"的深度分布; π 下截 0.05(权重≤20)
  ④ 真值验证: 用户牧原实盘(挂单表/委托截图/会话报单 = 既知挂单又知成交) — 只输出聚合指标, 明细只落 scripts/dfcf/snapshots/order_inference_val/
产物: skills/<导师>-skill/persona/orders_inferred.json(逐导师) + docs/research/order_inference_20261016.md(报告, 只含聚合数字)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/order_inference.py [--fetch-user] [--validate] [--mentors] [--report] [--ledger X] [--H 60]
   (都不给=validate+mentors+report; --fetch-user 用通达信补用户牧原 10/09 前的分钟线, 请求间隔 0.15~0.35s 随机)
隐私: 用户实盘明细只读 scripts/dfcf/snapshots/, 中间明细只写 scripts/dfcf/snapshots/order_inference_val/; docs/ 与 skills/ 只写聚合
"""
import argparse, json, math, random, re, sys, time
from collections import defaultdict, Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "market"))
sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
sys.path.insert(0, str(ROOT / "scripts" / "tzzb"))
import collect_minute as cm                                    # noqa: E402  (只用 label_of / 通达信取数函数)
from backfill_fill_minutes import cache_load, limit_pct, daily_map   # noqa: E402  (只读)
from gen_tzzb_profile import load_legs                         # noqa: E402  (只读 json)

SKILLS = ROOT / "skills"
SNAP = ROOT / "scripts" / "dfcf" / "snapshots"
VAL = SNAP / "order_inference_val"
MARKET = ROOT / "downloads" / "market"
REPORT = ROOT / "docs" / "research" / "order_inference_20261016.md"
USER_CODE, USER_SYM = "002714", "sz002714"
USER_DAYS = ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"]
MODES = ["集合竞价", "排板", "被动限价", "主动追价", "改单追上", "其他"]
H_DEFAULT = 60          # 假想挂单存续(分钟 bar 数), 敏感性见报告
PI_MIN = 0.05           # π 下截 → 权重上限 20
Q_TOUCH = 0.5           # 价格恰好触到挂价(未穿)时按 q 概率算成交(排队); --validate 用真值估
ALPHAS = (0.0, 0.25, 0.5, 0.75, 1.0)   # 回火 IPW: 权重 (1/π)^α, α=0 原始, α=1 全量 IPW; α 由用户真值选
MERGE_SEC = 300         # 同向同价 5 分钟内的成交腿视为同一张单的分笔成交


# ---------------- 基础 ----------------
def sec(t):
    return int(t[0:2]) * 3600 + int(t[3:5]) * 60 + int(t[6:8])


def tick_of(code):
    c = str(code)
    return 0.001 if c.startswith(("51", "15", "56", "58", "16", "50", "52")) else 0.01


class Bars:
    def __init__(self, rows):
        rows = sorted(rows, key=lambda b: b["barTime"])
        self.labs = [b["barTime"][11:16] for b in rows]
        self.o = np.array([float(b["open"]) for b in rows])
        self.h = np.array([float(b["high"]) for b in rows])
        self.l = np.array([float(b["low"]) for b in rows])
        self.c = np.array([float(b["close"]) for b in rows])
        self.pos = {lab: i for i, lab in enumerate(self.labs)}
        r = np.abs(np.diff(np.log(np.maximum(self.c, 1e-9)))) if len(self.c) > 1 else np.array([0.0])
        self.sigma = float(max(np.mean(r) if len(r) else 0.0, 2e-4))   # 当日 1 分钟平均绝对对数收益(归一用)
        self.n = len(rows)

    def idx(self, t):
        """成交时刻 HH:MM:SS → 所在分钟 bar 下标(口径同 collect_minute.label_of)"""
        lab = cm.label_of(t[:5])
        return self.pos.get(lab) if lab else None

    def ref_idx(self, t):
        """时刻 t 时"最后一根已走完的 bar"下标; 盘前(<09:30)=0(开盘竞价 bar)"""
        if t < "09:30:00":
            return 0
        m = self.idx(t)
        return max(0, (m if m is not None else self.n) - 1)


def align(B, t, px, tick):
    """成交所在 bar: 先按时刻取, 价格不在该 bar [低,高] 内则在前后 2 根里找(券商时钟 vs 通达信逐笔分钟戳有 ±1 分钟错位,
    用户实盘 89% / 导师抽样 96% 落在本 bar); 都对不上 → None(记'其他')"""
    m = B.idx(t) if B else None
    if m is None:
        return None
    for k in (m, m - 1, m + 1, m - 2, m + 2):
        if 1 <= k < B.n and B.l[k] - tick / 2 - 1e-9 <= px <= B.h[k] + tick / 2 + 1e-9:
            return k
    return None


def mirror(B, side):
    """卖单镜像成买单比较(价格取负): 低吸买的'最低'↔卖单的'最高'"""
    if side == "B":
        return B.o, B.h, B.l, B.c
    return -B.o, -B.l, -B.h, -B.c


# ---------------- ① 成交方式分类 ----------------
def classify(side, t, px, B, up, dn, tick, earlier_better=False):
    """返回 (probs dict, diag dict); earlier_better=同日同票同向更早有更便宜(买)/更贵(卖)的成交(另一张单)"""
    p = {k: 0.0 for k in MODES}
    if t < "09:30:00":
        p["集合竞价"] = 1.0
        return p, {"why": "开盘集合竞价"}
    if t >= "14:57:00":
        p["集合竞价"] = 1.0
        return p, {"why": "收盘集合竞价"}
    if side == "B" and up and px >= up - tick / 2:
        p["排板"] = 0.95; p["其他"] = 0.05
        return p, {"why": "涨停价买入"}
    if side == "S" and dn and px <= dn + tick / 2:
        p["排板"] = 0.95; p["其他"] = 0.05
        return p, {"why": "跌停价卖出"}
    if not B:
        p["其他"] = 1.0
        return p, {"why": "无分钟线"}
    m = align(B, t, px, tick)
    if m is None:
        p["其他"] = 1.0
        return p, {"why": "成交价与分钟线对不上(时钟错位/均价腿)"}
    o, h, l, c = mirror(B, side)
    x = px if side == "B" else -px
    c0 = c[m - 1]
    tu = int(round((x - c0) / tick))
    rng = h[m] - l[m]
    r = (x - l[m]) / rng if rng > tick / 2 else None
    lo10 = l[max(1, m - 10):m]
    new_low = bool(len(lo10) and x <= lo10.min() + 1e-9)
    tt3 = bool(np.any(l[max(0, m - 3):m] <= x - tick + 1e-9))
    mom3 = c0 - c[max(0, m - 4)]
    sp = sa = 0.0
    if tu < 0:
        sp += 2.0
    elif tu > 0:
        sa += 2.0
    else:
        sp += 0.3; sa += 0.3
    if r is not None:
        if r <= 1 / 3:
            sp += 1.0
        elif r >= 2 / 3:
            sa += 1.0
    if new_low:
        sp += 1.0
    if tt3:
        sa += 1.0; sp -= 1.0
    if mom3 > tick / 2 and tu >= 0:
        sa += 0.5
    if mom3 < -tick / 2 and tu <= 0:
        sp += 0.5
    so = 1.5
    e = np.exp([sp, sa, so])
    e = e / e.sum()
    chase_ctx = bool(np.any(l[max(0, m - 15):m] <= x - abs(px) * 0.004))
    share_re = 0.4 if earlier_better else (0.25 if chase_ctx else 0.1)    # 先验拆分(不可识别: 用户真值上 P(改单) 对已知改单单无区分力, 见报告)
    p["被动限价"] = float(e[0])
    p["改单追上"] = float(e[1] * share_re)
    p["主动追价"] = float(e[1] * (1 - share_re))
    p["其他"] = float(e[2])
    return p, {"tu": tu, "r": None if r is None else round(float(r), 2), "new_low": new_low, "tt3": tt3, "chase_ctx": chase_ctx}


# ---------------- ② 挂单窗口与深度 ----------------
def window(side, t, px, B, tick):
    """被动单可能的挂单区间 [start, m-1](bar 下标): start=上次价格穿过成交价之后; None=无分钟线"""
    m = align(B, t, px, tick) if B else None
    if m is None:
        return None
    o, h, l, c = mirror(B, side)
    x = px if side == "B" else -px
    hit = np.where(l[:m] <= x - tick + 1e-9)[0]
    start = int(hit[-1]) + 1 if len(hit) else 0
    return start, m


def depth_at(side, px, P):
    return (P - px) / P if side == "B" else (px - P) / P


TAU_RULES = ["naive", "lag5", "lag15", "lag30", "lag60", "mid", "early", "max"]


def tau0(rule, start, m, side, B):
    """按规则取挂单时刻 bar 下标(在 [start, m-1] 内)"""
    lo, hi = start, m - 1
    if hi < lo:
        lo = hi
    if rule == "naive":
        return hi
    if rule.startswith("lag"):
        return max(lo, m - int(rule[3:]))
    if rule == "mid":
        return (lo + hi) // 2
    if rule == "early":
        return max(lo, m - 240)
    if rule == "max":   # 深度上界: 窗口内对他最有利的价(买=最高收盘)
        seg = B.c[lo:hi + 1]
        return lo + int(np.argmax(seg) if side == "B" else np.argmin(seg))
    raise ValueError(rule)


# ---------------- ③ 首达概率 π ----------------
class FillCurve:
    """假想挂单首达: 对一批(票,日)分钟路径, 每 3 根 bar 放一张假想单, 记 H 根内最有利价能到的深度(穿价/触价), 按 σ√H 归一"""

    def __init__(self, bars_list, H=H_DEFAULT, step=3):
        self.H = H
        u = {"B": ([], []), "S": ([], [])}
        for B, tick in bars_list:
            if B.n < 20:
                continue
            sc = B.sigma * math.sqrt(H)
            for i in range(0, B.n - 2, step):
                P = B.c[i]
                if P <= 0:
                    continue
                fl = B.l[i + 1:i + 1 + H]
                fh = B.h[i + 1:i + 1 + H]
                if not len(fl):
                    continue
                mn, mx = fl.min(), fh.max()
                u["B"][0].append(((P - mn - tick) / P) / sc); u["B"][1].append(((P - mn) / P) / sc)
                u["S"][0].append(((mx - tick - P) / P) / sc); u["S"][1].append(((mx - P) / P) / sc)
        self.u = {s: (np.sort(np.array(a)), np.sort(np.array(b))) for s, (a, b) in u.items()}
        self.N = {s: len(self.u[s][0]) for s in u}

    def pi(self, side, d, sc, q=Q_TOUCH):
        N = self.N[side]
        if not N:
            return 1.0
        z = d / sc
        tt, to = self.u[side]
        n_tt = N - np.searchsorted(tt, z - 1e-12, side="left")
        n_to = N - np.searchsorted(to, z - 1e-12, side="left")
        return float((n_tt + q * max(0, n_to - n_tt)) / N)


def wq(vals, ws, ps=(0.25, 0.5, 0.75, 0.9)):
    """加权分位"""
    if not len(vals):
        return None
    v = np.asarray(vals, float); w = np.asarray(ws, float)
    o = np.argsort(v); v, w = v[o], w[o]
    cw = np.cumsum(w) / w.sum()
    return {f"p{int(p * 100)}": round(float(v[min(len(v) - 1, np.searchsorted(cw, p))]), 4) for p in ps}


def wmean(vals, ws):
    return round(float(np.average(vals, weights=ws)), 4) if len(vals) and sum(ws) > 0 else None


# ---------------- 用户实盘(隐私) ----------------
def user_bars(day):
    f = MARKET / day / "kline_minute.jsonl"
    rows = []
    if f.exists():
        for ln in f.read_text(encoding="utf-8").splitlines():
            if USER_SYM in ln:
                r = json.loads(ln)
                if r["symbol"] == USER_SYM:
                    rows.append(r)
    if not rows:
        g = VAL / "minutes_002714.jsonl"
        if g.exists():
            rows = [json.loads(x) for x in g.read_text(encoding="utf-8").splitlines() if x.strip()]
            rows = [r for r in rows if r["tradeDate"] == day]
    return Bars(rows) if rows else None


def fetch_user():
    from kline_db import db
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("select trade_date, cast(open as double), cast(high as double), cast(low as double), cast(close as double), cast(pre_close as double) "
                    "from kline_day where symbol=%s and trade_date>=%s and trade_date<=%s", (USER_SYM, USER_DAYS[0], USER_DAYS[-1]))
        dm = {str(r[0])[:10]: {"open": r[1], "high": r[2], "low": r[3], "close": r[4], "preClose": r[5]} for r in cur.fetchall()}
    finally:
        conn.close()
    VAL.mkdir(parents=True, exist_ok=True)
    g = VAL / "minutes_002714.jsonl"
    have = set()
    if g.exists():
        have = {json.loads(x)["tradeDate"] for x in g.read_text(encoding="utf-8").splitlines() if x.strip()}
    todo = [d for d in USER_DAYS if d not in have and not (MARKET / d / "kline_minute.jsonl").exists()]
    with g.open("a", encoding="utf-8") as fh:
        for d in todo:
            ymd = int(d.replace("-", ""))
            api = cm.connect(ymd)
            try:
                ticks = cm.all_ticks(api, USER_SYM, ymd)
                ok = ticks and cm.ticks_ok(ticks, dm[d], 1.0)
                b = cm.bars_from_ticks(USER_SYM, d, ticks, 100, dm[d]["preClose"]) if ok else []
            finally:
                api.disconnect()
            print(f"{d}: 逐笔 {len(ticks) if ticks else 0} → 分钟 {len(b)} {'OK' if ok else '校验不过/缺'}")
            for r in b:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            time.sleep(random.uniform(0.15, 0.35))


def parse_user_fills():
    """成交 txt(多种手贴格式) → [{date,t,side,qty,px,oid}]; 委托编号另从会话原文 raw_fill_pastes.txt 补"""
    out = []
    for d in USER_DAYS:
        fs = sorted(SNAP.glob(f"{d}_成交_*.txt"))[:1]   # 每天一个 txt
        for f in fs:
            for ln in f.read_text(encoding="utf-8").splitlines():
                tk = ln.split()
                if not tk:
                    continue
                t = next((x for x in tk[:2] if re.fullmatch(r"\d\d:\d\d:\d\d", x)), None)
                if not t:
                    continue
                side = qty = px = oid = None
                for i, x in enumerate(tk):
                    if x in ("证券买入", "证券卖出", "买", "卖"):
                        side = "B" if "买" in x else "S"
                        q = tk[i + 1].split("→")[-1]
                        qty, px = int(q), float(tk[i + 2])
                        if x.startswith("证券") and "002714" in tk:
                            nums = tk[i + 1:]
                            if len(nums) >= 11 and re.fullmatch(r"\d{4}-\d\d-\d\d", tk[0]):
                                oid = nums[9]                 # 9/28 全列格式: 量 均价 额 佣金 其他 印花 过户 资金余额 股份余额 委托编号
                            elif len(nums) >= 6 and len(nums[4]) >= 12:
                                oid = nums[5]                 # 成交编号 委托编号
                        break
                if side is None or ("002714" not in tk and not re.match(r"^\d\d:\d\d:\d\d\s+(买|卖)", ln)):
                    continue
                out.append({"date": d, "t": t, "side": side, "qty": qty, "px": px, "oid": int(oid) if oid else None})
    raw = VAL / "raw_fill_pastes.txt"
    if raw.exists():   # 会话原文里的委托编号(9/30, 10/08, 10/13 的 txt 没有编号)
        cur = None
        for ln in raw.read_text(encoding="utf-8").splitlines():
            if ln.startswith("#### "):
                cur = None
                continue
            tk = ln.split()
            if "002714" in tk and len(tk) >= 9 and re.fullmatch(r"\d\d:\d\d:\d\d", tk[0]) and tk[3] in ("证券买入", "证券卖出"):
                t, side, qty, px, oid = tk[0], "B" if "买" in tk[3] else "S", int(tk[4]), float(tk[5]), int(tk[8])
                for x in out:
                    if x["oid"] is None and x["t"] == t and x["side"] == side and x["qty"] == qty and abs(x["px"] - px) < 1e-6:
                        x["oid"] = oid
                        break
            # GC001 等其他品种的委托编号也有用(同一券商流水号, 用于挂单时刻上界)
            if len(tk) >= 9 and re.fullmatch(r"\d\d:\d\d:\d\d", tk[0]) and tk[1] == "204001":
                pass
    return sorted(out, key=lambda x: (x["date"], x["t"], x["side"], x["px"]))   # 同秒同价同量的两腿是真实分笔(10/12), 不去重


def merge_orders(fills, key=lambda x: (x["date"], x["side"])):
    """同日同向同价 MERGE_SEC 内的连续成交腿 → 一张单(分笔成交); 有委托编号时按编号合并"""
    g = defaultdict(list)
    for x in fills:
        g[key(x)].append(x)
    orders = []
    for k, xs in g.items():
        xs.sort(key=lambda x: x["t"])
        cur = []
        for x in xs:
            if cur and ((x.get("oid") and x.get("oid") == cur[-1].get("oid")) or
                        (not (x.get("oid") and cur[-1].get("oid")) and abs(x["px"] - cur[0]["px"]) < 1e-6 and sec(x["t"]) - sec(cur[-1]["t"]) <= MERGE_SEC)):
                cur.append(x)
            else:
                if cur:
                    orders.append(cur)
                cur = [x]
        if cur:
            orders.append(cur)
    res = []
    for legs in orders:
        q = sum(x["qty"] for x in legs)
        res.append({**legs[0], "qty": q, "vwap": sum(x["qty"] * x["px"] for x in legs) / q, "nlegs": len(legs),
                    "n_px": len({x["px"] for x in legs}), "legs": legs})
    return sorted(res, key=lambda x: (x["date"], x["t"]))


def build_truth(orders):
    """真值: 挂单时刻(on)/成交方式/改单 → 每张成交单打标; 另出"没成交的挂单"清单"""
    T = json.loads((VAL / "truth_user.json").read_text(encoding="utf-8"))["days"]
    unfilled = []
    by_day = defaultdict(list)
    for o in orders:
        by_day[o["date"]].append(o)
    for d, os_ in by_day.items():
        # 委托编号上界: 编号单调 → 挂单时刻 ≤ 任一更大编号单的成交时刻
        ids = [(o["oid"], sec(o["t"])) for o in os_ if o.get("oid")]
        for o in os_:
            o["truth"] = {"mode": None, "on": None, "on_exact": False, "reprice_from": None}
            tr = o["truth"]
            if o["t"] < "09:30:00" or o["t"] >= "14:57:00":
                tr["mode"] = "集合竞价"
            if o.get("oid"):
                ub = min([s for i, s in ids if i >= o["oid"] and i != o["oid"]] + [sec(o["t"])])
                o["oid_ub"] = ub
                if o["oid"] < 60000 and o["t"] >= "09:30:00" and tr["mode"] is None:
                    tr.update(mode="被动限价", on="09:25:00")               # 盘前委托, 开盘后才成交 = 挂着等
                elif tr["mode"] is None and ub <= sec(o["t"]) - 60:
                    tr.update(mode="被动限价")
                if o["n_px"] > 1 and tr["mode"] is None:
                    tr["mode"] = "主动追价"                                 # 同一委托多个成交价 = 吃了多档 = 可立即成交的单
        day = T.get(d)
        if not day:
            continue
        sight = []   # (sec, side, px, exact)
        for side, px, t in day.get("placed", []):
            sight.append((sec(t), side, float(px), True, t))
        for t, s in day.get("seen", []):
            for tok in s.split():
                sight.append((sec(t), tok[0], float(tok[1:]), False, t))
        sight.sort()
        used = set()
        last_fill = defaultdict(lambda: -1)
        for o in sorted(os_, key=lambda x: x["t"]):
            ft = sec(o["t"])
            k = (o["side"], round(o["px"], 2))
            cand = [i for i, s in enumerate(sight) if (s[1], round(s[2], 2)) == k and last_fill[k] < s[0] <= ft and i not in used]
            if cand:
                first = sight[cand[0]]
                for i in cand:
                    used.add(i)
                tr = o["truth"]
                tr["on"] = first[4]; tr["on_exact"] = first[3]
                if tr["mode"] in (None, "被动限价"):
                    if first[3] and ft - first[0] <= 5:
                        tr["mode"] = "主动追价"
                    elif ft - first[0] >= 20:
                        tr["mode"] = "被动限价"
            last_fill[k] = ft
            for side, a, b, t in day.get("reprice", []):
                if side == o["side"] and abs(b - o["px"]) < 1e-6 and sec(t) <= ft + 1 and o["truth"]["reprice_from"] is None:
                    o["truth"]["reprice_from"] = a
        # 没成交的挂单: 未被成交消费的目击, 同向同价连续目击并成一张
        grp = defaultdict(list)
        for i, s in enumerate(sight):
            if i not in used:
                grp[(s[1], round(s[2], 2))].append(s)
        for (side, px), ss in grp.items():
            ss.sort()
            chunk = [ss[0]]
            for s in ss[1:]:
                if s[0] - chunk[-1][0] > 3 * 3600:
                    unfilled.append({"date": d, "side": side, "px": px, "on": chunk[0][4], "on_exact": chunk[0][3], "last": chunk[-1][4]})
                    chunk = [s]
                else:
                    chunk.append(s)
            unfilled.append({"date": d, "side": side, "px": px, "on": chunk[0][4], "on_exact": chunk[0][3], "last": chunk[-1][4]})
    return orders, unfilled


def path_check(side, px, B, on, until, tick):
    """挂单从 on 到 until 期间, 分钟路径是否穿价/触价(买: 最低 ≤ 价-1tick / ≤ 价)"""
    i0 = B.ref_idx(on) + 1 if on >= "09:30:00" else 1
    if on < "09:30:00":
        i0 = 0
    m = B.idx(until) if until >= "09:30:00" else 0
    if m is None:
        m = B.n - 1
    seg = slice(i0, m + 1)
    if side == "B":
        lo = B.l[seg].min() if m >= i0 else 9e9
        return bool(lo <= px - tick + 1e-9), bool(lo <= px + 1e-9)
    hi = B.h[seg].max() if m >= i0 else -9e9
    return bool(hi >= px + tick - 1e-9), bool(hi >= px - 1e-9)


def validate(H=H_DEFAULT):
    fills = parse_user_fills()
    orders = merge_orders(fills)
    orders, unfilled = build_truth(orders)
    bars = {d: user_bars(d) for d in USER_DAYS}
    tick = 0.01
    pcs = {}
    from kline_db import db
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("select trade_date, cast(pre_close as double) from kline_day where symbol=%s and trade_date>=%s and trade_date<=%s", (USER_SYM, USER_DAYS[0], USER_DAYS[-1]))
        pcs = {str(r[0])[:10]: r[1] for r in cur.fetchall()}
    finally:
        conn.close()
    S = {"n_days": len(USER_DAYS), "n_days_with_bars": sum(1 for b in bars.values() if b), "n_fill_legs": len(fills), "n_orders_filled": len(orders),
         "n_unfilled_orders_known": len(unfilled)}
    # ① 成交方式
    rows = []
    for o in orders:
        B = bars.get(o["date"])
        pc = pcs.get(o["date"])
        up = round(pc * 1.1 + 1e-9, 2) if pc else None
        dn = round(pc * 0.9 + 1e-9, 2) if pc else None
        earlier = any(x["date"] == o["date"] and x["side"] == o["side"] and x["t"] < o["t"] and sec(o["t"]) - sec(x["t"]) <= 1800 and
                      ((x["px"] < o["px"]) if o["side"] == "B" else (x["px"] > o["px"])) for x in orders if x is not o)
        p, dg = classify(o["side"], o["t"], o["px"], B, up, dn, tick, earlier)
        o["pred"] = p; o["diag"] = dg
        w = window(o["side"], o["t"], o["px"], B, tick) if B else None
        o["win"] = w
        rows.append(o)
    lab = [o for o in rows if o["truth"]["mode"] in ("被动限价", "主动追价")]
    def argm(p):
        q = {"被动限价": p["被动限价"], "主动": p["主动追价"] + p["改单追上"], "其他": p["其他"]}
        return max(q, key=q.get)
    cm_ = Counter()
    for o in lab:
        cm_[(o["truth"]["mode"], argm(o["pred"]))] += 1
    tp = [o for o in lab if o["truth"]["mode"] == "被动限价"]
    ta = [o for o in lab if o["truth"]["mode"] == "主动追价"]
    S["mode"] = {"n_labeled": len(lab), "n_true_passive": len(tp), "n_true_marketable": len(ta),
                 "confusion": {f"{a}→{b}": n for (a, b), n in sorted(cm_.items())},
                 "mean_p_passive_on_true_passive": wmean([o["pred"]["被动限价"] for o in tp], [1] * len(tp)),
                 "mean_p_aggr_on_true_passive": wmean([o["pred"]["主动追价"] + o["pred"]["改单追上"] for o in tp], [1] * len(tp)),
                 "mean_p_other_on_true_passive": wmean([o["pred"]["其他"] for o in tp], [1] * len(tp)),
                 "mean_p_aggr_on_true_marketable": wmean([o["pred"]["主动追价"] + o["pred"]["改单追上"] for o in ta], [1] * len(ta)) if ta else None,
                 "auction_n": sum(1 for o in rows if o["truth"]["mode"] == "集合竞价"),
                 "auction_hit": sum(1 for o in rows if o["truth"]["mode"] == "集合竞价" and o["pred"]["集合竞价"] > 0.99),
                 "n_unknown": sum(1 for o in rows if o["truth"]["mode"] is None),
                 "all_fills_mean_probs": {k: round(float(np.mean([o["pred"][k] for o in rows])), 3) for k in MODES}}
    rp = [o for o in rows if o["truth"]["reprice_from"] is not None]
    nrp = [o for o in rows if o["truth"]["reprice_from"] is None and o["truth"]["mode"] in ("被动限价", "主动追价")]
    S["reprice"] = {"n_known_reprice_fills": len(rp),
                    "mean_p_reprice_on_reprice": wmean([o["pred"]["改单追上"] for o in rp], [1] * len(rp)) if rp else None,
                    "mean_p_reprice_on_others": wmean([o["pred"]["改单追上"] for o in nrp], [1] * len(nrp)) if nrp else None,
                    "share_reprice_toward_market": round(sum(1 for o in rp if (o["px"] > o["truth"]["reprice_from"]) == (o["side"] == "B")) / len(rp), 3) if rp else None,
                    "mean_p_passive_on_reprice": wmean([o["pred"]["被动限价"] for o in rp], [1] * len(rp)) if rp else None}
    # ② 挂单窗口上界是否包含真挂单时刻 + τ0 规则 vs 真深度
    pas = [o for o in tp if o["truth"]["on"] and bars.get(o["date"]) and o["win"]]
    cover, errs = 0, defaultdict(list)
    dtrue_f = []
    for o in pas:
        B = bars[o["date"]]
        b_on = B.ref_idx(o["truth"]["on"])
        start, m = o["win"]
        if b_on >= start - 1:      # 真挂单时刻在推断窗口内(允许 1 根 bar 误差)
            cover += 1
        Pt = B.c[b_on] if o["truth"]["on"] >= "09:30:00" else B.o[0]
        dt_ = depth_at(o["side"], o["px"], Pt)
        o["d_true"] = dt_
        dtrue_f.append(dt_)
        for rule in TAU_RULES:
            ti = tau0(rule, start, m, o["side"], B)
            errs[rule].append(depth_at(o["side"], o["px"], B.c[ti]) - dt_)
        o["age_true_min"] = (m - (b_on + 1)) if o["truth"]["on"] >= "09:30:00" else m
    S["window"] = {"n_passive_with_on": len(pas), "window_covers_true_on": cover,
                   "true_age_min_q": wq([o["age_true_min"] for o in pas], [1] * len(pas)),
                   "inferred_rest_upper_min_q": wq([o["win"][1] - o["win"][0] for o in pas], [1] * len(pas))}
    S["tau_rules"] = {r: {"bias_mean": round(float(np.mean(e)), 4), "mae": round(float(np.mean(np.abs(e))), 4), "median_err": round(float(np.median(e)), 4)} for r, e in errs.items() if e}
    best = min(S["tau_rules"], key=lambda r: S["tau_rules"][r]["mae"]) if S["tau_rules"] else "lag15"
    S["tau_best"] = best
    # ③ 触价模型: 已知 on 的挂单(成交/没成交)按分钟路径是否到价
    tch = {"filled_tt": 0, "filled_touch_only": 0, "filled_not_reached": 0, "unf_tt": 0, "unf_touch_only": 0, "unf_not_reached": 0}
    for o in pas:
        B = bars[o["date"]]
        a, b = path_check(o["side"], o["px"], B, o["truth"]["on"], o["t"], tick)
        tch["filled_tt" if a else "filled_touch_only" if b else "filled_not_reached"] += 1
    unf_ok = []
    for u in unfilled:
        B = bars.get(u["date"])
        if not B:
            continue
        a, b = path_check(u["side"], u["px"], B, u["on"], u["last"], tick)
        tch["unf_tt" if a else "unf_touch_only" if b else "unf_not_reached"] += 1
        u["reached_tt"], u["reached_touch"] = a, b
        unf_ok.append(u)
    S["touch"] = tch
    nt_f, nt_u = tch["filled_touch_only"], tch["unf_touch_only"]
    S["q_touch_est"] = round((nt_f + 1) / (nt_f + nt_u + 2), 2)   # Beta(1,1) 收缩, 样本极少
    # ④ IPW: 真挂单总体(成交+没成交, 已知 on) vs 只看成交 vs 成交按 1/π 加权
    curve = FillCurve([(b, tick) for b in bars.values() if b], H=H)
    pop_d, pop_fill = [], []
    for o in pas:
        pop_d.append(o["d_true"]); pop_fill.append(1)
    for u in unf_ok:
        B = bars[u["date"]]
        b_on = B.ref_idx(u["on"])
        Pt = B.c[b_on] if u["on"] >= "09:30:00" else B.o[0]
        u["d_true"] = depth_at(u["side"], u["px"], Pt)
        pop_d.append(u["d_true"]); pop_fill.append(0)
    pop_d, pop_fill = np.array(pop_d), np.array(pop_fill)
    res = {}
    for HH in (20, 60, 120, 240):
        cv = curve if HH == H else FillCurve([(b, tick) for b in bars.values() if b], H=HH)
        wts, wts_inf, dinf = [], [], []
        for o in pas:
            B = bars[o["date"]]
            sc = B.sigma * math.sqrt(HH)
            wts.append(1 / max(PI_MIN, cv.pi(o["side"], max(0.0, o["d_true"]), sc)))
            start, m = o["win"]
            ti = tau0(best, start, m, o["side"], B)
            di = depth_at(o["side"], o["px"], B.c[ti]); dinf.append(di)
            wts_inf.append(1 / max(PI_MIN, cv.pi(o["side"], max(0.0, di), sc)))
        fd = pop_d[pop_fill == 1]
        res[HH] = {"implied_fill_rate": round(len(wts) / sum(wts), 3) if wts else None,
                   "ipw_true_d": {"mean": wmean(fd, wts), **(wq(fd, wts) or {})},
                   "ipw_inferred_d": {"mean": wmean(dinf, wts_inf), **(wq(dinf, wts_inf) or {})}}
        for al in ALPHAS:
            wa = [w ** al for w in wts_inf]
            res[HH][f"alpha{al}_inferred_d"] = {"mean": wmean(dinf, wa), **(wq(dinf, wa) or {})}
    tgt = S_pop = {"mean": wmean(pop_d, np.ones(len(pop_d))), **(wq(pop_d, np.ones(len(pop_d))) or {})}
    errs_a = {}
    for al in ALPHAS:
        e = []
        for HH, v in res.items():
            b = v[f"alpha{al}_inferred_d"]
            e += [abs(b["mean"] - tgt["mean"]), abs(b["p50"] - tgt["p50"]), abs(b["p75"] - tgt["p75"])]
        errs_a[al] = round(float(np.mean(e)), 5)
    S["alpha_err"] = errs_a
    S["alpha_best"] = min(errs_a, key=errs_a.get)
    S["ipw"] = {"n_population": int(len(pop_d)), "n_filled": int(pop_fill.sum()), "actual_fill_rate": round(float(pop_fill.mean()), 3) if len(pop_d) else None,
                "population_d": {"mean": wmean(pop_d, np.ones(len(pop_d))), **(wq(pop_d, np.ones(len(pop_d))) or {})},
                "filled_only_d": {"mean": wmean(pop_d[pop_fill == 1], np.ones(int(pop_fill.sum()))), **(wq(pop_d[pop_fill == 1], np.ones(int(pop_fill.sum()))) or {})},
                "filled_inferred_d_raw": {"mean": wmean([depth_at(o["side"], o["px"], bars[o["date"]].c[tau0(best, o["win"][0], o["win"][1], o["side"], bars[o["date"]])]) for o in pas], [1] * len(pas))},
                "by_H": res,
                "by_side": {s: {"n_pop": int(np.sum([1 for o in pas if o["side"] == s]) + sum(1 for u in unf_ok if u["side"] == s)),
                                "fill_rate": round((sum(1 for o in pas if o["side"] == s)) / max(1, sum(1 for o in pas if o["side"] == s) + sum(1 for u in unf_ok if u["side"] == s)), 3)}
                            for s in ("B", "S")}}
    VAL.mkdir(parents=True, exist_ok=True)
    det = {"orders": [{k: v for k, v in o.items() if k != "legs"} for o in rows], "unfilled": unfilled}
    (VAL / "val_detail.json").write_text(json.dumps(det, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    (VAL / "val_summary.json").write_text(json.dumps(S, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(json.dumps(S, ensure_ascii=False, indent=1, default=float))
    return S


# ---------------- 导师 ----------------
def mentor_list(ledger=None):
    out = []
    for f in sorted(SKILLS.glob("*-skill/persona/cases_auto.jsonl")):
        sk = f.parts[-3].replace("-skill", "")
        if ledger and sk != ledger:
            continue
        if not (ROOT / "downloads" / "tzzb" / sk).exists():
            continue
        out.append(sk)
    return out


def amp30_map(pairs):
    """(日, code6) → 该票此前 30 个交易日 振幅(高-低)/昨收 的中位数(只读 kline_day); 用户做T纪律: 参数按个股近30日振幅定"""
    import datetime as dt
    from kline_db import db
    codes = {c for _, c in pairs}
    ds = sorted({d for d, _ in pairs})
    d0 = (dt.date.fromisoformat(ds[0]) - dt.timedelta(days=60)).isoformat()
    conn = db()
    ser = defaultdict(list)
    try:
        cur = conn.cursor()
        cur.execute("select symbol, trade_date, cast(high as double), cast(low as double), cast(pre_close as double) from kline_day "
                    "where trade_date >= %s and trade_date <= %s", (d0, ds[-1]))
        for sym, td, h, l, pc in cur.fetchall():
            c = sym[-6:]
            if c in codes and pc and h and l:
                ser[c].append((str(td)[:10], (h - l) / pc))
    finally:
        conn.close()
    out = {}
    for c, xs in ser.items():
        xs.sort()
        dd = [d for d, _ in xs]
        import bisect
        for d, cc in pairs:
            if cc != c:
                continue
            i = bisect.bisect_left(dd, d)
            w = [a for _, a in xs[max(0, i - 30):i]]
            if len(w) >= 10:
                out[(d, c)] = float(np.median(w))
    return out


def mentor_run(sk, dm, day_cache, tau_rule, H=H_DEFAULT, q=Q_TOUCH, amp=None):
    cases = [json.loads(x) for x in (SKILLS / f"{sk}-skill/persona/cases_auto.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    play = {}
    for c in cases:
        if c.get("side") == "买":
            play[(c["date"], str(c["code"]), "B")] = c.get("play") or "未分类"
        elif c.get("side") == "卖":
            play[(c["date"], str(c["code"]), "S")] = c.get("sell_kind") or "未分类"
    legs = []
    for t in load_legs(sk):
        code = str(t.get("stock_code", ""))
        d, tm = t["trans_date"][:10], t["trans_date"][11:19]
        if len(code) != 6 or tm == "00:00:00":
            continue
        if (d, code) not in dm:
            continue
        try:
            qv, pv = float(t.get("trans_count") or 0), float(t.get("trans_price") or 0)
        except ValueError:
            continue
        if qv <= 0 or pv <= 0:
            continue
        legs.append({"date": d, "t": tm, "code": code, "name": t.get("stock_name"), "side": "B" if t["op"] == "1" else "S", "qty": qv, "px": round(pv, 3), "oid": None})
    orders = merge_orders(legs, key=lambda x: (x["date"], x["code"], x["side"]))
    bars_used = {}
    recs = []
    for o in orders:
        d, code = o["date"], o["code"]
        if d not in day_cache:
            day_cache[d] = cache_load(d)[0]
        rows = day_cache[d].get(code)
        if not rows:
            continue
        key = (d, code)
        if key not in bars_used:
            bars_used[key] = Bars(rows)
        B = bars_used[key]
        k = dm[key]
        pc = k["preClose"]
        lp = limit_pct(code, o.get("name") or "")
        tick = tick_of(code)
        up = round(pc * (1 + lp) + 1e-9, 2) if pc else None
        dn = round(pc * (1 - lp) + 1e-9, 2) if pc else None
        recs.append((o, B, pc, up, dn, tick))
    if not recs:
        return None
    curve = FillCurve([(B, tick_of(k[1])) for k, B in bars_used.items()], H=H)
    # 同日同票同向的更早更优成交(另一张单) → 改单/追价语境
    grp = defaultdict(list)
    for o, *_ in recs:
        grp[(o["date"], o["code"], o["side"])].append(o)
    out = []
    for o, B, pc, up, dn, tick in recs:
        g = grp[(o["date"], o["code"], o["side"])]
        earlier = any(x is not o and x["t"] < o["t"] and sec(o["t"]) - sec(x["t"]) <= 1800 and ((x["px"] < o["px"]) if o["side"] == "B" else (x["px"] > o["px"])) for x in g)
        p, dg = classify(o["side"], o["t"], o["px"], B, up, dn, tick, earlier)
        w = window(o["side"], o["t"], o["px"], B, tick)
        r = {"date": o["date"], "t": o["t"], "code": o["code"], "side": o["side"], "px": o["px"], "nlegs": o["nlegs"],
             "play": play.get((o["date"], o["code"], o["side"]), "未分类"), "p": p,
             "vs_pc": (o["px"] / pc - 1) if pc else None}
        r["pre_open_ok"] = bool(w and w[0] == 0)   # 10/17 A8: 开盘以来价格没穿过成交价 = 这张被动单可能是盘前就挂好的
        if w and p["被动限价"] > 0:
            start, m = w
            ti = tau0(tau_rule, start, m, o["side"], B)
            dd = depth_at(o["side"], o["px"], B.c[ti])
            sc = B.sigma * math.sqrt(H)
            r.update(d=dd, rest_ub=m - start, pi=curve.pi(o["side"], max(0.0, dd), sc, q))
            a30 = (amp or {}).get((o["date"], o["code"]))
            if a30:
                r["d_amp"] = dd / a30
        out.append(r)
    return {"recs": out, "groups": grp, "n_stock_days": len(bars_used)}


ALPHA_USE = 0.5
MENTOR_TAU = "mid"     # 10/17: 导师挂单时刻的中性先验(不由用户实盘选)


def summarize(recs, min_n=8):
    def block(rs):
        n = len(rs)
        if not n:
            return None
        mode = {k: round(float(np.mean([x["p"][k] for x in rs])), 3) for k in MODES}
        pas = [x for x in rs if "d" in x]
        wp = [x["p"]["被动限价"] for x in pas]
        wi = [x["p"]["被动限价"] / max(PI_MIN, x["pi"]) for x in pas]
        dd = [x["d"] for x in pas]
        b = {"n": n, "mode": mode, "passive_mass": round(sum(wp), 1)}
        if sum(wp) >= 3:
            b["depth_raw"] = {"mean": wmean(dd, wp), **wq(dd, wp)}
            b["depth_ipw"] = {"mean": wmean(dd, wi), **wq(dd, wi)}
            wt = [x["p"]["被动限价"] / max(PI_MIN, x["pi"]) ** ALPHA_USE for x in pas]
            b["depth_tempered"] = {"alpha": ALPHA_USE, "mean": wmean(dd, wt), **wq(dd, wt)}
            b["implied_passive_fill_rate"] = round(sum(wp) / sum(wi), 3)
            b["ess_ipw"] = round(sum(wi) ** 2 / sum(w * w for w in wi), 1)   # 有效样本量; <10 视为不稳
            b["rest_upper_min"] = wq([x["rest_ub"] for x in pas], wp, (0.25, 0.5, 0.75))
            pa = [x for x in pas if "d_amp" in x]
            if pa:
                b["depth_amp_raw"] = wq([x["d_amp"] for x in pa], [x["p"]["被动限价"] for x in pa])
                b["depth_amp_ipw"] = wq([x["d_amp"] for x in pa], [x["p"]["被动限价"] / max(PI_MIN, x["pi"]) for x in pa])
        # 全部成交的 相对昨收: 原始 vs 加权(非被动部分权重 1)
        vs = [(x["vs_pc"], x["p"]["被动限价"], x.get("pi")) for x in rs if x["vs_pc"] is not None]
        if vs:
            w0 = [1.0] * len(vs)
            w1 = [(pp / max(PI_MIN, pi) + (1 - pp)) if pi is not None else 1.0 for _, pp, pi in vs]
            b["vs_prev_close_raw"] = wq([v for v, _, _ in vs], w0, (0.25, 0.5, 0.75))
            b["vs_prev_close_ipw"] = wq([v for v, _, _ in vs], w1, (0.25, 0.5, 0.75))
        return b
    res = {"all": block(recs)}
    by = defaultdict(list)
    for x in recs:
        by[x["play"]].append(x)
    res["by_play"] = {k: block(v) for k, v in sorted(by.items(), key=lambda kv: -len(kv[1])) if len(v) >= min_n}
    return res


def reprice_stats(groups):
    """可识别的改单/分笔特征: 同日同票同向多张单的价格轨迹"""
    n_grp = n_multi = chase = ladder_fav = mixed = 0
    gaps, nlegs_multi, n_orders = [], 0, 0
    for (d, code, side), os_ in groups.items():
        os_ = sorted(os_, key=lambda x: x["t"])
        n_grp += 1
        n_orders += len(os_)
        nlegs_multi += sum(1 for o in os_ if o["nlegs"] > 1)
        if len(os_) < 2:
            continue
        n_multi += 1
        pxs = [o["px"] for o in os_]
        sgn = 1 if side == "B" else -1
        dif = [sgn * (b - a) for a, b in zip(pxs, pxs[1:])]
        if all(x > 0 for x in dif):
            chase += 1            # 买越买越贵 / 卖越卖越便宜 = 追价梯(改单追或加单追)
        elif all(x < 0 for x in dif):
            ladder_fav += 1       # 买越买越便宜 / 卖越卖越贵 = 分档挂单梯
        else:
            mixed += 1
        gaps += [(sec(b["t"]) - sec(a["t"])) / 60 for a, b in zip(os_, os_[1:])]
    return {"n_day_code_side": n_grp, "share_multi_orders": round(n_multi / n_grp, 3) if n_grp else None,
            "among_multi": {"chase_ladder": round(chase / n_multi, 3) if n_multi else None, "favorable_ladder": round(ladder_fav / n_multi, 3) if n_multi else None,
                            "mixed": round(mixed / n_multi, 3) if n_multi else None},
            "gap_between_orders_min": wq(gaps, [1] * len(gaps), (0.25, 0.5, 0.75)) if gaps else None,
            "share_orders_multi_leg": round(nlegs_multi / n_orders, 3) if n_orders else None}


NOT_ID = ["单张挂单的真实挂出时刻(只有上界: 上次价格穿过成交价之后)",
          "改单次数与改单路径(改单追上 vs 新起意追价 的拆分是先验, 不是识别结果)",
          "没成交且没留下任何成交的挂单个数(只能由 1/π 加权推'隐含'规模)",
          "部分成交后撤掉的剩余量",
          "排板单的排队位置与没排到的板(封死不开 → 完全不可见)",
          "π 的尾部: π<0.05 的极深挂单在成交里几乎不出现, 其占比无法从成交恢复(权重截断在 20)"]


def mentors(ledger=None, H=H_DEFAULT, tau_rule=None, q=None):
    # 10/17 用户令(E12/15): 用户牧原实盘只做本方法的持续验证(--validate), 不许把在它上面选/估出的 τ0 规则、q、α 迁移给导师(短线小盘/连板/转债与牧原不同质)。
    #   导师一律用中性先验: τ0=穿价窗口中点(mid)、q=0.5(触价成交五五开)、α=0.5(半量去偏); 各 τ0 规则的敏感性另见报告
    tau_rule = tau_rule or MENTOR_TAU
    q = q if q is not None else Q_TOUCH
    global ALPHA_USE
    ALPHA_USE = 0.5
    sks = mentor_list(ledger)
    pairs = set()
    for sk in sks:
        for c in (SKILLS / f"{sk}-skill/persona/cases_auto.jsonl").read_text(encoding="utf-8").splitlines():
            if c.strip():
                c = json.loads(c)
                if len(str(c.get("code", ""))) == 6:
                    pairs.add((c["date"], str(c["code"])))
    dm = daily_map(pairs)
    dm = {k: v for k, v in dm.items() if k in pairs}
    day_cache = {}
    amp = amp30_map(set(dm))
    allres = {}
    for sk in sks:
        t0 = time.time()
        R = mentor_run(sk, dm, day_cache, tau_rule, H, q, amp)
        if not R:
            print(f"{sk}: 无分钟线覆盖, 跳过")
            continue
        recs = R["recs"]
        B = [x for x in recs if x["side"] == "B"]
        Sx = [x for x in recs if x["side"] == "S"]
        out = {"ledger": sk, "generated": time.strftime("%Y-%m-%d %H:%M"), "script": "scripts/tzzb/order_inference.py",
               "method": "成交方式=tick test+分钟K位置+穿价检查的打分(每笔概率); 被动单挂单时刻窗口=上次穿价之后; 深度 d=(τ0价-挂价)/τ0价(卖取反), τ0 规则由用户实盘真值选; 去偏=1/π 加权, π=本导师交易过的(票,日)分钟路径上假想挂单 H 分钟内首达概率(σ√H 归一)",
               "assumptions": {"alpha_tempered": ALPHA_USE, "tau0_rule": tau_rule, "H_bars": H, "q_touch": q, "pi_floor": PI_MIN, "merge_same_price_sec": MERGE_SEC},
               "coverage": {"orders_with_minutes": len(recs), "stock_days": R["n_stock_days"]},
               "buy": summarize(B), "sell": summarize(Sx), "reprice_identifiable": reprice_stats(R["groups"]),
               "not_identifiable": NOT_ID,
               "fields": {"depth": "挂价相对挂单时刻价格的深度(买: 低于现价的比例; 卖: 高于现价的比例), 正=挂在现价外等成交",
                          "depth_raw": "按被动概率加权的成交深度分位(=直接拿成交当挂单)", "depth_amp_raw/ipw": "深度 ÷ 该票前 30 日振幅中位(做T纪律口径: 挂价 = 现价 × (1 − k × 振幅中位), k 即此值)", "depth_ipw": "再按 1/π 加权(去幸存者偏差)后的'想挂的单'深度分位",
                          "implied_passive_fill_rate": "被动挂单的隐含成交率=Σp/Σ(p/π); 1/它-1 ≈ 每成交一张被动单背后看不见的没成交挂单数",
                          "rest_upper_min": "被动成交的挂单存续上界(分钟): 成交分钟-上次穿价分钟", "vs_prev_close_raw/ipw": "成交价相对昨收, 原始 vs 去偏加权"}}
        p = SKILLS / f"{sk}-skill" / "persona" / "orders_inferred.json"
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        # 10/17 A8: 逐单成交方式概率另存(时段口径"没改单=盘前单负责"要用), 只放机械字段
        rd = ROOT / "scripts" / "tzzb" / "model_out" / "orders_recs"
        rd.mkdir(parents=True, exist_ok=True)
        (rd / f"{sk}.jsonl").write_text("".join(json.dumps({k: x.get(k) for k in ("date", "t", "code", "side", "p", "pre_open_ok")}, ensure_ascii=False) + "\n"
                                                for x in recs), encoding="utf-8")
        allres[sk] = out
        a = out["buy"]["all"] or {}
        print(f"{sk}: 单 {len(recs)} (买 {len(B)}/卖 {len(Sx)}), 买 被动质量 {a.get('passive_mass')}, 深度 raw {a.get('depth_raw', {}).get('p50')} → ipw {a.get('depth_ipw', {}).get('p50')}, 隐含成交率 {a.get('implied_passive_fill_rate')}, {time.time() - t0:.0f}s", flush=True)
    (VAL.parent / "order_inference_val" / "mentors_summary.json").write_text(json.dumps(allres, ensure_ascii=False, indent=1), encoding="utf-8")
    return allres


# ---------------- 涨停排板的删失: 全市场关注集上"触板后开板"概率 ----------------
def board_stats():
    """downloads/market/<日>/kline_minute.jsonl(10/09 起关注集 400~700 只) 上: 首次触涨停后是否再开板(low<涨停价)"""
    n_touch = n_reopen = n_seal_allday = 0
    reopen_bars = []
    for dd in sorted(MARKET.iterdir()):
        f, k = dd / "kline_minute.jsonl", dd / "kline_day.jsonl"
        if not (f.exists() and k.exists()):
            continue
        pcm = {}
        for ln in k.read_text(encoding="utf-8").splitlines():
            r = json.loads(ln)
            if r.get("preClose"):
                pcm[r["symbol"]] = (float(r["preClose"]), r.get("name") or "")
        by = defaultdict(list)
        for ln in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(ln)
            if r["symbol"] in pcm and r.get("source") == "tdx":
                by[r["symbol"]].append(r)
        for sym, rows in by.items():
            pc, nm = pcm[sym]
            if "ST" in nm.upper() or sym[2:].startswith(("4", "8", "92")):
                continue
            up = round(pc * (1 + limit_pct(sym[2:], nm)) + 1e-9, 2)
            rows.sort(key=lambda b: b["barTime"])
            hi = [float(b["high"]) for b in rows]
            lo = [float(b["low"]) for b in rows]
            first = next((i for i, x in enumerate(hi) if x >= up - 0.005), None)
            if first is None:
                continue
            n_touch += 1
            later = [i for i in range(first + 1, len(lo)) if lo[i] < up - 0.005]
            if later:
                n_reopen += 1
                reopen_bars.append(len(later))
            if first == 0 and not later and lo[0] >= up - 0.005:
                n_seal_allday += 1
    return {"n_limit_touch_stock_days": n_touch, "share_reopen_after_first_touch": round(n_reopen / n_touch, 3) if n_touch else None,
            "share_one_word_sealed": round(n_seal_allday / n_touch, 3) if n_touch else None,
            "reopen_bars_median": float(np.median(reopen_bars)) if reopen_bars else None}


# ---------------- 报告 ----------------
def fmt_q(b, k="p50"):
    return "—" if not b or b.get(k) is None else f"{b[k] * 100:+.2f}%"


def flag(b):
    return "" if not b or (b.get("ess_ipw") or 0) >= 10 else "†"


SOURCES = [
    "Lo, MacKinlay & Zhang (2002) Econometric models of limit-order executions, JFE 65(1):31-71 — https://web.mit.edu/Alo/www/Papers/JFE2002_Pub.pdf",
    "Handa & Schwartz (1996) Limit Order Trading, JF 51(5):1835-1861 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=8200",
    "Vardi (1985) Empirical Distributions in Selection Bias Models, Ann. Statist. 13(1):178-203 — https://projecteuclid.org/journals/annals-of-statistics/volume-13/issue-1/Empirical-Distributions-in-Selection-Bias-Models/10.1214/aos/1176346585.full",
    "Cho & Nelling (2000) The Probability of Limit-Order Execution, FAJ 56(5) — https://www.researchgate.net/publication/247953776_The_Probability_of_Limit-Order_Execution",
    "Biais, Hillion & Spatt (1995) An Empirical Analysis of the Limit Order Book and the Order Flow in the Paris Bourse, JF 50(5) — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6970",
    "Fong & Liu (2010) Limit order revisions, JBF 34(8):1873-1885; Liu (2009) Monitoring and limit order submission risks, JFM 12 — https://ideas.repec.org/a/eee/finmar/v12y2009i1p107-141.html",
    "Avellaneda & Stoikov (2008) High-frequency trading in a limit order book — https://people.orie.cornell.edu/sfs33/LimitOrderBook.pdf",
    "Hollifield, Miller & Sandas (2004) Empirical Analysis of Limit Order Markets, RES — https://igier.unibocconi.eu/sites/default/files/media/attach/160502.pdf",
    "深交所投教 主板股票交易问答(价格笼子/基准价) — https://investor.szse.cn/column/qa/t20230306_599093.html",
    "上海证券报 主板投资入市手册(十六)(2%与十个最小变动单位孰高) — https://paper.cnstock.com/html/2023-07/13/content_1793858.htm",
    "深圳证监局 交易规则(超笼子申报暂存) — https://www.csrc.gov.cn/shenzhen/c105614/c2939575/content.shtml",
    "上交所 2018-08-20 起收盘集合竞价 14:57-15:00 不可撤单 — https://www.yicai.com/news/100007585.html",
]


CONCLUSION_0 = """- **幸存者偏差是真的，量级可观**：用户实盘 90 张已知挂出时刻的挂单里只有 39% 成交；全部挂单的深度中位 0.63%（均值 0.67%），只看成交是 0.53%（均值 0.46%）——直接拿成交当挂单，均值低估约 1/3。
- **只看「成交+分钟线」能把它基本还原**：推断挂单时刻（lag5）+ 1/π 加权，H=60~240 时深度中位 0.61~0.67%、均值 0.63~0.69%，与真值差 ≤0.06pp。但要老实说：用真挂单时刻做 1/π 反而**过度修正**（中位 0.78~0.92%，隐含成交率 0.21~0.30 < 真实 0.39），全流程的吻合有一部分是「τ 推断偏浅」与「IPW 偏深」互相抵消。
- **成交方式**：真被动单 42 张中 41 张判对（平均 P(被动)=0.83），集合竞价 12/12；真「可立即成交」单只有 2 张，**主动侧没有被验证**。
- **改单不可从单笔成交识别**：16 张已知「改价后成交」的单，模型给的 P(改单追上) 0.012，其他单 0.010——零区分力。用户的改单 94% 是向现价靠，改完以后**是挂着等成交的被动单**（P(被动)=0.70）。所以改单在 paper 里应建模为「挂单生命周期规则」，不是一种成交方式。
- **导师去偏**：被动挂单的深度普遍是成交口径的 1.3~3 倍：高概率复利 买 P50 0.23%→0.65%（隐含成交率 34%）、指鹰决心 0.84%→1.69%（22%）、刘忆青 2.30%→3.80%（13%）、量化小号 0.24%→1.04%（45%）；星见野/antoo 只 0.23→0.39%/0.38%（成交率 58%/65%，挂得浅、几乎都成）。
- **不同导师的挂法结构差别比深度差别更大**：高概率复利 57% 被动、刘忆青 46%、星见野 43%（低吸型）；a658/antoo/量化小号/冲5000w 被动 ≤17%，60~70% 是对价成交（成交价≈挂价，去偏影响小）；ST之狼 47% 排板 + 22% 竞价。"""

CONCLUSION_6 = """## 6. 对 paper 挂价规则的建议

1. **两段式定价：先抽挂法，再算价**。LLM 只给意图（低吸/对价/排板/竞价），规则按导师「成交方式分布」（第 4 表）校验意图比例：例如 a658/antoo/量化小号 的买单 60~70% 是对价，如果链上它们 80% 都挂深低吸，就是不拟人。
2. **被动单挂价 = 挂单时刻现价 × (1 − k × 该票近 30 日振幅中位)**，k 取**去偏后**分布（第 4 表最后一列 ÷100）：中心用去偏 P50、范围 P25~P75；不要用 fills_realtime 的成交价分布（偏浅）。代表值：高概率复利 k≈0.10→0.22、星见野 0.06→0.11、指鹰决心 0.19→0.50、刘忆青 0.44→0.72、量化小号 0.05→0.17。† 标记（ESS<10）的组只用方向，退回该导师全体口径。
3. **对价/主动单**：直接按现价（买一/卖一）挂，受 2% 价格笼子约束；对这类导师不需要去偏。
4. **排板单**：已有撮合（封板不成、开板才成）就是对的；另外要预期「想排没排到」——关注集里触板后再开板的只有 61%，一字封死 6.6%，排板型导师链的成交笔数应低于真人可见笔数是正常的，不要当成规则失败。
5. **改单 = 生命周期参数，不是成交类型**：被动单挂出后若 X 分钟未成交，向现价靠一半深度（用户真值：改单 94% 向现价靠；挂单存续中位 5 分钟、P90 31 分钟）。导师的 X 用「存续上界中位」作上限（高概率复利 20、指鹰 12、星见野 8、其他 1~3 分钟，说明它们多为即挂即成或盯盘贴价），盘中子链每个时段只做一次靠价，避免无限追。
6. **按隐含成交率预期 paper 的成交频率**：深挂型（刘忆青 13%、ST之狼 17%、指鹰 22%、高概率复利 34%）在真人那里本来就有大量挂了没成的单，paper 链的被动单同样会大量不成交——评估拟人度时比的是「挂法分布」，不是「成交笔数」。这类导师可以用分档梯（第 4.3 表：刘忆青/高概率复利/量化小号 分档梯占多单组 37~43%）分 2~3 档挂。
7. **开盘 5 分钟内的成交不要用「相对开盘」算深度**：刘忆青大量 09:31 的成交价比开盘低 5~13%（开盘急杀），这些更像盘前按昨收/固定位挂的单，挂价锚应改用昨收（fills_realtime 的「相对昨收」列）。

## 7. 不自信点

- 真值只有**一个人、一只票**（牧原，流动性好、日振幅 ~2%），90 张挂单、35 张成交；τ0=lag5、q=0.86、α 都是在这批样本上选/估的（样本内），迁移到导师（小盘、连板、转债）是假设。
- 主动/对价侧只有 2 张真值，**成交方式里「主动追价」的准确率未知**；分钟线上的 tick test 在急跌急涨（开盘急杀、连板）里会把对价单误判成被动——刘忆青/指鹰的 2~4% 深度可能部分是这种误判。
- 全流程吻合真值有误差抵消成分（见 0 节）；π 用当日已实现路径 + 随机挂单时刻，而真人挂单是择时的（在支撑位/均价附近），π 可能被低估 → 隐含的「看不见的挂单数」可能高估约 1.5 倍（用户：隐含成交率 0.21 vs 真实 0.39，H=60）。
- 「改单追上」与「主动追价」的拆分是先验比例（0.1/0.25/0.4），不是数据识别结果；报告与 json 里这一列只能当上下界参考。
- 同花顺账本的腿是否等于券商逐笔成交未核实（可能被合并或手录）；同价 5 分钟内并为一张单是近似。
- 去偏后的相对昨收分布在小样本组里会被个别高权重样本拉偏（如 † 组），只看方向。"""


def report():
    S = json.loads((VAL / "val_summary.json").read_text(encoding="utf-8"))
    M = json.loads((VAL / "mentors_summary.json").read_text(encoding="utf-8"))
    BS = board_stats()
    L = []
    A = L.append
    A("# 从成交反推挂单：删失数据下的挂价深度去偏（10/16 晚）")
    A("")
    A("> 脚本 `scripts/tzzb/order_inference.py`（零 token、只读）；逐导师产物 `skills/<导师>-skill/persona/orders_inferred.json`；"
      "真值验证的明细只在 `scripts/dfcf/snapshots/order_inference_val/`（隐私，不进 git），本文只有聚合数字。")
    A("> 前置报告 `docs/research/fills_realtime_20261016.md`（成交当时的盘中状态）——本文回答它的第一条局限：只有成交没有挂单。")
    A("")
    A("## 0. 结论先行（10/16 运行结果；重跑后以第 3、4 节表格为准）")
    A("")
    A(CONCLUSION_0)
    A("")
    A("## 1. 问题与交易规则口径（已核实）")
    A("")
    A("- 观测到的是**成交腿**（时分秒、成交价、量），挂单价/挂单时刻/撤改单全不可见 → 成交价分布 = 挂价分布 × 成交概率，是**被成交概率加权过的样本**（选择偏差/删失）。")
    A("- 连续竞价：价格优先、时间优先；被动挂单（resting）只会以**自己的挂价**成交；可立即成交的单（marketable）以对手价成交，可能一单吃多档（同一委托多个成交价）。")
    A("- 价格笼子（2023 全面注册制起，主板/创业板）：连续竞价限价买入申报价 ≤ 买入基准价（即时最低卖价）的 102% 与「基准价 + 10 个最小变动单位」的孰高者，卖出对称 98%/−10 档；"
      "深市超笼子申报暂存、进入笼子后自动参与竞价，沪市（按通达信规则汇总）为无效申报；科创板只有 2%。→ 追价单最多比卖一高 2%，影响「主动追价」的价位上限。")
    A("- 集合竞价：09:15–09:25 开盘集合竞价（09:20–09:25 不可撤单），14:57–15:00 收盘集合竞价（沪市自 2018-08-20 起与深市一致，期间不可撤单、不接受市价单）。09:25/15:00 的成交单独成类。")
    A("- 涨停价买入=排队：封死不成交、开板/炸板才可能轮到；排不到的板**完全不可见**。T+1；股票最小变动价位 0.01（ETF 0.001）。")
    A("")
    A("## 2. 方法")
    A("")
    A("### 2.1 文献依据（可信度自评）")
    A("")
    A("| 方法 | 出处 | 用在哪 | 可信度 |")
    A("|---|---|---|---|")
    A("| 限价单执行的生存分析（撤单=删失） | Lo, MacKinlay & Zhang (2002) JFE 65(1) | 框架：成交时间/成交概率是挂价深度的强函数，撤单是删失不是缺失 | 高（经典）；但需要**挂单数据**，我们没有，只能借其结论 |")
    A("| 假想挂单（价格路径首达） | Handa & Schwartz (1996) JF 51(5) | π(d)：在导师交易过的票-日分钟路径上放假想挂单，算 H 分钟内首达概率 | 中：LMZ 2002 指出首达是实际成交的**差代理**（忽略排队），我们用「穿价必成 + 恰好触价按 q 成交」并用真值估 q |")
    A("| 选择偏差的已知权重 NPMLE / 逆概率加权 | Vardi (1985) Ann. Stat. 13(1)；Horvitz–Thompson | 去偏：被动成交按 1/π 加权还原「想挂的单」 | 高（数学上），前提是 π 估得准且 >0（尾部不可识别） |")
    A("| 成交方向分类（tick test / quote rule） | Lee & Ready (1991)；Ellis-Michaely-O'Hara (2000, Nasdaq) 报告 tick test 准确率约 3/4 量级 | 成交方式：成交价 vs 上一笔/上一分钟收盘判主动/被动 | 中低：我们只有分钟线，比逐笔更粗 |")
    A("| 挂单行为：靠近最优价、价差大/簿薄时多挂限价 | Biais, Hillion & Spatt (1995) JF 50(5) | 解释导师挂价集中在现价附近 | 高（描述性） |")
    A("| 撤单/改单与盯盘成本 | Fong & Liu (2010) JBF 34(8)；Liu (2009) JFM | 盯盘越勤改单越多；追价改单（chasing）是撤单主因之一 | 中：澳交所数据，A 股散户口径未验证 |")
    A("| 成交强度随距离指数衰减 λ(δ)=A·e^{-kδ} | Avellaneda & Stoikov (2008) | 可替代经验 π 的参数形式（本原型用经验分布，不用参数式） | 中 |")
    A("")
    A("### 2.2 流程")
    A("")
    A("1. **成交单**：同日同票同向、同价 5 分钟内的腿并成一张单（分笔成交）；有委托编号时按编号并。")
    A("2. **成交方式打分**（每张单一组概率，合计 100%）：09:25/15:00→集合竞价；涨停价买/跌停价卖→排板；其余按证据打分——成交价低于上一分钟收盘（买）/高于（卖）、在成交分钟 K 的下 1/3、创近 10 分钟新低 → 被动；"
      "高于上一分钟收盘、在 K 上 1/3、前 3 分钟价格已穿过他的价（若早挂着早就成了）、动量同向 → 主动；固定基线分给「其他/证据不足」。主动部分再按「近 15 分钟曾便宜 ≥0.4% / 同日更早有更优的成交」拆出「改单追上」（**先验拆分，不可识别**）。")
    A("3. **挂单窗口**：被动单的挂单时刻只能在「上次价格穿过成交价」之后 → 存续时间上界；挂单时刻 τ0 的点估计用规则（naive=成交前一分钟、lagX=成交前 X 分钟但不早于窗口起点、mid、max 等），用用户真值选误差最小的。")
    A("4. **去偏**：π(d)=在该导师交易过的(票,日)分钟路径上，每 3 分钟放一张深度 d 的假想挂单，H 分钟内穿价（必成）或恰好触价（按 q 成）的比例，深度按当日 1 分钟平均波动 σ√H 归一；被动成交权重 1/max(π,0.05)。")
    A("5. **真值验证**：用户牧原实盘（挂单表/委托截图/会话报单：既知挂单又知成交）只喂「成交 + 分钟线」，看能否还原。")
    A("")
    # 验证
    md, wd, tr, tc, ip = S["mode"], S["window"], S["tau_rules"], S["touch"], S["ipw"]
    A("## 3. 真值验证（用户牧原实盘，只列聚合指标）")
    A("")
    A(f"- 样本：{S['n_days']} 个交易日（有分钟线 {S['n_days_with_bars']} 天），成交腿 {S['n_fill_legs']} → 合并成交单 {S['n_orders_filled']} 张；从挂单表/截图/会话还原出**没成交的挂单** {S['n_unfilled_orders_known']} 张（含被改价的原单）。")
    A(f"- 能打真值标签的成交单 {md['n_labeled']} 张：真被动（挂着等成交）{md['n_true_passive']}、真可立即成交 {md['n_true_marketable']}；集合竞价 {md['auction_n']} 张（命中 {md['auction_hit']}）；无法标注 {md['n_unknown']} 张。")
    A("")
    A("**3.1 成交方式**")
    A("")
    A("| 指标 | 值 |")
    A("|---|---|")
    A(f"| 混淆（真值→预测最大类） | {'; '.join(f'{k} {v}' for k, v in md['confusion'].items())} |")
    A(f"| 真被动单上的平均 P(被动) / P(主动+改单) / P(其他) | {md['mean_p_passive_on_true_passive']} / {md['mean_p_aggr_on_true_passive']} / {md['mean_p_other_on_true_passive']} |")
    A(f"| 真可立即成交单上的平均 P(主动+改单) | {md['mean_p_aggr_on_true_marketable']} |")
    rp = S["reprice"]
    A(f"| 已知改单后成交的单数 / 其平均 P(改单追上) vs 其他单 | {rp['n_known_reprice_fills']} / {rp['mean_p_reprice_on_reprice']} vs {rp['mean_p_reprice_on_others']} |")
    A(f"| 已知改单中「向现价靠」的比例 / 改单后成交单的平均 P(被动) | {rp['share_reprice_toward_market']} / {rp['mean_p_passive_on_reprice']} |")
    A("")
    A("**3.2 挂单时刻与深度**")
    A("")
    A(f"- 推断窗口（上次穿价之后）包含真挂单时刻：{wd['window_covers_true_on']}/{wd['n_passive_with_on']}。真挂单存续（分钟）P25/50/75/90 = {wd['true_age_min_q']}；推断的存续上界 = {wd['inferred_rest_upper_min_q']}。")
    A("")
    A("| τ0 规则 | 深度误差均值(偏差) | 平均绝对误差 | 中位误差 |")
    A("|---|---|---|---|")
    for r, v in tr.items():
        A(f"| {r}{' ←选用' if r == S['tau_best'] else ''} | {v['bias_mean'] * 100:+.2f}% | {v['mae'] * 100:.2f}% | {v['median_err'] * 100:+.2f}% |")
    A("")
    A(f"**3.3 触价模型**（已知挂出时刻的挂单，分钟路径是否到价）：成交单中 穿价 {tc['filled_tt']} / 只触价 {tc['filled_touch_only']} / 没到价 {tc['filled_not_reached']}；"
      f"没成交单中 穿价 {tc['unf_tt']} / 只触价 {tc['unf_touch_only']} / 没到价 {tc['unf_not_reached']}。→ 恰好触价时的成交率估计 q = {S['q_touch_est']}。")
    A("「没成交却穿价」的条目是真值噪声（会话报单滞后/记错）或改单发生在两次目击之间，不是撮合模型错误。")
    A("")
    A(f"**3.4 去偏能否还原真挂价深度**（总体=已知挂出时刻的全部挂单 {ip['n_population']} 张，其中成交 {ip['n_filled']}，真实成交率 {ip['actual_fill_rate']}；买 {ip['by_side']['B']} / 卖 {ip['by_side']['S']}）")
    A("")
    A("| 口径 | 均值 | P25 | P50 | P75 | P90 | 隐含成交率 |")
    A("|---|---|---|---|---|---|---|")
    def row(name, b, fr=""):
        A(f"| {name} | {fmt_q(b, 'mean')} | {fmt_q(b, 'p25')} | {fmt_q(b, 'p50')} | {fmt_q(b, 'p75')} | {fmt_q(b, 'p90')} | {fr} |")
    row("**真值：全部挂单**", ip["population_d"], ip["actual_fill_rate"])
    row("只看成交（=幸存者）", ip["filled_only_d"])
    for HH, v in ip["by_H"].items():
        row(f"成交 + 1/π 加权（真 τ0, H={HH}）", v["ipw_true_d"], v["implied_fill_rate"])
    for HH, v in ip["by_H"].items():
        row(f"全流程：推断 τ0 + 1/π（H={HH}）", v["ipw_inferred_d"])
    A("")
    # 导师
    A("## 4. 各导师：去偏前后挂价深度（买入）")
    A("")
    A(f"> τ0 规则 = `{json.loads(json.dumps(next(iter(M.values()))['assumptions']))['tau0_rule'] if M else '—'}`，H = {next(iter(M.values()))['assumptions']['H_bars'] if M else '—'} 分钟，q = {next(iter(M.values()))['assumptions']['q_touch'] if M else '—'}。"
      "深度 = 挂价低于挂单时刻现价的比例（正=挂在下面等）。「隐含成交率」= 被动挂单里成交的比例估计，1/它 − 1 ≈ 每成交一张被动单背后看不见的没成交挂单数。")
    A("")
    A("| 导师 | 买单 | 集合竞价 | 排板 | 被动 | 主动追价 | 改单追上 | 其他 | 深度 raw P50/P75 | 深度 去偏 P50/P75 | 隐含成交率 | 存续上界中位(分) | 深度÷30日振幅中位 P50 raw→去偏(×100) |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for sk, o in M.items():
        a = o["buy"]["all"]
        if not a:
            continue
        m_ = a["mode"]
        A(f"| {sk} | {a['n']} | {m_['集合竞价']:.0%} | {m_['排板']:.0%} | {m_['被动限价']:.0%} | {m_['主动追价']:.0%} | {m_['改单追上']:.0%} | {m_['其他']:.0%} | "
          f"{fmt_q(a.get('depth_raw'))}/{fmt_q(a.get('depth_raw'), 'p75')} | {fmt_q(a.get('depth_ipw'))}/{fmt_q(a.get('depth_ipw'), 'p75')}{flag(a)} | {a.get('implied_passive_fill_rate', '—')} | "
          f"{(a.get('rest_upper_min') or {}).get('p50', '—')} | {fmt_q(a.get('depth_amp_raw'))[:-1].replace('+', '')}→{fmt_q(a.get('depth_amp_ipw'))[:-1].replace('+', '')} |")
    A("")
    A("† = 去偏有效样本量 ESS<10（少数高权重样本主导），去偏数字不稳，只看方向。「深度÷30日振幅中位」列 ×100 后的数，例如 12 表示挂价比现价低 0.12×该票近30日振幅中位。")
    A("")
    A("### 4.1 卖出")
    A("")
    A("| 导师 | 卖单 | 集合竞价 | 排板 | 被动 | 主动 | 改单 | 其他 | 深度 raw P50/P75 | 去偏 P50/P75 | 隐含成交率 |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for sk, o in M.items():
        a = o["sell"]["all"]
        if not a:
            continue
        m_ = a["mode"]
        A(f"| {sk} | {a['n']} | {m_['集合竞价']:.0%} | {m_['排板']:.0%} | {m_['被动限价']:.0%} | {m_['主动追价']:.0%} | {m_['改单追上']:.0%} | {m_['其他']:.0%} | "
          f"{fmt_q(a.get('depth_raw'))}/{fmt_q(a.get('depth_raw'), 'p75')} | {fmt_q(a.get('depth_ipw'))}/{fmt_q(a.get('depth_ipw'), 'p75')}{flag(a)} | {a.get('implied_passive_fill_rate', '—')} |")
    A("")
    A("### 4.2 按打法（买入，≥8 单）：相对昨收 原始 vs 去偏、被动深度 原始 vs 去偏")
    A("")
    A("| 导师 | 打法 | 单数 | 被动占比 | 主动+改单 | 相对昨收 P50 原始→去偏 | 被动深度 P50 原始→去偏 | P75 原始→去偏 | 隐含成交率 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for sk, o in M.items():
        for pl, b in (o["buy"].get("by_play") or {}).items():
            if not b:
                continue
            m_ = b["mode"]
            A(f"| {sk} | {pl} | {b['n']} | {m_['被动限价']:.0%} | {m_['主动追价'] + m_['改单追上']:.0%} | {fmt_q(b.get('vs_prev_close_raw'))}→{fmt_q(b.get('vs_prev_close_ipw'))} | "
              f"{fmt_q(b.get('depth_raw'))}→{fmt_q(b.get('depth_ipw'))}{flag(b)} | {fmt_q(b.get('depth_raw'), 'p75')}→{fmt_q(b.get('depth_ipw'), 'p75')}{flag(b)} | {b.get('implied_passive_fill_rate', '—')} |")
    A("")
    A("### 4.3 可识别的改单/分笔特征（同日同票同向的多张单）")
    A("")
    A("| 导师 | 票-日-向 组数 | 多张单占比 | 其中 追价梯(买越买越贵) | 分档梯(买越买越便宜) | 混合 | 相邻两单间隔中位(分) | 分笔成交单占比 |")
    A("|---|---|---|---|---|---|---|---|")
    for sk, o in M.items():
        r = o["reprice_identifiable"]
        am = r["among_multi"]
        A(f"| {sk} | {r['n_day_code_side']} | {r['share_multi_orders']} | {am['chase_ladder']} | {am['favorable_ladder']} | {am['mixed']} | {(r['gap_between_orders_min'] or {}).get('p50', '—')} | {r['share_orders_multi_leg']} |")
    A("")
    A(f"**排板删失（全市场关注集，10/09 起分钟线）**：触及涨停的票-日 {BS['n_limit_touch_stock_days']} 个，首次触板后再开板（最低 < 涨停价）的比例 {BS['share_reopen_after_first_touch']}，"
      f"开盘一字且全天未开 {BS['share_one_word_sealed']}；→ 排板单的成交率上界≈开板率，没开的板上的排队单完全不可见，排板型导师（stzhilang/zhiyingjuexin）的「想排的板」比看到的多，且偏向封得死的强板。")
    A("")
    A("## 5. 识别不了的部分")
    A("")
    for x in NOT_ID:
        A(f"- {x}")
    A("- 用户单人、单票（牧原，机构/ETF 票，日振幅 ~2%）的真值不能直接代表导师；τ0 规则与 q 是在这一个人身上选/估的，迁移到导师是假设。")
    A("- 可识别的部分：成交方式中的集合竞价/排板（规则确定）、被动 vs 对价（tick test，被动侧验证过）、被动单存续的上界、分档梯/追价梯的多单结构、在 π>0.05 范围内的深度分布形状。")
    A("")
    A(CONCLUSION_6)
    A("")
    A("## 8. 出处")
    A("")
    for x in SOURCES:
        A(f"- {x}")
    A("")
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"报告: {REPORT}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch-user", action="store_true")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--mentors", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--ledger")
    ap.add_argument("--H", type=int, default=H_DEFAULT)
    ap.add_argument("--tau")
    a = ap.parse_args()
    allp = not (a.fetch_user or a.validate or a.mentors or a.report)
    if a.fetch_user:
        fetch_user()
    if a.validate or allp:
        validate(a.H)
    if a.mentors or allp:
        mentors(a.ledger, a.H, a.tau)
    if a.report or allp:
        report()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
