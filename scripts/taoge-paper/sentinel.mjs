// sentinel.mjs — 盘中哨兵: 轮询行情 → 本地拼bar → 竞价捕获 → 触发引擎 → 唤醒Claude
//
// live:    node sentinel.mjs                      (任务计划程序 09:12 启动, 15:10 自退)
// 回放:    node sentinel.mjs --replay 20260918 --no-wake --auto-exec
//   --replay DATE  用 kline 缓存 m5 逐bar回放(竞价段无历史数据, 跳过并记洞)
//   --no-wake      不 spawn claude, 唤醒请求只写 wake_requests.jsonl
//   --auto-exec    触发即自动按"下一根bar开盘价"成交(仅回放/测试! live 永远由Claude裁决)
//   --inbox-only   只做微信中继(agent.log→唤醒→replies/→hermes send), 不轮询行情
import fs from 'fs';
import path from 'path';
import { spawn } from 'child_process';
import { fileURLToPath } from 'url';
import { makeQuoteClient, fetchM5 } from './quote.mjs';
let lastQuotes = {};   // 每轮轮询更新的全量快照(wake附关联票用, 2026-09-22)
import { dbRow, hashchain, hole, wakeLog } from './dblog.mjs';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const KLINE_DIR = path.join(ROOT, '..', 'bilibili-taoge', 'downloads', 'kline');
const args = process.argv.slice(2);
const REPLAY = args.includes('--replay') ? args[args.indexOf('--replay') + 1] : null;
const NO_WAKE = args.includes('--no-wake');
const AUTO_EXEC = args.includes('--auto-exec');
const INBOX_ONLY = args.includes('--inbox-only');

const cfg = JSON.parse(fs.readFileSync(path.join(ROOT, 'config.json'), 'utf8'));
const stateFile = path.join(ROOT, 'paper_state.json');
const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
const saveState = () => fs.writeFileSync(stateFile, JSON.stringify(state, null, 1));

const FEE_B = 0.00025, FEE_S = 0.00075;
// 量单位归一: 缓存bar用vol(股), mkline新抓用v(手) → 统一返回股
const shares = b => b.vol ?? (b.v || 0) * 100;
const barAmt = b => b.amount || shares(b) * b.c;

// ---------- 工具 ----------
const hhmm = t => t.slice(8, 10) + ':' + t.slice(10, 12);
const dayOf = t => t.slice(0, 8);
const dateStr = d => String(d.getFullYear()) + String(d.getMonth() + 1).padStart(2, '0') + String(d.getDate()).padStart(2, '0');
function loadWatchlist(date) {
  const f = path.join(ROOT, 'watchlist', date + '.json');
  if (!fs.existsSync(f)) { hole('watchlist缺失', date); return []; }
  return JSON.parse(fs.readFileSync(f, 'utf8')).items;
}
function loadBars(code) {
  const f = path.join(KLINE_DIR, code + '_m5.json');
  return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')).bars : [];
}

// ---------- 触发引擎 ----------
// ctx: {price, prevClose, dayAmount, barsToday, histBySlot(同序bar历史均量), nowBar}
function condOk(c, ctx) {
  switch (c.type) {
    case 'time_window': { const t = hhmm(ctx.nowBar.t); return t >= c.from && t <= c.to; }
    case 'price_above': return ctx.price != null && ctx.price > c.value;
    case 'price_below': return ctx.price != null && ctx.price < c.value;
    case 'pct_above': return ctx.prevClose && ctx.price != null && (ctx.price / ctx.prevClose - 1) * 100 > c.value;
    case 'pct_below': return ctx.prevClose && ctx.price != null && (ctx.price / ctx.prevClose - 1) * 100 < c.value;
    case 'amount_gt': return ctx.dayAmount > c.value;
    case 'vol_ratio_gt': {
      const avg = ctx.histBySlot[ctx.nowBar.t.slice(8)];
      return avg && shares(ctx.nowBar) > avg * c.value;
    }
    default: hole('未知条件类型', JSON.stringify(c)); return false;
  }
}

// ---------- 决策落盘(+哈希链) ----------
function writeDecision(date, item, ctx, verdict) {
  const dir = path.join(ROOT, 'decisions', date);
  fs.mkdirSync(dir, { recursive: true });
  const f = path.join(dir, `${ctx.nowBar.t}_${item.id}.json`);
  fs.writeFileSync(f, JSON.stringify({
    decision_time: ctx.nowBar.t, strategy: item.strategy, trigger_id: item.id,
    code: item.code, name: item.name, side: item.side,
    info_cutoff: ctx.nowBar.t,                 // 决策时可见信息的边界
    price_seen: ctx.price, prev_close: ctx.prevClose, day_amount: Math.round(ctx.dayAmount),
    conditions: item.conditions, action: item.action, source: item.source,
    verdict,                                   // auto_exec | wake_pending | notify_only
  }, null, 1));
  hashchain(f);
  return f;
}

// ---------- 成交(仅 auto-exec) ----------
function execFill(date, item, nextBar, pos) {
  const px = nextBar.o;
  if (item.action.type === 'buy') {
    const qty = item.action.qty, amt = px * qty, fee = +(amt * FEE_B).toFixed(2);
    if (amt + fee > state.cash) { hole('资金不足', item.id); return null; }
    state.cash -= amt + fee;
    state.positions.push({ code: item.code, name: item.name, qty, cost: px, feeB: fee, buy_date: date, buy_bar: nextBar.t, trigger_id: item.id });
    return { side: 'buy', px, qty, fee };
  }
  if (item.action.type === 'sell' && pos) {
    const qty = item.action.pct ? Math.floor(pos.qty * item.action.pct / 100) * 1 : (item.action.qty || pos.qty);
    const amt = px * qty, fee = +(amt * FEE_S).toFixed(2);
    state.cash += amt - fee;
    pos.qty -= qty;
    const closed = pos.qty <= 0;
    if (closed) state.positions = state.positions.filter(p => p !== pos);
    return { side: 'sell', px, qty, fee, closed };
  }
  return null;
}

// ---------- 微信 inbox(hermes 中转: agent.log → 唤醒 → replies/ → hermes send) ----------
// hermes-agent 是 kimi 独立 agent, 无法直接访问 Claude; 但它把每条入站微信写进 agent.log
// 的 "inbound message: platform=weixin ... msg='...'" 行, 哨兵 tail 该日志实现双向中继。
import { spawnSync } from 'child_process';
const INBOX = cfg.inbox || {};
const REPLIES_DIR = path.join(ROOT, 'replies');
const SENT_LOG = path.join(REPLIES_DIR, 'sent.log');
const INBOX_STATE = path.join(ROOT, 'state', 'inbox_offset.json');
const startedAt = new Date();
let inboxOffset = 0, lastSendAttempt = 0;

function loadInboxOffset() {
  try {
    const s = JSON.parse(fs.readFileSync(INBOX_STATE, 'utf8'));
    if (s.log === INBOX.log && fs.existsSync(INBOX.log) && fs.statSync(INBOX.log).size >= s.offset)
      return s.offset;
  } catch {}
  // 无记录/日志换文件: 从文件尾开始, 只认启动后的新消息(防重启复读历史)
  return fs.existsSync(INBOX.log) ? fs.statSync(INBOX.log).size : 0;
}
function saveInboxOffset() {
  fs.mkdirSync(path.dirname(INBOX_STATE), { recursive: true });
  fs.writeFileSync(INBOX_STATE, JSON.stringify({ log: INBOX.log, offset: inboxOffset, at: new Date().toISOString() }));
}

function checkInbox(date) {
  if (!INBOX.enabled || !INBOX.log || !fs.existsSync(INBOX.log)) return;
  const size = fs.statSync(INBOX.log).size;
  if (size < inboxOffset) { hole('inbox日志被截断重置', INBOX.log); inboxOffset = 0; }
  if (size === inboxOffset) return;
  const fd = fs.openSync(INBOX.log, 'r');
  const buf = Buffer.alloc(size - inboxOffset);
  fs.readSync(fd, buf, 0, buf.length, inboxOffset);
  fs.closeSync(fd);
  inboxOffset = size; saveInboxOffset();
  for (const line of buf.toString('utf8').split('\n')) {
    const m = line.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .*inbound message: platform=weixin .* msg='(.*)' reply_to_id=/);
    if (!m) continue;
    if (new Date(m[1].replace(' ', 'T')) < startedAt) continue;   // 双重保险: 不回启动前的消息
    const msg = m[2].trim();
    const prefix = (INBOX.prefix || ['k3:']).find(p => msg.toLowerCase().startsWith(p.toLowerCase()));
    if (!prefix) continue;
    const ask = msg.slice(prefix.length).trim();
    if (!ask) continue;
    fs.mkdirSync(REPLIES_DIR, { recursive: true });
    const replyFile = path.join(REPLIES_DIR, `reply_${Date.now()}.txt`);
    const prompt = `[微信用户消息经hermes中转] 用户(人在外面, 手机微信提问): "${ask}"
你是 taoge-paper 的问答会话。可读 paper_state.json / watchlist/${date}.json / rules_seed.json / decisions/${date}/ / journal/ 后回答。
纪律: ①把回复写到 ${replyFile} (纯文本≤300字, 口语化, 不用markdown表格) ②除此之外不写任何文件 ③不联网, 不调用任何发送工具 ④工具调用≤4轮 ⑤数据里没有的就直说不知道, 不编造。`;
    wakeLog({ kind: 'wechat_inbox', msg: ask.slice(0, 200), reply_file: replyFile });
    if (!NO_WAKE && cfg.wake.enabled) spawnWake(prompt, 'inbox');
  }
}

function processOutbox() {
  if (!INBOX.enabled || !fs.existsSync(REPLIES_DIR)) return;
  if (Date.now() - lastSendAttempt < (INBOX.send_min_gap_ms || 100000)) return;
  const sent = new Set(fs.existsSync(SENT_LOG) ? fs.readFileSync(SENT_LOG, 'utf8').split('\n').filter(Boolean) : []);
  const pending = fs.readdirSync(REPLIES_DIR).filter(f => /^reply_\d+\.txt$/.test(f) && !sent.has(f)).sort();
  if (!pending.length) return;
  lastSendAttempt = Date.now();
  const f = pending[0];
  const r = spawnSync(INBOX.hermes, ['send', '--to', 'weixin', '-s', 'k3回复', '-f', path.join(REPLIES_DIR, f)],
    { encoding: 'utf8', timeout: 60000, windowsHide: true });
  const out = ((r.stdout || '') + (r.stderr || '')).trim();
  if (r.status === 0 && !/rate limited|failed|error/i.test(out)) {
    fs.appendFileSync(SENT_LOG, f + '\n');
    wakeLog({ kind: 'wechat_reply_sent', file: f });
  } else {
    // 失败(典型=iLink限流): 不标sent, 惩罚性退避15分钟后再试(限流期重试只会加深上游惩罚)
    lastSendAttempt = Date.now() + (INBOX.send_retry_ms || 900000);
    wakeLog({ kind: 'wechat_reply_fail', file: f, err: out.slice(0, 200) });
  }
}

// ---------- 告警(用户铁律: 盘中出问题第一时间通知 — 什么问题/导致什么/该怎么做) ----------
// 与 inbox 中继解耦: 即使微信问答交给 kimi(inbox.enabled=false), 告警照发。
// 防抖: 同类30分钟只写1次; 投递走队列(alerts/目录=outbox), 失败退避15分钟后由哨兵循环重试,
// 投递成功才记 delivered.log — 限流不会丢告警, 只会迟到。
const ALERTS_DIR = path.join(ROOT, 'alerts');
const ALERT_SENT = path.join(ALERTS_DIR, 'sent_alerts.log');
const ALERT_DELIVERED = path.join(ALERTS_DIR, 'delivered.log');
let lastAlertAt = 0;
function alert(what, impact, action) {
  wakeLog({ kind: 'alert', what, impact, action });
  const now = Date.now();
  const key = what.slice(0, 40);
  const log = fs.existsSync(ALERT_SENT) ? fs.readFileSync(ALERT_SENT, 'utf8') : '';
  if (log.split('\n').some(l => { const i = l.indexOf('|'); return i > 0 && l.slice(i + 1) === key && now - +l.slice(0, i) < 30 * 60000; })) return;
  fs.mkdirSync(ALERTS_DIR, { recursive: true });
  fs.writeFileSync(path.join(ALERTS_DIR, `alert_${now}.txt`), `【什么问题】${what}\n【导致什么】${impact}\n【该怎么做】${action}`);
  fs.appendFileSync(ALERT_SENT, `${now}|${key}\n`);
  processAlerts();   // 立即尝试投递, 失败自然进入退避重试
}

function processAlerts() {
  if (!fs.existsSync(ALERTS_DIR)) return;
  if (Date.now() - lastAlertAt < 60000) return;   // 全局投递节流: 1分钟最多1条
  const hermes = (cfg.inbox || {}).hermes;
  if (!hermes) return;
  const delivered = new Set(fs.existsSync(ALERT_DELIVERED) ? fs.readFileSync(ALERT_DELIVERED, 'utf8').split('\n').filter(Boolean) : []);
  // alert_*=哨兵告警, alert_settle_*=结算告警(结算直发失败时由存活的哨兵代收重投)
  const pending = fs.readdirSync(ALERTS_DIR).filter(f => /^alert(_settle)?_\d+\.txt$/.test(f) && !delivered.has(f)).sort();
  if (!pending.length) return;
  lastAlertAt = Date.now();
  const f = pending[0];
  const r = spawnSync(hermes, ['send', '--to', 'weixin', '-s', '哨兵告警', '-f', path.join(ALERTS_DIR, f)],
    { encoding: 'utf8', timeout: 60000, windowsHide: true });
  const out = ((r.stdout || '') + (r.stderr || '')).trim();
  if (r.status === 0 && !/rate limited|failed|error/i.test(out)) {
    fs.appendFileSync(ALERT_DELIVERED, f + '\n');
    wakeLog({ kind: 'alert_delivered', file: f });
  } else {
    lastAlertAt = Date.now() + (INBOX.send_retry_ms || 900000);   // 限流期重试只会加深上游惩罚
    wakeLog({ kind: 'alert_send_fail', file: f, err: out.slice(0, 200) });
  }
}

// ---------- 唤醒 ----------
// Windows: detached:true + stdio:'ignore' 会让 shell:true 的子进程静默死(9/21实盘踩坑, 全天0唤醒);
// 不要 detached/unref — Windows 子进程不随父退出被杀; stdout/stderr 落 wake_logs/ 可观测
function spawnWake(prompt, tag) {
  fs.mkdirSync(path.join(ROOT, 'wake_logs'), { recursive: true });
  const out = fs.openSync(path.join(ROOT, 'wake_logs', `${dateStr(new Date())}_${String(Date.now()).slice(-6)}_${tag}.log`), 'a');
  const child = spawn(cfg.wake.cmd, cfg.wake.args, {
    cwd: cfg.wake.cwd, stdio: ['pipe', out, out], shell: true, windowsHide: true,
  });
  child.on('error', e => {
    hole('唤醒spawn失败', tag + ' ' + String(e));
    alert('唤醒进程启动失败(tag=' + tag + ')', '触发已落decisions/但headless裁决会话没起来, 该触发不会有裁决也不会推送', '查 wake_logs/ 有无对应日志; 确认 claude CLI 在 PATH(当前cmd=' + cfg.wake.cmd + '); 可手动 echo 测试 | claude -p 验证');
  });
  child.stdin.end(prompt);   // prompt 走 stdin: 防引号/换行被 cmd 拼接吃掉
}

function wake(item, ctx, decisionFile) {
  // 关联票快照(2026-09-22 hermes): 从触发备注/出处提取其他代码, 附实时快照进唤醒包——
  // 裁决会话"不联网"纪律下也能验证跨票前提(如"龙头仍封板")。
  const related = [...new Set((((item.action && item.action.note) || '') + ' ' + (item.source || '')).match(/(sh|sz)\d{6}/g) || [])]
    .filter(c => c !== item.code).slice(0, 4);
  let relatedBlock = '';
  if (related.length) {
    const parts = related.map(c => {
      const q = lastQuotes[c];
      if (!q || !q.price) return `${c} 暂无快照`;
      const pct = q.prevClose ? ((q.price / q.prevClose - 1) * 100).toFixed(2) + '%' : '无昨收';
      return `${c} 现${q.price}(${pct})`;
    });
    relatedBlock = '\n关联票实时: ' + parts.join('; ');
  }
  const entry = {
    kind: item.action.type === 'notify' ? 'notify' : 'trigger',
    trigger_id: item.id, code: item.code, name: item.name, side: item.side,
    at_bar: ctx.nowBar.t, price: ctx.price, decision_file: decisionFile,
    prompt: `[taoge-paper checkpoint模式] ${item.name}(${item.code}) ${item.side} 条件命中@${ctx.nowBar.t} 现价${ctx.price}。
触发出处: ${item.source || '(无)'}
触发备注: ${item.action.note || '(无)'}${relatedBlock}
你是盘中裁决会话, 纪律: ①先读 rules_seed.json 找到该触发对应的规则(id/learned_before≤今天才能用) ②读 ${decisionFile} 与 paper_state.json ③裁决 approve/reject/降级notify, 写 decisions/${ctx.nowBar.t.slice(0, 8)}/${item.id}_裁决.json (含 rule_id/verdict/info_cutoff=现在时刻/reasoning≤3句) —— 先写决策文件, 再碰任何行情数据 ④approve 才更新 paper_state.json(改前重读文件, 别用会话开头的缓存) ⑤只做裁决不做研究, 不联网, 工具调用≤2轮后结束。`,
  };
  wakeLog(entry);
  if (!NO_WAKE && cfg.wake.enabled) spawnWake(entry.prompt, item.id);
}

// ---------- 核心节拍: 喂一个"当前快照上下文" ----------
function tick(date, items, barsByCode, idxByCode, prevCloseByCode, histSlotAvg) {
  for (const item of items) {
    if (item.valid_date !== date) continue;
    const bars = barsByCode[item.code], i = idxByCode[item.code];
    if (!bars || i == null || i < 0) continue;
    const nowBar = bars[i];
    const barsToday = bars.filter(b => dayOf(b.t) === date && b.t <= nowBar.t);
    const ctx = {
      nowBar, price: nowBar.c, prevClose: prevCloseByCode[item.code],
      // 缓存bar可能无amount字段: 缺省用 量(手)×100×收盘 估算
      dayAmount: barsToday.reduce((s, b) => s + barAmt(b), 0),
      histBySlot: histSlotAvg[item.code] || {},
    };
    if (!item.conditions.every(c => condOk(c, ctx))) continue;
    // 触发! 先定verdict再落盘, 一个触发只写一个决策文件
    const pos = state.positions.find(p => p.code === item.code);
    let verdict, fill = null;
    if (item.action.type === 'notify') verdict = 'notify_only';
    else if (AUTO_EXEC) {
      const next = bars[i + 1];
      if (!next) { hole('无下一根bar无法成交', item.id + '@' + nowBar.t); continue; }
      fill = execFill(date, item, next, pos);
      verdict = fill ? 'auto_exec' : 'exec_failed';
    } else verdict = 'wake_pending';
    const decisionFile = writeDecision(date, item, ctx, verdict);
    if (fill) {
      console.log(`${fill.side.toUpperCase()} ${item.name} ${fill.qty}@${fill.px} fee=${fill.fee} (${item.id})`);
      saveState();
    } else wake(item, ctx, decisionFile);
    items = items.filter(x => x !== item);   // 一次性触发
  }
  return items;
}

// 前5日同序bar均量(回放/启动回补时预计算)
function buildHistSlotAvg(bars, date) {
  const slots = {};
  for (const b of bars) {
    if (dayOf(b.t) >= date) continue;
    (slots[b.t.slice(8)] ||= []).push(shares(b));
  }
  const out = {};
  for (const [slot, vs] of Object.entries(slots)) {
    const last5 = vs.slice(-5);
    out[slot] = last5.reduce((s, v) => s + v, 0) / last5.length;
  }
  return out;
}

// ---------- 回放模式 ----------
async function replay(date) {
  let items = loadWatchlist(date);
  const codes = [...new Set(items.map(i => i.code))];
  const barsByCode = {}, idxByCode = {}, prevCloseByCode = {}, histSlotAvg = {};
  for (const c of codes) {
    const bars = loadBars(c);
    barsByCode[c] = bars.filter(b => dayOf(b.t) <= date);
    const dayBars = bars.filter(b => dayOf(b.t) === date);
    if (!dayBars.length) { hole('回放无当日bar', c + '@' + date); continue; }
    const prev = bars.filter(b => dayOf(b.t) < date);
    prevCloseByCode[c] = prev.length ? prev[prev.length - 1].c : null;
    histSlotAvg[c] = buildHistSlotAvg(bars, date);
  }
  // 全部code的当日bar时间轴并集, 逐bar推进(每根bar=一次"轮询周期")
  const timeline = [...new Set(codes.flatMap(c => (barsByCode[c] || []).filter(b => dayOf(b.t) === date).map(b => b.t)))].sort();
  console.log(`回放 ${date}: ${codes.length}票 ${timeline.length}根bar, watchlist ${items.length}条${NO_WAKE ? ' [no-wake]' : ''}${AUTO_EXEC ? ' [auto-exec]' : ''}`);
  hole('回放跳过竞价段', date + ' 09:15-09:25 无历史竞价数据');
  for (const t of timeline) {
    for (const c of codes) {
      const i = (barsByCode[c] || []).findIndex(b => b.t === t);
      if (i >= 0) idxByCode[c] = i;
    }
    items = tick(date, items, barsByCode, idxByCode, prevCloseByCode, histSlotAvg);
    if (!items.length) break;
  }
  console.log(`回放结束: 剩余未触发 ${items.length}条 [${items.map(i => i.id).join(', ') || '-'}]`);
  console.log(`state: cash=${state.cash.toFixed(2)} 持仓=${state.positions.map(p => p.name + '×' + p.qty).join(',') || '无'}`);
}

// ---------- live 模式 ----------
function pollIntervalMs(hhmmss) {
  const t = hhmmss.slice(0, 6);
  if (t < '091500') return 60000;          // 竞价前: 怠速
  if (t < '092500') return 10000;          // 竞价段
  if (t < '103000') return 15000;          // 早盘高频
  if (t < '140000') return 30000;          // 午间降频
  if (t < '150500') return 15000;          // 尾盘
  return 60000;
}

async function live() {
  const today = new Date();
  const date = String(today.getFullYear()) + String(today.getMonth() + 1).padStart(2, '0') + String(today.getDate()).padStart(2, '0');
  fs.mkdirSync(path.join(ROOT, 'raw'), { recursive: true });   // 9/21坑: 归档清掉raw/后全天ENOENT, 行情一行没落
  let items = loadWatchlist(date);
  if (!items.length) alert('今日watchlist缺失或为空(' + date + ')', '触发引擎无条目可判, 策略信号全丢(行情快照仍会落raw)', '先确认今天是否交易日; 是则说明昨晚evening会话没产出——检查 watchlist/' + date + '.json, 补齐后重启哨兵');
  const codes = [...new Set([...items.map(i => i.code), ...cfg.codes_extra])];
  const getQuotes = makeQuoteClient(cfg.sources, (ev, d) => wakeLog({ kind: ev, ...d }));
  // 启动回补: 昨收+历史同序均量+当日已有bar
  const barsByCode = {}, prevCloseByCode = {}, histSlotAvg = {}, lastBarT = {}, lastCum = {};
  const backfillFailed = [];
  for (const c of codes) {
    try {
      const m5 = await fetchM5(c, 320);
      barsByCode[c] = m5;
      const prev = m5.filter(b => dayOf(b.t) < date);
      prevCloseByCode[c] = prev.length ? prev[prev.length - 1].c : null;
      histSlotAvg[c] = buildHistSlotAvg(m5, date);
      lastBarT[c] = m5.length ? m5[m5.length - 1].t : null;
    } catch (e) {
      hole('mkline回补失败', c + ' ' + e);
      // 新股/无历史 vs 源故障分流(2026-09-22 hermes): 实时快照能取到价=新股首日无历史属预期, 取不到=真源故障
      try {
        const { quotes } = await getQuotes([c]);
        const q = quotes && quotes[c];
        if (q && q.price) {
          prevCloseByCode[c] = q.prevClose ?? null;   // 昨收兜底用快照字段(新股=发行价或空)
          histSlotAvg[c] = null;                       // 无历史均量, vol_ratio条件自动失效; price/pct(有昨收时)仍可用
          barsByCode[c] = [];
          hole('按新股/无历史处理', c + ' 实时价=' + q.price + ' prevClose=' + q.prevClose + '; vol_ratio失效, price/pct(有昨收时)可用');
          continue;
        }
      } catch (_) {}
      backfillFailed.push(c);
    }
  }
  if (codes.length && backfillFailed.length === codes.length)
    alert('启动回补全灭: 腾讯+新浪m5双源均不可用', '全部票无昨收/历史均量/当日已有bar, pct与量比类条件判不了, 仅price类条件能触发', '查网络与两源接口(可能IP被风控); 开盘前未恢复则今天人工盯盘, 别依赖哨兵');
  else if (backfillFailed.length)
    alert('部分票回补失败: ' + backfillFailed.join(','), '这些票缺昨收与历史均量, 其pct/vol_ratio条件失效', '看 holes.log 确认挂在哪个源; 双源齐挂才会到这步(单源挂有兜底)');
  console.log(`live ${date}: ${codes.length}票, watchlist ${items.length}条`);
  const rawQuoteFile = path.join(ROOT, 'raw', `quotes_${date}.jsonl`);
  const rawAuctionFile = path.join(ROOT, 'raw', `auction_${date}.jsonl`);

  let nextPollAt = 0, pollFails = 0;
  inboxOffset = loadInboxOffset();
  setInterval(async () => {
    const now = new Date();
    const clock = now.toTimeString().slice(0, 8).replaceAll(':', '');   // HHmmss
    checkInbox(date);        // 微信中继: 不收时段节流限制
    processOutbox();
    processAlerts();         // 告警队列: 限流迟到不丢, 退避后重投
    if (clock > '151000') { console.log('15:10 自退'); process.exit(0); }   // 禁止 saveState: 哨兵09:12的内存态会覆盖盘中裁决对paper_state的更新(9/23新华都卖出被冲掉)
    if (clock < '091200') return;
    if (Date.now() < nextPollAt) return;
    // 反爬虫抖动: 基准周期×(0.75~1.25)随机, 绝不打固定节拍(用户指令: 不像爬虫, 防IP封)
    nextPollAt = Date.now() + pollIntervalMs(clock) * (0.75 + Math.random() * 0.5);
    try {
      const { quotes, raw, source } = await getQuotes(codes);
      if (quotes) lastQuotes = quotes;   // 刷新快照缓存供wake附关联票
      pollFails = 0;
      const inAuction = clock >= '091500' && clock < '092500';
      fs.appendFileSync(inAuction ? rawAuctionFile : rawQuoteFile,
        JSON.stringify({ clock, source, raw: raw.slice(0, 50000) }) + '\n');
      // 快照→拼bar: 只认比上次更新的bar时间(腾讯快照 time 字段=最近bar时间)
      // 快照 vol/amount 是当日累计值 → 必须做增量差分, 否则 dayAmount 随bar数成倍虚增
      for (const c of codes) {
        const q = quotes[c];
        if (!q) continue;
        if (q.prevClose && !prevCloseByCode[c]) prevCloseByCode[c] = q.prevClose;
        const bt = q.time && q.time.slice(0, 12);
        if (!bt || bt === lastBarT[c]) continue;
        lastBarT[c] = bt;
        const cum = lastCum[c] || { vol: 0, amt: 0 };
        const cumVol = q.volHands * 100, cumAmt = q.amount || 0;   // 累计股数/累计额(元)
        const dVol = Math.max(0, cumVol - cum.vol), dAmt = Math.max(0, cumAmt - cum.amt);
        lastCum[c] = { vol: cumVol, amt: cumAmt };
        // 用 vol(股) 而非 v(手), 与 kline 缓存口径一致(shares() 直读)
        (barsByCode[c] ||= []).push({ t: bt, o: q.price, h: q.price, l: q.price, c: q.price, vol: dVol, amount: dAmt });
      }
      // 触发检查(用每票最新bar)
      const idxByCode = {};
      for (const c of codes) idxByCode[c] = (barsByCode[c] || []).length - 1;
      items = tick(date, items, barsByCode, idxByCode, prevCloseByCode, histSlotAvg);
    } catch (e) {
      pollFails++;
      hole('轮询异常', String(e).slice(0, 200));
      if (pollFails === 5)   // 连击第5次告警一次(30分钟同类防抖); 恢复后成功会清零重新计
        alert('连续5次轮询失败(快照全源不可用?)', '行情停更=触发引擎盲飞, 拼bar断档, 结算当天可能有数据洞', '查 holes.log 看是哪个源在挂; 大概率IP被临时风控——降频等恢复, 或检查 tencent/sina/eastmoney 三源逐个手测');
    }
  }, 1000);
}

// ---------- inbox-only 模式: 非交易时段的微信中继(手动启动, Ctrl+C退) ----------
function inboxOnly() {
  const date = dateStr(new Date());
  inboxOffset = loadInboxOffset();
  console.log(`inbox-only ${date}: 监听微信 k3: 消息 → headless claude → replies/ → hermes send`);
  setInterval(() => { checkInbox(date); processOutbox(); processAlerts(); }, 2000);
}

// ---------- 单实例锁(9/21坑: inbox-only残留进程+计划任务live同时tail → 消息重复唤醒) ----------
const LOCK = path.join(ROOT, 'state', 'sentinel.lock');
function acquireLock(mode) {
  try {
    const s = JSON.parse(fs.readFileSync(LOCK, 'utf8'));
    try { process.kill(s.pid, 0); console.log(`已有哨兵在跑(pid=${s.pid}, ${s.mode}), 退出`); process.exit(0); }
    catch {}   // pid已死=陈旧锁, 覆盖
  } catch {}
  fs.mkdirSync(path.dirname(LOCK), { recursive: true });
  fs.writeFileSync(LOCK, JSON.stringify({ pid: process.pid, mode, at: new Date().toISOString() }));
}

if (REPLAY) await replay(REPLAY);
else if (INBOX_ONLY) { acquireLock('inbox-only'); inboxOnly(); }
else { acquireLock('live'); await live(); }
