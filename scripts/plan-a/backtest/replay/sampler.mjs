// sampler.mjs — 样本日采样器(只做这一件事: 产出 sample_days.json)
//
// 用途定位(2026-09-27 用户拍板): 留给后续 2025-10-01~2026-09-26 全宇宙(~230天)抽样用;
// 首跑区间 2026-06-29~2026-09-26 是全量不抽样, 本模块该区间不参与。
//
// 采样规则(立法):
//   宇宙 = 2025-10-01 ~ 2026-09-26 中, 存在 T-1 晚桃哥 md 小节的交易日
//   每月 3-5 普通日 + 全部极端日; 首跑目标 ~40 天
//   极端日定义: 上证单日 |涨跌| ≥ 2% 或 持仓票(T-1 md【桃哥: 持有】)单日 |涨跌| ≥ 10%
//     —— 持仓票涨跌幅的数据源代理: T 日 md 画面真值里的百分比(免全量 kline), 报告里标注此代理
import fs from 'fs';
import { tradingCalendar, parseTaogeSection } from './infopack.mjs';
import { pickGranularity } from './kline.mjs';

export function sampleDays({ from = '20251001', to = '20260926', perMonth = 3, shDailyPct = {}, hole = () => {} }) {
  const cal = tradingCalendar();   // [{date(YYYYMMDD), file}] 已排序
  // 预解析: 哪些日期有桃哥小节
  const hasTaoge = new Map();
  for (const d of cal) {
    if (d.date < from || d.date > to) continue;
    const txt = fs.readFileSync(d.file, 'utf8');
    hasTaoge.set(d.date, /### 桃哥/.test(txt) ? parseTaogeSection(txt, hole) : null);
  }
  const dates = cal.map(d => d.date).filter(d => d >= from && d <= to);
  // T 入宇宙 ⇔ T-1(日历前一日)有桃哥小节; 附上证当日涨跌幅(主源 kline)
  const universe = [];
  for (let i = 1; i < dates.length; i++) {
    if (hasTaoge.get(dates[i - 1])) universe.push({ date: dates[i], prev: dates[i - 1], shPct: shDailyPct[dates[i]] ?? null });
  }
  // 极端日判定
  const picked = new Map();   // date → {reasons:[]}
  const byMonth = new Map();
  for (const u of universe) {
    const month = u.date.slice(0, 6);
    (byMonth.get(month) || byMonth.set(month, []).get(month)).push(u);
    const reasons = [];
    // 上证涨跌幅: 主源=sh000001 日线 kline(调用方预置 shDailyPct); 兜底=T日md画面"上证"条目
    const mdT = hasTaoge.get(u.date);
    const shPct = u.shPct ?? mdT?.vision?.find(v => /上证/.test(v.name))?.pct ?? null;
    if (shPct != null && Math.abs(shPct) >= 2) reasons.push(`extreme_sh:${shPct >= 0 ? '+' : ''}${shPct}%`);
    // 持仓票: T-1 持有集合 ∩ T 日画面 |pct|≥10
    const held = new Set((hasTaoge.get(u.prev)?.mentions || []).filter(m => m.held).map(m => m.code));
    for (const v of mdT?.vision || []) {
      if (v.code && held.has(v.code) && Math.abs(v.pct) >= 10)
        reasons.push(`extreme_stock:${v.name}:${v.pct >= 0 ? '+' : ''}${v.pct}%`);
    }
    if (reasons.length) picked.set(u.date, { ...u, reasons });
  }
  // 每月普通日与极端日是加法关系(立法: "每月 3-5 普通日 + 全部极端日"), 极端日不占普通日名额
  for (const [month, list] of [...byMonth.entries()].sort()) {
    const pool = list.filter(u => !picked.has(u.date));
    let need = Math.min(perMonth, pool.length);
    if (!need) continue;
    const step = pool.length / need;
    for (let k = 0; k < need; k++) {
      const u = pool[Math.min(pool.length - 1, Math.floor((k + 0.5) * step))];
      if (!picked.has(u.date)) picked.set(u.date, { ...u, reasons: ['normal'] });
    }
  }
  // 输出
  return [...picked.values()].sort((a, b) => a.date < b.date ? -1 : 1).map(u => ({
    date: u.date, prev_date: u.prev, gran: pickGranularity(u.date), reasons: u.reasons,
  }));
}
