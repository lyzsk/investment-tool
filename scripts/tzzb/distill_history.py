# -*- coding: utf-8 -*-
"""distill_history.py — tzzb 导师历史回溯蒸馏(2026-10-11 建; 与 distill_daily.py 同族, 一次性全量 vs 每日增量)

缘由: rules.md 长期空骨架的根因=只有 distill_daily(当日增量, 10/8 起)在跑, 180+ 天 32B【推测】初稿从未被
  LLM 提炼; 每晚 1 天素材过不了"样本≥2"门槛。本脚本对全历史做一次回溯蒸馏。
流程(每导师): ①机械层(零 token): gen_tzzb_profile 统计→profile_stats.txt; 全历史逐日小节抽取→history_sections.md
  ②单个 claude -p 按 tzzb-skill distill 工作流(五闸门+消费分级)+情境四元组产出新版 rules.md+report.md
  ③产物只落 results/distill_history/<ledger>/(暂存), **不碰 skills/**——人审后再合并(合并后须 gen_rules_index+sync_skills)
幂等: <out>/DONE 存在=跳过; 失败不阻塞下一位(串行, 不并发)。子进程 CREATE_NO_WINDOW(10/8 零弹窗立法)。
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/distill_history.py [--ledger a,b] [--force]
"""
import argparse, json, os, subprocess, sys, time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
from llm_batch_tzzb import md_path, canon, extract_section  # 小节口径与 32B 初稿同源(禁另立)
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from claude_call import call as claude_call  # noqa: E402
LEAN_ARGS = ["--exclude-dynamic-system-prompt-sections", "--disable-slash-commands", "--strict-mcp-config",
             "--tools", "Read,Write,Edit,Grep,Glob"]   # 10/15 A13①(同 settle_decisions._call / 链驱动器 CLAUDE 口径)

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

def _claude_json(stdout):
    """10/11: claude -p 经网关时会在 JSON 前打印提示横幅(如 auto mode 计费说明), 只取最后一个 JSON 对象行"""
    for line in reversed((stdout or "").strip().splitlines()):
        if line.lstrip().startswith("{"):
            return json.loads(line)
    return json.loads(stdout or "")

_EXE = os.path.join(os.environ.get("APPDATA", ""), r"npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe")
CLAUDE = [_EXE if os.path.exists(_EXE) else "claude", "-p", "--output-format", "json", "--permission-mode", "acceptEdits"]
# 土豆(转债)走机械五闸门分支不在此列; 数据少的排后, chong5000w 源 07-06 停更但历史可蒸
# 10/17 二B-4: 名单读导师登记表; _PRIO 只管排序偏好, 登记表新增的导师自动排在末尾
import mentors  # noqa: E402  (scripts/lib 已在 sys.path)
_PRIO = ["stzhilang", "xingjianye", "lianghuaxiaohao", "a658", "bianbenling", "liuyiqing",
         "gaogailvfuli", "xuanqiucaijing", "daxingdaxingdadangxing", "chong5000w", "antoo", "zhiyingjuexin", "zjwzlclf", "ynw01", "wudaokongfang"]
_TZ = [x for x in mentors.ids("tzzb") if x != "buchitudou0"]
DEFAULT = [x for x in _PRIO if x in _TZ] + [x for x in _TZ if x not in _PRIO]

PROMPT = """任务: 对 tzzb 导师「{name}」(ledger={ledger}) 做**历史回溯蒸馏**(一次性覆盖全部历史), 产出新版规则库草稿。元指令: 任务优先, 禁反问。

先读(全部只读):
- skills/tzzb-skill/workflows/distill.md —— 按其「LLM 提取流程」第 2-5 步执行(五闸门准入 + 消费分级 + 防串扰), 区别仅在对象=全历史而非单日
- skills/{ledger}-skill/persona/ 下 profile.md、rules.md、cases.md(现有画像/规则/案例)
- 格式样板 skills/liuyiqing-skill/persona/rules.md —— 只学格式, 禁借其内容(防串扰铁律)

证据(按强度排序):
1. {out}/profile_stats.txt —— 机械统计底座, 规则里的一切数字必须出自它(手写数字=违规)
2. skills/{ledger}-skill/persona/cases.md 的机械双尾样本区
3. {out}/history_sections.md —— 全历史 {ndays} 个交易日逐日小节。硬数据行(净值/持仓/成交)=事实;
   【推测】行(多为"(32B初稿)")=**未经复核的假设**: 只能当线索, 须用同日或多日硬数据核实后才能进证据链;
   空泛推测(如"可能触发风控暂停机制")直接丢弃

规则准入: 五闸门全过; 样本≥2 且每个样本带日期锚点; 每条新增**情境四元组**:
  行情(大盘环境: 普涨/普跌/震荡, 主线是否清晰) / 阶段(情绪周期: 冰点/修复/主升/高潮/退潮) /
  板块(所在方向或板块簇) / 票数行为(同日几票、集中或分散、加减仓节奏)
  ——每一元必须来自证据里可查的事实, 查不到就写"未知", 禁编。消费分级 [可跟]/[画像]/[教训] 必标。{extra}
现有规则: 逐条用全历史核销(兑现/打脸/欠定, 更新样本数), 不删除; 被打脸的降级并注明。

输出——只许写下面两个文件, 禁止写任何其他路径(尤其禁止修改 skills/ 下任何文件):
- {out}/rules.md: 完整的新版 rules.md(沿用原文件头说明与五闸门节, 规则区重排)
- {out}/report.md: 变更报告——新增/修订/降级各几条及各一句理由; 被丢弃的高频推测假设 Top5 及丢弃理由; 不自信点;
  末行只写: DISTILL_HIST_OK {ledger}
"""


def log(m):
    print(f"[{datetime.now():%m-%d %H:%M}] {m}", flush=True)


def build_inputs(L, out):
    """机械层: 统计画像 + 全历史小节抽取 → 返回小节天数"""
    r = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT_DIR / "gen_tzzb_profile.py"), "--ledger", L["ledger"]],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
    (out / "profile_stats.txt").write_text((r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.returncode else ""), encoding="utf-8")
    nav = ROOT / "downloads" / "tzzb" / L["ledger"] / "nav_daily.json"
    days = sorted(f"{d[:4]}-{d[4:6]}-{d[6:8]}" for d in
                  (x["date"] for x in json.loads(nav.read_text(encoding="utf-8"))["ex_data"]["index_list"]))
    parts = []
    for day in days:
        p = md_path(day)
        if not p.exists():
            continue
        sec = extract_section(p.read_text(encoding="utf-8").splitlines(), canon("#### " + L["name"]))
        if sec:
            parts.append(f"## {day}\n" + "\n".join(sec[2][1:]).strip())
    (out / "history_sections.md").write_text(
        f"# {L['name']}({L['ledger']}) 全历史逐日小节({len(parts)} 日, 机械抽取自 md/, distill_history.py)\n\n" + "\n\n".join(parts) + "\n",
        encoding="utf-8")
    return len(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default="", help="逗号分隔; 缺省=全部正例(土豆除外)")
    ap.add_argument("--force", action="store_true", help="忽略 DONE 重跑")
    a = ap.parse_args()
    meta = {l["ledger"]: l for l in json.loads((SCRIPT_DIR / "tzzb_ledgers.json").read_text(encoding="utf-8"))}
    todo = [x for x in (a.ledger.split(",") if a.ledger else DEFAULT) if x]
    for lg in todo:
        L = meta.get(lg)
        if not L or L.get("kind") == "neg":
            log(f"{lg}: 未知或负样本, 跳过")
            continue
        out = ROOT / "results" / "distill_history" / lg
        out.mkdir(parents=True, exist_ok=True)
        if (out / "DONE").exists() and not a.force:
            log(f"{lg}: 已有 DONE, 跳过")
            continue
        n = build_inputs(L, out)
        log(f"{lg}: 机械层完成, 小节 {n} 日 → claude -p 蒸馏")
        extra = "\n  本导师产出须标\"(程序化嫌疑)\"。" if lg == "lianghuaxiaohao" else ""
        # 10/15: 大账本(antoo 拆单极碎: history 321KB + cases 机械区 204KB)全读会撑爆上下文/成本 → 体量提示, 让模型检索取证
        kb = sum((p.stat().st_size if p.exists() else 0) for p in (out / "history_sections.md", ROOT / "skills" / f"{lg}-skill" / "persona" / "cases.md")) // 1024
        if kb > 300:
            extra += (f"\n  证据体量大(history_sections+cases 约 {kb}KB): 先通读 profile_stats.txt; cases.md 机械区与 history_sections.md "
                      "用 Grep/分段 Read 按需取证(按月份/熟票/桶抽样核实), 不必逐行读完; report.md 里写明抽样范围。")
        prompt = PROMPT.format(name=L["name"], ledger=lg, out=str(out).replace("\\", "/"), ndays=n, extra=extra)
        t0 = time.time()
        # 10/15 A13①: 改走公共 claude_call(prompt 走 stdin/信封判错/成本记 scripts/lib/claude_cost.csv/key 轮换) + 精简参数
        #   (去动态系统提示/斜杠命令/MCP, 工具白名单只给读写检索——本任务只读证据写两个文件, 不需要 Bash)
        r = claude_call(prompt, tag=f"tzzb-distill-history:{lg}", permission="acceptEdits", timeout=3600,
                        extra_args=LEAN_ARGS, expect_files=[out / "report.md", out / "rules.md"])
        rep = out / "report.md"
        ok = r.ok and rep.exists() and rep.read_text(encoding="utf-8").strip().splitlines()[-1].strip() == f"DISTILL_HIST_OK {lg}" \
            and (out / "rules.md").exists()
        u = r.usage or {}
        log(f"{lg}: {'OK' if ok else 'FAIL'} ({time.time() - t0:.0f}s, cost={r.cost_usd:.2f}, rc={r.returncode}, "
            f"cache_create={u.get('cache_creation_input_tokens', '?')}, errors={'|'.join(r.errors)[:160]})")
        if ok:
            (out / "DONE").write_text(datetime.now().isoformat(), encoding="utf-8")
        else:
            (out / "claude_stdout.txt").write_text((r.stdout_tail or "")[-5000:] + "\n" + (r.stderr_tail or "")[-2000:], encoding="utf-8")
    log("ALL_DONE")


if __name__ == "__main__":
    main()
