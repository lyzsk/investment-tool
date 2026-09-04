# -*- coding: utf-8 -*-
"""2026-08-24 盘前+竞价预测分时图 v2：Y轴百分比(左) + 价格(右)，含竞价校准"""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False
rng = np.random.default_rng(42)

def make_path(points, n=240, noise=0.0008):
    xs = np.array([p[0] for p in points], dtype=float)
    ys = np.array([p[1] for p in points], dtype=float)
    xi = np.arange(n, dtype=float)
    yi = np.interp(xi, xs, ys)
    yi += np.concatenate([[0], rng.normal(0, noise, n - 1)]).cumsum() * 0.15
    yi[0] = ys[0]; yi[-1] = ys[-1]
    return yi

def time_label(i):
    if i < 120:
        h, m = 9 + (30 + i) // 60, (30 + i) % 60
    else:
        h, m = 13 + (i - 120) // 60, (i - 120) % 60
    return f'{h}:{m:02d}'

def draw(ax, prev_close, title, scenarios, pct_ylim, zones=()):
    """zones: (lo_pct, hi_pct, color, label)"""
    for label, pts, color in scenarios:
        y = make_path(pts)
        ax.plot(np.arange(240), y, color=color, lw=1.8, label=label, alpha=0.92)
    ax.axhline(0, color='gray', ls='--', lw=1, alpha=0.6)
    for lo, hi, color, label in zones:
        ax.axhspan(lo, hi, color=color, alpha=0.15)
        ax.text(2, (lo + hi) / 2, label, color=color, fontsize=9,
                va='center', fontweight='bold')
    ax.axvspan(15, 60, color='gold', alpha=0.10)
    ax.axvspan(120, 180, color='gold', alpha=0.10)
    ymax = pct_ylim[1]
    ax.text(37, ymax * 0.88, '做T①\n9:45-10:30', ha='center', fontsize=8, color='darkgoldenrod')
    ax.text(150, ymax * 0.88, '做T②\n13:00-14:00', ha='center', fontsize=8, color='darkgoldenrod')
    ax.set_title(title, fontsize=11, loc='left')
    ax.set_ylabel('涨跌幅 (%)')
    ax.set_ylim(*pct_ylim)
    ax.legend(fontsize=8.5, loc='lower left', framealpha=0.9)
    ax.grid(alpha=0.25)
    # 右轴 = 绝对价格
    ax2 = ax.twinx()
    ax2.set_ylim(prev_close * (1 + pct_ylim[0] / 100), prev_close * (1 + pct_ylim[1] / 100))
    ax2.set_ylabel('价格 (元)', color='dimgray')
    ax2.tick_params(axis='y', labelcolor='dimgray')

fig, axes = plt.subplots(2, 1, figsize=(11, 9), sharex=True)
fig.suptitle('2026-08-24（周一）走势预测 v2 · 竞价校准版（09:18 实况）\n'
             '588200/牧原竞价平开 | 诺德+5.4%、大东南+4.0%竞价异动 | 日经-0.9%、三星-4.8%',
             fontsize=12, fontweight='bold')

# 588200：竞价平开 → 基准剧本开盘从 -0.7% 修正为 0%
draw(
    axes[0], 1.173,
    '588200 科创芯片ETF（昨收 1.173 | 竞价平开 | 成本 1.555 | 上周缩量4连跌）',
    [
        ('基准(50%)：平开震荡，下探-1.3%后回升，收平附近',
         [(0, 0.0), (25, -0.6), (50, -1.3), (75, -1.0), (120, -0.6), (170, -0.2), (239, -0.1)], 'royalblue'),
        ('乐观(30%)：AI叙事发酵，冲+1.5%（反T区）',
         [(0, 0.2), (30, 0.8), (60, 1.6), (100, 1.4), (180, 1.7), (239, 1.5)], 'seagreen'),
        ('悲观(20%)：吸血恐慌+外围拖累，放量破-2%',
         [(0, -0.4), (30, -1.4), (55, -2.1), (90, -2.5), (160, -3.0), (239, -2.7)], 'firebrick'),
    ],
    (-3.5, 2.5),
    zones=[
        (1.54, 1.88, 'red', '反T卖区 1.191-1.195 (+1.5~1.9%)'),
        (-1.96, -1.53, 'green', '正T买区 1.150-1.155 (-2.0~-1.5%)'),
    ],
)
axes[0].axhline(-2.81, color='red', ls=':', lw=1.2)
axes[0].text(130, -2.9, '认错线 1.140 (-2.8%)', color='red', fontsize=9)

# 牧原：竞价平开，弱震荡
draw(
    axes[1], 39.07,
    '牧原股份 002714（昨收 39.07 | 竞价平开 | 不做日内T，看周线波段）',
    [
        ('基准(55%)：平开弱震荡 -0.7%~+0.3%',
         [(0, 0.0), (30, -0.4), (60, -0.2), (120, -0.4), (180, 0.0), (239, -0.1)], 'royalblue'),
        ('乐观(25%)：猪周期预期发酵 +1.4%',
         [(0, 0.2), (40, 0.7), (90, 1.3), (150, 1.1), (239, 1.3)], 'seagreen'),
        ('悲观(20%)：板块弱势下探 -1.4%',
         [(0, -0.3), (50, -0.9), (120, -1.2), (200, -1.4), (239, -1.3)], 'firebrick'),
    ],
    (-2.5, 2.2),
    zones=[(-0.82, -0.57, 'green', '支撑 38.8 (-0.7%)')],
)

ticks = [0, 30, 60, 90, 120, 150, 180, 210, 239]
axes[1].set_xticks(ticks)
axes[1].set_xticklabels([time_label(t) for t in ticks])
axes[1].set_xlabel('交易时间（9:30-11:30 / 13:00-15:00）')

fig.text(0.01, 0.005, '左轴=涨跌幅% · 右轴=价格 | 预测仅为概率剧本，非投资建议 | 09:18竞价校准', fontsize=8, color='gray')
plt.tight_layout(rect=[0, 0.02, 1, 0.93])
out = r'C:\Users\admin\dev\investment-tool\strategy\2026-08-24-predict-v2.png'
plt.savefig(out, dpi=140, bbox_inches='tight')
print('saved:', out)
