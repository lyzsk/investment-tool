# -*- coding: utf-8 -*-
"""import_lhb_db.py — 龙虎榜本地 json → 行情库 investment_market.lhb_stock / lhb_seat(2026-10-15 建, 零请求)
用途: 一次性导入历史(应用还没重启、Java LhbImportServiceImpl 未上线时用); 口径与 Java 版逐字段一致, 之后每日由 Quartz lhbImportHandler 导
口径:
  lhb_stock: list.json 每条上榜记录一行; is_primary=该票当日口径记录(无则第一条多日累计记录)
  lhb_seat: detail_<code>.json 的 buy/sell 每行一行(东财原样; 同席位同在买五卖五=两行), seat_rank=同 trade_id 同方向内按金额降序名次
  is_institution=名称 ^机构(专用|投资者)?$ ; youzi_alias=youzi.json[席位简称]
  只导"完整"的日子: list.json 抓取时刻 ≥ 交易日 18:00 且每只票都有 detail(同 fetch_lhb 缓存判据); 临时版/缺文件跳过并列出
幂等: 每个交易日一个事务, 先物理删除该日两表再插入; 只写 lhb_stock/lhb_seat 两张表
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/lhb/import_lhb_db.py [--from yyyy-MM-dd] [--to yyyy-MM-dd] [--dry]
"""
import argparse
import datetime as dt
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lhb"))
from lhb_lib import LHB, YOUZI, RE_JG, seat_short, is_three_day, symbol_of  # noqa: E402

STOCK_COLS = ["trade_date", "symbol", "code", "name", "trade_id", "is_primary", "reason", "close_price", "change_rate", "buy_amt", "sell_amt",
              "net_amt", "deal_net_ratio", "deal_amount", "turnover_rate", "trade_market", "fetched_at", "source", "status", "create_by", "create_time", "is_deleted"]
SEAT_COLS = ["trade_date", "symbol", "code", "trade_id", "direction", "seat_rank", "dept_code", "dept_name", "amount", "buy_amt", "sell_amt", "net_amt",
             "buy_ratio", "sell_ratio", "is_institution", "youzi_alias", "source", "status", "create_by", "create_time", "is_deleted"]


def parse_day(d):
    """返回 (date, stock_rows, seat_rows) 或 (date, None, 原因)"""
    try:
        L = json.loads((d / "list.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return d.name, None, f"list.json 读不了: {e}"
    date = L["date"]
    if not L.get("rows"):
        return date, None, "空榜"
    if not (L.get("fetched_at", "") >= f"{date} 18:00"):
        return date, None, f"临时版(抓取 {L.get('fetched_at')})"
    now = dt.datetime.now()
    src = L.get("source") or "em"
    by = {}
    for r in L["rows"]:
        by.setdefault(r["SECURITY_CODE"], []).append(r)
    stock_rows, seat_rows = [], []
    for code, rows in by.items():
        prim = next((r for r in rows if not is_three_day(r)), rows[0])
        sym = symbol_of(prim.get("SECUCODE"), code)
        for r in rows:
            stock_rows.append((date, symbol_of(r.get("SECUCODE"), code), code, r.get("SECURITY_NAME_ABBR"), int(r["TRADE_ID"]), 1 if r is prim else 0,
                               r.get("EXPLANATION"), r.get("CLOSE_PRICE"), r.get("CHANGE_RATE"), r.get("BILLBOARD_BUY_AMT"), r.get("BILLBOARD_SELL_AMT"),
                               r.get("BILLBOARD_NET_AMT"), r.get("DEAL_NET_RATIO"), r.get("ACCUM_AMOUNT"), r.get("TURNOVERRATE"), r.get("TRADE_MARKET"),
                               L.get("fetched_at"), src, 0, 1, now, 0))
        f = d / f"detail_{code}.json"
        try:
            det = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return date, None, f"缺 {f.name}: {e}"
        for side, key in (("buy", "BUY"), ("sell", "SELL")):
            grp = {}
            for x in det.get(side) or []:
                grp.setdefault(str(x.get("TRADE_ID")), []).append(x)
            for tid, xs in grp.items():
                # 名次: 金额降序, 同额按营业部编码(稳定序, 与 Java 一致)
                xs = sorted(xs, key=lambda x: (-(float(x.get(key) or 0)), str(x.get("OPERATEDEPT_CODE") or "")))
                for i, x in enumerate(xs, 1):
                    name = (x.get("OPERATEDEPT_NAME") or "").strip()
                    seat_rows.append((date, sym, code, int(tid), key, i, x.get("OPERATEDEPT_CODE"), name, x.get(key), x.get("BUY"), x.get("SELL"),
                                      x.get("NET"), x.get("TOTAL_BUYRIO"), x.get("TOTAL_SELLRIO"), 1 if RE_JG.match(name) else 0,
                                      YOUZI.get(seat_short(name)), src, 0, 1, now, 0))
    return date, stock_rows, seat_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="since")
    ap.add_argument("--to", dest="until")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    import pymysql
    c = pymysql.connect(host="localhost", user="root", password="root", database="investment_market", charset="utf8mb4", autocommit=False)
    cur = c.cursor()
    sql_s = f"INSERT INTO investment_market.lhb_stock ({','.join(STOCK_COLS)}) VALUES ({','.join(['%s'] * len(STOCK_COLS))})"
    sql_t = f"INSERT INTO investment_market.lhb_seat ({','.join(SEAT_COLS)}) VALUES ({','.join(['%s'] * len(SEAT_COLS))})"
    ok = skipped = ns = nt = 0
    skips = []
    for p in sorted(glob.glob(str(LHB / "2*"))):
        p = Path(p)
        iso = p.name.replace(".", "-")
        if (a.since and iso < a.since) or (a.until and iso > a.until):
            continue
        date, srows, trows = parse_day(p)
        if srows is None:
            skipped += 1
            skips.append(f"{date}: {trows}")
            continue
        if not a.dry:
            cur.execute("DELETE FROM investment_market.lhb_stock WHERE trade_date = %s", (date,))
            cur.execute("DELETE FROM investment_market.lhb_seat WHERE trade_date = %s", (date,))
            for i in range(0, len(srows), 1000):
                cur.executemany(sql_s, srows[i:i + 1000])
            for i in range(0, len(trows), 1000):
                cur.executemany(sql_t, trows[i:i + 1000])
            c.commit()
        ok += 1
        ns += len(srows)
        nt += len(trows)
    c.close()
    print(f"导入 {ok} 天: lhb_stock {ns} 行, lhb_seat {nt} 行; 跳过 {skipped} 天" + ("(dry)" if a.dry else ""))
    for s in skips:
        print("  跳过", s)
    print("JSON:" + json.dumps({"days": ok, "stock_rows": ns, "seat_rows": nt, "skipped": skips}, ensure_ascii=False))


if __name__ == "__main__":
    main()
