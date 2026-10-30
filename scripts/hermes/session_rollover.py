# -*- coding: utf-8 -*-
"""session_rollover.py — 每个交易日 07:58 关旧的交互 Claude Code 会话、在 C:\\Users\\admin 开新会话(TODO T1, 10/20 用户批)

为什么: 主会话越长, 每一轮重读 / 重写的上下文越贵; 每个交易日开一个新会话, 上下文从零开始。用户睡前另手动重启一次。
做什么:
  ① 非交易日(a_rules 读 Java 同一份 holiday 表) → 什么都不做
  ② 找旧的交互会话: claude.exe 且命令行不含 " -p "(排除后台 claude -p), 父进程是 cmd / powershell / WindowsTerminal
  ②' 关之前先扫 jsonl(10/27 用户令, drain_pending.py): 该推微信没推的现在补推; 没答完 / 排队没送进会话的写进交接, 新会话开场带上(含 →pc1 标记)
  ③ 旧会话正忙(还有子进程在跑: bash / python / node = 我在跑工具或后台任务) → 10/20 用户定: 不推迟, 写交接到 scripts/temp/handoff_session_*.md,
     只关 claude 和窗口、子进程留着跑完, 新会话带开场提示"先读交接"
  ④ 关旧: 不忙 = taskkill /T /F claude + 它的 cmd 窗口; 忙 = 只关 claude 和 cmd 窗口(不带 /T, 子进程跑完); 父进程是 WindowsTerminal 时不关整个终端
  ⑤ 开新: cmd /k claude.cmd --dangerously-skip-permissions, 工作目录 C:\\Users\\admin(记忆和持久定时都按这个目录加载);
     平时不带开场提示(10/20 用户定: 对话由用户发起; 触发词见记忆 trigger-phrases); 写了交接时带一句"先读交接"。信任已由用户在 ~/.claude.json 标好
  ⑥ 自检: 45 秒后应恰好有 1 个交互会话且是新开的那个 → 推微信一句结果
零弹窗例外(10/20 用户批): 新开的是有意打开的主窗口, 只在交易日。本脚本自身由计划任务 ClaudeSessionRollover 经 wscript //B 无窗口启动。
用法: python session_rollover.py [--dry] [--force] [--delay N] [--no-wechat](--force = 非交易日也执行; --delay / --no-wechat 手动演练用: 演练不真推微信)
日志: scripts/temp/session_rollover.log
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
LOG = ROOT / "scripts" / "temp" / "session_rollover.log"
HOME = Path(r"C:\Users\admin")
CLAUDE_CMD = HOME / "AppData" / "Roaming" / "npm" / "claude.cmd"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEWCON = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
SHELLS = ("cmd.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe", "openconsole.exe")
BUSY = ("bash.exe", "python.exe", "pythonw.exe", "node.exe")


def log(*a):
    LOG.parent.mkdir(exist_ok=True)
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] " + " ".join(str(x) for x in a)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def procs():
    ps = "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", creationflags=NOWIN).stdout
    rows = json.loads(out) if out.strip() else []
    return rows if isinstance(rows, list) else [rows]


def sessions(rows):
    by = {r["ProcessId"]: r for r in rows}
    out = []
    for r in rows:
        if (r.get("Name") or "").lower() != "claude.exe":
            continue
        cmd = f" {r.get('CommandLine') or ''} "
        par = by.get(r.get("ParentProcessId")) or {}
        if " -p " in cmd or (par.get("Name") or "").lower() not in SHELLS:
            continue
        out.append({"pid": r["ProcessId"], "parent": par.get("ProcessId"), "parent_name": (par.get("Name") or "").lower()})
    return out


def busy_children(rows, pid):
    kids, todo = [], [pid]
    while todo:
        p = todo.pop()
        for r in rows:
            if r.get("ParentProcessId") == p:
                todo.append(r["ProcessId"])
                if (r.get("Name") or "").lower() in BUSY:
                    kids.append(f"{r['Name']}({r['ProcessId']})")
    return kids


def wechat(msg, dry):
    if dry:
        log("[dry] 微信:", msg)
        return
    subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "hermes" / "wx_send.py"), "--raw", "--src", "session_rollover", msg],
                   creationflags=NOWIN, timeout=400)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--delay", type=int, default=0, help="先等 N 秒再执行(手动演练时让当前对话先说完)")
    ap.add_argument("--no-wechat", action="store_true", help="演练用: 结果只写日志不推微信(10/20 用户令: 测试推送不真发)")
    a = ap.parse_args()
    import a_rules as AR
    today = dt.date.today().isoformat()
    if not a.force and not AR._is_trade_day_fallback(today):
        log(f"{today} 非交易日, 不换会话(非交易日你手动)")
        return 0
    if a.delay:
        time.sleep(a.delay)
    rows = procs()
    old = sessions(rows)
    busy = {s["pid"]: busy_children(rows, s["pid"]) for s in old}
    busy = {k: v for k, v in busy.items() if v}
    handoff = None
    try:   # 10/27 用户令: 关之前先扫 jsonl —— 该推微信没推的现在补推, 没答完 / 排队没送进去的带进新会话
        import drain_pending as DP
        drain = DP.run("rollover", dry=a.dry)
    except Exception as e:   # noqa: BLE001  扫描出错不耽误换会话
        log(f"扫 jsonl 出错: {e!r}")
        drain = {"carry": [], "pushed": 0, "outbox_left": 0, "lines": []}
    if busy:   # 10/20 用户定: 旧会话还有任务在跑 → 不推迟, 写交接(scripts/temp/), 只关 claude 和窗口、不杀它的子进程(后台任务继续跑完), 新会话开场提示读交接
        handoff = write_handoff(rows, busy, drain["lines"]) if not a.dry else Path("(空跑不写交接)")
        log(f"旧会话正忙 {busy} → 交接写到 {handoff}")
    elif drain["carry"]:
        handoff = write_handoff(rows, {}, drain["lines"]) if not a.dry else Path("(空跑不写交接)")
        log(f"有 {len(drain['carry'])} 条消息没处理完 → 交接写到 {handoff}")
    for s in old:
        tree = [] if busy else ["/T"]   # 忙: 只关 claude 本身和它的窗口(cmd), 子进程留着跑完; 不忙: 连同子进程一起关
        tgts = [s["pid"]] + ([s["parent"]] if s["parent_name"] in ("cmd.exe", "powershell.exe", "pwsh.exe") else [])
        log(f"关旧会话 claude pid {s['pid']}(父 {s['parent_name']} {s['parent']}) → taskkill {' '.join(tree)} /F {tgts}")
        if not a.dry:
            for t in tgts:
                subprocess.run(["taskkill", *tree, "/F", "/PID", str(t)], capture_output=True, creationflags=NOWIN)
    if not a.dry and old:
        time.sleep(3)
    args = [str(CLAUDE_CMD), "--dangerously-skip-permissions"]
    if handoff:
        marks = " ".join(c["mark"] for c in drain["carry"] if c["mark"])   # 带上 →pc1 标记: PC3 --fetch 按标记能在新会话里取到回复
        args.append((f"上一个会话换掉时还有任务在跑，" if busy else "上一个会话换掉时") +
                    (f"有 {len(drain['carry'])} 条你的消息没答完或没送进会话{(' ' + marks) if marks else ''}，" if drain["carry"] else "") +
                    f"交接在 {handoff}，先读它，接着处理里面没做完的事" + ("，要推微信的照规矩推" if any(c["need_push"] for c in drain["carry"]) else "") + "。")
    log(f"开新会话: cmd /k {' '.join(args)} (cwd {HOME})")
    if a.dry:
        log("[dry] 不实际关 / 开; 当前交互会话:", old)
        return 0
    env = {**os.environ, "DISABLE_AUTOUPDATER": "1"}   # 10/23 用户批: 交互会话不自动更新(彩排实测 00:58 自更新替换 claude.exe 3.5 分钟+, 盘中会让后台 claude -p 全起不来); 想升级手动 claude update
    newp = subprocess.Popen(["cmd.exe", "/k", *args], cwd=str(HOME), creationflags=NEWCON, env=env)
    time.sleep(45)
    # 10/29 晚用户: 重启后也必须落到当时该用的网关 / 模型; cs_switch auto 会核对时段、settings、切换器, 不对才改并在新 CLI 里 /model
    try:
        r_ = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "claude_profile" / "cs_switch.py"), "auto"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN, timeout=240)
        log(f"重启后 cs_switch auto exit={r_.returncode}: {(r_.stdout or r_.stderr).strip()[-200:]}")
    except Exception as e:   # noqa: BLE001
        log(f"重启后 cs_switch auto 异常: {e!r}")
    now = sessions(procs())
    ok = len(now) == 1 and now[0]["parent"] == newp.pid
    hm = dt.datetime.now().strftime("%H:%M")
    log(f"自检: 交互会话 {now}; 新开 cmd {newp.pid} → {'通过' if ok else '异常'}")
    drained = (f"补推了 {drain['pushed']} 条之前没推到微信的回复。" if drain["pushed"] else "") + \
              (f"{len(drain['carry'])} 条没答完的消息已带进新会话。" if drain["carry"] else "")
    wechat((f"{hm} 已换新的 Claude 会话（旧会话已关），微信中继照常可用。" + drained +
            (f"旧会话还有任务在跑，已写交接 {handoff.name} 并让新会话接手。" if busy else "")) if ok else
           f"{hm} 换会话自检异常：现在交互会话 {len(now)} 个（应为 1 个），请回 PC1 看一眼。", a.no_wechat)
    return 0 if ok else 1


def write_handoff(rows, busy, extra=()):
    """交接(机械, 不调模型): 还在跑的子进程命令行 + 后台任务输出文件 + 没处理完的消息(drain_pending) + 旧会话最近的对话摘录(你的消息 / 我的回复)"""
    now = dt.datetime.now()
    out = ROOT / "scripts" / "temp" / f"handoff_session_{now:%Y%m%d_%H%M}.md"
    by = {r["ProcessId"]: r for r in rows}
    L = [f"# 会话交接 {now:%Y-%m-%d %H:%M}（session_rollover.py 自动写）", ""]
    if extra:
        L += ["## 没处理完的消息（drain_pending 扫 jsonl 得出；逐条答，答完照规矩推微信 / 等 PC3 来取）", ""] + list(extra)
    if busy:
        L += ["## 还在跑的进程（没杀，会继续跑完；用 tasklist / 输出文件看结果）"]
    for pid, kids in busy.items():
        for k in kids:
            kp = int(k.split("(")[1].rstrip(")"))
            L.append(f"- {k}: `{(by.get(kp, {}).get('CommandLine') or '')[:300]}`")
    proj = HOME / ".claude" / "projects" / "C--Users-admin"
    js = sorted(proj.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if js:
        sid = js[-1].stem
        tdir = Path(r"C:\Users\admin\AppData\Local\Temp\claude\C--Users-admin") / sid / "tasks"
        outs = sorted(tdir.glob("*.output"), key=lambda p: p.stat().st_mtime)[-8:] if tdir.exists() else []
        L += ["", f"## 后台任务输出文件（旧会话 {sid}）"] + [f"- {p}（{dt.datetime.fromtimestamp(p.stat().st_mtime):%H:%M} 更新）" for p in outs] or ["- （无）"]
        users, said = [], []
        for l in js[-1].open(encoding="utf-8", errors="replace"):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            m = r.get("message") or {}
            c = m.get("content")
            if r.get("type") == "user" and isinstance(c, str) and not c.startswith("<"):
                users.append(c)
            elif r.get("type") == "assistant" and isinstance(c, list):
                t = " ".join(x.get("text", "") for x in c if x.get("type") == "text").strip()
                if t:
                    said.append(t)
        L += ["", "## 你最近的消息（旧到新）"] + [f"- {u[:400]}" for u in users[-8:]]
        L += ["", "## 我最近的回复（旧到新）"] + [f"- {s[:500]}" for s in said[-3:]]
        L += ["", f"完整记录：{js[-1]}"]
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    sys.exit(main())
