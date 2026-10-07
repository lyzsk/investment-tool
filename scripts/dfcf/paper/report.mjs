// report.mjs — paper 人读视图(零 token 机械生成, 2026-10-03)
// 定位: matcher 账本(books/*.json)是给链/机器读的; 本脚本产出给人看的单文件 HTML:
//   净值曲线(内联 SVG, 无 CDN 可离线)+账本汇总+持仓+挂单+成交明细。
// 用法: node scripts/dfcf/paper/report.mjs [--out <路径>]   (matcher --eod 尾挂自动调, 失败仅 WARN)
// 产物: scripts/dfcf/paper/report.html; 出口 0=ok
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DIR = path.dirname(fileURLToPath(import.meta.url));
const BOOKS = path.join(DIR, "books");
const COLORS = { "A-taoge": "#d62728", "A-cb": "#ff7f0e", "A-qushitiange": "#e377c2", "A-lubenyuan": "#17becf", "A-tzzb": "#bcbd22", "B-taoge": "#1f77b4", "B-cb": "#2ca02c", "C-taoge": "#9467bd", "C-cb": "#8c564b" };
const INIT = 100000;

const outArg = process.argv.indexOf("--out");
const OUT = outArg > 0 ? process.argv[outArg + 1] : path.join(DIR, "report.html");

const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const pct = (x) => (x >= 0 ? "+" : "") + (x * 100).toFixed(2) + "%";

// ---- 读账本(10/7 用户令: 图上只留 A-xxx/B-xxx——旧导师个人书收编停用, C 线与杂书不进图) ----
const SHOW = new Set(["A-taoge", "A-cb", "A-qushitiange", "A-lubenyuan",
    "A-liuyiqing", "A-lianghuaxiaohao", "A-a658", "A-bianbenling", "A-xingjianye",
    "A-daxingdaxingdadangxing", "A-gaogailvfuli", "A-xuanqiucaijing", "A-stzhilang", "A-chong5000w",
    "B-taoge", "B-cb"]);
const books = fs.readdirSync(BOOKS).filter((f) => f.endsWith(".json") && !f.startsWith("_") && SHOW.has(f.replace(/\.json$/, ""))).map((f) => {
    const b = JSON.parse(fs.readFileSync(path.join(BOOKS, f), "utf8"));
    const mvCost = Object.values(b.positions || {}).reduce((s, p) => s + p.qty * p.cost, 0);
    if (!b.nav.length) b.nav = [{ date: new Date().toISOString().slice(0, 10), cash: b.cash, mv: +mvCost.toFixed(2), nav: +(b.cash + mvCost).toFixed(2), orders: 0, filled: 0, voided: 0 }];
    return b;
}).sort((a, b) => a.source.localeCompare(b.source));

const dates = [...new Set(books.flatMap((b) => b.nav.map((n) => n.date)))].sort();

// ---- 净值曲线 SVG(日期并集 x 轴, 缺日账本向前取平) ----
function chart() {
    const W = 960, H = 320, PL = 92, PR = 16, PT = 24, PB = 40;
    const allNavs = books.flatMap((b) => b.nav.map((n) => n.nav));
    const lo = Math.min(...allNavs, INIT) * 0.995, hi = Math.max(...allNavs, INIT) * 1.005;
    const X = (i) => PL + (dates.length < 2 ? 0 : (i / (dates.length - 1)) * (W - PL - PR));
    const Y = (v) => PT + (1 - (v - lo) / (hi - lo || 1)) * (H - PT - PB);
    const parts = [`<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" font-size="11">`,
        `<rect width="${W}" height="${H}" fill="#fafafa"/>`];
    for (let i = 0; i <= 4; i++) {  // y 网格+刻度(净值+百分比双标)
        const v = lo + ((hi - lo) * i) / 4, y = Y(v);
        parts.push(`<line x1="${PL}" y1="${y}" x2="${W - PR}" y2="${y}" stroke="#e0e0e0"/>`,
            `<text x="${PL - 6}" y="${y + 4}" text-anchor="end" fill="#666">${v.toFixed(0)} (${pct((v - INIT) / INIT)})</text>`);
    }
    parts.push(`<line x1="${PL}" y1="${Y(INIT)}" x2="${W - PR}" y2="${Y(INIT)}" stroke="#999" stroke-dasharray="5,4"/>`,
        `<text x="${W - PR}" y="${Y(INIT) - 4}" text-anchor="end" fill="#999">本金10万</text>`);
    dates.forEach((d, i) => { if (dates.length < 8 || i % Math.ceil(dates.length / 8) === 0) parts.push(`<text x="${X(i)}" y="${H - PB + 16}" text-anchor="middle" fill="#666">${d.slice(5)}</text>`); });
    for (const b of books) {
        const c = COLORS[b.source] || "#333";
        const ptsArr = dates.map((d, i) => {
            let nav = null;
            for (const n of b.nav) { if (n.date <= d) nav = n.nav; if (n.date === d) break; }
            return nav == null ? null : { i, d, nav };
        }).filter(Boolean);
        const pts = ptsArr.map((p) => `${X(p.i).toFixed(1)},${Y(p.nav).toFixed(1)}`);
        if (pts.length > 1) parts.push(`<polyline points="${pts.join(" ")}" fill="none" stroke="${c}" stroke-width="2"/>`);
        else if (pts.length === 1) parts.push(`<circle cx="${pts[0].split(",")[0]}" cy="${pts[0].split(",")[1]}" r="4" fill="${c}"/>`);
        // hover 探针: 每交易日一个透明圆点, title=日期/净值/收益率/当日现金+市值
        for (const p of ptsArr) {
            const day = b.nav.find((n) => n.date === p.d);
            const tip = `${b.source} ${p.d}\n净值 ${p.nav.toFixed(0)} (${pct((p.nav - INIT) / INIT)})` + (day ? `\n现金 ${day.cash.toFixed(0)} 市值 ${day.mv.toFixed(0)}\n成交${day.filled} 废单${day.voided}` : "");
            parts.push(`<circle cx="${X(p.i).toFixed(1)}" cy="${Y(p.nav).toFixed(1)}" r="7" fill="${c}" fill-opacity="0" stroke="none"><title>${esc(tip)}</title></circle>`);
        }
    }
    books.forEach((b, i) => { const c = COLORS[b.source] || "#333"; parts.push(`<rect x="${PL + i * 90}" y="6" width="10" height="10" fill="${c}"/><text x="${PL + i * 90 + 14}" y="15" fill="#333">${b.source}</text>`); });
    return parts.join("") + "</svg>";
}

// ---- 汇总指标 ----
function stats(b) {
    const last = b.nav[b.nav.length - 1];
    let peak = -Infinity, mdd = 0;
    for (const n of b.nav) { peak = Math.max(peak, n.nav); mdd = Math.min(mdd, (n.nav - peak) / peak); }
    const fills = b.trades.length, voids = b.orders.filter((o) => o.status === "void").length;
    return { last, ret: (last.nav - INIT) / INIT, mdd, fills, voids, voidRate: fills + voids ? voids / (fills + voids) : 0 };
}

const sumRows = books.map((b) => { const s = stats(b); return `<tr><td><b style="color:${COLORS[b.source]}">${b.source}</b></td><td>${s.last.date}</td><td>${s.last.nav.toFixed(0)}</td><td style="color:${s.ret >= 0 ? "#c00" : "#080"}">${pct(s.ret)}</td><td>${s.last.cash.toFixed(0)}</td><td>${s.last.mv.toFixed(0)}</td><td style="color:#080">${pct(s.mdd)}</td><td>${s.fills}</td><td>${s.voids}</td><td>${pct(s.voidRate)}</td></tr>`; }).join("\n");

const posRows = books.flatMap((b) => Object.entries(b.positions || {}).map(([c, p]) => `<tr><td>${b.source}</td><td>${c}</td><td>${p.qty}</td><td>${p.cost.toFixed(2)}</td><td>${(p.qty * p.cost).toFixed(0)}</td></tr>`)).join("\n") || `<tr><td colspan="5" style="color:#999">全部空仓</td></tr>`;

const openRows = books.flatMap((b) => b.orders.filter((o) => o.status === "open").map((o) => `<tr><td>${b.source}</td><td>${o.id}</td><td>${o.side}</td><td>${o.code}</td><td>${o.price}</td><td>${o.qty}</td><td>${esc(o.note)}</td></tr>`)).join("\n") || `<tr><td colspan="7" style="color:#999">无挂单</td></tr>`;

const tradeRows = books.flatMap((b) => b.trades.map((t) => ({ ...t, src: b.source }))).sort((a, b) => b.id.localeCompare(a.id))
    .map((t) => `<tr><td>${t.id}</td><td>${t.src}</td><td style="color:${t.side === "BUY" ? "#c00" : "#080"}">${t.side}</td><td>${t.code}</td><td>${t.price}</td><td>${t.qty}</td><td>${(t.fee ?? 0).toFixed(2)}</td><td>${esc(t.why)}</td></tr>`).join("\n") || `<tr><td colspan="8" style="color:#999">无成交</td></tr>`;

const html = `<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>paper 模拟盘报告 ${new Date().toISOString().slice(0, 16).replace("T", " ")}</title>
<style>body{font-family:"Microsoft YaHei",sans-serif;max-width:1000px;margin:20px auto;padding:0 12px;color:#222}h1{font-size:20px}h2{font-size:15px;border-left:4px solid #d62728;padding-left:8px;margin-top:28px}table{border-collapse:collapse;width:100%;font-size:12px}td,th{border:1px solid #ddd;padding:4px 6px;text-align:left}th{background:#f0f0f0}td:last-child{max-width:420px;word-break:break-all}</style></head><body>
<h1>paper 模拟盘(6 账本×10万) — ${new Date().toISOString().slice(0, 10)}</h1>
<h2>净值曲线</h2>${chart()}
<h2>账本汇总</h2><table><tr><th>账本</th><th>最新日期</th><th>净值</th><th>收益率</th><th>现金</th><th>市值</th><th>最大回撤</th><th>成交笔数</th><th>废单数</th><th>废单率</th></tr>${sumRows}</table>
<h2>当前持仓</h2><table><tr><th>账本</th><th>代码</th><th>数量</th><th>成本价</th><th>成本额</th></tr>${posRows}</table>
<h2>挂单中</h2><table><tr><th>账本</th><th>单号</th><th>方向</th><th>代码</th><th>价</th><th>量</th><th>条件/失效</th></tr>${openRows}</table>
<h2>成交明细(全部)</h2><table><tr><th>单号</th><th>账本</th><th>方向</th><th>代码</th><th>价</th><th>量</th><th>费用</th><th>原因</th></tr>${tradeRows}</table>
<p style="color:#999;font-size:11px">机械生成零 token: node scripts/dfcf/paper/report.mjs(matcher --eod 尾挂自动刷新)。收益率红涨绿跌; 废单率=决策质量度量。</p>
</body></html>`;
fs.writeFileSync(OUT, html);
console.log(`report.html 已生成: ${books.length} 账本, ${dates.length} 个交易日, ${OUT}`);
