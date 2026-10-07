// dedup_review_sections.mjs — 复盘区重复小节去重合并(2026-10-07 一次性, 配合 sync_review_sections)
// 背景: 10/7 晨链把部分新骨架节(趋势天哥/st之狼/冲5000w/高概率/宣秋/大兴)追加到了错误家族位置,
//       sync 的家族作用域查找看不见 → 又补了正确位 → 同名节双份。
// 规则: 模板同名 #### 节 >1 份时——保留"正确家族区间内"的那份, 其余非空内容并入保留节, 多余整块删除;
//       非模板节(个股 #### 等)即使同名也不动。幂等: 重跑=0 改动。
import fs from "fs";
import path from "path";

const canon = (s) => s.replace(/^#+\s*/, "").replace(/\s+/g, "").toLowerCase();
const HEADER_RE = /^#{3,4} /;

// 模板: kidCanon -> 所属家族 ### canon
const tplLines = fs.readFileSync("inv-stock/src/main/resources/templates/stock-template.md", "utf8").split("\n");
const fs_ = tplLines.findIndex((l) => /^## 复盘\s*$/.test(l));
const kidFam = new Map();
const fams = [];
for (let i = fs_ + 1; i < tplLines.length && !/^## /.test(tplLines[i]); i++) {
    if (/^### /.test(tplLines[i])) fams.push(canon(tplLines[i]));
    else if (/^#### /.test(tplLines[i]) && fams.length) kidFam.set(canon(tplLines[i]), fams[fams.length - 1]);
}

let changed = 0;
const tally = {};
for (const dir of fs.readdirSync("md").filter((d) => fs.statSync(path.join("md", d)).isDirectory()).sort()) {
    for (const f of fs.readdirSync(path.join("md", dir)).filter((x) => x.endsWith(".md")).sort()) {
        const p = path.join("md", dir, f);
        let lines = fs.readFileSync(p, "utf8").split("\n");
        const fv = lines.findIndex((l) => /^## 复盘\s*$/.test(l));
        if (fv === -1) continue;
        const regionEnd = () => lines.findIndex((l, i) => i > fv && /^## /.test(l));
        const end0 = regionEnd();
        const R = () => (regionEnd() === -1 ? lines.length : regionEnd());

        const parse = () => {
            const bs = [];
            for (let i = fv + 1; i < R(); i++) {
                if (HEADER_RE.test(lines[i])) bs.push({ canon: canon(lines[i]), hdr: i, end: i });
                else if (bs.length) bs[bs.length - 1].end = i;
            }
            return bs;
        };
        const famSpan = (fam) => {
            const h = lines.findIndex((l, i) => i > fv && i < R() && /^### /.test(l) && canon(l) === fam);
            if (h === -1) return [-1, -1];
            let e = R();
            for (let i = h + 1; i < R(); i++) if (/^### /.test(lines[i])) { e = i; break; }
            return [h, e];
        };

        let touched = false;
        for (const c of [...kidFam.keys()]) {
            const same = parse().filter((b) => b.canon === c);
            if (same.length < 2) continue;
            const [hs, he] = famSpan(kidFam.get(c));
            const keeper = same.find((b) => b.hdr > hs && b.hdr < he) || same[0];
            const keepCont = lines.slice(keeper.hdr + 1, keeper.end + 1);
            // ① 错位份的非空内容并入保留节(去重)
            const merged = [];
            for (const l of same.filter((b) => b !== keeper))
                for (const x of lines.slice(l.hdr + 1, l.end + 1))
                    if (x.trim() !== "" && !keepCont.includes(x) && !merged.includes(x)) merged.push(x);
            if (merged.length) { lines.splice(keeper.end + 1, 0, "", ...merged); touched = true; }
            // ② 重解析后删除多余份(从大行号往小删)
            const [hs1, he1] = famSpan(kidFam.get(c));
            const same1 = parse().filter((b) => b.canon === c);
            const k1 = same1.find((b) => b.hdr > hs1 && b.hdr < he1) || same1[0];
            for (const b of same1.filter((x) => x !== k1).sort((a, b) => b.hdr - a.hdr)) {
                let e = R();
                for (let i = b.hdr + 1; i < R(); i++) if (HEADER_RE.test(lines[i])) { e = i; break; }
                lines.splice(b.hdr, e - b.hdr);
                touched = true;
            }
            tally[c] = (tally[c] || 0) + 1;
        }
        if (!touched) continue;
        // 空行收敛
        const body = lines.slice(fv + 1, R());
        const sq = [];
        for (const l of body) { if (l.trim() === "" && sq.length && sq[sq.length - 1].trim() === "") continue; sq.push(l); }
        while (sq.length && sq[sq.length - 1].trim() === "") sq.pop();
        sq.push("");
        const rebuilt = [...lines.slice(0, fv + 1), ...sq, ...lines.slice(R())];
        if (rebuilt.join("\n") !== fs.readFileSync(p, "utf8")) { changed++; fs.writeFileSync(p, rebuilt.join("\n")); }
    }
}
console.log(`汇总: 改 ${changed} 文件; 去重 canon: ${JSON.stringify(tally)}`);
