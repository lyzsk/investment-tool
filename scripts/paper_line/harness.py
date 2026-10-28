# -*- coding: utf-8 -*-
"""harness.py — 链的约束层(10/24 用户批: ①04 必填"深度 / 广度"字段 + 内容闸 ②03 多空改一次调用 ③05 改机械风控, 有用的定性判断并进 04)

配置: scripts/live/harness.yaml(用户可改); 读不到用这里的默认值。零 token。
  ASK03_ONE        03 一次调用写空方 + 多方(替代两个分叉: 10/23 分叉常不命中缓存, 带 03 那本 $157 vs 不带 $32)
  REQ04            04 每只新开 / 加仓票的必填字段(本票同形态 / 同逻辑邻居 / 龙虎榜 / 电报 / 买入后情景树 / 本轮市况风险)
  gate04(...)      内容闸: 必填字段齐不齐、E 编号是不是真在材料里、负样本有没有被当依据、确定性用词有没有百分比 → 违规清单
  mech05(...)      机械风控: 今天新开票数上限(导师近 5 / 10 / 20 日动态) / 当日亏损暂停新买 / 单票仓位上限 → dict + 给 06 看的文本
  enforce05(...)   06 落地后硬执行: 超出的新开买单剔掉(按出现顺序保留前 N), 暂停新买时剔掉全部新开买单
10/24 步骤边界 v2(用户: harness 约束每一步输出什么 + 已有材料不许忽略; 用户把"看多少 / 证据要多少"交给 Claude 定):
  ASK02_V2 / gate02   02 只出: 态度 / ≤3 条证据(只写编号) / ≤3 个方向 / 和机械状态不一致的理由 / 代码能判的翻转条件 / ≤300 字备注
  ASK03_ONE / gate03  03 每方恰好 3 条, 每条 论断 + 引用 + 类型; 不打分不决定; 有负样本 / 最差情景时空方必须引
  req_checked / gate04  04 对持仓 + 建加减清的票逐"类别"回应必查(类别从材料自动解析); 证据门槛: 建 / 加 ≥2 类支持, 减 / 清 ≥1 类; 反对必须写回应;
                     近期规律列出形态时不许"无关"; 结论里的百分比必须是材料原数; 带 03 时建 / 加必须 rebut 空方
  enforce06        06 只能落: 04 建 / 加的票 + 持仓 + 上一版已有的票; 04 清仓的票不许再买 → 违规的机械剔掉(不再叫模型)
"""
import datetime as dt
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG_F = ROOT / "scripts" / "live" / "harness.yaml"
DEF = {"banned_words": ["大概率", "稳了", "必然", "肯定", "一定会", "无脑"],
       "risk05": {"mode": "mech", "windows": [5, 10, 20], "new_open_mult": 1.5, "daily_loss_pause_pct": -3.0, "single_max_pct": "auto", "model_can_only_tighten": True}}
NO_DATA = re.compile(r"无数据|未上榜|无点名|没上榜|没有点名|不适用|查询失败|样本 ?0")


def cfg():
    try:
        import yaml
        d = yaml.safe_load(CFG_F.read_text(encoding="utf-8")) or {}
    except Exception:   # noqa: BLE001
        d = {}
    return {"banned_words": (d.get("content_gate") or {}).get("banned_words") or DEF["banned_words"],
            "risk05": {**DEF["risk05"], **(d.get("risk05") or {})},
            "min_support": {"建": 0, "加": 0, "减": 0, "清": 0, **(((d.get("steps") or {}).get("04") or {}).get("min_support") or {})},   # 10/24 用户: 先归零
            "on_fail": str((d.get("steps") or {}).get("on_fail") or "guide"),            # guide = 只记录不打回(10/24 用户: 目的是告诉模型怎么做, 不是拦截) | retry = 打回一次
            "only06": str(((d.get("steps") or {}).get("06") or {}).get("only_04_picks") or "warn"),   # warn = 只记录 | drop = 机械剔掉
            "slim": bool((d.get("inputs") or {}).get("slim", False)),   # 10/24 用户: 默认全量
            "full_n": int((d.get("inputs") or {}).get("must_check_full_n", 99)),
            "shared02": bool(((d.get("steps") or {}).get("02") or {}).get("shared", True)),   # 10/24 📋1 02 全体共用(market02.py)   # 10/24 📋1 材料瘦身(规则简表 / 不常驻案例全文和工作流 / 前一天 md 摘要)
            "note_max": int(((d.get("steps") or {}).get("02") or {}).get("note_max_chars") or 300)}


ASK03_ONE = """【03 多空(一次写两面)】基于 01 事实、02 市况和必查结果, 先写**空方**再写**多方**, 各恰好 3 条论点; 每条 = 一句论断(≤40 字) + 引用(E 编号 / 规则编号 / 大小盘段编号 M大n·M小n) + 类型(数据 / 规则 / 样本 / 资金 / 题材 / 市况)。
空方必须: 材料里有 ⚠负样本 或"最差 / P10"的, 至少引一条; 必查"近期规律"对多方不利时要引。
多方必须: 写好情况出现的频率(例: "n=40, P75 +3%"), 不许只举最好的一个例子; 导师正样本、资金(龙虎榜净买)、题材阶段的支持。
不打分、不做决定(决定留给 04)。最后各写一句"对方最有力的一条, 我怎么回应"。
最后 ```json {"bear": {"args": [{"claim": "...", "cite": "E3", "type": "样本"}], "reply_to_bull": "..."}, "bull": {"args": [{"claim": "...", "cite": "E5", "type": "数据"}], "reply_to_bear": "..."}}"""

REQ04 = """
【必填(harness 约束, 不填会被打回)】每只 action = 建 / 加 的票, 在 json 的这只票里加 "depth":
  "same_form": 本票同形态分布, 写 E 编号 + 一句结论(必须同时说中位和最差 / P10, 不能只说中位)
  "peers": 同逻辑邻居(股票: 席位风格 / 同题材 / 梯队位置; 转债: 同债近期路径), 写 E 编号 + 结论
  "lhb": 龙虎榜席位和风格(没上榜写"未上榜")
  "telegraph": 电报信号(没点名写"无点名"; 被点名要写是正面还是负面)
  "after_buy": 买入后情景树, 至少 2 条: [{"close": "今天收盘可能怎样", "next": "次日大概怎么走(引用分布)", "sell": "在哪 / 什么信号卖", "ref": "E 编号"}]
材料里确实没有就写"无数据", 不许跳过; 引用 ⚠负样本 的导师案例只能写在 "如果错了最可能错在哪", 不能当买入理由。
另在 json 顶层加 "market_risk": {"max_new": 本轮最多新开几只(整数), "max_single_pct": 单票最多几成仓, "why": "市况为什么要收紧(例: 弱市只做主板冲板确认)"} —— 只能比下面"05 机械风控"给的上限更紧, 不能更松。"""


def _eids(text):
    return set(re.findall(r"\bE(\d+)\b", text or ""))


def _neg_dates(material, code):
    """必查里这只票"导师同票"行标了 ⚠负样本 的日期(MM-DD)"""
    out = set()
    for l in (material or "").splitlines():
        if "导师同票" in l and "⚠负样本" in l:
            seg = l.split("导师同票", 1)[1]
            for m in re.finditer(r"(\d\d-\d\d) [买卖][^;|]*?⚠负样本", seg):
                out.add(m.group(1))
    if not out:
        return out
    # 只认属于这只票的那段必查(### 代码 名称 ... 到下一个 ###)
    blk = re.search(rf"### {code}\b[\s\S]*?(?=\n### |\Z)", material or "")
    if blk and "⚠负样本" not in blk.group(0):
        return set()
    return out


# ---------------- 10/24 步骤边界 v2 ----------------
# 必查条目名 → 类别(04 按类别回应, 不按 E 编号逐条; 北新一只就 17 条, 逐条会被糊弄)。名字按前缀匹配, 新加的必查条目没归类 → 落"其他"类(也要回应)
CATS = [("价位", ("关键价位", "触及概率")), ("近期规律", ("近期规律",)), ("导师", ("导师同票", "导师相似卖点", "导师卖点分位")),
        ("同形态", ("相似日", "同债近期路径", "强势股次日", "振幅分布")), ("题材", ("题材", "同逻辑·题材梯队", "同逻辑·历史样本")),
        ("龙虎榜", ("同逻辑·席位风格", "同逻辑·净卖", "同逻辑·龙虎榜", "同逻辑·主买游资后续", "同逻辑·邻居", "同逻辑邻居")),
        ("电报", ("电报点名", "同逻辑·监管筹码电报")), ("停牌", ("停牌状态",)),
        ("本体", ("本体事件",)), ("炸板回封", ("炸板回封",)), ("市况联动", ("市况联动",)), ("正股", ("正股状态",)),
        ("样例", ("全体导师同票样例", "同情境样例"))]   # 10/24 用户: 全体导师正负样例(含被排除的样例导师)   # 10/24 用户: 补上建议过的扩充
NOT_SUPPORT = {"价位", "停牌"}   # 只管挂价 / 能不能交易, 不算"该不该做"的证据
IMPACT = ("支持", "反对", "无关")
ATT = ("偏多", "中性", "偏空")
IDX_OK = {"sh000001", "sz399001", "sz399006", "sh000688", "sh000300", "sz399303"}


def _cat(name):
    for c, keys in CATS:
        if any(name.startswith(k) for k in keys):
            return c
    return "其他"


def blocks(material):
    """必查 → {代码: {"held": bool, "items": [(E号, 名称, 内容)], "text": 整段}}"""
    out = {}
    for m in re.finditer(r"^### (\d{6})([^\n]*)\n([\s\S]*?)(?=^### |\Z)", material or "", re.M):
        items = [(int(x.group(1)), x.group(2).strip(), x.group(3)) for x in re.finditer(r"^- E(\d+) ([^:：\n]+)[:：] ?(.*)$", m.group(3), re.M)]
        if items:
            out[m.group(1)] = {"held": "(持仓)" in m.group(2), "items": items, "text": m.group(3)}
    return out


def cats_of(material, code):
    """→ {类别: [E 编号]}"""
    b = blocks(material).get(code)
    if not b:
        return {}
    out = {}
    for e, name, _ in b["items"]:
        out.setdefault(_cat(name), []).append(f"E{e}")
    return out


def _pattern_listed(material, code):
    b = blocks(material).get(code)
    if not b:
        return False
    return any(name.startswith("近期规律") and not re.search(r"没有|查询失败|无分钟", txt) for _, name, txt in b["items"])


def req_checked(material):
    """给 04 的动态要求: 每只票要回应哪些类别(从这一轮材料自动解析)"""
    B = blocks(material)
    if not B:
        return ""
    rows = [f"  {c}{'(持仓)' if b['held'] else ''}: " + " / ".join(f"{k} {','.join(v)}" for k, v in cats_of(material, c).items()) for c, b in B.items()]
    return ("\n【怎么用必查(harness 指引)】做决定前, 把每只持仓、以及你打算 建 / 加 / 减 / 清 的票, 按下面列的类别逐类看一遍, 在这只票的 json 里写 \"checked\" —— "
            "目的是不漏看已有的材料(龙虎榜 / 电报 / 近期规律 / 市况联动 这些很容易被跳过):\n"
            "  每类一条 {\"E\": 编号, \"影响\": \"支持|反对|无关\", \"结论\": 一句话, 引用的数字照抄材料}; 是反对就再写 \"回应\": 为什么还这么做 / 怎么防; "
            "近期规律列出了形态时写清你的动作是顺着还是逆着它; 无关也写一句为什么无关。\n"
            "  **01 里标 ⚠不在能力圈 的强题材**: 在 json 顶层写 \"not_doing\": [{\"theme\": 题材, \"why\": \"不在能力圈|已见顶|样本不足|和导师规则冲突|其他\", \"note\": 一句}] —— 看到了、为什么不做。\n"
            "  **买入(建 / 加)前先看「样例」类**: 全体导师(今天的导师和被排除的样例导师都算)在这只票 / 同情境下的正负样例都是依据; 写出负样例几笔、最差一例是谁哪天亏多少, "
            "再写为什么还买 / 怎么防(仓位、止损、卖点)。不能只引正样例。\n"
            "  示例: \"checked\": {\"近期规律\": {\"E\": \"E3\", \"影响\": \"支持\", \"结论\": \"近 10 天尾盘常拉升(回测第二天 53%), 卖单放到 14:45 后\"}, "
            "\"市况联动\": {\"E\": \"E9\", \"影响\": \"反对\", \"结论\": \"小盘跌≥1% 的日子它收盘中位 -1.60%\", \"回应\": \"今天小盘已跌 3%, 只做半仓、跌破 255 走\"}, "
            "\"龙虎榜\": {\"E\": \"E6\", \"影响\": \"无关\", \"结论\": \"昨天未上榜\"}}\n各票必查类别:\n" + "\n".join(rows) + tg_reply_req(material))


def tg_named(material):
    """必查里有「电报点名」条目的票 → {代码: E 编号}"""
    out = {}
    for c, b in blocks(material).items():
        for e, name, _ in b["items"]:
            if name.startswith("电报点名"):
                out[c] = f"E{e}"
    return out


RULES_REQ = ("\n【考虑过的规则(harness 要求; 只记录, 不打回)】在 json 顶层写 \"rules_considered\": [{\"id\": \"规则编号(导师 R / A… 或 market-skill M / KD / KS / U)\", "
             "\"对哪只票\": \"代码或'全局'\", \"判断\": \"支持|反对|不适用\", \"一句\": \"为什么\"}] —— 带机械触发标签的和话术级的规则都要列; 列你这一轮真正想过的, 不用凑数")


DEFAULT_REQ = ("\n【默认动作(harness 要求; 只记录, 不打回; 10/25 用户批 B)】skill 规则最前面有「默认动作」(按今日开盘档 × 持仓状态, 导师最常做什么)。"
               "每只持仓 / 建加的票在 picks 里加 \"default\": {\"格\": \"开盘档 + 状态(例: 低开≤−3% · 被套 · 仓位<50%)\", \"默认\": \"该格默认动作\", \"偏离\": \"不偏离 | 偏离: 改成什么\", \"依据\": \"偏离时引用的窄规则编号(R / M / KS / U)\"}; "
               "偏离默认动作必须引用比默认动作更窄的规则, 写不出就照默认动作做")


def default_check(j):
    """→ {"n": picks 数, "missing": [没写 default 的], "deviate": [偏离的], "no_basis": [偏离但没引规则编号的]}(只记录)"""
    out = {"n": 0, "missing": [], "deviate": [], "no_basis": []}
    for p in ((j or {}).get("picks") or []) if isinstance(j, dict) else []:
        if not isinstance(p, dict):
            continue
        out["n"] += 1
        c = str(p.get("code"))
        d = p.get("default")
        if not isinstance(d, dict):
            out["missing"].append(c)
            continue
        if str(d.get("偏离") or "").startswith("偏离"):
            out["deviate"].append(c)
            if not re.search(r"(?<![A-Za-z])(R|M|KS|U)\d{1,3}(?!\d)", str(d.get("依据") or "")):
                out["no_basis"].append(c)
    return out


def rules_check(j, material):
    """→ {"n": 列了几条, "ids": [...], "bad": [材料里没有的编号], "mech_missing": [当前已机械触发却没列的]}(只记录)"""
    rc = (j or {}).get("rules_considered") if isinstance(j, dict) else None
    rc = rc if isinstance(rc, list) else []
    ids = [str(x.get("id")) for x in rc if isinstance(x, dict) and x.get("id")]
    have = set(re.findall(r"(?<![A-Za-z0-9])([A-Z]{1,2}\d{1,3})(?![0-9])", material or ""))
    bad = sorted({i for i in ids if i not in have})
    trig = set(re.findall(r"机械触发[^\n]{0,40}?((?:R|A|B|C)\d{1,3})", material or ""))
    return {"n": len(ids), "ids": ids[:40], "bad": bad[:20], "mech_missing": sorted(trig - set(ids))[:20]}


def tg_reply_req(material):
    """10/25 用户选 B: 被电报点名的票, 选不选都要回应 —— harness 要求写, 检查结果只记录不打回"""
    T = tg_named(material)
    if not T:
        return ""
    return ("\n【电报点名回应(harness 要求; 只记录, 不打回, 不拦单)】下面这些票今天被加红电报点名(必查「电报点名」有分类和这一类的历史分布), "
            "不管你选不选, 都在 json 顶层写 \"telegraph_reply\": [{\"code\": 代码, \"E\": 编号, \"选\": \"选|不选\", \"理由\": \"一句: 和这一类点名的历史分布是什么关系\"}]: "
            + "、".join(f"{c}({e})" for c, e in T.items()))


def tg_reply_check(j, material):
    """→ {"need": [...], "answered": [...], "missing": [...]}(只记录)"""
    T = tg_named(material)
    got = set()
    for x in ((j or {}).get("telegraph_reply") or []) if isinstance(j, dict) else []:
        if isinstance(x, dict) and str(x.get("code")) in T and str(x.get("理由") or "").strip():
            got.add(str(x.get("code")))
    return {"need": sorted(T), "answered": sorted(got), "missing": sorted(set(T) - got)}


def _nums(s):
    return [abs(float(x.replace("−", "-"))) for x in re.findall(r"[+\-−]?\d+(?:\.\d+)?(?=\s*%)", s or "")]


def _num_ok(x, text):
    pool = [abs(float(v.replace("−", "-"))) for v in re.findall(r"[+\-−]?\d+(?:\.\d+)?", text or "")]
    return any(abs(x - v) <= 0.06 or abs(x - v * 100) <= 0.6 for v in pool)


def gate_checked(p, material, held, ms=None):
    """04 一只票的 checked 覆盖 + 证据门槛 → 违规清单"""
    code, act = str(p.get("code")), p.get("action")
    if not (code in held or act in ("建", "加", "减", "清")):
        return []
    need = cats_of(material, code)
    if not need:
        return []
    ch = p.get("checked")
    if not isinstance(ch, dict):
        return [f"{code}: 缺 checked(要逐类回应: {' / '.join(need)})"]
    V, have = [], _eids(material)
    blk = blocks(material)[code]["text"]
    miss = [c for c in need if c not in ch]
    if miss:
        V.append(f"{code}: checked 缺类别 {' / '.join(miss)}")
    sup = 0
    for c, x in ch.items():
        if not isinstance(x, dict):
            V.append(f"{code}: checked.{c} 不是 {{E, 影响, 结论}}")
            continue
        imp = x.get("影响")
        if imp not in IMPACT:
            V.append(f"{code}: checked.{c}.影响 只能是 支持 / 反对 / 无关")
        ids = _eids(str(x.get("E", "")) + " " + str(x.get("结论", "")))
        if ids - have:
            V.append(f"{code}: checked.{c} 引用的 E{','.join(sorted(ids - have))} 不在材料里")
        if imp == "反对" and not str(x.get("回应") or "").strip():
            V.append(f"{code}: checked.{c} 是反对, 要写'回应'(为什么还这么做 / 怎么防)")
        bad = [n for n in _nums(str(x.get("结论", ""))) if not _num_ok(n, blk)]
        if bad:
            V.append(f"{code}: checked.{c} 结论里的 " + ", ".join(f"{b:g}%" for b in bad[:3]) + " 在这只票的必查里找不到(只许引用材料原数)")
        if imp == "支持" and c not in NOT_SUPPORT:
            sup += 1
    ms = ms or cfg()["min_support"]
    if act in ("建", "加") and sup < ms[act]:
        V.append(f"{code}: {act} 至少要 {ms[act]} 个类别'支持'(价位 / 停牌不算), 现在 {sup} 个 —— 证据不够就别{act}, 或写清还缺什么")
    if act in ("减", "清") and sup < ms[act]:
        V.append(f"{code}: {act} 至少要 {ms[act]} 个类别'支持'")
    if act in ("建", "加"):   # 10/24 用户: 买入前必须看负样例(今天的导师 + 样例导师都算), 防止只看正例觉得必赚
        nneg = sum(int(x) for x in re.findall(r"⚠负样例\((\d+)\)", blk))
        sm = ch.get("样例") if isinstance(ch.get("样例"), dict) else None
        if nneg and (not sm or not re.search(r"负", str(sm.get("结论", ""))) or not (str(sm.get("回应") or "").strip() or sm.get("影响") == "支持")):
            V.append(f"{code}: 必查里有 {nneg} 笔负样例(全体导师同票 / 同情境), {act}前要在 checked.样例 写出负样例笔数和最差一例, 再写为什么还买 / 怎么防")
    if _pattern_listed(material, code) and isinstance(ch.get("近期规律"), dict) and ch["近期规律"].get("影响") == "无关":
        V.append(f"{code}: 必查列出了近期规律, 不许写'无关' —— 写清你的动作顺着还是逆着它")
    return V


ASK02_V2 = """【02 市况】上面是今天的全部材料。只做一件事: 判断今天是什么样的日子、对打法意味着什么。**不要复述材料里的数字**(要用就写编号: E 编号 / 大小盘段编号 M大n·M小n), 不写和具体导师有关的内容。
方向(directions)要用材料里**有方向的来源**互相印证: 导师近 3 日实际买卖(逆向) / 发哥(看他的核销命中率) / UP 近 3 日定调 / 涨停分析 + 梯队 / 指数 K 线结构 / market-skill;
每个方向写清哪些来源支持(src)、哪些来源反对或没提(against), 来源之间打架时写你采纳哪边、为什么; 没有来源支持的方向不要写。来源标签用: 导师逆向 / 发哥 / 桃哥 / 天哥 / 卢本圆 / 涨停分析 / 梯队 / 指数K线 / M编号 / KD·KS编号。
最后 ```json {"attitude": "偏多|中性|偏空", "why": ["≤3 条, 每条一句 + 编号或来源标签, 如 '小盘开盘起单边走弱 M小1' / '上证跌回日线箱体下沿附近 指数K线'"], "directions": [{"theme": "题材", "ref": "编号", "src": ["支持的来源标签"], "against": "反对 / 没提的来源, 没有写'无'"}](≤3 个),
 "vs_mech": "大小盘路径 / 情绪数据的机械状态和你的判断不一致时写理由, 一致写'无'", "flip_if": [{"type": "index", "code": "sh000300|sz399303|sh000001|sz399006", "op": ">=|<=", "pct": 当日涨跌幅%, "why": "到这就要改判"}](1~3 条),
 "state": "一个词(给人看)", "horizon_days": N, "note": "≤300 字, 可空",
 "up_views": {"桃哥": "近 3 日(T−1/T−2/T−3)他对市况 / 方向的判断一句话 + 哪天说的; 都没提写'没提'", "卢本圆": "同上", "趋势天哥": "同上"}}
(10/25 用户: 三位 UP 每人都要写, 没提就写"没提", 不许空着; 你采纳 / 不采纳谁的看法写在 directions 的 src / against 里)"""


_TERMS = {}


def terms():
    """术语表 + 股票昵称表(scripts/live/glossary.yaml / stock_aliases.json / fage aliases)"""
    if "g" not in _TERMS:
        try:
            import yaml
            g = yaml.safe_load((ROOT / "scripts" / "live" / "glossary.yaml").read_text(encoding="utf-8")) or {}
        except Exception:   # noqa: BLE001
            g = {}
        al = {}
        for f in (ROOT / "scripts" / "live" / "stock_aliases.json", ROOT / "skills" / "fage-skill" / "persona" / "aliases.json"):
            try:
                al.update({k: v for k, v in json.loads(f.read_text(encoding="utf-8")).items() if not k.startswith("_") and isinstance(v, list)})
            except (OSError, ValueError):
                pass
        _TERMS["g"], _TERMS["al"] = g, al
    return _TERMS["g"], _TERMS["al"]


def glossary_text():
    """拼进系统提示的术语表(全部会话一样)"""
    g, _ = terms()
    if not g:
        return ""
    L = ["", "## 术语表(统一口径; 只用这里定义的词, 不自造同义词)"] + [f"- {r}" for r in g.get("rules") or []]
    for t in g.get("terms") or []:
        L.append(f"- **{t['term']}**: {t['def']}" + (f"(禁用: {'、'.join(t['ban'])})" if t.get("ban") else ""))
    return "\n".join(L)


def gate_terms(text):
    """股票简称 / 昵称、术语表禁用词 → 违规清单(指引模式只记录)"""
    g, al = terms()
    V = []
    t = text or ""
    for k, v in al.items():
        for m in re.finditer(re.escape(k), t):
            nxt = t[m.end(): m.end() + len(v[1]) - len(k)] if v[1].startswith(k) else ""
            if v[1].startswith(k) and v[1][len(k):] and nxt == v[1][len(k):]:
                continue   # 是全称的一部分(北新路桥 里的 北新)
            V.append(f"用了简称“{k}”, 要写全称 {v[1]}({v[0]})")
            break
    for tm in g.get("terms") or []:
        for b in tm.get("ban") or []:
            for m in re.finditer(re.escape(b), t):
                if tm["term"].startswith(b) and t[m.start(): m.start() + len(tm["term"])] == tm["term"]:
                    continue   # 是正式术语的一部分(一字板 里的 一字)
                V.append(f"用了“{b}”, 术语表口径是“{tm['term']}”")
                break
    return V


def gate_rebound(strategy):
    """10/27 晚用户批: 06 里写「反抽」的规则必须把四样写出来(起点 / 起算 / 结束 / 走强改判, 数值取 01 反抽卡), 否则记违规(指引模式只记录; 守卫 B 照常接管)
    判定: why 里出现「反抽」, 但没有同时出现 起点(最低) / 起算 / 结束(回落) / 改判(弱转强 / 走强) 中至少 3 样 → 违规"""
    V = []
    for c in (strategy or {}).get("codes") or []:
        for r in c.get("rules") or []:
            w = str(r.get("why") or "")
            if "反抽" not in w:
                continue
            got = [bool(re.search(k, w)) for k in (r"起点|最低", r"起算|进入反抽", r"结束|回落", r"改判|弱转强|走强")]
            if sum(got) < 3:
                miss = [n for n, g in zip(("起点", "起算", "结束", "走强改判"), got) if not g]
                V.append(f"{c.get('code')} {r.get('id')}: 写了「反抽」但没填 {'/'.join(miss)}(数值看 01 反抽卡)")
    return V


SRC02 = r"导师逆向|发哥|桃哥|天哥|卢本圆|涨停分析|梯队|指数\s*K\s*线|(?<![A-Za-z])M\d+|K[DS]\d+"


def gate02(j, prose, material):
    if not isinstance(j, dict):
        return ["02 没有 json"]
    V, have = [], _eids(material)
    segs = set(re.findall(r"\[(M[大小]\d+)\]", material or ""))
    if j.get("attitude") not in ATT:
        V.append("attitude 只能是 偏多 / 中性 / 偏空")
    why = j.get("why")
    if not isinstance(why, list) or not 1 <= len(why) <= 3:
        V.append("why 要 1~3 条")
    else:
        for w in why:
            ids, ms = _eids(str(w)), set(re.findall(r"M[大小]\d+", str(w)))
            if not ids and not ms and not re.search(SRC02, str(w)):   # 10/25: 方向证据包没有 E 编号, 来源标签也算出处
                V.append(f"why 这条没有编号: {str(w)[:30]}")
            bad = sorted({*(f"E{x}" for x in ids - have), *(ms - segs)})
            if bad:
                V.append(f"why 引用的编号不在材料里: {', '.join(bad)}")
    d = j.get("directions")
    if not isinstance(d, list) or len(d) > 3:
        V.append("directions 是列表, 最多 3 个")
    else:
        for x in d:
            if isinstance(x, dict) and not x.get("src"):
                V.append(f"方向 {x.get('theme')} 没写支持它的来源(src)")
    if not str(j.get("vs_mech") or "").strip():
        V.append("vs_mech 要写(一致写'无')")
    uv = j.get("up_views")
    if not isinstance(uv, dict) or any(not str(uv.get(k) or "").strip() for k in ("桃哥", "卢本圆", "趋势天哥")):
        V.append("up_views 要逐个写桃哥 / 卢本圆 / 趋势天哥近 3 日的判断(没提写'没提')")
    f = j.get("flip_if")
    if not isinstance(f, list) or not 1 <= len(f) <= 3:
        V.append("flip_if 要 1~3 条")
    else:
        for x in f:
            if not (isinstance(x, dict) and x.get("type") == "index" and x.get("code") in IDX_OK and x.get("op") in (">=", "<=") and isinstance(x.get("pct"), (int, float))):
                V.append("flip_if 这条代码判不了(要 type=index / code / op / pct 数字): " + json.dumps(x, ensure_ascii=False)[:60])
    # 10/24 用户: 先不要篇幅限制(02 备注 300 字的检查已删)
    return V


def gate03(j, material):
    if not isinstance(j, dict):
        return ["03 没有 json"]
    V, have = [], _eids(material)
    for side in ("bear", "bull"):
        s = j.get(side)
        args = s.get("args") if isinstance(s, dict) else None
        if not isinstance(args, list) or len(args) != 3:
            V.append(f"{side} 要恰好 3 条论点")
            continue
        for a in args:
            if not isinstance(a, dict) or not str(a.get("cite") or "").strip() or a.get("type") not in ("数据", "规则", "样本", "资金", "题材", "市况"):
                V.append(f"{side} 论点缺 cite 或 type 不在枚举里: " + json.dumps(a, ensure_ascii=False)[:50])
                continue
            if _eids(a["cite"]) - have:
                V.append(f"{side} 引用的 {a['cite']} 不在材料里")
            # 10/24 用户: 先不要篇幅限制(03 每条 40 字的检查已删)
        if not str((s or {}).get("reply_to_bull" if side == "bear" else "reply_to_bear") or "").strip():
            V.append(f"{side} 缺'对方最有力的一条, 我怎么回应'")
    if ("⚠负样本" in (material or "") or "最差" in (material or "")) and isinstance(j.get("bear"), dict):
        args = [a for a in j["bear"].get("args") or [] if isinstance(a, dict)]
        cites = " ".join(str(a.get("cite", "")) + str(a.get("claim", "")) for a in args)
        if not re.search(r"负样本|最差|P10", cites) and not any(a.get("type") == "样本" for a in args):
            V.append("材料里有负样本 / 最差情景, 空方至少要引一条(type=样本 或写明最差 / P10)")
    return V


def enforce06(s, j04, held, prev_codes=(), dry=False):
    """06 只能落 04 选中的票: 新开买(非持仓) 必须是 04 建 / 加 或上一版已有; 04 清仓的票不许买 → 剔掉违规规则, 返回剔除清单"""
    if not isinstance(s, dict) or not isinstance(j04, dict) or not isinstance(j04.get("picks"), list):
        return []   # 04 没出选票(json 缺) → 判不了越界, 不剔(否则会把 06 全剔光)
    act = {str(p.get("code")): p.get("action") for p in j04.get("picks") or [] if isinstance(p, dict)}
    dropped = []
    for x in s.get("codes") or []:
        c = str(x.get("code"))
        keep = []
        for r in x.get("rules") or []:
            bad = None
            if r.get("side") == "BUY":
                if c not in held and act.get(c) not in ("建", "加") and c not in prev_codes:
                    bad = "04 没选(建 / 加)"
                elif act.get(c) == "清":
                    bad = "04 判清仓"
            if bad:
                dropped.append(f"{c}:{r.get('id')}({bad})")
            if not bad or dry:
                keep.append(r)
        x["rules"] = keep
    if not dry:   # dry = 只报不剔(10/24 用户: 默认 warn)
        s["codes"] = [x for x in s.get("codes") or [] if x.get("rules") or str(x.get("code")) in held]
    return dropped


def gate04(j, prose, material, banned=None, held=(), need_rebut=False):
    """→ 违规清单(空 = 过)。j = 04 的 json; prose = 04 全文; material = 这一轮给模型的材料(启动消息 / 触发消息)"""
    if not isinstance(j, dict):
        return ["04 没有 json"]
    V = []
    have = _eids(material)
    for p in j.get("picks") or []:
        if not isinstance(p, dict):
            continue
        V += gate_checked(p, material, set(held))   # 10/24 步骤边界 v2: 持仓 + 建加减清 逐类回应 + 证据门槛
        if p.get("action") not in ("建", "加"):
            continue
        if need_rebut and not str(p.get("rebut") or "").strip():
            V.append(f"{p.get('code')}: 带 03 时 建 / 加 要写 rebut(空方最有力的那条, 你怎么回应)")
        code = str(p.get("code"))
        d = p.get("depth")
        if not isinstance(d, dict):
            V.append(f"{code}: 缺 depth(本票同形态 / 同逻辑邻居 / 龙虎榜 / 电报 / 买入后情景树)")
            continue
        for k in ("same_form", "peers", "lhb", "telegraph"):
            v = str(d.get(k) or "").strip()
            if not v:
                V.append(f"{code}: depth.{k} 空")
                continue
            ids = _eids(v)
            if ids - have:
                V.append(f"{code}: depth.{k} 引用的 E{','.join(sorted(ids - have))} 不在材料里")
            if not ids and not NO_DATA.search(v):
                V.append(f"{code}: depth.{k} 没有 E 编号也没写'无数据'")
        sf = str(d.get("same_form") or "")
        if sf and not NO_DATA.search(sf) and not re.search(r"最差|P10|最低|下沿|P25", sf):
            V.append(f"{code}: depth.same_form 只说了中位 / 好的一面, 要同时写最差或 P10")
        ab = d.get("after_buy")
        if not isinstance(ab, list) or len(ab) < 2:
            V.append(f"{code}: depth.after_buy 至少 2 条情景")
        else:
            for i, x in enumerate(ab):
                if not isinstance(x, dict) or not all(str(x.get(k) or "").strip() for k in ("close", "next", "sell")):
                    V.append(f"{code}: after_buy 第 {i + 1} 条缺 close / next / sell")
        negd = _neg_dates(material, code)
        why = " ".join(str(p.get(k) or "") for k in ("why", "play"))
        hit = [x for x in negd if x in why]
        if hit:
            V.append(f"{code}: 理由里引用了负样本({', '.join(sorted(hit))}), 只能写在'如果错了最可能错在哪'")
    if "⚠不在能力圈" in (material or "") and not isinstance(j.get("not_doing"), list):   # 10/24 用户 13:57: 能力圈外的强题材照样列, 04 写看到了为什么不做
        V.append("01 列了 ⚠不在能力圈 的强题材, 缺 not_doing(看到了、为什么不做)")
    if any(p.get("action") in ("建", "加") for p in j.get("picks") or []):
        mr = j.get("market_risk")
        if not isinstance(mr, dict) or mr.get("max_new") is None:
            V.append("缺 market_risk(本轮最多新开几只 / 单票几成 / 为什么)")
    for w in banned or cfg()["banned_words"]:
        for m in re.finditer(re.escape(w), prose or ""):
            sent = re.split(r"[。；;\n]", (prose or "")[max(0, m.start() - 60): m.end() + 60])
            s = next((x for x in sent if w in x), "")
            if not re.search(r"\d+(\.\d+)?\s*%|\b[MRET]\d+\b", s):   # 有百分比, 或在引用规则 / E 编号(如 "M4: 炸板次日收盘无脑接统计上为负")都算有出处
                V.append(f"用了'{w}'但同一句没有百分比或规则 / E 编号: …{s.strip()[:40]}…")
                break
    return V


def gate04_msg(V):
    return ("你的 04 没通过 harness 内容闸, 问题如下:\n- " + "\n- ".join(V[:15]) +
            "\n\n只做一件事: 按原来的判断补齐 / 改正, 输出同格式的完整最终 ```json(不要重新分析, 结论可以不变)。" + REQ04)


# ---------------- 05 机械风控 ----------------
_MC = {}
_TL = __import__("threading").local()   # 10/24: 连接按线程各一条(多本账多线程共用一条 pymysql 连接会 InterfaceError, must_extra 回放里撞过)


def _db():
    if getattr(_TL, "c", None) is None:
        import sys
        sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
        import manual_backfill as mb
        _TL.c = mb.db().cursor()
    return _TL.c


def mentor_pace(skill, D, windows=(5, 10, 20)):
    """导师近 N 个交易日(含空仓日 = 0): 日均买入票数(同一天同一只票算 1) + 单票最大仓位中位"""
    k = (skill, D, tuple(windows))
    if k in _MC:
        return _MC[k]
    c = _db()
    c.execute("select distinct trade_date from investment_market.kline_day where symbol='sh000001' and trade_date < %s order by trade_date desc limit %s", (D, max(windows)))
    days = [str(x[0]) for x in c.fetchall()]
    if not days:
        return None
    c.execute("select date(record_time), count(distinct stock_code) from investment_tool.tzzb_record where ledger=%s and record_type='bs_leg' and is_deleted=0 "
              "and side like '%%买%%' and date(record_time) >= %s and date(record_time) < %s group by 1", (skill, days[-1], D))
    buys = {str(d): n for d, n in c.fetchall()}
    out = {f"近{w}日日均买入票数": round(sum(buys.get(d, 0) for d in days[:w]) / max(1, len(days[:w])), 2) for w in windows}
    c.execute("select date(record_time), max(json_extract(payload_json, '$.position_percent')) from investment_tool.tzzb_record where ledger=%s and record_type='position_snap' "
              "and is_deleted=0 and stock_code not in ('SZRQ88','GC001','204001','131810') and date(record_time) >= %s and date(record_time) < %s group by 1", (skill, days[-1], D))
    mx = sorted(float(v or 0) * 100 for _, v in c.fetchall())
    out["近20日单票最大仓位中位%"] = round(mx[len(mx) // 2], 1) if mx else None
    _MC[k] = out
    return out


def mech05(line, D, state, nav_now, nav_open):
    """→ {"max_new", "pause_buy", "max_single_pct", "new_today", "text"}; 决策 T 线没有导师 = 不限新开(只有本线标的)"""
    R = cfg()["risk05"]
    held0 = set(((state.get("start") or {}).get("positions") or {}).keys())
    new_today = len({t["code"] for t in state.get("trades") or [] if t.get("side") == "BUY" and t.get("code") not in held0})
    pnl = (nav_now / nav_open - 1) * 100 if nav_open else 0.0
    pause = pnl <= float(R["daily_loss_pause_pct"])
    if line.get("kind") == "dt":
        return {"max_new": -1, "pause_buy": pause, "max_single_pct": 100, "new_today": new_today,
                "text": f"05 机械风控(决策 T 线): 今日盈亏 {pnl:+.2f}%{' ≤ 暂停线 → 暂停新买' if pause else ''}; 只做本线标的, 不限新开"}
    pace = mentor_pace(line["skill"], D, R["windows"]) or {}
    avg = max([v for k, v in pace.items() if k.startswith("近") and "买入" in k] or [0])
    cap_new = max(1, math.ceil(avg * float(R["new_open_mult"])))
    left = max(0, cap_new - new_today)
    sm = R["single_max_pct"]
    single = max(30.0, float(pace.get("近20日单票最大仓位中位%") or 30.0)) if sm == "auto" else float(sm)
    txt = (f"05 机械风控(硬闸, 执行器强制): 导师 {', '.join(f'{k} {v}' for k, v in pace.items())} → 今天新开票数上限 {cap_new}"
           f"(= 最大窗口日均 {avg} × {R['new_open_mult']}, 至少 1), 已新开 {new_today}, **本轮最多再新开 {left} 只**; "
           f"单票上限 {single:.0f}%; 今日盈亏 {pnl:+.2f}%" + (f" ≤ {R['daily_loss_pause_pct']}% → **暂停新买**(卖出不受限)" if pause else "") +
           "。04 的 market_risk 只能比这更紧。")
    return {"max_new": 0 if pause else left, "pause_buy": pause, "max_single_pct": single, "new_today": new_today, "text": txt}


def enforce05(s, m05, held, tighten=None):
    """06 落地后: 新开买单(持仓以外的票)只保留前 max_new 只; 暂停新买时全剔。→ 被剔清单"""
    if not isinstance(s, dict) or m05.get("max_new", -1) < 0 and not m05.get("pause_buy"):
        return []
    lim = m05["max_new"]
    if isinstance(tighten, dict) and isinstance(tighten.get("max_new"), int) and tighten["max_new"] >= 0:
        lim = min(lim, tighten["max_new"]) if lim >= 0 else tighten["max_new"]
    kept, dropped = [], []
    for x in s.get("codes") or []:
        c = str(x.get("code"))
        if c in held:
            continue
        if any(r.get("side") == "BUY" for r in x.get("rules") or []):
            if m05.get("pause_buy") or len(kept) >= lim:
                for r in x["rules"]:
                    if r.get("side") == "BUY":
                        dropped.append(f"{c}:{r.get('id')}")
                x["rules"] = [r for r in x["rules"] if r.get("side") != "BUY"]
            else:
                kept.append(c)
    return dropped


def _selftest():
    mat = "### 002307 北新路桥\n- E5 强势股次日: …\n- E7 导师同票: 导师做过 2 次: 10-14 买(连板接力) → ⚠负样本 10-15 卖出盈亏 -6.8%\n- E8 同逻辑·席位风格: 作手新一 …"
    good = {"picks": [{"code": "002307", "action": "建", "why": "首板次日排板 E5", "depth": {"same_form": "E5 中位 +6%, P10 −0.5%", "peers": "E8 作手新一次日中位 +6.9%", "lhb": "E8", "telegraph": "无点名",
                                                                                 "after_buy": [{"close": "封板", "next": "高开", "sell": "开盘冲高", "ref": "E5"}, {"close": "炸板", "next": "低开", "sell": "反抽", "ref": "E5"}]}}],
            "market_risk": {"max_new": 1, "max_single_pct": 20, "why": "弱市"}}
    assert gate04(good, "冲高中位 6%", mat) == [], gate04(good, "", mat)
    bad = json.loads(json.dumps(good))
    bad["picks"][0]["why"] = "照导师 10-14 的手法"
    bad["picks"][0]["depth"]["same_form"] = "E5 中位 +6%"
    bad["picks"][0]["depth"]["peers"] = "E99"
    del bad["market_risk"]
    V = gate04(bad, "大概率封板", mat)
    for k in ("负样本", "E99", "最差或 P10", "market_risk", "大概率"):
        assert any(k in v for v in V), (k, V)
    s = {"codes": [{"code": "600001", "rules": [{"id": "r1", "side": "BUY"}]}, {"code": "600002", "rules": [{"id": "r1", "side": "BUY"}]}, {"code": "002307", "rules": [{"id": "r1", "side": "SELL"}]}]}
    d = enforce05(s, {"max_new": 1, "pause_buy": False}, {"002307"})
    assert d == ["600002:r1"] and s["codes"][1]["rules"] == [], d
    d = enforce05(json.loads(json.dumps(s)), {"max_new": 5, "pause_buy": False}, set(), tighten={"max_new": 0})
    assert len(d) == 1, d
    print("harness 自测通过")


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _selftest()
    if len(sys.argv) > 2:
        print(mentor_pace(sys.argv[1], sys.argv[2]))
