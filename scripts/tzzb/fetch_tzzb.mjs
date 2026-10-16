// fetch_tzzb.mjs — 投资账本抓取(多账本版, 2026-10-01 由单账本改造)
// 用法: node scripts/fetch_tzzb.mjs [--ledger <id>]
//   默认跑 scripts/tzzb_ledgers.json 全部账本; --ledger 只跑指定账本
//   (Java CbTzzbFetchHandler 小时级兜底: 当日净值已入库的账本短路跳过, 缺的账本逐个 --ledger 补抓)
// 产物: downloads/tzzb/<ledger>/position_change_p<n>.json / nav_daily.json / month.json / position.json
//       downloads/tzzb/<ledger>/change_bs_<code>_p<n>.json (逐笔买卖腿, 每标的全历史分页)
//       downloads/tzzb/<ledger>/state.json(lastFetch/tradeRows/lastNavDate/bsLegs, 供对账)
// 出口: 0=正常(含无新增); 2=凭证失效(stderr 带 ledger id); 5=IP 被同花顺封禁(Nginx forbidden, 10/14 加; 全部账本都会失败, 调用方应停止本轮); 1=其他失败
// 约定: 摘要行以 "JSON:" 前缀输出供 Java handler 解析(照 fetch_bilibili.mjs --list 先例)
// 10/15 三层降级(TODO A11): A=页面内 XHR 代发(全量端点) → B=纯被动监听(原生 CDP Network 域记录账本页自己请求的返回体, 不在页面执行 JS;
//   拿得到 profit_rate/position_change 第1页/day_position 最新日/day_calendar, 与 A 同结构直接落同名文件) → C=读渲染后页面文字
//   (DOM.getOuterHTML, 同一次页面加载, 不额外请求; 解析出 每日收益率/当日持仓/交易记录 → layerC_*.json, 字段名同 A, 不覆盖 A 层文件)。
//   每层失败记 failKind(BLOCKED/AUTH/RATE_LIMIT/NO_DATA/UNAVAILABLE/PARSE) 进 JSON 摘要 fails[]; 三层全败且含 BLOCKED 才写熔断 exit 5。
//   --layer A|B|C 强制只走某层(冒烟用); --root <dir> 换产物根目录(冒烟用, 不碰正式数据)。
// 每日快照: 每天首次运行把 downloads/tzzb(除 _guard)打包成 downloads/_snapshots/tzzb_<日>.zip, 保留 30 天(PowerShell 隐藏窗口)
import fs from "fs";
import path from "path";
import { BrowserTransport } from "./browser/browser_transport.mjs";
import { openEdge, capturePage } from "./browser/cdp_passive.mjs";
import { parseLayerC } from "./browser/layer_c_parse.mjs";
import { spawnSync } from "child_process";
const VIA_BROWSER = !process.argv.includes("--direct");
let TRANSPORT = null;
process.on("exit", () => { try { TRANSPORT?.ed?.kill(); } catch { /* ignore */ } });

const BASE = "https://capital.hexin.cn/caishen_httpserver/direct/caishen_fund/community_share/v1";
const ROOT = path.resolve(process.argv.includes("--root") ? process.argv[process.argv.indexOf("--root") + 1] : "downloads/tzzb");
const FORCE_LAYER = process.argv.includes("--layer") ? process.argv[process.argv.indexOf("--layer") + 1] : null;
class LayerFail extends Error { constructor(kind, msg) { super(msg); this.kind = kind; } }
const kindOf = (e) => e?.kind || (/JSON|Unexpected token/.test(String(e?.message)) ? "PARSE" : "UNAVAILABLE");
const LEDGERS = JSON.parse(fs.readFileSync(path.resolve("scripts/tzzb/tzzb_ledgers.json"), "utf8"));  // 10/2 迁入 scripts/tzzb/(cwd=项目根)
const PER_PAGE = 50;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// 10/14 防封加固(同花顺 15:13 封 IP 后): 节流 ≤0.5 次/秒(记忆: 批量≤0.5 次/秒) + 抖动; 熔断标记; 每日请求预算; 单实例锁; 请求计数落盘
const jitter = () => sleep(2000 * (0.75 + Math.random() * 0.5));
const GUARD = path.join(ROOT, "_guard");
const BAN = path.join(GUARD, "ban.json");           // 被封时写入; 存在且未过冷却期 → 不发任何请求, 直接 exit 5
const BAN_COOL_H = 6;                                 // 冷却 6 小时后才允许 1 次探测(探测仍封=重新计时)
const today = new Date().toLocaleDateString("sv-SE");
// 单日请求上限(增量后一整轮约 250 次, 9 轮/天也远低于此)。10/15 加当日追加额度文件 _guard/budget_extra_<日>.json {"extra":N,"why":"..."}:
// 新导师首次全量抓这类一次性大消耗把当天额度吃光(10/15 两新人全量后 15:10/19:10 正常轮全被拦), 只对当天有效, 次日自动失效
const DAY_BUDGET = 2000 + (() => { try { return Math.max(0, +JSON.parse(fs.readFileSync(path.join(ROOT, "_guard", `budget_extra_${today}.json`), "utf8")).extra || 0); } catch { return 0; } })();
const CNT = path.join(GUARD, `requests_${today}.json`);
fs.mkdirSync(GUARD, { recursive: true });
let reqCount = (() => { try { return JSON.parse(fs.readFileSync(CNT, "utf8")).n || 0; } catch { return 0; } })();
const bump = () => { reqCount++; if (reqCount % 10 === 0) fs.writeFileSync(CNT, JSON.stringify({ n: reqCount })); };
process.on("exit", () => { try { fs.writeFileSync(CNT, JSON.stringify({ n: reqCount })); } catch { /* ignore */ } });
function banned() {
    try {
        const b = JSON.parse(fs.readFileSync(BAN, "utf8")), ageH = (Date.now() - Date.parse(b.at)) / 36e5;
        return ageH < BAN_COOL_H ? { ...b, ageH } : null;
    } catch { return null; }
}
const LEDGER_FILE = path.resolve("scripts/tzzb/tzzb_ledgers.json");
function saveLedgers() { fs.writeFileSync(LEDGER_FILE, JSON.stringify(LEDGERS, null, 2)); }
// 候选视图: _ranks/<比赛key>.json 榜单里同名(去空格)的人 → (比赛key, user_key); 再各 1 次 profit_rate_by_share 取最新净值日
async function bestView(cfg, curNav) {
    const nm = String(cfg.name || "").replace(/\s/g, "");
    const cands = [];
    for (const f of fs.existsSync(path.join(ROOT, "_ranks")) ? fs.readdirSync(path.join(ROOT, "_ranks")).filter((x) => x.endsWith(".json")) : []) {
        try {
            const j = JSON.parse(fs.readFileSync(path.join(ROOT, "_ranks", f), "utf8"));
            for (const r of j.rows || [])
                if (String(r.user_name || "").replace(/\s/g, "") === nm && !(j.match_key === cfg.key && String(r.user_key) === String(cfg.user_key)))
                    cands.push({ key: j.match_key, user_key: String(r.user_key), enter: String(r.enter_date || "9999") });
        } catch { /* 坏文件跳过 */ }
    }
    for (const v of cfg.extra_views || []) cands.push(v);   // 用户手贴的个人分享(key+user_key)也可放这里
    const uniq = [...new Map(cands.map((c) => [`${c.key}|${c.user_key}`, c])).values()];
    let best = null;
    for (const c of uniq) {
        if (reqCount >= DAY_BUDGET) break;
        try {
            bump();
            let r;
            if (VIA_BROWSER) {
                if (!TRANSPORT) TRANSPORT = await BrowserTransport.open({ key: c.key, user_key: c.user_key });
                const x = await TRANSPORT.get(`${BASE}/profit_rate_by_share?key=${c.key}&user_key=${c.user_key}`);
                r = { status: x.status, text: async () => x.text };
            } else {
                r = await fetch(`${BASE}/profit_rate_by_share?key=${c.key}&user_key=${c.user_key}`, { headers: { "User-Agent": "Mozilla/5.0" } });
            }
            const body = await r.text();
            if (/nginx forbidden/i.test(body)) throw new LayerFail("BLOCKED", `bestView 探测 403 Nginx forbidden ledger=${cfg.ledger}`);   // 10/15: 不再直接熔断, 交给 A→B→C 降级
            const d = (JSON.parse(body)?.ex_data?.index_list || []).reduce((m, x) => (x.date > m ? x.date : m), "");
            console.log(`  候选视图 ${c.key}/${c.user_key}: 最新 ${d || "无"}`);
            if (d && (!best || d > best.date || (d === best.date && (c.enter || "9999") < (best.enter || "9999")))) best = { ...c, date: d };   // 同样最新时选入场最早的(历史最长)
        } catch (e) { if (e instanceof LayerFail) throw e; console.log(`  候选视图 ${c.key}/${c.user_key}: 失败 ${e.message}`); }
        await jitter();
    }
    return best && best.date > curNav ? best : best;
}

// 10/15 调仓流水增量(只给 pc_incremental 账本用, 如 antoo): 流水按时间倒序, 新行只出现在最前面 →
//   新增 n = 服务端 max_count − 本地行数; 拉 ceil((n+50)/50) 页, 校验 fresh[n..n+50) 与本地前 50 行逐行一致(=没有补录/删改历史行),
//   一致才拼成 新n行+本地旧行, 按 50 行/页重写 position_change_p*.json(信封照 p1); 任何不一致/本地不完整/7 天没全量 → 返回 null 走全量
const pcKey = (t) => [t.trans_date, t.stock_code, t.op, t.buy_sell, t.trans_price, t.prePositionPercent, t.aftPositionPercent].join("|");
async function pcIncremental(out, call) {
    const files = fs.readdirSync(out).filter((x) => /^position_change_p\d+\.json$/.test(x)).sort((a, b) => +a.match(/\d+/)[0] - +b.match(/\d+/)[0]);
    if (!files.length) return null;
    let st = {};
    try { st = JSON.parse(fs.readFileSync(path.join(out, "state.json"), "utf8")); } catch { return null; }
    if (!st.pcFullAt || Date.now() - Date.parse(st.pcFullAt) > 7 * 864e5) return null;   // 每周至少一次全量对账
    const old = [];
    for (const f of files) old.push(...(JSON.parse(fs.readFileSync(path.join(out, f), "utf8"))?.ex_data?.change_list || []));
    if (old.length !== st.tradeRows) return null;   // 本地本身不完整(上次被截断/中断)
    const j1 = await call("position_change_by_share", 1);
    const M = +j1?.ex_data?.max_count;
    if (isNaN(M)) return null;
    const n = M - old.length;
    if (n < 0) { console.log(`  流水增量: 服务端 ${M} < 本地 ${old.length}(有删改), 走全量`); return null; }
    const fresh = [...(j1?.ex_data?.change_list || [])];
    const need = Math.min(M, n + PER_PAGE);
    for (let p = 2; fresh.length < need; p++) {
        await jitter();
        const l = (await call("position_change_by_share", p))?.ex_data?.change_list || [];
        if (!l.length) break;
        fresh.push(...l);
        if (l.length < PER_PAGE) break;
    }
    const V = Math.min(PER_PAGE, old.length, fresh.length - n);
    if (V <= 0 && old.length) return null;
    for (let i = 0; i < V; i++) if (pcKey(fresh[n + i]) !== pcKey(old[i])) { console.log(`  流水增量: 第 ${n + i} 行与本地不一致(疑补录历史), 走全量`); return null; }
    const rows = [...fresh.slice(0, n), ...old];
    let pages = 0;
    for (let i = 0; i < rows.length; i += PER_PAGE) {
        pages++;
        const chunk = rows.slice(i, i + PER_PAGE);
        fs.writeFileSync(path.join(out, `position_change_p${pages}.json`), JSON.stringify({ ...j1, ex_data: { ...j1.ex_data, change_list: chunk, count: chunk.length, page: pages, max_count: M }, _incremental: true }, null, 1));
    }
    console.log(`  流水增量: 新增 ${n} 行(拉 ${Math.ceil(fresh.length / PER_PAGE)} 页, 校验 ${V} 行一致), 共 ${rows.length} 行/${pages} 页`);
    return { rows, total: rows.length, pages, maxCount: M };
}

async function fetchLedgerA(cfg) {
    let { ledger, key, user_key } = cfg;
    const out = path.join(ROOT, ledger);
    fs.mkdirSync(out, { recursive: true });
    // 10/14 自动换视图(用户: "要比较多个比赛看他们最新的"): 同一个人在不同比赛里 user_key 不同, 某个比赛视图会停更(退赛/换赛),
    //   如 A658 在 joonDP3 视图停在 10/09, 但在 CM3ntt2(user_key 187735)仍更新。数据停更 ≥3 天时, 从 _ranks/ 榜单里按用户名
    //   找出他所有 (比赛key, user_key), 各 1 次请求比最新净值日, 换到最新的那个(写回 tzzb_ledgers.json, 旧值留 views_tried)
    try {
        const st0 = JSON.parse(fs.readFileSync(path.join(out, "state.json"), "utf8"));
        const nav0 = String(st0.lastNavDate || "");
        const stale3 = nav0 && nav0 < new Date(Date.now() - 3 * 864e5).toISOString().slice(0, 10).replace(/-/g, "");
        const triedAt = cfg.view_checked_at ? Date.parse(cfg.view_checked_at) : 0;
        if (stale3 && Date.now() - triedAt > 20 * 36e5) {
            const best = await bestView(cfg, nav0);
            cfg.view_checked_at = new Date().toISOString();
            if (best && best.date > nav0) {
                console.log(`${ledger}: 视图 ${key}/${user_key} 停在 ${nav0}, 换到 ${best.key}/${best.user_key}(最新 ${best.date})`);
                (cfg.views_tried ||= []).push({ key, user_key, lastNavDate: nav0, at: cfg.view_checked_at });
                cfg.key = key = best.key; cfg.user_key = user_key = best.user_key;
            } else {
                console.log(`${ledger}: 停在 ${nav0}, ${best ? `其他比赛视图最新也只到 ${best.date}` : "榜单里找不到其他视图"}——疑本人没更新, 需要时找用户要个人分享链接`);
            }
            saveLedgers();
        }
    } catch { /* 无 state=首抓 */ }
    // 10/14 防封: 数据停更的账本(分享 key 的比赛窗口到期, 如 a658 停在 10/09、chong5000w 停在 07/06)每小时都"不是最新",
    //   原先每轮都重抓; 改为: 上次抓到的最新净值日比今天早 5 天以上 且 20 小时内抓过 → 本轮跳过, 一天最多抓一次
    try {
        const st0 = JSON.parse(fs.readFileSync(path.join(out, "state.json"), "utf8"));
        const nav0 = String(st0.lastNavDate || ""), ageH = (Date.now() - Date.parse(st0.lastFetch)) / 36e5;
        const stale = nav0 && nav0 < new Date(Date.now() - 5 * 864e5).toISOString().slice(0, 10).replace(/-/g, "");
        if (stale && ageH < 20 && !process.argv.includes("--full") && !cfg.views_tried?.some((v) => v.at === cfg.view_checked_at)) {   // 刚换了视图=不跳过, 立刻用新视图抓
            console.log(`${ledger}: 数据停在 ${nav0}(疑分享 key 窗口到期), ${ageH.toFixed(1)} 小时前刚抓过, 本轮跳过(一天最多一次)`);
            return { ledger, skipped: "stale", lastNavDate: nav0, ok: true };
        }
    } catch { /* 无 state=首抓 */ }

    async function call(endpoint, page = null, tries = 3, qs = "") {
        const url = `${BASE}/${endpoint}?key=${key}&user_key=${user_key}` + (page ? `&page=${page}` : "") + qs;
        for (let i = 0; ; i++) {
            if (reqCount >= DAY_BUDGET) {
                console.error(`今日请求已达上限 ${DAY_BUDGET}(防封), 本轮停止 ledger=${ledger}`);
                process.exit(5);
            }
            try {
                bump();
                // 10/15: 默认走浏览器代发(页面反爬脚本生成令牌, 见 browser/browser_transport.mjs); --direct=旧的直连(10/14 15:13 起 403)
                let r;
                if (VIA_BROWSER) {
                    if (!TRANSPORT) TRANSPORT = await BrowserTransport.open({ key, user_key });
                    const x = await TRANSPORT.get(url);
                    r = { status: x.status, text: async () => x.text, json: async () => JSON.parse(x.text) };
                    if (x.status === 0) throw new Error(x.text);
                } else {
                    r = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0" } });
                }
                if (r.status === 401 || r.status === 403) {
                    // 10/14: "Nginx forbidden. request info: <IP>" = 同花顺 WAF 封了本机 IP, 不是凭证过期(原先一律报凭证失效, 误导了 6 小时)
                    const body = await r.text().catch(() => "");
                    // 10/15: 不在这里熔断/退出, 抛给 fetchLedger 走 A→B→C 降级; 三层全败才熔断(exit 5)/报凭证失效(exit 2)
                    if (/nginx forbidden/i.test(body)) throw new LayerFail("BLOCKED", `A 层 ${r.status} Nginx forbidden: ${body.replace(/<[^>]+>/g, " ").trim().slice(0, 120)}`);
                    throw new LayerFail("AUTH", `A 层 ${r.status} 凭证失效? ledger=${ledger}`);
                }
                const j = await r.json();
                if (j?.status_code === -100 || j?.error === -100 || j?.error_code === "-100" || j?.error_code === -100) {
                    // 限流"服务器繁忙", 闭环重试
                    if (i >= tries - 1) throw new LayerFail("RATE_LIMIT", `${endpoint} 连续限流 -100`);
                    await sleep(3000 * (i + 1));
                    continue;
                }
                return j;
            } catch (e) {
                if (e instanceof LayerFail || i >= tries - 1) throw e;
                await sleep(2000 * (i + 1));
            }
        }
    }

    // ① 调仓流水(分页50, 全量也就几页, 增量与全量成本相同 → 永远全拉, 简单幂等)
    // 实测信封(2026-10-01): error_code/error_msg/ex_data; 列表=ex_data.change_list, 总数=ex_data.max_count
    let total = 0, pages = 0, maxCount = Infinity;
    const codes = new Set();   // 顺带产出全量标的清单, 供 ③ 逐笔腿逐个拉
    // 10/15 大账本(antoo 拆单极碎, 流水上万行): 页数上限按账本放宽(tzzb_ledgers.json pc_max_pages, 默认 40),
    //   且 pc_incremental=true 时非 --full 只拉"新增行数+1 页校验"(见 pcIncremental), 免得每小时一轮把上百页全翻一遍烧请求预算
    const PC_MAX = Math.max(40, +cfg.pc_max_pages || 40);
    let incr = null;
    if (cfg.pc_incremental && !process.argv.includes("--full")) incr = await pcIncremental(out, call);
    if (incr) {
        ({ total, pages, maxCount } = incr);
        for (const t of incr.rows) if (t.stock_code) codes.add(t.stock_code);
    } else for (let p = 1; p <= PC_MAX && total < maxCount; p++) {
        const j = await call("position_change_by_share", p);
        const list = j?.ex_data?.change_list || [];
        if (j?.ex_data?.max_count != null && !isNaN(+j.ex_data.max_count)) maxCount = +j.ex_data.max_count;
        if (!Array.isArray(list) || list.length === 0) break;
        fs.writeFileSync(path.join(out, `position_change_p${p}.json`), JSON.stringify(j, null, 1));
        for (const t of list) if (t.stock_code) codes.add(t.stock_code);
        total += list.length;
        pages = p;
        if (list.length < PER_PAGE) break;
        await jitter();
    }
    if (!incr && total < maxCount && maxCount !== Infinity) console.log(`${ledger}: 流水 ${total}/${maxCount} 行, 被页数上限 ${PC_MAX} 截断(需要全量就在 tzzb_ledgers.json 调大 pc_max_pages)`);
    // 10/15: 清掉本轮没覆盖到的旧分页文件(换视图后页数变少, 旧视图的 p5/p6 留着会被下游当成同一份流水重复读)
    if (pages > 0) {
        for (const f of fs.readdirSync(out).filter((x) => /^position_change_p\d+\.json$/.test(x))) {
            if (+f.match(/\d+/)[0] > pages) fs.unlinkSync(path.join(out, f));
        }
    }
    // ② 净值/月度/当前持仓(单页端点)
    let lastNavDate = "";
    for (const [ep, file] of [
        ["profit_rate_by_share", "nav_daily.json"],
        ["month_by_share", "month.json"],
        ["position_by_share", "position.json"],
    ]) {
        const j = await call(ep);
        fs.writeFileSync(path.join(out, file), JSON.stringify(j, null, 1));
        if (file === "nav_daily.json") {
            for (const x of j?.ex_data?.index_list || []) {
                if (x.date > lastNavDate) lastNavDate = x.date; // "yyyyMMdd" 字典序=时间序
            }
        }
        await jitter();
    }
    // ③ 逐笔买卖腿 change_bs(10/2 解锁: 此前 -100 真相=缺必传参数 stock_code, 非反爬非限流;
    //    hexin-v 消融实验证伪无关, 不采集不依赖)
    //    实测坑: 分页 page 参数对重仓标的服务端忽略(每页重复返回同一批腿) → 按"0新增distinct"早停,
    //    否则 51 标的全打到 50 页上限空烧请求。单页最多返回 ~75 条, 更早历史可能被截断(已知限制)
    let bsLegs = 0;
    // 10/14 增量(防封 IP): 原先每轮对账本历史上所有标的(刘忆青 91 个)逐个翻页, 单账本单轮 ~400 请求, 每小时一轮 → 10/14 被封。
    //   改为只刷新: 近 10 天流水里出现过的标的 + 当前持仓 + 本地还没有缓存文件的标的; 其余沿用本地 change_bs 缓存(历史腿不会变)
    //   --full 强制全量(偶尔对账用)
    const FULL = process.argv.includes("--full");
    const cutoff = new Date(Date.now() - 10 * 864e5).toISOString().slice(0, 10);
    const recent = new Set();
    for (let p = 1; p <= pages; p++) {
        try {
            for (const t of JSON.parse(fs.readFileSync(path.join(out, `position_change_p${p}.json`), "utf8"))?.ex_data?.change_list || [])
                if (t.stock_code && String(t.trans_date || "").slice(0, 10) >= cutoff) recent.add(t.stock_code);
        } catch { /* 缺页=不影响, 下面兜底 */ }
    }
    try {
        for (const x of JSON.parse(fs.readFileSync(path.join(out, "position.json"), "utf8"))?.ex_data?.position_list || [])
            if (x.stock_code) recent.add(x.stock_code);
    } catch { /* 无持仓文件 */ }
    const todoCodes = [...codes].filter((c) => FULL || recent.has(c) || !fs.existsSync(path.join(out, `change_bs_${c}_p1.json`)));
    console.log(`change_bs 增量: 刷新 ${todoCodes.length}/${codes.size} 个标的${FULL ? "(--full)" : ""}`);
    for (const code of todoCodes) {
        const seen = new Set();
        for (let p = 1; p <= 50; p++) {
            const j = await call("change_bs_by_share", p, 3, `&stock_code=${code}`);
            const list = j?.ex_data?.change_list || [];
            if (!Array.isArray(list) || list.length === 0) break;
            let fresh = 0;
            for (const t of list) {
                const k = `${t.trans_date}|${t.op}`;
                if (!seen.has(k)) { seen.add(k); fresh++; }
            }
            if (p === 1) {
                fs.writeFileSync(path.join(out, `change_bs_${code}_p1.json`), JSON.stringify(j, null, 1));
            } else if (fresh === 0) {
                break;   // 分页重复, 后面不会再有新货
            } else {
                fs.writeFileSync(path.join(out, `change_bs_${code}_p${p}.json`), JSON.stringify(j, null, 1));
            }
            bsLegs += fresh;
            if (list.length < 38) break;
            await jitter();
        }
        await jitter();
    }
    // ④ 历史日持仓 day_positions(10/6 破译端点; 合并进主链=增量模式: 只抓缺的日期,
    //    首轮全量回补已由独立跑完成, 每日新增≈1 日期/人)
    {
        const dpFile = path.join(out, "day_positions.json");
        let store = fs.existsSync(dpFile) ? JSON.parse(fs.readFileSync(dpFile, "utf8")) : {};
        const allDays = (JSON.parse(fs.readFileSync(path.join(out, "nav_daily.json"), "utf8"))
            ?.ex_data?.index_list || []).map((x) => x.date);
        const todo = allDays.filter((d) => !store[d]);
        let dpOk = 0, dpFail = 0;
        for (const d of todo) {
            try {
                const j = await call("day_position_by_share", null, 3, "&date=" + d);
                const list = j?.ex_data?.list || [];
                store[d] = list.length
                    ? { list, sum_pct: +list.reduce((a, x) => a + (+x.position_percent || 0), 0).toFixed(3) }
                    : { list: [], sum_pct: 0, note: "空仓或无数据" };
                dpOk++;
            } catch { dpFail++; }
            await jitter();
        }
        if (todo.length) {
            fs.writeFileSync(dpFile, JSON.stringify(store, null, 1));
            console.log("day_positions 增量: " + dpOk + " 新/" + dpFail + " 败 (" + Object.keys(store).length + "/" + allDays.length + " 日覆盖)");
        }
    }
    const pcFullAt = !incr && total >= maxCount ? new Date().toISOString()
        : (() => { try { return JSON.parse(fs.readFileSync(path.join(out, "state.json"), "utf8")).pcFullAt; } catch { return undefined; } })();
    fs.writeFileSync(path.join(out, "state.json"),
        JSON.stringify({ lastFetch: new Date().toISOString(), tradeRows: total, lastNavDate, bsLegs, layer: "A", pcFullAt, pcMode: incr ? "incremental" : "full" }, null, 1));
    return { ledger, trades: total, pages, lastNavDate, bsLegs, ok: true, pcMode: incr ? "incremental" : "full" };
}

// ---------- B/C 层(10/15): 一次被动页面加载, B 用页面自己请求的原始 JSON, C 用渲染后文字 ----------
const homeUrl = (cfg) => `https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=${cfg.key}&user_key=${cfg.user_key}`;
let CAPTURE = null;   // 同一账本 B/C 共用一次加载
async function loadPassive(cfg) {
    if (CAPTURE?.ledger === cfg.ledger) return CAPTURE.r;
    if (TRANSPORT) { await TRANSPORT.close(); TRANSPORT = null; }   // A 层 Edge 占着同一用户目录, 先关
    if (reqCount >= DAY_BUDGET) throw new LayerFail("RATE_LIMIT", `今日请求已达上限 ${DAY_BUDGET}`);
    const edge = await openEdge();
    try {
        const r = await capturePage(edge, homeUrl(cfg), { match: /capital\.hexin\.cn\/caishen_httpserver/ });
        for (let i = 0; i < r.responses.length; i++) bump();   // 页面自己发的接口请求也计入当日预算
        CAPTURE = { ledger: cfg.ledger, r };
        return r;
    } finally { edge.close(); }
}
const epOf = (u) => (u.split("?")[0].split("/").pop() || "");
async function fetchLedgerB(cfg) {
    const out = path.join(ROOT, cfg.ledger);
    fs.mkdirSync(out, { recursive: true });
    const r = await loadPassive(cfg);
    const got = {};
    let forbidden = 0;
    for (const x of r.responses) {
        if (x.status === 403 || /nginx forbidden/i.test(x.body || "")) { forbidden++; continue; }
        if (!x.body || x.status !== 200) continue;
        try { const j = JSON.parse(x.body); if (String(j.error_code ?? "0") === "0" && j.ex_data) got[epOf(x.url)] = { j, url: x.url }; } catch { /* 非 JSON 跳过 */ }
    }
    if (!got.profit_rate_by_share) {
        if (forbidden) throw new LayerFail("BLOCKED", `B 层: 页面自己的 ${forbidden} 个接口请求也被 403`);
        throw new LayerFail(r.responses.length ? "NO_DATA" : "UNAVAILABLE", `B 层: 页面未请求到 profit_rate_by_share(捕获 ${r.responses.length} 个响应)`);
    }
    const files = [];
    fs.writeFileSync(path.join(out, "nav_daily.json"), JSON.stringify(got.profit_rate_by_share.j, null, 1)); files.push("nav_daily.json");
    let lastNavDate = "";
    for (const x of got.profit_rate_by_share.j.ex_data.index_list || []) if (x.date > lastNavDate) lastNavDate = x.date;
    let trades = null;
    if (got.position_change_by_share && /[?&]page=1(&|$)/.test(got.position_change_by_share.url)) {
        fs.writeFileSync(path.join(out, "position_change_p1.json"), JSON.stringify(got.position_change_by_share.j, null, 1)); files.push("position_change_p1.json");
        trades = got.position_change_by_share.j.ex_data.max_count ?? null;
    }
    if (got.day_position_by_share) {
        const d = (got.day_position_by_share.url.match(/[?&]date=(\d{8})/) || [])[1];
        const list = got.day_position_by_share.j.ex_data.list || [];
        if (d) {
            const f = path.join(out, "day_positions.json");
            const store = fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, "utf8")) : {};
            store[d] = list.length ? { list, sum_pct: +list.reduce((a, x) => a + (+x.position_percent || 0), 0).toFixed(3) } : { list: [], sum_pct: 0, note: "空仓或无数据" };
            fs.writeFileSync(f, JSON.stringify(store, null, 1)); files.push(`day_positions.json[${d}]`);
        }
    }
    if (got.day_calendar_by_share) { fs.writeFileSync(path.join(out, "day_calendar.json"), JSON.stringify(got.day_calendar_by_share.j, null, 1)); files.push("day_calendar.json"); }
    // 10/15 TODO A11③: 个股页 hqChartsWeb.html 自己会请求 change_bs_by_share(10/15 实测 ST之狼 002667: 页面发 stock/info/detail + daily_history_by_share + change_bs_by_share)
    //   → B 层逐票被动打开"近 10 天流水 + 最新日持仓"里的票(上限 B_BS_MAX 只), 落 change_bs_<code>_p1.json(与 A 层同结构); 同一个 Edge 复用, 票间抖动
    let bsOk = 0;
    {
        const cutoff = new Date(Date.now() - 10 * 864e5).toISOString().slice(0, 10);
        const cand = new Map();
        for (const t of got.position_change_by_share?.j?.ex_data?.change_list || [])
            if (t.stock_code && String(t.trans_date || "").slice(0, 10) >= cutoff && !cand.has(t.stock_code)) cand.set(t.stock_code, { market: t.market ?? "", name: t.stock_name || "" });
        for (const x of got.day_position_by_share?.j?.ex_data?.list || []) {
            const c = x.code || x.stock_code;
            if (c && !/^(204|1318)/.test(c) && !cand.has(c)) cand.set(c, { market: x.market ?? "", name: x.name || x.stock_name || "" });
        }
        const B_BS_MAX = 12, todo = [...cand.entries()].slice(0, B_BS_MAX);
        if (todo.length && reqCount < DAY_BUDGET) {
            await sleep(1500);   // 上一个 Edge(账本主页)刚关, 等它释放用户目录
            const edge = await openEdge();
            try {
                for (const [code, m] of todo) {
                    const url = `https://tzzb.10jqka.com.cn/tzzbWeb/common/hqChartsWeb.html?key=${cfg.key}&command=tzzb_kl_${cfg.key}&user_key=${cfg.user_key}`
                        + `&leader_name=${encodeURIComponent(cfg.name || "")}&code=${code}&market=${m.market}&name=${encodeURIComponent(m.name)}&from_page=matchHomePage&query_type=2&`;
                    try {
                        const r = await capturePage(edge, url, { match: /capital\.hexin\.cn\/caishen_httpserver/, wantHtml: false, maxMs: 30000 });
                        for (let i = 0; i < r.responses.length; i++) bump();
                        const x = r.responses.find((y) => /change_bs_by_share/.test(y.url) && y.url.includes(`stock_code=${code}`) && y.status === 200 && y.body);
                        const j = x ? JSON.parse(x.body) : null;
                        if (j && String(j.error_code ?? "0") === "0" && Array.isArray(j.ex_data?.change_list)) {
                            fs.writeFileSync(path.join(out, `change_bs_${code}_p1.json`), JSON.stringify(j, null, 1)); bsOk++;
                        }
                    } catch (e) { console.log(`  B 层个股页 ${code} 失败: ${String(e.message).slice(0, 100)}`); }
                    if (reqCount >= DAY_BUDGET) break;
                    await jitter();
                }
            } finally { edge.close(); }
            files.push(`change_bs×${bsOk}/${todo.length}(个股页)`);
        }
    }
    const st0 = (() => { try { return JSON.parse(fs.readFileSync(path.join(out, "state.json"), "utf8")); } catch { return {}; } })();
    fs.writeFileSync(path.join(out, "state.json"), JSON.stringify({ ...st0, lastFetch: new Date().toISOString(), lastNavDate, tradeRows: trades ?? st0.tradeRows, layer: "B",
        layerNote: `B=被动监听: 刷新了 nav/流水第1页/最新日持仓 + 个股页 change_bs ${bsOk} 只(近 10 天流水/持仓里的票); month/position 与其余 change_bs 沿用旧缓存` }, null, 1));
    return { ledger: cfg.ledger, trades, lastNavDate, files, ok: true };
}
async function fetchLedgerC(cfg) {
    const out = path.join(ROOT, cfg.ledger);
    fs.mkdirSync(out, { recursive: true });
    const r = await loadPassive(cfg);
    if (!r.text) throw new LayerFail("UNAVAILABLE", "C 层: 渲染后页面为空");
    const c = parseLayerC(r.text);
    if (!c.daily.length && !c.trades.length && !c.positions.length) throw new LayerFail(/forbidden|403/i.test(r.text) ? "BLOCKED" : "PARSE", `C 层: 页面文字里解析不出收益率/持仓/交易记录(文字 ${r.text.length} 字)`);
    const meta = { _layer: "C", fetched_at: new Date().toISOString(), source: "rendered page text", report_time: c.reportTime };
    fs.writeFileSync(path.join(out, "layerC_daily.json"), JSON.stringify({ ...meta, ex_data: { daily_profit_loss_rate: c.todayRate, total_profit_loss_rate: c.totalRate, index_list: c.daily } }, null, 1));
    fs.writeFileSync(path.join(out, "layerC_position_change.json"), JSON.stringify({ ...meta, ex_data: { change_list: c.trades } }, null, 1));
    fs.writeFileSync(path.join(out, "layerC_day_position.json"), JSON.stringify({ ...meta, date: c.positionDate, ex_data: { list: c.positions } }, null, 1));
    const lastNavDate = c.daily.reduce((m, x) => (x.date > m ? x.date : m), "");
    const st0 = (() => { try { return JSON.parse(fs.readFileSync(path.join(out, "state.json"), "utf8")); } catch { return {}; } })();
    fs.writeFileSync(path.join(out, "state.json"), JSON.stringify({ ...st0, lastFetchC: new Date().toISOString(), lastNavDateC: lastNavDate, layer: "C",
        layerNote: "C=页面文字: 只产 layerC_*.json(每日收益率/当日持仓/交易记录), 不覆盖 A 层文件; lastNavDate 仍是 A/B 最后一次的值" }, null, 1));
    return { ledger: cfg.ledger, lastNavDateC: lastNavDate, daily: c.daily.length, trades: c.trades.length, positions: c.positions.length, ok: true };
}

async function fetchLedger(cfg) {
    const fails = [];
    const tryLayer = async (L, fn) => {
        if (FORCE_LAYER && FORCE_LAYER !== L) return null;
        try { const r = await fn(cfg); return { ...r, layer: L, fails }; }
        catch (e) { fails.push({ layer: L, kind: kindOf(e), msg: String(e.message).slice(0, 200) }); console.error(`[${cfg.ledger}] ${L} 层失败 ${kindOf(e)}: ${String(e.message).slice(0, 160)}`); return null; }
    };
    const res = (await tryLayer("A", fetchLedgerA)) || (await tryLayer("B", fetchLedgerB)) || (await tryLayer("C", fetchLedgerC));
    if (res) { if (fails.length) console.log(`[${cfg.ledger}] 降级到 ${res.layer} 层成功; 前序失败: ${fails.map((f) => `${f.layer}:${f.kind}`).join(", ")}`); return res; }
    // 三层全败: 有 BLOCKED=疑真封 IP → 熔断(冷却期零请求) exit 5; 只有 AUTH=凭证失效 exit 2; 其他 exit 1
    const kinds = new Set(fails.map((f) => f.kind));
    console.log(`JSON:${JSON.stringify([{ ledger: cfg.ledger, ok: false, fails }])}`);
    if (kinds.has("BLOCKED")) {
        if (!FORCE_LAYER) fs.writeFileSync(BAN, JSON.stringify({ at: new Date().toISOString(), ledger: cfg.ledger, info: fails.map((f) => `${f.layer}:${f.kind} ${f.msg}`).join(" | ").slice(0, 300), reqToday: reqCount }, null, 1));
        console.error(`同花顺 A/B/C 三层全败且含 BLOCKED, ${FORCE_LAYER ? "(--layer 冒烟不写熔断)" : `已写熔断 ${BAN_COOL_H}h`} ledger=${cfg.ledger}`);
        process.exit(5);
    }
    if (kinds.size === 1 && kinds.has("AUTH")) { console.error(`凭证失效 ledger=${cfg.ledger}: 请重新从分享链接取 key+user_key(见 api.md)`); process.exit(2); }
    throw new Error(`A/B/C 三层全败: ${fails.map((f) => `${f.layer}:${f.kind}`).join(", ")}`);
}

// ---------- 每日快照(10/15): downloads/tzzb → downloads/_snapshots/tzzb_<日>.zip, 保留 30 天 ----------
function dailySnapshot() {
    try {
        if (ROOT !== path.resolve("downloads/tzzb")) return;   // --root 冒烟不打包
        const dir = path.resolve("downloads/_snapshots");
        fs.mkdirSync(dir, { recursive: true });
        const zip = path.join(dir, `tzzb_${today}.zip`);
        for (const f of fs.readdirSync(dir)) {   // 保留 30 天
            const m = f.match(/^tzzb_(\d{4}-\d\d-\d\d)\.zip$/);
            if (m && Date.now() - Date.parse(m[1]) > 30 * 864e5) fs.unlinkSync(path.join(dir, f));
        }
        if (fs.existsSync(zip)) return;
        const items = fs.readdirSync(ROOT).filter((x) => x !== "_guard").map((x) => path.join(ROOT, x));
        if (!items.length) return;
        const tmp = zip.replace(/\.zip$/, ".tmp.zip");
        const ps = `$ErrorActionPreference='Stop'; Compress-Archive -Path ${items.map((x) => `'${x.replace(/'/g, "''")}'`).join(",")} -DestinationPath '${tmp}' -Force`;
        const r = spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps], { windowsHide: true, timeout: 600000, encoding: "utf8" });
        if (r.status === 0 && fs.existsSync(tmp)) { fs.renameSync(tmp, zip); console.log(`每日快照: ${zip} (${(fs.statSync(zip).size / 1e6).toFixed(1)} MB)`); }
        else { try { fs.unlinkSync(tmp); } catch { /* */ } console.error(`每日快照失败(不影响抓取): ${(r.stderr || r.error?.message || "").slice(0, 200)}`); }
    } catch (e) { console.error(`每日快照失败(不影响抓取): ${e.message}`); }
}

// ---------- 比赛榜单模式(2026-10-07 建): 发现层, by 比赛只产元数据, 归档永远 by ledger ----------
// 用法: node scripts/tzzb/fetch_tzzb.mjs --rank <比赛key>[,<比赛key>...] [--pages N]
// 背景: (比赛key, user_key) 直通账本全链端点(10/7 实证: 与账本 key 返回同一数据, user_key=账本主键);
//       榜单行自带 user_key/rank/score/total_profit_rate/win_rate/position_rate/enter_date = 正负样本筛料。
// 产物: downloads/tzzb/_ranks/<比赛key>.json(全量榜单) + stdout 摘要; 零副作用不动 ledger 链。
async function fetchRank(matchKey, maxPages = 20) {
    const outDir = path.join(ROOT, "_ranks");
    fs.mkdirSync(outDir, { recursive: true });
    const rows = [];
    for (let p = 1; p <= maxPages; p++) {
        const url = `${BASE}/match_ranking_by_share?key=${matchKey}&page=${p}`;
        let j;
        for (let i = 0; ; i++) {
            try {
                const r = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0" } });
                j = await r.json();
                break;
            } catch (e) {
                if (i >= 2) throw e;
                await sleep(2000 * (i + 1));
            }
        }
        const list = j?.ex_data?.rank_list || [];
        if (!Array.isArray(list) || list.length === 0) break;
        rows.push(...list);
        if (list.length < 50) break;
        await jitter();
    }
    fs.writeFileSync(path.join(outDir, `${matchKey}.json`), JSON.stringify({ match_key: matchKey, fetched_at: new Date().toISOString(), rows }, null, 1));
    return rows;
}

async function rankMode(keys) {
    const summary = [];
    for (const k of keys) {
        const rows = await fetchRank(k);
        const uniq = new Map(rows.map((r) => [r.user_key, r]));   // 同人翻页去重
        const profit = [...uniq.values()].map((r) => +r.total_profit_rate).filter((x) => !isNaN(x)).sort((a, b) => b - a);
        summary.push({ match: k, players: uniq.size,
            top: [...uniq.values()].sort((a, b) => b.score - a.score).slice(0, 3).map((r) => `${r.user_name}(${r.user_key}) ${(100 * +r.total_profit_rate).toFixed(1)}%`) });
        console.log(`[rank] ${k}: ${rows.length} 行/${uniq.size} 人, 收益中位 ${profit.length ? (100 * profit[Math.floor(profit.length / 2)]).toFixed(1) + "%" : "?"}`);
        await jitter();
    }
    console.log(`JSON:${JSON.stringify(summary)}`);
}

async function main() {
    // 10/14 熔断: 冷却期内不发任何请求(封禁期间越请求封得越久); 冷却期过了, 本次就是那 1 次探测
    const b = banned();
    if (b && !process.argv.includes("--force-probe")) {
        console.error(`熔断中: ${b.at} 被同花顺封 IP(${b.info}), 冷却 ${BAN_COOL_H}h 还剩 ${(BAN_COOL_H - b.ageH).toFixed(1)}h, 本次不请求`);
        process.exit(5);
    }
    // 单实例锁: Java 每小时一轮 + 手动跑/别的脚本 同时打同花顺=请求翻倍(锁持有进程已死则回收)
    const LOCK = path.join(GUARD, "fetch.lock");
    try {
        const pid = +fs.readFileSync(LOCK, "utf8");
        try { process.kill(pid, 0); console.error(`另一个 fetch_tzzb 在跑(pid ${pid}), 本次退出`); process.exit(1); } catch { /* 死锁回收 */ }
    } catch { /* 无锁 */ }
    fs.writeFileSync(LOCK, String(process.pid));
    process.on("exit", () => { try { if (+fs.readFileSync(LOCK, "utf8") === process.pid) fs.unlinkSync(LOCK); } catch { /* ignore */ } });
    const li = process.argv.indexOf("--ledger");
    const only = li > -1 ? process.argv[li + 1] : null;
    const ri = process.argv.indexOf("--rank");
    if (ri > -1) {
        const keys = (process.argv[ri + 1] || "").split(",").filter(Boolean);
        if (!keys.length) { console.error("用法: --rank <比赛key>[,<比赛key>...]"); process.exit(1); }
        await rankMode(keys);
        return;
    }
    const targets = only ? LEDGERS.filter((l) => l.ledger === only) : LEDGERS;
    if (targets.length === 0) {
        console.error(`未知账本: ${only} (见 scripts/tzzb_ledgers.json)`);
        process.exit(1);
    }
    dailySnapshot();   // 抓之前打包(=前一轮的完整数据), 当天只打一次
    const results = [];
    for (const l of targets) {
        results.push(await fetchLedger(l));
        await jitter();
    }
    console.log(`JSON:${JSON.stringify(results)}`);
    if (TRANSPORT) await TRANSPORT.close();
}
main().catch((e) => {
    console.error("FAIL:", e.message);
    process.exit(1);
});
