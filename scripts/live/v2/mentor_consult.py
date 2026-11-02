# -*- coding: utf-8 -*-
"""按需问 xxx-skill：机械01+指定人格+公共情境；fast/slow同会话，只记录不自动交易。"""
import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "chain"), str(ROOT / "scripts" / "knowledge"), str(Path(__file__).resolve().parent)]
import chain_steps as CS  # noqa: E402
sys.path.insert(0, str(ROOT / "scripts" / "paper_line"))
import pack as PaperPack  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))  # paper_line/session.py 与 v2/session.py 同名，v2优先
from context_pack import get_context_pack, ContextPending  # noqa: E402
from decision_pack import focus01, retrieve, retrieve_deferred  # noqa: E402
from confidence import assess, clamp  # noqa: E402
from market_state import current as market_current  # noqa: E402
from decision_windows import evaluate as evaluate_windows  # noqa: E402
from freshness import current_book, live02, seconds as clock_seconds  # noqa: E402
from linkage import build as build_linkage  # noqa: E402
from epistemics import candidate  # noqa: E402
from lineage import link_analogs  # noqa: E402
from schema import validate_case, validate_source_manifest  # noqa: E402
from session import V2Session, NO_TOOLS  # noqa: E402
from store import KnowledgeStore  # noqa: E402
sys.path.insert(0, str(ROOT / "scripts" / "dfcf" / "snapshots" / "order-skill"))
import rule_gate as RG  # noqa: E402
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import claude_call as CC  # noqa: E402

SCHEMA = {
    "type": "object",
    "required": ["stance", "action", "evidence", "confidence", "invalid_if", "next_check"],
    "properties": {
        "stance": {"type": "string"},
        "action": {"type": "string"},
        "evidence": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "confidence": {"type": "object", "required": ["raw"], "properties": {"raw": {"type": "string"}, "n": {"type": "integer"}, "reason": {"type": "string"}}},
        "invalid_if": {"type": "string"},
        "next_check": {"type": "string"},
        "choices": {"type": "array", "maxItems": 3},
        "rules": {"type": "array"},
        "changes": {"type": "array"},
        "orders": {"type": "array", "items": {"type": "object", "required": ["side", "price"],
                   "properties": {"side": {"type": "string", "enum": ["BUY", "SELL"]}, "price": {"type": "number"},
                                  "qty": {"type": "integer"}, "t": {"type": "string"}, "op": {"type": "string"},
                                  "why": {"type": "string"}, "code": {"type": "string"}}}}
    }
}


CONFIG = json.loads((Path(__file__).parent / "consult_config.json").read_text(encoding="utf-8"))


def stage_for(at):
    for w in CONFIG["windows"]:
        if w["start"] <= at < w["end"]:
            return w["stage"]
    return CONFIG["default_stage"]


def consult_id(day, skill, code, question):
    return hashlib.sha1(f"{day}|{skill}|{code}|{question}".encode("utf-8")).hexdigest()[:16]


def account_start(day):
    start = PaperPack.real_start(day)
    if start:
        start["positions"] = {c: {**p, "sellable": p["qty"]} for c, p in start["positions"].items()}
    return start


def fact01(skill, code, day, at):
    start = account_start(day)
    state = start or {"cash": 0, "positions": {}, "trades": []}
    state["trades"] = []
    strategy = {"codes": [{"code": code, "rules": []}]}
    text, _, _, _ = CS.build_01(skill, day, at, "按需导师咨询，不执行交易", state, strategy, [], {}, "", "按需咨询，无挂单", None, live=False)
    return focus01(text, code)


def build_pack(store, skill, code, question, day, at, fact_builder=None, persona_builder=None, retrieval_builder=None):
    knowledge = get_context_pack(store, code, f"{day}T{at}", purpose="chain04", budget="small")
    names = CS.names(day)
    f01 = (fact_builder or fact01)(skill, code, day, at)
    stable, var, info = (persona_builder or CS.persona)(skill, [], [names.get(code) or code], [code])
    pattern = knowledge["context"]["dimensions"]["pattern"]
    retrieval = (retrieval_builder or retrieve)(skill, code, names.get(code) or code, day, at, pattern)
    confidence_assessment = assess(n=0, coverage_ok=not retrieval["missing"])
    state = market_current(store, code, day, at)
    windows = evaluate_windows(state)
    account = account_start(day)
    return {"contract_version": "1.1", "mode": "on_demand_mentor_consult", "skill": skill, "code": code,
            "name": names.get(code) or code, "question": question, "at": f"{day}T{at}",
            "account_mode": "real_start_excluding_601988" if account else "no_account_no_order", "account": account,
            "facts01": f01, "linkage_4d": build_linkage(code, day), "persona_stable": stable, "persona_on_demand": var, "persona_info": info, "knowledge": knowledge,
            "market_state": {k: v for k, v in state.items() if k != "pack"}, "live02": live02(code, day, at), "decision_windows": windows,
            "retrieval": retrieval, "confidence_assessment": confidence_assessment}


def prompt_fast(pack):
    body = json.dumps(pack, ensure_ascii=False)
    return (f"[BOOT mentor-consult {pack['at']} {pack['skill']}]\n用户问：{pack['question']}\n"
            "只按指定导师画像回答他/她在当前情境可能怎么做，给少量选择(最多3个)，不要替用户自动选择或成交。"
            "01事实、导师规则/案例、公共 verified 证据分层引用；相似案例必须写差异，不要求一模一样。"
            "必要查询已由代码执行并附 retrieval；缺失项必须明说。需要额外数据只能用 ./q 的只读命名查询，不得凭感觉补。"
            "置信度不得超过 confidence_assessment.cap；只能降档。"
            "快版先给可执行观察方向，但必须有 stance/action/evidence/confidence/invalid_if/next_check；可带 choices/rules。\n"
            f"```json\n{body}\n```")


def prompt_slow(pack, fast):
    return ("复核上一轮快版，不重复全文：①主动找反例和最强反方 ②逐条核销 fast 引用的规则/案例是否同情境，写 shared/different "
            "③检查是否把候选/纯先验当成已核销 ④检查是否把系统BS当成导师真人BS ⑤给出修订和失效条件。"
            "仍只记录候选，不自动交易。输出完整修订 JSON，并增加 changes 数组。\n"
            f"用户问题：{pack['question']}\n快版：\n```json\n{json.dumps(fast, ensure_ascii=False)}\n```")


def normalize_decision(obj):
    """只修类型，不补内容；缺 stance/action 等仍由schema拒绝。"""
    d = dict(obj or {})
    if isinstance(d.get("evidence"), dict):
        d["evidence"] = [f"{k}: {v}" for k, v in d["evidence"].items()]
    elif isinstance(d.get("evidence"), list):
        d["evidence"] = [x if isinstance(x, str) else json.dumps(x, ensure_ascii=False) for x in d["evidence"]]
    elif isinstance(d.get("evidence"), str):
        d["evidence"] = [d["evidence"]]
    if isinstance(d.get("confidence"), str):
        d["confidence"] = {"raw": d["confidence"], "reason": "模型原文"}
    elif isinstance(d.get("confidence"), dict) and "raw" not in d["confidence"]:
        for key in ("value", "level", "cap"):
            if d["confidence"].get(key) is not None:
                d["confidence"]["raw"] = str(d["confidence"][key])
                break
    for key in ("stance", "action", "invalid_if", "next_check"):
        if not isinstance(d.get(key), str):
            d[key] = json.dumps(d.get(key), ensure_ascii=False)
    return d


def normalized_result(result):
    obj = normalize_decision(getattr(result, "parsed", None))
    errors = CC.validate(obj, SCHEMA)
    if errors:
        raise RuntimeError(f"格式归一化仍失败: {errors}")
    result.parsed = obj
    result.ok = True
    result.errors = []
    return result


def validate_orders(pack, decision):
    """06建议单：复用原G1~G7；无账户/缺数量/错误价格不得冒充可执行单。"""
    d = dict(decision or {})
    orders = d.get("orders") or []
    if not orders:
        d["order_gate"] = {"accepted": 0, "rejected": [], "warnings": []}
        return d
    accepted, rejected, warnings = [], [], []
    account = pack.get("account")
    for o in orders:
        if not account or not o.get("qty") or not o.get("price"):
            rejected.append({"order": o, "errors": ["账户快照缺失" if not account else "缺价格或数量"]})
            continue
        code = o.get("code") or pack["code"]
        pos = (account.get("positions") or {}).get(code) or {}
        cost = pos.get("cost")
        st = {"base": pos.get("qty") or 0, "avail": pos.get("sellable"), "cash": account.get("cash"), "orders": [],
              "fills": {"B": {"qty": 0, "avg": cost}, "S": {"qty": 0, "avg": 0}}, "hold_used": 0, "target": 0}
        prev = ((pack.get("knowledge") or {}).get("context", {}).get("instrument", {}).get("day") or {}).get("preClose")
        book = current_book(code, pack["at"][:10], pack["at"][11:19])
        fresh = bool(book and 0 <= clock_seconds(pack["at"][11:19]) - clock_seconds(book["t"]) <= 15)
        errors, warns = RG.check([("B" if o["side"] == "BUY" else "S", float(o["price"]), int(o["qty"]))], st, book if fresh else None, pack["at"][:10], code, prev_close=prev)
        if not prev:
            warns.append("G4 缺昨收，未校验涨跌停")
        if not fresh:
            warnings.append("G5 无15秒内对手方盘口，未按最新盘口校验价格笼子")
        d["freshness"] = {"book_t": (book or {}).get("t"), "fresh_3s_book": fresh}
        if errors:
            rejected.append({"order": o, "errors": errors})
        else:
            accepted.append(o)
            warnings.extend(warns)
    d["orders"] = accepted
    d["order_gate"] = {"accepted": len(accepted), "rejected": rejected, "warnings": list(dict.fromkeys(warnings))}
    return d


def record_consult(store, pack, decision, stage, cid, out_dir, cost_usd):
    decision = dict(decision)
    decision["confidence"] = clamp(decision.get("confidence"), pack.get("confidence_assessment") or assess(n=0))
    decision = validate_orders(pack, decision)
    now = dt.datetime.now().isoformat(timespec="seconds")
    case_id = f"consult:{cid}:{stage}"
    source_id = f"consult:{pack['at'][:10]}:{pack['skill']}"
    source = {"source_id": source_id, "type": "mentor_consult", "uri": str(Path(out_dir) / f"{stage}.json"),
              "source_time": now, "ingest_time": now, "parser_version": "consult-1", "quality_status": "ok"}
    validate_source_manifest(source)
    case = {"case_id": case_id, "subject": pack["code"], "context_id": pack["knowledge"]["context"]["context_id"],
            "issued_at": now, "available_at": now, "target_start": pack["at"][:10], "target_end": None,
            "hypothesis": decision["stance"], "action": {"text": decision["action"], "skill": pack["skill"], "stage": stage,
                                                         "orders": decision.get("orders") or [], "order_gate": decision.get("order_gate"), "system_bs": True, "mentor_real_bs": False, "auto_execute": False},
            "outcome": {}, "label": "待核", "confidence": decision["confidence"],
            "epistemic": candidate(source="mentor_consult", as_of=now, evidence=[case_id]), "review_state": "candidate", "source_id": source_id}
    validate_case(case)
    store.upsert("source_manifest", source, "source_id")
    store.upsert("case_record", case, "case_id")
    store.link(case_id, "context", case["context_id"])
    store.link(f"facts01:{pack['at']}:{pack['code']}", "observed", case_id, {"builder": "chain_steps.build_01"})
    link_analogs(store, pack["knowledge"], case_id)
    out = Path(out_dir) / f"{stage}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"case": case, "decision": decision, "cost_usd": cost_usd}, ensure_ascii=False, indent=1), encoding="utf-8")
    return case


def consult(store, skill, code, question, day, at, out_root, stage="fast", execute=False, session=None, pack_builder=None,
            timeout_s=None, effort=None):
    cid = consult_id(day, skill, code, question)
    out_dir = Path(out_root) / skill / cid
    if stage == "slow":
        try:
            pack = json.loads((out_dir / "pack.json").read_text(encoding="utf-8"))
            fast = json.loads((out_dir / "fast.json").read_text(encoding="utf-8"))["decision"]
            prompt = prompt_slow(pack, fast)
        except OSError:
            pack = (pack_builder or build_pack)(store, skill, code, question, day, at)
            prompt = prompt_fast(pack) + "\n本次是slow独立深审：直接完成反例、shared/different和失效条件复核，不另出快版。"
        retrieve_deferred(pack)
    else:
        try:
            pack = (pack_builder or build_pack)(store, skill, code, question, day, at)
        except ContextPending as e:
            return {"executed": False, "status": "pending_context", "consult_id": cid, "reason": str(e)}
        prompt = prompt_fast(pack)
    if not execute:
        return {"executed": False, "status": "dry", "consult_id": cid, "pack": pack, "prompt": prompt}
    ses = session or V2Session(day, Path(out_root) / skill, system=(f"你只模拟用户点名的 {skill}，不混入其他导师人格。"
                                      "输出是候选系统BS，不是导师真人BS，不自动交易。公共知识只按材料里的认识论标记引用。"
                                      "必要数据必须先查；额外数据只允许 ./q 只读查询；置信度只能低于或等于机械上限。"),
                               tag=f"consult-{skill}", schema=SCHEMA,
                               allowed_tools=["Bash(./q:*)"], disallowed_tools=[x for x in NO_TOOLS if x != "Bash"])
    cost0 = sum(x.get("usd") or 0 for x in ses.st.get("turns") or [])
    try:
        result = ses.ask(prompt, f"{stage}-{code}", timeout_s=timeout_s, effort=effort)
    except RuntimeError as e:
        recovered = None
        if getattr(ses.last_result, "parsed", None):
            try:
                recovered = normalized_result(ses.last_result)
            except RuntimeError:
                pass
        if recovered is not None:
            result = recovered
        else:
            if "json" not in str(e).lower():
                raise
            try:
                result = ses.ask("只把上一答原样整理成一个 ```json 代码块，字段必须完整；不要新增分析，不要调用工具。", f"format-fix-{stage}", timeout_s=timeout_s, effort=effort)
            except RuntimeError:
                result = normalized_result(ses.last_result)
    if stage == "fast":
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "pack.json").write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
    cost_usd = sum(x.get("usd") or 0 for x in ses.st.get("turns") or []) - cost0
    case = record_consult(store, pack, result.parsed, stage, cid, out_dir, cost_usd)
    return {"executed": True, "status": "ok", "consult_id": cid, "case_id": case["case_id"],
            "session_id": ses.st["sid"], "cost_usd": cost_usd, "decision": result.parsed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--code", required=True)
    ap.add_argument("--question", required=True)
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--at", default=dt.datetime.now().strftime("%H:%M:%S"))
    ap.add_argument("--stage", choices=["auto", "fast", "slow"], default="auto")
    ap.add_argument("--execute", action="store_true")
    a = ap.parse_args()
    if not (ROOT / "skills" / f"{a.skill}-skill" / "SKILL.md").exists():
        raise ValueError(f"未知 skill: {a.skill}")
    stage = a.stage if a.stage != "auto" else stage_for(a.at)
    out = ROOT / "results" / "_live" / a.date / "consult"
    store = KnowledgeStore(ROOT / "downloads" / "ontology" / "ontology.db")
    try:
        if a.execute and stage == "fast_slow":
            from full_chain import full_slow
            try:
                fast_result = consult(store, a.skill, a.code, a.question, a.date, a.at, out, "fast", True,
                                      timeout_s=CONFIG["fast"]["timeout_s"], effort=CONFIG["fast"]["effort"])
            except RuntimeError as e:
                fast_result = {"executed": False, "status": "failed", "error": str(e)}
            print(json.dumps({"stage": "fast", "result": fast_result}, ensure_ascii=False, indent=1), flush=True)
            slow_result = full_slow(store, a.skill, a.code, a.question, a.date, a.at, out,
                                    timeout_s=CONFIG["slow"]["timeout_s"], effort=CONFIG["slow"]["effort"])
            print(json.dumps({"stage": "slow", "result": slow_result}, ensure_ascii=False, indent=1), flush=True)
            return
        else:
            one_stage = "fast" if stage == "fast_slow" else stage
            cfg = CONFIG[one_stage]
            if a.execute and one_stage == "slow":
                from full_chain import full_slow
                r = full_slow(store, a.skill, a.code, a.question, a.date, a.at, out,
                              timeout_s=cfg["timeout_s"], effort=cfg["effort"])
            else:
                r = consult(store, a.skill, a.code, a.question, a.date, a.at, out, one_stage, a.execute,
                            timeout_s=cfg["timeout_s"], effort=cfg["effort"])
            r["planned_stage"] = stage
    finally:
        store.close()
    r.pop("pack", None)
    r.pop("prompt", None)
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
