# -*- coding: utf-8 -*-
"""similar_days.py — 相似市况检索(TODO 三-2f, 10/17 ② agent; 零 token, 只读行情库 investment_market)

市况向量(每个交易日收盘可知, 只用 ≤ 该日数据):
  上证 1/5/20 日涨跌 · 创业板指 1 日涨跌 · 两市股票成交额 / 前 20 日均值(对数) · 上涨家数占比
  · 涨停数 · 跌停数(对数) · 炸板率(触板未封 / 触板) · 最高连板 · 2 板及以上家数(对数)
  —— 主线强度暂用"连板梯队宽度(2板+家数)+最高连板"代理(行业/题材时点表 一-5j 建好后可换成"涨停最集中题材占比")。
  标准化: 用 2025-01 起全样本的均值/标准差(z-score; 已知的轻度后见: 只影响尺度, 不影响"谁更像"的排序太多)。
检索: 查询日 Q = 链日 D 的前一交易日收盘; 候选 = 2025-01-02 ~ Q 前 6 个交易日(要有"之后几天");
  相似度 = exp(−加权欧氏距离²/2) × 0.5^(距今交易日/HALF_LIFE)(近期按时间衰减), 取前 3(彼此间隔 ≥3 个交易日, 防同一段行情占满)。
输出每个相似日: 当日市况 + 之后 1/3/5 日上证涨跌、次日涨停数 + 导师当时(相似日的下一交易日 = 对应"今天")怎么做:
  tzzb 导师=真人账本(出手/方向/收盘总仓/买了什么, mimicry 同口径); 桃哥/卢本圆=md「今日操作」; 其余=无。
产物: scripts/dfcf/paper/similar_days/<D>.json(市况部分; 导师部分注入时现算); 驱动器经 quality_hooks 读(开关 CHAIN_SIMILAR_DAYS, 默认 0)。
CLI(scripts/venv/Scripts/python.exe -X utf8):
  similar_days.py --build [--date 2026-10-19]      (收盘后/盘前跑; 一次全量 SQL 约 10~20 秒)
  similar_days.py --show --date D [--skill x]       打印注入文本
  similar_days.py --selftest
"""
import argparse
import json
import math
import sys
from datetime import date as _date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "similar_days"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
sys.path.insert(0, str(ROOT / "scripts" / "bilibili"))

START = "2024-11-01"          # 取数起点(留 20 日回看)
CAND_FROM = "2025-01-02"
GAP_AFTER = 6                 # 候选须在查询日前 ≥6 个交易日(有 5 日后续)
HALF_LIFE = 250.0             # 时间衰减半衰期(交易日)
TOPK, MIN_SEP = 3, 3
FEATS = ["idx1", "idx5", "idx20", "cy1", "amt_r", "up_ratio", "zt", "dt", "zb_rate", "max_lb", "lb2"]
W = {"idx1": 1.0, "idx5": 1.0, "idx20": 0.8, "cy1": 0.6, "amt_r": 1.0, "up_ratio": 1.0, "zt": 1.2, "dt": 0.8, "zb_rate": 0.8, "max_lb": 1.0, "lb2": 1.0}
CN = {"idx1": "上证当日", "idx5": "上证5日", "idx20": "上证20日", "cy1": "创业板当日", "amt_r": "成交额/20日均", "up_ratio": "上涨占比",
      "zt": "涨停", "dt": "跌停", "zb_rate": "炸板率", "max_lb": "最高连板", "lb2": "2板+"}


def _rate(sym):
    c = sym[2:]
    if sym.startswith("bj"):
        return 0.30
    if c.startswith(("30", "68")):
        return 0.20
    return 0.10


def market_table(start=START, until=None):
    """→ {"dates": [...], "raw": {feat: list}}(逐日, 只用 ≤ 当日数据)"""
    import pandas as pd
    from kline_db import db
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("select symbol, trade_date, cast(high as double), cast(low as double), cast(close as double), cast(pre_close as double), "
                    "cast(amount as double) from kline_day where trade_date >= %s and trade_date < %s and (symbol like 'sh60%%' or symbol like 'sz00%%' "
                    "or symbol like 'sz30%%' or symbol like 'sh68%%' or symbol like 'bj%%' or symbol in ('sh000001', 'sz399006'))",
                    (start, until or "2999-12-31"))
        rows = cur.fetchall()
        cur.execute("select symbol, name, list_date from security_master")
        sm = {s: (n or "", ld) for s, n, ld in cur.fetchall()}
    finally:
        conn.close()
    df = pd.DataFrame(rows, columns=["sym", "d", "h", "l", "c", "pc", "amt"])
    df["d"] = df["d"].astype(str)
    idx = df[df.sym == "sh000001"].set_index("d")["c"].sort_index()
    cy = df[df.sym == "sz399006"].set_index("d")["c"].sort_index()
    st = df[~df.sym.isin(["sh000001", "sz399006"])].copy()
    st = st[(st.pc > 0) & (st.c > 0)]
    st["ld"] = st.sym.map(lambda s: str(sm.get(s, ("", None))[1] or ""))
    st = st[(st.ld == "") | (st.d > st.ld)]                       # 上市当日起算: 新股前 5 日下面按交易日剔
    name = st.sym.map(lambda s: sm.get(s, ("", None))[0])
    r = st.sym.map(_rate).astype(float)
    is_st = name.str.contains("ST", na=False) & ~st.sym.str[2:].str.startswith(("30", "68")) & (st.d < "2026-07-06")
    r = np.where(is_st, 0.05, r)
    lu = np.floor(st.pc * (1 + r) * 100 + 0.5 + 1e-6) / 100
    ld = np.floor(st.pc * (1 - r) * 100 + 0.5 + 1e-6) / 100
    st["zt"] = st.c >= lu - 0.005
    st["touch"] = st.h >= lu - 0.005
    st["dt"] = st.c <= ld + 0.005
    st["up"] = st.c > st.pc
    st["dn"] = st.c < st.pc
    st = st.sort_values(["sym", "d"])
    st["nth"] = st.groupby("sym").cumcount()
    st.loc[(st.ld != "") & (st.nth < 5) & (st.ld >= start), ["zt", "touch", "dt"]] = False   # 新股前 5 日无涨跌幅
    g = (~st.zt).groupby(st.sym).cumsum()
    st["lb"] = st.zt.groupby([st.sym, g]).cumsum()
    day = st.groupby("d").agg(zt=("zt", "sum"), touch=("touch", "sum"), dt=("dt", "sum"), up=("up", "sum"), dn=("dn", "sum"),
                              amt=("amt", "sum"), max_lb=("lb", "max"), lb2=("lb", lambda x: int((x >= 2).sum())))
    dates = [d for d in day.index if d in idx.index]
    day = day.loc[dates]
    ix = idx.reindex(dates)
    cyx = cy.reindex(dates)
    amt20 = day.amt.rolling(20, min_periods=10).mean().shift(1)
    raw = {"idx1": (ix / ix.shift(1) - 1), "idx5": (ix / ix.shift(5) - 1), "idx20": (ix / ix.shift(20) - 1), "cy1": (cyx / cyx.shift(1) - 1),
           "amt_r": np.log(day.amt / amt20), "up_ratio": day.up / (day.up + day.dn).clip(lower=1), "zt": np.log1p(day.zt.astype(float)),
           "dt": np.log1p(day.dt.astype(float)), "zb_rate": (day.touch - day.zt) / day.touch.clip(lower=1),
           "max_lb": day.max_lb.clip(upper=10).astype(float), "lb2": np.log1p(day.lb2.astype(float))}
    raw_out = {k: [None if (v is None or not np.isfinite(v)) else float(v) for v in raw[k].values] for k in FEATS}
    show = {"zt_n": day.zt.astype(int).tolist(), "dt_n": day.dt.astype(int).tolist(), "lb2_n": day.lb2.astype(int).tolist(),
            "amt_e8": (day.amt / 1e8).round(0).tolist(), "idx_close": ix.round(2).tolist()}
    return {"dates": dates, "raw": raw_out, "show": show}


def zscore(tab, since=CAND_FROM):
    ds = tab["dates"]
    Z = np.full((len(ds), len(FEATS)), np.nan)
    stats = {}
    for j, k in enumerate(FEATS):
        v = np.array([np.nan if x is None else x for x in tab["raw"][k]], float)
        ref = v[[i for i, d in enumerate(ds) if d >= since]]
        mu, sd = np.nanmean(ref), np.nanstd(ref)
        stats[k] = (float(mu), float(sd))
        Z[:, j] = (v - mu) / (sd if sd > 0 else 1.0)
    return Z, stats


def search(tab, q_date, topk=TOPK):
    ds = tab["dates"]
    if q_date not in ds:
        prior = [d for d in ds if d <= q_date]
        if not prior:
            return []
        q_date = prior[-1]
    qi = ds.index(q_date)
    Z, _ = zscore(tab)
    w = np.array([W[k] for k in FEATS])
    q = Z[qi]
    ok = np.isfinite(q)
    res = []
    for i, d in enumerate(ds):
        if d < CAND_FROM or i > qi - GAP_AFTER:
            continue
        z = Z[i]
        m = ok & np.isfinite(z)
        if m.sum() < len(FEATS) - 2:
            continue
        dist = float(np.sqrt(np.sum(w[m] * (z[m] - q[m]) ** 2) / w[m].sum() * len(FEATS)))
        age = qi - i
        sim = math.exp(-dist ** 2 / 2 / len(FEATS)) * 0.5 ** (age / HALF_LIFE)
        res.append((sim, dist, i))
    res.sort(reverse=True)
    pick = []
    for sim, dist, i in res:
        if all(abs(i - j) >= MIN_SEP for _, _, j in pick):
            pick.append((sim, dist, i))
        if len(pick) >= topk:
            break
    out = []
    ix = tab["show"]["idx_close"]
    for sim, dist, i in pick:
        after = {f"idx_{n}d": (round(ix[i + n] / ix[i] - 1, 4) if i + n < len(ds) and ix[i] else None) for n in (1, 3, 5)}
        out.append({"date": ds[i], "next_day": ds[i + 1] if i + 1 < len(ds) else None, "sim": round(sim, 4), "dist": round(dist, 3),
                    "vec": {k: tab["raw"][k][i] for k in FEATS}, "zt_n": tab["show"]["zt_n"][i], "dt_n": tab["show"]["dt_n"][i],
                    "lb2_n": tab["show"]["lb2_n"][i], "amt_e8": tab["show"]["amt_e8"][i], "after": after,
                    "next_zt_n": tab["show"]["zt_n"][i + 1] if i + 1 < len(ds) else None})
    return {"query": q_date, "query_vec": {k: tab["raw"][k][qi] for k in FEATS}, "query_show": {k: tab["show"][k][qi] for k in tab["show"]},
            "similar": out}


def prev_trade_day(tab, d):
    p = [x for x in tab["dates"] if x < d]
    return p[-1] if p else None


def build(chain_date):
    tab = market_table(until=chain_date)
    q = prev_trade_day(tab, chain_date)
    res = search(tab, q) if q else {}
    res.update(chain_date=chain_date, generated_by="scripts/dfcf/paper/similar_days.py", feats=FEATS, weights=W)
    return res


def load(chain_date):
    try:
        return json.loads((OUT / f"{chain_date}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _mentor_action(skill, day):
    """相似日的下一交易日(=对应"今天")导师怎么做; 无数据=None"""
    if not day:
        return None
    try:
        if skill in ("taoge", "lubenyuan", "qushitiange"):
            import up_ops_stats as U
            y, m = int(day[:4]), int(day[5:7])
            f = ROOT / "md" / f"{y}S{(m - 1) // 3 + 1}" / f"{day}.md"
            if not f.exists():
                return None
            r = U.parse_day(f.read_text(encoding="utf-8", errors="replace"), U.UPS[skill][0])
            if r is None:
                return None
            b = [o["code"] for o in r["ops"] if o["side"] == "买"]
            s = [o["code"] for o in r["ops"] if o["side"] == "卖"]
            return "md 今日操作: " + ("无" if not r["ops"] else f"买 {len(b)} 笔{('(' + ','.join(b[:3]) + ')') if b else ''} / 卖 {len(s)} 笔")
        import override_stats as O
        t = O.Truth().of(skill, day)
        if not t:
            return None
        import mimicry_score as ms
        R = ms.Real(skill)
        nm = lambda c: R.names.get(c) or c
        return (f"真人{'出手' if t['trade'] else '没动'}, 方向 {t['dir']}, 收盘总仓 {t['tp']:.0%}"
                + (f", 买 {'、'.join(nm(c) for c in sorted(t['buys'])[:4])}" if t["buys"] else ""))
    except Exception:   # noqa: BLE001
        return None


def text_block(skill, chain_date):
    d = load(chain_date)
    if not d or not d.get("similar"):
        return ""
    qv = d.get("query_vec") or {}
    qs = d.get("query_show") or {}
    pct = lambda x: "—" if x is None else f"{x * 100:+.1f}%"
    L = [f"- 相似市况(零 token 机械检索: 按 {d['query']} 收盘的市况向量, 从 2025-01 起找最像的 3 天, 近期加权; 只是历史参照, 不是预测): "
         f"昨日 上证 {pct(qv.get('idx1'))}/5日 {pct(qv.get('idx5'))}, 涨停 {qs.get('zt_n')} 跌停 {qs.get('dt_n')}, 炸板率 {pct(qv.get('zb_rate')).lstrip('+')}, "
         f"最高 {int(qv.get('max_lb') or 0)} 板, 2板+ {qs.get('lb2_n')} 家, 成交额 {qs.get('amt_e8'):.0f} 亿"]
    for s in d["similar"]:
        a = s["after"]
        act = _mentor_action(skill, s.get("next_day"))
        L.append(f"  - {s['date']}(相似度 {s['sim']:.2f}): 上证 {pct(s['vec'].get('idx1'))}, 涨停 {s['zt_n']} 跌停 {s['dt_n']}, 最高 {int(s['vec'].get('max_lb') or 0)} 板"
                 f" → 之后 上证 次日 {pct(a.get('idx_1d'))} / 3日 {pct(a.get('idx_3d'))} / 5日 {pct(a.get('idx_5d'))}, 次日涨停 {s.get('next_zt_n')}"
                 + (f"; 导师次日({s.get('next_day')}): {act}" if act else "; 导师当时无数据"))
    return "\n".join(L)


def selftest():
    fails = []

    def chk(n, c):
        print(("PASS " if c else "FAIL ") + n)
        if not c:
            fails.append(n)

    rng = np.random.default_rng(7)
    n = 300
    ds = [f"D{i:04d}" for i in range(n)]
    raw = {k: list(rng.normal(size=n)) for k in FEATS}
    for k in FEATS:   # 第 50 天 ≈ 最后一天(查询日), 第 280 天(太近, 在 GAP 内)也 ≈
        raw[k][50] = raw[k][n - 1] + 0.01
        raw[k][n - 3] = raw[k][n - 1]
    tab = {"dates": ds, "raw": raw, "show": {"zt_n": [50] * n, "dt_n": [5] * n, "lb2_n": [10] * n, "amt_e8": [10000] * n,
                                             "idx_close": list(3000 + np.cumsum(rng.normal(size=n)))}}
    global CAND_FROM, HALF_LIFE
    old, old_hl = CAND_FROM, HALF_LIFE
    CAND_FROM, HALF_LIFE = "D0000", 1e9
    try:
        r = search(tab, ds[-1])
        chk("最像的是第 50 天(无衰减)", r["similar"][0]["date"] == "D0050")
        HALF_LIFE = 5.0
        chk("强时间衰减下近期优先", search(tab, ds[-1])["similar"][0]["date"] > "D0200")
        HALF_LIFE = 1e9
        chk("GAP 内的近日不进候选", all(s["date"] < ds[n - GAP_AFTER] for s in r["similar"]))
        chk("相似日互相间隔 ≥3", all(abs(int(a["date"][1:]) - int(b["date"][1:])) >= MIN_SEP for a in r["similar"] for b in r["similar"] if a is not b))
        chk("之后 1/3/5 日有值", r["similar"][0]["after"]["idx_5d"] is not None)
        chk("返回 3 个", len(r["similar"]) == 3)
        raw2 = {k: list(v) for k, v in raw.items()}
        raw2["zt"][10] = None
        tab2 = dict(tab, raw=raw2)
        chk("缺值不炸", len(search(tab2, ds[-1])["similar"]) == 3)
    finally:
        CAND_FROM, HALF_LIFE = old, old_hl
    chk("无产物=空串", text_block("a658", "2099-01-01") == "")
    print("SELFTEST " + ("PASS" if not fails else f"FAIL {fails}"))
    return 0 if not fails else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--date", default=_date.today().isoformat())
    ap.add_argument("--skill", default="gaogailvfuli")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if a.build:
        d = build(a.date)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{a.date}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"similar_days → {OUT / (a.date + '.json')} 查询日 {d.get('query')}: " + ", ".join(f"{s['date']}({s['sim']:.2f})" for s in d.get("similar") or []))
    if a.show or a.build:
        print(text_block(a.skill, a.date))
        return
    ap.print_help()


if __name__ == "__main__":
    main()
