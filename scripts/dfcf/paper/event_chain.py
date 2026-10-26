# -*- coding: utf-8 -*-
"""event_chain.py — 全天盯盘·事件触发子链(10/21 用户令: 全天盯盘今天至少上线一条, 先上梅月路; 其余链仍是 trigger_stats 零成本影子)

谁调: trigger_stats.py 每分钟判事件, EVENT_CHAIN_SKILLS 里的链没被冷却/上限拦下时 fire() 后台拉起本脚本(无窗口)。
跑哪几步(用户 10/21 定的 D1 口径):
  价格越出策略区间 / 本链成交 / 封板炸板          → 06(+盲审): 只按新价位改挂单/撤单, 不重判市况
  开盘实况翻转 / 心跳 60 分钟 / 其他             → 02→04→05→06(+盲审), 即原盘中子链
  上面跑完 02 的 市况或态度 变了                   → 下一分钟补一轮 03→04→05→06(+盲审), 在新态度下带多空辩论重新决策
不走零 token 触发闸 A(事件本身就是闸); 同链上一轮没跑完=本次跳过; 每轮跑完调应用接口入库(同 Java PaperChainHandler)。
产物: results/_shadow/<日>/live_runs.jsonl(每轮: 时刻 / 原因 / 步骤 / 退出码 / 耗时 / 态度前后) + scripts/temp/event_chain/<链>_<日>_<HHMM>.log
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LOGD = ROOT / "scripts" / "temp" / "event_chain"
PY = ROOT / "scripts" / "venv" / "Scripts" / "python.exe"
LIGHT = re.compile(r"越出策略区间|封板|炸板|本链成交")
FULL_STEPS, LIGHT_STEPS, DEBATE_STEPS = "02,04,05,06,blind", "06,blind", "03,04,05,06,blind"


def live_skills():
    """EVENT_CHAIN_SKILLS: 环境变量优先, 否则 chain_flags.txt 同名行; 逗号分隔"""
    v = os.environ.get("EVENT_CHAIN_SKILLS")
    if v is None:
        try:
            for line in (ROOT / "scripts" / "claude_profile" / "chain_flags.txt").read_text(encoding="utf-8").splitlines():
                k, _, val = line.split("#")[0].partition("=")
                if k.strip() == "EVENT_CHAIN_SKILLS":
                    v = val
        except OSError:
            pass
    return {s.strip() for s in (v or "").split(",") if s.strip()}


def fire(skill, D, hm, why):
    """trigger_stats 调: 后台拉起一轮, 立即返回"""
    subprocess.Popen([str(PY), "-X", "utf8", str(Path(__file__)), "--skill", skill, "--date", D, "--hm", hm, "--why", json.dumps(why, ensure_ascii=False)],
                     cwd=ROOT, creationflags=NOWIN | getattr(subprocess, "DETACHED_PROCESS", 0), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _alive(pid):
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        return str(pid) in subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, creationflags=NOWIN).stdout


def _c02(rd):
    f = rd / "02_analysis.md"
    if not f.exists():
        return {}
    b = re.findall(r"```contract\s*\n([\s\S]*?)```", f.read_text(encoding="utf-8", errors="replace"))
    try:
        c = json.loads(b[-1]) if b else {}
    except ValueError:
        return {}
    return {"market_state": c.get("market_state"), "stance": c.get("stance") or "多"}


def _run(skill, date, slot, steps, dry):
    LOGD.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "CHAIN_SUBCHAIN_GATE": "0"}
    cmd = [str(PY), "-X", "utf8", "scripts/chain/run_chain.py", "--skill", skill, "--slot", slot, "--steps", steps, "--date", date] + (["--dry"] if dry else [])
    t0 = time.time()
    with (LOGD / f"{skill}_{date}_{slot}.log").open("a", encoding="utf-8") as lf:
        lf.write(f"[{dt.datetime.now():%H:%M:%S}] {' '.join(cmd)}\n")
        lf.flush()
        try:
            rc = subprocess.run(cmd, cwd=ROOT, env=env, stdout=lf, stderr=subprocess.STDOUT, timeout=40 * 60, creationflags=NOWIN).returncode
        except subprocess.TimeoutExpired:
            rc = -1
    if not dry:   # 同 PaperChainHandler.ingest: 入库失败只记日志
        try:
            q = f"skill={skill}&mode=LIVE&date={date}&slot={slot}&exitCode={rc}"
            urllib.request.urlopen(urllib.request.Request(f"http://localhost:8888/api/paper/chain/ingest?{q}", method="POST"), timeout=60).read()
        except Exception as e:   # noqa: BLE001
            with (LOGD / f"{skill}_{date}_{slot}.log").open("a", encoding="utf-8") as lf:
                lf.write(f"WARN 入库失败: {e!r}\n")
    return rc, round(time.time() - t0)


def _wx(msg, skill, dry):
    subprocess.run([str(PY), "-X", "utf8", "scripts/hermes/wx_send.py", msg, "--raw", "--src", f"event_{skill}"] + (["--dry"] if dry else []),
                   cwd=ROOT, capture_output=True, creationflags=NOWIN)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--date", default=dt.date.today().isoformat())   # YYYY-MM-DD
    ap.add_argument("--hm", required=True)   # HH:MM
    ap.add_argument("--why", default="[]")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    why = json.loads(a.why)
    date, slot = a.date.replace("-", ""), a.hm.replace(":", "")
    rd = ROOT / "results" / f"{a.skill}_chain" / f"live-{date}"
    out = ROOT / "results" / "_shadow" / a.date / ("live_runs_dry.jsonl" if a.dry else "live_runs.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    rec = {"t": a.hm, "skill": a.skill, "why": why}
    lock = LOGD / f"{a.skill}.pid"
    LOGD.mkdir(parents=True, exist_ok=True)
    try:
        held = int(lock.read_text())
    except (OSError, ValueError):
        held = 0
    if held and held != os.getpid() and _alive(held):
        rec["skipped"] = f"上一轮还在跑(pid {held})"
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return
    lock.write_text(str(os.getpid()))
    try:
        light = all(LIGHT.search(w) for w in why) and why
        steps = LIGHT_STEPS if light else FULL_STEPS
        before = _c02(rd)
        _wx(f"【{a.skill} 事件触发 {a.hm}】{'; '.join(why)[:200]} → 跑 {steps.replace(',blind', '').replace(',', '→')}", a.skill, a.dry)
        rc, sec = _run(a.skill, date, slot, steps, a.dry)
        rec.update(steps=steps, rc=rc, sec=sec, stance_before=before)
        if not light and rc in (0, 3):
            after = _c02(rd)
            rec["stance_after"] = after
            if before and after and after != before:
                s2 = (dt.datetime.strptime(a.hm, "%H:%M") + dt.timedelta(minutes=1)).strftime("%H%M")
                _wx(f"【{a.skill} {a.hm} 02 变了】{before.get('market_state')}/{before.get('stance')} → {after.get('market_state')}/{after.get('stance')}, 补跑 03 辩论→04→05→06(slot {s2})", a.skill, a.dry)
                rc2, sec2 = _run(a.skill, date, s2, DEBATE_STEPS, a.dry)
                rec.update(debate_slot=s2, rc2=rc2, sec2=sec2)
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    finally:
        if lock.exists() and lock.read_text() == str(os.getpid()):
            lock.unlink()


if __name__ == "__main__":
    main()
