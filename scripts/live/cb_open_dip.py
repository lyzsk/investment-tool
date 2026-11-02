# -*- coding: utf-8 -*-
"""转债开盘5分钟低吸：按阈值与正股强弱分层，盘中最高/收盘分开，零token。"""
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "live"))
import signals as SG  # noqa: E402

OUT = ROOT / "results" / "_live"
THRESHOLDS = (0.005, 0.01, 0.02, 0.03, 0.05)


def dist(rows, key):
    xs = sorted(x[key] for x in rows)
    if not xs:
        return None
    q = lambda p: xs[int(p * (len(xs) - 1))]  # noqa: E731
    return {"n": len(xs), "mean": round(st.mean(xs), 3), "median": round(st.median(xs), 3),
            "p10": round(q(.1), 3), "p90": round(q(.9), 3), "best": round(xs[-1], 3), "worst": round(xs[0], 3),
            **{f"win{g:g}": round(sum(x >= g for x in xs) / len(xs), 4) for g in (1, 2, 3, 5)}}


def stock_moves(D):
    out = {}
    f = ROOT / "downloads" / "market" / D / "kline_day.jsonl"
    if not f.exists():
        return out
    for l in f.open(encoding="utf-8"):
        r = json.loads(l)
        if r.get("preClose"):
            out[r["symbol"][-6:]] = float(r["close"]) / float(r["preClose"]) - 1
    return out


def strength(x):
    return "正股强≥2%" if x >= 0.02 else "正股弱≤-2%" if x <= -0.02 else "正股平"


def main():
    rows = defaultdict(list)
    files = sorted((ROOT / "downloads" / "quotes" / "cb" / "minute_path").glob("20*.jsonl"))
    for f in files:
        D = f.stem
        moves = stock_moves(D)
        for l in f.open(encoding="utf-8"):
            r = json.loads(l)
            c, p = str(r.get("code") or ""), r.get("p") or []
            if len(p) < 6 or not p[0]:
                continue
            stk = SG.cb_stock(c)
            if not stk or stk not in moves:
                continue
            group = strength(moves[stk])
            for a in THRESHOLDS:
                if min(p[1:6]) > p[0] * (1 - a):
                    continue
                entry = p[0] * (1 - a)
                rec = {"top": (max(p[1:]) / entry - 1) * 100, "close": (p[-1] / entry - 1) * 100}
                rows[(a, group)].append(rec)
                rows[(a, "全部")].append(rec)
            base = {"top": (max(p[1:]) / p[0] - 1) * 100, "close": (p[-1] / p[0] - 1) * 100}
            rows[("基准", group)].append(base)
            rows[("基准", "全部")].append(base)
    result = {f"{a}|{g}": {"top": dist(v, "top"), "close": dist(v, "close")} for (a, g), v in sorted(rows.items(), key=lambda x: (str(x[0][0]), x[0][1]))}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cb_open_dip.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    L = ["# 转债开盘5分钟低吸分层", "", "> 入场近似=开盘价×(1-a)，不是保证成交；top=之后最高，close=当天收盘。按正股当日强弱分组。", ""]
    for a in THRESHOLDS:
        for g in ("全部", "正股强≥2%", "正股平", "正股弱≤-2%"):
            v = result.get(f"{a}|{g}")
            b = result.get(f"基准|{g}")
            if not v:
                continue
            L.append(f"- a={a:.1%} {g}: n={v['top']['n']} 最高均{v['top']['mean']:+.2f}%/中{v['top']['median']:+.2f}% · 收盘均{v['close']['mean']:+.2f}%/中{v['close']['median']:+.2f}% · P10 {v['close']['p10']:+.2f}% P90 {v['close']['p90']:+.2f}% 最差{v['close']['worst']:+.2f}%"
                     + (f" · 基准收盘{b['close']['mean']:+.2f}%" if b else ""))
    (OUT / "cb_open_dip.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
