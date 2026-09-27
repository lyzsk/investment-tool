// llm.mjs — headless claude -p 调用封装(只做这一件事: 把 prompt 送进 LLM, 拿回结构化 JSON)
//
// Windows 坑(taoge-paper 已验证):
//   ① spawn 不带 shell:true 解析不了 claude.cmd → 必须 shell:true
//   ② 所有 spawn 必须 .on('error') 兜底 + windowsHide:true
//   ③ prompt 走 stdin, 防引号/换行被 cmd 拼接吃掉
// 纪律: 温度0(模型侧默认), 结构化 JSON 输出(schema 定死), 原始输出全留痕(runDir/llm_raw/),
//   解析失败=当日空仓记洞, 不许拿半截 JSON 去交易。
// --mock-llm 模式: 返回固定 JSON, 供 claude -p 不可用时的链路 smoke(报告里显式标注)。
import fs from 'fs';
import path from 'path';
import { spawn } from 'child_process';

// watchlist JSON schema(定死, LLM 只许在这个词表里填):
//   condition.type ∈ time_window/open/price_above/price_below/pct_above/pct_below/
//                    amount_gt/index_pct_below/index_pct_above/vol_ratio_gt/no_new_low_n
//   action.type ∈ buy/sell/notify; buy 用 max_amt(单票金额上限) 而非 qty(防 LLM 算错手数)
//   evidence(立法 2026-09-27 用户拍板, 防训练数据污染): 每条决策必须引用盘前信息包内的
//     具体内容 —— md原文片段 / kline数值 / 规则编号; 引不出证据的决策不许下单。
//     可机检的三类锚: "rule:R9" / "md:信息包原文子串(≥6字)" / "kline:sh600667"
export const PLAN_SCHEMA_HINT = `{
  "plan_date": "YYYY-MM-DD",
  "market_view": "一句话市况判断",
  "watchlist": [
    {
      "id": "英文短横线id", "code": "sh600127", "name": "金健米业",
      "side": "buy|sell|watch", "valid_date": "YYYYMMDD",
      "conditions": [
        {"type": "time_window", "from": "09:31", "to": "11:30"},
        {"type": "pct_below", "value": -2},
        {"type": "no_new_low_n", "bars": 3}
      ],
      "action": {"type": "buy", "max_amt": 25000, "note": "≤2句理由"},
      "evidence": ["rule:R6", "md:金健米业(sh600127) · 观察 · 低吸方向", "kline:sh600127"],
      "source": "依据的规则id或信息包条目"
    }
  ]
}`;

const COND_TYPES = new Set(['time_window', 'open', 'price_above', 'price_below', 'pct_above', 'pct_below',
  'amount_gt', 'index_pct_below', 'index_pct_above', 'vol_ratio_gt', 'no_new_low_n']);

// 证据锚校验(单条): 返回 true=锚住; 锚不在信息包里=幻觉证据, 该决策作废
function evidenceOk(ev, packText, ruleIds) {
  if (typeof ev !== 'string') return false;
  if (ev.startsWith('rule:')) return ruleIds.has(ev.slice(5).trim());
  if (ev.startsWith('kline:')) return packText.includes(ev.slice(6).trim());
  if (ev.startsWith('md:')) { const q = ev.slice(3).trim(); return q.length >= 6 && packText.includes(q); }
  return false;   // 无前缀=不可机检, 一律按不合格处理(严进)
}

// 污染审计(立法: 推理链出现信息包外的事件 → 标记该日污染作废)
// 可机检的两类污染:
//   ① 引用了信息包里不存在的股票代码(训练数据记忆里的票混进来)
//   ② 提及晚于 info_cutoff 的日期(未来函数/记忆泄露)
// 注意局限: "信息包外的事件"若不含代码/日期(如复述某条旧新闻)机械查不出 —— 复盘人工兜底。
export function detectPollution(rawText, packText, infoCutoff) {
  const hits = [];
  for (const m of rawText.matchAll(/(sh|sz)\d{6}/g)) {
    if (!packText.includes(m[0])) hits.push('包外代码:' + m[0]);
  }
  const cutoff = infoCutoff.slice(0, 8);
  for (const m of rawText.matchAll(/(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})/g)) {
    const d = m[1] + String(m[2]).padStart(2, '0') + String(m[3]).padStart(2, '0');
    if (d > cutoff) hits.push(' cutoff后日期:' + d);
  }
  return [...new Set(hits)];
}

// 输出校验: 逐条过 schema + 证据锚, 不合法的条目丢弃记洞(宁缺毋滥), 全丢=当日空仓
export function validatePlan(obj, date, hole, packText = '', ruleIds = new Set()) {
  const items = [];
  for (const [k, it] of (obj?.watchlist || []).entries()) {
    const bad = [];
    if (!/^(sh|sz)\d{6}$/.test(it?.code || '')) bad.push('code');
    if (!['buy', 'sell', 'watch'].includes(it?.side)) bad.push('side');
    if (!Array.isArray(it?.conditions) || !it.conditions.length) bad.push('conditions');
    else for (const c of it.conditions) if (!COND_TYPES.has(c.type)) bad.push('cond:' + c.type);
    if (!['buy', 'sell', 'notify'].includes(it?.action?.type)) bad.push('action');
    if (it?.action?.type === 'buy' && it.side !== 'buy') bad.push('side/action不一致');
    // 证据锚: buy/sell 必须至少一条可机检证据且全部锚在信息包内; watch 放宽(不下单)
    const evs = Array.isArray(it?.evidence) ? it.evidence : [];
    if (it?.action?.type !== 'notify') {
      if (!evs.length) bad.push('无evidence');
      else {
        const badEv = evs.filter(e => !evidenceOk(e, packText, ruleIds));
        if (badEv.length) bad.push('证据锚外:' + badEv.join('|').slice(0, 120));
      }
    }
    if (bad.length) { hole?.('LLM条目校验丢弃', `#${k} ${it?.code || '?'}: ${bad.join(',')}`); continue; }
    items.push({
      id: String(it.id || `llm-${k}`), strategy: 'llm', code: it.code, name: it.name || it.code,
      side: it.side === 'watch' ? 'watch' : it.side, valid_date: date,
      conditions: it.conditions, evidence: evs,
      action: it.action.type === 'notify'
        ? { type: 'notify', note: String(it.action.note || '') }
        : { type: it.action.type, max_amt: Math.min(+it.action.max_amt || 25000, 25000), qty: it.action.qty, note: String(it.action.note || '') },
      source: String(it.source || 'llm'),
    });
  }
  return { market_view: String(obj?.market_view || ''), items };
}

// 从 LLM 输出里抠 JSON: 优先 ```json fence, 退化找第一个平衡的 {...}
export function extractJson(text) {
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  const cand = fence ? fence[1] : text;
  const start = cand.indexOf('{');
  if (start < 0) throw new Error('输出无JSON');
  let depth = 0;
  for (let i = start; i < cand.length; i++) {
    if (cand[i] === '{') depth++;
    else if (cand[i] === '}') { depth--; if (!depth) return JSON.parse(cand.slice(start, i + 1)); }
  }
  throw new Error('JSON括号不平衡');
}

// 真实调用: claude -p (prompt 走 stdin); 超时 180s; 失败抛错由上层记洞降级
export function callClaude(prompt, { timeoutMs = 180000, cwd } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn('claude', ['-p'], {
      shell: true, windowsHide: true, cwd: cwd || process.cwd(),
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    let out = '', err = '';
    const timer = setTimeout(() => { child.kill(); reject(new Error('claude -p 超时')); }, timeoutMs);
    child.stdout.on('data', d => out += d);
    child.stderr.on('data', d => err += d);
    child.on('error', e => { clearTimeout(timer); reject(new Error('spawn失败(claude.cmd不在PATH?): ' + e)); });
    child.on('close', code => {
      clearTimeout(timer);
      if (code === 0 && out.trim()) resolve(out);
      else reject(new Error(`exit=${code} stderr=${err.slice(0, 200)} stdout=${out.slice(0, 200)}`));
    });
    child.stdin.end(prompt);
  });
}

// 统一入口: mock 或真调, 原始输出一律落 runDir/llm_raw/<tag>.txt 留痕
export async function runLlm(prompt, { mock, mockResponse, runDir, tag, hole, cwd }) {
  let raw, mode;
  if (mock) { raw = mockResponse; mode = 'mock'; }
  else {
    raw = await callClaude(prompt, { cwd });
    mode = 'real';
  }
  const dir = path.join(runDir, 'llm_raw');
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, tag + '.prompt.txt'), prompt);
  fs.writeFileSync(path.join(dir, tag + '.txt'), raw);
  const obj = extractJson(raw);   // 解析失败直接抛, 上层记洞=当日空仓
  return { obj, mode, rawFile: path.join(dir, tag + '.txt') };
}
