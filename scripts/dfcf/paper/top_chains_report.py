# -*- coding: utf-8 -*-
"""top_chains_report.py — paper 总收益前 N 条链的逐日交易/挂单/理由明细(零 token, 10/16 用户令: "呈现给我看看我研究一下")
数据: books/A-*.json(orders/trades/nav) + results/<skill>_chain/live-<日>/slots/<slot>/04_plan.md 的 contract(候选理由 why/conf/pos) + names.json
输出: scripts/dfcf/paper/reports/top<N>_<日>.md
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/top_chains_report.py [--top 5] [--from 2026-10-08]
"""
import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
P = ROOT / "scripts" / "dfcf" / "paper"
SKILL = {"A-cb": "buchitudou0"}
STATUS = {"filled": "✅成交", "void": "作废(未触发)", "cxl": "撤单(被新单取代)", "invalid": "失效(条件触发撤)", "reject": "拒单", "open": "挂着"}


def contract(f):
    try:
        t = f.read_text(encoding="utf-8")
        m = re.findall(r"```contract\s*\n(.*?)```", t, re.S)
        return json.loads(m[-1]) if m else {}
    except Exception:  # noqa: BLE001
        return {}


def why04(skill, day, slot):
    d8 = day.replace("-", "")
    rd = ROOT / "results" / f"{skill}_chain" / f"live-{d8}"
    for f in (rd / "slots" / slot / "04_plan.md", rd / "04_plan.md"):
        c = contract(f)
        if c.get("candidates"):
            return {str(x.get("code")): x for x in c["candidates"] if x.get("code")}
    return {}


def market_state(skill, day):
    rd = ROOT / "results" / f"{skill}_chain" / f"live-{day.replace('-', '')}"
    for f in (rd / "slots" / "0915" / "02_analysis.md", rd / "02_analysis.md"):
        c = contract(f)
        if c:
            return f"{c.get('market_state', '?')} / 态度 {c.get('stance', '?')} / 方向 {'、'.join(map(str, c.get('directions', [])))[:80]}"
    return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--from", dest="frm", default="2026-10-08")
    a = ap.parse_args()
    names = json.loads((P / "names.json").read_text(encoding="utf-8")) if (P / "names.json").exists() else {}
    acc = {x[0]: x[1] for x in json.loads("[]")}
    try:
        from_js = (P / "accounts.mjs").read_text(encoding="utf-8")
        acc = dict(re.findall(r'\["(A-[^"]+)", "([^"]+)"', from_js))
    except Exception:  # noqa: BLE001
        pass
    books = []
    for f in P.glob("books/A-*.json"):
        b = json.loads(f.read_text(encoding="utf-8"))
        nav = [n for n in b.get("nav", []) if n["date"] >= a.frm]
        if nav:
            books.append((nav[-1]["nav"] / 100000 - 1, f.stem, b, nav))
    books.sort(reverse=True)
    last = max(n[-1]["date"] for *_, n in books)
    L = [f"# paper 总收益前 {a.top} 名: 逐日交易/挂单/理由(截至 {last}, 实盘 10/8 起各 10 万)", "",
         "> 读法: 每条链先看逐日净值, 再看每天的挂单表——时间=挂单时段(09:15=盘前全链, 其余=盘中子链), 状态=最终结局, 理由=链终裁 note(触发/失效条件) + 04 候选理由(why)。止损/保护线卖出在「成交」表里, 理由=哨兵原因。",
         "> antoo/芷影攫心 的 10/8~10/14 是 10/15 补跑回放(as-of), 不是实盘; 10/16 起导师链换成各自框架(方案 A), 本表都是旧框架时期。", "",
         "## 总排名", "| 名次 | 账户 | 累计 | 挂单数 | 成交数 |", "|---|---|---|---|---|"]
    for i, (r, src, b, nav) in enumerate(books, 1):
        L.append(f"| {i} | {acc.get(src, src)} | {r * 100:+.2f}% | {sum(1 for o in b['orders'] if o.get('date', '') >= a.frm)} | {sum(1 for t in b.get('trades', []) if str(t['id'])[:10] >= a.frm)} |")
    for r, src, b, nav in books[:a.top]:
        skill = SKILL.get(src, src[2:])
        L += ["", f"## {acc.get(src, src)}({src}) 累计 {r * 100:+.2f}%", "", "**逐日净值**: " + " → ".join(
            f"{n['date'][5:]} {n['nav']:.0f}({(n['nav'] / (nav[i - 1]['nav'] if i else 100000) - 1) * 100:+.2f}%)" for i, n in enumerate(nav))]
        days = sorted({o["date"] for o in b["orders"] if o.get("date", "") >= a.frm} | {str(t["id"])[:10] for t in b.get("trades", []) if str(t["id"])[:10] >= a.frm})
        for d in days:
            L += ["", f"### {d}  市况: {market_state(skill, d)}", "",
                  "| 时间 | 方向 | 票 | 挂价 | 数量 | 结局 | 成交 | 链终裁理由(note) | 04 候选理由 |", "|---|---|---|---|---|---|---|---|---|"]
            w04 = {}
            for o in sorted([o for o in b["orders"] if o.get("date") == d], key=lambda o: (o.get("time", ""), o["id"])):
                slot = o.get("time", "09:15").replace(":", "")
                if slot not in w04:
                    w04[slot] = why04(skill, d, slot)
                c = w04[slot].get(str(o["code"]), {})
                why = (c.get("why") or "") + (f" [置信 {c['conf']}]" if c.get("conf") else "")
                nm = names.get(o["code"], "")
                note = re.sub(r"\s*\|\s*10/11 重建重放.*$", "", str(o.get("note", ""))).replace("|", "/")[:160]
                fill = f"{o.get('fillPrice')} {o.get('fillWhy', '')}"[:40] if o.get("status") == "filled" else (o.get("voidWhy") or o.get("why") or "")[:40]
                L.append(f"| {o.get('time', '')} | {'买' if o['side'] == 'BUY' else '卖' if o['side'] == 'SELL' else o['side']} | {nm}({o['code']}) | {o.get('price')} | {o.get('qty')} | "
                         f"{STATUS.get(o.get('status'), o.get('status'))} | {fill.replace('|', '/')} | {note} | {why.replace('|', '/')[:120]} |")
            tr = [t for t in b.get("trades", []) if str(t["id"])[:10] == d]
            if tr:
                L += ["", "成交(含哨兵止损): " + "; ".join(f"{'买' if t['side'] == 'BUY' else '卖'} {names.get(t['code'], t['code'])} {t['qty']}@{t['price']}({str(t.get('why', ''))[:30]})" for t in tr)]
    out = P / "reports" / f"top{a.top}_{last}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
