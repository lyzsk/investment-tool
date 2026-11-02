# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "live" / "v2"))
from linkage import build  # noqa: E402


class LinkageTest(unittest.TestCase):
    def test_shanghai_xiba_deformed_n(self):
        x = build("603200", "2026-10-30")
        self.assertEqual(x["shape"]["kind"], "变形N字")
        self.assertTrue(x["shape"]["middle_new_high"])
        self.assertTrue(x["shape"]["pullback_below_first_close"])
        self.assertTrue(x["shape"]["second_below_middle_high"])
        self.assertEqual(len(x["days"]), 5)
        self.assertEqual(x["days"][0]["recency_weight"], 0.2)
        self.assertEqual(x["days"][-1]["recency_weight"], 1.0)
        self.assertEqual(x["days"][-1]["role"], "当前确认")
        self.assertGreaterEqual(len(build("603200", "2026-10-30", n=20)["days"]), 5)


if __name__ == "__main__":
    unittest.main()
