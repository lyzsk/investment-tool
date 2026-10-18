# -*- coding: utf-8 -*-
"""chain_t_stats.py — 链自己的 T 成绩(10/17 用户定: 链的 T 盈亏要回灌 07 复盘和反思触发; 零 token, 只读)

T 口径 = 同一交易日同一只票既有买入成交又有卖出成交(先买后卖=正T 底仓/新仓回转, 先卖后买=倒T)。
回转额 = min(买入额, 卖出额); 扣费后 T 盈亏 = 配对部分 (卖均价 − 买均价) × 配对股数 − 当日该票全部费用; 占回转额 = 收益率。
对照: 导师本人当日 T(downloads/tzzb 逐笔腿, 同口径) + 导师长期 T 画像判定(t_profile: 执行T/不学T, 期望, 胜率)。
用法: from chain_t_stats import day_t, block_07, streak
  day_t(book, d) → [{code, kind, qty, pnl, ret}] ; block_07(skill, book, d, asof) → 07 注入文本 ; streak(book, d, n) → 近 n 个有 T 日的扣费后 pnl 列表
CLI: python chain_t_stats.py --book A-lianghuaxiaohao --date 2026-10-16 [--root 沙盒数据根] | --selftest
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def _hm(tr):
    m = re.search(r"(\d{2}:\d{2})", str(tr.get("why") or ""))
    return m.group(1) if m else "99:99"


def day_t(book, d):
    """10/17 审计中-1 修: 按成交时间顺序配对(先买后卖=正T, 先卖后买=倒T), 配对量取 min, 手续费按配对量占比分摊;
    没被配对的部分(如底仓止损卖出、新开仓留仓)不计入 T"""
    by = defaultdict(list)
    for tr in book.get("trades") or []:
        if str(tr.get("id") or "").startswith(d):
            by[str(tr.get("code"))].append(tr)
    out = []
    for code, ts in by.items():
        ts = sorted(ts, key=lambda x: (_hm(x), str(x.get("id"))))
        opens = []   # [side, 剩余量, 价, 单位手续费, 原始量]
        pairs = defaultdict(lambda: {"qty": 0, "pnl": 0.0, "amt": 0.0})
        for tr in ts:
            side, q, px = ("B" if tr.get("side") == "BUY" else "S"), int(tr.get("qty") or 0), float(tr.get("price") or 0)
            fee_u = float(tr.get("fee") or 0) / q if q else 0.0
            while q > 0 and opens and opens[0][0] != side:
                o = opens[0]
                m = min(q, o[1])
                buy_px, sell_px = (o[2], px) if o[0] == "B" else (px, o[2])
                kind = "正T" if o[0] == "B" else "倒T"
                pairs[kind]["qty"] += m
                pairs[kind]["pnl"] += (sell_px - buy_px) * m - (o[3] + fee_u) * m
                pairs[kind]["amt"] += buy_px * m
                o[1] -= m
                q -= m
                if o[1] == 0:
                    opens.pop(0)
            if q > 0:
                opens.append([side, q, px, fee_u, q])
        for kind, v in pairs.items():
            if v["qty"]:
                out.append({"code": code, "kind": kind, "qty": v["qty"], "pnl": round(v["pnl"], 2), "ret": round(v["pnl"] / v["amt"], 5) if v["amt"] else 0.0})
    return out


def streak(book, d, n=3):
    """截至 d(含)最近 n 个"有 T"的交易日, 每日扣费后 T 盈亏合计(新→旧)"""
    days = sorted({str(t.get("id", ""))[:10] for t in book.get("trades") or [] if str(t.get("id", ""))[:10] <= d}, reverse=True)
    res = []
    for x in days:
        ts = day_t(book, x)
        if ts:
            res.append((x, round(sum(t["pnl"] for t in ts), 2)))
        if len(res) >= n:
            break
    return res


def _mentor_profile(skill, asof):
    for f in sorted((HERE / "t_profile").glob("*.json"), reverse=True):
        if f.stem <= asof:
            try:
                return (json.loads(f.read_text(encoding="utf-8")).get("mentors") or {}).get(skill)
            except (OSError, ValueError):
                return None
    return None


def _mentor_day_t(skill, d):
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "tzzb"))
        from gen_tzzb_profile import load_legs   # noqa: PLC0415
        legs = [x for x in load_legs(skill) if str(x.get("trans_date", "")).startswith(d) and x.get("op") in ("1", "2")]
    except Exception:   # noqa: BLE001
        return None
    by = defaultdict(lambda: {"1": [0, 0.0], "2": [0, 0.0]})
    for x in legs:
        g = by[str(x.get("stock_code"))][x["op"]]
        g[0] += float(x.get("trans_count") or 0)
        g[1] += float(x.get("trans_amount") or 0) or float(x.get("trans_price") or 0) * float(x.get("trans_count") or 0)
    out = []
    for code, g in by.items():
        if g["1"][0] and g["2"][0]:
            q = min(g["1"][0], g["2"][0])
            pb, ps = g["1"][1] / g["1"][0], g["2"][1] / g["2"][0]
            out.append({"code": code, "ret": (ps - pb) / pb if pb else 0.0})
    return out


def block_07(skill, book, d, asof=None):
    ts = day_t(book, d)
    prof = _mentor_profile(skill, asof or d)
    v = (prof or {}).get("verdict")
    L = ["\n## 本链今天的 T 成绩（驱动器注入, 10/17 起; 同一只票当天既买又卖 = T; 已扣手续费）"]
    if not ts:
        L.append("- 本链今天没有做 T。")
    for t in ts:
        L.append(f"- {t['code']} {t['kind']} {t['qty']} 股: 扣费后 {t['pnl']:+.0f} 元({t['ret']:+.2%} 占回转额)")
    if prof:
        lg = prof.get("long") or {}
        L.append(f"- 导师 T 画像判定: **{v}**(长期 {lg.get('n', 0)} 笔, 每笔扣费后均值 {float(lg.get('ret_mean') or 0):+.2%}, 胜率 {float(lg.get('win') or 0):.0%}, t={lg.get('t')})")
    mt = _mentor_day_t(skill, d)
    if mt is not None:
        L.append("- 导师本人今天的 T: " + ("无" if not mt else "、".join(f"{x['code']}({x['ret']:+.2%})" for x in mt)))
    sk = streak(book, d, 3)
    if sk:
        L.append("- 本链最近有 T 的日子(扣费后合计): " + "；".join(f"{x} {p:+.0f} 元" for x, p in sk))
    L.append("- 复盘要求: 本链今天的 T 和导师比, 是该做没做 / 不该做做了 / 做了但价差不够(扣费后为负)? "
             + ("导师判定是\"不学T\", 本链今天若做了 T 必须写成教训。" if v == "不学T" else "导师判定是\"执行T\", 若本链扣费后为负, 写清是挂价、时机还是规模的问题。" if v == "执行T" else ""))
    return "\n".join(L)


def selftest():
    b = {"trades": [{"id": "2026-10-16-A-x-001", "side": "BUY", "code": "600000", "price": 10.0, "qty": 1000, "fee": 5},
                    {"id": "2026-10-16-A-x-002", "side": "SELL", "code": "600000", "price": 10.2, "qty": 1000, "fee": 10.1},
                    {"id": "2026-10-16-A-x-003", "side": "BUY", "code": "000001", "price": 11.0, "qty": 500, "fee": 5},
                    {"id": "2026-10-15-A-x-001", "side": "SELL", "code": "600000", "price": 10.0, "qty": 500, "fee": 5},
                    {"id": "2026-10-15-A-x-002", "side": "BUY", "code": "600000", "price": 10.1, "qty": 500, "fee": 5}]}
    t = day_t(b, "2026-10-16")
    assert len(t) == 1 and t[0]["kind"] == "正T" and abs(t[0]["pnl"] - (200 - 15.1)) < 0.01, t
    t2 = day_t(b, "2026-10-15")
    assert t2[0]["kind"] == "倒T" and t2[0]["pnl"] < 0, t2
    assert [x for x, _ in streak(b, "2026-10-16", 3)] == ["2026-10-16", "2026-10-15"]
    assert "没有做 T" in block_07("x", b, "2026-10-14")
    lu = {"trades": [{"id": "2026-10-16-A-l-028", "side": "SELL", "code": "300364", "price": 26, "qty": 200, "fee": 7.6, "why": "分钟回放@2026-10-16 09:31"},
                     {"id": "2026-10-16-A-l-031", "side": "BUY", "code": "300364", "price": 25.26, "qty": 200, "fee": 5, "why": "分钟回放@2026-10-16 10:15"},
                     {"id": "2026-10-16-A-l-034", "side": "SELL", "code": "300364", "price": 23.95, "qty": 300, "fee": 8.59, "why": "止损哨兵(分钟回放 14:42)"}]}
    t3 = day_t(lu, "2026-10-16")
    assert len(t3) == 1 and t3[0]["kind"] == "倒T" and t3[0]["qty"] == 200 and abs(t3[0]["pnl"] - (0.74 * 200 - 12.6)) < 0.01, t3   # 审计实例: 约 +135
    print("CHAIN_T_STATS SELFTEST PASS")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--book")
    ap.add_argument("--date")
    ap.add_argument("--root", default=str(HERE))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    else:
        bk = json.loads((Path(a.root) / "books" / f"{a.book}.json").read_text(encoding="utf-8"))
        sk = "buchitudou0" if a.book == "A-cb" else a.book[2:]
        print(block_07(sk, bk, a.date))
