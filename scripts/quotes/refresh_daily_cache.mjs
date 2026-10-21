// refresh_daily_cache.mjs — 日线缓存 downloads/quotes/daily/<code>.json 每晚整体补到最新(10/20 晚; 零网络, 读本地行情库)
// 为什么: 缓存只在某脚本缺某只票时顺手补, 没有定时整体刷新 → 10/20 晚 1570 只里最新到 10/20 的只有 16 只、停在 10/16 的 319 只;
//   读它的: matcher 前收兜底 / EOD 历史日 / report 持仓收盘 / daily_digest / settle / 振幅中位(run_chain 失效线 / 子链闸 / t_event / open_live) 全受影响
// 做法: 对缓存里每只票调 kline.mjs archiveDaily(src=db: 只读 investment_market.kline_day + 复权因子; 期间有除权自动整档重取, 不混基准)
// 时机: check md 晚间, 行情库收盘入库(15:35)之后、指标 / 拓扑之前; 也可手动跑
// 用法: node scripts/quotes/refresh_daily_cache.mjs [--codes a,b]   输出 JSON:{total, inc, fail, mixed, stale_after}
import fs from "node:fs";
import path from "node:path";
import { archiveDaily } from "./kline.mjs";

const DIR = "downloads/quotes/daily";
const arg = (k) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : null; };
const codes = arg("--codes") ? arg("--codes").split(",") : fs.readdirSync(DIR).filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5).replace("_", "."));
const r = await archiveDaily(codes, { dir: DIR, src: "db", gapMs: 0 });
const last = {};
for (const c of codes) {
    try { const k = JSON.parse(fs.readFileSync(path.join(DIR, `${c}.json`), "utf8")).klines; const d = k[k.length - 1].d; last[d] = (last[d] || 0) + 1; } catch { /* 坏档 */ }
}
const top = Object.keys(last).sort().pop();
console.log(`JSON:${JSON.stringify({ total: codes.length, inc: r.inc, fail: r.fail.length, fail_sample: r.fail.slice(0, 5), mixed: r.mixed.length, latest: top, at_latest: last[top], not_latest: codes.length - (last[top] || 0) })}`);
