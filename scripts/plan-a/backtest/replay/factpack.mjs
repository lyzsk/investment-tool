// factpack.mjs — 人读版回测的事实采集助手(只做两件事: 日线 bars / 名称→代码)
// 2026-09-28 为 harness_human.py 而建: 行情复用 kline.mjs(分层缓存/多源/抖动/单位归一全在里面),
// 本文件只补一个仓库里缺的能力: 腾讯 smartbox 名称搜代码(带缓存+抖动, 防封铁律同 quote.mjs)。
// 用法:
//   node factpack.mjs bars    --codes=sh600127,sz000001 --from=2025-08-01 --to=2025-08-20 --out=<abs.json>
//   node factpack.mjs resolve --names=金健米业,闻泰转债 --out=<abs.json>
// 输出 bars: {code: [{t:'YYYYMMDD',o,h,l,c,vol}...]}; resolve: {name: {code,name,ok}}
import fs from 'fs';
import path from 'path';
import { ensureBars } from './kline.mjs';

const NAME_CACHE = 'C:/Users/admin/dev/investment-tool/scripts/plan-a/downloads/kline/name_cache.json';

const arg = k => (process.argv.find(a => a.startsWith(`--${k}=`)) || '').split('=').slice(1).join('=');
const sleep = ms => new Promise(r => setTimeout(r, ms));

// ---------- 名称→代码(腾讯 smartbox, GBK 响应, Node 全 ICU 直接 TextDecoder('gbk')) ----------
async function resolveOne(name) {
  const url = `https://smartbox.gtimg.cn/s3/?v=2&q=${encodeURIComponent(name)}&t=all`;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 8000);
  try {
    const r = await fetch(url, { signal: ctrl.signal, headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' } });
    let text = new TextDecoder('gbk').decode(await r.arrayBuffer());
    // 9/28 实测: 响应里名字有时是字面 \uXXXX 转义序列, 先反转义再匹配
    text = text.replace(/\\u([0-9a-fA-F]{4})/g, (_, h) => String.fromCharCode(parseInt(h, 16)));
    // 形如 v_hint="sh~600127~金健米业~jjmy~GP-A" (^ 分隔多条, 市场与代码是两个独立段); 名字完全相等才收
    const pick = (re) => { const m = re.exec(text); return m ? { code: m[1] + m[2], name: m[3] } : null; };
    const EXACT = /(sh|sz|bj)~(\d{6})~([^~^"]+)~/g;
    let m, first = null;
    while ((m = EXACT.exec(text))) {
      if (!first) first = { code: m[1] + m[2], name: m[3] };
      if (m[3] === name) return { code: m[1] + m[2], name: m[3], ok: true };
    }
    // 完全匹配落空 → 收第一条但标 fuzzy(转债名常带空格/全角差异)
    if (first) return { ...first, ok: 'fuzzy' };
    return { code: null, name, ok: false };
  } finally {
    clearTimeout(timer);
  }
}

// 第二源: 东财 suggest(smartbox 不索引转债, 9/28 实测 v_hint="N"); MktNum 1=沪 0=深
async function resolveOneEM(name) {
  const url = `https://searchapi.eastmoney.com/api/suggest/get?input=${encodeURIComponent(name)}&type=14&token=D43BF722C8E33BDDC73FB97D5F4A8D3C&count=5`;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 8000);
  try {
    const r = await fetch(url, { signal: ctrl.signal, headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' } });
    const data = (await r.json())?.QuotationCodeTable?.Data || [];
    const hit = data.find(d => d.Name === name) || data[0];
    if (!hit) return { code: null, name, ok: false };
    const mkt = String(hit.MktNum) === '1' ? 'sh' : String(hit.MktNum) === '0' ? 'sz' : null;
    if (!mkt) return { code: null, name, ok: false };
    return { code: mkt + hit.Code, name: hit.Name, ok: hit.Name === name ? true : 'fuzzy' };
  } finally {
    clearTimeout(timer);
  }
}

async function cmdResolve(out) {
  const names = arg('names').split(',').filter(Boolean);
  let cache = {};
  try { cache = JSON.parse(fs.readFileSync(NAME_CACHE, 'utf8')); } catch { /* 首次 */ }
  const result = {};
  for (const n of names) {
    if (cache[n] && cache[n].ok) { result[n] = cache[n]; continue; }
    await sleep(300 + Math.random() * 500);   // 抖动, 不打固定节拍
    try {
      result[n] = await resolveOne(n);
      if (!result[n].ok) { await sleep(300 + Math.random() * 500); result[n] = await resolveOneEM(n); }  // switch-case 转移
    } catch (e) {
      try { result[n] = await resolveOneEM(n); }
      catch (e2) { result[n] = { code: null, name: n, ok: false, err: String(e2.message || e2) }; }
    }
    if (result[n].ok) { cache[n] = result[n]; fs.mkdirSync(path.dirname(NAME_CACHE), { recursive: true }); fs.writeFileSync(NAME_CACHE, JSON.stringify(cache, null, 1)); }
  }
  fs.writeFileSync(out, JSON.stringify(result, null, 1));
  console.log(`resolve 完成: ${Object.values(result).filter(r => r.ok).length}/${names.length}`);
}

// ---------- 日线 bars(复用 kline.mjs 缓存与多源抓取) ----------
async function cmdBars(out) {
  const codes = arg('codes').split(',').filter(Boolean);
  const from = arg('from').replaceAll('-', ''), to = arg('to').replaceAll('-', '');
  const result = {};
  for (const code of codes) {
    const hole = [];
    try {
      const bars = await ensureBars(code, 'day', from, to, hole);
      result[code] = bars.filter(b => b.t.slice(0, 8) >= from && b.t.slice(0, 8) <= to)
        .map(b => ({ t: b.t.slice(0, 8), o: b.o, h: b.h, l: b.l, c: b.c, vol: b.vol ?? (b.v || 0) * 100 }));
      if (hole.length) result[code].holes = hole;
    } catch (e) {
      result[code] = { error: String(e.message || e) };   // 记洞不崩: 停牌/未上市/源全灭
    }
  }
  fs.writeFileSync(out, JSON.stringify(result, null, 1));
  console.log(`bars 完成: ${Object.values(result).filter(v => Array.isArray(v) && v.length).length}/${codes.length} 只有数据`);
}

const mode = process.argv[2];
if (mode === 'bars') await cmdBars(arg('out'));
else if (mode === 'resolve') await cmdResolve(arg('out'));
else { console.error('用法: factpack.mjs bars|resolve --...'); process.exit(1); }
