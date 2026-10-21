# -*- coding: utf-8 -*-
"""cixin_local.py — 次新股区间跌幅榜·本地备源(10/17 A12; 零网络请求, 只读行情库)
scan.mjs 的「次新区间跌幅榜」主源=东财 clist 板块 BK0959(f24=60 日涨跌幅), 东财单源, 被封时整榜缺(TODO B3 已知缺口)。
备源: 本地行情库 investment_market(收盘入库, 新浪主/东财备): security_master.list_date 近 365 天的 A 股 + kline_day 收盘价
  60 日涨跌 = 最新收盘 / 60 个交易日前收盘 − 1(上市不足 60 个交易日 = 对上市首日收盘; 与东财 f24 口径近似, 不完全相同)
  今日涨跌 = 最新收盘 / 昨收 − 1; 数据日 = 行情库最新交易日(盘前/盘中跑 = T-1 收盘口径, 输出里标注)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/quotes/cixin_local.py [--top 30]
输出: stdout 一行 JSON {"asof": "yyyy-MM-dd", "n": 次新总数, "rows": [{code,name,list_date,pct60,pct_today}]}; 出口 0=ok 1=失败
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def db():
    import pymysql
    yml = (ROOT / "inv-admin/src/main/resources/application.yml").read_text(encoding="utf-8")
    pw = re.search(r"password:\s*\"?([^\"\r\n]+)", yml).group(1).strip()
    return pymysql.connect(host="localhost", port=3306, user="root", password=pw, database="investment_market", charset="utf8mb4")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--live", action="store_true", help="盘中: 现价用新浪批量实时价(scan.mjs 盘中兜底用)")
    a = ap.parse_args()
    cur = db().cursor()
    cur.execute("select max(trade_date) from kline_day where is_deleted=0")
    asof = cur.fetchone()[0]
    since = asof - dt.timedelta(days=365)
    cur.execute("select symbol, code, name, list_date from security_master where sec_type='STOCK' and is_deleted=0 and delist_date is null "
                "and list_date is not null and list_date > %s and list_date <= %s", (since, asof))
    sec = {s: (c, n, ld) for s, c, n, ld in cur.fetchall()}
    if not sec:
        raise RuntimeError("行情库无近一年上市的 A 股(list_date 缺?)")
    ph = ",".join(["%s"] * len(sec))
    cur.execute(f"select symbol, trade_date, close, pre_close from kline_day where is_deleted=0 and symbol in ({ph}) and trade_date <= %s "
                f"order by symbol, trade_date", (*sec, asof))
    bars = {}
    for s, d, c, pc in cur.fetchall():
        bars.setdefault(s, []).append((d, float(c or 0), float(pc or 0)))
    rows = []
    for s, ks in bars.items():
        if not ks or ks[-1][0] != asof or ks[-1][1] <= 0:
            continue   # 当日停牌/无收盘: 不排
        ref = ks[-61][1] if len(ks) > 60 else ks[0][1]
        last = ks[-1]
        if ref <= 0:
            continue
        c, n, ld = sec[s]
        rows.append({"code": c, "name": n, "list_date": ld.isoformat(), "pct60": round((last[1] / ref - 1) * 100, 2),
                     "pct_today": round((last[1] / last[2] - 1) * 100, 2) if last[2] > 0 else None})
    rows.sort(key=lambda r: r["pct60"])
    if a.live and rows:   # 10/20 晚: 盘中实时 —— 名单 / 60 日前参考价取本地库, 现价用新浪一次批量请求(约 90 只 = 1 次), 失败 = 退回收盘口径并标注
        try:
            import urllib.request
            sym_of = {sec[s][0]: s for s in sec}
            ref_of = {}
            for s, ks in bars.items():
                if ks and ks[-1][1] > 0:
                    ref_of[sec[s][0]] = (ks[-61][1] if len(ks) > 60 else ks[0][1], ks[-1][1])
            codes = [r["code"] for r in rows]
            req = urllib.request.Request("https://hq.sinajs.cn/list=" + ",".join(sym_of[c] for c in codes), headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"})
            txt = urllib.request.urlopen(req, timeout=8).read().decode("gbk", errors="replace")
            live = {}
            for l in txt.split("\n"):
                m = re.match(r'var hq_str_(\w+)="([^"]*)"', l)
                if m and m.group(2):
                    f = m.group(2).split(",")
                    if len(f) > 3 and float(f[3] or 0) > 0:
                        live[m.group(1)[2:]] = float(f[3])
            for r in rows:
                p, (ref, prev) = live.get(r["code"]), ref_of.get(r["code"], (0, 0))
                if p and ref > 0:
                    r["pct60"], r["pct_today"] = round((p / ref - 1) * 100, 2), round((p / prev - 1) * 100, 2) if prev > 0 else None
            rows.sort(key=lambda r: r["pct60"])
            asof = f"{dt.datetime.now():%Y-%m-%d %H:%M} 实时(新浪 {len(live)}/{len(rows)} 只)"
        except Exception as e:   # noqa: BLE001
            asof = f"{asof} 收盘(实时取价失败: {str(e)[:40]})"
    print(json.dumps({"asof": asof if isinstance(asof, str) else asof.isoformat(), "n": len(rows), "rows": rows[:a.top]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        sys.exit(main())
    except Exception as e:   # noqa: BLE001
        print(json.dumps({"error": f"{type(e).__name__}: {e}"[:200]}, ensure_ascii=False))
        sys.exit(1)
