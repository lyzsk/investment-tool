// scorecard.mjs — 模拟盘评分卡(零 token 机械层, 2026-10-04 盲区修复⑧: score/reward 数值化)
// 数据源: nav_<source>.csv(date,cash,mv,nav,filled,voided) + token_log.csv(date,slot,step,attempt,in,out,cost_usd,duration_s)
// 产物: scorecard.md(人读) + scorecard.json(机器); 定位=TradingAgents 缺口的 score/reward 层最小实现
// 口径: 6 账本横向归因(A=定时链/B=hermes 盘中/C=用户人工)——谁的决策赚谁的线; 收益数字仅供账本间相对比较(铁律3不看绝对值)
// 用法: node scripts/dfcf/paper/scorecard.mjs [--out <dir>]
import fs from "node:fs";
import path from "node:path";

const DIR = path.resolve("scripts/dfcf/paper");
const OUT = (() => { const i = process.argv.indexOf("--out"); return i > -1 ? process.argv[i + 1] : DIR; })();
const START_NAV = 100000;
const USD_CNY = 7.2;  // token 成本折算汇率(近似, 看量级不看精确)

const readCsv = (f) => fs.existsSync(f) ? fs.readFileSync(f, "utf8").trim().split("\n").map((l) => l.split(",")) : [];

// ---- 账本指标 ----
const books = [];
for (const f of fs.readdirSync(DIR).filter((x) => /^nav_.+\.csv$/.test(x))) {
    const src = f.slice(4, -4);
    const rows = readCsv(path.join(DIR, f)).map(([date, cash, mv, nav, filled, voided]) => ({ date, cash: +cash, mv: +mv, nav: +nav, filled: +filled, voided: +voided }));
    if (!rows.length) continue;
    const navs = rows.map((r) => r.nav);
    const last = rows[rows.length - 1];
    const ret = last.nav / START_NAV - 1;
    let mdd = 0, peak = navs[0];
    for (const n of navs) { peak = Math.max(peak, n); mdd = Math.min(mdd, n / peak - 1); }
    const rets = [];
    for (let i = 1; i < navs.length; i++) rets.push(navs[i] / navs[i - 1] - 1);
    const mean = rets.length ? rets.reduce((a, b) => a + b, 0) / rets.length : 0;
    const sd = rets.length > 1 ? Math.sqrt(rets.reduce((a, b) => a + (b - mean) ** 2, 0) / (rets.length - 1)) : 0;
    const sharpe = sd > 0 ? (mean / sd) * Math.sqrt(252) : null;  // 日频年化, rf=0; 样本<10 日纯看符号
    const filled = rows.reduce((a, r) => a + r.filled, 0), voided = rows.reduce((a, r) => a + r.voided, 0);
    books.push({ src, days: rows.length, nav: last.nav, ret, mdd, sharpe, filled, voided,
        voidRate: filled + voided ? voided / (filled + voided) : 0, position: last.mv / last.nav });
}

// ---- token 成本 ----
const tok = readCsv(path.join(DIR, "token_log.csv"));
const tokRows = (tok[0] && tok[0][0] === "date" ? tok.slice(1) : tok)
    .map(([date, slot, step, attempt, tin, tout, cost, dur]) => ({ date, slot, step, cost: +cost || 0, tokens: (+tin || 0) + (+tout || 0), dur: +dur || 0 }));
const costTotal = tokRows.reduce((a, r) => a + r.cost, 0);
const tokTotal = tokRows.reduce((a, r) => a + r.tokens, 0);
const byStep = {};
for (const r of tokRows) { (byStep[r.step] = byStep[r.step] || { cost: 0, tokens: 0, n: 0 }); const b = byStep[r.step]; b.cost += r.cost; b.tokens += r.tokens; b.n++; }

// ---- 输出 ----
const pct = (x) => (x * 100).toFixed(2) + "%";
const nowLocal = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };  // 禁 toISOString: UTC 偏移(rotation.mjs 同款教训)
const lines = [`# 模拟盘评分卡(生成=${nowLocal()}, scorecard.mjs 机械生成)`, ""];
lines.push("## 账本归因(起始各 10 万虚拟金)", "",
    "| 账本 | 天数 | 净值 | 累计收益 | 最大回撤 | 简易Sharpe | 成交/废单 | 废单率 | 仓位 |",
    "|---|---|---|---|---|---|---|---|---|");
for (const b of books.sort((a, b) => b.ret - a.ret))
    lines.push(`| ${b.src} | ${b.days} | ${b.nav.toFixed(0)} | ${pct(b.ret)} | ${pct(b.mdd)} | ${b.sharpe == null ? "-" : b.sharpe.toFixed(2)} | ${b.filled}/${b.voided} | ${pct(b.voidRate)} | ${pct(b.position)} |`);
lines.push("", "## 链 token 成本(仅定时链有日志; 样本期累计)", "",
    `- 总成本: $${costTotal.toFixed(2)}(≈¥${(costTotal * USD_CNY).toFixed(0)}) / ${(tokTotal / 1e4).toFixed(1)}万 token / ${tokRows.length} 次调用`,
    "", "| 环节 | 次数 | 成本$ | token万 |", "|---|---|---|---|");
for (const [s, b] of Object.entries(byStep).sort((a, b) => b[1].cost - a[1].cost))
    lines.push(`| ${s} | ${b.n} | ${b.cost.toFixed(2)} | ${(b.tokens / 1e4).toFixed(1)} |`);
lines.push("", "> 口径注记: 收益为纸面(撮合保守规则已防虚高); Sharpe 样本<10 日只看符号不看量级; token 成本只含定时链(hermes/C 线无日志)。");
const md = lines.join("\n");
fs.writeFileSync(path.join(OUT, "scorecard.md"), md);
fs.writeFileSync(path.join(OUT, "scorecard.json"), JSON.stringify({ builtAt: new Date().toISOString(), books, cost: { usd: +costTotal.toFixed(4), tokens: tokTotal, byStep } }, null, 1));
console.log(md);
