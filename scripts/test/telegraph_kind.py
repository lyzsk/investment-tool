# -*- coding: utf-8 -*-
"""telegraph_kind.py — 加红电报点名: 按"电报说了这只票什么"分类 → 点名后次日表现; 点名后开板 → 按板高 / 市值 / 开板时刻拆(10/25 用户)

用户 10/25: 不要用 N 分钟时间窗一刀切, 先看关键词; "xx 股大涨 / yy 股大跌"这种异动播报次日负期望, 其他点名没研究过;
           涨停点名 + 之后开板 = 想捕获的 T 字 / 回封; 数据覆盖近 100 个交易日就够
分类 v2(两层, 只用电报原文, 盘中当场能算):
  电报类型(看标题): 外盘(港股 / 美股) · 涨停分析(午间 / 收盘涨停分析) · 综述(午评 / 收评 / 指数 / 两市) · 板块异动(xx 板块 / 概念股 拉升 / 走强 / 跳水…)
                  · 个股利空(减持 / 立案 / 问询 / 处罚 / 风险提示…) · 个股消息(公告 / 中标 / 合同 / 回购 / 增持 / 预增 / 获批…) · 个股异动(单票涨跌 / 新高) · 其他
  这只票的动作(分句): 从票名往后读到第一个 "，。；"(顿号 "、" 不断句, 所以 "A、B、C 涨停" 三只都是涨停), 里面的谓语:
                  冲板(触及 / 逼近 / 冲击涨停、炸板) · 封板(涨停 / 封板 / N 连板 / N 天 M 板 / 一字) · 大涨(涨超 / 拉升 / 冲高 / 走强 / 直线…) · 大跌(跌停 / 跌超 / 跳水 / 下挫…) · 只点名
  领 / 跟: 这只票是不是这条电报第一个被点到的票; 此前: 票名前同一分句有"此前 / 曾"(说的是今天更早的事)
v1(上一版: 票名前后 30 字找关键词)一并算出, 给 v1 → v2 对照
盘中能算的"见顶"代理: 点名那一分钟离当天此前最高回落了多少(< 1% = 还在高点附近, ≥ 2% = 已回落)、点名时涨了多少
口径: 买点 = 点名后下一分钟收盘, 那一分钟封死在板上的买不进、剔除(同 telegraph_nextday / telegraph-skill T1); 次日 = 相对买点
产物: docs/research/telegraph_kind.md + docs/research/telegraph_kind_samples.md(每类随机示例, 人工核对分类用)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/test/telegraph_kind.py [--days 100]
"""
import argparse
import collections
import json
import random
import re
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "test"), str(ROOT / "scripts" / "market")]
OUT = ROOT / "docs" / "research" / "telegraph_kind.md"
SAMPLES = ROOT / "docs" / "research" / "telegraph_kind_samples.md"
STATS = ROOT / "downloads" / "ontology" / "telegraph_kind_stats.json"   # 10/25: 必查「电报点名」读这份(tools/telegraph_now.py)
ST_ = {}

# ---- v1(上一版, 留作对照) ----
KW1 = [("涨停播报", r"涨停|封板|连板|\d+\s*板|一字"),
       ("大跌异动", r"跌停|大跌|跳水|下挫|跌超|跌幅扩大|闪崩|重挫"),
       ("大涨异动", r"大涨|拉升|涨超|直线|走强|冲高|涨幅扩大|异动|爆发|飙升"),
       ("公告消息", r"公告|中标|签订|合同|回购|增持|预增|业绩|获批|收购|重组|定增|订单")]


def kind_v1(text, name):
    t = text.replace(" ", "")
    i = t.find((name or "").replace(" ", ""))
    seg = t[max(0, i - 30): i + len(name) + 30] if i >= 0 else t
    return next((k for k, rx in KW1 if re.search(rx, seg)), "其他")


# ---- v2 ----
ZONG = r"午评|收评|早评|三大指数|沪指|深成指|创业板指|科创50|全市场|两市|半日|成交额|北向资金|A股收盘|A股开盘|集合竞价"
ZTFX = r"涨停分析|涨停复盘|连板股|封板率"
WAI = r"港股|恒生|H股|美股|纳指|道指|标普|中概"
BAN = r"板块|概念股?|产业链|赛道|题材|方向|(?:股|概念|板块)(?:持续|集体|午后|盘中|早盘|再度|尾盘|快速|震荡)?(?:走强|拉升|大涨|异动|走高|爆发|活跃|反弹|涨停潮|跳水|走弱|下挫|大跌|冲高|飙升|调整|回落)|涨停潮|集体|多股|十余股|批量"
BAD = r"减持|立案|问询|处罚|警示函|监管函|终止|亏损|预亏|预减|风险提示|异常波动|退市|停牌核查|违规|诉讼|冻结|质押|爆雷|下修"
GOOD = r"公告|中标|签订|签署|合同|回购|增持|预增|扭亏|业绩|获批|收购|重组|定增|订单|合作|量产|首发|调研|回应"
MOVE = r"涨超|涨逾|跌超|跌逾|涨停|跌停|拉升|跳水|走强|走弱|新高|新低|大涨|大跌|触及|逼近|扩大涨幅|扩大跌幅"
ACT = [("冲板", r"触及(?:20cm|20CM)?涨停|逼近(?:20cm|20CM)?涨停|冲击(?:20cm|20CM)?涨停|一度涨停|冲板|涨停.{0,3}(?:打开|开板|炸板)|炸板"),
       ("封板", r"涨停|封板|封死|\d+连板|\d+天\d+板|[二三四五六七八九十\d]+板|一字|地天"),
       ("大跌", r"跌停|跌超|跌逾|跌近|大跌|跳水|下挫|闪崩|重挫|跌幅扩大|走低|翻绿|天地|跌幅(?:居前|靠前)|跟跌|领跌"),
       ("大涨", r"涨超|涨逾|涨近|大涨|拉升|冲高|走强|涨幅扩大|扩大涨幅|直线|飙升|走高|翻红|涨\d|拉涨|异动|涨幅(?:居前|靠前)|跟涨|领涨|新高")]


def title_of(text):
    m = re.match(r"\s*【([^】]{2,80})】", text)
    return m.group(1) if m else text[:40]


def tg_type(text):
    t = title_of(text).replace(" ", "")
    head = text.replace(" ", "")[:80]
    if re.search(WAI, t):
        return "外盘"
    if re.search(ZTFX, t):
        return "涨停分析"
    if re.search(ZONG, t) or re.search(r"午评|收评", head):
        return "综述"
    if re.search(BAN, t):
        return "板块异动"
    if re.search(BAD, t):
        return "个股利空"
    if re.search(GOOD, t):
        return "个股消息"
    if re.search(MOVE, t):
        return "个股异动"
    return "其他"


def clause(text, name):
    """票名起到第一个 "，。；！？" 为止(顿号不断句; 名字后面直接是"、"说明是列举, 继续读到谓语)"""
    t = text.replace(" ", "")
    i = t.find(name.replace(" ", ""))
    if i < 0:
        return ""
    m = re.search(r"[，。；;！？!?\n]", t[i:])
    return t[i: i + (m.start() if m else 60)][:80]


def past(text, name):
    """票名前面同一分句里有 "此前 / 早盘曾 / 昨日" = 说的是之前的事(此前 X 涨停 = 这只票今天更早封过板)"""
    t = text.replace(" ", "")
    i = t.find(name.replace(" ", ""))
    k = max(t.rfind(ch, 0, i) for ch in "，。；】")
    return bool(re.search(r"此前|早盘曾|曾|昨日|前一交易日|上周", t[k + 1: i])) if i > 0 else False


NOT_SUBJ = r"^.{2,6}?(?:指出|认为|表示|称|研报|目标价|董秘|办公室|汽车|产业规模|成为|反超)"


def action(text, name):
    c = clause(text, name)
    if re.search(NOT_SUBJ, c) and not any(re.search(rx, c) for _, rx in ACT):   # 10/25 人工抽查: "中信证券指出" / "载人航天工程办公室" / "我国新能源汽车" 不是在说这只票的行情
        return "非主体"
    return next((k for k, rx in ACT if re.search(rx, c)), "只点名")


def lead(text, name, names_in):
    t = text.replace(" ", "")
    pos = sorted((t.find(n.replace(" ", "")), n) for n in names_in if t.find(n.replace(" ", "")) >= 0)
    return "领" if pos and pos[0][1] == name else "跟"


# ---- 统计工具 ----
def dist(xs, k="co"):
    v = sorted(((x[k], x) for x in xs if x.get(k) is not None), key=lambda p: p[0])
    if not v:
        return "-"
    a = [p for p, _ in v]
    w, b = v[0][1], v[-1][1]
    return (f"中{a[len(a) // 2]:+.2f} 均{st.mean(a):+.2f} P10 {a[int(len(a) * .1)]:+.2f} P90 {a[min(len(a) - 1, int(len(a) * .9))]:+.2f} "
            f"最差{a[0]:+.2f}({w['name']} {w['D'][5:]}) 最好{a[-1]:+.2f}({b['name']} {b['D'][5:]})")


def summ(xs, k="co"):
    """给必查用的紧凑分布"""
    a = sorted(x[k] for x in xs if x.get(k) is not None)
    if not a:
        return None
    return {"n": len(a), "med": round(a[len(a) // 2], 2), "mean": round(st.mean(a), 2), "p10": round(a[int(len(a) * .1)], 2),
            "p90": round(a[min(len(a) - 1, int(len(a) * .9))], 2), "worst": round(a[0], 2)}


def short(xs, k="co"):
    a = sorted(x[k] for x in xs if x.get(k) is not None)
    return f"{len(a)} / 中{a[len(a) // 2]:+.2f} 均{st.mean(a):+.2f}" if a else "0"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=100)
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()
    import manual_backfill as mb
    import telegraph_nextday as TN
    import telegraph_validate as TV
    rows0, _, _, sealed0, _ = TN.collect()
    days = sorted({r["D"] for r in rows0})[-a.days:]
    D0 = days[0]
    rows0 = [r for r in rows0 if r["D"] >= D0]
    con = TV.db()
    cur = con.cursor()
    by_name, by_code = TV.names(cur)
    full, cache = {}, {}
    for D in days:
        for t, txt in TV.telegraphs(D):
            full.setdefault((D, t), []).append(txt)
    # 10/25 人工抽查发现: md 里的电报原文会截断(午评后半段的"xx 等纷纷下挫"被切掉 → 误判"只点名") → 业务库 cls_telegraph 有全文(03-01 起), 同一分钟优先用全文
    c2 = mb.db().cursor()
    c2.execute("select date_format(publish_time,'%%Y-%%m-%%d'), date_format(publish_time,'%%H:%%i'), content from investment_tool.cls_telegraph where is_deleted=0 and publish_time >= %s",
               (days[0],))
    dbt = collections.defaultdict(list)
    for d_, t_, ct in c2.fetchall():
        if ct:
            dbt[(d_, t_)].append(ct)
    n_db = 0
    for k, v in full.items():
        if dbt.get(k):
            full[k] = dbt[k] + v   # 全文在前, md 截断版留作兜底
            n_db += 1
    print(f"电报分钟 {len(full)} 个, 其中 {n_db} 个用到库里全文")
    rows = []
    for r in rows0:
        txts = [x for x in full.get((r["D"], r["t"]), []) if r["name"] and r["name"] in x.replace(" ", "")]
        if not txts:
            continue
        txt = txts[0]
        b = TV.bars(cur, r["D"], r["sym"], cache)
        pre = [x for x in b if x[0] <= r["t"]]
        dd = (max(x[1] for x in pre) / pre[-1][2] - 1) * 100 if pre and pre[-1][2] else None
        nm_in = list(TV.mentions(txt, by_name, by_code).values())
        rows.append({**r, "text": txt, "v1": kind_v1(txt, r["name"]), "type": tg_type(txt), "act": action(txt, r["name"]),
                     "lead": lead(txt, r["name"], nm_in), "past": past(txt, r["name"]), "n_named": len(nm_in), "dd": dd, "upp": (r["up"] or 0) * 100, "clause": clause(txt, r["name"])})
    rows.sort(key=lambda r: (r["D"], r["t"]))
    half = days[len(days) // 2]
    TY = ["综述", "涨停分析", "板块异动", "个股异动", "个股消息", "个股利空", "外盘", "其他"]
    AC = ["封板", "冲板", "大涨", "大跌", "只点名", "非主体"]
    L = [f"# 加红电报点名分类 v2 · 近 {len(days)} 个交易日（{days[0]} ~ {days[-1]}）· 可成交点名 {len(rows)} 个（剔除点名后一分钟封死买不进的）", "",
         "> 脚本 `scripts/test/telegraph_kind.py`（零 token）。买点 = 点名后下一分钟收盘；表里\"次日收盘 / 次日最高\"都相对买点 %。",
         "> 分类只用电报原文、盘中当场能算；\"已见顶\"那一列用的是点名之后的走势（事后口径），盘中可用的代理见第四节。", "",
         "## 一、v2 分类：这只票的动作 × 电报类型（次日收盘：次数 / 中位 / 均值）", "",
         "| 动作 ＼ 类型 | " + " | ".join(TY) + " | 合计 |", "|---|" + "---|" * (len(TY) + 1)]
    for ac in AC:
        L.append(f"| {ac} | " + " | ".join(short([r for r in rows if r["act"] == ac and r["type"] == ty]) for ty in TY) + f" | **{short([r for r in rows if r['act'] == ac])}** |")
    L += ["", "## 二、按动作看全分布（次日收盘 / 次日最高）", "", "| 动作 | 次数 | 次日收盘 | 次日最高 | 次日最高 ≥+3% |", "|---|---|---|---|---|"]
    for ac in AC:
        xs = [r for r in rows if r["act"] == ac]
        if xs:
            L.append(f"| {ac} | {len(xs)} | {dist(xs)} | {dist(xs, 'hi')} | {sum(x['hi'] >= 3 for x in xs) / len(xs):.0%} |")
    L += ["", "领涨 vs 跟涨（这只票是不是这条电报第一个被点到的）：", "", "| 动作 | 领：次数 / 次日收盘 | 跟：次数 / 次日收盘 |", "|---|---|---|"]
    for ac in AC:
        L.append(f"| {ac} | {short([r for r in rows if r['act'] == ac and r['lead'] == '领'])} | {short([r for r in rows if r['act'] == ac and r['lead'] == '跟'])} |")
    L += ["", "\"此前 X 涨停 / 曾 …\"（电报说的是这只票今天更早的事）vs 说的是现在：", "", "| 动作 | 此前：次数 / 次日收盘 | 现在 |", "|---|---|---|"]
    for ac in AC:
        L.append(f"| {ac} | {short([r for r in rows if r['act'] == ac and r['past']])} | {short([r for r in rows if r['act'] == ac and not r['past']])} |")
    L += ["", "## 三、v1（票名前后 30 字找关键词）→ v2 对照：v1 每类被 v2 分到哪", "", "| v1 \\ v2 动作 | " + " | ".join(AC) + " |", "|---|" + "---|" * len(AC)]
    for k1 in ["涨停播报", "大涨异动", "大跌异动", "公告消息", "其他"]:
        L.append(f"| {k1} | " + " | ".join(str(sum(1 for r in rows if r["v1"] == k1 and r["act"] == ac)) for ac in AC) + " |")
    L += ["", "## 四、盘中能算的\"见顶\"代理 vs 事后真见顶", "",
          "点名那一分钟离当天此前最高回落了多少（盘中能算）：", "", "| 动作 | 回落 <1%（还在高点附近） | 回落 1~2% | 回落 ≥2%（已回落） |", "|---|---|---|---|"]
    for ac in AC:
        xs = [r for r in rows if r["act"] == ac and r["dd"] is not None]
        L.append(f"| {ac} | {short([r for r in xs if r['dd'] < 1])} | {short([r for r in xs if 1 <= r['dd'] < 2])} | {short([r for r in xs if r['dd'] >= 2])} |")
    L += ["", "点名时当天已经涨了多少（盘中能算）：", "", "| 动作 | <3% | 3~7% | ≥7% |", "|---|---|---|---|"]
    for ac in AC:
        xs = [r for r in rows if r["act"] == ac]
        L.append(f"| {ac} | {short([r for r in xs if r['upp'] < 3])} | {short([r for r in xs if 3 <= r['upp'] < 7])} | {short([r for r in xs if r['upp'] >= 7])} |")
    L += ["", "事后口径（点名之后当天再没创新高 = 已见顶；盘中不知道，只用来看代理准不准）：", "", "| 动作 | 已见顶 | 没见顶 | 代理\"回落 ≥1%\"和事后\"已见顶\"一致率 |", "|---|---|---|---|"]
    for ac in AC:
        xs = [r for r in rows if r["act"] == ac and r["dd"] is not None]
        agree = sum((r["dd"] >= 1) == bool(r["peaked"]) for r in xs) / len(xs) if xs else 0
        L.append(f"| {ac} | {short([r for r in xs if r['peaked']])} | {short([r for r in xs if not r['peaked']])} | {agree:.0%} |")
    L += ["", f"## 五、前后两半稳不稳（前 {days[0]}~ / 后 {half}~）", "", "| 动作 | 前半：次数 / 次日收盘 | 后半 |", "|---|---|---|"]
    for ac in AC:
        L.append(f"| {ac} | {short([r for r in rows if r['act'] == ac and r['D'] < half])} | {short([r for r in rows if r['act'] == ac and r['D'] >= half])} |")
    L += ["", "一条电报点多只票会被重复计 → 按\"同一条电报 × 同一动作\"先取平均、再统计（每条电报只算一次）：", "", "| 动作 | 不去重：次数 / 次日收盘 | 按条去重 |", "|---|---|---|"]
    for ac in AC:
        g = collections.defaultdict(list)
        for r in rows:
            if r["act"] == ac:
                g[(r["D"], r["t"], r["text"][:60])].append(r["co"])
        dd_ = [{"co": st.mean(v)} for v in g.values()]
        L.append(f"| {ac} | {short([r for r in rows if r['act'] == ac])} | {short(dd_)} |")
    if "--no-open" not in sys.argv:
        L += opened_after_named(rows, days, full, by_name, by_code)
    L += ["", "## 不自信点", "",
          "- 分类是关键词规则，`telegraph_kind_samples.md` 里每格随机 6 条原文可以人工核对",
          "- **人工抽查（10/25，约 105 条随机示例）**：第一版约 90% 分对；错的两类已修——①md 里电报原文被截断（午评后半段\"xx 等纷纷下挫\"被切掉 → 误判\"只点名\"），改用业务库 cls_telegraph 全文（03-01 起），\"只点名\"从 391 降到 63；②票名被误认（\"载人航天工程办公室\"→航天工程、\"我国新能源汽车\"→国新能源、\"中信证券指出\"是券商观点不是行情），新增\"非主体\"类单列（15 次）。还剩的已知问题：港股 / H 股电报里的同名 A 股（兆易创新、华虹宏力）归\"外盘\"，用的是 A 股价格",
          "- 已剔除点名后一分钟封死买不进的；按条去重后方向不变（第五节下表）",
          "- 100 个交易日里大部分是同一段行情；封板 / 冲板前后两半方向不完全一致（小样本），大跌两半一致为负",
          "- 第六节\"开板即接\"用的是分钟收盘价，秒开秒封的那一分钟实际能不能成交没验证；流通市值用最近换手率反推的流通股数 × 当天收盘，股本变动的票会有偏差"]
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    write_samples(rows, TY, AC)
    ST_["days"] = [days[0], days[-1]]
    ST_["act"] = {ac: {"co": summ([r for r in rows if r["act"] == ac]), "hi": summ([r for r in rows if r["act"] == ac], "hi"),
                       "dd": {b: summ([r for r in rows if r["act"] == ac and r["dd"] is not None and f(r["dd"])]) for b, f in
                              (("<1", lambda v: v < 1), ("1~2", lambda v: 1 <= v < 2), (">=2", lambda v: v >= 2))},
                       "lead": {lv: summ([r for r in rows if r["act"] == ac and r["lead"] == lv]) for lv in ("领", "跟")}} for ac in AC}
    STATS.parent.mkdir(parents=True, exist_ok=True)
    STATS.write_text(json.dumps(ST_, ensure_ascii=False, indent=1), encoding="utf-8")


def write_samples(rows, TY, AC):
    rnd = random.Random(1025)
    S = ["# 电报点名分类 v2 · 随机示例（人工核对用）", "", "每格随机 6 条：时间 · 票 · 分到的类 · 该票所在分句 · 原文前 120 字 · 次日收盘", ""]
    for ac in AC:
        for ty in TY:
            xs = [r for r in rows if r["act"] == ac and r["type"] == ty]
            if not xs:
                continue
            S += [f"## {ac} × {ty}（{len(xs)}）", ""]
            for r in rnd.sample(xs, min(6, len(xs))):
                S.append(f"- {r['D']} {r['t']} **{r['name']}**（{r['lead']}{'，此前' if r['past'] else ''}，v1={r['v1']}）分句「{r['clause']}」 · {r['text'][:120].replace('|', '/')} · 次日收盘 {r['co']:+.2f}")
            S.append("")
    SAMPLES.write_text("\n".join(S) + "\n", encoding="utf-8")


def opened_after_named(rows, days, full, by_name, by_code):
    """电报点名之后开板(用户想捕获的 T 字 / 回封) vs 同期没被点名的开板; 按板高 / 流通市值 / 第几次开板 / 开板时刻拆"""
    import board_knowledge as BK
    import manual_backfill as mb
    _, opens, *_ = BK.collect()
    opens = [e for e in opens if days[0] <= e["D"] <= days[-1]]
    if not opens:
        return ["", "## 六、点名后开板：没有分钟路径数据"]
    named = collections.defaultdict(list)   # (日, 代码) → [(时刻, 动作)] —— 用全部点名(含封死买不进的), 开板时才接
    for (D, t), txts in full.items():
        for txt in txts:
            for sym, nm in TV_mentions(txt, by_name, by_code).items():
                named[(D, sym[2:])].append((t, action(txt, nm) if not nm.isdigit() else "只点名"))
    cur = mb.db().cursor()
    codes = sorted({e["code"] for e in opens})
    MC = {}   # 10/25: 行情库换手率只有最近几天有 → 流通股数 = 最近一个有换手率的交易日 成交额 / 换手率 / 收盘价, 当天流通市值 ≈ 流通股数 × 当天收盘(股本变化慢, 近似)
    for i in range(0, len(codes), 400):
        part = [("sh" if c.startswith("6") else "sz") + c for c in codes[i:i + 400]]
        cur.execute("select symbol, trade_date, amount, turnover_rate, close from investment_market.kline_day where is_deleted=0 and trade_date>=%s and symbol in ("
                    + ",".join(["%s"] * len(part)) + ") order by trade_date", (days[0], *part))
        closes, shares = collections.defaultdict(dict), {}
        for s, d, amt, tr, cl in cur.fetchall():
            if cl:
                closes[s[2:]][str(d)] = float(cl)
            if amt and tr and cl and float(tr) > 0:
                shares[s[2:]] = float(amt) / (float(tr) / 100) / float(cl)
        for c_, dd in closes.items():
            if c_ in shares:
                for d_, cl in dd.items():
                    MC[(c_, d_)] = shares[c_] * cl / 1e8
    A, B = [], []
    for e in opens:
        pre = [x for x in named.get((e["D"], e["code"]), []) if x[0] <= e["t"]]
        e = {**e, "co": e["next_co"], "hi": e["next_hi"], "mc": MC.get((e["code"], e["D"]))}
        if pre:
            e["nact"] = pre[0][1]
            A.append(e)
        elif (e["D"], e["code"]) not in named:
            B.append(e)
    md = sorted({e["D"] for e in opens})
    L = ["", f"## 六、电报点名之后开板 vs 同期没被点名的开板（分钟路径覆盖 {md[0]} ~ {md[-1]}，{len(md)} 个交易日）", "",
         "> 开板事件 = `board_knowledge.collect()`（主板 + 创业板非 ST，分钟收盘价跌离涨停价）；接 = 开板那一分钟价；跌深接 = 开板后跌到离涨停 2 / 3 / 5% 那一刻。",
         "> 点名后开板 = 开板时刻之前当天已经被加红电报点过名（含点名时封死买不进的）。", "",
         "| 组 | 开板次数 | 之后封回 | 收盘封住 | 开板即接→次日收盘 | →次日最高 | 跌 2% 接：封回 / 次日收盘 | 跌 3% 接 | 跌 5% 接 |", "|---|---|---|---|---|---|---|---|---|"]

    def deep(xs, x):
        ys = [{**e["deep"][x], "co": e["deep"][x]["next_co"]} for e in xs if x in e["deep"]]
        return f"{sum(y['resealed'] for y in ys) / len(ys):.0%} / {short(ys)}" if ys else "-"

    def row(nm, xs):
        if not xs:
            return f"| {nm} | 0 | | | | | | | |"
        return (f"| {nm} | {len(xs)} | {sum(e['resealed'] for e in xs) / len(xs):.0%} | {sum(e['close_sealed'] for e in xs) / len(xs):.0%} | {dist(xs)} | "
                f"{short(xs, 'hi')} | {deep(xs, 2)} | {deep(xs, 3)} | {deep(xs, 5)} |")
    ST_["open"] = {"named": {"n": len(A), "reseal": round(sum(e["resealed"] for e in A) / len(A), 3) if A else None, "co": summ(A), "hi": summ(A, "hi"),
                             "deep": {x: {"n": len([e for e in A if x in e["deep"]]), "reseal": round(sum(e["deep"][x]["resealed"] for e in A if x in e["deep"]) / max(1, len([e for e in A if x in e["deep"]])), 3),
                                          "co": summ([{"co": e["deep"][x]["next_co"]} for e in A if x in e["deep"]])} for x in (2, 3, 5)}},
                   "unnamed": {"n": len(B), "reseal": round(sum(e["resealed"] for e in B) / len(B), 3) if B else None, "co": summ(B)}}
    L += [row("已被电报点名", A), row("当天没被点名", B), "", "### 拆开看（每格：点名组 / 没点名组；封回率 · 开板即接次日收盘 次数 / 中位 / 均值）", ""]

    def cell(xs):
        return f"封回 {sum(e['resealed'] for e in xs) / len(xs):.0%} · {short(xs)}" if xs else "0"
    splits = [("点名时这只票的动作", lambda e: e.get("nact"), ["封板", "冲板", "大涨", "大跌", "只点名"]),
              ("板高（今天是第几板）", lambda e: "首板" if e["height"] == 1 else "2 板" if e["height"] == 2 else "3 板+", ["首板", "2 板", "3 板+"]),
              ("流通市值", lambda e: None if e["mc"] is None else "小(<50亿)" if e["mc"] < 50 else "中(50~200亿)" if e["mc"] < 200 else "大(≥200亿)", ["小(<50亿)", "中(50~200亿)", "大(≥200亿)"]),
              ("当天第几次开板", lambda e: "第 1 次" if e["k"] == 1 else "第 2 次+", ["第 1 次", "第 2 次+"]),
              ("开板时刻", lambda e: "10:00 前" if e["t"] < "10:00" else "10:00~11:30" if e["t"] <= "11:30" else "13:00~14:00" if e["t"] < "14:00" else "14:00 后", ["10:00 前", "10:00~11:30", "13:00~14:00", "14:00 后"])]
    for title, f, keys in splits:
        L += [f"**{title}**", "", "| 档 | 已被电报点名 | 当天没被点名 |", "|---|---|---|"]
        for k in keys:
            L.append(f"| {k} | {cell([e for e in A if f(e) == k])} | {cell([e for e in B if f(e) == k]) if title != '点名时这只票的动作' else '—'} |")
        L.append("")
    return L


def TV_mentions(txt, by_name, by_code):
    import telegraph_validate as TV
    return TV.mentions(txt, by_name, by_code)


if __name__ == "__main__":
    main()
