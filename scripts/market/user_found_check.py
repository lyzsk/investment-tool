# -*- coding: utf-8 -*-
"""market/user_found_check.py — market-skill 用户发现 U 节每晚零 token 核销(10/25 用户批沉淀分层 v2: U 先核销, 够样本升 M / KS 要用户点头)

U1 转债低开后当天冲到开盘价 +6%: 全市场转债日线, 开盘 < 昨收 的日子里 当天最高 ≥ 开盘 × 1.06 的比例; 对照 = 开盘 ≥ 昨收 的日子
U2 转债高开 +2~3% 后回落到 −3% 接: 开盘涨幅 2%~3% 且当天最低 ≤ 昨收 × 0.97 → 在昨收 × 0.97 接 → 当天收盘 / 次日最高 / 次日收盘(相对接价)
U3 尾盘 14:25~14:45 低点后 10 分钟内拉升 ≥1.5%: 分钟路径(股票 downloads/quotes/stock/minute_path + 转债 downloads/quotes/cb/minute_path)
   盘中可执行口径: 14:25 起每分钟看"14:25 以来最低价 L(到此刻)", 之后 10 分钟内价格 ≥ L × 1.015 → 记一次(每票每天一次, 买点 = 触发那分钟价)
   → 到收盘 / 次日收盘(次日用日线)相对买点; 对照 = 同一批票同一天 14:45 收盘价买
产物: docs/research/user_found_check.md(只报数, 不改 user_found.md; 升级要你点头)
用法: python user_found_check.py [--days 120]
"""
import argparse
import collections
import datetime as dt
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "backfill_bilibili")]
OUT = ROOT / "docs" / "research" / "user_found_check.md"
TM = [f"{9 + (i + 31) // 60:02d}:{(i + 31) % 60:02d}" if i < 120 else f"{13 + (i - 119) // 60:02d}:{(i - 119) % 60:02d}" for i in range(240)]


def dist(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return "n=0"
    return f"n={len(v)} 中{v[len(v) // 2]:+.2f} 均{st.mean(v):+.2f} P10 {v[int(len(v) * .1)]:+.2f} P90 {v[min(len(v) - 1, int(len(v) * .9))]:+.2f} 最差{v[0]:+.2f} 最好{v[-1]:+.2f}"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    a = ap.parse_args()
    import manual_backfill as mb
    c = mb.db().cursor()
    c.execute("select distinct trade_date from investment_market.kline_day where symbol='sh000001' and is_deleted=0 order by trade_date desc limit %s", (a.days + 2,))
    days = sorted(str(x[0]) for x in c.fetchall())
    c.execute("select k.symbol, k.trade_date, k.open, k.high, k.low, k.close, k.pre_close from investment_market.kline_day k join investment_market.security_master s "
              "on s.symbol=k.symbol and s.sec_type='CB' where k.is_deleted=0 and k.trade_date>=%s and k.pre_close>0 order by k.symbol, k.trade_date", (days[0],))
    CB = collections.defaultdict(list)
    for s, d, o, h, l_, cl, pc in c.fetchall():
        if o and cl:
            CB[s].append((str(d), float(o), float(h), float(l_), float(cl), float(pc)))
    u1, u1b, u2 = [], [], []
    for s, K in CB.items():
        for i, (d, o, h, l_, cl, pc) in enumerate(K):
            g = o / pc - 1
            (u1 if g < 0 else u1b).append(h / o - 1 >= 0.06)
            if 0.02 <= g <= 0.03 and l_ <= pc * 0.97:
                ent = pc * 0.97
                nx = K[i + 1] if i + 1 < len(K) else None
                u2.append({"r0": (cl / ent - 1) * 100, "h1": (nx[2] / ent - 1) * 100 if nx else None, "c1": (nx[4] / ent - 1) * 100 if nx else None})
    L = [f"# market-skill 用户发现 U 节核销（{dt.date.today()}；近 {a.days} 个交易日 {days[2]} ~ {days[-1]}；零 token）", "",
         "> 脚本 `scripts/market/user_found_check.py`。只报数，不改 `user_found.md`；要升成 M / KS 规则等你点头。", "",
         "## U1 转债低开后当天冲到开盘价 +6%", "",
         f"- 低开日：{sum(u1)} / {len(u1)} = **{sum(u1) / len(u1):.1%}** 当天最高 ≥ 开盘 +6%" if u1 else "- 无数据",
         f"- 对照（平开 / 高开日）：{sum(u1b)} / {len(u1b)} = {sum(u1b) / len(u1b):.1%}" if u1b else "",
         "", "## U2 转债高开 +2~3% 后回落到昨收 −3% 接", "",
         f"- 次数 {len(u2)}；当天收盘 {dist([x['r0'] for x in u2])}", f"- 次日最高 {dist([x['h1'] for x in u2])}", f"- 次日收盘 {dist([x['c1'] for x in u2])}"]
    # U3
    res = collections.defaultdict(list)
    for kind, base in (("股票", ROOT / "downloads" / "quotes" / "stock" / "minute_path"), ("转债", ROOT / "downloads" / "quotes" / "cb" / "minute_path")):
        fs = sorted(f for f in base.glob("20*.jsonl") if days[2] <= f.stem <= days[-2])
        for f in fs:
            D = f.stem
            nd = days[days.index(D) + 1] if D in days and days.index(D) + 1 < len(days) else None
            for l in f.open(encoding="utf-8"):
                try:
                    j = json.loads(l)
                except ValueError:
                    continue
                p = j.get("p") or []
                if len(p) < 240:
                    continue
                i0, i1 = TM.index("14:25"), TM.index("14:45")
                lo, ti, ev = None, None, None
                for i in range(i0, min(i1 + 11, 239)):
                    if i <= i1 and (lo is None or p[i] < lo):
                        lo, ti = p[i], i
                    if lo and ti is not None and i - ti <= 10 and p[i] >= lo * 1.015 and i > ti:
                        ev = i
                        break
                res[(kind, "base")].append({"D": D, "code": j["code"], "px": p[i1], "close": p[-1], "nd": nd})
                if ev is not None:
                    res[(kind, "ev")].append({"D": D, "code": j["code"], "px": p[ev], "close": p[-1], "nd": nd})
    # 次日收盘用日线
    need = {(x["code"], x["nd"]) for v in res.values() for x in v if x["nd"]}
    nc = {}
    codes = sorted({k[0] for k in need})
    for i in range(0, len(codes), 300):
        part = codes[i:i + 300]
        syms = [("sh" if cc.startswith(("6", "11")) else "sz") + cc for cc in part]
        c.execute("select symbol, trade_date, close from investment_market.kline_day where is_deleted=0 and trade_date>=%s and symbol in (" + ",".join(["%s"] * len(syms)) + ")",
                  (days[2], *syms))
        for s, d, cl in c.fetchall():
            nc[(s[2:], str(d))] = float(cl) if cl else None
    L += ["", "## U3 尾盘 14:25~14:45 低点后 10 分钟内拉升 ≥1.5%（盘中可执行口径，买点 = 触发那分钟价）", "",
          "| 品种 | 组 | 次数 | 到收盘 | 次日收盘 |", "|---|---|---|---|---|"]
    for kind in ("股票", "转债"):
        ev, bs = res[(kind, "ev")], res[(kind, "base")]
        for nm, xs in (("形态出现后买", ev), ("对照: 14:45 买", bs)):
            if xs:
                L.append(f"| {kind} | {nm} | {len(xs)} | {dist([(x['close'] / x['px'] - 1) * 100 for x in xs])} | "
                         f"{dist([(nc[(x['code'], x['nd'])] / x['px'] - 1) * 100 for x in xs if nc.get((x['code'], x['nd']))])} |")
        if bs:
            L.append(f"| {kind} | 出现率 | {len(ev)} / {len(bs)} = {len(ev) / len(bs):.1%} | | |")
    L += ["", "## 不自信点", "", "- U1 / U2 用日线，不知道盘中先后（U2 可能先冲高再跌到 −3%，接的时候已经是当天第二段）",
          "- U3 分钟路径只覆盖采集名单（股票：近 100 日碰过涨停的 + 导师 / UP 相关票；转债：成交活跃的 56~几百只），不是全市场",
          "- 用户原话针对澳弘转债（单票观察），这里是全市场口径，结论不等于对澳弘成立"]
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
