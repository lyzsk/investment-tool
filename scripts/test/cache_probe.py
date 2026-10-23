# -*- coding: utf-8 -*-
"""cache_probe.py — 中转(gravitex)上 prompt 缓存到底命不命中(10/22 用户令; 今天 se_chain 全天命中率 3.6%)
做法: 一份固定材料(土豆 rules.md, 约 2 万 token)放 system 并打缓存断点, 只回一个字, effort=low, 花费约 $0.3
  串行 5 次(间隔 3 秒) → 第 1 次应写缓存, 2~5 次应读缓存; 再并发 4 次 → 看并发会不会被分到不同上游
  分别测 TTL 5m 和 1h 两档; 每次记 cache_read / cache_create / input, 结果写 results/inv-stock/test/cache_probe_<时刻>.json
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/test/cache_probe.py
"""
import concurrent.futures as cf
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import claude_api as API   # noqa: E402

MAT = (ROOT / "skills" / "buchitudou0-skill" / "persona" / "rules.md").read_text(encoding="utf-8")


def one(ttl, i, tag):
    r = API.stream(system=[(f"缓存探针 {ttl}。下面是一份固定材料, 不需要分析。\n\n" + MAT, ttl)], user=f"只回复一个字: 好(第 {i} 次)",
                   tag=f"cache-probe-{tag}", max_tokens=200, effort="low", need_json=False, deadline_s=120)
    u = r.usage or {}
    return {"i": i, "ok": r.ok, "secs": r.secs, "read": u.get("cache_read_input_tokens"), "create": u.get("cache_creation_input_tokens"),
            "input": u.get("input_tokens"), "usd": r.cost_usd, "err": r.error[:80]}


def main():
    out = {"at": dt.datetime.now().isoformat(timespec="seconds"), "material_chars": len(MAT)}
    for ttl in ("5m", "1h"):
        seq = []
        for i in range(1, 6):
            seq.append(one(ttl, i, f"{ttl}-seq"))
            time.sleep(3)
        with cf.ThreadPoolExecutor(4) as ex:
            par = list(ex.map(lambda i: one(ttl, i, f"{ttl}-par"), range(6, 10)))
        out[ttl] = {"serial": seq, "parallel": par}
        tot = seq + par
        rd = sum(x["read"] or 0 for x in tot)
        allin = sum((x["read"] or 0) + (x["create"] or 0) + (x["input"] or 0) for x in tot)
        print(f"[{ttl}] 串行 读缓存次数 {sum(1 for x in seq[1:] if (x['read'] or 0) > 0)}/4 · 并发 {sum(1 for x in par if (x['read'] or 0) > 0)}/4 · 命中率 {rd / max(1, allin):.0%} · 花费 ${sum(x['usd'] for x in tot):.3f}")
        for x in tot:
            print("   ", x)
    f = ROOT / "results" / "inv-stock" / "test" / f"cache_probe_{dt.datetime.now():%m%d_%H%M}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("->", f)


if __name__ == "__main__":
    main()
