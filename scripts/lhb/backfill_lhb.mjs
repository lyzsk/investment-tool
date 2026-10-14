// backfill_lhb.mjs — 龙虎榜历史回填(倒序 新→旧, 逐日调 fetch_lhb.mjs; 2026-10-14 建)
// 用法: node scripts/lhb/backfill_lhb.mjs --from 2025-01-07 --to yyyy-MM-dd [--max-days N] [--write] [--until HH:MM] [--gap 秒] [--remount]
//   --max-days: 本次最多"真抓"N 天(已完整只差挂 md 的不计数, 走缓存零请求)
//   --until: 到这个时刻不再开新的一天(跨午夜按"下一次出现"算; check md 00:00 轮传 06:40, 保证 07:00 前停)
//   --gap: 两个"真抓"日之间的间隔秒数(缺省 8, ×0.75~1.25 抖动); fetch_lhb 内部请求间隔另有 2.0~3.0s
//   --remount: 零请求重挂——只对 json 已完整的日子用缓存按当前格式整节重写 md(改了列/金额格式后用), 不完整的日子跳过不抓
// 跳过: list.json 完整(18:00 后抓)+detail 齐 → 不请求; --write 时 md 已有总表/无复盘节/无 md 的连 fetch_lhb 都不起
// 停止条件: 反爬(exit 5)立即停; 连续 2 天抓取失败停(不硬打); 到 --until; 到 --max-days
// 金丝雀: 开始/结束各探一次东财 push2(实盘行情源)是否正常, 写进日志——证明回填没把东财域名打封
// 交易日: inv-common/.../holiday/*.json(isOffDay=true 休) + 周末休(A 股调休周六不开市); 东财返回空=当日无榜, 记"空榜"不算失败
// 日志: scripts/lhb/logs/backfill_<yyyyMMdd_HHmm>.log; 末行 JSON:{...}
// 出口: 0=正常结束(含到 until/max-days) 1=有失败日 5=遇反爬中止
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
process.chdir(ROOT);
const ARGS = process.argv.slice(2);
const opt = (k) => { const i = ARGS.indexOf(k); return i === -1 ? null : ARGS[i + 1]; };
const FROM = opt("--from") || "2025-01-07";
const TO = opt("--to");
const MAX = +(opt("--max-days") || 1e9);
const WRITE = ARGS.includes("--write") || ARGS.includes("--remount");
const REMOUNT = ARGS.includes("--remount");
const UNTIL = opt("--until");
const GAP = +(opt("--gap") || 8);
if (!TO) { console.error("用法: node scripts/lhb/backfill_lhb.mjs --from 2025-01-07 --to yyyy-MM-dd [--max-days N] [--write] [--until HH:MM] [--gap 秒]"); process.exit(2); }

const bj = () => new Date(Date.now() + 8 * 3600e3).toISOString().slice(0, 19).replace("T", " ");
const LOG_DIR = path.join("scripts", "lhb", "logs");
fs.mkdirSync(LOG_DIR, { recursive: true });
const LOG = path.join(LOG_DIR, `backfill_${bj().replace(/[-: ]/g, "").slice(0, 12).replace(/^(\d{8})/, "$1_")}.log`);
const log = (m) => { const l = `[${bj().slice(11)}] ${m}`; console.log(l); fs.appendFileSync(LOG, l + "\n"); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 截止时刻(北京时间 HH:MM 的下一次出现)
let deadline = null;
if (UNTIL) {
    const [h, m] = UNTIL.split(":").map(Number);
    const now = new Date();
    deadline = new Date(now);
    deadline.setHours(h, m, 0, 0);
    if (deadline <= now) deadline.setDate(deadline.getDate() + 1);
}

// 交易日列表(倒序)
const off = {};
const HD = path.join("inv-common", "src", "main", "resources", "holiday");
if (fs.existsSync(HD)) for (const f of fs.readdirSync(HD).filter((x) => x.endsWith(".json"))) Object.assign(off, JSON.parse(fs.readFileSync(path.join(HD, f), "utf8")));
const days = [];
for (let d = new Date(TO + "T00:00:00Z"); d >= new Date(FROM + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() - 1)) {
    const iso = d.toISOString().slice(0, 10);
    const wd = d.getUTCDay();
    if (wd === 0 || wd === 6 || off[iso] === true) continue;
    days.push(iso);
}

function complete(date) {
    const dir = path.join("downloads", "lhb", date.replace(/-/g, "."));
    try {
        const L = JSON.parse(fs.readFileSync(path.join(dir, "list.json"), "utf8"));
        if (!(L.fetched_at >= `${date} 18:00`) || !L.rows?.length) return false;
        return [...new Set(L.rows.map((r) => r.SECURITY_CODE))].every((c) => fs.existsSync(path.join(dir, `detail_${c}.json`)));
    } catch { return false; }
}

// md 侧不用再动: 无 md / 无 ## 复盘(早期 41 天, 只存 json) / ### 龙虎榜 已有总表 → 缓存日连 fetch_lhb 都不起(补完后每晚空转只需秒级)
function mdSettled(date) {
    const [y, m] = date.split("-");
    const f = path.join("md", `${y}S${Math.ceil(+m / 3)}`, `${date}.md`);
    if (!fs.existsSync(f)) return "no_md";
    const t = fs.readFileSync(f, "utf8").replace(/\r/g, "");
    if (!/^## 复盘[ \t]*$/m.test(t)) return "no_fupan";
    const i = t.search(/^### 龙虎榜[ \t]*$/m);
    if (i < 0) return null;
    const nl = t.indexOf("\n", i);
    const rest = nl < 0 ? "" : t.slice(nl + 1);
    const e = rest.search(/^#{1,3} /m);
    const sec = e < 0 ? rest : rest.slice(0, e);
    return /^\| [^|\n]+ \d{6} \|/m.test(sec) ? "written" : null;   // 表头随模板可改, 只认"首格=名 6位代码"的数据行
}

async function canary(tag) {
    try {
        const r = await fetch("https://push2.eastmoney.com/api/qt/stock/get?secid=1.000001&fields=f43,f58", {
            headers: { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36" }, signal: AbortSignal.timeout(10000) });
        const j = await r.json();
        const ok = r.ok && j?.data?.f58;
        log(`金丝雀(${tag}) 东财 push2: ${ok ? `正常(${j.data.f58} ${j.data.f43})` : `异常 HTTP ${r.status} ${JSON.stringify(j).slice(0, 80)}`}`);
        return !!ok;
    } catch (e) {
        log(`金丝雀(${tag}) 东财 push2: 异常 ${e.message}`);
        return false;
    }
}

const S = { range: `${FROM}~${TO}`, trading_days: days.length, fetched: 0, cached: 0, empty: [], no_md: [], no_fupan: [], failed: [],
    md_written: 0, stock_times: 0, requests: 0, stop: "完成全部" };
const T0 = Date.now();
log(`===== 龙虎榜回填 ${FROM}~${TO} 倒序, 交易日 ${days.length} 天, max-days=${MAX === 1e9 ? "不限" : MAX}, until=${UNTIL || "不限"}, gap=${GAP}s, write=${WRITE} =====`);
S.canary_start = REMOUNT ? null : await canary("开始");   // 重挂零请求, 不探
let consecFail = 0;
for (const d of days) {
    if (deadline && new Date() >= deadline) { S.stop = `到截止 ${UNTIL}`; break; }
    const cached = complete(d);
    if (cached && !WRITE) { S.cached++; continue; }
    if (REMOUNT && !cached) continue;
    if (cached && WRITE && !REMOUNT) {
        const st = mdSettled(d);
        if (st) { S.cached++; if (st === "no_fupan") S.no_fupan.push(d); if (st === "no_md") S.no_md.push(d); continue; }
    }
    if (!cached && S.fetched >= MAX) { S.stop = `到 max-days ${MAX}`; break; }
    const r = spawnSync(process.execPath, ["scripts/lhb/fetch_lhb.mjs", "--date", d, ...(WRITE ? ["--write"] : [])], { encoding: "utf8", windowsHide: true, timeout: 15 * 60e3 });
    const jl = (r.stdout || "").split("\n").reverse().find((l) => l.startsWith("JSON:"));
    const j = jl ? JSON.parse(jl.slice(5)) : { code: r.status ?? 1, msg: (r.stderr || "").slice(0, 200) };
    S.requests += j.requests || 0;
    if (cached) S.cached++; else S.fetched++;
    if (j.code === 0 || j.code === 4) {
        S.stock_times += j.stocks || 0;
        if (j.md === "已写") S.md_written++;
        if (j.md === "无复盘节(只存json)") S.no_fupan.push(d);
        if (j.code === 4) S.no_md.push(d);
        consecFail = 0;
        if (!cached || j.md === "已写") log(`${d} ✓ ${j.stocks} 只/${j.records} 条, 请求 ${j.requests}, ${j.secs}s, md=${j.md ?? "-"}${j.code === 4 ? "(无md)" : ""}`);
    } else if (j.code === 3) {
        S.empty.push(d);
        consecFail = 0;
        log(`${d} - 空榜(东财无数据, 疑非交易日)`);
    } else {
        S.failed.push(d);
        consecFail++;
        log(`${d} ✗ exit ${j.code}: ${j.msg}`);
        if (j.code === 5) { S.stop = `遇反爬(${d}: ${j.msg})`; break; }
        if (consecFail >= 2) { S.stop = `连续 ${consecFail} 天失败, 停止不硬打`; break; }
    }
    if (!cached) await sleep(GAP * 1000 * (0.75 + Math.random() * 0.5));
}
S.canary_end = REMOUNT ? null : await canary("结束");
S.secs = Math.round((Date.now() - T0) / 1000);
S.remaining = days.filter((d) => !complete(d)).length - S.empty.length;
log(`===== 结束: ${S.stop}; 真抓 ${S.fetched} 天 / 缓存 ${S.cached} 天, 请求 ${S.requests} 次, 只次 ${S.stock_times}, 写 md ${S.md_written}, `
    + `无复盘(只存json) ${S.no_fupan.length}, 空榜 ${S.empty.length}, 失败 ${S.failed.length}, 余 ${S.remaining} 天未完整, 用时 ${S.secs}s =====`);
console.log("JSON:" + JSON.stringify({ ...S, log: LOG.replace(/\\/g, "/") }));
process.exit(S.stop.startsWith("遇反爬") ? 5 : S.failed.length ? 1 : 0);
