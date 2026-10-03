// matcher.mjs — 模拟盘撮合+账本(零 token 机械层, 2026-10-02)
// 设计文档=docs/TODO.md §E; 行格式规范=scripts/dfcf/paper/README.md
// 用法:
//   node scripts/dfcf/paper/matcher.mjs --init                      # 建6账本各10万
//   node scripts/dfcf/paper/matcher.mjs --import plans/<file>.md    # plans行→挂单(格式校验)
//   node scripts/dfcf/paper/matcher.mjs --once [--dry]              # 单轮撮合(腾讯快照, 保守成交)
//   node scripts/dfcf/paper/matcher.mjs --eod --date <yyyy-MM-dd>   # 日终: 废单→nav→state_digest
// 保守成交铁律: 买=现价≤挂价才成 / 卖=现价≥挂价才成; 09:25-09:30 竞价休止不撮合;
//   历史回放仅工程冒烟用(rules 从历史学出=训练集考试, 收益数字不看)
// 出口: 0=ok 1=用法/格式错 2=行情源失败 3=账本损坏
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const DIR = path.dirname(fileURLToPath(import.meta.url));   // 锚脚本自身, 不吃 cwd(10/3 教训: 错 cwd 会在幻影路径建账)
const BOOKS = path.join(DIR, "books");
const CONFIG = { initCash: 100000, feeRate: 0.00025, minFee: 5, stampTax: 0.0005, slippage: 0 }; // 费率=参数化占位, 待与用户券商实收对账
const SOURCES = ["A-taoge", "A-cb", "B-taoge", "B-cb", "C-taoge", "C-cb"];
const arg = (k) => { const i = process.argv.indexOf("--" + k); return i > -1 ? process.argv[i + 1] : null; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = () => sleep(600 * (0.75 + Math.random() * 0.5));

// ---- 账本 IO + 哈希链(审计红线: 状态变更必留痕) ----
const bookFile = (src) => path.join(BOOKS, `${src}.json`);
function loadBook(src) {
    const b = JSON.parse(fs.readFileSync(bookFile(src), "utf8"));
    if (!b.cash && b.cash !== 0) { console.error(`账本损坏 ${src}`); process.exit(3); }
    return b;
}
function saveBook(b, why) {
    const entry = { at: new Date().toISOString(), why, prev: b.lastHash || "GENESIS" };
    entry.hash = crypto.createHash("sha256").update(JSON.stringify({ c: b.cash, p: b.positions, n: b.trades.length, prev: entry.prev })).digest("hex").slice(0, 16);
    b.lastHash = entry.hash;
    (b.chain = b.chain || []).push(entry);
    fs.writeFileSync(bookFile(b.source), JSON.stringify(b, null, 1));
}
function initBooks() {
    fs.mkdirSync(BOOKS, { recursive: true });
    for (const src of SOURCES) {
        if (fs.existsSync(bookFile(src))) { console.log(`已存在跳过 ${src}`); continue; }
        saveBook({ source: src, cash: CONFIG.initCash, positions: {}, orders: [], trades: [], nav: [], chain: [] }, "init 10万");
        console.log(`建账 ${src}: ${CONFIG.initCash}`);
    }
}

// ---- plans 行解析: - HH:MM | source | BUY|SELL|CXL | code | price | qty | valid | note ----
const LINE = /^-\s*(\d{1,2}:\d{2})\s*\|\s*([ABC]-(?:taoge|cb))\s*\|\s*(BUY|SELL|CXL)\s*\|\s*(\d{6})\s*\|\s*([\d.]+|-)\s*\|\s*(\d+|-)\s*\|\s*(\S+)\s*\|\s*(.+)$/;
function importPlans(file) {
    const date = path.basename(file).match(/^(\d{4}-\d{2}-\d{2})/)?.[1];
    if (!date) { console.error("文件名须以 yyyy-MM-dd 开头"); process.exit(1); }
    let ok = 0, bad = 0, dup = 0;
    fs.readFileSync(file, "utf8").split("\n").forEach((l, i) => {
        l = l.trim();
        if (!l.startsWith("-")) return;
        const m = l.match(LINE);
        if (!m) { console.error(`坏行 ${i + 1}: ${l.slice(0, 60)}`); bad++; return; }
        // 幂等: 行内容哈希进账本, 重复 import 同文件/同行=跳过(Java 每分钟撮合前 import 的兜底)
        const h = crypto.createHash("sha1").update(l).digest("hex").slice(0, 12);
        const [, time, src] = m;
        const b = loadBook(src);
        b.imported = b.imported || [];
        if (b.imported.includes(h)) { dup++; return; }
        const [, , , side, code, price, qty, valid, note] = m;
        if (side === "CXL") {
            const o = b.orders.find((o) => o.code === code && o.status === "open");
            if (o) { o.status = "cxl"; o.note += ` | CXL@${time}: ${note}`; console.log(`撤单 ${src} ${code} #${o.id}`); }
            else console.log(`无单可撤 ${src} ${code}(忽略)`);
            b.imported.push(h); saveBook(b, `CXL ${code}`); ok++;
            return;
        }
        if (!(+price > 0) || !(+qty > 0)) { console.error(`坏价量 ${i + 1}`); bad++; return; }
        const id = `${date}-${src}-${String(b.orders.length + 1).padStart(3, "0")}`;
        b.orders.push({ id, date, time, side, code, price: +price, qty: +qty, valid, note, status: "open" });
        b.imported.push(h);
        saveBook(b, `挂单 ${side} ${code}@${price}x${qty}`);
        console.log(`挂单 ${src} #${id} ${side} ${code} @${price} x${qty}`);
        ok++;
    });
    console.log(`JSON:${JSON.stringify({ ok, bad, dup })}`);
    if (bad) process.exit(1);
}

// ---- 回放专用: 真实成交直接记账(不走撮合, C 线照抄 snapshots 用) + 期初种子 ----
const FILL = /^-\s*(\d{1,2}:\d{2})\s*\|\s*([ABC]-(?:taoge|cb))\s*\|\s*(BUY|SELL)\s*\|\s*(\d{6})\s*\|\s*([\d.]+)\s*\|\s*(\d+)\s*\|\s*([\d.]+)\s*\|\s*(.*)$/;
function importFills(file) {
    const date = path.basename(file).match(/^(\d{4}-\d{2}-\d{2})/)?.[1];
    if (!date) { console.error("文件名须以 yyyy-MM-dd 开头"); process.exit(1); }
    let ok = 0, bad = 0;
    fs.readFileSync(file, "utf8").split("\n").forEach((l, i) => {
        l = l.trim();
        if (!l.startsWith("-")) return;
        const m = l.match(FILL);
        if (!m) { console.error(`坏行 ${i + 1}: ${l.slice(0, 60)}`); bad++; return; }
        const [, time, src, side, code, price, qty, feeReal, note] = m;
        const b = loadBook(src);
        b.imported = b.imported || [];
        const h = crypto.createHash("sha1").update(l).digest("hex").slice(0, 12);
        if (b.imported.includes(h)) { console.log(`重复跳过 ${i + 1}`); return; }
        const amt = +price * +qty, f = +feeReal;
        if (side === "BUY") {
            if (b.cash < amt + f) { console.error(`现金不足拒 ${i + 1}`); bad++; return; }
            b.cash -= amt + f;
            const p = b.positions[code] || { qty: 0, cost: 0 };
            p.cost = (p.cost * p.qty + amt + f) / (p.qty + +qty); p.qty += +qty;
            b.positions[code] = p;
        } else {
            const p = b.positions[code];
            if (!p || p.qty < +qty) { console.error(`持仓不足拒 ${i + 1}(先 --seed 期初)`); bad++; return; }
            p.qty -= +qty; b.cash += amt - f;
            if (!p.qty) delete b.positions[code];
        }
        b.imported.push(h);
        b.trades.push({ id: `${date}-${src}-F${String(b.trades.length + 1).padStart(3, "0")}`, side, code, price: +price, qty: +qty, fee: f, why: `真实成交记账: ${note}` });
        saveBook(b, `真实成交 ${side} ${code}@${price}x${qty}`);
        console.log(`记账 ${src} ${side} ${code} @${price} x${qty} 费${f}`);
        ok++;
    });
    console.log(`JSON:${JSON.stringify({ ok, bad })}`);
    if (bad) process.exit(1);
}
function seed(src, code, qty, cost, cash) {
    const b = loadBook(src);
    b.cash = +cash;
    if (+qty > 0) b.positions[code] = { qty: +qty, cost: +cost };
    saveBook(b, `期初种子 ${code} ${qty}股@${cost} 现金${cash}(回放用, 成本=近似值 nav 不受影响)`);
    console.log(`种子 ${src}: 现金${cash} ${code} ${qty}股@${cost}`);
}
const prefix = (code) => (/^(60|68|11[0138]|5)/.test(code) ? "sh" : "sz");
async function snap(code) {
    const r = await fetch(`https://qt.gtimg.cn/q=${prefix(code)}${code}`, { headers: { Referer: "https://gu.qq.com/" } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const m = new TextDecoder("gbk").decode(await r.arrayBuffer()).match(/="([\s\S]*)"/);
    if (!m) throw new Error("腾讯返回为空");
    const f = m[1].split("~");
    return { code, name: f[1], last: +f[3], prevClose: +f[4], open: +f[5], high: +f[33], low: +f[34] };
}

// ---- 撮合 ----
const fee = (side, amt) => (side === "SELL" ? Math.max(CONFIG.minFee, amt * CONFIG.feeRate) + amt * CONFIG.stampTax : Math.max(CONFIG.minFee, amt * CONFIG.feeRate));
function fill(b, o, px, why, dry) {
    const amt = o.price * o.qty;
    const f = fee(o.side, amt);
    if (o.side === "BUY") {
        if (!dry && b.cash < amt + f) { o.status = "reject"; o.note += " | 现金不足"; return `现金不足拒单 ${o.id}`; }
        b.cash -= amt + f;
        const p = b.positions[o.code] || { qty: 0, cost: 0 };
        p.cost = (p.cost * p.qty + amt + f) / (p.qty + o.qty); p.qty += o.qty;
        b.positions[o.code] = p;
    } else {
        const p = b.positions[o.code];
        if (!p || p.qty < o.qty) { o.status = "reject"; o.note += " | 持仓不足"; return `持仓不足拒单 ${o.id}`; }
        p.qty -= o.qty; b.cash += amt - f;
        if (!p.qty) delete b.positions[o.code];
    }
    o.status = "filled"; o.fillPrice = px; o.fee = +f.toFixed(2); o.fillWhy = why;
    b.trades.push({ id: o.id, side: o.side, code: o.code, price: o.price, qty: o.qty, fee: o.fee, why });
    return `成交 ${b.source} #${o.id} ${o.side} ${o.code} @${o.price} x${o.qty} (现价${px}, ${why})`;
}
async function once(dry) {
    const hm = new Date().toTimeString().slice(0, 5);
    if (hm >= "09:25" && hm < "09:30") { console.log("竞价休止时段, 不撮合"); return; }
    const books = SOURCES.filter((s) => fs.existsSync(bookFile(s))).map(loadBook);
    const open = books.flatMap((b) => b.orders.filter((o) => o.status === "open").map((o) => ({ b, o })));
    if (!open.length) { console.log("无挂单"); return; }
    const codes = [...new Set(open.map((x) => x.o.code))];
    const px = {};
    for (const c of codes) { try { px[c] = await snap(c); } catch (e) { console.error(`快照失败 ${c}: ${e.message}`); } await jitter(); }
    if (!Object.keys(px).length) { console.error("行情源全灭"); process.exit(2); }
    for (const { b, o } of open) {
        const q = px[o.code];
        if (!q || !q.last) continue;
        let hit = null;
        if (o.side === "BUY" && q.last <= o.price) hit = `现价${q.last}≤挂${o.price}`;
        if (o.side === "SELL" && q.last >= o.price) hit = `现价${q.last}≥挂${o.price}`;
        if (!hit) continue;
        console.log(fill(b, o, q.last, hit, dry));
        if (!dry) saveBook(b, `成交 ${o.id}`);
    }
    console.log(`JSON:${JSON.stringify({ open: open.length, dry: !!dry })}`);
}

// ---- 日终: 废单→nav→state_digest ----
async function eod(date) {
    const books = SOURCES.filter((s) => fs.existsSync(bookFile(s))).map(loadBook);
    const codes = [...new Set(books.flatMap((b) => Object.keys(b.positions)))];
    const close = {};
    for (const c of codes) { try { close[c] = (await snap(c)).last; } catch { } await jitter(); }
    const digest = [`# state_digest ${date}（EOD 自动生成, 次日 facts 用）`, ""];
    for (const b of books) {
        let voided = 0, filled = 0;
        for (const o of b.orders.filter((o) => o.date === date)) {
            if (o.status === "open") { o.status = "void"; voided++; }
            if (o.status === "filled") filled++;
        }
        const mv = Object.entries(b.positions).reduce((s, [c, p]) => s + p.qty * (close[c] || p.cost), 0);
        const nav = +(b.cash + mv).toFixed(2);
        b.nav.push({ date, cash: +b.cash.toFixed(2), mv: +mv.toFixed(2), nav, orders: b.orders.filter((o) => o.date === date).length, filled, voided });
        saveBook(b, `EOD ${date} nav=${nav}`);
        fs.appendFileSync(path.join(DIR, `nav_${b.source}.csv`), `${date},${b.cash.toFixed(2)},${mv.toFixed(2)},${nav},${filled},${voided}\n`);
        const pos = Object.entries(b.positions).map(([c, p]) => `${c} ${p.qty}股@成本${p.cost.toFixed(2)}`).join("; ") || "空仓";
        digest.push(`## ${b.source}: nav ${nav} (现金${b.cash.toFixed(0)}) | 持仓: ${pos} | 当日 ${filled}成交/${voided}废单`);
    }
    fs.writeFileSync(path.join(DIR, "state_digest.md"), digest.join("\n") + "\n");
    console.log(`EOD ${date} 完成 → state_digest.md`);
    try {  // 尾挂人读视图(零 token, 失败不致命)
        const { execFileSync } = await import("node:child_process");
        execFileSync(process.execPath, [path.join(DIR, "report.mjs")], { stdio: "inherit" });
    } catch (e) { console.warn("WARN report.mjs 生成失败(不致命):", e.message); }
}

// ---- main ----
const MODE = process.argv.includes("--init") ? "init" : arg("import") ? "import" : arg("import-fills") ? "fills"
    : arg("seed") ? "seed" : process.argv.includes("--once") ? "once" : process.argv.includes("--eod") ? "eod" : null;
if (!MODE) { console.error("用法: --init | --import <file> | --import-fills <file> | --seed <src> <code> <qty> <cost> <cash> | --once [--dry] | --eod --date <d>"); process.exit(1); }
if (MODE === "init") initBooks();
else if (MODE === "import") importPlans(arg("import"));
else if (MODE === "fills") importFills(arg("import-fills"));
else if (MODE === "seed") { const v = process.argv.slice(process.argv.indexOf("--seed") + 1); if (v.length < 5) { console.error("--seed 需 5 参"); process.exit(1); } seed(...v); }
else if (MODE === "once") await once(process.argv.includes("--dry"));
else if (MODE === "eod") { const d = arg("date"); if (!d) { console.error("--eod 需 --date"); process.exit(1); } await eod(d); }
