# -*- coding: utf-8 -*-
"""case_log.py — tzzb 导师逐日"操作日志卡"(10/18 用户令: 把 cases / rules 加厚; 零 token, 只读, 机械可复现)

为什么: cases.md 只记"显著"的案例, 平常日子的手法(拿着不动 / 高开卖一半 / 尾盘建仓)没有落地, 日积月累的技巧蒸馏不出来。
        本脚本把导师每个有持仓或有成交的交易日都写成一张卡, 给蒸馏 / 检索读。
数据(全部已在盘上):
  skills/<id>-skill/persona/cases_auto.jsonl  每笔成交事件(date,time,code,side,vwap,nlegs,feat 当日/昨日行情背景, play/sell_kind, result)
                                              + 日内事件(side=日内事件: 换股 / 同票加仓 / 先买后卖; 只取 event+evidence, 不取 hyp 推断)
  skills/<id>-skill/persona/fills_rt.jsonl    成交那一分钟的盘中状态(rt: mins_from_open / vs_prev_close / vs_open / pos_so_far / mom5 / 触板...)
  downloads/tzzb/<id>/day_positions.json      每日收盘仓位 {YYYYMMDD:{list:[{code,name,op,position_percent,rate}]}}
                                              op(与成交腿交叉核对过): 0 持有 / 3 新开 / 4 清仓 / 7 加仓 / 8 减仓 / 9 当日有买有卖 / 1 买入 / 2 卖出
  行情库 kline_day(只读): 未成交持仓的当日表现 + 次日结果; sh000001 = 大盘
  downloads/market/<D>/auction_live_open.json(10/12 起): 成交 / 持仓票的开盘集合竞价(口径同 scripts/lib/auction.mjs)
  涨停家数 / 上涨占比: 从全体导师 cases_auto 的 feat(zt_n_day / zt_n_prev / up_ratio_prev, mentor_fingerprint 同一口径)按日期汇总
防后见: 每张卡只用卡日期当天及以前的信息; 唯一例外是明确标注的「结果(次日 …)」行(次日收盘)。cases_auto 的 r_5d 一律不用。
产物: skills/<id>-skill/persona/case_log/<YYYY-MM>.md(每日一卡, 月内按日期正序) + case_log/index.md(一日一行: 日期 + 标签 + 链接, 倒序)
      幂等: 内容不变不重写; 目录里本脚本不再产出的旧 .md 会删掉(目录只归本脚本)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/case_log.py [--ledger a,b] [--dry]
"""
import argparse
import bisect
import collections
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
import a_rules as AR        # noqa: E402
import mentors as M         # noqa: E402
from kline_db import db     # noqa: E402

OP = {"0": "持有", "3": "新开", "4": "清仓", "7": "加仓", "8": "减仓", "9": "有买有卖", "1": "买入", "2": "卖出"}
WD = "一二三四五六日"
FLY = 0.03   # 卖后次日收较卖价 ≥+3% = 卖飞, ≤-3% = 逃顶(卖对)
FUTURE_EV = {"首只2日内亏损卖", "首只持有≥3日", "两只都持有到次日"}   # 日内事件 evidence 里看了卡日之后的字段, 不进卡(防后见)


def is_repo(code, name=""):
    c, n = str(code), str(name or "")
    return c.startswith(("204", "1318")) or n.startswith(("GC", "R-")) or "逆回购" in n


def iso(k):
    return f"{k[:4]}-{k[4:6]}-{k[6:]}" if len(k) == 8 else k


def pc(x, d=1):
    return "?" if x is None else f"{x * 100:+.{d}f}%"


def pp(x):
    return "?" if x is None else f"{x * 100:.0f}%" if x >= 0.095 or x == 0 else f"{x * 100:.1f}%"


def jl(p):
    if not p.exists():
        return []
    out = []
    for l in p.read_text(encoding="utf-8").splitlines():
        l = l.strip()
        if l:
            try:
                out.append(json.loads(l))
            except ValueError:
                pass
    return out


def tbucket(t):
    t = (t or "")[:5]
    if not t:
        return "?"
    return "竞价" if t < "09:30" else "开盘5分钟" if t < "09:35" else "早盘" if t < "10:30" else "上午" if t < "11:31" else "午后" if t < "14:30" else "尾盘"


# ---------- 公共市场层(全体导师共用, 只算一次) ----------
def market_breadth():
    """日期 → {zt: 涨停家数, up: 上涨占比}; 汇自全体导师 feat(同一 Market 口径), 当日值优先, 缺则取次日记录里的 *_prev"""
    zt, up = {}, {}
    days = None
    for f in sorted((ROOT / "skills").glob("*-skill/persona/cases_auto.jsonl")):
        for r in jl(f):
            fe = r.get("feat") or {}
            if fe.get("zt_n_day") is not None:
                zt.setdefault(r["date"], fe["zt_n_day"])
            if fe.get("up_ratio_day") is not None:
                up.setdefault(r["date"], fe["up_ratio_day"])
            if fe.get("zt_n_prev") is not None or fe.get("up_ratio_prev") is not None:
                days = days or []
                days.append((r["date"], fe.get("zt_n_prev"), fe.get("up_ratio_prev")))
    return zt, up, days or []


def resolve_prev(days_prev, cal, zt, up):
    """次日记录里的 zt_n_prev / up_ratio_prev = 上一交易日的值(cal=大盘交易日历)"""
    for d, z, u in days_prev:
        i = bisect.bisect_left(cal, d)
        if 0 < i < len(cal) and cal[i] == d:
            p = cal[i - 1]
            if z is not None:
                zt.setdefault(p, z)
            if u is not None:
                up.setdefault(p, u)


def idx_calendar():
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("select trade_date from kline_day where is_deleted=0 and symbol='sh000001' and trade_date >= '2025-01-01' order by trade_date")
        return [str(r[0]) for r in cur.fetchall()]
    finally:
        conn.close()


def load_kline(codes, d0, d1):
    syms = {}
    for c in codes:
        if c and len(c) == 6 and c.isdigit():
            try:
                syms[AR.symbol(c)] = c
            except Exception:   # noqa: BLE001
                pass
    syms["sh000001"] = "IDX"
    out = collections.defaultdict(dict)
    conn = db()
    try:
        cur = conn.cursor()
        ks = list(syms)
        for i in range(0, len(ks), 400):
            part = ks[i:i + 400]
            cur.execute("select symbol, trade_date, cast(open as double), cast(high as double), cast(low as double), cast(close as double), "
                        "cast(pre_close as double) from kline_day where is_deleted=0 and trade_date between %s and %s "
                        f"and symbol in ({','.join(['%s'] * len(part))})", [d0, d1] + part)
            for sym, td, o, h, l, c, pcl in cur.fetchall():
                out[syms[sym]][str(td)] = {"o": o, "h": h, "l": l, "c": c, "pc": pcl}
    finally:
        conn.close()
    return out


_AUC = {}


def auction(d):
    if d not in _AUC:
        f = ROOT / "downloads" / "market" / d / "auction_live_open.json"
        try:
            _AUC[d] = json.loads(f.read_text(encoding="utf-8")).get("symbols") or {}
        except (OSError, ValueError):
            _AUC[d] = None
    return _AUC[d]


def auc_line(d, code, name):
    S = auction(d)
    if not S:
        return None
    try:
        s = S.get(AR.symbol(code))
    except Exception:   # noqa: BLE001
        return None
    if not s:
        return None
    p1, fin = s.get("p2_first") or s.get("p1"), s.get("fin") or s.get("p2")
    parts = []
    if p1:
        parts.append(f"9:20 {p1['pct']:+.1f}%")
    if fin:
        parts.append(f"开 {fin['pct']:+.1f}%")
    if s.get("vol_ratio"):
        parts.append(f"竞价量=昨全天 {s['vol_ratio'] * 100:.1f}%")
    tags = [t for t in (s.get("tags") or [])][:2]
    return f"{name} " + " → ".join(parts[:2]) + ("; " + parts[2] if len(parts) > 2 else "") + (f"【{'; '.join(tags)}】" if tags else "")


# ---------- 单导师 ----------
def kpct(k, a, b="pc"):
    if not k or not k.get(a) or not k.get(b):
        return None
    return k[a] / k[b] - 1


def build(sk, zt, up, cal_all):
    P = ROOT / "skills" / f"{sk}-skill" / "persona"
    dp_f = ROOT / "downloads" / "tzzb" / sk / "day_positions.json"
    dp_raw = json.loads(dp_f.read_text(encoding="utf-8")) if dp_f.exists() else {}
    issues = collections.Counter()
    dp = {}          # iso → {code: entry}(非逆回购)
    repo = {}        # iso → 逆回购仓位
    keys = sorted(dp_raw)
    for i, k in enumerate(keys):
        v = dp_raw[k] or {}
        lst = v.get("list") or []
        if i == 0 and not lst:   # 首个键 = 拉取基线(常为"空仓或无数据"), 不当真实空仓
            issues["首日基线无数据"] += 1
            continue
        D = iso(k)
        dp[D] = {}
        repo[D] = 0.0
        for p in lst:
            c = str(p.get("code"))
            if is_repo(c, p.get("name")):
                repo[D] += float(p.get("position_percent") or 0)
            else:
                dp[D][c] = p
    rows = jl(P / "cases_auto.jsonl")
    ev = collections.defaultdict(list)    # 日 → 成交事件
    ie = collections.defaultdict(list)    # 日 → 日内事件
    for r in rows:
        if r.get("side") == "日内事件":
            ie[r["date"]].append(r)
        elif r.get("code") is not None:
            ev[r["date"]].append(r)
    rt = collections.defaultdict(list)
    for r in jl(P / "fills_rt.jsonl"):
        rt[(r.get("date"), r.get("time"), str(r.get("code")), r.get("side"))].append(r.get("rt"))
    for d in ev:
        for r in ev[d]:
            q = rt.get((r["date"], r.get("time"), str(r["code"]), r["side"]))
            r["_rt"] = q.pop(0) if q else None
        ev[d].sort(key=lambda r: (r.get("time") or "", r["side"] != "买", str(r["code"])))
    if not dp and not ev:
        return None, issues
    d_first = min(list(dp) + list(ev))
    d_last = max(list(dp) + list(ev))
    codes = {c for x in dp.values() for c in x} | {str(r["code"]) for x in ev.values() for r in x}
    K = load_kline(codes, d_first, (dt.date.fromisoformat(d_last) + dt.timedelta(days=12)).isoformat())
    cal = sorted(K.get("IDX", {})) or cal_all
    T = [d for d in cal if d_first <= d <= d_last]
    for d in set(ev) | set(dp):
        if d not in K.get("IDX", {}):
            issues["含非交易日键(节假日, 已忽略)"] += 1
    nxt = lambda d: cal[bisect.bisect_right(cal, d)] if bisect.bisect_right(cal, d) < len(cal) else None
    run = {}       # code → 已连续持有天数(截至上一交易日收盘)
    trunc = set()  # 持有起点早于数据起点
    cards, flats = [], []
    flows = fund_flows(sk)
    first_dp = min(dp) if dp else None
    prevD = None
    for D in T:
        H0 = {c: p for c, p in (dp.get(prevD) or {}).items() if float(p.get("position_percent") or 0) > 0} if prevD and prevD in dp else None
        if dp and D not in dp and D >= first_dp:
            issues["day_positions 缺交易日"] += 1
        cur = dp.get(D)
        H1 = {c: p for c, p in (cur or {}).items() if float(p.get("position_percent") or 0) > 0} if cur is not None else None
        E, IE = ev.get(D, []), ie.get(D, [])
        if not E and not H0 and not H1 and not any(str(p.get("op")) not in ("0",) for p in (cur or {}).values()):
            if cur is not None or prevD in dp:
                flats.append(D)
            prevD = D
            run = {}
            continue
        cards.append(card(sk, D, prevD, H0, cur, H1, E, IE, K, nxt(D), run, trunc, zt, up, repo, issues, flows.get(D)))
        # 更新连续持有天数(用 D 收盘仓位)
        if H1 is not None:
            nr = {}
            for c in H1:
                nr[c] = run.get(c, 0) + 1
                if c not in run and D == first_dp and str(H1[c].get("op")) != "3":   # 数据首日就持有且不是当日新开 = 起点在数据之前
                    trunc.add(c)
            for c in list(trunc):
                if c not in nr:
                    trunc.discard(c)
            run = nr
        prevD = D
    return {"cards": cards, "flats": flats, "T": T}, issues


def held_days(c, run, trunc):
    n = run.get(c)
    if not n:
        return "?"
    return f"≥{n}天" if c in trunc else f"{n}天"


def classify_sell(r):
    fe, q = r.get("feat") or {}, r.get("_rt") or {}
    res = r.get("result") or {}
    og = fe.get("open_pct")
    vpc = q.get("vs_prev_close", fe.get("buy_pct"))
    vo = q.get("vs_open", fe.get("vs_open"))
    pos = q.get("pos_so_far")
    pnl = res.get("pnl")
    gap = "高开" if og is not None and og >= 0.02 else "低开" if og is not None and og <= -0.02 else ""
    tb = tbucket(r.get("time"))
    if q.get("at_limit") or q.get("touched_limit") or fe.get("at_limit"):
        w = "板上卖"
    elif pnl is not None and pnl < 0 and vpc is not None and vpc < 0:
        w = "砍仓"
    elif (vo is not None and vo >= 0.02) or (pos is not None and pos >= 0.8):
        w = "冲高卖"
    elif vo is not None and vo <= -0.02:
        w = "回落卖"
    else:
        w = {"竞价": "竞价卖", "开盘5分钟": "开盘卖", "尾盘": "尾盘卖"}.get(tb, "盘中卖")
    return gap + w


def classify_buy(r, new, keep):
    fe, q = r.get("feat") or {}, r.get("_rt") or {}
    vpc = q.get("vs_prev_close", fe.get("buy_pct"))
    if q.get("at_limit") or fe.get("at_limit"):
        return ("打板建仓" if keep else "板上买(当日走)") if new else "板上加仓"
    if not new:
        return "下跌加仓" if vpc is not None and vpc < 0 else "上涨加仓"
    tb = tbucket(r.get("time"))
    return tb + ("建仓" if keep else "买(当日走)")


def rt_str(r):
    q = r.get("_rt")
    fe = r.get("feat") or {}
    if not q:
        return f"成交价较昨收 {pc(fe.get('buy_pct'))}" if fe.get("buy_pct") is not None else ""
    s = [f"开盘后{q['mins_from_open']}分" if q.get("mins_from_open") is not None else None,
         f"较昨收{pc(q.get('vs_prev_close'))}", f"较开{pc(q.get('vs_open'))}",
         f"日内位置{q['pos_so_far']:.2f}" if q.get("pos_so_far") is not None else None,
         f"5分动量{pc(q.get('mom5'))}" if q.get("mom5") is not None else None,
         "封板中" if q.get("at_limit") else "炸板后" if q.get("broke_limit") else "曾触板" if q.get("touched_limit") else None]
    return ", ".join(x for x in s if x)


def bg_str(fe):
    if not fe or fe.get("pct_prev") is None:
        return ""
    s = [f"昨{pc(fe['pct_prev'])}" + ("(涨停)" if fe.get("zt_prev") else "(炸板)" if fe.get("zb_prev") else ""),
         f"{fe['H_prev']}连板" if fe.get("H_prev") else None,
         f"5日{pc(fe.get('ret5_prev'), 0)}" if fe.get("ret5_prev") is not None else None,
         f"20日位置{fe['pos20_prev']:.2f}" if fe.get("pos20_prev") is not None else None,
         f"换手{fe['turn_prev']:.0f}%" if fe.get("turn_prev") is not None else None,
         f"流通{fe['fmcap_prev_e8']:.0f}亿" if fe.get("fmcap_prev_e8") is not None else None,
         "昨龙虎榜" if fe.get("lhb_prev") else None,
         ("题材 " + "/".join(fe["themes"][:3])) if fe.get("themes") else None]
    return " ".join(x for x in s if x)


FLOW_MIN_PCT, FLOW_MIN_YUAN = 0.03, 300   # 10/18 晚: 资金进出 ≥ 昨日总资产 3% 且 ≥300 元才标(净值指数 4 位小数的舍入误差远小于此)


def fund_flows(sk):
    """10/18 晚用户令: 识别入金 / 出金, 免得"满仓还加仓"被误读成手法。
    nav_daily.json 的 index_list 同时有 asset(总资产, 元) 和 index(净值指数, 不受出入金影响):
      资金进出 = asset_t − asset_{t−1} × index_t / index_{t−1}(正 = 入金, 负 = 出金); 返回 {iso 日: (金额, 占昨日总资产比例)}"""
    f = ROOT / "downloads" / "tzzb" / sk / "nav_daily.json"
    try:
        L = json.loads(f.read_text(encoding="utf-8"))["ex_data"]["index_list"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    out, prev = {}, None
    for x in sorted(L, key=lambda x: x.get("date") or ""):
        try:
            a, i = float(x["asset"]), float(x["index"])
        except (KeyError, TypeError, ValueError):
            continue
        if prev and prev[0] > 0 and prev[1] > 0:
            fl = a - prev[0] * i / prev[1]
            if abs(fl) >= max(FLOW_MIN_PCT * prev[0], FLOW_MIN_YUAN):
                out[iso(x["date"])] = (round(fl, 2), fl / prev[0])
        prev = (a, i)
    return out


def card(sk, D, prevD, H0, cur, H1, E, IE, K, N, run, trunc, zt, up, repo, issues, flow=None):
    wd = WD[dt.date.fromisoformat(D).weekday()]
    ix = K["IDX"].get(D)
    tags = []
    L = []
    # 大盘
    mk = [f"上证 开{pc(kpct(ix, 'o'), 2)} 收{pc(kpct(ix, 'c'), 2)}" if ix else "上证 ?"]
    if D in zt:
        mk.append(f"涨停 {zt[D]} 家")
    if D in up:
        mk.append(f"上涨占比 {up[D] * 100:.0f}%")
    L.append("- 大盘: " + " | ".join(mk))
    if flow:   # 资金进出: 当天仓位 % 的变化有一部分是钱进出, 不全是加减仓
        kind = "疑似入金" if flow[0] > 0 else "疑似出金"
        L.append(f"- 资金: {kind} {flow[0]:+,.0f} 元(约昨日总资产 {flow[1] * 100:+.0f}%) — 当天仓位占比的变化有一部分来自资金进出, 不全是加减仓")
        tags.append(kind)
    names = {}
    for src in (H0 or {}, cur or {}):
        for c, p in src.items():
            names.setdefault(c, p.get("name") or c)
    for r in E:
        names.setdefault(str(r["code"]), r.get("name") or str(r["code"]))
    by_code = collections.defaultdict(list)
    for r in E:
        by_code[str(r["code"])].append(r)
    # 昨收持仓
    s0 = sum(float(p.get("position_percent") or 0) for p in (H0 or {}).values())
    if H0 is None:
        L.append("- 昨收持仓: (无数据)")
    elif not H0:
        L.append("- 昨收持仓: 空仓" + (f"(逆回购 {pp(repo.get(prevD))})" if repo.get(prevD) else ""))
    else:
        it = []
        for c, p in sorted(H0.items(), key=lambda x: -float(x[1].get("position_percent") or 0)):
            rate = p.get("rate")
            it.append(f"{names[c]} {pp(float(p.get('position_percent') or 0))}(浮{pc(float(rate)) if rate is not None else '?'}, 持{held_days(c, run, trunc)})")
        L.append(f"- 昨收持仓(合计 {pp(s0)}): " + "; ".join(it))
    # 竞价
    aus = [auc_line(D, c, names[c]) for c in list((H0 or {}).keys()) + [c for c in by_code if c not in (H0 or {})]]
    aus = [a for a in aus if a]
    if aus:
        L.append("- 竞价(9:25): " + " | ".join(aus[:8]))
    # 成交
    held_before = set(H0 or {})
    bought_new = set()
    sold_clear, sells_pnl = set(), []
    first_side = {}
    if E:
        L.append("- 成交:")
    for r in E:
        c = str(r["code"])
        first_side.setdefault(c, r["side"])
        fe = r.get("feat") or {}
        px = r.get("vwap")
        head = f"  - {(r.get('time') or '?')[:8]} {r['side']} {names[c]}({c}) @{px if px is not None else '?'} ×{r.get('nlegs') or '?'}腿"
        if r["side"] == "买":
            new = bool(r.get("new_open")) and c not in held_before
            lab = classify_buy(r, new, H1 is None or c in H1)
            if new:
                bought_new.add(c)
            tags.append(lab)
            sub = [x for x in (r.get("play_subs") or []) if x][:3]
            extra = [f"[{r.get('play') or '?'}{('/' + '/'.join(sub)) if sub else ''}]", "新开" if new else "加仓/回补",
                     f"开盘{pc(fe.get('open_pct'))}" if fe.get("open_pct") is not None else None]
            st = rt_str(r)
            bg = bg_str(fe)
            L.append(head + " " + " ".join(x for x in extra if x) + (f" | 时点: {st}" if st else "") + (f" | 背景: {bg}" if bg else ""))
        else:
            lab = classify_sell(r)
            tags.append(lab)
            res = r.get("result") or {}
            pnl = res.get("pnl")
            if pnl is not None:
                sells_pnl.append(pnl)
            kd = K.get(c, {}).get(D)
            after = (kd["c"] / px - 1) if kd and px else None
            extra = [f"[{r.get('sell_kind') or '?'}]", f"盈亏{pc(pnl)}" if pnl is not None else None,
                     f"持{res['hold_days']}天" if res.get("hold_days") is not None else None,
                     f"开盘{pc(fe.get('open_pct'))}" if fe.get("open_pct") is not None else None,
                     f"卖后当日收较卖价{pc(after)}" if after is not None else None]
            st = rt_str(r)
            L.append(head + " " + " ".join(x for x in extra if x) + (f" | 时点: {st}" if st else ""))
    # 仓位变化(按代码)
    ch = []
    for c in sorted(set((cur or {}).keys()) | set(by_code) | set(held_before),
                    key=lambda c: (-max(float((H0 or {}).get(c, {}).get("position_percent") or 0), float((cur or {}).get(c, {}).get("position_percent") or 0)), c)):
        a = float((H0 or {}).get(c, {}).get("position_percent") or 0)
        e = (cur or {}).get(c)
        b = float(e.get("position_percent") or 0) if e else 0.0
        op = str(e.get("op")) if e else ("4" if c in held_before and cur is not None else None)
        if c in held_before and (cur is not None) and (not e or b <= 0.005):
            sold_clear.add(c)
        if c not in by_code and op in (None, "0"):
            continue
        if c not in by_code and op not in (None, "0"):
            issues["账本仓位有变动但无成交事件"] += 1
        if c in by_code and cur is not None and c not in cur and c not in held_before:
            issues["有成交但当日仓位表无此票"] += 1
        ch.append(f"{names[c]} {pp(a)}→{pp(b)}" + (f"({OP.get(op, 'op' + op)})" if op else ""))
    if ch:
        s1 = sum(float(p.get("position_percent") or 0) for p in (H1 or {}).values())
        L.append(f"- 仓位: 合计 {pp(s0) if H0 is not None else '?'}→{pp(s1) if H1 is not None else '?'}; " + "; ".join(ch[:12]) + (f" 等 {len(ch)} 只" if len(ch) > 12 else ""))
    # 未动持仓
    still = [c for c in (H0 or {}) if c not in by_code and c not in sold_clear and str(((cur or {}).get(c) or {}).get("op") or "0") == "0"]
    if still:
        it = []
        for c in still:
            k = K.get(c, {}).get(D)
            it.append(f"{names[c]} 开{pc(kpct(k, 'o'))} 高{pc(kpct(k, 'h'))} 收{pc(kpct(k, 'c'))}" if k else f"{names[c]} (无日线)")
            if not k:
                issues["持仓票缺当日日线"] += 1
        L.append("- 未动持仓: " + "; ".join(it[:10]) + (f" 等 {len(it)} 只" if len(it) > 10 else ""))
    # 日内回合(当日买进又卖出、昨收不持有的票)
    rts = []
    for c, rs in by_code.items():
        if c in held_before or {r["side"] for r in rs} != {"买", "卖"}:
            continue
        b = [r for r in rs if r["side"] == "买" and r.get("vwap")]
        s = [r for r in rs if r["side"] == "卖" and r.get("vwap")]
        if not b or not s:
            continue
        wb = sum(r["vwap"] * (r.get("nlegs") or 1) for r in b) / sum(r.get("nlegs") or 1 for r in b)
        ws = sum(r["vwap"] * (r.get("nlegs") or 1) for r in s) / sum(r.get("nlegs") or 1 for r in s)
        t0, t1 = b[0].get("time") or "", s[-1].get("time") or ""
        dur = ""
        if len(t0) >= 8 and len(t1) >= 8:
            sec = (int(t1[:2]) * 3600 + int(t1[3:5]) * 60 + int(t1[6:8])) - (int(t0[:2]) * 3600 + int(t0[3:5]) * 60 + int(t0[6:8]))
            if sec >= 0:
                dur = f", 首买到末卖 {sec}秒" if sec < 120 else f", 首买到末卖 {sec // 60}分"
        rts.append(f"{names[c]} 买均{wb:g}→卖均{ws:g} {pc(ws / wb - 1, 2)}{dur}")
    if rts:
        L.append("- 日内回合: " + "; ".join(rts[:8]) + (f" 等 {len(rts)} 个" if len(rts) > 8 else ""))
    # 日内事件(只取 event + evidence, 不取 hyp 推断)
    if IE:
        it = []
        for r in IE:
            ev_ = r.get("evidence") or {}
            nm = "→".join(r.get("names") or [])
            bits = []
            for k, v in ev_.items():
                if v in (None, "未知") or k in FUTURE_EV:
                    continue
                if isinstance(v, bool):
                    v = "是" if v else "否"
                elif isinstance(v, float):
                    v = pc(v) if ("盈亏" in k or k.endswith("-1")) else f"{v:.0f}" if "分钟" in k else f"{v:.3g}"
                bits.append(f"{k}={v}")
            it.append(f"{r.get('event')}({nm}{'; ' + ', '.join(bits[:3]) if bits else ''})")
        L.append("- 盘中事件: " + "; ".join(it[:8]) + (f" 等 {len(it)} 条" if len(it) > 8 else ""))
    # 日级标签
    for c, rs in by_code.items():
        sides = {r["side"] for r in rs}
        if sides == {"买", "卖"}:
            tags.append("正T" if first_side[c] == "买" and c in held_before else "日内来回" if c not in held_before else "反T")
    s1 = sum(float(p.get("position_percent") or 0) for p in (H1 or {}).values()) if H1 is not None else None
    if (repo.get(D) or 0) < 0:
        issues["逆回购仓位为负(原样显示)"] += 1
    day = []
    if sold_clear and bought_new:
        day.append(("满仓换股" if s0 >= 0.9 else "换股"))
    if H0 is not None and s0 <= 0.005 and bought_new & set(H1 or {}):
        day.append("空仓→建仓")
    if H0 and s1 is not None and s1 <= 0.005:
        day.append("清仓离场")
    if not E:
        day.append("持仓不动" if not ch else "仓位变动无成交明细")
    if s1 is not None and s1 >= 0.95:
        day.append("收盘满仓")
    if sells_pnl and all(x < 0 for x in sells_pnl):
        day.append("卖出全亏")
    seen, tg = set(), []
    for t in day + tags:
        if t not in seen:
            seen.add(t)
            tg.append(t)
    # 结果(次日)
    if N is None:
        res_line = "- 结果: 次日数据未到"
    else:
        it = []
        sold_px = collections.defaultdict(list)
        for r in E:
            if r["side"] == "卖" and r.get("vwap"):
                sold_px[str(r["code"])].append(r["vwap"])
        for c, pxs in sold_px.items():
            kn = K.get(c, {}).get(N)
            if kn:
                avg = sum(pxs) / len(pxs)
                x = kn["c"] / avg - 1
                kd = K.get(c, {}).get(D)
                rest = f", 余仓 {pp(float(H1[c].get('position_percent') or 0))} 次日{pc(kn['c'] / kd['c'] - 1)}" if H1 and c in H1 and kd and kd.get("c") else ""
                it.append(f"{names[c]} 卖后次日收较卖价{pc(x)}" + ("(卖飞)" if x >= FLY else "(逃顶)" if x <= -FLY else "") + rest)
            else:
                rn = next((r.get("result", {}).get("r_next_after_sell") for r in E if str(r["code"]) == c and r["side"] == "卖"
                           and (r.get("result") or {}).get("r_next_after_sell") is not None), None)
                it.append(f"{names[c]} 卖后次日{pc(rn)}(cases_auto 口径)" if rn is not None else f"{names[c]} 卖后次日 ?")
        for c, p in sorted((H1 or {}).items(), key=lambda x: -float(x[1].get("position_percent") or 0)):
            if c in sold_px:
                continue
            k, kn = K.get(c, {}).get(D), K.get(c, {}).get(N)
            x = kn["c"] / k["c"] - 1 if k and kn and k["c"] else None
            it.append(f"{names[c]}({'新开' if c in bought_new else '持'}) 次日{pc(x)}")
        res_line = f"- 结果(次日 {N[5:]}): " + ("; ".join(it[:12]) + (f" 等 {len(it)} 只" if len(it) > 12 else "") if it else "无持仓无卖出")
    L.append(res_line)
    title = f"### {D} 周{wd} | " + (" / ".join(tg) if tg else "—")
    return {"date": D, "tags": tg, "md": title + "\n" + "\n".join(L) + "\n", "n_act": len(E)}


def write_if_changed(f, s):
    if f.exists() and f.read_text(encoding="utf-8") == s:
        return False
    f.write_text(s, encoding="utf-8")
    return True


def load_annot(sk):
    """10/18 日卡解读(scripts/tzzb/case_annotate.py 写 case_log/annotations.jsonl; 同一日期多条取最后一条)"""
    f = ROOT / "skills" / f"{sk}-skill" / "persona" / "case_log" / "annotations.jsonl"
    A = {}
    if f.exists():
        for l in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(l)
                A[r["date"]] = r
            except (ValueError, KeyError):
                continue
    return A


def annot_line(a):
    hyp = " / ".join(f"{h.get('h')} {round(float(h.get('p') or 0) * 100)}%" for h in (a.get("why") or [])[:3])
    rules = "/".join(a.get("rules") or []) or "无"
    return (f"- 解读(模型推测, {a.get('by', '?')}): 手法类={a.get('class', '?')}; 动机: {hyp or '?'}; 对应规则 {rules}"
            + ("; **新手法候选**" if a.get("new") else "") + (f"; 备注: {a['note']}" if a.get("note") else ""))


def render(sk, R, dry=False):
    out = ROOT / "skills" / f"{sk}-skill" / "persona" / "case_log"
    name = M.get(sk).get("name") or sk
    ann = load_annot(sk)
    for c in R["cards"]:   # 10/18: 有解读的日卡末尾加解读行(结果行之后); 当日无成交的机械标一句
        if c["date"] in ann:
            c["md"] = c["md"].rstrip("\n") + "\n" + annot_line(ann[c["date"]]) + "\n"
            if ann[c["date"]].get("class"):
                c["tags"] = c["tags"] + [f"【{ann[c['date']]['class']}】"]
        elif not c.get("n_act"):
            c["md"] = c["md"].rstrip("\n") + "\n- 解读(机械): 当日无成交, 持仓不动\n"
    months = collections.defaultdict(list)
    for c in R["cards"]:
        months[c["date"][:7]].append(c)
    files = {}
    head = (f"> 机械生成(scripts/tzzb/case_log.py, 零 token): 每个有持仓或成交的交易日一张卡。卡内只用当日及以前的信息, 唯一例外是标明的「结果(次日)」行。\n"
            "> 字段: 昨收持仓=仓位占总资产(浮=该票持仓盈亏, 持N天=截至昨收连续持有); 时点=成交那一分钟的盘中状态(日内位置 0=此前最低 1=此前最高, >1 / <0 = 成交即创日内新高 / 新低); "
            "背景=昨日及以前的个股状态; 仓位 op: 新开/清仓/加仓/减仓/有买有卖; 卖飞/逃顶=卖后次日收较卖价 ≥+3% / ≤-3%。\n")
    for m, cs in sorted(months.items()):
        files[f"{m}.md"] = f"# {name}({sk}) 操作日志 {m}\n\n" + head + "\n" + "\n".join(c["md"] for c in cs)
    flats = R["flats"]
    runs = []
    pos = {d: i for i, d in enumerate(R["T"])}
    for d in flats:
        if runs and pos[d] > 0 and runs[-1][1] == R["T"][pos[d] - 1]:
            runs[-1][1] = d
            runs[-1][2] += 1
        else:
            runs.append([d, d, 1])
    lines = [(c["date"], f"- [{c['date']}]({c['date'][:7]}.md#{c['date']}) {' / '.join(c['tags']) or '—'}") for c in R["cards"]]
    lines += [(a, f"- {a}" + (f"~{b}" if b != a else "") + f" 空仓 {n} 日(无卡)") for a, b, n in runs]
    lines.sort(key=lambda x: x[0], reverse=True)
    tc = collections.Counter(t for c in R["cards"] for t in c["tags"])
    files["index.md"] = (f"# {name}({sk}) 操作日志索引\n\n> 共 {len(R['cards'])} 张日卡({R['cards'][0]['date'] if R['cards'] else '-'}~{R['cards'][-1]['date'] if R['cards'] else '-'}), "
                         f"空仓 {len(flats)} 日; 月文件 {len(months)} 个。标签频次: " + ", ".join(f"{k} {v}" for k, v in tc.most_common(15)) + "\n\n"
                         + "\n".join(l for _, l in lines) + "\n")
    if dry:
        return files, 0
    out.mkdir(parents=True, exist_ok=True)
    n = sum(write_if_changed(out / f, s) for f, s in files.items())
    for f in out.glob("*.md"):
        if f.name not in files:
            f.unlink()
    return files, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    ids = a.ledger.split(",") if a.ledger else M.ids("tzzb")
    zt, up, prevs = market_breadth()
    cal_all = idx_calendar()
    resolve_prev(prevs, cal_all, zt, up)
    summ = {}
    for sk in ids:
        t1 = time.time()
        try:
            R, iss = build(sk, zt, up, cal_all)
            if R is None:
                print(f"{sk}: 无 day_positions 也无 cases_auto, 跳过")
                continue
            files, nw = render(sk, R, a.dry)
        except Exception as e:   # noqa: BLE001  一个导师失败不拖垮全体
            import traceback
            traceback.print_exc()
            print(f"{sk}: 失败 {type(e).__name__}: {e}")
            summ[sk] = {"失败": str(e)}
            continue
        summ[sk] = {"日卡": len(R["cards"]), "空仓日": len(R["flats"]), "月文件": len(files) - 1, "改写": nw, "成交": sum(c["n_act"] for c in R["cards"]),
                    "数据问题": dict(iss)}
        print(f"{sk}: 日卡 {len(R['cards'])}, 空仓 {len(R['flats'])}, 月 {len(files) - 1}, 改写 {nw} 文件, 数据问题 {dict(iss)} ({time.time() - t1:.1f}s)")
    print(f"总耗时 {time.time() - t0:.1f}s")
    print("JSON:" + json.dumps(summ, ensure_ascii=False))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
