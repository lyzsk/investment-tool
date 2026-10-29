# -*- coding: utf-8 -*-
"""signal_odds.py — 信号统计期望表(10/28 用户令: 提醒要有统计期望才推; 零 token)

口径: 信号出现时按信号价买入, 在"能卖的窗口"里摸到 买价 × (1 + TGT) 算盈利
  转债(11 / 12 开头, T+0): 信号之后到当天收盘的 3 秒盘口最高价
  正股(T+1): 次日日线最高价(downloads/market/<次日>/kline_day.jsonl)
另记"收盘卖"的平均收益(转债 = 当日最后价, 正股 = 次日收盘)当参考
分组: 信号 × 转债 / 正股; 全池回放(不分名单, emit 不过滤), 节流照实盘 Throttle
产物: results/_live/signal_odds.json {"tgt", "days", "rows": {"S1|cb": {n, win, avg_close}}}
用法: python signal_odds.py --days 2026-10-19,2026-10-20 [--tgt 1.0]   (每天一个进程并行跑: --one D → results/_live/_odds/<D>.json, 再 --merge)
"""
import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import signals as SG   # noqa: E402

MKT = ROOT / "downloads" / "market"
OUT = ROOT / "results" / "_live"
TGTS = (1, 2, 3, 5)   # 同时记几个目标的盈利率, 门槛目标用 --tgt / chain_flags SIG_ODDS_TGT


def next_day(D):
    ds = sorted(p.name for p in MKT.iterdir() if p.is_dir() and p.name[:2] == "20" and (p / "kline_day.jsonl").exists() and p.name > D)
    return ds[0] if ds else None


def day_hi(D):
    out = {}
    if not D:
        return out
    for l in (MKT / D / "kline_day.jsonl").open(encoding="utf-8"):
        try:
            r = json.loads(l)
            out[r["symbol"][-6:]] = (float(r["high"]), float(r["close"]))
        except (ValueError, KeyError, TypeError):
            continue
    return out


def one(D, tgt):
    SG.load_yaml()
    SG.load_dyn(D)
    meta = SG.Meta(D)
    meta.sigmas()
    det = SG.Detector(D, meta, emit=None)
    th = SG.Throttle()
    evs, last, mx = [], {}, defaultdict(list)   # mx: 代码 → [(交易秒, 价)]
    for r in SG.iter_rows(D):
        for e in det.feed(r):
            if th.ok(e):
                evs.append(e)
        c, t, p = str(r.get("s", ""))[2:], r.get("t") or "", float(r.get("p") or 0)
        if p > 0 and "09:30:00" <= t <= "15:00:00" and c[:2] in ("11", "12"):
            mx[c].append((t, p))
            last[c] = p
    nd = next_day(D)
    hi = day_hi(nd)
    rows = defaultdict(lambda: {"n": 0, "win": 0, "ret": 0.0, **{f"w{g:g}": 0 for g in TGTS}})
    for e in evs:
        c, px = e["code"], float(e["px"] or 0)
        if px <= 0:
            continue
        if c[:2] in ("11", "12"):
            after = [p for t, p in mx.get(c, []) if t > e["t"]]
            if not after:
                continue
            top, ret = max(after), (last[c] / px - 1) * 100
            k = "cb"
        else:
            if c not in hi:
                continue
            top, cl = hi[c]
            ret = (cl / px - 1) * 100
            k = "stock"
        ix = SG.idx_now(D, e["t"])   # "上证 +0.52% / 创业板 …" → 分「上证此刻红 / 绿」两组(10/28 用户: 期望要分情况, 不能一个信号一个数)
        try:
            bk = "up" if float(ix.split("上证 ")[1].split("%")[0]) >= 0 else "dn"
        except (IndexError, ValueError):
            bk = None
        for kk in [f"{e['sig']}|{k}"] + ([f"{e['sig']}|{k}|{bk}"] if bk else []):
            z = rows[kk]
            z["n"] += 1
            z["win"] += int(top >= px * (1 + tgt / 100))
            z["ret"] += ret
            for g in TGTS:
                z[f"w{g:g}"] += int(top >= px * (1 + g / 100))
    return {"D": D, "next": nd, "rows": dict(rows)}


def merge(files, tgt):
    tot = defaultdict(lambda: defaultdict(float))
    days = []
    for f in files:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        days.append(d["D"])
        for k, v in d["rows"].items():
            for kk, vv in v.items():
                tot[k][kk] += vv
    rows = {k: {"n": int(v["n"]), "win": round(v["win"] / v["n"], 4) if v["n"] else None, "avg_close": round(v["ret"] / v["n"], 3) if v["n"] else None,
                **{f"win{g:g}": round(v.get(f"w{g:g}", 0) / v["n"], 4) for g in TGTS if v["n"]}} for k, v in tot.items()}
    res = {"tgt": tgt, "days": sorted(days), "built": dt.datetime.now().isoformat(timespec="seconds"), "rows": dict(sorted(rows.items()))}
    (OUT / "signal_odds.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--one")
    ap.add_argument("--merge", nargs="*")
    ap.add_argument("--tgt", type=float, default=1.0)
    a = ap.parse_args()
    if a.one:
        (OUT / "_odds").mkdir(parents=True, exist_ok=True)
        r = one(a.one, a.tgt)
        (OUT / "_odds" / f"{a.one}.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        print(a.one, "done", sum(v["n"] for v in r["rows"].values()))
    elif a.merge is not None:
        r = merge(a.merge or sorted(str(p) for p in (OUT / "_odds").glob("20*.json")), a.tgt)
        print(f"天: {r['days']}  目标 +{r['tgt']}%")
        for k, v in r["rows"].items():
            print(f"  {k:10s} n={v['n']:5d}  " + "  ".join(f"+{g}% {v.get(f'win{g}', 0) * 100:5.1f}%" for g in TGTS) + f"  收盘卖均值 {v['avg_close']:+.2f}%")
