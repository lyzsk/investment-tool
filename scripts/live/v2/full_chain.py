# -*- coding: utf-8 -*-
"""slow_full：从fast之前的01+02会话分叉，独立03→04→06；05机械执行。"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "knowledge"), str(Path(__file__).resolve().parent)]
from mentor_consult import (CONFIG, SCHEMA, build_pack, consult_id, normalized_result, prompt_fast, record_consult)  # noqa: E402
from session import V2Session, NO_TOOLS  # noqa: E402
from store import KnowledgeStore  # noqa: E402
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import claude_call as CC  # noqa: E402

BASE_SCHEMA = {"type": "object", "required": ["status"], "properties": {"status": {"type": "string"}}}


def new_session(day, out, skill, schema=SCHEMA, call_fn=None):
    return V2Session(day, out, call_fn=call_fn or CC.call, system=(f"你只模拟用户点名的 {skill}，不混入其他导师人格。输出是候选系统BS，不是导师真人BS，不自动交易。"
                                      "01/02共享后，slow从fast前分叉独立03→04→06。公共知识只按认识论标记引用，额外数据只允许./q。"),
                     tag=f"consult-{skill}-full", schema=schema,
                     allowed_tools=["Bash(./q:*)"], disallowed_tools=[x for x in NO_TOOLS if x != "Bash"])


def robust_ask(session, prompt, sig, timeout_s, effort):
    try:
        return session.ask(prompt, sig, timeout_s=timeout_s, effort=effort)
    except RuntimeError:
        if getattr(session.last_result, "parsed", None):
            return normalized_result(session.last_result)
        result = session.ask("只把上一答整理成完整JSON代码块，不新增分析、不调用工具。", f"format-{sig}", timeout_s=timeout_s, effort=effort)
        return normalized_result(result) if not result.ok else result


def full_slow(store, skill, code, question, day, at, out_root, pack_builder=None, timeout_s=None, effort=None, call_fn=None):
    out_root = Path(out_root)
    cid = consult_id(day, skill, code, question)
    out_dir = out_root / skill / cid
    timeout_s = timeout_s or CONFIG["slow"]["timeout_s"]
    effort = effort or CONFIG["slow"]["effort"]
    try:
        pack = json.loads((out_dir / "pack.json").read_text(encoding="utf-8"))
        base_state = json.loads((out_root / "skill" / "session.json").read_text(encoding="utf-8"))
    except OSError:
        pack = (pack_builder or build_pack)(store, skill, code, question, day, at)
        base_ses = new_session(day, out_root / "skill", skill, BASE_SCHEMA, call_fn=call_fn)
        base_prompt = "只建立01+02共享上下文，不分析、不调用工具。输出JSON代码块 {\"status\":\"ok\"}。\n" + prompt_fast(pack)
        robust_ask(base_ses, base_prompt, "base", CONFIG["fast"]["timeout_s"], CONFIG["fast"]["effort"])
        base_state = base_ses.st
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "pack.json").write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
    ses = new_session(day, out_dir / "slow", skill, call_fn=call_fn)
    prompts = [
        ("slow03", "独立03：此分支从fast之前分叉，不知道也不采用fast结论。对当前标的和指定skill做最强多方/空方、反例、skill适用性审查；输出完整JSON，action写‘交04独立重评’。"),
        ("slow04", "独立04：只根据03和共享01+02，给最多3个方向，明确主选/备选、证据、置信、失效条件；输出完整JSON。"),
        ("slow06", "独立06：根据04形成操作版本。需要操作时给明确orders(side/price/qty/op/why)，05由代码做G1~G7，不自动成交；输出完整JSON。"),
    ]
    results, total = {}, 0.0
    for stage, instruction in prompts:
        if stage == "slow03":
            r = robust_ask(ses, instruction, stage, timeout_s, effort) if ses.st.get("sid") else ses.ask(
                instruction, stage, timeout_s=timeout_s, effort=effort, fork_from=base_state["sid"], parent_cost=base_state.get("cost_cum") or 0.0)
        else:
            r = robust_ask(ses, instruction, stage, timeout_s, effort)
        results[stage] = r.parsed
        cost = ses.st["turns"][-1]["usd"]
        total += cost
        record_consult(store, pack, r.parsed, stage, cid, out_dir, cost)
    (out_dir / "slow.json").write_text(json.dumps({"case": json.loads((out_dir / "slow06.json").read_text(encoding="utf-8"))["case"],
                                                   "decision": results["slow06"], "cost_usd": total}, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"executed": True, "status": "ok", "stage": "slow_full", "consult_id": cid,
            "session_id": ses.st["sid"], "forked_from": base_state["sid"], "cost_usd": total,
            "decision": results["slow06"], "stages": results}
