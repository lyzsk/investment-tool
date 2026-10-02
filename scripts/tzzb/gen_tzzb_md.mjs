// gen_tzzb_md.mjs — 生成 md `#### <name>` 小节的硬数据层(零 token, 2026-10-02)
// 用法:
//   node scripts/gen_tzzb_md.mjs --ledger bchitudou0 --date 2026-09-30          # stdout 打印
//   node scripts/gen_tzzb_md.mjs --ledger bchitudou0 --date 2026-09-30 --write  # 挂载进 md(整小节覆盖)
//   node scripts/gen_tzzb_md.mjs --ledger bchitudou0 --all --write              # 全历史日批量回填
// 输入: downloads/tzzb/<ledger>/change_bs_*.json(逐笔腿) + nav_daily.json(净值)
// 挂载: md/<year>S<quarter>/<date>.md 的 #### <name> 小节(名字以模板为准, 空格不敏感匹配)
//       覆盖时保留旧小节里的【推测】行(LLM 推测层是另一作者, 硬数据重跑不冲掉)
// 口径: ①腿去重键=(trans_date|op|stock_code)(change_bs 分页服务端重复, 同 fetch 早停同款)
//       ②同(日,标的)内买卖腿按时间 FIFO 配对成 round-trip; 买未配对=持有过夜(他风格日内归零, 属异常要显式)
//       ③明细封顶 10 笔, 超出并入汇总行; 空仓日只出净值行
//       ④推测层(为什么选这债/为什么这时点)不在这里——归 tzzb-sum skill LLM 合成, 逐条标【推测】
// 幂等: 无状态文件——硬数据层覆盖即幂等, 【推测】行有无即推测层状态(内容即状态, 2026-10-02 用户拍板口径)
import fs from "fs";
import path from "path";

const arg = (k) => { const i = process.argv.indexOf("--" + k); return i > -1 ? process.argv[i + 1] : null; };
const LEDGER = arg("ledger") || "bchitudou0";
const DATE = arg("date");
const WRITE = process.argv.includes("--write");
const ALL = process.argv.includes("--all");
if (!ALL && !DATE) { console.error("用法: node scripts/gen_tzzb_md.mjs --ledger <id> (--date yyyy-MM-dd | --all) [--write]"); process.exit(1); }

const DIR = path.resolve("downloads/tzzb", LEDGER);
if (!fs.existsSync(DIR)) { console.error(`${DIR} 不存在, 先跑 fetch_tzzb.mjs --ledger ${LEDGER}`); process.exit(1); }

// ledger → md 小节名: 名字以模板 #### 标题为准(用户可能带空格改模板), canon=去空格小写匹配
const canon = (s) => s.replace(/^#+\s*/, "").replace(/\s+/g, "").toLowerCase();
const LEDGERS = JSON.parse(fs.readFileSync("scripts/tzzb_ledgers.json", "utf8"));
const NAME = (LEDGERS.find((l) => l.ledger === LEDGER) || {}).name || LEDGER;
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

// 转债代码段(沪深): 110/111/113/118(沪) 123/127/128(深) → 单位"张", 其余"股"
const isBond = (c) => /^(11[0138]|12[378])/.test(c || "");
const unit = (c) => (isBond(c) ? "张" : "股");
const fmtPct = (x) => (x >= 0 ? "+" : "") + (x * 100).toFixed(2) + "%";
const fmtDur = (ms) => {
    const s = Math.round(ms / 1000);
    if (s < 3600) return `${Math.floor(s / 60)}分${String(s % 60).padStart(2, "0")}秒`;
    return `${Math.floor(s / 3600)}时${Math.floor((s % 3600) / 60)}分`;
};
const fmtWan = (amt) => (amt / 10000).toFixed(1) + "万";

// ---- 原料一次性载入: 腿按日分组(去重), 净值按日索引 ----
const legsByDate = {};
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
const navList = JSON.parse(fs.readFileSync(path.join(DIR, "nav_daily.json"), "utf8"))?.ex_data?.index_list || [];
const navByDay = {};
navList.forEach((x, i) => {
    const d = x.date;
    navByDay[`${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`] = { cur: +x.index, prev: i > 0 ? +navList[i - 1].index : null };
});

// 日汇总(机械交叉核对原料): 每标的有交易的日期集合 —— 分页截断自动感知
// (2026-10-02 立法: ⚠️ 标记由脚本确定性产出, LLM 不许数数; 10/2 全量核查 51 标的 0 缺日,
//  "75 条顶格"实测=分页服务端重复返回第 1 页(冗余非丢失), 本标记常态休眠但保留哨兵)
const summDates = {};
for (const f of fs.readdirSync(DIR).filter((f) => f.startsWith("position_change_p"))) {
    const list = JSON.parse(fs.readFileSync(path.join(DIR, f), "utf8"))?.ex_data?.change_list || [];
    for (const t of list) {
        const d = (t.trans_date || "").slice(0, 10);
        if (d) (summDates[t.stock_code] ||= new Set()).add(d);
    }
}

// ---- 生成某日的硬数据层正文; 无腿且无净值 = null(跳过, 不污染 md) ----
function genForDate(day) {
    const legs = (legsByDate[day] || []).sort((a, b) => (a.trans_date < b.trans_date ? -1 : 1));
    const nav = navByDay[day];
    if (legs.length === 0 && !nav) return null;
    const navLine = nav ? `净值 ${nav.cur.toFixed(4)}` + (nav.prev ? ` · 日收益 ${fmtPct(nav.cur / nav.prev - 1)}` : "") : "";
    if (legs.length === 0) return navLine ? `${navLine} · 无操作(空仓观望)` : null;

    // FIFO 配对 round-trip
    const trips = [];
    const openBuys = {};
    for (const t of legs) {
        if (t.op === "1") (openBuys[t.stock_code] ||= []).push(t);
        else if (t.op === "2") {
            const q = openBuys[t.stock_code] || [];
            trips.push({ code: t.stock_code, name: t.stock_name, buy: q.length ? q.shift() : null, sell: t });
        }
    }
    const overnight = Object.values(openBuys).flat();

    const rows = trips.map(({ code, name, buy, sell }) => {
        const bp = buy ? +buy.trans_price : null, sp = +sell.trans_price;
        const pct = bp ? sp / bp - 1 : null;
        const dur = buy ? new Date(sell.trans_date) - new Date(buy.trans_date) : null;
        const u = unit(code);
        const buyTxt = buy ? `${buy.trans_date.slice(11)} 买 ${buy.trans_count}${u}@${bp.toFixed(4)}` : "(买腿缺)";
        const stat = [
            pct != null ? `**${fmtPct(pct)}` : null,
            dur != null ? `持仓 ${fmtDur(dur)}` : null,
            buy ? `名义 ${fmtWan(+buy.trans_amount)}` + "**" : null,
        ].filter(Boolean).join(" · ");
        return `- ${name}(${code}): ${buyTxt} → ${sell.trans_date.slice(11)} 卖 ${sell.trans_count}${u}@${sp.toFixed(4)} ${stat}`;
    });

    const wins = trips.filter((t) => t.buy && +t.sell.trans_price > +t.buy.trans_price).length;
    const durs = trips.filter((t) => t.buy).map((t) => new Date(t.sell.trans_date) - new Date(t.buy.trans_date));
    const avgDur = durs.length ? durs.reduce((a, b) => a + b, 0) / durs.length : 0;
    const pcts = trips.filter((t) => t.buy).map((t) => +t.sell.trans_price / +t.buy.trans_price - 1);
    const avgPct = pcts.length ? pcts.reduce((a, b) => a + b, 0) / pcts.length : 0;
    const notional = trips.reduce((a, t) => a + (t.buy ? +t.buy.trans_amount : 0), 0);
    const lastAftZero = legs[legs.length - 1].aftPositionPercent === 0;

    const out = [];
    out.push(navLine + (lastAftZero ? " · 空仓过夜" : " · 持仓过夜"));
    out.push("");
    const CAP = 10;
    out.push(...rows.slice(0, CAP));
    if (rows.length > CAP) out.push(`- …另有 ${rows.length - CAP} 笔(明细略, 见 tzzb_record bs_leg)`);
    out.push("");
    out.push(`汇总: ${trips.length} 笔 round-trip · 胜率 ${wins}/${trips.length} · 平均单笔 ${fmtPct(avgPct)} · 平均持仓 ${fmtDur(avgDur)} · 名义本金 ${fmtWan(notional)}`);
    // 分页截断哨兵(确定性标记, 推测层只许读不许算): 日汇总有交易但当日腿缺失才报
    // (10/2 全量核查 51 标的 0 缺日常态休眠; pre/aftPositionPercent 已实证为日级字段且恒 0, 无腿级仓位可校验)
    const legStocks = new Set(legs.map((t) => t.stock_code));
    for (const [code, dates] of Object.entries(summDates)) {
        if (dates.has(day) && !legStocks.has(code)) out.push(`⚠️ 数据校验: ${code} 日汇总有交易但逐笔腿缺失(分页截断), 当日汇总口径可能不全`);
    }
    for (const t of overnight) {
        out.push(`⚠️ ${t.stock_name}(${t.stock_code}) 买 ${t.trans_count}${unit(t.stock_code)}@${(+t.trans_price).toFixed(4)} 未平(持有过夜)`);
    }
    return out.join("\n");
}

// ---- 挂载: 整小节覆盖, 保留旧【推测】行 ----
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
    const carry = lines.slice(hi + 1, end).filter((l) => l.includes("【推测】"));
    const block = [HEADING, "", ...body.split("\n")];
    if (carry.length) block.push("", ...carry);
    block.push("");
    lines.splice(hi, end - hi, ...block);
    fs.writeFileSync(md, lines.join("\n"));
    return carry.length ? `覆盖(保${carry.length}条推测)` : "覆盖";
}

const days = ALL
    ? [...new Set([...Object.keys(legsByDate), ...Object.keys(navByDay)])].sort()
    : [DATE];

const tally = {};
for (const day of days) {
    const body = genForDate(day);
    if (body === null) { tally["无数据跳过"] = (tally["无数据跳过"] || 0) + 1; continue; }
    if (!WRITE) { console.log((ALL ? `\n=== ${day} ===\n` : "") + body); continue; }
    const r = mount(day, body);
    tally[r] = (tally[r] || 0) + 1;
}
if (WRITE || ALL) console.error(`[gen_tzzb_md] ${LEDGER}(${HEADING}): ` + Object.entries(tally).map(([k, v]) => `${k}=${v}`).join(" "));
