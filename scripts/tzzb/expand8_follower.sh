#!/usr/bin/env bash
# expand8_follower.sh — 2026-10-07 排队任务: 等 coldstart_chain 全链跑完(等 "DONE" 标记)再执行,
# 防与链内 md 写入互抢(coldstart 写小节 vs migrate 重排全文件 = 丢更新风险)。
# 内容: ①migrate 补 8 新账本骨架(模板已加节) ②gen_tzzb_md --all --write 灌 8 人硬数据
#       ③llm_batch_tzzb 二跑(捞 8 新账本+换窗新增的推测缺口, 32B 零 token)
set -x
cd /c/Users/admin/dev/investment-tool
PY=scripts/venv/Scripts/python.exe

# 等 coldstart DONE(最多等 24h, 每 5min 看一眼)
for i in $(seq 1 288); do
  grep -aq "^=== 总账\|+ echo DONE\|DONE " scripts/backfill_taoge/coldstart.log 2>/dev/null && break
  sleep 300
done
echo "=== [F1] coldstart 已结束, migrate 骨架 $(date) ==="
node scripts/md/migrate_md_template.mjs || echo "MIGRATE_FAIL"

echo "=== [F2] 8 新账本硬数据层 $(date) ==="
for l in daxingdaxingdadangxing gaogailvfuli xuanqiucaijing stzhilang chong5000w xinyanggushen yangdaren liurenih xingjianye; do
  node scripts/tzzb/gen_tzzb_md.mjs --ledger $l --all --write || echo "MD_FAIL $l"
done

echo "=== [F3] 32B 推测初稿二跑(8 新账本+新窗口) $(date) ==="
$PY -X utf8 scripts/tzzb/llm_batch_tzzb.py || echo "LLM_BATCH2_FAIL"
echo "=== expand8 DONE $(date) ==="
