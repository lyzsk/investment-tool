#!/usr/bin/env bash
# post_md_fix.sh — Claude Code PostToolUse hook: 每次 Edit/Write .md 后自动跑格式巡检
# 挂法: .claude/settings.local.json hooks.PostToolUse
cd "$(git rev-parse --show-toplevel 2>/dev/null || dirname "$0")/../.."
scripts/venv/Scripts/python.exe -X utf8 scripts/md/fix_spacing.py 2>/dev/null
