# -*- coding: utf-8 -*-
"""知识底座 v1 离线＋真实数据测试；不调用模型，不写正式库。"""
import tempfile
import unittest
from pathlib import Path
import json

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "knowledge"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "live" / "v2"))

from adapters import ForecastAdapter, KlineAdapter, MarketAdapter, TzzbAdapter, UPAdapter, UserAdapter, read_status
from context_pack import forecast_summary, get_context_pack
from dimensions import validate_dimensions
from epistemics import candidate, citable, verified
from schema import validate_case, validate_rule
from signal_pack import event_pack
from store import KnowledgeStore

D = "2026-10-30"
CODES = ["600785", "111024", "113698"]


class ContractTest(unittest.TestCase):
    def test_rule_schema_and_relations(self):
        good = {"id": "R1", "owner": "market", "version": 1, "context_id": "c1", "trigger": {}, "action": "观察",
                "evidence": ["case:1"], "relations": [{"type": "refines", "target": "U44"}], "confidence": {},
                "epistemic": candidate(source="test", as_of="2026-11-01", evidence=["case:1"]), "review": {"state": "candidate"}}
        self.assertTrue(validate_rule(good))
        bad = dict(good, relations=[{"type": "unknown", "target": "U50"}])
        with self.assertRaises(ValueError):
            validate_rule(bad)
        with self.assertRaises(ValueError):
            validate_rule(dict(good, evidence=[]))
        with self.assertRaises(ValueError):
            validate_rule(dict(good, review={"state": "active"}))
        active = dict(good, review={"state": "active"}, epistemic=verified(3, 2 / 3, "2026-11-01", ["case:1"]))
        self.assertTrue(validate_rule(active))
        self.assertTrue(citable(active))
        self.assertFalse(citable(good))

    def test_future_and_multiday_hypothesis(self):
        c = {"case_id": "hyp:1", "subject": "600785", "context_id": "c1", "issued_at": "2026-11-01T21:00:00",
             "available_at": "2026-11-01T21:00:00", "target_start": "2026-11-03", "target_end": "2026-11-10",
             "hypothesis": "百字辈若同步修复则新华有二次反抽", "action": {"stance": "观察"}, "outcome": {},
             "label": "待核", "confidence": {"raw": "中"},
             "epistemic": candidate(source="test", as_of="2026-11-01T21:00:00", evidence=["user:hyp:1"]), "review_state": "candidate", "source_id": "user:hyp:1"}
        self.assertTrue(validate_case(c))
        bad = dict(c, target_end="2026-11-01")
        with self.assertRaises(ValueError):
            validate_case(bad)

    def test_real_ingestion_and_pack(self):
        tmp = Path(tempfile.mkdtemp()) / "test.db"
        store = KnowledgeStore(tmp)
        self.assertEqual(MarketAdapter(store).ingest_day(D, "三季报大周期弱势", CODES), 3)
        TzzbAdapter(store).ingest_day(D, CODES)
        status_path = Path(r"C:/Users/admin/AppData/Local/Temp/kline_status_20261030.json")
        print("STATUS_PATH", status_path, status_path.exists())
        status = read_status(str(status_path))
        self.assertEqual(KlineAdapter(store).ingest_day(D, status=status), 39)
        self.assertGreater(ForecastAdapter(store).ingest_day(D, CODES), 0)
        self.assertGreaterEqual(UserAdapter(store).ingest_day(D), 2)
        UPAdapter(store).ingest_day(D)
        pack = get_context_pack(store, "600785", "2026-10-31T23:00:00", purpose="viewer", budget="full")
        self.assertEqual(pack["context"]["market"]["cycle"], pack["context"]["dimensions"]["cycle_stage"])
        self.assertEqual(set(pack["context"]["dimensions"]["zibei"]), {"bai"})
        self.assertTrue(validate_dimensions(pack["context"]["dimensions"]))
        with self.assertRaises(ValueError):
            validate_dimensions(dict(pack["context"]["dimensions"], theme=["主线归属"]))
        live = get_context_pack(store, "600785", "2026-10-31T23:00:00", purpose="chain04", budget="small")
        self.assertTrue(live["cases"])
        self.assertTrue(all(citable(x) for x in live["cases"]))
        self.assertNotIn("prior_cycle_note", live["context"]["market"])
        self.assertEqual(pack["context"]["market"]["prior_cycle_note"]["epistemic"]["status"], "prior")
        self.assertTrue(all(x["epistemic"]["status"] == "verified" for x in live["cases"]))
        semantic_keys = [(x["issued_at"][:10], (x.get("action") or {}).get("kind"), (x.get("action") or {}).get("context"), x["hypothesis"]) for x in live["cases"]]
        self.assertEqual(len(semantic_keys), len(set(semantic_keys)))
        for x in live["cases"]:
            if (x.get("action") or {}).get("member_ids"):
                self.assertEqual(x["epistemic"]["n"], 1)
        self.assertTrue(any(x["source_id"] == f"user:{D}" for x in pack["cases"]))
        self.assertTrue(any(x["source_id"] == f"kline:{D}" for x in pack["cases"]))
        self.assertIn("forecast", pack)
        ev = {"sig": "S17", "t": "09:24:55", "code": "600785", "name": "新华百货", "px": 11.82,
              "detail": "构造竞价低吸事件", "odds": {"p": 2 / 3, "n": 3, "tgt": 3, "dir": "buy"}}
        ep = event_pack(store, ev, "2026-11-02")
        self.assertEqual(ep["signal"]["sig"], "S17")
        self.assertEqual(ep["confidence"]["signal_n"], 3)
        self.assertEqual(ep["confidence"]["raw"], "低")
        self.assertIn("不自动新增模型仓位", ep["action"])
        self.assertTrue(ep["invalid_if"] and ep["next_check"])
        sell = event_pack(store, dict(ev, sig="S18", odds={"p": 0.8, "n": 14, "tgt": 3, "dir": "sell"}), "2026-11-02")
        self.assertIn("高抛", sell["action"])
        with self.assertRaises(ValueError):   # 10/30 09:24 不能偷用当天 15:00 才可见的情境
            event_pack(store, ev, D)
        store.close()

    def test_forecast_outcome_respects_available_time(self):
        self.assertEqual(forecast_summary("002724", "2026-10-28T00:00:00")["n"], 0)
        self.assertGreater(forecast_summary("002724", "2026-11-02T00:00:00")["n"], 0)

    def test_missing_context_fails_loudly(self):
        store = KnowledgeStore(Path(tempfile.mkdtemp()) / "empty.db")
        with self.assertRaises(ValueError):
            get_context_pack(store, "600785", f"{D}T15:00:00")
        store.close()


if __name__ == "__main__":
    unittest.main()
