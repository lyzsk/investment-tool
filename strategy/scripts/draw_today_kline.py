# -*- coding: utf-8 -*-
"""今日日K预测图：三只持仓股 近期K线 + 今日进行中K线(高亮) + 预测收盘区间"""
import urllib.request, json, datetime
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

STOCKS = [
    {'code': 'sh588200', 'name': '588200 科创芯片ETF', 'mas': (20, 60, 120),
     'marks': [(1.1202, 'red', '你的挂买 1.12 = MA120(1.1202)')],
     'pred': '基准收 -2.5%~-3.2%（1.135-1.144），长下影探底MA120；若收盘站回1.155上方则超预期强'},
    {'code': 'sz002714', 'name': '牧原股份 002714', 'mas': (20, 60),
     'marks': [(38.20, 'green', '今日低 38.20 支撑')],
     'pred': '基准收 38.4-38.7（-1.0%~-1.7%）小阴线，缩量；猪周期逻辑不变，持有'},
    {'code': 'sz002759', 'name': 'ST天际 002759', 'mas': (20, 60),
     'marks': [(17.0, 'red', '止损线 17.0'), (19.14, 'orange', '今日高 19.14')],
     'pred': '基准收 18.2-18.6（-1.5%~+0.7%）长上影十字/小阴；板块先锋炸板则跟跌'},
]

def fetch(code):
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,60,qfq'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    d = json.loads(urllib.request.urlopen(req, timeout=15).read())
    rows = d['data'][code].get('qfqday') or d['data'][code].get('day')
    return [[r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in rows]

def realtime(code):
    req = urllib.request.Request(f'https://qt.gtimg.cn/q={code}', headers={'User-Agent': 'Mozilla/5.0'})
    p = urllib.request.urlopen(req, timeout=10).read().decode('gbk', errors='ignore').split('~')
    return {'open': float(p[5]), 'now': float(p[3]), 'high': float(p[33]), 'low': float(p[34]), 'prev': float(p[4])}

fig, axes = plt.subplots(3, 1, figsize=(12, 12))
fig.suptitle('2026-08-24 持仓三股·今日日K预测（13:07 数据）\n最后一根为今日进行中K线，黄色框=预测收盘区间', fontsize=13, fontweight='bold')

for ax, s in zip(axes, STOCKS):
    kl = fetch(s['code'])[-35:]
    rt = realtime(s['code'])
    today = datetime.date.today().strftime('%Y-%m-%d')
    # 今日K线（进行中）：开高低现
    kl_today = [today, rt['open'], rt['now'], rt['high'], rt['low'], 0]
    if kl[-1][0] == today:
        kl[-1] = kl_today
    else:
        kl.append(kl_today)

    closes = [k[2] for k in kl]
    for n in s['mas']:
        if len(closes) >= n:
            ma = [np.mean(closes[max(0, i - n + 1):i + 1]) for i in range(len(closes))]
            ax.plot(range(len(kl)), ma, lw=1.2, label=f'MA{n}={ma[-1]:.3f}' if n == 120 else f'MA{n}')

    for i, k in enumerate(kl):
        o, c, h, l = k[1], k[2], k[3], k[4]
        color = '#e54545' if c >= o else '#26a26a'  # 红涨绿跌
        is_today = (i == len(kl) - 1)
        lw = 2.2 if is_today else 1.0
        ax.vlines(i, l, h, color=color, lw=lw, zorder=3)
        ax.add_patch(Rectangle((i - 0.3, min(o, c)), 0.6, max(abs(c - o), 1e-6),
                               facecolor=color if not is_today else color,
                               edgecolor='black' if is_today else color,
                               lw=1.5 if is_today else 0.5,
                               alpha=0.95 if is_today else 0.8, zorder=4))
    # 标注均线/关键位
    for price, color, label in s['marks']:
        ax.axhline(price, color=color, ls='--', lw=1.2, alpha=0.8)
        ax.text(len(kl) - 1, price, f' {label}', color=color, fontsize=9, va='bottom', fontweight='bold')
    # 预测收盘区间框
    ax.add_patch(Rectangle((len(kl) - 1.45, rt['low']), 0.9, rt['high'] - rt['low'],
                           facecolor='gold', alpha=0.15, edgecolor='orange', ls=':', zorder=2))
    pct = (rt['now'] / rt['prev'] - 1) * 100
    ax.set_title(f"{s['name']}：现 {rt['now']}（{pct:+.2f}%）｜{s['pred']}", fontsize=10, loc='left')
    ax.legend(fontsize=8, loc='upper right')
    ax.grid(alpha=0.25)
    step = max(1, len(kl) // 8)
    ax.set_xticks(range(0, len(kl), step))
    ax.set_xticklabels([kl[i][0][5:] for i in range(0, len(kl), step)], fontsize=8)

plt.tight_layout(rect=[0, 0.01, 1, 0.95])
out = r'C:\Users\admin\dev\investment-tool\strategy\2026-08-24-kline-predict.png'
plt.savefig(out, dpi=140, bbox_inches='tight')
print('saved:', out)
