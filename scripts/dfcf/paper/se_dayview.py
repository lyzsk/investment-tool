# -*- coding: utf-8 -*-
"""se_dayview.py — 把 se_dayreplay.py(主回放) + se_dayinject.py(注入演示) + 当天实际执行器(results/_live, 只读)画成一个自包含 HTML(无外网; 图 = 内联 SVG)

内容: 顶部汇总 · 全天总览(回放链 / 实际执行器 / 事件) · 主时间轴(每个事件一行, 触发行带 触发→00 事实包→01→02→03多∥03空→04→05→06→生效 甘特条, 点开看数据来源 /
      01 全文 / 02~06 原文与 JSON / 校验剔除 / token 美元) · 净值曲线(回放 vs 实际执行器 vs 上证, 成交点) · 实际执行器对照 · 成交明细 · 注入演示 · 情况清单
用法: python se_dayview.py --dir results/inv-stock/paper/day_replay/2026-10-21/meiyuelu
"""
import argparse
import csv
import html
import json
import re
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LIMIT_S = 180
# 类别色(dataviz 参考调色板, 固定顺序): 甘特 8 段
STEPS = [("00", "00 事实包", "#2a78d6"), ("01", "01 事实", "#eb6834"), ("02_market", "02 市况", "#1baf7a"), ("03_bull", "03 多", "#eda100"),
         ("03_bear", "03 空", "#e87ba4"), ("04_pick", "04 选票", "#008300"), ("05_risk", "05 风控", "#6250d6"), ("06_final", "06 终裁", "#e34948")]
SCOL = {k: c for k, _, c in STEPS}
SNAME = {k: n for k, n, _ in STEPS}
SER = {"replay": "#2a78d6", "actual": "#eb6834", "sh": "#1baf7a"}
TRIG = {"首版", "补丁后重跑", "成交后必跑", "竞价成交后必跑", "出区间", "翻转", "指数事件", "心跳", "失败重试", "手动", "排队补跑", "续跑补叫"}


def esc(x):
    return html.escape(str(x if x is not None else ""))


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def rd(p):
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def jsonl(p):
    out = []
    for l in (rd(p) or "").splitlines():
        try:
            out.append(json.loads(l))
        except ValueError:
            pass
    return out


def hs(t):
    t = str(t)
    if len(t) == 5:
        t += ":00"
    h, m, s = (int(x) for x in t[:8].split(":"))
    return h * 3600 + m * 60 + s


def sh(x):
    x = int(round(x))
    return f"{x // 3600:02d}:{x % 3600 // 60:02d}:{x % 60:02d}"


def xmin(t):
    """交易时间轴(分钟, 午休压缩): 09:15 = 0, 11:30 = 135, 13:00 = 135, 15:00 = 255"""
    s = hs(t) / 60
    if s <= 11 * 60 + 30:
        return max(0.0, s - (9 * 60 + 15))
    if s < 13 * 60:
        return 135.0
    return min(255.0, 135 + (s - 13 * 60))


# ---------------- 读数据 ----------------
def load_dir(d):
    S = jl(d / "summary.json", {}) or {}
    ev = jsonl(d / "events.jsonl")
    acts = jsonl(d / "actions.jsonl")
    curve = []
    for l in (rd(d / "curve.csv") or "").splitlines()[1:]:
        x = l.split(",")
        try:
            curve.append({"t": x[0], "nav": float(x[1]), "ret": float(x[2]), "sh": float(x[4]) if x[4] else None})
        except (IndexError, ValueError):
            pass
    runs = {r["id"]: r for r in S.get("runs") or []}
    for rid, r in runs.items():
        rr = d / rid
        r["timing"] = jl(rr / "timing.json", {}) or {}
        cj = jl(rr / "calls.json", {}) or {}
        r["calls"], r["plan"] = cj.get("calls") or [], cj.get("plan") or {}
        r["sources"] = jl(rr / "sources.json", []) or []
        r["checked"] = jl(rr / "strategy_checked.json", None)
    return S, ev, acts, curve, runs


def load_actual(D, skill):
    """10/21 实际执行器(单次 claude -p 版, results/_live 只读) + 成本日志 / 账号日志里的起止时刻"""
    base = ROOT / "results" / "_live" / D / f"se_{skill}"
    ev = jsonl(base / "events.jsonl")
    acts = jsonl(base / "actions.jsonl")
    stj = jl(base / "state.json", {}) or {}
    curve = []
    for l in (rd(base / "curve.csv") or "").splitlines()[1:]:
        x = l.split(",")
        try:
            curve.append({"t": x[0], "nav": float(x[1]), "ret": float(x[3])})
        except (IndexError, ValueError):
            pass
    strat = []
    for f in sorted((base / "strategies").glob("*.json")):
        j = jl(f, {}) or {}
        strat.append({"file": f.name, "why": j.get("why"), "usd": j.get("cost_usd"), "strategy": j.get("strategy"), "dropped": j.get("dropped"), "fired": j.get("fired")})
    cost = []
    try:
        with (ROOT / "scripts" / "lib" / "claude_cost.csv").open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("tag") == f"se-{skill}" and r.get("ts", "").startswith(D) and r["ts"][11:] >= "09:00":
                    cost.append(r)
    except OSError:
        pass
    prof = []
    for l in (rd(ROOT / "scripts" / "claude_profile" / "profile_log.csv") or "").splitlines():
        x = l.split(",")
        if len(x) >= 3 and x[0].startswith(D) and x[2].strip() == f"se-{skill}" and x[0][11:] >= "09:00":
            prof.append(x[0][11:19])
    trig = [e for e in ev if e.get("kind") == "重定"]
    runs, ci, si = [], 0, 0
    for e in trig:
        c = next((r for r in cost[ci:] if r["ts"][11:19] >= e["t"]), None)
        if c:
            ci = cost.index(c) + 1
        p0 = next((p for p in prof if p >= e["t"]), None)
        end = c["ts"][11:19] if c else None
        ok = bool(c and c.get("ok") == "1")
        s = strat[si] if ok and si < len(strat) else None
        si += 1 if ok else 0
        runs.append({"trig": e["t"], "why": e.get("why"), "n": e.get("n"), "claude_start": p0, "end": end, "claude_s": float(c["duration_s"]) if c else None,
                     "total": (hs(end) - hs(e["t"])) if end else None, "usd": float(c["cost_usd"] or 0) if c else None, "ok": ok,
                     "err": (c.get("errors") or "")[:200] if c else "无记录", "strategy": s})
    S = {"base": str(base.relative_to(ROOT)).replace("\\", "/"), "events": ev, "acts": acts, "curve": curve, "strategies": strat, "runs": runs,
         "start": stj.get("start") or {}, "summary": (rd(base / "summary.md") or "").strip(), "end_ret": curve[-1]["ret"] if curve else None,
         "restarts": [e for e in ev if e.get("kind") == "续跑恢复"], "kicks": [e for e in trig if str(e.get("why", "")).startswith("手动")],
         "fails": [r for r in runs if not r["ok"]]}
    return S


def load_inject(d):
    out = []
    for sd in sorted((d / "inject").glob("s*/")):
        meta = jl(sd / "scenario.json", {}) or {}
        S, ev, acts, curve, runs = load_dir(sd)
        out.append({"dir": sd, "meta": meta, "S": S, "ev": ev, "acts": acts, "runs": runs})
    return out


# ---------------- 甘特 ----------------
def gantt(r, k=1.6):
    """0 = 触发; 00 事实包等待 → 01 脚本 → 各 API 步(墙钟 / 虚拟时钟) → 竖线 = 生效; 红虚线 = 180 秒"""
    fw = float(r.get("facts_wait") or 0)
    dur = float(r.get("dur") or fw)
    W = int(max(LIMIT_S + 30, dur + 60) * k) + 20
    H = 58
    s01 = float(((r.get("timing") or {}).get("steps") or {}).get("01", {}).get("secs") or (0.8 if r.get("chain_dur") else 0))
    segs = [("00", 0, fw, True, r.get("facts_note") or "")]
    if r.get("chain_dur") is not None:
        segs.append(("01", fw, fw + s01, not r.get("err"), "脚本备料" + (f"(抛异常: {r.get('err')})" if r.get("err") else "")))
    for c in r.get("calls") or []:
        segs.append((c["step"], fw + c["t0"], fw + c["t1"], c["ok"], c.get("err") or ""))
    lane = {"00": 0, "01": 0, "02_market": 0, "03_bull": 0, "03_bear": 1, "04_pick": 0, "05_risk": 0, "06_final": 0}
    o = [f'<svg class="gantt" width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img">']
    o.append(f'<line x1="{LIMIT_S * k}" y1="0" x2="{LIMIT_S * k}" y2="{H - 12}" stroke="#d93025" stroke-dasharray="3,2"/>'
             f'<text x="{LIMIT_S * k + 2}" y="{H - 2}" font-size="9" fill="#52514e">180s</text>')
    for step, a, b, ok, note in segs:
        y = 4 + lane.get(step, 0) * 18
        w = max(2.0, (b - a) * k)
        o.append(f'<rect x="{a * k:.1f}" y="{y}" width="{w:.1f}" height="15" rx="2" fill="{SCOL.get(step, "#777")}" opacity="{1 if ok else 0.35}" '
                 f'stroke="{"#fcfcfb" if ok else "#b31412"}" stroke-width="{1 if ok else 1.6}"><title>{esc(SNAME.get(step, step))}: {a:.1f}→{b:.1f}s = {b - a:.1f}s'
                 f'{"" if ok else " 失败/超时"} {esc(note)[:160]}</title></rect>')
        lab = f"{SNAME.get(step, step).split()[0]}{'多' if step == '03_bull' else '空' if step == '03_bear' else ''} {b - a:.0f}s"
        if w > 36:
            o.append(f'<text x="{a * k + 2:.1f}" y="{y + 11}" font-size="9" fill="#fff">{esc(lab)}</text>')
    if r.get("skip05"):
        x = max((fw + c["t1"] for c in r.get("calls") or [] if c["step"] == "04_pick"), default=0) * k
        o.append(f'<text x="{x + 2:.1f}" y="{H - 14}" font-size="9" fill="#52514e">05 跳过</text>')
    red = dur >= LIMIT_S
    col = "#b31412" if red else "#0b0b0b"
    o.append(f'<line x1="{dur * k:.1f}" y1="0" x2="{dur * k:.1f}" y2="{H - 12}" stroke="{col}" stroke-width="2"/>'
             f'<text x="{dur * k + 4:.1f}" y="14" font-size="11" font-weight="bold" fill="{col}">{dur:.0f}s{" ≥180" if red else ""}</text>'
             f'<text x="{dur * k + 4:.1f}" y="28" font-size="9" fill="#52514e">{"生效 " + r["applied"] if r.get("applied") else "未生效"}</text>')
    o.append("</svg>")
    return "".join(o)


def overview(ev, runs, actual):
    W, L, H = 1120, 70, 150
    k = (W - L - 20) / 255

    def X(t):
        return L + xmin(t) * k
    o = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">']
    for t in ("09:15", "09:30", "10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "14:57"):
        x = X(t)
        o.append(f'<line x1="{x:.1f}" y1="14" x2="{x:.1f}" y2="{H - 16}" stroke="#e6e5e0"/><text x="{x:.1f}" y="{H - 4}" font-size="9" text-anchor="middle" fill="#52514e">{t if t != "11:30" else "11:30|13:00"}</text>')
    o.append(f'<text x="2" y="36" font-size="10" fill="#52514e">回放链</text><text x="2" y="72" font-size="10" fill="#52514e">实际执行器</text><text x="2" y="110" font-size="10" fill="#52514e">事件</text>')
    for r in runs.values():
        if r.get("chain_dur") is None:
            continue
        a, b = X(r["trig"]), X(sh(hs(r["trig"]) + r["dur"]))
        bad = not r.get("applied")
        o.append(f'<rect x="{a:.1f}" y="24" width="{max(2.5, b - a):.1f}" height="18" rx="2" fill="{SER["replay"]}" opacity="{0.4 if bad else 0.9}" stroke="{"#b31412" if bad or r["dur"] >= LIMIT_S else "none"}">'
                 f'<title>{esc(r["id"])} {esc(r["kind"])} 触发 {esc(r["trig"])} 耗时 {r["dur"]:.0f}s {esc(r.get("result"))}</title></rect>')
    for r in actual.get("runs") or []:
        if not r.get("end"):
            continue
        a, b = X(r["trig"]), X(r["end"])
        o.append(f'<rect x="{a:.1f}" y="60" width="{max(2.5, b - a):.1f}" height="18" rx="2" fill="{SER["actual"]}" opacity="{0.9 if r["ok"] else 0.4}" stroke="{"#b31412" if not r["ok"] else "none"}">'
                 f'<title>实际执行器 触发 {esc(r["trig"])} → {esc(r["end"])}({r["total"]}s) {esc(r["why"])[:80]} {"" if r["ok"] else "失败 " + esc(r["err"])}</title></rect>')
    for e in actual.get("restarts") or []:
        x = X(e["t"])
        o.append(f'<path d="M{x - 4:.1f},84 L{x + 4:.1f},84 L{x:.1f},92 Z" fill="#0b0b0b"><title>实际执行器 {esc(e["t"])} 进程重启 → 续跑恢复</title></path>')
    for e in ev:
        x = X(e["t"])
        trig = e["kind"] in TRIG
        o.append(f'<circle cx="{x:.1f}" cy="{106 if trig else 118}" r="{4 if trig else 2.5}" fill="{SER["replay"] if trig else "#898781"}"><title>{esc(e["t"])} {esc(e["kind"])} {esc(e.get("why"))[:120]}</title></circle>')
    o.append("</svg>")
    return "".join(o)


def curve_svg(curve, acts, actual):
    W, H, L, R, T, B = 1120, 320, 56, 20, 26, 30
    if not curve:
        return "<p>无曲线</p>"
    ac = actual.get("curve") or []
    ys = [c["ret"] for c in curve] + [c["sh"] for c in curve if c["sh"] is not None] + [c["ret"] for c in ac] + [0.0]
    lo, hi = min(ys), max(ys)
    pad = max(0.1, (hi - lo) * 0.12)
    lo, hi = lo - pad, hi + pad
    kx = (W - L - R) / 255

    def X(t):
        return L + xmin(t) * kx

    def Y(v):
        return T + (hi - v) / (hi - lo) * (H - T - B)
    o = [f'<svg id="curve" width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">']
    step = 0.1 if hi - lo < 1.2 else 0.25 if hi - lo < 3 else 0.5 if hi - lo < 6 else 1.0
    v = int(lo / step) * step
    while v <= hi:
        o.append(f'<line x1="{L}" y1="{Y(v):.1f}" x2="{W - R}" y2="{Y(v):.1f}" stroke="#eeede8"/>'
                 f'<text x="{L - 4}" y="{Y(v) + 3:.1f}" font-size="9" text-anchor="end" fill="#52514e">{v:+.2f}%</text>')
        v += step
    for t in ("09:30", "10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00"):
        o.append(f'<text x="{X(t):.1f}" y="{H - 10}" font-size="9" text-anchor="middle" fill="#52514e">{t if t != "11:30" else "11:30|13:00"}</text>')
    o.append(f'<line x1="{L}" y1="{Y(0):.1f}" x2="{W - R}" y2="{Y(0):.1f}" stroke="#898781" stroke-width="1.2" stroke-dasharray="5,3"/>')

    def line(pts, col):
        if len(pts) < 2:
            return ""
        return f'<polyline fill="none" stroke="{col}" stroke-width="2" stroke-linejoin="round" points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}"/>'
    o.append(line([(X(c["t"]), Y(c["sh"])) for c in curve if c["sh"] is not None], SER["sh"]))
    o.append(line([(X(c["t"]), Y(c["ret"])) for c in ac if "09:30" <= c["t"][:5] <= "15:00"], SER["actual"]))
    o.append(line([(X(c["t"]), Y(c["ret"])) for c in curve], SER["replay"]))

    def marker(a, cv, col, who):
        near = min(cv, key=lambda c: abs(hs(c["t"]) - hs(a["t"]))) if cv else {"ret": 0}
        x, y = X(a["t"]), Y(near["ret"])
        buy = a["side"] == "BUY"
        pts = f"{x:.1f},{y - 6:.1f} {x - 5:.1f},{y - 15:.1f} {x + 5:.1f},{y - 15:.1f}" if buy else f"{x:.1f},{y + 6:.1f} {x - 5:.1f},{y + 15:.1f} {x + 5:.1f},{y + 15:.1f}"
        return (f'<polygon points="{pts}" fill="{col}" stroke="#fcfcfb" stroke-width="1.5"><title>{who} {esc(a["t"])} {"买" if buy else "卖"} {esc(a.get("name") or "")}{esc(a["code"])} {a["qty"]}@{a["px"]}</title></polygon>'
                f'<text x="{x:.1f}" y="{(y - 18) if buy else (y + 25):.1f}" font-size="9" text-anchor="middle" fill="#0b0b0b">{"B" if buy else "S"}</text>')
    for a in acts:
        o.append(marker(a, curve, SER["replay"], "回放"))
    for a in actual.get("acts") or []:
        o.append(marker(a, ac, SER["actual"], "实际执行器"))
    o.append(f'<rect x="{L + 8}" y="6" width="14" height="3" fill="{SER["replay"]}"/><text x="{L + 26}" y="11" font-size="10" fill="#0b0b0b">回放(10 万空仓起步)</text>'
             f'<rect x="{L + 150}" y="6" width="14" height="3" fill="{SER["actual"]}"/><text x="{L + 168}" y="11" font-size="10" fill="#0b0b0b">10/21 实际执行器(旧账本起点, 收益%)</text>'
             f'<rect x="{L + 370}" y="6" width="14" height="3" fill="{SER["sh"]}"/><text x="{L + 388}" y="11" font-size="10" fill="#0b0b0b">上证(相对昨收)</text>'
             f'<line x1="{L + 480}" y1="8" x2="{L + 494}" y2="8" stroke="#898781" stroke-dasharray="5,3"/><text x="{L + 498}" y="11" font-size="10" fill="#0b0b0b">不操作 0%</text>'
             f'<text x="{L + 560}" y="11" font-size="10" fill="#52514e">▲B 买 ▼S 卖(颜色 = 哪条线的成交)</text>')
    o.append(f'<line id="xh" x1="0" y1="{T}" x2="0" y2="{H - B}" stroke="#52514e" stroke-width="1" visibility="hidden"/>')
    o.append("</svg>")
    data = {"L": L, "kx": kx, "rows": [[round(X(c["t"]), 1), c["t"][:5], c["ret"], c["sh"]] for c in curve],
            "act": [[round(X(c["t"]), 1), c["ret"]] for c in ac if "09:30" <= c["t"][:5] <= "15:00"]}
    o.append(f"<div id='tip' class='tip'></div><script>window.CURVE={json.dumps(data)};</script>")
    return "".join(o)


JS = """
(function(){var s=document.getElementById('curve'),tip=document.getElementById('tip'),xh=document.getElementById('xh');if(!s||!window.CURVE)return;
function near(a,x){var b=null,d=1e9;for(var i=0;i<a.length;i++){var e=Math.abs(a[i][0]-x);if(e<d){d=e;b=a[i];}}return b;}
s.addEventListener('mousemove',function(ev){var r=s.getBoundingClientRect(),x=(ev.clientX-r.left)*(s.viewBox.baseVal.width/r.width);var p=near(CURVE.rows,x);if(!p)return;
var q=near(CURVE.act,x);xh.setAttribute('x1',p[0]);xh.setAttribute('x2',p[0]);xh.setAttribute('visibility','visible');
tip.style.display='block';tip.style.left=(ev.pageX+12)+'px';tip.style.top=(ev.pageY-10)+'px';
tip.innerHTML='<b>'+p[1]+'</b><br>回放 '+(p[2]>=0?'+':'')+p[2].toFixed(2)+'%'+(q?'<br>实际执行器 '+(q[1]>=0?'+':'')+q[1].toFixed(2)+'%':'')+(p[3]!=null?'<br>上证 '+(p[3]>=0?'+':'')+p[3].toFixed(2)+'%':'');});
s.addEventListener('mouseleave',function(){tip.style.display='none';xh.setAttribute('visibility','hidden');});})();
"""


# ---------------- 触发详情 ----------------
def code_block(title, text, open_=False):
    if text is None:
        return f"<details><summary>{esc(title)} <span class='mut'>(无此文件)</span></summary></details>"
    return f"<details{' open' if open_ else ''}><summary>{esc(title)} <span class='mut'>({len(text)} 字)</span></summary><pre>{esc(text)}</pre></details>"


def strat_table(s):
    if not s:
        return "<p class='mut'>无</p>"
    L = [f"<p><b>看法</b>: {esc(s.get('view'))}</p>", "<table class='t'><tr><th>代码</th><th>名称</th><th>区间 band</th><th>规则</th><th>方向</th><th>条件</th><th>数量</th><th>竞价</th><th>理由</th></tr>"]
    for x in s.get("codes") or []:
        rs = x.get("rules") or [{}]
        for i, r in enumerate(rs):
            L.append("<tr>" + (f"<td rowspan='{len(rs)}'>{esc(x.get('code'))}</td><td rowspan='{len(rs)}'>{esc(x.get('name'))}</td><td rowspan='{len(rs)}'>{esc(x.get('band'))}</td>" if i == 0 else "")
                     + f"<td>{esc(r.get('id'))}</td><td>{esc(r.get('side'))}</td><td>{('价' + esc(r.get('op')) + esc(r.get('px'))) if r else '(无规则)'}</td><td>{esc(r.get('qty'))}</td><td>{'是' if r.get('auction') else ''}</td><td>{esc(r.get('why'))}</td></tr>")
    L.append("</table>")
    if s.get("next") or s.get("invalid") or s.get("mimic"):
        L.append(f"<p class='mut'>下一轮预期: {esc(s.get('next'))} | 失效条件: {esc(s.get('invalid'))} | 拟人自检: {esc(s.get('mimic'))} | 管到: {esc(s.get('valid_until'))}</p>")
    return "".join(L)


def detail(d, r):
    rr = d / r["id"]
    T = r.get("timing") or {}
    steps = T.get("steps") or {}
    stub = r.get("stub")
    L = [f"<div class='det'><h4>链 {esc(r['id'])} · {esc(r['kind'])} · 触发 {esc(r['trig'])} → 链开跑 {esc(r.get('start'))} → 结束 {esc(r.get('end'))}"
         f"(事实包 {r.get('facts_wait', 0):.0f} 秒 + 链 {r.get('chain_dur') or 0:.1f} 秒 = {r.get('dur') or 0:.1f} 秒) → "
         f"{'生效 v' + str(r.get('ver')) + ' @' + r['applied'] if r.get('applied') else '<b class=red>未生效</b>'} · {esc(r.get('result'))} · ${r.get('usd') or 0:.2f}</h4>"]
    if stub:
        L.append("<p class='inj'>桩模型: 未真调模型(各步耗时 / 成败为注入方案给定, 虚拟时钟); 01 是真脚本产物, 校验是 se_exec 真代码</p>")
    L.append(f"<p><b>触发原因</b>: {esc(r['why'])}" + (f"<br><b>排队合并来源</b>: {esc(', '.join(r.get('src_events') or []))}" if r.get("src_events") else "")
             + (f"<br><b>上一次触发</b>: {esc(r.get('prev_trig'))}({esc(r.get('prev_kind'))})" if r.get("prev_trig") else "")
             + (f"<br><b>指数事件说明</b>: {esc(r.get('idx_note'))}" if r.get("idx_note") else "") + "</p>")
    if r.get("traceback"):
        L.append(code_block("异常 traceback", r["traceback"], True))
    L.append("<details open><summary>数据来源清单(每块材料来自哪个文件、数据截至几点)</summary><table class='t'><tr><th>材料块</th><th>文件</th><th>数据截至</th></tr>")
    for s in r.get("sources") or []:
        extra = f"<br><span class='mut'>名单外票: {esc(s.get('明细'))}</span>" if s.get("明细") else ""
        L.append(f"<tr><td>{esc(s.get('块'))}</td><td>{'<br>'.join(esc(f) for f in s.get('文件') or [])}{extra}</td><td>{esc(s.get('截至'))}</td></tr>")
    L.append("</table></details>")
    fw = r.get("facts_wait") or 0
    L.append("<details open><summary>各步耗时 / token / 美元(时刻 = 距触发秒数)</summary><table class='t'><tr><th>步骤</th><th>开始</th><th>结束</th><th>耗时</th><th>首字节</th><th>成功</th>"
             "<th>输出 token</th><th>缓存读</th><th>缓存写</th><th>美元</th><th>步上限</th><th>错误 / 降级</th></tr>")
    L.append(f"<tr><td>00 事实包(se_facts)</td><td>0</td><td>{fw:.0f}</td><td>{fw:.0f}s</td><td>-</td><td>是</td><td colspan='4'>{esc(r.get('facts') or '')}</td><td>60s</td><td>{esc(r.get('facts_note'))}</td></tr>")
    s01 = steps.get("01") or {}
    L.append(f"<tr><td>01 事实(脚本)</td><td>{fw:.0f}</td><td>{fw + (s01.get('secs') or 0):.1f}</td><td>{s01.get('secs', '-')}s</td><td>-</td><td>{'<b class=red>否</b>' if r.get('err') else '是'}</td>"
             f"<td colspan='4'>候选池 {s01.get('pool', '-')} 只, 01 全文 {s01.get('chars', '-')} 字, 零 token</td><td>-</td><td>{esc(r.get('err') or '')}</td></tr>")
    cmap = {c["step"]: c for c in r.get("calls") or []}
    for k in ("02_market", "03_bull", "03_bear", "04_pick", "05_risk", "06_final"):
        s, c = steps.get(k) or {}, cmap.get(k) or {}
        if s.get("skipped"):
            L.append(f"<tr><td>{SNAME[k]}</td><td colspan='11' class='warn'>跳过: {esc(s['skipped'])}</td></tr>")
            continue
        if not s and not c:
            L.append(f"<tr><td>{SNAME[k]}</td><td colspan='11' class='mut'>没跑(前面失败 / 异常, 链提前结束)</td></tr>")
            continue
        ok = s.get("ok", c.get("ok"))
        deg = {"02_market": "→ 降级: 用开盘实况机械判定当市况", "03_bull": "→ 降级: 03 只剩空方", "03_bear": "→ 降级: 03 只剩多方", "04_pick": "→ 本次作废沿用上一版",
               "05_risk": "→ 降级: 只用脚本统计", "06_final": "→ 本次作废沿用上一版"}[k] if not ok else ""
        t0 = f"{fw + c['t0']:.1f}" if c else "-"
        t1 = f"{fw + c['t1']:.1f}" if c else "-"
        L.append(f"<tr><td>{SNAME[k]}</td><td>{t0}</td><td>{t1}</td><td>{s.get('secs', c.get('secs'))}s</td><td>{s.get('ttft', '-')}</td>"
                 f"<td>{'是' if ok else '<b class=red>否</b>'}</td><td>{s.get('out') or '-'}</td><td>{s.get('cache_read') or '-'}</td><td>{s.get('cache_write') or '-'}</td><td>{(s.get('usd') or 0):.4f}</td>"
                 f"<td>{c.get('deadline') or '-'}s</td><td>{esc(s.get('err') or c.get('err') or '')} {esc(deg)}</td></tr>")
    L.append(f"<tr><th colspan='3'>合计(触发 → 生效)</th><th>{r.get('dur') or 0:.1f}s</th><th colspan='5'></th><th>{r.get('usd') or 0:.4f}</th><th colspan='2'>{esc(T.get('result') or r.get('result'))}</th></tr></table></details>")
    ck = r.get("checked") or {}
    dropped = ck.get("dropped") if ck else r.get("dropped")
    L.append(f"<details open><summary>执行器校验(se_exec.SE.check)剔除 / 提示 {len(dropped or [])} 处 + 落地策略</summary>")
    L.append("<ul>" + "".join(f"<li>{esc(x)}</li>" for x in dropped) + "</ul>" if dropped else "<p class='mut'>无剔除</p>")
    L.append(strat_table(ck.get("strategy")) if ck else "<p class='red'>本次没有可用策略(沿用上一版)</p>")
    L.append("</details>")
    L.append(code_block("01 事实全文(脚本生成, 02~06 共用的缓存前缀; 末尾就是事实包全文)", rd(rr / "01_facts.md")))
    for k, nm in (("02_market", "02 市况"), ("03_bull", "03 多方"), ("03_bear", "03 空方"), ("04_pick", "04 选票"), ("05_risk", "05 风控"), ("06_final", "06 终裁")):
        L.append(code_block(f"{nm} 原文 {k}.md", rd(rr / f"{k}.md")))
        j = rd(rr / f"{k}.json")
        if j is not None:
            L.append(code_block(f"{nm} JSON {k}.json", j))
    L.append(code_block("timing.json(se_chain 写)", rd(rr / "timing.json")))
    if r.get("plan"):
        L.append(code_block("注入方案(桩每步耗时 / 成败)", json.dumps(r["plan"], ensure_ascii=False, indent=1)))
    L.append("</div>")
    return "".join(L)


def badge(kind):
    col = "#2a78d6" if kind in TRIG else "#b31412" if kind in ("链失败", "链异常", "放弃重试", "涨停买不进", "跌停卖不出", "T+1卖不了", "进程崩溃", "收盘后落地", "排队作废") \
        else "#6b6a65"
    return f"<span class='badge' style='background:{col}'>{esc(kind)}</span>"


def timeline(d, ev, runs, tid):
    H = [f"<table class='tl' id='{tid}'>"]
    for e in ev:
        r = runs.get(e.get("run")) if e.get("run") else None
        tags = ""
        if e.get("inj") or (r and r.get("inj")):
            tags += "<span class='ibadge'>注入(非自然发生)</span>"
        if r and r.get("stub"):
            tags += "<span class='ibadge gray'>未真调模型</span>"
        if e.get("budget"):
            tags += "<span class='ibadge gray'>回放预算到, 未调链</span>"
        if e.get("counted") and e["kind"] in TRIG:
            tags += f"<span class='ibadge gray'>占上限 {e.get('n_re')}</span>"
        txt = esc(e.get("why"))
        if e.get("note"):
            txt += f"<br><span class='mut'>{esc(e['note'])}</span>"
        if e.get("void"):
            txt += "<br><span class='mut'>作废: " + esc("; ".join(e["void"])) + "</span>"
        if e.get("dropped"):
            txt += "<br><span class='mut'>校验: " + esc("; ".join(e["dropped"])) + "</span>"
        if e.get("restored"):
            txt += "<br><span class='mut'>崩溃前内存: " + esc(json.dumps(e.get("before"), ensure_ascii=False)) + "<br>恢复后: " + esc(json.dumps(e["restored"], ensure_ascii=False)) + "</span>"
        g = ""
        if r and r.get("chain_dur") is not None:
            g = gantt(r) + f"<div class='mut'>链 {esc(r['id'])} · {esc(r.get('result'))} · ${r.get('usd') or 0:.2f}" + (" · 自由触发(占上限)" if r.get("counted") else " · 必判 / 心跳(不占上限)") + "</div>"
        H.append(f"<tr class='ev-row' data-ev='{e['i']}'><td class='mut'>{e['i']}</td><td><b>{esc(e['t'])}</b></td><td>{badge(e['kind'])}{tags}</td><td style='max-width:460px'>{txt}</td><td>{g}</td></tr>")
        if r and r.get("chain_dur") is not None:
            H.append(f"<tr class='ev-detail'><td></td><td colspan='4'><details><summary>展开链 {esc(r['id'])}: 数据来源 / 01 全文 / 02~06 原文与 JSON / 校验剔除 / token 美元</summary>{detail(d, r)}</details></td></tr>")
    H.append("</table>")
    return "".join(H)


# ---------------- 情况清单 ----------------
def checklist(S, ev, acts, runs, A, inj, nd):
    by_item = {}
    for sc in inj:
        for it in sc["meta"].get("items") or []:
            by_item.setdefault(it, []).append(sc)

    def tms(es):
        return ", ".join(sorted({e["t"][:8] for e in es}))[:260]
    K = lambda *ks: [e for e in ev if e["kind"] in ks]   # noqa: E731
    chain = [r for r in runs.values() if r.get("chain_dur") is not None]
    trig_why = lambda s: [e for e in ev if e["kind"] in TRIG and s in str(e.get("why"))]   # noqa: E731
    flips_k = [e for e in ev if e["kind"] in TRIG and "开盘实况" in str(e.get("why"))]
    cool_flip = [e for e in K("冷却挡掉") if "翻转保留" in str(e.get("note"))]
    hb = [e for e in ev if e["kind"] in TRIG and "心跳" in str(e.get("why"))]
    act_fail = A.get("fails") or []
    items = [
        ("first", "09:15 首版(跑 01→06)", K("首版", "补丁后重跑"), "09:15 触发; 竞价段只读不成交", None),
        ("chain_crash", "链代码异常(se_chain.index_block 遇 p=null 抛 TypeError)", K("链异常"), "se_exec 现行: 记重定异常, 不重试 → 这一轮丢; 回放打补丁后重跑", None),
        ("auction_fill", "竞价单按撮合价成交", K("竞价成交"), "09:25:00 带 auction 的规则: 买价 ≥ 撮合价按撮合价成交, 成交后必跑", None),
        ("auction_limit", "竞价单没成交 → 09:30 起转普通限价单", K("竞价未成交"), "不标已触发, 09:30 起按连续竞价规则撮合", None),
        ("fill_must", "本链成交后必跑(不占上限、不受冷却)", K("成交后必跑", "竞价成交后必跑"), f"连续竞价成交 {sum(1 for a in acts if a.get('phase') == '连续')} 笔; BUY 按 min(规则价, 卖一), SELL 按 max(规则价, 买一)", None),
        ("band_exit", "出区间触发(占上限)", K("出区间") + trig_why("出区间"), "价格出了 band → 自由触发, 受冷却约束", None),
        ("band_repeat", "出区间反复触发", (K("出区间") + trig_why("出区间")) if len(K("出区间") + trig_why("出区间")) >= 2 else [], "每次重定都按新 band; 冷却 3 / 5 分钟内只挡不丢", None),
        ("flip", "开盘实况市况翻转(占上限)", flips_k, "当天 open_live 翻转: " + "; ".join(f"{k} {v}" for k, v in (S.get("flips") or {}).items()), "flip"),
        ("cooldown", "冷却挡掉(10:30 前 3 分钟 / 之后 5 分钟)", K("冷却挡掉"), "只挡自由触发; 必判(成交 / 重试 / 手动)不受冷却", None),
        ("flip_kept", "冷却中来的翻转保留到冷却结束再触发", cool_flip, "10/21 晚修的 bug: 原来冷却中翻转被标已看永久吞掉", None),
        ("index_event", "指数事件(上证从检查点走满动态 θ, 占上限)", K("指数事件") + trig_why("指数事件"), "index_event.check: 检查点 = 上次触发时刻; θ≈0.29%(上证 10/21)", None),
        ("hb_tiers", "心跳各时段档位(5/10/15/30/10/5 分钟下限)", hb, f"心跳 = max(真人决策间隔 P75 {(S.get('hb_real') or [None])[0]} 分钟, 时段下限); 梅月路全天各档: {S.get('hb_min')}", None),
        ("hb_push", "心跳被其它触发往后推(从上次触发秒数重新计)", [e for e in hb if "上次触发" in str(e.get("note"))], "任何触发都重置心跳起点; 链在跑不判心跳", None),
        ("cap", "自由触发到上限后只机械执行", K("到上限"), f"上限 SX.real_cap = {S.get('cap_free')}; 到了仍认 成交 / 心跳 / 重试 / 手动", None),
        ("queue_merge", "链在跑时来事件 → 排队合并 → 链结束立即补跑", K("排队", "排队补跑"), "se_exec.restrategize 的 queued; 补跑是否占上限 = 排队里全是自由触发才占", None),
        ("api_retry", "API 断连 / 链失败 → 90 秒后重试", K("链失败", "失败重试"), "沿用上一版; fail_n ≤ 3 时 90 秒后带原因重试(必判)", "api"),
        ("api_giveup", "连续失败放弃(fail_n > 3 不再重试)", K("放弃重试"), "se_exec: k ≤ 3 才设重试 → 实际是失败第 4 次才放弃(共试 4 次)", None),
        ("deg_02", "02 失败 / 超时 → 用机械市况", [{"t": r["trig"]} for r in chain if not (r.get("steps", {}).get("02_market") or {}).get("ok", True)], "se_chain: m02 = 开盘实况机械判定", None),
        ("deg_03", "03 一边失败 → 单边", [{"t": r["trig"]} for r in chain if any(not (r.get("steps", {}).get(k) or {}).get("ok", True) for k in ("03_bull", "03_bear"))], "无对辩, 04 照跑", None),
        ("deg_05", "05 时间不够只用脚本统计", [{"t": r["trig"]} for r in chain if r.get("skip05")], "04 结束剩 ≤ 70 秒 → 05 不调模型", None),
        ("fail_04", "04 失败 → 本次作废沿用上一版", [{"t": r["trig"]} for r in chain if "04 失败" in str(r.get("result"))], "返回 None → 链失败 → 90 秒重试", None),
        ("fail_06", "06 失败 / 无 JSON → 本次作废沿用上一版", [{"t": r["trig"]} for r in chain if "06 失败" in str(r.get("result"))], "返回 None → 链失败 → 90 秒重试", None),
        ("over_170", "整条链超 170 秒 / 触发→生效 ≥ 180 秒", [{"t": r["trig"]} for r in chain if (r.get("dur") or 0) >= LIMIT_S or (r.get("chain_dur") or 0) > 170], "执行器不杀链, 只等; 期间按旧策略成交", None),
        ("facts_wait", "事实包现做等 60 秒(最新一份超 30 分钟)", [{"t": r["trig"]} for r in chain if (r.get("facts_wait") or 0) >= 60], "se_facts.refresh: 60 秒内没做完就用旧的; 这 60 秒算进触发→生效", None),
        ("limit_up", "涨停封板买不进", K("涨停买不进"), "回放按卖一为空判买不进(se_exec 现行会假成交)", None),
        ("limit_down", "跌停封板卖不出", K("跌停卖不出"), "回放按买一为空判卖不出(se_exec 现行会假成交)", None),
        ("t1", "T+1 当日买的卖不了", K("T+1卖不了") + [{"t": r["trig"]} for r in chain if any("超过持仓" in x for x in (r.get("dropped") or []))], "执行时: 可卖 0 → 规则作废一次; 校验时: SELL 超可卖直接剔", None),
        ("cash_trunc", "现金不够按现金截断", K("现金截断"), "n = 向下取整((现金 − 5) / 价)", None),
        ("sell_trunc", "卖出超过可卖截断", K("可卖截断") + [{"t": r["trig"]} for r in chain if any("卖出合计" in x for x in (r.get("dropped") or []))], "校验只提示; 执行 n = min(规则量, 今天可卖)", None),
        ("no_cash", "规则命中但没钱 / 没可卖", K("规则命中没钱/没可卖"), "规则标已触发(作废一次), 不成交", None),
        ("check_drop", "校验剔除(超涨跌停 / 非整百 / 不在候选池 / 方向不配)", [{"t": r["trig"]} for r in chain if any(("超涨跌停" in x or "整数倍" in x or "不在可用标的" in x or "不配" in x) for x in (r.get("dropped") or []))],
         "se_exec.SE.check: 剔掉不回炉", None),
        ("stale", "盘口断流(某票 60 秒无更新)", K("盘口断流"), "se_exec.Feed: 新浪补价(回放用 1 分钟线); 补不到继续用旧价", None),
        ("suspend", "停牌票", K("停牌"), "成交量 0 / 现价 0 → 不撮合、不判出区间; 复牌恢复", None),
        ("facts_missing", "事实包缺", [], "se_exec._chain 传 \"(今日事实包缺)\"; 01 候选池只剩持仓 + 上一版策略", None),
        ("crash_restore", "进程崩溃后续跑(断点恢复)", [], "se_exec.SE._restore: 版本 / fired / 计数 / 冷却起点 / 翻转已看 / 被打断那轮 → 补叫", "restart"),
        ("kick", "手动 KICK(往影子账目录写 KICK 文件)", [], "必判不占上限, 读完即删", "kick"),
        ("lunch", "午休", K("午休"), "11:31~12:59 不成交不判; 心跳计时扣 90 分钟", None),
        ("close_late", "收盘时链还没跑完", K("收盘后落地"), "14:57 后落地不再生效", None),
        ("queue_void", "收盘后排队作废", K("排队作废"), "收盘后不再补跑", None),
        ("void_close", "收盘未触发规则作废", [e for e in K("收盘停") if e.get("void")], "14:57 停, 当前版本未成交规则全部作废", None),
        ("budget", "回放预算到(本回放自加的花费闸, 真调最多 14 次)", [e for e in ev if e.get("budget")], "之后本该触发的照记, 不调链, 继续按最后一版机械执行", None),
        ("next_day", "次日接续(state 接到下一天)", [], "se_exec._init_state: SE_GENESIS 当天 10 万; 之后接前一交易日影子账收盘(持仓 / 现金 / 成本照搬, 隔夜全部可卖)", None),
    ]
    out = []
    for key, title, real, how, act_key in items:
        st_ = []
        tm = []
        if real:
            st_.append("真实")
            tm.append(tms(real))
        if act_key == "api" and act_fail:
            st_.append("真实·实际执行器")
            tm.append("实际执行器 " + ", ".join(r["trig"] + "→" + (r["end"] or "?") for r in act_fail))
        if act_key == "restart" and A.get("restarts"):
            st_.append("真实·实际执行器")
            tm.append("实际执行器 " + ", ".join(e["t"] for e in A["restarts"]))
        if act_key == "kick" and A.get("kicks"):
            st_.append("真实·实际执行器")
            tm.append("实际执行器 " + ", ".join(e["t"] for e in A["kicks"]))
        if act_key == "flip" and any("开盘实况" in str(r.get("why")) for r in A.get("runs") or []):
            st_.append("真实·实际执行器")
            tm.append("实际执行器 " + ", ".join(r["trig"] for r in A["runs"] if "开盘实况" in str(r.get("why"))))
        scs = by_item.get(key) or []
        if key == "next_day" and nd:
            st_.append("注入(真代码)")
            tm.append("见下方次日接续")
        if scs:
            st_.append("注入")
            tm.append("注入: " + ", ".join(f"<a href='#{s['meta']['id']}'>{esc(s['meta']['id'])}</a>" for s in scs))
        out.append({"key": key, "title": title, "status": " + ".join(st_) or "未出现", "times": " | ".join(tm) or "-", "how": how})
    return out


CSS = """
body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;margin:16px 24px;color:#0b0b0b;background:#fcfcfb;font-size:13px}
h1{font-size:20px;margin:4px 0}h2{font-size:16px;margin:24px 0 8px;border-bottom:2px solid #e6e5e0;padding-bottom:4px}h3{font-size:14px;margin:16px 0 4px}h4{margin:6px 0}
.cards{display:flex;flex-wrap:wrap;gap:10px}.card{border:1px solid #dcdbd5;border-radius:8px;padding:8px 12px;min-width:150px;background:#fff}
.card .v{font-size:20px;font-weight:600}.card .k{color:#52514e;font-size:11px}
.mut{color:#52514e}.red{color:#b31412}.warn{color:#8a5a00}.inj{background:#fdf0ee;border:1px dashed #b31412;padding:4px 8px;border-radius:4px;color:#8f1010}
table.t{border-collapse:collapse;margin:4px 0}table.t td,table.t th{border:1px solid #e6e5e0;padding:3px 6px;vertical-align:top;text-align:left}
table.t th{background:#f4f3ef}
table.tl{border-collapse:collapse;width:100%}table.tl td{border-bottom:1px solid #eeede8;padding:4px 6px;vertical-align:top}
tr.ev-row:hover{background:#f4f3ef}
.badge{display:inline-block;color:#fff;border-radius:3px;padding:1px 6px;font-size:12px;white-space:nowrap}
.ibadge{display:inline-block;background:#fdf0ee;color:#8f1010;border:1px solid #b31412;border-radius:3px;padding:0 4px;font-size:11px;margin-left:4px;white-space:nowrap}
.ibadge.gray{background:#f4f3ef;color:#52514e;border-color:#898781}
pre{white-space:pre-wrap;word-break:break-all;background:#f4f3ef;border:1px solid #e6e5e0;padding:8px;max-height:520px;overflow:auto;font-size:12px}
details{margin:3px 0}summary{cursor:pointer;color:#1f5fb0}
.det{border-left:3px solid #2a78d6;padding:4px 10px;margin:4px 0 10px;background:#fff}
.note{background:#fdf6e3;border:1px solid #d9b45a;padding:6px 10px;border-radius:6px;margin:6px 0}
.scen{border:1px solid #dcdbd5;border-radius:8px;padding:6px 12px;margin:10px 0;background:#fff}
.tip{position:absolute;display:none;background:#fff;border:1px solid #898781;border-radius:4px;padding:4px 8px;font-size:12px;pointer-events:none}
.legend span{margin-right:10px}
"""


def build(d):
    S, ev, acts, curve, runs = load_dir(d)
    D, skill = S.get("date"), S.get("skill")
    A = load_actual(D, skill)
    inj = load_inject(d)
    nd = jl(d / "inject" / "next_day.json", None)
    chain = [r for r in runs.values() if r.get("chain_dur") is not None and not r.get("err")]
    durs = [r["dur"] for r in chain]
    cdurs = [r["chain_dur"] for r in chain]
    real_trig = [e for e in ev if e.get("run") and not e.get("inj")]
    budget_n = sum(1 for e in ev if e.get("budget"))
    ar = A.get("runs") or []
    a_tot = [r["total"] for r in ar if r.get("total") is not None]
    a_usd = sum(r["usd"] or 0 for r in ar)
    sh_ = S.get("sh_ret_pct")
    H = [f"<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>{esc(skill)} 策略执行器 {esc(D)} 全天回放</title><style>{CSS}</style></head><body>"]
    H.append(f"<h1>策略执行器全天回放 · {esc(skill)} · {esc(D)}(09:15 → 15:00)</h1>")
    H.append(f"<p class='mut'>离线回放: {esc(D)} 真实 3 秒盘口推进模拟时钟, 10 万现金空仓起步(10/22 起的真实设定); 每次触发真调 scripts/chain/se_chain.run(effort=low, live=False 等价: 名单外票用 1 分钟线复原新浪快照);"
             f" 新策略生效 = 触发 + 事实包等待 + 链实际耗时; 链在跑时按旧策略继续成交。生成于 {esc(S.get('generated'))}</p>")
    H.append("<div class='cards'>"
             f"<div class='card'><div class='k'>回放收益(10 万起)</div><div class='v'>{S['ret_pct']:+.2f}%</div><div class='k'>nav {S['end_nav']:.0f}</div></div>"
             f"<div class='card'><div class='k'>不操作(空仓现金)</div><div class='v'>+0.00%</div><div class='k'>回放差 {S['ret_pct']:+.2f} 个点</div></div>"
             f"<div class='card'><div class='k'>上证指数</div><div class='v'>{(f'{sh_:+.2f}%') if sh_ is not None else '-'}</div><div class='k'>回放差 {(f'{S['ret_pct'] - sh_:+.2f}') if sh_ is not None else '-'} 个点</div></div>"
             f"<div class='card'><div class='k'>10/21 实际执行器(单次 claude -p 版)</div><div class='v'>{(f'{A['end_ret']:+.2f}%') if A.get('end_ret') is not None else '-'}</div><div class='k'>起点 = 旧账本 {float(A['start'].get('cash') or 0):.0f} 现金 + 持仓; 收益% 对比</div></div>"
             f"<div class='card'><div class='k'>链次数(回放)</div><div class='v'>{len(chain)}</div><div class='k'>真实触发 {len(real_trig)} · 异常 {sum(1 for r in runs.values() if r.get('err'))} · 预算到未调 {budget_n} · 自由触发 {S.get('n_free')}/{S.get('cap_free')}</div></div>"
             f"<div class='card'><div class='k'>总花费(回放 / 实际执行器)</div><div class='v'>${S['usd']:.2f}</div><div class='k'>每次 ${(S['usd'] / max(1, len(chain))):.2f} · 实际执行器 ${a_usd:.2f}({len(ar)} 次)</div></div>"
             f"<div class='card'><div class='k'>触发→生效 中位 / 最大</div><div class='v'>{(f'{st.median(durs):.0f}s / {max(durs):.0f}s') if durs else '-'}</div>"
             f"<div class='k'>{'全部 < 180 秒' if durs and max(durs) < LIMIT_S else f'<b class=red>{sum(1 for x in durs if x >= LIMIT_S)} 次 ≥ 180 秒</b>'} · 纯链 中位 {(st.median(cdurs) if cdurs else 0):.0f}s / 最大 {(max(cdurs) if cdurs else 0):.0f}s</div></div>"
             f"<div class='card'><div class='k'>实际执行器 触发→生效</div><div class='v'>{(f'{st.median(a_tot):.0f}s / {max(a_tot):.0f}s') if a_tot else '-'}</div><div class='k'>中位 / 最大(含 1 次 API 断连 431 秒)</div></div>"
             f"<div class='card'><div class='k'>成交 / 事件</div><div class='v'>{len(acts)} 笔 / {len(ev)} 条</div><div class='k'>实际执行器成交 {len(A.get('acts') or [])} 笔</div></div>"
             "</div>")
    H.append("<div class='note'><b>口径说明</b>: ① 事实包按触发时刻取 scripts/dfcf/paper/facts/" + esc(D) + "/*/facts.md 里\"构建于\" ≤ 当时的最新一份(同 se_facts.refresh: 不满 30 分钟复用; 超 30 分钟现做, 60 秒内没做完用旧的),"
             " 再按 se_facts.slim 瘦身; results/_live 下的 facts.txt 是 14:40 的那份(含午后信息), 09:15 就用它等于偷看"
             " ② 导师画像 / 规则用文件当前版本 ③ 名单外的票(3 秒盘口没采的)用 tdx 1 分钟线: 撮合价 = 最近一根已收完 bar 的收盘价, 比实盘新浪 10 秒补价粗"
             " ④ 回放比 se_exec 多一条真实约束: 涨停封板(卖一空)买不进 / 跌停封板(买一空)卖不出; 14:57:00 停(se_exec 现行跑到 14:57:59)"
             " ⑤ 09:16 首版链在 se_chain.index_block 抛 TypeError(面板 中证2000 p=null), se_exec 实盘会丢这一轮; 回放在进程内打补丁后立即重跑(源文件没改)"
             " ⑥ <span class='inj'>红框 = 注入(非自然发生)</span>; 没标的都是回放里自然发生的; 注入演示全用桩模型(未真调模型)</div>")
    H.append("<h2>全天总览(蓝 = 回放每次链, 橙 = 10/21 实际执行器每次重定, 半透明红边 = 失败 / 未生效; ▼ = 实际执行器进程重启; 圆点 = 回放事件, 大点 = 触发)</h2>" + overview(ev, runs, A))
    H.append("<h2>主时间轴(回放, 每个事件一行; 触发行带甘特: 0 = 触发 → 00 事实包 → 01 脚本 → 02 → 03 多 ∥ 空 → 04 → 05 → 06 → 生效; 红虚线 = 180 秒)</h2>")
    H.append("<p class='legend'>" + "".join(f"<span><span class='badge' style='background:{c}'>{esc(n)}</span></span>" for _, n, c in STEPS) + " <span class='mut'>半透明红边 = 该步失败 / 超时; 悬停看秒数; 点「展开」看详情</span></p>")
    H.append(timeline(d, ev, runs, "tl-main"))
    H.append(f"<h2>净值曲线(收益%; 回放 {S['ret_pct']:+.2f}% / 实际执行器 {(A.get('end_ret') or 0):+.2f}% / 上证 {(f'{sh_:+.2f}%') if sh_ is not None else '-'}; 鼠标悬停看数值)</h2>"
             + curve_svg(curve, acts, A) + "<p class='mut'>实际执行器的起点是旧 paper 账本(纳指ETF 17000 + 长江电力 2200 + 现金 6053, 按昨收约 100407), 回放是 10 万现金空仓: 两条线只能比收益%, 不能比金额。</p>")
    # 实际执行器
    H.append(f"<h2>对照: 10/21 实际执行器(单次 claude -p 版, 只读 {esc(A['base'])})</h2>")
    H.append(f"<p>{esc(A.get('summary'))}</p><p class='mut'>耗时口径: 触发 = events.jsonl 的\"重定\"时刻; claude 开跑 = scripts/claude_profile/profile_log.csv; 结束 = scripts/lib/claude_cost.csv(ts / duration_s / cost)。"
             "它当时是固定 60 分钟心跳 + 单次 claude -p(读文件), 不是 01→06 链; 事实包现做也在这条时间里。</p>")
    H.append("<table class='t'><tr><th>#</th><th>触发</th><th>原因</th><th>claude 开跑</th><th>结束</th><th>触发→结束</th><th>claude 本身</th><th>美元</th><th>结果</th><th>落地策略(看法 / 规则)</th></tr>")
    for i, r in enumerate(ar, 1):
        s = (r.get("strategy") or {}).get("strategy") or {}
        rules = "; ".join(f"{x.get('code')} {y['side']} 价{y['op']}{y['px']}×{y['qty']}" for x in s.get("codes") or [] for y in x.get("rules") or [])
        H.append(f"<tr><td>{i}</td><td>{esc(r['trig'])}</td><td>{esc(r['why'])}</td><td>{esc(r['claude_start'])}</td><td>{esc(r['end'])}</td>"
                 f"<td>{'<b class=red>' if (r['total'] or 0) >= LIMIT_S else ''}{r['total']}s{'</b>' if (r['total'] or 0) >= LIMIT_S else ''}</td><td>{r['claude_s']}s</td><td>{(r['usd'] or 0):.2f}</td>"
                 f"<td>{'生效 ' + esc((r.get('strategy') or {}).get('file')) if r['ok'] else '<b class=red>失败</b> ' + esc(r['err'])}</td><td>{esc(str(s.get('view') or '')[:120])}<br><span class='mut'>{esc(rules)}</span></td></tr>")
    H.append("</table>")
    H.append("<p>实际执行器的其它事件: " + esc("; ".join(f"{e['t']} {e['kind']}" + (f"(恢复到 v{e.get('ver')}, 重定 {e.get('n_all')} 次)" if e['kind'] == '续跑恢复' else "") for e in A.get("events") or [] if e.get("kind") != "重定")) + "</p>")
    H.append("<p>实际执行器成交: " + (esc("; ".join(f"{a['t']} {a['side']} {a.get('name') or ''}{a['code']} {a['qty']}@{a['px']}" for a in A.get("acts") or [])) or "无") + "</p>")
    H.append(f"<div class='note'><b>对比要点</b>: 回放 {len(chain)} 次链(触发→生效中位 {(st.median(durs) if durs else 0):.0f} 秒, ${S['usd']:.2f}) vs 实际执行器 {len(ar)} 次(中位 {(st.median(a_tot) if a_tot else 0):.0f} 秒, ${a_usd:.2f});"
             f" 回放心跳 {S.get('hb_min', {}).get('10:00')} 分钟(真人 P75)、实际执行器 60 分钟固定; 回放从 10 万空仓建仓, 实际执行器从旧账本满仓起步只加了 1 笔。</div>")
    # 成交
    H.append("<h2>回放成交明细(actions.jsonl)</h2><table class='t'><tr><th>时间</th><th>阶段</th><th>方向</th><th>代码</th><th>名称</th><th>价</th><th>数量</th><th>费用</th><th>规则</th><th>当时盘口</th><th>成交后现金</th><th>截断</th><th>理由</th></tr>")
    for a in acts:
        tp = a.get("tape") or {}
        H.append(f"<tr><td>{esc(a['t'])}</td><td>{esc(a.get('phase'))}</td><td>{esc(a['side'])}</td><td>{esc(a['code'])}</td><td>{esc(a.get('name'))}</td><td>{a['px']}</td><td>{a['qty']}</td><td>{a['fee']}</td>"
                 f"<td>{esc(a['rule'])}</td><td>现 {esc(tp.get('p'))} 买一 {esc(tp.get('b1'))} 卖一 {esc(tp.get('a1'))} @{esc(tp.get('t'))} {esc(tp.get('src') or '3秒盘口')}</td><td>{a.get('cash_after')}</td>"
                 f"<td>{esc('; '.join(a.get('notes') or []))}</td><td>{esc(a.get('why'))}</td></tr>")
    H.append("</table>" if acts else "<tr><td colspan='13' class='mut'>全天无成交</td></tr></table>")
    H.append(f"<p>收盘持仓: {esc(', '.join(f'{c} {p['qty']} 股(成本 {p.get('cost')}, 收 {p.get('close_px')})' for c, p in (S.get('end_positions') or {}).items()) or '空仓')} · 现金 {S.get('cash', 0):.2f}</p>")
    # 注入
    H.append("<h2>注入演示(全部非自然发生; 桩模型未真调模型; 从主回放快照分叉, 行情 / 规则代码全真)</h2>")
    for sc in inj:
        m, Ss = sc["meta"], sc["S"]
        H.append(f"<div class='scen' id='{esc(m['id'])}'><h3>{esc(m['id'])} · {esc(m['title'])} <span class='ibadge'>注入(非自然发生)</span><span class='ibadge gray'>未真调模型</span></h3>"
                 f"<p>{esc(m['desc'])}</p><p class='mut'>分叉自主回放 {esc(m.get('fork_snapshot'))} 的快照 · 窗口 {esc(m['fork'])} → {esc(m['t_end'])} · 事件 {len(sc['ev'])} 条 · 链 {Ss.get('calls')} 次 · 覆盖: {esc(', '.join(m.get('items') or []))}</p>"
                 f"<details><summary>展开时间轴({len(sc['ev'])} 行)</summary>{timeline(sc['dir'], sc['ev'], sc['runs'], 'tl-' + m['id'])}</details></div>")
    if nd:
        H.append("<div class='scen' id='next_day'><h3>次日接续 <span class='ibadge'>注入(真代码)</span></h3><p>把本回放收盘账当作 SE_GENESIS 首日(10/22)收盘, 在临时目录用 se_exec.SE(真代码 _init_state)建 10/22 与 10/23 的开盘账:</p>"
                 f"<table class='t'><tr><th>日</th><th>来源</th><th>现金</th><th>持仓(股 / 可卖 / 成本)</th></tr>"
                 f"<tr><td>回放收盘</td><td>state_close.json</td><td>{nd['close']['cash']}</td><td>{esc('; '.join(f'{c} {p['qty']}/{p['sellable']}/{p.get('cost')}' for c, p in nd['close']['positions'].items()) or '空仓')}</td></tr>"
                 f"<tr><td>10/22 开盘</td><td>{esc(nd['d1022']['from'])}</td><td>{nd['d1022']['cash']}</td><td>{esc('; '.join(f'{c} {p['qty']}/{p['sellable']}' for c, p in nd['d1022']['positions'].items()) or '空仓')}</td></tr>"
                 f"<tr><td>10/23 开盘</td><td>{esc(nd['d1023']['from'])}</td><td>{nd['d1023']['cash']}</td><td>{esc('; '.join(f'{c} {p['qty']}/{p['sellable']}/{p.get('cost')}' for c, p in nd['d1023']['positions'].items()) or '空仓')}</td></tr></table>"
                 "<p class='mut'>今天买的(收盘可卖 0)隔夜后全部可卖; 10/22 本身是 genesis(10 万), 不接 10/21。</p></div>")
    # 清单
    CL = checklist(S, ev, acts, runs, A, inj, nd)
    H.append("<h2>情况清单(本例: 真实 = 主回放自然发生 / 真实·实际执行器 = 10/21 实盘执行器发生过 / 注入 = 演示 / 未出现)</h2><table class='t' id='sit'><tr><th>#</th><th>情况</th><th>本例</th><th>时刻</th><th>怎么处理</th></tr>")
    for i, c in enumerate(CL, 1):
        col = "#006b00" if c["status"].startswith("真实") else "#8f1010" if c["status"].startswith("注入") else "#52514e"
        H.append(f"<tr data-key='{c['key']}'><td>{i}</td><td>{esc(c['title'])}</td><td><b style='color:{col}'>{esc(c['status'])}</b></td><td>{c['times']}</td><td>{esc(c['how'])}</td></tr>")
    H.append("</table>")
    H.append(f"<p class='mut'>文件: {esc(str(d))} · events.jsonl {len(ev)} 条 · actions.jsonl {len(acts)} 条 · curve.csv {len(curve)} 行 · 每次链子目录 NN_HHMMSS/ · 注入 inject/&lt;场景&gt;/ · "
             f"脚本 scripts/dfcf/paper/se_dayreplay.py(引擎) / se_dayinject.py(注入) / se_dayview.py(本页)</p>")
    H.append(f"<script>{JS}</script></body></html>")
    out = d / "day.html"
    out.write_text("".join(H), encoding="utf-8")
    (d / "checklist.json").write_text(json.dumps(CL, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def check(d, out):
    """自检(断言结果, 不只看没报错): 关键块在 / 主时间轴行数 = events 数 / 真实触发 ≥ 6 且每次有 timing.json / 情况清单每项有状态 / 无外网引用"""
    from html.parser import HTMLParser
    h = out.read_text(encoding="utf-8")
    ev = jsonl(d / "events.jsonl")
    S = jl(d / "summary.json", {}) or {}
    runs = {r["id"]: r for r in S.get("runs") or []}

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids, self.rows, self.cur, self.depth, self.ext = set(), {}, None, 0, []

        def handle_starttag(self, tag, at):
            a = dict(at)
            if a.get("id"):
                self.ids.add(a["id"])
            if tag == "table" and str(a.get("id", "")).startswith("tl-"):
                self.cur, self.depth = a["id"], 0
            if tag == "table" and self.cur:
                self.depth += 1
            if tag == "tr" and self.cur and a.get("class") == "ev-row":
                self.rows[self.cur] = self.rows.get(self.cur, 0) + 1
            for k in ("src", "href"):
                if str(a.get(k, "")).startswith(("http://", "https://", "//")):
                    self.ext.append(a[k])

        def handle_endtag(self, tag):
            if tag == "table" and self.cur:
                self.depth -= 1
                if self.depth == 0:
                    self.cur = None
    p = P()
    p.feed(h)
    for k in ("tl-main", "curve", "sit"):
        assert k in p.ids, f"缺关键块 #{k}"
    for k in ("对照: 10/21 实际执行器", "注入演示", "情况清单", "数据来源清单", "01 事实全文"):
        assert k in h, f"缺关键块「{k}」"
    assert p.rows.get("tl-main") == len(ev), f"主时间轴行数 {p.rows.get('tl-main')} ≠ events {len(ev)}"
    real = [e for e in ev if e.get("run") and not e.get("inj") and runs.get(e["run"], {}).get("chain_dur") is not None and not runs[e["run"]].get("err") and not runs[e["run"]].get("stub")]
    assert len(real) >= 6, f"真实触发(真调模型跑完链)只有 {len(real)} 次 < 6"
    miss = [e["run"] for e in real if not (d / e["run"] / "timing.json").exists()]
    assert not miss, f"这些链没有 timing.json: {miss}"
    CL = jl(d / "checklist.json", []) or []
    assert CL and all(c.get("status") for c in CL), "情况清单有项没有状态"
    assert f"<tr data-key='{CL[-1]['key']}'>" in h, "情况清单没写进页面"
    assert not p.ext, f"有外网引用: {p.ext[:3]}"
    for sid, n in p.rows.items():
        if sid != "tl-main":
            evn = len(jsonl(d / "inject" / sid[3:] / "events.jsonl"))
            assert n == evn, f"注入 {sid} 行数 {n} ≠ events {evn}"
    return {"rows_main": p.rows.get("tl-main"), "events": len(ev), "real_triggers": len(real), "checklist": len(CL), "inject_tables": len(p.rows) - 1,
            "status_count": {s: sum(1 for c in CL if c["status"] == s) for s in sorted({c["status"] for c in CL})}}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "results" / "inv-stock" / "paper" / "day_replay" / "2026-10-21" / "meiyuelu"))
    ap.add_argument("--no-check", action="store_true")
    a = ap.parse_args()
    out = build(Path(a.dir))
    print(out)
    if not a.no_check:
        print("自检通过:", json.dumps(check(Path(a.dir), out), ensure_ascii=False))


if __name__ == "__main__":
    main()
