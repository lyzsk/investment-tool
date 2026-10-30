# -*- coding: utf-8 -*-
"""forecast_kline_ingest.py — 把 results/kline/<日>/_status.json 的 v2 预测写入 forecast_ledger, 用实际日 K 核销(零 token)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/kline_study/forecast_kline_ingest.py
"""
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "lib"), str(ROOT / "scripts" / "kline_study")]
import forecast_ledger as FL   # noqa: E402
from kline_score import walk   # noqa: E402


def daily():
    day = {}
    for f in glob.glob(str(ROOT / "downloads" / "market" / "20*" / "kline_day.jsonl")):
        for l in open(f, encoding="utf-8"):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if r.get("preClose"):
                day[(r["symbol"][2:], r["tradeDate"])] = r
    return day


def main():
    D = daily()
    ds = sorted({d for _, d in D})
    nxt = lambda d: next((x for x in ds if x > d), None)   # noqa: E731
    lim = lambda c: 0.2 if c[:3] in ("300", "301", "688") or c[:2] in ("11", "12") else 0.1   # noqa: E731
    c = FL.db()
    n_pred = n_eval = n_late = 0
    for st in sorted(glob.glob(str(ROOT / "results" / "kline" / "20*" / "_status.json"))):
        try:
            S = json.load(open(st, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for g in S.get("images", {}).values():
            p = g.get("预测") or {}
            case = str(g.get("case") or "")
            if p.get("引擎") != "v2" or "@" not in case or not p.get("单日top3"):
                continue
            code, T = case.split("@", 1)
            issued = str(p.get("时间") or st.split("_status")[0][-10:])
            late = issued[:10] > T   # 收盘后补画历史截图 = 不是事前预测, 只留档不计命中
            ctx = f"票型:{p.get('票型') or '未知'}"
            t1, t2 = nxt(T), None
            r1 = D.get((code, t1)) if t1 else None
            late = bool(t1 and issued.replace("T", " ")[:16] >= f"{t1} 15:00")   # 目标日收盘后补写才排除; 目标日盘前 / 盘中仍是事前
            a1 = walk(r1["open"], r1["high"], r1["low"], r1["close"], r1["preClose"], lim(code)) if r1 else None
            if t1:
                t2 = nxt(t1)
            r2 = D.get((code, t2)) if t2 else None
            a2 = walk(r2["open"], r2["high"], r2["low"], r2["close"], r2["preClose"], lim(code)) if r2 else None
            r0 = D.get((code, T))
            a0 = walk(r0["open"], r0["high"], r0["low"], r0["close"], r0["preClose"], lim(code)) if r0 else None
            for kind, horizon, preds, actual, baseline in (("single", 1, p.get("单日top3") or [], a1, "震荡"),
                                                            ("two_day", 2, p.get("两日top3") or [], f"{a1}→{a2}" if a1 and a2 else None, "震荡→震荡")):
                for rank, txt in enumerate(preds[:3], 1):
                    predicted = str(txt).split()[0]
                    if not predicted or (horizon == 2 and "→" not in predicted):
                        continue
                    try:
                        prob = float(str(txt).split()[1].rstrip("%"))
                    except (IndexError, ValueError):
                        prob = None
                    dedupe = f"kline_v2|{kind}|{code}|{T}|{rank}|{issued}"
                    FL.put(c, source="kline_v2", kind=f"{kind}_top{rank}", code=code, issued_at=issued, horizon=horizon, predicted=predicted,
                           prob=prob, context=ctx, late=late, dedupe=dedupe)
                    n_pred += 1
                    n_late += int(late)
                    if actual:
                        prev = (a0 if horizon == 1 else f"{a0}→{a0}") if a0 else None
                        FL.settle(c, dedupe, actual, predicted == actual, baseline == actual, prev == actual if prev else None)
                        n_eval += 1
    # 直接生成的持仓卡(没有截图)也统一核销: dedupe 里带预测基准日 T
    for dedupe, code, horizon, predicted in c.execute("select dedupe,code,horizon,predicted from predictions where source='kline_v2' and actual is null").fetchall():
        try:
            T = dedupe.split("|")[3]
            t1 = nxt(T)
            r1 = D.get((code, t1)) if t1 else None
            if not r1:
                continue
            a1 = walk(r1["open"], r1["high"], r1["low"], r1["close"], r1["preClose"], lim(code))
            actual, baseline = a1, "震荡"
            if horizon == 2:
                t2 = nxt(t1)
                r2 = D.get((code, t2)) if t2 else None
                if not r2:
                    continue
                a2 = walk(r2["open"], r2["high"], r2["low"], r2["close"], r2["preClose"], lim(code))
                actual, baseline = f"{a1}→{a2}", "震荡→震荡"
            r0 = D.get((code, T))
            a0 = walk(r0["open"], r0["high"], r0["low"], r0["close"], r0["preClose"], lim(code)) if r0 else None
            prev = (a0 if horizon == 1 else f"{a0}→{a0}") if a0 else None
            FL.settle(c, dedupe, actual, predicted == actual, baseline == actual, prev == actual if prev else None)
            n_eval += 1
        except (IndexError, KeyError, TypeError):
            continue
    c.commit()
    groups = FL.write_summary(c)
    c.close()
    print(json.dumps({"predictions": n_pred, "evaluated": n_eval, "late_excluded": n_late, "groups": groups,
                      "db": str(FL.DB), "summary": str(FL.OUT / "summary.md")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
