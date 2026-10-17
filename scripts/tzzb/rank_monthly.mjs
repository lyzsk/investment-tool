// rank_monthly.mjs — 同花顺投资账本 比赛月榜 / 候选轻量抓取 传输层(10/17 agent③ 建)
// 只管"发请求+落文件+断点续传", **不碰任何 _guard 文件**: 额度/熔断/互斥/时间窗/计数回写 全由 Python 包装 scripts/tzzb/rank_screen.py
//   (经 scripts/tzzb/tzzb_guard.py, 以正式 downloads/tzzb/_guard 为唯一真源) 负责。直接手跑本脚本 = 绕过正式额度, 禁止(无 --i-am-wrapped 会拒跑)。
// 请求一律走浏览器代发(browser/browser_transport.mjs; 直连 10/14 起会被页面反爬 403), 节流 ≈0.5 次/秒 + 抖动。
// 模式:
//   --probe                       1 次请求探测(月榜第 1 页), 判断是否解封
//   --overall --keys a,b          总榜(无 month 参数) → downloads/tzzb/_ranks/<key>.json(格式同 fetch_tzzb --rank; 已有文件跳过, --refresh 重拉)
//   --monthly --keys a,b [--from 202501] [--to 202610] [--max-pages 20]
//                                 月榜 → downloads/tzzb/_ranks_monthly/<key>/<YYYYMM>.json; 断点续传(完整的过去月份跳过; 当月 20h 内抓过跳过)
//   --light <cands.json> [--root downloads/tzzb_cand] [--pc-pages 4]
//                                 候选轻量: profit_rate_by_share(日净值) + position_change_by_share 前 N 页 → <root>/<ledger>/ 同名文件
//   公共: --max-req N(本次最多发 N 次, 含开页估算 3 次) --deadline <epoch ms>(到点停) --dry(不联网, 只列计划)
// 输出: 末行 "JSON:{...}" = {mode, requests, blocked, done, pending, errors}; 退出码 0=做完 3=额度/时限停(有待续) 5=Nginx 403(疑封) 1=其他失败
import fs from "fs";
import path from "path";

const A = process.argv;
const arg = (k, d = null) => (A.includes(k) ? A[A.indexOf(k) + 1] : d);
const has = (k) => A.includes(k);
const BASE = "https://capital.hexin.cn/caishen_httpserver/direct/caishen_fund/community_share/v1";
const RANKS = path.resolve("downloads/tzzb/_ranks");
const MONTHLY = path.resolve("downloads/tzzb/_ranks_monthly");
const MAX_REQ = +arg("--max-req", "0");
const DEADLINE = +arg("--deadline", "0");
const DRY = has("--dry");
const PAGE_OPEN_COST = 3;   // 开账本页时页面自己会发几次接口(估算, 从严计入)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = () => sleep(2000 * (0.75 + Math.random() * 0.5));
const ym = (d = new Date()) => `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}`;
const S = { mode: null, requests: 0, blocked: false, done: [], pending: 0, errors: [] };
const finish = (code) => { console.log(`JSON:${JSON.stringify(S)}`); process.exit(code); };
class Blocked extends Error {}
class OutOfBudget extends Error {}

if (!DRY && !has("--i-am-wrapped") && !has("--selftest")) {
    console.error("rank_monthly.mjs 只能经 scripts/tzzb/rank_screen.py 调用(它负责共用正式额度/熔断); 手动看计划用 --dry");
    process.exit(1);
}

let T = null;
async function transport(host) {
    if (T) return T;
    if (MAX_REQ && S.requests + PAGE_OPEN_COST > MAX_REQ) throw new OutOfBudget("额度不够开页");
    const { BrowserTransport } = await import("./browser/browser_transport.mjs");
    S.requests += PAGE_OPEN_COST;
    T = await BrowserTransport.open(host);
    return T;
}
process.on("exit", () => { try { T?.ed?.kill(); } catch { /* ignore */ } });

// 一次请求: 403 Nginx → Blocked; -100 限流 → 退避重试; JSON 坏 → 重试; 额度/时限 → OutOfBudget
async function get(host, url, tries = 3) {
    for (let i = 0; ; i++) {
        if (MAX_REQ && S.requests >= MAX_REQ) throw new OutOfBudget(`本次额度 ${MAX_REQ} 用完`);
        if (DEADLINE && Date.now() >= DEADLINE) throw new OutOfBudget("到时限");
        const t = await transport(host);
        S.requests++;
        const x = await t.get(url);
        if (/nginx forbidden/i.test(x.text || "") || x.status === 403) throw new Blocked(`${x.status} ${String(x.text).replace(/<[^>]+>/g, " ").trim().slice(0, 120)}`);
        let j = null;
        try { j = JSON.parse(x.text); } catch { /* 下面重试 */ }
        const rl = j && (j.status_code === -100 || j.error === -100 || String(j.error_code) === "-100");
        if (j && !rl) return j;
        if (i >= tries - 1) throw new Error(rl ? "连续限流 -100" : `非 JSON(status ${x.status}): ${String(x.text).slice(0, 80)}`);
        await sleep(3000 * (i + 1));
    }
}

function hostPage() {
    // 任意一个正式账本分享页即可加载页面反爬脚本(令牌按页面生成, 与请求的比赛 key 无关)
    const L = JSON.parse(fs.readFileSync("scripts/tzzb/tzzb_ledgers.json", "utf8"));
    const h = L.find((l) => l.key && l.user_key);
    return { key: h.key, user_key: h.user_key };
}

const monthlyUrl = (key, month, page) => `${BASE}/match_ranking_by_share?key=${key}&page=${page}&count=50&month=${month}&sort_type=monthly_profit&sort_order=1&group_type=simple`;
const overallUrl = (key, page) => `${BASE}/match_ranking_by_share?key=${key}&page=${page}&count=50`;

function monthsFor(key) {
    const from = arg("--from"), to = arg("--to", ym());
    let start = from;
    if (!start) {
        try {
            const rows = JSON.parse(fs.readFileSync(path.join(RANKS, `${key}.json`), "utf8")).rows || [];
            const e = rows.map((r) => String(r.enter_date || "")).filter((s) => /^\d{4}-\d\d/.test(s)).sort()[0];
            start = e ? e.slice(0, 7).replace("-", "") : "202501";
        } catch { start = "202501"; }
        if (start < "202501") start = "202501";
    }
    const out = [];
    for (let y = +start.slice(0, 4), m = +start.slice(4); `${y}${String(m).padStart(2, "0")}` <= to; m === 12 ? (y++, m = 1) : m++) out.push(`${y}${String(m).padStart(2, "0")}`);
    return out;
}

function monthlyState(key, month) {
    const f = path.join(MONTHLY, key, `${month}.json`);
    try {
        const j = JSON.parse(fs.readFileSync(f, "utf8"));
        const fresh = month < ym() || Date.now() - Date.parse(j.fetched_at) < 20 * 36e5;
        return { f, j, skip: j.complete && fresh };
    } catch { return { f, j: null, skip: false }; }
}

async function pullPages(host, urlOf, prev, maxPages, save) {
    const rows = prev?.rows || [];
    let page = (prev?.pages || 0) + 1, complete = false;
    for (; page <= maxPages; page++) {
        const j = await get(host, urlOf(page));
        const list = j?.ex_data?.rank_list;
        if (!Array.isArray(list)) throw new Error(`返回无 rank_list: ${JSON.stringify(j).slice(0, 120)}`);
        rows.push(...list);
        save(rows, page, list.length < 50);
        if (list.length < 50) { complete = true; break; }
        await jitter();
    }
    if (!complete) save(rows, Math.min(page, maxPages), true);   // 到页数上限也算完整(榜单接口本身最多约 20 页)
    return rows;
}

async function modeMonthly(keys) {
    const host = hostPage(), maxPages = +arg("--max-pages", "20");
    const plan = [];
    for (const k of keys) for (const m of monthsFor(k)) { const s = monthlyState(k, m); if (!s.skip) plan.push({ k, m, s }); }
    S.pending = plan.length;
    console.log(`[monthly] 待抓 ${plan.length} 个(比赛×月); 估算请求 ≤${plan.length * maxPages}(每个最多 ${maxPages} 页)`);
    if (DRY) { for (const p of plan.slice(0, 40)) console.log(`  ${p.k} ${p.m}${p.s.j ? `(续 p${p.s.j.pages + 1})` : ""}`); return; }
    for (const { k, m, s } of plan) {
        fs.mkdirSync(path.dirname(s.f), { recursive: true });
        const save = (rows, pages, complete) => fs.writeFileSync(s.f, JSON.stringify({ match_key: k, month: m, params: "sort_type=monthly_profit&sort_order=1&group_type=simple", fetched_at: new Date().toISOString(), pages, complete, rows }, null, 1));
        const prev = s.j && !s.j.complete ? s.j : null;
        const rows = await pullPages(host, (p) => monthlyUrl(k, m, p), prev, maxPages, save);
        S.done.push(`${k}/${m}:${rows.length}`); S.pending--;
        console.log(`[monthly] ${k} ${m}: ${rows.length} 行`);
        await jitter();
    }
}

async function modeOverall(keys) {
    const host = hostPage();
    const todo = keys.filter((k) => has("--refresh") || !fs.existsSync(path.join(RANKS, `${k}.json`)));
    S.pending = todo.length;
    console.log(`[overall] 待抓 ${todo.length}/${keys.length}: ${todo.join(",")}`);
    if (DRY) return;
    fs.mkdirSync(RANKS, { recursive: true });
    for (const k of todo) {
        const tmp = path.join(RANKS, `${k}.partial.json`);
        let prev = null;
        try { prev = JSON.parse(fs.readFileSync(tmp, "utf8")); } catch { /* 无 */ }
        const save = (rows, pages, complete) => fs.writeFileSync(complete ? path.join(RANKS, `${k}.json`) : tmp, JSON.stringify({ match_key: k, fetched_at: new Date().toISOString(), pages, rows }, null, 1));
        const rows = await pullPages(host, (p) => overallUrl(k, p), prev, 20, save);
        try { fs.unlinkSync(tmp); } catch { /* */ }
        S.done.push(`${k}:${rows.length}`); S.pending--;
        console.log(`[overall] ${k}: ${rows.length} 行`);
        await jitter();
    }
}

async function modeLight(file) {
    const root = path.resolve(arg("--root", "downloads/tzzb_cand")), pcPages = +arg("--pc-pages", "4");
    const cands = JSON.parse(fs.readFileSync(file, "utf8"));
    const today = new Date().toLocaleDateString("sv-SE");
    const todo = cands.filter((c) => {
        try { return JSON.parse(fs.readFileSync(path.join(root, c.ledger, "light_state.json"), "utf8")).date !== today; } catch { return true; }
    });
    S.pending = todo.length;
    console.log(`[light] 待抓 ${todo.length}/${cands.length} 人; 估算请求 ≤${todo.length * (1 + pcPages)}`);
    if (DRY) { for (const c of todo.slice(0, 40)) console.log(`  ${c.ledger} ${c.name} ${c.key}/${c.user_key}`); return; }
    for (const c of todo) {
        const out = path.join(root, c.ledger);
        fs.mkdirSync(out, { recursive: true });
        const host = { key: c.key, user_key: c.user_key };
        const q = `key=${c.key}&user_key=${c.user_key}`;
        const nav = await get(host, `${BASE}/profit_rate_by_share?${q}`);
        fs.writeFileSync(path.join(out, "nav_daily.json"), JSON.stringify(nav, null, 1));
        let pages = 0, rows = 0, maxCount = null;
        for (let p = 1; p <= pcPages; p++) {
            await jitter();
            const j = await get(host, `${BASE}/position_change_by_share?${q}&page=${p}`);
            const l = j?.ex_data?.change_list || [];
            maxCount = j?.ex_data?.max_count ?? maxCount;
            fs.writeFileSync(path.join(out, `position_change_p${p}.json`), JSON.stringify(j, null, 1));
            pages = p; rows += l.length;
            if (l.length < 50) break;
        }
        fs.writeFileSync(path.join(out, "light_state.json"), JSON.stringify({ date: today, at: new Date().toISOString(), pages, rows, max_count: maxCount, truncated: maxCount != null && rows < +maxCount }, null, 1));
        S.done.push(`${c.ledger}:${rows}/${maxCount}`); S.pending--;
        console.log(`[light] ${c.ledger}(${c.name}): 净值 ${(nav?.ex_data?.index_list || []).length} 日, 流水 ${rows}/${maxCount}`);
        await jitter();
    }
}

async function modeProbe() {
    const keys = JSON.parse(fs.readFileSync("scripts/tzzb/match_keys.json", "utf8")).known;
    const host = hostPage();
    console.log(`[probe] 1 次: 月榜 ${keys[0]} ${ym()} 第 1 页`);
    if (DRY) return;
    const j = await get(host, monthlyUrl(keys[0], ym(), 1), 1);
    const n = (j?.ex_data?.rank_list || []).length;
    S.done.push(`probe:${n}`);
    console.log(`[probe] 通: rank_list ${n} 行, 字段 ${Object.keys((j?.ex_data?.rank_list || [])[0] || {}).join(",").slice(0, 200)}`);
}

function selftest() {
    // 只测纯函数: 月份区间 / 续传判定
    const save = A.slice();
    A.push("--from", "202511", "--to", "202602");
    const m = monthsFor("XXX");
    if (m.join(",") !== "202511,202512,202601,202602") { console.error("monthsFor FAIL", m); process.exit(1); }
    A.length = 0; A.push(...save);
    if (!/month=202501&sort_type=monthly_profit/.test(monthlyUrl("k", "202501", 2)) || !/page=2&count=50/.test(monthlyUrl("k", "202501", 2))) { console.error("url FAIL"); process.exit(1); }
    console.log("rank_monthly selftest PASS");
}

async function main() {
    if (has("--selftest")) return selftest();
    const keys = (arg("--keys") || "").split(",").filter(Boolean);
    try {
        if (has("--probe")) { S.mode = "probe"; await modeProbe(); }
        else if (has("--overall")) { S.mode = "overall"; await modeOverall(keys); }
        else if (has("--monthly")) { S.mode = "monthly"; await modeMonthly(keys); }
        else if (has("--light")) { S.mode = "light"; await modeLight(arg("--light")); }
        else { console.error("用法见文件头"); process.exit(1); }
    } catch (e) {
        if (e instanceof Blocked) { S.blocked = true; S.errors.push(e.message); console.error(`[blocked] ${e.message}`); try { await T?.close(); } catch { /* */ } finish(5); }
        if (e instanceof OutOfBudget) { S.errors.push(e.message); console.error(`[stop] ${e.message}`); try { await T?.close(); } catch { /* */ } finish(3); }
        S.errors.push(String(e.message).slice(0, 200)); console.error(`[fail] ${e.message}`); try { await T?.close(); } catch { /* */ } finish(1);
    }
    try { await T?.close(); } catch { /* */ }
    finish(S.pending > 0 ? 3 : 0);
}
main();
