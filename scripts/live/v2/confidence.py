# -*- coding: utf-8 -*-
"""机械置信上限：模型只能在 cap 内降档，不能把叙事升成高置信。"""
RANK = {"候选": 0, "低": 1, "中": 2, "高": 3}


def assess(*, n=0, hit_rate=None, baseline=None, avg_return=None, cost_pct=None,
           out_of_sample=False, counterexample_reviewed=False, exit_ok=None,
           coverage_ok=False, high_min_n=60, high_min_edge=0.10):
    reasons, missing = [], []
    edge = hit_rate - baseline if isinstance(hit_rate, (int, float)) and isinstance(baseline, (int, float)) else None
    net = avg_return - cost_pct if isinstance(avg_return, (int, float)) and isinstance(cost_pct, (int, float)) else None
    if n <= 0 or hit_rate is None:
        missing.append("独立核销样本")
    if baseline is None:
        missing.append("同期同池基准")
    if cost_pct is None:
        missing.append("实际成本")
    if not counterexample_reviewed:
        missing.append("反例复核")
    if exit_ok is not True:
        missing.append("退出可行性")
    if not coverage_ok:
        missing.append("必要数据覆盖")
    if not out_of_sample:
        missing.append("样本外验证")
    cap = "高"
    if n < high_min_n or edge is None or edge < high_min_edge or net is None or net <= 0 or not out_of_sample:
        cap = "中"
    if n < 20 or edge is None or edge <= 0 or net is None or net <= 0 or exit_ok is not True or not counterexample_reviewed or not coverage_ok:
        cap = "低"
    if n <= 0 or hit_rate is None:
        cap = "候选"
    reasons.append(f"n={n}, edge={edge}, net={net}, out_of_sample={out_of_sample}, exit_ok={exit_ok}")
    return {"cap": cap, "n": n, "edge": edge, "net_return": net, "missing": missing,
            "reason": "; ".join(reasons), "model_can_only_lower": True}


def clamp(confidence, assessment):
    conf = dict(confidence or {})
    raw = conf.get("raw") if conf.get("raw") in RANK else "候选"
    cap = assessment["cap"]
    conf["raw"] = raw if RANK[raw] <= RANK[cap] else cap
    conf["mechanical_cap"] = cap
    conf["mechanical"] = assessment
    return conf
