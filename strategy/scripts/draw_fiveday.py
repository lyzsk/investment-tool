# -*- coding: utf-8 -*-
"""五日线式多日分时(5分钟K线)：前4日真实+今日(实际+尾盘推演)+明日预测。Y轴左%(对首日昨收)右价。"""
import urllib.request, json, datetime
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False
BARS = 48  # 5分钟K线每日根数

STOCKS = [
 {'code':'sh588200','name':'588200 科创芯片','dec':3,
  'tomorrow':[('基准55%：平开小高开冲高1.15-1.16，收+1%左右', 0.005, -0.004, 0.010, 0.012),
              ('反向45%：隔夜美股半导体再跌则低开回测1.12', -0.008, -0.014, 0.004, -0.010)]},
 {'code':'sz002714','name':'牧原股份','dec':2,
  'tomorrow':[('基准55%：板块延续高开震荡39.5-40.2', 0.004, -0.003, 0.012, 0.008),
              ('反向45%：两日连涨后高开低走回补39.0', 0.006, -0.010, 0.008, -0.006)]},
 {'code':'sz002759','name':'ST天际','dec':2,
  'tomorrow':[('基准(今收≥18则55%)：高开冲18.5-19.1', 0.010, -0.005, 0.045, 0.030),
              ('反向(今收<18则55%)：低开破17.5探17.0止损区', -0.012, -0.045, 0.005, -0.035)]},
]

def fetch_m5(code, n=300):
    url=f'https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_x=/CN_MarketDataService.getKLineData?symbol={code}&scale=5&ma=no&datalen={n}'
    req=urllib.request.Request(url, headers={'Referer':'https://finance.sina.com.cn','User-Agent':'Mozilla/5.0'})
    raw=urllib.request.urlopen(req,timeout=15).read().decode('utf-8',errors='ignore')
    body=raw[raw.find('(')+1:raw.rfind(')')]
    return json.loads(body)  # [{day, open, high, low, close, volume}]

def fetch_daily(code, n=10):
    url=f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{n},qfq'
    req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    d=json.loads(urllib.request.urlopen(req,timeout=15).read())
    return d['data'][code]['qfqday']

fig, axes = plt.subplots(3, 1, figsize=(16, 15))
for ax, s in zip(axes, STOCKS):
    code = s['code']
    bars = fetch_m5(code)
    daily = fetch_daily(code)
    close_map = {d[0]: float(d[2]) for d in daily}
    days = {}
    for b in bars:
        days.setdefault(b['day'][:10], []).append(float(b['close']))
    dates = sorted(days.keys())[-5:]
    first = dates[0]
    prev_dates = [d for d in sorted(close_map.keys()) if d < first]
    base_prev = close_map[prev_dates[-1]] if prev_dates else days[first][0]
    x_all, y_all = [], []
    for i, dt in enumerate(dates):
        closes = days[dt]
        xs = np.arange(i*BARS, i*BARS+len(closes))
        x_all += list(xs)
        y_all += [(c/base_prev-1)*100 for c in closes]
    # 今日尾盘推演（若今天未收满48根）
    today = dates[-1]; tcl = days[today]; tn = len(tcl)
    if tn < BARS:
        fit = min(6, tn)
        slope = np.polyfit(range(fit), tcl[-fit:], 1)[0] if fit > 3 else 0
        last = tcl[-1]
        proj = [last + slope*0.4*(i+1) for i in range(BARS-tn)]
        ax.plot(np.arange(4*BARS+tn, 5*BARS), [(c/base_prev-1)*100 for c in proj],
                color='gray', ls=':', lw=1.3, label='今日尾盘推演')
    ax.plot(x_all, y_all, color='black', lw=1.1, label='实际分时(5min)')
    # 明日预测（第5日）
    if tn > 3:
        fit = min(6, tn)
        slope = np.polyfit(range(fit), tcl[-fit:], 1)[0]
        today_close_est = tcl[-1] + slope*0.4*max(0, BARS-tn) if tn < BARS else tcl[-1]
    else:
        today_close_est = tcl[-1]
    tc_pct = (today_close_est/base_prev-1)*100
    anchors = [0, 9, 18, 36, BARS-1]
    for label, gap, low1, high1, close1 in s['tomorrow']:
        seq = [gap, low1, high1, low1/2, close1]
        y5 = [tc_pct + v*100 for v in seq]
        yy = np.interp(np.arange(BARS), anchors, y5)
        yy = yy + np.random.RandomState(hash(code+label)%2**31).randn(BARS)*0.04
        ax.plot(np.arange(5*BARS, 6*BARS), yy, ls='--', lw=1.5, label=f'明日·{label}', alpha=0.9)
    # 分隔线
    for i in range(6):
        ax.axvline(i*BARS, color='#bbb', ls='-', lw=0.8, alpha=0.7)
    ax.axvline(5*BARS, color='#c00', ls='-', lw=1.2, alpha=0.7)
    ylim_tmp = (min(y_all+[tc_pct])-1.0, max(y_all+[tc_pct])+1.0)
    for i, dt in enumerate(dates):
        ax.text(i*BARS+BARS/2, ylim_tmp[1]-0.25, f"{dt[5:7]}/{dt[8:10]}", fontsize=10, fontweight='bold', ha='center', color='#333')
    ax.text(5*BARS+BARS/2, ylim_tmp[1]-0.25, "明日·预测", fontsize=10, fontweight='bold', ha='center', color='#c00')
    ax.axhline(0, color='gray', ls=':', lw=0.8)
    ax.set_xlim(0, 6*BARS-1); ax.set_ylim(*ylim_tmp)
    ax.set_xticks([i*BARS for i in range(7)])
    ax.set_xticklabels([d[5:] for d in dates]+['明日',''])
    ax.set_ylabel('累计涨跌幅 %（对首日昨收）')
    ax.set_title(f"{s['name']} 五日分时+明日预测（基准价 {base_prev}）", loc='left', fontsize=11, fontweight='bold')
    ax.legend(fontsize=7, loc='upper left'); ax.grid(alpha=0.25)
    ax2 = ax.twinx(); ax2.set_ylim(base_prev*(1+ylim_tmp[0]/100), base_prev*(1+ylim_tmp[1]/100))
    ax2.set_ylabel('价格', color='dimgray'); ax2.yaxis.set_major_formatter(lambda v,p: f"{v:.{s['dec']}f}")

now_str = datetime.datetime.now().strftime('%H:%M')
fig.suptitle(f'五日分时 + 明日预测（5分钟K线，生成 {now_str}）', fontsize=14, fontweight='bold')
fig.text(0.01, 0.005, '明日预测为概率剧本非承诺', fontsize=8, color='gray')
plt.tight_layout(rect=[0, 0.01, 1, 0.96])
out = r'C:\Users\admin\dev\investment-tool\strategy\2026S3\2026-08-25\2026-08-25-fiveday.png'
plt.savefig(out, dpi=110)
print('saved:', out)
