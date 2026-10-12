// report.mjs — paper 人读视图(零 token 机械生成, 2026-10-03 建; 10/11 重写: 东财/同花顺式收益率走势)
// 定位: matcher 账本(books/*.json)给机器读; 本脚本产出给人看的单文件 HTML(内联 SVG+原生 JS, 无 CDN 可离线)。
// 10/11 用户令: ①主看收益率图, 像东财/同花顺 ②悬停某日=当日 11+3+对照 全部收益率(累计+当日) ③代码必带股票名 ④好读
// 设计(dataviz 规范): 累计收益率% 单轴; 0 轴加粗; 上证指数=灰色粗线基准; 14 skill 线=8 色×(实线/虚线)复合编码(>8 系列规范做法),
//   对照组=黑色点线; 竖线吸附交易日+浮窗按累计收益降序列全部; 点图例=只看选中(其余置灰); 每日数据质量标注(实盘/回放估算/as-of);
//   明暗两主题; 表格视图兜底(可读性+无障碍)。文本一律文本色, 红涨绿跌只用于数值且带 +/− 号(不靠颜色单通道)。
// 用法: node scripts/dfcf/paper/report.mjs [--out <路径>]   (matcher --eod 尾挂自动调, 失败仅 WARN; PAPER_ROOT=沙盒时读沙盒账本)
// 产物: <数据根>/report.html; 股票名缓存=scripts/dfcf/paper/names.json(首次联网查, 之后本地)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { ACCOUNTS, TABLE_ONLY, INIT, NAME } from "./accounts.mjs";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const DIR = process.env.PAPER_ROOT ? path.resolve(process.env.PAPER_ROOT) : SCRIPT_DIR;  // 10/10: as-of 沙盒
const ASOF = !!process.env.PAPER_ASOF || DIR !== SCRIPT_DIR;
const BOOKS = path.join(DIR, "books");
const KDIR = path.join(SCRIPT_DIR, "..", "..", "..", "downloads", "quotes", "daily");
const NAMES_FILE = path.join(SCRIPT_DIR, "names.json");
const outArg = process.argv.indexOf("--out");
const OUT = outArg > 0 ? process.argv[outArg + 1] : path.join(DIR, "report.html");

// ---- 账户元数据: 唯一真源=accounts.mjs(10/11 抽出, daily_digest 共用); 固定顺序=固定颜色槽, 上证=灰粗线 ----

// ---- 股票名: 本地缓存优先, 缺的联网补(snapshot 多源), 失败留空 ----
async function loadNames(codes) {
    let names = {};
    try { names = JSON.parse(fs.readFileSync(NAMES_FILE, "utf8")); } catch { /* 首次 */ }
    const miss = [...new Set(codes)].filter((c) => /^\d{6}$/.test(c) && !names[c]);
    if (miss.length) {
        try {
            const { snapOne } = await import("./snapshot.mjs");
            for (const c of miss) {
                const s = await snapOne(c);
                if (!s.error && s.name) names[c] = s.name;
                await new Promise((r) => setTimeout(r, 250));
            }
            fs.writeFileSync(NAMES_FILE, JSON.stringify(names, null, 1));
        } catch (e) { console.warn("WARN 股票名补查失败(不致命):", e.message); }
    }
    return names;
}

// ---- 日线(收盘价/指数): 读归档; 指数缺最近交易日时增量补档 ----
const readKl = (code) => { try { return JSON.parse(fs.readFileSync(path.join(KDIR, code.replace(".", "_") + ".json"), "utf8")).klines || []; } catch { return []; } };
async function indexBars(lastDate) {
    let k = readKl("1.000001");
    if (!k.length || k.at(-1).d < lastDate) {
        try { const { archiveDaily } = await import("../../quotes/kline.mjs"); await archiveDaily(["1.000001"], { dir: KDIR, gapMs: 200 }); k = readKl("1.000001"); }
        catch (e) { console.warn("WARN 上证指数补档失败(基准线缺最近几日):", e.message); }
    }
    return k;
}

// ---- 读账本 ----
const load = (src) => { try { return JSON.parse(fs.readFileSync(path.join(BOOKS, src + ".json"), "utf8")); } catch { return null; } };
const accounts = ACCOUNTS.map(([src, name, kind], slot) => ({ src, name, kind, slot, b: load(src) })).filter((a) => a.b);
const extras = TABLE_ONLY.map(([src, name, kind]) => ({ src, name, kind, b: load(src) })).filter((a) => a.b);
const all = [...accounts, ...extras];

// x 轴=账本 nav 日期并集 ∩ 交易日(md 文件名=Java 交易日 md 生成, 排除节假日 EOD 空跑行), 实盘自首跑日起
// 10/11: 10/8 前的 nav 行=建账占位/试跑期 10 万平值, 画进来会被误读成"那几天 0 收益"(实为无数据)
const LIVE_START = "2026-10-08";
const tradingDays = new Set();
for (const sub of fs.existsSync(path.resolve(SCRIPT_DIR, "../../../md")) ? fs.readdirSync(path.resolve(SCRIPT_DIR, "../../../md")) : []) {
    const p = path.resolve(SCRIPT_DIR, "../../../md", sub);
    if (fs.statSync(p).isDirectory()) for (const f of fs.readdirSync(p)) if (/^\d{4}-\d{2}-\d{2}\.md$/.test(f)) tradingDays.add(f.slice(0, 10));
}
const dates = [...new Set(accounts.flatMap((a) => a.b.nav.map((n) => n.date)))]
    .filter((d) => tradingDays.has(d) && (ASOF || d >= LIVE_START)).sort();

// ---- 曲线数据集(10/11: 实盘 + as-of 回放沙盒 两套, 页面内切换; 用户问"9/28-30 补跑 report 怎么没显示") ----
const SANDBOX = path.join(SCRIPT_DIR, "sandbox", "asof-0928");
async function chartData(dir, asof) {
    const ld = (src) => { try { return JSON.parse(fs.readFileSync(path.join(dir, "books", src + ".json"), "utf8")); } catch { return null; } };
    const accs = ACCOUNTS.map(([src, name, kind], slot) => ({ src, name, kind, slot, b: ld(src) })).filter((a) => a.b);
    // x 轴=nav 日期并集 ∩ 交易日; 实盘自首跑日起(之前=建账占位 10 万平值, 画进来会被误读成"0 收益")
    const ds = [...new Set(accs.flatMap((a) => a.b.nav.map((n) => n.date)))].filter((d) => tradingDays.has(d) && (asof || d >= LIVE_START)).sort();
    // 每日数据质量: 沙盒=as-of 回放; 当日成交含"回放"=回放估算; restate=重算; 否则实盘撮合
    const quality = Object.fromEntries(ds.map((d) => {
        if (asof) return [d, "as-of回放"];
        const replay = accs.some((a) => a.b.trades.some((t) => String(t.id).startsWith(d) && /回放/.test(t.why || "")));
        const restated = accs.some((a) => a.b.nav.some((n) => n.date === d && n.restated));
        return [d, replay ? "回放估算" : restated ? "重算" : "实盘撮合"];
    }));
    // 累计收益=nav/10万−1; 当日收益=nav/前一日 nav−1(首日相对 10 万); 账本未开户=无点, 中途缺=断点
    const series = (a) => {
        const byDate = Object.fromEntries(a.b.nav.map((n) => [n.date, n.nav]));
        let prev = INIT, started = false;
        return ds.map((d) => {
            if (byDate[d] === undefined) return started ? { cum: null, day: null } : null;
            started = true;
            const v = byDate[d], o = { nav: v, cum: v / INIT - 1, day: v / prev - 1 };
            prev = v;
            return o;
        });
    };
    let bench = null;   // 上证基准: 以首个图表日的前一交易日收盘为 0
    if (ds.length) {
        const k = await indexBars(ds.at(-1));
        const i0 = k.findIndex((x) => x.d >= ds[0]), base = i0 > 0 ? k[i0 - 1].c : null;
        if (base) {
            let prev = base;
            bench = ds.map((d) => { const r = k.find((x) => x.d === d); if (!r) return null; const o = { cum: r.c / base - 1, day: r.c / prev - 1 }; prev = r.c; return o; });
        }
    }
    const weekBase = (() => {   // "本周以来"基准=本周一前最后一个交易日(各账户同起点, 对照组 10/12 才上线也能公平比)
        if (!ds.length) return null;
        const d = new Date(ds.at(-1) + "T12:00:00"); d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
        const mon = d.toLocaleDateString("sv-SE"), i = ds.findLastIndex((x) => x < mon);
        return i >= 0 ? i : null;
    })();
    return { dates: ds, quality, asof, weekBase, bench: bench ? { name: "上证指数", pts: bench } : null,
        series: accs.map((a) => ({ src: a.src, name: a.name, kind: a.kind, slot: a.slot, pts: series(a) })) };
}

// ---- 10/11 用户令: 只出一个 report, 9/28-30 as-of 回放与 10/8 起实盘并成一条时间轴 ----
// 两本账独立(回放=沙盒, 实盘 10/8 重新 10 万开户), 累计收益按日收益连乘衔接: 实盘段 cum'=(1+回放末日cum)(1+实盘cum)−1;
// 当日收益各段原值; 上证/导师基准按合并后日期从真实序列重算(以首日前一交易日为 0)
const TZZB = path.resolve(SCRIPT_DIR, "../../../downloads/tzzb");
const ledgerOf = (src) => (src === "A-cb" ? "buchitudou0" : src.replace(/^A-/, ""));
function mentorPts(src, ds) {  // N2: 导师真人净值(tzzb index_list), 无账本(UP/对照组)=null → 页面退回上证
    let list;
    try { list = JSON.parse(fs.readFileSync(path.join(TZZB, ledgerOf(src), "nav_daily.json"), "utf8")).ex_data.index_list; } catch { return null; }
    const idx = Object.fromEntries(list.map((x) => [`${x.date.slice(0, 4)}-${x.date.slice(4, 6)}-${x.date.slice(6)}`, +x.index]));
    const before = Object.keys(idx).filter((d) => d < ds[0]).sort().at(-1);
    if (!before) return null;
    let prev = idx[before];
    const base = prev;
    const pts = ds.map((d) => { if (idx[d] === undefined) return null; const o = { cum: idx[d] / base - 1, day: idx[d] / prev - 1 }; prev = idx[d]; return o; });
    return pts.some((p) => p) ? pts : null;
}
async function mergedData(a, l) {
    const ds = a ? [...a.dates.filter((d) => !l.dates.includes(d)), ...l.dates].sort() : l.dates;
    const quality = { ...(a ? a.quality : {}), ...l.quality };
    const series = ACCOUNTS.map(([src, name, kind], slot) => {
        const pa = a?.series.find((s) => s.src === src)?.pts, pl = l.series.find((s) => s.src === src)?.pts;
        if (!pa && !pl) return null;
        const segA = a ? a.dates.filter((d) => !l.dates.includes(d)).map((d) => (pa ? pa[a.dates.indexOf(d)] : null)) : [];
        const lastA = [...segA].reverse().find((p) => p && p.cum != null)?.cum ?? 0;
        const segL = (pl || l.dates.map(() => null)).map((p) => (!p || p.cum == null ? p : { ...p, cum: (1 + lastA) * (1 + p.cum) - 1 }));
        return { src, name, kind, slot, pts: [...segA, ...segL], mentor: mentorPts(src, ds) };
    }).filter(Boolean);
    let bench = null;
    if (ds.length) {
        const k = await indexBars(ds.at(-1));
        const i0 = k.findIndex((x) => x.d >= ds[0]), base = i0 > 0 ? k[i0 - 1].c : null;
        if (base) { let prev = base; bench = ds.map((d) => { const r = k.find((x) => x.d === d); if (!r) return null; const o = { cum: r.c / base - 1, day: r.c / prev - 1 }; prev = r.c; return o; }); }
    }
    const weekBase = (() => {
        if (!ds.length) return null;
        const d = new Date(ds.at(-1) + "T12:00:00"); d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
        const mon = d.toLocaleDateString("sv-SE"), i = ds.findLastIndex((x) => x < mon);
        return i >= 0 ? i : null;
    })();
    return { dates: ds, quality, asof: false, weekBase, bench: bench ? { name: "上证指数", pts: bench } : null, series };
}

function stats(a) {
    const nav = a.b.nav;
    const last = nav.at(-1) || { nav: INIT, cash: a.b.cash, mv: 0, date: "-" };
    const prev = nav.length > 1 ? nav.at(-2).nav : INIT;
    let peak = INIT, mdd = 0;
    for (const n of nav) { peak = Math.max(peak, n.nav); mdd = Math.min(mdd, n.nav / peak - 1); }
    const fills = a.b.trades.length, voids = a.b.orders.filter((o) => o.status === "void").length;
    return { date: last.date, nav: last.nav, cum: last.nav / INIT - 1, day: nav.length ? last.nav / prev - 1 : 0, mdd,
        cashPct: last.nav ? (last.cash ?? a.b.cash) / last.nav : 1, pos: Object.keys(a.b.positions || {}).length,
        fills, voidRate: fills + voids ? voids / (fills + voids) : 0 };
}

const lastClose = (code) => { const k = readKl(code); return k.length ? k.at(-1) : null; };

async function main() {
    if (ASOF) {  // 10/11 用户令: 不出沙盒独立报告, 回放已并入主报告(matcher --eod 在沙盒尾挂调用时安静退出)
        console.log("as-of 沙盒不出独立报告(已并入主报告 scripts/dfcf/paper/report.html), 跳过");
        return;
    }
    const sbBooks = fs.existsSync(path.join(SANDBOX, "books")) ? Object.fromEntries(ACCOUNTS.map(([src]) => {
        try { return [src, JSON.parse(fs.readFileSync(path.join(SANDBOX, "books", src + ".json"), "utf8"))]; } catch { return [src, null]; }
    })) : {};
    const sbTrades = Object.entries(sbBooks).flatMap(([src, b]) => (b ? b.trades.map((t) => ({ ...t, who: NAME[src] + "(回放)" })) : []));
    const codes = [...all.flatMap((a) => [...Object.keys(a.b.positions || {}), ...a.b.trades.map((t) => t.code), ...a.b.orders.filter((o) => o.status === "open").map((o) => o.code)]),
        ...sbTrades.map((t) => t.code)];
    const names = await loadNames(codes);
    const nm = (c) => names[c] ? `${c} ${names[c]}` : c;

    const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    // 一套曲线数据集: 9/28-30 as-of 回放 + 10/8 起实盘 合并一条时间轴(mergedData)
    const merged = await mergedData(fs.existsSync(path.join(SANDBOX, "books")) ? await chartData(SANDBOX, true) : null, await chartData(DIR, false));
    const DATA = { generated: new Date().toLocaleString("sv-SE").slice(0, 16), live: merged, asof: null };
    // 拟人度表(similarity.mjs 产物; EOD 自动算前一交易日)
    let simRows = `<tr><td colspan="5" class="muted">尚无拟人度数据(导师真值次日才齐, 首个交易日收盘后生成)</td></tr>`, simUpd = "";
    try {
        const sim = JSON.parse(fs.readFileSync(path.join(DIR, "similarity.json"), "utf8"));
        simUpd = `截至 ${sim.updated.slice(0, 4)}-${sim.updated.slice(4, 6)}-${sim.updated.slice(6)}, 滚动 ${sim.window} 日`;
        const lv = (x) => (x == null ? "—" : (x * 100).toFixed(1) + "%");
        simRows = sim.summary.filter((x) => x.days).sort((a, b) => (b.delta ?? -9) - (a.delta ?? -9)).map((x) => {
            const nm = (accounts.find((a) => a.src === x.book) || {}).name || x.name;
            return `<tr><td>${esc(nm)}<span class="muted"> ${x.book}</span></td><td class="num"><b>${lv(x.comp)}</b></td><td class="num">${lv(x.ctrl)}</td>`
                + `<td class="num ${x.delta > 0 ? "up" : x.delta < 0 ? "dn" : ""}">${x.delta == null ? "—" : (x.delta >= 0 ? "+" : "−") + Math.abs(x.delta * 100).toFixed(1)}</td><td class="num">${x.days}</td></tr>`;
        }).join("") || simRows;
    } catch { /* 未生成 */ }

    const rows = all.map((a) => {  // 累计/回撤按合并时间轴(回放+实盘连乘), 与走势图一致; 当日/持仓/成交等=实盘账本现状
        const s = stats(a), m = merged.series.find((x) => x.src === a.src);
        const pts = m ? m.pts.filter((p) => p && p.cum != null) : [];
        if (pts.length) {
            let peak = 1, mdd = 0;
            for (const p of pts) { peak = Math.max(peak, 1 + p.cum); mdd = Math.min(mdd, (1 + p.cum) / peak - 1); }
            s.cum = pts.at(-1).cum; s.mdd = mdd;
        }
        return { a, s };
    }).sort((x, y) => y.s.cum - x.s.cum);
    const sign = (x, d = 2) => (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x * 100).toFixed(d) + "%";
    const cls = (x) => (x > 0 ? "up" : x < 0 ? "dn" : "");
    const sumRows = rows.map(({ a, s }, i) => `<tr><td class="num">${i + 1}</td><td><span class="sw" data-slot="${a.slot ?? ""}" data-src="${a.src}"></span>${esc(a.name)}<span class="muted"> ${a.src}</span></td><td>${a.kind}</td>`
        + `<td class="num ${cls(s.cum)}"><b>${sign(s.cum)}</b></td><td class="num ${cls(s.day)}">${sign(s.day)}</td><td class="num">${s.nav.toFixed(0)}</td>`
        + `<td class="num dn2">${s.mdd ? sign(s.mdd) : "0.00%"}</td><td class="num">${(s.cashPct * 100).toFixed(0)}%</td><td class="num">${s.pos}</td><td class="num">${s.fills}</td><td class="num">${(s.voidRate * 100).toFixed(0)}%</td><td class="muted">${s.date}</td></tr>`).join("");

    const posRows = all.flatMap((a) => Object.entries(a.b.positions || {}).map(([c, p]) => {
        const lc = lastClose(c), px = lc?.c, pnl = px ? px / p.cost - 1 : null;
        return `<tr><td>${esc(a.name)}</td><td>${esc(nm(c))}</td><td class="num">${p.qty}</td><td class="num">${p.cost.toFixed(2)}</td>`
            + `<td class="num">${px ?? "-"}<span class="muted"> ${lc ? lc.d.slice(5) : ""}</span></td><td class="num ${pnl == null ? "" : cls(pnl)}">${pnl == null ? "-" : sign(pnl)}</td><td class="num">${(p.qty * (px || p.cost)).toFixed(0)}</td></tr>`;
    })).join("") || `<tr><td colspan="7" class="muted">全部空仓</td></tr>`;

    const openRows = all.flatMap((a) => a.b.orders.filter((o) => o.status === "open").map((o) => `<tr><td>${esc(a.name)}</td><td>${o.date}</td><td class="${o.side === "BUY" ? "up" : "dn"}">${o.side === "BUY" ? "买" : "卖"}</td><td>${esc(nm(o.code))}</td><td class="num">${o.price}</td><td class="num">${o.qty}</td><td class="muted small">${esc((o.note || "").slice(0, 120))}</td></tr>`)).join("") || `<tr><td colspan="7" class="muted">无挂单</td></tr>`;

    const trades = [...all.flatMap((a) => a.b.trades.map((t) => ({ ...t, who: a.name }))), ...sbTrades].sort((x, y) => String(y.id).localeCompare(String(x.id)));
    const tradeRows = trades.map((t) => `<tr><td>${String(t.id).slice(0, 10)}</td><td>${esc(t.who)}</td><td class="${t.side === "BUY" ? "up" : "dn"}">${t.side === "BUY" ? "买" : "卖"}</td><td>${esc(nm(t.code))}</td><td class="num">${t.price}</td><td class="num">${t.qty}</td><td class="num">${(+t.price * t.qty).toFixed(0)}</td><td class="muted small">${esc(String(t.why || "").slice(0, 80))}</td></tr>`).join("") || `<tr><td colspan="8" class="muted">无成交</td></tr>`;

    const dataJson = JSON.stringify(DATA).replace(/</g, "\\u003c");
    const fill = { TITLE: ASOF ? "paper 模拟盘 · as-of 回放(沙盒)" : "paper 模拟盘 · 收益率走势", GEN: DATA.generated,
        NACC: String(DATA.live.series.length), NDAY: String(DATA.live.dates.length), SUM: sumRows, POS: posRows, OPEN: openRows,
        TRADES: tradeRows, NTRADE: String(trades.length), DATA: dataJson, SIM: simRows, SIMUPD: simUpd };
    const html = TEMPLATE.replace(/%%(\w+)%%/g, (m, k) => (k in fill ? fill[k] : m));  // 函数式替换: 数据里的 $ 不被当替换模式
    fs.writeFileSync(OUT, html);
    console.log(`report.html 已生成: ${merged.series.length} 条收益线, ${merged.dates.length} 个交易日(含回放 ${merged.dates.filter((d) => merged.quality[d] === "as-of回放").length} 日), ${OUT}`);
}

const TEMPLATE = `<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%%TITLE%%</title>
<style>
.viz-root{color-scheme:light;--surface-0:#f3f3f1;--surface-1:#fcfcfb;--line:#e4e3df;--text-primary:#0b0b0b;--text-secondary:#52514e;--text-muted:#8a8985;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--s7:#6250d6;--s8:#e34948;--ctrl:#0b0b0b;--bench:#a8a7a2;--up:#d5292a;--dn:#13893b;--zero:#8a8985}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;--surface-0:#121211;--surface-1:#1a1a19;--line:#2e2e2c;--text-primary:#f0efec;--text-secondary:#c3c2b7;--text-muted:#8f8e86;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#e66767;--ctrl:#f0efec;--bench:#6d6c66;--up:#f0605d;--dn:#3fb46a;--zero:#8f8e86}}
:root[data-theme="dark"] .viz-root{color-scheme:dark;--surface-0:#121211;--surface-1:#1a1a19;--line:#2e2e2c;--text-primary:#f0efec;--text-secondary:#c3c2b7;--text-muted:#8f8e86;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#e66767;--ctrl:#f0efec;--bench:#6d6c66;--up:#f0605d;--dn:#3fb46a;--zero:#8f8e86}
*{box-sizing:border-box}body{margin:0}
.viz-root{font-family:"Microsoft YaHei","PingFang SC",system-ui,sans-serif;background:var(--surface-0);color:var(--text-primary);min-height:100vh;padding:20px}
.wrap{max-width:1280px;margin:0 auto}
header{display:flex;align-items:baseline;gap:16px;flex-wrap:wrap}h1{font-size:20px;margin:0}
.muted{color:var(--text-muted)}.small{font-size:11px}
.card{background:var(--surface-1);border:1px solid var(--line);border-radius:8px;padding:16px;margin-top:16px}
h2{font-size:15px;margin:0 0 10px}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
.chip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:14px;padding:3px 10px;font-size:12px;cursor:pointer;background:var(--surface-1);color:var(--text-secondary);user-select:none}
button.btn.on{border-color:var(--text-secondary);color:var(--text-primary);font-weight:600}
.chip.on{border-color:var(--text-secondary);color:var(--text-primary);font-weight:600}.chip.dim{opacity:.45}
.chip svg{flex:none}
button.btn:disabled{opacity:.4;cursor:not-allowed}button.btn{border:1px solid var(--line);background:var(--surface-1);color:var(--text-secondary);border-radius:6px;padding:3px 10px;font-size:12px;cursor:pointer}
#chart{position:relative}#chart svg{display:block;width:100%;height:auto;touch-action:none}
#tip{position:absolute;pointer-events:none;background:var(--surface-1);border:1px solid var(--line);border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.12);padding:8px 10px;font-size:12px;min-width:250px;display:none;z-index:2}
#tip .hd{display:flex;justify-content:space-between;gap:12px;margin-bottom:4px;color:var(--text-secondary)}
#tip table{border-collapse:collapse;width:100%}#tip td{padding:1px 4px;white-space:nowrap}#tip td.v{text-align:right;font-weight:700;font-variant-numeric:tabular-nums}
#tip td.d{text-align:right;color:var(--text-secondary);font-variant-numeric:tabular-nums}#tip tr.f td{background:color-mix(in srgb,var(--text-muted) 14%,transparent)}
.up{color:var(--up)}.dn{color:var(--dn)}.dn2{color:var(--text-secondary)}
table.t{border-collapse:collapse;width:100%;font-size:12.5px}table.t th{text-align:left;font-weight:600;color:var(--text-secondary);border-bottom:1px solid var(--line);padding:6px 8px;position:sticky;top:0;background:var(--surface-1)}
table.t td{border-bottom:1px solid var(--line);padding:5px 8px}table.t td.num,table.t th.num{text-align:right;font-variant-numeric:tabular-nums}
table.t tr:hover td{background:color-mix(in srgb,var(--text-muted) 10%,transparent)}
.sw{display:inline-block;width:18px;height:0;border-top:2px solid;margin-right:6px;vertical-align:middle}
.scroll{max-height:420px;overflow:auto}
details summary{cursor:pointer;color:var(--text-secondary);font-size:13px;margin-top:4px}
.qbadge{font-size:10px;border-radius:3px;padding:0 4px;border:1px solid var(--line);color:var(--text-secondary)}
.legend-note{font-size:11px;color:var(--text-muted);margin-top:6px;line-height:1.6}
</style></head>
<body><div class="viz-root"><div class="wrap">
<header><h1>%%TITLE%%</h1><span class="muted">生成 %%GEN%% · %%NACC%% 条收益线 · %%NDAY%% 个交易日</span>
<span style="flex:1"></span><button class="btn" id="theme">切换明暗</button></header>

<div class="card">
<h2><span id="mtitle">累计收益率走势</span> <span class="muted small">(本金各 10 万; 悬停看当日全部账户, 点图例只看选中)</span></h2>
<div class="toolbar"><span class="muted small">时间轴: 9/28–9/30=as-of 回放(沙盒账本) · 10/8 起=实盘; 两段账本独立(实盘 10/8 重新 10 万开户), 累计收益按日收益连乘衔接</span></div>
<div class="toolbar"><span class="muted small">区间</span><button class="btn rng on" data-r="all">全部</button><button class="btn rng" data-r="week">本周以来</button><span class="muted small" style="margin-left:12px">口径</span><button class="btn mode on" data-m="abs">绝对收益</button><button class="btn mode" data-m="ctrl">相对对照组</button><button class="btn mode" data-m="bench">相对上证</button><button class="btn mode" data-m="mentor">相对导师真人</button><span class="muted small" id="mnote"></span></div>
<div class="toolbar" id="legend"></div>
<div id="chart"><div id="tip"></div></div>
<div class="legend-note">线型: 实线=前 8 个账户, 虚线=后 6 个(同色序); 黑点线=对照组(裸模型基准, skill 贡献=该线−对照线); 灰粗线=上证指数(同期基准)。
日期下方标签=当日数据来源: <b>实盘撮合</b>=盘中每分钟按实时价成交 / <b>回放估算</b>=事后按日线高低价补记(偏乐观, 分钟级时序不可考) / <b>重算</b>=EOD 被 --restate 修正过。</div>
<details><summary>收益率数据表(逐日)</summary><div class="scroll" id="dtable"></div></details>
</div>

<div class="card"><h2>拟人度 <span class="muted small">(模拟操作 vs 导师真人当日持仓/操作; 对照组=裸模型同口径; 差值=skill 真实贡献; %%SIMUPD%%)</span></h2><div class="scroll"><table class="t"><tr><th>导师</th><th class="num">拟人度</th><th class="num">对照组</th><th class="num">skill−对照(百分点)</th><th class="num">有效天数</th></tr>%%SIM%%</table></div></div>

<div class="card"><h2>账户排行(按累计收益)</h2><div class="scroll"><table class="t"><tr><th class="num">#</th><th>账户</th><th>类型</th><th class="num">累计收益</th><th class="num">最新一日</th><th class="num">净值</th><th class="num">最大回撤</th><th class="num">现金占比</th><th class="num">持仓数</th><th class="num">成交笔数</th><th class="num">废单率</th><th>截至</th></tr>%%SUM%%</table></div></div>

<div class="card"><h2>当前持仓</h2><div class="scroll"><table class="t"><tr><th>账户</th><th>股票</th><th class="num">数量</th><th class="num">成本</th><th class="num">最近收盘</th><th class="num">浮盈亏</th><th class="num">市值</th></tr>%%POS%%</table></div></div>

<div class="card"><h2>挂单中</h2><div class="scroll"><table class="t"><tr><th>账户</th><th>日期</th><th>方向</th><th>股票</th><th class="num">价格</th><th class="num">数量</th><th>条件/备注</th></tr>%%OPEN%%</table></div></div>

<div class="card"><details><summary>成交明细(%%NTRADE%% 笔, 点开)</summary><div class="scroll"><table class="t"><tr><th>日期</th><th>账户</th><th>方向</th><th>股票</th><th class="num">价格</th><th class="num">数量</th><th class="num">金额</th><th>原因</th></tr>%%TRADES%%</table></div></details></div>
<p class="muted small">机械生成零 token: node scripts/dfcf/paper/report.mjs(matcher --eod 收盘后自动刷新)。数值红涨绿跌并带 +/− 号。</p>
</div></div>
<script>
const DS=%%DATA%%;let D=DS.live;
const root=document.querySelector(".viz-root"),css=n=>getComputedStyle(root).getPropertyValue(n).trim();
document.getElementById("theme").onclick=()=>{const h=document.documentElement,cur=h.dataset.theme||(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light");h.dataset.theme=cur==="dark"?"light":"dark";draw();};
const colorOf=s=>s.kind==="对照"?css("--ctrl"):css("--s"+((s.slot%8)+1));
const dashOf=s=>s.kind==="对照"?"2 4":(s.slot>=8?"7 4":"");
const pct=(x,d=2)=>x==null?"—":(x>0?"+":x<0?"−":"")+Math.abs(x*100).toFixed(d)+"%";
const sgnCls=x=>x>0?"up":x<0?"dn":"";
const focus=new Set();let hoverSrc=null;
let all=[];
function initAll(){all=[...D.series,...(D.bench?[{src:"BENCH",name:D.bench.name,kind:"基准",pts:D.bench.pts}]:[])];all.forEach(s=>{s.raw=s.pts;s.hide=false;});}
initAll();
// 区间(全部/本周以来) × 口径(绝对/相对对照组/相对上证) 统一重算: 以基准日 k 收盘为 0 重新起算(k=-1 即本金 10 万)
// 10/11 超额口径(书 ch2/ch5/ch8: 只做多的选股要看相对基准的超额): 超额=(1+账户累计)/(1+基准累计)−1, 自基准首个有数日起算;
//   基准线本身在该口径下恒为 0, 不画(0 轴即基准)
let RNG="all",MODE="abs";
const MODES={abs:["累计收益率走势","累计","当日"],ctrl:["相对对照组的超额收益","超额","当日超额"],bench:["相对上证指数的超额收益","超额","当日超额"],mentor:["相对导师真人的超额收益","超额","当日超额"]};
const refOf=m=>m==="ctrl"?all.find(s=>s.kind==="对照"):m==="bench"?all.find(s=>s.kind==="基准"):null;
const hasData=s=>!!s&&s.raw.some(p=>p&&p.cum!=null);
const rebase=(raw,k)=>{const b=k>=0&&raw[k]&&raw[k].cum!=null?raw[k].cum:0;return raw.map((p,i)=>i<k?null:(!p||p.cum==null)?p:{...p,cum:(1+p.cum)/(1+b)-1});};
function recompute(){
 const ref=MODE==="mentor"?null:refOf(MODE);let k=RNG==="week"&&D.weekBase!=null?D.weekBase:-1;
 if(ref)k=Math.max(k,ref.raw.findIndex(p=>p&&p.cum!=null)-1);
 const rp=ref?rebase(ref.raw,k):null,bn=all.find(s=>s.kind==="基准");
 const rel=(p0,r0)=>p0.map((p,i)=>{const r=r0?r0[i]:null;if(!p||p.cum==null)return p;if(!r||r.cum==null)return {cum:null,day:null};
   return {...p,cum:(1+p.cum)/(1+r.cum)-1,day:p.day!=null&&r.day!=null?(1+p.day)/(1+r.day)-1:null};});
 // N2 相对导师真人: 每条线对各自导师 tzzb 净值(s.mentor); 无真人账本(UP/对照组)退回上证; 基准线本身不画
 all.forEach(s=>{const p0=rebase(s.raw,k);
  if(MODE==="mentor"){s.hide=s.kind==="基准";const mr=s.mentor||(bn?bn.raw:null);s.pts=s.hide?p0:rel(p0,mr?rebase(mr,k):null);return;}
  s.hide=!!ref&&s===ref;s.pts=!ref?p0:rel(p0,rp);});
 document.getElementById("mtitle").textContent=MODES[MODE][0];
 document.getElementById("mnote").textContent=MODE==="abs"?"":MODE==="mentor"?"超额=(1+账户累计)/(1+导师真人累计)−1; 导师=tzzb 账本净值, 无真人账本的 UP/对照组用上证; 0 轴=导师本人, 线在 0 上方=跑赢导师":"超额=(1+账户累计)/(1+"+(MODE==="ctrl"?"对照组":"上证")+"累计)−1"+(ref&&ref.raw.findIndex(p=>p&&p.cum!=null)>0?", 自"+(MODE==="ctrl"?"对照组":"上证")+"首个有数日起算":"")+"; 0 轴=基准本身, 线在 0 上方=跑赢";
 document.querySelectorAll(".rng").forEach(x=>x.classList.toggle("on",x.dataset.r===RNG));
 document.querySelectorAll(".mode").forEach(x=>{x.classList.toggle("on",x.dataset.m===MODE);const ok=x.dataset.m==="abs"||(x.dataset.m==="mentor"?D.series.some(s=>s.mentor)||!!D.bench:hasData(refOf(x.dataset.m)));x.disabled=!ok;x.title=ok?"":"该数据集里基准还没有数据";});
 buildLegend();buildTable();draw();}
function setRange(r){RNG=r;recompute();}
document.querySelectorAll(".rng").forEach(x=>x.onclick=()=>setRange(x.dataset.r));
document.querySelectorAll(".mode").forEach(x=>x.onclick=()=>{if(x.disabled)return;MODE=x.dataset.m;recompute();});
const isOn=s=>!focus.size||focus.has(s.src);
const strokeOf=s=>s.kind==="基准"?css("--bench"):colorOf(s);
// 图例(色样=线型样张, 身份不靠颜色单通道)
const lg=document.getElementById("legend");
function sample(s){const ns="http://www.w3.org/2000/svg",v=document.createElementNS(ns,"svg");v.setAttribute("width","22");v.setAttribute("height","8");const l=document.createElementNS(ns,"line");
l.setAttribute("x1","1");l.setAttribute("x2","21");l.setAttribute("y1","4");l.setAttribute("y2","4");l.setAttribute("stroke",strokeOf(s));l.setAttribute("stroke-width",s.kind==="基准"?"4":"2");if(s.kind!=="基准"&&dashOf(s))l.setAttribute("stroke-dasharray",dashOf(s).replace(" 4"," 3"));v.appendChild(l);return v;}
function buildLegend(){lg.textContent="";for(const s of all){if(s.hide)continue;const c=document.createElement("span");c.className="chip"+(focus.has(s.src)?" on":"")+(focus.size&&!focus.has(s.src)?" dim":"");c.appendChild(sample(s));c.appendChild(document.createTextNode(s.name));
c.onclick=()=>{focus.has(s.src)?focus.delete(s.src):focus.add(s.src);buildLegend();draw();};c.onmouseenter=()=>{hoverSrc=s.src;draw();};c.onmouseleave=()=>{hoverSrc=null;draw();};lg.appendChild(c);}
const r=document.createElement("button");r.className="btn";r.textContent="显示全部";r.onclick=()=>{focus.clear();buildLegend();draw();};lg.appendChild(r);
document.querySelectorAll(".sw[data-src]").forEach(e=>{const s=all.find(x=>x.src===e.dataset.src);if(s){e.style.borderTopColor=strokeOf(s);if(dashOf(s))e.style.borderTopStyle="dashed";}});}
// 主图
const chart=document.getElementById("chart"),tip=document.getElementById("tip");let svg,geo;
function draw(){
 const W=Math.max(640,chart.clientWidth||1200),H=Math.round(Math.min(560,Math.max(380,W*0.42))),PL=64,PR=158,PT=16,PB=58;
 const n=D.dates.length,vals=all.filter(s=>!s.hide).flatMap(s=>s.pts.filter(p=>p&&p.cum!=null).map(p=>p.cum));
 let lo=Math.min(0,...vals),hi=Math.max(0,...vals);const padv=Math.max((hi-lo)*0.08,0.005);lo-=padv;hi+=padv;
 const stepRaw=(hi-lo)/6,mag=Math.pow(10,Math.floor(Math.log10(stepRaw))),step=[1,2,2.5,5,10].map(m=>m*mag).find(x=>x>=stepRaw);lo=Math.floor(lo/step)*step;hi=Math.ceil(hi/step)*step;
 const X=i=>PL+(n<2?(W-PL-PR)/2:i*(W-PL-PR)/(n-1)),Y=v=>PT+(1-(v-lo)/(hi-lo))*(H-PT-PB);geo={X,Y,PL,PR,PT,PB,W,H,n};
 const ns="http://www.w3.org/2000/svg",el=(t,a)=>{const e=document.createElementNS(ns,t);for(const k in a)e.setAttribute(k,a[k]);return e;};
 if(svg)svg.remove();svg=el("svg",{viewBox:"0 0 "+W+" "+H,role:"img","aria-label":"各账户累计收益率走势"});chart.insertBefore(svg,tip);
 for(let v=lo;v<=hi+1e-9;v+=step){const y=Y(v),z=Math.abs(v)<1e-9;svg.appendChild(el("line",{x1:PL,x2:W-PR,y1:y,y2:y,stroke:z?css("--zero"):css("--line"),"stroke-width":z?1.5:1}));
  const t=el("text",{x:PL-8,y:y+4,"text-anchor":"end","font-size":11,fill:css("--text-muted")});t.textContent=(v>0?"+":v<0?"−":"")+Math.abs(v*100).toFixed(step<0.01?1:0)+"%";svg.appendChild(t);}
 const every=Math.max(1,Math.ceil(n/12));
 D.dates.forEach((d,i)=>{if(i%every&&i!==n-1)return;const t=el("text",{x:X(i),y:H-PB+16,"text-anchor":"middle","font-size":11,fill:css("--text-secondary")});t.textContent=d.slice(5);svg.appendChild(t);
  const q=D.quality[d];if(q&&q!=="实盘撮合"){const b=el("text",{x:X(i),y:H-PB+30,"text-anchor":"middle","font-size":9.5,fill:css("--text-muted")});b.textContent=q;svg.appendChild(b);}});
 const order=[...all].sort((a,b)=>(isOn(a)?1:0)-(isOn(b)?1:0)||(a.src===hoverSrc)-(b.src===hoverSrc));
 const labels=[];
 for(const s of order){if(s.hide)continue;const on=isOn(s),hl=s.src===hoverSrc;let d="",pen=false;s.pts.forEach((p,i)=>{if(!p||p.cum==null){pen=false;return;}d+=(pen?"L":"M")+X(i).toFixed(1)+" "+Y(p.cum).toFixed(1);pen=true;});
  if(!d)continue;const bench=s.kind==="基准";
  svg.appendChild(el("path",{d,fill:"none",stroke:on?strokeOf(s):css("--line"),"stroke-width":bench?4:(hl?3.2:(s.kind==="对照"?2.4:2)),"stroke-dasharray":bench?"":dashOf(s),"stroke-linejoin":"round","stroke-linecap":"round",opacity:bench?(on?0.55:0.3):1}));
  const li=s.pts.map((p,i)=>p&&p.cum!=null?i:-1).filter(i=>i>=0).pop();if(on&&li!=null)labels.push({s,y:Y(s.pts[li].cum),x:X(li),v:s.pts[li].cum});}
 // 线尾直标(防重叠: 排序后最小间距 13px; 太多时只标 前3/后3/对照/基准/选中)
 labels.sort((a,b)=>a.y-b.y);const many=labels.length>10;const keep=new Set();const byV=[...labels].sort((a,b)=>b.v-a.v);
 if(many){byV.slice(0,3).forEach(l=>keep.add(l));byV.slice(-3).forEach(l=>keep.add(l));labels.forEach(l=>{if(l.s.kind==="对照"||l.s.kind==="基准"||focus.has(l.s.src)||l.s.src===hoverSrc)keep.add(l);});}
 let lastY=-1e9;for(const l of labels){if(many&&!keep.has(l))continue;const y=Math.max(l.y,lastY+13);lastY=y;const t=el("text",{x:W-PR+8,y:y+4,"font-size":11,fill:css("--text-primary")});t.textContent=l.s.name+" "+pct(l.v,1);svg.appendChild(t);
  svg.appendChild(el("line",{x1:l.x+2,x2:W-PR+5,y1:l.y,y2:y,stroke:css("--text-muted"),"stroke-width":0.6}));}
 const hair=el("line",{y1:PT,y2:H-PB,stroke:css("--text-muted"),"stroke-width":1,"stroke-dasharray":"3 3",visibility:"hidden"});svg.appendChild(hair);
 const hit=el("rect",{x:PL-10,y:0,width:W-PL-PR+20,height:H,fill:"transparent"});svg.appendChild(hit);
 const show=(ev)=>{const r=svg.getBoundingClientRect(),sx=(ev.clientX-r.left)*W/r.width;let i=n<2?0:Math.round((sx-PL)/((W-PL-PR)/(n-1)));i=Math.max(0,Math.min(n-1,i));
  hair.setAttribute("x1",X(i));hair.setAttribute("x2",X(i));hair.setAttribute("visibility","visible");
  const rows=all.filter(s=>!s.hide).map(s=>({s,p:s.pts[i]})).filter(o=>o.p&&o.p.cum!=null).sort((a,b)=>b.p.cum-a.p.cum);
  tip.textContent="";const hd=document.createElement("div");hd.className="hd";const a=document.createElement("b");a.textContent=D.dates[i];const q=document.createElement("span");q.className="qbadge";q.textContent=D.quality[D.dates[i]]||"";hd.append(a,q);tip.appendChild(hd);
  const tb=document.createElement("table"),th=document.createElement("tr");["","账户",MODES[MODE][1],MODES[MODE][2]].forEach((x,j)=>{const c=document.createElement("td");c.textContent=x;c.className=j>1?"d":"";c.style.color="var(--text-muted)";th.appendChild(c);});tb.appendChild(th);
  for(const {s,p} of rows){const tr=document.createElement("tr");if(focus.has(s.src)||s.src===hoverSrc)tr.className="f";const c0=document.createElement("td");c0.appendChild(sample(s));const c1=document.createElement("td");c1.textContent=s.name;
   const c2=document.createElement("td");c2.className="v "+sgnCls(p.cum);c2.textContent=pct(p.cum);const c3=document.createElement("td");c3.className="d "+sgnCls(p.day);c3.textContent=pct(p.day);tr.append(c0,c1,c2,c3);tb.appendChild(tr);}
  tip.appendChild(tb);tip.style.display="block";const cw=chart.clientWidth,tw=tip.offsetWidth,px=X(i)*r.width/W;tip.style.left=(px+16+tw>cw?px-16-tw:px+16)+"px";tip.style.top="8px";};
 hit.addEventListener("pointermove",show);hit.addEventListener("pointerdown",show);hit.addEventListener("pointerleave",()=>{tip.style.display="none";hair.setAttribute("visibility","hidden");});
}
// 数据表视图
function buildTable(){const t=document.createElement("table");t.className="t";const h=document.createElement("tr");["日期","来源",...all.filter(s=>!s.hide).map(s=>s.name)].forEach(x=>{const c=document.createElement("th");c.textContent=x;h.appendChild(c);});t.appendChild(h);
 D.dates.forEach((d,i)=>{const r=document.createElement("tr");const c0=document.createElement("td");c0.textContent=d;const c1=document.createElement("td");c1.textContent=D.quality[d]||"";r.append(c0,c1);
  all.filter(s=>!s.hide).forEach(s=>{const p=s.pts[i],c=document.createElement("td");c.className="num "+(p?sgnCls(p.cum):"");c.textContent=p&&p.cum!=null?pct(p.cum)+" ("+pct(p.day)+")":"—";r.appendChild(c);});t.appendChild(r);});
 const host=document.getElementById("dtable");host.textContent="";host.appendChild(t);}
recompute();addEventListener("resize",()=>draw());
</script></body></html>`;

main().catch((e) => { console.error("report 生成失败:", e); process.exit(1); });
