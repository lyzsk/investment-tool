"""拉取日线到本地缓存(只读 SELECT). 股票池: security_master 中 STOCK 且 board_type in (MAIN,GEM,STAR); 北交所暂不纳入.
用法: python load_daily.py [start=2023-06-01] [end=2026-10-23]
输出: C:/Users/admin/dev/_kline_extract/cache/kline_day_{start}_{end}.parquet
"""
import sys
import time
from pathlib import Path

import pandas as pd

import db_ro

CACHE = Path("C:/Users/admin/dev/_kline_extract/cache")


def main(start="2023-06-01", end="2026-10-23"):
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"kline_day_{start}_{end}.parquet"
    sm = db_ro.query("select symbol, name, board_type, is_st, list_date from security_master "
                     "where is_deleted=0 and sec_type='STOCK' and board_type in ('MAIN','GEM','STAR')")
    syms = sm["symbol"].tolist()
    print("symbols", len(syms))
    parts = []
    t0 = time.time()
    B = 300
    for i in range(0, len(syms), B):
        batch = syms[i:i + B]
        ph = ",".join(["%s"] * len(batch))
        df = db_ro.query(
            f"select symbol, trade_date, open, high, low, close, pre_close, volume, amount, turnover_rate, "
            f"limit_up, limit_down from kline_day where is_deleted=0 and trade_date between %s and %s "
            f"and symbol in ({ph})", [start, end] + batch)
        parts.append(df)
        print(i, len(df), round(time.time() - t0, 1), flush=True)
    d = pd.concat(parts, ignore_index=True)
    for c in ["open", "high", "low", "close", "pre_close", "amount", "turnover_rate", "limit_up", "limit_down"]:
        d[c] = pd.to_numeric(d[c], errors="coerce").astype("float64")
    d["volume"] = pd.to_numeric(d["volume"], errors="coerce").astype("float64")
    d["trade_date"] = pd.to_datetime(d["trade_date"])
    d = d.merge(sm, on="symbol", how="left")
    d = d.sort_values(["symbol", "trade_date"]).drop_duplicates(["symbol", "trade_date"], keep="last")
    d.to_parquet(out)
    print("saved", out, len(d))


if __name__ == "__main__":
    main(*sys.argv[1:])
