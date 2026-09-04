# -*- coding: utf-8 -*-
"""五日分时：最近3交易日真实(5min) + 今日预测 + 明日预测。Y轴左%(对首日昨收)右价。"""
import urllib.request, json, datetime
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False
BARS = 48

STOCKS = [
 {'code':'sh588200','name':'588200 科创芯片','dec':3,
  'today':[('基准50%：平开震荡修复，收1.135-1.150', 0.003, -0.006, 0.010, 0.013),
           ('乐观25%：半导体修复延续冲1.155-1.165', 0.008, -0.002, 0.022, 0.018),
           ('悲观25%：再测MA120(1.12)企稳', -0.005, -0.012, 0.004, -0.007)],
  'tomorrow':[('基准：延续修复1.14-1.17', 0.004, -0.003, 0.012, 0.010),
              ('反向：若今日冲高回落则回踩1.125', -0.004, -0.010, 0.005, -0.006)]},
 {'code':'sz002714','name':'牧原股份','dec':2,
  'today':[('基准50%：高开震荡39.5-40.3，40关口有压', 0.005, -0.006, 0.012, 0.006),
           ('乐观25%：放量突破40 → 40.5', 0.008, 0.000, 0.018, 0.014),
           ('悲观25%：两日连涨后高开低走回补39.2', 0.006, -0.014, 0.008, -0.010)],
  'tomorrow':[('基准：40关口争夺，38.9-40.2', 0.000, -0.008, 0.010, 0.004),
              ('反向：板块退潮回39.0', -0.006, -0.016, 0.004, -0.012)]},
 {'code':'sz002759','name':'ST天际','dec':2,
  'today':[('悲观45%：低开探17.0-17.3（昨收<18反向激活）', -0.010, -0.035, 0.008, -0.020),
           ('基准35%：17.3-17.9震荡弱修复', -0.005, -0.020, 0.012, 0.005),
           ('乐观20%：板块反弹收复18.0', 0.005, -0.008, 0.030, 0.025)],
  'tomorrow':[('基准：守17.0则横盘17.2-17.8', 0.000, -0.015, 0.015, 0.005),
              ('反向：收盘破17.0止损离场', -0.010, -0.040, 0.005, -0.030)]},
]

def fetch_m5(code, n=300):
    url=f'https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_x=/CN_MarketDataService.getKLineData?symbol={code}&scale=5&ma=no&datalen={n}'
    req=urllib.request.Request(url, headers={'Referer':'https://finance.sina.com.cn','User-Agent':'Mozilla/5.0'})
    raw=urllib.request.urlopen(req,timeout=15).read().decode('utf-8',errors='ignore')
    return json.loads(raw[raw.find('(')+1:raw.rfind(')')])

def fetch_daily(code, n=10):
    url=f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{n},qfq'
    req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    d=json.loads(urllib.request.urlopen(req,timeout=15).read())
    return d['data'][code]['qfqday']

def scen_curve(pc, anchors_pct, seed):
    """pc=前收, anchors_pct=[gap,low,high,mid,close] 相对变动(小数)"""
    pts = [0, 9, 18, 36, BARS-1]
    vals = [a*100 for a in anchors_pct]
    yy = np.interp(np.arange(BARS), pts, vals)
    yy += np.random.RandomState(seed).randn(BARS)*0.05
    return yy

fig, axes = plt.subplots(3, 1, figsize=(16, 15))
for ax, s in zip(axes, STOCKS):
    code = s['code']
    bars = fetch_m5(code)
    daily = fetch_daily(code)
    close_map = {d[0]: float(d[2]) for d in daily}
    days = {}
    for b in bars:
        days.setdefault(b['day'][:10], []).append(float(b['close']))
    dates = sorted(days.keys())[-3:]  # 最近3个完整交易日
    first = dates[0]
    prev_dates = [d for d in sorted(close_map.keys()) if d < first]
    base_prev = close_map[prev_dates[-1]] if prev_dates else days[first][0]
    x_all, y_all = [], []
    for i, dt in enumerate(dates):
        closes = days[dt]
        xs = np.arange(i*BARS, i*BARS+len(closes))
        x_all += list(xs)
        y_all += [(c/base_prev-1)*100 for c in closes]
    ax.plot(x_all, y_all, color='black', lw=1.2, label='实际(5min)')
    # 昨收（=最新一天收盘）
    last_close = days[dates[-1]][-1]
    # 今日预测（第4格）
    for label, g, lo, hi, cl in s['today']:
        yc = scen_curve(last_close, [g, lo, hi, lo/2, cl], hash(code+label)%2**31)
        anchor = (last_close/base_prev-1)*100
        ax.plot(np.arange(3*BARS, 4*BARS), yc+anchor, ls='--', lw=1.5, label='今日·'+label)
    # 明日预测（第5格，锚=今日基准收盘）
    base_today_close_pct = (last_close/base_prev-1)*100 + s['today'][0][4]*100
    for label, g, lo, hi, cl in s['tomorrow']:
        yc = scen_curve(1, [g, lo, hi, lo/2, cl], hash(code+label+'T')%2**31)
        ax.plot(np.arange(4*BARS, 5*BARS), yc+base_today_close_pct, ls=':', lw=1.5, label='明日·'+label)
    for i in range(6):
        ax.axvline(i*BARS, color='#bbb', lw=0.8, alpha=0.7)
    ax.axvline(3*BARS, color='#c00', lw=1.4, alpha=0.8)  # 今日分界
    labels = [d[5:] for d in dates] + ['今日·预测', '明日·预测']
    ylim_all = y_all + [ (last_close/base_prev-1)*100 ]
    ylim = (min(ylim_all)-1.2, max(ylim_all)+1.5)
    for i, lb in enumerate(labels):
        c = '#c00' if '预测' in lb else '#333'
        ax.text(i*BARS+BARS/2, ylim[1]-0.35, lb, fontsize=10, fontweight='bold', ha='center', color=c)
    ax.axhline(0, color='gray', ls=':', lw=0.8)
    ax.set_xlim(0, 5*BARS-1); ax.set_ylim(*ylim)
    ax.set_xticks([i*BARS+BARS//2 for i in range(5)]); ax.set_xticklabels(labels)
    ax.set_ylabel('累计涨跌幅 %（对首日昨收）')
    ax.set_title(f"{s['name']}（首日昨收 {base_prev}，最新收 {last_close}）", loc='left', fontsize=11, fontweight='bold')
    ax.legend(fontsize=6.5, loc='upper left'); ax.grid(alpha=0.25)
    ax2 = ax.twinx(); ax2.set_ylim(base_prev*(1+ylim[0]/100), base_prev*(1+ylim[1]/100))
    ax2.set_ylabel('价格', color='dimgray'); ax2.yaxis.set_major_formatter(lambda v,p: f"{v:.{s['dec']}f}")

fig.suptitle('五日分时：近3日真实 + 今日/明日预测（2026-08-26 盘前）', fontsize=14, fontweight='bold')
fig.text(0.01, 0.005, '预测为概率剧本非承诺', fontsize=8, color='gray')
plt.tight_layout(rect=[0, 0.01, 1, 0.96])
out = r'C:\Users\admin\dev\investment-tool\strategy\2026S3\2026-08-26\2026-08-26-fiveday.png'
import os; os.makedirs(os.path.dirname(out), exist_ok=True)
plt.savefig(out, dpi=110)
print('saved:', out)
