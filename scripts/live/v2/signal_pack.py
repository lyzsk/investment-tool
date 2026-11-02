# -*- coding: utf-8 -*-
"""live v2 signal 包：只提供可执行观察／复核所需结构，不让模型空泛结束。"""
from context_pack import get_context_pack
from schema import CONTRACT_VERSION


def signal_pack(store, code, at, signal_type="generic"):
    pack = get_context_pack(store, code, at, purpose="signal", budget="small")
    return {
        "contract_version": CONTRACT_VERSION,
        "code": code,
        "signal_type": signal_type,
        "at": at,
        "stance": "观察并等待当前情境确认",
        "action": "只按现有机械 signal 与风控执行，不自动新增模型仓位",
        "evidence": pack["cases"],
        "context": pack["context"],
        "belief_state": pack["belief_state"],
        "forecast": pack["forecast"],
        "confidence": {"raw": "低" if pack["forecast"].get("n", 0) < 20 else "中", "n": pack["forecast"].get("n", 0)},
        "invalid_if": "当前盘口与同簇状态不再支持该 signal 的成立条件",
        "next_check": "下一次同簇／核心板态或3秒盘口变化时复核",
        "missing": pack["missing"],
    }


def event_pack(store, event, day):
    """真实 signals.py 事件 → live v2 包；不改原事件、不绕过机械风控。"""
    sig = event["sig"]
    pack = signal_pack(store, event["code"], f"{day}T{event['t']}", signal_type=sig)
    sell = sig in ("S16", "S18", "S13", "S15")
    auction = sig in ("S6", "S16", "S17", "S18")
    odds = event.get("odds") or {}
    signal_n = int(odds.get("n") or 0)
    pack.update(
        signal=dict(event),
        stance=("竞价出现卖方证据，优先复核持仓卖点与失效条件" if sell and auction else
                "竞价出现买方证据，等待开盘后价格和同簇确认" if auction else
                "卖方盘口证据成立，优先复核持仓处置" if sell else
                "买方盘口证据成立，等待同簇和后续盘口确认"),
        action=("对持仓推送抢跑／高抛提醒；只按原计划单和机械风控执行" if sell else
                "记录并推送原信号；不自动新增模型仓位，后续仍走机械风控"),
        invalid_if=("价格收回09:20竞价基准且卖方未匹配不再占优" if sell and auction else
                    "开盘后跌回09:20竞价基准且买方未匹配不再占优" if auction else
                    "后续3秒盘口不再支持该信号方向"),
        next_check="09:30首笔、随后3秒盘口及同簇核心票" if auction else "下一次3秒盘口或同簇核心板态变化",
    )
    pack["confidence"] = {"raw": "中" if signal_n >= 20 else "低", "n": pack["forecast"].get("n", 0),
                          "signal_n": signal_n, "signal_p": odds.get("p"), "signal_dir": odds.get("dir")}
    return pack
