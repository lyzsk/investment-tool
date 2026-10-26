# -*- coding: utf-8 -*-
"""key_levels.py — 关键价位表(v3 命名查询工具; 零 token, 只读行情库; 10/22 晚用户令 "1、2、3 先做")

回答: "这只票现在上方 / 下方有哪些价位会挡 / 托? 离现价多远?" —— 挂单价、止损价、止盈价都该落在这些价位附近, 而不是拍脑袋的整百分比
价位来源(全部 D 日开盘前已知, 只有 分时均价 / 当日高低 是盘中值):
  涨停 / 跌停价       kline_day.limit_up / limit_down 的 D−1 行 → 按 D−1 收盘 × 板块幅度推 D 日(主板 10 / 创业科创 20 / 转债 20 / ST 5)
  昨日 开高低收        D−1
  前高 / 前低          近 5 / 10 / 20 / 60 / 120 日最高最低(带日期)
  均线                MA5 / 10 / 20 / 60(D−1 收盘口径)
  未回补缺口           近 60 日: 向上缺口 = 当日最低 > 前日最高 且之后最低没回到前日最高; 向下同理
  近期涨停板位          近 20 日涨停日的收盘价(打板资金成本, 常成支撑)
  成交密集区            近 20 日: 有分钟线(kline_minute, 10/09 起关注集)用分钟量价直方图; 否则把每日成交量均摊到当日 [低, 高] 区间 → 取量最大的 3 档
  整数关口              现价附近的整数 / 半整数(转债看 5 元整数, 股票按价位定步长)
  分时均价 / 当日高低     --at 给了且 D 当天有分钟线时才有(kline_minute.avg_price 截到该时刻)
用法:
  python key_levels.py --code 601988 --date 2026-10-23 [--price 7.25] [--at 10:15]
  python key_levels.py --code 111024 --date 2026-10-23
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))


def sym(code):
    return ("sh" if code.startswith(("6", "9", "11", "5")) else "sz") + code


def lim_pct(code, name=""):
    if code.startswith(("11", "12")):
        return 20.0
    if "ST" in (name or "").upper():
        return 5.0
    return 20.0 if code.startswith(("300", "301", "688", "689")) else 10.0


def cur_():
    import manual_backfill as mb
    c = mb.db().cursor()
    c.execute("use investment_market")
    return c


def tick(code):
    return 0.001 if code.startswith(("11", "12", "5", "15", "16")) else 0.01


def rnd(x, code):
    t = tick(code)
    return round(round(x / t) * t, 3)


def levels(code, D, price=None, at=None):
    cur = cur_()
    s = sym(code)
    cur.execute("select name from security_master where symbol=%s", (s,))
    r = cur.fetchone()
    name = r[0] if r else ""
    cur.execute("select trade_date, open, high, low, close, volume from kline_day where is_deleted=0 and symbol=%s and trade_date < %s "
                "order by trade_date desc limit 130", (s, D))
    K = [(str(d), float(o), float(h), float(l), float(c), float(v or 0)) for d, o, h, l, c, v in cur.fetchall() if o and c][::-1]
    if len(K) < 6:
        return {"err": f"{code} 在 {D} 前日线不足"}
    pc = K[-1][4]
    px = price or pc
    L = []

    def add(p, what, src):
        if p and p > 0:
            L.append({"价": rnd(p, code), "是什么": what, "来源": src})

    lp = lim_pct(code, name)
    add(pc * (1 + lp / 100), f"D 日涨停价(+{lp:g}%)", "昨收推算")
    add(pc * (1 - lp / 100), f"D 日跌停价(−{lp:g}%)", "昨收推算")
    d1 = K[-1]
    add(d1[1], "昨开", d1[0])
    add(d1[2], "昨高", d1[0])
    add(d1[3], "昨低", d1[0])
    add(pc, "昨收", d1[0])
    for n in (5, 10, 20, 60, 120):
        if len(K) >= n:
            w = K[-n:]
            hi = max(w, key=lambda x: x[2])
            lo = min(w, key=lambda x: x[3])
            add(hi[2], f"{n} 日最高", hi[0])
            add(lo[3], f"{n} 日最低", lo[0])
    for n in (5, 10, 20, 60):
        if len(K) >= n:
            add(sum(x[4] for x in K[-n:]) / n, f"MA{n}", "昨收口径")
    # 未回补缺口(近 60 日)
    W = K[-61:]
    for i in range(1, len(W)):
        a, b = W[i - 1], W[i]
        rest = W[i + 1:]
        if b[3] > a[2] and all(x[3] > a[2] for x in rest):
            add(a[2], f"向上缺口下沿(未补, 缺口 {a[2]:.3g}~{b[3]:.3g})", b[0])
        if b[2] < a[3] and all(x[2] < a[3] for x in rest):
            add(a[3], f"向下缺口上沿(未补, 缺口 {b[2]:.3g}~{a[3]:.3g})", b[0])
    # 近 20 日涨停板位
    for i in range(max(1, len(K) - 20), len(K)):
        if K[i][4] >= K[i - 1][4] * (1 + lp / 100 - 0.002):   # 留 0.2% 容差(涨停价四舍五入到分)
            add(K[i][4], "涨停板位(当日涨停收盘)", K[i][0])
    # 成交密集区
    vp, src = volume_profile(cur, s, K, D, code)
    for p, share in vp:
        add(p, f"成交密集区(占近 20 日量 {share:.0%})", src)
    # 整数关口
    step = 5.0 if code.startswith(("11", "12")) else (1.0 if px >= 20 else 0.5 if px >= 5 else 0.1)
    base = int(px / step) * step
    for k in (0, 1):
        add(base + k * step, "整数关口", f"步长 {step:g}")
    # 盘中: 分时均价 / 当日高低
    intraday = {}
    if at:
        cur.execute("select bar_time, high, low, close, avg_price from kline_minute where is_deleted=0 and symbol=%s and trade_date=%s and time(bar_time) <= %s order by bar_time",
                    (s, D, at + ":00"))
        rows = cur.fetchall()
        if rows:
            add(float(rows[-1][4]), f"分时均价(截至 {at})", "kline_minute")
            add(max(float(x[1]) for x in rows), f"当日最高(截至 {at})", "kline_minute")
            add(min(float(x[2]) for x in rows), f"当日最低(截至 {at})", "kline_minute")
            intraday = {"此刻价": float(rows[-1][3])}
            if not price:
                px = intraday["此刻价"]
        else:
            intraday = {"说明": f"{D} 没有 {code} 的分钟线(不在关注集或还没采)"}
    # 合并相同价位, 按离现价排序
    M = {}
    for x in L:
        M.setdefault(x["价"], []).append(f"{x['是什么']}[{x['来源']}]")
    rows = [{"价": p, "离现价%": round((p / px - 1) * 100, 2), "是什么": " / ".join(v)} for p, v in M.items()]
    above = sorted([r for r in rows if r["价"] > px], key=lambda r: r["价"])
    below = sorted([r for r in rows if r["价"] < px], key=lambda r: -r["价"])
    at_px = [r for r in rows if r["价"] == px]
    return {"code": code, "name": name, "D": D, "现价": px, "现价来源": "参数" if price else ("盘中分钟线" if intraday.get("此刻价") else "昨收"),
            **({"盘中": intraday} if intraday else {}), "上方(近→远)": above[:12], "就在现价": at_px, "下方(近→远)": below[:12],
            "说明": "多个来源落在同一价位 = 更强; 离现价 ±1% 内的价位最该看"}


def volume_profile(cur, s, K, D, code, top=3):
    """近 20 日成交密集区: 有分钟线用分钟收盘价 × 量; 否则日量均摊到 [低, 高]; 分 40 档取量最大的 top 档(相邻档只留一个)"""
    W = K[-20:]
    lo, hi = min(x[3] for x in W), max(x[2] for x in W)
    if hi <= lo:
        return [], ""
    nb = 40
    w = (hi - lo) / nb
    bins = [0.0] * nb
    cur.execute("select close, volume from kline_minute where is_deleted=0 and symbol=%s and trade_date >= %s and trade_date < %s", (s, W[0][0], D))
    mrows = cur.fetchall()
    days_with_min = 0
    if mrows:
        cur.execute("select count(distinct trade_date) from kline_minute where is_deleted=0 and symbol=%s and trade_date >= %s and trade_date < %s", (s, W[0][0], D))
        days_with_min = cur.fetchone()[0]
    if days_with_min >= 5:
        for c, v in mrows:
            i = min(nb - 1, max(0, int((float(c) - lo) / w)))
            bins[i] += float(v or 0)
        src = f"分钟量价({days_with_min} 天)"
    else:
        for _, o, h, l, c, v in W:
            a, b = int((l - lo) / w), min(nb - 1, int((h - lo) / w))
            for i in range(a, b + 1):
                bins[i] += v / (b - a + 1)
        src = "日量均摊(近 20 日)"
    tot = sum(bins) or 1
    order = sorted(range(nb), key=lambda i: -bins[i])
    pick = []
    for i in order:
        if all(abs(i - j) > 2 for j in pick):
            pick.append(i)
        if len(pick) >= top:
            break
    return [(lo + (i + 0.5) * w, bins[i] / tot) for i in pick], src


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--price", type=float)
    ap.add_argument("--at")
    a = ap.parse_args()
    print(json.dumps(levels(a.code, a.date, a.price, a.at), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
