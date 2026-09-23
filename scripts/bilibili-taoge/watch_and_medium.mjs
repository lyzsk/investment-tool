// 等 small 批跑完(transcribe.done)后, 自动启动 medium 重跑到 txt_medium/, 日志 transcribe_txt_medium.log
import fs from "fs";
import { spawn } from "child_process";

const DIR = "C:/Users/admin/dev/investment-tool/scripts/bilibili-taoge";
const DONE = DIR + "/downloads/transcribe.done";
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

for (let i = 0; i < 360; i++) {
  if (fs.existsSync(DONE)) {
    const p = spawn(DIR + "/venv/Scripts/python.exe", ["batch_transcribe.py", "medium", "txt_medium"],
      { cwd: DIR, detached: true, stdio: "ignore", windowsHide: true });
    p.unref();
    process.exit(0);
  }
  await sleep(60000);
}
process.exit(1);
