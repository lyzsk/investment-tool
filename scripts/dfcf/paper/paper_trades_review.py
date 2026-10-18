# -*- coding: utf-8 -*-
"""paper_trades_review.py — 给人工审核用: 指定几本 paper 账本, 逐日列出挂单和成交(时间 / 价格 / 股票名 / 数量 / 占净值仓位 / 成交方式)(10/18 用户要; 零 token, 只读)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/paper_trades_review.py --books A-xingjianye,A-stzhilang,A-qushitiange,A-control --out docs/review/paper_top3_20261018.md
"""
import argparse
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def fill_kind(why):
    w = why or ""
    if w.startswith("分钟回放"):
        m = re.search(r"@\S+ (\d\d:\d\d)", w)
        return f"分钟回放 {m.group(1) if m else ''}".strip(), "回放(分钟线)"
    if w.startswith("回放成交"):
        return "日线回放估算", "回放估算(日线, 偏乐观)"
    if w.startswith("止损哨兵"):
        return "止损哨兵触发", "实盘撮合"
    if "≤挂" in w or "≥挂" in w or "现价" in w:
        return "实盘撮合(时刻未记录)", "实盘撮合"
    return w[:20], "其他"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    names = json.loads((HERE / "names.json").read_text(encoding="utf-8")) if (HERE / "names.json").exists() else {}
    L = ["# paper 账本逐日挂单与成交（人工审核用）", "",
         "> 来源：`scripts/dfcf/paper/books/<账本>.json`，零 token 机械导出（`scripts/dfcf/paper/paper_trades_review.py`）。",
         "> 「挂单时刻」= 哪个时段的链下的单（0915 = 盘前全链；其余 = 盘中子链）。",
         "> 「成交方式」：**实盘撮合** = 盘中按实时价成交（成交时刻当时没记录，只知道在挂单之后）；**分钟回放** = 事后按分钟线补算；**日线回放估算** = 只用日线高低判断碰没碰到价，偏乐观。",
         "> 「仓位」= 成交金额 ÷ 前一日收盘净值。", "> ⚠ 10/16 这一天已被 as-of 重跑结果替换（重跑时读到了 10/16 收盘后才蒸馏的画像，你 10/17 定：不处理），审核时注意。", ""]
    for bk in a.books.split(","):
        b = json.loads((HERE / "books" / f"{bk}.json").read_text(encoding="utf-8"))
        nav = {n["date"]: n["nav"] for n in b.get("nav") or []}
        days = sorted(nav)
        om = {o["id"]: o for o in b.get("orders") or []}
        tm = {t["id"]: t for t in b.get("trades") or []}
        first = days[0] if days else ""
        L += [f"## {bk}（{first} 起；最新净值 {nav[days[-1]]:,.0f}，{nav[days[-1]] / 100000 - 1:+.2%}）", ""]
        L += ["| 日期 | 挂单时刻 | 方向 | 股票 | 挂单价 | 数量 | 状态 | 成交价 | 仓位 | 成交方式 | 链给的理由（截断） |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for o in sorted(b.get("orders") or [], key=lambda x: (x["date"], x.get("time", ""), x["id"])):
            d = o["date"]
            prev = max([x for x in days if x < d], default=None)
            base = nav.get(prev) or 100000
            t = tm.get(o["id"])
            px = t["price"] if t else o.get("fillPrice")
            pos = f"{px * o['qty'] / base:.0%}" if px else ""
            how = fill_kind((t or {}).get("why") or o.get("fillWhy"))[0] if (t or o.get("fillPrice")) else ""
            st = {"filled": "成交", "open": "未成交", "expired": "过期未成", "cancelled": "撤单", "voided": "作废", "blocked": "被拦", "reject": "被拒(资金/持仓/T+1)", "invalid": "无效(价格锚/一字/越界)"}.get(o.get("status"), o.get("status"))
            nm = names.get(o["code"], "")
            note = re.sub(r"\s+", " ", o.get("note") or "")[:70].replace("|", "/")
            L.append(f"| {d[5:]} | {o.get('time', '')} | {'买' if o['side'] == 'BUY' else '卖'} | {nm}({o['code']}) | {o.get('price')} | {o['qty']} | {st} | {px or ''} | {pos} | {how} | {note} |")
        L.append("")
        L += ["每日净值：" + "；".join(f"{d[5:]} {nav[d]:,.0f}" for d in days), ""]
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"→ {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
