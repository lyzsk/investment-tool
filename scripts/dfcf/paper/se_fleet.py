# -*- coding: utf-8 -*-
"""se_fleet.py — 新 paper(策略执行器)全体导师自动拉起(10/21 晚用户令: 10/22 起 15 位导师全部用新 paper, 各 10 万从 0 开始; 对照组撤掉)

谁调: check md --only mix(交易日 09:00~14:55 每 5 分钟)调 --ensure: 名单里没在跑、今天还没收盘的执行器就后台拉起(无窗口)
名单: chain_flags.txt `SE_FLEET_SKILLS`(逗号分隔; 空 = mentors.active_ids() 全体, 已去掉 paper_excluded 里的人和对照组); `SE_FLEET=0` 整体关
错峰: 首版策略时刻 = 09:15:00 + 序号 × 20 秒(15 条 → 09:15:00 ~ 09:19:40), 防 15 个模型调用同一秒发出
防双开: se_exec 自己的 pid 锁(scripts/temp/se_<链>.lock); 今天 summary.md 已有 = 已收盘, 不再拉
日志: logs/inv-stock/paper/live/se_fleet/<日>.log(拉起记录) · 各执行器输出 logs/inv-stock/paper/live/se_exec/<链>_<日>.log
用法: python se_fleet.py --ensure [--date D] | --status
"""
import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(HERE))
import mentors   # noqa: E402
from se_exec import flag   # noqa: E402

PY = ROOT / "scripts" / "venv" / "Scripts" / "python.exe"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
LOGD = ROOT / "logs" / "inv-stock" / "paper" / "live"


def skills():
    v = flag("SE_FLEET_SKILLS")
    return [s.strip() for s in v.split(",") if s.strip()] if v else [s for s in mentors.active_ids() if s != "control"]


def variants():
    """10/21 晚: 同一导师的对照变体, 例 zhiyingjuexin@nolimit; 拉起时带 --variant"""
    return [x.strip() for x in flag("SE_FLEET_VARIANTS", "").split(",") if "@" in x]


def alive(skill):
    f = ROOT / "scripts" / "temp" / f"se_{skill}.lock"
    try:
        import psutil
        pid = int(f.read_text().strip() or 0)
        cmd = " ".join(psutil.Process(pid).cmdline())
        sk, _, var = skill.partition("@")
        return pid and "se_exec.py" in cmd and sk in cmd and ((f"--variant {var}" in cmd) if var else "--variant" not in cmd)
    except Exception:   # noqa: BLE001
        return False


def log(D, msg):
    (LOGD / "se_fleet").mkdir(parents=True, exist_ok=True)
    with (LOGD / "se_fleet" / f"{D}.log").open("a", encoding="utf-8") as f:
        f.write(f"[{dt.datetime.now():%H:%M:%S}] {msg}\n")


def ensure(D):
    import a_rules as AR
    hm = dt.datetime.now().strftime("%H%M")
    if flag("SE_FLEET", "1") != "1" or not AR._is_trade_day_fallback(D) or not ("0900" <= hm < "1457"):
        return
    (LOGD / "se_exec").mkdir(parents=True, exist_ok=True)
    for i, s in enumerate(skills() + variants()):
        if alive(s) or (ROOT / "results" / "_live" / D / f"se_{s}" / "summary.md").exists():
            continue
        sk, _, var = s.partition("@")
        t0 = dt.time.fromisoformat(flag("SE_FIRST", "09:15:00") or "09:15:00")   # 10/21 晚(★12): 首版时刻可配, 明天 09:00:00
        t = (dt.datetime.combine(dt.date.today(), t0) + dt.timedelta(seconds=20 * i)).strftime("%H:%M:%S")
        out = open(LOGD / "se_exec" / f"{s.replace('@', '_')}_{D}.log", "a", encoding="utf-8")
        p = subprocess.Popen([str(PY), "-X", "utf8", str(HERE / "se_exec.py"), "--skill", sk, "--date", D, "--first", t] + (["--variant", var] if var else []),
                             cwd=ROOT, creationflags=NOWIN, stdout=out, stderr=subprocess.STDOUT)
        log(D, f"拉起 {s} pid={p.pid} 首版 {t}")


def status(D):
    for s in skills() + variants():
        hb = ROOT / "results" / "_live" / D / f"se_{s}" / "heartbeat.txt"
        print(f"{s:16s} {'在跑' if alive(s) else '没跑'}  {hb.read_text(encoding='utf-8').strip() if hb.exists() else '-'}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensure", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    if a.ensure:
        ensure(a.date)
    else:
        status(a.date)


if __name__ == "__main__":
    main()
