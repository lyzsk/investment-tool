// quote.mjs — 行情源抽象: 腾讯批量快照(主) / 新浪(备) / 东财push2(兜底)
// 设计原则(用户指令 2026-09-21): ①数据源=可穷举的switch-case故障转移链, 每种死法都有下一手,
// 不许if-else补丁摞补丁 ②请求频率必须带随机抖动, 绝不打固定节拍(防IP封/不像爬虫)
// ③这些脚本最终由Java进程调用, 失败模式要在脚本内闭环, 不把异常抛给上层擦屁股。
// 快照源: 每源连续失败3次切下一个; 全部失败抛错由调用方记 holes。
// 快照原始串由调用方落 raw(这里只返回解析结果+raw)。
import fs from 'fs';
import path from 'path';

const UA = { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' };

async function fetchBuf(url, headers = {}, timeoutMs = 8000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { headers: { ...UA, ...headers }, signal: ctrl.signal });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return Buffer.from(await r.arrayBuffer());
  } finally { clearTimeout(t); }
}

// ---- 腾讯批量快照 ----
// v_sh600000="51~浦发银行~600000~price~prevclose~open~vol(手)~外盘~内盘~买一...~time~...~amount(万)~..."
async function tencent(codes) {
  const buf = await fetchBuf('https://qt.gtimg.cn/q=' + codes.join(','));
  const text = new TextDecoder('gbk').decode(buf);
  const out = {};
  for (const line of text.split(';')) {
    const m = line.match(/v_([a-z]{2}\d{6})="([^"]*)"/);
    if (!m) continue;
    const f = m[2].split('~');
    if (f.length < 38) continue;
    out[m[1]] = {
      code: m[1], name: f[1],
      price: +f[3] || null, prevClose: +f[4] || null, open: +f[5] || null,
      volHands: +f[6] || 0,                 // 当日累计成交量(手)
      time: f[30] || '',                    // YYYYMMDDHHmmss
      high: +f[33] || null, low: +f[34] || null,
      amount: (+f[37] || 0) * 10000,        // 万 → 元
    };
  }
  if (!Object.keys(out).length) throw new Error('tencent: 解析为空');
  return { quotes: out, raw: text };
}

// ---- 新浪批量快照(备, 需Referer) ----
// var hq_str_sh600000="name,open,prevclose,price,high,low,bid,ask,vol(股),amount(元),...,date,time";
async function sina(codes) {
  const buf = await fetchBuf('https://hq.sinajs.cn/list=' + codes.join(','),
    { Referer: 'https://finance.sina.com.cn' });
  const text = new TextDecoder('gbk').decode(buf);
  const out = {};
  for (const line of text.split(';')) {
    const m = line.match(/hq_str_([a-z]{2}\d{6})="([^"]*)"/);
    if (!m || !m[2]) continue;
    const f = m[2].split(',');
    out[m[1]] = {
      code: m[1], name: f[0],
      open: +f[1] || null, prevClose: +f[2] || null, price: +f[3] || null,
      high: +f[4] || null, low: +f[5] || null,
      volHands: (+f[8] || 0) / 100, amount: +f[9] || 0,
      time: (f[30] || '').replaceAll('-', '') + (f[31] || '').replaceAll(':', ''),
    };
  }
  if (!Object.keys(out).length) throw new Error('sina: 解析为空');
  return { quotes: out, raw: text };
}

// ---- 东财push2批量(兜底, 限流狠) ----
async function eastmoney(codes) {
  const secids = codes.map(c => (c.startsWith('sh') ? '1.' : '0.') + c.slice(2)).join(',');
  const buf = await fetchBuf('https://push2.eastmoney.com/api/qt/ulist.np/get?secids='
    + secids + '&fields=f12,f14,f2,f3,f5,f6,f15,f16,f17,f18');
  const text = buf.toString('utf8');
  const j = JSON.parse(text);
  const out = {};
  for (const d of (j.data && j.data.diff) || []) {
    const code = (d.f12.startsWith('6') ? 'sh' : 'sz') + d.f12;
    out[code] = {
      code, name: d.f14,
      price: d.f2 === '-' ? null : d.f2, prevClose: d.f18 === '-' ? null : d.f18,
      open: d.f17 === '-' ? null : d.f17, high: d.f15, low: d.f16,
      volHands: d.f5 || 0, amount: d.f6 || 0,
      time: '',   // push2 ulist 不带时间戳, 用本地钟
    };
  }
  if (!Object.keys(out).length) throw new Error('eastmoney: 解析为空');
  return { quotes: out, raw: text };
}

const SOURCES = { tencent, sina, eastmoney };

// 带备选切换的行情客户端
export function makeQuoteClient(order = ['tencent', 'sina', 'eastmoney'], onEvent = () => {}) {
  let cur = 0, fails = 0;
  return async function getQuotes(codes) {
    for (let tried = 0; tried < order.length; tried++) {
      const name = order[cur];
      try {
        const r = await SOURCES[name](codes);
        fails = 0;
        return { ...r, source: name };
      } catch (e) {
        fails++;
        onEvent('quote_fail', { source: name, err: String(e).slice(0, 120), fails });
        if (fails >= 3) { cur = (cur + 1) % order.length; fails = 0; onEvent('quote_switch', { to: order[cur] }); }
        else break; // 未满3次, 下轮重试同源
      }
    }
    throw new Error('所有行情源不可用');
  };
}

// mkline 权威bar(仅启动回补与收盘对账用): 返回 [{t,o,h,l,c,v,amount}]
// 2026-09-21: 腾讯 mkline 服务端报错 {"code":11,"Can't load controller:MklineController"} 疑下线 → 加新浪兜底
export async function fetchM5(code, count = 48) {
  try {
    const buf = await fetchBuf(`https://ifzq.gtimg.cn/appstock/app/mkline/mkline?param=${code},m5,,${count}`);
    const j = JSON.parse(buf.toString('utf8'));
    const arr = (j.data && j.data[code] && j.data[code].m5) || [];
    if (arr.length) {
      // b[8] 不一定有成交额, 缺省用 量(手)×100×收盘价 估算
      return arr.map(b => ({ t: b[0], o: +b[1], c: +b[2], h: +b[3], l: +b[4], v: +b[5],
        amount: b[8] ? +b[8] : (+b[5]) * 100 * (+b[2]) }));
    }
  } catch {}
  // 备: 新浪 getKLineData(scale=5, datalen≤1023, 需Referer; volume单位=股, amount=元)
  const buf = await fetchBuf(
    `https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_x=/CN_MarketDataService.getKLineData?symbol=${code}&scale=5&ma=no&datalen=${Math.min(count, 1023)}`,
    { Referer: 'https://finance.sina.com.cn' });
  const t = buf.toString('utf8');
  const arr = JSON.parse(t.slice(t.indexOf('([') + 1, t.lastIndexOf(')')));
  return arr.map(b => ({ t: b.day.replace(/[-: ]/g, '').slice(0, 12), o: +b.open, c: +b.close,
    h: +b.high, l: +b.low, v: Math.round(+b.volume / 100), amount: +b.amount }));
}

export function appendRaw(file, obj) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.appendFileSync(file, JSON.stringify(obj) + '\n');
}
