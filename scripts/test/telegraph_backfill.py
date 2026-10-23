# -*- coding: utf-8 -*-
"""telegraph_backfill.py — 加红电报点名票历史分时回补(10/23 用户批 (b): 回溯 2026-01-14 起, 让"电报次日"一次有半年样本, 不用攒一两个月)

做什么: 逐个 md 交易日(有「## 加红电报」节的), 找出当天电报点名的 A 股(同 telegraph_validate 的识别口径) + 上证指数,
        行情库 kline_minute 里没有的, 用通达信历史分时补(get_history_minute_time_data: 每分钟价格 + 量, 没有分钟内高低)
存哪: downloads/market/telegraph_min/<日>.json  {代码: [[HH:MM, 价, 量], ...]} —— 只写本地文件, 不写业务库
节奏: 单连接串行, 每次请求后睡 0.15 秒(约 6 次 / 秒以内, 通达信这个量级历来没封过); 连不上换服务器; pid 锁防双开; --stop HH:MM 到点停(幂等, 下次接着补)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/test/telegraph_backfill.py [--since 2026-01-14] [--stop 23:30]
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "test"), str(ROOT / "scripts" / "market"), str(ROOT / "scripts" / "backfill_bilibili")]
OUT = ROOT / "downloads" / "market" / "telegraph_min"
LOCK = ROOT / "scripts" / "temp" / "telegraph_backfill.pid"


def minutes():
    """通达信历史分时 240 个点对应的时刻"""
    out = []
    for h0, m0, n in ((9, 31, 120), (13, 1, 120)):
        t = dt.datetime(2000, 1, 1, h0, m0)
        for _ in range(n):
            out.append(t.strftime("%H:%M"))
            t += dt.timedelta(minutes=1)
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-01-14")
    ap.add_argument("--stop", default="")
    ap.add_argument("--until", default="9999-12-31")
    a = ap.parse_args()
    if LOCK.exists():
        try:
            os.kill(int(LOCK.read_text().strip()), 0)
            print("已在跑, 退出")
            return
        except (OSError, ValueError):
            pass
    LOCK.write_text(str(os.getpid()))
    try:
        import telegraph_validate as TV
        import collect_minute as CM
        OUT.mkdir(parents=True, exist_ok=True)
        con = TV.db()
        cur = con.cursor()
        by_name, by_code = TV.names(cur)
        cur.execute("use investment_market")
        days = sorted(p.stem for p in (ROOT / "md").glob("*/*.md") if a.since <= p.stem <= a.until and len(p.stem) == 10)
        T = minutes()
        api, n_req, n_ok = CM.connect(), 0, 0
        for D in days:
            if a.stop and dt.datetime.now().strftime("%H:%M") >= a.stop:
                print("到点停", a.stop)
                break
            tg = TV.telegraphs(D)
            if not tg:
                continue
            f = OUT / f"{D}.json"
            have = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
            syms = {"sh000001"}
            for _, txt in tg:
                syms |= set(TV.mentions(txt, by_name, by_code))
            todo = []
            for s in sorted(syms):
                if s in have:
                    continue
                cur.execute("select 1 from kline_minute where trade_date=%s and symbol=%s limit 1", (D, s))
                if not cur.fetchone():
                    todo.append(s)
            for s in todo:
                r = None
                for _try in range(3):
                    try:
                        r = api.get_history_minute_time_data(CM.tdx_market(s), s[2:], int(D.replace("-", "")))
                        break
                    except Exception:   # noqa: BLE001
                        api = CM.connect(skip=())
                n_req += 1
                if r and len(r) >= 200:
                    have[s] = [[T[i], float(x["price"]), int(x.get("vol") or 0)] for i, x in enumerate(r[:240])]
                    n_ok += 1
                time.sleep(0.15)
            if todo:
                f.write_text(json.dumps(have, ensure_ascii=False), encoding="utf-8")
            print(D, "点名", len(syms) - 1, "新补", len(todo), "累计请求", n_req, "成功", n_ok, flush=True)
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
