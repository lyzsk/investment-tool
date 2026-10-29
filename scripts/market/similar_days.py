# -*- coding: utf-8 -*-
"""similar_days.py — 拓扑 / 相似日库 v2(转债; 10/22 晚用户定细分口径; 零 token, 只读行情库)

为什么(用户 10/22 教): 算振幅 / 概率不能拿全历史中位数, 要先按 市况 + 拓扑 + 当时状态 筛相似日, 再看相似日的走势分布。
v1 → v2(10/22 19:4x 用户定): 分档改细(13 档) + 加竞价开盘幅度 + 前一日 K 线形态 + 更细的大盘风格 + 多个分钟窗口的最高
  特征(都是 D 日 09:25 前已知):
    gap        D 日竞价开盘相对昨收(转债自身): ≥6 / 4~6 / 2~4 / 1~2 / 0~1 / −1~0 / −2~−1 / −4~−2 / −6~−4 / <−6 (%)   ← 10/22 实测最有用
    stk_prev   正股前一日涨跌 13 档: 涨停 / >8 / 6~8 / 4~6 / 2~4 / 0~2 / −2~0 / −4~−2 / −6~−4 / −8~−6 / <−8 / 跌停(主板 ±10、创业科创 ±20 按比例换算)
    cb_prev    转债前一日涨跌 13 档(转债 ±20 涨跌幅; 档位同上 ×2)
    kline      转债前一日 K 线形态: 大阳 / 小阳 / 十字 / 小阴 / 大阴 × 上影长 / 下影长 / 光头光脚(实体 = |收−开|/昨收, 影线 = 占全天振幅比例)
    spike      暴涨后状态: 无 / 未回撤 / 退潮 5~15% / 深退 >15%(前 10 日内收盘曾较 20 日前涨 ≥40%)
    level      转债价位: <130 / 130~180 / 180~250 / ≥250
    mkt        前一日大盘: 上证 × 创业板 各 5 档(≥1.5 / 0.5~1.5 / −0.5~0.5 / −1.5~−0.5 / ≤−1.5)
  结果(D 日): 开盘后最高 / 最低 / 收盘相对开盘 / 振幅 + 有分钟数据的: 开盘后 5 / 10 / 15 / 30 / 60 分钟内最高
  匹配: 全条件精确匹配, 样本 <15 逐级放宽(先去 mkt → kline → level → cb_prev → spike, 最后只留 gap + stk_prev), 每级报 n
用法:
  python similar_days.py --build
  python similar_days.py --query 111024 --date 2026-10-23 [--gap 2.5]      (--gap 不给 = 09:25 前查, 不用竞价特征)
"""
import argparse
import bisect
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "downloads" / "market" / "similar"
LIB = OUT / "cb_days.jsonl"
SINCE = "2023-01-01"
MIN_N = 15
WINS = (("hi5", 5), ("hi10", 10), ("hi15", 15), ("hi30", 30), ("hi60", 60))


def db():
    sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))   # dist_full
    import manual_backfill as mb
    c = mb.db()
    c.cursor().execute("use investment_market")
    return c


def cb_map():
    fs = sorted(glob.glob(str(ROOT / "downloads" / "quotes" / "cb" / "meta" / "RPT_BOND_CB_LIST_all_*.json")))
    m = json.loads(Path(fs[-1]).read_text(encoding="utf-8")) if fs else []
    rows = m if isinstance(m, list) else ((m.get("result") or {}).get("data") or m.get("data") or [])
    return {str(r.get("SECURITY_CODE")): str(r.get("CONVERT_STOCK_CODE") or "") for r in rows if r.get("CONVERT_STOCK_CODE")}


def b13(p, lim, cb=False):
    """13 档; lim = 该品种涨跌停幅度(主板 10 / 创业科创 20 / 转债 20)
    10/27 晚用户定: 20cm(30cm)股票 = 主板 13 档(每档 2 个点)+ 往 ±10%~±lim 对称外延, 每档仍 2 个点(≥18 / ≥16 … ≥−18 / <−18); 10/28 晚: 转债同 20cm 口径"""
    if p is None:
        return None
    u = lim / 10
    if p >= lim - 0.2 * u:
        return "涨停"
    if p <= -lim + 0.2 * u:
        return "跌停"
    if lim <= 10:   # 10/28 晚用户定: 转债也按 20cm 同口径外延(原 cb 也走这里 = 每档 4 个点)
        for e in (8, 6, 4, 2, 0, -2, -4, -6, -8):
            if p >= e * u:
                return f"≥{e * u:g}"
        return f"<{-8 * u:g}"
    top = int(lim) - 2
    for e in range(top, -top - 1, -2):
        if p >= e:
            return f"≥{e:g}"
    return f"<{-top:g}"


def b_gap(g):
    if g is None:
        return None
    for e in (6, 4, 2, 1, 0, -1, -2, -4, -6):
        if g >= e:
            return f"≥{e}"
    return "<-6"


def b_idx(p):
    return None if p is None else "≥1.5" if p >= 1.5 else "0.5~1.5" if p >= 0.5 else "−0.5~0.5" if p > -0.5 else "−1.5~−0.5" if p > -1.5 else "≤−1.5"


def b_level(c):
    return "<130" if c < 130 else "130~180" if c < 180 else "180~250" if c < 250 else "≥250"


def b_kline(o, h, l, c, pc):
    body = (c - o) / pc * 100
    rng = max(h - l, 1e-9)
    up, dn = (h - max(o, c)) / rng, (min(o, c) - l) / rng
    kind = "大阳" if body >= 3 else "小阳" if body >= 0.5 else "大阴" if body <= -3 else "小阴" if body <= -0.5 else "十字"
    sh = "上影长" if up >= 0.4 else "下影长" if dn >= 0.4 else "光头光脚" if up < 0.1 and dn < 0.1 else ""
    return kind + ("·" + sh if sh else "")


def board_lim(stk):
    return 20.0 if stk.startswith(("300", "301", "688", "689")) else 10.0


def series(cur, symbols, since=SINCE):
    if not symbols:
        return {}
    cur.execute(f"select symbol, trade_date, open, high, low, close from kline_day where is_deleted=0 and trade_date >= %s and symbol in ({','.join(['%s'] * len(symbols))}) order by symbol, trade_date",
                (since, *symbols))
    S = {}
    for s, d, o, h, l, c in cur.fetchall():
        if o and c:
            S.setdefault(s, []).append((str(d), float(o), float(h), float(l), float(c)))
    return S


def mkt_map(cur):
    S = series(cur, ["sh000001", "sz399006"], "2022-12-01")
    out = {}
    for s, k in S.items():
        for i in range(1, len(k)):
            out.setdefault(k[i][0], {})[s] = (k[i][4] / k[i - 1][4] - 1) * 100
    return {d: f"上证{b_idx(v.get('sh000001'))}/创业{b_idx(v.get('sz399006'))}" for d, v in out.items()}


_MP = {}


def minute_path(code, d):
    """开盘后每分钟最高(相对开盘价)的来源: ①cb/minute/<code>/<d>.json(逐笔合成, 有高低) ②cb/minute_path/<d>.jsonl(分时价, 无高低, 用分钟价代替)"""
    f = ROOT / "downloads" / "quotes" / "cb" / "minute" / code / f"{d}.json"
    if f.exists():
        bars = (json.loads(f.read_text(encoding="utf-8")) or {}).get("bars") or []
        return [b["h"] for b in bars if b["t"] > "09:30"]
    if d not in _MP:
        g = ROOT / "downloads" / "quotes" / "cb" / "minute_path" / f"{d}.jsonl"
        _MP[d] = {}
        if g.exists():
            for l in g.read_text(encoding="utf-8").splitlines():
                r = json.loads(l)
                _MP[d][r["code"]] = r["p"]
    return _MP[d].get(code)


def minute_feats(code, d, o):
    hs = minute_path(code, d)
    if not hs or not o:
        return {}
    return {k: round((max(hs[:n]) / o - 1) * 100, 3) for k, n in WINS if len(hs) >= n}


def feats(k, i, st_k, st_d, lim, mkt):
    d, o, h, l, c = k[i]
    pc = k[i - 1][4]
    p2 = k[i - 2][4]
    closes = [x[4] for x in k[i - 21:i]]
    spike = max(closes[-10:]) >= closes[0] * 1.4
    dd = (pc / max(closes[-5:]) - 1) * 100
    j = bisect.bisect_left(st_d, d)
    sp = (st_k[st_d[j - 1]] / st_k[st_d[j - 2]] - 1) * 100 if j >= 2 and st_d[j - 1] < d else None
    po, ph, pl = k[i - 1][1], k[i - 1][2], k[i - 1][3]
    return {"gap_pct": round((o / pc - 1) * 100, 3), "gap": b_gap((o / pc - 1) * 100), "stk_prev_pct": None if sp is None else round(sp, 3), "stk_prev": b13(sp, lim),
            "cb_prev": b13((pc / p2 - 1) * 100, 20, cb=True), "kline": b_kline(po, ph, pl, pc, p2), "level": b_level(pc),
            "spike": ("退潮" if spike and -15 <= dd <= -5 else "深退" if spike and dd < -15 else "未回撤" if spike else "无"), "mkt": mkt.get(k[i - 1][0])}


def build():
    cur = db().cursor()
    cur.execute("select symbol, code from security_master where sec_type='CB'")
    cbs = {code: sym for sym, code in cur.fetchall()}
    M = cb_map()
    stk_syms = {c: ("sh" if s.startswith(("6", "9")) else "sz") + s for c, s in M.items() if s}
    S = series(cur, list(cbs.values()))
    T = series(cur, list(set(stk_syms.values())))
    mkt = mkt_map(cur)
    n = 0
    OUT.mkdir(parents=True, exist_ok=True)
    with LIB.open("w", encoding="utf-8") as fo:
        for code, sym in cbs.items():
            k = S.get(sym) or []
            st_k = {d: c for d, _, _, _, c in T.get(stk_syms.get(code, ""), [])}
            st_d = sorted(st_k)
            lim = board_lim(M.get(code, ""))
            for i in range(21, len(k)):
                d, o, h, l, c = k[i]
                pc = k[i - 1][4]
                rec = {"code": code, "d": d, "pc": pc, **feats(k, i, st_k, st_d, lim, mkt),
                       "hi": round((h / o - 1) * 100, 3), "lo": round((l / o - 1) * 100, 3), "co": round((c / o - 1) * 100, 3), "amp": round((h - l) / pc * 100, 3)}
                rec.update(minute_feats(code, d, o))
                fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
    print("建库完成", n, "个转债日 →", LIB)


def q(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * p))], 2)


TIERS = [["gap", "stk_prev", "spike", "cb_prev", "level", "kline", "mkt"], ["gap", "stk_prev", "spike", "cb_prev", "level", "kline"],
         ["gap", "stk_prev", "spike", "cb_prev", "level"], ["gap", "stk_prev", "spike", "cb_prev"], ["gap", "stk_prev", "spike"], ["gap", "stk_prev"], ["gap"]]


_LIB = None


def _lib():
    """库只读一次(paper v3 材料包一次查十几只转债, 每次重读 19 万行太慢)"""
    global _LIB
    if _LIB is None:
        _LIB = [json.loads(l) for l in LIB.read_text(encoding="utf-8").splitlines()]
    return _LIB


def query(code, D, gap=None):
    cur = db().cursor()
    cur.execute("select symbol from security_master where code=%s and sec_type='CB'", (code,))
    sym = cur.fetchone()[0]
    k = [x for x in series(cur, [sym])[sym] if x[0] < D]
    stk = cb_map().get(code, "")
    T = series(cur, [("sh" if stk.startswith(("6", "9")) else "sz") + stk]) if stk else {}
    st_k = {d: c for d, _, _, _, c in (list(T.values())[0] if T else []) if d < D}
    fake_open = k[-1][4] * (1 + (gap or 0) / 100)
    kk = k + [(D, fake_open, fake_open, fake_open, fake_open)]
    cur_f = feats(kk, len(kk) - 1, st_k, sorted(st_k), board_lim(stk), mkt_map(cur))
    lib = [r for r in _lib() if r["d"] < D]
    tiers = TIERS if gap is not None else [[x for x in t if x != "gap"] for t in TIERS[:-1]]
    out = {"code": code, "D": D, "当前特征": {x: cur_f[x] for x in ("gap", "stk_prev", "cb_prev", "kline", "spike", "level", "mkt")} if gap is not None else
           {x: cur_f[x] for x in ("stk_prev", "cb_prev", "kline", "spike", "level", "mkt")}, "tiers": []}
    for keys in tiers:
        xs = [r for r in lib if all(r.get(x) == cur_f.get(x) for x in keys)]
        t = {"按": keys, "n": len(xs)}
        if xs:
            import dist_full as DF   # 10/24 用户令: 统一报全分布(均值 / 中位 / P10~P90 / 最差 / 最好 + 案例), 不能只报中位
            tg = lambda r: f"{r.get('code')} {r.get('d')}"   # noqa: E731
            t.update({"开盘后最高 P25/P40/中位/P75": [q([r["hi"] for r in xs], p) for p in (.25, .4, .5, .75)], "最低 中位": q([r["lo"] for r in xs], .5),
                      "收盘相对开盘 中位": q([r["co"] for r in xs], .5), "收>开 比例": round(sum(1 for r in xs if r["co"] > 0) / len(xs), 2),
                      "开盘后最高 全分布": DF.full(xs, key=lambda r: r["hi"], tag=tg), "最低 全分布": DF.full(xs, key=lambda r: r["lo"], tag=tg),
                      "收盘相对开盘 全分布": DF.full(xs, key=lambda r: r["co"], tag=tg)})
            if gap is None:
                t["竞价开盘 中位"] = q([r["gap_pct"] for r in xs], .5)
            for kname, n in WINS:
                v = [r[kname] for r in xs if kname in r]
                if v:
                    t[f"开盘 {n} 分钟内最高 中位 / P40 (n)"] = (q(v, .5), q(v, .4), len(v))
        out["tiers"].append(t)
        if len(xs) >= MIN_N:
            break
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--query")
    ap.add_argument("--date")
    ap.add_argument("--gap", type=float)
    a = ap.parse_args()
    if a.build:
        build()
    if a.query:
        print(json.dumps(query(a.query, a.date, a.gap), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
