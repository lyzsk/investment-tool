#!/usr/bin/env bash
# grep_verify.sh — 改名/重构后引用面扫描(2026-10-08, GLM 跨文件语义弱缺陷的机械补丁)
# 用法: bash scripts/md/grep_verify.sh <旧路径/旧名> [--json]
# 例:   bash scripts/md/grep_verify.sh "scripts/fetch_bilibili.mjs"
#       bash scripts/md/grep_verify.sh "A-tzzb"
TARGET="$1"
if [ -z "$TARGET" ]; then echo "用法: bash scripts/md/grep_verify.sh <旧路径/旧名>"; exit 1; fi
cd /c/Users/admin/dev/investment-tool
echo "=== 引用面扫描: $TARGET ==="
grep -rn "$TARGET" \
  scripts/ skills/ docs/ inv-stock/src/ inv-admin/src/ inv-system/src/ sql/ \
  --include='*.{py,mjs,js,md,java,yml,yaml,json,sql,xml,sh,cmd}' \
  --exclude-dir=__pycache__ --exclude-dir=node_modules --exclude-dir=.git \
  --exclude-dir=books --exclude-dir=plans --exclude-dir=facts \
  --exclude='*.log' --exclude='*.json' 2>/dev/null | head -30
FOUND=$(grep -rln "$TARGET" \
  scripts/ skills/ docs/ inv-stock/src/ inv-admin/src/ inv-system/src/ sql/ \
  --include='*.{py,mjs,js,md,java,yml,yaml,sql,xml,sh,cmd}' \
  --exclude-dir=__pycache__ --exclude-dir=node_modules --exclude-dir=.git 2>/dev/null | wc -l)
if [ "$FOUND" -gt 0 ]; then
  echo "⚠️  $FOUND 个文件引用 $TARGET——改名/删除前必须同步改或删这些文件"
  exit 1
else
  echo "✅ 无残留引用, 可安全改名/删除"
fi
