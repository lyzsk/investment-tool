# -*- coding: utf-8 -*-
"""expect与skill 06预测适配器：统一issued/available/target、独立核销和同期基准。"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "lib"), str(ROOT / "scripts" / "paper_line")]
import forecast_ledger as FL  # noqa: E402


def next_day(D):
    ds = sorted(p.name for p in (ROOT / "downloads" / "market").glob("20*") if p.name > D and (p / "kline_day.jsonl").exists())
    return ds[0] if ds else None


def bars(D):
    f = ROOT / "downloads" / "market" / D / "kline_day.jsonl"
    if not f.exists():
        return {}
    out = {}
    for l in f.open(encoding="utf-8"):
        r = json.loads(l)
        sym, code = r["symbol"], r["symbol"][-6:]
        expected = ("sh" if code.startswith(("6", "5", "11")) else "sz") + code
        if sym == expected:
            out[code] = r
    return out


def ingest_expect(c, D):
    f = ROOT / "results" / "_live" / D / "expect.json"
    if not f.exists():
        return 0
    doc = json.loads(f.read_text(encoding="utf-8"))
    issued = dt.datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")
    nd = next_day(D)
    actual = bars(nd) if nd else {}
    market_base = (sum(float(b["high"]) >= float(b["preClose"]) * 1.03 for b in actual.values()) / len(actual)) if actual else None
    n = 0
    for group in doc.get("明日聚焦") or []:
        theme = group.get("题材") or "未知"
        codes = []
        for text in group.get("梯队") or []:
            import re
            m = re.search(r"\((\d{6})\)", text)
            if m:
                codes.append(m.group(1))
        hits = []
        for code in codes:
            b = actual.get(code)
            hit = None if not b else float(b["high"]) >= float(b["preClose"]) * 1.03
            if hit is not None:
                hits.append(hit)
            dedupe = f"expect|{D}|{theme}|{code}"
            FL.put(c, source="expect", kind="candidate", code=code, issued_at=issued, horizon=1,
                   predicted="次日最高≥+3%", prob=None, context=f"题材:{theme}", dedupe=dedupe)
            if hit is not None:
                FL.settle(c, dedupe, "实际次日最高", hit, market_base)   # 同期全市场基准
            n += 1
    return n


def ingest_skill(c, D):
    import viewer
    import viewer_extra as X
    import replay_report as rr
    base = ROOT / "results" / "_live" / D
    if not base.exists():
        return 0
    lines = {x["id"]: x for x in (json.loads((ROOT / "scripts" / "paper_line" / "lines.json").read_text(encoding="utf-8")).get("lines") or [])}
    import skill_names as SN
    for d in sorted(base.glob("live_*")):
        lines.setdefault(d.name, {"id": d.name, "name": SN.cn(d.name[5:]) + "skill", "mode": "watch", "kind": "mimic", "skill": d.name[5:], "live": True})
    records = []
    for lid, line in lines.items():
        bdir = base / lid
        if not bdir.exists():
            continue
        book = viewer.book(bdir, line)
        codes = {t["code"] for t in book["trades"]} | set(book["positions"]) | {o["code"] for v in book["versions"] for o in v["orders"] if o.get("code")}
        bars_ = viewer.charts(D, codes)
        tape = rr.load_tape(D)
        X.order_fates(bdir, book, tape, bars_)
        for v in book["versions"]:
            for o in v["orders"]:
                if o.get("code") not in codes:
                    continue
                fate = o.get("fate") or {}
                cat = fate.get("cat")
                if cat:
                    records.append((lid, v, o, cat))
    base_rate = sum(cat == "成交" for _, _, _, cat in records) / len(records) if records else None
    for lid, v, o, cat in records:
        dedupe = f"skill06|{D}|{lid}|{v['dir']}|{o.get('code')}|{o.get('id')}"
        issued = f"{D}T{v['trig']}"
        FL.put(c, source="skill06", kind="order_fill", code=o["code"], issued_at=issued, horizon=1,
               predicted=f"{o.get('side')} {o.get('op') or ''}{o.get('px')} 可成交", prob=None,
               context=f"skill:{lid}|{o.get('side')}", dedupe=dedupe)
        FL.settle(c, dedupe, cat, cat == "成交", base_rate)
    return len(records)


def main(D):
    c = FL.db()
    n = {"expect": ingest_expect(c, D), "skill06": ingest_skill(c, D), "fage_spec": 0}
    c.commit()
    FL.write_summary(c)
    c.close()
    out = ROOT / "results" / "forecast" / "sources.json"
    old = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    old[D] = n
    out.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(n, ensure_ascii=False))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(sys.argv[1] if len(sys.argv) > 1 else dt.date.today().isoformat())
