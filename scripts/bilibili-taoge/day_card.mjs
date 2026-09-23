// 日内回放卡片: node day_card.mjs <date:20260902> <code1> <code2> ...
// 每只股票输出: 前收, 开盘, 前30分钟 bars, 日内高/低点及时间, 收盘, 全天量
import fs from "fs";
const [date, ...codes] = process.argv.slice(2);
const K = "C:/Users/admin/dev/investment-tool/scripts/bilibili-taoge/downloads/kline";
for (const code of codes) {
  let bars;
  try { bars = JSON.parse(fs.readFileSync(`${K}/${code}_m5.json`, "utf-8")).bars; }
  catch { console.log(code, "no data"); continue; }
  const day = bars.filter(b => b.t.startsWith(date));
  if (!day.length) { console.log(`${code} ${date}: 无数据(停牌/未上市)`); continue; }
  const di = bars.indexOf(day[0]);
  const pc = di > 0 ? bars[di - 1].c : null;
  const hi = day.reduce((a, b) => b.h > a.h ? b : a);
  const lo = day.reduce((a, b) => b.l < a.l ? b : a);
  const pct = v => pc ? ((v / pc - 1) * 100).toFixed(1) + "%" : "-";
  console.log(`### ${code} ${date} 前收${pc} 开${day[0].o}(${pct(day[0].o)}) 收${day[day.length-1].c}(${pct(day[day.length-1].c)}) 高${hi.h}@${hi.t.slice(8)} 低${lo.l}@${lo.t.slice(8)}`);
  // 前 6 根 + 高低点附近 + 尾盘 2 根
  const show = new Set([0,1,2,3,4,5, day.indexOf(hi), day.indexOf(lo), day.length-2, day.length-1]);
  for (let i = 0; i < day.length; i++) {
    if (!show.has(i)) continue;
    const b = day[i];
    console.log(`  ${b.t.slice(8)} o${b.o} h${b.h} l${b.l} c${b.c} v${Math.round(b.vol)} ${pct(b.c)}`);
  }
}
