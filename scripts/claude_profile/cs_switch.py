# -*- coding: utf-8 -*-
"""claude_profile/cs_switch.py — 上下班切交互 CLI 的配置(10/29 用户令; 计划任务 08:30 → gravitex / 18:30 → kimi-code, 经 cs_switch.vbs 无窗口启动)

用户实测: CLI 运行中改 settings.json 会生效, 但要在同一个 CLI 里再打一次 /model 选模型。所以:
  ① 等 CLI 空闲: 最近一轮已经答完(会话 jsonl 最后一条是 turn_duration / 没有正在写的回复)且 2 分钟内没有新写入; 最多等 WAIT_MAX 分钟,
     等不到 → 不切, 推微信告诉用户「CLI 一直在忙, 这次没切, 你空了自己切」(切到一半会让正在跑的任务后半段换模型)
  ② cs.mjs set <配置>(改 settings.json)
  ③ 往交互 CLI 注入 `/model <模型>`(cli_inject 的 AttachConsole 打字 + 单独回车), 模型 = 该配置的 ANTHROPIC_MODEL
后台 claude -p 不受影响: 它们每个进程开跑时按 rotation 选一次配置(--settings 叠加, 不读 settings.json 默认), 跑完前不会中途换
用法: python cs_switch.py [auto | gravitex | kimi-code] [--dry]   (auto = 交易日 08:30~18:30 gravitex, 其余 kimi-code; 计划任务用 auto)
"""
import argparse
import base64
import datetime as dt
import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CS = Path(r"C:\Users\admin\dev\dev-notes\others\key-switcher\scripts\cs.mjs")
PROF = Path(r"C:\Users\admin\dev\dev-notes\others\key-switcher\profiles-claude.json")
LOG = Path(__file__).resolve().parent / "cs_switch.log"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def log(*a):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] " + " ".join(str(x) for x in a) + "\n")


def latest_session():
    fs = [Path(p) for p in glob.glob(os.path.expanduser(r"~\.claude\projects\C--Users-admin\*.jsonl"))]   # 交互主会话固定开在用户目录
    return max(fs, key=lambda p: p.stat().st_mtime) if fs else None


def idle():
    f = latest_session()
    if not f:
        return True, "没有会话文件"
    age = time.time() - f.stat().st_mtime
    last = None
    with f.open("rb") as fh:
        fh.seek(max(0, f.stat().st_size - 200_000))
        for l in fh.read().decode("utf-8", "ignore").splitlines()[1:]:
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if r.get("type") in ("user", "assistant", "system"):
                last = r
    done = bool(last) and last.get("type") == "system" and last.get("subtype") == "turn_duration"
    return (done or age >= 600), f"最后一条 {last.get('type') if last else '-'}/{(last or {}).get('subtype', '')}, {int(age)} 秒没写入"


def last_ask():
    """会话里最后一条真人输入(被打断的任务是什么)"""
    f = latest_session()
    if not f:
        return "-"
    txt = "-"
    with f.open("rb") as fh:
        fh.seek(max(0, f.stat().st_size - 4_000_000))
        for l in fh.read().decode("utf-8", "ignore").splitlines()[1:]:
            try:
                r = json.loads(l)
            except ValueError:
                continue
            c = (r.get("message") or {}).get("content") if r.get("type") == "user" else None
            if isinstance(c, str) and c.strip() and not c.startswith("<"):
                txt = " ".join(c.split())
            elif isinstance(c, list):
                t = " ".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text").strip()
                if t and not t.startswith("<"):
                    txt = " ".join(t.split())
    return txt[:300]


def esc():
    r = subprocess.run([str(ROOT / "scripts" / "venv" / "Scripts" / "python.exe"), "-X", "utf8", str(ROOT / "scripts" / "hermes" / "cli_inject.py"), "enter", "esc"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN, timeout=90)
    log("Esc →", (r.stdout or r.stderr).strip()[-120:])
    time.sleep(2)   # 10/29 用户: 双保险 Esc + Ctrl+C(Ctrl+C 只按一次, 两次会退出 CLI)
    r = subprocess.run([str(ROOT / "scripts" / "venv" / "Scripts" / "python.exe"), "-X", "utf8", str(ROOT / "scripts" / "hermes" / "cli_inject.py"), "enter", "ctrlc"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN, timeout=90)
    log("Ctrl+C →", (r.stdout or r.stderr).strip()[-120:])


def model_of(name):
    try:
        d = json.loads(PROF.read_text(encoding="utf-8"))
        items = d if isinstance(d, dict) else {x.get("name"): x for x in d}
        items = items.get("profiles", items) if isinstance(items, dict) else items
        e = (items.get(name) or {})
        return (e.get("env") or e).get("ANTHROPIC_MODEL")
    except (OSError, ValueError, AttributeError):
        return None


def _procs_like(pat, sub="run"):
    """命令行含 pat 且含子命令 sub 的 node 进程号(结束 auto-switcher 正在跑的那一轮 / kimi 常驻 watch 用)"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | Where-Object {{$_.CommandLine -like '*{pat}*' -and $_.CommandLine -like '* {sub}*'}} | ForEach-Object {{ $_.ProcessId }}"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN, timeout=60)
        return [int(x) for x in r.stdout.split() if x.strip().isdigit()]
    except Exception:   # noqa: BLE001
        return []


HOL_DIR = ROOT / "inv-common" / "src" / "main" / "resources" / "holiday"
KS = CS.parent
SETTINGS = Path.home() / ".claude" / "settings.json"


def trade_day(d):
    """工作日 = 交易日口径: 周一~周五且不在法定假日表(holiday/<年>.json, true=休市; 调休补班的周末交易所不开市 → 不算)"""
    try:
        hol = json.loads((HOL_DIR / f"{d.year}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        hol = {}
    return d.weekday() < 5 and not hol.get(d.isoformat(), False)


def want(now=None):
    """10/29 晚用户令: 交易日 08:30~18:30 → gravitex(Sonnet 5.5), 其余时间 → kimi 订阅(kimi-code; 撞窗口由 kimi 切换器换 kimi-api)"""
    now = now or dt.datetime.now()
    return "gravitex" if trade_day(now.date()) and "08:30" <= now.strftime("%H:%M") < "18:30" else "kimi-code"


def current_family():
    try:
        u = (json.loads(SETTINGS.read_text(encoding="utf-8-sig")).get("env") or {}).get("ANTHROPIC_BASE_URL", "")
    except (OSError, ValueError):
        return None
    return "gravitex" if "gravitex" in u else "kimi" if ("kimi" in u or "moonshot" in u) else None


def current_model():
    try:
        return (json.loads(SETTINGS.read_text(encoding="utf-8-sig")).get("env") or {}).get("ANTHROPIC_MODEL")
    except (OSError, ValueError):
        return None


def node(js, cmd):
    r_ = subprocess.run(["node", str(KS / js), cmd], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN, timeout=120)
    log(f"{js} {cmd}:", (r_.stdout or r_.stderr).strip()[-200:])


def stop_gravitex_switcher():
    """关掉 gravitex 切换器: 禁用计划任务 auto-switcher + 结束正在跑(随机延后 0~5 分钟)的那一轮 —— 10/29 22:03 就是那一轮把 kimi 切回 gravitex"""
    node("auto-switcher.mjs", "stop")
    subprocess.run(["schtasks", "/End", "/TN", "auto-switcher"], capture_output=True, creationflags=NOWIN, timeout=60)
    for p_ in _procs_like("auto-switcher.mjs"):
        subprocess.run(["taskkill", "/PID", str(p_), "/F"], capture_output=True, creationflags=NOWIN)
        log("结束在跑的 auto-switcher.mjs pid", p_)


def stop_kimi_switcher():
    """关掉 kimi 切换器: 结束常驻进程(vbs 拉起的 watch) + 删计划任务 auto-switcher-kimi / auto-switcher-kimi-return(它自己的 stop 全做)"""
    node("auto-switcher-kimi.mjs", "stop")
    for p_ in _procs_like("auto-switcher-kimi.mjs", "watch"):
        subprocess.run(["taskkill", "/PID", str(p_), "/F"], capture_output=True, creationflags=NOWIN)
        log("结束 auto-switcher-kimi 常驻进程 pid", p_)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("profile", nargs="?", default="auto", help="auto(按时段定) | gravitex | kimi-code")
    ap.add_argument("--wait-max", type=int, default=30)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--interrupt", action="store_true", help="先 Esc 终止 CLI 正在做的事再切; 默认不切任务, CLI 忙也能 /model")
    a = ap.parse_args()
    target = want() if a.profile == "auto" else a.profile
    fam = "gravitex" if target.startswith("gravitex") else "kimi"
    cur = current_family()
    m = model_of(target)
    log(f"[{a.profile}] 目标 {target}({m}), 当前 settings = {cur}" + (" [dry]" if a.dry else ""))
    if a.dry:
        return 0
    # ① 先关另一边的切换器(不然它会把 settings 改回去), 再开这一边的
    if fam == "gravitex":
        stop_kimi_switcher()
    else:
        stop_gravitex_switcher()
    if cur == fam and current_model() == m and a.profile == "auto":   # 同网关且模型也对(比如开机补跑): 只保证切换器, 不改 settings、不动 CLI
        node("auto-switcher.mjs" if fam == "gravitex" else "auto-switcher-kimi.mjs", "start")
        log(f"已在 {fam} / {m}, 只确认切换器")
        return 0
    ok, why = idle()
    stopped = None
    if not ok:
        log(f"CLI 在忙({why}); " + ("按 --interrupt 终止" if a.interrupt else "不终止, 直接切 settings 并注入 /model"))   # 10/30 用户: 忙时也能 /model
    if a.interrupt:
        stopped = last_ask()
        esc()
        time.sleep(5)
    # ② 改 settings.json(cs.mjs set: 按 profiles-claude.json 的 env + dev 目录下的 key 文件)
    target_ = "gravitex" if fam == "gravitex" else "kimi-code"   # 10/29 晚用户: 默认 key = dev 下 gravitex-api-key.txt / kimi-code-api-key.txt(订阅); 之后的轮换交给各自切换器
    r = subprocess.run(["node", str(CS), "set", target_], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
    log("cs set:", (r.stdout or r.stderr).strip()[-200:])
    # ③ 开这一边的切换器(gravitex: 按 auto-switcher-config.json 在几把 gravitex key 间轮换; kimi: 订阅优先, 撞 5 小时 / 7 天窗口换 kimi-api)
    node("auto-switcher.mjs" if fam == "gravitex" else "auto-switcher-kimi.mjs", "start")
    # ④ 在当前唯一的 CLI 里 /model <模型> + 回车确认「Switch model?」
    if m:
        msg = f"/model {m}"
        r2 = subprocess.run([str(ROOT / "scripts" / "venv" / "Scripts" / "python.exe"), "-X", "utf8", str(ROOT / "scripts" / "hermes" / "cli_inject.py"), "send",
                             base64.b64encode(msg.encode("utf-8")).decode()], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN, timeout=120)
        log("注入", msg, "→", (r2.stdout or r2.stderr).strip()[-200:])
        time.sleep(4)
        r3 = subprocess.run([str(ROOT / "scripts" / "venv" / "Scripts" / "python.exe"), "-X", "utf8", str(ROOT / "scripts" / "hermes" / "cli_inject.py"), "enter", "cr"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN, timeout=90)
        log("确认 Switch model? 回车 →", (r3.stdout or r3.stderr).strip()[-120:])
    log(f"切完: settings = {current_family()}")
    if stopped:
        try:
            sys.path.insert(0, str(ROOT / "scripts" / "hermes"))
            import wx_send
            wx_send.send(f"【切配置 {dt.datetime.now():%H:%M}】已切到 {target}({m})。切之前 CLI 在忙, 我按 Esc 停掉了这个任务: {stopped[:200]} —— 要继续就在 CLI 里再说一次",
                         src="cs_switch", raw=True, wait=60, force=True)
        except Exception as e:   # noqa: BLE001
            log("推微信失败", repr(e))
    return 0

if __name__ == "__main__":
    sys.exit(main())
