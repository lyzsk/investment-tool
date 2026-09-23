#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
indicators.py — 技术指标层（k3-inv 决策第二步）
RSI(6/14) MACD(12/26/9) KDJ(9/3/3) CCI(14) BOLL(20,2) MA(5/10/20/60/120) ATR(14) 量比(5日)
用法: python indicators.py <code> [--n 60] [--tail 5]
数据: 复用 fetch_klines 多源（腾讯→东财→新浪）
"""
import sys, math
sys.path.insert(0, __file__.rsplit('\\',1)[0].rsplit('/',1)[0])
from fetch_klines import fetch as _fetch

def fetch_day(code, n):
    return _fetch(code, 'day', n)

def ema(vals, n):
    k = 2/(n+1); out=[vals[0]]
    for v in vals[1:]: out.append(v*k + out[-1]*(1-k))
    return out

def sma(vals, n):
    return [sum(vals[i-n+1:i+1])/n if i>=n-1 else None for i in range(len(vals))]

def rsi(closes, n):
    gains=[max(closes[i]-closes[i-1],0) for i in range(1,len(closes))]
    losses=[max(closes[i-1]-closes[i],0) for i in range(1,len(closes))]
    ag=ema(gains,n); al=ema(losses,n)
    return [None]+[100-100/(1+g/l) if l>0 else 100 for g,l in zip(ag,al)]

def macd(closes, fast=12, slow=26, sig=9):
    ef=ema(closes,fast); es=ema(closes,slow)
    dif=[a-b for a,b in zip(ef,es)]
    dea=ema(dif,sig)
    bar=[(d-e)*2 for d,e in zip(dif,dea)]
    return dif, dea, bar

def kdj(highs,lows,closes,n=9):
    ks=[]; ds=[]
    for i in range(len(closes)):
        lo=min(lows[max(0,i-n+1):i+1]); hi=max(highs[max(0,i-n+1):i+1])
        rsv=(closes[i]-lo)/(hi-lo)*100 if hi>lo else 50
        ks.append(rsv/3 + (ks[-1]*2/3 if ks else 50/3*2))
        ds.append(ks[-1]/3 + (ds[-1]*2/3 if ds else 50/3*2))
    return ks, ds, [3*k-2*d for k,d in zip(ks,ds)]

def cci(highs,lows,closes,n=14):
    tp=[(h+l+c)/3 for h,l,c in zip(highs,lows,closes)]
    out=[]
    for i in range(len(tp)):
        if i<n-1: out.append(None); continue
        win=tp[i-n+1:i+1]; ma=sum(win)/n; md=sum(abs(x-ma) for x in win)/n
        out.append((tp[i]-ma)/(0.015*md) if md>0 else 0)
    return out

def boll(closes,n=20,mult=2):
    out=[]
    for i in range(len(closes)):
        if i<n-1: out.append((None,None,None)); continue
        win=closes[i-n+1:i+1]; ma=sum(win)/n
        sd=math.sqrt(sum((x-ma)**2 for x in win)/n)
        out.append((ma+mult*sd, ma, ma-mult*sd))
    return out

def atr(highs,lows,closes,n=14):
    trs=[max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1,len(closes))]
    return [None]+ema(trs,n)

def main():
    code = sys.argv[1] if len(sys.argv)>1 else 'sz002714'
    n = int(sys.argv[sys.argv.index('--n')+1]) if '--n' in sys.argv else 60
    tail = int(sys.argv[sys.argv.index('--tail')+1]) if '--tail' in sys.argv else 5
    bars, src = fetch_day(code, n+30)
    bars = bars[-n:]
    c=[b['c'] for b in bars]; h=[b['h'] for b in bars]; l=[b['l'] for b in bars]; v=[b['vol'] for b in bars]
    ma={k: sma(c,k) for k in (5,10,20,60,120)}
    r6=rsi(c,6); r14=rsi(c,14)
    dif,dea,bar=macd(c)
    k,d,j=kdj(h,l,c)
    cc=cci(h,l,c)
    bo=boll(c)
    at=atr(h,l,c)
    vma5=sma(v,5)
    print(f"{code} 源:{src} 样本:{len(bars)}")
    print(f"{'日期':<10} {'收盘':>7} {'RSI6':>5} {'RSI14':>6} {'DIF':>6} {'DEA':>6} {'K':>5} {'D':>5} {'J':>6} {'CCI':>7} {'BOLL上':>7} {'BOLL下':>7} {'量比5':>5}")
    for i in range(len(bars)-tail, len(bars)):
        b=bars[i]
        def f(x,w=6,p=2): return f"{x:>{w}.{p}f}" if isinstance(x,(int,float)) else ' '*w
        print(f"{b['t']:<10} {b['c']:>7} {f(r6[i],5,1)} {f(r14[i],6,1)} {f(dif[i],6)} {f(dea[i],6)} {f(k[i],5,1)} {f(d[i],5,1)} {f(j[i],6,1)} {f(cc[i],7,1)} {f(bo[i][0],7)} {f(bo[i][2],7)} {f(v[i]/vma5[i] if vma5[i] else None,5,2)}")
    i=len(bars)-1
    print(f"\n最新快照: 收{c[i]} | MA5 {ma[5][i]:.2f} MA10 {ma[10][i]:.2f} MA20 {ma[20][i]:.2f} MA60 {ma[60][i]:.2f}" + (f" MA120 {ma[120][i]:.2f}" if ma[120][i] else ""))
    print(f"RSI6 {r6[i]:.1f} RSI14 {r14[i]:.1f} | DIF {dif[i]:.3f} DEA {dea[i]:.3f} MACD柱 {bar[i]:.3f} | K {k[i]:.1f} D {d[i]:.1f} J {j[i]:.1f} | CCI {cc[i]:.1f} | BOLL {bo[i][2]:.2f}~{bo[i][0]:.2f} | ATR {at[i]:.2f}({at[i]/c[i]*100:.1f}%)")

if __name__ == '__main__':
    main()
