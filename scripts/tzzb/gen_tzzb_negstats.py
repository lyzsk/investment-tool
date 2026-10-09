#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_tzzb_negstats.py — 负例 5 人反模式统计(2026-10-08 夜, TODO §1.3)

定位: 负样本层——对 kind=neg 五人(洋大人/猎人IH/huweigang/买入太极/饿狼King, "大亏3+中亏1+小亏对照1")
跑机械画像(复用 gen_tzzb_profile.profile_stocks_fn)+ 负例专属维度(nav 连亏/回撤、深亏腿、亏损加仓),
并与正例(kind=pos 股票五人)对照, 产出 skills/tzzb-skill/references/negstats.md。
消费方: 链驱动器 05_risk 步注入(负例警示, 见 run_taoge_chain.py 钩子), 人工复盘亦可读。
幂等: 重跑覆盖 negstats.md; 数据源=downloads/tzzb/<ledger>/(负例语料已全量入库)。

用法: python scripts/tzzb/gen_tzzb_negstats.py [--json out.json]
出口: 0=ok 1=数据缺失
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):  # GBK 控制台防 ✓ 类字符炸 print(10/8 实测)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_tzzb_profile import (  # noqa: E402
    LEDGERS, NAME_OF, load_legs, load_nav, profile_stocks_fn)

ROOT = Path(__file__).resolve().parents[2]
OUT_MD = ROOT / "skills" / "tzzb-skill" / "references" / "negstats.md"
NEG = [l["ledger"] for l in LEDGERS if l.get("kind") == "neg"]
POS_STOCKS = [l["ledger"] for l in LEDGERS
              if l.get("kind") == "pos" and l["ledger"] not in ("buchitudou0",)]  # 股票正例(转债口径不同)


def nav_stats(nav: dict) -> dict:
    """净值日序列 → 累计/回撤/连亏(负例核心维度)。nav={date: 日收益率}"""
    days = sorted(d for d in nav if nav[d] is not None)
    if not days:
        return {}
    eq, peak, mdd, curve = 1.0, 1.0, 0.0, []
    for d in days:
        eq *= 1 + nav[d]
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
        curve.append(eq)
    streak = worst = cur = 0
    for d in days:
        cur = cur + 1 if nav[d] < 0 else 0
        streak, worst = (cur, d) if cur > streak else (streak, worst)
    return {"累计收益%": round((curve[-1] - 1) * 100, 1), "最大回撤%": round(mdd * 100, 1),
            "最长连亏日": streak, "连亏止于": worst, "交易日数": len(days)}


def enrich(ledger: str) -> dict:
    """基础画像 + 负例扩展(nav/腿反模式基于 trips 重算)。"""
    base = profile_stocks_fn(ledger)
    legs, nav = load_legs(ledger), load_nav(ledger)
    base["N1_nav"] = nav_stats(nav)
    # trips 级深亏(复用 profile 的 FIFO 配对逻辑太深, 这里按卖腿对当日均买价近似)
    byday = defaultdict(list)
    for t in legs:
        byday[t["trans_date"][:10]].append(t)
    deep, addown_days = 0, 0
    for d, ts in byday.items():
        buys = defaultdict(list)
        for t in ts:
            if t["op"] == "1":
                buys[t["stock_code"]].append(float(t["trans_price"]))
        for c, ps in buys.items():
            if any(b < a for a, b in zip(ps, ps[1:])):
                addown_days += 1
                break
    base["N2_反模式"] = {"亏损加仓日数": addown_days}
    h1 = base.get("H1_亏损应对", {})
    if "亏损隔夜扛占比" in h1:
        n, d = h1["亏损隔夜扛占比"].split("/")
        base["N2_反模式"]["亏损隔夜扛率"] = f"{int(n)/max(1,int(d)):.0%}"
    return base


def pos_baseline() -> dict:
    """正例五人均值(胜率/扛单/最大单亏), 对照行。"""
    agg = {"胜率_日内": [], "亏损隔夜扛率": [], "最大单日亏": []}
    for lg in POS_STOCKS:
        try:
            r = profile_stocks_fn(lg)
        except Exception as e:
            print(f"WARN 正例 {lg} 画像败: {e}")
            continue
        b = r.get("桶_日内", {})
        if "胜率" in b:
            agg["胜率_日内"].append(int(b["胜率"].split("/")[1].split("=")[1].rstrip("%")) / 100)
        h1 = r.get("H1_亏损应对", {})
        if "亏损隔夜扛占比" in h1:
            n, d = h1["亏损隔夜扛占比"].split("/")
            agg["亏损隔夜扛率"].append(int(n) / max(1, int(d)))
        if "最大单日亏%(净值口径)" in h1:
            agg["最大单日亏"].append(h1["最大单日亏%(净值口径)"] / 100)
    mean = lambda xs: sum(xs) / len(xs) if xs else None
    return {"正例均值": {k: f"{mean(v):.0%}" for k, v in agg.items()},
            "_raw": {k: [round(x, 3) for x in v] for k, v in agg.items()}}


def render(negs: dict, pos: dict) -> str:
    lines = [f"# 负例反模式统计(negstats, 自动生成 {date.today()})", "",
             "> 来源=gen_tzzb_negstats.py(幂等重跑); 消费方=链 05_risk 注入钩子 + 人工复盘。",
             "> 负例五人=大亏3+中亏1+小亏对照1; 正例基线=股票五人均值。", "",
             "| 人 | 累计% | 最大回撤% | 最长连亏日 | 亏损隔夜扛率 | 亏损加仓日 | 最大单日亏% |",
             "|---|---|---|---|---|---|---|"]
    warns = []
    for lg, r in negs.items():
        n1 = r.get("N1_nav", {})
        n2 = r.get("N2_反模式", {})
        h1 = r.get("H1_亏损应对", {})
        lines.append(f"| {r['name']} | {n1.get('累计收益%','-')} | {n1.get('最大回撤%','-')} | "
                     f"{n1.get('最长连亏日','-')} | {n2.get('亏损隔夜扛率','-')} | "
                     f"{n2.get('亏损加仓日数','-')} | {h1.get('最大单日亏%(净值口径)','-')} |")
        # 反模式卡(每人至多 3 条, 只取对正例有区分度的维度——扛单率正例也 96%, 无区分度故不列, 10/8 自查)
        card = []
        if n1.get("最长连亏日", 0) >= 7:
            card.append(f"连亏 {n1['最长连亏日']} 日不断仓(止于 {n1.get('连亏止于')})")
        if n1.get("最大回撤%", 0) <= -30:
            card.append(f"回撤 {n1['最大回撤%']}% 无风控")
        if h1.get("最大单日亏%(净值口径)", 0) <= -8:
            card.append(f"单日最大亏 {h1['最大单日亏%(净值口径)']}%(仓位无上限意识)")
        if n2.get("亏损加仓日数", 0) >= 20:
            card.append(f"{n2['亏损加仓日数']} 个亏损加仓日(越跌越买)")
        if card:
            warns.append(f"- **{r['name']}**: " + ";".join(card[:3]))
    lines += ["", "## 05 注入警示卡(驱动器取此节, 每链随机 ≤2 条)", ""] + (warns or ["- (无显著反模式)"])
    lines += ["", "## 正例基线(对照)", "", f"`{pos.get('正例均值')}`", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None, help="同时落 JSON(调试)")
    a = ap.parse_args()
    negs = {}
    for lg in NEG:
        d = ROOT / "downloads" / "tzzb" / lg
        if not d.exists():
            print(f"WARN 负例语料缺: {d}(跳过)")
            continue
        try:
            negs[lg] = enrich(lg)
            print(f"✓ {lg}({negs[lg]['name']}) 窗口 {negs[lg].get('窗口')}")
        except Exception as e:
            print(f"WARN {lg} 统计败: {e}")
    if not negs:
        sys.exit("负例全缺, exit 1")
    pos = pos_baseline()
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(render(negs, pos), encoding="utf-8")
    print(f"negstats.md 落盘 → {OUT_MD} ({len(negs)} 人)")
    if a.json:
        Path(a.json).write_text(
            json.dumps({"negs": negs, "pos": pos}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"json → {a.json}")


if __name__ == "__main__":
    main()
