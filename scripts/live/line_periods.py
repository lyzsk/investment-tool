# -*- coding: utf-8 -*-
"""line_periods.py — 每条实盘线当天"叫模型时段"(10/25 用户: 要记录我什么时候把某个 skill 停了; 零 token, 只读)

读 <线目录>/events.jsonl 里执行器记的三种事件(时刻 = 盘中时钟, 回放 = 模拟时钟):
  休眠(没留下, 不叫模型)  09:19 没进留下名单 / 你盘中收束(微信「暂停」/ keep.py); why = 谁几点改的名单(10/25 起执行器写)
  留下(叫模型)            你加回(之后 KICK 重想一次)
  定时停(不再叫模型)      LIVE_STOP_AFTER(土豆 10:00)
→ periods(ldir) = {"segs": [{from, to, on, why}], "on_secs", "off_at"(第一次停的时刻 / None), "partial", "text"}
休眠 ≠ 账本冻结: 之前挂的单照样机械撮合 —— 核销里"停之后成交"的单标出来; C 方案(skill 成绩)按 on 时段标"部分时段"
用法: python line_periods.py <线目录>   (调试)
"""
import json
import sys
from pathlib import Path

OPEN, CLOSE = "09:00:00", "15:00:00"
OFF = {"休眠(没留下, 不叫模型)": "收束 / 没留下", "定时停(不再叫模型)": "定时停"}
ON = {"留下(叫模型)"}


def _secs(t):
    h, m, s = (int(x) for x in t.split(":"))
    return h * 3600 + m * 60 + s


def _trade_secs(a, b):
    """a~b 之间的交易秒数(扣午休 11:30~13:00)"""
    x, y = _secs(a), _secs(b)
    lo, hi = _secs("11:30:00"), _secs("13:00:00")
    return max(0, y - x) - max(0, min(y, hi) - max(x, lo))


def periods(ldir):
    ldir = Path(ldir)
    evs = []
    try:
        for l in (ldir / "events.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                evs.append(json.loads(l))
            except ValueError:
                continue
    except OSError:
        pass
    segs, on, since, why = [], True, OPEN, "盘前首跑"
    for e in evs:
        k, t = e.get("kind"), str(e.get("t") or "")[:8]
        if len(t) != 8:
            continue
        if k in OFF and on:
            w = e.get("why") or (f"定时停 {e.get('at', '')}" if k.startswith("定时停") else OFF[k] + "(原因没记录: 10/25 前的执行器)")
            segs.append({"from": since, "to": t, "on": True, "why": why})
            on, since, why = False, t, (f"定时停 {e.get('at', '')}(LIVE_STOP_AFTER)" if k.startswith("定时停") else w)
        elif k in ON and not on:
            segs.append({"from": since, "to": t, "on": False, "why": why})
            on, since, why = True, t, e.get("why") or "加回"
    segs.append({"from": since, "to": CLOSE, "on": on, "why": why})
    segs = [s for s in segs if s["from"] < s["to"]]
    on_secs = sum(_trade_secs(s["from"], s["to"]) for s in segs if s["on"])
    off_at = next((s["from"] for s in segs if not s["on"]), None)
    txt = "; ".join(f"{s['from'][:5]}~{s['to'][:5]} {'叫模型' if s['on'] else '不叫模型'}" + ("" if s["on"] and s["why"] == "盘前首跑" else f"({s['why']})") for s in segs)
    if off_at:
        txt += " —— 不叫模型期间之前挂的单照样撮合"
    return {"segs": segs, "on_secs": on_secs, "off_at": off_at, "partial": off_at is not None, "text": txt}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for a in sys.argv[1:]:
        p = periods(a)
        print(Path(a).name, "部分时段" if p["partial"] else "全时段", f"叫模型 {p['on_secs'] // 60} 分钟", "|", p["text"])
