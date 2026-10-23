# -*- coding: utf-8 -*-
"""cb_minute_backfill.py — 转债历史 1 分钟线回补(通达信历史逐笔聚合; 10/22 用户令: 先落地澳弘近 1 个月, 再给"开盘冲高回落 × 相似日"分布表用)

为什么: 东财分时接口只给近 5 天; 行情库 kline_minute 只有 10/09 起的关注集。通达信历史逐笔可回溯到 2026-01(10/22 实测灵康 01-05 有),
       collect_minute.py 已有"逐笔 → 241 根 1 分钟 OHLC + 转债 10 倍缩放校正 + 与日线对账"的全套函数, 这里只复用、不改它。
落地: downloads/quotes/cb/minute/<代码>/<日>.json(每天一个文件, 已存在跳过 = 幂等); 不写行情库(入库仍归 Java MarketImportService)
限速: 每个债-日约 1~3 次请求(2000 条一页), 请求间隔 ≥2 秒; 只打通达信, 不打东财 / 新浪
用法:
  python cb_minute_backfill.py --code 111024 --days 22               # 近 22 个交易日(≈1 个月)
  python cb_minute_backfill.py --pairs pairs.json                    # [[代码, 日期], ...] 批量(土豆 / 高概率的转债出手日)
"""
import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "market"), str(ROOT / "scripts" / "lib")]
import collect_minute as CM   # noqa: E402

OUT = ROOT / "downloads" / "quotes" / "cb" / "minute"
GAP = 2.0


def daily(code):
    """{日期: {close, high, low, prev}}: 先读本地转债日线, 没有再读行情库"""
    out = {}
    f = ROOT / "downloads" / "quotes" / "daily" / f"{code}.json"
    k = []
    if f.exists():
        k = (json.loads(f.read_text(encoding="utf-8")) or {}).get("klines") or []
    if True:   # 10/22 晚修: 本地 daily 文件只覆盖少数转债(73 个债-日因此 no_daily), 一律以行情库为准合并
        sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
        import manual_backfill as mb
        cur = mb.db().cursor()
        cur.execute("use investment_market")
        cur.execute("select trade_date, close, high, low from kline_day where symbol in (%s, %s) and is_deleted=0 order by trade_date", ("sh" + code, "sz" + code))
        dbk = [{"d": str(d), "c": float(c), "h": float(h), "l": float(l)} for d, c, h, l in cur.fetchall()]
        have = {x["d"] for x in k}
        k = sorted(k + [x for x in dbk if x["d"] not in have], key=lambda x: x["d"])
    for i, x in enumerate(k):
        out[x["d"]] = {"close": x["c"], "high": x["h"], "low": x["l"], "prev": k[i - 1]["c"] if i else None}
    return out


def one(api, code, day, K):
    f = OUT / code / f"{day}.json"
    if f.exists():
        return "skip"
    k = K.get(day)
    nodaily = not k
    if nodaily:   # 10/22 晚: 退市转债行情库里没有日线(幸存者偏差) → 不对账, 价格缩放按转债常识判(逐笔中位 >1000 = 放大了 10 倍), 昨收留空
        k = {"close": None, "high": None, "low": None, "prev": None}
    sym = ("sh" if code.startswith(("11", "5", "6")) else "sz") + code   # 转债: 11x 沪 / 12x 深
    ticks = CM.all_ticks(api, sym, int(day.replace("-", "")))
    time.sleep(GAP)
    if not ticks:
        return "no_ticks"
    if nodaily:
        ps = sorted(x["price"] for x in ticks if x["vol"] > 0)
        sc = 0.1 if ps and ps[len(ps) // 2] > 1000 else 1.0
    else:
        sc = CM.price_scale(ticks, k["close"])
        if not CM.ticks_ok(ticks, k, sc):
            return "mismatch"
    bars = CM.bars_from_ticks(sym, day, ticks, 10, k["prev"], sc)   # 转债 1 手 = 10 张
    first = next((x for x in ticks if x["time"] == "09:25"), None)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"code": code, "day": day, "prev": k["prev"], "no_daily": nodaily, "open_auction": round(first["price"] * sc, 4) if first else None,
                             "bars": [{"t": b["barTime"][11:16], "o": b["open"], "h": b["high"], "l": b["low"], "c": b["close"], "v": b["volume"], "avg": b["avgPrice"]} for b in bars],
                             "src": "tdx_ticks", "made": dt.datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False), encoding="utf-8")
    return "ok(无日线)" if nodaily else "ok"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--code")
    ap.add_argument("--days", type=int, default=22)
    ap.add_argument("--pairs")
    a = ap.parse_args()
    if a.pairs:
        pairs = json.loads(Path(a.pairs).read_text(encoding="utf-8"))
    else:
        K = daily(a.code)
        ds = sorted(d for d in K if d < dt.date.today().isoformat() or dt.datetime.now().hour >= 16)[-a.days:]
        pairs = [[a.code, d] for d in ds]
    api = CM.connect()
    stat, Kc = {}, {}
    for code, day in pairs:
        if code not in Kc:
            Kc[code] = daily(code)
        try:
            r = one(api, code, day, Kc[code])
        except Exception as e:   # noqa: BLE001
            r = "err:" + type(e).__name__
            try:
                api.disconnect()
            except Exception:   # noqa: BLE001
                pass
            api = CM.connect()
        if r == "no_ticks":   # 10/22 实测: 同一台服务器个别日子逐笔为空(10/19、10/21), 换一台再试一次
            try:
                api2 = CM.connect(skip=(getattr(api, "_ip", ""),))
                r = one(api2, code, day, Kc[code]) + "(换服务器)"
                api2.disconnect()
            except Exception as e:   # noqa: BLE001
                r = "no_ticks/换服务器失败:" + type(e).__name__
        stat[r] = stat.get(r, 0) + 1
        print(code, day, r, flush=True)
    api.disconnect()
    print("汇总", stat)


if __name__ == "__main__":
    main()
