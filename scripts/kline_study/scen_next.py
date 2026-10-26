# -*- coding: utf-8 -*-
"""scen_next.py — 强势股次日 / 隔日情景(10/24 用户考题: 原图上续画未来 K 线)
样本 = strong_next 库同状态(炸板 / 回调 / 首板…, 同 10cm/20cm, 同涨跌档 / 市况 / 情绪 / 价位 / 量比, 样本 <15 逐级放宽), 只用 T 之前的样本
情景按 T+1 收盘(相对 T 收盘)分三档: 强 ≥ +3% / 震荡 −3%~+3% / 弱 ≤ −3%; 概率 = 样本占比; 每档的代表路径 = 档内各字段中位数(T+1 开高低收 + T+2 开高低收)
用法: python scen_next.py <代码> <结果日D>
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper_line" / "tools"))
import strong_next as S   # noqa: E402

SC = (("强", lambda r: r["co"] >= 3), ("震荡", lambda r: -3 < r["co"] < 3), ("弱", lambda r: r["co"] <= -3))


def samples(code, D):
    r = S.query(code, D)
    st = r["当前状态"]
    T = r["T(状态日)"]
    L = [x for x in S.lib() if x["d"] < T]
    for keys in S.TIERS:
        xs = [x for x in L if all(x.get(k) == st.get(k) for k in keys)]
        if len(xs) >= S.MIN_N:
            return r, keys, xs
    return r, keys, xs


def scen(code, D):
    r, keys, xs = samples(code, D)
    out = {"code": code, "T": r["T(状态日)"], "状态": r["当前状态"], "匹配": keys, "n": len(xs), "情景": []}
    for nm, f in SC:
        g = [x for x in xs if x.get("co") is not None and f(x)]
        if not g:
            continue
        med = {k: float(np.median([x[k] for x in g if x.get(k) is not None])) for k in ("gap", "hi", "lo", "co", "o2", "h2", "l2", "c2")}
        med["hi"] = max(med["hi"], med["gap"], med["co"])
        med["lo"] = min(med["lo"], med["gap"], med["co"])
        med["h2"] = max(med["h2"], med["o2"], med["c2"])
        med["l2"] = min(med["l2"], med["o2"], med["c2"])
        rep = min(g, key=lambda x: sum(abs(x[k] - med[k]) for k in ("gap", "hi", "lo", "co")))   # 最像中位路径的真实样本
        out["情景"].append({"名": nm, "概率": round(len(g) / len(xs) * 100), "n": len(g), "路径中位": {k: round(v, 2) for k, v in med.items()},
                          "T+2收盘 P25/中位/P75": [round(float(np.percentile([x["c2"] for x in g], q)), 2) for q in (25, 50, 75)],
                          "代表样本": f"{rep['code']} {rep['d']}"})
    return out


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(scen(sys.argv[1], sys.argv[2]), ensure_ascii=False, indent=1))


H3 = 3   # 10/24 用户: 日 K 和分时都预测 3 日


def _db():
    sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
    import manual_backfill as mb
    return mb.db().cursor()


def scen3(code, D, H=H3):
    """3 日情景: 同状态样本(strong_next 匹配, 只用 T 之前) → 每个样本之后 H 个交易日的真实日 K(相对样本当天收盘 %) → 按第 H 天收盘分 强 ≥+5% / 震荡 / 弱 ≤−5%
    每档: 概率 + 第 H 天收盘 P25/中位/P75 + 代表样本 = 3 日收盘路径最接近档内中位路径的真实样本(画它的真实 K 线 / 分时)"""
    r, keys, xs = samples(code, D)
    c = _db()
    rows = []
    for x in xs:
        sym = ("sh" if x["code"].startswith("6") else "sz") + x["code"]
        c.execute("select close from investment_market.kline_day where symbol=%s and is_deleted=0 and trade_date=%s", (sym, x["d"]))
        b = c.fetchone()
        if not b or not b[0]:
            continue
        base = float(b[0])
        c.execute("select trade_date, open, high, low, close from investment_market.kline_day where symbol=%s and is_deleted=0 and trade_date>%s order by trade_date limit %s", (sym, x["d"], H))
        f = c.fetchall()
        if len(f) < H:
            continue
        path = [{"d": str(t), **{k: (float(v) / base - 1) * 100 for k, v in zip(("o", "h", "l", "c"), (o, h, l, cl))}} for t, o, h, l, cl in f]
        rows.append({"code": x["code"], "sym": sym, "d": x["d"], "path": path})
    out = {"code": code, "T": r["T(状态日)"], "状态": r["当前状态"], "匹配": keys, "n": len(rows), "H": H, "情景": []}
    for nm, f in (("强", lambda v: v >= 5), ("震荡", lambda v: -5 < v < 5), ("弱", lambda v: v <= -5)):
        g = [x for x in rows if f(x["path"][-1]["c"])]
        if not g:
            continue
        med = [{k: float(np.median([x["path"][i][k] for x in g])) for k in ("o", "h", "l", "c")} for i in range(H)]
        rep = min(g, key=lambda x: sum(abs(x["path"][i][k] - med[i][k]) for i in range(H) for k in ("c", "h", "l")))
        cH = [x["path"][-1]["c"] for x in g]
        out["情景"].append({"名": nm, "概率": round(len(g) / len(rows) * 100), "n": len(g), "中位路径": [{k: round(v, 2) for k, v in m.items()} for m in med],
                          f"第{H}天收盘 P25/中位/P75": [round(float(np.percentile(cH, q)), 2) for q in (25, 50, 75)],
                          "代表样本": {"code": rep["code"], "sym": rep["sym"], "d": rep["d"], "path": [{k: (round(v, 2) if k != "d" else v) for k, v in p.items()} for p in rep["path"]]}})
    return out


def minute_path(sym, day):
    """代表样本那天的真实 1 分钟收盘序列(没有就 None)"""
    c = _db()
    c.execute("select bar_time, close from investment_market.kline_minute where symbol=%s and trade_date=%s and is_deleted=0 order by bar_time", (sym, day))
    r = [(str(t), float(v)) for t, v in c.fetchall() if v]
    return r if len(r) >= 120 else None
