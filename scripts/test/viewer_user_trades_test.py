# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "paper_line"))
from viewer import user_trades  # noqa: E402


class UserTradesTest(unittest.TestCase):
    def test_broker_serial_prefix_is_visible(self):
        rows = user_trades("2026-10-30")
        self.assertEqual(len(rows), 6)
        self.assertEqual({x[1] for x in rows}, {"600785", "601988", "002241"})


if __name__ == "__main__":
    unittest.main()
