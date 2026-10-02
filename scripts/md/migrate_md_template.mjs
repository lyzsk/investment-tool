// migrate_md_template.mjs — md 复盘结构同步器(2026-10-02 v2: 模板驱动常备工具)
// 用户立法: stock-template.md 每次变更后跑本脚本批量同步所有历史 md
// 用法: node scripts/migrate_md_template.mjs [--dry] [dir...]   默认 md/2025S1..2026S4
// 能力:
//   ①模板驱动: 复盘骨架(## 复盘 ~ 下一个 ## 之间的 ###/#### 标题行)从 stock-template.md 现读, 不写死
//   ②标题归一: 同义变体(空格/大小写差异, 如 `股市-桃哥复盘` vs `股市 - 桃哥复盘`, `Bilibili` vs `bilibili`)
//     一律改写为模板原文; 匹配键=去空格小写
//   ③缺节补骨架: 模板里有而 md 里没有的 ###/#### 骨架节, 按模板顺序补在 ## 复盘 末尾
//   ④遗产迁移: 旧 `### 桃哥` 小节内容搬进模板的桃哥节(内部 #### 降一级), 一次性历史逻辑, 找不到就跳过
//   ⑤模式C: 无 ## 复盘 的文件跳过(上古格式不强扭)
// 幂等: 全量同步后重跑=全跳过
import fs from "fs";
import path from "path";

const DRY = process.argv.includes("--dry");
const dirs = process.argv.slice(2).filter((a) => !a.startsWith("--"));
const targets = dirs.length
    ? dirs
    : ["2025S1", "2025S2", "2025S3", "2025S4", "2026S1", "2026S2", "2026S3", "2026S4"].map(
          (d) => path.join("md", d));

const TEMPLATE = path.resolve("inv-stock/src/main/resources/templates/stock-template.md");

// 归一键: 去空格小写(中英文标题通用)
const canon = (s) => s.replace(/^#+\s*/, "").replace(/\s+/g, "").toLowerCase();

// ---- 从模板读复盘骨架: ## 复盘 到下一个 ## 之间的标题行(保持顺序与层级) ----
function readSkeleton() {
    const lines = fs.readFileSync(TEMPLATE, "utf8").split("\n");
    const s = lines.findIndex((l) => /^## 复盘\s*$/.test(l));
    if (s === -1) throw new Error("模板缺 ## 复盘");
    const skel = [];
    for (let i = s + 1; i < lines.length; i++) {
        if (/^## /.test(lines[i])) break;
        if (/^#{3,4} /.test(lines[i])) skel.push(lines[i].trim());
    }
    return skel;
}

function migrate(file, skel) {
    const lines = fs.readFileSync(file, "utf8").split("\n");
    const acts = [];

    // ④ 遗产 ### 桃哥 抽离(内容暂存, 稍后挂进模板桃哥节)
    let legacy = [];
    const tg = lines.findIndex((l) => /^### 桃哥\s*$/.test(l));
    let work = [...lines];
    if (tg !== -1) {
        let tgEnd = work.length;
        for (let i = tg + 1; i < work.length; i++) {
            if (/^#{1,3} /.test(work[i])) { tgEnd = i; break; }
        }
        legacy = work.slice(tg + 1, tgEnd);
        while (legacy.length && legacy[0].trim() === "") legacy.shift();
        while (legacy.length && legacy[legacy.length - 1].trim() === "") legacy.pop();
        legacy = legacy.map((l) => (/^#{4,5} /.test(l) ? "#" + l : l));
        work.splice(tg, tgEnd - tg);
        acts.push("遗产桃哥抽离");
    }

    // 模式C: 无 ## 复盘
    const fv = work.findIndex((l) => /^## 复盘\s*$/.test(l));
    if (fv === -1) return legacy.length ? "异常:无复盘但有桃哥" : null;
    let fvEnd = work.length;
    for (let i = fv + 1; i < work.length; i++) {
        if (/^## /.test(work[i])) { fvEnd = i; break; }
    }

    // ② 标题归一: 复盘区间内, 归一键命中模板骨架的标题行→改写为模板原文
    const skelByCanon = new Map(skel.map((h) => [canon(h), h]));
    for (let i = fv + 1; i < fvEnd; i++) {
        if (!/^#{3,4} /.test(work[i])) continue;
        const c = canon(work[i]);
        if (skelByCanon.has(c) && work[i].trim() !== skelByCanon.get(c)) {
            work[i] = skelByCanon.get(c);
            acts.push(`归一:${c}`);
            // 行数不变, fvEnd 有效
        }
    }

    // ③ 缺节补骨架: 按模板顺序, 缺的挂到复盘末尾(保持模板相对顺序)
    const present = new Set();
    for (let i = fv + 1; i < fvEnd; i++) {
        if (/^#{3,4} /.test(work[i])) present.add(canon(work[i]));
    }
    const missing = skel.filter((h) => !present.has(canon(h)));
    if (missing.length) {
        // 重定位复盘尾(归一不改行数, fvEnd 仍有效)
        let ins = fvEnd;
        while (ins > fv + 1 && work[ins - 1].trim() === "") ins--;
        const block = [""];
        for (const h of missing) {
            block.push(h, "");
            // 桃哥节补骨架时, 遗产内容一并挂进去
            if (legacy.length && canon(h).includes("桃哥复盘")) {
                block.push(...legacy, "");
                acts.push(`遗产内容挂入${h}`);
                legacy = [];
            }
        }
        work.splice(ins, 0, ...block);
        acts.push(`补骨架:${missing.map((h) => canon(h)).join("/")}`);
        // fvEnd 之后可能还有内容, 插空行已在 block 里
    }
    if (legacy.length) return "异常:遗产桃哥无处挂(模板缺桃哥节)";

    if (!acts.length) return null;
    if (!DRY) fs.writeFileSync(file, work.join("\n"));
    return acts.join(",");
}

const skel = readSkeleton();
console.log(`${DRY ? "[dry] " : ""}模板骨架: ${skel.join(" → ")}`);
let changed = 0, skippedC = 0, anomalies = [];
const all = new Set(skel.map(canon));
// 幂等判据: 复盘区标题集 ⊇ 模板骨架 且文本全等于模板原文 → migrate 自然返回 null
for (const dir of targets) {
    if (!fs.existsSync(dir)) continue;
    for (const f of fs.readdirSync(dir).filter((f) => f.endsWith(".md")).sort()) {
        const r = migrate(path.join(dir, f), skel);
        if (r === null) { skippedC++; continue; }
        if (r.startsWith("异常")) { anomalies.push(`${dir}/${f}: ${r}`); continue; }
        changed++;
        if (DRY) console.log(`[dry] ${dir}/${f}: ${r}`);
    }
}
console.log(`${DRY ? "[dry] " : ""}汇总: 改动 ${changed}, 跳过(已同步或无复盘) ${skippedC}, 异常 ${anomalies.length}`);
anomalies.forEach((a) => console.log("  " + a));
