# -*- coding: utf-8 -*-
"""claude_profile/cs_switch.py — 上下班切交互 CLI 的配置(10/29 用户令; 计划任务 08:30 → gravitex / 18:30 → kimi-code, 经 cs_switch.vbs 无窗口启动)

用户实测: CLI 运行中改 settings.json 会生效, 但要在同一个 CLI 里再打一次 /model 选模型。所以:
  ① 等 CLI 空闲: 最近一轮已经答完(会话 jsonl 最后一条是 turn_duration / 没有正在写的回复)且 2 分钟内没有新写入; 最多等 WAIT_MAX 分钟,
     等不到 → 不切, 推微信告诉用户「CLI 一直在忙, 这次没切, 你空了自己切」(切到一半会让正在跑的任务后半段换模型)
  ② cs.mjs set <配置>(改 settings.json)
  ③ 往交互 CLI 注入 `/model <模型>`(cli_inject 的 AttachConsole 打字 + 单独回车), 模型 = 该配置的 ANTHROPIC_MODEL
后台 claude -p 不受影响: 它们每个进程开跑时按 rotation 选一次配置(--settings 叠加, 不读 settings.json 默认), 跑完前不会中途换
用法: python cs_switch.py gravitex | kimi-code [--wait-max 30] [--dry]
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("profile")
    ap.add_argument("--wait-max", type=int, default=30)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    ok, why = idle()
    stopped = None
    if not ok:   # 10/29 用户定: 有任务在跑 → 马上停(按 Esc 打断)再切, 推微信说停了什么
        stopped = last_ask()
        log(f"切 {a.profile}: CLI 在忙({why}), 按 Esc 打断; 停掉的任务: {stopped}")
        if not a.dry:
            esc()
            time.sleep(5)
    m = model_of(a.profile)
    log(f"切 {a.profile}: 模型 {m}" + (" [dry]" if a.dry else ""))
    if a.dry:
        return 0
    r = subprocess.run(["node", str(CS), "set", a.profile], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
    log("cs set:", (r.stdout or r.stderr).strip()[-200:])
    if m:
        msg = f"/model {m}"
        r2 = subprocess.run([str(ROOT / "scripts" / "venv" / "Scripts" / "python.exe"), "-X", "utf8", str(ROOT / "scripts" / "hermes" / "cli_inject.py"), "send",
                             base64.b64encode(msg.encode("utf-8")).decode()], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN, timeout=120)
        log("注入", msg, "→", (r2.stdout or r2.stderr).strip()[-200:])
        time.sleep(4)   # 10/29 用户指出: /model 后还会弹「Switch model?」确认框(1 Yes / 2 No), 必须再按一次回车选 Yes, 否则不会真切
        r3 = subprocess.run([str(ROOT / "scripts" / "venv" / "Scripts" / "python.exe"), "-X", "utf8", str(ROOT / "scripts" / "hermes" / "cli_inject.py"), "enter", "cr"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN, timeout=90)
        log("确认 Switch model? 回车 →", (r3.stdout or r3.stderr).strip()[-120:])
    if stopped:
        try:
            sys.path.insert(0, str(ROOT / "scripts" / "hermes"))
            import wx_send
            wx_send.send(f"【切配置 {dt.datetime.now():%H:%M}】已切到 {a.profile}({m})。切之前 CLI 在忙, 我按 Esc 停掉了这个任务: {stopped[:200]} —— 要继续就在 CLI 里再说一次",
                         src="cs_switch", raw=True, wait=60, force=True)
        except Exception as e:   # noqa: BLE001
            log("推微信失败", repr(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
