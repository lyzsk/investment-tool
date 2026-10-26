# -*- coding: utf-8 -*-
"""pa_reason.py — 逐根 K 线可解释推理原型(10/26 用户要: 可解释 + 可用; 零 token, 不调 LLM, 只读行情库)

参考: PA_Agent(bar_by_bar_summary 的 role / trapped_side / context_effect 字段 + "每个数字都要和随机基线比")、
      price-action-lab(三层: 先机械计数 → 再资格审核 → 再可执行性; "系统事实决定结论, 叙述只能引用事实")
输出三段, 每一步都带依据(本地数据算出的数 / KD·KS 规则编号 / 样本 n / 基准):
  ① 最近 5 根 K 线逐根: 形态事实 → 谁在买 / 谁被套 / 哪里有抛压或支撑
  ② 当前背景: 箱体(KD1)、20 日位置(KD7)、近 5 日上方套牢盘、情绪(全市场涨停家数)、龙虎榜、导师同票
  ③ 未来 2 根: 全市场同状态历史样本(只用 T 之前已走完的) → 抛压能不能冲过 / 支撑守不守 / T+1 走法概率 / 竞价开盘条件切换表 / T+2 分支
     每个概率都并列"无条件基准"(同票型不加条件 / 全样本), 差值才是信息量
用法:
  python pa_reason.py 002307 2026-10-23 [--json out.json] [--rebuild]
数据: investment_market.kline_day / security_master / lhb_stock / lhb_seat(只 SELECT, 会话只读)·
      investment_tool.tzzb_record(导师逐笔, 只 SELECT)· downloads/quotes/stock/minute_path/<日>.jsonl(分钟路径)·
      scripts/kline_study/draw_box.py seg_boxes(段式箱体)
缓存: results/kline/_pa_reason_cache.npz(全市场日线, 截止日变了自动重建; 只是本脚本自己的缓存, 不进库)
走法 8 种的名字和阈值照 scen_v2.py 文档串(独立实现, 不 import —— scen_v2 正在重写; 它定稿后改成直接调它的概率)
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(Path(__file__).resolve().parent)]
CACHE = ROOT / "results" / "kline" / "_pa_reason_cache.npz"
MINUTE = ROOT / "downloads" / "quotes" / "stock" / "minute_path"
SINCE = "2024-01-01"
WAYS = ["涨停", "冲高A杀", "高开低走", "单边上涨", "震荡", "深V", "单边下跌", "跌停"]
MIN_N = 100   # 同状态样本少于 100 就逐级放宽(30 时百洋股份只剩 n=36, 概率差全是噪声)


# ---------------------------------------------------------------- 数据
def db(database="investment_market"):
    """连接口径抄 scripts/live/plan_review.py db(); 会话只读, 本脚本只发 SELECT"""
    import pymysql
    yml = (ROOT / "inv-admin/src/main/resources/application.yml").read_text(encoding="utf-8")
    pw = re.search(r"password:\s*\"?([^\"\r\n]+)", yml).group(1).strip()
    conn = pymysql.connect(host="localhost", port=3306, user="root", password=pw, database=database, charset="utf8mb4", autocommit=True, read_timeout=900)
    with conn.cursor() as c:
        c.execute("SET SESSION TRANSACTION READ ONLY")
    return conn


def sym_of(code):
    return ("sh" if code.startswith(("6", "9")) else "sz") + code


def lim_k(sym):
    """涨跌幅档: 20cm 板 ×2(阈值按 scen_v2 文档: 10cm / 20cm 自动 ×1 / ×2)"""
    return 2.0 if sym[2:4] in ("30", "68") else 1.0


def load_market(T, rebuild=False):
    """全市场(沪深主板 + 创业板 + 科创板, 非 ST)日线 → 扁平数组, 按 (票, 日) 排序"""
    if CACHE.exists() and not rebuild:
        z = np.load(CACHE, allow_pickle=True)
        if str(z["T"]) >= T:
            return {k: z[k] for k in z.files}
    conn = db()
    import pymysql.cursors
    c = conn.cursor(pymysql.cursors.SSCursor)
    c.execute("select k.symbol, cast(to_days(k.trade_date) as signed), cast(k.open as double), cast(k.high as double), cast(k.low as double), cast(k.close as double), "
              "cast(k.pre_close as double), cast(k.volume as double), cast(k.amount as double), cast(ifnull(k.limit_up, 0) as double), cast(ifnull(k.limit_down, 0) as double) "
              "from kline_day k "
              "where k.symbol in (select symbol from security_master where sec_type = 'STOCK' and is_deleted = 0 and ifnull(is_st, 0) = 0) and k.trade_date >= %s and k.is_deleted = 0 and (k.symbol like 'sh60%%' or k.symbol like 'sh68%%' or k.symbol like 'sz00%%' or k.symbol like 'sz30%%') "
              "order by k.symbol, k.trade_date", (SINCE,))
    syms, rows = {}, []
    while True:
        part = c.fetchmany(200000)
        if not part:
            break
        for r in part:
            rows.append((syms.setdefault(r[0], len(syms)), *r[1:]))
    conn.close()
    A = np.array(rows, dtype=float)
    S = np.array(sorted(syms, key=syms.get))
    out = {"sid": A[:, 0].astype(np.int32), "day": A[:, 1].astype(np.int32), "o": A[:, 2], "h": A[:, 3], "l": A[:, 4], "c": A[:, 5], "pc": A[:, 6],
           "v": A[:, 7], "amt": A[:, 8], "up": A[:, 9], "dn": A[:, 10], "syms": S, "T": np.array(T)}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(CACHE, **out)
    return out


def to_days(d):
    import datetime as dt
    return dt.date.fromisoformat(d).toordinal() + 365   # MySQL TO_DAYS 比 python ordinal 大 365(TO_DAYS("2007-10-07")=733321)


def from_days(n):
    import datetime as dt
    return dt.date.fromordinal(int(n) - 365).isoformat()


# ---------------------------------------------------------------- 全市场特征
def features(M):
    sid, c, pc, o, h, l_, v, amt = M["sid"], M["c"], M["pc"], M["o"], M["h"], M["l"], M["v"], M["amt"]
    n = len(c)
    k = np.array([lim_k(s) for s in M["syms"]])[sid]
    p = np.where(k > 1.5, 0.2, 0.1)
    up = np.where(M["up"] > 0, M["up"], np.round(pc * (1 + p) + 1e-9, 2))
    dn = np.where(M["dn"] > 0, M["dn"], np.round(pc * (1 - p) + 1e-9, 2))
    same1 = np.r_[False, sid[1:] == sid[:-1]]          # 和前一行同票
    sealed = c >= up - 0.005
    hit = h >= up - 0.005
    dnc = c <= dn + 0.005
    psealed = np.r_[False, sealed[:-1]] & same1
    r = (c / pc - 1) * 100 / k                            # 按 10cm 口径归一的涨跌
    typ = np.full(n, "普通", dtype=object)
    typ[(~hit) & (r <= -7)] = "大跌"
    typ[(~hit) & (r >= 7)] = "大涨"
    typ[dnc] = "跌停"
    typ[psealed & ~hit] = "断板"
    typ[hit & ~sealed] = "炸板"
    typ[sealed] = "首板"
    typ[sealed & psealed] = "连板中"
    pb = np.select([r >= 5, r >= 2, r > -2, r > -5], ["≥5", "2~5", "−2~2", "−5~−2"], "≤−5")
    # 复权因子(除权日 pre_close ≠ 前一日 close): 往后累乘到最新口径, 只用来比较跨日价位
    g = np.ones(n)
    g[1:] = np.where(same1[1:], pc[1:] / np.where(c[:-1] > 0, c[:-1], 1), 1.0)
    lg = np.log(np.clip(g, 1e-6, None))
    cs = np.cumsum(lg)
    last = np.r_[np.nonzero(sid[1:] != sid[:-1])[0], n - 1]
    endcs = np.repeat(cs[last], np.diff(np.r_[-1, last]))
    F = np.exp(endcs - cs)
    vw = (h + l_ + c) / 3   # 典型价 ≈ 当天成交成本: 库里成交额 10/09 之前全是 NULL, 历史样本只能用它; 统计口径统一用它(个股逐根描述里另报真实均价)
    ac, avw = c * F, vw * F
    # 近 5 日成交里, 成交均价 > 今天收盘(= 买在上面、现在被套)的量占比
    trap_v, tot_v = np.zeros(n), np.zeros(n)
    for lag in range(5):
        ok = np.ones(n, bool)
        if lag:
            ok[:lag] = False
            ok[lag:] = sid[lag:] == sid[:-lag]
        idx = np.arange(n) - lag
        idx[idx < 0] = 0
        vv = np.where(ok, v[idx], 0)
        trap_v += np.where(avw[idx] > ac * 1.0, vv, 0)
        tot_v += vv
    trap = np.where(tot_v > 0, trap_v / np.where(tot_v > 0, tot_v, 1), 0)
    tb = np.select([trap < 0.3, trap < 0.6], ["<30%", "30~60%"], "≥60%")
    # 20 日收盘箱体位置(KD7 口径)
    from numpy.lib.stride_tricks import sliding_window_view as sw
    W = 20
    bp = np.full(n, 0.5)
    if n >= W:
        mx, mn = sw(ac, W).max(1), sw(ac, W).min(1)
        okw = sid[W - 1:] == sid[:n - W + 1]
        val = np.where(mx > mn, (ac[W - 1:] - mn) / np.where(mx > mn, mx - mn, 1), 0.5)
        bp[W - 1:] = np.where(okw, val, 0.5)
    bb = np.select([bp < 0.3, bp <= 0.7], ["下沿", "中部"], "上沿")
    # 波动档: ATR14%(10cm 口径); 前一日票型(T−1 的状态, "炸板次日"和"连板次日"不是一回事)
    trp = np.maximum(h - l_, np.maximum(abs(h - pc), abs(l_ - pc))) / np.where(pc > 0, pc, 1) * 100 / k
    A14 = 14
    atrp = np.full(n, np.nan)
    if n >= A14:
        ok14 = sid[A14 - 1:] == sid[:n - A14 + 1]
        atrp[A14 - 1:] = np.where(ok14, sw(trp, A14).mean(1), np.nan)
    ab = np.select([atrp < 3, atrp < 6], ["<3%", "3~6%"], "≥6%")
    ptyp = np.concatenate([np.array(["无"], dtype=object), typ[:-1]])
    ptyp[~same1] = "无"
    # 情绪: 当天全市场封板家数(scen_v2 口径: <50 冷 / <100 中 / ≥100 热)+ 比前 5 日均值升温还是降温
    days, inv = np.unique(M["day"], return_inverse=True)
    nzt = np.bincount(inv, weights=sealed.astype(float))
    m5 = np.array([nzt[max(0, i - 5):i].mean() if i else nzt[0] for i in range(len(nzt))])
    emo_d = np.where(nzt < 50, "冷", np.where(nzt < 100, "中", "热"))
    trend_d = np.where(nzt >= m5 * 1.15, "升温", np.where(nzt <= m5 * 0.85, "降温", "持平"))
    # 次日 / 第 2 日结果(全部换算成"相对 T 收盘 %")
    nx1 = np.r_[sid[1:] == sid[:-1], False]
    nx2 = np.r_[sid[2:] == sid[:-2], False, False]
    def sh(a, s):
        out = np.full(n, np.nan)
        out[:n - s] = a[s:]
        return out
    o1, h1, l1, c1, pc1, up1, dn1 = (sh(x, 1) for x in (o, h, l_, c, pc, up, dn))
    c2, h2, l2, pc2 = (sh(x, 2) for x in (c, h, l_, pc))
    R = lambda x, b: (x / b - 1) * 100   # noqa: E731
    O1, H1, L1, C1 = R(o1, pc1), R(h1, pc1), R(l1, pc1), R(c1, pc1)
    C2 = ((1 + C1 / 100) * (c2 / pc2) - 1) * 100
    H2 = ((1 + C1 / 100) * (h2 / pc2) - 1) * 100
    L2 = ((1 + C1 / 100) * (l2 / pc2) - 1) * 100
    hiT = (h / c - 1) * 100       # T 的最高相对 T 收盘
    loT = (l_ / c - 1) * 100
    vwT = (vw / c - 1) * 100
    way1 = ways(O1, H1, L1, C1, c1 >= up1 - 0.005, c1 <= dn1 + 0.005, k)
    rng1 = np.where(H1 > L1, (C1 - L1) / np.where(H1 > L1, H1 - L1, 1), 0.5)
    way2 = ways(R(sh(o, 2), pc2), R(h2, pc2), R(l2, pc2), R(c2, pc2), c2 >= sh(up, 2) - 0.005, c2 <= sh(dn, 2) + 0.005, k)
    yz1 = (o1 >= up1 - 0.005) & (l1 >= up1 - 0.005)
    return {"k": k, "up": up, "dn": dn, "typ": typ, "ptyp": ptyp, "ab": ab, "atrp": atrp, "pb": pb, "tb": tb, "trap": trap, "bb": bb, "bp": bp, "emo": emo_d[inv], "emot": trend_d[inv],
            "nzt": nzt[inv], "ok2": nx1 & nx2, "O1": O1, "H1": H1, "L1": L1, "C1": C1, "C2": C2, "H2": H2, "L2": L2, "hiT": hiT, "loT": loT, "vwT": vwT,
            "way1": way1, "way2": way2, "yz1": yz1, "rng1": rng1, "sealed": sealed, "vw": vw, "nzt_by_day": dict(zip(days.tolist(), nzt.tolist()))}


def ways(O, H, L, C, zt, dt_, k):
    """8 种走法(相对 T 收盘 %, 阈值 ×k); 名字 / 阈值照 scen_v2 文档串"""
    pos = np.where(H > L, (C - L) / np.where(H > L, H - L, 1), 0.5)
    w = np.full(len(C), "震荡", dtype=object)
    w[(C <= -3 * k) & (pos <= 0.25)] = "单边下跌"
    w[(C >= 3 * k) & (pos >= 0.75)] = "单边上涨"
    w[(O >= 2 * k) & (C < O - 3 * k)] = "高开低走"
    w[(L <= -5 * k) & (C >= L + 5 * k)] = "深V"
    w[(H >= 5 * k) & (C <= H - 6 * k)] = "冲高A杀"
    w[dt_] = "跌停"
    w[zt] = "涨停"
    return w


# ---------------------------------------------------------------- 统计工具
def q(a, ps=(10, 25, 50, 75, 90)):
    a = a[~np.isnan(a)]
    if not len(a):
        return {}
    return {f"P{p}" if p != 50 else "中位": round(float(np.percentile(a, p)), 1) for p in ps} | {"均值": round(float(a.mean()), 1)}


def pct(mask, base):
    n = int(base.sum())
    return (round(float((mask & base).sum()) / n * 100, 1) if n else None), n


def conf(n, delta):
    """置信: 没有样本外验证, 一律不给"高"; n≥200 且相对基准差 ≥5 个百分点 = 中, 其余低"""
    if n >= 200 and delta is not None and abs(delta) >= 5:
        return "中"
    return "低"


# ---------------------------------------------------------------- 个股: 逐根
def stock_rows(code, T, n=140):
    conn = db()
    c = conn.cursor()
    c.execute("select name from security_master where code=%s and sec_type='STOCK' limit 1", (code,))
    name = (c.fetchone() or [code])[0]
    c.execute("select trade_date, open, high, low, close, pre_close, volume, amount, turnover_rate, limit_up, limit_down from kline_day "
              "where symbol=%s and is_deleted=0 and trade_date<=%s order by trade_date desc limit %s", (sym_of(code), T, n))
    R = [(str(r[0]), *(float(x or 0) for x in r[1:])) for r in c.fetchall()][::-1]
    conn.close()
    return name, R


def minute_day(code, d):
    """分钟路径: downloads/quotes/stock/minute_path/<d>.jsonl(p = 241 个分钟价, v = 分钟量)"""
    f = MINUTE / f"{d}.jsonl"
    if not f.exists():
        return None
    key = f'"code": "{code}"'
    with f.open(encoding="utf-8") as fh:
        for line in fh:
            if key in line:
                x = json.loads(line)
                if x.get("d") == d:
                    return x
    return None


def minute_facts(m, up):
    p, v = np.array(m["p"], float), np.array(m.get("v") or [0] * len(m["p"]), float)
    at = p >= up - 0.005
    t = lambda i: f"{9 + (30 + i) // 60:02d}:{(30 + i) % 60:02d}" if i < 120 else f"{13 + (i - 120) // 60:02d}:{(i - 120) % 60:02d}"   # noqa: E731
    out = {"均价": round(float((p * v).sum() / v.sum()), 3) if v.sum() else None, "最低时刻": t(int(p.argmin())), "最高时刻": t(int(p.argmax())),
           "尾盘30分%": round(float((p[-1] / p[-31] - 1) * 100), 2) if len(p) > 31 else None}
    if at.any():
        out["首次触板"] = t(int(np.argmax(at)))
        out["开板次数"] = int(((at[:-1]) & (~at[1:])).sum())
        out["板上成交占比%"] = round(float(v[at].sum() / v.sum() * 100), 1) if v.sum() else None
        out["最后在板上"] = t(int(len(at) - 1 - np.argmax(at[::-1])))
    return out


def bar_type(o, h, l_, c, ph, pl):
    """PA_Agent kline_features._classify_bar 同口径: inside / outside / doji(实体 ≤25%) / trend(收在上 35% 或下 35%)"""
    if h <= ph and l_ >= pl:
        return "inside", "内包(被前一根包住, 观望)"
    if h >= ph and l_ <= pl:
        return ("outside_bull", "阳外包") if c >= o else ("outside_bear", "阴外包")
    rg = h - l_
    if rg <= 0:
        return "flat", "一字"
    body, cp = abs(c - o) / rg, (c - l_) / rg
    if body <= 0.25:
        return "doji", "十字 / 小实体(多空平衡)"
    if c > o and cp >= 0.65:
        return "trend_bull", "多头趋势棒"
    if c < o and cp <= 0.35:
        return "trend_bear", "空头趋势棒"
    return "other", "普通"


def per_bar(code, R, i, ctx):
    d, o, h, l_, c, pc, v, amt, tr, upx, dnx = R[i]
    k = lim_k(sym_of(code))
    up = upx or round(pc * (1 + 0.1 * k) + 1e-9, 2)
    dn = dnx or round(pc * (1 - 0.1 * k) + 1e-9, 2)
    ph, pl = R[i - 1][2], R[i - 1][3]
    vw = amt / v if v and amt else (h + l_ + c) / 3
    v20 = np.mean([r[6] for r in R[max(0, i - 20):i]])
    b10 = np.mean([abs(r[4] - r[1]) for r in R[max(0, i - 10):i]])
    rg = h - l_
    bt, bt_cn = bar_type(o, h, l_, c, ph, pl)
    uw = (h - max(o, c)) / rg if rg else 0
    lw = (min(o, c) - l_) / rg if rg else 0
    cp = (c - l_) / rg if rg else 1
    m = minute_day(code, d)
    mf = minute_facts(m, up) if m else {}
    E, who, trap, sup, rules = [], [], [], [], []
    E.append(f"开 {o:.2f} 高 {h:.2f} 低 {l_:.2f} 收 {c:.2f}({(c / pc - 1) * 100:+.2f}%), 振幅 {rg / pc * 100:.1f}%, 实体 {abs(c - o) / rg * 100 if rg else 0:.0f}% / 上影 {uw * 100:.0f}% / 下影 {lw * 100:.0f}%, 收位 {cp * 100:.0f}%")
    E.append(f"量 = 20 日均量 × {v / v20:.2f}, 换手 {tr:.1f}%, " + (f"当日成交均价 {vw:.2f}" if amt else f"典型价(高+低+收)/3 {vw:.2f}(库里没有成交额)"))
    sealed, hit = c >= up - 0.005, h >= up - 0.005
    # 涨跌停 K 线的几何(实体 / 影线)被价格上限截断, 不按普通 K 线分类(KD3); 板型口径照 intake.facts
    opens = mf.get("开板次数") or 0
    if o >= up - 0.005 and l_ >= up - 0.005:
        bt, bt_cn = "limit", "一字板"
    elif sealed and o >= up - 0.005:
        bt, bt_cn = "limit", "T字板" if opens <= 1 else "烂板回封"
    elif sealed:
        bt, bt_cn = "limit", ("烂板回封" if opens >= 2 else "回封板" if opens == 1 else "封板")
    elif hit:
        bt_cn = ("烂板(反复开板没封住)" if opens >= 2 else "炸板") + f" · {bt_cn}"
    elif c <= dn + 0.005:
        bt, bt_cn = "limit", "跌停"
    trapped_side = "none"
    if o >= up - 0.005 and l_ >= up - 0.005:
        who.append("一字板: 只有排板资金买到, 当天没有被套的人")
        rules.append("KD3(一字板不识别形态)")
    elif sealed:
        who.append(f"封板: 打板 / 排板资金在涨停价 {up:.2f} 买入" + (f"(首次触板 {mf['首次触板']}, 开板 {mf['开板次数']} 次, 板上成交占当天 {mf['板上成交占比%']}%)" if mf.get("首次触板") else ""))
        rules.append("KD3")
    elif hit:
        trapped_side = "bulls"
        trap.append(f"炸板: 涨停价 {up:.2f} 买入的打板资金被套 {(c / up - 1) * 100:+.1f}%" + (f"(首次触板 {mf['首次触板']}, 板上成交占当天 {mf['板上成交占比%']}%, 最后在板上 {mf['最后在板上']})" if mf.get("首次触板") else ""))
        rules.append("KD3")
    if c < vw * 0.995:
        trap.append(f"收盘低于当日均价 {vw:.2f}: 当天买入的人平均浮亏 {(c / vw - 1) * 100:.1f}%")
        trapped_side = "bulls"
    elif c > vw * 1.005:
        who.append(f"收盘高于当日均价 {vw:.2f}: 当天买入的人平均浮盈 {(c / vw - 1) * 100:+.1f}%(空头 / 卖出者吃亏)")
        trapped_side = "bears" if trapped_side == "none" else "both"
    if uw >= 0.4 and rg / pc >= 0.04:
        trap.append(f"长上影 {uw * 100:.0f}%: {max(o, c):.2f}~{h:.2f} 是当天卖压区")
    if lw >= 0.4 and rg / pc >= 0.04:
        sup.append(f"长下影 {lw * 100:.0f}%: {l_:.2f}~{min(o, c):.2f} 有承接" + (f"(最低在 {mf['最低时刻']})" if mf.get("最低时刻") else ""))
    if c <= dn + 0.005:
        trap.append(f"跌停 {dn:.2f}: 当天所有买入者被套")
    # 规则命中(KS 编号见 skills/market-skill/persona/kline_rules.md)
    if c > o and abs(c - o) >= 1.5 * b10 and v >= 1.5 * v20 and not sealed:
        rules.append("KS2(非涨停长阳 + 放量 → 之后 5 天统计跑输, h5 按日超额 −0.40%, n=108,267)")
    if cp >= 0.9 and not sealed and rg > 0:
        rules.append("KS3(收在当天最高 10% 非涨停 → 3~5 天跑输, 置信低中)")
    if l_ > R[i - 1][2] and not (o >= up - 0.005 and l_ >= up - 0.005):
        rules.append(f"KS1 前提(上升窗口 {R[i - 1][2]:.2f}~{l_:.2f}; 3 天不补 → 之后 5 天统计跑输, n=11,149)")
    effect = {"trend_bull": "strengthens_bull", "trend_bear": "strengthens_bear", "outside_bull": "strengthens_bull", "outside_bear": "strengthens_bear"}.get(bt, "neutral")
    if bt == "limit":
        effect = "strengthens_bear" if c <= dn + 0.005 else "strengthens_bull"
    if hit and not sealed:
        effect = "weakens_bull"
        rules.append("KS8(炸板状态 → 之后 1~3 日情景按同状态历史样本; 本脚本第③段即此方法)")
    if mf.get("尾盘30分%") is not None:
        E.append(f"分钟: 均价 {mf.get('均价')}, 最低 {mf.get('最低时刻')} / 最高 {mf.get('最高时刻')}, 尾盘 30 分钟 {mf['尾盘30分%']:+.2f}%")
    return {"日": d, "bar_type": bt, "形态": bt_cn, "context_effect": effect, "trapped_side": trapped_side, "事实": E, "谁在买": who, "谁被套 / 抛压": trap, "支撑": sup, "规则": rules}


# ---------------------------------------------------------------- 背景
def background(code, R, M, X, iT):
    import draw_box as DB
    o, h, l_, c, pc = (np.array([r[j] for r in R]) for j in (1, 2, 3, 4, 5))
    tr = np.maximum(h - l_, np.maximum(abs(h - pc), abs(l_ - pc)))
    atr = np.array([tr[max(0, i - 13):i + 1].mean() for i in range(len(tr))])
    segs = DB.seg_boxes(o, h, l_, c, atr, 0)
    cur = segs[-1] if segs and segs[-1][1] == len(c) - 1 else None
    prev_box = segs[-1] if segs and not cur else None
    B = {}
    if cur:
        B["日线箱体(KD1)"] = f"在箱体里: 上沿 {cur[2]:.2f} / 下沿 {cur[3]:.2f}(起 {R[cur[0]][0]}), 现价在箱体 {(c[-1] - cur[3]) / (cur[2] - cur[3]) * 100:.0f}% 位置"
    elif prev_box:
        B["日线箱体(KD1)"] = f"已离箱(趋势段): 上一个箱体 {R[prev_box[0]][0]}~{R[prev_box[1]][0]} 上沿 {prev_box[2]:.2f} / 下沿 {prev_box[3]:.2f}, 现价 {c[-1]:.2f} 在上沿{'上方' if c[-1] > prev_box[2] else '下方'} {(c[-1] / prev_box[2] - 1) * 100:+.1f}%"
    gaps = []
    for j in range(len(R) - 10, len(R)):
        lo_after = min(r[3] for r in R[j:])
        if R[j][3] > R[j - 1][2] and lo_after > R[j - 1][2]:
            gaps.append(f"{R[j][0][5:]} 上升缺口 {R[j - 1][2]:.2f}~{min(R[j][3], lo_after):.2f} 未补(支撑; 见 KS1: 3 天不补之后 5 天统计跑输)")
        hi_after = max(r[2] for r in R[j:])
        if R[j][2] < R[j - 1][3] and hi_after < R[j - 1][3]:
            gaps.append(f"{R[j][0][5:]} 下降缺口 {max(R[j][2], hi_after):.2f}~{R[j - 1][3]:.2f} 未补(压力)")
    B["近 10 日未补缺口"] = gaps or "无"
    B["ATR14"] = f"{atr[-1]:.2f}({atr[-1] / c[-1] * 100:.1f}%)"
    r20 = (c[-1] / c[-21] - 1) * 100 if len(c) > 21 else None
    B["20 日涨跌"] = f"{r20:+.1f}%" if r20 is not None else "-"
    B["20 日收盘箱体位置(KD7)"] = f"{X['bp'][iT] * 100:.0f}%({X['bb'][iT]})"
    B["近 5 日上方套牢盘"] = f"近 5 日成交里 {X['trap'][iT] * 100:.0f}% 的量成交均价高于今天收盘({X['tb'][iT]} 档)"
    B["情绪"] = f"全市场封板 {int(X['nzt'][iT])} 家({X['emo'][iT]}), 比前 5 日均值 {X['emot'][iT]}"
    B["票型"] = f"{X['typ'][iT]}(收盘涨跌 {X['pb'][iT]} 档, 10cm 口径)"
    # 龙虎榜(T 与 T−1)
    try:
        conn = db()
        cc = conn.cursor()
        cc.execute("select trade_date, net_amt, deal_amount, reason from lhb_stock where symbol=%s and is_primary=1 and is_deleted=0 and trade_date<=%s order by trade_date desc limit 2", (sym_of(code), R[-1][0]))
        L = []
        for d, net, deal, rs in cc.fetchall():
            cc.execute("select ifnull(youzi_alias, dept_name), direction, net_amt from lhb_seat where symbol=%s and trade_date=%s and is_deleted=0 order by abs(net_amt) desc limit 3", (sym_of(code), d))
            top = "; ".join(f"{(n or '')[:14]} {'买' if dr == 'BUY' else '卖'} {float(x) / 1e8:+.2f}亿" for n, dr, x in cc.fetchall())
            L.append(f"{d} 净{'买' if float(net) > 0 else '卖'} {float(net) / 1e8:+.2f}亿(占成交 {float(net) / float(deal) * 100:+.1f}%) 前三席位: {top}")
        B["龙虎榜"] = L or "近两次没上榜"
        cc.execute("select ledger, side, count(distinct record_time), round(avg(price), 3), max(record_time) from investment_tool.tzzb_record where record_type='bs_leg' and is_deleted=0 "
                   "and stock_code=%s and record_time >= date_sub(%s, interval 7 day) and record_time < date_add(%s, interval 1 day) group by ledger, side", (code, R[-1][0], R[-1][0]))
        try:
            sys.path.insert(0, str(ROOT / "scripts" / "lib"))
            import skill_names as SKN
            nm = SKN.cn
        except Exception:   # noqa: BLE001
            nm = str
        mt = [f"{nm(lg) or lg} {sd} {n} 笔 均价 {p}(最近 {str(t)[5:16]})" for lg, sd, n, p, t in cc.fetchall()]
        B["导师同票(近 7 天, 同花顺投资账本逐笔)"] = mt or "没有导师操作"
        conn.close()
    except Exception as e:   # noqa: BLE001
        B["龙虎榜"] = f"读不到 {e!r}"[:100]
    return B


# ---------------------------------------------------------------- 未来 2 根
def match(X, iT, base):
    """同状态样本: 票型 + 涨跌档 + 情绪 + 套牢盘档 + 20 日箱体位置, n<MIN_N 逐级放宽"""
    keys = [("typ", "票型"), ("pb", "涨跌档"), ("ptyp", "前一日票型"), ("ab", "波动档ATR14%"), ("emo", "情绪"), ("tb", "套牢盘档"), ("bb", "20日箱体位置")]
    for m in range(len(keys), 0, -1):
        mask = base.copy()
        for kk, _ in keys[:m]:
            mask &= X[kk] == X[kk][iT]
        if mask.sum() >= MIN_N or m == 1:
            return mask, [f"{lab}={X[kk][iT]}" for kk, lab in keys[:m]]
    return base, []


def future(X, M, iT, T):
    Td = to_days(T)
    base = X["ok2"] & (M["day"] < Td)
    # 只用 T 之前就已走完 2 天的样本(第 2 天的日期 < T 当天之后) —— 近似: 信号日 ≤ T 前 3 个交易日
    days = np.unique(M["day"][M["day"] < Td])
    cut = days[-1] if len(days) else Td   # 信号日 ≤ T−2 → 第 2 天 ≤ T, T 收盘时已知
    base &= M["day"] < cut
    base &= ~np.isnan(X["C2"])
    S, lab = match(X, iT, base)
    typ0 = base & (X["typ"] == X["typ"][iT]) & (X["pb"] == X["pb"][iT])   # 基准 = 同票型 + 同涨跌档(只有票型时"普通"有 318 万样本, 基准没意义)
    core = typ0 & (X["pb"] == X["pb"][iT]) & (X["ptyp"] == X["ptyp"][iT]) & (X["ab"] == X["ab"][iT])   # 因子消融的底: 票型 + 涨跌档 + 前一日票型 + 波动档
    if core.sum() < 400:
        core = typ0
    k = X["k"][iT]
    hiT, loT, vwT = X["hiT"][iT], X["loT"][iT], X["vwT"][iT]
    out = {"样本": f"{' + '.join(lab)} → n={int(S.sum())}(基准: 同票型 + 涨跌档 n={int(typ0.sum())}; 全样本 n={int(base.sum())}; 样本期 {SINCE}~{from_days(cut)})"}
    steps = []
    # 步 1: T 最高价那档抛压能不能冲过
    if hiT > 0.3:
        reach = X["H1"] >= X["hiT"] - 1e-6
        rej = reach & (X["C1"] < X["hiT"])
        p_r, n_ = pct(reach, S)
        p_r0, _ = pct(reach, typ0)
        p_j, nr = pct(rej, S & reach)
        p_j0, _ = pct(rej, typ0 & reach)
        steps.append({"步": "抛压①: T 日最高价那档(高位买入者解套位)", "条件": f"T 最高 = 收盘 {hiT:+.1f}%",
                      "统计": f"T+1 冲到 T 最高: {p_r}%(n={n_}; 基准 {p_r0}%)· 冲到之后收盘回到它下方: {p_j}%(n={nr}; 基准 {p_j0}%)",
                      "置信": conf(nr, None if p_j is None or p_j0 is None else p_j - p_j0)})
    # 步 2: T 成交均价(当天买入者成本)
    if vwT > 0.3:
        reach = X["H1"] >= X["vwT"]
        hold = reach & (X["C1"] >= X["vwT"])
        p_r, n_ = pct(reach, S)
        p_h, nr = pct(hold, S & reach)
        p_h0, _ = pct(hold, typ0 & reach)
        steps.append({"步": "抛压②: T 日典型价(高+低+收)/3 ≈ 当天买入者平均成本; 收盘在它下方 = 当天买的人整体被套", "条件": f"T 典型价 = 收盘 {vwT:+.1f}%",
                      "统计": f"T+1 冲到 T 典型价: {p_r}%(n={n_}; 基准 {pct(reach, typ0)[0]}%)· 冲到后收盘站上: {p_h}%(n={nr}; 基准 {p_h0}%)", "置信": conf(nr, None if p_h is None or p_h0 is None else p_h - p_h0)})
    elif vwT < -0.3:
        brk = X["L1"] <= X["vwT"]
        p_b, n_ = pct(brk, S)
        p_b0, _ = pct(brk, typ0)
        steps.append({"步": "支撑①: T 日典型价(高+低+收)/3 在收盘下方(当天买入者整体浮盈, 回落到这里是第一道承接)", "条件": f"T 典型价 = 收盘 {vwT:+.1f}%",
                      "统计": f"T+1 最低跌到 T 典型价: {p_b}%(n={n_}; 基准 {p_b0}%)", "置信": conf(n_, None if p_b is None or p_b0 is None else p_b - p_b0)})
    # 步 3: T 最低(支撑)
    brk = X["L1"] <= X["loT"]
    p_b, n_ = pct(brk, S)
    p_b0, _ = pct(brk, typ0)
    steps.append({"步": "支撑②: T 日最低价", "条件": f"T 最低 = 收盘 {loT:+.1f}%", "统计": f"T+1 跌破 T 最低: {p_b}%(n={n_}; 基准 {p_b0}%)",
                  "置信": conf(n_, None if p_b is None or p_b0 is None else p_b - p_b0)})
    # 步 4: 多空力量 —— 情绪 / 套牢盘 两个因子的"拿掉试试"(同票型内, 只改这一个因子看 T+1 收盘中位差多少)
    for kk, lab_ in (("ptyp", "前一日票型"), ("ab", "波动档"), ("emo", "情绪"), ("emot", "情绪方向"), ("tb", "上方套牢盘"), ("bb", "20日箱体位置")):
        bs_ = (typ0 & (X["pb"] == X["pb"][iT])) if kk in ("ptyp", "ab") else core   # 核心状态里本身含 前一日票型 / 波动档, 这两个在 票型 + 涨跌档 里消融
        A_ = bs_ & (X[kk] == X[kk][iT])
        B_ = bs_ & (X[kk] != X[kk][iT])
        if A_.sum() >= 20 and B_.sum() >= 20:
            ma, mb = np.nanmedian(X["C1"][A_]), np.nanmedian(X["C1"][B_])
            ua, ub = (X["way1"][A_] == "涨停").mean() * 100, (X["way1"][B_] == "涨停").mean() * 100
            steps.append({"步": f"多空力量: {lab_}", "条件": f"{lab_}={X[kk][iT]}",
                          "统计": f"{'同票型 + 涨跌档' if kk in ('ptyp', 'ab') else '同核心状态(票型 + 涨跌档 + 前一日票型 + 波动档)'}里 {lab_}={X[kk][iT]} 的 T+1 收盘中位 {ma:+.1f}% / 涨停 {ua:.0f}%(n={int(A_.sum())}) vs 其余 {mb:+.1f}% / {ub:.0f}%(n={int(B_.sum())}) → 差 {ma - mb:+.1f} 个点",
                          "置信": "中" if min(A_.sum(), B_.sum()) >= 200 and (abs(ua - ub) >= 5 or abs(ma - mb) >= 2) else "低"})
    out["推理步"] = steps
    # 步 5: T+1 走法概率(top3 + 极端)
    W1 = Counter(X["way1"][S])
    W0 = Counter(X["way1"][typ0])
    n, n0 = sum(W1.values()), sum(W0.values())
    top = [(w, W1[w] / n * 100, W0[w] / n0 * 100 if n0 else 0) for w, _ in W1.most_common()]
    out["T+1 走法"] = [{"走法": w, "概率%": round(p, 1), "基准%": round(b, 1), "差": round(p - b, 1),
                       "T+1 收盘 P25/中位/P75": [round(float(np.nanpercentile(X["C1"][S & (X["way1"] == w)], z)), 1) for z in (25, 50, 75)]} for w, p, b in top]
    out["T+1 全分布"] = {"开盘": q(X["O1"][S]), "最高": q(X["H1"][S]), "最低": q(X["L1"][S]), "收盘": q(X["C1"][S]), "一字涨停(买不进)%": round(float(X["yz1"][S].mean() * 100), 1)}
    # 步 6: 竞价开盘 → 走法切换表(9:25 就能看到的条件)
    edges = [-99, -3 * k, 0, 3 * k, 6 * k, 99]
    labs = [f"≤{-3 * k:.0f}%", f"{-3 * k:.0f}~0%", f"0~{3 * k:.0f}%", f"{3 * k:.0f}~{6 * k:.0f}%", f"≥{6 * k:.0f}%"]
    sw_ = []
    for a, b, lb in zip(edges, edges[1:], labs):
        mm = S & (X["O1"] > a) & (X["O1"] <= b)
        if mm.sum() < 10:
            mm2 = typ0 & (X["O1"] > a) & (X["O1"] <= b)
            src = "同票型 + 涨跌档"
        else:
            mm2, src = mm, "同状态"
        if mm2.sum() < 10:
            continue
        cw = Counter(X["way1"][mm2]).most_common(2)
        nn = int(mm2.sum())
        sw_.append(f"开在 {lb}: 占 {mm.sum() / max(1, S.sum()) * 100:.0f}% · 最可能 {cw[0][0]} {cw[0][1] / nn * 100:.0f}%" + (f" / {cw[1][0]} {cw[1][1] / nn * 100:.0f}%" if len(cw) > 1 else "")
                   + f" · 收盘中位 {np.nanmedian(X['C1'][mm2]):+.1f}%(n={nn}, {src})")
    out["竞价开盘切换"] = sw_
    # 步 7: T+2 分支(按 T+1 前两种走法)
    br = []
    for w, _, _ in top[:2]:
        mm = S & (X["way1"] == w)
        src = "同状态"
        if mm.sum() < 20:
            mm, src = typ0 & (X["way1"] == w), "同票型 + 涨跌档"
        if mm.sum() < 10:
            continue
        cw = Counter(X["way2"][mm]).most_common(3)
        nn = int(mm.sum())
        br.append(f"若 T+1 = {w}: T+2 收盘(相对 T 收盘)中位 {np.nanmedian(X['C2'][mm]):+.1f}% [P25 {np.nanpercentile(X['C2'][mm], 25):+.1f} / P75 {np.nanpercentile(X['C2'][mm], 75):+.1f}] · "
                  f"T+2 走法 " + " / ".join(f"{a} {b / nn * 100:.0f}%" for a, b in cw) + f"(n={nn}, {src})")
    out["T+2 分支"] = br
    return out


def story(name, code, T, bars, B, Fu):
    """把推理步串成一句"故事", 每个分句后面括号里写依据; 不新增任何判断"""
    L = []
    last = bars[-1]
    L.append(f"{T} {last['形态']}" + (f", {last['谁被套 / 抛压'][0]}" if last["谁被套 / 抛压"] else ""))
    for s in Fu["推理步"][:3]:
        L.append(f"{s['步'].split(':')[0]} → {s['统计']}")
    t1 = Fu["T+1 走法"][:3]
    L.append("T+1 最可能: " + " / ".join(f"{x['走法']} {x['概率%']}%(基准 {x['基准%']}%)" for x in t1))
    top_w = t1[0]["走法"] if t1 else ""
    alt = [x for x in Fu["竞价开盘切换"] if f"最可能 {top_w}" not in x]
    if alt:
        L.append("转换条件(竞价可见): " + " | ".join(alt))
    return " ⟶ ".join(L)


def run(code, T, rebuild=False):
    M = load_market(T, rebuild)
    X = features(M)
    name, R = stock_rows(code, T)
    if R[-1][0] != T:
        raise SystemExit(f"{code} 在 {T} 没有日线(最后一根 {R[-1][0]})")
    s = np.nonzero(M["syms"] == sym_of(code))[0]
    if not len(s):
        raise SystemExit(f"{code} 不在全市场样本里(ST / 北交所 / 非股票?)")
    idx = np.nonzero((M["sid"] == s[0]) & (M["day"] == to_days(T)))[0]
    if not len(idx):
        raise SystemExit("全市场缓存里没有截止日这一根, 加 --rebuild")
    iT = int(idx[0])
    bars = [per_bar(code, R, i, None) for i in range(len(R) - 5, len(R))]
    B = background(code, R, M, X, iT)
    Fu = future(X, M, iT, T)
    return {"code": code, "name": name, "T": T, "逐根": bars, "背景": B, "未来2根": Fu, "串联": story(name, code, T, bars, B, Fu)}


def render(o):
    L = [f"# {o['name']}({o['code']}) 截至 {o['T']} · 逐根推理(pa_reason 原型, 零 token)", "", "## ① 最近 5 根(K5 → K1, K1 = 截止日)"]
    for j, b in enumerate(o["逐根"]):
        L.append(f"- **K{5 - j} {b['日']} {b['形态']}**(bar_type={b['bar_type']} · context_effect={b['context_effect']} · trapped_side={b['trapped_side']})")
        for kk in ("事实", "谁在买", "谁被套 / 抛压", "支撑", "规则"):
            if b[kk]:
                L.append(f"  - {kk}: " + "; ".join(b[kk]))
    L += ["", "## ② 当前背景"]
    for k_, v in o["背景"].items():
        L.append(f"- {k_}: " + ("; ".join(v) if isinstance(v, list) else str(v)))
    F = o["未来2根"]
    L += ["", "## ③ 未来 2 根", f"- 取样: {F['样本']}"]
    for s in F["推理步"]:
        L.append(f"- {s['步']} [{s['条件']}] → {s['统计']} · 置信 {s['置信']}")
    L.append("- T+1 走法(概率 / 基准 / 差 / 该走法的 T+1 收盘 P25·中位·P75):")
    for x in F["T+1 走法"][:5]:
        L.append(f"  - {x['走法']} {x['概率%']}%(基准 {x['基准%']}%, 差 {x['差']:+.1f})收盘 {x['T+1 收盘 P25/中位/P75']}")
    ext = [x for x in F["T+1 走法"][5:] if x["走法"] in ("涨停", "跌停", "冲高A杀", "深V")]
    if ext:
        L.append("  - 极端(不在前 5): " + " / ".join(f"{x['走法']} {x['概率%']}%" for x in ext))
    fd = F["T+1 全分布"]
    L.append(f"- T+1 全分布(相对 T 收盘 %): 开 {fd['开盘']} · 高 {fd['最高']} · 低 {fd['最低']} · 收 {fd['收盘']} · 一字涨停 {fd['一字涨停(买不进)%']}%")
    L.append("- 竞价开盘 → 情景切换(9:25 可观测):")
    L += [f"  - {x}" for x in F["竞价开盘切换"]]
    L.append("- T+2 分支:")
    L += [f"  - {x}" for x in F["T+2 分支"]]
    L += ["", f"**串联**: {o['串联']}", "",
          "_口径: 概率全部来自全市场同状态历史日线(只用 T 之前已走完的样本), 没有题材 / 消息 / 盘口; 没做样本外验证, 置信最高给到'中'。_"]
    return "\n".join(L)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("T")
    ap.add_argument("--json")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    o = run(a.code, a.T, a.rebuild)
    print(render(o))
    if a.json:
        Path(a.json).write_text(json.dumps(o, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
