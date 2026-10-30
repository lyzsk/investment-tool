# -*- coding: utf-8 -*-
"""kline_study/kline_score.py — K 线预测每晚核销(10/28 晚用户令: 和「明日预案」一样跟 check md 走; 零 token)
对 results/kline/<日>/_status.json 里每张截图的预测, 次日 / 后天行情出来后对答案:
  v2(scen_v2 单日第 1)· pa(pa_reason T+1 第 1)· 基线(永远猜「震荡」)三者命中率; 两日组合第 1 名命中率
产物: results/kline/_score.md(累计表 + 最近 3 天逐只)+ _score.json
用法: C:/Users/admin/anaconda3/python.exe -X utf8 scripts/kline_study/kline_score.py
"""
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KL = ROOT / "results" / "kline"


def walk(o, h, l, c, pc, lim):
    up, dn, k = round(pc * (1 + lim) + 1e-9, 2), round(pc * (1 - lim) + 1e-9, 2), lim / 0.1
    O, H, L_, C = [(x / pc - 1) * 100 for x in (o, h, l, c)]
    if c >= up - 0.005:
        return "涨停"
    if c <= dn + 0.005:
        return "跌停"
    if H >= 5 * k and C <= H - 6 * k:
        return "冲高A杀"
    if O >= 2 * k and C < O - 3 * k:
        return "高开低走"
    rng = H - L_ or 1e-9
    if C >= 3 * k and (C - L_) / rng >= 0.75:
        return "单边上涨"
    if L_ <= -5 * k and C >= L_ + 5 * k:
        return "深V"
    if C <= -3 * k and (C - L_) / rng <= 0.25:
        return "单边下跌"
    return "震荡"


def main():
    day = {}
    for f in glob.glob(str(ROOT / "downloads" / "market" / "20*" / "kline_day.jsonl")):
        for l in open(f, encoding="utf-8"):
            r = json.loads(l)
            if r.get("preClose"):
                day[(r["symbol"][2:], r["tradeDate"])] = r
    ds = sorted({d for _, d in day})
    nxt = lambda d: next((x for x in ds if x > d), None)   # noqa: E731
    lim = lambda c: 0.2 if c[:3] in ("300", "301", "688") or c[:2] in ("11", "12") else 0.1   # noqa: E731
    rows, seen = [], set()
    for st in sorted(glob.glob(str(KL / "20*" / "_status.json"))):
        S = json.load(open(st, encoding="utf-8"))
        for g in S.get("images", {}).values():
            p, code = g.get("预测") or {}, (g.get("ocr") or {}).get("code")
            if not p.get("单日top3") or not code or "@" not in str(g.get("case")):
                continue
            T = g["case"].split("@")[1]
            if (code, T) in seen:
                continue
            T1 = nxt(T)
            r1 = day.get((code, T1)) if T1 else None
            if not r1:
                continue
            seen.add((code, T))
            a1 = walk(r1["open"], r1["high"], r1["low"], r1["close"], r1["preClose"], lim(code))
            T2 = nxt(T1)
            r2 = day.get((code, T2)) if T2 else None
            a2 = walk(r2["open"], r2["high"], r2["low"], r2["close"], r2["preClose"], lim(code)) if r2 else None
            pa = None
            try:
                w = json.load(open(KL / f"pa_reason_{code}_{T}.json", encoding="utf-8"))["未来2根"]["T+1 走法"]
                pa = (w[0] if isinstance(w[0], str) else (w[0].get("走法") or w[0].get("name") or str(w[0]))).split()[0] if w else None
            except Exception:   # noqa: BLE001
                pass
            v2 = p["单日top3"][0].split()[0]
            side_hit = None
            try:   # 10/28 晚: 正例 = 涨向 / 跌向 / 平 合计概率最高的方向 → 方向命中(和画图同口径)
                import sys as _s
                _s.path.insert(0, str(ROOT / "scripts" / "kline_study"))
                import scen_v2 as SV
                import draw_future as DF
                sc = SV.scen(code, T)
                pr = DF.v2_pair(sc)
                if pr:
                    side_hit = DF.wdir(a1) == pr[0]["方向"]
            except Exception:   # noqa: BLE001
                pass
            two = (p.get("两日top3") or [""])[0].split()[0]
            rows.append({"code": code, "T": T, "实际T+1": a1, "实际T+2": a2, "v2": v2, "pa": pa, "v2两日": two,
                         "v2中": v2 == a1, "pa中": (pa == a1) if pa else None, "基线中": a1 == "震荡", "正例方向中": side_hit, "两日中": (two == f"{a1}→{a2}") if a2 else None})
    n = len(rows)
    rate = lambda k: (sum(1 for r in rows if r[k]) , sum(1 for r in rows if r[k] is not None))   # noqa: E731
    L = ["# K 线预测核销(每晚 check md 自动重算; T+1 走法 8 类)", "",
         "| 方法 | 命中 / 样本 | 命中率 |", "|---|---|---|"]
    for k, nm in (("正例方向中", "正例方向(涨 / 跌 / 平 合计最高)"), ("v2中", "v2 单日第 1"), ("pa中", "pa_reason T+1 第 1"), ("基线中", "基线: 永远猜震荡"), ("两日中", "v2 两日组合第 1")):
        h, m = rate(k)
        L.append(f"| {nm} | {h} / {m} | {h / m:.0%} |" if m else f"| {nm} | 0 / 0 | - |")
    L += ["", "## 最近 3 个截止日逐只", "", "| 票 | 截止日 | 实际 T+1 | 实际 T+2 | v2 | pa |", "|---|---|---|---|---|---|"]
    last = sorted({r["T"] for r in rows})[-3:]
    for r in rows:
        if r["T"] in last:
            L.append(f"| {r['code']} | {r['T'][5:]} | {r['实际T+1']} | {r['实际T+2'] or '-'} | {r['v2']}{'✓' if r['v2中'] else ''} | {r['pa'] or '-'}{'✓' if r['pa中'] else ''} |")
    (KL / "_score.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (KL / "_score.json").write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")
    print("\n".join(L[:8]), f"\n(共 {n} 只)")
    import forecast_kline_ingest as FI   # 10/30: kline_score 同时是 forecast_ledger 的 K 线适配器, nightly 不再另跑一份
    FI.main()


if __name__ == "__main__":
    main()
