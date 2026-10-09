// gen_players.mjs — players.json 观察池建档(2026-10-09, TODO §2-4)
// 数据源: scripts/tzzb/tzzb_ledgers.json(现役 16 人) + downloads/tzzb/_ranks/<match>.json(六场榜单)
// 产出: scripts/tzzb/players.json = { active: [...现役含三闸登记], watch: [...榜单前20宽进] }
// 幂等: 重跑覆盖; 榜单快照取自 _ranks 文件 fetched_at, 过期(>7天)标 stale
// 用法: node scripts/tzzb/gen_players.mjs
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")), "..", "..");
const LEDGERS = JSON.parse(fs.readFileSync(path.join(ROOT, "scripts/tzzb/tzzb_ledgers.json"), "utf8"));
const RANKS_DIR = path.join(ROOT, "downloads/tzzb/_ranks");
const OUT = path.join(ROOT, "scripts/tzzb/players.json");

// ---- 现役登记(三闸元数据: 榜单名次/出手/持续性由 fetch 侧核, 这里登记档案位) ----
const active = LEDGERS.map((l) => ({
    ledger: l.ledger, name: l.name, kind: l.kind || "pos",
    match_key: l.key, user_key: l.user_key, entered: l.entered ?? null,
    rank_at_pick: l.rank ? +l.rank : null, rate_pct_at_pick: l.rank_rate_pct ?? l.rate_pct ?? null,
    note: l.match ?? "",
}));

// ---- 观察池: 每场榜单前 20, 排除现役, 宽进 ----
const activeKeys = new Set(active.map((a) => `${a.match_key}:${a.user_key}`));
const activeNames = new Set(active.map((a) => a.name));
// 同名去空格归一(tzzb 榜名与 json 名空格风格不一: "A658正好蓝天" vs "A658 正好蓝天")
const norm = (s) => (s || "").replace(/\s+/g, "");
const activeNamesN = new Set(active.map((a) => norm(a.name)));
const watch = [];
for (const f of fs.readdirSync(RANKS_DIR).filter((x) => x.endsWith(".json"))) {
    const matchKey = f.replace(/\.json$/, "");
    const d = JSON.parse(fs.readFileSync(path.join(RANKS_DIR, f), "utf8"));
    const staleDays = Math.floor((Date.now() - new Date(d.fetched_at).getTime()) / 86400000);
    for (const r of (d.rows || []).slice(0, 20)) {
        const key = `${matchKey}:${r.user_key}`;
        if (activeKeys.has(key) || activeNames.has(r.user_name) || activeNamesN.has(norm(r.user_name))) continue;
        watch.push({
            match_key: matchKey, user_key: r.user_key, name: r.user_name,
            rank: +r.show_rank_index || null, rate_pct: +r.total_profit_rate || null,
            position_rate: +r.position_rate || null, enter_date: r.enter_date || null,
            snapshot_at: d.fetched_at, stale_days: staleDays,
        });
    }
}
// 同人跨场去重(同名同 enter_date=同一人, 保留窗口最早那场=历史最长)
const byPerson = new Map();
for (const w of watch) {
    const k = `${norm(w.name)}|${w.enter_date}`;
    if (!byPerson.has(k) || (byPerson.get(k).snapshot_at > w.snapshot_at)) byPerson.set(k, w);
}
const watchOut = [...byPerson.values()].sort((a, b) => (b.rate_pct || 0) - (a.rate_pct || 0));

fs.writeFileSync(OUT, JSON.stringify({
    generated_at: new Date().toISOString(),
    rules: "现役=三闸严出(总榜前20+出手≥30日/腿≥100+持续≥0.15%/日); 观察池=每场榜前20宽进+同人跨场去重留最早窗口; 周期榜面复查=重跑本脚本 diff",
    active, watch: watchOut,
}, null, 1));
console.log(`players.json: active=${active.length} watch=${watchOut.length}(六场前20去重后) → ${OUT}`);
