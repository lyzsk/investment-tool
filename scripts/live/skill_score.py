# -*- coding: utf-8 -*-
"""skill_score.py — C 方案: 实盘线 skill 成绩零 token 机械算(10/25 用户定; 每晚跑, 只读)

口径(用户 10/25):
  每天每条线从用户真实持仓起步(土豆 = 自己的账) → 成绩 = 一串互相独立的"单日"战绩, 测不到连续持仓能力
  日超额 = 模拟账收盘净值 − 同起点全天不动的净值 = Σ 每笔成交按收盘价算的贡献(买: (收盘 − 成交价) × 量 − 费; 卖: (成交价 − 收盘) × 量 − 费)
           超额% = 日超额 ÷ 开盘净值(起点持仓按昨收 + 现金)
  没成交的单: 不改持仓、当天作废、不进成绩 → 只进过程诊断(plan_review: 挂太低·错过 / 挂太高·该走没走 / 差一点)
  被停的线(你收束 / 09:19 没留下 / 定时停): 成绩拆两块 = 叫模型时段内的成交 + 停后机械撮合(停了改不了单), 合计 = 总成绩; 标"部分时段"
  起点检查: 起点持仓来自哪天的 snapshots 收盘持仓, 是不是上一交易日(不是 → ⚠, 当天成绩要打问号)
  你主要看过程: 每条线标出贡献最大的那笔(和最大的错过), 附那一版 06 原文路径
产物: <根>/<D>/review/skill_score.md + .json; 实盘根(results/_live)另把当天各线写进 results/_live/skill_score.jsonl(同日重跑覆盖) → 累计排名
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/live/skill_score.py --date 2026-10-26 [--root results/_replay/2026-10-23]
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "live"), str(ROOT / "scripts" / "lib")]
import line_periods as LP   # noqa: E402
import plan_review as PR   # noqa: E402

LIVE = ROOT / "results" / "_live"
CUM = LIVE / "skill_score.jsonl"


def prev_trade_day(D):
    try:
        c = PR.db().cursor()
        c.execute("select max(trade_date) from investment_market.kline_day where symbol='sh000001' and trade_date < %s", (D,))
        r = c.fetchone()
        return str(r[0]) if r and r[0] else None
    except Exception:   # noqa: BLE001
        return None


def score_line(ldir, x, M, D, pday):
    st = json.loads((ldir / "state.json").read_text(encoding="utf-8"))
    s0 = st.get("start") or {}
    pos0 = s0.get("positions") or {}
    pc = lambda c: (M.day.get(c) or {}).get("pre_close")   # noqa: E731
    nav_open = float(s0.get("cash") or 0) + sum(int(p.get("qty") or 0) * float(pc(c) or p.get("cost") or 0) for c, p in pos0.items())
    per = LP.periods(ldir)
    B = PR.load_book(ldir)
    vdir = {v["v"]: v["vdir"] for v in B["vers"]}
    contrib, miss_close = [], []
    for t in st.get("trades") or []:
        c, q, px, fee = str(t["code"]), int(t["qty"]), float(t["px"]), float(t.get("fee") or 0)
        cl = M.close(c)
        if not cl:
            miss_close.append(c)
            continue
        amt = ((cl - px) if t["side"] == "BUY" else (px - cl)) * q - fee
        try:
            v = int(str(t.get("rule") or "").split(":")[0])
        except ValueError:
            v = None
        after = bool(per["off_at"] and str(t.get("t") or "") >= per["off_at"])
        contrib.append({"t": t.get("t"), "code": c, "name": M.name(c, t.get("name")), "side": t["side"], "qty": q, "px": px, "close": cl, "amt": round(amt, 2),
                        "after_off": after, "v": v, "vdir": str(ldir / "versions" / vdir[v]) if v in vdir and vdir[v] else None, "why": str(t.get("why") or "")[:120]})
    ex = sum(r["amt"] for r in contrib)
    ex_on = sum(r["amt"] for r in contrib if not r["after_off"])
    top = max(contrib, key=lambda r: abs(r["amt"]), default=None)
    misses = [o for o in x["orders"] if "挂太低·错过" in (o.get("miss_tags") or []) or "挂太高·该走没走" in (o.get("miss_tags") or [])]
    def _cost(o):   # 错过 / 没走掉的幅度(相对挂价, %)
        return abs(PR.pct(o["close"], o["px"]) or 0)
    tm = max(misses, key=_cost, default=None)
    src = str(s0.get("from") or "")
    sday = src.split(":")[-1] if src.startswith("real:") else None
    start_ok = None if not src.startswith("real:") else (sday == pday if pday else None)
    pct_ = lambda a: round(a / nav_open * 100, 3) if nav_open else None   # noqa: E731
    return {"id": x["id"], "skill": x.get("skill"), "name": x.get("name"), "D": D, "nav_open": round(nav_open, 2), "excess": round(ex, 2), "excess_pct": pct_(ex),
            "excess_on": round(ex_on, 2), "excess_on_pct": pct_(ex_on), "excess_off": round(ex - ex_on, 2), "excess_off_pct": pct_(ex - ex_on),
            "partial": per["partial"], "on_min": per["on_secs"] // 60, "periods": per["text"], "n_trades": len(contrib), "n_orders": x["n_orders"],
            "n_miss": len(misses), "top": top, "top_miss": ({"code": tm["code"], "name": tm["name"], "side": tm["side"], "px": tm["px"], "close": tm["close"],
                                                           "tags": tm.get("miss_tags"), "versions": tm.get("versions"), "why": tm.get("why", "")[:120],
                                                           "vdir": str(ldir / "versions" / vdir[tm["versions"][-1]]) if tm.get("versions") and vdir.get(tm["versions"][-1]) else None} if tm else None),
            "start_from": src, "start_ok": start_ok, "prev_day": pday, "no_close": miss_close}


def fpct(x):
    return "—" if x is None else f"{x:+.2f}%"


def render(D, rows, cum):
    side = {"BUY": "买", "SELL": "卖"}
    L = [f"# skill 成绩(C 方案) {D}", "",
         "> 零 token。日超额 = 模拟账收盘净值 − 同起点全天不动; 每天从你的真实持仓起步, 所以是一串独立的单日战绩。没成交的单不进成绩(只进计划核销的过程诊断)。",
         "> 被停的线: 合计 = 叫模型时段内 + 停后机械撮合(停了改不了单, 那部分别记在 skill 头上)。", "",
         "| 线 | 叫模型 | 日超额 | 其中叫模型时段 | 停后撮合 | 成交 | 挂单 | 错过/没走 | 起点 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: -(r["excess_pct"] or 0)):
        so = "✅" if r["start_ok"] else ("—(自己的账)" if r["start_ok"] is None and not str(r["start_from"]).startswith("real:") else f"⚠ {r['start_from']} ≠ 上一交易日 {r['prev_day']}")
        L.append(f"| {r['name']} | {'⏸ 部分 ' + str(r['on_min']) + ' 分钟' if r['partial'] else '全天'} | {r['excess']:+,.0f}({fpct(r['excess_pct'])}) | {fpct(r['excess_on_pct'])} | "
                 f"{fpct(r['excess_off_pct']) if r['partial'] else '—'} | {r['n_trades']} | {r['n_orders']} | {r['n_miss']} | {so} |")
    L += ["", "## 每条线该读哪一笔(你主要看过程)", ""]
    for r in rows:
        L.append(f"### {r['name']}")
        if r["partial"]:
            L.append(f"- 时段: {r['periods']}")
        t = r["top"]
        if t:
            L.append(f"- 贡献最大: {t['t'][:5]} {side[t['side']]} {t['name']} {t['qty']} 股 @{t['px']} → 收盘 {t['close']} = {t['amt']:+,.0f} 元"
                     + (" ⏸停后撮合" if t["after_off"] else "") + f"; 当时理由: {t['why']}" + (f"; 原文 `{t['vdir']}\\06.md`" if t["vdir"] else ""))
        else:
            L.append("- 当天没有成交")
        m = r["top_miss"]
        if m:
            L.append(f"- 最大的错过 / 没走掉: {side[m['side']]} {m['name']} 挂 {m['px']} 收盘 {m['close']} 〔{' / '.join(m['tags'] or [])}〕; 当时理由: {m['why']}"
                     + (f"; 原文 `{m['vdir']}\\06.md`" if m["vdir"] else ""))
        if r["no_close"]:
            L.append(f"- ⚠ 这些票没有收盘价, 没算进成绩: {', '.join(r['no_close'])}")
        L.append("")
    if cum:
        L += ["## 累计(实盘线, 按单日超额% 相加)", "", "| skill | 天数 | 其中部分时段 | 累计超额% | 日均 | 最好一天 | 最差一天 |", "|---|---|---|---|---|---|---|"]
        for k, v in sorted(cum.items(), key=lambda kv: -sum(x["excess_pct"] or 0 for x in kv[1])):
            xs = [x["excess_pct"] or 0 for x in v]
            L.append(f"| {v[-1]['name']} | {len(v)} | {sum(1 for x in v if x['partial'])} | {sum(xs):+.2f}% | {sum(xs) / len(xs):+.2f}% | {max(xs):+.2f}% | {min(xs):+.2f}% |")
    return "\n".join(L) + "\n"


def run(D, root):
    root = Path(root)
    if not root.is_absolute():
        root = ROOT / root
    day = root / D if (root / D).is_dir() else root
    R, M = PR.run(D, root, write=True, do_dlog=False)   # 先跑核销(没成交单的诊断标签在里面), 同时拿到行情
    pday = prev_trade_day(D)
    byid = {x["id"]: x for x in R["lines"]}
    rows = []
    for p in sorted(day.glob("live_*")):
        x = byid.get(PR.LDS.lid_of(p.name)) or byid.get(p.name)
        if x and (p / "state.json").exists():
            rows.append(score_line(p, x, M, D, pday))
    cum = None
    if day.resolve().parent == LIVE.resolve():   # 只有实盘根才进累计
        old = [json.loads(l) for l in CUM.read_text(encoding="utf-8").splitlines() if l.strip()] if CUM.exists() else []
        old = [r for r in old if r.get("D") != D] + [{k: v for k, v in r.items() if k not in ("top", "top_miss")} for r in rows]
        CUM.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in sorted(old, key=lambda r: (r["D"], r["id"]))) + "\n", encoding="utf-8")
        cum = {}
        for r in old:
            cum.setdefault(r.get("skill") or r["id"], []).append(r)
    od = day / "review"
    od.mkdir(parents=True, exist_ok=True)
    (od / "skill_score.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (od / "skill_score.md").write_text(render(D, rows, cum), encoding="utf-8")
    return rows, od


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--root", default="results/_live")
    a = ap.parse_args()
    rows, od = run(a.date, a.root)
    for r in rows:
        print(f"{r['id']:<22} {'部分' if r['partial'] else '全天'} 日超额 {r['excess']:+,.0f}({fpct(r['excess_pct'])}) 叫模型时段 {fpct(r['excess_on_pct'])} 停后 {fpct(r['excess_off_pct'])} 成交 {r['n_trades']} 起点 {r['start_from']}")
    print("→", od / "skill_score.md")


if __name__ == "__main__":
    main()
