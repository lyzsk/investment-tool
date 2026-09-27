// 桃哥历史视频索引刷新(2026-09-27 新建, 回填工程配套; 逻辑复制改进自 plan-a/crawl_index.mjs)
// 为什么新建而不改 crawl_index.mjs: plan-a 的索引是 BFS 一跳口径(639条, 已知不全),
// 回填要"尽量全集", 需要多跳 BFS + 合并旧索引, 且产物落新目录, 不影响在跑的 plan-a 系统。
// 爬法: 从种子集(旧 index 全部 bvid)出发, archive/related 多跳 BFS, owner.mid==625315686 过滤,
//       直到 frontier 掏空或请求数上限。related 无需登录不风控(9/27 实证), 是最稳的全集途径。
// 输出: scripts/backfill_taoge/index.json = 数组 [{bvid,title,pubdate,cid,duration,date}] 按 pubdate 新→旧
// 降级: 单请求失败跳过继续; 返回 HTML(风控页)记 risk-blocked, 连续风控则整体降级=只输出旧 index 并警告。
// 注意: 绝不写 scripts/plan-a/downloads/index.json (在跑系统的数据, 只读)。
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url)); // scripts/
const OLD_INDEX = path.join(SCRIPT_DIR, "plan-a", "downloads", "index.json"); // 只读
const OUT_DIR = path.join(SCRIPT_DIR, "backfill_taoge");
const OUT_INDEX = path.join(OUT_DIR, "index.json");
const MID = 625315686;

const UA = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
  "Accept-Language": "zh-CN,zh;q=0.9",
  "Referer": "https://www.bilibili.com",
};

// 上限估算: 种子 ~639 + 每种子 related ~40 条里本人 ~20 条会进 frontier, 多跳收敛后期望请求数 ≈ 最终全集规模。
// 1507 全集 → 留 2 倍余量。超过说明 related 图没收敛(异常), 强停防失控。
const MAX_REQUESTS = 3200;
const MAX_ERRORS = 15;        // 累计错误上限(网络抖动容忍, 超了说明环境有问题, 强停)
const MAX_RISK_BLOCKED = 5;   // 连续风控上限: 风控是账号/IP 级状态, 连撞 5 次再打无意义
const SAVE_EVERY = 30;        // 每 30 请求落一次盘(崩溃止损)

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
// 请求抖动(健壮性铁律): 300-800ms 随机, 防高频连打触发软风控
const jitter = () => sleep(300 + Math.random() * 500);

// GET JSON: 风控页/验证页是 HTML("<" 开头)而非 JSON, 抛特定错误让上层按风控处理
class RiskBlocked extends Error {}
async function getJson(url) {
  const r = await fetch(url, { headers: UA });
  const t = await r.text();
  if (t.startsWith("<")) throw new RiskBlocked("risk-blocked: " + url.slice(0, 80));
  return JSON.parse(t);
}

const fmtDate = (ts) => {
  const d = new Date(ts * 1000); // 本地时区(机器在 CST), 与 results 目录日期口径一致
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

function loadOldIndex() {
  if (!fs.existsSync(OLD_INDEX)) return {};
  try {
    return JSON.parse(fs.readFileSync(OLD_INDEX, "utf-8"));
  } catch (e) {
    console.error("old index parse fail (按无旧索引继续):", e.message);
    return {};
  }
}

function save(indexMap) {
  // 输出数组、新→旧排序: 回填脚本消费方便, 人也好看
  const arr = [...indexMap.values()].sort((a, b) => b.pubdate - a.pubdate);
  fs.mkdirSync(OUT_DIR, { recursive: true });
  fs.writeFileSync(OUT_INDEX, JSON.stringify(arr, null, 1));
  return arr;
}

async function main() {
  const old = loadOldIndex();
  const oldCount = Object.keys(old).length;
  console.log(`old index: ${oldCount} 条 (${OLD_INDEX})`);

  // 索引表: bvid -> {bvid,title,pubdate,cid,duration,date}; 旧索引先灌入做底(cid 旧格式没有, 置 null)
  const index = new Map();
  for (const [bvid, v] of Object.entries(old)) {
    index.set(bvid, { bvid, title: v.title, pubdate: v.pubdate, cid: null,
      duration: v.duration ?? null, date: v.date || fmtDate(v.pubdate) });
  }

  // 种子 = 旧索引全部 bvid(按发布时间新→旧, 新的 related 更可能带出旧索引缺失的新稿);
  // 旧索引都没有时用 crawl_index.mjs 的硬编码种子兜底
  const seeds = Object.entries(old).sort((a, b) => b[1].pubdate - a[1].pubdate).map(([b]) => b);
  let frontier = seeds.length ? seeds
    : ["BV1Moe16hEgL", "BV12eeg6bEd2", "BV1tfew6gE4v", "BV1Vde76tE33", "BV1jWYk6YE1m"];
  const visited = new Set();

  let requests = 0, errors = 0, riskStreak = 0, newFound = 0;
  let degraded = false; // 风控整体降级标记: 一旦触发, 剩余种子不再打, 直接输出已有底
  while (frontier.length && requests < MAX_REQUESTS && !degraded) {
    const bvid = frontier.shift();
    if (visited.has(bvid)) continue;
    visited.add(bvid);
    try {
      const j = await getJson(`https://api.bilibili.com/x/web-interface/archive/related?bvid=${bvid}`);
      requests++;
      riskStreak = 0;
      for (const v of j.data || []) {
        if (v.owner?.mid !== MID) continue;
        if (!index.has(v.bvid)) {
          newFound++;
          index.set(v.bvid, { bvid: v.bvid, title: v.title, pubdate: v.pubdate,
            cid: v.cid ?? null, duration: v.duration ?? null, date: fmtDate(v.pubdate) });
        }
        if (!visited.has(v.bvid)) frontier.push(v.bvid); // 多跳: 本人视频也进 frontier 继续扩
      }
      // 种子本身不在索引里(旧索引缺的新种子)时, view API 补登(多一次请求, 只在缺失时)
      if (!index.has(bvid)) {
        try {
          const v = await getJson(`https://api.bilibili.com/x/web-interface/view?bvid=${bvid}`);
          requests++;
          if (v.code === 0 && v.data.owner.mid === MID) {
            index.set(bvid, { bvid, title: v.data.title, pubdate: v.data.pubdate,
              cid: v.data.cid, duration: v.data.duration, date: fmtDate(v.data.pubdate) });
          }
        } catch (e) {
          if (e instanceof RiskBlocked) throw e;
          errors++;
        }
        await jitter();
      }
      if (requests % SAVE_EVERY === 0) {
        save(index);
        console.log(`requests=${requests} index=${index.size} (+${newFound}) frontier=${frontier.length} errors=${errors}`);
      }
    } catch (e) {
      if (e instanceof RiskBlocked) {
        riskStreak++;
        console.error(`risk-blocked ${bvid} (连续${riskStreak}次)`);
        if (riskStreak >= MAX_RISK_BLOCKED) {
          degraded = true;
          console.error("!!! 连续风控, 整体降级: 停止抓取, 只输出已有索引(旧索引打底, 仍可用) !!!");
          break;
        }
        frontier.push(bvid); // 风控是临时态, 该种子回队尾等下轮
        await sleep(10000);  // 风控后冷一冷
        continue;
      }
      errors++;
      console.error(`err ${bvid}: ${e.message}`);
      if (errors > MAX_ERRORS) { console.error("too many errors, stop"); break; }
      await sleep(5000);
    }
    await jitter();
  }

  const arr = save(index);
  const cutoff = Math.floor(new Date("2025-01-07T00:00:00+08:00").getTime() / 1000);
  const after = arr.filter(v => v.pubdate >= cutoff).length;
  console.log(`DONE. requests=${requests} errors=${errors} degraded=${degraded}`);
  console.log(`索引总数=${arr.length} (旧 ${oldCount}, 新增 ${index.size - oldCount})`);
  console.log(`2025-01-07 后=${after} 条 (旧索引同口径 310)`);
  console.log(`输出: ${OUT_INDEX}`);
  if (degraded) console.log("警告: 本次风控降级, 数字=旧索引+已抓部分, 改天重跑补齐");
}

main().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
