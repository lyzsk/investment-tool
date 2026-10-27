# -*- coding: utf-8 -*-
"""rules_split_log.py — 把 rules.md 里的核销过程记录挪到 persona/rule_log.md(10/26 用户批: rules.md 只留规则本身 + 一行验证状态; 零 token)

挪走的行(规则块 ### Rn 里, 单行 bullet 及其缩进续行):
  - **竞争假设** / - **证伪条件** / - **反例… / - **MM-DD 登记后样本… / - **登记后样本… / - **与旧规则冲突**
rule_log.md 按 "### Rn <标题>" 分节追加(同一条规则再挪就接在该节末尾); rules.md 文件头加一行指针
幂等: 每晚 check md 在 tzzb 蒸馏之后跑一次, 把蒸馏新写进 rules.md 的这类行挪走
用法: python rules_split_log.py [--skill id ...] [--dry]
"""
import argparse
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAT = re.compile(r"^- \*\*(竞争假设|证伪条件|反例|\d{2}-\d{2} 登记后样本|登记后样本|与旧规则冲突)")
HEAD = re.compile(r"^### (R[\w\-]+|[A-Z]\d+[\w\-]*) ")
NOTE = "> 核销过程记录(竞争假设 / 证伪条件 / 反例 / 登记后样本)在同目录 `rule_log.md`, 按 ### 规则编号分节(10/26 起; scripts/md/rules_split_log.py 每晚挪)"


def split(text):
    """→ (新 rules 文本, {(编号, 标题): [行]})"""
    L, out, moved = text.split("\n"), [], {}
    cur, i = None, 0
    while i < len(L):
        l = L[i]
        if l.startswith("## "):
            cur = None
        m = HEAD.match(l)
        if m:
            cur = (m.group(1), l[4:].strip())
        if cur and PAT.match(l):
            blk = [l]
            while i + 1 < len(L) and L[i + 1].startswith("  ") and L[i + 1].strip():
                i += 1
                blk.append(L[i])
            moved.setdefault(cur, []).extend(blk)
        else:
            out.append(l)
        i += 1
    return "\n".join(out), moved


def merge_log(old, moved, sk):
    secs = {}
    order = []
    hdr = f"# {sk} · 规则核销记录(从 rules.md 挪来; 规则本身在 rules.md, 这里只放过程: 竞争假设 / 证伪条件 / 反例 / 登记后样本)\n"
    body = old.split("\n### ", 1)
    if old.strip():
        hdr = body[0].rstrip("\n") + "\n"
        rest = ("### " + body[1]) if len(body) > 1 else ""
        for blk in re.split(r"\n(?=### )", rest):
            if blk.startswith("### "):
                k = blk.split("\n", 1)[0][4:].split(" ", 1)[0]
                secs[k] = blk.rstrip("\n")
                order.append(k)
    for (rid, title), lines in moved.items():
        if rid in secs:
            secs[rid] += "\n" + "\n".join(lines)
        else:
            secs[rid] = f"### {title}\n" + "\n".join(lines)
            order.append(rid)
    return hdr + "\n" + "\n\n".join(secs[k] for k in order) + "\n"


def run(sk, dry=False):
    f = ROOT / "skills" / f"{sk}-skill" / "persona" / "rules.md"
    if not f.exists():
        return None
    raw = f.read_bytes()
    nl = "\r\n" if b"\r\n" in raw else "\n"
    t = raw.decode("utf-8").replace("\r\n", "\n")
    new, moved = split(t)
    n = sum(len(v) for v in moved.values())
    if not n:
        return 0
    if NOTE not in new:
        L = new.split("\n")
        k = 1 if L and L[0].startswith("# ") else 0
        L.insert(k, NOTE)
        new = "\n".join(L)
    if dry:
        return n
    lf = f.with_name("rule_log.md")
    old = lf.read_text(encoding="utf-8") if lf.exists() else ""
    log = merge_log(old, moved, sk)
    tmp = lf.with_suffix(".md.tmp")
    tmp.write_bytes(log.replace("\n", nl).encode("utf-8"))
    os.replace(tmp, lf)
    tmp = f.with_suffix(".md.tmp")
    tmp.write_bytes(new.replace("\n", nl).encode("utf-8"))
    os.replace(tmp, f)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", nargs="*")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    sks = a.skill or sorted(d.name[:-6] for d in (ROOT / "skills").glob("*-skill") if (d / "persona" / "rules.md").exists())
    tot = 0
    for sk in sks:
        n = run(sk, a.dry)
        if n:
            print(f"{sk}: 挪 {n} 行{'(dry)' if a.dry else ''}")
            tot += n
    print(f"JSON:{{\"moved\": {tot}}}")


if __name__ == "__main__":
    main()
