# gen_tzzb_profile.py — 投资账本选手机械统计画像·统一入口(2026-10-06 合并版)
# 合并自: profile_buchitudou0.py(K3 原作, 转债分支逻辑原样函数化) + profile_stocks.py(五人股票分支)。
# 对齐 gen_ 家族(gen_tzzb_md/gen_scorecard/gen_taoge_ic/gen_tzzb_cases)。
# 分支路由: --ledger buchitudou0 = 土豆转债分支(全日内 FIFO+正股联动+桃哥联动+五闸门原料)
#           --ledger <五人>     = 股票分支(隔夜三桶+市场分布+撞票矩阵)
# 共享层: 载腿去重 / nav 载入 —— 两分支各自的 FIFO 因口径不同分开实现(转债全日内 vs 股票跨日三桶)。
# 用法: python scripts/tzzb/gen_tzzb_profile.py --ledger buchitudou0 [--json out.json]
#       python scripts/tzzb/gen_tzzb_profile.py --all   # 全六人+撞票矩阵
import json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGERS = json.loads((ROOT / "scripts/tzzb/tzzb_ledgers.json").read_text(encoding="utf-8"))
NAME_OF = {l["ledger"]: l["name"] for l in LEDGERS}

# ============ 共享层 ============
def load_legs(ledger):
    """载腿(去重键 trans_date|op|stock_code)"""
    d = ROOT / "downloads/tzzb" / ledger
    legs, seen = [], set()
    for f in d.glob("change_bs_*.json"):
        for t in json.loads(f.read_text(encoding="utf-8"))["ex_data"]["change_list"]:
            k = (t["trans_date"], t["op"], t["stock_code"])
            if k in seen: continue
            seen.add(k); legs.append(t)
    return legs

def load_nav(ledger):
    """净值日序列 → {date: 日收益率}"""
    nav = {}
    nl = json.loads((ROOT / "downloads/tzzb" / ledger / "nav_daily.json").read_text(encoding="utf-8"))["ex_data"]["index_list"]
    for i, x in enumerate(nl):
        d = f"{x['date'][:4]}-{x['date'][4:6]}-{x['date'][6:]}"
        nav[d] = float(x["index"]) / float(nl[i - 1]["index"]) - 1 if i else None
    return nav

# ============ 土豆转债分支(K3 原逻辑函数化, 语义未动) ============
def profile_tudou():
    import datetime  # 原脚本同款
    legs = load_legs("buchitudou0")
    nav = load_nav("buchitudou0")

    # ---------- FIFO round-trip(全日内; 土豆 T+0 无隔夜) ----------
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

    R = {}
    R["总量"] = {"腿": len(legs), "round_trip": len(trips), "出手日": len(byday), "标的": len({t["stock_code"] for t in legs})}

    # H1 止损型
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

    # H2 时刻分布
    def tmin(ts): return int(ts[:2]) * 60 + int(ts[3:5])
    R["H2"] = {
        "买腿<09:35占比": f"{sum(1 for t in legs if t['op']=='1' and tmin(t['trans_date'][11:]) < 575)}/{sum(1 for t in legs if t['op']=='1')}",
        "买腿≥14:30占比": f"{sum(1 for t in legs if t['op']=='1' and tmin(t['trans_date'][11:]) >= 870)}/{sum(1 for t in legs if t['op']=='1')}",
        "卖腿≥14:30占比": f"{sum(1 for t in legs if t['op']=='2' and tmin(t['trans_date'][11:]) >= 870)}/{sum(1 for t in legs if t['op']=='2')}",
    }

    # H4 熟票池
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

    # 杂项
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

    # ---------- 反向链: md 市况联动(转债特有) ----------
    def md_of(day):
        y, m = day[:4], int(day[5:7])
        return ROOT / "md" / f"{y}S{(m + 2) // 3}" / f"{day}.md"
    def parse_mkt(day):
        p = md_of(day)
        if not p.exists(): return None
        c = p.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"上涨\s*(\d+)\s*家\s*/\s*下跌\s*(\d+)\s*家；涨停\s*(\d+)\s*家\s*/\s*跌停\s*(\d+)\s*家；两市成交额\s*([\d.]+)\s*万亿", c)
        return {"up": int(m[1]), "down": int(m[2]), "zt": int(m[3]), "dt": int(m[4]), "vol": float(m[5])} if m else None
    def bond_prefix(name):
        return re.sub(r"^(Z|ST|\*ST)", "", name).split("转")[0]
    def find_stock_in_zt(day, prefix):
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

    mkt_days = {d: m for d, m in ((d, parse_mkt(d)) for d in nav) if m}
    flat_days = [d for d in nav if d not in byday]
    R["市况覆盖"] = {"有收评md的日": len(mkt_days), "最早": min(mkt_days) if mkt_days else None,
                  "空仓日总数": len(flat_days), "窗口内空仓日": sorted(d for d in flat_days if d in mkt_days)}

    act = [mkt_days[d] for d in byday if d in mkt_days]
    flt = [mkt_days[d] for d in flat_days if d in mkt_days]
    def avg(xs, k): return round(sum(x[k] for x in xs) / max(1, len(xs)), 1)
    R["H5"] = {
        "窗口": f"{min(mkt_days)}~{max(mkt_days)}" if mkt_days else "无",
        "出手日(n)": len(act), "空仓日(n)": len(flt),
        "出手日 平均涨停/跌停/成交额": [avg(act, "zt"), avg(act, "dt"), avg(act, "vol")],
        "空仓日 平均涨停/跌停/成交额": [avg(flt, "zt"), avg(flt, "dt"), avg(flt, "vol")],
    }

    nav_days = sorted(nav)
    prev_of = {nav_days[i]: nav_days[i - 1] for i in range(1, len(nav_days))}
    def taoge_mentions(day, prefix):
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
    R["H3"] = {"口径": "T-1(因果): 昨日涨停分析/桃哥复盘 → 今日选债; 当日(结果): 收盘涨停分析",
               "有联动信号的(日×标的)": len(h3), "明细": h3}
    return R

# ============ 五人股票分支(原 profile_stocks.py) ============
def market(code):
    if re.fullmatch(r"0\d{4}", code): return "港股"
    if re.fullmatch(r"(92\d{3}|[48]\d{5})", code): return "北交所"
    if re.fullmatch(r"1[13]\d{4}", code): return "转债"
    return "A股"

def exit_days(d, bd):
    return max(1, round((__import__("datetime").date.fromisoformat(d) - __import__("datetime").date.fromisoformat(bd)).days))

def profile_stocks_fn(ledger):
    import datetime
    name = NAME_OF[ledger]
    legs, nav = load_legs(ledger), load_nav(ledger)
    byday = defaultdict(list)
    for t in legs: byday[t["trans_date"][:10]].append(t)
    trips, openq = [], defaultdict(list)
    for d in sorted(byday):
        for t in sorted(byday[d], key=lambda x: x["trans_date"]):
            if t["op"] == "1": openq[t["stock_code"]].append((t, d))
            elif openq[t["stock_code"]]:
                b, bd = openq[t["stock_code"]].pop(0)
                sec = lambda x: int(x[11:13])*3600 + int(x[14:16])*60 + int(x[17:19])
                trips.append({"day": bd, "exit": d, "code": t["stock_code"], "name": t["stock_name"],
                    "mkt": market(t["stock_code"]), "bp": float(b["trans_price"]), "sp": float(t["trans_price"]),
                    "bt": b["trans_date"][11:], "st": t["trans_date"][11:],
                    "amt": float(b["trans_amount"]), "pct": float(t["trans_price"])/float(b["trans_price"]) - 1,
                    "hold_s": max(0, (sec(t["trans_date"]) - sec(b["trans_date"])) if d == bd
                             else (86400 - sec(b["trans_date"])) + sec(t["trans_date"]) + 86400*(exit_days(d, bd)-1)),
                    "bucket": "日内" if d == bd else ("隔夜" if exit_days(d, bd) == 1 else "多日")})
    R = {"ledger": ledger, "name": name, "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        "窗口": f"{min(byday)}~{max(byday)}",
        "总量": {"腿": len(legs), "round_trip": len(trips), "出手日": len(byday),
               "空仓日": sum(1 for d in nav if d not in byday), "标的": len({t["stock_code"] for t in legs}),
               "市场分布": dict(Counter(market(t["stock_code"]) for t in legs))}}
    for bk in ("日内", "隔夜", "多日"):
        xs = [t for t in trips if t["bucket"] == bk]
        if not xs: R[f"桶_{bk}"] = {"笔数": 0}; continue
        w = [t for t in xs if t["pct"] >= 0]
        holds = sorted(t["hold_s"] for t in xs)
        R[f"桶_{bk}"] = {"笔数": len(xs), "胜率": f"{len(w)}/{len(xs)}={len(w)/len(xs):.0%}",
            "平均盈利%": round(sum(t["pct"] for t in w)/max(1, len(w))*100, 2),
            "平均亏损%": round(sum(t["pct"] for t in xs if t["pct"] < 0)/max(1, len(xs)-len(w))*100, 2),
            "中位持仓": f"{holds[len(holds)//2]}s", "最大单亏%": round(min(t["pct"] for t in xs)*100, 2)}
    losers = [t for t in trips if t["pct"] < 0]
    R["H1_亏损应对"] = {"亏损笔": len(losers),
        "亏损当日即出占比": f"{sum(1 for t in losers if t['bucket'] == '日内')}/{len(losers)}",
        "亏损隔夜扛占比": f"{sum(1 for t in losers if t['bucket'] != '日内')}/{len(losers)}",
        "最大单日亏%(净值口径)": round(min(v for v in nav.values() if v is not None)*100, 2)}
    tmin = lambda ts: int(ts[:2])*60 + int(ts[3:5])
    buys = [t for t in legs if t["op"] == "1"]
    def first_buy(d):
        ts = sorted(byday[d], key=lambda y: y["trans_date"])
        return next((t["trans_date"][11:] for t in ts if t["op"] == "1"), None)
    fb = [x for x in (first_buy(d) for d in byday) if x]
    R["H2_时刻"] = {"首买通道": dict(Counter(
        "竞价09:25" if x == "09:25:00" else "开盘<09:31" if x < "09:31" else "盘中≥09:31" for x in fb)),
        "买腿<10:00占比": f"{sum(1 for t in buys if tmin(t['trans_date'][11:]) < 600)}/{len(buys)}",
        "买腿≥14:30": sum(1 for t in buys if tmin(t['trans_date'][11:]) >= 870)}
    freq = Counter(t["stock_code"] for t in legs)
    dayfreq = Counter()
    for d, ts in byday.items():
        for c in {t["stock_code"] for t in ts}: dayfreq[c] += 1
    top = freq.most_common(8)
    R["H4_熟票池"] = {"腿数top5": [(c, n, f"{n/len(legs):.0%}") for c, n in top[:5]],
        "重复≥5日标的": sum(1 for _, n in dayfreq.items() if n >= 5), "只做过1日标的": sum(1 for _, n in dayfreq.items() if n == 1)}
    amts = [t["amt"] for t in trips]
    R["杂项"] = {"单笔名义中位/万": round(sorted(amts)[len(amts)//2]/1e4, 1) if amts else None,
        "平均每日trip": round(len(trips)/len(byday), 1)}
    # 持仓维度(day_positions 真实百分比, 10/7 §H-3①: 持仓周期/仓位节奏矿脉)
    dp_file = ROOT / "downloads" / "tzzb" / ledger / "day_positions.json"
    if dp_file.exists():
        dp = json.loads(dp_file.read_text(encoding="utf-8"))
        days_p = sorted(dp.keys())
        sumpct, nholds, nrepo, holds_days = [], 0, 0, 0
        first_last = {}
        for d8 in days_p:
            lst = dp[d8].get("list") or []
            holds = [x for x in lst if not re.match(r"^(204|1318)", x.get("code", "")) and float(x.get("position_percent") or 0) > 0]
            nholds += len(holds)
            nrepo += sum(1 for x in lst if re.match(r"^(204|1318)", x.get("code", "")))
            if holds:
                holds_days += 1
                sumpct.append(sum(float(x["position_percent"]) for x in holds))
            for x in holds:
                c = x.get("code")
                if c not in first_last: first_last[c] = [d8, d8]
                first_last[c][1] = d8
        R["持仓维度"] = {
            "覆盖日": len(days_p),
            "平均持仓只数": round(nholds / max(1, holds_days), 1),
            "平均总仓位%": round(100 * sum(sumpct) / max(1, len(sumpct)), 1) if sumpct else None,
            "满仓日(≥90%)占比": f"{sum(1 for x in sumpct if x >= 0.9)}/{len(sumpct)}" if sumpct else None,
            "轻仓日(≤30%)占比": f"{sum(1 for x in sumpct if x <= 0.3)}/{len(sumpct)}" if sumpct else None,
            "逆回购日数": nrepo,
            "持仓票只数": len(first_last),
            "最长持有票(首末日)": sorted(first_last.items(), key=lambda kv: kv[1][1])[-3:] if first_last else [],
        }
    return R

# ============ 撞票矩阵(跨全六人) ============
def cross_matrix():
    hold = {}
    for lg in NAME_OF:
        d = ROOT / "downloads/tzzb" / lg
        if not d.exists(): continue
        s = set()
        for f in d.glob("change_bs_*.json"):
            for t in json.loads(f.read_text(encoding="utf-8"))["ex_data"]["change_list"]:
                s.add((t["trans_date"][:10], t["stock_code"]))
        hold[lg] = s
    pairs, detail = Counter(), defaultdict(list)
    lgs = list(hold)
    for i in range(len(lgs)):
        for j in range(i + 1, len(lgs)):
            for k in hold[lgs[i]] & hold[lgs[j]]:
                pairs[(lgs[i], lgs[j])] += 1
                if len(detail[(lgs[i], lgs[j])]) < 30: detail[(lgs[i], lgs[j])].append(k)
    return {"撞票对": {f"{a}×{b}": n for (a, b), n in pairs.most_common()},
            "明细top": {f"{a}×{b}": v for (a, b), v in sorted(detail.items(), key=lambda x: -pairs.get(x[0], 0))[:5]}}

# ============ main ============
def build(ledger):
    return profile_tudou() if ledger == "buchitudou0" else profile_stocks_fn(ledger)

if __name__ == "__main__":
    if "--all" in sys.argv:
        out = {lg: build(lg) for lg in NAME_OF}
        out["撞票矩阵"] = cross_matrix()
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    else:
        i = sys.argv.index("--ledger"); lg = sys.argv[i + 1]
        if lg not in NAME_OF: sys.exit(f"未知 ledger {lg}(可选: {'/'.join(NAME_OF)})")
        R = build(lg)
        if "--json" in sys.argv:
            Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(json.dumps(R, ensure_ascii=False, indent=1, default=str))
