// fetch_cb_quotes.mjs — 转债行情抓取(东财 push2/push2his 公开接口, 2026-10-02)
// 用途: ①日线 OHLC 回填(执行质量复盘: 卖飞/买位分析) ②当日分时(1min)归档(tzzb-sum 每日挂载前调用,
//       分钟级历史东财只留 ~5 天, 必须当天归档才能向后积累) ③实时快照(竞价筛选器前置, 09:15-09:30 用)
// 用法:
//   node scripts/quotes/fetch_cb_quotes.mjs --kline-all                    # 他做过的全部标的日线回填(幂等合并)
//   node scripts/quotes/fetch_cb_quotes.mjs --kline --code 113618          # 单标的日线
//   node scripts/quotes/fetch_cb_quotes.mjs --trends --code 113618         # 单标的最近5日分时归档
//   node scripts/quotes/fetch_cb_quotes.mjs --trends-all                   # 当日有腿标的全部归档(tzzb-sum 前置步骤)
//   node scripts/quotes/fetch_cb_quotes.mjs --snap --code 113618           # 实时快照 stdout(竞价时段行为待实盘验证)
// 产物: downloads/quotes/cb/kline/<code>.json  downloads/quotes/cb/trends/<code>_<yyyy-mm-dd>.json
// 纪律: 公开行情无凭证; 请求抖动 0.75-1.25x; 失败脚本内重试闭环(3次退避), 连续失败显式报错 exit 1
// 备选源: 若东财限流/封禁, 切同花顺日线(待实现, 切换点=fetchJson 一处, 见脚本健壮性铁律)
import fs from "fs";
import path from "path";

const ROOT = path.resolve("downloads/quotes/cb");
const TZZB = path.resolve("downloads/tzzb/bchitudou0");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = () => sleep(800 * (0.75 + Math.random() * 0.5)); // 请求抖动铁律
const arg = (k) => { const i = process.argv.indexOf("--" + k); return i > -1 ? process.argv[i + 1] : null; };

// 沪转债 110/111/113/118 → secid 市场 1; 深转债 123/127/128 → 0
const secid = (code) => (/^(11[0138])/.test(code) ? "1." : "0.") + code;

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

// ---- 日线: klt=101 fqt=1(前复权; 转债分红极少, 影响可忽略) → {date:{o,h,l,c,vol,amt}} 幂等合并 ----
// 双源(铁律): 东财主源; data=null(多为强赎退市债, 10/2 实测 20/51) → 腾讯 ifzq 兜底(退市数据保留更久)
async function kline(code) {
    const url = `https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=${secid(code)}` +
        `&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=1&beg=20250101&end=20500101`;
    let lines = [];
    try {
        const j = await fetchJson(url);
        lines = j?.data?.klines || [];
    } catch (e) {
        if (!/data=null/.test(e.message)) throw e;  // data=null 才落腾讯, 网络错误直接抛
    }
    if (lines.length === 0) {
        const prefix = /^(11[0138])/.test(code) ? "sh" : "sz";
        const turl = `https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=${prefix}${code},day,2025-01-01,2026-12-31,640,qfq`;
        const r = await fetch(turl, { headers: { Referer: "https://gu.qq.com/" } });
        if (!r.ok) throw new Error(`腾讯kline HTTP ${r.status}`);
        const tj = await r.json();
        const d = tj?.data?.[`${prefix}${code}`] || {};
        const rows = d.day || d.qfqday || [];
        if (rows.length === 0) throw new Error("双源均无数据");
        lines = rows.map((x) => x.slice(0, 7).join(","));  // 腾讯同日/ OHLCV 顺序与东财一致
    }
    const file = path.join(ROOT, "kline", `${code}.json`);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const old = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : {};
    for (const line of lines) {
        const [date, o, c, h, l, vol, amt] = line.split(",");
        old[date] = { o: +o, h: +h, l: +l, c: +c, vol: +vol, amt: +(amt || 0) };
    }
    fs.writeFileSync(file, JSON.stringify(old));
    return Object.keys(old).length;
}

// ---- 分时(1min): trends2 ndays 最近N交易日 → 按日切分归档(已存在跳过, 分钟数据不可再生) ----
async function trends(code, ndays = 5) {
    const url = `https://push2his.eastmoney.com/api/qt/stock/trends2/get?secid=${secid(code)}` +
        `&fields1=f1,f2,f3,f4,f5,f6,f7,f8&fields2=f51,f52,f53,f54,f55,f56&ndays=${ndays}&iscr=0`;
    const j = await fetchJson(url);
    const byDay = {};
    for (const line of j?.data?.trends || []) {
        const [dt, price, vol] = line.split(",");
        const day = dt.slice(0, 10);
        (byDay[day] ||= []).push({ t: dt.slice(11), p: +price, vol: +vol });
    }
    fs.mkdirSync(path.join(ROOT, "trends"), { recursive: true });
    let saved = 0, skipped = 0;
    for (const [day, arr] of Object.entries(byDay)) {
        const file = path.join(ROOT, "trends", `${code}_${day}.json`);
        if (fs.existsSync(file)) { skipped++; continue; }  // 归档不可再生, 已存不覆盖
        fs.writeFileSync(file, JSON.stringify({ code, day, bars: arr }));
        saved++;
    }
    return { saved, skipped, days: Object.keys(byDay) };
}

// ---- 实时快照(竞价筛选器前置) ----
// 源切换(脚本健壮性铁律): 东财 push2 系 /stock/get 2026-10-02 实测本网络不可达(连 ut token 也无响应),
// 主源=腾讯 qt.gtimg.cn(无需凭证); 腾讯字段: 3最新 4昨收 5今开 30时间 31涨跌 32涨跌% 33最高 34最低
// (竞价时段 09:15-09:25 字段行为=虚拟撮合价, 待 10/9 实盘验证)
async function snap(code) {
    const prefix = /^(11[0138])/.test(code) ? "sh" : "sz";
    const url = `https://qt.gtimg.cn/q=${prefix}${code}`;
    const r = await fetch(url, { headers: { Referer: "https://gu.qq.com/" } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const txt = await r.text();
    const m = txt.match(/="(.*)"/);
    if (!m) throw new Error("腾讯返回为空(代码错?)");
    const f = m[1].split("~");
    const ts = f[30] || "";
    return { code, name: f[1], 最新: +f[3], 昨收: +f[4], 今开: +f[5],
        涨跌: +f[31], 涨跌幅: +f[32], 最高: +f[33], 最低: +f[34],
        时间: ts ? `${ts.slice(0, 4)}-${ts.slice(4, 6)}-${ts.slice(6, 8)} ${ts.slice(8, 10)}:${ts.slice(10, 12)}:${ts.slice(12, 14)}` : "" };
}

// ---- 他做过的标的清单(从腿文件扫) ----
function hisCodes() {
    const codes = new Set();
    for (const f of fs.readdirSync(TZZB).filter((f) => f.startsWith("change_bs_"))) {
        for (const t of JSON.parse(fs.readFileSync(path.join(TZZB, f), "utf8"))?.ex_data?.change_list || []) {
            if (t.stock_code) codes.add(t.stock_code);
        }
    }
    return [...codes];
}

const MODE = process.argv.includes("--kline-all") ? "kline-all"
    : process.argv.includes("--trends-all") ? "trends-all"
    : process.argv.includes("--kline") ? "kline"
    : process.argv.includes("--trends") ? "trends"
    : process.argv.includes("--snap") ? "snap" : null;
if (!MODE) { console.error("用法见文件头注释"); process.exit(1); }

try {
    if (MODE === "snap") {
        console.log(JSON.stringify(await snap(arg("code")), null, 1));
    } else if (MODE === "kline") {
        console.log(`kline ${arg("code")}: ${await kline(arg("code"))} 天`);
    } else if (MODE === "trends") {
        console.log(`trends ${arg("code")}:`, JSON.stringify(await trends(arg("code"))));
    } else {
        const codes = hisCodes();
        let ok = 0, fail = [];
        for (const c of codes) {
            try {
                if (MODE === "kline-all") await kline(c);
                else {
                    const r = await trends(c);
                    if (r.saved) console.log(`trends ${c}: 归档${r.saved}天 ${r.days.join(",")}`);
                }
                ok++;
            } catch (e) { fail.push(`${c}:${e.message}`); }
            await jitter();
        }
        console.log(`[fetch_cb_quotes] ${MODE} 标的=${codes.length} 成功=${ok} 失败=${fail.length}`);
        if (fail.length) { console.error("失败明细:", fail.join(" | ")); process.exit(1); }
    }
} catch (e) {
    console.error(`[fetch_cb_quotes] 致命失败: ${e.message}`);
    process.exit(1);
}
