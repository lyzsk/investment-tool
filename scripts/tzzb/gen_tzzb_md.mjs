// gen_tzzb_md.mjs — tzzb 账本 → md `#### <name>` 小节硬数据层(零 token)
// v1 2026-10-02 建 | v2 2026-10-06 整体重构(用户令: 补丁摞补丁推倒重来)
//
// 设计原则(用户立法沉淀):
//   ①md=当天腿的忠实记录: 日内做T(当天买+卖)=完整行; 跨日卖出=单行(买腿在历史 md, 不拼接);
//     当天买入未卖=买腿行+(持仓)。禁期货术语("未平/平仓")。
//   ②仓位标签用推算持仓(aftPositionPercent 恒 0 已实证失真, 6/12 A658 满仓被标空仓=大 bug 教训):
//     有腿日=收盘持仓只数; 无腿日=asset 变化(现金不动, 持仓会波动)交叉验证。
//   ③汇总三计数(日内/跨日/新建仓), 不硬凑全口径胜率。
//   ④期初存粮(账本开始记录前已有持仓): 首见卖出无库存=如实标"期初存粮", 不截 0 掩盖。
//
// 三层结构: load(原料) → derive(派生: FIFO 配对+持仓滚动+日分类, 一次算好) → render(纯查表渲染)
// 用法:
//   node scripts/gen_tzzb_md.mjs --ledger <id> --date 2026-09-30 [--write]   # 单日(stdout/--write)
//   node scripts/gen_tzzb_md.mjs --ledger <id> --all --write                 # 全历史批量
// 挂载: 整小节覆盖, 【推测】段全保留(从首个含【推测】行到小节末, 去尾空行防叠加)
// 幂等: 无状态文件——硬数据覆盖即幂等, 【推测】有无即推测层状态(内容即状态)
import fs from "fs";
import path from "path";

const arg = (k) => { const i = process.argv.indexOf("--" + k); return i > -1 ? process.argv[i + 1] : null; };
const LEDGER = arg("ledger") || "buchitudou0";
const DATE = arg("date");
const WRITE = process.argv.includes("--write");
const ALL = process.argv.includes("--all");
if (!ALL && !DATE) { console.error("用法: node scripts/gen_tzzb_md.mjs --ledger <id> (--date yyyy-MM-dd | --all) [--write]"); process.exit(1); }

// ---------- load: 原料 ----------
const DIR = path.resolve("downloads/tzzb", LEDGER);
if (!fs.existsSync(DIR)) { console.error(`${DIR} 不存在, 先跑 fetch_tzzb.mjs --ledger ${LEDGER}`); process.exit(1); }

const canon = (s) => s.replace(/^#+\s*/, "").replace(/\s+/g, "").toLowerCase();
const LEDGERS = JSON.parse(fs.readFileSync("scripts/tzzb/tzzb_ledgers.json", "utf8"));
const NAME = (LEDGERS.find((l) => l.ledger === LEDGER) || {}).name || LEDGER;
// 负样本闸(10/7 用户立法): kind=neg 不进 md——语料留 downloads/, 反例规则走 gen_tzzb_negstats.py(待建)+05 风控
if ((LEDGERS.find((l) => l.ledger === LEDGER) || {}).kind === "neg") {
    console.error(`${LEDGER}(${NAME}) 是负样本: 不产 md 硬数据层(10/7 立法); 语料在 downloads/tzzb/${LEDGER}/`);
    process.exit(1);
}
function sectionHeading() {
    const tpl = fs.readFileSync("inv-stock/src/main/resources/templates/stock-template.md", "utf8").split("\n");
    const zi = tpl.findIndex((l) => /^#{3} /.test(l) && canon(l) === canon("同花顺投资账本"));
    for (let i = zi + 1; i > 0 && i < tpl.length; i++) {
        if (/^#{2,3} /.test(tpl[i])) break;
        if (/^#{4} /.test(tpl[i]) && canon(tpl[i]) === canon(NAME)) return tpl[i].trim();
    }
    return "#### " + NAME;
}
const HEADING = sectionHeading();

const legsByDate = {};          // day -> [腿](去重, 时序)
{
    const seen = new Set();
    for (const f of fs.readdirSync(DIR).filter((f) => f.startsWith("change_bs_"))) {
        const list = JSON.parse(fs.readFileSync(path.join(DIR, f), "utf8"))?.ex_data?.change_list || [];
        for (const t of list) {
            const day = (t.trans_date || "").slice(0, 10);
            if (!day) continue;
            const k = `${t.trans_date}|${t.op}|${t.stock_code}`;
            if (seen.has(k)) continue;
            seen.add(k);
            (legsByDate[day] ||= []).push(t);
        }
    }
    for (const d of Object.keys(legsByDate)) legsByDate[d].sort((a, b) => (a.trans_date < b.trans_date ? -1 : 1));
}
const navByDay = {};            // day -> {cur, prev}
{
    const nl = JSON.parse(fs.readFileSync(path.join(DIR, "nav_daily.json"), "utf8"))?.ex_data?.index_list || [];
    nl.forEach((x, i) => {
        const d = x.date;
        navByDay[`${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`] = { cur: +x.index, prev: i > 0 ? +nl[i - 1].index : null };
    });
}
const summDates = {};           // 分页截断哨兵原料(10/2 立法: 脚本数数, LLM 不许算)
for (const f of fs.readdirSync(DIR).filter((f) => f.startsWith("position_change_p"))) {
    const list = JSON.parse(fs.readFileSync(path.join(DIR, f), "utf8"))?.ex_data?.change_list || [];
    for (const t of list) {
        const d = (t.trans_date || "").slice(0, 10);
        if (d) (summDates[t.stock_code] ||= new Set()).add(d);
    }
}

// ---------- derive: FIFO 配对 + 持仓滚动 + 日分类(一次算好, render 只查表) ----------
const dayClass = {};            // day -> {intraday:[{buy,sell}], crossday:[sell腿], sells:[sell腿], buys:[buy腿]}
const holdByDay = {};           // day -> Map(code -> qty) 收盘持仓
const seeds = [];               // 期初存粮: 首见超卖 {code, name, qty}
{
    const openq = new Map();    // code -> [未配对买腿](FIFO 队列)
    const pos = new Map();      // code -> 净持仓(可负=超卖欠定)
    const seq = [...new Set([...Object.keys(legsByDate), ...Object.keys(navByDay)])].sort();
    for (const d of seq) {
        const cls = { intraday: [], crossday: [], sells: [], buys: [] };
        for (const t of legsByDate[d] || []) {
            if (t.op === "1") {
                (openq.get(t.stock_code) || openq.set(t.stock_code, []).get(t.stock_code)).push(t);
                pos.set(t.stock_code, (pos.get(t.stock_code) || 0) + +t.trans_count);
                cls.buys.push(t);
            } else {
                const buy = (openq.get(t.stock_code) || []).shift() || null;
                pos.set(t.stock_code, (pos.get(t.stock_code) || 0) - +t.trans_count);
                const q = pos.get(t.stock_code);
                if (q < 0 && !seeds.some((s) => s.code === t.stock_code))
                    seeds.push({ code: t.stock_code, name: t.stock_name, qty: -q, day: d });  // 首见超卖=期初存粮(记首见日)
                if (buy && buy.trans_date.slice(0, 10) === d) cls.intraday.push({ buy, sell: t });
                else cls.crossday.push(t);
                cls.sells.push(t);
            }
        }
        dayClass[d] = cls;
        holdByDay[d] = new Map(pos);
    }
}

// ---------- render: 纯渲染(只读 derive 结果) ----------
const codeName = new Map();   // code -> 名称(腿数据反查, 持仓明细用)
for (const d of Object.keys(legsByDate)) for (const lg of legsByDate[d]) codeName.set(lg.stock_code, lg.stock_name);
// 真实历史持仓(day_position_by_share, 10/6 破译): {date8: {list:[{code,name,position_percent,rate}]}}——百分比取代推算股数(1074股类残差禁现)
let dayPos = null;
{ const f = path.join(DIR, "day_positions.json"); if (fs.existsSync(f)) { try { dayPos = JSON.parse(fs.readFileSync(f, "utf8")); } catch {} } }
function realPos(day) {
    if (!dayPos) return null;
    const rec = dayPos[day.replaceAll("-", "")];
    return rec && rec.list?.length ? rec.list : null;
}
const isBond = (c) => /^(11[0138]|12[378])/.test(c || "");
const unit = (c) => (isBond(c) ? "张" : "股");
const fmtPct = (x) => (x >= 0 ? "+" : "") + (x * 100).toFixed(2) + "%";
const fmtDur = (ms) => {
    const s = Math.round(ms / 1000);
    if (s < 3600) return `${Math.floor(s / 60)}分${String(s % 60).padStart(2, "0")}秒`;
    return `${Math.floor(s / 3600)}时${Math.floor((s % 3600) / 60)}分`;
};
const fmtWan = (amt) => (amt / 10000).toFixed(1) + "万";

// 国债逆回购=现金管理非持仓。语义(10/7 用户破译): 正值=当日借出存续; **负值=T-1 借出今日资金回笼的清算镜像**
// (实证: 星见野 4/13 +100.0% → 4/14 -99.7% 完美镜像对)。展示保留 API 原值(不去符号), 但 sum 总仓位排除(镜像会污染)。
const isRepo = (x) => /^(204|1318)/.test(x.code) || /GC0|R-00/.test(x.name || "");

function positionTag(day, hasLegs) {
    // ①真实历史持仓(day_positions.json)——存在即权威; 逆回购单列不计入持仓(负值日=T+1清算污染 sum, 10/7 用户令加总百分比)
    const real = realPos(day);
    if (real) {
        const repos = real.filter(isRepo), holds = real.filter((x) => !isRepo(x) && +x.position_percent > 0);
        const sum = holds.reduce((a, x) => a + +x.position_percent, 0);
        const detail = holds.map((x) => `${x.name} ${(100 * +x.position_percent).toFixed(1)}%`).join(" · ");
        const repoTxt = repos.length ? ` · 另逆回购 ${repos.map((x) => (100 * +x.position_percent).toFixed(1) + "%").join("/")} 现金管理(负=T-1借出回笼)` : "";
        if (hasLegs) return holds.length ? `持仓过夜(${holds.length} 支 ${(100 * sum).toFixed(1)}%: ${detail}${repoTxt})` : `空仓过夜(${repoTxt.slice(3) || "仅逆回购"})`;
        return holds.length || repos.length ? `无操作(持仓过夜 ${(100 * sum).toFixed(1)}%: ${detail || "仅逆回购"}${repoTxt})` : "无操作(空仓)";
    }
    // ②fallback: 推算持仓只数(无股数无百分比——期初存粮场景推算值不可靠, 只报只数)
    const held = holdByDay[day] ? [...holdByDay[day].entries()].filter(([, q]) => q > 0) : [];
    if (hasLegs) return held.length ? `持仓过夜(${held.length} 支, 明细待核)` : "空仓过夜";
    const a = navByDay[day];
    const chg = a && a.prev ? Math.abs(a.cur / a.prev - 1) : 0;
    return (chg > 0.001 || held.length) ? "无操作(持仓过夜)" : "无操作(空仓)";
}

function renderDay(day) {
    const legs = legsByDate[day] || [];
    const nav = navByDay[day];
    if (legs.length === 0 && !nav) return null;
    const navLine = nav ? `净值 ${nav.cur.toFixed(4)}` + (nav.prev ? ` · 日收益 ${fmtPct(nav.cur / nav.prev - 1)}` : "") : "";
    if (legs.length === 0) return navLine ? `${navLine} · ${positionTag(day, false)}` : null;

    const cls = dayClass[day];
    const rows = [];
    // ①日内做T(当天买+当天卖): 完整行带盈亏
    for (const { buy, sell } of cls.intraday) {
        const pct = +sell.trans_price / +buy.trans_price - 1;
        const dur = new Date(sell.trans_date) - new Date(buy.trans_date);
        rows.push(`- ${sell.stock_name}(${sell.stock_code}): ${buy.trans_date.slice(11)} 买 ${buy.trans_count}${unit(sell.stock_code)}@${(+buy.trans_price).toFixed(4)} → ${sell.trans_date.slice(11)} 卖 ${sell.trans_count}${unit(sell.stock_code)}@${(+sell.trans_price).toFixed(4)} **${fmtPct(pct)} · 持仓 ${fmtDur(dur)} · 名义 ${fmtWan(+buy.trans_amount)}**`);
    }
    // ②跨日卖出: 单行记录(买腿在历史 md, 用户立法不拼接)
    for (const sell of cls.crossday) {
        rows.push(`- ${sell.stock_name}(${sell.stock_code}): ${sell.trans_date.slice(11)} 卖 ${sell.trans_count}${unit(sell.stock_code)}@${(+sell.trans_price).toFixed(4)}`);
    }
    // ③当天买入: 净持仓为正的(持仓), 被同日卖出抵消的不标(做T行已表达)
    for (const buy of cls.buys) {
        const heldNow = (holdByDay[day].get(buy.stock_code) || 0) > 0;
        const soldSameDay = cls.sells.some((s) => s.stock_code === buy.stock_code);
        if (heldNow || !soldSameDay) {
            rows.push(`- ${buy.stock_name}(${buy.stock_code}): ${buy.trans_date.slice(11)} 买 ${buy.trans_count}${unit(buy.stock_code)}@${(+buy.trans_price).toFixed(4)}${heldNow ? " (持仓)" : ""}`);
        }
    }
    rows.sort((a, b) => ((a.match(/(\d{2}:\d{2}:\d{2})/)?.[1] || "").localeCompare(b.match(/(\d{2}:\d{2}:\d{2})/)?.[1] || "")));

    // 汇总三计数
    const wins = cls.intraday.filter((t) => +t.sell.trans_price > +t.buy.trans_price).length;
    const pcts = cls.intraday.map((t) => +t.sell.trans_price / +t.buy.trans_price - 1);
    const avgPct = pcts.length ? pcts.reduce((a, b) => a + b, 0) / pcts.length : 0;
    const notional = cls.intraday.reduce((a, t) => a + +t.buy.trans_amount, 0);
    const openCnt = rows.filter((r) => r.includes("(持仓)")).length;
    const parts = [];
    if (cls.intraday.length) parts.push(`日内 round-trip ${cls.intraday.length} 笔(胜率 ${wins}/${cls.intraday.length}, 平均 ${fmtPct(avgPct)}, 名义 ${fmtWan(notional)})`);
    if (cls.crossday.length) parts.push(`跨日卖出 ${cls.crossday.length} 笔`);
    if (openCnt) parts.push(`新建仓 ${openCnt} 笔(持仓)`);

    const out = [`${navLine} · ${positionTag(day, true)}`, ""];
    const CAP = 10;
    out.push(...rows.slice(0, CAP));
    if (rows.length > CAP) out.push(`- …另有 ${rows.length - CAP} 笔(明细略, 见 tzzb_record bs_leg)`);
    out.push("", `汇总: ` + (parts.length ? parts.join(" · ") : `${legs.length} 笔`));
    // 分页截断哨兵(10/2 立法: 确定性标记)
    const legStocks = new Set(legs.map((t) => t.stock_code));
    for (const [code, dates] of Object.entries(summDates)) {
        if (dates.has(day) && !legStocks.has(code)) out.push(`⚠️ 数据校验: ${code} 日汇总有交易但逐笔腿缺失(分页截断), 当日汇总口径可能不全`);
    }
    // 期初存粮披露(仅该票首次出现卖出的日子)
    const daySeeds = seeds.filter((s) => s.day === day);  // 仅首见日披露(后续卖出日不重复报)
    if (daySeeds.length) out.push(`⚠️ 期初存粮: ${daySeeds.map((s) => `${s.name}(${s.code}) 账本开始记录前已持有(首见卖出超出现有买入, 欠定 ${s.qty}${unit(s.code)})`).join("; ")}`);
    return out.join("\n");
}

// ---------- mount: 整小节覆盖, 【推测】全段保留 ----------
function mount(day, body) {
    const [y, m] = day.split("-");
    const md = path.join("md", `${y}S${Math.ceil(+m / 3)}`, `${day}.md`);
    if (!fs.existsSync(md)) return "无md";
    const lines = fs.readFileSync(md, "utf8").split("\n");
    const hi = lines.findIndex((l) => /^#{4} /.test(l) && canon(l) === canon(HEADING));
    if (hi === -1) return "无小节";
    let end = lines.length;
    for (let i = hi + 1; i < lines.length; i++) {
        if (/^#{2,4} /.test(lines[i])) { end = i; break; }
    }
    const secLines = lines.slice(hi + 1, end);
    const specIdx = secLines.findIndex((l) => l.includes("【推测】"));
    const carry = specIdx >= 0 ? secLines.slice(specIdx) : [];
    while (carry.length && carry[carry.length - 1].trim() === "") carry.pop();  // 去尾空行(防叠加)
    const block = [HEADING, "", ...body.split("\n")];
    if (carry.length) block.push("", ...carry, "");  // 尾留恰好 1 空行接下节标题
    else block.push("");
    lines.splice(hi, end - hi, ...block);
    fs.writeFileSync(md, lines.join("\n"));
    return carry.length ? `覆盖(保${carry.length}行推测)` : "覆盖";
}

// ---------- main ----------
const days = ALL
    ? [...new Set([...Object.keys(legsByDate), ...Object.keys(navByDay)])].sort()
    : [DATE];
const tally = {};
for (const day of days) {
    const body = renderDay(day);
    if (body === null) { tally["无数据跳过"] = (tally["无数据跳过"] || 0) + 1; continue; }
    if (!WRITE) { console.log((ALL ? `\n=== ${day} ===\n` : "") + body); continue; }
    const r = mount(day, body);
    tally[r] = (tally[r] || 0) + 1;
}
if (WRITE || ALL) console.error(`[gen_tzzb_md] ${LEDGER}(${HEADING}): ` + Object.entries(tally).map(([k, v]) => `${k}=${v}`).join(" "));
