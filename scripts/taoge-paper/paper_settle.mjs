// paper_settle.mjs — 日结算(纯脚本, 无Claude): 断言成交bar → 记账 → equity → market_quote_daily
//
// 用法: node paper_settle.mjs --date 20260918
// 输入: paper_state.json + decisions/<date>/*.json + kline缓存(权威bar)
// 输出: equity.csv 追加; db_bound/market_quote_daily.jsonl; state.as_of 更新
// 口径: 成交价=决策bar的下一根m5 bar开盘价(此处重新断言), 与回测三件套一致。
import fs from 'fs';
import path from 'path';
import { spawnSync } from 'child_process';
import { fileURLToPath } from 'url';
import { dbRow, hole } from './dblog.mjs';
import { fetchM5 } from './quote.mjs';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const cfg = JSON.parse(fs.readFileSync(path.join(ROOT, 'config.json'), 'utf8'));

// ---- 告警与推送(闭环铁律: 结算失败也必须让用户知道, 不抛给上层Java/计划任务) ----
const hermes = (cfg.inbox || {}).hermes;
function hermesSend(subject, file) {
  if (!hermes) return false;
  try {
    const r = spawnSync(hermes, ['send', '--to', 'weixin', '-s', subject, '-f', file], { encoding: 'utf8', timeout: 60000, windowsHide: true });
    const out = ((r.stdout || '') + (r.stderr || '')).trim();
    if (r.status === 0 && !/rate limited|failed|error/i.test(out)) return true;
    hole('推送失败(限流?)', subject + ' ' + out.slice(0, 200));
  } catch (e) { hole('推送异常', subject + ' ' + e); }
  return false;
}
function alert(what, impact, action) {
  try {
    const dir = path.join(ROOT, 'alerts');
    fs.mkdirSync(dir, { recursive: true });
    const name = `alert_settle_${Date.now()}.txt`;
    fs.writeFileSync(path.join(dir, name), `【什么问题】${what}\n【导致什么】${impact}\n【该怎么做】${action}`);
    hole('结算告警', what);
    // 直发成功则记delivered防哨兵重投; 失败不管——15:06-15:10存活的哨兵processAlerts会收走重试
    if (hermesSend('结算告警', path.join(dir, name))) fs.appendFileSync(path.join(dir, 'delivered.log'), name + '\n');
  } catch {}
}
process.on('uncaughtException', e => {
  alert('结算脚本崩溃: ' + String(e).slice(0, 150), '今日 equity/market_quote_daily 没落盘, paper账目断一天', '看 alerts/ 与 holes.log 定位; 修复后手动重跑 node paper_settle.mjs --date <日期>');
  process.exit(1);
});
process.on('unhandledRejection', e => {
  alert('结算脚本异步失败: ' + String(e).slice(0, 150), '今日 equity/market_quote_daily 可能不完整', '看 alerts/ 与 holes.log 定位; 修复后手动重跑 node paper_settle.mjs --date <日期>');
  process.exit(1);
});
const KLINE_DIR = path.join(ROOT, '..', 'bilibili-taoge', 'downloads', 'kline');
const args = process.argv.slice(2);
// --date YYYYMMDD, 缺省=今天(任务计划程序 15:06 调用时不带参数)
let DATE = args.includes('--date') ? args[args.indexOf('--date') + 1] : null;
if (!DATE) {
  const d = new Date();
  DATE = String(d.getFullYear()) + String(d.getMonth() + 1).padStart(2, '0') + String(d.getDate()).padStart(2, '0');
}

const stateFile = path.join(ROOT, 'paper_state.json');
const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
const loadBars = c => JSON.parse(fs.readFileSync(path.join(KLINE_DIR, c + '_m5.json'), 'utf8')).bars;
// 量单位归一: 缓存bar用vol(股), mkline新抓用v(手) → 统一返回股
const shares = b => b.vol ?? (b.v || 0) * 100;
const barAmt = b => b.amount || shares(b) * b.c;

// 缓存缺当日bar时从 mkline 现拉并回写缓存(9/21坑: sentinel没落raw, 结算无米下锅)
async function ensureBars(c) {
  let bars = [];
  try { bars = loadBars(c); } catch {}
  if (bars.some(b => b.t.startsWith(DATE))) return bars;
  const m5 = await fetchM5(c, 320);   // [{t,o,h,l,c,v(手),amount}]
  const merged = [...bars];
  for (const b of m5) if (!merged.some(x => x.t === b.t)) merged.push({ t: b.t, o: b.o, h: b.h, l: b.l, c: b.c, vol: Math.round((b.v || 0) * 100), amount: b.amount });
  merged.sort((a, b) => a.t < b.t ? -1 : 1);
  fs.mkdirSync(KLINE_DIR, { recursive: true });
  fs.writeFileSync(path.join(KLINE_DIR, c + '_m5.json'), JSON.stringify({ code: c, bars: merged }));
  return merged;
}

// ---- 1. 校验当日所有 auto_exec 决策的成交价 = 下一根bar开盘价(防漂移断言) ----
const decDir = path.join(ROOT, 'decisions', DATE);
const fills = [];
if (fs.existsSync(decDir)) {
  for (const f of fs.readdirSync(decDir).filter(f => f.endsWith('.json'))) {
    const d = JSON.parse(fs.readFileSync(path.join(decDir, f), 'utf8'));
    if (d.verdict !== 'auto_exec') continue;
    const bars = await ensureBars(d.code);
    const i = bars.findIndex(b => b.t === d.info_cutoff);
    const next = bars[i + 1];
    if (!next) { hole('结算: 无下一根bar', f); continue; }
    fills.push({ ...d, fill_px: next.o, fill_bar: next.t });
  }
}
console.log(`结算 ${DATE}: ${fills.length} 笔 auto_exec 成交已断言 (fill=下一根bar开盘价)`);

// ---- 2. 逐日行情入 db_bound(market_quote_daily, m5聚合为日线) ----
const wlFile = path.join(ROOT, 'watchlist', DATE + '.json');
const codes = new Set(['sh000001']);
if (fs.existsSync(wlFile)) JSON.parse(fs.readFileSync(wlFile, 'utf8')).items.forEach(i => codes.add(i.code));
for (const p of state.positions) codes.add(p.code);
for (const c of codes) {
  try {
    const all = await ensureBars(c);
    const dayBars = all.filter(b => b.t.startsWith(DATE));
    if (!dayBars.length) { hole('结算: 无当日bar', c); continue; }
    const o = dayBars[0].o, cl = dayBars[dayBars.length - 1].c;
    const prev = all.filter(b => b.t < DATE + '0000');
    const prevClose = prev.length ? prev[prev.length - 1].c : null;
    dbRow('market_quote_daily', {
      trade_date: `${DATE.slice(0, 4)}-${DATE.slice(4, 6)}-${DATE.slice(6, 8)}`,
      stock_code: c, open: o, high: Math.max(...dayBars.map(b => b.h)),
      low: Math.min(...dayBars.map(b => b.l)), close: cl,
      volume: dayBars.reduce((s, b) => s + shares(b), 0),
      amount: dayBars.reduce((s, b) => s + barAmt(b), 0),
      pct_chg: prevClose ? +((cl / prevClose - 1) * 100).toFixed(2) : null,
      source: 'tencent_m5_agg',
    });
  } catch (e) { hole('结算: 读kline失败', c + ' ' + e); }
}

// ---- 3. 净值: 现金 + 持仓按当日收盘 ----
let mv = 0;
for (const p of state.positions) {
  const dayBars = (await ensureBars(p.code)).filter(b => b.t.startsWith(DATE));
  if (dayBars.length) mv += dayBars[dayBars.length - 1].c * p.qty;
  else hole('结算: 持仓无收盘价', p.code);
}
const nav = +(state.cash + mv).toFixed(2);
const shBars = (await ensureBars('sh000001')).filter(b => b.t.startsWith(DATE));
const equityFile = path.join(ROOT, 'equity.csv');
const hadRow = fs.existsSync(equityFile) && fs.readFileSync(equityFile, 'utf8').split('\n').some(l => l.startsWith(DATE + ','));
if (!fs.existsSync(equityFile)) fs.writeFileSync(equityFile, 'date,cash,market_value,total_nav,return_pct,sh_close\n');
fs.appendFileSync(equityFile, [DATE, state.cash.toFixed(2), mv.toFixed(2), nav,
  ((nav / state.nav_start - 1) * 100).toFixed(2), shBars.length ? shBars[shBars.length - 1].c : ''].join(',') + '\n');

state.as_of = DATE;
fs.writeFileSync(stateFile, JSON.stringify(state, null, 1));
console.log(`NAV ${nav} (${((nav / state.nav_start - 1) * 100).toFixed(2)}%)  cash=${state.cash.toFixed(2)} mv=${mv.toFixed(2)} 持仓=${state.positions.map(p => p.name + '×' + p.qty).join(',') || '无'}`);

// ---- 4. 结算摘要推送(每日≤1条: 用户不看电脑也知道账; 重跑/非交易日不推) ----
if (!hadRow && shBars.length) {
  const dir = path.join(ROOT, 'push');
  fs.mkdirSync(dir, { recursive: true });
  const f = path.join(dir, `settle_${DATE}.txt`);
  fs.writeFileSync(f,
    `paper结算 ${DATE}: NAV ${nav} (${((nav / state.nav_start - 1) * 100).toFixed(2)}%), 现金${state.cash.toFixed(2)}, ` +
    `持仓${state.positions.map(p => p.name + '×' + p.qty).join(',') || '无'}, 成交${fills.length}笔, 上证收${shBars[shBars.length - 1].c}`);
  hermesSend('paper结算', f);
}
