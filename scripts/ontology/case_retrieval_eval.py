# -*- coding: utf-8 -*-
"""ontology/case_retrieval_eval.py — case_retrieval 的验证(10/26 凌晨; 只读; 产物 downloads/ontology/case_vec/eval/)

考题: 10/20~10/23 四位导师(芷影攫心 / 刘忆青 / 不吃土豆0 / 做手德融)真实买卖 = 索引里这几天的决策点(同票同方向相隔 >15 分钟算新的一次) + K3 虚拟题
每题: 情境用 query_situation 现算(只用 D 之前 + D 开盘 + 当时成交价 + 决策那一刻的持仓), 并和索引特征对账 → 跑检索(多组权重 + 放宽消融) → 机械"像不像" + 原文渲染(供人工判)
机械评分(5 个核心维度, 和硬过滤分开定义, 粗一档):
  ① 昨日状态组(涨停 / 炸板 / 跌停·大跌 / 平·大涨)  ② 价位档相同或相邻  ③ 开盘区间相同或相邻  ④ 持仓组(未持有 / 浮盈 / 被套 / 其他)  ⑤ 股票: 连板组(0 / 1~2 / 3+); 转债: 正股开盘方向
  像 = ≥4 项且④对上; 部分像 = 3 项, 或 2 项 + 手法类相同(日卡解读"手法类=", 只用于评估, 不进检索); 不像 = 其余
用法: python case_retrieval_eval.py run      (跑全部考题 → eval/raw.jsonl + eval/render_*.md)
      python case_retrieval_eval.py onto     (事件本体 30 条抽查材料 → eval/onto_sample.md)
"""
import collections
import datetime as dt
import json
import random
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ontology"))
import case_retrieval as CR   # noqa: E402

EV = CR.OUTD / "eval"
MENTORS = ["zhiyingjuexin", "liuyiqing", "buchitudou0", "zuoshoudeirong"]
WSETS = {"A 结构0.5/拓扑0.3/语义0.2": (0.5, 0.3, 0.2), "B 0.3/0.3/0.4": (0.3, 0.3, 0.4), "C 0.7/0.2/0.1": (0.7, 0.2, 0.1), "D 0.4/0.4/0.2": (0.4, 0.4, 0.2),
         "E 等权": (1 / 3, 1 / 3, 1 / 3), "C2 0.6/0.2/0.2": (0.6, 0.2, 0.2), "C3 0.8/0.1/0.1": (0.8, 0.1, 0.1), "C4 0.6/0.3/0.1": (0.6, 0.3, 0.1), "F 只结构": (1, 0, 0), "G 只语义": (0, 0, 1), "H 只拓扑": (0, 1, 0)}


TAG_RE = re.compile(r"\[([^\]]+)\]")


def one_liner(q, tags, extra=""):
    f = q["f"]
    s = (f"{q['name']} 昨日{f['prev']}{'' if f['h'] == '0' else f['h'] + '连板'}, 今天开盘{f.get('gap'):+.1f}%, 在较昨收{f.get('px_pct'):+.1f}%处{q['side']}"
         if f.get("gap") is not None and f.get("px_pct") is not None else f"{q['name']} {q['side']}")
    if f["hold"].startswith(("被套", "浮盈")):
        s += f", 手里这只{f['hold']}"
    elif f["hold"] == "未持有":
        s += ", 新开仓"
    if tags:
        s += f"({tags})"
    if f.get("stk_gap") is not None:
        s += f", 正股开盘{f['stk_gap']:+.1f}%"
    return s + (", " + extra if extra else "")


PREVG = {"涨停": "涨停", "炸板": "炸板", "炸板·收涨": "炸板", "炸板·收跌": "炸板", "跌停": "跌", "大跌": "跌", "平": "平", "大涨": "平"}


def holdg(h):
    return "未持有" if h == "未持有" else "浮盈" if h.startswith("浮盈") else "被套" if h.startswith("被套") else "其他"


def hgrp(h):
    return "0" if h == "0" else "1~2" if h in ("1", "2") else "3+"


def adj(k, a, b):
    if a is None or b is None:
        return False
    if a == b:
        return True
    o = CR.ORD.get(k)
    return bool(o and a in o and b in o and abs(o.index(a) - o.index(b)) == 1)


def judge(qf, cf, q_play=None, c_play=None):
    m = []
    m.append(PREVG.get(qf["prev"]) == PREVG.get(cf["prev"]))
    m.append(adj("pxb", qf.get("pxb"), cf.get("pxb")))
    m.append(adj("gapb", qf.get("gapb"), cf.get("gapb")))
    hm = holdg(qf["hold"]) == holdg(cf["hold"])
    m.append(hm)
    if qf["asset"] == "股票":
        m.append(hgrp(qf["h"]) == hgrp(cf["h"]))
    else:
        a, b = qf.get("stk_gap"), cf.get("stk_gap")
        m.append(a is not None and b is not None and (a >= 0) == (b >= 0))
    n = sum(m)
    same_play = bool(q_play and c_play and q_play == c_play)
    if n >= 4 and hm:
        return "像", n, same_play
    if n >= 3 or (n >= 2 and same_play):
        return "部分像", n, same_play
    return "不像", n, same_play


GENERIC = {"开盘5分钟", "早盘", "上午", "盘中", "午后", "尾盘", "放量", "缩量", "昨龙虎榜", "热点题材", "新开", "加仓/回补"}


def tags_of(cs):
    """日卡成交行方括号里的行为标签(炸板次日 / 竞价 / 低吸 / 追涨 / 止损 / 冲高止盈…); 去掉纯时段 / 量能类"""
    out = set()
    for line in (cs.get("txt") or {}).get("card_trades") or []:
        m = TAG_RE.search(line)
        if m:
            out |= {t.strip() for t in m.group(1).split("/") if t.strip()}
    return out - GENERIC


MAIN = ("连板接力", "首板次日", "炸板次日", "首板", "反包", "跌停次日", "趋势", "超跌", "转债", "低位首板", "回调", "ETF/宽基")
EXEC = ("打板", "追涨", "低吸", "竞价")
SELLK = ("日内T", "止损", "冲高止盈", "止盈", "时间止损/平走", "小盈亏快出", "成本未知")


def beh_of(tags):
    main = next((t for t in tags if t in MAIN or t.endswith("次日")), None)
    ex = next((t for t in EXEC if t in tags), None)
    sk = next((t for t in SELLK if t in tags), None)
    return main, ex, sk


def judge_strict(q, qtags, qplay, cs, cplay):
    """严判(和硬过滤不同源, 10/26 加): 数值近 = |开盘差| ≤2 点、|成交价差| ≤2 点、持仓浮盈差 ≤4 点(或都未持有) 三项里对上几项;
    行为近 = 日卡行为标签: 买 = 主打法(连板接力 / 首板次日 / 炸板次日…)相同 且 执行(打板 / 追涨 / 低吸 / 竞价, 两边都有才比)相同; 卖 = 卖出类型(止损 / 冲高止盈 / 止盈 / 日内T…)相同;
    或日卡"手法类"相同。标签里"低吸"用当天全天区间(事后口径), 手法类是模型事后解读 —— 只用于评估, 不进检索
    像 = 数值近 ≥2 且 行为近; 部分像 = 之一; 不像 = 都不满足"""
    qf, cf = q["f"], cs["f"]
    num = 0
    for k in ("gap", "px_pct"):
        a, b = qf.get(k), cf.get(k)
        num += int(a is not None and b is not None and abs(a - b) <= 2)
    ha, hb = qf.get("hold_pnl"), cf.get("hold_pnl")
    num += int((ha is None and hb is None and qf["hold"] == cf["hold"]) or (ha is not None and hb is not None and abs(ha - hb) <= 4))
    ct = tags_of(cs) | ({"转债"} if cf.get("asset") in ("转债", "妖债") else set()) | ({"竞价"} if (cs["t"] or "")[:5] <= "09:25" else set())
    qm, qe, qs = beh_of(qtags)
    cm, ce, ck = beh_of(ct)
    if q["side"] == "买":
        beh = bool(qm and qm == cm and (not qe or not ce or qe == ce))
    else:
        beh = bool(qs and qs == ck)
    pe = bool(qplay and cplay and qplay == cplay)
    beh = beh or pe
    ov = [x for x in ((qm if qm and qm == cm else None), (qe if qe and qe == ce else None), (qs if qs and qs == ck else None)) if x]
    lab = "像" if num >= 2 and beh else "部分像" if (num >= 2 or beh) else "不像"
    return lab, num, ov, pe


def play_of(cs, cards):
    card = cards.get(cs["skill"], {}).get(cs["d"]) or {}
    m = re.search(r"手法类=([^;；]+)", card.get("interp") or "")
    return m.group(1).strip() if m else None


KEY = {("zhiyingjuexin", "2026-10-23", "002368", "买", 0): ("K1 太极股份: 芷影竞价低开 −8.2% 低吸降成本", "竞价低开8%低吸加仓, 想开盘反抽时卖掉降成本(做T)"),
       ("zhiyingjuexin", "2026-10-23", "002696", "买", 0): ("K2 百洋股份: 炸板次日越跌越买", "昨天炸板天地板被套, 今天从高处一路往下分批越跌越买"),
       }


def run(d0="2026-10-20", d1="2026-10-23", tag=""):
    EV.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    S = CR.store()
    log_ = []
    cards = {m: CR.parse_cards(m) for m in MENTORS}
    cards_all = {}
    for sd in (ROOT / "skills").glob("*-skill"):
        if (sd / "persona" / "case_log").exists():
            cards_all[sd.name[:-6]] = CR.parse_cards(sd.name[:-6])
    # 考题 = 索引里 10/20~10/23 四位导师的决策点(和索引同一套切法); 情境由 query_situation 现算(走实盘会用的那条路), 再和索引里的特征对账
    sits = [cs for cs in S["cases"] if cs["skill"] in MENTORS and d0 <= cs["d"] <= d1]
    sits.sort(key=lambda x: (x["d"], x["t"]))
    print(f"考题 {len(sits)} 个(决策点)")
    c = CR.cur()
    c.execute("select open from investment_market.kline_day where symbol='sh111024' and trade_date='2026-10-23'")
    op = float(c.fetchone()[0])
    k3 = {"id": "K3", "skill": "buchitudou0", "d": "2026-10-23", "code": "111024", "name": "澳弘转债", "side": "买", "t": "09:25:00", "px": op, "k": 0, "virtual": True,
          "f": {"hold": "未持有", "hold_pnl": None, "pos_total": 0.0}, "n_legs": 0,
          "key": ("K3 澳弘转债 111024: 转债和正股双双低开", "转债和正股双双低开, 竞价要不要买、开盘怎么走")}
    if not tag:
        sits.append(k3)
    out = []
    qcache = {}
    mism = []
    for s in sits:
        kk = (s["skill"], s["d"], s["code"], s["side"], s["k"])
        if kk in KEY:
            s["key"] = KEY[kk]
        ta = time.time()
        ctx = {"hold": s["f"]["hold"], "hold_pnl": s["f"]["hold_pnl"], "pos_total": s["f"]["pos_total"], "addon": s["f"].get("addon")}
        px = s["legs"][0][1] if s.get("legs") else s["px"]
        q = CR.query_situation(s["code"], s["d"], s["side"], px, s["t"], ctx, c)
        q["skill"] = s["skill"]
        if not s.get("virtual"):
            bad = [k for k in ("prev", "h", "gapb", "pxb", "box", "mkt", "stk_gapb", "theme", "tier", "act") if q["f"].get(k) != s["f"].get(k)]
            if bad:
                mism.append((s["id"], {k: (q["f"].get(k), s["f"].get(k)) for k in bad}))
        card = cards.get(s["skill"], {}).get(s["d"]) or {}
        tags = ""
        for line in card.get("trades") or []:
            if CR.nkey(s["name"])[:3] in CR.nkey(line) and f" {s['side']} " in line[:14]:
                m = TAG_RE.search(line)
                tags = m.group(1) if m else ""
                break
        m = re.search(r"手法类=([^;；]+)", card.get("interp") or "")
        play = m.group(1).strip() if m else None
        qtags = (tags_of(s) | ({"转债"} if s["code"][:2] in ("11", "12") else set()) | ({"竞价"} if s["t"][:5] <= "09:25" else set())) if not s.get("virtual") else {"转债", "竞价"}
        tq = time.time() - ta
        text = one_liner(q, tags, s["key"][1] if s.get("key") else "")
        te = time.time()
        vec = CR.embed([text])[0]
        te = time.time() - te
        res = {}
        for wn, w in WSETS.items():
            R = CR.retrieve(q, text, w, qvec=vec)
            picks = R["pos"] + R["neg"]
            js = []
            for x in picks:
                cs = x[7]
                j = judge(q["f"], cs["f"], play, play_of(cs, cards_all))
                j2 = judge_strict(q, qtags, play, cs, play_of(cs, cards_all))
                js.append({"strict": j2[0], "num": j2[1], "tag_ov": j2[2], "play_eq": j2[3], "id": cs["id"], "lab": x[5], "score": round(x[0], 3), "struct": round(x[1], 3), "topo": round(x[2], 3), "sem": round(x[3], 3) if x[3] is not None else None,
                           "judge": j[0], "core": j[1], "same_play": j[2], "same_code": cs["code"] == s["code"], "same_skill": cs["skill"] == s["skill"]})
            res[wn] = {"ms": R["ms"], "n": len(R["cell"]), "dropped": R["dropped"], "picks": js}
            if w == CR.DEF_W:
                (EV / ("render" + tag)).mkdir(exist_ok=True)
                rid = f"{s['d']}_{s['skill']}_{s['code']}_{s['side']}_{s['k']}"
                rendered = CR.render(R, text)
                (EV / ("render" + tag) / f"{rid}.md").write_text(rendered, encoding="utf-8")
                cnt = collections.Counter(x[5][:2] for x in R["cell"])
                res[wn]["dist"] = {"正": cnt["正"], "负": cnt["负"], "平": cnt["平"], "待核": cnt["待核"], "hmax": CR.dist_line(R["cell"], "hmax"), "c3": CR.dist_line(R["cell"], "c3"),
                                   "c1": CR.dist_line(R["cell"], "c1")}
                res[wn]["rid"] = rid
        # 消融: 放宽顺序 / 不做硬过滤(都用 A 权重)
        for vn, rl in (("动作类不做硬过滤(只打分)", [("drop", "act")] + CR.RELAX),
                       ("无硬过滤", []), ("旧放宽(逐个去掉, 10/25 初版)", CR.RELAX_OLD), ("放宽顺序反转(先去最重要的)", [("drop", k) for k in CR.CONDS] + [("drop", "asset")])):
            Rv = CR.retrieve(q, text, (0.5, 0.3, 0.2), qvec=vec, relax=rl)   # 消融都用 A 权重(和 A 行对比)
            pk = Rv["pos"] + Rv["neg"]
            res[vn] = {"picks": [{"judge": judge(q["f"], x[7]["f"], play, play_of(x[7], cards_all))[0], "strict": judge_strict(q, qtags, play, x[7], play_of(x[7], cards_all))[0],
                                  "id": x[7]["id"], "lab": x[5]} for x in pk], "n": len(Rv["cell"]), "ms": Rv["ms"], "dropped": Rv["dropped"]}
        out.append({"qtags": sorted(qtags), "s": {k: v for k, v in s.items() if k in ("id", "skill", "d", "code", "name", "side", "t", "px", "k", "n_legs", "key", "virtual")}, "legs": (s.get("legs") or [])[:12], "play": play, "tags": tags, "text": text,
                    "qf": {k: v for k, v in q["f"].items() if k != "seats"}, "seats": q["f"].get("seats"), "t_query_s": round(tq, 2), "t_embed_s": round(te, 2), "res": res})
        print(f"{s['d']} {s['t'][:5]} {s['skill']} {s['name']} {s['side']}#{s['k']} {q['f']['hold']} n={res['C 0.7/0.2/0.1']['n']} 放宽{res['C 0.7/0.2/0.1']['dropped']} "
              f"判={[p['judge'] for p in res['C 0.7/0.2/0.1']['picks']]} 情境{tq:.2f}s embed{te:.2f}s 检索{res['C 0.7/0.2/0.1']['ms']}ms", flush=True)
    print(f"情境对账: {len(sits) - 1} 题里 query_situation 与索引特征不一致 {len(mism)} 题", mism[:5])
    (EV / f"mismatch{tag}.json").write_text(json.dumps(mism, ensure_ascii=False, indent=1), encoding="utf-8")
    (EV / f"raw{tag}.jsonl").write_text("".join(json.dumps(o, ensure_ascii=False, default=str) + "\n" for o in out), encoding="utf-8")
    print(f"完成 {len(out)} 题 {time.time() - t0:.0f}s → {EV}")


def onto(n=30, seed=1026):
    """事件本体抽查材料: 题材 12 / 梯队位置 8 / 席位 10, 每条附 md 原文片段"""
    EV.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{CR.ONTO}?mode=ro", uri=True)
    rnd = random.Random(seed)
    th = con.execute("select eid, code, d, tags from event where kind='theme' and d >= '2026-07-01'").fetchall()
    se = con.execute("select eid, code, d, sub, tags from event where kind='seat' and d >= '2026-07-01' and d <= '2026-10-23'").fetchall()
    pick_t = rnd.sample(th, 20)
    pick_s = rnd.sample(se, 10)
    c = CR.cur()
    L = []
    for j, (eid, code, d, tags) in enumerate(pick_t):
        t = json.loads(tags)
        y, m = d[:4], int(d[5:7])
        txt = (ROOT / "md" / f"{y}S{(m - 1) // 3 + 1}" / f"{d}.md").read_text(encoding="utf-8", errors="replace")
        za = CR.section(txt, "涨停分析", level=2)
        c.execute("select name from investment_market.security_master where code=%s and sec_type='STOCK' limit 1", (code,))
        r_ = c.fetchone()
        nm_ = CR.nkey(r_[0]) if r_ else code
        rows = []
        for bn, body in CR.subblocks(za, level=3):
            hit = [l for l in body.splitlines() if l.startswith("|") and (code in l or nm_ in CR.nkey(l))]
            if hit:
                tbl = [l for l in body.splitlines() if l.startswith("|") and "股票名称" not in l and not re.match(r"^\|\s*:?-", l)]
                rows.append(f"md 题材块「{bn}」(共 {len(tbl)} 行) 本票行: " + hit[0][:160])
                rows += ["  同块前 3 行: " + x[:120] for x in tbl[:3]]
        lad = CR.section(txt, "涨停梯队", level=2)
        lad_l = [l for l in lad.splitlines() if code in l]
        kind = "题材" if j < 12 else "梯队位置"
        L.append({"no": j + 1, "kind": kind, "eid": eid, "claim": f"{code} {d} 题材={t['theme']} 板数={t['boards']} 梯队位置={t['pos']} 阶段={t['stage']}",
                  "md_rows": rows[:14], "ladder": lad_l[:3]})
    for k, (eid, code, d, dept, tags) in enumerate(pick_s):
        t = json.loads(tags)
        c.execute("select max(dept_name), sum(net_amt) from investment_market.lhb_seat where trade_date=%s and code=%s and dept_code=%s", (d, code, dept))
        dn, na = c.fetchone()
        y, m = d[:4], int(d[5:7])
        f = ROOT / "md" / f"{y}S{(m - 1) // 3 + 1}" / f"{d}.md"
        txt = f.read_text(encoding="utf-8", errors="replace") if f.exists() else ""
        mm = re.search(r"^#### [^\n]*" + code + r"\s*$(.*?)(?=^#### |^### |^## |\Z)", txt, re.S | re.M)
        L.append({"no": 21 + k, "kind": "席位", "eid": eid, "claim": f"{code} {d} 席位 {dn}(别名 {t['alias']}, 风格 {t['style']}) 净买 {float(na or 0) / 1e4:.0f} 万 排名 {t['rank']}",
                  "md_rows": (mm.group(1).strip().splitlines()[:4] if mm else ["(md 龙虎榜没有这只票的小节)"]), "ladder": []})
    (EV / "onto_sample.json").write_text(json.dumps(L, ensure_ascii=False, indent=1), encoding="utf-8")
    md = []
    for x in L:
        md.append(f"### {x['no']}. [{x['kind']}] {x['claim']}\n" + "\n".join("    " + r[:300] for r in x["md_rows"]) + ("\n    梯队: " + " / ".join(x["ladder"]) if x["ladder"] else ""))
    (EV / "onto_sample.md").write_text("\n\n".join(md), encoding="utf-8")
    print(f"→ {EV / 'onto_sample.md'}")


def summary(tag=""):
    """raw.jsonl → 报告用表格(markdown 片段, eval/summary.md)"""
    R = [json.loads(l) for l in (EV / f"raw{tag}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    S = CR.store()
    byid = {cs["id"]: cs for cs in S["cases"]}
    L = []
    # 1) 各权重组 / 消融: 像的比例(按案例计 + 按题计)
    L += ["| 方案 | 案例数 | 宽判 像 | 严判 像 | 严判 部分像 | 严判 不像 | 严判 像的比例 | 严判 像+部分像 | 正样本严判像 | 负样本严判像 | 有同票案例的题 | 平均格子 n |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for wn in list(WSETS) + ["动作类不做硬过滤(只打分)", "无硬过滤", "旧放宽(逐个去掉, 10/25 初版)", "放宽顺序反转(先去最重要的)"]:
        P = [p_ for r in R for p_ in r["res"][wn]["picks"]]
        js = [p_["judge"] for p_ in P]
        ss = collections.Counter(p_["strict"] for p_ in P)
        pos_ = [p_ for p_ in P if p_.get("lab") == "正"]
        neg_ = [p_ for p_ in P if p_.get("lab") == "负"]
        same = sum(1 for r in R if any(byid.get(p_.get("id"), {}).get("code") == r["s"]["code"] for p_ in r["res"][wn]["picks"]))
        n = len(P) or 1
        L.append(f"| {wn} | {len(P)} | {js.count('像') / n:.0%} | {ss['像']} | {ss['部分像']} | {ss['不像']} | **{ss['像'] / n:.0%}** | {(ss['像'] + ss['部分像']) / n:.0%} | "
                 f"{sum(1 for p_ in pos_ if p_['strict'] == '像')}/{len(pos_)} | {sum(1 for p_ in neg_ if p_['strict'] == '像')}/{len(neg_)} | {same}/{len(R)} | "
                 f"{sum(r['res'][wn]['n'] for r in R) / len(R):.0f} |")
    # 1b) 按"票 × 日"成簇的 bootstrap(考题高度相关: 同一只票同一天拆成多个决策点), 2000 次; 和 A 的配对差
    rnd = random.Random(7)
    clus = collections.defaultdict(list)
    for i, r in enumerate(R):
        clus[(r["s"]["code"], r["s"]["d"])].append(i)
    keys = list(clus)

    def rate(wn, idx):
        P = [p_ for i in idx for p_ in R[i]["res"][wn]["picks"]]
        return sum(p_["strict"] == "像" for p_ in P) / max(1, len(P))
    L += ["", f"成簇 bootstrap(票×日 {len(keys)} 簇, 2000 次): 严判像的比例 90% 区间 · 和 A 的配对差 90% 区间", ""]
    for wn in [w for w in list(WSETS) + ["动作类不做硬过滤(只打分)", "无硬过滤", "旧放宽(逐个去掉, 10/25 初版)", "放宽顺序反转(先去最重要的)"]]:
        bs, df = [], []
        for _ in range(2000):
            idx = [i for k in (rnd.choice(keys) for _ in keys) for i in clus[k]]
            x, y = rate(wn, idx), rate("A 结构0.5/拓扑0.3/语义0.2", idx)
            bs.append(x)
            df.append(x - y)
        bs.sort()
        df.sort()
        L.append(f"- {wn}: {bs[100]:.0%}~{bs[1900]:.0%} · 差 {df[100]:+.0%}~{df[1900]:+.0%}")
    # 1c) 拆开看: 数值近 / 行为近 各自命中率(A / C / F / G)
    L += ["", "| 方案 | 数值近(≥2/3) | 行为近 |", "|---|---|---|"]
    for wn in ("A 结构0.5/拓扑0.3/语义0.2", "C 0.7/0.2/0.1", "F 只结构", "G 只语义", "H 只拓扑"):
        P = [p_ for r in R for p_ in r["res"][wn]["picks"] if "num" in p_]
        L.append(f"| {wn} | {sum(p_['num'] >= 2 for p_ in P) / len(P):.0%} | {sum(bool(p_['tag_ov']) or p_['play_eq'] for p_ in P) / len(P):.0%} |")
    # 2) 放宽次数分布
    dr = collections.Counter(len(r["res"]["C 0.7/0.2/0.1"]["dropped"]) for r in R)
    L += ["", "放宽步数分布(C 权重 = 默认): " + " · ".join(f"{k} 步 {v} 题" for k, v in sorted(dr.items()))]
    steps = collections.Counter(tuple(x) if isinstance(x, list) else x for r in R for x in r["res"]["C 0.7/0.2/0.1"]["dropped"])
    L.append("各步被用到的次数: " + " · ".join(f"{CR.step_cn(tuple(k))} {v}" for k, v in steps.most_common()))
    # 3) 耗时
    ms = sorted(r["res"]["C 0.7/0.2/0.1"]["ms"] for r in R)
    tq = sorted(r["t_query_s"] for r in R)
    te = sorted(r["t_embed_s"] for r in R)
    L.append(f"耗时(n={len(R)}): 情境计算 中位 {tq[len(tq) // 2] * 1000:.0f} ms 最大 {tq[-1] * 1000:.0f} ms · bge-m3 一句话 中位 {te[len(te) // 2] * 1000:.0f} ms 最大 {te[-1] * 1000:.0f} ms · "
             f"检索打分 中位 {ms[len(ms) // 2]} ms 最大 {ms[-1]} ms")
    # 4) 逐题表
    L += ["", "| # | 情境一句话 | 格子 n · 正/负/平 · 3 日最高均值 / P10 / 最差 | 3 个案例(机械判) | 放宽步数 |", "|---|---|---|---|---|"]
    for i, r in enumerate(R, 1):
        a = r["res"]["C 0.7/0.2/0.1"]
        d = a.get("dist", {})
        cs_ = []
        for p_ in a["picks"]:
            c0 = byid.get(p_["id"])
            if c0:
                cs_.append(f"{p_['lab']}·{c0['mentor']} {c0['d'][5:]} {c0['name']}→**{p_['strict']}**(数值{p_['num']}/3, 标签{'+'.join(p_['tag_ov']) or '无'}{', 同手法' if p_['play_eq'] else ''})")
        key = f"**{r['s']['key'][0]}** " if r["s"].get("key") else ""
        L.append(f"| {i} | {key}{r['s']['d'][5:]} {r['s']['t'][:5]} {r['s']['skill']}: {r['text'][:90]} | n={a['n']} · {d.get('正')}/{d.get('负')}/{d.get('平')} · "
                 f"{(d.get('hmax') if r['s']['side'] == '买' else d.get('c1', '')).replace('n=', 'n')[:60]} | {'<br>'.join(cs_)} | {len(a['dropped'])} |")
    (EV / f"summary{tag}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:20]))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    {"run": run, "onto": onto, "summary": summary}[sys.argv[1]](*sys.argv[2:])
