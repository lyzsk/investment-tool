// 批量抓腾讯 m5 K线缓存到本地: node fetch_m5.mjs sh600127 sz002790 ...
// 输出 downloads/kline/<code>_m5.json  { code, bars: [{t, o, c, h, l, vol}] }
import fs from "fs";
import path from "path";

const OUT = "C:/Users/admin/dev/investment-tool/scripts/bilibili-taoge/downloads/kline";
fs.mkdirSync(OUT, { recursive: true });

const codes = process.argv.slice(2);
for (const code of codes) {
  const url = `https://ifzq.gtimg.cn/appstock/app/kline/mkline?param=${code},m5,,640`;
  const r = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0" } });
  const j = await r.json();
  const o = j.data?.[code];
  if (!o?.m5) { console.log(code, "FAIL", j.msg || "no m5"); continue; }
  const bars = o.m5.map(a => ({
    t: a[0], o: +a[1], c: +a[2], h: +a[3], l: +a[4], vol: +a[5],
  }));
  fs.writeFileSync(path.join(OUT, `${code}_m5.json`), JSON.stringify({ code, bars }));
  console.log(code, "bars=", bars.length, bars[0].t, "->", bars[bars.length - 1].t);
  await new Promise(r2 => setTimeout(r2, 400));
}
