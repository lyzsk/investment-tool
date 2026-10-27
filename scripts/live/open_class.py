# -*- coding: utf-8 -*-
"""open_class.py — 必查「开盘情境」(10/26 用户点评: 百洋股份这种"竞价跌停被抢上来"的水下票, 各线都按"水上冲高卖"在开盘第一波就卖, 卖错了; 零 token, 只读)

情境(按 09:25 竞价路径, auction_live_open.json): 竞价一直跌停 / 竞价跌停被抢上来(抬 <5 点 / ≥5 点)/ 水上高开 ≥3% / 水上平高开 0~3% / 水下低开 0~−3% / 水下低开 <−3%(非跌停)
统计(全市场盘口池里的票, 过去有竞价 + 分钟数据的日子, 不含当天): 当天最高 / 收盘相对开盘价、10 点前最低最高、最高出现在 10 点前的比例
build(D)     → results/_live/open_class_stats.json(每晚 check md 跑; 只用 D 之前的日子)
item(code, D) → 必查一行: 本票今天属于哪类 + 这类的当天分布 + 卖法提示(用户 10/26: 水下被抢上来的票要等走弱确认再卖、分仓前少后多)
"""
import collections
import glob
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"
OUT = ROOT / "results" / "_live" / "open_class_stats.json"
TIPS = {
    "竞价跌停被抢上来": "水下被抢上来 ≠ 水上冲高: 统计上当天最高多在 10 点后出现、收盘中位高于开盘 → 不在开盘第一波就砸; 等走弱确认(冲高回落破均价 / 二封跌停)再卖, 分仓前少后多(用户 10/26 点评)",
    "竞价一直跌停": "跌停开: 看开板后急拉还是慢拉、有没有二封(U5); 二封 = 弱, 反抽就走",
    "水上高开≥3%": "水上高开: 最高多在 10 点前(冲高卖的典型场景), 收盘分布两头宽",
    "水上平高开0~3%": "水上平高开: 最高多在 10 点前, 收盘中位低于开盘 → 冲高分批卖",
}


def klass(v, lim):
    p1, op = v["p1"]["pct"], v["fin"]["pct"]
    if p1 <= -(lim - 0.3) and op > -(lim - 0.3):
        return "竞价跌停被抢上来" + ("(抬≥5点)" if op - p1 >= 5 else "(抬<5点)")
    if p1 <= -(lim - 0.3):
        return "竞价一直跌停"
    if op >= 3:
        return "水上高开≥3%"
    if op >= 0:
        return "水上平高开0~3%"
    if op >= -3:
        return "水下低开0~-3%"
    return "水下低开<-3%(非跌停)"


def _lim(s):
    return 20 if s[2:4] == "30" else 10


def build(D=None):
    R = collections.defaultdict(list)
    days = []
    for f in sorted(glob.glob(str(MKT / "*" / "auction_live_open.json"))):
        d = Path(f).parent.name
        mf = Path(f).parent / "kline_minute.jsonl"
        if (D and d >= D) or not mf.exists():
            continue
        days.append(d)
        a = json.loads(Path(f).read_text(encoding="utf-8")).get("symbols") or {}
        want = {}
        for s, v in a.items():
            if s[2:4] not in ("60", "00", "30") or not isinstance(v.get("fin"), dict) or not v["fin"].get("px") or not isinstance(v.get("p1"), dict) or v["p1"].get("pct") is None:
                continue
            want[s] = (klass(v, _lim(s)), v["fin"]["px"], v["prev"], _lim(s))
        bars = collections.defaultdict(list)
        for l in open(mf, encoding="utf-8"):
            s = l[12:20]
            if s in want:
                x = json.loads(l)
                bars[s].append((x["barTime"][11:16], x["high"], x["low"], x["close"]))
        for s, (k, o, pc, lim) in want.items():
            b = sorted(bars.get(s) or [])
            if len(b) < 200:
                continue
            hi = max(x[1] for x in b)
            c = b[-1][3]
            t_hi = next(x[0] for x in b if x[1] == hi)
            b30 = [x for x in b if x[0] <= "10:00"]
            R[k].append([(hi / o - 1) * 100, (c / o - 1) * 100, (min(x[2] for x in b30) / o - 1) * 100, (max(x[1] for x in b30) / o - 1) * 100, t_hi <= "10:00"])

    def q(v, p):
        v = sorted(v)
        return round(v[min(len(v) - 1, int(len(v) * p))], 2)
    out = {"截至": D, "日子": days, "类": {}}
    for k, v in R.items():
        hi, c = [x[0] for x in v], [x[1] for x in v]
        out["类"][k] = {"n": len(v), "最高中位": round(st.median(hi), 2), "最高P25": q(hi, .25), "最高P75": q(hi, .75), "收盘中位": round(st.median(c), 2), "收盘P10": q(c, .1), "收盘P90": q(c, .9),
                       "收盘均值": round(st.mean(c), 2), "10点前最低中位": round(st.median([x[2] for x in v]), 2), "10点前最高中位": round(st.median([x[3] for x in v]), 2),
                       "最高在10点前": round(sum(x[4] for x in v) / len(v), 2)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


_S = {}


def item(code, D):
    f = MKT / D / "auction_live_open.json"
    if not f.exists():
        return None
    s = ("sh" if str(code).startswith(("6", "11", "5")) else "sz") + str(code)
    try:
        v = (json.loads(f.read_text(encoding="utf-8")).get("symbols") or {}).get(s)
    except ValueError:
        return None
    if not v or not isinstance(v.get("fin"), dict) or not v["fin"].get("px") or not isinstance(v.get("p1"), dict) or v["p1"].get("pct") is None:
        return None
    k = klass(v, _lim(s))
    if "st" not in _S:
        try:
            _S["st"] = json.loads(OUT.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _S["st"] = {}
    c = ((_S["st"] or {}).get("类") or {}).get(k)
    head = f"09:20 前 {v['p1']['pct']:+.2f}% → 开 {v['fin']['pct']:+.2f}% = 【{k}】"
    if not c:
        return head + "(这类没有统计)"
    tip = next((t for kk, t in TIPS.items() if k.startswith(kk)), "")
    return (head + f"; 这类过去 {len((_S['st'] or {}).get('日子') or [])} 天 n={c['n']}: 当天最高(相对开盘)中位 {c['最高中位']:+.2f}%(P25 {c['最高P25']:+.2f} / P75 {c['最高P75']:+.2f}), "
            f"收盘中位 {c['收盘中位']:+.2f}%(P10 {c['收盘P10']:+.2f} / P90 {c['收盘P90']:+.2f}), 10 点前最低中位 {c['10点前最低中位']:+.2f}%, 最高出现在 10 点前 {c['最高在10点前']:.0%}"
            + (f"; 提示: {tip}" if tip else ""))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import datetime as dt
    D = sys.argv[1] if len(sys.argv) > 1 else dt.date.today().isoformat()
    o = build(None if "--all" in sys.argv else None)
    for k, c in sorted(o["类"].items()):
        print(k, c)
