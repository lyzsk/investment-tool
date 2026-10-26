# -*- coding: utf-8 -*-
"""md/rules_lint.py — 沉淀分层 v2 的代码闸(10/25 用户批): 导师 / UP skill 的 rules.md 每条规则必须带「来源」(证据链 / 证据 / 来源 / 出处 / 样本 任一字段)
零 token, 只读; 每晚 check md 跑一次, 缺来源的规则列进 docs/review/rules_lint.md(不改 rules.md: 改 persona 归蒸馏 / 主会话)
另查: 规则有没有「时间状态」(建立 / 最后验证日期) —— 没有的单列(旧规则), 不算违规
用法: python rules_lint.py
"""
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "review" / "rules_lint.md"
SRC = re.compile(r"^\s*-\s*\**\s*(证据链|证据|来源|出处|样本|数据|统计)[^\n]{0,3}?\**\s*[:：(（\[]", re.M)
TS = re.compile(r"时间状态|建立 20\d\d-")
SKIP = ("market-skill", "telegraph-skill", "control-skill", "check-cls-md", "tzzb-skill")   # 知识 skill 另有口径(每条带 n / 置信 / 截至日)


def blocks(t):
    """→ [(编号, 标题, 正文)]; 规则 = ### / #### 开头、编号形如 R12 / A3 / B10; 已删除线(~~)的跳过"""
    out = []
    parts = re.split(r"(?m)^(#{3,4} [^\n]*)$", t)
    for i in range(1, len(parts) - 1, 2):
        m = re.match(r"#{3,4} ([A-Z]{1,2}\d+)\b\s*(.*)", parts[i])
        if m and "~~" not in parts[i][:12]:
            out.append((m.group(1), m.group(2).strip(), parts[i + 1]))
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    L = [f"# rules.md 来源检查（{dt.date.today()}；每条规则必须带「证据链 / 证据 / 来源 / 出处 / 样本」之一）", "",
         "> 脚本 `scripts/md/rules_lint.py`（零 token，只读，不改 rules.md）。缺来源的规则：要么补来源（蒸馏 / 你给），要么降级 / 删。", "",
         "| skill | 规则数 | 缺来源 | 没有时间状态 |", "|---|---|---|---|"]
    detail, tot, bad = [], 0, 0
    for d in sorted((ROOT / "skills").glob("*-skill")):
        if d.name in SKIP:
            continue
        p = d / "persona" / "rules.md"
        if not p.exists():
            continue
        B = blocks(p.read_text(encoding="utf-8", errors="replace"))
        if not B:
            continue
        miss = [(r, t) for r, t, body in B if not SRC.search(body)]
        nots = [r for r, t, body in B if not TS.search(body)]
        tot += len(B)
        bad += len(miss)
        L.append(f"| {d.name[:-6]} | {len(B)} | {len(miss)} | {len(nots)} |")
        if miss:
            detail += [f"- **{d.name[:-6]}**：" + "；".join(f"{r} {t[:30]}" for r, t in miss)]
    L += ["", f"合计 {tot} 条规则，缺来源 {bad} 条。", "", "## 缺来源的规则", ""] + (detail or ["（没有）"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:60]))


if __name__ == "__main__":
    main()
