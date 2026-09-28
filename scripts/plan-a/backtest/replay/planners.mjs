// planners.mjs — 三组对照的预案生成器 + 一致率指标(只做这一件事: 信息包 → 当日 watchlist)
//
// 分组(2026-09-27 用户拍板修订: 原五组改三组+一指标):
//   A 照抄桃哥:  解析 T-1 md 解读里他自述的操作, 机械跟单(基准组, 慢一天是诚实的代价)
//   C 裸 LLM:    通用提示, 无 persona(带证据锚 schema)
//   D persona-LLM: 带 skills/taoge-skill/ 全部画像文件(带证据锚 schema)
//   E 一致率:    评估指标不是组 —— D 预案 vs T 晚 md 他自述操作(方向/选股/价位, 不算收益)
//   (B 机械规则组砍掉: taoge-paper 实盘在跑它, 已有外部对照)
import fs from 'fs';
import { PLAN_SCHEMA_HINT } from './llm.mjs';

const PERSONA_DIR = 'C:/Users/admin/dev/investment-tool/skills/taoge-skill/persona';

// ---------- A 组: 照抄桃哥 ----------
// 他 T-1 自述"买了X" → A 组 T 日开盘跟买(次根 bar 开盘价); 自述"走了/卖了X" → A 组 T 日开盘跟卖。
// 解析只信两类结构化证据, 其余记洞不猜:
//   ① 提及个股的 tags: 已买入/已抄底/已追买/已低吸买入/低吸了 → 买
//   ② 桃哥今日操作 自由文本: 持仓股名出现在 走/卖/清/割 关键词 ±6 字内 → 卖
export function planA(pack, state, hole) {
  const items = [], t = pack.taoge;
  if (!t) return items;
  const date = pack.date;
  // 买入照抄(tags 证据)
  const BUY_TAGS = ['已买入', '已抄底', '已追买', '已低吸买入', '低吸了', '已建仓', '追了'];
  for (const m of t.mentions) {
    if (m.tags.some(tag => BUY_TAGS.some(bt => tag.includes(bt)))) {
      if (state.positions.some(p => p.code === m.code)) continue;   // 已持有不重复照抄
      items.push({
        id: `A-copy-buy-${m.code}-${date}`, strategy: 'A', code: m.code, name: m.name,
        side: 'buy', valid_date: date,
        conditions: [{ type: 'open' }],   // 开盘第一根 bar 确认后, 次根 bar 开盘价成交
        action: { type: 'buy', max_amt: 25000, note: `照抄: 他T-1自述[${m.tags.join('/')}]` },
        source: `${pack.prev_date} md 提及个股`,
      });
    }
  }
  // 卖出照抄(操作文本证据, 只判 A 组当前持仓)
  const SELL_RE = /(走|卖|清|割|撤|跑)/;
  for (const pos of state.positions) {
    const ops = t.his_ops || '';
    const idx = ops.indexOf(pos.name);
    if (idx >= 0 && SELL_RE.test(ops.slice(Math.max(0, idx - 6), idx + pos.name.length + 6))) {
      items.push({
        id: `A-copy-sell-${pos.code}-${date}`, strategy: 'A', code: pos.code, name: pos.name,
        side: 'sell', valid_date: date,
        conditions: [{ type: 'open' }],
        action: { type: 'sell', qty: pos.qty, note: `照抄: 他T-1自述卖出(${ops.slice(0, 60)})` },
        source: `${pack.prev_date} md 桃哥今日操作`,
      });
    } else if (ops && /走|卖|清/.test(ops) && idx < 0) {
      // 操作文本里有卖但匹配不上持仓名(别名/转写错字) → 记洞, 不猜
      hole?.('A组卖出匹配失败', `${date} 持仓${pos.name} 操作文本="${ops.slice(0, 80)}"`);
    }
  }
  return items;
}

// ---------- C/D 组: LLM 盘前预案 prompt ----------
// 信息包摘要文本(C/D 共用同一份输入, 唯一变量=persona, 保证消融干净)
export function packDigestText(pack) {
  const t = pack.taoge || {};
  const mentionLines = (t.mentions || []).map(m =>
    `  - ${m.name}(${m.code}) · ${m.tags.join('·')}${m.held ? ' 【桃哥: 持有】' : ''}${m.note ? ' — ' + m.note.slice(0, 80) : ''}`).join('\n');
  const visionLines = (t.vision || []).slice(0, 15).map(v =>
    `  - ${v.name}${v.code ? '(' + v.code + ')' : ''} ${v.price}(${v.pct}%)`).join('\n');
  const klineLines = Object.entries(pack.kline || {}).map(([c, k]) =>
    `  - ${c} 昨收${k.last_close}(${k.last_pct ?? '?'}%) 近${k.bars.length}日: ${k.bars.map(b => b.d.slice(4) + '收' + b.c).join(' ')}`).join('\n');
  const ruleLines = pack.rules.map(r => `  - ${r.id} ${r.name}(learned_before=${r.learned_before}): ${r.trigger || r.precondition || ''} → ${r.action || (r.items || []).join(';')}`).join('\n');
  // 2026-09-14 前的 md 无结构化解读小节: 转写原文(截断)兜底, 并显式标注数据形态, 防 LLM 假装看到解读
  const transcriptBlock = t.market_view ? '' :
    `\n【T-1晚 桃哥复盘转写原文(ASR, 含同音错字; 当日无结构化解读小节, 这是唯一复盘信息源)】\n${(t.transcript || '(无)').slice(0, 1800)}`;
  return `【信息边界】你只许用 ≤${pack.prev_date} 晚的信息(info_cutoff=${pack.info_cutoff}), 严禁提及任何之后的行情。
【T-1晚 桃哥复盘解读】
大盘判断: ${t.market_view || '(当日md无结构化解读小节, 见下方转写原文)'}
提及个股:
${mentionLines || '  (无)'}
桃哥今日操作: ${t.his_ops || '(无)'}
明日策略: ${t.strategy || '(无)'}${transcriptBlock}
【T-1晚 画面真值(视觉数据)】
${visionLines || '  (无)'}
【候选票 kline 历史(截止T-1收盘)】
${klineLines || '  (无)'}
【已学规则(全部带 learned_before ≤ 信息边界, 可直接引用)】
${ruleLines || '  (无可用规则)'}`;
}

// 证据锚纪律(C/D 共用, 拼进 prompt 尾部): 引不出证据的决策不许下单(立法 2026-09-27)
const EVIDENCE_DISCIPLINE = `【证据纪律(硬性, 机器逐条校验, 不合格直接丢弃该条目)】
每条 buy/sell 必须带 evidence 数组, 元素只许三种:
  ① "md:<信息包原文的连续逐字片段≥6字>" —— 必须逐字照抄【】区块里的连续文字, 禁止改写/省略中间字/拼接两句(空格可省, 字一个不能错); 引画面数据同样逐字(含数字)
  ② "kline:<代码>" —— 该代码的kline摘要必须出现在信息包里
  ③ "rule:<规则编号>" —— 只能用信息包/画像里实际存在的编号(如 R9 或 A2), 禁止自造编号
反例(会被杀): "md:太极实业 · 看多·已买入 【桃哥: 持有】"(中间省略了"(早盘)(转写别名)"原文, 不是连续子串); "rule:B10-risk"(自造编号)
正确例: "md:太极实业(sh600667) · 看多 · 已买入(早盘)"`;

export function promptC(pack) {
  return `你是短线交易预案生成器。今天是 ${pack.date.slice(0, 4)}-${pack.date.slice(4, 6)}-${pack.date.slice(6, 8)} 开盘前。
根据下面的 T-1 晚信息包, 产出今日 watchlist(盘中由机械引擎按"触发后次根bar开盘价"执行)。
纪律: 单票金额上限 25000 元; 只在信息包出现过的代码里选; 每个条目必须给可机械判定的 conditions; 不确定就不给条目, 空仓是合法输出。
${EVIDENCE_DISCIPLINE}
只输出一个 JSON 对象(不要markdown解释), schema:
${PLAN_SCHEMA_HINT}

${packDigestText(pack)}`;
}

export function promptD(pack) {
  const profile = fs.readFileSync(PERSONA_DIR + '/profile.md', 'utf8');
  const language = fs.readFileSync(PERSONA_DIR + '/language.md', 'utf8');
  const rules = fs.readFileSync(PERSONA_DIR + '/rules.md', 'utf8');
  return `${profile}

---

${language}

---

${rules}

---

以上是 B站 UP 主"股桃"(桃哥)的完整人格画像。你现在扮演桃哥, 今天是 ${pack.date.slice(0, 4)}-${pack.date.slice(4, 6)}-${pack.date.slice(6, 8)} 开盘前, 用他的思维方式/他的纪律产出今日 watchlist(盘中由机械引擎按"触发后次根bar开盘价"执行)。
纪律: 单票金额上限 25000 元(他缩量环境 2-3 成仓); 只在信息包出现过的代码里选; 退出不靠你(机械三档撤退统一兜底), 你只负责"买什么/什么条件买/避开什么"; 每个条目必须给可机械判定的 conditions; 不符合他审美的机会一律不给(空仓是合法输出)。
${EVIDENCE_DISCIPLINE}
只输出一个 JSON 对象(不要markdown解释, 不要角色扮演台词), schema:
${PLAN_SCHEMA_HINT}

${packDigestText(pack)}`;
}

// ---------- E 组: 一致率评估(D 预案 vs T 晚 md 他自述操作; 方向/选股/价位, 不算收益) ----------
// his_ops_set: 从 T 日晚 md 解析出的他的真实操作 {code: buy|sell|hold}
// plan: D 组当日 watchlist。输出三维度对照 JSON, 供报告汇总。
export function evalE(planItems, taogeT, hole) {
  const hisBuys = new Set(), hisSells = new Set(), hisHolds = new Set();
  for (const m of taogeT?.mentions || []) {
    if (m.tags.some(x => /已买入|已抄底|已追买|已低吸买入|低吸了|追了/.test(x))) hisBuys.add(m.code);
    if (m.held) hisHolds.add(m.code);
  }
  // 操作文本里的"走了/卖了X" → his_sell
  for (const m of taogeT?.mentions || []) {
    const ops = taogeT?.his_ops || '';
    const idx = ops.indexOf(m.name);
    if (idx >= 0 && /(走|卖|清|割|撤|跑)/.test(ops.slice(Math.max(0, idx - 6), idx + m.name.length + 6))) hisSells.add(m.code);
  }
  const planBuys = new Map(), planSells = new Map(), planWatch = new Map();
  for (const it of planItems) {
    if (it.action.type === 'buy') planBuys.set(it.code, it);
    else if (it.action.type === 'sell') planSells.set(it.code, it);
    else planWatch.set(it.code, it);
  }
  const rows = [];
  // 维度1+2: 选股与方向 —— 他的每个买入, D 是否同向(买=一致 / watch=半对 / 漏=miss)
  for (const code of hisBuys) {
    rows.push({
      code, his: 'buy',
      plan: planBuys.has(code) ? 'buy' : planWatch.has(code) ? 'watch' : 'none',
      direction_match: planBuys.has(code) ? 1 : planWatch.has(code) ? 0.5 : 0,
      price_dim: planBuys.get(code)?.conditions?.filter(c => /pct|price/.test(c.type)) || [],
    });
  }
  for (const code of hisSells) {
    rows.push({
      code, his: 'sell',
      plan: planSells.has(code) ? 'sell' : 'none',
      direction_match: planSells.has(code) ? 1 : 0,
      price_dim: [],
    });
  }
  // D 买了但他没买的 = 假阳性(也计入方向分母, 对抗式: 不只看命中)
  for (const [code] of planBuys) {
    if (!hisBuys.has(code)) rows.push({ code, his: 'none', plan: 'buy', direction_match: 0, price_dim: [] });
  }
  const n = rows.length;
  return {
    dimension_note: '方向=买卖同向(watch记0.5); 选股=plan.buy ∩ his.buy; 价位=plan触发条件留档人工对照(机械比对无真值, 记为局限)',
    his_buys: [...hisBuys], his_sells: [...hisSells], his_holds: [...hisHolds],
    rows,
    direction_score: n ? +(rows.reduce((s, r) => s + r.direction_match, 0) / n).toFixed(3) : null,
    selection_hit: hisBuys.size ? [...hisBuys].filter(c => planBuys.has(c)).length / hisBuys.size : null,
  };
}
