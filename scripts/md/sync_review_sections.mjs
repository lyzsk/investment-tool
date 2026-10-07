// sync_review_sections.mjs — 复盘区小节按"模板+日期规则"外科手术式同步(2026-10-07 用户令, 一次性)
// 规则:
//   ① ### bilibili 及其 ####: 全历史保留(md 起点 2025-01-07 起都要)
//   ② ### 同花顺投资账本 的每个 #### 账本: 从该账本 nav_daily 最早日(=比赛开始)起才有;
//      全部不合格的文件 → 整个 ### 节删除(早期 md 不背空账本骨架)
//   ③ 文件日期 >= 今天: 完整模板骨架(今天起格式=stock-template.md)
//   ④ 标题文本归一为模板原文(空白不敏感 canon 比对)
//   ⑤ 其余内容零位移: 复盘持仓下的个股 ####(旧格式)、五锚点挂载节、任何非模板块一概不动不挪
//      ——只删"日期不合格且为空"的账本骨架节; 有内容的报"悬空"警告保留
// 实现: 按 canon 决定删谁 → 单遍重建(天然无索引簿记) → 归一 → 补缺 → 空行收敛
// 幂等: 重跑=0 改动。用法: node scripts/md/sync_review_sections.mjs [--dry]  (cwd=项目根)
import fs from "fs";
import path from "path";

const DRY = process.argv.includes("--dry");
const TODAY = (() => { const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; })();
const canon = (s) => s.replace(/^#+\s*/, "").replace(/\s+/g, "").toLowerCase();
const TZZB = canon("同花顺投资账本");
const HEADER_RE = /^#{3,4} /;

// ---- 模板骨架 ----
const tplLines = fs.readFileSync("inv-stock/src/main/resources/templates/stock-template.md", "utf8").split("\n");
const fs_ = tplLines.findIndex((l) => /^## 复盘\s*$/.test(l));
if (fs_ === -1) throw new Error("模板缺 ## 复盘");
const groups = [];
for (let i = fs_ + 1; i < tplLines.length && !/^## /.test(tplLines[i]); i++) {
    if (/^### /.test(tplLines[i])) groups.push({ h3: tplLines[i].trim(), kids: [] });
    else if (/^#### /.test(tplLines[i]) && groups.length) groups[groups.length - 1].kids.push(tplLines[i].trim());
}
const tzzbKids = groups.find((g) => canon(g.h3) === TZZB).kids;
const tzzbKidCanons = new Set(tzzbKids.map(canon));
const tplCanon = new Map();
for (const g of groups) { tplCanon.set(canon(g.h3), g.h3); for (const k of g.kids) tplCanon.set(canon(k), k); }

// ---- 账本比赛开始日 ----
const starts = new Map();
for (const l of JSON.parse(fs.readFileSync("scripts/tzzb/tzzb_ledgers.json", "utf8"))) {
    const p = path.join("downloads/tzzb", l.ledger, "nav_daily.json");
    if (!fs.existsSync(p)) { console.warn(`[warn] ${l.ledger} 无 nav_daily.json, 该账本视作不合格`); continue; }
    const list = JSON.parse(fs.readFileSync(p, "utf8"))?.ex_data?.index_list || [];
    if (!list.length) continue;
    const min = list.reduce((m, x) => (String(x.date) < m ? String(x.date) : m), "99999999");
    starts.set(canon(l.name), `${min.slice(0, 4)}-${min.slice(4, 6)}-${min.slice(6, 8)}`);
}
const qualifies = (c, date) => date >= TODAY || (starts.get(c) || "9999-99-99") <= date;

let files = 0, changed = 0;
const tally = {};
const bump = (k) => (tally[k] = (tally[k] || 0) + 1);
for (const dir of fs.readdirSync("md").filter((d) => fs.statSync(path.join("md", d)).isDirectory()).sort()) {
    for (const f of fs.readdirSync(path.join("md", dir)).filter((x) => x.endsWith(".md")).sort()) {
        files++;
        const p = path.join("md", dir, f);
        const date = f.replace(/\.md$/, "");
        const lines = fs.readFileSync(p, "utf8").split("\n");
        const fv = lines.findIndex((l) => /^## 复盘\s*$/.test(l));
        if (fv === -1) continue;                      // 模式C: 上古文件无 ## 复盘, 不动
        let fvEnd = lines.length;
        for (let i = fv + 1; i < lines.length; i++) if (/^## /.test(lines[i])) { fvEnd = i; break; }

        // ---- pass1: 扫块, 决定删除集 ----
        const delCanons = new Set();                  // 要删的 tzzb 子节 canon
        let delTzzbHeader = false, touched = false;
        const kidBlocks = [];                         // {canon, hdr, end} tzzb 子节
        let hTzzbHdr = -1, hTzzbDirectBlank = true;
        let cur = null;
        for (let i = fv + 1; i < fvEnd; i++) {
            const line = lines[i];
            if (HEADER_RE.test(line)) {
                const c = canon(line), l3 = /^### /.test(line);
                if (l3 && c === TZZB) { hTzzbHdr = i; cur = null; continue; }
                if (l3) { cur = null;
                    if (hTzzbHdr >= 0 && i > hTzzbHdr && kidBlocks.length) { /* tzzb 家族结束 */ } }
                if (!l3 && hTzzbHdr >= 0 && tzzbKidCanons.has(c)) { cur = { canon: c, hdr: i, end: i }; kidBlocks.push(cur); continue; }
                cur = null;
            } else if (cur) cur.end = i;
            else if (hTzzbHdr >= 0 && kidBlocks.length === 0 && line.trim() !== "") hTzzbDirectBlank = false; // ### 直接内容
        }
        const qKids = kidBlocks.filter((b) => qualifies(b.canon, date));
        for (const b of kidBlocks) {
            if (qualifies(b.canon, date)) continue;
            if (lines.slice(b.hdr + 1, b.end + 1).some((l) => l.trim() !== "")) { bump(`!!悬空内容保留:${b.canon}`); continue; }
            delCanons.add(b.canon); touched = true; bump(`删早于比赛开始:${b.canon}`);
        }
        if (hTzzbHdr >= 0 && !qKids.length && hTzzbDirectBlank && kidBlocks.every((b) => delCanons.has(b.canon))) {
            delTzzbHeader = true; touched = true; bump("删空账本总节:同花顺投资账本");
        }

        // ---- pass2: 单遍重建(删块+标题归一) ----
        const out = [];
        let i = fv + 1;
        while (i < fvEnd) {
            if (HEADER_RE.test(lines[i])) {
                const c = canon(lines[i]);
                let j = i + 1;
                while (j < fvEnd && !HEADER_RE.test(lines[j])) j++;
                const kill = delCanons.has(c)
                    || (delTzzbHeader && /^### /.test(lines[i]) && c === TZZB);
                if (!kill) {
                    const tplText = tplCanon.get(c);
                    if (tplText && lines[i].trim() !== tplText) { out.push(tplText); bump(`归一标题:${c}`); touched = true; }
                    else out.push(lines[i]);
                    out.push(...lines.slice(i + 1, j));
                }
                i = j;
            } else { out.push(lines[i]); i++; }
        }

        // ---- pass3: 补缺(家族缺→区域末尾追加; 子节缺→插在该家族内前一模板兄弟内容后) ----
        for (const g of groups) {
            const gCanons = g.kids.map(canon);
            const wantKids = canon(g.h3) === TZZB ? g.kids.filter((k) => qualifies(canon(k), date)) : g.kids;
            const famIdx = out.findIndex((l) => /^### /.test(l) && canon(l) === canon(g.h3));
            if (famIdx === -1) {
                if (!wantKids.length) continue;
                while (out.length && out[out.length - 1].trim() === "") out.pop();
                out.push("", g.h3, ...wantKids.flatMap((k) => ["", k]));
                touched = true; bump(`补家族:${canon(g.h3)}`);
                continue;
            }
            let famEndIdx = out.findIndex((l, idx) => idx > famIdx && /^### /.test(l));
            if (famEndIdx === -1) famEndIdx = out.length;
            let anchor = famIdx;                      // 家族内已就位的最末模板子节头行
            for (const k of wantKids) {
                const kc = canon(k);
                let found = -1;
                for (let x = famIdx + 1; x < famEndIdx; x++)
                    if (/^#### /.test(out[x]) && canon(out[x]) === kc) { found = x; break; }
                if (found !== -1) { anchor = found; continue; }
                // 缺 → 插在 anchor 块后(家族区间内下一个头行前 / 家族末尾)
                let at = famEndIdx;
                for (let x = anchor + 1; x < famEndIdx; x++) if (HEADER_RE.test(out[x])) { at = x; break; }
                out.splice(at, 0, "", k, "");
                famEndIdx += 3;
                anchor = at + 1;
                touched = true; bump(`补骨架:${kc}`);
            }
        }

        // ---- pass4: 空行收敛(3+→1; 区尾留一空行) ----
        const squeezed = [];
        for (const l of out) { if (l.trim() === "" && squeezed.length && squeezed[squeezed.length - 1].trim() === "") continue; squeezed.push(l); }
        while (squeezed.length && squeezed[squeezed.length - 1].trim() === "") squeezed.pop();
        squeezed.push("");
        if (!touched) continue;
        const rebuilt = [...lines.slice(0, fv + 1), ...squeezed, ...lines.slice(fvEnd)];
        if (rebuilt.join("\n") === lines.join("\n")) continue;
        changed++;
        if (DRY) console.log(`[dry] ${p}`);
        else fs.writeFileSync(p, rebuilt.join("\n"));
    }
}
console.log(`${DRY ? "[dry] " : ""}汇总: 扫 ${files} 文件, 改 ${changed}; 动作: ${JSON.stringify(tally)}`);
console.log(`账本开始日: ${[...starts.entries()].map(([k, v]) => `${k}=${v}`).sort().join(", ")}`);
