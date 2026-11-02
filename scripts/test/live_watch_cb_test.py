# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "live"))
import signals as S  # noqa: E402


class HotCBTest(unittest.TestCase):
    def test_limit_up_stock_cb_enters_signal_watchlist(self):
        self.assertIn("111024", S.hot_cb_codes("2026-10-30"))
        self.assertIn("111024", S.watch_codes("2026-10-30"))


if __name__ == "__main__":
    unittest.main()
