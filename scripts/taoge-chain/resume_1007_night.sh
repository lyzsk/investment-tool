#!/usr/bin/env bash
# resume_1007_night.sh — 10/7 晚收尾三件套(app 稳定后自动): elangking sync → 9/28-30 回放 → 天哥 10/3 补账
cd /c/Users/admin/dev/investment-tool
PY=scripts/venv/Scripts/python.exe
echo "=== [0] 等 app 稳定(最多 10min) $(date) ==="
for i in $(seq 1 20); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 5 "http://localhost:8888/api/cb/tzzb/sync?ledger=buchitudou0" -X POST 2>/dev/null)
  [ -n "$code" ] && [ "$code" != "000" ] && break; sleep 30
done
echo "app http=$code, 补 elangking sync $(date)"
curl -s -m 240 -X POST "http://localhost:8888/api/cb/tzzb/sync?ledger=elangking" | head -c 200; echo
echo "=== [1] 9/28-30 A线回放(云端 claude) $(date) ==="
for d in 20260928 20260929 20260930; do
  rm -rf "results/taoge_chain/live-$d" "results/taoge_chain/$d"
  rm -f "scripts/dfcf/paper/plans/${d:0:4}-${d:4:2}-${d:6:2}_A-taoge.md"
  $PY -X utf8 scripts/taoge-chain/run_taoge_chain.py --date "$d" --slot 0915 2>&1 | tail -6
  echo "--- $d 0915 全链完 $(date)"
done
echo "=== [2] 天哥 10/3 md 欠账补一天(llm-batch 幂等) $(date) ==="
$PY -X utf8 scripts/backfill_bilibili/backfill_bilibili.py --up qushitiange --llm-batch 2>&1 | tail -8
echo "=== RESUME ALL DONE $(date) ==="
