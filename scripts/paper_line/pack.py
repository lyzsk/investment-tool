# -*- coding: utf-8 -*-
"""pack.py — paper v3 材料包(零 token): 启动时的第 1 条消息 + 盘中触发时的"必查结果"

第 1 条消息(09:00 启动, 经 stdin 给会话; 10/22 实测 --append-system-prompt-file 大文件没进上下文):
  开头 BOOT 暗号 → 本消息目录 → 本线说明 → skill 全文(每类索引在前、全文在后, 不设上限) → 本线记忆 → 导师 T−1 真实操作(拟人线)
  → 当天 + 前一天 md 全文 → 01 快层(账户 / 开盘实况 / 指数 / 候选池盘中特征 / 事实包) → 必查结果(E 编号, 06 引用用) → 资料目录(第二层怎么查)
盘中触发(trigger_msg): 01 快层(事实包没变就不重发) + 焦点票(持仓 + 当前策略里的票)的必查结果
必查项(10/22 晚 TODO 10.1, 脚本替模型查好, 模型不用"知道要查"):
  每只候选: 关键价位(上下各 3 个) · 导师同票历史 · 转债 = 相似日分布 / 股票 = 挂过的题材及阶段
  每只持仓: 再加 导师相似卖点(同浮盈 / 持有天数下 P(当天卖) 与卖法)
  决策T 线: 关键价位 + 近 30 日振幅分布(最高 / 最低相对昨收的分位)
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import line_dirs as LDS   # noqa: E402  10/25 账本目录命名(live_<skill> / paper_<id>)
V3 = ROOT / "scripts" / "paper_line"
sys.path[:0] = [str(V3 / "tools"), str(ROOT / "scripts" / "market"), str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "lib")]
MAX_CHECK = 20   # 10/24: 15 → 20(全量每只约 8KB; 其余用 ./q)
FULL_N = 99   # 10/24 用户: 必查全量(harness.yaml inputs.must_check_full_n 可改; 持仓永远全量)
_DAY = {}   # 10/24: 必查里一天内不变的项(只用 D 之前的数据)按 (项, 代码, 日[, 附加]) 缓存 —— 同一进程内盘中触发不重算, 数据一样都不少


def day_cached(key, fn):
    if key not in _DAY:
        _DAY[key] = fn()
    return _DAY[key]


def full_n():
    try:
        import harness as H
        return H.cfg().get("full_n", FULL_N)
    except Exception:   # noqa: BLE001
        return FULL_N
MEMDIR = V3 / "memory"   # 本线记忆(executor 收盘写; 桩测试换成临时目录)   # 必查的候选只数(候选池前 15; 持仓总是查)


def rd(p):
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def flag(name, default=""):
    """开关: 环境变量优先, 否则 chain_flags.txt(同 exec_base.flag 口径; pack 不 import exec_base 免得拖进整条 v2)"""
    import os
    if os.environ.get(name) is not None:
        return os.environ[name]
    for l in rd(ROOT / "scripts" / "claude_profile" / "chain_flags.txt").splitlines():
        k, _, v = l.split("#")[0].partition("=")
        if k.strip() == name:
            return v.strip()
    return default


def live_on():
    """10/24 用户定: 10/26 起跑实盘线(chain_flags.txt LIVE_LINE=1) —— 线按当天 selected_mentors.json 动态生成, 不再读 lines.json"""
    return flag("LIVE_LINE", "0") == "1"


_SEL = {}


def live_sel(D):
    """当天选人结果(mentor_select): 有就读; 没有 → 今天及以后现算并落盘, 过去的日子(回放)只现算不落盘"""
    import mentor_select as MS
    s = MS.load(D)
    if s is None:
        if D >= dt.date.today().isoformat():
            s = MS.write(D)
        else:   # 回放: 现算一次缓存在进程里(不落盘, 不碰 results/_live 的过去日子)
            if D not in _SEL:
                _SEL[D] = MS.select(D)
            s = _SEL[D]
    return s


def live_lines(D):
    """实盘线: 盘前名单(入选导师按排名 + 2 位 UP 桃哥 / 卢本圆; 趋势天哥只当市况参考)每人一条线; 线号 live_<skill>(不和 paper v3 同名账本串仓位); 全部盯盘模式"""
    import mentor_select as MS
    import skill_names as SN
    s = live_sel(D)
    out = {}
    for sid in s.get("premarket") or []:
        lid = f"live_{sid}"
        out[lid] = {"id": lid, "skill": sid, "kind": "mimic", "mode": "watch", "live": True, "role": "UP" if sid in MS.UPS else "导师", "name": SN.cn(sid),
                    "debate": (flag("LIVE_03", "1") or "1").strip() == "1"}   # 10/25 用户定: live line 跑 03(一次调用写空方 + 多方, PAPER_03_MODE=one); 竞价段不跑
    return out


def lines(D=None):
    if live_on():
        return live_lines(D or dt.date.today().isoformat())
    return {x["id"]: x for x in json.loads(rd(V3 / "lines.json"))["lines"]}


LIVE_EXCLUDE = {"601988"}   # 10/25 用户: 中国银行长期持有, 留下来的导师都不做它 → 不进 live line 账本、不让模型判断


def _real_from_table(t, f):
    """券商原表格式: 「导出时间 总资产 可用资金 …」下一行取可用; 「序 证券代码 证券名称 持仓数量 可用数量 成本价 …」各行取 持仓数量 > 0"""
    lines = t.splitlines()
    cash, pos = None, {}
    for i, l in enumerate(lines):
        if l.startswith("导出时间") and "可用资金" in l and i + 1 < len(lines):
            w = lines[i + 1].split()
            try:
                cash = float(w[3])   # 日期 时间 总资产 可用资金
            except (IndexError, ValueError):
                pass
        w = l.split()
        if len(w) >= 6 and w[0].isdigit() and len(w[0]) <= 3 and len(w[1]) == 6 and w[1].isdigit():
            try:
                q, cost = int(w[3]), float(w[5])
            except ValueError:
                continue
            if q > 0 and w[1] not in LIVE_EXCLUDE:
                pos[w[1]] = {"qty": q, "cost": cost, "name": w[2]}
    if cash is None:
        return None
    return {"cash": round(cash, 2), "positions": pos, "from": f.name[:10]}


def real_start(D):
    """10/25 用户令: live line 每条线开盘前拿到的持仓 = 用户此刻的真实持仓和仓位分布(隐私: 只在内存 / results(已 gitignore), 不进 git、不进 skill)
    读 scripts/dfcf/snapshots/<日>_成交_*.txt 里 D 之前最近一份的「资产 / 持仓(收盘)」行 → {"cash", "positions": {代码: {qty, cost}}, "from"}; 去掉 LIVE_EXCLUDE; 没有 → None"""
    snap = ROOT / "scripts" / "dfcf" / "snapshots"
    fs = sorted(f for f in snap.glob("20*_成交_*.txt") if f.name[:10] < D)
    for f in fs[::-1]:
        t = rd(f)
        m = re.search(r"^持仓\(收盘\)[:：](.*)$", t, re.M)
        if not m:
            tb = _real_from_table(t, f)   # 10/28: 10/27 那份是券商原表直接贴进来、没写「持仓(收盘)」行 → 原来会跳过退回 10/26 的持仓(4 条线拿错起点)
            if tb:
                return tb
            continue
        pos, cash = {}, 0.0
        for part in m.group(1).split(";"):
            part = part.strip()
            g = re.match(r"(\S+)\s+(\d{6})\s+(\d+)\s+成本\s+([\d.]+)", part)
            if g and g.group(2) not in LIVE_EXCLUDE and int(g.group(3)) > 0:
                pos[g.group(2)] = {"qty": int(g.group(3)), "cost": float(g.group(4)), "name": g.group(1)}
            gc = re.match(r"GC001\s+(\d+)\s*张\s*(\d+)", part)
            if gc:
                cash += float(gc.group(2))   # 国债逆回购 = 现金(次日到账)
        a_ = re.search(r"可用\s*([\d.]+)", t)
        cash += float(a_.group(1)) if a_ else 0.0
        return {"cash": round(cash, 2), "positions": pos, "from": f.name[:10]}
    return None


def keep_of(D):
    """今天留下的线(skill id 集合); None = 用户还没挑 → 按 LIVE_DEFAULT_KEEP(数字 = 入选导师前 N 位; all = 全部留下)"""
    s = live_sel(D)
    if s.get("keep") is not None:   # [] = 用户全部收束
        return set(s["keep"])
    v = (flag("LIVE_DEFAULT_KEEP", "3") or "3").strip()
    if v == "all":
        return set(s.get("premarket") or [])
    import mentor_select as MS
    return set([x for x in s.get("premarket") or [] if x not in MS.UPS][:int(v or 0)])


REPO_CODES = ("SZRQ88", "GC001", "204001", "131810", "888880", "131990")   # 逆回购 / 国标准券 = 现金, 不算仓位; 10/29: 补 888880 新标准券(刘忆青 10/29 58% 被当仓位 → 缩放算成 99.9%)/ 131990 标准券(悟到空方)


def mentor_pos_pct(skill, D):
    """导师 D 之前最近一次收盘持仓快照的总仓位(0~1, 去掉逆回购); 快照空仓 / 没有 → 近 20 个交易日每日总仓位的中位; 都没有 → None
    10/25 用户: live line 起点持仓按你的真实持仓结构、但总仓位等比例缩放到导师的仓位(防"仓位不同 → 走不同分支"的歧义)"""
    import manual_backfill as mb
    c = mb.db().cursor()
    c.execute("select date(record_time), stock_code, payload_json, stock_name from investment_tool.tzzb_record where record_type='position_snap' and is_deleted=0 and ledger=%s "
              "and record_time < %s and record_time >= date_sub(%s, interval 40 day) order by record_time", (skill, D, D))
    by = {}
    for d, code, pj, nm in c.fetchall():
        if str(code) in REPO_CODES or any(w in str(nm or "") for w in ("标准券", "逆回购", "回购")):   # 10/29: 名字兜底, 新出现的回购代码不再漏
            by.setdefault(str(d), 0.0)
            continue
        try:
            pp = float((json.loads(pj or "{}") or {}).get("position_percent") or 0)
        except ValueError:
            pp = 0.0
        by[str(d)] = by.get(str(d), 0.0) + pp
    if not by:
        return None
    last = by[max(by)]
    if last > 0.01:
        return min(1.0, last), f"导师 {max(by)} 收盘快照总仓位"
    xs = sorted(v for v in list(by.values())[-20:] if v > 0.01)
    return (min(1.0, xs[len(xs) // 2]), f"导师 {max(by)} 收盘空仓 → 用近 20 个快照日有仓日的中位") if xs else None


def keep_why(D, skill):
    """这条线为什么在 / 不在留下名单(10/25 用户: 要记录我什么时候把某个 skill 停了 → 晚上核销 / C 方案按"部分时段"算)"""
    s = live_sel(D)
    if s.get("keep") is None:
        return f"默认留下(LIVE_DEFAULT_KEEP={flag('LIVE_DEFAULT_KEEP', '3')}; 你 09:19 前没回「留下」)" + ("" if skill in keep_of(D) else ", 没排进默认")
    how = {"set": "只留", "add": "加回", "drop": "收束", "reset": "回到默认"}
    for x in (s.get("keep_log") or [])[::-1]:   # 最近一次改到这条线的操作
        if skill in (x.get("ids") or []) or x.get("how") in ("set", "reset"):
            return f"你{how.get(x.get('how'), x.get('how'))} {','.join(x.get('ids') or [])}({x.get('t', '')})"
    return "你挑的留下名单"


def md_path(D):
    return ROOT / "md" / f"{D[:4]}S{(int(D[5:7]) - 1) // 3 + 1}" / f"{D}.md"


def prev_day(D):
    import manual_backfill as mb
    c = mb.db().cursor()
    c.execute("use investment_market")
    c.execute("select max(trade_date) from kline_day where symbol='sh000001' and trade_date < %s", (D,))
    return str(c.fetchone()[0])


def skill_text(skill):
    """skill 全文: 每类先索引后全文(10/22 用户定: 索引放前面当目录, 不设上限)"""
    d = ROOT / "skills" / f"{skill}-skill"
    p = d / "persona"
    order = [("SKILL.md", d / "SKILL.md"), ("画像索引 profile_index.md", p / "profile_index.md"), ("规则索引 rules_index.md", p / "rules_index.md"),
             ("案例目录 cases_index.md", p / "cases_index.md"), ("画像 profile.md", p / "profile.md"), ("规则全文 rules.md", p / "rules.md"),
             ("案例全文 cases.md", p / "cases.md"), ("指纹 fingerprint.md", p / "fingerprint.md")]
    # 10/24: workflows/(chain.md 等)是旧 paper 链的流程指令, 不是数据, v3 / 实盘线用不到 → 不放(用户: 旧 paper 用不到的都可以去掉)
    parts = [(t, rd(f)) for t, f in order if f.exists()]
    return parts


# ---------------- 10/24 📋1 材料瘦身(按将来按 token 计费的方式省; harness.yaml inputs.slim 开关) ----------------
MD_KEEP = ("午评", "收评", "涨停分析", "涨停梯队")   # 这些节全留(前一天的; 午间涨停分析和收盘那份重复, 不留)
MD_DROP = ("午间涨停分析",)
MD_CAP = {"概况": 10**9, "_up": 10**9, "_mentor": 10**9, "_default": 10**9, "_pre": 10**9}   # 10/24 用户: T-1 日有大量预判, 复盘 / UP / 导师 / 盘前都不截断(只去掉午间涨停分析重复、龙虎榜只列前 8、电报改 ./q 查)
UP_HEADS = ("桃哥", "趋势天哥", "卢本圆")


def slim_on():
    try:
        import harness as H
        return bool(H.cfg().get("slim", True))
    except Exception:   # noqa: BLE001
        return True


def rules_brief(t):
    """规则全文 → 简表: 每条 ### R 只留标题 + 规则 / 方向 / 机械触发 / 消费提示 几行(各 ≤220 字); 去掉修订记录、验证状态等长段"""
    out, keep = [], False
    skip_sec = False
    lesson, has_hint = False, False   # 10/27 晚用户令: [教训] 规则简表里没有消费提示 / 警告时自动补一句「只提醒, 不是禁止」

    def _close():
        if lesson and not has_hint:
            out.append("- **消费提示**(自动补): [教训] = 他这类做法的结果偏差, 只提醒 / 降一档仓位, 不是禁止, 不能单独否决他本人会做的动作; 引用时写这类情境他本人做没做")
    for l in (t or "").splitlines():
        if l.startswith("## "):
            _close()
            lesson, keep = False, False
            skip_sec = "修订记录" in l or "核销" in l or "候选假设" in l
            if not skip_sec:
                out.append(l)
            continue
        if skip_sec:
            continue
        if l.startswith("### "):
            _close()
            out.append(l)
            keep = True
            lesson, has_hint = "教训" in l and "只提醒" not in l and "不是禁" not in l and "不给方向" not in l, False
            continue
        if keep and re.match(r"^- \*\*(规则|方向|机械触发|消费提示|触发|动作)\*\*", l):
            out.append(l[:220] + ("…" if len(l) > 220 else ""))
            has_hint = has_hint or l.startswith("- **消费提示**")
        elif keep and lesson and l.startswith("- **消费警告**"):   # [教训] 的消费警告也带上(原来简表丢了)
            out.append(l[:220] + ("…" if len(l) > 220 else ""))
            has_hint = True
    _close()
    return "\n".join(out) + "\n\n(简表: 每条规则的验证状态 / 样本 / 修订记录不常驻; 要全文用 ./q rule <skill> <R编号>)"


def md_digest(t, mentor_name=""):
    """前一天 md → 摘要(10/24 用户: 预判类全留不截断): 只去掉午间涨停分析(和收盘那份重复)、龙虎榜只列前 8 只(每只 ≤200 字, 其余 ./q 查)、加红电报不常驻(./q 查);
    按上级标题处理(丢弃节的子节一起丢)"""
    parts = re.split(r"(?m)^(#{2,4} [^\n]+)$", t or "")
    out = [parts[0][:500]]
    mine = re.sub(r"\s+", "", mentor_name or "")
    cur2 = cur3 = ""
    lhb_n = lhb_more = 0
    for i in range(1, len(parts) - 1, 2):
        h, body = parts[i], parts[i + 1]
        lv = len(h) - len(h.lstrip("#"))
        name = re.sub(r"^#+\s*", "", h).strip()
        key = re.sub(r"\s+", "", name)
        if lv == 2:
            cur2, cur3 = name, ""
        elif lv == 3:
            cur3 = name
        if any(k in cur2 for k in MD_DROP):
            continue
        if lv == 4 and "龙虎榜" in cur3:
            if lhb_n < 8:
                out.append(h + body[:200] + ("…" + chr(10) if len(body) > 200 else ""))
                lhb_n += 1
            else:
                lhb_more += 1
            continue
        if name in ("财联社早报", "红旗大街发哥", "盘前"):
            out.append(h + body[:MD_CAP["_pre"]] + ("…" + chr(10) if len(body) > MD_CAP["_pre"] else ""))
        elif any(k in cur2 for k in MD_KEEP) or any(k in name for k in MD_KEEP):
            out.append(h + body)
        elif name.startswith("加红电报"):   # 10/24 用户: 前一天电报大概率用不到(只用来核销"当天被点名的票次日难有好卖点"), 不放标题, 要查用 ./q
            n_ = sum(1 for x in body.splitlines() if x.strip()[:1] in ("-", "*", "【") or x.strip()[:1].isdigit())
            out.append(h + chr(10) + f"(共 {n_} 条, 不常驻; 要查用 ./q md <日> 加红电报。今天被点名的候选票必查里有「电报点名」, 规律见 telegraph-skill){chr(10)}")
        elif "概况" in name:
            out.append(h + body[:MD_CAP["概况"]] + (f"{chr(10)}…(截断; 全文 ./q md <日> 复盘){chr(10)}" if len(body) > MD_CAP["概况"] else ""))
        elif any(u in name for u in UP_HEADS):
            out.append(h + body[:MD_CAP["_up"]] + (f"{chr(10)}…(截断){chr(10)}" if len(body) > MD_CAP["_up"] else ""))
        elif lv == 4 and mine and mine in key:
            out.append(h + body)
        elif lv == 4:
            out.append(h + body[:MD_CAP["_mentor"]] + ("…" + chr(10) if len(body) > MD_CAP["_mentor"] else ""))
        else:
            out.append(h + body[:MD_CAP["_default"]] + (f"{chr(10)}…(截断){chr(10)}" if len(body) > MD_CAP["_default"] else ""))
    if lhb_more:
        out.append(f"{chr(10)}(龙虎榜另有 {lhb_more} 只没列; 全文 ./q md <日> 龙虎榜 或 ./q peers <代码> <D>){chr(10)}")
    return "".join(out)


def skill_text_slim(skill):
    """常驻版 skill: SKILL / 三个索引 / 画像 / 规则简表 / 指纹; 案例全文和工作流文档不常驻(./q cases / 资料目录)"""
    d = ROOT / "skills" / f"{skill}-skill"
    p = d / "persona"
    order = [("SKILL.md", d / "SKILL.md"), ("画像索引 profile_index.md", p / "profile_index.md"), ("规则索引 rules_index.md", p / "rules_index.md"),
             ("案例目录 cases_index.md", p / "cases_index.md"), ("画像 profile.md", p / "profile.md"), ("指纹 fingerprint.md", p / "fingerprint.md")]
    parts = [(t, rd(f)) for t, f in order if f.exists()]
    if (p / "rules.md").exists():
        parts.insert(5, ("规则简表(rules.md 每条只留规则 / 方向 / 触发; 全文 ./q rule)", rules_brief(rd(p / "rules.md"))))
    return parts


def mentor_t1(skill, D):
    """导师 T−1 真实操作(同花顺账本 tzzb_record; 23:10 拉取) —— 拟人线的"昨天他怎么做的" """
    import manual_backfill as mb
    p = prev_day(D)
    c = mb.db().cursor()
    c.execute("use investment_tool")
    c.execute("select record_time, stock_code, stock_name, side, price, qty from tzzb_record where record_type='bs_leg' and is_deleted=0 and ledger=%s "
              "and record_time >= %s and record_time < %s order by record_time", (skill, p, D))
    rows = c.fetchall()   # 逐笔腿: side = 买入 / 卖出 字面量, 有真实数量(trade 表的 side 是"操作类型"枚举 1 加仓 … 9 做T, 不是方向)
    L = [f"- {t:%H:%M:%S} {s} {n}({code}) {int(q or 0)} 股 @{float(px):g}" for t, code, n, s, px, q in rows]
    c.execute("select max(record_time) from tzzb_record where record_type='position_snap' and is_deleted=0 and ledger=%s and record_time < %s", (skill, D))
    ts = c.fetchone()[0]
    pos = ""
    if ts:   # 快照一票一行(同一时刻), position_percent = 占总资产比例(0~1)
        c.execute("select stock_code, stock_name, payload_json from tzzb_record where record_type='position_snap' and is_deleted=0 and ledger=%s and record_time=%s", (skill, ts))
        items = []
        for code, n, pj in c.fetchall():
            try:
                pp = float((json.loads(pj or "{}") or {}).get("position_percent") or 0)
            except ValueError:
                pp = 0
            if pp > 0:
                items.append(f"{n}({code}) {pp * 100:.0f}%")
        pos = f"\n收盘持仓快照({ts:%m-%d %H:%M}): {'、'.join(items) or '空仓'}"
    return f"导师 {p} 全部成交({len(rows)} 笔):\n" + ("\n".join(L) or "- 当天没有成交") + pos


def amp_stats(code, D, wins=(5, 15, 30, 60, 120)):
    """做 T 振幅分布(10/22 深夜用户定颗粒度 5 / 15 / 30 / 60 / 120 日): 每个窗口 最高相对昨收 / 最低相对昨收 / 日内振幅(高−低)/昨收 的 P25 / 中位 / P75
    短窗口看"最近变活跃还是变安静", 长窗口看常态(10/22 回测, bank-skill R7: 振幅宽度看 5~15 日更准, 挂价离昨收多远看 30~120 日更准)"""
    import manual_backfill as mb
    c = mb.db().cursor()
    c.execute("use investment_market")
    sym = ("sh" if code.startswith(("6", "5", "11")) else "sz") + code
    c.execute("select trade_date, high, low, close from kline_day where is_deleted=0 and symbol=%s and trade_date < %s order by trade_date desc limit %s", (sym, D, max(wins) + 1))
    k = [(str(d), float(h), float(l), float(cl)) for d, h, l, cl in c.fetchall()][::-1]
    if len(k) < 6:
        return "日线不足"
    q = lambda xs, p: round(sorted(xs)[min(len(xs) - 1, int(len(xs) * p))], 2)   # noqa: E731
    rows = []
    for n in wins:
        w = k[-(n + 1):]
        hi = [(w[i][1] / w[i - 1][3] - 1) * 100 for i in range(1, len(w))]
        lo = [(w[i][2] / w[i - 1][3] - 1) * 100 for i in range(1, len(w))]
        am = [(w[i][1] - w[i][2]) / w[i - 1][3] * 100 for i in range(1, len(w))]
        rows.append(f"近 {len(hi)} 日: 最高相对昨收 {q(hi, .25)} / {q(hi, .5)} / {q(hi, .75)}%; 最低相对昨收 {q(lo, .25)} / {q(lo, .5)} / {q(lo, .75)}%; "
                    f"日内振幅 {q(am, .25)} / {q(am, .5)} / {q(am, .75)}%(P25 / 中位 / P75)")
    rows.append("读法: 今天能走多宽看近 5~15 日的日内振幅; 高抛 / 低吸挂在昨收上下多远看近 30~120 日的最高 / 最低(回测更准); 只换窗口不改方向, 对称挂单扣费后照样亏")
    return chr(10) + chr(10).join("    " + r for r in rows)


def halt_status(code, D, now_hms=None):
    """停牌判断(10/23 凌晨用户问: 纳指 ETF 溢价高时常临时停牌 09:30~10:30, 能不能自动判断): 读当天 3 秒盘口最后一条;
    09:20 后仍然 现价 0 + 买卖五档全空 = 停牌(正常交易的票 09:15 起就有竞价虚拟撮合价)"""
    import datetime as _dt
    t = now_hms or _dt.datetime.now().strftime("%H:%M:%S")
    if t < "09:20:00":
        return "09:20 前还判断不了(竞价前段)"
    f = ROOT / "downloads" / "market" / D / "book_snap.jsonl"
    sym = ("sh" if code.startswith(("6", "5", "11")) else "sz") + code
    last = None
    try:
        with f.open(encoding="utf-8", errors="replace") as fh:
            for l in fh:
                if f'"{sym}"' in l:
                    last = l
    except OSError:
        return "没有今天的 3 秒盘口文件, 判断不了"
    if not last:
        return "3 秒盘口里没有这只票, 判断不了"
    r = json.loads(last)
    empty = not r.get("p") and not any((x or [0, 0])[0] for x in (r.get("b") or []) + (r.get("k") or []))
    return f"**疑似停牌**(截至 {r.get('t')} 现价 0、买卖五档全空; 溢价停牌通常 10:30 复牌, 复牌前挂单不会成交)" if empty else f"正常交易(截至 {r.get('t')} 现价 {r.get('p')})"


def _levels_line(code, D, px=None):
    import key_levels as K
    r = K.levels(code, D, px)
    if r.get("err"):
        return r["err"]
    up = "; ".join(f"{x['价']}({x['离现价%']:+}% {x['是什么'].split('[')[0]})" for x in r["上方(近→远)"][:3])
    dn = "; ".join(f"{x['价']}({x['离现价%']:+}% {x['是什么'].split('[')[0]})" for x in r["下方(近→远)"][:3])
    return f"现价 {r['现价']}({r['现价来源']}) | 上方: {up} | 下方: {dn}"


def _cb_similar():
    """10/23 修: 总控进程里 `import similar_days` 会先拿到 scripts/dfcf/paper/similar_days.py(市况相似日, 没有 query) → 转债相似日按文件路径导入, 不靠模块名"""
    m = sys.modules.get("cb_similar_days")
    if m is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("cb_similar_days", ROOT / "scripts" / "market" / "similar_days.py")
        m = importlib.util.module_from_spec(spec)
        sys.modules["cb_similar_days"] = m
        spec.loader.exec_module(m)
    return m


def _similar_line(code, D, gap=None):
    S = _cb_similar()
    r = S.query(code, D, gap)
    t = next((x for x in r["tiers"] if x["n"] >= S.MIN_N), r["tiers"][-1] if r["tiers"] else {})
    if not t or not t.get("n"):
        return "相似日样本 0"
    extra = " ".join(f"{k.split('内')[0].replace('开盘 ', '')}内最高中位 {v[0]}%(n={v[2]})" for k, v in t.items() if k.startswith("开盘 ") and ("5 分钟" in k or "15 分钟" in k))
    import dist_full as DF   # 10/24 用户令: 全分布(均值 / 中位 / P10~P90 / 最差 / 最好 + 案例)
    return (f"按 {'+'.join(t['按'])} n={t['n']}: 开盘后最高: {DF.line(t.get('开盘后最高 全分布'))}; 盘中最低: {DF.line(t.get('最低 全分布'))}; 收盘相对开盘: {DF.line(t.get('收盘相对开盘 全分布'))}; "
            f"收>开 {t.get('收>开 比例')}" + (f"; 竞价开盘中位 {t['竞价开盘 中位']}%" if "竞价开盘 中位" in t else "") + (f"; {extra}" if extra else ""))


def _same_line(skill, code):
    p = ROOT / "skills" / f"{skill}-skill" / "persona" / "cases_auto.jsonl"
    rows = [json.loads(l) for l in rd(p).splitlines() if l.strip()]
    rows = [r for r in rows if str(r.get("code")) == code and r.get("side") in ("买", "卖")]
    if not rows:
        return "导师没做过"
    b = [r for r in rows if r["side"] == "买"]
    s = [r for r in rows if r["side"] == "卖" and (r.get("result") or {}).get("pnl") is not None]
    avg = sum(r["result"]["pnl"] for r in s) / len(s) * 100 if s else None
    return f"导师做过 买 {len(b)} 次 / 卖 {len(s)} 次, 最近 {rows[-1]['date']}" + (f", 卖出平均盈亏 {avg:+.1f}%" if avg is not None else "")


def _theme_line(name, D):
    import theme_life as T
    r = T.by_stock(name, D)
    th = r.get("近 20 个交易日挂过的题材") or {}
    if not th:
        return "近 20 天没进过涨停分析"
    return "; ".join(f"{t}: {v['生命周期'].get('阶段')} 第 {v['生命周期'].get('本波第几天')} 天" for t, v in list(th.items())[:3])


T_BOOK = {"bank": ("A-dbank", "A-tbank", "A-hbank"), "nasdaq": ("A-dndq", "A-tndq", "A-hndq")}


def t_review(skill, D, n=5):
    """旧决策T(t_decide)近 n 天复盘: 每天 事后最优 T(t_review.py 用分钟线算的标签)+ 旧决策T 当天各时段决策和理由 + 机械T / 不T 结果 —— 带标签的真实样本(10/22 晚用户: 旧决策T 也是案例)"""
    names = T_BOOK.get(skill)
    if not names:
        return "(无)"
    fs = sorted(f for f in (ROOT / "scripts" / "dfcf" / "paper" / "t_log").glob("*.json") if f.stem < D)[-n:]
    L = []
    for f in fs:
        try:
            j = json.loads(rd(f))
        except ValueError:
            continue
        b = j.get("books") or {}
        d, t, h = (b.get(x) or {} for x in names)
        L.append(f"### {j.get('date')}")
        L.append(f"- {d.get('summary') or t.get('summary') or ''}")
        L.append(f"- 机械T 相对不T {t.get('vs_hold')} 元; 旧决策T 相对不T {d.get('vs_hold')} 元")
        for slot, x in (d.get("decisions") or {}).items():
            if isinstance(x, dict):
                L.append(f"  - 旧决策T {slot}: {x.get('action')} {x.get('tier', '')} —— {str(x.get('reason', ''))[:300]}")
    return chr(10).join(L) or "(还没有复盘记录)"


def market_rules():
    """10/23 用户批: 知识 skill market-skill 的规则全文(短, 进全部拟人线第一层); 缺了不拦启动"""
    t = rd(ROOT / "skills" / "market-skill" / "persona" / "rules.md")
    k = rd(ROOT / "skills" / "market-skill" / "persona" / "kline_rules.md")   # 10/25 原 kline-skill 并入: K 线定义 / 统计(06 后市看法的一环)
    u = rd(ROOT / "skills" / "market-skill" / "persona" / "user_found.md")   # 用户发现(假设)
    return "\n\n".join(x for x in (t or "(market-skill 规则文件缺)", k, u) if x)


_TG = {}


def clock_hms():
    """此刻 HH:MM:SS —— 执行器 / 回放的时钟(exec_base.now 回放时被换成虚拟时钟); 没加载执行器就用真实时间(10/25 修回放偷看)"""
    import datetime as _dt
    X_ = sys.modules.get("exec_base")
    return (X_.now() if X_ else _dt.datetime.now()).strftime("%H:%M:%S")


def telegraph_hits(D):
    """今天(到此刻)加红电报点名过的票 {代码: "HH:MM 电报摘要"}; 同一分钟内复用(md 盘中在更新)"""
    upto = clock_hms()[:5]
    key = (D, upto)
    if key not in _TG:
        out = {}
        try:
            sys.path.insert(0, str(ROOT / "scripts" / "test"))
            import telegraph_validate as TV
            if "names" not in _TG:
                _TG["names"] = TV.names(TV.db().cursor())
            bn, bc = _TG["names"]
            for t0, txt in TV.telegraphs(D):
                if t0 > upto:   # 10/25 修回放偷看: 只认此刻之前发的
                    continue
                for sym in TV.mentions(txt, bn, bc):
                    out.setdefault(sym[2:], f"{t0} {txt[:40]}")
        except Exception:   # noqa: BLE001
            pass
        _TG[key] = out
    return _TG[key]


def telegraph_links(D, upto="23:59:59"):
    """D 当天加红电报点名的票 → {代码: [(HH:MM:SS, 链接, 摘要)]}(只要 upto 之前发的; md「加红电报」节 markdown 链接; 盘前电报也算); 同一分钟复用"""
    import datetime as _dt
    key = ("tl", D, _dt.datetime.now().strftime("%H%M"))
    if key not in _TG:
        out = {}
        try:
            sys.path.insert(0, str(ROOT / "scripts" / "test"))
            import telegraph_validate as TV
            if "names" not in _TG:
                _TG["names"] = TV.names(TV.db().cursor())
            bn, bc = _TG["names"]
            m = re.search(r"\n## 加红电报\n(.*?)(?:\n## |\Z)", rd(md_path(D)), re.S)
            for d, t, txt, url in re.findall(r"^- \[(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d)\] \[(.*?)\]\((https?://[^)\s]+)\)", m.group(1) if m else "", re.M):
                if d != D:
                    continue
                for sym in TV.mentions(txt, bn, bc):
                    out.setdefault(sym[2:], []).append((t, url, txt[:40]))
        except Exception:   # noqa: BLE001
            pass
        _TG[key] = out
    return {c: [h for h in v if h[0] <= upto] for c, v in _TG[key].items() if any(h[0] <= upto for h in v)}


PRICE_ITEMS = ("关键价位", "触及概率", "导师相似卖点", "电报点名", "K线结构", "封板状态")   # 随价格 / 时刻变的项: 盘中触发每次重算重发; 其余一天不变, 盘前首跑发过就只引用编号


def must_check(line, D, codes, names, state, quotes=None, tags=None, ereg=None, seen=None, hot=None, fulln=None):
    """→ (文本, 条目数); 每项一个 E 编号, 06 用 "依据：E3" 引用
    10/24: tags = 必查范围(watch_set)每只票的来源标签(给了就不按 MAX_CHECK 截); ereg = 全天固定的 E 编号表 {(代码, 项名, 第几个): 编号};
           seen = 盘前首跑 / 之前已发过全量的票 —— 这些票只发 PRICE_ITEMS, 其余项写"见盘前首跑材料 E…"(数据还在会话里, 不重复发)"""
    L, n = [], 0
    ereg = {} if ereg is None else ereg
    quotes = quotes or {}
    held = state.get("positions") or {}
    skill = line["skill"]
    brief_n = 0
    allc = list(dict.fromkeys([*held, *codes]))
    for ci, c in enumerate(allc if tags else allc[:MAX_CHECK + len(held)]):
        nm = names.get(c, "")
        px = (quotes.get(c) or {}).get("p")
        items = []
        full = c in held or ci < (full_n() if fulln is None else fulln)   # 10/24 盘前首跑预算: fulln 可压低; 10/24 分层: 持仓 + 前 FULL_N 只全量(颗粒度最细), 其余简版(价位 / 规律 / 导师同票 / 题材 / 本体事件), 细节 ./q 自己查
        brief_n += 0 if full else 1
        try:
            items.append(("关键价位", _levels_line(c, D, px)))
        except Exception as e:   # noqa: BLE001
            items.append(("关键价位", f"查询失败 {e!r}"[:80]))
        if full and not c.startswith(("11", "12")):   # 10/25 用户: K 线进 06(日线 / 15 分钟段式箱体 + ATR + 近 60 日结构); 15 分钟随盘中变 → 每次触发重算
            try:
                import kline_struct as KS
                items.append(("K线结构", KS.line(c, D, px, at=clock_hms())))
            except Exception as e:   # noqa: BLE001
                items.append(("K线结构", f"查询失败 {e!r}"[:80]))
        try:   # 10/23 01:4x 用户批: 挂单今天触及概率(近 15 日日线, 相对昨收; 客观数, 06 挑价用)
            if not full:
                raise StopIteration
            import fill_prob as FP
            R_ = FP.hist(c, D)
            if R_:
                items.append(("触及概率(近 15 日, 相对昨收)", FP.ladder(c, D, R_[0][3])))
        except StopIteration:
            pass
        except Exception as e:   # noqa: BLE001
            items.append(("触及概率", f"查询失败 {e!r}"[:80]))
        try:   # 10/24 用户令: 近期规律由代码算成事实(澳弘尾盘拉升你看得出、模型看不出) —— 只列回测有预测力的形态 + 回测第二天出现率
            import pattern_scan as PS
            items += day_cached(("ps", c, D, full), lambda: PS.must_line(c, D, brief=not full))
        except Exception as e:   # noqa: BLE001
            items.append(("近期规律", f"查询失败 {e!r}"[:80]))
        try:   # 10/24 用户: 补上建议过的扩充 —— 本体事件 / 炸板回封 / 市况联动(大小盘大跌大涨日本票怎么走) / 转债的正股状态
            import must_extra as MX
            items += day_cached(("mx", c, D, full), lambda: MX.lines(c, D, detail=full, market=full))   # 全量: 本体 / 炸板回封 / 市况联动(9 组 + 13 档) / 正股; 简版: 只本体事件(转债: 正股状态)
        except Exception as e:   # noqa: BLE001
            items.append(("必查补充", f"查询失败 {e!r}"[:80]))
        if line["kind"] == "dt":
            items.append(("振幅分布", amp_stats(c, D)))
            if c.startswith(("5", "15", "16")):   # 跨境 ETF 溢价停牌
                items.append(("停牌状态", halt_status(c, D)))
        else:
            try:   # 10/24 用户: 全体导师(今天的导师 + 被排除的样例导师)同票 / 同情境的正负样例 —— 买入前必须看负样例, 防只看正例
                import samples as SMP
                items += day_cached(("smp", c, D), lambda: SMP.lines(c, D))
            except Exception as e:   # noqa: BLE001
                items.append(("全体导师同票样例", f"查询失败 {e!r}"[:80]))
            try:   # 10/24 用户令: 导师案例带 正 / 负 / 平 标签(芷影 10-14 海欣负样本被当成买入依据)
                import case_label as CL
                items.append(("导师同票", day_cached(("cl", skill, c, D), lambda: CL.summary(skill, c, D))))
            except Exception as e:   # noqa: BLE001
                items.append(("导师同票", _same_line(skill, c) + f"(标签查询失败 {e!r}"[:60] + ")"))
            try:
                if c.startswith(("11", "12")):
                    if full:
                        items.append(("相似日", day_cached(("sim", c, D), lambda: _similar_line(c, D))))
                else:
                    items.append(("题材", day_cached(("th", nm, D), lambda: _theme_line(nm, D))))
            except Exception as e:   # noqa: BLE001
                items.append(("相似日/题材", f"查询失败 {e!r}"[:80]))
            if not full:
                pass
            elif c.startswith(("11", "12")):   # 10/24 用户令: 同一只转债近 10 日开盘 / 尾盘路径(澳弘 10/20 和 10/23 开盘走法相似没被认出)
                try:
                    import cb_path as CP
                    items += day_cached(("cbp", c, D), lambda: CP.must_line(c, D))
                except Exception as e:   # noqa: BLE001
                    items.append(("同债近期路径", f"查询失败 {e!r}"[:80]))
            elif c[:1] in ("0", "3", "6"):   # 10/24 用户令: 同炒作逻辑的邻居(龙虎榜席位风格 / 同题材 / 梯队位置)
                try:
                    import peers as PR
                    items += day_cached(("pr", c, D), lambda: PR.must_line(c, D))
                except Exception as e:   # noqa: BLE001
                    items.append(("同逻辑邻居", f"查询失败 {e!r}"[:80]))
            if c[:1] in ("0", "3", "6"):   # 10/25 用户选 A: 电报点名按"电报说了这只票什么"分类 + 这一类的历史全分布 + 点名后开板那组数(只摆事实, 04 要回应, 不拦单)
                try:
                    import telegraph_now as TN
                    tgi = TN.item(c, D, clock_hms())
                except Exception as e:   # noqa: BLE001
                    tgi = None
                    tg = telegraph_hits(D).get(c)
                    if tg:
                        tgi = f"今天 {tg} …(分类统计取不到: {e!r})"[:300]
                if tgi:
                    items.append(("电报点名", tgi))
            if c[:1] in ("0", "3", "6") and (c in held or hot is None or c in hot):   # 10/25 用户批: 封板 / 开板 / 回封时给"当天"口径(北新路桥二封后按"次日"统计卖的教训)
                try:
                    sys.path.insert(0, str(ROOT / "scripts" / "live"))
                    import board_state as BS
                    bsi = BS.item(c, D, clock_hms())
                    if bsi:
                        items.append(("封板状态", bsi))
                except Exception as e:   # noqa: BLE001
                    items.append(("封板状态", f"查询失败 {e!r}"[:80]))
            if c in held and c[:1] in ("0", "3", "6") and clock_hms() >= "09:25:00":   # 10/26 用户点评: 竞价跌停被抢上来的水下票 ≠ 水上冲高, 各线都在开盘第一波就卖错了
                try:
                    sys.path.insert(0, str(ROOT / "scripts" / "live"))
                    import open_class as OC
                    oci = OC.item(c, D)
                    if oci:
                        items.append(("开盘情境", oci))
                except Exception as e:   # noqa: BLE001
                    items.append(("开盘情境", f"查询失败 {e!r}"[:80]))
            if full and c[:1] in ("0", "3", "6"):   # 10/22 晚用户批: 强势股次日溢价(strong_next) + 导师卖点分位(动态) 进必查
                try:
                    import strong_next as SN
                    items += day_cached(("sn", c, D, skill, c in held), lambda: SN.must_line(c, D, skill, held=c in held))
                except Exception as e:   # noqa: BLE001
                    items.append(("强势股次日", f"查询失败 {e!r}"[:80]))
        if c in held and line["kind"] == "mimic":
            p = held[c]
            cost = p.get("cost")
            ref = px or (quotes.get(c) or {}).get("p")
            if cost and ref:
                try:
                    import mentor_sells as M
                    days = int(p.get("days") or (0 if p.get("sellable", 0) < p.get("qty", 0) else 1))
                    r = M.query(skill, D, round((ref / cost - 1) * 100, 2), max(days, 1), None,
                                "cb" if c.startswith(("11", "12")) else "stock") if days >= 1 else M.query_intraday(skill, D)
                    sx = r.get("卖的那些次") or {}
                    ad = r.get("加仓 / 做T 的那些次")
                    items.append(("导师相似卖点", f"同状态当天卖出 {r.get('最像的这些日子里 当天卖出比例', '-')}; 卖出时段 {sx.get('卖出时段')}(**是分散在这些时段里卖, 不是开盘就卖**; 执行器按这个分布分批挂); "
                                              f"卖价相对开盘 {sx.get('卖价相对开盘 P25/中位/P75')}; 卖后 3 日最高 {sx.get('卖后: 3 日内最高相对卖价 中位 / ≥5% 比例')}; "
                                              f"**同状态当天加仓 {r.get('最像的这些日子里 当天加仓比例(含先买后卖做T)', '-')}**"
                                              + (f"(其中当天又卖 = 做T {ad.get('其中当天又卖(做T)')}/{ad.get('n')}; 加仓时段 {ad.get('加仓时段')}; 加仓价相对开盘 {ad.get('加仓价相对开盘 P25/中位/P75')})" if isinstance(ad, dict) else "")
                                  if "卖的那些次" in r or "最像的这些日子里 当天卖出比例" in r else json.dumps(r, ensure_ascii=False)[:300]))
                except Exception as e:   # noqa: BLE001
                    items.append(("导师相似卖点", f"查询失败 {e!r}"[:80]))
                try:   # 10/28 晚(C): 可复现的默认动作表 —— 票型 × 开盘档 × 赚亏, 动作含 加仓 / 做T, 三层(全期 / 近 20 日); 取代 R39 那张打板模板表
                    sys.path.insert(0, str(ROOT / "scripts" / "skills_ver"))
                    import default_table as DTB
                    op_ = (quotes.get(c) or {}).get("o") or ref
                    import auction_path as APX
                    pc_ = APX.prev_close(c, D)
                    pcx = pc_ or ref
                    cl = DTB.cell(skill, D, c, round((op_ / pcx - 1) * 100, 2) if op_ and pcx else 0.0, round((pcx / cost - 1) * 100, 2))
                    g1, g2 = cl.get("全期"), cl.get("近20日")
                    items.append(("导师默认动作(票型格)", f"格 = {cl['票型']} · {cl['开盘']} · {cl['赚亏']}(只按开盘那一刻能知道的算; 「昨封没封」只对连板票有意义, 已不用); "
                                                     f"全期 {json.dumps(g1, ensure_ascii=False) if g1 else '没有样本'}; 近 20 日 {json.dumps(g2, ensure_ascii=False) if g2 else '没有样本'} "
                                                     "—— 主动作按这格最大的那个(清 / 做T / 加 / 持); 做T / 加 占比不低时, 隔夜仓不是只能卖"))
                except Exception as e:   # noqa: BLE001
                    items.append(("导师默认动作(票型格)", f"查询失败 {e!r}"[:80]))
        L.append(f"### {c} {nm}{' (持仓)' if c in held else ''}" + (f" [来源: {' | '.join((tags or {}).get(c) or [])[:240]}]" if tags and tags.get(c) else ""))
        occ, skipped = {}, []
        for k, v in items:
            occ[k] = occ.get(k, 0) + 1
            eid = ereg.setdefault((c, k, occ[k]), len(ereg) + 1)
            if seen and c in seen and (not k.startswith(PRICE_ITEMS) or (hot is not None and c not in hot)):   # hot 外的已发票: 价位也不重发(10/24: 触发 109KB 太大)
                skipped.append(eid)
                continue
            n += 1
            L.append(f"- E{eid} {k}: {v}")
        if skipped:
            L.append(f"- (当天不变的 {len(skipped)} 项见盘前首跑材料: E{min(skipped)}~E{max(skipped)}, 编号全天固定)")
    if brief_n:
        L.append(f"(后面 {brief_n} 只是简版: 只有价位 / 近期规律 / 导师同票 / 题材 / 本体事件; 它们的完整必查一项不少都存着(E 编号相同): ./q must <代码> {line['id']}; 其他细节 ./q peers | pattern | events | like | cbpath | similar)")
    return "\n".join(L), n


INTRO = {
    "mimic": "本线是**拟人学习线**：用截至昨天的全部材料 + 导师昨天的真实操作，模仿导师今天会怎么做，并且要赚钱。今晚导师真人账本出来后会逐笔对比打分（拟人度要打赢'照导师昨天原样做'这个基线），同时看收益。",
    "dt": ("本线是**决策 T 线**：只交易下面给定的标的，先建底仓再做 T。对照组是同标的的机械 T（固定按 30 日振幅挂单）和不 T（只拿底仓）。"
           "**目标是降低持仓成本，不贪**：不追求每次吃大价差，**能成交优先**（挂价贴近买一 / 卖一，急的时候按卖二买），价差只要够来回费用 2 倍就做。"
           "常用场景：高开低走 → 开盘卖一部分底仓，回落到分时均价 / 昨收 / 支撑或尾盘接回；低开高走 → 开盘低吸、冲高卖；冲高回落 / 探底回升 / 区间震荡 → 高抛低吸；"
           "单边上涨日不做反 T（卖飞），只正 T 或不 T；单边下跌日先卖后买降成本，接回后再跌不连续摊低。"
           "**允许隔日 / 隔几日的 T**：今天卖了没接回 = 隔夜反 T，几天内低位接回；今天低吸多出 = 隔夜正 T，次日冲高卖（收盘股数可以和底仓不一样）。"
           "前几天还没完成的 T 写在「本线记忆」里，今天要接着处理。"),
}
INTRO_LIVE = ("本线是**实盘线**（用户真钱决策的参考，不是拟人考试）：按 {who} 的做法（能力圈 / 选票 / 买卖点 / 仓位节奏）找今天的机会，目标是**赚钱**；"
              "skill 里的教训和 market-skill 统计可以让你偏离导师原样，偏离要写依据（E / M 编号）。概率只能引用必查里代码算好的数，不要自己编。"
              "账本开盘时的持仓和现金 = 用户此刻的真实持仓和仓位分布（不含中国银行：用户长期持有、不用你判断），你要对这些持仓给出今天怎么处理（拿 / 减 / 做 T / 清），再考虑新开仓；"
              "单子进模拟账本机械撮合，晚上逐张核销（成交没有 / 没成交的原因 / 第二天结果）。"
              "盘前这一版就是今天的计划：用户看完会从几条线里留下几条，09:19 起只有留下的线还会被叫醒。")
INTRO_UP = "{who} 是 B 站 UP，没有同花顺逐笔账本：按他的复盘观点和 skill 规则（市况判断 / 主线 / 选股口径）决定今天怎么做，他在 md 日记里的小节是主要依据。"
MODE = {"watch": "盯盘模式。盘中触发方式：成交 / 价格出 band / 你写的 wake 失效条件命中 / 市况翻转 / 心跳 / 固定时刻(09:20 竞价复核、14:51 尾盘) 都会叫醒你，每次接着本会话想。",
        "plan": "计划模式。盘中触发方式：**只有计划失效才会叫醒你**——价格出了你写的 band，或你写的 wake 条件命中(时间止损 / 关键价破位 / 指数转弱)；另有固定时刻 09:20 竞价复核、14:51 尾盘。成交、心跳、市况翻转都不会叫醒你——所以条件单和 wake 要一次写全，覆盖涨跌两头。"}


def fee_note(line):
    """决策 T 线的费用门槛(10/22 深夜用户令: 1 万本钱下最低 5 元佣金占比不低, 要让模型把"价差不到来回费用 2 倍不做"当真)"""
    cash = float(line.get("cash") or 100000)
    stamp = 0.0 if any(c.startswith(("5", "15", "16")) for c in line.get("universe") or []) else 0.0005
    rows = []
    for frac, lab in ((0.15, "约 1/3 底仓"), (0.25, "约 1/2 底仓"), (0.5, "约全部底仓")):
        amt = cash * frac
        fee = max(5.0, amt * 0.00025) * 2 + amt * stamp
        rows.append(f"| {amt:.0f} 元（{lab}） | {fee:.2f} 元 | {fee / amt * 100:.2f}% | **{fee / amt * 200:.2f}%** |")
    nl = chr(10)
    return (f"**本账本钱只有 {cash:.0f} 元**（和旧决策T 同口径，方便对照）。佣金万 2.5、**每笔最低 5 元**" + ("、股票卖出印花税万 5" if stamp else "、ETF 免印花税") +
            "；小单的手续费占比很高。**规则：一次 T 的预期价差（高抛价 − 低吸价，相对价格）不到下表「2 倍门槛」就不做**；每条 T 单的 why 里写出「预期价差 x% vs 门槛 y%」。" + nl * 2 +
            "| 单笔金额 | 来回手续费 | 占比 | 2 倍门槛（最低价差） |" + nl + "|---|---|---|---|" + nl + nl.join(rows) + nl * 2 +
            "单笔越小门槛越高，所以要么等足够大的价差，要么用更大的档位；对照必查结果里的振幅分布判断今天够不够得着。" +
            (nl * 2 + "**纳指 ETF 溢价高时交易所会临时停牌（常见 09:30~10:30，10:30 复牌）**：停牌期间挂单不会成交，盘口为空；先看公告 / 开盘是否停牌，停牌日的 T 从复牌后算起，竞价单和开盘单要考虑停牌。" if not stamp else ""))


# ---------- 第一层补充(10/23 凌晨用户批: 导师近 20 日逐笔 + 仓位轨迹 / 情绪周期 / 活跃题材 / 昨日对照 / 土豆转债成交额) ----------
def trade_days(D, n):
    import manual_backfill as mb
    c = mb.db().cursor()
    c.execute("use investment_market")
    c.execute("select distinct trade_date from kline_day where symbol='sh000001' and trade_date < %s order by trade_date desc limit %s", (D, n))
    return sorted(str(x[0]) for x in c.fetchall())


def mentor_recent(skill, D, n=20):
    """导师近 n 个交易日全部逐笔(同花顺逐笔腿: 方向 / 股数 / 价)+ 每天收盘仓位快照(各票占总资产 %)"""
    import manual_backfill as mb
    days = trade_days(D, n)
    if not days:
        return "(无)"
    c = mb.db().cursor()
    c.execute("use investment_tool")
    c.execute("select date(record_time), time(record_time), stock_code, stock_name, side, price, qty from tzzb_record where record_type='bs_leg' and is_deleted=0 "
              "and ledger=%s and record_time >= %s and record_time < %s order by record_time", (skill, days[0], D))
    legs = {}
    for d, t, code, nm, sd, px, q in c.fetchall():
        legs.setdefault(str(d), []).append(f"{str(t).zfill(8)[:5]} {sd}{nm}({code}) {int(q or 0)}@{float(px):g}")
    c.execute("select date(record_time), stock_code, stock_name, payload_json from tzzb_record where record_type='position_snap' and is_deleted=0 and ledger=%s "
              "and record_time >= %s and record_time < %s", (skill, days[0], D))
    pos = {}
    for d, code, nm, pj in c.fetchall():
        try:
            pp = float((json.loads(pj or "{}") or {}).get("position_percent") or 0)
        except ValueError:
            pp = 0
        if pp > 0:
            pos.setdefault(str(d), []).append(f"{nm} {pp * 100:.0f}%")
    L = []
    for d in days:
        if d in legs or d in pos:
            L.append(f"- {d}: " + ("；".join(legs.get(d, [])) or "无成交") + f" ｜收盘仓位: {'、'.join(pos.get(d, [])) or '空仓 / 无快照'}")
        else:
            L.append(f"- {d}: 无成交、无快照")
    return chr(10).join(L)


def emotion_table(D, n=10):
    """近 n 个交易日情绪周期(从行情库日线现算; 涨停价按 昨收 × 10% / 创业科创 20% 推, 排除 ST / 北交所)"""
    import manual_backfill as mb
    days = trade_days(D, n + 1)
    if len(days) < 2:
        return "(无)"
    c = mb.db().cursor()
    c.execute("use investment_market")
    c.execute("select k.symbol, s.name, k.trade_date, k.high, k.low, k.close, k.pre_close from kline_day k join security_master s on s.symbol=k.symbol and s.sec_type='STOCK' "
              "where k.is_deleted=0 and k.trade_date >= %s and k.trade_date < %s and k.pre_close > 0", (days[0], D))
    by = {}
    for sym, nm, d, h, l, cl, pc in c.fetchall():
        if sym[:2] not in ("sh", "sz") or "ST" in (nm or "").upper() or sym[2:].startswith(("4", "8", "92")):
            continue
        lim = 0.2 if sym[2:].startswith(("300", "301", "688", "689")) else 0.1
        up, dn = round(float(pc) * (1 + lim) + 1e-9, 2), round(float(pc) * (1 - lim) + 1e-9, 2)
        by.setdefault(str(d), {})[sym] = (float(h) >= up - 0.005, float(cl) >= up - 0.005, float(cl) <= dn + 0.005, float(cl) / float(pc) - 1)
    rows = ["| 日期 | 涨停 | 跌停 | 炸板(摸板没封) | 炸板率 | 最高连板 | 连板晋级率 | 昨日涨停今日平均涨幅 |", "|---|---|---|---|---|---|---|---|"]
    streak = {}
    prev = None
    for d in days:
        x = by.get(d) or {}
        zt = {s for s, v in x.items() if v[1]}
        touch = sum(1 for v in x.values() if v[0])
        dt_ = sum(1 for v in x.values() if v[2])
        for s in list(streak):
            if s not in zt:
                streak.pop(s)
        for s in zt:
            streak[s] = streak.get(s, 0) + 1
        if prev is not None and d != days[0]:
            pz = prev
            prem = [x[s][3] for s in pz if s in x]
            jin = sum(1 for s in pz if s in zt)
            rows.append(f"| {d} | {len(zt)} | {dt_} | {touch - len(zt)} | {(touch - len(zt)) / touch * 100 if touch else 0:.0f}% | {max(streak.values()) if streak else 0} | "
                        f"{jin / len(pz) * 100 if pz else 0:.0f}% | {sum(prem) / len(prem) * 100 if prem else 0:+.2f}% |")
        prev = zt
    return chr(10).join(rows)


def theme_top(D):
    try:
        import theme_life as TL
        return chr(10).join("- " + x for x in TL.top(D)["近 5 日最活跃题材"])
    except Exception as e:   # noqa: BLE001
        return f"(题材统计取不到: {e!r})"[:120]


def vs_mentor_yesterday(line, D):
    """昨天(上一交易日)本线 paper 做了什么 vs 导师真人做了什么(拟人线最直接的学习信号; 第一天没有)"""
    import manual_backfill as mb
    days = trade_days(D, 1)
    if not days:
        return "(无)"
    p = days[-1]
    f = ROOT / "results" / "_live" / p / LDS.ldir(line["id"]) / "state.json"
    if not f.exists():
        return f"(上一交易日 {p} 本线还没有运行记录, 从下一个交易日起有)"
    st = json.loads(rd(f) or "{}")
    ours = [f"{t['t'][:5]} {t['side']} {t.get('name') or ''}({t['code']}) {t['qty']}@{t['px']}" for t in st.get("trades") or []]
    c = mb.db().cursor()
    c.execute("use investment_tool")
    c.execute("select time(record_time), stock_code, stock_name, side, price, qty from tzzb_record where record_type='bs_leg' and is_deleted=0 and ledger=%s "
              "and date(record_time)=%s order by record_time", (line["skill"], p))
    real = [f"{str(t).zfill(8)[:5]} {sd}{nm}({code}) {int(q or 0)}@{float(px):g}" for t, code, nm, sd, px, q in c.fetchall()]
    oc = {t["code"] for t in st.get("trades") or []}
    rc = {r.split("(")[1].split(")")[0] for r in real if "(" in r}
    return (f"上一交易日 {p}:\n- 本线 paper: {'；'.join(ours) or '无成交'}\n- 导师真人: {'；'.join(real) or '无成交'}\n"
            f"- 同票: {'、'.join(sorted(oc & rc)) or '无'}；只有我们做的: {'、'.join(sorted(oc - rc)) or '无'}；只有导师做的: {'、'.join(sorted(rc - oc)) or '无'}")


def cb_turnover_top(D, n_days=5, k=10):
    """近 n_days 个交易日全市场转债成交额前 k(土豆选债口径: 前一日全市场转债成交额第一)"""
    import manual_backfill as mb
    days = trade_days(D, n_days)
    c = mb.db().cursor()
    c.execute("use investment_market")
    L = []
    for d in days[::-1]:
        c.execute("select s.code, s.name, k.amount, k.close, k.pre_close from kline_day k join security_master s on s.symbol=k.symbol and s.sec_type='CB' "
                  "where k.is_deleted=0 and k.trade_date=%s order by k.amount desc limit %s", (d, k))
        L.append(f"- {d}: " + "；".join(f"{nm}({code}) {float(a) / 1e8:.1f} 亿 {(float(cl) / float(pc) - 1) * 100 if pc else 0:+.1f}%" for code, nm, a, cl, pc in c.fetchall()))
    return chr(10).join(L)


SHARED_HEAD = "[共享开头: 全市场 T−1 及以前的数据, 全部账本完全相同; 本线的材料在后面]"


# 10/25 用户: 周五 paper line 没压过 skill(skill 全文是导师本人的东西) → 先压必查只数, 实在放不下才动 skill(桃哥 skill 全文 1.9MB, 只能压)
BUDGET_STEPS = ["全量", "必查: 持仓 + 前 60 只全量, 其余简版", "必查: 持仓 + 前 30 只全量, 其余简版", "必查: 持仓 + 前 10 只全量, 其余简版", "skill 改常驻版(案例全文 / 工作流不常驻, 规则改简表)", "skill 单节 >60KB 改只给路径(Read / Grep 查全文)"]


def boot_budget_kb():
    """盘前首跑材料上限(KB; chain_flags.txt BOOT_MAX_KB: auto = 按历史算 / 数字 = 固定 / 0 = 不限)
    auto(10/24 用户: 参数尽量动态化): 上限 token = 上下文 CONTEXT_TOKENS × 0.95 − 近 5 个有记录交易日各会话"一天涨了多少"(收盘最大上下文 − 盘前首跑)的 P90;
    一天涨多少 = 保温轮(单次请求, 才是真实上下文)的上下文 − 盘前首跑估计, 按保温时刻外推到 14:51; 每 KB token = 盘前首跑那轮 ÷ 盘前首跑字节的 P25(盘前首跑轮有工具调用会累加偏大); 没历史 → 900"""
    v = (flag("BOOT_MAX_KB", "auto") or "auto").strip()
    if v != "auto":
        try:
            return float(v)
        except ValueError:
            return 900.0
    key = ("boot_budget", dt.date.today().isoformat())
    if key in _DAY:
        return _DAY[key]
    def tmin(hms):   # 09:00 起的交易分钟(去午休)
        h, m = int(hms[:2]), int(hms[3:5])
        x = (h - 9) * 60 + m
        return x - max(0, min(x, 240) - 150)
    rows, ratio = [], []
    for day in sorted({p.parent.parent.name for p in [*(ROOT / "results" / "_live").glob("20*/live_*/session.json"), *(ROOT / "results" / "_live").glob("20*/paper_*/session.json")]})[-5:]:
        for f in LDS.line_dirs(ROOT / "results" / "_live" / day, "session.json"):
            try:
                T = json.loads(rd(f)).get("turns") or []
                bm = sorted(f.parent.glob("versions/01_*/00_boot_msg.md"))
                if not T or not bm:
                    continue
                kb = bm[0].stat().st_size / 1024
                t0 = (T[0].get("cache_read") or 0) + (T[0].get("cache_write") or 0) + (T[0].get("in") or 0)
                if kb > 50 and t0:
                    ratio.append(t0 / kb)   # 盘前首跑那轮有工具调用时会偏大(一轮里多次请求累加), 下面取低分位
                # 真实上下文只有"保温"那轮可信(一句话、不调工具 = 单次请求); 一天的增长按保温时刻外推到 14:51
                K = [(t["t"], (t.get("cache_read") or 0) + (t.get("cache_write") or 0) + (t.get("in") or 0)) for t in T if t.get("round") == "keep"]
                K = [k for k in K if k[1] > 0 and tmin(k[0]) > 60]
                if K:
                    rows.append((kb, K[-1][1], tmin(K[-1][0])))
            except (OSError, ValueError, KeyError):
                continue
    ratio.sort()
    r25 = ratio[len(ratio) // 4] if ratio else 0
    grow = sorted(max(0.0, (ctx_ - kb * r25) * tmin("14:51") / m) for kb, ctx_, m in rows) if r25 else []
    if len(grow) < 3 or not ratio:
        _DAY[key] = 900.0
        return 900.0
    grow.sort()
    ratio.sort()
    g90, r50 = grow[int(0.9 * (len(grow) - 1))], r25
    ctx = float(flag("CONTEXT_TOKENS", "1000000") or 1000000)
    _DAY[key] = round(max(300.0, (ctx * 0.95 - g90) / r50))   # 下限 300KB: 再小连导师 skill 都放不下
    _DAY[("boot_budget_why", key[1])] = f"上下文 {ctx:.0f} × 0.95 − 一天增长 P90 {g90:.0f}(n={len(grow)}) = {ctx * 0.95 - g90:.0f} token ÷ {r50:.0f} token/KB"
    return _DAY[key]


def boot_msg(line, D, f01, P, names, state, round02, watch=None, ereg=None):
    """盘前首跑材料按预算逐级省(只动"怎么给", 数据都还能 Read / ./q 查到; 共享开头不动, 保证全部账本缓存共用): 0 全量 → 1 skill 常驻版 → 2 skill 大节只给路径 → 3/4/5 必查全量只数压到 60 / 30 / 10
    统计里 budget = {上限, 用到第几级, 每级大小}"""
    cap = boot_budget_kb()
    tried, cache = [], {}
    for lv in range(len(BUDGET_STEPS)):
        txt, st = _boot_msg(line, D, f01, P, names, state, round02, watch, ereg, lv, cache)
        tried.append(st["kb"])
        if not cap or st["kb"] <= cap or lv == len(BUDGET_STEPS) - 1:
            st["budget"] = {"cap_kb": cap, "level": lv, "step": BUDGET_STEPS[lv], "kb_by_level": tried, "why": _DAY.get(("boot_budget_why", dt.date.today().isoformat()), "")}
            if lv:
                txt = txt.replace("\n# 本消息目录\n", f"\n> 盘前首跑材料按上限 {cap:g}KB 省了: {'；'.join(BUDGET_STEPS[1:lv + 1])}。省掉的全文都还在: 简版票的完整必查(和全量一模一样, E 编号相同) ./q must <代码> {line['id']}; skill 原文 Read skills/{line['skill']}-skill/ 下文件, 规则 ./q rule; 其他细节 ./q levels / pattern / events / cases\n\n# 本消息目录\n", 1)
                st["kb"] = round(len(txt.encode()) / 1024, 1)
                if None in cache:   # 10/25 上下文第 ③ 招"分级进查询": 全量必查(lv0 算过的那份, E 编号一致)整份交给调用方落盘, 模型 ./q must 取回
                    st["must_full"] = cache[None][0]
            return txt, st


def _boot_msg(line, D, f01, P, names, state, round02, watch, ereg, lv, cache):
    """第 1 条消息全文 → (文本, 统计)
    10/24: ①共享开头: 前一天 md / 情绪周期 / 题材 / market-skill 放最前面(全部账本逐字相同 → 缓存只写一次, 其余账本按缓存价读), BOOT 暗号和本线材料在后面
           ②必查 = watch(必查范围, 带来源标签; 没给就按候选池前 MAX_CHECK), E 编号进 ereg(全天固定)"""
    tag = f"[BOOT {D} {line['id']} line]"
    slim = slim_on()   # 10/24 📋1: 瘦身(规则简表 / 不带案例全文和工作流 / 前一天 md 摘要); harness.yaml inputs.slim: false 可切回全量
    sk = skill_text_slim(line["skill"]) if slim or lv >= 4 else skill_text(line["skill"])
    if lv >= 5:
        sk = [(t, b if len(b.encode()) <= 60 * 1024 or "索引" in t or "目录" in t else f"(本节 {len(b.encode()) // 1024}KB 超出盘前首跑预算, 不常驻; 全文用 Read / Grep 查 skills/{line['skill']}-skill/ 下对应文件 —— 先看上面的索引找条目)") for t, b in sk]
    mem = rd(MEMDIR / f"{line['id']}.md") or "(第一天, 还没有记忆)"
    up = line.get("role") == "UP"
    t1 = "(UP 没有逐笔账本, 他的观点看 md 日记里他的小节)" if up else mentor_t1(line["skill"], D) if line["kind"] == "mimic" else "(决策 T 线不用)"
    pd_ = prev_day(D)
    mdD, mdP = rd(md_path(D)), rd(md_path(pd_))
    if slim:
        try:
            sys.path.insert(0, str(ROOT / "scripts" / "lib"))
            import mentors as MT
            mnm = (MT.get(line["skill"]) or {}).get("name", "") if line["kind"] == "mimic" else ""
        except Exception:   # noqa: BLE001
            mnm = ""
        mdP = md_digest(mdP, mnm)
    codes = [c for c in P] if line["kind"] == "mimic" else list(line.get("universe") or [])
    fulln = {1: 60, 2: 30, 3: 10, 4: 10, 5: 10}.get(lv)
    if fulln not in cache:   # 必查只在全量只数变了时重算
        if watch and line["kind"] == "mimic":
            cache[fulln] = must_check(line, D, list(watch), names, state, tags=watch, ereg=ereg, fulln=fulln)
        else:
            cache[fulln] = must_check(line, D, codes[:MAX_CHECK], names, state, ereg=ereg, fulln=fulln)
    chk, n = cache[fulln]
    shared = []   # 全部账本逐字相同的部分(只放 T−1 及以前、当天不变、和导师无关的)
    if line["kind"] == "mimic":
        shared = [(f"md 日记 {pd_}(前一个交易日{', 摘要: 全文 ./q md ' + pd_ + ' <小节名>' if slim else ''})", mdP),
                  ("近 10 日情绪周期(涨停 / 跌停 / 炸板率 / 最高连板 / 晋级率 / 昨日涨停溢价)", emotion_table(D)),
                  ("近 5 日最活跃题材及所处阶段", theme_top(D)),
                  ("盘面共性知识 market-skill(全市场统计规律, 没有人格; 导师规则决定做什么, 这里提醒哪些情况统计上容易亏; 要偏离导师就写依据的 M 编号)", market_rules())]
    cat = rd(V3 / "catalog" / "data_catalog.md")
    intro = (INTRO_LIVE + ("\n" + INTRO_UP if up else "")).format(who=line["name"] + "skill") if line.get("live") else INTRO[line["kind"]]
    secs = [("本线说明", f"{intro}\n{MODE[line['mode']]}" + (f"\n**只许交易：{'、'.join(line['universe'])}**" if line.get("universe") else "") + (chr(10) * 2 + fee_note(line) if line["kind"] == "dt" else "")),
            *[(f"skill · {t}", b) for t, b in sk],
            ("本线记忆(前几天决策摘要 + 复盘教训)", mem),
            ("导师 T−1 真实操作", t1),
            *([("导师近 20 个交易日全部逐笔 + 每天收盘仓位(看他最近的票池、节奏、仓位高低)", mentor_recent(line["skill"], D)),
               ("昨天本线 vs 导师真人(哪里像、哪里不像)", vs_mentor_yesterday(line, D))] if line["kind"] == "mimic" and not up else []),
            *([("近 5 个交易日全市场转债成交额前 10(土豆选债口径)", cb_turnover_top(D))] if line["skill"] == "buchitudou0" else []),
            *([("用户给本线的授权(优先于导师作息习惯, 不优先于风控)", rd(V3 / "line_notes" / f"{line['skill']}.md"))] if line.get("live") and (V3 / "line_notes" / f"{line['skill']}.md").exists() else []),   # 10/28 晚: 用户逐条线的授权 / 进化方向(scripts/paper_line/line_notes/<skill>.md)
            *([("做 T 知识包 t_knowledge.md(全体导师 T 法正反面 / 各 skill 做 T 规则 / 梅月路银行·ETF 专题 / 土豆竞价T)", rd(ROOT / "scripts" / "dfcf" / "paper" / "t_knowledge.md")),
               ("旧决策T 近 5 天复盘(当时怎么决策 vs 事后最优 T, 带标签的真实样本)", t_review(line["skill"], D))] if line["kind"] == "dt" else []),
            (f"md 日记 {D}(今天, 截至现在)", mdD or "(今天的 md 还没生成)"),
            *([] if shared else [(f"md 日记 {pd_}(前一个交易日)", mdP)]),
            ("01 快层(账户 / 开盘实况 / 指数 / 候选池 / 事实包)", f01),
            (f"必查结果(脚本已查好, 共 {n} 项; E 编号全天固定, 盘中触发只重发随价格变的项; 06 引用写 '依据：E编号')", chk),
            ("资料目录(第二层: 需要细节时自己查)", cat)]
    head = ""
    if shared:
        head = SHARED_HEAD + "\n\n" + "\n\n".join(f"# 共享 {i}. {t}\n\n{b}" for i, (t, b) in enumerate(shared, 1)) + "\n\n---\n\n"
    toc = "\n".join(f"{i}. {t}（{len(b.encode()) // 1024} KB）" for i, (t, b) in enumerate(secs, 1))
    body = "\n\n".join(f"# {i}. {t}\n\n{b}" for i, (t, b) in enumerate(secs, 1))
    txt = f"{head}{tag} 本线：{line['name']}｜交易日 {D}｜10 万元起步的模拟账本{'(上面是共享开头)' if shared else ''}\n\n# 本消息目录\n{toc}\n\n{body}\n\n---\n\n{round02}"
    return txt, {"kb": round(len(txt.encode()) / 1024, 1), "shared_kb": round(len(head.encode()) / 1024, 1),
                 "sections": {t: round(len(b.encode()) / 1024, 1) for t, b in shared + secs}, "checks": n}


def trigger_msg(line, D, f01, P, names, state, quotes, focus, ask, tags=None, ereg=None, seen=None, hot=None):
    chk, n = must_check(line, D, focus, names, state, quotes, tags=tags, ereg=ereg, seen=seen, hot=hot)
    return f"{f01}\n\n## 必查结果(必查范围, 共 {n} 项; E 编号全天固定 —— 盘前首跑发过的票只重发随价格变的项, 其余见盘前首跑材料)\n{chk}\n\n---\n\n{ask}", n


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ln = lines()[sys.argv[1] if len(sys.argv) > 1 else "tudou"]
    D = sys.argv[2] if len(sys.argv) > 2 else dt.date.today().isoformat()
    txt, st = boot_msg(ln, D, "(01 快层: 自测省略)", {}, {}, {"positions": {}}, "(02 提示: 自测省略)")
    print(json.dumps(st, ensure_ascii=False, indent=1))
