# -*- coding: utf-8 -*-
"""quality_daily.py — 决策质量新功能的每日产物一键生成(10/17 ② agent; 零 token; 只读行情库/账本, 只写 scripts/dfcf/paper/ 下各产物目录)

生成(给"链日" D 用, 只用 D 之前的数据):
  slot_profile/<D>.json   出手时段分布(长期×近20日) + 0915 开仓预算         (<1 秒)
  t_profile/<D>.json      T 法画像 + 执行T/不学T 判定                       (<1 秒)
  similar_days/<D>.json   相似市况 3 天(读 investment_market.kline_day)       (约 15 秒)
  rule_tags/<导师>.json   规则方向/机械触发标注(读 rules.md)                 (<1 秒)
  overrides/locks.json    override 胜负 + 锁层(读 overrides/*.jsonl; 真人当日数据 15:10 后才有)
建议挂法: 晚间 check md 收尾(或 08:00 盘前兜底)跑一次 `--date <下一交易日>`; 不挂也行——slot/t 产物缺时 quality_hooks 用最近一份(标 stale), 相似市况缺=不注入。
CLI: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/quality_daily.py [--date D] [--only slot,t,similar,rules,override] | --selftest
"""
import argparse
import json
import sys
import time
from datetime import date as _date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
STEPS = ("slot", "t", "similar", "rules", "override")


def next_trade_day(today=None):
    """15:00 后=下一交易日, 否则=今天(若今天是交易日); 日历=上证日线归档, 缺则按工作日近似"""
    import a_rules as AR
    now = datetime.now()
    d = today or now.date().isoformat()
    cal = AR.trade_days()
    after_close = today is None and now.hour >= 15
    later = [x for x in cal if (x > d if after_close else x >= d)]
    if later:
        return later[0]
    import datetime as dt
    x = dt.date.fromisoformat(d) + dt.timedelta(days=1 if after_close else 0)
    while x.weekday() >= 5:
        x += dt.timedelta(days=1)
    return x.isoformat()


def run(D, only=STEPS):
    res = {}
    for s in only:
        t0 = time.time()
        try:
            if s == "slot":
                import slot_profile as P
                d = P.build(D)
                P.OUT.mkdir(parents=True, exist_ok=True)
                P.path_of(D).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
                res[s] = f"{len(d['mentors'])} 位"
            elif s == "t":
                import t_profile as T
                d = T.build(D)
                T.OUT.mkdir(parents=True, exist_ok=True)
                (T.OUT / f"{D}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
                res[s] = " ".join(f"{k}:{v.get('verdict')}" for k, v in d["mentors"].items() if v.get("verdict") in ("执行T", "不学T"))
            elif s == "similar":
                import similar_days as S
                d = S.build(D)
                S.OUT.mkdir(parents=True, exist_ok=True)
                (S.OUT / f"{D}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
                res[s] = f"查询日 {d.get('query')}: " + ", ".join(f"{x['date']}({x['sim']:.2f})" for x in d.get("similar") or [])
            elif s == "rules":
                import rule_tags as R
                d = R.build()
                res[s] = f"{len(d)} 位, 可机械判定 {sum(x['n_mech'] for x in d.values())} 条"
            elif s == "override":
                import override_stats as O
                today = min(_date.today().isoformat(), D)
                r = O.run("2026-10-08", today)
                res[s] = f"记账 {len(r['days'])} 天, 锁 {sum(len(v) for v in r['locks'].values())} 层"
            res[s] = f"OK {time.time() - t0:.1f}s {res[s]}"
        except Exception as e:   # noqa: BLE001
            res[s] = f"FAIL {type(e).__name__}: {str(e)[:200]}"
    return res


def selftest():
    fails = []
    import a_rules as AR
    cal = AR.trade_days()
    if cal:
        d = cal[-1]
        nd = next_trade_day(d)
        if nd != d:
            fails.append(f"next_trade_day 交易日当天应返回当天: {d}→{nd}")
    for m in ("price_rules", "slot_profile", "t_profile", "override_stats", "similar_days", "rule_tags"):
        import contextlib, io
        mod = __import__(m)
        with contextlib.redirect_stdout(io.StringIO()):
            if mod.selftest():
                fails.append(f"{m}.selftest 失败")
    print("SELFTEST " + ("PASS" if not fails else f"FAIL {fails}"))
    return 0 if not fails else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--only")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    D = a.date or next_trade_day()
    only = [x.strip() for x in a.only.split(",")] if a.only else STEPS
    print(f"决策质量产物 链日 {D}")
    res = run(D, only)
    for k, v in res.items():
        print(f"  {k:9s} {v}")
    sys.exit(0 if all(v.startswith("OK") for v in res.values()) else 1)


if __name__ == "__main__":
    main()
