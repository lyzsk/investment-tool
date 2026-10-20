// scan.mjs(2026-10-02 从 plan-a 抢救回 scripts/ 根: taoge-skill 每日六榜扫描在用, 其余 plan-a 资产已压缩进 _graveyard) — 市场扫描榜单层(2026-10-01, TODO 0.7-2 / 9-28 事实包立法配套)
// 职责: 竞价/涨跌幅榜/连板梯队/跌停榜/次新区间跌幅榜/板块榜 → scan.md(LLM 事实包用)+scan.json(原始)
// 采集层只负责采全, 哪层先行归 02 市况判定(9-28 立法: 权重不硬编码进采集层)。
// 防封铁律照 quote.mjs: 多源 switch-case 故障转移 + 请求随机抖动 + 失败脚本内闭环(每榜独立 try/catch,
// 失败段写 [本榜获取失败] 不抛给上层; 全灭才 exit 1)。
// 双源实测(2026-10-01): 东财 push2 clist(主) + 新浪 getHQNodeData(备, 涨跌榜);
//   腾讯排行双源计划破产——rank.php 302→空 data、ifzq rankAction 未定义, 均已死, 勿再试。
//   连板梯队=东财涨停池→财联社涨停池(10/14)→md 电报解析; 跌停池/次新/板块=东财单源(被封时该榜闭环标 [失败], 不编数据)。
// 封禁教训(同日实测): push2 对测试性连发(~25 次/5min)会 IP 级 ECONNRESET 全客户端静默,
//   生产节奏=每日几次×~10 请求, 榜间抖动已加大到 0.8-2s。
// 用法: node scan.mjs --out <run_dir> [--date YYYYMMDD] [--top 30] [--asof YYYYMMDD(历史数据日=回放口径, 零实时源)]
import fs from 'fs';
import path from 'path';
import http from 'http';
import https from 'https';
import { fileURLToPath } from 'url';
import { logHealth, latestPriorScan } from './quotes/client.mjs';
import { gcall } from './lib/req_guard.mjs';  // 10/15 统一请求层: 按域名记账/熔断/窗口(push2 18 次/5min), 熔断中的源直接抛错走本脚本已有的备源  // 10/7 数据源治理: 健康台账+昨日降级

const UA = { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' };
const EM_REF = { Referer: 'https://quote.eastmoney.com/' };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const jitter = () => sleep(800 + Math.random() * 1200);  // 绝不打固定节拍(封禁教训: 见文件头)

// 2026-10-01 实测: push2.eastmoney.com 的 IPv6 路由是死的(undici fetch=UND_ERR_SOCKET),
// 强制 IPv4(family:4) 即通 —— 全脚本统一走 https/http 模块 family:4, 不用全局 fetch。
// (push2ex 的 v6 恰好是通的所以涨停池首测"侥幸"成功, 别被误导; python urllib 默认 v4 所以 board_rank 一直没事)
function fetchBuf(url, headers = {}, timeoutMs = 8000) {
  // 10/15 实测反转: push2/push2delay 的 clist 走 IPv4 一律 socket hang up(当日 48 次全败, 同机 curl/fetch 走 IPv6=200),
  // 10/01 时恰好相反(v6 死 v4 活) → 双栈兜底: 先 v4, 连接级失败再试 v6, 不写死某一栈
  return gcall(url, async () => {
    try { return await fetchBufRaw(url, headers, timeoutMs, 4); }
    catch (e) {
      if (/HTTP \d/.test(String(e.message))) throw e;   // 服务端明确拒绝(4xx/5xx)不换栈
      return await fetchBufRaw(url, headers, timeoutMs, 6);
    }
  }, { maxWaitMs: 15000 });  // facts.mjs 给 scan 120s 总时限, 限速等待封顶 15s
}
function fetchBufRaw(url, headers = {}, timeoutMs = 8000, family = 4) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith('https') ? https : http;
    const req = mod.get(url, { family, headers: { ...UA, ...headers }, timeout: timeoutMs }, res => {
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
  // 10/19 收盘后两栈实测: push2delay 的 clist 走 IPv4 / IPv6 都 socket hang up(10/13 起每天 0~1 次成功, 天天熔断报红)
  // → delay 从"push2 失败后第二选择"降到各榜备源(新浪 / 本地库)之后, 由 emDelay() 在备源也失败时最后一试
  return await emClist(opt);
}
async function emDelay(opt) { await jitter(); return await emClist(opt, 'push2delay.eastmoney.com'); }
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
    const u = `https://push2ex.eastmoney.com/getTopic${type}Pool?ut=${POOL_UT}&dpt=wz.ztzt&Pageindex=0&pagesize=200&sort=${type === 'DT' ? 'fund:asc' : 'fbt:asc'}&date=${ymd}`;  // 10/10 修: DT 池无 fbt 字段, 按 fbt 排序=空池(跌停榜此前一直降级新浪)
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
    for (const m2 of sec.matchAll(/【[^】]*涨停分析[^】]*】[^\]]*/g)) {  // 10/14 修: 原 [^]]* 在 JS 里=任意 1 字符+若干 ], 只截到标题
      const txt = m2[0];
      const clean = s => {  // 剥概念前缀: "并购重组的新华传媒"/"机器人概念股襄阳轴承"/"纺织板块泰慕士"→纯票名
        for (const sep of ['的', '概念股', '板块']) { const i = s.indexOf(sep); if (i >= 0 && i + sep.length < s.length) s = s.slice(i + sep.length); }
        return s.replace(/[0-9]+$/, '');  // '中新赛克1'→'中新赛克'(正则把板数尾巴吸进名的偶发)
      };
      // 10/14 修: 原两条正则的反斜杠在 10/6 写入时被 heredoc 吃掉(\s→s, \d→d), 从未匹配过; 此前未接线所以没暴露
      for (const g of txt.matchAll(/([一-龥A-Za-z0-9*ST]+)[\s,，]*(?:\d+天)?(\d+)\s*连板/g)) results.push({ name: clean(g[1]), lb: +g[2] });
      for (const g of txt.matchAll(/([一-龥A-Za-z0-9*ST]+)[\s,，]*(\d+)\s*天\s*(\d+)\s*板/g)) results.push({ name: clean(g[1]), lb: +g[3] });
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
    let rows;
    try { rows = await sinaRank(asc, top); }
    catch (e2) {   // 新浪也灭 → 东财延迟镜像最后一试(10/19 降级); 再灭=异常上抛, 由主流程闭环
      const er = await emDelay({ fs: FS_ALL_A, fid: 'f3', po: asc ? 0 : 1, pz: top });
      return { src: 'eastmoney-delay15m', md: er.map((r, i) => `${i + 1}. ${r.f14}(${r.f12}) ${fmtPct(r.f3)} 额${fmtAmt(r.f6)}`).join('\n'), raw: er,
        warn: `东财主源失败: ${e1.message}; 新浪失败: ${e2.message}` };
    }
    const md = rows.map((r, i) => `${i + 1}. ${r.name}(${r.code}) ${fmtPct(r.pct)} 额${fmtAmt(r.amt)}`).join('\n');
    return { src: 'sina', md, raw: rows, warn: '东财主源失败: ' + e1.message };
  }
}
const board涨跌幅 = top => rankBoard(0, top);
const board跌幅 = top => rankBoard(1, top);
// 连板梯队备源①(10/14 REA 调研): 财联社涨停池 x-quote.cls.cn up_down_analysis?type=up_pool, 公开免签名, 全量池
// (10/13 实测 70 只=收评涨停数), limit_up_days=连板数, up_reason "题材|归因" 取竖线前作题材; 只有实时/最近一个交易日,
// 故 as-of 历史口径不可用。口径差: 东财 zttj.ct=统计窗内涨停次数("17天10板"记 10), 财联社=连续涨停天数, 标注在 src
async function clsLianban() {
  const j = await fetchJson('https://x-quote.cls.cn/quote/index/up_down_analysis?app=CailianpressWeb&os=web&rever=1&sv=8.7.9&type=up_pool&way=last_px',
    { Referer: 'https://www.cls.cn/', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36' });
  if (j.code !== 200 || !Array.isArray(j.data) || !j.data.length) throw new Error(`财联社涨停池空/异常 code=${j.code}`);
  const tradeDate = j.data.map(x => x.time || '').sort().pop().slice(0, 10).replaceAll('-', '');
  return j.data.map(x => ({ code: x.secu_code.replace(/^(sh|sz|bj)/, ''), name: x.secu_name.trim(), lb: x.limit_up_days || 1,
    hy: String(x.up_reason || '').includes('|') ? String(x.up_reason).split('|')[0].trim() : (x.is_st ? 'ST' : '') })).map(r => ({ ...r, tradeDate }));
}
// 10/14 用户定口径: 窗口内涨停次数 = "N天M板"(3天3板/3天2板都可能); 东财 zttj.days/ct 直接给; 财联社备源只有连续天数, 记作 N天N板
function tiersMd(rows, head) {
  const tiers = {};
  const lab = (r) => ((r.days || r.lb) <= 1 && r.lb <= 1 ? '首板' : `${r.days || r.lb}天${r.lb}板`);
  for (const r of rows.sort((a, b) => b.lb - a.lb || (a.days || a.lb) - (b.days || b.lb))) (tiers[lab(r)] = tiers[lab(r)] || []).push(`${r.name}(${r.hy})`);
  return [head].concat(Object.entries(tiers).map(([k, v]) => `${k}[${v.length}]: ${v.join(' ')}`)).join('\n');
}
// 故障转移(10/14): 东财涨停池(主) → 财联社涨停池(备①, 仅实时口径) → md 加红电报解析(备②, 只含焦点股, 10/6 写好但此前未接线)
// SCAN_DRILL=ztpool 环境变量=演练开关(模拟东财失败, 验备源; 生产不设)
async function board连板(date, maxBack = 5, asof = false) {
  let emErr;
  try {
    if (process.env.SCAN_DRILL === 'ztpool') throw new Error('演练: 模拟东财涨停池失败');
    const { pool, tradeDate } = await emPool('ZT', date, maxBack);
    // zttj.ct=连板数, zttj.days=统计天数; 按连板数降序织梯队
    const rows = pool.map(x => ({ code: x.c, name: x.n, lb: x.zttj ? x.zttj.ct : 1, days: x.zttj ? x.zttj.days : 1, hy: x.hybk || '', fund: x.fund }));
    return { src: 'eastmoney-ztpool', md: tiersMd(rows, `(涨停池日期=${tradeDate}, 涨停 ${rows.length} 只)`), raw: rows, tradeDate };
  } catch (e) { emErr = e; }
  if (asof) throw emErr;  // as-of 禁降级: 备源都只有实时/当日数据
  try {
    const rows = await clsLianban();
    const tradeDate = rows[0].tradeDate;
    return { src: 'cls-uppool(连板=连续涨停天数口径)', warn: '东财涨停池失败: ' + String(emErr.message || emErr).slice(0, 80),
      md: tiersMd(rows, `(财联社涨停池日期=${tradeDate}, 涨停 ${rows.length} 只)`), raw: rows, tradeDate };
  } catch (e2) {
    const tl = telegraphLianban(date);
    if (!tl.length) throw new Error(`东财: ${String(emErr.message || emErr).slice(0, 60)} | 财联社: ${String(e2.message || e2).slice(0, 60)} | 电报解析: 无`);
    return { src: 'md-telegraph(降级: 只含电报点名的焦点股, 非全量池)', warn: `东财+财联社均失败: ${String(e2.message || e2).slice(0, 60)}`,
      md: tiersMd(tl.map(r => ({ ...r, hy: '' })), `(加红电报涨停分析解析, ${tl.length} 只焦点股)`), raw: tl };
  }
}
async function board跌停(date, top, noFallback = false) {
  try {
    const { pool, tradeDate } = await emPool('DT', date, noFallback ? 1 : 5);
    const md = [`(跌停池日期=${tradeDate}, 跌停 ${pool.length} 只)`]
      .concat(pool.slice(0, top).map((x, i) => `${i + 1}. ${x.n}(${x.c}) ${x.hybk || ''}`));
    return { src: 'eastmoney-dtpool', md: md.join('\n'), raw: pool };
  } catch (e) {  // 兜底: 新浪跌幅榜近似(跌幅 Top N 不等于跌停, 标注降级)
    if (noFallback) throw e;  // as-of 禁降级: 新浪只有实时数据
    const rows = await sinaRank(1, top);
    return { src: 'sina(降级:跌幅榜非跌停池)', warn: e.message,
      md: rows.map((r, i) => `${i + 1}. ${r.name}(${r.code}) ${fmtPct(r.pct)}`).join('\n'), raw: rows };
  }
}
async function board次新(top) {
  // 次新股板块 BK0959; f26=上市日期, f24=60日涨跌幅 → 区间跌幅榜(回撤视角)
  try {
    if (process.env.SCAN_DRILL === 'cixin') throw new Error('演练: 跳过东财 BK0959');
    const rows = await emClist2x({ fs: 'b:BK0959', fid: 'f24', po: 0, pz: top, fields: 'f12,f14,f2,f3,f24,f26' });
    const md = [`(次新股板块 BK0959, 按60日涨跌幅升序=区间回撤最深)`]
      .concat(rows.map((r, i) => `${i + 1}. ${r.f14}(${r.f12}) 上市${r.f26 || '?'} 60日${fmtPct(r.f24)} 今日${fmtPct(r.f3)}`));
    return { src: 'eastmoney', md: md.join('\n'), raw: rows };
  } catch (e) {
    // 10/17 A12 备源(switch-case): 东财单源被封时本榜原先整榜缺 → 本地行情库(security_master.list_date 近一年 + kline_day)算 60 日涨跌, 零请求;
    //   口径=行情库最新交易日收盘(盘前/盘中跑=T-1), 60 日涨跌对 60 个交易日前收盘(上市不足 60 日=对首日收盘), 与东财 f24 近似不等同
    const { spawnSync } = await import('node:child_process');
    const PY = path.join(path.dirname(fileURLToPath(import.meta.url)), 'venv', 'Scripts', 'python.exe');
    const r = spawnSync(PY, ['-X', 'utf8', path.join(path.dirname(fileURLToPath(import.meta.url)), 'quotes', 'cixin_local.py'), '--top', String(top)],
      { encoding: 'utf8', windowsHide: true, timeout: 30000 });
    let j = null;
    try { j = JSON.parse((r.stdout || '').trim().split('\n').pop()); } catch { /* 下面统一报错 */ }
    if (!j || j.error || !j.rows?.length) {
      try {   // 10/19: 本地库也不行 → 东财延迟镜像最后一试
        const er = await emDelay({ fs: 'b:BK0959', fid: 'f24', po: 0, pz: top, fields: 'f12,f14,f2,f3,f24,f26' });
        return { src: 'eastmoney-delay15m', warn: String(e.message || e).slice(0, 80), raw: er,
          md: [`(次新股板块 BK0959, 东财延迟镜像, 按60日涨跌幅升序)`].concat(er.map((r, i) => `${i + 1}. ${r.f14}(${r.f12}) 上市${r.f26 || '?'} 60日${fmtPct(r.f24)} 今日${fmtPct(r.f3)}`)).join('\n') };
      } catch { /* 下面统一报错 */ }
      throw new Error(`东财: ${e.message}; 本地备源: ${j?.error || r.error?.message || (r.stderr || '').slice(0, 120) || '无输出'}`);
    }
    const md = [`(东财失败, 本地行情库兜底: 近一年上市 ${j.n} 只, 数据日 ${j.asof} 收盘, 按60日涨跌幅升序; 60日=对60个交易日前收盘, 上市不足60日对首日收盘, 与东财口径近似)`]
      .concat(j.rows.map((x, i) => `${i + 1}. ${x.name}(${x.code}) 上市${x.list_date} 60日${fmtPct(x.pct60)} ${j.asof.slice(5)}日${fmtPct(x.pct_today)}`));
    return { src: 'local-db(东财失败兜底)', warn: String(e.message || e).slice(0, 80), md: md.join('\n'), raw: j.rows };
  }
}
async function board板块() {
  try {
    const hy = await emClist2x({ fs: 'm:90+t:2', fid: 'f3', po: 1, pz: 8, fields: 'f14,f3' });
    await jitter();
    const hyDn = await emClist2x({ fs: 'm:90+t:2', fid: 'f3', po: 0, pz: 8, fields: 'f14,f3' });
    await jitter();
    const gn = await emClist2x({ fs: 'm:90+t:3', fid: 'f3', po: 1, pz: 8, fields: 'f14,f3' });
    const line = (tag, rows) => `${tag}: ` + rows.map(x => `${x.f14}${fmtPct(x.f3)}`).join(' ');
    return { src: 'eastmoney', md: [line('行业涨幅Top8', hy), line('行业跌幅Top8', hyDn), line('概念涨幅Top8', gn)].join('\n'),
      raw: { hy, hyDn, gn } };
  } catch (e) {
    // 10/11 夜: 东财 push2/push2delay 整个 IP 被断连时板块榜整榜缺失 → 新浪行业/概念板块兜底(多源切换铁律)
    await jitter();
    try { return await sina板块(e.message); }
    catch (e2) {   // 10/19: 新浪也灭 → 东财延迟镜像最后一试
      const hy = await emDelay({ fs: 'm:90+t:2', fid: 'f3', po: 1, pz: 8, fields: 'f14,f3' });
      const hyDn = await emDelay({ fs: 'm:90+t:2', fid: 'f3', po: 0, pz: 8, fields: 'f14,f3' });
      const gn = await emDelay({ fs: 'm:90+t:3', fid: 'f3', po: 1, pz: 8, fields: 'f14,f3' });
      const line = (tag, rows) => `${tag}: ` + rows.map(x => `${x.f14}${fmtPct(x.f3)}`).join(' ');
      return { src: 'eastmoney-delay15m', warn: `东财: ${e.message}; 新浪: ${e2.message}`,
        md: [line('行业涨幅Top8', hy), line('行业跌幅Top8', hyDn), line('概念涨幅Top8', gn)].join('\n'), raw: { hy, hyDn, gn } };
    }
  }
}
// 新浪板块: "var X = {"id":"id,名称,家数,均价,涨跌额,涨跌幅%,量,额,领涨代码,领涨涨幅,..."}"; 板块划分与东财不同, 输出标注口径
async function sina板块(emErr) {
  const parse = buf => {
    const t = new TextDecoder('gbk').decode(buf);
    const obj = JSON.parse(t.slice(t.indexOf('{'), t.lastIndexOf('}') + 1));
    return Object.values(obj).map(v => v.split(',')).map(f => ({ name: f[1], pct: +f[5] })).filter(x => x.name && Number.isFinite(x.pct));
  };
  const hyAll = parse(await fetchBuf('https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php', { Referer: 'https://finance.sina.com.cn' }));
  await jitter();
  const gnAll = parse(await fetchBuf('https://money.finance.sina.com.cn/q/view/newFLJK.php?param=class', { Referer: 'https://finance.sina.com.cn' }));
  if (!hyAll.length || !gnAll.length) throw new Error('新浪板块空; 东财: ' + emErr);
  const top = (rows, asc) => [...rows].sort((a, b) => asc ? a.pct - b.pct : b.pct - a.pct).slice(0, 8);
  const line = (tag, rows) => `${tag}: ` + rows.map(x => `${x.name}${fmtPct(x.pct)}`).join(' ');
  return { src: 'sina', md: ['(东财断连, 新浪板块口径兜底: 行业/概念划分与东财不同)', line('行业涨幅Top8', top(hyAll)),
    line('行业跌幅Top8', top(hyAll, true)), line('概念涨幅Top8', top(gnAll))].join('\n') };
}

// ---------- as-of 回放榜(10/10 9/28-30 补跑语义修复) ----------
// 历史日能取到的只有 东财涨停/跌停池(按日期) + 日线归档; 涨跌幅榜=归档样本内(~750 只, 非全市场)按该日涨跌幅排序;
// 次新/板块榜无历史源 → 显式标不可得, 禁编
function archiveRank(date8, asc, top) {
  const d = `${date8.slice(0, 4)}-${date8.slice(4, 6)}-${date8.slice(6)}`;
  const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'downloads', 'quotes', 'daily');
  const rows = [];
  for (const f of fs.readdirSync(dir)) {
    if (!/^\d{6}\.json$/.test(f)) continue;
    try {
      const k = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')).klines || [];
      const i = k.findIndex(x => x.d === d);
      if (i > 0 && k[i - 1].c > 0) rows.push({ code: f.slice(0, 6), pct: (k[i].c / k[i - 1].c - 1) * 100, amt: k[i].a });
    } catch { /* 坏档跳过 */ }
  }
  if (!rows.length) throw new Error(`归档无 ${d} 日线`);
  rows.sort((a, b) => (asc ? a.pct - b.pct : b.pct - a.pct));
  const md = [`(as-of 近似: 日线归档样本 ${rows.length} 只内排序, 非全市场; 归档无票名)`]
    .concat(rows.slice(0, top).map((r, i) => `${i + 1}. (${r.code}) ${fmtPct(r.pct)}${r.amt > 0 ? ' 额' + fmtAmt(r.amt) : ''}`));  // 腾讯源归档 a=0
  return { src: 'asof-archive', md: md.join('\n'), raw: rows.slice(0, top) };
}
const NA_ASOF = async () => { throw new Error('as-of 回放: 该榜无历史数据源, 不可得(禁编)'); };

// ---------- 主流程: 逐榜采集, 独立闭环, 汇总落盘 ----------
async function main() {
  const argv = process.argv.slice(2);
  const get = (k, d) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : d; };
  const outDir = get('--out', null);
  const date = get('--date', new Date().toLocaleDateString("sv-SE").replaceAll('-', ''));
  const top = +get('--top', 30);
  const asof = get('--asof', null);  // YYYYMMDD=历史数据日(链日前一交易日): 全榜改历史口径, 零实时源
  if (!outDir) { console.error('用法: node scan.mjs --out <run_dir> [--date YYYYMMDD] [--top 30] [--asof YYYYMMDD]'); process.exit(2); }

  const jobs = asof ? [
    ['涨跌幅榜', `涨幅 Top${top}(as-of 归档样本近似)`, async () => archiveRank(asof, false, top)],
    ['跌幅榜', `跌幅 Top${top}(as-of 归档样本近似)`, async () => archiveRank(asof, true, top)],
    ['连板梯队', '东财涨停池(历史日期)按连板数织梯队', () => board连板(asof, 1, true)],
    ['跌停榜', '东财跌停池(历史日期, as-of 无降级)', () => board跌停(asof, top, true)],
    ['次新区间跌幅榜', 'as-of 不可得', NA_ASOF],
    ['板块榜', 'as-of 不可得', NA_ASOF],
  ] : [
    ['涨跌幅榜', '涨幅 Top' + top + '(竞价时段运行=竞价榜语义, 快照源不分时段)', () => board涨跌幅(top)],
    ['跌幅榜', '跌幅 Top' + top, () => board跌幅(top)],
    ['连板梯队', '东财涨停池按连板数织梯队(备: 财联社涨停池→电报解析)', () => board连板(date)],
    ['跌停榜', '东财跌停池(失败降级=跌幅榜近似并标注)', () => board跌停(date, top)],
    ['次新区间跌幅榜', 'BK0959 按60日涨跌幅升序', () => board次新(top)],
    ['板块榜', '行业涨跌Top8+概念涨幅Top8', () => board板块()],
  ];
  const mdParts = [asof
    ? `# 市场扫描(as-of 回放: 数据日=${asof} 收盘, 链日盘前视角; scan.mjs ${new Date().toTimeString().slice(0, 5)} 历史构建)`
    : `# 市场扫描(${date}, scan.mjs ${new Date().toTimeString().slice(0, 5)} 现场拉取)`,
    `> 采集层只采全; 哪层先行归 02 市况判定(9-28 立法)\n`];
  const health = asof ? () => {} : logHealth;  // as-of 不记实时源健康台账(历史口径不代表源当下状态)
  const jsonOut = {};
  let okCount = 0;
  for (const [name, note, fn] of jobs) {
    try {
      const r = await fn();
      mdParts.push(`## ${name}\n来源: ${r.src}${r.warn ? ' ⚠️' + r.warn : ''} | ${note}\n${r.md}`);
      jsonOut[name] = { src: r.src, warn: r.warn || null, raw: r.raw ?? r.md };
      okCount++;
      health('scan', name, r.src, true);                       // 10/7: 健康台账
      console.log(`[scan] ${name} OK (${r.src})`);
    } catch (e) {
      mdParts.push(`## ${name}\n[本榜获取失败: ${String(e.message || e).slice(0, 200)}]`);
      jsonOut[name] = { src: null, error: String(e.message || e).slice(0, 200) };
      health('scan', name, null, false, e.message || e);       // 10/7: 失败也记账
      console.log(`[scan] ${name} FAIL: ${String(e.message || e).slice(0, 100)}`);
    }
    await jitter();  // 榜间抖动, 防固定节拍
  }
  fs.mkdirSync(outDir, { recursive: true });

  // §5.5 对策(10/7): 全灭不再 exit 1(Java misfire=丢弃不重试, 链断)——降级续用最近历史产物+大标注, 链照跑
  if (!okCount && !asof) {  // as-of 禁降级续用他日产物(会混入实时数据)
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
