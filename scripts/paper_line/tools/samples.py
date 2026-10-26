# -*- coding: utf-8 -*-
"""samples.py — 全体导师正负样例(10/24 用户: 不管是今天的导师还是被排除的导师, 他们的正负样例都是参考依据;
买入前必须把负样例找出来, 防止只看正例觉得买入必赚; 零 token, 只读事件本体 downloads/ontology/ontology.db)

两项(只用 D 之前的数据):
  全体导师同票样例  这只票上全部导师(含被排除 / 停更的 = 样例)的买入: 正 / 负 / 平 计数 + 负样例逐条(导师 / 角色 / 日期 / 时刻 / 打法 / 结果) + 最近正样例
  同情境样例        这只票上一交易日的状态(首板 / 二板 / 炸板 / 回调 1~3 / 大涨…) → 历史上全部导师买入"前一天也是这个状态"的票: 正负计数 + 结果全分布 + 负样例逐条
角色: 今天的导师 = results/_live/<D>/selected_mentors.json 的 active(没有这个文件时: 登记表里没退出 paper 的) · 其余 = 样例(只能当证据)
标签口径: 同 case_label(买入看之后第一次卖出的盈亏; 没卖过看买入日收盘→次日收盘)
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "lib")]
import dist_full as DF   # noqa: E402

DB = ROOT / "downloads" / "ontology" / "ontology.db"
_M = {}


def _load():
    if "trades" in _M:
        return _M
    c = sqlite3.connect(DB)
    T = []
    for code, d, tags, out in c.execute("select code, d, tags, out from event where kind='trade'"):
        t, o = json.loads(tags), json.loads(out)
        if t.get("side") == "买" and t.get("label") in ("正", "负", "平"):
            T.append({"code": code, "d": d, "m": t["mentor"], "play": t.get("play") or "-", "lb": t["label"], "v": o.get("v"), "tm": (o.get("time") or "")[:5]})
    S = {}
    for code, d, tags in c.execute("select code, d, tags from event where kind='day'"):
        S[(code, d)] = json.loads(tags).get("state")
    days = sorted({d for _, d in S})
    c.close()
    _M.update(trades=T, state=S, days=days)
    return _M


def _prev(d):
    import bisect
    days = _load()["days"]
    i = bisect.bisect_left(days, d)
    return days[i - 1] if i > 0 else None


def roles(D):
    """{导师 id: '导师' | '样例'}"""
    f = ROOT / "results" / "_live" / D / "selected_mentors.json"
    act = None
    if f.exists():
        try:
            act = set(json.loads(f.read_text(encoding="utf-8")).get("active") or [])
        except ValueError:
            act = None
    if act is None:
        try:
            import mentors as MT
            act = set(MT.active_ids())
        except Exception:   # noqa: BLE001
            act = set()
    return lambda m: "导师" if m in act else "样例"


def _fmt(x, role):
    return f"{x['m']}({role(x['m'])}) {x['d'][5:]}{(' ' + x['tm']) if x['tm'] else ''} {x['code']} {x['play']} → {x['v']:+.1f}%" if x.get("v") is not None else f"{x['m']} {x['d'][5:]} {x['code']}"


def _block(xs, role, n_neg=8, n_pos=4):
    neg = sorted((x for x in xs if x["lb"] == "负"), key=lambda x: x["d"], reverse=True)
    pos = sorted((x for x in xs if x["lb"] == "正"), key=lambda x: x["d"], reverse=True)
    cnt = {k: sum(1 for x in xs if x["lb"] == k) for k in ("正", "负", "平")}
    vals = [x for x in xs if x.get("v") is not None]
    s = f"买入 {len(xs)} 笔: 正 {cnt['正']} / 负 {cnt['负']} / 平 {cnt['平']}"
    if len(vals) >= 3:
        s += f" | 结果 {DF.line(DF.full(vals, key=lambda x: x['v'], tag=lambda x: x['m'] + ' ' + x['d'][5:] + ' ' + x['code']))}"
    if neg:
        s += f" | ⚠负样例({len(neg)}): " + "; ".join(_fmt(x, role) for x in neg[:n_neg]) + (f" …另 {len(neg) - n_neg} 笔" if len(neg) > n_neg else "")
    if pos:
        s += " | 正样例(最近): " + "; ".join(_fmt(x, role) for x in pos[:n_pos])
    return s, cnt


def lines(code, D):
    if not DB.exists():
        return [("全体导师同票样例", "没有事件本体(先跑 scripts/ontology/build.py)")]
    M, role = _load(), roles(D)
    out = []
    same = [x for x in M["trades"] if x["code"] == code and x["d"] < D]
    if same:
        s, _ = _block(same, role)
        out.append(("全体导师同票样例", s))
    else:
        out.append(("全体导师同票样例", "没有任何导师(含样例)买过这只票"))
    p = _prev(D)
    st = M["state"].get((code, p)) if p else None
    if st:
        sit = [x for x in M["trades"] if x["d"] < D and (pp := _prev(x["d"])) and M["state"].get((x["code"], pp)) == st]
        if sit:
            s, _ = _block(sit, role)
            out.append(("同情境样例", f"本票 {p[5:]} 状态={st} → 历史上全部导师买入'前一天也是 {st}'的票: {s}"))
        else:
            out.append(("同情境样例", f"本票 {p[5:]} 状态={st}, 历史上没有导师买过同状态的票"))
    else:
        out.append(("同情境样例", f"本票上一交易日不在强势股库(没有首板 / 炸板 / 回调这类状态), 无同情境样例"))
    return out


def neg_count(text):
    """从必查文本里读 ⚠负样例(n) 的总数(给 harness 用)"""
    import re
    return sum(int(x) for x in re.findall(r"⚠负样例\((\d+)\)", text or ""))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for k, v in lines(sys.argv[1], sys.argv[2]):
        print(f"- {k}: {v}")
