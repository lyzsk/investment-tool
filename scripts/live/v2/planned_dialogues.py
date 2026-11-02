# -*- coding: utf-8 -*-
"""持久化预设对话：空预设不跑；按时间唤醒，成功/失败均留痕，CLI重启不丢。"""
import argparse
import datetime as dt
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "knowledge"), str(ROOT / "scripts" / "live" / "v2"), str(ROOT / "scripts" / "hermes")]
from store import KnowledgeStore  # noqa: E402
from mentor_consult import build_pack, consult, stage_for  # noqa: E402
from full_chain import full_slow  # noqa: E402
from linkage import build as build_linkage  # noqa: E402
from freshness import live02  # noqa: E402
from context_pack import get_context_pack  # noqa: E402

CONFIG = json.loads((Path(__file__).parent / "planned_dialogues.json").read_text(encoding="utf-8"))
STATE = ROOT / "results" / "_live" / "planned_state.json"


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"attempts": {}}


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def builder_for(store, task, day, at):
    def build(_store, skill, code, question, _day, _at):
        if task["code"] == "AUTO":
            from market_pack import build as build_market
            return build_market(_store, skill, question, _day, _at)
        pack = build_pack(_store, skill, code, question, _day, _at)
        comparisons = []
        for c in task.get("compare_codes") or []:
            comparisons.append({"code": c, "knowledge": get_context_pack(_store, c, f"{_day}T{_at}", purpose="chain04", budget="small"),
                                "linkage": build_linkage(c, _day), "live02": live02(c, _day, _at)})
        pack["comparisons"] = comparisons
        return pack
    return build


def push_result(task, result, stage):
    import wx_send
    d = result.get("decision") or {}
    text = (f"预设 {task['id']} {stage}\n{task['skill']} {task['code']}\n"
            f"方向:{d.get('stance', result.get('status'))}\n操作:{d.get('action', '')}\n"
            f"置信:{(d.get('confidence') or {}).get('raw', '候选')}\n失效:{d.get('invalid_if', '')}\n下一查:{d.get('next_check', '')}")
    return wx_send.send(text, src=f"planned_{task['id']}", raw=True, wait=120)


def run_task(store, task, day, at, execute):
    if not execute:
        return {"id": task["id"], "executed": False, "status": "planned"}
    out = ROOT / "results" / "_live" / day / "consult"
    builder = builder_for(store, task, day, at)
    stage = stage_for(at)
    fast = consult(store, task["skill"], task["code"], task["question"], day, at, out, "fast", True,
                   pack_builder=builder, timeout_s=120, effort="low")
    if task.get("push"):
        push_result(task, fast, "fast")
    slow = full_slow(store, task["skill"], task["code"], task["question"], day, at, out, pack_builder=builder)
    if task.get("push"):
        push_result(task, slow, "slow_full")
    return {"id": task["id"], "executed": True, "fast": fast, "slow": slow}


def run_due(now, execute=False):
    day, at = now.date().isoformat(), now.strftime("%H:%M:%S")
    state = load_state()
    done = []
    if at >= CONFIG["prepare"]["time"]:
        plan = ROOT / "results" / "_live" / day / "session_plan.json"
        if not plan.exists():
            plan.parent.mkdir(parents=True, exist_ok=True)
            plan.write_text(json.dumps({"date": day, "prepared_at": now.isoformat(timespec="seconds"),
                                        "mentor_sessions": {t["skill"]: str(uuid.uuid5(uuid.NAMESPACE_URL, f"{day}:{t['skill']}")) for t in CONFIG["tasks"]}}, ensure_ascii=False, indent=1), encoding="utf-8")
    for task in CONFIG["tasks"]:
        key = f"{day}:{task['id']}"
        if not task.get("enabled") or at < task["time"] or key in state["attempts"]:
            continue
        state["attempts"][key] = {"at": now.isoformat(timespec="seconds"), "status": "started" if execute else "dry"}
        if execute:
            save_state(state)  # 先占住，防CLI重启/下一分钟重复烧token
        try:
            store = KnowledgeStore(ROOT / "downloads" / "ontology" / "ontology.db")
            try:
                result = run_task(store, task, day, at, execute)
            finally:
                store.close()
            state["attempts"][key]["status"] = "ok" if execute else "dry"
            done.append(result)
        except Exception as e:  # 不反复回炉；错误保留，人工决定是否重跑
            state["attempts"][key].update(status="failed", error=f"{type(e).__name__}: {e}")
            done.append({"id": task["id"], "executed": False, "status": "failed", "error": str(e)})
        if execute:
            save_state(state)
    return done


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", help="测试用 YYYY-MM-DDTHH:MM:SS")
    ap.add_argument("--execute", action="store_true")
    a = ap.parse_args()
    now = dt.datetime.fromisoformat(a.now) if a.now else dt.datetime.now()
    print(json.dumps(run_due(now, a.execute), ensure_ascii=False, indent=1))
