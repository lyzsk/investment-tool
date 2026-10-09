for lid in liuyiqing lianghuaxiaohao a658; do
  [ -f "results/${lid}_chain/live-20261008/06_verdict.md" ] && { echo "$lid 已有 06, 跳过"; continue; }
  rm -rf "results/${lid}_chain/live-20261008"
  scripts/venv/Scripts/python.exe -X utf8 scripts/taoge-chain/run_taoge_chain.py --skill "$lid" --slot 0915 --date 20261008 2>&1 | tail -3
  echo "--- $lid 完 $(date)"
done
