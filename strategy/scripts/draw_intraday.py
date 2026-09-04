# -*- coding: utf-8 -*-
"""盘中版预测图：实际走势(黑) + 三情景预测(锚定真实开盘价) + 做T区间。Y轴左%右价格。"""
import sys, json, urllib.request, datetime
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False
rng = np.random.default_rng(7)

STOCKS = [
    {'code': 'sh588200', 'name': '588200 科创芯片ETF', 'prev': 1.173,
     'zones': [(1.54, 1.88, 'red', '反T卖区 1.191-1.195'), (-1.96, -1.53, 'green', '正T买区 1.150-1.155')],
     'stop': -2.81, 'ylim': (-3.5, 3.5)},
    {'code': 'sz002714', 'name': '牧原股份', 'prev': 39.07,
     'zones': [(-1.53, -1.23, 'green', '试T买区 38.5-38.6'), (-0.18, 0.13, 'red', '试T卖区 39.0-39.1')],
     'stop': -1.94, 'ylim': (-2.5, 2.5)},
]

PLANS = {
    'sh588200': '做T计划(1万份)\n①正T:1.150-1.155买→1.170-1.176卖\n②反T:1.191-1.195卖→1.162-1.166接\n③破1.140全天停手 ④14:30后收尾',
    'sz002714': '试T计划(仅100股练手)\n①38.5-38.6买→39.0-39.1卖\n②破38.3认错 ③不做不加仓',
}

def fetch_realtime(codes):
    url = 'https://qt.gtimg.cn/q=' + ','.join(codes)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    data = urllib.request.urlopen(req, timeout=10).read().decode('gbk', errors='ignore')
    out = {}
    for line in data.strip().split(';'):
        if '~' in line:
            p = line.split('~')
            code = line.split('=')[0].replace('v_', '').strip()
            out[code] = {'name': p[1], 'now': float(p[3]), 'open': float(p[5]) or None,
                         'vol': float(p[6]), 'high': float(p[33]) if len(p) > 33 and p[33] else None,
                         'low': float(p[34]) if len(p) > 34 and p[34] else None}
    return out

def fetch_minutes(code):
    """今日分时 [(min_idx, price)]，未开盘返回空"""
    try:
        url = f'https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={code}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        rows = d['data'][code]['data']['data']
        res = []
        for r in rows:
            t, price = r.split()[0], float(r.split()[1])
            hh, mm = int(t[:2]), int(t[2:])
            idx = (hh * 60 + mm) - (9 * 60 + 30)
            if idx < 0: continue
            if hh >= 13: idx = (hh * 60 + mm) - (13 * 60) + 120
            res.append((min(idx, 239), price))
        return res
    except Exception as e:
        print('minute fetch fail', code, e)
        return []

def make_path(points, n=240):
    xs = np.array([p[0] for p in points], dtype=float)
    ys = np.array([p[1] for p in points], dtype=float)
    xi = np.arange(n, dtype=float)
    yi = np.interp(xi, xs, ys)
    yi += np.concatenate([[0], rng.normal(0, 0.0009, n - 1)]).cumsum() * 0.12
    yi[0] = ys[0]; yi[-1] = ys[-1]
    return yi

def time_label(i):
    if i < 120:
        h, m = 9 + (30 + i) // 60, (30 + i) % 60
    else:
        h, m = 13 + (i - 120) // 60, (i - 120) % 60
    return f'{h}:{m:02d}'

now_str = datetime.datetime.now().strftime('%H:%M')
rt = fetch_realtime([s['code'] for s in STOCKS])

# 三情景模板（以真实开盘为锚，整体平移）
TEMPLATES = [
    ('基准', [(0, 0.0), (25, -0.5), (50, -1.1), (80, -0.8), (120, -0.5), (170, -0.1), (239, 0.0)], 'royalblue'),
    ('乐观', [(0, 0.1), (30, 0.8), (60, 1.6), (110, 1.4), (180, 1.8), (239, 1.6)], 'seagreen'),
    ('悲观', [(0, -0.1), (30, -1.2), (55, -2.0), (100, -2.4), (170, -2.9), (239, -2.6)], 'firebrick'),
]

fig, axes = plt.subplots(2, 1, figsize=(11, 9), sharex=True)
fig.suptitle(f'2026-08-24 盘中实测 vs 预测（截至 {now_str}）\n黑线=实际走势 · 三条彩色=剧本（已锚定真实开盘价）',
             fontsize=12, fontweight='bold')

for ax, s in zip(axes, STOCKS):
    prev = s['prev']
    r = rt.get(s['code'], {})
    open_pct = ((r['open'] / prev - 1) * 100) if r.get('open') else 0.0
    mins = fetch_minutes(s['code'])

    # 实际走势（黑）
    if mins:
        xs = [m[0] for m in mins]
        ys = [(m[1] / prev - 1) * 100 for m in mins]
        ax.plot(xs, ys, color='black', lw=2.2, label=f'实际（开 {open_pct:+.2f}%）', zorder=5)
        last_idx, last_pct = xs[-1], ys[-1]
    else:
        cur_pct = (r.get('now', prev) / prev - 1) * 100
        ax.plot([0], [cur_pct], 'ko', ms=6, label=f'当前 {cur_pct:+.2f}%（竞价/未开盘）', zorder=5)
        last_idx, last_pct = 0, cur_pct

    # 三情景：平移锚定到真实开盘
    for label, pts, color in TEMPLATES:
        offset = open_pct - pts[0][1]
        adj = [(x, y + offset) for x, y in pts]
        y = make_path(adj)
        ax.plot(np.arange(240), y, color=color, lw=1.4, ls='--', alpha=0.75, label=f'{label}情景')

    ax.axhline(0, color='gray', ls='--', lw=1, alpha=0.6)
    for lo, hi, color, zlabel in s['zones']:
        ax.axhspan(lo, hi, color=color, alpha=0.15)
        ax.text(2, (lo + hi) / 2, zlabel, color=color, fontsize=9, va='center', fontweight='bold')
    if s['stop']:
        ax.axhline(s['stop'], color='red', ls=':', lw=1.2)
        ax.text(130, s['stop'] - 0.08, f'认错线 {prev*(1+s["stop"]/100):.3f} ({s["stop"]:.1f}%)', color='red', fontsize=9)
    ax.axvspan(15, 60, color='gold', alpha=0.10)
    ax.axvspan(120, 180, color='gold', alpha=0.10)
    ax.text(37, s['ylim'][1] * 0.86, '做T①', ha='center', fontsize=8, color='darkgoldenrod')
    ax.text(150, s['ylim'][1] * 0.86, '做T②', ha='center', fontsize=8, color='darkgoldenrod')
    if mins:
        ax.axvline(last_idx, color='black', ls=':', lw=1, alpha=0.5)
    hi_lo = ''
    if r.get('high') and r.get('low'):
        hi_lo = f" | 高 {r['high']} 低 {r['low']}"
    # 做T计划文本框（右上角）
    plan = PLANS.get(s['code'])
    if plan:
        ax.text(0.985, 0.97, plan, transform=ax.transAxes, fontsize=9,
                ha='right', va='top', color='black', fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.45', facecolor='lightyellow', edgecolor='orange'))
    ax.set_title(f"{s['name']}（昨收 {prev} | 开 {r.get('open') or '-'} | 现 {r.get('now', '-')}{hi_lo}）", fontsize=11, loc='left')
    ax.set_ylabel('涨跌幅 (%)')
    ax.set_ylim(*s['ylim'])
    ax.legend(fontsize=8, loc='lower left', framealpha=0.9)
    ax.grid(alpha=0.25)
    ax2 = ax.twinx()
    ax2.set_ylim(prev * (1 + s['ylim'][0] / 100), prev * (1 + s['ylim'][1] / 100))
    ax2.set_ylabel('价格 (元)', color='dimgray')
    ax2.tick_params(axis='y', labelcolor='dimgray')

ticks = [0, 30, 60, 90, 120, 150, 180, 210, 239]
axes[1].set_xticks(ticks)
axes[1].set_xticklabels([time_label(t) for t in ticks])
axes[1].set_xlabel('交易时间')
fig.text(0.01, 0.005, '左轴% · 右轴价格 | 虚线为剧本非承诺 | 生成于 ' + now_str, fontsize=8, color='gray')
plt.tight_layout(rect=[0, 0.02, 1, 0.93])
out = r'C:\Users\admin\dev\investment-tool\strategy\2026-08-24-tplan.png'
plt.savefig(out, dpi=140, bbox_inches='tight')
print('saved:', out)
