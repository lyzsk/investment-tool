# -*- coding: utf-8 -*-
"""mentor_recent.py — 导师近 T−n 日持仓 / 操作过的票 → 必查 / 候选池 / 3 秒盘口(10/24 用户提: 不只 T−1, 断板续板的票导师会回头做)

口径(零 token, 每天算一次落盘 results/_live/<D>/mentor_recent.json):
  ①导师按"当时结算"(用户: 和开盘选人一个道理): T−k 那天的持仓 / 操作算不算, 看 T−k 收盘后选人是否入选(mentor_select.select(T−k 的下一个交易日), 门槛同 mentor_select)
  ②n 按导师自己的数据定(不拍脑袋): 导师上次操作某票后多少个交易日再买回 / 再操作同一只(同花顺逐笔腿, 近 250 个交易日)
     P50 内 → 必查(一半的回头操作发生在这之内); P80 内 → 候选池(04 只能从候选池选, 不进池导师式回头买就不可能); P90 内 → 3 秒盘口(零 token)
     样本 < MIN_N 笔用全体导师合并分位; 上限 KMAX 个交易日(持仓快照 10/13 前不全, 更早只认逐笔)
  ③T−1 收盘持仓 + T−1 操作过的 → 必查(k = 1)
  还在持有的票每天都在快照里 → k = 1; 这里多出来的主要是"最近几天卖掉 / 清仓"的票
用法: python mentor_recent.py D   → 打印各导师 n、三层各几只
"""
import datetime as dt
import json
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(Path(__file__).resolve().parent), str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "lib")]
MIN_N, KMAX, HIST = 15, 20, 250
TIERS = (("must", 0.5), ("pool", 0.8), ("book", 0.9))
_C = {}


def _cur():
    import manual_backfill as mb
    return mb.db().cursor()


def tdays(D, n):
    c = _cur()
    c.execute("select distinct trade_date from investment_market.kline_day where symbol='sh000001' and trade_date < %s and is_deleted=0 order by trade_date desc limit %s", (D, n))
    return [str(x[0]) for x in c.fetchall()][::-1]


def _q(v, p):
    v = sorted(v)
    return v[int(p * (len(v) - 1))] if v else None


def lag_stats(D):
    """各导师"再操作同一只票"的间隔分位(交易日) → {导师: {n, must, pool, book}}, "_all" = 全体合并"""
    days = tdays(D, HIST)
    ix = {d: i for i, d in enumerate(days)}
    c = _cur()
    c.execute("select ledger, stock_code, date(record_time), side from investment_tool.tzzb_record where record_type='bs_leg' and is_deleted=0 and record_time >= %s and record_time < %s",
              (days[0], D))
    ev = {}
    for led, code, d, side in c.fetchall():
        d = str(d)
        if d in ix and code:
            ev.setdefault(led, {}).setdefault(code, set()).add((ix[d], "买" in str(side)))
    lags, allg = {}, []
    for led, m in ev.items():
        for code, s in m.items():
            ds = sorted({d for d, _ in s})
            buys = {d for d, b in s if b}
            for a, b in zip(ds, ds[1:]):
                if b in buys:   # 回头"买": 加仓 / 买回(只卖不算回头做)
                    lags.setdefault(led, []).append(b - a)
                    allg.append(b - a)
    out = {"_all": {"n": len(allg), **{t: min(KMAX, _q(allg, p) or 1) for t, p in TIERS}}}
    for led, v in lags.items():
        src = v if len(v) >= MIN_N else allg
        out[led] = {"n": len(v), "pooled": len(v) < MIN_N, **{t: min(KMAX, _q(src, p) or 1) for t, p in TIERS}}
    return out


def qualified(day_after):
    """day_after 开盘时(用它之前的数据)入选的导师"""
    if day_after not in _C:
        import mentor_select as MS
        _C[day_after] = {x["id"] for x in MS.select(day_after)["ranked"] if x["role"] == "入选"}
    return _C[day_after]


def build(D):
    """→ {"stats": 分位, "codes": OrderedDict{代码: {"k", "tier", "tags": [...]}}}; tier 取各来源里最高的一层(must > pool > book)"""
    st = lag_stats(D)
    kmax = max([v["book"] for v in st.values()] + [1])
    days = tdays(D, kmax + 1)   # days[-1] = T−1
    nxt = days[1:] + [D]   # T−k 的下一个交易日(选人"当时结算"用)
    c = _cur()
    rank = {"must": 0, "pool": 1, "book": 2}
    out = OrderedDict()
    for k in range(1, min(kmax, len(days)) + 1):
        d, d_after = days[-k], nxt[-k]
        q = qualified(d_after)
        if not q:
            continue
        ph = ",".join(["%s"] * len(q))
        c.execute("select ledger, stock_code, stock_name, side from investment_tool.tzzb_record where record_type='bs_leg' and is_deleted=0 and date(record_time)=%s "
                  f"and ledger in ({ph})", (d, *q))
        rows = [(led, code, nm, "买" if "买" in str(sd) else "卖") for led, code, nm, sd in c.fetchall()]
        # 收盘持仓快照: 当晚(或周末)拉的那份 = T−k 收盘; 取 T−k 当天到下一个交易日之前最晚一份
        c.execute("select ledger, max(record_time) from investment_tool.tzzb_record where record_type='position_snap' and is_deleted=0 and record_time >= %s and record_time < %s "
                  f"and ledger in ({ph}) group by ledger", (d, d_after, *q))
        for led, ts in c.fetchall():
            c.execute("select stock_code, stock_name from investment_tool.tzzb_record where record_type='position_snap' and is_deleted=0 and ledger=%s and record_time=%s", (led, ts))
            rows += [(led, code, nm, "持") for code, nm in c.fetchall()]
        for led, code, nm, how in rows:
            code = str(code or "")
            if len(code) != 6 or not code.isdigit():
                continue
            s = st.get(led) or st["_all"]
            tier = next((t for t, _ in TIERS if k <= s[t]), None) if k > 1 else "must"
            if tier is None:
                continue
            e = out.setdefault(code, {"k": k, "tier": tier, "name": nm or "", "tags": []})
            e["k"] = min(e["k"], k)
            if rank[tier] < rank[e["tier"]]:
                e["tier"] = tier
            tag = f"导师T-{k} {led} {how}"
            if tag not in e["tags"] and len(e["tags"]) < 6:
                e["tags"].append(tag)
    out = OrderedDict(sorted(out.items(), key=lambda kv: (rank[kv[1]["tier"]], kv[1]["k"], -len(kv[1]["tags"]))))
    return {"D": D, "stats": st, "codes": out}


def load(D):
    """一天算一次: results/_live/<D>/mentor_recent.json(今天及以后落盘; 回放日子只缓存进程内)"""
    key = ("mr", D)
    if key in _C:
        return _C[key]
    f = ROOT / "results" / "_live" / D / "mentor_recent.json"
    r = None
    if f.exists():
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
            r["codes"] = OrderedDict(r["codes"])
        except (OSError, ValueError, KeyError):
            r = None
    if r is None:
        r = build(D)
        if D >= dt.date.today().isoformat():
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    _C[key] = r
    return r


def codes(D, tier):
    """tier 这一层及以上的票(must ⊂ pool ⊂ book) → OrderedDict{代码: 标签串}"""
    lv = {"must": 0, "pool": 1, "book": 2}[tier]
    rank = {"must": 0, "pool": 1, "book": 2}
    return OrderedDict((c, "; ".join(e["tags"])) for c, e in load(D)["codes"].items() if rank[e["tier"]] <= lv)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    D = sys.argv[1] if len(sys.argv) > 1 else dt.date.today().isoformat()
    r = build(D)
    print("各导师回头操作间隔分位(交易日; P50 → 必查 / P80 → 候选池 / P90 → 3 秒盘口):")
    for led, v in sorted(r["stats"].items(), key=lambda kv: -kv[1]["n"]):
        print(f"  {led:24s} 样本 {v['n']:4d}{'(不足, 用全体)' if v.get('pooled') else ''}  必查 ≤T-{v['must']}  候选池 ≤T-{v['pool']}  盘口 ≤T-{v['book']}")
    from collections import Counter
    print("三层只数:", dict(Counter(e["tier"] for e in r["codes"].values())))
    for c_, e in list(r["codes"].items())[:40]:
        print(f"  {c_} {e['name']:<8} {e['tier']:<5} T-{e['k']:<2} {' | '.join(e['tags'])[:120]}")
