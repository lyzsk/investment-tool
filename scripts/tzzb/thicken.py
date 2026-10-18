# -*- coding: utf-8 -*-
"""thicken.py — 用导师全部历史买卖腿给 skill 加厚 rules / cases(10/18 用户令: "把 cases、rules 加厚, 这样才是提高拟人化的方式")

为什么: 每日蒸馏只记"显著"的, tzzb 只有成交没有讲解 → 叙事案例 0~3 条、规则 8~14 条, 漏斗升不上来;
        但历史腿每人 100~2400 条, 机械层已挖了选股 / 买点(fingerprint)和持仓处理(hold_mining), 没变成规则和案例。
流程(每导师): ① 机械层(零 token, 已有): fingerprint.md + scripts/tzzb/model_out/reports/hold_mining_<id>.md
             ② 一个 claude -p 读机械层 + 现有 rules_index / cases.md, 写**新增**规则和案例卡到暂存
                results/thicken/<id>/{rules_new.md, cases_new.md, report.md}(不碰 skills/)
             ③ --merge: 暂存并进 skills(规则插在「速览行」节之前, 案例插在 cases.md 机械双尾区之前) → 规则时间状态 / 规则索引 / 画像快照 / 同步
规则口径: 单样本可进(标 [单样本], 10/18 R27); 每条必须有条件→动作→占比/样本数→证据锚点→可证伪条件; 不改不删已有规则(只新增)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/thicken.py --ledger liuyiqing [--force]   |   --merge --ledger liuyiqing
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from claude_call import call as claude_call   # noqa: E402
import mentors as M                          # noqa: E402

PY = str(ROOT / "scripts" / "venv" / "Scripts" / "python.exe")
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LEAN_ARGS = ["--exclude-dynamic-system-prompt-sections", "--disable-slash-commands", "--strict-mcp-config", "--tools", "Read,Write,Edit,Grep,Glob"]

PROMPT = """任务: 给 tzzb 导师「{name}」(ledger={id}) 的 skill **加厚规则和案例**。元指令: 任务优先, 禁反问; 只读下面列的文件, 只写暂存目录 {out}/。

背景: 他的 rules.md 只有 {n_rules} 条、cases.md 叙事案例只有 {n_cases} 条, 太薄, paper 链学不像。但他的全部历史买卖腿已被机械统计成两份材料:
- `skills/{id}-skill/persona/fingerprint.md` —— 选股 / 买点 / 卖出 / 市况-仓位 / 盘中节奏 / 典型选股规则 / 反例(全历史逐笔统计)
- `scripts/tzzb/model_out/reports/hold_mining_{id}.md` —— 持仓处理手法: "持仓遇到某情境(高开/低开/昨涨停/浮盈浮亏/持有天数/盘中冲高/大盘)时他怎么做"的条件分布 + 代表例子
现有规则先看 `skills/{id}-skill/persona/rules_index.md`(一行一条), 需要时再按行号读 rules.md; 现有案例看 `skills/{id}-skill/persona/cases.md`。

要做:
1. **新增规则** → 写 `{out}/rules_new.md`。目标 8~15 条, 重点补现有规则没覆盖的: 持仓处理(什么情况清 / 减 / 加 / 拿)、卖出时机、加仓条件、仓位管理、大盘差时怎么做、他的反常习惯。
   - 只新增, 不重复现有规则(意思相同的跳过; 是对现有规则的补充就写成新规则并在标题注明"补 R?")。
   - 编号从 R{next_r} 起连续; 每条用和现有 rules.md 一样的块格式, 标题行 `### R<n> <一句话规则> [画像]（10/18 历史全量挖掘新增）`, 下面至少这几行:
     `- **规则**:` 条件 → 动作(写成"当…时, 他…"), 带占比和样本数(如"持 1 天的仓 64% 次日清仓, n=104");
     `- **证据链**:` 指向材料里的具体条目(如"hold_mining 持有天数=持1天 条"、"fingerprint 四、卖出指纹")+ 1~2 个日期例子;
     `- **竞争假设**:` 至少两个解释 + 你给的概率;
     `- **证伪条件**:` 机械可判的一句;
     `- **验证状态**:` [样本 n] 或 [单样本]。
   - 样本 <5 的也可以写, 标 [单样本] 或 [小样本 n=…]; 数字只许抄材料里的, 不许自己编。
   - hold_mining 每条带"滚动验证"结论(训练 40 个交易日 → 验证随后 10 个交易日, 整体往后滑, 10/18 用户定: 短线打法分阶段):
     **"近期有效"的才能写成规则主体**(验证状态写 [样本 n · 滚动验证近期有效 · 通过率 x%]);
     "曾有效·近期失效"写成规则但标明"某段时间成立、最近不成立"(写清成立的日期段); "过时 / 不稳定 / 样本不足"只能写成 [单样本]/[线索] 级或不写。
     (若报告是旧格式"时间外通过/未通过", 按 通过≈近期有效、未通过≈不稳定 理解。)
2. **新增案例卡** → 写 `{out}/cases_new.md`。目标 12~20 张, 从两份材料的例子里挑, 每张:
   `### [类型] 日期 标题`(类型取 持仓处理 / 卖飞 / 逃顶 / 反例 / 加仓 / 换股 之一), 下面 `- 背景:`(当天开盘/盘中/浮盈/已持天数/大盘)`- 行为:`(他做了什么、几点)`- 结果:`(次日涨跌)`- 对应规则:`(新或旧规则编号)。
   至少三分之一是反例 / 卖飞 / 亏损的(反例比正例更校准画像)。
3. 写 `{out}/report.md`: 新增规则列表(编号+一句话+样本数)、新增案例数、你认为最有价值的 3 条和最不确定的 3 条。
4. 全部写完后单独一行输出 `THICKEN_OK {id}`。
"""

PROMPT2 = """任务: 给 tzzb 导师「{name}」(ledger={id}) 的 skill **第二轮加厚(更深)**。元指令: 任务优先, 禁反问; 只读下面列的文件, 只写暂存目录 {out}/。

背景: 第一轮已从统计汇总里加了一批规则/案例(现在 rules {n_rules} 条、叙事案例 {n_cases} 条), 但只用了汇总, 没看逐日明细。他有 {n_cards} 个有操作/持仓的交易日。
本轮新材料(全部机械生成、全是事实):
- `skills/{id}-skill/persona/case_log/index.md` —— 每个交易日一行(日期 + 机械标签), 点进 `case_log/<YYYY-MM>.md` 看当天完整日卡(大盘 / 昨收持仓 / 竞价 / 每笔成交及成交那一分钟的盘中状态 / 仓位变化 / 次日结果)
- `scripts/tzzb/model_out/reports/hold_mining_{id}.md` —— 新版: 单项 + 两条件组合 + 次日序列 + 建仓侧(开仓大小 / 加仓条件), 每条带**滚动验证**结论(训练 40 日 → 验证随后 10 日, 往后滑): 近期有效 / 曾有效·近期失效 / 过时 / 不稳定 / 样本不足
现有规则看 `skills/{id}-skill/persona/rules_index.md`, 现有案例看 `cases.md`(已有的别重复)。

要做:
1. **通读 index.md 全部日期的标签**, 按标签组合把交易日分成若干"手法类"(如 低开砍仓 / 冲高卖 / 满仓换股 / 尾盘建仓 / 正T / 空仓→建仓 ...), 每类至少打开 2~3 张日卡细看; 月份要覆盖全(早期和近期都要看, 打法可能变了)。
2. **新增规则** → `{out}/rules_new.md`, 目标 10~20 条, 编号从 R{next_r} 起, 格式同第一轮(标题 `### R<n> <一句话> [画像]（10/18 第二轮·逐日日卡新增）` + 规则 / 证据链 / 竞争假设 / 证伪条件 / 验证状态):
   - 优先写 hold_mining 里**"近期有效"**和**"曾有效·近期失效"**(写明成立日期段)且现有规则没覆盖的;
   - 再写从日卡里看出来、统计没覆盖的**手法细节**(几点动手、挂价相对开盘/均价、分几笔、先卖后买还是先买后卖、亏损时怎么处理、连续亏几天后怎么变);
   - 证据链必须引用具体日卡日期(≥2 个, 单样本标 [单样本]); 数字只抄材料, 不许编; 阶段性的写清哪段时间。
3. **新增案例卡** → `{out}/cases_new.md`, 目标 25~40 张, 从日卡里挑, 让每个"手法类"都有代表, 早期 / 近期都有, 至少三分之一是亏损 / 卖飞 / 反例; 格式同第一轮(`### [类型] 日期 标题` + 背景 / 行为 / 结果 / 对应规则)。
4. `{out}/report.md`: 手法类清单(每类日数 + 代表日期)、新增规则 / 案例数、看过哪些月份、最有价值 3 条与最不确定 3 条。
5. 全部写完后单独一行输出 `THICKEN2_OK {id}`。
"""


def counts(sk):
    rules = (ROOT / "skills" / f"{sk}-skill" / "persona" / "rules.md").read_text(encoding="utf-8")
    cases = (ROOT / "skills" / f"{sk}-skill" / "persona" / "cases.md").read_text(encoding="utf-8")
    nums = [int(x) for x in re.findall(r"^#{3,4} +R(\d+)\b", rules, re.M)]
    return len(nums), len(re.findall(r"^### \[", cases, re.M)), (max(nums) + 1 if nums else 1)


def n_cards(sk):
    f = ROOT / "skills" / f"{sk}-skill" / "persona" / "case_log" / "index.md"
    return len(re.findall(r"^- \[\d{4}-\d\d-\d\d\]", f.read_text(encoding="utf-8"), re.M)) if f.exists() else 0


def run(sk, force, pass2=False):
    try:   # 10/18: 用户去掉不进 paper 的导师, 要不要继续加厚 skill 待定 → 先跳过(省 token), 定了再跑
        if sk in (json.loads((ROOT / "scripts" / "tzzb" / "paper_excluded.json").read_text(encoding="utf-8")).get("excluded") or {}) and not force:
            print(f"{sk}: 不进 paper(paper_excluded.json), 加厚先跳过(--force 强跑)")
            return 0
    except (OSError, ValueError):
        pass
    out = ROOT / "results" / ("thicken2" if pass2 else "thicken") / sk
    if (out / "DONE").exists() and not force:
        print(f"{sk}: 已有暂存(DONE), 跳过(--force 重跑)")
        return 0
    if not (ROOT / "scripts" / "tzzb" / "model_out" / "reports" / f"hold_mining_{sk}.md").exists():
        print(f"{sk}: 缺 hold_mining 报告, 先跑 hold_mining.py")
        return 1
    out.mkdir(parents=True, exist_ok=True)
    nr, nc, nx = counts(sk)
    rel = str(out.relative_to(ROOT)).replace("\\", "/")
    if pass2:
        if not n_cards(sk):
            print(f"{sk}: 缺 case_log 日卡, 先跑 case_log.py")
            return 1
        prompt = PROMPT2.format(name=M.get(sk)["name"], id=sk, out=rel, n_rules=nr, n_cases=nc, next_r=nx, n_cards=n_cards(sk))
    else:
        prompt = PROMPT.format(name=M.get(sk)["name"], id=sk, out=rel, n_rules=nr, n_cases=nc, next_r=nx)
    tok = "THICKEN2_OK" if pass2 else "THICKEN_OK"
    r = claude_call(prompt, tag=f"tzzb-thicken{'2' if pass2 else ''}:{sk}", permission="acceptEdits", timeout=3600, extra_args=LEAN_ARGS,
                    sentinels=[f"{tok} {sk}"], require_sentinels=True, expect_files=[out / "rules_new.md", out / "cases_new.md", out / "report.md"])
    print(f"{sk}: ok={r.ok} cost=${r.cost_usd:.2f} 用时 {r.duration_s:.0f}s errors={r.errors[:3]}")
    if r.ok:
        (out / "DONE").write_text(dt.datetime.now().isoformat(), encoding="utf-8")
    return 0 if r.ok else 1


def merge(sk, pass2=False):
    out = ROOT / "results" / ("thicken2" if pass2 else "thicken") / sk
    pdir = ROOT / "skills" / f"{sk}-skill" / "persona"
    rn, cn = (out / "rules_new.md").read_text(encoding="utf-8").strip(), (out / "cases_new.md").read_text(encoding="utf-8").strip()
    rules, cases = (pdir / "rules.md").read_text(encoding="utf-8"), (pdir / "cases.md").read_text(encoding="utf-8")
    bak = ROOT / "scripts" / "temp" / "night_bak" / ("thicken2_before" if pass2 else "thicken_before") / sk
    bak.mkdir(parents=True, exist_ok=True)
    (bak / "rules.md").write_text(rules, encoding="utf-8")
    (bak / "cases.md").write_text(cases, encoding="utf-8")
    rn = "\n".join(l for l in rn.splitlines() if not l.startswith("# "))   # 去掉暂存文件自带的一级标题
    cn = "\n".join(l for l in cn.splitlines() if not l.startswith("# "))
    block_r = (f"\n\n## 逐日日卡第二轮新增（10/18 thicken.py --pass2; 来源 case_log/ + hold_mining_{sk}.md 滚动验证）\n\n{rn}\n\n" if pass2 else
               f"\n\n## 历史全量挖掘新增（10/18 thicken.py; 来源 fingerprint.md + hold_mining_{sk}.md）\n\n{rn}\n\n")
    m = re.search(r"^## 速览行", rules, re.M)
    rules = rules[:m.start()] + block_r.lstrip("\n") + rules[m.start():] if m else rules.rstrip() + block_r
    block_c = f"\n## {'逐日日卡第二轮案例卡（10/18 thicken.py --pass2）' if pass2 else '历史全量挖掘案例卡（10/18 thicken.py）'}\n\n{cn}\n\n"
    m = re.search(r"^## 执行质量双尾样本库", cases, re.M)
    cases = cases[:m.start()] + block_c.lstrip("\n") + cases[m.start():] if m else cases.rstrip() + "\n" + block_c
    (pdir / "rules.md").write_text(rules, encoding="utf-8")
    (pdir / "cases.md").write_text(cases, encoding="utf-8")
    for cmd in ([PY, "-X", "utf8", "scripts/md/rule_time_state.py", "--skill", sk, "--write"], ["node", "scripts/md/gen_rules_index.mjs", "--skill", sk]):
        subprocess.run(cmd, cwd=ROOT, creationflags=NOWIN, capture_output=True, text=True, encoding="utf-8", errors="replace")
    nr, nc, _ = counts(sk)
    print(f"{sk}: 并入后 规则 {nr} 条 / 叙事案例 {nc} 张(改前备份 {bak.relative_to(ROOT)})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--pass2", action="store_true", help="第二轮: 读逐日日卡 case_log + 滚动验证挖掘")
    a = ap.parse_args()
    rc = 0
    for sk in a.ledger.split(","):
        rc |= (merge(sk, a.pass2) or 0) if a.merge else run(sk, a.force, a.pass2)
    if a.merge:
        subprocess.run([PY, "-X", "utf8", "scripts/skills_ver/persona_versions.py", "snapshot", "--all", "--why", "10/18 thicken 历史挖掘加厚"], cwd=ROOT, creationflags=NOWIN, capture_output=True)
        subprocess.run(["node", "scripts/sync_skills.mjs"], cwd=ROOT, creationflags=NOWIN, capture_output=True)
    return rc


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
