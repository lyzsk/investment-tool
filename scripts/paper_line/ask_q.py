# -*- coding: utf-8 -*-
"""ask_q.py — 查询交给 harness(10/25 用户批: 回放里模型 0 次 ./q → 不再指望模型自己调工具)

A  焦点票补全量: 盘前首跑只给了简版必查的票(slim), 一变成焦点(持仓 / 上一版挂单 / 04·06 提到 / 叫醒原因点名)就把完整必查塞进触发消息; 每只一天一次
B  04 选了 建 / 加 的简版票还没补过全量 → 06 提问前面直接附上完整必查(不多一轮)
ask 04 必答 "ask": 最多 3 条查询(菜单里的 ./q 命令) + 每条"查了会改变什么决定"; 不查写 "no_ask_why"
    → 代码在 04 和 06 之间本地跑(零 token, 几秒), 结果编 Q1~Q3 放 06 提问最前面
    + 代码按情景自动加查询(Q 编号接着排): 建 / 加 的票导师做过 → cases; 持仓 / 建加的票在涨跌停或被电报点名封板 → peers(events / md 查今天一律拦: 盘中没有, 回放里是偷看)
防敷衍(用户 10/25: 让 harness 约束): ask_check → 违规清单; 执行器 PAPER_ASK_GATE=retry(默认)时不在竞价 / 尾盘就打回一次(只补 ask 字段)
每晚统计: 执行器记事件「04 查询」(要了什么 / 跑成没 / 违规 / 06 引了哪些 Q), scripts/live/ask_stats.py 汇总
"""
import json
import os
import re
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
Q = ROOT / "scripts" / "paper_line" / "q.py"
PY = ROOT / "scripts" / "venv" / "Scripts" / "python.exe"
CMDS = {"similar", "window", "wminute", "sells", "sellsT", "levels", "theme", "themeof", "themetop", "same", "cases", "rule", "peers", "cbpath",
        "pattern", "events", "like", "md", "must"}
DECIDE = re.compile(r"建|加|减|清|不做|不碰|放弃|挂价|挂在|止损|止盈|仓位|几成|卖|买|撤|留|换")
MAX_ASK, MAX_PROMOTE, MAX_CHARS = 3, 4, 3500

MENU = """【查询菜单(这一步必答 ask; 你不用自己调工具 —— 写在 json 里, 代码替你查, 结果作为 Q1~Q3 放在下一条 06 消息最前面)】
D = 今天日期; <线号> = 本线; 代码写 6 位
- `./q cases <skill> <代码> D`        导师在这只票上的历史买卖, 每次带 正 / 负 / 平 标签 —— 想跟导师做这只 / 想知道他通常怎么卖
- `./q sells <skill> D <昨收浮盈%> <持有天数>`  导师同状态时当天卖不卖、卖在哪 —— 持仓要不要走、挂多高
- `./q peers <代码> D`                 同炒作逻辑邻居(龙虎榜席位风格 / 同题材 / 梯队) —— 新开仓前看同伙表现
- `./q events <代码> <历史日期>`        某只票某个历史交易日的全部事件(开板 / 回封 / 席位 / 电报 / 导师交易)+ 事件 id(今天的盘中查不到)
- `./q like <事件id>`                  同类历史事件的结果全分布(事件 id 从 events 拿) —— "这种情况历史上次日怎么走"
- `./q levels <代码> D [现价] [HH:MM]`  关键价位表 —— 定挂价 / 止损前
- `./q pattern <代码> D`               近期规律(固定形态近 10 天出现率 vs 长期 + 回测第二天出现率)
- `./q cbpath <转债代码> D`            同一只转债近 10 日开盘缺口 / 30 分钟最高 / 尾盘路径 —— 做转债
- `./q similar <转债代码> D [竞价%]`    转债相似日分布
- `./q theme <题材名> D` / `./q themeof <股票名> D`  题材生命周期(第几天 / 阶段)
- `./q rule <skill> <规则编号>`        某条导师规则全文(验证状态 / 样本 / 反例)
- `./q md <历史日期> <小节名>`         历史某天 md 某一节(今天的已经在材料里)
- `./q must <代码> <线号>`             盘前只给了简版的票的完整必查"""

ASK_REQ = ("\n" + MENU + "\n【ask 必答(harness 约束)】json 顶层写 \"ask\": [{\"cmd\": \"./q …(上面菜单里的命令, 参数写全)\", \"why\": \"查了可能改变什么决定(写清哪只票 6 位代码 + 哪个决定: 建 / 不做 / 挂价 / 止损 / 仓位 / 卖…)\"}](最多 3 条)。"
           "不查就写 \"ask\": [] 并写 \"no_ask_why\": 为什么不用查(要点名你这轮建 / 加的每只票靠哪几个 E 编号就够了)。"
           "不许照抄上一轮的 ask; 竞价段 / 尾盘可以不查。")


def slim_codes(boot_text, must_full_text):
    """盘前首跑里只给了简版的票: 首跑里这只票的必查块明显短于完整存档(< 60%)"""
    def blocks(t):
        return {m.group(1): len(m.group(0)) for m in re.finditer(r"^### (\d{6})\b[\s\S]*?(?=^### |\Z)", t or "", re.M)}
    sec = (boot_text or "").split("必查结果", 1)[-1]
    b, f = blocks(sec), blocks(must_full_text)
    return {c for c, n in f.items() if c in b and b[c] < 0.6 * n}


def full_block(must_full_text, code):
    m = re.search(r"^### " + re.escape(code) + r"\b[\s\S]*?(?=^### |\Z)", must_full_text or "", re.M)
    return m.group(0).strip() if m else ""


def _env(D, day_dir):
    e = dict(os.environ)
    e["PAPER_Q_DATE"], e["PAPER_Q_DAY"] = D, str(day_dir)
    return e


def run_one(cmd, D, day_dir, timeout=40):
    try:
        a = shlex.split(cmd.replace("\\", "/"))
    except ValueError as e:
        return False, f"(命令解析失败: {e})"
    if a and a[0] in ("./q", "q", ".\\q"):
        a = a[1:]
    if not a or a[0] not in CMDS:
        return False, f"(不在菜单里的命令: {a[0] if a else '空'})"
    a = [D if x in ("D", "<D>") else x for x in a]
    if a[0] in ("events", "md") and D in a[1:]:   # 今天的事件本体 / md 是收盘后才建的: 实盘里查不到, 回放里查到 = 偷看未来 → 一律拦
        return False, f"({a[0]} 查不了今天: 今天的事件 / md 收盘后才建, 盘中有的已经在材料里; 查历史请写具体日期)"
    try:
        r = subprocess.run([str(PY), "-X", "utf8", str(Q), *a], cwd=ROOT, env=_env(D, day_dir), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (r.stdout or "").strip() or (r.stderr or "").strip()[-400:]
        if len(out) > MAX_CHARS:
            out = out[:MAX_CHARS] + f"\n…(截断, 全文 {len(out)} 字)"
        return r.returncode == 0 and bool(r.stdout.strip()), out or "(空)"
    except subprocess.TimeoutExpired:
        return False, f"(超时 {timeout} 秒)"


def run_many(cmds, D, day_dir):
    with ThreadPoolExecutor(max_workers=4) as ex:
        return list(ex.map(lambda c: run_one(c, D, day_dir), cmds))


def auto_asks(j, held, skill, mimic, limit_codes, asked):
    """情景自动查询(代码替它想到的): 建 / 加 的票导师做过 → cases; 持仓 / 建加票在涨跌停或被点名封板 → events; 已经被要过的不重复"""
    picks = [p for p in ((j or {}).get("picks") or []) if isinstance(p, dict)]
    new = [str(p.get("code")) for p in picks if p.get("action") in ("建", "加")]
    out = []
    for c in new:
        if mimic and skill and not any(c in a and ("cases" in a or "same" in a) for a in asked):
            out.append(f"./q cases {skill} {c} D")
    for c in list(dict.fromkeys([*new, *held])):   # 涨跌停 / 点名封板 → 同炒作逻辑邻居(历史席位风格 / 同题材 / 梯队); 今天的事件本体盘中没有
        if c in limit_codes and c[:1] in "036" and not any(c in a and "peers" in a for a in asked):
            out.append(f"./q peers {c} D")
    return out[:3]


def ask_check(j, material, prev_cmds=(), crit=False):
    """→ 违规清单(空 = 过)"""
    if not isinstance(j, dict):
        return []
    if "ask" not in j:
        return ["缺 ask 字段(要查写命令 + 会改变什么决定; 不查写 ask: [] + no_ask_why)"]
    ask = j.get("ask")
    if not isinstance(ask, list):
        return ["ask 要是列表"]
    V = []
    picks = [p for p in (j.get("picks") or []) if isinstance(p, dict)]
    new = {str(p.get("code")) for p in picks if p.get("action") in ("建", "加")}
    codes = {str(p.get("code")) for p in picks} | set(re.findall(r"(?<!\d)\d{6}(?!\d)", material or ""))   # 10/25: 中文紧挨代码时 \b 不成立(北新路桥002307), 用数字边界
    cmds = []
    for i, x in enumerate(ask[:MAX_ASK], 1):
        cmd = str((x or {}).get("cmd") or "") if isinstance(x, dict) else str(x)
        why = str((x or {}).get("why") or "") if isinstance(x, dict) else ""
        cmds.append(cmd.strip())
        head = cmd.replace("./q", "").split()
        if not head or head[0] not in CMDS:
            V.append(f"ask 第 {i} 条不是菜单里的命令: {cmd[:40]}")
        cs = set(re.findall(r"(?<!\d)\d{6}(?!\d)", why))
        if not cs or not DECIDE.search(why):
            V.append(f"ask 第 {i} 条 why 没写清哪只票(6 位代码)+ 会改变哪个决定: {why[:40]}")
        elif not (cs & codes):
            V.append(f"ask 第 {i} 条 why 里的代码不在这一轮材料 / 选票里")
    if len(ask) > MAX_ASK:
        V.append(f"ask 最多 {MAX_ASK} 条")
    if cmds and prev_cmds and sorted(cmds) == sorted(prev_cmds):
        V.append("ask 和上一轮一字不差(照抄)")
    if not ask and not crit and new:
        why = str(j.get("no_ask_why") or "")
        miss = [c for c in new if c not in why]
        if len(why) < 10:
            V.append("ask 为空但 no_ask_why 没写(这轮有建 / 加, 要说清靠哪几个 E 编号就够)")
        elif miss or not re.search(r"\bE\d+\b", why):
            V.append(f"ask 为空, no_ask_why 要点名每只建 / 加的票 + 靠的 E 编号(缺: {', '.join(miss) or 'E 编号'})")
    return V


def cited(text):
    return sorted(set(re.findall(r"\bQ(\d{1,2})\b", text or "")), key=int)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    D = sys.argv[1] if len(sys.argv) > 1 else "2026-10-23"
    day = ROOT / "results" / "_replay" / D / D
    print(run_one("./q cases taoge 002307 D", D, day)[1][:500])
    print(ask_check({"picks": [{"code": "002724", "action": "建"}], "ask": []}, "002724"))
    print(ask_check({"picks": [{"code": "002724", "action": "建"}], "ask": [{"cmd": "./q peers 002724 D", "why": "002724 同伙弱就不建"}]}, "002724"))
