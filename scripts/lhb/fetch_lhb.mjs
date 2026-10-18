// fetch_lhb.mjs — 每日龙虎榜采集(东财 datacenter-web 公开接口) + md 挂载(2026-10-14 建)
// 用法: node scripts/lhb/fetch_lhb.mjs --date yyyy-MM-dd [--write] [--force] [--source em|sina|ths] [--local] [--no-fallback]
//   10/17 A12: 缺省 em, 东财失败(近 7 天的日子)自动切新浪备源(fetchSina); 演练 LHB_DRILL=em 跳过东财
//   --local(10/15 加): 只读本地已完整的 json 重写 md, 绝不联网; 本地不完整 → exit 6
// 数据(一天 3 次请求): ①上榜总表 RPT_DAILYBILLBOARD_DETAILSNEW(按日) ②买五 RPT_BILLBOARD_DAILYDETAILSBUY(按日整批)
//   ③卖五 RPT_BILLBOARD_DAILYDETAILSSELL(按日整批). 整批里某条记录买卖两边全缺时才按个股补(每只 2 次). 一只票多个上榜原因=多条记录(TRADE_ID 不同), 合并成一只.
// 产物: downloads/lhb/yyyy.MM.dd/{list.json, detail_<code>.json}; 已存在且完整则跳过请求(--force 强制重抓)
//   完整=list 抓取时刻 ≥ 交易日 18:00(之前抓的算临时, 下次重抓) 且每只上榜票都有 detail 文件
// 挂载(--write): md/<y>S<q>/<date>.md 的 ## 复盘 → ### 龙虎榜 整节覆盖(幂等, 不碰其他节); 无 ## 复盘 的早期 md 只存 json 不写
//   小节标题禁含 "|"(Java inheritHoldingsFromPrevious 会把 "### 复盘持仓" 之后所有 "#### x | y" 当持仓继承)
// 出口: 0=ok 1=抓取失败 3=当日榜单未出(空) 4=无md 5=反爬 6=--local 且本地 json 不完整; 末行 JSON:{...}
// 防封: ≤0.5 次/秒(请求间隔 2.0~3.0s 抖动) + 3 次退避重试(8s/24s/72s ×抖动) + 失败显式非 0, 不编数据
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { guard, gfetch } from "../lib/req_guard.mjs";   // 10/15 统一请求层(源 em_datacenter: 熔断/日预算/计数, 见 scripts/lib/req_guard_sources.json)

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
process.chdir(ROOT);
const ARGS = process.argv.slice(2);
const opt = (k) => { const i = ARGS.indexOf(k); return i === -1 ? null : ARGS[i + 1]; };
const DATE = opt("--date");
const WRITE = ARGS.includes("--write");
const FORCE = ARGS.includes("--force");
const LOCAL = ARGS.includes("--local");   // 10/15: 只读本地 json, 不联网
const SOURCE = opt("--source") || "em";
const READY_HHMM = "18:00";   // 交易所 16:30~17:30 陆续出齐(公开口径), 东财同步晚几分钟; 18:00 前抓的视为临时

const out = { date: DATE, source: SOURCE, requests: 0, stocks: 0, records: 0, fetched: false, md: null };
class Exit { constructor(code) { this.code = code; } }
function done(code, msg) {   // 不在这里 process.exit: Windows 上 fetch 句柄未关时 exit 会触发 libuv 断言崩溃(exit 3221226505), 改为抛出由 main 收尾设 exitCode
    out.code = code;
    if (msg) out.msg = msg;
    throw new Exit(code);
}
if (!DATE || !/^\d{4}-\d{2}-\d{2}$/.test(DATE)) {
    console.error("用法: node scripts/lhb/fetch_lhb.mjs --date yyyy-MM-dd [--write] [--force] [--source em|ths]");
    process.exit(2);
}
const DIR = path.join(process.env.LHB_OUT_DIR || path.join("downloads", "lhb"), DATE.replace(/-/g, "."));   // LHB_OUT_DIR=演练用产物目录(不碰真实 downloads/lhb)
const T0 = Date.now();

// ---------- HTTP ----------
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = (base) => base * (0.75 + Math.random() * 0.5);
const HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
    Referer: "https://data.eastmoney.com/stock/lhb.html",
};
class Ban extends Error {}
const G = guard("em_datacenter");
let lastReq = 0;
async function getJson(url) {
    let lastErr = null;
    for (let a = 0; a < 4; a++) {
        if (a) await sleep(jitter(8000 * 3 ** (a - 1)));
        const gap = jitter(2500) - (Date.now() - lastReq);   // 节流: 两次请求间隔 ≥1.9s(均值 2.5s)
        if (gap > 0) await sleep(gap);
        lastReq = Date.now();
        out.requests++;
        try {
            let r;
            try { r = await G.fetch(url, { headers: HDR, signal: AbortSignal.timeout(20000) }); }
            catch (e) { if (e.name === "ReqError" && (e.kind === "BLOCKED" || e.local)) throw new Ban(e.message); throw e; }   // 熔断中/命中 403·429/超预算: 不重试, 直接按反爬停
            const txt = await r.text();
            if (r.status === 403 || r.status === 429) { lastErr = new Ban(`HTTP ${r.status}`); continue; }
            if (!r.ok) { lastErr = new Error(`HTTP ${r.status}`); continue; }
            let j;
            try { j = JSON.parse(txt); } catch { lastErr = new Ban(`非 JSON 响应(疑反爬页): ${txt.slice(0, 80)}`); continue; }
            return j;
        } catch (e) {
            if (e instanceof Ban && /熔断|BLOCKED|RATE_LIMIT/.test(e.message)) throw e;
            lastErr = e;
        }
    }
    if (lastErr instanceof Ban) G.ban(lastErr.message);   // 4 次都是反爬页=熔断该源(冷却见配置), 后续进程不再硬打
    throw lastErr;
}

const EM = "https://datacenter-web.eastmoney.com/api/data/v1/get";
const LIST_COLS = "SECURITY_CODE,SECUCODE,SECURITY_NAME_ABBR,TRADE_DATE,TRADE_ID,EXPLANATION,CLOSE_PRICE,CHANGE_RATE,BILLBOARD_NET_AMT,BILLBOARD_BUY_AMT,BILLBOARD_SELL_AMT,DEAL_NET_RATIO,ACCUM_AMOUNT,TURNOVERRATE,TRADE_MARKET";
const DET_COLS = "SECURITY_CODE,TRADE_DATE,TRADE_ID,OPERATEDEPT_CODE,OPERATEDEPT_NAME,EXPLANATION,BUY,SELL,NET,TOTAL_BUYRIO,TOTAL_SELLRIO";
const q = (s) => encodeURIComponent(s);

async function emReport(report, cols, filter, sort = "", size = 500) {
    const rows = [];
    for (let page = 1; page <= 20; page++) {
        const url = `${EM}?reportName=${report}&columns=${cols}&filter=${q(filter)}&pageNumber=${page}&pageSize=${size}${sort}&source=WEB&client=WEB`;
        const j = await getJson(url);
        if (!j.success) {
            if (j.code === 9201) break;          // 返回数据为空(合法: 当日未出/无数据)
            throw new Error(`东财 ${report} 返回失败: ${j.code} ${j.message}`);
        }
        rows.push(...j.result.data);
        if (page >= (j.result.pages || 1)) break;
    }
    return rows;
}

// 东财源: 总表 + 买五/卖五整批 → { list, details: {code: {buy, sell}} }
async function fetchEm(date) {
    const list = await emReport("RPT_DAILYBILLBOARD_DETAILSNEW", LIST_COLS, `(TRADE_DATE='${date}')`, "&sortColumns=BILLBOARD_NET_AMT,TRADE_ID&sortTypes=-1,1");
    if (!list.length) return { list, details: {} };
    // 实测服务端 pageSize 上限 500(传 5000 也按 500 分页), 上榜 >100 条的日子要翻页; 显式全序排序防翻页重叠/漏行
    const DET_SORT = "&sortColumns=TRADE_ID,OPERATEDEPT_CODE,BUY,SELL&sortTypes=1,1,-1,-1";
    const buy = await emReport("RPT_BILLBOARD_DAILYDETAILSBUY", DET_COLS, `(TRADE_DATE='${date}')`, DET_SORT, 500);
    const sell = await emReport("RPT_BILLBOARD_DAILYDETAILSSELL", DET_COLS, `(TRADE_DATE='${date}')`, DET_SORT, 500);
    const details = {};
    for (const r of list) details[r.SECURITY_CODE] ??= { buy: [], sell: [], mode: "bulk" };
    for (const r of buy) details[r.SECURITY_CODE]?.buy.push(r);
    for (const r of sell) details[r.SECURITY_CODE]?.sell.push(r);
    // 整批缺腿的(某条上榜记录没有买或卖席位) → 按个股补
    for (const code of Object.keys(details)) {
        const ids = new Set(list.filter((r) => r.SECURITY_CODE === code).map((r) => String(r.TRADE_ID)));   // 注: 总表 TRADE_ID 是数字, 明细表是字符串
        const d = details[code];
        // 某条上榜记录买卖两边都没有才补抓(融资买入占比类榜单只有买方、无卖方是正常的, 实测按个股补抓结果相同, 不必多打 2 次)
        const ok = [...ids].every((id) => d.buy.some((x) => String(x.TRADE_ID) === id) || d.sell.some((x) => String(x.TRADE_ID) === id));
        if (ok) continue;
        const f = `(TRADE_DATE='${date}')(SECURITY_CODE="${code}")`;
        details[code] = { buy: await emReport("RPT_BILLBOARD_DAILYDETAILSBUY", DET_COLS, f), sell: await emReport("RPT_BILLBOARD_DAILYDETAILSSELL", DET_COLS, f), mode: "code" };
        out.refetched = (out.refetched || 0) + 1;
    }
    return { list, details };
}

// 同花顺备用源(降级接口位): data.10jqka.com.cn/market/longhu/ 只给"当天"页面(GBK HTML, 无按日期参数), 席位在个股子页;
// 未实现解析——显式失败, 不编数据。东财长期不可用时再接。
async function fetchThs(_date) {
    throw new Error("同花顺备用源未实现(仅接口位): 页面只给当天榜单, 席位需逐股子页 HTML 解析");
}

// 10/17 A12 新浪备源(另一家供应商, 东财失败自动切; 也可 --source sina 强制):
//   ①总表 vInvestConsult/kind/lhb/index.phtml?tradedate=<日>(GBK HTML, 按上榜原因分表: 代码/名称/收盘/对应值/成交量万股/成交额万元)
//   ②席位 jsonp InvestConsultService.getLHBComBSData?symbol=&tradedate=&type=(每个"原因×个股"1 次; 金额单位万元, 席位全称与东财同)
//   映射成东财字段, render/build 不用改: TRADE_ID=新浪原因类型_代码; 买入/卖出/净额=该原因下买五卖五去重合计(与东财口径同, 10/16 百洋核对);
//   涨跌/换手=本地行情库 downloads/market/<日>/kline_day.jsonl(零请求; 新浪"对应值"随原因变, 不能当涨跌幅)。
//   请求量: 1 + 原因×个股 次(≈60~90), 间隔 2.0~3.0s; 只给近 7 天自动兜底(防 backfill 历史日大批量打新浪)
const SINA = "https://vip.stock.finance.sina.com.cn";
const SINA_HDR = { "User-Agent": HDR["User-Agent"] || "Mozilla/5.0", Referer: `${SINA}/q/go.php/vInvestConsult/kind/lhb/index.phtml` };
let lastSina = 0;
async function sinaGet(url) {
    const gap = jitter(2500) - (Date.now() - lastSina);
    if (gap > 0) await sleep(gap);
    lastSina = Date.now();
    out.requests++;
    const r = await gfetch(url, { headers: SINA_HDR, signal: AbortSignal.timeout(20000) });
    if (!r.ok) throw new Error(`新浪 HTTP ${r.status}`);
    return new TextDecoder("gbk").decode(Buffer.from(await r.arrayBuffer()));
}
function parseSinaList(html) {
    const out2 = [];
    const blocks = html.split(/id="dataTable"/).slice(1);
    for (const b of blocks) {
        const reason = ((b.match(/<span[^>]*font-weight:bold[^>]*>\s*([\s\S]*?)\s*<\/span>/) || [])[1] || "").replace(/<[^>]+>/g, "").trim();
        for (const tr of b.split(/<tr/).slice(1)) {
            const m = tr.match(/showDetail\('(\w+)','(\d{6})','([\d-]+)'/);
            if (!m) continue;
            const td = [...tr.matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g)].map((x) => x[1].replace(/<[^>]+>/g, "").trim());
            out2.push({ type: m[1], code: m[2], date: m[3], reason, name: td[2], close: +td[3], value: +td[4], volWan: +td[5], amtWan: +td[6] });
        }
    }
    return out2;
}
function parseSinaDetail(txt) {
    const m = txt.match(/var details=\(([\s\S]*)\)\s*;?\s*$/);
    if (!m) throw new Error("新浪席位 jsonp 结构异常");
    return JSON.parse(m[1]);
}
async function fetchSina(date) {
    const rows = parseSinaList(await sinaGet(`${SINA}/q/go.php/vInvestConsult/kind/lhb/index.phtml?tradedate=${date}`)).filter((r) => r.date === date);
    if (!rows.length) return { list: [], details: {} };
    const kd = {};
    try {
        for (const l of fs.readFileSync(path.join("downloads", "market", date, "kline_day.jsonl"), "utf8").split("\n")) {
            if (!l) continue;
            const j = JSON.parse(l);
            kd[j.symbol.slice(2)] = j;
        }
    } catch { /* 本地无当日日线: 涨跌/换手留空 */ }
    const list = [], details = {};
    const MAX = +process.env.LHB_SINA_MAX || Infinity;   // 演练限量: 只取前 N 个席位明细(其余席位空), 控制探测请求数
    let nDet = 0;
    for (const r of rows) {
        const tid = `sina${r.type}_${r.code}`;
        const det = nDet++ >= MAX ? { buy: [], sell: [] } : parseSinaDetail(await sinaGet(`${SINA}/q/api/jsonp.php/var%20details=/InvestConsultService.getLHBComBSData?symbol=${r.code}&tradedate=${date}&type=${r.type}`));
        const conv = (x) => ({ SECURITY_CODE: r.code, TRADE_DATE: `${date} 00:00:00`, TRADE_ID: tid, OPERATEDEPT_CODE: x.comCode, OPERATEDEPT_NAME: x.comName,
            EXPLANATION: r.reason, BUY: +x.buyAmount * 1e4 || 0, SELL: +x.sellAmount * 1e4 || 0, NET: +x.netAmount * 1e4 || 0 });
        const buy = (det.buy || []).map(conv), sell = (det.sell || []).map(conv);
        const d = (details[r.code] ||= { buy: [], sell: [], mode: "sina" });
        d.buy.push(...buy); d.sell.push(...sell);
        const seen = new Set(), uniq = [];   // 同席位同时在买五卖五只算一次
        for (const x of [...buy, ...sell]) { const k = `${x.OPERATEDEPT_NAME}|${x.BUY}|${x.SELL}`; if (!seen.has(k)) { seen.add(k); uniq.push(x); } }
        const bAmt = uniq.reduce((a, x) => a + x.BUY, 0), sAmt = uniq.reduce((a, x) => a + x.SELL, 0);
        const k = kd[r.code];
        list.push({ SECURITY_CODE: r.code, SECUCODE: `${r.code}.${/^6/.test(r.code) ? "SH" : /^[03]/.test(r.code) ? "SZ" : "BJ"}`, SECURITY_NAME_ABBR: r.name,
            TRADE_DATE: `${date} 00:00:00`, TRADE_ID: tid, EXPLANATION: r.reason, CLOSE_PRICE: r.close,
            CHANGE_RATE: k && k.preClose ? +((k.close / k.preClose - 1) * 100).toFixed(4) : null,
            BILLBOARD_NET_AMT: bAmt - sAmt, BILLBOARD_BUY_AMT: bAmt, BILLBOARD_SELL_AMT: sAmt,
            DEAL_NET_RATIO: null, ACCUM_AMOUNT: r.amtWan * 1e4, TURNOVERRATE: k ? k.turnoverRate : null, TRADE_MARKET: null });
    }
    return { list, details };
}

// ---------- 存取 ----------
const readJson = (f) => { try { return JSON.parse(fs.readFileSync(f, "utf8")); } catch { return null; } };
const ts = () => { const d = new Date(Date.now() + 8 * 3600e3); return d.toISOString().slice(0, 19).replace("T", " "); };   // 北京时间

function loadCached() {
    const L = readJson(path.join(DIR, "list.json"));
    if (!L || !Array.isArray(L.rows) || !L.rows.length) return null;
    if (!(L.fetched_at >= `${DATE} ${READY_HHMM}`)) return null;     // 18:00 前抓的=临时
    const details = {};
    for (const code of new Set(L.rows.map((r) => r.SECURITY_CODE))) {
        const d = readJson(path.join(DIR, `detail_${code}.json`));
        if (!d || !Array.isArray(d.buy) || !Array.isArray(d.sell)) return null;
        details[code] = d;
    }
    return { list: L.rows, details, fetched_at: L.fetched_at, source: L.source };
}

function save(list, details) {
    fs.mkdirSync(DIR, { recursive: true });
    const at = ts();
    for (const [code, d] of Object.entries(details)) {
        const name = (list.find((r) => r.SECURITY_CODE === code) || {}).SECURITY_NAME_ABBR;
        fs.writeFileSync(path.join(DIR, `detail_${code}.json`), JSON.stringify({ date: DATE, code, name, source: out.source, mode: d.mode, fetched_at: at, buy: d.buy, sell: d.sell }, null, 1));
    }
    // list.json 最后写: 它在且完整 = 本日 detail 都已落盘
    fs.writeFileSync(path.join(DIR, "list.json"), JSON.stringify({ date: DATE, source: out.source, fetched_at: at, count: list.length, rows: list }, null, 1));
    return at;
}

// ---------- 加工 ----------
const YOUZI = (readJson("scripts/lhb/youzi.json") || {}).map || {};
// 10/14 用户定: 拉萨天团算游资(有游资故意用拉萨席位), 但标出具体营业部, 不合并成一个"拉萨天团"
const yzName = (s) => { const y = YOUZI[s]; return y === "拉萨天团" ? `${s.replace(/^东方财富 /, "")}证券营业部` : y; };   // 用户: 直接写营业部原名, 如 拉萨金融城南环路证券营业部
function seatShort(n) {
    n = (n || "").trim();
    const m = n.match(/^(.*?)(股份有限公司|有限责任公司|有限公司)(.*)$/);
    if (!m) return n;                                       // 机构专用/深股通专用/沪股通专用/自然人 等原样
    const broker = m[1].replace(/证券/, "");
    const br = m[3].replace(/(证券)?营业部$/, "").trim();
    return br ? `${broker} ${br}` : broker;
}
function shortReason(s) {
    const p3 = /连续(三|3)个交易日/.test(s) ? "3日" : "";
    const bj = /^北交所/.test(s) ? "北交所" : "";
    let m;
    if (/无价格涨跌幅限制/.test(s)) return "无涨跌幅限制";
    if (/可转债.*上市首日|上市首日.*可转债/.test(s)) return "可转债上市首日";
    if ((m = s.match(/融资买入.*?(\d+)[%％]以上/))) return `融资买入占比≥${m[1]}%`;
    if ((m = s.match(/涨跌幅偏离值(?:累计)?达到?\+?(\d+)%\(-(\d+)%\)/))) return `${bj}${p3}偏离+${m[1]}%/-${m[2]}%`;
    if ((m = s.match(/(涨|跌)幅偏离值(?:累计)?达到?[+-]?(\d+)%/))) return `${p3}${m[1]}幅偏离${m[2]}%`;
    if ((m = s.match(/振幅(?:值)?达到?(\d+)%/))) return `${p3}振幅${m[1]}%`;
    if ((m = s.match(/换手率(?:累计)?达到?(\d+)%/))) return `${p3}换手${m[1]}%`;
    if ((m = s.match(/(涨|跌)幅(?:累计)?达到?[+-]?(\d+)%/))) return `${p3}${m[1]}幅${m[2]}%`;
    return s.replace(/的?(前[5五]只)?(证券|股票)$/, "");
}
// 金额(元) → md 显示(用户 10/14 定): |v|<1亿 → "xxxx万"(≥100万取整, 否则 1 位小数); ≥1亿 → "x.xx亿"; 单位紧跟数字
const amt = (v, sign = false) => {
    const x = +v || 0;
    const a = Math.abs(x);
    let s;
    if (a >= 1e8 || (a / 1e4).toFixed(0) === "10000") s = (a / 1e8).toFixed(2) + "亿";
    else {
        const w = a / 1e4;
        s = w >= 100 ? w.toFixed(0) : w.toFixed(1);
        if (s === "0" || s === "0.0") return "0";
        s += "万";
    }
    return (x < 0 ? "-" : sign ? "+" : "") + s;
};
const pct = (v) => (v == null ? "-" : `${v > 0 ? "+" : ""}${(+v).toFixed(2)}%`);
const esc = (s) => String(s).replace(/\*/g, "\\*").replace(/\|/g, "／");
const isThreeDay = (r) => /连续/.test(r.EXPLANATION || "");   // 多日累计口径(连续 3 日/北交所连续 3 日/连续 10 日内多次异常); 主记录优先取当日口径

function build(list, details) {
    const by = new Map();
    for (const r of list) { if (!by.has(r.SECURITY_CODE)) by.set(r.SECURITY_CODE, []); by.get(r.SECURITY_CODE).push(r); }
    const stocks = [];
    for (const [code, rows] of by) {
        const prim = rows.find((r) => !isThreeDay(r)) || rows[0];    // 主记录: 当日口径优先, 只有 3 日累计时用它
        const d = details[code] || { buy: [], sell: [] };
        const buy = d.buy.filter((x) => String(x.TRADE_ID) === String(prim.TRADE_ID)).sort((a, b) => b.BUY - a.BUY);
        const sell = d.sell.filter((x) => String(x.TRADE_ID) === String(prim.TRADE_ID)).sort((a, b) => b.SELL - a.SELL);
        // 同一席位可能同时在买五与卖五: 卖五里与买五"名+买+卖"完全相同的行一对一抵消; 同榜内真重复的行(如两个机构专用同额, 实测 127114 07/14)保留
        const uniq = [...buy];
        const pool = buy.map((x) => `${x.OPERATEDEPT_NAME}|${x.BUY}|${x.SELL}`);
        for (const x of sell) {
            const k = pool.indexOf(`${x.OPERATEDEPT_NAME}|${x.BUY}|${x.SELL}`);
            if (k >= 0) pool[k] = null; else uniq.push(x);
        }
        const sum = (f) => uniq.filter(f).reduce((a, x) => a + (+x.NET || 0), 0);
        const has = (f) => uniq.some(f);
        const jg = (x) => /^机构(专用|投资者)?$/.test(x.OPERATEDEPT_NAME);              // 主板=机构专用; 北交所/可转债榜写法=机构投资者/机构
        const bx = (x) => /^(深股通|沪股通)(专用|投资者)?$/.test(x.OPERATEDEPT_NAME);
        const yz = new Map();
        for (const x of uniq) { const n = yzName(seatShort(x.OPERATEDEPT_NAME)); if (n) yz.set(n, (yz.get(n) || 0) + (+x.NET || 0)); }
        stocks.push({
            code, name: prim.SECURITY_NAME_ABBR, prim, rows, buy, sell,
            reasons: [...new Set(rows.map((r) => shortReason(r.EXPLANATION)))],
            jg: has(jg) ? sum(jg) : null, jgB: buy.filter(jg).length, jgS: sell.filter(jg).length,
            bx: has(bx) ? sum(bx) : null, yz,
        });
    }
    stocks.sort((a, b) => b.prim.BILLBOARD_NET_AMT - a.prim.BILLBOARD_NET_AMT);
    return stocks;
}

// #### 概况 总表: 表头+分隔行从模板 stock-template.md 的 ### 龙虎榜 下第一张表现读(用户改模板脚本自动跟上, 不写死);
// 每列按表头名查 COL_VALUE 取值, 表头名不认识的列填 "-" 并在 JSON 里报 unknown_cols. 空值一律 "-"
const COL_VALUE = {
    股票: (s) => `${esc(s.name)} ${s.code}`,
    上榜原因: (s) => s.reasons.join("; "),
    涨跌: (s) => pct(s.prim.CHANGE_RATE),
    买入: (s) => amt(s.prim.BILLBOARD_BUY_AMT),                 // 买五合计
    卖出: (s) => amt(s.prim.BILLBOARD_SELL_AMT),                // 卖五合计
    净额: (s) => amt(s.prim.BILLBOARD_NET_AMT, true),           // 买五卖五合计净买入
    龙虎榜净额: (s) => amt(s.prim.BILLBOARD_NET_AMT, true),
    机构: (s) => (s.jg == null ? "-" : `${amt(s.jg, true)}(${s.jgB ? s.jgB + "买" : ""}${s.jgS ? s.jgS + "卖" : ""})`),
    北向: (s) => (s.bx == null ? "-" : amt(s.bx, true)),
    游资: (s) => yzCell(s.yz),
    知名游资: (s) => yzCell(s.yz),
};
function templateTable() {
    const T = fs.readFileSync("inv-stock/src/main/resources/templates/stock-template.md", "utf8").replace(/\r/g, "").split("\n");
    const i = T.findIndex((l) => l.trim() === "### 龙虎榜");
    const rows = [];
    for (let k = i + 1; i >= 0 && k < T.length && !/^#{1,3} /.test(T[k]); k++) {
        if (/^\|/.test(T[k])) rows.push(T[k].trim());
        else if (rows.length) break;
    }
    if (rows.length < 2) throw new Error("模板 stock-template.md 的 ### 龙虎榜 下找不到表头+分隔行");
    const cells = (l) => l.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
    const head = cells(rows[0]);
    let sep = cells(rows[1]);
    if (sep.length !== head.length || !sep.every((c) => /^:?-+:?$/.test(c))) sep = head.map(() => ":--:");   // 模板分隔行列数不对(曾误写 13 列)→ 按表头列数生成
    const unknown = head.filter((h) => !COL_VALUE[h]);
    if (unknown.length) out.unknown_cols = unknown;
    return { head, sep, fns: head.map((h) => COL_VALUE[h] || (() => "-")) };
}

const seatLabel = (x) => { const s = seatShort(x.OPERATEDEPT_NAME); const y = YOUZI[s]; return esc(s) + (y ? `(${y})` : ""); };   // 明细里席位名本身已含营业部
const yzCell = (m) => [...m].map(([n, v]) => `${n}${amt(v, true)}`).join(" ") || "-";

function render(stocks, nRecords) {
    const top = (arr, k, dir) => arr.filter((s) => s[k] != null && s[k] * dir > 0).sort((a, b) => (b[k] - a[k]) * dir).slice(0, 3)
        .map((s) => `${esc(s.name)} ${amt(s[k], true)}`).join("、") || "无";
    const yzCount = new Map();
    for (const s of stocks) for (const n of s.yz.keys()) yzCount.set(n, (yzCount.get(n) || 0) + 1);
    const bxBuy = top(stocks, "bx", 1).split("、")[0];
    const bxSell = top(stocks, "bx", -1).split("、")[0];
    const head = `上榜 ${stocks.length} 只(${nRecords} 条记录); 机构净买前三: ${top(stocks, "jg", 1)}; 机构净卖前三: ${top(stocks, "jg", -1)}; `
        + `北向净买最多: ${bxBuy}; 北向净卖最多: ${bxSell}; 游资: ${[...yzCount].sort((a, b) => b[1] - a[1]).map(([n, c]) => `${n}×${c}`).join(" ") || "无"}`;
    const TB = templateTable();
    const L = ["### 龙虎榜", "", "#### 概况", "", head, "",
        "| " + TB.head.join(" | ") + " |",
        "| " + TB.sep.join(" | ") + " |"];
    for (const s of stocks) L.push("| " + TB.fns.map((f) => f(s)).join(" | ") + " |");
    L.push("", `原始数据: ${DIR.replace(/\\/g, "/")}/(${out.source === "sina" ? "新浪龙虎榜(东财失败时的备源, 涨跌取本地日线)" : "东财 datacenter-web"}; 主记录=当日口径, 只有 3 日累计榜时用 3 日数据; 买入/卖出/净额=买五卖五合计, 机构/游资=买五卖五去重后净额, 机构括号=在买五/卖五里出现的次数)`, "");
    for (const s of stocks) {
        const p = s.prim;
        const multiTag = (r) => (/连续(三|3)个交易日/.test(r.EXPLANATION) ? "3日" : "多日");
        const extra = s.rows.filter((r) => r !== p && isThreeDay(r) && !isThreeDay(p)).map((r) => `${multiTag(r)}累计榜净额 ${amt(r.BILLBOARD_NET_AMT, true)}`);
        L.push(`#### ${esc(s.name)} ${s.code}`, "",
            `- 上榜: ${s.reasons.join("; ")} · 涨跌 ${pct(p.CHANGE_RATE)} · 成交额 ${amt(p.ACCUM_AMOUNT)} · 净额 ${amt(p.BILLBOARD_NET_AMT, true)}`
            + `(买 ${amt(p.BILLBOARD_BUY_AMT)} 卖 ${amt(p.BILLBOARD_SELL_AMT)})${isThreeDay(p) ? ` · ${multiTag(p)}累计口径` : ""}${extra.length ? " · " + extra.join(" · ") : ""}`,
            `- 买: ${s.buy.map((x) => `${seatLabel(x)} ${amt(x.BUY)}`).join(" / ") || "-"}`,
            `- 卖: ${s.sell.map((x) => `${seatLabel(x)} ${amt(x.SELL)}`).join(" / ") || "-"}`, "");
    }
    return L;
}

// ---------- md 挂载: ## 复盘 → ### 龙虎榜 整节覆盖 ----------
// 缺 ### 龙虎榜 骨架(Java 旧模板生成的日子): 先用用户常备工具 migrate_md_template.mjs 补骨架(它只收目录, 故拷到临时目录跑再拷回; 期间原文件被别人改了就不拷回)
function migrateSkeleton(md) {
    const tmp = fs.mkdtempSync(path.join("scripts", "temp", "lhb_mig_"));
    try {
        const before = fs.readFileSync(md, "utf8");
        const f = path.join(tmp, path.basename(md));
        fs.writeFileSync(f, before);
        const r = spawnSync(process.execPath, ["scripts/md/migrate_md_template.mjs", tmp], { encoding: "utf8", windowsHide: true, timeout: 60000 });
        const after = fs.readFileSync(f, "utf8");
        if (r.status !== 0 || after === before || fs.readFileSync(md, "utf8") !== before) return false;
        fs.writeFileSync(md, after);
        out.migrated = true;
        return true;
    } finally {
        fs.rmSync(tmp, { recursive: true, force: true });
    }
}

function mount(block) {
    const [y, m] = DATE.split("-");
    const md = path.join("md", `${y}S${Math.ceil(+m / 3)}`, `${DATE}.md`);
    if (!fs.existsSync(md)) return { code: 4, md: "无md" };
    let text = fs.readFileSync(md, "utf8");
    if (/^## 复盘[ \t]*\r?$/m.test(text) && !/^### 龙虎榜[ \t]*\r?$/m.test(text) && migrateSkeleton(md)) text = fs.readFileSync(md, "utf8");
    const lines = text.split("\n");
    const bare = (l) => l.replace(/\r$/, "").trim();
    const fi = lines.findIndex((l) => bare(l) === "## 复盘");
    if (fi === -1) return { code: 0, md: "无复盘节(只存json)" };
    let fEnd = lines.length;
    for (let i = fi + 1; i < lines.length; i++) if (/^## /.test(lines[i])) { fEnd = i; break; }
    let hi = -1;
    for (let i = fi + 1; i < fEnd; i++) if (bare(lines[i]) === "### 龙虎榜") { hi = i; break; }
    let hEnd;
    if (hi === -1) {   // 骨架缺节: 插在 ### 复盘持仓 节之后(其后第一个 ### 之前), 无复盘持仓则插在 ## 复盘 之后第一个 ### 前
        const ci = lines.findIndex((l, i) => i > fi && i < fEnd && bare(l) === "### 复盘持仓");
        let at = fEnd;
        for (let i = (ci === -1 ? fi : ci) + 1; i < fEnd; i++) if (/^#{1,3} /.test(lines[i])) { at = i; break; }
        hi = hEnd = at;
    } else {
        hEnd = lines.length;
        for (let i = hi + 1; i < lines.length; i++) if (/^#{1,3} /.test(lines[i])) { hEnd = i; break; }
    }
    const eol = hi < lines.length && lines[hi].endsWith("\r") ? "\r" : "";
    const blk = block.map((l) => l + eol);
    const old = lines.slice(hi, hEnd).join("\n");
    if (old === blk.join("\n")) return { code: 0, md: "无变化" };
    lines.splice(hi, hEnd - hi, ...blk);
    fs.writeFileSync(md, lines.join("\n"));
    return { code: 0, md: "已写" };
}

// ---------- main ----------
try {
    let data = FORCE && !LOCAL ? null : loadCached();
    if (data) {
        out.cached = true;
        out.source = data.source || out.source;
    } else if (LOCAL) {
        done(6, "本地 json 不完整(--local 不联网, 未请求)");
    } else {
        // 10/17 A12 switch-case 转移: 东财(主) → 新浪(备, 近 7 天自动; 历史日不自动以免 backfill 大批量打新浪); --source 强制单源
        let got;
        if (SOURCE === "ths") got = await fetchThs(DATE);
        else if (SOURCE === "sina") got = await fetchSina(DATE);
        else {
            try {
                if (process.env.LHB_DRILL === "em") throw new Error("演练: 跳过东财");
                got = await fetchEm(DATE);
            } catch (e) {
                const recent = DATE >= new Date(Date.now() + 8 * 3600e3 - 7 * 86400e3).toISOString().slice(0, 10);
                if (e instanceof Exit || !recent || ARGS.includes("--no-fallback")) throw e;
                console.error(`[lhb] 东财失败(${String(e.message || e).slice(0, 120)}) → 切新浪备源`);
                out.fallback = `东财失败: ${String(e.message || e).slice(0, 120)}`;
                out.source = "sina";
                got = await fetchSina(DATE);
            }
        }
        if (!got.list.length) { out.secs = +((Date.now() - T0) / 1000).toFixed(1); done(3, `当日龙虎榜未出(${out.source === "sina" ? "新浪" : "东财"}返回空)`); }
        out.fetched_at = save(got.list, got.details);
        out.fetched = true;
        if (!(out.fetched_at >= `${DATE} ${READY_HHMM}`)) out.provisional = true;   // 当日 18:00 前抓的: 下次重抓
        data = { list: got.list, details: got.details };
    }
    const stocks = build(data.list, data.details);
    out.stocks = stocks.length;
    out.records = data.list.length;
    out.no_seat = stocks.filter((s) => !s.buy.length && !s.sell.length).map((s) => s.code);
    if (WRITE) {
        const r = mount(render(stocks, data.list.length));
        out.md = r.md;
        if (r.code) { out.secs = +((Date.now() - T0) / 1000).toFixed(1); done(r.code, "当日 md 不存在"); }
    }
    out.secs = +((Date.now() - T0) / 1000).toFixed(1);
    console.log(`[lhb] ${DATE}: ${stocks.length} 只/${data.list.length} 条, ${out.cached ? "用缓存" : `抓取 ${out.requests} 次请求`}, ${out.secs}s${WRITE ? `, md=${out.md}` : ""}`);
    done(0);
} catch (e) {
    out.secs = +((Date.now() - T0) / 1000).toFixed(1);
    if (e instanceof Exit) out.code = e.code;
    else { out.code = e instanceof Ban ? 5 : 1; out.msg = String(e.message || e); }
}
console.log("JSON:" + JSON.stringify(out));
process.exitCode = out.code;
