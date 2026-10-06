// kline.mjs — A股/指数 日线多源注册表(2026-10-05, 用户立法: 数据源 switch-case 快速切换)
// 快照层见 scripts/dfcf/paper/snapshot.mjs(5源); 日线层实测健康源=3 独立供应商:
//   东财(前复权,支持增量beg) → 腾讯ifzq(前复权,全量900根) → 新浪(不复权,仅兜底: 除权段价格失真,禁与前复权档混档)
// 实测淘汰(10/5): 网易163 chddata=502死, 雪球=匿名cookie 400016, 东财92镜像=空, 网易实时feed=空。
// 归档格式: <dir>/<code>.json = {code, adjusted, src, klines:[{d,o,c,h,l,v,a}]} 幂等按日期合并
// 导出: fetchDaily / archiveDaily / KLINE_SRCS —— gen_taoge_ic(A1 IC/IR) 与 A2 通用归档共用
// CLI: node scripts/quotes/kline.mjs --codes 002428,1.000001 [--src east] [--dir <d>] [--full]
import fs from "node:fs";
import path from "node:path";

const UA = { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36", Referer: "https://quote.eastmoney.com/" };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const isIdx = (code) => code.includes(".");
const mktSym = (code) => isIdx(code) ? (code.startsWith("1.") ? "sh" + code.slice(2) : "sz" + code.slice(2))
    : (/^(60|68|11[0138]|5)/.test(code) ? "sh" : "sz") + code;
const secid = (code) => isIdx(code) ? code : (/^(60|68|11[0138]|5)/.test(code) ? "1." : "0.") + code;

// ---- 源实现: 统一返回 {bars:[{d,o,c,h,l,v,a}], src, adjusted} ----
async function eastDaily(code, { beg = "19900101" } = {}) {  // 主源: 支持增量(beg=归档末日)
    const url = `https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=${secid(code)}&klt=101&fqt=1&beg=${beg}&end=20500101`
        + `&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56,f57`;
    let lastErr;
    for (let a = 1; a <= 3; a++) {  // 防试错: 3 次退避(东财偶发 reset/限频, 10/5 实证)
        try {
            const r = await fetch(url, { headers: UA });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const j = JSON.parse(await r.text());
            const kl = j?.data?.klines;
            if (!kl?.length) throw new Error("空klines");
            return { bars: kl.map((s) => { const f = s.split(","); return { d: f[0], o: +f[1], c: +f[2], h: +f[3], l: +f[4], v: +f[5], a: +f[6] }; }), src: "east", adjusted: true };
        } catch (e) { lastErr = e; await sleep(800 * a); }
    }
    throw lastErr;
}
async function txDaily(code) {  // 兜底1: 腾讯 fqkline(qfq 前复权), 忽略 beg 全量 900 根
    const sym = mktSym(code);
    const r = await fetch(`https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=${sym},day,,,900,qfq`, { headers: UA });
    if (!r.ok) throw new Error(`tx HTTP ${r.status}`);
    const j = JSON.parse(await r.text());
    const arr = j?.data?.[sym]?.qfqday || j?.data?.[sym]?.day;
    if (!arr?.length) throw new Error("tx 空");
    return { bars: arr.map((x) => ({ d: x[0], o: +x[1], c: +x[2], h: +x[3], l: +x[4], v: +x[5], a: 0 })), src: "tencent", adjusted: true };
}
async function sinaDaily(code) {  // 兜底2: 新浪日K(不复权!) — 仅前两源全灭时用, 且禁与前复权档混档
    const sym = mktSym(code);
    const r = await fetch(`https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_=/CN_MarketDataService.getKLineData?symbol=${sym}&scale=240&ma=no&datalen=1023`,
        { headers: { ...UA, Referer: "https://finance.sina.com.cn/" } });
    if (!r.ok) throw new Error(`sina HTTP ${r.status}`);
    const t = await r.text();
    const s0 = t.indexOf("["), s1 = t.lastIndexOf("]");  // 不猜 JSONP 包裹形状, 直接取首[到末]
    if (s0 < 0 || s1 <= s0) throw new Error("sina 空");
    const arr = JSON.parse(t.slice(s0, s1 + 1));
    if (!arr?.length) throw new Error("sina 空数组");
    return { bars: arr.map((x) => ({ d: x.day, o: +x.open, c: +x.close, h: +x.high, l: +x.low, v: +x.volume, a: 0 })), src: "sina", adjusted: false };
}

// ---- 源注册表(顺序=fallback 顺序) ----
export const KLINE_SRCS = [
    { id: "east", label: "东财push2his", adjusted: true, fn: eastDaily },
    { id: "tencent", label: "腾讯ifzq", adjusted: true, fn: txDaily },
    { id: "sina", label: "新浪不复权", adjusted: false, fn: sinaDaily },
];

export async function fetchDaily(code, opt = {}) {
    if (opt.src) {  // 强制单源: 不回落, 败=败(排障语义)
        const s = KLINE_SRCS.find((x) => x.id === opt.src);
        if (!s) throw new Error(`未知源 ${opt.src}(可用: ${KLINE_SRCS.map((x) => x.id).join("/")})`);
        return s.fn(code, opt);
    }
    let lastErr;
    for (const { fn } of KLINE_SRCS) {
        try { return await fn(code, opt); } catch (e) { lastErr = e; await sleep(300); }
    }
    throw lastErr;
}

// ---- 归档(幂等增量, 按日期去重合并; 复权口径不同拒混档) ----
export async function archiveDaily(codes, { dir = "downloads/quotes/daily", src, gapMs = 600, full = false } = {}) {
    fs.mkdirSync(dir, { recursive: true });
    let ok = 0, inc = 0, fail = [], mixed = [];
    for (const code of [...new Set(codes)]) {
        const f = path.join(dir, code.replace(".", "_") + ".json");
        let old = null;
        if (fs.existsSync(f)) { try { old = JSON.parse(fs.readFileSync(f, "utf8")); } catch { old = null; } }
        try {
            const beg = !full && old?.klines?.length ? old.klines[old.klines.length - 1].d.replaceAll("-", "") : "19900101";
            const fresh = await fetchDaily(code, { src, beg });
            if (old?.klines?.length && ((old.adjusted ?? true) !== fresh.adjusted)) {  // 老档无 adjusted 字段=前复权源写入, 视为 true
                mixed.push(`${code}:${old.adjusted ? "前复权档" : "不复权档"}拒混${fresh.src}`);
                continue;  // 不复权源不污染已有前复权档(收益计算会被除权段打歪)
            }
            const map = new Map((!full && old?.klines || []).map((x) => [x.d, x]));
            for (const x of fresh.bars) map.set(x.d, x);
            const klines = [...map.values()].sort((a, b) => a.d.localeCompare(b.d));
            fs.writeFileSync(f, JSON.stringify({ code, adjusted: fresh.adjusted, src: fresh.src, klines }));
            old && !full ? inc++ : ok++;
        } catch (e) { fail.push(`${code}:${e.message}`); }
        await sleep(gapMs);
    }
    console.log(`日线归档: 新 ${ok} / 增量 ${inc} / 失败 ${fail.length}${fail.length ? " (" + fail.slice(0, 8).join(", ") + ")" : ""}${mixed.length ? " / 拒混档 " + mixed.length : ""} → ${dir}/`);
    return { ok, inc, fail, mixed };
}

// ---- CLI(仅直接执行时跑, 被 import 时跳过——gen_taoge_ic 等消费方只取函数) ----
import { pathToFileURL } from "node:url";
const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMain) {
    const argv = process.argv.slice(2);
    const arg = (k) => { const i = argv.indexOf("--" + k); return i > -1 ? argv[i + 1] : null; };
    if (argv.includes("--from-corpus")) {
        // A2 批量回补: 扫全量 md 的（6位代码）去重 → 归档(增量幂等, 已档票秒过)
        const codes = new Set();
        for (const q of fs.readdirSync("md").filter((d) => /^\d{4}S\d$/.test(d)).sort()) {
            for (const f of fs.readdirSync(path.join("md", q)).filter((f) => f.endsWith(".md")).sort()) {
                for (const m of fs.readFileSync(path.join("md", q, f), "utf8").matchAll(/（(\d{6})）/g)) codes.add(m[1]);
            }
        }
        console.log(`corpus 去重 ${codes.size} 票, 增量归档开始(已档秒过, 新票~1s/只)`);
        const r = await archiveDaily([...codes], { src: arg("src") || undefined, dir: arg("dir") || undefined, full: argv.includes("--full") });
        console.log(`JSON:${JSON.stringify({ codes: codes.size, ok: r.ok, inc: r.inc, fail: r.fail.length })}`);
    } else if (argv.includes("--codes")) {
        const codes = arg("codes").split(",").map((s) => s.trim()).filter(Boolean);
        const r = await archiveDaily(codes, { src: arg("src") || undefined, dir: arg("dir") || undefined, full: argv.includes("--full") });
        console.log(`JSON:${JSON.stringify({ ok: r.ok, inc: r.inc, fail: r.fail.length })}`);
        if (r.fail.length && !r.ok && !r.inc) process.exit(2);
    } else {
        console.error("用法: --codes 002428,1.000001 [--src east|tencent|sina] [--dir <d>] [--full] | --from-corpus");
        process.exit(1);
    }
}