# -*- coding: utf-8 -*-
"""minute_live.py — 盘中实时 1 分钟 / 5 分钟线(10/21 用户令: 先保证当日实时分钟线让消费者能用; 零 token、零请求)

源: 3 秒盘口 downloads/market/<日>/book_snap.jsonl(collect_book, 名单约 40~50 只: 做T 标的 + paper 各账本持仓/挂单 + 当日计划单 + 用户实盘持仓)
口径: 与收盘采集 kline_minute.jsonl(collect_minute.py)一致 —— 09:25 撮合 → 09:30 那根; 09:30~11:29 的成交记到下一分钟(09:30:xx → 09:31);
      11:30 → 11:30; 13:00~14:59 → +1 分钟; 15:00 → 15:00。量 / 额 = 累计量 / 累计额相减(准); 高低 = 3 秒采样的最高最低(会漏 3 秒内尖刺)
产物: downloads/market/<日>/kline_minute_live.jsonl(1 分钟, 字段同 kline_minute + source=book_snap) · kline_5m_live.jsonl(由 1 分钟合成)
      每分钟原子重写(只含已走完的分钟); 收盘后以 15:35 通达信采集的 kline_minute.jsonl 为准, 本文件不入库
用法: python minute_live.py --ensure(check md 每 5 分钟调, 交易时段没在跑就后台拉起) | --run [--date D] | --once [--date D](算一次就退, 回放 / 自测)
"""
import argparse
import datetime as dt
import gzip
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"
LOCK = ROOT / "scripts" / "temp" / "minute_live.pid"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def label(t):
    """快照时刻 HH:MM:SS → 分钟 bar 标签(同 collect_minute 口径); 不在交易时段 = None"""
    hm = t[:5]
    if "09:25" <= hm < "09:30":
        return "09:30"
    if "09:30" <= hm < "11:30" or "13:00" <= hm < "15:00":
        m = int(hm[:2]) * 60 + int(hm[3:]) + 1
        return f"{m // 60:02d}:{m % 60:02d}"
    if hm == "11:30":
        return "11:30"
    if hm == "15:00":
        return "15:00"
    return None


def build(D, upto=None):
    f = MKT / D / "book_snap.jsonl"
    op = open
    if not f.exists():
        f, op = MKT / D / "book_snap.jsonl.gz", gzip.open
        if not f.exists():
            return {}
    bars, last = {}, {}
    with op(f, "rt", encoding="utf-8") as fh:
        for l in fh:
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if not r.get("p"):
                continue
            lb = label(r["t"])
            if not lb:
                continue
            s = r["s"]
            b = bars.setdefault(s, {}).get(lb)
            if b is None:
                b = bars[s][lb] = {"o": r["p"], "h": r["p"], "l": r["p"], "c": r["p"], "v0": last.get(s, (0, 0))[0], "a0": last.get(s, (0, 0))[1]}
            b["h"], b["l"], b["c"] = max(b["h"], r["p"]), min(b["l"], r["p"]), r["p"]
            b["v1"], b["a1"] = r.get("v") or 0, r.get("a") or 0
            last[s] = (b["v1"], b["a1"])
    out = {}
    for s, bs in bars.items():
        rows, cv, ca = [], 0, 0.0
        for lb in sorted(bs):
            if upto and lb > upto:
                continue
            b = bs[lb]
            v, a = max(0, b["v1"] - b["v0"]), max(0.0, b["a1"] - b["a0"])
            cv, ca = b["v1"], b["a1"]
            rows.append({"symbol": s, "tradeDate": D, "barTime": f"{D}T{lb}:00", "open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"],
                         "volume": v, "amount": round(a, 2), "avgPrice": round(ca / cv, 4) if cv else b["c"], "source": "book_snap"})
        out[s] = rows
    return out


def five(rows):
    g = {}
    for r in rows:
        hm = r["barTime"][11:16]
        m = int(hm[:2]) * 60 + int(hm[3:])
        k = m if m % 5 == 0 else m + 5 - m % 5   # 5 分钟 bar 以结束时刻标(09:31~09:35 → 09:35)
        key = f"{k // 60:02d}:{k % 60:02d}"
        x = g.get(key)
        if x is None:
            g[key] = {**r, "barTime": r["barTime"][:11] + key + ":00"}
        else:
            x.update(high=max(x["high"], r["high"]), low=min(x["low"], r["low"]), close=r["close"], volume=x["volume"] + r["volume"],
                     amount=round(x["amount"] + r["amount"], 2), avgPrice=r["avgPrice"])
    return [g[k] for k in sorted(g)]


def write(D, upto=None):
    data = build(D, upto)
    d = MKT / D
    for name, fn in (("kline_minute_live.jsonl", lambda rs: rs), ("kline_5m_live.jsonl", five)):
        tmp = d / (name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for s in sorted(data):
                for r in fn(data[s]):
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, d / name)
    return data


def alive():
    try:
        pid = int(LOCK.read_text())
        return str(pid) in subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, creationflags=NOWIN).stdout
    except (OSError, ValueError):
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensure", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    if a.ensure:
        hm = dt.datetime.now().strftime("%H%M")
        if "0925" <= hm <= "1505" and (MKT / a.date / "book_snap.jsonl").exists() and not alive():
            p = subprocess.Popen([sys.executable, "-X", "utf8", str(Path(__file__)), "--run"], cwd=ROOT,
                                 creationflags=NOWIN | getattr(subprocess, "DETACHED_PROCESS", 0), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            LOCK.write_text(str(p.pid))
        return
    if a.once:
        data = write(a.date)
        print(f"{a.date}: {len(data)} 只, 1 分钟 {sum(len(v) for v in data.values())} 根")
        return
    if a.run:
        LOCK.write_text(str(os.getpid()))
        while dt.datetime.now().strftime("%H:%M") <= "15:02":
            now = dt.datetime.now()
            # 只写已走完的分钟: 此刻 10:05:20 → 最新完整 bar = 10:05(覆盖 10:04:00~10:04:59)
            try:
                write(a.date, upto=label(now.strftime("%H:%M:%S")) and (now - dt.timedelta(minutes=0)).strftime("%H:%M"))
            except Exception:   # noqa: BLE001
                pass
            time.sleep(60 - dt.datetime.now().second + 2)


if __name__ == "__main__":
    main()
