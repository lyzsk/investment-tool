#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""settle_decisions.py — 决策延迟结算(TODO §3-A 第 6 条, 2026-10-14 建; 借 TradingAgents settlement.py)
10/21 用户批迁移: 原 15:50 定时任务(结算 + LLM 便宜反思)删除 —— 机械结算改由 07 复盘流程每轮先跑一次(check md step_review07, 幂等), 结果进 07 素材包;
  LLM 反思删除, 由 07 的 root_causes / lessons 按票挂到决策上代替(decision_memory.reflects_from_07)

结算(零 token, 机械): 对 decisions/<skill>.jsonl 里每单, T+1 / 2 / 3 / 5 / 10 交易日收盘后各结一次(10/20 前只有 T+1 / T+3):
  - 是否成交: 查账本 books/<source>.json 同日同 slot 同票同向同量同价的挂单状态(filled/void/cxl/invalid/reject/open; 找不到=unknown)
  - 入场价 = 成交价(未成交=挂单价, 当"假如成交"算), 收益 = 收盘/入场 − 1; 卖单取负号(卖后跌=对)
  - 超上证 = 方向×(个股收益 − 上证同窗收益); 上证基准 = 决策日前一交易日收盘 → T+k 收盘
  - 超对照组 = 买单收益 − 对照组账本(A-control) nav 同窗收益(卖单/对照组自己不算)
  行情只读本地: downloads/market/<日>/kline_day.jsonl(15:35 收盘采集, 不复权原始价) → 次日 preClose → downloads/quotes/daily/<code>.json(前复权缓存, 兜底)
  收盘价拿不到=留待下次(不会用盘中价); 重复跑幂等(已结的 (id, 窗口) 跳过)。
反思(10/14 起: 每次运行只开 1 个 claude -p, 所有 skill 合并, ≤40 单): 只对白名单 skill(chain_flags.txt CHAIN_REFLECTION=1 + CHAIN_REFLECTION_SKILLS)、
  等到本导师持有期窗口 T+h 结算后才反思(h = 导师真实持有交易日中位数, dm.hold_window; point-in-time: 只给 T+1..T+h 的数), 2~4 句只谈执行细节;
  谈改/否定导师规则的反思被机械护栏拦下不入库。

用法:
  python scripts/dfcf/paper/settle_decisions.py                        # 每日收盘后(建议接 15:35 行情库采集之后)
  python scripts/dfcf/paper/settle_decisions.py --date 2026-10-14 --summary <md>
  python scripts/dfcf/paper/settle_decisions.py --backfill 2026-10-08:2026-10-13 --dir scripts/temp/x   # 从 plans+06 产物补决策记录
  python scripts/dfcf/paper/settle_decisions.py --selftest
出口: 0=完成 1=有反思调用失败(结算照常落盘) 2=用法/锁
"""
import argparse, json, os, re, sys, time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import decision_memory as dm  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MARKET = ROOT / "downloads" / "market"
DAILY = ROOT / "downloads" / "quotes" / "daily"
BOOKS = HERE / "books"
PLANS = HERE / "plans"
IDX = "IDX:sh000001"
INIT_NAV = 100000.0
WINDOWS = dm.WINDOWS   # (1, 2, 3, 5, 10); 10/20 用户问"为啥 T+3 不是 T+2": 原 (1, 3) 是照搬 TradingAgents 口径, 没按导师持有期定;
#   全结(零 token), 评估 / 反思 / 回注都按各导师真实持有交易日中位数挑窗口(dm.hold_window; 用户: "这样才动态起来, 准确性才高")
hold_window = dm.hold_window


# ---------- 行情(只读本地, 零网络) ----------
def sym(code):
    c = str(code)
    if c.startswith(("92", "8", "4")):
        return "bj" + c
    if c.startswith(("6", "5", "9", "11")):
        return "sh" + c
    return "sz" + c


class Prices:
    def __init__(self, market=MARKET, daily=DAILY, now=None):
        self.market, self.daily, self.now = Path(market), Path(daily), now or datetime.now()
        self._mk, self._cache = {}, {}
        days = {p.name for p in self.market.glob("????-??-??") if (p / "kline_day.jsonl").exists()}
        for b in self._cache_bars(IDX):
            days.add(b["d"])
        self.days = sorted(d for d in days if self._cache_ok(d) or d in {p.name for p in self.market.glob("????-??-??")})

    def _cache_ok(self, d):
        today = self.now.strftime("%Y-%m-%d")
        return d < today or (d == today and self.now.strftime("%H:%M") >= "15:30")   # 缓存里的当日 bar 可能是盘中价

    def _market(self, d):
        if d not in self._mk:
            rows = {}
            f = self.market / d / "kline_day.jsonl"
            if f.exists():
                for line in f.read_text(encoding="utf-8").splitlines():
                    try:
                        r = json.loads(line)
                        rows[r["symbol"]] = r
                    except (json.JSONDecodeError, KeyError):
                        pass
            self._mk[d] = rows
        return self._mk[d]

    def _cache_bars(self, code):
        if code not in self._cache:
            f = self.daily / ("1_000001.json" if code == IDX else f"{code}.json")
            try:
                self._cache[code] = json.loads(f.read_text(encoding="utf-8")).get("klines") or []
            except (OSError, ValueError):
                self._cache[code] = []
        return self._cache[code]

    def shift(self, d, k):
        """d 之后第 k 个交易日(k<0=之前); 日历外=None"""
        if k > 0:
            after = [x for x in self.days if x > d]
            return after[k - 1] if len(after) >= k else None
        before = [x for x in self.days if x < d]
        return before[k] if len(before) >= -k else None

    def bar(self, code, d):
        """{o,h,l,c} 或 None; 先行情库快照(原始价), 再缓存(前复权)"""
        s = "sh000001" if code == IDX else sym(code)
        r = self._market(d).get(s)
        if r and r.get("close"):
            return {"o": r.get("open"), "h": r.get("high"), "l": r.get("low"), "c": r["close"], "src": "market"}
        if self._cache_ok(d):
            for b in self._cache_bars(code):
                if b.get("d") == d and b.get("c"):
                    return {"o": b.get("o"), "h": b.get("h"), "l": b.get("l"), "c": b["c"], "src": "cache"}
        return None

    def close(self, code, d):
        b = self.bar(code, d)
        if b:
            return b["c"]
        nd = self.shift(d, 1)   # 当日快照缺(如 10/08 行情库还没建)→ 次日快照的 preClose
        if nd:
            r = self._market(nd).get("sh000001" if code == IDX else sym(code))
            if r and r.get("preClose"):
                return r["preClose"]
        return None


# ---------- 账本 ----------
_BOOKS = {}


def book(books_dir, source):
    k = (str(books_dir), source)
    if k not in _BOOKS:
        try:
            _BOOKS[k] = json.loads((Path(books_dir) / f"{source}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _BOOKS[k] = None
    return _BOOKS[k]


def order_status(books_dir, d):
    """→ (status, fill_px, why); 匹配=同日+同 slot(HH:MM)+同票+同向+同量+挂价差<0.006"""
    b = book(books_dir, d["source"])
    if not b:
        return "unknown", None, "无账本"
    hm = f"{d['slot'][:2]}:{d['slot'][2:]}" if d["slot"].isdigit() else None
    cands = [o for o in b.get("orders") or [] if o.get("date") == d["date"] and str(o.get("code")) == d["code"]
             and o.get("side") == d["side"] and int(o.get("qty") or 0) == d["qty"] and abs(float(o.get("price") or 0) - d["px"]) < 0.006]
    pick = [o for o in cands if o.get("time") == hm] or cands
    if not pick:
        return "unknown", None, "账本无对应挂单(未 import/被 import 拒)"
    o = pick[-1]
    why = o.get("fillWhy") or (o.get("note", "").rsplit(" | ", 1)[-1] if " | " in o.get("note", "") else "")
    return o.get("status"), (float(o["fillPrice"]) if o.get("fillPrice") else None), why[:80]


def ctrl_ret(books_dir, d0, dk):
    b = book(books_dir, "A-control")
    if not b or not b.get("nav"):
        return None
    nav = {r["date"]: float(r["nav"]) for r in b["nav"]}
    if dk not in nav:
        return None
    before = [x for x in sorted(nav) if x < d0]
    ref = nav[before[-1]] if before else INIT_NAV   # 对照组首日之前=初始 10 万
    return nav[dk] / ref - 1


# ---------- 结算 ----------
def settle_one(d, w, px: Prices, books_dir, asof_date):
    dk = px.shift(d["date"], w)
    if not dk or dk > asof_date:
        return None
    ck = px.close(d["code"], dk)
    prev = px.shift(d["date"], -1)
    i0, ik = (px.close(IDX, prev) if prev else None), px.close(IDX, dk)
    if not ck or not i0 or not ik:
        return None
    status, fill, why = order_status(books_dir, d) if not d.get("asof") else ("unknown", None, "as-of 回放单")
    entry = fill or d["px"]
    sign = 1 if d["side"] == "BUY" else -1
    sr, ir = ck / entry - 1, ik / i0 - 1
    cr = ctrl_ret(books_dir, d["date"], dk) if d["side"] == "BUY" and d["skill"] != "control" else None
    b0 = px.bar(d["code"], d["date"]) or {}
    r4 = lambda v: None if v is None else round(v, 5)
    return {"id": d["id"], "win": w, "resolved": dk, "status": status, "fill_px": fill, "why": why, "entry": entry,
            "close": ck, "stock_ret": r4(sr), "signed_ret": r4(sign * sr), "idx_ret": r4(ir), "ex_idx": r4(sign * (sr - ir)),
            "ctrl_ret": r4(cr), "ex_ctrl": r4(sr - cr) if cr is not None else None,
            "day": {k: b0.get(k) for k in ("o", "h", "l", "c")} if b0 else None,
            "ts": datetime.now().isoformat(timespec="seconds")}


def settle_all(dir_, skills, px, books_dir, asof_date):
    done, pend = {}, 0
    for sk in skills:
        decs, sets = dm.load_decisions(dir_, sk), dm.load_settles(dir_, sk)
        new = []
        for d in sorted(decs.values(), key=lambda x: (x["date"], x["slot"])):
            for w in WINDOWS:
                if w in sets.get(d["id"], {}):
                    continue
                r = settle_one(d, w, px, books_dir, asof_date)
                if r:
                    new.append(r)
                else:
                    pend += 1
        dm.append_settles(dir_, sk, new)
        done[sk] = len(new)
    return done, pend


# ---------- 反思: 10/21 用户批迁移 —— 不再单独调 LLM 反思; 由 07 复盘的 root_causes / lessons 按票挂到决策上
#   (decision_memory.reflects_from_07, run_chain 07 通过时写), 以后 04/06 经 reflection_block 照常读 ----------
def _p(v):
    return "—" if v is None else f"{v * 100:+.2f}%"


# ---------- backfill: plans 行 + 06 产物 → 决策记录(历史/他 skill 补账用) ----------
PLAN_RE = re.compile(r"^- (\d\d):(\d\d) \| (\S+) \| (BUY|SELL) \| (\d{6}) \| ([\d.]+) \| (\d+) \| [^|]* \|(.*)$")


def _contracts_for(skill, date, slot):
    rd = ROOT / "results" / f"{skill}_chain" / f"live-{date.replace('-', '')}"
    fs = [rd / "slots" / slot / "06_verdict.md", rd / "06_verdict.md", rd / "06_verdict.prev.md"] + sorted(rd.glob("slots/*/06_verdict.md"))
    out = []
    for f in fs:
        if f.exists():
            b = re.findall(r"```contract\s*\n([\s\S]*?)```", f.read_text(encoding="utf-8"))
            try:
                out.append(json.loads(b[-1]) if b else {})
            except json.JSONDecodeError:
                pass
    return out


def backfill(dir_, d0, d1, skills=None, plans=PLANS):
    names = {}
    try:
        names = json.loads((HERE / "names.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    n = 0
    for f in sorted(Path(plans).glob("????-??-??_A-*.md")):
        date, source = f.stem.split("_", 1)
        if not (d0 <= date <= d1):
            continue
        sk = {"A-cb": "buchitudou0"}.get(source, source[2:])
        if not (ROOT / "results" / f"{sk}_chain").is_dir() or (skills and sk not in skills):
            continue
        have = dm.load_decisions(dir_, sk)
        have_slots = {(r["date"], r["slot"]) for r in have.values()}   # 驱动器已记过的 (日, slot) 整批跳过(防补账批次 ts 更晚把链原生记录遮掉)
        recs = []
        for line in f.read_text(encoding="utf-8").splitlines():
            m = PLAN_RE.match(line.strip())
            if not m:
                continue
            hh, mm, src, side, code, pxs, qty, rest = m.groups()
            slot, px, qty = hh + mm, float(pxs), int(qty)
            if (date, slot) in have_slots:
                continue
            parts = [x.strip() for x in rest.split(" | ")]
            note = parts[-1] if parts else ""
            act = None
            for c in _contracts_for(sk, date, slot):
                for a in c.get("actions") or []:
                    if str(a.get("code")) == code and (a.get("op") == "买") == (side == "BUY") and a.get("qty") == qty:
                        act = dict(a, _px=px)
                        break
                if act:
                    break
            if not act:
                anc = parts[0] if len(parts) >= 3 else None
                cond = dict(re.findall(r"(cancel_below|stop_below)=([\d.]+)", parts[1] if len(parts) >= 3 else ""))
                act = {"code": code, "op": "买" if side == "BUY" else "卖", "qty": qty, "_px": px, "anchor": anc, **cond,
                       "name": names.get(code, ""), "why": note, "rules": [{"id": x} for x in re.findall(r"[A-Z]\d+", (re.search(r"规则: ([A-Z0-9,]+)", note) or [None, ""])[1])]}
            rec = dm.records_from_contract({"actions": [act]}, skill=sk, source=src, date=date, slot=slot, sub=slot != "0915",
                                           blind_fail=("未过盲审" in note or "未过拟人审" in note), asof=False, origin="backfill", ts=f"{date}T{hh}:{mm}:00")
            recs += [r for r in rec if r["id"] not in have]
        dm.write_decisions(dir_, sk, recs)
        n += len(recs)
    return n


# ---------- 汇总 ----------
def summary(dir_, skills):
    lines = ["| skill | 日期 | slot | 方向 | 票 | 挂价×量 | 状态 | T+1 方向收益 | T+1 超上证 | T+1 超对照 | T+3 方向收益 | T+3 超上证 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    agg = []
    for sk in skills:
        decs, sets = dm.load_decisions(dir_, sk), dm.load_settles(dir_, sk)
        t1 = []
        for d in sorted(decs.values(), key=lambda x: (x["date"], x["slot"])):
            s1, s3 = sets.get(d["id"], {}).get(1) or {}, sets.get(d["id"], {}).get(3) or {}
            lines.append(f"| {sk} | {d['date'][5:]} | {d['slot']} | {'买' if d['side'] == 'BUY' else '卖'} | {d.get('name') or ''}{d['code']} | "
                         f"{d['px']:g}×{d['qty']} | {s1.get('status', '待结')} | {_p(s1.get('signed_ret'))} | {_p(s1.get('ex_idx'))} | "
                         f"{_p(s1.get('ex_ctrl'))} | {_p(s3.get('signed_ret'))} | {_p(s3.get('ex_idx'))} |")
            if s1:
                t1.append(s1)
        if decs:
            f = [s for s in t1 if s.get("status") == "filled"]
            mean = lambda xs: sum(xs) / len(xs) if xs else None
            agg.append(f"- {sk}: 决策 {len(decs)} 单, T+1 已结 {len(t1)}(成交 {len(f)}); 已成交单 T+1 方向收益均值 {_p(mean([s['signed_ret'] for s in f]))}, "
                       f"超上证均值 {_p(mean([s['ex_idx'] for s in f]))}, 胜率(超上证>0) "
                       + (f"{sum(1 for s in f if s['ex_idx'] > 0)}/{len(f)}" if f else "—")
                       + f"; 全部单(含未成交按挂价假设)T+1 超上证均值 {_p(mean([s['ex_idx'] for s in t1]))}")
            hw = hold_window(sk)
            fh = [s for d in decs.values() for s in [sets.get(d["id"], {}).get(hw) or {}] if s.get("status") == "filled"]
            agg.append(f"  - 按导师持有期(中位 → T+{hw}): 已结成交 {len(fh)} 单, 方向收益均值 {_p(mean([s['signed_ret'] for s in fh]))}, 超上证均值 {_p(mean([s['ex_idx'] for s in fh]))}, "
                       + (f"做对 {sum(1 for s in fh if s['signed_ret'] > 0)}/{len(fh)}" if fh else "做对 —"))
    return "\n".join(agg + [""] + lines)


def _skills_in(dir_):
    return sorted({p.name.split(".")[0] for p in Path(dir_).glob("*.jsonl")})


def _lock(dir_):
    Path(dir_).mkdir(parents=True, exist_ok=True)
    f = Path(dir_) / ".settle.lock"
    try:
        fd = os.open(str(f), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode()); os.close(fd)
        return f
    except FileExistsError:
        try:
            import psutil
            if not psutil.pid_exists(int(f.read_text() or 0)):
                f.unlink(missing_ok=True)
                return _lock(dir_)
        except (ValueError, OSError, ImportError):
            pass
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="结算截至日(只结 T+k ≤ 此日且已有收盘价的)")
    ap.add_argument("--dir", default=str(dm.DIR), help="决策日志目录(默认 scripts/dfcf/paper/decisions)")
    ap.add_argument("--books", default=str(BOOKS))
    ap.add_argument("--skills", help="逗号分隔; 缺省=目录里所有")
    ap.add_argument("--reflect", help="10/21 起无效(LLM 反思已删, 由 07 代替); 保留参数只为旧调用不报错")
    ap.add_argument("--backfill", metavar="D0:D1", help="先从 plans+06 产物补决策记录(只补缺的)")
    ap.add_argument("--summary", help="汇总表写到此 md")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    lk = _lock(a.dir)
    if not lk:
        print("另一个结算进程在跑, 退出")
        sys.exit(2)
    try:
        sel = set(a.skills.split(",")) if a.skills else None
        # 10/20 用户: 退出 paper 的导师(paper_excluded.json)不该再出现 —— 补记 / 结算 / 汇总 / 反思一律跳过(反思花 token, 即使白名单写 * 也不给)
        sys.path.insert(0, str(ROOT / "scripts" / "lib"))
        import mentors as MT
        ex = set(MT.excluded())
        if a.backfill:
            d0, _, d1 = a.backfill.partition(":")
            print(f"backfill {d0}~{d1 or d0}: 新增 {backfill(a.dir, d0, d1 or d0, ((sel or (set(_skills_in(a.dir)) | set(MT.active_ids()))) - ex))} 条决策记录")
        skills = [s for s in _skills_in(a.dir) if (not sel or s in sel) and s not in ex]
        px = Prices()
        done, pend = settle_all(a.dir, skills, px, a.books, a.date)
        print(f"结算(截至 {a.date}): 新结 {sum(done.values())} 个窗口 {done}; 未到期/缺收盘价 {pend} 个窗口")
        if a.summary:
            Path(a.summary).parent.mkdir(parents=True, exist_ok=True)
            Path(a.summary).write_text(f"# 决策结算汇总(截至 {a.date}, {datetime.now():%Y-%m-%d %H:%M})\n\n" + summary(a.dir, skills) + "\n", encoding="utf-8")
            print(f"汇总 → {a.summary}")
        sys.exit(0)
    finally:
        lk.unlink(missing_ok=True)


# ---------- 自测(零 token, 假行情/假账本/假 claude) ----------
def selftest():
    import tempfile, types
    fails = []
    dm.HOLD_OVERRIDE["taoge"] = 1   # 旧断言按 T+1 窗口写; 按导师持有期的新行为在下面单独测(T+2)
    tmp = Path(tempfile.mkdtemp(prefix="settle_selftest_"))
    mk, dl, bk, dd = tmp / "market", tmp / "daily", tmp / "books", tmp / "decisions"
    for p in (mk, dl, bk, dd):
        p.mkdir()
    days = ["2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13"]
    idx = {"2026-09-30": 3800, "2026-10-08": 3810, "2026-10-09": 3820, "2026-10-12": 3790, "2026-10-13": 3838}
    stk = {"2026-10-08": 10.0, "2026-10-09": 10.5, "2026-10-12": 10.2, "2026-10-13": 11.0}
    (dl / "1_000001.json").write_text(json.dumps({"klines": [{"d": d, "c": c} for d, c in idx.items()]}), encoding="utf-8")
    for d in days[1:]:   # 10/08 无行情库快照 → 走次日 preClose
        (mk / d).mkdir()
        prev = days[days.index(d) - 1]
        rows = [{"symbol": "sh000001", "close": idx[d], "preClose": idx[prev]},
                {"symbol": "sz002050", "open": stk[d], "high": stk[d] + .3, "low": stk[d] - .3, "close": stk[d], "preClose": stk[prev]}]
        (mk / d / "kline_day.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    (bk / "A-taoge.json").write_text(json.dumps({"orders": [
        {"date": "2026-10-08", "time": "09:15", "code": "002050", "side": "BUY", "qty": 100, "price": 9.9, "status": "filled", "fillPrice": 9.9, "fillWhy": "现价≤挂"},
        {"date": "2026-10-09", "time": "10:00", "code": "002050", "side": "SELL", "qty": 100, "price": 10.6, "status": "void", "note": "x | 收盘作废"}]}), encoding="utf-8")
    (bk / "A-control.json").write_text(json.dumps({"nav": [{"date": "2026-10-09", "nav": 101000}, {"date": "2026-10-13", "nav": 99000}]}), encoding="utf-8")
    c06 = {"supersedes": "首裁", "actions": [{"name": "三花", "code": "002050", "op": "买", "trigger_price": "Z*0.99", "_px": 9.9, "qty": 100,
                                              "anchor": "10", "why": "回踩", "rules": [{"id": "A4", "ctx": "x"}]}]}
    r1 = dm.records_from_contract(c06, skill="taoge", source="A-taoge", date="2026-10-08", slot="0915", sub=False, blind_fail=False, asof=False)
    r2 = dm.records_from_contract({"actions": [{"name": "三花", "code": "002050", "op": "卖", "trigger_price": "10.6", "qty": 100, "anchor": "10.5"}]},
                                  skill="taoge", source="A-taoge", date="2026-10-09", slot="1000", sub=True, blind_fail=False, asof=False)
    r3 = dm.records_from_contract({"actions": [{"name": "三花", "code": "002050", "op": "买", "trigger_price": "11", "qty": 100, "anchor": "11"}]},
                                  skill="taoge", source="A-taoge", date="2026-10-13", slot="0915", sub=False, blind_fail=False, asof=False)
    if r1[0]["px"] != 9.9 or r1[0]["rules"] != ["A4"] or r1[0]["id"] != "2026-10-08|taoge|0915|002050|BUY|9.9|100":
        fails.append(f"records_from_contract 错: {r1}")
    dm.write_decisions(dd, "taoge", r1 + r2 + r3)
    px = Prices(mk, dl, now=datetime(2026, 10, 13, 20, 0))
    if px.shift("2026-10-08", 3) != "2026-10-13" or px.shift("2026-10-08", -1) != "2026-09-30" or px.shift("2026-10-13", 1) is not None:
        fails.append(f"交易日历错: {px.days}")
    if px.close("002050", "2026-10-08") != 10.0:
        fails.append("10/08 无快照时未取次日 preClose")
    done, pend = settle_all(dd, ["taoge"], px, bk, "2026-10-13")
    st = dm.load_settles(dd, "taoge")
    a1 = st.get(r1[0]["id"], {})
    # 买 9.9 成交; T+1 10/09 收 10.5 → +6.06%; 上证 3800→3820 +0.526%; 对照组 101000/100000 −1 = +1%
    if not a1.get(1) or abs(a1[1]["signed_ret"] - (10.5 / 9.9 - 1)) > 1e-4 or abs(a1[1]["ex_idx"] - (10.5 / 9.9 - 1 - (3820 / 3800 - 1))) > 1e-4 \
            or a1[1]["status"] != "filled" or abs(a1[1]["ctrl_ret"] - 0.01) > 1e-9:
        fails.append(f"T+1 买单结算错: {a1.get(1)}")
    if not a1.get(3) or a1[3]["resolved"] != "2026-10-13" or abs(a1[3]["signed_ret"] - (11.0 / 9.9 - 1)) > 1e-4:
        fails.append(f"T+3 结算错: {a1.get(3)}")
    a2 = st.get(r2[0]["id"], {})
    # 卖 10.6 未成交(按挂价假设); T+1 10/12 收 10.2 → 价格 −3.77%, 方向收益 +3.77%; 超上证 = −(−3.77% − (3790/3810−1)), 基准起点=决策日前一交易日 10/08
    if not a2.get(1) or a2[1]["status"] != "void" or a2[1]["signed_ret"] <= 0 or a2[1]["ex_ctrl"] is not None \
            or abs(a2[1]["ex_idx"] + ((10.2 / 10.6 - 1) - (3790 / 3810 - 1))) > 1e-4:
        fails.append(f"卖单方向/未成交结算错: {a2.get(1)}")
    if 3 in a2 or st.get(r3[0]["id"]):
        fails.append("未到期窗口被提前结算")
    if pend != 10 or done["taoge"] != 5:   # 10/20 窗口 (1,2,3,5,10): a1 结 T+1/2/3, a2 结 T+1/2, r3 全未到期 → 结 5 / 待 10
        fails.append(f"结算计数错 done={done} pend={pend}")
    if settle_all(dd, ["taoge"], px, bk, "2026-10-13")[0]["taoge"] != 0:
        fails.append("重复结算不幂等")
    # 盘中(15:30 前)缓存里的当日 bar 不得当收盘用
    px_early = Prices(tmp / "nomarket", dl, now=datetime(2026, 10, 13, 10, 0))
    if px_early.close(IDX, "2026-10-13") is not None or px_early.close(IDX, "2026-10-12") != 3790:
        fails.append("盘中缓存当日 bar 闸错")
    # 10/21: 07 → 反思记忆(代替原 LLM 反思): 点名了该票的 root_causes / lessons 挂到当天决策; 谈改规则的被护栏标 blocked 不回注
    c07 = {"root_causes": [{"layer": "驱动器", "item": "002050 挂价离现价 3% 没成交", "fix": "低吸挂价贴近当日低点", "replay": "+1.2%"}],
           "lessons": [{"type": "错误归因", "text": "三花 A4 规则错了, 以后不必遵守"}, {"type": "规则草案", "text": "别的票的话, 不该挂到 002050"}]}
    n = dm.reflects_from_07(dd, "taoge", "2026-10-08", c07, {"002050": "三花"})
    rf = dm.load_reflects(dd, "taoge")
    x = rf.get(r1[0]["id"]) or {}
    if n != 1 or x.get("resolved") != "2026-10-08" or "挂价离现价" not in x.get("text", "") or x.get("guard") != "ok" or "不必遵守" in x.get("text", "") or x.get("blocked_n") != 1:
        fails.append(f"07 → 反思记忆错: n={n} {x}")
    dm.append_reflects(dd, "taoge", [{"id": r1[0]["id"], "text": "挂价贴近当日低点成交, 位置合适", "resolved": "2026-10-09", "guard": "ok"}])
    for t_, want in (("挂价离现价 3%, 下次贴近一点", True), ("按 A4 的失效条件撤单是对的", True),
                     ("规则不对, 应改", False), ("导师这条可以突破", False), ("C24 已过时", False)):
        if dm.guard_ok(t_) != want:
            fails.append(f"护栏误判: {t_}")
    # 回注 as-of: 10/09 resolved 的反思, 链日 10/09 不可见 / 10/12 可见
    t09, *_ = dm.past_context([dd], "taoge", ["002050"], "2026-10-09")
    t12, ns, nc = dm.past_context([dd], "taoge", ["002050"], "2026-10-12")
    if t09 or "贴近当日低点" not in t12 or ns != 1:
        fails.append(f"past_context as-of 过滤错: {t12!r}")
    t14, *_ = dm.past_context([dd], "taoge", ["002050"], "2026-10-14")
    if "T+3 方向收益" not in t14:
        fails.append("past_context 未带上已到期的 T+3 数字")
    dm.HOLD_OVERRIDE.clear()
    fp = tmp / "skills" / "zz-skill" / "persona"
    fp.mkdir(parents=True)
    (fp / "fingerprint.md").write_text("- 持有交易日(非日内): 4.0(P25-P75 2.0~6.0)\n", encoding="utf-8")
    root0, dm.ROOT = dm.ROOT, tmp
    if dm.hold_window("zz") != 3 or dm.hold_window("nobody") != 1:   # 4 离 3 / 5 一样近 → 取短
        fails.append(f"hold_window 错: {dm.hold_window('zz')}")
    dm.ROOT = root0
    print("汇总样例:\n" + summary(dd, ["taoge"]).splitlines()[0])
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        print("SETTLE SELFTEST FAIL:")
        for f in fails:
            print(" -", f)
        sys.exit(1)
    print("SETTLE SELFTEST PASS: 交易日历/缺快照取次日 preClose/盘中缓存闸/买卖方向收益+超上证+超对照组/未成交按挂价/未到期不结/幂等/"
          "07 → 反思记忆(按票挂接 + 护栏)/回注 as-of 过滤")


if __name__ == "__main__":
    main()
