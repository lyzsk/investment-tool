# -*- coding: utf-8 -*-
"""rerun_day.py — paper 某交易日整日重跑(10/16 用户令: 方案 A 首日暴露名单闸/子链无 05 等问题, 改完后重跑 10/16)
步骤(全在沙盒 scripts/temp/rerun_<日>/sb, 实盘 books 只在最后 --merge 时整本替换, 且先整目录备份):
  prep : 实盘 books 复制进沙盒 → 每本账剔除当日 orders/trades/nav, 现金/持仓由"前一日为止的成交流水"从 10 万重放得到
         (先用全部流水重放校验能否复现当前现金/持仓, 复现不了的账本拒绝处理并报出) → 当日各 slot 的实盘 facts 原样拷进沙盒
  run  : 按时段推进: 0915 全部链并发 → 分钟线撮合到下一个时段 → 该时段排程内的链子链并发 → 撮合 → … → 15:00 → 日线兜底撮合 → EOD
         每条链 as-of 模式(PAPER_ROOT=沙盒, PAPER_ASOF=日), run_dir=results/<skill>_chain/asof-<日>; 成本记 tok/, 超预算停
  merge: 沙盒账本整本替换实盘(实盘先备份到 scripts/dfcf/paper/books.bak-rerun<日>-<时刻>), 实盘 nav csv 由 matcher --eod 重算
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/rerun_day.py --date 2026-10-16 prep|run|merge [--budget 350] [--dry]
      run --mix: 每个 slot 链跑完后调 mix_plans.py 出混合账本单(失败不影响主流程), EOD 后 mix_plans --learn
      --tag X(10/17 A4 开关 A/B 沙盒): 沙盒目录改为 scripts/temp/rerun_<日>-X、链产物目录 asof-<日>-X(CHAIN_RUN_TAG), 不碰正式重跑目录;
              带 tag 时禁止 merge(A/B 臂只评估不合入); 各臂开关用环境变量传(如 CHAIN_T_PROFILE=1), 驱动器 _flag() 环境变量优先
"""
import argparse, csv, json, os, shutil, subprocess, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LIVE = ROOT / "scripts" / "dfcf" / "paper"
PY = str(ROOT / "scripts" / "venv" / "Scripts" / "python.exe")
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import a_rules as _AR  # noqa: E402  10/17: 交易规则统一模块


def FEE(side, amt, code=None, date=None):
    """10/17: 同 matcher.mjs fee() = a_rules.fees 的 佣金(万2.5, 最低5元)+印花税(只收股票卖方; 转债/ETF/LOF 免), 过户费不计。
    code=None → 按股票算(= 10/16 前旧口径)"""
    f = _AR.fees(side, amt, code or "600000", date, commission_rate=0.00025, min_commission=5.0)
    return f["commission"] + f["stamp"]


TAG = None   # --tag: A/B 沙盒臂名


def log(here, m):
    line = f"[{datetime.now():%m-%d %H:%M:%S}] {m}"
    print(line, flush=True)
    with open(here / "run.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def replay_trades(trades, upto=None):
    """按流水顺序从 10 万重放现金/持仓(成本公式同 matcher fill); upto=只重放该日之前的成交"""
    cash, pos = 100000.0, {}
    for t in trades:
        if upto and str(t["id"])[:10] >= upto:
            continue
        amt, f = t["price"] * t["qty"], float(t.get("fee") or 0)
        if t["side"] == "BUY":
            cash -= amt + f
            p = pos.get(t["code"], {"qty": 0, "cost": 0.0})
            p["cost"] = (p["cost"] * p["qty"] + amt + f) / (p["qty"] + t["qty"]); p["qty"] += t["qty"]
            pos[t["code"]] = p
        else:
            cash += amt - f
            p = pos.get(t["code"])
            if p:
                p["qty"] -= t["qty"]
                if p["qty"] <= 0:
                    pos.pop(t["code"])
    return cash, pos


def prep(day, here):
    sb = here / "sb"
    if sb.exists():
        shutil.rmtree(sb)
    (sb / "books").mkdir(parents=True)
    (sb / "plans").mkdir()
    bad = []
    for f in sorted((LIVE / "books").glob("A-*.json")):
        b = json.loads(f.read_text(encoding="utf-8"))
        if f.stem == "A-tzzb":
            continue
        cash_all, pos_all = replay_trades(b.get("trades", []))
        ok = abs(cash_all - b["cash"]) < 2 and {c: p["qty"] for c, p in pos_all.items()} == {c: p["qty"] for c, p in b["positions"].items()}
        if not ok:
            bad.append(f"{f.stem}: 流水重放 现金 {cash_all:.2f} vs 账本 {b['cash']:.2f}, 持仓 {sorted(pos_all)} vs {sorted(b['positions'])}")
            continue
        cash, pos = replay_trades(b["trades"], upto=day)
        b["orders"] = [o for o in b["orders"] if o.get("date") != day]
        b["trades"] = [t for t in b["trades"] if str(t["id"])[:10] != day]
        b["nav"] = [n for n in b["nav"] if n.get("date") != day]
        b["cash"], b["positions"] = round(cash, 4), {c: {"qty": p["qty"], "cost": p["cost"]} for c, p in pos.items()}
        b.setdefault("chain", []).append({"at": datetime.now().isoformat(), "why": f"rerun_day prep: 剔除 {day} 当日, 回到前一日收盘状态", "prev": b.get("lastHash")})
        (sb / "books" / f.name).write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    src = LIVE / "facts" / day
    shutil.copytree(src, sb / "facts" / day)
    log(here, f"prep {day}: 账本 {len(list((sb / 'books').glob('*.json')))} 本进沙盒; facts 时段 {sorted(p.name for p in (sb / 'facts' / day).iterdir())}"
              + (f"; ⚠ 复现失败未处理: {bad}" if bad else ""))
    return not bad


def schedule(day):
    """各链当日排程时段: 读 sys_job(启用中的 paperChainHandler), param=skill:slot(土豆 skill=buchitudou0, 桃哥无前缀)"""
    sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
    import manual_backfill as mb   # noqa: PLC0415
    cur = mb.db().cursor()
    cur.execute("select job_handler_param from sys_job where job_handler_name='paperChainHandler' and status=0 and is_deleted=0")
    sch = {}
    for (p,) in cur.fetchall():
        sk, slot = (p.split(":") if ":" in p else ("taoge", p))
        if slot.isdigit() and slot not in ("07",):
            sch.setdefault(slot, []).append(sk)
    return dict(sorted(sch.items()))


def spent(here):
    tot = 0.0
    for f in (here / "tok").glob("*.csv"):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            try:
                tot += float(r.get("cost_usd") or 0)
            except ValueError:
                pass
    return tot


def matcher(here, day, *args):
    e = dict(os.environ, PAPER_ROOT=str(here / "sb"), PAPER_ASOF=day, KLINE_OFFLINE="1")
    r = subprocess.run(["node", "scripts/dfcf/paper/matcher.mjs", *args], cwd=ROOT, env=e, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=NOWIN)
    tail = [l for l in (r.stdout or "").splitlines() if l.strip()][-1:]
    log(here, f"matcher {' '.join(args)} rc={r.returncode}: {' '.join(tail)}" + (f" ERR {r.stderr[-200:]}" if r.returncode else ""))


def mix(here, day, *args):
    """10/16 混合账本(可选, run --mix 才调): mix_plans.py 走沙盒(PAPER_ROOT); 任何失败只记日志, 不影响主流程"""
    try:
        sb = here / "sb"
        if not (sb / "mix_state.json").exists() and (LIVE / "mix_state.json").exists():
            shutil.copy2(LIVE / "mix_state.json", sb / "mix_state.json")   # 带上实盘 Hedge 学习状态(只用 <day 的记录)
        e = dict(os.environ, PAPER_ROOT=str(sb), PAPER_ASOF=day, KLINE_OFFLINE="1")
        r = subprocess.run([PY, "-X", "utf8", "scripts/dfcf/paper/mix_plans.py", "--date", day, *args], cwd=ROOT, env=e, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", creationflags=NOWIN, timeout=600)
        tail = [l for l in (r.stdout or "").splitlines() if l.startswith("[A-mix")]
        log(here, f"mix {' '.join(args)} rc={r.returncode}: {' | '.join(tail)}" + (f" ERR {(r.stderr or '')[-200:]}" if r.returncode else ""))
    except Exception as ex:   # noqa: BLE001
        log(here, f"mix {' '.join(args)} 失败(不影响主流程): {ex}")


def run(day, here, budget, dry, with_mix=False):
    sch = schedule(day)
    slots = list(sch)
    log(here, f"run {day}: 时段 {slots}; 预算 ${budget}")
    (here / "tok").mkdir(exist_ok=True); (here / "logs").mkdir(exist_ok=True)
    d8 = day.replace("-", "")
    for i, slot in enumerate(slots):
        if spent(here) > budget:
            log(here, f"STOP: 已花 ${spent(here):.2f} > ${budget}, 不开 {slot}"); break
        if not (here / "sb" / "facts" / day / slot).exists():
            log(here, f"{slot}: 沙盒无该时段 facts(实盘当天没建), 跳过"); continue
        procs = []
        for sk in sch[slot]:
            e = dict(os.environ, PAPER_ROOT=str(here / "sb"), PAPER_ASOF=day, KLINE_OFFLINE="1", PAPER_TOKEN_LOG=str(here / "tok" / f"{sk}_{slot}.csv"))
            if TAG:
                e["CHAIN_RUN_TAG"] = TAG   # 10/17: A/B 臂产物分目录 asof-<日>-<tag>
            cmd = [PY, "-X", "utf8", "scripts/taoge-chain/run_taoge_chain.py", "--skill", sk, "--slot", slot, "--date", d8, "--asof", str(here / "sb")] + (["--dry"] if dry else [])
            lf = open(here / "logs" / f"{sk}_{slot}.log", "w", encoding="utf-8")
            procs.append((sk, subprocess.Popen(cmd, cwd=ROOT, env=e, stdout=lf, stderr=subprocess.STDOUT, creationflags=NOWIN), lf))
            time.sleep(3)
        for sk, p, lf in procs:
            rc = p.wait(); lf.close()
            log(here, f"{slot} {sk}: rc={rc}")
        if with_mix and not dry:
            mix(here, day, "--slot", slot)
        nxt = slots[i + 1] if i + 1 < len(slots) else "1500"
        matcher(here, day, "--replay-min", "--date", day, "--until", nxt)
        log(here, f"{slot} 完成, 累计 ${spent(here):.2f}")
    matcher(here, day, "--replay", "--date", day)    # 无分钟线的票日线兜底
    matcher(here, day, "--eod", "--date", day)
    if with_mix and not dry:
        mix(here, day, "--learn")
    log(here, "RERUN_DONE")


def merge(day, here):
    bak = LIVE / f"books.bak-rerun{day.replace('-', '')}-{datetime.now():%H%M}"
    shutil.copytree(LIVE / "books", bak)
    n = 0
    for f in (here / "sb" / "books").glob("A-*.json"):
        shutil.copy2(f, LIVE / "books" / f.name); n += 1
    log(here, f"merge: {n} 本沙盒账本替换实盘(实盘原账备份 {bak.name}); 接着重算 nav csv / 报告")
    for args in (["--eod", "--date", day],):
        r = subprocess.run(["node", "scripts/dfcf/paper/matcher.mjs", *args, "--restate"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
        log(here, f"live matcher {' '.join(args)} --restate rc={r.returncode}: {(r.stdout or '').strip()[-200:]}")
    subprocess.run(["node", "scripts/dfcf/paper/report.mjs"], cwd=ROOT, capture_output=True, creationflags=NOWIN)
    (here / "MERGED").write_text(datetime.now().isoformat(), encoding="utf-8")   # check md 的 07 复盘见此标记才复盘重跑结果(asof 目录)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("action", choices=["prep", "run", "merge"])
    ap.add_argument("--budget", type=float, default=350.0)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--mix", action="store_true", help="run 时每个 slot 撮合前调 mix_plans.py 出混合账本单, EOD 后 --learn(默认关)")
    ap.add_argument("--tag", help="A/B 沙盒臂名(只评估不合入)")
    a = ap.parse_args()
    global TAG
    TAG = a.tag
    if TAG and a.action == "merge":
        raise SystemExit("带 --tag 的 A/B 沙盒禁止 merge")
    here = ROOT / "scripts" / "temp" / (f"rerun_{a.date.replace('-', '')}" + (f"-{TAG}" if TAG else ""))
    here.mkdir(parents=True, exist_ok=True)
    {"prep": lambda: prep(a.date, here), "run": lambda: run(a.date, here, a.budget, a.dry, a.mix), "merge": lambda: merge(a.date, here)}[a.action]()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
