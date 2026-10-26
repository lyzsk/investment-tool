# -*- coding: utf-8 -*-
"""board_state.py — 必查「封板状态」(10/25 用户批: 持仓 / 焦点票封板、开板、回封时给"当天"口径的统计; 零 token, 只读)

起因: 10/23 芷影线北新路桥 09:33 二封涨停后在封板价卖, 引用的是"回封板次日收盘中位 −2.20%"(次日口径)——拿明天的统计决定今天盘中, 口径错配;
      当天该看的是: 已回封过的票今天封到收盘的概率、再开板后到收盘怎么走
state(code, D, upto)  → 今天到 upto 为止: 涨停价 / 是否封过 / 现在封着没 / 开板次数 / 首封时刻 / 连板高度(按日线) → dict 或 None(今天没碰过涨停)
item(code, D, upto)   → 必查一行文本(没碰过涨停 → None)
统计: downloads/ontology/ontology.db event 表 kind='open'(每次开板一个事件; tags: height 首板/二板/三板+ · tm 早盘<10:00/上午/下午<14:00/尾盘≥14:00 · k 第N次;
      out: resealed 这次开板后有没有回封 · close_sealed 收盘封没封住 · ret_close 开板那刻买到收盘 %), 只取 D 之前的事件(不偷看)
分钟数据: downloads/market/<D>/kline_minute_live.jsonl(盘中, Java 每分钟写) → 没有用 kline_minute.jsonl(收盘后)
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "downloads" / "ontology" / "ontology.db"
MKT = ROOT / "downloads" / "market"
_C = {}


def _sym(code):
    return ("sh" if str(code).startswith(("6", "11", "5")) else "sz") + str(code)


def _bars(code, D, upto):
    key = ("bars", D)
    if key not in _C:
        by = {}
        for fn in ("kline_minute_live.jsonl", "kline_minute.jsonl"):
            f = MKT / D / fn
            if not f.exists():
                continue
            for l in f.open(encoding="utf-8"):
                try:
                    j = json.loads(l)
                except ValueError:
                    continue
                by.setdefault(j.get("symbol"), {})[j["barTime"][11:16]] = (j["high"], j["low"], j["close"])
            if by:
                break
        _C[key] = by
    rows = _C[key].get(_sym(code)) or {}
    return [(t, *v) for t, v in sorted(rows.items()) if t <= upto[:5]]


def _limit_and_height(code, D):
    key = ("lim", code, D)
    if key not in _C:
        try:
            sys.path.insert(0, str(ROOT / "scripts" / "live"))
            import plan_review as PR
            c = PR.db().cursor()
            c.execute("select trade_date, close, limit_up from investment_market.kline_day where symbol=%s and trade_date <= %s order by trade_date desc limit 8", (_sym(code), D))
            rows = c.fetchall()
            up = float(rows[0][2]) if rows and str(rows[0][0]) == D and rows[0][2] else None
            if up is None:   # 当天日线还没入库 → 用昨收算(主板 10% / 创业科创 20%)
                prev = [r for r in rows if str(r[0]) < D]
                if prev:
                    pc = float(prev[0][1])
                    up = round(pc * (1.2 if str(code).startswith(("30", "68")) else 1.1), 2)
            n = 0
            for d, cl, lu in rows:
                if str(d) >= D:
                    continue
                if lu and abs(float(cl) - float(lu)) < 1e-6:
                    n += 1
                else:
                    break
            _C[key] = (up, n)
        except Exception:   # noqa: BLE001
            _C[key] = (None, 0)
    return _C[key]


def state(code, D, upto):
    up, prev_boards = _limit_and_height(code, D)
    if not up:
        return None
    b = _bars(code, D, upto)
    if not b:
        return None
    sealed_min = [t for t, hi, lo, cl in b if abs(cl - up) < 1e-6]
    touched = [t for t, hi, lo, cl in b if hi >= up - 1e-6]
    if not touched:
        return None
    opens, prev_sealed = 0, False
    for t, hi, lo, cl in b:
        s = abs(cl - up) < 1e-6
        if prev_sealed and not s:
            opens += 1
        prev_sealed = s
    now_sealed = bool(b) and abs(b[-1][3] - up) < 1e-6
    first = sealed_min[0] if sealed_min else touched[0]
    height = "首板" if prev_boards == 0 else "二板" if prev_boards == 1 else "三板+"
    tm = "早盘<10:00" if first < "10:00" else "上午" if first < "11:31" else "下午<14:00" if first < "14:00" else "尾盘≥14:00"
    return {"up": up, "height": height, "first": first, "opens": opens, "now_sealed": now_sealed, "tm": tm, "last": b[-1][3]}


def _stats(D, height, tm, k):
    key = ("st", D, height, tm, k)
    if key in _C:
        return _C[key]
    out = None
    try:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True).cursor()
        c.execute("select tags, out from event where kind='open' and d < ?", (D,))
        rows = [(json.loads(t or "{}"), json.loads(o or "{}")) for t, o in c.fetchall()]
        for drop in ([], ["tm"], ["tm", "height"]):   # 样本 < 30 逐级放宽
            sel = [o for t, o in rows if t.get("k") == k and ("height" in drop or t.get("height") == height) and ("tm" in drop or t.get("tm") == tm)]
            if len(sel) >= 30 or drop == ["tm", "height"]:
                out = (sel, drop)
                break
    except Exception:   # noqa: BLE001
        out = None
    _C[key] = out
    return out


def _dist(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return "无样本"
    q = lambda p: xs[int(p * (len(xs) - 1))]   # noqa: E731
    return f"n={len(xs)} 中{q(.5):+.2f}% P10 {q(.1):+.2f}% 最差 {xs[0]:+.2f}%"


def item(code, D, upto):
    s = state(code, D, upto)
    if not s:
        return None
    k_now = f"第{max(1, s['opens'])}次"
    k_next = f"第{s['opens'] + 1}次"
    head = (f"〔当天口径〕今天{s['height']}冲击涨停 {s['up']}: 首封 {s['first']}, 已开板 {s['opens']} 次, 现在{'封着' if s['now_sealed'] else '没封住(现价 ' + str(s['last']) + ')'}")
    L = [head]
    if s["opens"] >= 1:   # 已开过板: 这些开过板又回封的, 收盘封住多少
        st = _stats(D, s["height"], s["tm"], k_now)
        if st:
            sel, drop = st
            rs = [o for o in sel if o.get("resealed") == 1]
            if rs:
                cs = sum(1 for o in rs if o.get("close_sealed") == 1) / len(rs)
                L.append(f"同类({s['height']}·{s['tm']}·{k_now}开板后回封过{'·已放宽 ' + '/'.join(drop) if drop else ''}) n={len(rs)}: 收盘封住 {cs:.0%}")
    st2 = _stats(D, s["height"], s["tm"], k_next)
    if st2:
        sel, drop = st2
        if sel:
            rr = sum(1 for o in sel if o.get("resealed") == 1) / len(sel)
            L.append(f"若再开板({k_next}{'·已放宽 ' + '/'.join(drop) if drop else ''}): 之后回封 {rr:.0%}, 收盘封住 {sum(1 for o in sel if o.get('close_sealed') == 1) / len(sel):.0%}; "
                     f"开板那一刻到收盘 {_dist([o.get('ret_close') for o in sel])}")
    L.append("这是用到今天盘中已发生情况(封没封、开过几次板)的统计, 比「炸板回封 / 强势股次日」那类只按昨天状态算的今天分布更具体; 两者冲突时以这条为准")
    return " | ".join(L)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for t in ("09:31", "09:34", "09:45"):
        print(t, item("002307", "2026-10-23", t + ":00"))
