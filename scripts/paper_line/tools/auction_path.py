# -*- coding: utf-8 -*-
"""auction_path.py — 集合竞价路径(10/24 用户批 ❓14: 竞价复核的 01 加"09:15~09:20 竞价路径"; 零 token, 只读当天已录的快照)

为什么: 01 原来只给竞价最新一笔(撮合价 / 未匹配量), 看不到这一段怎么走过来的; 09:15~09:20 可以撤单, 09:19 前后未匹配买单突然大减 = 先挂大单抬价再撤(撤单假单)
每只票一行(只用 ≤ until 的快照):
  首价(第一次有撮合价的时刻 / 相对昨收) · 09:15~09:20 撮合价最高 / 最低 · 09:20 后第一笔 → 此刻(09:20 后不能撤单, 这段的抬价 / 压价才算数)
  撤单信号: 09:18:30~09:19:59 之间某一方总挂单(匹配量 + 该方未匹配)的最大值, 到 09:20 前最后一笔掉了 ≥ DROP → "疑似撤买单(假抬价)" / "疑似撤卖单(假压价)"
            (只看未匹配会误报: 价格一调, 未匹配从卖方翻到买方, 卖方未匹配归零但没人撤单 —— 10/23 中行)
  当前未匹配: 买 / 卖哪边多
数据: downloads/market/<日>/book_snap.jsonl(.gz)(3 秒名单) → 名单外的票用 call_auction_open_raw.jsonl(新浪全市场, 约 15 秒一张)
口径: 竞价段 买一价 = 卖一价 = 虚拟撮合价, 买一量 = 匹配量, 买二量 = 未匹配买, 卖二量 = 未匹配卖
用法: python auction_path.py <D> <HH:MM:SS> <代码,代码>
"""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MKT = ROOT / "downloads" / "market"
DROP = 0.5   # ⚙️ 09:18:30 之后某一方总挂单(匹配 + 未匹配)掉一半以上才报撤单


def _snap_lines(D):
    f = MKT / D / "book_snap.jsonl"
    if f.exists():
        with f.open(encoding="utf-8") as fh:
            yield from fh
    elif f.with_suffix(".jsonl.gz").exists():
        with gzip.open(f.with_suffix(".jsonl.gz"), "rt", encoding="utf-8") as fh:
            yield from fh


_PC = {}


def prev_close(c, D):
    """昨收: 先读本地日线缓存(chain_steps 同口径), 没有就查行情库 kline_day"""
    if (c, D) in _PC:
        return _PC[(c, D)]
    v = None
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "chain"))
        import chain_steps as SC
        v = SC.prev_close(c, D)
    except Exception:   # noqa: BLE001
        pass
    if not v:
        try:
            sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
            import manual_backfill as mb
            cur = mb.db().cursor()
            cur.execute("select k.close from investment_market.kline_day k join investment_market.security_master s on s.symbol=k.symbol and s.sec_type in ('STOCK', 'CB', 'ETF') "
                        "where k.symbol in (%s, %s, %s) and k.trade_date < %s and k.is_deleted=0 order by k.trade_date desc limit 1", ("sh" + c, "sz" + c, "bj" + c, D))   # 只按后 6 位会和指数(sh000002 等)混
            r = cur.fetchone()
            v = float(r[0]) if r else None
        except Exception:   # noqa: BLE001
            v = None
    _PC[(c, D)] = v
    return v


def series(D, until, codes):
    """→ {代码: [(t, 撮合价, 匹配量, 未匹配买, 未匹配卖)]}"""
    want, out = set(codes), {}
    lim = min(until, "09:25:59")
    if until < "09:15:00":
        return out
    for l in _snap_lines(D):
        if '"t": "09:1' not in l and '"t": "09:2' not in l and '"t":"09:1' not in l and '"t":"09:2' not in l:
            if '"t": "09:3' in l or '"t":"09:3' in l:
                break
            continue
        r = json.loads(l)
        c, t = str(r.get("s", ""))[2:], r.get("t", "")
        if c not in want or not ("09:15:00" <= t <= lim):
            continue
        b, k = r.get("b") or [], r.get("k") or []
        if b and b[0][0]:
            out.setdefault(c, []).append((t, float(b[0][0]), int(b[0][1] or 0), int(b[1][1] if len(b) > 1 else 0), int(k[1][1] if len(k) > 1 else 0)))
    first = {c: v[0][0] for c, v in out.items()}
    miss = {c for c in want if c not in first or first[c] > "09:15:30"}   # 不在 3 秒名单 / 名单里开头缺一段(如 002307 09:20 才进名单) → 新浪快照补
    raw = MKT / D / "call_auction_open_raw.jsonl"
    if miss and raw.exists():
        for l in raw.open(encoding="utf-8", errors="replace"):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            c, f = str(r.get("symbol", ""))[2:], r.get("fields") or []
            if c not in miss or len(f) < 32:
                continue
            t = f[31]
            if not ("09:15:00" <= t <= lim):
                continue
            px = float(f[11] or 0)
            if px and (c not in first or t < first[c]):
                out.setdefault(c, []).append((t, px, int(float(f[10] or 0)), int(float(f[12] or 0)), int(float(f[22] or 0))))
    for c in out:
        out[c] = sorted(set(out[c]))
    return out


def analyze(S, prev):
    if not S:
        return None
    pc = lambda x: round((x / prev - 1) * 100, 2) if prev else None   # noqa: E731
    p1 = [x for x in S if x[0] < "09:20:00"]
    p2 = [x for x in S if x[0] >= "09:20:00"]
    out = {"首价": (S[0][0], pc(S[0][1])), "现": (S[-1][0], pc(S[-1][1])), "未匹配": (S[-1][3], S[-1][4]), "匹配量": S[-1][2]}
    if p1:
        out["0915_0920"] = (pc(max(x[1] for x in p1)), pc(min(x[1] for x in p1)), pc(p1[-1][1]))
        w = [x for x in p1 if x[0] >= "09:18:30"]
        if len(w) >= 2:
            last = p1[-1]
            for side, i in (("买", 3), ("卖", 4)):
                tot = lambda x, i=i: x[2] + x[i]   # noqa: E731  单边总挂单 = 匹配量 + 该方未匹配; 09:20 前它变小只能是撤单(未匹配从卖方翻到买方不算)
                mx = max(w, key=tot)
                if tot(mx) > 0 and tot(last) <= tot(mx) * (1 - DROP) and mx[0] < last[0]:
                    out.setdefault("撤单", []).append(f"疑似撤{side}单({'假抬价' if side == '买' else '假压价'}): {side}方总挂单(匹配+未匹配) {mx[0]} {tot(mx)} → {last[0]} {tot(last)}(掉 {(1 - tot(last) / tot(mx)) * 100:.0f}%)"
                                                       + (f", 撮合价 {pc(mx[1]):+.2f}% → {pc(last[1]):+.2f}%" if prev else ""))
    if p2:
        out["0920后"] = (pc(p2[0][1]), pc(p2[-1][1]))
    return out


def text(D, until, codes, prev_of, names=None):
    names = names or {}
    S = series(D, until, codes)
    L = []
    for c in codes:
        a = analyze(S.get(c), prev_of(c))
        if not a:
            continue
        f = lambda v: f"{v:+.2f}%" if isinstance(v, (int, float)) else "-"   # noqa: E731
        s = f"- {c} {names.get(c, '')}: 首价 {a['首价'][0]} {f(a['首价'][1])}"
        if "0915_0920" in a:
            hi, lo, end = a["0915_0920"]
            s += f" | 09:15~09:20 高 {f(hi)} 低 {f(lo)} 收 {f(end)}"
        if "0920后" in a:
            s += f" | 09:20 后(不能撤单) {f(a['0920后'][0])} → {f(a['0920后'][1])}"
        ub, us = a["未匹配"]
        s += f" | 此刻 {a['现'][0]} {f(a['现'][1])} 未匹配 买 {ub} / 卖 {us}({'买方多' if ub > us else '卖方多' if us > ub else '平'})"
        if a.get("撤单"):
            s += " | ⚠" + "; ".join(a["撤单"])
        L.append(s)
    if not L:
        return ""
    return ("## 竞价路径(09:15~09:20 可撤单 / 09:20 后不可撤; 只用此刻之前的快照)\n"
            "口径: 09:20 后的抬价 / 压价才算数; ⚠疑似撤单 = 09:18:30 后某一方总挂单(匹配 + 未匹配)掉一半以上(先挂大单再撤, 前面的撮合价不可信)\n" + "\n".join(L))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = sys.argv[1:]
    print(text(a[0], a[1], a[2].split(","), lambda c: prev_close(c, a[0])))
