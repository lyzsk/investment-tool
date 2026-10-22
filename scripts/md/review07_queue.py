# -*- coding: utf-8 -*-
"""review07_queue.py — 07 复盘排队执行器(10/16 晚): check md 每轮把"标签已到/到点兜底"的链交给本进程, 同时最多跑 N 条(默认 4), 跑完一条补一条, 全部跑完退出。
同一时刻只允许一个执行器(锁文件 scripts/md/review07_queue.lock 记 pid); 已在跑时 check md 把新到的链追加进队列文件, 执行器每完成一条就重读队列。
用法(由 check_md_daily.py 起, 无窗口): python review07_queue.py [--max 4]
队列文件: scripts/md/review07_queue.jsonl  每行 {"skill","date","asof"(沙盒路径或空)}; 完成记录追加到 scripts/md/logs/review07_runs.jsonl(耗时/退出码, 供用户定串行还是并行)
"""
import argparse, json, os, subprocess, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / "scripts" / "venv" / "Scripts" / "python.exe")
Q = ROOT / "scripts" / "md" / "review07_queue.jsonl"
LOCK = ROOT / "scripts" / "md" / "review07_queue.lock"
RUNS = ROOT / "scripts" / "md" / "logs" / "review07_runs.jsonl"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def pid_alive(pid):
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, creationflags=NOWIN).stdout
        return str(pid) in out
    except Exception:   # noqa: BLE001
        return False


def runner_alive():
    try:
        return pid_alive(int(LOCK.read_text().strip()))
    except (OSError, ValueError):
        return False


def done_file(job):
    rd = ROOT / "results" / f"{job['skill']}_chain" / (f"asof-{job['date']}" if job.get("asof") else f"live-{job['date']}")
    return rd, (rd / "slots" / "review" / "07_review.md")


def enqueue(jobs):
    """check md 调: 追加队列(去重), 没有执行器在跑就起一个(无窗口后台)。返回 是否新起了执行器"""
    have = set()
    if Q.exists():
        for l in Q.read_text(encoding="utf-8").splitlines():
            if l.strip():
                j = json.loads(l)
                have.add((j["skill"], j["date"]))
    with Q.open("a", encoding="utf-8") as f:
        for j in jobs:
            if (j["skill"], j["date"]) not in have:
                f.write(json.dumps(j, ensure_ascii=False) + "\n")
    if runner_alive():
        return False
    subprocess.Popen([PY, "-X", "utf8", str(Path(__file__).resolve())], cwd=ROOT, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                     creationflags=NOWIN | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=int(os.environ.get("REVIEW07_MAX", "4")))
    a = ap.parse_args()
    if runner_alive():
        return
    LOCK.write_text(str(os.getpid()))
    running, started = {}, set()
    try:
        while True:
            jobs = [json.loads(l) for l in Q.read_text(encoding="utf-8").splitlines() if l.strip()] if Q.exists() else []
            pending = [j for j in jobs if (j["skill"], j["date"]) not in started and (j["skill"], j["date"]) not in running and not done_file(j)[1].exists()]
            while pending and len(running) < a.max:
                j = pending.pop(0)
                rd, _ = done_file(j)
                rd.mkdir(parents=True, exist_ok=True)
                lf = open(rd / "review07.log", "a", encoding="utf-8")
                cmd = [PY, "-X", "utf8", "scripts/chain/run_chain.py", "--skill", j["skill"], "--review", "--date", j["date"]] + (["--asof", j["asof"]] if j.get("asof") else [])
                p = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT, creationflags=NOWIN)
                running[(j["skill"], j["date"])] = (p, lf, time.time(), j)
                started.add((j["skill"], j["date"]))
            for k, (p, lf, t0, j) in list(running.items()):
                if p.poll() is not None:
                    lf.close()
                    RUNS.parent.mkdir(parents=True, exist_ok=True)
                    with RUNS.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"skill": j["skill"], "date": j["date"], "start": datetime.fromtimestamp(t0).isoformat(timespec="seconds"),
                                            "secs": round(time.time() - t0), "rc": p.returncode, "ok": done_file(j)[1].exists(), "max": a.max}, ensure_ascii=False) + "\n")
                    del running[k]
                    # 10/17 审计中-9: 跑完(成功或失败)立刻从队列文件删掉并允许以后重跑——原来失败的 job 留在队列里,
                    #   check md 4 小时后重发时因"队列里已有"不再追加、执行器又因 started 不重跑 → 永远"已发 2 次仍无产物"
                    started.discard(k)
                    if Q.exists():
                        keep = [l for l in Q.read_text(encoding="utf-8").splitlines() if l.strip() and (json.loads(l)["skill"], json.loads(l)["date"]) != k]
                        Q.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
            if not running and not pending:
                break
            time.sleep(15)
        # 队列清掉已完成的
        if Q.exists():
            left = [l for l in Q.read_text(encoding="utf-8").splitlines() if l.strip() and not done_file(json.loads(l))[1].exists()
                    and (json.loads(l)["skill"], json.loads(l)["date"]) not in started]
            Q.write_text("\n".join(left) + ("\n" if left else ""), encoding="utf-8")
    finally:
        try:
            LOCK.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
