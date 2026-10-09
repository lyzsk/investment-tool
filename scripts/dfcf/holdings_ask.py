#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""holdings_ask.py — 持仓票全链观点按需聚合器(2026-10-09 凌晨, 用户拍板 A 按需版)

定位: 用户持仓票的"问即答"底座——不限时(用户与 hermes 对话/粘贴进 cli 时随时跑),
实时 grep 当日全链产物(01-06/blind)+ md 当日小节 + facts 快照 + paper plans,
聚成一页供"全链路推导+挂单建议"用。零 LLM, 纯机械聚合; 判断与推导由调用方(hermes/Claude)叠加。

用法(venv python, cwd=项目根):
  python scripts/dfcf/holdings_ask.py --code 002714            # 默认今天, 无则最近的 live-*
  python scripts/dfcf/holdings_ask.py --name 牧原 --date 20261008
出口: 0=有产出 1=啥都没找到
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def latest_live(code: str) -> Path | None:
    dirs = sorted(ROOT.glob("results/*/live-*"), reverse=True)
    for d in dirs:
        if any(d.glob("0*.md")):
            return d
    return None


def quarter_of(date_dash: str) -> str:
    y, m = int(date_dash[:4]), int(date_dash[5:7])
    return f"{y}S{(m + 2) // 3}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", default=None, help="6位代码")
    ap.add_argument("--name", default=None, help="票名(与 code 二选一)")
    ap.add_argument("--date", default=None, help="yyyymmdd, 缺省=最新 live-*")
    a = ap.parse_args()
    if not a.code and not a.name:
        sys.exit("要 --code 或 --name")

    live = (ROOT / "results" / "x" / f"live-{a.date}") if a.date else None
    if live is None or not live.exists():
        live = latest_live(a.code or a.name)
    if live is None:
        sys.exit("无任何链产物目录")
    date8 = live.name.split("-")[1]
    date_dash = f"{date8[:4]}-{date8[4:6]}-{date8[6:]}"
    keys = [k for k in (a.name, a.code) if k]

    print(f"# {('/'.join(keys))} @ {date_dash} 全链聚合(holdings_ask, 机械层)")

    # 1. 全链产物(results/<skill>_chain/live-<date>/0*.md)
    hit_chains = 0
    for f in sorted(live.parent.parent.glob(f"*/live-{date8}/0*.md")):
        skill = f.parents[1].name.replace("_chain", "")
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        got = []
        for i, l in enumerate(lines):
            if any(k in l for k in keys) and not l.strip().startswith("```"):
                ctx = lines[i - 1].strip()[:60] if i and lines[i - 1].strip() and not lines[i - 1].startswith("#") else ""
                got.append((l.strip()[:240], ctx))
        if got:
            hit_chains += 1
            print(f"\n## [{skill}] {f.name}")
            for text, ctx in got[:6]:
                print(f"- {text}" + (f"  ←上句: {ctx}" if ctx else ""))

    # 2. md 当日小节
    md = ROOT / "md" / quarter_of(date_dash) / f"{date_dash}.md"
    if md.exists():
        text = md.read_text(encoding="utf-8")
        m = re.search(rf"#### ([^\n]*{'|'.join(keys)}[^\n]*)", text)
        if m:
            seg = text[m.start():]
            nxt = re.search(r"\n#### ", seg[4:])
            seg = seg[:nxt.start() + 4] if nxt else seg[:3000]
            print(f"\n## md 当日小节 {m.group(1).strip()}")
            print("\n".join(seg.splitlines()[:20]))

    # 3. facts 快照行(当日 0915 槽)
    facts = ROOT / "scripts" / "dfcf" / "paper" / "facts" / date_dash / "0915" / "facts.md"
    if facts.exists():
        hits = [l.strip()[:240] for l in facts.read_text(encoding="utf-8").splitlines()
                if any(k in l for k in keys)]
        if hits:
            print(f"\n## facts 快照(0915)")
            print("\n".join(hits[:5]))

    # 4. paper plans 挂单行(当日全 A 线)
    n = 0
    for f in sorted((ROOT / "scripts" / "dfcf" / "paper" / "plans").glob(f"{date_dash}_A-*.md")):
        for l in f.read_text(encoding="utf-8").splitlines():
            if a.code and a.code in l and l.startswith("- "):
                print(f"- plans[{f.stem.split('_', 1)[1]}]: {l.strip()[:200]}")
                n += 1
    if n:
        print("(上行区=paper 各线对该票的当日挂单)")

    print(f"\n(命中 {hit_chains} 条链; 调用方据此做全链推导+挂单建议)")


if __name__ == "__main__":
    main()
