# -*- coding: utf-8 -*-
"""kline_db.py — 只读查行情库日线(10/15, TODO §3-B-3; kline.mjs 的 "db" 源后端)
用法: python kline_db.py <symbol>[,<symbol>...] [--beg yyyyMMdd]
  symbol = sh600000 / sz002428 / bj920575 / sh000001(指数)
stdout 一行 JSON: {"maxDate": 库内全市场最新交易日, "data": {symbol: {"bars": [[d,o,h,l,c,v股,a元], ...], "factors": [[ex_date, factor], ...]}}}
只读: 只有 SELECT, 不写任何表(业务库只读立法)。
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def db():
    import pymysql
    yml = (ROOT / "inv-admin/src/main/resources/application.yml").read_text(encoding="utf-8")
    pw = re.search(r"password:\s*\"?([^\"\r\n]+)", yml).group(1).strip()
    return pymysql.connect(host="localhost", port=3306, user="root", password=pw, database="investment_market", charset="utf8mb4",
                           connect_timeout=5, read_timeout=60)


def main():
    syms = [s for s in sys.argv[1].split(",") if re.fullmatch(r"(sh|sz|bj)\d{6}", s)]
    beg = sys.argv[sys.argv.index("--beg") + 1] if "--beg" in sys.argv else "19900101"
    beg = f"{beg[:4]}-{beg[4:6]}-{beg[6:8]}"
    out = {"maxDate": None, "data": {}}
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("select max(trade_date) from kline_day where symbol='sh000001'")   # 上证指数=交易日历(走索引)
        m = cur.fetchone()[0]
        out["maxDate"] = m.isoformat() if m else None
        for i in range(0, len(syms), 200):
            part = syms[i:i + 200]
            ph = ",".join(["%s"] * len(part))
            cur.execute(f"select symbol, trade_date, open, high, low, close, volume, amount from kline_day where symbol in ({ph}) and trade_date >= %s "
                        f"order by symbol, trade_date", (*part, beg))
            for s, d, o, h, l, c, v, a in cur.fetchall():
                out["data"].setdefault(s, {"bars": [], "factors": []})["bars"].append(
                    [d.isoformat(), float(o or 0), float(h or 0), float(l or 0), float(c or 0), int(v or 0), float(a or 0)])
            cur.execute(f"select symbol, min(trade_date) from kline_day where symbol in ({ph}) group by symbol", tuple(part))
            for s, fd in cur.fetchall():
                if s in out["data"]:
                    out["data"][s]["firstDate"] = fd.isoformat()
            cur.execute(f"select symbol, list_date from security_master where symbol in ({ph})", tuple(part))
            for s, ld in cur.fetchall():
                if s in out["data"] and ld:
                    out["data"][s]["listDate"] = ld.isoformat()
            cur.execute(f"select symbol, ex_date, factor from adjustment_factor where symbol in ({ph}) order by symbol, ex_date", tuple(part))
            for s, d, f in cur.fetchall():
                if s in out["data"]:
                    out["data"][s]["factors"].append([d.isoformat(), float(f)])
    finally:
        conn.close()
    sys.stdout.write(json.dumps(out, separators=(",", ":")))


if __name__ == "__main__":
    main()
