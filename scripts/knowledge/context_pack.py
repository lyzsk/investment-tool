# -*- coding: utf-8 -*-
"""统一情境包：distill/live v2/viewer/主CLI共用；只读，零模型调用。"""
import json
import hashlib
import sqlite3
from pathlib import Path
from schema import CONTRACT_VERSION, validate_pack
from epistemics import citable, verified

ROOT = Path(__file__).resolve().parents[2]


class ContextPending(ValueError):
    """当时确定情境尚未生成/核销；禁止用后来数据或自由文本补齐。"""


def forecast_summary(code, at=None):
    f = ROOT / "results" / "forecast" / "ledger.db"
    if not f.exists():
        return {"n": 0, "hit": None, "baseline": None}
    c = sqlite3.connect(f)
    try:
        where, params = "code=? and late=0 and hit is not null", [code]
        if at:
            where += " and issued_at<=? and evaluated_at<=?"
            params += [at, at]
        n, hit, baseline = c.execute(f"select count(*),avg(group_hit),avg(group_baseline) from (select avg(hit) group_hit,avg(baseline_hit) group_baseline from predictions where {where} group by kind,context,predicted,date(issued_at),horizon)", params).fetchone()
        return {"n": n, "hit": hit, "baseline": baseline}
    finally:
        c.close()


def aggregate_citations(cases):
    """同票/同预测日/同票型/同方向的多次时间戳记录合并为一个机械核销证据组。"""
    groups = {}
    for c in cases:
        if c["case_id"].startswith("forecast:"):
            a = c.get("action") or {}
            key = (c["subject"], c["issued_at"][:10], a.get("kind"), a.get("context"), c["hypothesis"])
        else:
            key = ("raw", c["case_id"])
        groups.setdefault(key, []).append(c)
    out = []
    for key, rows in groups.items():
        rows.sort(key=lambda c: c["available_at"])
        if len(rows) == 1:
            out.append(rows[0])
            continue
        latest = rows[-1]
        ids = [c["case_id"] for c in rows]
        hits = sum(int(c["outcome"].get("hit") or 0) for c in rows)
        latest_hit = int(latest["outcome"].get("hit") or 0)
        raw = f"{key}|{','.join(ids)}"
        action = dict(latest.get("action") or {})
        action["member_ids"] = ids
        out.append({"case_id": "forecast_group:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16], "subject": latest["subject"],
                    "context_id": latest["context_id"], "issued_at": min(c["issued_at"] for c in rows), "available_at": max(c["available_at"] for c in rows),
                    "target_start": latest.get("target_start"), "target_end": latest.get("target_end"), "hypothesis": latest["hypothesis"], "action": action,
                    "outcome": {"n": 1, "runs": len(rows), "hits": hits, "latest_hit": latest_hit, "raw_hit_rate": hits / len(rows)},
                    "label": "正" if latest_hit else "负",
                    "confidence": {"raw": "已核销聚合", "basis": "同内容不同时间戳只算一次独立核销"},
                    "epistemic": verified(1, latest_hit, max(c["available_at"] for c in rows), ids), "review_state": "active", "source_id": latest["source_id"]})
    return out


def get_context_pack(store, subject, at, purpose="live", budget="small"):
    contexts = [c for c in store.all("context_snapshot") if c["subject"] == subject and c["available_at"] <= at]
    if not contexts:
        raise ContextPending(f"缺情境加待核销: {subject} @ {at}")
    context = sorted(contexts, key=lambda c: c["available_at"])[-1]
    all_cases = [c for c in store.all("case_record") if c["subject"] == subject and c["available_at"] <= at]
    citation_required = purpose in ("live", "signal", "order", "chain04", "chain06")
    if citation_required:
        context = dict(context)
        context["market"] = dict(context.get("market") or {})
        context["market"].pop("prior_cycle_note", None)   # 先验备注只供 distill/viewer，不得被决策引用
    cases = [c for c in all_cases if not citation_required or citable(c)]   # 无标记/候选/纯先验不得进入 04/06/live 引用
    if citation_required:
        cases = aggregate_citations(cases)
    cases.sort(key=lambda c: c["available_at"])
    if budget == "small" and purpose != "viewer":
        neg = [c for c in cases if c["label"] == "负"][-3:]
        pos = [c for c in cases if c["label"] == "正"][-2:]
        other = [c for c in cases if c["label"] not in ("正", "负")][-3:]
        cases = neg + pos + other
    rules = store.all("rule") if purpose in ("distill", "viewer") else [r for r in store.all("rule") if r["review"].get("state") == "active" and (not citation_required or citable(r))]
    belief = store.latest("belief_state", "as_of", at) or {"state": {}, "evidence": []}
    pack = {"contract_version": CONTRACT_VERSION, "subject": subject, "at": at, "context": context, "cases": cases,
            "rules": rules, "belief_state": belief, "sources": {s["source_id"]: s for s in store.all("source_manifest")},
            "missing": [] if cases else ["verified_case" if citation_required and all_cases else "case"], "forecast": forecast_summary(subject, at),
            "meta": {"purpose": purpose, "budget": budget, "evidence_ids": [c["case_id"] for c in cases],
                     "citation_gate": citation_required, "cases_before_gate": len(all_cases), "cases_after_gate": len(cases)}}
    validate_pack(pack)
    return pack


def optional_context_pack(store, subject, at, purpose="live", budget="small"):
    """缺失时返回空，不阻断旧流程；真实缺失会写 missing，不伪造情境。"""
    try:
        return get_context_pack(store, subject, at, purpose, budget)
    except ValueError:
        return None


def knowledge_section(store, subject, at):
    """给 distill 的公共情境小节；无情境时返回空串，保持旧素材包行为。"""
    pack = optional_context_pack(store, subject, at, purpose="distill", budget="small")
    if not pack:
        return ""
    body = {"context": pack["context"], "cases": pack["cases"], "belief_state": pack["belief_state"], "forecast": pack["forecast"]}
    return "## ⑥ 公共情境与跨skill证据（知识底座 v1）\n\n```json\n" + json.dumps(body, ensure_ascii=False, indent=1) + "\n```"


if __name__ == "__main__":
    import argparse
    from store import KnowledgeStore
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--at", required=True)
    ap.add_argument("--purpose", default="live")
    ap.add_argument("--budget", default="small")
    a = ap.parse_args()
    print(json.dumps(get_context_pack(KnowledgeStore(a.db), a.subject, a.at, a.purpose, a.budget), ensure_ascii=False, indent=1))
