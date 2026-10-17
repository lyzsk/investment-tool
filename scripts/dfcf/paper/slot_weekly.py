# -*- coding: utf-8 -*-
"""slot_weekly.py — 链时段 vs 真人出手时段 周检(TODO A9, 10/17 建; 零 token, 只读)

每周(周六/周日)重跑一次: 统计每位导师真人"出手"(买+卖)时段分布, 对比该链当前启用的 sys_job 时段, 错配就列出提醒用户裁。
数据(全部只读):
  链时段   DB sys_job(job_handler_name='paperChainHandler', is_deleted=0; status=0 启用 / 1 暂停), param "skill:HHMM", 桃哥=裸 "HHMM"
  tzzb     downloads/tzzb/<ledger>/change_bs_*.json 逐笔腿(gen_tzzb_profile.load_legs), 去国债逆回购; 同日同票同方向同档=1 次出手
  B站 UP   md 本人小节「今日操作」时段词(up_ops_stats.parse_day; 买+卖); "未说时段"不计入分母, 另列条数
时段档 = 五个盘中阶段(tzzb 时刻与 UP 时段词同一口径), 每段由哪些链 slot 负责:
  竞价 [09:15,09:30) ← 0915 | 开盘 [09:30,10:00) ← 0927/0935/0945 | 上午 [10:00,11:30] ← 1000/1030/1100/1127
  午后 [13:00,14:30) ← 1230/1300/1400 | 尾盘 [14:30,15:00] ← 1430/1455(1455 档的 sys_job 实际 14:35 触发)
  UP 时段词: 竞价→竞价 开盘/早盘→开盘 盘中/上午→上午 午后/下午→午后 尾盘→尾盘
  另附细网格(按 slot 名切)出手次数表, 只供参考, 不参与判定。
错配规则(用户 10/14 晚认可):
  ① 无档: 真人出手落在"本链没有任何启用 slot 负责"的阶段, 合计 ≥20% → 提醒
     10/17 用户定(A8)开盘阶段口径: 没改单 = 盘前(0915)单负责, 改单/盘中追价 = 要子链时段负责;
     tzzb 按 scripts/dfcf/paper/slot_rule.py 的逐单概率 p915 拆分(开盘阶段一次出手只有 1−p915 算"需要子链"); UP 口述无法判改单, 按严格口径
  ② 空档: 本链启用的 slot 所在阶段在统计窗口内 0 样本 → 提醒(0915 盘前全链兼做全天规划, 不算)
统计窗口: 近 90 个自然日(≈60 交易日)样本 ≥20 用近期, 不足退全历史(报告里写明用的哪个)。
产物: docs/research/slot_weekly_<yyyyMMdd>.md(不写 slot_activity.json, 不写库)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/slot_weekly.py [--date yyyy-MM-dd] [--dry] [--selftest]
  --dry=只打印不落盘; 出口 0=无错配 4=有错配(提醒) 1=异常; 末行 JSON:{...}
被 check_md_daily.py --only slot_weekly 调用(只在周六/周日执行)。
"""
import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TZ = ROOT / "downloads" / "tzzb"
MD = ROOT / "md"
OUT_DIR = ROOT / "docs" / "research"
sys.path.insert(0, str(ROOT / "scripts" / "tzzb"))
sys.path.insert(0, str(ROOT / "scripts" / "bilibili"))
sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
sys.path.insert(0, str(ROOT / "scripts" / "dfcf" / "paper"))
import slot_rule as SR  # noqa: E402  10/17 A8 开盘阶段归属口径

# (阶段, 起, 止(含), 负责的 slot)
PHASES = [("竞价", "09:15", "09:29", {"0915"}), ("开盘", "09:30", "09:59", {"0927", "0935", "0945"}),
          ("上午", "10:00", "11:30", {"1000", "1030", "1100", "1127"}), ("午后", "13:00", "14:29", {"1230", "1300", "1400"}),
          ("尾盘", "14:30", "15:00", {"1430", "1455"})]
PH_NAMES = [p[0] for p in PHASES]
SLOT_PHASE = {s: p[0] for p in PHASES for s in p[3]}
WORD_PHASE = {"竞价": "竞价", "开盘": "开盘", "盘中": "上午", "午后": "午后", "尾盘": "尾盘"}
GRID = ["0915", "0927", "0935", "0945", "1000", "1030", "1100", "1127", "1300", "1400", "1430", "1455"]
UP_SKILLS = {"taoge": "#### 股市 - 桃哥复盘", "qushitiange": "#### 趋势天哥", "lubenyuan": "#### 卢本圆复盘"}
NO_REAL = {"control"}
REPO = re.compile(r"^(204|131|888)")
RECENT_DAYS = 90
MIN_N = 20
UNCOVER_TH = 0.20


def phase(hm):
    for name, a, b, _ in PHASES:
        if a <= hm <= b:
            return name
    return None


def grid(hm):
    k = hm.replace(":", "")
    cur = GRID[0]
    for s in GRID:
        if k >= s:
            cur = s
    return cur


# ---------------------------------------------------------------- 链时段(DB 只读)
def chain_slots():
    """{skill: {"on": [...], "off": [...]}}"""
    import manual_backfill as mb
    cur = mb.db().cursor()
    cur.execute("select job_handler_param, status from sys_job where job_handler_name='paperChainHandler' and is_deleted=0")
    out = defaultdict(lambda: {"on": [], "off": []})
    for p, st in cur.fetchall():
        sk, _, sl = (p or "").strip().rpartition(":")
        if not sl.isdigit():
            continue
        out[sk or "taoge"]["on" if int(st) == 0 else "off"].append(sl)
    for v in out.values():
        v["on"].sort()
        v["off"].sort()
    return dict(out)


# ---------------------------------------------------------------- 真人出手
def tzzb_ops(ledger):
    """[{date, ph, g}] 同日同票同方向同细档只算一次; 交易时段外(含手录 00:00:00)不计"""
    from gen_tzzb_profile import load_legs
    seen, ops = set(), []
    for t in sorted(load_legs(ledger), key=lambda t: t["trans_date"]):
        if t.get("op") not in ("1", "2") or REPO.match(str(t.get("stock_code") or "")):
            continue
        d, hm = t["trans_date"][:10], t["trans_date"][11:16]
        ph = phase(hm)
        if not ph:
            continue
        k = (d, str(t["stock_code"]), t["op"], grid(hm))
        if k in seen:
            continue
        seen.add(k)
        ops.append({"date": d, "ph": ph, "g": grid(hm), "p915": SR.p915(ledger, d, t["stock_code"], "B" if t["op"] == "1" else "S", hm)})
    return ops


def up_ops(skill):
    """[{date, ph}] ph=None 表示口述没说时段"""
    import up_ops_stats as U
    head = UP_SKILLS[skill]
    ops = []
    for f in sorted(MD.rglob("20??-??-??.md")):
        try:
            r = U.parse_day(f.read_text(encoding="utf-8", errors="replace"), head)
        except Exception:   # noqa: BLE001
            r = None
        for o in (r or {}).get("ops", []):
            ops.append({"date": f.stem, "ph": WORD_PHASE.get(o.get("time"))})
    return ops


def window(ops, asof):
    lo = (dt.date.fromisoformat(asof) - dt.timedelta(days=RECENT_DAYS)).isoformat()
    allx = [o for o in ops if o["date"] < asof]
    rec = [o for o in allx if o["date"] >= lo]
    if sum(1 for o in rec if o["ph"]) >= MIN_N:
        return rec, f"近 {RECENT_DAYS} 天"
    return allx, "全历史(近期样本不足)"


# ---------------------------------------------------------------- 判定
def judge(ops, on):
    said = [o for o in ops if o["ph"]]
    n = len(said)
    cnt = Counter(o["ph"] for o in said)
    covered = {SLOT_PHASE.get(s) for s in on}
    strict = {p: cnt[p] for p in PH_NAMES if cnt.get(p) and p not in covered}
    zero = [s for s in on if s != "0915" and not cnt.get(SLOT_PHASE.get(s))]
    loose = sum(v for p, v in strict.items() if not (p == "开盘" and "0915" in on))   # 宽松口径: 0915 计划单兼管开盘阶段
    # 10/17 A8 主判定: 开盘阶段且本链有 0915 → 没改单(p915)那部分算 0915 负责; 无逐单概率的(UP/无分钟线)按严格
    unc = dict(strict)
    if "开盘" in unc and "0915" in on:
        unc["开盘"] = round(sum(1.0 - (o["p915"] if o.get("p915") is not None else 0.0) for o in said if o["ph"] == "开盘"), 1)
        if not unc["开盘"]:
            unc.pop("开盘")
    n915 = sum(1 for o in said if o["ph"] == "开盘" and o.get("p915") is not None)
    return {"n": n, "unc_loose": (loose / n) if n else None, "unc_strict": (sum(strict.values()) / n) if n else None, "n_all": len(ops),
            "dist": {p: cnt.get(p, 0) for p in PH_NAMES}, "grid": Counter(o.get("g") for o in said if o.get("g")),
            "uncovered": unc, "unc_share": (sum(unc.values()) / n) if n else None, "zero": zero, "open_with_p915": n915}


def flags_of(j):
    f = []
    if j["unc_share"] is not None and j["unc_share"] >= UNCOVER_TH:
        f.append(f"无档 {j['unc_share']:.0%} 的出手落在本链没有 slot 的阶段: " + ", ".join(f"{k}({v})" for k, v in sorted(j["uncovered"].items(), key=lambda kv: -kv[1]))
                 + f"(参考: 开盘全算 0915 {j['unc_loose']:.0%} / 开盘全不算 {j['unc_strict']:.0%})")
    if j["zero"]:
        f.append("空档(启用但该阶段 0 样本): " + ", ".join(j["zero"]))
    return f


def run(asof):
    cs = chain_slots()
    ledgers = json.loads((ROOT / "scripts" / "tzzb" / "tzzb_ledgers.json").read_text(encoding="utf-8"))
    pos = [L["ledger"] for L in ledgers if L.get("kind") == "pos"]
    rows = []
    for sk in sorted(set(cs) | set(pos) | set(UP_SKILLS) | NO_REAL):
        sl = cs.get(sk, {"on": [], "off": []})
        r = {"skill": sk, "on": sl["on"], "off": sl["off"], "flags": [], "notes": []}
        rows.append(r)
        if sk in NO_REAL:
            r["notes"].append("对照组无真人, 不比")
            continue
        if not sl["on"]:
            r["notes"].append("未排程(无启用的 sys_job)" + (f"; 暂停中的档 {','.join(sl['off'])}" if sl["off"] else ""))
        if sk in UP_SKILLS:
            ops, r["kind"] = up_ops(sk), "UP"
        elif (TZ / sk).exists():
            ops, r["kind"] = tzzb_ops(sk), "tzzb"
        else:
            r["notes"].append("无真人数据源")
            continue
        w, r["win"] = window(ops, asof)
        r["j"] = j = judge(w, sl["on"])
        if sl["on"]:
            if j["n"] < MIN_N:
                r["notes"].append(f"有时段的样本 {j['n']} < {MIN_N}, 结论仅供参考")
            r["flags"] = flags_of(j)
    return rows


def render(rows, asof):
    hit = [r for r in rows if r["flags"]]
    L = [f"# 链时段 vs 真人出手时段 周检 {asof}", "",
         "> 零 token 自动生成(scripts/dfcf/paper/slot_weekly.py)。时段档=五阶段: 竞价[09:15,09:30)←0915 / 开盘[09:30,10:00)←0927·0935·0945 / "
         "上午[10:00,11:30]←1000·1030·1100·1127 / 午后[13:00,14:30)←1230·1300·1400 / 尾盘[14:30,15:00]←1430·1455。",
         f"> 规则: ①无档=真人出手落在本链没有 slot 的阶段合计 ≥{UNCOVER_TH:.0%} ②空档=启用 slot 所在阶段 0 样本(0915 盘前全链不算)。"
         f" 窗口: 近 {RECENT_DAYS} 天有时段样本 ≥{MIN_N} 用近期, 否则全历史。出手=买+卖, 同日同票同方向同细档算 1 次。",
         "> 只提醒, 不改排程; 改不改由用户裁。", "",
         f"## 需要用户看的({len(hit)} 条链)", ""]
    if not hit:
        L.append("- 无错配")
    for r in hit:
        L.append(f"- **{r['skill']}**(启用 {','.join(r['on'])}; 样本 {r['j']['n']}, {r['win']}): " + "; ".join(r["flags"])
                 + (f"({'; '.join(r['notes'])})" if r["notes"] else ""))
    notes = [r for r in rows if r["notes"] and not r["flags"]]
    if notes:
        L += ["", "## 备注", ""] + [f"- {r['skill']}: {'; '.join(r['notes'])}" for r in notes]
    L += ["", "## 各链五阶段出手次数(★=本链有启用 slot 负责该阶段)", "",
          "| 链 | 类型 | 启用 slot | 窗口 | 有时段/全部 | " + " | ".join(PH_NAMES) + " | 无档占比(主: 没改单归 0915) | 开盘全算 0915 | 开盘全不算 |", "|---|---|---|---|---|" + "---|" * len(PH_NAMES) + "---|---|---|"]
    for r in rows:
        if "j" not in r:
            continue
        cov = {SLOT_PHASE.get(s) for s in r["on"]}
        us = r["j"]["unc_share"]
        L.append(f"| {r['skill']} | {r['kind']} | {','.join(r['on']) or '-'} | {r['win']} | {r['j']['n']}/{r['j']['n_all']} | "
                 + " | ".join(f"{r['j']['dist'][p]}{'★' if p in cov else ''}" for p in PH_NAMES) + f" | {'-' if us is None else f'{us:.0%}'} | {'-' if us is None else format(r['j']['unc_loose'], '.0%')} | {'-' if us is None else format(r['j']['unc_strict'], '.0%')} |")
    L += ["", "## 参考: tzzb 导师细网格出手次数(按 slot 名切, [slot, 下一个 slot); ★=启用 ☆=暂停; 1230 午间链计入 1300)", "",
          "| 链 | " + " | ".join(GRID) + " |", "|---|" + "---|" * len(GRID)]
    for r in rows:
        if r.get("kind") != "tzzb":
            continue
        on = {("1300" if s == "1230" else s) for s in r["on"]}
        off = {("1300" if s == "1230" else s) for s in r["off"]}
        L.append(f"| {r['skill']} | " + " | ".join(f"{r['j']['grid'].get(g, 0)}{'★' if g in on else '☆' if g in off else ''}" for g in GRID) + " |")
    L += ["", "## 不自信点", "",
          "- 开盘阶段口径(10/17 用户定): 没改单=0915 盘前单负责, 改单/盘中追价=子链负责。真人挂单看不到, 用成交方式推断概率(集合竞价 + 开盘以来没被穿价的被动限价单=可能盘前就挂好)近似, 推断本身有误差(见 docs/research/order_inference_20261016.md); UP 口述判不了改单, 按开盘全不算。",
          "- 阶段划分是我定的口径(开盘 30 分钟/上午/午后/尾盘 30 分钟); 0927 只负责'开盘'阶段, 不负责竞价(竞价单 09:25 前已定)。",
          "- 1455 档的 sys_job 实际 14:35 触发, 归入尾盘阶段。",
          "- UP 只有口述时段词且多数没说时段(见'有时段/全部'), 结论粗; 天哥 md「今日操作」解析为 0 条。", ""]
    return "\n".join(L)


def selftest():
    assert phase("09:25") == "竞价" and phase("09:31") == "开盘" and phase("11:30") == "上午" and phase("12:00") is None
    assert phase("13:05") == "午后" and phase("14:56") == "尾盘" and phase("00:00") is None and grid("09:36") == "0935"
    ops = [{"date": "2026-10-01", "ph": p} for p in ["竞价"] * 5 + ["上午"] * 3 + ["午后"] * 2]
    j = judge(ops, ["0915", "1000", "1455", "1030"])
    assert abs(j["unc_share"] - 0.2) < 1e-9 and j["zero"] == ["1455"], j
    f = flags_of(j)
    assert f[0].startswith("无档 20%") and "1455" in f[1], f
    assert not flags_of(judge(ops, ["0915", "1000", "1230"]))
    u = judge([{"date": "x", "ph": "开盘"}] * 3 + [{"date": "x", "ph": None}] * 4, ["0915", "0927"])
    assert u["n"] == 3 and u["n_all"] == 7 and u["unc_share"] == 0 and not u["zero"], u
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return 0
    rows = run(a.date)
    md = render(rows, a.date)
    out = OUT_DIR / f"slot_weekly_{a.date.replace('-', '')}.md"
    hit = [r["skill"] for r in rows if r["flags"]]
    if a.dry:
        print(md)
    else:
        out.write_text(md + "\n", encoding="utf-8")
        print("\n".join(md.splitlines()[:7 + len(hit) + 1]))
    print("JSON:" + json.dumps({"date": a.date, "mismatch": hit, "report": None if a.dry else out.relative_to(ROOT).as_posix()}, ensure_ascii=False))
    return 4 if hit else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        sys.exit(main())
    except Exception as e:   # noqa: BLE001
        print(f"slot_weekly 异常: {type(e).__name__}: {e}")
        print("JSON:" + json.dumps({"error": f"{type(e).__name__}: {e}"[:200]}, ensure_ascii=False))
        sys.exit(1)
