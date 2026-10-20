# -*- coding: utf-8 -*-
"""ctx_index.py — 盘中资料索引化(10/19 用户定: "事实包和 3 秒盘口都做成索引, 模型按需捞"; 零 token, 零网络)

给谁用: 实盘 order-skill(私有)、决策 T 账本(t_decide.py: 银行 / 纳指 / 私有品种)、以后导师链 facts(带开关)——同一份索引, 一处改三处受益。
为什么不塞全文: 每个时段的 facts.md 约 48KB, 3 秒盘口一只票一天 4000+ 行, 原样给模型又贵又淹没重点;
              给"目录 + 一句话状态", 驱动器按品种关键词预取相关几行, 模型要细节再按行号 Read 原文。
四类资料(= 资料覆盖表 1~4):
  ① 盘中走势  tape_l0(一句话: 现价 / 均价线及 15 分钟斜率 / 离均价线 / 高低点及时间 / 量能节奏 / 五档买卖比 / 大单墙)
              tape_l1(5 分钟 K: 开高低收 / 均价线 / 量) ; L2 = 原始文件 downloads/market/<日>/book_snap.jsonl(只给脚本)
  ② 盘中事实  facts_index(最新时段 facts.md 的目录: 节名 / 行号范围 / 条数 / 一句话) + prefetch(按品种关键词抽命中的行, 带行号)
  ③ 结构三态  structure(前一交易日 indicators.jsonl: 三态 / 箱体 / EMA / 止损候选 + 盯盘 md 的结构位行)
  ④ 外围期货  futures(最新 facts 的期货 / 外围行: 纳指期货、标普期货、股指期货; 品种相关的农产品等)
  coverage()  四项各自有没有、多新(分钟), 缺的写清楚 → 进决策材料和日志
用法: python scripts/lib/ctx_index.py --code 601988 [--date D] [--l1] [--section 新到电报] [--json]
      from ctx_index import pack; pack(code, D) → 给模型的一段文字(L0 + 事实目录 + 预取 + 结构 + 期货 + 覆盖表)
"""
import argparse
import datetime as dt
import json
import re
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"
FACTS = ROOT / "scripts" / "dfcf" / "paper" / "facts"
LIVE = ROOT / "scripts" / "dfcf" / "snapshots" / "live"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import a_rules as AR   # noqa: E402

# 品种 → 事实包里要预取的关键词(驱动器替模型先捞; 不够模型再按目录行号 Read)
KW = {"601988": ["银行", "工行", "工商银行", "中行", "中国银行", "农行", "建行", "四大行", "红利", "高股息", "沪深300", "上证50", "权重", "防御"],
      "159941": ["纳指", "纳斯达克", "美股", "标普", "英伟达", "科技股", "美债", "美元", "跨境", "QDII"]}
FUT_KW = {"601988": ["沪深300股指", "上证50股指"], "159941": ["纳指期货", "标普500期货", "美元指数"]}
_PRIV = ROOT / "scripts" / "dfcf" / "snapshots" / "order-skill" / "kw.json"   # 实盘持仓品种的关键词放私有区(gitignore), 不进公共代码
if _PRIV.exists():
    try:
        _p = json.loads(_PRIV.read_text(encoding="utf-8"))
        KW.update(_p.get("KW", {}))
        FUT_KW.update(_p.get("FUT_KW", {}))
    except ValueError:
        pass
sys.path.insert(0, str(ROOT / "scripts" / "market"))
try:
    import topology as TOPO   # 10/19 晚: 市场拓扑(每晚 check md 生成), 手写 KW 之外的关键词 / 期货兜底
except ImportError:
    TOPO = None


def kw_of(code, D):
    """预取关键词 = 手写表(优先) + 拓扑(D 之前那份: 东财行业 / 申万三级 / 前 5 邻居名), 去重"""
    ks = list(KW.get(str(code), []))
    r = TOPO.load(code, D, strict=True) if TOPO else None
    if r:
        ks += [x for x in [r.get("ind"), (r.get("sw") or "").split("/")[-1]] if x and len(x) >= 2]
        ks += [x["n"].replace(" ", "") for x in r["nb"][:5]]
    return list(dict.fromkeys(k.rstrip("ⅡⅢ") for k in ks if k))


def fut_of(code, D):
    if str(code) in FUT_KW:
        return FUT_KW[str(code)]
    r = TOPO.load(code, D, strict=True) if TOPO else None
    return [f for f in (r or {}).get("fut", []) if f not in ("沪深300股指",)]


def _prev_close(code, D):
    mk = sorted(x.name for x in MKT.iterdir() if re.match(r"\d{4}-\d\d-\d\d$", x.name) and x.name < D and (x / "kline_day.jsonl").exists())
    if not mk:
        return None
    s = f'"{sym(code)}"'
    for l in (MKT / mk[-1] / "kline_day.jsonl").open(encoding="utf-8"):
        if s in l:
            return json.loads(l).get("close")
    return None


def topo_block(code, D, k=5):
    """⑥ 拓扑 + 邻居此刻涨跌(book_snap 已录前 3 邻居盘口; 没录到的写"无盘口") + 一句逼模型对照的问题
    10/19 用户: 相关性是过去的经验只能参考, 最终 LLM 判断, 但要确保被消费、引发思考"""
    if not TOPO:
        return ""
    ln = TOPO.line(code, D, k=k, strict=True)
    if not ln:
        return "⑥ 拓扑: 该票没有(新股 / 停牌 / 前一晚未生成)"
    r = TOPO.load(code, D, strict=True)
    me = _tape(code, D)
    pc = _prev_close(code, D)
    now = []
    for x in r["nb"][:k]:
        t = [y for y in book_rows(x["c"], D) if y["p"] > 0 and y["t"] <= CUT.get("t", "15:00:30")]
        p0 = _prev_close(x["c"], D)
        now.append(f"{x['n'].replace(' ', '')} {(t[-1]['p'] / p0 - 1) * 100:+.1f}%" if t and p0 else f"{x['n'].replace(' ', '')} 无盘口")
    mine = f"本票 {(me[-1]['p'] / pc - 1) * 100:+.1f}%" if me and pc else "本票 无盘口"
    return ("⑥ " + ln + f"\n   此刻: {mine} | " + " | ".join(now) +
            "\n   → 出单前先答一句: 本票和邻居同向还是背离? 同向 = 板块行情(跟着板块定高抛低吸的幅度); 背离 = 个股消息 / 资金或补涨补跌(查 ② 预取和 ⑤ md 找原因); "
            "邻居先动本票没动 = 可能跟随。相关性是过去 60 / 20 日统计, 题材刚切换时会滞后, 只作参考, 结论由你判断")


def sym(code):
    """book_snap / indicators 的口径 = sh601988 / sz159941"""
    _ex, c = AR.norm(code)
    return f"{_ex}{c}" if _ex in ("sh", "sz", "bj") else (("sh" if str(code).startswith(("6", "5", "9")) else "sz") + str(code))


# ================================================================ ① 盘中走势
def book_rows(code, D):
    """当天 3 秒盘口原始行(盘中 book_snap.jsonl; 收盘后 collect_book 压成 .jsonl.gz, 两种都认)"""
    f = MKT / D / "book_snap.jsonl"
    g = MKT / D / "book_snap.jsonl.gz"
    s = f'"{sym(code)}"'
    if f.exists():
        fh = f.open(encoding="utf-8")
    elif g.exists():
        import gzip
        fh = gzip.open(g, "rt", encoding="utf-8")
    else:
        return []
    with fh:
        return [json.loads(l) for l in fh if s in l]


CUT = {}   # 回放用: pack(before=时段) 时只看该时段及以前的盘口, 防偷看


def _tape(code, D):
    r = book_rows(code, D)
    end = CUT.get("t", "15:00:30")
    return [x for x in r if x["p"] > 0 and "09:30:00" <= x["t"] <= end] or None


def _ago(r, mins):
    t0 = (dt.datetime.strptime(r[-1]["t"], "%H:%M:%S") - dt.timedelta(minutes=mins)).strftime("%H:%M:%S")
    old = [x for x in r if x["t"] <= t0]
    return old[-1] if old else r[0]


def tape_l0(code, D):
    r = _tape(code, D)
    if not r:
        return None, "① 盘中走势: 无(该票不在 3 秒盘口采集名单 / 今天没采)"
    x = r[-1]
    vw = x["a"] / x["v"] if x["v"] else x["p"]
    o = _ago(r, 15)
    vw15 = o["a"] / o["v"] if o["v"] else vw
    hi = max(r, key=lambda y: y["p"])
    lo = min(r, key=lambda y: y["p"])
    m = {}
    for y in r:
        m[y["t"][:4]] = y["v"]
    ks = list(m)
    v10 = [(m[k] - m[ks[i - 1]]) for i, k in enumerate(ks) if i > 0]
    pace = f"近10分钟量 {v10[-1] // 100}手 / 全天每10分钟中位 {int(st.median(v10)) // 100}手" if len(v10) >= 3 else ""
    w = [y for y in r if y["t"] >= _ago(r, 10)["t"]]
    bi = st.mean(sum(q for _, q in y["b"]) for y in w)
    ak = st.mean(sum(q for _, q in y["k"]) for y in w) or 1
    lv = [q for _, q in x["b"] + x["k"]]
    med = st.median(lv) if lv else 0
    walls = [f"买{p}×{q // 100}手" for p, q in x["b"] if q >= max(3 * med, 20000)] + [f"卖{p}×{q // 100}手" for p, q in x["k"] if q >= max(3 * med, 20000)]
    d = {"t": x["t"], "last": x["p"], "vwap": round(vw, 3), "vwap_slope15": round(vw - vw15, 3), "dist": round(x["p"] / vw - 1, 4), "open": r[0]["p"],
         "hi": hi["p"], "hi_t": hi["t"][:5], "lo": lo["p"], "lo_t": lo["t"][:5], "bid_ask": round(bi / ak, 2), "walls": walls, "pace": pace}
    txt = (f"① 盘中走势 L0({d['t'][:5]}): 现 {d['last']} 开 {d['open']} 高 {d['hi']}({d['hi_t']}) 低 {d['lo']}({d['lo_t']}) | 均价线 {d['vwap']}"
           f"(15分钟 {d['vwap_slope15']:+.3f}, {'向上' if d['vwap_slope15'] > 0.003 else '向下' if d['vwap_slope15'] < -0.003 else '走平'}) 现价{'在上' if d['dist'] >= 0 else '在下'} {abs(d['dist']):.2%}"
           f" | 五档买/卖 {d['bid_ask']}" + (f" | 大单 {' '.join(walls)}" if walls else "") + (f" | {pace}" if pace else "")
           + f"  [细节: L1 5分钟K 用 ctx_index.py --code {code} --l1; 原始 downloads/market/{D}/book_snap.jsonl(.gz)]")
    return d, txt


def tape_l1(code, D, bar=5):
    r = _tape(code, D)
    if not r:
        return "(无 3 秒盘口)"
    out, cur, key = ["时间 | 开 | 高 | 低 | 收 | 均价线 | 量(手)"], None, None
    prev_v = 0

    def flush():
        if cur:
            out.append(f"{key} | {cur['o']} | {cur['h']} | {cur['l']} | {cur['c']} | {cur['vw']:.3f} | {(cur['v1'] - cur['v0']) // 100}")
    for x in r:
        hh, mm = int(x["t"][:2]), int(x["t"][3:5])
        k = f"{hh:02d}:{mm // bar * bar:02d}"
        if k != key:
            flush()
            key, cur = k, {"o": x["p"], "h": x["p"], "l": x["p"], "c": x["p"], "v0": prev_v, "v1": x["v"], "vw": x["a"] / x["v"] if x["v"] else x["p"]}
        cur["h"], cur["l"], cur["c"], cur["v1"] = max(cur["h"], x["p"]), min(cur["l"], x["p"]), x["p"], x["v"]
        cur["vw"] = x["a"] / x["v"] if x["v"] else cur["vw"]
        prev_v = x["v"]
    flush()
    return "\n".join(out)


# ================================================================ ② 盘中事实
def latest_facts(D, before=None):
    d = FACTS / D
    if not d.exists():
        return None
    slots = sorted(x.name for x in d.iterdir() if (x / "facts.md").exists() and re.match(r"\d{4}$", x.name) and (not before or x.name <= before))
    return (d / slots[-1] / "facts.md") if slots else None


def _sections(f):
    lines = f.read_text(encoding="utf-8").splitlines()
    secs, cur = [], None
    for i, l in enumerate(lines, 1):
        if l.startswith("## "):
            if cur:
                secs.append(cur)
            cur = {"name": l[3:].strip(), "a": i, "b": i, "lines": []}
        elif cur:
            cur["b"] = i
            if l.strip():
                cur["lines"].append((i, l))
    if cur:
        secs.append(cur)
    seen, out = set(), []
    for s in secs:                       # facts 里有的节会出现两次(盘前块 + 本时段块), 保留后出现的(更新)
        k = s["name"].split("(")[0]
        if k in seen:
            out = [x for x in out if x["name"].split("(")[0] != k]
        seen.add(k)
        out.append(s)
    return out, lines


def facts_index(D, before=None):
    f = latest_facts(D, before)
    if not f:
        return None, "② 盘中事实: 今天还没有 facts 包"
    secs, _ = _sections(f)
    age = ""
    try:
        age = f"{int((dt.datetime.now() - dt.datetime.fromtimestamp(f.stat().st_mtime)).seconds / 60)} 分钟前"
    except OSError:
        pass
    rel = f.relative_to(ROOT).as_posix()
    rows = []
    acct = [s for s in secs if re.match(r"[AB]-", s["name"])]
    if acct:   # 各账本状态 25 行合成一行
        rows.append(f"- 各 paper 账本状态({len(acct)} 本) | 行 {acct[0]['a']}~{acct[-1]['b']} | {len(acct)} 行 | " + "; ".join(s["name"].split(":")[0] for s in acct[:4]) + "…")
    for s in secs:
        if s in acct:
            continue
        first = next((re.sub(r"\s+", " ", l)[:60] for _, l in s["lines"] if not l.startswith("#")), "")
        rows.append(f"- {s['name'][:28]} | 行 {s['a']}~{s['b']} | {len(s['lines'])} 行 | {first}")
    return {"file": rel, "slot": f.parent.name, "sections": [(s["name"], s["a"], s["b"]) for s in secs]}, \
        f"② 盘中事实 目录({rel}, 时段 {f.parent.name}, {age}; 要整节就 Read 该文件对应行号):\n" + "\n".join(rows)


def prefetch(code, D, before=None, cap=14):
    f = latest_facts(D, before)
    if not f:
        return ""
    kws = kw_of(code, D)
    secs, _ = _sections(f)
    hits = []
    for s in secs:
        if s["name"].startswith(("A-", "B-", "导师信号", "选股层")):     # 各账本状态 / 导师规则卡: 与品种行情无关
            continue
        for i, l in s["lines"]:
            if any(k in l for k in kws):
                hits.append(f"  [{s['name'][:10]} 行{i}] {re.sub(r'\s+', ' ', l)[:150]}")
    return (f"② 预取(按 {code} 关键词 {'/'.join(kws[:6])}…, 命中 {len(hits)} 行, 列前 {min(cap, len(hits))}):\n" + "\n".join(hits[:cap])) if hits else f"② 预取: 关键词 {'/'.join(kws[:6])} 在最新事实包里没有命中"


def section(D, name, before=None):
    f = latest_facts(D, before)
    if not f:
        return ""
    secs, lines = _sections(f)
    s = next((x for x in secs if name in x["name"]), None)
    return "\n".join(lines[s["a"] - 1:s["b"]]) if s else f"(没有 {name} 这一节)"


# ================================================================ ③ 结构 / 三态
def structure(code, D):
    mk = sorted(x.name for x in MKT.iterdir() if re.match(r"\d{4}-\d\d-\d\d$", x.name) and x.name < D and (x / "indicators.jsonl").exists())
    out, d = [], None
    if mk:
        s = f'"{sym(code)}"'
        for l in (MKT / mk[-1] / "indicators.jsonl").open(encoding="utf-8"):
            if s in l:
                d = json.loads(l)
                break
    if d:
        ema = " ".join(f"EMA{k[3:]} {d[k]}" for k in ("ema20", "ema60", "ema144", "ema169") if d.get(k))
        out.append(f"③ 结构(截至 {mk[-1]} 收盘): 三态 {d.get('regime')} | 收 {d.get('close')} | 箱体 {d.get('box_lo')}~{d.get('box_hi')} | {ema} | 止损候选 {d.get('stops')}")
    else:
        out.append("③ 结构: indicators.jsonl 里没有该票")
    lf = LIVE / f"{D}.md"
    if lf.exists():
        for l in lf.read_text(encoding="utf-8").splitlines():
            if l.startswith("|") and str(code) in l:
                out.append("   盯盘结构位(昨高低 / 前5日 / MA / 股性): " + l[:260])
                break
    return d, "\n".join(out)


# ================================================================ ④ 外围 / 期货
def futures(code, D, before=None):
    f = latest_facts(D, before)
    if not f:
        return None, "④ 外围期货: 今天还没有 facts 包"
    t = f.read_text(encoding="utf-8")
    want = fut_of(code, D) + ["沪深300股指", "纳指期货"]
    got = []
    for l in t.splitlines():
        for k in want:
            for m in re.finditer(re.escape(k) + r"\s*[\d.]+\([-+\d.]+%[^)]*\)", l):
                if m.group(0) not in got:
                    got.append(m.group(0))
    return got, f"④ 外围期货(时段 {f.parent.name} 现拉): " + (" | ".join(got) if got else "没找到相关期货行")


# ================================================================ ⑤ md 沉淀(10/19 用户: 快速 / 深度都没用上 md/ 下每天的 yyyy-mm-dd.md)
def md_hits(code, D, days=30, cap=12):
    """md/<季度>/<日>.md(财联社早报 / 午评收评 / 涨停分析 / 三 UP / 同花顺导师 / 发哥 …)里提到该票(代码或名称)或其关键词的行: 日期 / 小节 / 行号 / 摘要
    只给索引, 原文按行号 Read; 只看 ≤ D 的(回放不偷看)"""
    name = None
    try:
        name = json.loads((ROOT / "scripts" / "dfcf" / "paper" / "names.json").read_text(encoding="utf-8")).get(str(code))
    except (OSError, ValueError):
        pass
    keys = [str(code)] + ([name] if name else []) + [k for k in kw_of(code, D) if len(k) >= 2][:4]
    files = sorted((f for f in (ROOT / "md").glob("20*/20??-??-??.md") if f.stem <= D), key=lambda f: f.stem)[-days:]
    out, n = [], 0
    for f in reversed(files):
        sec = ""
        for i, l in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if l.startswith("#"):
                sec = l.lstrip("# ").strip()[:16]
                continue
            hit = next((k for k in keys if k in l), None)
            if hit and not l.startswith("|"):
                n += 1
                if len(out) < cap:
                    s = re.sub(r"\s+", " ", l)
                    j = max(0, s.find(hit) - 40)   # 摘要以命中词为中心(电报行很长, 命中词常在 100 字之后)
                    out.append(f"  [{f.stem[5:]} {sec} 行{i}] {'…' if j else ''}{s[j:j + 110]}")
    rel = "md/<季度>/<日>.md"
    # 10/19 用户: "远期的类似市况不查吗" → 再加 similar_days.py 选出的相似市况日(全样本 2025-01 起, 不限 30 天)及其次日的 md 命中
    sim_lines = []
    try:
        sj = json.loads((ROOT / "scripts" / "dfcf" / "paper" / "similar_days" / f"{D}.json").read_text(encoding="utf-8"))
        for h in (sj.get("similar") or [])[:3]:
            for day in (h.get("date"), h.get("next_day")):
                f = next(iter(sorted((ROOT / "md").glob(f"20*/{day}.md"))), None) if day else None
                if not f or f.stem > D:
                    continue
                sec, got = "", []
                for i, l in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                    if l.startswith("#"):
                        sec = l.lstrip("# ").strip()[:16]
                        continue
                    hit = next((k for k in keys if k in l), None)
                    if hit and not l.startswith("|"):
                        s = re.sub(r"\s+", " ", l)
                        j = max(0, s.find(hit) - 40)
                        got.append(f"  [相似日 {day}(相似度 {h.get('sim')}) {sec} 行{i}] {'…' if j else ''}{s[j:j + 100]}")
                sim_lines += got[:3]
    except (OSError, ValueError):
        pass
    head = f"⑤ md 沉淀(近 {len(files)} 个交易日的 {rel}, 关键词 {'/'.join(keys[:5])}; 命中 {n} 行, 列最近 {len(out)}; 原文按行号 Read)"
    body = out + ([f"  —— 相似市况日(similar_days, 2025-01 起全样本)里提到它的:"] + sim_lines if sim_lines else [])
    return (head + ":\n" + "\n".join(body)) if body else f"⑤ md 沉淀: 近 {len(files)} 天和相似市况日的 md 里都没提到 {'/'.join(keys[:3])}"


# ================================================================ 覆盖表 + 打包
def coverage(code, D, before=None):
    t, _ = tape_l0(code, D)
    fi, _ = facts_index(D, before)
    s, _ = structure(code, D)
    fu, _ = futures(code, D, before)
    now = dt.datetime.now()
    tape_age = None
    if t:
        tape_age = int((now - dt.datetime.strptime(f"{D} {t['t']}", "%Y-%m-%d %H:%M:%S")).total_seconds() / 60)
    rows = [("①盘中走势", bool(t) and (tape_age is None or tape_age <= 10 or now.strftime("%H:%M") > "15:00" or now.strftime("%H:%M") < "09:30"), f"{t['t'][:5]}" if t else "不在采集名单"),
            ("②盘中事实", bool(fi), f"时段 {fi['slot']}" if fi else "无 facts"),
            ("③结构三态", bool(s), "前一交易日" if s else "indicators 缺"),
            ("④外围期货", bool(fu), f"{len(fu)} 项" if fu else "缺")]
    return rows, "资料覆盖: " + " ｜ ".join(f"{n} {'✅' if ok else '❌'}({w})" for n, ok, w in rows)


def pack(code, D=None, before=None, l1=False):
    """给模型的一段: 覆盖表 + ①L0 + ②目录 + ②预取 + ③ + ④(约 2~4KB); l1=True 再附 5 分钟 K"""
    D = D or dt.date.today().isoformat()
    CUT.clear()
    if before and re.match(r"\d{4}$", before):
        CUT["t"] = f"{before[:2]}:{before[2:]}:59"
    parts = [coverage(code, D, before)[1], tape_l0(code, D)[1]]
    if l1:
        parts.append("① L1 5分钟K:\n" + tape_l1(code, D))
    parts += [prefetch(code, D, before), structure(code, D)[1], futures(code, D, before)[1], md_hits(code, D), facts_index(D, before)[1]]
    if TOPO:
        parts.insert(-1, topo_block(code, D))
    return "\n".join(p for p in parts if p)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--before", help="只看这个时段及以前的 facts(回放用, 如 1033)")
    ap.add_argument("--l1", action="store_true")
    ap.add_argument("--section")
    a = ap.parse_args()
    if a.section:
        print(section(a.date, a.section, a.before))
        return
    t = pack(a.code, a.date, a.before, a.l1)
    print(t)
    print(f"\n({len(t)} 字)")


if __name__ == "__main__":
    main()
