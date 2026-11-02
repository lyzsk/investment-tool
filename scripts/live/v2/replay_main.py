# -*- coding: utf-8 -*-
"""live v2 主交互验收：真实历史 signal，两轮共用一会话；默认 dry，--execute 才调用模型。"""
import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "live"), str(ROOT / "scripts" / "knowledge"), str(Path(__file__).resolve().parent)]
import signals as SG  # noqa: E402
from driver import process_event  # noqa: E402
from session import V2Session  # noqa: E402
from store import KnowledgeStore  # noqa: E402


def real_events(source, codes, sigs, until="09:25"):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        kept = SG.replay(source, until=until, codes=codes, all_=False, samples=0)
    SG.D_NOW["D"] = source
    try:
        stat_days = json.loads((ROOT / "results" / "_live" / "signal_odds.json").read_text(encoding="utf-8")).get("days") or []
    except (OSError, ValueError):
        stat_days = []
    stats_ok = bool(stat_days) and max(stat_days) < source
    out = []
    for e in kept:
        if e["code"] in codes and e["sig"] in sigs:
            if stats_ok:
                SG.odds_gate(e)
            else:
                e["odds"] = None
                e["stats_pending"] = "没有严格早于信号日的统计，禁止用未来核销表"
            e["replay_of"] = source
            e["mode"] = "post_close_replay_not_live_order"
            out.append(e)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="复核发生日；情境只取该时刻前可见数据")
    ap.add_argument("--replay-date", required=True)
    ap.add_argument("--codes", default="600785,002724")
    ap.add_argument("--sigs", default="S17,S16")
    ap.add_argument("--max", type=int, default=2)
    ap.add_argument("--execute", action="store_true")
    a = ap.parse_args()
    codes, sigs = a.codes.split(","), a.sigs.split(",")
    events = real_events(a.replay_date, codes, set(sigs))
    if not events:
        raise ValueError("真实回放没有所选 signal，不构造替代事件")
    out = ROOT / "results" / "_live" / a.date / "live_v2"
    store = KnowledgeStore(ROOT / "downloads" / "ontology" / "ontology.db")
    ses = V2Session(a.date, out) if a.execute else None
    results = []
    try:
        for e in events[:a.max]:
            r = process_event(store, e, a.date, out, execute=a.execute, session=ses)
            results.append({"event": {k: e.get(k) for k in ("replay_of", "t", "code", "name", "sig", "px")},
                            "executed": r.get("executed"), "status": r.get("status", "ok"), "case_id": (r.get("case") or {}).get("case_id"),
                            "session_id": r.get("session_id"), "cost_usd": r.get("cost_usd"), "decision": r.get("decision")})
    finally:
        store.close()
    print(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
