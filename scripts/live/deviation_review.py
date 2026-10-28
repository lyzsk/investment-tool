# -*- coding: utf-8 -*-
"""deviation_review.py — check md 新增「备案与链路偏差复盘」(10/27 用户令: "先举出明日备案和各 chain 每一步和后市发展的区别, 然后问为什么, 得到原因,
看能不能知道 know why / know how, 沉淀到 market-skill 和对应 skill, 要人审的放 TODO"; 零 token —— 只做「举出区别」这一半, 为什么 / 沉淀由晚上的会话或用户填)

读(只读): results/_live/<D>/expect.json(前一晚给 D 的明日预案)+ watch_seed.json + md 涨停分析(theme_life, 含 D)
         + results/_live/<D>/review/plan_review.json(各线挂单 → 成交 → 后续)+ downloads/market/<D>/kline_day.jsonl
写: results/_live/<D>/review/deviation.md —— 四节:
   ① 预案 vs 实际: 每个聚焦题材「预测明天 ≥3 家的概率」vs 实际家数 → 对 / 错; 新口径阶段 → 次日家数
   ② 种子池 vs 实际: 续板(冲 N+1)封没封 / 断板观察 当天涨跌 / 字辈 当天涨停几只
   ③ 各线成交偏差: 成交单里 当天盈亏最差 / 卖后最高(卖飞)最大 的前几笔(按 |偏差| 排, 动态取前 20% 但至少 3 条)
   ④ 待问「为什么」: ①~③ 里偏差最大的 5 条, 每条留 为什么 / know why / know how / 沉淀到哪 四个空, 晚上会话或用户填
用法: python deviation_review.py --date D     (nightly_recalc 在 plan_review 之后调)
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "results" / "_live"
MKT = ROOT / "downloads" / "market"
sys.path.insert(0, str(ROOT / "scripts" / "paper_line" / "tools"))


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def day_bars(D):
    out = {}
    f = MKT / D / "kline_day.jsonl"
    if f.exists():
        for l in f.open(encoding="utf-8"):
            r = json.loads(l)
            s = r.get("symbol", "")
            if s[:2] in ("sh", "sz") and r.get("preClose"):
                out[s] = r
    return out


def pct(r, k):
    return (r[k] / r["preClose"] - 1) * 100


def build(D):
    import theme_life as TL
    E = jl(LIVE / D / "expect.json", {}) or {}
    W = jl(LIVE / D / "watch_seed.json", {}) or {}
    PR = jl(LIVE / D / "review" / "plan_review.json", {}) or {}
    B = day_bars(D)
    cnt = defaultdict(int)
    for r in TL.rows_canon():
        if r[0] == D and r[5]:
            cnt[r[1]] += 1
    L = [f"# 偏差复盘 {D}(前一晚预案 / 种子池 / 各线挂单 vs 当天实际; 零 token 机械对照, 「为什么」留给晚上填)", ""]
    devs = []
    # ① 预案
    L.append("## ① 预案 vs 实际(明天 ≥3 家涨停的概率 vs 实际家数)")
    if not E:
        L.append("- 没有 expect.json")
    hit = n = 0
    for f in E.get("明日聚焦") or []:
        th, p = f["题材"], f.get("明天≥3家·延续概率") or 0
        act = cnt.get(th, 0)
        ok = (act >= 3) == (p >= 0.5)
        n += 1
        hit += ok
        nq = (f.get("新口径") or {}).get("标签") or ""
        L.append(f"- {th}: 预测 {p:.0%} → 实际 {act} 家 · {'对' if ok else '**错**'}" + (f" · 新口径阶段 {nq}" if nq else ""))
        if not ok:
            devs.append((abs(p - (1 if act >= 3 else 0)), f"预案·{th}: 预测 {p:.0%}, 实际 {act} 家", "market-skill(题材延续) / expect.py 延续率分组"))
    if n:
        L.append(f"- 方向命中 {hit}/{n}")
    top_new = [] if not E else sorted(((k, v) for k, v in cnt.items() if k not in {f['题材'] for f in E.get('明日聚焦') or []}), key=lambda kv: -kv[1])[:3]
    if top_new:
        L.append("- 预案外当天涨停多的题材: " + " / ".join(f"{k} {v} 家" for k, v in top_new))
        for k, v in top_new:
            if v >= 3:
                devs.append((v / 10, f"预案漏掉的题材: {k} 当天 {v} 家", "expect.py 流转 / 新题材识别"))
    # ② 种子池
    L += ["", "## ② 种子池 vs 实际"]
    sym = lambda c: ("sh" if c[:1] in ("6", "9", "5") else "sz") + c   # noqa: E731
    for tag, nm in (("续板", "续板(冲 N+1)"), ("断板观察", "断板观察")):
        rows = []
        for x in W.get("seed") or []:
            if tag in (x.get("tags") or []):
                r = B.get(sym(x["code"]))
                if r:
                    up = r.get("limitUp")
                    sealed = bool(up and r["close"] >= up - 0.005)
                    rows.append((x["name"], pct(r, "close"), pct(r, "high"), sealed))
        if rows:
            ns = sum(s for *_, s in rows)
            L.append(f"- {nm} {len(rows)} 只: 封住 {ns} · 收盘中位 {sorted(r[1] for r in rows)[len(rows) // 2]:+.1f}% | "
                     + " / ".join(f"{a} {b:+.1f}%{'🔒' if s else ''}" for a, b, c, s in sorted(rows, key=lambda r: -r[1])[:10]))
    zb = defaultdict(list)
    for x in W.get("seed") or []:
        for t in x.get("tags") or []:
            if t.startswith("字辈"):
                r = B.get(sym(x["code"]))
                if r:
                    zb[t].append((x["name"], pct(r, "close"), bool(r.get("limitUp") and r["close"] >= r["limitUp"] - 0.005)))
    for t, rows in zb.items():
        L.append(f"- {t}: {len(rows)} 只, 涨停 {sum(s for *_, s in rows)} · " + " / ".join(f"{a} {b:+.1f}%" for a, b, s in sorted(rows, key=lambda r: -r[1])[:8]))
    # ③ 各线成交偏差
    L += ["", "## ③ 各线成交单偏差(plan_review; 当天盈亏 / 成交后最高最低)"]
    fills = []
    for ln in PR.get("lines") or []:
        for o in ln.get("orders") or []:
            if o.get("cat") != "成交":
                continue
            dp = o.get("day_pnl_pct")
            if o["side"] == "SELL":   # 卖: 卖后最高还涨多少(卖飞) / 收盘相对卖价
                hi, lo = o.get("sold_fly_pct"), o.get("close_vs_sell_pct")
                dev = hi or 0
            else:                     # 买: 当天盈亏 / 成交后最高最低
                hi, lo = o.get("after_high_pct"), o.get("after_low_pct")
                dev = -(dp or 0)
            fills.append((dev, ln.get("name") or ln["id"], o, dp, hi, lo))
    if not fills:
        L.append("- plan_review.json 还没有(nightly 04:00 跑)" if not PR else "- 当天没有成交单")
    fills.sort(key=lambda x: -x[0])
    k = max(3, len(fills) // 5)
    f_ = lambda v: "—" if v is None else f"{v:+.2f}%"   # noqa: E731
    for dev, nm, o, dp, hi, lo in fills[:k]:
        if o["side"] == "SELL":
            L.append(f"- {nm} {o['fill_t']} 卖 {o['name']} @{o['fill_px']}: 卖后最高还涨 {f_(hi)} · 收盘相对卖价 {f_(lo)} · 相对成本 {f_(o.get('vs_cost_pct'))} | 依据: {str(o.get('why'))[:120]}")
        else:
            L.append(f"- {nm} {o['fill_t']} 买 {o['name']} @{o['fill_px']}: 当天 {f_(dp)} · 成交后最高 {f_(hi)} / 最低 {f_(lo)} | 依据: {str(o.get('why'))[:120]}")
        if dev > 2:
            devs.append((dev / 5, f"{nm} {o['fill_t']} {'卖' if o['side'] == 'SELL' else '买'} {o['name']} @{o['fill_px']}: " + (f"卖后还涨 {hi:+.2f}%" if o['side'] == 'SELL' else f"买后当天 {dp:+.2f}%"),
                         f"{nm} 的 skill 规则({', '.join(o.get('rule_keys') or [])})"))
    # ④ 待问为什么
    L += ["", "## ④ 待问「为什么」(偏差最大的 5 条; 晚上会话 / 你填, 填完的 know how 进 market-skill 或对应 skill, 要你审的进 TODO ❓)"]
    for _, what, where in sorted(devs, key=lambda d: -d[0])[:5]:
        L += [f"### {what}", "- 为什么: ", "- know why(机制): ", "- know how(下次怎么做, 带口径 / 阈值来源): ", f"- 沉淀到: {where}", ""]
    out = LIVE / D / "review" / "deviation.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    return out, "\n".join(L)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    a = ap.parse_args()
    f, t = build(a.date)
    print(t)
    print(f"→ {f}")
