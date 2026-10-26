# -*- coding: utf-8 -*-
"""pattern_scan.py — 个股 / 转债"近期规律"(10/24 用户: 我看近期澳弘就能发现规律, 模型为什么不能 → 规律由代码算成事实; 零 token)
10/24 二版(用户: 应该适用所有能找到规律的个股; 规律可以不是冰冷数字, 也可以是描述性的、区间性的):
  ① 描述(每只票都给, 只是描述近期走法, 不代表明天): 每天归一个形态(冲高回落 / 探底回升 / 单边上涨 / 单边下跌 / 窄幅震荡 / 宽幅震荡),
     最高点 / 最低点集中在哪个时段, 冲高 / 回落 / 尾盘拉升的常见区间(P25~P75) → 一句话
  ② 规律(只列回测有预测力的): 形态 / 时段 / 阈值事件近 N 天出现率 ≥ HI, 且回测"近期这样之后第二天出现率 ÷ 全样本出现率" ≥ LIFT_MIN、回测 ≥ BT_MIN_N 次
     给模型的数 = 回测第二天出现率(近期 8/10 ≠ 明天 80%; 10/24 回测: 稀有事件第二天 30~55%, 常见事件无预测力)
数据: 分钟 = downloads/quotes/cb/minute_path(转债 120 天) / downloads/quotes/stock/minute_path(股票关注集 50~60 天), 每行 {code, d, prev, p: 240 个分钟收盘价};
      没有分钟数据的票 → 日线兜底(行情库 kline_day 近 120 天, 全市场都有; 没有时段特征, 不做规律判定只给描述)
形态阈值按本票自己的波动定: thr = 近期日内振幅中位 × 0.4(夹在 1%~4%), 银行股和妖股用同一把尺会失真
局限: 分钟只有收盘价, 冲高 / 回落幅度偏保守。只用 D 之前的数据(防偷看)。
用法: python pattern_scan.py <代码> <D> [N=10] · python pattern_scan.py --backtest [cb|stock]
"""
import collections
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "lib"), str(ROOT / "scripts" / "backfill_bilibili")]
import dist_full as DF   # noqa: E402

SRC = {"cb": ROOT / "downloads" / "quotes" / "cb" / "minute_path", "stock": ROOT / "downloads" / "quotes" / "stock" / "minute_path"}
LAB = [f"{h:02d}:{m:02d}" for h in (9, 10, 11) for m in range(60) if "09:31" <= f"{h:02d}:{m:02d}" <= "11:30"] + \
      [f"{h:02d}:{m:02d}" for h in (13, 14, 15) for m in range(60) if "13:01" <= f"{h:02d}:{m:02d}" <= "15:00"]
IX = {t: i for i, t in enumerate(LAB)}
N_DEF, MIN_N, HI, LO = 10, 6, 0.7, 0.2
LIFT_MIN, BT_MIN_N = 1.5, 30
BT = ROOT / "downloads" / "market" / "pattern_scan"
SLOTS = [("09:31~09:45", "09:31", "09:45"), ("09:46~10:30", "09:46", "10:30"), ("10:31~11:30", "10:31", "11:30"), ("13:01~14:00", "13:01", "14:00"), ("14:01~15:00", "14:01", "15:00")]
SHAPES = ["冲高回落", "探底回升", "单边上涨", "单边下跌", "窄幅震荡", "宽幅震荡"]


def _slot(t):
    return next((n for n, a, b in SLOTS if a <= t <= b), None)


def _ev(key, fn):
    """事件判定: 特征缺(日线没有时段特征)返回 None = 这天不计入"""
    return lambda f: (fn(f[key]) if f.get(key) is not None else None)


EVENTS = [   # (名字, 判定) —— 判定拿一天的特征 dict, 返回 True / False / None(算不了)
    ("高开≥2%", _ev("缺口", lambda v: v >= 2)),
    ("低开≤−1%", _ev("缺口", lambda v: v <= -1)),
    ("30分钟内冲高≥3%", _ev("30分钟高", lambda v: v >= 3)),
    ("30分钟内冲高≥5%", _ev("30分钟高", lambda v: v >= 5)),
    ("15分钟内跌破开盘−2%", _ev("15分钟低", lambda v: v <= -2)),
    ("全天最高在10:00前", _ev("最高时刻", lambda v: v <= "10:00")),
    ("最低点在14:00后", _ev("最低时刻", lambda v: v > "14:00")),
    ("尾盘低点后拉升≥1.5%", _ev("尾盘拉升", lambda v: v >= 1.5)),
    ("收盘低于开盘", _ev("收/开", lambda v: v < 0)),
    ("收盘较最高回落≥3%", _ev("较最高回落", lambda v: v <= -3)),
    ("收盘高于昨收", _ev("收/昨收", lambda v: v > 0)),
] + [(f"形态={s}", _ev("形态", lambda v, s=s: v == s)) for s in SHAPES]
CONT = ["缺口", "30分钟高", "15分钟低", "日内最高", "日内最低", "尾盘拉升", "收/开", "收/昨收", "较最高回落"]


def kind_of(code):
    return "cb" if code[:2] in ("11", "12") else "stock"


def _db():
    import manual_backfill as mb
    c = mb.db().cursor()
    c.execute("use investment_market")
    return c


def _opens(kind, codes=None, since="2026-01-01"):
    """{(code, d): (开盘, 昨收)} 行情库日线"""
    c = _db()
    q = ("select k.symbol, k.trade_date, k.open, k.pre_close from kline_day k join security_master s on s.symbol=k.symbol "
         "where s.sec_type=%s and k.is_deleted=0 and k.trade_date >= %s and k.open > 0")
    args = ["CB" if kind == "cb" else "STOCK", since]
    if codes:
        syms = [px + c_ for c_ in codes for px in ("sh", "sz", "bj")]   # 10/24: 不用 right(symbol, 6)(全表扫 2.7 秒), 枚举完整代码走索引
        q += " and k.symbol in (" + ",".join(["%s"] * len(syms)) + ")"
        args += syms
    c.execute(q, args)
    return {(s[-6:], str(d)): (float(o), float(pc) if pc else None) for s, d, o, pc in c.fetchall()}


def shape(f, thr):
    """一天的形态(相对开盘 %): 日内最高 h / 最低 l / 收 c; 有时段时按先高后低 / 先低后高区分冲高回落和探底回升"""
    h, l, c = f["日内最高"], f["日内最低"], f["收/开"]
    if h - l < thr:
        return "窄幅震荡"
    if c >= thr and c >= h - thr / 2:
        return "单边上涨"
    if c <= -thr and c <= l + thr / 2:
        return "单边下跌"
    up, dn = h >= thr and h - c >= thr, l <= -thr and c - l >= thr
    if up and dn:
        if f.get("最高时刻") and f.get("最低时刻"):
            return "冲高回落" if f["最高时刻"] < f["最低时刻"] else "探底回升"
        return "冲高回落" if h - c >= c - l else "探底回升"
    return "冲高回落" if up else "探底回升" if dn else "宽幅震荡"


def feats(r, op):
    """分钟版一天特征"""
    p, prev = r["p"], r.get("prev")
    if not prev or len(p) != 240 or not all(p):
        return None
    o = op[0] if op else None
    note = None
    if not o:
        o, note = p[0], "开盘≈09:31"
    pc = lambda x, b: round((x / b - 1) * 100, 2)   # noqa: E731
    imax, imin = max(range(240), key=lambda i: p[i]), min(range(240), key=lambda i: p[i])
    tw = p[IX["14:20"]:IX["14:45"] + 1]
    tl = IX["14:20"] + min(range(len(tw)), key=lambda i: tw[i])
    after = p[tl + 1:]
    f = {"d": r["d"], "src": "分钟", "缺口": pc(o, prev), "30分钟高": pc(max(p[:30]), o), "15分钟低": pc(min(p[:15]), o),
         "日内最高": pc(max(max(p), o), o), "日内最低": pc(min(min(p), o), o), "最高时刻": LAB[imax], "最低时刻": LAB[imin],
         "尾盘拉升": pc(max(after), p[tl]) if after else None, "收/开": pc(p[-1], o), "收/昨收": pc(p[-1], prev), "较最高回落": pc(p[-1], max(max(p), o))}
    if note:
        f["注"] = note
    return f


def _finish(F):
    """按本票振幅定形态阈值, 补 形态 / 高低点时段"""
    rng = [x["日内最高"] - x["日内最低"] for x in F]
    thr = min(4.0, max(1.0, st.median(rng) * 0.4)) if rng else 2.0
    for x in F:
        x["形态"] = shape(x, thr)
        if x.get("最高时刻"):
            x["高点时段"], x["低点时段"] = _slot(x["最高时刻"]), _slot(x["最低时刻"])
    return F, thr


def load_daily(code, D, days=120):
    """日线兜底(全市场都有): 只有 缺口 / 日内最高最低 / 收开 / 收昨收 / 较最高回落, 没有时段"""
    c = _db()
    c.execute("select k.trade_date, k.open, k.high, k.low, k.close, k.pre_close from kline_day k join security_master s on s.symbol=k.symbol and s.sec_type in ('STOCK', 'CB') "
              "where k.symbol in (%s, %s, %s) and k.trade_date < %s and k.is_deleted=0 and k.open > 0 "
              "order by k.trade_date desc limit %s", ("sh" + code, "sz" + code, "bj" + code, D, days))   # 10/24: 只按后 6 位会把 sh000002(A股指数)和 sz000002(万科)混在一起
    out = []
    for d, o, h, l, cl, pc_ in reversed(c.fetchall()):
        o, h, l, cl, pc_ = float(o), float(h), float(l), float(cl), float(pc_ or 0)
        if not pc_:
            continue
        p = lambda x, b: round((x / b - 1) * 100, 2)   # noqa: E731
        out.append({"d": str(d), "src": "日线", "缺口": p(o, pc_), "日内最高": p(h, o), "日内最低": p(l, o), "收/开": p(cl, o), "收/昨收": p(cl, pc_), "较最高回落": p(cl, h)})
    return out


def load_code(code, D=None, kind=None):
    """这只票全部历史日特征(按日期), 只取 D 之前; 没有分钟数据 → 日线兜底"""
    kind = kind or kind_of(code)
    rows = []
    for f in sorted(SRC[kind].glob("20*.jsonl")):
        if D and f.stem >= D:
            continue
        with f.open(encoding="utf-8") as fh:
            for l in fh:
                if f'"{code}"' in l[:30]:
                    r = json.loads(l)
                    if r.get("code") == code:
                        rows.append(r)
                    break
    out = []
    if rows:
        op = _opens(kind, [code])
        out = [x for x in (feats(r, op.get((code, r["d"]))) for r in rows) if x]
    if len(out) < MIN_N and D:
        out = load_daily(code, D)
    return _finish(out)[0] if out else out


def _bt(kind):
    f = BT / f"bt_{kind}.json"
    return json.loads(f.read_text(encoding="utf-8"))["结果"] if f.exists() else {}


def _rate(xs, fn):
    v = [fn(x) for x in xs]
    v = [b for b in v if b is not None]
    return (sum(v), len(v)) if v else (0, 0)


def describe(rec, lng):
    """描述性 / 区间性(不是预测): 每种形态带日期, 有分钟数据带最高 / 最低点时刻; 区间给 P25~P75 + 均值 + 两端极值(带日期)"""
    if not rec:
        return ""
    d5 = lambda x: x["d"][5:]   # noqa: E731
    sh = {}
    for x in rec:
        sh.setdefault(x["形态"], []).append(x)
    parts = ["形态 " + " / ".join(f"{k} {len(v)} 天(" + "、".join(d5(x) + (f" 高{x['最高时刻']}低{x['最低时刻']}" if x.get("最高时刻") else "") for x in v) + ")"
                               for k, v in sorted(sh.items(), key=lambda z: -len(z[1])))]
    for key, nm in (("高点时段", "最高点"), ("低点时段", "最低点")):
        c = {}
        for x in rec:
            if x.get(key):
                c.setdefault(x[key], []).append(x)
        if c:
            k, v = max(c.items(), key=lambda z: len(z[1]))
            tot = sum(len(z) for z in c.values())
            if len(v) / tot >= 0.5:
                tk = "最高时刻" if key == "高点时段" else "最低时刻"
                parts.append(f"{nm}多在 {k}({len(v)}/{tot}: " + "、".join(f"{d5(x)} {x[tk]}" for x in v) + ")")
    for key, nm in (("缺口", "开盘缺口"), ("30分钟高", "开盘 30 分钟冲高"), ("日内最高", "日内最高(相对开盘)"), ("较最高回落", "收盘较最高回落"), ("尾盘拉升", "尾盘低点后拉升")):
        xs = sorted((x for x in rec if x.get(key) is not None), key=lambda x: x[key])
        if len(xs) >= MIN_N:
            v = [x[key] for x in xs]
            parts.append(f"{nm} P25~P75 {v[len(v) // 4]:+.1f}%~{v[(3 * len(v)) // 4]:+.1f}% 均 {sum(v) / len(v):+.1f}% "
                         f"最低 {v[0]:+.1f}%({d5(xs[0])}) 最高 {v[-1]:+.1f}%({d5(xs[-1])})")
    if lng and len(lng) >= 20:
        ls = {}
        for x in lng:
            ls[x["形态"]] = ls.get(x["形态"], 0) + 1
        top = max(sh.items(), key=lambda z: len(z[1]))
        parts.append(f"(长期 {len(lng)} 天里 {top[0]} 占 {ls.get(top[0], 0) / len(lng):.0%}, 近期 {len(top[1]) / len(rec):.0%})")
    return "; ".join(parts)


def scan(F, N=N_DEF, kind="cb"):
    """F = 按日期排好的日特征 → (规律列表, 近期 / 长期分布)"""
    rec, lng = F[-N:], F[:-N] if len(F) > N else []
    pats, bt = [], (_bt(kind) if F and F[-1].get("src", "分钟") == "分钟" else {})
    for name, fn in EVENTS:
        k, n = _rate(rec, fn)
        if n < MIN_N:
            continue
        rate = k / n
        lk, ln = _rate(lng, fn)
        lrate = lk / ln if ln else None
        if not (rate >= HI or rate <= LO):
            continue
        tag = "近期常出现" if rate >= HI else "近期几乎不出现"
        cmp_ = "长期样本不足" if lrate is None or ln < 10 else "长期也如此" if abs(rate - lrate) < 0.2 else f"近期才{'出现' if rate > lrate else '消失'}"
        b = bt.get(name) or {}
        if rate >= HI:
            nxt, base, nb, nc = b.get("第二天出现率"), b.get("全样本出现率"), b.get("近期≥70% 次数") or 0, b.get("近期≥70% 票数")
        else:
            nxt, base, nb, nc = b.get("第二天出现率(低)"), b.get("全样本出现率"), b.get("近期≤20% 次数") or 0, None
        if not b:
            continue   # 没有回测(日线兜底 / 新事件) → 不当规律报, 描述里已经有
        if rate >= HI and (nb < BT_MIN_N or not base or (nxt or 0) / base < LIFT_MIN):
            continue
        if rate <= LO and (nb < BT_MIN_N or (base or 0) < 0.3 or (nxt if nxt is not None else 1) > base / LIFT_MIN):
            continue   # "近期几乎不出现": 本来就少见的不提供信息; 回测第二天出现率没明显低于基准的也不报(10/24: 300750 收盘高于昨收 2/10 → 第二天 43% vs 44%)
        pats.append({"事件": name, "回测第二天": f"回测: 近期这样之后第二天出现 {nxt:.0%}(全样本 {base:.0%}; n={nb}" + (f", 来自 {nc} 只" if nc else "") + ")",
                     "近期": f"{k}/{n}", "出现率": round(rate, 2), "长期": f"{lk}/{ln}" if ln else "-", "长期出现率": round(lrate, 2) if lrate is not None else None,
                     "判断": tag, "对照": cmp_, "出现的日子": [x["d"][5:] for x in rec if fn(x)][-8:]})
    dist = {}
    for c in CONT:
        r = [x for x in rec if x.get(c) is not None]
        g = [x for x in lng if x.get(c) is not None]
        if r:
            dist[c] = {"近期": DF.full(r, key=lambda x, c=c: x[c], tag=lambda x: x["d"][5:]), **({"长期": DF.full(g, key=lambda x, c=c: x[c], tag=lambda x: x["d"][5:])} if len(g) >= 10 else {})}
    return pats, dist


def query(code, D, N=N_DEF):
    F = load_code(code, D)
    if not F:
        return {"code": code, "D": D, "err": "没有分钟也没有日线数据"}
    pats, dist = scan(F, N, kind_of(code))
    last, lng = F[-N:], F[:-N]
    src = F[-1].get("src", "分钟")
    return {"code": code, "D": D, "数据": src, "有效天数": len(F), "近期窗口": f"{last[0]['d']}~{last[-1]['d']} {len(last)} 天",
            "描述": describe(last, lng), "近期规律": pats, "特征分布(近期 vs 长期)": dist,
            "近期逐日": [{k: v for k, v in x.items() if k not in ("注", "src")} for x in last],
            "口径": f"描述 = 近期走法(不代表明天); 规律 = 出现率 ≥{HI:.0%} 或 ≤{LO:.0%} 且回测有预测力(第二天出现率 ≥ 全样本 × {LIFT_MIN}, 回测 ≥{BT_MIN_N} 次)"
                    + ("; 日线兜底: 没有时段特征, 不做规律判定" if src == "日线" else "; 只有分钟收盘价, 冲高 / 回落偏保守"),
            "提示": "引用规律时写回测第二天出现率, 不写近期出现率当概率; 描述只说明近期怎么走"}


def must_line(code, D, N=N_DEF, brief=False):
    r = query(code, D, N)
    if r.get("err"):
        return [("近期规律", r["err"])]
    if brief:   # 简版: 只报回测有预测力的规律, 不带描述(描述 ./q pattern)
        s = "; ".join(f"{p['事件']} 近期 {p['近期']}({p['回测第二天']})" for p in r["近期规律"])
        return [("近期规律", f"({r['数据']}) " + (s or "无回测有预测力的形态") + "; 描述 ./q pattern")]
    s = "; ".join(f"{p['事件']} 近期 {p['近期']}(长期 {p['长期']}, {p['对照']}; {p['回测第二天']})" for p in r["近期规律"])
    return [("近期规律", f"{r['近期窗口']}({r['数据']}) 描述: {r['描述']}" + (f" | 规律(回测有预测力): {s}" if s else " | 规律: 无回测有预测力的形态"))]


def backtest(kind="cb", N=N_DEF):
    """每只票每天: 用前 N 天判"近期常出现(≥HI)" → 看当天是否出现; 基准 = 该事件全样本出现率"""
    by = collections.defaultdict(list)
    files = sorted(SRC[kind].glob("20*.jsonl"))
    for f in files:
        for l in f.open(encoding="utf-8"):
            r = json.loads(l)
            by[r["code"]].append(r)
    op = _opens(kind, since=files[0].stem if files else "2026-01-01")
    F = {}
    for c, v in by.items():
        xs = [x for x in (feats(r, op.get((c, r["d"]))) for r in sorted(v, key=lambda z: z["d"])) if x]
        if xs:
            F[c] = _finish(xs)[0]
    res = {}
    for name, fn in EVENTS:
        allv = [b for v in F.values() for b in (fn(x) for x in v) if b is not None]
        base = sum(allv) / len(allv) if allv else 0
        flag_hi = flag_lo = hit_hi = hit_lo = 0
        codes_hi = set()
        for c, v in F.items():
            for i in range(N, len(v)):
                k, n = _rate(v[i - N:i], fn)
                today = fn(v[i])
                if n < MIN_N or today is None:
                    continue
                rate = k / n
                if rate >= HI:
                    flag_hi += 1
                    hit_hi += today
                    codes_hi.add(c)
                elif rate <= LO:
                    flag_lo += 1
                    hit_lo += today
        res[name] = {"全样本出现率": round(base, 3), "近期≥70% 次数": flag_hi, "近期≥70% 票数": len(codes_hi), "第二天出现率": round(hit_hi / flag_hi, 3) if flag_hi else None,
                     "近期≤20% 次数": flag_lo, "第二天出现率(低)": round(hit_lo / flag_lo, 3) if flag_lo else None}
    out = {"kind": kind, "票数": len(F), "票日": sum(len(v) for v in F.values()), "天数": len(files), "N": N, "HI": HI, "LO": LO, "结果": res}
    BT.mkdir(parents=True, exist_ok=True)
    (BT / f"bt_{kind}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = sys.argv[1:]
    if not a:
        print(__doc__)
    elif a[0] == "--backtest":
        print(json.dumps(backtest(a[1] if len(a) > 1 else "cb"), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(query(a[0], a[1], int(a[2]) if len(a) > 2 else N_DEF), ensure_ascii=False, indent=1))
