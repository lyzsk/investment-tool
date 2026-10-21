# -*- coding: utf-8 -*-
"""decision_memory.py — 决策日志/结算/反思的存储与回注读取(TODO §3-A 第 6 条, 2026-10-14 建; 借 TradingAgents memory/log.py)

三个文件按 skill 分(每条链进程互斥, 按 skill 分文件=并发 15 链不会互相穿插写), 全部只追加:
  <dir>/<skill>.jsonl          决策记录(驱动器 06 出单后写; 或 settle_decisions.py --backfill 从 plans+06 产物补)
  <dir>/<skill>.settle.jsonl   结算记录(settle_decisions.py 写; 每单 T+1/2/3/5/10 各一行, 零 token)
  <dir>/<skill>.reflect.jsonl  反思记录(settle_decisions.py 调 claude -p 写; 每单一行, 基于本导师持有期窗口 T+h 的结算, 10/20 前=T+1)
<dir> 实盘=scripts/dfcf/paper/decisions; as-of 回放=<沙盒>/decisions(不污染实盘)
回注口径(防偷看未来): 只用 resolved(=反思所依据的那根收盘的日期) < 链运行日 的记录。
被驱动器懒加载(仅 CHAIN_REFLECTION=1 时 import), 只用标准库。
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DIR = Path(__file__).resolve().parent / "decisions"
FLAGS = ROOT / "scripts" / "claude_profile" / "chain_flags.txt"
# 10/20 用户: "反思窗口要按导师持有期, 这样才动态起来, 准确性才高" —— 结算全窗口, 反思 / 回注 / 评估按各导师真实持有交易日中位数挑窗口
WINDOWS = (1, 2, 3, 5, 10)
HOLD_OVERRIDE = {}   # 自测 / 手动钉死用: {skill: 窗口}


def hold_window(skill):
    """该导师真实持有交易日中位数(skills/<skill>-skill/persona/fingerprint.md, 每晚 mentor_fingerprint 刷新) → 最近的结算窗口(平手取短);
    取不到(土豆日内转债 / 对照组 / 没 fingerprint) = 1。fingerprint 更新后窗口自动跟着变"""
    if skill in HOLD_OVERRIDE:
        return HOLD_OVERRIDE[skill]
    try:
        t = (ROOT / "skills" / f"{skill}-skill" / "persona" / "fingerprint.md").read_text(encoding="utf-8")
    except OSError:
        return 1
    m = re.search(r"持有交易日(?:\(非日内\))?[:：]?\s*(\d+(?:\.\d+)?)", t)
    if not m:
        return 1
    h = float(m.group(1))
    return min(WINDOWS, key=lambda w: (abs(w - h), w))


# ---------- 开关(与驱动器 _flag 同口径: 环境变量优先, 其次 chain_flags.txt) ----------
def flag_raw(name):
    if name in os.environ:
        return os.environ[name]
    try:
        for line in FLAGS.read_text(encoding="utf-8").splitlines():
            k, _, val = line.split("#")[0].partition("=")
            if k.strip() == name:
                return val.strip()
    except OSError:
        pass
    return None


def reflect_skills():
    """CHAIN_REFLECTION_SKILLS: 逗号分隔白名单; '*'/'all'=全部; 缺省或空=无(保守: 只开总开关不会全量开)"""
    v = (flag_raw("CHAIN_REFLECTION_SKILLS") or "").strip()
    if v in ("*", "all"):
        return "*"
    return {s.strip() for s in v.split(",") if s.strip()}


def skill_enabled(skill):
    if (flag_raw("CHAIN_REFLECTION") or "").strip() != "1":
        return False
    ws = reflect_skills()
    return ws == "*" or skill in ws


# ---------- 写 ----------
def _append(path, recs):
    if not recs:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:   # 一次 write: 同 skill 本就互斥, 这里再降穿插风险
        fh.write(data)


def decision_id(date, skill, slot, code, side, px, qty):
    return f"{date}|{skill}|{slot}|{code}|{side}|{px:g}|{qty}"


def _short(v, n):
    s = "" if v is None else str(v).replace("\r", " ").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "…"


def records_from_contract(contract, *, skill, source, date, slot, sub, blind_fail, asof, origin="chain", ts=None):
    """06 contract.actions(v06 已回填 _px) → 决策记录列表; 无数值价的动作跳过"""
    ts = ts or datetime.now().isoformat(timespec="seconds")
    out = []
    for a in contract.get("actions") or []:
        try:
            px = float(a.get("_px") if a.get("_px") is not None else a.get("trigger_price"))
            qty = int(a.get("qty"))
        except (TypeError, ValueError):
            continue
        side = "BUY" if a.get("op") == "买" else "SELL"
        code = str(a.get("code"))

        def num(k):
            try:
                return float(a.get(k)) if a.get(k) is not None else None
            except (TypeError, ValueError):
                return None
        out.append({
            "id": decision_id(date, skill, slot, code, side, px, qty), "ts": ts, "skill": skill, "source": source,
            "date": date, "slot": slot, "code": code, "name": a.get("name") or "", "side": side, "px": px, "qty": qty,
            "anchor": num("anchor"), "cancel_below": num("cancel_below"), "stop_below": num("stop_below"),
            "why": _short(a.get("why"), 200), "invalid_if": _short(a.get("invalid_if"), 200),
            "rules": [str(r.get("id")) for r in (a.get("rules") or []) if isinstance(r, dict) and r.get("id")],
            "supersedes": _short(contract.get("supersedes"), 80), "sub": bool(sub), "blind_fail": bool(blind_fail),
            "asof": bool(asof), "origin": origin,
        })
    return out


def write_decisions(dir_, skill, recs):
    _append(Path(dir_) / f"{skill}.jsonl", recs)


def append_settles(dir_, skill, recs):
    _append(Path(dir_) / f"{skill}.settle.jsonl", recs)


def append_reflects(dir_, skill, recs):
    _append(Path(dir_) / f"{skill}.reflect.jsonl", recs)


def reflects_from_07(dir_, skill, date, contract, names=None):
    """10/21 用户批(15:50 的 LLM 反思删掉, 由 07 的结论代替, 注入以后的 04/06): 07 contract 的 root_causes + lessons 按票挂到当天各决策上 →
    {skill}.reflect.jsonl(与原反思同格式, past_context 照常读); 只挂文字里点名了该票代码 / 名称的, 不点名的不硬挂; 谈改规则的过护栏(guard)。返回写入条数"""
    decs = [d for d in load_decisions(dir_, skill).values() if d.get("date") == date]
    if not decs:
        return 0
    items = []
    for r in contract.get("root_causes") or []:
        if isinstance(r, dict):
            items.append(f"[根因·{r.get('layer', '')}] {r.get('item', '')}; 改: {r.get('fix', '')}; 回放: {r.get('replay', '')}")
    for x in contract.get("lessons") or []:
        if isinstance(x, dict) and x.get("text"):
            items.append(f"[{x.get('type', '教训')}] {x['text']}")
    names = names or {}
    recs = []
    for d in decs:
        keys = [k for k in (str(d.get("code")), d.get("name") or names.get(str(d.get("code")), "")) if k]
        hit = [t for t in items if any(k in t for k in keys)]
        good = [t for t in hit if guard_ok(t)]   # 逐段过护栏: 谈改规则的那段不回注, 其余照挂
        if not good:
            continue
        text = " | ".join(good)[:600]
        recs.append({"id": d["id"], "text": text, "resolved": date, "guard": "ok", "blocked_n": len(hit) - len(good), "src": "07", "ts": datetime.now().isoformat(timespec="seconds")})
    if recs:
        append_reflects(dir_, skill, recs)
    return len(recs)


# ---------- 读 ----------
def _read_jsonl(path):
    out = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass   # 坏行跳过(只追加文件, 断电半行不致命)
    except OSError:
        pass
    return out


def load_decisions(dir_, skill):
    """同 (date, slot) 重跑(手动回炉重 emit)只认最后一批(ts 最大); 同 id 后写覆盖先写"""
    recs = _read_jsonl(Path(dir_) / f"{skill}.jsonl")
    last = {}
    for r in recs:
        k = (r.get("date"), r.get("slot"))
        last[k] = max(last.get(k, ""), r.get("ts", ""))
    out = {}
    for r in recs:
        if r.get("ts", "") == last[(r.get("date"), r.get("slot"))]:
            out[r["id"]] = r
    return out


def load_settles(dir_, skill):
    """{id: {win: rec}}"""
    out = {}
    for r in _read_jsonl(Path(dir_) / f"{skill}.settle.jsonl"):
        out.setdefault(r["id"], {})[int(r["win"])] = r
    return out


def load_reflects(dir_, skill):
    out = {}
    for r in _read_jsonl(Path(dir_) / f"{skill}.reflect.jsonl"):
        out[r["id"]] = r   # 后写覆盖
    return out


# ---------- 反思护栏(机械): 谈"改/否定导师规则"的反思一律不入库不回注 ----------
RULE_GUARD = re.compile(
    r"(规则|导师|画像|人格|persona|rules?|选股逻辑|(?<![A-Za-z0-9])[A-ER]\d{1,3}(?![0-9]))[^。；;!！?？\n]{0,12}?"
    r"(错了|有误|不对|失效(?!条件|价|线|单|位)|作废|放弃|废除|不再适用|过时|应改|改为|修改|删除|删掉|不必遵守|不该遵守|不应遵守|可以突破|可突破|别信|不可信)")


def guard_ok(text):
    return not RULE_GUARD.search(text or "")


# ---------- 回注 ----------
def _pct(v):
    return "—" if v is None else f"{v * 100:+.1f}%"


def _fmt_entry(d, sts, rf, as_of, hw=1):
    side = "买" if d["side"] == "BUY" else "卖"
    s1 = sts.get(1) or {}
    st = {"filled": f"已成交@{s1.get('fill_px'):g}" if s1.get("fill_px") else "已成交",
          "void": "未成交(废单)", "cxl": "被后续时段撤单", "invalid": "失效条件触发撤单", "reject": "matcher 拒单",
          "open": "未成交", "unknown": "账本无对应挂单"}.get(s1.get("status"), s1.get("status") or "未结算")
    parts = []
    for w in WINDOWS:   # 已到期(resolved < as_of)的窗口全给, ★ = 本导师典型持有期
        s = sts.get(w)
        if s and s.get("resolved", "9") < as_of:
            parts.append(f"T+{w}{'★' if w == hw else ''} 方向收益 {_pct(s.get('signed_ret'))}, 超上证 {_pct(s.get('ex_idx'))}"
                         + (f", 超对照组 {_pct(s.get('ex_ctrl'))}" if s.get("ex_ctrl") is not None else ""))
    slot = f"{d['slot'][:2]}:{d['slot'][2:]}" if str(d.get("slot", "")).isdigit() else d.get("slot", "")
    head = (f"- {d['date'][5:]} {slot} {side} {d.get('name') or ''}({d['code']}) 挂{d['px']:g}×{d['qty']}"
            f" → {st}" + (" | " + " | ".join(parts) if parts else ""))
    return head + f"\n  反思: {rf['text']}"


def past_context(dirs, skill, codes, as_of, n_same=5, n_cross=3, cap_same=15):
    """返回 (注入文本, 同票条数, 跨票条数); 只含 反思 resolved < as_of 的本 skill 记录(as-of 防偷看)。dirs=多个根(沙盒+实盘), 同 id 去重"""
    decs, sets, refs = {}, {}, {}
    for d in dirs:
        if not d or not Path(d).is_dir():
            continue
        decs.update(load_decisions(d, skill))
        for k, v in load_settles(d, skill).items():
            sets.setdefault(k, {}).update(v)
        refs.update(load_reflects(d, skill))
    pool = []
    for i, rf in refs.items():
        d = decs.get(i)
        if not d or rf.get("guard") != "ok" or not rf.get("text") or not (rf.get("resolved") or "9") < as_of:
            continue
        pool.append(d)
    pool.sort(key=lambda d: (d["date"], d["slot"], d["id"]), reverse=True)
    codes = [str(c) for c in dict.fromkeys(codes or [])]
    same, used = [], set()
    for c in codes:
        hit = [d for d in pool if d["code"] == c][:n_same]
        for d in hit:
            if len(same) < cap_same:
                same.append(d); used.add(d["id"])
    cross = [d for d in pool if d["id"] not in used and d["code"] not in codes][:n_cross]
    if not same and not cross:
        return "", 0, 0
    hw = hold_window(skill)
    out = [f"\n\n# 本链过往决策复盘(驱动器注入, CHAIN_REFLECTION; 只含 {as_of} 之前已结算的本链自己的单子, 机械结算+执行复盘)",
           "- 用途: 只用于改进**执行细节**(挂价离现价多远、仓位大小、下单时段、止损/失效条件松紧)。导师规则、选股逻辑、方向判断一律以 persona/rules 为准, "
           f"下面任何内容都不得作为改写、否定或绕开导师规则的理由; 单笔结果不足以证明论点对错。T+{hw}★ = 本导师真实持有交易日中位数对应的窗口, 主看它。产物里不必逐条回应本块。"]
    if same:
        out += ["", "## 同票(本次涉及的持仓/挂单/候选票, 最近在前)"] + [_fmt_entry(d, sets.get(d["id"], {}), refs[d["id"]], as_of, hw) for d in same]
    if cross:
        out += ["", "## 本链其他票(最近在前)"] + [_fmt_entry(d, sets.get(d["id"], {}), refs[d["id"]], as_of, hw) for d in cross]
    return "\n".join(out), len(same), len(cross)
