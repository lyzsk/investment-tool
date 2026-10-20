# -*- coding: utf-8 -*-
"""paper_vs_real.py — paper 链 vs 导师真人 每晚偏离归因(10/19 用户定; 零 token, 只读)

为什么: 10/19 发现 paper 和导师真人每天收益差约 −1%, 逐日持仓 10 位里 9 位从 10/8 起一天都没重合;
        真人买的票只有 36% 出现在当天给链的事实包里——链看不见的票不可能选(候选池召回是第一根因, 不是规则不够)。
按 "日期 + 代码 + 导师" 串: 导师真人持仓(tzzb day_positions) / paper 持仓(成交流水重放到当天收盘) / 真人买入 / 当天事实包 / 收益
每位导师每天算:
  重合      paper 与真人当天持仓有没有同一只票; 真人持仓里 paper 也有的仓位占比
  仓位差    paper 股票仓位 − 真人仓位(百分点)
  候选召回  真人当天买入的票, 有没有出现在当天任一时段的事实包(facts.md / scan.md)里
  收益差    paper 当日收益 − 真人当日收益
  归因      这一天差距主要来自: 看不见(召回 0) / 看见没选 / 选了不同的票 / 仓位轻重 / 撮合(当日成交被重算过)
产物(不另存报告, 直接进 skill, 蒸馏消费):
  skills/<id>-skill/persona/fingerprint.md 末尾 <!-- AUTO:paper偏离 --> 块(近 10 个交易日逐日一行 + 汇总 + 读法)
  scripts/dfcf/paper/paper_vs_real.json(facts.mjs「导师真人昨日持仓」节 / 午间体检 / report 读; 开关 CHAIN_MENTOR_HOLD_FACTS)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/paper_vs_real.py [--date D]
"""
import argparse
import datetime as dt
import glob
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TZ = ROOT / "downloads" / "tzzb"
MARK0, MARK1 = "<!-- AUTO:paper偏离 -->", "<!-- /AUTO:paper偏离 -->"
START = "2026-10-08"


def rj(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def paper_daily(b):
    pos, out, tr, i = defaultdict(int), {}, sorted(b.get("trades") or [], key=lambda t: str(t["id"])), 0
    nav = {n["date"]: n for n in b.get("nav") or []}
    for d in sorted(x for x in nav if x >= START):
        while i < len(tr) and str(tr[i]["id"])[:10] <= d:
            t = tr[i]
            pos[t["code"]] += t["qty"] if t["side"] == "BUY" else -t["qty"]
            i += 1
        n = nav[d]
        out[d] = {"codes": sorted(c for c, q in pos.items() if q > 0), "stock_w": 1 - (n.get("cash") or 0) / n["nav"] if n.get("nav") else None, "nav": n.get("nav")}
    return out


def facts_text(d, cache={}):
    if d not in cache:
        cache[d] = "".join(Path(f).read_text(encoding="utf-8") for f in glob.glob(str(HERE / "facts" / d / "*" / "facts.md")) + glob.glob(str(HERE / "facts" / d / "*" / "scan.md")))
    return cache[d]


sys.path.insert(0, str(ROOT / "scripts" / "market"))
try:
    import topology as TOPO   # 10/19 晚 TODO 二-13: "同板块算半重合"
except ImportError:
    TOPO = None


def same_sector(a, b, d):
    """a / b 同东财行业, 或互为拓扑前 10 邻居 = 半重合(事后评估用, 当天拓扑没有就用最近一份, 不涉及决策不怕偷看)"""
    if not TOPO:
        return False
    ra, rb = TOPO.load(a, d) or TOPO.load(a, "9999"), TOPO.load(b, d) or TOPO.load(b, "9999")
    if not ra or not rb:
        return False
    return bool(ra.get("ind") and ra["ind"] == rb.get("ind")) or b in {x["c"] for x in ra["nb"]} or a in {x["c"] for x in rb["nb"]}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    excl = set((rj(ROOT / "scripts" / "tzzb" / "paper_excluded.json") or {}).get("excluded", {}))
    led = [x for x in rj(ROOT / "scripts" / "tzzb" / "tzzb_ledgers.json") or [] if x.get("book") and x["ledger"] not in excl]
    res = {}
    for x in led:
        sk, src = x["ledger"], x["book"]
        b = rj(HERE / "books" / f"{src}.json")
        dp = rj(TZ / sk / "day_positions.json") or {}
        idx = {i["date"]: float(i["index"]) for i in ((rj(TZ / sk / "nav_daily.json") or {}).get("ex_data") or {}).get("index_list") or []}
        if not b or not dp:
            continue
        pd = paper_daily(b)
        buys = defaultdict(set)
        for l in (ROOT / "skills" / f"{sk}-skill" / "persona" / "cases_auto.jsonl").read_text(encoding="utf-8").splitlines() if (ROOT / "skills" / f"{sk}-skill" / "persona" / "cases_auto.jsonl").exists() else []:
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if r.get("side") == "买" and r.get("date", "") >= START:
                buys[r["date"]].add(str(r.get("code")))
        restated = {r.get("date") for r in b.get("restated_fills") or []}
        rows, prev_d = [], None
        for d in sorted(pd):
            d8 = d.replace("-", "")
            rl = {y["code"]: float(y["position_percent"]) for y in (dp.get(d8) or {}).get("list") or [] if float(y["position_percent"]) > 0}
            p = pd[d]
            row = {"d": d, "paper": p["codes"], "real": sorted(rl), "real_w": round(sum(rl.values()), 3) if d8 in dp else None,
                   "paper_w": round(p["stock_w"], 3) if p["stock_w"] is not None else None}
            row["overlap"] = sorted(set(p["codes"]) & set(rl))
            row["half"] = sorted(f"{c}~{q}" for c in set(rl) - set(p["codes"]) for q in set(p["codes"]) - set(rl) if same_sector(c, q, d))
            row["cover"] = round(sum(w for c, w in rl.items() if c in p["codes"]) / sum(rl.values()), 3) if rl else None
            bs = buys.get(d, set())
            ft = facts_text(d) if bs else ""
            row["real_buys"], row["seen"] = sorted(bs), sorted(c for c in bs if c in ft)
            if prev_d and pd[prev_d]["nav"] and p["nav"]:
                pr = p["nav"] / pd[prev_d]["nav"] - 1
                p8 = prev_d.replace("-", "")
                rr = idx[d8] / idx[p8] - 1 if d8 in idx and p8 in idx else None
                row["paper_ret"], row["real_ret"] = round(pr, 4), (round(rr, 4) if rr is not None else None)
                row["gap"] = round(pr - rr, 4) if rr is not None else None
            # 归因(一天一句, 按优先级)
            why = []
            if bs and not row["seen"]:
                why.append(f"看不见: 真人买的 {len(bs)} 只当天事实包里都没有")
            elif bs and not (set(row["seen"]) & set(p["codes"])):
                why.append(f"看见没选: 真人买的票有 {len(row['seen'])} 只在事实包里, 链没买")
            if rl and not row["overlap"]:
                why.append("持仓 0 重合" + (f"(同板块半重合 {len(row['half'])} 对)" if row["half"] else ""))
            if row["real_w"] is not None and row["paper_w"] is not None and abs(row["real_w"] - row["paper_w"]) >= 0.3:
                why.append(f"仓位差 {(row['paper_w'] - row['real_w']) * 100:+.0f} 个百分点")
            if d in restated:
                why.append("当日成交被重算过(撮合口径)")
            row["why"] = why
            rows.append(row)
            prev_d = d
        cmp_ = [r for r in rows if r["real_w"] is not None]
        sm = {"days": len(cmp_), "overlap_days": sum(1 for r in cmp_ if r["overlap"]), "half_days": sum(1 for r in cmp_ if r["half"] and not r["overlap"]),
              "avg_cover": round(sum(r["cover"] or 0 for r in cmp_) / max(len(cmp_), 1), 3),
              "avg_pos_gap": round(sum((r["paper_w"] or 0) - (r["real_w"] or 0) for r in cmp_) / max(len(cmp_), 1), 3),
              "buys": sum(len(r["real_buys"]) for r in rows), "seen": sum(len(r["seen"]) for r in rows),
              "avg_gap": round(sum(r["gap"] for r in rows if r.get("gap") is not None) / max(1, sum(1 for r in rows if r.get("gap") is not None)), 4)}
        res[src] = {"skill": sk, "name": x.get("name"), "summary": sm, "days": rows}
        # 写进 skill(蒸馏消费)
        fp = ROOT / "skills" / f"{sk}-skill" / "persona" / "fingerprint.md"
        if fp.exists():
            L = [MARK0, f"## paper 链 vs 本人真实操作 偏离(paper_vs_real.py 每晚机械生成 {a.date}; 蒸馏时先看这块: 差在哪一环)", "",
                 f"- 近 {sm['days']} 天: 持仓有重合 {sm['overlap_days']} 天(另有只是同板块的半重合 {sm['half_days']} 天) | 你的持仓里链也有的仓位平均 {sm['avg_cover'] * 100:.0f}% | 链股票仓位比你平均 {sm['avg_pos_gap'] * 100:+.0f} 个百分点"
                 f" | 你买的 {sm['buys']} 只里当天链的事实包能看到 {sm['seen']} 只 | 链日收益比你平均 {sm['avg_gap'] * 100:+.2f}%", "",
                 "| 日期 | 链持仓 | 你的持仓(仓位) | 重合 | 你当天买 / 链看得见 | 收益 链 vs 你 | 归因 |", "|---|---|---|---|---|---|---|"]
            for r in rows[-10:]:
                L.append(f"| {r['d'][5:]} | {'、'.join(r['paper']) or '空仓'} | {'、'.join(r['real']) or '空仓'}({(r['real_w'] or 0) * 100:.0f}%) | {'、'.join(r['overlap']) or (('同板块 ' + '、'.join(r['half'][:3])) if r['half'] else '—')} | "
                         f"{len(r['real_buys'])} / {len(r['seen'])} | {('%+.2f%%' % (r['paper_ret'] * 100)) if r.get('paper_ret') is not None else '—'} vs {('%+.2f%%' % (r['real_ret'] * 100)) if r.get('real_ret') is not None else '—'} | {'；'.join(r['why']) or '—'} |")
            L += ["", "读法: '看不见' = 候选池问题(驱动器 / 事实包没给, 链没机会选), 不是规则问题; '看见没选' 才是 skill 规则 / 判断要改进的地方; 仓位差持续同方向 = 规模规则没学到。", MARK1]
            t = fp.read_text(encoding="utf-8")
            t = re.sub(re.escape(MARK0) + r"[\s\S]*?" + re.escape(MARK1), lambda _: "\n".join(L), t) if MARK0 in t else t.rstrip() + "\n\n" + "\n".join(L) + "\n"
            fp.write_text(t, encoding="utf-8")
    (HERE / "paper_vs_real.json").write_text(json.dumps({"updated": dt.datetime.now().isoformat(timespec="seconds"), "date": a.date, "mentors": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    tb, ts = sum(v["summary"]["buys"] for v in res.values()), sum(v["summary"]["seen"] for v in res.values())
    print(f"{len(res)} 位导师; 真人买入 {tb} 只, 当天事实包能看到 {ts} 只({ts / max(tb, 1):.0%})")
    for v in res.values():
        s = v["summary"]
        print(f"  {v['name'][:8]}: 重合 {s['overlap_days']}/{s['days']} 天, 仓位差 {s['avg_pos_gap'] * 100:+.0f}pt, 召回 {s['seen']}/{s['buys']}, 日收益差 {s['avg_gap'] * 100:+.2f}%")


if __name__ == "__main__":
    main()
