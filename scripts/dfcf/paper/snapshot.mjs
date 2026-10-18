// snapshot.mjs — 多源行情快照(2026-10-04, TODO §C.7-①; 10-05 升级源注册表 switch-case)
// 源注册表(用户立法: 数据源快速切换): 默认按序 fallback 防试错; --src <id> 强制单源不回落(排障/对比)。
//   实测可用=5 端点/3 独立供应商(腾讯×2域名、东财×2域名、新浪); 北交所链自动过滤不认 bj 的源。
// 实测淘汰记录(10/5): 网易163 chddata=502死, 网易实时feed=空, 雪球=匿名cookie 400016, 东财92镜像=空响应。
// 出错语义: 逐源尝试首个可用即返; 全灭=该票 {code, error}(显式失败不编数据); 残缺(last/prevClose缺)=换源。
// 导出: snapOne/snapMany/limitOf/isSealed —— matcher 撮合/驱动器验价/facts 共用同一真源
// CLI: node scripts/dfcf/paper/snapshot.mjs --codes 600127,002050 [--src tencent] [--asof yyyy-MM-dd] [--json <f>] [--md <f>]
const SRC_TIMEOUT = 8000;
// 10/15 统一请求层(scripts/lib/req_guard.mjs): 按域名记账/熔断/日预算; 盘中盯盘在用 → maxWaitMs=0(源被限速/熔断就立刻换下一源, 绝不排队等),
//   腾讯 qt 阈值宽(连败 8 次才停 3 分钟), 熔断只让本源让位, 其余 4 源照常
import { gfetch } from "../../lib/req_guard.mjs";
// 10/14: 所有等待自带 ±25% 抖动(固定间隔=机器指纹, 反爬最容易认); 调用处不用改
const sleep = (ms) => new Promise((r) => setTimeout(r, ms * (0.75 + Math.random() * 0.5)));

// ---- 板限分档: 10/16 晚改走统一规则模块 scripts/lib/a_rules.mjs(出处 docs/rules/a_share_trading_rules.md) ----
// 原写法只分 30/68→20%、8/4/920→30%、其余 10%: 转债被当 10%(应 20%, 上市首日 +57.3%)、新股前 5 日/北交所首日被当有涨跌停、
// 科创/创业类 ETF 被当 10%(应 20%)、回放 2026-07-06 前主板 ST 被当 10%(应 5%)。
// limitOf 仍返回"判定阈值"%(板限-0.3pt 余量防四舍五入漏判); 无涨跌幅限制 → Infinity(永不算触板/越界)。opt={date,name,isSt,listingN}
import * as AR from "../../lib/a_rules.mjs";
export function limitOf(code, opt = {}) {
    const p = AR.limitPct(code, opt.date, opt);
    return p === null ? Infinity : +(p * 100 - 0.3).toFixed(4);
}
export const limitPricesOf = (code, prevClose, opt = {}) => AR.limitPrices(code, opt.date, prevClose, opt);   // [涨停价, 跌停价], 按最小价位四舍五入
export function isSealed(s) {
    const lim = limitOf(s.code, { name: s.name || null });
    return Number.isFinite(lim) && s.open > 0 && s.open === s.high && s.high === s.low && s.low === s.last && Math.abs(s.pct) >= lim;
}

// ---- 源实现: 统一返回 {code,name,prevClose,last,open,high,low,pct,src} ----
// 10/15: 支持带前缀代码(sh000001/sz399006 等指数, 也可 sh600000), 进同一份共享缓存; 6 位代码行为不变(000001=平安银行)
const isPre = (c) => /^(sh|sz|bj)\d{6}$/.test(c);
const isBJ = (c) => (isPre(c) ? c.startsWith("bj") : /^(8|4|920)/.test(c));
const tencentMkt = (c) => (isPre(c) ? "" : /^(60|68|11[0138]|5)/.test(c) ? "sh" : "sz");   // 前缀代码自带市场, 拼接时前缀为空
const sinaMkt = (c) => (isPre(c) ? "" : /^(60|68|11[0138]|5)/.test(c) ? "sh" : isBJ(c) ? "bj" : "sz");
const emSecid = (c) => (isPre(c) ? `${c.startsWith("sh") ? 1 : 0}.${c.slice(2)}` : `${/^(60|68|11[0138]|5)/.test(c) ? 1 : 0}.${c}`);
// 10/12 加 vol(手)/amt(元)/qtTime: 盘中盯盘(live_watch.mjs)算均价与量能节奏用; 只新增字段, 撮合/验价不受影响
const qtParse = (code, f, src) => ({ code, name: f[1], last: +f[3], prevClose: +f[4], open: +f[5], high: +f[33], low: +f[34], pct: +f[32],
    vol: +f[6] || null, amt: f[37] ? +f[37] * 10000 : null, qtTime: f[30] || null,
    qtDate: /^\d{8}/.test(f[30] || "") ? `${f[30].slice(0, 4)}-${f[30].slice(4, 6)}-${f[30].slice(6, 8)}` : null, src });   // 10/17 H3: 行情所属交易日

async function fetchWithTimeout(url, headers) {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), SRC_TIMEOUT);
    try {
        const r = await gfetch(url, { headers, signal: ctl.signal }, { maxWaitMs: 0 });
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
    const secid = emSecid(code);
    const r = await fetchWithTimeout(
        `https://${host}/api/qt/stock/get?secid=${secid}&fields=f43,f44,f45,f46,f57,f58,f60,f86,f170&invt=2&fltt=2`,
        { Referer: "https://quote.eastmoney.com/" });
    const j = JSON.parse(await r.text());
    const d = j?.data;
    if (!d || !d.f43) throw new Error(`${label}返回为空`);
    return { code, name: d.f58, last: +d.f43, prevClose: +d.f60, open: +d.f46, high: +d.f44, low: +d.f45, pct: +d.f170,
        qtDate: +d.f86 > 0 ? new Date(+d.f86 * 1000).toLocaleDateString("sv-SE") : null, src: label };   // 10/17 H3: f86=行情时间戳(秒, 10/17 实测)
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
    return { code, name: f[0], open: +f[1], prevClose: +f[2], last: +f[3], high: +f[4], low: +f[5], pct: f[2] ? +((f[3] / f[2] - 1) * 100).toFixed(2) : 0,
        qtDate: /^\d{4}-\d{2}-\d{2}$/.test(f[30] || "") ? f[30] : null, src: "sina" };   // 10/17 H3: f[30]=行情日期
}

// 10/18 第 4 家独立供应商: 财联社 x-quote 个股详情(免签名; 10/14 REA 抓包发现, 10/18 实测 sz002714/sh600519 可用; 请求层源 cls_xquote 记账/熔断)
//   字段: last_px/open_px/high_px/low_px/preclose_px/up_price/down_price/av_px; label.suspend=1 停牌; 没有行情日期字段 → qtDate=null(不标 stale, 调用方按时段自行判断)
async function fromCls(code) {
    const sym = isPre(code) ? code : `${sinaMkt(code)}${code}`;
    const r = await fetchWithTimeout(`https://x-quote.cls.cn/v2/quote/a/web/stock/detail?secu_code=${sym}`,
        { Referer: "https://www.cls.cn/", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0" });
    const j = JSON.parse(await r.text());
    const q = j?.data?.quote;
    if (j?.code !== 200 || !q) throw new Error(`财联社 code=${j?.code}`);
    const n = (x) => (x === undefined || x === null || x === "" ? NaN : +String(x).replace(/[^\d.-]/g, ""));
    const last = n(q.last_px), pc = n(q.preclose_px);
    if (!(last > 0) || !(pc > 0)) throw new Error("财联社空数据");
    return { code, name: q.secu_name, open: n(q.open_px) || 0, prevClose: pc, last, high: n(q.high_px) || last, low: n(q.low_px) || last,
        pct: +((last / pc - 1) * 100).toFixed(2), suspended: j?.data?.label?.suspend === 1, qtDate: null, src: "cls" };
}

// ---- 源注册表(顺序=fallback 顺序; sup=该源支持的代码域) ----
export const SNAPSHOT_SRCS = [
    { id: "tencent", label: "腾讯qt实时", sup: (c) => !isBJ(c), fn: fromTencent },
    { id: "east", label: "东财实时", sup: () => true, fn: eastGet("push2.eastmoney.com", "east") },
    { id: "tx_minute", label: "腾讯分时qt", sup: (c) => !isBJ(c), fn: fromTxMinute },
    { id: "sina", label: "新浪实时", sup: () => true, fn: fromSina },
    { id: "cls", label: "财联社x-quote", sup: (c) => !isBJ(c), fn: fromCls },   // 10/18 第 4 家独立供应商(东财延迟之前)
    { id: "east_delay", label: "东财延迟15m", sup: () => true, fn: eastGet("push2delay.eastmoney.com", "east_delay") },
];

// 源返回残缺(如东财对已切换票 last=null)=视为失败换下一源, 不让半截数据冒充价格锚
const usable = (s) => s && s.name && s.last > 0 && s.prevClose > 0;
// 10/17 健壮性 H3(实证 10/09 星见野 600241 被误拒): 行情所属交易日 qtDate 早于今天=盘前/休市, 源还停在上一交易日的盘
//   (last=上一交易日收盘, prevClose=再前一日收盘)。这里只加 stale/qtDate 字段、不改原值(baselines 把快照当该交易日 bar 用, 要原口径);
//   要"今天的前收"一律走 todayPrevClose(s): stale → last; 无日期(老缓存条目) → prevClose, 调用方自己决定信不信(matcher 盘前不信, 走日线+日期校验)
const todayLocal = () => new Date().toLocaleDateString("sv-SE");
const markStale = (s) => (s && !s.error && s.qtDate ? { ...s, stale: s.qtDate < todayLocal() } : s);
export const todayPrevClose = (s) => (!s || s.error ? null : s.stale ? s.last : s.prevClose);

// 直连单票(无缓存; 多源 fallback): 缓存层补缺/强制单源排障时用
async function snapOneLive(code, opt = {}) {
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
            if (usable(s)) return markStale(s);
            errs.push(`${id}:残缺数据`);
        } catch (e) { errs.push(`${id}:${e.message}`); }
        if (!opt.src) await sleep(300);
    }
    return { code, error: errs.join(" | ") };
}

// ---- 行情共享缓存(10/11 用户提: "所有查实时行情共用同一份文件") ----
// 读穿缓存: 新鲜(盘中 20s / 盘外 10min)直接用; 缺的合并成一次腾讯批量请求(实测 50 只≈75ms, 逐只 10 只≈670ms),
//   批量缺失/北交所再逐只多源兜底; 写回 downloads/quotes/live/snap_cache.json(临时文件+原子改名, 多进程安全)。
// 效果: 15 条链+每分钟撮合+报告同时查价, 对外只发一次请求(东财/腾讯不再因并发被限流); 每条结果带 age_s=距抓取秒数。
// 偏差: 盘中最多落后 20s(撮合本就 1 分钟一轮)。opt.src(强制单源)/opt.noCache 绕过缓存。
const CACHE = new URL("../../../downloads/quotes/live/snap_cache.json", import.meta.url);
const ttlMs = () => {
    const d = new Date(), hm = d.getHours() * 100 + d.getMinutes(), wd = d.getDay();
    return wd >= 1 && wd <= 5 && hm >= 915 && hm <= 1505 ? 20_000 : 600_000;
};
async function readCache() {
    const fs = await import("node:fs");
    try { return JSON.parse(fs.readFileSync(CACHE, "utf8")); } catch { return {}; }
}
async function writeCache(upd) {
    const fs = await import("node:fs");
    const { fileURLToPath } = await import("node:url");
    const f = fileURLToPath(CACHE);
    fs.mkdirSync(f.replace(/[\\/][^\\/]+$/, ""), { recursive: true });
    const cur = await readCache();   // 读-合并-写: 保留他进程刚写入的更新鲜条目
    for (const [c, s] of Object.entries(upd)) if (!cur[c] || (cur[c].ts || 0) < s.ts) cur[c] = s;
    const tmp = `${f}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(cur));
    try { fs.renameSync(tmp, f); } catch { try { fs.unlinkSync(tmp); } catch { } }
}
async function tencentBatch(codes) {   // 腾讯 qt 一次查多只: q=sh600000,sz000001,...
    const out = {};
    for (let i = 0; i < codes.length; i += 50) {
        const part = codes.slice(i, i + 50);
        try {
            const r = await fetchWithTimeout(`https://qt.gtimg.cn/q=${part.map((c) => tencentMkt(c) + c).join(",")}`, { Referer: "https://gu.qq.com/" });
            const txt = new TextDecoder("gbk").decode(await r.arrayBuffer());
            const want = new Map(part.map((c) => [tencentMkt(c) + c, c]));   // 返回的 v_<sym> → 调用方给的代码(6 位或带前缀)
            for (const m of txt.matchAll(/v_((?:sh|sz)\d{6})="([^"]*)"/g)) {
                const c = want.get(m[1]);
                if (!c) continue;
                const s = qtParse(c, m[2].split("~"), "tencent_batch");
                if (usable(s)) out[c] = s;
            }
        } catch { /* 整批失败=全部走逐只兜底 */ }
    }
    return out;
}

export async function snapMany(codes, gapMs = 400, opt = {}) {
    const uniq = [...new Set(codes)], out = {};
    if (opt.src || opt.noCache) {
        for (const c of uniq) { out[c] = await snapOneLive(c, opt); await sleep(gapMs); }
        return out;
    }
    const now = Date.now(), ttl = ttlMs(), cache = await readCache(), upd = {};
    const miss = uniq.filter((c) => !(cache[c] && now - cache[c].ts < ttl));
    const got = await tencentBatch(miss.filter((c) => !isBJ(c)));
    for (const c of miss) {
        let s = got[c];
        if (!s) { s = await snapOneLive(c, opt); await sleep(gapMs); }   // 批量缺/北交所 → 逐只多源
        if (!s.error) upd[c] = { ...s, ts: Date.now() };
        else out[c] = s;
    }
    if (Object.keys(upd).length) await writeCache(upd);
    for (const c of uniq) {
        if (out[c]) continue;
        const s = upd[c] || cache[c];
        out[c] = markStale({ ...s, age_s: Math.round((Date.now() - s.ts) / 1000) });
    }
    return out;
}

export async function snapOne(code, opt = {}) {
    if (opt.src || opt.noCache) return snapOneLive(code, opt);
    return (await snapMany([code], 0, opt))[code];
}

// ---- as-of 回放快照(10/10: 9/28-30 补跑语义修复) ----
// 链日 D 盘前视角=D 的前一交易日日线, 读 downloads/quotes/daily 归档(前复权; 缺档/未覆盖 D-1 则 kline.mjs 补档)
// 日历=上证指数归档 1_000001 的交易日序列。两种口径:
//   默认(facts 关注票): D-1 日线本身 → last=D-1 收, prevClose=D-2 收, pct/高低=D-1 当日(盘前看昨日K线)
//   premarket(cand_snap/拒落账): D 盘前 → last=prevClose=D-1 收, 高低开=0(D 未开盘), sealedPrev=D-1 是否一字
const KDIR = new URL("../../../downloads/quotes/daily/", import.meta.url);
async function readKl(code) {
    const fs = await import("node:fs");
    try { return JSON.parse(fs.readFileSync(new URL(code.replace(".", "_") + ".json", KDIR), "utf8")).klines || []; }
    catch { return []; }
}
export async function prevTradeDay(D) {
    const d = (await readKl("1.000001")).map((k) => k.d).filter((x) => x < D).pop();
    if (!d) throw new Error(`交易日历(1_000001 归档)无 ${D} 之前的交易日`);
    return d;
}
export async function snapAsof(code, D, { premarket = false } = {}) {
    const d1 = await prevTradeDay(D);
    let kl = (await readKl(code)).filter((k) => k.d < D);
    if (kl.at(-1)?.d !== d1) {  // 归档缺或未覆盖 D-1 → 增量补档(真实历史数据, 幂等合并)
        const { fileURLToPath } = await import("node:url");
        const { archiveDaily } = await import("../../quotes/kline.mjs");
        await archiveDaily([code], { dir: fileURLToPath(KDIR), gapMs: 300 });
        kl = (await readKl(code)).filter((k) => k.d < D);
    }
    const b = kl.at(-1), p = kl.at(-2);
    if (b?.d !== d1 || !(b.c > 0) || !(p?.c > 0)) return { code, error: `asof 日线缺 ${d1}(停牌/未上市/取数失败)` };
    const day = { code, name: "", prevClose: p.c, last: b.c, open: b.o, high: b.h, low: b.l, pct: +((b.c / p.c - 1) * 100).toFixed(2), src: `asof-daily(${d1})` };
    if (!premarket) return day;
    return { code, name: "", prevClose: b.c, last: b.c, open: 0, high: 0, low: 0, pct: 0, sealedPrev: isSealed(day), src: `asof-premarket(${D}, 前收=${d1}收)` };
}

// ---- CLI ----
const argv = process.argv.slice(2);
const arg = (k) => { const i = argv.indexOf("--" + k); return i > -1 ? argv[i + 1] : null; };
if (argv.includes("--codes")) {
    const codes = arg("codes").split(",").map((s) => s.trim()).filter(Boolean);
    // --asof D: 链日 D 盘前口径(日线归档), 不碰实时源(9/28-30 补跑语义修复)
    const res = {};
    if (arg("asof")) for (const c of [...new Set(codes)]) res[c] = await snapAsof(c, arg("asof"), { premarket: true });
    else {
        Object.assign(res, await snapMany(codes, 400, { src: arg("src") }));
        // 10/17 H3: CLI 实时口径只给驱动器 cand_snap 用(=今天要挂的单的价格锚) → 盘前停在上一交易日的行情, 前收改成该日收盘(原值留 sessionPrevClose)
        for (const [c, s] of Object.entries(res)) if (s && !s.error && s.stale)
            res[c] = { ...s, sessionPrevClose: s.prevClose, prevClose: s.last, src: `${s.src}·盘前(行情停在${s.qtDate}收盘, 前收=该日收, 涨跌幅/高低=该日)` };
    }
    const ok = Object.values(res).filter((s) => !s.error);
    const fail = Object.values(res).filter((s) => s.error);
    const json = JSON.stringify({ at: new Date().toISOString(), src: arg("asof") ? `asof ${arg("asof")}` : arg("src") || "auto(fallback)", snaps: Object.values(res) }, null, 1);
    if (arg("json")) {
        const fs = await import("node:fs");
        fs.writeFileSync(arg("json"), json);
    }
    if (arg("md")) {
        const fs = await import("node:fs");
        const rows = Object.values(res).map((s) => s.error
            ? `- ${s.code}: ⚠快照失败(${s.error})`
            : `- ${s.code} ${s.name}: 前收${s.prevClose} 现${s.last} (${s.pct > 0 ? "+" : ""}${s.pct}%) 高${s.high} 低${s.low}${isSealed(s) || s.sealedPrev ? " 🔒一字封死·禁入候选" : ""} [${s.src}]`);
        fs.writeFileSync(arg("md"), `# cand_snap 候选票价格锚（机械拉取, 驱动器 04 后生成; LLM 挂单价必须锚定此表前收/现价）\n\n${rows.join("\n")}\n`);
    }
    console.log(json);
    console.log(`JSON:${JSON.stringify({ ok: ok.length, fail: fail.length })}`);
    process.exit(fail.length && !ok.length ? 2 : 0); // 全灭才 exit 2(部分失败不挡链, 消费方按 error 字段降级)
}