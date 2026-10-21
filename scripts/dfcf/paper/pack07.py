# -*- coding: utf-8 -*-
"""pack07.py — 07 复盘素材包(10/21 凌晨用户批 TODO 一-1; 零 token, 驱动器机械取数拼好注入, 不靠模型自己找)

用户口径(10/21):
  ① 固定清单, 全部机械取数:
     - 当日行情(要全): 持仓和成交票的日线、5 分钟 K、竞价一行、20 / 60 日箱体位置 —— 全部链公用, 增量追加(新票才算)
     - 导师真人: 当日买卖腿 + 近 20 个交易日同票操作 —— 公用, 增量
     - skill: 当天引用过的规则全文 + 其他导师的相似规则(文本相似度) + 按票(同票 + 拓扑邻居)命中的 cases / 操作日志 / 否决条款
     - 过往 lessons: 本链近 5 天 + 相似情况的 lessons(相似日的 lessons + 和今天归因检测项文本相似的)
     - 知识库: 只给 docs/knowledge 目录(用户还没验收)
     - 多日结算: 本链前几天的单现在结果如何(15:50 机械结算的产物)
  ② 包头第一节 = 覆盖表(每项有没有、多新), 缺的写清楚
  ③ 不限篇幅, 长了就加索引: 公用部分落盘 results/_pack07/<日>/ (market.md / mentor_<导师>.md + 行号索引), 本链只注入本链相关的全文 + 公用文件的行号索引
相似度: 字符二元组 TF-IDF 余弦(numpy, 零依赖, 可复现); 以后可换本地 bge-m3 向量
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/pack07.py --skill a658 --date 2026-10-20 [--print]
被 run_chain.py 07 步调用: block_07(skill, D)(开关 CHAIN_PACK07)
"""
import argparse
import datetime as dt
import gzip
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MKT = ROOT / "downloads" / "market"
DAILY = ROOT / "downloads" / "quotes" / "daily"
RES = ROOT / "results"
SK = ROOT / "skills"
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts" / "tzzb"))
sys.path.insert(0, str(ROOT / "scripts" / "market"))
import mentors   # noqa: E402

NAMES = None


def _jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def name_of(c):
    global NAMES
    if NAMES is None:
        NAMES = _jl(HERE / "names.json", {}) or {}
    return NAMES.get(c, "")


def sym(c):
    return ("sh" if c.startswith(("6", "5", "9", "11")) else "bj" if c.startswith(("8", "4", "92")) else "sz") + c


def trade_days(D, n):
    ds = sorted(p.name for p in MKT.iterdir() if re.fullmatch(r"\d{4}-\d\d-\d\d", p.name) and p.name <= D and (p / "kline_day.jsonl").exists())
    return ds[-n:]


# ============================================================ ① 当日行情(公用, 增量)
_DAY, _BOOK, _MIN, _AUC = {}, {}, {}, {}


def day_bar(D, c):
    if D not in _DAY:
        m = {}
        f = MKT / D / "kline_day.jsonl"
        if f.exists():
            for l in f.open(encoding="utf-8"):
                try:
                    r = json.loads(l)
                    m[r["symbol"][2:]] = r
                except (ValueError, KeyError):
                    pass
        _DAY[D] = m
    return _DAY[D].get(c)


def book_5m(D, c):
    """3 秒盘口 → 5 分钟 K(开高低收 + 截至该 5 分钟的均价线); 没有 = None"""
    if D not in _BOOK:
        m = {}
        for f, op in ((MKT / D / "book_snap.jsonl", open), (MKT / D / "book_snap.jsonl.gz", gzip.open)):
            if f.exists():
                with op(f, "rt", encoding="utf-8") as fh:
                    for l in fh:
                        try:
                            r = json.loads(l)
                        except ValueError:
                            continue
                        if r.get("p") and "09:30:00" <= r.get("t", "") <= "15:00:59":
                            m.setdefault(str(r["s"])[2:], []).append((r["t"], float(r["p"]), float(r.get("v") or 0), float(r.get("a") or 0)))
                break
        _BOOK[D] = m
    rows = _BOOK[D].get(c)
    if not rows:
        return None
    return _agg5([(t[:5], p, v, a) for t, p, v, a in rows], cum=True)


def minute_5m(D, c):
    """分钟线(关注集 + 补抓) → 5 分钟 K; 没有 = None"""
    if D not in _MIN:
        m = {}
        for fn in ("kline_minute.jsonl", "kline_minute_extra.jsonl"):
            f = MKT / D / fn
            if f.exists():
                for l in f.open(encoding="utf-8"):
                    try:
                        r = json.loads(l)
                    except ValueError:
                        continue
                    m.setdefault(str(r["symbol"])[2:], []).append((r["barTime"][11:16], r["open"], r["high"], r["low"], r["close"], float(r.get("volume") or 0), float(r.get("amount") or 0)))
        _MIN[D] = m
    rows = _MIN[D].get(c)
    if not rows:
        return None
    out, cv, ca = {}, 0.0, 0.0
    for t, o, h, l, cl, v, a in sorted(rows):
        k = _bucket(t)
        cv, ca = cv + v, ca + a
        b = out.setdefault(k, [o, h, l, cl, 0])
        b[1], b[2], b[3], b[4] = max(b[1], h), min(b[2], l), cl, (ca / cv if cv else None)
    return out


def _bucket(hm):
    h, m = int(hm[:2]), int(hm[3:5])
    m5 = (m // 5) * 5
    return f"{h:02d}:{m5:02d}"


def _agg5(rows, cum):
    out = {}
    for t, p, v, a in sorted(rows):
        k = _bucket(t)
        b = out.setdefault(k, [p, p, p, p, None])
        b[1], b[2], b[3] = max(b[1], p), min(b[2], p), p
        b[4] = (a / v) if cum and v else b[4]
    return out


def auction_line(D, c):
    if D not in _AUC:
        _AUC[D] = (_jl(MKT / D / "auction_live_open.json", {}) or {}).get("symbols") or {}
    s = _AUC[D].get(sym(c))
    if not s:
        return None
    p920 = (s.get("p2_first") or s.get("p1") or {}).get("pct")
    fin = s.get("fin") or s.get("p2") or {}
    vr = s.get("vol_ratio")
    return (f"9:20 {p920:+.1f}% → 9:25 开 {fin.get('px')}({fin.get('pct', 0):+.1f}%)" if p920 is not None else f"9:25 开 {fin.get('px')}({fin.get('pct', 0):+.1f}%)") \
        + (f" | 竞价量=昨全天 {vr * 100:.1f}%" if vr else "") + (f" 【{'; '.join(s['tags'])}】" if s.get("tags") else "")


def box(D, c):
    k = (_jl(DAILY / f"{c}.json", {}) or {}).get("klines") or []
    k = [x for x in k if x.get("d", "") <= D]
    if len(k) < 20:
        return None, None
    cl = k[-1]["c"]
    out = {}
    for n in (20, 60):
        w = [x["c"] for x in k[-n:]]
        lo, hi = min(w), max(w)
        out[n] = (lo, hi, (cl - lo) / (hi - lo) if hi > lo else None)
    return out, k[-1]["d"]


def market_section(D, c):
    L, cov = [f"### {c} {name_of(c)}"], {}
    b = day_bar(D, c)
    if b:
        pct = (b["close"] / b["preClose"] - 1) * 100 if b.get("preClose") else None
        L.append(f"- 日线 {D}: 开 {b['open']} 高 {b['high']} 低 {b['low']} 收 {b['close']}" + (f"({pct:+.2f}%)" if pct is not None else "")
                 + f" | 前收 {b.get('preClose')} 涨停 {b.get('limitUp')} 跌停 {b.get('limitDown')}" + (f" | 换手 {b['turnoverRate']:.2f}%" if b.get("turnoverRate") else "")
                 + (f" | 额 {b['amount'] / 1e8:.2f} 亿" if b.get("amount") else ""))
    cov["日线"] = bool(b)
    bx, bd = box(D, c)
    if bx:
        L.append("- 箱体(收盘): " + " / ".join(f"{n} 日 {lo:g}~{hi:g} 位置 {'?' if pos is None else f'{pos:.2f}'}" for n, (lo, hi, pos) in bx.items()) + f"(日线缓存截至 {bd})")
    cov["箱体"] = bool(bx) and bd == D
    a = auction_line(D, c)
    L.append(f"- 竞价: {a or '无(不在竞价采集名单)'}")
    cov["竞价"] = bool(a)
    k5, src = book_5m(D, c), "3 秒盘口"
    if not k5:
        k5, src = minute_5m(D, c), "分钟线"
    if k5:
        L.append(f"- 5 分钟 K({src}; 时刻 开/高/低/收/均价线):")
        L.append("  " + " | ".join(f"{t} {o:g}/{h:g}/{l:g}/{cl:g}/{'—' if v is None else f'{v:.3f}'}" for t, (o, h, l, cl, v) in sorted(k5.items())))
    else:
        L.append("- 5 分钟 K: 无(不在 3 秒盘口名单, 也不在分钟线关注集)")
    cov["5分钟K"] = src if k5 else False
    return L, cov


def shared_market(D, codes):
    """公用行情文件: results/_pack07/<日>/market.md(增量追加) + market_index.json {code: {start, end, cov}}"""
    out = RES / "_pack07" / D
    out.mkdir(parents=True, exist_ok=True)
    f, fi = out / "market.md", out / "market_index.json"
    idx = _jl(fi, {}) or {}
    lines = f.read_text(encoding="utf-8").splitlines() if f.exists() else [f"# 07 素材包 · 当日行情(公用, 增量) {D}", ""]
    for c in codes:
        if c in idx:
            continue
        sec, cov = market_section(D, c)
        idx[c] = {"start": len(lines) + 1, "end": len(lines) + len(sec), "cov": cov}
        lines += sec + [""]
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    fi.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    return f, idx, lines


# ============================================================ ② 导师真人(公用, 增量)
def mentor_section(skill, D, codes):
    try:
        from gen_tzzb_profile import load_legs
        legs = load_legs(skill)
    except Exception:   # noqa: BLE001
        return [f"- 导师 {skill} 没有逐笔腿(UP / 对照组, 或账本未抓)"], False
    days20 = set(d for d in trade_days(D, 21))
    today = [x for x in legs if str(x.get("trans_date", ""))[:10] == D]
    cs = set(codes) | {str(x.get("stock_code")) for x in today}
    recent = [x for x in legs if str(x.get("trans_date", ""))[:10] in days20 and str(x.get("stock_code")) in cs and str(x.get("trans_date", ""))[:10] != D]
    f = lambda x: f"{x['trans_date'][5:16]} {'买' if x.get('op') == '1' else '卖'} {x.get('stock_code')}{x.get('stock_name', '')} {float(x.get('trans_price') or 0):g}×{x.get('trans_count')}"
    L = [f"### 导师 {skill} 真人当日买卖腿({D}, {len(today)} 条)"] + ([f"- {f(x)}" for x in sorted(today, key=lambda x: x['trans_date'])] or ["- 当日无成交(或账本还没更新到今天)"])
    L += [f"### 导师 {skill} 近 20 个交易日同票操作({len(recent)} 条; 同票 = 本链当日持仓 / 成交票 + 导师当日成交票)"] + ([f"- {f(x)}" for x in sorted(recent, key=lambda x: x['trans_date'])] or ["- 无"])
    last = max((str(x.get("trans_date", ""))[:10] for x in legs), default="")
    return L, last


# ============================================================ ③ skill / cases / 错题 / lessons(相似度)
def _grams(s):
    s = re.sub(r"\s+", "", s)
    return [s[i:i + 2] for i in range(len(s) - 1)]


class Sim:
    """字符二元组 TF-IDF 余弦"""
    def __init__(self, docs):
        self.docs = docs
        tf = [Counter(_grams(d)) for d in docs]
        df = Counter(g for t in tf for g in t)
        n = len(docs)
        self.idf = {g: math.log((n + 1) / (c + 1)) + 1 for g, c in df.items()}
        self.vec = [self._v(t) for t in tf]

    def _v(self, t):
        v = {g: c * self.idf.get(g, 1.0) for g, c in t.items()}
        nrm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {g: x / nrm for g, x in v.items()}

    def top(self, q, k=5, skip=None):
        qv = self._v(Counter(_grams(q)))
        sc = []
        for i, v in enumerate(self.vec):
            if skip and skip(i):
                continue
            s = sum(x * v.get(g, 0.0) for g, x in qv.items())
            sc.append((s, i))
        return sorted(sc, reverse=True)[:k]


def _sections(f, pat):
    """按标题切节 → [(标题, 正文, 起始行号)]"""
    try:
        L = f.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out, cur = [], None
    for i, l in enumerate(L, 1):
        if re.match(pat, l):
            if cur:
                out.append(cur)
            cur = [l, [], i]
        elif cur:
            cur[1].append(l)
    if cur:
        out.append(cur)
    return [(t, "\n".join(b).strip(), ln) for t, b, ln in out]


_CORP = {}


def corpus():
    """全体导师规则 / cases / 操作日志 / 否决条款 → 统一条目 {kind, skill, id, title, text, file, line}"""
    if _CORP:
        return _CORP
    rules, cases = [], []
    for e in mentors.all():
        sd = SK / f"{e['id']}-skill" / "persona"
        for t, b, ln in _sections(sd / "rules.md", r"^#{3,4} [A-Z]?R?\d+ |^#{3,4} [A-E]\d+ "):
            m = re.match(r"^#{3,4} ([A-Z]?\d+|R\d+)", t)
            rules.append({"kind": "规则", "skill": e["id"], "id": m.group(1) if m else "", "title": t.lstrip("# "), "text": b, "file": f"skills/{e['id']}-skill/persona/rules.md", "line": ln})
        for t, b, ln in _sections(sd / "cases.md", r"^### "):
            cases.append({"kind": "案例", "skill": e["id"], "title": t.lstrip("# "), "text": b, "file": f"skills/{e['id']}-skill/persona/cases.md", "line": ln})
        for f in sorted((sd / "case_log").glob("20??-??.md"))[-3:]:   # 操作日志近 3 个月
            for t, b, ln in _sections(f, r"^### "):
                cases.append({"kind": "操作日志", "skill": e["id"], "title": t.lstrip("# "), "text": b, "file": f.relative_to(ROOT).as_posix(), "line": ln})
    rj = ROOT / "skills" / "tzzb-skill" / "references" / "reject_rules.md"
    if rj.exists():
        for i, l in enumerate(rj.read_text(encoding="utf-8").splitlines(), 1):
            if l.startswith("| RJ"):
                cases.append({"kind": "否决条款(错题泛化)", "skill": "tzzb", "title": l[:60], "text": l, "file": rj.relative_to(ROOT).as_posix(), "line": i})
    _CORP["rules"], _CORP["cases"] = rules, cases
    _CORP["rsim"] = Sim([r["title"] + "\n" + r["text"] for r in rules])
    _CORP["csim"] = Sim([c["title"] + "\n" + c["text"] for c in cases])
    return _CORP


def contracts(skill, D):
    d8 = D.replace("-", "")
    rd = RES / f"{skill}_chain" / f"live-{d8}"
    out = []
    for f in list(rd.glob("0[2-6]_*.md")) + list(rd.glob("slots/*/0[2-6]_*.md")):
        m = re.findall(r"```contract\s*(\{.*?\})\s*```", f.read_text(encoding="utf-8", errors="ignore"), re.S)
        if m:
            try:
                out.append(json.loads(m[-1]))
            except ValueError:
                pass
    return out


def cited_rules(skill, D):
    ids = Counter()
    for c in contracts(skill, D):
        for x in re.findall(r'"(?:id|rules?)"\s*:\s*"?([A-Z]?\d{1,3})', json.dumps(c, ensure_ascii=False)):
            ids[x if x[0].isalpha() else "R" + x] += 1
        for a in c.get("actions") or []:
            for r in a.get("rules") or []:
                rid = r.get("id") if isinstance(r, dict) else r
                if rid:
                    ids[str(rid)] += 1
    return ids


def lessons_of(skill, D, days):
    out = []
    for d in days:
        f = RES / f"{skill}_chain" / f"live-{d.replace('-', '')}" / "07_review.md"
        if not f.exists():
            continue
        m = re.findall(r"```contract\s*(\{.*?\})\s*```", f.read_text(encoding="utf-8", errors="ignore"), re.S)
        try:
            c = json.loads(m[-1]) if m else {}
        except ValueError:
            c = {}
        for x in c.get("lessons") or []:
            if isinstance(x, dict) and x.get("text"):
                out.append({"skill": skill, "date": d, "type": x.get("type"), "text": x["text"], "evidence": x.get("evidence", ""), "file": f.relative_to(ROOT).as_posix()})
    return out


# ============================================================ 拼包
def chain_codes(skill, D):
    bk = mentors.book(skill)
    b = _jl(HERE / "books" / f"{bk}.json", {}) or {}
    qty = {}
    for t in sorted(b.get("trades") or [], key=lambda x: str(x["id"])):
        if str(t["id"])[:10] < D:
            qty[t["code"]] = qty.get(t["code"], 0) + (t["qty"] if t["side"] == "BUY" else -t["qty"])
    held = [c for c, q in qty.items() if q > 0]
    traded = sorted({t["code"] for t in b.get("trades") or [] if str(t["id"]).startswith(D)})
    ordered = sorted({o["code"] for o in b.get("orders") or [] if o.get("date") == D} - set(traded))
    return list(dict.fromkeys(held + traded)), ordered


def neighbors(codes, D):
    try:
        import topology as TOPO
        out = set()
        for c in codes:
            r = TOPO.load(c, D) or {}
            out |= {str(x[0] if isinstance(x, (list, tuple)) else x.get("c") if isinstance(x, dict) else x) for x in (r.get("nb") or [])[:5]}
        return out - set(codes)
    except Exception:   # noqa: BLE001
        return set()


def build(skill, D):
    codes, ordered = chain_codes(skill, D)
    mfile, midx, mlines = shared_market(D, codes + ordered)
    cov = []
    # ① 行情
    mk = []
    for c in codes:
        e = midx.get(c) or {}
        mk += mlines[e.get("start", 1) - 1:e.get("end", 0)] + [""]
    miss = {k: [c for c in codes if not (midx.get(c, {}).get("cov") or {}).get(k)] for k in ("日线", "箱体", "竞价", "5分钟K")}
    cov.append(f"| 当日行情(持仓 + 成交 {len(codes)} 只) | " + ("有" if codes else "本链当日无持仓无成交") + " | " + "; ".join(f"{k}缺 {len(v)} 只({','.join(v[:4])})" for k, v in miss.items() if v) + " |")
    # ② 导师
    ms, last = mentor_section(skill, D, codes)
    mdir = RES / "_pack07" / D
    (mdir / f"mentor_{skill}.md").write_text("\n".join(ms) + "\n", encoding="utf-8")
    cov.append(f"| 导师真人腿 | {'有' if last else '无'} | 账本逐笔腿最新 {last or '—'}" + (" ⚠ 不是今天(真人还没更新, 当日对照无效)" if last and last < D else "") + " |")
    # ③ skill
    C = corpus()
    cited = cited_rules(skill, D)
    mine = [r for r in C["rules"] if r["skill"] == skill and r["id"] in cited]
    def core(r):   # 规则核心几行内联; 证据链 / 历次核销等长尾给行号索引(用户 10/21: 不限篇幅, 长了就加索引)
        L = r["text"].splitlines()
        k = next((i for i, l in enumerate(L) if re.match(r"^\s*-\s*\*\*(证据链|核销|\d{1,2}-\d{1,2} 核销|验证状态)", l)), len(L))
        k = min(k, 8)   # 没有分隔标记的格式(如桃哥规则)也只内联前 8 行
        tail = f"\n- (证据链 / 核销记录等 {len(L) - k} 行见 {r['file']}:{r['line'] + 1 + k}-{r['line'] + len(L)})" if k < len(L) else ""
        return "\n".join(L[:k]) + tail
    rl = [f"### {r['title']}(引用 {cited[r['id']]} 次; {r['file']}:{r['line']})\n{core(r)}" for r in mine]
    sim_rules = []
    for r in mine:
        for s, i in C["rsim"].top(r["title"] + "\n" + r["text"], k=3, skip=lambda i: C["rules"][i]["skill"] == skill):
            x = C["rules"][i]
            if s > 0.15:
                sim_rules.append((s, f"- [{x['skill']} {x['id']}] {x['title'][:60]}(像本链 {r['id']}, 相似度 {s:.2f}; {x['file']}:{x['line']})\n  " + x["text"][:300].replace("\n", " ")))
    sim_rules = [t for _, t in sorted(sim_rules, reverse=True)[:10]]
    cov.append(f"| 当天引用的规则 | {len(mine)} 条全文 | 其他导师相似规则 {len(sim_rules)} 条 |")
    nb = neighbors(codes, D)
    keys = set(codes) | {name_of(c) for c in codes if name_of(c)}
    nkeys = nb | {name_of(c) for c in nb if name_of(c)}
    by_code = [x for x in C["cases"] if any(k and k in (x["title"] + x["text"]) for k in keys)]
    by_nb = [x for x in C["cases"] if x not in by_code and any(k and len(k) >= 2 and k in (x["title"] + x["text"]) for k in nkeys)]
    q = "\n".join(r["title"] + r["text"][:300] for r in mine)
    try:
        sys.path.insert(0, str(HERE))
        import attribution as AT
        R = _jl(RES / "_attribution" / f"{D}.json") or AT.build(D)
        ch = next((x for x in R["chains"] if x["skill"] == skill), {})
        q += "\n" + "\n".join(f["ev"] for f in ch.get("finds") or [])
    except Exception:   # noqa: BLE001
        ch = {}
    by_text = [C["cases"][i] for s, i in C["csim"].top(q, k=8) if s > 0.12 and C["cases"][i] not in by_code + by_nb] if q.strip() else []
    fmt = lambda x: f"- [{x['kind']} · {x['skill']}] {x['title'][:70]}({x['file']}:{x['line']})\n  " + x["text"][:400].replace("\n", " ")
    cov.append(f"| cases / 操作日志 / 否决条款 | 同票 {len(by_code)} · 拓扑邻居 {len(by_nb)} · 文本相似 {len(by_text)} | 拓扑邻居 {len(nb)} 只 |")
    # ④ lessons
    days = trade_days(D, 6)[:-1]
    mine_l = lessons_of(skill, D, days)
    allL = []
    for e in [mentors.get(x) for x in mentors.active_ids()]:
        allL += lessons_of(e["id"], D, trade_days(D, 25)[:-1])
    sd = (_jl(HERE / "similar_days" / f"{D}.json") or {}).get("top") or (_jl(HERE / "similar_days" / f"{D}.json") or {}).get("similar") or []
    sim_dates = {str(x.get(k)) for x in sd if isinstance(x, dict) for k in ("date", "next_day") if x.get(k)}   # 相似日及其次日(次日才对应"今天")
    by_day = [x for x in allL if x["date"] in sim_dates and x not in mine_l]
    rest = [x for x in allL if x not in mine_l and x not in by_day]
    by_txt = []
    if rest and q.strip():
        S = Sim([x["text"] + x.get("evidence", "") for x in rest])
        by_txt = [rest[i] for s, i in S.top(q, k=5) if s > 0.12]
    fl = lambda x: f"- [{x['skill']} {x['date']} {x.get('type') or ''}] {x['text'][:300]}({x['file']})"
    cov.append(f"| 过往 lessons | 本链近 5 天 {len(mine_l)} 条 | 相似日 {len(by_day)} 条 · 文本相似 {len(by_txt)} 条(全体导师近 25 天) |")
    # ⑤ 多日结算
    st = [json.loads(l) for l in (HERE / "decisions" / f"{skill}.settle.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()] if (HERE / "decisions" / f"{skill}.settle.jsonl").exists() else []
    st = [x for x in st if x.get("resolved") == D]
    cov.append(f"| 多日结算(今天到期的窗口) | {len(st)} 条 | 15:50 机械结算; 07 早于 15:50 跑时今天的还没结 |")
    kn = sorted((ROOT / "docs" / "knowledge").glob("*.md"))
    cov.append(f"| 知识库目录 | {len(kn)} 篇 | 只给目录(用户未验收) |")
    # 拼
    P = [f"\n\n# 驱动器补充: 07 素材包({D}; 零 token 机械取数, 不用自己找; 公用部分在 {mdir.relative_to(ROOT).as_posix()}/, 要别的票按行号 Read)",
         "## ① 覆盖表", "| 项 | 有没有 | 说明 |", "|---|---|---|"] + cov
    P += ["\n## ② 当日行情(本链持仓 + 成交票)"] + (mk or ["(无)"])
    if ordered:
        P.append("- 本链今天挂过单但没成交的票(行情在公用文件里): " + ", ".join(f"{c}{name_of(c)} → {mfile.relative_to(ROOT).as_posix()}:{midx[c]['start']}-{midx[c]['end']}" for c in ordered if c in midx))
    P += ["\n## ③ 导师真人"] + ms
    P += ["\n## ④ 当天引用过的规则(全文)"] + (rl or ["(当天 contract 里没有引用规则编号)"])
    P += ["\n## ⑤ 其他导师的相似规则(文本相似度, 拓扑参考)"] + (sim_rules or ["(无)"])
    P += ["\n## ⑥ cases / 操作日志 / 否决条款(错题)", "### 同票"] + ([fmt(x) for x in by_code[:12]] or ["(无)"])
    P += ["### 拓扑邻居票(扣大盘联动 / 同行业)"] + ([fmt(x) for x in by_nb[:8]] or ["(无)"])
    P += ["### 和今天引用的规则 / 归因检测项文本相似"] + ([fmt(x) for x in by_text] or ["(无)"])
    P += ["\n## ⑦ 过往 lessons", "### 本链近 5 天"] + ([fl(x) for x in mine_l] or ["(无)"])
    P += ["### 相似市况日的 lessons(全体导师)"] + ([fl(x) for x in by_day[:8]] or ["(无)"])
    P += ["### 和今天情况文本相似的 lessons(全体导师)"] + ([fl(x) for x in by_txt] or ["(无)"])
    P += ["\n## ⑧ 多日结算(本链前几天的单, 今天到期的窗口)"] + ([f"- {x['id'].split('|')[0]} {x['id'].split('|')[3]} {x['id'].split('|')[4]} T+{x['win']}: {x.get('status')} 收益 {x.get('signed_ret', 0) * 100:+.2f}% 超上证 {(x.get('ex_idx') or 0) * 100:+.2f}%" for x in st] or ["(无)"])
    P += ["\n## ⑨ 知识库目录(docs/knowledge, 需要时按文件名 Read)"] + [f"- {f.name}: " + (f.read_text(encoding='utf-8').splitlines() or [''])[0].lstrip('# ') for f in kn]
    text = "\n".join(P) + "\n"
    (mdir / f"pack_{skill}.md").write_text(text, encoding="utf-8")
    return text


def block_07(skill, D):
    try:
        return build(skill, D)
    except Exception as e:   # noqa: BLE001
        return f"\n\n# 驱动器补充: 07 素材包生成失败({e}), 本次 07 自行取数\n"


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--print", action="store_true")
    a = ap.parse_args()
    t = build(a.skill, a.date)
    print(t if a.print else f"07 素材包 {a.skill} {a.date}: {len(t)} 字 → results/_pack07/{a.date}/pack_{a.skill}.md")
