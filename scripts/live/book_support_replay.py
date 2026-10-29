# -*- coding: utf-8 -*-
"""live/book_support_replay.py — 前低托单(买侧 U49)/ 前高压单(卖侧镜像)历史回放(10/28 晚用户令; 零 token, 只读 3 秒盘口录像)

托单(买侧): 现价在日内前低上方 ≤ 2 个价位, 买一 ~ 买二里有一档 ≥ max(5 × 同侧其他档中位, 本票平时 1 分钟成交额 × 0.5 ÷ 价)、
           且那一档价格 ≥ 前低(= 托在前低上方), 近 5 分钟主动卖 ≥ 主动买(= 卖压大)→ 事件
压单(卖侧): 现价在日内前高下方 ≤ 2 个价位, 卖一 ~ 卖二里有大单(同口径)且价格 ≤ 前高, 近 5 分钟主动买 ≥ 主动卖 → 事件
前低 / 前高 = 09:35 后、事件前 ≥ 5 分钟形成的日内最低 / 最高; 同票同方向 30 分钟内只记一次
结果: 事件价之后 30 分钟收益(托单看涨 / 压单看跌 = 方向对), 对照基线 = 同批票任意时点 30 分钟收益方向
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/live/book_support_replay.py [--days 2026-10-19,...]
产物: results/_live/book_support_replay.md
"""
import argparse
import gzip
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"


def secs(t):
    h, m, s = int(t[:2]), int(t[3:5]), int(t[6:8])
    x = h * 3600 + m * 60 + s
    return x - 5400 if x >= 13 * 3600 else x   # 午休压掉 1.5 小时


def rows(D):
    p = MKT / D / "book_snap.jsonl.gz"
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for l in f:
            r = json.loads(l)
            t = r.get("t") or ""
            if "09:35:00" <= t <= "14:56:00" and not ("11:30:01" <= t <= "12:59:59") and r.get("p"):
                yield r


def run_day(D):
    st = defaultdict(lambda: {"hi": None, "lo": None, "hi_t": 0, "lo_t": 0, "hist": [], "last": {"S": -10 ** 9, "B": -10 ** 9}, "prev": None})
    ev, path = [], defaultdict(list)
    for r in rows(D):
        c = r["s"]
        if c[2:4] in ("11", "12") or c.startswith(("sh000", "sz399")):
            continue
        x, p = secs(r["t"]), float(r["p"])
        z = st[c]
        path[c].append((x, p))
        pv = z["prev"]
        if pv:   # 主动买卖(成交价 vs 上一快照买一卖一中间)
            dv = (r.get("v") or 0) - (pv.get("v") or 0)
            if dv > 0 and pv.get("b") and pv.get("k") and pv["b"][0][0] and pv["k"][0][0]:
                mid = (pv["b"][0][0] + pv["k"][0][0]) / 2
                z["hist"].append((x, dv if p > mid else 0, dv if p < mid else 0))
        z["prev"] = r
        z["hist"] = [h for h in z["hist"] if h[0] >= x - 300]
        tick = 0.01
        if z["lo"] is None or p < z["lo"]:
            z["lo"], z["lo_t"] = p, x
        if z["hi"] is None or p > z["hi"]:
            z["hi"], z["hi_t"] = p, x
        b, k = r.get("b") or [], r.get("k") or []
        buy5, sell5 = sum(h[1] for h in z["hist"]), sum(h[2] for h in z["hist"])

        def big(levels):
            vs = [float(v) for pp, v in levels if pp and v]
            if len(vs) < 3:
                return None
            for pp, v in levels[:2]:
                oth = [float(vv) for qq, vv in levels if qq and vv and qq != pp]
                if pp and v and oth and float(v) >= 5 * statistics.median(oth) and float(v) * float(pp) >= 3e5:
                    return float(pp), float(v)
            return None
        if x - z["lo_t"] >= 300 and p <= z["lo"] + 2 * tick + 1e-9 and sell5 >= buy5 > -1 and x - z["last"]["B"] >= 1800:
            g = big(b)
            if g and g[0] >= z["lo"] - 1e-9:
                z["last"]["B"] = x
                ev.append((c, D, r["t"], x, p, "托单", g))
        if x - z["hi_t"] >= 300 and p >= z["hi"] - 2 * tick - 1e-9 and buy5 >= sell5 and x - z["last"]["S"] >= 1800:
            g = big(k)
            if g and g[0] <= z["hi"] + 1e-9:
                z["last"]["S"] = x
                ev.append((c, D, r["t"], x, p, "压单", g))
    out = []
    for c, D_, t, x, p, kind, g in ev:
        fut = [q for xx, q in path[c] if x < xx <= x + 1800]
        if len(fut) < 50:
            continue
        r30 = (fut[-1] / p - 1) * 100
        out.append({"code": c, "D": D_, "t": t, "kind": kind, "px": p, "r30": r30, "ok": (r30 > 0) if kind == "托单" else (r30 < 0)})
    base = []
    for c, pts in path.items():
        for i in range(0, len(pts) - 600, 600):
            j = next((k_ for k_ in range(i, len(pts)) if pts[k_][0] >= pts[i][0] + 1800), None)
            if j:
                base.append((pts[j][1] / pts[i][1] - 1) * 100)
    return out, base


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", default="")
    a = ap.parse_args()
    days = a.days.split(",") if a.days else sorted(p.name for p in MKT.iterdir() if (p / "book_snap.jsonl.gz").exists())
    allev, allbase = [], []
    for D in days:
        o, b = run_day(D)
        allev += o
        allbase += b
        print(D, "事件", len(o), file=sys.stderr)
    L = ["# 前低托单 / 前高压单 历史回放(零 token, 3 秒盘口录像)", "", f"天数 {len(days)}: {days[0]} ~ {days[-1]}", "",
         "| 信号 | 事件数 | 30 分钟方向对 | 30 分钟收益 均值 / 中位 | 基线 |", "|---|---|---|---|---|"]
    up = sum(1 for x in allbase if x > 0) / len(allbase) if allbase else 0
    for kind in ("托单", "压单"):
        xs = [e for e in allev if e["kind"] == kind]
        if not xs:
            L.append(f"| {kind} | 0 | - | - | - |")
            continue
        r = [e["r30"] for e in xs]
        bl = up if kind == "托单" else 1 - up
        L.append(f"| {kind} | {len(xs)} | {sum(e['ok'] for e in xs) / len(xs):.0%} | {statistics.mean(r):+.2f}% / {statistics.median(r):+.2f}% | 任意时点 30 分钟{'上涨' if kind == '托单' else '下跌'} {bl:.0%}(均值 {statistics.mean(allbase):+.2f}%) |")
    by = defaultdict(list)
    for e in allev:
        by[(e["kind"], e["D"])].append(e["ok"])
    L += ["", "## 按天", ""] + [f"- {k[1]} {k[0]}: n={len(v)} 方向对 {sum(v) / len(v):.0%}" for k, v in sorted(by.items(), key=lambda z: (z[0][1], z[0][0]))]
    hit = [e for e in allev if e["code"] == "sz002696" and e["D"] == "2026-10-28"]
    L += ["", f"## 百洋股份 10/28(U49 来源样本)是否抓到: {[(e['t'], e['kind'], round(e['r30'], 2)) for e in hit] or '没抓到'}"]
    out = ROOT / "results" / "_live" / "book_support_replay.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
