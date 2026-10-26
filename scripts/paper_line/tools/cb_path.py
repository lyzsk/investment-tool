# -*- coding: utf-8 -*-
"""cb_path.py — 同一只转债近 N 个交易日的开盘 / 盘中 / 尾盘路径(10/23 用户: 澳弘 10/20 和 10/23 开盘走法相似, 模型没认出来 —— 相似日库没有"同债近期"这一维; 零 token)

每天一行(只用 D 之前的数据):
  缺口 = 竞价开盘 / 昨收; 竞价段最低(09:15~09:25, 有 call_auction_open 才有) → 09:20 价 → 撮合价
  开盘后 30 分钟内最高(相对开盘 + 时刻) / 15 分钟内最低 → 之后 60 分钟最高(低到高)
  尾盘: 14:20~14:45 最低 → 之后到收盘最高(相对那个低点) / 收盘相对开盘
数据: downloads/quotes/cb/minute/<代码>/<日>.json(通达信逐笔聚合) → 缺了用 downloads/market/<日>/kline_minute.jsonl
用法: python cb_path.py <转债代码> <D> [N=10]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MIN = ROOT / "downloads" / "quotes" / "cb" / "minute"
MKT = ROOT / "downloads" / "market"


def _bars(code, d):
    """→ (昨收, 竞价开盘, [(HH:MM, 高, 低, 收)])"""
    f = MIN / code / f"{d}.json"
    if f.exists():
        j = json.loads(f.read_text(encoding="utf-8"))
        B = [(b["t"], b["h"], b["l"], b["c"]) for b in j.get("bars") or []]
        return j.get("prev"), j.get("open_auction") or (B[0][3] if B else None), B
    f = MKT / d / "kline_minute.jsonl"
    if not f.exists():
        return None, None, []
    sym = ("sh" if code.startswith("11") else "sz") + code
    B = []
    for l in f.open(encoding="utf-8"):
        if f'"{sym}"' in l:
            x = json.loads(l)
            B.append((x["barTime"][11:16], x["high"], x["low"], x["close"]))
    B.sort()
    prev = None
    kd = MKT / d / "kline_day.jsonl"
    if kd.exists():
        for l in kd.open(encoding="utf-8"):
            if f'"{sym}"' in l:
                prev = json.loads(l).get("preClose") or json.loads(l).get("pre_close")
                break
    return prev, (B[0][3] if B else None), B


def _auction(code, d):
    f = MKT / d / "call_auction_open.jsonl"
    if not f.exists():
        return None
    sym = ("sh" if code.startswith("11") else "sz") + code
    P = []
    for l in f.open(encoding="utf-8"):
        if f'"{sym}"' in l:
            x = json.loads(l)
            if x.get("price"):
                P.append((x["snapTime"][11:19], float(x["price"])))
    if not P:
        return None
    lo = min(P, key=lambda x: x[1])
    p20 = next((p for t, p in P if t >= "09:20"), None)
    return {"竞价段最低": lo[1], "最低时刻": lo[0][:5], "09:20价": p20, "撮合": P[-1][1]}


def days_before(D, n):
    ds = sorted({p.stem for p in MKT.glob("20*") if p.is_dir() and p.name < D} | {p.stem for p in MIN.glob("*/20*.json") if p.stem < D})
    return ds[-n:]


def query(code, D, n=10):
    rows = []
    for d in days_before(D, n + 5):
        prev, o, B = _bars(code, d)
        if not B or not prev or not o:
            continue
        pct = lambda x, base: round((x / base - 1) * 100, 2)   # noqa: E731
        m30 = [b for b in B if "09:31" <= b[0] <= "10:00"] or B[:30]
        h = max(m30, key=lambda b: b[1])
        m15 = [b for b in B if "09:31" <= b[0] <= "09:45"] or B[:15]
        lo = min(m15, key=lambda b: b[2])
        after = [b for b in B if lo[0] < b[0] <= f"{int(lo[0][:2]) + 1:02d}{lo[0][2:]}"]
        hi2 = max(after, key=lambda b: b[1]) if after else lo
        tw = [b for b in B if "14:20" <= b[0] <= "14:45"]
        tail = None
        if tw:
            tl = min(tw, key=lambda b: b[2])
            ta = [b for b in B if tl[0] < b[0] <= "15:00"]
            if ta:
                tail = {"尾盘低点": tl[0], "低点后最高(相对低点)": pct(max(b[1] for b in ta), tl[2])}
        au = _auction(code, d)
        rows.append({"d": d, "缺口": pct(o, prev), **({"竞价段最低(相对昨收)": pct(au["竞价段最低"], prev), "竞价最低时刻": au["最低时刻"], "09:20(相对昨收)": pct(au["09:20价"], prev) if au["09:20价"] else None} if au else {}),
                     "开盘后30分钟最高(相对开盘)": pct(h[1], o), "最高时刻": h[0], "15分钟内最低(相对开盘)": pct(lo[2], o), "低点后60分钟最高(相对低点)": pct(hi2[1], lo[2]),
                     **(tail or {}), "收盘(相对开盘)": pct(B[-1][3], o), "收盘(相对昨收)": pct(B[-1][3], prev)})
    rows = rows[-n:]
    low = [r for r in rows if r["缺口"] <= -1]
    high = [r for r in rows if r["缺口"] >= 2]
    summ = {}
    for tag, xs in (("低开(≤−1%)日", low), ("高开(≥+2%)日", high)):
        if xs:
            summ[tag] = {"天数": len(xs), "开盘后30分钟最高 各日": [r["开盘后30分钟最高(相对开盘)"] for r in xs], "收盘相对开盘 各日": [r["收盘(相对开盘)"] for r in xs]}
    return {"code": code, "D": D, "近 N 天": len(rows), "按缺口归类": summ, "逐日": rows}


def must_line(code, D, n=10):
    r = query(code, D, n)
    if not r["逐日"]:
        return [("同债近期路径", "没有分钟数据")]
    days = "; ".join(f"{x['d'][5:]} 缺口{x['缺口']:+.1f} 30分钟高{x['开盘后30分钟最高(相对开盘)']:+.1f}@{x['最高时刻']} 收/开{x['收盘(相对开盘)']:+.1f}" for x in r["逐日"])
    s = "; ".join(f"{k} {v['天数']} 天 30 分钟高 {v['开盘后30分钟最高 各日']}" for k, v in r["按缺口归类"].items())
    return [("同债近期路径", f"近 {r['近 N 天']} 天(相对开盘 %): {days}" + (f" | 归类: {s}" if s else ""))]


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = sys.argv[1:]
    print(json.dumps(query(a[0], a[1], int(a[2]) if len(a) > 2 else 10), ensure_ascii=False, indent=1))
