# -*- coding: utf-8 -*-
"""override_stats.py — 06 override(LLM 改基线建议)胜负统计 + 连续 20 天净负锁层(TODO 三-2 待做项, 10/17 ② agent; 零 token, 只读)

原料: scripts/dfcf/paper/overrides/<D>.jsonl(驱动器 _ledger_v06 记账, 开关 CHAIN_LEDGER_CONSTRAINTS 开着才有):
  每行 {skill, slot, sub, baseline{trade,dir,tp_target,n_new,p_trade}, chain{trade,dir,n_new,net_pct}, override[{layer,...}], undeclared[层]}
真值: 导师真人当日(mimicry_score.Real/derive 同口径: 出手/方向/收盘总仓/买入票); 链账本 books/A-<skill>.json(收盘总仓/当日买入/收益);
      基线虚拟账户 baseline/BL-<skill>.json(当日买入/收益)。
逐层判胜负(只判"改了"的层 = 声明的 override ∪ 未声明但偏离的层; 同一 (导师, 日, 层) 取最后一次记录, 盘中子链只看 0915 主链没改的层):
  L1 出手   链.trade==真人.trade≠基线.trade → 胜; 基线==真人≠链 → 负; 其余平
  L2 方向   同上(加/不动/减; 真人不出手=不动)
  L4 总仓   |链收盘总仓−真人| 比 |基线目标总仓−真人| 小 TOL 以上=胜, 大 TOL 以上=负
  L3 选股   链当日新买票 ∩ 真人当日买入 的命中数 vs 基线账户当日新买票的命中数(多=胜, 少=负)
  另记 收益差(链账本当日收益 − 基线账户当日收益, 只报告不进锁)
锁层: 某导师某层 近 LOCK_WINDOW(20) 个交易日 net=胜−负 < 0, 且该窗口内该导师 override 记账天数 ≥ LOCK_MIN_DAYS(20) → 锁
  (=系统至少跑满 20 个交易日才可能锁; 锁住后 06 该层必须接受基线, 驱动器开关 CHAIN_OVERRIDE_LOCK 默认 0); net 回到 ≥0 自动解锁。
产物: overrides/stats_<D>.json(逐日逐层明细+汇总) + overrides/locks.json(驱动器读) + 终端汇总表。

CLI(scripts/venv/Scripts/python.exe -X utf8):
  override_stats.py [--until 2026-10-19] [--since 2026-10-08]      统计并写 locks.json(收盘后跑; 真人账本 15:10 后才有当日数据)
  override_stats.py --selftest
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import date as _date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OVR = HERE / "overrides"
BOOKS = HERE / "books"
BASE = HERE / "baseline"
sys.path.insert(0, str(HERE))

LAYERS = ("L1", "L2", "L3", "L4")
LOCK_WINDOW = 20
LOCK_MIN_DAYS = 20
TOL_TP = 0.05            # L4 总仓差异 5pt 以内算平
DIR_OF = {1: "加", 0: "不动", -1: "减", None: "不动"}


def _jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def read_overrides(d0, d1, odir=None):
    """→ {(skill, date): {"main": rec|None, "subs": [rec...]}}(同 slot 取最后一行)"""
    out = {}
    for f in sorted(Path(odir or OVR).glob("20??-??-??.jsonl")):
        if not (d0 <= f.stem <= d1):
            continue
        last = {}
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("skill") and r.get("baseline") is not None:
                last[(r["skill"], r.get("slot"), bool(r.get("sub")))] = r
        for (sk, slot, sub), r in last.items():
            e = out.setdefault((sk, f.stem), {"main": None, "subs": []})
            if sub:
                e["subs"].append(r)
            else:
                e["main"] = r
    return out


class Truth:
    """真人当日 trade/dir/tp/buys(mimicry 同口径); 缺数据=None"""

    def __init__(self):
        self._r = {}

    def real(self, skill):
        if skill not in self._r:
            try:
                import mimicry_score as ms
                self._r[skill] = ms.Real(skill) if (ms.TZ / skill / "day_positions.json").exists() else None
            except Exception:   # noqa: BLE001
                self._r[skill] = None
        return self._r[skill]

    def of(self, skill, d):
        R = self.real(skill)
        if R is None or not R.has(d):
            return None
        import mimicry_score as ms
        days = sorted(k for k in R.dp if k < d.replace("-", ""))
        prev = R.snap(f"{days[-1][:4]}-{days[-1][4:6]}-{days[-1][6:]}") if days else None
        cur = R.snap(d)
        if cur is None:
            return None
        f = ms.derive(prev, cur, lambda c: None)
        return {"trade": bool(f["trade"]), "dir": DIR_OF.get(f["dir"]) if f["trade"] else "不动", "tp": float(f["tp"]), "buys": set(cur["buy"])}


def _book(path):
    return _jl(path, {}) or {}


def book_day(b, d):
    """账本当日: 收盘总仓 tp / 当日收益 ret / 当日新买票(按 trade id 日期前缀)"""
    nav = sorted(b.get("nav") or [], key=lambda x: x.get("date", ""))
    cur = next((x for x in nav if x.get("date") == d), None)
    prev = [x for x in nav if x.get("date", "") < d]
    tp = (float(cur.get("mv") or 0) / float(cur["nav"])) if cur and cur.get("nav") else None
    ret = (float(cur["nav"]) / float(prev[-1]["nav"]) - 1) if cur and prev and prev[-1].get("nav") else None
    buys = {str(t.get("code")) for t in b.get("trades") or [] if t.get("side") == "BUY" and str(t.get("id", "")).startswith(d)}
    return {"tp": tp, "ret": ret, "buys": buys}


def _cmp(chain_v, base_v, real_v):
    if real_v is None or chain_v is None or base_v is None or chain_v == base_v:
        return 0
    if chain_v == real_v:
        return 1
    if base_v == real_v:
        return -1
    return 0


def score_day(rec, real, cb, bb, layers):
    """单条记录对指定层的胜负 {层: +1/0/-1}"""
    base, ch = rec.get("baseline") or {}, rec.get("chain") or {}
    out = {}
    for L in layers:
        if L == "L1":
            out[L] = _cmp(bool(ch.get("trade")), bool(base.get("trade")), real["trade"])
        elif L == "L2":
            out[L] = _cmp(ch.get("dir") or "不动", base.get("dir") or "不动", real["dir"])
        elif L == "L4":
            tpc, tpb = (cb or {}).get("tp"), base.get("tp_target")
            if tpc is None or tpb is None:
                out[L] = 0
            else:
                ec, eb = abs(tpc - real["tp"]), abs(float(tpb) - real["tp"])
                out[L] = 1 if ec + TOL_TP < eb else -1 if eb + TOL_TP < ec else 0
        elif L == "L3":
            hc = len((cb or {}).get("buys", set()) & real["buys"])
            hb = len((bb or {}).get("buys", set()) & real["buys"])
            out[L] = (hc > hb) - (hc < hb) if ((cb or {}).get("buys") or (bb or {}).get("buys")) else 0
    return out


def layers_of(rec):
    lay = {x.get("layer") for x in rec.get("override") or [] if x.get("layer")}
    return (lay | set(rec.get("undeclared") or [])) & set(LAYERS)


def run(since, until, odir=None, books=None, base_dir=None, truth=None, write=True):
    truth = truth or Truth()
    recs = read_overrides(since, until, odir)
    days_all = sorted({d for _, d in recs})
    rows = []
    for (sk, d), e in sorted(recs.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        real = truth.of(sk, d)
        cb = book_day(_book(Path(books or BOOKS) / f"A-{sk}.json"), d)
        bb = book_day(_book(Path(base_dir or BASE) / f"BL-{sk}.json"), d)
        done = set()
        for rec, tag in ([(e["main"], "0915")] if e["main"] else []) + [(r, r.get("slot")) for r in e["subs"]]:
            lay = layers_of(rec) - done
            done |= lay
            if not lay:
                continue
            sc = score_day(rec, real, cb, bb, lay) if real else {L: None for L in lay}
            rows.append({"skill": sk, "date": d, "slot": tag, "layers": sorted(lay), "score": sc,
                         "declared": sorted({x.get("layer") for x in rec.get("override") or []}),
                         "ret_diff": (cb["ret"] - bb["ret"]) if cb.get("ret") is not None and bb.get("ret") is not None else None,
                         "no_truth": real is None})
    # 汇总 + 锁
    by = defaultdict(lambda: {"win": 0, "loss": 0, "tie": 0, "n": 0, "days": set(), "net_series": defaultdict(int)})
    rec_days = defaultdict(set)
    for (sk, d) in recs:
        rec_days[sk].add(d)
    for r in rows:
        for L, s in r["score"].items():
            if s is None:
                continue
            a = by[(r["skill"], L)]
            a["n"] += 1
            a["days"].add(r["date"])
            a["net_series"][r["date"]] += s
            a["win" if s > 0 else "loss" if s < 0 else "tie"] += 1
    locks = {}
    summary = {}
    for (sk, L), a in sorted(by.items()):
        win_days = sorted(rec_days[sk])[-LOCK_WINDOW:]
        net20 = sum(v for d, v in a["net_series"].items() if d in set(win_days))
        locked = len(win_days) >= LOCK_MIN_DAYS and net20 < 0
        summary.setdefault(sk, {})[L] = {"win": a["win"], "loss": a["loss"], "tie": a["tie"], "n": a["n"], "net20": net20,
                                         "days_in_window": len(win_days), "locked": locked}
        if locked:
            locks.setdefault(sk, {})[L] = {"locked": True, "net20": net20, "window": [win_days[0], win_days[-1]], "n": a["n"]}
    res = {"since": since, "until": until, "days": days_all, "rows": rows, "summary": summary,
           "locks": locks, "rule": f"近 {LOCK_WINDOW} 个记账交易日 net=胜−负<0 且记账天数≥{LOCK_MIN_DAYS} → 锁层",
           "ret_diff_mean": {sk: (sum(x) / len(x)) for sk, x in _group_ret(rows).items()}}
    if write:
        d = Path(odir or OVR)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"stats_{until}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=sorted), encoding="utf-8")
        (d / "locks.json").write_text(json.dumps({"until": until, "rule": res["rule"], "locks": locks}, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def _group_ret(rows):
    g = defaultdict(list)
    seen = set()
    for r in rows:
        if r["ret_diff"] is not None and (r["skill"], r["date"]) not in seen:
            seen.add((r["skill"], r["date"]))
            g[r["skill"]].append(r["ret_diff"])
    return g


def locks_of(skill, odir=None):
    """驱动器用: {层: info}(无锁/无文件=空)"""
    return ((_jl(Path(odir or OVR) / "locks.json", {}) or {}).get("locks") or {}).get(skill) or {}


def print_summary(res):
    print(f"override 胜负 {res['since']}~{res['until']}(记账日 {len(res['days'])} 天; {res['rule']})")
    print("| 导师 | 层 | 胜 | 负 | 平 | 近20日净 | 窗口天数 | 锁 |\n|---|---|---|---|---|---|---|---|")
    for sk, lay in res["summary"].items():
        for L, a in lay.items():
            print(f"| {sk} | {L} | {a['win']} | {a['loss']} | {a['tie']} | {a['net20']:+d} | {a['days_in_window']} | {'锁' if a['locked'] else ''} |")
    for sk, v in res["ret_diff_mean"].items():
        print(f"收益差(链−基线账户) {sk}: 日均 {v:+.2%}")


def selftest():
    import tempfile
    fails = []

    def chk(n, c):
        print(("PASS " if c else "FAIL ") + n)
        if not c:
            fails.append(n)

    tmp = Path(tempfile.mkdtemp(prefix="ovr_"))
    (tmp / "o").mkdir()
    (tmp / "b").mkdir()
    (tmp / "bl").mkdir()
    days = [f"2026-11-{i:02d}" for i in range(1, 26)]

    class FakeTruth:
        def of(self, sk, d):   # 真人: 每天都出手、方向=加、总仓 0.8、买 600001
            return {"trade": True, "dir": "加", "tp": 0.8, "buys": {"600001"}}

    nav_c, nav_b, tr_c, tr_b = [], [], [], []
    for i, d in enumerate(days):
        # sk=x: 基线判不出手, 链出手(声明 L1) → 链对; sk=y: 基线判加, 链判减(未声明 L2) → 链错
        recs = [{"skill": "x", "slot": "0915", "sub": False, "baseline": {"trade": False, "dir": "不动", "tp_target": 0.5},
                 "chain": {"trade": True, "dir": "加"}, "override": [{"layer": "L1", "why": "测试理由足够长"}], "undeclared": ["L2"]},
                {"skill": "y", "slot": "0915", "sub": False, "baseline": {"trade": True, "dir": "加", "tp_target": 0.8},
                 "chain": {"trade": True, "dir": "减"}, "override": [], "undeclared": ["L2"]},
                {"skill": "y", "slot": "1000", "sub": True, "baseline": {"trade": True, "dir": "加", "tp_target": 0.8},
                 "chain": {"trade": True, "dir": "减"}, "override": [{"layer": "L4", "why": "子链改总仓理由"}], "undeclared": ["L2"]}]
        (tmp / "o" / f"{d}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n", encoding="utf-8")
        nav_c.append({"date": d, "mv": 30000 + i, "nav": 100000})
        nav_b.append({"date": d, "mv": 80000, "nav": 100000 - i})
        tr_c.append({"id": f"{d}-A-y-001", "side": "BUY", "code": "600001"})
        tr_b.append({"id": f"{d}-BL-y-001", "side": "BUY", "code": "600002"})
    (tmp / "b" / "A-y.json").write_text(json.dumps({"nav": nav_c, "trades": tr_c}), encoding="utf-8")
    (tmp / "bl" / "BL-y.json").write_text(json.dumps({"nav": nav_b, "trades": tr_b}), encoding="utf-8")
    res = run(days[0], days[-1], tmp / "o", tmp / "b", tmp / "bl", FakeTruth())
    sx, sy = res["summary"]["x"], res["summary"]["y"]
    chk("x L1 声明 override 全胜", sx["L1"]["win"] == 25 and sx["L1"]["loss"] == 0)
    chk("x L2 未声明偏离也计(链加=真人加)", sx["L2"]["win"] == 25)
    chk("y L2 改错全负", sy["L2"]["loss"] == 25)
    chk("子链只计主链没改的层(L4)", sy["L4"]["n"] == 25 and "L2" in sy and sy["L2"]["n"] == 25)
    chk("y L4: 链总仓 0.3 离真人 0.8 更远=负", sy["L4"]["loss"] == 25)
    chk("y 锁 L2/L4, x 不锁", set(res["locks"].get("y", {})) == {"L2", "L4"} and "x" not in res["locks"])
    chk("locks.json 可读", set(locks_of("y", tmp / "o")) == {"L2", "L4"})
    chk("收益差有值", "y" in res["ret_diff_mean"])
    res2 = run(days[0], days[10], tmp / "o", tmp / "b", tmp / "bl", FakeTruth(), write=False)
    chk("不满 20 天不锁", not res2["locks"])

    class NoTruth:
        def of(self, sk, d):
            return None
    res3 = run(days[0], days[-1], tmp / "o", tmp / "b", tmp / "bl", NoTruth(), write=False)
    chk("无真值=不计分不锁", not res3["locks"] and all(r["no_truth"] for r in res3["rows"]))
    chk("空目录不炸", run("2030-01-01", "2030-01-02", tmp / "none", write=False)["rows"] == [])
    print("SELFTEST " + ("PASS" if not fails else f"FAIL {fails}"))
    return 0 if not fails else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-10-08")
    ap.add_argument("--until", default=_date.today().isoformat())
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    res = run(a.since, a.until, write=not a.no_write)
    print_summary(res)
    if not res["rows"]:
        print("(无 override 记账: CHAIN_LEDGER_CONSTRAINTS 未开或当日链未跑)")


if __name__ == "__main__":
    main()
