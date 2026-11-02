# -*- coding: utf-8 -*-
"""项目内禁用 rotation 后的离线回归测试；不调用模型、不读写真 settings。"""
import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "claude_profile"), str(ROOT / "scripts" / "lib")]
import claude_call as CC  # noqa: E402
import rotation  # noqa: E402


class RotationOffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old_state, self.old_log = rotation.STATE, rotation.USE_LOG
        rotation.STATE = self.tmp / "state.json"
        rotation.USE_LOG = self.tmp / "profiles.csv"
        self.old_env = dict(os.environ)
        os.environ.pop("CLAUDE_PROFILE_PIN", None)
        os.environ.pop("CLAUDE_ROT_MODE", None)

    def tearDown(self):
        rotation.STATE, rotation.USE_LOG = self.old_state, self.old_log
        os.environ.clear()
        os.environ.update(self.old_env)

    def test_file_disables_project_profile_selection(self):
        self.assertTrue(rotation.rotation_off())
        self.assertIsNone(rotation.current_profile())
        with mock.patch.object(rotation.subprocess, "run", side_effect=AssertionError("不应调用切换工具")):
            self.assertEqual(rotation.settings_args(), [])

    def test_project_never_switches_on_quota_error(self):
        self.assertFalse(rotation.on_window_limit("You've reached your 5-hour usage limit"))
        self.assertFalse(rotation.STATE.exists())

    def test_log_reports_default_manager_profile(self):
        with mock.patch.object(rotation, "_settings_profile", return_value="kimi-api"):
            rotation.log_use("offline-test")
        with rotation.USE_LOG.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(rows[-1]["profile"], "kimi-api")

    def test_explicit_test_pin_survives_but_does_not_rotate(self):
        os.environ["CLAUDE_PROFILE_PIN"] = "kimi-code"
        self.assertEqual(rotation.current_profile(), "kimi-code")
        self.assertFalse(rotation.on_window_limit("5-hour usage limit"))


class ErrorClassificationTest(unittest.TestCase):
    def test_only_explicit_quota_text_is_a_window(self):
        self.assertTrue(CC.QUOTA_RE.search("You've reached your 5-hour usage limit"))
        self.assertTrue(CC.QUOTA_RE.search("7-day usage limit; quota will reset"))
        self.assertFalse(CC.QUOTA_RE.search("Request rejected (429) · The engine is currently overloaded"))
        self.assertFalse(CC.QUOTA_RE.search("unrecognized_model"))
        self.assertTrue(CC.TRANSIENT_RE.search("Request rejected (429) · overloaded"))
        self.assertTrue(CC.CONFIG_RE.search("unrecognized_model"))

    @staticmethod
    def _fake_rotation():
        return mock.Mock(
            settings_args=mock.Mock(return_value=[]),
            current_profile=mock.Mock(return_value=None),
            log_use=mock.Mock(),
            is_api400=mock.Mock(return_value=False),
            on_window_limit=mock.Mock(return_value=False),
            rotation_off=mock.Mock(return_value=True),
        )

    @staticmethod
    def _completed(text, rc=1):
        import subprocess
        body = json.dumps({"type": "result", "subtype": "error" if rc else "success", "is_error": bool(rc), "result": text}).encode()
        return subprocess.CompletedProcess(["claude"], rc, stdout=body, stderr=b"")

    def _run_two(self, first, rot):
        responses = [self._completed(first), self._completed("ok", rc=0)]
        with mock.patch.object(CC, "_rotation", return_value=rot), \
             mock.patch.object(CC, "_automemory_env", return_value={}), \
             mock.patch.object(CC, "claude_exe", return_value=["claude"]), \
             mock.patch.object(CC.subprocess, "run", side_effect=responses) as run, \
             mock.patch.object(CC.time, "sleep") as sleep:
            result = CC.call("offline", tag="offline-test", log_cost=False)
        return result, run, sleep

    def test_overloaded_retries_same_profile_with_short_backoff(self):
        rot = self._fake_rotation()
        result, run, sleep = self._run_two("API Error: Request rejected (429) · The engine is currently overloaded", rot)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(run.call_count, 2)
        self.assertLessEqual(sleep.call_args.args[0], 60)
        rot.on_window_limit.assert_not_called()

    def test_unrecognized_model_does_not_retry_or_switch(self):
        rot = self._fake_rotation()
        result, run, _ = self._run_two("unrecognized_model; API Error: Request rejected (429) · overloaded", rot)
        self.assertFalse(result.ok)
        self.assertEqual(run.call_count, 1)
        rot.on_window_limit.assert_not_called()

    def test_true_quota_waits_briefly_for_external_manager(self):
        rot = self._fake_rotation()
        result, run, sleep = self._run_two("You've reached your 5-hour usage limit", rot)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(sleep.call_args.args[0], 60)
        rot.on_window_limit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
