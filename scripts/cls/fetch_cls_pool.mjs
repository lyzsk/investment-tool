// fetch_cls_pool.mjs — 财联社涨停/炸板/跌停池 → 「ST 股涨停」与「涨停梯队」两段 md 文本(2026-10-14 建, REA 调研产物)
// 背景: md 的 ### ST 股 一直靠用户手工从财联社 App 抄, ## 涨停梯队 一直空着; 调研发现 App/网页同源的行情接口
//   x-quote.cls.cn/quote/index/up_down_analysis?type=up_pool|up_open_pool|down_pool 公开、免签名、免登录,
//   字段=secu_code/secu_name/change/last_px/time(首次涨停时刻)/up_reason("题材|归因")/is_st/limit_up_days(连板数)/plate[]
//   10/13 实测: up_pool 70 只=当日收评"涨停 70"; is_st=1 三只与用户手抄 ### ST 股 逐字段一致(价/幅/时刻/归因)
// 用法: node scripts/cls/fetch_cls_pool.mjs [--out downloads/cls_pool] [--no-mcap]
//   stdout = 两段 md 文本(### ST 股 / ## 涨停梯队), 末行 JSON:{tradeDate,zt,zb,dt,st}
//   产物 = <out>/<交易日>/{up_pool,up_open_pool,down_pool}.json(原始响应全文) + pool.md
//   **不写 md**: 挂进日记 md 要用户拍板(md 有人工编辑; 10/14 REA 评估结论, 报告 10/18 已删)
// 交易日 = 池内 time 字段的日期(盘前跑拿到的是上一交易日收盘池; 盘中跑=实时池, 不稳定, 建议 15:05 后跑)
// 市值: 池里没有, 用腾讯 qt 批量补(1 次请求, 字段 44=流通市值亿; 10/13 核对: 用户手抄的"63.53 亿"=流通市值, 非总市值); 失败只缺市值不缺行(--no-mcap 跳过)
// 防封: 3~4 个请求/次, 请求间 1~2s 抖动, 每个请求 3 次退避重试; 失败显式非 0, 不编数据
// 出口: 0=ok 1=涨停池抓取失败(财联社+东财备源都失败; 炸板/跌停池失败只降级不阻断) 3=返回结构异常
// 10/17 A12: 财联社池失败自动切东财 push2ex 池(emPool), 梯队头标"本次=东财备源"; 演练 CLS_POOL_DRILL=1
import fs from "node:fs";
import path from "node:path";
import { gfetch } from "../lib/req_guard.mjs";   // 10/15 统一请求层: 按域名记账/熔断/日预算(scripts/lib/req_guard_sources.json)

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
            const r = await gfetch(url, { headers, signal: ctl.signal }).finally(() => clearTimeout(t));
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
// 10/17 A12 备源: 财联社 x-quote 池失败 → 东财 push2ex 涨停/炸板/跌停池(另一家供应商, 与 scan.mjs 连板梯队主源同接口), 映射成财联社字段。
//   语义差异(输出里标注): 东财无"题材|归因", up_reason 放东财行业(hybk); is_st 按名称含 ST 判; limit_up_days=东财连板数 lbc。
//   东财池按日期查: 从今天往前找最近一个非空池(≤4 天, 每天 1 次请求)。演练: CLS_POOL_DRILL=1 跳过财联社直接走本备源。
const EM_POOL = { up_pool: "ZT", up_open_pool: "ZB", down_pool: "DT" };
const ymdOf = (d) => d.toLocaleDateString("sv-SE").replace(/-/g, "");
async function emPool(type, ymd) {
    const t = EM_POOL[type];
    const r = await getText(`https://push2ex.eastmoney.com/getTopic${t}Pool?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt&Pageindex=0&pagesize=300&sort=${t === "DT" ? "fund:asc" : "fbt:asc"}&date=${ymd}`,
        { Referer: "https://quote.eastmoney.com/" });
    let j;
    try { j = JSON.parse(await r.text()); } catch { throw Object.assign(new Error(`东财 ${t}Pool 非 JSON`), { code: 3 }); }
    const pool = j?.data?.pool || [];
    const day = `${ymd.slice(0, 4)}-${ymd.slice(4, 6)}-${ymd.slice(6)}`;
    const hms = (v) => { const s = String(v ?? "150000").padStart(6, "0"); return `${s.slice(0, 2)}:${s.slice(2, 4)}:${s.slice(4, 6)}`; };
    const mk = (c) => (/^6/.test(c) ? "sh" : /^[03]/.test(c) ? "sz" : "bj") + c;
    return { code: 200, src: "eastmoney", ymd, raw: pool, data: pool.map((x) => ({
        secu_code: mk(String(x.c)), secu_name: String(x.n || "").trim(), change: (+x.zdp || 0) / 100, last_px: (+x.p || 0) / 1000,
        time: `${day} ${hms(x.fbt ?? x.lbt)}`, up_reason: x.hybk || "", is_st: /ST/.test(x.n || "") ? 1 : 0, limit_up_days: +x.lbc || 1, plate: [] })) };
}
async function emPoolRecent(type) {
    const d = new Date();
    for (let i = 0; i < 4; i++, d.setDate(d.getDate() - 1)) {
        if (d.getDay() === 0 || d.getDay() === 6) continue;
        const j = await emPool(type, ymdOf(d));
        if (j.data.length) return j;
        await sleep(1000 + Math.random() * 1000);
    }
    throw Object.assign(new Error(`东财 ${EM_POOL[type]}Pool 近 4 天全空`), { code: 1 });
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
    let zt, src = "cls";
    try {
        if (process.env.CLS_POOL_DRILL === "1") throw new Error("演练: 跳过财联社");
        zt = await pool("up_pool");
    } catch (e) {
        console.error(`财联社涨停池失败(${e.message}) → 切东财 push2ex 备源`);
        try { zt = await emPoolRecent("up_pool"); src = "em"; }
        catch (e2) { console.error(`涨停池抓取失败(财联社+东财都失败): ${e2.message}`); process.exitCode = e2.code || e.code || 1; return; }
    }
    const res = { up_pool: zt };
    for (const t of ["up_open_pool", "down_pool"]) {
        await sleep(1000 + Math.random() * 1000);
        try { res[t] = src === "em" ? await emPool(t, zt.ymd) : await pool(t); }
        catch (e) {
            if (src === "em") { console.error(`${t} 失败(降级: 该项计数缺省): ${e.message}`); continue; }
            // 财联社炸板/跌停池单项失败 → 东财同日池兜底(交易日取涨停池 time 的日期)
            try {
                const ymd = ((zt.data.map((x) => x.time).sort().pop() || "").slice(0, 10)).replace(/-/g, "");
                await sleep(1000 + Math.random() * 1000);
                res[t] = await emPool(t, ymd);
                console.error(`${t} 财联社失败(${e.message}) → 东财备源 ${res[t].data.length} 只`);
            } catch (e2) { console.error(`${t} 失败(降级: 该项计数缺省): 财联社 ${e.message} / 东财 ${e2.message}`); }
        }
    }
    const items = zt.data.map((x) => ({ ...x, secu_name: x.secu_name.trim() }));
    const tradeDate = (items.map((x) => x.time).sort().pop() || "").slice(0, 10) || "unknown";
    // 10/14 用户定连板口径=窗口内涨停次数("N天M板", 3天2板也可能): 财联社 limit_up_days 只是连续天数, 用东财涨停池 zttj{days,ct} 覆盖(1 个请求);
    //   东财失败=降级为连续口径 N天N板, 并在梯队头注明
    let emTj = null;
    try {
        if (src === "em") {   // 备源本身就是东财涨停池: 直接用其 zttj, 不再多发一次请求
            emTj = Object.fromEntries((zt.raw || []).filter((x) => x.zttj).map((x) => [x.c, { days: x.zttj.days, ct: x.zttj.ct }]));
            if (!Object.keys(emTj).length) emTj = null;
        } else {
            await sleep(1000 + Math.random() * 1000);
            const r = await getText(`https://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt&Pageindex=0&pagesize=300&sort=fbt:asc&date=${tradeDate.replace(/-/g, "")}`,
                { Referer: "https://quote.eastmoney.com/" });
            const ej = JSON.parse(await r.text());
            emTj = Object.fromEntries((ej.data?.pool || []).filter((x) => x.zttj).map((x) => [x.c, { days: x.zttj.days, ct: x.zttj.ct }]));
            if (!Object.keys(emTj).length) emTj = null;
        }
    } catch (e) { console.error(`东财涨停统计失败(降级连续口径): ${e.message}`); }
    for (const x of items) {
        const t = emTj?.[code6(x.secu_code)];
        x.days = t ? t.days : x.limit_up_days || 1;
        x.ct = t ? t.ct : x.limit_up_days || 1;
    }
    const boardLab = (x) => (x.days <= 1 && x.ct <= 1 ? "首板" : `${x.days} 天 ${x.ct} 板`);

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

    // ── ## 涨停梯队: 按"N天M板"分档(M 降序, 同 M 天数少的在前), 档内按首次涨停时刻; 题材=up_reason 竖线前的标签 ──
    const tiers = {};
    for (const x of items) (tiers[boardLab(x)] ||= []).push(x);
    const theme = (x) => { const r = (x.up_reason || "").trim(); return r.includes("|") ? r.split("|")[0].trim().slice(0, 12) : x.is_st ? "ST" : (r.slice(0, 8) || "?"); };
    const zb = res.up_open_pool?.data?.length, dt = res.down_pool?.data?.length;
    const top = items.reduce((a, x) => (x.ct > a.ct || (x.ct === a.ct && x.days < a.days) ? x : a), items[0]);
    const lad = ["## 涨停梯队", "",
        `> 财联社涨停池 ${tradeDate}${src === "em" ? "(本次=东财备源)" : ""}: 涨停 ${items.length} 只(含 ST ${st.length}) / 炸板 ${zb ?? "?"} / 跌停 ${dt ?? "?"}` +
        (zb != null ? ` / 封板率 ${(items.length / (items.length + zb) * 100).toFixed(0)}%` : "") +
        ` · 最高 ${boardLab(top)}(${top.secu_name}) · 板数口径=${emTj ? "窗口内涨停次数(东财涨停统计)" : "连续涨停天数(东财统计失败降级)"} · 源 ${src === "em" ? "东财 push2ex(财联社池失败降级; 题材列=东财行业, 不是财联社归因)" : "x-quote.cls.cn"}`, ""];
    for (const [k, arr] of Object.entries(tiers).sort((a, b) => b[1][0].ct - a[1][0].ct || a[1][0].days - b[1][0].days)) {
        arr.sort((a, b) => a.time.localeCompare(b.time));
        lad.push(`- **${k}(${arr.length})**: ` + arr.map((x) => `${x.secu_name}(${code6(x.secu_code)} ${theme(x)})`).join("、"));
    }
    const md = [...stMd, "", ...lad, ""].join("\n");

    const dir = path.join(OUT, tradeDate);
    fs.mkdirSync(dir, { recursive: true });
    for (const [k, v] of Object.entries(res)) fs.writeFileSync(path.join(dir, `${k}.json`), JSON.stringify({ fetchedAt: new Date().toISOString(), ...v }));
    fs.writeFileSync(path.join(dir, "pool.md"), md);
    console.log(md);
    // 10/14 用户定: --write 把「## 涨停梯队」挂进该交易日 md 的 ## 涨停梯队 小节(### ST 股 暂不挂, 待用户核对一周再定)
    //   只覆盖 空小节 或 本脚本写过的(首行带 "> 财联社涨停池"); 有人工内容 → 不动, 报"保留人工内容"
    let mounted = null;
    if (process.argv.includes("--write")) {
        const [y, mo] = tradeDate.split("-"), f = path.join("md", `${y}S${Math.ceil(+mo / 3)}`, `${tradeDate}.md`);
        if (!fs.existsSync(f)) mounted = "无md";
        else {
            const raw = fs.readFileSync(f, "utf8"), eol = raw.includes("\r\n") ? "\r\n" : "\n", L = raw.split(/\r?\n/);
            const s = L.findIndex((l) => /^## 涨停梯队\s*$/.test(l));
            if (s === -1) mounted = "md无##涨停梯队小节";
            else {
                let e = L.length;
                for (let i = s + 1; i < L.length; i++) if (/^## /.test(L[i])) { e = i; break; }
                const body = L.slice(s + 1, e).filter((l) => l.trim());
                if (body.length && !body[0].startsWith("> 财联社涨停池")) mounted = "保留人工内容(小节非空且非本脚本所写)";
                else {
                    L.splice(s, e - s, ...lad, "");
                    mounted = "已写";
                }
                // 10/14 用户定: ### ST 股 挂在 ## 涨停分析 末尾, 表格同涨停分析(一行一票); 只覆盖 空/本脚本写的(首行=表头 "| 股票名称"), 人工内容不动
                const a = L.findIndex((l) => /^## 涨停分析\s*$/.test(l));
                if (a !== -1) {
                    let b = L.length;
                    for (let i = a + 1; i < L.length; i++) if (/^## /.test(L[i])) { b = i; break; }
                    const sti = L.findIndex((l, i) => i > a && i < b && /^### ST ?股\s*$/.test(l));
                    const board = boardLab;
                    const why = (x) => { const r = (x.up_reason || "").split("|").pop().replace(/\s+/g, " ").replace(/\|/g, "/").trim(); const s1 = r.split("。")[0]; return (s1.length > 80 ? s1.slice(0, 80) + "…" : s1) || "-"; };
                    const tbl = ["### ST 股", "", "| 股票名称 | 板数 | 涨跌幅 | 涨停时间 | 上涨逻辑 |", "| :------- | :--- | :----- | :------- | :------- |",
                        ...(st.length ? st.map((x) => `| ${x.secu_name} <br>${code6(x.secu_code)} | ${board(x)} | ${(x.change * 100).toFixed(2)}% | ${x.time.slice(11, 16)} | ${why(x)} |`)
                            : ["| (当日无 ST 涨停) | | | | |"]), ""];
                    if (sti === -1) {
                        let ins = b; while (ins > a + 1 && !L[ins - 1].trim()) ins--;
                        L.splice(ins, 0, "", ...tbl);
                        mounted += "+ST股已写";
                    } else {
                        let se = b;
                        for (let i = sti + 1; i < b; i++) if (/^#{1,3} /.test(L[i])) { se = i; break; }
                        const first = L.slice(sti + 1, se).find((l) => l.trim());
                        if (!first || first.startsWith("| 股票名称")) { L.splice(sti, se - sti, ...tbl); mounted += "+ST股已写"; }
                        else mounted += "+ST股保留人工内容";
                    }
                }
                fs.writeFileSync(f, L.join(eol));
            }
        }
        console.error(`[ztpool] ${tradeDate} md: ${mounted}`);
    }
    console.log(`JSON:${JSON.stringify({ tradeDate, src, zt: items.length, zb: zb ?? null, dt: dt ?? null, st: st.length, dir, md: mounted })}`);
})();
