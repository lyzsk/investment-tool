# -*- coding: utf-8 -*-
"""asset_scan.py — 产物"谁读"自动扫描(10/20 晚用户: 关系图要标出"谁读", 很多产物没人读)

做法(静态, 零网络): 对 downloads/market/<最近交易日>/ 下每个产物、scripts/dfcf/paper/ 下每个产物目录 / 文件,
  拿文件名(去 .gz / 日期)在全项目代码(scripts/**/*.py|mjs|js, inv-*/**/*.java)里搜, 列出引用它的脚本;
  再看引用它的脚本里有没有"写"的迹象(write / dump / appendFile / open(... "w"/"a") / >>)判断哪个是生产者, 其余算读方。
  只有生产者引用、没有别的脚本引用 = "无人读"(只是静态引用, 动态拼路径的可能漏判, 结果供人复核)。
产物: docs/graph/asset_scan.json(给 paper_line_graph.py 画"未接入的数据"带) + 终端表
用法: scripts/venv/Scripts/python.exe -X utf8 docs/graph/asset_scan.py
"""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"
PAPER = ROOT / "scripts" / "dfcf" / "paper"
SKIP = {"__pycache__", "sandbox", "manifest.json", "README.md"}
WRITE = re.compile(r"write_text|writeFileSync|appendFileSync|json\.dump|\.write\(|open\([^)]*[\"'][wa]b?[\"']|createWriteStream|>>|saveBook|os\.replace|renameSync")


def code_files():
    out = []
    for pat in ("scripts/**/*.py", "scripts/**/*.mjs", "scripts/**/*.js", "inv-*/**/*.java"):
        out += [p for p in ROOT.glob(pat) if "venv" not in p.parts and "node_modules" not in p.parts and "temp" not in p.parts and "_graveyard" not in p.parts]
    return out


def main():
    days = sorted(p.name for p in MKT.iterdir() if re.fullmatch(r"\d{4}-\d\d-\d\d", p.name))
    D = days[-1]
    assets = {}
    for f in (MKT / D).iterdir():
        n = re.sub(r"\.gz$|\.tmp$", "", f.name)
        if n.startswith("DONE_") or n in SKIP:
            continue
        assets[n] = f"downloads/market/<日>/{n}"
    for f in PAPER.iterdir():
        if f.name in SKIP or f.name.startswith(("books.bak", ".")) or f.suffix in (".py", ".mjs", ".csv", ".tmp") or f.name.endswith(".csv.tmp"):
            continue
        assets[f.name] = f"scripts/dfcf/paper/{f.name}{'/' if f.is_dir() else ''}"
    files = code_files()
    texts = {}
    for p in files:
        try:
            texts[p] = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            pass
    res = []
    DECIDE = {"run_chain.py", "facts.mjs", "quality_hooks.py", "ctx_index.py", "mix_plans.py", "t_decide.py", "t_event.py", "open_live.py", "matcher.mjs", "snapshot.mjs", "ledger_limits.py", "attribution.py"}
    DYN = {"call_auction_open.jsonl": ["inv-stock(Java importAuction 入行情库 call_auction 表)"], "call_auction_close.jsonl": ["inv-stock(Java importAuction 入行情库)"],
           "call_auction_open_raw.jsonl": [], "call_auction_close_raw.jsonl": [], "auction_live_close.json": []}   # 文件名动态拼接, 静态搜不到: 人工核过
    for name, where in sorted(assets.items()):
        is_dir = where.endswith("/")
        pats = [f'"{name}"', f"'{name}'", f"/{name}/", f"/{name}\""] if is_dir else [name]
        refs = []
        for p, tx in texts.items():
            if not any(x in tx for x in pats):
                continue
            lines = [l for l in tx.splitlines() if any(x in l for x in pats)]
            refs.append({"script": p.relative_to(ROOT).as_posix(), "writes": any(WRITE.search(l) for l in lines)})
        stem = re.sub(r"\.(jsonl|json|md|html)$", "", name)
        own = lambda s: Path(s).stem in (stem, f"collect_{stem}", f"collect_{stem.split('_')[0]}", f"{stem}_db") or Path(s).stem.replace("collect_", "") in stem
        writers = [r["script"] for r in refs if r["writes"] or own(r["script"])]
        readers = [r["script"] for r in refs if r["script"] not in writers]
        mods = {Path(w).stem for w in writers}
        for m in mods:   # 生产者的模块被别处 import(如 ctx_index import topology)= 间接读方
            readers += [p.relative_to(ROOT).as_posix() for p, tx in texts.items() if p.relative_to(ROOT).as_posix() not in writers and re.search(rf"\bimport {m}\b|from {m} import|/{m}\.mjs", tx)]
        readers = sorted(set(readers)) + (DYN.get(name) or [])
        dec = [r for r in readers if Path(r).name in DECIDE]
        level = "无人读" if not readers else ("进决策" if dec else "只给报表/采集")
        res.append({"name": name, "where": where, "writers": writers, "readers": readers, "decision_readers": dec, "level": level})
    out = ROOT / "docs" / "graph" / "asset_scan.json"
    out.write_text(json.dumps({"date": D, "assets": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in sorted(res, key=lambda r: ("无人读", "只给报表/采集", "进决策").index(r["level"])):
        print(f"{r['level']:10s} {r['where']:52s} 写: {', '.join(Path(x).name for x in r['writers'][:2]) or '-'} | 决策读: {', '.join(Path(x).name for x in r['decision_readers'][:3]) or '-'} | 其他读: {len(r['readers']) - len(r['decision_readers'])}")
    from collections import Counter
    print(f"\n共 {len(res)} 个产物: {dict(Counter(r['level'] for r in res))} → {out}")


if __name__ == "__main__":
    main()
