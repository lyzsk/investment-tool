// 追溯准备: 用 index.json ∩ stocks/*.md 日期 生成工作清单并批量下载音频(可断点续跑)
import fs from "fs";
import path from "path";

const ROOT = "C:/Users/admin/dev/investment-tool";
const DIR = path.join(ROOT, "scripts/bilibili-taoge/downloads");
const AUDIO_DIR = path.join(DIR, "audio");
const UA = { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36", "Referer": "https://www.bilibili.com" };

fs.mkdirSync(AUDIO_DIR, { recursive: true });
fs.mkdirSync(path.join(DIR, "txt"), { recursive: true });

const index = JSON.parse(fs.readFileSync(path.join(DIR, "index.json"), "utf-8"));

// stocks 下所有 md 日期
const mdDates = new Set();
for (const d of fs.readdirSync(path.join(ROOT, "stocks"))) {
  if (!/^20\d\dS\d$/.test(d)) continue;
  for (const f of fs.readdirSync(path.join(ROOT, "stocks", d))) {
    if (/^20\d\d-\d\d-\d\d\.md$/.test(f)) mdDates.add(f.slice(0, 10));
  }
}

// 工作清单: 交易日且有视频
const worklist = {};
for (const [bvid, v] of Object.entries(index)) {
  if (!mdDates.has(v.date)) continue;
  (worklist[v.date] ||= []).push({ bvid, ...v });
}
for (const arr of Object.values(worklist)) arr.sort((a, b) => a.pubdate - b.pubdate);
fs.writeFileSync(path.join(DIR, "worklist.json"), JSON.stringify(worklist, null, 1));

const all = Object.values(worklist).flat();
console.log(`trading days with videos: ${Object.keys(worklist).length}, videos to process: ${all.length}`);
const totalSec = all.reduce((s, v) => s + (v.duration || 0), 0);
console.log(`total audio duration: ${(totalSec / 3600).toFixed(1)}h`);

// 下载音频(跳过已有 txt 或已有音频)
async function getJson(url) {
  const r = await fetch(url, { headers: UA });
  const t = await r.text();
  if (t.startsWith("<")) throw new Error("blocked");
  return JSON.parse(t);
}
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

let done = 0, skipped = 0, failed = [];
for (const v of all) {
  const audioPath = path.join(AUDIO_DIR, `${v.bvid}.m4a`);
  const txtPath = path.join(DIR, "txt", `${v.bvid}.txt`);
  if (fs.existsSync(txtPath)) { skipped++; continue; }
  if (fs.existsSync(audioPath) && fs.statSync(audioPath).size > 10000) { skipped++; continue; }
  try {
    const view = await getJson(`https://api.bilibili.com/x/web-interface/view?bvid=${v.bvid}`);
    if (view.code !== 0) throw new Error("view: " + view.message);
    const play = await getJson(`https://api.bilibili.com/x/player/playurl?bvid=${v.bvid}&cid=${view.data.cid}&fnval=16&fourk=0`);
    const track = play.data?.dash?.audio?.[0];
    if (!track) throw new Error("no audio track");
    const r = await fetch(track.baseUrl, { headers: UA });
    fs.writeFileSync(audioPath, Buffer.from(await r.arrayBuffer()));
    done++;
    if (done % 20 === 0) console.log(`downloaded ${done}, skipped ${skipped}, failed ${failed.length}`);
  } catch (e) {
    failed.push({ bvid: v.bvid, err: e.message });
    await sleep(3000);
  }
  await sleep(400);
}
console.log(`DONE download: new=${done} skip=${skipped} failed=${failed.length}`);
if (failed.length) console.log("failed:", JSON.stringify(failed));
