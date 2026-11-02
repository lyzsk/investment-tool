# -*- coding: utf-8 -*-
"""惯性拓扑→盘中自动采集名单：复用related_inertia结果，写独立自动段，零token。"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTRA = ROOT / "scripts" / "temp" / "collect_book_extra.txt"
BEGIN, END = "# >>> 惯性拓扑自动(inertia_watch.py 生成)", "# <<< 惯性拓扑"


def update(day, extra=EXTRA):
    src = ROOT / "results" / "_live" / day / "inertia_neighbors.json"
    doc = json.loads(src.read_text(encoding="utf-8"))
    evidence, codes = [], set()
    for hold, v in (doc.get("holdings") or {}).items():
        for x in v.get("related") or []:
            if x.get("kind") in ("中军", "资金惯性") and re.fullmatch(r"\d{6}", str(x.get("code") or "")):
                codes.add(x["code"])
                evidence.append({"from": hold, "to": x["code"], "kind": x["kind"], "corr": x.get("corr")})
    text = extra.read_text(encoding="utf-8") if extra.exists() else ""
    text = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", text, flags=re.S)
    if codes:
        text = text.rstrip("\n") + f"\n{BEGIN}\n" + " ".join(sorted(codes)) + f"\n{END}\n"
    extra.write_text(text, encoding="utf-8")
    out = ROOT / "results" / "_live" / day / "inertia_watch.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"date": day, "codes": sorted(codes), "evidence": evidence}, ensure_ascii=False, indent=1), encoding="utf-8")
    return out, sorted(codes)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    a = ap.parse_args()
    out, codes = update(a.date)
    print(f"→ {out} | {len(codes)} 只进盘中自动名单: {','.join(codes)}")
