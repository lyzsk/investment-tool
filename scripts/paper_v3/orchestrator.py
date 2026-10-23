# -*- coding: utf-8 -*-
"""orchestrator.py — paper v3 总控(一个进程管全部账本; 10/22 晚用户定)

为什么不是 9 个独立进程: 09:20 竞价复核 / 大盘翻转 / 10:30 空仓提醒这类时刻, 9 本会同时要叫醒模型 —— 各进程各自起 claude -p 就是 10/22 v2 的并发事故。
总控 = 一个进程里每本账一个线程(盯盘 + 撮合 + 记账 + 判断何时叫醒, 逻辑全在 executor.V3), 叫醒模型统一走 executor.GATE:
  同时最多 V3_MAX_INFLIGHT(默认 4)个 claude -p, 其余按优先级排队(启动 / 竞价复核 → 成交 / 失效条件 / 空仓提醒 → 出区间 / 翻转 → 心跳; 同级有持仓的先、土豆在前)
每本账的会话照旧各自独立(09:00 --session-id 新建, 之后 --resume); 每本账自己的开关(尾盘错峰 / 决策 T 固定心跳)放线程局部
某本账线程异常退出 → 30 秒后自动重建这本账(从落盘状态续跑), 不影响其他本
用法: python orchestrator.py [--date D] [--lines tudou,liuyiqing] [--fake]
"""
import argparse
import datetime as dt
import os
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper_v3"))
import executor as E   # noqa: E402

LOCK = ROOT / "scripts" / "temp" / "v3_orchestrator.lock"


def take_lock():
    import psutil
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text().strip() or 0)
            if pid != os.getpid() and "orchestrator.py" in " ".join(psutil.Process(pid).cmdline()):
                sys.exit(f"v3 总控已在跑(pid {pid}), 本进程退出")
        except (ValueError, psutil.Error):
            pass
    LOCK.write_text(str(os.getpid()))


def common_env():
    """全部账本共用的开关(进程级): 竞价复核时刻 / 档位 / 不停触发 / 不走 v2 的土豆竞价测试"""
    eff = E.X.flag("V3_EFFORT", "high") or "high"
    os.environ.update(SE_AUC_TEST_SKILLS="", SE_AUC_AT=E.X.flag("V3_AUC_AT", "09:20:00") or "09:20:00", SE_SHADOW_EFFORT="", SE_FLEET_VARIANTS="",
                      SE_EFFORT=eff, SE_FIRST_EFFORT=eff, SE_AUC_EFFORT=eff, SE_FULL_PAUSE="0")
    ttl = E.X.flag("V3_CACHE_TTL", "1h") or ""   # 10/23 00:5x 实测: 中转站支持 1 小时提示缓存(scripts/test/cache_ttl_probe.py), 叫醒间隔 >5 分钟不再整段重写
    if ttl:
        os.environ.update(CLAUDE_CODE_PROMPT_CACHE_TTL=ttl, ENABLE_PROMPT_CACHING_1H="1" if ttl == "1h" else "0")


def line_ov(ln, idx):
    """每本账自己的开关(线程局部): 尾盘版错峰 8 秒 / 决策 T 线心跳固定 60 分钟"""
    ov = {"SE_TAIL_AT": (dt.datetime.strptime(E.X.flag("V3_TAIL_AT", "14:51:00") or "14:51:00", "%H:%M:%S") + dt.timedelta(seconds=8 * idx)).strftime("%H:%M:%S")}
    if ln["kind"] == "dt":
        ov["SE_HB_DYNAMIC"] = "0"
    return ov


def run_line(ln, idx, D, fake):
    first = (dt.datetime.strptime(E.X.flag("V3_FIRST", "09:00:00") or "09:00:00", "%H:%M:%S") + dt.timedelta(seconds=20 * idx)).strftime("%H:%M:%S")
    while True:
        E._TL.ov = line_ov(ln, idx)
        try:
            e = E.V3(ln, D, dry=False, fake=fake)
            if (e.dir / "summary.md").exists():
                return   # 今天已收盘
            e.run(t_strategy=first)
            return
        except Exception:   # noqa: BLE001
            msg = traceback.format_exc()[-600:]
            print(f"[{dt.datetime.now():%H:%M:%S}] {ln['id']} 线程异常, 30 秒后重建:\n{msg}", flush=True)
            try:
                (ROOT / "results" / "_live" / D / f"v3_{ln['id']}" / "events.jsonl").open("a", encoding="utf-8").write(
                    '{"t": "%s", "kind": "总控重建本账", "err": %s}\n' % (dt.datetime.now().strftime("%H:%M:%S"), __import__("json").dumps(msg[-300:], ensure_ascii=False)))
            except OSError:
                pass
            time.sleep(30)
            if dt.datetime.now().strftime("%H:%M") >= "15:01":
                return


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--lines", default="")
    ap.add_argument("--fake", action="store_true")
    a = ap.parse_args()
    take_lock()
    try:
        common_env()
        L = E.lines()
        want = [x.strip() for x in (a.lines or E.X.flag("V3_LINES", "") or "").split(",") if x.strip()] or list(L)
        print(f"[{dt.datetime.now():%H:%M:%S}] v3 总控启动 {a.date}: {want}; 同时最多 {E.GATE.n} 个会话在跑", flush=True)
        ths = []
        for idx, lid in enumerate(L):
            if lid not in want:
                continue
            th = threading.Thread(target=run_line, args=(L[lid], idx, a.date, a.fake), name=f"v3-{lid}", daemon=True)
            th.start()
            ths.append(th)
            time.sleep(1)   # 建账 / 读状态错开一点
        for th in ths:
            th.join()
        print(f"[{dt.datetime.now():%H:%M:%S}] 全部账本收盘, 总控退出", flush=True)
    finally:
        try:
            if LOCK.read_text().strip() == str(os.getpid()):
                LOCK.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
