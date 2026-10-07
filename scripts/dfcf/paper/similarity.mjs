// similarity.mjs — A 级模拟账本 ↔ 真实导师 相似度百分比(2026-10-07 建, paper 两级制核心度量)
// 用户令: "paper 尽可能都要能选出股, 至少要和拟人对象有个相似度百分比"。
// 两维口径(v1, 10/7):
//   ①持仓 Jaccard: 模拟账本当日持仓 code 集 vs 导师 day_positions 当日持仓 code 集(剔逆回购);
//     双空=1.0, 单边空=0(空仓对满仓=完全不像)
//   ②操作对齐: 导师当日有操作的 code 集(position_change 日汇总)中, 模拟当日同票有动作(trades)的占比;
//     双方都无操作=1.0(一起休息也是像)
//   综合 = 0.6×① + 0.4×②; 滚动 window 日均值(仅计真实数据存在的日子)。
// 已知边界(v1 诚实档): ①方向不计(买对卖只算"都动了这只") ②历史 EOD 持仓不可重建——逐日追加累计, 起跑日=10/8
//   ③bilibili UP 无结构化真值账本, 不进对照(A-taoge/A-qushitiange/A-lubenyuan 的相似度待 vision 持仓真值另立口径)
// 用法: node scripts/dfcf/paper/similarity.mjs [--date yyyymmdd] [--window 20]
// 产物: scripts/dfcf/paper/similarity.csv(逐日追加) + stdout 表
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const DIR = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(DIR, '..', '..', '..');
const BOOKS = path.join(DIR, 'books');
const LEDGERS = JSON.parse(fs.readFileSync(path.join(ROOT, 'scripts/tzzb/tzzb_ledgers.json'), 'utf8'));
const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > -1 ? process.argv[i + 1] : d; };
const DATE = arg('date', new Date().toISOString().slice(0, 10).replaceAll('-', ''));
const WINDOW = +(arg('window', 20));
const CSV = path.join(DIR, 'similarity.csv');

// 对照对: A-<ledger> 账本 ↔ downloads/tzzb/<ledger>(仅正样本有账本; 负样本不开账本=风控规则语料, 10/7 立法)
const PAIRS = LEDGERS.filter(l => l.kind !== 'neg')
    .map(l => ({ book: l.ledger === 'buchitudou0' ? 'A-cb' : 'A-' + l.ledger, dir: l.ledger, name: l.name }));

const isRepo = x => /^(204|1318)/.test(x.code || '') || /GC0|R-00/.test(x.name || '');

function realPositions(ledger, d8) {
    try {
        const j = JSON.parse(fs.readFileSync(path.join(ROOT, 'downloads/tzzb', ledger, 'day_positions.json'), 'utf8'))[d8];
        return new Set((j?.list || []).filter(x => !isRepo(x) && +x.position_percent > 0).map(x => x.code));
    } catch { return null; }   // 无该日真值=不计入
}
function realOpCodes(ledger, dDash) {
    const codes = new Set();
    try {
        for (const f of fs.readdirSync(path.join(ROOT, 'downloads/tzzb', ledger)).filter(f => f.startsWith('position_change_p'))) {
            const list = JSON.parse(fs.readFileSync(path.join(ROOT, 'downloads/tzzb', ledger, f), 'utf8'))?.ex_data?.change_list || [];
            for (const t of list) if ((t.trans_date || '').slice(0, 10) === dDash && t.stock_code) codes.add(t.stock_code);
        }
    } catch { /* 目录缺=无 */ }
    return codes;
}
function simState(book, dDash) {
    const b = JSON.parse(fs.readFileSync(path.join(BOOKS, book + '.json'), 'utf8'));
    const pos = new Set(Object.keys(b.positions || {}).filter(c => !isRepo({ code: c })));
    const ops = new Set((b.trades || []).filter(t => (t.date || t.ts || '').startsWith(dDash)).map(t => t.code));
    return { pos, ops };
}

const rows = [];
for (const p of PAIRS) {
    const real = realPositions(p.dir, DATE);
    if (real === null) continue;
    const { pos, ops } = simState(p.book, DATE.slice(0, 4) + '-' + DATE.slice(4, 6) + '-' + DATE.slice(6, 8));
    const realOps = realOpCodes(p.dir, DATE.slice(0, 4) + '-' + DATE.slice(4, 6) + '-' + DATE.slice(6, 8));
    const un = new Set([...real, ...pos]);
    const inter = [...real].filter(c => pos.has(c)).length;
    const jac = un.size === 0 ? 1 : inter / un.size;
    const opAlign = realOps.size === 0 ? (ops.size === 0 ? 1 : 0.5)  // 他不动我动=半分(主动冒进), 都不动=1
        : [...realOps].filter(c => ops.has(c)).length / realOps.size;
    const comp = +(0.6 * jac + 0.4 * opAlign).toFixed(4);
    rows.push({ date: DATE, book: p.book, 导师: p.dir, pos_n: real.size, sim_n: pos.size,
        jac: +jac.toFixed(4), opAlign: +opAlign.toFixed(4), composite: comp });
}
// 追加 + 滚动
let hist = [];
try { hist = fs.readFileSync(CSV, 'utf8').trim().split('\n').slice(1).map(l => { const f = l.split(','); return { date: f[0], book: f[1], 导师: f[2], composite: +f[7] }; }); } catch { /* 首日 */ }
fs.appendFileSync(CSV, rows.map(r => [r.date, r.book, r.导师, r.pos_n, r.sim_n, r.jac, r.opAlign, r.composite].join(',')).join('\n') + (rows.length ? '\n' : ''), 'utf8');
console.log(`相似度 @${DATE} (滚动${WINDOW}日=综合均值 | 起跑10/8, 逐日长肉):`);
for (const r of rows) {
    const w = [...hist.filter(h => h.book === r.book), ...rows.filter(x => x.book === r.book)]
        .slice(-WINDOW).map(h => h.composite);
    const roll = w.length ? (w.reduce((a, b) => a + b, 0) / w.length * 100).toFixed(1) + '%' : '—';
    console.log(`  ${r.book} ↔ ${r.导师}: 持仓J=${(r.jac * 100).toFixed(0)}% (${r.sim_n}/${r.pos_n}支) 操作对齐=${(r.opAlign * 100).toFixed(0)}% 综合=${(r.composite * 100).toFixed(1)}% | 滚动=${roll}`);
}
if (!rows.length) console.log('  (本日无真实持仓真值的对照对——非交易日或 day_positions 未覆盖)');
