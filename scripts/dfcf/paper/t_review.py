# -*- coding: utf-8 -*-
"""t_review.py — 做 T 每日复盘(零 token; 10/18 建, 决策 T 的"进化"标签源)

收盘后(行情库 15:35 采完分钟线之后, 由 check md 调): 对每个品种用当日 1 分钟线机械算"事后最优 T":
  正T(先买后卖) 最大价差 = max_{i<j}(高_j / 低_i − 1)      反T(先卖后买) 最大价差 = max_{i<j}(高_i / 低_j − 1)
  (银行 T+1: 正T 的卖出动用底仓, 买入那部分留到次日, 价差仍按同日算; 只看价差上限, 不含规模)
再对齐三本账(不T / 机械T / 决策T)当天: 成交、收盘净值、T 的实现盈亏(相对不T), 写 t_log/<日>.json
  决策 T 的"近 5 天复盘"就读这里的 summary(下一交易日的决策提示词带上) → 每天都有可学的标签
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/t_review.py --date D
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import t_bot as TB   # noqa: E402
import a_rules as AR  # noqa: E402

GROUPS = {"601988": {"name": "中国银行", "hold": "A-hbank", "mech": "A-tbank", "dec": "A-dbank", "skill": "bank"},
          "159941": {"name": "纳指ETF(广发)", "hold": "A-hndq", "mech": "A-tndq", "dec": "A-dndq", "skill": "nasdaq"},
          # 10/18 晚: 用户实盘持仓牧原(私有: 日卡 / 复盘只写 snapshots/muyuan-skill/, 不进公共 t_log; 多一列"你的实盘 T")
          "002714": {"name": "牧原股份", "hold": "A-hmuyuan", "mech": "A-tmuyuan", "dec": "A-dmuyuan", "skill": "muyuan", "real": True,
                     "skill_dir": TB.SNAP / "muyuan-skill"}}


def est_fee(side, amt):
    """用户券商口径: 佣金+其他费用 每笔最低 5 元(万2.5), 卖出另收印花税 0.05%"""
    return max(5.0, amt * 0.00025) + (amt * 0.0005 if side == "SELL" else 0.0)


def t_value(trades, close):
    """当日 T 增值(元) = 卖出额 − 买入额 − 费用 + 当日净增减股数 × 收盘价 = 今天这些交易比"一笔不做"多赚的钱; trades=[(side, price, qty, fee|None)]"""
    v, fee, net = 0.0, 0.0, 0
    for side, px, qty, f in trades:
        amt = float(px) * int(qty)
        f = est_fee(side, amt) if f is None else float(f)
        v += amt if side == "SELL" else -amt
        net += -int(qty) if side == "SELL" else int(qty)
        fee += f
    return round(v - fee + net * close, 2), round(fee, 2), net


def write_card(sk, D, card, skill_dir=None):
    """品种 skill 的日卡: 插在 <!-- CASES --> 之后(新卡在前), 同日重跑先删旧卡(私有 skill 用 skill_dir)"""
    f = Path(skill_dir or ROOT / "skills" / f"{sk}-skill") / "persona" / "cases.md"
    if not f.exists():
        return
    t = f.read_text(encoding="utf-8")
    t = re.sub(rf"(?ms)^### {D} .*?(?=^### 20\d\d-|\Z)", "", t)
    head, _, tail = t.partition("<!-- CASES -->")
    f.write_text(f"{head}<!-- CASES -->\n\n{card.strip()}\n\n{tail.lstrip()}", encoding="utf-8")


def bars(D, code):
    f = ROOT / "downloads" / "market" / D / "kline_minute.jsonl"
    sym = AR.symbol(code)
    out = []
    if f.exists():
        for l in f.read_text(encoding="utf-8").splitlines():
            if f'"{sym}"' in l:
                r = json.loads(l)
                if r.get("symbol") == sym:
                    out.append(r)
    return sorted(out, key=lambda r: r["barTime"])


def best_t(B):
    if len(B) < 30:
        return None
    lo_min, lo_t, best_pos = 9e9, None, (0.0, None, None)
    hi_max, hi_t, best_neg = 0.0, None, (0.0, None, None)
    for b in B:
        t = b["barTime"][11:16]
        if b["high"] / lo_min - 1 > best_pos[0]:
            best_pos = (b["high"] / lo_min - 1, lo_t, t)
        if hi_max and hi_max / b["low"] - 1 > best_neg[0]:
            best_neg = (hi_max / b["low"] - 1, hi_t, t)
        if b["low"] < lo_min:
            lo_min, lo_t = b["low"], t
        if b["high"] > hi_max:
            hi_max, hi_t = b["high"], t
    return {"正T": {"spread": round(best_pos[0], 4), "buy_at": best_pos[1], "sell_at": best_pos[2]},
            "反T": {"spread": round(best_neg[0], 4), "sell_at": best_neg[1], "buy_at": best_neg[2]}}


def nav_of(src, code, close):
    b = TB.book(src)
    pos = int(((b.get("positions") or {}).get(code) or {}).get("qty") or 0)
    return float(b.get("cash") or 0) + pos * close, b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    D = a.date
    TB_DIR = TB.DATA / "t_log"
    TB_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"date": D, "generated_at": dt.datetime.now().isoformat(timespec="seconds"), "books": {}, "best": {}}
    st = {}
    try:
        st = json.loads((TB.DATA / "t_decide_state.json").read_text(encoding="utf-8")).get(D, {})
    except (OSError, ValueError):
        pass
    priv = {"date": D, "generated_at": rec["generated_at"], "books": {}, "best": {}}
    for code, g in GROUPS.items():
        R = priv if g.get("real") else rec
        if g.get("real") and not (TB.book(g["dec"]).get("trades") or TB.real_trades(D, {code})):
            continue   # 牧原: 账本还没起跑且当天没实盘成交 → 不写
        B = bars(D, code)
        bt = best_t(B)
        close = B[-1]["close"] if B else None
        R["best"][code] = bt
        if not close:
            continue
        hold_nav, _ = nav_of(g["hold"], code, close)
        for kind in ("hold", "mech", "dec"):
            nav, b = nav_of(g[kind], code, close)
            tr4 = [(t["side"], t["price"], t["qty"], t.get("fee")) for t in b.get("trades") or [] if str(t.get("id", "")).startswith(D)]
            trades = [x[:3] for x in tr4]
            tv = t_value(tr4, close) if kind != "hold" else (0.0, 0.0, 0)
            dec = {k: (v or {}).get("decision") for k, v in (st.get(g[kind]) or {}).items() if isinstance(v, dict) and v.get("decision")} if kind == "dec" else None
            summ = (f"{g['name']} 收 {close}; 事后最优 正T {bt['正T']['spread']:.2%}({bt['正T']['buy_at']}买→{bt['正T']['sell_at']}卖) / 反T {bt['反T']['spread']:.2%}"
                    f"({bt['反T']['sell_at']}卖→{bt['反T']['buy_at']}买)" if bt else f"{g['name']} 收 {close}; 分钟线不足")
            summ += f"; 本账本成交 {trades or '无'}; 净值 {nav:.0f}(不T {hold_nav:.0f}, 差 {nav - hold_nav:+.0f})"
            if dec:
                summ += "; 当时决策: " + " | ".join(f"{k} {d.get('action')} {d.get('tier')}: {str(d.get('reason'))[:60]}" for k, d in dec.items())
            R["books"][g[kind]] = {"nav": round(nav, 2), "vs_hold": round(nav - hold_nav, 2), "trades": trades, "decisions": dec, "summary": summ,
                                   "t_value": tv[0], "fee": tv[1], "net_qty": tv[2]}
        if g.get("real"):   # 用户实盘: 从 snapshots 成交单算同口径 T 增值
            rt = TB.real_trades(D, {code})
            tv = t_value([(x[2], x[4], x[3], x[6]) for x in rt], close)
            R["books"]["REAL"] = {"trades": len(rt), "t_value": tv[0], "fee": tv[1], "net_qty": tv[2]}
        bk = R["books"]
        card = [f"### {D} {g['name']}" + (f" · 事后最优 正T {bt['正T']['spread']:.2%} / 反T {bt['反T']['spread']:.2%}" if bt else "")]
        if bt:
            card.append(f"- 最优时点: 正T {bt['正T']['buy_at']}买→{bt['正T']['sell_at']}卖; 反T {bt['反T']['sell_at']}卖→{bt['反T']['buy_at']}买")
        dd = bk.get(g["dec"]) or {}
        for k, d in (dd.get("decisions") or {}).items():
            card.append(f"- 决策 {k}: {d.get('action')} {d.get('tier')} — {str(d.get('reason') or '')[:120]}")
        card.append("- 当天成交: " + "; ".join(f"{n} {(bk.get(g[n2]) or {}).get('trades') or '无'}" for n, n2 in (("决策T", "dec"), ("机械T", "mech"))))
        card.append("- 净值 vs 不T: " + " / ".join(f"{n} {(bk.get(g[n2]) or {}).get('vs_hold', 0):+.0f}" for n, n2 in (("决策T", "dec"), ("机械T", "mech"))))
        card.append("- 当日 T 增值(扣费, 元): " + " / ".join(f"{n} {(bk.get(k) or {}).get('t_value', 0):+.0f}" for n, k in
                                                        ((("你的实盘", "REAL"),) if g.get("real") else ()) + (("决策T", g["dec"]), ("机械T", g["mech"]))))
        write_card(g["skill"], D, "\n".join(card), g.get("skill_dir"))
    (TB_DIR / f"{D}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    if priv["books"]:   # 私有复盘只进 snapshots(gitignore)
        pd_ = TB.SNAP / "muyuan-skill" / "t_log"
        pd_.mkdir(parents=True, exist_ok=True)
        (pd_ / f"{D}.json").write_text(json.dumps(priv, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in rec["books"].items():
        print(k, v["summary"][:200])


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
