// sim.mjs — 盘中机械执行器(只做这一件事: watchlist 条件扫描 + 三档撤退 + 成交断言)
//
// 立法口径:
//   ① 成交 = 触发 bar 的下一根 bar 开盘价(与 pilot-2week / taoge-paper 完全一致)
//   ② 可成交性过滤: 涨停买不进 / 跌停卖不出 / 一字板(o=h=l=c 且封板)不许编造成交 → 记洞跳过
//   ③ A股 T+1: 当日买入的股数当日不可卖
//   ④ 费用: 买万2.5 / 卖万7.5(用户确认口径, 含印花税)
//   ⑤ 退出 = 机械三档模板(LLM 不编造"桃哥式止损", 语料缺失):
//      反弹撤(冲高回落: 浮盈≥+2.5% 后从日内高点回撤≥1.5%) / 止损撤(成本-6%) / 尾盘兜底(14:30-14:57 清仓)
//   ⑥ 日线粒度退化(2025-10~2026-01 的 T): 无盘中结构, 三档撤退只能用收盘确认→次日开盘价成交,
//      这是数据窗口硬约束下的保守近似, 在报告里显式标注, 不粉饰。
// 条件词汇与 sentinel.mjs 对齐(触发引擎语义复刻, 不 import 以保持回测独立可跑)。
import { shares, barAmt, limitUpPx, limitDownPx } from './kline.mjs';

export const FEE_B = 0.00025, FEE_S = 0.00075;
const hhmm = t => t.slice(8, 10) + ':' + t.slice(10, 12);
const dayOf = t => t.slice(0, 8);

// ---------- 条件判定 ----------
// ctx: {price, prevClose, dayAmount, nowBar, barsToday, indexPct, histBySlot}
export function condOk(c, ctx) {
  switch (c.type) {
    case 'time_window': { const t = hhmm(ctx.nowBar.t); return t >= c.from && t <= c.to; }
    case 'open': return ctx.barIndexToday === 0;                     // 开盘触发: 当日第一根 bar 收盘后
    case 'price_above': return ctx.price != null && ctx.price > c.value;
    case 'price_below': return ctx.price != null && ctx.price < c.value;
    case 'pct_above': return ctx.prevClose && ctx.price != null && (ctx.price / ctx.prevClose - 1) * 100 > c.value;
    case 'pct_below': return ctx.prevClose && ctx.price != null && (ctx.price / ctx.prevClose - 1) * 100 < c.value;
    case 'amount_gt': return ctx.dayAmount > c.value;
    case 'index_pct_below': return ctx.indexPct != null && ctx.indexPct < c.value;
    case 'index_pct_above': return ctx.indexPct != null && ctx.indexPct > c.value;
    case 'vol_ratio_gt': {
      const avg = ctx.histBySlot?.[ctx.nowBar.t.slice(8)];
      return avg && shares(ctx.nowBar) > avg * c.value;
    }
    case 'no_new_low_n': {   // 企稳: 最近 n 根 bar 不再创新低(低吸类规则的机械判据)
      const n = c.bars || 3, bt = ctx.barsToday;
      if (bt.length < n + 1) return false;
      const recent = bt.slice(-n), before = bt[bt.length - n - 1];
      return recent.every(b => b.l >= before.l);
    }
    default: return false;   // 未知条件=不触发 + 调用方记洞
  }
}

// ---------- 三档撤退模板(机械, 所有组共用; A组在他自述卖出之外也用它兜底) ----------
export function exitTemplates(pos, date) {
  const stop = +(pos.cost * 0.94).toFixed(2);
  return [
    { id: `exit-rebound-${pos.code}-${date}`, strategy: 'mech-exit', code: pos.code, name: pos.name,
      side: 'sell', valid_date: date, is_exit: true,
      conditions: [{ type: 'time_window', from: '09:31', to: '14:30' }, { type: 'pullback_from_high', pct_from_cost: 2.5, dd: 1.5 }],
      action: { type: 'sell', qty: pos.qty, note: '反弹撤: 浮盈≥2.5%后冲高回落(自日高回撤1.5%), 守利润' },
      source: '机械三档撤退模板' },
    { id: `exit-stop-${pos.code}-${date}`, strategy: 'mech-exit', code: pos.code, name: pos.name,
      side: 'sell', valid_date: date, is_exit: true,
      conditions: [{ type: 'price_below', value: stop }],
      action: { type: 'sell', qty: pos.qty, note: `止损撤: 破成本-6%(${stop})` },
      source: '机械三档撤退模板' },
    { id: `exit-eod-${pos.code}-${date}`, strategy: 'mech-exit', code: pos.code, name: pos.name,
      side: 'sell', valid_date: date, is_exit: true,
      conditions: [{ type: 'time_window', from: '14:50', to: '14:57' }],
      action: { type: 'sell', qty: pos.qty, note: '尾盘兜底: 不留仓过夜(回测口径, 偏保守)' },
      source: '机械三档撤退模板' },
  ];
}

// 冲高回落条件单独实现(需要日内高点记忆, 不属于无状态 condOk)
function pullbackOk(c, ctx, pos) {
  if (!pos) return false;
  const hi = Math.max(...ctx.barsToday.map(b => b.h));
  const pctCost = (hi / pos.cost - 1) * 100;
  const dd = (ctx.price / hi - 1) * 100;
  return pctCost >= c.pct_from_cost && dd <= -c.dd;
}

// ---------- 成交(含可成交性过滤) ----------
function tryFill(item, nextBar, pos, ctx, state, hole, log) {
  const px = nextBar.o;
  const oneWay = nextBar.o === nextBar.h && nextBar.h === nextBar.l && nextBar.l === nextBar.c;   // 一字板
  if (item.action.type === 'buy') {
    const limitUp = ctx.prevClose ? limitUpPx(ctx.prevClose, item.code, item.name) : null;
    if (oneWay && limitUp && px >= limitUp) { hole('一字涨停买不进', `${item.id}@${nextBar.t} px=${px}`); return null; }
    if (limitUp && px >= limitUp) { hole('涨停价买不进', `${item.id}@${nextBar.t} px=${px} limit=${limitUp}`); return null; }
    // 仓位: 单票上限 max_amt(默认2.5万 ≈ pilot 的 2.5 成); qty 取整百股
    const maxAmt = item.action.max_amt || 25000;
    let qty = item.action.qty || Math.floor(maxAmt / px / 100) * 100;
    qty = Math.min(qty, Math.floor(state.cash / (px * (1 + FEE_B)) / 100) * 100);
    if (qty <= 0) { hole('资金不足或不足一手', item.id); return null; }
    const amt = px * qty, fee = +(amt * FEE_B).toFixed(2);
    state.cash -= amt + fee;
    // buy_date 取成交 bar 的日期而非触发日: 日线粒度下触发=T收盘、成交=T+1开盘, T+1 判定必须按真实成交日
    const p = { code: item.code, name: item.name, qty, cost: px, feeB: fee, buy_date: nextBar.t.slice(0, 8), buy_bar: nextBar.t, trigger_id: item.id };
    state.positions.push(p);
    return { side: 'buy', px, qty, fee, pos: p };
  }
  if (item.action.type === 'sell' && pos) {
    const limitDown = ctx.prevClose ? limitDownPx(ctx.prevClose, item.code, item.name) : null;
    if (oneWay && limitDown && px <= limitDown) { hole('一字跌停卖不出', `${item.id}@${nextBar.t} px=${px}`); return null; }
    if (limitDown && px <= limitDown) { hole('跌停价卖不出', `${item.id}@${nextBar.t} px=${px} limit=${limitDown}`); return null; }
    // T+1: 只能卖 buy_date < 今日的股数
    const sellable = pos.buy_date < ctx.date ? pos.qty : 0;
    const qty = Math.min(item.action.qty || pos.qty, sellable);
    if (qty <= 0) { hole('T+1当日买入不可卖', item.id + '@' + nextBar.t); return null; }
    const amt = px * qty, fee = +(amt * FEE_S).toFixed(2);
    state.cash += amt - fee;
    pos.qty -= qty;
    if (pos.qty <= 0) state.positions = state.positions.filter(p => p !== pos);
    return { side: 'sell', px, qty, fee };
  }
  return null;
}

// ---------- 单日回放 ----------
// items: 当日 watchlist(预案 + 持仓三档撤退由本函数自动附加)
// barsByCode: {code: 全量bars(含历史, 已按t排序)}; indexBars: sh000001 同粒度全量
// 返回当日 fills 数组; state 就地更新
export function simulateDay({ date, items, state, barsByCode, indexBars, hole, log }) {
  const fills = [];
  const dayBarsOf = c => (barsByCode[c] || []).filter(b => dayOf(b.t) === date);
  const prevCloseOf = (bars) => {
    const prev = (bars || []).filter(b => dayOf(b.t) < date);
    return prev.length ? prev[prev.length - 1].c : null;
  };
  const idxDay = dayBarsOf('sh000001').length ? barsByCode['sh000001'] : indexBars;
  const idxPrevClose = prevCloseOf(idxDay);
  // 时间轴 = 全部相关票当日 bar 的并集(逐 bar 推进 = 不知道右半边)
  const codes = [...new Set(items.map(i => i.code).concat(state.positions.map(p => p.code)))];
  const timeline = [...new Set(codes.flatMap(c => dayBarsOf(c).map(b => b.t)))].sort();
  // 前5日同序 bar 均量(vol_ratio 用; 日线粒度无同序概念, histBySlot 为空 → vol_ratio 条件自动失效)
  const histSlotAvg = {};
  for (const c of codes) {
    const slots = {};
    for (const b of (barsByCode[c] || [])) {
      if (dayOf(b.t) >= date) continue;
      (slots[b.t.slice(8)] ||= []).push(shares(b));
    }
    histSlotAvg[c] = {};
    for (const [slot, vs] of Object.entries(slots)) {
      const last5 = vs.slice(-5);
      histSlotAvg[c][slot] = last5.reduce((s, v) => s + v, 0) / last5.length;
    }
  }
  // 持仓自动挂三档撤退(与预案 items 同引擎扫描)
  let pending = [...items];
  for (const pos of state.positions) pending.push(...exitTemplates(pos, date));
  const fired = new Set();

  for (const t of timeline) {
    for (const item of pending) {
      if (fired.has(item.id) || item.valid_date !== date) continue;
      const bars = barsByCode[item.code] || [];
      const i = bars.findIndex(b => b.t === t);
      if (i < 0) continue;
      const barsToday = bars.filter(b => dayOf(b.t) === date && b.t <= t);
      const nowBar = bars[i];
      const pos = state.positions.find(p => p.code === item.code);
      const idxNow = (idxDay || []).filter(b => dayOf(b.t) === date && b.t <= t);
      const ctx = {
        date, nowBar, price: nowBar.c, prevClose: prevCloseOf(bars),
        barsToday, barIndexToday: barsToday.length - 1,
        dayAmount: barsToday.reduce((s, b) => s + barAmt(b), 0),
        histBySlot: histSlotAvg[item.code],
        indexPct: idxPrevClose && idxNow.length ? (idxNow[idxNow.length - 1].c / idxPrevClose - 1) * 100 : null,
      };
      const ok = item.conditions.every(c =>
        c.type === 'pullback_from_high' ? pullbackOk(c, ctx, pos) : condOk(c, ctx));
      if (!ok) continue;
      const next = bars[i + 1];
      if (!next) { hole('无下一根bar无法成交', item.id + '@' + t); fired.add(item.id); continue; }
      const fill = tryFill(item, next, pos, ctx, state, hole, log);
      fills.push({
        id: item.id, code: item.code, name: item.name, side: item.action.type,
        trigger_bar: t, fill_bar: next.t, verdict: fill ? 'filled' : 'rejected',
        px: fill?.px ?? null, qty: fill?.qty ?? null, fee: fill?.fee ?? null,
        note: item.action.note, source: item.source,
      });
      fired.add(item.id);   // 一次性触发(触发即离场的 exit 或一次性买入)
      if (fill) log?.(`${fill.side.toUpperCase()} ${item.name} ${fill.qty}@${fill.px} fee=${fill.fee} (${item.id})`);
    }
    // 盘中持仓变化后补齐新仓位的三档撤退(当日买入的 exit 明天才挂, T+1 本就卖不了)
    pending = pending.filter(x => !fired.has(x.id));
  }
  // 日线粒度退化说明: timeline 只有一根 bar 时, open 触发=当日收盘后确认, 成交=次日开盘价 ——
  // 由调用方在连续日循环里保证"次日 bar"存在(跨天成交在 runDays 里处理)。
  return fills;
}
