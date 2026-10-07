// matcher.mjs — 模拟盘撮合+账本(零 token 机械层, 2026-10-02)
// 设计文档=docs/TODO.md §E; 行格式规范=scripts/dfcf/paper/README.md
// 用法:
//   node scripts/dfcf/paper/matcher.mjs --init                      # 建6账本各10万
//   node scripts/dfcf/paper/matcher.mjs --import plans/<file>.md    # plans行→挂单(格式校验)
//   node scripts/dfcf/paper/matcher.mjs --once [--dry]              # 单轮撮合(腾讯快照, 保守成交)
//   node scripts/dfcf/paper/matcher.mjs --eod --date <yyyy-MM-dd>   # 日终: 废单→nav→state_digest
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

const DIR = path.dirname(fileURLToPath(import.meta.url));   // 锚脚本自身, 不吃 cwd(10/3 教训: 错 cwd 会在幻影路径建账)
const BOOKS = path.join(DIR, "books");
const CONFIG = { initCash: 100000, feeRate: 0.00025, minFee: 5, stampTax: 0.0005, slippage: 0 }; // 费率=参数化占位, 待与用户券商实收对账
const SOURCES = [  // 10/7 两级制扩容: A=纯机械(3UP全链+cb+10导师盘前), B=机械+人工
    "A-taoge", "A-qushitiange", "A-lubenyuan", "A-cb", "A-liuyiqing", "A-lianghuaxiaohao", "A-a658", "A-bianbenling", "A-xingjianye", "A-daxingdaxingdadangxing", "A-gaogailvfuli", "A-xuanqiucaijing", "A-stzhilang", "A-chong5000w",
    "A-liuyiqing", "A-lianghuaxiaohao", "A-a658", "A-bianbenling", "A-xingjianye",
    "A-daxingdaxingdadangxing", "A-gaogailvfuli", "A-xuanqiucaijing", "A-stzhilang", "A-chong5000w",
    "B-taoge", "B-cb"];  // C 线 10/7 作废(并入 B=机械+人工), books/C-*.json 留档只读
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
const LINE = /^-\s*(\d{1,2}:\d{2})\s*\|\s*([ABC]-(?:taoge|cb))\s*\|\s*(BUY|SELL|CXL)\s*\|\s*(\d{6})\s*\|\s*([\d.]+|-)\s*\|\s*(\d+|-)\s*\|\s*(\S+)\s*\|\s*(?:(\d+(?:\.\d+)?(?:@\d+(?:\.\d+)?)?|-)\s*\|\s*)?(?:((?:cancel_below|stop_below)=[\d.]+(?:;(?:cancel_below|stop_below)=[\d.]+)*|-)\s*\|\s*)?(.+)$/;
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
        if (!(code in prevCloseCache)) {
            try { prevCloseCache[code] = (await snap(code)).prevClose; } catch (e) { prevCloseCache[code] = null; console.error(`前收取数失败 ${code}: ${e.message}`); }
            await jitter();
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
        p.qty -= o.qty; b.cash += amt - f;
        if (!p.qty) delete b.positions[o.code];
    }
    o.status = "filled"; o.fillPrice = price; o.fee = +f.toFixed(2); o.fillWhy = why;
    b.trades.push({ id: o.id, side: o.side, code: o.code, price, qty: o.qty, fee: o.fee, why });
    return `成交 ${b.source} #${o.id} ${o.side} ${o.code} @${price} x${o.qty} (现价${px}, ${why})`;
}
async function once(dry) {
    const hm = new Date().toTimeString().slice(0, 5);
    if (!inMatchWindow(hm)) {
        if (!dry) { console.log(`非撮合时段 ${hm}(窗=09:30-15:00, 竞价/盘后禁撮合), 不撮合`); return; }
        console.log(`WARN: 非撮合时段 ${hm}, dry 模式绕过时段闸(仅测试)`);
    }
    const books = SOURCES.filter((s) => fs.existsSync(bookFile(s))).map(loadBook);
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
async function eod(date) {
    const books = SOURCES.filter((s) => fs.existsSync(bookFile(s))).map(loadBook);
    const codes = [...new Set(books.flatMap((b) => Object.keys(b.positions)))];
    const close = {};
    for (const [c, q] of Object.entries(await snapMany(codes))) if (!q.error) close[c] = q.last;
    const digest = [`# state_digest ${date}（EOD 自动生成, 次日 facts 用）`, ""];
    for (const b of books) {
        let voided = 0, filled = 0, blocked = 0;
        for (const o of b.orders.filter((o) => o.date === date)) {
            if (o.status === "open") { o.status = "void"; voided++; }
            if (o.status === "filled") filled++;
            if (o.status === "reject" || o.status === "invalid") blocked++;
        }
        const mv = Object.entries(b.positions).reduce((s, [c, p]) => s + p.qty * (close[c] || p.cost), 0);
        const nav = +(b.cash + mv).toFixed(2);
        b.nav.push({ date, cash: +b.cash.toFixed(2), mv: +mv.toFixed(2), nav, orders: b.orders.filter((o) => o.date === date).length, filled, voided, blocked });
        saveBook(b, `EOD ${date} nav=${nav}`);
        fs.appendFileSync(path.join(DIR, `nav_${b.source}.csv`), `${date},${b.cash.toFixed(2)},${mv.toFixed(2)},${nav},${filled},${voided},${blocked}\n`);
        const pos = Object.entries(b.positions).map(([c, p]) => `${c} ${p.qty}股@成本${p.cost.toFixed(2)}`).join("; ") || "空仓";
        digest.push(`## ${b.source}: nav ${nav} (现金${b.cash.toFixed(0)}) | 持仓: ${pos} | 当日 ${filled}成交/${voided}废单/${blocked}哨兵拦截(一字/失效/价格锚)`);
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
else if (MODE === "import") await importPlans(arg("import"));
else if (MODE === "fills") importFills(arg("import-fills"));
else if (MODE === "seed") { const v = process.argv.slice(process.argv.indexOf("--seed") + 1); if (v.length < 5) { console.error("--seed 需 5 参"); process.exit(1); } seed(...v); }
else if (MODE === "once") await once(process.argv.includes("--dry"));
else if (MODE === "eod") { const d = arg("date"); if (!d) { console.error("--eod 需 --date"); process.exit(1); } await eod(d); }
