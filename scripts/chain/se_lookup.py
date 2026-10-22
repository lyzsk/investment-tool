# -*- coding: utf-8 -*-
"""se_lookup.py — 01→06 链的"脚本替模型查料"(10/21 晚用户定: skills / 07 复盘 / md 原文 / 今日更早版本推理 全部可查, 但不整份塞, 按关键词机械摘段)

auto_pack(...)   每次触发由脚本按"本次涉及的票(代码 + 名称)/ 规则编号"自动检索, 摘相关段落附进 01(零 token, 毫秒级, 每类有上限)
lookup(...)      同一套检索, 给对照变体 C(@toolcall)当模型可调用的工具: 模型自己写关键词查
来源: versions = 今天本链更早版本的 02~06 原文 | skills = 本导师 rules.md / cases.md / cases_auto.jsonl / case_log | review07 = 本导师近 5 个交易日旧链 07 复盘 |
      md = 当天和前一交易日的 md(早报 / 发哥 / B 站三 UP / 午评 / 涨停分析 / 收评) | topo = 拓扑(持仓 / 候选的关联票)
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAPS = {"versions": 8000, "skills": 8000, "review07": 6000, "md": 8000}


def _rd(p):
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _units(text):
    """切成检索单元: 表格行一行一个; 其余按空行 / 标题分段; 每段记它所在的最近标题"""
    out, head, buf = [], "", []

    def flush():
        if buf:
            t = "\n".join(buf).strip()
            if t:
                out.append((head, t))
            buf.clear()
    for l in text.splitlines():
        if re.match(r"^#{1,6} ", l):
            flush()
            head = l.strip("# ").strip()
            continue
        if l.startswith("|"):
            flush()
            if not re.match(r"^\|[\s\-:|]+\|$", l):
                out.append((head, l.strip()))
            continue
        if not l.strip():
            flush()
            continue
        buf.append(l)
    flush()
    return out


def _grab(text, keys, cap, src):
    keys = [k for k in keys if k and len(k) >= 2]
    if not keys:
        return []
    got, used = [], 0
    for head, u in _units(text):
        if any(k in u for k in keys):
            piece = f"[{src}{' · ' + head[:40] if head else ''}] {u[:1200]}"
            if used + len(piece.encode()) > cap:
                break
            got.append(piece)
            used += len(piece.encode())
    return got


def _md_files(D):
    fs = sorted(ROOT.glob("md/*/20*.md"))
    fs = [f for f in fs if f.stem <= D]
    return fs[-2:]


def search(skill, D, keys, live_dir=None, sources=("versions", "skills", "review07", "md"), skip_ver=None, caps=None):
    caps = {**CAPS, **(caps or {})}
    out = {}
    if "versions" in sources and live_dir:
        vs = sorted(d for d in (Path(live_dir) / "versions").glob("*") if d.is_dir())
        vs = [v for v in vs if v.name != skip_ver]
        txt = "\n\n".join(f"# 版本 {v.name}\n" + "\n\n".join(_rd(v / n) for n in ("02_market.md", "03_bull.md", "03_bear.md", "04_pick.md", "05_risk.md", "06_final.md")) for v in vs[::-1])
        out["versions"] = _grab(txt, keys, caps["versions"], "今日更早版本")
    if "skills" in sources:
        d = ROOT / "skills" / f"{skill}-skill" / "persona"
        txt = _rd(d / "rules.md") + "\n\n" + _rd(d / "cases.md") + "\n\n" + "\n\n".join(_rd(f) for f in sorted((d / "case_log").glob("*.md"))[-3:])
        g = _grab(txt, keys, caps["skills"] - 1500, "skills")
        codes = [k for k in keys if re.fullmatch(r"\d{6}", k)]
        rows = []
        for l in _rd(d / "cases_auto.jsonl").splitlines()[::-1]:
            if any(c in l for c in codes):
                rows.append("[skills · cases_auto] " + l[:300])
                if len(rows) >= 5:
                    break
        out["skills"] = g + rows
    if "review07" in sources:
        dirs = sorted((ROOT / "results" / f"{skill}_chain").glob("live-2026*"))
        dirs = [x for x in dirs if x.name.replace("live-", "") < D.replace("-", "")][-5:]
        txt = "\n\n".join(f"# 07 复盘 {x.name[5:]}\n" + _rd(x / "07_review.md") for x in dirs[::-1])
        g = _grab(txt, keys, caps["review07"] - 2000, "07 复盘")
        les = _grab(txt, ["教训", "根因", "下次"], 2000, "07 教训")
        out["review07"] = g + [x for x in les if x not in g]
    if "md" in sources:
        txt = "\n\n".join(f"# md {f.stem}\n" + _rd(f) for f in _md_files(D)[::-1])
        out["md"] = _grab(txt, keys, caps["md"], "md")
    return out


def topo_block(codes, D):
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "market"))
        import topology as TOPO
        rows = TOPO.brief(list(codes)[:20], D)
    except Exception as e:   # noqa: BLE001
        return f"(拓扑取不到: {e!r}"[:120] + ")"
    return "\n".join(f"- {r}" for r in rows) or "(这些票没有拓扑数据)"


def _buys(skill):
    """本导师历史买入腿(cases_auto.jsonl: 买入那一刻的特征 feat + 打法 play + 结果 result: r_close 当日收 / r_next 次日收 / r_5d 5 日)"""
    out = []
    for l in _rd(ROOT / "skills" / f"{skill}-skill" / "persona" / "cases_auto.jsonl").splitlines():
        try:
            x = json.loads(l)
        except ValueError:
            continue
        if x.get("event") is None and x.get("side") == "买" and isinstance(x.get("feat"), dict) and isinstance(x.get("result"), dict):
            out.append(x)
    return out


def playbook(skill, D):
    """10/21 晚(用户: 拟人是为了收益稳定, 向成功案例学习): 本导师各打法的真实战绩(只用 D 之前的买入), 按 5 日收益排序"""
    import statistics as st
    by = {}
    for x in _buys(skill):
        if x.get("date", "") >= D:
            continue
        r = x["result"]
        by.setdefault(x.get("play") or "未分类", []).append(r)
    rows = []
    for p, rs in by.items():
        r5 = [r["r_5d"] for r in rs if r.get("r_5d") is not None]
        rn = [r["r_next"] for r in rs if r.get("r_next") is not None]
        if len(r5) < 3:
            continue
        rows.append((st.mean(r5), p, len(rs), sum(1 for v in r5 if v > 0) / len(r5), st.mean(rn) if rn else None, min(r5)))
    rows.sort(reverse=True)
    if not rows:
        return "(本导师没有带结果的历史买入样本)"
    L = ["| 打法 | 次数 | 5 日均收益 | 5 日胜率 | 次日均收益 | 5 日最差 |", "|---|---|---|---|---|---|"]
    for m5, p, n, w, mn, worst in rows:
        L.append(f"| {p} | {n} | {m5 * 100:+.1f}% | {w * 100:.0f}% | {('%+.1f%%' % (mn * 100)) if mn is not None else '-'} | {worst * 100:+.1f}% |")
    return "\n".join(L)


def _daily_prev(code, D):
    try:
        k = json.loads(_rd(ROOT / "downloads" / "quotes" / "daily" / f"{code}.json") or "{}").get("klines") or []
    except ValueError:
        return None
    k = [x for x in k if x.get("d", "") < D][-6:]
    if len(k) < 2:
        return None
    pct_prev = k[-1]["c"] / k[-2]["c"] - 1
    ret5 = k[-1]["c"] / k[0]["c"] - 1
    return pct_prev, ret5


def similar_buys(skill, D, feats, names=None, k=4, max_codes=6):
    """当前候选(盘中特征) ↔ 本导师历史买点的最近邻(只用 D 之前): 特征 = 当时涨幅 / 日内位置 / 相对开盘 / 昨日涨幅 / 近 5 日涨幅; 给出相似历史买点的结果"""
    hist = [x for x in _buys(skill) if x.get("date", "") < D and x["result"].get("r_close") is not None]
    if not hist:
        return ""
    L = []
    for c, f in list(feats.items())[:max_codes]:
        if f.get("chg") is None:
            continue
        dp = _daily_prev(c, D)
        if not dp:
            continue
        o = f.get("o")
        q = {"buy_pct": f["chg"] / 100, "pos_in_day": (f.get("pos") or 50) / 100, "vs_open": (f["p"] / o - 1) if o and f.get("p") else 0.0,
             "pct_prev": dp[0], "ret5_prev": dp[1]}
        w = {"buy_pct": 1 / 0.03, "pos_in_day": 1 / 0.25, "vs_open": 1 / 0.03, "pct_prev": 1 / 0.04, "ret5_prev": 1 / 0.10}
        scored = []
        for x in hist:
            ft = x["feat"]
            try:
                dist = sum(((float(ft.get(kk) or 0) - v) * w[kk]) ** 2 for kk, v in q.items()) ** 0.5
            except (TypeError, ValueError):
                continue
            scored.append((dist, x))
        scored.sort(key=lambda t: t[0])
        top = scored[:k]
        if not top:
            continue
        rs = [x["result"] for _, x in top]
        r5 = [r["r_5d"] for r in rs if r.get("r_5d") is not None]
        nm = (names or {}).get(c, "")
        L.append(f"- {c}{nm} 此刻: 涨 {q['buy_pct'] * 100:+.1f}% / 日内位置 {q['pos_in_day']:.2f} / 昨日 {q['pct_prev'] * 100:+.1f}% / 近 5 日 {q['ret5_prev'] * 100:+.1f}% → 导师最像的 {len(top)} 次买点: "
                 + "; ".join(f"{x['date']} {x.get('name', '')}({x.get('play') or '-'}, 当时涨 {x['feat'].get('buy_pct', 0) * 100:+.1f}% → 当日收 {x['result']['r_close'] * 100:+.1f}%"
                             + (f" / 5 日 {x['result']['r_5d'] * 100:+.1f}%" if x["result"].get("r_5d") is not None else "") + ")" for _, x in top)
                 + (f" | 这几次 5 日均 {sum(r5) / len(r5) * 100:+.1f}%" if r5 else ""))
    return "\n".join(L)


def auto_pack(skill, D, codes, names, rule_ids, live_dir=None, skip_ver=None, feats=None):
    """每次触发脚本自动查: 关键词 = 持仓 / 候选的代码 + 名称 + 上一版引用的规则编号; 返回 markdown 块"""
    keys = list(dict.fromkeys([*codes, *[n for n in names if n], *rule_ids]))
    res = search(skill, D, keys, live_dir, skip_ver=skip_ver)
    L = ["# 脚本按本次涉及的票 / 规则编号检索出的相关原文(零 token 机械摘段; 每段前面标了来源)"]
    for k, title in (("versions", "今日更早版本里提到这些票 / 规则的推理"), ("skills", "本导师 skills 里提到这些票 / 规则的段落"),
                     ("review07", "本导师近 5 日 07 复盘里相关的段落和教训"), ("md", "当天 / 前一交易日 md 里提到这些票的段落")):
        if res.get(k):
            L.append(f"## {title}\n" + "\n".join(res[k]))
    L.append("## 拓扑(持仓 / 候选的关联票, 括号 = 昨日涨跌; 只用前一晚的拓扑)\n" + topo_block(codes, D))
    L.append("## 本导师各打法的真实战绩(历史买入 → 5 日 / 次日收益; 向赚钱的打法学, 少做亏钱的打法)\n" + playbook(skill, D))
    if feats:
        sb = similar_buys(skill, D, feats, dict(zip(codes, names)))
        if sb:
            L.append("## 当前候选 ↔ 导师历史上最像的买点(盘中特征最近邻; 看导师在类似位置买进后的结果)\n" + sb)
    return "\n\n".join(L)


TOOL = {"name": "lookup", "description": "按关键词(票名 / 6 位代码 / 规则编号 / 词语)查: 本导师 skills(规则全文 / 案例)、近 5 日 07 复盘、当天和前一交易日 md 原文、今天本链更早版本的推理。返回匹配的原文段落(标来源)。每步最多用 2 次, 用完直接写答案。",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string", "description": "关键词, 多个用空格分开"},
                                                         "source": {"type": "string", "enum": ["all", "skills", "review07", "md", "versions"]}},
                         "required": ["query"]}}


def lookup(skill, D, live_dir, query, source="all"):
    keys = [k for k in re.split(r"[\s,，;；]+", str(query or "")) if k][:8]
    srcs = ("versions", "skills", "review07", "md") if source in (None, "", "all") else (source,)
    res = search(skill, D, keys, live_dir, sources=srcs, caps={k: 5000 for k in CAPS})
    parts = [x for v in res.values() for x in v]
    return "\n".join(parts)[:12000] or f"(没有找到包含 {keys} 的段落)"


if __name__ == "__main__":
    t = auto_pack("zhiyingjuexin", "2026-10-21", ["300209", "002242"], ["天迈科技", "九阳股份"], ["R10", "R26"])
    print(len(t.encode()), "bytes")
    print(t[:3000])
