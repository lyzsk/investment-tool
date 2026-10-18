# -*- coding: utf-8 -*-
"""edge_map.py — 导师「强项地图」: 导师 × 打法 × 市况 格子的扣费后期望(收缩估计), 给混合账本 A-mix-sw(扬长避短)用(10/17 建; 零 token, 只读)

设计: docs/research/mix_strengths_weaknesses_20261017.md
证据:
  真人: skills/<导师>-skill/persona/cases_auto.jsonl 的新开仓买入(play=统一打法分类器标签, feat.zt_n_prev=昨日涨停家数, result.r_next / r_5d)
        持有口径按导师: mentor_scope.json hold_days_med ≥3 用 r_5d, 否则 r_next; 扣固定费 fee_pct
  链:   (二期) 链 paper 成交的打法标签还没打 —— 现在链证据 0 条, 权重公式已按 params 留好(n_chain 增长后自动加权)
格子: (打法, 情绪温度) —— 情绪温度按昨日涨停家数分档(params mix_sw.temp_bins, 缺省 <40 冷 / 40~80 温 / ≥80 热)
收缩: 格子均值 → 向该导师该打法均值收缩(k_cell) → 再向该导师全体均值收缩(k_play) → 导师均值向全体导师收缩(k_mentor)
判定(as-of, 只用 < D 的样本): n ≥ min_n 且 收缩均值 ≤ cut_mean 且 t ≤ −t_min → cut(混合账本不跟); ≥ boost_mean 且 t ≥ t_min → boost(加权); 其余 neutral
真人/链权重(params mix_sw.real_weight): mode auto → w_chain = n_chain / (n_chain + chain_k), w_real = 1 − w_chain; fixed → 用 real_fixed
产物: scripts/dfcf/paper/edge_map/<D>.json(+ .md 人看表)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/edge_map.py [--date D] [--show 导师] [--selftest]
"""
import argparse
import json
import math
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "edge_map"
DEF = dict(min_n=20, cut_mean=-0.005, boost_mean=0.005, t_min=1.0, k_cell=20, k_play=30, k_mentor=50, fee_pct=0.0015,
           temp_bins=[40, 80], real_weight={"mode": "auto", "chain_k": 60, "real_fixed": 0.7})


def params():
    try:
        import yaml
        p = (yaml.safe_load((HERE / "params.yaml").read_text(encoding="utf-8")) or {}).get("mix_sw") or {}
    except Exception:   # noqa: BLE001
        p = {}
    out = dict(DEF)
    out.update({k: v for k, v in p.items() if k in DEF})
    return out


def mentors():
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "lib"))
        import mentors as M   # noqa: PLC0415  登记表(10/17)
        return M.ids("tzzb")
    except Exception:   # noqa: BLE001
        return [l["ledger"] for l in json.loads((ROOT / "scripts/tzzb/tzzb_ledgers.json").read_text(encoding="utf-8")) if l.get("kind") == "pos"]


def temp_of(zt_n, bins):
    if zt_n is None:
        return "未知"
    return "冷" if zt_n < bins[0] else "温" if zt_n < bins[1] else "热"


_CAL = None


def _cal():
    """交易日历 = 全部导师 cases_auto 出现过的日期并集(导师每个交易日总有人成交, 够当日历用; 不联网不读库)"""
    global _CAL
    if _CAL is None:
        ds = set()
        for f in (ROOT / "skills").glob("*-skill/persona/cases_auto.jsonl"):
            for line in f.read_text(encoding="utf-8").splitlines():
                i = line.find('"date": "')
                if i >= 0:
                    ds.add(line[i + 9:i + 19])
        _CAL = sorted(ds)
    return _CAL


def samples(ledger, asof, P):
    f = ROOT / "skills" / f"{ledger}-skill" / "persona" / "cases_auto.jsonl"
    if not f.exists():
        return []
    scope = {}
    try:
        scope = json.loads((ROOT / "scripts/tzzb/mentor_scope.json").read_text(encoding="utf-8")).get(ledger) or {}
    except (OSError, ValueError):
        pass
    try:
        use5 = float(scope.get("hold_days_med") or 1) >= 3
    except (TypeError, ValueError):   # 如"无统计，按画像"
        use5 = False
    # 10/17 审计中-10: 样本的结果(r_next / r_5d)要在 asof 之前就已知——买入日必须早于 asof 往前数 1 / 5 个交易日, 否则回放会带后见之明
    cal = [x for x in _cal() if x < asof]
    h = 5 if use5 else 1
    cut = cal[-h] if len(cal) >= h else "0000-00-00"
    # 10/18 R16: 扣费改用本导师自己的券商费率(scripts/tzzb/fee_profile.json, 从他的成交反推: 买佣 + 卖佣含印花税), 没有才用固定 fee_pct
    fee = P["fee_pct"]
    try:
        fp = json.loads((ROOT / "scripts/tzzb/fee_profile.json").read_text(encoding="utf-8")).get(ledger) or {}
        if fp.get("buy_rate") is not None and fp.get("sell_rate_incl_stamp") is not None:
            fee = float(fp["buy_rate"]) + float(fp["sell_rate_incl_stamp"])
    except (OSError, ValueError, TypeError):
        pass
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            c = json.loads(line)
        except ValueError:
            continue
        if c.get("side") != "买" or not c.get("new_open") or str(c.get("date")) >= cut:
            continue
        r = (c.get("result") or {}).get("r_5d" if use5 else "r_next")
        if r is None:
            continue
        out.append({"play": c.get("play") or "未分类", "temp": temp_of((c.get("feat") or {}).get("zt_n_prev"), P["temp_bins"]), "r": float(r) - fee})
    return out


def shrink(mean, n, prior, k):
    return (n * mean + k * prior) / (n + k) if n + k else prior


def tstat(xs):
    if len(xs) < 3:
        return 0.0
    sd = st.pstdev(xs)
    return (st.mean(xs) / (sd / math.sqrt(len(xs)))) if sd > 0 else 0.0


def build(asof, P=None):
    P = P or params()
    data = {m: samples(m, asof, P) for m in mentors()}
    allr = [x["r"] for v in data.values() for x in v]
    g = st.mean(allr) if allr else 0.0
    n_chain = 0   # 二期: 链 paper 成交打法标签接入后计数
    rw = P["real_weight"]
    w_chain = (n_chain / (n_chain + float(rw.get("chain_k", 60)))) if rw.get("mode") == "auto" else 1 - float(rw.get("real_fixed", 0.7))
    res = {"date": asof, "generated_at": datetime.now().isoformat(timespec="seconds"), "params": P, "global_mean": round(g, 5),
           "weights": {"real": round(1 - w_chain, 3), "chain": round(w_chain, 3), "n_chain": n_chain, "mode": rw.get("mode")}, "mentors": {}}
    for m, xs in data.items():
        if not xs:
            continue
        mm = shrink(st.mean([x["r"] for x in xs]), len(xs), g, P["k_mentor"])
        byp, byc = defaultdict(list), defaultdict(list)
        for x in xs:
            byp[x["play"]].append(x["r"])
            byc[(x["play"], x["temp"])].append(x["r"])
        pm = {p: shrink(st.mean(v), len(v), mm, P["k_play"]) for p, v in byp.items()}
        cells = {}
        for (p, tp), v in byc.items():
            sh = shrink(st.mean(v), len(v), pm[p], P["k_cell"])
            t = tstat(v)
            act = "neutral"
            if len(v) >= P["min_n"]:
                if sh <= P["cut_mean"] and t <= -P["t_min"]:
                    act = "cut"
                elif sh >= P["boost_mean"] and t >= P["t_min"]:
                    act = "boost"
            cells[f"{p}|{tp}"] = {"n": len(v), "raw": round(st.mean(v), 5), "shrunk": round(sh, 5), "t": round(t, 2), "action": act}
        plays = {p: {"n": len(byp[p]), "shrunk": round(pm[p], 5)} for p in byp}
        res["mentors"][m] = {"n": len(xs), "mean_shrunk": round(mm, 5), "plays": plays, "cells": cells}
    return res


def write(res):
    OUT.mkdir(exist_ok=True)
    (OUT / f"{res['date']}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    L = [f"# 导师强项地图 · {res['date']}(as-of, 只用之前的样本)", "",
         f"> 格子=打法 × 情绪温度(昨日涨停家数 <{res['params']['temp_bins'][0]} 冷 / <{res['params']['temp_bins'][1]} 温 / 其余热); 收益=扣费后(各导师按自己反推的券商费率, 没有的按 {res['params']['fee_pct']:.2%}); "
         f"判定门槛 n≥{res['params']['min_n']}、收缩均值 ≤{res['params']['cut_mean']:.1%} 且 t≤−{res['params']['t_min']} → 不跟 / ≥{res['params']['boost_mean']:.1%} 且 t≥{res['params']['t_min']} → 加权。"
         f" 真人/链权重 {res['weights']['real']}/{res['weights']['chain']}(链证据 {res['weights']['n_chain']} 条, mode={res['weights']['mode']})", "",
         "| 导师 | 样本 | 收缩均值 | 不跟(格子) | 加权(格子) |", "|---|---|---|---|---|"]
    for m, v in sorted(res["mentors"].items(), key=lambda kv: -kv[1]["mean_shrunk"]):
        cut = [f"{k}({c['shrunk']:+.1%}, n{c['n']})" for k, c in v["cells"].items() if c["action"] == "cut"]
        bst = [f"{k}({c['shrunk']:+.1%}, n{c['n']})" for k, c in v["cells"].items() if c["action"] == "boost"]
        L.append(f"| {m} | {v['n']} | {v['mean_shrunk']:+.2%} | {'; '.join(cut) or '-'} | {'; '.join(bst) or '-'} |")
    (OUT / f"{res['date']}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


def lookup(res, mentor, play, temp):
    """混合账本查询: (action, 收缩均值); 无数据=neutral"""
    v = (res or {}).get("mentors", {}).get(mentor) or {}
    c = (v.get("cells") or {}).get(f"{play}|{temp}")
    return (c["action"], c["shrunk"]) if c else ("neutral", None)


def selftest():
    import random
    global samples, mentors
    keep = (samples, mentors)
    try:
        random.seed(1)
        mentors = lambda: ["a"]
        samples = lambda m, asof, P: ([{"play": "首板次日", "temp": "温", "r": random.gauss(-0.03, 0.02)} for _ in range(40)]
                                      + [{"play": "连板接力", "temp": "温", "r": random.gauss(0.02, 0.02)} for _ in range(40)]
                                      + [{"play": "追涨", "temp": "冷", "r": random.gauss(-0.05, 0.02)} for _ in range(5)])
        r = build("2026-10-19")
        c = r["mentors"]["a"]["cells"]
        assert c["首板次日|温"]["action"] == "cut", c
        assert c["连板接力|温"]["action"] == "boost", c
        assert c["追涨|冷"]["action"] == "neutral", "样本 <min_n 不应判定"
        assert lookup(r, "a", "无此打法", "温") == ("neutral", None)
        print("EDGE_MAP SELFTEST PASS")
    finally:
        samples, mentors = keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    write(build(a.date))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
