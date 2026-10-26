"""K 线学习 - 行情库只读连接 (investment_market). 只允许 SELECT.
连接参数取自 inv-admin application.yml(与 scripts/backfill_bilibili/manual_backfill.py 的 db() 相同口径), 仅换库名.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def connect(database: str = "investment_market"):
    import pymysql
    yml = (ROOT / "inv-admin/src/main/resources/application.yml").read_text(encoding="utf-8")
    pw = re.search(r"password:\s*\"?([^\"\r\n]+)", yml).group(1).strip()
    conn = pymysql.connect(host="localhost", port=3306, user="root", password=pw, database=database,
                           charset="utf8mb4", autocommit=True, read_timeout=600)
    with conn.cursor() as cur:
        # 会话级只读, 防误写
        cur.execute("SET SESSION TRANSACTION READ ONLY")
    return conn


def query(sql: str, args=None, database: str = "investment_market"):
    s = sql.strip().lower()
    if not (s.startswith("select") or s.startswith("show") or s.startswith("describe") or s.startswith("with")):
        raise ValueError("kline_study 只允许只读查询")
    import pandas as pd
    conn = connect(database)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        return pd.DataFrame(list(rows), columns=cols)
    finally:
        conn.close()
