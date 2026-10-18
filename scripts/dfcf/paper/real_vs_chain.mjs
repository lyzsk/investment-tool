// real_vs_chain.mjs — B 线(导师真人)对照 A 线(skill 链)逐日表(零 token, 只读; 2026-10-15 用户令)
// 口径(10/15 用户澄清): A 线=skill 沉淀跑模拟盘; B 线=导师真人真实操作(同花顺投资账本 tzzb), 不再是早期"hermes 临场单"
// 每位有 tzzb 账本的导师(正样本)一行: 真人当日涨跌(账本 index_list 日环比) / 链当日涨跌(books nav 日环比) / 真人持仓 / 链持仓 / 重合只数
//   日期: --date 当天真人还没更新(tzzb 15:10 起抓, 晚到账本 23:10 前)=该导师取 ≤date 的最近真人日, 链同取那天, 行内标日期
//   链持仓 = 成交流水重放到该日收盘(同 similarity.mjs simState 口径); 真人持仓 = day_positions 该日(剔逆回购)
// 用法: node scripts/dfcf/paper/real_vs_chain.mjs [--date yyyy-MM-dd]   → 写 real_vs_chain/<date>.md + stdout
//   被 daily_digest.mjs import 取 summaryLines() 挂进微信日报
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { NAME } from "./accounts.mjs";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const DIR = process.env.PAPER_ROOT ? path.resolve(process.env.PAPER_ROOT) : SCRIPT_DIR;
const ROOT = path.resolve(SCRIPT_DIR, "../../..");
const TZZB = path.join(ROOT, "downloads", "tzzb");
const isRepo = (code, name) => /^(204|1318)/.test(code || "") || /GC0|R-00/.test(name || "");
const pct = (x) => (x == null ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x * 100).toFixed(2) + "%");
const readJson = (f) => { try { return JSON.parse(fs.readFileSync(f, "utf8")); } catch { return null; } };

function pairs() {
    const ledgers = readJson(path.join(ROOT, "scripts", "tzzb", "tzzb_ledgers.json")) || [];
    return ledgers.filter((l) => l.kind !== "neg")
        .map((l) => ({ book: l.ledger === "buchitudou0" ? "A-cb" : "A-" + l.ledger, ledger: l.ledger, name: NAME[l.ledger === "buchitudou0" ? "A-cb" : "A-" + l.ledger] || l.name || l.ledger }));
}

// 真人: ≤date 的最近一日 {d, ret, hold[名称]}; 无账本/无数据=null
function realOf(ledger, date) {
    const il = readJson(path.join(TZZB, ledger, "nav_daily.json"))?.ex_data?.index_list;
    if (!il?.length) return null;
    const d8 = date.replaceAll("-", "");
    const i = il.findLastIndex((x) => x.date <= d8);
    if (i < 1) return null;
    const d = il[i].date, dd = `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}`;
    const dp = readJson(path.join(TZZB, ledger, "day_positions.json"))?.[d];
    const hold = dp ? (dp.list || []).filter((x) => +x.position_percent > 0 && !isRepo(x.code, x.name)).map((x) => ({ code: x.code, name: x.name, pct: +x.position_percent })) : null;
    return { d: dd, ret: +il[i].index / +il[i - 1].index - 1, hold, sum: dp ? dp.sum_pct : null };
}

// 链: 该日 nav 日环比 + 成交流水重放到该日收盘的持仓
function chainOf(book, dd, names) {
    const b = readJson(path.join(DIR, "books", book + ".json"));
    if (!b) return null;
    const navs = (b.nav || []).filter((n) => n.date >= "2026-10-08");   // 10/8 实盘重新开户
    const i = navs.findIndex((n) => n.date === dd);
    const ret = i < 0 ? null : navs[i].nav / (i > 0 ? navs[i - 1].nav : 100000) - 1;
    const qty = {};
    for (const t of [...(b.trades || [])].sort((x, y) => String(x.id).localeCompare(String(y.id)))) {
        if (String(t.id).slice(0, 10) > dd) continue;
        qty[t.code] = (qty[t.code] || 0) + (t.side === "BUY" ? t.qty : -t.qty);
    }
    const hold = Object.keys(qty).filter((c) => qty[c] > 0 && !isRepo(c)).map((c) => ({ code: c, name: names[c] || c }));
    return { ret, hold };
}

export function build(date) {
    const names = readJson(path.join(SCRIPT_DIR, "names.json")) || {};
    const rows = [];
    for (const p of pairs()) {
        if (!fs.existsSync(path.join(DIR, "books", p.book + ".json"))) continue;
        const r = realOf(p.ledger, date);
        if (!r) continue;
        const c = chainOf(p.book, r.d, names);
        if (!c) continue;
        const rc = new Set((r.hold || []).map((x) => x.code));
        rows.push({ ...p, d: r.d, rRet: r.ret, cRet: c.ret, rHold: r.hold, rSum: r.sum, cHold: c.hold, overlap: c.hold.filter((x) => rc.has(x.code)).length });
    }
    return rows;
}

export function summaryLines(date) {
    const rows = build(date).filter((x) => x.cRet != null);
    if (!rows.length) return [];
    const same = rows.filter((x) => Math.sign(x.rRet) === Math.sign(x.cRet)).length;
    const stale = rows.filter((x) => x.d !== date).length;
    const out = [`B线真人对照(真人/链 当日, 持仓重合): 真人红${rows.filter((x) => x.rRet > 0).length}绿${rows.filter((x) => x.rRet < 0).length}, ` +
        `链红${rows.filter((x) => x.cRet > 0).length}绿${rows.filter((x) => x.cRet < 0).length}, 同向 ${same}/${rows.length}, 持仓重合合计 ${rows.reduce((s, x) => s + x.overlap, 0)} 只` +
        (stale ? `(${stale} 位真人今日未更新, 用最近一日)` : "")];
    for (const x of rows) out.push(`· ${x.name.replace(/\(.*\)$/, "")}${x.d !== date ? "[" + x.d.slice(5) + "]" : ""} ${pct(x.rRet)}/${pct(x.cRet)} 重合${x.overlap}`);
    return out;
}

function markdown(date, rows) {
    const L = [`# B线(导师真人) vs A线(skill 链) ${date}`, "",
        "> 真人=同花顺投资账本 index 日环比; 链=paper 账本 nav 日环比; 真人当日未更新的取最近一日(日期列标出), 链同取那天", "",
        "| 导师 | 日期 | 真人当日 | 链当日 | 同向 | 真人持仓(仓位) | 链持仓 | 重合 |", "|---|---|---|---|---|---|---|---|"];
    for (const x of rows) {
        const rh = x.rHold == null ? "(无持仓数据)" : x.rHold.length ? x.rHold.map((h) => `${h.name}(${h.pct >= 0.01 ? Math.round(h.pct * 100) + "%" : "<1%"})`).join("、") : "空仓";
        L.push(`| ${x.name} | ${x.d} | ${pct(x.rRet)} | ${pct(x.cRet)} | ${x.cRet == null ? "—" : Math.sign(x.rRet) === Math.sign(x.cRet) ? "✓" : "✗"} | ${rh} | ${x.cHold.map((h) => h.name).join("、") || "空仓"} | ${x.overlap} |`);
    }
    return L.join("\n") + "\n";
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
    const i = process.argv.indexOf("--date");
    const date = i > -1 ? process.argv[i + 1] : new Date().toLocaleDateString("sv-SE");
    const rows = build(date);
    const out = path.join(DIR, "real_vs_chain");
    fs.mkdirSync(out, { recursive: true });
    fs.writeFileSync(path.join(out, `${date}.md`), markdown(date, rows), "utf8");
    console.log(markdown(date, rows));
    console.log(summaryLines(date).join("\n"));
}
