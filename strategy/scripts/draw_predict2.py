# -*- coding: utf-8 -*-
"""2026-08-25 盘前三股分时预测：588200 / 牧原 / ST天际，三情景，Y轴左%右价"""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

def trading_minutes():
    out, t = [], 9*60+30
    while t <= 11*60+30: out.append(t); t += 1
    t = 13*60
    while t <= 15*60: out.append(t); t += 1
    return out

MINS = trading_minutes(); N = len(MINS)

STOCKS = [
 {'name':'588200 科创芯片','prev':1.130,'dec':3,
  'note':'竞价低开-1.5%(1.117)符合基准；费半-4%余波 vs MA120(1.12)+央行宽松',
  'scen':[
    ('基准55%：低开下探1.110-1.112企稳修复', 1.117, 1.110, 45, 1.118, '#1f77b4'),
    ('悲观30%：破1.110探1.095-1.10', 1.117, 1.097, 70, 1.102, '#d62728'),
    ('乐观15%：低开后直接修复翻红', 1.117, 1.112, 25, 1.142, '#2ca02c')],
  'zones':[(-2.5,-1.3,'green','正T买区 1.105-1.115'), (1.8,2.7,'red','反T卖区 1.150-1.160')],
  'stop':-3.54, 'stop_label':'停手线 1.090', 'ylim':(-4.5,3.5)},
 {'name':'牧原股份','prev':38.83,'dec':2,
  'note':'竞价平开0%，符合预期；昨尾盘修复，农业板块昨日强',
  'scen':[
    ('基准55%：平开弱震荡38.3-39.0', 38.83, 38.35, 60, 38.70, '#1f77b4'),
    ('悲观25%：破38.2探37.8', 38.70, 37.80, 90, 37.95, '#d62728'),
    ('乐观20%：农业延续走强', 38.95, 38.60, 30, 39.30, '#2ca02c')],
  'zones':[(-1.37,-1.11,'green','试T买 38.3(100股)'), (0.1,0.44,'red','试T卖 38.9-39.0')],
  'stop':-2.14, 'stop_label':'认错 38.0', 'ylim':(-3,3)},
 {'name':'ST天际','prev':18.35,'dec':2,
  'note':'竞价低开-1.9%开在昨日低点18.00支撑位；先锋洗霸竞价涨停，跟风分化',
  'scen':[
    ('基准45%：18.0附近争夺，17.8-18.4震荡', 18.00, 17.85, 55, 18.15, '#1f77b4'),
    ('悲观30%：破18.0下探17.5-17.6', 18.00, 17.60, 60, 17.70, '#d62728'),
    ('乐观25%：先锋封死带动修复18.5-18.8', 18.00, 17.95, 30, 18.65, '#2ca02c')],
  'zones':[(-2.45,-1.9,'green','生死线 18.00(破则减半)')],
  'stop':-7.36, 'stop_label':'止损线 17.0', 'ylim':(-8.5,8.5)},
]

fig, axes = plt.subplots(3, 1, figsize=(13, 16))
for ax, s in zip(axes, STOCKS):
    pc = s['prev']
    for label, o, lo, lot, c, color in s['scen']:
        anchors=[0,N//4,lot,3*N//4,N-1]
        o_pct,lo_pct,c_pct=(o/pc-1)*100,(lo/pc-1)*100,(c/pc-1)*100
        mid_pct=(o_pct+lo_pct)/2
        vals=[o_pct,mid_pct,lo_pct,(lo_pct+c_pct)/2+0.15,c_pct]
        ys=np.interp(np.arange(N),anchors,vals)
        rs=np.random.RandomState(hash(s['name']+label)%2**31)
        noise=rs.randn(N)*0.045; noise[[0,N-1]]=0
        w=min(5,N//10); k=np.ones(w)/w
        ys[1:-1]=np.convolve(np.concatenate([[ys[0]]*w,ys,[ys[-1]]*w]),k,'same')[w+w//2:w+w//2+N-2] if N>10 else ys[1:-1]
        ys=ys+noise
        ax.plot(range(N),ys,color=color,lw=2 if '基准' in label else 1.5,
                ls='-' if '基准' in label else '--',alpha=0.9,label=label)
    ax.axhline(0,color='#888',ls=':',alpha=0.8)
    for y1,y2,c,lab in s['zones']:
        ax.axhspan(y1,y2,color=c,alpha=0.13)
        ax.text(2,(y1+y2)/2,lab,fontsize=9,color=c,va='center',fontweight='bold')
    if s['stop'] is not None:
        ax.axhline(s['stop'],color='red',ls='-.',alpha=0.7)
        ax.text(N-60,s['stop']+0.08,s['stop_label'],fontsize=9,color='red',fontweight='bold')
    for i,(a,b) in enumerate([(27,60),(150,180)]):
        ax.axvspan(a,b,color='gold',alpha=0.12)
        if i==0: ax.text(a+1,ax.get_ylim()[1] if False else s['ylim'][1]*0.82,'做T窗①',fontsize=9,color='#B8860B')
        else: ax.text(a+1,s['ylim'][1]*0.82,'做T窗②',fontsize=9,color='#B8860B')
    ax.set_xlim(0,N-1); ax.set_ylim(*s['ylim'])
    ticks=[0,30,60,90,120,150,180,210,239]
    ax.set_xticks(ticks); ax.set_xticklabels(['9:30','10:00','10:30','11:00','11:30','13:00','13:30','14:00','15:00'])
    ax.axvline(120,color='#ccc',ls='--',alpha=0.5)
    ax2=ax.twinx()
    ax2.set_ylim(s['ylim'][0]/100*pc+pc, s['ylim'][1]/100*pc+pc)
    ax2.set_ylabel('价格',fontsize=10)
    ax2.yaxis.set_major_formatter(lambda v,p: f"{v:.{s['dec']}f}")
    ax.set_ylabel('涨跌幅 %',fontsize=10)
    ax.set_title(f"{s['name']}  昨收 {pc} ｜ {s['note']}",fontsize=11,fontweight='bold',loc='left')
    ax.legend(fontsize=8,loc='lower right' if '天际' in s['name'] else 'upper right',framealpha=0.9)
    ax.grid(alpha=0.3)

fig.suptitle('2026-08-25（周二）盘前预测 · 持仓三股分时剧本',fontsize=14,fontweight='bold')
fig.tight_layout(rect=[0,0,1,0.97])
out=r'C:\Users\admin\dev\investment-tool\strategy\2026S3/2026-08-25/2026-08-25-0915.png'
fig.savefig(out,dpi=110)
print('saved:',out)
