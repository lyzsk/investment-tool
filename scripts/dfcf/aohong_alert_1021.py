# -*- coding: utf-8 -*-
"""aohong_alert_1021.py — 10/21 用户实盘澳弘转债(111024)止损 / 时间止损提醒(一次性, 用户 10:3x 令; 零 token)
破位: 转债 ≤ 251.10(今日低) 或 正股 605058 ≤ 66.38(今日低) → 立即推微信; 之后每再跌 1% 再推一次
时间: 11:00 转债 < 256 → 推"按买一卖一半 210 张"; ≥256 推现状; 11:25 推"清完剩余"; 11:31 退出
取价: 新浪批量(两只一次请求) 每 5 秒 = 0.2 次/秒
"""
import datetime as dt
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / "scripts" / "venv" / "Scripts" / "python.exe"
LOG = ROOT / "scripts" / "temp" / "aohong_alert_1021.log"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CB_STOP, ST_STOP = 251.10, 66.38


def log(*a):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{dt.datetime.now():%H:%M:%S}] " + " ".join(str(x) for x in a) + "\n")


def wx(msg):
    subprocess.Popen([str(PY), "-X", "utf8", str(ROOT / "scripts" / "hermes" / "wx_send.py"), msg, "--raw", "--src", "aohong_alert", "--wait", "600"],
                     cwd=ROOT, creationflags=NOWIN, stdout=open(LOG, "a", encoding="utf-8"), stderr=subprocess.STDOUT)   # 不阻塞盯价; 限频时 wx_send 自己等
    log("推送", msg[:60].replace("\n", " "))


def quote():
    req = urllib.request.Request("https://hq.sinajs.cn/list=sh111024,sh605058", headers={"Referer": "https://finance.sina.com.cn"})
    out = {}
    for l in urllib.request.urlopen(req, timeout=5).read().decode("gbk").splitlines():
        x = l.split('"')[1].split(",")
        out[l[13:19]] = {"p": float(x[3]), "pc": float(x[2]), "b1": float(x[11]), "t": x[31]}
    return out


def main():
    cb_next, st_next, done = CB_STOP, ST_STOP, set()
    log("开始")
    while dt.datetime.now().strftime("%H:%M") < "11:31":
        try:
            q = quote()
        except Exception as e:   # noqa: BLE001
            log("取价失败", repr(e)[:100])
            time.sleep(10)
            continue
        cb, st = q["111024"], q["605058"]
        hm = dt.datetime.now().strftime("%H:%M")
        hit = []
        if cb["p"] and cb["p"] <= cb_next:
            hit.append(f"转债 {cb['p']} ≤ {cb_next:.2f}")
            cb_next = round(cb["p"] * 0.99, 2)
        if st["p"] and st["p"] <= st_next:
            hit.append(f"正股 {st['p']} ≤ {st_next:.2f}")
            st_next = round(st["p"] * 0.99, 2)
        if hit:
            wx(f"【澳弘止损 破位 {cb['t']}】{'; '.join(hit)}\n转债现 {cb['p']}(买一 {cb['b1']}) 正股 {st['p']}({(st['p'] / st['pc'] - 1) * 100:+.2f}%)\n按你定的: 撤掉全部卖单, 420张按买一卖出")
        if hm >= "11:00" and "1100" not in done:
            done.add("1100")
            if cb["p"] < 256:
                wx(f"【澳弘时间止损 11:00】转债 {cb['p']} < 256 → 按约定: 撤单, 先按买一({cb['b1']})卖一半 210 张; 剩下的 11:25 前清完\n正股 {st['p']}({(st['p'] / st['pc'] - 1) * 100:+.2f}%)")
            else:
                wx(f"【澳弘时间止损 11:00】转债 {cb['p']} ≥ 256, 不用先卖一半; 11:25 前仍要清完\n正股 {st['p']}({(st['p'] / st['pc'] - 1) * 100:+.2f}%)")
        if hm >= "11:25" and "1125" not in done:
            done.add("1125")
            wx(f"【澳弘时间止损 11:25】到点清仓: 撤掉剩余卖单, 按买一({cb['b1']})全部卖出\n转债 {cb['p']} 正股 {st['p']}({(st['p'] / st['pc'] - 1) * 100:+.2f}%)")
        time.sleep(5)
    log("结束")


if __name__ == "__main__":
    if "--test" in sys.argv:
        print(quote())
    else:
        main()
