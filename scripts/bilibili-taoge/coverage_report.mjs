// 覆盖率报告: index.json 的日期 vs stocks/*/YYYY-MM-DD.md
import fs from "fs";
import path from "path";

const ROOT = "C:/Users/admin/dev/investment-tool";
const index = JSON.parse(fs.readFileSync(path.join(ROOT, "scripts/bilibili-taoge/downloads/index.json"), "utf-8"));
const byDate = {};
for (const v of Object.values(index)) (byDate[v.date] ||= []).push(v);

const dirs = fs.readdirSync(path.join(ROOT, "stocks")).filter(d => /^20\d\dS\d$/.test(d));
let totalMd = 0, covered = 0;
for (const dir of dirs.sort()) {
  const files = fs.readdirSync(path.join(ROOT, "stocks", dir)).filter(f => f.endsWith(".md")).sort();
  let c = 0;
  const missing = [];
  for (const f of files) {
    const date = f.slice(0, 10);
    totalMd++;
    if (byDate[date]) c++;
    else missing.push(date);
  }
  covered += c;
  console.log(`${dir}: ${c}/${files.length} days covered${missing.length ? " | missing: " + (missing.length <= 12 ? missing.join(",") : missing.slice(0, 6).join(",") + " ... " + missing.slice(-3).join(",")) : ""}`);
}
console.log(`\nTOTAL: ${covered}/${totalMd}`);
// 视频数 vs 天数: 有些天可能多个视频
const multi = Object.entries(byDate).filter(([, v]) => v.length > 1);
console.log("days with >1 video:", multi.length);
