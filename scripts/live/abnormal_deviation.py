# -*- coding: utf-8 -*-
"""U53 异动偏离：区间涨幅−对应A指，1~N日滚动取最大；截至指定日收盘，零token。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "review"), str(ROOT / "scripts" / "backfill_bilibili")]
from mentor_cards import daily, sym  # noqa: E402


def index_of(code):
    return "sh000002" if code[0] == "6" else ("sz399102" if code[:3] in ("300", "301") else ("sh000688" if code[:3] == "688" else "sz399107"))


def deviation(code, day, win):
    K = [b for b in daily(sym(code), day, 45)]
    I = {b["d"]: b["c"] for b in daily(index_of(code), day, 45)}
    ks = [b for b in K if b["d"] in I]
    if len(ks) < 2 or ks[-1]["d"] != day:
        return {"code": code, "win": win, "status": "缺数据", "n": len(ks)}
    cur = ks[-1]
    best = max(((cur["c"] / ks[-1 - k]["c"] - 1) * 100 - (I[cur["d"]] / I[ks[-1 - k]["d"]] - 1) * 100, k, ks[-1 - k]["d"])
               for k in range(1, min(win, len(ks) - 1) + 1))
    return {"code": code, "win": win, "value": round(best[0], 4), "days": best[1], "from": best[2], "to": cur["d"], "index": index_of(code)}


def evaluate(code, day):
    d10, d30 = deviation(code, day, 10), deviation(code, day, 30)
    severe = (d10.get("value") or -10**9) >= 100 or (d30.get("value") or -10**9) >= 200
    return {"code": code, "date": day, "status": "严重异动" if severe else "绕开", "d10": d10, "d30": d30,
            "rule": "10日最大偏离>=100% 或 30日>=200% = 严重异动；截至收盘"}


if __name__ == "__main__":
    D = sys.argv[1]
    codes = sys.argv[2].split(",")
    out = [evaluate(c, D) for c in codes]
    f = ROOT / "results" / "_live" / D / "abnormal_deviation.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
