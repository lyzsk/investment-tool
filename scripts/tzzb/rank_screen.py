# -*- coding: utf-8 -*-
"""rank_screen.py — tzzb 比赛月榜逐月拉取 + 按新选人标准筛中长线候选(10/17 agent③ 建; A14 用户批"月榜参数逐月拉")

三段漏斗(每段零 token; 抓取段全部经 tzzb_guard 共用正式 downloads/tzzb/_guard 的额度/熔断/锁/时间窗):
  probe        1 次请求探测是否解封(浏览器代发)。403 → 写正式 ban.json(6h) + side_stop_<日>.json(副线停到次日), 退出 5
  fetch-rank   ①总榜(match_keys.json 里还没有 _ranks/<key>.json 的场) ②月榜 逐场×逐月(断点续传, 可跨天)
  screen       离线: 月榜 → 每人逐月收益 → 扣沪深300 → 同窗口比/≥6 个月(≈120 交易日)/扣大盘夏普/分段多数跑赢/多重检验门槛
               → 短名单(正例候选 + 风格相近负例) scripts/tzzb/rank_shortlist_<日>.json + 报告 scripts/tzzb/model_out/reports/rank_screen_<日>.md
  fetch-light  短名单每人 1 次日净值 + ≤4 页调仓流水(≈5 次/人) → downloads/tzzb_cand/<ledger>/
  report       离线: 日净值扣大盘夏普/回撤 + 调仓流水(建仓→清仓)持仓周期 → 三档(<3 天 / 3~20 天 / >20 天)各挑前几名 + 配负例 → 报告补"第三段"
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/rank_screen.py <probe|fetch-rank|screen|fetch-light|report> [选项]
  --reserve 600(给正式轮次留的当日额度) --wait(遇时间窗/锁就等, 不退出) --dry(不联网) --keys a,b --from 202501
  --selftest(纯离线自测, 不读网络不写正式文件)
"""
import argparse, json, math, os, random, statistics as st, subprocess, sys, time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tzzb_guard as G  # noqa: E402

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
KEYS_FILE = ROOT / "scripts" / "tzzb" / "match_keys.json"
RANKS = ROOT / "downloads" / "tzzb" / "_ranks"
MONTHLY = ROOT / "downloads" / "tzzb" / "_ranks_monthly"
CROOT = ROOT / "downloads" / "tzzb_cand"
NODE_SCRIPT = "scripts/tzzb/rank_monthly.mjs"
TODAY = datetime.now().strftime("%Y%m%d")


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def all_keys():
    j = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    return list(dict.fromkeys(j.get("known", []) + [x["key"] if isinstance(x, dict) else x for x in j.get("new_1016", [])]))


# ---------------- 抓取编排(唯一会发请求的地方; 全部经 tzzb_guard) ----------------
def run_side(node_args, need, reserve, wait, source, dry=False):
    """一次副线会话: 总闸 → 拿正式锁 → 给 node 传本次额度+时限 → 计数回写 → 403 熔断传播 → 放锁。返回 (rc, summary)"""
    if dry:
        r = subprocess.run(["node", NODE_SCRIPT, *node_args, "--dry"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN, timeout=120)
        print(r.stdout.strip()); return r.returncode, None
    while True:
        ok, why, rem = G.preflight(reserve, need)
        if ok:
            break
        if not wait or "熔断" in why or "副线今日已停" in why or "额度不足" in why:
            log(f"不发请求: {why}"); return 9, None
        log(f"等: {why}"); time.sleep(60)
    if not G.acquire_lock(wait_s=0):
        log("正式 fetch.lock 刚被占, 放弃本次"); return 9, None
    mins = G.minutes_until_blocked()
    deadline_ms = int((time.time() + max(0, mins - 2) * 60) * 1000)
    summary, rc = None, 1
    try:
        log(f"副线 {source}: 可用额度 {rem}(正式 {G.day_budget()} 已用 {G.used_today()} 预留 {reserve}), 时限 {mins - 2} 分钟")
        r = subprocess.run(["node", NODE_SCRIPT, *node_args, "--i-am-wrapped", "--max-req", str(rem), "--deadline", str(deadline_ms)],
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN, timeout=mins * 60 + 600)
        rc = r.returncode
        for line in (r.stdout or "").splitlines():
            if line.startswith("JSON:"):
                summary = json.loads(line[5:])
        tail = [l for l in (r.stdout or "").splitlines() if l.strip() and not l.startswith("JSON:")][-3:]
        log(f"  rc={rc} {' | '.join(tail)[:300]} {(r.stderr or '').strip()[-200:]}")
    finally:
        n = (summary or {}).get("requests")
        if n is None:
            n = need   # 拿不到计数(崩溃)按最少需要量从严记
        total = G.add_requests(n)
        log(f"  计数回写正式: +{n} → 今日 {total}")
        if rc == 5:
            info = "; ".join((summary or {}).get("errors") or [])[:200]
            G.write_ban(f"{source}: {info}", source=f"side:{source}", req_today=total)
            G.write_side_stop(f"{source} 浏览器代发仍 Nginx 403: {info}")
            log("  疑封: 已写正式 ban.json(6h) + side_stop(副线停到次日)")
        G.release_lock()
    return rc, summary


def cmd_probe(a):
    rc, s = run_side(["--probe"], 4, a.reserve, a.wait, "probe", a.dry)
    if not a.dry and rc in (0, 5):
        G.write_probe(rc == 0, "; ".join((s or {}).get("done") or (s or {}).get("errors") or []))
    log({0: "探测通过: 可以继续抓", 5: "仍 403: 已熔断, 停到次日", 9: "未发请求"}.get(rc, f"探测失败 rc={rc}(非 403, 不熔断; 看日志)"))
    return rc


def cmd_fetch_rank(a):
    keys = a.keys.split(",") if a.keys else all_keys()
    rc, _ = run_side(["--overall", "--keys", ",".join(keys)], 25, a.reserve, a.wait, "rank-overall", a.dry)
    if rc not in (0, 3) and not a.dry:
        return rc
    while True:
        args = ["--monthly", "--keys", ",".join(keys)] + (["--from", a.from_] if a.from_ else [])
        rc, s = run_side(args, 50, a.reserve, a.wait, "rank-monthly", a.dry)
        if a.dry or rc != 3 or not a.wait:
            return rc
        if G.remaining(a.reserve) < 50:
            log("今日副线额度用完, 明天续(断点续传)"); return 3
        log(f"时间窗到/本轮停, 待续 {s and s.get('pending')}; 等窗口再续")


def cmd_fetch_light(a):
    f = Path(a.cands) if a.cands else ROOT / "scripts" / "tzzb" / f"rank_shortlist_{TODAY}.json"
    cands = [c for c in json.loads(f.read_text(encoding="utf-8")).get("fetch", [])] if f.suffix == ".json" and "shortlist" in f.name else json.loads(f.read_text(encoding="utf-8"))
    tmp = ROOT / "scripts" / "temp" / f"rank_light_cands_{TODAY}.json"
    tmp.write_text(json.dumps(cands, ensure_ascii=False, indent=1), encoding="utf-8")
    while True:
        rc, s = run_side(["--light", str(tmp)], 10, a.reserve, a.wait, "light", a.dry)
        if a.dry or rc != 3 or not a.wait or G.remaining(a.reserve) < 10:
            return rc


# ---------------- 离线: 基准 ----------------
def bench_monthly(symbol="sh000300"):
    """沪深300 月收益 {YYYYMM: r}; 行情库只读"""
    sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
    from kline_db import db
    c = db()
    try:
        cur = c.cursor()
        cur.execute("select trade_date, close from kline_day where symbol=%s and trade_date>='2024-12-01' order by trade_date", (symbol,))
        rows = [(d.strftime("%Y%m%d"), float(x)) for d, x in cur.fetchall()]
    finally:
        c.close()
    return rows


def month_returns(daily):
    last = {}
    for d, c in daily:
        last[d[:6]] = c
    ms = sorted(last)
    return {ms[i]: last[ms[i]] / last[ms[i - 1]] - 1 for i in range(1, len(ms))}


# ---------------- 离线: 月榜 → 每人逐月收益 ----------------
def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_monthly(mdir=MONTHLY):
    """{person: {"months": {YYYYMM: r}, "views": {(key,user_key)}, "pos": [...], "type": set, "enter": min}}; person=去空格用户名"""
    P = defaultdict(lambda: {"months": {}, "views": set(), "pos": [], "type": set(), "enter": "9999", "conflict": 0})
    raw = []
    for f in sorted(Path(mdir).glob("*/*.json")):
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in j.get("rows") or []:
            v = _f(r.get("monthly_profit"))
            if v is None:
                continue
            raw.append(abs(v))
            nm = str(r.get("user_name") or "").replace(" ", "").replace("　", "")
            if not nm:
                continue
            p = P[nm]
            m = j.get("month")
            if m in p["months"] and abs(p["months"][m] - v) > 1e-6:
                p["conflict"] += 1   # 同人跨场同月收益不一致(不同账户/不同口径), 取均值并计数
                p["months"][m] = (p["months"][m] + v) / 2
            else:
                p["months"][m] = v
            p["views"].add((j.get("match_key"), str(r.get("user_key"))))
            pr = _f(r.get("position_rate"))
            if pr is not None:
                p["pos"].append(pr)
            p["type"].add(str(r.get("type") or ""))
            if r.get("enter_date"):
                p["enter"] = min(p["enter"], str(r["enter_date"]))
    # 单位自检: 中位绝对值 >1 视为百分数
    scale = 0.01 if raw and st.median(raw) > 1 else 1.0
    if scale != 1.0:
        for p in P.values():
            p["months"] = {m: v * scale for m, v in p["months"].items()}
    return P, {"rows": len(raw), "unit": "percent→/100" if scale != 1.0 else "fraction"}


def score_person(months, bench, window):
    ex = [months[m] - bench[m] for m in window if m in months and m in bench]
    if len(ex) < len(window) or len(ex) < 3:
        return None
    sd = st.pstdev(ex)
    raw = [months[m] for m in window]
    return {"n": len(ex), "ex_mean": st.mean(ex), "sharpe_ex": (st.mean(ex) / sd * math.sqrt(12)) if sd > 1e-9 else None,
            "win_frac": sum(1 for x in ex if x > 0) / len(ex), "cum": math.prod(1 + x for x in raw) - 1, "vol": st.pstdev(raw) * math.sqrt(12),
            "worst": min(raw)}


def existing_names():
    s = set()
    for f in [ROOT / "scripts" / "tzzb" / "tzzb_ledgers.json", ROOT / "scripts" / "tzzb" / "candidates_20261016.json"]:
        try:
            for x in json.loads(f.read_text(encoding="utf-8")):
                s.add(str(x.get("name") or "").replace(" ", ""))
        except (OSError, ValueError):
            pass
    return s


def screen(P, bench, window, k_pos=30, min_months=6):
    T = len(window)
    rows = []
    for nm, p in P.items():
        if len(p["months"]) < min_months:
            continue
        s = score_person(p["months"], bench, window)
        if not s or s["sharpe_ex"] is None:
            continue
        rows.append({"name": nm, **s, "months_total": len(p["months"]), "pos_rate": st.median(p["pos"]) if p["pos"] else None,
                     "manual": any(t and t != "common" for t in p["type"]), "views": sorted(p["views"]), "conflict": p["conflict"], "enter": p["enter"]})
    N = len(rows)
    # 多重检验门槛: N 个"零本事"的人里 T 个月夏普的期望最大值 ≈ sqrt(2 ln N)/sqrt(T) (月) × sqrt(12)
    thr = math.sqrt(2 * math.log(max(N, 2))) / math.sqrt(T) * math.sqrt(12) if N else None
    ok = [r for r in rows if r["win_frac"] > 0.5 and not r["manual"]]
    ok.sort(key=lambda r: -r["sharpe_ex"])
    pos = ok[:k_pos]
    # 负例: 每个正例配 1 个风格相近(仓位率 ±0.15, 年化波动 ±35%)、扣大盘夏普<0 且分段多数跑输的人
    used, neg = set(), []
    bad = [r for r in rows if r["sharpe_ex"] < 0 and r["win_frac"] < 0.5]
    for r in pos:
        best, bd = None, 9e9
        for b in bad:
            if b["name"] in used or r["pos_rate"] is None or b["pos_rate"] is None:
                continue
            if abs(b["pos_rate"] - r["pos_rate"]) > 0.15 or not (0.65 <= (b["vol"] / r["vol"] if r["vol"] else 0) <= 1.35):
                continue
            dist = abs(b["pos_rate"] - r["pos_rate"]) / 0.15 + abs(math.log(b["vol"] / r["vol"]))
            if dist < bd:
                best, bd = b, dist
        if best:
            used.add(best["name"]); neg.append({**best, "pair_of": r["name"]})
    return {"N_eligible": N, "window": window, "mt_threshold": thr, "pos": pos, "neg": neg, "n_pass_gate": len(ok)}


def _ledger_id(nm, i):
    asc = "".join(ch for ch in nm.lower() if ch.isascii() and ch.isalnum())
    return f"rk_{asc[:16] or 'u'}{i:03d}"


def cmd_screen(a):
    P, meta = load_monthly()
    if not P:
        log(f"月榜数据为空({MONTHLY}); 先 fetch-rank"); return 2
    bench = month_returns(bench_monthly())
    now = datetime.now()
    last_full = (now.replace(day=1) - timedelta(days=1)).strftime("%Y%m")
    ms = sorted(m for m in bench if m <= last_full)
    window = ms[-a.window:]
    res = screen(P, bench, window, a.k)
    have = existing_names()
    fetch, L = [], []
    for i, r in enumerate(res["pos"] + res["neg"]):
        key, uk = r["views"][0]
        fetch.append({"ledger": _ledger_id(r["name"], i), "name": r["name"], "key": key, "user_key": uk, "kind": "rank_neg" if r in res["neg"] else "rank_pos", "pair_of": r.get("pair_of")})
    out = {"generated": now.isoformat(timespec="seconds"), "meta": meta, "window": window, "N_eligible": res["N_eligible"], "n_pass_gate": res["n_pass_gate"],
           "mt_threshold": res["mt_threshold"], "pos": res["pos"], "neg": res["neg"], "fetch": fetch}
    sl = ROOT / "scripts" / "tzzb" / f"rank_shortlist_{TODAY}.json"
    sl.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    pct = lambda x: "-" if x is None else f"{x:+.1%}"
    L += [f"# 比赛月榜筛人（{now:%Y-%m-%d %H:%M}，零 token；第二段=月榜粗筛）", "",
          f"> 数据: `downloads/tzzb/_ranks_monthly/`（{len(list(MONTHLY.glob('*/*.json')))} 个 比赛×月 文件，{meta['rows']} 行，单位 {meta['unit']}）；基准 沪深300 月收益（行情库只读）。",
          f"> 标准（A14/real_trade_sources §4.7）: 只在同一窗口比（{window[0]}~{window[-1]} 共 {len(window)} 个完整月，窗口内每月都有数的人才参与）；"
          f"月榜出现 ≥6 个月（≈120 交易日）；按扣沪深300 后的月度夏普（年化）排序；分段（逐月）多数跑赢；`type≠common`（手录等）剔除；"
          f"每个正例配 1 个风格相近（仓位率 ±15pp、波动 ±35%）且扣大盘夏普<0、多数月跑输的负例。", "",
          f"- 合格样本 {res['N_eligible']} 人，过闸（多数月跑赢、非手录）{res['n_pass_gate']} 人；**多重检验门槛**（{res['N_eligible']} 个零本事的人里最好的那个，扣大盘夏普期望能到）≈ {res['mt_threshold'] and round(res['mt_threshold'], 2)}——低于它的排名大概率是运气。",
          f"- 月榜只能看收益，**持仓周期三档要第三段**（fetch-light 每人 ~5 次请求拿日净值+调仓流水）再分。", "",
          "| # | 用户 | 窗口累计 | 扣大盘夏普 | 跑赢月占比 | 最差月 | 年化波动 | 仓位率 | 月榜月数 | 已在库 | 过门槛 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(res["pos"], 1):
        L.append(f"| {i} | {r['name']} | {pct(r['cum'])} | {r['sharpe_ex']:.2f} | {r['win_frac']:.0%} | {pct(r['worst'])} | {r['vol']:.0%} | {'-' if r['pos_rate'] is None else f'{r['pos_rate']:.0%}'} | {r['months_total']} | {'是' if r['name'] in have else ''} | {'是' if res['mt_threshold'] and r['sharpe_ex'] >= res['mt_threshold'] else ''} |")
    L += ["", "**配对负例**（风格相近、结果差；进第三段一起抓，用来做'这条规则负例也遵守吗'的对照）", "", "| 负例 | 配给 | 窗口累计 | 扣大盘夏普 | 跑赢月占比 | 仓位率 |", "|---|---|---|---|---|---|"]
    for r in res["neg"]:
        L.append(f"| {r['name']} | {r['pair_of']} | {pct(r['cum'])} | {r['sharpe_ex']:.2f} | {r['win_frac']:.0%} | {'-' if r['pos_rate'] is None else f'{r['pos_rate']:.0%}'} |")
    L += ["", f"下一步: `scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/rank_screen.py fetch-light --wait`（{len(fetch)} 人 × ≈5 次）→ `report`。短名单: `{sl.relative_to(ROOT)}`"]
    rp = ROOT / "scripts" / "tzzb" / "model_out" / "reports" / f"rank_screen_{TODAY}.md"
    rp.write_text("\n".join(L) + "\n", encoding="utf-8")
    log(f"短名单 {sl.relative_to(ROOT)}; 报告 {rp.relative_to(ROOT)}")
    return 0


# ---------------- 离线: 第三段(日净值 + 调仓流水) ----------------
def hold_from_flow(d):
    """position_change 日汇总: buy_sell 3=建仓 4=清仓 → 每段持仓天数(日历日); 返回 (段列表, 每周笔数)"""
    rows = []
    for f in sorted(Path(d).glob("position_change_p*.json")):
        try:
            rows += json.loads(f.read_text(encoding="utf-8")).get("ex_data", {}).get("change_list") or []
        except (OSError, ValueError, AttributeError):
            pass
    rows = sorted(rows, key=lambda x: str(x.get("trans_date")))
    open_, segs = {}, []
    for x in rows:
        c, bs, t = str(x.get("stock_code")), str(x.get("buy_sell")), str(x.get("trans_date"))[:10]
        if c.startswith(("204", "1318")):
            continue
        if bs == "3" or (bs in ("1", "5", "7", "9") and c not in open_):
            open_.setdefault(c, t)
        elif bs == "4" and c in open_:
            segs.append((datetime.strptime(t, "%Y-%m-%d") - datetime.strptime(open_.pop(c), "%Y-%m-%d")).days)
    span = (datetime.strptime(str(rows[-1]["trans_date"])[:10], "%Y-%m-%d") - datetime.strptime(str(rows[0]["trans_date"])[:10], "%Y-%m-%d")).days if len(rows) > 1 else 0
    return segs, (len(rows) / max(1, span / 7)) if span else None, len(open_)


def nav_stats(d, bench_daily):
    try:
        il = json.loads((Path(d) / "nav_daily.json").read_text(encoding="utf-8"))["ex_data"]["index_list"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    import ast
    il = ast.literal_eval(il) if isinstance(il, str) else il
    n = [(str(x["date"]), float(x["index"])) for x in il if float(x.get("index") or 0) > 0]
    if len(n) < 20:
        return None
    b = dict(bench_daily)
    r = [(n[i][0], n[i][1] / n[i - 1][1] - 1) for i in range(1, len(n))]
    bk = sorted(b)
    bret = {bk[i]: b[bk[i]] / b[bk[i - 1]] - 1 for i in range(1, len(bk))}
    ex = [x - bret[d] for d, x in r if d in bret]
    peak, mdd = n[0][1], 0.0
    for _, v in n:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    sd = st.pstdev(ex) if len(ex) > 2 else 0
    return {"days": len(n), "window": [n[0][0], n[-1][0]], "total": n[-1][1] / n[0][1] - 1, "mdd": mdd,
            "sharpe_ex_d": (st.mean(ex) / sd * math.sqrt(244)) if sd > 1e-12 else None}


def tier(h):
    return None if h is None else ("短(<3天)" if h < 3 else ("中(3~20天)" if h <= 20 else "长(>20天)"))


def cmd_report(a):
    sl = Path(a.cands) if a.cands else ROOT / "scripts" / "tzzb" / f"rank_shortlist_{TODAY}.json"
    S = json.loads(sl.read_text(encoding="utf-8"))
    bench = bench_monthly()
    res = []
    for c in S["fetch"]:
        d = CROOT / c["ledger"]
        ns = nav_stats(d, bench)
        segs, tpw, still = hold_from_flow(d) if (d / "position_change_p1.json").exists() else ([], None, 0)
        h = st.median(segs) if segs else None
        res.append({**c, "nav": ns, "hold_med": h, "hold_p75": sorted(segs)[int(len(segs) * .75)] if segs else None, "segs": len(segs), "open_now": still,
                    "trades_pw": tpw, "tier": tier(h)})
    by = defaultdict(list)
    for r in res:
        if r["kind"] == "rank_pos" and r["nav"] and r["nav"]["sharpe_ex_d"] is not None and r["tier"]:
            by[r["tier"]].append(r)
    L = ["", f"## 第三段（{datetime.now():%Y-%m-%d %H:%M}）: 日净值 + 调仓流水 → 持仓周期三档", "",
         "> 持仓周期 = 调仓流水（每日每票 1 条汇总）里 建仓→清仓 的日历天数中位；流水只拉了前 ≤4 页（最近 ≤200 条），活跃账户只代表近期风格。夏普 = 日净值扣沪深300 后年化。", ""]
    for t in ["长(>20天)", "中(3~20天)", "短(<3天)"]:
        xs = sorted(by.get(t, []), key=lambda r: -r["nav"]["sharpe_ex_d"])
        L += [f"### {t}（{len(xs)} 人，前 {a.per_tier} 名推荐）", "", "| 用户 | 净值窗口 | 区间收益 | 最大回撤 | 扣大盘夏普(日) | 持仓中位/P75 天 | 每周笔数 | 配对负例 |", "|---|---|---|---|---|---|---|---|"]
        for r in xs[:a.per_tier]:
            ng = next((x for x in res if x.get("pair_of") == r["name"]), None)
            nv = r["nav"]
            L.append(f"| {r['name']} | {nv['window'][0]}~{nv['window'][1]}({nv['days']}日) | {nv['total']:+.0%} | {nv['mdd']:.0%} | {nv['sharpe_ex_d']:.2f} | {r['hold_med']}/{r['hold_p75']} | "
                     f"{'-' if r['trades_pw'] is None else round(r['trades_pw'], 1)} | {ng['name'] + ('(' + (tier(ng['hold_med']) or '?') + ')') if ng else '-'} |")
        L.append("")
    rp = ROOT / "scripts" / "tzzb" / "model_out" / "reports" / f"rank_screen_{TODAY}.md"
    with rp.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    (ROOT / "scripts" / "tzzb" / f"rank_screen_stage3_{TODAY}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    log(f"第三段写入 {rp.relative_to(ROOT)}")
    return 0


# ---------------- 自测(离线) ----------------
def _selftest():
    import tempfile
    random.seed(7)
    d = Path(tempfile.mkdtemp(prefix="rank_screen_st_"))
    window = [f"2026{m:02d}" for m in range(4, 10)]
    bench = {m: 0.01 for m in window}
    # 造 3 场 × 6 月: good=每月 +4%(跑赢 6/6), lucky=一个月 +80% 其余 -2%, bad=每月 -3%, 同人跨场
    for key in ["K1", "K2"]:
        for m in window:
            rows = []
            for nm, f in [("good", lambda m: 0.04 + (0.01 if int(m) % 2 else -0.01)), ("lucky", lambda m: 0.8 if m == "202606" else -0.02),
                          ("bad", lambda m: -0.03 + (0.012 if int(m) % 2 else -0.012)), ("short", lambda m: 0.05)]:
                if nm == "short" and m < "202608":
                    continue
                rows.append({"user_name": nm, "user_key": f"{key}{nm}", "monthly_profit": str(round(f(m) * 100, 4)), "position_rate": "0.8", "type": "common", "enter_date": "2026-03-01"})
            (d / key).mkdir(exist_ok=True)
            (d / key / f"{m}.json").write_text(json.dumps({"match_key": key, "month": m, "rows": rows}), encoding="utf-8")
    P, meta = load_monthly(d)
    assert meta["unit"].startswith("percent"), meta
    assert abs(P["lucky"]["months"]["202606"] - 0.8) < 1e-6 and len(P["short"]["months"]) == 2
    res = screen(P, bench, window, k_pos=5)
    names = [r["name"] for r in res["pos"]]
    assert names == ["good"], names              # lucky 多数月跑输被闸掉; short 月数不足
    assert [r["name"] for r in res["neg"]] == ["bad"] and res["neg"][0]["pair_of"] == "good", res["neg"]
    assert res["mt_threshold"] and res["mt_threshold"] > 1
    # 持仓周期(流水)
    pc = d / "c1"; pc.mkdir()
    flow = [{"stock_code": "A", "buy_sell": "3", "trans_date": "2026-01-01 10:00:00"}, {"stock_code": "A", "buy_sell": "4", "trans_date": "2026-01-31 10:00:00"},
            {"stock_code": "B", "buy_sell": "3", "trans_date": "2026-01-05 10:00:00"}, {"stock_code": "B", "buy_sell": "4", "trans_date": "2026-01-06 10:00:00"},
            {"stock_code": "C", "buy_sell": "3", "trans_date": "2026-01-07 10:00:00"}]
    (pc / "position_change_p1.json").write_text(json.dumps({"ex_data": {"change_list": flow}}), encoding="utf-8")
    segs, tpw, still = hold_from_flow(pc)
    assert sorted(segs) == [1, 30] and still == 1 and tier(st.median(segs)) == "中(3~20天)"
    # month_returns
    mr = month_returns([("20260130", 100), ("20260227", 110), ("20260331", 99)])
    assert abs(mr["202602"] - 0.1) < 1e-9 and abs(mr["202603"] + 0.1) < 1e-9
    print("rank_screen selftest PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["probe", "fetch-rank", "screen", "fetch-light", "report"])
    ap.add_argument("--reserve", type=int, default=G.DEFAULT_RESERVE)
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--keys")
    ap.add_argument("--from", dest="from_")
    ap.add_argument("--cands")
    ap.add_argument("--window", type=int, default=6)
    ap.add_argument("--k", type=int, default=30)
    ap.add_argument("--per-tier", type=int, default=3)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if not a.cmd:
        print(__doc__); return 1
    return {"probe": cmd_probe, "fetch-rank": cmd_fetch_rank, "screen": cmd_screen, "fetch-light": cmd_fetch_light, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main() or 0)
