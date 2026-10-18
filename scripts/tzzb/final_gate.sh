#!/usr/bin/env bash
# final_gate.sh — 10/7 总收尾调度: F3(32B)跑完→放行 E-replay(md 合成)→E 完→护卫港硬数据+32B 三跑
set -x
cd /c/Users/admin/dev/investment-tool
# ① 等 follower F3 完成
for i in $(seq 1 240); do grep -aq "expand8 DONE" scripts/tzzb/expand8.log 2>/dev/null && break; sleep 120; done
echo "=== [G1] F3 完, 放行 E-replay $(date) ==="
rm -f scripts/backfill_taoge/PAUSE
# ② 等 E-replay 完成(第二个 总账 标记)
for i in $(seq 1 240); do [ "$(grep -ac '=== 总账' scripts/backfill_taoge/coldstart.log)" -ge 2 ] && break; sleep 120; done
echo "=== [G2] E-replay 完, 护卫港硬数据 $(date) ==="
node scripts/tzzb/gen_tzzb_md.mjs --ledger huweigang --all --write || echo "HWG_MD_FAIL"
echo "=== [G3] 32B 三跑(护卫港+散欠) $(date) ==="
scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/llm_batch_tzzb.py || echo "LLM3_FAIL"
echo "paused-final-gate-20261007 全部收尾" > scripts/backfill_taoge/PAUSE
echo "=== final_gate DONE $(date) ==="
