# -*- coding: utf-8 -*-
"""t_private_report.py — 牧原私有报告(零 token; 10/18 晚用户定: 牧原单独一份 report, 不进 git, 在 PC1 双击看; 明暗两主题 + 你 vs paper 对照曲线)

产物: scripts/dfcf/snapshots/report_private.html(snapshots/ 整个 gitignore)
内容: ①对照曲线: 累计 T 增值(元) / 收益率(持有 + T), 你的实盘 vs 决策T vs 机械T vs 不T, 可切"paper 起跑后"同起点比
      ②你的实盘 T 逐日(snapshots 成交单 → 当日 T 增值, 9/28 起全部历史) ③四方对照表(读 snapshots/muyuan-skill/t_log)
      ④决策T 最近几次决策和理由 ⑤skill 状态(规则数 / 日卡数)和数据画像要点
T 增值 = 卖出额 − 买入额 − 费用 + 当日净增减股数 × 收盘价(= 当天这些交易比"一笔不做"多赚的钱); 费用有导出列用实收, 没有按每笔最低 5 元 + 卖出印花税估
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/t_private_report.py   (check md 每晚 t_review 之后跑)
"""
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
import t_bot as TB        # noqa: E402
import t_review as TR     # noqa: E402

CODE, SYM = "002714", "sz002714"
SK = TB.SNAP / "muyuan-skill"
OUT = TB.SNAP / "report_private.html"


def closes():
    from kline_db import db
    c = db()
    try:
        cur = c.cursor()
        cur.execute("select trade_date, cast(close as double) from kline_day where symbol=%s and is_deleted=0 and trade_date>='2026-09-01'", (SYM,))
        return {str(d): v for d, v in cur.fetchall()}
    finally:
        c.close()


def main():
    C = closes()
    days = sorted({f.name[:10] for f in TB._snap_files()})
    real = []
    for D in days:
        rt = TB.real_trades(D, {CODE})
        if not rt or D not in C:
            continue
        v, fee, net = TR.t_value([(x[2], x[4], x[3], x[6]) for x in rt], C[D])
        buys = [x for x in rt if x[2] == "BUY"]
        sells = [x for x in rt if x[2] == "SELL"]
        real.append((D, len(rt), sum(x[3] for x in buys), sum(x[3] for x in sells), net, fee, v, C[D]))
    logs = {}
    for f in sorted((SK / "t_log").glob("*.json")):
        try:
            logs[f.stem] = json.loads(f.read_text(encoding="utf-8")).get("books") or {}
        except ValueError:
            pass
    esc = html.escape
    sg = lambda x: ("+" if x > 0 else "−" if x < 0 else "") + f"{abs(x):,.0f}"   # noqa: E731
    cl = lambda x: "up" if x > 0 else "dn" if x < 0 else ""   # noqa: E731
    tot = sum(r[6] for r in real)
    rows = "".join(f"<tr><td>{d}</td><td class=n>{n}</td><td class=n>{b}</td><td class=n>{s}</td><td class=n>{net:+d}</td><td class=n>{fee:.0f}</td>"
                   f"<td class='n {cl(v)}'><b>{sg(v)}</b></td><td class=n>{c}</td></tr>" for d, n, b, s, net, fee, v, c in reversed(real))
    four = ""
    for d in sorted(logs, reverse=True):
        bk = logs[d]
        g = lambda k: (bk.get(k) or {}).get("t_value")   # noqa: E731
        four += f"<tr><td>{d}</td>" + "".join(f"<td class='n {cl(x or 0)}'>{'—' if x is None else sg(x)}</td>" for x in (g("REAL"), g("A-dmuyuan"), g("A-tmuyuan"))) + "<td class=n>0</td></tr>"
    four = four or "<tr><td colspan=5 class=m>10/19 起跑(第 1 天建底仓, 10/20 起开始 T), 收盘后 t_review.py 写入</td></tr>"
    st = {}
    try:
        st = json.loads((HERE / "t_decide_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    decs = []
    for d in sorted(st, reverse=True)[:3]:
        for slot, v in (st[d].get("A-dmuyuan") or {}).items():
            if isinstance(v, dict) and v.get("decision"):
                x = v["decision"]
                decs.append(f"<tr><td>{d} {slot}</td><td>{esc(str(x.get('action')))} {esc(str(x.get('tier')))}</td><td>{esc(str(x.get('reason'))[:160])}</td><td class=n>${v.get('cost', 0)}</td></tr>")
    decs = "".join(decs) or "<tr><td colspan=4 class=m>还没有决策记录</td></tr>"
    prof = (SK / "persona" / "profile.md").read_text(encoding="utf-8")
    r30 = re.search(r"\| 近 30 日 \| ([^|]+) \| ([^|]+) \| ([^|]+) \|", prof)
    nrules = len(re.findall(r"^### R\d+", (SK / "persona" / "rules.md").read_text(encoding="utf-8"), re.M))
    ncards = len(re.findall(r"^### 20", (SK / "persona" / "cases.md").read_text(encoding="utf-8"), re.M))
    # 曲线数据: 每个交易日(有你成交单或有 paper 复盘的日子)的 T 增值 → 前端累加; 收益率口径 = 牧原持有收益 + 累计 T 增值 / 底仓市值
    dates = sorted({r[0] for r in real} | set(logs))
    rmap = {r[0]: r[6] for r in real}
    base_val = (TB.real_position(CODE) or 1) * (C.get(dates[0]) if dates else 1)
    series = {"real": [rmap.get(d, (logs.get(d, {}).get("REAL") or {}).get("t_value")) for d in dates],
              "dec": [(logs.get(d, {}).get("A-dmuyuan") or {}).get("t_value") for d in dates],
              "mech": [(logs.get(d, {}).get("A-tmuyuan") or {}).get("t_value") for d in dates]}
    data = json.dumps({"dates": dates, "close": [C.get(d) for d in dates], "base_val": base_val, "series": series,
                       "paper_start": min(logs) if logs else "2026-10-19"}, ensure_ascii=False).replace("<", "\\u003c")
    body = f"""<header><h1>牧原股份 · 私有报告</h1><span class=m>生成 {dt.datetime.now():%Y-%m-%d %H:%M} · 只在本机(snapshots/ 不进 git)</span><span style="flex:1"></span><button class=btn id=theme>切换明暗</button></header>
<div class=card><h2>你 vs paper 对照曲线</h2>
<div class=bar><span class=m>口径</span><button class="btn mode on" data-m="yuan">累计 T 增值(元)</button><button class="btn mode" data-m="pct">收益率(持有 + T)</button>
<span class=m style="margin-left:12px">区间</span><button class="btn rng on" data-r="all">全部(9/28 起)</button><button class="btn rng" data-r="paper">paper 起跑后</button></div>
<div id=chart><div id=tip></div></div>
<p class=note><b>累计 T 增值</b> = 每天"这些交易比一笔不做多赚的钱"(扣费)累加, 不T 恒为 0 线; <b>收益率(持有 + T)</b> = 牧原持有收益(不T 线, 灰虚线) + 累计 T 增值 ÷ 底仓市值, 能直接看出 T 把持有收益抬高还是拉低。
你的实盘从 9/28 起(只有贴了成交单的日子; 没贴单的日子按 0 记、空心点); 决策T / 机械T 从 paper 起跑日起。切到"paper 起跑后"几条线同一起点比。</p></div>
<div class=card><h2>你的实盘 T 逐日(扣费后比"一笔不做"多赚 / 少赚多少元) · 合计 <span class={cl(tot)}>{sg(tot)} 元</span>({len(real)} 个有成交的交易日)</h2>
<table><tr><th>日期</th><th class=n>成交笔数</th><th class=n>买入股数</th><th class=n>卖出股数</th><th class=n>净增减</th><th class=n>费用</th><th class=n>T 增值(元)</th><th class=n>收盘</th></tr>{rows}</table>
<p class=note>T 增值 = 卖出额 − 买入额 − 费用 + 净增减股数 × 当日收盘。正数 = 当天的交易比不动多赚; 净增减不为 0 的日子(加仓 / 减仓)里, 增值包含"多买 / 少拿的那部分按收盘价估值", 不全是 T 的价差。费用: 有导出费用列的用实收, 否则按每笔最低 5 元 + 卖出印花税 0.05% 估。只统计你贴了成交单的日子。</p></div>
<div class=card><h2>四方对照: 当日 T 增值(元)</h2><table><tr><th>日期</th><th class=n>你的实盘</th><th class=n>决策T</th><th class=n>机械T</th><th class=n>不T</th></tr>{four}</table>
<p class=note>决策T 读本 skill(你的错题本规则 + 牧原数据画像) + 全体导师做 T 知识 + 盘中行情, 时段 0915 / 0933 / 10:33 / 13:03 / 14:33, 14:45 机械收口; 机械T 按近 30 日振幅挂高抛低吸各 1/3 底仓; 底仓 = 你最近一次导出的真实持股数, 你清仓后自动停。</p></div>
<div class=card><h2>决策T 最近决策</h2><table><tr><th>时段</th><th>动作</th><th>理由</th><th class=n>花费</th></tr>{decs}</table></div>
<div class=card><h2>skill 状态</h2><p>规则 {nrules} 条(来自你的错题本) · 日卡 {ncards} 张 · 近 30 日 最高涨幅中位 {esc(r30.group(1).strip()) if r30 else '—'} / 最大跌幅中位 {esc(r30.group(2).strip()) if r30 else '—'} / 日内区间中位 {esc(r30.group(3).strip()) if r30 else '—'}</p>
<p class=note>skill 目录: scripts/dfcf/snapshots/muyuan-skill/(SKILL.md / persona / workflows)</p></div>"""
    page = ("<!doctype html><html lang=zh><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>牧原 · 私有报告</title><style>"
            + CSS + "</style></head><body><div class=root><div class=w>" + body + "</div></div><script>" + JS.replace("__DATA__", data) + "</script></body></html>")
    OUT.write_text(page, encoding="utf-8")
    print(f"私有报告 → {OUT.relative_to(ROOT)}(你的实盘 T {len(real)} 天, 合计 {tot:+.0f} 元)")


CSS = """
.root{color-scheme:light;--bg:#f3f3f1;--card:#fcfcfb;--line:#e4e3df;--tx:#0b0b0b;--tx2:#52514e;--mu:#8a8985;--up:#d5292a;--dn:#13893b;--c1:#2a78d6;--c2:#eb6834;--c3:#1baf7a;--c4:#a8a7a2}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .root{color-scheme:dark;--bg:#121211;--card:#1a1a19;--line:#2e2e2c;--tx:#f0efec;--tx2:#c3c2b7;--mu:#8f8e86;--up:#f0605d;--dn:#3fb46a;--c1:#3987e5;--c2:#d95926;--c3:#199e70;--c4:#6d6c66}}
:root[data-theme="dark"] .root{color-scheme:dark;--bg:#121211;--card:#1a1a19;--line:#2e2e2c;--tx:#f0efec;--tx2:#c3c2b7;--mu:#8f8e86;--up:#f0605d;--dn:#3fb46a;--c1:#3987e5;--c2:#d95926;--c3:#199e70;--c4:#6d6c66}
*{box-sizing:border-box}body{margin:0}.root{font-family:"Microsoft YaHei",system-ui,sans-serif;background:var(--bg);color:var(--tx);min-height:100vh;padding:20px}.w{max-width:1100px;margin:0 auto}
header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}h1{font-size:20px;margin:0}h2{font-size:15px;margin:0 0 10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;margin-top:16px}
table{border-collapse:collapse;width:100%;font-size:12.5px}th{text-align:left;color:var(--tx2);border-bottom:1px solid var(--line);padding:6px 8px}td{border-bottom:1px solid var(--line);padding:5px 8px}
.n{text-align:right;font-variant-numeric:tabular-nums}.up{color:var(--up)}.dn{color:var(--dn)}.m{color:var(--mu);font-size:12px}.note{font-size:11px;color:var(--mu);margin-top:6px;line-height:1.6}
.bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
.btn{border:1px solid var(--line);background:var(--card);color:var(--tx2);border-radius:6px;padding:3px 10px;font-size:12px;cursor:pointer}.btn.on{border-color:var(--tx2);color:var(--tx);font-weight:600}
#chart{position:relative}#chart svg{display:block;width:100%;height:auto}
#tip{position:absolute;pointer-events:none;background:var(--card);border:1px solid var(--line);border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.15);padding:8px 10px;font-size:12px;display:none;z-index:2;min-width:190px}
#tip td{padding:1px 4px;border:0}#tip td.v{text-align:right;font-weight:700;font-variant-numeric:tabular-nums}
"""

JS = r"""
const D=__DATA__;const root=document.querySelector(".root"),css=n=>getComputedStyle(root).getPropertyValue(n).trim();
let MODE="yuan",RNG="all";
document.getElementById("theme").onclick=()=>{const h=document.documentElement,cur=h.dataset.theme||(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light");h.dataset.theme=cur==="dark"?"light":"dark";draw();};
document.querySelectorAll(".mode").forEach(b=>b.onclick=()=>{MODE=b.dataset.m;document.querySelectorAll(".mode").forEach(x=>x.classList.toggle("on",x===b));draw();});
document.querySelectorAll(".rng").forEach(b=>b.onclick=()=>{RNG=b.dataset.r;document.querySelectorAll(".rng").forEach(x=>x.classList.toggle("on",x===b));draw();});
const LINES=[["real","你的实盘","--c1",""],["dec","决策T(paper)","--c2",""],["mech","机械T(paper)","--c3","6 4"],["hold","不T / 只拿着","--c4","3 4"]];
function build(){
  let i0=RNG==="paper"?D.dates.findIndex(d=>d>=D.paper_start):0;if(i0<0)i0=D.dates.length;
  const ds=D.dates.slice(i0),cl=D.close.slice(i0),c0=i0>0?D.close[i0-1]:null,base=D.base_val||1,out={};
  for(const [k] of LINES){
    let cum=0,started=false;
    out[k]=ds.map((d,j)=>{
      const pr=c0?cl[j]/c0-1:cl[j]/cl[0]-1;   // 持有收益: 区间起点前一日收盘(全部区间 = 首日收盘)为 0
      if(k==="hold")return {v:MODE==="yuan"?0:pr,miss:false};
      const x=D.series[k][i0+j];
      if(x==null&&!started&&k!=="real")return null;
      started=true;cum+=x||0;
      return {v:MODE==="yuan"?cum:pr+cum/base,miss:x==null};
    });
  }
  return {ds,out};
}
function fmt(v){return MODE==="yuan"?(v>0?"+":v<0?"−":"")+Math.abs(v).toLocaleString("zh-CN",{maximumFractionDigits:0})+" 元":(v>0?"+":v<0?"−":"")+Math.abs(v*100).toFixed(2)+"%";}
function draw(){
  const host=document.getElementById("chart"),tip=document.getElementById("tip");host.querySelectorAll("svg,p").forEach(s=>s.remove());
  const {ds,out}=build();if(!ds.length){host.insertAdjacentHTML("afterbegin","<p class=m>这个区间还没有数据(paper 10/19 起跑)</p>");return;}
  const W=1060,H=340,L=78,R=120,T=16,B=34,ns="http://www.w3.org/2000/svg";
  const vals=Object.values(out).flat().filter(p=>p).map(p=>p.v);let lo=Math.min(0,...vals),hi=Math.max(0,...vals);if(hi-lo<1e-9){hi+=MODE==="yuan"?100:0.01;lo-=MODE==="yuan"?100:0.01;}const pad=(hi-lo)*.08;lo-=pad;hi+=pad;
  const x=i=>L+(ds.length===1?(W-L-R)/2:i*(W-L-R)/(ds.length-1)),y=v=>T+(hi-v)/(hi-lo)*(H-T-B);
  const svg=document.createElementNS(ns,"svg");svg.setAttribute("viewBox","0 0 "+W+" "+H);
  const el=(t,a)=>{const e=document.createElementNS(ns,t);for(const k in a)e.setAttribute(k,a[k]);svg.appendChild(e);return e;};
  for(let g=0;g<=4;g++){const v=lo+(hi-lo)*g/4;el("line",{x1:L,x2:W-R,y1:y(v),y2:y(v),stroke:css("--line")});const t=el("text",{x:L-6,y:y(v)+4,"text-anchor":"end","font-size":11,fill:css("--mu")});t.textContent=fmt(v);}
  el("line",{x1:L,x2:W-R,y1:y(0),y2:y(0),stroke:css("--mu"),"stroke-width":1.4});
  const step=Math.max(1,Math.ceil(ds.length/10));ds.forEach((d,i)=>{if(i%step&&i!==ds.length-1)return;const t=el("text",{x:x(i),y:H-12,"text-anchor":"middle","font-size":11,fill:css("--mu")});t.textContent=d.slice(5);});
  const ps=ds.indexOf(D.paper_start);if(ps>0){el("line",{x1:x(ps),x2:x(ps),y1:T,y2:H-B,stroke:css("--mu"),"stroke-dasharray":"2 3"});const t=el("text",{x:x(ps)+4,y:T+10,"font-size":11,fill:css("--mu")});t.textContent="paper 起跑";}
  for(const [k,name,c,dash] of LINES){
    const P=out[k].map((p,i)=>p?[x(i),y(p.v),p]:null).filter(Boolean);if(!P.length)continue;
    el("polyline",{points:P.map(p=>p[0]+","+p[1]).join(" "),fill:"none",stroke:css(c),"stroke-width":k==="real"?2.6:2,"stroke-dasharray":dash});
    if(k!=="hold")P.forEach(p=>el("circle",{cx:p[0],cy:p[1],r:3,fill:p[2].miss?css("--card"):css(c),stroke:css(c)}));
    const lp=P[P.length-1],t=el("text",{x:lp[0]+8,y:lp[1]+4,"font-size":12,fill:css(c),"font-weight":600});t.textContent=name;
  }
  const vl=el("line",{x1:0,x2:0,y1:T,y2:H-B,stroke:css("--tx2"),"stroke-width":1,opacity:0});
  svg.addEventListener("mousemove",ev=>{
    const r=svg.getBoundingClientRect(),mx=(ev.clientX-r.left)*W/r.width;let i=Math.round((mx-L)/((W-L-R)/Math.max(1,ds.length-1)));i=Math.max(0,Math.min(ds.length-1,i));
    vl.setAttribute("x1",x(i));vl.setAttribute("x2",x(i));vl.setAttribute("opacity",.5);
    tip.innerHTML="<b>"+ds[i]+"</b><table>"+LINES.map(([k,n,c])=>{const p=out[k][i];return "<tr><td style='color:"+css(c)+"'>■</td><td>"+n+(p&&p.miss?"(当天没贴单)":"")+"</td><td class=v>"+(p?fmt(p.v):"—")+"</td></tr>";}).join("")+"</table>";
    tip.style.display="block";const px=x(i)*r.width/W;tip.style.left=Math.min(px+14,r.width-210)+"px";tip.style.top="10px";
  });
  svg.addEventListener("mouseleave",()=>{tip.style.display="none";vl.setAttribute("opacity",0);});
  host.insertBefore(svg,tip);
}
draw();addEventListener("resize",draw);
"""


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
