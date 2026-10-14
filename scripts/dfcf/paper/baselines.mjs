// baselines.mjs — paper 按步归因的等权基准 + 分市况命中率(零 token, 只读; 2026-10-14 建, TODO §3-A 第 7 条)
// 借鉴 evotraders utils/baselines.py(等权基准) + analyst_tracker.py(分组胜率). 只加统计不改链: 读链产物/账本/本地行情, 只写 baselines.json。
//
// 问题: 链 02→04→05/06 每一步有没有增值? 做法=给每一步配一个"不动脑"的等权基准, 同一持有期比收益:
//   06 实际    = 该链当日 0915 盘前 06 终裁的 BUY 挂单(取账本 orders: date=D, time=09:15), 按下单金额加权;
//                成交→成交价买入(账本 fillPrice, 即 matcher 真实撮合/回放结果), 未成交/撤/废/拒=现金 0%
//   04 等权    = 0915 版 04 contract 里 group≠"遗留"(遗留=已有持仓的卖/持有建议, 不是买入提议)且有 6 位代码的候选, 去重等权,
//                D 日开盘价买入(保守: 开盘即涨停且全天没开板=买不到→现金; 开盘涨停但盘中开过板=按涨停价成交; D 日无 bar=停牌买不到)
//   02 方向等权 = 0915 版 02 contract 的 directions(文本含"回避"的剔除)按关键词映射到板块 ETF(跟踪对应行业指数, 可交易),
//                去重等权, 买入规则同 04; 映射不到的方向(连板接力/并购重组/航运等)不计入, 覆盖率单列
//   持有期统一 = D 日买入 → D+1 交易日收盘估值(A 股 T+1 最早可卖日); 收益 = (D收/买价)×(D+1收/D+1昨收)−1(用昨收跨除权),
//                扣往返费 0.1%(matcher 费率: 买卖各万 2.5 + 卖出印花 0.05%; 最低 5 元因不知金额忽略); D+1 停牌=按 D 收冻结
//   06 选股    = 06 买的那些票按 04 同口径 D 开盘等权买(只看"选了谁", 不看挂价)
//   05+06 增值 = 06 实际 − 04 等权(风控+终裁的筛选/挂价/仓位合起来值不值), 拆成 选股=06选股−04等权 与 挂价执行=06实际−06选股
//   04 增值 = 04 等权 − 02 方向等权(选股值不值)
//   命中率     = 06 0915 单按 02 市况(该链自己 0915 的 market_state)× 买/卖 分组: 买命中=成交后到 D+1 收盘毛收益>0;
//                卖命中=卖出后到 D+1 收盘价格低于卖价(卖对了); 未成交不计。对照=04 候选(开盘买)同口径命中率
// 0915 版取数: run_dir/slots/0915/(10/13 起) → baselines_0915_backfill.json(10/12 从 chain_step 导出) → 顶层(无 .prev=当日没跑盘中子链)
// 行情(纯本地, 不联网): downloads/market/<日>/kline_day.jsonl(不复权+昨收+涨停价) → 行情库 kline_day(只读 SELECT) → 日线归档(前复权)
//   --snap-today: 仅当 D+1=今天且本地还没今天 bar 时用 snapshot.mjs 取今日快照(matcher --eod 15:05 尾挂用; 行情库 15:35 才入库)
// 用法: node scripts/dfcf/paper/baselines.mjs [--snap-today] [--out <json>]   产物: scripts/dfcf/paper/baselines.json(report.mjs 读)
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { ACCOUNTS, NAME } from "./accounts.mjs";
import { limitOf } from "./snapshot.mjs";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(SCRIPT_DIR, "../../..");
const RESULTS = path.join(ROOT, "results");
const KDIR = path.join(ROOT, "downloads", "quotes", "daily");
const MKT = path.join(ROOT, "downloads", "market");
const SANDBOX = path.join(SCRIPT_DIR, "sandbox", "asof-0928");
const LIVE_START = "2026-10-08";   // 与 report.mjs 同: 实盘自 10/8 起, 之前=9/28-30 as-of 回放沙盒
const FEE = 0.001;                 // 往返费(见文件头)
const argv = process.argv.slice(2);
const OUT = argv.includes("--out") ? argv[argv.indexOf("--out") + 1] : path.join(SCRIPT_DIR, "baselines.json");
const SNAP_TODAY = argv.includes("--snap-today");
const TODAY = new Date().toLocaleDateString("sv-SE");

// ---- 02 方向 → 板块 ETF(关键词表, 取方向文本里最先出现的关键词; 同位置取长词). 改表=改口径, 在 baselines.json 留版本 ----
const ETF_MAP_VER = "2026-10-14";
const ETF_MAP = [
    [/机器人/, "562500", "机器人ETF"],
    [/网络安全|信息安全|网安|信创|软件|IT服务/, "159852", "软件ETF"],
    [/AI硬件|算力|光通信|光模块|CPO|通信|液冷/, "515880", "通信ETF"],
    [/AI应用|人工智能|AI/, "515070", "人工智能ETF"],
    [/游戏/, "159869", "游戏ETF"],
    [/短剧|影视|传媒|出版|漫剧|院线/, "512980", "传媒ETF"],
    [/医药|医疗|制药|创新药|生物医药/, "512010", "医药ETF"],
    [/固态电池|锂电|电池|储能/, "159755", "电池ETF"],
    [/电网|六张网|电力设备/, "159326", "电网设备ETF"],
    [/电力|公用|水电|绿电/, "159611", "电力ETF"],
    [/光伏|逆变器/, "515790", "光伏ETF"],
    [/风电|新能源(?!车|整车)/, "516160", "新能源ETF(风电近似)"],
    [/养殖|生猪|农牧/, "159865", "养殖ETF"],
    [/农业|种植|种业|粮食|橡胶/, "159698", "粮食ETF(农业近似)"],
    [/化工|化学制品|有机硅|染料|化肥|乳酸/, "159870", "化工ETF"],
    [/银行/, "512800", "银行ETF"],
    [/高股息|红利/, "510880", "红利ETF"],
    [/白酒|酒/, "512690", "酒ETF"],
    [/芯片|半导体/, "512480", "半导体ETF"],
    [/PCB|元件|消费电子/, "159732", "消费电子ETF"],
    [/汽车|零部件|零部|整车|新能源车|特斯拉/, "515030", "新能源车ETF(汽车近似)"],
    [/黄金|贵金属/, "518880", "黄金ETF"],
    [/有色|小金属|稀土|锗/, "512400", "有色金属ETF"],
    [/券商|证券|互联金融|互金|金融科技/, "512880", "证券ETF"],
    [/油气|天然气|石油/, "159930", "能源ETF(油气近似)"],
    [/煤炭/, "515220", "煤炭ETF"],
    [/军工|航天|国防|卫星/, "512660", "军工ETF"],
    [/地产/, "512200", "房地产ETF"],
    [/消费|零售|食品|饮料|电商|家居|家电|茶饮|乳品/, "159928", "消费ETF"],
    [/宽基|权重|沪深300/, "510300", "沪深300ETF"],
];
function mapDirection(text) {
    const s = String(text || "");
    if (/回避/.test(s)) return { skip: "回避" };
    let best = null;
    for (const [re, code, name] of ETF_MAP) {
        const m = s.match(re);
        if (m && (!best || m.index < best.idx || (m.index === best.idx && m[0].length > best.len))) best = { idx: m.index, len: m[0].length, code, name };
    }
    return best ? { code: best.code, name: best.name } : { unmapped: true };
}

// ---- 交易日: md/<年S季>/<日>.md(Java 交易日 md, 与 report.mjs 同口径) ----
const tradingDays = (() => {
    const set = new Set(), md = path.join(ROOT, "md");
    for (const sub of fs.existsSync(md) ? fs.readdirSync(md) : []) {
        const p = path.join(md, sub);
        if (fs.statSync(p).isDirectory()) for (const f of fs.readdirSync(p)) if (/^\d{4}-\d{2}-\d{2}\.md$/.test(f)) set.add(f.slice(0, 10));
    }
    return [...set].sort();
})();
const nextTd = (d) => tradingDays.find((x) => x > d) || null;

// ---- 链产物: 0915 版 contract ----
const lastContract = (f) => {
    try { const b = [...fs.readFileSync(f, "utf8").matchAll(/```contract\s*\n([\s\S]*?)```/g)]; return b.length ? JSON.parse(b.at(-1)[1]) : null; } catch { return null; }
};
let BACKFILL = {};
try { BACKFILL = JSON.parse(fs.readFileSync(path.join(SCRIPT_DIR, "baselines_0915_backfill.json"), "utf8")); } catch { /* 无补录 */ }
const STEP_FILE = { "02": "02_analysis", "04": "04_plan", "05": "05_risk", "06": "06_verdict" };
function contract0915(skill, runKey, step) {
    const dir = path.join(RESULTS, `${skill}_chain`, runKey), f = STEP_FILE[step];
    const slot = path.join(dir, "slots", "0915", f + ".md");
    if (fs.existsSync(slot)) return { c: lastContract(slot), from: "slots/0915" };
    const bf = BACKFILL[runKey]?.[skill]?.[step];
    if (bf) return { c: bf, from: "chain_step 补录" };
    if (!fs.existsSync(path.join(dir, f + ".prev.md")) && fs.existsSync(path.join(dir, f + ".md"))) return { c: lastContract(path.join(dir, f + ".md")), from: "顶层" };
    return { c: null, from: null };
}
const STATES = ["有主线", "无主线退潮", "普跌"];
const normState = (v) => {   // 与 report.mjs / 驱动器 norm_enum 同口径
    const s = String(v || "").trim(), hit = STATES.filter((a) => s.startsWith(a));
    if (hit.length) return hit.sort((a, b) => b.length - a.length)[0];
    const pre = s.length >= 2 ? STATES.filter((a) => a.startsWith(s)) : [];
    return pre.length === 1 ? pre[0] : null;
};
const skillOf = (src) => (src === "A-cb" ? "buchitudou0" : src.replace(/^A-/, ""));

// ---- 账本(实盘 books/ 与 as-of 沙盒), 只读 ----
const loadBook = (dir, src) => { try { return JSON.parse(fs.readFileSync(path.join(dir, "books", src + ".json"), "utf8")); } catch { return null; } };
const BOOKS = { live: {}, asof: {} };
for (const [src] of ACCOUNTS) { BOOKS.live[src] = loadBook(SCRIPT_DIR, src); BOOKS.asof[src] = loadBook(SANDBOX, src); }
function quality(mode, d) {   // 与 report.mjs chartData 同口径
    if (mode === "asof") return "as-of回放";
    const bs = Object.values(BOOKS.live).filter(Boolean);
    if (bs.some((b) => b.trades.some((t) => String(t.id).startsWith(d) && /回放/.test(t.why || "")))) return "回放估算";
    if (bs.some((b) => b.nav.some((n) => n.date === d && n.restated))) return "重算";
    return "实盘撮合";
}

// ---- 枚举链日: results/<skill>_chain/{live-YYYYMMDD(≥10/8) | asof-YYYYMMDD(<10/8)}, 且为交易日 ----
const runs = [];
for (const [src] of ACCOUNTS) {
    const skill = skillOf(src), cdir = path.join(RESULTS, `${skill}_chain`);
    if (!fs.existsSync(cdir)) continue;
    for (const name of fs.readdirSync(cdir)) {
        const m = name.match(/^(live|asof)-(\d{4})(\d{2})(\d{2})$/);
        if (!m) continue;
        const d = `${m[2]}-${m[3]}-${m[4]}`, mode = m[1];
        if (!tradingDays.includes(d) || (mode === "live" ? d < LIVE_START : d >= LIVE_START)) continue;
        runs.push({ src, skill, mode, d, runKey: name });
    }
}
runs.sort((a, b) => a.d.localeCompare(b.d) || ACCOUNTS.findIndex((x) => x[0] === a.src) - ACCOUNTS.findIndex((x) => x[0] === b.src));

// ---- 行情: 不复权 bar {o,h,l,c,pc,lu}; 本地三级, 一次性批量取 ----
const symOf = (c) => (/^(92|8|4)/.test(c) ? "bj" : /^(6|5|9|11)/.test(c) ? "sh" : "sz") + c;
const BAR = new Map();   // `${code}|${date}` → bar
const SRC_COUNT = {};
const put = (code, d, bar, src) => { if (!BAR.has(`${code}|${d}`) && bar && bar.o > 0 && bar.c > 0) { BAR.set(`${code}|${d}`, bar); SRC_COUNT[src] = (SRC_COUNT[src] || 0) + 1; } };
function loadJsonl(dates, codes) {
    const want = new Map(codes.map((c) => [symOf(c), c]));
    for (const d of dates) {
        const f = path.join(MKT, d, "kline_day.jsonl");
        if (!fs.existsSync(f)) continue;
        for (const line of fs.readFileSync(f, "utf8").split("\n")) {
            if (!line) continue;
            const sym = line.slice(0, 40).match(/"symbol":\s*"([a-z]{2}\d{6})"/)?.[1];   // 先粗筛再 JSON.parse(全市场 8k 行)
            if (!sym || !want.has(sym)) continue;
            const r = JSON.parse(line);
            put(want.get(sym), d, { o: +r.open, h: +r.high, l: +r.low, c: +r.close, pc: r.preClose == null ? null : +r.preClose, lu: r.limitUp == null ? null : +r.limitUp }, "jsonl");
        }
    }
}
function loadDb(pairs) {   // 只读 SELECT; 账号同 Java application.yml(与 backfill_bilibili/manual_backfill.py 同做法)
    if (!pairs.length) return;
    const MYSQL = "C:/Program Files/MySQL/MySQL Server 8.0/bin/mysql.exe";
    let pw;
    try { pw = fs.readFileSync(path.join(ROOT, "inv-admin/src/main/resources/application.yml"), "utf8").match(/password:\s*"?([^"\r\n]+)/)[1].trim(); } catch { return; }
    if (!fs.existsSync(MYSQL)) return;
    const codes = [...new Set(pairs.map((p) => p[0]))], dates = [...new Set(pairs.map((p) => p[1]))];
    const sql = `select symbol, date_format(trade_date,'%Y-%m-%d'), open, high, low, close, pre_close, limit_up from kline_day where is_deleted=0 and status=0 `
        + `and trade_date in (${dates.map((d) => `'${d}'`).join(",")}) and symbol in (${codes.map((c) => `'${symOf(c)}'`).join(",")}) order by id`;
    try {
        const out = execFileSync(MYSQL, ["-uroot", "-N", "-B", "-r", "investment_market", "-e", sql], { env: { ...process.env, MYSQL_PWD: pw }, encoding: "utf8", windowsHide: true, maxBuffer: 64 << 20 });
        const back = new Map(codes.map((c) => [symOf(c), c]));
        const rows = new Map();   // 同 symbol+日 多行(多源)取最后入库的
        for (const l of out.split(/\r?\n/)) { const f = l.split("\t"); if (f.length >= 8 && back.has(f[0])) rows.set(`${f[0]}|${f[1]}`, f); }
        for (const f of rows.values()) put(back.get(f[0]), f[1], { o: +f[2], h: +f[3], l: +f[4], c: +f[5], pc: f[6] === "NULL" ? null : +f[6], lu: f[7] === "NULL" ? null : +f[7] }, "行情库");
    } catch (e) { console.warn("WARN 行情库查询失败(降级日线归档):", String(e.message).split("\n")[0]); }
}
function loadArchive(pairs) {   // 前复权档: 近期与不复权一致, D 之后有除权时 06 挂价比较会偏(已知局限, 仅兜底)
    const byCode = new Map();
    for (const [c, d] of pairs) (byCode.get(c) || byCode.set(c, []).get(c)).push(d);
    for (const [c, ds] of byCode) {
        let kl = [];
        try { kl = JSON.parse(fs.readFileSync(path.join(KDIR, c + ".json"), "utf8")).klines || []; } catch { continue; }
        for (const d of ds) { const i = kl.findIndex((k) => k.d === d); if (i >= 0) put(c, d, { o: kl[i].o, h: kl[i].h, l: kl[i].l, c: kl[i].c, pc: i > 0 ? kl[i - 1].c : null, lu: null }, "日线归档"); }
    }
}
async function loadSnapToday(codes) {
    const { snapMany } = await import("./snapshot.mjs");
    const px = await snapMany(codes, 400);
    for (const [c, q] of Object.entries(px)) if (q && !q.error && q.last > 0) put(c, TODAY, { o: q.open, h: q.high, l: q.low, c: q.last, pc: q.prevClose || null, lu: null }, "今日快照");
}

// ---- 买入/收益(保守成交) ----
const isAtLimitUp = (code, bar) => (bar.lu ? bar.o >= bar.lu - 1e-6 : bar.pc > 0 && (bar.o / bar.pc - 1) * 100 >= limitOf(code));
function openBuy(code, d) {
    const bar = BAR.get(`${code}|${d}`);
    if (!bar) return { E: null, why: "D日无bar(停牌/缺价)" };
    if (isAtLimitUp(code, bar)) return bar.l < bar.o - 1e-6 ? { E: bar.o, why: "开盘涨停·盘中开板按涨停价" } : { E: null, why: "开盘涨停未开板·买不到" };
    return { E: bar.o, why: "开盘价" };
}
// 毛收益(不扣费): D 日以 E 买入 → D+1 收盘; null=待结算
function hold(code, d, d1, E, availDates) {
    const b0 = BAR.get(`${code}|${d}`), b1 = BAR.get(`${code}|${d1}`);
    if (!b0) return null;
    if (!b1) return availDates.has(d1) && d1 !== TODAY ? { r: b0.c / E - 1, frozen: true } : null;   // 今天缺价=快照没取到, 不当停牌
    return { r: (b0.c / E) * (b1.c / (b1.pc > 0 ? b1.pc : b0.c)) - 1, frozen: false };
}

async function main() {
    // 1) 汇总每个链日的输入
    const items = runs.map((run) => {
        const c02 = contract0915(run.skill, run.runKey, "02"), c04 = contract0915(run.skill, run.runKey, "04");
        const dirs = Array.isArray(c02.c?.directions) ? c02.c.directions.map((x) => (typeof x === "string" ? x : JSON.stringify(x))) : [];
        const dmap = dirs.map((t) => ({ text: t, ...mapDirection(t) }));
        const cands = (Array.isArray(c04.c?.candidates) ? c04.c.candidates : []).filter((x) => /^\d{6}$/.test(String(x.code)) && x.group !== "遗留");
        const book = BOOKS[run.mode][run.src];
        const orders = (book?.orders || []).filter((o) => o.date === run.d && o.time === "09:15" && (o.side === "BUY" || o.side === "SELL"));
        return { ...run, d1: nextTd(run.d), regime: normState(c02.c?.market_state), from02: c02.from, from04: c04.from,
            dmap, c04codes: [...new Set(cands.map((x) => String(x.code)))], hasBook: !!book, orders };
    });
    // 2) 行情批量: jsonl → 行情库 → 日线归档 → (可选)今日快照
    const need = new Set();
    for (const it of items) {
        const codes = [...it.c04codes, ...it.dmap.filter((x) => x.code).map((x) => x.code), ...it.orders.map((o) => o.code)];
        for (const c of codes) { need.add(`${c}|${it.d}`); if (it.d1) need.add(`${c}|${it.d1}`); }
    }
    const pairs = () => [...need].filter((k) => !BAR.has(k)).map((k) => k.split("|"));
    const allCodes = [...new Set([...need].map((k) => k.split("|")[0]))], allDates = [...new Set([...need].map((k) => k.split("|")[1]))];
    loadJsonl(allDates, allCodes);
    loadDb(pairs());
    loadArchive(pairs());
    if (SNAP_TODAY) {
        const miss = [...new Set(pairs().filter(([, d]) => d === TODAY).map(([c]) => c))];
        if (miss.length && new Date().getHours() >= 15) { console.log(`今日快照补价 ${miss.length} 只(D+1=今天, 行情库未入库)`); try { await loadSnapToday(miss); } catch (e) { console.warn("WARN 今日快照失败(该日待结算):", e.message); } }
    }
    const availDates = new Set([...BAR.keys()].map((k) => k.split("|")[1]));

    // 3) 逐链日计算
    const days = [], hits = [];
    for (const it of items) {
        const pending = !it.d1 || !availDates.has(it.d1);
        const row = { d: it.d, d1: it.d1, src: it.src, name: NAME[it.src], mode: it.mode, quality: quality(it.mode, it.d), regime: it.regime,
            src02: it.from02, src04: it.from04, pending };
        // D 开盘等权腿(04/02/06 选股共用): 买不到=现金 0
        const openLeg = (code) => { const b = openBuy(code, it.d); const h = b.E && !pending ? hold(code, it.d, it.d1, b.E, availDates) : null; return { code, E: b.E, why: b.why, r: b.E ? (h ? h.r - FEE : null) : 0, gross: h?.r ?? null }; };
        const leg04 = it.c04codes.map(openLeg);
        // 02 方向 ETF 等权(同 ETF 只算一次)
        const etfs = [...new Map(it.dmap.filter((x) => x.code).map((x) => [x.code, x])).values()];
        const leg02 = etfs.map((x) => ({ ...openLeg(x.code), etf: x.name }));
        // 06 实际: 0915 BUY 单按下单金额加权, 未成交=0
        const buys = it.orders.filter((o) => o.side === "BUY");
        const leg06 = buys.map((o) => {
            const w = o.price * o.qty, filled = o.status === "filled" && o.fillPrice > 0;
            const h = filled && !pending ? hold(o.code, it.d, it.d1, o.fillPrice, availDates) : null;
            return { code: o.code, w, status: o.status, fill: filled ? o.fillPrice : null, r: filled ? (h ? h.r - FEE : null) : 0, gross: h?.r ?? null };
        });
        const ew = (leg) => (leg.length && leg.every((x) => x.r != null) ? leg.reduce((s, x) => s + x.r, 0) / leg.length : null);
        row.b04 = pending ? null : ew(leg04);
        row.b02 = pending ? null : ew(leg02);
        row.a06 = pending || !it.hasBook ? null : !leg06.length ? 0 : leg06.every((x) => x.r != null) ? leg06.reduce((s, x) => s + x.w * x.r, 0) / leg06.reduce((s, x) => s + x.w, 0) : null;
        // 06 选股·开盘等权: 06 买的票按 04 同口径开盘买 → 把 05+06 增值拆成 选股(s06−b04) 与 挂价执行(a06−s06)
        row.s06 = pending || !it.hasBook ? null : !buys.length ? 0 : ew([...new Set(buys.map((o) => o.code))].map(openLeg));
        row.v0506 = row.a06 != null && row.b04 != null ? row.a06 - row.b04 : null;
        row.vSel = row.s06 != null && row.b04 != null ? row.s06 - row.b04 : null;
        row.vExec = row.a06 != null && row.s06 != null ? row.a06 - row.s06 : null;
        row.v04 = row.b04 != null && row.b02 != null ? row.b04 - row.b02 : null;
        row.n = { c04: leg04.length, c04buyable: leg04.filter((x) => x.E).length, dirs: it.dmap.length, dirsSkip: it.dmap.filter((x) => x.skip).length,
            dirsMapped: it.dmap.filter((x) => x.code).length, etfs: leg02.length, buy06: buys.length, buy06filled: leg06.filter((x) => x.fill).length,
            sell06: it.orders.length - buys.length };
        row.unmapped = it.dmap.filter((x) => x.unmapped).map((x) => x.text);
        row.legs = { "04": leg04, "02": leg02, "06": leg06 };
        days.push(row);
        // 命中率原料(已结算才计)
        if (pending) continue;
        for (const x of leg06) if (x.fill && x.gross != null) hits.push({ src: it.src, d: it.d, regime: it.regime, kind: "06买", code: x.code, hit: x.gross > 0 });
        for (const o of it.orders.filter((o) => o.side === "SELL" && o.status === "filled" && o.fillPrice > 0)) {
            const h = hold(o.code, it.d, it.d1, o.fillPrice, availDates);
            if (h) hits.push({ src: it.src, d: it.d, regime: it.regime, kind: "06卖", code: o.code, hit: h.r < 0 });
        }
        for (const x of leg04) if (x.E && x.gross != null) hits.push({ src: it.src, d: it.d, regime: it.regime, kind: "04候选", code: x.code, hit: x.gross > 0 });
    }

    // 4) 汇总: 每链 + 全部链合计
    const mean = (a) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : null);
    const agg = (rows) => {
        const ok = rows.filter((r) => !r.pending);
        const col = (k) => ok.map((r) => r[k]).filter((v) => v != null);
        const both = (a, b) => ok.filter((r) => r[a] != null && r[b] != null);
        return { days: ok.length, pending: rows.length - ok.length, a06: mean(col("a06")), s06: mean(col("s06")), b04: mean(col("b04")), b02: mean(col("b02")),
            v0506: mean(col("v0506")), vSel: mean(col("vSel")), vExec: mean(col("vExec")), v04: mean(col("v04")), n0506: both("a06", "b04").length, n04: both("b04", "b02").length,
            win0506: both("a06", "b04").filter((r) => r.a06 > r.b04).length, win04: both("b04", "b02").filter((r) => r.b04 > r.b02).length };
    };
    const byChain = ACCOUNTS.map(([src]) => ({ src, name: NAME[src], ...agg(days.filter((r) => r.src === src)) })).filter((x) => x.days + x.pending);
    const groupHits = (hs) => {
        const out = {};
        for (const g of [...STATES, null]) for (const k of ["06买", "06卖", "04候选"]) {
            const xs = hs.filter((h) => h.regime === g && h.kind === k);
            if (xs.length) (out[g ?? "无标签"] = out[g ?? "无标签"] || {})[k] = { n: xs.length, hit: xs.filter((h) => h.hit).length };
        }
        return out;
    };
    const res = {
        updated: new Date().toLocaleString("sv-SE").slice(0, 16), etfMapVer: ETF_MAP_VER, fee: FEE,
        口径: "见 baselines.mjs 文件头; 06 实际=0915 BUY 挂单按金额加权(未成交=现金), 04/02=D 开盘等权(开盘涨停未开板=买不到), 持有到 D+1 收盘, 扣往返 0.1%",
        priceSrc: SRC_COUNT, chainDays: days.length, settled: days.filter((r) => !r.pending).length,
        total: agg(days), byChain, hits: { all: groupHits(hits), byChain: Object.fromEntries(ACCOUNTS.map(([s]) => [s, groupHits(hits.filter((h) => h.src === s))])) },
        days,
    };
    // 汇总缩进可读, 逐链日明细一行一条(含每条腿, 可审计; 体积/diff 可控)
    fs.writeFileSync(OUT, JSON.stringify({ ...res, days: "%DAYS%" }, null, 1).replace('"%DAYS%"', "[\n" + days.map((d) => JSON.stringify(d)).join(",\n") + "\n]") + "\n");
    const pct = (x) => (x == null ? "—" : (x * 100).toFixed(2) + "%");
    console.log(`baselines: ${res.chainDays} 链日(已结算 ${res.settled}) | 06 ${pct(res.total.a06)} / 04等权 ${pct(res.total.b04)} / 02方向 ${pct(res.total.b02)} | 05+06增值 ${pct(res.total.v0506)}(${res.total.win0506}/${res.total.n0506}) 04增值 ${pct(res.total.v04)}(${res.total.win04}/${res.total.n04}) | 行情 ${JSON.stringify(SRC_COUNT)} → ${OUT}`);
}

main().catch((e) => { console.error("baselines 失败:", e); process.exit(1); });
