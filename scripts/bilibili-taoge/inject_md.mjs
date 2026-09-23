// 把转写结果注入 stocks/*/YYYY-MM-DD.md 的 ## 复盘 下 (### 桃哥)
// 默认幂等(已有 ### 桃哥 则跳过); --replace 替换已有小节内容; --dir <txt目录名> 默认 txt
import fs from "fs";
import path from "path";

const ROOT = "C:/Users/admin/dev/investment-tool";
const DIR = path.join(ROOT, "scripts/bilibili-taoge/downloads");
const args = process.argv.slice(2);
const REPLACE = args.includes("--replace");
const dirIdx = args.indexOf("--dir");
const TXT_DIR = dirIdx >= 0 ? args[dirIdx + 1] : "txt";
const SKIP_DATES = new Set(REPLACE ? ["2026-09-18"] : []); // 9/18 是手工精修版, 不覆盖
const worklist = JSON.parse(fs.readFileSync(path.join(DIR, "worklist.json"), "utf-8"));

const txtPathOf = (bvid) => path.join(DIR, TXT_DIR, `${bvid}.txt`);
const fmtTime = (ts) => {
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

function buildSection(date, videos) {
  const parts = ["### 桃哥", ""];
  for (const v of videos) {
    const txtPath = txtPathOf(v.bvid);
    if (!fs.existsSync(txtPath)) continue;
    const lines = fs.readFileSync(txtPath, "utf-8").split("\n").map(s => s.trim()).filter(Boolean);
    const mins = v.duration >= 60 ? `${Math.round(v.duration / 60)} 分钟` : `${v.duration} 秒`;
    parts.push(`**[${v.title}](https://www.bilibili.com/video/${v.bvid})** · ${fmtTime(v.pubdate)} 发布 · ${mins} ·（语音转写）`, "");
    for (let i = 0; i < lines.length; i += 4) {
      parts.push("> " + lines.slice(i, i + 4).join(""), "");
    }
  }
  const anaPath = path.join(DIR, "analysis", `${date}.json`);
  if (fs.existsSync(anaPath)) {
    const a = JSON.parse(fs.readFileSync(anaPath, "utf-8"));
    const STANCE = { bullish: "看多", bearish: "看空", watch: "观察", avoid: "避开" };
    parts.push("#### 解读", "");
    if (a.market_view) parts.push(`- **大盘判断**: ${a.market_view}`);
    if (a.mentions?.length) {
      parts.push("- **提及个股**:");
      for (const m of a.mentions) {
        const alias = m.asr_aliases?.length ? `（转写别名: ${m.asr_aliases.join("/")}）` : "";
        const pos = m.his_position ? ` 【桃哥: ${m.his_position}】` : "";
        parts.push(`  - ${m.name}${m.code ? "(" + m.code + ")" : ""} · ${STANCE[m.stance] || m.stance}${m.action ? " · " + m.action : ""}${alias} — ${m.logic || ""}${pos}`);
      }
    }
    if (a.operations_today?.length) parts.push(`- **桃哥今日操作**: ${a.operations_today.join("; ")}`);
    if (a.tomorrow_implication) {
      const ti = a.tomorrow_implication;
      const seg = [];
      if (ti.关注?.length) seg.push("关注 " + ti.关注.map(x => `${x.name}${x.code ? "(" + x.code + ")" : ""}${x.trigger ? ": " + x.trigger : ""}`).join("、"));
      if (ti.避开?.length) seg.push("避开 " + ti.避开.map(x => `${x.name}${x.reason ? ": " + x.reason : ""}`).join("、"));
      if (seg.length) parts.push(`- **明日策略**: ${seg.join("; ")}`);
    }
    if (a.style_rules?.length) parts.push(`- **风格规则**: ${a.style_rules.map((r, i) => `${i + 1})${r}`).join(" ")}`);
    if (a.confidence) parts.push(`- 提取置信度: ${a.confidence}`);
    parts.push("");
  }
  return parts.join("\n").replace(/\n{3,}/g, "\n\n").trim() + "\n";
}

let injected = 0, replaced = 0, skippedHas = 0, skippedNoTxt = 0, noHeading = [];
for (const [date, videos] of Object.entries(worklist)) {
  if (SKIP_DATES.has(date)) continue;
  const withTxt = videos.filter(v => fs.existsSync(txtPathOf(v.bvid)));
  if (!withTxt.length) { skippedNoTxt++; continue; }
  const quarter = `20${date.slice(2, 4)}S${Math.ceil(+date.slice(5, 7) / 3)}`;
  const mdPath = path.join(ROOT, "stocks", quarter, `${date}.md`);
  if (!fs.existsSync(mdPath)) { console.log("md missing:", mdPath); continue; }
  const content = fs.readFileSync(mdPath, "utf-8");
  const section = "\n" + buildSection(date, withTxt) + "\n";

  const existM = content.match(/^### 桃哥[ \t]*$/m);
  if (existM && !REPLACE) { skippedHas++; continue; }
  if (existM && REPLACE) {
    // 替换: 从 ### 桃哥 行到下一个同级/更高级标题行之间
    const start = existM.index;
    const rest = content.slice(start + existM[0].length);
    const nextH = rest.search(/^#{2,3} /m);
    const end = nextH >= 0 ? start + existM[0].length + nextH : content.length;
    fs.writeFileSync(mdPath, content.slice(0, start) + section.trim() + "\n\n" + content.slice(end).replace(/^\n+/, ""));
    replaced++;
    continue;
  }

  const m = content.match(/^## 复盘[ \t]*$/m);
  let next;
  if (m) {
    const at = m.index + m[0].length;
    next = content.slice(0, at) + "\n" + section + content.slice(at);
  } else {
    noHeading.push(date);
    next = content.trimEnd() + "\n\n## 复盘\n" + section;
  }
  fs.writeFileSync(mdPath, next);
  injected++;
}
console.log(`dir=${TXT_DIR} replace=${REPLACE} | injected=${injected} replaced=${replaced} skipped(has)=${skippedHas} skipped(no txt)=${skippedNoTxt} no-heading=${noHeading.length}`);
if (noHeading.length) console.log(noHeading.join(","));
