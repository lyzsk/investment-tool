# -*- coding: utf-8 -*-
"""决策窗口：组合连续状态与signal；只产生候选，机械置信由confidence.py封顶。"""
from confidence import assess


def window(kind, direction, evidence, invalid_if, next_check, assessment=None):
    return {"kind": kind, "direction": direction, "status": "candidate", "action": "观察或按需问skill，不自动交易",
            "evidence": evidence, "confidence": assessment or assess(n=0), "invalid_if": invalid_if, "next_check": next_check}


def evaluate(state, signal=None, stats=None, exit_ok=None, cost_pct=None, counterexample_reviewed=False):
    d = state["dimensions"]
    out = []
    signal_type = (signal or {}).get("sig")
    stats = stats or {}
    assessment = assess(n=int(stats.get("n") or 0), hit_rate=stats.get("hit_rate"), baseline=stats.get("baseline"),
                        avg_return=stats.get("avg_return"), cost_pct=cost_pct, out_of_sample=bool(stats.get("out_of_sample")),
                        counterexample_reviewed=counterexample_reviewed, exit_ok=exit_ok,
                        coverage_ok=bool(state.get("evidence_ids")))
    if d["pattern"] in ("趋势", "转强候选"):
        out.append(window("trend_turn", "趋势/转强观察", [f"票型={d['pattern']}", f"均线事实={state.get('instrument', {}).get('trend', {})}"],
                          "跌回MA20且同簇不确认", "放量突破/站稳均价线后再评，不预判必然涨停", assessment))
    if signal_type in ("S6", "S17") or d["auction"] in ("竞价抢筹", "竞价低吸"):
        out.append(window("auction_repair", "竞价修复观察", [f"竞价={d['auction']}", f"市况={d['cycle_stage']}"],
                          "跌回09:20基准且买方不再占优", "09:30首笔、3秒盘口和同簇核心", assessment))
    if signal_type in ("S10", "S11", "S8"):
        out.append(window("pre_strength", "转强/冲板候选(不限连板)", [f"signal={signal_type}", f"票型={d['pattern']}"],
                          "强度不能延续或同簇核心转弱", "同簇同步度、成交额和下一档压力", assessment))
    if signal_type in ("S16", "S18"):
        out.append(window("sell_risk", "持仓抢跑/高抛风险复核", [f"signal={signal_type}", f"竞价={d['auction']}"],
                          "收回09:20基准且卖方不再占优", "持仓原计划卖点和真实承接", assessment))
    return out
