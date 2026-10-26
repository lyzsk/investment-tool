# -*- coding: utf-8 -*-
"""session_growth.py — 实盘线会话体检: 上午会话涨到多大、午后叫醒是不是变贵变慢(10/25 用户: 周一结束要在 TODO 里写清楚, 用来决定 PAPER_NOON_RESET 开不开; 零 token, 只读)

读各线 <根>/<D>/live_*/: session.json(每轮 secs / usd / cache_read = 会话上下文大小的近似) + events.jsonl(链耗时)
口径: 上午 = 09:35~11:30 的链(去掉盘前首跑 / 竞价段), 午后 = 13:00~14:50 的链; 比每条链 耗时 / 花费 的中位
判定: 午后中位 ≥ 上午中位 × 1.3(耗时或花费任一) → "变贵变慢, 建议开午休换会话"; 否则 "没明显变化, 保持关"; 某段 < 3 条链 → "样本不够"
产物: <根>/<D>/review/session_growth.md; --todo 时在 docs/TODO.md「周一跑完按真实数据调」那条下面追加一行结论(只追加自己那一行, 同日重跑覆盖)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/live/session_growth.py --date 2026-10-26 [--root results/_live] [--todo]
"""
import argparse
import datetime as dt
import json
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TODO = ROOT / "docs" / "TODO.md"
K = 1.3


def med(xs):
    return round(st.median(xs), 2) if xs else None


def line_stat(d):
    ev = []
    try:
        ev = [json.loads(l) for l in (d / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, ValueError):
        pass
    ch = [e for e in ev if e.get("kind") == "链耗时" and not e.get("boot")]
    am = [e for e in ch if "09:35:00" <= str(e.get("t")) < "11:30:00"]
    pm = [e for e in ch if "13:00:00" <= str(e.get("t")) < "14:50:00"]
    turns = []
    try:
        turns = json.loads((d / "session.json").read_text(encoding="utf-8")).get("turns") or []
    except (OSError, ValueError):
        pass
    cr = [(t.get("t"), t.get("cache_read") or 0) for t in turns if t.get("cache_read") and not t.get("fork") and t.get("round") != "keep"]   # 03 分叉不算主会话; t = 真实钟点(回放里不是模拟时刻, 上下文分段只在实盘准)
    am_cr = [c for t, c in cr if str(t) < "11:30:00"]
    pm_cr = [c for t, c in cr if str(t) >= "13:00:00"]
    noon = (d / "session_am.json").exists()
    return {"line": d.name, "n_am": len(am), "n_pm": len(pm), "turns": len(turns), "noon_reset": noon,
            "am_secs": med([e["secs"] for e in am]), "pm_secs": med([e["secs"] for e in pm]),
            "am_usd": med([e.get("usd") or 0 for e in am]), "pm_usd": med([e.get("usd") or 0 for e in pm]),
            "ctx_am_end_k": round(am_cr[-1] / 1000) if am_cr else None, "ctx_pm_end_k": round(pm_cr[-1] / 1000) if pm_cr else None,
            "ctx_first_k": round(cr[0][1] / 1000) if cr else None}


def verdict(r):
    if r["n_am"] < 3 or r["n_pm"] < 3:
        return "样本不够"
    slow = r["am_secs"] and r["pm_secs"] >= r["am_secs"] * K
    dear = r["am_usd"] and r["pm_usd"] >= r["am_usd"] * K
    return "变贵变慢" if (slow or dear) else "没明显变化"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--root", default="results/_live")
    ap.add_argument("--todo", action="store_true")
    a = ap.parse_args()
    root = ROOT / a.root
    day = root / a.date if (root / a.date).is_dir() else root
    rows = [line_stat(d) for d in sorted(day.glob("live_*")) if (d / "events.jsonl").exists()]
    for r in rows:
        r["verdict"] = verdict(r)
    vs = [r["verdict"] for r in rows if r["verdict"] != "样本不够"]
    if not vs:
        concl = "样本不够(上午或午后链 < 3 条), 结论下不了"
    elif vs.count("变贵变慢") * 2 > len(vs):
        concl = f"午后变贵变慢({vs.count('变贵变慢')}/{len(vs)} 条线) → 建议打开 PAPER_NOON_RESET=1(等你点头)"
    else:
        concl = f"午后没明显变贵变慢({vs.count('变贵变慢')}/{len(vs)} 条线超 {K} 倍) → 保持 PAPER_NOON_RESET=0"
    L = [f"# 实盘线会话体检 {a.date}", "", f"> 上午 = 09:35~11:30 的链, 午后 = 13:00~14:50 的链(不含盘前首跑); 中位比; 超 {K} 倍算变贵变慢。上下文 = 每轮缓存读取 token(会话大小的近似)。", "",
         f"**结论: {concl}**", "",
         "| 线 | 上午链 | 午后链 | 耗时中位 上午→午后(秒) | 花费中位 上午→午后 | 上下文 开盘→午前→收盘(千 token) | 会话轮数 | 判定 |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['line']}{'(午休换过会话)' if r['noon_reset'] else ''} | {r['n_am']} | {r['n_pm']} | {r['am_secs']}→{r['pm_secs']} | ${r['am_usd']}→${r['pm_usd']} | "
                 f"{r['ctx_first_k']}→{r['ctx_am_end_k']}→{r['ctx_pm_end_k']} | {r['turns']} | {r['verdict']} |")
    od = day / "review"
    od.mkdir(parents=True, exist_ok=True)
    (od / "session_growth.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(concl)
    for r in rows:
        print(r)
    if a.todo and TODO.exists():
        s = TODO.read_text(encoding="utf-8")
        tag = f"  - 📊 {a.date} 会话体检(脚本自动写): "
        lines = [l for l in s.split("\n") if not l.startswith(tag)]
        k = next((i for i, l in enumerate(lines) if l.startswith("- 周一跑完按真实数据调")), None)
        if k is not None:
            lines.insert(k + 1, tag + concl + f"; 明细 `{od.relative_to(ROOT).as_posix()}/session_growth.md`")
            TODO.write_text("\n".join(lines), encoding="utf-8")
            print("TODO 已写")


if __name__ == "__main__":
    main()
