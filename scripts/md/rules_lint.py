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
DIMS = ("大势", "市况", "题材", "个股", "导师", "竞价", "票型", "位置", "情境卡")
STAT = re.compile(r"胜率|命中率|均值|平均|中位|P10|P90|n\s*[=＝]\s*\d+", re.I)
RECENT = re.compile(r"近期|近\s*\d+\s*(?:个)?(?:交易日|日|天)|全期|滚动窗口|样本外")


def context_status(body):
    if "情境卡" in body or len({x for x in DIMS if x in body}) >= 3:
        return "只1例" if re.search(r"n\s*[=＝]\s*1\b|1\s*例|单一样本", body) else "齐"
    return "缺"


def recent_status(body):
    return "齐" if not STAT.search(body) or RECENT.search(body) else "缺"


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
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate", action="store_true", help="旧规则只标情境/近期缺口，不阻断")
    ap.add_argument("--strict", action="store_true", help="新规则/蒸馏验收：有缺情境或缺近期窗口即退出1")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    L = [f"# rules.md 来源/情境/近期检查（{dt.date.today()}）", "",
         "> 来源必须有证据；统计结论必须带近期窗口+全期对照；旧规则只标不拦，--strict 才阻断新沉淀。", "",
         "| skill | 规则数 | 缺来源 | 缺情境 | 缺近期窗口 | 没有时间状态 |", "|---|---|---|---|---|---|"]
    detail, tot, bad, bad_ctx, bad_recent = [], 0, 0, 0, 0
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
        ctx = [(r, context_status(body)) for r, t, body in B if context_status(body) == "缺"]
        recent = [r for r, t, body in B if recent_status(body) == "缺"]
        tot += len(B)
        bad += len(miss)
        bad_ctx += len(ctx)
        bad_recent += len(recent)
        L.append(f"| {d.name[:-6]} | {len(B)} | {len(miss)} | {len(ctx)} | {len(recent)} | {len(nots)} |")
        if miss:
            detail += [f"- **{d.name[:-6]}**：" + "；".join(f"{r} {t[:30]}" for r, t in miss)]
        if ctx:
            detail += [f"- **{d.name[:-6]} 缺情境**：" + "、".join(r for r, _ in ctx)]
        if recent:
            detail += [f"- **{d.name[:-6]} 缺近期窗口**：" + "、".join(recent)]
    L += ["", f"合计 {tot} 条规则，缺来源 {bad} 条；缺情境 {bad_ctx} 条；缺近期窗口 {bad_recent} 条。", "", "## 缺来源/情境/近期的规则", ""] + (detail or ["（没有）"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:60]))
    return int(bool(a.strict and (bad or bad_ctx or bad_recent)))


if __name__ == "__main__":
    sys.exit(main())
