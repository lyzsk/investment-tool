// collect_daily.mjs — 行情库 investment_market 每日采集: 证券主数据 + 全市场日线快照(第 1 段, 2026-10-11 建)
// 链路: Quartz MarketDailyHandler(15:35) → 本脚本 → downloads/market/<交易日>/*.jsonl + manifest.json + DONE_<stage>
//       → Java MarketImportService 读 jsonl 入库(security_master 按 symbol 有则更新/无则插入; kline_day 按交易日先删后插)
// 范围(本段): A股沪深京 / 可转债 / ETF / 沪深京指数。港股通、东财行业·概念·地域板块、外围指数、上市日期 = 后续段(东财 clist)
// 数据源(多源切换铁律): 快照 新浪 getHQNodeData(主) → 腾讯 qt 批量(备 1, 10/17 A9) → 东财 push2 clist(备 2, 走请求层排队; 10/11 实测 push2/push2delay 被断连, 恢复后自动可用)
//   同一节点整节点只用一个源(防同表混源口径); 交易日 = kline.mjs 多源取上证指数最后一根日线日期
// 单位归一(10/11 实测反推 成交额/成交量≈价格): 股票/ETF=股(份), 转债=张, 深市指数=股, 沪市指数源给"手"→×100
// 停牌(开盘价=0)不出日线行; 涨跌停价新浪不给 → 按板块规则算(主板10%含ST/创业科创20%/北交所30%/转债20%; N/C 新股=NULL)
// 断点: 每阶段完成写 DONE_<stage>, 重跑跳过(--force 重做); 盘中(交易日 09:15~15:30)拒跑(快照不完整), --force 可越过
// 用法: node scripts/market/collect_daily.mjs [--expect yyyy-MM-dd] [--stages security,kline_day] [--force] [--src sina|tencent|em] [--out downloads/market]
// 出口: 0=成功 1=采集失败/校验不过/交易日不符(manifest 记原因) 2=盘中拒跑; 一律设 exitCode 自然退出(Windows 下有未关连接时 process.exit 会触发 libuv 断言崩溃, 10/11 实测)
import fs from "node:fs";
import path from "node:path";
import https from "node:https";
import { fileURLToPath } from "node:url";
import { fetchDaily } from "../quotes/kline.mjs";
import { gfetch, gcall } from "../lib/req_guard.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const argv = process.argv.slice(2);
const arg = (k, d) => { const i = argv.indexOf("--" + k); return i > -1 ? argv[i + 1] : d; };
const FORCE = argv.includes("--force");
const STAGES = (arg("stages", "security,kline_day")).split(",");
const ONLY_SRC = arg("src", null);
const OUT_ROOT = path.resolve(ROOT, arg("out", "downloads/market"));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = (lo = 1500, hi = 3500) => sleep(lo + Math.random() * (hi - lo));   // 绝不固定节拍(封禁教训)
const log = (...a) => console.log(`[${new Date().toLocaleTimeString("sv-SE")}]`, ...a);

// ---- HTTP: 强制 IPv4(push2 的 IPv6 路由是死的, scan.mjs 10/1 实测), 不用全局 fetch ----
// 10/15: push2 系 IPv4/IPv6 哪条通会变(10/01 v6 死, 10/15 clist 的 v4 全 socket hang up), 双栈兜底: 先 v4, 连接级失败再 v6
async function getText(url, headers, timeoutMs = 12000) {
  try { return await getTextFam(url, headers, timeoutMs, 4); }
  catch (e) { if (/HTTP \d/.test(String(e.message))) throw e; return await getTextFam(url, headers, timeoutMs, 6); }
}
function getTextFam(url, headers, timeoutMs = 12000, family = 4) {
    return new Promise((resolve, reject) => {
        const req = https.get(url, { family, headers: { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", ...headers }, timeout: timeoutMs }, (res) => {
            if (res.statusCode >= 400) { res.resume(); return reject(new Error("HTTP " + res.statusCode)); }
            const c = []; res.on("data", (d) => c.push(d)); res.on("end", () => resolve(Buffer.concat(c).toString("utf8")));
        });
        req.on("timeout", () => req.destroy(new Error("timeout>" + timeoutMs + "ms")));
        req.on("error", reject);
    });
}
async function withRetry(fn, tries = 3) {
    let last;
    for (let i = 1; i <= tries; i++) {
        try { return await fn(); } catch (e) { last = e; await sleep(2000 * i + Math.random() * 1500); }
    }
    throw last;
}

// ---- 节点定义: 每个节点 = 一类标的, 各源的取法 ----
const NODES = [
    { id: "a_share", secType: "STOCK", sina: "hs_a", em: "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048", minCount: 5000 },
    { id: "cb", secType: "CB", sina: "hskzz_z", em: "b:MK0354", minCount: 100 },
    { id: "etf", secType: "ETF", sina: "etf_hq_fund", em: "b:MK0021,b:MK0022,b:MK0023,b:MK0024", minCount: 500 },
    { id: "index", secType: "INDEX", sina: "hs_s", em: "m:1+s:2,m:0+t:5", minCount: 200 },
];

// 新浪: 统一返回 [{symbol, code, name, open, high, low, close, preClose, volume, amount, turnover}]
async function sinaNode(node) {
    const B = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.";
    const H = { Referer: "https://finance.sina.com.cn" };
    const total = +JSON.parse(await withRetry(() => getText(`${B}getHQNodeStockCount?node=${node.sina}`, H)));
    if (!(total > 0)) throw new Error(`新浪 ${node.sina} 计数异常: ${total}`);
    const out = [];
    for (let p = 1; p <= Math.ceil(total / 100); p++) {
        await jitter();
        const rows = JSON.parse(await withRetry(() => getText(`${B}getHQNodeData?page=${p}&num=100&sort=symbol&asc=1&node=${node.sina}`, H)));
        for (const r of rows) out.push({ symbol: r.symbol, code: r.code, name: r.name, open: +r.open, high: +r.high, low: +r.low,
            close: +r.trade, preClose: +r.settlement, volume: +r.volume, amount: +r.amount, turnover: r.turnoverratio ? +r.turnoverratio : null });
    }
    return { total, rows: out, src: "sina" };
}
// 腾讯 qt 批量(10/17 A9 第一备源): 腾讯没有"按板块列全市场"的接口 → 名单取最近一个已落盘交易日的 security_master.jsonl(当日新上市的票会缺, 下一交易日补上);
//   一次 60 只, 全市场约 135 次请求, 走请求层 tencent_qt(盯盘主源, 从未被封) + 0.3~0.8s 抖动。
//   单位(10/17 实测对照 10/16 新浪入库值): f6 成交量=手 → 股票/ETF/指数/北交所 ×100、转债 ×10(张)、科创板(688/689)本来就是股 ×1; f37 成交额=万元 ×1e4; f38 换手%
let _txUniverse = null;
function txUniverse(tradeDate) {
    if (_txUniverse) return _txUniverse;
    const days = fs.readdirSync(OUT_ROOT).filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d) && d < tradeDate
        && fs.existsSync(path.join(OUT_ROOT, d, "security_master.jsonl"))).sort();
    if (!days.length) throw new Error("腾讯备源: 找不到上一交易日的 security_master.jsonl 当名单");
    const rows = fs.readFileSync(path.join(OUT_ROOT, days.at(-1), "security_master.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));
    _txUniverse = { from: days.at(-1), rows };
    return _txUniverse;
}
async function txNode(node, tradeDate) {
    const { rows: uni, from } = txUniverse(tradeDate);
    const syms = uni.filter((s) => s.secType === node.secType).map((s) => s.symbol);
    if (!syms.length) throw new Error(`腾讯备源 ${node.id}: 名单(${from})里没有 ${node.secType}`);
    const out = [];
    for (let i = 0; i < syms.length; i += 60) {
        const part = syms.slice(i, i + 60);
        const txt = await withRetry(async () => {
            const r = await gfetch(`https://qt.gtimg.cn/q=${part.join(",")}`, { headers: { Referer: "https://gu.qq.com/" } }, { source: "tencent_qt" });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return new TextDecoder("gbk").decode(await r.arrayBuffer());
        });
        for (const m of txt.matchAll(/v_((?:sh|sz|bj)\d{6})="([^"]*)"/g)) {
            const f = m[2].split("~"), sym = m[1], code = sym.slice(2);
            if (!f[3] || !/^\d{8}/.test(f[30] || "") || `${f[30].slice(0, 4)}-${f[30].slice(4, 6)}-${f[30].slice(6, 8)}` !== tradeDate) continue;   // 非当日行情(停牌/退市)不出
            const mult = node.secType === "CB" ? 10 : (node.secType === "STOCK" && /^(688|689)/.test(code)) ? 1 : 100;
            out.push({ symbol: sym, code, name: f[1], open: +f[5], high: +f[33], low: +f[34], close: +f[3], preClose: +f[4],
                volume: +f[6] * mult, amount: f[37] ? +f[37] * 1e4 : null, turnover: f[38] === "" ? null : +f[38] });
        }
        await jitter(300, 800);
    }
    return { total: syms.length, rows: out, src: "tencent", volumeNormalized: true, universeFrom: from };
}
// 东财 clist(第二备源): fltt=2 小数已换算; f5 成交量单位=手(股票/ETF/指数 ×100, 转债 1手=10张 ×10)
//   10/17 A9: 改走请求层 em_clist(窗口 12 次/5 分钟, 排队等候最长 6 分钟/次)——全市场约 80 页, 慢(约 35 分钟)但不会撞 ~25 次/5 分钟的封禁线
async function emNode(node) {
    const H = { Referer: "https://quote.eastmoney.com/" };
    const F = "f2,f5,f6,f8,f12,f13,f14,f15,f16,f17,f18";
    const url = (pn) => `https://push2.eastmoney.com/api/qt/clist/get?pn=${pn}&pz=100&po=1&np=1&fltt=2&invt=2&fid=f12&fs=${encodeURIComponent(node.em)}&fields=${F}`;
    const gt = (u, h) => gcall(u, () => getText(u, h), { source: "em_clist", maxWaitMs: 360000 });
    const first = JSON.parse(await withRetry(() => gt(url(1), H)));
    const total = first.data?.total;
    if (!(total > 0)) throw new Error(`东财 ${node.id} total 异常`);
    const mult = node.secType === "CB" ? 10 : 100;
    const out = [], take = (d) => { for (const r of d) {
        if (r.f2 === "-" || r.f17 === "-") continue;
        const ex = r.f13 === 1 ? "sh" : String(r.f12).startsWith("92") || String(r.f12).startsWith("4") || String(r.f12).startsWith("8") ? "bj" : "sz";
        out.push({ symbol: ex + r.f12, code: String(r.f12), name: r.f14, open: +r.f17, high: +r.f15, low: +r.f16, close: +r.f2, preClose: +r.f18,
            volume: +r.f5 * mult, amount: +r.f6, turnover: r.f8 === "-" ? null : +r.f8 });
    } };
    take(first.data.diff || []);
    for (let pn = 2; pn <= Math.ceil(total / 100); pn++) { await jitter(); take(JSON.parse(await withRetry(() => gt(url(pn), H))).data?.diff || []); }
    return { total, rows: out, src: "dfcf", volumeNormalized: true };
}
const SOURCES = { sina: sinaNode, tencent: txNode, em: emNode };   // 10/17 A9: 新浪 → 腾讯批量 → 东财(请求层排队)

// ---- 归一化 ----
const exchangeOf = (symbol) => symbol.slice(0, 2).toUpperCase();
function boardTypeOf(code, symbol) {
    if (symbol.startsWith("bj")) return "BSE";
    if (/^(688|689)/.test(code)) return "STAR";
    if (/^(300|301|302)/.test(code)) return "GEM";
    return "MAIN";
}
const round = (x, d) => Math.round((x + Number.EPSILON) * 10 ** d) / 10 ** d;
function limits(node, r, boardType) {
    if (!(r.preClose > 0)) return [null, null];
    if (node.secType === "STOCK") {
        if (/^[NC]/.test(r.name)) return [null, null];   // 新股上市前几日(N/C 前缀)无涨跌幅或规则特殊, 不臆算
        const pct = boardType === "BSE" ? 0.30 : boardType === "GEM" || boardType === "STAR" ? 0.20 : 0.10;   // 现行规则: ST 同板块(用户 10/11 校正)
        return [round(r.preClose * (1 + pct), 2), round(r.preClose * (1 - pct), 2)];
    }
    if (node.secType === "CB") return [round(r.preClose * 1.2, 3), round(r.preClose * 0.8, 3)];   // 沪深转债 ±20%
    return [null, null];   // ETF/指数: 不算
}

// ---- 交易日: 上证指数最后一根日线(kline.mjs 多源: 东财 push2his → 腾讯 → 新浪) ----
async function latestTradeDate() {
    const begin = new Date(Date.now() - 20 * 864e5).toISOString().slice(0, 10).replaceAll("-", "");
    const { bars, src } = await fetchDaily("1.000001", { beg: begin, noDb: true });   // 10/15: 定交易日必须看网络(库里是昨天的), 跳过行情库源
    const d = bars.at(-1)?.d;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d || "")) throw new Error("取交易日失败: " + JSON.stringify(bars.at(-1)));
    return { date: d, src };
}

// ---- 原子写 + 断点 ----
function writeJsonl(file, recs) {
    fs.writeFileSync(file + ".tmp", recs.map((r) => JSON.stringify(r)).join("\n") + (recs.length ? "\n" : ""));
    fs.renameSync(file + ".tmp", file);
}

async function main() {
    const now = new Date(), hm = now.getHours() * 100 + now.getMinutes(), wd = now.getDay();
    const { date: tradeDate, src: dateSrc } = await latestTradeDate();
    const today = now.toLocaleDateString("sv-SE");
    const expect = arg("expect", null);   // Java Handler 传当日: 源未更新到当日(识别出的交易日仍是前一日)→报错, 防把昨日数据当今日入库
    if (expect && expect !== tradeDate) {
        console.error(`交易日不符: 期望 ${expect}, 数据源最新交易日 ${tradeDate}(取自 ${dateSrc}), 可能源未更新, 稍后补采`);
        process.exitCode = 1; return;
    }
    if (!FORCE && tradeDate === today && wd >= 1 && wd <= 5 && hm >= 915 && hm < 1530) {
        console.error(`盘中拒跑: ${today} ${hm} 在 09:15~15:30 内, 快照不完整(科创/创业盘后固定价格交易 15:30 才结束); --force 可越过`);
        process.exitCode = 2; return;
    }
    const dir = path.join(OUT_ROOT, tradeDate);
    fs.mkdirSync(dir, { recursive: true });
    const mfFile = path.join(dir, "manifest.json");
    const mf = fs.existsSync(mfFile) ? JSON.parse(fs.readFileSync(mfFile, "utf8")) : { tradeDate, stages: {} };
    mf.stages = mf.stages || {};   // 10/12 修: 同目录 manifest 可能先由 collect_global/collect_auction 建(无 stages 键), 原先直接崩在写 stages 处
    const saveMf = () => fs.writeFileSync(mfFile, JSON.stringify(mf, null, 1));
    log(`交易日 ${tradeDate}(取自 ${dateSrc}), 输出 ${path.relative(ROOT, dir)}, 阶段 ${STAGES.join(",")}`);

    const need = STAGES.filter((s) => FORCE || !fs.existsSync(path.join(dir, "DONE_" + s)));
    if (!need.length) { log("全部阶段已有 DONE, 跳过(--force 重做)"); return; }

    // 一次快照同时喂 security 与 kline_day 两个阶段(同源同刻, 口径一致)
    const security = [], klines = [], nodeStat = {};
    let failed = null;
    for (const node of NODES) {
        const order = ONLY_SRC ? [ONLY_SRC] : ["sina", "tencent", "em"];
        let got = null, errs = [];
        for (const s of order) {
            try { log(`节点 ${node.id} 源 ${s} 开始`); got = await SOURCES[s](node, tradeDate); break; }
            catch (e) { errs.push(`${s}: ${e.message}`); log(`节点 ${node.id} 源 ${s} 失败: ${e.message}, 切下一源`); await jitter(3000, 6000); }
        }
        if (!got) { failed = `节点 ${node.id} 全部源失败: ${errs.join(" | ")}`; break; }
        let suspended = 0;
        for (const r of got.rows) {
            const exchange = exchangeOf(r.symbol);
            const boardType = node.secType === "STOCK" ? boardTypeOf(r.code, r.symbol) : null;
            security.push({ symbol: r.symbol, code: r.code, exchange, secType: node.secType, boardType, name: r.name,
                isSt: /ST/.test(r.name) ? 1 : 0, source: got.src });
            if (!(r.open > 0)) { suspended++; continue; }   // 停牌: 不出日线行
            let volume = Number.isFinite(r.volume) ? Math.round(r.volume) : null;
            if (!got.volumeNormalized && node.secType === "INDEX" && exchange === "SH" && volume != null) volume *= 100;   // 新浪沪市指数给"手"
            const [lu, ld] = limits(node, r, boardType);
            klines.push({ symbol: r.symbol, tradeDate, open: r.open, high: r.high, low: r.low, close: r.close, preClose: r.preClose || null,
                volume, amount: Number.isFinite(r.amount) ? round(r.amount, 2) : null, turnoverRate: r.turnover, limitUp: lu, limitDown: ld, source: got.src });
        }
        nodeStat[node.id] = { source: got.src, total: got.total, rows: got.rows.length, suspended };
        if (got.rows.length < node.minCount) { failed = `节点 ${node.id} 只拿到 ${got.rows.length} 条 < 下限 ${node.minCount}`; break; }
        log(`节点 ${node.id}: ${got.rows.length}/${got.total} 条(源 ${got.src}, 停牌 ${suspended})`);
        await jitter(3000, 6000);
    }
    mf.nodes = nodeStat;
    if (failed) { mf.error = failed; mf.failedAt = new Date().toISOString(); saveMf(); console.error("采集失败:", failed); process.exitCode = 1; return; }
    delete mf.error;

    // symbol 去重(同一 symbol 出现在多节点时保留先到者; 例: 个别 ETF 也在指数节点)
    const seen = new Set(), secUniq = security.filter((s) => !seen.has(s.symbol) && seen.add(s.symbol));
    const seenK = new Set(), kUniq = klines.filter((k) => !seenK.has(k.symbol) && seenK.add(k.symbol));
    const stamp = new Date().toISOString();
    if (need.includes("security")) {
        writeJsonl(path.join(dir, "security_master.jsonl"), secUniq);
        mf.stages.security = { count: secUniq.length, finishedAt: stamp };
        fs.writeFileSync(path.join(dir, "DONE_security"), stamp);
    }
    if (need.includes("kline_day")) {
        writeJsonl(path.join(dir, "kline_day.jsonl"), kUniq);
        mf.stages.kline_day = { count: kUniq.length, finishedAt: stamp };
        fs.writeFileSync(path.join(dir, "DONE_kline_day"), stamp);
    }
    saveMf();
    log(`完成: security_master ${secUniq.length} 条, kline_day ${kUniq.length} 条 → ${path.relative(ROOT, dir)}`);
}

main().catch((e) => { console.error("collect_daily 异常:", e.stack || e.message); process.exitCode = 1; });
