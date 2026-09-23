// 桃哥(股市-目标1000万的股桃, mid=625315686) 最新视频发现 + 音频下载
// 方案B: 无cookie。用 search.bilibili.com HTML 页(不风控)发现视频, view/playurl API 取详情和音频。
// 用法: node fetch_taoge.mjs [--bvid BVxxxx] [--out <dir>]
import fs from "fs";
import path from "path";

const UA = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
  "Accept-Language": "zh-CN,zh;q=0.9",
};
const MID = 625315686;
const KEYWORDS = ["股桃", "桃哥复盘"];

function arg(name) {
  const i = process.argv.indexOf("--" + name);
  return i >= 0 ? process.argv[i + 1] : null;
}

async function getJson(url, referer = "https://www.bilibili.com") {
  const r = await fetch(url, { headers: { ...UA, Referer: referer } });
  const t = await r.text();
  if (t.startsWith("<")) throw new Error("risk-blocked: " + url.slice(0, 80));
  return JSON.parse(t);
}

async function discover() {
  const found = new Map(); // bvid -> {bvid,title,pubdate}
  for (const kw of KEYWORDS) {
    for (let page = 1; page <= 2; page++) {
      const url = `https://search.bilibili.com/video?keyword=${encodeURIComponent(kw)}&order=pubdate&page=${page}`;
      try {
        const r = await fetch(url, { headers: UA });
        const html = await r.text();
        const re = /bvid:"(BV1[a-zA-Z0-9]{9})",title:"((?:[^"\\]|\\.)*)",pubdate:(\d+)/g;
        for (const m of html.matchAll(re)) {
          if (!found.has(m[1])) found.set(m[1], { bvid: m[1], title: m[2], pubdate: +m[3] });
        }
      } catch (e) {
        console.error(`search page fail kw=${kw} page=${page}: ${e.message}`);
      }
    }
  }
  // 用 view API 校验确实是桃哥的视频(搜索结果可能混入转载/同名)
  const his = [];
  for (const c of [...found.values()].sort((a, b) => b.pubdate - a.pubdate).slice(0, 12)) {
    try {
      const v = await getJson(`https://api.bilibili.com/x/web-interface/view?bvid=${c.bvid}`);
      if (v.code === 0 && v.data.owner.mid === MID) {
        his.push({ ...c, cid: v.data.cid, desc: v.data.desc, duration: v.data.duration, title: v.data.title });
      }
    } catch (e) {
      console.error(`view fail ${c.bvid}: ${e.message}`);
    }
  }
  return his.sort((a, b) => b.pubdate - a.pubdate);
}

async function downloadAudio(bvid, cid, outDir) {
  const play = await getJson(`https://api.bilibili.com/x/player/playurl?bvid=${bvid}&cid=${cid}&fnval=16&fourk=0`);
  const audios = play.data?.dash?.audio || [];
  if (!audios.length) throw new Error("no audio track (may need retry/login for this video)");
  // 取码率最低的音轨, ASR 足够
  const track = audios[0];
  const r = await fetch(track.baseUrl, { headers: { ...UA, Referer: "https://www.bilibili.com" } });
  const buf = Buffer.from(await r.arrayBuffer());
  const out = path.join(outDir, `${bvid}.m4a`);
  fs.writeFileSync(out, buf);
  return out;
}

async function main() {
  const outDir = arg("out") || path.join(process.cwd(), "downloads");
  fs.mkdirSync(outDir, { recursive: true });

  let video = null;
  const bvid = arg("bvid");
  if (bvid) {
    const v = await getJson(`https://api.bilibili.com/x/web-interface/view?bvid=${bvid}`);
    if (v.code !== 0) throw new Error("view api: " + v.message);
    video = { bvid, cid: v.data.cid, title: v.data.title, pubdate: v.data.pubdate, desc: v.data.desc, duration: v.data.duration };
  } else {
    const his = await discover();
    if (!his.length) throw new Error("no videos found for mid " + MID);
    console.log("recent videos:");
    for (const v of his) console.log(`  ${v.bvid} | ${v.title} | ${new Date(v.pubdate * 1000).toLocaleString("zh-CN", { hour12: false })}`);
    video = his[0];
  }

  console.log(`\ntarget: ${video.bvid} | ${video.title} | duration=${video.duration}s`);
  const audioPath = await downloadAudio(video.bvid, video.cid, outDir);
  const metaPath = path.join(outDir, `${video.bvid}.json`);
  fs.writeFileSync(metaPath, JSON.stringify(video, null, 2));
  console.log("audio:", audioPath, fs.statSync(audioPath).size, "bytes");
  console.log("meta:", metaPath);
}

main().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
