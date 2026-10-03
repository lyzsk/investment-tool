// facts.mjs — 共享事实包构建器 v1(零 token 机械层, 2026-10-02)
// 定位: LLM 只为判断付费不为看数据付费; A/B/C/D 四方消费同一 facts 版本=归因干净前提
// 用法: node scripts/dfcf/paper/facts.mjs --slot 0915 [--date yyyy-MM-dd]
// 产物: facts/<date>/<slot>/{facts.md(2-4k token LLM 读), facts.json(机器用)}
// v1 内容: ①scan.mjs 六榜(大盘) ②持仓+挂单票腾讯快照 ③state_digest(昨日EOD)
// v2(10/2): ④新到电报=直接读当天 md ## 加红电报 节(Java 全天实时写), 抠 [时间戳] 落在
//   上一 slot~本 slot 之间的条目; 首 slot=当日 00:00 起; 今日 md 未建=显式标注不编数据
// 出口: 0=ok 1=用法错 2=scan 失败
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

const DIR = path.resolve("scripts/dfcf/paper");
const arg = (k) => { const i = process.argv.indexOf("--" + k); return i > -1 ? process.argv[i + 1] : null; };
const SLOT = arg("slot");
if (!SLOT) { console.error("用法: --slot <HHMM> [--date d]"); process.exit(1); }
const date = arg("date") || new Date().toISOString().slice(0, 10);
const OUT = path.join(DIR, "facts", date, SLOT);
fs.mkdirSync(OUT, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const prefix = (code) => (/^(60|68|11[0138]|5)/.test(code) ? "sh" : "sz");
async function snap(code) {
    const r = await fetch(`https://qt.gtimg.cn/q=${prefix(code)}${code}`, { headers: { Referer: "https://gu.qq.com/" } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const m = new TextDecoder("gbk").decode(await r.arrayBuffer()).match(/="([\s\S]*)"/);
    if (!m) throw new Error("空");
    const f = m[1].split("~");
    return { code, name: f[1], last: +f[3], pct: +f[32], high: +f[33], low: +f[34], open: +f[5] };
}

// ---- 一字封死检测(10/3 立法, TODO §C.10: 选股层过滤, 一字票当日禁入候选) ----
// 判据: 开=高=低=现价 且涨跌幅达板限(10cm/20cm/30cm 分档); 盘前=昨日一字, 盘中=今日迄今一字
const limitOf = (code) => (/^(30|68)/.test(code) ? 19.7 : /^(8|4|920)/.test(code) ? 29.7 : 9.7);
const isSealed = (s) => s.open > 0 && s.open === s.high && s.high === s.low && s.low === s.last && Math.abs(s.pct) >= limitOf(s.code);
const sealTag = (s) => (s.pct > 0 ? "🔒一字涨停" : "🔒一字跌停");
async function sealMap(codes) {
    const map = new Map();
    for (const c of [...new Set(codes)].slice(0, 60)) {
        try { const s = await snap(c); if (isSealed(s)) map.set(c, sealTag(s)); } catch { }
        await sleep(400);
    }
    return map;
}
function markSealed(scanText, seals) {
    if (!seals.size) return { text: scanText, n: 0 };
    let n = 0;
    const text = scanText.split("\n").map((l) => {
        for (const [c, tag] of seals) if (l.includes(c)) { n++; return l.replace(/\s*$/, ` ${tag}·禁入候选`); }
        return l;
    }).join("\n");
    return { text, n };
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
    try { snaps.push({ ...(await snap(code)), tag }); } catch (e) { console.error(`快照失败 ${code}: ${e.message}`); }
    await sleep(500);
}

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
    // 上一 slot(同日期目录下比本 slot 小的最大者)
    const dayDir = path.join(DIR, "facts", date);
    const prev = fs.existsSync(dayDir) ? fs.readdirSync(dayDir).filter((d) => /^\d{4}$/.test(d) && d < SLOT).sort().pop() : null;
    const after = prev ? `${date} ${prev.slice(0, 2)}:${prev.slice(2)}:00` : `${date} 00:00:00`;
    const items = [...sec.matchAll(/^- \[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] (\[[\s\S]*?)(?=\n- \[|\n## |$)/gm)]
        .filter((x) => x[1] > after && x[1] <= `${date} ${SLOT.slice(0, 2)}:${SLOT.slice(2)}:59`)
        .map((x) => `- [${x[1].slice(11, 16)}] ${x[2].replace(/\n  !\[.*$/gm, "").slice(0, 300)}`);
    return items.length ? items.join("\n") : `(自${after.slice(11)}无新电报)`;
}

// ---- 拼 facts.md(LLM 读, 目标 2-4k token) ----
const md = [`# facts ${date} ${SLOT}（机械构建零 token; 版本=${date}/${SLOT}）`, "",
    "## 昨日账本状态", digest, "",
    "## 选股层硬过滤(机械规则, 优先级高于一切候选)", seals.size ? "🔒=一字封死(开=高=低=现价且达板限): 当日禁入候选, 无论买卖方向; 已在六榜行尾标注, 04/06 层不得将其列为可交易标的(等炸板分歧也不行——连续一字票进候选=废单制造机)" : "(今日无一字封死票)", "",
    "## 新到电报(自上一 slot)", telegraph(), "",
    "## 关注票实时快照", snaps.length ? snaps.map((s) => `- ${s.code} ${s.name}(${s.tag}): ${s.last} (${s.pct > 0 ? "+" : ""}${s.pct}%) 高${s.high} 低${s.low}${isSealed(s) ? " " + sealTag(s) + "·禁入候选" : ""}`).join("\n") : "(无持仓无挂单)", "",
    "## 大盘六榜", scanMd].join("\n");
fs.writeFileSync(path.join(OUT, "facts.md"), md);
fs.writeFileSync(path.join(OUT, "facts.json"), JSON.stringify({ date, slot: SLOT, builtAt: new Date().toISOString(), watch: snaps, chars: md.length }, null, 1));
console.log(`facts ${date}/${SLOT}: ${md.length}字 → ${OUT}/`);
console.log(`JSON:${JSON.stringify({ out: OUT, chars: md.length, watch: snaps.length })}`);
