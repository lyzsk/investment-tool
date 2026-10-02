// fetch_stock_trends.mjs — A股个股分时(1min)归档(桃哥核销证据层, 2026-10-02)
// 用途: 桃哥=分时盘口选手, 其日内断言("早盘冲高2点没走"/"尾盘硬拉"/"海底捞月")需分钟级数据核销;
//       东财分时只留 ~5 个交易日, 必须当天归档才攒得出历史(同 cb_quotes 铁律)
// 用法:
//   node scripts/quotes/fetch_stock_trends.mjs --codes 600127,002264 [--date yyyy-MM-dd] [--force]
//   node scripts/quotes/fetch_stock_trends.mjs --from-md <yyyy-MM-dd> [--force]
//     --from-md: 从 md/<y>S<q>/<date>.md 全文抠 （6位代码） 去重归档(桃哥小节+持仓节一并覆盖)
//     --date 不传=最近交易日; 归档=最近5个交易日内匹配目标日(东财只留5天, 过期显式报错不编数据)
// 产物: downloads/quotes/stock/trends/<code>_<yyyy-MM-dd>.json(raw trends2 json)
// 纪律: 公开行情无凭证; 抖动 0.75-1.25x; 3次退避; data=null 先翻转市场位再报错; 与 cb 脚本互不调用(高内聚)
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve("downloads/quotes/stock/trends");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = () => sleep(800 * (0.75 + Math.random() * 0.5));
const arg = (k) => { const i = process.argv.indexOf("--" + k); return i > -1 ? process.argv[i + 1] : null; };
const CODES = arg("codes") ? arg("codes").split(",").map((s) => s.trim()).filter(Boolean) : null;
const FROM_MD = arg("from-md");
const FORCE = process.argv.includes("--force");
if (!CODES && !FROM_MD) {
    console.error("用法: --codes 600127,002264 | --from-md <yyyy-MM-dd> [--date d] [--force]");
    process.exit(1);
}

// 沪 60/68/11/5 → 1; 深 00/30/12 → 0; 北交所 4/8/920 → 先 0 后翻转试错
const secid = (code) => (/^(60|68|11|5)/.test(code) ? "1." : "0.") + code;

async function fetchJson(url, tries = 3) {
    for (let i = 0; ; i++) {
        try {
            const r = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0", Referer: "https://quote.eastmoney.com/" } });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const j = await r.json();
            return j;
        } catch (e) {
            if (i >= tries - 1) throw e;
            await sleep(2000 * (i + 1));
        }
    }
}

// 拉最近5日分时, 按目标日过滤; 目标日无数据=非交易日或已超5天窗口
async function trends(code, date) {
    const fields1 = "f1,f2,f3,f4,f5,f6,f7,f8";
    const fields2 = "f51,f52,f53,f54,f55,f56,f57,f58";
    const url = (sid) => `https://push2his.eastmoney.com/api/qt/stock/trends2/get?secid=${sid}` +
        `&fields1=${fields1}&fields2=${fields2}&iscr=0&ndays=5`;
    let j = await fetchJson(url(secid(code)));
    if (j?.data == null) { // 市场位翻转兜底(北交所等)
        j = await fetchJson(url((secid(code).startsWith("1.") ? "0." : "1.") + code));
        if (j?.data == null) throw new Error("双市场位均无数据(代码错?)");
    }
    const all = j.data.trends || [];
    const days = [...new Set(all.map((t) => t.slice(0, 10)))].sort();
    const target = date || days[days.length - 1];
    const rows = all.filter((t) => t.startsWith(target));
    if (!rows.length) throw new Error(`目标日 ${target} 无分时(可得=${days.join("/")}, 超5天窗口或非交易日)`);
    return { target, rows, meta: { code, name: j.data.name, daysAvailable: days } };
}

function codesFromMd(date) {
    const [y, m] = date.split("-");
    const f = path.join("md", `${y}S${Math.ceil(+m / 3)}`, `${date}.md`);
    if (!fs.existsSync(f)) { console.error(`无md: ${f}`); process.exit(4); }
    const text = fs.readFileSync(f, "utf8");
    const codes = [...new Set([...text.matchAll(/（(\d{6})）/g)].map((x) => x[1]))];
    if (!codes.length) { console.error("md 中未抠到（6位代码）"); process.exit(3); }
    return codes;
}

(async () => {
    fs.mkdirSync(ROOT, { recursive: true });
    const codes = CODES || codesFromMd(FROM_MD);
    const date = arg("date") || FROM_MD || null;
    let ok = 0, fail = 0;
    for (const code of codes) {
        const out = path.join(ROOT, `${code}_${date || "latest"}.json`);
        try {
            const { target, rows, meta } = await trends(code, date);
            const file = path.join(ROOT, `${code}_${target}.json`);
            if (!FORCE && fs.existsSync(file)) { console.log(`幂等跳过 ${code} ${target}`); ok++; continue; }
            fs.writeFileSync(file, JSON.stringify({ ...meta, date: target, count: rows.length, trends: rows }, null, 1));
            console.log(`归档 ${code} ${meta.name || ""} ${target}: ${rows.length} 根1min`);
            ok++;
        } catch (e) { console.error(`失败 ${code}: ${e.message}`); fail++; }
        await jitter();
    }
    console.log(`JSON:${JSON.stringify({ ok, fail, codes: codes.length })}`);
    if (fail) process.exit(1);
})();
