// sync_skills.mjs — skills/ → .claude/skills/ 双副本同步(2026-10-07 建, 替代逐文件手工 cp)
// 纪律: skills/ 是 canonical(git 版本化); .claude/skills/ 是 headless `claude -p /<skill>` 的实际加载点。
// 规则: 镜像 skills/ 下每个目录到目标(先删目标同名再整拷, 天然处理目录内改名);
//       目标独有目录不动, 打印供人核对。
// 注意: **skill 整体重命名/废弃后, 目标里的旧目录不会自动消失**——extra 清单会列出, 确认废弃后手工删。
// 用法: node scripts/sync_skills.mjs   (编辑 skills/ 任何文件后必跑; 旧 SKILL.md 里的"cp ... "手工纪律全部由本脚本取代)
import fs from "fs";
import path from "path";

const SRC = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")), "..", "skills");
const DST = path.resolve(SRC, "..", ".claude", "skills");

let copied = 0;
for (const e of fs.readdirSync(SRC, { withFileTypes: true })) {
  if (!e.isDirectory()) continue;
  const d = path.join(DST, e.name);
  fs.rmSync(d, { recursive: true, force: true });
  fs.cpSync(path.join(SRC, e.name), d, { recursive: true });
  copied++;
  console.log("synced:", e.name);
}
const srcSet = new Set(fs.readdirSync(SRC));
const extra = fs.readdirSync(DST, { withFileTypes: true })
  .filter((x) => x.isDirectory() && !srcSet.has(x.name))
  .map((x) => x.name);
if (extra.length) console.log("目标独有(不动; 若是废弃旧名请手工删):", extra.join(", "));
console.log("JSON:" + JSON.stringify({ copied, extra: extra.length }));
