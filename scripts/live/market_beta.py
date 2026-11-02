# -*- coding: utf-8 -*-
"""每票跟大盘程度：1分钟收益相关，5/10/20窗口并列，避免冻结单一口径。零token。"""
import argparse
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"
INDICES = {"sh000852": "中证1000", "sz399006": "创业板", "sh000001": "上证"}


def series(D, codes):
    f = MKT / D / "kline_minute.jsonl"
    if not f.exists():
        return {}
    out = {c: [] for c in codes}
    with f.open(encoding="utf-8") as fh:
        for l in fh:
            r = json.loads(l)
            s = r.get("symbol")
            if s in out:
                out[s].append((r["barTime"], float(r["close"])))
    return {s: sorted(v) for s, v in out.items() if v}


def corr(a, b):
    xa, xb = dict(a), dict(b)
    ts = sorted(set(xa) & set(xb))
    if len(ts) < 20:
        return None, len(ts)
    ra = [xa[y] / xa[x] - 1 for x, y in zip(ts, ts[1:]) if xa[x] and xa[y]]
    rb = [xb[y] / xb[x] - 1 for x, y in zip(ts, ts[1:]) if xb[x] and xb[y]]
    if len(ra) != len(rb) or len(ra) < 20:
        return None, len(ts)
    try:
        return statistics.correlation(ra, rb), len(ra)
    except statistics.StatisticsError:
        return None, len(ra)


def evaluate(codes, day, windows=(5, 10, 20)):
    out = []
    for code in codes:
        sym = ("sh" if code.startswith(("6", "5", "11")) else "sz") + code
        rec = {"code": code, "date": day, "windows": {}}
        for w in windows:
            days = sorted(p.name for p in MKT.glob("20*") if p.name <= day and (p / "kline_minute.jsonl").exists())[-w:]
            vals, ns = {}, 0
            for ix, name in INDICES.items():
                rs = []
                for d in days:
                    ser = series(d, [sym, ix])
                    if sym in ser and ix in ser:
                        rs.append(corr(ser[sym], ser[ix]))
                good = [x[0] for x in rs if x[0] is not None]
                ns = sum(x[1] for x in rs)
                vals[name] = round(statistics.fmean(good), 4) if good else None
            rec["windows"][str(w)] = {"corr": vals, "n_returns": ns, "days": days}
        out.append(rec)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--codes", required=True)
    a = ap.parse_args()
    out = evaluate(a.codes.split(","), a.date)
    f = ROOT / "results" / "_live" / a.date / "market_beta.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
