// settle_k3_v01.mjs — k3-inv v0.1 回测结算 (2026-09-01 → 2026-09-18)
//
// 口径与桃哥 pilot-2week 完全一致:
//   - 决策/提醒时刻 → 下一根 m5 bar 开盘价成交(脚本内断言 bar 真实存在且价格一致, 防手抖)
//   - 费用: 买入佣金万2.5, 卖出佣金万2.5+印花税0.05% (FEE_S=0.00075)
//   - 起始资金 100,475.40 (= 用户真实东财总资产, 与桃哥回测同口径)
//   - 持仓股按每日收盘价 mark-to-market 进 equity.csv; 期末未平仓保留为市值
// 决策本身(买/卖/不买)已在 walk-forward 裁决中完成, 本脚本只做结算与校验, 不改任何决策。
//
// 用法: node settle_k3_v01.mjs   (在 scripts/k3-inv/backtest/ 下运行)
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));

const KLINE_DIR = path.join(__dirname, '..', '..', 'bilibili-taoge', 'downloads', 'kline');
const OUT_DIR = path.join(__dirname, 'runs', 'k3-v0.1-20260901_0918');
const FEE_B = 0.00025, FEE_S = 0.00075;
const START = 100475.40;

// ---- walk-forward 裁决产物(冻结, 每条带信息可用性依据) ----
const DECISIONS = [
  { action: 'buy', date: '20260901', time: '1350', code: 'sh601988', name: '中国银行', qty: 1500,
    reason: '9/01 13:46电报:银行股持续走高+净息差企稳报道(sector_move); 李大霄筛通过(国有大行龙头/业绩/非题材); 威科夫=吸筹末端慢牛, 决策时涨幅<5%不违追高线; 防御配置仓1成' },
  { action: 'buy', date: '20260907', time: '1000', code: 'sh688008', name: '澜起科技', qty: 100,
    reason: '9/04晚隔夜催化(闪迪+5.4%/美光HBM需求翻倍, overnight映射存储); 9/07 0945低点192.76不破+0955放量回升=SOS回踩确认; 李大霄筛通过(内存接口全球龙头); 约1.9成仓' },
  { action: 'sell', date: '20260911', time: '0935', code: 'sh688008', name: '澜起科技', qty: 100,
    reason: '9/10晚反向催化(英伟达被市监总局调查+SK海力士-4%+美PPI超预期), 半导体链承压→规则§4反向催化无条件走; 09:31决策, 0935 bar成交' },
];
const MARK_END = { code: 'sh601988', date: '20260918' };  // 期末未平仓, 按收盘价估值

// ---- kline 加载 ----
function load(code) {
  return JSON.parse(fs.readFileSync(path.join(KLINE_DIR, code + '_m5.json'), 'utf8')).bars;
}
const barsOf = {};
for (const c of ['sh601988', 'sh688008', 'sh000001']) barsOf[c] = load(c);

function barAt(code, date, time) {
  const key = date + time;
  return barsOf[code].find(b => b.t === key);
}
function dailyCloses(code) {
  const m = {};
  for (const b of barsOf[code]) m[b.t.slice(0, 8)] = b.c;
  return m;
}

// ---- 执行(带 bar 断言) ----
let cash = START;
const pos = {};   // code -> {name, qty, cost}
const trades = []; // 已完成+未平仓
const open = {};  // code -> trade 记录

function buy(d) {
  const bar = barAt(d.code, d.date, d.time);
  if (!bar) throw new Error('买入bar不存在: ' + d.code + ' ' + d.date + d.time);
  const px = bar.o;
  const amt = px * d.qty, fee = +(amt * FEE_B).toFixed(2);
  cash -= (amt + fee);
  const tr = { bd: d.date, bt: d.time, code: d.code, name: d.name, qty: d.qty, bp: px, feeB: fee, reason: d.reason };
  open[d.code] = tr;
  console.log('BUY ', d.date, d.time, d.code, d.name, d.qty + '@' + px, 'fee=' + fee, 'cash=' + cash.toFixed(2));
}
function sell(d) {
  const bar = barAt(d.code, d.date, d.time);
  if (!bar) throw new Error('卖出bar不存在: ' + d.code + ' ' + d.date + d.time);
  const tr = open[d.code];
  if (!tr || tr.qty !== d.qty) throw new Error('持仓不匹配: ' + d.code);
  const px = bar.o;
  const amt = px * d.qty, fee = +(amt * FEE_S).toFixed(2);
  cash += (amt - fee);
  tr.sd = d.date; tr.st = d.time; tr.sp = px; tr.feeS = fee;
  tr.pnl = +((amt - fee) - (tr.bp * tr.qty + tr.feeB)).toFixed(2);
  tr.pct = +(tr.pnl / (tr.bp * tr.qty + tr.feeB) * 100).toFixed(2);
  tr.sellReason = d.reason;
  trades.push(tr);
  delete open[d.code];
  console.log('SELL', d.date, d.time, d.code, d.name, d.qty + '@' + px, 'fee=' + fee, 'pnl=' + tr.pnl, 'cash=' + cash.toFixed(2));
}

for (const d of DECISIONS) (d.action === 'buy' ? buy : sell)(d);

// ---- 每日净值 ----
const dates = [...new Set(barsOf['sh000001'].map(b => b.t.slice(0, 8)))].sort();
const closes = { sh601988: dailyCloses('sh601988'), sh688008: dailyCloses('sh688008'), sh000001: dailyCloses('sh000001') };
const equity = [];
// 逐日重放现金变化
let cashFlow = START;
const flowByDate = {};
{
  let c = START;
  for (const d of DECISIONS) {
    const bar = barAt(d.code, d.date, d.time);
    const amt = bar.o * d.qty;
    c += d.action === 'buy' ? -(amt + +(amt * FEE_B).toFixed(2)) : (amt - +(amt * FEE_S).toFixed(2));
    flowByDate[d.date] = c;
  }
}
for (const date of dates) {
  if (flowByDate[date] !== undefined) cashFlow = flowByDate[date];
  // 当日收盘持仓: 已买未卖
  let mv = 0;
  for (const d of DECISIONS) {
    if (d.action !== 'buy') continue;
    const sold = trades.find(t => t.code === d.code && t.bd === d.date);
    const sellD = sold ? sold.sd : null;
    if (d.date <= date && (!sellD || date < sellD)) {
      const close = closes[d.code][date];
      if (close !== undefined) mv += close * d.qty;
    }
  }
  mv = +mv.toFixed(2);
  const nav = +(cashFlow + mv).toFixed(2);
  equity.push({ date, cash: +cashFlow.toFixed(2), market_value: mv, total_nav: nav,
    return_pct: +((nav / START - 1) * 100).toFixed(2), sh_close: closes['sh000001'][date] });
}

// ---- 未平仓期末估值 ----
const markClose = closes[MARK_END.code][MARK_END.date];
for (const code in open) {
  const tr = open[code];
  tr.open_mark = { date: MARK_END.date, close: markClose, mv: +(markClose * tr.qty).toFixed(2),
    unrealized: +(markClose * tr.qty - (tr.bp * tr.qty + tr.feeB)).toFixed(2) };
  trades.push(tr);
}

// ---- 汇总 ----
const endNav = equity[equity.length - 1].total_nav;
let peak = -1e18, maxDD = 0;
for (const e of equity) { peak = Math.max(peak, e.total_nav); maxDD = Math.min(maxDD, e.total_nav / peak - 1); }
const benchBase = closes['sh000001'][dates[0]], benchEnd = closes['sh000001'][dates[dates.length - 1]];
const benchPct = +((benchEnd / benchBase - 1) * 100).toFixed(2);
const closed = trades.filter(t => t.sp !== undefined);

const settlement = {
  meta: {
    strategy: 'k3-inv v0.1', run: 'k3-v0.1-20260901_0918', run_type: 'backtest',
    window: dates[0] + '→' + dates[dates.length - 1], trading_days: dates.length,
    start_capital: START, fee_buy: FEE_B, fee_sell: FEE_S,
    fill_rule: '决策时刻下一根m5 bar开盘价(脚本断言bar存在)',
    benchmark: '上证指数 sh000001 收盘 ' + benchBase + '→' + benchEnd,
    honesty: '策略规格STRATEGY.md回测前冻结; 电报仅取时间戳≤决策时刻; 9/10与9/16盘中电报缺失按无电报日处理(数据洞诚实标注)',
  },
  result: {
    end_nav: endNav, total_return_pct: +((endNav / START - 1) * 100).toFixed(2),
    benchmark_return_pct: benchPct, excess_pct: +((endNav / START - 1) * 100 - benchPct).toFixed(2),
    max_drawdown_pct: +(maxDD * 100).toFixed(2),
    closed_trades: closed.length, closed_wins: closed.filter(t => t.pnl > 0).length,
    open_positions: Object.keys(open).length,
  },
  trades, equity,
};

fs.mkdirSync(OUT_DIR, { recursive: true });
fs.writeFileSync(path.join(OUT_DIR, 'settlement.json'), JSON.stringify(settlement, null, 1));

// trades.csv
const tHead = 'buy_date,buy_time,sell_date,sell_time,code,name,qty,buy_px,sell_px,pnl_yuan,pnl_pct,reason';
const tRows = trades.map(t => [t.bd, t.bt, t.sd || '(持仓中)', t.st || '', t.code, t.name, t.qty, t.bp,
  t.sp !== undefined ? t.sp : '(期末收盘' + markClose + '估值)',
  t.pnl !== undefined ? t.pnl : t.open_mark.unrealized,
  t.pct !== undefined ? t.pct : +(t.open_mark.unrealized / (t.bp * t.qty + t.feeB) * 100).toFixed(2),
  '"' + t.reason + (t.sellReason ? ' / 卖:' + t.sellReason : '') + '"'].join(','));
fs.writeFileSync(path.join(OUT_DIR, 'trades.csv'), tHead + '\n' + tRows.join('\n') + '\n');

// equity.csv
const eHead = 'date,cash,market_value,total_nav,return_pct,sh_close';
fs.writeFileSync(path.join(OUT_DIR, 'equity.csv'),
  eHead + '\n' + equity.map(e => [e.date, e.cash, e.market_value, e.total_nav, e.return_pct, e.sh_close].join(',')).join('\n') + '\n');

console.log('\n== k3-inv v0.1 结算 ==');
console.log('期末NAV:', endNav, '(' + settlement.result.total_return_pct + '%)  上证:', benchPct + '%', ' 超额:', settlement.result.excess_pct + 'pct');
console.log('最大回撤:', settlement.result.max_drawdown_pct + '%', ' 已平仓:', closed.length, '笔 胜:', closed.filter(t => t.pnl > 0).length, ' 未平仓:', Object.keys(open).length);
console.log('输出:', OUT_DIR);
