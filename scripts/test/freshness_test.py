# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "live" / "v2"))
from freshness import current_book, live02, seconds  # noqa: E402


class FreshnessTest(unittest.TestCase):
    def test_realtime_book_and_topology_semantics(self):
        b = current_book("600785", "2026-10-30", "09:24:55")
        self.assertIsNotNone(b)
        self.assertLessEqual(seconds("09:24:55") - seconds(b["t"]), 15)
        x = live02("600785", "2026-10-30", "09:24:55")
        self.assertTrue(x["freshness"]["realtime_membership_and_prices"])
        self.assertEqual(x["freshness"]["topology_relation"], "previous_completed_day_precompute")


if __name__ == "__main__":
    unittest.main()
