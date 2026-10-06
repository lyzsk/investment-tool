// fetch_tzzb.mjs — 投资账本抓取(多账本版, 2026-10-01 由单账本改造)
// 用法: node scripts/fetch_tzzb.mjs [--ledger <id>]
//   默认跑 scripts/tzzb_ledgers.json 全部账本; --ledger 只跑指定账本
//   (Java CbTzzbFetchHandler 小时级兜底: 当日净值已入库的账本短路跳过, 缺的账本逐个 --ledger 补抓)
// 产物: downloads/tzzb/<ledger>/position_change_p<n>.json / nav_daily.json / month.json / position.json
//       downloads/tzzb/<ledger>/change_bs_<code>_p<n>.json (逐笔买卖腿, 每标的全历史分页)
//       downloads/tzzb/<ledger>/state.json(lastFetch/tradeRows/lastNavDate/bsLegs, 供对账)
// 出口: 0=正常(含无新增); 2=凭证失效(stderr 带 ledger id); 1=其他失败
// 约定: 摘要行以 "JSON:" 前缀输出供 Java handler 解析(照 fetch_bilibili.mjs --list 先例)
import fs from "fs";
import path from "path";

const BASE = "https://capital.hexin.cn/caishen_httpserver/direct/caishen_fund/community_share/v1";
const ROOT = path.resolve("downloads/tzzb");
const LEDGERS = JSON.parse(fs.readFileSync(path.resolve("scripts/tzzb/tzzb_ledgers.json"), "utf8"));  // 10/2 迁入 scripts/tzzb/(cwd=项目根)
const PER_PAGE = 50;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = () => sleep(800 * (0.75 + Math.random() * 0.5)); // 请求抖动铁律

async function fetchLedger({ ledger, key, user_key }) {
    const out = path.join(ROOT, ledger);
    fs.mkdirSync(out, { recursive: true });

    async function call(endpoint, page = null, tries = 3, qs = "") {
        const url = `${BASE}/${endpoint}?key=${key}&user_key=${user_key}` + (page ? `&page=${page}` : "") + qs;
        for (let i = 0; ; i++) {
            try {
                const r = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0" } });
                if (r.status === 401 || r.status === 403) {
                    console.error(`凭证失效(${r.status}) ledger=${ledger}: 请重新从分享链接取 key+user_key(见 api.md)`);
                    process.exit(2);
                }
                const j = await r.json();
                if (j?.status_code === -100 || j?.error === -100 || j?.error_code === "-100" || j?.error_code === -100) {
                    // 限流"服务器繁忙", 闭环重试
                    if (i >= tries - 1) throw new Error(`${endpoint} 连续限流 -100`);
                    await sleep(3000 * (i + 1));
                    continue;
                }
                return j;
            } catch (e) {
                if (i >= tries - 1) throw e;
                await sleep(2000 * (i + 1));
            }
        }
    }

    // ① 调仓流水(分页50, 全量也就几页, 增量与全量成本相同 → 永远全拉, 简单幂等)
    // 实测信封(2026-10-01): error_code/error_msg/ex_data; 列表=ex_data.change_list, 总数=ex_data.max_count
    let total = 0, pages = 0, maxCount = Infinity;
    const codes = new Set();   // 顺带产出全量标的清单, 供 ③ 逐笔腿逐个拉
    for (let p = 1; p <= 40 && total < maxCount; p++) {
        const j = await call("position_change_by_share", p);
        const list = j?.ex_data?.change_list || [];
        if (typeof j?.ex_data?.max_count === "number") maxCount = j.ex_data.max_count;
        if (!Array.isArray(list) || list.length === 0) break;
        fs.writeFileSync(path.join(out, `position_change_p${p}.json`), JSON.stringify(j, null, 1));
        for (const t of list) if (t.stock_code) codes.add(t.stock_code);
        total += list.length;
        pages = p;
        if (list.length < PER_PAGE) break;
        await jitter();
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
    for (const code of codes) {
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
    fs.writeFileSync(path.join(out, "state.json"),
        JSON.stringify({ lastFetch: new Date().toISOString(), tradeRows: total, lastNavDate, bsLegs }, null, 1));
    return { ledger, trades: total, pages, lastNavDate, bsLegs, ok: true };
}

async function main() {
    const li = process.argv.indexOf("--ledger");
    const only = li > -1 ? process.argv[li + 1] : null;
    const targets = only ? LEDGERS.filter((l) => l.ledger === only) : LEDGERS;
    if (targets.length === 0) {
        console.error(`未知账本: ${only} (见 scripts/tzzb_ledgers.json)`);
        process.exit(1);
    }
    const results = [];
    for (const l of targets) {
        results.push(await fetchLedger(l));
        await jitter();
    }
    console.log(`JSON:${JSON.stringify(results)}`);
}
main().catch((e) => {
    console.error("FAIL:", e.message);
    process.exit(1);
});
