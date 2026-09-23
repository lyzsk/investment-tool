// settle_k3_v02.mjs — k3-inv v0.2 回测结算 (2026-09-01 → 2026-09-18)
//
// 与 v0.1 的唯一差异 = 决策集不同(v0.2 规格 scripts/k3-inv/STRATEGY.md):
//   - 09/01 中国银行买入被【板块顶背离否决】(中证银行 7562 vs 7/30 前峰 7517 价格新高,
//     DIF 100.12→74.29 / RSI 70.5→65.8 未新高 → §2 禁止开新仓)
//   - 09/14 银行背离虽修复(DIF 100.22≈前峰), 但 regime 转防守(涨停高度 7→4 递减) → 不开新仓
//   - 09/16 澜起再入被否: 防守 regime + 当日主线=半导体设备(摩根大通SPE报告)非存储,
//     个股挂不上主线 + 9/16 电报数据洞无存储催化可得
//   - 09/03 中远海能竞价观察窗: 历史竞价数据不可得, 规则不可执行(进 paper 验证清单)
// 结算口径与 settle_k3_v01.mjs / 桃哥 pilot-2week 完全一致。
//
// 用法: node settle_k3_v02.mjs   (在 scripts/k3-inv/backtest/ 下运行)
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));

const KLINE_DIR = path.join(__dirname, '..', '..', 'bilibili-taoge', 'downloads', 'kline');
const OUT_DIR = path.join(__dirname, 'runs', 'k3-v0.2-20260901_0918');
const FEE_B = 0.00025, FEE_S = 0.00075;
const START = 100475.40;

// ---- walk-forward 裁决产物(v0.2 规则, 冻结) ----
const DECISIONS = [
  { action: 'buy', date: '20260907', time: '1000', code: 'sh688008', name: '澜起科技', qty: 100,
    reason: 'regime中性(高度5-6板); 存储=隔夜映射主线(9/04晚闪迪+5.4%/美光HBM翻倍, A股存储9/04跌-1.2%未透支); 9/07 0945低点192.76不破+0955放量回升=SOS回踩确认; 李大霄筛通过; 买入价194.87非60日新高, 顶背离否决不适用; 约1.9成仓' },
  { action: 'sell', date: '20260911', time: '0935', code: 'sh688008', name: '澜起科技', qty: 100,
    reason: '9/10晚反向催化(英伟达被市监总局调查+SK海力士-4%+美PPI超预期)→§5反向催化无条件走; 09:31决策, 0935 bar成交' },
];
const VETOES = [
  { date: '20260901', target: '中国银行 sh601988', rule: '§2 板块顶背离否决 + 主线不成立(单次报道)',
    detail: '中证银行7562 vs 7/30前峰7517价格新高, DIF 100.12→74.29/RSI 70.5→65.8未新高→禁止开新仓; v0.1在此买入浮亏-1.97%, v0.2规避' },
  { date: '20260914', target: '中国银行 sh601988', rule: '§1 防守regime不开新仓',
    detail: '板块DIF修复至100.22≈前峰, 但涨停高度7→4递减=退潮, 且个股无威科夫入场结构(9/15-9/18连阴)' },
  { date: '20260916', target: '澜起科技 sh688008', rule: '§1防守 + §2主线不符 + §0数据洞',
    detail: '当日主线=半导体设备(摩根大通SPE报告, 涨停票均设备/材料小票), 澜起属设计/接口挂不上; 存储当日无可得催化(9/16盘中电报缺失); 高度4板=防守' },
  { date: '20260903', target: '中远海能 sh600026', rule: '§4 竞价观察窗(不可执行)',
    detail: '报道即涨停类机会需次日竞价数据, 历史竞价不可得 → 规则进paper验证清单, 本轮回测不执行' },
];

const barsOf = {};
for (const c of ['sh688008', 'sh000001']) barsOf[c] = JSON.parse(fs.readFileSync(path.join(KLINE_DIR, c + '_m5.json'), 'utf8')).bars;
function barAt(code, date, time) { return barsOf[code].find(b => b.t === date + time); }
function dailyCloses(code) { const m = {}; for (const b of barsOf[code]) m[b.t.slice(0, 8)] = b.c; return m; }

let cash = START;
const trades = [], open = {};
function buy(d) {
  const bar = barAt(d.code, d.date, d.time);
  if (!bar) throw new Error('买入bar不存在: ' + d.code + d.date + d.time);
  const amt = bar.o * d.qty, fee = +(amt * FEE_B).toFixed(2);
  cash -= (amt + fee);
  open[d.code] = { bd: d.date, bt: d.time, code: d.code, name: d.name, qty: d.qty, bp: bar.o, feeB: fee, reason: d.reason };
  console.log('BUY ', d.date, d.time, d.code, d.name, d.qty + '@' + bar.o, 'fee=' + fee, 'cash=' + cash.toFixed(2));
}
function sell(d) {
  const bar = barAt(d.code, d.date, d.time);
  if (!bar) throw new Error('卖出bar不存在: ' + d.code + d.date + d.time);
  const tr = open[d.code];
  if (!tr || tr.qty !== d.qty) throw new Error('持仓不匹配: ' + d.code);
  const amt = bar.o * d.qty, fee = +(amt * FEE_S).toFixed(2);
  cash += (amt - fee);
  tr.sd = d.date; tr.st = d.time; tr.sp = bar.o; tr.feeS = fee;
  tr.pnl = +((amt - fee) - (tr.bp * tr.qty + tr.feeB)).toFixed(2);
  tr.pct = +(tr.pnl / (tr.bp * tr.qty + tr.feeB) * 100).toFixed(2);
  tr.sellReason = d.reason;
  trades.push(tr); delete open[d.code];
  console.log('SELL', d.date, d.time, d.code, d.name, d.qty + '@' + bar.o, 'fee=' + fee, 'pnl=' + tr.pnl, 'cash=' + cash.toFixed(2));
}
for (const d of DECISIONS) (d.action === 'buy' ? buy : sell)(d);

const dates = [...new Set(barsOf['sh000001'].map(b => b.t.slice(0, 8)))].sort();
const closes = { sh688008: dailyCloses('sh688008'), sh000001: dailyCloses('sh000001') };
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
const equity = [];
let cashFlow = START;
for (const date of dates) {
  if (flowByDate[date] !== undefined) cashFlow = flowByDate[date];
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

const endNav = equity[equity.length - 1].total_nav;
let peak = -1e18, maxDD = 0;
for (const e of equity) { peak = Math.max(peak, e.total_nav); maxDD = Math.min(maxDD, e.total_nav / peak - 1); }
const benchBase = closes['sh000001'][dates[0]], benchEnd = closes['sh000001'][dates[dates.length - 1]];
const benchPct = +((benchEnd / benchBase - 1) * 100).toFixed(2);

const settlement = {
  meta: {
    strategy: 'k3-inv v0.2', run: 'k3-v0.2-20260901_0918', run_type: 'backtest',
    window: dates[0] + '→' + dates[dates.length - 1], trading_days: dates.length,
    start_capital: START, fee_buy: FEE_B, fee_sell: FEE_S,
    fill_rule: '决策时刻下一根m5 bar开盘价(脚本断言bar存在)',
    benchmark: '上证指数 sh000001 收盘 ' + benchBase + '→' + benchEnd,
    v02_changes: '新增大盘预判层/板块主线层/顶背离否决/竞价观察窗(不可执行)/隔夜映射加权; rules.md 除名',
    honesty: '规格STRATEGY.md v0.2执行前冻结; 电报仅取时间戳≤决策时刻; 9/10与9/16盘中电报缺失按无电报日处理; 否决记录见vetoes',
  },
  result: {
    end_nav: endNav, total_return_pct: +((endNav / START - 1) * 100).toFixed(2),
    benchmark_return_pct: benchPct, excess_pct: +((endNav / START - 1) * 100 - benchPct).toFixed(2),
    max_drawdown_pct: +(maxDD * 100).toFixed(2),
    closed_trades: trades.length, closed_wins: trades.filter(t => t.pnl > 0).length,
    vetoes: VETOES.length,
  },
  vetoes: VETOES, trades, equity,
};

fs.mkdirSync(OUT_DIR, { recursive: true });
fs.writeFileSync(path.join(OUT_DIR, 'settlement.json'), JSON.stringify(settlement, null, 1));

const tHead = 'buy_date,buy_time,sell_date,sell_time,code,name,qty,buy_px,sell_px,pnl_yuan,pnl_pct,reason';
const tRows = trades.map(t => [t.bd, t.bt, t.sd, t.st, t.code, t.name, t.qty, t.bp, t.sp, t.pnl, t.pct,
  '"' + t.reason + ' / 卖:' + t.sellReason + '"'].join(','));
fs.writeFileSync(path.join(OUT_DIR, 'trades.csv'), tHead + '\n' + tRows.join('\n') + '\n');

const eHead = 'date,cash,market_value,total_nav,return_pct,sh_close';
fs.writeFileSync(path.join(OUT_DIR, 'equity.csv'),
  eHead + '\n' + equity.map(e => [e.date, e.cash, e.market_value, e.total_nav, e.return_pct, e.sh_close].join(',')).join('\n') + '\n');

console.log('\n== k3-inv v0.2 结算 ==');
console.log('期末NAV:', endNav, '(' + settlement.result.total_return_pct + '%)  上证:', benchPct + '%', ' 超额:', settlement.result.excess_pct + 'pct');
console.log('最大回撤:', settlement.result.max_drawdown_pct + '%', ' 交易:', trades.length, '笔 否决:', VETOES.length, '次');
console.log('对照v0.1: -0.70% → v0.2:', settlement.result.total_return_pct + '%');
console.log('输出:', OUT_DIR);
