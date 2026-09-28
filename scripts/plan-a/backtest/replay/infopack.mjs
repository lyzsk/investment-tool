// infopack.mjs — T-1 晚信息包组装(只做这一件事)
//
// info-cutoff 铁律: T 日决策只用 ≤T-1 晚的信息。本模块所有输入按日期硬过滤:
//   ① stocks md 只读 T-1(及更早)的文件 —— 由调用方传入的日期决定, 本模块不猜
//   ② rules_seed.json 按 learned_before 过滤(cutoff 口径见 ruleUsable)
//   ③ kline 历史摘要只取 ≤T-1 收盘的 bar
// 输出 = 各组 planner 的统一输入; LLM 组(C/D)的 prompt 也由它拼装, 保证"输入同源"。
import fs from 'fs';
import path from 'path';
import { ensureBars, pickGranularity } from './kline.mjs';

const STOCKS_DIR = 'C:/Users/admin/dev/investment-tool/stocks';
const RULES_FILE = 'C:/Users/admin/dev/investment-tool/scripts/taoge-paper/rules_seed.json';

// ---------- 日期工具 ----------
const p2 = n => String(n).padStart(2, '0');
export const dashOf = d => `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`;   // 20260916 → 2026-09-16
export const compactOf = s => s.replaceAll('-', '');                                // 2026-09-16 → 20260916

// 全 universe 交易日历 = 所有 stocks/20XXSY/*.md 文件名(每日 md 只在交易日产出)
export function tradingCalendar() {
  const out = [];
  for (const dir of fs.readdirSync(STOCKS_DIR).filter(d => /^2\d{3}S\d$/.test(d))) {
    for (const f of fs.readdirSync(path.join(STOCKS_DIR, dir))) {
      const m = f.match(/^(\d{4}-\d{2}-\d{2})\.md$/);
      if (m) out.push({ date: compactOf(m[1]), file: path.join(STOCKS_DIR, dir, f) });
    }
  }
  out.sort((a, b) => a.date < b.date ? -1 : 1);
  return out;
}

// ---------- md 桃哥小节解析 ----------
// 结构(见 stocks/2026S3/2026-09-14.md):
//   ### 桃哥 > 转写原文(blockquote) > #### 画面(视觉真值, 带涨跌幅) > #### 解读(结构化 bullet)
// 解析只依赖 #### 标题与 bullet 前缀, 不依赖具体措辞; 解析不出的字段留空记洞, 不编造。
export function parseTaogeSection(mdText, hole) {
  const sec = mdText.match(/### 桃哥([\s\S]*?)(?=\n### |\n## (?!#)|$)/);
  if (!sec) return null;
  const body = sec[1];
  const grab = h => {
    const m = body.match(new RegExp('#### ' + h + '([\\s\\S]*?)(?=\\n#### |$)'));
    return m ? m[1].trim() : '';
  };
  // 画面: "瑞尔特(002790) 8.38(-9.99%)" / "培育钻石 2580.39(+4.42%)" —— 代码可能只有6位数字
  const vision = [];
  for (const mm of grab('画面').matchAll(/([一-龥A-Za-z][一-龥A-Za-z0-9\-]*?)(?:\((\d{6})\))? (\d+(?:\.\d+)?)\(([+-]\d+(?:\.\d+)?)%\)/g)) {
    vision.push({ name: mm[1], code: mm[2] ? normCode(mm[2]) : null, price: +mm[3], pct: +mm[4] });
  }
  const jd = grab('解读');
  // 转写原文(blockquote 行): 2026-09-14 之前的 md 没有结构化解读小节, 转写原文是 C/D 组唯一的信息源
  const transcript = body.split('\n').filter(l => l.startsWith('>')).map(l => l.replace(/^>\s?/, '')).join('\n').trim();
  // 提及个股: "- 太极实业(sh600667) · 看多 · 已买入(早盘)（转写别名: 太极） — 备注 【桃哥: 持有】"
  // tags 段可含半角/全角括号注释(如"已买入(早盘)"), 故先粗抓到 " — " 分界, 再剥离转写别名后切 ·
  const mentions = [];
  const mentionRe = /^\s*-\s+([一-龥A-Za-z][一-龥A-Za-z0-9]*?)\((?:sh|sz)?(\d{6})\)\s*·\s*(.+?)\s*(?:—\s*(.*))?$/gm;
  for (const mm of jd.matchAll(mentionRe)) {
    const tail = mm[4] || '';
    const tagBlob = mm[3].replace(/（转写别名[^）]*）/g, '');
    mentions.push({
      name: mm[1], code: normCode(mm[2]),
      tags: tagBlob.split('·').map(s => s.trim()).filter(Boolean),
      held: /【桃哥:\s*持有】/.test(tail) || /【桃哥:\s*持有】/.test(mm[3]),
      note: tail.replace(/【桃哥:[^】]*】/g, '').trim(),
      raw: mm[0].trim(),
    });
  }
  const bullet = k => {
    const m = jd.match(new RegExp('- \\*\\*' + k + '\\*\\*[:：]\\s*(.+)'));
    return m ? m[1].trim() : '';
  };
  // 明日策略里的 "关注 X(sh600127): ...、Y(sz002714): ..." 结构化提取
  const strategy = bullet('明日策略');
  const focus = [], avoid = [];
  const stratFocus = strategy.match(/关注\s*(.*?)(?:;\s*避开|$)/);
  const stratAvoid = strategy.match(/避开\s*(.*)$/);
  for (const mm of (stratFocus?.[1] || '').matchAll(/([一-龥A-Za-z][一-龥A-Za-z0-9]*?)\((?:sh|sz)?(\d{6})\)/g))
    focus.push({ name: mm[1], code: normCode(mm[2]) });
  for (const mm of (stratAvoid?.[1] || '').matchAll(/([一-龥A-Za-z][一-龥A-Za-z0-9]*?)(?:\((?:sh|sz)?(\d{6})\))?(?:、|$|:)/g))
    if (mm[2]) avoid.push({ name: mm[1], code: normCode(mm[2]) });
  if (!mentions.length && hole) hole('解读无提及个股(格式漂移?)', jd.slice(0, 120));
  return {
    vision,
    mentions,
    transcript,                                // ASR 转写原文(无解读小节时的兜底信息源)
    market_view: bullet('大盘判断'),
    his_ops: bullet('桃哥今日操作'),          // 他自述的当日操作(A组照抄源/E组对照真值)
    strategy, focus, avoid,
    style_rules: bullet('风格规则'),
    raw_jiedu: jd,
  };
}

// 代码归一: 6位数字 → sh/sz 前缀(6/9 开头=沪, 0/2/3 开头=深)
export function normCode(c) {
  if (/^(sh|sz)/.test(c)) return c;
  return (/^[69]/.test(c) ? 'sh' : 'sz') + c;
}

export function loadMd(dateCompact, hole) {
  const dash = dashOf(dateCompact);
  for (const dir of fs.readdirSync(STOCKS_DIR).filter(d => /^2\d{3}S\d$/.test(d))) {
    const f = path.join(STOCKS_DIR, dir, dash + '.md');
    if (fs.existsSync(f)) return fs.readFileSync(f, 'utf8');
  }
  hole?.('md缺失', dash);
  return null;
}

// ---------- 规则过滤 ----------
// ruleUsable 口径(立法 §4): 信息包里的规则必须 learned_before ≤ T-1。
// 注意: rules_seed.json 自己的 _meta 写的是"该日期之前的决策不得使用"(= T ≥ learned_before 可用)。
// 两种口径差一天(例: R9 learned_before=2026-09-16, T-1 口径下 T=20260916 不可用, T 口径下可用,
// 而 pilot-2week 在 9/16 用了 R9 并赚回 +6.5%)。默认立法口径 T-1, --rule-cutoff T 可切换做消融。
export function loadRules() {
  return JSON.parse(fs.readFileSync(RULES_FILE, 'utf8')).rules;
}
// prevDate = T-1 交易日; cutoff='T-1'(立法默认): 规则 learned_before ≤ prevDate 才进信息包
//            cutoff='T'(消融):           规则 learned_before ≤ tradeDate 即可(=rules_seed _meta 原义)
export function rulesFor(pack, prevDate, cutoff) {
  const bound = cutoff === 'T' ? pack.date : prevDate;
  return loadRules().filter(r => compactOf(r.learned_before) <= bound);
}

// ---------- kline 历史摘要(截止 T-1 收盘, 防未来函数: 硬过滤 t < T) ----------
export async function klineDigest(codes, prevDate, hole, maxBars = 5) {
  const out = {};
  for (const code of [...new Set(codes)]) {
    try {
      const bars = await ensureBars(code, 'day', '202509010000', prevDate + '2359', hole);
      const hist = bars.filter(b => b.t <= prevDate + '2359').slice(-maxBars);
      if (!hist.length) { hole?.('digest无历史bar', code + '@' + prevDate); continue; }
      const last = hist[hist.length - 1];
      const prev = hist.length > 1 ? hist[hist.length - 2] : null;
      out[code] = {
        last_close: last.c,
        last_pct: prev ? +((last.c / prev.c - 1) * 100).toFixed(2) : null,
        bars: hist.map(b => ({ d: b.t.slice(0, 8), o: b.o, h: b.h, l: b.l, c: b.c })),
      };
    } catch (e) { hole?.('digest抓取失败', code + ' ' + String(e).slice(0, 100)); }
  }
  return out;
}

// ---------- 总装: T 日信息包(输入全部 ≤ T-1 晚) ----------
export async function buildInfoPack(date, prevDate, { ruleCutoff = 'T-1', hole } = {}) {
  const mdText = loadMd(prevDate, hole);
  const taoge = mdText ? parseTaogeSection(mdText, hole) : null;
  if (!taoge) hole?.('桃哥小节缺失', prevDate);
  const rules = rulesFor({ date }, prevDate, ruleCutoff);
  // 候选票: 优先解读提及个股; 无解读小节的老 md 退化用画面真值里的代码
  const candidateCodes = [
    ...(taoge?.mentions || []).map(m => m.code),
    ...(taoge?.focus || []).map(f => f.code),
    ...((taoge?.mentions?.length ? [] : (taoge?.vision || []).filter(v => v.code).map(v => v.code))),
    'sh000001',
  ];
  const digest = await klineDigest(candidateCodes, prevDate, hole);
  return {
    date, prev_date: prevDate, rule_cutoff: ruleCutoff,
    gran: pickGranularity(date),
    taoge, rules, kline: digest,
    info_cutoff: prevDate + '2359',   // 显式写出信息边界
  };
}
