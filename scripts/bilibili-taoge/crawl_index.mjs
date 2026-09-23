// BFS 爬取桃哥全部历史视频索引: archive/related API 无需登录、不风控
// 输出 downloads/index.json: { bvid: {title, pubdate, date, duration} }
import fs from "fs";
import path from "path";

const UA = { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36", "Accept-Language": "zh-CN,zh;q=0.9", "Referer": "https://www.bilibili.com" };
const MID = 625315686;
const OUT_DIR = path.join(process.cwd(), "downloads");
const INDEX = path.join(OUT_DIR, "index.json");
const MAX_REQUESTS = 800;
const DELAY_MS = 700;

async function getJson(url) {
  const r = await fetch(url, { headers: UA });
  const t = await r.text();
  if (t.startsWith("<")) throw new Error("blocked");
  return JSON.parse(t);
}
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const fmtDate = (ts) => {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

const index = fs.existsSync(INDEX) ? JSON.parse(fs.readFileSync(INDEX, "utf-8")) : {};
let frontier = Object.keys(index).length ? [] : ["BV1Moe16hEgL", "BV12eeg6bEd2", "BV1tfew6gE4v", "BV1Vde76tE33", "BV1jWYk6YE1m", "BV1sqYi68ESj", "BV1apYL6EEoc", "BV1NNYM6mEpS", "BV1tQYx6uERM", "BV1Dv411b7UX"];
const visited = new Set();

let requests = 0, errors = 0;
while (frontier.length && requests < MAX_REQUESTS) {
  const bvid = frontier.shift();
  if (visited.has(bvid)) continue;
  visited.add(bvid);
  try {
    const j = await getJson(`https://api.bilibili.com/x/web-interface/archive/related?bvid=${bvid}`);
    requests++;
    for (const v of j.data || []) {
      if (v.owner?.mid !== MID) continue;
      if (!index[v.bvid]) {
        index[v.bvid] = { title: v.title, pubdate: v.pubdate, date: fmtDate(v.pubdate), duration: v.duration };
      }
      if (!visited.has(v.bvid)) frontier.push(v.bvid);
    }
    // 种子本身也要入索引
    if (!index[bvid]) {
      try {
        const v = await getJson(`https://api.bilibili.com/x/web-interface/view?bvid=${bvid}`);
        requests++;
        if (v.code === 0 && v.data.owner.mid === MID) {
          index[bvid] = { title: v.data.title, pubdate: v.data.pubdate, date: fmtDate(v.data.pubdate), duration: v.data.duration };
        }
      } catch {}
    }
    if (requests % 20 === 0) {
      fs.writeFileSync(INDEX, JSON.stringify(index, null, 1));
      console.log(`requests=${requests} index=${Object.keys(index).length} frontier=${frontier.length}`);
    }
  } catch (e) {
    errors++;
    console.error(`err ${bvid}: ${e.message}`);
    if (errors > 10) { console.error("too many errors, stop"); break; }
    await sleep(5000);
  }
  await sleep(DELAY_MS);
}
fs.writeFileSync(INDEX, JSON.stringify(index, null, 1));
console.log(`DONE. requests=${requests} total videos indexed=${Object.keys(index).length}`);
const dates = [...new Set(Object.values(index).map(v => v.date))].sort();
console.log("date range:", dates[0], "~", dates[dates.length - 1], "| distinct days:", dates.length);
