# -*- coding: utf-8 -*-
"""screen_candidates.py — 候选导师(非短线风格, 10/16 晚用户人工找的 7 位)观察抓取 + 零 token 筛选
1) 抓取: 逐个 node scripts/tzzb/fetch_tzzb.mjs --ledgers <候选清单> --root downloads/tzzb_cand --ledger <id>
   (独立产物目录, 不进正式清单/日报/体检; 账本间隔 60~120s 随机)
   10/17 agent③: 改成**共用正式额度与熔断**(scripts/tzzb/tzzb_guard.py, 真源=downloads/tzzb/_guard):
   - 每天首次抓之前先 1 次探测(rank_screen.py probe); 仍 403 → 正式熔断 6h + 副线停到次日
   - 每个账本开抓前: 正式熔断/副线停/时间窗(15:10 前不发; 15~23 点 :05~:30 让正式轮次)/正式额度(扣 reserve 后)/正式锁 全过才抓;
     抓的期间持有正式 fetch.lock(正式轮次撞上 exit 1 下一轮补); 子进程额度=正式剩余(把候选计数器预置成 2000−剩余)
   - 抓完把实际请求数加回正式 requests_<日>.json; 子进程 exit 5 且写了候选 ban.json=真封 → 传播到正式 ban.json; exit 5 无 ban=额度用完
   - 已有 position_change_p1.json 的账本走增量(补没抓完的 change_bs/day_positions), 首次才 --full
   - 一个账本最长跑到下一个让行窗口前 3 分钟, 超时杀进程树(下次增量续上)
2) 筛选: 收益/最大回撤(不卡死, 只报告)/数据天数/收盘总仓/持股只数/持股天数/换手(笔数每周)/板块分布/与现有 11 位正例日收益相关
   → docs/research/candidates_screen_<日>.md + scripts/tzzb/candidates_screen.json
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/screen_candidates.py [--fetch] [--report] [--only id] [--cands 清单.json] [--reserve 600] [--wait] [--dry]
     (都不给=先抓后筛; --wait=遇时间窗/锁就等; --dry=只打印每个账本会怎么抓, 不发请求)
"""
import argparse, ast, json, os, random, statistics as st, subprocess, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAND = ROOT / "scripts" / "tzzb" / "candidates_20261016.json"
CROOT = ROOT / "downloads" / "tzzb_cand"
MAIN = ROOT / "downloads" / "tzzb"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tzzb_guard as G  # noqa: E402  10/17: 共用正式额度/熔断
CGUARD = CROOT / "_guard"
MIN_NEED = 150      # 一个候选账本增量至少要这么多额度才开抓(首次全量会用到上千; 不够的中途停, 下次增量续)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import mentors  # noqa: E402  10/17 二B-4: 导师登记表
POS = [x for x in mentors.ids("tzzb") if x not in ("buchitudou0", "chong5000w")]   # 现役正例(原名单即不含土豆/冲5000w)


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def _kill_tree(pid):
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, creationflags=NOWIN)


def _cand_count():
    return G.used_today(CGUARD)


def fetch(cands, cand_file=CAND, reserve=G.DEFAULT_RESERVE, wait=False, dry=False):
    if not dry and not G.probe_ok_today():
        log("今天还没探测过, 先 1 次探测(rank_screen.py probe)")
        r = subprocess.run([sys.executable, "-X", "utf8", "scripts/tzzb/rank_screen.py", "probe", "--reserve", str(reserve)] + (["--wait"] if wait else []),
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN, timeout=1800)
        log("  " + " | ".join(l for l in (r.stdout or "").splitlines()[-3:]))
        if r.returncode != 0:
            log(f"探测未通过(rc={r.returncode}), 本轮不抓"); return
    for i, c in enumerate(cands):
        full = not (CROOT / c["ledger"] / "position_change_p1.json").exists()
        if dry:
            ok, why, rem = G.preflight(reserve, MIN_NEED)
            log(f"[dry] {c['ledger']}({c['name']}): {'--full 首抓' if full else '增量续抓'}; 此刻总闸 {'通过' if ok else '不通过: ' + why}; 副线可用额度 {G.remaining(reserve)}")
            continue
        if i:
            time.sleep(random.uniform(60, 120))
        while True:
            ok, why, rem = G.preflight(reserve, MIN_NEED)
            mins = G.minutes_until_blocked() if ok else 0
            if ok and mins >= 15:
                break
            why = why or f"离下一个让行窗口只剩 {mins} 分钟"
            if not wait or "熔断" in why or "副线今日已停" in why or "额度不足" in why:
                log(f"停: {why}"); return
            log(f"等 60s: {why}"); time.sleep(60)
        if not G.acquire_lock():
            log("正式 fetch.lock 刚被占, 本轮停"); return
        n0 = n1 = 0; rc = None; cand_ban = CGUARD / "ban.json"
        try:
            CGUARD.mkdir(parents=True, exist_ok=True)
            if cand_ban.exists():   # 熔断以正式为准; 旧逻辑留下的候选 ban 归档, 免得子进程误判
                cand_ban.rename(CGUARD / f"ban_archived_{datetime.now():%Y%m%d%H%M%S}.json")
            n0 = max(0, G.day_budget(CGUARD) - rem)          # 子进程额度 = 正式剩余(扣 reserve 后)
            (CGUARD / f"requests_{datetime.now():%Y-%m-%d}.json").write_text(json.dumps({"n": n0}), encoding="utf-8")
            limit_s = max(60, (mins - 3) * 60)
            log(f"抓 {c['ledger']}({c['name']}) {'--full' if full else '增量'}; 额度 {rem}, 最长 {limit_s // 60} 分钟")
            cmd = ["node", "scripts/tzzb/fetch_tzzb.mjs", "--ledgers", str(cand_file), "--root", str(CROOT), "--ledger", c["ledger"]] + (["--full"] if full else [])
            pr = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
            try:
                out, err = pr.communicate(timeout=limit_s); rc = pr.returncode
            except subprocess.TimeoutExpired:
                _kill_tree(pr.pid); out, err = pr.communicate(); rc = "timeout"
            tail = [l for l in (out or "").splitlines() if l.strip()][-2:]
            log(f"  rc={rc} {' | '.join(tail)[:300]} {(err or '')[-200:] if rc else ''}")
        finally:
            n1 = _cand_count()
            used = max(0, n1 - n0) + (10 if rc == "timeout" else 0)   # 被杀时计数最多少记 9 次, 从严补 10
            total = G.add_requests(used)
            log(f"  计数回写正式: +{used} → 今日 {total}")
            if rc == 5 and cand_ban.exists():
                info = json.loads(cand_ban.read_text(encoding="utf-8")).get("info", "")
                G.write_ban(f"screen_candidates {c['ledger']}: {info}", source="side:screen_candidates", req_today=total)
                G.write_side_stop(f"候选抓取三层全败含 BLOCKED: {info}"[:200])
                log("  真封(三层全败含 BLOCKED): 已传播到正式 ban.json + 副线停到次日")
            G.release_lock()
        if rc == 5:
            log("子进程 exit 5(封禁或额度用完), 停止本轮"); return


def nav(d):
    try:
        il = json.loads((d / "nav_daily.json").read_text(encoding="utf-8"))["ex_data"]["index_list"]
        il = ast.literal_eval(il) if isinstance(il, str) else il
        return [(str(x["date"]), float(x["index"])) for x in il if float(x.get("index") or 0) > 0]
    except Exception:   # noqa: BLE001
        return []


def rets(n):
    return {n[i][0]: n[i][1] / n[i - 1][1] - 1 for i in range(1, len(n))}


def corr(a, b):
    ds = sorted(set(a) & set(b))
    if len(ds) < 30:
        return None
    x, y = [a[k] for k in ds], [b[k] for k in ds]
    try:
        return st.correlation(x, y)
    except st.StatisticsError:
        return None


def board(c):
    c = str(c)
    if c.startswith(("688", "689")): return "科创"
    if c.startswith(("300", "301")): return "创业板"
    if c.startswith(("4", "8", "92")): return "北交所"
    if c.startswith(("11", "12")): return "转债"
    if c.startswith(("5", "15", "16", "18")): return "ETF"
    if len(c) == 5: return "港股"
    return "主板"


def stats(d):
    n = nav(d)
    if len(n) < 5:
        return None
    peak, mdd = n[0][1], 0.0
    for _, v in n:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    days = (datetime.strptime(n[-1][0], "%Y%m%d") - datetime.strptime(n[0][0], "%Y%m%d")).days
    tot = n[-1][1] / n[0][1] - 1
    out = {"window": [n[0][0], n[-1][0]], "nav_days": len(n), "total": tot, "ann": (1 + tot) ** (365 / max(days, 1)) - 1 if days > 30 else None, "mdd": mdd}
    try:
        dp = json.loads((d / "day_positions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        dp = {}
    tp, nh, runs, cur, bd = [], [], [], {}, {}
    for day in sorted(dp):
        ps = [p for p in (dp[day] or {}).get("list") or [] if float(p.get("position_percent") or 0) > 0.02 and not str(p.get("code", "")).startswith(("204", "1318"))]
        tp.append(min(3.0, sum(float(p["position_percent"]) for p in ps))); nh.append(len(ps))
        codes = {str(p.get("code")) for p in ps}
        for c in codes:
            bd[board(c)] = bd.get(board(c), 0) + 1
        for c in list(cur):
            if c not in codes:
                runs.append(cur.pop(c))
        for c in codes:
            cur[c] = cur.get(c, 0) + 1
    out.update({"dp_days": len(tp), "total_pos_med": st.median(tp) if tp else None, "n_hold_med": st.median(nh) if nh else None,
                "hold_days_med": st.median(runs) if runs else None, "hold_days_p75": sorted(runs)[int(len(runs) * .75)] if runs else None,
                "board": {k: round(v / sum(bd.values()), 2) for k, v in sorted(bd.items(), key=lambda kv: -kv[1])} if bd else {}})
    trades = 0
    for f in d.glob("position_change_p*.json"):
        try:
            trades += len(json.loads(f.read_text(encoding="utf-8")).get("ex_data", {}).get("change_list") or [])   # 10/17 修: 原读 "list" 恒空
        except (OSError, ValueError, AttributeError):
            pass
    out["trades_per_week"] = round(trades / max(1, len(n) / 5), 1) if trades else None
    R = rets(n)
    cs = {m: corr(R, rets(nav(MAIN / m))) for m in POS}
    cs = {m: round(v, 2) for m, v in cs.items() if v is not None}
    out["corr_max"] = max(cs.items(), key=lambda kv: kv[1]) if cs else None
    out["corr_mean"] = round(st.mean(cs.values()), 2) if cs else None
    return out


def report(cands):
    res = {}
    L = [f"# 候选导师筛选（{datetime.now():%Y-%m-%d %H:%M}，零 token）", "",
         "> 你 10/16 晚人工找的非短线候选；回撤按你说的不卡死，只报告。对照：现有 11 位正例持股天数中位多为 1~2 天。", "",
         "> 持股天数三种口径（10/17 加，见 scripts/tzzb/hold_reconcile.py）：**段中位**=每只票连续持有段一段一票取中位（小仓快进快出与底仓长拿同权）；"
         "**资金加权段**=同样的段按收盘仓位%加权（钱实际拿多久）；**逐笔金额加权**=逐笔买卖腿按数量 FIFO 配对后按金额加权的持有天数（含未平仓到最后一天）。三者差很大时=杠铃型（底仓长拿 + 小仓快进快出）。", "",
         "| 候选 | 数据窗口 | 区间收益 | 年化 | 最大回撤 | 收盘总仓中位 | 持股只数中位 | 持股天数 段中位/P75 | 资金加权段 | 逐笔金额加权(≤3天金额占比) | 每周成交笔 | 板块 | 与现有正例相关 均值/最高 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in cands:
        s = stats(CROOT / c["ledger"])
        res[c["ledger"]] = {"name": c["name"], **(s or {"error": "无数据"})}
        if not s:
            L.append(f"| {c['name']} | 无数据(没抓到/视图失效) | | | | | | | | | | | |"); continue
        try:
            from hold_reconcile import summarize as _hr
            hr = _hr(CROOT / c["ledger"])
        except Exception as e:   # noqa: BLE001  口径核对失败不影响主表
            hr = {"error": str(e)[:80]}
        res[c["ledger"]]["hold_reconcile"] = hr
        cw = (hr.get("dp") or {}).get("cap_weighted_run"); fw = hr.get("fifo") or {}
        f = lambda x, p=True: "-" if x is None else (f"{x:+.0%}" if p else f"{x}")
        L.append(f"| {c['name']} | {s['window'][0]}~{s['window'][1]}({s['nav_days']}日) | {f(s['total'])} | {f(s['ann'])} | {s['mdd']:.0%} | "
                 f"{'-' if s['total_pos_med'] is None else f'{s['total_pos_med']:.0%}'} | {f(s['n_hold_med'], False)} | {f(s['hold_days_med'], False)}/{f(s['hold_days_p75'], False)} | "
                 f"{'-' if cw is None else f'{cw} 天'} | {'-' if fw.get('amt_weighted_days_all') is None else f'{fw['amt_weighted_days_all']} 天({fw['amt_share_le3d']:.0%})'} | "
                 f"{f(s['trades_per_week'], False)} | {' '.join(f'{k}{v:.0%}' for k, v in list(s['board'].items())[:3])} | {s['corr_mean']}/{s['corr_max']} |")
    (ROOT / "scripts" / "tzzb" / "candidates_screen.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    out = ROOT / "docs" / "research" / f"candidates_screen_{datetime.now():%Y%m%d}.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L)); print(f"报告: {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--cands", help="候选清单(缺省 candidates_20261016.json; 格式同 tzzb_ledgers.json)")
    ap.add_argument("--reserve", type=int, default=G.DEFAULT_RESERVE, help="给正式轮次留的当日额度")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    cf = Path(a.cands).resolve() if a.cands else CAND
    cands = [c for c in json.loads(cf.read_text(encoding="utf-8")) if not a.only or c["ledger"] == a.only]
    if a.fetch or not a.report:
        fetch(cands, cf, a.reserve, a.wait, a.dry)
        if a.dry:
            return
    if a.report or not a.fetch:
        report(cands)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
