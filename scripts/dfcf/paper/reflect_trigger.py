# -*- coding: utf-8 -*-
"""reflect_trigger.py — 反思回注 FinCon 式触发(TODO 二B-6; 零 token, 只读; 2026-10-16 晚建)

出处: docs/research/ai_trading_frameworks_20261016.md 建议 11(FinCon arXiv 2407.06567: 按回撤触发自我批判、信念只定向下发给相关节点;
CLQT 记忆消融在噪声内 → 不常驻注入, 只在"持续偏离/回撤"时才注入, 且只注入执行参数 + case 提示, 不改画像/规则文件)。
每条链每个交易日 D 收盘后机械判一次, 结果写 scripts/dfcf/paper/reflection/<D>.json; 驱动器 run_chain.py 在
CHAIN_REFLECT_TRIGGER=1 时读"运行日之前最近一份"把触发链的 inject 原文拼进 04/06 prompt 末尾(未触发=不注入, 行为同现在)。

触发(阈值全在 params.yaml reflection_trigger 节):
  ① 拟人偏差(只 tzzb 导师链 + A-cb↔土豆; 口径复用 mimicry_score.py 的 Real/Chain/derive):
     在"配对日"(真人账本与链账本都有数据的交易日)上逐日判五个维度, 同一维度同一偏向连续 streak_days 个配对日 → 触发
       交不交易: 多动=真人没成交而链成交 / 少动=真人成交而链没成交
       方向    : 双方都成交且净方向(净加/不动/净减, mimicry EPS_DIR 口径)不同 → 偏多/偏空
       标的    : 双方足迹(收盘实质持仓∪当天买入)都非空, 市场板块(主板/创业/科创/北交/ST/ETF/转债)分布重合度 < board_min_overlap → 错位
       仓位    : |链收盘总仓 − 真人收盘总仓|(双方封顶 100%, 真人两融不算超配) > pos_gap → 偏重/偏轻
       时段    : 双方都成交且成交时段桶无交集(真人=逐笔成交时刻; 链=挂单 slot 近似) → 偏早/偏晚
     某维度当天无定义(如一方没成交时的方向/时段) = 当作"未偏离"。真人数据最新配对日落后 D 超过 max_lag_days 个交易日 → 拟人触发作废(数据陈旧)
  ② 回撤(全部链, 含 B站 UP/对照组): 近 dd_window 个交易日 峰值→D 回撤 ≤ dd_abs, 或 同窗收益 − 对照组同窗收益 ≤ dd_rel_ctrl → 当天即触发
  解除: 已触发项连续 release_days 个(配对日/交易日)不再满足 → 解除。状态机每次从 START 起重算(不依赖前几天的文件, 可任意日重跑)
注入内容(每链 ≤ max_cases 条 case, 与触发维度相关): 本链近 case_lookback_days 天 07 复盘里
  拟人对照(项=该维度且不一致) > lessons(case卡/错误归因/规则草案/规则修正, 含维度关键词) > 旧版 预案对照 的 误判/漏票 教训(含关键词)
用法:
  scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/reflect_trigger.py --date 2026-10-16
  scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/reflect_trigger.py --since 2026-10-08 --until 2026-10-16 --out-dir <目录>   # 回算
  scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/reflect_trigger.py --selftest
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "reflection"
RESULTS = ROOT / "results"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "chain"))
import mimicry_score as ms  # noqa: E402  Real/Chain/Prices/derive/overlap 同口径
from collect_lessons import contract_of  # noqa: E402  07 contract 解析同口径

DEFAULTS = {"streak_days": 3, "release_days": 2, "max_lag_days": 3, "pos_gap": 0.30, "board_min_overlap": 0.34,
            "dd_window": 5, "dd_abs": -0.05, "dd_rel_ctrl": -0.05, "dd_rel_real": -0.05, "dd_abs_trigger": False, "sys_rate": 0.5, "dd_size_factor": 0.5,
            "max_cases": 3, "case_lookback_days": 10, "stale_days": 10, "t_loss_streak": 3}
# 链清单: (skill=驱动器 SKILL_NAME, book, 真人 ledger 或 None)。与 run_chain.py SKILL_CFG source 同口径; 10/17 读导师登记表(tzzb 导师才有真人账本)
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import mentors  # noqa: E402
CHAINS = [(e["id"], e["book"], e["id"] if e["type"] == "tzzb" else None) for e in mentors.all()]
DIMS = ("交不交易", "方向", "标的", "仓位", "时段")
BUCKETS = ("竞价/开盘(≤09:35)", "上午", "午后(≤14:30)", "尾盘(>14:30)")
KW = {"交不交易": ("出手", "不动", "空仓", "观望", "开仓", "零腿", "不交易", "没动", "空过", "交不交易", "成交"),
      "方向": ("加仓", "减仓", "方向", "清仓", "净买", "净卖", "做多", "做空"),
      "标的": ("板块", "标的", "选股", "选票", "题材", "簇", "漏票", "能力圈", "赛道", "行业"),
      "仓位": ("仓位", "总仓", "满仓", "半仓", "轻仓", "重仓", "降仓", "成仓"),
      "时段": ("竞价", "开盘", "尾盘", "午后", "时段", "槽", "slot", "早盘", "盘中", "0927", "1455"),
      "回撤": ("止损", "亏", "回撤", "失效线", "跌停", "stop", "误判"),
      "T法": ("做T", "做 T", "正T", "倒T", "日内回转", "T 成绩", "回转")}   # 10/17 加


def params():
    p = dict(DEFAULTS)
    try:
        import yaml
        p.update((yaml.safe_load((HERE / "params.yaml").read_text(encoding="utf-8")) or {}).get("reflection_trigger") or {})
    except Exception as e:  # noqa: BLE001  缺 yaml/缺节=默认值
        print(f"WARN: params.yaml reflection_trigger 读取失败, 用默认值: {e}", file=sys.stderr)
    return p


def bucket(hm):
    """成交时段桶序号(与驱动器 _bucket 同口径)"""
    return 0 if hm <= "09:35" else 1 if hm <= "11:30" else 2 if hm <= "14:30" else 3


# ---------------- 纯函数(selftest 直接喂) ----------------
def deviations(rf, cf, rt, ct, p):
    """真人特征 rf / 链特征 cf(mimicry derive 产物) + 当日成交时段桶集合 rt/ct → {维度: (偏向, 说明)}; 未偏离/无定义=不出现"""
    out = {}
    if cf["trade"] != rf["trade"]:
        out["交不交易"] = ("多动", "导师没成交, 本链成交") if cf["trade"] else ("少动", "导师有成交, 本链没动")
    if rf["trade"] and cf["trade"] and rf["dir"] is not None and cf["dir"] is not None and rf["dir"] != cf["dir"]:
        nm = {1: "净加", 0: "不动", -1: "净减"}
        out["方向"] = ("偏多" if cf["dir"] > rf["dir"] else "偏空", f"本链{nm[cf['dir']]}/导师{nm[rf['dir']]}")
    if rf["foot_n"] and cf["foot_n"]:   # 市场板块(主板/创业/科创/北交/ST/ETF/转债)=风格层; 行业层逐日轮动且缓存覆盖不全, 回算几乎天天 0% 重合=不具选择性, 不用
        ov = ms.overlap(cf["boards"], rf["boards"])
        if ov is not None and ov < p["board_min_overlap"]:
            out["标的"] = ("错位", f"板块重合 {ov:.0%}: 本链 {_top(cf['boards'])} / 导师 {_top(rf['boards'])}")
    ctp, rtp = min(cf["tp"], 1.0), min(rf["tp"], 1.0)   # 真人两融可 >100%, 链不能加杠杆: 按满仓封顶比
    if abs(ctp - rtp) > p["pos_gap"]:
        out["仓位"] = ("偏重" if ctp > rtp else "偏轻", f"收盘总仓 本链 {cf['tp']:.0%} / 导师 {rf['tp']:.0%}")
    if rt and ct and not (set(rt) & set(ct)):
        out["时段"] = ("偏早" if min(ct) < min(rt) else "偏晚",
                       f"本链 {'、'.join(BUCKETS[i] for i in sorted(set(ct)))} / 导师 {'、'.join(BUCKETS[i] for i in sorted(set(rt)))}")
    return out


def _top(counter, k=2):
    n = sum(counter.values())
    return "、".join(f"{a} {b / n:.0%}" for a, b in counter.most_common(k)) if n else "无"


def walk(days_dev, streak_n, release_n):
    """days_dev=[(日期, {键: 说明})] 按日升序(键=维度·偏向) → 末日状态 {键: {active, since, streak, clear, days:[(日, 说明)]}}
    键当天出现=偏离: streak+1, clear=0; 未出现: streak=0, 已触发的 clear+1, clear≥release_n 解除"""
    st = {}
    for d, dev in days_dev:
        for k in set(st) | set(dev):
            s = st.setdefault(k, {"active": False, "since": None, "streak": 0, "clear": 0, "days": []})
            if k in dev:
                s["streak"] += 1
                s["clear"] = 0
                s["days"] = (s["days"] + [(d, dev[k])])[-max(streak_n, 5):]
                if not s["active"] and s["streak"] >= streak_n:
                    s["active"], s["since"] = True, d
            else:
                s["streak"] = 0
                if s["active"]:
                    s["clear"] += 1
                    if s["clear"] >= release_n:
                        s.update(active=False, since=None, clear=0)
    return st


def drawdown(navs, ctrl_navs, p):
    """navs/ctrl_navs = 窗口内按日升序的 [(日, nav)](含基期, 末=D) → (是否越线, 指标 dict)"""
    if len(navs) < 2:
        return False, {}
    vals = [v for _, v in navs]
    dd = vals[-1] / max(vals) - 1
    r = vals[-1] / vals[0] - 1
    m = {"dd": round(dd, 4), "ret": round(r, 4), "base": navs[0][0], "n": len(navs) - 1}
    hit = dd <= p["dd_abs"]
    if ctrl_navs and len(ctrl_navs) >= 2:
        rc = ctrl_navs[-1][1] / ctrl_navs[0][1] - 1
        m.update(ctrl_ret=round(rc, 4), rel=round(r - rc, 4), ctrl_base=ctrl_navs[0][0])
        hit = hit or (r - rc) <= p["dd_rel_ctrl"]
    return hit, m


def real_window_ret(ledger, d0, d1):
    """导师真人同窗收益(tzzb nav_daily, d0→d1 两端净值; 缺=None)"""
    try:
        il = json.loads((ROOT / "downloads" / "tzzb" / ledger / "nav_daily.json").read_text(encoding="utf-8"))["ex_data"]["index_list"]
        nav = {str(x["date"]): float(x["index"]) for x in il if float(x.get("index") or 0) > 0}
        a, b = nav.get(d0.replace("-", "")), nav.get(d1.replace("-", ""))
        return (b / a - 1) if a and b else None
    except Exception:   # noqa: BLE001
        return None


def cap_systemic(res, D, p, results=RESULTS):
    """10/18 审计④ R5③(用户批): 某一维度在全体链里触发率 > sys_rate(50%) = 系统性偏差(驱动器约束层的事), 不再逐链注入, 只记录"""
    rows = res["chains"]
    n = len(rows) or 1
    cnt = {}
    for r in rows.values():
        for dm in {t["key"].split("·")[0] for t in (r.get("triggers") or [])}:
            cnt[dm] = cnt.get(dm, 0) + 1
    sysd = sorted(dm for dm, c in cnt.items() if c / n > p.get("sys_rate", 0.5) and dm != "T法")
    res["systemic"] = {dm: f"{cnt[dm]}/{n}" for dm in sysd}
    if not sysd:
        return res
    for skill, r in rows.items():
        keep = [t for t in (r.get("triggers") or []) if t["key"].split("·")[0] not in sysd]
        if len(keep) == len(r.get("triggers") or []):
            continue
        r["suppressed"] = [t["key"] for t in r["triggers"] if t["key"].split("·")[0] in sysd]
        r["triggers"] = keep
        if not keep:
            r.update(triggered=False, inject="", cases=[])
            continue
        dims = []
        for t in keep:
            if t["key"].split("·")[0] not in dims:
                dims.append(t["key"].split("·")[0])
        r["cases"] = pick_cases(dims, load_reviews(skill, D, p["case_lookback_days"], results), p["max_cases"])
        r["inject"] = render(D, [(t["key"], t["reason"], t["param"]) for t in keep], r["cases"], p)
    return res


def exec_param(key, s, p, real_tp=None):
    """触发键 → 本日执行参数(一句话, 只调执行不改画像)"""
    dim, side = key.split("·")
    if key == "T法·连亏":   # 10/17 用户定: 链自己的 T 成绩回灌反思
        return ("本日暂停同票日内回转(T); 底仓照常按计划处理。恢复条件: 07 复盘写清亏在挂价 / 时机 / 规模哪一项并给出改法")
    n = len(s.get("days") or []) if dim != "回撤" else 0
    if key == "交不交易·多动":
        return ("本日默认不开新仓、不调仓(止损/保护线/失效离场照做); 只有出现导师画像里明确的出手信号才动, "
                "并在 why 里写明是哪条规则、为什么导师今天也会出手")
    if key == "交不交易·少动":
        return ("本日不要因'没把握/等确认'空过: 导师的常规出手信号出现就按画像出手(仓位可取下沿); "
                "选择不动须在 no_trade_reason 里写明'导师今天也会不动'的依据")
    if dim == "方向":
        return ("本日新买/加仓前先过一遍导师的减仓/离场信号; 同等条件下优先减、不优先加" if side == "偏多"
                else "本日减仓/清仓前先核对导师的持有条件是否真被破坏; 未破坏=按导师习惯继续拿, 有信号时可加")
    if dim == "标的":
        return "本日新开仓优先在导师近期足迹的市场板块(见上: 主板/创业板/科创/ST/ETF/转债…)里找; 选导师近期不碰的板块须在 why 里写明画像依据"
    if dim == "仓位":
        if real_tp is not None:
            lo, hi = max(0.0, real_tp - p["pos_gap"] / 2), real_tp + p["pos_gap"] / 2
            return f"本日收盘总仓向导师近 {n} 日均值 {real_tp:.0%} 靠拢(目标区间 {lo:.0%}~{hi:.0%}); 仓位约束块的硬上下限优先"
        return "本日收盘总仓向导师近期水平靠拢; 仓位约束块的硬上下限优先"
    if dim == "时段":
        return ("本日新单优先放到导师常用时段对应的 slot; 比导师更早出手须写明理由" if side == "偏早"
                else "导师出手比本链早: 本日导师常用的早段信号出现即在该时段 slot 出手, 不必等到后面的 slot 再确认")
    if dim == "回撤":
        return (f"本日新开仓单票规模 ×{p['dd_size_factor']}; 不加仓浮亏票; 先逐只核对持仓的止损/失效线, 已触发的照做")
    return ""


PRIORITY = ("回撤", "交不交易", "方向", "仓位", "标的", "时段", "T法")   # 10/17: 加 T法(链自己的 T 连续亏)   # 多条触发互相冲突时的优先级(注入原文里也写明)


def resolve(trig, real_tp=None):
    """触发项 [{key, param}] → 就地改写被更高优先级项压住的仓位参数(偏轻要加/偏重要减 与 回撤/多动/偏多/少动/偏空 冲突)"""
    keys = {t["key"] for t in trig}
    for t in trig:
        if t["key"] == "回撤·越线" and "仓位·偏轻" in keys:
            # 10/18 审计④ R5②(用户批): 学像优先——和"仓位偏轻"同时触发时, 回撤那条不下发"新开仓减半"(否则本就轻仓的链被压得更轻)
            t["param"] = "与「仓位·偏轻」同时触发: 学像优先, 不下发新开仓减半; 只提示单票别超导师习惯上限、止损照导师口径"
        elif t["key"] == "仓位·偏轻":
            if True:   # 10/18: 不再被回撤压住(学像优先); 和多动/偏多的冲突照旧处理
                hit = [k for k in ("交不交易·多动", "方向·偏多") if k in keys]
                if hit:
                    lvl = f"(导师近期均值 {real_tp:.0%})" if real_tp is not None else ""
                    t["param"] = (f"与「{'」「'.join(hit)}」同时触发: 不为补仓位单独开仓/加仓; 只在出现导师出手信号时, "
                                  f"单笔按导师的仓位水平{lvl}定规模, 买完拿住、少做日内调仓")
        elif t["key"] == "仓位·偏重":
            hit = [k for k in ("交不交易·少动", "方向·偏空") if k in keys]
            if hit:
                t["param"] = f"与「{'」「'.join(hit)}」同时触发: 不为降仓位单独卖出; 只在导师离场信号出现时按导师仓位水平减"
    return trig


def reason_text(key, s, m=None):
    dim, side = key.split("·")
    if dim == "回撤":
        t = f"近 {m.get('n', '')} 个交易日({str(m.get('base'))[5:]} 起) 峰值回撤 {m['dd']:.1%}, 区间收益 {m['ret']:.1%}"
        if "rel" in m:
            t += f"(对照组 {m['ctrl_ret']:.1%}, 相对 {m['rel']:+.1%})"
        return t
    days = s.get("days") or []
    ds = "、".join(f"{d[5:]}({why})" for d, why in days[-3:])
    return (f"{dim}·{side}: 连续 {s['streak']} 个配对日偏离导师真人(最近: {ds})" if s.get("streak")
            else f"{dim}·{side}: 自 {s['since']} 触发, 尚未连续 {s.get('release', 2)} 日消失(最近偏离: {ds})")


# ---------------- 07 case 挑选 ----------------
def load_reviews(skill, d, lookback, results=RESULTS):
    """本链 [d-lookback+1, d] 的 07 contract → [(日, contract)] 新→旧
    10/18: live-<日> 没有 07 时退读 asof-<日>(整日重跑后正式账本来自 asof 目录, 如 10/16; -oldrerun 等带后缀的旧重跑不读)"""
    d0 = (dt.date.fromisoformat(d) - dt.timedelta(days=lookback - 1)).strftime("%Y%m%d")
    d1 = d.replace("-", "")
    out = []
    base = results / f"{skill}_chain"
    days = sorted({m.group(1) for rd in base.glob("*-*") if (m := re.fullmatch(r"(?:live|asof)-(\d{8})", rd.name))}, reverse=True)
    for day in days:
        if not (d0 <= day <= d1):
            continue
        f = None
        for rd in (base / f"live-{day}", base / f"asof-{day}"):
            for g in (rd / "07_review.md", rd / "slots" / "review" / "07_review.md"):
                if g.exists():
                    f = g
                    break
            if f:
                break
        if not f:
            continue
        c = contract_of(f.read_text(encoding="utf-8"))
        if c:
            out.append((f"{day[:4]}-{day[4:6]}-{day[6:]}", c))
    return out


def _cut(s, n=150):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def pick_cases(dims, reviews, k):
    """dims=触发维度(有序) → ≤k 条 case 文本; 各维度轮流取, 每维度内按 拟人对照 > lessons > 旧版预案对照, 新→旧"""
    pools = []
    for dim in dims:
        kws, pool = KW.get(dim, ()), []
        for tier in range(3):
            for day, c in reviews:
                if tier == 0 and dim in DIMS:
                    for x in c.get("拟人对照") or []:
                        if isinstance(x, dict) and x.get("项") == dim and x.get("一致") is False:
                            pool.append(f"{day[5:]} 拟人对照·{dim}: 本链 {_cut(x.get('本链'), 40)} / 真人 {_cut(x.get('真人'), 40)}; "
                                        f"原因={x.get('原因')}: {_cut(x.get('说明'), 80)}")
                elif tier == 1:
                    for x in sorted((x for x in c.get("lessons") or [] if isinstance(x, dict)), key=lambda x: x.get("type") != "case卡"):
                        t = str(x.get("text") or "")
                        if any(w in t for w in kws):
                            pool.append(f"{day[5:]} 07 lessons[{x.get('type')}]: {_cut(t)}")
                elif tier == 2:
                    for x in sorted((x for x in c.get("预案对照") or [] if isinstance(x, dict)), key=lambda x: x.get("结果") != "误判"):
                        t = f"{x.get('项', '')}: {x.get('教训', '')}"
                        if x.get("结果") in ("误判", "漏票") and str(x.get("教训") or "").strip() and any(w in t for w in kws):
                            pool.append(f"{day[5:]} 07 预案对照[{x.get('结果')}] {_cut(t)}")
        pools.append(pool)
    out, seen, i = [], set(), 0
    while len(out) < k and any(i < len(pl) for pl in pools):
        for pl in pools:
            if i < len(pl) and len(out) < k and pl[i] not in seen:
                seen.add(pl[i])
                out.append(pl[i])
        i += 1
    return out


def render(d, trig, cases, p):
    """触发项 [(键, 原因, 执行参数)] + case → 注入 04/06 的原文(驱动器原样拼接)"""
    L = [f"\n\n## 偏离触发提示（驱动器注入·FinCon 式定向反思: {d} 收盘后机械判定本链持续偏离导师真人/回撤; 只调本日执行参数并给 case 提示, 画像与规则不变）"]
    for i, (k, why, par) in enumerate(trig, 1):
        L += [f"- 触发{i} {why}", f"  本日执行参数: {par}"]
    L.append(f"- 相关 case（本链 07 复盘摘录, ≤{p['max_cases']} 条, 多为单样本, 只作识别提示）:")
    L += [f"  - {c}" for c in cases] or ["  - （近期 07 复盘里没有与该维度相关的条目）"]
    L.append("- 执行参数与画像里导师明确的信号冲突时以画像为准, 但须在 why/no_trade_reason 里写明; 仓位约束块的硬上下限优先于本提示; "
             f"多条之间冲突按 {' > '.join(PRIORITY)} 取舍。"
             f"该维度连续 {p['release_days']} 个交易日不再偏离即自动解除。")
    return "\n".join(L)


# ---------------- 数据装配 ----------------
def leg_buckets(ledger):
    """真人逐笔腿 → {日: {时段桶}}(剔逆回购; 同 mimicry Real 去重口径)"""
    out, seen = {}, set()
    d = ms.TZ / ledger
    for f in glob.glob(str(d / "position_change_p*.json")) + glob.glob(str(d / "change_bs_*.json")):
        for t in ((ms.load(f) or {}).get("ex_data") or {}).get("change_list") or []:
            td = str(t.get("trans_date") or "")
            k = (td, t.get("stock_code"), t.get("trans_count"), t.get("trans_price"), t.get("op"))
            if k in seen or len(td) < 16 or not t.get("stock_code") or ms.is_repo(t["stock_code"], t.get("stock_name")):
                continue
            seen.add(k)
            if ms.norm_op(t) in ("1", "2"):
                out.setdefault(td[:10], set()).add(bucket(td[11:16]))
    return out


def chain_buckets(book):
    """链成交 → {日: {时段桶}}(按挂单 slot 近似; 同驱动器 07 拟人对照口径)"""
    b = ms.load(ms.BOOKS / f"{book}.json") or {}
    om = {o.get("id"): o for o in b.get("orders") or []}
    out = {}
    for t in b.get("trades") or []:
        if ms.is_repo(str(t.get("code"))):
            continue
        o = om.get(t.get("id"), {})
        hm = str(o.get("time") or "09:15")
        hm = hm if ":" in hm else f"{hm[:2]}:{hm[2:]}"
        out.setdefault(str(o.get("date") or str(t.get("id"))[:10]), set()).add(bucket(hm))
    return out


def compute(D, p, results=RESULTS):
    names = ms.load(HERE / "names.json") or {}
    books = {b: ms.Chain(b, names) for _, b, _ in CHAINS if (ms.BOOKS / f"{b}.json").exists()}
    reals = {l: ms.Real(l) for _, _, l in CHAINS if l and (ms.TZ / l / "day_positions.json").exists()}
    beg = (dt.date.fromisoformat(ms.START) - dt.timedelta(days=25)).isoformat()
    codes = set()
    for r in reals.values():
        for k, rec in r.dp.items():
            if k >= beg.replace("-", ""):
                codes |= {str(x.get("code")) for x in (rec or {}).get("list") or []}
    for c in books.values():
        codes |= {str(t["code"]) for t in c.trades}
    px = ms.Prices.from_db(codes, beg)
    if not px.ok:
        cal = sorted({f"{k[:4]}-{k[4:6]}-{k[6:]}" for r in reals.values() for k in r.dp
                      if dt.date(int(k[:4]), int(k[4:6]), int(k[6:])).weekday() < 5} | {D})
        px = ms.Prices({}, cal)
    cal = [d for d in px.cal if d <= D]
    if D not in cal:
        cal.append(D)
    tdays = [d for d in cal if d >= ms.START]
    ctrl = books.get(ms.CONTROL)
    res = {"date": D, "generated_at": dt.datetime.now().isoformat(timespec="seconds"), "stale_days": p["stale_days"],
           "params": {k: p[k] for k in DEFAULTS}, "price_source": "本地行情库" if px.c else "无(中性漂移)", "chains": {}}
    for skill, book, ledger in CHAINS:
        ch = books.get(book)
        row = {"book": book, "ledger": ledger, "triggered": False, "triggers": [], "inject": "", "notes": []}
        res["chains"][skill] = row
        if ch is None:
            row["notes"].append("无账本")
            continue
        trig = []
        # ① 拟人偏差
        real = reals.get(ledger) if ledger else None
        if real:
            rows = ms.build_days((book, ledger), ch, real, None, px, tdays)
            rb, cb = leg_buckets(ledger), chain_buckets(book)
            seq = [(r["date"], {f"{dim}·{v[0]}": v[1] for dim, v in
                                deviations(r["real"], r["chainf"], rb.get(r["date"], set()), cb.get(r["date"], set()), p).items()}) for r in rows]
            row["paired_days"] = [r["date"] for r in rows]
            row["daily_dev"] = {d: dev for d, dev in seq}
            st = walk(seq, p["streak_days"], p["release_days"])
            lag = len([d for d in cal if rows and d > rows[-1]["date"]]) if rows else None
            if not rows:
                row["notes"].append(f"窗口内无配对日(真人数据最新 {real.last})")
            elif lag > p["max_lag_days"]:
                row["notes"].append(f"真人数据滞后 {lag} 个交易日(最新配对日 {rows[-1]['date']}), 拟人触发作废")
            else:
                if lag:
                    row["notes"].append(f"配对数据截至 {rows[-1]['date']}(真人账本落后 {lag} 个交易日)")
                for k, s in sorted(st.items(), key=lambda kv: DIMS.index(kv[0].split("·")[0])):
                    if s["active"]:
                        rtp = None
                        if k.startswith("仓位"):
                            tps = [min(r["real"]["tp"], 1.0) for r in rows[-max(1, len(s["days"])):]]
                            rtp = sum(tps) / len(tps)
                        s["release"] = p["release_days"]
                        trig.append({"key": k, "since": s["since"], "streak": s["streak"], "clear": s["clear"], "real_tp": rtp,
                                     "reason": reason_text(k, s), "param": exec_param(k, s, p, rtp)})
        else:
            row["notes"].append("无导师真人账本: 只判回撤")
        # ② 回撤(状态机同上: 交易日逐日判, 越线即触发, 连续 release_days 日不越线解除)
        dseq, mlast = [], {}
        for i, d in enumerate(tdays):
            win = [x for x in cal if x <= d][-(p["dd_window"] + 1):]
            navs = [(x, ch.nav[x]) for x in win if x in ch.nav]
            cn = [(x, ctrl.nav[x]) for x in win if x in ctrl.nav] if (ctrl and skill != "control") else []
            if cn and navs:   # 相对口径: 双方共同起点
                b0 = max(navs[0][0], cn[0][0])
                navs2, cn = [x for x in navs if x[0] >= b0], [x for x in cn if x[0] >= b0]
            else:
                navs2 = navs
            hit, m = drawdown(navs, None, p)
            # 10/18 审计④ R5①(用户批): 绝对回撤只报告不触发(那一周上证 −2.6%, 链的回撤大多是大盘); 触发只看相对: 对照组同窗 / 导师真人同窗
            m["abs_hit"] = hit
            hit = hit and bool(p.get("dd_abs_trigger"))
            if ledger and len(navs) >= 2:
                rr = real_window_ret(ledger, navs[0][0], navs[-1][0])
                if rr is not None:
                    m.update(real_ret=round(rr, 4), rel_real=round(m["ret"] - rr, 4))
                    hit = hit or (m["ret"] - rr) <= p["dd_rel_real"]
            if cn and len(navs2) >= 2:
                _, m2 = drawdown(navs2, cn, p)
                if "rel" in m2:
                    m.update(ctrl_ret=m2["ctrl_ret"], rel=m2["rel"], ctrl_base=m2["ctrl_base"])
                    hit = hit or m2["rel"] <= p["dd_rel_ctrl"]
            mlast[d] = m
            dseq.append((d, {"回撤·越线": json.dumps(m, ensure_ascii=False)} if hit else {}))
        row["drawdown"] = mlast.get(D)
        sd = walk(dseq, 1, p["release_days"]).get("回撤·越线")
        if sd and sd["active"]:
            m = mlast.get(D) or {}
            trig.append({"key": "回撤·越线", "since": sd["since"], "streak": sd["streak"], "clear": sd["clear"],
                         "reason": ("回撤: " + reason_text("回撤·越线", sd, m)) + ("" if sd["streak"] else f"(已回到线内但自 {sd['since']} 触发后尚未连续 {p['release_days']} 日在线内)"),
                         "param": exec_param("回撤·越线", sd, p)})
        # ③ 10/17 用户定: 链自己的 T 成绩——最近 t_loss_streak 个"有 T 的日子"扣费后都为负 → 触发(只看链, 不看导师)
        try:
            import chain_t_stats as CT   # noqa: PLC0415
            bk = json.loads((ms.BOOKS / f"{book}.json").read_text(encoding="utf-8"))
            sk_t = CT.streak(bk, D, p["t_loss_streak"])
            row["t_streak"] = sk_t
            if len(sk_t) >= p["t_loss_streak"] and all(x[1] < 0 for x in sk_t):
                trig.append({"key": "T法·连亏", "since": sk_t[-1][0], "streak": len(sk_t), "clear": 0,
                             "reason": "T法·连亏: 本链最近 " + str(len(sk_t)) + " 个有 T 的日子扣费后都为负(" + "、".join(f"{d[5:]} {v:+.0f} 元" for d, v in sk_t) + ")",
                             "param": exec_param("T法·连亏", {}, p)})
        except Exception as e:   # noqa: BLE001
            row["notes"].append(f"T 成绩统计失败: {e}")
        if trig:
            trig.sort(key=lambda t: PRIORITY.index(t["key"].split("·")[0]))
            resolve(trig, next((t["real_tp"] for t in trig if t.get("real_tp") is not None), None))
            dims = []
            for t in trig:
                dm = t["key"].split("·")[0]
                if dm not in dims:
                    dims.append(dm)
            cases = pick_cases(dims, load_reviews(skill, D, p["case_lookback_days"], results), p["max_cases"])
            row.update(triggered=True, triggers=trig, cases=cases,
                       inject=render(D, [(t["key"], t["reason"], t["param"]) for t in trig], cases, p))
    return cap_systemic(res, D, p, results)


def write(res, out_dir=OUT):
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / f"{res['date']}.json"
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
    os.replace(tmp, f)
    return f


def summary(res):
    L = []
    for skill, r in res["chains"].items():
        if r["triggered"]:
            L.append(f"  {skill}: 触发 " + "；".join(t["key"] + ("" if t["streak"] else "(维持)") for t in r["triggers"]) + f"  case {len(r.get('cases') or [])} 条")
    return f"{res['date']}: {sum(r['triggered'] for r in res['chains'].values())}/{len(res['chains'])} 条链触发" + ("\n" + "\n".join(L) if L else "")


# ---------------- 自测 ----------------
def selftest():
    fails = []
    p = dict(DEFAULTS)
    mk = lambda **k: dict({"trade": False, "buy": False, "sell": False, "hold": set(), "buys": set(), "tp": 0.0, "n": 0, "mx": 0.0,  # noqa: E731
                           "boards": ms.collections.Counter(), "inds": ms.collections.Counter(), "foot_n": 0, "ind_known": 0,
                           "net": 0.0, "turn": 0.0, "dir": 0}, **k)
    C = ms.collections.Counter
    # deviations: 五维各一正例 + 一致=空
    r0, c0 = mk(), mk()
    if deviations(r0, c0, set(), set(), p):
        fails.append("双静应无偏离")
    dv = deviations(mk(), mk(trade=True, buy=True, dir=1), set(), {0}, p)
    if set(dv) != {"交不交易"} or dv["交不交易"][0] != "多动":
        fails.append(f"多动判错: {dv}")
    dv = deviations(mk(trade=True, dir=-1, tp=0.9, foot_n=1, boards=C({"创业板": 1})), mk(trade=True, dir=1, tp=0.3, foot_n=1, boards=C({"沪深主板": 1})), {3}, {0}, p)
    if dv.get("方向", ("",))[0] != "偏多" or dv.get("仓位", ("",))[0] != "偏轻" or dv.get("标的", ("",))[0] != "错位" or dv.get("时段", ("",))[0] != "偏早":
        fails.append(f"方向/仓位/标的/时段判错: {dv}")
    dv = deviations(mk(trade=True, dir=1, foot_n=1, boards=C({"创业板": 1}), ind_known=1, inds=C({"半导体": 1}), tp=2.1),
                    mk(trade=True, dir=1, foot_n=2, boards=C({"沪深主板": 1, "创业板": 1}), ind_known=1, inds=C({"电池": 1}), tp=0.95), {0, 1}, {1}, p)
    if dv:
        fails.append(f"板块半重合/行业不同/两融 210% vs 95%/时段有交集/方向同 应无偏离: {dv}")
    # walk: 3 连触发 / 2 日解除 / 中断重计
    seq = [("d1", {"a": "x"}), ("d2", {"a": "x"}), ("d3", {}), ("d4", {"a": "x"}), ("d5", {"a": "x"}), ("d6", {"a": "x"})]
    st = walk(seq, 3, 2)
    if not st["a"]["active"] or st["a"]["since"] != "d6" or st["a"]["streak"] != 3:
        fails.append(f"walk 连续计数错: {st}")
    st = walk(seq + [("d7", {})], 3, 2)
    if not st["a"]["active"]:
        fails.append("walk: 消失 1 日不应解除")
    st = walk(seq + [("d7", {}), ("d8", {})], 3, 2)
    if st["a"]["active"]:
        fails.append("walk: 连续 2 日消失应解除")
    st = walk(seq + [("d7", {}), ("d8", {"a": "x"}), ("d9", {})], 3, 2)
    if not st["a"]["active"]:
        fails.append("walk: 消失被偏离打断后应重新计数")
    # drawdown: 绝对 / 相对 / 未越线
    h, m = drawdown([("a", 100), ("b", 102), ("c", 96)], None, p)
    if not h or abs(m["dd"] - (96 / 102 - 1)) > 1e-4:
        fails.append(f"绝对回撤判错: {m}")
    h, m = drawdown([("a", 100), ("b", 97)], [("a", 100), ("b", 103)], p)   # 10/18: 阈值 -3%→-5%, 用 -6% 测
    if not h or abs(m["rel"] + 0.06) > 1e-4:
        fails.append(f"相对对照组落后判错: {m}")
    h, _ = drawdown([("a", 100), ("b", 98)], [("a", 100), ("b", 99)], p)
    if h:
        fails.append("回撤 2%/相对 -1% 不应触发")
    # pick_cases: 拟人对照 > lessons > 旧版; 维度过滤; ≤k
    revs = [("2026-10-15", {"拟人对照": [{"项": "交不交易", "本链": "买2笔", "真人": "未动", "一致": False, "原因": "理解错导师框架", "说明": "普跌日导师空仓"},
                                      {"项": "仓位", "本链": "80%", "真人": "80%", "一致": True}],
                         "lessons": [{"type": "错误归因", "text": "竞价追高被埋", "evidence": "x"}, {"type": "case卡", "text": "普跌日导师不出手而我们开仓", "evidence": "y"}]}),
            ("2026-10-14", {"预案对照": [{"项": "开仓", "结果": "误判", "教训": "空仓日不该出手"}, {"项": "PCB", "结果": "命中", "教训": "出手正确"}]})]
    cs = pick_cases(["交不交易"], revs, 3)
    if len(cs) != 3 or "拟人对照·交不交易" not in cs[0] or "case卡" not in cs[1] or "预案对照[误判]" not in cs[2]:
        fails.append(f"case 挑选顺序/过滤错: {cs}")
    if any("命中" in c or "竞价追高" in c for c in pick_cases(["交不交易"], revs, 5)):
        fails.append("case 挑选混入命中项/无关维度")
    cs = pick_cases(["时段", "交不交易"], revs, 2)
    if len(cs) != 2 or "竞价追高" not in cs[0] or "拟人对照" not in cs[1]:
        fails.append(f"多维度轮流取错: {cs}")
    # render + 文件读写
    txt = render("2026-10-16", [("交不交易·多动", "交不交易·多动: 连续 3 个配对日", exec_param("交不交易·多动", {}, p))], cs, p)
    if "偏离触发提示" not in txt or "默认不开新仓" not in txt or "画像与规则不变" not in txt or txt.count("\n  - ") != 2:
        fails.append("render 文本缺要素")
    if "近 3 日均值 40%" not in exec_param("仓位·偏重", {"days": [1, 2, 3]}, p, 0.4):
        fails.append("仓位执行参数缺导师均值")
    tr = resolve([{"key": "交不交易·多动", "param": "a"}, {"key": "仓位·偏轻", "param": "b"}], 0.96)
    if "不为补仓位单独开仓" not in tr[1]["param"] or "96%" not in tr[1]["param"] or tr[0]["param"] != "a":
        fails.append(f"冲突消解(多动×偏轻)错: {tr}")
    tr = resolve([{"key": "回撤·越线", "param": "a"}, {"key": "交不交易·多动", "param": "c"}, {"key": "仓位·偏轻", "param": "b"}], 0.96)
    if "学像优先" not in tr[0]["param"] or "不为补仓位单独开仓" not in tr[2]["param"]:   # 10/18 R5②: 回撤让位于偏轻; 偏轻×多动冲突照旧
        fails.append(f"冲突消解(回撤×偏轻)错: {tr}")
    if resolve([{"key": "仓位·偏轻", "param": "b"}, {"key": "时段·偏早", "param": "t"}])[0]["param"] != "b":
        fails.append("无冲突时不应改写仓位参数")
    if "不为降仓位单独卖出" not in resolve([{"key": "方向·偏空", "param": "a"}, {"key": "仓位·偏重", "param": "b"}])[1]["param"]:
        fails.append("冲突消解(偏空×偏重)错")
    td = Path(tempfile.mkdtemp(prefix="selftest_reflect_"))
    try:
        f = write({"date": "2026-10-16", "chains": {"x": {"triggered": True, "inject": txt}}}, td)
        if json.loads(f.read_text(encoding="utf-8"))["chains"]["x"]["inject"] != txt or list(td.glob("*.tmp")):
            fails.append("写文件往返不一致/残留 tmp")
        # load_reviews: 只取窗口内 live-* 且 ≤D, 缺 07 回落 slots/review
        for day, sub in (("20261015", ""), ("20261014", "slots/review/"), ("20261017", ""), ("20261001", "")):
            q = td / "res" / "x_chain" / f"live-{day}" / sub
            q.mkdir(parents=True, exist_ok=True)
            (q / "07_review.md").write_text(f"正文\n```contract\n{json.dumps({'lessons': [{'type': 'case卡', 'text': day}]})}\n```\n", encoding="utf-8")
        got = [d for d, _ in load_reviews("x", "2026-10-16", 10, td / "res")]
        if got != ["2026-10-15", "2026-10-14"]:
            fails.append(f"load_reviews 窗口/回落错: {got}")
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)
    if bucket("09:25") != 0 or bucket("10:00") != 1 or bucket("13:00") != 2 or bucket("14:55") != 3:
        fails.append("时段桶口径错")
    print("reflect_trigger selftest " + ("PASS" if not fails else "FAIL:\n  " + "\n  ".join(fails)))
    return not fails


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--out-dir")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(0 if selftest() else 1)
    p = params()
    out = Path(a.out_dir) if a.out_dir else OUT
    if a.since:
        d0, d1 = dt.date.fromisoformat(a.since), dt.date.fromisoformat(a.until or dt.date.today().isoformat())
        days = [(d0 + dt.timedelta(i)).isoformat() for i in range((d1 - d0).days + 1)]
        days = [d for d in days if dt.date.fromisoformat(d).weekday() < 5]
    else:
        days = [a.date or dt.date.today().isoformat()]
    for d in days:
        res = compute(d, p)
        f = write(res, out)
        print(summary(res) + f"\n  → {f}")


if __name__ == "__main__":
    main()
