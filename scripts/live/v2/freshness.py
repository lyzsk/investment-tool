# -*- coding: utf-8 -*-
"""02/06时效：实时指数/情绪/盘口；夜间拓扑关系只读，不伪装成实时重算。"""
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MKT = ROOT / "downloads" / "market"


def seconds(t):
    h, m, s = (int(x) for x in t.split(":"))
    return h * 3600 + m * 60 + s


def latest_jsonl(path, at, predicate=None):
    if not path.exists():
        return None
    op = gzip.open if path.suffix == ".gz" else open
    last = None
    with op(path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            t = r.get("t") or r.get("barTime", "")[11:19]
            if t and t <= at and (not predicate or predicate(r)):
                last = r
    return last


def current_book(code, day, at):
    sym = ("sh" if code.startswith(("6", "5", "11")) else "sz") + code
    for name in ("book_snap.jsonl", "book_snap.jsonl.gz"):
        r = latest_jsonl(MKT / day / name, at, lambda x: x.get("s") == sym and (x.get("p") or (x.get("b") and x["b"][0][0])))
        if r:
            return r
    return None


def live02(code, day, at):
    mood = latest_jsonl(MKT / day / "mood.jsonl", at)
    index = latest_jsonl(MKT / day / "index_snap.jsonl", at, lambda x: x.get("idx"))
    book = current_book(code, day, at)
    return {"as_of": f"{day}T{at}", "mood": mood or {}, "index": index or {}, "book": book or {},
            "freshness": {"mood_t": (mood or {}).get("t"), "index_t": (index or {}).get("t"), "book_t": (book or {}).get("t"),
                          "age_s": seconds(at) - seconds(book["t"]) if book else None,
                          "topology_relation": "previous_completed_day_precompute",
                          "realtime_membership_and_prices": True}}


if __name__ == "__main__":
    import sys
    print(json.dumps(live02(sys.argv[1], sys.argv[2], sys.argv[3]), ensure_ascii=False, indent=1))
