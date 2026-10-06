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
import { snapOne, limitOf, isSealed } from "./snapshot.mjs"; // 快照/板限/一字判据统一多源真源(10/5)

const DIR = path.resolve("scripts/dfcf/paper");
const arg = (k) => { const i = process.argv.indexOf("--" + k); return i > -1 ? process.argv[i + 1] : null; };
const SLOT = arg("slot");
if (!SLOT) { console.error("用法: --slot <HHMM> [--date d]"); process.exit(1); }
const date = arg("date") || new Date().toISOString().slice(0, 10);
const OUT = path.join(DIR, "facts", date, SLOT);
fs.mkdirSync(OUT, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sealTag = (s) => (s.pct > 0 ? "🔒一字涨停" : "🔒一字跌停");
async function sealMap(codes) {  // 一字封死检测(10/3 立法 §C.10): 开=高=低=现价且达板限; 多源快照(snapOne 全灭=显式 error 不编数据)
    const map = new Map();
    for (const c of [...new Set(codes)].slice(0, 60)) {
        const s = await snapOne(c);
        if (!s.error && isSealed(s)) map.set(c, sealTag(s));
        await sleep(400);
    }
    return map;
}

// ①六榜(复用 scan.mjs; 非交易时段=最近交易日收盘数据)
let scanMd = "(六榜获取失败)";
try {
    execFileSync("node", ["scripts/scan.mjs", "--out", OUT], { stdio: "pipe", timeout: 120000 });
    scanMd = fs.readFileSync(path.join(OUT, "scan.md"), "utf8");
} catch (e) { console.error(`scan 失败: ${e.message.slice(0, 120)}`); process.exit(2); }

// ①b 一字封死标注(六榜+关注票全扫, 命中行尾打 🔒·禁入候选)
const scanCodes = [...scanMd.matchAll(/\b((?:[0368]\d{5}|920\d{3}|4\d{5}))\b/g)].map((x) => x[1]);
const seals = await sealMap(scanCodes);
function markSealed(text, sealMap2) {
    if (!sealMap2.size) return { text, n: 0 };
    let n = 0;
    const out = text.split("\n").map((l) => {
        for (const [c, tag] of sealMap2) if (l.includes(c)) { n++; return l.replace(/\s*$/, ` ${tag}·禁入候选`); }
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
    const s = await snapOne(code);
    if (s.error) console.error(`快照失败 ${code}: ${s.error}`);
    else snaps.push({ ...s, tag });
    await sleep(500);
}

// ②b 关注票日线锚(A2 接线 10/5): 日线归档存在时补 近120日区间位置%(零 token; 文件缺失静默跳过=未回补)
function dailyAnchor(code) {
    try {
        const k = JSON.parse(fs.readFileSync(path.join("downloads", "quotes", "daily", code + ".json"), "utf8")).klines;
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
    rotationMd = execFileSync("node", ["scripts/rotation.mjs", "--digest"], { stdio: "pipe", timeout: 15000 }).toString("utf8").trim();
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
    if (tg.length) out.push("### 桃哥(主框架: 情绪周期/龙头) ✅已验证规则\n" + tg.join("\n"));
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
    // dir = skill 内 rules.md 所在目录(相对 skills/); 土豆在 persona/buchitudou0/ 子层
    // (10/7 修双 persona 死路径 bug: 原拼 .../persona/buchitudou0/persona/rules.md, ruleHeads 静默空→土豆规则从未进过速览)
    const mentors = [["liunianqing-skill/persona", "刘念青(波段隔夜/板块簇, 日均+1.10%)"], ["lianghuaxiaohao-skill/persona", "量化实验(程序化嫌疑,只看不跟)"],
        ["a658-skill/persona", "A658(ST/次新极端风险, 教训为主)"], ["bianbenling-skill/persona", "边学本领(无止损反面教材)"],
        ["xingjianye-skill/persona", "星见野(港/北交所重仓)"], ["buchitudou0-skill/persona/buchitudou0", "不吃土豆0(转债T+0, A-cb用)"]];
    for (const [dir, label] of mentors) {
        const heads = ruleHeads(`skills/${dir}/rules.md`, /^###\s/).slice(0, 8);
        if (heads.length) out.push("### " + label + "\n" + heads.join("\n"));
    }
    const [y, m] = date.split("-");
    try {
        const text = fs.readFileSync(path.join("md", `${y}S${Math.ceil(+m / 3)}`, `${date}.md`), "utf8");
        for (const [name, tag] of [["卢本圆复盘", "卢本圆(盘中实战, 晨报型)"], ["趋势天哥", "趋势天哥(趋势视角)"]]) {
            const si = text.indexOf("#### " + name);
            if (si === -1) continue;
            const rest = text.slice(si);
            const endM = rest.slice(10).match(/^#{2,4} /m);
            const sec = (endM ? rest.slice(0, 10 + endM.index) : rest).replace(/\s+/g, " ").slice(0, 400);
            out.push("### 当日 " + tag + " 小节速览(截断)\n" + sec);
        }
    } catch { }
    return out.length ? out.join("\n\n") : "(导师速览构建失败, 各源信号本次缺席)";
}

// ---- 拼 facts.md(LLM 读, 目标 2-4k token) ----
const md = [`# facts ${date} ${SLOT}（机械构建零 token; 版本=${date}/${SLOT}）`, "",
    "## 昨日账本状态", digest, "",
    "## 选股层硬过滤(机械规则, 优先级高于一切候选)", seals.size ? "🔒=一字封死(开=高=低=现价且达板限): 当日禁入候选, 无论买卖方向; 已在六榜行尾标注, 04/06 层不得将其列为可交易标的(等炸板分歧也不行——连续一字票进候选=废单制造机)" : "(今日无一字封死票)", "",
    "## 导师信号速览(G-1 聚合: 全员规则标题+记分+当日晨报; 01 需逐源回应, 权重按状态标 ✅>⏳>❌)", mentorDigest(), "",
    "## 池子覆盖率(最近涨停池 vs pools.json 登记簿)", coverage.md, "",
    "## 轮动位置(rotation.mjs 机械判定)", rotationMd, "",
    ...(tmp ? ["## 竞价异动临时池(接力池取数口, 当日有效)", tmp.md, ""] : []),
    "## 新到电报(自上一 slot)", telegraph(), "",
    "## 关注票实时快照", snaps.length ? snaps.map((s) => `- ${s.code} ${s.name}(${s.tag}): ${s.last} (${s.pct > 0 ? "+" : ""}${s.pct}%) 高${s.high} 低${s.low}${isSealed(s) ? " " + sealTag(s) + "·禁入候选" : ""}${dailyAnchor(s.code)}`).join("\n") : "(无持仓无挂单)", "",
    "## 大盘六榜", scanMd].join("\n");
fs.writeFileSync(path.join(OUT, "facts.md"), md);
fs.writeFileSync(path.join(OUT, "facts.json"), JSON.stringify({ date, slot: SLOT, builtAt: new Date().toISOString(), watch: snaps, coverage: coverage.data, tempPool: tmp ? tmp.rows : undefined, chars: md.length }, null, 1));
console.log(`facts ${date}/${SLOT}: ${md.length}字 → ${OUT}/`);
console.log(`JSON:${JSON.stringify({ out: OUT, chars: md.length, watch: snaps.length })}`);
