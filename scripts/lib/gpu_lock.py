# -*- coding: utf-8 -*-
"""gpu_lock.py — 全机唯一的 GPU 锁(10/17 晚, 审计② Q-8: B站三个视频任务同分钟起 + "先查显存再启动"有竞态, 两个 7B 可能叠加爆显存)

规则: 要用显卡的进程(B站 process_video 的本地纠错 / 视觉、llm_batch_tzzb 32B、手动回填)先拿锁, 用完放; 同一时刻只有一个。
  锁文件 downloads/_gpu/gpu.lock = {"pid", "label", "since"}; 用 O_EXCL 原子创建(两个进程同一秒抢也只有一个成功)。
  持有者进程已死 = 残留, 自动清掉; 持有超过 MAX_HOLD_H 小时也当残留(防进程挂死占锁)。
  急停: 建 downloads/_gpu/STOP —— 所有等锁的进程不再开新的 GPU 活(已在跑的跑完当前这一段), 删掉即恢复。
  Java 侧(B站视频任务)拉进程前读同一个锁文件, 有人持有就本轮跳过, 不认领、不耗重试次数。
用法(代码): with gpu_slot("bili-vision BVxxx", wait_min=25): ...   拿不到 → 抛 GpuBusy
用法(命令行, 突发情况):
  python gpu_lock.py status            谁占着、占了多久、进程还在不在、显存
  python gpu_lock.py clear [--force]   清残留锁(持有者还活着要加 --force, 会提示先结束那个进程)
  python gpu_lock.py stop | resume     急停 / 恢复
  python gpu_lock.py selftest
"""
import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "downloads" / "_gpu"
LOCK = DIR / "gpu.lock"
STOP = DIR / "STOP"
MAX_HOLD_H = 3
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class GpuBusy(RuntimeError):
    pass


def _alive(pid):
    try:
        import psutil
        return psutil.pid_exists(int(pid))
    except Exception:   # noqa: BLE001
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, creationflags=NOWIN)
        return str(pid) in r.stdout


def holder():
    try:
        return json.loads(LOCK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _stale(h):
    if not h:
        return LOCK.exists() and time.time() - LOCK.stat().st_mtime > 60   # 空文件 / 坏文件放了 1 分钟以上
    try:
        age_h = (datetime.now() - datetime.fromisoformat(h["since"])).total_seconds() / 3600
    except (KeyError, ValueError):
        age_h = 0
    return not _alive(h.get("pid", 0)) or age_h > MAX_HOLD_H


def try_acquire(label):
    DIR.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, json.dumps({"pid": os.getpid(), "label": label, "since": datetime.now().isoformat(timespec="seconds")},
                                    ensure_ascii=False).encode("utf-8"))
            os.close(fd)
            return True
        except FileExistsError:
            if _stale(holder()):
                LOCK.unlink(missing_ok=True)
                continue
            return False
    return False


def release():
    h = holder()
    if h and h.get("pid") == os.getpid():
        LOCK.unlink(missing_ok=True)


@contextlib.contextmanager
def gpu_slot(label, wait_min=25, poll=20):
    t0 = time.time()
    while True:
        if not STOP.exists() and try_acquire(label):
            break
        if time.time() - t0 > wait_min * 60:
            h = holder()
            raise GpuBusy(("GPU 急停中(downloads/_gpu/STOP)" if STOP.exists() else f"GPU 被占: {h}") + f", 等了 {wait_min} 分钟")
        time.sleep(poll)
    try:
        yield
    finally:
        release()


def vram():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader"], capture_output=True,
                           text=True, timeout=15, creationflags=NOWIN)
        return r.stdout.strip()
    except Exception:   # noqa: BLE001
        return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "clear", "stop", "resume", "selftest"])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.cmd == "selftest":
        return selftest()
    h = holder()
    if a.cmd == "status":
        print(json.dumps({"held": bool(h) or LOCK.exists(), "holder": h, "holder_alive": bool(h) and _alive(h.get("pid", 0)),
                          "stale": _stale(h) if LOCK.exists() else None, "stop": STOP.exists(), "vram": vram()}, ensure_ascii=False))
    elif a.cmd == "clear":
        if h and _alive(h.get("pid", 0)) and not a.force:
            print(f"持有者 pid {h['pid']}({h.get('label')}) 还活着; 先结束它(taskkill /PID {h['pid']} /T /F)或加 --force")
            return 1
        LOCK.unlink(missing_ok=True)
        print("已清锁")
    elif a.cmd == "stop":
        DIR.mkdir(parents=True, exist_ok=True)
        STOP.write_text(datetime.now().isoformat(), encoding="utf-8")
        print("已急停: 新的 GPU 活不再开始(在跑的会跑完当前一段); resume 恢复")
    elif a.cmd == "resume":
        STOP.unlink(missing_ok=True)
        print("已恢复")
    return 0


def selftest():
    import tempfile
    global DIR, LOCK, STOP
    keep = (DIR, LOCK, STOP)
    try:
        DIR = Path(tempfile.mkdtemp())
        LOCK, STOP = DIR / "gpu.lock", DIR / "STOP"
        assert try_acquire("a") and not try_acquire("b"), "第二个不应拿到"
        release()
        assert try_acquire("c"), "放锁后应能拿到"
        LOCK.write_text(json.dumps({"pid": 999999, "label": "死进程", "since": datetime.now().isoformat()}), encoding="utf-8")
        assert try_acquire("d"), "持有者已死应自动清"
        release()
        STOP.write_text("x")
        try:
            with gpu_slot("e", wait_min=0.02, poll=0.5):
                raise AssertionError("急停时不应拿到")
        except GpuBusy:
            pass
        STOP.unlink()
        with gpu_slot("f", wait_min=0.02):
            assert holder()["label"] == "f"
        assert not LOCK.exists(), "退出 with 应放锁"
        print("GPU_LOCK SELFTEST PASS")
    finally:
        DIR, LOCK, STOP = keep


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main() or 0)
