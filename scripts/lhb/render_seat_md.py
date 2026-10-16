# -*- coding: utf-8 -*-
"""render_seat_md.py — seat_profile.json(+seat_style.json) → docs/research/lhb_seat_profile_20261015.md(零 token; 2026-10-15 建)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/lhb/render_seat_md.py [--out docs/research/xxx.md]
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def f(v, pct=True):
    if v is None:
        return "-"
    return f"{v:+.2f}%" if pct else f"{v}"


def boards(b):
    return "、".join(f"{x}({n})" for x, n in b) or "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/research/lhb_seat_profile_20261015.md")
    a = ap.parse_args()
    j = json.loads((ROOT / "scripts/lhb/seat_profile.json").read_text(encoding="utf-8"))
    sf = ROOT / "scripts/lhb/seat_style.json"
    st = json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else {"style": {}, "cost_usd": 0}
    S = st["style"]
    L = [f"# 龙虎榜游资席位画像({j['range'][0]} ~ {j['range'][1]})", "",
         f"> 生成: {j['generated_at']} · 脚本 `scripts/lhb/seat_profile.py`(零 token 统计) + `scripts/lhb/seat_style_llm.py`(只写\"风格一句话\", 1 个 claude -p, 官方价 ${st.get('cost_usd', 0):.2f}) + `scripts/lhb/render_seat_md.py`",
         f"> 全量数据: `scripts/lhb/seat_profile.json`(全部 {j['seat_count']} 个席位, 含小样本); 原始: downloads/lhb/(427 天 json) + 行情库 kline_day(只读)", "",
         "## 数据量与口径", "",
         f"- 交易日 {j['trading_days']} 天, 上榜 {j['stock_days']} 只次; 出现过的席位 {j['seat_count']} 个(按东财营业部编码归并更名, 如 国泰君安→国泰海通), 有净买入上榜的 {j['seats_with_buy']} 个, 其中 ≥5 次的 {j['seats_ge5']} 个(<5 次归\"小样本\", 只在 json 里)",
         f"- K 线覆盖 {j['kline_coverage'][0]}/{j['kline_coverage'][1]} 只(缺的是转债/北交所 2026-10-09 前/退市股, 这些事件不计收益, 只计次数)", "",
         "```", j["definitions"], "```", "",
         "## 基准(先看这个: 打板票次日天然有溢价)", "",
         "| 口径 | 只次 | T+1 开盘均 | T+1 收盘均 | T+1 收盘中位 | T+1 收红率 | T+3 均 | T+3 中位 |", "| :-- | --: | --: | --: | --: | --: | --: | --: |"]
    for k, v in j["baseline"].items():
        L.append(f"| {k} | {v['buy_n']} | {f(v['o1_mean'])} | {f(v['c1_mean'])} | {f(v['c1_median'])} | {v['red1_rate']}% | {f(v['c3_mean'])} | {f(v['c3_median'])} |")
    L += ["", "解读: 席位的 T+1 溢价要和同类基准比——\"同类超额\"一列已扣掉(T 日涨停桶基准 +2.02%, 非涨停桶 -1.21%)。", "",
          "## 拉萨天团 / 机构 / 北向 整体", "",
          "组内同票同日合并成一个事件(组净额 > 0 才算买入)。拉萨天团=youzi.json 里别名为拉萨天团的 5 个东财拉萨营业部(山南/昌都/拉萨东城区江苏大道等其他东财西藏营业部未计入, 单独在下表)。", "",
          "| 组 | 买入次数 | T+1 开盘 均/中 | T+1 收盘 均/中 | 收红率 | T+3 均/中 | 同类超额 | 涨停占比 | 常做行业 | 风格一句话 |",
          "| :-- | --: | :--: | :--: | --: | :--: | --: | --: | :-- | :-- |"]
    for g, v in j["groups"].items():
        L.append(f"| {g} | {v['buy_n']} | {f(v['o1_mean'])} / {f(v['o1_median'])} | {f(v['c1_mean'])} / {f(v['c1_median'])} | {v['red1_rate']}% | "
                 f"{f(v['c3_mean'])} / {f(v['c3_median'])} | {f(v['c1_excess_mean'])} | {v['limitup_rate']}% | {boards(v['top_boards'])} | {S.get('group:' + g, '-')} |")
    L += ["", "## 知名游资(youzi.json 别名, 同别名多席位合并、同票同日去重)", "",
          "| 别名 | 席位 | 买入次数 | T+1 开盘 均/中 | T+1 收盘 均/中 | 收红率 | T+3 均/中 | 同类超额 | 涨停占比 | 常做行业 | 风格一句话 |",
          "| :-- | :-- | --: | :--: | :--: | --: | :--: | --: | --: | :-- | :-- |"]
    for al, v in sorted(j["aliases"].items(), key=lambda x: -x[1]["buy_n"]):
        tag = "(小样本)" if v["small_sample"] else ""
        L.append(f"| {al}{tag} | {' / '.join(v['seats'])} | {v['buy_n']} | {f(v['o1_mean'])} / {f(v['o1_median'])} | {f(v['c1_mean'])} / {f(v['c1_median'])} | "
                 f"{v['red1_rate'] if v['red1_rate'] is not None else '-'}% | {f(v['c3_mean'])} / {f(v['c3_median'])} | {f(v['c1_excess_mean'])} | {v['limitup_rate']}% | {boards(v['top_boards'])} | {S.get('alias:' + al, '-')} |")
    top = [s for s in j["seats"] if s["kind"] == "营业部"][:50]
    L += ["", "## 前 50 活跃营业部(按净买入上榜次数; 机构专用/北向/占位码不在此表)", "",
          "| # | 席位 | 别名 | 买入 | T+1 开盘 均/中 | T+1 收盘 均/中 | 收红率 | T+3 均/中 | 同类超额 | 涨停占比 | 快卖率 | 均净买 | 常做行业 | 风格一句话 |",
          "| --: | :-- | :-- | --: | :--: | :--: | --: | :--: | --: | --: | --: | --: | :-- | :-- |"]
    for i, s in enumerate(top, 1):
        L.append(f"| {i} | {s['short']} | {s['alias'] or '-'} | {s['buy_n']} | {f(s['o1_mean'])} / {f(s['o1_median'])} | {f(s['c1_mean'])} / {f(s['c1_median'])} | "
                 f"{s['red1_rate']}% | {f(s['c3_mean'])} / {f(s['c3_median'])} | {f(s['c1_excess_mean'])} | {s['limitup_rate']}% | {s['quick_sell_rate']}% | "
                 f"{s['avg_net_buy_wan']:.0f}万 | {boards(s['top_boards'])} | {S.get(s['key'], '-')} |")
    big = [s for s in j["seats"] if s["kind"] == "营业部" and s["n_ret1"] >= 30 and s["c1_excess_mean"] is not None]
    for title, rows in (("同类超额最高 15 个营业部(T+1 有收益样本 ≥30)", sorted(big, key=lambda s: -s["c1_excess_mean"])[:15]),
                        ("同类超额最低 10 个营业部(T+1 有收益样本 ≥30)", sorted(big, key=lambda s: s["c1_excess_mean"])[:10])):
        L += ["", f"## {title}", "", "| 席位 | 别名 | 买入 | T+1 收盘 均/中 | 收红率 | T+3 均 | 同类超额 | 涨停占比 | 常做行业 |", "| :-- | :-- | --: | :--: | --: | --: | --: | --: | :-- |"]
        for s in rows:
            L.append(f"| {s['short']} | {s['alias'] or '-'} | {s['buy_n']} | {f(s['c1_mean'])} / {f(s['c1_median'])} | {s['red1_rate']}% | {f(s['c3_mean'])} | "
                     f"{f(s['c1_excess_mean'])} | {s['limitup_rate']}% | {boards(s['top_boards'])} |")
    L += ["", f"(≥30 样本的营业部共 {len(big)} 个; 多重比较: 从几百个席位里挑最高的, 头部有相当部分是运气, 样本外要再验)", "",
          "## 不自信点", "",
          "1. 基准价用 T 收盘: 席位真实成本未知(盘中低吸的票成本低于收盘, 溢价被低估; 尾盘拉升的被高估), \"溢价\"是\"收盘后跟进者\"视角, 不是席位自己的收益。",
          "2. 只看得到上榜那天的买五/卖五: 席位没上榜的买卖、上榜后哪天卖都看不到; 快卖率只是下界(卖出那天没上榜就看不到)。",
          "3. 行业用 10/15 的东财行业快照(当前行业, 非上榜时点; 个别票期间改过行业会错), 转债/退市股无行业; 题材(概念)没做——本地没有逐日题材归属, 需另抓。",
          "4. 游资别名只有 youzi.json 收录的 27 个简称(本次按营业部编码把同编码历史名一并算进去, 如 中国银河 绍兴→绍兴鲁迅中路 算赵老哥); 未收录的知名游资就按营业部原名出现在表里, 别名列为 -。",
          "5. 427 天单一行情段(2025-01~2026-10), 市况分段没做; 多重比较下\"超额最高\"榜单有幸存/运气成分, 不是可直接跟的名单。",
          "6. 风格一句话是 LLM 根据本表数字归纳的(不看原始数据), 只作阅读辅助; 数字以表为准。", ""]
    out = ROOT / a.out
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"写 {a.out}: {len(L)} 行, 前 50 表 {len(top)} 行")


if __name__ == "__main__":
    main()
