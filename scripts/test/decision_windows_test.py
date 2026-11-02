# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "live" / "v2"))
from decision_windows import evaluate  # noqa: E402


def state(pattern):
    return {"dimensions": {"pattern": pattern, "auction": "平开", "cycle_stage": "震荡"}, "instrument": {"trend": {"ma20": 10}},
            "evidence_ids": ["e1"]}


class WindowTest(unittest.TestCase):
    def test_trend_is_not_forced_into_board_template(self):
        out = evaluate(state("趋势"))
        self.assertEqual(out[0]["kind"], "trend_turn")
        self.assertIn("不预判必然涨停", out[0]["next_check"])

    def test_signal_only_forms_candidate_not_high_confidence(self):
        out = evaluate(state("转强候选"), {"sig": "S17"})
        self.assertTrue(any(x["kind"] == "auction_repair" for x in out))
        self.assertTrue(all(x["status"] == "candidate" for x in out))
        self.assertTrue(all(x["confidence"]["cap"] == "候选" for x in out))


if __name__ == "__main__":
    unittest.main()
