# -*- coding: utf-8 -*-
"""近4日联动卡：保留首板→分歧→二板的形成过程，防止01只剩当日切片。零token。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "review"), str(ROOT / "scripts" / "backfill_bilibili")]
from mentor_cards import daily, sym  # noqa: E402


def auction(code, day):
    f = ROOT / "downloads" / "market" / day / "auction_live_open.json"
    if not f.exists():
        return {}
    symbol = ("sh" if code.startswith(("6", "5", "11")) else "sz") + code
    s = (json.loads(f.read_text(encoding="utf-8")).get("symbols") or {}).get(symbol) or {}
    return {"d_after920": s.get("d_after920"), "tags": s.get("tags") or [], "fin": s.get("fin") or {}}


CONFIG = json.loads((Path(__file__).parent / "linkage_window.json").read_text(encoding="utf-8"))


def build(code, day, n=None):
    n = n or CONFIG["default_days"]
    n = max(CONFIG["min_days"], min(CONFIG["max_days"], int(n)))
    bars = [b for b in daily(sym(code), day, max(12, n + 2)) if b["d"] <= day]
    recent = bars[-n:]
    rows = []
    for i, b in enumerate(recent):
        rows.append({"date": b["d"], "open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"], "preClose": b["pc"],
                     "pct": round((b["c"] / b["pc"] - 1) * 100, 2) if b["pc"] else None, "volume": b["v"],
                     "recency_weight": round((i + 1) / len(recent), 3), "role": "起点背景" if i == 0 else "当前确认" if i == len(recent) - 1 else "形成过程",
                     "auction": auction(code, b["d"])})
    limit = [r["close"] >= round(r["preClose"] * 1.1 + 1e-9, 2) - 1e-9 for r in rows]
    boards = [i for i, x in enumerate(limit) if x]
    shape = {"kind": "未形成N字", "boards": [rows[i]["date"] for i in boards]}
    if len(boards) >= 2:
        first, last = boards[0], boards[-1]
        middle = rows[first + 1:last]
        first_close, last_close = rows[first]["close"], rows[last]["close"]
        mid_high = max((r["high"] for r in middle), default=first_close)
        below_first = any(r["close"] < first_close for r in middle)
        shape.update(kind="变形N字" if below_first else "N字",
                     middle_new_high=mid_high > first_close,
                     pullback_below_first_close=below_first,
                     second_below_middle_high=last_close < mid_high,
                     first_close=first_close, middle_high=mid_high, second_close=last_close,
                     volume_path=[r["volume"] for r in rows])
    return {"code": code, "window": {"days": n, "min": CONFIG["min_days"], "max": CONFIG["max_days"], "adaptive": CONFIG["adaptive"], "recency_weight": CONFIG["recency_weight"]},
            "days": rows, "forward_path": [{"date": r["date"], "pct": r["pct"], "recency_weight": r["recency_weight"], "role": r["role"]} for r in rows],
            "shape": shape, "note": "仅复述已形成事实；近端日期用于理解形成过程，N字/变形N字不是次日预测"}


if __name__ == "__main__":
    print(json.dumps(build(sys.argv[1], sys.argv[2]), ensure_ascii=False, indent=1))
