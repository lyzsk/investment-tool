# -*- coding: utf-8 -*-
"""telegraph_now.py — 盘中加红电报点名(10/25 用户选 telegraph_placement.md 的 A + D + G + H + J, B 只要求回应不打回; 零 token, 只读)

named(D, upto)      今天 ≤ upto 被加红电报点名的票 → {代码: [{t, type, act, lead, past, title, url}]}
                    原文优先业务库 cls_telegraph 全文(Java 每分钟拉; md 里的会截断), 拿不到用 md「加红电报」节; 分类同 scripts/test/telegraph_kind.py v2
item(code, D, upto) 必查「电报点名」一行(A): 几点 / 哪类电报 / 这只票的动作 / 领跟 / 此前 + 点名时涨幅和离当时最高(有分钟线才有) +
                    这一类近 100 个交易日的全分布(downloads/ontology/telegraph_kind_stats.json, 每晚重算) + 封板 / 冲板类附"点名后开板"那组数(开板即接 vs 跌深接)
                    只摆事实: 次日收盘中位为负的类别写"这一类次日收盘中位为负", 其余只给分布; 样本 < 50 标"样本少"
limit_named(D, upto) 被点名且动作 = 封板 / 冲板 的票(D: 进候选池 + 3 秒盘口; 不叫醒 chain —— 用户 10/25: 开板叫醒会风暴, 先跑几天看)
tag(code, D, upto)  推送 / 盘前汇总里的短标记(J): "⚠电报10:43·封板(跟)"
"""
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "test"), str(ROOT / "scripts" / "backfill_bilibili")]
STATS = ROOT / "downloads" / "ontology" / "telegraph_kind_stats.json"
_C = {}


def _names():
    if "names" not in _C:
        import telegraph_validate as TV
        _C["names"] = TV.names(TV.db().cursor())
    return _C["names"]


def _texts(D):
    """→ [(HH:MM:SS, 全文, 链接)]; 同一分钟内复用(盘中电报一分钟一拉)"""
    key = ("tx", D, time.strftime("%H%M"))
    if key in _C:
        return _C[key]
    out = []
    try:
        import manual_backfill as mb
        c = mb.db().cursor()
        c.execute("select date_format(publish_time,'%%H:%%i:%%s'), coalesce(content, brief, title), cls_id from investment_tool.cls_telegraph "
                  "where is_deleted=0 and publish_time >= %s and publish_time < date_add(%s, interval 1 day) order by publish_time", (D, D))
        out = [(t, txt or "", f"https://www.cls.cn/detail/{cid}") for t, txt, cid in c.fetchall()]
    except Exception:   # noqa: BLE001  库读不到 → md
        pass
    if not out:
        try:
            import pack
            m = re.search(r"\n## 加红电报\n(.*?)(?:\n## |\Z)", pack.rd(pack.md_path(D)) or "", re.S)
            for d, t, txt, url in re.findall(r"^- \[(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d)\] \[(.*?)\]\((https?://[^)\s]+)\)", m.group(1) if m else "", re.M):
                if d == D:
                    out.append((t, txt, url))
        except Exception:   # noqa: BLE001
            pass
    _C[key] = out
    return out


def named(D, upto="23:59:59"):
    key = ("named", D, upto[:5])   # 10/25: 同一分钟内复用(必查每只票都会调一次, 每次全量扫电报 × 全部股票名太慢, 回放里拖慢明显)
    if key in _C:
        return _C[key]
    _C[key] = _named(D, upto)
    return _C[key]


def _named(D, upto="23:59:59"):
    import telegraph_kind as TK
    import telegraph_validate as TV
    bn, bc = _names()
    out = {}
    for t, txt, url in _texts(D):
        if t > upto:
            continue
        hit = TV.mentions(txt, bn, bc)
        nms = list(hit.values())
        for sym, nm in hit.items():
            if nm.isdigit():
                act = "只点名"
            else:
                act = TK.action(txt, nm)
            if act == "非主体":
                continue
            out.setdefault(sym[2:], []).append({"t": t, "type": TK.tg_type(txt), "act": act, "lead": TK.lead(txt, nm, nms) if not nm.isdigit() else "跟",
                                                "past": TK.past(txt, nm) if not nm.isdigit() else False, "title": TK.title_of(txt)[:40], "url": url})
    return out


def _stats():
    if "st" not in _C or time.time() - _C.get("st_t", 0) > 600:
        try:
            _C["st"] = json.loads(STATS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _C["st"] = {}
        _C["st_t"] = time.time()
    return _C["st"]


def _fmt(s):
    if not s:
        return "无样本"
    few = "(样本少)" if s["n"] < 50 else ""
    return f"n={s['n']}{few} 中{s['med']:+.2f} 均{s['mean']:+.2f} P10 {s['p10']:+.2f} P90 {s['p90']:+.2f} 最差{s['worst']:+.2f}"


def _at_naming(code, D, t):
    """点名那一分钟: 当天已涨幅 / 离当时最高回落(分钟线; 没有返回 None)"""
    try:
        import telegraph_validate as TV
        sym = ("sh" if code.startswith("6") else "sz") + code
        cur = TV.db().cursor()
        b = TV.bars(cur, D, sym, _C.setdefault("bars", {}))
        pre = [x for x in b if x[0] <= t[:5]]
        if not pre:
            return None
        cur.execute("select pre_close from investment_market.kline_day where symbol=%s and trade_date=%s", (sym, D))
        pc = (cur.fetchone() or [None])[0]
        up = (pre[-1][2] / float(pc) - 1) * 100 if pc else None
        dd = (max(x[1] for x in pre) / pre[-1][2] - 1) * 100
        return up, dd
    except Exception:   # noqa: BLE001
        return None


def item(code, D, upto="23:59:59"):
    hs = named(D, upto).get(code)
    if not hs:
        return None
    S = _stats()
    A = S.get("act") or {}
    rng = "~".join(S.get("days") or []) or "近 100 个交易日"
    L = []
    for h in hs[-3:]:
        a = A.get(h["act"]) or {}
        x = _at_naming(code, D, h["t"])
        now = f"点名时当天 {x[0]:+.1f}%、离此前最高回落 {x[1]:.1f}%" if x and x[0] is not None else "点名时涨幅: 没有分钟线"
        bucket = None if not x else "<1" if x[1] < 1 else "1~2" if x[1] < 2 else ">=2"
        co = a.get("co")
        neg = "; 这一类次日收盘中位为负" if co and co["med"] < 0 else ""
        if not ("09:30:00" <= h["t"] <= "14:57:00"):   # 统计口径是盘中点名后一分钟买; 盘前 / 盘后电报只列事实
            L.append(f"{h['t'][:5]} {'盘前' if h['t'] < '09:30' else '盘后'}电报 {h['type']}「{h['title']}」→ 本票动作 {h['act']}({h['lead']}); 历史统计只覆盖盘中点名, 这条不套分布; 链接 {h['url']}")
            continue
        seg = (f"{h['t'][:5]} {h['type']}「{h['title']}」→ 本票动作 {h['act']}({h['lead']}{'·说的是此前' if h['past'] else ''}); {now}; "
               f"这一类({h['act']})点名后一分钟买 → 次日收盘 {_fmt(co)}{neg}; 次日最高 {_fmt(a.get('hi'))}")
        if bucket and (a.get("dd") or {}).get(bucket):
            seg += f"; 其中点名时离高点回落 {bucket}% 这档: 次日收盘 {_fmt(a['dd'][bucket])}"
        L.append(seg + f"; 链接 {h['url']}")
    if any(h["act"] in ("封板", "冲板") and "09:30:00" <= h["t"] <= "14:57:00" for h in hs):
        o = (S.get("open") or {}).get("named") or {}
        if o:
            dp = o.get("deep") or {}
            L.append(f"若之后开板(点名后开板 {o.get('n')} 次): 之后封回 {o.get('reseal', 0):.0%}; 开板那一分钟接 → 次日收盘 {_fmt(o.get('co'))}, 次日最高 {_fmt(o.get('hi'))}; "
                     + "; ".join(f"跌到离涨停 {k}% 再接: 封回 {v.get('reseal', 0):.0%}, 次日收盘 {_fmt(v.get('co'))}" for k, v in dp.items() if v.get("n"))
                     + "(想接的话提前挂 board_dip 条件单, 开板不会叫醒你)")
    return f"[{rng} 统计, 只摆事实不拦单] " + " || ".join(L)


def limit_named(D, upto="23:59:59"):
    return sorted(c for c, hs in named(D, upto).items() if any(h["act"] in ("封板", "冲板") and h["t"] >= "09:25:00" for h in hs) and c[:1] in "036")


def tag(code, D, upto="23:59:59"):
    hs = (named(D, upto) or {}).get(str(code))
    if not hs:
        return ""
    h = hs[-1]
    return f"⚠电报{h['t'][:5]}·{h['act']}({h['lead']})"


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = sys.argv[1:]
    D = a[0] if a else dt.date.today().isoformat()
    up = a[1] if len(a) > 1 else "23:59:59"
    N = named(D, up)
    print(f"{D} ≤{up} 被点名 {len(N)} 只; 封板 / 冲板 {len(limit_named(D, up))} 只")
    for c in (limit_named(D, up)[:2] + list(N)[:1]):
        print(c, item(c, D, up)[:900])
