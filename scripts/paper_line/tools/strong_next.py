# -*- coding: utf-8 -*-
"""strong_next.py — 强势股次日溢价库(股票版相似日; v3 命名查询工具; 零 token, 只读行情库; 10/22 晚用户令: 拟人芷影 / 刘忆青的重要因素 = 判断强势股和次日冲高值)

回答: "这只票今天(T)收盘是这个状态(首板 / 二板 / 炸板 / 大涨 / 涨停后回调…), 历史上同状态、同市况的票, 明天(T+1)开盘多少、能冲多高、收在哪?"
样本: 行情库 2023 年以来全 A 日线(排除 ST / 北交所 / 上市不满 20 个交易日); 涨停价自己算(行情库 limit_up 只有约 36% 有值): 昨收 × (1 + 10% / 创业科创 20%) 四舍五入到分
T 日状态(收盘后已知, 不偷看):
  state   首板 / 二板 / 三板+ / 炸板(盘中摸过涨停没封住) / 大涨(≥7% 未板) / 回调1~3(最近一次涨停后第 1~3 天, 今天没涨停) / 其他(不进库)
  board   10cm / 20cm
  sealed  封死(收在涨停价; T 日收盘买不进, 只能排板或 T+1 竞价买)
  pct_b   回调日当天涨跌 5 档(≥3 / 0~3 / −3~0 / −6~−3 / <−6)
  volr    量比 = 当日量 / 前 5 日均量, 3 档(<1 / 1~2 / ≥2)
  level   价位 <5 / 5~10 / 10~20 / 20~50 / ≥50
  mkt     当天上证 × 创业板 各 3 档(≥0.5 / −0.5~0.5 / ≤−0.5)
  zt_n    当天全市场涨停家数 4 档(<30 / 30~60 / 60~100 / ≥100)(情绪)
T+1 结果(相对 T 收盘): gap 开盘 / hi 最高(冲高值) / lo 最低 / co 收盘 / hi_o 开盘后再冲多少(最高相对开盘) / yizi 一字涨停(买不进); T+2: o2 开 / h2 高 / l2 低 / c2 收(都相对 T 收盘)
策略: 次日挂 +N% 卖、没到收盘卖, 扣来回费约 0.15%(印花税 + 佣金); 买点 = T 收盘(封死的标"需排板")
匹配: 全条件精确匹配, 样本 <15 逐级放宽(先去 volr → level → zt_n → mkt → pct_b, 最后只留 state + board)
用法:
  python strong_next.py --build                                   (建库 → downloads/market/similar/stock_strong.jsonl)
  python strong_next.py --query 002696 --date 2026-10-23           (用 D 前一交易日收盘的状态, 查 D 当天的分布; 只用 D 之前的样本)
  python strong_next.py --validate                                 (样本外: 2023~2025 建分布, 2026 检验)
"""
import argparse
import bisect
import collections
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))   # dist_full
OUT = ROOT / "downloads" / "market" / "similar"
LIB = OUT / "stock_strong.jsonl"
META = OUT / "stock_strong.meta.json"   # 建库时用到的日线最新日期
SINCE = "2023-01-01"
MIN_N = 15
SELL_TH = (1, 2, 3, 5)
FEE = 0.15
TIERS = [["state", "board", "pct_b", "mkt", "zt_n", "level", "volr"], ["state", "board", "pct_b", "mkt", "zt_n", "level"],
         ["state", "board", "pct_b", "mkt", "zt_n"], ["state", "board", "pct_b", "mkt"], ["state", "board", "pct_b"], ["state", "board"]]


def db():
    import manual_backfill as mb
    c = mb.db().cursor()
    c.execute("use investment_market")
    return c


def lim_of(code):
    return 0.20 if code.startswith(("300", "301", "688", "689")) else 0.10


def zt_price(pc, lim):
    return round(pc * (1 + lim) + 1e-9, 2)


def b5(p, edges, labels):
    for e, lb in zip(edges, labels):
        if p >= e:
            return lb
    return labels[-1]


def b_pct(p):
    return b5(p, (3, 0, -3, -6), ("≥3", "0~3", "−3~0", "−6~−3", "<−6"))


def b_idx(p):
    return "≥0.5" if p >= 0.5 else "≤−0.5" if p <= -0.5 else "−0.5~0.5"


def b_level(c):
    return b5(c, (50, 20, 10, 5), ("≥50", "20~50", "10~20", "5~10", "<5"))


def b_volr(v):
    return "≥2" if v >= 2 else "1~2" if v >= 1 else "<1"


def b_ztn(n):
    return "≥100" if n >= 100 else "60~100" if n >= 60 else "30~60" if n >= 30 else "<30"


def load(cur, since=SINCE):
    cur.execute("select s.symbol, s.name from security_master s where s.sec_type='STOCK'")
    names = {s: n or "" for s, n in cur.fetchall()}
    syms = [s for s, n in names.items() if s[:2] in ("sh", "sz") and "ST" not in n.upper() and not s[2:].startswith(("4", "8", "92"))]
    K = {}
    for i in range(0, len(syms), 300):
        part = syms[i:i + 300]
        cur.execute(f"select symbol, trade_date, open, high, low, close, pre_close, volume from kline_day where is_deleted=0 and trade_date >= %s "
                    f"and symbol in ({','.join(['%s'] * len(part))}) order by symbol, trade_date", (since, *part))
        for s, d, o, h, l, c, pc, v in cur.fetchall():
            if o and c and pc:
                K.setdefault(s, []).append((str(d), float(o), float(h), float(l), float(c), float(pc), float(v or 0)))
    cur.execute("select symbol, trade_date, close, pre_close from kline_day where is_deleted=0 and trade_date >= %s and symbol in ('sh000001','sz399006')", (since,))
    M = collections.defaultdict(dict)
    for s, d, c, pc in cur.fetchall():
        if c and pc:
            M[str(d)][s] = (float(c) / float(pc) - 1) * 100
    return K, M


def day_states(K):
    """→ {symbol: [(i, state dict)]} + 每天涨停家数"""
    ztn = collections.Counter()
    flags = {}
    for s, k in K.items():
        lim = lim_of(s[2:])
        f = []
        for i, (d, o, h, l, c, pc, v) in enumerate(k):
            up = zt_price(pc, lim)
            zt, touch = c >= up - 0.005, h >= up - 0.005
            f.append((zt, touch))
            if zt:
                ztn[d] += 1
        flags[s] = f
    return flags, ztn


def state_at(k, f, i):
    """第 i 天收盘时的状态(只用 ≤ i 的数据); 不进库返回 None"""
    if i < 20:
        return None
    d, o, h, l, c, pc, v = k[i]
    pct = (c / pc - 1) * 100
    zt, touch = f[i]
    if zt:
        n = 1
        while i - n >= 0 and f[i - n][0]:
            n += 1
        st = "首板" if n == 1 else "二板" if n == 2 else "三板+"
    elif touch:
        st = "炸板"
    else:
        last = next((j for j in range(1, 4) if f[i - j][0]), None)
        if last:
            st = f"回调{last}"
        elif pct >= 7:
            st = "大涨"
        else:
            return None
    v5 = sum(x[6] for x in k[i - 5:i]) / 5
    return {"state": st, "pct": round(pct, 2), "pct_b": b_pct(pct) if st.startswith("回调") or st in ("炸板", "大涨") else "-",
            "sealed": bool(zt), "volr": b_volr(v / v5 if v5 else 1), "level": b_level(c)}


def build():
    cur = db()
    K, M = load(cur)
    flags, ztn = day_states(K)
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    tmp = LIB.with_suffix(".jsonl.tmp")   # 10/22 晚: 写临时文件再替换, 每晚重建时盘中 / 必查读不到半截库
    with tmp.open("w", encoding="utf-8") as fo:
        for s, k in K.items():
            f = flags[s]
            board = "20cm" if lim_of(s[2:]) > 0.15 else "10cm"
            for i in range(20, len(k) - 1):
                st = state_at(k, f, i)
                if not st:
                    continue
                d, c = k[i][0], k[i][4]
                mk = M.get(d) or {}
                n1 = k[i + 1]
                lim = lim_of(s[2:])
                up1 = zt_price(c, lim)
                rec = {"code": s[2:], "d": d, "board": board, **st, "mkt": f"上证{b_idx(mk.get('sh000001', 0))}/创业{b_idx(mk.get('sz399006', 0))}", "zt_n": b_ztn(ztn[d]),
                       "gap": round((n1[1] / c - 1) * 100, 2), "hi": round((n1[2] / c - 1) * 100, 2), "lo": round((n1[3] / c - 1) * 100, 2),
                       "co": round((n1[4] / c - 1) * 100, 2), "hi_o": round((n1[2] / n1[1] - 1) * 100, 2), "yizi": n1[1] >= up1 - 0.005 and n1[2] == n1[3]}
                if i + 2 < len(k):
                    n2 = k[i + 2]
                    rec["c2"] = round((n2[4] / c - 1) * 100, 2)
                    rec.update({"o2": round((n2[1] / c - 1) * 100, 2), "h2": round((n2[2] / c - 1) * 100, 2), "l2": round((n2[3] / c - 1) * 100, 2)})   # 10/22: T+2 开高低(相对 T 收盘), 供"封死票 T+1 开盘买 → T+2 卖"口径
                fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
    os.replace(tmp, LIB)
    kmax = max((k[-1][0] for k in K.values() if k), default="")
    META.write_text(json.dumps({"kline_max": kmax, "n": n}, ensure_ascii=False), encoding="utf-8")
    print("建库完成", n, "个强势股日 →", LIB, "日线到", kmax)


def stale():
    """行情库日线比建库时新 → 要重建(check md 每晚调 --build-if-stale)"""
    cur = db()
    cur.execute("select max(trade_date) from kline_day where is_deleted=0 and symbol='sh000001'")
    dbmax = str(cur.fetchone()[0])
    try:
        old = json.loads(META.read_text(encoding="utf-8")).get("kline_max", "")
    except (OSError, ValueError):
        old = ""
    return dbmax > old, old, dbmax


_LIB = None


def lib():
    global _LIB
    if _LIB is None:
        _LIB = [json.loads(l) for l in LIB.read_text(encoding="utf-8").splitlines()]
    return _LIB


def q(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * p))], 2) if xs else None


def ev(xs, th):
    """次日挂 +th% 卖(开盘就高于 th 按开盘卖), 没到收盘卖, 扣费"""
    out = []
    for r in xs:
        if r["gap"] >= th:
            v = r["gap"]
        elif r["hi"] >= th:
            v = th
        else:
            v = r["co"]
        out.append(v - FEE)
    return round(sum(out) / len(out), 2), f"{sum(1 for x in out if x > 0) / len(out):.0%}"


def dist(xs):
    import dist_full as DF   # 10/24 用户令: 统一报 均值 + P10~P90 + 最差 / 最好(带票名日期) + n, 不能只报中位
    tag = lambda r: f"{r.get('code')} {r.get('d')}"   # noqa: E731
    return {"n": len(xs), "次日开盘 P25/中位/P75": [q([r["gap"] for r in xs], p) for p in (.25, .5, .75)],
            "次日最高(冲高) P25/中位/P75": [q([r["hi"] for r in xs], p) for p in (.25, .5, .75)],
            "次日最高 全分布": DF.full(xs, key=lambda r: r["hi"], tag=tag), "次日收盘 全分布": DF.full(xs, key=lambda r: r["co"], tag=tag),
            "次日最低 全分布": DF.full(xs, key=lambda r: r["lo"], tag=tag),
            "开盘后再冲 中位": q([r["hi_o"] for r in xs], .5), "次日收盘 中位": q([r["co"] for r in xs], .5), "次日最低 中位": q([r["lo"] for r in xs], .5),
            "次日最低 P25/中位/P75": [q([r["lo"] for r in xs], p) for p in (.25, .5, .75)], "次日振幅 中位": q([r["hi"] - r["lo"] for r in xs], .5),
            "冲高≥3% 比例": f"{sum(1 for r in xs if r['hi'] >= 3) / len(xs):.0%}", "收>开 比例": f"{sum(1 for r in xs if r['co'] > r['gap']) / len(xs):.0%}",
            "一字涨停(买不进)比例": f"{sum(1 for r in xs if r['yizi']) / len(xs):.0%}", "T+2 收盘 中位": q([r["c2"] for r in xs if "c2" in r], .5),
            "次日挂单卖 期望 / 胜率(扣费)": {f"+{th}%": ev(xs, th) for th in SELL_TH}}


def query(code, D):
    cur = db()
    s = ("sh" if code.startswith("6") else "sz") + code
    cur.execute("select trade_date, open, high, low, close, pre_close, volume from kline_day where is_deleted=0 and symbol=%s and trade_date < %s order by trade_date desc limit 40", (s, D))
    k = [(str(d), float(o), float(h), float(l), float(c), float(pc), float(v or 0)) for d, o, h, l, c, pc, v in cur.fetchall() if o and c and pc][::-1]
    if len(k) < 21:
        return {"err": "日线不足"}
    lim = lim_of(code)
    f = [(x[4] >= zt_price(x[5], lim) - 0.005, x[2] >= zt_price(x[5], lim) - 0.005) for x in k]
    st = state_at(k, f, len(k) - 1)
    T = k[-1][0]
    if not st:
        return {"code": code, "T": T, "状态": "不是强势股(没涨停 / 炸板 / 大涨 / 涨停后 3 天内)", "pct": round((k[-1][4] / k[-1][5] - 1) * 100, 2)}
    cur.execute("select symbol, close, pre_close from kline_day where is_deleted=0 and trade_date=%s and symbol in ('sh000001','sz399006')", (T,))
    mk = {a: (float(b) / float(c) - 1) * 100 for a, b, c in cur.fetchall()}
    cur.execute("select k.symbol, k.close, k.pre_close from kline_day k join security_master s on s.symbol=k.symbol and s.sec_type='STOCK' "
                "where k.is_deleted=0 and k.trade_date=%s and k.pre_close>0", (T,))
    zt_n = sum(1 for sy, c_, pc_ in cur.fetchall() if sy[:2] in ("sh", "sz") and float(c_) >= zt_price(float(pc_), lim_of(sy[2:])) - 0.005)   # 当天全市场涨停家数(库里只有到 T−1 的结果日)
    cur_f = {**st, "board": "20cm" if lim > 0.15 else "10cm", "mkt": f"上证{b_idx(mk.get('sh000001', 0))}/创业{b_idx(mk.get('sz399006', 0))}", "zt_n": b_ztn(zt_n)}
    L = [r for r in lib() if r["d"] < T]
    out = {"code": code, "T(状态日)": T, "D(结果日)": D, "当前状态": {k_: cur_f[k_] for k_ in ("state", "board", "pct", "pct_b", "sealed", "volr", "level", "mkt", "zt_n")},
           "注意": "封死涨停 = T 收盘买不进(排板或 T+1 竞价买); 期望按 T 收盘价买算" if cur_f["sealed"] else "", "tiers": []}
    for keys in TIERS:
        xs = [r for r in L if all(r.get(x) == cur_f.get(x) for x in keys)]
        out["tiers"].append({"按": keys, **(dist(xs) if xs else {"n": 0})})
        if len(xs) >= MIN_N:
            break
    return out


_Q, _ZTN = {}, {}


def query_cached(code, D):
    """同一天同一只票只查一次(11 本账共用一个进程; 必查每次叫醒都会重拼)"""
    if (code, D) not in _Q:
        _Q[(code, D)] = query(code, D)
    return _Q[(code, D)]


_SELL = {}


def mentor_sell_pct(skill, D, recent=60):
    """导师"持有 1 天就卖"的卖点, 落在库内同状态 T+1 冲高(hi)分布的第几分位(10/22 晚用户批: 卖价参考做成动态、有理有据)
    只用 D 之前已发生的成交; 冲高分布只用 D 前一交易日之前的库记录(库记录 d 的 hi = d+1 的最高, d = D−1 那天的 hi 就是今天, 不许用)
    → {"recent": [分位...](最近 recent 笔, 新在后), "all": [...], "by_state": {state: [最近的分位...]}, "HI": {(state, board): 排好序的 hi}, "n_all"}"""
    if (skill, D) in _SELL:
        return _SELL[(skill, D)]
    L = lib()
    days = sorted({r["d"] for r in L if r["d"] < D})
    cut = days[-1] if days else D
    HI = collections.defaultdict(list)
    for r in L:
        if r["d"] < cut:
            HI[(r["state"], r["board"])].append(r["hi"])
    for v in HI.values():
        v.sort()
    IDX = {(r["code"], r["d"]): r for r in L if r["d"] < D}
    f = ROOT / "skills" / f"{skill}-skill" / "persona" / "cases_auto.jsonl"
    C = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()] if f.exists() else []
    C = [c for c in C if c.get("side") in ("买", "卖") and str(c.get("code", ""))[:1] in ("0", "3", "6") and c.get("date", "") < D and c.get("vwap")]
    out = {"recent": [], "all": [], "by_state": collections.defaultdict(list), "HI": HI, "n_all": 0}
    if C:
        cur = db()
        syms = sorted({("sh" if c["code"].startswith("6") else "sz") + c["code"] for c in C})
        K = collections.defaultdict(list)
        for i in range(0, len(syms), 300):
            part = syms[i:i + 300]
            cur.execute(f"select symbol, trade_date, close from kline_day where is_deleted=0 and trade_date >= '2025-01-01' and trade_date < %s "
                        f"and symbol in ({','.join(['%s'] * len(part))}) order by symbol, trade_date", (D, *part))
            for s, d, c_ in cur.fetchall():
                if c_:
                    K[s[2:]].append((str(d), float(c_)))
        sells = collections.defaultdict(list)
        for c in C:
            if c["side"] == "卖":
                sells[c["code"]].append(c)
        for v in sells.values():
            v.sort(key=lambda s: (s["date"], s.get("time", "")))
        got = []
        for c in sorted((c for c in C if c["side"] == "买"), key=lambda c: (c["date"], c.get("time", ""))):
            k = K.get(c["code"]) or []
            ds = [x[0] for x in k]
            if c["date"] not in ds:
                continue
            i = ds.index(c["date"])
            sl = next((s for s in sells[c["code"]] if (s["date"], s.get("time", "")) > (c["date"], c.get("time", ""))), None)
            rt = IDX.get((c["code"], c["date"]))
            if not sl or not rt or i + 1 >= len(ds) or sl["date"] != ds[i + 1]:   # 只要"买入次日就卖"、买入日收盘是强势股状态的
                continue
            dist = HI.get((rt["state"], rt["board"]))
            if not dist:
                continue
            x = (sl["vwap"] / k[i][1] - 1) * 100
            p = round(bisect.bisect_left(dist, x) / len(dist) * 100)
            got.append((rt["state"], p))
        out["all"] = [p for _, p in got]
        out["recent"] = out["all"][-recent:]
        for s_, p in got[-recent * 2:]:
            out["by_state"][s_].append(p)
        out["n_all"] = len(got)
    _SELL[(skill, D)] = out
    return out


def must_line(code, D, skill=None, held=False):
    """→ [(标签, 一行)]: paper v3 必查用(pack.must_check); 零 token, 失败由调用方兜"""
    r = query_cached(code, D)
    if r.get("err"):
        return [("强势股次日", f"查不了: {r['err']}")]
    if "当前状态" not in r:
        return [("强势股次日", f"{r.get('T')} 收盘不是强势股(涨 {r.get('pct')}%), 库里没有可比样本")]
    s = r["当前状态"]
    t = next((x for x in r["tiers"] if x.get("n", 0) >= MIN_N), r["tiers"][-1] if r["tiers"] else {"n": 0})
    head = f"{r['T(状态日)']} 收盘 = {s['state']}·{s['board']}{'·封死' if s.get('sealed') else ''}(涨 {s.get('pct')}%)"
    if not t.get("n"):
        return [("强势股次日", head + "; 同状态样本 0")]
    ev3 = (t.get("次日挂单卖 期望 / 胜率(扣费)") or {}).get("+3%")
    import dist_full as DF
    out = [("强势股次日", f"{head}; 历史同状态 n={t['n']}(按 {'/'.join(t['按'])}) 今天(T+1) 开盘中位 {t['次日开盘 P25/中位/P75'][1]}%、"
                          f"冲高≥3% {t['冲高≥3% 比例']}、振幅中位 {t['次日振幅 中位']}%、一字 {t['一字涨停(买不进)比例']}; 挂 +3% 卖(以昨收为买点)期望/胜率 {ev3}(相对昨收 %)"
                          f" | 次日最高: {DF.line(t.get('次日最高 全分布'))} | 次日收盘: {DF.line(t.get('次日收盘 全分布'))} | 次日最低: {DF.line(t.get('次日最低 全分布'))}")]
    if skill:
        m = mentor_sell_pct(skill, D)
        rc = m["recent"]
        if len(rc) >= 10:
            med = sorted(rc)[len(rc) // 2]
            q1, q3 = sorted(rc)[len(rc) // 4], sorted(rc)[len(rc) * 3 // 4]
            al = sorted(m["all"])
            bs = m["by_state"].get(s["state"]) or []
            txt = (f"导师'买入次日就卖'的卖价, 落在同状态冲高分布的 近 {len(rc)} 笔中位 P{med}(P25~P75 = P{q1}~P{q3}); 全部 {len(al)} 笔中位 P{al[len(al) // 2]}"
                   + (f"; 同为{s['state']}的近期 {len(bs)} 笔中位 P{sorted(bs)[len(bs) // 2]}" if len(bs) >= 5 else ""))
            if held:
                dist = m["HI"].get((s["state"], s["board"])) or []
                pm = sorted(bs)[len(bs) // 2] if len(bs) >= 5 else med
                if dist:
                    v = dist[min(len(dist) - 1, int(len(dist) * pm / 100))]
                    txt += f" → 今天卖价参考 = 冲高分布 P{pm} = 昨收 {v:+.2f}%"
            out.append(("导师卖点分位(动态)", txt))
        else:
            out.append(("导师卖点分位(动态)", f"导师'买入次日就卖'且买入日是强势股的样本只有 {len(rc)} 笔, 不给分位"))
    return out


def validate():
    """样本外: 2023~2025 按 state × board × mkt 建分布, 2026 检验 '冲高≥3% 比例' 和 '+3% 挂单期望' 的预测 vs 实际"""
    L = lib()
    tr = [r for r in L if r["d"] < "2026-01-01"]
    te = [r for r in L if r["d"] >= "2026-01-01"]
    key = lambda r: (r["state"], r["board"], r["mkt"])   # noqa: E731
    g_tr, g_te = collections.defaultdict(list), collections.defaultdict(list)
    for r in tr:
        g_tr[key(r)].append(r)
    for r in te:
        g_te[key(r)].append(r)
    rows = []
    for k_, xs in g_te.items():
        ys = g_tr.get(k_) or []
        if len(xs) >= 30 and len(ys) >= 30:
            rows.append((k_, len(ys), sum(r["hi"] >= 3 for r in ys) / len(ys), ev(ys, 3)[0], len(xs), sum(r["hi"] >= 3 for r in xs) / len(xs), ev(xs, 3)[0]))
    rows.sort(key=lambda r: -r[3])
    print("| 状态 × 板 × 市况 | 训练 n | 训练 冲高≥3% | 训练 +3%卖期望 | 2026 n | 2026 冲高≥3% | 2026 +3%卖期望 |")
    print("|---|---|---|---|---|---|---|")
    for r in rows[:40]:
        print(f"| {' / '.join(r[0])} | {r[1]} | {r[2]:.0%} | {r[3]:+.2f}% | {r[4]} | {r[5]:.0%} | {r[6]:+.2f}% |")
    import statistics as stt
    if len(rows) >= 5:
        a, b = [r[3] for r in rows], [r[6] for r in rows]
        ma, mb_ = stt.mean(a), stt.mean(b)
        cov = sum((x - ma) * (y - mb_) for x, y in zip(a, b))
        corr = cov / ((sum((x - ma) ** 2 for x in a) * sum((y - mb_) ** 2 for y in b)) ** 0.5 or 1)
        print(f"\n分组数 {len(rows)}; 训练期望 vs 2026 期望 的相关 = {corr:.2f}(越接近 1 = 分组在样本外越站得住)")
    print(f"全体: 训练 n={len(tr)} +3%卖期望 {ev(tr, 3)} | 2026 n={len(te)} {ev(te, 3)}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--build-if-stale", action="store_true")
    ap.add_argument("--query")
    ap.add_argument("--date")
    ap.add_argument("--validate", action="store_true")
    a = ap.parse_args()
    if a.build_if_stale:
        st_, old, new = stale()
        print(f"库建于日线 {old or '(未知)'}, 行情库现到 {new}", "→ 重建" if st_ else "→ 不用重建")
        if st_:
            build()
    if a.build:
        build()
    if a.validate:
        validate()
    if a.query:
        print(json.dumps(query(a.query, a.date), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
