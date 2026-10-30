"""mentor_buy_depth.py — 导师真实买入价相对昨收的分布(10/29 晚用户批「买单挂价按导师自己的买入深度分布」; 零 token, 只读库)
口径: tzzb_record bs_leg 买入腿(op=1)、股票(去转债 / 基金 / 逆回购), 近 N 个交易日(默认 60), 每腿 = 成交价 / 当天昨收 − 1;
       按成交额加权的 P25 / P50 / P75 + 样本数; 缓存 results/_live/<D>/_buy_depth_<skill>.json(当天不变)
用法: python mentor_buy_depth.py --skill liuyiqing --date 2026-10-30
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))


def _sym(c):
    return ("sh" if c.startswith(("6", "9")) else "sz") + c


def depth(skill, D, days=60):
    cache = ROOT / "results" / "_live" / D / f"_buy_depth_{skill}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except ValueError:
            pass
    import manual_backfill as mb
    cur = mb.db().cursor()
    cur.execute("select date(record_time), stock_code, payload_json from investment_tool.tzzb_record where is_deleted=0 and record_type='bs_leg' and ledger=%s "
                "and record_time < %s and record_time >= date_sub(%s, interval %s day)", (skill, D, D, int(days * 1.5)))
    legs = []
    for d, code, pj in cur.fetchall():
        code = str(code or "")
        if len(code) != 6 or not code.startswith(("0", "3", "6")) or code.startswith(("11", "12", "13", "15", "16", "18", "20")):
            continue
        try:
            p = json.loads(pj or "{}")
        except ValueError:
            continue
        if str(p.get("op")) != "1":
            continue
        try:
            px, q = float(p.get("trans_price") or 0), float(p.get("trans_count") or 0)
        except ValueError:
            continue
        if px > 0 and q > 0:
            legs.append((str(d), code, px, px * q))
    if not legs:
        out = {"n": 0}
    else:
        cur.execute("use investment_market")
        pcs = {}
        for d, code, _, _ in legs:
            if (d, code) in pcs:
                continue
            cur.execute("select pre_close from kline_day where symbol=%s and trade_date=%s", (_sym(code), d))
            r = cur.fetchone()
            pcs[(d, code)] = float(r[0]) if r and r[0] else None
        xs = sorted(((px / pcs[(d, c)] - 1) * 100, w) for d, c, px, w in legs if pcs.get((d, c)))
        tw = sum(w for _, w in xs) or 1

        def wq(p):
            acc = 0.0
            for v, w in xs:
                acc += w
                if acc >= p * tw:
                    return round(v, 2)
            return round(xs[-1][0], 2)
        out = {"n": len(xs), "p25": wq(0.25), "p50": wq(0.5), "p75": wq(0.75), "days": days, "from": min(d for d, *_ in legs), "to": max(d for d, *_ in legs)}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return out


EDGES = [("09:25", "09:31"), ("09:31", "09:45"), ("09:45", "10:30"), ("10:30", "11:30"), ("13:00", "14:30"), ("14:30", "15:00")]


def plan(skill, D, new_open=True, play=None, mkt=None):
    """10/29 晚用户「重点是做好 a: 按 skill 学导师买的节奏」: 导师 D 之前同类买入(新开 / 加仓; 有打法就先按打法)的
    时段占比 + 每段买价相对昨收 / 开盘的中位 —— 来源 skills/<导师>-skill/persona/cases_auto.jsonl(mentor_fingerprint 每晚重算);
    → {"n", "by": "打法 / 新开 / 全体", "plan": [{"from", "to", "share", "vs_prev", "vs_open", "n"}]}; 样本 <8 → None"""
    f = ROOT / "skills" / f"{skill}-skill" / "persona" / "cases_auto.jsonl"
    if not f.exists():
        return None
    B = []
    for l in f.read_text(encoding="utf-8").splitlines():
        if '"side": "买"' not in l:
            continue
        try:
            b = json.loads(l)
        except ValueError:
            continue
        ft = b.get("feat") or {}
        if b.get("date", "") >= D or ft.get("asset") not in ("MAIN", "GEM", "STAR", None) or ft.get("buy_pct") is None:
            continue
        ip = ft.get("idx_pct_day")
        mk = "up" if ip is not None and ip >= 0.003 else "dn" if ip is not None and ip <= -0.003 else "flat"   # 10/30: 买入价也按当时市况分
        B.append({"t": str(b.get("time") or "")[:5], "new": bool(b.get("new_open")), "play": b.get("play"), "vp": ft["buy_pct"] * 100,
                  "vo": None if ft.get("vs_open") is None else ft["vs_open"] * 100, "mkt": mk})
    for by, xs in (("打法", [b for b in B if b["new"] == new_open and play and b["play"] == play]), ("新开" if new_open else "加仓", [b for b in B if b["new"] == new_open]), ("全体", B)):
        if mkt:
            xm = [b for b in xs if b["mkt"] == mkt]
            if len(xm) >= 8:   # 同市况样本够才用, 不够退回同类型全体
                xs, by = xm, by + f"/{mkt}市况"
        if len(xs) >= 8:
            break
    else:
        return None
    med = lambda v: sorted(v)[len(v) // 2] if v else None   # noqa: E731
    out = []
    for a, b in EDGES:
        seg = [x for x in xs if a <= x["t"] < b]
        if seg:
            out.append({"from": a + ":00", "to": b + ":00", "share": round(len(seg) / len(xs), 3), "vs_prev": round(med([x["vp"] for x in seg]), 2),
                        "vs_open": med([x["vo"] for x in seg if x["vo"] is not None]), "n": len(seg)})
    return {"n": len(xs), "by": by, "plan": out}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    print(json.dumps(depth(a.skill, a.date), ensure_ascii=False))
    print(json.dumps(plan(a.skill, a.date, True), ensure_ascii=False))
    print(json.dumps(plan(a.skill, a.date, False), ensure_ascii=False))
