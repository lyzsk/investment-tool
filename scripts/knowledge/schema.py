# -*- coding: utf-8 -*-
"""知识底座 v1 的数据契约；只校验结构，不调用模型。"""
from dimensions import validate_dimensions
from epistemics import citable, validate_epistemic

CONTRACT_VERSION = "1.1"
QUALITY = {"ok", "degraded", "failed"}
LABELS = {"正", "负", "平", "待核"}
REVIEW = {"candidate", "active", "watch", "rejected", "restructured"}
RELATIONS = {"supports", "refines", "conflicts", "restructures"}


def _required(obj, keys, path):
    missing = [k for k in keys if k not in obj]
    if missing:
        raise ValueError(f"{path} 缺字段: {missing}")


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def validate_source_manifest(m):
    _required(m, ("source_id", "type", "uri", "source_time", "ingest_time", "parser_version", "quality_status"), "source_manifest")
    if m["quality_status"] not in QUALITY:
        raise ValueError(f"quality_status 非法: {m['quality_status']}")
    for k in ("source_id", "type", "uri", "source_time", "ingest_time", "parser_version"):
        if not _text(m[k]):
            raise ValueError(f"source_manifest.{k} 不能为空")
    return True


def validate_context(c):
    _required(c, ("context_id", "subject", "as_of", "available_at", "market", "theme", "instrument", "dimensions", "evidence"), "context_snapshot")
    if not _text(c["available_at"]) or not _text(c["as_of"]):
        raise ValueError("context_snapshot 时间不能为空")
    if c["available_at"] > c["as_of"]:
        raise ValueError("available_at 不能晚于 as_of")
    if not isinstance(c["evidence"], list) or not c["evidence"]:
        raise ValueError("context_snapshot.evidence 必须是非空列表")
    validate_dimensions(c["dimensions"])
    return True


def validate_case(c):
    _required(c, ("case_id", "subject", "context_id", "issued_at", "available_at", "hypothesis", "action", "outcome", "label", "confidence", "epistemic", "review_state", "source_id"), "case")
    if c["label"] not in LABELS:
        raise ValueError(f"case.label 非法: {c['label']}")
    if c["review_state"] not in REVIEW:
        raise ValueError(f"case.review_state 非法: {c['review_state']}")
    if not _text(c["issued_at"]) or not _text(c["available_at"]):
        raise ValueError("case 的 issued_at/available_at 不能为空")
    if c["available_at"] < c["issued_at"]:
        raise ValueError("available_at 不能早于 issued_at")
    for k in ("target_start", "target_end"):
        if c.get(k) is not None and not isinstance(c[k], str):
            raise ValueError(f"case.{k} 必须是字符串")
    if c.get("target_start") and c.get("target_end") and c["target_end"] < c["target_start"]:
        raise ValueError("target_end 不能早于 target_start")
    validate_epistemic(c["epistemic"])
    return True


def validate_rule(r):
    _required(r, ("id", "owner", "version", "context_id", "trigger", "action", "evidence", "relations", "confidence", "epistemic", "review"), "rule")
    if not isinstance(r["evidence"], list) or not r["evidence"]:
        raise ValueError("rule.evidence 必须是非空列表")
    if not isinstance(r["relations"], list):
        raise ValueError("rule.relations 必须是列表")
    for rel in r["relations"]:
        if rel.get("type") not in RELATIONS:
            raise ValueError(f"relation.type 非法: {rel.get('type')}")
        if not _text(rel.get("target", "")):
            raise ValueError("relation.target 不能为空")
    if not isinstance(r["review"], dict) or r["review"].get("state") not in REVIEW:
        raise ValueError("rule.review.state 非法")
    validate_epistemic(r["epistemic"])
    if r["review"].get("state") == "active" and not citable(r):
        raise ValueError("active 规则必须机械已核销(n,hit_rate)；候选/纯先验不得激活引用")
    return True


def validate_pack(p):
    _required(p, ("contract_version", "subject", "at", "context", "cases", "rules", "belief_state", "sources", "missing", "forecast"), "context_pack")
    if p["contract_version"] != CONTRACT_VERSION:
        raise ValueError("context_pack 契约版本不兼容")
    if not isinstance(p["missing"], list):
        raise ValueError("context_pack.missing 必须是列表")
    validate_context(p["context"])
    for c in p["cases"]:
        validate_case(c)
    for r in p["rules"]:
        validate_rule(r)
    return True
