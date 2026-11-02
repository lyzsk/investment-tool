# -*- coding: utf-8 -*-
import sys
import unittest
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "live"))
from signal_odds import add_score, day_hi, row_bucket  # noqa: E402


class ScoreTest(unittest.TestCase):
    def test_buy_and_sell_direction(self):
        rows = defaultdict(row_bucket)
        add_score(rows, "buy", 10, 10.3, 10.1, False, 1)
        add_score(rows, "sell", 10, 9.7, 9.9, True, 1)
        self.assertEqual(rows["buy"]["w3"], 1)
        self.assertEqual(rows["sell"]["w3"], 1)
        self.assertAlmostEqual(rows["buy"]["ret"], 1.0)
        self.assertAlmostEqual(rows["sell"]["ret"], 10 / 9.9 * 100 - 100)

    def test_not_hit(self):
        rows = defaultdict(row_bucket)
        add_score(rows, "buy", 10, 10.2, 9.8, False, 1)
        add_score(rows, "sell", 10, 9.8, 10.2, True, 1)
        self.assertEqual(rows["buy"]["w3"], 0)
        self.assertEqual(rows["sell"]["w3"], 0)
    def test_same_code_index_does_not_overwrite_stock(self):
        bars = day_hi("2026-10-26")
        self.assertEqual(bars["000010"][1], 1.29)
        self.assertEqual(bars["000099"][1], 12.84)


if __name__ == "__main__":
    unittest.main()
