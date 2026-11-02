# -*- coding: utf-8 -*-
"""导师×时间节点/市况：买入日可见条件下的平仓收益全分布，零token。"""
import argparse
import bisect
import datetime as dt
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "lib"), str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "tzzb")]
import manual_backfill as mb  # noqa: E402
import mentors as M  # noqa: E402
from regime_trades import FEE_RT  # noqa: E402


def dist(xs):
    if not xs:
        return None
    xs = sorted(xs)
    q = lambda p: xs[int(p * (len(xs) - 1))]  # noqa: E731
    return {"n": len(xs), "win": round(sum(x > 0 for x in xs) / len(xs), 4), "mean": round(st.mean(xs), 4),
            "median": round(st.median(xs), 4), "p10": round(q(.1), 4), "p90": round(q(.9), 4),
            "best": round(xs[-1], 4), "worst": round(xs[0], 4)}


def mood(day):
    f = ROOT / "downloads" / "market" / day / "mood.jsonl"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8").splitlines()[-1])
    except (ValueError, IndexError):
        return {}


def conditions(cur, cal, amounts, all_days, closes):
    i = cal.index(cur)
    idx = cal[:i + 1]
    out = []
    if cur[5:7] in ("01", "04", "08", "10"):
        out.append("季报披露期")
    if len([d for d in all_days if d[:7] == cur[:7] and d >= cur]) <= 5:
        out.append("月末季末")
    if i >= 2 and all(closes[cal[j]] < closes[cal[j - 1]] for j in range(i - 1, i + 1)):
        out.append("大盘连阴≥3")
    m = mood(cur)
    if float(m.get("fall") or 0) >= 4000:
        out.append("普跌日")
    if float(m.get("avg") or 0) > 0 and float(m.get("rise") or 0) > float(m.get("fall") or 0):
        out.append("修复日")
    themes = defaultdict(int)
    for x in m.get("up") or []:
        if len(x) > 3:
            for th in str(x[3] or "").split("+"):
                themes[th] += 1
    if themes and max(themes.values()) >= 20:
        out.append("主线明确日")
    prev = [amounts[d] for d in cal[max(0, i - 20):i]]
    if prev and amounts[cur] <= sorted(prev)[max(0, int(.2 * (len(prev) - 1)))]:
        out.append("缩量地量日")
    return out or ["常规日"]


def run(ids, day):
    cur = mb.db().cursor()
    cur.execute("use investment_market")
    cur.execute("select trade_date,close,amount from kline_day where symbol='sh000001' and trade_date<=%s order by trade_date", (day,))
    rows = cur.fetchall()
    cal = [str(x[0]) for x in rows]
    amounts = {str(d): float(a or 0) for d, _, a in rows}
    closes = {str(d): float(c) for d, c, _ in rows}
    cond = {d: conditions(d, cal, amounts, cal, closes) for d in cal}
    out = {}
    for skill in ids:
        f = ROOT / "skills" / f"{skill}-skill" / "persona" / "cases_auto.jsonl"
        if not f.exists():
            continue
        by = defaultdict(list)
        for l in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(l)
            except ValueError:
                continue
            res = r.get("result") or {}
            if r.get("side") != "卖" or res.get("pnl") is None or r.get("date", "") > day:
                continue
            i = bisect.bisect_left(cal, r["date"])
            if i >= len(cal) or cal[i] != r["date"]:
                i = bisect.bisect_right(cal, r["date"]) - 1
            buy_i = i - int(res.get("hold_days") or 0) - 1
            if buy_i < 0:
                continue
            pnl = float(res["pnl"]) - FEE_RT(str(r.get("code")))
            for c in cond[cal[buy_i]]:
                by[c].append(pnl)
            by["全部"].append(pnl)
        out[skill] = {k: dist(v) for k, v in by.items()}
    return {"date": day, "mentors": out, "definition": "买入日前一交易日可见条件；平仓pnl扣近似成本；全分布"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--ledgers", default="")
    a = ap.parse_args()
    ids = a.ledgers.split(",") if a.ledgers else M.ids("tzzb")
    out = run(ids, a.date)
    f = ROOT / "downloads" / "tzzb" / "mentor_regime.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    L = [f"# 导师×时间节点/市况（{a.date}）", "", "> 买入日前一交易日可见条件；mean/median/P10/P90/best/worst均为平仓收益(扣近似成本)。", ""]
    for sk, rows in out["mentors"].items():
        L.append(f"## {M.get(sk)['name']}")
        for k, v in sorted(rows.items(), key=lambda x: x[0]):
            if v:
                L.append(f"- {k}: n={v['n']} 胜{v['win']:.0%} 均{v['mean']:+.2%} 中{v['median']:+.2%} P10 {v['p10']:+.2%} P90 {v['p90']:+.2%} 最好{v['best']:+.2%} 最差{v['worst']:+.2%}")
    md = ROOT / "docs" / "research" / "mentor_regime.md"
    md.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"→ {f} / {md}")
