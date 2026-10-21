# -*- coding: utf-8 -*-
"""t_decide.py — 决策 T 账本(10/18 用户定: "做T 最考验学习所有 skill 的综合能力和对市场的评估能力"; 花 token)

账本: A-dbank 中国银行 601988 / A-dndq 纳指ETF 广发 159941(各 10 万)。同品种另有 机械T(A-tbank/A-tndq) 与 不T(A-hbank/A-hndq) 两本对照。
节奏(slot): 第 1 天 09:30 后按现价建 50% 底仓(同机械版, 便于对比), 当天不 T;
  之后每个交易日 4 次决策 + 1 次机械收口:
    0915  盘前定今天基调(隔夜外围 / 期货 / 各链市况; 做不做 / 正T 先买后卖 / 反T 先卖后买 / 规模档), 可挂集合竞价单
    0933  开盘后 3 分钟: 竞价结果 + 开盘走势已知, 改单 / 撤单 / 补单
    1033  上午复核
    1303  午后开盘复核
    1433  最后一次决策(之后 14:45 机械收口)
    1445  机械收口(不调模型): 卖了没买回=现价买回; 买了没卖掉=纳指 T+0 现价卖、银行 T+1 留隔夜次日处理
每次决策给模型的材料(全部内联, 模型不翻文件): 品种近 30 日振幅分布 / 当日行情快照(开高低现、均价) / 今日集合竞价过程 /
  当日各导师链 02 的市况与方向共识 / 账本状态(底仓、现金、挂单、今日成交) / 用户做 T 纪律 / 本品种 skill(skills/bank-skill 或 nasdaq-skill) /
  做 T 知识包(t_knowledge.md: 全体导师 T 法正反面 + 各 skill 做T 规则 + 梅月路同类标的 + 土豆竞价T) / 本账本近 5 天复盘
输出 JSON(驱动器校验: 价格在涨跌停内且在 ±2% 价格笼子内、数量按规模档且 100 股取整、银行卖量 ≤ 可卖底仓、买入不超现金) → plans 行 → matcher --import
进化: 收盘后 t_review.py 用分钟线算"事后最优 T"当标签, 和当天决策对齐写 t_log/<日>.json(下一天的"近 5 天复盘"就读这里)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/t_decide.py --tick [--date D] [--dry] [--force-slot 1000]
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import t_bot as TB          # noqa: E402  共用: kline/params/snap/write_import/lot/tick_px
import a_rules as AR        # noqa: E402

BOTS = {"A-dbank": {"code": "601988", "name": "中国银行", "t0": False, "skill": "bank"},      # 10/18 用户定: 沉淀成独立品种 skill(skills/bank-skill / nasdaq-skill)
        "A-dndq": {"code": "159941", "name": "纳指ETF(广发)", "t0": True, "skill": "nasdaq", "event": True, "close_at": "1450"},   # 10/20 晚用户批: 事件驱动(t_event.py) + 收口 14:50
        # 10/18 晚用户定: 实盘持仓牧原(私有 skill 放 snapshots/, 底仓=用户真实持股数; 用户清仓后自动停)
        "A-dmuyuan": {"code": "002714", "name": "牧原股份", "t0": False, "skill": "muyuan", "real": True,
                      "skill_dir": ROOT / "scripts" / "dfcf" / "snapshots" / "muyuan-skill"}}
SLOTS = ["0915", "0933", "1033", "1303", "1433"]   # 10/18 用户定: 0915 定基调 / 0933 开盘后 / 10:33 / 13:03 / 14:33, 14:45 机械收口
CLOSE_AT = "1445"
EVENT_ON = None   # 10/20 晚: 开关 T_EVENT(chain_flags.txt / 环境变量); 开 = 带 "event" 的账本只跑 0915 固定时段, 盘中决策交给 t_event.py 按事件 --force-slot 调


def _event(cfg):
    global EVENT_ON
    if EVENT_ON is None:
        EVENT_ON = _flag("T_EVENT", "0") == "1"
    return EVENT_ON and cfg.get("event")
DATA = TB.DATA
STATE = DATA / "t_decide_state.json"
TLOG = DATA / "t_log"

DISCIPLINE = """做 T 硬纪律(规则与费用口径, 必须遵守):
- 参数按该品种近 30 日振幅分布定, 禁止固定模板; 规模三档: 1/3 底仓、1/2 底仓、全部底仓(把握越大档越高, 不确定就 1/3 或不做)
- 按走势情景分配挂单(例: 高开冲高情景挂高抛、回落情景挂低吸), 单子要能放一段时间(用户隔段看盘), 不要贴着现价追
- 收盘股数可以浮动: 多出来的 = 隔夜正 T(次日处理); 少了的 14:45 会被机械买回
- 正T = 先买后卖(看日内反弹), 反T = 先卖后买(看日内回落); 银行 T+1: 当天买进的不能当天卖, 正T 的卖出要用底仓; 纳指 ETF 是 T+0
- 费用(用户券商实收): 每笔最低 5 元(不免五), 银行卖出另有印花税 0.05%; ETF 无印花税。本账本只用 1 万(底仓约 5000 元), 1/3 档一笔约 1500 元 → 单边约 0.33%、来回约 0.7%; 全档一笔约 5000 元 → 来回约 0.25%。预期价差 < 来回费用的 2 倍就别做, 小档位尤其要算"""


def consensus(D):
    d8 = D.replace("-", "")
    states, dirs, stances = {}, {}, {}
    for d in (ROOT / "results").glob("*_chain"):
        f = d / f"live-{d8}" / "02_analysis.md"
        if not f.exists():
            continue
        m = re.findall(r"```contract\s*\n([\s\S]*?)```", f.read_text(encoding="utf-8"))
        try:
            c = json.loads(m[-1])
        except (ValueError, IndexError):
            continue
        states[c.get("market_state")] = states.get(c.get("market_state"), 0) + 1
        stances[c.get("stance")] = stances.get(c.get("stance"), 0) + 1
        for x in c.get("directions") or []:
            k = re.split(r"[(（/·]", str(x))[0].strip()
            dirs[k] = dirs.get(k, 0) + 1
    top = lambda d: "; ".join(f"{k}×{v}" for k, v in sorted(d.items(), key=lambda x: -x[1])[:6]) or "(今天各链 02 还没出)"
    return f"市况: {top(states)}\n立场: {top(stances)}\n方向: {top(dirs)}"


def auction(D, code):
    try:
        A = json.loads((ROOT / "downloads" / "market" / D / "auction_live_open.json").read_text(encoding="utf-8"))
        s = (A.get("symbols") or {}).get(AR.symbol(code))
        if not s:
            return "(本品种不在今天竞价采集名单里)"
        sys.path.insert(0, str(ROOT / "scripts" / "lib"))
        return json.dumps({k: s.get(k) for k in ("p1", "p1_hi", "p1_lo", "p2_first", "p2", "fin", "vol_ratio", "tags")}, ensure_ascii=False)
    except (OSError, ValueError):
        return "(今天竞价过程未采到)"


def _flag(name, default=None):
    import decision_memory as DM   # 与驱动器同口径: 环境变量优先, 其次 chain_flags.txt
    v = DM.flag_raw(name)
    return default if v is None else v


def ctx_pack(code, D, slot):
    """10/19 用户定"索引化, 模型按需捞": 盘中资料索引(scripts/lib/ctx_index.py, 实盘 order-skill 共用); 失败不拖垮决策"""
    try:
        import ctx_index as CI
        before = None if slot == "0915" else (slot if slot.isdigit() else None)
        return CI.pack(code, D, before=before)
    except Exception as e:   # noqa: BLE001
        return f"(资料索引生成失败: {e})"


def facts_sections(D):
    """当天 0915 事实包里的 隔夜外围 + 期货 两节(纳指 ETF 主要看这个; 银行也看大盘情绪)"""
    try:
        t = (DATA / "facts" / D / "0915" / "facts.md").read_text(encoding="utf-8")
    except OSError:
        return "(今天 0915 事实包还没生成)"
    out = []
    for h in ("## 隔夜外围", "## 期货"):
        i = t.find(h)
        if i >= 0:
            j = t.find("\n## ", i + 3)
            out.append(t[i:j if j > 0 else i + 1500][:1500])
    return "\n".join(out) or "(事实包里没有外围 / 期货节)"


def skill_notes(sk, n_cases=10, skill_dir=None):
    """品种 skill: profile(手写逻辑 + 机械数据画像) + rules + 最近 n 张日卡(私有 skill 用 skill_dir)"""
    d = Path(skill_dir or ROOT / "skills" / f"{sk}-skill") / "persona"
    try:
        prof = (d / "profile.md").read_text(encoding="utf-8")
        rules = (d / "rules.md").read_text(encoding="utf-8")
        cases = (d / "cases.md").read_text(encoding="utf-8")
    except OSError:
        return f"({sk}-skill 缺)"
    cards = re.split(r"(?m)^(?=### 20\d\d-)", cases.split("<!-- CASES -->", 1)[-1])
    cards = [c.strip() for c in cards if c.strip().startswith("### 20")][:n_cases]   # 新卡在前
    return f"{prof.strip()}\n\n{rules.strip()}\n\n### 最近日卡\n" + ("\n\n".join(cards) or "(还没有日卡, 这是最初几天)")


def mentor_notes():
    """10/18 用户定: 不只学梅月路 → 读全体 skill 的做 T 知识包(t_knowledge.py 每晚重算); 缺了才退回梅月路专题"""
    try:
        return (HERE / "t_knowledge.md").read_text(encoding="utf-8")[:8000]
    except OSError:
        return _meiyuelu_notes()


def _meiyuelu_notes():
    try:
        t = (ROOT / "skills" / "meiyuelu-skill" / "persona" / "profile.md").read_text(encoding="utf-8")
        i = t.index("## 【专题: 银行股与ETF")
        j = t.find("\n## ", i + 5)
        return t[i:j if j > 0 else i + 4000][:3500]
    except (OSError, ValueError):
        return "(梅月路专题缺)"


def recent_reviews(src, D, n=5):
    out = []
    for f in sorted(TLOG.glob("*.json"), reverse=True):
        if f.stem >= D:
            continue
        try:
            r = (json.loads(f.read_text(encoding="utf-8")).get("books") or {}).get(src)
        except ValueError:
            continue
        if r:
            out.append(f"{f.stem}: {r.get('summary', '')}")
        if len(out) >= n:
            break
    return "\n".join(out) or "(还没有复盘记录, 这是最初几天)"


def book_state(src, code, D):
    b = TB.book(src)
    pos = int(((b.get("positions") or {}).get(code) or {}).get("qty") or 0)
    today = [t for t in b.get("trades") or [] if str(t.get("id", "")).startswith(D)]
    opens = [o for o in b.get("orders") or [] if o.get("status") == "open" and o.get("date") == D]
    bought_today = sum(int(t["qty"]) for t in today if t["side"] == "BUY")
    return b, pos, today, opens, bought_today


PROMPT = """你是做 T 交易员, 管理一个 paper 账本 {src}: 标的 {name}({code}), 底仓 {base} 股, 现在持仓 {pos}, 可用于做 T 的现金 {cash:.0f} 元。{scale}现在是 {D} {hm}(本次决策时段 {slot})。
目标: 通过日内高抛低吸让持仓成本下降 / 收益跑赢"底仓只拿着"; 不确定就不做(观望也是决策)。

## 品种近 30 日振幅(相对昨收): 最高涨幅中位 {up:.2%}, 最大跌幅中位 {dn:.2%}; 昨收 {prev}
## 当前行情: {quote}
## 今日集合竞价过程(9:15~9:20 可撤 / 9:20~9:25 不可撤 / 9:25 撮合): {auc}
## 今天各导师 paper 链 02 的市况共识:
{cons}
## 隔夜外围 / 期货(纳指 ETF 主要看美股和纳指期货; 注意 A 股白天美股已收盘, 场内价格跟期货和溢价走):
{ext}
## 盘中资料索引(10/19 起; ① 3 秒盘口走势 L0 ② 本时段最新事实包: 驱动器按本品种关键词预取的行 + 全文目录(带行号) ③ 结构 / 三态 ④ 最新外围期货; 先看"资料覆盖", ❌ 的项不要假设):
{idx}
## 账本: 今日已成交 {today}; 未成交挂单 {opens}
## {discipline}
## 本品种 skill(你的主要依据: 品种画像 + 做 T 规则 + 最近日卡):
{skill}
## 参考: 做 T 知识包(全体导师 T 法统计正反面 + 各 skill 做T 规则 + 梅月路同类标的手法 + 土豆竞价T):
{notes}
## 本账本近几天复盘(事后最优 T vs 当时决策):
{reviews}

{read_hint}只输出一个 ```json 块:
{{"action":"观望|正T|反T|改单|撤单","tier":"0|1/3|1/2|全","reason":"一两句, 说清依据哪些信号(竞价/市况/位置/量能)",
 "cancel_open": true/false,   // 是否撤掉现有未成交挂单(改单时设 true 再给新单)
 "orders":[{{"side":"BUY|SELL","price":数值,"frac":底仓比例(0~1),"why":"情景"}}],
 "plan":"如果到下个时段前出现什么情况, 你会怎么改(给下次决策的自己看)"}}"""


def validate(dec, code, prev, last, base, pos, cash, bought_today, t0):
    up_px, dn_px = AR.limit_prices(code, None, prev)[:2] if hasattr(AR, "limit_prices") else (prev * 1.1, prev * 0.9)
    lines, errs = [], []
    for o in dec.get("orders") or []:
        try:
            side, px, frac = str(o["side"]).upper(), float(o["price"]), float(o["frac"])
        except (KeyError, TypeError, ValueError):
            errs.append(f"坏单 {o}")
            continue
        if side not in ("BUY", "SELL") or not (0 < frac <= 1):
            errs.append(f"坏单 {o}")
            continue
        if up_px and px > up_px or dn_px and px < dn_px or (last and abs(px / last - 1) > 0.02):
            errs.append(f"价 {px} 出涨跌停或 ±2% 笼子(现价 {last})")
            continue
        q = TB.lot(code, base * frac)
        if side == "SELL":
            sellable = pos - (0 if t0 else bought_today)
            q = min(q, TB.lot(code, sellable))
        else:
            q = min(q, TB.lot(code, cash * 0.98 / px))
        if q <= 0:
            errs.append(f"{side} 数量为 0(可卖/现金不足)")
            continue
        lines.append((side, TB.tick_px(code, px), q, str(o.get("why") or "")[:40]))
    return lines, errs


def decide(src, cfg, D, slot, dry):
    from claude_call import call
    code = cfg["code"]
    b, pos, today, opens, bought = book_state(src, code, D)
    base = int(b.get("_t_base") or 0)
    P = TB.params(code, D)
    q = TB.snap(code) or {}
    last = float(q.get("last") or 0) if not q.get("stale") else 0.0
    vwap = (float(q["amt"]) / (float(q["vol"]) * (100 if not str(code).startswith("1") else 100))) if q.get("amt") and q.get("vol") else None
    quote = (f"开 {q.get('open')} 高 {q.get('high')} 低 {q.get('low')} 现 {q.get('last')} 涨跌 {q.get('pct')}%" + (f" 均价约 {vwap:.3f}" if vwap else "")) if last else "(未开盘/行情不是今天)"
    idx, can_read = ctx_pack(code, D, slot), _flag("T_DECIDE_READ", "1") == "1"
    read_hint = ("要细节可以用 Read 工具按上面目录的行号读原文(facts.md 某节 / 3 秒盘口 5 分钟K 用不了 Read, 不要读 book_snap); 最多 Read 3 次、每次 ≤80 行, 够用就别读。\n" if can_read else "")
    prompt = PROMPT.format(idx=idx, read_hint=read_hint, src=src, name=cfg["name"], code=code, base=base, pos=pos, cash=TB.t_cash(b, cfg), D=D, hm=dt.datetime.now().strftime("%H:%M"),
                           slot=slot, up=P["up"], dn=P["dn"], prev=P["prev"], quote=quote, auc=auction(D, code), cons=consensus(D), ext=facts_sections(D),
                           today=[(t["side"], t["price"], t["qty"]) for t in today] or "无", opens=[(o["id"], o["side"], o["price"], o["qty"]) for o in opens] or "无",
                           discipline=DISCIPLINE, scale=("本账本按用户实盘真实规模跑(底仓 = 用户真实持股数), 费用每笔最低 5 元在这个规模下影响较小; T 的规模按本品种 skill 规则的三档定(10/19 用户定: 决策T 学 skill 里的正负样本, 不模仿用户本人; 日卡里「你的实盘」那一行只是一条带盈亏的样本)。" if cfg.get("real") else "本账本只动 1 万(底仓约 5000 元), 小档位费用占比高。"), skill=skill_notes(cfg["skill"], skill_dir=cfg.get("skill_dir")), notes=mentor_notes(), reviews=recent_reviews(src, D))
    if dry:
        return {"slot": slot, "dry": True, "prompt_chars": len(prompt), "idx_chars": len(idx), "coverage": idx.splitlines()[0] if idx else ""}
    from claude_call import LEAN_ARGS
    r = call(prompt, tag=f"t-decide:{src}", permission="default", timeout=600, extra_args=LEAN_ARGS + ["--tools", "Read" if can_read else ""], json_tag="json")
    m = re.findall(r"```json\s*\n([\s\S]*?)```", r.result or "")
    try:
        dec = json.loads(m[-1]) if m else {}
    except ValueError:
        dec = {}
    rec = {"slot": slot, "at": dt.datetime.now().isoformat(timespec="seconds"), "cost": round(r.cost_usd or 0, 3), "decision": dec, "quote": quote,
           "coverage": idx.splitlines()[0] if idx else ""}
    if not dec:
        rec["error"] = f"模型输出解析失败 {r.errors[:2]}"
        return rec
    hm = dt.datetime.now().strftime("%H:%M")
    lines = []
    if dec.get("cancel_open") or dec.get("action") in ("撤单", "改单"):
        for o in opens:
            lines.append(f"- {hm} | {src} | CXL | {code} | - | - | - | - | oid={o['id']} | 决策T 撤单({slot})")
    vl, errs = validate(dec, code, P["prev"], last or P["prev"], base, pos, TB.t_cash(b, cfg), bought, cfg["t0"])
    for side, px, qty, why in vl:
        lines.append(f"- {hm} | {src} | {side} | {code} | {px:g} | {qty} | day | {last or P['prev']:g} | - | 决策T {dec.get('action')} {dec.get('tier')} {why}")
    rec["lines"], rec["rejected"] = lines, errs
    if lines:
        rc, msg = TB.write_import(D, src, lines)
        rec["import"] = {"rc": rc, "msg": msg}
    return rec


def tick(D, dry, force_slot=None, only=None):
    now = dt.datetime.now().strftime("%H%M")
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    sd = state.setdefault(D, {})
    out, touched = [], set()
    for src, cfg in BOTS.items():
        if only and src not in only:
            continue
        code, s = cfg["code"], sd.setdefault(src, {})
        touched.add(src)
        close_at = cfg.get("close_at", CLOSE_AT)
        slots = ["0915"] if _event(cfg) else SLOTS
        if cfg.get("real") and TB.real_follow(src, cfg, D, now, s, dry):   # 10/20: 先跟随用户实盘(清仓/加减仓), 跟随日 / 不持仓日不调模型
            continue
        b = TB.book(src)
        base = int(b.get("_t_base") or 0)
        pos = int(((b.get("positions") or {}).get(code) or {}).get("qty") or 0)
        if not base:   # 第 1 天: 同机械版建底仓 + 收盘记底仓
            if not s.get("base_order") and now >= "0930":
                q0 = TB.snap(code) or {}
                last = float(q0.get("last") or 0) if not q0.get("stale") else 0
                if last:
                    q = TB.base_qty(cfg, last, D)
                    line = f"- {now[:2]}:{now[2:]} | {src} | BUY | {code} | {TB.tick_px(code, last * 1.005):g} | {q} | day | {last:g} | - | 决策T 建底仓 50%"
                    if not dry:
                        s["base_order"] = {"at": now, "imp": TB.write_import(D, src, [line])}
                    out.append(f"{src} 建底仓: {line}")
                elif "0930" <= now <= "1500":
                    TB.FAILS.append(f"{src} 建底仓取不到 {code} 现价")   # 10/19: 不再静默(见 t_bot.snap 解析 bug)
            if s.get("base_order") and not s.get("base_set") and now >= close_at and pos:
                b["_t_base"] = pos
                if not dry:
                    (DATA / "books" / f"{src}.json").write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
                s["base_set"] = pos
                out.append(f"{src} 底仓记 {pos}")
            continue
        due = [x for x in slots if x <= now and x not in s] if not force_slot else [force_slot]
        if due and (now < close_at or force_slot):
            sl = due[-1]   # 只做最近一个到点的时段(错过的不补)
            for x in due:
                s.setdefault(x, {"skip": "过时"} if x != sl else None)
            rec = decide(src, cfg, D, sl, dry)
            s[sl] = rec
            out.append(f"{src} {sl}: {json.dumps(rec.get('decision') or rec, ensure_ascii=False)[:300]}")
        if now >= close_at and not s.get("close") and not force_slot:   # 机械收口(同 t_bot)
            q = TB.snap(code) or {}
            last = float(q.get("last") or 0) or TB.params(code, D)["prev"]
            lines = []
            if pos < base:
                lines.append(f"- {close_at[:2]}:{close_at[2:]} | {src} | BUY | {code} | {TB.tick_px(code, last * 1.01):g} | {base - pos} | day | {last:g} | - | 决策T 收口买回")
            elif pos > base and cfg["t0"]:
                lines.append(f"- {close_at[:2]}:{close_at[2:]} | {src} | SELL | {code} | {TB.tick_px(code, last * 0.99):g} | {pos - base} | day | {last:g} | - | 决策T 收口卖出多余(T+0)")
            s["close"] = {"at": now, "lines": lines}
            if lines and not dry:
                s["close"]["imp"] = TB.write_import(D, src, lines)
            out.append(f"{src} 收口: {lines or '无需'}")
    if not dry:   # 10/20 晚: t_event.py 事件触发(--only)和 check md 每 5 分钟的 tick 可能同时跑 → 写前重读, 只合并本次处理过的账本
        fresh = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
        fresh.setdefault(D, {}).update({k: sd[k] for k in touched})
        tmp = STATE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(fresh, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, STATE)
    print("\n".join(out) or f"{now} 无到点动作")
    if TB.FAILS and "0930" <= now <= "1500":
        print("ERROR: " + " | ".join(TB.FAILS))
        sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tick", action="store_true")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--force-slot")
    ap.add_argument("--only", help="逗号分隔账本, 如 A-dndq(t_event.py 事件触发时只跑这一本)")
    a = ap.parse_args()
    if a.tick:
        tick(a.date, a.dry, a.force_slot, set(a.only.split(",")) if a.only else None)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
