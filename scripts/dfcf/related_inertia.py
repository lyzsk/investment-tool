# -*- coding: utf-8 -*-
"""related_inertia.py — 持仓票的"资金惯性"联动股(零 token 零请求, 10/15 用户令)
用户原话: 持仓除了看妖股, 还要看"趋势/资金在当前行情下有历史惯性的股", 例: 牧原持仓时短线资金惯性做的是东瑞股份。
做法: 行情库 kline_day(只读)近 60 个交易日, 全市场个股与持仓票日收益相关系数 ≥0.5 的票里:
  - 中军: 相关最高的 1 只(如温氏股份, 板块同涨同跌的锚)
  - 短线惯性: 换手率 ≥ 持仓票 2 倍 且 振幅更大的, 按换手降序取 2 只(如东瑞股份: 同板块里短线资金最爱炒的那只)
结果并入 scripts/dfcf/snapshots/live/related_<日>.json(related_yao.mjs 产物)的 related 列表, kind=中军/资金惯性
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/related_inertia.py [--date yyyy-MM-dd]
"""
import argparse, collections, datetime as dt, json, statistics as st, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
import manual_backfill as mb  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    f = ROOT / "scripts" / "dfcf" / "snapshots" / "live" / f"related_{a.date}.json"
    if not f.exists():
        print(f"缺 {f.name}(先跑 related_yao.mjs)"); return 1
    out = json.loads(f.read_text(encoding="utf-8"))
    cur = mb.db().cursor(); cur.execute("use investment_market")
    cur.execute("select distinct trade_date from kline_day where trade_date<=%s order by trade_date desc limit 61", (a.date,))
    ds = sorted(r[0] for r in cur.fetchall())
    cur.execute("select k.symbol,k.trade_date,k.close,k.pre_close,k.high,k.low,k.turnover_rate from kline_day k join security_master s on s.symbol=k.symbol "
                "where s.sec_type='STOCK' and k.trade_date>=%s and k.trade_date<=%s and k.is_deleted=0", (ds[0], a.date))
    R, AMP, TR = collections.defaultdict(dict), collections.defaultdict(list), collections.defaultdict(list)
    for sym, d, cl, pc, h, l, tr in cur.fetchall():
        if pc and cl and float(pc) > 0:
            R[sym][d] = float(cl) / float(pc) - 1; AMP[sym].append((float(h) - float(l)) / float(pc)); TR[sym].append(float(tr or 0))
    cur.execute("select symbol,name from security_master"); NAME = dict(cur.fetchall())
    for h, v in out["holdings"].items():
        key = next((k for k in R if k[-6:] == h), None)
        if not key:
            continue
        base, hamp, htr = R[key], st.mean(AMP[key]), st.mean(TR[key])
        rows = []
        for s, r in R.items():
            if s == key or "ST" in NAME.get(s, ""):
                continue
            d = [x for x in base if x in r]
            if len(d) < 45:
                continue
            try:
                cr = st.correlation([base[x] for x in d], [r[x] for x in d])
            except st.StatisticsError:
                continue
            if cr >= 0.5:
                rows.append({"code": s[-6:], "name": NAME.get(s, "?"), "corr": round(cr, 2), "amp": round(st.mean(AMP[s]) * 100, 2), "turnover": round(st.mean(TR[s]), 2)})
        if not rows:
            continue
        have = {x["code"] for x in v["related"]}
        anchor = max(rows, key=lambda x: x["corr"])
        hot = sorted([x for x in rows if x["turnover"] >= 2 * htr and x["amp"] > hamp * 100], key=lambda x: -x["turnover"])[:2]
        add = [{**anchor, "kind": "中军", "shared": [f"60日相关{anchor['corr']}"], "maxLb": 0, "ztDays": 0}] + \
              [{**x, "kind": "资金惯性", "shared": [f"60日相关{x['corr']}", f"换手{x['turnover']}(持仓{round(htr, 2)})"], "maxLb": 0, "ztDays": 0} for x in hot]
        v["related"] = [x for x in v["related"] if x.get("kind") not in ("中军", "资金惯性")] + [x for x in add if x["code"] not in have]
        print(h, "中军", anchor["name"], anchor["corr"], "| 资金惯性", [f"{x['name']}(相关{x['corr']} 换手{x['turnover']} 振幅{x['amp']}%)" for x in hot])
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
