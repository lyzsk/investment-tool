# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "live" / "v2"))
from decision_pack import focus01, required_queries, retrieve  # noqa: E402


class DecisionPackTest(unittest.TestCase):
    def test_required_coverage_and_failure_is_explicit(self):
        seen = []

        def runner(q):
            seen.append(q["id"])
            return {"ok": q["id"] != "peers", "text": "事实" if q["id"] != "peers" else "", "error": "缺" if q["id"] == "peers" else ""}

        r = retrieve("buchitudou0", "600785", "新华百货", "2026-11-01", "09:30:00", "趋势", runner)
        self.assertIn("levels", seen)
        self.assertNotIn("window", seen)
        self.assertEqual(r["deferred"][0]["id"], "window")
        self.assertIn("themetop", seen)
        self.assertEqual(r["missing"][0]["query"], "peers")
        self.assertGreater(r["coverage"]["required"], 5)

    def test_cb_has_own_required_path(self):
        qs = required_queries("buchitudou0", "111024", "澳弘转债", "2026-11-01", "09:30:00", "转债")
        self.assertTrue(any(q["id"] == "cbpath" for q in qs))
        self.assertTrue(any(q["id"] == "similar" for q in qs))

    def test_focus01_keeps_only_subject_in_candidate_table(self):
        text = "# 01\n事实\n## 候选池\n| 行 | 代码 |\n|---|---|\n| 1 | 600785 | 新华 |\n| 2 | 002724 | 海洋王 |\n## 上一版\nx"
        out = focus01(text, "600785")
        self.assertIn("600785", out)
        self.assertNotIn("002724", out)
        self.assertIn("事实", out)


if __name__ == "__main__":
    unittest.main()
