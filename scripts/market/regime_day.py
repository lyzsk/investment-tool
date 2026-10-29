# -*- coding: utf-8 -*-
"""market/regime_day.py — 日级市况分级(10/28 晚; 零 token, 只读行情库; 给「全期 / 同市况 / 近期」三层统计用)

每个交易日一行(收盘后算):
  广度   上涨家数占比(主板 + 创业 + 科创, 排除北交所)、涨停数、跌停数
  指数   上证 / 中证1000 / 创业板指 涨跌; 风格 = 小盘强(中证1000 − 上证 ≥ +0.5)/ 权重强(≤ −0.5)/ 均衡
  连阴   上证连续收跌天数
  分级   冰点(跌停 ≥30 且 涨停 <40)/ 普跌(上涨占比 ≤30%)/ 普涨(≥70%)/ 分化(其余); 修复 = 今天普涨或分化偏涨(≥55%)且昨天普跌或冰点
产物: downloads/market/regime/regime_days.json {日期: {...}}; import: get(D) / prev(D)(D 前一个交易日, 盘中只能用这个)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/market/regime_day.py [--since 2024-06-01]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
OUT = ROOT / "downloads" / "market" / "regime" / "regime_days.json"
_C = {}


def build(since="2024-06-01"):
    import manual_backfill as mb
    c = mb.db().cursor()
    c.execute("select trade_date, sum(close > pre_close), count(*), "
              "sum(close >= round(pre_close * (case when symbol like 'sz30%%' or symbol like 'sh68%%' then 1.2 else 1.1 end), 2) - 0.005), "
              "sum(close <= round(pre_close * (case when symbol like 'sz30%%' or symbol like 'sh68%%' then 0.8 else 0.9 end), 2) + 0.005) "
              "from investment_market.kline_day where is_deleted=0 and trade_date >= %s and pre_close > 0 "
              "and (symbol like 'sh60%%' or symbol like 'sz00%%' or symbol like 'sz30%%' or symbol like 'sh68%%') group by trade_date", (since,))
    br = {str(d): (int(u or 0), int(n or 0), int(zt or 0), int(dt or 0)) for d, u, n, zt, dt in c.fetchall()}
    ix = {}
    for s in ("sh000001", "sh000852", "sz399006"):
        c.execute("select trade_date, close, pre_close from investment_market.kline_day where symbol=%s and is_deleted=0 and trade_date >= %s", (s, since))
        ix[s] = {str(d): (float(cl) / float(pc) - 1) * 100 for d, cl, pc in c.fetchall() if pc}
    out, prev, streak = {}, None, 0
    for d in sorted(br):
        u, n, zt, dtn = br[d]
        if n < 1000:
            continue
        r = u / n
        sh, zz, cy = ix["sh000001"].get(d), ix["sh000852"].get(d), ix["sz399006"].get(d)
        streak = streak + 1 if sh is not None and sh < 0 else 0
        lab = "冰点" if dtn >= 30 and zt < 40 else "普跌" if r <= 0.30 else "普涨" if r >= 0.70 else "分化"
        rep = bool(prev and prev["分级"] in ("普跌", "冰点") and (lab == "普涨" or (lab == "分化" and r >= 0.55)))
        sty = None if sh is None or zz is None else "小盘强" if zz - sh >= 0.5 else "权重强" if zz - sh <= -0.5 else "均衡"
        row = {"上涨占比": round(r, 3), "涨停": zt, "跌停": dtn, "上证": None if sh is None else round(sh, 2), "中证1000": None if zz is None else round(zz, 2),
               "创业板": None if cy is None else round(cy, 2), "风格": sty, "上证连阴": streak, "分级": lab, "修复": rep, "标签": ("修复" if rep else lab) + (f"·{sty}" if sty else "")}
        out[d] = row
        prev = row
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    return out


def _load():
    if "d" not in _C:
        try:
            _C["d"] = json.loads(OUT.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _C["d"] = {}
    return _C["d"]


def get(D):
    return _load().get(D)


def prev(D):
    ks = sorted(k for k in _load() if k < D)
    return (ks[-1], _load()[ks[-1]]) if ks else (None, None)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2024-06-01")
    a = ap.parse_args()
    out = build(a.since)
    import collections
    print(len(out), "天", collections.Counter(v["标签"].split("·")[0] for v in out.values()))
    for d in sorted(out)[-8:]:
        print(d, json.dumps(out[d], ensure_ascii=False))


if __name__ == "__main__":
    main()
