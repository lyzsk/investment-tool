# -*- coding: utf-8 -*-
"""原 paper viewer 的统一 replay_viewer：继承原模板/BS画法，增加日期与公共情境。"""
import argparse
import json
import re
import sys
from pathlib import Path
from store import KnowledgeStore
from context_pack import get_context_pack

ROOT = Path(__file__).resolve().parents[2]
TPL = ROOT / "scripts" / "paper_line" / "viewer_tpl.html"


def knowledge_for(store, day):
    out = {}
    for c in store.all("context_snapshot"):
        if c["as_of"].startswith(day):
            out[c["subject"]] = get_context_pack(store, c["subject"], f"{day}T23:59:59", purpose="viewer", budget="full")
    return out


def consult_books(data, day, live_root=None):
    """按需咨询进入原账本导航；orders只是候选建议，不是成交。"""
    base = Path(live_root) if live_root else ROOT / "results" / "_live" / day / "consult"
    out = []
    if not base.exists():
        return out
    for sf in sorted(base.glob("*/*/fast.json")):
        slow = sf.with_name("slow.json")
        use = slow if slow.exists() else sf
        try:
            doc = json.loads(use.read_text(encoding="utf-8"))
            pack = json.loads(sf.with_name("pack.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        case, decision = doc["case"], doc["decision"]
        skill = case["action"]["skill"]
        orders = []
        for o in case["action"].get("orders") or []:
            if not o.get("price") or o.get("side") not in ("BUY", "SELL"):
                continue
            orders.append({"t": o.get("t") or pack["at"][11:19], "code": o.get("code") or pack["code"], "name": o.get("name") or pack.get("name"), "side": o["side"],
                           "px": o["price"], "qty": o.get("qty") or 0, "op": o.get("op") or "限价", "why": o.get("why") or decision["action"]})
        same = next((b for b in data.get("books") or [] if b.get("skill") == skill), None)
        versions = [{"dir": use.stem, "trig": pack["at"][11:19], "start": pack["at"], "why": pack["question"], "boot": use.stem == "fast",
                     "total": 0, "result": "ok", "usd": doc.get("cost_usd") or 0, "k3": 0, "steps": [], "files": {}, "orders": orders,
                     "view": decision["stance"], "stop": False, "sizes": {}}]
        out.append({"id": f"consult_{skill}_{sf.parent.name}", "name": f"按需咨询·{skill}", "mode": "consult", "kind": "candidate", "skill": skill,
                    "audit": [], "nav0": None, "nav1": None, "ret": None, "trades": [], "suggestions": orders, "positions": {}, "events": [],
                    "keep": [], "versions": versions, "mentor_day": (same or {}).get("mentor_day")})
    return out


def inject(data, all_days=None):
    html = TPL.read_text(encoding="utf-8")
    html = html.replace("/*__DATA__*/", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"), 1)
    html = html.replace("const DATA = JSON.parse", "let DATA = JSON.parse", 1)
    html = html.replace('<div class="wrap">', '<div class="card"><label>日期 <select id="daySelect"></select></label></div><div class="wrap">', 1)
    html = html.replace("function renderSummary(){", """function knowledgeCard(){
  const K=DATA.knowledge||{}, rows=Object.entries(K).map(([code,p])=>{
    const m=p.context.market||{}, t=p.context.theme||{}, f=p.forecast||{};
    return `<tr><td>${esc(code)}</td><td>${esc(m.cycle||'未标')}</td><td>${esc((t.zibei||[]).map(z=>z.py+':'+z.n).join(' / '))}</td><td>${p.cases.length}</td><td>${esc(f.n??'-')}</td></tr>`;
  }).join('');
  return `<div class="card"><h2>公共情境与跨skill证据（知识底座 v1）</h2>${rows ? `<table><tr><th>代码</th><th>市场周期</th><th>字辈</th><th>案例</th><th>预测样本</th></tr>${rows}</table>` : '该日期之前没有可用情境快照，不伪造。'}</div>`;
}
function renderSummary(){""", 1)
    html = html.replace("  ${multiCard()}", "  ${multiCard()}${knowledgeCard()}", 1)
    day_data = {k: v for k, v in (all_days or {data["date"]: data}).items() if k != data["date"]}
    html = html.replace("renderNav(); renderSummary();", """const DAY_DATA = __DAY_DATA__;
DAY_DATA[DATA.date] = DATA;
const daySelect = document.getElementById('daySelect');
daySelect.innerHTML = Object.keys(DAY_DATA).sort().map(x=>`<option value="${x}">${x}</option>`).join('');
daySelect.value = DATA.date;
daySelect.onchange = e => { DATA = DAY_DATA[e.target.value]; CUR = null; SHOW_USER = DATA.user.length > 0; document.getElementById('d').textContent = DATA.date; renderNav(); renderSummary(); };
renderNav(); renderSummary();""".replace("__DAY_DATA__", json.dumps(day_data, ensure_ascii=False).replace("</", "<\\/")), 1)
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-10-30")
    ap.add_argument("--dates", help="逗号分隔多个日期；单 HTML 内切换，默认只用 --date")
    ap.add_argument("--out", default=str(ROOT / "docs" / "private" / "replay_viewer.html"))
    a = ap.parse_args()
    days = sorted(set(x.strip() for x in a.dates.split(",") if x.strip())) if a.dates else [a.date]
    sys.path.insert(0, str(ROOT / "scripts" / "paper_line"))
    import viewer
    store = KnowledgeStore(ROOT / "downloads" / "ontology" / "ontology.db")
    all_days = {}
    try:
        for day in days:
            argv = sys.argv
            try:
                sys.argv = [str(ROOT / "scripts" / "paper_line" / "viewer.py"), "--date", day]
                viewer.main()  # 先让原 viewer 产出同一份 dark mode + BS 图数据，再注入公共情境
            finally:
                sys.argv = argv
            original = ROOT / "results" / "inv-stock" / "paper_line" / f"viewer_{day}.html"
            text = original.read_text(encoding="utf-8")
            m = re.search(r'<script id="data" type="application/json">([\s\S]*?)</script>', text)
            if not m:
                raise ValueError(f"原 viewer 缺 DATA: {original}")
            data = json.loads(m.group(1))
            data["knowledge"] = knowledge_for(store, day)
            data["books"] = list(data.get("books") or []) + consult_books(data, day)
            all_days[day] = data
    finally:
        store.close()
    current = all_days[a.date]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(inject(current, all_days), encoding="utf-8")
    print(f"→ {a.out} (继承原 viewer dark mode / 左侧菜单 / BS 画法；{len(all_days)} 天可切换；{len(current['knowledge'])} 个公共情境)")


if __name__ == "__main__":
    main()
