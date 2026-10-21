# -*- coding: utf-8 -*-
"""backfill_global_daily.py — 外盘日线历史回补(10/20 晚 市况改造 R6, 用户批; 给相似日检索补外盘特征)

源: 新浪(一个品种一次请求取全部历史, 每次间隔 3~5 秒随机; stooq 有浏览器校验, 不用)
  美股指数 / ETF  US_MinKService.getDailyK   .ndx 纳指100 / .inx 标普500 / ashr / fxi / kweb(恒生科技替代) / ewy(KOSPI 替代) / ewj(日经替代)
  外盘期货连续   GlobalFuturesService.getGlobalFuturesDailyKLine   NQ 小纳指 / ES 小标普 / CHA50CFD A50 / NKD 日经期货 / HSI 恒指期货
产物: downloads/market/history/global/<键>.jsonl 每行 {d, o, h, l, c}(按日期去重, 幂等; 每次全量覆盖)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/market/backfill_global_daily.py [--only NQ,ndx]
之后: 每天 07:15 的外围收盘(collect_global)会采当日值; 本脚本每周跑一次补洞即可
"""
import argparse
import json
import random
import re
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "downloads" / "market" / "history" / "global"
US = {"ndx": ".ndx", "spx": ".inx", "ashr": "ashr", "fxi": "fxi", "kweb": "kweb", "ewy": "ewy", "ewj": "ewj"}
FUT = {"NQ": "NQ", "ES": "ES", "A50": "CHA50CFD", "NKD": "NKD", "HSI": "HSI"}
UA = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def get(url):
    txt = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read().decode("utf-8", errors="replace")
    m = re.search(r"\((\[.*\])\)", txt, re.S)
    if not m:
        raise ValueError(f"无数据: {txt[:80]}")
    return json.loads(m.group(1))


def fetch(key):
    if key in US:
        rows = get(f"https://stock.finance.sina.com.cn/usstock/api/jsonp_v2.php/var%20x=/US_MinKService.getDailyK?symbol={US[key]}")
        return [{"d": r["d"], "o": float(r["o"]), "h": float(r["h"]), "l": float(r["l"]), "c": float(r["c"])} for r in rows]
    rows = get(f"https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20x=/GlobalFuturesService.getGlobalFuturesDailyKLine?symbol={FUT[key]}")
    return [{"d": r["date"], "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"])} for r in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    a = ap.parse_args()
    keys = a.only.split(",") if a.only else list(US) + list(FUT)
    OUT.mkdir(parents=True, exist_ok=True)
    for i, k in enumerate(keys):
        if i:
            time.sleep(random.uniform(3, 5))
        try:
            rows = {r["d"]: r for r in fetch(k) if r["c"] > 0}
            (OUT / f"{k}.jsonl").write_text("\n".join(json.dumps(rows[d]) for d in sorted(rows)) + "\n", encoding="utf-8")
            ds = sorted(rows)
            print(f"{k}: {len(ds)} 根 {ds[0]}~{ds[-1]}")
        except Exception as e:   # noqa: BLE001  一个失败不拖垮其他
            print(f"{k}: 失败 {e}")


if __name__ == "__main__":
    main()
