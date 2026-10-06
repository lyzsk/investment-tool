// fetch_quotes.mjs — 分时/日线行情归档·统一入口(2026-10-06 合并版, 用户命名 fetch_quotes --market cb|stock)
// 合并自: fetch_cb_quotes.mjs(转债) + fetch_stock_trends.mjs(股票分时)——分时归档核心(trends2+5天窗口+幂等)真重复。
// 两 market 的 secid 规则/产物路径/附属能力不同, 函数分流保内聚:
//   --market cb   : kline 双源回填+分时归档+实时快照(转债全套, 原 160 行逻辑函数化)
//   --market stock: 分时归档+--from-md 批量(原 91 行逻辑函数化)
// 共享层: fetchJson 重试 / jitter / 归档幂等原则(已存不覆盖——分钟数据不可再生)
// 产物: downloads/quotes/{cb,stock}/... (路径与合并前完全一致, 消费方零改动)
// 纪律: 公开行情无凭证; 请求抖动 0.75-1.25x; 3 次退避重试
import fs from "node:fs";
import path from "node:path";

const arg = (k) => { const i = process.argv.indexOf("--" + k); return i > -1 ? process.argv[i + 1] : null; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = () => sleep(800 * (0.75 + Math.random() * 0.5));
const MARKET = arg("market") || "cb";

// ============ 共享层 ============
async function fetchJson(url, tries = 3) {
    for (let i = 0; ; i++) {
        try {
            const r = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0", Referer: "https://quote.eastmoney.com/" } });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const j = await r.json();
            if (j?.data === null) throw new Error("data=null(代码或市场错?)");
            return j;
        } catch (e) {
            if (i >= tries - 1) throw e;
            await sleep(2000 * (i + 1));
        }
    }
}
// ---- 分时归档(共享核心: trends2 ndays → 按日切分, 已存跳过) ----
async function archiveTrends(code, secidOf, outDir, ndays = 5) {
    const url = `https://push2his.eastmoney.com/api/qt/stock/trends2/get?secid=${secidOf(code)}` +
        `&fields1=f1,f2,f3,f4,f5,f6,f7,f8&fields2=f51,f52,f53,f54,f55,f56&ndays=${ndays}&iscr=0`;
    const j = await fetchJson(url);
    const byDay = {};
    for (const line of j?.data?.trends || []) {
        const [dt, price, vol] = line.split(",");
        (byDay[dt.slice(0, 10)] ||= []).push({ t: dt.slice(11), p: +price, vol: +vol });
    }
    fs.mkdirSync(outDir, { recursive: true });
    let saved = 0, skipped = 0;
    for (const [day, arr] of Object.entries(byDay)) {
        const file = path.join(outDir, `${code}_${day}.json`);
        if (fs.existsSync(file)) { skipped++; continue; }
        fs.writeFileSync(file, JSON.stringify({ code, day, bars: arr }));
        saved++;
    }
    return { saved, skipped, days: Object.keys(byDay) };
}

// ============ 转债分支(原 fetch_cb_quotes.mjs) ============
const CB_ROOT = path.resolve("downloads/quotes/cb");
const CB_SECID = (code) => (/^(11[0138])/.test(code) ? "1." : "0.") + code;

async function cbKline(code) {
    let lines = [];
    try {
        const j = await fetchJson(`https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=${CB_SECID(code)}` +
            `&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=1&beg=20250101&end=20500101`);
        lines = (j?.data?.klines || []).map((x) => x.slice(0, 33));
    } catch { /* 东财限频/挂→腾讯兜底 */ }
    if (lines.length === 0) {  // 兜底: 腾讯(退市债数据保留更久, 10/2 实测)
        const prefix = /^(11[0138])/.test(code) ? "sh" : "sz";
        const r = await fetch(`https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=${prefix}${code},day,2025-01-01,2026-12-31,640,qfq`, { headers: { Referer: "https://gu.qq.com/" } });
        if (r.ok) {
            const tj = await r.json();
            const rows = tj?.data?.[`${prefix}${code}`]?.day || tj?.data?.[`${prefix}${code}`]?.qfqday || [];
            lines = rows.map((x) => x.slice(0, 7).join(","));
        }
    }
    const file = path.join(CB_ROOT, "kline", `${code}.json`);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const old = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : {};
    for (const line of lines) {
        const [date, o, c, h, l, vol, amt] = line.split(",");
        old[date] = { o: +o, h: +h, l: +l, c: +c, vol: +vol, amt: +(amt || 0) };
    }
    fs.writeFileSync(file, JSON.stringify(old));
    return Object.keys(old).length;
}
async function cbSnap(code) {
    const prefix = /^(11[0138])/.test(code) ? "sh" : "sz";
    const r = await fetch(`https://qt.gtimg.cn/q=${prefix}${code}`, { headers: { Referer: "https://gu.qq.com/" } });
    const m = new TextDecoder("gbk").decode(await r.arrayBuffer()).match(/="([\s\S]*)"/);
    if (!m) throw new Error("腾讯返回为空");
    const f = m[1].split("~");
    return { code, name: f[1], last: +f[3], prevClose: +f[4], open: +f[5], pct: +f[32] };
}
async function cbTzzbCodes() {  // 当日有腿标的(从土豆账本流水扫)
    const TZZB = path.resolve("downloads/tzzb/buchitudou0");
    const codes = new Set();
    const state = path.join(TZZB, "state.json");
    if (fs.existsSync(state)) {
        const s = JSON.parse(fs.readFileSync(state, "utf8"));
        // 从最近流水页扫当日腿
        for (const f of fs.readdirSync(TZZB).filter((x) => x.startsWith("position_change_p"))) {
            const j = JSON.parse(fs.readFileSync(path.join(TZZB, f), "utf8"));
            for (const t of j?.ex_data?.change_list || []) {
                if (t.trans_date.slice(0, 10) === new Date().toISOString().slice(0, 10)) codes.add(t.stock_code);
            }
        }
    }
    return [...codes];
}

// ============ 股票分支(原 fetch_stock_trends.mjs) ============
const STOCK_ROOT = path.resolve("downloads/quotes/stock/trends");
const STOCK_SECID = (code) => (/^(60|68|11|5)/.test(code) ? "1." : "0.") + code;

async function stockTrendsForCode(code, date, force) {
    const j = await fetchJson(`https://push2his.eastmoney.com/api/qt/stock/trends2/get?secid=${STOCK_SECID(code)}` +
        `&fields1=f1,f2,f3,f4,f5,f6,f7,f8&fields2=f51,f52,f53,f54,f55,f56&ndays=5&iscr=0`);
    const all = j?.data?.trends || [];
    const days = [...new Set(all.map((t) => t.slice(0, 10)))].sort();
    const target = date || days[days.length - 1];
    const rows = all.filter((t) => t.startsWith(target));
    if (!rows.length) throw new Error(`目标日 ${target} 无分时(可得=${days.join("/")})`);
    const file = path.join(STOCK_ROOT, `${code}_${target}.json`);
    if (!force && fs.existsSync(file)) return { code, target, skipped: true };
    fs.mkdirSync(STOCK_ROOT, { recursive: true });
    fs.writeFileSync(file, JSON.stringify({ code, name: j.data.name, date: target, count: rows.length, trends: rows }));
    return { code, target, count: rows.length, skipped: false };
}
function codesFromMd(date) {
    const [y, m] = date.split("-");
    const f = path.join("md", `${y}S${Math.ceil(+m / 3)}`, `${date}.md`);
    if (!fs.existsSync(f)) { console.error(`无md: ${f}`); process.exit(4); }
    const codes = [...fs.readFileSync(f, "utf8").matchAll(/（(\d{6})）/g)].map((x) => x[1]);
    return [...new Set(codes)];
}

// ============ main ============
(async () => {
    if (MARKET === "cb") {
        // 用法: --kline-all | --kline --code | --trends --code | --trends-all | --snap --code
        const mode = arg("kline-all") !== null || process.argv.includes("--kline-all") ? "kline-all"
            : process.argv.includes("--kline") ? "kline" : process.argv.includes("--trends-all") ? "trends-all"
            : process.argv.includes("--trends") ? "trends" : process.argv.includes("--snap") ? "snap" : null;
        if (!mode) { console.error("cb 用法: --kline-all | --kline --code | --trends --code | --trends-all | --snap --code"); process.exit(1); }
        if (mode === "kline-all" || mode === "trends-all") {
            const codes = await cbTzzbCodes();
            let ok = 0, fail = 0;
            for (const c of codes) {
                try { mode === "kline-all" ? await cbKline(c) : await archiveTrends(c, CB_SECID, path.join(CB_ROOT, "trends")); ok++; }
                catch (e) { console.error(`失败 ${c}: ${e.message}`); fail++; }
                await jitter();
            }
            console.log(`JSON:${JSON.stringify({ ok, fail })}`);
        } else {
            const code = arg("code");
            if (!code) { console.error("需 --code"); process.exit(1); }
            if (mode === "kline") console.log(await cbKline(code));
            if (mode === "trends") console.log(await archiveTrends(code, CB_SECID, path.join(CB_ROOT, "trends")));
            if (mode === "snap") console.log(await cbSnap(code));
        }
    } else if (MARKET === "stock") {
        // 用法: --codes 600127,002264 [--date d] [--force] | --from-md <date> [--force]
        const CODES = arg("codes") ? arg("codes").split(",").map((s) => s.trim()).filter(Boolean) : null;
        const FROM_MD = arg("from-md");
        const FORCE = process.argv.includes("--force");
        if (!CODES && !FROM_MD) { console.error("stock 用法: --codes 600127,002264 [--date d] | --from-md <date> [--force]"); process.exit(1); }
        const codes = CODES || codesFromMd(FROM_MD);
        const date = arg("date") || FROM_MD || null;
        let ok = 0, fail = 0;
        for (const code of codes) {
            try { const r = await stockTrendsForCode(code, date, FORCE); console.log(r.skipped ? `幂等跳过 ${code} ${r.target}` : `归档 ${code} ${r.count} 根1min`); ok++; }
            catch (e) { console.error(`失败 ${code}: ${e.message}`); fail++; }
            await jitter();
        }
        console.log(`JSON:${JSON.stringify({ ok, fail, codes: codes.length })}`);
        if (fail) process.exit(1);
    } else {
        console.error(`未知 --market ${MARKET}(可选: cb|stock)`);
        process.exit(1);
    }
})();
