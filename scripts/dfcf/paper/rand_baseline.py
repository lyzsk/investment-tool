# -*- coding: utf-8 -*-
"""rand_baseline.py — RAND 抛硬币基准(零 token; 10/18 晚用户定 P0): 每条导师链配一个"随机交易员", 回答"这条链跑赢运气了吗"

做法(只把"买哪只"随机化, 其余全部照抄这条链自己的实际行为 = 最严格的同条件对照):
  1. 读链的实盘账本成交(10/8 起), FIFO 配对成"持仓段": (买入日, 卖出日 or 仍持有, 买入金额)
  2. 每个持仓段的票换成当天候选宇宙里随机一只: 宇宙 = 该导师当日指纹候选池(scripts/tzzb/pools/<日>.json, 缺当天用最近一个更早的);
     UP / 对照组没有池 = 当天全体导师池的并集; 开盘涨幅 > 9% 的票视为买不到, 重抽
  3. 统一口径记盈亏: 买 = 买入日开盘价, 卖 = 卖出日收盘价(仍持有 = 最新收盘), 金额同原段, 费用 = 每笔最低 5 元(万2.5) + 卖出印花税 0.05%
  4. 同一口径也算一遍"链自己选的票"(同方法收益), 和 N 次随机的分布比 → 分位(链排在随机分布的第几百分位; 50% = 和抛硬币一样)
  口径限制: 开盘买 / 收盘卖是近似(链真实成交价不同), 所以只拿"同方法收益"和随机比, 账本真实收益另列参考; 样本天数少时分位只看方向
产物: scripts/dfcf/paper/rand_baseline.json(report.html 的 skill 多维对比读它) + reports/rand_baseline_<日>.md
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/rand_baseline.py [--seeds 500] [--start 2026-10-08]   (check md 每晚跑)
"""
import argparse
import bisect
import datetime as dt
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
import mentors as M   # noqa: E402
import a_rules as AR  # noqa: E402

POOLS = ROOT / "scripts" / "tzzb" / "pools"
INIT = 100000.0


def fee(side, amt):
    return max(5.0, amt * 0.00025) + (amt * 0.0005 if side == "SELL" else 0.0)


def lots_of(book, start):
    """FIFO 配对: [(买入日, 卖出日|None, 代码, 股数, 买入金额)]"""
    open_, out = defaultdict(list), []
    for t in sorted(book.get("trades") or [], key=lambda t: str(t.get("id"))):
        d = str(t.get("id", ""))[:10]
        if d < start or AR.symbol(t["code"]) is None:
            continue
        q = int(t["qty"])
        if t["side"] == "BUY":
            open_[t["code"]].append([d, q, float(t["price"])])
            continue
        while q > 0 and open_[t["code"]]:
            lot = open_[t["code"]][0]
            k = min(q, lot[1])
            out.append((lot[0], d, t["code"], k, k * lot[2]))
            lot[1] -= k
            q -= k
            if lot[1] == 0:
                open_[t["code"]].pop(0)
    for c, ls in open_.items():
        out += [(d, None, c, q, q * p) for d, q, p in ls if q > 0]
    return out


def pools_by_date():
    P = {}
    for f in sorted(POOLS.glob("20??-??-??.json")):
        try:
            J = json.loads(f.read_text(encoding="utf-8")).get("mentors") or {}
        except ValueError:
            continue
        P[f.stem] = {m: [str(x["code"]) for x in (v.get("pool") or [])] for m, v in J.items()}
    return P


def universe(P, keys, d, mid):
    i = bisect.bisect_right(keys, d) - 1
    if i < 0:
        i = 0
    day = P[keys[i]]
    if day.get(mid):
        return day[mid]
    return sorted({c for v in day.values() for c in v})


def load_k(codes, start):
    from kline_db import db
    c = db()
    try:
        cur = c.cursor()
        syms = {AR.symbol(x): x for x in codes if AR.symbol(x)}
        K = defaultdict(dict)
        L = list(syms)
        for i in range(0, len(L), 500):
            part = L[i:i + 500]
            cur.execute(f"select symbol, trade_date, cast(open as double), cast(close as double), cast(pre_close as double) from kline_day "
                        f"where is_deleted=0 and trade_date>=%s and symbol in ({','.join(['%s'] * len(part))})", [start, *part])
            for s, d, o, cl, pc in cur.fetchall():
                K[syms[s]][str(d)] = (o, cl, pc)
        return K
    finally:
        c.close()


def pnl(K, code, bd, sd, amt, last_d):
    k = K.get(code) or {}
    b = k.get(bd)
    s = k.get(sd or last_d) or (k[max(k)] if k else None)
    if not b or not s or not b[0]:
        return None
    q = amt / b[0]
    return q * s[1] - amt - fee("BUY", amt) - (fee("SELL", q * s[1]) if sd else 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=500)
    ap.add_argument("--start", default="2026-10-08")
    a = ap.parse_args()
    P = pools_by_date()
    keys = sorted(P)
    if not keys:
        sys.exit("没有候选池文件")
    chains = [e for e in M.all() if e.get("book")]
    books = {}
    for e in chains:
        try:
            books[e["id"]] = json.loads((HERE / "books" / f"{e['book']}.json").read_text(encoding="utf-8"))
        except OSError:
            pass
    L = {mid: lots_of(b, a.start) for mid, b in books.items()}
    codes = {c for ls in L.values() for x in ls for c in [x[2]]} | {c for d in P.values() for v in d.values() for c in v}
    K = load_k(codes, a.start)
    last_d = max((d for k in K.values() for d in k), default=a.start)
    rng = random.Random(20261018)
    res = {}
    for e in chains:
        mid = e["id"]
        ls = L.get(mid) or []
        if not ls:
            res[mid] = {"name": e.get("display") or mid, "lots": 0}
            continue
        own = [pnl(K, c, bd, sd, amt, last_d) for bd, sd, c, q, amt in ls]
        valid = [i for i, x in enumerate(own) if x is not None]
        own_ret = sum(own[i] for i in valid) / INIT
        draws = []
        for _ in range(a.seeds):
            tot = 0.0
            for i in valid:
                bd, sd, c, q, amt = ls[i]
                U = [x for x in universe(P, keys, bd, mid) if (K.get(x) or {}).get(bd)]
                v = None
                for _try in range(8):
                    if not U:
                        break
                    x = rng.choice(U)
                    o, cl, pc = K[x][bd]
                    if pc and o / pc - 1 > 0.09:   # 开盘近涨停 = 买不到, 重抽
                        continue
                    v = pnl(K, x, bd, sd, amt, last_d)
                    if v is not None:
                        break
                tot += v or 0.0
            draws.append(tot / INIT)
        draws.sort()
        pct = sum(1 for x in draws if x < own_ret) / len(draws)
        nav = (books[mid].get("nav") or [{}])[-1].get("nav")
        res[mid] = {"name": e.get("display") or mid, "lots": len(valid), "own_ret": round(own_ret, 5), "book_ret": round(nav / INIT - 1, 5) if nav else None,
                    "rand_p10": round(draws[len(draws) // 10], 5), "rand_p50": round(draws[len(draws) // 2], 5), "rand_p90": round(draws[len(draws) * 9 // 10], 5),
                    "pct": round(pct, 3)}
    out = {"updated": dt.datetime.now().isoformat(timespec="seconds"), "start": a.start, "last": last_d, "seeds": a.seeds, "chains": res}
    (HERE / "rand_baseline.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    rows = sorted(((v.get("pct", -1), k, v) for k, v in res.items()), reverse=True)
    md = [f"# RAND 抛硬币基准({a.start} ~ {last_d}, {a.seeds} 次随机; rand_baseline.py 机械生成)", "",
          "> 只把\"买哪只\"随机化(当天同一候选宇宙), 买卖日期 / 金额 / 持有期全部照抄链自己; 统一按开盘买、收盘卖记账。分位 = 链的同方法收益排在随机分布的百分位(50% = 和抛硬币一样)。", "",
          "| 链 | 持仓段 | 链(同方法) | 账本实际 | 随机 P10 / P50 / P90 | 分位 |", "|---|---|---|---|---|---|"]
    for p, k, v in rows:
        if not v.get("lots"):
            md.append(f"| {v['name']} | 0 | — | — | — | 无成交 |")
            continue
        md.append(f"| {v['name']} | {v['lots']} | {v['own_ret']:+.2%} | {'—' if v['book_ret'] is None else format(v['book_ret'], '+.2%')} | "
                  f"{v['rand_p10']:+.2%} / {v['rand_p50']:+.2%} / {v['rand_p90']:+.2%} | **{v['pct']:.0%}** |")
    rp = HERE / "reports" / f"rand_baseline_{dt.date.today():%Y%m%d}.md"
    rp.parent.mkdir(exist_ok=True)
    rp.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[4:]))
    print(f"→ {rp.relative_to(ROOT)}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
