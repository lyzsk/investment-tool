# -*- coding: utf-8 -*-
"""live v2 离线闭环测试；桩替代 claude，不花 token。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "knowledge"), str(ROOT / "live" / "v2")]
from driver import process_event, record_result, start_worker  # noqa: E402
from dimensions import unknown  # noqa: E402
from epistemics import verified  # noqa: E402
from session import V2Session  # noqa: E402
from store import KnowledgeStore  # noqa: E402


def store_with_context(tmp):
    store = KnowledgeStore(Path(tmp) / "k.db")
    store.upsert("context_snapshot", {"context_id": "ctx:600785", "subject": "600785", "as_of": "2026-10-30T15:00:00",
                                      "available_at": "2026-10-30T15:00:00", "market": {"cycle": "测试"}, "theme": {},
                                      "instrument": {"code": "600785"}, "dimensions": unknown(), "evidence": ["构造"]}, "context_id")
    return store


EVENT = {"sig": "S17", "t": "09:24:55", "code": "600785", "name": "新华百货", "px": 11.82, "detail": "构造",
         "odds": {"p": 0.66, "n": 3, "tgt": 3, "dir": "buy"}}
DECISION = {"stance": "观察开盘确认", "action": "只记录，不自动下单", "evidence": ["S17 n=3"],
            "confidence": {"raw": "低", "n": 3, "reason": "样本不足"}, "invalid_if": "跌回竞价基准", "next_check": "09:30首笔"}


class DriverTest(unittest.TestCase):
    def test_dry_pack_and_result_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = store_with_context(tmp)
            store.upsert("case_record", {"case_id": "forecast:test", "subject": "600785", "context_id": "ctx:600785",
                                         "issued_at": "2026-10-30T00:00:00", "available_at": "2026-10-31T00:00:00",
                                         "hypothesis": "测试预测", "action": {"kind": "test"}, "outcome": {"hit": 1}, "label": "正",
                                         "confidence": {}, "epistemic": verified(1, 1, "2026-10-31", ["forecast:test"]),
                                         "review_state": "active", "source_id": "forecast:test"}, "case_id")
            r = process_event(store, EVENT, "2026-11-02", Path(tmp) / "out", execute=False)
            self.assertFalse(r["executed"])
            self.assertEqual(r["pack"]["signal"]["sig"], "S17")
            self.assertFalse((Path(tmp) / "out" / "decisions.jsonl").exists())
            case = record_result(store, r["pack"], EVENT, DECISION, "2026-11-02", Path(tmp) / "out")
            self.assertEqual(case["review_state"], "candidate")
            self.assertEqual(case["label"], "待核")
            self.assertTrue(case["action"]["mechanical_only"])
            self.assertTrue(any(x["src"] == "forecast:test" and x["rel"] == "analog" for x in store.links(dst=case["case_id"])))
            self.assertEqual(len((Path(tmp) / "out" / "decisions.jsonl").read_text(encoding="utf-8").splitlines()), 1)
            store.close()

    def test_one_session_then_resume_only(self):
        calls = []

        def fake(prompt, **kw):
            calls.append(kw)
            sid = kw["extra_args"][1] if kw["extra_args"] else kw["resume"]
            return SimpleNamespace(ok=True, parsed=DECISION, session_id=sid, cost_usd=len(calls) * 0.2,
                                   usage={"output_tokens": 10}, errors=[])

        with tempfile.TemporaryDirectory() as tmp:
            ses = V2Session("2026-11-02", Path(tmp), call_fn=fake)
            ses.ask("first", "S17")
            ses.ask("second", "S6")
            self.assertEqual(calls[0]["extra_args"][:1], ["--session-id"])
            self.assertIsNone(calls[0]["resume"])
            self.assertEqual(calls[1]["extra_args"], [])
            self.assertEqual(calls[1]["resume"], ses.st["sid"])
            self.assertEqual(calls[0]["extra_args"][1], calls[1]["resume"])
            self.assertEqual(len(ses.st["turns"]), 2)
            self.assertAlmostEqual(ses.st["turns"][1]["usd"], 0.2)
            saved = json.loads((Path(tmp) / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["sid"], ses.st["sid"])

    def test_background_worker_consumes_real_event_shape(self):
        class FakeSession:
            def __init__(self):
                self.st = {"turns": []}
                self.calls = 0

            def ask(self, prompt, sig):
                self.calls += 1
                self.st["turns"].append({"usd": 0})
                return SimpleNamespace(parsed=DECISION)

        with tempfile.TemporaryDirectory() as tmp:
            store = store_with_context(tmp)
            ses = FakeSession()
            q, thread = start_worker("2026-11-02", Path(tmp) / "out", session=ses, store_path=Path(tmp) / "k.db")
            q.put(dict(EVENT))
            q.put(None)
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(ses.calls, 1)
            rows = (Path(tmp) / "out" / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 1)
            self.assertEqual(json.loads(rows[0])["event"]["sig"], "S17")
            store.close()

    def test_future_context_never_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = store_with_context(tmp)
            r = process_event(store, EVENT, "2026-10-30", Path(tmp), execute=False)
            self.assertEqual(r["status"], "pending_context")
            self.assertFalse(r["executed"])
            self.assertEqual(r["missing"], ["deterministic_context"])
            self.assertFalse((Path(tmp) / "decisions.jsonl").exists())

            class NoCall:
                def ask(self, *args):
                    raise AssertionError("缺情境不得调用模型")

            r = process_event(store, EVENT, "2026-10-30", Path(tmp), execute=True, session=NoCall())
            self.assertEqual(r["status"], "pending_context")
            self.assertEqual(len((Path(tmp) / "pending_context.jsonl").read_text(encoding="utf-8").splitlines()), 1)
            self.assertEqual(store.all("case_record"), [])
            store.close()


if __name__ == "__main__":
    unittest.main()
