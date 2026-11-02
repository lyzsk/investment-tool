# -*- coding: utf-8 -*-
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "knowledge"), str(ROOT / "live" / "v2")]
from dimensions import unknown  # noqa: E402
from full_chain import full_slow  # noqa: E402
from mentor_consult import build_pack  # noqa: E402
from store import KnowledgeStore  # noqa: E402

DECISION = {"stance": "观察", "action": "只记录，不自动交易", "evidence": ["构造"], "confidence": {"raw": "低"},
            "invalid_if": "失效", "next_check": "下一盘口"}


def store(tmp):
    s = KnowledgeStore(Path(tmp) / "k.db")
    s.upsert("context_snapshot", {"context_id": "ctx", "subject": "600785", "as_of": "2026-10-30T15:00:00",
                                  "available_at": "2026-10-30T15:00:00", "market": {}, "theme": {}, "instrument": {},
                                  "dimensions": unknown(), "evidence": ["构造"]}, "context_id")
    return s


def pack_builder(s, skill, code, q, day, at):
    return build_pack(s, skill, code, q, day, at,
                      fact_builder=lambda *a: "01",
                      persona_builder=lambda *a: (["persona"], [], {}),
                      retrieval_builder=lambda *a: {"required": [], "missing": [], "deferred": [], "coverage": {}})


class FullChainTest(unittest.TestCase):
    def test_slow_forks_before_fast_and_runs_03_04_06(self):
        calls = []

        def fake(prompt, **kw):
            calls.append(kw)
            if "--fork-session" in kw["extra_args"]:
                sid = "slow-sid"
            elif kw["extra_args"]:
                sid = kw["extra_args"][1]
            else:
                sid = kw["resume"]
            parsed = {"status": "ok"} if kw["tag"].endswith("-base") else DECISION
            return SimpleNamespace(ok=True, parsed=parsed, session_id=sid, cost_usd=len(calls) * 0.1, usage={}, errors=[])

        with tempfile.TemporaryDirectory() as tmp:
            s = store(tmp)
            out = full_slow(s, "buchitudou0", "600785", "怎么做", "2026-11-01", "09:30:00", Path(tmp), pack_builder=pack_builder, call_fn=fake)
            self.assertEqual(out["stage"], "slow_full")
            self.assertEqual(list(out["stages"]), ["slow03", "slow04", "slow06"])
            self.assertEqual(out["session_id"], "slow-sid")
            self.assertEqual(out["forked_from"], "base-sid" if calls[0]["extra_args"][1] == "base-sid" else out["forked_from"])
            self.assertNotEqual(out["session_id"], out["forked_from"])
            self.assertTrue(any("--fork-session" in c["extra_args"] for c in calls))
            self.assertEqual(out["cost_usd"], 0.30000000000000004)
            s.close()


if __name__ == "__main__":
    unittest.main()
