// auction.mjs — 集合竞价过程共享读取 + 渲染(10/18 用户定: 竞价过程进共享实时层, paper 全链 + 用户实盘 + 盘中问答都读同一份; 零 token)
// 数据: scripts/market/collect_auction.py 竞价期间每轮原子重写 downloads/market/<日>/auction_live_open.json(state=running|final)
// 口径: 09:15~09:20 可撤单(虚报多, 只看区间) / 09:20~09:25 不可撤(真实意图, 重点看 9:20→9:25 怎么变) / 09:25 撮合=开盘价+竞价量
// 消费: dfcf/paper/facts.mjs(slot ≥0925 的事实包「集合竞价」节) / dfcf/live_watch.mjs(盯盘 md「集合竞价」节)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as AR from "./a_rules.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const INDEX = { sh000001: "上证", sz399001: "深成", sz399006: "创业板" };
const sg = (x, d = 1) => (x === null || x === undefined ? "?" : `${x > 0 ? "+" : ""}${(+x).toFixed(d)}`);
const wan = (v) => (v === null || v === undefined ? "?" : v >= 1e8 ? `${(v / 1e8).toFixed(2)}亿` : v >= 1e4 ? `${Math.round(v / 1e4)}万` : `${Math.round(v)}`);

/** 读当日竞价汇总; 文件缺/坏 = null(调用方写"未采到", 不编数据) */
export function loadAuction(date, phase = "open") {
    const f = path.join(ROOT, "downloads", "market", date, `auction_live_${phase}.json`);
    try { return JSON.parse(fs.readFileSync(f, "utf8")); } catch { return null; }
}

/** 一只票一行: 9:20(可撤段末) → 9:25 撮合; 量=股 */
export function stockLine(sym, s) {
    if (!s) return null;
    const p1 = s.p2_first || s.p1, fin = s.fin || s.p2;   // 9:20 基准=撤单冻结后第一张快照
    const head = `${s.name || sym}(${sym.slice(2)})`;
    const parts = [];
    if (p1) parts.push(`9:20 ${sg(p1.pct)}%` + (s.p1_lo !== null && s.p1_hi !== null ? `(可撤段区间 ${sg(s.p1_lo)}~${sg(s.p1_hi)}%)` : ""));
    if (fin) parts.push(`${s.fin ? "9:25 开盘" : `${fin.t.slice(0, 5)} 匹配`} ${fin.px}(${sg(fin.pct)}%)`);
    if (fin && fin.vol) parts.push(`竞价量 ${wan(fin.vol)}股 / 额 ${wan(fin.vol * fin.px)}` + (s.vol_ratio ? ` = 昨日全天 ${(s.vol_ratio * 100).toFixed(1)}%` : ""));
    if (s.p2 && s.p2.unm) parts.push(`不可撤段末未匹配 ${s.p2.unm > 0 ? "买" : "卖"} ${wan(Math.abs(s.p2.unm))}股`);
    return `- ${head}: ${parts.join(" | ") || "无撮合"}${(s.tags || []).length ? ` 【${s.tags.join("; ")}】` : ""}`;
}

/** codes=6 位代码(关注票); top=市场里 9:20 后抬价/压价最多各 N 只(竞价额 ≥500 万, 去掉指数) */
export function auctionMd(A, codes = [], { top = 4, title = true } = {}) {
    if (!A) return "(今日竞价过程未采到: downloads/market/<日>/auction_live_open.json 缺失)";
    const S = A.symbols || {}, L = [];
    if (title) L.push(`> 采集 ${A.updated?.slice(11, 19) || "?"}${A.state === "final" ? "(竞价已结束)" : "(竞价进行中, 数字会变)"}; 9:15~9:20 可撤单=虚报多只看区间, 9:20~9:25 不可撤=真实意图, 重点看 9:20→9:25 的变化`);
    const idx = Object.entries(INDEX).map(([k, n]) => { const x = S[k]; if (!x) return null; const b = x.p2_first || x.p1, e = x.fin || x.p2 || b;
        return `${n} ${sg(e?.pct, 2)}%` + (b && b !== e ? `(9:20 ${sg(b.pct, 2)}%)` : ""); }).filter(Boolean);
    if (idx.length) L.push("指数: " + idx.join(" | "));
    const seen = new Set();
    const mine = codes.map((c) => AR.symbol(c)).filter((s) => S[s] && !seen.has(s) && seen.add(s));
    if (codes.length) L.push(mine.length ? mine.map((s) => stockLine(s, S[s])).join("\n") : "(关注票不在采集名单或无撮合)");
    if (top) {
        const pool = Object.entries(S).filter(([k, s]) => !INDEX[k] && s.d_after920 !== undefined && (s.fin || s.p2) && (s.fin || s.p2).vol * (s.fin || s.p2).px >= 5e6);
        const up = [...pool].sort((a, b) => b[1].d_after920 - a[1].d_after920).slice(0, top).filter(([, s]) => s.d_after920 >= 1);
        const dn = [...pool].sort((a, b) => a[1].d_after920 - b[1].d_after920).slice(0, top).filter(([, s]) => s.d_after920 <= -1);
        if (up.length) L.push("采集名单里 9:20 后抬价最多:", ...up.map(([k, s]) => stockLine(k, s)));
        if (dn.length) L.push("采集名单里 9:20 后压价最多:", ...dn.map(([k, s]) => stockLine(k, s)));
    }
    return L.join("\n");
}
