# -*- coding: utf-8 -*-
"""cli_relay.py — 把一句话转给另一台电脑(或本机)正在跑的 Claude Code 窗口, 等它答完把回复打印出来(10/13 建)

用法(和微信 hermes 一样的写法):
  python scripts/hermes/cli_relay.py "pc1 cli: 牧原现在怎么挂单"
  python scripts/hermes/cli_relay.py pc1 "牧原现在怎么挂单" [--wait 600]
在任意一台的 Claude Code 里直接说「pc1 cli: xxx」也行——全局 CLAUDE.md 里有一条规矩让 Claude 后台跑本脚本, 答完收到通知再转述回复(=hermes 看守脚本的推送, 全天可用)。
看守: 发完每 10 秒读一次对方会话记录, 答完立刻打印; 最长等 --wait(默认 30 分钟), 超时后可 --fetch "<标记>" 补取。
流程: ssh 到目标机 → cli_inject.py send(计划任务在目标机登录会话里往 Claude 窗口打字+回车) → 每 10 秒 ssh 读目标机会话记录,
  回复写完(turn_duration)就打印; 超过 --wait 秒没答完就把已有部分打印出来并说明。
机器清单: scripts/hermes/cli_hosts.json(ssh 地址/目录/python)。目标是本机时不走 ssh。
"""
import argparse, base64, json, re, socket, subprocess, sys, time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOSTS = json.loads((HERE / "cli_hosts.json").read_text(encoding="utf-8"))
SELF_NAMES = {"pc1": "DESKTOP-3JCO3I1", "pc2": "CHINAMI-VHGLL1T", "pc3": "SHA01W0865"}   # 计算机名 → 判断目标是不是本机
NOWIN = 0x08000000


def run_on(target, args, timeout=90):
    h = HOSTS[target]
    script = h["repo"] + r"\scripts\hermes\cli_inject.py"
    if SELF_NAMES.get(target, "").lower() == socket.gethostname().lower():
        cmd = [sys.executable, str(HERE / "cli_inject.py"), *args]
    else:
        py = f'"{h["python"]}"' if "\\" in h["python"] else h["python"]     # 裸 python=走对方 PATH, 不加引号
        remote = f'{py} "{script}" ' + " ".join(f'"{a}"' for a in args)
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", h["ssh"], remote]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=NOWIN)
    out = "\n".join(l for l in (r.stdout or "").splitlines() if not re.search(r"post-quantum|store now|upgraded", l, re.I))
    return out.strip()


def wait_reply(target, mark, wait, first=False, skip=""):
    """看守: 每 10 秒读一次对方会话记录, 答完(turn_duration)即返回; 超过 wait 秒返回已写出的部分。
    10/14 两段式: first=True 时对方一写出第一段文字(快版)就先返回(exit 3), 调用方转述后再 --fetch --rest 等完整版;
    skip=已转述过的快版文字, 完整版只打印它之后的部分"""
    t0, last = time.time(), {}
    while time.time() - t0 < wait:
        time.sleep(5 if first else 10)
        try:
            last = json.loads(run_on(target, ["read", mark]).splitlines()[-1])
        except (ValueError, IndexError, subprocess.TimeoutExpired):
            continue
        if last.get("status") == "done":
            break
        if first and (last.get("text") or "").strip():
            print(f"---- {target} 快版(完整版还在写; 转述后后台跑: cli_relay.py {target} --fetch \"{mark}\" --rest) ----\n{last['text']}")
            return 3
    st = last.get("status", "not_found")
    note = {"done": "", "pending": f"(等了 {wait} 秒还没答完, 以下是目前已写出的部分; 稍后取: cli_relay.py {target} --fetch \"{mark}\")",
            "not_found": "(对方会话记录里没找到这条消息: 可能没发出去、输入框里卡着, 或对方窗口不是 Claude Code)"}[st]
    text = last.get("text") or ""
    if skip and text.startswith(skip.strip()):
        text = text[len(skip.strip()):].strip() or "(复核无补充)"
    print(f"---- {target} 回复 {note}----\n{text or '(无)'}")
    return 0 if st == "done" else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("message", nargs="?")
    ap.add_argument("--wait", type=int, default=1800, help="最长等多少秒(默认 30 分钟; 对方忙时消息排在它手上任务后面)")
    ap.add_argument("--fetch", metavar="标记", help="不发消息, 只按标记取回之前那条的回复(超时后补取用)")
    ap.add_argument("--rest", action="store_true", help="配 --fetch: 等到对方答完(最长 15 分钟), 只打印快版之后的完整版部分")
    ap.add_argument("--one-shot", action="store_true", help="不分两段, 答完一次性返回(旧行为)")
    a = ap.parse_args()
    target, msg = a.target.strip(), a.message
    m = re.match(r"^\s*(pc\d)\s*cli\s*[:：]\s*(.+)$", target, re.S | re.I)
    if m:                                          # 整句 "pc1 cli: xxx" 写法
        target, msg = m.group(1).lower(), m.group(2).strip()
    target = target.lower()
    if target in HOSTS and a.fetch:
        if a.rest:   # 两段式第二段: 先取快版文字作 skip, 再等答完
            try:
                first = json.loads(run_on(target, ["read", a.fetch]).splitlines()[-1]).get("text", "").split("\n\n")[0]
            except (ValueError, IndexError, subprocess.TimeoutExpired):
                first = ""
            return wait_reply(target, a.fetch, min(a.wait, 900), skip=first)
        return wait_reply(target, a.fetch, 15)
    if target not in HOSTS or not msg:
        print(f"用法: cli_relay.py \"pcN cli: 消息\" [--wait 秒] | cli_relay.py pcN --fetch \"<标记>\"(可用: {', '.join(k for k in HOSTS if k.startswith('pc'))})")
        return 2
    mark = f"[{socket.gethostname()}→{target} {datetime.now():%H%M%S}]"
    b64 = base64.b64encode(f"{mark} {msg}".encode("utf-8")).decode("ascii")
    sent = run_on(target, ["send", b64])
    print(f"送达 {target}: {sent} 标记 {mark}", flush=True)
    if not sent.startswith("SENT"):
        return 1
    return wait_reply(target, mark, a.wait, first=not a.one_shot)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
