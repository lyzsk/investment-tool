# -*- coding: utf-8 -*-
"""slot_rule.py — 时段归属口径(10/17 用户定 A8): 开盘阶段的成交, 没改单 = 盘前(0915)单负责; 改单/盘中追价 = 归子链时段
真人看不到挂单记录, 用 order_inference 的逐单成交方式概率近似(scripts/tzzb/model_out/orders_recs/<导师>.jsonl):
  盘前单概率 p915 = P(集合竞价) + P(被动限价) × [开盘以来价格没穿过成交价(=挂单可能盘前就在)]
  其余(主动追价/改单追上/排板/其他)= 盘中决定, 归成交时刻所在子链时段
只作用于开盘阶段 [09:30, 10:00) 的成交; 没有逐单记录(无分钟线/B站 UP)= None(调用方按旧口径)
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RECS = ROOT / "scripts" / "tzzb" / "model_out" / "orders_recs"
_CACHE = {}


def preopen_map(ledger):
    """{(date, code, side 'B'/'S'): p915} 取同日同票同方向最早一张开盘阶段单"""
    if ledger in _CACHE:
        return _CACHE[ledger]
    out = {}
    f = RECS / f"{ledger}.jsonl"
    if f.exists():
        rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        for r in sorted(rows, key=lambda r: (r["date"], r["t"])):
            if not ("09:30" <= str(r.get("t"))[:5] < "10:00"):
                continue
            k = (r["date"], str(r["code"]), r["side"])
            if k in out:
                continue
            p = r.get("p") or {}
            out[k] = round(float(p.get("集合竞价") or 0) + float(p.get("被动限价") or 0) * (1.0 if r.get("pre_open_ok") else 0.0), 4)
    _CACHE[ledger] = out
    return out


def p915(ledger, date, code, side, hm):
    """单笔成交属于盘前单的概率; 不在开盘阶段=None(按成交时刻归属)"""
    if not ("09:30" <= hm < "10:00"):
        return None
    return preopen_map(ledger).get((date, str(code), side))
