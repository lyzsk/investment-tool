// facts.mjs — 共享事实包构建器 v1(零 token 机械层, 2026-10-02)
// 定位: LLM 只为判断付费不为看数据付费; A/B/C/D 四方消费同一 facts 版本=归因干净前提
// 用法: node scripts/dfcf/paper/facts.mjs --slot <HHMM> [--date yyyy-MM-dd]
// 产物: facts/<date>/<slot>/{facts.md(2-4k token LLM 读), facts.json(机器用)}
// v1 内容: ①scan.mjs 六榜(大盘) ②持仓+挂单票腾讯快照 ③state_digest(昨日EOD)
// v2(10/2): ④新到电报=直接读当天 md ## 加红电报 节(Java 全天实时写), 抠 [时间戳] 落在
//   上一 slot~本 slot 之间的条目; 首 slot=当日 00:00 起; 今日 md 未建=显式标注不编数据
// v3(10/5): 快照统一走 snapshot.mjs 多源(腾讯→东财→腾讯分时qt→新浪→东财延迟); 关注票加日线锚(A2)
// v4(10/6): ⑤导师信号速览(G-1 聚合层接线)——全员 persona 规则标题+记分卡+当日盘前导师小节,
//   "确保每个 skill 都别空仓": 每个信号源在 01 都有声音, 权重判断留 LLM(按状态标 ✅>⏳>❌)
// v3(10/4): ⑤池子覆盖率(涨停池 vs persona/pools.json, <70% WARN 强制扩池)+⑥竞价异动临时池
//   (slot≥0925, 涨幅榜池外新面孔=接力池取数口)——盲区修复⑤双池制的机械层
// 出口: 0=ok 1=用法错 2=scan 失败
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { snapOne, snapAsof, prevTradeDay, limitOf, isSealed } from "./snapshot.mjs";
import { futuresMd } from "../../quotes/futures.mjs";   // 10/16 用户令: 全市场期货(国内股指/农产品/能化有色黑色+少量外围)进事实包 // 快照/板限/一字判据统一多源真源(10/5)
import * as MENTORS from "../../lib/mentors.mjs";   // 10/17 二B-4: 导师登记表
import { loadAuction, auctionMd } from "../../lib/auction.mjs";   // 10/18: 集合竞价过程(共享实时层, 盯盘同一份)

// 10/10 as-of 回放(9/28-30 补跑语义修复): env PAPER_ROOT=沙盒(books/state_digest/facts 全走沙盒, 不碰实盘),
// PAPER_ASOF=链日 D(须=--date): 全部行情改 D 前一交易日(D1)收盘口径, 零实时源; 导师当日小节改读 D1 md(D 的 md 含盘后复盘=后见之明)
const DIR = process.env.PAPER_ROOT ? path.resolve(process.env.PAPER_ROOT) : path.resolve("scripts/dfcf/paper");
const arg = (k) => { const i = process.argv.indexOf("--" + k); return i > -1 ? process.argv[i + 1] : null; };
const SLOT = arg("slot");
if (!SLOT) { console.error("用法: --slot <HHMM> [--date d]"); process.exit(1); }
const date = arg("date") || new Date().toLocaleDateString("sv-SE");
const ASOF = process.env.PAPER_ASOF || null;
if (ASOF && (ASOF !== date || !process.env.PAPER_ROOT)) { console.error(`as-of 须 PAPER_ASOF=--date(${ASOF} vs ${date}) 且设 PAPER_ROOT 沙盒`); process.exit(1); }
const D1 = ASOF ? await prevTradeDay(ASOF) : null;
const snapAt = (c) => (ASOF ? snapAsof(c, ASOF) : snapOne(c));
const OUT = path.join(DIR, "facts", date, SLOT);
fs.mkdirSync(OUT, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sealTag = (s) => (s.pct > 0 ? "🔒一字涨停" : "🔒一字跌停");
async function sealMap(codes) {  // 一字封死检测(10/3 立法 §C.10): 开=高=低=现价且达板限; 多源快照(snapOne 全灭=显式 error 不编数据)
    const map = new Map();
    for (const c of [...new Set(codes)].slice(0, 60)) {
        const s = await snapAt(c);
        if (!s.error && isSealed(s)) map.set(c, sealTag(s));
        await sleep(ASOF ? 50 : 400);
    }
    return map;
}

// ①六榜(复用 scan.mjs; 非交易时段=最近交易日收盘数据)
let scanMd = "(六榜获取失败)";
try {
    execFileSync("node", ["scripts/scan.mjs", "--out", OUT, ...(ASOF ? ["--asof", D1.replaceAll("-", "")] : [])], { stdio: "pipe", timeout: 120000, windowsHide: true });
    scanMd = fs.readFileSync(path.join(OUT, "scan.md"), "utf8");
} catch (e) { console.error(`scan 失败: ${e.message.slice(0, 120)}`); process.exit(2); }

// ①b 一字封死标注(六榜+关注票全扫, 命中行尾打 🔒·封死中(10/16 起不一律禁入, 排板开板才成交))
const scanCodes = [...scanMd.matchAll(/\b((?:[0368]\d{5}|920\d{3}|4\d{5}))\b/g)].map((x) => x[1]);
const seals = await sealMap(scanCodes);
function markSealed(text, sealMap2) {
    if (!sealMap2.size) return { text, n: 0 };
    let n = 0;
    const out = text.split("\n").map((l) => {
        for (const [c, tag] of sealMap2) if (l.includes(c)) { n++; return l.replace(/\s*$/, ` ${tag}·封死中(排板只在开板时成交)`); }
        return l;
    }).join("\n");
    return { text: out, n };
}
const marked = markSealed(scanMd, seals);
scanMd = marked.text;
if (marked.n) console.log(`一字封死标注: ${marked.n} 行 (${[...seals.entries()].map(([c, t]) => c + t).join(", ")})`);

// ②持仓+挂单票快照(从6账本扫)
const watch = new Map();
for (const f of fs.existsSync(path.join(DIR, "books")) ? fs.readdirSync(path.join(DIR, "books")) : []) {
    const b = JSON.parse(fs.readFileSync(path.join(DIR, "books", f), "utf8"));
    for (const c of Object.keys(b.positions || {})) watch.set(c, "持仓");
    for (const o of (b.orders || []).filter((o) => o.status === "open")) watch.set(o.code, "挂单");
}
const snaps = [];
for (const [code, tag] of watch) {
    const s = await snapAt(code);
    if (s.error) console.error(`快照失败 ${code}: ${s.error}`);
    else snaps.push({ ...s, tag });
    await sleep(ASOF ? 50 : 500);
}

// ②b 关注票日线锚(A2 接线 10/5): 日线归档存在时补 近120日区间位置%(零 token; 文件缺失静默跳过=未回补)
function dailyAnchor(code) {
    try {
        const k = JSON.parse(fs.readFileSync(path.join("downloads", "quotes", "daily", code + ".json"), "utf8")).klines
            .filter((x) => !ASOF || x.d < ASOF);  // as-of: 只用链日前的K线
        if (!k?.length) return "";
        const last = k[k.length - 1], win = k.slice(-120);
        const hi = Math.max(...win.map((x) => x.h)), lo = Math.min(...win.map((x) => x.l));
        return hi > lo ? ` 近120日${lo.toFixed(2)}~${hi.toFixed(2)}(${((last.c - lo) / (hi - lo) * 100).toFixed(0)}%)` : "";
    } catch { return ""; }
}
// ①c 池子登记簿: 覆盖率告警 + 竞价异动临时池(10/4 立法, 盲区修复⑤)
// 池子偏见=最大盲区根因(固态有 9/5 预建池被选中/医药没池连方向组都没建); pools.json=低吸池(B48)唯一机器真源
// 覆盖率: 最近涨停池票名在池率<70% → WARN 强制扩池; 临时池: slot≥0925 涨幅榜池外新面孔(打破 T-1 池子时间差, 接力池取数口)
const POOLS_FILE = path.resolve("skills/taoge-skill/persona/pools.json");
const pools = (() => {
    try {
        const p = JSON.parse(fs.readFileSync(POOLS_FILE, "utf8"));
        const names = new Set(), codes = new Set();
        for (const d of Object.values(p.directions || {})) for (const s of d.stocks || []) { names.add(s.name); codes.add(s.code); }
        return { names, codes };
    } catch { return null; }
})();
function poolCoverage() {  // → {md, data|null}
    if (!pools) return { md: "⚠️ pools.json 缺失/解析失败——池子无登记簿, 覆盖率无法计算, 本身即告警, 立即修复", data: null };
    const sec = (scanMd.match(/## 连板梯队\n([\s\S]*?)(?=\n## |\n*$)/) || [])[1] || "";
    if (!sec || /获取失败/.test(sec)) return { md: "(连板梯队缺失, 无法计算)", data: null };
    const names = [...new Set(sec.split("\n").filter((l) => /连板\[/.test(l))
        .flatMap((l) => [...l.matchAll(/([一-龥A-Za-z0-9*]+)\(/g)].map((x) => x[1]).filter((n) => n.length >= 2)))];
    if (!names.length) return { md: "(涨停池无票)", data: { total: 0, inPool: 0, rate: 1 } };
    const inn = names.filter((n) => pools.names.has(n)), out = names.filter((n) => !pools.names.has(n));
    const rate = inn.length / names.length;
    const warn = rate < 0.7 ? ` ⚠️WARN: 在池率 ${(rate * 100).toFixed(0)}% < 70%——池子太窄, 强制扩池(04 提案+用户确认后改 pools.json)` : "";
    return {
        md: [`涨停池 ${names.length} 只, 在池 ${inn.length} 只 (${(rate * 100).toFixed(0)}%)${warn}`,
            `在池: ${inn.join("、") || "无"}`, `池外: ${out.join("、") || "无"}`].join("\n"),
        data: { total: names.length, inPool: inn.length, rate: +rate.toFixed(3) },
    };
}
function tempPool() {  // slot≥0925 才存在(竞价后) → {md, rows} | null
    if (SLOT < "0925") return null;
    if (!pools) return { md: "⚠️ pools.json 缺失——无法区分池内外, 临时池停用", rows: [] };
    const sec = (scanMd.match(/## 涨跌幅榜\n([\s\S]*?)(?=\n## |\n*$)/) || [])[1] || "";
    if (!sec || /获取失败/.test(sec)) return { md: "(涨幅榜缺失, 临时池空——接力池今日无取数口)", rows: [] };
    const rows = sec.split("\n").filter((l) => !l.includes("🔒"))
        .map((l) => l.match(/^\s*\d+\.\s*(.+?)\((?:sh|sz|bj)?(\d{6})\)\s*([+-]?[\d.]+)%/)).filter(Boolean)
        .map((x) => ({ name: x[1], code: x[2], pct: +x[3] }))
        .filter((r) => !pools.codes.has(r.code) && !watch.has(r.code)).slice(0, 10);
    const md = rows.length
        ? rows.map((r) => `- ${r.code} ${r.name} ${r.pct > 0 ? "+" : ""}${r.pct}%`).join("\n")
            + "\n> 临时池=竞价/早盘异动票当日临时入池(打破 T-1 池子时间差, 接力池取数口); 日内级不落 pools.json, 隔夜归 04 提案+用户确认"
        : "(涨幅榜 Top 内无池外新面孔)";
    return { md, rows };
}
const coverage = poolCoverage();
const tmp = tempPool();

// ①d 轮动位置(rotation.mjs --digest, 纯本地零网络; 10/4 盲区修复⑥: "科技回避"粗话消失=资金从哪向哪迁移+证据锚)
let rotationMd = "(rotation 历史未建: node scripts/rotation.mjs --backfill)";
try {
    rotationMd = execFileSync("node", ["scripts/rotation.mjs", "--digest", ...(ASOF ? ["--asof", ASOF] : [])], { stdio: "pipe", timeout: 15000, windowsHide: true }).toString("utf8").trim();
} catch (e) { rotationMd = `(轮动位置获取失败: ${String(e.message).slice(0, 120)})`; }

// ③state_digest
const digestFile = path.join(DIR, "state_digest.md");
const digest = fs.existsSync(digestFile) ? fs.readFileSync(digestFile, "utf8") : "(无 state_digest=首日前)";

// ④新到电报(读当天 md ## 加红电报 节, 抠上一 slot 之后的条目)
function telegraph() {
    const [y, m] = date.split("-");
    const mdFile = path.join("md", `${y}S${Math.ceil(+m / 3)}`, `${date}.md`);
    if (!fs.existsSync(mdFile)) return "(今日 md 未建, 无电报)";
    const text = fs.readFileSync(mdFile, "utf8");
    const si = text.indexOf("## 加红电报");
    if (si === -1) return "(md 无加红电报节)";
    const end = text.indexOf("\n## ", si + 3);
    const sec = text.slice(si, end === -1 ? undefined : end);
    const dayDir = path.join(DIR, "facts", date);
    const prev = fs.existsSync(dayDir) ? fs.readdirSync(dayDir).filter((d) => /^\d{4}$/.test(d) && d < SLOT).sort().pop() : null;
    const after = prev ? `${date} ${prev.slice(0, 2)}:${prev.slice(2)}:00` : `${date} 00:00:00`;
    const items = [...sec.matchAll(/^- \[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] (\[[\s\S]*?)(?=\n- \[|\n## |$)/gm)]
        .filter((x) => x[1] > after && x[1] <= `${date} ${SLOT.slice(0, 2)}:${SLOT.slice(2)}:59`)
        .map((x) => `- [${x[1].slice(11, 16)}] ${x[2].replace(/\n  !\[.*$/gm, "").slice(0, 300)}`);
    return items.length ? items.join("\n") : `(自${after.slice(11)}无新电报)`;
}

// ⑤导师信号速览(G-1 聚合层机械接线, 10/6): 各 skill persona 规则标题+记分卡+当日盘前导师小节
function ruleHeads(file, re) {
    try {
        return fs.readFileSync(file, "utf8").split("\n").filter((l) => re.test(l))
            .map((l) => l.replace(/^#+\s*/, "").replace(/^[-*]\s*/, "").slice(0, 90));
    } catch { return []; }
}
function mentorDigest() {
    const out = [];
    const tg = ruleHeads("skills/taoge-skill/persona/rules_index.md", /^- [A-Z]\d+ ✅/).slice(0, 25);
    if (tg.length) out.push("### 桃哥(情绪周期/龙头) ✅已验证规则\n" + tg.join("\n"));
    try {
        const ic = JSON.parse(fs.readFileSync("skills/taoge-skill/persona/ic.json", "utf8"));
        out.push(`- 桃哥提及 IC 记分(10/6): 预测性 ${JSON.stringify(ic.split?.predictive)} / 事实性 ${JSON.stringify(ic.split?.factual)}——预测性观点暂不给正权重, 事实性提及=动量参考`);
    } catch { }
    try {
        const fg = fs.readFileSync("skills/fage-skill/persona/rules.md", "utf8");
        const seg = fg.slice(fg.indexOf("## 强项"), fg.indexOf("## 框架指纹"));
        const sc = JSON.parse(fs.readFileSync("skills/fage-skill/persona/score.json", "utf8"));
        out.push(`### 发哥(刹车: 回避信号一票否决级) 近20日纯命中 ${sc.last20.pureHitRate}\n` +
            seg.replace(/^## [^\n]*\n+/, "").trim().split("\n").filter((l) => /^\d+\./.test(l.trim())).join("\n"));
    } catch { }
    // 10/14 F3 修: 原表只接 6 位(大兴/高概率/宣秋/ST之狼/冲5000w 缺席, 卢本圆/天哥只读当日 md 小节), 且 /^###\s/ 抓进分区标题
    // (量化"一、出场区"/边学"`[可跟]` 区")与模板占位(土豆"R<n>")。现: 全员统一一节, 每节=规则行+(B站导师)最近 md 小节;
    // 节标题须含 run_chain.py MENTOR_HEAD 关键词(各链 01 按它切本导师小节, 同导师只能一个 ### 块)
    // 10/17 二B-4: 名单读导师登记表(scripts/lib/mentors.mjs): [skill, 节标题=short, UP 的 md 小节名=name]; 桃哥另有专节(上方)不在此列, 对照组无导师
    // (顺序=登记表序: tzzb 在前、B站 UP 在后; 与 10/17 前写死表相比土豆从第 6 节移到第 1 节、天哥/卢本圆互换, 内容逐节不变)
    const mentors = [...MENTORS.all().filter((e) => e.type === "tzzb"), ...MENTORS.all().filter((e) => e.type === "UP" && e.id !== "taoge")]
        .map((e) => (e.type === "UP" ? [e.id, cardTitle(e), e.name] : [e.id, cardTitle(e)]));
    const mdDate = D1 || date;  // as-of: D 的 md 复盘节=D 盘后才写入(后见之明), 改读 D1 的(D 盘前已存在)
    for (const [skill, label, mdName] of mentors) {
        const lines = ruleLines(skill, !!mdName);
        const s = mdName ? latestMdSection(mdName, mdDate) : null;
        if (s) lines.push(`- ${s.day === date ? "当日" : s.day} md 小节速览(截断): ${s.sec}`);
        out.push("### " + label + "\n" + (lines.length ? lines.join("\n") : `(skills/${skill}-skill/persona/rules.md 无可读规则行)`));
    }
    return out.length ? out.join("\n\n") : "(导师速览构建失败, 各源信号本次缺席)";
}
// 规则行: tzzb 导师只认编号标题(### / #### Rn), B站导师只认 "- **L1 名**" 列表(tzzb 正文里 "- **W1 注**/**H1 口径警示**" 是注释非规则), 跳过停用/打脸/证伪条;
// 排序 [可跟]/md验证 > [教训] > 其余(原文序稳定)
// as-of: 行内任一日期 ≥ 链日=规则状态含后见之明, 整行剔除并计数。只防得住"状态日期", 防不住"规则出生日"(出生日不在标题行,
// 如 liuyiqing R6 生于 10/11)——这一口子同既有 tzzb 速览, 仍须 06/盲审按 rules_index 披露
// 10/18 用户定: 导师速览节标题改成"名字(机械统计标签; 业绩风险; 截至 MM-DD 近 N 日)"——scripts/tzzb/mentor_cards.py 每天按 D 之前的数据现算,
//   不再用登记表里写死的 short(带"日均+1.10%"等过期数字和人写的评价)。名字在最前, 驱动器按名字切小节不受影响; 名片算不出 = 退回登记表 short
let _CARDS = null;
function cardTitle(e) {
    if (_CARDS === null) {
        _CARDS = {};
        const d = ASOF || date, f = path.join("scripts", "tzzb", "mentor_cards", `${d}.json`);
        try {
            if (!fs.existsSync(f)) {
                execFileSync(path.join("scripts", "venv", "Scripts", "python.exe"), ["-X", "utf8", "scripts/tzzb/mentor_cards.py", "--date", d],
                    { stdio: "pipe", timeout: 120000, windowsHide: true });
            }
            for (const [k, v] of Object.entries(JSON.parse(fs.readFileSync(f, "utf8")).cards || {})) _CARDS[k] = v.title;
        } catch (err) {
            console.error(`导师名片不可用, 节标题退回登记表 short: ${String(err.message || err).slice(0, 120)}`);
        }
    }
    return _CARDS[e.id] || e.short;
}
const RULE_HEAD = /^#{3,4}\s+R\d+\s/, RULE_BULLET = /^- \*\*[A-Z]\d+\s/;
const RULE_DEAD = /停用|~~|\|已打脸\]|\[已证伪/;
function ruleLines(skill, bullet = false, cap = 8) {
    let text;
    try { text = fs.readFileSync(`skills/${skill}-skill/persona/rules.md`, "utf8"); } catch { return []; }
    const re = bullet ? RULE_BULLET : RULE_HEAD;
    let rows = text.split("\n").filter((l) => re.test(l) && !RULE_DEAD.test(l))
        .map((l) => l.replace(/^#+\s*|^- /, "").replace(/\*\*:?|`/g, "").replace(/\s*(（[^）]*）|【[^】]*】)\s*$/, "").trim());
    let leak = 0;
    if (ASOF) rows = rows.filter((l) => !(l.match(/20\d\d-\d\d-\d\d/g) || []).some((d) => d >= ASOF) || !++leak);
    const rank = (l) => (/\[可跟|md 验证|✅/.test(l) ? 0 : /\[教训/.test(l) ? 1 : 2);
    rows = rows.map((l, i) => [rank(l), i, l]).sort((a, b) => a[0] - b[0] || a[1] - b[1]).map((x) => x[2]);
    const out = rows.slice(0, cap).map((l) => l.slice(0, 90));
    if (rows.length > cap) out.push(`(另 ${rows.length - cap} 条未列, 见 skills/${skill}-skill/persona/rules.md)`);
    if (leak) out.push(`(as-of: ${leak} 条规则状态日期 ≥ ${ASOF}, 已剔除)`);
    return out;
}
// B站导师 md 小节: 天哥 17:45 盘后发稿、卢本圆 08:08 晨报, 均晚于 07:50 开跑 → 当日小节常空; 取 ≤upto 最近 5 份 md 里首个非空小节并标日期
function latestMdSection(name, upto) {
    let files = [];
    try {
        for (const q of fs.readdirSync("md").filter((d) => /^\d{4}S\d$/.test(d)))
            for (const f of fs.readdirSync(path.join("md", q))) if (/^\d{4}-\d\d-\d\d\.md$/.test(f) && f.slice(0, 10) <= upto) files.push(path.join("md", q, f));
    } catch { return null; }
    files = files.sort((a, b) => path.basename(b).localeCompare(path.basename(a))).slice(0, 5);
    for (const f of files) {
        const text = fs.readFileSync(f, "utf8");
        const si = text.indexOf("#### " + name);
        if (si === -1) continue;
        const rest = text.slice(si);
        const endM = rest.slice(10).match(/^#{2,4} /m);
        const sec = (endM ? rest.slice(0, 10 + endM.index) : rest).replace(/^#### [^\n]*\n/, "").replace(/\s+/g, " ").trim();
        if (sec.length >= 20) return { day: path.basename(f, ".md"), sec: sec.slice(0, 400) };
    }
    return null;
}

// 10/13 用户令(0915 改 07:50 开跑的配套): 当日财联社早报要点 + 发哥盘前推演要点进事实包——此前事实包完全不读当日这两样,
// 只读发哥历史规则标题。只读盘前蒸馏产物 spec.md(证据层, 零请求零 token); 两者都在 09:15 前发布, as-of 回放同样可用
function premarket() {
    const part = (label, f, tag) => {
        try {
            const rows = fs.readFileSync(f, "utf8").split("\n").map((l) => l.trim()).filter((l) => l.startsWith(tag));
            return rows.length ? [`### ${label}`, ...rows] : [`### ${label}`, "(当日 spec.md 无要点行)"];
        } catch { return [`### ${label}`, "(今日尚未挂载: 链接未贴或盘前蒸馏未做, 本次缺席)"]; }
    };
    return [...part("财联社早报要点(宏观/行业/公司/环球/机会)", path.join("downloads", "cls_zaobao", date, "spec.md"), "【早报要点】"), "",
        ...part("红旗大街发哥 盘前推演要点(刹车级信号源)", path.join("downloads", "wechat", "fage", date, "spec.md"), "【推演要点】")].join("\n");
}

// 10/14 龙虎榜消费①(零 token): 读 downloads/lhb/<最近一个 < 链日 的交易日>/ 的落盘 json(fetch_lhb.mjs 每晚采, 盘后 17 点前后出, D 盘前必已存在→as-of 无后见之明)
// 只摘: 一行概况 + 关注票(持仓/挂单)若上榜 + 净买前 6 / 净卖前 4, 每票一行(机构净额/游资名); 目标 ≤1.5k 字
function lhbDigest() {
    const root = path.join("downloads", "lhb");
    if (!fs.existsSync(root)) return "(龙虎榜未采集)";
    const day = fs.readdirSync(root).filter((d) => /^\d{4}\.\d{2}\.\d{2}$/.test(d) && d.replace(/\./g, "-") < date).sort().pop();
    if (!day) return "(无前一交易日龙虎榜)";
    let list;
    try { list = JSON.parse(fs.readFileSync(path.join(root, day, "list.json"), "utf8")).rows || []; } catch { return `(${day} 龙虎榜 list.json 读失败)`; }
    let yz = {};
    try { yz = JSON.parse(fs.readFileSync(path.join("scripts", "lhb", "youzi.json"), "utf8")).map || {}; } catch { /* 无游资表=不标 */ }
    const amt = (x) => { const a = Math.abs(x); const s = x < 0 ? "-" : "+"; return a >= 1e8 ? `${s}${(a / 1e8).toFixed(2)}亿` : `${s}${Math.round(a / 1e4)}万`; };
    const short = (n) => n.replace(/股份有限公司|有限责任公司|有限公司/g, "").replace(/证券营业部|营业部|分公司/g, "").replace(/证券/, " ").replace(/\s+/g, " ").trim();
    const by = new Map();
    for (const r of list) {   // 一票多上榜原因=多行, 合并(金额取最大那行, 原因拼接)
        const o = by.get(r.SECURITY_CODE);
        if (!o) by.set(r.SECURITY_CODE, { ...r, reasons: [r.EXPLANATION] });
        else { o.reasons.push(r.EXPLANATION); if (Math.abs(r.BILLBOARD_NET_AMT) > Math.abs(o.BILLBOARD_NET_AMT)) Object.assign(o, r, { reasons: o.reasons }); }
    }
    const seats = (code) => {
        try {
            const d = JSON.parse(fs.readFileSync(path.join(root, day, `detail_${code}.json`), "utf8"));
            const all = new Map();
            for (const s of [...(d.buy || []), ...(d.sell || [])]) all.set(s.OPERATEDEPT_NAME + "|" + (s.OPERATEDEPT_CODE || ""), s);
            let inst = 0, ni = 0; const hot = new Map();   // 同名游资(如拉萨天团多席)合并净额
            for (const s of all.values()) {
                if (s.OPERATEDEPT_NAME === "机构专用") { inst += s.NET || 0; ni++; continue; }
                const k = short(s.OPERATEDEPT_NAME), y = yz[k] || Object.entries(yz).find(([kk]) => k.includes(kk))?.[1];
                if (y) { let nm = typeof y === "string" ? y : y.name || k; if (nm === "拉萨天团") nm = `${k.replace(/^东方财富 /, "")}证券营业部`; hot.set(nm, (hot.get(nm) || 0) + (s.NET || 0)); }   // 10/14: 拉萨标营业部
            }
            return { inst, ni, hot: [...hot].sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).map(([n, v]) => `${n}${amt(v)}`) };
        } catch { return null; }
    };
    const rows = [...by.values()];
    const watch = new Set(snaps.map((s) => s.code));
    const sorted = [...rows].sort((a, b) => b.BILLBOARD_NET_AMT - a.BILLBOARD_NET_AMT);
    const pick = [...rows.filter((r) => watch.has(r.SECURITY_CODE)), ...sorted.slice(0, 6), ...sorted.slice(-4).reverse()];
    const seen = new Set(), L = [];
    const insts = rows.map((r) => ({ r, s: seats(r.SECURITY_CODE) })).filter((x) => x.s && x.s.ni);
    insts.sort((a, b) => b.s.inst - a.s.inst);
    const top = (xs) => xs.map((x) => `${x.r.SECURITY_NAME_ABBR}${amt(x.s.inst)}`).join("、") || "无";
    L.push(`${day.replace(/\./g, "-")} 上榜 ${rows.length} 只; 机构净买前三: ${top(insts.filter((x) => x.s.inst > 0).slice(0, 3))}; 机构净卖前三: ${top(insts.filter((x) => x.s.inst < 0).slice(-3).reverse())}`);
    for (const r of pick) {
        if (seen.has(r.SECURITY_CODE)) continue;
        seen.add(r.SECURITY_CODE);
        const s = seats(r.SECURITY_CODE);
        const tag = watch.has(r.SECURITY_CODE) ? "【关注票】" : "";
        L.push(`- ${tag}${r.SECURITY_NAME_ABBR} ${r.SECURITY_CODE} ${r.CHANGE_RATE > 0 ? "+" : ""}${r.CHANGE_RATE?.toFixed(1)}% | ${[...new Set(r.reasons.map((x) => x.replace(/^无价格涨跌幅限制的证券.*/, "无涨跌幅限制").replace(/^有价格涨跌幅限制的/, "").replace(/的前[\d五三]+只证券|的证券$/g, "").replace(/^日收盘价格/, "日")))].join("/").slice(0, 40)} | 净额${amt(r.BILLBOARD_NET_AMT)}(占成交${r.DEAL_NET_RATIO?.toFixed(1)}%)`
            + (s ? ` | 机构${s.ni ? amt(s.inst) + `(${s.ni}席)` : "无"}${s.hot.length ? " | 游资 " + s.hot.slice(0, 3).join("、") : ""}` : ""));
    }
    L.push(`(全量: downloads/lhb/${day}/ 与当日 md「### 龙虎榜」节; 龙虎榜=盘后公布的上榜席位, 只说明昨日资金结构, 不预示今日涨跌)`);
    return L.join("\n");
}

// ---- 10/18 晚(用户定"周三接, 先备好"): 关注票三态 / 箱体 / 均线 / 止损候选, 开关 CHAIN_REGIME_FACTS(chain_flags.txt; 环境变量优先), 关=本节不出现 ----
function chainFlag(name) {
    if (process.env[name] === "0" || process.env[name] === "1") return process.env[name] === "1";
    try {
        for (const line of fs.readFileSync(path.resolve("scripts/claude_profile/chain_flags.txt"), "utf8").split("\n")) {
            const [k, v] = line.split("#")[0].split("=");
            if (k && k.trim() === name) return (v || "").trim() === "1";
        }
    } catch { /* 文件缺 = 关 */ }
    return false;
}
function regimeMd(codes) {
    const root = path.resolve("downloads/market");
    let dir = null;
    try { dir = fs.readdirSync(root).filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d) && d < date && fs.existsSync(path.join(root, d, "indicators.jsonl"))).sort().pop(); } catch { /* 无 */ }
    if (!dir) return "(indicators.jsonl 未生成, 不可得)";
    const want = new Set(codes), L = [];
    for (const l of fs.readFileSync(path.join(root, dir, "indicators.jsonl"), "utf8").split("\n")) {
        if (!l) continue;
        const x = JSON.parse(l);
        if (!want.has(x.symbol.slice(2))) continue;
        const st = Object.entries(x.stops || {}).map(([k, v]) => `${k} ${v}`).join("/") || "—";
        L.push(`- ${x.symbol.slice(2)}: **${x.regime}**(ER20 ${x.er20}) | 箱体 ${x.box_lo ?? "?"}~${x.box_hi ?? "?"} 位置 ${x.box_pos ?? "?"} | EMA20 ${x.ema20} / EMA60 ${x.ema60} / EMA144 ${x.ema144}(${(x.vs_ema144 * 100).toFixed(1)}%) / EMA169 ${x.ema169} | MA120 ${x.ma120 ?? "?"} / MA144 ${x.ma144 ?? "?"} | 止损候选 ${st}`);
    }
    return [`(${dir} 收盘口径; 三态 = 上涨趋势 / 下跌趋势 / 交易区间 / 无规则, 定义见 scripts/quotes/indicators_db.py; 全市场自检: 趋势标签本身不是优势, 优势在选股——只当情景参考, 打法按本导师在该状态下的历史期望(导师指纹「三态」块))`, ...(L.length ? L : ["(关注票都不在快照里)"])].join("\n");
}

// ---- 拼 facts.md(LLM 读, 目标 2-4k token) ----
// 10/12 用户令: 隔夜外围进事实包——只读 collect_global.py 的落盘(downloads/market/<北京日期>/global_kline.jsonl, 每日 07:15 采), 零额外请求;
// 当日未采到=取最近一份并标采集日; as-of 回放=不可得(该文件只有实时口径, 禁混入)
function overseas() {
    if (ASOF) return "(as-of 回放: 外围隔夜数据无历史快照, 不可得)";
    const root = path.resolve("downloads/market");
    let dir = null;
    try { dir = fs.readdirSync(root).filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d) && d <= date && fs.existsSync(path.join(root, d, "global_kline.jsonl"))).sort().pop(); } catch { }
    if (!dir) return "(外围数据未采集: downloads/market/*/global_kline.jsonl 不存在)";
    const rows = fs.readFileSync(path.join(root, dir, "global_kline.jsonl"), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
    const name = {};
    try { for (const l of fs.readFileSync(path.join(root, dir, "global_security.jsonl"), "utf8").split("\n").filter(Boolean)) { const s = JSON.parse(l); name[s.symbol] = s.name; } } catch { }
    const fmt = (r) => { const pct = r.preClose ? ((r.close / r.preClose - 1) * 100).toFixed(2) : "?"; return `${name[r.symbol] || r.symbol} ${r.close}(${pct > 0 ? "+" : ""}${pct}%)`; };
    const groups = [["美股", /^us\.(NDX|IXIC|SPX|DJI)$/], ["中概", /^us\.(HXC|KWEB)$/], ["港股", /^hk\./], ["日英", /^(jp\.|gl\.UKX)/], ["期货", /^gl\.(A50|ES|NQ)$/], ["商品汇率", /^gl\.(GC|CL|USDCNH)$/]];
    const days = [...new Set(rows.map((r) => r.tradeDate))].sort();
    return [`(采集日 ${dir}${dir !== date ? " ⚠️非当日, 可能缺最新隔夜" : ""}; 各品种=当地最近交易日 ${days.join("/")} 收盘, 期货汇率=北京时间凌晨收盘口径)`,
        ...groups.map(([g, re]) => { const rs = rows.filter((r) => re.test(r.symbol)); return rs.length ? `- ${g}: ${rs.map(fmt).join(" / ")}` : null; }).filter(Boolean)].join("\n");
}

const md = [`# facts ${date} ${SLOT}（机械构建零 token; 版本=${date}/${SLOT}; 构建于 ${new Date().toTimeString().slice(0, 5)}）`, "",
    // 10/15: 0915 链 08:15 开跑, 构建之后才挂进 md 的资讯(晚贴的发哥/重抓的早报)这里看不到——写明构建时刻, 01 以 md 当日小节为准
    `> 本包构建于 ${new Date().toTimeString().slice(0, 5)}; 之后才挂进当日 md 的资讯(如晚贴的发哥推演)不在本包, 需要时读当日 md 对应小节`, "",
    ...(ASOF ? [`> ⏪ as-of 回放构建(${new Date().toISOString().slice(0, 16)}Z): 行情=${D1} 收盘口径(日线归档+东财历史涨跌停池), 账本=沙盒; 次新/板块榜无历史源; 涨跌幅榜=归档样本近似`, ""] : []),
    "## 昨日账本状态", digest, "",
    "## 选股层硬过滤(机械规则, 优先级高于一切候选)", seals.size ? "🔒=一字封死(开=高=低=现价且达板限): 现在买不到。10/16 起不再一律禁入——本导师有排板/打板/炸板回封习惯的, 可以在涨停价挂单排队, 但撮合规则=封板时不成交、开板(现价低于涨停价)才成交, 收盘仍封=作废; 没有这类习惯的导师照旧不碰" : "(今日无一字封死票)", "",
    "## 导师信号速览(G-1 聚合: 全员规则标题+记分+当日晨报; 10/16 起各链只需回应本导师小节, 其余仅供参考; 权重按状态标 ✅>⏳>❌)", mentorDigest(), "",
    "## 池子覆盖率(最近涨停池 vs pools.json 登记簿)", coverage.md, "",
    "## 轮动位置(rotation.mjs 机械判定)", rotationMd, "",
    ...(tmp ? ["## 竞价异动临时池(接力池取数口, 当日有效)", tmp.md, ""] : []),
    // 10/18 用户定: 集合竞价过程进所有链(0927 子链=按竞价结果修正 0915 的单); 只给 09:25~09:59 的时段, 之后连续竞价已覆盖; as-of 读当日存档(09:25:40 前的数据, 无后见)
    ...(SLOT >= "0925" && SLOT < "1000" ? ["## 集合竞价(09:15~09:25, 关注票=各链持仓+挂单)", auctionMd(loadAuction(ASOF || date), [...watch.keys()]), ""] : []),
    "## 隔夜外围(美股/中概/港股/日英/A50·美股期货/金油/离岸人民币)", overseas(), "",
    "## 期货(国内主力+外围期货, 现场拉取)", ASOF ? "(as-of 回放: 无期货历史快照, 不可得)" : await futuresMd(), "",
    "## 今日盘前资讯(当日早报+发哥推演, 盘前蒸馏要点原文)", premarket(), "",
    "## 昨日龙虎榜(机械摘录: 概况+关注票+净买/净卖前列)", lhbDigest(), "",
    "## 新到电报(自上一 slot)", telegraph(), "",
    // 10/17 健壮性 H3: 盘前(行情停在上一交易日的盘, snapshot stale=true)标清口径: 价=该日收盘=今日前收, 涨跌幅/高低=该日, 不是今天的盘
    "## 关注票实时快照" + (snaps.some((s) => s.stale) ? `（盘前: 行情停在 ${[...new Set(snaps.filter((s) => s.stale).map((s) => s.qtDate))].join("/")} 收盘——价格=该日收盘=今日前收, 涨跌幅/高低=该日, 今天尚未开盘）` : ""),
    snaps.length ? snaps.map((s) => `- ${s.code} ${s.name}(${s.tag}): ${s.last}${s.stale ? "(=今日前收)" : ""} (${s.stale ? "该日" : ""}${s.pct > 0 ? "+" : ""}${s.pct}%) 高${s.high} 低${s.low}${isSealed(s) ? " " + sealTag(s) + "·封死中(排板只在开板时成交)" : ""}${dailyAnchor(s.code)}`).join("\n") : "(无持仓无挂单)", "",
    ...(chainFlag("CHAIN_REGIME_FACTS") ? ["", "## 关注票状态(三态 / 箱体 / 均线 / 止损候选)", regimeMd(snaps.map((s) => s.code)), ""] : []),
    "## 大盘六榜", scanMd].join("\n");
fs.writeFileSync(path.join(OUT, "facts.md"), md);
fs.writeFileSync(path.join(OUT, "facts.json"), JSON.stringify({ date, slot: SLOT, builtAt: new Date().toISOString(), watch: snaps, coverage: coverage.data, tempPool: tmp ? tmp.rows : undefined, chars: md.length }, null, 1));
console.log(`facts ${date}/${SLOT}: ${md.length}字 → ${OUT}/`);
console.log(`JSON:${JSON.stringify({ out: OUT, chars: md.length, watch: snaps.length })}`);
