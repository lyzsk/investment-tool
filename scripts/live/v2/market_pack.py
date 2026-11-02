# -*- coding: utf-8 -*-
"""市场池咨询pack：给“准备B哪只/哪类”使用，保留候选池而非强行单票。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "chain"), str(ROOT / "scripts" / "knowledge"), str(Path(__file__).resolve().parent)]
import chain_steps as CS  # noqa: E402
from context_pack import get_context_pack, ContextPending  # noqa: E402
from decision_pack import retrieve  # noqa: E402
from decision_windows import evaluate as evaluate_windows  # noqa: E402
from confidence import assess  # noqa: E402
from freshness import live02  # noqa: E402
from linkage import build as build_linkage  # noqa: E402
from market_state import current as market_current  # noqa: E402
from mentor_consult import account_start  # noqa: E402


def pack_for(store, code, day, at):
    try:
        return get_context_pack(store, code, f"{day}T{at}", purpose="chain04", budget="small")
    except ContextPending:
        from adapters import MarketAdapter
        prev = next((d.name for d in sorted((ROOT / "downloads" / "market").glob("20*"), reverse=True)
                     if d.name < day and (d / "kline_day.jsonl").exists()), None)
        if not prev:
            raise
        MarketAdapter(store).ingest_day(prev, "", [code])
        return get_context_pack(store, code, f"{day}T{at}", purpose="chain04", budget="small")


def build(store, skill, question, day, at, limit=12):
    watch_file = ROOT / "results" / "_live" / day / "watch_seed.json"
    import json
    watch = json.loads(watch_file.read_text(encoding="utf-8")) if watch_file.exists() else {}
    seed = (watch.get("seed") or [])[:limit]
    codes = [x["code"] for x in seed if x.get("code")]
    if not codes:
        raise ValueError("市场池为空，缺情境加待核销")
    packs = {c: pack_for(store, c, day, at) for c in codes}
    names = CS.names(day)
    account = account_start(day)
    state = account or {"cash": 0, "positions": {}, "trades": []}
    state["trades"] = []
    strategy = {"codes": [{"code": c, "rules": []} for c in codes[:5]]}
    facts01, _, _, _ = CS.build_01(skill, day, at, "市场池按需咨询，不执行交易", state, strategy, [], {}, "", "市场池咨询", None, live=False)
    stable, var, info = CS.persona(skill, [], [names.get(c) or c for c in codes], codes)
    retrieval = retrieve(skill, codes[0], names.get(codes[0]) or codes[0], day, at, packs[codes[0]]["context"]["dimensions"]["pattern"])
    state0 = market_current(store, codes[0], day, at)
    primary = packs[codes[0]]
    return {"contract_version": "1.1", "mode": "market_pool_consult", "skill": skill, "code": "AUTO", "question": question,
            "at": f"{day}T{at}", "account_mode": "real_start_excluding_601988" if account else "no_account_no_order", "account": account,
            "pool": [{"code": c, "name": names.get(c) or c, "tags": next((x.get("tags") for x in seed if x["code"] == c), []),
                      "dimensions": packs[c]["context"]["dimensions"], "linkage": build_linkage(c, day)} for c in codes],
            "facts01": facts01, "persona_stable": stable, "persona_on_demand": var, "persona_info": info,
            "knowledge": primary, "knowledge_pool": packs, "market_state": {k: v for k, v in state0.items() if k != "pack"},
            "live02": live02(codes[0], day, at), "decision_windows": evaluate_windows(state0),
            "retrieval": retrieval, "confidence_assessment": assess(n=0, coverage_ok=not retrieval["missing"])}
