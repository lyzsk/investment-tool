#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_klines.py — 个股多周期K线统一拉取（多源 switch-case 故障切换）
用法: python fetch_klines.py <code> [--periods day,60,30,15,5] [--n 60] [--save]
  code: 带市场前缀 sh/sz，如 sz002714 / sh601091
  periods: day=日K(前复权), 60/30/15/5=分钟K
输出: 打印各周期最近几根的紧凑文本 + --save 时写 scripts/k3-inv/data/klines/<code>_<period>.json
数据源优先级(switch-case):
  day   : 腾讯fqkline(qfq) -> 东财push2his(klt=101) -> 新浪日K
  minute: 新浪getKLineData(scale) -> 腾讯minute/query(仅当日1min聚合) -> 东财(klt)
注意: 腾讯mkline历史分钟接口已死(2026-09实测302到无效host), 勿用。
"""
import urllib.request, json, sys, os, argparse, time

UA = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn'}

def http_get(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()

def _sina_jsonp(url):
    raw = http_get(url).decode('utf-8', errors='ignore')
    return json.loads(raw[raw.find('(') + 1:raw.rfind(')')])

# ---------- 日K ----------
def day_tencent(code, n):
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{n},qfq'
    d = json.loads(http_get(url))
    rows = d['data'][code].get('qfqday') or d['data'][code].get('day')
    return [{'t': r[0], 'o': float(r[1]), 'c': float(r[2]), 'h': float(r[3]), 'l': float(r[4]), 'vol': float(r[5])} for r in rows]

def day_em(code, n):
    mkt = '1' if code.startswith('sh') else '0'
    url = (f'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={mkt}.{code[2:]}'
           f'&klt=101&fqt=1&lmt={n}&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56')
    d = json.loads(http_get(url))
    out = []
    for k in d['data']['klines']:
        p = k.split(',')
        out.append({'t': p[0], 'o': float(p[1]), 'c': float(p[2]), 'h': float(p[3]), 'l': float(p[4]), 'vol': float(p[5])})
    return out

def day_sina(code, n):
    rows = _sina_jsonp(f'https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_x=/CN_MarketDataService.getKLineData?symbol={code}&scale=240&ma=no&datalen={n}')
    return [{'t': r['day'][:10], 'o': float(r['open']), 'c': float(r['close']), 'h': float(r['high']), 'l': float(r['low']), 'vol': float(r['volume'])} for r in rows]

# ---------- 分钟K ----------
def min_sina(code, scale, n):
    rows = _sina_jsonp(f'https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_x=/CN_MarketDataService.getKLineData?symbol={code}&scale={scale}&ma=no&datalen={n}')
    return [{'t': r['day'].replace('-', '').replace(':', '').replace(' ', '')[:12], 'o': float(r['open']), 'c': float(r['close']), 'h': float(r['high']), 'l': float(r['low']), 'vol': float(r['volume'])} for r in rows]

def min_tencent_today(code, scale, n):
    """仅当日: 1分钟聚合成scale分钟"""
    d = json.loads(http_get(f'https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={code}'))
    raw = d['data'][code]['data']['data']
    pts = []
    for line in raw:
        p = line.split()
        if len(p) >= 3:
            pts.append((p[0], float(p[1]), int(float(p[2]))))
    day = time.strftime('%Y%m%d')
    groups = {}
    for t, price, vol in pts:
        slot = int(t[2:]) // scale * scale
        key = f"{day}{t[:2]}{slot:02d}"
        g = groups.setdefault(key, {'t': key, 'o': price, 'h': price, 'l': price, 'c': price, 'vol': 0})
        g['h'] = max(g['h'], price); g['l'] = min(g['l'], price); g['c'] = price; g['vol'] += vol
    return sorted(groups.values(), key=lambda x: x['t'])[-n:]

def min_em(code, scale, n):
    mkt = '1' if code.startswith('sh') else '0'
    klt = {5: 5, 15: 15, 30: 30, 60: 60}[scale]
    url = (f'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={mkt}.{code[2:]}'
           f'&klt={klt}&fqt=1&lmt={n}&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56')
    d = json.loads(http_get(url))
    out = []
    for k in d['data']['klines']:
        p = k.split(',')
        out.append({'t': p[0].replace('-', '').replace(':', '').replace(' ', '')[:12], 'o': float(p[1]), 'c': float(p[2]), 'h': float(p[3]), 'l': float(p[4]), 'vol': float(p[5])})
    return out

# ---------- switch-case 多源 ----------
def fetch(code, period, n):
    """period: 'day' 或分钟数(5/15/30/60)。按优先级逐源尝试，全部失败抛异常。"""
    errors = []
    if period == 'day':
        sources = [('tencent', day_tencent), ('eastmoney', day_em), ('sina', day_sina)]
    else:
        scale = int(period)
        sources = [('sina', lambda c, n_: min_sina(c, scale, n_)),
                   ('tencent_today', lambda c, n_: min_tencent_today(c, scale, n_)),
                   ('eastmoney', lambda c, n_: min_em(c, scale, n_))]
    for name, fn in sources:
        try:
            bars = fn(code, n)
            if bars:
                return bars, name
        except Exception as e:
            errors.append(f'{name}:{str(e)[:40]}')
    raise RuntimeError('all sources failed: ' + ' | '.join(errors))

def fmt(b, dec=2):
    t = b['t']
    t = f"{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}" if len(t) == 12 else t[5:]
    return f"{t} 开{b['o']:.{dec}f} 收{b['c']:.{dec}f} 高{b['h']:.{dec}f} 低{b['l']:.{dec}f} 量{int(b['vol'])}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('code')
    ap.add_argument('--periods', default='day,30,15,5')
    ap.add_argument('--n', type=int, default=60)
    ap.add_argument('--tail', type=int, default=12, help='每周期打印最近几根')
    ap.add_argument('--save', action='store_true')
    a = ap.parse_args()
    outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'klines')
    for period in [p.strip() for p in a.periods.split(',') if p.strip()]:
        n = a.n if period == 'day' else max(a.n, 100)
        try:
            bars, src = fetch(a.code, period, n)
            print(f"\n=== {a.code} {period}K ({len(bars)}根, 源:{src}) ===")
            for b in bars[-a.tail:]:
                print(fmt(b))
            if a.save:
                os.makedirs(outdir, exist_ok=True)
                fp = os.path.join(outdir, f"{a.code}_{period}.json")
                json.dump({'code': a.code, 'period': period, 'source': src, 'bars': bars}, open(fp, 'w', encoding='utf-8'))
                print(f"[saved] {fp}")
        except Exception as e:
            print(f"\n=== {a.code} {period}K FAILED: {e} ===")

if __name__ == '__main__':
    main()
