# -*- coding: utf-8 -*-
"""facts_pack.py — 策略执行器(exec_base)的事实包(零 token; 10/21 抢救版: 旧 paper 决策链停了, 抢救版自己备事实包)
生成方式同 run_chain.build_facts + slim_facts: node scripts/dfcf/paper/facts.mjs --slot HHMM --date D → scripts/dfcf/paper/facts/<D>/<slot>/facts.md(共享),
再按本链瘦身(昨日账本状态只留本链账本行; 导师信号速览只留本导师小节 + 发哥)写到 results/_live/<D>/se_<skill>/facts.txt。不调任何模型。
省请求: 三条链共享同一份 facts.md; 最新一份不满 MIN_AGE 秒不重建; 同一时刻只许一个构建(锁 = facts/<D>/.se_build.lock, 内容=node pid; 同时占 run_chain 的 slot 目录 .build.lock, 土豆链同 slot 会等我们)。
用法: python facts_pack.py --skill meiyuelu [--date D] [--build(允许现做一份)] [--wait 60]
"""
import argparse
import datetime as dt
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import mentors   # noqa: E402

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FACTS = HERE / "facts"
MIN_AGE = 1800   # 最新共享 facts.md 不满 30 分钟就复用, 不重建(昨天旧链一天 11 个 slot ≈ 半小时一份; 防三条链各打一遍东财/腾讯)
LOCK_MAX = 600   # 构建锁超过 10 分钟当残留


def latest(D):
    fs = [f for f in (FACTS / D).glob("*/facts.md") if f.stat().st_size > 0]
    return max(fs, key=lambda f: f.stat().st_mtime) if fs else None


def slim(t, skill):
    """同 run_chain.slim_facts(10/16 审计#5/#7)"""
    src, kw = mentors.book(skill), mentors.head(skill)

    def section(text, head):
        i = text.find(head)
        if i < 0:
            return None
        j = i + len(head)
        while True:
            j = text.find("\n## ", j)
            if j < 0:
                return i, len(text)
            if not re.match(r"\n## [ABC]-", text[j:j + 8]):
                return i, j
            j += 4
    s1 = section(t, "## 昨日账本状态")
    if s1:
        body = t[s1[0]:s1[1]].split("\n")
        keep = [l for l in body if not re.match(r"## [ABC]-", l) or l.startswith(f"## {src}:")]
        t = t[:s1[0]] + "\n".join(keep) + t[s1[1]:]
    s2 = section(t, "## 导师信号速览")
    if s2 and kw:
        parts = t[s2[0]:s2[1]].split("\n### ")
        keep = [x for x in parts[1:] if x.startswith(kw) or x.startswith("发哥")]
        t = t[:s2[0]] + parts[0] + "".join("\n### " + x for x in keep) + "\n(其余导师的规则不在本链范围, 已省略)" + t[s2[1]:]
    return t


def _alive(pid):
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:   # noqa: BLE001
        return True


def _lock_busy(lock):
    if not lock.exists():
        return False
    try:
        pid = int(lock.read_text().strip() or 0)
    except (OSError, ValueError):
        pid = 0
    if time.time() - lock.stat().st_mtime > LOCK_MAX or (pid and not _alive(pid)):
        lock.unlink(missing_ok=True)
        return False
    return True


def build(D, wait=60, slot=None):
    """现做一份(slot=当前 HHMM)。返回 (facts.md 或 None, 说明)。wait 秒内没做完不杀进程, 后台线程等它做完再放锁(下次重定就能用)"""
    lock = FACTS / D / ".se_build.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    if _lock_busy(lock):
        return None, "他链正在构建"
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        return None, "他链正在构建"
    slot = slot or dt.datetime.now().strftime("%H%M")
    sd = FACTS / D / slot
    if (sd / "facts.md").exists():   # 这个 slot 别人(土豆链)已建过 → 直接用
        lock.unlink(missing_ok=True)
        return sd / "facts.md", f"复用他链同 slot {slot}"
    sd.mkdir(parents=True, exist_ok=True)
    rlock = sd / ".build.lock"
    try:
        fd = os.open(str(rlock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        lock.unlink(missing_ok=True)
        return None, f"slot {slot} 他链正在构建"
    try:
        p = subprocess.Popen(["node", "scripts/dfcf/paper/facts.mjs", "--slot", slot, "--date", D], cwd=ROOT, creationflags=NOWIN,
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except Exception as e:   # noqa: BLE001
        lock.unlink(missing_ok=True)
        rlock.unlink(missing_ok=True)
        return None, f"起不来: {e!r}"[:200]
    lock.write_text(str(p.pid))
    res = {}

    def waiter():
        try:
            res["err"] = (p.communicate()[1] or b"").decode("utf-8", "replace")[-200:]
        finally:
            lock.unlink(missing_ok=True)
            rlock.unlink(missing_ok=True)
    th = threading.Thread(target=waiter, daemon=True)
    th.start()
    th.join(wait)
    out = FACTS / D / slot / "facts.md"
    if th.is_alive():
        return None, f"slot {slot} {wait}s 内没做完(后台继续)"
    if p.returncode != 0 or not out.exists():
        return None, f"slot {slot} 构建败 rc={p.returncode}: {res.get('err', '')}"
    return out, f"现做 slot {slot}"


def refresh(skill, D, out_dir, allow_build=True, wait=60):
    """写 out_dir/facts.txt; 返回 {ok, src, note}。任何失败只返回说明, 不抛(fail-open)"""
    note = ""
    try:
        cur = latest(D)
        fresh = cur and time.time() - cur.stat().st_mtime < MIN_AGE
        if allow_build and not fresh:
            f, note = build(D, wait)
            cur = f or latest(D)
        if not cur:
            return {"ok": False, "src": None, "note": note or "今天没有任何 facts.md"}
        t = slim(cur.read_text(encoding="utf-8"), skill)
        dst = Path(out_dir) / "facts.txt"
        tmp = dst.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(t)
        os.replace(tmp, dst)
        return {"ok": True, "src": str(cur.relative_to(ROOT)).replace("\\", "/"), "note": note or "复用最近一份"}
    except Exception as e:   # noqa: BLE001
        return {"ok": False, "src": None, "note": f"{note} 异常 {e!r}"[:300]}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--wait", type=int, default=60)
    a = ap.parse_args()
    print(refresh(a.skill, a.date, ROOT / "results" / "_live" / a.date / f"se_{a.skill}", a.build, a.wait))


if __name__ == "__main__":
    main()
