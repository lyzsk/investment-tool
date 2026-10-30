# -*- coding: utf-8 -*-
"""forecast_ledger.py — 项目统一的「事前预测 → 事后核销 → 校准」账本(10/30 用户令; 零 token, 本地 SQLite)

不是 market-skill 规则库: 这里只保存事前说了什么、实际发生什么、哪类预测在哪些情境下可靠。
其他环节(K 线 / 明日预案 / 我的判断 / 发哥 / skill 线)各自做适配器, 不重复造核销口径。

接口:
  put(...)                       写入一条预测(dedupe 幂等)
  settle(dedupe, actual, hit, baseline_hit)  写实际结果
  calib(source, kind, context=None)          → {n, hit, baseline, delta}(排除事后补写)
  write_summary()                → results/forecast/summary.md
"""
import datetime as dt
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "forecast"
DB = OUT / "ledger.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions(
 dedupe TEXT PRIMARY KEY, source TEXT, kind TEXT, code TEXT, issued_at TEXT, horizon INTEGER,
 predicted TEXT, prob REAL, context TEXT, late INTEGER DEFAULT 0,
 actual TEXT, hit INTEGER, baseline_hit INTEGER, prev_hit INTEGER, evaluated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_forecast_calib ON predictions(source, kind, context, late, hit);
"""


def db():
    OUT.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("pragma table_info(predictions)")}
    if "prev_hit" not in cols:
        c.execute("alter table predictions add column prev_hit integer")
    return c


def put(c, *, source, kind, code, issued_at, horizon, predicted, prob=None, context="", late=False, dedupe):
    c.execute("INSERT INTO predictions(dedupe,source,kind,code,issued_at,horizon,predicted,prob,context,late) VALUES(?,?,?,?,?,?,?,?,?,?) "
              "ON CONFLICT(dedupe) DO UPDATE SET source=excluded.source,kind=excluded.kind,context=excluded.context,late=excluded.late,prob=excluded.prob",
              (dedupe, source, kind, code, issued_at, int(horizon), predicted, prob, context, int(bool(late))))


def settle(c, dedupe, actual, hit, baseline_hit, prev_hit=None):
    c.execute("UPDATE predictions SET actual=?,hit=?,baseline_hit=?,prev_hit=?,evaluated_at=? WHERE dedupe=?",
              (actual, int(bool(hit)), int(bool(baseline_hit)), None if prev_hit is None else int(bool(prev_hit)), dt.datetime.now().isoformat(timespec="seconds"), dedupe))


def calib(c, source, kind, context=None):
    """某类预测在同类情境下的事前命中、同口径基线、差值; n=0 时命中率 None"""
    sql = "select count(*),avg(hit),avg(baseline_hit),avg(prev_hit) from predictions where source=? and kind=? and late=0 and hit is not null"
    args = [source, kind]
    if context is not None:
        sql += " and context=?"
        args.append(context)
    n, h, b, pb = c.execute(sql, args).fetchone()
    return {"n": n, "hit": h, "baseline": b, "prev_baseline": pb,
            "delta": (h - b) if h is not None and b is not None else None,
            "delta_prev": (h - pb) if h is not None and pb is not None else None}


def calibrated_confidence(c, source, kind, context, raw, min_n=20):
    """给我自己的判断用: 同类事前样本够才按真实命中率修正; 不够绝不假装已校准。
    raw = 原置信(高/中/低); 返回 (置信, 说明)。命中 ≥70% 高 / ≥45% 中 / 否则低; 同时报与基线差。"""
    r = calib(c, source, kind, context)
    if r["n"] < min_n or r["hit"] is None:
        return raw, f"校准样本不足(n={r['n']},先保留原置信)"
    lv = "高" if r["hit"] >= 0.70 else "中" if r["hit"] >= 0.45 else "低"
    return lv, f"同类事前命中 {r['hit']:.0%} · 基线 {r['baseline']:.0%} · n={r['n']}"


def write_summary(c):
    L = ["# 预测核销账本(每晚重算; late=事后补写的不计入命中)", "",
         "| 来源 | 类型 | 情境 | n | 命中 | 比震荡 | 比同昨 |", "|---|---|---|---:|---:|---:|---:|"]
    rows = c.execute("select source,kind,context from predictions where late=0 and hit is not null group by source,kind,context order by source,kind,context").fetchall()
    for s, k, ctx in rows:
        r = calib(c, s, k, ctx)
        L.append(f"| {s} | {k} | {ctx or '全体'} | {r['n']} | {r['hit']:.1%} | {r['delta']:+.1%} | {r['delta_prev']:+.1%} |")
    L += ["", "## 汇总(不限情境)", ""]
    for s, k in c.execute("select source,kind from predictions where late=0 and hit is not null group by source,kind").fetchall():
        r = calib(c, s, k)
        L.append(f"- **{s} / {k}**: n={r['n']} · 命中 {r['hit']:.1%} · 比震荡 {r['delta']:+.1%} · 比同昨 {r['delta_prev']:+.1%}")
    (OUT / "summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return len(rows)
