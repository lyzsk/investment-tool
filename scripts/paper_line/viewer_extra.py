# -*- coding: utf-8 -*-
"""viewer_extra.py — viewer.py 的附加计算(10/24 用户令 B 版; 零 token、只读)
① 每张挂单的结局: 直接调 replay_report.order_audit(它本来就收账本目录, 指到 results/_live 即可)取"成没成交 + 原因", 再补"被下一版替换 / 之后走势"
② 排队等待 vs 计算: 事件发生(重定 / 重定排队) → 排队叫醒(进名额队列) → timing.start(链开始)
③ 每分钟 token: 每一步按 开始时刻 + 耗时 摊到分钟(另给"按发出那一分钟全算"口径), 对照 K3 TPM 上限
④ 导师真人对照: replay_report.mentor_day + viewer 的逐笔
⑤ 缓存保温体检: 每次保温的花费、距上次调用多久、缓存是不是已经过期
⑥ 瘦身计算器的默认值(从当天实测取)
"""
import bisect
import html
import re
import statistics
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent)]
import replay_report as rr   # noqa: E402

# 分钟轴 = 09:00~11:29 + 13:00~14:59(盘前 30 分钟也算: 11 本的启动链都挤在 09:00)
AXIS = [f"{m // 60:02d}:{m % 60:02d}" for m in [*range(540, 690), *range(780, 900)]]
AIDX = {t: i for i, t in enumerate(AXIS)}
KEEP_DESIGN_USD = 0.2   # 保温设计花费上限($0.1~0.2)
sec, hms = rr.sec, rr.hms


def tidx(hm):
    """HH:MM → 交易分钟序号(09:30=0, 11:30=120, 13:00=120, 15:00=240; 盘前算 0)"""
    h, m = int(hm[:2]), int(hm[3:5])
    x = h * 60 + m - 570
    if h >= 13:
        x -= 90
    return max(0, min(240, x if x <= 120 or h >= 13 else 120))


def idx2hm(i):
    m = 570 + i if i <= 120 else 780 + i - 120
    return f"{m // 60:02d}:{m % 60:02d}"


def price_at(code, t, tape, bars):
    """t(HH:MM:SS)那一刻的价: 先用 3 秒盘口, 没有再用 1 分钟 K 线收盘"""
    tp = tape.get(code) or []
    i = bisect.bisect_right(tp, (t, 9e9))
    if i:
        return tp[i - 1][1]
    bs = [b for b in bars.get(code) or [] if b[0] <= t[:5]]
    return bs[-1][1] if bs else None


def cat_of(why):
    if why.strip().endswith("✅ 成交") or why.strip() == "成交":   # 注意别用"包含成交"判: "没成交 / 前置单没成交"也含这两个字
        return "成交"
    for pat, c in (("草稿版", "草稿没挂"), ("炸板接单", "炸板接没触发"), ("数据缺口", "数据缺口"), ("没有盘口数据", "没数据"),
                   ("前置单", "前置单没成交"), ("排队量没排到", "排队没轮到"), ("封死", "封死买不进"), ("价格没", "价格没到"), ("要细查", "到过价没成交(细查)")):
        if pat in why:
            return c
    return "其他"


def order_fates(bdir, B, tape, bars):
    """给 B["versions"][*]["orders"][*] 加 fate 字段; 返回 [对不上的说明]"""
    h = rr.order_audit(bdir, tape, B["trades"])
    heads = re.findall(r"<details><summary>(\S+) · .*? · 有效 (\d\d:\d\d)~(\d\d:\d\d) · 挂单 (\d+) 张</summary>", h)
    rows = [html.unescape(r[3]) for r in re.findall(r"<tr><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td></tr>", h)]
    assert sum(int(x[3]) for x in heads) == len(rows), f"{bdir.name}: order_audit 行数对不上"
    strs = {int(p.name[:2]): p for p in (bdir / "strategies").glob("*.json") if p.name[:2].isdigit()}
    rules_of = {}
    for vname, *_ in heads:
        k = int(vname[:2]) if vname[:2].isdigit() else None
        S = (rr.jl(strs[k], {}) or {}) if k in strs else {}
        rules_of[vname] = ([(x["code"], r) for x in (S.get("strategy") or {}).get("codes") or [] for r in x.get("rules") or []], S.get("dropped") or [])
    audit, i = {}, 0
    for vname, t0, nxt, n in heads:
        assert len(rules_of[vname][0]) == int(n), f"{bdir.name} {vname}: 策略规则数和 order_audit 对不上"
        for c, r in rules_of[vname][0]:
            audit[(vname, c, r["id"])] = (rows[i], t0, nxt)
            i += 1
    names = [v["dir"] for v in B["versions"]]
    probs = []
    for j, v in enumerate(B["versions"]):
        nxt_rules = {(c, r.get("side"), r.get("px")) for c, r in rules_of.get(names[j + 1], ([], []))[0]} if j + 1 < len(names) else set()
        for o in v["orders"]:
            a = audit.get((v["dir"], o.get("code"), o.get("id")))
            if not a:
                dr = rules_of.get(v["dir"], ([], []))[1]
                mine = [x for x in dr if str(x).startswith(f"{o.get('code')} {o.get('id')} ")] or dr
                o["fate"] = {"cat": "执行器剔除", "why": "06 写了但执行器没收(不在 strategies/ 生效策略里): " + ("; ".join(mine)[:200] or "没写原因"), "win": ""}
                probs.append(f"{B['id']} {v['dir']} {o.get('code')} {o.get('id')}{' after=' + str(o.get('after')) if o.get('after') else ''} 被执行器剔除: {'; '.join(mine)[:80]}")
                continue
            why, t0, nxt = a
            f = {"cat": cat_of(why), "why": why, "win": f"{t0}~{nxt}"}
            px, c = o.get("px"), o.get("code")
            reach = lambda s_: s_[1] <= px if o.get("side") == "BUY" else s_[1] >= px   # noqa: E731
            if f["cat"] == "到过价没成交(细查)" and v.get("start") and isinstance(px, (int, float)):
                # order_audit 的有效期按分钟取整(策略文件名 HHMM); live 有 timing → 精确生效 = start + total。到价全在生效前 = 链慢了没赶上, 不是执行器问题
                te = hms(sec(v["start"]) + round(v.get("total") or 0))
                pre = [s_ for s_ in tape.get(c, []) if t0 + ":00" <= s_[0] < te and reach(s_)]
                post = [s_ for s_ in tape.get(c, []) if te <= s_[0] < nxt + ":00" and reach(s_)]
                if pre and not post:
                    f["cat"] = "生效前已到价(链慢了)"
                    f["why"] = f"{pre[0][0]} 就到过 {px}(极值 {(min if o.get('side') == 'BUY' else max)(x[1] for x in pre)}), 但这一版 {te} 才出结果、生效后再没到价 —— order_audit 按整分钟算有效期会误报'到过价没成交'"
            if f["cat"] != "成交" and nxt < "15:00":
                if (c, o.get("side"), px) in nxt_rules:
                    f["repl"] = f"{nxt} 下一版沿用同价"
                else:
                    f["repl"] = f"{nxt} 被下一版替换"
                    seg = [s_ for s_ in tape.get(c, []) if s_[0] >= nxt + ":00"] if isinstance(px, (int, float)) and f["cat"] in ("价格没到", "排队没轮到") else []   # 草稿 / 前置单没成交的本来就不会成, 不算"替换吃亏"
                    hit = next((s_ for s_ in seg if reach(s_)), None)
                    if hit:
                        f["repl"] += f"; 替换后 {hit[0]} 价格到过 {px}(不撤会成)"
                        if f["cat"] == "价格没到":
                            f["cat"] = "被替换(之后到价)"
            if isinstance(px, (int, float)) and px:
                p30 = price_at(c, idx2hm(min(240, tidx(t0) + 30)) + ":00", tape, bars)
                pc = price_at(c, "15:00:00", tape, bars)
                f["t30"] = idx2hm(min(240, tidx(t0) + 30))
                f["d30"] = round((p30 / px - 1) * 100, 2) if p30 else None
                f["dc"] = round((pc / px - 1) * 100, 2) if pc else None
            o["fate"] = f
    return probs


def queue_waits(B, ev):
    """每版: 事件发生 ev → 进名额队列 qt → 链开始 start; hold = 本账上一轮还在算(重定排队)等的, gate = 等全局名额的"""
    q = sorted(e["t"] for e in ev if e.get("kind") == "排队叫醒")
    rq = sorted(e["t"] for e in ev if e.get("kind") == "重定排队")
    probs, prev, used = [], "00:00:00", set()
    for v in B["versions"]:
        S = v.get("start") or v["trig"]
        k = bisect.bisect_right(q, S)
        qt = q[k - 1] if k else S
        evt, src = qt, "重定"
        if str(v.get("why") or "").startswith("(排队补叫)"):
            cand = [t for t in rq if prev <= t <= qt and t not in used]
            if cand:
                evt, src = cand[0], "重定排队"
                used.add(cand[0])
            else:
                src = "补叫但没找到重定排队记录"
                probs.append(f"{B['id']} {v['dir']} 是排队补叫, 但 events 里没找到对应的重定排队")
        v["q"] = {"ev": evt, "qt": qt, "src": src, "hold": sec(qt) - sec(evt), "gate": sec(S) - sec(qt), "wait": sec(S) - sec(evt)}
        prev = S
    lost = [t for t in rq if t not in used]
    probs += [f"{B['id']} {t} 重定排队后没有对应的补叫版本(被吞 / 被合并 / 停触发)" for t in lost]
    return probs


def ctx(s):
    return sum((s.get(k) or 0) for k in ("cr", "cw", "in"))


def calls(B):
    """这本账全天每次模型调用: (开始秒, 耗时, token, 是否估); 步骤串行累加, 03 多空两个并行; 03 没 token 明细 → 按同版 04 的上下文估"""
    out = []
    for v in B["versions"]:
        t = sec(v.get("start") or v["trig"])
        c04 = next((ctx(s) + (s.get("out") or 0) for s in v["steps"] if s["name"] == "04"), 0)
        par = 0
        for s in v["steps"]:
            d = float(s.get("secs") or 0)
            if s["name"] in ("03_bull", "03_bear"):
                out.append((t, d, c04, True))
                par = max(par, d)
                continue
            t += par
            par = 0
            out.append((t, d, ctx(s) + (s.get("out") or 0), False))
            t += d
    for k in B["keep"]:
        d = float(k.get("secs") or 0)
        out.append((sec(k["t"]) - d, d, (k.get("cr") or 0) + (k.get("cw") or 0), False))
    return out


def tpm(books):
    """{spread|start: {all|<线>: {tok:[], est:[]}}, spill:{}, rpm, conc}"""
    res = {"axis": AXIS, "spread": {}, "start": {}, "spill": {"spread": 0, "start": 0}, "total": 0}
    starts = [0] * len(AXIS)
    edges = []
    for b in [None, *books]:
        for mode in ("spread", "start"):
            res[mode][b["id"] if b else "all"] = {"tok": [0.0] * len(AXIS), "est": [0.0] * len(AXIS)}
    for b in books:
        for s, d, tk, est in calls(b):
            res["total"] += tk
            m0 = AIDX.get(hms(s)[:5])
            if m0 is not None:
                starts[m0] += 1
            edges += [(s, 1), (s + d, -1)]
            for mode in ("spread", "start"):
                parts = [(hms(s)[:5], tk)]
                if mode == "spread" and d > 0:
                    parts, x = [], s
                    while x < s + d:
                        y = min(s + d, (int(x) // 60 + 1) * 60)
                        parts.append((hms(x)[:5], tk * (y - x) / d))
                        x = y
                for hm, part in parts:
                    i = AIDX.get(hm)
                    if i is None:
                        res["spill"][mode] += part
                        continue
                    for key in ("all", b["id"]):
                        res[mode][key]["est" if est else "tok"][i] += part
    for mode in ("spread", "start"):
        for v in res[mode].values():
            v["tok"] = [round(x) for x in v["tok"]]
            v["est"] = [round(x) for x in v["est"]]
        res["spill"][mode] = round(res["spill"][mode])
    conc = mx = 0
    at = ""
    for t, dlt in sorted(edges, key=lambda e: (e[0], e[1])):
        conc += dlt
        if conc > mx:
            mx, at = conc, hms(t)
    res["rpm"] = {"max": max(starts), "at": AXIS[starts.index(max(starts))], "arr": starts}
    res["conc"] = {"max": mx, "at": at}
    return res


def mentor_block(B, M, D):
    if B.get("kind") != "mimic":
        return None
    txt = rr.mentor_day(B["id"], D)
    m = re.search(r"收盘持仓快照[^:：]*[:：]\s*(.*)", txt or "")
    close = m.group(1).strip() if m else "(取不到)"
    mt = M.get(B["skill"]) or []
    mc = {x[1]: x[2] for x in mt}
    bc = {t["code"]: t.get("name") for t in B["trades"]}
    oc = {o["code"]: o.get("name") for v in B["versions"] for o in v["orders"] if o.get("code")}
    hold_m = set(re.findall(r"\((\d{6})\)", close))
    same, ordered, hold = set(mc) & set(bc), (set(mc) & set(oc)) - set(bc), hold_m & set(B["positions"])
    nm = lambda cs, d: "、".join(f"{d.get(c) or ''}{c}" for c in sorted(cs)) or "无"   # noqa: E731
    if not mt:
        s = "导师当天没出手; " + (f"本账成交 {len(B['trades'])} 笔({nm(set(bc), bc)}) → 和导师'不动'不一致" if B["trades"] else "本账也没成交 → 一致(都不动)")
    else:
        s = (f"导师做了 {len(mc)} 只({nm(set(mc), mc)}, {len(mt)} 笔); 本账成交 {len(bc)} 只({nm(set(bc), bc)}) → "
             + (f"做了同一只: {nm(same, mc)}" if same else "没有做同一只") + (f"; 挂过单没成交的导师票: {nm(ordered, mc)}" if ordered else "")
             + (f"; 收盘同持: {nm(hold, mc)}" if hold else ""))
    return {"text": txt, "close": close, "verdict": s, "same": sorted(same)}


def keep_check(B, ratio):
    """每次保温: 距本账上次调用多久、缓存是否已过期、花费是否超设计; 返回 [问题]"""
    asks = sorted([(sec(v.get("start") or v["trig"]), sec(v.get("start") or v["trig"]) + float(v.get("total") or 0)) for v in B["versions"]]
                  + [(sec(k["t"]) - float(k.get("secs") or 0), sec(k["t"])) for k in B["keep"]])
    probs = []
    for k in B["keep"]:
        s0 = sec(k["t"]) - float(k.get("secs") or 0)
        prev = max((e for s, e in asks if e <= s0 + 1 and s < s0 - 1), default=None)
        k["idle"] = round((s0 - prev) / 60, 1) if prev is not None else None
        k["start"] = hms(s0)
        k3t = k.get("k3") or 0
        k["gap"] = bool(k.get("usd") and k["usd"] * ratio > 2 * k3t + 0.5)   # token 明细不全(executor 保温只记缓存读写, 没记未缓存输入)
        if k["gap"]:
            k["k3"], k["est"] = k["usd"] * ratio, True
        k["bad"] = bool((k.get("cw") or 0) >= 100000 or (k.get("usd") or 0) > KEEP_DESIGN_USD * 2)
        k["note"] = ("没成功(超时)" if not k.get("usd") and not k.get("cr") and not k.get("cw") else
                     "缓存已过期 → 保温本身把整段上下文重写了一遍" if (k.get("cw") or 0) >= 100000 else
                     "缓存没命中: 缓存读写都很小却花了钱 → 整段按未缓存输入计费(executor 保温没记 input_tokens, K3¥ 按比例估)" if k["gap"] else "正常续期")
        if k["bad"]:
            probs.append(f"{B['id']} {k['t']} 保温 ${k.get('usd')} (缓存写 {k.get('cw')}, 距上次调用 {k['idle']} 分钟) {k['note']}")
    return probs


def calc_defaults(books):
    st = [s for b in books for v in b["versions"] for s in v["steps"] if s.get("cr") is not None and s["name"] in ("04", "05", "06")]
    cx = [ctx(s) for s in st]
    cr, tot = sum(s.get("cr") or 0 for s in st), sum(cx)
    watch = [len(b["versions"]) for b in books if b.get("mode") == "watch"]
    per_v = [len(v["steps"]) for b in books for v in b["versions"]]   # 每次触发几次模型调用(03 多空算 2 次)
    return {"now": {"R": int(statistics.median(cx)) if cx else 300000, "Q": 0, "O": int(sum(s.get("out") or 0 for s in st) / max(1, len(st))),
                    "N": round(sum(watch) / max(1, len(watch))), "S": round(sum(per_v) / max(1, len(per_v)), 1), "H": round(cr / max(1, tot), 2)},
            "slim": {"R": 40000, "Q": 10000, "O": 2000, "N": round(sum(watch) / max(1, len(watch))), "S": 1, "H": 0.8}}
