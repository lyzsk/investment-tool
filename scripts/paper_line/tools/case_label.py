# -*- coding: utf-8 -*-
"""case_label.py — 导师案例(cases_auto.jsonl 每条买 / 卖)机械打 正 / 负 / 平 标签(10/23 用户: 芷影 10-14 海欣是亏钱走人, 模型却当成买入依据 —— 案例没标正负)

口径(只看结果, 不看动机):
  卖: result.pnl ≥ +1% → 正; ≤ −1% → 负; 其余 / 成本未知 → 平(成本未知标"未知")
  买: 有对应的卖(同票之后第一笔卖)用那笔卖的 pnl; 没有就用 result.r_next(买入日收盘 → 次日收盘): ≥ +1% 正 / ≤ −2% 负 / 其余平
用法: label(row, rows) → ("正"|"负"|"平"|"未知", 数值%, 说明)
      summary(skill, code) → 一行文本(必查 "导师同票" 用): 每次买卖带标签, 负样本醒目标出
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _rows(skill):
    p = ROOT / "skills" / f"{skill}-skill" / "persona" / "cases_auto.jsonl"
    try:
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return []


def label(r, rows=None):
    res = r.get("result") or {}
    if r.get("side") == "卖":
        p = res.get("pnl")
        if p is None:
            return "未知", None, "成本未知"
        return ("正" if p >= 0.01 else "负" if p <= -0.01 else "平"), round(p * 100, 2), f"卖出盈亏 {p * 100:+.1f}%"
    if r.get("side") == "买":
        nxt = next((x for x in (rows or []) if x.get("code") == r.get("code") and x.get("side") == "卖" and (x.get("date"), x.get("time")) > (r.get("date"), r.get("time"))), None)
        if nxt and (nxt.get("result") or {}).get("pnl") is not None:
            p = nxt["result"]["pnl"]
            return ("正" if p >= 0.01 else "负" if p <= -0.01 else "平"), round(p * 100, 2), f"{nxt['date']} 卖出盈亏 {p * 100:+.1f}%"
        rn = res.get("r_next")
        if rn is None:
            return "未知", None, "还没有结果"
        return ("正" if rn >= 0.01 else "负" if rn <= -0.02 else "平"), round(rn * 100, 2), f"买入日收盘→次日收盘 {rn * 100:+.1f}%"
    return "未知", None, ""


def summary(skill, code, D=None):
    rows = _rows(skill)
    mine = [r for r in rows if str(r.get("code")) == code and r.get("side") in ("买", "卖") and (D is None or r.get("date", "") < D)]
    if not mine:
        return "导师没做过"
    cnt = {"正": 0, "负": 0, "平": 0, "未知": 0}
    parts = []
    for r in mine[-8:]:
        lb, v, why = label(r, rows)
        cnt[lb] += 1
        parts.append(f"{r['date'][5:]} {r['side']}{'(' + str(r.get('play')) + ')' if r.get('play') else ''} → {'⚠负样本' if lb == '负' else lb} {why}")
    neg = cnt["负"]
    head = f"导师做过 {len(mine)} 次(最近 8 次: 正 {cnt['正']} / 负 {neg} / 平 {cnt['平']} / 未知 {cnt['未知']})"
    tail = " | ⚠ 负样本只能当教训、写在'最怕什么', 不能当买入依据" if neg else ""
    return head + ": " + "; ".join(parts) + tail


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(summary(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
