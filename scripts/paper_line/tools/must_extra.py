# -*- coding: utf-8 -*-
"""must_extra.py — 必查补充四项(10/24 用户: 例子 3 怎么还是只有我说的, 没有你建议的扩充; 零 token)

  本体事件   这只票上一个交易日连着什么(状态 / 开板 / 席位 / 题材 / 电报 / 导师交易) —— 事件本体 ontology.db
  炸板回封   上一交易日开过板(股票): 最后一次开板的同标签历史(同高度 / 深度 / 时段 / 大盘) → 封回率 + 次日最高 / 收盘全分布
  市况联动   小盘(国证2000) / 大盘(上证) 跌 ≥1% 或涨 ≥1% 的日子里, 这只票当天收盘的全分布(近 120 个交易日) —— 回答"今天这种市况它一般怎么走"
  正股状态   转债专用: 正股上一交易日的状态(首板 / 炸板 / 跌停 / 回调…)、开板、席位 + 正股自己的近期描述
都只用 D 之前的数据。每项返回 (名称, 文本), 由 pack.must_check 追加进必查(每项一个 E 编号)。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "lib"), str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "ontology")]
import dist_full as DF   # noqa: E402

_C = {}
_TL = __import__("threading").local()   # 10/24: 数据库连接按线程各一条(多本账多线程共用一条连接 → pymysql InterfaceError, 回放里 E6 查询失败)


def _db():
    if getattr(_TL, "c", None) is None:
        import manual_backfill as mb
        _TL.c = mb.db().cursor()
        _TL.c.execute("use investment_market")
    return _TL.c


def prev_day(D):
    k = ("pd", D)
    if k not in _C:
        c = _db()
        c.execute("select max(trade_date) from kline_day where symbol='sh000001' and trade_date < %s and is_deleted=0", (D,))
        r = c.fetchone()
        _C[k] = str(r[0]) if r and r[0] else None
    return _C[k]


def ontology_lines(code, D):
    """→ [(本体事件, …), (炸板回封, …)?]"""
    import query as OQ
    d1 = prev_day(D)
    if not d1:
        return []
    try:
        r = OQ.events(code, d1)
    except SystemExit as e:
        return [("本体事件", str(e))]
    ev = r.get("事件") or []
    if not ev:
        return [("本体事件", f"{d1} 无事件(未上强势股库 / 龙虎榜 / 涨停分析 / 电报 / 导师交易)")]
    out = [("本体事件", f"{d1}: " + " · ".join(e["摘要"] for e in ev[:10]))]
    opens = [e for e in ev if e["eid"].startswith("open:")]
    if opens and code[:1] in ("0", "3", "6"):
        try:
            out.append(("炸板回封", f"{d1} 开板 {len(opens)} 次, 最后一次 → " + OQ.line_stats(OQ.like(opens[-1]["eid"]))))
        except Exception as e:   # noqa: BLE001
            out.append(("炸板回封", f"查询失败 {e!r}"[:80]))
    return out


def _lim(code):
    return 20 if code[:3] in ("300", "301", "688", "689") or code[:2] in ("11", "12") else 30 if code[:1] in ("4", "8", "9") and code[:3] != "900" else 10


def _b13(p, lim, cb=False):
    """13 档(同 similar_days.b13): 涨停 / ≥8 / ≥6 / ≥4 / ≥2 / ≥0 / ≥−2 / ≥−4 / ≥−6 / ≥−8 / <−8 / 跌停;
    10/27 晚用户定: 20cm / 30cm 股票每档仍 2 个点, ±10% 外对称外延到涨跌停(≥18 … <−18); 转债仍按 20cm 等比缩放(每档 4 个点)"""
    import similar_days as _SD
    return _SD.b13(p, lim, cb=cb)


B13_ORDER = ["涨停", "≥8", "≥6", "≥4", "≥2", "≥0", "≥-2", "≥-4", "≥-6", "≥-8", "<-8", "跌停"]


def market_ctx(D, days=130):
    """D 之前约 130 个交易日, 每天的全市场状态(行情库日线全 A 股): 上涨 / 下跌 / 平家数、涨停 / 炸板 / 跌停、炸板率、续板(昨今都涨停) / 断板(昨涨停今没封)、上证 / 国证2000 涨跌
    缓存: 内存 + downloads/market/pattern_scan/market_ctx_<D>.json"""
    k = ("ctx", D)
    if k in _C:
        return _C[k]
    f = ROOT / "downloads" / "market" / "pattern_scan" / f"market_ctx_{D}.json"
    if f.exists():
        _C[k] = json.loads(f.read_text(encoding="utf-8"))
        return _C[k]
    c = _db()
    c.execute("select distinct trade_date from kline_day where symbol='sh000001' and trade_date < %s and is_deleted=0 order by trade_date desc limit %s", (D, days + 1))
    ds = sorted(str(x[0]) for x in c.fetchall())
    if not ds:
        return {}
    c.execute("select k.symbol, k.trade_date, k.high, k.close, k.pre_close from kline_day k join security_master s on s.symbol=k.symbol and s.sec_type='STOCK' "
              "where k.trade_date >= %s and k.trade_date < %s and k.is_deleted=0 and k.pre_close > 0", (ds[0], D))
    by = {}
    for s, d, h, cl, pc in c.fetchall():
        code, lim = s[-6:], _lim(s[-6:])
        up = round(float(pc) * (1 + lim / 100) + 1e-9, 2)
        by.setdefault(str(d), {})[code] = (float(cl) >= up - 0.005, float(h) >= up - 0.005, (float(cl) / float(pc) - 1) * 100, lim)
    c.execute("select symbol, trade_date, close / pre_close - 1 from kline_day where symbol in ('sh000001', 'sz399303') and trade_date >= %s and trade_date < %s and is_deleted=0 and pre_close > 0", (ds[0], D))
    idx = {}
    for s, d, v in c.fetchall():
        idx.setdefault(str(d), {})[s] = round(float(v) * 100, 2)
    out = {}
    for i, d in enumerate(ds):
        X = by.get(d) or {}
        if not X:
            continue
        prev = by.get(ds[i - 1]) if i else {}
        zt = sum(1 for v in X.values() if v[0])
        zb = sum(1 for v in X.values() if v[1] and not v[0])
        dt_ = sum(1 for v in X.values() if v[2] <= -v[3] + 0.2 * v[3] / 10)
        xb = sum(1 for cd, v in X.items() if v[0] and (prev.get(cd) or (False,))[0])
        db = sum(1 for cd, v in X.items() if not v[0] and (prev.get(cd) or (False,))[0])
        n = len(X)
        out[d] = {"up": sum(1 for v in X.values() if v[2] > 0), "down": sum(1 for v in X.values() if v[2] < 0), "n": n, "zt": zt, "zb": zb, "dt": dt_,
                  "zbr": round(zb / (zt + zb) * 100) if zt + zb else 0, "xb": xb, "db": db,
                  "jj": round(xb / max(1, sum(1 for v in (prev or {}).values() if v[0])) * 100) if prev else None, "sh": (idx.get(d) or {}).get("sh000001"), "small": (idx.get(d) or {}).get("sz399303")}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    _C[k] = out
    return out


GROUPS = [   # (名字, 判定) —— 拿一天的市场状态
    ("小盘(国证2000)跌≥1%", lambda m: (m.get("small") or 0) <= -1),
    ("小盘涨≥1%", lambda m: (m.get("small") or 0) >= 1),
    ("大盘(上证)跌≥1%", lambda m: (m.get("sh") or 0) <= -1),
    ("普跌(下跌家数≥70%)", lambda m: m["down"] >= 0.7 * m["n"]),
    ("普涨(上涨家数≥70%)", lambda m: m["up"] >= 0.7 * m["n"]),
    ("炸板率≥40%", lambda m: m["zbr"] >= 40),

]


def _hist(vals, lim, cb=False):
    c = {}
    for v in vals:
        b = _b13(v, lim, cb)
        c[b] = c.get(b, 0) + 1
    key = lambda z: 999 if z == "涨停" else -999 if z == "跌停" else float(z.lstrip("≥<")) - (0.5 if z.startswith("<") else 0)   # noqa: E731  按数值从涨停排到跌停
    return " ".join(f"{b} {c[b]}" for b in sorted(c, key=key, reverse=True))


def market_link(code, D, days=120, detail=True):
    """本票在不同全市场状态下的当天收盘(相对昨收)全分布 + 13 档分布; detail=False 只给两组(小盘跌 / 普跌)"""
    c = _db()
    c.execute("select k.trade_date, k.close / k.pre_close - 1 from kline_day k join security_master s on s.symbol=k.symbol and s.sec_type in ('STOCK', 'CB', 'ETF') "
              "where k.symbol in (%s, %s, %s) and k.trade_date < %s and k.is_deleted=0 and k.pre_close > 0 order by k.trade_date desc limit %s",
              ("sh" + code, "sz" + code, "bj" + code, D, days))
    me = {str(d): float(v) * 100 for d, v in c.fetchall()}
    if len(me) < 20:
        return [("市况联动", f"日线不足({len(me)} 天)")]
    M = market_ctx(D)
    lim = _lim(code)
    jv = sorted(m["jj"] for m in M.values() if m.get("jj") is not None)   # 晋级率门槛按这段时间自己的分位(10/24: 写死 20% 时 131 天里 92 天都算"低")
    G = list(GROUPS)
    if len(jv) >= 20:
        lo_, hi_ = jv[len(jv) // 4], jv[(3 * len(jv)) // 4]
        G += [(f"连板晋级率≤{lo_}%(本段 P25, 接力亏钱)", lambda m, x=lo_: m.get("jj") is not None and m["jj"] <= x),
              (f"连板晋级率≥{hi_}%(本段 P75, 接力赚钱)", lambda m, x=hi_: m.get("jj") is not None and m["jj"] >= x)]
    if not detail:
        G = [GROUPS[0], GROUPS[3]]
    parts = []
    allx = [{"d": d, "v": v} for d, v in me.items()]
    parts.append(f"全部 {len(allx)} 天: {DF.line(DF.full(allx, key=lambda x: x['v'], tag=lambda x: x['d'][5:]))}")
    for nm, fn in G:
        xs = [{"d": d, "v": v} for d, v in me.items() if d in M and fn(M[d])]
        if len(xs) < 3:
            parts.append(f"{nm}: 样本 {len(xs)} 天")
            continue
        s = f"{nm}的 {len(xs)} 天: {DF.line(DF.full(xs, key=lambda x: x['v'], tag=lambda x: x['d'][5:]))}"
        if detail:
            s += f" | 13 档: {_hist([x['v'] for x in xs], lim, code[:2] in ("11", "12"))}"
        parts.append(s)
    last = sorted(M)[-1] if M else None
    ctx = ""
    if last:
        m = M[last]
        ctx = (f" || 参照: 上一交易日 {last[5:]} 全市场 上涨 {m['up']} / 下跌 {m['down']}, 涨停 {m['zt']} / 炸板 {m['zb']}(炸板率 {m['zbr']}%) / 跌停 {m['dt']}, "
               f"续板 {m['xb']} / 断板 {m['db']}(晋级率 {m.get('jj', '-')}%), 上证 {m['sh']:+.2f}% / 国证2000 {m['small']:+.2f}%" if m.get("sh") is not None and m.get("small") is not None else "")
    return [("市况联动", f"近 {len(me)} 个交易日本票收盘(相对昨收)按全市场状态分组(涨停等按日线估算, 和财联社口径略有差): " + " | ".join(parts) + ctx)]


def _cb_stock(cb, D):
    k = ("cbs", cb)
    if k in _C:
        return _C[k]
    mk = ROOT / "downloads" / "market"
    for d in sorted((p.name for p in mk.glob("20*") if p.name < D), reverse=True)[:10]:
        f = mk / d / "cb_facts.jsonl"
        if f.exists():
            for l in f.open(encoding="utf-8"):
                if f'"{cb}"' in l[:20]:
                    x = json.loads(l)
                    _C[k] = (x.get("stock"), x.get("stock_name"))
                    return _C[k]
    _C[k] = (None, None)
    return _C[k]


def cb_stock_state(cb, D):
    s, nm = _cb_stock(cb, D)
    if not s:
        return [("正股状态", "找不到正股代码(cb_facts 里没有)")]
    out = []
    for name, txt in ontology_lines(s, D):
        out.append(("正股状态", f"正股 {s} {nm or ''} {txt}" if name == "本体事件" else f"正股 {s} 炸板回封: {txt}"))
    try:
        import pattern_scan as PS
        r = PS.query(s, D)
        if not r.get("err"):
            out.append(("正股状态", f"正股 {s} 近期({r['数据']}) 描述: {r['描述'][:240]}"))
    except Exception as e:   # noqa: BLE001
        out.append(("正股状态", f"正股近期描述失败 {e!r}"[:80]))
    return out


def lines(code, D, detail=True, market=True):
    out = []
    fns = [(lambda: cb_stock_state(code, D)) if code[:2] in ("11", "12") else (lambda: ontology_lines(code, D) if detail else ontology_lines(code, D)[:1])]
    if market:
        fns.append(lambda: market_link(code, D, detail=detail))
    for fn in fns:
        try:
            out += fn()
        except Exception as e:   # noqa: BLE001  一项失败不拖垮其它
            out.append(("必查补充", f"查询失败 {e!r}"[:100]))
    return out


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for k, v in lines(sys.argv[1], sys.argv[2]):
        print(f"- {k}: {v}")
