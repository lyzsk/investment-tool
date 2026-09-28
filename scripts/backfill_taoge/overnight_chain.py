# overnight_chain.py — 通宵看门狗(2026-09-28 凌晨, 用户睡觉任务)
# 职责: 不依赖 Claude 会话存活, 把串行链第三环接上并维持到早上:
#   1) 等 md-sweep#3 收尾(看 backfill.log 新增 "md 补写清扫结束")
#   2) 立刻跑一轮 --distill-sweep
#   3) 之后每 20 分钟再扫一轮(主回填进程是老代码无 distill 钩子, 新完成的天靠这里补), 直到 08:30
# 幂等: distill_state.json 账本去重, 重扫零成本; 锁文件防并发重叠
import datetime as dt
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent.parent
LOG = SCRIPT_DIR / "backfill.log"
LOCK = SCRIPT_DIR / "distill_sweep.lock"
INSTANCE_LOCK = SCRIPT_DIR / "watchdog_instance.lock"  # 单实例锁(9/28 双开事故立法)


def ensure_single_instance():
    """pid 锁+tasklist 活体验证: 已有活实例则本实例退出; 死锁自动清"""
    if INSTANCE_LOCK.exists():
        try:
            pid = int(INSTANCE_LOCK.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            pid = -1
        alive = False
        if pid > 0:
            try:
                r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, timeout=15)
                alive = str(pid) in r.stdout
            except (OSError, subprocess.TimeoutExpired):
                alive = True  # 证据不足保守退出
        if alive:
            print(f"看门狗已在运行(pid={pid}), 本实例退出", flush=True)
            sys.exit(0)
        INSTANCE_LOCK.unlink(missing_ok=True)
    INSTANCE_LOCK.write_text(str(os.getpid()), encoding="utf-8")
    import atexit
    atexit.register(lambda: INSTANCE_LOCK.unlink(missing_ok=True))
PY = ROOT / "scripts" / "venv" / "Scripts" / "python.exe"
END_AT = dt.datetime.now().replace(hour=18, minute=0, second=0, microsecond=0)  # 2026-09-28 用户改: 链条跑到 18:00
if END_AT <= dt.datetime.now():
    END_AT += dt.timedelta(days=1)
POLL = 60
ROUND_GAP = 20 * 60


def log(msg):
    line = f"[{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [watchdog] {msg}"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def sweep_alive() -> bool:
    """有没有活着的 --distill-sweep 进程(锁的真实含义; 9/28 孤儿场景: 看门狗死了但 sweep 还在跑)。
    9/28 04:35 修复自匹配 bug: 查询串本身含 '--distill-sweep', powershell 查询进程永远匹配自己 → 永远 True。
    修法: 只认 python.exe 且排除查询进程自身 PID。"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.Name -eq 'python.exe' -and $_.CommandLine -like '*--distill-sweep*' } | Measure-Object | Select-Object -ExpandProperty Count"],
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip().isdigit() and int(r.stdout.strip()) > 0
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return True  # 查不到就当活着, 保守不并发


def run_distill_sweep():
    if LOCK.exists():
        if sweep_alive():
            log("上一轮 distill-sweep 还在跑(锁在且进程活), 本轮跳过")
            return
        LOCK.unlink(missing_ok=True)  # 孤儿锁: 进程已死, 清掉再开新轮
        log("清除孤儿锁(锁在但进程已死)")
    try:
        LOCK.write_text(str(dt.datetime.now()), encoding="utf-8")
        r = subprocess.run([str(PY), str(ROOT / "scripts" / "backfill_taoge.py"), "--distill-sweep"],
                           cwd=str(ROOT), timeout=4 * 3600)
        log(f"distill-sweep 一轮结束 exit={r.returncode}")
    except subprocess.TimeoutExpired:
        log("distill-sweep 单轮超时 4h, 强杀下轮再来")
    except OSError as e:
        log(f"distill-sweep 启动失败: {e}")
    finally:
        LOCK.unlink(missing_ok=True)


def main():
    ensure_single_instance()  # 9/28 双开事故立法
    offset = LOG.stat().st_size if LOG.exists() else 0
    if "--now" in sys.argv:
        # 接棒已发生(或 md 不需等)时直进 distill 循环, 跳过等收尾阶段(9/28: 重启看门狗用)
        log(f"看门狗启动(--now 直进 distill 循环), 结束期限 {END_AT:%m-%d %H:%M}")
    else:
        log(f"看门狗启动, 等待 md-sweep 收尾(日志偏移 {offset}), 结束期限 {END_AT:%m-%d %H:%M}")
        while dt.datetime.now() < END_AT:
            try:
                with open(LOG, "r", encoding="utf-8", errors="ignore") as f:
                    f.seek(offset)
                    new = f.read()
                    offset = f.tell()
                if "md 补写清扫结束" in new:
                    log("检测到 md-sweep 收尾, 接棒 distill-sweep")
                    break
            except OSError:
                pass
            time.sleep(POLL)
    while dt.datetime.now() < END_AT:
        if (ROOT / "scripts" / "PAUSE").exists():  # 与 backfill_taoge.py 的 PAUSE_FILE 同路径(scripts/PAUSE)
            log("PAUSE 在, 本轮 distill-sweep 跳过(随叫随停 9/28)")
        else:
            run_distill_sweep()
        time.sleep(ROUND_GAP)
    log(f"到点 {END_AT:%H:%M}, 看门狗收工(distill 账本幂等, 随时可再 --distill-sweep)")


if __name__ == "__main__":
    main()
