// settle.mjs — 记账与产出(只做这一件事: equity曲线 / trades.csv / report.md)
//
// 口径: 费用买万2.5/卖万7.5(sim 内已逐笔扣); 持仓按当日最后一根 bar 收盘价估值;
// 产出对齐 pilot-2week 三件套(equity.csv / trades.csv / report.md) + decisions/ + hashchain.log。
import fs from 'fs';
import path from 'path';

const dayOf = t => t.slice(0, 8);

// CSV 写 UTF-8 BOM: 无 BOM 时中文 Windows 的 Excel 按 GBK 读 → 全列乱码(9/27 用户踩坑)
const BOM = '﻿';

// 文件写重试(9/27 踩坑: 用户 Excel 打开 equity.csv 占锁 → EBUSY 崩掉 62 天跑批)
// 5 次×1s 退避; 最终失败抛出带指引的错误, 别只丢 errno
export function writeRetry(fn, label, tries = 5) {
  for (let i = 0; ; i++) {
    try { return fn(); }
    catch (e) {
      if ((e.code === 'EBUSY' || e.code === 'EPERM') && i < tries - 1) {
        const until = Date.now() + 1000;
        while (Date.now() < until);   // 同步短退避(写文件都是 ms 级, 不值得上异步)
        continue;
      }
      if (e.code === 'EBUSY' || e.code === 'EPERM') {
        throw new Error(`文件被占用(请关闭 Excel/编辑器后重跑): ${label} [${e.code}]`);
      }
      throw e;
    }
  }
}

// 当日结算: 现金 + 持仓市值 → 追加 equity.csv
export function settleDay({ runDir, group, date, state, barsByCode, hole }) {
  let mv = 0;
  for (const p of state.positions) {
    const dayBars = (barsByCode[p.code] || []).filter(b => dayOf(b.t) === date);
    if (dayBars.length) mv += dayBars[dayBars.length - 1].c * p.qty;
    else {   // 当日无 bar(停牌): 用最近一根历史 bar 收盘价估值并记洞
      const hist = (barsByCode[p.code] || []).filter(b => dayOf(b.t) < date);
      if (hist.length) { mv += hist[hist.length - 1].c * p.qty; hole?.('停牌按前收估值', `${p.code}@${date}`); }
      else { mv += p.cost * p.qty; hole?.('无估值bar按成本', `${p.code}@${date}`); }
    }
  }
  const nav = +(state.cash + mv).toFixed(2);
  const shBars = (barsByCode['sh000001'] || []).filter(b => dayOf(b.t) === date);
  const f = path.join(runDir, 'equity.csv');
  writeRetry(() => {
    if (!fs.existsSync(f)) fs.writeFileSync(f, BOM + 'date,cash,market_value,total_nav,return_pct,sh_close\n');
    fs.appendFileSync(f, [date, state.cash.toFixed(2), mv.toFixed(2), nav,
      ((nav / state.nav_start - 1) * 100).toFixed(2), shBars.length ? shBars[shBars.length - 1].c : ''].join(',') + '\n');
  }, f);
  state.equity.push({ date, nav });
  return nav;
}

// trades.csv: 逐笔成交(含被可成交性过滤拒掉的, verdict=rejected 留痕)
export function writeTrades(runDir, allFills) {
  const f = path.join(runDir, 'trades.csv');
  const head = 'date,id,code,name,side,verdict,trigger_bar,fill_bar,px,qty,fee,note\n';
  const esc = s => `"${String(s ?? '').replaceAll('"', "'")}"`;
  const rows = allFills.map(x => [x.trigger_bar.slice(0, 8), x.id, x.code, x.name, x.side, x.verdict,
    x.trigger_bar, x.fill_bar || '', x.px ?? '', x.qty ?? '', x.fee ?? '', esc(x.note)].join(','));
  writeRetry(() => fs.writeFileSync(f, BOM + head + rows.join('\n') + '\n'), f);
}

// report.md: 每组一份, 对齐 pilot-2week 的报告骨架
export function writeReport({ runDir, group, days, state, allFills, extra = {} }) {
  const eq = state.equity;
  const nav0 = state.nav_start, nav1 = eq.length ? eq[eq.length - 1].nav : nav0;
  const filled = allFills.filter(x => x.verdict === 'filled');
  const rejected = allFills.filter(x => x.verdict === 'rejected');
  //  round-trip 盈亏配对(先进先出, 仅统计口径用)
  const buys = {}, rt = [];
  for (const x of filled) {
    if (x.side === 'buy') (buys[x.code] ||= []).push(x);
    else {
      const b = (buys[x.code] || []).shift();
      if (b && x.px && b.px) rt.push({ code: x.code, name: x.name, pnl: +(((x.px - b.px) * x.qty) - b.fee - x.fee).toFixed(2), pct: +(((x.px / b.px - 1) * 100)).toFixed(2) });
    }
  }
  const wins = rt.filter(r => r.pnl > 0);
  // 最大回撤
  let peak = nav0, mdd = 0;
  for (const e of eq) { peak = Math.max(peak, e.nav); mdd = Math.min(mdd, (e.nav / peak - 1) * 100); }
  const md = `# replay 回测报告 · ${group} 组

- **区间**: ${days[0]} → ${days[days.length - 1]}(${days.length} 个交易日)
- **粒度**: ${extra.granNote || '按日期自动分层'}
- **起始资金**: ${nav0.toFixed(2)} | **终值**: **${nav1.toFixed(2)}** | **总收益**: **${((nav1 / nav0 - 1) * 100).toFixed(2)}%**
- **最大回撤**: ${mdd.toFixed(2)}% | **成交**: ${filled.length} 笔(被拒 ${rejected.length} 笔) | **round-trip**: ${rt.length} 笔, ${wins.length} 胜
${extra.llmNote || ''}
## round-trip 明细

| 标的 | 盈亏 | % |
|---|---|---|
${rt.map(r => `| ${r.name}(${r.code}) | ${r.pnl >= 0 ? '+' : ''}${r.pnl} | ${r.pct >= 0 ? '+' : ''}${r.pct}% |`).join('\n') || '| (无) | | |'}

## 被可成交性过滤拒绝的成交(不许编造成交的留痕)

${rejected.map(r => `- ${r.trigger_bar} ${r.name} ${r.side}: ${r.note || ''}`).join('\n') || '(无)'}

## 文件
- trades.csv / equity.csv / decisions/(每日决策+哈希链) / holes.log(数据洞) / hashchain.log(防作伪链)
${extra.appendix || ''}
`;
  writeRetry(() => fs.writeFileSync(path.join(runDir, 'report.md'), md), path.join(runDir, 'report.md'));
}
