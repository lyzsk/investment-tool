# gen_tzzb_review.py — tzzb 选手执行质量复盘·泛化版(2026-10-07, 泛化自 review_cb_daily.py K3 原作)
# 回答: 他卖飞了吗? 逃早了吗? 买贵了吗? 跑赢躺平基准了吗?
# 与 cb 版差异: ①kline 源=downloads/quotes/daily/<code>.json(多源日线, klines 数组格式)
#   ②跨日 trip 同口径参与(卖日收盘对照仍成立); 港股/北交所缺 kline 跳过计数
# 口径(日线粒度, 输出内标注): 卖分位/卖飞上限/持收增量/买滑点/双尾(≥5%)/日度对照(他 vs 开盘躺平)
# 用法: python scripts/tzzb/gen_tzzb_review.py --ledger lnq [--json out.json] | --all
import json, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGERS = {l["ledger"]: l["name"] for l in json.loads((ROOT / "scripts/tzzb/tzzb_ledgers.json").read_text(encoding="utf-8"))}
KDAILY = ROOT / "downloads" / "quotes" / "daily"

def load_kdaily():
    """日线统一载入 → {code: {date: {o,h,l,c}}}: ①daily 归档(五人, kline.mjs 多源)
    ②cb kline(土豆转债, {date: {o,h,l,c}} 原生 dict 格式)——两源合并不覆盖"""
    out = {}
    if KDAILY.exists():
        for f in KDAILY.glob("*.json"):
            try:
                arr = json.loads(f.read_text(encoding="utf-8"))["klines"]
                out[f.stem] = {x["d"]: {"o": x["o"], "h": x["h"], "l": x["l"], "c": x["c"]} for x in arr}
            except Exception: pass
    for f in (ROOT / "downloads" / "quotes" / "cb" / "kline").glob("*.json"):
        if f.stem in out: continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out[f.stem] = {k: {"o": v["o"], "h": v["h"], "l": v["l"], "c": v["c"]} for k, v in d.items()}
        except Exception: pass
    return out

KL = load_kdaily()
PREV = {}  # (code, date) -> 前收; 供"日涨跌%"列(10/7 为 gen_tzzb_cases 换源补)
for _code, _dd in KL.items():
    _ds = sorted(_dd)
    for _i in range(1, len(_ds)):
        PREV[(_code, _ds[_i])] = _dd[_ds[_i - 1]]["c"]

def build(ledger):
    TZZB = ROOT / "downloads" / "tzzb" / ledger
    legs, seen = [], set()
    for f in TZZB.glob("change_bs_*.json"):
        for t in json.load(open(f, encoding="utf-8"))["ex_data"]["change_list"]:
            k = (t["trans_date"], t["op"], t["stock_code"])
            if k in seen: continue
            seen.add(k); legs.append(t)
    byday = defaultdict(list)
    for t in legs: byday[t["trans_date"][:10]].append(t)

    # 跨日 FIFO(gen_tzzb_md 同款): 卖腿配跨日买腿
    trips, no_kl = [], 0
    openq = defaultdict(list)
    for d in sorted(byday):
        for t in sorted(byday[d], key=lambda x: x["trans_date"]):
            if t["op"] == "1": openq[t["stock_code"]].append((t, d)); continue
            if not openq[t["stock_code"]]: continue
            b, bd = openq[t["stock_code"]].pop(0)
            k = KL.get(t["stock_code"], {}).get(d)   # 用卖出日 OHLC
            if not k or k["h"] <= k["l"]: no_kl += 1; continue
            bp, sp = float(b["trans_price"]), float(t["trans_price"])
            trips.append({
                "day": d, "buy_day": bd, "code": t["stock_code"], "name": t["stock_name"],
                "cross": d != bd, "bt": b["trans_date"][11:], "st": t["trans_date"][11:], "bp": bp, "sp": sp,
                "pct": sp / bp - 1, "amt": float(b.get("trans_amount") or 0),
                "买滑点%": round((bp / k["o"] - 1) * 100, 2),
                "卖分位": round((sp - k["l"]) / (k["h"] - k["l"]), 2),
                "卖飞上限%": round((k["h"] / sp - 1) * 100, 2),
                "持收增量%": round((k["c"] / sp - 1) * 100, 2),
                "日涨跌%": (lambda pc: round((k["c"] / pc - 1) * 100, 2) if pc else None)(PREV.get((t["stock_code"], d))),
            })

    def agg(xs, key): return round(sum(x[key] for x in xs) / max(1, len(xs)), 2) if xs else None
    intraday = [t for t in trips if not t["cross"]]
    crossday = [t for t in trips if t["cross"]]
    wins = [t for t in trips if t["pct"] >= 0]; losses = [t for t in trips if t["pct"] < 0]
    bins = [(-999, -10), (-10, -5), (-5, -2), (-2, 0), (0, 2), (2, 5), (5, 10), (10, 999)]
    dist = {f"{lo:+d}~{hi:+d}": sum(1 for t in trips if lo <= t["持收增量%"] < hi) for lo, hi in bins}
    fly = sorted([t for t in trips if t["持收增量%"] >= 5], key=lambda x: -x["持收增量%"])
    esc = sorted([t for t in trips if t["持收增量%"] <= -5], key=lambda x: x["持收增量%"])
    # 日度对照: (卖日×标的) 他 vs 开盘躺平
    g = defaultdict(list)
    for t in trips: g[(t["day"], t["code"])].append(t)
    his, base = [], []
    for (d, code), ts in g.items():
        k = KL.get(code, {}).get(d)
        if not k or not k["o"]: continue
        w = sum(t["amt"] for t in ts) or len(ts)
        his.append(sum(t["pct"] * (t["amt"] or 1) for t in ts) / w * 100)
        base.append((k["c"] / k["o"] - 1) * 100)
    R = {
        "ledger": ledger, "name": LEDGERS.get(ledger),
        "样本": {"有日线trip": len(trips), "缺日线跳过(港股/北交所/未归档)": no_kl, "日内": len(intraday), "跨日": len(crossday)},
        "全体": {"平均卖分位": agg(trips, "卖分位"), "平均卖飞上限%": agg(trips, "卖飞上限%"),
                "平均持收增量%": agg(trips, "持收增量%"), "持收增量>0(拿住更赚)占比": f"{sum(1 for t in trips if t['持收增量%'] > 0)}/{len(trips)}" if trips else None},
        "日内trip": {"平均卖分位": agg(intraday, "卖分位"), "平均持收增量%": agg(intraday, "持收增量%")},
        "跨日trip": {"平均持收增量%": agg(crossday, "持收增量%"),
                "跨日卖对(持收更差=卖对)占比": f"{sum(1 for t in crossday if t['持收增量%'] < 0)}/{len(crossday)}" if crossday else None},
        "亏损单": {"持收后更差(止损正确)占比": f"{sum(1 for t in losses if t['持收增量%'] < 0)}/{len(losses)}" if losses else None},
        "买通道滑点": {"09:25-09:30(竞价/死窗) 平均%": agg([t for t in trips if t["bt"] <= "09:30:00"], "买滑点%"),
                "盘中(>09:31) 平均%": agg([t for t in trips if t["bt"] > "09:31:00"], "买滑点%")},
        "持收增量分布": dist,
        "显著卖飞(≥5%)": {"笔数": len(fly), "深度(≥10%)前5": fly[:5]},
        "显著逃顶(≤-5%)": {"笔数": len(esc), "深度(≤-10%)前5": esc[:5]},
        "日度对照": {"口径": "等权(日×标的): 他名义加权 vs 开盘躺平", "他平均%": round(sum(his)/max(1,len(his)), 2) if his else None,
                "躺平基准%": round(sum(base)/max(1,len(base)), 2) if base else None,
                "跑赢": f"{sum(1 for h,b in zip(his,base) if h>b)}/{len(his)}" if his else None},
    }
    return R, trips

if __name__ == "__main__":
    if "--all" in sys.argv:
        out = {}
        for lg in LEDGERS:
            R, trips = build(lg)
            out[lg] = {"summary": R, "trips_sample": trips[:20]}
            print(f"== {R['name']} == trip={R['样本']}", file=sys.stderr)
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    else:
        i = sys.argv.index("--ledger"); lg = sys.argv[i+1]
        if lg not in LEDGERS: sys.exit(f"未知 ledger {lg}")
        R, trips = build(lg)
        if "--json" in sys.argv:
            Path(sys.argv[sys.argv.index("--json")+1]).write_text(json.dumps({"summary": R, "trips": trips}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(R, ensure_ascii=False, indent=1, default=str))
