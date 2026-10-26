# -*- coding: utf-8 -*-
"""ontology/sample_lib.py — 样例库(10/25 用户批; 零 token, 只读业务库 / 本地文件, 产物写 downloads/ontology, 不写业务库)

一个样例 = 一次买入(导师 × 交易日 × 票: 当天第一笔买的时刻 + 当天全部买的均价; 全部同花顺账本, 停更 / 负收益 / 被排除的照样进; 只做股票)
特征(全部只用买入当天之前 / 当时已知的数据):
  板型买点  tzzb/board_entry.classify(一字排板 / T字板买 / 厂字板买 / 烂板回封买 / 回封板买 / 炸板买·回封 / 炸板买·没回封 / 深V低吸 / 反包板买 / 打板… / 非板日)
            注: 板型用的是买入当天全天走势(事后才知道当天怎么收) —— 这是"样例分类", 不是盘中可用的信号
  箱体位置  买价在日线段式箱体里的位置(买入日之前 160 根日线, 算法同 kline_struct / 术语表): 下沿(<25%) / 中部 / 上沿(>75%) / 越上沿 / 越下沿 / 已离箱向上 / 已离箱向下 / 无箱体
  连板高度  买入日之前连续封死涨停天数: 0 / 1 / 2 / 3+
  市况      T−1 上证涨跌(强 >+0.5% / 平 / 弱 <−0.5%) × T−1 全市场涨停家数(冷 <50 / 中 50~99 / 热 ≥100)
  题材      theme_life.by_stock(买入日之前 20 个交易日涨停分析里挂的第一个题材)
结果(相对买价 %): T+0 收盘 · T+1 / T+2 / T+3 最高和收盘
标签(用户 10/25 定): X = 这只票买入前 30 个交易日日振幅(高 − 低)/ 昨收 的中位(%)
  正 = T+1~T+3 任一天最高 ≥ 买价 × (1 + X%)  —— T 日浮亏但次日能冲高卖不算负
  负 = 3 天都没冲到 且 T+3 收盘 < 买价
  平 = 其余
  待核 n = 后面还差 n 个交易日的行情(每晚重算 = 每晚 n − 1; 冲到 +X% 立刻判正)
实际怎么出的: 同导师同票买入后的第一笔卖 → 当天卖(T 掉) / T+k 盈利卖 / T+k 亏损卖 / 3 天内没卖(拿着)
产物: downloads/ontology/samples.jsonl(全量重算) + docs/research/sample_lib.md(各导师 / 各板型 正负平)
查询: like(板型, 箱体位置, 连板高度, 市况) → 全部导师的同类样例: 正负平 + 结果全分布 + 最差 / 最好例(跨账本相似查询, 用户 10/25 要)
用法: python sample_lib.py build | python sample_lib.py like 炸板买·回封 上沿 2 弱·热 [--skill x] | python sample_lib.py like-id <样例 id>
"""
import argparse
import collections
import datetime as dt
import json
import statistics as st
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "tzzb"), str(ROOT / "scripts" / "paper_line" / "tools"), str(ROOT / "scripts" / "lib")]
OUT = ROOT / "downloads" / "ontology" / "samples.jsonl"
MD = ROOT / "docs" / "research" / "sample_lib.md"


def cur():
    import manual_backfill as mb
    return mb.db().cursor()


def box_pos(o, h, l_, c, px):
    """买入日之前的日线(numpy) → 箱体位置标签 + 数值"""
    import kline_struct as KS
    if len(c) < 30:
        return "无箱体", None
    pc = np.concatenate([[o[0]], c[:-1]])
    atr = KS.atr14(h, l_, c, pc)
    bx = KS.seg_boxes(o, h, l_, c, atr)
    if not bx:
        return "无箱体", None
    s, e, R, S = bx[-1][:4]
    if e >= len(c) - 3:
        if R <= S:
            return "无箱体", None
        pos = (px - S) / (R - S) * 100
        lab = "越上沿" if pos > 100 else "越下沿" if pos < 0 else "上沿" if pos > 75 else "下沿" if pos < 25 else "中部"
        return lab, round(pos)
    return ("已离箱向上" if px > R else "已离箱向下" if px < S else "回到旧箱内"), None


def regime(idx_pct, ztn):
    a = "强" if idx_pct > 0.5 else "弱" if idx_pct < -0.5 else "平"
    b = "冷" if ztn < 50 else "热" if ztn >= 100 else "中"
    return f"{a}·{b}"


def market_days(d0):
    """{日: (上证涨跌%, 全市场涨停家数)}(主板 + 创业板, 非 ST, 10cm / 20cm)"""
    c = cur()
    c.execute("select trade_date, close, pre_close from investment_market.kline_day where symbol='sh000001' and is_deleted=0 and trade_date>=%s", (d0,))
    idx = {str(d): (float(cl) / float(pc) - 1) * 100 for d, cl, pc in c.fetchall() if cl and pc}
    c.execute("select k.trade_date, sum(case when k.close >= round(k.pre_close * (case when k.symbol like 'sz30%%' or k.symbol like 'sh68%%' then 1.2 else 1.1 end), 2) - 0.005 then 1 else 0 end) "
              "from investment_market.kline_day k join investment_market.security_master s on s.symbol=k.symbol and s.sec_type='STOCK' and s.name not like '%%ST%%' "
              "where k.is_deleted=0 and k.trade_date>=%s and k.pre_close>0 and (k.symbol like 'sh6%%' or k.symbol like 'sz0%%' or k.symbol like 'sz3%%') group by k.trade_date", (d0,))
    zt = {str(d): int(n or 0) for d, n in c.fetchall()}
    return {d: (idx.get(d, 0.0), zt.get(d, 0)) for d in idx}


def build():
    import board_entry as BE
    import mentors as MT
    import theme_life as TL
    names = {}
    try:
        names = {e["id"]: e.get("display") or e.get("name") or e["id"] for e in MT.all()}
    except Exception:   # noqa: BLE001
        pass
    c = cur()
    c.execute("select ledger, date(record_time), time(record_time), stock_code, stock_name, side, price, qty from investment_tool.tzzb_record "
              "where record_type='bs_leg' and is_deleted=0 order by record_time")
    legs = collections.defaultdict(list)   # (导师, 代码) → [(日, 时, 买卖, 价, 量)]
    ev = {}
    for led, d, t, code, nm, sd, px, q in c.fetchall():
        code = str(code or "")
        if len(code) != 6 or code[:1] not in "036" or not px or not q:
            continue
        d, t, buy = str(d), str(t).zfill(8)[:5], "买" in str(sd)
        legs[(led, code)].append((d, t, buy, float(px), float(q)))
        if buy:
            e = ev.setdefault((led, d, code), {"skill": led, "d": d, "code": code, "name": nm or "", "t": t, "v": 0.0, "q": 0.0})
            e["v"] += float(px) * float(q)
            e["q"] += float(q)
    E = list(ev.values())
    print(f"买入事件 {len(E)} 个, {len({e['skill'] for e in E})} 个账本")
    d0 = min(e["d"] for e in E)
    M = market_days((dt.date.fromisoformat(d0) - dt.timedelta(days=10)).isoformat())
    mdays = sorted(M)
    by = collections.defaultdict(list)
    for e in E:
        by[e["code"]].append(e)
    out = []
    for n_, (code, es) in enumerate(by.items()):
        c.execute("select trade_date, open, high, low, close, pre_close from investment_market.kline_day where symbol=%s and is_deleted=0 and trade_date>=%s order by trade_date",
                  (BE.sym(code), (dt.date.fromisoformat(min(e["d"] for e in es)) - dt.timedelta(days=260)).isoformat()))
        K = [(str(a), *(float(x or 0) for x in r)) for a, *r in c.fetchall()]
        if not K:
            continue
        ix = {k[0]: i for i, k in enumerate(K)}
        A = np.array([k[1:] for k in K])
        lim = BE.lim(code, es[0]["name"])
        for e in es:
            i = ix.get(e["d"])
            if i is None or i < 1 or not e["q"]:
                continue
            px = e["v"] / e["q"]
            o, h, l_, cl, pc = K[i][1:]
            if not pc:
                continue
            board, _ = BE.classify(code, e["name"], (o, h, l_, cl, pc, e["d"]), K[i - 1][1:] if K[i - 1][5] and K[i - 1][4] else None, e["t"], px)
            lo = max(0, i - 160)
            bl, bv = box_pos(A[lo:i, 0], A[lo:i, 1], A[lo:i, 2], A[lo:i, 3], px)
            hgt = 0
            for j in range(i - 1, max(-1, i - 15), -1):
                if K[j][4] >= round(K[j][5] * (1 + lim) + 1e-9, 2) - 0.005:
                    hgt += 1
                else:
                    break
            amp = [(K[j][2] - K[j][3]) / K[j][5] * 100 for j in range(max(0, i - 30), i) if K[j][5]]
            X = round(st.median(amp), 2) if amp else 5.0
            pd_ = mdays[max(0, mdays.index(e["d"]) - 1)] if e["d"] in M else None
            ip, zn = M.get(pd_, (0.0, 0)) if pd_ else (0.0, 0)
            r = {"id": f"{e['skill']}:{e['d']}:{code}", "skill": e["skill"], "mentor": names.get(e["skill"], e["skill"]), "d": e["d"], "t": e["t"], "code": code, "name": e["name"],
                 "px": round(px, 3), "board": board, "box": bl, "box_pos": bv, "h": "3+" if hgt >= 3 else str(hgt), "mkt": regime(ip, zn), "X": X,
                 "r0": round((cl / px - 1) * 100, 2)}
            hit, have = False, 0
            for k in (1, 2, 3):
                if i + k < len(K):
                    have = k
                    r[f"h{k}"] = round((K[i + k][2] / px - 1) * 100, 2)
                    r[f"c{k}"] = round((K[i + k][4] / px - 1) * 100, 2)
                    hit = hit or r[f"h{k}"] >= X
            r["label"] = "正" if hit else ("负" if r.get("c3", 0) < 0 else "平") if have == 3 else f"待核{3 - have}"
            sells = [x for x in legs[(e["skill"], code)] if not x[2] and (x[0], x[1]) >= (e["d"], e["t"])]
            if sells:
                s0 = sells[0]
                k = sum(1 for x in K[i:] if x[0] <= s0[0]) - 1
                pnl = (s0[3] / px - 1) * 100
                r["exit"] = "当天卖(T)" if k == 0 else f"T+{k} {'盈利' if pnl >= 0 else '亏损'}卖" if k <= 3 else "拿着(3 天后才卖)"
                r["exit_pnl"] = round(pnl, 2)
            else:
                r["exit"] = "拿着(还没卖)"
            out.append(r)
        if n_ % 200 == 0:
            print(f"  {n_}/{len(by)} 只票", flush=True)
    th = {}
    for r in out:   # 题材(慢, 按 (名, 日) 缓存)
        k = (r["name"], r["d"])
        if k not in th:
            try:
                th[k] = next(iter(TL.by_stock(r["name"], r["d"]).get("近 20 个交易日挂过的题材") or {}), None)
            except Exception:   # noqa: BLE001
                th[k] = None
        r["theme"] = th[k]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
    write_md(out)
    print(f"→ {OUT} {len(out)} 个样例")


def load():
    return [json.loads(l) for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()] if OUT.exists() else []


def dist(xs, k):
    v = sorted(((x[k], x) for x in xs if x.get(k) is not None), key=lambda p: p[0])
    if not v:
        return "-"
    a = [p for p, _ in v]
    return (f"中{a[len(a) // 2]:+.2f} 均{st.mean(a):+.2f} P10 {a[int(len(a) * .1)]:+.2f} P90 {a[min(len(a) - 1, int(len(a) * .9))]:+.2f} "
            f"最差{a[0]:+.2f}({v[0][1]['mentor']} {v[0][1]['name']} {v[0][1]['d'][5:]}) 最好{a[-1]:+.2f}({v[-1][1]['mentor']} {v[-1][1]['name']} {v[-1][1]['d'][5:]})")


def pnf(xs):
    n = collections.Counter(x["label"][:2] for x in xs)
    done = n["正"] + n["负"] + n["平"]
    return f"{len(xs)} 笔 · 正 {n['正']} / 负 {n['负']} / 平 {n['平']} / 待核 {n['待核']}" + (f" · 正率 {n['正'] / done:.0%} 负率 {n['负'] / done:.0%}" if done else "")


def write_md(R):
    L = [f"# 样例库（{dt.date.today()} 重算；{len(R)} 个买入样例，{len({r['skill'] for r in R})} 个账本，停更 / 负收益的都在）", "",
         "> 脚本 `scripts/ontology/sample_lib.py`（零 token）。正 = T+1~T+3 任一天最高 ≥ 买价 +X%（X = 这只票前 30 日振幅中位）；负 = 3 天都没冲到且 T+3 收盘 < 买价；平 = 其余；待核 n = 还差 n 天行情。",
         "> 板型买点用的是买入当天全天走势（事后分类，不是盘中信号）。数据只有同花顺账本逐笔（股票）；你的实盘样例另放隐私区，live line 计划核销样例周一起接。", "",
         "## 各导师", "", "| 导师 | 样例 | T+1 收盘 | T+1~3 最高的最大值 |", "|---|---|---|---|"]
    by = collections.defaultdict(list)
    for r in R:
        by[r["mentor"]].append(r)
    for m, xs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        for x in xs:
            x["hmax"] = max([x.get(f"h{k}") for k in (1, 2, 3) if x.get(f"h{k}") is not None] or [None]) if any(x.get(f"h{k}") is not None for k in (1, 2, 3)) else None
        L.append(f"| {m} | {pnf(xs)} | {dist(xs, 'c1')} | {dist(xs, 'hmax')} |")
    for title, key in (("板型买点", "board"), ("箱体位置", "box"), ("连板高度", "h"), ("市况（T−1 上证 × 涨停家数）", "mkt"), ("实际怎么出的", "exit")):
        g = collections.defaultdict(list)
        for r in R:
            g[r.get(key)].append(r)
        L += ["", f"## {title}", "", "| 档 | 样例 | T+1 收盘 |", "|---|---|---|"]
        for k, xs in sorted(g.items(), key=lambda kv: -len(kv[1])):
            L.append(f"| {k} | {pnf(xs)} | {dist(xs, 'c1')} |")
    MD.write_text("\n".join(L) + "\n", encoding="utf-8")


def like(board=None, box=None, h=None, mkt=None, skill=None, R=None, n_show=8):
    """跨账本相似查询: 四维(板型买点 × 箱体位置 × 连板高度 × 市况), 给了几维按几维匹配; → 文本"""
    R = R if R is not None else load()
    xs = [r for r in R if (not board or r["board"] == board) and (not box or r["box"] == box) and (not h or r["h"] == str(h)) and (not mkt or r["mkt"] == mkt)
          and (not skill or r["skill"] == skill)]
    key = " × ".join(f"{a}={b}" for a, b in (("板型", board), ("箱体", box), ("连板", h), ("市况", mkt), ("导师", skill)) if b)
    if not xs:
        return f"同类样例({key}): 0 笔"
    bym = collections.Counter(x["mentor"] for x in xs)
    L = [f"同类样例({key}): {pnf(xs)}", f"- 哪些导师: " + "、".join(f"{m} {n}" for m, n in bym.most_common(10)),
         f"- T+0 收盘 {dist(xs, 'r0')}", f"- T+1 收盘 {dist(xs, 'c1')}", f"- T+1 最高 {dist(xs, 'h1')}", f"- T+3 收盘 {dist(xs, 'c3')}",
         "- 实际怎么出的: " + "、".join(f"{k} {v}" for k, v in collections.Counter(x["exit"] for x in xs).most_common(6))]
    neg = [x for x in xs if x["label"] == "负"]
    pos = [x for x in xs if x["label"] == "正"]
    for lab, ys in (("负样例", sorted(neg, key=lambda x: x.get("c3", 0))[:n_show // 2]), ("正样例", sorted(pos, key=lambda x: -(x.get("h1") or 0))[:n_show // 2])):
        for y in ys:
            L.append(f"  · {lab} {y['mentor']} {y['d']} {y['t']} {y['name']}({y['code']}) 买 {y['px']} · T+0 {y['r0']:+.1f} / T+1 高 {y.get('h1', '-')} 收 {y.get('c1', '-')} / T+3 收 {y.get('c3', '-')} · {y['exit']}")
    return "\n".join(L)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "like", "like-id"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--skill", default=None)
    a = ap.parse_args()
    if a.cmd == "build":
        build()
    elif a.cmd == "like":
        v = (a.args + [None] * 4)[:4]
        print(like(*[x if x not in ("-", "*", "") else None for x in v], skill=a.skill))
    else:
        R = load()
        r = next((x for x in R if x["id"] == a.args[0]), None)
        if not r:
            return print("没有这个样例 id")
        print(f"样例 {r['id']}: {r['board']} · 箱体 {r['box']} · 连板 {r['h']} · 市况 {r['mkt']} → {r['label']}")
        print(like(r["board"], r["box"], r["h"], r["mkt"], R=R))


if __name__ == "__main__":
    main()
