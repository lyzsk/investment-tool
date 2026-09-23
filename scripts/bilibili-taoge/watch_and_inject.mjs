// 等待 transcribe.done 出现, 然后自动执行 inject_md.mjs, 结果写 downloads/inject.log
import fs from "fs";
import path from "path";
import { execSync } from "child_process";

const DIR = "C:/Users/admin/dev/investment-tool/scripts/bilibili-taoge";
const DONE = path.join(DIR, "downloads", "transcribe.done");
const LOG = path.join(DIR, "downloads", "inject.log");
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

for (let i = 0; i < 360; i++) { // 最多等 6 小时
  if (fs.existsSync(DONE)) {
    try {
      const out = execSync("node inject_md.mjs", { cwd: DIR, encoding: "utf-8" });
      fs.writeFileSync(LOG, `[${new Date().toISOString()}] inject ok\n${out}\n`);
    } catch (e) {
      fs.writeFileSync(LOG, `[${new Date().toISOString()}] inject FAIL\n${e.message}\n${e.stdout || ""}\n${e.stderr || ""}\n`);
    }
    process.exit(0);
  }
  await sleep(60000);
}
fs.writeFileSync(LOG, `[${new Date().toISOString()}] timeout waiting for transcribe.done\n`);
process.exit(1);
