# -*- coding: utf-8 -*-
"""book_capacity.py — 3 秒盘口(新浪五档批量)单请求最大只数压测(10/23 14:2x 用户令; 盘后跑, 零 token)

做什么: 复用 collect_book.fetch(和盘中同一个请求 / 解析), 名单从当日 kline_day 成交额前列取(都在交易、不会因停牌返回空);
       阶梯 50 → 80 → 120 → 160 → 200 → 300 只, 每档每 3 秒一次跑 5 分钟, 记每轮耗时 / URL 长度 / 返回只数 / HTTP 错误;
       任何一档出现 403 / 456 / 返回空 / 返回只数不齐 → 立刻停、记阈值、不再加压(防把盘中在用的源测封);
       之后在最后一个通过档上测"拆两个请求 串行 / 并发"。
只读: 不改 collect_book.py / chain_flags, 不写行情目录; 结果 results/inv-stock/test/book_capacity_<日>.json + 打印
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/test/book_capacity.py [--date 2026-10-23] [--secs 300]
"""
import argparse
import concurrent.futures as cf
import json
import statistics as st
import sys
import time
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "market"), str(ROOT / "scripts" / "backfill_bilibili")]
import collect_book as CB   # noqa: E402
import manual_backfill as mb   # noqa: E402

TIERS = [50, 80, 120, 160, 200, 300]


def universe(D, n):
    c = mb.db().cursor()
    c.execute("use investment_market")
    c.execute("select k.symbol from kline_day k join security_master s on s.symbol=k.symbol and s.sec_type='STOCK' "
              "where k.trade_date=%s and k.is_deleted=0 and k.volume>0 and (k.symbol like 'sh6%%' or k.symbol like 'sz0%%' or k.symbol like 'sz3%%') "
              "order by k.amount desc limit %s", (D, n))
    return [r[0] for r in c.fetchall()]


def one(syms):
    t0 = time.time()
    try:
        out = CB.fetch(syms)
        return {"ok": True, "secs": time.time() - t0, "n": len(out)}
    except urllib.error.HTTPError as e:
        return {"ok": False, "secs": time.time() - t0, "n": 0, "err": f"HTTP {e.code}"}
    except Exception as e:   # noqa: BLE001
        return {"ok": False, "secs": time.time() - t0, "n": 0, "err": repr(e)[:120]}


def tier(syms, secs, mode="single"):
    rs, bad = [], None
    end = time.time() + secs
    while time.time() < end:
        t0 = time.time()
        if mode == "single":
            r = one(syms)
        else:
            h = len(syms) // 2
            parts = [syms[:h], syms[h:]]
            if mode == "split_serial":
                rr = [one(p) for p in parts]
            else:
                with cf.ThreadPoolExecutor(2) as ex:
                    rr = list(ex.map(one, parts))
            r = {"ok": all(x["ok"] for x in rr), "secs": time.time() - t0, "n": sum(x["n"] for x in rr), "err": "; ".join(x.get("err", "") for x in rr if x.get("err"))}
        rs.append(r)
        if not r["ok"] or r["n"] == 0 or r["n"] < len(syms):
            bad = r
            break
        time.sleep(max(0.0, CB.STEP - (time.time() - t0)))
    s = sorted(x["secs"] for x in rs)
    return {"mode": mode, "n_req": len(syms), "rounds": len(rs), "url_len": len("https://hq.sinajs.cn/list=" + ",".join(syms)),
            "p50": round(st.median(s), 3), "p95": round(s[min(len(s) - 1, int(len(s) * 0.95))], 3), "max": round(s[-1], 3),
            "min_returned": min(x["n"] for x in rs), "bad": bad}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-10-23")
    ap.add_argument("--secs", type=int, default=300)
    a = ap.parse_args()
    U = universe(a.date, max(TIERS))
    print(f"名单池 {len(U)} 只(当日成交额前列)", flush=True)
    res, passed = [], None
    for n in TIERS:
        r = tier(U[:n], a.secs)
        res.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
        if r["bad"]:
            print(f"!! {n} 只出问题, 停止加压: {r['bad']}", flush=True)
            break
        passed = n
    if passed:
        for mode in ("split_serial", "split_parallel"):
            r = tier(U[:passed], min(a.secs, 120), mode)
            res.append(r)
            print(json.dumps(r, ensure_ascii=False), flush=True)
            if r["bad"]:
                break
    out = ROOT / "results" / "inv-stock" / "test" / f"book_capacity_{a.date.replace('-', '')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"date": a.date, "passed_max": passed, "tiers": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("→", out)


if __name__ == "__main__":
    main()
