# review_cb_daily.py — 不吃土豆0 执行质量复盘(日线 OHLC × 他的腿, 零 token, 2026-10-02)
# 回答用户三问: 他卖飞了吗? 逃早了吗? 有没有更优操作?
# 口径(日线粒度局限, 已在输出中标注):
#   卖分位 = (卖价-当日低)/(当日高-当日低) — <0.5=卖在当日下半区(卖飞风险)
#   卖飞上限 = 当日高/卖价-1 — OHLC 不知高点在卖前还是卖后; 但他 88% 卖在 09:30-35, 高点大概率在卖后, 强指示
#   持有至收盘增量 = 收盘/卖价-1 — 正=卖飞/负=逃对(逃早也是对的)
#   买滑点 = 买价/当日开-1 — 竞价买入应≈0; 死窗/追单的追价成本
# 用法: scripts/venv/Scripts/python.exe scripts/review_cb_daily.py [--json out.json]
import json, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # investment-tool/(10/2 迁入 scripts/tzzb/)
TZZB = ROOT / "downloads" / "tzzb" / "buchitudou0"
KDIR = ROOT / "downloads" / "quotes" / "cb" / "kline"

legs, seen = [], set()
for f in TZZB.glob("change_bs_*.json"):
    for t in json.load(open(f, encoding="utf-8"))["ex_data"]["change_list"]:
        k = (t["trans_date"], t["op"], t["stock_code"])
        if k in seen: continue
        seen.add(k); legs.append(t)

kl = {}
for f in KDIR.glob("*.json"):
    kl[f.stem] = json.load(open(f, encoding="utf-8"))

byday = defaultdict(list)
for t in legs: byday[t["trans_date"][:10]].append(t)

trips, no_kl = [], 0
for d, ts in byday.items():
    ts.sort(key=lambda x: x["trans_date"])
    q = defaultdict(list)
    for t in ts:
        if t["op"] == "1": q[t["stock_code"]].append(t)
        elif q[t["stock_code"]]:
            b = q[t["stock_code"]].pop(0)
            k = kl.get(t["stock_code"], {}).get(d)
            if not k or k["h"] <= k["l"]:
                no_kl += 1; continue
            bp, sp = float(b["trans_price"]), float(t["trans_price"])
            trips.append({
                "day": d, "code": t["stock_code"], "name": t["stock_name"],
                "bt": b["trans_date"][11:], "st": t["trans_date"][11:], "bp": bp, "sp": sp,
                "pct": sp / bp - 1,
                "amt": float(b.get("trans_amount") or 0),
                "买滑点%": round((bp / k["o"] - 1) * 100, 2),
                "买分位": round((bp - k["l"]) / (k["h"] - k["l"]), 2),
                "卖分位": round((sp - k["l"]) / (k["h"] - k["l"]), 2),
                "卖飞上限%": round((k["h"] / sp - 1) * 100, 2),
                "持收增量%": round((k["c"] / sp - 1) * 100, 2),
                "日涨跌%": round((k["c"] / k["o"] - 1) * 100, 2),
            })

def agg(xs, key): return round(sum(x[key] for x in xs) / max(1, len(xs)), 2)

def day_compare(trips, kl):
    """(日×标的)名义加权: 他当日实际收益 vs 同标的开盘买入躺到收盘"""
    g = defaultdict(list)
    for t in trips:
        g[(t["day"], t["code"])].append(t)
    his_list, base_list = [], []
    for (d, code), ts in g.items():
        k = kl.get(code, {}).get(d)
        if not k or not k["o"]:
            continue
        w = sum(t["amt"] for t in ts) or len(ts)
        his_list.append(sum(t["pct"] * (t["amt"] or 1) for t in ts) / w * 100)
        base_list.append((k["c"] / k["o"] - 1) * 100)
    n = len(his_list)
    return {
        "口径": "等权平均每个(日×标的): 他=名义加权收益, 基准=开盘躺到收盘",
        "他平均%": round(sum(his_list) / max(1, n), 2),
        "躺平基准%": round(sum(base_list) / max(1, n), 2),
        "跑赢基准": f"{sum(1 for h, b in zip(his_list, base_list) if h > b)}/{n}",
        "跑输>2%": sum(1 for h, b in zip(his_list, base_list) if b - h > 2),
        "跑赢>2%": sum(1 for h, b in zip(his_list, base_list) if h - b > 2),
    }

wins = [t for t in trips if t["pct"] >= 0]; losses = [t for t in trips if t["pct"] < 0]
# 双尾阈值口径(用户 10/2 立法: 不搞固定 topN, 用分布+阈值): 显著=|持收增量|≥5%, 深度=≥10%
bins = [(-999, -10), (-10, -5), (-5, -2), (-2, 0), (0, 2), (2, 5), (5, 10), (10, 999)]
dist = {f"{lo:+d}~{hi:+d}": sum(1 for t in trips if lo <= t["持收增量%"] < hi) for lo, hi in bins}
fly5 = sorted([t for t in trips if t["持收增量%"] >= 5], key=lambda x: -x["持收增量%"])
esc5 = sorted([t for t in trips if t["持收增量%"] <= -5], key=lambda x: x["持收增量%"])
R = {
    "样本": {"有kline的round_trip": len(trips), "缺kline跳过": no_kl},
    "全体": {"平均卖分位": agg(trips, "卖分位"), "平均买分位": agg(trips, "买分位"),
            "平均卖飞上限%": agg(trips, "卖飞上限%"), "平均持收增量%": agg(trips, "持收增量%"),
            "卖分位<0.3占比": f"{sum(1 for t in trips if t['卖分位'] < 0.3)}/{len(trips)}",
            "持收增量>0(拿住更赚)占比": f"{sum(1 for t in trips if t['持收增量%'] > 0)}/{len(trips)}"},
    "盈利单": {"平均卖分位": agg(wins, "卖分位"), "平均持收增量%": agg(wins, "持收增量%")},
    "亏损单": {"平均持收增量%": agg(losses, "持收增量%"), "持收后更差(止损正确)占比": f"{sum(1 for t in losses if t['持收增量%'] < 0)}/{len(losses)}"},
    "买通道滑点": {
        "09:25竞价买 平均滑点%": agg([t for t in trips if t["bt"] == "09:25:00"], "买滑点%"),
        "09:30:00死窗买 平均滑点%": agg([t for t in trips if t["bt"] == "09:30:00"], "买滑点%"),
        "追单(>09:30:10) 平均滑点%": agg([t for t in trips if t["bt"] > "09:30:10"], "买滑点%"),
    },
    "持收增量分布": dist,
    "显著卖飞(≥5%)": {"笔数": len(fly5), "深度(≥10%)全量": [t for t in fly5 if t["持收增量%"] >= 10]},
    "显著逃顶(≤-5%)": {"笔数": len(esc5), "深度(≤-10%)全量": [t for t in esc5 if t["持收增量%"] <= -10]},
    # 日度对照(更公允的"更优操作"基准, 2026-10-02): 趋势日他反复进出, 笔级卖飞会高估机会成本——
    # 按(日×标的)名义加权: 他实际收益 vs 开盘买入躺到收盘
    "日度对照": day_compare(trips, kl),
}
if "--json" in sys.argv:
    Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps({"summary": R, "trips": trips}, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(R, ensure_ascii=False, indent=1))
