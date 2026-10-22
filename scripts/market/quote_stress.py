# -*- coding: utf-8 -*-
"""quote_stress.py — 行情源批量请求压测(10/21 用户定今天盘后测; 零 token; 结果先报用户, 确认后才写进 req_guard)

每档: 源 × 一次带 N 只 × 每 S 秒一次, 持续 M 分钟; 记录 单次耗时 P50 / P99 / 最大、响应字节、失败数、失败类型
停手: 连续失败 3 次, 或 HTTP 403 / 456 / 501 / 连接被重置 → 立即停该源(不再测它后面的档), 推微信
名单: 下载目录里最近一天的 kline_day.jsonl 取沪深个股(按成交额从高到低), 只读行情, 不下单
源: sina = hq.sinajs.cn/list=(五档在同一串里); tencent = qt.gtimg.cn/q=(带五档)
输出: results/inv-stock/stress/<日>/<源>.jsonl(每次请求一行) + summary.md
用法: python quote_stress.py --src tencent --plan 2:6,50:6,100:6,2:3,50:3,100:3 --minutes 10
      python quote_stress.py --src sina --plan 50:3,100:3,50:2,100:2,50:1,100:1 --minutes 10
      python quote_stress.py --src sina --plan 100:3,200:3,400:3,800:3 --minutes 5        (定名单上限)
"""
import argparse
import datetime as dt
import json
import statistics as st
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import ipv4_first   # noqa: E402,F401  10/21: 本机 IPv6 不通, 先走 IPv4
PY = ROOT / "scripts" / "venv" / "Scripts" / "python.exe"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def universe(n):
    days = sorted(p.parent.name for p in (ROOT / "downloads" / "market").glob("20*/kline_day.jsonl"))
    rows = []
    for l in (ROOT / "downloads" / "market" / days[-1] / "kline_day.jsonl").open(encoding="utf-8"):
        r = json.loads(l)
        s = r.get("symbol", "")
        if s[:2] in ("sh", "sz") and not s.startswith(("sh000", "sz399")) and r.get("amount"):
            rows.append((float(r["amount"]), s))
    rows.sort(reverse=True)
    return [s for _, s in rows[:n]]


def url(src, syms):
    if src == "sina":
        return "https://hq.sinajs.cn/list=" + ",".join(syms), {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
    return "https://qt.gtimg.cn/q=" + ",".join(syms), {"User-Agent": "Mozilla/5.0"}


def wx(msg):
    subprocess.run([str(PY), "-X", "utf8", str(ROOT / "scripts" / "hermes" / "wx_send.py"), msg, "--raw", "--src", "stress_alert", "--wait", "60", "--force"],
                   cwd=ROOT, creationflags=NOWIN, capture_output=True)


def run_tier(src, n, step, minutes, log):
    syms = universe(n)
    u, h = url(src, syms)
    lat, size, fails, kinds, streak = [], [], 0, {}, 0
    end = time.time() + minutes * 60
    while time.time() < end:
        t0 = time.time()
        ok, kind, nb = False, None, 0
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=8).read()
            nb = len(b)
            txt = b.decode("gbk", "replace")
            got = txt.count('="') if src == "sina" else txt.count('~')
            ok = nb > 50 * min(n, 5) and got > 0
            kind = None if ok else "空/截断"
        except urllib.error.HTTPError as e:
            kind = f"HTTP {e.code}"
        except Exception as e:   # noqa: BLE001
            kind = type(e).__name__ + (":reset" if "reset" in str(e).lower() or "10054" in str(e) else "")
        dt_ = time.time() - t0
        log.write(json.dumps({"t": dt.datetime.now().strftime("%H:%M:%S"), "n": n, "step": step, "ok": ok, "s": round(dt_, 3), "bytes": nb, "kind": kind}) + "\n")
        log.flush()
        if ok:
            streak = 0
            lat.append(dt_)
            size.append(nb)
        else:
            fails += 1
            streak += 1
            kinds[kind] = kinds.get(kind, 0) + 1
            if streak >= 3 or (kind and any(k in kind for k in ("403", "456", "501", "reset"))):
                return {"n": n, "step": step, "stopped": f"{kind} (连续失败 {streak})", "ok": len(lat), "fails": fails, "kinds": kinds}
        time.sleep(max(0.0, step - (time.time() - t0)))
    lat.sort()
    return {"n": n, "step": step, "ok": len(lat), "fails": fails, "kinds": kinds,
            "p50": round(st.median(lat), 3) if lat else None, "p99": round(lat[int(len(lat) * 0.99) - 1], 3) if len(lat) > 10 else None,
            "max": round(max(lat), 3) if lat else None, "bytes": int(st.median(size)) if size else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", choices=["sina", "tencent"], required=True)
    ap.add_argument("--plan", required=True, help="只数:间隔秒, 逗号分隔")
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    D = dt.date.today().isoformat()
    od = ROOT / "results" / "inv-stock" / "stress" / D
    od.mkdir(parents=True, exist_ok=True)
    res = []
    with (od / f"{a.src}{a.tag}.jsonl").open("a", encoding="utf-8") as log:
        for tier in a.plan.split(","):
            n, step = tier.split(":")
            r = run_tier(a.src, int(n), float(step), a.minutes, log)
            res.append(r)
            print(json.dumps(r, ensure_ascii=False), flush=True)
            if r.get("stopped"):
                wx(f"【压测停手】{a.src} {n}只×{step}秒 第 {r['ok'] + r['fails']} 次: {r['stopped']}; 已停该源, 不测后面的档")
                break
    L = [f"## {a.src}{a.tag} {dt.datetime.now():%H:%M}", "| 只数 | 间隔秒 | 成功 | 失败 | P50 秒 | P99 秒 | 最大 | 响应字节 | 备注 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in res:
        L.append(f"| {r['n']} | {r['step']:g} | {r['ok']} | {r['fails']} | {r.get('p50')} | {r.get('p99')} | {r.get('max')} | {r.get('bytes')} | {r.get('stopped') or r.get('kinds') or ''} |")
    with (od / "summary.md").open("a", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
