# -*- coding: utf-8 -*-
"""strong_themes.py — 今日强题材(10/24 模块 4; 零 token)

两个来源(只用 ≤ 此刻的数据):
  T-1   前一交易日 md「涨停分析」: 每个题材的涨停家数 / 最高板 / 生命周期阶段(theme_life) / 成员(按板数从高到低)
  盘中  collect_mood 快照里的涨停池(财联社 up_reason 题材): 此刻每个题材涨停几家 / 最高板 / 成员 / 首封时刻; 炸板池同题材几家
能力圈(按导师): 板块占比(mentor_scope.board, 占比 < 5% 的板块算圈外; ST 看 ST 占比) · 转债导师(土豆) = 强题材成员的正股有转债才算圈内, 候选给转债代码
产出:
  candidates(skill, D, at, k=30, per=6) → [(代码, 说明)]  圈内强题材前 k 只(先盘中后 T-1, 每个题材最多 per 只, 板数高的先) —— 给候选池"今日强题材"来源, 不被 30 只截掉
  block(skill, D, at) → 01 的「今日强题材 / 盘中题材强度」节: 圈内 / 圈外分开列; 圈外的标"不在能力圈", 04 要写看到了、为什么不做
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "paper_line" / "tools"), str(ROOT / "scripts" / "market")]
MKT = ROOT / "downloads" / "market"
_C = {}


def board_of(code, name=""):
    if "ST" in (name or ""):
        return "ST"
    if code[:3] in ("300", "301"):
        return "创业板"
    if code[:3] in ("688", "689"):
        return "科创板"
    if code[:1] in ("4", "8", "9") and code[:3] != "900":
        return "北交所"
    return "沪深主板"


def scope(skill):
    if "scope" not in _C:
        try:
            _C["scope"] = json.loads((ROOT / "scripts" / "tzzb" / "mentor_scope.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _C["scope"] = {}
    s = _C["scope"].get(skill) or {}
    if skill == "buchitudou0" or s.get("kind") == "no_stat" and skill == "buchitudou0":
        return {"cb": True}
    b = s.get("board") or {}
    return {"cb": False, "boards": {k for k, v in b.items() if v >= 0.05} or {"沪深主板"}}


def cb_of(D):
    """正股代码 → (转债代码, 转债名)"""
    k = ("cb", D)
    if k not in _C:
        m = {}
        for d in sorted((p.name for p in MKT.glob("20*") if p.name < D), reverse=True)[:5]:
            f = MKT / d / "cb_facts.jsonl"
            if f.exists():
                for l in f.open(encoding="utf-8"):
                    x = json.loads(l)
                    if x.get("stock"):
                        m.setdefault(x["stock"], (x["code"], x.get("name")))
                break
        _C[k] = m
    return _C[k]


def t1_themes(D):
    """前一交易日涨停分析 → {题材: {"n", "max_b", "stage", "day_n", "mem": [(代码, 名, 板)]}}"""
    k = ("t1", D)
    if k in _C:
        return _C[k]
    import theme_life as TL
    rows = TL.rows_canon()
    days = sorted({r[0] for r in rows if r[0] < D})
    out = {}
    if days:
        d1 = days[-1]
        by = defaultdict(list)
        for r in rows:
            if r[0] == d1 and r[3]:
                by[r[1]].append((r[3], r[2], r[4] or 0, r[5]))
        for th, mem in by.items():
            zt = [m for m in mem if m[3]]
            if not zt:
                continue
            L = TL.life(th, D) or {}
            out[th] = {"d": d1, "n": len(zt), "max_b": max(m[2] for m in zt), "stage": str(L.get("阶段") or "").split("(")[0], "day_n": L.get("本波第几天"),
                       "mem": sorted(((m[0], m[1], m[2]) for m in zt), key=lambda x: -x[2])}
    _C[k] = out
    return out


def live_themes(D, at):
    """盘中: 最近一张情绪快照的涨停池 → {题材: {"n", "max_b", "mem": [(代码, 名, 板, 首封)], "zb": 炸板家数}}"""
    import collect_mood as CM
    rs = [r for r in CM.rows(D, at) if r.get("up")]
    if not rs:
        return {}, None
    r = rs[-1]
    by = defaultdict(list)
    for c, n, lb, why, t in r["up"]:
        if why:
            by[why].append((c, n, lb, t))
    zb = defaultdict(int)
    for c, n, why in r.get("zb_list") or []:
        if why:
            zb[why] += 1
    out = {th: {"n": len(m), "max_b": max(x[2] for x in m), "mem": sorted(m, key=lambda x: (-x[2], x[3])), "zb": zb.get(th, 0)} for th, m in by.items()}
    return out, r["t"]


def _in_circle(sc, code, name, D):
    if sc["cb"]:
        return cb_of(D).get(code)
    return (code, name) if board_of(code, name) in sc["boards"] else None


def cb_active(D, n=30):
    """转债导师的候选来源(10/24): 前一交易日成交额最大的 n 只转债 → [(代码, 说明)]"""
    k = ("cba", D, n)
    if k in _C:
        return _C[k]
    sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
    import manual_backfill as mb
    c = mb.db().cursor()
    c.execute("select max(trade_date) from investment_market.kline_day where symbol='sh000001' and trade_date < %s and is_deleted=0", (D,))
    d1 = c.fetchone()[0]
    c.execute("select right(k.symbol, 6), s.name, k.amount, k.close / k.pre_close - 1 from investment_market.kline_day k join investment_market.security_master s "
              "on s.symbol=k.symbol and s.sec_type='CB' where k.trade_date=%s and k.is_deleted=0 and k.pre_close > 0 order by k.amount desc limit %s", (d1, n))
    _C[k] = [(code, f"转债活跃·{str(d1)[5:]} 成交额第 {i} {float(a) / 1e8:.1f} 亿 {float(p) * 100:+.1f}%") for i, (code, nm, a, p) in enumerate(c.fetchall(), 1)]
    return _C[k]


def candidates(skill, D, at, k=30, per=6):   # 10/24: 候选池 30 → 100 后放宽(原 k=5、每题材 2 只)
    sc = scope(skill)
    out, seen = [], set()
    live, lt = live_themes(D, at)
    srcs = [("盘中", sorted(live.items(), key=lambda x: (-x[1]["n"], -x[1]["max_b"]))), ("T-1", sorted(t1_themes(D).items(), key=lambda x: (-x[1]["n"], -x[1]["max_b"])))]
    for tag, ths in srcs:
        for th, v in ths:
            got = 0
            for m in v["mem"]:
                hit = _in_circle(sc, m[0], m[1], D)
                if not hit or hit[0] in seen:
                    continue
                seen.add(hit[0])
                out.append((hit[0], f"今日强题材·{tag} {th}({v['n']} 家涨停, 最高 {v['max_b']} 板){'' if hit[0] == m[0] else ' 正股 ' + m[1]}"))
                got += 1
                if got >= per or len(out) >= k:
                    break
            if len(out) >= k:
                return out
    return out


def block(skill, D, at, top=8):
    sc = scope(skill)
    L = ["## 今日强题材 / 盘中题材强度(代码按本导师能力圈分圈内 / 圈外; 圈外的看到了也要在 04 的 not_doing 写为什么不做)"]
    live, lt = live_themes(D, at)

    def fmt(th, v, live_=False):
        mem = v["mem"][:6]
        inn = [m for m in mem if _in_circle(sc, m[0], m[1], D)]
        tag = "" if inn else " ⚠不在能力圈"
        ms = "、".join(f"{m[1]}({m[0]}){m[2]}板" + (f"@{m[3]}" if live_ and len(m) > 3 and m[3] else "") for m in mem)
        extra = f" 炸板 {v['zb']} 家" if live_ else f" 阶段 {v['stage']} 本波第 {v['day_n']} 天"
        return f"- {th}: 涨停 {v['n']} 家, 最高 {v['max_b']} 板,{extra}{tag} | {ms}"
    if live:
        L.append(f"盘中({lt[:5]} 涨停池):")
        L += [fmt(th, v, True) for th, v in sorted(live.items(), key=lambda x: (-x[1]["n"], -x[1]["max_b"]))[:top]]
    else:
        L.append("盘中: 暂无(09:25 后情绪面板才有涨停池)")
    t1 = t1_themes(D)
    if t1:
        d1 = next(iter(t1.values()))["d"]
        L.append(f"T-1({d1[5:]} 涨停分析):")
        L += [fmt(th, v) for th, v in sorted(t1.items(), key=lambda x: (-x[1]["n"], -x[1]["max_b"]))[:top]]
    if sc["cb"]:
        L.append("(转债导师: 圈内 = 强题材成员的正股有转债, 候选给转债代码)")
    return "\n".join(L)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = sys.argv[1:]
    skill, D, at = a[0], a[1], (a[2] if len(a) > 2 else "09:00:00")
    print(block(skill, D, at))
    print("候选:", candidates(skill, D, at))
