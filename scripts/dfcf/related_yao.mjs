// related_yao.mjs — 持仓票的"关联妖股"自动挑选(零 token, 2026-10-15 用户令)
// 用户原话: 不是把某只妖股(金健米业)写死, 而是按当前阶段, 找和持仓票同板块/同概念、或有关联(包括"反向概念妖股大涨抽血")的妖股, 看它们对持仓票的影响。
// 做法(全机械):
//   ① 近期妖股池: 最近 20 个交易日 paper 事实包里的连板梯队(scan.json, 东财涨停池 zttj: lb=板数/days=统计天数)出现过 ≥3 板的票——
//      包括今天已经炸板/跌停的(退潮中的妖股也要看, 如 10/15 金健米业跌停)
//   ② 关联度两条腿: 概念重合(东财 F10 核心题材, 本地缓存 7 天) + 近 20 日日收益相关系数(日线归档, 缺档用 kline.mjs 补)
//      同族 = 共享行业细分/★精准概念; 同向带动 = 相关 ≥ +0.35; 跷跷板(抽血) = 相关 ≤ -0.35(样本 ≥15 日)
//   ③ 每只持仓挑: 同族最多 3 只(板数高的优先) + 统计关联最多 2 只 → scripts/dfcf/snapshots/live/related_<日>.json(隐私区, 含持仓)
//   live_watch.mjs 启动时读它, 把这些票加进盯盘并在 md 里单列一节
// 用法: node scripts/dfcf/related_yao.mjs [--date yyyy-MM-dd] [--stocks 002714,...]   (缺省持仓=snapshots/live/watchlist.txt)
// 请求: 只有 F10 概念(缓存未命中时)与日线补档两类, 都走统一请求层(限速+随机抖动), 单次运行一般 <40 次
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { gfetch } from "../lib/req_guard.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const arg = (k, d) => { const i = process.argv.indexOf("--" + k); return i > 0 ? process.argv[i + 1] : d; };
const DAY = arg("date", new Date().toLocaleDateString("sv-SE"));
const LIVE = path.join(ROOT, "scripts", "dfcf", "snapshots", "live");
const WL = path.join(LIVE, "watchlist.txt");
const HOLD = (arg("stocks") || (fs.existsSync(WL) ? fs.readFileSync(WL, "utf8") : "002714")).split(/[,\s]+/).filter((x) => /^\d{6}$/.test(x));
const F10_DIR = path.join(ROOT, "downloads", "f10");
const DAILY = path.join(ROOT, "downloads", "quotes", "daily");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = () => sleep(1500 + Math.random() * 2000);   // 随机间隔, 不打固定节拍
const readJson = (f, d = null) => { try { return JSON.parse(fs.readFileSync(f, "utf8")); } catch { return d; } };

// ① 近期妖股池(最近 10 个有事实包的交易日)
function yaoPool() {
    const fdir = path.join(ROOT, "scripts", "dfcf", "paper", "facts");
    const days = fs.readdirSync(fdir).filter((d) => /^\d{4}-\d\d-\d\d$/.test(d) && d <= DAY).sort().slice(-20);   // 20 个交易日窗口(10 日太短, 金健米业这类隔几天涨停一次的会漏)
    const pool = {};
    for (const d of days) {
        const slots = fs.readdirSync(path.join(fdir, d)).filter((s) => fs.existsSync(path.join(fdir, d, s, "scan.json"))).sort();
        if (!slots.length) continue;
        const raw = readJson(path.join(fdir, d, slots[slots.length - 1], "scan.json"), {})?.["连板梯队"]?.raw;
        for (const r of Array.isArray(raw) ? raw : []) {
            if (!/^\d{6}$/.test(String(r.code))) continue;
            const p = pool[r.code] || (pool[r.code] = { code: String(r.code), name: r.name, maxLb: 0, ztDays: 0, lastDay: d, hy: r.hy || "" });
            if (r.lb > p.maxLb) { p.maxLb = r.lb; p.days = r.days; }
            p.ztDays += 1; p.lastDay = d; p.name = r.name || p.name;
        }
    }
    // 妖股=10 日内最高 ≥3 板, 或 10 日内涨停 ≥3 天(反复涨停的高振幅票, 如金健米业, 不一定连板)
    return Object.values(pool).filter((p) => !HOLD.includes(p.code) && (p.maxLb >= 3 || p.ztDays >= 3));
}

// ② 概念(东财 F10 核心题材; 缓存 7 天)
async function concepts(code) {
    const f = path.join(F10_DIR, `${code}.json`);
    const c = readJson(f);
    if (c && Date.now() - Date.parse(c.at) < 7 * 86400e3) return c.boards;
    const mkt = /^[69]/.test(code) ? "SH" : /^[48]/.test(code) ? "BJ" : "SZ";
    try {
        await jitter();
        const r = await gfetch(`https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax?code=${mkt}${code}`,
            { headers: { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", Referer: "https://emweb.securities.eastmoney.com/" } });
        const j = await r.json();
        const boards = (j.ssbk || []).map((x) => ({ name: x.BOARD_NAME, precise: x.IS_PRECISE === "1" }));
        fs.mkdirSync(F10_DIR, { recursive: true });
        fs.writeFileSync(f, JSON.stringify({ at: new Date().toISOString(), code, boards }));
        return boards;
    } catch (e) {
        return c?.boards || [];   // 取不到=用旧缓存/空(只是少一条腿, 不阻断)
    }
}
// 行业层级标签(F10 前 3 个=证监会/东财行业链, 如 农林牧渔、养殖业、生猪养殖)+ ★精准概念; 风格/指数类标签不算关联
const NOISE = /板块$|风格|大盘|中盘|小盘|股通|融资融券|标准普尔|富时|MSCI|HS300|深证|上证|中证|深成|机构重仓|转债标的|AH股|券商金股|中报|年报|一季报|三季报|预增|预亏|首亏|高市净率|低价|昨日|热股|央国企改革|破净|微盘/;
function keyTags(boards) {
    const ind = boards.slice(0, 3).map((b) => b.name).filter((n) => !NOISE.test(n));
    const pre = boards.filter((b) => b.precise).map((b) => b.name);
    return { ind, pre, all: new Set([...ind, ...pre, ...boards.map((b) => b.name).filter((n) => !NOISE.test(n))]) };
}

// ③ 近 20 日日收益相关
function rets(code) {
    const k = readJson(path.join(DAILY, `${code}.json`))?.klines?.filter((x) => x.d <= DAY) || [];
    const m = {};
    for (let i = 1; i < k.length; i++) if (k[i - 1].c > 0 && k[i].c > 0) m[k[i].d] = k[i].c / k[i - 1].c - 1;
    return m;
}
function corr(a, b, n = 20) {
    const ds = Object.keys(a).filter((d) => d in b).sort().slice(-n);
    if (ds.length < 15) return { r: null, n: ds.length };
    const xs = ds.map((d) => a[d]), ys = ds.map((d) => b[d]);
    const mx = xs.reduce((s, x) => s + x, 0) / xs.length, my = ys.reduce((s, y) => s + y, 0) / ys.length;
    let sxy = 0, sxx = 0, syy = 0;
    for (let i = 0; i < xs.length; i++) { sxy += (xs[i] - mx) * (ys[i] - my); sxx += (xs[i] - mx) ** 2; syy += (ys[i] - my) ** 2; }
    return { r: sxx && syy ? Math.round(sxy / Math.sqrt(sxx * syy) * 100) / 100 : null, n: ds.length };
}

const pool = yaoPool();
const need = [...HOLD, ...pool.map((p) => p.code)].filter((c) => {
    const k = readJson(path.join(DAILY, `${c}.json`))?.klines;
    return !k || !k.length || k[k.length - 1].d < DAY.slice(0, 10) && k[k.length - 1].d < new Date(Date.now() - 4 * 86400e3).toLocaleDateString("sv-SE");
});
if (need.length) {   // 日线补档(kline.mjs 自带多源+请求层)
    try { execFileSync("node", [path.join(ROOT, "scripts", "quotes", "kline.mjs"), "--codes", need.join(",")], { cwd: ROOT, stdio: "ignore", timeout: 300_000, windowsHide: true }); } catch { /* 缺档=该票只剩概念一条腿 */ }
}
const out = { day: DAY, generatedAt: new Date().toISOString(), poolSize: pool.length, holdings: {} };
for (const h of HOLD) {
    const ht = keyTags(await concepts(h)), hr = rets(h);
    const rows = [];
    for (const p of pool) {
        const pt = keyTags(await concepts(p.code));
        const shared = [...pt.all].filter((t) => ht.all.has(t));
        const sameInd = pt.ind.slice(1).some((t) => ht.ind.slice(1).includes(t)) || (pt.ind[0] && pt.ind[0] === ht.ind[0]);   // 同行业(二三级细分优先, 一级如农林牧渔也算)
        const sameCon = pt.pre.some((t) => ht.pre.includes(t));   // 只共享★精准概念(乡村振兴这类宽概念噪音大, 单列"同概念", 排在同行业之后)
        const c = corr(hr, rets(p.code));
        const kind = sameInd ? "同行业" : sameCon ? "同概念" : c.r != null && c.r >= 0.35 ? "同向带动" : c.r != null && c.r <= -0.35 ? "跷跷板(抽血)" : null;
        if (kind) rows.push({ ...p, kind, shared, corr: c.r, corrN: c.n });
    }
    const byHeat = (a, b) => (b.lastDay > a.lastDay) - (b.lastDay < a.lastDay) || b.maxLb - a.maxLb || b.ztDays - a.ztDays;
    const fam = [...rows.filter((x) => x.kind === "同行业").sort(byHeat), ...rows.filter((x) => x.kind === "同概念").sort(byHeat)].slice(0, 3);
    const stat = rows.filter((x) => x.kind !== "同行业" && x.kind !== "同概念").sort((a, b) => Math.abs(b.corr) - Math.abs(a.corr)).slice(0, 2);
    out.holdings[h] = { tags: { ind: ht.ind, pre: ht.pre }, related: [...fam, ...stat] };
}
fs.mkdirSync(LIVE, { recursive: true });
fs.writeFileSync(path.join(LIVE, `related_${DAY}.json`), JSON.stringify(out, null, 1));
for (const [h, v] of Object.entries(out.holdings)) {
    console.log(`${h} 行业/精准概念: ${[...v.tags.ind, ...v.tags.pre].join("、")}`);
    for (const r of v.related) console.log(`  · ${r.kind} ${r.name}(${r.code}) 近 20 日最高 ${r.maxLb} 板/涨停 ${r.ztDays} 天(${r.lastDay}) 共享:${r.shared.slice(0, 4).join("/") || "-"} 20日相关 ${r.corr ?? "样本不足"}`);
    if (!v.related.length) console.log("  (近 10 日妖股池里没有与它关联的票)");
}
console.log(`妖股池 ${pool.length} 只 → ${path.join(LIVE, `related_${DAY}.json`)}`);
