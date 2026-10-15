# distill_daily.py — 每日 tzzb 导师蒸馏(当日增量, 单会话 claude -p 串行处理全部)
# 10/8 用户纠正: 不是每人一个 claude -p, 是共用一个(省 context 重复加载)
# 10/14: 加 --ledgers a,b,c(只蒸馏这几家; 缺省=全部 11 人, 行为不变)——check md 的"晚到账本补蒸馏"用
# 用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/distill_daily.py [--date 2026-10-08] [--ledgers a658,chong5000w]
import argparse, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.stdout.reconfigure(encoding="utf-8")
ALL_LEDGERS = ["buchitudou0", "liuyiqing", "lianghuaxiaohao", "a658", "bianbenling", "xingjianye",
               "daxingdaxingdadangxing", "gaogailvfuli", "xuanqiucaijing", "stzhilang", "chong5000w",
               "antoo", "zhiyingjuexin"]   # 10/15 +2 新导师

ap = argparse.ArgumentParser()
ap.add_argument("--date", default=None)
ap.add_argument("--ledgers", default=None, help="逗号分隔, 只蒸馏这几家(缺省=全部 11 人)")
a = ap.parse_args()
from datetime import date as _d
target = a.date or _d.today().isoformat()   # 10/14 修: 原 _d().today() 缺参必崩(只在不传 --date 时触发)
if a.ledgers:
    ledgers = [x.strip() for x in a.ledgers.split(",") if x.strip()]
    bad = [x for x in ledgers if x not in ALL_LEDGERS]
    if bad or not ledgers:
        print(f"--ledgers 含未知账本: {bad}(可选: {', '.join(ALL_LEDGERS)})", flush=True)
        sys.exit(2)
else:
    ledgers = ALL_LEDGERS
n = len(ledgers)

prompt = f"""调用 skills/tzzb-skill 的 distill 工作流(先读 skills/tzzb-skill/workflows/distill.md), 对以下 {n} 个 ledger 逐一执行 {target} 当日的蒸馏:

{", ".join(ledgers)}

每个 ledger: 只处理 {target} 这一天(当日增量, 不追历史), 核销+增补 persona(profile/rules/language, 全带锚点, 修订记录带日期)。当天无操作=空仓纪律信号, 也是正常结果。

串行逐人处理(不要并发), 每完成一人 stdout 打印一行 "DISTILL_OK <ledger>"。全部完成后打印 "ALL_DISTILL_DONE"。
最终回复(会话最后一条消息)的开头必须逐行重新列出全部 "DISTILL_OK <ledger>" 行, 再写总结, 最后一行 "ALL_DISTILL_DONE"——驱动器只看得到最后一条消息, 中途打印的行会丢。"""

print(f"=== distill_daily {target} (单会话 x {n} 人{'' if n == len(ALL_LEDGERS) else ': ' + ','.join(ledgers)}) ===", flush=True)
# 10/9 用户令: 不限模型——不传 --model, ANTHROPIC_MODEL 覆写由 claude_call 剔除(drop_env 默认), 跟随宿主环境
# 10/12 §5.3: 改走公共模块 claude_call(stdin 传 prompt/json 信封判错/哨兵整行匹配/成本账本 scripts/lib/claude_cost.csv)
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from claude_call import call as claude_call
r = claude_call(prompt, tag="tzzb-distill-daily", permission="skip", timeout=3600, sentinels=["ALL_DISTILL_DONE"])
out = r.result
ok = [l.replace("DISTILL_OK", "").strip() for l in out.splitlines() if "DISTILL_OK" in l and "ALL" not in l]
print(f"哨兵: {len(ok)}/{n} OK → {ok}", flush=True)
if r.sentinels.get("ALL_DISTILL_DONE"):
    print("=== ALL_DISTILL_DONE ===", flush=True)
else:
    print(f"=== 未全部完成(末行: {out.strip().splitlines()[-1][:80] if out.strip() else '空'}; {' | '.join(r.errors)[:200]}) ===", flush=True)
