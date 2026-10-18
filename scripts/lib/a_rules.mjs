// a_rules.mjs — A 股交易规则统一模块(2026-10-16 建; 与 a_rules.py 同口径, 共用样例 a_rules_cases.json 互相对照)
// 规则出处与生效日期见 docs/rules/a_share_trading_rules.md。只管"规则", 不取行情、不写库; JS 版不查数据库(ST/上市日靠参数或名称)。
// 历史回放必须传 date(按当日规则); date 省略=今天。
// 接口(与 Python 同名, 驼峰别名同时导出):
//   board(code) / limitBand(code, date, opt) / limitPct(code, date, opt) / limitPrices(code, date, prevClose, opt)
//   atLimitUp/atLimitDown(code, date, prevClose, price, opt) / priceCage(code, date, side, base, listingN) / cageReject(code, date)
//   tick(code) / priceDecimals(code) / lotRule(code) / validQty(code, qty, side, held) / roundQty(code, qty)
//   isT0(code, name) / volumeUnit(source, code) / fees(side, amount, code, date, {commissionRate, minCommission, includeHandling})
//   sessions(date, code) / phaseAt(code, date, "HH:MM:SS") / listingDay(code, date, listDate, name) / countTradeDays(d0, d1)
//   opt = { name, listDate, isSt, listingN, phase }
// CLI: node scripts/lib/a_rules.mjs --selftest | --dump(供 a_rules.py 对照)
import fs from "node:fs";

const CASES = new URL("./a_rules_cases.json", import.meta.url);
const CAL_FILE = new URL("../../downloads/quotes/daily/1_000001.json", import.meta.url);
const HOLIDAY_DIR = new URL("../../inv-common/src/main/resources/holiday/", import.meta.url);

export const D_STAR_OPEN = "2019-07-22";
export const D_GEM_REG = "2020-08-24";
export const D_BSE_OPEN = "2021-11-15";
export const D_TRANSFER_FEE_HALF = "2022-04-29";
export const D_CB_RULE = "2022-08-01";
export const D_MAIN_REG = "2023-04-10";
export const D_STAMP_HALF = "2023-08-28";
export const D_RULES_2026 = "2026-07-06";
const STOCK_BOARDS = ["MAIN", "GEM", "STAR", "BSE"];
const FUND_BOARDS = ["ETF", "LOF", "REITS"];
const sw = (c, ...ps) => ps.some((p) => c.startsWith(p));

// ---------------- 代码 / 日期 ----------------
export function norm(code) {
    const s = String(code).trim();
    let m = s.match(/^(sh|sz|bj|hk)\.?(\d{5,6})$/i);
    if (m) return [m[1].toLowerCase(), m[2]];
    m = s.match(/^(\d{5,6})\.(sh|sz|bj|hk|ss)$/i);
    if (m) { const ex = m[2].toLowerCase(); return [ex === "ss" ? "sh" : ex, m[1]]; }
    if (/^\d{5}$/.test(s)) return ["hk", s];
    if (/^\d{1,6}$/.test(s)) {
        const c = s.padStart(6, "0");
        if (sw(c, "4", "8", "92")) return ["bj", c];
        if (sw(c, "6", "900", "5", "11", "204")) return ["sh", c];
        return ["sz", c];
    }
    return [null, s];
}
export const symbol = (code) => { const [ex, c] = norm(code); return ex ? ex + c : c; };
const pad = (n) => String(n).padStart(2, "0");
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export function ndate(d) {
    if (d === undefined || d === null) return iso(new Date());
    if (d instanceof Date) return iso(d);
    const s = String(d).trim().slice(0, 10);
    return /^\d{8}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6)}` : s;
}

export function board(code) {
    const [ex, c] = norm(code);
    if (ex === "hk") return "HK";
    if (ex === "bj") return c.startsWith("899") ? "INDEX" : "BSE";
    if (ex === "sh") {
        if (c.startsWith("000")) return "INDEX";
        if (sw(c, "600", "601", "603", "605")) return "MAIN";
        if (sw(c, "688", "689")) return "STAR";
        if (sw(c, "110", "111", "113", "118")) return "CB";
        if (c.startsWith("508")) return "REITS";
        if (sw(c, "501", "502", "506")) return "LOF";
        if (sw(c, "51", "52", "53", "56", "58")) return "ETF";
        if (c.startsWith("900")) return "BSHARE";
        if (c.startsWith("204")) return "REPO";
        return "OTHER";
    }
    if (ex === "sz") {
        if (sw(c, "000", "001", "002", "003", "004")) return "MAIN";
        if (sw(c, "300", "301", "302")) return "GEM";
        if (sw(c, "123", "127", "128")) return "CB";
        if (c.startsWith("159")) return "ETF";
        if (c.startsWith("16")) return "LOF";
        if (c.startsWith("180")) return "REITS";
        if (c.startsWith("399")) return "INDEX";
        if (c.startsWith("20")) return "BSHARE";
        if (c.startsWith("131")) return "REPO";
    }
    return "OTHER";
}
export const BOARD_CN = { MAIN: "沪深主板", GEM: "创业板", STAR: "科创板", BSE: "北交所", CB: "可转债", ETF: "ETF", LOF: "LOF",
    REITS: "REITs", INDEX: "指数", REPO: "逆回购", BSHARE: "B股", HK: "港股", OTHER: "其他" };

// ---------------- 名称信号 ----------------
export const isStName = (name) => !!name && String(name).toUpperCase().includes("ST");
export const isDelistName = (name) => !!name && String(name).trimEnd().endsWith("退");
const FUND20_RE = /科创|创业|双创|创成长|创50|创100|创蓝筹|创价值|创医药|创科技|创新能/;
const T0_RE = new RegExp("债|货币|现金|理财|快线|添益|日利|黄金|金ETF|上海金|白银|豆粕|有色|能源化工|商品|原油|油气|" +
    "纳指|纳斯达克|标普|道琼斯|美国|美股|日经|日本|东证|德国|法国|欧洲|英国|恒生|港股|H股|香港|中概|海外|" +
    "亚太|沙特|东南亚|越南|印度|巴西|QDII|全球|中韩|韩国|新兴|港美|恒指|恒科|港科|港中小|港红利|港消费|港医");

// ---------------- 交易日历 ----------------
let CAL = null;
export function tradeDays() {
    if (CAL === null) {
        try { CAL = JSON.parse(fs.readFileSync(CAL_FILE, "utf8")).klines.map((k) => k.d); } catch { CAL = []; }
    }
    return CAL;
}
const HOL = {};
function isTradeDayFallback(d) {
    const y = d.slice(0, 4);
    if (!(y in HOL)) { try { HOL[y] = JSON.parse(fs.readFileSync(new URL(`${y}.json`, HOLIDAY_DIR), "utf8")); } catch { HOL[y] = {}; } }
    const wd = new Date(`${d}T12:00:00`).getDay();
    return wd >= 1 && wd <= 5 && HOL[y][d] !== true;
}
const bisectL = (a, x) => { let lo = 0, hi = a.length; while (lo < hi) { const m = (lo + hi) >> 1; if (a[m] < x) lo = m + 1; else hi = m; } return lo; };
const bisectR = (a, x) => { let lo = 0, hi = a.length; while (lo < hi) { const m = (lo + hi) >> 1; if (a[m] <= x) lo = m + 1; else hi = m; } return lo; };
const addDay = (d, k) => { const x = new Date(`${d}T12:00:00`); x.setDate(x.getDate() + k); return iso(x); };
export function countTradeDays(d0, d1) {
    d0 = ndate(d0); d1 = ndate(d1);
    if (d0 > d1) return 0;
    const cal = tradeDays();
    const last = cal.length ? cal[cal.length - 1] : "0000-00-00";
    let n = 0;
    if (cal.length && d0 <= last) n += bisectR(cal, d1 < last ? d1 : last) - bisectL(cal, d0);
    let x = cal.length ? (d0 > addDay(last, 1) ? d0 : addDay(last, 1)) : d0;
    while (x <= d1) { n += isTradeDayFallback(x) ? 1 : 0; x = addDay(x, 1); }
    return n;
}
export function listingDay(code, date, listDate, name) {
    date = ndate(date);
    if (listDate) { const ld = ndate(listDate); return ld <= date ? countTradeDays(ld, date) : 0; }
    if (name) {
        const n = String(name).trim();
        if (n.startsWith("N")) return 1;
        if (n.startsWith("C") && ["MAIN", "GEM", "STAR"].includes(board(code))) return 2;
    }
    return null;
}

// ---------------- 涨跌幅 ----------------
export function limitBand(code, date, opt = {}) {
    const { name = null, listDate = null, listingN = null, phase = null } = opt;
    let { isSt = null } = opt;
    const b = board(code);
    date = ndate(date);
    if (phase === "退市整理首日" || phase === "重新上市首日") return STOCK_BOARDS.includes(b) ? null : baseBand(b, code, name, date, null);
    const n = STOCK_BOARDS.includes(b) || b === "CB" || b === "REITS" ? (listingN ?? listingDay(code, date, listDate, name)) : null;
    if (STOCK_BOARDS.includes(b)) {
        if (isSt === null || isSt === undefined) isSt = name !== null && name !== undefined ? isStName(name) : false;
        const ld = listDate ? ndate(listDate) : null;
        if (n !== null && n >= 1) {
            if (b === "BSE") { if (n === 1) return null; }
            else if (b === "STAR") { if (n <= 5) return null; }
            else if (b === "GEM") {
                if (date >= D_GEM_REG && (ld === null || ld >= D_GEM_REG) && n <= 5) return null;
                if (date < D_GEM_REG && n === 1) return [0.44, 0.36];
            } else {
                const reg = ld ? ld >= D_MAIN_REG : date >= D_MAIN_REG;
                if (reg && n <= 5) return null;
                if (!reg && n === 1) return [0.44, 0.36];
            }
        }
        return stockBand(b, date, isSt, name);
    }
    if (b === "CB") {
        if (date < D_CB_RULE) return null;
        return n === 1 ? [0.573, 0.433] : [0.2, 0.2];
    }
    if (b === "REITS") return n === 1 ? [0.3, 0.3] : [0.1, 0.1];
    return baseBand(b, code, name, date, n);
}
function stockBand(b, date, isSt, name) {
    if (b === "BSE") return [0.3, 0.3];
    if (b === "STAR") return [0.2, 0.2];
    if (b === "GEM") return date >= D_GEM_REG ? [0.2, 0.2] : isSt ? [0.05, 0.05] : [0.1, 0.1];
    if (isDelistName(name)) return [0.1, 0.1];
    if (isSt && date < D_RULES_2026) return [0.05, 0.05];
    return [0.1, 0.1];
}
function baseBand(b, code, name, date, n) {
    if (b === "ETF" || b === "LOF") {
        const c = norm(code)[1];
        if ((b === "ETF" && sw(c, "588", "589")) || (name && FUND20_RE.test(String(name)))) return [0.2, 0.2];
        return [0.1, 0.1];
    }
    if (b === "REITS") return n === 1 ? [0.3, 0.3] : [0.1, 0.1];
    if (b === "BSHARE") return [0.1, 0.1];
    return null;
}
export function limitPct(code, date, opt = {}) { const band = limitBand(code, date, opt); return band === null ? null : band[0]; }

// ---------------- 价位 ----------------
export function tick(code) {
    const b = board(code);
    if (["CB", "ETF", "LOF", "REITS"].includes(b)) return 0.001;
    if (b === "BSHARE" && norm(code)[0] === "sh") return 0.001;
    return 0.01;
}
export const priceDecimals = (code) => (tick(code) < 0.005 ? 3 : 2);
const tickI = (code) => (tick(code) < 0.005 ? 100000 : 1000000);   // 1e-8 元
const rhu = (xi, ti) => Math.floor((xi + ti / 2) / ti) * ti;
const px = (v, code) => Number((v / 1e8).toFixed(priceDecimals(code)));

export function limitPrices(code, date, prevClose, opt = {}) {
    if (!(prevClose > 0)) return [null, null];
    const band = limitBand(code, date, opt);
    if (band === null) return [null, null];
    const ti = tickI(code);
    const p4 = Math.round(prevClose * 10000), pi = p4 * 10000;
    let upi = rhu(p4 * (10000 + Math.round(band[0] * 10000)), ti);
    let dni = rhu(p4 * (10000 - Math.round(band[1] * 10000)), ti);
    if (upi - pi < ti) upi = pi + ti;
    if (pi - dni < ti) dni = pi - ti;
    if (dni < ti) dni = ti;
    return [px(upi, code), px(dni, code)];
}
export function atLimitUp(code, date, prevClose, price, opt = {}) {
    const [up] = limitPrices(code, date, prevClose, opt);
    return up !== null && price !== null && price !== undefined && price >= up - tick(code) / 2;
}
export function atLimitDown(code, date, prevClose, price, opt = {}) {
    const [, dn] = limitPrices(code, date, prevClose, opt);
    return dn !== null && price !== null && price !== undefined && price <= dn + tick(code) / 2;
}
export function priceCage(code, date, side = "BUY", base = null, listingN = null) {
    if (!(base > 0)) return null;
    const b = board(code); date = ndate(date);
    const ti = tickI(code), b4 = Math.round(base * 10000), bi = b4 * 10000;
    const buy = String(side).toUpperCase().startsWith("B");
    const pt = (p, k) => {
        const pp = Math.trunc(p * 10000 + 1e-9);
        if (buy) return px(Math.max(rhu(b4 * (10000 + pp), ti), bi + k * ti), code);
        return px(Math.min(rhu(b4 * (10000 - pp), ti), bi - k * ti), code);
    };
    if (b === "STAR" && date >= D_STAR_OPEN) return pt(0.02, 0);
    if (b === "GEM") { if (date >= D_MAIN_REG) return pt(0.02, 10); if (date >= D_GEM_REG) return pt(0.02, 0); return null; }
    if (b === "MAIN" && date >= D_MAIN_REG) return pt(0.02, 10);
    if (b === "BSE") return pt(0.05, 10);
    if (b === "CB" && date >= D_CB_RULE && listingN === 1) return pt(0.1, 0);
    return null;
}
export const cageReject = (code, date) => !(board(code) === "GEM" && D_GEM_REG <= ndate(date) && ndate(date) < D_MAIN_REG);

// ---------------- 申报数量 ----------------
export function lotRule(code) {
    const b = board(code);
    if (b === "STAR") return { min: 200, step: 1, max_limit: 100000, max_market: 50000, unit: "股" };
    if (b === "BSE") return { min: 100, step: 1, max_limit: 1000000, max_market: 1000000, unit: "股" };
    if (b === "GEM") return { min: 100, step: 100, max_limit: 300000, max_market: 150000, unit: "股" };
    if (b === "CB") return { min: 10, step: 10, max_limit: 1000000, max_market: 1000000, unit: "张" };
    if (FUND_BOARDS.includes(b)) return { min: 100, step: 100, max_limit: 1000000, max_market: 1000000, unit: "份" };
    return { min: 100, step: 100, max_limit: 1000000, max_market: 1000000, unit: "股" };
}
export function validQty(code, qty, side = "BUY", held = null, market = false) {
    const r = lotRule(code);
    if (!Number.isInteger(+qty) || +qty <= 0) return [false, "数量须为正整数"];
    const q = +qty, mx = market ? r.max_market : r.max_limit;
    if (q > mx) return [false, `单笔上限 ${mx}${r.unit}`];
    const sell = String(side).toUpperCase().startsWith("S");
    if (sell && held !== null && held !== undefined) {
        const h = Math.trunc(+held);
        if (q > h) return [false, "超过持仓"];
        if (q === h) return [true, "清仓(含零股一次性卖出)"];
        if (r.step === r.min && q % r.step === h % r.step) return [true, "零股部分一次性卖出"];
    }
    if (q < r.min) return [false, `不足最小申报 ${r.min}${r.unit}`];
    if ((q - r.min) % r.step) return [false, r.step !== r.min ? `须为 ${r.min}${r.unit} 起、${r.step}${r.unit} 递增` : `须为 ${r.step}${r.unit} 整数倍`];
    return [true, ""];
}
export function roundQty(code, qty) {
    const r = lotRule(code), q = Math.trunc(qty);
    if (q < r.min) return 0;
    return Math.min(r.max_limit, r.min + Math.floor((q - r.min) / r.step) * r.step);
}

// ---------------- T+0 ----------------
export function isT0(code, name = null) {
    const b = board(code);
    if (b === "CB") return true;
    if (b === "ETF" || b === "LOF") {
        const c = norm(code)[1];
        if (b === "ETF" && sw(c, "511", "518", "513")) return true;
        return !!(name && T0_RE.test(String(name)));
    }
    return false;
}

// ---------------- 成交量单位 ----------------
const VOL = {
    tencent_qt: { default: 100, STAR: 1, CB: 10 }, tencent_kline: { default: 100, STAR: 1, CB: 10 }, sina: { default: 1, INDEX_SH: 100 },
    em: { default: 100, CB: 10 }, tdx: { default: 100, CB: 10 }, db: { default: 1 }, tzzb: { default: 1 },
};
const VOL_ALIAS = { tencent: "tencent_qt", qt: "tencent_qt", tencent_batch: "tencent_qt", ifzq: "tencent_kline", dfcf: "em", eastmoney: "em",
    em_push2: "em", pytdx: "tdx", tdx_mt: "tdx", kline_day: "db", market_db: "db" };
export function volumeUnit(source, code) {
    const s = String(source).toLowerCase(), src = VOL_ALIAS[s] || s, t = VOL[src];
    if (!t) throw new Error(`未知成交量源 ${source}(已知: ${Object.keys(VOL).sort().join(",")})`);
    const b = board(code);
    if (b === "INDEX" && norm(code)[0] === "sh" && "INDEX_SH" in t) return t.INDEX_SH;
    return t[b] ?? t.default;
}

// ---------------- 费用 ----------------
const r2 = (x) => Math.floor(x * 100 + 0.5 + 1e-9) / 100;
export function fees(side, amount, code, date, { commissionRate = 0.00025, minCommission = 5, includeHandling = false } = {}) {
    amount = +amount;
    const b = board(code); date = ndate(date);
    const sell = String(side).toUpperCase().startsWith("S");
    const comm = amount > 0 ? Math.max(minCommission, amount * commissionRate) : 0;
    let stamp = 0, transfer = 0, handling = 0;
    if (sell && (STOCK_BOARDS.includes(b) || b === "BSHARE")) stamp = amount * (date >= D_STAMP_HALF ? 0.0005 : 0.001);
    if (STOCK_BOARDS.includes(b)) transfer = amount * (date >= D_TRANSFER_FEE_HALF ? 0.00001 : b === "BSE" ? 0.000025 : 0.00002);
    if (includeHandling && STOCK_BOARDS.includes(b))
        handling = amount * (b === "BSE" ? (date >= D_STAMP_HALF ? 0.000125 : 0.00025) : (date >= D_STAMP_HALF ? 0.0000341 : 0.0000487));
    return { commission: r2(comm), stamp: r2(stamp), transfer: r2(transfer), handling: r2(handling),
        total: r2(r2(comm) + r2(stamp) + r2(transfer) + r2(handling)) };
}

// ---------------- 交易时段 ----------------
export function sessions(date, code = null) {
    date = ndate(date);
    if (!countTradeDays(date, date)) return [];
    const b = code ? board(code) : "MAIN", ex = code ? norm(code)[0] : "sh";
    const out = [["开盘集合竞价", "09:15:00", "09:20:00", true], ["开盘集合竞价", "09:20:00", "09:25:00", false], ["连续竞价", "09:30:00", "11:30:00", true]];
    if (b === "CB" && ex === "sh") out.push(["连续竞价", "13:00:00", "15:00:00", true]);
    else if (FUND_BOARDS.includes(b) && ex === "sh" && date < D_RULES_2026) out.push(["连续竞价", "13:00:00", "15:00:00", true]);
    else out.push(["连续竞价", "13:00:00", "14:57:00", true], ["收盘集合竞价", "14:57:00", "15:00:00", false]);
    let after = false;
    if (b === "STAR" && date >= D_STAR_OPEN) after = true;
    else if (b === "GEM" && date >= D_GEM_REG) after = true;
    else if (date >= D_RULES_2026 && ["MAIN", "GEM", "STAR", "ETF"].includes(b)) after = true;
    if (after) out.push(["盘后固定价格", "15:05:00", "15:30:00", true]);
    return out;
}
export function phaseAt(code, date, t) {
    t = String(t).length === 5 ? `${t}:00` : String(t).slice(0, 8);
    for (const [name, a, b, can] of sessions(date, code))
        if ((a <= t && t < b) || (t === b && (b === "11:30:00" || b === "15:00:00") && name !== "盘后固定价格")) return [name, can];
    return [null, null];
}

// 驼峰/下划线别名(与 Python 名对齐, 方便两边对照)
export { limitBand as limit_band, limitPct as limit_pct, limitPrices as limit_prices, lotRule as lot_rule, isT0 as is_t0, volumeUnit as volume_unit,
    priceCage as price_cage, validQty as valid_qty, roundQty as round_qty, countTradeDays as count_trade_days, phaseAt as phase_at };

// ---------------- selftest / dump ----------------
function evalCase(c) {
    const a = c.args, o = { name: a.name ?? null, listDate: a.list_date ?? null, isSt: a.is_st ?? null, listingN: a.listing_n ?? null, phase: a.phase ?? null };
    switch (c.fn) {
        case "limit_prices": return limitPrices(a.code, a.date, a.prev_close, o);
        case "limit_band": { const r = limitBand(a.code, a.date, o); return r === null ? null : [r[0], r[1]]; }
        case "board": return board(a.code);
        case "tick": return tick(a.code);
        case "lot_rule": { const r = lotRule(a.code); return [r.min, r.step, r.max_limit]; }
        case "valid_qty": return validQty(a.code, a.qty, a.side ?? "BUY", a.held ?? null)[0];
        case "round_qty": return roundQty(a.code, a.qty);
        case "is_t0": return isT0(a.code, a.name ?? null);
        case "volume_unit": return volumeUnit(a.source, a.code);
        case "fees": { const r = fees(a.side, a.amount, a.code, a.date, { commissionRate: a.commission_rate ?? 0.00025, minCommission: a.min_commission ?? 5 });
            return [r.commission, r.stamp, r.transfer, r.total]; }
        case "price_cage": return priceCage(a.code, a.date, a.side, a.base, a.listing_n ?? null);
        case "sessions": return sessions(a.date, a.code);
        case "phase_at": return phaseAt(a.code, a.date, a.t);
        case "count_trade_days": return countTradeDays(a.d0, a.d1);
        default: throw new Error(c.fn);
    }
}
const same = (x, y) => JSON.stringify(x) === JSON.stringify(y);
if (import.meta.url === `file:///${process.argv[1]?.replace(/\\/g, "/").replace(/^\//, "")}` || process.argv[1]?.endsWith("a_rules.mjs")) {
    const cases = JSON.parse(fs.readFileSync(CASES, "utf8")).cases;
    if (process.argv.includes("--dump")) {
        process.stdout.write(JSON.stringify(cases.map(evalCase)));
    } else if (process.argv.includes("--selftest")) {
        let ok = true;
        for (const c of cases) {
            const got = evalCase(c), good = same(got, c.want);
            ok &&= good;
            console.log(`${good ? "PASS" : "FAIL"} ${c.id}${good ? "" : `  got=${JSON.stringify(got)} want=${JSON.stringify(c.want)}`}`);
        }
        console.log("A_RULES.MJS SELFTEST", ok ? "PASS" : "FAIL");
        process.exit(ok ? 0 : 1);
    }
}
