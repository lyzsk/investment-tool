#!/usr/bin/env bash
# setup.sh — 新机克隆后跑一次：skills副本 + hook挂载 + 本地配置，一条命令满血
# 2026-10-19 建；配合"单commit重启"使用
set -e
cd "$(dirname "$0")/.."

echo "[1/3] 同步 skills/ -> .claude/skills/ ..."
node scripts/sync_skills.mjs

echo "[2/3] 挂载 md 格式 hook ..."
mkdir -p .claude/hooks
cp scripts/md/post_md_fix.sh .claude/hooks/post_md_fix.sh
python -c "
import json, pathlib
p = pathlib.Path('.claude/settings.local.json')
p.parent.mkdir(exist_ok=True)
p.write_text(json.dumps({'hooks': {'PostToolUse': [
    {'matcher': 'Edit|Write',
     'hooks': [{'type': 'command', 'command': 'bash .claude/hooks/post_md_fix.sh'}]}
]}}, indent=2), encoding='utf-8')
print('  settings.local.json written')
"

echo "[3/3] 完成自检 ..."
ls .claude/skills >/dev/null 2>&1 && echo "  skills 副本 OK" || echo "  ⚠ skills 副本缺失，检查 node 和 sync_skills.mjs"
test -f .claude/hooks/post_md_fix.sh && echo "  hook OK"
echo "✅ setup done — 新机还需: venv (scripts/venv) / models (scripts/models) / MySQL 按需手动"
