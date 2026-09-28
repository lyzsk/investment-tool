// replay.mjs — 桃哥拟人策略历史回放引擎(LLM 在环 replay)主入口
//
// 分组(2026-09-27 用户拍板): A 照抄桃哥 / C 裸LLM / D persona-LLM; E=一致率评估指标(不是组)。
// 用法:
//   node replay.mjs --sample                                   # 采样器 → runs/replay-pilot/sample_days.json(留给230天宇宙用)
//   node replay.mjs --smoke [--mock-llm]                       # smoke: A 跑 9/15-17 三天; C/D 跑 9/16 一天(LLM真调1次/组)
//   node replay.mjs --run --groups A --from 20260629 --to 20260926 --gran m30        # A组全区间(优先)
//   node replay.mjs --run --groups C,D --from 20260629 --to 20260926 --gran m30      # C/D全区间(夜间批量, ~124次headless)
// 铁律执行顺序(立法 §4/§9): 信息包(≤T-1) → 预案 → 决策落盘+哈希链 → 之后模拟器才许碰 T 日行情。
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { makeChain, makeHole } from './replay/hchain.mjs';
import { ensureBars, pickGranularity, loadCachedBars } from './replay/kline.mjs';
import { tradingCalendar, buildInfoPack, loadMd, parseTaogeSection, compactOf } from './replay/infopack.mjs';
import { simulateDay } from './replay/sim.mjs';
import { settleDay, writeTrades, writeReport, writeRetry } from './replay/settle.mjs';
import { runLlm, validatePlan, detectPollution } from './replay/llm.mjs';
import { planA, promptC, promptD, packDigestText, evalE } from './replay/planners.mjs';
import { sampleDays } from './replay/sampler.mjs';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const RUNS = path.join(ROOT, 'runs');
const NAV_START = 100475.40;   // 与 pilot-2week 同口径(用户 9/19 东财真实总资产), 便于对账
const LLM_CWD = 'C:/Users/admin/dev/investment-tool/scripts/taoge-paper';   // claude -p 工作目录(与模拟盘一致)

// ---------- CLI ----------
const args = process.argv.slice(2);
const opt = (name, dflt) => args.includes(name) ? args[args.indexOf(name) + 1] : dflt;
const FLAG = name => args.includes(name);
const GROUPS = (opt('--groups', 'A')).split(',').map(s => s.trim());
const FROM = opt('--from', '20260629'), TO = opt('--to', '20260926');
const GRAN = opt('--gran', 'auto');           // auto=按日期分层; m30=全程m30(首跑区间口径)
const MOCK = FLAG('--mock-llm');
const RULE_CUTOFF = opt('--rule-cutoff', 'T-1');
const LLM_DELAY = +opt('--llm-delay', 2000);
const RUN_TAG = opt('--tag', '');
// --resume(9/27 加, EBUSY 崩批后断点续跑): 决策(plan)/成交(fills)/复盘(review)已落盘的日子
// 不再调 LLM、不重跑 sim——按 fills 确定性重放账本(买扣钱/卖加钱), equity.csv 清空重结。
// 这样断点续跑不会重调 LLM 产生不同预案(温度0也挡不住 headless 抖动), 保证全区间是同一条世界线
const RESUME = FLAG('--resume');

// 重放一笔已落盘成交到账本(口径照 sim.tryFill: 买=cash-(px*qty+fee), 卖=cash+(px*qty-fee), 先进先出配对)
function applyFill(state, f) {
  if (f.verdict !== 'filled') return;   // notify_only/rejected 不动账本
  if (f.side === 'buy') {
    state.cash -= f.px * f.qty + f.fee;
    state.positions.push({ code: f.code, name: f.name, qty: f.qty, cost: f.px, feeB: f.fee,
      buy_date: f.fill_bar.slice(0, 8), buy_bar: f.fill_bar, trigger_id: f.id });
  } else if (f.side === 'sell') {
    state.cash += f.px * f.qty - f.fee;
    const pos = state.positions.find(p => p.code === f.code && p.qty > 0);
    if (pos) { pos.qty -= f.qty; if (pos.qty <= 0) state.positions = state.positions.filter(p => p !== pos); }
  }
}

// ---------- 交易日工具 ----------
const cal = tradingCalendar().map(d => d.date);
function daysInRange(from, to) {
  // T 入列 ⇔ 交易日历上 T 的前一日有 md(T-1 晚信息包是决策输入); prev 从全量日历找, 不受区间起点截断
  return cal.filter(d => d >= from && d <= to)
    .map(d => ({ date: d, prev: cal[cal.indexOf(d) - 1] }))
    .filter(x => x.prev);
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

// ---------- 单日单组: 决策 → 哈希 → 行情 → 执行 → 结算 ----------
async function runOneDay({ group, day, state, runDir, chain, hole, mockReview }) {
  const { date, prev } = day;
  const gran = GRAN === 'auto' ? pickGranularity(date) : GRAN;
  // ---- 1. 信息包(全部 ≤T-1 晚) ----
  const pack = await buildInfoPack(date, prev, { ruleCutoff: RULE_CUTOFF, hole });
  // ---- 2. 预案(分组生成; 此阶段不碰 T 日行情) ----
  const decDir = path.join(runDir, 'decisions', date);
  const decFile = path.join(decDir, `${group}_plan.json`);
  const fillsPath = path.join(decDir, `${group}_fills.json`);
  const reviewPath = path.join(decDir, `${group}_review.json`);
  // resume: 决策已落盘 → 直接读盘不重调 LLM(断点续跑必须保住同一条世界线)
  const resumedPlan = RESUME && fs.existsSync(decFile);
  let items = [], llmMeta = null, reviewInject = state.lastReview || null;
  if (resumedPlan) {
    const stored = JSON.parse(fs.readFileSync(decFile, 'utf8'));
    items = stored.items || [];
    llmMeta = { mode: 'resume', ...(stored.llm || {}) };
  } else if (group === 'A') {
    items = planA(pack, state, hole);
  } else {   // C / D: LLM 盘前预案(节点①)
    const promptBase = group === 'C' ? promptC(pack) : promptD(pack);
    const prompt = promptBase + (reviewInject
      ? `\n\n【你昨天的收盘复盘(你自己写的, 仅供修正参考)】\n${reviewInject}` : '');
    try {
      const mockResponse = group === 'C' ? MOCK_PLAN_C(date) : MOCK_PLAN_D(date);
      const { obj, mode } = await runLlm(prompt, { mock: MOCK, mockResponse, runDir, tag: `${date}_${group}_plan`, hole, cwd: LLM_CWD });
      const packText = packDigestText(pack);
      // 污染审计: 推理链出现包外代码/cutoff后日期 → 该日污染作废(立法)
      const pol = detectPollution(JSON.stringify(obj), packText, date);
      if (pol.length) {
        hole('LLM污染作废', `${group}@${date}: ${pol.join(';')}`);
        fs.appendFileSync(path.join(runDir, 'pollution_audit.log'),
          JSON.stringify({ date, group, hits: pol, at: new Date().toISOString() }) + '\n');
        llmMeta = { mode, polluted: pol };
      } else {
        // 规则锚全集: rules_seed 的 R 系 + (D组) persona/rules.md 的 A/B/C/D/E 系编号
        const ruleIds = new Set(pack.rules.map(r => r.id));
        if (group === 'D') {
          const pr = fs.readFileSync('C:/Users/admin/dev/investment-tool/skills/taoge-skill/persona/rules.md', 'utf8');
          for (const m of pr.matchAll(/^### ([A-E]\d+)\s/gm)) ruleIds.add(m[1]);
        }
        const plan = validatePlan(obj, date, hole, packText, ruleIds);
        items = plan.items;
        llmMeta = { mode, market_view: plan.market_view, n_items: items.length };
      }
    } catch (e) {
      hole('LLM调用/解析失败当日空仓', `${group}@${date} ${String(e).slice(0, 200)}`);
      llmMeta = { mode: MOCK ? 'mock' : 'real', error: String(e).slice(0, 200) };
    }
    if (!MOCK) await sleep(LLM_DELAY);   // headless 批量节流
  }
  // ---- 3. 决策落盘 + 哈希链(先写哈希, 再让模拟器碰行情; resume 日已落盘跳过) ----
  if (!resumedPlan) {
    fs.mkdirSync(decDir, { recursive: true });
    fs.writeFileSync(decFile, JSON.stringify({
      group, date, gran, info_cutoff: pack.info_cutoff, rule_cutoff: RULE_CUTOFF,
      llm: llmMeta, items,
    }, null, 1));
    chain(decFile);
  }
  // ---- 4. 行情准备(此刻起才许读 T 日数据) ----
  const codes = [...new Set([...items.map(i => i.code), ...state.positions.map(p => p.code), 'sh000001'])];
  const barsByCode = {};
  for (const c of codes) {
    try {
      barsByCode[c] = await ensureBars(c, gran, day.prev + '0000', date + '2359', hole);
    } catch (e) { hole('行情抓取失败', `${c}@${date} ${gran} ${String(e).slice(0, 100)}`); barsByCode[c] = []; }
    const dayBars = barsByCode[c].filter(b => b.t.startsWith(date));
    if (!dayBars.length && c !== 'sh000001') hole('当日无bar(停牌/窗口外)', `${c}@${date}`);
  }
  // ---- 5. 机械执行(三档撤退由 sim 自动挂; resume 日按已落盘 fills 确定性重放) ----
  let fills;
  if (RESUME && fs.existsSync(fillsPath)) {
    fills = JSON.parse(fs.readFileSync(fillsPath, 'utf8'));
    for (const f of fills) applyFill(state, f);
    const n = fills.filter(f => f.verdict === 'filled').length;
    if (n) console.log(`  [${group} ${date}] resume回放 ${n} 笔成交`);
  } else {
    fills = simulateDay({ date, items, state, barsByCode, hole, log: s => console.log(`  [${group} ${date}] ${s}`) });
    if (fills.length) {
      fs.writeFileSync(fillsPath, JSON.stringify(fills, null, 1));
      chain(fillsPath);
    }
  }
  // ---- 6. 结算 ----
  settleDay({ runDir, group, date, state, barsByCode, hole });
  // ---- 7. C/D 节点②: 收盘复盘(T 收盘后, 输入 ≤T 收盘; 产出供 T+1 注入) ----
  if ((group === 'C' || group === 'D') && !FLAG('--no-review')) {
    if (RESUME && fs.existsSync(reviewPath)) {
      // resume: 复盘已落盘 → 读盘注入次日, 不重调 LLM
      state.lastReview = JSON.stringify(JSON.parse(fs.readFileSync(reviewPath, 'utf8')));
    } else try {
      const daySummary = codes.filter(c => c !== 'sh000001').map(c => {
        const db = (barsByCode[c] || []).filter(b => b.t.startsWith(date));
        return db.length ? `${c} 开${db[0].o} 收${db[db.length - 1].c} 高${Math.max(...db.map(b => b.h))} 低${Math.min(...db.map(b => b.l))}` : null;
      }).filter(Boolean).join('; ');
      const fillSummary = fills.filter(f => f.verdict === 'filled').map(f => `${f.side} ${f.name} ${f.qty}@${f.px}(${f.note || ''})`).join('; ') || '无成交';
      const reviewPrompt = `你是${group === 'D' ? '扮演桃哥的复盘者' : '短线复盘助手'}。今天 ${date} 收盘。这是你今天的盘前预案与实际执行:
预案条目: ${JSON.stringify(items.map(i => ({ code: i.code, side: i.side, note: i.action.note })))}
实际成交: ${fillSummary}
今日行情(≤今日收盘): ${daySummary}
持仓: ${state.positions.map(p => p.name + '×' + p.qty + '@' + p.cost).join(',') || '无'}
写一段≤150字复盘 + 给明天预案的修正提示(≤3条)。只输出JSON: {"review":"...","tomorrow_hints":["..."]}`;
      const { obj } = await runLlm(reviewPrompt, {
        mock: MOCK, mockResponse: mockReview || JSON.stringify({ review: 'mock复盘', tomorrow_hints: [] }),
        runDir, tag: `${date}_${group}_review`, hole, cwd: LLM_CWD,
      });
      state.lastReview = JSON.stringify(obj);
      const rf = path.join(decDir, `${group}_review.json`);
      fs.writeFileSync(rf, JSON.stringify(obj, null, 1));
      chain(rf);
    } catch (e) { hole('复盘节点失败(不影响当日账目)', `${group}@${date} ${String(e).slice(0, 150)}`); }
    if (!MOCK) await sleep(LLM_DELAY);
  }
  return fills;
}

// ---------- 单组多日循环 ----------
async function runGroup(group, days, runDirParent) {
  const runDir = path.join(runDirParent, group + (RUN_TAG ? '_' + RUN_TAG : ''));
  fs.mkdirSync(runDir, { recursive: true });
  const chain = makeChain(runDir), hole = makeHole(runDir);
  const state = { cash: NAV_START, nav_start: NAV_START, positions: [], equity: [], lastReview: null };
  const allFills = [];
  if (RESUME) {
    // 账本确定性重结: 清空 equity.csv 全区间重写(逐日 append, 防断点处留半行/旧行)
    const eq = path.join(runDir, 'equity.csv');
    if (fs.existsSync(eq)) writeRetry(() => fs.unlinkSync(eq), eq);
  }
  for (const day of days) {
    console.log(`[${group}] ${day.date} (T-1=${day.prev})`);
    allFills.push(...await runOneDay({ group, day, state, runDir, chain, hole }));
  }
  writeTrades(runDir, allFills);
  writeReport({
    runDir, group, days: days.map(d => d.date), state, allFills,
    extra: {
      granNote: GRAN === 'auto' ? '按日期自动分层(m5/m15/m30/m60/day)' : `全程 ${GRAN}(首跑区间口径, m30窗口实测覆盖2026-05起)`,
      llmNote: group === 'A' ? '' : MOCK ? '- **LLM**: mock 模式(固定JSON), 链路验证用, 不代表模型水平\n' : '- **LLM**: claude -p 真调, 温度0, 原始输出在 llm_raw/\n',
    },
  });
  const nav1 = state.equity.length ? state.equity[state.equity.length - 1].nav : NAV_START;
  console.log(`[${group}] 完成: NAV ${nav1.toFixed(2)} (${((nav1 / NAV_START - 1) * 100).toFixed(2)}%) 成交${allFills.filter(f => f.verdict === 'filled').length}笔 → ${runDir}`);
  return { group, runDir, state, allFills };
}

// ---------- E 指标: D预案 vs T晚md他自述操作 ----------
async function runE(dResults, days, runDirParent) {
  const runDir = path.join(runDirParent, 'E_metric');
  fs.mkdirSync(runDir, { recursive: true });
  const hole = makeHole(runDir);
  const out = [];
  for (const day of days) {
    const decFile = path.join(dResults.runDir, 'decisions', day.date, 'D_plan.json');
    if (!fs.existsSync(decFile)) continue;
    const plan = JSON.parse(fs.readFileSync(decFile, 'utf8'));
    const mdT = loadMd(day.date, hole);
    const taogeT = mdT ? parseTaogeSection(mdT, hole) : null;
    const score = evalE(plan.items || [], taogeT, hole);
    out.push({ date: day.date, ...score });
  }
  fs.writeFileSync(path.join(runDir, 'E_scores.json'), JSON.stringify(out, null, 1));
  const valid = out.filter(o => o.direction_score != null);
  const avg = valid.length ? (valid.reduce((s, o) => s + o.direction_score, 0) / valid.length).toFixed(3) : 'n/a';
  console.log(`[E] 一致率: 均分 ${avg} (${valid.length} 天) → ${runDir}/E_scores.json`);
}

// ---------- mock 预案(smoke 用, claude -p 不可用时降级; 报告显式标注) ----------
function MOCK_PLAN_C(date) {
  return JSON.stringify({
    plan_date: date, market_view: 'mock: 缩量震荡, 谨慎',
    watchlist: [{
      id: 'mock-c-taiji', code: 'sh600667', name: '太极实业', side: 'buy', valid_date: date,
      conditions: [{ type: 'time_window', from: '09:31', to: '11:30' }, { type: 'pct_above', value: -3 }],
      action: { type: 'buy', max_amt: 20000, note: 'mock链路验证单' },
      evidence: ['md:太极实业(sh600667)', 'kline:sh600667'], source: 'mock',
    }],
  });
}
function MOCK_PLAN_D(date) {
  return JSON.stringify({
    plan_date: date, market_view: 'mock(桃哥腔): 缩量市只做辨识度',
    watchlist: [{
      id: 'mock-d-taiji', code: 'sh600667', name: '太极实业', side: 'buy', valid_date: date,
      conditions: [{ type: 'time_window', from: '09:31', to: '13:30' }, { type: 'index_pct_below', value: 0 }, { type: 'pct_above', value: 0.5 }],
      action: { type: 'buy', max_amt: 20000, note: 'mock辨识度红盘抗跌' },
      evidence: ['md:太极实业(sh600667)', 'kline:sh600667'], source: 'mock:R9思路',
    }],
  });
}

// ---------- 主流程 ----------
async function main() {
  fs.mkdirSync(RUNS, { recursive: true });
  if (FLAG('--sample')) {
    const hole = makeHole(path.join(RUNS, 'replay-pilot'));
    // 上证日线涨跌幅(极端日主判据): 一次抓全区间日线, 逐日算 pct
    const shBars = await ensureBars('sh000001', 'day', '202509010000', '202609262359', hole);
    const shDailyPct = {};
    for (let i = 1; i < shBars.length; i++)
      shDailyPct[shBars[i].t.slice(0, 8)] = +((shBars[i].c / shBars[i - 1].c - 1) * 100).toFixed(2);
    const days = sampleDays({ hole, shDailyPct });
    const out = path.join(RUNS, 'replay-pilot', 'sample_days.json');
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, JSON.stringify({
      _meta: {
        universe: '2025-10-01~2026-09-26 中 T-1 晚有桃哥 md 小节的交易日',
        rule: '每月3-5普通日 + 全部极端日(上证|涨跌|≥2% 或 T-1持有票在T日画面|涨跌|≥10%)',
        note: '2026-06-29~2026-09-26 首跑区间为全量不抽样, 本文件留给后续230天全宇宙用',
        generated: new Date().toISOString(),
      },
      days,
    }, null, 1));
    console.log(`采样完成: ${days.length} 天 → ${out}`);
    const months = {};
    for (const d of days) months[d.date.slice(0, 6)] = (months[d.date.slice(0, 6)] || 0) + 1;
    console.log('按月分布:', JSON.stringify(months));
    console.log('极端日:', days.filter(d => d.reasons.some(r => r.startsWith('extreme'))).map(d => `${d.date}(${d.reasons.join(',')})`).join(' ') || '无');
    return;
  }
  if (FLAG('--smoke')) {
    const days = [
      { date: '20260915', prev: '20260914' },
      { date: '20260916', prev: '20260915' },
      { date: '20260917', prev: '20260916' },
    ];
    const smokeDir = path.join(RUNS, 'replay-smoke');
    const aRes = await runGroup('A', days, smokeDir);
    // C/D 只跑 1 天(LLM 链路 smoke: 真调一次验证 JSON解析+哈希留痕)
    const oneDay = [days[1]];
    const cRes = await runGroup('C', oneDay, smokeDir);
    const dRes = await runGroup('D', oneDay, smokeDir);
    await runE(dRes, oneDay, smokeDir);
    return;
  }
  // --run 全区间
  const days = daysInRange(FROM, TO);
  console.log(`区间 ${FROM}~${TO}: ${days.length} 个交易日, 组=${GROUPS.join('/')}, gran=${GRAN}, rule_cutoff=${RULE_CUTOFF}${MOCK ? ' [mock-llm]' : ''}`);
  const parent = path.join(RUNS, `replay-${FROM.slice(2)}_${TO.slice(2)}`);
  let dRes = null;
  for (const g of GROUPS) {
    const res = await runGroup(g, days, parent);
    if (g === 'D') dRes = res;
  }
  if (dRes) await runE(dRes, days, parent);
}

main().catch(e => { console.error('FATAL', e); process.exit(1); });
