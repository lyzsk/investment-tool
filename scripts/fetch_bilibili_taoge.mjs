// 桃哥(股市-目标1000万的股桃, mid=625315686) 视频发现 + 产物下载(2026-09-27 由 fetch_taoge.mjs + fetch_video.mjs 合并)
// 方案B: 无cookie。用 search.bilibili.com HTML 页(不风控)发现视频, view/playurl API 取详情和流地址。
// 用法:
//   node fetch_bilibili_taoge.mjs --list        # 只发现不下载, stdout 末行 "JSON:[...]" (Java BilibiliVideoHandler 发现段消费)
//   node fetch_bilibili_taoge.mjs [--bvid BVxxxx] [--out <目录>] [--video-only|--audio-only]
//                                               # 下载产物 → <outDir>/<bvid>.mp4(画面,视觉用) + .m4a(音轨,ASR用) + .json(源元数据=view API原始响应全文+抓取信封)
//   --bvid 不传=下最新一个; --out 不传默认 cwd/downloads, 传了=精确落盘目录(Java 传 downloads/bilibili/<作者mid>/<yyyy.MM.dd>, TODO 2.9 约定)
// B站 DASH 音视频分流: 一次 playurl(fnval=16) 同时返回 dash.audio + dash.video, 一次请求各取所需
// 幂等: 产物已存在(size>0)则跳过, 重试只补缺不重下; 退出码 0=所求产物全部就位, 1=任一失败
import fs from "fs";
import path from "path";

/* B站请求头: 伪装桌面 Chrome。无 cookie 方案的前提 = search HTML / view / playurl / related
   这几个接口不吃风控; 作者空间列表(x/space/wbi/arc/search)和动态 feed 已上 -352 风控用不了(9/27 实测) */
const UA = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
  "Accept-Language": "zh-CN,zh;q=0.9",
};
const MID = 625315686; // 桃哥 UP 主 mid, view/related 校验归属用
/* 搜索关键词三路(2026-09-27): "股桃"/"桃哥复盘"=标题向, 营销号蹭词 spam 多;
   UP 主全名=结果基本全是本人投稿, spam 极少, 兜住标题向被 spam 按发布时间挤位淹掉的场景
   (实测标题向 80 候选里只剩 1-2 个本人)。UP_NAME 单独常量 = 候选优先级标记用 */
const UP_NAME = "股市-目标1000万的股桃";
const KEYWORDS = ["股桃", "桃哥复盘", UP_NAME];
const RECENT_DAYS = 10; // --list 时效窗: 覆盖 search 索引延迟(1-3天)足够, 历史回填走 plan-a/downloads/index.json
const BFS_SEEDS = 3; // BFS 起跳种子数: related 返回集随种子而变(同种子确定, 9/27 实测), 单种子覆盖不全
const MAX_VIEW_CHECK = 80; // view API 校验上限: 防爆量, ~0.6s/个, 80 个 ~50s, cron 小时级可承受
const SEARCH_PAGES = 3; // 搜索翻页深度: spam 挤位, 桃哥较老的稿会掉出前 2 页(实测 9/18 时隐时现)

/* 命令行参数读取: --name value 形式, 不存在返回 null */
function arg(name) {
  const i = process.argv.indexOf("--" + name);
  return i >= 0 ? process.argv[i + 1] : null;
}

/* 请求抖动(健壮性铁律): 每个 B站请求后睡 300-800ms 随机值, 防高频连打触发软风控 */
function jitter() {
  return new Promise(s => setTimeout(s, 300 + Math.random() * 500));
}

/* GET JSON: 风控页/验证页是 HTML("<" 开头)而非 JSON, 直接抛错让调用方走 catch 降级 */
async function getJson(url, referer = "https://www.bilibili.com") {
  const r = await fetch(url, { headers: { ...UA, Referer: referer } });
  const t = await r.text();
  if (t.startsWith("<")) throw new Error("risk-blocked: " + url.slice(0, 80));
  return JSON.parse(t);
}

/* 下载二进制到本地(视频/音频流用), Referer 必须带 bilibili.com 否则 403 */
async function download(url, out) {
  const r = await fetch(url, { headers: { ...UA, Referer: "https://www.bilibili.com" } });
  if (!r.ok) throw new Error("download http " + r.status);
  fs.writeFileSync(out, Buffer.from(await r.arrayBuffer()));
  console.log("saved:", out, fs.statSync(out).size, "bytes");
}

/* 产物已存在(size>0)则跳过: 重试只补缺, 不重下几十MB的mp4 */
function existsNonEmpty(p) {
  return fs.existsSync(p) && fs.statSync(p).size > 0;
}

/* 发现: 搜索页 HTML 抠候选 → view API 验明正身 → related BFS 一跳补漏 → 时效窗过滤
   返回按发布时间倒序的本人视频数组 [{bvid,title,pubdate,mid,cid,desc,duration}] */
async function discover() {
  // ── 第 1 段: 搜索页 HTML 内嵌 JSON 正则抠 {bvid,title,pubdate,up}(pubdate=Unix秒, B站原字段名) ──
  const found = new Map(); // bvid -> {bvid,title,pubdate,up}; up=true 表示来自 UP 主全名搜索(高可信)
  for (const kw of KEYWORDS) {
    for (let page = 1; page <= SEARCH_PAGES; page++) {
      const url = `https://search.bilibili.com/video?keyword=${encodeURIComponent(kw)}&order=pubdate&page=${page}`;
      try {
        const r = await fetch(url, { headers: UA });
        const html = await r.text();
        /* 搜索页嵌数据有三种渲染格式(2026-09-27 实测同 URL 不同次/不同条目随机切换):
           ① 紧凑式 bvid:"...",title:"...",pubdate:1758...
           ② 转义骨架式 bvid:\"...\",title:\"...\",description:...,...,pubdate:1758...
           ③ 位置数组式 ...,\"BVxxx\",\"标题\",1790151038,... (无字段名, 9/23-24 漏抓根因)
           reNamed 覆盖①②(引号前可选反斜杠, pubdate 位置不定 → 后向 2000 字符窗内找),
           rePos 覆盖③(bvid/标题/pubdate 位置三元组), 两正则结果取并集 */
        const reNamed = /bvid:\\?"(BV1[a-zA-Z0-9]{9})\\?",title:\\?"((?:[^"\\]|\\.)*?)\\?",[\s\S]{0,2000}?pubdate:(\d+)/g;
        const rePos = /\\"(BV1[a-zA-Z0-9]{9})\\",\\"((?:[^"\\]|\\.)*?)\\",(\d{9,11})/g;
        for (const re of [reNamed, rePos]) {
          for (const m of html.matchAll(re)) {
            if (!found.has(m[1])) {
              found.set(m[1], { bvid: m[1], title: m[2], pubdate: +m[3], up: kw === UP_NAME });
            }
          }
        }
      } catch (e) {
        /* 单页失败不致命: 其余页/关键词照样跑, 结果取并集 */
        console.error(`search page fail kw=${kw} page=${page}: ${e.message}`);
      }
      await jitter();
    }
  }

  // ── 第 2 段: view API 验明正身(搜索结果混入大量转载/同名/蹭词营销号, 只认 owner.mid==桃哥) ──
  // 预过滤(2026-09-27): spam 会把 pubdate 改成未来日期蹭"按发布时间排序"(实测出现 2026-09-30),
  // 不滤掉则排序前列全是 spam, 桃哥本人被挤出 view 校验窗口 → 表现为"时有时无"
  const nowSec = Date.now() / 1000;
  const cutoff = nowSec - RECENT_DAYS * 86400;
  const cands = [...found.values()]
    .filter(c => c.pubdate >= cutoff && c.pubdate <= nowSec + 86400) // 时效窗内 且 非未来日期
    /* UP 主全名搜索来的候选排最前(基本是本人, spam 淹没的是标题向), 组内按发布时间倒序 */
    .sort((a, b) => (b.up - a.up) || (b.pubdate - a.pubdate))
    .slice(0, MAX_VIEW_CHECK);
  const his = [];
  for (const c of cands) {
    try {
      const v = await getJson(`https://api.bilibili.com/x/web-interface/view?bvid=${c.bvid}`);
      if (v.code === 0 && v.data.owner.mid === MID) {
        // view 返回的 title 是干净原文(搜索页抠的可能带转义), cid/duration 也只有 view 有
        // _raw(2026-09-29 用户定): 保留 view API 原始 data 全文, 落盘 .json 存源不存裁剪版
        his.push({ ...c, mid: String(MID), cid: v.data.cid, desc: v.data.desc, duration: v.data.duration, title: v.data.title, _raw: v.data });
      }
    } catch (e) {
      console.error(`view fail ${c.bvid}: ${e.message}`);
    }
    await jitter();
  }

  // ── 第 3 段: BFS 一跳补漏(2026-09-27) ──
  // search 索引对最新稿有 1-3 天延迟(9/21 搜不到当晚稿实证), archive/related 不风控且强关联本人,
  // 用已发现的最新视频顺一跳把更新的稿捞回来; related 返回项自带 owner.mid/cid/duration/pubdate,
  // 无需二次 view 校验。同一种子的 related 集合确定, 但不同种子各给一部分(40 条里本人 ~20 条),
  // 故取 his 前 BFS_SEEDS 个最新视频都当种子取并集
  const known = new Set(his.map(v => v.bvid));
  for (const seed of his.slice(0, BFS_SEEDS)) {
    try {
      const rel = await getJson(`https://api.bilibili.com/x/web-interface/archive/related?bvid=${seed.bvid}`);
      for (const it of rel.data || []) {
        if (it.owner?.mid === MID && !known.has(it.bvid)) {
          his.push({ bvid: it.bvid, title: it.title, pubdate: it.pubdate, mid: String(MID),
            cid: it.cid, desc: it.desc, duration: it.duration });
          known.add(it.bvid);
        }
      }
    } catch (e) {
      console.error(`related BFS fail seed=${seed.bvid} (降级=该种子跳过): ${e.message}`);
    }
    await jitter();
  }

  // ── 第 4 段: 时效窗收尾过滤 ──
  // 日常 job 只管增量; BFS 会顺带捞出 2020-2024 老稿(实测), 不过滤会被 cron 自动插表+下载+跑 7B
  // (每条 15-20min 白烧)。历史回填不走本 job: scripts/plan-a/downloads/index.json 已有 639 全量索引
  const out = his.filter(v => v.pubdate >= cutoff).sort((a, b) => b.pubdate - a.pubdate);
  /* 各段计数打 stderr(Java runNode 收进 sys_job_log): 发现波动时一眼定位是哪段在漏 */
  console.error(`discover: found=${found.size} cands=${cands.length} his=${his.length} final=${out.length}`);
  return out;
}

/* 下载单个视频的全部产物: mp4(画面) + m4a(音轨) + json(元数据) */
async function downloadProducts(video, outDir, wantVideo, wantAudio) {
  // 一次 playurl 同时拿 dash.audio + dash.video(原来两个脚本各调一次=重复请求)
  const play = await getJson(`https://api.bilibili.com/x/player/playurl?bvid=${video.bvid}&cid=${video.cid}&fnval=16&fourk=0`);

  if (wantAudio) {
    const m4a = path.join(outDir, `${video.bvid}.m4a`);
    if (existsNonEmpty(m4a)) {
      console.log("skip audio (exists):", m4a);
    } else {
      const audios = play.data?.dash?.audio || [];
      if (!audios.length) throw new Error("no audio track (may need retry/login for this video)");
      await download(audios[0].baseUrl, m4a); // ASR 用, 第一条音轨足够
    }
  }

  if (wantVideo) {
    const mp4 = path.join(outDir, `${video.bvid}.mp4`);
    if (existsNonEmpty(mp4)) {
      console.log("skip video (exists):", mp4);
    } else {
      const videos = play.data?.dash?.video || [];
      if (!videos.length) throw new Error("no video track");
      // 无cookie通常最高480p; 按(清晰度id, 码率)挑最优, 视觉识别分辨率即正义
      const best = [...videos].sort((a, b) => (b.id - a.id) || (b.bandwidth - a.bandwidth))[0];
      console.log(`available qualities: ${[...new Set(videos.map(x => x.id))].sort((a, b) => b - a).join(",")} -> pick id=${best.id} ${best.width}x${best.height} band=${best.bandwidth}`);
      await download(best.baseUrl, mp4);
    }
  }

  // 源元数据每次都刷新(2026-09-29 用户定: 存原本的样子, 不存手工裁剪版):
  // 信封(api 来源+fetched_at) + data=view API 原始响应全文(含 stat 播放/点赞/硬币、
  // pages 分P、owner、subtitle 等 40+ 字段)。只是磁盘产物(随原料 30 天清理, 不入库),
  // 物理删除后要重查=拿 bvid 重跑本脚本重新走 view/playurl
  let raw = video._raw;
  if (!raw) {
    // BFS related 捞进来的候选没过 view API(罕见), 补拉一次保 raw
    const v = await getJson(`https://api.bilibili.com/x/web-interface/view?bvid=${video.bvid}`);
    if (v.code === 0) raw = v.data;
  }
  const metaPath = path.join(outDir, `${video.bvid}.json`);
  fs.writeFileSync(metaPath, JSON.stringify({
    api: `https://api.bilibili.com/x/web-interface/view?bvid=${video.bvid}`,
    fetched_at: new Date().toISOString(),
    data: raw ?? video,
  }, null, 2));
  console.log("meta:", metaPath);
}

async function main() {
  // --list: 只发现不下载, stdout 输出 JSON 数组 [{bvid,title,pubdate,duration,...}]
  // 供 Java quartz handler (BilibiliVideoHandler) ProcessBuilder 消费; stdout 末尾一行 JSON, 其它都是日志
  if (process.argv.includes("--list")) {
    let his = await discover();
    /* 空结果重试一次(2026-09-27): B站偶发整轮返回降级空页(6 次连跑出现 1 次全空),
       cron 小时级虽会自然重试, 但 runOnce 手工触发不想等一小时; 只重试一次, 有界 */
    if (!his.length) {
      console.error("discover empty, retry once after 2s");
      await new Promise(s => setTimeout(s, 2000));
      his = await discover();
    }
    console.log("JSON:" + JSON.stringify(his));
    return;
  }

  // 下载模式: 落盘目录由 --out 精确指定(Java 侧按 downloads/bilibili/<作者mid>/<yyyy.MM.dd> 约定传)
  const outDir = arg("out") || path.join(process.cwd(), "downloads");
  fs.mkdirSync(outDir, { recursive: true });

  // 目标视频: --bvid 指定则 view API 取详情; 不指定则 discover() 取最新一个(手工补下载用)
  let video = null;
  const bvid = arg("bvid");
  if (bvid) {
    const v = await getJson(`https://api.bilibili.com/x/web-interface/view?bvid=${bvid}`);
    if (v.code !== 0) throw new Error("view api: " + v.message);
    video = { bvid, cid: v.data.cid, title: v.data.title, pubdate: v.data.pubdate, desc: v.data.desc, duration: v.data.duration, _raw: v.data };
  } else {
    const his = await discover();
    if (!his.length) throw new Error("no videos found for mid " + MID);
    console.log("recent videos:");
    for (const v of his) console.log(`  ${v.bvid} | ${v.title} | ${new Date(v.pubdate * 1000).toLocaleString("zh-CN", { hour12: false })}`);
    video = his[0];
  }

  // --video-only / --audio-only 只下一种产物(兼容壳/调试用); 默认两个都下
  const videoOnly = process.argv.includes("--video-only");
  const audioOnly = process.argv.includes("--audio-only");
  const wantVideo = !audioOnly;
  const wantAudio = !videoOnly;

  console.log(`\ntarget: ${video.bvid} | ${video.title} | duration=${video.duration}s`);
  await downloadProducts(video, outDir, wantVideo, wantAudio);
}

main().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
