# -*- coding: utf-8 -*-
"""minute_hist.py — 指定票 / 指数的历史 1 分钟线回补(10/21 用户定: 按消费者需要的范围回补, 不做 A 股全量; 零 token)

取法同 scripts/market/collect_minute.py: 个股 / ETF / 转债 = 通达信历史逐笔 → 1 分钟 bar(末笔≈日线收盘 ±1% 校验, 不过换服务器重取);
指数 = 通达信历史分时(get_history_minute_time_data, 240 点, 只有价和量)。只连通达信, 不碰新浪 / 腾讯 / 东财。请求间隔 0.15~0.35 秒随机。
输出: downloads/market/_minute_hist/<symbol>.jsonl(已有的 (日) 跳过, 只追加) + 本次统计打印(请求数 / 成功 / 缺 / 耗时 / 能往前给到哪天)
日线(校验 + 昨收): 个股 downloads/quotes/daily/<代码>.json; 指数 downloads/market/<日>/kline_day.jsonl
用法: python minute_hist.py --codes 002714,159941,601988,111024,605058 --days 60
      python minute_hist.py --index sh000001,sz399006,sh932000,sh000300 --days 60
"""
import argparse
import datetime as dt
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_minute as cm   # noqa: E402

OUT = ROOT / "downloads" / "market" / "_minute_hist"


def daily_stock(code):
    k = json.loads((ROOT / "downloads" / "quotes" / "daily" / f"{code}.json").read_text(encoding="utf-8"))["klines"]
    out, prev = {}, None
    for x in k:
        out[x["d"]] = {"close": x["c"], "high": x["h"], "low": x["l"], "preClose": prev}
        prev = x["c"]
    return out


def done_days(sym):
    f = OUT / f"{sym}.jsonl"
    s = set()
    if f.exists():
        for l in f.open(encoding="utf-8"):
            try:
                s.add(json.loads(l)["tradeDate"])
            except (ValueError, KeyError):
                pass
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default="")
    ap.add_argument("--index", default="")
    ap.add_argument("--days", type=int, default=60)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    days = sorted(p.parent.name for p in (ROOT / "downloads" / "market").glob("20*/kline_day.jsonl"))
    hist = []
    for f in sorted((ROOT / "downloads" / "quotes" / "daily").glob("002714.json")):
        hist = [x["d"] for x in json.loads(f.read_text(encoding="utf-8"))["klines"]]
    tdays = sorted(set(hist) | set(days))[-a.days:]
    api, n_req, n_ok, n_miss, t0, first = cm.connect(), 0, 0, 0, time.time(), {}
    try:
        for code in [c for c in a.codes.split(",") if c]:
            sym = cm.symbol_of_code(code)
            dm, have = daily_stock(code), done_days(sym)
            with (OUT / f"{sym}.jsonl").open("a", encoding="utf-8") as fh:
                for d in tdays:
                    if d in have or d not in dm:
                        continue
                    k, ymd = dm[d], int(d.replace("-", ""))
                    b = []
                    for _ in range(2):
                        try:
                            ticks = cm.all_ticks(api, sym, ymd)
                        except Exception:   # noqa: BLE001
                            ticks = []
                        sc = cm.price_scale(ticks, k["close"]) if ticks else 1.0
                        if ticks and cm.ticks_ok(ticks, k, sc):
                            b = cm.bars_from_ticks(sym, d, ticks, 100, k["preClose"], sc)
                            break
                        try:
                            api.disconnect()
                        except Exception:   # noqa: BLE001
                            pass
                        api = cm.connect(skip=(getattr(api, "_ip", None),))
                    n_req += 1
                    if b:
                        n_ok += 1
                        first[sym] = min(first.get(sym, d), d)
                        for r in b:
                            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    else:
                        n_miss += 1
                    time.sleep(random.uniform(0.15, 0.35))
            print(f"{sym}: 累计成功到 {first.get(sym)} 起", flush=True)
        for sym in [s for s in a.index.split(",") if s]:
            have = done_days(sym)
            with (OUT / f"{sym}.jsonl").open("a", encoding="utf-8") as fh:
                for d in tdays:
                    if d in have:
                        continue
                    try:
                        b = cm.bars_from_minute_time(api, sym, d, d.replace("-", ""))
                    except Exception:   # noqa: BLE001
                        b = []
                    n_req += 1
                    if b:
                        n_ok += 1
                        first[sym] = min(first.get(sym, d), d)
                        for r in b:
                            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    else:
                        n_miss += 1
                    time.sleep(random.uniform(0.15, 0.35))
            print(f"{sym}: 累计成功到 {first.get(sym)} 起", flush=True)
    finally:
        try:
            api.disconnect()
        except Exception:   # noqa: BLE001
            pass
    print(f"完成: 请求 {n_req} 次(按 票×日 计, 逐笔分页另算), 成功 {n_ok}, 缺 {n_miss}, 用时 {time.time() - t0:.0f}s; 窗口 {tdays[0]}~{tdays[-1]}")


if __name__ == "__main__":
    main()
