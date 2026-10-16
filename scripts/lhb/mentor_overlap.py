# -*- coding: utf-8 -*-
"""mentor_overlap.py — 同花顺导师真实买入 × 龙虎榜席位 对照(零 token; 2026-10-15 建)
输入(只读, 零请求): downloads/tzzb/<ledger>/ (scripts/tzzb/tzzb_ledgers.json 里 kind≠neg 的正样本)
       + downloads/lhb/(lhb_lib 读, 口径同 seat_profile: 主记录买五且净额>0=该席位买入)
导师买入口径:
  来源 = position_change_p*.json 的 ex_data.change_list ∪ change_bs_*.json(逐笔腿)——两者都读、按 (日期, 代码) 去重
  (实测: 不吃土豆0 的 position_change 只有 1 条买入, 逐笔腿里才全; 两融账户的 252 融资买/235 担保品买也是买, 同 gen_tzzb_md normOp)
  买入事件 = (交易日 T, 代码) 一对(同日多笔算一次); 只统计 T 落在龙虎榜数据覆盖区间内的
对照:
  当日上榜 = T 当日该票在龙虎榜; 前一日上榜 = T 的上一个交易日该票在龙虎榜(=导师可能是看了龙虎榜去买)
  同向席位 = T 当日该票龙虎榜上净买入的席位; 统计 机构 / 拉萨天团(youzi 别名) / 知名游资(youzi 其他别名) / 北向 同向的比例
  反向 = 同组在 T 当日净卖出
  市场基准上榜率 = 同期每天上榜只数 / 当天有日线的 A 股只数(行情库 kline_day 只读)的均值——用来看"导师选的票是不是比随便选更常上榜"
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/lhb/mentor_overlap.py
产物: scripts/lhb/mentor_overlap.json + docs/research/lhb_mentor_overlap_20261015.md
"""
import datetime as dt
import glob
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lhb"))
import lhb_lib as L  # noqa: E402

OUT_J = ROOT / "scripts" / "lhb" / "mentor_overlap.json"
OUT_M = ROOT / "docs" / "research" / "lhb_mentor_overlap_20261015.md"


def norm_op(t):
    op, bs = str(t.get("op")), str(t.get("buy_sell"))
    if op in ("1", "2"):
        return op
    if bs in ("1", "3", "7"):
        return "1"
    if bs in ("2", "4", "8"):
        return "2"
    return "1" if op in ("252", "235") else "2" if op == "256" else op


def mentor_buys(ledger):
    d = ROOT / "downloads" / "tzzb" / ledger
    ev = {}
    src = Counter()
    for pat, tag in (("position_change_p*.json", "position_change"), ("change_bs_*.json", "change_bs")):
        for f in glob.glob(str(d / pat)):
            try:
                lst = json.loads(Path(f).read_text(encoding="utf-8")).get("ex_data", {}).get("change_list") or []
            except ValueError:
                continue
            for t in lst:
                if norm_op(t) != "1" or not t.get("trans_date") or not t.get("stock_code"):
                    continue
                k = (t["trans_date"][:10], t["stock_code"])
                src[tag] += 1
                ev.setdefault(k, {"date": k[0], "code": k[1], "name": t.get("stock_name"), "src": set()})["src"].add(tag)
    return list(ev.values()), src


def main():
    ledgers = [l for l in json.loads((ROOT / "scripts/tzzb/tzzb_ledgers.json").read_text(encoding="utf-8")) if l.get("kind") != "neg"]
    days = list(L.iter_days())
    dates = [d for d, _ in days]
    prev_of = {dates[i]: dates[i - 1] for i in range(1, len(dates))}
    lhb = {}                     # (date, code) -> stock
    for d, stocks in days:
        for s in stocks:
            lhb[(d, s["code"])] = s
    # 市场基准上榜率: 每天上榜只数 / 当天有日线的 A 股只数
    import pymysql
    c = pymysql.connect(host="localhost", user="root", password="root", database="investment_market", charset="utf8mb4")
    cur = c.cursor()
    cur.execute("select trade_date, count(*) from kline_day where trade_date >= %s and is_deleted = 0 and (symbol like 'sh6%%' or symbol like 'sz0%%' "
                "or symbol like 'sz3%%' or symbol like 'bj%%') group by trade_date", (dates[0],))
    ncount = {r[0].isoformat(): r[1] for r in cur.fetchall()}
    c.close()
    lhb_n = Counter(d for d, _ in lhb)

    def cats(s, sign):
        """该上榜票当天各组同向(sign=1: 组净额>0 且有成员在买五净买)/反向(sign=-1: 组净额<0 且有成员在卖五净卖); 返回 set"""
        g = defaultdict(float)
        hit = defaultdict(bool)
        for x in s["seats"]:
            if x["is_jg"]:
                k = "机构"
            elif x["is_bx"]:
                k = "北向"
            else:
                a = key_alias.get(x["key"]) or L.YOUZI.get(x["short"])
                k = "拉萨天团" if a == "拉萨天团" else "知名游资" if a else None
            if not k:
                continue
            g[k] += x["net"]
            if (sign > 0 and x["in_buy5"] and x["net"] > 0) or (sign < 0 and x["in_sell5"] and x["net"] < 0):
                hit[k] = True
        return {k for k, v in g.items() if v * sign > 0 and hit[k]}

    # 同编码历史名命中别名(赵老哥 绍兴鲁迅中路等): 预先建 key→alias
    key_alias = {}
    for d, stocks in days:
        for s in stocks:
            for x in s["seats"]:
                if x["key"] not in key_alias or key_alias[x["key"]] is None:
                    key_alias[x["key"]] = L.alias_of([x["name"]])
    res = {"generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "lhb_range": [dates[0], dates[-1]], "mentors": []}
    CAT = ["机构", "拉萨天团", "知名游资", "北向"]
    for l in ledgers:
        evs, src = mentor_buys(l["ledger"])
        evs = [e for e in evs if dates[0] <= e["date"] <= dates[-1] and e["date"] in set(dates)]
        n = len(evs)
        if not n:
            res["mentors"].append({"ledger": l["ledger"], "name": l["name"], "buy_events": 0})
            continue
        on_t = on_prev = 0
        same = Counter()
        oppo = Counter()
        seat_same = Counter()
        seat_name = {}
        alias_same = Counter()
        examples = []
        base = []
        for e in sorted(evs, key=lambda e: e["date"]):
            d = e["date"]
            if ncount.get(d):
                base.append(lhb_n[d] / ncount[d])
            s = lhb.get((d, e["code"]))
            p = prev_of.get(d)
            if p and (p, e["code"]) in lhb:
                on_prev += 1
            if not s:
                continue
            on_t += 1
            cs = cats(s, 1)
            for k in cs:
                same[k] += 1
            for k in cats(s, -1):
                oppo[k] += 1
            buyers = [x for x in s["seats"] if x["in_buy5"] and x["net"] > 0]
            for x in buyers:
                if x["is_jg"] or x["is_bx"]:
                    continue
                seat_same[x["key"]] += 1
                seat_name[x["key"]] = x["short"]
                a = key_alias.get(x["key"])
                if a:
                    alias_same[a] += 1
            if len(examples) < 400:
                examples.append({"date": d, "code": e["code"], "name": s["name"], "chg": s["prim"].get("CHANGE_RATE"),
                                 "net_wan": round((s["prim"].get("BILLBOARD_NET_AMT") or 0) / 1e4), "same": sorted(cs),
                                 "buyers": [seat_name.get(x["key"], x["short"]) + (f"({key_alias[x['key']]})" if key_alias.get(x["key"]) else "")
                                            for x in sorted(buyers, key=lambda x: -x["net"])[:5]]})
        rate = lambda k: round(100 * k / n, 1)
        rate_t = lambda k: round(100 * k / on_t, 1) if on_t else None
        m = {"ledger": l["ledger"], "name": l["name"], "buy_events": n, "src_legs": dict(src),
             "range": [min(e["date"] for e in evs), max(e["date"] for e in evs)],
             "on_lhb_T": on_t, "on_lhb_T_pct": rate(on_t), "on_lhb_prev": on_prev, "on_lhb_prev_pct": rate(on_prev),
             "market_base_pct": round(100 * sum(base) / len(base), 2) if base else None,
             "same_dir": {k: {"n": same[k], "pct_of_buys": rate(same[k]), "pct_of_onlhb": rate_t(same[k])} for k in CAT},
             "opposite": {k: {"n": oppo[k], "pct_of_onlhb": rate_t(oppo[k])} for k in CAT},
             "top_seats_same": [[seat_name[k], key_alias.get(k), c] for k, c in seat_same.most_common(10)],
             "alias_same": alias_same.most_common(), "examples_on_lhb": examples}
        res["mentors"].append(m)
        print(f"{l['name']}: 买入 {n}, 当日上榜 {on_t}({m['on_lhb_T_pct']}%), 前日上榜 {on_prev}({m['on_lhb_prev_pct']}%), 基准 {m['market_base_pct']}%", flush=True)
    OUT_J.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    render(res)


def render(res):
    M = [m for m in res["mentors"]]
    L2 = [f"# 同花顺导师买入 × 龙虎榜席位 对照(龙虎榜 {res['lhb_range'][0]} ~ {res['lhb_range'][1]})", "",
          f"> 生成: {res['generated_at']} · 脚本 `scripts/lhb/mentor_overlap.py`(零 token) · 全量 `scripts/lhb/mentor_overlap.json`(含每次上榜买入的明细, 每人最多 400 条)", "",
          "## 口径", "", "```", __doc__.split("导师买入口径:")[1].split("用法:")[0].strip(), "```", "",
          "## 总表", "",
          "| 导师 | 数据区间 | 买入事件 | T日上榜 | 前一日上榜 | 市场基准上榜率 | 上榜倍数 | 机构同向 | 拉萨天团同向 | 知名游资同向 | 北向同向 | 拉萨天团反向 |",
          "| :-- | :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: |"]
    for m in M:
        if not m["buy_events"]:
            L2.append(f"| {m['name']} | - | 0 | - | - | - | - | - | - | - | - | - |")
            continue
        sd, op = m["same_dir"], m["opposite"]
        mult = round(m["on_lhb_T_pct"] / m["market_base_pct"], 1) if m["market_base_pct"] else "-"
        cell = lambda k: f"{sd[k]['n']}({sd[k]['pct_of_onlhb']}%)" if m["on_lhb_T"] else "0"
        L2.append(f"| {m['name']} | {m['range'][0]}~{m['range'][1]} | {m['buy_events']} | {m['on_lhb_T']}({m['on_lhb_T_pct']}%) | {m['on_lhb_prev']}({m['on_lhb_prev_pct']}%) | "
                  f"{m['market_base_pct']}% | {mult}× | {cell('机构')} | {cell('拉萨天团')} | {cell('知名游资')} | {cell('北向')} | "
                  f"{op['拉萨天团']['n']}({op['拉萨天团']['pct_of_onlhb']}%) |" if m["on_lhb_T"] else
                  f"| {m['name']} | {m['range'][0]}~{m['range'][1]} | {m['buy_events']} | 0(0%) | {m['on_lhb_prev']}({m['on_lhb_prev_pct']}%) | {m['market_base_pct']}% | 0× | 0 | 0 | 0 | 0 | 0 |")
    L2 += ["", "列说明: 买入事件=(交易日, 代码)去重; T日上榜/前一日上榜 括号=占买入事件%; 上榜倍数=T日上榜率 ÷ 市场基准上榜率(>1=导师选的票比随机选更常上榜, 即偏龙虎榜活跃票);",
           "同向/反向 括号=占\"T日上榜的买入事件\"%(同一事件可多组同向)。", ""]
    for m in M:
        L2 += [f"## {m['name']}({m['ledger']})", ""]
        if not m["buy_events"]:
            L2 += ["龙虎榜覆盖区间内无买入记录。", ""]
            continue
        sd, op = m["same_dir"], m["opposite"]
        L2.append(f"- 数据: {m['range'][0]}~{m['range'][1]}, 买入事件 {m['buy_events']}(原始腿: {', '.join(f'{k} {v}' for k, v in m['src_legs'].items())})")
        L2.append(f"- 当日上榜 {m['on_lhb_T']} 次({m['on_lhb_T_pct']}%, 市场基准 {m['market_base_pct']}%); 前一日上榜后买入 {m['on_lhb_prev']} 次({m['on_lhb_prev_pct']}%)")
        if m["on_lhb_T"]:
            L2.append("- 同向(当日上榜事件中): " + " · ".join(f"{k} {sd[k]['n']}({sd[k]['pct_of_onlhb']}%)" for k in sd)
                      + "; 反向(净卖): " + " · ".join(f"{k} {op[k]['n']}({op[k]['pct_of_onlhb']}%)" for k in op))
            L2.append("- 同日同向次数最多的营业部: " + ("、".join(f"{s}{'(' + a + ')' if a else ''}×{c}" for s, a, c in m["top_seats_same"]) or "无"))
            if m["alias_same"]:
                L2.append("- 有别名的同向营业部(按席位人次, 拉萨天团 5 个席位分别计): " + "、".join(f"{a}×{c}" for a, c in m["alias_same"]))
            ex = m["examples_on_lhb"][-8:]
            L2 += ["", "最近的当日上榜买入(最多 8 条):", "", "| 日期 | 股票 | 涨跌 | 榜净额 | 同向组 | 净买前五营业部 |", "| :-- | :-- | --: | --: | :-- | :-- |"]
            for e in ex:
                L2.append(f"| {e['date']} | {e['name']} {e['code']} | {e['chg']:+.2f}% | {e['net_wan']}万 | {'/'.join(e['same']) or '-'} | {' / '.join(e['buyers']) or '-'} |")
        L2.append("")
    L2 += ["## 不自信点", "",
           "1. 导师成交来自同花顺投资账本公开流水: 手录账户(00:00:00)、分页截断(gen_tzzb_md 有哨兵)会漏腿; position_change 与 change_bs 两源合并去重, 仍可能少。",
           "2. \"同向\"只是同一天同一只票都在买, 不代表跟随或抱团(导师多为小资金, 不会出现在买五里); 龙虎榜只露买五卖五, 没上榜的游资动向看不到。",
           "3. 市场基准上榜率=当天上榜只数/当天有日线的 A 股数(含转债的上榜被算进分子, 分母只有股票, 基准略偏高); 转债导师(不吃土豆0)的票大多不在龙虎榜口径内, 低上榜率不代表不跟游资。",
           "4. 各导师数据区间不同(多为 2025-09 / 2026-01 以后), 样本量差异大, 不同导师之间的比例只能粗比。",
           "5. 知名游资只认 youzi.json 收录的别名(按营业部编码把历史更名一起算), 未收录的游资归在营业部名里。", ""]
    OUT_M.write_text("\n".join(L2), encoding="utf-8")
    print(f"写 {OUT_M.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
