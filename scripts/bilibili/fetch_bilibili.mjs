// B站 UP 视频发现 + 产物下载(2026-09-27 合并建; 10/5 多UP参数化 --mid/--name, 默认=桃哥 625315686; 10/6 更名 fetch_bilibili.mjs 去 taoge 专属命名)
// 方案(10/12 晚改, 10/14 双源): 无登录。发现主路=UP 投稿列表 x/space/wbi/arc/search(WBI 签名) ∪ x/series/recArchivesByKeywords(免签名), 双源全败降级旧方案B
// (search.bilibili.com HTML 页发现); 详情和流地址走 view/playurl API。
// 用法:
//   node fetch_bilibili.mjs --list        # 只发现不下载, stdout 末行 "JSON:[...]" (Java BilibiliVideoHandler 发现段消费)
//   node fetch_bilibili.mjs [--bvid BVxxxx] [--out <目录>] [--video-only|--audio-only]
//                                               # 下载产物 → <outDir>/<bvid>.mp4(画面,视觉用) + .m4a(音轨,ASR用) + .json(源元数据=view API原始响应全文+抓取信封)
//   --bvid 不传=下最新一个; --out 不传默认 cwd/downloads, 传了=精确落盘目录(Java 传 downloads/bilibili/<作者mid>/<yyyy.MM.dd>, TODO 2.9 约定)
// B站 DASH 音视频分流: 一次 playurl(fnval=16) 同时返回 dash.audio + dash.video, 一次请求各取所需
// 幂等: 产物已存在(size>0)则跳过, 重试只补缺不重下; 退出码 0=所求产物全部就位, 1=任一失败
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { gfetch } from "../lib/req_guard.mjs";   // 10/15 统一请求层: 限速/熔断/日预算/失败分类(见 scripts/lib/req_guard.mjs)

/* B站请求头: 伪装桌面 Chrome。search HTML / view / playurl / related 不吃风控; 作者空间列表(x/space/wbi/arc/search)
   9/27 不签名直接调被 -352 挡, 10/12 补 WBI 签名+buvid 后可用(见 spaceList); 动态 feed 仍未试 */
const UA = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
  "Accept-Language": "zh-CN,zh;q=0.9",
};
const MID = Number(arg("mid")) || 625315686; // UP 主 mid, view/related 校验归属用; --mid 覆盖(10/5 多UP化)
/* 搜索关键词三路(2026-09-27): "股桃"/"桃哥复盘"=标题向, 营销号蹭词 spam 多;
   UP 主全名=结果基本全是本人投稿, spam 极少, 兜住标题向被 spam 按发布时间挤位淹掉的场景
   (实测标题向 80 候选里只剩 1-2 个本人)。UP_NAME 单独常量 = 候选优先级标记用
   10/5 多UP化: --mid/--name 参数化(卢本圆 550494308/趋势天哥 1372241958);
   --name 时关键词=[名, 名+复盘](新 UP 非桃哥, 标题向词不可套用) */
const UP_NAME = arg("name") || "股市-目标1000万的股桃";
const KEYWORDS = arg("name") ? [...new Set([arg("name"), arg("name") + "复盘"])] : ["股桃", "桃哥复盘", UP_NAME];
const RECENT_DAYS = 60; // 候选收集窗: 覆盖搜索索引延迟(1-3天)+非日更 UP 断更期(卢本圆实测可 19 天不发)
const RECENT_KEEP = 10; // 每 UP 保留条数(10/6 用户立法: 不是倒推N天, 是往回找N个视频——2 UP 即 20 条够 sum+distill 起步)
const BFS_SEEDS = 3; // BFS 起跳种子数: related 返回集随种子而变(同种子确定, 9/27 实测), 单种子覆盖不全
const MAX_VIEW_CHECK = 80; // view API 校验上限: 防爆量, ~0.6s/个, 80 个 ~50s, cron 小时级可承受
const SEARCH_PAGES = arg("name") ? 5 : 3; // 搜索翻页深度: spam 挤位, 桃哥较老的稿会掉出前 2 页(实测 9/18 时隐时现);
// 10/5: 新 UP(有 --name)深翻 5 页+综合排序路=事实上的 mid 限定发现(view 校验锁 mid; wbi space API 无登录态 -352 不可行, 10/5 实测)

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
  let r;
  try { r = await gfetch(url, { headers: { ...UA, Referer: referer } }); }
  catch (e) { if (e.kind === "BLOCKED") throw new Error("risk-blocked(熔断中): " + url.slice(0, 80)); throw e; }
  const t = await r.text();
  if (t.startsWith("<")) throw new Error("risk-blocked: " + url.slice(0, 80));
  return JSON.parse(t);
}

/* 下载二进制到本地(视频/音频流用), Referer 必须带 bilibili.com 否则 403 */
async function download(url, out) {
  const r = await gfetch(url, { headers: { ...UA, Referer: "https://www.bilibili.com" } });
  if (!r.ok) throw new Error("download http " + r.status);
  // 10/17 健壮性 M16: 原先直接写目标文件、不核对长度 → 半截 m4a 之后被 existsNonEmpty 当成已下载, 永久跳过、转写只有前半段
  const buf = Buffer.from(await r.arrayBuffer());
  const cl = +(r.headers?.get?.("content-length") || 0);
  if (cl && !r.headers?.get?.("content-encoding") && buf.length !== cl) throw new Error(`download 截断 ${buf.length}/${cl} bytes`);
  const tmp = out + ".part";
  fs.writeFileSync(tmp, buf);
  fs.renameSync(tmp, out);
  console.log("saved:", out, fs.statSync(out).size, "bytes");
}

/* 产物已存在(size>0)则跳过: 重试只补缺, 不重下几十MB的mp4 */
function existsNonEmpty(p) {
  return fs.existsSync(p) && fs.statSync(p).size > 0;
}

/* ── 发现主路(10/14 改双源): ①UP 投稿列表 x/space/wbi/arc/search(WBI 签名) ②UP 稿件列表 x/series/recArchivesByKeywords(免签名) ──
   病灶史: 原发现只靠搜索页 HTML, 搜索索引对新稿延迟 1-3 天 + 营销号蹭词挤位 → 10/12 天哥 18:01 稿漏抓;
   10/12 补 WBI 签名(nav 接口 img/sub key → 固定重排表取 mixin key → 参数排序后 md5)+ finger/spi 发的 buvid3/4 后可用。
   10/14(REA 调研): 加②作独立第二源——不依赖 WBI 算法(签名表/参数一改①就死, ②不受影响), 只要 buvid cookie+space Referer;
   两源同按 mid 取, 天然锁本人(另按 mid/upMid 字段再核一次, 联合投稿的他人主稿剔除, 与旧 view 归属闸同口径)。
   两源取并集+对账日志(各自独有的 bvid 打 stderr, 进 sys_job_log): 一源漏稿另一源补, 长期看日志就知道哪源在漏。
   请求数: 旧=spi+nav+space+10×view=13 次/轮; 新=spi+nav+space+rec=4 次/轮(--list 不再逐条 view: Java 只用
   bvid/title/pubdate/mid/duration, 两源列表自带; cid/_raw 只有下载模式需要, 下载时按 bvid 现取 view)。
   风控实测(10/14 01:2x): 几分钟内连发 ~25 次 B站接口后整 IP 返 412 HTML, ~10 分钟自愈 → 本脚本 4 次/轮远低于此。
   双源全败=返回 null, discover() 降级旧的搜索+BFS 路(多源切换铁律) */
const WBI_MIXIN = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
  37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52];
/* buvid 指纹 cookie: 两源共用一份(finger/spi 无需登录) */
async function buvidCookie() {
  const spi = await (await gfetch("https://api.bilibili.com/x/frontend/finger/spi", { headers: UA })).json();
  return `buvid3=${spi.data.b_3}; buvid4=${encodeURIComponent(spi.data.b_4)}`;
}
/* "mm:ss" / "h:mm:ss" → 秒(投稿列表的 length 字段是字符串) */
const lenSec = (s) => String(s || "0").split(":").reduce((a, x) => a * 60 + (+x || 0), 0);
/* ① WBI 签名的投稿列表 */
async function spaceList(mid, n, cookie) {
  try {
    const crypto = await import("node:crypto");
    const nav = await (await gfetch("https://api.bilibili.com/x/web-interface/nav", { headers: { ...UA, Cookie: cookie } })).json();
    const key = (u) => u.split("/").pop().split(".")[0];
    const raw = key(nav.data.wbi_img.img_url) + key(nav.data.wbi_img.sub_url);
    const mixin = WBI_MIXIN.map((i) => raw[i]).join("").slice(0, 32);
    const p = { mid: String(mid), ps: String(n), pn: "1", order: "pubdate", platform: "web", web_location: "1550101",
      dm_img_list: "[]", dm_img_str: "V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ", dm_cover_img_str: "QU5HTEUgKEludGVsKQ",
      dm_img_inter: '{"ds":[],"wh":[0,0,0],"of":[0,0,0]}', wts: String(Math.floor(Date.now() / 1000)) };
    const q = Object.keys(p).sort().map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(String(p[k]).replace(/[!'()*]/g, ""))}`).join("&");
    const w_rid = crypto.createHash("md5").update(q + mixin).digest("hex");
    await jitter();
    const r = await gfetch(`https://api.bilibili.com/x/space/wbi/arc/search?${q}&w_rid=${w_rid}`,
      { headers: { ...UA, Cookie: cookie, Referer: `https://space.bilibili.com/${mid}/video`, Origin: "https://space.bilibili.com" } });
    const t = await r.text();
    if (t.startsWith("<")) throw new Error(`风控 HTML 页 http ${r.status}`);
    const j = JSON.parse(t);
    if (j.code !== 0 || !Array.isArray(j.data?.list?.vlist)) throw new Error(`code=${j.code} ${j.message || ""}`);
    return j.data.list.vlist.filter((v) => !v.mid || v.mid === mid)
      .map((v) => ({ bvid: v.bvid, title: v.title, pubdate: v.created, mid: String(mid), duration: lenSec(v.length) }));
  } catch (e) {
    console.error(`源① space/wbi 失败: ${e.message}`);
    return null;
  }
}
/* ② 免签名的稿件列表(按发布时间倒序; state<0=删除/审核中, 剔除) */
async function recList(mid, n, cookie) {
  try {
    const r = await gfetch(`https://api.bilibili.com/x/series/recArchivesByKeywords?mid=${mid}&keywords=&ps=${n}&pn=1&orderby=pubdate`,
      { headers: { ...UA, Cookie: cookie, Referer: `https://space.bilibili.com/${mid}/video`, Origin: "https://space.bilibili.com" } });
    const t = await r.text();
    if (t.startsWith("<")) throw new Error(`风控 HTML 页 http ${r.status}`);
    const j = JSON.parse(t);
    if (j.code !== 0 || !Array.isArray(j.data?.archives)) throw new Error(`code=${j.code} ${j.message || ""}`);
    return j.data.archives.filter((v) => (!v.upMid || v.upMid === mid) && !(v.state < 0))
      .map((v) => ({ bvid: v.bvid, title: v.title, pubdate: v.pubdate, mid: String(mid), duration: v.duration }));
  } catch (e) {
    console.error(`源② recArchives 失败: ${e.message}`);
    return null;
  }
}

/* 发现: 双源并集(各自失败互不影响; 源①偶发风控先自重试一次) → 按发布时间倒序取 RECENT_KEEP 条;
   双源全败才走旧路(搜索页 HTML+view 校验+related BFS)。返回 [{bvid,title,pubdate,mid,duration}] */
async function discover() {
  let cookie = null;
  try { cookie = await buvidCookie(); } catch (e) { console.error(`buvid 获取失败(降级搜索路): ${e.message}`); }
  if (cookie) {
    await jitter();
    let sl = await spaceList(MID, RECENT_KEEP, cookie);
    if (!sl) {   // 偶发风控 HTML 页(10/12 实测连发后撞上, 2s 后即恢复): 自重试一次
      await new Promise((s) => setTimeout(s, 2000));
      sl = await spaceList(MID, RECENT_KEEP, cookie);
    }
    await jitter();
    const rl = await recList(MID, RECENT_KEEP, cookie);
    if ((sl && sl.length) || (rl && rl.length)) {
      const merged = new Map();
      for (const v of rl || []) merged.set(v.bvid, { ...v, src: "rec" });
      for (const v of sl || []) merged.set(v.bvid, { ...v, src: merged.has(v.bvid) ? "both" : "space" });  // 同 bvid 以①为准
      const out = [...merged.values()].sort((a, b) => b.pubdate - a.pubdate).slice(0, RECENT_KEEP);
      /* 对账: 只比两源都覆盖到的时间窗(较老一侧的最早 pubdate 之后), 窗内一源有一源无=疑似漏稿/口径差, 打日志不阻断 */
      if (sl && rl && sl.length && rl.length) {
        const floor = Math.max(Math.min(...sl.map((v) => v.pubdate)), Math.min(...rl.map((v) => v.pubdate)));
        const sb = new Set(sl.map((v) => v.bvid)), rb = new Set(rl.map((v) => v.bvid));
        const onlyS = sl.filter((v) => v.pubdate >= floor && !rb.has(v.bvid)).map((v) => v.bvid);
        const onlyR = rl.filter((v) => v.pubdate >= floor && !sb.has(v.bvid)).map((v) => v.bvid);
        if (onlyS.length || onlyR.length) console.error(`对账差异: 仅space=[${onlyS}] 仅rec=[${onlyR}]`);
      }
      console.error(`discover(双源): space=${sl ? sl.length : "败"} rec=${rl ? rl.length : "败"} final=${out.length}`);
      return out;
    }
    console.error("双源均失败/为空, 降级搜索路");
  }
  return discoverBySearch();
}

/* 旧路(9/27 方案B, 10/12 起为降级备用): 搜索页 HTML 抠候选 → view 验明正身 → related BFS 补漏 */
async function discoverBySearch() {
  // ── 第 1 段: 搜索页 HTML 内嵌 JSON 正则抠 {bvid,title,pubdate,up}(pubdate=Unix秒, B站原字段名) ──
  const found = new Map(); // bvid -> {bvid,title,pubdate,up}; up=true 表示来自 UP 主全名搜索(高可信)
  for (const kw of KEYWORDS) {
    for (let page = 1; page <= SEARCH_PAGES; page++) {
      /* 10/5 两路: pubdate 序(时间近优先) + 综合排序(仅 page1; 卢本圆案: pubdate 序被营销号 spam 挤位,
         精确 UP 名搜索时本人视频排综合前3 — 9/27 三格式正则之外的第四种漏抓形态) */
      const urls = [`https://search.bilibili.com/video?keyword=${encodeURIComponent(kw)}&order=pubdate&page=${page}`];
      if (page === 1) urls.push(`https://search.bilibili.com/video?keyword=${encodeURIComponent(kw)}`);
      for (const url of urls) {
      try {
        const r = await gfetch(url, { headers: UA });
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
  let blocked = 0;  // 10/14 熔断: 连续 3 次风控 HTML(412)=整 IP 被限, 再打 80 次 view 只会延长封禁, 停手等下个 cron 周期
  for (const c of cands) {
    if (blocked >= 3) { console.error(`view 连续 ${blocked} 次风控, 熔断(剩余候选跳过)`); break; }
    try {
      const v = await getJson(`https://api.bilibili.com/x/web-interface/view?bvid=${c.bvid}`);
      blocked = 0;
      if (v.code === 0 && v.data.owner.mid === MID) {
        // view 返回的 title 是干净原文(搜索页抠的可能带转义), cid/duration 也只有 view 有
        // _raw(2026-09-29 用户定): 保留 view API 原始 data 全文, 落盘 .json 存源不存裁剪版
        his.push({ ...c, mid: String(MID), cid: v.data.cid, desc: v.data.desc, duration: v.data.duration, title: v.data.title, _raw: v.data });
      }
    } catch (e) {
      if (/risk-blocked/.test(e.message)) blocked++;
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
  // (每条 15-20min 白烧)。历史回填不走本 job: scripts/backfill_taoge/reuse/index.json 已有 639 全量索引
  const out = his.sort((a, b) => b.pubdate - a.pubdate).slice(0, RECENT_KEEP); // 10/6 立法: 往回 N 条而非 N 天
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
  // 10/15 多 P 告警(TODO A4: 三 UP 抽样 181 条 0 条多 P, 不做逐 P 下载; 真出现时这里报出来再做)
  if ((raw?.pages?.length || 1) > 1) console.error(`⚠多P稿: ${video.bvid} 共 ${raw.pages.length} P, 本脚本只下了 P1(cid=${video.cid}), 其余 P 未下载——见 TODO A4`);
  const metaPath = path.join(outDir, `${video.bvid}.json`);
  fs.writeFileSync(metaPath, JSON.stringify({
    api: `https://api.bilibili.com/x/web-interface/view?bvid=${video.bvid}`,
    fetched_at: new Date().toISOString(),
    data: raw ?? video,
  }, null, 2));
  console.log("meta:", metaPath);
}

/* ── 删改重发判重(10/15, TODO A4): UP 删稿改一改重新投 = 新 bvid, 原先会被当新稿再下载/转写/写一遍 md ──
   规则: 发布时间相差 ≤48h + 标题相似(去标点后 bigram Dice ≥0.8 或互相包含) + 时长差 <10% → 判为同一稿。
   比对对象: 本轮发现列表 + 本地已下载的元数据(downloads/bilibili/<mid>/<日期>/<bvid>.json, 近 3 天目录; 旧稿删了就不在列表里了)。
   处理: 旧稿本地已有产物 → 新稿从 --list 输出剔除(Java 不入库=不下载不写 md), 保留旧稿产物; 两版都在列表且都没处理 → 只留较新的一版。
   一律 stderr 告警(进 sys_job_log), 文字带两个 bvid 便于人工复核; BILI_DEDUP=0 关闭。 */
const normTitle = (s) => String(s || "").replace(/<[^>]+>/g, "").replace(/[\s\p{P}\p{S}]/gu, "").toLowerCase();
function titleSim(a, b) {
  a = normTitle(a); b = normTitle(b);
  if (!a || !b) return 0;
  if (a === b || a.includes(b) || b.includes(a)) return 1;
  const bg = (s) => { const m = new Map(); for (let i = 0; i < s.length - 1; i++) { const k = s.slice(i, i + 2); m.set(k, (m.get(k) || 0) + 1); } return m; };
  const A = bg(a), B = bg(b);
  let inter = 0;
  for (const [k, n] of A) inter += Math.min(n, B.get(k) || 0);
  return (2 * inter) / Math.max(1, a.length - 1 + b.length - 1);
}
export function isRepost(x, y) {
  const dt = Math.abs((+x.pubdate || 0) - (+y.pubdate || 0));
  const d1 = +x.duration || 0, d2 = +y.duration || 0;
  // 系列稿(②③④/上下篇/第N期/日期不同)不算重发: 标题里的编号/数字集合必须一致
  const nums = (t) => (normTitle(t).match(/\d+|[①-⑳❶-❿]|[上中下](?=篇|集|期)?$/g) || []).join(",");
  if (nums(x.title) !== nums(y.title)) return false;
  return x.bvid !== y.bvid && dt <= 48 * 3600 && d1 > 0 && d2 > 0 && Math.abs(d1 - d2) / Math.max(d1, d2) < 0.1 && titleSim(x.title, y.title) >= 0.8;
}
function localHistory(mid, base = path.join(process.cwd(), "downloads", "bilibili")) {
  const dir = path.join(base, String(mid)), out = [];
  if (!fs.existsSync(dir)) return out;
  for (const d of fs.readdirSync(dir).filter((x) => /^\d{4}\.\d\d\.\d\d$/.test(x)).sort().slice(-3)) {
    for (const f of fs.readdirSync(path.join(dir, d)).filter((x) => /^BV\w+\.json$/.test(x))) {
      try {
        const v = JSON.parse(fs.readFileSync(path.join(dir, d, f), "utf8")).data || {};
        const bvid = f.replace(/\.json$/, "");
        const done = ["m4a", "mp4"].some((e) => existsNonEmpty(path.join(dir, d, `${bvid}.${e}`)));
        out.push({ bvid, title: v.title, pubdate: v.pubdate, duration: v.duration, done });
      } catch { /* 坏元数据跳过 */ }
    }
  }
  return out;
}
export function dedupRepost(list, local = []) {
  if (process.env.BILI_DEDUP === "0") return list;
  const drop = new Set();
  for (const v of list) {
    const old = local.find((h) => h.done && isRepost(v, h) && h.pubdate <= v.pubdate);
    if (old) { drop.add(v.bvid); console.error(`⚠删改重发判重: ${v.bvid}「${v.title}」≈ 已处理旧稿 ${old.bvid}「${old.title}」(48h 内/标题相似/时长差<10%), 新稿跳过不入库不写 md`); }
  }
  for (const v of list) for (const w of list) {
    if (drop.has(v.bvid) || drop.has(w.bvid) || !isRepost(v, w) || !(v.pubdate < w.pubdate)) continue;
    if (local.some((h) => h.bvid === v.bvid && h.done)) { drop.add(w.bvid); console.error(`⚠删改重发判重: ${w.bvid} ≈ 已处理 ${v.bvid}, 新稿跳过`); }
    else { drop.add(v.bvid); console.error(`⚠删改重发判重: ${v.bvid}「${v.title}」与较新的 ${w.bvid} 同稿, 只留新版`); }
  }
  return list.filter((v) => !drop.has(v.bvid));
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
    his = dedupRepost(his, localHistory(MID));   // 10/15 删改重发判重(剔除的稿 stderr 告警)
    console.log("JSON:" + JSON.stringify(his));
    return;
  }

  // 下载模式: 落盘目录由 --out 精确指定(Java 侧按 downloads/bilibili/<作者mid>/<yyyy.MM.dd> 约定传)
  const outDir = arg("out") || path.join(process.cwd(), "downloads");
  fs.mkdirSync(outDir, { recursive: true });

  // 目标视频: --bvid 指定则 view API 取详情; 不指定则 discover() 取最新一个(手工补下载用)
  let video = null;
  let bvid = arg("bvid");
  if (!bvid) {
    /* 10/14: 发现结果不再带 cid/_raw(双源列表省掉了逐条 view), 选中最新一条后与 --bvid 同路现取 view */
    const his = await discover();
    if (!his.length) throw new Error("no videos found for mid " + MID);
    console.log("recent videos:");
    for (const v of his) console.log(`  ${v.bvid} | ${v.title} | ${new Date(v.pubdate * 1000).toLocaleString("zh-CN", { hour12: false })}`);
    bvid = his[0].bvid;
  }
  {
    const v = await getJson(`https://api.bilibili.com/x/web-interface/view?bvid=${bvid}`);
    if (v.code !== 0) throw new Error("view api: " + v.message);
    // 10/6 误下载防线: --bvid 也必须过 mid 归属校验(与发现段同款), 他人视频拒绝下载
    if (v.data.owner.mid !== MID) throw new Error(`bvid ${bvid} 归属 mid ${v.data.owner.mid} != 目标 ${MID}, 拒绝下载(防误下他人视频)`);
    video = { bvid, cid: v.data.cid, title: v.data.title, pubdate: v.data.pubdate, desc: v.data.desc, duration: v.data.duration, _raw: v.data };
  }

  // --video-only / --audio-only 只下一种产物(兼容壳/调试用); 默认两个都下
  const videoOnly = process.argv.includes("--video-only");
  const audioOnly = process.argv.includes("--audio-only");
  const wantVideo = !audioOnly;
  const wantAudio = !videoOnly;

  console.log(`\ntarget: ${video.bvid} | ${video.title} | duration=${video.duration}s`);
  await downloadProducts(video, outDir, wantVideo, wantAudio);
}

// 10/15: 只在直接执行时跑(被 import 做单测/复用判重函数时不跑)
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url))
  main().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
