# -*- coding: utf-8 -*-
"""se_dayreplay.py — 策略执行器全天离线回放引擎(09:15 → 15:00), se_dayinject.py 跑注入演示, se_dayview.py 画 HTML
(10/21 晚用户令: "把从 0915→15:00 收盘的所有内容通过 html 展现…让我看到数据来源、中间过程、从触发开始到结束的时长"; 用 10/21 的数据, 极端情况全覆盖)

做什么: 用某交易日真实 3 秒盘口(book_snap.jsonl) + 开盘实况(open_live.json) + 指数面板(panel_minute.jsonl) + 全市场 1 分钟线(kline_minute.jsonl),
对一个导师从 10 万现金空仓起步, 按盘口快照时间推进模拟时钟, 机械执行 + 事件触发 + 调 scripts/chain/se_chain.run 重定策略。
口径(逐条对照 se_exec.py 现行逻辑, 偏离处在页面"口径说明"里写明):
  - 触发 → 00 事实包准备(se_facts.refresh: 最新一份不满 30 分钟复用; 否则现做, 60 秒内没做完就用旧的) → se_chain.run(01→06) → 校验(se_exec.SE.check, 真代码) → 生效
    生效时刻 = 触发时刻 + 事实包等待 + 链实际耗时; 链的输入(账户 / 盘口 / 开盘实况)取"链开跑那一刻"(= 触发 + 事实包等待)
  - 链在跑期间按旧策略继续机械成交; 期间来的事件排队合并, 链结束立即补跑(se_exec.restrategize 的 queued)
  - 判定同 se_exec.need_re: 成交 / 失败重试 / 手动 必判不占上限; 出区间 / 翻转 / 指数事件(新, scripts/market/index_event.py) 占上限; 纯心跳不占;
    冷却 10:30 前 3 分钟 / 之后 5 分钟(必判不受冷却); 冷却中来的翻转保留到冷却结束再触发; 心跳 SX.heartbeat_min, 从上次触发时刻(秒)重新计, 链在跑不判
  - 竞价: 09:15 首版; 09:15~09:25 只读; 09:25:00 带 auction 的规则按撮合价一次成交; 09:25~09:30 不成交不判; 没成交的竞价单 09:30 起当普通限价单
  - 连续竞价撮合 / 费用 / T+1 同 se_exec.tick; 回放另加真实约束: 涨停封板(卖一 = 0)买不进、跌停封板(买一 = 0)卖不出(se_exec 现行没有这条, 见报告)
  - 午休 11:31~12:59 不成交不判(同 se_exec 的 "11:30" < hm < "13:00"); 14:57:00 停(se_exec 现行跑到 14:57:59, 见报告), 未触发规则作废
  - 链调用: 真模型(--mode real)最多 --max-calls 次, 到了之后"本该触发"照记事件不调链; --mode stub = 桩模型(零花费, 虚拟时钟给每步耗时)
产物: <out>/events.jsonl actions.jsonl curve.csv summary.json state_close.json snapshots.jsonl + 每次链 NN_HHMMSS/(se_chain 写 01~06 + timing.json; 本脚本加 calls.json / sources.json / strategy_checked.json / facts_used.txt)
用法: python se_dayreplay.py --skill meiyuelu --date 2026-10-21 [--mode real|stub] [--max-calls 14]
"""
import argparse
import bisect
import copy
import datetime as dt
import json
import re
import statistics as st
import sys
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "market"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts" / "chain"))   # 10/21 晚: se_chain 挪到 scripts/chain/, 必须排在 scripts/dfcf/paper(兼容垫片)前面
import a_rules as AR   # noqa: E402
import claude_api as API   # noqa: E402
import se_chain as SC   # noqa: E402
import se_exec as E   # noqa: E402
import shadow_exec as SX   # noqa: E402
import index_event as IE   # noqa: E402

assert Path(SC.__file__).resolve().parent.name == "chain", f"se_chain 应来自 scripts/chain, 实际 {SC.__file__}"
MKT = ROOT / "downloads" / "market"
INIT_CASH = 100000.0
LIMIT_S = 180   # 用户要求每次 触发 → 生效 < 3 分钟
FACTS_DIR = ROOT / "scripts" / "dfcf" / "paper" / "facts"
FACTS_MIN_AGE = 1800   # se_facts.MIN_AGE
FACTS_WAIT = 60        # se_exec.refresh_facts → se_facts.refresh(wait=60)
FACTS_BUILD = 75       # 10/21 实测现做一份 > 60 秒(13:39 / 14:39 两次都 60 秒没做完)
STEP_ORDER = ["02_market", "03_bull", "03_bear", "04_pick", "05_risk", "06_final"]
_REAL_TIME = SC.time


def hs(t):
    t = str(t)
    if len(t) == 5:
        t += ":00"
    h, m, s = (int(x) for x in t[:8].split(":"))
    return h * 3600 + m * 60 + s


def sh(x):
    x = int(round(x))
    return f"{x // 3600:02d}:{x % 3600 // 60:02d}:{x % 60:02d}"


def tgap(a, t):
    """a → t 之间的交易秒数(09:25~09:30 不算、午休 11:30~13:00 不算): 盘口"多久没更新"按交易时间量"""
    a = max(a, 9 * 3600 + 30 * 60)
    if 11 * 3600 + 30 * 60 < a < 13 * 3600:
        a = 13 * 3600
    g = t - a
    if a <= 11 * 3600 + 30 * 60 and t >= 13 * 3600:
        g -= 5400
    return g


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def rd(p):
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def rel(p):
    try:
        return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


# ---------------- se_chain 的回放侧补丁(只在本进程, 不改源文件) ----------------
def index_block_fixed(D, until):
    """se_chain.index_block 的修正版: 跳过 p 为 null 的面板行(10/21 中证2000 07:31~09:41 东财空报文 → 原版 None / float 抛 TypeError, 09:10~09:25 任何触发都会让整条链异常)"""
    last, ago = {}, {}
    hm = until[:5]
    t30 = (dt.datetime.strptime(hm, "%H:%M") - dt.timedelta(minutes=30)).strftime("%H:%M")
    for l in rd(MKT / D / "panel_minute.jsonl").splitlines():
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if not str(r.get("ts", "")).startswith(D) or r.get("t", "")[:5] > hm or r.get("p") is None:
            continue
        last[r["k"]] = r
        if r.get("t", "")[:5] <= t30:
            ago[r["k"]] = r
    L = []
    for k, r in last.items():
        a = ago.get(k)
        d30 = f", 近 30 分钟 {(r['p'] / a['p'] - 1) * 100:+.2f}%" if a and a.get("p") else ""
        L.append(f"- {r.get('n') or k} {r['t'][:5]} {(r.get('pct') or 0):+.2f}%{d30}")
    return "\n".join(L) or "(指数面板暂无)"


_ORIG_INDEX_BLOCK = SC.index_block
PATCH = {"index_block": False}


def apply_index_patch():
    SC.index_block = index_block_fixed
    PATCH["index_block"] = True


# ---------------- 虚拟时钟(桩模式: 每步耗时由注入方案给定, 不真等) ----------------
class VClock:
    def __init__(self):
        self.now, self.seq, self.base = 1e9, 1e9, 1e9
        self.lock = threading.Lock()

    def time(self):
        return self.now

    def reset(self):
        self.now = self.seq = self.base = 1e9


V = VClock()
_ORIG_BUILD01 = SC.build_01


def build01_hook(*a, **k):
    r = _ORIG_BUILD01(*a, **k)
    if Hook.mode != "real":
        V.now += 0.8   # 01 脚本段按实测约 0.8 秒计
        V.seq = V.now
    return r


SC.build_01 = build01_hook


# ---------------- API 包装: 记每步起止 + 桩 / 注入 ----------------
STUB_SECS = {"02_market": 21.0, "03_bull": 20.0, "03_bear": 18.0, "04_pick": 23.0, "05_risk": 14.0, "06_final": 20.0}


class Hook:
    lock = threading.Lock()
    mode = "real"        # real | stub
    plan = {}            # 桩: 步骤 → {"secs", "fail"(错误文字), "stall"(不受 deadline 约束的卡死), "json"}
    calls, t0 = [], 0.0


_ORIG_STREAM = API.stream


def _stub_json(step):
    return {"02_market": {"state": "桩", "attitude": "中性", "directions": [], "changed": "桩(未真调模型)", "horizon_days": 2, "mismatch": "无"},
            "03_bull": {"score": 50, "args": [], "key_risk": "桩"}, "03_bear": {"score": 50, "args": [], "key_risk": "桩"},
            "04_pick": {"picks": [], "cash_pct": 100}, "05_risk": {"checks": [], "adjust": []}}.get(step, {})


def stream_hook(**kw):
    step = re.sub(r"^se-chain-[^-]+-", "", kw.get("tag", ""))
    if Hook.mode == "real":
        a = time.time() - Hook.t0
        r = _ORIG_STREAM(**kw)
        b = time.time() - Hook.t0
    else:
        spec = dict(Hook.plan.get(step) or {})
        par = step.startswith("03")
        start = V.seq if par else V.now
        if par:
            time.sleep(0.15)   # 让 03 多 / 空两个线程都先算完各自 deadline 再推进虚拟时钟
        dl = kw.get("deadline_s") or 999
        secs = float(spec.get("secs", STUB_SECS.get(step, 20.0)))
        r = API.R()
        if spec.get("fail"):
            r.error = spec["fail"]
        elif spec.get("stall"):
            r.error = spec.get("stall_err") or "APITimeoutError: Request timed out.(首字节前卡死, deadline 只在收到流事件时才检查, 管不住)"
        elif secs > dl:
            secs = float(dl) + 0.3
            r.error = f"超时 {dl}s 中断"
        else:
            js = spec.get("json", _stub_json(step))
            r.text = f"(桩 {step}: 未真调模型, 本段文字为占位)\n```json\n{json.dumps(js, ensure_ascii=False, indent=1)}\n```"
            r.json, r.ok, r.ttft = js, True, round(min(secs, 3.0), 1)
            r.usage = {}
        r.secs = round(secs, 1)
        with V.lock:
            V.now = max(V.now, start + secs)
            if not par:
                V.seq = V.now
        a, b = start - V.base, start + secs - V.base
    with Hook.lock:
        Hook.calls.append({"step": step, "t0": round(a, 1), "t1": round(b, 1), "ok": r.ok, "secs": r.secs, "ttft": r.ttft, "err": (r.error or "")[:200],
                           "usd": r.cost_usd, "deadline": kw.get("deadline_s"), "stub": Hook.mode != "real"})
    return r


API.stream = stream_hook


# ---------------- 行情 ----------------
POOL_PAT = r"(?<!\d)([036]\d{5}|11\d{4}|12\d{4}|15\d{4}|5[16]\d{4})(?!\d)"


class Market:
    def __init__(self, D, extra_codes=()):
        self.D = D
        d = MKT / D
        f = d / "book_snap.jsonl"
        rows = []
        if f.exists():
            for l in f.open(encoding="utf-8"):
                try:
                    rows.append(json.loads(l))
                except ValueError:
                    pass
        else:
            import gzip
            with gzip.open(d / "book_snap.jsonl.gz", "rt", encoding="utf-8") as fh:
                for l in fh:
                    try:
                        rows.append(json.loads(l))
                    except ValueError:
                        pass
        rows.sort(key=lambda r: r.get("t", ""))   # 多进程写入, 行序有乱
        self.ticks = {}
        for r in rows:
            self.ticks.setdefault(hs(r["t"]), []).append(r)
        self.times = sorted(self.ticks)
        self.book_codes = sorted({str(r["s"])[2:] for r in rows})
        self.aucpx = {}
        for r in rows:   # 09:25 撮合价 = 09:25:00 之后该票第一条 p>0(竞价段 p=0)
            c = str(r["s"])[2:]
            if "09:25:00" <= r["t"] < "09:30:00" and r.get("p") and c not in self.aucpx:
                self.aucpx[c] = {"px": float(r["p"]), "t": r["t"], "src": "book_snap"}
        # 1 分钟线(tdx 全市场): 只载入可能用到的票(各 slot 事实包里出现的 + 盘口名单 + 上证)
        want = set(self.book_codes) | set(extra_codes)
        for fp in FACTS_DIR.glob(f"{D}/*/facts.md"):
            want |= set(re.findall(POOL_PAT, rd(fp)))
        want_sym = {AR.symbol(c) for c in want if re.fullmatch(r"\d{6}", c)} | {"sh000001"}
        self.km = {}
        for l in (d / "kline_minute.jsonl").open(encoding="utf-8"):
            i = l.find('"symbol": "')
            sym = l[i + 11:i + 19] if i >= 0 else ""
            if sym not in want_sym:
                continue
            try:
                r = json.loads(l)
            except ValueError:
                continue
            k = "sh000001" if sym == "sh000001" else sym[2:]
            x = self.km.setdefault(k, {"t": [], "o": [], "h": [], "l": [], "c": [], "v": [], "a": []})
            x["t"].append(r["barTime"][11:19])
            for a, b in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume"), ("a", "amount")):
                x[a].append(r.get(b))
        o = jl(d / "open_live.json", {}) or {}
        self.judg = o.get("judgments") or []
        self.flips = SX.flips(D)
        self.sh_pc, self.sh_pts = None, []
        for l in (d / "panel_minute.jsonl").open(encoding="utf-8"):
            if '"k":"SH"' not in l and '"k": "SH"' not in l:
                continue
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if not str(r.get("ts", "")).startswith(D) or r.get("p") is None:
                continue
            self.sh_pc = r.get("pc") or self.sh_pc
            t = r["t"][:8]
            if "09:30:00" <= t <= "15:00:59" and not ("11:30:59" < t < "13:00:00"):
                self.sh_pts.append((t, float(r["p"])))
        self.sh_pts.sort()
        self.sh_open = (IE._daily(IE.KEYS["SH"][2]).get(D) or {}).get("o")
        self._lim = {}
        self.slots = []   # (构建时刻秒, 路径)
        for fp in sorted(FACTS_DIR.glob(f"{D}/*/facts.md")):
            m = re.search(r"构建于 (\d\d:\d\d)", rd(fp)[:400])
            if m:
                self.slots.append((hs(m.group(1)), fp))
        self.slots.sort()

    def limits(self, c):
        if c not in self._lim:
            pc = SC.prev_close(c, self.D)
            up, dn = AR.limit_prices(c, self.D, pc) if pc else (None, None)
            self._lim[c] = (pc, up, dn)
        return self._lim[c]

    def km_bar_idx(self, c, t):
        x = self.km.get(c)
        if not x:
            return None, None
        i = bisect.bisect_right(x["t"], sh(t)) - 1
        return (x, i) if i >= 0 else (x, None)

    def km_quote(self, c, t):
        """名单外票 / 盘口断流兜底: ≤ t 已收完的最后一根 1 分钟 bar 的收盘价(成交量 0 = 停牌 / 无成交, 返回 None)"""
        x, i = self.km_bar_idx(c, t)
        if i is None:
            return None
        if c != "sh000001" and not x["v"][i]:
            return None
        p = float(x["c"][i])
        return {"p": p, "b1": p, "a1": p, "t": x["t"][i], "src": "1分钟线(回放代替新浪补价)"}

    def suspended(self, c, t):
        x, i = self.km_bar_idx(c, t)
        return bool(x and i is not None and not x["v"][i] and all(not v for v in x["v"][:i + 1]))

    def sina_emul(self, codes, at):
        """se_chain.sina_snap 的回放替身: 用 tdx 1 分钟线截至 at 复原 今开 / 昨收 / 现价 / 最高 / 最低 / 均价(停牌 = 没有, 同新浪现价 0 被丢)"""
        out = {}
        nm = SC.names(self.D)
        for c in codes:
            x, i = self.km_bar_idx(c, hs(at))
            if i is None or not any(x["v"][:i + 1]):
                continue
            vs, am = sum(v or 0 for v in x["v"][:i + 1]), sum(a or 0 for a in x["a"][:i + 1])
            p = float(x["c"][i])
            vw = am / vs if vs else None
            if vw and not (0.5 < vw / p < 2):
                vw = vw / 100 if 0.5 < vw / 100 / p < 2 else None
            out[c] = {"name": nm.get(c, ""), "o": float(x["o"][0]), "pc": self.limits(c)[0] or float(x["o"][0]), "p": p,
                      "h": max(float(v) for v in x["h"][:i + 1]), "l": min(float(v) for v in x["l"][:i + 1]), "vwap": vw}
        return out

    def auction_px(self, c):
        if c in self.aucpx:
            return self.aucpx[c]
        if not hasattr(self, "_cao"):
            self._cao = {}
            f = MKT / self.D / "call_auction_open.jsonl"
            if f.exists():
                for l in f.open(encoding="utf-8"):
                    try:
                        r = json.loads(l)
                    except ValueError:
                        continue
                    if r.get("price") and str(r.get("snapTime", ""))[11:19] <= "09:25:05":
                        self._cao[r["symbol"][2:]] = {"px": float(r["price"]), "t": r["snapTime"][11:19], "src": "call_auction_open"}
        return self._cao.get(c)

    def open_text(self, t):
        """同 se_exec.open_ctx, 但只看 ≤ t 的判定 / 翻转(实盘里文件只写到当下)"""
        hm = sh(t)[:5]
        J = [j for j in self.judg if j.get("t", "") <= hm.replace(":", "")]
        if not J:
            return "(今天开盘实况还没出判定)", None
        j = J[-1]
        fl = "; ".join(f"{k} {v}" for k, v in sorted(self.flips.items()) if k <= hm) or "无"
        L = [f"最新判定 {j.get('t')}: {j.get('label')}(分 {j.get('score')})"] + [f"- {x}" for x in j.get("factors") or []] + [f"今日翻转: {fl}"]
        return "\n".join(L), j.get("t")

    def sh_bars(self, t):
        """上证当日价格点(≤ t, 精确到秒防偷看), 首点 = 日线开盘价(同 index_event.bars_today)"""
        s = sh(t)
        pts = [(x[0][:5].replace(":", ""), x[1]) for x in self.sh_pts if x[0] <= s]
        if self.sh_open and t >= hs("09:30:00"):
            pts = [("0930", float(self.sh_open))] + [x for x in pts if x[0] > "0930"]
        return pts

    def sh_px(self, t):
        s = sh(t)
        i = bisect.bisect_right(self.sh_pts, (s, 1e18)) - 1
        return self.sh_pts[i][1] if i >= 0 else None


# ---------------- 回放引擎 ----------------
class Engine:
    """cfg: out, skill, D, mode(real|stub), max_calls, t_start, t_end, init(快照 dict 或 None), label,
            plan_fn(engine, kind, why, t) → 桩方案 dict, hb_fn(hm) → 分钟, cap, idx_kw, facts_override(文字), kicks [(秒, 原因)],
            drop_ticks {code: (秒a, 秒b)}, crash (秒崩, 秒起), snap(是否写 snapshots.jsonl), close_at"""

    def __init__(self, M, cfg):
        self.M, self.cfg = M, cfg
        self.skill, self.D = cfg["skill"], cfg["D"]
        self.out = Path(cfg["out"])
        self.out.mkdir(parents=True, exist_ok=True)
        for f in ("events.jsonl", "actions.jsonl", "curve.csv", "snapshots.jsonl"):
            (self.out / f).unlink(missing_ok=True)
        ini = copy.deepcopy(cfg.get("init")) or {}
        self.state = ini.get("state") or {"cash": INIT_CASH, "positions": {}, "trades": []}
        self.start_state = copy.deepcopy(self.state)
        self.strategy, self.ver = ini.get("strategy"), ini.get("ver", 0)
        self.fired = set(ini.get("fired") or [])
        self.last_re = ini.get("last_re")
        self.n_re, self.n_all, self.fail_n = ini.get("n_re", 0), 0, ini.get("fail_n", 0)
        self.n_all_base = ini.get("n_all", 0)
        self.retry = tuple(ini["retry"]) if ini.get("retry") else None
        self.flips_seen = set(ini.get("flips_seen") or [])
        self.capped = ini.get("capped", False)
        self.idx_n = ini.get("idx_n", 0)
        self.prev02 = ini.get("prev02")
        self.q = copy.deepcopy(ini.get("q") or {})
        self.running, self.queued, self.queued_counted = None, [], True
        self.cap = cfg.get("cap") if cfg.get("cap") is not None else SX.real_cap(self.skill, self.D)[0]
        self.events, self.runs = [], []
        self.cool_seen, self.q_seen, self.blk_seen, self.stale_on = set(), set(), set(), {}
        self.closed, self.dead = False, False
        self.facts_build_t = None   # 回放里"现做"事实包的完成时刻(秒)
        self.kicks = sorted(cfg.get("kicks") or [])
        self.patched_rerun = False
        self.flags = {"first": bool(ini), "auc": bool(ini) and (ini.get("t", 0) >= hs("09:25:00")), "open": bool(ini) and ini.get("t", 0) >= hs("09:30:00"),
                      "lunch": False, "pm": bool(ini) and ini.get("t", 0) >= hs("13:00:00"), "close": False}
        self.last_kind = ini.get("last_kind")
        self.last_kinds = []

    # ----- 记录 -----
    def ev(self, t, kind, why="", **k):
        e = {"i": len(self.events) + 1, "t": sh(t), "kind": kind, "why": why, **k}
        self.events.append(e)
        with (self.out / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        if self.cfg.get("verbose", True):
            print(f"[{e['t']}] {kind} {str(why)[:110]}", flush=True)
        return e

    # ----- 行情 -----
    def quote(self, c, t):
        """se_exec.Feed: 3 秒盘口; 名单外 / 超 60 秒没更新 → 新浪补价(回放用 1 分钟线代替); 都没有 → 用旧的(se_exec 现行也是继续用旧价)"""
        q = self.q.get(c)
        if q and tgap(hs(q["t"]), t) <= 60:
            return q
        k = self.M.km_quote(c, t)
        return k or q

    def nav(self, t):
        return round(self.state["cash"] + sum(p["qty"] * ((self.quote(c, t) or {}).get("p") or p.get("cost") or 0) for c, p in self.state["positions"].items()), 2)

    # ----- 事实包(同 se_facts.refresh 的时序) -----
    def facts_prep(self, t):
        """→ (等待秒, 用哪份 slot 路径, 说明)"""
        M = self.M
        have = [(b, p) for b, p in M.slots if b <= t]
        cur = have[-1] if have else None
        cands = ([cur[0]] if cur else []) + ([self.facts_build_t] if self.facts_build_t and self.facts_build_t <= t else [])
        fresh_t = max(cands) if cands else None
        if cur and fresh_t is not None and t - fresh_t < FACTS_MIN_AGE:
            return 1.0, cur[1], f"复用最近一份(slot {cur[1].parent.name} 构建于 {sh(cur[0])[:5]}, 不满 30 分钟)"
        if self.facts_build_t and t < self.facts_build_t:
            return 1.0, cur[1] if cur else None, "他链正在构建, 用最近一份"
        self.facts_build_t = t + FACTS_BUILD
        if not cur:
            return float(FACTS_WAIT), None, f"现做 slot {sh(t)[:5].replace(':', '')}, {FACTS_WAIT}s 内没做完, 今天还没有任何一份"
        return float(FACTS_WAIT), cur[1], (f"最新一份 slot {cur[1].parent.name} 已超 30 分钟 → 现做 slot {sh(t)[:5].replace(':', '')}, {FACTS_WAIT} 秒内没做完(实测约 {FACTS_BUILD} 秒)"
                                           f" → 本次仍用 slot {cur[1].parent.name}; 新的一份在 {sh(t + FACTS_BUILD)} 做好供下次用(回放里内容仍取 ≤ 当时已存在的真实 slot)")

    # ----- 触发 -----
    def fire(self, t, kind, why, counted, inj=False, meta=None):
        meta = meta or {}
        if self.running:
            self.queued.append({"t": sh(t), "kind": kind, "why": why, "counted": counted, "inj": inj})
            self.queued_counted = self.queued_counted and counted
            key = (self.running["id"], kind)
            if key not in self.q_seen:
                self.q_seen.add(key)
                self.ev(t, "排队", why, src_kind=kind, behind=self.running["id"], inj=inj,
                        note=f"链 {self.running['id']} 还在跑(预计 {sh(self.running['end']) if self.running.get('end') else '未开跑'} 结束), 事件排队, 结束后合并补跑")
            return
        n_tot = self.n_all + 1
        n_paid = sum(1 for r in self.runs if not r.get("err"))   # 01 段就抛异常的不花钱, 不占真调预算
        if self.cfg.get("mode") == "real" and n_paid >= self.cfg.get("max_calls", 14):
            self.n_re += 1 if counted else 0
            self.last_re, self.last_kind = t, kind
            self.ev(t, kind, why, budget=True, counted=counted, inj=inj, n_re=self.n_re,
                    note=f"回放预算到(已真调 {n_paid} 次链), 本该触发重定, 未调链; 继续按 v{self.ver} 机械执行")
            return
        self.n_all = n_tot
        self.n_re += 1 if counted else 0
        prev_last = (self.last_re, self.last_kind)
        self.last_re, self.last_kind = t, kind
        self.last_kinds = list((meta or {}).get("kinds") or [])
        rid = f"{self.n_all:02d}_{sh(t).replace(':', '')}"
        wait, fpath, fnote = self.facts_prep(t)
        run = {"id": rid, "kind": kind, "why": why, "trig": sh(t), "trig_s": t, "counted": counted, "inj": inj, "n_re": self.n_re,
               "facts_wait": wait, "facts": rel(fpath) if fpath else None, "facts_note": fnote, "prev_trig": sh(prev_last[0]) if prev_last[0] is not None else None,
               "prev_kind": prev_last[1], **meta}
        self.runs.append(run)
        self.running = {"id": rid, "stage": "prep", "start_at": t + wait, "end": None, "run": run, "fpath": fpath}
        self.ev(t, kind, why, run=rid, counted=counted, inj=inj, n_re=self.n_re, note=meta.get("note", ""))

    def start_chain(self, ts):
        """事实包等完了: 以此刻的账户 / 盘口 / 开盘实况跑 se_chain.run"""
        R = self.running
        run, rdir = R["run"], self.out / R["run"]["id"]
        rdir.mkdir(parents=True, exist_ok=True)
        at = sh(ts)
        fpath = R["fpath"]
        if self.cfg.get("facts_override") is not None:
            facts = self.cfg["facts_override"]
            run["facts"], run["facts_note"] = "(注入: 事实包缺)", "注入演示: 事实包文件读不到 → se_exec._chain 传 \"(今日事实包缺)\""
        elif fpath:
            body = SC_slim(rd(fpath), self.skill)
            m = re.search(r"构建于 (\d\d:\d\d)", body[:400])
            facts = f"(本份慢层材料生成于 {m.group(1) if m else '?'}:00, 不是此刻; 价格 / 持仓以上面快层为准)\n" + body
        else:
            facts = "(今日事实包缺)"
        (rdir / "facts_used.txt").write_text(facts, encoding="utf-8")
        otext, ot = self.M.open_text(ts)
        st_copy = copy.deepcopy(self.state)
        quotes = {c: dict(q) for c, q in self.q.items()}
        for c in list(st_copy["positions"]) + [x["code"] for x in (self.strategy or {}).get("codes") or []]:
            qq = self.quote(c, ts)
            if qq:
                quotes[c] = dict(qq)
        prev02 = self.prev02
        plan = None
        if self.cfg.get("mode") != "real":
            plan = self.cfg["plan_fn"](self, run["kind"], run["why"], ts) if self.cfg.get("plan_fn") else default_plan(self, ts)
            Hook.plan = plan or {}
            Hook.mode = "stub"
            V.reset()
            SC.time = V
        else:
            Hook.mode = "real"
            SC.time = _REAL_TIME
        Hook.calls, Hook.t0 = [], time.time()
        SC.sina_snap = lambda codes, _at=at: self.M.sina_emul(codes, _at)
        err, tb = None, None
        w0 = time.time()
        try:
            s, cost, T = SC.run(self.skill, self.D, at, run["why"], st_copy, copy.deepcopy(self.strategy), set(self.fired), quotes, facts, otext, prev02, rdir,
                                live=True, budget=self.cfg.get("budget", SC.CHAIN_BUDGET), effort=self.cfg.get("effort", "low"))
        except Exception as e:   # noqa: BLE001  se_exec.restrategize 的 except: 记"重定异常", 不重试
            s, cost, T, err, tb = None, 0.0, {"result": f"异常 {e!r}"[:300], "steps": {}}, repr(e)[:300], traceback.format_exc()[-1500:]
        if Hook.mode == "real":
            dur = time.time() - w0
        else:
            dur = (V.now - V.base) if not err else 0.5
        SC.time = _REAL_TIME
        Hook.mode = "real"
        calls = list(Hook.calls)
        (rdir / "calls.json").write_text(json.dumps({"wall": round(time.time() - w0, 1), "dur": round(dur, 1), "stub": self.cfg.get("mode") != "real", "calls": calls,
                                                    "plan": {k: {kk: vv for kk, vv in v.items() if kk != "json"} for k, v in (plan or {}).items()}},
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
        if err and not (rdir / "timing.json").exists():
            (rdir / "timing.json").write_text(json.dumps({**T, "total": round(dur, 1), "traceback": tb}, ensure_ascii=False, indent=1), encoding="utf-8")
        self.write_sources(rdir, ts, R, ot, quotes)
        steps = T.get("steps") or {}
        run.update(start=at, start_s=ts, chain_dur=round(dur, 1), end_s=ts + dur, end=sh(ts + dur), dur=round(R["run"]["facts_wait"] + dur, 1),
                   result=T.get("result") or ("ok" if s else "失败"), usd=round(cost or 0, 4), err=err, traceback=tb, stub=self.cfg.get("mode") != "real",
                   skip05=bool((steps.get("05_risk") or {}).get("skipped")), steps={k: v for k, v in steps.items() if isinstance(v, dict)},
                   prev02_from=self.prev02_from if hasattr(self, "prev02_from") else None)
        R.update(stage="chain", end=ts + dur, strategy=s)
        print(f"    链 {run['id']}: 事实包 {run['facts_wait']:.0f}s + 链 {dur:.0f}s ${cost or 0:.2f} {run['result'][:80]}", flush=True)

    def write_sources(self, rdir, ts, R, ot, quotes):
        P = ROOT / "skills" / f"{self.skill}-skill" / "persona"
        at = sh(ts)
        f01 = rd(rdir / "01_facts.md")
        pool = re.findall(r"^\| \d+ \| (\d{6}) \| [^|]* \| ([^|]*) \|", f01, re.M)
        out_list = [c for c, _ in pool if c not in self.M.book_codes]
        snap_last = max((q["t"] for c, q in self.q.items() if any(c == x for x, _ in pool)), default=None)
        src = [
            {"块": "导师画像 / 规则索引 / 规则全文(缓存前缀)", "文件": [rel(P / "profile.md"), rel(P / "rules_index.md"),
                                                       rel(P / "rules.md") + ("(全文)" if (P / "rules.md").exists() and (P / "rules.md").stat().st_size <= SC.RULES_INLINE_MAX else "(超长只给索引)")],
             "截至": "文件当前版本(" + dt.datetime.fromtimestamp((P / "rules.md").stat().st_mtime).strftime("%m-%d %H:%M") + " 改)"},
            {"块": "00 事实包(大盘 / 外围 / 资讯 / 六榜 / 导师信号, se_facts 零 token)", "文件": [R["run"].get("facts") or "无"],
             "截至": R["run"].get("facts_note") or ""},
            {"块": "账户(影子账)", "文件": ["回放内存账本, 起点 10 万现金空仓" if not self.cfg.get("init") else "回放内存账本(注入演示从主回放快照分叉)"], "截至": at},
            {"块": "候选池现价 / 买一卖一(3 秒盘口)", "文件": [rel(MKT / self.D / "book_snap.jsonl")], "截至": f"≤ {at}(池内最新一笔 {snap_last or '-'})"},
            {"块": "候选池 1 分钟线(5分MACD / RSI / 均价 / 日内位置)", "文件": [rel(MKT / self.D / "kline_minute_live.jsonl")], "截至": f"barTime ≤ {at}(bar 按结束时刻标)"},
            {"块": "名单外票(新浪快照的回放替身)", "文件": [rel(MKT / self.D / "kline_minute.jsonl") + "(tdx 全市场 1 分钟线)"], "截至": f"≤ {at} 已收完的 bar",
             "明细": ", ".join(out_list[:30]) or "无"},
            {"块": "竞价撮合 / 未匹配量(09:31 前才有)", "文件": [rel(MKT / self.D / "book_snap.jsonl") + " 09:15~09:25 段"], "截至": min(at, "09:25:59") if at < "09:31:00" else "不用"},
            {"块": "开盘实况机械判定 + 今日翻转", "文件": [rel(MKT / self.D / "open_live.json")], "截至": f"判定 {ot or '无(09:31 才出第一条)'}"},
            {"块": "指数 / 外围面板", "文件": [rel(MKT / self.D / "panel_minute.jsonl")], "截至": f"≤ {at[:5]}" + (" (回放补丁: 跳过 p=null 行)" if PATCH["index_block"] else "")},
            {"块": "昨收 / 涨跌停 / 近 30 日振幅", "文件": ["downloads/quotes/daily/<代码>.json"], "截至": f"< {self.D}"},
            {"块": "拟人统计(05)", "文件": [f"downloads/tzzb/{self.skill}/day_positions.json"], "截至": f"< {self.D} 近 60 个记录日"},
            {"块": "多日展望天数", "文件": ["scripts/chain/horizon_days.json"], "截至": "文件当前版本"},
            {"块": "上一版 02 市况", "文件": [getattr(self, "prev02_from", None) or "无(今天第一版)"], "截至": "上一次跑出 02 的链"},
        ]
        (rdir / "sources.json").write_text(json.dumps(src, ensure_ascii=False, indent=1), encoding="utf-8")

    def land(self):
        R = self.running
        self.running = None
        te = R["end"]
        run = R["run"]
        rdir = self.out / run["id"]
        if run.get("err"):
            run["applied"] = None
            self.ev(te, "链异常", f"链 {run['id']} 抛异常 {run['err'][:160]}", run_ref=run["id"],
                    note="se_exec.restrategize 现行: 异常走 except 记\"重定异常\", 不设 90 秒重试、不计失败次数 → 这一轮就丢了")
            if "index_block" in (run.get("traceback") or "") and not PATCH["index_block"] and self.cfg.get("patch_on_crash", True):
                apply_index_patch()
                self.patched_rerun = True
                run["patched_after"] = True
        elif R.get("strategy"):
            if self.closed:
                run["applied"] = None
                self.ev(te, "收盘后落地", f"链 {run['id']} 在 14:57 之后才出结果, 不再生效", run_ref=run["id"])
            else:
                X = self.checker()
                s2, dropped = E.SE.check(X, R["strategy"])
                (rdir / "strategy_checked.json").write_text(json.dumps({"strategy": s2, "dropped": dropped, "checked_at": sh(te),
                                                                        "ok_codes": sorted(set(X.codes()) | X.facts_codes())[:400]}, ensure_ascii=False, indent=1), encoding="utf-8")
                self.ver += 1
                self.strategy, self.fired = s2, set()
                run.update(applied=sh(te), ver=self.ver, dropped=dropped)
                self.fail_n = 0
                n_rules = sum(len(x.get("rules") or []) for x in s2.get("codes") or [])
                self.ev(te, "生效", f"v{self.ver} 生效: {len(s2.get('codes') or [])} 只票 {n_rules} 条规则" + (f"; 校验剔除 {len(dropped)} 处" if dropped else ""),
                        run_ref=run["id"], ver=self.ver, dropped=dropped, inj=run.get("inj"))
        else:
            run["applied"] = None
            self.fail_n += 1
            msg = f"链 {run['id']} 失败({run['result'][:120]}), 沿用 v{self.ver}"
            if self.fail_n <= 3 and not self.closed:
                self.retry = (te + 90, run["why"])
                msg += f"; 连续失败 {self.fail_n} 次, 90 秒后({sh(te + 90)})自动重试"
                self.ev(te, "链失败", msg, run_ref=run["id"], n_fail=self.fail_n, inj=run.get("inj"))
            else:
                self.ev(te, "放弃重试" if not self.closed else "链失败", msg + (f"; 连续失败 {self.fail_n} 次 > 3, 不再重试, 等下一个事件" if not self.closed else ""),
                        run_ref=run["id"], n_fail=self.fail_n, inj=run.get("inj"))
        if run.get("err") and run.get("patched_after"):
            self.ev(te, "回放补丁", "在回放进程里把 se_chain.index_block 换成跳过 p=null 行的版本(不改源文件), 立即重跑这一轮; 实盘 se_exec 不会重跑, 要主会话修 se_chain",
                    run_ref=run["id"])
            self.fire(te, "补丁后重跑", "(回放补丁后重跑) " + run["why"], counted=False, meta={"note": "非 se_exec 行为: 回放为了让后面能继续而补跑", "patched_rerun": True})
            return
        if self.queued:
            q, self.queued = self.queued, []
            qc, self.queued_counted = self.queued_counted, True
            whys = list(dict.fromkeys(x["why"] for x in q))
            if self.closed:
                self.ev(te, "排队作废", "收盘后不再补跑: " + "; ".join(whys)[:200])
            else:
                self.fire(te, "排队补跑", "(排队补叫) " + "; ".join(whys), counted=qc, inj=any(x["inj"] for x in q),
                          meta={"src_events": [x["kind"] + " " + x["t"] for x in q]})

    def checker(self):
        """se_exec.SE.check 的 self 替身: codes() / facts_codes() 直接调 se_exec 的真方法"""
        X = type("X", (), {})()
        X.state, X.strategy, X.skill, X.D = self.state, self.strategy, self.skill, self.D
        last = next((r for r in reversed(self.runs) if (self.out / r["id"] / "facts_used.txt").exists()), None)
        fp = (self.out / last["id"] / "facts_used.txt") if last else Path("__none__")
        X.facts_file = lambda: fp
        X.codes = lambda: E.SE.codes(X)
        X.facts_codes = lambda: E.SE.facts_codes(X)
        return X

    def advance(self, t):
        """处理 ≤ t 的链开跑 / 落地(按时间先后)"""
        while self.running:
            R = self.running
            if R["stage"] == "prep":
                if R["start_at"] > t:
                    return
                self.start_chain(R["start_at"])
                continue
            if R["end"] > t:
                return
            self.land()
            if self.prev02_update():
                pass

    def prev02_update(self):
        """se_exec._chain: prev02 = versions/*/02_market.md 里最新一份(前 2500 字)"""
        for r in reversed(self.runs):
            f = self.out / r["id"] / "02_market.md"
            if f.exists() and r.get("chain_dur") is not None:
                self.prev02, self.prev02_from = rd(f)[:2500], rel(f)
                return True
        return False

    # ----- 机械执行 -----
    def fill(self, t, x, r, px, n, phase, q, notes=None):
        c = x["code"]
        pos = self.state["positions"].setdefault(c, {"qty": 0, "cost": None, "sellable": 0})
        amt = px * n
        fe = E.SE.fee(None, c, r["side"], amt)
        if r["side"] == "BUY":
            pos["cost"] = ((pos["cost"] or 0) * pos["qty"] + amt + fe) / (pos["qty"] + n)
            pos["qty"] += n
            if AR.is_t0(c, x.get("name")):
                pos["sellable"] += n
            self.state["cash"] = round(self.state["cash"] - amt - fe, 2)
        else:
            pos["qty"] -= n
            pos["sellable"] -= n
            self.state["cash"] = round(self.state["cash"] + amt - fe, 2)
            if pos["qty"] <= 0:
                self.state["positions"].pop(c)
        a = {"t": sh(t), "code": c, "name": x.get("name"), "side": r["side"], "px": round(px, 3), "qty": n, "fee": fe, "rule": f"{self.ver}:{c}:{r['id']}",
             "why": r.get("why"), "phase": phase, "ver": self.ver, "cash_after": self.state["cash"], "notes": notes or [],
             "tape": {k: q.get(k) for k in ("p", "t", "b1", "a1", "src") if q and k in q}}
        self.state["trades"].append({k: v for k, v in a.items() if k in ("t", "code", "name", "side", "px", "qty", "fee", "rule", "why")})
        with (self.out / "actions.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
        return a

    def auction(self, t):
        fills, n_rules = [], 0
        for x in (self.strategy or {}).get("codes") or []:
            for r in x.get("rules") or []:
                if not r.get("auction"):
                    continue
                n_rules += 1
                key = f"{self.ver}:{x['code']}:{r['id']}"
                if key in self.fired:
                    continue
                ap = self.M.auction_px(x["code"])
                if not ap:
                    self.ev(t, "竞价未成交", f"{key} 没有撮合价(停牌 / 无竞价成交)", rule=key)
                    continue
                m = ap["px"]
                hit = r["px"] >= m if r["side"] == "BUY" else r["px"] <= m
                if not hit:
                    self.ev(t, "竞价未成交", f"{key} {r['side']} 价{r['px']} vs 撮合价 {m}: 没够到, 09:30 起当普通限价单继续有效", rule=key)
                    continue
                pos = self.state["positions"].get(x["code"]) or {"sellable": 0}
                n = min(r["qty"], AR.round_qty(x["code"], (self.state["cash"] - 5) / m)) if r["side"] == "BUY" else min(r["qty"], pos["sellable"])
                self.fired.add(key)
                if n <= 0:
                    self.ev(t, "规则命中没钱/没可卖", key)
                    continue
                notes = [f"现金截断 {r['qty']}→{n}"] if r["side"] == "BUY" and n < r["qty"] else []
                fills.append(self.fill(t, x, r, m, n, "竞价", {"p": m, "t": ap["t"], "b1": m, "a1": m, "src": ap["src"]}, notes))
        return fills, n_rules

    def tick(self, t):
        fills = []
        for x in (self.strategy or {}).get("codes") or []:
            c = x["code"]
            q = self.quote(c, t)
            if not q or not q.get("p"):
                continue
            p = q["p"]
            pc, up, dn = self.M.limits(c)
            for r in x.get("rules") or []:
                key = f"{self.ver}:{c}:{r['id']}"
                if key in self.fired:
                    continue
                if not (p <= r["px"] if r["side"] == "BUY" else p >= r["px"]):
                    continue
                pos = self.state["positions"].get(c) or {"sellable": 0, "qty": 0}
                book = q.get("src") is None
                if r["side"] == "BUY" and book and not q.get("a1") and up and p >= up - 1e-6:
                    if ("up", key) not in self.blk_seen:
                        self.blk_seen.add(("up", key))
                        self.ev(t, "涨停买不进", f"{key} BUY 价≤{r['px']}: 现价 {p} = 涨停 {up}, 卖一为空(封板), 回放判买不进, 规则留着等开板",
                                note="se_exec.tick 现行没有这条: 会按 min(规则价, 现价) 直接成交(假成交), 见报告", rule=key)
                    continue
                if r["side"] == "SELL" and book and not q.get("b1") and dn and p <= dn + 1e-6:
                    if ("dn", key) not in self.blk_seen:
                        self.blk_seen.add(("dn", key))
                        self.ev(t, "跌停卖不出", f"{key} SELL 价≥{r['px']}: 现价 {p} = 跌停 {dn}, 买一为空(封板), 回放判卖不出, 规则留着等开板",
                                note="se_exec.tick 现行没有这条: 会按 max(规则价, 买一=0) = 规则价直接成交(假成交), 见报告", rule=key)
                    continue
                notes = []
                if r["side"] == "BUY":
                    px = min(r["px"], q.get("a1") or p) or p
                    n = min(r["qty"], AR.round_qty(c, (self.state["cash"] - 5) / px))
                    if 0 < n < r["qty"]:
                        notes.append(f"现金截断 {r['qty']}→{n}(现金 {self.state['cash']:.0f})")
                else:
                    px = max(r["px"], q.get("b1") or p)
                    n = min(r["qty"], pos["sellable"])
                    if 0 < n < r["qty"]:
                        notes.append(f"可卖截断 {r['qty']}→{n}(今天可卖 {pos['sellable']})")
                self.fired.add(key)
                if n <= 0:
                    if r["side"] == "SELL" and pos.get("qty", 0) > 0:
                        self.ev(t, "T+1卖不了", f"{key} SELL 命中(现价 {p}), 持有 {pos['qty']} 股但今天可卖 0(当日买入 T+1), 规则作废一次", rule=key)
                    else:
                        self.ev(t, "规则命中没钱/没可卖", f"{key} 现价 {p}" + (f"(现金 {self.state['cash']:.0f})" if r["side"] == "BUY" else "(无持仓)"), rule=key)
                    continue
                a = self.fill(t, x, r, px, n, "连续", q, notes)
                fills.append(a)
                for nt in notes:
                    self.ev(t, "现金截断" if nt.startswith("现金") else "可卖截断", f"{key}: {nt}", rule=key)
        return fills

    def watch_feed(self, t):
        """盘口断流 / 停牌: 当前策略里的票超 60 秒没有新盘口(名单内)或 1 分钟线成交量 0"""
        for x in (self.strategy or {}).get("codes") or []:
            c = x["code"]
            q0 = self.q.get(c)
            susp = self.M.suspended(c, t) and not (q0 and tgap(hs(q0["t"]), t) <= 60)
            q = self.q.get(c)
            stale = c in self.M.book_codes and (not q or tgap(hs(q["t"]), t) > 60)
            k = "停牌" if susp else ("盘口断流" if stale else None)
            if k and self.stale_on.get(c) != k:
                self.stale_on[c] = k
                kq = self.M.km_quote(c, t)
                if k == "停牌":
                    self.ev(t, "停牌", f"{c} 1 分钟线成交量 0 / 盘口现价 0(停牌中), 规则不撮合; 出区间不判(没有现价)", code=c)
                else:
                    self.ev(t, "盘口断流", f"{c} 3 秒盘口 {'从没出现' if not q else '最后一笔 ' + q['t']}, 已超 60 秒没更新 → 新浪补价(回放用 1 分钟线 {kq['t'] + ' 收 ' + str(kq['p']) if kq else '也没有'})",
                            code=c, note="se_exec.Feed: 超 60 秒算陈旧, 每 10 秒向新浪补一次; 补不到就继续用旧价撮合(无陈旧保护)")
            elif not k and c in self.stale_on:
                was = self.stale_on.pop(c)
                self.ev(t, "恢复", f"{c} {was}结束, 盘口恢复(现价 {(self.quote(c, t) or {}).get('p')})", code=c)

    def need_re(self, t, fills):
        hm = sh(t)[:5]
        why, kinds, must, inj = [], [], False, False
        if fills:
            why.append("本链成交 " + ",".join(f"{f['side']}{f['code']} {f['qty']}@{f['px']}" for f in fills))
            kinds.append("成交")
            must = True
        if self.retry and t >= self.retry[0] and not self.running:
            why.append("(失败重试) " + str(self.retry[1])[:120])
            kinds.append("失败重试")
            self.retry = None
            must = True
        while self.kicks and self.kicks[0][0] <= t:
            kt, kw = self.kicks.pop(0)
            why.append("手动: " + kw)
            kinds.append("手动")
            must, inj = True, True
        for x in (self.strategy or {}).get("codes") or []:
            q = self.quote(x["code"], t)
            if q and q.get("p") and not (x["band"][0] <= q["p"] <= x["band"][1]):
                why.append(f"{x['code']} {q['p']} 出区间 {x['band'][0]}~{x['band'][1]}")
                kinds.append("出区间")
        new_flips = []
        lr_hm = sh(self.last_re)[:5] if self.last_re is not None else "00:00"
        for k, v in sorted(self.M.flips.items()):
            if k <= hm and k not in self.flips_seen:
                if k >= lr_hm:
                    why.append(v)
                    kinds.append("翻转")
                    new_flips.append(k)
                else:
                    self.flips_seen.add(k)
        idx_note = None
        if self.cfg.get("index_event", True) and self.last_re is not None:
            hit, mv, th, note = IE.check(self.D, sh(self.last_re)[:5].replace(":", ""), hm.replace(":", ""), self.M.sh_bars(t), "SH",
                                         n_today=self.idx_n, **(self.cfg.get("idx_kw") or {}))
            if hit:
                why.append(f"指数事件: 上证从检查点 {sh(self.last_re)[:5]} 走 {mv:+.2f}%(θ {th:.2f}%)")
                kinds.append("指数事件")
                idx_note = note
        hb_hit, hb = False, None
        if self.last_re is not None and not self.running:
            gap = (t - self.last_re) / 60 - (90 if sh(self.last_re)[:5] <= "11:30" < hm else 0)
            hb = self.cfg["hb_fn"](hm) if self.cfg.get("hb_fn") else SX.heartbeat_min(self.skill, self.D, hm)
            if gap >= hb:
                why.append(f"心跳 {hb} 分钟")
                kinds.append("心跳")
                hb_hit = True
        if not why:
            return
        cool = 3 if hm <= "10:30" else 5
        kind = next((k for k in ("成交", "失败重试", "手动", "翻转", "指数事件", "出区间", "心跳") if k in kinds), kinds[0])
        kind = "成交后必跑" if kind == "成交" else kind
        if not must and self.last_re is not None and t - self.last_re < cool * 60:
            key = (self.last_re, tuple(sorted(set(kinds))))
            if key not in self.cool_seen and not set(kinds) <= set(self.last_kinds):   # 刚触发过的同类条件还在(如出区间未回) = 预期内, 不刷屏
                self.cool_seen.add(key)
                kept = [w for w, k in zip(why, kinds) if k == "翻转"]
                self.ev(t, "冷却挡掉", "; ".join(why), src_kind=kind, kinds=sorted(set(kinds)),
                        note=f"距上次触发 {sh(self.last_re)} 不到 {cool} 分钟(冷却到 {sh(self.last_re + cool * 60)})" +
                             (f"; 翻转保留, 冷却结束后再触发: {kept}" if kept else "; 冷却后若仍满足会再判"))
            return
        self.flips_seen.update(new_flips)
        meta = {"note": "", "kinds": sorted(set(kinds))}
        if hb_hit:
            meta["note"] = f"心跳 = 上次触发 {sh(self.last_re)}({self.last_kind}) + {hb} 分钟" + ("(午休 90 分钟不计)" if sh(self.last_re)[:5] <= "11:30" < hm else "")
        if idx_note:
            meta["idx_note"] = idx_note
        if new_flips:
            meta["flips"] = new_flips
        if must or (hb_hit and len(why) == 1):
            self.fire(t, kind, "; ".join(why), counted=False, inj=inj, meta=meta)
            return
        if self.n_re >= self.cap:
            if not self.capped:
                self.capped = True
                self.ev(t, "到上限", "; ".join(why), note=f"自由触发已 {self.n_re}/{self.cap}, 之后只按最后一版机械执行; 仍认 成交 / 心跳 / 失败重试 / 手动")
            return
        if "指数事件" in kinds:
            self.idx_n += 1
        self.fire(t, kind, "; ".join(why), counted=True, inj=inj, meta=meta)

    def curve_row(self, t, label=None):
        shp = self.M.sh_px(t)
        nv = self.nav(t)
        shpct = f"{(shp / self.M.sh_pc - 1) * 100:.3f}" if shp and self.M.sh_pc else ""
        pos = "|".join(f"{c}:{p['qty']}" for c, p in self.state["positions"].items())
        return f"{label or sh(t)},{nv},{(nv / INIT_CASH - 1) * 100:.3f},{shp or ''},{shpct},{self.state['cash']},{pos}\n"

    def snapshot(self, t):
        return {"t": t, "state": self.state, "strategy": self.strategy, "ver": self.ver, "fired": sorted(self.fired), "last_re": self.last_re,
                "last_kind": self.last_kind, "n_re": self.n_re, "n_all": self.n_all, "fail_n": self.fail_n, "retry": self.retry, "flips_seen": sorted(self.flips_seen),
                "capped": self.capped, "idx_n": self.idx_n, "prev02": self.prev02, "q": self.q, "running": bool(self.running)}

    # ----- 主循环 -----
    def run(self):
        M, cfg = self.M, self.cfg
        t_start, t_end = hs(cfg.get("t_start", "09:15:00")), hs(cfg.get("t_end", "15:00:00"))
        close_at = hs(cfg.get("close_at", "14:57:00"))
        cur = (self.out / "curve.csv").open("w", encoding="utf-8")
        cur.write("t,nav,ret_pct,sh,sh_pct,cash,pos\n")
        snap_f = (self.out / "snapshots.jsonl").open("w", encoding="utf-8") if cfg.get("snap") else None
        last_min = None
        crash = cfg.get("crash")
        for t in M.times:
            if t > t_end:
                break
            self.advance(t)
            for r in M.ticks[t]:   # 更新盘口(只认 p>0, 同 se_exec.Feed)
                c = str(r["s"])[2:]
                dropw = (cfg.get("drop_ticks") or {}).get(c)
                if dropw and dropw[0] <= t <= dropw[1]:
                    continue
                if r.get("p"):
                    self.q[c] = {"p": float(r["p"]), "t": r["t"], "b1": (r.get("b") or [[0]])[0][0], "a1": (r.get("k") or [[0]])[0][0]}
            if t < t_start:
                continue
            if crash and crash[0] <= t < crash[1]:
                if not self.dead:
                    self.dead = True
                    cfg["on_crash"](self, crash[0])
                continue
            if crash and self.dead and t >= crash[1]:
                self.dead = False
                cfg["on_restart"](self, crash[1])
            if not self.flags["first"]:
                self.flags["first"] = True
                t0 = max(t_start, hs("09:15:00"))
                self.ev(t0, "阶段", "集合竞价开始(09:15~09:25 只读不成交)")
                self.fire(t0, "首版", "开盘前首版策略", counted=False)
                self.advance(t)
                continue
            if t < hs("09:25:00"):
                continue
            if not self.flags["auc"]:
                self.flags["auc"] = True
                ta = hs("09:25:00")
                fills, n_rules = self.auction(ta)
                self.ev(ta, "竞价撮合", f"当前生效 v{self.ver}" + (f", 竞价单 {n_rules} 条, 成交 {len(fills)} 笔" if self.strategy else ", 首版还没生效, 无竞价单"),
                        auc_rules=n_rules, fills=[f["rule"] for f in fills],
                        note="" if self.strategy else ("首版链还在跑" if self.running else ""))
                for f in fills:
                    self.ev(ta, "竞价成交", f"{f['side']} {f.get('name') or ''}{f['code']} {f['qty']}@{f['px']}(撮合价)", rule=f["rule"])
                if fills:
                    self.fire(ta, "竞价成交后必跑", "竞价成交 " + ",".join(f"{f['side']}{f['code']}" for f in fills), counted=False)
            hm = sh(t)[:5]
            if hm != last_min and not ("11:31" <= hm < "13:00"):
                last_min = hm
                cur.write(self.curve_row(t))
                if snap_f and not self.running:
                    snap_f.write(json.dumps(self.snapshot(t), ensure_ascii=False) + "\n")
            if t < hs("09:30:00"):
                continue
            if not self.flags["open"]:
                self.flags["open"] = True
                self.ev(hs("09:30:00"), "阶段", "连续竞价开始, 执行器每 3 秒读盘口机械成交")
            if "11:31" <= hm < "13:00":
                if not self.flags["lunch"]:
                    self.flags["lunch"] = True
                    self.ev(hs("11:30:00"), "午休", "11:30~13:00 不成交不判(执行器 11:30:xx 这一分钟还会判一次); 心跳计时扣掉 90 分钟" +
                            (f"; 链 {self.running['id']} 还在跑, 落地照常生效" if self.running else ""))
                continue
            if t >= hs("13:00:00") and not self.flags["pm"]:
                self.flags["pm"] = True
                if not self.flags["lunch"]:   # 午休段盘口没有新行(采集器也歇), 补记一条
                    self.flags["lunch"] = True
                    self.ev(hs("11:30:00"), "午休", "11:30~13:00 不成交不判(执行器 11:30:xx 这一分钟还会判一次); 心跳计时扣掉 90 分钟")
                self.ev(hs("13:00:00"), "阶段", "午后开盘, 恢复机械执行与判定")
            if t >= close_at:
                if not self.flags["close"]:
                    self.flags["close"] = True
                    self.closed = True
                    void = [f"{x['code']} {r['side']} 价{r['op']}{r['px']} ×{r['qty']}" for x in (self.strategy or {}).get("codes") or [] for r in x.get("rules") or []
                            if f"{self.ver}:{x['code']}:{r['id']}" not in self.fired]
                    self.ev(close_at, "收盘停", f"执行器停, v{self.ver} 未触发规则 {len(void)} 条作废", void=void,
                            note=(f"链 {self.running['id']} 还在跑, 结果收盘后才落地 → 不再生效" if self.running else ""))
                continue
            fills = self.tick(t)
            for f in fills:
                self.ev(t, "成交", f"{f['side']} {f.get('name') or ''}{f['code']} {f['qty']}@{f['px']} 规则 {f['rule']}", rule=f["rule"], notes=f.get("notes"))
            self.watch_feed(t)
            self.need_re(t, fills)
        while self.running:
            R = self.running
            self.advance(R["start_at"] if R["stage"] == "prep" else R["end"])
        nv = self.nav(t_end)
        if t_end >= hs("15:00:00"):
            cur.write(self.curve_row(t_end, "15:00:00"))
            self.ev(t_end, "收盘", f"收盘价结算 nav {nv:.0f}({(nv / INIT_CASH - 1) * 100:+.2f}%), 写 summary / state_close(次日接续用)")
        cur.close()
        if snap_f:
            snap_f.close()
        return self.finish(nv, t_end)

    def finish(self, nv, t_end):
        M = self.M
        shp = M.sh_px(t_end)
        sh_ret = (shp / M.sh_pc - 1) * 100 if shp and M.sh_pc else None
        close_pos = {c: {"qty": p["qty"], "cost": round(p["cost"], 4) if p.get("cost") else None, "sellable": p["sellable"],
                         "close_px": (self.quote(c, t_end) or {}).get("p")} for c, p in self.state["positions"].items()}
        (self.out / "state_close.json").write_text(json.dumps({"date": self.D, "cash": self.state["cash"], "positions": close_pos, "nav": nv, "trades": self.state["trades"]},
                                                              ensure_ascii=False, indent=1), encoding="utf-8")
        chain = [r for r in self.runs if r.get("chain_dur") is not None and not r.get("err")]
        durs = [r["dur"] for r in chain]
        S = {"date": self.D, "skill": self.skill, "mode": self.cfg.get("mode"), "label": self.cfg.get("label"), "start_nav": INIT_CASH, "end_nav": nv,
             "ret_pct": round((nv / INIT_CASH - 1) * 100, 3), "sh_ret_pct": round(sh_ret, 3) if sh_ret is not None else None, "sh_pc": M.sh_pc,
             "calls": self.n_all, "max_calls": self.cfg.get("max_calls"), "usd": round(sum(r.get("usd") or 0 for r in self.runs), 4),
             "dur_median": round(st.median(durs), 1) if durs else None, "dur_max": max(durs) if durs else None,
             "chain_median": round(st.median([r["chain_dur"] for r in chain]), 1) if chain else None,
             "over_180": [r["id"] for r in chain if r["dur"] >= LIMIT_S], "cap_free": self.cap, "n_free": self.n_re,
             "hb_min": {hm: SX.heartbeat_min(self.skill, self.D, hm) for hm in ("09:30", "10:00", "10:30", "13:00", "14:30", "14:50")}, "hb_real": SX.real_hb(self.skill, self.D),
             "trades": self.state["trades"], "end_positions": close_pos, "cash": self.state["cash"], "runs": self.runs, "n_events": len(self.events),
             "flips": M.flips, "book_codes": M.book_codes, "patch_index_block": PATCH["index_block"], "facts_slots": [[sh(b), rel(p)] for b, p in M.slots],
             "generated": dt.datetime.now().isoformat(timespec="seconds")}
        (self.out / "summary.json").write_text(json.dumps(S, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"完成[{self.cfg.get('label') or 'main'}]: nav {nv:.0f} ({S['ret_pct']:+.2f}%), 链 {self.n_all} 次, ${S['usd']:.2f}, 事件 {len(self.events)} 条 → {self.out}", flush=True)
        return S


def SC_slim(text, skill):
    """se_facts.slim(按本链瘦身), 同 se_exec 实际读到的 facts.txt"""
    import se_facts
    return se_facts.slim(text, skill)


def default_plan(eng, ts):
    """桩模式默认: 06 = 从 01 候选池挑前两只有现价的票给一份合法策略(只验回放 / 页面逻辑)"""
    out = []
    for c in [c for c in (list(eng.state["positions"]) + eng.M.book_codes) if c not in ("159941",)][:6]:
        q = eng.quote(c, ts) or {}
        p = q.get("p") or eng.M.limits(c)[0]
        if not p or len(out) >= 2:
            continue
        held = eng.state["positions"].get(c, {}).get("sellable", 0)
        out.append({"code": c, "name": SC.names(eng.D).get(c, ""), "band": [round(p * 0.985, 2), round(p * 1.015, 2)],
                    "rules": [{"id": "b1", "side": "BUY", "op": "<=", "px": round(p * 0.997, 2), "qty": 1000, "why": "桩: 回落低吸"}]
                    + ([{"id": "s1", "side": "SELL", "op": ">=", "px": round(p * 1.006, 2), "qty": held // 100 * 100 or held, "why": "桩: 冲高卖"}] if held else [])})
    return {"06_final": {"json": {"view": "桩策略(未真调模型)", "codes": out, "next": "桩", "invalid": "桩", "mimic": "桩", "valid_until": "15:00"}}}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", default="meiyuelu")
    ap.add_argument("--date", default="2026-10-21")
    ap.add_argument("--out", default=None)
    ap.add_argument("--mode", default="real", choices=["real", "stub"])
    ap.add_argument("--max-calls", type=int, default=14)
    ap.add_argument("--effort", default="low")
    ap.add_argument("--t-end", default="15:00:00")
    a = ap.parse_args()
    out = Path(a.out) if a.out else ROOT / "results" / "inv-stock" / "paper" / "day_replay" / a.date / (a.skill + ("_stub" if a.mode == "stub" else ""))
    M = Market(a.date)
    cfg = {"out": out, "skill": a.skill, "D": a.date, "mode": a.mode, "max_calls": a.max_calls, "effort": a.effort, "snap": True, "label": "main", "t_end": a.t_end}
    Engine(M, cfg).run()


if __name__ == "__main__":
    main()
