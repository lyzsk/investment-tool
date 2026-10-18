# -*- coding: utf-8 -*-
"""lhb_lib.py — 龙虎榜本地 json 公共读取层(零请求; 2026-10-15 建, seat_profile / mentor_overlap / import_lhb_db 共用)
口径(与 fetch_lhb.mjs build() 一致):
  - 一只票一天可能多条上榜记录(TRADE_ID 不同, 如当日口径+3 日累计); 主记录=当日口径优先, 只有多日累计时用它
  - 席位事件只取主记录的买五/卖五; 同一席位同时在买五与卖五 → 合并成一个事件(买/卖/净额取该席位行, 两边数值相同)
  - 席位身份键=OPERATEDEPT_CODE(东财营业部编码, 跨更名稳定: 国泰君安→国泰海通、绍兴→绍兴鲁迅中路);
    垃圾编码(0/99999/10000128629 等多名共用)改用全名作键; 展示名=最近一次出现的全名
  - 游资别名: scripts/lhb/youzi.json(键=简称, 同 fetch_lhb seatShort); 同一编码任一历史名命中即算
  - 机构: 名称 ^机构(专用|投资者)?$ ; 北向: 深股通/沪股通(专用|投资者)?
"""
import glob
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LHB = ROOT / "downloads" / "lhb"
YOUZI = json.loads((ROOT / "scripts" / "lhb" / "youzi.json").read_text(encoding="utf-8"))["map"]
BAD_CODES = {"0", "99999", "10000128629", "", None}
RE_JG = re.compile(r"^机构(专用|投资者)?$")
RE_BX = re.compile(r"^(深股通|沪股通)(专用|投资者)?$")


def seat_short(n):
    n = (n or "").strip()
    m = re.match(r"^(.*?)(股份有限公司|有限责任公司|有限公司)(.*)$", n)
    if not m:
        return n
    broker = m.group(1).replace("证券", "", 1)
    br = re.sub(r"(证券)?营业部$", "", m.group(3)).strip()
    return f"{broker} {br}" if br else broker


def is_three_day(r):
    return "连续" in (r.get("EXPLANATION") or "")


def symbol_of(secucode, code):
    suf = (secucode or "").split(".")[-1].upper()
    return {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(suf, "sz" if code[0] in "0123" else "sh") + code


def seat_key(code, name):
    return f"N:{name}" if str(code) in BAD_CODES or RE_JG.match(name or "") or RE_BX.match(name or "") else f"C:{code}"


def load_day(dirpath):
    """返回 (date, stocks) 或 None(不完整的日子跳过); stocks=[{code,name,symbol,prim,rows,seats:[...]}]"""
    try:
        L = json.loads((dirpath / "list.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    date = L["date"]
    if not L.get("rows") or not (L.get("fetched_at", "") >= f"{date} 18:00"):
        return None
    by = {}
    for r in L["rows"]:
        by.setdefault(r["SECURITY_CODE"], []).append(r)
    stocks = []
    for code, rows in by.items():
        try:
            d = json.loads((dirpath / f"detail_{code}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        prim = next((r for r in rows if not is_three_day(r)), rows[0])
        tid = str(prim["TRADE_ID"])
        buy = [x for x in d.get("buy") or [] if str(x.get("TRADE_ID")) == tid]
        sell = [x for x in d.get("sell") or [] if str(x.get("TRADE_ID")) == tid]
        # 同 fetch_lhb: 卖五里与买五"名+买+卖"完全相同的行一对一抵消(同一席位同一笔), 同榜真重复行(两个机构专用同额)保留
        pool = [(x.get("OPERATEDEPT_NAME"), x.get("BUY"), x.get("SELL")) for x in buy]
        uniq = [(x, "buy") for x in buy]
        for x in sell:
            k = (x.get("OPERATEDEPT_NAME"), x.get("BUY"), x.get("SELL"))
            if k in pool:
                pool[pool.index(k)] = None
                uniq.append((x, "both"))
            else:
                uniq.append((x, "sell"))
        seats = {}
        for x, side in uniq:
            name = x.get("OPERATEDEPT_NAME") or ""
            k = seat_key(x.get("OPERATEDEPT_CODE"), name)
            s = seats.get(k)
            if s is None:
                s = seats[k] = {"key": k, "dept_code": x.get("OPERATEDEPT_CODE"), "name": name, "short": seat_short(name),
                                "buy": 0.0, "sell": 0.0, "net": 0.0, "in_buy5": False, "in_sell5": False}
            if side != "both":      # both=卖五里那行与买五重复, 金额已在买五那行计过
                s["buy"] += float(x.get("BUY") or 0)
                s["sell"] += float(x.get("SELL") or 0)
                s["net"] += float(x.get("NET") or 0)
            if side == "buy":
                s["in_buy5"] = True
            else:
                s["in_sell5"] = True
        for s in seats.values():
            s["is_jg"] = bool(RE_JG.match(s["name"]))
            s["is_bx"] = bool(RE_BX.match(s["name"]))
        stocks.append({"code": code, "name": prim["SECURITY_NAME_ABBR"], "symbol": symbol_of(prim.get("SECUCODE"), code),
                       "market": prim.get("TRADE_MARKET"), "prim": prim, "rows": rows, "seats": list(seats.values())})
    return date, stocks


def iter_days(since=None, until=None):
    for p in sorted(glob.glob(str(LHB / "2*"))):
        p = Path(p)
        r = load_day(p)
        if r is None:
            continue
        if since and r[0] < since:
            continue
        if until and r[0] > until:
            continue
        yield r


def alias_of(names):
    """一个席位(编码)的所有历史全名 → 游资别名(任一命中)"""
    for n in names:
        a = YOUZI.get(seat_short(n))
        if a:
            return a
    return None


def kline_map(symbols, since="2025-01-01"):
    """kline_day 只读: {symbol: [(date_iso, open, close, pre_close), ...] 升序}; 库里没有的(北交所 2026-10-09 前/转债)从 downloads/quotes/daily 补(前复权, 只用比值)"""
    import pymysql
    out = {}
    c = pymysql.connect(host="localhost", user="root", password="root", database="investment_market", charset="utf8mb4")
    try:
        cur = c.cursor(pymysql.cursors.SSCursor)
        cur.execute("select symbol, trade_date, `open`, `close`, pre_close from kline_day where trade_date >= %s and is_deleted = 0 "
                    "and (symbol like 'sh%%' or symbol like 'sz%%' or symbol like 'bj%%') order by symbol, trade_date", (since,))
        want = set(symbols)
        for sym, d, o, cl, pc in cur:
            if sym in want:
                out.setdefault(sym, []).append((d.isoformat(), float(o), float(cl), float(pc) if pc is not None else None))
    finally:
        c.close()
    for sym in set(symbols) - set(out):
        f = ROOT / "downloads" / "quotes" / "daily" / f"{sym[2:]}.json"
        if not f.exists():
            continue
        try:
            ks = json.loads(f.read_text(encoding="utf-8")).get("klines") or []
        except ValueError:
            continue
        rows, prev = [], None
        for k in ks:
            if k["d"] < since:
                prev = k["c"]
                continue
            rows.append((k["d"], float(k["o"]), float(k["c"]), prev))
            prev = float(k["c"])
        if rows:
            out[sym] = rows
    return out
