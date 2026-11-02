# -*- coding: utf-8 -*-
"""check md 的 tzzb 导师白名单；只控制 sum+distill，不删除样例或限制其他机械维护。"""
import json
from pathlib import Path

CONFIG = Path(__file__).with_name("check_md_mentors.json")


def states():
    return json.loads(CONFIG.read_text(encoding="utf-8"))["mentors"]


def enabled_ids():
    return {mid for mid, rec in states().items() if rec.get("state") == "on"}


def filter_enabled(ledgers):
    enabled = enabled_ids()
    return [rec for rec in ledgers if rec.get("ledger") in enabled]
