# -*- coding: utf-8 -*-
"""review/buy_audit.py — 买入侧体检(10/28 晚用户令 E; 零 token): live 线为什么不买?
对每条 live 拟人线 × 当天: 导师真人买了哪些票 → 这些票在本线 01 候选池 / 04 选票 / 06 买单 / 成交 各走到哪一步, 断在哪一步、断的原因(04 的动作 / 06 why / 剔单事件)
另统计: 04 选了「建 / 加」的票数, 06 出买单的票数, 成交的买单数; 06 买单规则数 vs 卖单规则数
产物: results/_live/<D>/review/buy_audit.md(进回看页问题区 + check md 总结)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/review/buy_audit.py [--date D]
"""
import argparse
import datetime as dt
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
LIVE = ROOT / "results" / "_live"


def jl(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def mentor_buys(D, sk):
    import manual_backfill as mb
    c = mb.db().cursor()
    c.execute("select stock_code, stock_name, min(record_time), avg(price) from investment_tool.tzzb_record where record_type='bs_leg' and is_deleted=0 "
              "and date(record_time)=%s and ledger=%s and side like '%%买%%' group by 1, 2", (D, sk))
    return [(str(a), b, t.strftime("%H:%M"), float(p)) for a, b, t, p in c.fetchall() if a and str(a).isdigit()]


def audit(D):
    L = [f"# 买入侧体检 {D}(live 线为什么不买; 零 token)", ""]
    for ld in sorted((LIVE / D).glob("live_*")):
        sk = ld.name[5:]
        vers = sorted(ld.glob("versions/*"))
        acts = [json.loads(l) for l in (ld / "actions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()] if (ld / "actions.jsonl").exists() else []
        p04 = {}
        b06, s06 = {}, 0
        for v in vers:
            j4 = jl(v / "04.json") or {}
            for x in j4.get("picks") or []:
                if x.get("action") in ("建", "加"):
                    p04.setdefault(str(x.get("code")), []).append(f"{v.name[3:9]} {x.get('action')} {x.get('target_pct')}%")
            j6 = jl(v / "06.json") or {}
            for x in j6.get("codes") or []:
                for r in x.get("rules") or []:
                    if r.get("side") == "BUY":
                        b06.setdefault(str(x.get("code")), []).append(f"{v.name[3:9]} {r.get('px') or r.get('style') or r.get('intent')}")
                    elif r.get("side") == "SELL":
                        s06 += 1
        nb = sum(1 for a in acts if a.get("side") == "BUY")
        L += [f"## {sk}", f"- 版本 {len(vers)} · 04 选「建 / 加」的票 {len(p04)} 只 · 06 出过买单的票 {len(b06)} 只(买单规则 {sum(len(v) for v in b06.values())} / 卖单规则 {s06})· 买入成交 {nb} 笔", ""]
        ev = [json.loads(l) for l in (ld / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()] if (ld / "events.jsonl").exists() else []
        drops = [e for e in ev if "剔" in str(e.get("kind")) and "买" in str(e.get("kind"))]
        try:
            mb_ = mentor_buys(D, sk) if sk != "taoge" else []
        except Exception:   # noqa: BLE001
            mb_ = []
        if mb_:
            L.append("| 导师真人买 | 时刻 / 均价 | 01 候选池 | 04 建 / 加 | 06 买单 | 成交 | 断在哪 |")
            L.append("|---|---|---|---|---|---|---|")
            for code, nm, t, px in mb_:
                in01 = sum(1 for v in vers if code in ((v / "01_facts.md").read_text(encoding="utf-8", errors="ignore") if (v / "01_facts.md").exists() else ""))
                fill = [a for a in acts if a.get("code") == code and a.get("side") == "BUY"]
                stage = "成交" if fill else "06 有买单没成交" if code in b06 else "04 选了 06 没出单" if code in p04 else "在候选池 04 没选" if in01 else "不在候选池"
                L.append(f"| {nm}({code}) | {t} {px:.2f} | {in01}/{len(vers)} 版 | {('; '.join(p04.get(code, [])[:2])) or '-'} | {('; '.join(b06.get(code, [])[:2])) or '-'} | {len(fill)} | {stage} |")
            L.append("")
        if drops:
            L.append("- 剔买单事件: " + "; ".join(f"{e.get('t')} {e.get('kind')} {e.get('codes') or ''}" for e in drops[:6]))
            L.append("")
    out = LIVE / D / "review" / "buy_audit.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    audit(a.date)


if __name__ == "__main__":
    main()
