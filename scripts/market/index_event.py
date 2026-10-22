# -*- coding: utf-8 -*-
"""index_event.py — 策略执行器"指数事件"的动态阈值(10/21 晚用户令: 0.8% 太大, 从检查点动 0.5% 就很可怕, 阈值按市况动态求解; 零 token)

事件定义: 检查点 = 执行器上一次重定策略的时刻(任何原因: 首版 / 成交 / 出区间 / 翻转 / 心跳 / 13:00 …);
          |指数现价 / 检查点价 − 1| ≥ θ 即"指数事件"。检查点在 09:30 之前(09:15 首版)一律按开盘价算 —— 开盘缺口归竞价 / 开盘实况管, 不在这里重复触发。
θ(推荐方案 E1 = "按指数自己近 20 日波动定锚 + 当天第 5 次起逐次加码"; 回测见 docs/research/index_event_threshold_20261021.md):
    σd   = 近 20 个交易日"全天 1 分钟收益平方和"的中位数开方(该指数一个普通交易日的日内已实现波动; 上证 10/21 前约 0.68%)
    θ    = clamp(X × σd × ρ^(−G), LOF × σd, HIF × σd) × (1 + ESC × max(0, 今日已触发指数事件数 − N_FREE))
    X=0.45 → 上证 θ≈0.30%; G=0 (默认不按今日波动比调; G=0.5 = 候选 E2, 今日越活跃越警觉, 回测和 E1 打平, 面板 60~90 秒采样会让 ρ 偏差, 故不默认)
    ESC=0.10, N_FREE=4: 当天前 4 次按 θ, 第 5 次起每多 1 次 θ 放大 10%(10/21 晚用户定)(防暴跌 / 暴涨日一天十几次)
    ρ    = 今日开盘至今已实现波动 / 近 20 日同时段已实现波动中位(开方), 按 30 分钟先验向 1 收缩, 截在 [0.6, 2.5]; 只用于 G>0 和说明文字
    创业板 / 沪深300 有历史分钟线 → 用各自 σd 自动缩放; 中证2000 / 国证2000 没有历史分钟线 → 退回固定值(说明里写明)
数据: 历史 = downloads/market/_minute_hist/<代码>.jsonl(通达信 1 分钟收盘价, 约 60 天) + downloads/quotes/daily/<日线>.json(开盘价);
      当日 = 调用方传入的 bars; 没传可用 bars_today(): 面板 panel_minute.jsonl(实测约 85 秒一个点) → 没有再用 _minute_hist 当日(盘后回放)
API:
    threshold(D, hm, bars_so_far, history=None, key="SH", n_today=0) -> (θ百分比, 说明)
    check(D, checkpoint_hm, now_hm, bars, key="SH", n_today=0) -> (触发?, 幅度百分比(带符号), θ, 说明)
    bars_today(D, key="SH", before=None) -> [(hhmm, 价)]   (第一个点 = 开盘价 "0930", 如果日线里有)
用法: python index_event.py --selftest | --backtest [--key SH|CYB|HS300] | --show --date D [--checkpoint HHMM] [--now HHMM] [--key SH]
首次调用读历史约 0.1~0.3 秒(进程内缓存), 之后每次 threshold / check 约 0.1 毫秒级。
"""
import argparse
import bisect
import datetime as dt
import json
import math
import statistics as st
import sys
import time
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"
HIST = MKT / "_minute_hist"
DAILY = ROOT / "downloads" / "quotes" / "daily"

# 面板键 → (名称, 历史分钟线代码, 日线缓存文件名, 数据缺失时的固定 θ%)
# 固定值 = 0.45 × 10/21 前 20 日 σd(上证 0.675 / 创业板 1.623 / 沪深300 0.727); 中证2000 按日线 ATR 比(2.82/1.45)换算上证 0.30 ≈ 0.60
KEYS = {
    "SH": ("上证", "sh000001", "1_000001", 0.30),
    "CYB": ("创业板", "sz399006", "399006", 0.73),
    "HS300": ("沪深300", "sh000300", None, 0.33),
    "CSI2000": ("中证2000", "sh932000", None, 0.60),
    "GZ2000": ("国证2000", "sz399303", None, 0.60),
}
X, G, LOF, HIF, ESC, N_FREE = 0.35, 0.0, 0.27, 0.67, 0.10, 4   # 10/21 晚用户暂定系数 0.35(拐点), 加码 10%
NH, NH_MIN, N0, RHO = 20, 5, 30, (0.6, 2.5)
WIN = 30

# 交易分钟轴: 0 = 09:30(开盘价), 1..120 = 09:31..11:30, 121..240 = 13:01..15:00
MINS = ["0930"] + [f"{(570 + i) // 60:02d}{(570 + i) % 60:02d}" for i in range(1, 121)] + [f"{(780 + i) // 60:02d}{(780 + i) % 60:02d}" for i in range(1, 121)]
POS = {m: i for i, m in enumerate(MINS)}


def idx_of(hm):
    """HHMM / HH:MM → 交易分钟下标(≤ hm 的最后一个交易分钟; 09:30 前 = 0, 午休 = 120, 15:00 后 = 240)"""
    hm = str(hm).replace(":", "")[:4]
    if hm in POS:
        return POS[hm]
    return max(0, bisect.bisect_right(MINS, hm) - 1)


def _norm(bars):
    """bars: [(hhmm, p)] / [{"t"|"hm"|"barTime", "p"|"close"}] → 按时间排序的 [(hhmm, p)](同一分钟取最后一个, 只留 09:30 起)"""
    out = {}
    for b in bars or []:
        if isinstance(b, dict):
            t = b.get("hm") or b.get("t") or str(b.get("barTime", ""))[11:16]
            p = b.get("p") if b.get("p") is not None else b.get("close")
        else:
            t, p = b[0], b[1]
        if p:
            t = str(t).replace(":", "")[:4]
            if t >= "0930":
                out[t] = float(p)
    return sorted(out.items())


# ---------------- 历史 ----------------
@lru_cache(maxsize=8)
def _daily(fname):
    if not fname:
        return {}
    try:
        k = json.loads((DAILY / f"{fname}.json").read_text(encoding="utf-8")).get("klines") or []
    except (OSError, ValueError):
        return {}
    return {x["d"]: x for x in k}


@lru_cache(maxsize=8)
def _minute_file(sym):
    """{日: [(hhmm, close)]}; 文件缺 / 空 = {}"""
    by = {}
    f = HIST / f"{sym}.jsonl"
    if not sym or not f.exists():
        return by
    with f.open(encoding="utf-8") as fh:
        for l in fh:
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if r.get("close"):
                by.setdefault(r["tradeDate"], []).append((r["barTime"][11:16].replace(":", ""), float(r["close"])))
    return by


def day_path(bars, open_px=None):
    """[(hhmm, p)] → 241 长的价格数组(缺的分钟用前值; 没有开盘价用第一个点)"""
    b = _norm(bars)
    if not b and not open_px:
        return None
    px = [None] * 241
    if open_px:
        px[0] = float(open_px)
    for t, p in b:
        px[idx_of(t)] = p
    last = next(p for p in px if p is not None)
    for i in range(241):
        if px[i] is None:
            px[i] = last
        last = px[i]
    return px


def history_paths(D, key="SH", n=NH):
    """D 之前最近 n 天的 241 价格数组(开盘价取日线缓存)"""
    _, sym, dfile, _ = KEYS[key]
    by, dk = _minute_file(sym), _daily(dfile)
    days = [d for d in sorted(by) if d < D][-n:]
    return {d: day_path(by[d], (dk.get(d) or {}).get("o")) for d in days if len(by[d]) >= 200}


def _cum(paths):
    """每天的累计 r² 数组(长 241)"""
    C = []
    for px in paths.values():
        if not px:
            continue
        c = [0.0] * 241
        for i in range(1, 241):
            r = px[i] / px[i - 1] - 1 if px[i - 1] else 0.0
            c[i] = c[i - 1] + r * r
        C.append(c)
    return C


@lru_cache(maxsize=64)
def _profile(D, key):
    return _cum(history_paths(D, key)) if key in KEYS else []


def sigma_day(C):
    """近 N 日全天已实现波动中位(开方, %)"""
    return math.sqrt(st.median(c[240] for c in C)) * 100


def sigma30(C, i):
    """截至 i 的 30 个交易分钟已实现波动中位(开方, %); 开盘前 30 分钟统一用 09:31~10:00 —— 只给回测方案 B / C 用"""
    b = max(i, WIN)
    a = b - WIN + 1
    return math.sqrt(st.median(c[b] - c[a - 1] for c in C)) * 100


def rho(C, bars, i, n0=N0):
    """今日已实现波动 / 历史同段中位(开方), 向 1 收缩; bars = 今日 [(hhmm, p)](含开盘价更好); → (ρ, 已观察分钟数)"""
    b = [(idx_of(t), p) for t, p in _norm(bars) if idx_of(t) <= i]
    if len(b) < 2:
        return 1.0, 0
    rv = sum((p1 / p0 - 1) ** 2 for (_, p0), (_, p1) in zip(b, b[1:]))
    a, z = b[0][0], b[-1][0]
    span = z - a
    if span <= 0:
        return 1.0, 0
    hv = st.median(c[z] - c[a] for c in C)
    if hv <= 0:
        return 1.0, span
    w = n0 / span
    return min(RHO[1], max(RHO[0], math.sqrt((rv / hv + w) / (1 + w)))), span


# ---------------- API ----------------
def threshold(D, hm, bars_so_far, history=None, key="SH", n_today=0, x=None, g=None):
    """→ (θ%, 说明). history = {日: [(hhmm, p)]} 可选(不给就读 _minute_hist 里 D 之前 20 天); 不够 5 天 → 固定值"""
    x, g = X if x is None else x, G if g is None else g
    name, _, _, fb = KEYS.get(key, (key, None, None, 0.30))
    esc = 1 + ESC * max(0, int(n_today or 0) + 1 - N_FREE)   # 10/21 晚用户定: 第 1~4 次按 θ, 第 5 次 ×1.10, 第 6 次 ×1.20 …(n_today = 已触发次数, 本次是第 n_today+1 次)
    C = _cum({d: day_path(v) for d, v in history.items() if v}) if history is not None else _profile(D, key)
    if len(C) < NH_MIN:
        th = fb * esc
        return round(th, 3), (f"{name} 历史分钟线只有 {len(C)} 天(< {NH_MIN}), 退回固定 θ={fb:.2f}%"
                              + (f" × 加码 {esc:.2f}(今日第 {n_today + 1} 次)" if esc > 1 else ""))
    sd = sigma_day(C)
    i = max(1, idx_of(hm))
    r, span = rho(C, bars_so_far, i)
    raw = x * sd * r ** (-g)
    base = min(HIF * sd, max(LOF * sd, raw))
    th = base * esc
    act = "比平常活跃" if r >= 1.15 else "比平常安静" if r <= 0.87 else "和平常差不多"
    note = (f"{name} θ={th:.2f}% = {x:g} × 近 {len(C)} 日日内波动 σd {sd:.2f}%"
            + (f" × 今日波动比^−{g:g}({r:.2f})" if g else "")
            + ("" if base == raw else f"(截到 {LOF:g}~{HIF:g} 倍 σd)")
            + (f" × 加码 {esc:.2f}(今日已触发 {n_today} 次, 前 {N_FREE} 次不加码)" if esc > 1 else "")
            + f"; 今日至今波动比 {r:.2f}({act}, 开盘至今 {span} 分钟)")
    return round(th, 3), note


def bars_today(D, key="SH", before=None):
    """当日价格点: 面板 panel_minute(实时) → 少于 3 个点就用 _minute_hist 当日(回放); 开盘价取日线缓存(有的话)"""
    cut = (before or "1500").replace(":", "")[:4]
    _, sym, dfile, _ = KEYS.get(key, (key, None, None, None))
    o = (_daily(dfile).get(D) or {}).get("o")
    out = []
    f = MKT / D / "panel_minute.jsonl"
    if f.exists():
        with f.open(encoding="utf-8") as fh:
            for l in fh:
                if f'"k":"{key}"' not in l and f'"k": "{key}"' not in l:
                    continue
                try:
                    r = json.loads(l)
                except ValueError:
                    continue
                t = r.get("t", "").replace(":", "")[:4]
                if r.get("p") and str(r.get("ts", D)).startswith(D) and "0930" <= t <= cut and not ("1130" < t < "1300"):
                    out.append((t, float(r["p"])))
    src = "面板 panel_minute"
    if len(out) < 3:
        hist = [x for x in _minute_file(sym).get(D) or [] if x[0] <= cut]
        if hist:
            out, src = hist, "历史分钟线 _minute_hist"
    if o:   # 日线里有当日开盘价(盘后 / 日线缓存已刷新)就以它为 09:30 点; 面板 09:30:xx 那个点是开盘后几秒的价, 不是开盘价
        out = [("0930", float(o))] + [x for x in out if x[0] > "0930"]
    bars_today.src = src
    return _norm(out)


def check(D, checkpoint_hm, now_hm, bars, key="SH", n_today=0, **kw):
    """→ (触发?, 检查点→现在 幅度%(带符号), θ%, 说明); n_today = 本链今天已经触发过的指数事件次数(给软上限加码用)"""
    name = KEYS.get(key, (key,))[0]
    b = _norm(bars)
    now = str(now_hm).replace(":", "")[:4]
    upto = [x for x in b if x[0] <= now]
    if not upto:
        th, note = threshold(D, now, [], key=key, n_today=n_today, **kw)
        return False, 0.0, th, f"{name} 到 {now} 还没有当日价格点, 不判 | {note}"
    cp_raw = str(checkpoint_hm).replace(":", "")[:4]
    cp = max("0930", cp_raw)
    p_now = upto[-1][1]
    pc = [x for x in upto if x[0] <= cp]
    p_cp = (pc[-1] if pc else upto[0])[1]
    mv = (p_now / p_cp - 1) * 100
    th, note = threshold(D, now, upto, key=key, n_today=n_today, **kw)
    hit = abs(mv) >= th
    cpn = f"开盘价 {p_cp:.2f}(检查点 {cp_raw} 在 09:30 前, 缺口归竞价)" if cp_raw < "0930" else f"{cp[:2]}:{cp[2:]} 价 {p_cp:.2f}"
    return hit, round(mv, 3), th, (f"{'触发' if hit else '未触发'}: {name} 从检查点 {cpn} 到 {upto[-1][0][:2]}:{upto[-1][0][2:]} {p_now:.2f} "
                                   f"走 {mv:+.2f}%, |幅度| {'≥' if hit else '<'} θ {th:.2f}% | {note}")


# ---------------- 回测 ----------------
def atr_pct(D, key, n=14):
    dk = _daily(KEYS[key][2])
    ds = [d for d in sorted(dk) if d < D][-(n + 1):]
    if len(ds) < n + 1:
        return None
    tr = [max(dk[b]["h"], dk[a]["c"]) / dk[a]["c"] - min(dk[b]["l"], dk[a]["c"]) / dk[a]["c"] for a, b in zip(ds, ds[1:])]
    return st.mean(tr) * 100


def scheme_thetas(sc, D, px, key):
    """方案在 D 这天 1..240 每分钟的基础 θ 数组(下标同 MINS; 软上限加码在 simulate 里做)
    sc = ("F", 值) 固定 | ("A", k) 日线 ATR14×k | ("C", k) 30 分钟时段波动 × 今日波动比 × k | ("E", x, g) 推荐族"""
    kind = sc[0]
    if kind == "F":
        return [sc[1]] * 241
    if kind == "A":
        a = atr_pct(D, key)
        return [sc[1] * a if a else KEYS[key][3]] * 241
    C = _profile(D, key)
    if len(C) < NH_MIN:
        return [KEYS[key][3]] * 241
    bars = [(MINS[i], px[i]) for i in range(241)]
    out = [None]
    if kind == "C":       # σ30 已是该指数自己的口径, 截断按上证 0.15~0.80 换算
        s = KEYS[key][3] / 0.30
        for i in range(1, 241):
            r, _ = rho(C, bars[:i + 1], i)
            out.append(min(0.8 * s, max(0.15 * s, sc[1] * r * sigma30(C, i))))
        return out
    x, g = sc[1], sc[2]
    sd = sigma_day(C)
    for i in range(1, 241):
        r = rho(C, bars[:i + 1], i)[0] if g else 1.0
        out.append(min(HIF * sd, max(LOF * sd, x * sd * r ** (-g))))
    return out


def simulate(px, th, hb=60, cool=(3, 5), esc=0.0, n_free=0):
    """一天: 检查点从开盘价起; 13:00 必判 / 心跳 hb 分钟(交易分钟)重置检查点; 冷却 10:30 前 3 分钟后 5 分钟; → [(i, 方向)]"""
    c, last, ev = 0, 0, []
    for i in range(1, 241):
        if i == 121:                      # 13:00 午后必判(价 = 11:30 收)
            c, last = 120, 120
        if hb and i - last >= hb:         # 心跳重定 → 检查点跟着走
            c, last = i, i
            continue
        mv = px[i] / px[c] - 1
        cd = cool[0] if MINS[i] <= "1030" else cool[1]
        if abs(mv) * 100 >= th[i] * (1 + esc * max(0, len(ev) - n_free)) and i - last >= cd:
            ev.append((i, 1 if mv > 0 else -1))
            c, last = i, i
    return ev


def episodes(px, big=0.5, win=30):
    """30 个交易分钟内走 ≥ big% 的段: [(起点 p0, 走到一半 h, 走满 e, 方向)], 不重叠; 起点取段内真正的最低 / 最高点"""
    out, s = [], 0
    while s < 240:
        hit = next((e for e in range(s + 1, min(241, s + win + 1)) if abs(px[e] / px[s] - 1) * 100 >= big), None)
        if hit is None:
            s += 1
            continue
        d = 1 if px[hit] > px[s] else -1
        p0 = min(range(s, hit), key=lambda j: d * px[j])
        e = next(j for j in range(p0 + 1, 241) if d * (px[j] / px[p0] - 1) * 100 >= big)
        h = next(j for j in range(p0 + 1, e + 1) if d * (px[j] / px[p0] - 1) * 100 >= big / 2)
        out.append((p0, h, e, d))
        s = e
    return out


def _px(key, D):
    return day_path(_minute_file(KEYS[key][1])[D], (_daily(KEYS[key][2]).get(D) or {}).get("o"))


def evaluate(days, key, sc, hb=60, big=0.5, esc=0.0, n_free=0):
    per, f15, f30, a30, ep_n, early, late, lag, at_trig, open_n, ths = [], [], [], [], 0, 0, 0, [], [], 0, []
    for D in days:
        px = _px(key, D)
        th = scheme_thetas(sc, D, px, key)
        ths += [th[i] for i in (15, 60, 180)]
        ev = simulate(px, th, hb, esc=esc, n_free=n_free)
        per.append(len(ev))
        open_n += sum(1 for i, _ in ev if i <= 30)
        for i, d in ev:
            if i + 15 <= 240:
                f15.append(d * (px[i + 15] / px[i] - 1) * 100)
            if i + 30 <= 240:
                f30.append(d * (px[i + 30] / px[i] - 1) * 100)
                a30.append(abs(px[i + 30] / px[i] - 1) * 100)
        for p0, h, e, d in episodes(px, big):
            ep_n += 1
            hits = [i for i, dd in ev if dd == d and p0 < i <= e]
            if hits and hits[0] <= h:
                early += 1
            elif hits:
                late += 1
            if hits:
                lag.append(hits[0] - p0)
                at_trig.append(d * (px[hits[0]] / px[p0] - 1) * 100)
    n = len(days)
    q = sorted(per)
    return {"days": n, "mean": st.mean(per), "med": st.median(per), "p90": q[min(n - 1, int(0.9 * n))], "max": max(per),
            "zero": sum(1 for x in per if x == 0) / n, "open": open_n / max(1, sum(per)), "n_ev": sum(per),
            "c15": sum(x > 0 for x in f15) / max(1, len(f15)), "m15": st.mean(f15) if f15 else 0,
            "c30": sum(x > 0 for x in f30) / max(1, len(f30)), "m30": st.mean(f30) if f30 else 0, "a30": st.mean(a30) if a30 else 0,
            "ep": ep_n, "early": early / max(1, ep_n), "any": (early + late) / max(1, ep_n),
            "lag": st.median(lag) if lag else None, "at": st.median(at_trig) if at_trig else None,
            "th_med": st.median(ths), "th_lo": min(ths), "th_hi": max(ths)}


def baseline(days, key):
    """不触发时的基准: 每分钟按"近 15 分钟方向"算 15 / 30 分钟后同向概率与幅度"""
    f15, f30, a30 = [], [], []
    for D in days:
        px = _px(key, D)
        for i in range(15, 211):
            d = 1 if px[i] >= px[i - 15] else -1
            f15.append(d * (px[i + 15] / px[i] - 1) * 100)
            f30.append(d * (px[i + 30] / px[i] - 1) * 100)
            a30.append(abs(px[i + 30] / px[i] - 1) * 100)
    return {"c15": sum(x > 0 for x in f15) / len(f15), "m15": st.mean(f15), "c30": sum(x > 0 for x in f30) / len(f30), "m30": st.mean(f30), "a30": st.mean(a30)}


def eval_days(key, skip=10):
    by = _minute_file(KEYS[key][1])
    return [d for d in sorted(by) if len(by[d]) >= 200][skip:]


def _row(m, label):
    lag = "-" if m["lag"] is None else f"{m['lag']:.0f}"
    at = "-" if m["at"] is None else f"{m['at']:.2f}"
    return (f"| {label} | {m['th_lo']:.2f}~{m['th_med']:.2f}~{m['th_hi']:.2f} | {m['mean']:.2f} / {m['med']:.0f} / {m['p90']} / {m['max']} | {m['zero'] * 100:.0f}% | {m['open'] * 100:.0f}% "
            f"| {m['c15'] * 100:.0f}% / {m['m15']:+.3f} | {m['c30'] * 100:.0f}% / {m['m30']:+.3f} / {m['a30']:.2f} | {m['ep']} | {m['early'] * 100:.0f}% | {m['any'] * 100:.0f}% | {lag} | {at} |")


HEAD = ("| 方案 | θ% 低~中位~高 | 每天触发 均/中位/P90/最多 | 零触发天 | 开盘30分钟占比 | 15分钟后同向率 / 均值% | 30分钟后同向率 / 均值% / 平均绝对幅度% "
        "| 大段数 | 走到一半前抓到 | 走满前抓到 | 首次触发距起点(分钟, 中位) | 触发时已走%(中位) |\n|---|---|---|---|---|---|---|---|---|---|---|---|")


def schemes(key):
    s = KEYS[key][3] / 0.30      # 固定值换算到该指数口径(上证 = 1)
    return [(("F", 0.8), {}, "固定 0.8%(原设计, 对照)"), (("F", 0.5), {}, "固定 0.5%(对照)"), (("F", round(0.3 * s, 2)), {}, f"固定 {0.3 * s:.2f}%(最优固定档)"),
            (("A", 0.25), {}, "A 日线 ATR14×0.25"), (("C", 1.5), {}, "C 30分钟时段波动×今日波动比×1.5"),
            (("E", X, 0.0), {"esc": ESC, "n_free": N_FREE}, f"E1 {X}×σd + 第5次起加码(推荐)"),
            (("E", X, 0.5), {"esc": ESC, "n_free": N_FREE}, f"E2 {X}×σd×ρ^−0.5 + 第5次起加码")]


def backtest(key="SH"):
    big = round(0.5 * KEYS[key][3] / 0.30, 2)
    days = eval_days(key)
    if not days:
        print(f"{KEYS.get(key, (key,))[0]} 没有历史分钟线, 无法回测")
        return
    half = len(days) * 3 // 5
    print(f"## {KEYS[key][0]} 回测: {days[0]} ~ {days[-1]} 共 {len(days)} 天(数据前 10 天只当历史); 大段 = 30 个交易分钟内走 ≥{big}%(一半 = {big / 2:.2f}%); "
          f"心跳 60 分钟 / 13:00 必判 / 冷却 3·5 分钟; 检查点 09:30 从开盘价起\n")
    b = baseline(days, key)
    print(f"基准(任意分钟按近 15 分钟方向): 15 分钟后同向 {b['c15'] * 100:.0f}% / {b['m15']:+.3f}%, 30 分钟后同向 {b['c30'] * 100:.0f}% / {b['m30']:+.3f}% / 平均绝对幅度 {b['a30']:.2f}%\n")
    for nm, ds in (("全部", days), (f"前段 {days[0]}~{days[half - 1]}", days[:half]), (f"后段 {days[half]}~{days[-1]}", days[half:])):
        print(f"### {nm}({len(ds)} 天)\n\n{HEAD}")
        for sc, kw, lab in schemes(key):
            print(_row(evaluate(ds, key, sc, big=big, **kw), lab))
        print()
    print(f"### 心跳敏感性(推荐 E1, 全部天)\n\n{HEAD}")
    for hb in (30, 60, 0):
        print(_row(evaluate(days, key, ("E", X, 0.0), hb=hb, big=big, esc=ESC, n_free=N_FREE), f"E1 心跳 {hb or '无'}"))
    print(f"\n### 推荐 E1 逐日(后段)\n")
    for D in days[half:]:
        px = _px(key, D)
        ev = simulate(px, scheme_thetas(("E", X, 0.0), D, px, key), esc=ESC, n_free=N_FREE)
        eps = episodes(px, big)
        print(f"- {D} θ={scheme_thetas(('E', X, 0.0), D, px, key)[1]:.2f}% 触发 {len(ev)}: {' '.join(MINS[i] + ('↑' if d > 0 else '↓') for i, d in ev) or '-'} | "
              f"大段 {len(eps)}: {' '.join(MINS[p] + '→' + MINS[e] + ('↑' if d > 0 else '↓') for p, h, e, d in eps) or '-'}")


# ---------------- 自测 ----------------
def selftest():
    t0 = time.time()
    D = "2026-10-21"
    # 1) 没历史 → 固定值 + 说明写明
    th, note = threshold("2020-01-02", "1000", [], key="SH")
    assert th == KEYS["SH"][3] and "退回固定" in note, (th, note)
    th, note = threshold(D, "1000", [], key="CSI2000")
    assert th == KEYS["CSI2000"][3] and "退回固定" in note, (th, note)
    th, note = threshold(D, "1000", [], key="CSI2000", n_today=6)
    assert abs(th - KEYS["CSI2000"][3] * (1 + ESC * (6 + 1 - N_FREE))) < 1e-6 and "加码" in note, (th, note)
    # 2) 有历史: 上证 σd 合理, θ 在 [LOF, HIF]×σd 之内, 默认 θ ≈ 0.45 σd
    C = _profile(D, "SH")
    assert len(C) >= NH_MIN, f"上证历史分钟线不够: {len(C)} 天"
    sd = sigma_day(C)
    assert 0.3 < sd < 1.5, sd
    th, note = threshold(D, "1000", [("0930", 3700), ("1000", 3701)])
    assert abs(th - X * sd) < 0.002 and "σd" in note, (th, sd, note)
    # 3) 软上限: 第 1~4 次不加码, 第 5 次 ×1.10, 第 6 次 ×1.20(n_today=5 → 本次第 6 次), 第 8 次 ×1.40
    assert threshold(D, "1000", [], n_today=3)[0] == th and abs(threshold(D, "1000", [], n_today=4)[0] - th * 1.10) < 0.002   # 第 4 次不加码, 第 5 次 ×1.10
    assert abs(threshold(D, "1000", [], n_today=5)[0] - th * 1.20) < 0.002
    assert abs(threshold(D, "1000", [], n_today=7)[0] - th * 1.40) < 0.002
    # 4) G>0(候选 E2): 今日剧烈 → θ 变小(更警觉), 平静 → θ 变大, 都在截断内
    wild = [(MINS[i], 3700 * (1 + 0.003 * (1 if i % 2 else -1))) for i in range(61)]
    calm = [(MINS[i], 3700 * (1 + 0.0001 * (1 if i % 2 else -1))) for i in range(61)]
    tw, nw = threshold(D, MINS[60], wild, g=0.5)
    tc, nc = threshold(D, MINS[60], calm, g=0.5)
    assert tw < tc and LOF * sd - 1e-3 <= tw and tc <= HIF * sd + 1e-3, (tw, tc)
    assert "比平常活跃" in nw and "比平常安静" in nc, (nw, nc)
    # 5) check: 超过 θ 触发 / 不足不触发 / 方向带符号 / 09:30 前检查点 = 开盘价 / 没数据不判
    base = [(MINS[i], 3700.0) for i in range(0, 91)]
    hit, mv, t1, note = check(D, "1000", MINS[91], base + [(MINS[91], 3700 * (1 + 1.2 * th / 100))])
    assert hit and mv > 0 and note.startswith("触发"), (hit, mv, t1, note)
    hit, mv, t1, note = check(D, "1000", MINS[91], base + [(MINS[91], 3700 * (1 - 0.5 * th / 100))])
    assert not hit and mv < 0 and note.startswith("未触发"), (hit, mv, note)
    hit, mv, t1, note = check(D, "1000", MINS[91], base + [(MINS[91], 3700 * (1 - 1.1 * th / 100))])
    assert hit and mv < 0, (hit, mv)
    hit, mv, t1, note = check(D, "0915", "0945", [("0930", 3700), ("0945", 3700 * 1.01)])
    assert hit and abs(mv - 1.0) < 1e-6 and "开盘价" in note, (hit, mv, note)
    hit, mv, t1, note = check(D, "1000", "1001", [])
    assert not hit and "没有当日价格点" in note, note
    # 6) 当日数据: 10/21 面板有上证点, 第一个点是开盘价; 面板没有的日子退回历史分钟线
    b = bars_today(D, "SH")
    assert len(b) >= 100 and b[0][0] == "0930", (len(b), b[:2])
    src21 = bars_today.src
    b2 = bars_today("2026-10-16", "SH")
    assert len(b2) >= 200 and "历史" in bars_today.src, (len(b2), bars_today.src)
    # 7) 回放 10/21: 推荐方案(心跳 60)触发次数在合理范围
    px = _px("SH", D)
    ev = simulate(px, scheme_thetas(("E", X, 0.0), D, px, "SH"), esc=ESC, n_free=N_FREE)
    assert 1 <= len(ev) <= 10, ev
    # 8) 创业板有历史 → 不是固定值; 自动按自身波动缩放(θ 明显大于上证)
    tcyb, ncyb = threshold(D, "1000", [], key="CYB")
    assert "退回固定" not in ncyb and tcyb > th * 1.8, (tcyb, ncyb)
    # 9) 速度: 热缓存下 1000 次 check(60 个点) < 1 秒
    t1 = time.time()
    for _ in range(1000):
        check(D, "1000", "1030", b[:62])
    per = time.time() - t1
    assert per < 1.0, f"1000 次 check 用了 {per:.2f} 秒"
    print(f"自测通过(9 组断言): 上证 σd {sd:.3f}% → θ {th:.2f}%(第 5 次 {th * 1.10:.2f}% / 第 8 次 {th * 1.40:.2f}%); 创业板 θ {tcyb:.2f}%; "
          f"E2 剧烈 {tw:.2f}% / 平静 {tc:.2f}%; 10/21 当日数据源 {src21}, 回放(心跳 60)触发 {len(ev)} 次 "
          f"{[MINS[i] + ('↑' if d > 0 else '↓') for i, d in ev]}; 1000 次 check {per * 1000:.0f} 毫秒; 总耗时 {time.time() - t0:.2f} 秒(含读历史)")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--key", default="SH")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--checkpoint", default="0930")
    ap.add_argument("--now", default=None)
    ap.add_argument("--n-today", type=int, default=0)
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif a.backtest:
        backtest(a.key)
    elif a.show:
        b = bars_today(a.date, a.key, a.now)
        now = a.now or (b[-1][0] if b else "1500")
        print(check(a.date, a.checkpoint, now, b, key=a.key, n_today=a.n_today)[3], f"(当日数据源: {getattr(bars_today, 'src', '?')})")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
