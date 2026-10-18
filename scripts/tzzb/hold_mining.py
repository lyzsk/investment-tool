# -*- coding: utf-8 -*-
"""hold_mining.py — 从导师全部历史买卖腿里挖"遇到什么情况、他怎么处理"(10/18 用户令: 把 cases / rules 加厚; 零 token, 只读)

为什么: 指纹(mentor_fingerprint)已挖了"选什么票 / 什么时候买", 但"持仓遇到高开 / 低开 / 涨停 / 浮亏 / 大盘跌时怎么处理"
        (=日积月累的手法)没有系统统计; cases.md 只记显著的, 规则漏斗升不上来。本脚本把每个持仓日都当一个样本。
样本: 前一交易日收盘持有的每只票 × 当日 = 一个"持仓日"(day_positions 前后两日对比 + 行情库日线 + 成交腿时刻)
  动作: 清仓 / 减仓(仓位降 >8pp) / 加仓(升 >8pp) / 持有;  卖出时刻取成交腿最早一笔
  情境: 开盘缺口档 / 昨日是否涨停 / 持仓浮盈档 / 已持天数 / 大盘当日开盘档 / 当日盘中最高涨幅档
  结果: 卖出 → 卖后次日收盘相对卖出日收盘(正=卖飞); 持有 → 次日涨跌
挖掘: 每个单项情境下动作分布 vs 基线; 样本 ≥ MIN_N 且某动作占比 ≥ 55% 或是基线 ×1.6 → "手法候选"
10/18 加厚(三节追加在单项节之后):
  ① 组合情境: 两个单项同时成立(如 开盘高开2~5% × 浮盈≥10%), 门槛 max(10, 2×MIN_N), 且占比要比两个单项各自的占比再高 ≥10pp 才算"组合有新信息"
  ② 序列情境(账户日级): 他前一天 / 前几天做了什么(亏损卖出 / 清仓离场 / 连续几天没动 / 新开仓 …) → 今天新开仓 / 卖出 / 加减总仓位 / 不动 的比例 vs 基线(更常 / 更少都记)
  ③ 建仓侧: 新开仓的仓位(收盘仓位占比)按买点类型 play / 买入时段分组; 加仓买入(昨收已持有的票当日又买)发生在什么情境、加仓时票当日涨跌 / 加仓前浮盈分布
10/18 17:20 用户定: 验证从"一刀切 70/30"改成滚动(walk-forward) —— 短线导师打法随阶段变。按该导师自己的交易日序列, 训练窗 W 日挖 → 紧接 H 日验 → 整体后滑 H 日,
  每条规律 = 它在哪些训练窗被挖出 → 对应验证窗通过多少; 结论: 近期有效 / 曾有效·近期失效 / 过时 / 不稳定 / 样本不足(定义见 verdict())。
  报告里的 n / 占比 = 全样本合计(描述用), 规律是否站得住只看滚动结论。
产物: scripts/tzzb/model_out/reports/hold_mining_<导师>.md(给蒸馏读) + hold_mining_<导师>.json(机器读)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/hold_mining.py [--ledger a,b] [--skip a,b] [--min-n 5] [--win 40 --hold 10] [--min-test 3]
"""
import argparse
import collections
import datetime as dt
import itertools
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
import a_rules as AR        # noqa: E402
import mentors as M         # noqa: E402
from kline_db import db     # noqa: E402

OUT = ROOT / "scripts" / "tzzb" / "model_out" / "reports"
REPO = ("204", "1318", "GC")
ACT_TH = 0.08
CAP = 15          # 组合 / 序列 / 加仓情境 每节最多列几条
CAP_SINGLE = 25   # 单项节最多列几条
DAY_TH = 0.10     # 日级: 总仓位升 / 降 >10pp 算加 / 减总仓位
RECENT = 3        # "近期" = 最后 3 个滚动窗
RANK = {"近期有效": 0, "曾有效·近期失效": 1, "不稳定": 2, "过时": 3, "样本不足": 4}


def bucket_gap(x):
    if x is None:
        return None
    return "低开≤-5%" if x <= -0.05 else "低开-5~-2%" if x <= -0.02 else "平开±2%" if x < 0.02 else "高开2~5%" if x < 0.05 else "高开≥5%"


def bucket_rate(x):
    if x is None:
        return None
    return "浮亏≥10%" if x <= -0.10 else "浮亏0~10%" if x < 0 else "浮盈0~10%" if x < 0.10 else "浮盈≥10%"


def bucket_hold(n):
    return "持1天" if n <= 1 else "持2~3天" if n <= 3 else "持4天+"


def bucket_high(x):
    if x is None:
        return None
    return "盘中最高<+2%" if x < 0.02 else "盘中最高+2~6%" if x < 0.06 else "盘中最高≥+6%"


def bucket_idx(x):
    if x is None:
        return None
    return "大盘低开≤-0.5%" if x <= -0.005 else "大盘高开≥+0.5%" if x >= 0.005 else "大盘平开"


FEATS = {"开盘": lambda s: bucket_gap(s["gap"]), "昨日": lambda s: "昨日涨停" if s["zt_prev"] else None,
         "浮盈": lambda s: bucket_rate(s["rate"]), "持有天数": lambda s: bucket_hold(s["hold"]),
         "盘中": lambda s: bucket_high(s["high"]), "大盘": lambda s: bucket_idx(s["idx_gap"])}
PAIR_FEATS = {f"{n1}×{n2}": (lambda f1, f2: lambda s: (f"{f1(s)} × {f2(s)}" if f1(s) and f2(s) else None))(f1, f2)
              for (n1, f1), (n2, f2) in itertools.combinations(FEATS.items(), 2)}


def tb_sell(t):
    return "竞价" if t < "09:30" else "开盘5分钟" if t < "09:35" else "上午" if t < "11:31" else "午后" if t < "14:30" else "尾盘"


def tb_buy(t):
    if not t:
        return "无时刻"
    t = t[:5]
    return "竞价" if t < "09:30" else "开盘5分钟" if t < "09:35" else "早盘(-10:30)" if t < "10:30" else "上午" if t < "11:31" else "午后" if t < "14:30" else "尾盘"


def _med(xs):
    return statistics.median(xs) if xs else None


def load_kline(codes, d0, d1):
    syms = {AR.symbol(c): c for c in codes if c and c[:3] not in REPO and len(c) == 6}
    syms["sh000001"] = "IDX"
    out = collections.defaultdict(dict)
    if not syms:
        return out
    conn = db()
    try:
        cur = conn.cursor()
        ks = list(syms)
        for i in range(0, len(ks), 400):
            part = ks[i:i + 400]
            cur.execute("select symbol, trade_date, cast(open as double), cast(high as double), cast(low as double), cast(close as double), "
                        "cast(pre_close as double), cast(limit_up as double) from kline_day where is_deleted=0 and trade_date between %s and %s "
                        f"and symbol in ({','.join(['%s'] * len(part))})", [d0, d1] + part)
            for sym, td, o, h, l, c, pc, lu in cur.fetchall():
                code = syms[sym] if sym != "sh000001" else "IDX"
                out[code][str(td)] = {"o": o, "h": h, "l": l, "c": c, "pc": pc, "lu": lu}
    finally:
        conn.close()
    return out


# ---------- 滚动验证引擎 ----------
def make_windows(T, W, H):
    """T = 交易日序列(iso); 返回 [(训练起, 训练止, 验证起, 验证止)], 末窗验证段可不足 H 日"""
    out, i = [], 0
    while i + W < len(T):
        tr, te = T[i:i + W], T[i + W:i + W + H]
        out.append((tr[0], tr[-1], te[0], te[-1]))
        i += H
    return out


def walk(wins, items, discover, check):
    """每个窗: discover(训练段) → {规律键: info}; check(键, info, 训练段, 验证段) → True / False / None(验证段样本不足)"""
    hist = collections.defaultdict(list)
    for k, (a, b, c, d) in enumerate(wins):
        tr = [x for x in items if a <= x["date"] <= b]
        te = [x for x in items if c <= x["date"] <= d]
        if not tr:
            continue
        for key, info in discover(tr).items():
            hist[key].append((k, check(key, info, tr, te), info))
    return hist


def verdict(h, wins):
    """h = [(窗序号, 通过?)]; 近期有效 = 最近一次有样本的验证窗落在最后 RECENT 窗内且通过, 且通过率 ≥60%;
    曾有效·近期失效 = 通过率 ≥60% 但最近一次验证(在最后 RECENT 窗内)没过; 过时 = 通过过, 但最后一次通过早于最后 RECENT 窗; 其余 = 不稳定"""
    nwin = len(wins)
    ev = [(k, r) for k, r, *_ in h if r is not None]
    if not ev:
        return {"status": "样本不足", "found": len(h), "eval": 0, "pass": 0, "last_train": last_train(h, wins),
                "text": f"滚动验证: 样本不足(在 {len(h)} 个训练窗里挖出, 对应验证窗样本都不够)"}
    ps = [k for k, r in ev if r]
    rate = len(ps) / len(ev)
    lk, lr = ev[-1]
    recent = lk >= nwin - RECENT
    if lr and recent and rate >= 0.6:
        st = "近期有效"
    elif rate >= 0.6 and recent and not lr:
        st = "曾有效·近期失效"
    elif ps and max(ps) < nwin - RECENT and sum(1 for k, r in ev if k <= max(ps) and r) / sum(1 for k, r in ev if k <= max(ps)) >= 0.6:
        st = "过时"   # 早期(截至最后一次通过)通过率 ≥60%, 但最后 RECENT 窗没再成立
    else:
        st = "不稳定"
    first, last = (wins[ps[0]][2], wins[ps[-1]][3]) if ps else (None, None)
    txt = (f"滚动验证: {st}(验证通过 {len(ps)}/{len(ev)} 窗, 最近一次验证窗 {wins[lk][2]}~{wins[lk][3]} {'通过' if lr else '未通过'}"
           + ("" if recent else f", 不在最后 {RECENT} 窗内") + "; " + (f"成立区间 {first}~{last}" if ps else "从未通过")
           + ("; 仅 1 窗验证, 证据弱" if st == "近期有效" and len(ev) == 1 else "") + ")")
    return {"status": st, "found": len(h), "eval": len(ev), "pass": len(ps), "rate": round(rate, 2), "last_win": [wins[lk][2], wins[lk][3]],
            "last_pass": lr, "first_ok": first, "last_ok": last, "text": txt, "last_train": last_train(h, wins)}


def last_train(h, wins):
    """最近一次被挖出的训练窗里的占比 / 窗内基线(全样本占比会被阶段平均掉, 这个更贴近他最近的样子)"""
    k, _, info = h[-1] if h and len(h[-1]) > 2 else (None, None, None)
    if k is None or not info or "share" not in info or "base" not in info:
        return None
    return {"win": [wins[k][0], wins[k][1]], "share": round(info["share"], 3), "base": round(info["base"], 3)}


def lt_text(wf):
    t = wf.get("last_train")
    return f"; 最近挖出的训练窗 {t['win'][0]}~{t['win'][1]} 内 {t['share']:.0%}(窗内基线 {t['base']:.0%})" if t else ""


def fam_hold(samples, feats, acts, actf, min_n, wins, min_test, comp_gap=None):
    """持仓日样本上的"情境 → 动作"规律(单项 / 组合 / 加仓买入共用)。comp_gap: 组合要求占比比两个单项各高这么多"""
    def groups(ss, fs):
        g = collections.defaultdict(list)
        for s in ss:
            for fname, f in fs.items():
                v = f(s)
                if v:
                    g[(fname, v)].append(s)
        return g

    def discover(tr):
        base = collections.Counter(actf(s) for s in tr)
        single = None
        if comp_gap is not None:
            single = {}
            for (fn, v), ss in groups(tr, FEATS).items():
                c = collections.Counter(actf(s) for s in ss)
                for a_ in acts:
                    single[(v, a_)] = c[a_] / len(ss)
        out = {}
        for (fname, v), ss in groups(tr, feats).items():
            if len(ss) < min_n:
                continue
            cnt = collections.Counter(actf(s) for s in ss)
            for a_ in acts:
                share = cnt[a_] / len(ss)
                bp = base[a_] / len(tr)
                lift = share / bp if bp else None
                if share >= 0.55 or (lift and lift >= 1.6 and cnt[a_] >= 3):
                    if single is not None:
                        v1, v2 = v.split(" × ")
                        if share - max(single.get((v1, a_), 0), single.get((v2, a_), 0)) < comp_gap:
                            continue
                    out[(fname, v, a_)] = {"strong": share >= 0.55, "share": share, "base": bp}
        return out

    def check(key, info, tr, te):
        fname, v, a_ = key
        f = feats[fname]
        tt = [s for s in te if f(s) == v]
        if len(tt) < min_test:
            return None
        bt = sum(1 for s in te if actf(s) == a_) / len(te)
        tsh = sum(1 for s in tt if actf(s) == a_) / len(tt)
        return tsh > bt and (tsh >= 0.55 if info["strong"] else (bt == 0 or tsh / bt >= 1.2))

    hist = walk(wins, samples, discover, check)
    base_all = collections.Counter(actf(s) for s in samples)
    pats = []
    for (fname, v, a_), h in hist.items():
        f = feats[fname]
        ss = [s for s in samples if f(s) == v]
        cnt = collections.Counter(actf(s) for s in ss)
        share = cnt[a_] / len(ss)
        bp = base_all[a_] / len(samples)
        wf = verdict(h, wins)
        sells = [s for s in ss if s["act"] in ("清仓", "减仓") and s["sell_t"]]
        nx = [s["next"] for s in ss if actf(s) == a_ and s["next"] is not None]
        ex = sorted((s for s in ss if actf(s) == a_), key=lambda s: s["date"], reverse=True)[:3]
        pats.append({"cond": v, "feat": fname, "n": len(ss), "act": a_, "share": round(share, 3), "base": round(bp, 3),
                     "lift": round(share / bp, 2) if bp else None,
                     "dist": {x: cnt[x] for x in acts if cnt[x]} if len(acts) > 1 else {a_: cnt[a_], "否": len(ss) - cnt[a_]},
                     "sell_time": dict(collections.Counter(tb_sell(s["sell_t"]) for s in sells)), "oos": wf["text"], "wf": wf,
                     "next_avg": round(sum(nx) / len(nx), 4) if nx else None, "next_n": len(nx),
                     "examples": [{k2: e[k2] for k2 in ("date", "name", "code", "gap", "high", "close", "rate", "hold", "sell_t", "next")} for e in ex]})
    pats.sort(key=lambda p: (RANK[p["wf"]["status"]], -p["wf"]["pass"], -p["n"] * abs(p["share"] - p["base"])))
    return pats


# ---------- 日级(序列)样本 ----------
def day_records(dp, tdays, iso, evs, K):
    def hold(k):
        return {str(p["code"]): p for p in (dp.get(k) or {}).get("list") or []
                if float(p.get("position_percent") or 0) > 0 and not str(p.get("code")).startswith(REPO)}
    by_day = collections.defaultdict(list)
    for (d, c), rs in evs.items():
        if not c.startswith(REPO):
            by_day[d].extend(rs)
    recs = []
    for a, b in zip(tdays, tdays[1:]):
        D = iso(b)
        H0, H1 = hold(a), hold(b)
        cur = {str(p["code"]): p for p in (dp.get(b) or {}).get("list") or [] if not str(p.get("code")).startswith(REPO)}
        s0 = sum(float(p["position_percent"]) for p in H0.values())
        s1 = sum(float(p["position_percent"]) for p in H1.values())
        E = by_day.get(D, [])
        sells = [r for r in E if r["side"] == "卖"]
        pnl = [x for x in ((r.get("result") or {}).get("pnl") for r in sells) if x is not None]
        new = sorted({c for c in H1 if c not in H0} | {str(r["code"]) for r in E if r["side"] == "买" and r.get("new_open") and str(r["code"]) not in H0})
        trade = bool(E) or any(str(p.get("op")) != "0" for p in cur.values())
        ix = K.get("IDX", {}).get(D)
        recs.append({"date": D, "s0": s0, "s1": s1, "new": new, "loss_sell": any(x < 0 for x in pnl), "win_only": bool(pnl) and all(x > 0 for x in pnl),
                     "trade": trade, "w_rate0": (sum(float(p["position_percent"]) * float(p.get("rate") or 0) for p in H0.values()) / s0) if s0 > 0 else None,
                     "idx": (ix["c"] / ix["pc"] - 1) if ix and ix.get("pc") else None,
                     "acts": {x for x, ok in (("新开仓", bool(new)), ("有卖出", bool(sells)), ("总仓位升>10pp", s1 - s0 > DAY_TH),
                                                ("总仓位降>10pp", s1 - s0 < -DAY_TH), ("无成交", not trade)) if ok}})
    idle = 0
    for i, r in enumerate(recs):   # 状态 = 前一天 / 前几天的事(只用过去)
        st = []
        if i >= 1:
            p = recs[i - 1]
            idle = idle + 1 if not p["trade"] else 0
            if p["loss_sell"]:
                st.append("昨日有亏损卖出")
            if p["win_only"]:
                st.append("昨日卖出全盈利")
            if p["s0"] > 0.005 and p["s1"] <= 0.005:
                st.append("昨日清仓离场")
            elif p["s1"] <= 0.005:
                st.append("昨收空仓(非刚清仓)")
            if p["new"]:
                st.append("昨日新开仓")
            if idle >= 3:
                st.append("已连续≥3日无成交")
            if p["idx"] is not None and p["idx"] <= -0.01:
                st.append("昨日大盘跌≥1%")
            if p["s1"] >= 0.9:
                st.append("昨收仓位≥90%")
            if i >= 2 and p["loss_sell"] and recs[i - 2]["loss_sell"]:
                st.append("连续2日亏损卖出")
        if r["w_rate0"] is not None:
            if r["w_rate0"] <= -0.05:
                st.append("昨收持仓加权浮亏≥5%")
            elif r["w_rate0"] >= 0.10:
                st.append("昨收持仓加权浮盈≥10%")
        r["state"] = st
    return recs


DACTS = ("新开仓", "有卖出", "总仓位升>10pp", "总仓位降>10pp", "无成交")
# 结构性必然(不是习惯)的组合不报: 昨收空仓 → 今天没东西可卖 / 没仓可降; 昨收近满仓 → 很难再升
TRIVIAL = {("昨日清仓离场", "有卖出", "更少"), ("昨日清仓离场", "总仓位降>10pp", "更少"), ("昨收空仓(非刚清仓)", "有卖出", "更少"),
           ("昨收空仓(非刚清仓)", "总仓位降>10pp", "更少"), ("昨收仓位≥90%", "总仓位升>10pp", "更少")}


def fam_seq(recs, wins, min_n, min_test):
    def discover(tr):
        bp = {x: sum(1 for r in tr if x in r["acts"]) / len(tr) for x in DACTS}
        out = {}
        for stv in sorted({x for r in tr for x in r["state"]}):
            ss = [r for r in tr if stv in r["state"]]
            if len(ss) < min_n:
                continue
            for a_ in DACTS:
                sh = sum(1 for r in ss if a_ in r["acts"]) / len(ss)
                more = sh >= bp[a_] + 0.15 and (bp[a_] == 0 or sh >= 1.5 * bp[a_])
                less = sh <= bp[a_] - 0.15 and sh <= 0.6 * bp[a_]
                d_ = "更常" if more else "更少" if less else None
                if d_ and (stv, a_, d_) not in TRIVIAL:
                    out[(stv, a_, d_)] = {"share": sh, "base": bp[a_]}
        return out

    def check(key, info, tr, te):
        stv, a_, d_ = key
        tt = [r for r in te if stv in r["state"]]
        if len(tt) < min_test:
            return None
        bt = sum(1 for r in te if a_ in r["acts"]) / len(te)
        tsh = sum(1 for r in tt if a_ in r["acts"]) / len(tt)
        return (tsh > bt and (bt == 0 or tsh / bt >= 1.2)) if d_ == "更常" else (bt > 0 and tsh < bt and tsh / bt <= 0.83)

    hist = walk(wins, recs, discover, check)
    out = []
    for (stv, a_, d_), h in hist.items():
        ss = [r for r in recs if stv in r["state"]]
        sh = sum(1 for r in ss if a_ in r["acts"]) / len(ss)
        bp = sum(1 for r in recs if a_ in r["acts"]) / len(recs)
        wf = verdict(h, wins)
        ex = [r["date"] for r in sorted(ss, key=lambda r: r["date"], reverse=True) if (a_ in r["acts"]) == (d_ == "更常")][:3]
        out.append({"cond": stv, "act": a_, "dir": d_, "n": len(ss), "share": round(sh, 3), "base": round(bp, 3), "oos": wf["text"], "wf": wf, "examples": ex})
    out.sort(key=lambda p: (RANK[p["wf"]["status"]], -p["wf"]["pass"], -p["n"] * abs(p["share"] - p["base"])))
    return out


# ---------- 建仓侧 ----------
def new_opens(dp, tdays, iso, evs, rtm):
    def hold(k):
        return {str(p["code"]): p for p in (dp.get(k) or {}).get("list") or []
                if float(p.get("position_percent") or 0) > 0 and not str(p.get("code")).startswith(REPO)}
    opens = []
    for a, b in zip(tdays, tdays[1:]):
        D = iso(b)
        H0, H1 = hold(a), hold(b)
        for c, p in H1.items():
            if c in H0:
                continue
            bs = sorted((r for r in evs.get((D, c), []) if r["side"] == "买"), key=lambda r: r.get("time") or "")
            f0 = bs[0] if bs else None
            q = (rtm.get((D, f0.get("time"), c, "买")) if f0 else None) or {}
            opens.append({"date": D, "code": c, "name": p.get("name"), "size": float(p["position_percent"]),
                          "play": (f0.get("play") if f0 else None) or "无成交明细", "tb": tb_buy(f0.get("time") if f0 else None),
                          "vs_pc": q.get("vs_prev_close", ((f0 or {}).get("feat") or {}).get("buy_pct"))})
    return opens


ADD_DISTS = (("add_daypct", "加仓那一刻票的当日涨跌", lambda s: None if s["add_pct"] is None else "加仓时跌≥3%" if s["add_pct"] <= -0.03 else "加仓时跌0~3%" if s["add_pct"] < 0
              else "加仓时涨0~3%" if s["add_pct"] < 0.03 else "加仓时涨≥3%"),
             ("add_rate", "加仓前(昨收)浮盈", lambda s: bucket_rate(s["rate"])),
             ("add_time", "加仓时段", lambda s: tb_buy(s["add_t"]) if s["add_t"] else None))


def fam_entry(opens, samples, wins, min_n, min_test, W):
    ent = {"n_open": len(opens)}
    if len(opens) >= min_n:
        sz = sorted(o["size"] for o in opens)
        mall = _med(sz)
        rec = [o["size"] for o in opens if wins and o["date"] > wins[-1][1]] if wins else []
        ent["size_all"] = {"n": len(sz), "median": round(mall, 3), "q1": round(sz[len(sz) // 4], 3), "q3": round(sz[(3 * len(sz)) // 4], 3),
                           "试仓<15%": round(sum(1 for x in sz if x < 0.15) / len(sz), 3), "重仓≥50%": round(sum(1 for x in sz if x >= 0.5) / len(sz), 3),
                           "recent_n": len(rec), "recent_median": round(_med(rec), 3) if rec else None}
        mt_open = max(2, min_test - 1)   # 新开仓稀疏: 验证窗里该组 ≥2 次就计
        for key, lab in (("play", "买点类型"), ("tb", "首笔买入时段")):
            def discover(tr, key=key):
                m = _med([o["size"] for o in tr])
                out = {}
                for v in sorted({o[key] for o in tr}):
                    xs = [o["size"] for o in tr if o[key] == v]
                    if len(xs) < 3:
                        continue
                    mv = _med(xs)
                    d_ = "偏大" if mv >= m * 1.25 else "偏小" if mv <= m * 0.8 else None
                    if d_:
                        out[(v, d_)] = {"m": m}
                return out

            def check(k_, info, tr, te, key=key):
                xs = [o["size"] for o in te if o[key] == k_[0]]
                if len(xs) < mt_open:
                    return None
                mv = _med(xs)
                return mv >= info["m"] * 1.25 if k_[1] == "偏大" else mv <= info["m"] * 0.8
            rows = []
            for (v, d_), h in walk(wins, opens, discover, check).items():
                xs = [o for o in opens if o[key] == v]
                wf = verdict(h, wins)
                ex = sorted(xs, key=lambda o: o["date"], reverse=True)[:2]
                rows.append({"cond": v, "dir": d_, "n": len(xs), "median": round(_med([o["size"] for o in xs]), 3), "oos": wf["text"], "wf": wf,
                             "examples": [{"date": o["date"], "name": o["name"], "size": round(o["size"], 3), "vs_pc": o["vs_pc"]} for o in ex]})
            rows.sort(key=lambda x: (RANK[x["wf"]["status"]], -x["wf"]["pass"], -x["n"]))
            ent[f"by_{key}"] = rows[:10]
            ent[f"by_{key}_label"] = lab
    adds = [s for s in samples if s["add_evt"]]
    ent["n_add"] = len(adds)
    if len(adds) >= min_n:
        for key, lab, f in ADD_DISTS:
            def discover(tr, f=f):
                c = collections.Counter(f(s) for s in tr if f(s))
                n = sum(c.values())
                if n < min_n:
                    return {}
                top, k_ = c.most_common(1)[0]
                return {top: {"share": k_ / n}}

            def check(top, info, tr, te, f=f):
                c = collections.Counter(f(s) for s in te if f(s))
                n = sum(c.values())
                if n < min_test:
                    return None
                return c[top] / n >= info["share"] - 0.10 or c.most_common(1)[0][0] == top
            c = collections.Counter(f(s) for s in adds if f(s))
            n = sum(c.values())
            if not n:
                continue
            tops = []
            for top, h in walk(wins, adds, discover, check).items():
                wf = verdict(h, wins)
                tops.append({"top": top, "oos": wf["text"], "wf": wf})
            tops.sort(key=lambda x: (RANK[x["wf"]["status"]], -x["wf"]["pass"]))
            ent[key] = {"label": lab, "dist": {k: round(v / n, 3) for k, v in c.most_common()}, "n": n, "tops": tops[:3]}
        ent["add_base"] = round(len(adds) / max(1, len(samples)), 3)
        ent["add_cond"] = fam_hold(samples, FEATS, ("加仓买入",), lambda s: "加仓买入" if s["add_evt"] else "否", min_n, wins, min_test)[:CAP]
    return ent


def mine(sk, min_n, W=40, H=10, min_test=3):
    dp_f = ROOT / "downloads" / "tzzb" / sk / "day_positions.json"
    if not dp_f.exists():
        return None
    dp = json.loads(dp_f.read_text(encoding="utf-8"))
    days = sorted(dp)
    if len(days) < 20:
        return None
    iso = lambda k: f"{k[:4]}-{k[4:6]}-{k[6:]}"
    legs = collections.defaultdict(list)   # (日, 代码) → 卖出腿时刻
    evs = collections.defaultdict(list)    # (日, 代码) → 成交事件(cases_auto, 买 / 卖)
    ca = ROOT / "skills" / f"{sk}-skill" / "persona" / "cases_auto.jsonl"
    if ca.exists():
        for l in ca.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                if r.get("side") == "卖":
                    legs[(r["date"], str(r["code"]))].append(r.get("time") or "")
                if r.get("side") in ("买", "卖") and r.get("code") is not None:
                    evs[(r["date"], str(r["code"]))].append(r)
    rtf = ROOT / "skills" / f"{sk}-skill" / "persona" / "fills_rt.jsonl"
    rtm = {}
    if rtf.exists():
        for l in rtf.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                rtm.setdefault((r.get("date"), r.get("time"), str(r.get("code")), r.get("side")), r.get("rt"))
    codes = {str(p.get("code")) for k in days for p in (dp[k] or {}).get("list") or []}
    K = load_kline(codes, iso(days[0]), (dt.date.fromisoformat(iso(days[-1])) + dt.timedelta(days=10)).isoformat())
    kdays = sorted(K.get("IDX", {}))
    nxt = lambda d: next((x for x in kdays if x > d), None)
    names = {str(p.get("code")): p.get("name") for k in days for p in (dp[k] or {}).get("list") or []}

    def zt_of(c, k, d):   # 10/18: 行情库早期 limit_up 大面积为空(10/09 前约 2/3 行) → 用 a_rules 按前收算涨停价兜底
        if not k or not k.get("c"):
            return False
        lu = k.get("lu")
        if not lu and k.get("pc"):
            try:
                lu = AR.limit_prices(c, d, k["pc"], name=names.get(c))[0]
            except Exception:   # noqa: BLE001
                lu = None
        return bool(lu and k["c"] >= lu - 0.005)
    held_since = {}
    samples = []
    for a, b in zip(days, days[1:]):
        prev = {str(p["code"]): p for p in (dp[a] or {}).get("list") or [] if float(p.get("position_percent") or 0) > 0 and not str(p.get("code")).startswith(REPO)}
        cur = {str(p["code"]): p for p in (dp[b] or {}).get("list") or []}
        for c in list(held_since):
            if c not in prev:
                held_since.pop(c)
        for c, p in prev.items():
            held_since.setdefault(c, a)
            e = cur.get(c)
            pp, cp = float(p.get("position_percent") or 0), (float(e.get("position_percent") or 0) if e else 0.0)
            act = "清仓" if (not e or cp <= 0.005 or str(e.get("op")) == "4") else "减仓" if cp - pp < -ACT_TH else "加仓" if cp - pp > ACT_TH else "持有"
            D = iso(b)
            k = K.get(c, {}).get(D)
            if not k or not k["pc"]:
                continue
            ix = K["IDX"].get(D)
            nd = nxt(D)
            kn = K.get(c, {}).get(nd) if nd else None
            sell_t = min(legs.get((D, c)) or [""]) or None
            hold_n = max(1, sum(1 for x in kdays if iso(held_since[c]) <= x < D))
            kp = K.get(c, {}).get(iso(a))
            buys = [r for r in evs.get((D, c), []) if r["side"] == "买"]
            s = {"date": D, "code": c, "name": p.get("name"), "pos": round(pp, 3), "act": act, "sell_t": sell_t,
                 "gap": round(k["o"] / k["pc"] - 1, 4), "high": round(k["h"] / k["pc"] - 1, 4), "close": round(k["c"] / k["pc"] - 1, 4),
                 "zt_prev": zt_of(c, kp, iso(a)), "rate": float(p.get("rate")) if p.get("rate") is not None else None,
                 "hold": hold_n, "idx_gap": round(ix["o"] / ix["pc"] - 1, 4) if ix and ix["pc"] else None,
                 "next": round(kn["c"] / k["c"] - 1, 4) if kn and k["c"] else None,
                 "add_evt": bool(buys), "pos_after": round(cp, 3),
                 "add_t": min((r.get("time") or "" for r in buys), default="") or None,
                 "add_pct": next((v for v in ((rtm.get((r["date"], r.get("time"), c, "买")) or {}).get("vs_prev_close", (r.get("feat") or {}).get("buy_pct"))
                                              for r in buys) if v is not None), None)}
            samples.append(s)
        for c, e in cur.items():
            if float(e.get("position_percent") or 0) > 0 and c not in prev:
                held_since[c] = b
    acts = ("清仓", "减仓", "加仓", "持有")
    tdays = [d for d in days if iso(d) in K.get("IDX", {})]      # 只取交易日(day_positions 里有节假日键)
    T = [iso(d) for d in tdays]
    wins = make_windows(T, W, H)
    base = collections.Counter(s["act"] for s in samples)
    r = {"skill": sk, "n": len(samples), "days": [days[0], days[-1]], "base": {x: base[x] for x in acts}, "samples": samples,
         "wf_cfg": {"win": W, "hold": H, "min_test": min_test, "recent": RECENT, "n_win": len(wins),
                    "span": [wins[0][0], wins[-1][3]] if wins else None, "first_test": wins[0][2] if wins else None}}
    if len(samples) >= min_n:
        r["patterns"] = fam_hold(samples, FEATS, acts, lambda s: s["act"], min_n, wins, min_test)
        r["pair_min_n"] = max(10, 2 * min_n)
        r["pair_patterns"] = fam_hold(samples, PAIR_FEATS, acts, lambda s: s["act"], r["pair_min_n"], wins, min_test, comp_gap=0.10)
    else:
        r["patterns"], r["pair_patterns"], r["pair_min_n"] = [], [], max(10, 2 * min_n)
    recs = day_records(dp, tdays, iso, evs, K)
    r["seq_patterns"] = fam_seq(recs, wins, min_n, min_test) if recs else []
    r["day_base"] = {"n": len(recs), **{x: round(sum(1 for q in recs if x in q["acts"]) / max(1, len(recs)), 3) for x in DACTS}}
    r["entry"] = fam_entry(new_opens(dp, tdays, iso, evs, rtm), samples, wins, min_n, min_test, W)
    return r


# ---------- 渲染 ----------
def wf_count(ps):
    c = collections.Counter(p["wf"]["status"] for p in ps)
    return " / ".join(f"{k} {c[k]}" for k in RANK if c[k]) or "无"


def shown(ps, cap, dkey=None):
    """md 只列有验证结论的(样本不足的只计数), 近期有效 / 曾有效·近期失效 全列, 其余按排序补到 cap;
    dkey: 同一情境挖出了相反方向(更常 / 更少, 偏大 / 偏小)时只列排序靠前的那条"""
    if dkey:
        seen, keep = set(), []
        for p in ps:
            if dkey(p) not in seen:
                seen.add(dkey(p))
                keep.append(p)
        ps = keep
    good = [p for p in ps if p["wf"]["status"] in ("近期有效", "曾有效·近期失效")]
    rest = [p for p in ps if p["wf"]["status"] in ("不稳定", "过时")]
    return good + rest[:max(0, cap - len(good))]


def render(r, name):
    pc = lambda x: "?" if x is None else f"{x * 100:+.1f}%"
    cfg = r["wf_cfg"]
    L = [f"# {name}({r['skill']}) 持仓处理手法挖掘(机械, 零 token; {dt.date.today()})", "",
         f"> 样本 = 前一交易日收盘持有的每只票 × 当日, 共 {r['n']} 个持仓日({r['days'][0]}~{r['days'][1]})。动作按收盘仓位对比: 清仓 / 减仓(降 >8pp) / 加仓(升 >8pp) / 持有。",
         f"> 基线(全部持仓日): " + " / ".join(f"{k} {v}({v / max(1, r['n']):.0%})" for k, v in r["base"].items()),
         f"> 验证口径(10/18 改滚动, 原 70/30 一刀切作废): 按他自己的交易日序列, 训练窗 {cfg['win']} 日挖规律 → 紧接 {cfg['hold']} 日验证 → 整体后滑 {cfg['hold']} 日再来, "
         f"共 {cfg['n_win']} 窗(验证窗覆盖 {cfg['first_test'] or '-'}~{(cfg['span'] or ['-', '-'])[1]}); 验证窗里该情境样本 < {cfg['min_test']} 不计。每条规律给: 验证通过窗数 / 有样本的窗数、最近一次验证窗是否通过、成立区间(首个通过窗~最后通过窗)。",
         f"> 结论: **近期有效**(最近一次验证落在最后 {RECENT} 窗内且通过, 通过率 ≥60%) / **曾有效·近期失效**(通过率 ≥60% 但最近一次验证没过) / **过时**(早期成立: 截至最后一次通过的通过率 ≥60%, 但最后 {RECENT} 窗没再成立) / **不稳定**(其余)。"
         "只有\"近期有效\"能写成规则主体, 其余只能当[线索]并写明结论; 下面的 n / 占比是全样本合计(描述用)。",
         "> 每条 = \"在某情境下他明显更常做某动作\"(训练窗内该动作占比 ≥55% 或是基线 1.6 倍以上, 样本 ≥ 门槛)。次日=做完动作后那只票次日收盘涨跌(卖出的看卖飞 / 逃对)。", ""]
    ps = r["patterns"]
    if not ps:
        L.append("(样本不足或没有明显偏离基线的情境)")
    else:
        sh = shown(ps, CAP_SINGLE)
        L.append(f"> 单项规律共 {len(ps)} 条({wf_count(ps)}), 列 {len(sh)} 条(样本不足的不列)")
    for p in shown(ps, CAP_SINGLE):
        L.append(f"- **{p['feat']}={p['cond']}(n={p['n']}) → {p['act']} {p['share']:.0%}**(基线倍数 {p['lift']}; {p['oos']}{lt_text(p['wf'])}); 分布 " +
                 "/".join(f"{k}{v}" for k, v in p["dist"].items()) + (f"; 卖出时刻 " + "/".join(f"{k}{v}" for k, v in p["sell_time"].items()) if p["sell_time"] else "") +
                 (f"; {p['act']}后次日均 {pc(p['next_avg'])}(n={p['next_n']})" if p["next_avg"] is not None else ""))
        for e in p["examples"]:
            L.append(f"  - 例 {e['date']} {e['name']}({e['code']}): 开 {pc(e['gap'])} 最高 {pc(e['high'])} 收 {pc(e['close'])}; 浮盈 {pc(e['rate'])}; 已持 {e['hold']} 天"
                     + (f"; 卖出 {e['sell_t']}" if e["sell_t"] else "") + (f"; 次日 {pc(e['next'])}" if e["next"] is not None else ""))
    L += render_extra(r, pc)
    return "\n".join(L) + "\n"


def render_extra(r, pc):
    pp = lambda x: "?" if x is None else f"{x * 100:.0f}%"
    L = ["", f"## 组合情境(两个条件同时成立; 训练窗内 n≥{r.get('pair_min_n', '?')}, 且占比比两个单项各自高 ≥10pp)", ""]
    pair = r.get("pair_patterns") or []
    if not pair:
        L.append("(无: 样本不足, 或组合没有比单项多出信息)")
    else:
        sh = shown(pair, CAP)
        L.append(f"> 共 {len(pair)} 条({wf_count(pair)}), 列 {len(sh)} 条")
        for p in sh:
            L.append(f"- **{p['cond']}(n={p['n']}) → {p['act']} {p['share']:.0%}**(基线倍数 {p['lift']}; {p['oos']}{lt_text(p['wf'])}); 分布 "
                     + "/".join(f"{k}{v}" for k, v in p["dist"].items()) + (f"; {p['act']}后次日均 {pc(p['next_avg'])}(n={p['next_n']})" if p["next_avg"] is not None else ""))
            e = p["examples"][0] if p["examples"] else None
            if e:
                L.append(f"  - 例 {e['date']} {e['name']}({e['code']}): 开 {pc(e['gap'])} 最高 {pc(e['high'])} 收 {pc(e['close'])}; 浮盈 {pc(e['rate'])}; 已持 {e['hold']} 天"
                         + (f"; 卖出 {e['sell_t']}" if e["sell_t"] else "") + (f"; 次日 {pc(e['next'])}" if e["next"] is not None else ""))
    seq, db_ = r.get("seq_patterns") or [], r.get("day_base") or {}
    L += ["", "## 序列情境(账户日级: 他前一天 / 前几天做了什么 → 今天怎么做)", ""]
    if db_:
        L.append(f"> 样本 = 每个交易日一条(共 {db_.get('n')} 日)。今天的动作全样本基线: " + " / ".join(f"{k} {pp(db_.get(k))}" for k in DACTS))
        L.append("> 记录\"更常\"(训练窗内占比 ≥ 基线+15pp 且 ≥1.5 倍)和\"更少\"(≤ 基线-15pp 且 ≤0.6 倍)两个方向; 昨日亏损卖出 = 昨天有一笔卖出的已实现盈亏 <0(cases_auto 口径); "
                 "结构性必然的不列(昨收空仓→今天少卖 / 少降仓, 昨收近满仓→少加仓)。")
    if not seq:
        L.append("(无明显的序列习惯, 或样本不足)")
    else:
        sh = shown(seq, CAP, dkey=lambda p: (p["cond"], p["act"]))
        L.append(f"> 共 {len(seq)} 条({wf_count(seq)}), 列 {len(sh)} 条")
        for p in sh:
            L.append(f"- **{p['cond']}(n={p['n']}) → 今天{p['dir']}{p['act']}: {p['share']:.0%}**(全样本基线 {p['base']:.0%}; {p['oos']}{lt_text(p['wf'])}); 例 " + ", ".join(p["examples"]))
    ent = r.get("entry") or {}
    L += ["", "## 建仓侧(新开仓多大仓位 / 什么时候加仓)", ""]
    sa = ent.get("size_all")
    if not sa:
        L.append(f"(新开仓样本不足: {ent.get('n_open', 0)} 次收盘仍持有的新开)")
    else:
        L.append(f"> 新开仓 = 昨收不持有、今收持有的票, 仓位 = 当日收盘占总资产比例; 共 {sa['n']} 次。全部新开仓位中位 {pp(sa['median'])}(四分位 {pp(sa['q1'])}~{pp(sa['q3'])}), "
                 f"试仓<15% 占 {pp(sa['试仓<15%'])}, 重仓≥50% 占 {pp(sa['重仓≥50%'])}; 最后一个训练窗之后(最近 {r['wf_cfg']['hold']} 日左右)新开 {sa['recent_n']} 次, 中位 {pp(sa['recent_median'])}")
        for key in ("play", "tb"):
            rows = shown([x for x in (ent.get(f"by_{key}") or []) if x["wf"]["status"] != "样本不足"], 10, dkey=lambda x: x["cond"])
            if not rows:
                continue
            L.append(f"- 按{ent.get(f'by_{key}_label')}(训练窗内该组 n≥3 且中位数 ≥1.25 / ≤0.8 倍窗内全部中位 = 偏大 / 偏小; 验证窗该组 ≥2 次才计):")
            for x in rows:
                ex = "; ".join(f"{e['date']} {e['name']} {pp(e['size'])}" for e in x["examples"])
                L.append(f"  - {x['cond']} 仓位{x['dir']}(全样本 n={x['n']}, 中位 {pp(x['median'])}; {x['oos']}); 例 {ex}")
    L.append("")
    if ent.get("n_add", 0) and any(ent.get(k) for k, _, _ in ADD_DISTS):
        L.append(f"> 加仓买入 = 昨收已持有的票当日又有买入成交(事件口径, 与单项节\"仓位升 >8pp\"口径不同); 共 {ent['n_add']} 次, 占持仓日 {pp(ent.get('add_base'))}。")
        for key, lab, _ in ADD_DISTS:
            x = ent.get(key)
            if x:
                L.append(f"- {lab}(n={x['n']}): " + " / ".join(f"{k} {pp(v)}" for k, v in list(x["dist"].items())[:5])
                         + ("; 训练窗里最常见的档: " + "; ".join(f"{t['top']}({t['oos']})" for t in x["tops"]) if x["tops"] else ""))
        ac = [p for p in (ent.get("add_cond") or []) if p["wf"]["status"] != "样本不足"]
        if ac:
            L.append(f"- 什么情境下更常加仓买入({wf_count(ac)}):")
            for p in ac:
                L.append(f"  - {p['feat']}={p['cond']}(n={p['n']}) → 加仓买入 {p['share']:.0%}(基线倍数 {p['lift']}; {p['oos']}{lt_text(p['wf'])})")
    else:
        L.append(f"(加仓买入样本不足: {ent.get('n_add', 0)} 次)")
    return L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger")
    ap.add_argument("--skip", help="逗号分隔, 跳过这些导师(例: 正被 thicken 读的报告不覆盖)")
    ap.add_argument("--min-n", type=int, default=5)
    ap.add_argument("--win", type=int, default=40, help="滚动训练窗(交易日)")
    ap.add_argument("--hold", type=int, default=10, help="滚动验证窗(交易日), 也是每次后滑的步长")
    ap.add_argument("--min-test", type=int, default=3, help="验证窗里该情境样本数下限, 不足不计")
    a = ap.parse_args()
    ids = a.ledger.split(",") if a.ledger else M.ids("tzzb")
    ids = [x for x in ids if x not in set((a.skip or "").split(","))]
    OUT.mkdir(parents=True, exist_ok=True)
    summ = {}
    for sk in ids:
        try:
            r = mine(sk, a.min_n, a.win, a.hold, a.min_test)
        except Exception as e:   # noqa: BLE001  一个导师失败不拖垮全体
            import traceback
            traceback.print_exc()
            print(f"{sk}: 失败 {e}")
            continue
        if not r:
            print(f"{sk}: 无 day_positions 或样本 <20 天, 跳过")
            continue
        (OUT / f"hold_mining_{sk}.md").write_text(render(r, M.get(sk)["name"]), encoding="utf-8")
        (OUT / f"hold_mining_{sk}.json").write_text(json.dumps({k: v for k, v in r.items() if k != "samples"}, ensure_ascii=False, indent=1), encoding="utf-8")
        allp = r["patterns"] + r["pair_patterns"] + r["seq_patterns"]
        st = collections.Counter(p["wf"]["status"] for p in allp)
        ev = sum(v for k, v in st.items() if k != "样本不足")
        summ[sk] = {"持仓日": r["n"], "窗": r["wf_cfg"]["n_win"], "单项": len(r["patterns"]), "组合": len(r["pair_patterns"]), "序列": len(r["seq_patterns"]),
                    "新开": r["entry"].get("n_open", 0), "加仓买入": r["entry"].get("n_add", 0), **{k: st[k] for k in RANK}}
        print(f"{sk}: 持仓日 {r['n']}, 窗 {r['wf_cfg']['n_win']}, 单项 {len(r['patterns'])} / 组合 {len(r['pair_patterns'])} / 序列 {len(r['seq_patterns'])}; "
              f"近期有效 {st['近期有效']}/{ev}(有验证结论的), 曾有效·近期失效 {st['曾有效·近期失效']}, 过时 {st['过时']}, 不稳定 {st['不稳定']}, 样本不足 {st['样本不足']}; "
              f"新开 {summ[sk]['新开']}, 加仓买入 {summ[sk]['加仓买入']}")
    print("JSON:" + json.dumps(summ, ensure_ascii=False))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
