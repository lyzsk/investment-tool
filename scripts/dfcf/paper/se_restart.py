# -*- coding: utf-8 -*-
"""se_restart.py — 无窗口重启一条 se_exec(10/21): 杀旧进程树(只杀 cmdline 是 se_exec --skill <链> 的) → 起新进程 → 等心跳 + 续跑恢复事件, 打印版本号
用法: python se_restart.py --skill meiyuelu [--date D] [--no-kill]
拒绝条件: 该链有重定正在算(heartbeat pending=True 或 最后一条 重定 之后没落地), 除非 --force(会丢掉在算的那轮, 续跑后补叫)
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PY = ROOT / "scripts" / "venv" / "Scripts" / "python.exe"
TMP = ROOT / "scripts" / "temp"
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def procs(skill):
    out = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        c = " ".join(p.info["cmdline"] or [])
        if "se_exec.py" in c and f"--skill {skill}" in c and "--selftest" not in c:
            out.append(p)
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    d = ROOT / "results" / "_live" / a.date / f"se_{a.skill}"
    old = procs(a.skill)
    if old and not a.force:
        evs = [json.loads(l) for l in (d / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()] if (d / "events.jsonl").exists() else []
        n_all = sum(e.get("kind") == "重定" for e in evs)
        done = len(list((d / "strategies").glob("*.json"))) + sum(e.get("kind") in ("重定失败", "重定异常") for e in evs)
        if n_all > done:
            sys.exit(f"{a.skill} 有一轮重定还在算(重定 {n_all} 次 / 落地+失败 {done}), 等它落地再重启; 硬要重启加 --force")
    for p in old:   # 先杀子(真 python)再杀父(venv launcher), 连带它拉起的 claude 子进程
        try:
            for ch in p.children(recursive=True):
                ch.kill()
            p.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(old, timeout=10)
    left = [p for p in procs(a.skill) if p.is_running()]
    if left:
        sys.exit(f"旧进程没杀干净: {[p.pid for p in left]}")
    t0 = time.time()
    log = (TMP / f"se_{a.skill}_{a.date[5:7]}{a.date[8:]}.log").open("a", encoding="utf-8")
    log.write(f"\n==== {dt.datetime.now():%H:%M:%S} se_restart 重启 ====\n")
    log.flush()
    p = subprocess.Popen([str(PY), "-X", "utf8", "scripts/dfcf/paper/se_exec.py", "--skill", a.skill, "--date", a.date], cwd=ROOT, creationflags=FLAGS,
                         stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, close_fds=True)
    (TMP / f"se_{a.skill}.pid").write_text(str(p.pid))
    for _ in range(60):
        time.sleep(1)
        if p.poll() is not None:
            sys.exit(f"新进程退出了 rc={p.returncode}, 看 {log.name}")
        hb = d / "heartbeat.txt"
        if hb.exists() and hb.stat().st_mtime > t0:
            evs = [json.loads(l) for l in (d / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
            rec = [e for e in evs if e.get("kind") == "续跑恢复"]
            print(f"OK pid={p.pid} 心跳: {hb.read_text(encoding='utf-8').strip()}")
            print("续跑恢复:", json.dumps(rec[-1] if rec else None, ensure_ascii=False))
            return
    sys.exit(f"60 秒没等到心跳, pid={p.pid}")


if __name__ == "__main__":
    main()
