# -*- coding: utf-8 -*-
"""check md 导师白名单离线测试。"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "tzzb"))
import check_md_mentors as CM  # noqa: E402


class CheckMdMentorsTest(unittest.TestCase):
    def test_user_selected_nine_and_paused_states(self):
        expected = {"gjieshenqiangshou", "zhiyingjuexin", "liuyiqing", "buchitudou0", "stzhilang",
                    "zuoshoudeirong", "wudaokongfang", "lianghuaxiaohao", "xingjianye"}
        states = CM.states()
        self.assertEqual(CM.enabled_ids(), expected)
        self.assertEqual(len(states), 20)
        self.assertEqual(sum(rec["state"] == "sample_paused" for rec in states.values()), 10)
        self.assertEqual(states["chong5000w"]["state"], "stale_paused")

    def test_filter_only_changes_sum_distill_candidates(self):
        rows = [{"ledger": "zhiyingjuexin"}, {"ledger": "antoo"}, {"ledger": "stzhilang"}]
        self.assertEqual(CM.filter_enabled(rows), [{"ledger": "zhiyingjuexin"}, {"ledger": "stzhilang"}])
        self.assertTrue((ROOT / "skills" / "antoo-skill").exists(), "暂停导师的原skill目录必须保留")

    def test_every_registered_positive_mentor_has_explicit_state(self):
        registered = {r["ledger"] for r in json.loads((ROOT / "scripts" / "tzzb" / "tzzb_ledgers.json").read_text(encoding="utf-8"))
                      if r.get("kind") == "pos" and r.get("book")}
        self.assertEqual(registered, set(CM.states()))


if __name__ == "__main__":
    unittest.main()
