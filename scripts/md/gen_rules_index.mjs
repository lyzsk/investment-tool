// gen_rules_index.mjs — rules.md ### Xnn 头 → rules_index.md(B3 上下文分级加载, 2026-10-03)
// 定位: rules.md 全量 525KB 禁进 context; 常驻=元指令+profile+本索引, 需要某条全文时
//   grep -n "^### B57" skills/taoge-skill/persona/rules.md 按行号区间捞取。
// 用法: node scripts/md/gen_rules_index.mjs(幂等, rules.md 变更后随时重跑; chain 驱动器每轮自动重建)
// 产物: skills/taoge-skill/persona/rules_index.md; 出口 0=ok 1=rules.md 读取/解析异常
import fs from "node:fs";

const RULES = "skills/taoge-skill/persona/rules.md";
const OUT = "skills/taoge-skill/persona/rules_index.md";

const text = fs.readFileSync(RULES, "utf8");
const rows = [];
let cur = null;   // 当前 rule, 正文行顺收(取前 2 条要点做备注, 防 C6 式"标题零信息"漏捞)
let lineNo = 0;
for (const line of text.split("\n")) {
    lineNo++;
    const m = line.match(/^### ([A-Z]\d+) (.*)$/);
    if (m) {
        const [, id, rest] = m;
        const t = rest.match(/^(.*?)\s*\[([^\[\]]*)\]\s*$/);   // 末组 [...]=验证状态标签
        cur = { id, title: t ? t[1] : rest, tags: t ? t[2] : "", notes: [], line: lineNo };
        rows.push(cur);
        continue;
    }
    if (!cur || cur.notes.length >= 2) continue;
    const s = line.replace(/^\s*-\s*/, "").replace(/\*\*/g, "").trim();
    if (!s || s.startsWith("出生日") || s.startsWith("![")) continue;   // 画面回填/图片=溯源噪声
    cur.notes.push(s.length > 48 ? s.slice(0, 48) + "…" : s);
}
if (!rows.length) { console.error("未解析到任何 ### Xnn 规则头, rules.md 格式变了?"); process.exit(1); }

// 状态标签归并: md验证/plan-a=已验证, 待验证/话术=未验证, 已证伪/已失效=反例(索引里保留=反例优先立法)
const cls = (tags) => /已证伪|已失效/.test(tags) ? "❌" : /md 验证|plan-a|回测/.test(tags) ? "✅" : "⏳";
const groups = {};
for (const r of rows) (groups[r.id[0]] = groups[r.id[0]] || []).push(r);

const out = [`# rules_index.md — 桃哥决策规则索引(B3 分级加载; 生成于 ${new Date().toISOString().slice(0, 16).replace("T", " ")})`,
    `> 源: rules.md(${rows.length} 条/${(text.length / 1024).toFixed(0)}KB)。本索引=常驻; **禁全量读 rules.md**。`,
    `> 捞全文: grep -n "^### <编号>" skills/taoge-skill/persona/rules.md 得行号, 读到下一个 ### 前。`,
    `> 标记: ✅=已验证(md/plan-a) ⏳=待验证/话术 ❌=已证伪/已失效(反例优先, 保留)`, ""];
for (const letter of Object.keys(groups).sort()) {
    out.push(`## ${letter} 类(${groups[letter].length} 条)`);
    for (const r of groups[letter]) out.push(`- ${r.id} ${cls(r.tags)} ${r.title}｜${r.tags}${r.notes.length ? " → " + r.notes.join("；") : ""} [→正文](rules.md#L${r.line})`);
    out.push("");
}
fs.writeFileSync(OUT, out.join("\n"));
console.log(`rules_index.md: ${rows.length} 条, ${(out.join("\n").length / 1024).toFixed(1)}KB(源 ${(text.length / 1024).toFixed(0)}KB)`);
console.log(`JSON:${JSON.stringify({ rules: rows.length, outKB: +(out.join("\n").length / 1024).toFixed(1), srcKB: +(text.length / 1024).toFixed(0) })}`);
