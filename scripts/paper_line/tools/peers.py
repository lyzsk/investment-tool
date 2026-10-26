# -*- coding: utf-8 -*-
"""peers.py — 同炒作逻辑的邻居(10/23 用户令; 10/24 v1: 用户"本质是给概率作证, 非常关键"; v3 / 实盘线命名查询; 零 token, 只读)

回答: "这只票 T 日(D 的前一交易日)是谁买的、炒的什么性质、在梯队哪个位置; 同逻辑的历史样本次日怎么走; 有没有监管 / 筹码 / 电报信号"
维度(T 日收盘后已知, 不偷看 D):
  ① 龙虎榜席位: 净买前 3 + 游资别名; 席位风格 = 它历史净买的票 —— 买入日在不在涨停(打板型 / 低吸型)、次日它还在榜时是不是卖出(一日游)、
     次日最高 / 收盘全分布(溢价 / 砸盘); 这个席位 T 日同时净买的其他票(及它们 T 日状态)
  ② 炒作性质: 主线(题材本波 ≥3 天且峰值 ≥5 家) / 情绪修复(前一日涨停 <30 家后今天放量) / 新概念(题材首日 ≥3 家涨停) / 一般
  ③ 梯队: 全市场梯队 + 最高标; 本票位置 龙头 / 题材内最高 / 跟风 / 补涨(题材已发酵 ≥3 天本票才首板); 晋级率(市场 + 本题材: T−1 涨停 → T 连板)
  ④ 历史同逻辑样本: a 同一主买游资 + 同板数 b 同题材阶段 + 同板数 —— 各给次日最高 / 收盘全分布 + 最好 / 最差案例
  ⑤ 监管 / 筹码 / 电报: T 日上榜原因、3 日累计涨幅(接近异动线提醒)、换手率、T 日加红电报点名
不做: D 当天盘中(同题材今天的竞价 / 开板 / 回封要盘中涨停池, 等 collect_mood 建好再接)
用法: python peers.py <代码> <D> [--look 250]   (输出 JSON)
"""
import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "lib"), str(Path(__file__).parent)]
import dist_full as DF   # noqa: E402

_C = {}
_TL = __import__("threading").local()   # 10/24: 连接按线程各一条(多本账多线程共用一条 → InterfaceError, 回放 100 份材料里 52 份"同逻辑邻居查询失败")
TG = ROOT / "results" / "inv-stock" / "test" / "telegraph"


def cur():
    if getattr(_TL, "c", None) is None:
        import manual_backfill as mb
        c = mb.db().cursor()
        c.execute("use investment_market")
        _TL.c = c
    return _TL.c


def prev_day(D):
    c = cur()
    c.execute("select max(trade_date) from kline_day where symbol='sh000001' and trade_date < %s", (D,))
    return str(c.fetchone()[0])


def name_of(code):
    if ("nm", code) not in _C:
        c = cur()
        c.execute("select name from security_master where code=%s and sec_type='STOCK' limit 1", (code,))
        r = c.fetchone()
        _C[("nm", code)] = (r[0] if r else "") or ""
    return _C[("nm", code)]


def lim(code):
    return 0.2 if code[:3] in ("300", "301", "688", "689") else 0.1


def zt(pc, code):
    return round(pc * (1 + lim(code)) + 1e-9, 2)


def kline(syms, since):
    """{symbol: [(d, o, h, l, c, pc, turnover)]}, 带缓存"""
    need = [s for s in syms if ("k", s, since) not in _C]
    if need:
        c = cur()
        got = collections.defaultdict(list)
        for i in range(0, len(need), 300):
            part = need[i:i + 300]
            c.execute(f"select symbol, trade_date, open, high, low, close, pre_close, turnover_rate from kline_day where is_deleted=0 and trade_date >= %s "
                      f"and symbol in ({','.join(['%s'] * len(part))}) order by symbol, trade_date", (since, *part))
            for s, d, o, h, l, cl, pc, tr in c.fetchall():
                if o and cl and pc:
                    got[s].append((str(d), float(o), float(h), float(l), float(cl), float(pc), float(tr or 0)))
        for s in need:
            _C[("k", s, since)] = got.get(s, [])
    return {s: _C[("k", s, since)] for s in syms}


def boards_at(k, i, code):
    n = 0
    while i >= 0 and k[i][4] >= zt(k[i][5], code) - 0.005:
        n += 1
        i -= 1
    return n


def outcome(pairs, since):
    """pairs = [(symbol, T)] → [{s, d, b(T 日板数), pct(T 日涨幅), at_lim, hi, co, gap(次日相对 T 收)}]"""
    K = kline(sorted({s for s, _ in pairs}), since)
    out = []
    for s, d in pairs:
        k = K.get(s) or []
        ds = [x[0] for x in k]
        if d not in ds:
            continue
        i = ds.index(d)
        if i + 1 >= len(k):
            continue
        t, n = k[i], k[i + 1]
        out.append({"s": s, "d": d, "b": boards_at(k, i, s[2:]), "pct": (t[4] / t[5] - 1) * 100, "at_lim": t[4] >= zt(t[5], s[2:]) - 0.005,
                    "hi": (n[2] / t[4] - 1) * 100, "co": (n[4] / t[4] - 1) * 100, "gap": (n[1] / t[4] - 1) * 100})
    return out


def tag(r):
    return f"{r['s'][2:]}{name_of(r['s'][2:])} {r['d']}"


def seat_style(dc, T, look):
    """席位风格(只用 T 之前): 打板型 / 低吸型、一日游、次日溢价 / 砸盘"""
    c = cur()
    c.execute("select date_sub(%s, interval %s day)", (T, int(look * 1.5)))
    since = str(c.fetchone()[0])
    c.execute("select symbol, trade_date, sum(net_amt) from lhb_seat where is_deleted=0 and dept_code=%s and trade_date >= %s and trade_date < %s group by symbol, trade_date having sum(net_amt) > 0",
              (dc, since, T))
    hist = [(s, str(d)) for s, d, _ in c.fetchall()]
    ev = outcome(hist, since)
    c.execute("select symbol, trade_date from lhb_seat where is_deleted=0 and dept_code=%s and direction='SELL' and trade_date >= %s and trade_date <= %s", (dc, since, T))
    sells = {(s, str(d)) for s, d in c.fetchall()}
    c.execute("select symbol, trade_date from lhb_stock where is_deleted=0 and trade_date >= %s and trade_date <= %s", (since, T))
    listed = {(s, str(d)) for s, d in c.fetchall()}
    nxt = {}
    for s, d in hist:
        k = kline([s], since)[s]
        ds = [x[0] for x in k]
        if d in ds and ds.index(d) + 1 < len(k):
            nxt[(s, d)] = k[ds.index(d) + 1][0]
    on_next = [(s, d) for s, d in hist if (s, nxt.get((s, d))) in listed]
    sold_next = [x for x in on_next if (x[0], nxt.get(x)) in sells]
    n = len(ev)
    lim_share = sum(r["at_lim"] for r in ev) / n if n else 0
    low_share = sum(r["pct"] < 5 for r in ev) / n if n else 0
    tags = []
    if n >= 10:
        tags.append("打板型" if lim_share >= 0.6 else "低吸型" if low_share >= 0.5 else "混合")
        if len(on_next) >= 5 and len(sold_next) / len(on_next) >= 0.6:
            tags.append("一日游")
        hi = DF.full(ev, key=lambda r: r["hi"])
        co = DF.full(ev, key=lambda r: r["co"])
        if hi["中位"] >= 6:
            tags.append("次日溢价高")
        elif hi["中位"] <= 2:
            tags.append("次日溢价低")
        if co["中位"] <= -2:
            tags.append("次日常砸盘")
    else:
        tags.append(f"样本少(n={n})")
    return {"风格": tags, "n": n, "买入日涨停占比": round(lim_share, 2), "次日在榜时卖出占比": f"{len(sold_next)}/{len(on_next)}",
            "次日最高": DF.full(ev, key=lambda r: r["hi"], tag=tag), "次日收盘": DF.full(ev, key=lambda r: r["co"], tag=tag), "_ev": ev}


def seats(code, T, look):
    c = cur()
    sym = ("sh" if code.startswith("6") else "sz") + code
    c.execute("select dept_code, dept_name, youzi_alias, net_amt, is_institution from lhb_seat where is_deleted=0 and trade_date=%s and symbol=%s", (T, sym))
    rows = c.fetchall()
    c.execute("select reason, turnover_rate from lhb_stock where is_deleted=0 and trade_date=%s and symbol=%s", (T, sym))
    reasons = sorted({r for r, _ in c.fetchall() if r})
    if not rows:
        return {"上榜": False}
    net, meta = collections.defaultdict(float), {}
    for dc, dn, al, na, inst in rows:
        net[dc] += float(na or 0)
        meta[dc] = (dn, al, inst)
    buys = sorted([x for x in net.items() if x[1] > 0], key=lambda x: -x[1])[:3]
    sells = sorted([x for x in net.items() if x[1] < 0], key=lambda x: x[1])[:3]
    out_b = []
    for dc, na in buys:
        dn, al, inst = meta[dc]
        st = seat_style(dc, T, look)
        c.execute("select symbol, sum(net_amt) from lhb_seat where is_deleted=0 and dept_code=%s and trade_date=%s and symbol<>%s group by symbol having sum(net_amt) > 0", (dc, T, sym))
        same = [s for s, _ in c.fetchall()][:6]
        sm = outcome([(s, T) for s in same], T) if same else []
        same_txt = []
        for s in same:
            k = kline([s], T)[s]
            if k:
                b = boards_at(k, len(k) - 1, s[2:])
                same_txt.append(f"{s[2:]}{name_of(s[2:])}({'%d板' % b if b else '%+.1f%%' % ((k[-1][4] / k[-1][5] - 1) * 100)})")
        out_b.append({"席位": al or ("机构" if inst else dn), "营业部": dn, "dept": dc, "净买(万)": round(na / 1e4), **{k: v for k, v in st.items() if k != "_ev"},
                      "同日还净买了": same_txt, "_ev": st["_ev"]})
    return {"上榜": True, "上榜原因": reasons, "净买前列": out_b,
            "净卖前列": [{"席位": meta[dc][1] or ("机构" if meta[dc][2] else meta[dc][0]), "净卖(万)": round(-na / 1e4)} for dc, na in sells]}


def ladder(code, name, T):
    import theme_life as TL
    R = TL.rows_canon()
    days = sorted({r[0] for r in R if r[0] <= T})
    T1 = days[-2] if len(days) > 1 else None
    today = [r for r in R if r[0] == T]
    yest = [r for r in R if r[0] == T1] if T1 else []
    lad = collections.Counter(r[4] for r in today if r[5] and r[4])
    top = max(lad) if lad else 0
    leaders = sorted({r[2] for r in today if r[5] and r[4] == top})
    y_zt = {r[3] for r in yest if r[5]}
    promo = sum(1 for r in today if r[5] and r[4] >= 2 and r[3] in y_zt)
    me = [r for r in today if r[3] == code or r[2] == name]
    mine = max([r[4] for r in me] or [0])
    zt_t, zt_t1 = sum(1 for r in today if r[5]), sum(1 for r in yest if r[5])
    themes = {}
    for th in sorted({r[1] for r in me}):
        L = TL.life(th, T, after=True)
        mates = sorted({(x[4], x[2]) for x in today if x[1] == th and x[2] != name}, key=lambda x: -x[0])
        th_y = {x[3] for x in yest if x[1] == th and x[5]}
        th_promo = sum(1 for x in today if x[1] == th and x[5] and x[4] >= 2 and x[3] in th_y)
        day_n, peak = L.get("本波第几天") or 0, L.get("本波峰值家数") or 0
        nature = ("主线" if day_n >= 3 and peak >= 5 else "新概念" if day_n == 1 and len(mates) + 1 >= 3 else
                  "情绪修复" if zt_t1 and zt_t1 < 30 and zt_t >= zt_t1 * 1.5 else "一般")
        th_top = max([b for b, _ in mates] + [mine])
        pos = ("龙头(全市场最高板)" if mine and mine == top else "题材内最高" if mine == th_top and mine >= 2 else
               "补涨(题材已发酵≥3天本票才首板)" if mine == 1 and day_n >= 3 else "首板" if mine == 1 else "跟风")
        themes[th] = {"阶段": L.get("阶段"), "本波第几天": day_n, "峰值家数": peak, "炒作性质": nature, "本票位置": pos,
                      "同题材 T 日其他票": [f"{nm} {b}板" if b else f"{nm} 大涨" for b, nm in mates[:8]], "题材晋级": f"{th_promo}/{len(th_y)}"}
    return {"本票 T 日": f"{mine} 板" if mine else ("大涨" if me else "未上涨停分析"), "全市场梯队": {f"{k}板": v for k, v in sorted(lad.items(), reverse=True)},
            "最高标": f"{'、'.join(leaders[:3])} {top} 板", "市场晋级率": f"{promo}/{len(y_zt)}", "涨停家数 T−1→T(涨停分析口径)": f"{zt_t1}→{zt_t}", "题材": themes, "_mine": mine}


def hist_same_logic(code, T, seat_ev, lad, look):
    """④ 历史同逻辑样本: a 同主买游资 + 同板数 b 同题材阶段 + 同板数"""
    import theme_life as TL
    out = {}
    b = lad.get("_mine") or 0
    if seat_ev:
        xs = [r for r in seat_ev if r["b"] == b] if b else [r for r in seat_ev if not r["at_lim"]]
        out["同主买游资 + 同板数"] = {"条件": f"{b} 板" if b else "非涨停买入", "次日最高": DF.full(xs, key=lambda r: r["hi"], tag=tag), "次日收盘": DF.full(xs, key=lambda r: r["co"], tag=tag)}
    for th, v in (lad.get("题材") or {}).items():
        stg = str(v.get("阶段") or "").split("(")[0]
        c = cur()
        c.execute("select date_sub(%s, interval %s day)", (T, int(look * 1.5)))
        since = str(c.fetchone()[0])
        pairs = []
        for r in TL.rows_canon():
            if since <= r[0] < T and r[1] == th and r[5] and r[4] == b and r[3]:
                if str((TL.life(th, r[0], after=True) or {}).get("阶段") or "").split("(")[0] == stg:
                    pairs.append((("sh" if r[3].startswith("6") else "sz") + r[3], r[0]))
        ev = outcome(pairs, since)
        key = f"同题材({th})同阶段({stg}) + 同板数"
        if len(ev) < 15:   # 新题材 / 少见阶段: 退到"任意题材的同阶段 + 同板数"(样本够才有意义)
            pairs = []
            for r in TL.rows_canon():
                if since <= r[0] < T and r[5] and r[4] == b and r[3] and str((TL.life(r[1], r[0], after=True) or {}).get("阶段") or "").split("(")[0] == stg:
                    pairs.append((("sh" if r[3].startswith("6") else "sz") + r[3], r[0]))
            ev, key = outcome(sorted(set(pairs)), since), f"任意题材同阶段({stg}) + 同板数(本题材样本 <15, 已放宽)"
        out[key] = {"条件": f"{b} 板", "次日最高": DF.full(ev, key=lambda r: r["hi"], tag=tag), "次日收盘": DF.full(ev, key=lambda r: r["co"], tag=tag)}
    return out


def misc(code, T, lh):
    sym = ("sh" if code.startswith("6") else "sz") + code
    k = kline([sym], prev_day(T) if False else "2000-01-01")[sym]
    k = [x for x in k if x[0] <= T]
    out = {}
    if len(k) >= 4:
        r3 = (k[-1][4] / k[-4][4] - 1) * 100
        out["近 3 日累计涨幅"] = round(r3, 1)
        th = 20 if lim(code) == 0.1 else 30
        if r3 >= th * 0.75:
            out["监管提醒"] = f"3 日累计 {r3:.1f}% 接近 {th}% 异动线(偏离值按扣指数算, 这里是近似)"
        out["T 日换手%"] = round(k[-1][6], 2)
    out["上榜原因"] = (lh or {}).get("上榜原因") or []
    tg = []
    f = TG / f"{T}.jsonl"
    if f.exists():
        for l in f.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(l)
            except ValueError:
                continue
            if e.get("sym") == sym:
                tg.append(f"{e.get('t')} {str(e.get('text') or '')[:40]}")
    out["T 日电报点名"] = tg[:3]
    return out


def lhb_timeline(code, T, n=10):
    """10/24 用户: 炒作周期内上榜情况 —— 本票近 n 个交易日每次上榜: 主买 / 主卖席位, 谁是新进(接力), 前几次的主买今天是不是在卖(出货)"""
    c = cur()
    sym = ("sh" if code.startswith("6") else "sz") + code
    c.execute("select distinct trade_date from kline_day where symbol='sh000001' and trade_date <= %s order by trade_date desc limit %s", (T, n))
    days = sorted(str(x[0]) for x in c.fetchall())
    c.execute("select trade_date, dept_code, dept_name, youzi_alias, is_institution, sum(net_amt) from lhb_seat where is_deleted=0 and symbol=%s and trade_date >= %s and trade_date <= %s "
              "group by trade_date, dept_code, dept_name, youzi_alias, is_institution", (sym, days[0], T))
    by = collections.defaultdict(list)
    for d, dc, dn, al, inst, na in c.fetchall():
        by[str(d)].append((dc, al or ("机构" if inst else dn[:10]), float(na or 0)))
    k = {x[0]: x for x in kline([sym], days[0])[sym]}
    out, buyers_before = [], {}
    for d in days:
        if d not in by:
            continue
        rows = by[d]
        b = sorted([x for x in rows if x[2] > 0], key=lambda x: -x[2])[:3]
        s = sorted([x for x in rows if x[2] < 0], key=lambda x: x[2])[:3]
        new = [x[1] for x in b if x[0] not in buyers_before]
        dump = [x[1] for x in s if x[0] in buyers_before]
        kk = k.get(d)
        kl = kline([sym], "2000-01-01")[sym]
        idx = [x[0] for x in kl].index(d) if kk else None
        out.append({"d": d, "涨幅": round((kk[4] / kk[5] - 1) * 100, 1) if kk else None, "板数": boards_at(kl, idx, code) if idx is not None else None,
                    "主买": [f"{x[1]} {x[2] / 1e4:.0f}万" for x in b], "主卖": [f"{x[1]} {-x[2] / 1e4:.0f}万" for x in s],
                    "新进接力": new, "前次主买今天出货": dump})
        for x in b:
            buyers_before.setdefault(x[0], d)
    return out


def seat_followup(dc, T, look, ev=None):
    """10/24 用户: 这个席位买入后第 1 / 2 / 3 天怎么走; 次日有没有别的游资接力(净买上榜), 接力 vs 没接力的后续分布"""
    c = cur()
    c.execute("select date_sub(%s, interval %s day)", (T, int(look * 1.5)))
    since = str(c.fetchone()[0])
    if ev is None:
        c.execute("select symbol, trade_date, sum(net_amt) from lhb_seat where is_deleted=0 and dept_code=%s and trade_date >= %s and trade_date < %s group by symbol, trade_date having sum(net_amt) > 0",
                  (dc, since, T))
        pairs = [(s, str(d)) for s, d, _ in c.fetchall()]
    else:
        pairs = [(r["s"], r["d"]) for r in ev]
    K = kline(sorted({s for s, _ in pairs}), since)
    c.execute("select symbol, trade_date from lhb_seat where is_deleted=0 and trade_date >= %s and trade_date <= %s and dept_code<>%s group by symbol, trade_date, dept_code having sum(net_amt) > 0",
              (since, T, dc))
    other_buy = {(s, str(d)) for s, d in c.fetchall()}
    rows = []
    for s, d in pairs:
        k = K.get(s) or []
        ds = [x[0] for x in k]
        if d not in ds:
            continue
        i = ds.index(d)
        base = k[i][4]
        r = {"s": s, "d": d}
        for j in (1, 2, 3):
            if i + j < len(k) and k[i + j][0] < T:
                r[f"c{j}"] = (k[i + j][4] / base - 1) * 100
        if i + 1 < len(k):
            r["relay"] = (s, k[i + 1][0]) in other_buy
        rows.append(r)
    out = {f"买入后第{j}天收盘": DF.full(rows, key=lambda r, j=j: r.get(f"c{j}"), tag=tag) for j in (1, 2, 3)}
    rel = [r for r in rows if r.get("relay") is True]
    nor = [r for r in rows if r.get("relay") is False]
    out["次日有别的游资净买接力"] = f"{len(rel)}/{len(rel) + len(nor)}"
    out["有接力 → 第2天收盘"] = DF.full(rel, key=lambda r: r.get("c2"), tag=tag)
    out["没接力 → 第2天收盘"] = DF.full(nor, key=lambda r: r.get("c2"), tag=tag)
    return out


def query(code, D, look=250):
    T = prev_day(D)
    nm = name_of(code)
    out = {"code": code, "name": nm, "D": D, "T(看的是这一天收盘后已知的)": T}
    for k, fn in (("龙虎榜", lambda: seats(code, T, look)), ("题材 / 梯队", lambda: ladder(code, nm, T))):
        try:
            out[k] = fn()
        except Exception as e:   # noqa: BLE001
            out[k] = {"err": repr(e)[:200]}
    try:
        top_ev = ((out["龙虎榜"].get("净买前列") or [{}])[0]).get("_ev") if out["龙虎榜"].get("上榜") else None
        out["历史同逻辑样本"] = hist_same_logic(code, T, top_ev, out["题材 / 梯队"] if "err" not in out["题材 / 梯队"] else {}, look)
    except Exception as e:   # noqa: BLE001
        out["历史同逻辑样本"] = {"err": repr(e)[:200]}
    try:
        out["监管 / 筹码 / 电报"] = misc(code, T, out.get("龙虎榜"))
    except Exception as e:   # noqa: BLE001
        out["监管 / 筹码 / 电报"] = {"err": repr(e)[:200]}
    try:   # 10/24 用户: 炒作周期内的龙虎榜时间线 + 主买游资买入后第 1~3 天 / 接力与否
        out["龙虎榜时间线(近10日)"] = lhb_timeline(code, T)
        lh = out.get("龙虎榜") or {}
        if lh.get("上榜") and lh.get("净买前列"):
            b0 = lh["净买前列"][0]
            out["主买游资后续"] = {"席位": b0["席位"], **seat_followup(b0["dept"], T, look, b0.get("_ev"))}
    except Exception as e:   # noqa: BLE001
        out["龙虎榜时间线(近10日)"] = {"err": repr(e)[:200]}
    return out


def _clean(x):
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items() if not str(k).startswith("_")}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    return x


def must_line(code, D):
    """→ [(标签, 一行)]: 必查用(每行带全分布)"""
    r = query(code, D)
    L = []
    lh = r.get("龙虎榜") or {}
    if lh.get("err"):
        L.append(("同逻辑·龙虎榜", f"查询失败 {lh['err'][:80]}"))
    elif not lh.get("上榜"):
        L.append(("同逻辑·龙虎榜", f"{r['T(看的是这一天收盘后已知的)']} 没上龙虎榜"))
    else:
        for b in lh["净买前列"]:
            L.append(("同逻辑·席位风格", f"{b['席位']} 净买 {b['净买(万)']} 万 · 风格 {'/'.join(b['风格'])}(买入日涨停占比 {b['买入日涨停占比']:.0%}, 次日在榜卖出 {b['次日在榜时卖出占比']}) · 它历史净买的票 次日最高: {DF.line(b['次日最高'])}; 次日收盘: {DF.line(b['次日收盘'])}"
                      + (f" · 同日还买 {'、'.join(b['同日还净买了'])}" if b["同日还净买了"] else "")))
        if lh.get("净卖前列"):
            L.append(("同逻辑·净卖", "、".join(f"{x['席位']} {x['净卖(万)']} 万" for x in lh["净卖前列"])))
    tl = r.get("题材 / 梯队") or {}
    if tl.get("err"):
        L.append(("同逻辑·题材梯队", f"查询失败 {tl['err'][:80]}"))
    else:
        th = "; ".join(f"{k}: {v['炒作性质']} · {v['阶段']} 第 {v['本波第几天']} 天 · 本票{v['本票位置']} · 题材晋级 {v['题材晋级']} · 同题材 {'、'.join(v['同题材 T 日其他票'][:6]) or '无'}" for k, v in tl["题材"].items()) or "本票不在涨停分析里"
        L.append(("同逻辑·题材梯队", f"T 日 {tl['本票 T 日']} · 全市场梯队 {tl['全市场梯队']} · 最高标 {tl['最高标']} · 市场晋级率 {tl['市场晋级率']} · 涨停家数(涨停分析口径) {tl['涨停家数 T−1→T(涨停分析口径)']} | {th}"))
    hs = r.get("历史同逻辑样本") or {}
    if hs.get("err"):
        L.append(("同逻辑·历史样本", f"查询失败 {hs['err'][:80]}"))
    for k, v in hs.items():
        if k != "err":
            L.append(("同逻辑·历史样本", f"{k}({v['条件']}) 次日最高: {DF.line(v['次日最高'])}; 次日收盘: {DF.line(v['次日收盘'])}"))
    m = r.get("监管 / 筹码 / 电报") or {}
    tl2 = r.get("龙虎榜时间线(近10日)")
    if isinstance(tl2, dict) and tl2.get("err"):
        L.append(("同逻辑·龙虎榜时间线", f"查询失败 {tl2['err'][:80]}"))
    elif tl2:
        L.append(("同逻辑·龙虎榜时间线", " → ".join(f"{x['d'][5:]}({x['板数']}板 {x['涨幅']:+.1f}%) 买[{'、'.join(x['主买'][:2])}]" + (f" 新进{'、'.join(x['新进接力'][:2])}" if x["新进接力"] and x is not tl2[0] else "")
                                                     + (f" ⚠前次主买出货{'、'.join(x['前次主买今天出货'])}" if x["前次主买今天出货"] else "") for x in tl2)))
    else:
        L.append(("同逻辑·龙虎榜时间线", "近 10 日没上过榜"))
    fu = r.get("主买游资后续")
    if fu:
        L.append(("同逻辑·主买游资后续", f"{fu['席位']} 买入后 第1天收盘: {DF.line(fu['买入后第1天收盘'])}; 第2天: {DF.line(fu['买入后第2天收盘'])}; 第3天: {DF.line(fu['买入后第3天收盘'])} | "
                  f"次日有别的游资接力 {fu['次日有别的游资净买接力']}: 有接力→第2天 {DF.line(fu['有接力 → 第2天收盘'])}; 没接力→第2天 {DF.line(fu['没接力 → 第2天收盘'])}"))
    if not m.get("err"):
        L.append(("同逻辑·监管筹码电报", f"近 3 日累计 {m.get('近 3 日累计涨幅')}% · T 日换手 {m.get('T 日换手%')}%" + (f" · ⚠{m['监管提醒']}" if m.get("监管提醒") else "")
                  + (f" · 上榜原因 {'; '.join(m['上榜原因'])[:80]}" if m.get("上榜原因") else "") + (f" · T 日电报 {'; '.join(m['T 日电报点名'])}" if m.get("T 日电报点名") else " · T 日电报未点名")))
    return L


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("D")
    ap.add_argument("--look", type=int, default=250)
    a = ap.parse_args()
    print(json.dumps(_clean(query(a.code, a.D, a.look)), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
