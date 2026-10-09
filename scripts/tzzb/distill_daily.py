# distill_daily.py — 每日 tzzb 导师蒸馏(当日增量, 单会话 claude -p 串行处理全部)
# 10/8 用户纠正: 不是每人一个 claude -p, 是共用一个(省 context 重复加载)
# 用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/distill_daily.py [--date 2026-10-08]
import argparse, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.stdout.reconfigure(encoding="utf-8")

ap = argparse.ArgumentParser()
ap.add_argument("--date", default=None)
a = ap.parse_args()
from datetime import date as _d
target = a.date or _d().today().isoformat()

prompt = f"""调用 skills/tzzb-skill 的 distill 工作流(先读 skills/tzzb-skill/workflows/distill.md), 对以下 11 个 ledger 逐一执行 {target} 当日的蒸馏:

buchitudou0, liuyiqing, lianghuaxiaohao, a658, bianbenling, xingjianye, daxingdaxingdadangxing, gaogailvfuli, xuanqiucaijing, stzhilang, chong5000w

每个 ledger: 只处理 {target} 这一天(当日增量, 不追历史), 核销+增补 persona(profile/rules/language, 全带锚点, 修订记录带日期)。当天无操作=空仓纪律信号, 也是正常结果。

串行逐人处理(不要并发), 每完成一人 stdout 打印一行 "DISTILL_OK <ledger>"。全部完成后打印 "ALL_DISTILL_DONE"。"""

print(f"=== distill_daily {target} (单会话 x 11 人) ===", flush=True)
# 10/9 用户令: 不限模型——去掉 --model 与 ANTHROPIC_MODEL 覆写, 跟随宿主环境
_env = {**__import__("os").environ}
_env.pop("ANTHROPIC_MODEL", None)
r = subprocess.run(["cmd", "/c", "claude", "-p", "--dangerously-skip-permissions"],
                   input=prompt, cwd=str(ROOT), capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=3600, env=_env)
out = (r.stdout or "")
ok = [l.replace("DISTILL_OK", "").strip() for l in out.splitlines() if "DISTILL_OK" in l and "ALL" not in l]
print(f"哨兵: {len(ok)}/11 OK → {ok}", flush=True)
if "ALL_DISTILL_DONE" in out:
    print("=== ALL_DISTILL_DONE ===", flush=True)
else:
    print(f"=== 未全部完成(末行: {out.strip().splitlines()[-1][:80] if out.strip() else '空'}) ===", flush=True)
