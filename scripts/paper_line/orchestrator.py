# -*- coding: utf-8 -*-
"""orchestrator.py — paper v3 总控(一个进程管全部账本; 10/22 晚用户定)

为什么不是 9 个独立进程: 09:20 竞价复核 / 大盘翻转 / 10:30 空仓提醒这类时刻, 9 本会同时要叫醒模型 —— 各进程各自起 claude -p 就是 10/22 v2 的并发事故。
总控 = 一个进程里每本账一个线程(盯盘 + 撮合 + 记账 + 判断何时叫醒, 逻辑全在 executor.V3), 叫醒模型统一走 executor.GATE:
  同时最多 PAPER_MAX_INFLIGHT(默认 4)个 claude -p, 其余按优先级排队(启动 / 竞价复核 → 成交 / 失效条件 / 空仓提醒 → 出区间 / 翻转 → 心跳; 同级有持仓的先、土豆在前)
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
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import line_dirs as LDS   # noqa: E402  10/25 账本目录命名(live_<skill> / paper_<id>)
sys.path.insert(0, str(ROOT / "scripts" / "paper_line"))
import executor as E   # noqa: E402
import pack   # noqa: E402

BOOKS = {}   # 线号 → V3 对象(实盘线盘前串行 / 盘前汇总要看各本盘前首跑进度)

LOCK = ROOT / "scripts" / "temp" / "line_orchestrator.lock"


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
    eff = E.X.flag("PAPER_EFFORT", "high") or "high"
    os.environ.update(EXEC_AUC_TEST_SKILLS="", EXEC_AUC_AT=E.X.flag("PAPER_AUC_AT", "09:20:00") or "09:20:00", EXEC_SHADOW_EFFORT="", EXEC_FLEET_VARIANTS="",
                      EXEC_EFFORT=eff, EXEC_FIRST_EFFORT=eff, EXEC_AUC_EFFORT=eff, EXEC_FULL_PAUSE="0")
    ttl = E.X.flag("PAPER_CACHE_TTL", "1h") or ""   # 10/23 00:5x 实测: 中转站支持 1 小时提示缓存(scripts/test/cache_ttl_probe.py), 叫醒间隔 >5 分钟不再整段重写
    if ttl:
        os.environ.update(CLAUDE_CODE_PROMPT_CACHE_TTL=ttl, ENABLE_PROMPT_CACHING_1H="1" if ttl == "1h" else "0")


def line_ov(ln, idx):
    """每本账自己的开关(线程局部): 尾盘版错峰 8 秒 / 决策 T 线心跳固定 60 分钟"""
    ov = {"EXEC_TAIL_AT": (dt.datetime.strptime(E.X.flag("PAPER_TAIL_AT", "14:51:00") or "14:51:00", "%H:%M:%S") + dt.timedelta(seconds=8 * idx)).strftime("%H:%M:%S")}
    if ln["kind"] == "dt":
        ov["EXEC_HB_DYNAMIC"] = "0"
    return ov


def run_line(ln, idx, D, fake, ids=None):
    first = (dt.datetime.strptime(E.X.flag("PAPER_FIRST", "09:00:00") or "09:00:00", "%H:%M:%S") + dt.timedelta(seconds=20 * idx)).strftime("%H:%M:%S")
    if ln.get("live"):   # 10/24 实盘线: 盘前首跑(串行)(第 1 本写热共享开头缓存, 之后按组放行, live.boot_wait)
        import live as LV
        first = LV.first_at()
    while True:
        E._TL.ov = line_ov(ln, idx)
        try:
            e = E.V3(ln, D, dry=False, fake=fake)
            BOOKS[ln["id"]] = e
            if (e.dir / "summary.md").exists():
                return   # 今天已收盘
            if ln.get("live") and not e.strategy and ids:
                while dt.datetime.now().strftime("%H:%M:%S") < first:
                    time.sleep(5)
                w = LV.boot_wait(idx, ids, BOOKS)
                first = dt.datetime.now().strftime("%H:%M:%S")
                print(f"[{first}] {ln['id']} 盘前首跑(第 {idx + 1} 本, 等前一组 {w} 秒)", flush=True)
            e.run(t_strategy=first)
            return
        except Exception:   # noqa: BLE001
            msg = traceback.format_exc()[-600:]
            print(f"[{dt.datetime.now():%H:%M:%S}] {ln['id']} 线程异常, 30 秒后重建:\n{msg}", flush=True)
            try:
                (ROOT / "results" / "_live" / D / LDS.ldir(ln["id"]) / "events.jsonl").open("a", encoding="utf-8").write(
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
    _rm = (E.X.flag("LIVE_ROT_MODE", "") or "").strip()   # 10/29 用户令: 实盘线 key 轮换模式(kimi = 订阅 kimi-code 优先, 撞窗口换烧 token 的 kimi-api; 空 = 照 rotation.txt)
    os.environ["CLAUDE_ROT_MODE"] = _rm or "day"   # 10/29: 实盘线(08:28 起进程)固定白天档 gravitex, 不吃夜间 kimi-night 时段规则
    _lm = (E.X.flag("LIVE_MODEL", "") or "").strip()   # 10/29 用户令: 实盘线统一模型(白天 gravitex 上跑 claude-sonnet-5-5)
    if _lm:
        os.environ["CLAUDE_MODEL_OVERRIDE"] = _lm
    take_lock()
    try:
        common_env()
        live = pack.live_on()
        if live:   # 10/24 实盘线: 先出(刷新)当天名单, 保留用户已挑的 keep
            sys.path.insert(0, str(ROOT / "scripts" / "paper_line" / "tools"))
            import mentor_select as MS
            try:
                print(MS.text(MS.write(a.date)), flush=True)
            except Exception as e:   # noqa: BLE001  选人失败 → 用已有名单(没有就 pack.live_sel 现算)
                print(f"[{dt.datetime.now():%H:%M:%S}] 盘前选人失败 {e!r}", flush=True)
        L = E.lines(a.date)
        sel = [x.strip() for x in (a.lines or ("" if live else E.X.flag("PAPER_LINES", "")) or "").split(",") if x.strip()]
        want = [lid for lid in L if not sel or lid in sel or L[lid]["skill"] in sel]   # --lines 认线号也认 skill id
        print(f"[{dt.datetime.now():%H:%M:%S}] v3 总控启动 {a.date}: {want}; 同时最多 {E.GATE.n} 个会话在跑", flush=True)
        if live and not a.fake:   # 10/25 用户定 09:00 才首跑 → 事实包 + 02 共用在首跑前 8 分钟才做(保证新鲜; 08:28 拉起只先出名单)
            prep = (dt.datetime.strptime(E.X.flag("LIVE_FIRST", "09:00:00") or "09:00:00", "%H:%M:%S") - dt.timedelta(minutes=8)).strftime("%H:%M:%S")
            while dt.datetime.now().strftime("%H:%M:%S") < prep:
                time.sleep(5)
        if not a.fake and dt.datetime.now().strftime("%H:%M") < "09:00":
            # 10/24 用户批(❓13): 盘前首跑先现做一份事实包(最多等 4 分钟) —— 10/23 09:00 首版用的是 08:01 那份(0900 那份要 1 分 45 秒才做完), 看不到 08:1x 才挂上的发哥
            try:
                sys.path.insert(0, str(ROOT / "scripts" / "dfcf" / "paper"))
                import facts_pack
                f, note = facts_pack.build(a.date, wait=240)
                print(f"[{dt.datetime.now():%H:%M:%S}] 盘前首跑事实包: {note} → {f}", flush=True)
            except Exception as e:   # noqa: BLE001  做不出来不挡开盘: 各本账 09:00 照旧用最近一份
                print(f"[{dt.datetime.now():%H:%M:%S}] 盘前首跑事实包失败 {e!r}", flush=True)
        try:   # 10/24 📋1: 02 全体共用 —— 各本盘前首跑前先由市况会话写一份, 之后触发式刷新(market02.trigger: 翻转条件 / 大小盘结构变化 / 指数再走一段 / 情绪突变 / 竞价定格)
            import market02 as M2
            if M2.shared_on():
                r0 = M2.run(a.date, dt.datetime.now().strftime("%H:%M:%S"), fake=a.fake)
                print(f"[{dt.datetime.now():%H:%M:%S}] 02 共用市况: {'写好' if r0 else '失败(各本照旧自己写 02)'}", flush=True)
                threading.Thread(target=M2.scheduler, args=(a.date, dt.datetime.now), kwargs={"fake": a.fake}, name="v3-market02", daemon=True).start()
        except Exception as e:   # noqa: BLE001
            print(f"[{dt.datetime.now():%H:%M:%S}] 02 共用启动失败 {e!r}(各本照旧自己写 02)", flush=True)
        if not a.fake:   # 10/24 模块 8: 分时信号检测(零 token, 读 3 秒盘口, 命中合并推微信; 自己跑到 15:00:30 退出)
            try:
                import subprocess
                subprocess.Popen([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "live" / "signals.py"), "--run", a.date], cwd=str(ROOT),
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), stdout=open(ROOT / "scripts" / "temp" / f"signals_{a.date}.log", "a", encoding="utf-8"), stderr=subprocess.STDOUT)
                print(f"[{dt.datetime.now():%H:%M:%S}] 信号检测已拉起(日志 scripts/temp/signals_{a.date}.log)", flush=True)
                if (E.X.flag("PUSH_BUS", "1") or "1") == "1":   # 10/25 用户批: 合并推送总线 dispatcher(自己跑到 15:05 退出; 重启续跑不重发)
                    subprocess.Popen([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "hermes" / "push_bus.py"), "--run", a.date], cwd=str(ROOT),
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), stdout=open(ROOT / "scripts" / "temp" / f"push_bus_{a.date}.out", "a", encoding="utf-8"), stderr=subprocess.STDOUT)
                    print(f"[{dt.datetime.now():%H:%M:%S}] 合并推送总线已拉起(日志 scripts/hermes/state/push_bus_{a.date}.log)", flush=True)
                if (E.X.flag("LIVE_WATCHCARD", "1") or "1") == "1":   # 10/26 用户: 6 条线盯盘卡(持仓 / 挂单 / 计划 / 叫醒条件, 任一线变了重推, 进总线合并)
                    subprocess.Popen([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "paper_line" / "tools" / "watchcard.py"), "--run", a.date], cwd=str(ROOT),
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), stdout=open(ROOT / "scripts" / "temp" / f"watchcard_{a.date}.log", "a", encoding="utf-8"), stderr=subprocess.STDOUT)
            except Exception as e:   # noqa: BLE001
                print(f"[{dt.datetime.now():%H:%M:%S}] 信号检测启动失败 {e!r}", flush=True)
        ths = []
        ids = [lid for lid in L if lid in want]
        for idx, lid in enumerate(ids):
            th = threading.Thread(target=run_line, args=(L[lid], idx, a.date, a.fake, ids if live else None), name=f"v3-{lid}", daemon=True)
            th.start()
            ths.append(th)
            time.sleep(1)   # 建账 / 读状态错开一点
        if live and dt.datetime.now().strftime("%H:%M:%S") < "09:19:00":   # 盘前各版不逐条推, 全部落地后合成一条盘前汇总
            import live as LV

            def _dg():
                try:
                    t = LV.digest(a.date, lambda: {lid: BOOKS[lid] for lid in ids if lid in BOOKS}, send=not a.fake)
                    print(f"[{dt.datetime.now():%H:%M:%S}] 盘前汇总{'已推' if t else '今天推过了'}", flush=True)
                except Exception as e:   # noqa: BLE001
                    print(f"[{dt.datetime.now():%H:%M:%S}] 盘前汇总失败 {e!r}", flush=True)
                if not a.fake and (E.X.flag("MORNING_KLINE", "1") or "1") == "1":   # 10/28: 盘前首跑收尾 → 持仓 K 线预测 + 明日预案要点推微信(用户 10/27 令; 一天一次)
                    try:
                        sys.path.insert(0, str(ROOT / "scripts" / "kline_study"))
                        import morning_push as MP
                        print(f"[{dt.datetime.now():%H:%M:%S}] 盘前持仓 K 线预测: {MP.run(a.date)}", flush=True)
                    except Exception as e:   # noqa: BLE001
                        print(f"[{dt.datetime.now():%H:%M:%S}] 盘前持仓 K 线预测失败 {e!r}", flush=True)
            threading.Thread(target=_dg, name="live-digest", daemon=True).start()
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
