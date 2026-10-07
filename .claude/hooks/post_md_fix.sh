#!/usr/bin/env bash
# post_md_fix.sh — Claude Code PostToolUse hook: 每次 Edit/Write .md 后自动跑格式巡检
# 挂法: .claude/settings.local.json hooks.PostToolUse
cd /c/Users/admin/dev/investment-tool
scripts/venv/Scripts/python.exe -X utf8 scripts/md/fix_spacing.py 2>/dev/null
