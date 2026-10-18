// futures.mjs — 期货与外围行情(10/16 用户令: 全市场取数时要看期货——东财/新浪的国内各品种 + 少量外围; 进事实包和盯盘, 所有链共读)
// 源: 新浪 hq.sinajs.cn(免签, 一次请求拿全部品种; 走统一请求层 req_guard 'sina' 源: 限速/熔断/随机间隔)
//   nf_XX0 = 国内连续主力(商品: 0名 1时刻 2开 3高 4低 5昨收 6买 7卖 8最新 9结算 10昨结算 13持仓 14成交量 17日期;
//            中金所股指 IF/IH/IC/IM: 0开 1高 2低 3最新 4成交量 6持仓 14昨结算(=涨停价/1.1 验证))
//   hf_XX = 外盘(0最新 4高 5低 6时刻 7昨收 12日期 13名); DINIW=美元指数(1最新 3昨收)
// 涨跌幅: 国内按昨结算(期货口径), 外盘按昨收
// 用法: node scripts/quotes/futures.mjs [--write]   (--write: 落 downloads/futures/<日>.json + .md)
//   被 import: futuresMd() 返回 md 块(facts.mjs / live_watch.mjs 用), 失败返回"[期货获取失败: …]"不抛
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { gfetch } from "../lib/req_guard.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
// 品种(10/16 我定, 用户授权"具体影响因素由你决定"): 股指=大盘预期; 农产品=牧原/养殖链(生猪/玉米/豆粕); 能源化工/有色/黑色/新能源=周期板块; 外围少量
export const FUT = [
    ["股指", [["nf_IF0", "沪深300股指"], ["nf_IH0", "上证50股指"], ["nf_IC0", "中证500股指"], ["nf_IM0", "中证1000股指"]]],
    ["农产品", [["nf_LH0", "生猪"], ["nf_C0", "玉米"], ["nf_M0", "豆粕"], ["nf_JD0", "鸡蛋"]]],
    ["能化/有色/黑色", [["nf_SC0", "原油"], ["nf_AU0", "黄金"], ["nf_AG0", "白银"], ["nf_CU0", "铜"], ["nf_RB0", "螺纹钢"], ["nf_I0", "铁矿石"], ["nf_LC0", "碳酸锂"]]],
    ["外围", [["hf_ES", "标普500期货"], ["hf_NQ", "纳指期货"], ["hf_OIL", "布伦特原油"], ["hf_GC", "COMEX黄金"], ["hf_SI", "COMEX白银"], ["DINIW", "美元指数"]]],   // 10/16 用户令: WTI→布伦特, 金银用 COMEX(新浪 hf_GC/hf_SI 即 COMEX)
];
const CFFEX = /^nf_I[FHCM]0$/;

function parse(code, raw) {
    const f = raw.split(",");
    let last, prev, oi = null, date = null;
    if (code === "DINIW") { last = +f[1]; prev = +f[3]; date = f[10]; }
    else if (code.startsWith("hf_")) { last = +f[0]; prev = +f[7]; date = f[12]; }
    else if (CFFEX.test(code)) { last = +f[3]; prev = +f[14]; oi = +f[6]; }
    else { last = +f[8]; prev = +f[10]; oi = +f[13]; date = f[17]; }
    if (!(last > 0) || !(prev > 0)) return null;
    return { last, prev, pct: Math.round((last / prev - 1) * 10000) / 100, oi, date };
}

export async function futuresQuotes() {
    const codes = FUT.flatMap(([, xs]) => xs.map((x) => x[0]));
    const r = await gfetch(`https://hq.sinajs.cn/list=${codes.join(",")}`, { headers: { Referer: "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" } });
    const txt = new TextDecoder("gbk").decode(await r.arrayBuffer());
    const out = {};
    for (const m of txt.matchAll(/hq_str_(\w+)="([^"]*)"/g)) {
        const q = m[2] ? parse(m[1], m[2]) : null;
        if (q) out[m[1]] = q;
    }
    if (!Object.keys(out).length) throw new Error("新浪期货返回空");
    return out;
}

export async function futuresMd() {
    try {
        const q = await futuresQuotes();
        const sgn = (x) => (x > 0 ? "+" : "") + x.toFixed(2) + "%";
        const L = [`(新浪 ${new Date().toTimeString().slice(0, 5)}; 国内=连续主力, 涨跌按昨结算; 外围按昨收)`];
        for (const [grp, xs] of FUT) {
            const items = xs.filter(([c]) => q[c]).map(([c, n]) => `${n} ${q[c].last}(${sgn(q[c].pct)}${q[c].oi ? `, 持仓${Math.round(q[c].oi / 1000)}k` : ""})`);
            if (items.length) L.push(`- ${grp}: ${items.join(" | ")}`);
        }
        return L.join("\n");
    } catch (e) {
        return `[期货获取失败: ${String(e.message || e).slice(0, 100)}]`;
    }
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
    const md = await futuresMd();
    console.log(md);
    if (process.argv.includes("--write")) {
        // 10/17 健壮性 L7: 文件名用调用方给的目标日(check_md 00:00 收尾轮原先写成新自然日); 取数失败不落档, exit 1
        const di = process.argv.indexOf("--date");
        const day = di > -1 && /^\d{4}-\d\d-\d\d$/.test(process.argv[di + 1] || "") ? process.argv[di + 1] : new Date().toLocaleDateString("sv-SE"), dir = path.join(ROOT, "downloads", "futures");
        if (md.startsWith("[期货获取失败")) { console.error(md); process.exit(1); }
        fs.mkdirSync(dir, { recursive: true });
        try { fs.writeFileSync(path.join(dir, `${day}.json`), JSON.stringify({ at: new Date().toISOString(), quotes: await futuresQuotes() }, null, 1)); } catch { /* 失败已在 md 里标注 */ }
        fs.writeFileSync(path.join(dir, `${day}.md`), md + "\n");
    }
}
