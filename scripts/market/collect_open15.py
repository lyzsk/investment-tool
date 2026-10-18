# -*- coding: utf-8 -*-
"""collect_open15.py — 全市场开盘前 15 分钟分时(10/16 晚用户批: 研究导师选股要竞价/开盘数据, 只存关注集不够; 往后每天自己攒样本)
源: 通达信 get_history_minute_time_data(每只 1 次请求, 240 点=09:31~11:30+13:01~15:00 的每分钟价+量), 只留 09:31~09:45 共 15 点;
    竞价(09:25)另有行情库 call_auction(10/12 起)。范围=当日 kline_day.jsonl 里有成交的全部 A 股/ETF(不含指数/转债), 约 5000+ 只
输出: downloads/market/<日>/open15_minute.jsonl  {symbol, tradeDate, t:"09:31".., price, vol(股)} + DONE_open15(幂等; --force 重做)
      暂不入库(用户问"要建 DB 吗": 先文件攒, 需要 SQL 查询时再建表 + Java 导入)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/market/collect_open15.py [--date YYYY-MM-DD] [--limit N] [--force]
请求节奏: 每只间隔 0.15~0.25s 随机(10/17 M1: 原 0.05~0.12s ≈10 次/秒); 连接断=重连; 单只失败记缺失不阻断
10/17 健壮性 M1: ①价格缩放=collect_minute.price_scale(用 240 点末价比日线收盘; ETF/3 位小数品种通达信放大 10 倍)
  ②校验=缩放后 240 点全部落在当日日线 [最低×0.99, 最高×1.01] 且末价≈收盘 ±1%, 不过=重连重取一次, 仍不过记'丢弃'(防流错位串票)
  ③缺失+丢弃 >2% 不写 DONE_open15(写 PARTIAL_open15, 下次自动重做), 输出按市场统计
"""
import argparse, datetime as dt, json, random, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_minute as cm   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    day = a.date or sorted(d.name for d in cm.MARKET.iterdir() if (d / "kline_day.jsonl").exists())[-1]
    out = cm.MARKET / day
    if (out / "DONE_open15").exists() and not a.force:
        print(f"OPEN15 {day} 已有 DONE_open15, 跳过"); return 0
    sec = {r["symbol"]: r for r in cm.read_jsonl(out / "security_master.jsonl")}
    kd = {k["symbol"]: k for k in cm.read_jsonl(out / "kline_day.jsonl")}
    syms = [k["symbol"] for k in cm.read_jsonl(out / "kline_day.jsonl")
            if (k.get("volume") or 0) > 0 and sec.get(k["symbol"], {}).get("secType") in ("STOCK", "ETF")]
    if a.limit:
        syms = syms[:a.limit]
    ymd = int(day.replace("-", ""))
    api, rows, miss, bad, t0 = cm.connect(ymd), [], [], [], time.time()
    labels = cm.LABELS[1:16]   # 09:31..09:45
    try:
        for i, sym in enumerate(syms, 1):
            try:
                k = kd.get(sym) or {}
                for _try in range(2):
                    r = api.get_history_minute_time_data(cm.tdx_market(sym), sym[2:], ymd)
                    if not r or len(r) < 200:
                        break
                    pts = [{"price": x["price"], "vol": x["vol"]} for x in r]
                    sc = cm.price_scale(pts, k.get("close")) if k.get("close") else 1.0
                    if not k.get("close") or cm.ticks_ok(pts, k, sc):
                        break
                    try:
                        api.disconnect()
                    except Exception:   # noqa: BLE001
                        pass
                    api = cm.connect(ymd)
                    r = "BAD"
                if not r or (r != "BAD" and len(r) < 200):
                    miss.append(sym)
                elif r == "BAD":
                    bad.append(sym)   # 两次都对不上日线 = 疑流错位串票, 丢弃不写
                else:
                    unit = 100
                    for lab, x in zip(labels, r[:15]):
                        rows.append({"symbol": sym, "tradeDate": day, "t": lab, "price": round(x["price"] * sc, 4), "vol": int(x["vol"]) * unit})
            except Exception:   # noqa: BLE001
                miss.append(sym)
                try:
                    api.disconnect()
                except Exception:   # noqa: BLE001
                    pass
                api = cm.connect(ymd)
            time.sleep(random.uniform(0.15, 0.25))
            if i % 1000 == 0:
                cm.log(f"OPEN15 进度 {i}/{len(syms)} 缺 {len(miss)}")
    finally:
        try:
            api.disconnect()
        except Exception:   # noqa: BLE001
            pass
    cm.write_jsonl(out / "open15_minute.jsonl", rows)
    lost = len(miss) + len(bad)
    by_mkt = {}
    for s in miss + bad:
        by_mkt[s[:2]] = by_mkt.get(s[:2], 0) + 1
    info = {"at": dt.datetime.now().isoformat(), "symbols": len(syms), "rows": len(rows), "miss": len(miss), "bad": len(bad), "lostByMarket": by_mkt}
    ok = not syms or lost <= 0.02 * len(syms)
    if not a.limit:
        if ok:
            (out / "DONE_open15").write_text(json.dumps(info, ensure_ascii=False))
            (out / "PARTIAL_open15").unlink(missing_ok=True)
        else:
            (out / "PARTIAL_open15").write_text(json.dumps(info, ensure_ascii=False))
    print(f"OPEN15 {day}: {len(syms)} 只, 写 {len(rows)} 行, 缺 {len(miss)}, 对不上日线丢弃 {len(bad)}(按市场 {by_mkt}), 用时 {time.time() - t0:.0f}s"
          + ("" if ok else " → 缺失+丢弃 >2%, 不写 DONE(PARTIAL_open15), 下次重做"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
