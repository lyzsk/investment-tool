# -*- coding: utf-8 -*-
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "knowledge"))
from epistemics import candidate, verified  # noqa: E402
from lineage import explain_rule, put_rule, rule_key  # noqa: E402
from store import KnowledgeStore  # noqa: E402


class LineageTest(unittest.TestCase):
    def test_evidence_rule_relation_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = KnowledgeStore(Path(tmp) / "k.db")
            case = {"case_id": "forecast:1", "subject": "600785", "context_id": "ctx:1", "issued_at": "2026-10-30T00:00:00",
                    "available_at": "2026-10-31T00:00:00", "hypothesis": "上涨", "action": {}, "outcome": {"hit": 1},
                    "label": "正", "confidence": {}, "epistemic": verified(1, 1, "2026-10-31", ["forecast:1"]),
                    "review_state": "active", "source_id": "forecast:test"}
            s.upsert("case_record", case, "case_id")
            rule = {"id": "R1", "owner": "market", "version": 1, "context_id": "ctx:1", "trigger": {"pattern": "普通"},
                    "action": "只作观察", "evidence": ["forecast:1"], "relations": [], "confidence": {},
                    "epistemic": verified(1, 1, "2026-10-31", ["forecast:1"]), "review": {"state": "active"}}
            key = put_rule(s, rule, ["forecast:1"])
            out = explain_rule(s, "market", "R1", 1)
            self.assertEqual(key, rule_key(rule))
            self.assertEqual(out["evidence_cases"][0]["case_id"], "forecast:1")
            self.assertEqual(out["incoming"][0]["rel"], "supports")
            self.assertTrue(any(x["rel"] == "context" for x in out["outgoing"]))
            s.close()

    def test_candidate_not_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = KnowledgeStore(Path(tmp) / "k.db")
            with self.assertRaises(ValueError):
                put_rule(s, {"id": "R2", "owner": "market", "version": 1, "context_id": "ctx", "trigger": {}, "action": "观察",
                             "evidence": ["c"], "relations": [], "confidence": {}, "epistemic": candidate(), "review": {"state": "active"}}, ["c"])
            s.close()


if __name__ == "__main__":
    unittest.main()
