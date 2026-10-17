// daily_digest.mjs — paper 每日微信简报(2026-10-11 用户令: 每晚结算后推当日简报, 床上能看)
// 内容: 上证/对照组基准 → 当日涨幅前三/后三(带累计) → 未出单账户 → 拟人度(skill−对照, 滚动) → 报告路径
// 用法: node scripts/dfcf/paper/daily_digest.mjs --date yyyy-MM-dd [--send]   (matcher --eod 实盘收盘后自动 --send)
//   不带 --send=只打印(调试); 发送走 hermes send --to weixin(复用网关凭据, 无 LLM)
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { ACCOUNTS, INIT, NAME } from "./accounts.mjs";
import { summaryLines as realLines } from "./real_vs_chain.mjs";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const DIR = process.env.PAPER_ROOT ? path.resolve(process.env.PAPER_ROOT) : SCRIPT_DIR;
const KDIR = path.resolve(SCRIPT_DIR, "../../../downloads/quotes/daily");
const HERMES = "C:\\Users\\admin\\AppData\\Local\\hermes\\hermes-agent\\bin\\hermes.exe";
const arg = (k) => { const i = process.argv.indexOf("--" + k); return i > -1 ? process.argv[i + 1] : null; };
const DATE = arg("date") || new Date().toLocaleDateString("sv-SE");
const sign = (x, d = 2) => (x == null ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x * 100).toFixed(d) + "%");

const rows = [];
for (const [src, name, kind] of ACCOUNTS) {
    let b;
    try { b = JSON.parse(fs.readFileSync(path.join(DIR, "books", src + ".json"), "utf8")); } catch { continue; }
    const i = b.nav.findIndex((n) => n.date === DATE);
    if (i < 0) continue;
    const nav = b.nav[i].nav, prev = b.nav.slice(0, i).filter((n) => n.date >= "2026-10-08").pop()?.nav ?? INIT;
    rows.push({ src, name, kind, day: nav / prev - 1, cum: nav / INIT - 1, orders: b.nav[i].orders ?? 0, filled: b.nav[i].filled ?? 0 });
}
if (!rows.length) { console.log(`${DATE} 无结算数据, 不发`); process.exit(0); }

let bench = null;
try {
    const k = JSON.parse(fs.readFileSync(path.join(KDIR, "1_000001.json"), "utf8")).klines;
    const j = k.findIndex((x) => x.d === DATE);
    if (j > 0) bench = k[j].c / k[j - 1].c - 1;
} catch { /* 指数缺 */ }

const ctrl = rows.find((r) => r.kind === "对照");
const skills = rows.filter((r) => r.kind !== "对照").sort((a, b) => b.day - a.day);
const lvl = (x) => (x == null ? "—" : (x * 100).toFixed(0) + "%");   // 拟人度=水平值, 不带正负号
const dlt = (x) => (x >= 0 ? "+" : "−") + Math.abs(x * 100).toFixed(0);
const fmt = (r) => `${r.name} ${sign(r.day)}(累计${sign(r.cum, 1)})`;
const lines = [`【paper 日报 ${DATE.slice(5)}】`,
    `上证 ${sign(bench)} | 对照组 ${ctrl ? sign(ctrl.day) : "—"}`,
    `今日前三: ${skills.slice(0, 3).map(fmt).join("、")}`,
    `今日后三: ${skills.slice(-3).reverse().map(fmt).join("、")}`];
if (ctrl) lines.push(`跑赢对照组: ${skills.filter((r) => r.day > ctrl.day).length}/${skills.length} 个账户`);
const idle = skills.filter((r) => !r.orders).map((r) => r.name);
if (idle.length) lines.push(`今日未出单: ${idle.join("、")}`);
// 10/11: 质量异常可见化——盲审降级照发的单 + 导入被拒的单(原静默丢单)
const blindAcc = [], NAMEMAP = Object.fromEntries(ACCOUNTS.map(([s, n]) => [s, n]));
for (const [src] of ACCOUNTS) {
    try {
        const b = JSON.parse(fs.readFileSync(path.join(DIR, "books", src + ".json"), "utf8"));
        const n = b.orders.filter((o) => o.date === DATE && /【未过(盲审|拟人审)】/.test(o.note || "")).length;
        if (n) blindAcc.push(`${NAMEMAP[src]}×${n}`);
    } catch { /* 账本缺 */ }
}
if (blindAcc.length) lines.push(`未过盲审/拟人审照发: ${blindAcc.join("、")}`);
try {   // 10/16 晚 B8 初版权重(skill_weights.py, check md 收盘后算; 读最新一份)
    const wd = path.join(SCRIPT_DIR, "weights");
    const wf = fs.readdirSync(wd).filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f) && f.slice(0, 10) <= DATE).sort().pop();
    if (wf) {
        const W = JSON.parse(fs.readFileSync(path.join(wd, wf), "utf8")).rows;
        const fmt = (r) => `${r.name}${(r.w * 100).toFixed(1)}%`;
        lines.push(`权重(${wf.slice(5, 10)} 初版, 拟人度×真人业绩, 样本少≈等权): 前 ${W.slice(0, 3).map(fmt).join("、")} | 后 ${W.slice(-3).map(fmt).join("、")}`);
    }
} catch { /* 权重文件未出 */ }
try {
    const rej = fs.readFileSync(path.join(DIR, "import_rejects.csv"), "utf8").split("\n").filter((l) => l.startsWith(DATE + ","));
    if (rej.length) {
        const by = {};
        for (const l of rej) { const s = l.split(",")[1]; by[s] = (by[s] || 0) + 1; }
        lines.push(`挂单被拒: ${Object.entries(by).map(([s, n]) => `${NAMEMAP[s] || s}×${n}`).join("、")}(明细 import_rejects.csv)`);
    }
} catch { /* 无被拒 */ }
try {
    const sim = JSON.parse(fs.readFileSync(path.join(DIR, "similarity.json"), "utf8"));
    const s = sim.summary.filter((x) => x.delta != null).sort((a, b) => b.delta - a.delta);
    if (s.length) lines.push(`拟人度(截至${sim.updated.slice(4, 6)}/${sim.updated.slice(6)}, skill−对照): ` +
        s.slice(0, 3).map((x) => `${NAME[x.book] || x.name} ${lvl(x.comp)}(${dlt(x.delta)})`).join("、") +
        (s.length > 3 ? `; 垫底 ${NAME[s.at(-1).book] || s.at(-1).name} ${lvl(s.at(-1).comp)}(${dlt(s.at(-1).delta)})` : ""));
} catch { /* 拟人度未生成 */ }
// 10/15 用户令: B 线=导师真人(tzzb), 挂"真人当日/链当日/持仓重合"对照; 全表(含持仓明细)落 real_vs_chain/<日>.md
try { lines.push(...realLines(DATE)); } catch (e) { lines.push(`B线真人对照生成失败: ${e.message}`); }
lines.push("详情: scripts/dfcf/paper/report.html(悬停看全部账户); 真人对照全表 real_vs_chain/" + DATE + ".md");
const msg = lines.join("\n");
console.log(msg);
if (process.argv.includes("--send")) {
    for (let t = 1; t <= 5; t++) {   // iLink 限流冷却 30s+, 最多重试 5 次
        try { console.log(execFileSync(HERMES, ["send", "--to", "weixin", msg], { encoding: "utf8", windowsHide: true }).trim()); break; }
        catch (e) { console.warn(`微信发送失败(第${t}次): ${String(e.stdout || e.message).slice(-120)}`); if (t < 5) execFileSync(process.execPath, ["-e", "setTimeout(()=>{},60000)"]); }
    }
}
