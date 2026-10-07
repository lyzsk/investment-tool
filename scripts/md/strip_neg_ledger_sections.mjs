// strip_neg_ledger_sections.mjs — 一次性: 从全部历史 md 剥离负样本账本小节(2026-10-07)
// 背景: 10/7 晨间自动链把 tzzb_ledgers.json 全部 15 账本(含 4 个 kind=neg)机械镜像进了
//       模板与 md; 用户立法(10/7): 负样本不开账本/不进 md, 只作反例规则语料(05 风控禁手清单)。
//       原料无损: downloads/tzzb/<neg>/ 与 DB 不动; gen_tzzb_md.mjs 已加 neg 闸防再生。
// 逻辑: 删除 `#### <neg 名>` 小节整块(标题+内容, 至下一个任意级别标题行), 吞标题前空行防双空行。
// 用法: node scripts/md/strip_neg_ledger_sections.mjs [--dry]
// 幂等: 剥完重跑=0 改动。
import fs from "fs";
import path from "path";

const DRY = process.argv.includes("--dry");
const LEDGERS = JSON.parse(fs.readFileSync("scripts/tzzb/tzzb_ledgers.json", "utf8"));
const NEG = LEDGERS.filter((l) => l.kind === "neg");
const canon = (s) => s.replace(/^#+\s*/, "").replace(/\s+/g, "").toLowerCase();
const negHeads = new Set(NEG.map((l) => canon(l.name)));

let files = 0, changed = 0, removed = 0;
for (const dir of fs.readdirSync("md").filter((d) => fs.statSync(path.join("md", d)).isDirectory()).sort()) {
    for (const f of fs.readdirSync(path.join("md", dir)).filter((f) => f.endsWith(".md")).sort()) {
        files++;
        const p = path.join("md", dir, f);
        const lines = fs.readFileSync(p, "utf8").split("\n");
        const out = [];
        let cut = false, n = 0;
        for (const line of lines) {
            if (/^####\s/.test(line) && negHeads.has(canon(line))) {
                if (out.length && out[out.length - 1].trim() === "") out.pop(); // 吞前空行
                cut = true; n++;
                continue;
            }
            if (cut && /^#{1,4}\s/.test(line)) { // 下一标题=小节边界, 补回分隔空行
                cut = false;
                if (out.length && out[out.length - 1] !== "") out.push("");
            }
            if (cut) continue;
            out.push(line);
        }
        const text = out.join("\n").replace(/\n{3,}/g, "\n\n");
        if (text !== lines.join("\n")) {
            changed++;
            removed += n;
            if (!DRY) fs.writeFileSync(p, text);
            else console.log(`[dry] ${p}: -${n} 节`);
        }
    }
}
console.log(`${DRY ? "[dry] " : ""}汇总: 扫 ${files} 文件, 改 ${changed}, 剥除 ${removed} 个负样本小节 (${NEG.map((l) => l.name).join("/")})`);
