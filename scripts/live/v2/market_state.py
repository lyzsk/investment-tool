# -*- coding: utf-8 -*-
"""连续市况状态：保留当前结构化状态与变化，不写长篇叙事。"""
import json
from pathlib import Path
from context_pack import get_context_pack


def current(store, code, day, at):
    pack = get_context_pack(store, code, f"{day}T{at}", purpose="chain04", budget="small")
    c = pack["context"]
    return {"as_of": pack["at"], "subject": code, "dimensions": c["dimensions"],
            "market": (c.get("market") or {}).get("features") or {}, "theme": (c.get("theme") or {}).get("features") or {},
            "zibei": (c.get("theme") or {}).get("zibei_features") or {}, "instrument": (c.get("instrument") or {}).get("features") or {},
            "evidence_ids": pack["meta"]["evidence_ids"], "pack": pack}


def changes(previous, now):
    if not previous:
        return []
    out = []
    a, b = previous.get("dimensions") or {}, now["dimensions"]
    for key in ("cycle_stage", "position", "auction", "pattern"):
        if a.get(key) != b.get(key):
            out.append({"field": key, "from": a.get(key), "to": b.get(key)})
    for th, cur in (now.get("theme") or {}).items():
        old = (previous.get("theme") or {}).get(th) or {}
        if old.get("stage") != cur.get("stage"):
            out.append({"field": f"theme:{th}", "from": old.get("stage"), "to": cur.get("stage")})
    for py, cur in (now.get("zibei") or {}).items():
        old = (previous.get("zibei") or {}).get(py) or {}
        if old.get("stage") != cur.get("stage"):
            out.append({"field": f"zibei:{py}", "from": old.get("stage"), "to": cur.get("stage")})
    return out


def update(store, code, day, at, path):
    now = current(store, code, day, at)
    path = Path(path)
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = None
    now["changes"] = changes(previous, now)
    path.parent.mkdir(parents=True, exist_ok=True)
    public = {k: v for k, v in now.items() if k != "pack"}
    path.write_text(json.dumps(public, ensure_ascii=False, indent=1), encoding="utf-8")
    return now
