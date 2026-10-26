# -*- coding: utf-8 -*-
"""live_assets.py — 10b 素材消费盘点: 项目里攒的素材, 实盘线(live line)到底用没用(10/24 用户要; 10/25 定"真调回放跑的时候做"; 零 token, 只读)

素材 6 类:
  A 行情日产物   downloads/market/<日>/ 每个文件(去 .gz)
  B 其他下载     downloads/<目录>(market 以外; ontology 逐文件)
  C md 日记各节  md/<季>/<日>.md 的 ## / ### 标题
  D skill 文件   skills/<入选导师 / market-skill / telegraph-skill>/ 下的 .md / .json
  E 业务库表     investment_tool / investment_market 的表(information_schema, 只读)
  F 工具产物     scripts/paper_line/tools/*.py(必查 / 候选池 / 统计)
判定(按强到弱取第一个):
  进首跑材料  在盘前首跑消息 00_boot_msg.md 里出现(标题 / 文件名 / 表名)
  进触发消息  在盘中触发消息 00_trigger_msg.md / 01_facts.md 里出现
  代码在用    实盘线代码(入口 scripts/paper_line + scripts/live 的传递闭包)里引用 —— 进了某个机械判断 / 必查, 但原文不进消息
  ./q 可查    只有 q.py(模型自己查)引用
  没消费      以上都没有 → 进「未消费清单」
另: 回放会话记录里模型实际调了几次 ./q、查了什么(会话 = 各线 session.json 的 sid)
动态拼路径的引用可能漏判(静态搜文件名), 结论供人复核
产物: docs/graph/live_line_assets.html + docs/graph/live_line_assets.json
用法: scripts/venv/Scripts/python.exe -X utf8 docs/graph/live_assets.py [--replay results/_replay/2026-10-23/2026-10-23]
"""
import argparse
import collections
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "live")]
SKIPD = {"venv", "node_modules", "__pycache__", "temp", "_graveyard", "_archive"}


def code_files():
    out = {}
    for pat in ("scripts/**/*.py", "scripts/**/*.mjs", "scripts/**/*.js"):
        for p in ROOT.glob(pat):
            if not SKIPD & set(p.parts):
                try:
                    out[p] = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    pass
    return out


def live_closure(files):
    """入口 = scripts/paper_line/** + scripts/live/** ; 按模块名 / 文件名引用做传递闭包"""
    by_stem = collections.defaultdict(list)
    for p in files:
        by_stem[p.stem].append(p)
    pats = {s: re.compile(r"(?<![\w.])" + re.escape(s) + r"(?![\w])") for s in by_stem if len(s) > 3}
    reach = {p for p in files if "paper_line" in p.parts or ("live" in p.parts and "scripts" in p.parts)}
    front = list(reach)
    while front:
        t = files[front.pop()]
        for s, pt in pats.items():
            if any(q not in reach for q in by_stem[s]) and pt.search(t):
                for q in by_stem[s]:
                    if q not in reach:
                        reach.add(q)
                        front.append(q)
    return reach


def db_tables():
    try:
        import plan_review as PR
        c = PR.db().cursor()
        c.execute("select table_schema, table_name, table_rows from information_schema.tables where table_schema in ('investment_tool','investment_market')")
        return [(a, b, r) for a, b, r in c.fetchall()]
    except Exception as e:   # noqa: BLE001
        print("读表清单失败:", e)
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", default="results/_replay/2026-10-23/2026-10-23")
    a = ap.parse_args()
    rp = ROOT / a.replay
    D = rp.name
    boot, trig = "", ""
    lines = sorted(rp.glob("live_*"))
    for ld in lines:
        for f in ld.glob("versions/*/00_boot_msg.md"):
            boot += f.read_text(encoding="utf-8", errors="ignore")
        for f in list(ld.glob("versions/*/00_trigger_msg.md")) + list(ld.glob("versions/*/01_facts.md")):
            trig += f.read_text(encoding="utf-8", errors="ignore")
    files = code_files()
    reach = live_closure(files)
    q_txt = files.get(ROOT / "scripts" / "paper_line" / "q.py", "")
    live_code = {p: t for p, t in files.items() if p in reach}

    def judge(keys, code_keys=()):
        """keys: 消息 + 代码里都搜; code_keys: 只在代码 / q.py 里搜(文件名太常见, 消息里提一句不算进了材料)"""
        keys = [k for k in keys if k and len(k) >= 3]
        for k in keys:
            if k in boot:
                return "进首跑材料", k
        for k in keys:
            if k in trig:
                return "进触发消息", k
        for k in [*keys, *code_keys]:
            hit = [p for p, t in live_code.items() if k in t and p.name != "q.py"]
            if hit:
                return "代码在用", ", ".join(sorted({str(p.relative_to(ROOT)).replace(chr(92), "/") for p in hit})[:3])
        for k in [*keys, *code_keys]:
            if k in q_txt:
                return "./q 可查", "q.py"
        return "没消费", ""

    A = []
    mk = ROOT / "downloads" / "market" / D
    for f in sorted(mk.iterdir()) if mk.exists() else []:
        n = re.sub(r"\.gz$", "", f.name)
        if n.startswith("DONE_") or n == "manifest.json":
            continue
        A.append(("A 行情日产物", f"downloads/market/<日>/{n}", *judge([n, Path(n).stem])))
    for d in sorted((ROOT / "downloads").iterdir()):
        if not d.is_dir() or d.name in ("market",):
            continue
        if d.name == "ontology":
            for f in sorted(d.iterdir()):
                A.append(("B 其他下载", f"downloads/ontology/{f.name}", *judge([f.name, f.stem])))
        else:
            A.append(("B 其他下载", f"downloads/{d.name}/", *judge([f"downloads/{d.name}", f'"{d.name}"', f"'{d.name}'"])))
    mdf = ROOT / "md" / f"{D[:4]}S{(int(D[5:7]) - 1) // 3 + 1}" / f"{D}.md"
    seen, top = set(), ""
    for l in (mdf.read_text(encoding="utf-8").splitlines() if mdf.exists() else []):
        m = re.match(r"^(##+) (.+)$", l)
        if not m or m.group(1) not in ("##", "###"):
            continue
        if m.group(1) == "##":
            top = m.group(2)
        elif top in ("涨停分析", "午间涨停分析"):
            continue   # 题材小节每天不一样, 按"涨停分析"整节算(盘前首跑带的是前一交易日的整节)
        if m.group(2) not in seen:
            seen.add(m.group(2))
            A.append(("C md 日记各节", f"{m.group(1)} {m.group(2)}", *judge([l])))
    sel = {}
    try:
        sel = json.loads((ROOT / "results" / "_live" / "2026-10-26" / "selected_mentors.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    sk = [f"{s}-skill" for s in (sel.get("premarket") or [])] + ["market-skill", "telegraph-skill"]
    for s in sk:
        for f in sorted((ROOT / "skills" / s).rglob("*")):
            if f.is_file() and f.suffix in (".md", ".json") and "case_log" not in f.parts:
                rel = str(f.relative_to(ROOT / "skills")).replace(chr(92), "/")
                st, ev = judge([f.name if f.name not in ("SKILL.md", "rules.md", "cases.md", "profile.md") else f"skill · {f.name}", rel])
                if st == "没消费":
                    st, ev = judge([rel, f"{s}/persona/{f.name}"], code_keys=[f'"{f.name}"', f"'{f.name}'", f.name])
                A.append(("D skill 文件", rel, st, ev))
    for f in sorted((ROOT / "scripts" / "paper_line" / "tools").glob("*.py")):
        A.append(("F 工具", f"paper_line/tools/{f.name}", *judge([f.stem])))
    for sch, t, rows in sorted(db_tables()):
        if t.startswith(("sys_", "qrtz_", "gen_", "flyway")):
            continue
        A.append(("E 业务库表", f"{sch}.{t}(约 {rows or 0} 行)", *judge([t])))
    # 模型实际 ./q 调用
    qcalls = collections.Counter()
    for ld in lines:
        try:
            ss = json.loads((ld / "session.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sids = [ss.get("sid")] + [t.get("fork") for t in ss.get("turns") or [] if t.get("fork")]
        for sid in filter(None, sids):
            for tf in (Path.home() / ".claude" / "projects").glob(f"*/{sid}.jsonl"):
                for l in tf.read_text(encoding="utf-8", errors="ignore").splitlines():
                    try:
                        j = json.loads(l)
                    except ValueError:
                        continue
                    if j.get("type") != "assistant":
                        continue
                    for c in (j.get("message") or {}).get("content") or []:
                        if isinstance(c, dict) and c.get("type") == "tool_use":   # 只认模型真发出的工具调用(工具定义里的名字不算)
                            inp = c.get("input") or {}
                            cmd = str(inp.get("command") or "")
                            w = ("./q " + (cmd.split()[1] if len(cmd.split()) > 1 else "?")) if cmd.startswith("./q") else f"{c.get('name')} {Path(str(inp.get('file_path') or inp.get('pattern') or '')).name}"
                            qcalls[(ld.name, w)] += 1
    out = {"replay": a.replay, "assets": [{"kind": k, "name": n, "status": s, "evidence": e} for k, n, s, e in A],
           "q_calls": [{"line": a_, "what": b, "n": n} for (a_, b), n in qcalls.most_common()]}
    (ROOT / "docs" / "graph" / "live_line_assets.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    cnt = collections.Counter((k, s) for k, _, s, _ in A)
    kinds = sorted({k for k, *_ in A})
    STS = ["进首跑材料", "进触发消息", "代码在用", "./q 可查", "没消费"]
    col = {"进首跑材料": "#1f3a26", "进触发消息": "#1d3140", "代码在用": "#3a3420", "./q 可查": "#2f2640", "没消费": "#4a2226"}
    H = ["<!doctype html><meta charset='utf-8'><title>实盘线素材消费盘点</title>",
         "<style>body{font:14px -apple-system,'Microsoft YaHei',sans-serif;margin:24px;max-width:1200px;background:#15171c;color:#d7dae0}"   # 10/25 用户: html 一律 dark mode
         "h1,h2,h3{color:#e8eaee}table{border-collapse:collapse;margin:8px 0 24px}td,th{border:1px solid #3a3f4b;padding:4px 8px;vertical-align:top}"
         "th{background:#232731}code{font-size:12px;color:#9fb4d8}a{color:#7fb0ff}</style>",
         f"<h1>实盘线素材消费盘点</h1><p>依据: 回放 <code>{html.escape(a.replay)}</code> 的盘前首跑 / 触发消息 + 实盘线代码(scripts/paper_line + scripts/live 的传递闭包, {len(reach)} 个文件)。"
         "静态搜文件名 / 表名 / 标题, 动态拼路径的可能漏判。生成脚本 <code>docs/graph/live_assets.py</code>。</p>",
         "<h2>总览</h2><table><tr><th>类</th>" + "".join(f"<th style='background:{col[s]}'>{s}</th>" for s in STS) + "</tr>"]
    for k in kinds:
        H.append(f"<tr><td>{k}</td>" + "".join(f"<td>{cnt[(k, s)] or ''}</td>" for s in STS) + "</tr>")
    H.append("</table>")
    H.append("<h2>未消费清单(没进消息、实盘线代码不用、./q 也查不到)</h2><table><tr><th>类</th><th>素材</th></tr>")
    for k, n, s, e in A:
        if s == "没消费":
            H.append(f"<tr><td>{k}</td><td>{html.escape(n)}</td></tr>")
    H.append("</table><h2>模型实际查了什么(回放会话里的 ./q / Read / Grep 调用)</h2><table><tr><th>线</th><th>调用</th><th>次数</th></tr>")
    for (l_, w), n in qcalls.most_common():
        H.append(f"<tr><td>{l_}</td><td>{html.escape(w)}</td><td>{n}</td></tr>")
    if not qcalls:
        H.append("<tr><td colspan=3>回放会话里没有一次 ./q / Read / Grep 调用</td></tr>")
    H.append("</table><h2>全部素材</h2>")
    for k in kinds:
        H.append(f"<h3>{k}</h3><table><tr><th>素材</th><th>状态</th><th>证据</th></tr>")
        for k2, n, s, e in A:
            if k2 == k:
                H.append(f"<tr><td>{html.escape(n)}</td><td style='background:{col[s]}'>{s}</td><td><code>{html.escape(e)[:200]}</code></td></tr>")
        H.append("</table>")
    (ROOT / "docs" / "graph" / "live_line_assets.html").write_text("\n".join(H), encoding="utf-8")
    for k in kinds:
        print(k, {s: cnt[(k, s)] for s in STS if cnt[(k, s)]})
    print("./q 调用:", sum(qcalls.values()), dict(qcalls.most_common(8)))


if __name__ == "__main__":
    main()
