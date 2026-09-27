// kline.mjs — 分层粒度 K线抓取与缓存(只做这一件事)
//
// 分层口径(立法, 2026-09-27): 历史分钟线窗口硬约束(腾讯 ifzq.gtimg.cn):
//   m5=2周 / m15=8周 / m30=16周 / m60=8个月, 再早只有日线。
//   同一引擎按 T 日期自动选最细可用档:
//     T 距今≤14天 → m5; 2026-08起 → m15; 2026-06起 → m30; 2026-02起 → m60; 更早 → day
// 缓存: scripts/plan-a/downloads/kline/<code>_<gran>.json (与 pilot-2week 的 m5 缓存同目录复用)
// 量单位归一(前人血泪): 缓存 bar 字段是 vol(股) 不是 v(手), 无 amount;
//   新抓的腾讯 mkline a[5] 是手 → ×100 转股后再入缓存; shares()/barAmt() 统一口径。
// 反封: 请求带 300-800ms 随机抖动, 腾讯主/新浪备 switch-case 转移。
import fs from 'fs';
import path from 'path';

const KLINE_DIR = 'C:/Users/admin/dev/investment-tool/scripts/plan-a/downloads/kline';
const UA = { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' };

// 量单位归一: 统一返回股
export const shares = b => b.vol ?? (b.v || 0) * 100;
export const barAmt = b => b.amount || shares(b) * b.c;

const sleep = ms => new Promise(r => setTimeout(r, ms));
const jitter = () => sleep(300 + Math.random() * 500);   // 300-800ms 随机抖动, 不打固定节拍

// ---------- 分层粒度选择 ----------
// today 缺省=真实今天(数据可得性的锚); tradeDate 格式 YYYYMMDD
export function pickGranularity(tradeDate, today) {
  const t = today || dateStr(new Date());
  const ageDays = Math.round((parseDate(t) - parseDate(tradeDate)) / 86400000);
  if (ageDays <= 14) return 'm5';
  if (tradeDate >= '20260801') return 'm15';
  if (tradeDate >= '20260601') return 'm30';
  if (tradeDate >= '20260201') return 'm60';
  return 'day';
}
const parseDate = d => new Date(+d.slice(0, 4), +d.slice(4, 6) - 1, +d.slice(6, 8));
export const dateStr = d => String(d.getFullYear()) + String(d.getMonth() + 1).padStart(2, '0') + String(d.getDate()).padStart(2, '0');

// ---------- 源: 腾讯(主) ----------
async function tencentKline(code, gran, count) {
  let url, pick;
  if (gran === 'day') {
    url = `https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=${code},day,,,${count},qfq`;
    pick = j => {
      const d = j.data?.[code];
      const arr = d?.qfqday || d?.day || [];
      // 日线数组: [date, o, c, h, l, vol(手), ...] → t 统一成 YYYYMMDD1500 方便与分钟线同槽排序
      return arr.map(a => ({ t: a[0].replaceAll('-', '') + '1500', o: +a[1], c: +a[2], h: +a[3], l: +a[4], vol: Math.round((+a[5] || 0) * 100) }));
    };
  } else {
    url = `https://ifzq.gtimg.cn/appstock/app/kline/mkline?param=${code},${gran},,${count}`;
    pick = j => {
      const arr = j.data?.[code]?.[gran] || [];
      // 分钟数组: [t, o, c, h, l, vol(手), ...] → vol×100 转股(与缓存口径一致)
      return arr.map(a => ({ t: a[0], o: +a[1], c: +a[2], h: +a[3], l: +a[4], vol: Math.round((+a[5] || 0) * 100) }));
    };
  }
  const r = await fetch(url, { headers: UA });
  const bars = pick(await r.json());
  if (!bars.length) throw new Error('tencent 空数据 ' + gran);
  return bars;
}

// ---------- 源: 新浪(备, 需 Referer; volume单位=股 不用转) ----------
async function sinaKline(code, gran, count) {
  const scale = { m5: 5, m15: 15, m30: 30, m60: 60, day: 240 }[gran];
  const r = await fetch(
    `https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_x=/CN_MarketDataService.getKLineData?symbol=${code}&scale=${scale}&ma=no&datalen=${Math.min(count, 1023)}`,
    { headers: { ...UA, Referer: 'https://finance.sina.com.cn' } });
  const text = await r.text();
  const arr = JSON.parse(text.slice(text.indexOf('([') + 1, text.lastIndexOf(')')));
  if (!arr.length) throw new Error('sina 空数据 ' + gran);
  return arr.map(b => ({
    t: gran === 'day' ? b.day.replaceAll('-', '') + '1500' : b.day.replace(/[-: ]/g, '').slice(0, 12),
    o: +b.open, c: +b.close, h: +b.high, l: +b.low, vol: Math.round(+b.volume),
  }));
}

// 多源 switch-case 转移链(脚本健壮性铁律: 每种死法都有下一手)
const SOURCES = { tencent: tencentKline, sina: sinaKline };
async function fetchKline(code, gran, count, hole) {
  let lastErr;
  for (const name of ['tencent', 'sina']) {
    try {
      await jitter();
      return { bars: await SOURCES[name](code, gran, count), source: name };
    } catch (e) {
      lastErr = e;
      hole?.('kline源失败切换', `${name} ${code} ${gran} ${String(e).slice(0, 120)}`);
    }
  }
  throw lastErr;
}

// ---------- 缓存读写 ----------
const cacheFile = (code, gran) => path.join(KLINE_DIR, `${code}_${gran}.json`);
export function loadCachedBars(code, gran) {
  const f = cacheFile(code, gran);
  return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')).bars : [];
}

// ensureBars: 保证本地有覆盖 [needFrom, needTo] 的 bar; 缺则现抓回写缓存(多源+抖动)
// 返回 bars(全量, 调用方自行按日期切); 失败抛错由上层记洞
export async function ensureBars(code, gran, needFrom, needTo, hole) {
  let bars = loadCachedBars(code, gran);
  const lo = bars.length ? bars[0].t : null;
  const hi = bars.length ? bars[bars.length - 1].t : null;
  const covered = lo && hi && lo <= needFrom && hi >= needTo;
  if (covered) return bars;
  // 分钟线服务端上限: m5=640 m15/m30/m60 多抓几档拼; 日线一次 1200 根覆盖全宇宙
  const count = gran === 'day' ? 1200 : { m5: 640, m15: 800, m30: 800, m60: 800 }[gran];
  const { bars: fresh } = await fetchKline(code, gran, count, hole);
  const merged = [...bars];
  for (const b of fresh) if (!merged.some(x => x.t === b.t)) merged.push(b);
  merged.sort((a, b) => a.t < b.t ? -1 : 1);
  fs.mkdirSync(KLINE_DIR, { recursive: true });
  fs.writeFileSync(cacheFile(code, gran), JSON.stringify({ code, gran, bars: merged }));
  // 抓完仍不覆盖 = 停牌/未上市/窗口外, 返回现状让上层判断记洞
  return merged;
}

// 涨跌停幅度(可成交性过滤用): 科创68/创业30=20%, ST=5%, 其余主板=10%
export function limitPct(code, name) {
  if (name && /ST/i.test(name)) return 5;
  if (/^(sh688|sz300|sz301)/.test(code)) return 20;
  if (/^(sh8|sh4|sz8|sz4)/.test(code)) return 30;   // 北交所
  return 10;
}
export const limitUpPx = (prevClose, code, name) => +(prevClose * (1 + limitPct(code, name) / 100)).toFixed(2);
export const limitDownPx = (prevClose, code, name) => +(prevClose * (1 - limitPct(code, name) / 100)).toFixed(2);
