# -*- coding: utf-8 -*-
"""fee_profile.py — 从导师自己的成交记录反推他的券商费率(10/18, 用户问"不同券商手续费不一样, 别人的怎么推"; 零 token, 只读)

原理: 同花顺投资账本每笔成交有 成交价 / 成交量 / 成交金额(trans_amount, 已含费用):
  买入: 金额 − 价×量 = 佣金(+ 过户费)            → 佣金率 = 差额 / (价×量)
  卖出: 价×量 − 金额 = 佣金 + 印花税(股票卖出 0.05%)
  只用 A 股股票(代码 0/3/6 开头)、成交额 > 2 万的单算费率(避开最低收费干扰); 小单(< 1 万)的最低差额判断有没有"最低 5 元"
产物: scripts/tzzb/fee_profile.json  {ledger: {buy_rate, min_fee, sell_rate_incl_stamp, n_buy, n_sell, note}}
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/fee_profile.py [--show]
消费方(待接): 混合账本"买单命中率"改"扣费净收益"(审计④ R16), 导师真人的扣费收益统计; 链的模拟撮合仍按 a_rules 缺省(万 2.5, 最低 5 元)
"""
import argparse
import glob
import json
import os
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_name("fee_profile.json")
STAMP = 0.0005


def infer(led_dir):
    buys, sells = [], []
    for f in glob.glob(str(led_dir / "change_bs_*.json")):
        try:
            rows = json.loads(Path(f).read_text(encoding="utf-8"))["ex_data"]["change_list"]
        except Exception:   # noqa: BLE001
            continue
        for x in rows:
            try:
                amt, px, n = float(x["trans_amount"]), float(x["trans_price"]), float(x["trans_count"])
            except (KeyError, TypeError, ValueError):
                continue
            g = px * n
            if g <= 0 or str(x.get("stock_code", ""))[:1] not in "036":
                continue
            (buys if x.get("op") == "1" else sells if x.get("op") == "2" else []).append((amt - g if x.get("op") == "1" else g - amt, g))
    big_b = [f / g for f, g in buys if f > 0 and g > 20000]
    big_s = [f / g for f, g in sells if f > 0 and g > 20000]
    small = [f for f, g in buys if f > 0 and g < 10000]
    if len(big_b) < 5:
        return None
    br = st.median(big_b)
    sr = st.median(big_s) if len(big_s) >= 5 else br + STAMP
    min5 = bool(small) and st.median(small) >= 4.5
    note = []
    if br > 0.0008:
        note.append("买入费率 > 万 8, 异常(可能含其他市场 / 数据口径不同), 先按缺省")
    if abs((sr - br) - STAMP) > 0.0002:
        note.append(f"卖出 − 买入 = {(sr - br) * 1e4:.1f}‱, 和印花税 5‱ 对不上")
    return {"buy_rate": round(br, 6), "min_fee": 5.0 if min5 else 0.0, "sell_rate_incl_stamp": round(sr, 6),
            "n_buy": len(big_b), "n_sell": len(big_s), "note": "; ".join(note)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    res = {}
    for d in sorted((ROOT / "downloads" / "tzzb").iterdir()):
        if d.is_dir() and not d.name.startswith("_"):
            r = infer(d)
            if r:
                res[d.name] = r
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("| 导师 | 买入佣金率 | 最低 5 元 | 卖出(含印花税) | 样本 | 备注 |\n|---|---|---|---|---|---|")
    for k, v in res.items():
        print(f"| {k} | 万{v['buy_rate'] * 1e4:.2f} | {'是' if v['min_fee'] else '否(免五)'} | 万{v['sell_rate_incl_stamp'] * 1e4:.2f} | {v['n_buy']}/{v['n_sell']} | {v['note']} |")
    print(f"→ {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
