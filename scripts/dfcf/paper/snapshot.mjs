// snapshot.mjs — 多源行情快照(2026-10-04, TODO §C.7-①; 10-05 升级源注册表 switch-case)
// 源注册表(用户立法: 数据源快速切换): 默认按序 fallback 防试错; --src <id> 强制单源不回落(排障/对比)。
//   实测可用=5 端点/3 独立供应商(腾讯×2域名、东财×2域名、新浪); 北交所链自动过滤不认 bj 的源。
// 实测淘汰记录(10/5): 网易163 chddata=502死, 网易实时feed=空, 雪球=匿名cookie 400016, 东财92镜像=空响应。
// 出错语义: 逐源尝试首个可用即返; 全灭=该票 {code, error}(显式失败不编数据); 残缺(last/prevClose缺)=换源。
// 导出: snapOne/snapMany/limitOf/isSealed —— matcher 撮合/驱动器验价/facts 共用同一真源
// CLI: node scripts/dfcf/paper/snapshot.mjs --codes 600127,002050 [--src tencent] [--json <f>] [--md <f>]
const SRC_TIMEOUT = 8000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- 板限分档(2026-07-06 起主板 ST 同为 10%, 无需 ST 特判; 阈值留 0.3pt 余量防四舍五入漏判) ----
export function limitOf(code) {
    if (/^(30|68)/.test(code)) return 19.7;   // 创业板/科创板 20%
    if (/^(8|4|920)/.test(code)) return 29.7; // 北交所 30%
    return 9.7;                                // 主板(含 ST) 10%
}
export function isSealed(s) {
    return s.open > 0 && s.open === s.high && s.high === s.low && s.low === s.last && Math.abs(s.pct) >= limitOf(s.code);
}

// ---- 源实现: 统一返回 {code,name,prevClose,last,open,high,low,pct,src} ----
const isBJ = (c) => /^(8|4|920)/.test(c);
const tencentMkt = (c) => (/^(60|68|11[0138]|5)/.test(c) ? "sh" : "sz");
const sinaMkt = (c) => (/^(60|68|11[0138]|5)/.test(c) ? "sh" : isBJ(c) ? "bj" : "sz");
const qtParse = (code, f, src) => ({ code, name: f[1], last: +f[3], prevClose: +f[4], open: +f[5], high: +f[33], low: +f[34], pct: +f[32], src });

async function fetchWithTimeout(url, headers) {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), SRC_TIMEOUT);
    try {
        const r = await fetch(url, { headers, signal: ctl.signal });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r;
    } finally { clearTimeout(t); }
}

async function fromTencent(code) {
    const r = await fetchWithTimeout(`https://qt.gtimg.cn/q=${tencentMkt(code)}${code}`, { Referer: "https://gu.qq.com/" });
    const m = new TextDecoder("gbk").decode(await r.arrayBuffer()).match(/="([\s\S]*)"/);
    if (!m) throw new Error("腾讯返回为空");
    return qtParse(code, m[1].split("~"), "tencent");
}
const eastGet = (host, label) => async (code) => {  // 东财系两域名共用 API(push2 实时 / push2delay 延迟15分)
    const secid = `${/^(60|68|11[0138]|5)/.test(code) ? 1 : 0}.${code}`;
    const r = await fetchWithTimeout(
        `https://${host}/api/qt/stock/get?secid=${secid}&fields=f43,f44,f45,f46,f57,f58,f60,f170&invt=2&fltt=2`,
        { Referer: "https://quote.eastmoney.com/" });
    const j = JSON.parse(await r.text());
    const d = j?.data;
    if (!d || !d.f43) throw new Error(`${label}返回为空`);
    return { code, name: d.f58, last: +d.f43, prevClose: +d.f60, open: +d.f46, high: +d.f44, low: +d.f45, pct: +d.f170, src: label };
};
async function fromTxMinute(code) {  // 腾讯分时接口的 qt 块(独立域名 web.ifzq: qt.gtimg 挂时它可能还活着)
    const r = await fetchWithTimeout(`https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=${tencentMkt(code)}${code}`,
        { Referer: "https://gu.qq.com/" });
    const j = JSON.parse(await r.text());
    const f = j?.data?.[`${tencentMkt(code)}${code}`]?.qt?.[`${tencentMkt(code)}${code}`]; // qt 对象键=sym 非 0/1 下标
    if (!f?.[3]) throw new Error("tx_minute qt 块缺失");
    return qtParse(code, f, "tx_minute");
}
async function fromSina(code) {
    const r = await fetchWithTimeout(`https://hq.sinajs.cn/list=${sinaMkt(code)}${code}`,
        { Referer: "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0" });
    const m = new TextDecoder("gbk").decode(await r.arrayBuffer()).match(/="([\s\S]*)"/);
    if (!m) throw new Error("新浪返回为空");
    const f = m[1].split(",");
    if (!(+f[3] > 0) || !(+f[2] > 0)) throw new Error("新浪空数据"); // f[0]=票名非数字; 判 last/prevClose
    return { code, name: f[0], open: +f[1], prevClose: +f[2], last: +f[3], high: +f[4], low: +f[5], pct: f[2] ? +((f[3] / f[2] - 1) * 100).toFixed(2) : 0, src: "sina" };
}

// ---- 源注册表(顺序=fallback 顺序; sup=该源支持的代码域) ----
export const SNAPSHOT_SRCS = [
    { id: "tencent", label: "腾讯qt实时", sup: (c) => !isBJ(c), fn: fromTencent },
    { id: "east", label: "东财实时", sup: () => true, fn: eastGet("push2.eastmoney.com", "east") },
    { id: "tx_minute", label: "腾讯分时qt", sup: (c) => !isBJ(c), fn: fromTxMinute },
    { id: "sina", label: "新浪实时", sup: () => true, fn: fromSina },
    { id: "east_delay", label: "东财延迟15m", sup: () => true, fn: eastGet("push2delay.eastmoney.com", "east_delay") },
];

// 源返回残缺(如东财对已切换票 last=null)=视为失败换下一源, 不让半截数据冒充价格锚
const usable = (s) => s && s.name && s.last > 0 && s.prevClose > 0;

export async function snapOne(code, opt = {}) {
    let chain;
    if (opt.src) {  // 强制单源: 不回落, 败=败(排障要的就是这个语义)
        const s = SNAPSHOT_SRCS.find((x) => x.id === opt.src);
        if (!s) return { code, error: `未知源 ${opt.src}(可用: ${SNAPSHOT_SRCS.map((x) => x.id).join("/")})` };
        if (!s.sup(code)) return { code, error: `源 ${s.id} 不支持 ${code}` };
        chain = [s];
    } else {
        chain = SNAPSHOT_SRCS.filter((s) => s.sup(code));
    }
    const errs = [];
    for (const { id, fn } of chain) {
        try {
            const s = await fn(code);
            if (usable(s)) return s;
            errs.push(`${id}:残缺数据`);
        } catch (e) { errs.push(`${id}:${e.message}`); }
        if (!opt.src) await sleep(300);
    }
    return { code, error: errs.join(" | ") };
}

export async function snapMany(codes, gapMs = 400, opt = {}) {
    const out = {};
    for (const c of [...new Set(codes)]) {
        out[c] = await snapOne(c, opt);
        await sleep(gapMs);
    }
    return out;
}

// ---- CLI ----
const argv = process.argv.slice(2);
const arg = (k) => { const i = argv.indexOf("--" + k); return i > -1 ? argv[i + 1] : null; };
if (argv.includes("--codes")) {
    const codes = arg("codes").split(",").map((s) => s.trim()).filter(Boolean);
    const res = await snapMany(codes, 400, { src: arg("src") });
    const ok = Object.values(res).filter((s) => !s.error);
    const fail = Object.values(res).filter((s) => s.error);
    const json = JSON.stringify({ at: new Date().toISOString(), src: arg("src") || "auto(fallback)", snaps: Object.values(res) }, null, 1);
    if (arg("json")) {
        const fs = await import("node:fs");
        fs.writeFileSync(arg("json"), json);
    }
    if (arg("md")) {
        const fs = await import("node:fs");
        const rows = Object.values(res).map((s) => s.error
            ? `- ${s.code}: ⚠快照失败(${s.error})`
            : `- ${s.code} ${s.name}: 前收${s.prevClose} 现${s.last} (${s.pct > 0 ? "+" : ""}${s.pct}%) 高${s.high} 低${s.low}${isSealed(s) ? " 🔒一字封死·禁入候选" : ""} [${s.src}]`);
        fs.writeFileSync(arg("md"), `# cand_snap 候选票价格锚（机械拉取, 驱动器 04 后生成; LLM 挂单价必须锚定此表前收/现价）\n\n${rows.join("\n")}\n`);
    }
    console.log(json);
    console.log(`JSON:${JSON.stringify({ ok: ok.length, fail: fail.length })}`);
    process.exit(fail.length && !ok.length ? 2 : 0); // 全灭才 exit 2(部分失败不挡链, 消费方按 error 字段降级)
}