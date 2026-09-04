# -*- coding: utf-8 -*-
"""三只持仓股实时分时图 + 午后推演（反T接回视角）"""
import urllib.request, json, datetime
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False
rng = np.random.default_rng(11)

STOCKS = [
    {'code': 'sh588200', 'name': '588200 科创芯片ETF', 'prev': 1.148,
     'lines': [(1.120, 'red', '挂买1.12=MA120'), (1.155, 'green', '反T回补参考 1.150-1.155')],
     'ylim': (-4.2, 1.5)},
    {'code': 'sz002714', 'name': '牧原股份 002714', 'prev': 39.99,
     'lines': [(38.20, 'green', '今日低38.20')],
     'ylim': (-3.0, 1.0)},
    {'code': 'sz002759', 'name': 'ST天际 002759', 'prev': 17.47,
     'lines': [(17.00, 'red', '止损17.0'), (19.14, 'orange', '今日高19.14')],
     'ylim': (-8.5, 4.5)},
]

def minutes(code):
    url = f'https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={code}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    d = json.loads(urllib.request.urlopen(req, timeout=12).read())
    rows = d['data'][code]['data']['data']
    res = []
    for r in rows:
        p = r.split()
        hh, mm = int(p[0][:2]), int(p[0][2:])
        idx = (hh * 60 + mm) - 570
        if hh >= 13: idx = (hh * 60 + mm) - 780 + 120
        res.append((min(max(idx, 0), 239), float(p[1]), float(p[2]) if len(p) > 2 else 0))
    return res

def time_label(i):
    if i < 120: h, m = 9 + (30 + i) // 60, (30 + i) % 60
    else: h, m = 13 + (i - 120) // 60, (i - 120) % 60
    return f'{h}:{m:02d}'

fig, axes = plt.subplots(3, 1, figsize=(12, 12))
now_str = datetime.datetime.now().strftime('%H:%M')
fig.suptitle(f'2026-08-24 持仓三股·分时实况 + 午后推演（截至 {now_str}）\n黑线=实际分时 蓝虚线=均价 紫色虚线=午后推演路径',
             fontsize=13, fontweight='bold')

for ax, s in zip(axes, STOCKS):
    prev = s['prev']
    mins = minutes(s['code'])
    if not mins:
        ax.set_title(f"{s['name']}：分时数据获取失败", loc='left'); continue
    xs = [m[0] for m in mins]; ps = [m[1] for m in mins]; vs = [m[2] for m in mins]
    pct = [(p / prev - 1) * 100 for p in ps]
    # 均价线
    vol_cum = np.cumsum(vs); pv_cum = np.cumsum(np.array(ps) * np.array(vs))
    avg = np.where(vol_cum > 0, pv_cum / np.maximum(vol_cum, 1), ps[0])
    avg_pct = [(a / prev - 1) * 100 for a in avg]

    ax.plot(xs, pct, color='black', lw=1.8, label='实际分时', zorder=5)
    ax.plot(xs, avg_pct, color='royalblue', lw=1.2, ls='--', label='均价线', zorder=4)

    # 午后推演：三条动量自适应路径（延续/收敛均价/反向极值），从当前点出发
    last_x, last_y = xs[-1], pct[-1]
    day_low_pct = min(pct); day_high_pct = max(pct)
    # 近30分钟动量斜率（%/分钟），阻尼衰减外推
    fit_n = min(30, len(pct))
    slope = np.polyfit(range(fit_n), pct[-fit_n:], 1)[0] if fit_n > 5 else 0.0
    proj_x = np.arange(last_x, 240)
    remain = len(proj_x)
    # A 趋势延续：斜率阻尼0.5外推，封顶不超过今日高点+0.8%
    end_a = max(min(last_y + slope * remain * 0.5, day_high_pct + 0.8), day_low_pct - 0.8)
    # B 收敛均价：向均价线靠拢
    end_b = (avg_pct[-1] + last_y) / 2
    # C 反向极值：在均价上方→回测今日低点区；在均价下方→回测今日高点区
    end_c = (day_low_pct + 0.1) if last_y > avg_pct[-1] else (day_high_pct - 0.1)
    for end_v, c, lab in [(end_a, 'purple', '推演A: 趋势延续'), (end_b, 'gray', '推演B: 收敛均价'), (end_c, 'orange', '推演C: 反向极值')]:
        pj = np.linspace(last_y, end_v, remain) + np.concatenate([[0], rng.normal(0, 0.06, remain - 1)]).cumsum() * 0.25
        ax.plot(proj_x, pj, color=c, lw=1.3, ls=':', label=lab, zorder=3)
    ax.axvline(last_x, color='black', ls=':', lw=0.8, alpha=0.5)

    ax.axhline(0, color='gray', ls='-', lw=0.8, alpha=0.5)
    line_pcts = []
    for price, color, label in s['lines']:
        lp = (price / prev - 1) * 100
        line_pcts.append(lp)
        ax.axhline(lp, color=color, ls='--', lw=1.2)
        ax.text(238, lp, f' {label}', color=color, fontsize=9, va='center', ha='right', fontweight='bold',
                bbox=dict(facecolor='white', alpha=0.7, edgecolor='none'))
    # 窗口②
    ax.axvspan(120, 180, color='gold', alpha=0.10)

    # 自适应Y轴：容纳实际数据+推演末端+标记线，上下各留15%余量
    all_v = pct + [end_a, end_b, end_c] + line_pcts + [0.0]
    lo, hi = min(all_v), max(all_v)
    pad = max((hi - lo) * 0.15, 0.4)
    ylim = (lo - pad, hi + pad)

    ax.set_title(f"{s['name']}：现 {ps[-1]}（{pct[-1]:+.2f}%）开 {ps[0]} 高 {max(ps)} 低 {min(ps)}",
                 fontsize=10, loc='left')
    ax.text(150, ylim[1] - pad * 0.5, '做T窗口② 13:00-14:00', ha='center', fontsize=8, color='darkgoldenrod')
    ax.set_ylabel('涨跌幅 (%)'); ax.set_ylim(*ylim)
    ax.legend(fontsize=8, loc='lower left'); ax.grid(alpha=0.25)
    ax2 = ax.twinx()
    ax2.set_ylim(prev * (1 + ylim[0] / 100), prev * (1 + ylim[1] / 100))
    ax2.set_ylabel('价格', color='dimgray'); ax2.tick_params(axis='y', labelcolor='dimgray')

ticks = [0, 30, 60, 90, 120, 150, 180, 210, 239]
axes[2].set_xticks(ticks); axes[2].set_xticklabels([time_label(t) for t in ticks])
fig.text(0.01, 0.005, '推演为概率路径非承诺 | 生成 ' + now_str, fontsize=8, color='gray')
plt.tight_layout(rect=[0, 0.01, 1, 0.94])
out = r'C:\Users\admin\dev\investment-tool\strategy\2026S3\2026-08-27\2026-08-27-minute.png'
plt.savefig(out, dpi=140, bbox_inches='tight')
print('saved:', out)
