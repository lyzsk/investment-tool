# -*- coding: utf-8 -*-
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "knowledge"), str(ROOT / "live" / "v2")]
from radar import Radar  # noqa: E402


class RadarTest(unittest.TestCase):
    def test_low_confidence_candidate_still_emits_and_updates_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = Radar("2026-11-01", Path(tmp) / "out", extra_path=Path(tmp) / "extra.txt")
            e = {"t": "09:24:55", "code": "600785", "name": "新华百货", "sig": "S17", "px": 11.82,
                 "detail": "构造", "odds": {"n": 17, "p": 0.6471}}
            w = r.on_event(e, 9 * 3600 + 30 * 60)
            self.assertIsNotNone(w)
            self.assertEqual(w["sig"], "W1")
            self.assertIn("低", w["detail"])
            self.assertIn("同期同池基准", w["detail"])
            self.assertIn("600785", (Path(tmp) / "extra.txt").read_text(encoding="utf-8"))
            self.assertTrue((Path(tmp) / "out" / "decision_windows.jsonl").exists())
            self.assertIsNone(r.on_event(e, 9 * 3600 + 31 * 60))
            r.close()


if __name__ == "__main__":
    unittest.main()
