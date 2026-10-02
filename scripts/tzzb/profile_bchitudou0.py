# profile_bchitudou0.py — 不吃土豆0 机械统计画像 + 市况反向联动(零 token, 2026-10-02)
# 正向链: 900腿 → 统计事实(H1止损/H2时刻/H4熟票池 + 杂项)
# 反向链: stocks md 收评节(大盘情绪) + 涨停分析节(正股状态) × 他的行为 → H3正股联动/H5市况开关
# 口径: 与 gen_tzzb_md.mjs 相同(腿去重键 trans_date|op|stock_code, FIFO round-trip)
# 用法: scripts/venv/Scripts/python.exe scripts/profile_bchitudou0.py [--json out.json]
import json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # investment-tool/(10/2 迁入 scripts/tzzb/)
DIR = ROOT / "downloads" / "tzzb" / "bchitudou0"

# ---------- 载入腿(去重) + 净值 ----------
legs, seen = [], set()
for f in DIR.glob("change_bs_*.json"):
    for t in json.load(open(f, encoding="utf-8"))["ex_data"]["change_list"]:
        k = (t["trans_date"], t["op"], t["stock_code"])
        if k in seen: continue
        seen.add(k); legs.append(t)
nav = {}
nl = json.load(open(DIR / "nav_daily.json", encoding="utf-8"))["ex_data"]["index_list"]
for i, x in enumerate(nl):
    d = f"{x['date'][:4]}-{x['date'][4:6]}-{x['date'][6:]}"
    nav[d] = float(x["index"]) / float(nl[i - 1]["index"]) - 1 if i else None

# ---------- FIFO round-trip ----------
byday = defaultdict(list)
for t in legs: byday[t["trans_date"][:10]].append(t)
trips = []
for d, ts in byday.items():
    ts.sort(key=lambda x: x["trans_date"])
    openq = defaultdict(list)
    for t in ts:
        if t["op"] == "1": openq[t["stock_code"]].append(t)
        else:
            b = openq[t["stock_code"]].pop(0) if openq[t["stock_code"]] else None
            if b:
                trips.append({"day": d, "code": t["stock_code"], "name": t["stock_name"],
                              "bp": float(b["trans_price"]), "sp": float(t["trans_price"]),
                              "bt": b["trans_date"][11:], "st": t["trans_date"][11:],
                              "amt": float(b["trans_amount"]),
                              "hold": (int(t["trans_date"][11:13]) * 3600 + int(t["trans_date"][14:16]) * 60 + int(t["trans_date"][17:19])) -
                                      (int(b["trans_date"][11:13]) * 3600 + int(b["trans_date"][14:16]) * 60 + int(b["trans_date"][17:19]))})
for tr in trips: tr["pct"] = tr["sp"] / tr["bp"] - 1

R = {}  # 结果集
R["总量"] = {"腿": len(legs), "round_trip": len(trips), "出手日": len(byday), "标的": len({t["stock_code"] for t in legs})}

# ---------- H1 止损型: 亏损单幅度/持仓 vs 盈利单 ----------
losers = [t for t in trips if t["pct"] < 0]; winners = [t for t in trips if t["pct"] >= 0]
def hist(xs, bins):
    return {f"{lo}~{hi}": sum(1 for x in xs if lo <= x * 100 < hi) for lo, hi in bins}
R["H1"] = {
    "胜率": f"{len(winners)}/{len(trips)} = {len(winners)/len(trips):.1%}",
    "亏损单幅度分布%": hist([t["pct"] for t in losers], [(-0.2, 0), (-0.5, -0.2), (-1, -0.5), (-2, -1), (-99, -2)]),
    "最大单笔亏损%": round(min(t["pct"] for t in trips) * 100, 2),
    "亏损单平均持仓秒": round(sum(t["hold"] for t in losers) / max(1, len(losers)), 1),
    "盈利单平均持仓秒": round(sum(t["hold"] for t in winners) / max(1, len(winners)), 1),
    "平均盈利%": round(sum(t["pct"] for t in winners) / max(1, len(winners)) * 100, 3),
    "平均亏损%": round(sum(t["pct"] for t in losers) / max(1, len(losers)) * 100, 3),
    "亏损单持仓≤10秒占比": f"{sum(1 for t in losers if t['hold'] <= 10)}/{len(losers)}",
}

# ---------- H2 尾盘型: 买卖时刻分布 ----------
def tmin(ts): return int(ts[:2]) * 60 + int(ts[3:5])
R["H2"] = {
    "买腿<09:35占比": f"{sum(1 for t in legs if t['op']=='1' and tmin(t['trans_date'][11:]) < 575)}/{sum(1 for t in legs if t['op']=='1')}",
    "买腿≥14:30占比": f"{sum(1 for t in legs if t['op']=='1' and tmin(t['trans_date'][11:]) >= 870)}/{sum(1 for t in legs if t['op']=='1')}",
    "卖腿≥14:30占比": f"{sum(1 for t in legs if t['op']=='2' and tmin(t['trans_date'][11:]) >= 870)}/{sum(1 for t in legs if t['op']=='2')}",
}

# ---------- H4 熟票池: 标的频次 ----------
freq = Counter(t["stock_code"] for t in legs)
dayfreq = Counter()
for d, ts in byday.items():
    for c in {t["stock_code"] for t in ts}: dayfreq[c] += 1
top = freq.most_common(10)
R["H4"] = {
    "腿数top5": [(c, n, f"{n/len(legs):.0%}") for c, n in top[:5]],
    "top1/top3/top5腿占比": f"{top[0][1]/len(legs):.0%}/{sum(n for _, n in top[:3])/len(legs):.0%}/{sum(n for _, n in top[:5])/len(legs):.0%}",
    "重复交易≥5日的标的": sum(1 for _, n in dayfreq.items() if n >= 5),
    "只做过1日的标的": sum(1 for _, n in dayfreq.items() if n == 1),
}

# ---------- 杂项: 单笔名义 / 竞价通道 / 连亏收手 ----------
amts = [t["amt"] for t in trips]
ch = Counter()
for d, ts in byday.items():
    bs = sorted([t for t in ts if t["op"] == "1"], key=lambda x: x["trans_date"])
    if bs: ch[bs[0]["trans_date"][11:19] if bs[0]["trans_date"][11:19] in ("09:25:00", "09:30:00") else ("<09:31" if bs[0]["trans_date"][11:] < "09:31" else ">=09:31")] += 1
R["杂项"] = {
    "单笔名义中位/最小/最大万": [round(sorted(amts)[len(amts)//2]/1e4, 1), round(min(amts)/1e4, 1), round(max(amts)/1e4, 1)],
    "每日首买通道分布": dict(ch),
    "平均每日round_trip": round(len(trips) / len(byday), 1),
}

# ---------- 反向链: md 市况联动 ----------
def md_of(day):
    y, m = day[:4], int(day[5:7])
    return ROOT / "stocks" / f"{y}S{(m + 2) // 3}" / f"{day}.md"
def parse_mkt(day):
    """收评节机械解析: (涨停, 跌停, 上涨家数, 成交额万亿); 无节返回 None"""
    p = md_of(day)
    if not p.exists(): return None
    c = p.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"上涨\s*(\d+)\s*家\s*/\s*下跌\s*(\d+)\s*家；涨停\s*(\d+)\s*家\s*/\s*跌停\s*(\d+)\s*家；两市成交额\s*([\d.]+)\s*万亿", c)
    return {"up": int(m[1]), "down": int(m[2]), "zt": int(m[3]), "dt": int(m[4]), "vol": float(m[5])} if m else None
def bond_prefix(name):
    return re.sub(r"^(Z|ST|\*ST)", "", name).split("转")[0]  # 再22转债→再22, 百达转2→百达, Z睿创转→睿创
def find_stock_in_zt(day, prefix):
    """当日 md 涨停分析节里按名称前缀找正股 → (股票名, 涨跌幅%, 板块) 或 None"""
    p = md_of(day)
    if not p.exists() or len(prefix) < 2: return None
    c = p.read_text(encoding="utf-8", errors="ignore")
    sec = re.search(r"## 涨停分析\n(.*)$", c, re.S)
    if not sec: return None
    cur_board = None
    for line in sec[1].split("\n"):
        mb = re.match(r"### (.+)", line)
        if mb: cur_board = mb[1].strip()
        ms = re.match(r"\|\s*(\S+?)\s*<br>\s*(\d{6})\s*\|[^|]*\|[^|]*?([\d.]+)%", line)
        if ms and (prefix[:2] in ms[1] or ms[1][:2] in prefix):
            return (ms[1], float(ms[3]), cur_board)
    return None

mkt_days = {d: parse_mkt(d) for d in nav}
mkt_days = {d: m for d, m in mkt_days.items() if m}
flat_days = [d for d in nav if d not in byday]  # 空仓日(nav有, 腿无)
R["市况覆盖"] = {"有收评md的日": len(mkt_days), "最早": min(mkt_days) if mkt_days else None,
              "空仓日总数": len(flat_days), "窗口内空仓日": sorted(d for d in flat_days if d in mkt_days)}

# H5: 空仓日 vs 出手日 市况对比(同窗口)
act = [mkt_days[d] for d in byday if d in mkt_days]
flt = [mkt_days[d] for d in flat_days if d in mkt_days]
def avg(xs, k): return round(sum(x[k] for x in xs) / max(1, len(xs)), 1)
R["H5"] = {
    "窗口": f"{min(mkt_days)}~{max(mkt_days)}" if mkt_days else "无",
    "出手日(n)": len(act), "空仓日(n)": len(flt),
    "出手日 平均涨停/跌停/成交额": [avg(act, "zt"), avg(act, "dt"), avg(act, "vol")],
    "空仓日 平均涨停/跌停/成交额": [avg(flt, "zt"), avg(flt, "dt"), avg(flt, "vol")],
}

# H3: 出手日所买债的正股 vs 涨停分析节(T-1因果链 + 当日结果链; 名称前缀匹配=推测级)
nav_days = sorted(nav)
prev_of = {nav_days[i]: nav_days[i - 1] for i in range(1, len(nav_days))}
def taoge_mentions(day, prefix):
    """T-1 md 桃哥复盘节是否提及该债/正股(叙事层软证据, 非统计事实环)"""
    p = md_of(day)
    if not p.exists(): return False
    c = p.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"#### 股市\s*-\s*桃哥复盘\n(.*?)(?=\n#{2,4} |\Z)", c, re.S)
    return bool(m and prefix[:2] in m[1])
h3 = []
for d in sorted(byday):
    for c in {t["stock_code"] for t in byday[d]}:
        name = next(t["stock_name"] for t in byday[d] if t["stock_code"] == c)
        px = bond_prefix(name)
        t0 = find_stock_in_zt(d, px) if d in mkt_days else None
        t1d = prev_of.get(d)
        t1 = find_stock_in_zt(t1d, px) if t1d else None
        tg = taoge_mentions(t1d, px) if t1d else False
        if t0 or t1 or tg:
            h3.append((d, name, f"T-1涨停分析:{t1}" if t1 else "T-1涨停分析:无",
                       f"当日:{t0}" if t0 else "当日:无", "桃哥节提及" if tg else ""))
R["H3"] = {
    "口径": "T-1(因果): 昨日涨停分析/桃哥复盘 → 今日选债; 当日(结果): 收盘涨停分析",
    "有联动信号的(日×标的)": len(h3),
    "明细": h3,
}

if "--json" in sys.argv:
    Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(R, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(json.dumps(R, ensure_ascii=False, indent=2, default=str))
