# -*- coding: utf-8 -*-
"""hold_reconcile.py — 持股天数三种口径逐笔核对(零请求, 只读 downloads 下已抓文件; 10/17 agent③ 建)

起因: 候选"暗里着火" candidates_screen 报"持股 1~3 天", real_trade_sources 报"资金加权持仓段 138 天", 两个口径矛盾。
三种口径:
  ① 段中位(screen_candidates 口径): day_positions 每只票连续出现的天数, 每段一票, 取中位——小仓快进快出的段和底仓长拿的段同权
  ② 资金加权段长(real_trade_sources 口径): 同样的段, 每段按 Σ收盘持仓% 加权(钱实际拿多久)
  ③ 逐笔 FIFO(本脚本新增, 真值): change_bs 逐笔买卖腿按数量 FIFO 配对, 每一手的持有天数; 给笔数中位 / 金额加权均值 / 未平仓
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/hold_reconcile.py [--dir downloads/tzzb_cand/cand_anlizhuohuo ...] [--json out.json]
      (缺省=downloads/tzzb_cand/ 下全部候选)  --selftest
"""
import argparse, json, statistics as st, sys
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP = ("204", "1318")   # 逆回购


def load_legs(d):
    legs = []
    for f in sorted(Path(d).glob("change_bs_*_p*.json")):
        try:
            L = json.loads(f.read_text(encoding="utf-8")).get("ex_data", {}).get("change_list") or []
        except (OSError, ValueError, AttributeError):
            continue
        for x in L:
            code = str(x.get("stock_code") or "")
            if not code or code.startswith(SKIP):
                continue
            try:
                q = float(x.get("trans_count") or 0); amt = float(x.get("trans_amount") or 0); px = float(x.get("trans_price") or 0)
            except ValueError:
                continue
            if q <= 0:
                continue
            legs.append({"code": code, "name": x.get("stock_name"), "t": str(x.get("trans_date")), "side": str(x.get("op")), "q": q, "amt": amt or q * px})
    seen, out = set(), []
    for l in sorted(legs, key=lambda z: (z["t"], z["side"])):   # 同秒先买后卖
        k = (l["code"], l["t"], l["side"], l["q"], round(l["amt"], 2))
        if k not in seen:
            seen.add(k); out.append(l)
    return out


def _d(t):
    return datetime.strptime(t[:10], "%Y-%m-%d")


def fifo(legs, end_date=None):
    """返回 lots: 每个已配对/未平仓数量块 {code,q,amt,days,open}"""
    book, lots = defaultdict(deque), []
    for l in legs:
        if l["side"] == "1":
            book[l["code"]].append([l["q"], l["amt"] / l["q"], l["t"]])
        elif l["side"] == "2":
            q = l["q"]
            while q > 1e-9 and book[l["code"]]:
                lot = book[l["code"]][0]
                m = min(q, lot[0])
                lots.append({"code": l["code"], "q": m, "amt": m * lot[1], "days": (_d(l["t"]) - _d(lot[2])).days, "open": False, "buy": lot[2][:10], "sell": l["t"][:10]})
                lot[0] -= m; q -= m
                if lot[0] <= 1e-9:
                    book[l["code"]].popleft()
            # q>0 剩余=建仓腿在抓取窗口之前(底仓), 无法配对 → 不计
    end = _d(end_date) if end_date else (max(_d(l["t"]) for l in legs) if legs else None)
    for code, dq in book.items():
        for q, px, t in dq:
            lots.append({"code": code, "q": q, "amt": q * px, "days": (end - _d(t)).days, "open": True, "buy": t[:10], "sell": None})
    return lots


def dp_runs(d):
    try:
        dp = json.loads((Path(d) / "day_positions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    runs, cur = [], {}
    for day in sorted(dp):
        ps = {str(p.get("code")): float(p.get("position_percent") or 0) for p in (dp[day] or {}).get("list") or []
              if float(p.get("position_percent") or 0) > 0.02 and not str(p.get("code", "")).startswith(SKIP)}
        for c in list(cur):
            if c not in ps:
                runs.append({"code": c, **cur.pop(c), "open": False})
        for c, w in ps.items():
            r = cur.setdefault(c, {"days": 0, "w": 0.0, "start": day})
            r["days"] += 1; r["w"] += w
    runs += [{"code": c, **r, "open": True} for c, r in cur.items()]
    return runs


def summarize(d):
    d = Path(d)
    legs = load_legs(d)
    runs = dp_runs(d)
    out = {"dir": str(d.relative_to(ROOT)) if d.is_absolute() and ROOT in d.parents else str(d), "legs": len(legs), "codes": len({l["code"] for l in legs})}
    if runs:
        lens = [r["days"] for r in runs]
        W = sum(r["w"] for r in runs)
        out["dp"] = {"runs": len(runs), "run_median": st.median(lens), "run_p75": sorted(lens)[int(len(lens) * .75)],
                     "cap_weighted_run": round(sum(r["w"] * r["days"] for r in runs) / W, 1) if W else None,
                     "top_runs": sorted(({"code": r["code"], "days": r["days"], "avg_pos": round(r["w"] / r["days"], 3), "start": r["start"], "open": r["open"]} for r in runs),
                                        key=lambda z: -z["days"] * z["avg_pos"])[:5],
                     "share_runs_le3": round(sum(1 for x in lens if x <= 3) / len(lens), 2)}
    if legs:
        lots = fifo(legs)
        closed = [x for x in lots if not x["open"]]
        A = sum(x["amt"] for x in lots)
        out["fifo"] = {"lots": len(lots), "closed": len(closed), "open": len(lots) - len(closed),
                       "closed_median_days": st.median([x["days"] for x in closed]) if closed else None,
                       "amt_weighted_days_all": round(sum(x["amt"] * x["days"] for x in lots) / A, 1) if A else None,
                       "amt_weighted_days_closed": round(sum(x["amt"] * x["days"] for x in closed) / sum(x["amt"] for x in closed), 1) if closed else None,
                       "amt_share_le3d": round(sum(x["amt"] for x in lots if x["days"] <= 3) / A, 2) if A else None,
                       "amt_share_gt20d": round(sum(x["amt"] for x in lots if x["days"] > 20) / A, 2) if A else None,
                       "biggest": sorted(({k: x[k] for k in ("code", "days", "open", "buy", "sell")} | {"amt": round(x["amt"])} for x in lots), key=lambda z: -z["amt"])[:5]}
    return out


def _selftest():
    legs = [{"code": "A", "t": "2026-01-01 09:30:00", "side": "1", "q": 100, "amt": 1000, "name": ""},
            {"code": "A", "t": "2026-01-03 10:00:00", "side": "2", "q": 40, "amt": 440, "name": ""},
            {"code": "B", "t": "2026-01-02 09:30:00", "side": "1", "q": 10, "amt": 100, "name": ""},
            {"code": "B", "t": "2026-01-02 14:00:00", "side": "2", "q": 10, "amt": 101, "name": ""},
            {"code": "C", "t": "2026-01-05 09:30:00", "side": "2", "q": 5, "amt": 50, "name": ""}]   # 窗口前底仓, 不配
    lots = fifo(legs, "2026-02-01")
    a = [x for x in lots if x["code"] == "A"]
    assert len(a) == 2 and a[0]["days"] == 2 and not a[0]["open"] and a[1]["open"] and a[1]["days"] == 31 and abs(a[1]["q"] - 60) < 1e-9
    assert [x["days"] for x in lots if x["code"] == "B"] == [0]
    assert not [x for x in lots if x["code"] == "C"]
    print("hold_reconcile selftest PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", nargs="*")
    ap.add_argument("--json")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    dirs = [Path(x) if Path(x).is_absolute() else ROOT / x for x in (a.dir or [])] or sorted(p for p in (ROOT / "downloads" / "tzzb_cand").iterdir() if p.is_dir() and not p.name.startswith("_"))
    res = [summarize(d) for d in dirs]
    for r in res:
        print(json.dumps(r, ensure_ascii=False, default=str))
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
