// scan.mjs(2026-10-02 从 plan-a 抢救回 scripts/ 根: taoge-skill 每日六榜扫描在用, 其余 plan-a 资产已压缩进 _graveyard) — 市场扫描榜单层(2026-10-01, TODO 0.7-2 / 9-28 事实包立法配套)
// 职责: 竞价/涨跌幅榜/连板梯队/跌停榜/次新区间跌幅榜/板块榜 → scan.md(LLM 事实包用)+scan.json(原始)
// 采集层只负责采全, 哪层先行归 02 市况判定(9-28 立法: 权重不硬编码进采集层)。
// 防封铁律照 quote.mjs: 多源 switch-case 故障转移 + 请求随机抖动 + 失败脚本内闭环(每榜独立 try/catch,
// 失败段写 [本榜获取失败] 不抛给上层; 全灭才 exit 1)。
// 双源实测(2026-10-01): 东财 push2 clist(主) + 新浪 getHQNodeData(备, 涨跌榜);
//   腾讯排行双源计划破产——rank.php 302→空 data、ifzq rankAction 未定义, 均已死, 勿再试。
//   连板/跌停池/次新/板块=东财单源(被封时该榜闭环标 [失败], 不编数据)。
// 封禁教训(同日实测): push2 对测试性连发(~25 次/5min)会 IP 级 ECONNRESET 全客户端静默,
//   生产节奏=每日几次×~10 请求, 榜间抖动已加大到 0.8-2s。
// 用法: node scan.mjs --out <run_dir> [--date YYYYMMDD] [--top 30]
import fs from 'fs';
import path from 'path';
import http from 'http';
import https from 'https';
import { fileURLToPath } from 'url';
import { logHealth, latestPriorScan } from './quotes/client.mjs';  // 10/7 数据源治理: 健康台账+昨日降级

const UA = { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' };
const EM_REF = { Referer: 'https://quote.eastmoney.com/' };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const jitter = () => sleep(800 + Math.random() * 1200);  // 绝不打固定节拍(封禁教训: 见文件头)

// 2026-10-01 实测: push2.eastmoney.com 的 IPv6 路由是死的(undici fetch=UND_ERR_SOCKET),
// 强制 IPv4(family:4) 即通 —— 全脚本统一走 https/http 模块 family:4, 不用全局 fetch。
// (push2ex 的 v6 恰好是通的所以涨停池首测"侥幸"成功, 别被误导; python urllib 默认 v4 所以 board_rank 一直没事)
function fetchBuf(url, headers = {}, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith('https') ? https : http;
    const req = mod.get(url, { family: 4, headers: { ...UA, ...headers }, timeout: timeoutMs }, res => {
      if (res.statusCode >= 400) { res.resume(); return reject(new Error('HTTP ' + res.statusCode)); }
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => resolve(Buffer.concat(chunks)));
    });
    req.on('timeout', () => req.destroy(new Error('timeout>' + timeoutMs + 'ms')));
    req.on('error', reject);
  });
}
async function fetchJson(url, headers = {}) {
  return JSON.parse((await fetchBuf(url, headers)).toString('utf8'));
}

// ---------- 东财 push2 clist(主源; board_rank 已验证的范式) ----------
// 全A fs: 深主板+创业板+沪主板+科创板; fields: f12代码/f14名/f2价/f3涨跌幅/f6成交额/f24 60日涨跌幅/f26上市日期
// 10/6 G-4 补全: push2 限频时切 push2delay(延迟 15min 镜像, 独立限频池; 盘后/盘前 slot=收盘数据零影响, 盘中影响小)
const FS_ALL_A = 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23';
async function emClist({ fs: fss, fid = 'f3', po = 1, pz = 30, fields = 'f12,f14,f2,f3,f6' }, host = 'push2.eastmoney.com') {
  const u = `https://${host}/api/qt/clist/get?pn=1&pz=${pz}&po=${po}&np=1&fltt=2&invt=2`
    + `&fid=${fid}&fs=${encodeURIComponent(fss)}&fields=${fields}`;
  const j = await fetchJson(u, EM_REF);
  const rows = (j.data && j.data.diff) || [];
  if (!rows.length) throw new Error('clist 空');
  return rows;
}
async function emClist2x(opt) {
  try { return await emClist(opt); }
  catch (e) { await jitter(); return await emClist(opt, 'push2delay.eastmoney.com'); }
}
const fmtPct = v => (v === '-' || v == null) ? '?' : (+v).toFixed(2) + '%';
const fmtAmt = v => (v === '-' || v == null) ? '?' : (v >= 1e8 ? (v / 1e8).toFixed(1) + '亿' : (v / 1e4).toFixed(0) + '万');

// ---------- 新浪全A排行(备源: 涨跌榜; 2026-10-01 实测活, JSON 直出) ----------
async function sinaRank(asc /* 0=涨幅榜 1=跌幅榜 */, n = 30) {
  const u = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'
    + `Market_Center.getHQNodeData?page=1&num=${n}&sort=changepercent&asc=${asc}&node=hs_a`;
  const j = await fetchJson(u, { Referer: 'https://finance.sina.com.cn' });
  if (!Array.isArray(j) || !j.length) throw new Error('sinaRank 空');
  return j.map(x => ({ code: x.symbol, name: x.name, pct: +x.changepercent, amt: +x.amount }));
}

// ---------- 东财涨停/跌停池(连板梯队的唯一结构化源; 单源风险已记录) ----------
const POOL_UT = '7eea3edcaed734bea9cbfc24409ed989';
async function emPool(type /* 'ZT'|'DT' */, date, maxBack = 5) {
  // 非交易日返回空 → 往前回退找最近有数据的交易日
  for (let i = 0; i < maxBack; i++) {
    const d = new Date(date.slice(0, 4) + '-' + date.slice(4, 6) + '-' + date.slice(6) + 'T12:00:00');
    d.setDate(d.getDate() - i);
    const ymd = d.toISOString().slice(0, 10).replaceAll('-', '');
    const u = `https://push2ex.eastmoney.com/getTopic${type}Pool?ut=${POOL_UT}&dpt=wz.ztzt&Pageindex=0&pagesize=200&sort=fbt:asc&date=${ymd}`;
    const j = await fetchJson(u, EM_REF);
    const pool = (j.data && j.data.pool) || [];
    if (pool.length) return { pool, tradeDate: ymd };
    await jitter();
  }
  throw new Error(`${type}Pool 近 ${maxBack} 天全空`);
}


// ---------- 连板梯队备源(10/6 G-4): 当日 md 加红电报的涨停分析条目机械解析 ----------
// 语义降级已标注: 电报只列焦点股(非全量池), "新华传媒 7 连板/澳弘电子 12 天 8 板"两种格式都收
function telegraphLianban(date8) {
  const results = [];
  for (let back = 0; back < 4 && !results.length; back++) {
    const d = new Date(date8.slice(0,4)+'-'+date8.slice(4,6)+'-'+date8.slice(6)+'T12:00:00');
    d.setDate(d.getDate() - back);
    const iso = d.toISOString().slice(0, 10);
    const [y, m] = iso.split('-');
    const p = path.join('md', y + 'S' + Math.ceil(+m / 3), iso + '.md');
    if (!fs.existsSync(p)) continue;
    const c = fs.readFileSync(p, 'utf8');
    const sec = c.slice(c.indexOf('## 加红电报'));
    for (const m2 of sec.matchAll(/【[^】]*涨停分析[^】]*】[^]]*/g)) {
      const txt = m2[0];
      const clean = s => {  // 剥概念前缀: "并购重组的新华传媒"/"机器人概念股襄阳轴承"/"纺织板块泰慕士"→纯票名
        for (const sep of ['的', '概念股', '板块']) { const i = s.indexOf(sep); if (i >= 0 && i + sep.length < s.length) s = s.slice(i + sep.length); }
        return s.replace(/[0-9]+$/, '');  // '中新赛克1'→'中新赛克'(正则把板数尾巴吸进名的偶发)
      };
      for (const g of txt.matchAll(/([一-龥A-Za-z0-9*ST]+)[s,，]*(?:d+天)?(d+)s*连板/g)) results.push({ name: clean(g[1]), lb: +g[2] });
      for (const g of txt.matchAll(/([一-龥A-Za-z0-9*ST]+)[s,，]*(d+)s*天s*(d+)s*板/g)) results.push({ name: clean(g[1]), lb: +g[3] });
    }
  }
  const seen = new Set();
  return results.filter(r => { const k = r.name + r.lb; if (seen.has(k) || r.name.length < 2 || !/[一-龥]/.test(r.name)) return false; seen.add(k); return true; });  // 去重+必须含中文(滤"20cm"类噪声)
}

// ---------- 各榜(每榜独立闭环) ----------
// 涨跌榜双源: 东财(主, 含成交额字段更全) → 新浪(备); 其余榜东财单源+闭环
async function rankBoard(asc, top, label) {
  try {
    const rows = await emClist2x({ fs: FS_ALL_A, fid: 'f3', po: asc ? 0 : 1, pz: top });
    const md = rows.map((r, i) => `${i + 1}. ${r.f14}(${r.f12}) ${fmtPct(r.f3)} 额${fmtAmt(r.f6)}`).join('\n');
    return { src: 'eastmoney', md, raw: rows };
  } catch (e1) {
    const rows = await sinaRank(asc, top);  // 备源也灭=异常上抛, 由主流程闭环
    const md = rows.map((r, i) => `${i + 1}. ${r.name}(${r.code}) ${fmtPct(r.pct)} 额${fmtAmt(r.amt)}`).join('\n');
    return { src: 'sina', md, raw: rows, warn: '东财主源失败: ' + e1.message };
  }
}
const board涨跌幅 = top => rankBoard(0, top);
const board跌幅 = top => rankBoard(1, top);
async function board连板(date) {
  const { pool, tradeDate } = await emPool('ZT', date);
  // zttj.ct=连板数, zttj.days=统计天数; 按连板数降序织梯队
  const rows = pool.map(x => ({ code: x.c, name: x.n, lb: x.zttj ? x.zttj.ct : 1, hy: x.hybk || '', fund: x.fund }))
    .sort((a, b) => b.lb - a.lb);
  const tiers = {};
  for (const r of rows) (tiers[r.lb] = tiers[r.lb] || []).push(`${r.name}(${r.hy})`);
  const md = [`(涨停池日期=${tradeDate}, 涨停 ${rows.length} 只)`]
    .concat(Object.keys(tiers).sort((a, b) => b - a).map(k => `${k}连板[${tiers[k].length}]: ${tiers[k].join(' ')}`));
  return { src: 'eastmoney-ztpool', md: md.join('\n'), raw: rows, tradeDate };
}
async function board跌停(date, top) {
  try {
    const { pool, tradeDate } = await emPool('DT', date);
    const md = [`(跌停池日期=${tradeDate}, 跌停 ${pool.length} 只)`]
      .concat(pool.slice(0, top).map((x, i) => `${i + 1}. ${x.n}(${x.c}) ${x.hybk || ''}`));
    return { src: 'eastmoney-dtpool', md: md.join('\n'), raw: pool };
  } catch (e) {  // 兜底: 新浪跌幅榜近似(跌幅 Top N 不等于跌停, 标注降级)
    const rows = await sinaRank(1, top);
    return { src: 'sina(降级:跌幅榜非跌停池)', warn: e.message,
      md: rows.map((r, i) => `${i + 1}. ${r.name}(${r.code}) ${fmtPct(r.pct)}`).join('\n'), raw: rows };
  }
}
async function board次新(top) {
  // 次新股板块 BK0959; f26=上市日期, f24=60日涨跌幅 → 区间跌幅榜(回撤视角)
  const rows = await emClist2x({ fs: 'b:BK0959', fid: 'f24', po: 0, pz: top, fields: 'f12,f14,f2,f3,f24,f26' });
  const md = [`(次新股板块 BK0959, 按60日涨跌幅升序=区间回撤最深)`]
    .concat(rows.map((r, i) => `${i + 1}. ${r.f14}(${r.f12}) 上市${r.f26 || '?'} 60日${fmtPct(r.f24)} 今日${fmtPct(r.f3)}`));
  return { src: 'eastmoney', md: md.join('\n'), raw: rows };
}
async function board板块() {
  const hy = await emClist2x({ fs: 'm:90+t:2', fid: 'f3', po: 1, pz: 8, fields: 'f14,f3' });
  await jitter();
  const hyDn = await emClist2x({ fs: 'm:90+t:2', fid: 'f3', po: 0, pz: 8, fields: 'f14,f3' });
  await jitter();
  const gn = await emClist2x({ fs: 'm:90+t:3', fid: 'f3', po: 1, pz: 8, fields: 'f14,f3' });
  const line = (tag, rows) => `${tag}: ` + rows.map(x => `${x.f14}${fmtPct(x.f3)}`).join(' ');
  return { src: 'eastmoney', md: [line('行业涨幅Top8', hy), line('行业跌幅Top8', hyDn), line('概念涨幅Top8', gn)].join('\n'),
    raw: { hy, hyDn, gn } };
}

// ---------- 主流程: 逐榜采集, 独立闭环, 汇总落盘 ----------
async function main() {
  const argv = process.argv.slice(2);
  const get = (k, d) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : d; };
  const outDir = get('--out', null);
  const date = get('--date', new Date().toISOString().slice(0, 10).replaceAll('-', ''));
  const top = +get('--top', 30);
  if (!outDir) { console.error('用法: node scan.mjs --out <run_dir> [--date YYYYMMDD] [--top 30]'); process.exit(2); }

  const jobs = [
    ['涨跌幅榜', '涨幅 Top' + top + '(竞价时段运行=竞价榜语义, 快照源不分时段)', () => board涨跌幅(top)],
    ['跌幅榜', '跌幅 Top' + top, () => board跌幅(top)],
    ['连板梯队', '东财涨停池按连板数织梯队', () => board连板(date)],
    ['跌停榜', '东财跌停池(失败降级=跌幅榜近似并标注)', () => board跌停(date, top)],
    ['次新区间跌幅榜', 'BK0959 按60日涨跌幅升序', () => board次新(top)],
    ['板块榜', '行业涨跌Top8+概念涨幅Top8', () => board板块()],
  ];
  const mdParts = [`# 市场扫描(${date}, scan.mjs ${new Date().toTimeString().slice(0, 5)} 现场拉取)`,
    `> 采集层只采全; 哪层先行归 02 市况判定(9-28 立法)\n`];
  const jsonOut = {};
  let okCount = 0;
  for (const [name, note, fn] of jobs) {
    try {
      const r = await fn();
      mdParts.push(`## ${name}\n来源: ${r.src}${r.warn ? ' ⚠️' + r.warn : ''} | ${note}\n${r.md}`);
      jsonOut[name] = { src: r.src, warn: r.warn || null, raw: r.raw ?? r.md };
      okCount++;
      logHealth('scan', name, r.src, true);                       // 10/7: 健康台账
      console.log(`[scan] ${name} OK (${r.src})`);
    } catch (e) {
      mdParts.push(`## ${name}\n[本榜获取失败: ${String(e.message || e).slice(0, 200)}]`);
      jsonOut[name] = { src: null, error: String(e.message || e).slice(0, 200) };
      logHealth('scan', name, null, false, e.message || e);       // 10/7: 失败也记账
      console.log(`[scan] ${name} FAIL: ${String(e.message || e).slice(0, 100)}`);
    }
    await jitter();  // 榜间抖动, 防固定节拍
  }
  fs.mkdirSync(outDir, { recursive: true });

  // §5.5 对策(10/7): 全灭不再 exit 1(Java misfire=丢弃不重试, 链断)——降级续用最近历史产物+大标注, 链照跑
  if (!okCount) {
    const prior = latestPriorScan(path.dirname(outDir.replace(/[\\/]$/, '')), path.basename(outDir.replace(/[\\/]$/, '')));
    if (prior) {
      const warn = `# ⚠️ 降级: 今日六榜全灭(东财限频?), 续用 ${prior.from} 的 scan 产物——时效性降级, 02 市况判定须按 T-1 口径`;
      fs.writeFileSync(path.join(outDir, 'scan.md'), warn + '\n\n' + (prior.md || JSON.stringify(prior.json)), 'utf8');
      fs.writeFileSync(path.join(outDir, 'scan.json'), JSON.stringify({ ...prior.json, degraded_from: prior.from }, null, 1), 'utf8');
      logHealth('scan', 'ALL', 'yesterday-fallback', true, '全灭降级续用 ' + prior.from);
      console.log(`[scan] 全灭降级: 续用 ${prior.from} 产物(链不断)`);
      process.exit(0);
    }
    logHealth('scan', 'ALL', null, false, '全灭且无历史可降级');
  }
  fs.writeFileSync(path.join(outDir, 'scan.md'), mdParts.join('\n\n'), 'utf8');
  fs.writeFileSync(path.join(outDir, 'scan.json'), JSON.stringify(jsonOut, null, 1), 'utf8');
  console.log(`[scan] ${okCount}/${jobs.length} 榜成功 → ${path.join(outDir, 'scan.md')}`);
  process.exit(okCount ? 0 : 1);  // 全灭且无历史才非零(部分失败不影响 facts 组装, md 里已标注)
}
main();
