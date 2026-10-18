# -*- coding: utf-8 -*-
"""fetch_industry.py — 全 A 股东财行业一次性快照(席位画像"常做板块"用; 2026-10-15 建)
数据: 东财 datacenter-web RPT_VALUEANALYSIS_DET(个股估值表, 带 BOARD_NAME=东财行业), 按交易日整批分页 500/页, 约 11~12 次请求
请求层: scripts/lib/req_guard.py(源 em_datacenter: 间隔 2.5s±抖动 ≈0.4 次/秒, 熔断/日预算); 失败显式非 0, 不编数据
口径: 当前行业(非历史时点行业), 用于统计"常做板块"足够; 本地已有快照则不再请求(--force 重抓)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/lhb/fetch_industry.py [--date yyyy-MM-dd] [--force]
产物: downloads/lhb/_industry/industry_em.json  {date, fetched_at, count, map:{code:{name,board}}}
"""
import argparse, json, sys, time, random, datetime as dt
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from req_guard import gfetch  # noqa: E402

OUT = ROOT / "downloads" / "lhb" / "_industry" / "industry_em.json"
API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
       "Referer": "https://data.eastmoney.com/gzfx/list.html", "Accept-Language": "zh-CN,zh;q=0.9"}


def get(date, page):
    flt = quote(f"(TRADE_DATE='{date}')")
    url = (f"{API}?reportName=RPT_VALUEANALYSIS_DET&columns=SECURITY_CODE,SECURITY_NAME_ABBR,BOARD_NAME,BOARD_CODE,TRADE_DATE"
           f"&filter={flt}&pageNumber={page}&pageSize=500&sortColumns=SECURITY_CODE&sortTypes=1&source=WEB&client=WEB")
    for a in range(3):
        if a:
            time.sleep(8 * 3 ** (a - 1) * (0.75 + random.random() * 0.5))
        r = gfetch(url, headers=HDR, timeout=20)
        if r.status == 200:
            return r.json()
        print(f"  HTTP {r.status} 第 {a + 1} 次", flush=True)
    raise RuntimeError(f"RPT_VALUEANALYSIS_DET {date} p{page} 连续失败")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if OUT.exists() and not a.force:
        j = json.loads(OUT.read_text(encoding="utf-8"))
        print(f"已有快照 {j['date']} {j['count']} 只, 不请求")
        return 0
    date = a.date or (dt.date.today() - dt.timedelta(days=1)).isoformat()
    m, pages, page = {}, 1, 1
    while page <= pages:
        j = get(date, page)
        if not j.get("success"):
            print("返回失败:", j.get("code"), j.get("message"))
            return 1
        pages = j["result"]["pages"]
        for r in j["result"]["data"]:
            m[r["SECURITY_CODE"]] = {"name": r["SECURITY_NAME_ABBR"], "board": r.get("BOARD_NAME")}
        print(f"  p{page}/{pages}: 累计 {len(m)}", flush=True)
        page += 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"date": date, "fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "source": "em RPT_VALUEANALYSIS_DET",
                               "count": len(m), "map": m}, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"写 {OUT.relative_to(ROOT)}: {len(m)} 只, 请求 {pages} 次")
    return 0


if __name__ == "__main__":
    sys.exit(main())
