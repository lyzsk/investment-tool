// rotation.mjs — 板块轮动图谱(跨日维度, 2026-10-04 盲区修复⑥; scan.mjs 管当日榜, 本脚本管跨日传导)
// 数据源: 东财 ZT 涨停池历史(每日快照落 history.json) + seed.json 经验先验(用户口述链路, 可手改)
// 产物: history.json(每日涨停池×板块) / matrix.json(板块涨停数日间转移矩阵) / --digest 当前位置判定
// 用法:
//   node scripts/rotation.mjs --backfill [--days 40]   回填历史(幂等, 空日=节假日或数据洞, 记 holes 跳过)
//   node scripts/rotation.mjs --matrix                 由 history 重算转移矩阵
//   node scripts/rotation.mjs --digest                 当前位置判定(纯本地, facts.mjs 每 slot 调)
//   node scripts/rotation.mjs --belong 603200          个股→板块/概念归属(F10 核心题材, ad hoc 查询)
// 已知数据洞: 20260925 东财 ZT 池单日为空(邻居日正常, 实测 2026-10-04); push2 系须强制 IPv4(scan.mjs 教训)
import fs from 'fs';
import path from 'path';
import http from 'http';
import https from 'https';
import zlib from 'zlib';

const UA = { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' };
const EM_REF = { Referer: 'https://quote.eastmoney.com/' };
const POOL_UT = '7eea3edcaed734bea9cbfc24409ed989';
const DIR = path.resolve('scripts/rotation');
const HIST = path.join(DIR, 'history.json');
const SEED = path.join(DIR, 'seed.json');
const MATRIX = path.join(DIR, 'matrix.json');
const HOT_MIN = 3;        // 板块涨停数≥此值=当日热点板
const FADE_RATIO = 0.5;   // 涨停数环比降幅≥50% 或退出热点=衰减
const RISE_MIN = 3;       // 涨停数净增≥3 或 0→≥HOT_MIN=启动

const sleep = ms => new Promise(r => setTimeout(r, ms));
const jitter = () => sleep(800 + Math.random() * 1200);  // 防封: 绝不打固定节拍(scan.mjs 教训)
const arg = k => { const i = process.argv.indexOf('--' + k); return i > -1 ? process.argv[i + 1] : null; };
const has = k => process.argv.includes('--' + k);

// push2 系 IPv6 死路由, 统一 family:4(scan.mjs 实测教训)
function fetchBuf(url, headers = {}, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith('https') ? https : http;
    const req = mod.get(url, { family: 4, headers: { ...UA, ...headers }, timeout: timeoutMs }, res => {
      if (res.statusCode >= 400) { res.resume(); return reject(new Error('HTTP ' + res.statusCode)); }
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => {  // emweb F10 会强制 gzip, 按头解压
        let buf = Buffer.concat(chunks);
        try { if (res.headers['content-encoding'] === 'gzip') buf = zlib.gunzipSync(buf); } catch { }
        resolve(buf);
      });
    });
    req.on('timeout', () => req.destroy(new Error('timeout>' + timeoutMs + 'ms')));
    req.on('error', reject);
  });
}
const fetchJson = async (u, h = {}) => JSON.parse((await fetchBuf(u, h)).toString('utf8'));

const localYmd = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;  // 禁 toISOString: UTC 偏移会吞一天(凌晨跑必踩)

async function ztPool(ymd) {  // 单日涨停池; 空/节假日回声=返回 null
  const u = `https://push2ex.eastmoney.com/getTopicZTPool?ut=${POOL_UT}&dpt=wz.ztzt&Pageindex=0&pagesize=200&sort=fbt:asc&date=${ymd}`;
  const j = await fetchJson(u, EM_REF);
  const pool = (j.data && j.data.pool) || [];
  if (!pool.length) return null;
  // 节假日回声闸(10/4 实测): 非交易日查询会返回"最近交易日"的池子(52/52 全同), qdate=真实数据日 ≠ 查询日 → 拒收
  if (j.data && j.data.qdate && String(j.data.qdate) !== ymd.replaceAll('-', '')) return null;
  return pool.map(x => ({ c: x.c, n: x.n, hy: x.hybk || '未知', lb: x.zttj ? x.zttj.ct : 1 }));
}

const load = (f, dflt) => (fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')) : dflt);
const save = (f, o) => { fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, JSON.stringify(o, null, 1), 'utf8'); };
const tradeDays = hist => Object.keys(hist.days || {}).sort();  // 历史内交易日(自身即日历)

// ---------- --backfill: 回填 ZT 池历史(幂等) ----------
async function backfill(days) {
  const hist = load(HIST, { _meta: '东财 ZT 涨停池每日快照(rotation.mjs 回填)', days: {}, holes: [] });
  const today = new Date();
  let got = 0, skip = 0;
  for (let i = 1; i <= days; i++) {  // i=1 起: 当日盘中数据不全, 由 scan/facts 链路当天 EOD 后另补(--backfill --days 2 可刷近日)
    const d = new Date(today); d.setDate(d.getDate() - i);
    if (d.getDay() === 0 || d.getDay() === 6) continue;  // 周末先剪
    const ymd = localYmd(d);
    if (hist.days[ymd]) { skip++; continue; }  // 幂等: 已有不重拉
    try {
      const pool = await ztPool(ymd.replaceAll('-', ''));
      if (!pool) { if (!hist.holes.includes(ymd)) hist.holes.push(ymd); continue; }  // 节假日或数据洞
      const boards = {};
      for (const s of pool) boards[s.hy] = (boards[s.hy] || 0) + 1;
      hist.days[ymd] = { total: pool.length, boards, stocks: pool };
      got++; console.log(`[backfill] ${ymd}: ${pool.length} 只, ${Object.keys(boards).length} 板块`);
    } catch (e) { console.error(`[backfill] ${ymd} FAIL: ${e.message}(跳过, 下轮重试)`); }
    await jitter();
  }
  save(HIST, hist);
  console.log(`[backfill] 新入 ${got} 日, 已有跳过 ${skip} 日, 累计 ${tradeDays(hist).length} 交易日, holes=${hist.holes.length}`);
}

// ---------- --matrix: 板块涨停数日间转移矩阵 ----------
// 语义: 相邻交易日对(T,T+1), T 衰减板(降幅≥50%/退出热点) × T+1 启动板(新入热点/净增≥3) 计一条 F→R 边
function matrix() {
  const hist = load(HIST, { days: {} });
  const ds = tradeDays(hist);
  if (ds.length < 5) { console.error('history 不足 5 交易日, 先 --backfill'); process.exit(1); }
  const edges = {}; let pairs = 0;
  for (let i = 0; i < ds.length - 1; i++) {
    const a = hist.days[ds[i]].boards, b = hist.days[ds[i + 1]].boards;
    const hotA = Object.keys(a).filter(k => a[k] >= HOT_MIN), hotB = new Set(Object.keys(b).filter(k => b[k] >= HOT_MIN));
    const fades = Object.keys(a).filter(k => hotA.includes(k) && (!hotB.has(k) || b[k] <= a[k] * FADE_RATIO) || (a[k] >= HOT_MIN && !(k in b)));
    const rises = Object.keys(b).filter(k => (!a[k] && b[k] >= HOT_MIN) || (b[k] - (a[k] || 0) >= RISE_MIN));
    for (const f of fades) for (const r of rises) { if (f === r) continue; (edges[f] = edges[f] || {})[r] = (edges[f][r] || 0) + 1; }
    pairs++;
  }
  save(MATRIX, { _meta: `转移矩阵: 衰减板→启动板 共现计数, 窗口=${pairs} 对, HOT_MIN=${HOT_MIN} FADE=${FADE_RATIO} RISE=${RISE_MIN}`, pairs, edges });
  console.log(`[matrix] ${pairs} 对相邻交易日, ${Object.keys(edges).length} 个衰减源板 → matrix.json`);
}

// ---------- --digest: 当前位置判定(facts.mjs 每 slot 调, 纯本地零网络) ----------
function directionOf(board, alias) {  // 板块→方向(seed alias 子串匹配)
  for (const [dir, kws] of Object.entries(alias)) if (kws.some(k => board.includes(k))) return dir;
  return null;
}
function digest() {
  const hist = load(HIST, { days: {} });
  const seed = load(SEED, { families: {}, edges: [], board_alias: {} });
  const ds = tradeDays(hist);
  if (ds.length < 3) { console.log('(rotation 历史不足 3 日, 先 node scripts/rotation.mjs --backfill)'); return; }
  const [d0, d1, d2] = ds.slice(-3);  // 最新三日
  const B = d => hist.days[d].boards;
  const alias = seed.board_alias || {};
  // 方向级聚合(家族内各方向涨停数合计; 未命中 alias 的板块单列)
  const agg = d => {
    const out = {};
    for (const [b, n] of Object.entries(B(d))) { const dir = directionOf(b, alias) || b; out[dir] = (out[dir] || 0) + n; }
    return out;
  };
  const [g0, g1, g2] = [agg(d0), agg(d1), agg(d2)];
  const dirs = [...new Set([...Object.keys(g0), ...Object.keys(g1), ...Object.keys(g2)])];
  const series = k => `${g0[k] || 0}→${g1[k] || 0}→${g2[k] || 0}`;
  const fading = dirs.filter(k => (g1[k] || 0) >= HOT_MIN && (g2[k] || 0) <= (g1[k] || 0) * FADE_RATIO && (g2[k] || 0) < HOT_MIN);
  const rising = dirs.filter(k => ((g1[k] || 0) < HOT_MIN && (g2[k] || 0) >= HOT_MIN) || ((g2[k] || 0) - (g1[k] || 0) >= RISE_MIN));
  const hot = dirs.filter(k => (g2[k] || 0) >= HOT_MIN && !rising.includes(k));
  const lines = [`数据=东财涨停池 ${d0}~${d2}(最新=${d2}, 当日 ${hist.days[d2].total} 只涨停)`, ''];
  lines.push(`**热点中**: ${hot.map(k => `${k}(${series(k)})`).join('、') || '无'}`);
  lines.push(`**衰减中**: ${fading.map(k => `${k}(${series(k)})`).join('、') || '无'}`);
  lines.push(`**新启动**: ${rising.map(k => `${k}(${series(k)})`).join('、') || '无'}`);
  // seed 传导链命中: 有边 F→R 且 F 衰减 + R 启动 = 切换确认; F 衰减 R 未启动 = 观察
  const edgeHit = [];
  for (const e of seed.edges || []) {
    const fromF = fading.includes(e.from), toR = (e.to || []).filter(t => rising.includes(t));
    if (fromF && toR.length) edgeHit.push(`✅ 切换确认: ${e.from}→${toR.join('/')}(旧衰+新启同时满足)`);
    else if (fromF) edgeHit.push(`👀 观察: ${e.from} 衰减中, 候选承接 ${(e.to || []).join('/')}(未达启动阈)`);
    else if (toR.length) edgeHit.push(`👀 观察: ${toR.join('/')} 启动, 但先验上游 ${e.from} 未见衰减(可能独立行情)`);
  }
  lines.push('', '**传导链(seed 先验 × 实证)**:', edgeHit.length ? edgeHit.join('\n') : '(无命中: 无先验边的衰减/启动组合)');
  // 大切换警戒: 家族合计
  for (const [fam, members] of Object.entries(seed.families || {})) {
    const sum = g => members.reduce((s, m) => s + (g[m] || 0), 0);
    lines.push(`家族[${fam}]: ${sum(g0)}→${sum(g1)}→${sum(g2)}`);
  }
  // 实证矩阵 Top 边
  const mx = load(MATRIX, null);
  if (mx && mx.edges) {
    const flat = [];
    for (const [f, to] of Object.entries(mx.edges)) for (const [t, n] of Object.entries(to)) flat.push([f, t, n]);
    flat.sort((a, b) => b[2] - a[2]);
    lines.push('', `**实证转移 Top5(窗口 ${mx.pairs} 对)**: ${flat.slice(0, 5).map(([f, t, n]) => `${f}→${t}×${n}`).join('、') || '(无)'}`);
  }
  console.log(lines.join('\n'));
}

// ---------- --belong: 个股→板块归属(F10 核心题材 PageAjax, 实测 2026-10-04) ----------
async function belong(code) {
  const mkt = /^(60|68|11[0138]|5)/.test(code) ? 'SH' : (/^(8|4|920)/.test(code) ? 'BJ' : 'SZ');
  const j = await fetchJson(`https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax?code=${mkt}${code}`,
    { Referer: 'https://emweb.securities.eastmoney.com/' });
  const rows = (j.ssbk || []).map(x => `${x.BOARD_NAME}${x.IS_PRECISE === '1' ? '★' : ''}`);
  console.log(`${code} 所属板块: ${rows.join('、') || '(空)'}`);
}

(async () => {
  if (has('backfill')) return await backfill(+(arg('days') || 40));
  if (has('matrix')) return matrix();
  if (has('digest')) return digest();
  if (has('belong')) return await belong(arg('belong'));
  console.error('用法: --backfill [--days N] | --matrix | --digest | --belong <code>');
  process.exit(1);
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });
