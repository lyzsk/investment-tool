# -*- coding: utf-8 -*-
"""ontology/build.py — 事件本体 v0(10/24 用户批: 数据进"本体", 给事件打统一语义标签并联动; 先做机械标签, 语义标签之后再定; 零 token)

统一键: (code 6 位, d 交易日[, t 时刻]);  事件 id = "<kind>:<code>:<d>[:<t>|:<序号>]"
事件种类(kind) × 机械标签(tags) × 结果(out, 都相对事件当天收盘 / 买点 %):
  day        票日状态(强势股库 stock_strong): state 首板/二板/三板+/炸板/大涨/回调1~3 · board 10/20cm · sealed · pct_b · volr · level · mkt · zt_n
             out: gap 次日开 / hi 次日最高 / lo 次日最低 / co 次日收 / c2 T+2 收
  open       开板事件(分钟路径, board_knowledge.collect): height 第几板 · depth 开板深度档 · dur 开板时长档 · tm 时段 · k 第几次开板 · mkt · ztn · typ 板型
             out: resealed 之后封回 / close_sealed 收盘封住 / ret_close 开板时接→收盘 / next_hi / next_co
  seat       龙虎榜席位净买(每票每日净买前 3): alias 游资名 · style 席位风格(只用事件日之前的历史: 打板型/低吸型/混合/样本少 + 次日溢价高/低) · rank
             out: hi / co 次日(相对上榜日收盘)
  theme      题材日(md 涨停分析): theme · stage 阶段 · day_n 本波第几天(分档) · nature 主线/新概念/一般 · boards 板数 · pos 题材内位置
  tg         加红电报点名(telegraph): peaked 点名时是否见顶 · half 上午/下午 · up 点名时涨幅档    out: hi / co 次日(相对点名后一分钟买点)
  trade      导师逐笔事件(cases_auto, 全部账本): mentor · side 买/卖 · play 打法 · sell_kind · label 正/负/平/未知    out: v 结果值
关系(link): 同键的事件互相连(kind 不同即连, 关系名 = "<kind>→<kind>"), 另: seat → 同席位同日买的其他票(rel = 同席位同日)
产物: downloads/ontology/ontology.db(SQLite, 本地文件, 不写业务库); 每晚可重建(约 1~3 分钟)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/ontology/build.py [--since 2025-01-01]
"""
import argparse
import bisect
import collections
import datetime as dt
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "lib"), str(ROOT / "scripts" / "paper_line" / "tools"),
                str(ROOT / "scripts" / "test"), str(ROOT / "scripts" / "market"), str(ROOT / "scripts" / "lib")]
OUT = ROOT / "downloads" / "ontology" / "ontology.db"
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    LOG.append(s)
    print(f"[{dt.datetime.now():%H:%M:%S}] {s}", flush=True)


def b_depth(x):
    d = -x
    return "≤2%" if d <= 2 else "2~4%" if d <= 4 else "4~7%" if d <= 7 else ">7%"


def b_dur(m):
    return "≤2分" if m <= 2 else "3~9分" if m <= 9 else "10~29分" if m <= 29 else "≥30分"


def b_tm(t):
    return "早盘<10:00" if t < "10:00" else "上午" if t <= "11:30" else "下午<14:00" if t < "14:00" else "尾盘≥14:00"


def b_mkt(p):
    return "≥+0.5" if p >= 0.5 else "≤−0.5" if p <= -0.5 else "平"


def b_ztn(n):
    return "<30" if n < 30 else "30~60" if n < 60 else "60~100" if n < 100 else "≥100"


def b_dayn(n):
    return "首日" if n <= 1 else "2~3天" if n <= 3 else "4~7天" if n <= 7 else "≥8天"


def b_up(x):
    return "<0" if x < 0 else "0~5%" if x < 5 else "5~9%" if x < 9 else "≥9%"


def db():
    import manual_backfill as mb
    c = mb.db().cursor()
    c.execute("use investment_market")
    return c


def load_k(c, since):
    t0 = time.time()
    c.execute("select k.symbol, k.trade_date, k.open, k.high, k.low, k.close, k.pre_close from kline_day k join security_master s on s.symbol=k.symbol and s.sec_type='STOCK' "
              "where k.is_deleted=0 and k.trade_date >= %s and k.pre_close > 0 order by k.symbol, k.trade_date", (since,))
    K = collections.defaultdict(list)
    for s, d, o, h, l, cl, pc in c.fetchall():
        if o and cl:
            K[s[2:]].append((str(d), float(o), float(h), float(l), float(cl), float(pc)))
    idx = {code: {x[0]: i for i, x in enumerate(v)} for code, v in K.items()}
    log(f"日线 {sum(len(v) for v in K.values())} 行 {time.time() - t0:.0f}s")
    return K, idx


def nxt(K, idx, code, d):
    i = (idx.get(code) or {}).get(d)
    if i is None or i + 1 >= len(K[code]):
        return None
    t, n = K[code][i], K[code][i + 1]
    return {"gap": round((n[1] / t[4] - 1) * 100, 2), "hi": round((n[2] / t[4] - 1) * 100, 2), "lo": round((n[3] / t[4] - 1) * 100, 2), "co": round((n[4] / t[4] - 1) * 100, 2)}


def ev_day(since):
    f = ROOT / "downloads" / "market" / "similar" / "stock_strong.jsonl"
    out = []
    for l in f.open(encoding="utf-8"):
        r = json.loads(l)
        if r["d"] < since:
            continue
        out.append(("day", r["code"], r["d"], "", {k: r.get(k) for k in ("state", "board", "sealed", "pct_b", "volr", "level", "mkt", "zt_n")},
                    {k: r.get(k) for k in ("gap", "hi", "lo", "co", "c2") if r.get(k) is not None}))
    log("day", len(out))
    return out


def ev_open():
    import board_knowledge as BK
    _, opens, *_ = BK.collect()   # 10/25 collect 多返回了反包板列表
    out = []
    for e in opens:
        out.append(("open", e["code"], e["D"], f"{e['t']}#{e['k']}", {"height": "首板" if e["height"] == 1 else "二板" if e["height"] == 2 else "三板+", "depth": b_depth(e["depth"]),
                    "dur": b_dur(e["dur"]), "tm": b_tm(e["t"]), "k": "第1次" if e["k"] == 1 else "第2次" if e["k"] == 2 else "第3次+", "mkt": b_mkt(e["mkt"]), "ztn": b_ztn(e["ztn"]), "typ": e["typ"]},
                    {"resealed": int(e["resealed"]), "close_sealed": int(e["close_sealed"]), "ret_close": round(e["ret_close"], 2),
                     **({"next_hi": round(e["next_hi"], 2)} if e.get("next_hi") is not None else {}), **({"next_co": round(e["next_co"], 2)} if e.get("next_co") is not None else {})}))
    log("open", len(out))
    return out


def ev_seat(c, K, idx, since):
    c.execute("select trade_date, code, dept_code, max(youzi_alias), max(dept_name), max(is_institution), sum(net_amt) from lhb_seat where is_deleted=0 and trade_date >= %s "
              "group by trade_date, code, dept_code having sum(net_amt) > 0 order by trade_date", (since,))
    rows = [(str(d), code, dc, al, dn, inst, float(na)) for d, code, dc, al, dn, inst, na in c.fetchall() if code]
    by_day = collections.defaultdict(list)
    for r in rows:
        by_day[(r[0], r[1])].append(r)
    hist = collections.defaultdict(lambda: {"n": 0, "lim": 0, "his": []})   # 席位到前一天为止的历史(防偷看)
    out, pend = [], collections.defaultdict(list)
    for d in sorted({r[0] for r in rows}):
        for code_key, (dd, code) in [(k, k) for k in by_day if k[0] == d]:
            pass
        todays = [k for k in by_day if k[0] == d]
        for (dd, code) in todays:
            for rank, r in enumerate(sorted(by_day[(dd, code)], key=lambda x: -x[6])[:3], 1):
                h = hist[r[2]]
                if h["n"] >= 10:
                    style = "打板型" if h["lim"] / h["n"] >= 0.6 else "混合"
                    med = h["his"][len(h["his"]) // 2] if h["his"] else 0
                    prem = "次日溢价高" if med >= 6 else "次日溢价低" if med <= 2 else "次日溢价中"
                else:
                    style, prem = "样本少", "-"
                o = nxt(K, idx, code, d) or {}
                i = (idx.get(code) or {}).get(d)
                at_lim = bool(i is not None and K[code][i][4] >= round(K[code][i][5] * (1.2 if code[:3] in ("300", "301", "688", "689") else 1.1) + 1e-9, 2) - 0.005)
                out.append(("seat", code, d, f"{r[2]}", {"alias": r[3] or ("机构" if r[5] else "营业部"), "dept": r[2], "style": style, "prem": prem, "rank": rank, "at_lim": at_lim},
                            {k: o[k] for k in ("hi", "co", "gap") if k in o}))
                pend[d].append((r[2], at_lim, o.get("hi")))
        for dc, at_lim, hi in pend.pop(d, []):   # 当天收盘后才进历史
            h = hist[dc]
            h["n"] += 1
            h["lim"] += int(at_lim)
            if hi is not None:
                bisect.insort(h["his"], hi)
    log("seat", len(out))
    return out


def ev_theme(since):
    import theme_life as TL
    out, cache = [], {}
    c = db()
    c.execute("select code, name from security_master where sec_type='STOCK'")
    n2c = {}
    for code, nm in c.fetchall():
        if nm:
            n2c[nm.replace(" ", "").replace("Ａ", "A")] = code
    R = []
    for r in TL.rows_canon():   # 涨停分析里多数行没有代码 → 按股票名补(去空格 / 全角)
        if r[0] < since:
            continue
        code = r[3] or n2c.get(str(r[2]).replace(" ", "").replace("\\", "").replace("Ａ", "A"))
        if code:
            R.append((r[0], r[1], r[2], code, *r[4:]))
    by = collections.defaultdict(list)
    for r in R:
        by[(r[0], r[1])].append(r)
    for r in R:
        d, th, nm, code, b, zt = r[0], r[1], r[2], r[3], r[4], r[5]
        if (th, d) not in cache:
            L = TL.life(th, d, after=True) or {}
            cache[(th, d)] = (str(L.get("阶段") or "").split("(")[0], L.get("本波第几天") or 0, L.get("本波峰值家数") or 0)
        stg, dn, pk = cache[(th, d)]
        mates = by[(d, th)]
        top = max([x[4] for x in mates] or [0])
        nature = "主线" if dn >= 3 and pk >= 5 else "新概念" if dn == 1 and len(mates) >= 3 else "一般"
        pos = "题材内最高" if b and b == top and b >= 2 else "补涨" if b == 1 and dn >= 3 else "首板" if b == 1 else "大涨" if not zt else "跟风"
        out.append(("theme", code, d, th, {"theme": th, "stage": stg, "day_n": b_dayn(dn), "nature": nature, "boards": f"{b}板" if b else "大涨", "pos": pos}, {}))
    log("theme", len(out))
    return out


def ev_tg():
    import telegraph_nextday as TN
    rows, *_ = TN.collect()
    out = []
    for r in rows:
        out.append(("tg", r["sym"][2:], r["D"], r.get("t") or "", {"peaked": "已见顶" if r.get("peaked") else "未见顶", "half": "上午" if (r.get("t") or "") < "12:00" else "下午",
                                                                  "up": b_up(r.get("up") or 0)}, {"hi": round(r["hi"], 2), "co": round(r["co"], 2), "gap": round(r["gap"], 2)}))
    log("tg", len(out))
    return out


def ev_trade():
    import case_label as CL
    out = []
    for f in sorted((ROOT / "skills").glob("*-skill/persona/cases_auto.jsonl")):
        m = f.parent.parent.name[:-6]
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        rows = [r for r in rows if r.get("side") in ("买", "卖") and r.get("code")]
        for i, r in enumerate(rows):
            lb, v, why = CL.label(r, rows)
            out.append(("trade", str(r["code"]), r["date"], f"{m}:{r.get('time')}:{i}", {"mentor": m, "side": r["side"], "play": r.get("play") or "-", "sell_kind": r.get("sell_kind") or "-", "label": lb},
                        ({"v": v} if v is not None else {}) | {"why": why, "time": r.get("time"), "vwap": r.get("vwap")}))
    log("trade", len(out))
    return out


def build(since):
    t0 = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript("""
      create table event(eid text primary key, kind text, code text, d text, sub text, tags text, out text);
      create table link(src text, rel text, dst text);
      create table meta(k text primary key, v text);""")
    c = db()
    K, idx = load_k(c, since)
    srcs = [("day", lambda: ev_day(since)), ("open", ev_open), ("seat", lambda: ev_seat(c, K, idx, since)), ("theme", lambda: ev_theme(since)), ("tg", ev_tg), ("trade", ev_trade)]
    cnt = {}
    for name, fn in srcs:
        try:
            E = fn()
        except Exception as e:   # noqa: BLE001  大声失败: 记下来, 其它来源照常建
            log(f"!! {name} 失败: {e!r}")
            cnt[name] = f"失败 {e!r}"[:200]
            continue
        rows = [(f"{k}:{code}:{d}" + (f":{sub}" if sub else ""), k, code, d, sub, json.dumps(tags, ensure_ascii=False), json.dumps(o, ensure_ascii=False)) for k, code, d, sub, tags, o in E]
        con.executemany("insert or replace into event values (?,?,?,?,?,?,?)", rows)
        cnt[name] = len(rows)
    con.execute("create index ix_key on event(code, d)")
    con.execute("create index ix_kind on event(kind, d)")
    # 关系: 同键不同种类互连; 同席位同日
    cur = con.execute("select eid, kind, code, d from event")
    by = collections.defaultdict(list)
    for eid, k, code, d in cur.fetchall():
        by[(code, d)].append((eid, k))
    L = []
    for v in by.values():
        if len(v) < 2:
            continue
        for a, ka in v:
            for b, kb in v:
                if a != b and ka != kb:
                    L.append((a, f"{ka}→{kb}", b))
    seat = collections.defaultdict(list)
    for eid, d, tags in con.execute("select eid, d, tags from event where kind='seat'").fetchall():
        seat[(json.loads(tags)["dept"], d)].append(eid)
    for v in seat.values():
        for a in v:
            for b in v:
                if a != b:
                    L.append((a, "同席位同日", b))
    con.executemany("insert into link values (?,?,?)", L)
    con.execute("create index ix_link on link(src)")
    con.execute("insert into meta values ('built', ?), ('since', ?), ('counts', ?), ('links', ?)", (dt.datetime.now().isoformat(timespec="seconds"), since, json.dumps(cnt, ensure_ascii=False), str(len(L))))
    con.commit()
    con.close()
    tmp.replace(OUT)
    log(f"完成 {OUT} 事件 {cnt} 关系 {len(L)} 用时 {time.time() - t0:.0f}s")
    return cnt


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2025-01-01")
    a = ap.parse_args()
    build(a.since)
