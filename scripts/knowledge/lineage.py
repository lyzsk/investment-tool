# -*- coding: utf-8 -*-
"""规则/案例血缘：证据→规则版本→关系；不让关系只停留在模型文本里。"""
from schema import validate_rule


def rule_key(rule):
    return f"rule:{rule['owner']}:{rule['id']}:v{rule['version']}"


def put_rule(store, rule, evidence_case_ids):
    key = rule_key(rule)
    validate_rule(rule)
    store.upsert("rule", rule, "id,owner,version")
    store.link(key, "context", rule["context_id"])
    for cid in evidence_case_ids:
        store.link(cid, "supports", key)
    for rel in rule["relations"]:
        store.link(key, rel["type"], rel["target"])
    return key


def dimension_match(current, other):
    """受控维度的相同/差异；相似不是同形证明，无 dimensions 就明确未知。"""
    if not current or not other:
        return {"shared": [], "different": ["dimensions_unknown"], "score": None}
    shared, different = [], []
    for key in ("cycle_stage", "position", "auction", "pattern"):
        if current.get(key) in (None, "无数据") or other.get(key) in (None, "无数据"):
            different.append(key + ":unknown")
        elif current.get(key) == other.get(key):
            shared.append(key)
        else:
            different.append(key)
    if set(current.get("theme") or []) & set(other.get("theme") or []):
        shared.append("theme")
    else:
        different.append("theme")
    cz, oz = current.get("zibei") or {}, other.get("zibei") or {}
    if set(cz) & set(oz):
        if all(cz[k] == oz[k] for k in set(cz) & set(oz)):
            shared.append("zibei")
        else:
            different.append("zibei_stage")
    known = len(shared) + len([x for x in different if not x.endswith(":unknown")])
    return {"shared": shared, "different": different, "score": round(len(shared) / known, 4) if known else None}


def link_analogs(store, pack, dest, event=None):
    """当前事实=observed；历史/相似案例=analog。没有合适案例时允许为空，不强行造证据。"""
    if event:
        eid = f"signal:{event.get('replay_of') or pack.get('at', '')[:10]}:{event['code']}:{event['sig']}:{event['t']}"
        store.link(eid, "observed", dest, {"px": event.get("px"), "detail": event.get("detail"), "mode": event.get("mode")})
    current = (pack.get("context") or {}).get("dimensions") or {}
    out = []
    for case in pack.get("cases") or pack.get("evidence") or []:
        ctx = store.get("context_snapshot", "context_id", case.get("context_id"))
        match = dimension_match(current, (ctx or {}).get("dimensions"))
        if ctx and case.get("issued_at", "")[:10] and case["issued_at"][:10] != str(ctx.get("as_of", ""))[:10]:
            match = {"shared": ["subject"] if case.get("subject") == pack.get("code") else [],
                     "different": ["context_time"], "score": None, "note": "案例关联的是核销情境，不是预测发出时同情境"}
        store.link(case["case_id"], "analog", dest, {**match, "note": "相似情境证据，不是一模一样的前例或直接证明"})
        out.append(case["case_id"])
        for member in (case.get("action") or {}).get("member_ids") or []:
            store.link(member, "aggregated", case["case_id"], {"independent_n": 1})
    return out

def explain_rule(store, owner, rule_id, version=1):
    key = f"rule:{owner}:{rule_id}:v{version}"
    rule = next((r for r in store.all("rule") if r["owner"] == owner and r["id"] == rule_id and r["version"] == version), None)
    incoming = store.links(dst=key)
    outgoing = store.links(src=key)
    case_ids = [x["src"] for x in incoming if x["rel"] == "supports"]
    cases = [c for cid in case_ids if (c := store.get("case_record", "case_id", cid))]
    return {"rule_key": key, "rule": rule, "evidence_cases": cases, "incoming": incoming, "outgoing": outgoing,
            "chain": ["source_manifest", "context_snapshot.dimensions", "case_record.epistemic", key, "context_pack", "outcome"]}
