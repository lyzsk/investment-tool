# plot_equity.py — k3 v0.1 / v0.2 / 桃哥 pilot-2week / 上证 归一化净值曲线
# 数据源: 各 run 目录的 equity.csv (date,total_nav[,sh_close])
# 输出: scripts/k3-inv/backtest/runs/equity-compare.png
# 用法: C:/Users/admin/anaconda3/python.exe plot_equity.py
import csv, os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

BASE = os.path.dirname(os.path.abspath(__file__))
SERIES = [
    ('k3 v0.2 (本版)', os.path.join(BASE, 'runs', 'k3-v0.2-20260901_0918', 'equity.csv'), '#d62728', '-', 2.2),
    ('k3 v0.1', os.path.join(BASE, 'runs', 'k3-v0.1-20260901_0918', 'equity.csv'), '#ff9896', '--', 1.5),
    ('桃哥 pilot-2week', os.path.join(BASE, '..', '..', 'bilibili-taoge', 'backtest', 'runs', 'pilot-2week', 'equity.csv'), '#1f77b4', '-', 2.2),
]

def load(path):
    dates, navs, shs = [], [], []
    with open(path, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            dates.append(datetime.strptime(row['date'], '%Y%m%d'))
            navs.append(float(row['total_nav']))
            shs.append(float(row['sh_close']) if row.get('sh_close') else None)
    return dates, navs, shs

fig, ax = plt.subplots(figsize=(11, 6))
sh_plotted = False
for name, path, color, ls, lw in SERIES:
    dates, navs, shs = load(path)
    base = navs[0]
    ax.plot(dates, [n / base * 100 for n in navs], ls, color=color, lw=lw,
            label=f'{name}  ({navs[-1]/base*100-100:+.2f}%)')
    if not sh_plotted and any(shs):
        sh_pairs = [(d, s) for d, s in zip(dates, shs) if s]
        b = sh_pairs[0][1]
        ax.plot([d for d, _ in sh_pairs], [s / b * 100 for _, s in sh_pairs], ':',
                color='#7f7f7f', lw=1.8,
                label=f'上证指数  ({sh_pairs[-1][1]/b*100-100:+.2f}%)')
        sh_plotted = True

ax.axhline(100, color='#bbbbbb', lw=0.8)
ax.set_title('净值曲线对照 (各自起点=100)   窗口 2026-09-01 → 2026-09-18')
ax.set_ylabel('归一化净值')
ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
ax.xaxis.set_major_locator(mdates.DayLocator())
plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
ax.legend(loc='best', fontsize=10)
ax.grid(alpha=0.25)
fig.tight_layout()
out = os.path.join(BASE, 'runs', 'equity-compare.png')
fig.savefig(out, dpi=150)
print('saved:', out)
