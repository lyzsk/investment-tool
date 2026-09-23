// 等 medium 批跑完(transcribe_txt_medium.done)后自动收尾:
//   1) correct_names.py txt_medium -> txt_medium_fixed (股名拼音纠错)
//   2) inject_md.mjs --dir txt_medium_fixed --replace (替换 md 中已有 ### 桃哥 小节)
// 日志: downloads/finalize.log
import fs from "fs";
import { spawnSync } from "child_process";

const DIR = "C:/Users/admin/dev/investment-tool/scripts/bilibili-taoge";
const DONE = DIR + "/downloads/transcribe_txt_medium.done";
const LOG = DIR + "/downloads/finalize.log";
const PY = DIR + "/venv/Scripts/python.exe";
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const log = (m) => {
  const line = `[${new Date().toLocaleString("zh-CN", { hour12: false })}] ${m}`;
  fs.appendFileSync(LOG, line + "\n");
};

for (let i = 0; i < 720; i++) { // 最多等 12 小时
  if (fs.existsSync(DONE)) break;
  await sleep(60000);
}
if (!fs.existsSync(DONE)) { log("timeout waiting for medium batch"); process.exit(1); }

log("medium done, running correct_names...");
let r = spawnSync(PY, ["correct_names.py", "txt_medium", "txt_medium_fixed"], { cwd: DIR, encoding: "utf-8" });
log("correct_names: " + (r.stdout || "").trim() + (r.status !== 0 ? " ERR:" + r.stderr : ""));

log("injecting...");
r = spawnSync("node", ["inject_md.mjs", "--dir", "txt_medium_fixed", "--replace"], { cwd: DIR, encoding: "utf-8" });
log("inject: " + (r.stdout || "").trim() + (r.status !== 0 ? " ERR:" + r.stderr : ""));
log("finalize complete");
process.exit(0);
