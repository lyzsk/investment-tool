// rebuild_days.mjs — 指定日期段账本重建(2026-10-11 建; 首用=10/8-10/9: EOD 覆盖+回放失真修复)
// 背景: 10/8 nav 被 10/9 价格覆盖; 旧回放=碰价按挂价成交(买贵卖贱)+时间穿越(10/8 回放晚于 10/9 回放, 卖出了"未来"才买的票)。
// 规则(每本账):
//   保留 = 实盘撮合真实成交(why 不含"回放"), 但同日同向同票同价同量的重复成交只留第一笔(10/9 双成交案, 重复单置 cxl)
//   保留 = 实盘哨兵结论(锚偏离/笼子/一字/越界/失效/防重 CXL 等, 见 LIVE_SENTINEL)
//   重放 = 旧回放成交 + EOD 未成交作废(void 无哨兵注记) + 旧回放拒单 → 恢复 open, 交给修正后的 matcher --replay
//   状态 = 回到起始日开盘 10 万现金空仓; 逐日: 先放回当日真实成交 → replay D → eod D(历史日=日线收盘)
//   留痕 = 旧成交进 tradesRestated, 旧 nav 进 navRestated, 全部 books 先整目录备份
// 用法: node scripts/dfcf/paper/rebuild_days.mjs --from 2026-10-08 --to 2026-10-09   (PAPER_ROOT=<拷贝目录> 可先演练)
// 前提: 起始日前无成交(否则拒绝重建该账本); 起始日资金=10 万
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const DIR = process.env.PAPER_ROOT ? path.resolve(process.env.PAPER_ROOT) : SCRIPT_DIR;
const BOOKS = path.join(DIR, "books");
const arg = (k) => { const i = process.argv.indexOf("--" + k); return i > -1 ? process.argv[i + 1] : null; };
const FROM = arg("from"), TO = arg("to");
if (!FROM || !TO) { console.error("用法: --from yyyy-MM-dd --to yyyy-MM-dd"); process.exit(1); }
const INIT = 100000;
const LIVE_SENTINEL = /锚偏离作废|跨日过期作废|失效撤单|一字封死拒买|拒买一字|笼子废单|价格锚越界拒单|import防重CXL|CXL@|现金不足|持仓不足|T\+1/;
const now = new Date().toISOString();
const dayOf = (id) => String(id).slice(0, 10);
const inRange = (d) => d >= FROM && d <= TO;

// 交易日(md 文件名) ∩ 区间
const days = [];
for (const sub of fs.readdirSync(path.resolve(SCRIPT_DIR, "../../../md"))) {
    const p = path.resolve(SCRIPT_DIR, "../../../md", sub);
    if (fs.statSync(p).isDirectory()) for (const f of fs.readdirSync(p)) if (/^\d{4}-\d{2}-\d{2}\.md$/.test(f) && inRange(f.slice(0, 10))) days.push(f.slice(0, 10));
}
days.sort();
if (!days.length) { console.error(`区间 ${FROM}~${TO} 无交易日`); process.exit(1); }

function save(b, why) {  // 与 matcher.saveBook 同一哈希链口径
    const entry = { at: new Date().toISOString(), why, prev: b.lastHash || "GENESIS" };
    entry.hash = crypto.createHash("sha256").update(JSON.stringify({ c: b.cash, p: b.positions, n: b.trades.length, prev: entry.prev })).digest("hex").slice(0, 16);
    b.lastHash = entry.hash;
    (b.chain = b.chain || []).push(entry);
    fs.writeFileSync(path.join(BOOKS, b.source + ".json"), JSON.stringify(b, null, 1));
}
function apply(b, t) {  // 真实成交放回(与 matcher.fill 同口径: 成本含费用)
    const amt = t.price * t.qty, f = t.fee || 0;
    if (t.side === "BUY") {
        b.cash -= amt + f;
        const p = b.positions[t.code] || { qty: 0, cost: 0 };
        p.cost = (p.cost * p.qty + amt + f) / (p.qty + t.qty); p.qty += t.qty;
        b.positions[t.code] = p;
    } else {
        const p = b.positions[t.code];
        if (!p || p.qty < t.qty) throw new Error(`${b.source} 真实成交 ${t.id} 卖出时持仓不足(重建前提破坏)`);
        p.qty -= t.qty; b.cash += amt - f;
        if (!p.qty) delete b.positions[t.code];
    }
    b.trades.push({ ...t, why: `${t.why} | 实盘撮合(10/11 重建保留)` });
}

// ---- 1. 备份 ----
const bak = `${BOOKS}.bak-${now.slice(0, 16).replace(/[-:T]/g, "")}`;
fs.cpSync(BOOKS, bak, { recursive: true });
console.log(`备份 → ${bak}`);

// ---- 2. 逐账本复位 ----
const real = {};  // source → 当日真实成交
for (const f of fs.readdirSync(BOOKS).filter((x) => /^[AB]-.*\.json$/.test(x))) {
    const b = JSON.parse(fs.readFileSync(path.join(BOOKS, f), "utf8"));
    const touched = b.trades.some((t) => inRange(dayOf(t.id))) || b.orders.some((o) => inRange(o.date)) || b.nav.some((n) => inRange(n.date));
    if (!touched) continue;
    if (b.trades.some((t) => dayOf(t.id) < FROM)) { console.warn(`跳过 ${b.source}: 起始日前有成交, 无法从 10 万重建`); continue; }
    const seen = new Set(), dupIds = new Set(), keep = [];
    for (const t of [...b.trades].sort((x, y) => String(x.id).localeCompare(String(y.id)))) {
        if (!inRange(dayOf(t.id)) || /回放/.test(t.why || "")) continue;
        const k = [dayOf(t.id), t.side, t.code, t.price, t.qty].join("|");
        if (seen.has(k)) { dupIds.add(t.id); continue; }
        seen.add(k); keep.push(t);
    }
    real[b.source] = keep;
    const keepIds = new Set(keep.map((t) => t.id));
    let reopened = 0, dupOrders = 0;
    const orderKey = (o) => [o.date, o.side, o.code, o.price, o.qty].join("|");
    const taken = new Set(keep.map((t) => [dayOf(t.id), t.side, t.code, t.price, t.qty].join("|")));  // 真实成交已占的键
    for (const o of b.orders) if (inRange(o.date) && o.status === "open") taken.add(orderKey(o));       // 已在待撮合的单(如补导入)也占键
    for (const o of [...b.orders].filter((o) => inRange(o.date)).sort((x, y) => String(x.id).localeCompare(String(y.id)))) {
        if (keepIds.has(o.id)) continue;
        if (dupIds.has(o.id)) { o.status = "cxl"; o.note += " | 10/11 重建: 双成交重复单作废"; continue; }
        const replayed = o.status === "filled"                                                   // 剩下的 filled 都是旧回放成交
            || (o.status === "void" && !LIVE_SENTINEL.test(o.note || ""))                         // EOD 未成交作废
            || ((o.status === "reject" || o.status === "invalid") && /回放/.test(o.note || ""));   // 旧回放拒单
        if (!replayed) continue;
        // 链回炉重复 emit 的同键单(同日同向同票同价同量)只留最早一张, 与真实成交同键的也作废(10/11 桃哥 600026/002164 双份案)
        if (taken.has(orderKey(o))) { o.status = "cxl"; o.note += " | 10/11 重建: 重复挂单作废(同键已存在)"; dupOrders++; continue; }
        taken.add(orderKey(o));
        o.status = "open"; delete o.fillPrice; delete o.fee; delete o.fillWhy;
        o.note += " | 10/11 重建重放"; reopened++;
    }
    b.tradesRestated = [...(b.tradesRestated || []), ...b.trades.map((t) => ({ ...t, restatedAt: now }))];
    b.navRestated = [...(b.navRestated || []), ...b.nav.filter((n) => inRange(n.date)).map((n) => ({ ...n, restatedAt: now }))];
    b.trades = []; b.nav = b.nav.filter((n) => n.date < FROM);
    b.cash = INIT; b.positions = {};
    save(b, `10/11 重建 ${FROM}~${TO}: 复位 10 万空仓, 保留真实成交 ${keep.length}(去重 ${dupIds.size}), 重放 ${reopened} 单, 重复挂单作废 ${dupOrders}`);
    console.log(`复位 ${b.source}: 真实成交保留 ${keep.length} 笔(重复作废 ${dupIds.size}), 待重放 ${reopened} 单, 重复挂单作废 ${dupOrders}`);
}

// ---- 3. 逐日: 真实成交 → replay → eod ----
const M = path.join(SCRIPT_DIR, "matcher.mjs");
const run = (...a) => execFileSync(process.execPath, [M, ...a], { encoding: "utf8", env: process.env, windowsHide: true });
for (const d of days) {
    for (const [src, list] of Object.entries(real)) {
        const today = list.filter((t) => dayOf(t.id) === d);
        if (!today.length) continue;
        const b = JSON.parse(fs.readFileSync(path.join(BOOKS, src + ".json"), "utf8"));
        for (const t of today) apply(b, t);
        save(b, `10/11 重建: 放回 ${d} 真实成交 ${today.length} 笔`);
    }
    console.log(run("--replay", "--date", d).split("\n").filter((l) => /^回放 |拒|笼子|越界/.test(l)).join("\n"));
    console.log(run("--eod", "--date", d).split("\n").filter((l) => /^EOD/.test(l)).join("\n"));
}
console.log(`重建完成 ${days.join(",")}; 备份在 ${bak}`);
