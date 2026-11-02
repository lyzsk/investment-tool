# -*- coding: utf-8 -*-
"""用户复盘与已知市场事实入库：保留当时想法/结果边界，默认candidate。"""
from adapters import now, put_case, put_context
from epistemics import candidate


def user_review(store, case_id, subject, context_id, issued, hypothesis, action, outcome=None, source_id="user_review:2026-11-01"):
    rec = {"case_id": case_id, "subject": subject, "context_id": context_id, "issued_at": issued, "available_at": now(),
           "hypothesis": hypothesis, "action": action, "outcome": outcome or {}, "label": "待核",
           "confidence": {"basis": "用户复盘原话"}, "epistemic": candidate(source="user_review", as_of=now(), evidence=[case_id]),
           "review_state": "candidate", "source_id": source_id}
    put_case(store, rec)
    store.link(case_id, "context", context_id)
    return rec


def market_fact(store, case_id, subject, context_id, day, hypothesis, outcome):
    rec = {"case_id": case_id, "subject": subject, "context_id": context_id, "issued_at": f"{day}T15:00:00", "available_at": f"{day}T15:00:00",
           "hypothesis": hypothesis, "action": {"observed": True}, "outcome": outcome, "label": "待核",
           "confidence": {"basis": "真实行情"}, "epistemic": candidate(source="market_fact", as_of=f"{day}T15:00:00", evidence=[case_id]),
           "review_state": "candidate", "source_id": f"day:{day}"}
    put_case(store, rec)
    store.link(case_id, "context", context_id)
    return rec
