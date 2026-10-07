// indicators.mjs — 技术指标机械层(2026-10-07 建, 回应"LLM 看K线能力弱": 不让 LLM 看图, 算好喂结论)
// 输入: downloads/quotes/daily/<code>.json (kline.mjs 日线档) + 可选 klt60/30/15 分K档
// 计算: MA5/10/20/60 · MACD(12,26,9) · RSI14 · 量能(5日量比+20日分位) · 信号:
//   均线多排/空排 · MA5×MA10 金叉死叉(近3根) · MACD 金叉死叉+顶/底背离(价创20日极值而柱不创=背离)
//   收盘 vs MA20(破位/收复) · 20日箱体突破 · 60分K EMA20 方向(日内趋势)
// 用法: node scripts/quotes/indicators.mjs --codes 002714,600519 [--json]
// 输出: 每票一行结构化摘要(事实句, 零判断)——facts/06/05 直接引用; 判断归决策层(立法: 采集层不判断)
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > -1 ? process.argv[i + 1] : d; };
const JSON_OUT = process.argv.includes('--json');

const load = (dir, code) => {
    try { return JSON.parse(fs.readFileSync(path.join(ROOT, dir, code + '.json'), 'utf8')).klines; } catch { return null; }
};
const ma = (cs, n) => cs.length < n ? null : cs.slice(-n).reduce((a, b) => a + b, 0) / n;
function macd(cs) {
    if (cs.length < 35) return null;
    let ema12 = cs.slice(0, 12).reduce((a, b) => a + b, 0) / 12, ema26 = cs.slice(0, 26).reduce((a, b) => a + b, 0) / 26;
    const dif = [], dea = [];
    for (const c of cs) { ema12 += (c - ema12) * 2 / 13; ema26 += (c - ema26) * 2 / 27; dif.push(ema12 - ema26); }
    let d = dif.slice(0, 9).reduce((a, b) => a + b, 0) / 9;
    for (const x of dif) { d += (x - d) * 2 / 10; dea.push(d); }
    const hist = dif.map((x, i) => (x - dea[i]) * 2);
    return { dif, dea, hist };
}
function rsi(cs, n = 14) {
    if (cs.length < n + 1) return null;
    let up = 0, dn = 0;
    for (let i = cs.length - n; i < cs.length; i++) { const ch = cs[i] - cs[i - 1]; ch >= 0 ? up += ch : dn -= ch; }
    return dn === 0 ? 100 : 100 - 100 / (1 + (up / n) / (dn / n));
}
function analyze(code) {
    const d = load('downloads/quotes/daily', code);
    if (!d || d.length < 60) return { code, err: '日线档不足60根(先 kline.mjs --codes)' };
    const cs = d.map(x => x.c), vs = d.map(x => x.v), last = d.at(-1);
    const m5 = ma(cs, 5), m10 = ma(cs, 10), m20 = ma(cs, 20), m60 = ma(cs, 60);
    const M = macd(cs), r = rsi(cs);
    const v5 = ma(vs, 5), vAvg20 = vs.slice(-20);
    const vPct = vAvg20.filter(v => v <= vs.at(-1)).length / 20;  // 当日量在20日里的分位
    const sig = [];
    if (m5 && m10 && m20) {
        if (m5 > m10 && m10 > m20) sig.push('均线多排(5>10>20)');
        else if (m5 < m10 && m10 < m20) sig.push('均线空排(5<10<20)');
        const c5 = cs.at(-2) - ma(cs.slice(0, -1), 5), c10 = cs.at(-2) - ma(cs.slice(0, -1), 10);  // 简化: 昨日位
        if (c5 * c10 < 0 || (m5 > m10) !== (ma(cs.slice(0, -1), 5) > ma(cs.slice(0, -1), 10))) sig.push('MA5/10 交叉(近1根)');
    }
    if (cs.at(-1) > m20 && cs.at(-2) <= ma(cs.slice(0, -1), 20)) sig.push('收复20日线');
    if (cs.at(-1) < m20 && cs.at(-2) >= ma(cs.slice(0, -1), 20)) sig.push('跌破20日线');
    if (M) {
        const h = M.hist, n = h.length;
        if (h.at(-1) > 0 && h.at(-2) <= 0) sig.push('MACD金叉');
        if (h.at(-1) < 0 && h.at(-2) >= 0) sig.push('MACD死叉');
        const hi20 = Math.max(...cs.slice(-20)), lo20 = Math.min(...cs.slice(-20));
        if (cs.at(-1) >= hi20 * 0.999 && h.at(-1) < Math.max(...h.slice(-20))) sig.push('顶背离疑(价新高MACD柱缩)');
        if (cs.at(-1) <= lo20 * 1.001 && h.at(-1) > Math.min(...h.slice(-20))) sig.push('底背离疑(价新低MACD柱缩)');
    }
    const hi20p = Math.max(...cs.slice(-21, -1)), lo20p = Math.min(...cs.slice(-21, -1));
    if (cs.at(-1) > hi20p) sig.push('突破20日箱体顶');
    if (cs.at(-1) < lo20p) sig.push('跌破20日箱体底');
    let intraday = null;
    const k60 = load('downloads/quotes/klt60', code);
    if (k60 && k60.length >= 20) {
        const c60 = k60.map(x => x.c);
        let e = c60.slice(0, 20).reduce((a, b) => a + b, 0) / 20;
        for (const c of c60.slice(20)) e += (c - e) * 2 / 21;
        intraday = c60.at(-1) > e ? '60分K在EMA20上(日内偏多)' : '60分K在EMA20下(日内偏空)';
    }
    return { code, close: last.c, date: last.d,
        line: `${code} 收${last.c}(${last.d}) MA5=${m5?.toFixed(2)} MA10=${m10?.toFixed(2)} MA20=${m20?.toFixed(2)} MA60=${m60?.toFixed(2)}; `
            + `MACD柱=${M ? M.hist.at(-1).toFixed(3) : '?'} RSI14=${r ? r.toFixed(0) : '?'}; `
            + `量比5/20=${v5 && vAvg20 ? (v5 / (vAvg20.reduce((a, b) => a + b, 0) / 20)).toFixed(2) : '?'} 量分位=${(vPct * 100).toFixed(0)}%; `
            + (sig.length ? '信号: ' + sig.join('; ') : '信号: 无') + (intraday ? '; ' + intraday : '') };
}

const codes = (arg('codes', '') || '').split(',').map(s => s.trim()).filter(Boolean);
if (!codes.length) { console.error('用法: node scripts/quotes/indicators.mjs --codes 002714,600519 [--json]'); process.exit(1); }
const rows = codes.map(analyze);
if (JSON_OUT) console.log('JSON:' + JSON.stringify(rows));
else for (const r of rows) console.log(r.err ? `${r.code}: ${r.err}` : r.line);
