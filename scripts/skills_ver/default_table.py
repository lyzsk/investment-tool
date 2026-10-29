# -*- coding: utf-8 -*-
"""skills_ver/default_table.py — 导师隔夜仓默认动作表(可复现; 10/28 晚用户令 C: 取代 R39 / R40 那张模型改写的表; 零 token)

为什么: R39「开盘档 × 昨日封没封 × 被套/浮盈」是打板模板 —— 非连板票也被套「昨未封」, 而且只统计"卖不卖", 没有"加仓 / 做T"
        (刘忆青 10/28 百洋股份: 导师深套时低位加仓再卖 = 做T, skill 按 R39「10:15 前清」清仓)
格子(都是开盘那一刻已知): 票型 × 开盘档 × 赚亏
  票型  连板(昨天封死涨停) / 强势回调(近 7 日 ≥2 板、昨天没封) / 趋势(昨收在 MA20 上方且 MA20 向上, 昨天没封板) / 超跌(近 5 日 ≤ −10% 或昨收在 MA20 下方且 MA20 向下) / 其他
  开盘档 高开(≥+2%) / 平开(−2%~+2%) / 低开(≤−2%)    赚亏 赚(昨收浮盈 ≥0) / 亏
动作(当天): 清(当天卖) · 加(当天又买; 其中又卖 = 做T) · 持(没动); 卖的那些次: 时段分布 + 卖价相对开盘中位(执行器分布卖用的就是这个)
三层: 全期 · 同市况(按当天上证涨跌 强 > +0.5 / 平 / 弱 < −0.5) · 近 20 个交易日; 样本 <5 的格标「样本少」
产物: docs/research/default_table_<skill>.md(给人看) + results/_live/default_table_<skill>.json(给必查查格子)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/skills_ver/default_table.py --skill liuyiqing [--date D]   (D = 只用 D 之前的样本; 缺省 = 全部)
      import: cell(skill, D, code, open_pct, pnl_prev) → 三层动作分布(盘前 / 开盘后查)
"""
import argparse
import bisect
import collections
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "paper_line" / "tools"), str(ROOT / "scripts" / "backfill_bilibili")]
OUTJ = ROOT / "results" / "_live"
OUTM = ROOT / "docs" / "research"


def kind_of(K, i):
    """K = [(d, o, h, l, c)], i = 当天下标; 票型只用 i−1 及以前"""
    if i < 21:
        return "其他"
    pc, ppc = K[i - 1][4], K[i - 2][4]
    zt = lambda j: K[j - 1][4] and K[j][4] >= round(K[j - 1][4] * 1.1 - 1e-9, 2) - 0.005 and K[j][4] == K[j][2]   # noqa: E731
    if zt(i - 1):
        return "连板"
    if sum(1 for j in range(max(1, i - 7), i) if zt(j)) >= 2:   # 10/28 晚: 近 7 日 ≥2 板、昨天没封 = 高位强势回调(百洋股份 10/28 那种, U43)
        return "强势回调"
    ma = statistics.fmean(x[4] for x in K[i - 20:i])
    ma_p = statistics.fmean(x[4] for x in K[i - 25:i - 5])
    r5 = pc / K[i - 6][4] - 1 if K[i - 6][4] else 0
    if r5 <= -0.10 or (pc < ma and ma < ma_p):
        return "超跌"
    if pc > ma and ma > ma_p:
        return "趋势"
    return "其他"


def gap_b(g):
    return "高开" if g >= 2 else "低开" if g <= -2 else "平开"


_IDX = {}


def reg_prev(d):
    """d 前一个交易日的市况分级(regime_day; 开盘那一刻已知): 冰点 / 普跌 / 普涨 / 分化 / 修复"""
    sys.path.insert(0, str(ROOT / "scripts" / "market"))
    import regime_day as RG
    _, r = RG.prev(d)
    return (r or {}).get("标签", "?").split("·")[0]


def mkt_of(d):
    if not _IDX:
        import manual_backfill as mb
        c = mb.db().cursor()
        c.execute("select trade_date, close, pre_close from investment_market.kline_day where symbol='sh000001' and is_deleted=0 and trade_date >= '2024-06-01'")
        for t, cl, pc in c.fetchall():
            if pc:
                p = (float(cl) / float(pc) - 1) * 100
                _IDX[str(t)] = "强" if p > 0.5 else "弱" if p < -0.5 else "平"
    return _IDX.get(d, "?")


_ROWS = {}


def rows(skill, D=None):
    if (skill, D) in _ROWS:
        return _ROWS[(skill, D)]
    import mentor_sells as M
    panel, sold, _ = M.data(skill)
    st = {(s["code"], s["d"]): s for s in sold}
    codes = {r["code"] for r in panel}
    K = M.load_kline(codes)
    out = []
    for r in panel:
        if r["asset"] != "stock" or (D and r["d"] >= D):
            continue
        k = K.get(r["code"]) or []
        ds = [x[0] for x in k]
        i = bisect.bisect_left(ds, r["d"])
        if i >= len(k) or ds[i] != r["d"]:
            continue
        s = st.get((r["code"], r["d"])) if r["sold"] else None
        out.append({"d": r["d"], "code": r["code"], "kind": kind_of(k, i), "gap": gap_b(r["gap"]), "pnl": "赚" if r["pnl_prev"] >= 0 else "亏", "mkt": reg_prev(r["d"]),
                    "act": "做T" if r.get("add") and r["sold"] else "加" if r.get("add") else "清" if r["sold"] else "持",
                    "t": s["t"] if s else None, "vs_open": s["vs_open"] if s else None, "add_vs_open": (r.get("add") or {}).get("vs_open")})
    _ROWS[(skill, D)] = out
    return out


def dist(xs):
    n = len(xs)
    if not n:
        return None
    c = collections.Counter(x["act"] for x in xs)
    import mentor_sells as M
    sx = [x for x in xs if x["act"] in ("清", "做T") and x["t"]]
    out = {"n": n, "清": f"{c['清'] / n:.0%}", "做T": f"{c['做T'] / n:.0%}", "加": f"{c['加'] / n:.0%}", "持": f"{c['持'] / n:.0%}"}
    if sx:
        out["卖出时段"] = M.mix([M.tbucket(x["t"]) for x in sx])
        out["卖价相对开盘中位%"] = M.q([x["vs_open"] for x in sx], .5)
    ad = [x["add_vs_open"] for x in xs if x["act"] in ("加", "做T") and x["add_vs_open"] is not None]
    if ad:
        out["加仓价相对开盘中位%"] = M.q(ad, .5)
    if n < 5:
        out["注"] = "样本少"
    return out


def cell_of(R, kind, gap, pnl, mkt=None, recent=None):
    xs = [x for x in R if x["kind"] == kind and x["gap"] == gap and x["pnl"] == pnl]
    return {"全期": dist(xs), "同市况": dist([x for x in xs if mkt and x["mkt"] == mkt]) if mkt else None,
            "近20日": dist([x for x in xs if recent and x["d"] >= recent]) if recent else None}


def recent_start(R, D=None, n=20):
    ds = sorted({x["d"] for x in R if not D or x["d"] < D})
    return ds[-n] if len(ds) >= n else (ds[0] if ds else None)


def cell(skill, D, code, open_pct, pnl_prev):
    """盘中查: 这只票今天的格子 → 三层分布(只用 D 之前)"""
    import mentor_sells as M
    R = rows(skill, D)
    K = M.load_kline({code}).get(code) or []
    ds = [x[0] for x in K]
    i = bisect.bisect_left(ds, D)
    kind = kind_of(K + [(D, 0, 0, 0, 0)] if i >= len(K) else K, i) if K else "其他"
    m = mkt_of(sorted(d for d in _IDX if d < D)[-1]) if mkt_of(D) == "?" and _IDX else mkt_of(D)
    rp = reg_prev(D)
    out = {"票型": kind, "开盘": gap_b(open_pct), "赚亏": "赚" if pnl_prev >= 0 else "亏", "昨天市况": rp, **cell_of(R, kind, gap_b(open_pct), "赚" if pnl_prev >= 0 else "亏", rp, recent_start(R, D))}
    out["同市况"] = out.pop("同市况")
    out["这位导师昨天市况同为「%s」的全部持仓日" % rp] = dist([x for x in R if x["mkt"] == rp])
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--date", default=None)
    a = ap.parse_args()
    R = rows(a.skill, a.date)
    rec = recent_start(R, a.date)
    tab = {}
    L = [f"# {a.skill} 隔夜仓默认动作表(可复现; 样本 = 持仓日面板 {len(R)} 行{', 截至 ' + a.date if a.date else ''}; 近 20 日起 {rec})", "",
         "> 脚本 `scripts/skills_ver/default_table.py`。格子 = 票型 × 开盘档 × 赚亏(都是开盘那一刻已知); 动作 = 清 / 做T(加了又卖)/ 加 / 持; 三层 = 全期 · 同市况(昨天的市况分级: 冰点 / 普跌 / 分化 / 修复 / 普涨)· 近 20 日。", "",
         "| 票型 | 开盘 | 赚亏 | 全期 n | 清 | 做T | 加 | 持 | 卖出时段(前 2) | 卖价/开盘 | 加仓价/开盘 | 近20日 n · 清 / 做T / 加 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for kind in ("连板", "强势回调", "趋势", "超跌", "其他"):
        for gap in ("高开", "平开", "低开"):
            for pnl in ("赚", "亏"):
                c = cell_of(R, kind, gap, pnl, None, rec)
                tab[f"{kind}|{gap}|{pnl}"] = c
                g = c["全期"]
                if not g:
                    continue
                r2 = c["近20日"]
                top2 = "、".join(list((g.get("卖出时段") or {}).keys())[:2])
                L.append(f"| {kind} | {gap} | {pnl} | {g['n']}{'(少)' if g.get('注') else ''} | {g['清']} | {g['做T']} | {g['加']} | {g['持']} | {top2} | {g.get('卖价相对开盘中位%', '-')} | {g.get('加仓价相对开盘中位%', '-')} | "
                         + (f"{r2['n']} · {r2['清']} / {r2['做T']} / {r2['加']}" if r2 else "-") + " |")
    mk = {}
    for m in ("冰点", "普跌", "分化", "修复", "普涨"):
        mk[m] = dist([x for x in R if x["mkt"] == m])
    L += ["", "## 同一位导师在不同市况下(按「昨天」市况分级 regime_day; 全部格子合并)", ""] + [f"- 昨天{m}: {json.dumps(v, ensure_ascii=False)}" for m, v in mk.items() if v]
    OUTM.mkdir(parents=True, exist_ok=True)
    (OUTM / f"default_table_{a.skill}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    OUTJ.mkdir(parents=True, exist_ok=True)
    (OUTJ / f"default_table_{a.skill}.json").write_text(json.dumps({"skill": a.skill, "asof": a.date, "recent_from": rec, "cells": tab, "mkt": mk}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(L[:40]))


if __name__ == "__main__":
    main()
