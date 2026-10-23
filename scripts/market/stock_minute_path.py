# -*- coding: utf-8 -*-
"""stock_minute_path.py — 股票近 N 个交易日 1 分钟价量路径(通达信历史分时; 10/22 晚用户令: 股票分钟级相似 / 拓扑要用)

为什么: 刘忆青 / 芷影是股票线, 分钟级相似(开盘到此刻走法像历史上哪几天)要股票的分钟路径; 行情库分钟线只有 10/09 起关注集
范围(用户 10/22 21:0x 定, 分两期):
  第一期 30 天: 刘忆青 + 芷影历史票 + 近 30 日涨停过 + 3 位 UP 近 30 日提到(scripts/temp/stock_minute_phase1.json, 937 只)
  第二期 60 天: TOP10 日均收益率导师历史票 + 3 位 UP 近 60 日提到(stock_minute_phase2.json, 1354 只)
源: pytdx get_history_minute_time_data(每只每天 1 次, 240 点 = 每分钟价 + 量; 10/22 实测这台服务器 1 分钟 K 线批量接口返回空, 只能用这个)
节奏: 串行一个连接, 间隔 0.25~0.4 秒随机; **从最近一天往回补**(中途停了最近的天数也是全的); --stop HH:MM 到点就停(下次接着补, 幂等)
价格校验: 末价和行情库当日收盘差 >1% 丢弃(按 10 的幂次就近校正, 同转债版)
防双开: pid 锁 scripts/temp/stock_minute_path.pid(10/22 晚转债回补双开写重了 3563 行的教训)
落地: downloads/quotes/stock/minute_path/<日>.jsonl, 一行一只 {code, d, prev, p: [240], v: [240]}; 当天文件里已有的代码跳过
用法: python stock_minute_path.py --codes-file scripts/temp/stock_minute_phase1.json --days 30 [--stop 07:00]
"""
import argparse
import datetime as dt
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "market"), str(ROOT / "scripts" / "backfill_bilibili")]
import collect_minute as CM   # noqa: E402
import manual_backfill as mb   # noqa: E402

OUT = ROOT / "downloads" / "quotes" / "stock" / "minute_path"
LOCK = ROOT / "scripts" / "temp" / "stock_minute_path.pid"


def lock():
    import psutil
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text().strip() or 0)
            if pid != os.getpid() and "stock_minute_path" in " ".join(psutil.Process(pid).cmdline()):
                sys.exit(f"已在跑(pid {pid}), 本进程退出")
        except (ValueError, psutil.Error):
            pass
    LOCK.write_text(str(os.getpid()))


def sym(c):
    return ("sh" if c.startswith("6") else "sz") + c


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes-file", required=True)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--stop", default="")
    a = ap.parse_args()
    lock()
    codes = [c for c in json.loads(Path(a.codes_file).read_text(encoding="utf-8")) if c[:1] in "036"]   # 北交所跳过
    cur = mb.db().cursor()
    cur.execute("use investment_market")
    cur.execute("select distinct trade_date from kline_day where symbol='sh000001' order by trade_date desc limit %s", (a.days + 1,))
    alld = sorted(str(x[0]) for x in cur.fetchall())
    days = alld[1:][::-1]   # 最近一天在前; alld[0] 只用来取第一天的昨收
    syms = [sym(c) for c in codes]
    C = {}
    for i in range(0, len(syms), 500):
        part = syms[i:i + 500]
        cur.execute(f"select symbol, trade_date, close from kline_day where is_deleted=0 and trade_date >= %s and symbol in ({','.join(['%s'] * len(part))})", (alld[0], *part))
        for s, d, c in cur.fetchall():
            C[(s[2:], str(d))] = float(c)
    OUT.mkdir(parents=True, exist_ok=True)
    api = CM.connect()
    stat = {"ok": 0, "空": 0, "对不上": 0, "无日线": 0}
    t0 = time.time()
    try:
        for di, d in enumerate(days):
            f = OUT / f"{d}.jsonl"
            done = {json.loads(l)["code"] for l in f.read_text(encoding="utf-8").splitlines() if l.strip()} if f.exists() else set()
            prevd = alld[alld.index(d) - 1]
            with f.open("a", encoding="utf-8") as fo:
                for c in codes:
                    if a.stop and dt.datetime.now().strftime("%H:%M") >= a.stop and dt.datetime.now().hour < 12:
                        print(f"到 {a.stop} 停", stat, flush=True)
                        return
                    if c in done:
                        continue
                    if (c, d) not in C:
                        stat["无日线"] += 1   # 停牌 / 未上市
                        continue
                    try:
                        r = api.get_history_minute_time_data(CM.tdx_market(sym(c)), c, int(d.replace("-", "")))
                    except Exception:   # noqa: BLE001
                        try:
                            api.disconnect()
                        except Exception:   # noqa: BLE001
                            pass
                        api = CM.connect()
                        r = None
                    time.sleep(random.uniform(0.25, 0.4))
                    if not r or len(r) < 200:
                        stat["空"] += 1
                        continue
                    ps = [float(x["price"]) for x in r]
                    close = C[(c, d)]
                    ratio = ps[-1] / close if close else 0
                    sc = next((10 ** -k for k in range(0, 4) if 0.9 < ratio / 10 ** k < 1.1), 1.0)
                    ps = [round(p * sc, 3) for p in ps]
                    if not close or abs(ps[-1] / close - 1) > 0.01:
                        # 10/22 22:0x 实测: 批量跑到第 10 天后整批"对不上"(单独取同一只同一天完全对得上) = pytdx 连接错位, 读到的是上一个请求的回包
                        # → 立刻断开重连再取一次; 连续 3 只对不上换一台服务器
                        stat["对不上"] += 1
                        bad = getattr(api, "_bad", 0) + 1
                        try:
                            api.disconnect()
                        except Exception:   # noqa: BLE001
                            pass
                        api = CM.connect(skip=(getattr(api, "_ip", ""),) if bad >= 3 else ())
                        api._bad = 0 if bad >= 3 else bad
                        r = api.get_history_minute_time_data(CM.tdx_market(sym(c)), c, int(d.replace("-", "")))
                        time.sleep(random.uniform(0.25, 0.4))
                        if not r or len(r) < 200:
                            continue
                        ps = [float(x["price"]) for x in r]
                        ratio = ps[-1] / close if close else 0
                        sc = next((10 ** -k for k in range(0, 4) if 0.9 < ratio / 10 ** k < 1.1), 1.0)
                        ps = [round(p * sc, 3) for p in ps]
                        if abs(ps[-1] / close - 1) > 0.01:
                            continue
                        stat["对不上"] -= 1
                        stat["重连后对上"] = stat.get("重连后对上", 0) + 1
                    else:
                        api._bad = 0
                    fo.write(json.dumps({"code": c, "d": d, "prev": C.get((c, prevd)), "p": ps, "v": [int(x["vol"]) for x in r]}, ensure_ascii=False) + "\n")
                    stat["ok"] += 1
            print(d, f"第 {di + 1}/{len(days)} 天", stat, f"{(time.time() - t0) / 60:.0f} 分钟", flush=True)
        print("完成", stat, flush=True)
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
