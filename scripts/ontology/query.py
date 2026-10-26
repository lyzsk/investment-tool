# -*- coding: utf-8 -*-
"""ontology/query.py — 事件本体 v0 的两个查询(10/24; 零 token, 只读 downloads/ontology/ontology.db)

events <代码> <D>        这只票这天发生了什么(各种事件 + 标签 + 结果)、连着什么(同席位同日的其他票、导师交易); 只看 D 当天的事件
like   <事件 id> [标签,标签]  同种类、同标签值的历史事件(只取事件日之前的): 结果全分布 + 最多 12 个案例, 每个案例带"同一天它还连着什么"
       (例: 一次开板事件 → 同高度 / 同开板深度 / 同时段 / 同大盘的历史开板: 之后封回率、次日收盘全分布, 每个案例列当天的席位 / 题材 / 导师交易)
默认标签(不写就用这些): open = height,depth,tm,mkt · day = state,board,mkt,zt_n · seat = alias,at_lim · theme = stage,boards,pos · tg = peaked,half,up · trade = mentor,side,play
用法: python query.py events 002307 2026-10-23 | python query.py like "open:002307:2026-10-23:09:38#1" [height,depth]
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import dist_full as DF   # noqa: E402

DB = ROOT / "downloads" / "ontology" / "ontology.db"
DEF = {"open": ["height", "depth", "tm", "mkt"], "day": ["state", "board", "mkt", "zt_n"], "seat": ["alias", "at_lim"], "theme": ["stage", "boards", "pos"],
       "tg": ["peaked", "half", "up"], "trade": ["mentor", "side", "play"]}
OUTK = {"open": ["resealed", "close_sealed", "ret_close", "next_hi", "next_co"], "day": ["gap", "hi", "co", "c2"], "seat": ["hi", "co"], "tg": ["hi", "co"], "trade": ["v"], "theme": []}


def con():
    if not DB.exists():
        raise SystemExit(f"没有 {DB}, 先跑 scripts/ontology/build.py")
    return sqlite3.connect(DB)


def _row(r):
    eid, kind, code, d, sub, tags, out = r
    return {"eid": eid, "kind": kind, "code": code, "d": d, "sub": sub, "tags": json.loads(tags), "out": json.loads(out)}


def brief(e):
    t = e["tags"]
    if e["kind"] == "seat":
        return f"席位 {t['alias']}({t['style']}/{t['prem']}{'/涨停买' if t.get('at_lim') else ''})"
    if e["kind"] == "theme":
        return f"题材 {t['theme']}({t['stage']} {t['day_n']} {t['nature']} {t['boards']} {t['pos']})"
    if e["kind"] == "trade":
        return f"导师 {t['mentor']} {t['side']} {t['play']} → {t['label']}"
    if e["kind"] == "open":
        return f"开板 {e['sub'].split('#')[0]} {t['height']} 深{t['depth']} 开{t['dur']}"
    if e["kind"] == "tg":
        return f"电报 {e['sub']} {t['peaked']}"
    if e["kind"] == "day":
        return f"状态 {t['state']}{'·封死' if t.get('sealed') else ''}"
    return e["eid"]


def events(code, D):
    c = con()
    E = [_row(r) for r in c.execute("select * from event where code=? and d=?", (code, D)).fetchall()]
    out = {"code": code, "D": D, "事件": [], "连着": {}}
    for e in E:
        out["事件"].append({"eid": e["eid"], "摘要": brief(e), "标签": e["tags"], "结果": e["out"]})
        if e["kind"] == "seat":
            mates = c.execute("select e.* from link l join event e on e.eid=l.dst where l.src=? and l.rel='同席位同日'", (e["eid"],)).fetchall()
            out["连着"][e["eid"]] = [f"{m[2]} {brief(_row(m))} 次日{json.loads(m[6]).get('co', '-')}" for m in mates][:8]
    return out


def like(eid, keys=None):
    c = con()
    r = c.execute("select * from event where eid=?", (eid,)).fetchone()
    if not r:
        return {"err": f"没有事件 {eid}; 先用 events 查 id"}
    e = _row(r)
    keys = keys or DEF.get(e["kind"], [])
    rows = [_row(x) for x in c.execute("select * from event where kind=? and d<?", (e["kind"], e["d"])).fetchall()]
    hit = [x for x in rows if all(x["tags"].get(k) == e["tags"].get(k) for k in keys)]
    stat = {}
    for k in OUTK.get(e["kind"], []):
        vals = [x for x in hit if x["out"].get(k) is not None]
        if not vals:
            continue
        if k in ("resealed", "close_sealed"):
            stat[k] = f"{sum(x['out'][k] for x in vals)}/{len(vals)}"
        else:
            stat[k] = DF.full(vals, key=lambda x, k=k: x["out"][k], tag=lambda x: f"{x['code']} {x['d']}")
    cases = []
    for x in sorted(hit, key=lambda z: z["d"], reverse=True)[:12]:
        same_day = [_row(y) for y in c.execute("select * from event where code=? and d=? and kind<>?", (x["code"], x["d"], x["kind"])).fetchall()]
        cases.append({"eid": x["eid"], "结果": x["out"], "同一天还有": [brief(y) for y in same_day][:8]})
    tr = [t for t in hit for _ in [0]]
    return {"事件": brief(e), "按标签": {k: e["tags"].get(k) for k in keys}, "历史同标签 n": len(hit), "结果统计": stat, "最近案例": cases,
            "说明": "只取事件日之前的历史; 换标签组合: like <id> 标签1,标签2"}


def _case_brief(c):
    """案例一行: 代码 日期 时刻 + 结果(10/24 用户: n=4 也要说是哪几天、几点)"""
    p = c["eid"].split(":")
    code, d = p[1], p[2][5:] if len(p) > 2 else ""
    tm = ":".join(p[3:5]).split("#")[0] if len(p) > 4 else ""
    o = c.get("结果") or {}
    seg = []
    if "resealed" in o:
        seg.append("封回" if o["resealed"] else "没封回")
    if "close_sealed" in o:
        seg.append("收盘封住" if o["close_sealed"] else "收盘没封")
    for k, nm in (("ret_close", "接→收"), ("next_hi", "次日高"), ("next_co", "次日收"), ("co", "次日收"), ("v", "结果")):
        if o.get(k) is not None and nm not in " ".join(seg):
            seg.append(f"{nm} {o[k]:+.2f}%" if isinstance(o[k], (int, float)) else f"{nm} {o[k]}")
    return f"{code} {d}{(' ' + tm) if tm else ''} " + "/".join(seg)


def line_stats(r, n_cases=8):
    """给必查 / 盘中回答用的一行(统计 + 最近 n 个案例的日期 / 时刻 / 结果)"""
    if r.get("err"):
        return r["err"]
    parts = [f"{k}: {v}" if isinstance(v, str) else f"{k}: {DF.line(v)}" for k, v in r["结果统计"].items()]
    cases = "; ".join(_case_brief(c) for c in (r.get("最近案例") or [])[:n_cases])
    return f"{r['事件']} · 同标签{r['按标签']} n={r['历史同标签 n']} | " + " | ".join(parts) + (f" | 最近案例: {cases}" if cases else "")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = sys.argv[1:]
    if not a or a[0] not in ("events", "like"):
        print(__doc__)
    elif a[0] == "events":
        print(json.dumps(events(a[1], a[2]), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(like(a[1], a[2].split(",") if len(a) > 2 else None), ensure_ascii=False, indent=1))
