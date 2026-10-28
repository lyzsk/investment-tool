# -*- coding: utf-8 -*-
"""official_close.py — 前一交易日的正式收盘价(10/27 事故后建; 零请求, 只读本地)

事故: downloads/quotes/daily/<code>.json 是"边用边补"的缓存, 10/26 09:36 盘中被写过一次, 最后一根 10-26 的 c 是当时的现价(百洋股份 10.13,
     真收盘 11.28)→ 昨收错 → 涨停价算成 11.14(真 12.41)→ 10/27 下午 S4a/S4p/S4b/S4c 对着假涨停价连报, 用户收到"回封动作"
口径: 优先 downloads/market/<D 之前最近一个有 kline_day.jsonl 的交易日>/kline_day.jsonl(收盘后 check md 落的正式日线);
     没有这份文件 / 里面没这只票 → 返回 None, 调用方照旧用日线缓存兜底
"""
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"
_DAY = {}   # D → (那个交易日, {6 位代码: 收盘})


def _load(D):
    if D in _DAY:
        return _DAY[D]
    ds = sorted(d for d in os.listdir(MKT) if re.fullmatch(r"\d{4}-\d\d-\d\d", d) and d < D and (MKT / d / "kline_day.jsonl").exists())
    out = ("", {})
    if ds:
        m = {}
        try:
            for l in (MKT / ds[-1] / "kline_day.jsonl").open(encoding="utf-8"):
                try:
                    r = json.loads(l)
                except ValueError:
                    continue
                if r.get("close") is not None:
                    m[str(r["symbol"])] = float(r["close"])   # 带市场前缀: sh000001 = 上证指数 ≠ sz000001 = 平安银行
        except OSError:
            m = {}
        out = (ds[-1], m)
    _DAY[D] = out
    return out


def sym(c):
    """6 位代码 → 带市场前缀(个股 / 转债 / ETF; 指数请直接传 sh000001 这种带前缀的)"""
    c = str(c)
    if c[:2] in ("sh", "sz", "bj"):
        return c
    if c.startswith(("6", "9", "5", "11")):
        return "sh" + c
    if c.startswith(("4", "8", "92")):
        return "bj" + c
    return "sz" + c   # 0 / 2 / 3 / 12 / 15 / 16 / 18


def prev_close(c, D):
    """→ 前一交易日正式收盘价; 拿不到 → None"""
    _, m = _load(D)
    return m.get(sym(c))
