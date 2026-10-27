# -*- coding: utf-8 -*-
"""push_bus.py — 盘中微信推送合并总线(10/25 用户批: 信号 / live line 挂单 / 成交 / 电报提醒全进一个队列, 一条微信合并多只票, 动态冷却; 零 token)

为什么: 微信 iLink 两道限制 ——①用户每发一条消息后只能主动推约 10 条(wx_send.quota 记账)②连发会触发 30 秒冷却(10/23 09:36~09:47 限频 12 次:
        09:10~09:40 半小时推了 21 条, 每条线每出一版就单推一条)。频繁推是好事, 只是额度有限 → 不丢信息、合并着发
怎么合:
  enqueue(text, src, urgent, key)  生产方(执行器 / signals.py)只往队列文件追加一行 scripts/hermes/state/push_queue/<日>.jsonl, 立刻返回
  dispatcher(--run D)              总控拉起的单独进程, 每 2 秒看队列:
    · 同 key 的新消息顶掉还没发出去的旧消息(例: 同一条线的新一版挂单顶掉上一版 —— 你只需要看最新计划; 成交 / 信号不设 key, 不会被顶)
    · 攒批窗口(从这批第一条进来算)按剩余额度动态定: 有急件(成交 / 告警 / 持仓票信号)且额度 ≥3 条 → 10 秒; 额度 ≥6 → 20 秒; 3~5 → 60 秒;
      ≤2 → 只发急件(10 秒), 非急件攒着, 等你回消息额度恢复或攒满 20 分钟再发(末尾提示回个字)
    · 两次发送至少隔 31 秒(iLink 冷却 30 秒)
    · 合并成一条: 急件在前, 每条之间用分隔线; 超过 1800 字就按整条切, 剩下的留到下一批(不把一条消息切两半)
  开关: chain_flags.txt PUSH_BUS=1(0 = 各方照旧直接调 wx_send); 日志 scripts/hermes/state/push_bus_<日>.log
用法: python push_bus.py --run D [--dry]  |  python push_bus.py --test(假消息走一遍合并, 强制 dry)
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
QDIR = HERE / "state" / "push_queue"
MAXC = 1800
GAP_S = 31
_ARR = []   # 最近到达的盘面信号 (ts, 通道) —— 动态攒批窗口用


def _qf(D):
    return QDIR / f"{D}.jsonl"


def enqueue(text, src="", urgent=False, key=None, D=None, fast=False, slow=False):
    """生产方调用: 追加一行就返回(不等发送)"""
    D = D or dt.date.today().isoformat()
    QDIR.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.time(), "at": dt.datetime.now().strftime("%H:%M:%S"), "src": src, "urgent": bool(urgent), "fast": bool(fast), "slow": bool(slow), "key": key, "text": text}
    with _qf(D).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return True


def on():
    try:
        for line in (HERE.parent / "claude_profile" / "chain_flags.txt").read_text(encoding="utf-8").splitlines():
            k, _, v = line.split("#")[0].partition("=")
            if k.strip() == "PUSH_BUS":
                return v.strip() == "1"
    except OSError:
        pass
    return os.environ.get("PUSH_BUS", "0") == "1"


def window(pending, remaining):
    """→ (这批要等几秒, 这批发哪些); remaining = 剩余额度(None = 不知道, 按充足算)"""
    r = 10 if remaining is None else remaining
    urg = [e for e in pending if e["urgent"]]
    if any(e.get("fast") for e in pending) and r >= 1:   # 10/26 用户: 回封预警要提前 → 快车道; 12:36 用户补: 快车道也要合并, 只是攒批短 → 等 8 秒把同时出的几条合成一条
        return 5, pending if r >= 3 else [e for e in pending if e.get("fast") or e["urgent"]]   # 10/26 15:2x: 8 → 5 秒
    if r <= 2:
        if urg:
            return 10, urg
        oldest = min(e["ts"] for e in pending)
        return (0 if time.time() - oldest >= 1200 else 10 ** 9), pending   # 非急件攒满 20 分钟才发
    if urg and r >= 3:
        return 10, pending
    # 10/26 20:0x 用户批: 普通 / 慢通道按到达频率动态攒批 —— 来得越密攒得越久, 目标每 10 分钟普通通道约 3 条
    now_ = time.time()
    if all(e.get("slow") for e in pending):   # 只剩回踩均价(S2): 3~10 分钟
        n15 = sum(1 for t, ln in _ARR if ln == "slow" and now_ - t < 900)
        return int(min(600, max(180, 180 * n15 / 3))), pending
    if all(e.get("src") == "live_signal" for e in pending):   # 普通通道(含顺带的慢通道): 15 秒 ~ 3 分钟
        n10 = sum(1 for t, ln in _ARR if ln == "norm" and now_ - t < 600)
        return int(min(180, max(15, 15 * n10 / 3))), pending
    return (20 if r >= 6 else 60), pending


def compose(items, remaining):
    items = sorted(items, key=lambda e: (not e["urgent"], e["ts"]))
    head = f"📦 {dt.datetime.now():%H:%M} 合并推送({len(items)} 条)"
    out, took, size = [], [], len(head)
    for e in items:
        t = e["text"].strip()
        if out and size + len(t) + 8 > MAXC:
            continue   # 10/26: 装不下的大条留到下一批, 继续往里塞后面的小条(原来 break = 小条也被卡住)
        out.append(t if len(t) <= MAXC - len(head) - 10 else t[:MAXC - len(head) - 30] + "…(截断)")
        took.append(e)
        size += len(t) + 8
    body = head.replace(f"({len(items)} 条)", f"({len(took)} 条)") + "\n" + "\n———\n".join(out)
    if remaining is not None and remaining <= 3:
        body += "\n(微信额度快用完, 方便时回个字)"
    return body, took


def _save_pending(pf, pending):
    try:
        pf.write_text(json.dumps(pending, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def log(D, s):
    try:
        with (HERE / "state" / f"push_bus_{D}.log").open("a", encoding="utf-8") as fh:
            fh.write(f"[{dt.datetime.now():%H:%M:%S}] {s}\n")
    except OSError:
        pass


def run(D, dry=False, until="15:05:00", once=False):
    import wx_send
    f = _qf(D)
    off, pending, last_send, n_sent = 0, [], 0.0, 0
    pf = HERE / "state" / f"push_bus_{D}.pending.json"   # 10/26: 重启前没发出去的队列存这里, 重启续上(原来重启 = 丢掉)
    if f.exists():   # 重启续跑: 已有的行算处理过(避免重发)
        off = f.stat().st_size
        try:
            pending = json.loads(pf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pending = []
    log(D, f"dispatcher 启动 dry={dry} 起点 {off}")
    while dt.datetime.now().strftime("%H:%M:%S") < until:
        if f.exists() and f.stat().st_size > off:
            with f.open("r", encoding="utf-8") as fh:
                fh.seek(off)
                for l in fh:
                    try:
                        e = json.loads(l)
                    except ValueError:
                        continue
                    if e.get("src") == "live_signal":   # 记到达时刻(动态攒批用)
                        _ARR.append((e.get("ts") or time.time(), "fast" if e.get("fast") else "slow" if e.get("slow") else "norm"))
                        del _ARR[:-300]
                    if e.get("key"):
                        pending = [x for x in pending if x.get("key") != e["key"]]   # 新一版顶掉还没发的旧版
                    pending.append(e)
                off = fh.tell()
            _save_pending(pf, pending)
        if pending and time.time() - last_send >= GAP_S:
            try:
                t0, used = wx_send.quota()
                remaining = max(0, wx_send.QUOTA - used) if t0 else None
            except Exception:   # noqa: BLE001
                remaining = None
            wait, batch = window(pending, remaining)
            first = min(e["ts"] for e in batch)
            if time.time() - first >= wait:
                text, sent = compose(batch, remaining)
                r = wx_send.send(text, src="live_bus", raw=True, wait=120, dry=dry, verbose=False)
                last_send = time.time()
                n_sent += 1
                ids = {id(x) for x in sent}
                pending = [x for x in pending if id(x) not in ids]
                _save_pending(pf, pending)
                log(D, f"发 {len(sent)} 条 → {r}; 剩余额度 {remaining}; 队列还剩 {len(pending)}; 来源 {sorted({x['src'] for x in sent})}")
        if once and n_sent and not pending:
            break
        time.sleep(2)
    log(D, "dispatcher 退出")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(HERE))
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    if a.test:   # 假消息: 同一条线连出 3 版(只该发最后一版) + 1 条成交(急件) + 2 条信号 → 应合成 1 条
        D = "2099-01-01"
        _qf(D).unlink(missing_ok=True)
        import threading
        th = threading.Thread(target=run, args=(D,), kwargs={"dry": True, "until": "23:59:59", "once": True}, daemon=True)
        th.start()
        time.sleep(1)
        for i in range(3):
            enqueue(f"📋 芷影攫心skill 第 {i + 1} 版挂单(测试)", src="live_zhiyingjuexin", key="live_zhiyingjuexin:ver", D=D)
        enqueue("✅ 刘忆青skill 成交(测试)", src="live_liuyiqing", urgent=True, D=D)
        enqueue("分时信号 S4a 炸板(测试)", src="live_signal", D=D)
        enqueue("分时信号 S4b 回封动作(测试)", src="live_signal", urgent=True, D=D)
        th.join(timeout=60)
        print((HERE / "state" / f"push_bus_{D}.log").read_text(encoding="utf-8")[-600:])
        return
    if a.run:
        run(a.run, dry=a.dry)


if __name__ == "__main__":
    main()
