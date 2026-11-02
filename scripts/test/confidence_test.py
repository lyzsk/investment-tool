# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "live" / "v2"))
from confidence import assess, clamp  # noqa: E402


class ConfidenceTest(unittest.TestCase):
    def test_high_requires_all_mechanical_evidence(self):
        good = dict(n=80, hit_rate=0.75, baseline=0.60, avg_return=2.0, cost_pct=0.1,
                    out_of_sample=True, counterexample_reviewed=True, exit_ok=True, coverage_ok=True)
        self.assertEqual(assess(**good)["cap"], "高")
        for key, value in (("n", 20), ("baseline", None), ("cost_pct", None), ("out_of_sample", False),
                           ("counterexample_reviewed", False), ("exit_ok", None), ("coverage_ok", False)):
            bad = dict(good, **{key: value})
            self.assertNotEqual(assess(**bad)["cap"], "高", key)

    def test_model_can_only_lower(self):
        a = assess(n=0)
        c = clamp({"raw": "高", "reason": "模型自评"}, a)
        self.assertEqual(c["raw"], "候选")
        self.assertEqual(c["mechanical_cap"], "候选")


if __name__ == "__main__":
    unittest.main()
