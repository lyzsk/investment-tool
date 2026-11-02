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
SELL_SIGS = {"S16", "S18", "S20"}   # 抢跑/高抛/首次跌停候选是风险信号：命中 = 之后跌到 -TGT


def next_day(D):
    ds = sorted(p.name for p in MKT.iterdir() if p.is_dir() and p.name[:2] == "20" and (p / "kline_day.jsonl").exists() and p.name > D)
    return ds[0] if ds else None


def day_hi(D):
    out = {}
    if not D:
        return out
    with (MKT / D / "kline_day.jsonl").open(encoding="utf-8") as fh:
        for l in fh:
            try:
                r = json.loads(l)
                sym, code = r["symbol"], r["symbol"][-6:]
                expected = ("sh" if code.startswith(("6", "5", "11")) else "bj" if code.startswith(("4", "8")) else "sz") + code
                if sym != expected:   # 指数与股票后六位可相同：sh000010 不得覆盖 sz000010
                    continue
                out[code] = (float(r["high"]), float(r["close"]), float(r["low"]))
            except (ValueError, KeyError, TypeError):
                continue
    return out


def row_bucket():
    return {"n": 0, "win": 0, "ret": 0.0, "rets": [], **{f"w{g:g}": 0 for g in TGTS}}


def add_score(rows, key, px, extreme, cl, sell, tgt):
    """同一计分器服务信号和基准；sell=True 时收益=规避后续下跌。"""
    z = rows[key]
    z["n"] += 1
    z["win"] += int(extreme <= px * (1 - tgt / 100) if sell else extreme >= px * (1 + tgt / 100))
    z["ret"] += ((px / cl - 1) if sell else (cl / px - 1)) * 100
    z["rets"].append(((px / cl - 1) if sell else (cl / px - 1)) * 100)
    for g in TGTS:
        z[f"w{g:g}"] += int(extreme <= px * (1 - g / 100) if sell else extreme >= px * (1 + g / 100))


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
    rows = defaultdict(row_bucket)
    for e in evs:
        c, px = e["code"], float(e["px"] or 0)
        if px <= 0:
            continue
        sell = e["sig"] in SELL_SIGS
        if c[:2] in ("11", "12"):
            after = [p for t, p in mx.get(c, []) if t > e["t"]]
            if not after:
                continue
            extreme, cl = (min(after) if sell else max(after)), last[c]
            k = "cb"
        else:
            if c not in hi:
                continue
            top, cl, low = hi[c]
            extreme = low if sell else top
            k = "stock"
        ix = SG.idx_now(D, e["t"])   # "上证 +0.52% / 创业板 …" → 分「上证此刻红 / 绿」两组(10/28 用户: 期望要分情况, 不能一个信号一个数)
        try:
            bk = "up" if float(ix.split("上证 ")[1].split("%")[0]) >= 0 else "dn"
        except (IndexError, ValueError):
            bk = None
        for kk in [f"{e['sig']}|{k}"] + ([f"{e['sig']}|{k}|{bk}"] if bk else []):
            add_score(rows, kk, px, extreme, cl, sell, tgt)
    # 同日、同 3 秒盘口池、同 09:25 起点的全量竞价基准；用于消融“只是当天整体强/弱”
    af = MKT / D / "auction_live_open.json"
    if af.exists():
        try:
            symbols = (json.loads(af.read_text(encoding="utf-8")).get("symbols") or {})
        except ValueError:
            symbols = {}
        for sym, s in symbols.items():
            c = sym[2:]
            if c not in det.st:
                continue
            px = float((s.get("fin") or {}).get("px") or 0)
            if px <= 0:
                continue
            cb = c[:2] in ("11", "12")
            if cb:
                after = [p for _, p in mx.get(c, [])]
                if not after:
                    continue
                high, low, cl = max(after), min(after), last[c]
                k = "cb"
            else:
                if c not in hi:
                    continue
                high, cl, low = hi[c]
                k = "stock"
            add_score(rows, f"BASE_AUCTION_BUY|{k}", px, high, cl, False, tgt)
            add_score(rows, f"BASE_AUCTION_SELL|{k}", px, low, cl, True, tgt)
    return {"D": D, "next": nd, "rows": dict(rows)}


def merge(files, tgt):
    tot = defaultdict(lambda: defaultdict(float))
    days = []
    for f in files:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        days.append(d["D"])
        for k, v in d["rows"].items():
            for kk, vv in v.items():
                if kk == "rets":
                    if not isinstance(tot[k][kk], list):
                        tot[k][kk] = []
                    tot[k][kk].extend(vv)
                else:
                    tot[k][kk] += vv
    def stats(v):
        xs = sorted(v.get("rets") or [])
        q = lambda p: round(xs[int(p * (len(xs) - 1))], 3) if xs else None
        return {"n": int(v["n"]), "win": round(v["win"] / v["n"], 4) if v["n"] else None,
                "avg_close": round(v["ret"] / v["n"], 3) if v["n"] else None,
                "median": q(.5), "p10": q(.1), "p90": q(.9), "best": q(1), "worst": q(0),
                **{f"win{g:g}": round(v.get(f"w{g:g}", 0) / v["n"], 4) for g in TGTS if v["n"]}}
    rows = {k: stats(v) for k, v in tot.items()}
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
            sell = k.startswith(("S16|", "S18|", "S20|", "BASE_AUCTION_SELL|"))
            sign = "−" if sell else "+"
            tail = "规避收益均值" if sell else "收盘卖均值"
            print(f"  {k:22s} n={v['n']:5d}  " + "  ".join(f"{sign}{g}% {v.get(f'win{g}', 0) * 100:5.1f}%" for g in TGTS) + f"  {tail} {v['avg_close']:+.2f}% 中位 {v['median']:+.2f}% P10 {v['p10']:+.2f}% P90 {v['p90']:+.2f}% 最差 {v['worst']:+.2f}%")
