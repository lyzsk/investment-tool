# -*- coding: utf-8 -*-
"""regime_trades.py — B: 每位导师在每种状态下的 胜率 / 盈亏比 / 期望值 / 凯利分数(零 token; 10/18 晚用户定)

为什么: 右侧交易靠 胜率 × 盈亏比 × 仓位 盈利; 三态自检(indicators_db --validate)显示"趋势标签本身不是优势"(A 股随机票趋势后反而偏回归),
        所以要看的是: 每位导师自己在 上涨趋势 / 下跌趋势 / 交易区间 / 无规则 里出手, 结果分别怎样 → 哪种状态听谁的、该给多大仓位。
数据: skills/<id>-skill/persona/cases_auto.jsonl 的卖出事件(result.pnl = 该笔 FIFO 收益, hold_days = 持有交易日数)
      → 买入日 = 卖出日往前 hold_days 个交易日; 状态 / 均线位置 / 箱体位置 取 **买入日前一交易日收盘**(买的时候已知, 不偷看)
      状态来自 scripts/quotes/indicators_db.py(同一套前复权 + 三态阈值)
统计(按 导师 × 买入时状态): 平仓笔数 / 胜率 / 平均盈利 / 平均亏损 / 盈亏比 / 期望值(每笔平均收益) / 1/4 凯利仓位 / 中位持有天数;
      另按 买入时在 EMA144 上方 vs 下方、交易区间里 箱体下部(<0.33)/中部/上部(>0.67) 拆
口径限制: pnl 是不含费用的价差收益(cases_auto 口径); 同日来回(做 T)也算一笔; 样本 <10 笔的格子只看方向
产物: scripts/tzzb/model_out/regime_trades.json + scripts/tzzb/model_out/reports/regime_trades_<日>.md
      + 每位导师 skills/<id>-skill/persona/fingerprint.md 末尾 <!-- AUTO:三态 --> 块(蒸馏 / 链 / mix 读)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/regime_trades.py [--ledger a,b]
"""
import argparse
import bisect
import datetime as dt
import json
import re
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
import a_rules as AR        # noqa: E402
import mentors as M         # noqa: E402
import indicators_db as ID  # noqa: E402

OUT = ROOT / "scripts" / "tzzb" / "model_out"
MARK0, MARK1 = "<!-- AUTO:三态 -->", "<!-- /AUTO:三态 -->"
STATES = ["上涨趋势", "下跌趋势", "交易区间", "无规则", "数据不足"]


def stats(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    w = [x for x in xs if x > 0]
    l = [x for x in xs if x <= 0]
    p = len(w) / len(xs)
    aw = st.mean(w) if w else 0.0
    al = -st.mean(l) if l else 0.0
    b = aw / al if al > 0 else None
    return {"n": len(xs), "win": round(p, 3), "avg_win": round(aw, 4), "avg_loss": round(al, 4), "payoff": None if b is None else round(b, 2),
            "exp": round(st.mean(xs), 4), "kelly4": ID.kelly(p, b) if b else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger")
    a = ap.parse_args()
    ids = a.ledger.split(",") if a.ledger else M.ids("tzzb")
    trades = {}
    syms = set()
    for sk in ids:
        f = ROOT / "skills" / f"{sk}-skill" / "persona" / "cases_auto.jsonl"
        if not f.exists():
            continue
        T = []
        for l in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(l)
            except ValueError:
                continue
            res = r.get("result") or {}
            if r.get("side") != "卖" or res.get("pnl") is None or AR.symbol(str(r.get("code"))) is None:
                continue
            T.append((r["date"], str(r["code"]), float(res["pnl"]), int(res.get("hold_days") or 0), r.get("name") or ""))
        trades[sk] = T
        syms |= {AR.symbol(c) for _, c, _, _, _ in T}
    syms.add("sh000001")
    for sk in ids:   # 同窗口对比要用到的: 真人近期买入 + 链账本买入的票
        f = ROOT / "skills" / f"{sk}-skill" / "persona" / "cases_auto.jsonl"
        for l in (f.read_text(encoding="utf-8").splitlines() if f.exists() else []):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if r.get("side") == "买" and r.get("date", "") >= "2026-10-01" and AR.symbol(str(r.get("code"))):
                syms.add(AR.symbol(str(r["code"])))
        try:
            b = json.loads((ROOT / "scripts" / "dfcf" / "paper" / "books" / f"{M.book(sk)}.json").read_text(encoding="utf-8"))
            syms |= {AR.symbol(str(t["code"])) for t in b.get("trades") or [] if AR.symbol(str(t["code"]))}
        except Exception:   # noqa: BLE001
            pass
    print(f"导师 {len(trades)} 位, 平仓 {sum(len(v) for v in trades.values())} 笔, 涉及 {len(syms)} 只; 读行情算三态…")
    raw = ID.load(sorted(syms), d0="2019-01-01")
    ser = {}
    for s, g in raw.groupby("symbol"):
        d = ID.compute(g)
        if d is not None:
            ser[s] = {row.date: (row.regime, row.box_pos, row.c / row.ema144 - 1 if row.ema144 else None) for row in d[["date", "regime", "box_pos", "c", "ema144"]].itertuples()}
    cal = sorted(ser.get("sh000001", {}))
    res, miss = {}, 0
    for sk, T in trades.items():
        by = defaultdict(list)
        for D, code, pnl, hd, nm in T:
            i = bisect.bisect_left(cal, D)
            if i >= len(cal) or cal[i] != D:
                i = bisect.bisect_right(cal, D) - 1
            e = i - hd            # 买入日
            if e - 1 < 0:
                miss += 1
                continue
            k = ser.get(AR.symbol(code), {}).get(cal[e - 1])   # 买入前一交易日收盘
            if not k:
                miss += 1
                continue
            reg, bp, v144 = k
            by[("状态", reg)].append(pnl)
            by[("全部", "全部")].append(pnl)
            if v144 is not None:
                by[("EMA144", "上方" if v144 >= 0 else "下方")].append(pnl)
                by[("状态×EMA144", f"{reg}·{'上方' if v144 >= 0 else '下方'}")].append(pnl)
            if reg == "交易区间" and bp is not None and bp == bp:
                by[("区间位置", "下部" if bp < 0.33 else "上部" if bp > 0.67 else "中部")].append(pnl)
        res[sk] = {f"{k[0]}|{k[1]}": stats(v) for k, v in by.items()}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "regime_trades.json").write_text(json.dumps({"updated": dt.datetime.now().isoformat(timespec="seconds"), "mentors": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    fmt = lambda s: "—" if not s else (f"{s['n']} 笔 · 胜率 {s['win']:.0%} · 盈亏比 {s['payoff'] if s['payoff'] is not None else '—'} · 期望 {s['exp'] * 100:+.2f}%"   # noqa: E731
                                     + (f" · ¼凯利 {s['kelly4']:.0%}" if s.get("kelly4") is not None else ""))
    md = [f"# 导师 × 三态 胜率 / 盈亏比 / 期望值({dt.date.today()}; regime_trades.py 机械生成)", "",
          "> 状态 = 买入前一交易日收盘时的三态(indicators_db.py); 收益 = 该笔平仓价差(不含费用); 期望 = 每笔平均收益; ¼凯利 = 按胜率和盈亏比算的建议仓位上限的 1/4(0 = 期望为负)。<10 笔的格子只看方向。", "",
          "| 导师 | 全部 | 上涨趋势 | 下跌趋势 | 交易区间 | 无规则 |", "|---|---|---|---|---|---|"]
    for sk, R in res.items():
        try:
            name = M.get(sk)["name"]
        except Exception:   # noqa: BLE001
            name = sk
        md.append(f"| {name} | " + " | ".join(fmt(R.get(k)) for k in ("全部|全部", "状态|上涨趋势", "状态|下跌趋势", "状态|交易区间", "状态|无规则")) + " |")
        # 写进导师指纹(AUTO 块)
        fp = ROOT / "skills" / f"{sk}-skill" / "persona" / "fingerprint.md"
        if fp.exists():
            blk = [MARK0, f"## 三态 × 胜率 / 盈亏比 / 期望值(regime_trades.py 机械生成 {dt.date.today()}; 状态 = 买入前一日收盘, 收益不含费用)", ""]
            for grp, keys in (("按买入时状态", ["状态|上涨趋势", "状态|下跌趋势", "状态|交易区间", "状态|无规则"]),
                              ("按 EMA144", ["EMA144|上方", "EMA144|下方"]), ("交易区间里的位置", ["区间位置|下部", "区间位置|中部", "区间位置|上部"])):
                blk.append(f"- **{grp}**: " + " ; ".join(f"{k.split('|')[1]} {fmt(R.get(k))}" for k in keys if R.get(k)))
            blk += [f"- 全部: {fmt(R.get('全部|全部'))}", MARK1]
            t = fp.read_text(encoding="utf-8")
            t = re.sub(re.escape(MARK0) + r"[\s\S]*?" + re.escape(MARK1), lambda _: "\n".join(blk), t) if MARK0 in t else t.rstrip() + "\n\n" + "\n".join(blk) + "\n"
            fp.write_text(t, encoding="utf-8")
    md += ["", f"(买入日或行情对不上、没算进来的平仓 {miss} 笔)"]
    # 10/19 备周三: ①候选规则(某状态 ≥10 笔且期望 ≤ 0 → "该状态少买") ②链 vs 真人 买入时状态分布(拟人度新维度)
    md += ["", "## 候选规则(某状态下 ≥10 笔且期望 ≤ 0; 周三起经你确认再写进各导师 rules.md, 标 [画像] 待验证)", ""]
    for sk, R in res.items():
        for k, v in R.items():
            if k.startswith("状态|") and v and v["n"] >= 10 and v["exp"] <= 0:
                md.append(f"- {M.get(sk)['name'] if sk in M.ids() else sk}: 在「{k.split('|')[1]}」里买 {v['n']} 笔, 胜率 {v['win']:.0%}, 期望 {v['exp'] * 100:+.2f}% → 候选「{k.split('|')[1]}少买 / 降档」")
    md += ["", "## 链 vs 真人: 买入时状态分布(**同一时间窗** = 链有成交的日子(10/8 起); 状态 = 买入前一交易日收盘)", "",
           "> 10/19 教训: 先前拿真人全历史(含牛市段)比链 10/8 起(回调段), 差距被市况放大成 50 个百分点; 同窗口后只差约 6 个点。链 vs 真人一律同窗口比。", "",
           "| 导师 | 真人 上涨 / 下跌 / 区间 / 无规则 | 真人买单数 | 链 上涨 / 下跌 / 区间 / 无规则 | 链买单数 |", "|---|---|---|---|---|"]
    paper = ROOT / "scripts" / "dfcf" / "paper" / "books"
    pool_r, pool_c = defaultdict(int), defaultdict(int)

    def st_of(code, D):
        i = bisect.bisect_left(cal, D)
        k = ser.get(AR.symbol(str(code)) or "", {}).get(cal[i - 1]) if i > 0 else None
        return k[0] if k else None
    for sk in res:
        try:
            b = json.loads((paper / f"{M.book(sk)}.json").read_text(encoding="utf-8"))
        except Exception:   # noqa: BLE001
            continue
        cnt, rc = defaultdict(int), defaultdict(int)
        days = set()
        for t in b.get("trades") or []:
            D = str(t.get("id", ""))[:10]
            if t.get("side") != "BUY" or D < "2026-10-08":
                continue
            days.add(D)
            s = st_of(t["code"], D)
            if s:
                cnt[s] += 1
        if days:
            f = ROOT / "skills" / f"{sk}-skill" / "persona" / "cases_auto.jsonl"
            for l in (f.read_text(encoding="utf-8").splitlines() if f.exists() else []):
                try:
                    r = json.loads(l)
                except ValueError:
                    continue
                if r.get("side") == "买" and min(days) <= r.get("date", "") <= max(days):
                    s = st_of(r.get("code"), r["date"])
                    if s:
                        rc[s] += 1
        n, nr = sum(cnt.values()), sum(rc.values())
        for s in STATES[:4]:
            pool_r[s] += rc[s]
            pool_c[s] += cnt[s]
        fmtd = lambda C, N: " / ".join(f"{C[s] / N:.0%}" for s in STATES[:4]) if N else "—"   # noqa: E731
        md.append(f"| {M.get(sk)['name']} | {fmtd(rc, nr)} | {nr} | {fmtd(cnt, n)} | {n} |")
    nr, n = sum(pool_r.values()), sum(pool_c.values())
    if n:
        md.append(f"| **合计** | {' / '.join(f'{pool_r[s] / max(nr, 1):.0%}' for s in STATES[:4])} | {nr} | {' / '.join(f'{pool_c[s] / n:.0%}' for s in STATES[:4])} | {n} |")
    rp = OUT / "reports" / f"regime_trades_{dt.date.today():%Y%m%d}.md"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[4:]))
    print(f"→ {rp.relative_to(ROOT)}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
