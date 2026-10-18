# -*- coding: utf-8 -*-
"""rule_tags.py — 言行一致性第二期: 旧规则补"方向/机械触发"标注 + 驱动器检查(TODO 三-3 ②③, 10/17 ② agent; 零 token, 只读 rules.md)

① 标注(--build): 读 skills/<导师>-skill/persona/rules.md 的规则节(### R<n> / #### R<n>):
   - 已有「- **方向**:」「- **机械触发**:」两行(10/16 深度蒸馏新规则) → 原样采用(src=蒸馏标注)
   - 没有的旧规则 → 机械补标(src=机械补标): 方向按标题+「规则」行关键词(买/卖/持有/双向); 机械触发只认能从本链账本+快照判定的模板:
       overnight_sell  隔夜仓次日早盘卖(标题/规则含 T+1|次日|隔夜 且 含 卖|兑现|清): 昨日新买、今日仍持有 → 今日 0915 应有卖单
       stop_loss(X%)   止损线(含 止损 且 有 "−X%"/"亏 X%" 数字): 持仓浮亏 ≤ −X% → 应有卖单
     其余 = 话术级(不进漏用检查, 只进方向检查)
   产物 scripts/dfcf/paper/rule_tags/<导师>.json + 汇总表(不改 rules.md: persona 归 ③/主会话; 要回写 rules.md 的两行由主会话决定)
② 检查(驱动器 quality_hooks, 开关 CHAIN_RULE_CHECK 默认 0):
   - 方向相符: 06 action.rules 引用的规则方向=买 却挂卖单 / 方向=卖 却挂买单 → 回炉一次
   - 漏用: 机械触发规则已触发(上面两类), 06 既没对该票下卖单, 也没在 holds/no_trade_reason 里写到该票或该规则 → 回炉一次
CLI(scripts/venv/Scripts/python.exe -X utf8): rule_tags.py --build | --show [--skill x] | --selftest
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SKILLS = ROOT / "skills"
OUT = HERE / "rule_tags"
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import mentors  # noqa: E402  10/17 二B-4: 导师登记表
TZZB = [x for x in mentors.ids("tzzb") if x != "buchitudou0"] + ["buchitudou0"]   # 土豆排末(原顺序)
HEAD = re.compile(r"^#{3,4}\s+(R\d+)\s+(.+?)\s*$", re.M)
BUY_W = re.compile(r"买|吸|建仓|入场|加仓|排板|打板|接回|低吸|追涨|开仓|上车|抢筹")
SELL_W = re.compile(r"卖|兑现|清仓|清隔夜|止损|止盈|减仓|出场|派发|离场|砍")
HOLD_W = re.compile(r"不空仓|满仓|持有|拿着|不动|不降仓|停车场|空仓")
DIR_LINE = re.compile(r"^- \*\*方向\*\*[:：]\s*(.+)$", re.M)
MECH_LINE = re.compile(r"^- \*\*机械触发\*\*[:：]\s*(.+)$", re.M)
RULE_LINE = re.compile(r"^- \*\*规则\*\*[:：]\s*(.+)$", re.M)
STOP = re.compile(r"止损[^\n]{0,30}?[-−－]\s*(\d+(?:\.\d+)?)\s*%|亏[损]?\s*(\d+(?:\.\d+)?)\s*%[^\n]{0,8}(?:止损|卖|走)")


def _jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def norm_dir(s):
    s = str(s or "")
    b, se = bool(BUY_W.search(s)), bool(SELL_W.search(s))
    if b and se:
        return "双向"
    if b:
        return "买"
    if se:
        return "卖"
    if HOLD_W.search(s):
        return "持有"
    return None


def parse_rules(text):
    """→ [{id, title, body}]; 同 id 多次出现取第一节(规则区在前, 核销/速览区在后)"""
    hs = list(HEAD.finditer(text))
    out, seen = [], set()
    for i, m in enumerate(hs):
        rid = m.group(1)
        if rid in seen or "<n>" in m.group(0):
            continue
        end = hs[i + 1].start() if i + 1 < len(hs) else len(text)
        nxt = re.search(r"^#{1,2}\s", text[m.end():end], re.M)
        body = text[m.end(): m.end() + nxt.start()] if nxt else text[m.end():end]
        seen.add(rid)
        out.append({"id": rid, "title": m.group(2), "body": body})
    return out


def tag_rule(r):
    title, body = r["title"], r["body"]
    dl, ml, rl = DIR_LINE.search(body), MECH_LINE.search(body), RULE_LINE.search(body)
    rule_txt = rl.group(1) if rl else ""
    tag = {"id": r["id"], "title": re.sub(r"\s*(\[[^\]]*\]|【[^】]*】|（[^）]*）|\(程序化嫌疑\))", "", title).strip()[:60], "level_tag": (re.search(r"\[(可跟|画像|教训)\]", title) or [None, None])[1],
           "struck": "~~" in title or "证伪" in title or "停用" in title}
    if dl:
        tag.update(dir=norm_dir(dl.group(1)) or dl.group(1).strip()[:10], dir_raw=dl.group(1).strip()[:80], src="蒸馏标注")
    else:
        d = norm_dir(tag["title"])   # 只看标题(去掉【修订·兑现】这类标签)(正文常混着情境/出场描述, 拿来定方向误标多; 标题无方向词=不定方向)
        if d in ("买", "卖") and norm_dir(rule_txt) not in (None, d, "持有"):   # 标题单向但规则正文两头都讲(如"开盘双通道入场"含出场) → 双向, 不进方向检查
            d = "双向"
        tag.update(dir=d, dir_raw=None, src="机械补标")
    mech = None
    # 机械模板只给"机械补标"的旧规则(蒸馏新规则自带机械触发, 多需盘中分时, 驱动器不判); 标题必须直说, 含亏损/不动/扛 的不套
    neg = re.search(r"亏|止损线|不卖|零动作|不动|扛|卖飞后", title)
    if tag["src"] == "机械补标" and not neg and tag["dir"] in ("卖", "双向", None) and (
            re.search(r"(T\+1|次日|隔夜)[^，,;；:：]{0,20}(卖|兑现|清)", title)):
        mech = {"kind": "overnight_sell", "text": "昨日新买、今日仍持有 → 今日早盘(0915 单)卖"}
        if "转债" in title:   # 只管转债的规则(如边学 R5)不套到股票上
            mech.update(codes_re=r"^(11|12)", text="昨日新买的转债、今日仍持有 → 今日早盘卖")
    src_txt = title + " " + rule_txt
    m = STOP.search(src_txt) if tag["src"] == "机械补标" and tag["dir"] in ("卖", "双向", None) and not re.search(r"不动|扛|零动作", title) else None
    if not mech and m:
        x = float(m.group(1) or m.group(2))
        if 1 <= x <= 30:
            mech = {"kind": "stop_loss", "pct": x, "text": f"持仓浮亏 ≤ -{x:g}% → 卖"}
    tag["mech"] = mech
    tag["mech_text"] = ml.group(1).strip()[:200] if ml else None
    tag["level"] = "机械" if mech else ("蒸馏机械触发(需盘中分时, 驱动器不判)" if ml else "话术级")
    if tag["struck"]:
        tag["dir"], tag["mech"], tag["level"] = None, None, "已证伪"
    return tag


def build_one(skill):
    f = SKILLS / f"{skill}-skill" / "persona" / "rules.md"
    if not f.exists():
        return None
    rules = [tag_rule(r) for r in parse_rules(f.read_text(encoding="utf-8", errors="replace"))]
    return {"skill": skill, "file": f"skills/{skill}-skill/persona/rules.md", "rules": {r["id"]: r for r in rules},
            "n": len(rules), "n_mech": sum(1 for r in rules if r["mech"]), "n_dir": sum(1 for r in rules if r["dir"]),
            "n_distilled": sum(1 for r in rules if r["src"] == "蒸馏标注")}


def build(skills=None):
    OUT.mkdir(parents=True, exist_ok=True)
    res = {}
    for sk in skills or TZZB:
        d = build_one(sk)
        if d:
            (OUT / f"{sk}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            res[sk] = d
    return res


def load(skill):
    return _jl(OUT / f"{skill}.json")


def text_block(skill, ctx=None):
    d = load(skill)
    if not d:
        return ""
    mech = [r for r in d["rules"].values() if r.get("mech")]
    dirs = [r for r in d["rules"].values() if r.get("dir") in ("买", "卖")]
    if not mech and not dirs:
        return ""
    L = ["- 规则方向/漏用检查(rule_tags, 驱动器校验): 引用的规则方向要与动作一致(" + "、".join(f"{r['id']}={r['dir']}" for r in dirs[:14]) + ")"]
    if mech:
        L.append("  - 可机械判定的规则(已触发却没体现=回炉一次; 不按它做就在 holds 里写该票+理由): "
                 + "; ".join(f"{r['id']} {r['mech']['text']}" for r in mech))
    return "\n".join(L)


def _prev_day(book, date_dash):
    ds = sorted({str(t.get("id", ""))[:10] for t in (book or {}).get("trades") or [] if str(t.get("id", ""))[:10] < date_dash}
                | {n.get("date") for n in (book or {}).get("nav") or [] if n.get("date", "") < date_dash})
    return ds[-1] if ds else None


def triggered(skill, ctx):
    """→ [(rule_id, code, 说明)] 已触发的机械规则"""
    d = load(skill)
    if not d:
        return []
    book, dd = ctx.get("book") or {}, ctx.get("date_dash")
    pos = {str(c): p for c, p in (book.get("positions") or {}).items() if int(p.get("qty") or 0) > 0}
    out = []
    for r in d["rules"].values():
        m = r.get("mech")
        if not m:
            continue
        if m["kind"] == "overnight_sell" and not ctx.get("sub") and (ctx.get("_q") or {}).get("slot", "0915") == "0915":
            pd = _prev_day(book, dd)
            bought = {str(t.get("code")) for t in book.get("trades") or [] if t.get("side") == "BUY" and str(t.get("id", ""))[:10] == pd}
            for c in sorted(bought & set(pos)):
                if m.get("codes_re") and not re.match(m["codes_re"], c):
                    continue
                out.append((r["id"], c, f"{r['id']}({r['title']}): {c} 是 {pd} 新买的隔夜仓"))
        elif m["kind"] == "stop_loss":
            snaps = {**((ctx.get("_q") or {}).get("watch") or {}), **(ctx.get("snap") or {})}
            for c, p in pos.items():
                last = float((snaps.get(c) or {}).get("last") or 0)
                cost = float(p.get("cost") or 0)
                if last > 0 and cost > 0 and last / cost - 1 <= -m["pct"] / 100:
                    out.append((r["id"], c, f"{r['id']}({r['title']}): {c} 浮亏 {last / cost - 1:.1%} ≤ -{m['pct']:g}%"))
    return out


def check(skill, c, acts, ctx):
    d = load(skill)
    if not d:
        return None
    errs = []
    for a in acts:
        op = a.get("op")
        if op not in ("买", "卖", "开盘卖"):
            continue
        for ref in a.get("rules") or []:
            r = d["rules"].get(str(ref.get("id") if isinstance(ref, dict) else ref))
            if not r or r.get("dir") not in ("买", "卖"):
                continue
            why = str(ref.get("ctx") or "") if isinstance(ref, dict) else ""
            # 买单引用卖方向规则当"出场计划"(ctx 里讲了卖/兑现/了结/持有几天)是正当用法, 不算相反; 卖单引用买规则同理(讲了接回/回补/再买)
            if r["dir"] == "卖" and op == "买" and re.search(r"卖|兑现|了结|出场|离场|止盈|止损|持有|次日|T\+1", why):
                continue
            if r["dir"] == "买" and op != "买" and re.search(r"接回|回补|再买|买回|入场|建仓", why):
                continue
            if (r["dir"] == "买" and op != "买") or (r["dir"] == "卖" and op == "买"):
                errs.append(f"{a.get('name') or a.get('code')} {op}单 引用 {r['id']}({r['title']}, 方向={r['dir']}) 方向相反——换成相符的规则或说明不引用")
    sold = {str(a.get("code")) for a in acts if a.get("op") in ("卖", "开盘卖")}
    txt = json.dumps({k: c.get(k) for k in ("holds", "no_trade_reason", "deviation_reason")}, ensure_ascii=False)
    for rid, code, why in triggered(skill, ctx):
        if code in sold or code in txt or re.search(rf"\b{rid}\b", txt):
            continue
        errs.append(f"规则已触发但单子没体现: {why}——要么下卖单, 要么在 holds 里写 {{\"code\":\"{code}\",\"why\":\"为什么这次不按 {rid}\"}}")
    return " | ".join(errs) if errs else None


def selftest():
    fails = []

    def chk(n, cnd):
        print(("PASS " if cnd else "FAIL ") + n)
        if not cnd:
            fails.append(n)

    md = """# x
## 规则
### R1 隔夜仓次日竞价卖出 [可跟]
- **规则**: 隔夜仓次日 09:25 竞价卖
### R2 尾盘建仓 [画像]
- **规则**: 14:30 后买入
### R7 开盘双通道入场 [画像]
- **规则**: 开盘买入, 半分钟内卖出
### R3 亏 5% 止损 [教训]
- **规则**: 浮亏到 -5% 止损卖出
### R4 低吸买点 [画像]（10/16 深度蒸馏新增）
- **方向**: 买
- **机械触发**: 当时位置≤0.3 → 挂低吸
### R5 ~~日内亏即收手~~(证伪)
- **规则**: 亏了就收手
### R6 高仓位不空仓 [画像]
- **规则**: 满仓
## 速览行
### R1 重复节不应覆盖
"""
    rs = {r["id"]: tag_rule(r) for r in parse_rules(md)}
    chk("解析 7 条(重复 id 取第一节)", len(rs) == 7 and "次日" in rs["R1"]["title"])
    chk("标题单向但正文两头讲=双向", rs["R7"]["dir"] == "双向")
    chk("R1 方向卖+overnight_sell", rs["R1"]["dir"] == "卖" and rs["R1"]["mech"]["kind"] == "overnight_sell")
    chk("R2 方向买 话术级", rs["R2"]["dir"] == "买" and rs["R2"]["mech"] is None and rs["R2"]["level"] == "话术级")
    chk("R3 止损 5%", rs["R3"]["mech"] and rs["R3"]["mech"]["kind"] == "stop_loss" and rs["R3"]["mech"]["pct"] == 5)
    chk("R4 蒸馏标注原样", rs["R4"]["src"] == "蒸馏标注" and rs["R4"]["dir"] == "买" and rs["R4"]["mech_text"])
    chk("R5 证伪不标", rs["R5"]["dir"] is None and rs["R5"]["level"] == "已证伪")
    chk("R6 持有", rs["R6"]["dir"] == "持有")
    import tempfile
    global OUT
    old = OUT
    OUT = Path(tempfile.mkdtemp(prefix="ruletags_"))
    try:
        (OUT / "x.json").write_text(json.dumps({"rules": rs}, ensure_ascii=False), encoding="utf-8")
        book = {"positions": {"600001": {"qty": 100, "cost": 10.0}, "600002": {"qty": 100, "cost": 10.0}},
                "trades": [{"id": "2026-10-15-A-x-001", "side": "BUY", "code": "600001"}], "nav": [{"date": "2026-10-15"}]}
        ctx = {"date_dash": "2026-10-16", "sub": False, "book": book, "_q": {"slot": "0915", "watch": {"600002": {"last": 9.4}}}, "snap": {}}
        tr = triggered("x", ctx)
        chk("触发: R1 隔夜仓 600001 + R3 止损 600002", {(a, b) for a, b, _ in tr} == {("R1", "600001"), ("R3", "600002")})
        chk("漏用=拦", check("x", {"actions": []}, [], ctx) is not None)
        ok_c = {"holds": [{"code": "600001", "why": "按 R1 本该卖, 今天高开不卖"}, {"code": "600002", "why": "等反抽"}]}
        chk("holds 写了理由=放", check("x", ok_c, [], ctx) is None)
        acts = [{"op": "卖", "code": "600001"}, {"op": "卖", "code": "600002"}]
        chk("下了卖单=放", check("x", {}, acts, ctx) is None)
        bad = [{"op": "买", "code": "600003", "name": "丙", "rules": [{"id": "R1", "ctx": "情境满足: 主线强"}]}] + acts
        chk("买单引用卖方向规则=拦", "方向相反" in (check("x", {}, bad, ctx) or ""))
        plan = [{"op": "买", "code": "600003", "name": "丙", "rules": [{"id": "R1", "ctx": "买入后按 R1 次日竞价兑现"}]}] + acts
        chk("买单引用卖规则当出场计划=放", check("x", {}, plan, ctx) is None)
        good = [{"op": "买", "code": "600003", "rules": [{"id": "R4"}]}] + acts
        chk("方向一致=放", check("x", {}, good, ctx) is None)
        chk("子链不查隔夜仓", all(a != "R1" for a, _, _ in triggered("x", dict(ctx, sub=True))))
        chk("text_block 列机械规则", "R1" in text_block("x") and "R3" in text_block("x"))
        chk("无标注文件=不查", check("nobody", {}, bad, ctx) is None and text_block("nobody") == "")
    finally:
        OUT = old
    print("SELFTEST " + ("PASS" if not fails else f"FAIL {fails}"))
    return 0 if not fails else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--skill")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if a.build:
        res = build([a.skill] if a.skill else None)
        print("| 导师 | 规则数 | 有方向 | 可机械判定 | 已有蒸馏标注 |\n|---|---|---|---|---|")
        for sk, d in res.items():
            print(f"| {sk} | {d['n']} | {d['n_dir']} | {d['n_mech']} | {d['n_distilled']} |")
    if a.show:
        for sk in ([a.skill] if a.skill else TZZB):
            d = load(sk)
            if not d:
                continue
            for r in d["rules"].values():
                print(f"{sk} {r['id']} [{r['src']}] 方向={r['dir']} {r['level']}" + (f" {r['mech']['text']}" if r.get("mech") else "") + f" | {r['title']}")
    if not (a.build or a.show):
        ap.print_help()


if __name__ == "__main__":
    main()
