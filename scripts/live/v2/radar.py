# -*- coding: utf-8 -*-
"""零token机械雷达：signal→连续状态/窗口→动态盯盘名单→少量候选推送。"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "knowledge"), str(Path(__file__).resolve().parent)]
from context_pack import ContextPending  # noqa: E402
from decision_windows import evaluate  # noqa: E402
from market_state import current  # noqa: E402
from store import KnowledgeStore  # noqa: E402

EXTRA = ROOT / "scripts" / "temp" / "collect_book_extra.txt"
BEGIN, END = "# >>> 决策雷达自动(radar.py 生成)", "# <<< 决策雷达"


def update_extra(codes, path=EXTRA):
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    text = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", text, flags=re.S)
    if codes:
        text = text.rstrip("\n") + f"\n{BEGIN}\n" + " ".join(sorted(codes)) + f"\n{END}\n"
    path.write_text(text, encoding="utf-8")


class Radar:
    def __init__(self, day, out_dir, max_day=6, cooldown_s=1800, store=None, extra_path=EXTRA):
        self.day, self.dir = day, Path(out_dir)
        self.extra_path = Path(extra_path)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.store = store or KnowledgeStore(ROOT / "downloads" / "ontology" / "ontology.db")
        self.max_day, self.cooldown_s = max_day, cooldown_s
        self.last, self.states, self.fired = {}, {}, 0

    def close(self):
        self.store.close()

    def on_event(self, event, now_s):
        """返回可交给原Pusher的候选事件；无窗口/冷却/超过少量上限则None。"""
        code = event["code"]
        if self.fired >= self.max_day or now_s - self.last.get(code, -10**9) < self.cooldown_s:
            return None
        try:
            state = current(self.store, code, self.day, event["t"])
        except ContextPending:
            from adapters import MarketAdapter
            prev = next((d.name for d in sorted((ROOT / "downloads" / "market").glob("20*"), reverse=True)
                         if d.name < self.day and (d / "kline_day.jsonl").exists()), None)
            if prev:
                MarketAdapter(self.store).ingest_day(prev, "", [code])
            try:
                state = current(self.store, code, self.day, event["t"])
            except ContextPending:
                with (self.dir / "pending_context.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"event": event, "status": "pending_context"}, ensure_ascii=False) + "\n")
                return None
        odds = event.get("odds") or {}
        stats = {"n": odds.get("n") or 0, "hit_rate": odds.get("p")}
        windows = evaluate(state, event, stats=stats, exit_ok=bool(event.get("px")))
        if not windows:
            return None
        state["changes"] = []
        previous = self.states.get(code)
        if previous:
            for key in ("cycle_stage", "position", "auction", "pattern"):
                if previous["dimensions"].get(key) != state["dimensions"].get(key):
                    state["changes"].append({"field": key, "from": previous["dimensions"].get(key), "to": state["dimensions"].get(key)})
        self.states[code] = state
        w = windows[0]
        record = {"t": event["t"], "code": code, "signal": event["sig"], "window": w,
                  "dimensions": state["dimensions"], "changes": state["changes"], "source_event": event}
        with (self.dir / "decision_windows.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.last[code], self.fired = now_s, self.fired + 1
        update_extra(set(self.states), self.extra_path)
        return {"t": event["t"], "code": code, "name": event.get("name") or code, "sig": "W1", "sig_name": "决策窗口",
                "px": event.get("px") or 0, "detail": f"{w['kind']}｜{w['direction']}｜{w['confidence']['cap']}｜缺:{'/'.join(w['confidence']['missing'][:2]) or '无'}｜失效:{w['invalid_if']}｜下一查:{w['next_check']}",
                "hold": event.get("hold"), "pool": event.get("pool"), "radar": True}
