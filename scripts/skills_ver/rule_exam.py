# -*- coding: utf-8 -*-
"""rule_exam.py — 导师规则样本外拟人体检(零 token; 10/26 凌晨建, 诊断 docs/review/distill_diagnosis_20261026.md 改进建议 ★P1 / A 的第 1~4 步)

问: 把 skill 的整套规则放在一起、按"越窄越优先"取舍, 在最近 N 个交易日导师本人的真实动作上像不像? 赢不赢最笨的两个基线?
输入:
  skills/<id>-skill/persona/rule_triggers.json   每条规则一行机器可判的触发条件(DSL 见 rule_dsl.py); rules.md 不读规则内容, 只读出生日
  scripts/skills_ver/exam_samples.py             最近 N 日 + 之前 lookback 日的持仓日 / 新开仓 / 账户日样本(只读)
考卷: 最近 N 个交易日(--days, 默认 20)的样本; 之前 lookback 日只用来 ① 训练两个基线 ② 算规则命中率(具体度)
输出:
  每条规则: 覆盖 / 一致 / 误报(叫做没做) / 反向(叫不做却做), 全窗口 + 出生后两组
  每个样本: 一致 / 不一致 / 冲突 / 没覆盖; 整套一致率; 冲突按"越窄越优先"裁决后的一致率
  基线: M0 = 训练段多数动作(总是清 / 总是竞价), M2 = 今日开盘档查表(格 n<3 退回 M0); 规则 = 裁决后那条推出的同一标签
  防偷看: 规则 when 用到决策时刻还不知道的字段(rule_dsl.FIELDS 的 known 档晚于决策时刻) → 标"含当日信息", 不计入整套(另报一组"计入时"作对照)
  出生期隔离(A4): 规则出生日(rules.md「时间状态: 建立 …」; JSON modified 更晚就用 modified)及之前的样本不算它的核销; 出生后 <3 个 → 待核销
  重复犯错(A4): 出生后同一条规则连续两个交易日判错, 或同一种错(同情境格 × 同错误方向)累计 ≥2 次 → 标红
  准入闸(A3, --candidate): 候选 vs 现行同一份考卷各跑一遍; 四条全满足才"通过": 一致率不降 / 冲突不升 / 误报不升 / 赢过 M0、M2 至少一个; 否则"进观察池"
产物: docs/review/rule_exam_<YYYYMMDD>.md + results/skill_exam/<YYYYMMDD>/<id>.json(候选模式: candidate_<id>.json + docs/review/rule_exam_candidate_<YYYYMMDD>_<id>.md)
用法:
  python rule_exam.py --skill zhiyingjuexin[,liuyiqing,...] [--days 20] [--end 2026-10-23] [--drop 2026-10-22,2026-10-23]
  python rule_exam.py --skill zhiyingjuexin --candidate <候选 rule_triggers.json | 补丁 json | 含 ```json 触发块的 md> [--trigger-dates 2026-10-22,2026-10-23]
  python rule_exam.py --skill ... --write-specific      (把 180 日命中率回写 rule_triggers.json 的 specific / broad 字段; 只改这两个字段)
"""
import argparse
import copy
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import exam_samples as ES  # noqa: E402
import rule_dsl as DSL  # noqa: E402
import open_bins as OB  # noqa: E402

NAMES = {"zhiyingjuexin": "芷影攫心", "liuyiqing": "刘忆青", "zuoshoudeirong": "做手德融", "buchitudou0": "不吃土豆0"}
BROAD = 0.70      # 命中率 ≥70% = 宽规则(几乎天天命中)
MIN_POST = 3      # 出生后样本 <3 → 待核销


# ------------------------------------------------------------------ 规则加载 / 候选合并 / 出生日 ------------------------------------------------------------------
def trig_path(sk):
    return ROOT / f"skills/{sk}-skill/persona/rule_triggers.json"


def load_triggers(sk, path=None):
    T = json.loads(Path(path or trig_path(sk)).read_text(encoding="utf-8"))
    for r in T["rules"]:
        r.setdefault("kind", "pos")
    return T


def _md_blocks(text):
    """从 md 里抽 ```json / ```rule_trigger 代码块里的触发条件(一块一条或一个 list)"""
    out = []
    for m in re.finditer(r"```(?:json|rule_trigger)\s*\n(.*?)```", text, re.S):
        try:
            v = json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            continue
        for x in (v if isinstance(v, list) else v.get("rules", [v]) if isinstance(v, dict) else []):
            if isinstance(x, dict) and "id" in x and ("when" in x or x.get("remove")):
                out.append(x)
    return out


def apply_candidate(base, cand_path):
    """候选: ① 完整 rule_triggers.json(有 skill + rules 且 mode != patch) → 整份替换; ② 补丁 {"rules": [...]} / md 触发块 → 按 id 替换 / 新增, remove:true 删除。
    返回 (候选 T, 变动 id 列表)"""
    p = Path(cand_path)
    txt = p.read_text(encoding="utf-8")
    old = {r["id"]: r for r in base["rules"]}
    if p.suffix.lower() == ".md":
        patch, full = _md_blocks(txt), None
    else:
        v = json.loads(txt)
        if isinstance(v, dict) and v.get("skill") and v.get("mode", "full") != "patch":
            full, patch = v, None
        else:
            full, patch = None, (v if isinstance(v, list) else v.get("rules", []))
    if full is not None:
        T = copy.deepcopy(full)
        for r in T["rules"]:
            r.setdefault("kind", "pos")
        new = {r["id"]: r for r in T["rules"]}
        changed = sorted([i for i in new if i not in old or json.dumps(new[i], sort_keys=True) != json.dumps(old[i], sort_keys=True)] + [f"-{i}" for i in old if i not in new])
        return T, changed
    T = copy.deepcopy(base)
    idx = {r["id"]: i for i, r in enumerate(T["rules"])}
    changed = []
    for x in patch:
        if x.get("remove"):
            if x["id"] in idx:
                T["rules"] = [r for r in T["rules"] if r["id"] != x["id"]]
                idx = {r["id"]: i for i, r in enumerate(T["rules"])}
                changed.append(f"-{x['id']}")
            continue
        x = dict(x)
        x.setdefault("kind", "pos")
        x.pop("pool", None)                                   # 候选要按"进主体"来考
        x.setdefault("modified", dt.date.today().isoformat())  # 候选的出生日 = 今天(考卷全在出生前 = 样本内)
        if x["id"] in idx:
            T["rules"][idx[x["id"]]] = x
        else:
            T["rules"].append(x)
            idx[x["id"]] = len(T["rules"]) - 1
        changed.append(x["id"])
    return T, changed


def dump_triggers(T):
    """一条规则一行(人能 diff), 头部字段各一行"""
    head = {k: v for k, v in T.items() if k != "rules"}
    L = ["{"] + [f' {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)},' for k, v in head.items()] + [' "rules": [']
    rs = list(T["rules"])
    for i, r in enumerate(rs):
        L.append("  " + json.dumps(r, ensure_ascii=False) + ("," if i < len(rs) - 1 else ""))
    L += [" ]", "}"]
    return "\n".join(L) + "\n"


def base_id(rid):
    m = re.match(r"(R\d+)", rid)
    return m.group(1) if m else rid


def births(sk):
    """rules.md: 「### Rn 标题」之后最近的「时间状态: 建立 YYYY-MM-DD」; 读不到 → 修订记录里第一次提到 Rn 的日期行; 再读不到 → 未知"""
    f = ROOT / f"skills/{sk}-skill/persona/rules.md"
    out = {}
    if not f.exists():
        return out
    lines = f.read_text(encoding="utf-8").splitlines()
    cur = None
    for ln in lines:
        m = re.match(r"^###\s+(R\d+)\b", ln)
        if m:
            cur = m.group(1)
            continue
        if cur and cur not in out:
            m2 = re.search(r"时间状态\**[:：]\s*建立\s*(\d{4}-\d{2}-\d{2})", ln)
            if m2:
                out[cur] = (m2.group(1), "rules.md 时间状态")
        if ln.startswith("## ") and not ln.startswith("## 10/25") and cur:
            cur = None if "规则" not in ln else cur
    # 兜底: 修订记录
    rev = []
    in_rev = False
    for ln in lines:
        if ln.startswith("## "):
            in_rev = "修订记录" in ln or "CHANGELOG" in ln.upper()
            continue
        if in_rev:
            m = re.match(r"^-\s*(\d{4}-\d{2}-\d{2})", ln)
            if m:
                rev.append((m.group(1), ln))
    for d, ln in rev:
        for rid in re.findall(r"\bR\d+\b", ln):
            out.setdefault(rid, (d, "修订记录首次提到"))
    return out


def eff_birth(rule, B):
    b = B.get(base_id(rule["id"]))
    born = b[0] if b else None
    mod = rule.get("modified")
    if born and mod:
        return max(born, mod), (b[1] + (f" / 改 {mod}" if mod > born else ""))
    if mod:
        return mod, "JSON modified(rules.md 读不到建立日)"
    if born:
        return born, b[1]
    return None, "出生日未知"


# ------------------------------------------------------------------ 判定 ------------------------------------------------------------------
def is_look(r):
    return bool(r.get("look")) or bool(DSL.look_fields(r))


def is_dir(r):
    return r.get("act") != "无方向"


def fires(r, s):
    if not DSL.match(r.get("when"), s) or not DSL.match(r.get("given"), s):
        return False
    if r["kind"] == "pos" and r.get("act") in DSL.COND_SELL and not s.get("n_sell"):
        return False
    return True


def ok_of(r, s, o=None):
    if r["kind"] == "pos":
        return DSL.pos_ok(r, o or DSL.real_o(s))
    return DSL.match(r.get("expect"), s)


def is_active(r):
    if r["kind"] == "pos":
        return r["act"] in DSL.ACTIVE
    return not r.get("passive")


def gb(x):
    if x is None:
        return "?"
    return "≤-5%" if x <= -0.05 else "-5~-2%" if x < -0.02 else "±2%" if x <= 0.02 else "2~5%" if x < 0.05 else "≥5%"


def cell_of(s, kind, sk):
    """情境格(冲突聚类 / 重复犯错用)"""
    if kind == "pos":
        return f"{'昨新开' if s.get('yest_new') else '老仓'}·昨{s.get('st_prev') or '?'}·开{gb(s.get('gap'))}"
    if kind == "open":
        return f"打法 {s.get('play') or '?'}"
    if sk in ES.TUDOU:
        return f"正股竞价{gb(s.get('stk_auc'))}·转债竞价{gb(s.get('bond_auc'))}"
    return f"昨收仓{'空' if s.get('empty_prev') else '<50%' if (s.get('tot0') or 0) < 0.5 else '≥50%'}·上证开{gb(s.get('idx_gap'))}"


def real_desc(s, kind, sk):
    if kind == "pos":
        return f"{s['act']}(首卖 {(s.get('t_sell1') or '-')[:5]} / 首买 {(s.get('t_buy1') or '-')[:5]})"
    if kind == "open":
        bv = s.get("buy_vs_pc1")
        return f"新开 {(s.get('t_buy1') or '-')[:5]} 买价{'' if bv is None else f'{bv:+.1%}'} 收盘仓 {s.get('pp1', 0):.0%}"
    if sk in ES.TUDOU:
        if not s.get("traded"):
            return "空手"
        return f"首笔 {s.get('first_channel')} {s.get('first_buy_name') or ''} {(s.get('first_buy') or '')[:8]}"
    return f"收盘仓 {s.get('tot0', 0):.0%}→{s.get('tot1', 0):.0%} 新开 {s.get('n_new')}"


def samples_of(S, kind, dates):
    rows = S[kind]
    if kind == "day":
        return [d for d in rows if d["date"] in dates and not d.get("missing")]
    return [p for p in rows if p["date"] in dates and not p.get("data_gap")]


def spec_rates(T, S, train_dates):
    """具体度 = 训练段(考卷之前)该类样本里的命中率; 越小越窄"""
    out = {}
    for r in T["rules"]:
        P = samples_of(S, r["kind"], train_dates)
        out[r["id"]] = round(sum(1 for s in P if fires(r, s)) / max(1, len(P)), 4) if P else r.get("specific", 1.0)
    return out


def evaluate(T, S, test_dates, FR, B, include_look=False, birth_gate=False):
    """一份考卷 × 一套规则 → {samples, rules, summary}
    include_look: 含当日信息的规则也参与(对照用); birth_gate: 规则只在出生后的样本上参与(出生后口径)"""
    sk = S["skill"]
    route_first = (T.get("route") or {}).get("mode") == "first_hit"
    RS = []
    for r in T["rules"]:
        if r.get("pool"):   # 观察池(没过准入闸)的规则不进整套; exam_skill 单独给它们出一张表
            continue
        r2 = dict(r)
        r2["_look"] = is_look(r)
        r2["_birth"], r2["_birth_src"] = eff_birth(r, B)
        RS.append(r2)
    rstat = {r["id"]: {"id": r["id"], "kind": r["kind"], "act": r.get("act"), "look": r["_look"], "birth": r["_birth"], "birth_src": r["_birth_src"],
                       "fire": 0, "dir": 0, "ok": 0, "fp": 0, "rev": 0, "post_dir": 0, "post_ok": 0, "post_fp": 0, "post_rev": 0, "wrong": []} for r in RS}
    out = []
    for kind in ("pos", "open", "day"):
        for s in samples_of(S, kind, test_dates):
            o = DSL.real_o(s) if kind == "pos" else None
            fired = []
            for r in RS:
                if r["kind"] != kind:
                    continue
                if r["_look"] and not include_look:
                    continue
                if birth_gate and r["_birth"] and s["date"] <= r["_birth"]:
                    continue
                if fires(r, s):
                    fired.append(r)
            if kind == "pos" and route_first:
                routed = [r for r in fired if r.get("route")]
                if routed:
                    mn = min(r["route"] for r in routed)
                    fired = [r for r in fired if not r.get("route") or r["route"] == mn]
            dirs = [r for r in fired if is_dir(r)]
            res = []
            for r in fired:
                st = rstat[r["id"]]
                st["fire"] += 1
                if not is_dir(r):
                    res.append((r["id"], None))
                    continue
                k = bool(ok_of(r, s, o))
                post = (r["_birth"] is not None) and s["date"] > r["_birth"]
                st["dir"] += 1
                st["ok"] += k
                if post:
                    st["post_dir"] += 1
                    st["post_ok"] += k
                if not k:
                    side = "fp" if is_active(r) else "rev"
                    st[side] += 1
                    if post:
                        st["post_" + side] += 1
                    st["wrong"].append({"date": s["date"], "name": s.get("name") or "账户日", "real": real_desc(s, kind, sk), "cell": cell_of(s, kind, sk),
                                        "said": r.get("act"), "post": post})
                res.append((r["id"], k))
            if not fired:
                v = "没覆盖"
            elif not dirs:
                v = "只有无方向"
            else:
                if kind == "pos":
                    feas = DSL.pos_feasible(dirs)
                else:
                    sg = defaultdict(set)
                    for r in dirs:
                        if r.get("dim"):
                            sg[r["dim"]].add(r.get("sign", 1))
                    feas = all(len(v_) <= 1 for v_ in sg.values())
                if not feas:
                    v = "冲突"
                elif all(k for _, k in res if k is not None):
                    v = "一致"
                else:
                    v = "不一致"
            top = None
            if dirs:
                m = min(FR.get(r["id"], 1.0) for r in dirs)
                tops = [r for r in dirs if FR.get(r["id"], 1.0) <= m + 1e-9]
                top = {"rules": [r["id"] for r in tops], "ok": all(ok_of(r, s, o) for r in tops)}
            # 推"清 / 不清"(持仓日) 或 "竞价首笔做不做"(土豆) 的那条: 能推出标签的规则里最窄的
            guess = None
            if kind == "pos":
                c = [(FR.get(r["id"], 1.0), DSL.L1[r["act"]]) for r in dirs if r["act"] in DSL.L1]
            else:
                c = [(FR.get(r["id"], 1.0), r.get("sign", 1) > 0) for r in dirs if r.get("dim") == "竞价首笔"]
            if c:
                m = min(x[0] for x in c)
                guess = Counter(x[1] for x in c if x[0] <= m + 1e-9).most_common(1)[0][0]
            out.append({"kind": kind, "date": s["date"], "name": s.get("name"), "real": real_desc(s, kind, sk), "cell": cell_of(s, kind, sk),
                        "verdict": v, "fired": res, "top": top, "guess": guess,
                        "label": (s["act"] == "清") if kind == "pos" else (bool(s.get("auction_any")) if sk in ES.TUDOU else None),
                        "gap": s.get("gap") if kind == "pos" else s.get("bond_auc")})
    return {"samples": out, "rules": rstat, "summary": summarize(out, rstat, sk)}


def summarize(out, rstat, sk):
    main_kind = "day" if sk in ES.TUDOU else "pos"
    res = {"main_kind": main_kind}
    for kind in ("pos", "open", "day", "all"):
        X = [x for x in out if kind == "all" or x["kind"] == kind]
        c = Counter(x["verdict"] for x in X)
        tops = [x for x in X if x["top"]]
        res[kind] = {"n": len(X), "一致": c["一致"], "不一致": c["不一致"], "冲突": c["冲突"], "没覆盖": c["没覆盖"] + c["只有无方向"],
                     "裁决一致": sum(1 for x in tops if x["top"]["ok"]), "有方向覆盖": len(tops)}
    res["误报"] = sum(v["fp"] for v in rstat.values())
    res["反向"] = sum(v["rev"] for v in rstat.values())
    return res


def rate(a, b):
    return None if not b else a / b


def fmt(a, b):
    return "—" if not b else f"{a}/{b}={a / b:.0%}"


# ------------------------------------------------------------------ 基线 ------------------------------------------------------------------
def baselines(S, sk, train_dates, test_dates, ev):
    """M0 = 训练段多数标签; M2 = 今日开盘档查表(股票: 个股开盘缺口; 土豆: 主做债 09:24 档), 格 n<3 退回 M0; 规则 = 裁决那条推出的标签"""
    if sk in ES.TUDOU:
        lab = lambda s: bool(s.get("auction_any"))  # noqa: E731   首笔是不是 09:25 竞价(主做债在训练段常换, 用 auction_main 当标签会失真)
        key = lambda s: OB.bin13_frac(s.get("bond_auc"), kind="cb")  # noqa: E731   转债 ±20% 按比例换算
        key5 = lambda s: gb(s.get("bond_auc"))  # noqa: E731
        tr = [s for s in samples_of(S, "day", train_dates) if s.get("has_main")]
        te = [s for s in samples_of(S, "day", test_dates)]
        name = ("首笔 09:25 竞价", "总是竞价", "总是不竞价", "主做债竞价档")
        X = [x for x in ev["samples"] if x["kind"] == "day"]
    else:
        lab = lambda s: s["act"] == "清"  # noqa: E731
        key = lambda s: OB.bin13_frac(s.get("gap"), s.get("code"))  # noqa: E731   创业板 / 科创板按比例换算
        key5 = lambda s: gb(s.get("gap"))  # noqa: E731
        tr = samples_of(S, "pos", train_dates)
        te = samples_of(S, "pos", test_dates)
        name = ("当天清 / 不清", "总是清", "总是不清", "今日开盘档")
        X = [x for x in ev["samples"] if x["kind"] == "pos"]
    if not tr or not te:
        return {"label": name[0], "n_train": len(tr), "n_test": len(te)}
    base = Counter(lab(s) for s in tr).most_common(1)[0][0]
    tab = OB.fit((key(s), lab(s)) for s in tr)          # 10/26 用户定: 13 档, 格 n<3 并相邻档(open_bins.lookup)
    tab5 = defaultdict(Counter)
    for s in tr:
        tab5[key5(s)][lab(s)] += 1
    m2 = lambda s: OB.lookup(tab, key(s), base)  # noqa: E731
    m2o = lambda s: (tab5[key5(s)].most_common(1)[0][0] if sum(tab5[key5(s)].values()) >= 3 else base)  # noqa: E731
    a0 = sum(lab(s) == base for s in te)
    a2 = sum(lab(s) == m2(s) for s in te)
    a2o = sum(lab(s) == m2o(s) for s in te)
    ar = sum(1 for x in X if x["guess"] is not None and x["guess"] == x["label"])
    cov = sum(1 for x in X if x["guess"] is not None)
    arf = sum(1 for x in X if (x["guess"] if x["guess"] is not None else base) == x["label"])
    return {"label": name[0], "n_train": len(tr), "n_test": len(te), "train_from": min(s["date"] for s in tr), "train_rate": round(sum(map(lab, tr)) / len(tr), 3),
            "M0": {"name": f"M0 默认动作({name[1] if base else name[2]})", "ok": a0, "n": len(te)},
            "M2": {"name": f"M2 {name[3]}查表(13 档)", "ok": a2, "n": len(te)},
            "M2_5": {"name": f"{name[3]}查表(旧 5 档, 和诊断报告同口径, 只作对照)", "ok": a2o, "n": len(te)},
            "rules": {"name": "规则(裁决那条推标签; 没规则算错)", "ok": ar, "n": len(X), "cov": cov},
            "rules_fb": {"name": "规则(没规则时退回 M0)", "ok": arf, "n": len(X)}}


# ------------------------------------------------------------------ 重复犯错 ------------------------------------------------------------------
def repeats(ev, TD, post_only=True):
    nxt = {d: TD[i + 1] for i, d in enumerate(TD[:-1])}
    out = []
    for rid, st in ev["rules"].items():
        W = [w for w in st["wrong"] if w["post"] or not post_only]
        if not W:
            continue
        ds = sorted({w["date"] for w in W})
        cons = [(a, nxt[a]) for a in ds if nxt.get(a) in ds]
        sig = Counter((w["cell"], f"叫{w['said']}") for w in W)
        same = [(k, n) for k, n in sig.items() if n >= 2]
        if cons or same:
            out.append({"rule": rid, "consecutive": cons, "same_error": [{"cell": k[0], "said": k[1], "n": n,
                                                                            "cases": [f"{w['date'][5:]} {w['name']} {w['real']}" for w in W if (w["cell"], f"叫{w['said']}") == k]} for k, n in same]})
    return out


# ------------------------------------------------------------------ 一家跑完 ------------------------------------------------------------------
def exam_skill(sk, end, days, lookback, drop, T=None):
    S = ES.build(sk, end, days, lookback)
    T = T or load_triggers(sk)
    B = births(sk)
    win = [d for d in S["window"]]
    test = [d for d in win if d not in drop]
    train = [d for d in S["days_all"] if d < win[0]]
    FR = spec_rates(T, S, train)
    ev = evaluate(T, S, set(test), FR, B)
    ev_look = evaluate(T, S, set(test), FR, B, include_look=True)
    ev_post = evaluate(T, S, set(test), FR, B, birth_gate=True)
    bl = baselines(S, sk, set(train), set(test), ev)
    bl_look = baselines(S, sk, set(train), set(test), ev_look)
    pool = [dict(r, pool=False) for r in T["rules"] if r.get("pool")]
    ev_pool = evaluate({"rules": pool}, S, set(test), FR, B)["rules"] if pool else {}
    have = sorted({x["date"] for x in ev["samples"]})
    miss = [d for d in test if d not in have]
    res = {"skill": sk, "name": NAMES.get(sk, sk), "end": end, "window": [win[0], win[-1]], "days": days, "drop": sorted(drop), "test_days": len(test),
           "days_with_data": len(have), "missing_days": miss, "last_data": S.get("last_dp"), "n_rules": len(T["rules"]),
           "n_broad": sum(1 for r in T["rules"] if FR.get(r["id"], 0) >= BROAD),
           "n_look": sum(1 for r in T["rules"] if is_look(r)), "spec": FR, "eval": ev, "eval_look": {"summary": ev_look["summary"], "baselines": bl_look},
           "eval_post": {"summary": ev_post["summary"]}, "baselines": bl,
           "repeats": repeats(ev, S["days_all"]), "repeats_all": repeats(ev, S["days_all"], post_only=False), "pool": ev_pool}
    res["n_rules"] = sum(1 for r in T["rules"] if not r.get("pool"))
    return res, S, T


def gate(cur, cand):
    """准入闸四条: 一致率不降(裁决一致 + 整套一致都不降) / 冲突不升 / 误报不升 / 赢过 M0、M2 至少一个"""
    mk = cur["eval"]["summary"]["main_kind"]
    A, Bc = cur["eval"]["summary"], cand["eval"]["summary"]
    reasons, ok = [], True

    def r_(x, k):
        return rate(x[k]["裁决一致"], x[k]["n"]) or 0

    def a_(x):
        return rate(x["all"]["一致"], x["all"]["n"]) or 0
    if r_(Bc, mk) + 1e-9 < r_(A, mk):
        ok = False
        reasons.append(f"裁决后一致率下降 {r_(A, mk):.0%} → {r_(Bc, mk):.0%}")
    if a_(Bc) + 1e-9 < a_(A):
        ok = False
        reasons.append(f"整套一致率下降 {a_(A):.0%} → {a_(Bc):.0%}")
    if Bc["all"]["冲突"] > A["all"]["冲突"]:
        ok = False
        reasons.append(f"冲突上升 {A['all']['冲突']} → {Bc['all']['冲突']}")
    if Bc["误报"] > A["误报"]:
        ok = False
        reasons.append(f"误报上升 {A['误报']} → {Bc['误报']}")
    bl = cand["baselines"]
    if bl.get("rules"):
        rr = bl["rules"]["ok"]
        if not (rr > bl["M0"]["ok"] or rr > bl["M2"]["ok"]):
            ok = False
            reasons.append(f"没赢任何基线: 规则 {rr}/{bl['rules']['n']} vs M0 {bl['M0']['ok']} / M2 {bl['M2']['ok']}")
    return ok, reasons


# ------------------------------------------------------------------ 报告 ------------------------------------------------------------------
def pct_s(a, b):
    return "—" if not b else f"{a / b:.0%}"


def headline(R):
    E = R["eval"]["summary"]
    mk = E["main_kind"]
    bl = R["baselines"]
    L = R["eval_look"]["summary"]
    P = R["eval_post"]["summary"]
    m = E[mk]
    a = E["all"]
    row = [R["name"], f"{R['days_with_data']}/{R['test_days']}" + (f"(缺 {', '.join(d[5:] for d in R['missing_days'])})" if R["missing_days"] else ""),
           f"{R['n_rules']}({R['n_broad']} 宽 / {R['n_look']} 含当日)", f"{'持仓日' if mk == 'pos' else '账户日'} {m['n']}",
           fmt(a["一致"], a["n"]), fmt(m["裁决一致"], m["n"]), str(a["冲突"]), str(a["没覆盖"]), f"{E['误报']} / {E['反向']}"]
    if bl.get("M0"):
        row += [fmt(bl["rules"]["ok"], bl["rules"]["n"]), fmt(bl["M0"]["ok"], bl["M0"]["n"]), fmt(bl["M2"]["ok"], bl["M2"]["n"])]
    else:
        row += ["—", "—", "—"]
    row += [f"{fmt(P[mk]['裁决一致'], P[mk]['有方向覆盖'])}(覆盖 {P[mk]['有方向覆盖']}/{P[mk]['n']})", fmt(L[mk]["裁决一致"], L[mk]["n"])]
    return "| " + " | ".join(row) + " |"


def verdict_line(R):
    bl = R["baselines"]
    if not bl.get("M0"):
        return f"- {R['name']}: 基线样本不足, 不判"
    r, m0, m2 = bl["rules"]["ok"], bl["M0"]["ok"], bl["M2"]["ok"]
    n = bl["rules"]["n"]
    best = max(m0, m2)
    tag = "赢两个基线" if r > best else "只赢一个基线" if r > min(m0, m2) else "打平最好的基线" if r == best else "输给两个基线" if r < min(m0, m2) else "没赢基线"
    return (f"- **{R['name']}**: 规则推「{bl['label']}」{r}/{n}, {bl['M0']['name']} {m0}/{n}, {bl['M2']['name']} {m2}/{n} → **{tag}**"
            f"(规则覆盖 {bl['rules']['cov']}/{n}; 没规则时退回默认 {bl['rules_fb']['ok']}/{n}; 旧 5 档查表 {bl['M2_5']['ok']}/{n}); 训练段 {bl['n_train']} 个样本(自 {bl.get('train_from', '?')}), 训练期标签率 {bl.get('train_rate', 0):.0%}")


def worst_rules(Rs, k=10):
    rows = []
    for R in Rs:
        for rid, st in R["eval"]["rules"].items():
            if st["dir"] >= 3:
                rows.append((st["ok"] / st["dir"], -(st["fp"] + st["rev"]), R, rid, st))
    rows.sort(key=lambda x: (x[0], x[1]))
    return rows[:k]


def conflict_cells(Rs, k=10):
    c = defaultdict(list)
    for R in Rs:
        for x in R["eval"]["samples"]:
            if x["verdict"] == "冲突":
                rules = "+".join(sorted(i for i, v in x["fired"] if v is not None))
                c[(R["name"], x["cell"])].append((x, rules))
    rows = sorted(c.items(), key=lambda kv: -len(kv[1]))[:k]
    return rows


def write_report(Rs, tag, args):
    L = [f"# 导师规则样本外拟人体检 · {tag}(零 token; scripts/skills_ver/rule_exam.py)", ""]
    R0 = Rs[0]
    L.append(f"> 考卷: 最近 {args.days} 个交易日 **{R0['window'][0]} ~ {R0['window'][1]}**" + (f", 去掉 {', '.join(sorted(args.drop))}" if args.drop else "")
             + f"; 训练段(只用于基线和具体度)= 考卷之前 {args.lookback} 个交易日。规则 = 各家 `persona/rule_triggers.json`(rules.md 只读出生日)。")
    L.append("> 判定: **一致** = 命中的给方向规则全对; **不一致** = 有错但能同时成立; **冲突** = 不可能同时成立; **没覆盖** = 没有给方向的规则命中。"
             "**裁决后** = 冲突时听训练段命中率最低(最窄)的那条; 芷影按 rules.md 新版处置路由先取第一档。")
    L.append("> 防偷看: 触发条件用到当日盘中 / 收盘信息的规则标「含当日信息」, **不计入**主口径(最后一列给计入时的数, 只作对照)。"
             "出生后口径 = 每条规则只在它出生日(或 10/25 改写日)之后的样本上参与。")
    L.append("> 置信: 每家考卷只有 12~20 个持仓日 / 账户日, 一个样本 = 5~8 个百分点; 下面的高低只当方向看【低~中】。")
    L.append("")
    L.append("## 〇、结论表")
    L.append("")
    L.append("| 导师 | 有数据天数 | 规则数(宽 / 含当日) | 主样本 | 整套一致率(全部样本) | 裁决后一致率(主样本) | 冲突 | 没覆盖 | 误报 / 反向 | 规则推标签 | M0 默认动作 | M2 开盘档查表 | 出生后口径·裁决一致(只算有出生后规则覆盖的样本) | 含当日信息计入·裁决一致 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for R in Rs:
        L.append(headline(R))
    L.append("")
    L.append("**规则 vs 基线(主样本的二分类标签: 股票导师 = 当天清 / 不清; 土豆 = 首笔是不是 09:25 竞价):**")
    L.append("")
    for R in Rs:
        L.append(verdict_line(R))
    L.append("")
    # 最差 10 条
    L.append("## 一、最差的 10 条规则(考卷内给方向 ≥3 次, 按一致率从低到高)")
    L.append("")
    L.append("| # | 导师 | 规则 | 类 | 叫什么 | 给方向 | 一致率 | 误报 / 反向 | 出生日 | 出生后 一致 | 错例(日期 票 真实动作) |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for i, (rt, _, R, rid, st) in enumerate(worst_rules(Rs), 1):
        ex = "; ".join(f"{w['date'][5:]} {w['name']} {w['real']}" for w in st["wrong"][:3])
        L.append(f"| {i} | {R['name']} | {rid} | {st['kind']} | {st['act']} | {st['dir']} | {rt:.0%} | {st['fp']} / {st['rev']} | {st['birth'] or '未知'} | "
                 f"{fmt(st['post_ok'], st['post_dir'])} | {ex} |")
    L.append("")
    L.append("## 二、冲突最多的情境")
    L.append("")
    cc = conflict_cells(Rs)
    if not cc:
        L.append("考卷内没有冲突样本。")
    else:
        L.append("| 导师 | 情境格 | 冲突样本数 | 打架的规则(命中组合) | 样本 |")
        L.append("|---|---|---|---|---|")
        for (nm, cell), xs in cc:
            combos = Counter(r for _, r in xs).most_common(2)
            L.append(f"| {nm} | {cell} | {len(xs)} | {'; '.join(f'{c}×{n}' for c, n in combos)} | {'; '.join(x[0]['date'][5:] + ' ' + str(x[0]['name']) + ' ' + x[0]['real'] for x in xs[:4])} |")
    L.append("")
    L.append("## 三、重复犯错(出生后; 连续两个交易日判错, 或同一情境格 × 同一错误方向 ≥2 次)")
    L.append("")
    red = [(R, x) for R in Rs for x in R["repeats"]]
    if not red:
        L.append("出生后没有重复犯错(多数规则出生后样本还很少, 见第四节)。")
    else:
        L.append("| 导师 | 规则 | 连续两天判错 | 同一种错 ≥2 次 |")
        L.append("|---|---|---|---|")
        for R, x in red:
            cons = ", ".join(f"{a[5:]}→{b[5:]}" for a, b in x["consecutive"]) or "—"
            same = "; ".join(f"【红】{s['cell']} {s['said']} ×{s['n']}({' / '.join(s['cases'][:3])})" for s in x["same_error"]) or "—"
            L.append(f"| {R['name']} | **{x['rule']}** | {cons} | {same} |")
    L.append("")
    allr = [(R, x) for R in Rs for x in R["repeats_all"] if not any(y["rule"] == x["rule"] for y in R["repeats"])]
    if allr:
        L.append("参考(含出生前样本, 不标红; 这些错在规则写成时就已经发生过):")
        L.append("")
        for R, x in allr[:15]:
            cons = ", ".join(f"{a[5:]}→{b[5:]}" for a, b in x["consecutive"][:3])
            same = "; ".join(f"{s['cell']} {s['said']} ×{s['n']}" for s in x["same_error"][:2])
            L.append(f"- {R['name']} {x['rule']}: " + " / ".join(t for t in (f"连续 {cons}" if cons else "", f"同错 {same}" if same else "") if t))
        L.append("")
    L.append("> 说明: rule_suspects.md 由 scripts/ontology/rule_health.py 每晚整份重写, 本脚本不往那里追加(会被覆盖), 重复犯错只在本节列。")
    L.append("")
    L.append("## 四、待核销(出生后考卷样本 <3, 不出结论)")
    L.append("")
    for R in Rs:
        pend = [(rid, st) for rid, st in R["eval"]["rules"].items() if st["post_dir"] < MIN_POST and not st["look"]]
        unk = [rid for rid, st in R["eval"]["rules"].items() if not st["birth"]]
        L.append(f"- **{R['name']}**(共 {len(R['eval']['rules'])} 条): 待核销 {len(pend)} 条 — "
                 + ", ".join(f"{rid}(出生 {st['birth'][5:] if st['birth'] else '?'}, 出生后 {st['post_dir']})" for rid, st in pend)
                 + (f"; 出生日未知: {', '.join(unk)}" if unk else ""))
    L.append("")
    pools = [(R, rid, st) for R in Rs for rid, st in (R.get("pool") or {}).items()]
    if pools:
        L.append("### 观察池(没过准入闸, 不计入整套; 单条在考卷上的表现)")
        L.append("")
        L.append("| 导师 | 规则 | 叫什么 | 命中 | 给方向 | 一致率 | 误报 / 反向 | 出生后 一致 |")
        L.append("|---|---|---|---|---|---|---|---|")
        for R, rid, st in pools:
            L.append(f"| {R['name']} | {rid} | {st['act']} | {st['fire']} | {st['dir']} | {pct_s(st['ok'], st['dir'])} | {st['fp']} / {st['rev']} | {fmt(st['post_ok'], st['post_dir'])} |")
        L.append("")
    L.append("## 五、含当日信息的规则(不计入主口径)")
    L.append("")
    for R in Rs:
        T = load_triggers(R["skill"]) if not R.get("_T") else R["_T"]
        lk = [f"{r['id']}({', '.join(DSL.look_fields(r)) or '人工标'})" for r in T["rules"] if is_look(r)]
        L.append(f"- {R['name']}: " + ("; ".join(lk) if lk else "无"))
    L.append("")
    L.append("## 六、逐家规则级明细(考卷内; 出生后另列)")
    for R in Rs:
        L.append("")
        L.append(f"### {R['name']}(窗口 {R['window'][0]}~{R['window'][1]}, 有数据 {R['days_with_data']} 天, 最后一天 {R['last_data']})")
        L.append("")
        S = R["eval"]["summary"]
        for k, nm in (("pos", "持仓日"), ("open", "新开仓"), ("day", "账户日")):
            x = S[k]
            if x["n"]:
                L.append(f"- {nm} {x['n']}: 一致 {x['一致']} / 不一致 {x['不一致']} / 冲突 {x['冲突']} / 没覆盖 {x['没覆盖']}; 裁决后一致 {fmt(x['裁决一致'], x['n'])}")
        L.append("")
        L.append("| 规则 | 类 | 叫什么 | 训练段命中率 | 宽 | 考卷命中 | 给方向 | 一致率 | 误报 | 反向 | 出生日 | 出生后 一致 | 出生后 误报 / 反向 | 状态 |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for rid, st in R["eval"]["rules"].items():
            sp = R["spec"].get(rid, 0)
            state = "含当日信息·不计" if st["look"] else ("待核销" if st["post_dir"] < MIN_POST else ("出生后一致率 <50%" if st["post_ok"] / st["post_dir"] < 0.5 else "出生后通过"))
            L.append(f"| {rid} | {st['kind']} | {st['act']} | {sp:.0%} | {'是' if sp >= BROAD else ''} | {st['fire']} | {st['dir']} | {pct_s(st['ok'], st['dir'])} | {st['fp']} | {st['rev']} | "
                     f"{st['birth'] or '未知'} | {fmt(st['post_ok'], st['post_dir'])} | {st['post_fp']} / {st['post_rev']} | {state} |")
    L.append("")
    L.append("## 七、口径与不自信点")
    L.append("")
    L += [
        "1. 触发条件是人工从诊断脚本的谓词表翻译成 DSL 的(rule_triggers.json 每条 note 写了编码口径); 换一种编法单条一致率会变 ±10pp, 整套结论(冲突多 / 不胜基线)对编法不太敏感。【中】",
        "2. 「裁决后」是对 chain 取舍的近似(听训练段命中率最低的那条); 真实 chain 是 LLM 读 rules_brief 简表, 不一定这么取舍。【中】",
        "3. 动作标签来自收盘仓位差(8pp 门槛)+ 成交腿; 「做T」和「加 / 减」、「减到 3% 残仓」算减还是清, 会影响个别样本。【低】",
        "4. 基线训练段 = 考卷之前的样本, 规则却是用全历史(含考卷)写的 → 规则一方占了样本内便宜, 即使这样规则仍不胜基线时结论更硬。",
        "5. 土豆 10/12 前没有 09:24 虚拟撮合, 用最终开盘价近似(R27 / R28 原文也是这么分组的); 他的主做债按前 10 个交易日成交腿最多的转债机械判。",
        "6. 出生日取 rules.md「时间状态: 建立」, 10/25 改过方向 / 适用面的规则取 JSON 的 modified(更晚者); 子规则(如 R2-持)用母规则 R2 的出生日。",
    ]
    f = ROOT / "docs/review" / f"rule_exam_{tag}.md"
    if f.exists():   # 同一天再跑(例: 凌晨首跑考到 10-23, 晚上 check_md 考到当天): 考卷末日不同 → 旧版挪进 results 存档, 不丢
        m = re.search(r"~ (\d{4}-\d{2}-\d{2})\*\*", f.read_text(encoding="utf-8")[:2000])
        if m and m.group(1) != R0["window"][1]:
            arc = ROOT / "results/skill_exam" / tag / f"rule_exam_{tag}_end{m.group(1).replace('-', '')}.md"
            arc.parent.mkdir(parents=True, exist_ok=True)
            arc.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    f.write_text("\n".join(L) + "\n", encoding="utf-8")
    return f


def write_candidate_report(sk, cur, cand, changed, ok, reasons, tag, drop_res):
    nm = NAMES.get(sk, sk)
    L = [f"# 规则准入闸 · {nm} · {tag}", "", f"候选变动: {', '.join(changed) or '无'}", ""]
    L.append("| 口径 | 现行 | 候选 |")
    L.append("|---|---|---|")
    mk = cur["eval"]["summary"]["main_kind"]
    for lab, f_ in (("整套一致率", lambda R: fmt(R["eval"]["summary"]["all"]["一致"], R["eval"]["summary"]["all"]["n"])),
                    ("裁决后一致率", lambda R: fmt(R["eval"]["summary"][mk]["裁决一致"], R["eval"]["summary"][mk]["n"])),
                    ("冲突", lambda R: str(R["eval"]["summary"]["all"]["冲突"])),
                    ("误报 / 反向", lambda R: f"{R['eval']['summary']['误报']} / {R['eval']['summary']['反向']}"),
                    ("规则推标签", lambda R: fmt(R["baselines"]["rules"]["ok"], R["baselines"]["rules"]["n"]) if R["baselines"].get("rules") else "—"),
                    ("M0 / M2", lambda R: f"{R['baselines']['M0']['ok']} / {R['baselines']['M2']['ok']}" if R["baselines"].get("M0") else "—")):
        L.append(f"| {lab} | {f_(cur)} | {f_(cand)} |")
    if drop_res:
        c2, k2 = drop_res
        L.append(f"| 去掉触发日后 裁决后一致率 | {fmt(c2['eval']['summary'][mk]['裁决一致'], c2['eval']['summary'][mk]['n'])} | {fmt(k2['eval']['summary'][mk]['裁决一致'], k2['eval']['summary'][mk]['n'])} |")
    L.append("")
    L.append(f"**结论: {'通过 → 可写进 rules.md 主体' if ok else '不通过 → 进观察池(rules.md 末尾「观察池」节, chain 不读)'}**")
    for r in reasons:
        L.append(f"- {r}")
    L.append("")
    L.append("候选里变动规则的考卷表现:")
    for rid in changed:
        st = cand["eval"]["rules"].get(rid.lstrip("-"))
        if st:
            L.append(f"- {rid}: 命中 {st['fire']} / 给方向 {st['dir']} / 一致 {pct_s(st['ok'], st['dir'])} / 误报 {st['fp']} / 反向 {st['rev']}(考卷全在出生前 = 样本内, 只证明不打架, 不证明对)")
    f = ROOT / "docs/review" / f"rule_exam_candidate_{tag}_{sk}.md"
    f.write_text("\n".join(L) + "\n", encoding="utf-8")
    return f


def strip(R):
    """落 JSON 前去掉大字段里不可序列化 / 冗余的部分"""
    R = dict(R)
    R.pop("_T", None)
    return R


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument("--lookback", type=int, default=160)
    ap.add_argument("--end", help="考卷最后一天(默认 = 今天及以前最后一个交易日)")
    ap.add_argument("--drop", default="", help="去掉这些天再算(逗号分隔), 用来看'去掉出生期 / 触发日'后的指标")
    ap.add_argument("--candidate", help="候选 rule_triggers.json / 补丁 json / 含 ```json 触发块的 md")
    ap.add_argument("--trigger-dates", default="", help="候选规则是照哪几天写的(逗号分隔); 准入报告另给去掉这几天后的数")
    ap.add_argument("--tag", help="产物日期标签(默认今天 YYYYMMDD)")
    ap.add_argument("--write-specific", action="store_true", help="把考卷 + 训练段全部样本上的命中率回写 rule_triggers.json 的 specific / broad")
    a = ap.parse_args()
    a.drop = {x.strip() for x in a.drop.split(",") if x.strip()}
    tag = a.tag or dt.date.today().strftime("%Y%m%d")
    end = a.end or ES.last_trade_day()
    outdir = ROOT / "results/skill_exam" / tag
    outdir.mkdir(parents=True, exist_ok=True)
    sks = [s.strip() for s in a.skill.split(",") if s.strip()]
    if a.candidate:
        sk = sks[0]
        base = load_triggers(sk)
        T2, changed = apply_candidate(base, a.candidate)
        cur, S, _ = exam_skill(sk, end, a.days, a.lookback, a.drop, base)
        cand, _, _ = exam_skill(sk, end, a.days, a.lookback, a.drop, T2)
        ok, reasons = gate(cur, cand)
        td = {x.strip() for x in a.trigger_dates.split(",") if x.strip()}
        drop_res = None
        if td:
            drop_res = (exam_skill(sk, end, a.days, a.lookback, a.drop | td, base)[0], exam_skill(sk, end, a.days, a.lookback, a.drop | td, T2)[0])
        f = write_candidate_report(sk, cur, cand, changed, ok, reasons, tag, drop_res)
        (outdir / f"candidate_{sk}.json").write_text(json.dumps({"skill": sk, "changed": changed, "pass": ok, "reasons": reasons,
                                                                 "current": cur["eval"]["summary"], "candidate": cand["eval"]["summary"],
                                                                 "baselines_cur": cur["baselines"], "baselines_cand": cand["baselines"]}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(("通过" if ok else "进观察池") + (": " + "; ".join(reasons) if reasons else ""))
        print("报告:", f.relative_to(ROOT))
        sys.exit(0 if ok else 2)
    Rs, failed = [], []
    for sk in sks:
        try:
            R, S, T = exam_skill(sk, end, a.days, a.lookback, a.drop)
        except Exception as e:  # noqa: BLE001   一家失败不拖垮其他家; 结尾非 0 退出让夜间流程记失败
            import traceback
            traceback.print_exc()
            print(f"[{sk}] 失败: {type(e).__name__}: {e}")
            failed.append(sk)
            continue
        if a.write_specific:
            allS = set(S["days_all"])
            FR = spec_rates(T, S, allS)
            raw = json.loads(trig_path(sk).read_text(encoding="utf-8"))
            for r in raw["rules"]:
                r["specific"] = FR.get(r["id"])
                if FR.get(r["id"], 0) >= BROAD:
                    r["broad"] = True
                else:
                    r.pop("broad", None)
            trig_path(sk).write_text(dump_triggers(raw), encoding="utf-8")
            print(f"[{sk}] specific / broad 已回写 {sum(1 for r in raw['rules'] if r.get('broad'))} 条宽规则")
        R["_T"] = T
        Rs.append(R)
        (outdir / f"{sk}.json").write_text(json.dumps(strip(R), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        E = R["eval"]["summary"]
        mk = E["main_kind"]
        bl = R["baselines"]
        print(f"[{sk}] {R['window'][0]}~{R['window'][1]} 有数据 {R['days_with_data']} 天 | 整套一致 {fmt(E['all']['一致'], E['all']['n'])} | 裁决后 {fmt(E[mk]['裁决一致'], E[mk]['n'])} | "
              f"冲突 {E['all']['冲突']} | 误报 {E['误报']} 反向 {E['反向']} | 规则 {bl.get('rules', {}).get('ok')} M0 {bl.get('M0', {}).get('ok')} M2 {bl.get('M2', {}).get('ok')} / {bl.get('n_test')}")
    if Rs:
        f = write_report(Rs, tag, a)
        print("报告:", f.relative_to(ROOT))
    if failed or not Rs:
        print("失败:", ", ".join(failed) or "没有一家跑成")
        sys.exit(1)


if __name__ == "__main__":
    main()
