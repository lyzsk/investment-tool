# -*- coding: utf-8 -*-
"""window_similar.py — 滑动窗口相似(10/22 晚用户令: 现有资源能做的相似度都做; 日级 + 分钟级)

日级(--daily): 目标票截至 D 前一日的最近 N 天走势(收益序列 + 振幅 + 量比), 在同类品种(转债 / 全 A)的全部历史窗口里找最像的 K 段,
               看这 K 段"之后"第 1 天的 开盘缺口 / 开盘后最高 / 收盘相对开盘 / 第 5 天累计 分布; N 默认 5、10、20 各算一遍
分钟级(--minute): 目标票 D 日开盘到时刻 t 的分钟路径(相对昨收的涨跌序列), 在全市场转债历史分钟路径(cb_minute_universe 产物)里找最像的 K 天,
               看它们 t 之后到收盘的 最高 / 最低 / 收盘 分布 —— 回答"走到这一步, 历史上同样走法的后来怎么样"
距离: 序列先减均值、除以标准差(形状) + 单独比较幅度(水平), 欧氏距离加权; 只用 D 之前的数据(防偷看未来)
用法:
  python window_similar.py --daily --code 111024 --date 2026-10-22 [--kind cb] [--k 30]
  python window_similar.py --minute --code 111024 --date 2026-10-22 --at 10:00 [--k 30]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))


def db():
    import manual_backfill as mb
    c = mb.db()
    c.cursor().execute("use investment_market")
    return c


def load_daily(kind, since="2019-01-01"):
    cur = db().cursor()
    t = "CB" if kind == "cb" else "STOCK"
    cur.execute("select k.symbol, k.trade_date, k.open, k.high, k.low, k.close, k.volume from kline_day k join security_master s on s.symbol=k.symbol "
                "where s.sec_type=%s and k.is_deleted=0 and k.trade_date >= %s and k.open > 0 order by k.symbol, k.trade_date", (t, since))
    S = {}
    for s, d, o, h, l, c, v in cur.fetchall():
        S.setdefault(s, []).append((str(d), float(o), float(h), float(l), float(c), float(v or 0)))
    return S


def feat(win):
    """win: 连续 N+1 根日线(含窗口前一根作基准) → 形状向量 + 水平向量"""
    c = np.array([x[4] for x in win])
    r = np.diff(np.log(c)) * 100
    amp = np.array([(x[2] - x[3]) / p[4] * 100 for p, x in zip(win, win[1:])])
    v = np.array([x[5] for x in win[1:]])
    vr = np.log((v + 1) / (v.mean() + 1))
    shape = np.concatenate([(r - r.mean()) / (r.std() + 1e-6), vr])
    level = np.array([r.sum(), amp.mean(), r[-1]])
    return shape, level


def outcome(k, i):
    """第 i 根(窗口后的第 1 天)及之后的结果"""
    p, x = k[i - 1], k[i]
    o = {"gap": (x[1] / p[4] - 1) * 100, "hi": (x[2] / x[1] - 1) * 100, "co": (x[4] / x[1] - 1) * 100}
    if i + 4 < len(k):
        o["d5"] = (k[i + 4][4] / p[4] - 1) * 100
    return o


def daily(code, D, kind="cb", N=10, K=30):
    S = load_daily(kind)
    sym = next((s for s in S if s[2:] == code), None)
    tk = [x for x in S[sym] if x[0] < D]
    qs, ql = feat(tk[-(N + 1):])
    shapes, levels, outs, meta = [], [], [], []
    for s, k in S.items():
        for i in range(N + 1, len(k) - 1):
            if k[i][0] >= D or (s == sym and i > len(tk) - N):
                break
            sh, lv = feat(k[i - N - 1:i])
            shapes.append(sh)
            levels.append(lv)
            outs.append(outcome(k, i))
            meta.append((s[2:], k[i][0]))
    A, L = np.array(shapes), np.array(levels)
    Ls = L.std(0) + 1e-6
    dist = np.sqrt(((A - qs) ** 2).mean(1)) + 0.5 * np.sqrt((((L - ql) / Ls) ** 2).mean(1))
    idx = np.argsort(dist)[:K]
    res = [dict(code=meta[j][0], d=meta[j][1], dist=round(float(dist[j]), 3), **{a: round(b, 2) for a, b in outs[j].items()}) for j in idx]
    def dist_of(key):
        v = sorted(r[key] for r in res if key in r)
        return {"n": len(v), "P25": v[len(v) // 4], "中位": v[len(v) // 2], "P75": v[len(v) * 3 // 4], ">0 比例": round(sum(1 for x in v if x > 0) / len(v), 2)} if v else None
    return {"code": code, "D": D, "N": N, "K": K, "样本窗口数": len(meta), "次日开盘缺口": dist_of("gap"), "次日开盘后最高": dist_of("hi"),
            "次日收盘相对开盘": dist_of("co"), "5 日累计": dist_of("d5"), "最像的 5 段": res[:5]}


def minute(code, D, at="10:00", K=30):
    P = ROOT / "downloads" / "quotes" / "cb" / "minute_path"
    lab = [f"{h:02d}:{m:02d}" for h in (9, 10, 11) for m in range(60) if "09:31" <= f"{h:02d}:{m:02d}" <= "11:30"] + \
          [f"{h:02d}:{m:02d}" for h in (13, 14, 15) for m in range(60) if "13:01" <= f"{h:02d}:{m:02d}" <= "15:00"]
    t = lab.index(at) + 1
    rows = []
    for f in sorted(P.glob("*.jsonl")):
        for l in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(l)
            if r.get("prev") and len(r["p"]) == 240:
                rows.append(r)
    q = next((r for r in rows if r["code"] == code and r["d"] == D), None)
    if not q:
        return {"err": f"没有 {code} {D} 的分钟路径(先跑 cb_minute_universe.py)"}
    hist = [r for r in rows if r["d"] < D]
    def path(r):
        return (np.array(r["p"][:t]) / r["prev"] - 1) * 100
    qp = path(q)
    A = np.array([path(r) for r in hist])
    shape = ((A - A.mean(1, keepdims=True)) / (A.std(1, keepdims=True) + 1e-6) - ((qp - qp.mean()) / (qp.std() + 1e-6))) ** 2
    dist = np.sqrt(shape.mean(1)) + 0.3 * np.abs(A[:, -1] - qp[-1]) / (np.abs(A[:, -1] - qp[-1]).std() + 1e-6)
    idx = np.argsort(dist)[:K]
    outs = []
    for j in idx:
        r = hist[j]
        p_at, rest = r["p"][t - 1], np.array(r["p"][t:])
        outs.append({"code": r["code"], "d": r["d"], "之后最高": round((rest.max() / p_at - 1) * 100, 2), "之后最低": round((rest.min() / p_at - 1) * 100, 2),
                     "到收盘": round((r["p"][-1] / p_at - 1) * 100, 2)})
    def dist_of(key):
        v = sorted(o[key] for o in outs)
        return {"P25": v[len(v) // 4], "中位": v[len(v) // 2], "P75": v[len(v) * 3 // 4], ">0 比例": round(sum(1 for x in v if x > 0) / len(v), 2)}
    real = {"之后最高": round((max(q["p"][t:]) / q["p"][t - 1] - 1) * 100, 2), "到收盘": round((q["p"][-1] / q["p"][t - 1] - 1) * 100, 2)}
    return {"code": code, "D": D, "at": at, "历史路径数": len(hist), "K": K, "此刻相对昨收": round(float(qp[-1]), 2),
            "之后最高": dist_of("之后最高"), "之后最低": dist_of("之后最低"), "到收盘": dist_of("到收盘"), "当天实际(回测用)": real, "最像的 5 天": outs[:5]}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily", action="store_true")
    ap.add_argument("--minute", action="store_true")
    ap.add_argument("--code", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--kind", default="cb")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--k", type=int, default=30)
    ap.add_argument("--at", default="10:00")
    a = ap.parse_args()
    out = daily(a.code, a.date, a.kind, a.n, a.k) if a.daily else minute(a.code, a.date, a.at, a.k)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
