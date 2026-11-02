# -*- coding: utf-8 -*-
"""认识论标记与 04/06 引用硬闸：无已核销 n/hit_rate 的知识不得引用。"""
STATUSES = {"verified", "candidate", "prior"}


def epistemic(status="candidate", n=0, hit_rate=None, source="model", as_of="", evidence=None):
    return {"status": status, "n": int(n or 0), "hit_rate": hit_rate, "source": source,
            "as_of": as_of, "evidence": list(evidence or [])}


def validate_epistemic(e):
    if not isinstance(e, dict) or e.get("status") not in STATUSES:
        raise ValueError("epistemic.status 必须为 verified/candidate/prior；无标记不得引用")
    status = e["status"]
    if status == "verified":
        if not isinstance(e.get("n"), int) or e["n"] <= 0:
            raise ValueError("已核销知识必须有 n>0")
        if not isinstance(e.get("hit_rate"), (int, float)) or not 0 <= e["hit_rate"] <= 1:
            raise ValueError("已核销知识必须有 0..1 命中率")
        if e.get("source") != "mechanical" or not e.get("as_of"):
            raise ValueError("已核销必须由机械核销产生并带 as_of，模型不得自封")
        if not isinstance(e.get("evidence"), list) or not e["evidence"]:
            raise ValueError("已核销必须带核销证据")
    else:
        if e.get("hit_rate") is not None:
            raise ValueError("候选/纯先验不得伪造命中率")
    return True


def citable(obj):
    """04/06/live/signal 只认机械已核销；任何缺字段/异常都关闭引用。"""
    try:
        e = obj.get("epistemic") or {}
        return e.get("status") == "verified" and bool(validate_epistemic(e))
    except (ValueError, TypeError, AttributeError):
        return False


def candidate(source="model", as_of="", evidence=None):
    return epistemic("candidate", 0, None, source, as_of, evidence)


def prior(source="model", as_of="", evidence=None):
    return epistemic("prior", 0, None, source, as_of, evidence)


def verified(n, hit_rate, as_of, evidence):
    e = epistemic("verified", n, hit_rate, "mechanical", as_of, evidence)
    validate_epistemic(e)
    return e
