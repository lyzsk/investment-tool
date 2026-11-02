# -*- coding: utf-8 -*-
"""完整事实包vs动态包机械校准：覆盖、重复、类比时间、未来函数；不拿压缩率当质量。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "knowledge"), str(ROOT / "scripts" / "live" / "v2"), str(ROOT / "scripts" / "chain"), str(ROOT / "scripts" / "paper_line")]
import chain_steps as CS  # noqa: E402
import pack as PaperPack  # noqa: E402
from mentor_consult import build_pack, fact01  # noqa: E402
from store import KnowledgeStore  # noqa: E402


def semantic_key(c):
    a = c.get("action") or {}
    return c["issued_at"][:10], a.get("kind"), a.get("context"), c["hypothesis"]


def main():
    day, at, skill, code = "2026-11-02", "09:20:00", "liuyiqing", "600785"
    store = KnowledgeStore(ROOT / "downloads" / "ontology" / "ontology.db")
    dynamic = build_pack(store, skill, code, "新华百货当前会怎么做", day, at)
    state = {"cash": 0, "positions": {}, "trades": []}
    strategy = {"codes": [{"code": code, "rules": []}]}
    full01, _, _, _ = CS.build_01(skill, day, at, "完整事实包对照", state, strategy, [], {}, "", "对照", None, live=False)
    full_persona = PaperPack.skill_text(skill)
    cases = dynamic["knowledge"]["cases"]
    future = []
    for c in cases:
        if c["available_at"] > dynamic["knowledge"]["at"]:
            future.append(c["case_id"])
        if c.get("epistemic", {}).get("as_of") and c["epistemic"]["as_of"] > dynamic["knowledge"]["at"]:
            future.append(c["case_id"] + ":epistemic")
    duplicates = len(cases) - len({semantic_key(c) for c in cases})
    analog_time_mismatch = [c["case_id"] for c in cases if c["issued_at"][:10] != dynamic["knowledge"]["context"]["as_of"][:10]]
    checks = {
        "current_required_queries": {"ok": not dynamic["retrieval"]["missing"], "detail": dynamic["retrieval"]["coverage"]},
        "future_violations": {"ok": not future, "detail": future},
        "duplicate_independent_groups": {"ok": duplicates == 0, "detail": duplicates},
        "analog_time_mismatch_is_explicit": {"ok": True, "detail": analog_time_mismatch,
                                              "note": "核销情境≠预测发出情境，只许analog，不能当同形supports"},
        "linkage_present": {"ok": bool(dynamic["linkage_4d"]["days"]), "detail": dynamic["linkage_4d"]["shape"]},
        "live02_freshness": {"ok": bool(dynamic["live02"]["freshness"].get("book_t")), "detail": dynamic["live02"]["freshness"]},
        "account_present": {"ok": bool(dynamic["account"]), "detail": dynamic["account_mode"]},
        "slow_window_deferred_not_faked": {"ok": True, "detail": [x["id"] for x in dynamic["retrieval"]["deferred"]]},
    }
    out = {"date": day, "skill": skill, "code": code, "checks": checks,
           "full": {"facts01_bytes": len(full01.encode()), "persona_parts": len(full_persona),
                    "persona_bytes": sum(len(t.encode()) + len(b.encode()) for t, b in full_persona)},
           "dynamic": {"pack_bytes": len(json.dumps(dynamic, ensure_ascii=False).encode()), "facts01_bytes": len(dynamic["facts01"].encode())},
           "verdict": "仅机械覆盖验收，不是模型质量A/B；需要真实决策对照另审"}
    out["ok"] = all(x["ok"] for x in checks.values())
    f = ROOT / "results" / "_live" / day / "retrieval_eval.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    L = [f"# 完整事实包 vs 动态包机械校准 {day}", "", f"- 完整01 {out['full']['facts01_bytes']}B / 动态01 {out['dynamic']['facts01_bytes']}B；动态整包 {out['dynamic']['pack_bytes']}B", ""]
    for k, v in checks.items():
        L.append(f"- {k}: {'OK' if v['ok'] else 'FAIL'} · {json.dumps(v['detail'], ensure_ascii=False)[:300]}")
    L += ["", out["verdict"]]
    (ROOT / "results" / "_live" / day / "retrieval_eval.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    store.close()
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
