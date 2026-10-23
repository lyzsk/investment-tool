# -*- coding: utf-8 -*-
"""cb_minute_universe.py — 全市场转债近 N 个交易日 1 分钟价量路径(通达信历史分时; 10/22 晚用户令"现有资源能做的相似度都做")

为什么: 分钟级相似(盘中走到此刻像历史上哪几天)需要大样本; 行情库分钟线只有 10/09 起关注集, cb_minute_backfill 只补了土豆 / 高概率出手日。
源: pytdx get_history_minute_time_data(每只每天 1 次请求, 240 点 = 每分钟价 + 量; 没有高低, 足够做路径相似); 间隔 0.25~0.4 秒随机
落地: downloads/quotes/cb/minute_path/<日>.jsonl, 一行一只 {code, d, prev, p: [240 个价], v: [240 个量]}; 当天文件已存在的代码跳过(幂等)
价格缩放: 转债通达信放大 10 倍 → 用当日日线收盘校正(行情库); 对不上(末价偏差 >1%)丢弃
用法: python cb_minute_universe.py [--days 60] [--codes 111024,113610]
"""
import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "market"), str(ROOT / "scripts" / "backfill_bilibili")]
import collect_minute as CM   # noqa: E402
import manual_backfill as mb   # noqa: E402

OUT = ROOT / "downloads" / "quotes" / "cb" / "minute_path"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--codes")
    a = ap.parse_args()
    cur = mb.db().cursor()
    cur.execute("use investment_market")
    cur.execute("select distinct trade_date from kline_day where symbol='sh000001' order by trade_date desc limit %s", (a.days,))
    days = sorted(str(x[0]) for x in cur.fetchall())
    cur.execute("select symbol from security_master where sec_type='CB'")
    syms = [s for (s,) in cur.fetchall() if s[:2] in ("sh", "sz")]
    if a.codes:
        want = set(a.codes.split(","))
        syms = [s for s in syms if s[2:] in want]
    cur.execute(f"select symbol, trade_date, close from kline_day where is_deleted=0 and trade_date >= %s and symbol in ({','.join(['%s'] * len(syms))})", (days[0], *syms))
    C = {}
    for s, d, c in cur.fetchall():
        C[(s, str(d))] = float(c)
    cur.execute(f"select symbol, trade_date, close from kline_day where is_deleted=0 and trade_date < %s and trade_date >= date_sub(%s, interval 15 day) and symbol in ({','.join(['%s'] * len(syms))})", (days[0], days[0], *syms))
    for s, d, c in cur.fetchall():
        C[(s, str(d))] = float(c)
    OUT.mkdir(parents=True, exist_ok=True)
    api = CM.connect()
    stat = {}
    for d in days:
        f = OUT / f"{d}.jsonl"
        done = {json.loads(l)["code"] for l in f.read_text(encoding="utf-8").splitlines()} if f.exists() else set()
        dprev = sorted(x for (s_, x) in C if x < d)
        with f.open("a", encoding="utf-8") as fo:
            for s in syms:
                if s[2:] in done or (s, d) not in C:
                    continue
                try:
                    r = api.get_history_minute_time_data(CM.tdx_market(s), s[2:], int(d.replace("-", "")))
                except Exception:   # noqa: BLE001
                    try:
                        api.disconnect()
                    except Exception:   # noqa: BLE001
                        pass
                    api = CM.connect()
                    r = None
                time.sleep(random.uniform(0.25, 0.4))
                if not r or len(r) < 200:
                    stat["空"] = stat.get("空", 0) + 1
                    continue
                ps = [float(x["price"]) for x in r]
                close = C[(s, d)]
                ratio = ps[-1] / close   # 10/22 实测转债历史分时放大 100 倍(逐笔是 10 倍), 按 10 的幂次就近校正
                sc = next((10 ** -k for k in range(0, 4) if 0.9 < ratio / 10 ** k < 1.1), 1.0)
                ps = [round(p * sc, 3) for p in ps]
                if abs(ps[-1] / close - 1) > 0.01:
                    stat["对不上"] = stat.get("对不上", 0) + 1
                    continue
                prevs = [C[(s, x)] for x in dprev if (s, x) in C]
                fo.write(json.dumps({"code": s[2:], "d": d, "prev": prevs[-1] if prevs else None, "p": ps, "v": [int(x["vol"]) for x in r]}, ensure_ascii=False) + "\n")
                stat["ok"] = stat.get("ok", 0) + 1
        print(d, stat, flush=True)
    print("完成", stat)


if __name__ == "__main__":
    main()
