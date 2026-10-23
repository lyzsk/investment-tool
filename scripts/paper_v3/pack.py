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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V3 = ROOT / "scripts" / "paper_v3"
sys.path[:0] = [str(V3 / "tools"), str(ROOT / "scripts" / "market"), str(ROOT / "scripts" / "backfill_bilibili")]
MAX_CHECK = 15
MEMDIR = V3 / "memory"   # 本线记忆(executor 收盘写; 桩测试换成临时目录)   # 必查的候选只数(候选池前 15; 持仓总是查)


def rd(p):
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def lines():
    return {x["id"]: x for x in json.loads(rd(V3 / "lines.json"))["lines"]}


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
    order += [(f"工作流 {f.name}", f) for f in sorted((d / "workflows").glob("*.md"))]
    parts = [(t, rd(f)) for t, f in order if f.exists()]
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


def _similar_line(code, D, gap=None):
    import similar_days as S
    r = S.query(code, D, gap)
    t = next((x for x in r["tiers"] if x["n"] >= S.MIN_N), r["tiers"][-1] if r["tiers"] else {})
    if not t or not t.get("n"):
        return "相似日样本 0"
    extra = " ".join(f"{k.split('内')[0].replace('开盘 ', '')}内最高中位 {v[0]}%(n={v[2]})" for k, v in t.items() if k.startswith("开盘 ") and ("5 分钟" in k or "15 分钟" in k))
    return (f"按 {'+'.join(t['按'])} n={t['n']}: 开盘后最高 P25/P40/中位/P75 {t.get('开盘后最高 P25/P40/中位/P75')}%; 收盘相对开盘中位 {t.get('收盘相对开盘 中位')}%; "
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
    return t or "(market-skill 规则文件缺)"


_TG = {}


def telegraph_hits(D):
    """今天(到此刻)加红电报点名过的票 {代码: "HH:MM 电报摘要"}; 同一分钟内复用(md 盘中在更新)"""
    import datetime as _dt
    key = (D, _dt.datetime.now().strftime("%H%M"))
    if key not in _TG:
        out = {}
        try:
            sys.path.insert(0, str(ROOT / "scripts" / "test"))
            import telegraph_validate as TV
            if "names" not in _TG:
                _TG["names"] = TV.names(TV.db().cursor())
            bn, bc = _TG["names"]
            for t0, txt in TV.telegraphs(D):
                for sym in TV.mentions(txt, bn, bc):
                    out.setdefault(sym[2:], f"{t0} {txt[:40]}")
        except Exception:   # noqa: BLE001
            pass
        _TG[key] = out
    return _TG[key]


def must_check(line, D, codes, names, state, quotes=None):
    """→ (文本, 条目数); 每项一个 E 编号, 06 用 "依据：E3" 引用"""
    L, n = [], 0
    quotes = quotes or {}
    held = state.get("positions") or {}
    skill = line["skill"]
    for c in list(dict.fromkeys([*held, *codes]))[:MAX_CHECK + len(held)]:
        nm = names.get(c, "")
        px = (quotes.get(c) or {}).get("p")
        items = []
        try:
            items.append(("关键价位", _levels_line(c, D, px)))
        except Exception as e:   # noqa: BLE001
            items.append(("关键价位", f"查询失败 {e!r}"[:80]))
        try:   # 10/23 01:4x 用户批: 挂单今天触及概率(近 15 日日线, 相对昨收; 客观数, 06 挑价用)
            import fill_prob as FP
            R_ = FP.hist(c, D)
            if R_:
                items.append(("触及概率(近 15 日, 相对昨收)", FP.ladder(c, D, R_[0][3])))
        except Exception as e:   # noqa: BLE001
            items.append(("触及概率", f"查询失败 {e!r}"[:80]))
        if line["kind"] == "dt":
            items.append(("振幅分布", amp_stats(c, D)))
            if c.startswith(("5", "15", "16")):   # 跨境 ETF 溢价停牌
                items.append(("停牌状态", halt_status(c, D)))
        else:
            items.append(("导师同票", _same_line(skill, c)))
            try:
                items.append(("相似日", _similar_line(c, D)) if c.startswith(("11", "12")) else ("题材", _theme_line(nm, D)))
            except Exception as e:   # noqa: BLE001
                items.append(("相似日/题材", f"查询失败 {e!r}"[:80]))
            tg = telegraph_hits(D).get(c) if c[:1] in ("0", "3", "6") else None
            if tg:   # 10/23 用户批: 候选今天被加红电报点名 → 必查加一行(知识 skill telegraph-skill)
                items.append(("电报点名", f"今天 {tg} …; 历史: 点名后追进去次日平均亏(避雷), 点名时还没见顶的相对好 —— 见 telegraph-skill T1 / T2(./q 查 skills/telegraph-skill/persona/rules.md)"))
            if c[:1] in ("0", "3", "6"):   # 10/22 晚用户批: 强势股次日溢价(strong_next) + 导师卖点分位(动态) 进必查
                try:
                    import strong_next as SN
                    items += SN.must_line(c, D, skill, held=c in held)
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
                    items.append(("导师相似卖点", f"同状态当天卖出 {r.get('最像的这些日子里 当天卖出比例', '-')}; 卖出时段 {sx.get('卖出时段')}; "
                                              f"卖价相对开盘 {sx.get('卖价相对开盘 P25/中位/P75')}; 卖后 3 日最高 {sx.get('卖后: 3 日内最高相对卖价 中位 / ≥5% 比例')}"
                                  if "卖的那些次" in r or "最像的这些日子里 当天卖出比例" in r else json.dumps(r, ensure_ascii=False)[:300]))
                except Exception as e:   # noqa: BLE001
                    items.append(("导师相似卖点", f"查询失败 {e!r}"[:80]))
        L.append(f"### {c} {nm}{' (持仓)' if c in held else ''}")
        for k, v in items:
            n += 1
            L.append(f"- E{n} {k}: {v}")
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
    f = ROOT / "results" / "_live" / p / f"v3_{line['id']}" / "state.json"
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


def boot_msg(line, D, f01, P, names, state, round02):
    """第 1 条消息全文 → (文本, 统计)"""
    tag = f"[BOOT {D} {line['id']} v3]"
    sk = skill_text(line["skill"])
    mem = rd(MEMDIR / f"{line['id']}.md") or "(第一天, 还没有记忆)"
    t1 = mentor_t1(line["skill"], D) if line["kind"] == "mimic" else "(决策 T 线不用)"
    pd_ = prev_day(D)
    mdD, mdP = rd(md_path(D)), rd(md_path(pd_))
    codes = [c for c in P] if line["kind"] == "mimic" else list(line.get("universe") or [])
    chk, n = must_check(line, D, codes[:MAX_CHECK], names, state)
    cat = rd(V3 / "catalog" / "data_catalog.md")
    secs = [("本线说明", f"{INTRO[line['kind']]}\n{MODE[line['mode']]}" + (f"\n**只许交易：{'、'.join(line['universe'])}**" if line.get("universe") else "") + (chr(10) * 2 + fee_note(line) if line["kind"] == "dt" else "")),
            *[(f"skill · {t}", b) for t, b in sk],
            ("本线记忆(前几天决策摘要 + 复盘教训)", mem),
            ("导师 T−1 真实操作", t1),
            *([("导师近 20 个交易日全部逐笔 + 每天收盘仓位(看他最近的票池、节奏、仓位高低)", mentor_recent(line["skill"], D)),
               ("盘面共性知识 market-skill(全市场统计规律, 没有人格; 导师规则决定做什么, 这里提醒哪些情况统计上容易亏; 要偏离导师就写依据的 M 编号)", market_rules()),
               ("近 10 日情绪周期(涨停 / 跌停 / 炸板率 / 最高连板 / 晋级率 / 昨日涨停溢价)", emotion_table(D)),
               ("近 5 日最活跃题材及所处阶段", theme_top(D)),
               ("昨天本线 vs 导师真人(哪里像、哪里不像)", vs_mentor_yesterday(line, D))] if line["kind"] == "mimic" else []),
            *([("近 5 个交易日全市场转债成交额前 10(土豆选债口径)", cb_turnover_top(D))] if line["skill"] == "buchitudou0" else []),
            *([("做 T 知识包 t_knowledge.md(全体导师 T 法正反面 / 各 skill 做 T 规则 / 梅月路银行·ETF 专题 / 土豆竞价T)", rd(ROOT / "scripts" / "dfcf" / "paper" / "t_knowledge.md")),
               ("旧决策T 近 5 天复盘(当时怎么决策 vs 事后最优 T, 带标签的真实样本)", t_review(line["skill"], D))] if line["kind"] == "dt" else []),
            (f"md 日记 {D}(今天, 截至现在)", mdD or "(今天的 md 还没生成)"),
            (f"md 日记 {pd_}(前一个交易日)", mdP),
            ("01 快层(账户 / 开盘实况 / 指数 / 候选池 / 事实包)", f01),
            (f"必查结果(脚本已查好, 共 {n} 项; 06 引用写 '依据：E编号')", chk),
            ("资料目录(第二层: 需要细节时自己查)", cat)]
    toc = "\n".join(f"{i}. {t}（{len(b.encode()) // 1024} KB）" for i, (t, b) in enumerate(secs, 1))
    body = "\n\n".join(f"# {i}. {t}\n\n{b}" for i, (t, b) in enumerate(secs, 1))
    txt = f"{tag} 本线：{line['name']}｜交易日 {D}｜10 万元起步的模拟账本\n\n# 本消息目录\n{toc}\n\n{body}\n\n---\n\n{round02}"
    return txt, {"kb": round(len(txt.encode()) / 1024, 1), "sections": {t: round(len(b.encode()) / 1024, 1) for t, b in secs}, "checks": n}


def trigger_msg(line, D, f01, P, names, state, quotes, focus, ask):
    chk, n = must_check(line, D, focus, names, state, quotes)
    return f"{f01}\n\n## 必查结果(焦点票, 共 {n} 项; 编号本轮内有效)\n{chk}\n\n---\n\n{ask}", n


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ln = lines()[sys.argv[1] if len(sys.argv) > 1 else "tudou"]
    D = sys.argv[2] if len(sys.argv) > 2 else dt.date.today().isoformat()
    txt, st = boot_msg(ln, D, "(01 快层: 自测省略)", {}, {}, {"positions": {}}, "(02 提示: 自测省略)")
    print(json.dumps(st, ensure_ascii=False, indent=1))
