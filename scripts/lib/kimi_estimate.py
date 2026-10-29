# -*- coding: utf-8 -*-
"""lib/kimi_estimate.py — 每天按 kimi-k3.1-pro 口径估算 token 用量 + 烧 token 的钱(10/29 用户令; 零 token, 每晚 check md 跑)

数据: results/_live/<D>/live_*/versions/*/timing.json(实盘线每步: in / cache_read / cache_write / out)
     + scripts/lib/claude_cost.csv 当天其他 claude -p(check md / 蒸馏 / 核对卡; 只取每行自己的 token, 不用 cost_usd —— 那列在 resume 会话里是累计值)
换算: Claude 计的 token × KIMI_RATIO = kimi 计的 token(10/29 实测同一份 690KB 启动材料: Claude 约 57.5 万 → kimi 26.8 万 → 0.467)
价格(kimi-k3.1-pro, 美元 / 百万, 10/29 查 moonshot 官方): 输入 2.00 · 缓存写 2.00 · 缓存读 0.20 · 输出 10.00; 人民币按 USD_CNY
订阅额度: 10/18 实测 k3 一个 5 小时窗口约 2000 万 token(含缓存读); 3.1-pro 的订阅额度未测 → 只给「按今天用量要几个 5 小时窗口」
用户账号: Tier 3(10/29 用户确认)
产物: results/_live/kimi_estimate.csv(每天一行, 追加 / 覆盖同日)+ 打印一段给人看
用法: python kimi_estimate.py [--date D]
"""
import argparse
import csv
import datetime as dt
import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KIMI_RATIO = 0.467
PRICE = {"in": 2.00, "cw": 2.00, "cr": 0.20, "out": 10.00}
USD_CNY = 7.1
WINDOW_5H = 20_000_000
OUT = ROOT / "results" / "_live" / "kimi_estimate.csv"


def day(D):
    live = Counter()
    for f in glob.glob(str(ROOT / "results" / "_live" / D / "live_*" / "versions" / "*" / "timing.json")):
        try:
            t = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for v in (t.get("steps") or {}).values():
            if isinstance(v, dict):
                live["in"] += int(v.get("in") or 0)
                live["cr"] += int(v.get("cache_read") or 0)
                live["cw"] += int(v.get("cache_write") or 0)
                live["out"] += int(v.get("out") or 0)
                live["calls"] += 1
    other = Counter()
    try:
        for r in csv.DictReader(open(ROOT / "scripts" / "lib" / "claude_cost.csv", encoding="utf-8")):
            if not r["ts"].startswith(D) or r["tag"].startswith("v3-live"):
                continue
            for k, c in (("in", "in_tokens"), ("cr", "cache_read"), ("cw", "cache_create"), ("out", "out_tokens")):
                try:
                    other[k] += int(float(r.get(c) or 0))
                except ValueError:
                    pass
            other["calls"] += 1
    except OSError:
        pass
    return live, other


def kimi(c):
    k = {x: c[x] * KIMI_RATIO for x in ("in", "cr", "cw", "out")}
    usd = sum(k[x] / 1e6 * PRICE[x] for x in k)
    return k, usd


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    live, other = day(a.date)
    rows = []
    L = [f"# {a.date} 按 kimi-k3.1-pro 口径估算(Claude token × {KIMI_RATIO}; 价格 美元/百万 输入 2 / 缓存写 2 / 缓存读 0.2 / 输出 10)"]
    for nm, c in (("实盘线", live), ("其他自动化", other)):
        k, usd = kimi(c)
        tot = sum(k.values())
        L.append(f"- {nm}: 调用 {c['calls']} 次 · kimi token 输入 {k['in'] / 1e6:.1f}M / 缓存写 {k['cw'] / 1e6:.1f}M / 缓存读 {k['cr'] / 1e6:.1f}M / 输出 {k['out'] / 1e6:.2f}M"
                 f"(合计 {tot / 1e6:.1f}M ≈ {tot / WINDOW_5H:.1f} 个 5 小时订阅窗口)· 全部烧 token ≈ ${usd:.1f} ≈ ¥{usd * USD_CNY:.0f}")
        rows.append([a.date, nm, c["calls"], round(k["in"]), round(k["cw"]), round(k["cr"]), round(k["out"]), round(usd, 2), round(usd * USD_CNY)])
    L.append("- 不自信点: 换算系数只测过 1 份材料; 订阅窗口额度是 10/18 k3 的实测, 3.1-pro 未测; kimi 推理 token 按输出价, 这里没单独算")
    old = [r for r in csv.reader(open(OUT, encoding="utf-8"))] if OUT.exists() else [["日期", "类别", "调用", "输入", "缓存写", "缓存读", "输出", "美元", "人民币"]]
    old = [r for r in old if r[0] != a.date]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    csv.writer(open(OUT, "w", encoding="utf-8", newline="")).writerows(old + rows)
    print("\n".join(L))


if __name__ == "__main__":
    main()
