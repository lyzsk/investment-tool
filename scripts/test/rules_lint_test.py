# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "md"))
from rules_lint import context_status, recent_status  # noqa: E402


class RulesLintTest(unittest.TestCase):
    def test_context_and_recent_gate(self):
        self.assertEqual(context_status("只有操作"), "缺")
        self.assertEqual(context_status("市况+题材+个股，n=1"), "只1例")
        self.assertEqual(context_status("情境卡: x"), "齐")
        self.assertEqual(recent_status("胜率60%，n=20"), "缺")
        self.assertEqual(recent_status("近期20日胜率60%，全期对照"), "齐")
        self.assertEqual(recent_status("没有统计，只写动作"), "齐")


if __name__ == "__main__":
    unittest.main()
