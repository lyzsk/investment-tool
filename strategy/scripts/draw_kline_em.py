# -*- coding: utf-8 -*-
"""东财风格日K：红涨绿跌蜡烛 + MA5/10/20 + 成交量副图 + 今日预测vs实际对比标注"""
import urllib.request, json, datetime
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

UP = '#e54545'    # 东财红
DOWN = '#1ba784'  # 东财绿
MA_C = {5:'#f5a623', 10:'#8e6ec8', 20:'#4a90d9'}  # 东财 MA5黄 MA10紫 MA20蓝

# 预测记录（我昨日给的"明日"=今日8/27的剧本）
PRED = {
 'sh588200': {'pred_close_lo':1.14,'pred_close_hi':1.17,'note':'基准收+1%'},
 'sz002714': {'pred_close_lo':39.5,'pred_close_hi':40.2,'note':'基准收+0.4%'},
 'sz002759': {'pred_close_lo':17.2,'pred_close_hi':17.8,'note':'基准横盘'},
}
STOCKS = [
 ('sh588200','588200 科创芯片',3),
 ('sz002714','牧原股份',2),
 ('sz002759','ST天际',2),
]

def fetch_daily(code, n=40):
    url=f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{n},qfq'
    req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    d=json.loads(urllib.request.urlopen(req,timeout=15).read())
    return d['data'][code]['qfqday']

fig = plt.figure(figsize=(15, 13), facecolor='white')
for idx, (code, name, dec) in enumerate(STOCKS):
    rows = fetch_daily(code)[-15:]
    dates = [r[0][5:] for r in rows]
    O = np.array([float(r[1]) for r in rows]); C = np.array([float(r[2]) for r in rows])
    H = np.array([float(r[3]) for r in rows]); L = np.array([float(r[4]) for r in rows])
    V = np.array([float(r[5]) for r in rows])
    n = len(rows); xs = np.arange(n)
    ax = fig.add_subplot(3, 2, idx*2+1)
    axv = fig.add_subplot(3, 2, idx*2+2)
    ax.set_facecolor('white'); axv.set_facecolor('white')
    # MA
    closes_all = C
    for w, c in MA_C.items():
        if n >= w:
            ma = np.convolve(closes_all, np.ones(w)/w, mode='valid')
            ax.plot(np.arange(w-1, n), ma, color=c, lw=1.2, label=f'MA{w}')
    # 蜡烛
    for i in range(n):
        up = C[i] >= O[i]
        color = UP if up else DOWN
        ax.plot([i, i], [L[i], H[i]], color=color, lw=0.9, zorder=2)
        body_lo, body_hi = min(O[i], C[i]), max(O[i], C[i])
        h = max(body_hi - body_lo, 0.001 * C[i])
        ax.add_patch(Rectangle((i-0.32, body_lo), 0.64, h, facecolor=color if not up else 'white',
                               edgecolor=color, lw=1.2, zorder=3))
        axv.bar(i, V[i], color=color, width=0.64)
    # 今日预测vs实际标注
    pr = PRED.get(code)
    if pr:
        i = n-1
        ax.axhspan(pr['pred_close_lo'], pr['pred_close_hi'], xmin=0.86, xmax=1.0, color='gold', alpha=0.35)
        ax.text(n-0.6, pr['pred_close_hi'], ' 预测区', color='darkgoldenrod', fontsize=8, va='bottom')
        ax.plot([i], [C[i]], marker='*', markersize=14, color='#d81e06', zorder=6)
    hit = ''
    if pr:
        c = C[-1]
        hit = '[命中]' if pr['pred_close_lo'] <= c <= pr['pred_close_hi'] else ('[超预期↑]' if c > pr['pred_close_hi'] else '[低于预期↓]')
    ax.set_title(f"{name}  收 {C[-1]:.{dec}f}（{(C[-1]/C[-2]-1)*100:+.2f}%） {hit}", loc='left', fontsize=11, fontweight='bold')
    ax.legend(fontsize=8, loc='upper left'); ax.grid(alpha=0.2, ls=':')
    ax.set_xlim(-0.7, n-0.1)
    ax.set_xticks(xs[::2]); ax.set_xticklabels([dates[i] for i in range(0, n, 2)], fontsize=8)
    ax.yaxis.set_major_formatter(lambda v, p: f"{v:.{dec}f}")
    axv.set_title('成交量', loc='left', fontsize=9); axv.grid(alpha=0.2, ls=':')
    axv.set_xlim(-0.7, n-0.1); axv.set_xticks(xs[::2]); axv.set_xticklabels([dates[i] for i in range(0, n, 2)], fontsize=8)

fig.suptitle('东财风格日K · 今日预测vs实际（金色带=预测收盘区，红星=实际收盘）', fontsize=14, fontweight='bold')
plt.tight_layout(rect=[0, 0.01, 1, 0.96])
out = r'C:\Users\admin\dev\investment-tool\strategy\2026S3\2026-08-27\2026-08-27-kline-review.png'
plt.savefig(out, dpi=110)
print('saved:', out)
