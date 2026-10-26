# -*- coding: utf-8 -*-
"""fleet.py — paper v3 总控拉起 / 守护(10/22 晚建; 21:4x 改: 不再一本账一个进程, 拉起一个总控 orchestrator.py 管全部账本 + 统一叫醒队列)

谁调: 计划任务 PaperLineFleet(工作日 08:52) + check md --only mix(交易日每 5 分钟)调 --ensure: 总控没在跑、还有账本今天没收盘 → 后台拉起(无窗口)
开关: chain_flags.txt `PAPER_FLEET`(1 = 拉; 0 = 整体关) · `PAPER_LINES`(逗号分隔线号; 空 = lines.json 全部)
时段: 08:50~14:57 之间才拉(各账本等到 09:00 + 序号 × 20 秒才启动会话)
防双开: 总控的 pid 锁(scripts/temp/line_orchestrator.lock); 全部账本今天 summary.md 都有 = 已收盘, 不再拉
日志: logs/inv-stock/paper/live/line_fleet/<日>.log(拉起记录) · 总控输出 logs/inv-stock/paper/live/line_exec/orchestrator_<日>.log
用法: python fleet.py --ensure [--date D] | --status [--date D]
"""
import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import line_dirs as LDS   # noqa: E402  10/25 账本目录命名(live_<skill> / paper_<id>)
V3 = ROOT / "scripts" / "paper_line"
sys.path[:0] = [str(V3), str(ROOT / "scripts" / "dfcf" / "paper"), str(ROOT / "scripts" / "lib"), str(ROOT / "scripts" / "quotes")]
from exec_base import flag   # noqa: E402
import pack   # noqa: E402

PY = ROOT / "scripts" / "venv" / "Scripts" / "python.exe"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
LOGD = ROOT / "logs" / "inv-stock" / "paper" / "live"


def line_ids(D=None):
    v = "" if pack.live_on() else flag("PAPER_LINES", "")   # 实盘线: 线按当天名单动态生成, PAPER_LINES 不管
    allL = list(pack.lines(D))
    return [x.strip() for x in v.split(",") if x.strip() in allL] if v.strip() else allL


def alive(line_id):
    f = ROOT / "scripts" / "temp" / f"line_{line_id}.lock"
    try:
        import psutil
        pid = int(f.read_text().strip() or 0)
        cmd = " ".join(psutil.Process(pid).cmdline())
        return bool(pid) and "executor.py" in cmd and f"--line {line_id}" in cmd
    except Exception:   # noqa: BLE001
        return False


def log(D, msg):
    (LOGD / "line_fleet").mkdir(parents=True, exist_ok=True)
    with (LOGD / "line_fleet" / f"{D}.log").open("a", encoding="utf-8") as f:
        f.write(f"[{dt.datetime.now():%H:%M:%S}] {msg}\n")


def orch_alive():
    f = ROOT / "scripts" / "temp" / "line_orchestrator.lock"
    try:
        import psutil
        pid = int(f.read_text().strip() or 0)
        return bool(pid) and "orchestrator.py" in " ".join(psutil.Process(pid).cmdline())
    except Exception:   # noqa: BLE001
        return False


def ensure(D):
    import a_rules as AR
    hm = dt.datetime.now().strftime("%H%M")
    t0 = "0825" if pack.live_on() else "0850"   # 10/24 实盘线: 08:28 拉起, 08:35 起盘前首跑(串行)
    if flag("PAPER_FLEET", "0") != "1" or not AR._is_trade_day_fallback(D) or not (t0 <= hm < "1457"):
        return
    if orch_alive() or all((ROOT / "results" / "_live" / D / LDS.ldir(lid) / "summary.md").exists() for lid in line_ids(D)):
        return
    (LOGD / "line_exec").mkdir(parents=True, exist_ok=True)
    out = open(LOGD / "line_exec" / f"orchestrator_{D}.log", "a", encoding="utf-8")
    p = subprocess.Popen([str(PY), "-X", "utf8", str(V3 / "orchestrator.py"), "--date", D], cwd=ROOT, creationflags=NOWIN, stdout=out, stderr=subprocess.STDOUT)
    log(D, f"拉起总控 pid={p.pid}")


def status(D):
    print(f"总控: {'在跑' if orch_alive() else '没跑'}(日志 logs/inv-stock/paper/live/line_exec/orchestrator_{D}.log)")
    for lid in line_ids(D):
        hb = ROOT / "results" / "_live" / D / LDS.ldir(lid) / "heartbeat.txt"
        print(f"{lid:16s} 心跳 {hb.read_text(encoding='utf-8').strip() if hb.exists() else '-'}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensure", action="store_true")
    ap.add_argument("--status", action="store_true")   # 10/23 08:2x: 文档 / 定时检查都写 --status, 原来不认会报错退出; 不带参数也是查状态
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    ensure(a.date) if a.ensure else status(a.date)


if __name__ == "__main__":
    main()
