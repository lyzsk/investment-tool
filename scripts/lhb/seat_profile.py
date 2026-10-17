# -*- coding: utf-8 -*-
"""seat_profile.py — 龙虎榜游资席位画像(零 token 统计; 2026-10-15 建)
输入(只读, 零请求): downloads/lhb/(fetch_lhb 落盘 json, lhb_lib 读) + 行情库 kline_day(只读; 北交所/转债缺的用 downloads/quotes/daily 补)
     + downloads/lhb/_industry/industry_em.json(东财行业快照, fetch_industry.py 一次性抓)
口径:
  买入事件 = 某席位出现在某票主记录(当日口径优先)的买五, 且该席位净额 > 0; 同票同日只算一次
  基准价 = 上榜日 T 收盘(游资多在 T 日盘中/尾盘买, 实际成本未知; 打板票 T 收盘≈买入价)
  T+1 开盘溢价 = T+1 开盘 / T+1 昨收 - 1; T+1 收盘溢价 = T+1 收盘 / T+1 昨收 - 1(昨收=交易所除权参考价, 除权日不失真)
  T+1 收红 = T+1 收盘溢价 > 0; T+3 收益 = 连乘 T+1..T+3 的 收盘/昨收 - 1
  T 之后 15 个自然日内没有下一根 K 线(长停牌)= 不计收益; 样本末尾几天没有 T+1/T+3 自然不计
  同类超额 = 事件的 T+1 收盘溢价 - 全部上榜只次中同类(T 日涨停/非涨停)的 T+1 收盘溢价均值(打板票次日天然溢价高, 不扣会把"爱打板"误当"有本事")
  可见快卖率 = 买入事件中, 该席位在 T+1 或 T+2 又以净卖出出现在同票龙虎榜的比例(只看得到上榜的那部分, 是下界)
  常做板块 = 买入事件里上榜股票的东财行业(当前行业快照, 非历史时点)前 3
  小样本 = 买入事件 < 5
  分组: 拉萨天团(youzi.json 别名=拉萨天团 的 5 个东财拉萨席位) / 机构(机构专用·机构投资者) / 北向(深股通·沪股通)——组内同票同日合并成一个事件, 组净额 > 0 才算买入
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/lhb/seat_profile.py
产物: scripts/lhb/seat_profile.json(全部席位) ; 报告 md 由 render_seat_md.py 生成
"""
import datetime as dt
import json
import statistics as stx
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lhb"))
import lhb_lib as L  # noqa: E402

OUT = ROOT / "scripts" / "lhb" / "seat_profile.json"
MIN_N = 5


def limit_pct(code, market, name, date=None):
    """10/17 健壮性 M11: 改走统一规则模块 a_rules(按日期); 原规则 ST 一律 5%(创业板 ST 应 20%、主板 ST 2026-07-06 起 10%)。返回百分数"""
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "lib"))
        import a_rules as AR   # noqa: PLC0415
        p = AR.limit_pct(code, date, name=name or None)
        return 99.0 if p is None else round(p * 100, 2)
    except Exception:   # noqa: BLE001  规则模块不可用 → 旧口径
        pass
    if "ST" in (name or "").upper():
        return 5.0
    if code.startswith(("30", "68")):
        return 20.0
    if code.startswith(("92", "8", "4")) or "北京" in (market or ""):
        return 30.0
    return 10.0


def main():
    ind = json.loads((ROOT / "downloads" / "lhb" / "_industry" / "industry_em.json").read_text(encoding="utf-8"))["map"]
    days = list(L.iter_days())
    dates = [d for d, _ in days]
    didx = {d: i for i, d in enumerate(dates)}
    # 每席位的 (date, code) 净卖记录, 用于快卖率
    seat_sells = defaultdict(set)
    seat_meta = {}
    events = defaultdict(list)          # key -> [event]
    groups = {"拉萨天团": defaultdict(list), "机构": defaultdict(list), "北向": defaultdict(list)}
    all_stockdays = []
    symbols = set()
    for d, stocks in days:
        for s in stocks:
            symbols.add(s["symbol"])
            p = s["prim"]
            sd = {"date": d, "code": s["code"], "symbol": s["symbol"], "name": s["name"], "market": s["market"],
                  "chg": p.get("CHANGE_RATE"), "board": (ind.get(s["code"]) or {}).get("board"), "multi": L.is_three_day(p)}
            all_stockdays.append(sd)
            gsum = defaultdict(lambda: [0.0, False])
            for x in s["seats"]:
                k = x["key"]
                m = seat_meta.setdefault(k, {"dept_code": x["dept_code"], "names": Counter(), "last_name": x["name"], "last_date": d, "appear": 0})
                m["names"][x["name"]] += 1
                m["appear"] += 1
                if d >= m["last_date"]:
                    m["last_name"], m["last_date"] = x["name"], d
                if x["net"] < 0:
                    seat_sells[k].add((d, s["code"]))
                if x["in_buy5"] and x["net"] > 0:
                    events[k].append({**sd, "net": x["net"], "both": x["in_sell5"]})
                g = "机构" if x["is_jg"] else "北向" if x["is_bx"] else None
                if g is None and L.YOUZI.get(x["short"]) == "拉萨天团":
                    g = "拉萨天团"
                if g:
                    gsum[g][0] += x["net"]
                    gsum[g][1] |= x["in_buy5"]
            for g, (net, inb) in gsum.items():
                if inb and net > 0:
                    groups[g][(d, s["code"])].append({**sd, "net": net, "both": False})
    print(f"交易日 {len(dates)}, 上榜只次 {len(all_stockdays)}, 席位 {len(seat_meta)}, 有买入事件的席位 {len(events)}", flush=True)

    K = L.kline_map(symbols, since="2025-01-01")
    kidx = {sym: {r[0]: i for i, r in enumerate(rows)} for sym, rows in K.items()}
    print(f"K 线覆盖 {len(K)}/{len(symbols)} 只", flush=True)

    ret_cache = {}

    def rets(sym, d):
        key = (sym, d)
        if key in ret_cache:
            return ret_cache[key]
        r = None
        rows = K.get(sym)
        i = kidx.get(sym, {}).get(d)
        if rows and i is not None and i + 1 < len(rows):
            n1 = rows[i + 1]
            if (dt.date.fromisoformat(n1[0]) - dt.date.fromisoformat(d)).days <= 15:
                def pc(j):
                    return rows[j][3] if rows[j][3] else rows[j - 1][2]
                o1 = n1[1] / pc(i + 1) - 1
                c1 = n1[2] / pc(i + 1) - 1
                c3 = None
                if i + 3 < len(rows):
                    c3 = 1.0
                    for j in (i + 1, i + 2, i + 3):
                        c3 *= rows[j][2] / pc(j)
                    c3 -= 1
                r = (o1, c1, c3)
        ret_cache[key] = r
        return r

    def is_lim(e):
        return e["chg"] is not None and e["chg"] >= limit_pct(e["code"], e["market"], e["name"], e.get("date")) - 0.25

    # 同类基准: 全部上榜只次按"T 日是否涨停"分两桶的 T+1 收盘溢价均值(超额=事件 c1 - 同桶均值; 去掉"打板票次日天然高开"的混杂)
    bucket = {True: [], False: []}
    for e in all_stockdays:
        r = rets(e["symbol"], e["date"])
        if r:
            bucket[is_lim(e)].append(r[1])
    bmean = {k: stx.mean(v) for k, v in bucket.items()}

    def summarize(evs, sells=None):
        o1, c1, c3, red = [], [], [], 0
        exc = []
        quick = 0
        for e in evs:
            r = rets(e["symbol"], e["date"])
            if r:
                o1.append(r[0])
                c1.append(r[1])
                red += r[1] > 0
                exc.append(r[1] - bmean[is_lim(e)])
                if r[2] is not None:
                    c3.append(r[2])
            if sells is not None:
                i = didx[e["date"]]
                if any((dates[j], e["code"]) in sells for j in (i + 1, i + 2) if j < len(dates)):
                    quick += 1
        n = len(evs)
        boards = Counter(e["board"] for e in evs if e["board"])
        lim = sum(1 for e in evs if is_lim(e))
        gem = sum(1 for e in evs if e["code"].startswith(("30", "68")))
        bj = sum(1 for e in evs if e["code"].startswith(("92", "8", "4")))
        pct = lambda a: round(100 * stx.mean(a), 2) if a else None
        med = lambda a: round(100 * stx.median(a), 2) if a else None
        return {
            "buy_n": n, "n_ret1": len(c1), "n_ret3": len(c3),
            "o1_mean": pct(o1), "o1_median": med(o1), "c1_mean": pct(c1), "c1_median": med(c1),
            "red1_rate": round(100 * red / len(c1), 1) if c1 else None, "c3_mean": pct(c3), "c3_median": med(c3), "c1_excess_mean": pct(exc),
            "avg_net_buy_wan": round(stx.mean(e.get("net", 0) for e in evs) / 1e4, 0) if evs else None,
            "limitup_rate": round(100 * lim / n, 1) if n else None,
            "gem_star_share": round(100 * gem / n, 1) if n else None, "bj_share": round(100 * bj / n, 1) if n else None,
            "multi_day_share": round(100 * sum(e["multi"] for e in evs) / n, 1) if n else None,
            "both_side_share": round(100 * sum(bool(e.get("both")) for e in evs) / n, 1) if n else None,
            "quick_sell_rate": round(100 * quick / n, 1) if (n and sells is not None) else None,
            "top_boards": [[b, c] for b, c in boards.most_common(3)],
            "first": min(e["date"] for e in evs) if evs else None, "last": max(e["date"] for e in evs) if evs else None,
            "small_sample": n < MIN_N,
        }

    seats = []
    for k, m in seat_meta.items():
        evs = events.get(k, [])
        name = m["last_name"]
        rec = {"key": k, "dept_code": m["dept_code"], "name": name, "short": L.seat_short(name),
               "names_all": [n for n, _ in m["names"].most_common()], "alias": L.alias_of(m["names"]),
               "kind": "机构" if L.RE_JG.match(name) else "北向" if L.RE_BX.match(name) else ("占位码" if k.startswith("N:") else "营业部"),
               "appear_n": m["appear"], "sell_n": len(seat_sells.get(k, ()))}
        rec.update(summarize(evs, seat_sells.get(k, set())))
        seats.append(rec)
    seats.sort(key=lambda r: (-r["buy_n"], -r["appear_n"]))

    grp = {}
    for g, evmap in groups.items():
        evs = [v[0] for v in evmap.values()]
        grp[g] = summarize(evs)
    # 知名游资别名(非拉萨): 按别名合并席位事件(同票同日去重)
    alias_ev = defaultdict(dict)
    for r in seats:
        if r["alias"] and r["alias"] != "拉萨天团":
            for e in events.get(r["key"], []):
                alias_ev[r["alias"]].setdefault((e["date"], e["code"]), e)
    aliases = {a: {**summarize(list(m.values())), "seats": [r["short"] for r in seats if r["alias"] == a]} for a, m in alias_ev.items()}
    base_all = summarize(all_stockdays)            # 全部上榜只次(不论谁买)
    base_lim = summarize([e for e in all_stockdays if is_lim(e)])
    base_nolim = summarize([e for e in all_stockdays if not is_lim(e)])
    pooled = {}
    for k, evs in events.items():
        if not k.startswith("N:"):
            for e in evs:
                pooled.setdefault((e["date"], e["code"]), e)
    base_seat = summarize(list(pooled.values()))   # 有营业部净买入的上榜只次

    out = {"generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "range": [dates[0], dates[-1]], "trading_days": len(dates),
           "stock_days": len(all_stockdays), "seat_count": len(seats), "seats_with_buy": sum(1 for r in seats if r["buy_n"]),
           "seats_ge5": sum(1 for r in seats if r["buy_n"] >= MIN_N), "kline_coverage": [len(K), len(symbols)],
           "definitions": __doc__.split("口径:")[1].split("用法:")[0].strip(),
           "baseline": {"全部上榜只次": base_all, "其中T日涨停": base_lim, "其中T日非涨停": base_nolim, "有营业部净买入的只次": base_seat}, "groups": grp, "aliases": aliases, "seats": seats}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"写 {OUT.relative_to(ROOT)}: 席位 {len(seats)}, 有买入 {out['seats_with_buy']}, ≥{MIN_N} 次 {out['seats_ge5']}")
    for g, v in grp.items():
        print(g, v["buy_n"], v["c1_mean"], v["red1_rate"])
    print("baseline", base_all["c1_mean"], base_all["red1_rate"], "| seat-pooled", base_seat["c1_mean"], base_seat["red1_rate"])


if __name__ == "__main__":
    main()
