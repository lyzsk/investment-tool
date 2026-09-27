#!/bin/bash
# Q3 合并综合陈述批量合成 (2026-09-24 晚, 用户批准: 今晚 headless 全跑 57 天)
# 流程: 等 vision 批(bnhyv7zg0)跑完 -> strip OCR 标记行 -> 逐日 headless claude -p 合成
# 断点续跑: md 里 #### 解读/#### 画面 都不在 = 已合成, 跳过
cd "$(dirname "$0")"
LOG=downloads/synthesize_q3.log
OUTDIR=downloads/synthesize_out
mkdir -p "$OUTDIR"

echo "[synthesize] start $(date '+%F %T')" >> "$LOG"

# ---- 1. 等 vision 批完成(12h 上限) ----
for i in $(seq 1 720); do
  if grep -q "batch done" downloads/batch_vision_q3.log 2>/dev/null; then
    echo "[synthesize] vision batch done detected" >> "$LOG"
    break
  fi
  sleep 60
done
if ! grep -q "batch done" downloads/batch_vision_q3.log 2>/dev/null; then
  echo "[synthesize] FATAL: vision batch not done after 12h, abort" >> "$LOG"
  exit 1
fi

# ---- 2. strip 历史 OCR 标记行(fill 批是旧内存写的, 现格式已废标记) ----
venv/Scripts/python.exe - <<'EOF' >> "$LOG" 2>&1
import re
from pathlib import Path
n = 0
for md in Path("../../stocks/2026S3").glob("*.md"):
    t = md.read_text(encoding="utf-8")
    t2 = re.sub(r"^<!-- OCR自动填充:.*-->\n?", "", t, flags=re.M)
    if t2 != t:
        md.write_text(t2, encoding="utf-8")
        n += 1
print(f"[strip] 去掉 OCR自动填充 标记行: {n} 个文件")
EOF

# ---- 3. 逐日合成 ----
# 倒叙: 近两周优先(订阅额度有限, 额度耗尽时牺牲最早的日子)
pairs=$(venv/Scripts/python.exe -c "
import json
d = json.load(open('downloads/q3_videos.json', encoding='utf-8'))
for k in sorted(d, reverse=True): print(k, d[k])
" | tr -d '\r')

ok=0; fail=0; skip=0
echo "$pairs" | while read -r date bvid; do
  [ -z "$date" ] && continue
  md="../../stocks/2026S3/${date}.md"
  [ "$date" = "2026-09-24" ] && { echo "[skip] $date 样品已手写" >> "$LOG"; continue; }
  [ ! -f "$md" ] && { echo "[skip] $date 无 md" >> "$LOG"; continue; }
  # 断点: 已合成(无 #### 解读 且无 #### 画面)跳过
  if ! grep -q "^#### 解读" "$md" && ! grep -q "^#### 画面" "$md"; then
    echo "[skip] $date 已是合成格式" >> "$LOG"
    continue
  fi
  prompt=$(sed -e "s/{DATE}/$date/g" -e "s/{BVID}/$bvid/g" synthesize_prompt.md)
  echo "[run] $date $bvid $(date '+%T')" >> "$LOG"
  timeout 900 claude -p "$prompt" \
    --permission-mode acceptEdits \
    --allowedTools "Read,Edit,Write,Glob,Grep" \
    > "$OUTDIR/$date.log" 2>&1
  rc=$?
  # 验收: ### 桃哥 还在, #### 解读/#### 画面 没了
  if grep -q "^### 桃哥" "$md" && ! grep -q "^#### 解读" "$md" && ! grep -q "^#### 画面" "$md"; then
    echo "[PASS] $date rc=$rc" >> "$LOG"
  else
    echo "[FAIL] $date rc=$rc 验收不通过(结构未达目标)" >> "$LOG"
  fi
  sleep 3
done

echo "[synthesize] all done $(date '+%F %T')" >> "$LOG"
grep -c "^\[PASS\]" "$LOG" | xargs echo "PASS total:" >> "$LOG"
grep "^\[FAIL\]" "$LOG" >> "$LOG" 2>/dev/null
echo "[synthesize] finished" >> "$LOG"
