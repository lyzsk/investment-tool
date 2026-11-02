# -*- coding: utf-8 -*-
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "knowledge"))
from replay_viewer import consult_books  # noqa: E402


class ViewerConsultTest(unittest.TestCase):
    def test_candidate_order_is_not_trade(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "buchitudou0" / "c1"
            d.mkdir(parents=True)
            (d / "pack.json").write_text(json.dumps({"at": "2026-11-01T09:30:00", "code": "600785", "name": "新华百货", "question": "怎么做"}, ensure_ascii=False), encoding="utf-8")
            doc = {"cost_usd": 0.1, "case": {"action": {"skill": "buchitudou0", "orders": [{"side": "BUY", "price": 11.82, "why": "候选"}]}},
                   "decision": {"stance": "观察", "action": "不自动交易"}}
            (d / "fast.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            data = {"books": [{"skill": "buchitudou0", "mentor_day": {"same": [1]}}]}
            books = consult_books(data, "2026-11-01", tmp)
            self.assertEqual(books[0]["trades"], [])
            self.assertEqual(len(books[0]["suggestions"]), 1)
            self.assertEqual(books[0]["suggestions"][0]["px"], 11.82)
            self.assertEqual(books[0]["mentor_day"]["same"], [1])
            self.assertEqual(books[0]["mode"], "consult")


if __name__ == "__main__":
    unittest.main()
