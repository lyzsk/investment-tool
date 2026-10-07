// replay_daily.mjs — 日线近似撮合回放器(2026-10-07 建, ④号件)
// 背景: 9/28-30 分钟行情已过 5 天归档窗, matcher 活快照模式无法回放 → 本脚本用日线 OHLC 近似撮合
// 语义(近似, report 会标注): 触发= low<=触发价<=high; 跳空低开按开盘价成交; cancel_below 当日触及即废;
//      持仓止损 stop_below 当日 low 触及即按 stop 价出(保守); 手续费=matcher CONFIG 同口径。
// 用法: node scripts/dfcf/paper/replay_daily.mjs --from 2026-09-28 --to 2026-09-30
import fs from "fs";
import path from "path";

const arg = (k) => { const i = process.argv.indexOf("--" + k); return i > -1 ? process.argv[i + 1] : null; };
const FROM = arg("from"), TO = arg("to");
const WRITE_BOOKS = process.argv.includes("--write-books");
if (!FROM || !TO) { console.error("用法: --from yyyy-MM-dd --to yyyy-MM-dd"); process.exit(1); }
const DIR = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const BOOKS = ["A-taoge", "A-cb", "A-qushitiange", "A-lubenyuan", "A-tzzb"];
const NAV0 = 100000, FEE = 0.00025, MINFEE = 5, STAMP = 0.0005;

const klineCache = {};
function dayRow(code, d) {
    if (!(code in klineCache)) {
        const f = path.join(DIR, "..", "..", "..", "downloads", "quotes", "daily", `${code}.json`);
        klineCache[code] = fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, "utf8")).klines : [];
    }
    return klineCache[code].find((k) => k.d === d) || null;
}
const dates = [];
for (let d = new Date(FROM); d <= new Date(TO); d.setDate(d.getDate() + 1)) {
    const s = d.toISOString().slice(0, 10); if (s >= FROM && s <= TO) dates.push(s);
}

const report = [`# 日线近似撮合回放 ${FROM}~${TO}`, `> 近似口径: OHLC 区间判定/跳空按开盘/止损按 stop 价; 非 tick 精确。`, ""];
const summary = [];
for (const book of BOOKS) {
    let cash = NAV0; const pos = {}; const navRows = []; let filled = 0, voided = 0, noQuote = 0;
    for (const d of dates) {
        const pf = path.join(DIR, "plans", `${d}_${book}.md`);
        if (fs.existsSync(pf)) {
            for (const line of fs.readFileSync(pf, "utf8").split("\n")) {
                const m = line.match(/- \d\d:\d\d \| \S+ \| (BUY|SELL|CANCELED|买|卖) \| (\d{6}) \| ([\d.]+) \| (\d+) \|/);
                if (!m) continue;
                const opRaw = m[1], op = opRaw === "买" ? "BUY" : opRaw === "卖" ? "SELL" : opRaw;
                const [, , code, pxs, qtys] = m; const px = +pxs, qty = +qtys;
                const cancel = (line.match(/cancel_below=([\d.]+)/) || [])[1];
                const stop = (line.match(/stop_below=([\d.]+)/) || [])[1];
                const row = dayRow(code, d);
                if (!row) { noQuote++; continue; }
                if (op === "CANCELED") { voided++; continue; }
                if (cancel && row.l <= +cancel) { voided++; continue; }
                if (op === "BUY" && pos[code]?.qty) continue;                 // 同票不重复开
                if (op === "BUY") {
                    if (row.l <= px && px <= row.h) {
                        const fp = row.o < px ? row.o : px;                    // 跳空低开按开盘
                        const fee = Math.max(fp * qty * FEE, MINFEE);
                        cash -= fp * qty + fee; pos[code] = { qty, cost: fp };
                        filled++;
                    } else voided++;
                } else if (op === "SELL" && pos[code]) {
                    if (row.h >= px) {
                        const fp = row.o > px ? row.o : px;
                        const fee = Math.max(fp * pos[code].qty * FEE, MINFEE) + fp * pos[code].qty * STAMP;
                        cash += fp * pos[code].qty - fee; delete pos[code]; filled++;
                    }
                }
            }
        }
        let mv = 0;
        for (const [code, p] of Object.entries(pos)) {
            const r = dayRow(code, d); mv += p.qty * (r ? r.c : p.cost);
        }
        navRows.push({ d, nav: cash + mv, posPct: mv / (cash + mv) });
    }
    const last = navRows[navRows.length - 1] || { nav: NAV0, posPct: 0 };
    if (WRITE_BOOKS && navRows.length) {
        const bf = path.join(DIR, "books", `${book}.json`);
        const bk = fs.existsSync(bf) ? JSON.parse(fs.readFileSync(bf, "utf8")) : { source: book, cash: NAV0, positions: {}, orders: [], trades: [], nav: [] };
        bk.nav = (bk.nav || []).filter((n) => !dates.includes(n.date)).concat(navRows.map((r) => ({
            date: r.d, cash: +(NAV0).toFixed(2), mv: +(r.nav - NAV0).toFixed(2), nav: +r.nav.toFixed(2), orders: 0, filled: 0, voided: 0 })));
        bk.cash = NAV0;  /* 回放态: 明早 reset_books 会清 9/28-30 行(设计内, report.html 已留档) */
        fs.writeFileSync(bf, JSON.stringify(bk, null, 1));
    }
    summary.push({ book, nav: last.nav, ret: (last.nav / NAV0 - 1) * 100, posPct: last.posPct, filled, voided, noQuote });
    report.push(`## ${book}`, "", "| 日期 | nav | 总仓% |", "|---|---|---|");
    navRows.forEach(r => report.push(`| ${r.d} | ${r.nav.toFixed(0)} | ${(r.posPct * 100).toFixed(0)}% |`));
    report.push(`成交 ${filled} / 废单(含未触发) ${voided} / 无日线 ${noQuote}`, "");
}
report.push("## 汇总", "", "| 账本 | 期末nav | 区间收益% | 期末总仓% | 成交 | 废单 | 无行情 |", "|---|---|---|---|---|---|---|");
summary.forEach(s => report.push(`| ${s.book} | ${s.nav.toFixed(0)} | ${s.ret.toFixed(2)} | ${(s.posPct * 100).toFixed(0)}% | ${s.filled} | ${s.voided} | ${s.noQuote} |`));
const out = path.join(DIR, "..", "..", "..", "results", "replay", `report_${FROM}_${TO}.md`);
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, report.join("\n") + "\n");
console.log(report.slice(-8).join("\n"));
console.log(`→ ${out}`);
