# -*- coding: utf-8 -*-
"""live_settle.py — 实盘每日结算(零 token, 10/14 建, TODO A7; 隐私: 只读写 scripts/dfcf/snapshots/)
触发: 用户回家贴东财导出 → 我归档成 snapshots/<日>_成交_*.txt → 跑本脚本 → 我在会话里据结果写 CASE
算什么(每笔成交):
  当日: 卖出后当日最高(卖飞 = 卖后最高 − 卖价) / 买入后当日最低(接贵 = 买价 − 买后最低); 分钟数据取 live/<日>.json(盯盘落盘), 缺则用全天高低
  T+1 / T+3: 收盘价相对成交价的方向收益(卖出=价格下跌为对); 日线取 downloads/market/<日>/kline_day.jsonl, 缺则 downloads/quotes/daily
  当日汇总: 买卖股数/均价, 净增减仓, 配对 T 价差(min(买,卖) 股 × (卖均 − 买均))
建议 vs 实挂: live/<日>_orders.md 里固定格式行(见下)——"建议"行也按同样口径算"假如挂了会怎样"(当日是否触价)
  `| HH:MM | 建议 或 实挂 | 买/卖 | 价格 | 数量 | 成交/未成/撤 |`
产物: snapshots/live/settle/<日>.json(当日) + 每次运行把到期的 T+1/T+3 回填进历史日的 json; 末行打印摘要供写 CASE
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/live_settle.py [--date yyyy-MM-dd] [--code 002714]
      缺省=今天 + 回填所有历史日的到期窗口
"""
import argparse, datetime as dt, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAP = ROOT / "scripts" / "dfcf" / "snapshots"
OUT = SNAP / "live" / "settle"
TRADE_RE = [   # 两种导出: ①用户/我整理过的 "09:30:00 卖 300 41.300" ②东财原样 "15:00:00 002714 牧原股份 证券卖出 200 40.890"
    re.compile(r"^(\d\d:\d\d:\d\d)\s+(买|卖)\s+(\d+)(?:→(\d+))?\s+([\d.]+)"),
    re.compile(r"^(\d\d:\d\d:\d\d)\s+(\d{6})\s+\S+\s+证券(买入|卖出)\s+(\d+)\s+([\d.]+)"),
]
ORDER_RE = re.compile(r"^\|\s*(\d\d:\d\d)\s*\|\s*(建议|实挂)\s*\|\s*(买|卖)\s*\|\s*([\d.]+)\s*\|\s*(\d+)\s*\|\s*([^|]*)\|")


def trades_of(day, code):
    out = []
    for f in sorted(SNAP.glob(f"{day}_成交_*.txt")):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            m = TRADE_RE[1].match(re.sub(r"^\d{4}-\d\d-\d\d\s+", "", line))   # 9/28 版导出行首多一列成交日期
            if m:
                if m.group(2) != code:
                    continue
                out.append({"t": m.group(1), "side": "买" if m.group(3) == "买入" else "卖", "qty": int(m.group(4)), "px": float(m.group(5))})
                continue
            m = TRADE_RE[0].match(line)
            if m:
                out.append({"t": m.group(1), "side": m.group(2), "qty": int(m.group(4) or m.group(3)), "px": float(m.group(5))})
    return sorted(out, key=lambda x: x["t"])


def day_bar(day, code):
    sym = ("sh" if code.startswith("6") else "sz") + code
    f = ROOT / "downloads" / "market" / day / "kline_day.jsonl"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if f'"{sym}"' in line:
                j = json.loads(line)
                return {"o": j["open"], "h": j["high"], "l": j["low"], "c": j["close"]}
    f = ROOT / "downloads" / "quotes" / "daily" / f"{code}.json"
    if f.exists():
        for k in json.loads(f.read_text(encoding="utf-8"))["klines"]:
            if k["d"] == day:
                return {"o": k["o"], "h": k["h"], "l": k["l"], "c": k["c"]}
    return None


def minute_bars(day, code):
    f = SNAP / "live" / f"{day}.json"
    try:
        bars = json.loads(f.read_text(encoding="utf-8"))["stocks"][code]["bars"]
        return {k: v for k, v in bars.items() if "09:30" <= k <= "15:00"}
    except (OSError, KeyError, ValueError):
        return {}


def trading_days_after(day, n):
    """day 之后的第 1..n 个交易日(以 md 文件存在为交易日判据, 与项目其他脚本一致)"""
    out, d = [], dt.date.fromisoformat(day)
    for _ in range(20):
        d += dt.timedelta(days=1)
        md = ROOT / "md" / f"{d.year}S{(d.month + 2) // 3}" / f"{d.isoformat()}.md"
        if md.exists():
            out.append(d.isoformat())
            if len(out) == n:
                break
    return out


def intraday(tr, bars, bar):
    """卖: 卖后当日最高; 买: 买后当日最低(分钟数据缺=用全天高低, 标 approx)"""
    hm = tr["t"][:5]
    after = [v for k, v in bars.items() if k >= hm]
    if after:
        hi, lo, approx = max(v["h"] for v in after), min(v["l"] for v in after), False
    elif bar:
        hi, lo, approx = bar["h"], bar["l"], True
    else:
        return {}
    if tr["side"] == "卖":
        return {"after_high": hi, "sold_too_early": round(max(0.0, hi - tr["px"]), 3), "approx": approx}
    return {"after_low": lo, "bought_too_high": round(max(0.0, tr["px"] - lo), 3), "approx": approx}


def fwd(tr, day, code):
    res = {}
    for k, d in zip((1, 3), (trading_days_after(day, 1)[-1:] or [None], trading_days_after(day, 3)[2:3] or [None])):
        d = d[0]
        b = day_bar(d, code) if d else None
        if not b:
            continue
        r = b["c"] / tr["px"] - 1
        res[f"T+{k}"] = {"date": d, "close": b["c"], "ret_dir": round(r if tr["side"] == "买" else -r, 4)}
    return res


def orders_of(day):
    f = SNAP / "live" / f"{day}_orders.md"
    out = []
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            m = ORDER_RE.match(line.strip())
            if m:
                out.append({"t": m.group(1), "kind": m.group(2), "side": m.group(3), "px": float(m.group(4)),
                            "qty": int(m.group(5)), "result": m.group(6).strip()})
    return out


def settle_day(day, code):
    trs = trades_of(day, code)
    if not trs:
        return None
    bar, bars = day_bar(day, code), minute_bars(day, code)
    for tr in trs:
        tr.update(intraday(tr, bars, bar))
        tr.update(fwd(tr, day, code))
    buy = [t for t in trs if t["side"] == "买"]
    sell = [t for t in trs if t["side"] == "卖"]
    avg = lambda xs: round(sum(t["px"] * t["qty"] for t in xs) / max(1, sum(t["qty"] for t in xs)), 3) if xs else None
    bq, sq = sum(t["qty"] for t in buy), sum(t["qty"] for t in sell)
    summ = {"buy_qty": bq, "buy_avg": avg(buy), "sell_qty": sq, "sell_avg": avg(sell), "net_qty": bq - sq,
            "pair_spread": round(min(bq, sq) * ((avg(sell) or 0) - (avg(buy) or 0)), 2) if buy and sell else 0,
            "sold_too_early_sum": round(sum(t.get("sold_too_early", 0) * t["qty"] for t in sell), 2),
            "bought_too_high_sum": round(sum(t.get("bought_too_high", 0) * t["qty"] for t in buy), 2)}
    ords = orders_of(day)
    for o in ords:   # 假如按此价挂: 挂后当日是否触价(买=最低≤价, 卖=最高≥价)
        after = [v for k, v in bars.items() if k >= o["t"]]
        if after:
            o["touched"] = (min(v["l"] for v in after) <= o["px"]) if o["side"] == "买" else (max(v["h"] for v in after) >= o["px"])
    return {"date": day, "code": code, "bar": bar, "trades": trs, "summary": summ, "orders": ords,
            "settled_at": dt.datetime.now().isoformat(timespec="seconds")}


def brief(r):
    s = r["summary"]
    lines = [f"{r['date']} {r['code']}: 买 {s['buy_qty']}@{s['buy_avg']} 卖 {s['sell_qty']}@{s['sell_avg']} 净{'+' if s['net_qty'] >= 0 else ''}{s['net_qty']} | 配对价差 {s['pair_spread']:+.0f} 元 | 卖飞合计 {s['sold_too_early_sum']:.0f} 元 | 接贵合计 {s['bought_too_high_sum']:.0f} 元"]
    worst = sorted([t for t in r["trades"] if t["side"] == "卖"], key=lambda t: -t.get("sold_too_early", 0))[:2] + \
        sorted([t for t in r["trades"] if t["side"] == "买"], key=lambda t: -t.get("bought_too_high", 0))[:2]
    for t in worst:
        k = "sold_too_early" if t["side"] == "卖" else "bought_too_high"
        fw = " ".join(f"{w}:{t[w]['ret_dir']:+.2%}" for w in ("T+1", "T+3") if w in t)
        lines.append(f"  {t['t']} {t['side']} {t['qty']}@{t['px']} {'卖飞' if t['side'] == '卖' else '接贵'} {t.get(k, 0):.2f}{'(全天口径)' if t.get('approx') else ''} {fw}")
    if r["orders"]:
        miss = [o for o in r["orders"] if o["kind"] == "建议" and o.get("touched") is False]
        lines.append(f"  建议单 {sum(1 for o in r['orders'] if o['kind'] == '建议')} 张, 挂后当日没触价 {len(miss)} 张" + (": " + ", ".join(f"{o['t']}{o['side']}{o['px']}" for o in miss[:4]) if miss else ""))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--code", default="002714")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    days = sorted({p.name[:10] for p in SNAP.glob("20??-??-??_成交_*.txt") if p.name[:10] <= a.date})
    done = []
    for d in days:   # 每次全量重算(幂等, 到期的 T+1/T+3 自然补上)
        r = settle_day(d, a.code)
        if r:
            (OUT / f"{d}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
            done.append(r)
    for r in done[-4:]:
        print(brief(r))
    print(f"JSON:{json.dumps({'days': len(done), 'latest': done[-1]['date'] if done else None}, ensure_ascii=False)}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
