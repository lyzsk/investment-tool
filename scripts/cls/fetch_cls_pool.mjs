// fetch_cls_pool.mjs — 财联社涨停/炸板/跌停池 → 「ST 股涨停」与「涨停梯队」两段 md 文本(2026-10-14 建, REA 调研产物)
// 背景: md 的 ### ST 股 一直靠用户手工从财联社 App 抄, ## 涨停梯队 一直空着; 调研发现 App/网页同源的行情接口
//   x-quote.cls.cn/quote/index/up_down_analysis?type=up_pool|up_open_pool|down_pool 公开、免签名、免登录,
//   字段=secu_code/secu_name/change/last_px/time(首次涨停时刻)/up_reason("题材|归因")/is_st/limit_up_days(连板数)/plate[]
//   10/13 实测: up_pool 70 只=当日收评"涨停 70"; is_st=1 三只与用户手抄 ### ST 股 逐字段一致(价/幅/时刻/归因)
// 用法: node scripts/cls/fetch_cls_pool.mjs [--out downloads/cls_pool] [--no-mcap]
//   stdout = 两段 md 文本(### ST 股 / ## 涨停梯队), 末行 JSON:{tradeDate,zt,zb,dt,st}
//   产物 = <out>/<交易日>/{up_pool,up_open_pool,down_pool}.json(原始响应全文) + pool.md
//   **不写 md**: 挂进日记 md 要用户拍板(md 有人工编辑, 见 docs/research/rea_eval_20261014.md)
// 交易日 = 池内 time 字段的日期(盘前跑拿到的是上一交易日收盘池; 盘中跑=实时池, 不稳定, 建议 15:05 后跑)
// 市值: 池里没有, 用腾讯 qt 批量补(1 次请求, 字段 44=流通市值亿; 10/13 核对: 用户手抄的"63.53 亿"=流通市值, 非总市值); 失败只缺市值不缺行(--no-mcap 跳过)
// 防封: 3~4 个请求/次, 请求间 1~2s 抖动, 每个请求 3 次退避重试; 失败显式非 0, 不编数据
// 出口: 0=ok 1=涨停池抓取失败(炸板/跌停池失败只降级不阻断) 3=返回结构异常
import fs from "node:fs";
import path from "node:path";

const ARGS = process.argv.slice(2);
const opt = (k, d) => { const i = ARGS.indexOf(k); return i === -1 ? d : ARGS[i + 1]; };
const OUT = opt("--out", path.join("downloads", "cls_pool"));
const NO_MCAP = ARGS.includes("--no-mcap");
const UA = { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9", Referer: "https://www.cls.cn/" };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function getText(url, headers = UA) {
    let last = "";
    for (let i = 1; i <= 3; i++) {
        try {
            const ctl = new AbortController();
            const t = setTimeout(() => ctl.abort(), 10000);
            const r = await fetch(url, { headers, signal: ctl.signal }).finally(() => clearTimeout(t));
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r;
        } catch (e) { last = e.message; if (i < 3) await sleep(1000 * i * (0.75 + Math.random() * 0.5)); }
    }
    throw new Error(last);
}
async function pool(type) {
    const r = await getText(`https://x-quote.cls.cn/quote/index/up_down_analysis?app=CailianpressWeb&os=web&rever=1&sv=8.7.9&type=${type}&way=last_px`);
    const j = await r.json();
    if (j.code !== 200 || !Array.isArray(j.data)) throw Object.assign(new Error(`${type} 结构异常 code=${j.code}`), { code: 3 });
    return j;
}
const code6 = (s) => s.replace(/^(sh|sz|bj)/, "");
const pct = (c) => `${c >= 0 ? "+" : ""}${(c * 100).toFixed(2)}%`;

async function mcapOf(items) {   // 腾讯 qt 批量: 字段 44=流通市值(亿); 北交所不支持(留空)
    const syms = items.map((x) => x.secu_code).filter((s) => /^(sh|sz)/.test(s));
    if (!syms.length) return {};
    const r = await getText(`https://qt.gtimg.cn/q=${syms.join(",")}`, { Referer: "https://gu.qq.com/" });
    const txt = new TextDecoder("gbk").decode(await r.arrayBuffer());
    const out = {};
    for (const m of txt.matchAll(/v_((?:sh|sz)\d{6})="([^"]*)"/g)) { const f = m[2].split("~"); if (+f[44] > 0) out[m[1]] = `${(+f[44]).toFixed(2)}亿`; }
    return out;
}

(async () => {
    let zt;
    try { zt = await pool("up_pool"); } catch (e) { console.error(`涨停池抓取失败: ${e.message}`); process.exitCode = e.code || 1; return; }
    const res = { up_pool: zt };
    for (const t of ["up_open_pool", "down_pool"]) {
        await sleep(1000 + Math.random() * 1000);
        try { res[t] = await pool(t); } catch (e) { console.error(`${t} 失败(降级: 该项计数缺省): ${e.message}`); }
    }
    const items = zt.data.map((x) => ({ ...x, secu_name: x.secu_name.trim() }));
    const tradeDate = (items.map((x) => x.time).sort().pop() || "").slice(0, 10) || "unknown";

    // ── ### ST 股: 照用户手抄格式 "序. 名 | 价 | 幅 | 涨停时刻 | 流通市值 | 代码 | 归因", 连板数降序→首次涨停时刻(10/13 手抄顺序同此) ──
    const st = items.filter((x) => x.is_st === 1).sort((a, b) => (b.limit_up_days || 1) - (a.limit_up_days || 1) || a.time.localeCompare(b.time));
    let mcap = {};
    if (st.length && !NO_MCAP) {
        await sleep(800 + Math.random() * 800);
        try { mcap = await mcapOf(st); } catch (e) { console.error(`市值补充失败(只缺市值列): ${e.message}`); }
    }
    const stMd = ["### ST 股", ""].concat(st.length
        ? st.map((x, i) => `${i + 1}. ${x.secu_name} | ${x.last_px} | ${pct(x.change)} | ${x.time.slice(11)} | ${mcap[x.secu_code] || "?"} | ${code6(x.secu_code)} | ${(x.up_reason || "").replace(/\s+/g, " ").trim()}`)
        : ["(当日无 ST 涨停)"]);

    // ── ## 涨停梯队: 按连板数(limit_up_days)降序分档, 档内按首次涨停时刻; 题材=up_reason 竖线前的标签 ──
    const tiers = {};
    for (const x of items) (tiers[x.limit_up_days || 1] ||= []).push(x);
    const theme = (x) => { const r = (x.up_reason || "").trim(); return r.includes("|") ? r.split("|")[0].trim().slice(0, 12) : x.is_st ? "ST" : (r.slice(0, 8) || "?"); };
    const zb = res.up_open_pool?.data?.length, dt = res.down_pool?.data?.length;
    const lad = ["## 涨停梯队", "",
        `> 财联社涨停池 ${tradeDate}: 涨停 ${items.length} 只(含 ST ${st.length}) / 炸板 ${zb ?? "?"} / 跌停 ${dt ?? "?"}` +
        (zb != null ? ` / 封板率 ${(items.length / (items.length + zb) * 100).toFixed(0)}%` : "") +
        ` · 最高 ${Math.max(...Object.keys(tiers).map(Number))} 连板 · 源 x-quote.cls.cn`, ""];
    for (const k of Object.keys(tiers).map(Number).sort((a, b) => b - a)) {
        const arr = tiers[k].sort((a, b) => a.time.localeCompare(b.time));
        lad.push(`- **${k === 1 ? "首板" : k + " 连板"}(${arr.length})**: ` + arr.map((x) => `${x.secu_name}(${code6(x.secu_code)} ${theme(x)})`).join("、"));
    }
    const md = [...stMd, "", ...lad, ""].join("\n");

    const dir = path.join(OUT, tradeDate);
    fs.mkdirSync(dir, { recursive: true });
    for (const [k, v] of Object.entries(res)) fs.writeFileSync(path.join(dir, `${k}.json`), JSON.stringify({ fetchedAt: new Date().toISOString(), ...v }));
    fs.writeFileSync(path.join(dir, "pool.md"), md);
    console.log(md);
    console.log(`JSON:${JSON.stringify({ tradeDate, zt: items.length, zb: zb ?? null, dt: dt ?? null, st: st.length, dir })}`);
})();
