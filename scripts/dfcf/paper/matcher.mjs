// matcher.mjs — 模拟盘撮合+账本(零 token 机械层, 2026-10-02)
// 设计文档=docs/TODO.md §E; 行格式规范=scripts/dfcf/paper/README.md
// 用法:
//   node scripts/dfcf/paper/matcher.mjs --init                      # 建6账本各10万
//   node scripts/dfcf/paper/matcher.mjs --import plans/<file>.md    # plans行→挂单(格式校验)
//   node scripts/dfcf/paper/matcher.mjs --once [--dry]              # 单轮撮合(腾讯快照, 保守成交)
//   node scripts/dfcf/paper/matcher.mjs --eod --date <yyyy-MM-dd> [--restate]  # 日终: 废单→nav→state_digest(只追加, 重算须 --restate)
// 保守成交铁律: 买=现价≤挂价才成 / 卖=现价≥挂价才成
// 时段铁律(10/3): 撮合窗=09:30-15:00, 竞价(09:15-09:30)与盘后一律不撮合——竞价成交只走
//   --import-fills 人工核销, 且人工核销前必须过锚偏离检查(锚飞了=废单, 禁按开盘价机械成交)
// 锚偏离铁律(10/3): plans 行带结构化 anchor=链自报估算锚; 撮合前校 |前收-锚|与|现价-锚|,
//   两者都偏超 3%(或 anchor@pct 指定)=自动废单"需链重锚重裁", matcher 永不自动改价
// 拒落账铁律(10/4): import 时校 |挂单价-前收|/前收 > 板限(10cm→11%/20cm→21%/30cm→31%/转债→32%)
//   =锚编了, 直接拒落账(取数失败宁可拒); 与锚偏离闸两层分工: 进口查挂单价粗筛, 撮合查自报锚细校
//   历史回放仅工程冒烟用(rules 从历史学出=训练集考试, 收益数字不看)
// 出口: 0=ok 1=用法/格式错 2=行情源失败 3=账本损坏
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { snapMany, limitOf, isSealed } from "./snapshot.mjs"; // 多源快照+板限分档统一真源(C7-①/C10)

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));   // 锚脚本自身, 不吃 cwd(10/3 教训: 错 cwd 会在幻影路径建账)
// 10/10 as-of 回放(9/28-30 补跑语义修复): env PAPER_ROOT=沙盒数据根(books/nav/state_digest/report 全走沙盒, 实盘零接触);
// PAPER_ASOF=回放模式: 拒落账闸前收/EOD 收盘价改读日线归档(不碰实时源), --once 实时撮合禁用
const DIR = process.env.PAPER_ROOT ? path.resolve(process.env.PAPER_ROOT) : SCRIPT_DIR;
const ASOF = process.env.PAPER_ASOF || null;
const KDIR = path.join(SCRIPT_DIR, "..", "..", "..", "downloads", "quotes", "daily");
if (ASOF && !process.env.PAPER_ROOT) { console.error("PAPER_ASOF 须配 PAPER_ROOT 沙盒(防回放写实盘账本)"); process.exit(1); }
const BOOKS = path.join(DIR, "books");
const CONFIG = { initCash: 100000, feeRate: 0.00025, minFee: 5, stampTax: 0.0005, slippage: 0 }; // 费率=参数化占位, 待与用户券商实收对账
const SOURCES = [...new Set([  // 10/10 去重: 原名单 10 本重复列两次 → replay/eod/once 同账本载入两份副本各自存盘(后写覆盖, 成交统计翻倍)
    // 10/7 两级制扩容: A=纯机械(3UP全链+cb+10导师盘前), B=机械+人工
    "A-taoge", "A-qushitiange", "A-lubenyuan", "A-cb", "A-liuyiqing", "A-lianghuaxiaohao", "A-a658", "A-bianbenling", "A-xingjianye", "A-daxingdaxingdadangxing", "A-gaogailvfuli", "A-xuanqiucaijing", "A-stzhilang", "A-chong5000w", "A-control",  // A-control=对照组(10/11)
    "A-liuyiqing", "A-lianghuaxiaohao", "A-a658", "A-bianbenling", "A-xingjianye",
    "A-daxingdaxingdadangxing", "A-gaogailvfuli", "A-xuanqiucaijing", "A-stzhilang", "A-chong5000w",
    "B-taoge", "B-cb"])];  // C 线 10/7 作废(并入 B=机械+人工), books/C-*.json 留档只读
const arg = (k) => { const i = process.argv.indexOf("--" + k); return i > -1 ? process.argv[i + 1] : null; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms)); // 节流已内置 snapshot.mjs(snapMany gapMs)

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

// ---- plans 行解析: - HH:MM | source | BUY|SELL|CXL | code | price | qty | valid | [anchor[@pct] |] [cond |] note ----
// anchor 列(10/3 PC1)=链自报估算锚(可选, 兼容旧 8 字段行; 新单应必填): 数字 或 数字@允许偏离%(默认3) 或 "-"
// cond 列(C7-②)=cancel_below=<价>(跌破即撤) / stop_below=<价>(SELL 止损=跌破按市价出), `;` 可组合, `-`=无
// 两列都在时 anchor 在前 cond 在后(内容文法可区分, 正则天然分流不歧义)
const LINE = /^-\s*(\d{1,2}:\d{2})\s*\|\s*(A-\w+|B-\w+|C-\w+)\s*\|\s*(BUY|SELL|CXL|买|卖)\s*\|\s*(\d{6})\s*\|\s*([\d.]+|-)\s*\|\s*(\d+|-)\s*\|\s*(\S+)\s*\|\s*(?:(\d+(?:\.\d+)?(?:@\d+(?:\.\d+)?)?|-)\s*\|\s*)?(?:((?:cancel_below|stop_below)=[\d.]+(?:;(?:cancel_below|stop_below)=[\d.]+)*|-)\s*\|\s*)?(.+)$/;
function parseCond(s) {
    const o = {};
    if (!s || s === "-") return o;
    for (const p of s.split(";")) {
        const [k, v] = p.split("=");
        if ((k === "cancel_below" || k === "stop_below") && +v > 0) o[k] = +v;
        else throw new Error(`cond 坏片段: ${p}`);
    }
    return o;
}
// 拒落账闸(10/4 用户立法): 挂单价 vs 实际前收偏离超一个板限=锚编了 → import 直接拒, 不落账不进场
// 阈值=板限+1pt(10cm→11%/20cm→21%/30cm→31%/转债→32%): 给"挂跌停价排队出"留活路, 超板限的偏离没有合法场景
const boardLimit = (code) => (/^(30|68)/.test(code) ? 0.21 : /^(8|4|920)/.test(code) ? 0.31 : /^(11|12)/.test(code) ? 0.32 : 0.11);
async function importPlans(file) {
    const date = path.basename(file).match(/^(\d{4}-\d{2}-\d{2})/)?.[1];
    if (!date) { console.error("文件名须以 yyyy-MM-dd 开头"); process.exit(1); }
    let ok = 0, bad = 0, dup = 0;
    const prevCloseCache = {};  // 拒落账闸取数缓存(每 code 一次快照)
    // 10/11: 被拒行留痕(原仅 stderr+链侧 WARN=静默丢单, 如大兴大A 10/8 两张买单带 stop_below 全被拒无人知)
    //   → <数据根>/import_rejects.csv, 日报/报告据此显示"当日被拒挂单"
    const rejects = [], origErr = console.error;
    console.error = (...a) => { const m = a.join(" "); if (/^(坏|拒落账|前收取数失败)/.test(m)) rejects.push(m); origErr(...a); };
    process.on("exit", () => {
        console.error = origErr;
        if (!rejects.length) return;
        const src = path.basename(file).replace(/^\d{4}-\d{2}-\d{2}_/, "").replace(/\.md$/, "");
        const csv = path.join(DIR, "import_rejects.csv");
        const head = fs.existsSync(csv) ? "" : "date,source,file,reason\n";
        fs.appendFileSync(csv, head + rejects.map((m) => [date, src, path.basename(file), `"${m.replace(/"/g, "'")}"`].join(",")).join("\n") + "\n");
    });
    const lines = fs.readFileSync(file, "utf8").split("\n");
    for (let i = 0; i < lines.length; i++) {
        let l = lines[i].trim();
        if (!l.startsWith("-")) continue;
        const m = l.match(LINE);
        if (!m) { console.error(`坏行 ${i + 1}: ${l.slice(0, 60)}`); bad++; continue; }
        // 幂等: 行内容哈希进账本, 重复 import 同文件/同行=跳过(Java 每分钟撮合前 import 的兜底)
        const h = crypto.createHash("sha1").update(l).digest("hex").slice(0, 12);
        const [, time, src] = m;
        const b = loadBook(src);
        b.imported = b.imported || [];
        if (b.imported.includes(h)) { dup++; continue; }
        const [, , , side, code, price, qty, valid, anchorRaw, condRaw, note] = m;
        if (side === "CXL") {
            const o = b.orders.find((o) => o.code === code && o.status === "open");
            if (o) { o.status = "cxl"; o.note += ` | CXL@${time}: ${note}`; console.log(`撤单 ${src} ${code} #${o.id}`); }
            else console.log(`无单可撤 ${src} ${code}(忽略)`);
            b.imported.push(h); saveBook(b, `CXL ${code}`); ok++;
            continue;
        }
        if (!(+price > 0) || !(+qty > 0)) { console.error(`坏价量 ${i + 1}`); bad++; continue; }
        let anchor = null, anchorPct = 0.03;
        if (anchorRaw && anchorRaw !== "-") {
            const [a, p] = anchorRaw.split("@");
            anchor = +a;
            if (!(anchor > 0)) { console.error(`坏锚 ${i + 1}: ${anchorRaw}`); bad++; continue; }
            if (p !== undefined) { anchorPct = +p / 100; if (!(anchorPct > 0)) { console.error(`坏锚偏离 ${i + 1}: ${anchorRaw}`); bad++; continue; } }
        }
        // 拒落账闸: 挂单价 vs 前收偏离超板限 → 拒(取数失败=宁可拒, 防编锚漏网; 大亚案锚编 45% 的教训)
        // 10/8 修: snap/jitter 从未定义(原始 bug), 改用已导入的 snapMany + 直接延时
        // 10/8 晚二修: 盘后 API 空返回 → 回退日线 kline 取前收(否则首跑全零成交)
        if (!(code in prevCloseCache)) {
            // as-of / 补导历史日(10/11): 实时快照=未来数据(给的是今天的前收), 直接走下方日线回退取该日前收
            if (ASOF || date < new Date().toLocaleDateString("sv-SE")) prevCloseCache[code] = null;
            else try {
                // 10/11 修: snapMany 返回 {code: snap} 对象, 原按数组取 snaps[0] 恒 undefined → 实时前收永远取不到,
                //   全靠日线归档兜底(仅 ~750 只), 归档外的候选票挂单一律"前收不可用"被拒(10/8 起静默丢单)
                const sn = (await snapMany([code], 200))[code];
                prevCloseCache[code] = sn && !sn.error ? (sn.prevClose || sn.last || null) : null;
            } catch (e) { prevCloseCache[code] = null; }
            if (!(prevCloseCache[code] > 0)) {
                // 回退: 日线 kline 的前一日收盘 = 前收(10/11: 归档缺该票则先补档)
                try {
                    const dailyFile = path.join(KDIR, `${code}.json`);
                    if (!fs.existsSync(dailyFile)) {
                        const { archiveDaily } = await import("../../quotes/kline.mjs");
                        await archiveDaily([code], { dir: KDIR, gapMs: 200 });
                    }
                    if (fs.existsSync(dailyFile)) {
                        const kl = JSON.parse(fs.readFileSync(dailyFile, "utf8")).klines || [];
                        const prev = kl.filter(k => k.d < date).pop();
                        if (prev && prev.c > 0) {
                            prevCloseCache[code] = prev.c;
                            console.log(`前收回退日线: ${code}=${prev.c} (${prev.d})`);
                        }
                    }
                } catch (e2) { /* 日线也缺=真拒 */ }
            }
            if (!(prevCloseCache[code] > 0)) console.error(`前收取数失败 ${code}: API+日线均不可用`);
            await new Promise(r => setTimeout(r, 200));
        }
        const pc = prevCloseCache[code];
        if (!(pc > 0)) { console.error(`拒落账 ${i + 1}: ${code} 前收不可用, 无法过闸`); bad++; continue; }
        const dev = Math.abs(+price - pc) / pc;
        if (dev > boardLimit(code)) {
            console.error(`拒落账 ${i + 1}: ${code} 挂${price} vs 前收${pc} 偏${(dev * 100).toFixed(1)}%>板限闸${(boardLimit(code) * 100).toFixed(0)}% → 锚飞了, 需链重锚重裁`);
            bad++; continue;
        }
        let cond;
        try { cond = parseCond(condRaw); } catch (e) { console.error(`坏行 ${i + 1}: ${e.message}`); bad++; continue; }
        if (cond.stop_below && side !== "SELL") { console.error(`坏行 ${i + 1}: stop_below 仅 SELL 单可带`); bad++; continue; }
        // 防重复挂单闸(10/9 双成交案): 同 code 同向已有 open 单 → 先 CXL 旧单再挂新单
        // (链回炉重 emit 时新行哈希不同绕过行级幂等; plans 语义本就=同票新单取代旧单)
        const dupOpen = b.orders.find((o) => o.code === code && o.side === side && o.status === "open");
        if (dupOpen) {
            dupOpen.status = "cxl"; dupOpen.note += ` | import防重CXL(被同日新单取代)`;
            console.log(`防重撤单 ${src} ${code} #${dupOpen.id}(旧单 ${dupOpen.price}x${dupOpen.qty} → 新 ${price}x${qty})`);
        }
        const id = `${date}-${src}-${String(b.orders.length + 1).padStart(3, "0")}`;
        b.orders.push({ id, date, time, side, code, price: +price, qty: +qty, valid, anchor, anchorPct, cond, note, status: "open" });
        b.imported.push(h);
        saveBook(b, `挂单 ${side} ${code}@${price}x${qty}${cond.cancel_below ? ` cancel<${cond.cancel_below}` : ""}${cond.stop_below ? ` stop<${cond.stop_below}` : ""}`);
        console.log(`挂单 ${src} #${id} ${side} ${code} @${price} x${qty}`);
        ok++;
    }
    console.log(`JSON:${JSON.stringify({ ok, bad, dup })}`);
    if (bad) process.exit(1);
}

// ---- 回放专用: 真实成交直接记账(不走撮合, C 线照抄 snapshots 用) + 期初种子 ----
const FILL = /^s*(d{1,2}:d{2})s*|s*(A-w+|B-w+|C-w+)s*|s*(BUY|SELL)s*|s*(d{6})s*|s*([d.]+)s*|s*(d+)s*|s*([d.]+)s*|s*(.*)$/;
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
        if (time >= "09:15" && time < "09:30")
            console.warn(`WARN ${i + 1}行: 竞价时段成交=人工核销, 确认已过锚偏离检查(锚飞了=废单, 禁按开盘价机械成交——10/3 大亚教训)`);
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

// ---- 撮合 ----
// 撮合时段窗(10/3 加宽: 旧版只挡 09:25-09:30, 09:15-09:25 竞价挂单期与 15:00 盘后仍会成交=违规):
// 全域只允许 09:30-15:00 成交; 15:00 整点档保留=尾盘竞价(14:57-15:00)按收盘价成交是真实规则
const inMatchWindow = (hm) => hm >= "09:30" && hm <= "15:00";
const fee = (side, amt) => (side === "SELL" ? Math.max(CONFIG.minFee, amt * CONFIG.feeRate) + amt * CONFIG.stampTax : Math.max(CONFIG.minFee, amt * CONFIG.feeRate));
function fill(b, o, px, why, dry, atPrice) { // atPrice=实际记账价(默认挂价; 止损哨兵按快照市价)
    const price = atPrice ?? o.price;
    const amt = price * o.qty;
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
        // 10/11 补 T+1(A 股当日买入次日才可卖; 原先只校持仓量, 盘中子链可卖出当日上午刚买的票): 可卖=持仓−当日买入
        // 当日买入=同 code BUY 成交且 trade id 以挂单日期开头(撮合单 id=日期-源-序号, 人工记账 id=日期-源-F序号)
        // 10/11 修: 可转债(11/12 开头)是 T+0, 当日买当日可卖, 不吃 T+1 闸(原误伤 A-cb 土豆转债做 T)
        const boughtToday = /^1[12]/.test(o.code) ? 0
            : b.trades.filter((t) => t.side === "BUY" && t.code === o.code && String(t.id).startsWith(o.date)).reduce((s, t) => s + t.qty, 0);
        if (p.qty - boughtToday < o.qty) { o.status = "reject"; o.note += ` | T+1 可卖不足(持${p.qty}含当日买${boughtToday})`; return `T+1 拒卖 ${o.id}`; }
        p.qty -= o.qty; b.cash += amt - f;
        if (!p.qty) delete b.positions[o.code];
    }
    o.status = "filled"; o.fillPrice = price; o.fee = +f.toFixed(2); o.fillWhy = why;
    b.trades.push({ id: o.id, side: o.side, code: o.code, price, qty: o.qty, fee: o.fee, why });
    return `成交 ${b.source} #${o.id} ${o.side} ${o.code} @${price} x${o.qty} (现价${px}, ${why})`;
}
// ---- 回放(10/9 用户令: bug 日"假装记录进去") ----
// --replay --date yyyy-MM-dd: 对该日 open 单按日线高低价判定(买: 当日最低≤挂价=成交; 卖: 当日最高≥挂价=成交),
// 成交价=挂单价, note 打 replay 标。分钟级时序不可考, 报告口径=回放估算, 与实时撮合数字分列。
async function replay(date, dry) {
    const books = SOURCES.filter((s) => fs.existsSync(bookFile(s))).map(loadBook);
    const open = books.flatMap((b) => b.orders.filter((o) => o.status === "open" && o.date === date).map((o) => ({ b, o })))
        .sort((x, y) => (x.o.side === "SELL" ? 0 : 1) - (y.o.side === "SELL" ? 0 : 1) || String(x.o.time).localeCompare(String(y.o.time)));  // 10/11: 先卖后买(日内时序不可考, 卖出回笼资金在前)
    if (!open.length) { console.log(`${date} 无 open 单可回放`); return; }
    const kdir = KDIR;
    let filled = 0, missed = 0, noData = 0, blockedFill = 0;
    // 10/11: 缺日线先补档再撮合(原=跳过→EOD 作废=凭空少成交, 10/8 重建演练 6 单缺线)
    const needBar = [...new Set(open.map((x) => x.o.code))].filter((c) => {
        try { return !(JSON.parse(fs.readFileSync(path.join(kdir, `${c}.json`), "utf8")).klines || []).some((k) => k.d === date); } catch { return true; }
    });
    if (needBar.length) {
        try { const { archiveDaily } = await import("../../quotes/kline.mjs"); await archiveDaily(needBar, { dir: kdir, gapMs: 300 }); }
        catch (e) { console.warn(`回放补日线失败(缺线单留 open): ${e.message}`); }
    }
    for (const { b, o } of open) {
        let row = null, prev = null;
        try {
            const kl = JSON.parse(fs.readFileSync(path.join(kdir, `${o.code}.json`), "utf8")).klines || [];
            const i = kl.findIndex((k) => k.d === date);
            row = kl[i] || null; prev = i > 0 ? kl[i - 1] : null;
        } catch { /* 文件缺 */ }
        if (!row || !(row.l > 0) || !(row.h > 0)) { noData++; console.log(`回放缺线 ${o.code} ${date}(跳过, 单留 open)`); continue; }
        // 10/10 补两道日线可判定的闸(防回放过度乐观): ①一字涨停=现实买不到 ②开盘即破 cancel_below=成交前已撤
        const sealedUp = prev?.c > 0 && row.o === row.h && row.h === row.l && row.l === row.c && (row.c / prev.c - 1) * 100 >= limitOf(o.code);
        if (o.side === "BUY" && sealedUp) {
            o.status = "reject"; o.note += ` | 回放: 一字涨停拒买@${row.c}`;
            console.log(`回放拒买 ${b.source} #${o.id} ${o.code}: 一字涨停`);
            if (!dry) saveBook(b, `replay 一字拒买 ${o.id}`);
            continue;
        }
        if (o.side === "BUY" && o.cond?.cancel_below && row.o < o.cond.cancel_below) {
            o.status = "invalid"; o.note += ` | 回放: 开盘${row.o}<cancel_below ${o.cond.cancel_below} 失效`;
            console.log(`回放失效 ${b.source} #${o.id} ${o.code}: 开盘即破失效价`);
            if (!dry) saveBook(b, `replay 失效 ${o.id}`);
            continue;
        }
        // 10/11 回放对齐实盘撮合(原: 碰价即按挂价成交=买贵卖贱都按挂价记, 如 10/8 冲5000w 挂 22.54 买、当日区间 18.97-20.2 仍按 22.54 记):
        // ①板限区间闸(同 once 哨兵3): 买>前收×(1+板限)/卖<前收×(1−板限)=锚编了拒单
        // ②开盘即可成交侧: 买单 开≤挂 → 按开盘价成交, 但挂价>开×1.02=价格笼子废单; 卖单对称(开≥挂, 挂<开×0.98 废单)
        // ③盘中触价: 开盘未触、盘中 低≤挂(买)/高≥挂(卖) → 按挂价成交(实盘 once 按触价时的现价成交, 日线下以挂价近似)
        const lim = limitOf(o.code), pc = prev?.c;
        if (pc > 0 && ((o.side === "BUY" && o.price > pc * (1 + lim / 100 + 0.005)) || (o.side === "SELL" && o.price < pc * (1 - lim / 100 - 0.005)))) {
            o.status = "reject"; o.note += ` | 回放: 价格锚越界拒单(挂${o.price} 前收${pc} 板限${lim}%)`;
            console.log(`回放拒单 ${b.source} #${o.id} ${o.code}: 挂${o.price} 出当日板限区间(前收${pc})`);
            if (!dry) saveBook(b, `replay 越界拒单 ${o.id}`);
            continue;
        }
        const buy = o.side === "BUY";
        const atOpen = buy ? row.o <= o.price : row.o >= o.price;
        if (atOpen && (buy ? o.price > row.o * 1.02 : o.price < row.o * 0.98) && !/^(11|12)/.test(o.code)) {
            o.status = "reject"; o.note += ` | 回放: 价格笼子废单(挂${o.price} vs 开盘${row.o}±2%)`;
            console.log(`回放笼子废单 ${b.source} #${o.id} ${o.code}: 挂${o.price} 开盘${row.o}`);
            if (!dry) saveBook(b, `replay 笼子废单 ${o.id}`);
            continue;
        }
        const hit = atOpen || (buy ? row.l <= o.price : row.h >= o.price);
        if (hit) {
            const px = atOpen ? row.o : o.price;
            const msg = fill(b, o, px, `回放成交@${date} ${atOpen ? "开盘" : "盘中触价"}${px} [${row.l}-${row.h}]`, dry, px);
            console.log(msg + " [replay]");
            if (msg.startsWith("成交")) filled++; else blockedFill++;  // 现金不足/持仓不足/T+1 拒=不计成交
        } else {
            missed++;
            console.log(`回放未触 ${b.source} #${o.id} ${o.side} ${o.code} 挂${o.price} 当日[${row.l}-${row.h}]`);
        }
        if (!dry) saveBook(b, `replay ${date}`);
    }
    console.log(`回放 ${date}: 成交 ${filled} / 拒(资金/持仓/T+1) ${blockedFill} / 未触 ${missed} / 缺线 ${noData}${dry ? " (dry)" : ""}`);
}
async function once(dry) {
    if (ASOF) { console.error("as-of 回放模式禁用 --once(实时撮合), 用 --replay --date"); process.exit(1); }
    const hm = new Date().toTimeString().slice(0, 5);
    if (!inMatchWindow(hm)) {
        if (!dry) { console.log(`非撮合时段 ${hm}(窗=09:30-15:00, 竞价/盘后禁撮合), 不撮合`); return; }
        console.log(`WARN: 非撮合时段 ${hm}, dry 模式绕过时段闸(仅测试)`);
    }
    const books = SOURCES.filter((s) => fs.existsSync(bookFile(s))).map(loadBook);
    // 10/9 修: day 单跨日泄漏——open 单 date<今日 的 day 单当日已失效, 不再参与撮合, 顺手标 void
    // (10/9 实录: liuyiqing 10/8 的 22 张 open 单 10/9 继续被撮合并成交双份)
    const today = new Date().toISOString().slice(0, 10);
    for (const b of books) {
        for (const o of b.orders) {
            if (o.status === "open" && (o.valid || "day") === "day" && o.date !== today) {
                o.status = "void"; o.note += ` | 跨日过期作废(${o.date}的day单, ${today}不再撮合)`;
                if (!dry) saveBook(b, `跨日作废 ${o.id}`);
                console.log(`跨日作废 ${b.source} #${o.id} ${o.code}(${o.date}的day单)`);
            }
        }
    }
    const open = books.flatMap((b) => b.orders.filter((o) => o.status === "open").map((o) => ({ b, o })));
    if (!open.length) { console.log("无挂单"); return; }
    const codes = [...new Set(open.map((x) => x.o.code))];
    const px = await snapMany(codes); // 多源 fallback(snapshot.mjs), 单票失败={code,error}不挡其他票
    if (!Object.values(px).some((q) => q && !q.error)) { console.error("行情源全灭"); process.exit(2); }
    for (const { b, o } of open) {
        const q = px[o.code];
        if (!q || q.error || !q.last) continue;
        const cond = o.cond || {};
        // 哨兵0(10/3 C10 执行层双保险): 顶一字涨停拒买 —— LLM 无视 facts 🔒 标注也不许成交(9/28 新华传媒四连一字废单案)
        if (o.side === "BUY" && isSealed(q) && q.pct > 0) {
            o.status = "reject"; o.note += ` | 一字封死拒买@${q.last}`;
            if (!dry) saveBook(b, `拒买一字 ${o.id}`);
            console.log(`拒买 ${b.source} #${o.id} ${o.code}: 一字封死(${q.last})`);
            continue;
        }
        // 哨兵1(C7-② cancel_below): 失效条件=跌破即撤, 形态已坏不许再接刀
        if (cond.cancel_below && q.last < cond.cancel_below) {
            o.status = "invalid"; o.note += ` | 失效撤单@${q.last}<${cond.cancel_below}`;
            if (!dry) saveBook(b, `失效撤单 ${o.id}`);
            console.log(`失效撤单 ${b.source} #${o.id} ${o.code}: 现价${q.last}破${cond.cancel_below}`);
            continue;
        }
        // 哨兵2(C7-② stop_below): 止损哨兵=SELL 挂单跌破止损价, 不等挂价按快照市价出
        if (o.side === "SELL" && cond.stop_below && q.last < cond.stop_below) {
            console.log(fill(b, o, q.last, `止损哨兵: 现价${q.last}<stop${cond.stop_below}`, dry, q.last));
            if (!dry) saveBook(b, `止损 ${o.id}`);
            continue;
        }
        // 哨兵3(C7-①第四道防线): 挂价穿出当日理论价格区间(前收±板限)的"会立即成交侧"=编造价嫌疑拒单
        //   只拒 BUY>板上界 / SELL<板下界(两处都会瞬间成交且价格离谱); BUY 挂超低/SELL 挂超高=合法等单留给 EOD 废单率度量
        const lim = limitOf(o.code);
        const up = q.prevClose * (1 + lim / 100 + 0.005), dn = q.prevClose * (1 - lim / 100 - 0.005);
        if ((o.side === "BUY" && o.price > up) || (o.side === "SELL" && o.price < dn)) {
            o.status = "reject"; o.note += ` | 价格锚越界拒单(挂${o.price}出界[${dn.toFixed(2)},${up.toFixed(2)}])`;
            if (!dry) saveBook(b, `价格锚拒单 ${o.id}`);
            console.log(`拒单 ${b.source} #${o.id} ${o.code}: 挂${o.price}超当日理论区间[${dn.toFixed(2)},${up.toFixed(2)}]`);
            continue;
        }
        // 锚偏离守卫(10/3): 链自报估算锚 vs 真实前收+现价, 双偏超阈=锚编了/市场变了 → 自动废单,
        // 绝不按挂单价机械成交(10/3 大亚教训: 锚14.00 vs 实际前收7.6 偏45%, 失效条款只是注释没拦住)。
        // 双条件都偏才废: 防大涨日盘中子链以现价为锚被前收误杀; matcher 只废单不改价, 重锚=链重裁
        if (o.anchor && q.prevClose > 0) {
            const devPC = Math.abs(q.prevClose - o.anchor) / o.anchor;
            const devLast = Math.abs(q.last - o.anchor) / o.anchor;
            if (devPC > o.anchorPct && devLast > o.anchorPct) {
                o.status = "void";
                o.note += ` | 锚偏离作废: 锚${o.anchor} vs 前收${q.prevClose}/现价${q.last} 偏${(Math.min(devPC, devLast) * 100).toFixed(1)}%>${(o.anchorPct * 100).toFixed(0)}% → 需链重锚重裁`;
                console.log(`锚偏离作废 ${b.source} #${o.id} ${o.code}: 锚${o.anchor} 前收${q.prevClose} 现价${q.last}`);
                if (!dry) saveBook(b, `锚偏离作废 ${o.id}`);
                continue;
            }
        }
        let hit = null;
        if (o.side === "BUY" && q.last <= o.price) hit = `现价${q.last}≤挂${o.price}`;
        if (o.side === "SELL" && q.last >= o.price) hit = `现价${q.last}≥挂${o.price}`;
        if (!hit) continue;
        // 价格笼子(10/4 用户令): 连续竞价限价申报 买≤基准价102%/卖≥98%, 超出=废单(主板 2023 注册制起同科创/创业)。
        // 建模=触发撮合瞬间申报(条件单触发时券商才报单), 基准价用快照现价代理(无五档); 转债(11/12)笼子规则
        // 不同(深市±10%)暂不套用。已知偏差: 1 分钟快照粒度下快跌中的合法回踩单可能被误废 → 计入废单率。
        if (!/^(11|12)/.test(o.code)) {
            const cageOk = o.side === "BUY" ? o.price <= q.last * 1.02 : o.price >= q.last * 0.98;
            if (!cageOk) {
                o.status = "reject"; o.note += ` | 价格笼子废单(挂${o.price} vs 现价${q.last}±2%笼)`;
                if (!dry) saveBook(b, `笼子废单 ${o.id}`);
                console.log(`笼子废单 ${b.source} #${o.id} ${o.code}: 挂${o.price}出±2%笼(现价${q.last})`);
                continue;
            }
        }
        console.log(fill(b, o, q.last, hit, dry));
        if (!dry) saveBook(b, `成交 ${o.id}`);
    }
    console.log(`JSON:${JSON.stringify({ open: open.length, dry: !!dry })}`);
}

// ---- 日终: 废单→nav→state_digest ----
// 10/11 两修(用户认可"只追加"): ①补算历史日期(date≠今天)收盘价读日线归档该日收——原先一律 snapMany 实时快照,
//   10/9 晚补算 10/8 时用了 10/9 价, 10/8 与 10/9 nav 全员相同的根因 ②nav 只追加: 某账本该日已有 nav=跳过(exit 0,
//   调度重跑安全); 确需重算(如 EOD 后才补 replay)加 --restate, 旧值进 b.navRestated 留痕不涂改
async function eod(date) {
    const restate = process.argv.includes("--restate");
    const live = !ASOF && date === new Date().toLocaleDateString("sv-SE");  // 本地日期(toISOString=UTC, 08:00 前会差一天)
    // 10/11: 补算历史日跳过"建账晚于该日"的账本(哈希链首条=init 时刻)——否则新账本(如 A-control)被补出不存在的平值点;
    // as-of 沙盒例外(沙盒账本今天建, 模拟的就是历史)
    const born = (b) => String(b.chain?.[0]?.at || "").slice(0, 10);
    const books = SOURCES.filter((s) => fs.existsSync(bookFile(s))).map(loadBook)
        .filter((b) => ASOF || live || !born(b) || born(b) <= date);
    const todo = books.filter((b) => restate || !b.nav.some((n) => n.date === date));
    if (!todo.length) { console.log(`EOD ${date}: 全部账本已有当日 nav, 只追加不覆盖 → 跳过(确需重算加 --restate)`); return; }
    const codes = [...new Set(todo.flatMap((b) => Object.keys(b.positions)))];
    const close = {};
    if (!live) {  // 历史日/as-of: 收盘价=日线归档当日收; 缺线先补档, 仍缺=按成本估并告警
        const bar = (c) => { try { return (JSON.parse(fs.readFileSync(path.join(KDIR, `${c}.json`), "utf8")).klines || []).find((k) => k.d === date); } catch { return null; } };
        const miss = codes.filter((c) => !(bar(c)?.c > 0));
        if (miss.length) {
            const { archiveDaily } = await import("../../quotes/kline.mjs");
            await archiveDaily(miss, { dir: KDIR, gapMs: 300 });
        }
        for (const c of codes) { const r = bar(c); if (r?.c > 0) close[c] = r.c; else console.warn(`EOD 缺线 ${c} ${date}(按成本估)`); }
    } else {
        for (const [c, q] of Object.entries(await snapMany(codes))) if (!q.error) close[c] = q.last;
        // 10/11: 实时取价失败的票回退日线当日收盘(补档后再查), 仍缺才按成本估且告警(原=静默按成本, nav 失真无痕)
        const miss = codes.filter((c) => !(close[c] > 0));
        if (miss.length) {
            try { const { archiveDaily } = await import("../../quotes/kline.mjs"); await archiveDaily(miss, { dir: KDIR, gapMs: 300 }); } catch { }
            for (const c of miss) {
                try { const r = (JSON.parse(fs.readFileSync(path.join(KDIR, `${c}.json`), "utf8")).klines || []).find((k) => k.d === date); if (r?.c > 0) { close[c] = r.c; console.warn(`EOD 实时价缺 ${c}, 回退日线收盘 ${r.c}`); continue; } } catch { }
                console.warn(`⚠ EOD ${c} 实时价与日线均缺, 按成本估值(nav 可能失真)`);
            }
        }
    }
    const digest = [`# state_digest ${date}（EOD 自动生成, 次日 facts 用）`, ""];
    for (const b of books) {
        const old = b.nav.find((n) => n.date === date);
        if (!todo.includes(b)) {  // 已结算账本: 不动, digest 照抄已发布值
            const pos = Object.entries(b.positions).map(([c, p]) => `${c} ${p.qty}股@成本${p.cost.toFixed(2)}`).join("; ") || "空仓";
            digest.push(`## ${b.source}: nav ${old.nav} (现金${old.cash.toFixed(0)}) | 持仓: ${pos} | 当日 ${old.filled}成交/${old.voided}废单/${old.blocked}哨兵拦截(一字/失效/价格锚)`);
            continue;
        }
        let voided = 0, filled = 0, blocked = 0;
        for (const o of b.orders.filter((o) => o.date === date)) {
            if (o.status === "open") { o.status = "void"; voided++; }
            if (o.status === "filled") filled++;
            if (o.status === "reject" || o.status === "invalid") blocked++;
        }
        const mv = Object.entries(b.positions).reduce((s, [c, p]) => s + p.qty * (close[c] || p.cost), 0);
        const nav = +(b.cash + mv).toFixed(2);
        if (old) (b.navRestated = b.navRestated || []).push({ ...old, restatedAt: new Date().toISOString() });
        b.nav = b.nav.filter((n) => n.date !== date);
        b.nav.push({ date, cash: +b.cash.toFixed(2), mv: +mv.toFixed(2), nav, orders: b.orders.filter((o) => o.date === date).length, filled, voided, blocked, ...(old ? { restated: true } : {}) });
        b.nav.sort((x, y) => x.date.localeCompare(y.date));
        saveBook(b, `EOD ${date} nav=${nav}${old ? ` (restate, 旧值${old.nav}留痕 navRestated)` : ""}`);
        // nav csv 落 nav/ 子目录(10/8 用户令归拢), 同日行替换=幂等(旧 appendFileSync 双跑重复行修复)
        const NAV_DIR = path.join(DIR, "nav");
        fs.mkdirSync(NAV_DIR, { recursive: true });
        const navCsv = path.join(NAV_DIR, `nav_${b.source}.csv`);
        const row = `${date},${b.cash.toFixed(2)},${mv.toFixed(2)},${nav},${filled},${voided},${blocked}`;
        const prev = fs.existsSync(navCsv) ? fs.readFileSync(navCsv, "utf8").split("\n").filter((l) => l.trim()) : [];
        fs.writeFileSync(navCsv, [...prev.filter((l) => !l.startsWith(date + ",")), row].sort().join("\n") + "\n");  // 排序: 补算历史日不落末尾
        const pos = Object.entries(b.positions).map(([c, p]) => `${c} ${p.qty}股@成本${p.cost.toFixed(2)}`).join("; ") || "空仓";
        digest.push(`## ${b.source}: nav ${nav} (现金${b.cash.toFixed(0)}) | 持仓: ${pos} | 当日 ${filled}成交/${voided}废单/${blocked}哨兵拦截(一字/失效/价格锚)`);
    }
    fs.writeFileSync(path.join(DIR, "state_digest.md"), digest.join("\n") + "\n");
    console.log(`EOD ${date} 完成 → state_digest.md`);
    try {  // 尾挂人读视图(零 token, 失败不致命)
        const { execFileSync } = await import("node:child_process");
        // 10/11: 先算前一交易日拟人度(导师 tzzb 真值当晚才抓全, 故 T 日 EOD 算 T-1), 报告读 similarity.json
        // 前一交易日=nav 日期里 < date 且有交易日 md 的最大者(账本有节假日 EOD 空跑占位行, 如 10/1-10/7, 不能算交易日)
        const isTd = (d) => fs.existsSync(path.join(SCRIPT_DIR, "..", "..", "..", "md", `${d.slice(0, 4)}S${Math.ceil(+d.slice(5, 7) / 3)}`, `${d}.md`));
        const prevD = [...new Set(books.flatMap((b) => b.nav.map((n) => n.date)))].filter((d) => d < date && isTd(d)).sort().pop();
        if (prevD && !ASOF) {
            try { execFileSync(process.execPath, [path.join(SCRIPT_DIR, "similarity.mjs"), "--date", prevD.replaceAll("-", "")], { stdio: "inherit", env: process.env, windowsHide: true }); }
            catch (e) { console.warn("WARN similarity 失败(不致命):", e.message); }
        }
        execFileSync(process.execPath, [path.join(SCRIPT_DIR, "report.mjs")], { stdio: "inherit" });
        // 10/11 用户令: 实盘 EOD 后推微信日报(沙盒/补算历史日不推)
        if (live) {
            try { execFileSync(process.execPath, [path.join(SCRIPT_DIR, "daily_digest.mjs"), "--date", date, "--send"], { stdio: "inherit", env: process.env, windowsHide: true }); }
            catch (e) { console.warn("WARN 微信日报失败(不致命):", e.message); }
        }
    } catch (e) { console.warn("WARN report.mjs 生成失败(不致命):", e.message); }
}

// ---- main ----
const MODE = process.argv.includes("--init") ? "init" : arg("import") ? "import" : arg("import-fills") ? "fills"
    : arg("seed") ? "seed" : process.argv.includes("--once") ? "once" : process.argv.includes("--replay") ? "replay" : process.argv.includes("--eod") ? "eod" : null;
if (!MODE) { console.error("用法: --init | --import <file> | --import-fills <file> | --seed <src> <code> <qty> <cost> <cash> | --once [--dry] | --replay --date <d> [--dry] | --eod --date <d> [--restate]"); process.exit(1); }
// 10/11 账本互斥锁: 读-改-写整段持锁(原 --once 载入账本→等行情→存盘期间, 链的 --import 存盘被覆盖=丢单);
// 持锁进程死亡即回收(process.kill(pid,0) 只探活不杀), 等锁上限 180s
const LOCK = path.join(BOOKS, ".matcher.lock");
{
    fs.mkdirSync(BOOKS, { recursive: true });
    const alive = (pid) => { try { process.kill(pid, 0); return true; } catch { return false; } };
    let waited = 0;
    for (;;) {
        try { fs.writeFileSync(LOCK, String(process.pid), { flag: "wx" }); break; }
        catch {
            const holder = +(() => { try { return fs.readFileSync(LOCK, "utf8"); } catch { return 0; } })();
            if (holder && !alive(holder)) { try { fs.unlinkSync(LOCK); } catch { } continue; }
            if (waited >= 180) { console.error(`账本锁被 pid ${holder} 占用超 180s, 放弃(${MODE})`); process.exit(4); }
            await sleep(1000); waited++;
        }
    }
    process.on("exit", () => { try { if (fs.readFileSync(LOCK, "utf8") === String(process.pid)) fs.unlinkSync(LOCK); } catch { } });
}
if (MODE === "init") initBooks();
else if (MODE === "import") await importPlans(arg("import"));
else if (MODE === "fills") importFills(arg("import-fills"));
else if (MODE === "seed") { const v = process.argv.slice(process.argv.indexOf("--seed") + 1); if (v.length < 5) { console.error("--seed 需 5 参"); process.exit(1); } seed(...v); }
else if (MODE === "once") await once(process.argv.includes("--dry"));
else if (MODE === "replay") { const d = arg("date"); if (!d) { console.error("--replay 需 --date yyyy-MM-dd"); process.exit(1); } await replay(d, process.argv.includes("--dry")); }
else if (MODE === "eod") { const d = arg("date"); if (!d) { console.error("--eod 需 --date"); process.exit(1); } await eod(d); }
