# distill_daily.py — 每日 tzzb 导师蒸馏(当日增量, 单会话 claude -p 串行处理全部)
# 10/8 用户纠正: 不是每人一个 claude -p, 是共用一个(省 context 重复加载)
# 10/14: 加 --ledgers a,b,c(只蒸馏这几家; 缺省=全部 11 人, 行为不变)——check md 的"晚到账本补蒸馏"用
# 用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/distill_daily.py [--date 2026-10-08] [--ledgers a658,chong5000w]
import argparse, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import mentors  # noqa: E402  10/17 二B-4: 导师登记表
ALL_LEDGERS = mentors.active_ids("tzzb")   # tzzb 导师链(含土豆), 顺序=登记表序; 10/18 起去掉退出 paper 的导师(只做零 token 维护)

ap = argparse.ArgumentParser()
ap.add_argument("--date", default=None)
ap.add_argument("--ledgers", default=None, help="逗号分隔, 只蒸馏这几家(缺省=全部 11 人)")
a = ap.parse_args()
from datetime import date as _d
target = a.date or _d.today().isoformat()   # 10/14 修: 原 _d().today() 缺参必崩(只在不传 --date 时触发)
if a.ledgers:
    ledgers = [x.strip() for x in a.ledgers.split(",") if x.strip()]
    REG = mentors.ids("tzzb")   # 10/29: 10/24 用户令"样例导师照常蒸馏", check md 已按有账本名单传(含退出 paper 的), 这里还卡 active → 10/26 起整步 exit 2、三天没蒸馏; 点名的按登记表认
    bad = [x for x in ledgers if x not in REG]
    if bad or not ledgers:
        print(f"--ledgers 含未知账本: {bad}(可选: {', '.join(REG)})", flush=True)
        sys.exit(2)
else:
    ledgers = ALL_LEDGERS
n = len(ledgers)
# 10/17 晚用户定: 会话数随人数动态——每会话最多 PER_SESSION 人(params.yaml distill.per_session, 缺省 6), 人数均分;
#   原因: 一个会话塞 18 人上下文涨到二十几万, 每轮都按这个长度重发; 万一缓存失效损失也成倍(10/17 $47 事故)。
#   人人相同的部分(收评)在同日公共包 _common.md, 每个会话只读一次; 会话串行跑(不同时改同一批文件)
PER_SESSION = 6
try:
    import yaml
    PER_SESSION = int(((yaml.safe_load((ROOT / "scripts" / "dfcf" / "paper" / "params.yaml").read_text(encoding="utf-8")) or {})
                       .get("distill") or {}).get("per_session") or PER_SESSION)
except Exception:   # noqa: BLE001
    pass
k = max(1, -(-n // max(1, PER_SESSION)))
groups = [ledgers[i::k] for i in range(k)]   # 轮流分配, 各组人数差 ≤1


def prompt_of(g):
    return f"""调用 skills/tzzb-skill 的 distill 工作流(先读 skills/tzzb-skill/workflows/distill.md), 对以下 {len(g)} 个 ledger 逐一执行 {target} 当日的蒸馏:

{", ".join(g)}

每个 ledger: 只处理 {target} 这一天(当日增量, 不追历史), 核销+增补 persona(profile/rules/language, 全带锚点, 修订记录带日期)。当天无操作=空仓纪律信号, 也是正常结果。

串行逐人处理(不要并发), 每完成一人 stdout 打印一行 "DISTILL_OK <ledger>"。全部完成后打印 "ALL_DISTILL_DONE"。
最终回复(会话最后一条消息)的开头必须逐行重新列出全部 "DISTILL_OK <ledger>" 行, 再写总结, 最后一行 "ALL_DISTILL_DONE"——驱动器只看得到最后一条消息, 中途打印的行会丢。"""


print(f"=== distill_daily {target} ({n} 人 → {k} 个会话, 每会话 ≤{PER_SESSION} 人{'' if n == len(ALL_LEDGERS) else ': ' + ','.join(ledgers)}) ===", flush=True)
# 10/9 用户令: 不限模型——不传 --model, ANTHROPIC_MODEL 覆写由 claude_call 剔除(drop_env 默认), 跟随宿主环境
# 10/12 §5.3: 改走公共模块 claude_call(stdin 传 prompt/json 信封判错/哨兵整行匹配/成本账本 scripts/lib/claude_cost.csv)
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from claude_call import call as claude_call, LEAN_ARGS  # 10/15 A13①: 精简参数(首轮写缓存 47k→18k)
ok, all_done, last = [], True, ""
for gi, g in enumerate(groups, 1):
    r = claude_call(prompt_of(g), tag="tzzb-distill-daily", permission="skip", timeout=3600, sentinels=["ALL_DISTILL_DONE"],
                    extra_args=LEAN_ARGS + ["--tools", "Read,Write,Edit,Grep,Glob,Bash"])
    out = r.result
    got = [l.replace("DISTILL_OK", "").strip() for l in out.splitlines() if "DISTILL_OK" in l and "ALL" not in l]
    ok += got
    print(f"会话 {gi}/{k}: {len(got)}/{len(g)} OK → {got}", flush=True)
    if not r.sentinels.get("ALL_DISTILL_DONE"):
        all_done = False
        last = f"会话 {gi} 末行: {out.strip().splitlines()[-1][:80] if out.strip() else '空'}; {' | '.join(r.errors)[:200]}"
print(f"哨兵: {len(ok)}/{n} OK → {ok}", flush=True)
if all_done:
    print("=== ALL_DISTILL_DONE ===", flush=True)
else:
    print(f"=== 未全部完成({last}) ===", flush=True)
