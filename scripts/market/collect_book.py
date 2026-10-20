# -*- coding: utf-8 -*-
"""collect_book.py — 盘口五档快照采集(10/18 晚用户定 P3: 给 QI / DI / OFI 攒数据; 零 token)

源: 新浪 hq.sinajs.cn 五档(批量, 一次请求带全部票) —— 特意不用腾讯: 撮合 / 盯盘已在用腾讯 qt, 腾讯约 1.6 次/秒会封, 分开源互不抢额度
节奏: 09:14~15:01 每 3 秒一次(≈0.33 次/秒); 同一只票快照时间没变(新浪约 3 秒刷新一次)就不重复写
名单(约 40 只, 每 10 分钟刷新): 做 T 账本标的 + paper 各账本持仓 / 未成交挂单 + 当日计划单 + 用户实盘持仓(snapshots 最近一次导出)
存储: downloads/market/<日>/book_snap.jsonl(盘中追加, 一行 = 一只票一个快照), 收盘后压成 book_snap.jsonl.gz; 每天约 30MB 原始 / 5MB 压缩
  字段: s 代码, t 时间, p 现价, v 累计量(股), a 累计额(元), b [[买1价,量],...买5], k [[卖1价,量],...卖5]
启动: check md --only mix(每 5 分钟)调 --ensure: 没在跑且在时段内 → 后台拉起(无窗口); 挂了下一轮自动重拉; pid 锁防双开
失败: 单次请求失败指数退避(3s→最多 60s), 不抛出; 连续失败 20 次写日志继续等; 永不影响撮合 / 盯盘
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/market/collect_book.py --ensure | --run | --gzip [--date D]
"""
import argparse
import datetime as dt
import glob
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"
PAPER = ROOT / "scripts" / "dfcf" / "paper"
LOCK = ROOT / "scripts" / "temp" / "collect_book.pid"
LOG = ROOT / "scripts" / "temp" / "collect_book.log"
START, END, STEP, MAXN = "0914", "1501", 3.0, 60
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
sys.path.insert(0, str(ROOT / "scripts" / "lib"))


def log(*a):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{dt.datetime.now():%m-%d %H:%M:%S}] " + " ".join(str(x) for x in a) + "\n")


def sym(code):
    try:
        import a_rules as AR
        return AR.symbol(code)
    except Exception:   # noqa: BLE001
        return ("sh" if code[0] in "569" else "sz") + code


def watch(D):
    codes = {"601988", "159941", "002714"}   # 做 T 账本标的
    real = set()   # 用户实盘成交里出现过的票
    for f in (PAPER / "books").glob("*.json"):
        try:
            b = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        codes |= set((b.get("positions") or {}).keys())
        codes |= {str(o.get("code")) for o in b.get("orders") or [] if o.get("status") == "open"}
    for f in glob.glob(str(PAPER / "plans" / f"{D}_*.md")):
        codes |= set(re.findall(r"\|\s*(?:BUY|SELL)\s*\|\s*(\d{6})\s*\|", Path(f).read_text(encoding="utf-8")))
    try:
        sys.path.insert(0, str(PAPER))
        import t_bot as TB
        for f in TB._snap_files()[-1:]:
            for l in f.read_text(encoding="utf-8").splitlines():
                t = l.split()
                if len(t) >= 5 and t[0].isdigit() and len(t[0]) <= 3 and len(t[1]) == 6 and t[1].isdigit():
                    codes.add(t[1])
                    real.add(t[1])
    except Exception:   # noqa: BLE001
        pass
    core = sorted(codes & ({"601988", "159941", "002714"} | real))
    nbr = []
    try:   # 10/19 晚: 实盘 / 做T 标的的拓扑前 3 邻居也录盘口 → ctx_index 能给模型看"邻居此刻涨跌", 不另开请求源
        sys.path.insert(0, str(ROOT / "scripts" / "market"))
        import topology as TOPO
        for c in core:
            nbr += [x["c"] for x in ((TOPO.load(c, D, strict=True) or {}).get("nb") or [])[:3]]
    except Exception:   # noqa: BLE001
        pass
    order = list(dict.fromkeys(core + nbr + sorted(codes)))
    out = [s for s in (sym(c) for c in order if re.fullmatch(r"\d{6}", c) and not c.startswith(("204", "1318"))) if s and not s.startswith("bj")]
    return out[:MAXN]


def fetch(syms):
    r = urllib.request.Request("https://hq.sinajs.cn/list=" + ",".join(syms), headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"})
    txt = urllib.request.urlopen(r, timeout=8).read().decode("gbk", errors="replace")
    out = []
    for l in txt.strip().splitlines():
        m = re.match(r'var hq_str_(\w+)="([^"]*)"', l)
        if not m or not m.group(2):
            continue
        f = m.group(2).split(",")
        if len(f) < 32:
            continue
        num = lambda x: float(x) if x not in ("", None) else 0.0   # noqa: E731
        out.append({"s": m.group(1), "t": f[31], "p": num(f[3]), "v": int(num(f[8])), "a": round(num(f[9]), 2),
                    "b": [[num(f[11 + 2 * i]), int(num(f[10 + 2 * i]))] for i in range(5)],
                    "k": [[num(f[21 + 2 * i]), int(num(f[20 + 2 * i]))] for i in range(5)], "d": f[30]})
    return out


def run(D):
    LOCK.write_text(str(os.getpid()))
    day_dir = MKT / D
    day_dir.mkdir(parents=True, exist_ok=True)
    fp = day_dir / "book_snap.jsonl"
    last_t, syms, refreshed, fails, back, n = {}, [], 0.0, 0, STEP, 0
    log(f"开始 {D} pid={os.getpid()}")
    try:
        with fp.open("a", encoding="utf-8") as fh:
            while True:
                now = dt.datetime.now()
                hm = now.strftime("%H%M")
                if hm > END:
                    break
                if hm < START:
                    time.sleep(10)
                    continue
                if time.time() - refreshed > 600:
                    syms, refreshed = watch(D), time.time()
                    log(f"名单 {len(syms)} 只")
                t0 = time.time()
                try:
                    rows = fetch(syms) if syms else []
                    fails, back = 0, STEP
                    for r in rows:
                        if r.pop("d") != D or last_t.get(r["s"]) == r["t"]:
                            continue   # 不是今天的(停牌 / 盘前残留) 或 快照没刷新 → 不写
                        last_t[r["s"]] = r["t"]
                        fh.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")
                        n += 1
                    fh.flush()
                except Exception as e:   # noqa: BLE001
                    fails += 1
                    back = min(60.0, back * 2)
                    if fails in (1, 5) or fails % 20 == 0:
                        log(f"请求失败 {fails} 次, 退避 {back:.0f}s: {e}")
                time.sleep(max(0.2, (back if fails else STEP) - (time.time() - t0)))
    finally:
        log(f"结束 {D}: 写 {n} 行")
        try:
            LOCK.unlink()
        except OSError:
            pass
    gz(D)


def gz(D):
    fp = MKT / D / "book_snap.jsonl"
    if fp.exists() and fp.stat().st_size:
        with fp.open("rb") as a, gzip.open(str(fp) + ".gz", "ab") as b:
            shutil.copyfileobj(a, b)
        fp.unlink()
        log(f"压缩 {D} → book_snap.jsonl.gz")


def alive():
    try:
        pid = int(LOCK.read_text())
    except (OSError, ValueError):
        return False
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return str(pid) in (r.stdout or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensure", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--gzip", action="store_true")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    if a.run:
        return run(a.date)
    if a.gzip:
        return gz(a.date)
    if a.ensure:
        hm = dt.datetime.now().strftime("%H%M")
        if not ("0900" <= hm < END) or dt.date.today().weekday() >= 5:
            print("盘口采集: 不在时段")
            return 0
        if alive():
            print("盘口采集: 运行中")
            return 0
        subprocess.Popen([sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--run", "--date", a.date], cwd=ROOT, creationflags=NOWIN,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        print("盘口采集: 已拉起")
    return 0


if __name__ == "__main__":
    sys.exit(main())
