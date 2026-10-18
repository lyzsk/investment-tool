// similarity.mjs — A 级模拟账本 ↔ 真实导师 拟人度(2026-10-07 建 v1; 10/11 v2 重写)
// 用户令: "paper 尽可能都要能选出股, 至少要和拟人对象有个相似度百分比"; 10/11 定: 打分=拟人度(skill 链−对照链)×导师真人长期业绩。
// 两维口径(沿用 v1 权重):
//   ①持仓 Jaccard: 模拟账本 D 日收盘持仓 code 集 vs 导师 day_positions D 日持仓 code 集(剔逆回购)
//   ②操作对齐: 导师 D 日有操作的 code 集中, 模拟 D 日同票有成交的占比; 导师没动而模拟动了=0.5(主动冒进)
//   综合 = 0.6×① + 0.4×②
// v2 修(10/11 审查): ①成交日期取 trade id 前缀(原按不存在的 t.date 筛=操作维恒空) ②持仓按成交流水重建到 D 日收盘
//   (原用当前持仓, 补算历史日失真) ③双方空仓且都没动=无信号日, 不计入均值(原记 100%=把"一起休息"抬成"很像")
//   ④每个导师同时算 A-control 对照组的相似度, 给出差值 delta=skill−对照(skill 的真实拟人贡献) ⑤本地日期 ⑥同日重跑覆盖不追加
// 已知边界: 方向不计(买对卖只算"都动了这只"); UP 主(桃哥/天哥/卢本圆)无结构化真值账本, 不进对照
// 用法: node scripts/dfcf/paper/similarity.mjs [--date yyyymmdd] [--window 20]   (缺省=今天; matcher --eod 收盘后自动算前一交易日)
// 产物: <数据根>/similarity.csv(逐日, 同日覆盖) + similarity.json(report.mjs 读) + stdout 表
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const DIR = process.env.PAPER_ROOT ? path.resolve(process.env.PAPER_ROOT) : SCRIPT_DIR;
const ROOT = path.resolve(SCRIPT_DIR, '../../..');
const BOOKS = path.join(DIR, 'books');
const CSV = path.join(DIR, 'similarity.csv');
const JSON_OUT = path.join(DIR, 'similarity.json');
const LEDGERS = JSON.parse(fs.readFileSync(path.join(ROOT, 'scripts/tzzb/tzzb_ledgers.json'), 'utf8'));
const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > -1 ? process.argv[i + 1] : d; };
const DATE = arg('date', new Date().toLocaleDateString('sv-SE').replaceAll('-', ''));
const DDASH = `${DATE.slice(0, 4)}-${DATE.slice(4, 6)}-${DATE.slice(6, 8)}`;
const WINDOW = +(arg('window', 20));
const CONTROL = 'A-control';

// 对照对: A-<ledger> 账本 ↔ downloads/tzzb/<ledger>(仅正样本; 负样本=风控语料不开账本, 10/7 立法)
const PAIRS = LEDGERS.filter((l) => l.kind !== 'neg')
    .map((l) => ({ book: l.ledger === 'buchitudou0' ? 'A-cb' : 'A-' + l.ledger, dir: l.ledger, name: l.name }));
const isRepo = (x) => /^(204|1318)/.test(x.code || '') || /GC0|R-00/.test(x.name || '');

function realPositions(ledger) {
    try {
        const j = JSON.parse(fs.readFileSync(path.join(ROOT, 'downloads/tzzb', ledger, 'day_positions.json'), 'utf8'))[DATE];
        return j ? new Set((j.list || []).filter((x) => !isRepo(x) && +x.position_percent > 0).map((x) => x.code)) : null;
    } catch { return null; }   // 无该日真值=不计入
}
function realOpCodes(ledger) {
    const codes = new Set();
    try {
        for (const f of fs.readdirSync(path.join(ROOT, 'downloads/tzzb', ledger)).filter((f) => f.startsWith('position_change_p'))) {
            const list = JSON.parse(fs.readFileSync(path.join(ROOT, 'downloads/tzzb', ledger, f), 'utf8'))?.ex_data?.change_list || [];
            for (const t of list) if ((t.trans_date || '').slice(0, 10) === DDASH && t.stock_code) codes.add(t.stock_code);
        }
    } catch { /* 目录缺=无 */ }
    return codes;
}
// 模拟账本 D 日收盘状态: 成交流水(trade id 前缀=日期)重放到 D 日(账本自 10 万空仓起; 10/8 重建后成立)
function simState(book) {
    let b;
    try { b = JSON.parse(fs.readFileSync(path.join(BOOKS, book + '.json'), 'utf8')); } catch { return null; }
    const qty = {};
    for (const t of [...(b.trades || [])].sort((x, y) => String(x.id).localeCompare(String(y.id)))) {
        if (String(t.id).slice(0, 10) > DDASH) continue;
        qty[t.code] = (qty[t.code] || 0) + (t.side === 'BUY' ? t.qty : -t.qty);
    }
    const pos = new Set(Object.keys(qty).filter((c) => qty[c] > 0 && !isRepo({ code: c })));
    const ops = new Set((b.trades || []).filter((t) => String(t.id).slice(0, 10) === DDASH).map((t) => t.code));
    return { pos, ops };
}
function score(real, realOps, sim) {
    if (!real.size && !sim.pos.size && !realOps.size && !sim.ops.size) return null;   // 无信号日
    const un = new Set([...real, ...sim.pos]);
    const jac = un.size ? [...real].filter((c) => sim.pos.has(c)).length / un.size : 1;
    const op = realOps.size ? [...realOps].filter((c) => sim.ops.has(c)).length / realOps.size : (sim.ops.size ? 0.5 : 1);
    return { jac, op, comp: 0.6 * jac + 0.4 * op };
}

const ctrl = simState(CONTROL);
const rows = [];
for (const p of PAIRS) {
    const real = realPositions(p.dir);
    if (real === null) continue;
    const sim = simState(p.book);
    if (!sim) continue;
    const ops = realOpCodes(p.dir);
    const s = score(real, ops, sim), c = ctrl ? score(real, ops, ctrl) : null;
    rows.push({ date: DATE, book: p.book, 导师: p.dir, name: p.name, real_n: real.size, sim_n: sim.pos.size,
        jac: s ? +s.jac.toFixed(4) : '', op: s ? +s.op.toFixed(4) : '', comp: s ? +s.comp.toFixed(4) : '',
        ctrl: c ? +c.comp.toFixed(4) : '', delta: s && c ? +(s.comp - c.comp).toFixed(4) : '' });
}

// csv: 同日覆盖(旧版逐行追加, 重跑出重复行)
const HEAD = 'date,book,导师,real_n,sim_n,jac,op,comp,ctrl,delta';
let lines = [];
try { lines = fs.readFileSync(CSV, 'utf8').trim().split('\n').slice(1).filter((l) => l && !l.startsWith(DATE + ',') && l.split(',').length === 10); } catch { /* 首日 */ }
lines.push(...rows.map((r) => [r.date, r.book, r.导师, r.real_n, r.sim_n, r.jac, r.op, r.comp, r.ctrl, r.delta].join(',')));
lines.sort();
fs.writeFileSync(CSV, [HEAD, ...lines].join('\n') + '\n', 'utf8');

// 滚动均值(只计有信号日) → similarity.json 给报告
const hist = lines.map((l) => { const f = l.split(','); return { date: f[0], book: f[1], comp: f[7] === '' ? null : +f[7], ctrl: f[8] === '' ? null : +f[8] }; });
const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);
const summary = PAIRS.map((p) => {
    const h = hist.filter((x) => x.book === p.book).slice(-WINDOW);
    const sc = h.filter((x) => x.comp != null), both = h.filter((x) => x.comp != null && x.ctrl != null);
    return { book: p.book, name: p.name, days: sc.length, comp: mean(sc.map((x) => x.comp)),
        ctrl: mean(both.map((x) => x.ctrl)), delta: both.length ? mean(both.map((x) => x.comp - x.ctrl)) : null };
});
fs.writeFileSync(JSON_OUT, JSON.stringify({ updated: DATE, window: WINDOW, summary }, null, 1));

const pct = (x) => (x == null || x === '' ? '—' : (x * 100).toFixed(1) + '%');
console.log(`拟人度 @${DATE}(滚动${WINDOW}日, 无信号日不计):`);
for (const r of rows) {
    const s = summary.find((x) => x.book === r.book);
    console.log(`  ${r.book.padEnd(26)} 当日=${pct(r.comp)} 对照=${pct(r.ctrl)} 差=${pct(r.delta)} | 滚动 ${pct(s.comp)} 对照 ${pct(s.ctrl)} 差 ${pct(s.delta)} (${s.days}日)`);
}
if (!rows.length) console.log('  (本日无导师真值——非交易日或 tzzb day_positions 未覆盖)');
