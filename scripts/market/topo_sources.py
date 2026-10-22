# -*- coding: utf-8 -*-
"""topo_sources.py — 拓扑的非统计来源(10/21 用户教学: 近期涨停分析权重最高 + md/rules.md 桃哥板块地图 + 用户口述; 零 token 零请求)

来源:
  涨停归类  md/<季度>/<日>.md 涨停表(行 "| 名称 <br>代码 | 首板/N天M板 | 涨幅 | 时间 | 题材A+题材B |"), 同一天同一题材里的票互为"涨停共振";
            近 20 个交易日 = 近期(权重最高), 21~120 个交易日 = 更早(归"其他")。按天衰减: 半衰期 5 个交易日
  rules.md  md/rules.md 的 "## 大类 / ### 小节" + 表格(代码或名称), 同小节 = 同簇, 同大类不同小节 = 弱同簇
  人工      scripts/market/topology_manual.json  {"603629": {"次簇:AI 硬件大类": ["002463", ...]}}  用户口述, 单独列出不参与配比
被 topology.py build() 调用; 也可单独: python topo_sources.py --show 603629 [--date D]
"""
import argparse
import datetime as dt
import json
import math
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MD = ROOT / "md"
HALF = 5.0
ROW = re.compile(r"^\|\s*([^|<]+?)\s*<br>\s*(\d{6})\s*\|\s*(首板|\d+\s*天\s*\d+\s*板|\d+\s*板)[^|]*\|[^|]*\|[^|]*\|\s*([^|]+?)\s*\|")


def _md_days(D, back):
    fs = sorted(p for p in MD.glob("20*S*/20??-??-??.md") if p.stem <= D)
    return fs[-back:]


def limit_up_themes(D, back=120):
    """[(日, {题材: set(代码)})], 只用 ≤ D 的 md(拓扑在 D 收盘后建, 和日线口径一致)"""
    out = []
    for f in _md_days(D, back):
        th = defaultdict(set)
        try:
            for l in f.read_text(encoding="utf-8", errors="replace").splitlines():
                m = ROW.match(l)
                if m:
                    for t in re.split(r"[+＋/、]", m.group(4)):
                        t = t.strip()
                        if t and t not in ("其他", "-"):
                            th[t].add(m.group(2))
        except OSError:
            continue
        if th:
            out.append((f.stem, th))
    return out


def lu_pairs(D, recent=20, back=120):
    """{代码: {邻居: [近期分, 更早分, {题材: 次数}]}} + 有涨停记录的代码集"""
    days = limit_up_themes(D, back)
    P = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, defaultdict(int)]))
    seen = set()
    n = len(days)
    for k, (d, th) in enumerate(days):
        age = n - 1 - k
        w = 0.5 ** (age / HALF)
        slot = 0 if age < recent else 1
        for t, cs in th.items():
            if len(cs) > 40:   # 题材太泛(如"业绩")一天几十只, 共现不说明关联
                continue
            seen |= cs
            for a in cs:
                for b in cs:
                    if a != b:
                        e = P[a][b]
                        e[slot] += w if slot == 0 else 0.5 ** ((age - recent) / 20)
                        e[2][t] += 1
    return P, seen


def _name_map():
    m = {}
    for f in sorted((ROOT / "downloads" / "market").glob("20*/security_master.jsonl"))[-1:]:
        for l in f.open(encoding="utf-8"):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            nm = re.sub(r"\s+", "", str(r.get("name") or ""))
            if nm and r.get("code"):
                m[nm] = str(r["code"])
    return m


def rules_clusters():
    """{代码: [(大类, 小节)]}; 名称按证券主表转代码, 转不到的跳过"""
    f = MD / "rules.md"
    if not f.exists():
        return {}
    nm = _name_map()
    big = sec = None
    sub, grp = "", 0
    out = defaultdict(list)
    for l in f.read_text(encoding="utf-8", errors="replace").splitlines():
        if l.startswith("## "):
            big, sec = l[3:].strip(), None
            continue
        if l.startswith("### "):
            sec, sub, grp = l[4:].strip(), "", 0
            continue
        if not (sec and l.startswith("|")) or re.fullmatch(r"\|[\s:\-|]*\|?", l.strip()):
            continue
        cells = [c.strip() for c in l.strip("|").split("|")]
        if not any(cells):   # 空行 = 小节内换一组(如 AI PCB 的 核心 6 只 / 边缘 / 小厂 / 覆铜板 / 车工业)
            grp += 1
            sub = ""
            continue
        code = next((c for c in cells[:2] if re.fullmatch(r"\d{6}", c)), None)
        if not code:
            for c in cells[:2]:
                code = nm.get(re.sub(r"[\s\-]", "", c)) or nm.get(re.sub(r"\s+", "", c))
                if code:
                    break
        if not code:
            if cells[0] and not re.search(r"代码|名称", cells[0]) and len([c for c in cells if c]) == 1:
                sub = cells[0]   # 组标题行(如"PCB 车工业 5G")
            continue
        key = (big, sec, f"{grp}:{sub}" if sub else str(grp))
        if key not in out[code]:
            out[code].append(key)
    return dict(out)


def manual():
    f = ROOT / "scripts" / "market" / "topology_manual.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", required=True)
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    P, seen = lu_pairs(a.date)
    nb = sorted(P.get(a.show, {}).items(), key=lambda kv: -(kv[1][0] + 0.25 * kv[1][1]))[:15]
    print("涨停共振:", [(c, round(v[0], 2), round(v[1], 2), dict(v[2])) for c, v in nb])
    R = rules_clusters()
    print("rules.md 簇:", R.get(a.show))
    print("人工:", manual().get(a.show))


if __name__ == "__main__":
    main()
