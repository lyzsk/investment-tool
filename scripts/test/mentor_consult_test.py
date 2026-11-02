# -*- coding: utf-8 -*-
"""按需导师咨询离线测试：01/人格可替换，模型用桩，不花 token。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "knowledge"), str(ROOT / "live" / "v2")]
from dimensions import unknown  # noqa: E402
from epistemics import verified  # noqa: E402
from mentor_consult import build_pack, consult, stage_for  # noqa: E402
from session import V2Session  # noqa: E402
from store import KnowledgeStore  # noqa: E402

DECISION = {"stance": "观察", "action": "只记录，不自动交易", "evidence": ["构造事实"], "confidence": {"raw": "低", "n": 1},
            "invalid_if": "盘口失效", "next_check": "下一笔3秒盘口", "choices": ["等确认"]}


def make_store(tmp):
    s = KnowledgeStore(Path(tmp) / "k.db")
    s.upsert("context_snapshot", {"context_id": "ctx", "subject": "600785", "as_of": "2026-10-30T15:00:00",
                                  "available_at": "2026-10-30T15:00:00", "market": {}, "theme": {}, "instrument": {},
                                  "dimensions": unknown(), "evidence": ["构造"]}, "context_id")
    s.upsert("case_record", {"case_id": "forecast:1", "subject": "600785", "context_id": "ctx", "issued_at": "2026-10-30T00:00:00",
                             "available_at": "2026-10-31T00:00:00", "hypothesis": "预测", "action": {"kind": "test"}, "outcome": {"hit": 1},
                             "label": "正", "confidence": {}, "epistemic": verified(1, 1, "2026-10-31", ["forecast:1"]),
                             "review_state": "active", "source_id": "forecast:test"}, "case_id")
    return s


def pack_builder(store, skill, code, question, day, at):
    return build_pack(store, skill, code, question, day, at,
                      fact_builder=lambda *args: "# 01 构造事实",
                      persona_builder=lambda *args: (["指定导师画像"], ["相关规则"], {"test": True}),
                      retrieval_builder=lambda *args: {"required": [], "missing": [], "coverage": {"required": 0, "ok": 0, "missing": 0}})


class ConsultTest(unittest.TestCase):
    def test_fast_slow_same_session_and_analog_lineage(self):
        calls = []

        def fake(prompt, **kw):
            calls.append(kw)
            sid = kw["extra_args"][1] if kw["extra_args"] else kw["resume"]
            return SimpleNamespace(ok=True, parsed=DECISION, session_id=sid, cost_usd=len(calls) * 0.1, usage={}, errors=[])

        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            ses = V2Session("2026-11-01", Path(tmp) / "consult", call_fn=fake)
            common = dict(store=store, skill="buchitudou0", code="600785", question="会怎么做", day="2026-11-01", at="09:30:00",
                          out_root=Path(tmp) / "consult", execute=True, session=ses, pack_builder=pack_builder)
            fast = consult(stage="fast", **common)
            slow = consult(stage="slow", **common)
            self.assertEqual(fast["session_id"], slow["session_id"])
            self.assertEqual(calls[1]["resume"], fast["session_id"])
            self.assertEqual(calls[1]["extra_args"], [])
            case = store.get("case_record", "case_id", fast["case_id"])
            self.assertFalse(case["action"]["auto_execute"])
            self.assertTrue(case["action"]["system_bs"])
            self.assertFalse(case["action"]["mentor_real_bs"])
            links = store.links(dst=fast["case_id"])
            self.assertTrue(any(x["rel"] == "observed" for x in links))
            analog = next(x for x in links if x["rel"] == "analog")
            self.assertIn("different", analog["meta"])
            store.close()

    def test_stage_windows_and_slow_standalone(self):
        self.assertEqual(stage_for("09:15:00"), "fast_slow")
        self.assertEqual(stage_for("09:14:59"), "slow")
        self.assertEqual(stage_for("10:29:59"), "fast_slow")
        self.assertEqual(stage_for("10:30:00"), "slow")
        self.assertEqual(stage_for("09:14:59"), "slow")
        calls = []

        def fake(prompt, **kw):
            calls.append(kw)
            sid = kw["extra_args"][1] if kw["extra_args"] else kw["resume"]
            return SimpleNamespace(ok=True, parsed=DECISION, session_id=sid, cost_usd=0.1, usage={}, errors=[])

        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            ses = V2Session("2026-11-01", Path(tmp) / "consult", call_fn=fake)
            r = consult(store, "buchitudou0", "600785", "午后怎么做", "2026-11-01", "13:00:00", Path(tmp) / "consult",
                        stage="slow", execute=True, session=ses, pack_builder=pack_builder)
            self.assertTrue(r["executed"])
            self.assertEqual(len(calls), 1)
            store.close()

    def test_missing_context_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore(Path(tmp) / "empty.db")
            r = consult(store, "buchitudou0", "600785", "会怎么做", "2026-10-30", "09:30:00", Path(tmp), pack_builder=pack_builder)
            self.assertEqual(r["status"], "pending_context")
            self.assertFalse(r["executed"])
            store.close()


if __name__ == "__main__":
    unittest.main()
