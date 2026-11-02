# -*- coding: utf-8 -*-
"""真实 signal → event_pack → 单会话复核 → 待核案例；默认 dry，--execute 才花 token。"""
import argparse
import datetime as dt
import hashlib
import json
import queue
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "knowledge"), str(Path(__file__).resolve().parent)]
from schema import validate_case, validate_source_manifest  # noqa: E402
from context_pack import ContextPending  # noqa: E402
from epistemics import candidate  # noqa: E402
from lineage import link_analogs  # noqa: E402
from session import V2Session  # noqa: E402
from signal_pack import event_pack  # noqa: E402
from store import KnowledgeStore  # noqa: E402


def prompt_for(pack, day):
    body = json.dumps(pack, ensure_ascii=False, indent=1)
    return (f"[BOOT live-v2 {day}]\n只复核下面这一条真实 signal。保留机械执行边界，不把 signal 直接变成买单/卖单；"
            "置信度必须结合 signal_n、signal_p 和缺失数据，小样本不得写高置信。\n"
            "输出 JSON: stance/action/evidence[字符串]/confidence{raw,n,reason}/invalid_if/next_check。\n"
            f"```json\n{body}\n```")


def case_id(event, day):
    raw = f"{day}|{event['code']}|{event['sig']}|{event['t']}"
    return "live_v2:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def record_result(store, pack, event, decision, day, out_dir):
    """模型只产生待核案例，不直接升规则；通过应用接口写派生知识库。"""
    cid = case_id(event, day)
    now = dt.datetime.now().isoformat(timespec="seconds")
    sid = "live_v2:" + day
    source = {"source_id": sid, "type": "live_v2", "uri": f"results/_live/{day}/live_v2/decisions.jsonl#{cid}",
              "source_time": now, "ingest_time": now, "parser_version": "live-v2-1", "quality_status": "ok"}
    validate_source_manifest(source)
    conf = decision["confidence"] if isinstance(decision["confidence"], dict) else {"raw": str(decision["confidence"])}
    case = {"case_id": cid, "subject": event["code"], "context_id": pack["context"]["context_id"],
            "issued_at": now, "available_at": now, "target_start": day, "target_end": None,
            "hypothesis": decision["stance"] + "；失效：" + decision["invalid_if"],
            "action": {"text": decision["action"], "signal": event, "mechanical_only": True},
            "outcome": {}, "label": "待核", "confidence": conf,
            "epistemic": candidate(source="model", as_of=now, evidence=[cid]), "review_state": "candidate", "source_id": sid}
    validate_case(case)
    store.upsert("source_manifest", source, "source_id")
    store.upsert("case_record", case, "case_id")
    store.link(cid, "context", case["context_id"])
    link_analogs(store, pack, cid, event)
    out = Path(out_dir) / "decisions.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"case_id": cid, "event": event, "context_id": case["context_id"], "decision": decision}, ensure_ascii=False) + "\n")
    return case


def process_event(store, event, day, out_dir, execute=False, session=None):
    try:
        pack = event_pack(store, event, day)
    except ContextPending as e:
        pending = {"executed": False, "status": "pending_context", "missing": ["deterministic_context"],
                   "event": event, "reason": str(e)}
        if execute:   # 只登记待核销，不调用模型、不写假 context/case
            out = Path(out_dir) / "pending_context.jsonl"
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(pending, ensure_ascii=False) + "\n")
        return pending
    prompt = prompt_for(pack, day)
    if not execute:
        return {"executed": False, "pack": pack, "prompt": prompt}
    ses = session or V2Session(day, out_dir)
    result = ses.ask(prompt, event["sig"])
    case = record_result(store, pack, event, result.parsed, day, out_dir)
    return {"executed": True, "case": case, "decision": result.parsed,
            "cost_usd": ses.st["turns"][-1]["usd"], "session_id": ses.st["sid"]}


def start_worker(day, out_dir, session=None, cooldown_s=180, store_path=None):
    """原 signals.py 的后台单队列消费者；返回 (queue, thread)，None 为停止哨兵。"""
    q = queue.Queue()
    out_dir = Path(out_dir)

    def work():
        store = KnowledgeStore(store_path or ROOT / "downloads" / "ontology" / "ontology.db")
        ses = session or V2Session(day, out_dir)
        last = {}
        try:
            while True:
                event = q.get()
                try:
                    if event is None:
                        return
                    now = time.monotonic()
                    if now - last.get(event["code"], -1e9) < cooldown_s:
                        continue
                    last[event["code"]] = now
                    process_event(store, event, day, out_dir, execute=True, session=ses)
                except Exception as e:  # 单条失败不拖垮机械 signal；错误落盘，不自动反复回炉
                    out_dir.mkdir(parents=True, exist_ok=True)
                    with (out_dir / "errors.jsonl").open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "event": event,
                                            "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False) + "\n")
                finally:
                    q.task_done()
        finally:
            store.close()

    thread = threading.Thread(target=work, name=f"live-v2-{day}", daemon=True)
    thread.start()
    return q, thread


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--event-json", required=True, help="signals.py 单条事件的 JSON")
    ap.add_argument("--execute", action="store_true", help="明确批准后才加；默认只生成事件包和 prompt，不调用模型")
    ap.add_argument("--print-prompt", action="store_true")
    a = ap.parse_args()
    event = json.loads(a.event_json)
    out = ROOT / "results" / "_live" / a.date / "live_v2"
    store = KnowledgeStore(ROOT / "downloads" / "ontology" / "ontology.db")
    try:
        r = process_event(store, event, a.date, out, execute=a.execute)
    finally:
        store.close()
    if not a.print_prompt:
        r.pop("prompt", None)
        r.pop("pack", None)
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
