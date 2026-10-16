// add_fupan_old_md.mjs — 给没有 `## 复盘` 的早期 md(2025-01-07~03-20 共 41 个)补复盘节(2026-10-15 建, 用户 10/15 定=补)
// 用法: node scripts/lhb/add_fupan_old_md.mjs [--dry] [--date yyyy-MM-dd ...]
// 做法(零请求):
//   ①骨架从模板 stock-template.md 的 `## 复盘` 段现读(### / #### 标题, 不写死); 模板里的空表格占位行不抄(### 龙虎榜 整节随后由 fetch_lhb 覆盖)
//   ②### 同花顺投资账本 下的导师小节: 只给当天确有该导师数据(change_bs/position_change/nav_daily/layerC 有这一天)的加, 内容=gen_tzzb_md.mjs 硬数据层(stdout, 不让它自己写盘);
//     一个都没有就连 ### 同花顺投资账本 也不加(用户 10/15 定)
//   ③### bilibili 下 UP 小节只放模板骨架标题(内容归 B站补跑管线)
//   ④复盘节追加在文件末尾(早期 md 结构=盘前/竞价/早盘/下午盘/总结, 无 ## 加红电报); 换行符跟原文件(CRLF/LF)
//   ⑤写完调 fetch_lhb.mjs --date D --write --local(只读本地 json, 绝不联网)填 ### 龙虎榜
// 安全: 目标文件 5 分钟内被改过=跳过(防与 B站补跑/check md 并发写); 写后核对: 原文=新文前缀, 新增部分只有 ## 复盘 一个二级标题; 失败恢复原文
// 末行 JSON:{...}
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
process.chdir(ROOT);
const ARGS = process.argv.slice(2);
const DRY = ARGS.includes("--dry");
const ONLY = ARGS.flatMap((a, i) => (ARGS[i - 1] === "--date" ? [a] : []));
const canon = (s) => s.replace(/^#+\s*/, "").replace(/\s+/g, "").toLowerCase();

// ---- 模板复盘骨架 ----
const T = fs.readFileSync("inv-stock/src/main/resources/templates/stock-template.md", "utf8").replace(/\r/g, "").split("\n");
const ts = T.findIndex((l) => /^## 复盘\s*$/.test(l));
const skel = [];
for (let i = ts + 1; i < T.length && !/^## /.test(T[i]); i++) if (/^#{3,4} /.test(T[i])) skel.push(T[i].trim());

// ---- tzzb 正样本导师: 有数据的日子 ----
const LEDGERS = JSON.parse(fs.readFileSync("scripts/tzzb/tzzb_ledgers.json", "utf8")).filter((l) => l.kind !== "neg");
const ledgerDays = {};
for (const l of LEDGERS) {
    const dir = path.join("downloads", "tzzb", l.ledger);
    const set = (ledgerDays[l.ledger] = new Set());
    if (!fs.existsSync(dir)) continue;
    const rd = (f) => { try { return JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")); } catch { return null; } };
    for (const f of fs.readdirSync(dir)) {
        if (/^(change_bs_|position_change_p)/.test(f) || f === "layerC_position_change.json")
            for (const t of rd(f)?.ex_data?.change_list || []) if (t.trans_date) set.add(t.trans_date.slice(0, 10));
        if (f === "nav_daily.json" || f === "layerC_daily.json")
            for (const x of rd(f)?.ex_data?.index_list || []) if (x.date) set.add(`${x.date.slice(0, 4)}-${x.date.slice(4, 6)}-${x.date.slice(6, 8)}`);
    }
}
function tzzbBody(ledger, day) {
    const r = spawnSync(process.execPath, ["scripts/tzzb/gen_tzzb_md.mjs", "--ledger", ledger, "--date", day], { encoding: "utf8", windowsHide: true, timeout: 120000 });
    return r.status === 0 && r.stdout.trim() ? r.stdout.replace(/\r/g, "").replace(/\n+$/, "") : null;
}

function buildBlock(day) {
    const L = ["## 复盘", ""];
    const tz = [];
    let sec = null;
    for (const h of skel) {
        if (/^### /.test(h)) { sec = canon(h); if (sec !== canon("同花顺投资账本")) L.push(h, ""); continue; }
        if (sec === canon("同花顺投资账本")) {
            const l = LEDGERS.find((x) => canon(x.name) === canon(h));
            if (!l || !ledgerDays[l.ledger]?.has(day)) continue;
            const body = tzzbBody(l.ledger, day);
            if (body) tz.push(h, "", ...body.split("\n"), "");
            continue;
        }
        L.push(h, "");
    }
    if (tz.length) {   // 插回模板位置: ### 同花顺投资账本 在模板里的次序(其后的 ### 节之前)
        const order = skel.filter((h) => /^### /.test(h)).map(canon);
        const zi = order.indexOf(canon("同花顺投资账本"));
        const nextSec = order.slice(zi + 1).map((c) => L.findIndex((x) => /^### /.test(x) && canon(x) === c)).find((i) => i >= 0);
        L.splice(nextSec ?? L.length, 0, "### 同花顺投资账本", "", ...tz);
    }
    while (L.length && L[L.length - 1] === "") L.pop();
    return { lines: L, tzzb: tz.filter((x) => /^#### /.test(x)) };
}

// ---- 目标 ----
const targets = [];
for (const d of fs.readdirSync("md").filter((x) => /^\d{4}S[1-4]$/.test(x)).sort())
    for (const f of fs.readdirSync(path.join("md", d)).filter((x) => /^\d{4}-\d{2}-\d{2}\.md$/.test(x)).sort()) {
        const day = f.slice(0, 10);
        if (ONLY.length && !ONLY.includes(day)) continue;
        const p = path.join("md", d, f);
        if (!/^## 复盘[ \t]*\r?$/m.test(fs.readFileSync(p, "utf8"))) targets.push({ day, p });
    }

const S = { targets: targets.length, written: [], skipped: [], failed: [], tzzb: {} };
for (const { day, p } of targets) {
    const st = fs.statSync(p);
    if (Date.now() - st.mtimeMs < 5 * 60e3) { S.skipped.push(`${day}: 5 分钟内被改过`); continue; }
    const orig = fs.readFileSync(p, "utf8");
    const crlf = (orig.match(/\r\n/g) || []).length, lf = (orig.match(/\n/g) || []).length;
    const EOL = crlf && crlf >= lf - crlf ? "\r\n" : "\n";
    const { lines, tzzb } = buildBlock(day);
    if (tzzb.length) S.tzzb[day] = tzzb;
    const lead = orig.endsWith(EOL + EOL) ? "" : orig.endsWith(EOL) || orig.endsWith("\n") ? EOL : EOL + EOL;
    const next = orig + lead + lines.join(EOL) + EOL;
    if (DRY) { console.log(`[dry] ${day}: +${lines.length} 行, EOL=${EOL === "\r\n" ? "CRLF" : "LF"}, tzzb=${tzzb.length}`); continue; }
    fs.writeFileSync(p, next);
    const r = spawnSync(process.execPath, ["scripts/lhb/fetch_lhb.mjs", "--date", day, "--write", "--local"], { encoding: "utf8", windowsHide: true, timeout: 120000 });
    const jl = (r.stdout || "").split("\n").reverse().find((l) => l.startsWith("JSON:"));
    const j = jl ? JSON.parse(jl.slice(5)) : { code: r.status, msg: (r.stderr || "").slice(0, 200) };
    // 核对: 原文是新文前缀; 新增部分只有一个 ## 标题(## 复盘); CRLF 文件新增部分不许有裸 LF
    const now = fs.readFileSync(p, "utf8");
    const add = now.slice(orig.length);
    const errs = [];
    if (!now.startsWith(orig)) errs.push("原文不是前缀");
    if ((add.match(/^## .*$/gm) || []).map((x) => x.replace(/\r$/, "")).join("|") !== "## 复盘") errs.push("新增部分二级标题不止 ## 复盘");
    if (EOL === "\r\n" && /(^|[^\r])\n/.test(add)) errs.push("新增部分有裸 LF");
    if (j.code !== 0 || j.md !== "已写") errs.push(`fetch_lhb --local: code=${j.code} md=${j.md} ${j.msg || ""}`);
    if (j.requests) errs.push(`fetch_lhb 发了 ${j.requests} 次请求(不该联网)`);
    if (errs.length) { fs.writeFileSync(p, orig); S.failed.push(`${day}: ${errs.join("; ")}(已恢复原文)`); continue; }
    S.written.push(day);
    console.log(`${day} ✓ 复盘节 +${add.split(EOL).length - 1} 行(龙虎榜 ${j.stocks} 只)${tzzb.length ? `, tzzb ${tzzb.length} 人` : ""}`);
}
console.log(`汇总: 目标 ${S.targets}, 写 ${S.written.length}, 跳过 ${S.skipped.length}, 失败 ${S.failed.length}`);
S.skipped.concat(S.failed).forEach((x) => console.log("  " + x));
console.log("JSON:" + JSON.stringify(S));
process.exitCode = S.failed.length ? 1 : 0;
