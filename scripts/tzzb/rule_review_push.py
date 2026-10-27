# -*- coding: utf-8 -*-
"""rule_review_push.py — 规则逐条人工核对: 你要了才发, 一次一家 2 条(10/26 晚用户令; 零 token)

用户原话(10/26 21:4x): "不要一口气发完, 两条两条来, 芷影 2 条, 然后我会问你要, 然后给刘忆青 2 条, 然后做手 2 条, 不吃土豆 2 条, 这样发"
        (20:3x 原话: 逐 rule 人工核对, 带上 rule 时间 + 内容整段(什么时候核销什么时候证伪), 不管是教训类还是其他类)
做什么:
  ① 收你的回复: 读 hermes 网关日志里你发的微信, 认 "芷影R13 对" / "刘忆青 R5 错: 理由" / "做手R22 改: …" / "土豆R8 删" 这种,
     原话追加进该 skill 的 persona/rule_log.md 对应 ### Rn 节「用户人工核对」(不改 rules.md 本身, 改规则由晚上会话按你的话做)
  ② 发下一组: 轮到哪家发哪家(芷影 → 刘忆青 → 做手 → 土豆 轮流), 每家 [教训] 类在前、其余按 rules.md 顺序, 没发过的取 2 条;
     每条 = 标题 + 时间状态(建立 / 最后验证 / 状态)+ rules.md 整段 + rule_log 里的核销 / 证伪记录(带日期, 最近 8 条)
  ③ 发完记 state(results/_rule_review/state.json); 全部发完从头再来
怎么要下一组: 微信发「规则」或「下一批」(--watch 每 15 秒看一次网关日志); 也可以在 Claude Code 里叫我跑 python scripts/tzzb/rule_review_push.py
口径: 只发 ### R<数字> 节(默认表 / 冲突表 / 反向审计表等汇总节不发); 走 wx_send(src=rule_review, 超 1800 字 wx_send 自己按整段切)
用法: python rule_review_push.py [--dry] [--collect-only] | --watch(计划任务 RuleReviewPush 每天 19:00 拉起, 24:00 退出; wscript //B 无窗口)
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "_rule_review"
STATE = OUT / "state.json"
SKILLS = [("zhiyingjuexin", "芷影攫心", "芷影", 2), ("liuyiqing", "刘忆青", "刘忆青", 2), ("zuoshoudeirong", "做手德融", "做手", 2), ("buchitudou0", "不吃土豆0", "土豆", 2)]
GW = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "logs" / "gateway.log"
MSG_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ .*inbound message: platform=weixin .* msg='(.*)' reply_to_id")
ASK_RE = re.compile(r"^\s*(规则|rule|rules|下一批|下一组|下两条|继续核|再来两条)\s*$", re.I)
REPLY_RE = re.compile(r"(芷影攫心|芷影|刘忆青|做手德融|做手|德融|不吃土豆0|不吃土豆|土豆)\s*(R\d+[\w\-]*)\s*[:：,，]?\s*(对|错|改|删|留|存疑|不确定)?\s*[:：,，]?\s*(.*)")
ALIAS = {"芷影攫心": "zhiyingjuexin", "芷影": "zhiyingjuexin", "刘忆青": "liuyiqing", "做手德融": "zuoshoudeirong", "做手": "zuoshoudeirong", "德融": "zuoshoudeirong",
         "不吃土豆0": "buchitudou0", "不吃土豆": "buchitudou0", "土豆": "buchitudou0"}


def rules_of(sk):
    """→ [(编号, 标题行, 整段文本, 是否教训)]"""
    f = ROOT / "skills" / f"{sk}-skill" / "persona" / "rules.md"
    t = f.read_text(encoding="utf-8").replace("\r\n", "\n")
    out = []
    for m in re.finditer(r"^### (R\d+[\w\-]*) (.*?)$\n(.*?)(?=^### |^## |\Z)", t, re.S | re.M):
        rid, title, body = m.group(1), m.group(2).strip(), m.group(3).strip()
        out.append((rid, title, body, "教训" in title or "[教训]" in body[:200]))
    return out


def log_of(sk, rid):
    f = ROOT / "skills" / f"{sk}-skill" / "persona" / "rule_log.md"
    if not f.exists():
        return []
    t = f.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.search(rf"^### {re.escape(rid)} .*?$\n(.*?)(?=^### |^## |\Z)", t, re.S | re.M)
    if not m:
        return []
    return [l.strip() for l in m.group(1).splitlines() if l.strip().startswith("- ")]


def card(sk, cn, rid, title, body, lesson):
    L = [f"【{cn} {rid}】{'〔教训〕' if lesson else ''}{title}"]
    L += [l.strip() for l in body.splitlines() if l.strip()]
    lg = log_of(sk, rid)
    if lg:
        L.append(f"核销 / 证伪记录({len(lg)} 条{', 只列最近 8 条' if len(lg) > 8 else ''}):")
        L += [x if len(x) <= 260 else x[:257] + "…" for x in lg[-8:]]
    else:
        L.append("核销 / 证伪记录: 还没有")
    return "\n".join(L)


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"done": {}, "round": 1, "last_collect": None, "batches": 0, "turn": 0}


def save_state(s):
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, STATE)


def _gw_msgs():
    if not GW.exists():
        return []
    out = []
    for l in GW.read_text(encoding="utf-8", errors="replace").splitlines()[-5000:]:
        m = MSG_RE.match(l)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def collect(state, dry=False):
    """读网关日志里你的微信回复 → 追加进 rule_log.md「用户人工核对」"""
    since = state.get("last_collect") or "2026-10-26 20:00:00"
    got = []
    for ts, msg in _gw_msgs():
        if ts <= since:
            continue
        for seg in re.split(r"[\n；;]|\\n", msg):
            r = REPLY_RE.search(seg.strip())
            if r:
                got.append((ts, ALIAS[r.group(1)], r.group(2), r.group(3) or "", (r.group(4) or "").strip()))
    for ts, sk, rid, verdict, why in got:
        f = ROOT / "skills" / f"{sk}-skill" / "persona" / "rule_log.md"
        line = f"- **用户人工核对 {ts[5:16]}**(微信): {verdict or '意见'}" + (f" —— {why}" if why else "")
        if dry:
            print("[dry] 写入", sk, rid, line)
            continue
        t = f.read_text(encoding="utf-8") if f.exists() else f"# {sk} · 规则核销记录\n"
        nl = "\r\n" if "\r\n" in t else "\n"
        t = t.replace("\r\n", "\n")
        m = re.search(rf"^### {re.escape(rid)} .*?$", t, re.M)
        if m:
            nxt = re.search(r"^### |^## ", t[m.end():], re.M)
            pos = m.end() + (nxt.start() if nxt else len(t) - m.end())
            t = t[:pos].rstrip("\n") + "\n" + line + "\n\n" + t[pos:].lstrip("\n")
        else:
            t = t.rstrip("\n") + f"\n\n### {rid}(用户核对)\n{line}\n"
        f.write_text(t.replace("\n", nl), encoding="utf-8")
        state.setdefault("verdicts", {})[f"{sk}:{rid}"] = {"at": ts, "v": verdict, "why": why}
    if got and not dry:
        state["last_collect"] = max(g[0] for g in got)
    return got


def next_batch(state):
    """轮到哪家只出那一家的 2 条(state["turn"] 轮转); 那家发完了跳到下一家 → ([(sk, cn, rule)], 用到的家序号)"""
    done = state.setdefault("done", {})
    for k in range(len(SKILLS)):
        i = (state.get("turn", 0) + k) % len(SKILLS)
        sk, cn, short, n = SKILLS[i]
        rs = rules_of(sk)
        rs = [r for r in rs if r[3]] + [r for r in rs if not r[3]]   # 教训类在前
        left = [r for r in rs if r[0] not in done.get(sk, [])]
        if left:
            return [(sk, cn, r) for r in left[:n]], i
    return [], None


def send_next(dry=False):
    state = load_state()
    got = collect(state, dry)
    batch, i = next_batch(state)
    head_extra = ""
    if not batch:   # 这一轮全部发完 → 从头再来
        state["done"], state["round"] = {}, state.get("round", 1) + 1
        batch, i = next_batch(state)
        head_extra = f"(上一轮已全部发完, 第 {state['round']} 轮从头开始)\n"
    tot = {sk: len(rules_of(sk)) for sk, *_ in SKILLS}
    left = {sk: tot[sk] - len(state["done"].get(sk, [])) for sk, *_ in SKILLS}
    head = (f"📋 规则人工核对 第 {state.get('batches', 0) + 1} 组 · {SKILLS[i][1]} {dt.datetime.now():%m-%d %H:%M}\n{head_extra}"
            "回复: 芷影R13 对 / 刘忆青R5 错: 理由 / 做手R22 改: 怎么改 / 土豆R8 删 · 要下一组发「规则」\n"
            "注: 核销记录里的日期 = 那天的交易数据(当晚或之后蒸馏时才写进来), 所以会有规则 10-15 建、记录写 10-14 的情况\n"
            "剩余: " + " · ".join(f"{cn} {left[sk]}/{tot[sk]}" for sk, cn, *_ in SKILLS)
            + (f"\n收到你 {len(got)} 条核对回复, 已记进各家 rule_log.md" if got else ""))
    text = head + "\n\n" + "\n\n".join(card(sk, cn, r[0], r[1], r[2], r[3]) for sk, cn, r in batch)
    sys.path.insert(0, str(ROOT / "scripts" / "hermes"))
    import wx_send
    res = wx_send.send(text, src="rule_review", raw=True, dry=dry, force=True, verbose=False)
    print(f"发 {SKILLS[i][1]} {[r[0] for _, _, r in batch]}({len(text)} 字) → {res}")
    if res in ("ok", "dup") and not dry:
        for sk, cn, r in batch:
            state["done"].setdefault(sk, []).append(r[0])
        state["batches"] = state.get("batches", 0) + 1
        state["turn"] = (i + 1) % len(SKILLS)
        with (OUT / "pushed.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "rules": [f"{sk}:{r[0]}" for sk, _, r in batch]}, ensure_ascii=False) + "\n")
    if not dry:
        save_state(state)
    return res


def watch(until="23:59:30"):
    """19:00 计划任务拉起: 每 15 秒看你有没有发「规则 / 下一批」, 有就发下一组; 顺手收核对回复"""
    st0 = load_state()
    since = max(st0.get("last_ask") or "", dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    while dt.datetime.now().strftime("%H:%M:%S") < until:
        asks = [ts for ts, msg in _gw_msgs() if ts > since and ASK_RE.match(msg)]
        if asks:
            since = asks[-1]
            s_ = load_state()
            s_["last_ask"] = since
            save_state(s_)
            send_next()
        else:
            s_ = load_state()
            if collect(s_):
                save_state(s_)
        time.sleep(15)


def main():
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--collect-only", action="store_true")
    ap.add_argument("--watch", action="store_true")
    a = ap.parse_args()
    if a.watch:
        watch()
        return 0
    if a.collect_only:
        st = load_state()
        got = collect(st, a.dry)
        if not a.dry:
            save_state(st)
        print(f"收到 {len(got)} 条核对回复")
        return 0
    r = send_next(a.dry)
    return 0 if r in ("ok", "dup", "dry") else 2


if __name__ == "__main__":
    sys.exit(main())
