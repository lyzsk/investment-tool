// gen_taoge_ic.mjs — 桃哥提及强度 → 次日收益 IC/IR 记分(2026-10-05, TODO §A.1)
// 定位: 与 gen_scorecard.mjs(命中率口径) 并列的"md→persona 记分"家族; 本脚本=连续强度信号的秩相关口径。
//   桃哥提及≠买入推荐(跌停票多为复盘教训), 故强度**带符号**(观点方向×档位)——TODO §A.1 与"分类命中率"并存非替代。
// 数据流(子命令按序跑, --all=全管线):
//   --extract  md 桃哥小节 → results/taoge_ic/mentions.json   (提及事件: 日期/代码/档位/注意力/命中词)
//   --kline    事件票+指数日线增量归档 → downloads/quotes/daily/<code>.json (东财 klt=101 前复权, 与 A2 归档同格式)
//   --calc     事件×收益 → skills/taoge-skill/persona/ic.json + 控制台记分卡
// 收益口径(2026-10-05 用户立法: 复盘说"明天"=T+1, A股T+1规则最早T+2卖):
//   main = o(T+2)/o(T+1)-1 (T+1开盘买→T+2开盘卖, 持整一个交易日, 可执行)
//   aux  = c(T+2)/o(T+1)-1 | 对照 o(T+1)→c(T+1) 不可执行仅看方向含金量
//   超额 = 窗口收益 − 板属指数同窗收益(30/68→创业板指, 其余→上证), IC 报 excess 为主
// IC/IR: 日度 Spearman(mid-rank 平均秩, 离散档位大量并列必须处理; 全同档日跳过计数)
//   + pooled IC(全部事件按日去均值后合并, 小日样本的功效补充) + pooled Kendall tau-b(并列稳健交叉印证)
//   IR=mean(IC)/std(IC); 窗口=全量/近20日/regime三桶(创业板指20日收益+MA20斜率机械分强弱震荡)
// 已知留白(见 TODO §A.1): ①LLM 语义补强(语气/仓位动作的隐含方向) ②日历季节相似窗(语料无跨年数据)
//   ③持仓段位未加权(skin-in-game 与"死扛"信号混杂, 攒样本再定) ④北交所票指数基准暂用上证
import fs from "node:fs";
import path from "node:path";

const OUT_EVENTS = "results/taoge_ic/mentions.json";
const KLINE_DIR = "downloads/quotes/daily";
const IC_JSON = "skills/taoge-skill/persona/ic.json";
const SECTION = "#### 股市 - 桃哥复盘";
const IDX = { sh: "1.000001", cyb: "0.399006" }; // 上证指数/创业板指(日历+基准)

// ---- 强度档位映射表(v1 关键词草案; 求序: 从±3向内, 首个命中定档; 直接改词重跑即可) ----
const TAG_DIRECT = { "空": -2, "看空": -2, "多": 2, "看多": 2, "持有": 2, "买": 3 }; // 提及行 tag 整词直判(优先于关键词表)
const GRADES = [
    { g: -3, kw: ["团灭", "秒跌停", "死扛", "被套", "崩了", "强烈不看好"] },
    { g: -2, kw: ["走了", "兑现", "回避", "监管函", "收了一张监管", "跌停", "不碰"] },
    { g: -1, kw: ["跟跌", "跟崩", "被带下来", "被带下"] },
    { g: +1, kw: ["抗跌", "逆势", "红盘", "领涨", "辨识度高"] },
    { g: +2, kw: ["看好", "低吸", "想买", "持有", "二波", "格局单", "关注"] },
    { g: +3, kw: ["买了", "打板", "建仓", "上车", "全仓买"] },
];

const arg = (k) => { const i = process.argv.indexOf("--" + k); return i > -1 ? process.argv[i + 1] : null; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const mode = process.argv.includes("--all") ? "all"
    : process.argv.includes("--extract") ? "extract" : process.argv.includes("--kline") ? "kline"
        : process.argv.includes("--calc") ? "calc" : process.argv.includes("--llm-split") ? "llmsplit" : null;
if (!mode) { console.error("用法: --extract | --kline | --calc | --all"); process.exit(1); }

// ---------- 提及抽取 ----------
// 打分=TAG_DIRECT 整词直判 + GRADES 关键词表(从±3向内首个命中); **注意力秒数只抽取存档不参与打分**
// (10/5 用户立法: 机械±1修正方向可能反——盯25s可能是在研究"怎么这么抗跌"的正向犹豫; 注意力语义留 LLM 补强层消费)
function gradeOf(tag, text) {
    const t = (tag || "").trim();
    if (TAG_DIRECT[t] != null) return { g: TAG_DIRECT[t], hit: `tag:${t}` };
    for (const { g, kw } of GRADES) {
        for (const k of kw) if (text.includes(k)) return { g, hit: k };
    }
    return { g: 0, hit: null };
}
function extractAll() {
    const events = new Map(); // key=date|code → event(多节命中合并: 取最大|档|, 注意力累加, 源列表)
    let secDays = 0, emptyDays = 0, skippedNeutral = 0;
    const add = (date, code, name, g, hit, src, attS) => {
        const key = `${date}|${code}`;
        const e = events.get(key) || { date, code, name, grade: 0, attention_s: 0, sources: [], hits: [] };
        if (Math.abs(g) > Math.abs(e.grade)) e.grade = g;
        e.attention_s += attS || 0;
        e.sources.push(src);
        if (hit) e.hits.push(hit);
        e.name = e.name || name;
        events.set(key, e);
    };
    for (const q of fs.readdirSync("md").filter((d) => /^\d{4}S\d$/.test(d)).sort()) {
        for (const f of fs.readdirSync(path.join("md", q)).filter((f) => f.endsWith(".md") && fs.statSync(path.join("md", q, f)).isFile()).sort()) {
            const text = fs.readFileSync(path.join("md", q, f), "utf8");
            const hi = text.indexOf(SECTION);
            if (hi === -1) continue;
            const rest = text.slice(hi + SECTION.length);
            const endM = rest.match(/^#{2,4} /m);
            const sec = endM ? rest.slice(0, endM.index) : rest;
            if (sec.trim().length < 40) { emptyDays++; continue; } // 空壳标题(当日未合成)
            secDays++;
            const date = f.slice(0, 10);
            // ① 提及个股/持仓逆向行(嵌套缩进 bullet 也收; CRLF 行尾用 \r? 收尾)
            for (const m of sec.matchAll(/^\s*- (?:\*\*)?([^（*]+?)(?:\*\*)?（(\d{6})）(?:·\s*([^—·\n]*?))?(?:\s*—\s*|\s*·\s*)(.*)\r?$/gm)) {
                const [, name, code, tag, note] = m;
                const attM = (note || "").match(/盯\s*([\d.]+)s/);
                const { g, hit } = gradeOf(tag, `${tag || ""} ${note || ""}`);
                if (g === 0) { skippedNeutral++; continue; }
                add(date, code, name.trim(), g, hit, "提及行", attM ? +attM[1] : 0);
            }
            // ② 画面增量段: "票名 12.34（+5.6%）盘口盯 26.0s" (沉默关注; 无方向词→不打分只记注意力, 供 LLM 补强层)
            for (const m of sec.matchAll(/([^\s，。；·（"]{2,10}) [\d.]+（[+\-\d.]+%）(?:盘口|分时)?盯 ?([\d.]+)s/g)) {
                const [, name, s] = m;
                const { g, hit } = gradeOf(null, m[0]);
                if (g === 0) continue; // 纯注意力无观点 → 不进带符号口径(注意力口径=二期)
                add(date, "", name, g, hit, "画面增量", +s); // code 空缺待回填(下行尝试)
            }
        }
    }
    // 画面增量事件无 code: 尝试按票名在当日提及行回填, 找不到=丢弃计数
    let dropped = 0;
    const final = [];
    for (const e of events.values()) {
        if (!e.code) {
            const byName = [...events.values()].find((x) => x.code && x.date === e.date && x.name === e.name);
            if (byName) { byName.attention_s += e.attention_s; byName.sources.push(...e.sources); continue; }
            dropped++; continue;
        }
        if (e.grade === 0) { skippedNeutral++; continue; }
        final.push(e);
    }
    final.sort((a, b) => a.date.localeCompare(b.date));
    fs.mkdirSync(path.dirname(OUT_EVENTS), { recursive: true });
    fs.writeFileSync(OUT_EVENTS, JSON.stringify({ generatedAt: new Date().toISOString(), events: final }, null, 1));
    console.log(`抽取: ${secDays} 个有效小节(空壳 ${emptyDays}) → ${final.length} 事件 / ${new Set(final.map((e) => e.date)).size} 天; 中性剔除 ${skippedNeutral}, 画面无code丢弃 ${dropped}`);
    console.log(`JSON:${JSON.stringify({ events: final.length, days: new Set(final.map((e) => e.date)).size, skippedNeutral, dropped })}`);
    return final;
}

// ---------- 日线归档(统一走 scripts/quotes/kline.mjs 多源注册表: 东财→腾讯→新浪, 10/5 用户立法) ----------
import { archiveDaily } from "../quotes/kline.mjs";

// ---------- IC/IR 计算 ----------
const midrank = (xs) => { // 并列取平均秩(mid-rank), Spearman 标准处理
    const idx = xs.map((v, i) => [v, i]).sort((a, b) => a[0] - b[0]);
    const r = new Array(xs.length);
    let i = 0;
    while (i < idx.length) {
        let j = i;
        while (j + 1 < idx.length && idx[j + 1][0] === idx[i][0]) j++;
        const avg = (i + j) / 2 + 1;
        for (let k = i; k <= j; k++) r[idx[k][1]] = avg;
        i = j + 1;
    }
    return r;
};
const pearson = (a, b) => {
    const n = a.length, ma = a.reduce((s, x) => s + x, 0) / n, mb = b.reduce((s, x) => s + x, 0) / n;
    let cov = 0, va = 0, vb = 0;
    for (let i = 0; i < n; i++) { const x = a[i] - ma, y = b[i] - mb; cov += x * y; va += x * x; vb += y * y; }
    return va && vb ? cov / Math.sqrt(va * vb) : null;
};
const spearman = (a, b) => (new Set(a).size < 2 || new Set(b).size < 2) ? null : pearson(midrank(a), midrank(b));
function tauB(a, b) { // Kendall tau-b(并列稳健)
    let c = 0, d = 0, t = 0, u = 0;
    for (let i = 0; i < a.length; i++) for (let j = i + 1; j < a.length; j++) {
        const s = Math.sign(a[i] - a[j]), r = Math.sign(b[i] - b[j]);
        if (s * r > 0) c++; else if (s * r < 0) d++; else { if (s !== 0 && r === 0) t++; else if (s === 0 && r !== 0) u++; else { t++; u++; } }
    }
    const den = Math.sqrt((c + d + t) * (c + d + u));
    return den ? (c - d) / den : null;
}
function loadKL(name) {
    const f = path.join(KLINE_DIR, name.replace(".", "_") + ".json");
    if (!fs.existsSync(f)) return null;
    const k = JSON.parse(fs.readFileSync(f, "utf8")).klines;
    const map = new Map(k.map((x, i) => [x.d, i]));
    return { k, map };
}
function regimeOf(idxKL, date) { // 创业板指 20日收益+MA20: >+8%强 / <-8%弱 / 中间震荡(参数占位可调)
    const k = idxKL.k;
    let i = -1;
    for (let j = k.length - 1; j >= 0; j--) if (k[j].d <= date) { i = j; break; }
    if (i < 20) return "unknown";
    const c = k[i].c, ref = k[i - 20].c, r20 = c / ref - 1;
    const ma20 = k.slice(i - 19, i + 1).reduce((s, x) => s + x.c, 0) / 20;
    const ma20p = k.slice(i - 24, i - 19).reduce((s, x) => s + x.c, 0) / 5;
    const slope = ma20 / ma20p - 1;
    if (r20 > 0.08 && slope > 0) return "强";
    if (r20 < -0.08) return "弱";
    return "震荡";
}
function calc() {
    const { events } = JSON.parse(fs.readFileSync(OUT_EVENTS, "utf8"));
    const sh = loadKL(IDX.sh), cyb = loadKL(IDX.cyb);
    if (!sh || !cyb) { console.error("缺指数日线(先 --kline)"); process.exit(2); }
    const cal = cyb.k.map((x) => x.d); // 交易日历(创业板指)
    const rows = []; const pending = [], noKl = [];
    for (const e of events) {
        const di = cal.findIndex((d) => d >= e.date); // md 日期=复盘日(盘后), T+1=其后首个交易日
        if (di < 0 || !cal[di + 1]) { pending.push(e); continue; }
        const t1 = cal[di], t2 = cal[di + 1];
        const kl = loadKL(e.code);
        if (!kl) { noKl.push(e.code); continue; }
        const i1s = kl.map.get(t1), i2s = kl.map.get(t2); // map 存的是下标不是 bar
        if (i1s == null || i2s == null || !(kl.k[i1s].o > 0) || !(kl.k[i2s].o > 0)) { noKl.push(e.code); continue; } // 停牌/无bar
        const b1 = kl.k[i1s], b2 = kl.k[i2s];
        const board = /^(30|68)/.test(e.code) ? cyb : sh;
        const i1 = board.map.get(t1), i2 = board.map.get(t2);
        const ret = (x, y) => y.o / x.o - 1, retC = (x, y) => y.c / x.o - 1;
        const rawMain = ret(b1, b2);
        const idxMain = i1 != null && i2 != null ? ret(board.k[i1], board.k[i2]) : null;
        rows.push({
            date: e.date, code: e.code, name: e.name, grade: e.grade, attention_s: e.attention_s,
            t1, t2, main: rawMain, aux: retC(b1, b2), dayOnly: retC(b1, b1),
            excess: idxMain == null ? null : rawMain - idxMain, regime: regimeOf(cyb, t1),
        });
    }
    // 日度 IC(≥3 事件才算) + pooled
    const byDay = {};
    for (const r of rows) if (r.excess != null) (byDay[r.date] = byDay[r.date] || []).push(r);
    const daily = [];
    let degenerateDays = 0;
    for (const d of Object.keys(byDay).sort()) {
        if (byDay[d].length < 3) { degenerateDays++; continue; }
        const g = byDay[d].map((r) => r.grade);
        const icE = spearman(g, byDay[d].map((r) => r.excess)), icR = spearman(g, byDay[d].map((r) => r.main));
        if (icE == null && icR == null) { degenerateDays++; continue; }
        daily.push({ date: d, n: byDay[d].length, icExcess: icE == null ? null : +icE.toFixed(3), icRaw: icR == null ? null : +icR.toFixed(3) });
    }
    const stats = (ics) => {
        const v = ics.filter((x) => x != null);
        if (!v.length) return null;
        const mean = v.reduce((a, x) => a + x, 0) / v.length;
        const std = Math.sqrt(v.reduce((a, x) => a + (x - mean) ** 2, 0) / (v.length - 1 || 1));
        return { n: v.length, icMean: +mean.toFixed(4), icStd: +std.toFixed(4), ir: std ? +(mean / std).toFixed(3) : null, tStat: std ? +(mean / std * Math.sqrt(v.length)).toFixed(2) : null };
    };
    // pooled: 按日去均值(消市场日效应)后合并秩相关
    const pooledGrades = [], pooledRets = [];
    for (const d of Object.keys(byDay)) {
        const list = byDay[d].filter((r) => r.excess != null);
        if (list.length < 2) continue;
        const mu = list.reduce((a, r) => a + r.excess, 0) / list.length;
        for (const r of list) { pooledGrades.push(r.grade); pooledRets.push(r.excess - mu); }
    }
    const byRegime = {};
    for (const r of rows) (byRegime[r.regime] = byRegime[r.regime] || []).push(r);
    const regimeStats = {};
    for (const [rg, list] of Object.entries(byRegime)) {
        const g = list.map((r) => r.grade), x = list.map((r) => r.excess).filter((v) => v != null);
        regimeStats[rg] = { events: list.length, pooledIC: spearman(g, list.map((r) => r.excess)) == null ? null : +spearman(g, list.map((r) => r.excess)).toFixed(3) };
    }
    const pooledBy = (types) => {
        const g = [], x = [];
        for (const d of Object.keys(byDay)) {
            const list = byDay[d].filter((r) => types.includes(r._pt));
            if (list.length < 2) continue;
            const mu = list.reduce((a, r) => a + r.excess, 0) / list.length;
            for (const r of list) { g.push(r.grade); x.push(r.excess - mu); }
        }
        return { ic: spearman(g, x) == null ? null : +spearman(g, x).toFixed(4), n: g.length };
    };
    for (const r of rows) r._pt = (events.find((e) => e.date === r.date && e.code === r.code) || {}).pred_type || null;
    const recentD = daily.slice(-20);
    const out = {
        src: "taoge", metric: "IC/IR", generatedAt: new Date().toISOString(),
        formula: "强度=档位(-3..+3, 关键词表见 gen_taoge_ic.mjs GRADES); main=T+1开盘买→T+2开盘卖(可执行, 用户立法 10/5); excess=main−板属指数同窗; IC=Spearman(mid-rank), 日度需≥3事件",
        events: rows.length, days: Object.keys(byDay).length, pendingT2: pending.length, noKline: [...new Set(noKl)].length,
        all: stats(daily.map((d) => d.icExcess)), last20: stats(recentD.map((d) => d.icExcess)),
        allRaw: stats(daily.map((d) => d.icRaw)),
        pooled: { events: pooledGrades.length, icExcess: spearman(pooledGrades, pooledRets) == null ? null : +spearman(pooledGrades, pooledRets).toFixed(4), tauB: tauB(pooledGrades, pooledRets) == null ? null : +tauB(pooledGrades, pooledRets).toFixed(4) },
        byRegime: regimeStats,
        split: { predictive: pooledBy(["predictive"]), factual: pooledBy(["factual"]), mixed: pooledBy(["mixed"]), 未分: pooledBy([null]) },
        degenerateDays, daily,
    };
    fs.mkdirSync(path.dirname(IC_JSON), { recursive: true });
    fs.writeFileSync(IC_JSON, JSON.stringify(out, null, 1));
    console.log(`\n=== 桃哥 IC/IR 记分卡 ===  事件 ${rows.length}(待T+2 ${pending.length}, 缺K线 ${out.noKline}) / ${out.days} 天(有效IC日 ${daily.length}, 退化日 ${degenerateDays})`);
    for (const [tag, s] of [["全量(excess)", out.all], ["近20日(excess)", out.last20], ["全量(raw)", out.allRaw]]) {
        if (s) console.log(`${tag}: IC均值 ${s.icMean} ± ${s.icStd} | IR ${s.ir} | t ${s.tStat} (${s.n}日)`);
    }
    console.log(`pooled(日去均值): IC ${out.pooled.icExcess} | tau-b ${out.pooled.tauB} (${out.pooled.events} 事件)`);
    if (out.split.predictive.n || out.split.factual.n) console.log("分口径 pooled IC: 预测性 " + JSON.stringify(out.split.predictive) + " 事实性 " + JSON.stringify(out.split.factual) + " mixed " + JSON.stringify(out.split.mixed));
    console.log(`regime 分桶: ${Object.entries(regimeStats).map(([k, v]) => `${k}=${v.events}事/IC${v.pooledIC}`).join("  ")}`);
    console.log(`JSON:${JSON.stringify({ out: IC_JSON, events: rows.length })}`);
}

// ---------- main ----------
// ---------- LLM 分离层(10/6 用户拍板"直接上 LLM"): 预测性提及 vs 事实性提及 ----------
// 每事件取 md 里它的提及行上下文, 10 条/批喂 claude -p 二分类; 结论写回 mentions.json 的 pred_type;
// --calc 时分口径重算 IC(全量/仅预测性/仅事实性)——回答"桃哥信号是观点 alpha 还是惨案延续动量"
const CLAUDE_EXE = (process.env.APPDATA || "") + "\\npm\\node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe";
import { spawn } from "node:child_process";
function askClaude(prompt) {
    return new Promise((resolve) => {
        const exe = CLAUDE_EXE; // Windows native exe, spawn 免 shell 转义
        const p = spawn(exe, ["-p", "--output-format", "json", "--permission-mode", "acceptEdits"], { cwd: process.cwd() });
        let out = "";
        p.stdout.on("data", (c) => out += c);
        p.stderr.on("data", () => { });
        p.stdin && p.stdin.end(prompt); // claude -p 从 argv 收 prompt; 超长走 stdin
        const t = setTimeout(() => p.kill(), 600000);
        p.on("close", (code) => { clearTimeout(t); resolve({ code, out }); });
    });
}
async function llmSplit() {
    const { events } = JSON.parse(fs.readFileSync(OUT_EVENTS, "utf8"));
    if (!events?.length) { console.error("mentions.json 空, 先 --extract"); process.exit(1); }
    // 事件 → md 提及行上下文(±1 行)
    const ctxOf = (e) => {
        const [y, m] = e.date.split("-");
        const f = path.join("md", `${y}S${Math.ceil(+m / 3)}`, `${e.date}.md`);
        if (!fs.existsSync(f)) return `(md 缺失)`;
        const text = fs.readFileSync(f, "utf8");
        const hi = text.indexOf(SECTION);
        if (hi === -1) return "(小节缺失)";
        const lines = text.slice(hi).split("\n");
        const i = lines.findIndex((l) => l.includes(`（${e.code}）`));
        return i < 0 ? "(行未定位, 仅档位信息)" : lines.slice(Math.max(0, i - 1), i + 2).join(" ⏎ ").slice(0, 600);
    };
    const BATCH = 10;
    for (let s = 0; s < events.length; s += BATCH) {
        const batch = events.slice(s, s + BATCH).map((e, i) => ({ i, grade: e.grade, ctx: ctxOf(e) }));
        const prompt = `任务: 判断桃哥(A股复盘博主)某日对个股的"提及"属于预测性观点还是事实性复盘。对下面每条:
- grade=当日机械档位(-3..+3, 由关键词表打的)
- ctx=当日 md 复盘小节里该票的提及行摘录(⏎=换行)

分类标准:
- predictive(预测性): 对未来/次日表达操作观点或计划——想买/等回踩买/看多持有/看空回避/准备加仓减仓
- factual(事实性): 只是陈述当日已发生的事——跌停了/炸板了/被带崩/收监管函/涨停(当日既成事实)
- mixed: 两者兼有
只输出严格 JSON 数组(无其他文字): [{"i":0,"type":"predictive|factual|mixed","conf":0.0-1.0,"reason":"≤15字"}]

条目:
${batch.map((b) => `#${b.i} grade=${b.grade}\n${b.ctx}`).join("\n---\n")}`;
        const { code, out } = await askClaude(prompt);
        let tags = null;
        try {
            const j = JSON.parse(out);
            const txt = (j.result || j).toString();
            tags = JSON.parse(txt.slice(txt.indexOf("["), txt.lastIndexOf("]") + 1));
        } catch { }
        if (!Array.isArray(tags)) { console.error(`批 ${s / BATCH} 解析败(code=${code}), 该批跳过`); continue; }
        for (const t of tags) {
            const e = events[s + t.i];
            if (e && t.type) e.pred_type = t.type, e.pred_conf = t.conf, e.pred_reason = t.reason;
        }
        console.log(`llm-split ${s + batch.length}/${events.length}`);
        await sleep(2000);
    }
    fs.writeFileSync(OUT_EVENTS, JSON.stringify({ generatedAt: new Date().toISOString(), events }, null, 1));
    const c = {};
    events.forEach((e) => c[e.pred_type || "未分"] = (c[e.pred_type || "未分"] || 0) + 1);
    console.log("分布:", JSON.stringify(c), `→ ${OUT_EVENTS}`);
}

if (mode === "extract" || mode === "all") {
    const evts = extractAll();
    if (mode === "all") {
        const codes = [...new Set([...evts.map((e) => e.code), IDX.sh, IDX.cyb])];
        await archiveDaily(codes, { dir: KLINE_DIR });
    }
}
if (mode === "kline" && !process.argv.includes("--all")) {
    if (!fs.existsSync(OUT_EVENTS)) { console.error("先 --extract"); process.exit(1); }
    const { events } = JSON.parse(fs.readFileSync(OUT_EVENTS, "utf8"));
    await archiveDaily([...new Set([...events.map((e) => e.code), IDX.sh, IDX.cyb])], { dir: KLINE_DIR });
}
if (mode === "llmsplit") { await llmSplit(); }

if (mode === "calc" || mode === "all") calc();
