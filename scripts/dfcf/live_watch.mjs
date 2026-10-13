// live_watch.mjs — 盘中盯盘(2026-10-12 建; 同日用户令: 不只盯持仓, 要看指数/方向/板块, 与 skill 链"先市况→再方向→后个股"同理; 项目目的=短线)
// 三层, **不另起行情请求, 复用 paper 线**(用户 10/12: 整个项目一体, 高内聚低耦合): 状态落 scripts/dfcf/snapshots/live/<日期>.json + .md(隐私区)
//   ① 大盘: 读 paper 当日最新时段 facts/<日期>/<时段>/facts.md 的「市场扫描」段(scan.mjs 每个时段现拉: 涨跌幅榜/连板梯队/跌停/板块), 零额外请求;
//      指数暂由本脚本每分钟 1 次腾讯 qt(snapshot.mjs 尚不支持指数代码; TODO: 收盘后把指数并进 snapshot.mjs 共享缓存, 本处改调它)
//   ② 方向: 同上 facts 的板块榜 + 当日链 02 共识方向(results/*_chain/live-<日>/02_analysis.md, 15 分钟重读)
//   ③ 个股: --codes 持仓/关注票, 每只自建 1 分钟线/均价/量能节奏(相对昨日同进度)/行情类型(趋势上涨/震荡/趋势下跌)
// 信号(去重, 落 alerts): 个股 突破昨高/跌破昨低/日内新高/站回或跌破均价/量能翻倍/类型切换; 大盘 指数翻红翻绿/涨停家数骤变 —— 即"挂单该动"的触发点
// Claude 被问挂单时直接读 .md, 一分钟内出方案; 交易日盘中跑, 午休空转, --until 到点退出
// 用法: node scripts/dfcf/live_watch.mjs --stocks 002714[,600xxx] [--every 15] [--until 1501] [--once]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { snapMany } from "./paper/snapshot.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const arg = (k, d) => { const i = process.argv.indexOf("--" + k); return i > 0 ? process.argv[i + 1] : d; };
const CODES = arg("stocks", "002714")   // 不能叫 --codes: import snapshot.mjs 时它的 CLI 见 --codes 就会执行并退出
.split(",").filter(Boolean);
const EVERY = +arg("every", 15) * 1000;
const UNTIL = +arg("until", 1501);
const day = new Date().toLocaleDateString("sv-SE");
const OUT = path.join(ROOT, "scripts", "dfcf", "snapshots", "live");
fs.mkdirSync(OUT, { recursive: true });
const fJson = path.join(OUT, `${day}.json`), fMd = path.join(OUT, `${day}.md`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const hm = () => { const d = new Date(); return d.getHours() * 100 + d.getMinutes(); };
const r2 = (x) => Math.round(x * 100) / 100;
const UA = { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" };
const INDEXES = [["sh000001", "上证"], ["sz399001", "深成"], ["sz399006", "创业板"], ["sh000688", "科创50"], ["sh000300", "沪深300"]];

async function get(url, headers = {}, enc = "utf8") {
    const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), 8000);
    try {
        const r = await fetch(url, { headers: { ...UA, ...headers }, signal: ctl.signal });
        if (!r.ok) throw new Error("HTTP " + r.status);
        return new TextDecoder(enc).decode(await r.arrayBuffer());
    } finally { clearTimeout(t); }
}
// 指数: 腾讯 qt 带前缀批量(snapshot.mjs 只认 6 位个股代码, 000001 会撞平安银行)
async function indexes() {
    const t = await get(`https://qt.gtimg.cn/q=${INDEXES.map((x) => x[0]).join(",")}`, { Referer: "https://gu.qq.com/" }, "gbk");
    const out = [];
    for (const [sym, name] of INDEXES) {
        const m = t.match(new RegExp(`v_${sym}="([^"]*)"`));
        if (!m) continue;
        const f = m[1].split("~");
        const vol = +f[6], amt = +f[37] * 10000;
        out.push({ sym, name, last: +f[3], pct: +f[32], high: +f[33], low: +f[34], amtYi: r2(amt / 1e8) });
    }
    return out;
}
// paper 线最新时段的市场扫描(scan.mjs 产物, facts.mjs 拼进 facts.md); 返回 {slot, md}
function paperScan() {
    const dir = path.join(ROOT, "scripts", "dfcf", "paper", "facts", day);
    if (!fs.existsSync(dir)) return null;
    const slots = fs.readdirSync(dir).filter((x) => /^\d{4}$/.test(x) && fs.existsSync(path.join(dir, x, "facts.md"))).sort();
    if (!slots.length) return null;
    const slot = slots[slots.length - 1], txt = fs.readFileSync(path.join(dir, slot, "facts.md"), "utf8");
    const i = txt.indexOf("# 市场扫描");
    if (i < 0) return { slot, md: "(该时段 facts 无市场扫描段)" };
    const sec = txt.slice(i).split("\n");
    const pick = (name, n) => { const k = sec.findIndex((l) => l.startsWith("## " + name)); return k < 0 ? [] : sec.slice(k, k + n).filter((l) => !l.startsWith("来源")); };
    return { slot, md: [sec[0], ...pick("连板梯队", 8), ...pick("跌停榜", 2), ...pick("板块榜", 5), ...pick("涨跌幅榜", 8)].join("\n") };
}
// 当日链 02 共识方向(15 条链各自的 directions, 按出现次数排序)
function chainConsensus() {
    const d8 = day.replaceAll("-", ""), cnt = {}, states = {};
    for (const dir of fs.readdirSync(path.join(ROOT, "results")).filter((x) => x.endsWith("_chain"))) {
        const f = path.join(ROOT, "results", dir, `live-${d8}`, "02_analysis.md");
        if (!fs.existsSync(f)) continue;
        const blocks = fs.readFileSync(f, "utf8").match(/`{3}contract\s*\n([\s\S]*?)`{3}/g) || [];
        try {
            const c = JSON.parse(blocks[blocks.length - 1].replace(/`{3}contract\s*\n|`{3}/g, ""));
            states[c.market_state] = (states[c.market_state] || 0) + 1;
            for (const x of c.directions || []) { const k = String(x).split(/[(（/·]/)[0].trim(); cnt[k] = (cnt[k] || 0) + 1; }
        } catch { /* 坏契约跳过 */ }
    }
    return { states, directions: Object.entries(cnt).sort((a, b) => b[1] - a[1]).slice(0, 10) };
}
// 个股 30 日股性 + 昨日(归档 downloads/quotes/daily/<code>.json; 缺档=只给实时)
function stockStats(code) {
    const f = path.join(ROOT, "downloads", "quotes", "daily", `${code}.json`);
    if (!fs.existsSync(f)) return null;
    const k = JSON.parse(fs.readFileSync(f, "utf8")).klines.filter((x) => x.d < day);
    const w = k.slice(-31), q = (xs, p) => { const s = [...xs].sort((a, b) => a - b); return r2(s[Math.round(p * (s.length - 1))]); };
    const amp = [], oh = [], ol = [];
    for (let i = 1; i < w.length; i++) { const p = w[i - 1].c, c = w[i]; amp.push((c.h - c.l) / p * 100); oh.push((c.h / c.o - 1) * 100); ol.push((c.l / c.o - 1) * 100); }
    const last = k[k.length - 1];
    return { prevHigh: last.h, prevLow: last.l, prevVol: last.v, amp50: q(amp, .5), amp75: q(amp, .75), oh50: q(oh, .5), oh75: q(oh, .75), ol50: q(ol, .5), ol25: q(ol, .25) };
}
function elapsed() {
    const d = new Date(), m = d.getHours() * 60 + d.getMinutes() + d.getSeconds() / 60;
    return Math.min(Math.max(m - 570, 0), 120) + Math.min(Math.max(m - 780, 0), 120);
}

const state = { day, stocks: {}, alerts: [], market: {}, consensus: chainConsensus(), updated: null };
let consensusAt = Date.now();
if (fs.existsSync(fJson)) { try { const old = JSON.parse(fs.readFileSync(fJson, "utf8")); state.stocks = old.stocks || {}; state.alerts = old.alerts || []; state.market = old.market || {}; } catch { /* 重建 */ } }
const stats = Object.fromEntries(CODES.map((c) => [c, stockStats(c)]));
const seen = new Set(state.alerts.map((a) => a.key));
const alert = (key, msg) => { if (seen.has(key)) return; seen.add(key); const a = { t: new Date().toTimeString().slice(0, 8), key, msg }; state.alerts.push(a); console.log(`[${a.t}] ⚠ ${msg}`); };
let slowAt = 0, idxAt = 0;

async function tick() {
    const now = Date.now();
    if (now - idxAt >= 60_000) {   // ① 指数: 每分钟 1 次(暂未进共享缓存, 见文件头 TODO)
        idxAt = now;
        try {
            const idx = await indexes();
            for (const x of idx) {
                const prev = (state.market.indexes || []).find((y) => y.sym === x.sym);
                if (prev && Math.sign(prev.pct) !== Math.sign(x.pct) && Math.abs(x.pct) >= 0.1) alert(`idx-${x.sym}-${x.pct > 0 ? "红" : "绿"}-${hm()}`, `${x.name}翻${x.pct > 0 ? "红" : "绿"} ${x.pct}%`);
            }
            state.market.indexes = idx;
        } catch (e) { state.market.indexErr = e.message; }
    }
    if (now - slowAt > 60_000) {   // ② paper 线市场扫描 + 链共识(只读文件, 零请求)
        slowAt = now;
        state.market.scan = paperScan();
        if (now - consensusAt > 900_000) { state.consensus = chainConsensus(); consensusAt = now; }
    }
    // ③ 个股
    const snaps = await snapMany(CODES, 0);
    const el = elapsed();
    for (const code of CODES) {
        const s = snaps[code], st = stats[code];
        if (!s || s.error || !(s.last > 0)) continue;
        const o = state.stocks[code] || (state.stocks[code] = { bars: {} });
        const t = (s.qtTime || "").slice(8, 12) || String(hm()).padStart(4, "0"), key = t.slice(0, 2) + ":" + t.slice(2, 4);
        const b = o.bars[key] || (o.bars[key] = { o: s.last, h: s.last, l: s.last, c: s.last, v0: s.vol });
        b.h = Math.max(b.h, s.last); b.l = Math.min(b.l, s.last); b.c = s.last; b.v1 = s.vol;
        const vwap = s.vol > 0 && s.amt > 0 ? r2(s.amt / (s.vol * 100)) : null;
        const pace = el > 0 && st?.prevVol ? r2(s.vol / (st.prevVol * el / 240)) : null;
        const idxUp = (state.market.indexes || []).filter((x) => x.pct > 0.3).length, idxDn = (state.market.indexes || []).filter((x) => x.pct < -0.3).length;
        const atHigh = s.last >= s.high - 0.02, atLow = s.last <= s.low + 0.02;
        let regime = "震荡";
        if (atHigh && vwap && s.last > vwap && ((pace || 0) >= 1.8 || idxUp >= 3)) regime = "趋势上涨";
        else if (atLow && vwap && s.last < vwap && ((pace || 0) >= 1.8 || idxDn >= 3)) regime = "趋势下跌";
        const nm = s.name;
        if (o.regime && regime !== o.regime) alert(`${code}-rg-${regime}-${key}`, `${nm} 行情类型 ${o.regime}→${regime}(${s.last}, 均价 ${vwap}, 量能 ${pace} 倍)`);
        if (st && s.high > st.prevHigh) alert(`${code}-brkH`, `${nm} 突破昨高 ${st.prevHigh} → 卖档上移/末档改跟随`);
        if (st && s.low < st.prevLow) alert(`${code}-brkL`, `${nm} 跌破昨低 ${st.prevLow} → 接回档下移`);
        if (o.lastHigh && s.high > o.lastHigh + 0.001) alert(`${code}-nh-${s.high}`, `${nm} 日内新高 ${s.high}`);
        if (o.vwapSide && vwap && (s.last > vwap ? "上" : "下") !== o.vwapSide) alert(`${code}-vw-${key}`, `${nm} ${s.last > vwap ? "站回" : "跌破"}均价 ${vwap}`);
        if ((pace || 0) >= 2) alert(`${code}-pace2`, `${nm} 量能 ${pace} 倍(昨日同进度 2 倍+)`);
        Object.assign(o, { regime, lastHigh: s.high, vwapSide: vwap ? (s.last > vwap ? "上" : "下") : null,
            quote: { name: nm, last: s.last, prevClose: s.prevClose, open: s.open, high: s.high, low: s.low, pct: s.pct, vol: s.vol, vwap, pace, src: s.src } });
    }
    state.updated = new Date().toTimeString().slice(0, 8);
    const tmp = fJson + ".tmp"; fs.writeFileSync(tmp, JSON.stringify(state)); fs.renameSync(tmp, fJson);
    fs.writeFileSync(fMd, render() + "\n");
}

function render() {
    const m = state.market, L = [`# 盘中盯盘 ${day} 更新 ${state.updated}`, "", "## ① 大盘"];
    L.push((m.indexes || []).map((x) => `${x.name} ${x.last}(${x.pct}%, 额${x.amtYi}亿)`).join(" | ") || `指数失败 ${m.indexErr || ""}`);
    L.push("", "## ② 方向");
    L.push(m.scan ? `(paper 线 ${m.scan.slot} 时段 scan.mjs)\n${m.scan.md}` : "(paper 当日 facts 尚无)");
    const c = state.consensus;
    L.push(`链 02 共识(各链最新时段, 盘中子链会覆盖盘前版): 市况 ${Object.entries(c.states).map(([k, v]) => `${k}${v}`).join("/")} | 方向 ${c.directions.map(([k, v]) => `${k}×${v}`).join(" ")}`);
    L.push("", "## ③ 个股");
    for (const code of CODES) {
        const o = state.stocks[code], st = stats[code];
        if (!o?.quote) continue;
        const q = o.quote, keys = Object.keys(o.bars).sort().slice(-12);
        L.push(`**${q.name}(${code})** ${q.last}(${q.pct}%) 开 ${q.open} 高 ${q.high} 低 ${q.low} | 均价 ${q.vwap} | 量能 ${q.pace} 倍 | **类型: ${o.regime}**`);
        if (st) L.push(`  股性30日: 振幅中位 ${st.amp50}% P75 ${st.amp75}% | 开→高 中位 +${st.oh50}% P75 +${st.oh75}% | 开→低 中位 ${st.ol50}% P25 ${st.ol25}% | 昨高 ${st.prevHigh} 昨低 ${st.prevLow}`);
        L.push(`  近 12 分钟: ${keys.map((k) => { const x = o.bars[k]; return `${k} ${x.c}(${x.v1 && x.v0 ? x.v1 - x.v0 : "?"}手)`; }).join(" | ")}`);
    }
    L.push("", "## 信号(最近 10 条)", ...state.alerts.slice(-10).map((a) => `- ${a.t} ${a.msg}`));
    return L.join("\n");
}

if (process.argv.includes("--once")) { await tick(); console.log(render()); process.exit(0); }
console.log(`live_watch 持仓/关注 ${CODES.join(",")} 每 ${EVERY / 1000}s → ${fMd}`);
while (hm() < UNTIL) {
    const h = hm();
    if ((h >= 915 && h < 1131) || (h >= 1259 && h <= 1500)) {
        try { await tick(); } catch (e) { console.log(`tick 失败: ${e.message}`); }
    }
    await sleep(EVERY);
}
console.log("收盘, 退出");
