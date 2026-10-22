# -*- coding: utf-8 -*-
"""shadow_exec.py — 全天连续模拟盘·零成本影子(10/21 凌晨用户批 TODO D1: 先拿真实触发次数; 零 token, 不下单, 不碰真实账本)

做什么: 09:25~15:00 每分钟, 对每条在跑的导师链算"如果是'模型定策略 + 机械盯盘', 此刻要不要叫模型重定策略", 只记日志不调模型。
重定策略的事件(10/21 回放 A658 10/20 定的口径; 均价线穿越 / 创新高这类日内波动写进策略由执行器处理, 不算事件):
  ① 原固定时段(sys_job 里该链的子链时刻) —— 必判
  ② 开盘实况结论翻转(open_live judgments; 全市场共享事件, 只对此刻有持仓 / 挂单 / 候选的链算)
  ③ 本链成交(账本 chain 事件"成交 ...")—— 必判
  ④ 关注票(持仓 + 未成交挂单 + 最近一次 04 候选)价格越出策略区间: 距上次重定时价格 ≥ K × 近 30 日日振幅中位(K = 1.0)
  ⑤ 关注票封板 / 炸板(现价触及 / 离开涨停价)
冷却: 09:25~10:30 3 分钟, 之后 5 分钟(必判不受冷却); 每链每天上限 = 4 + 2 × 真人近 60 个记录日日均出手次数(同日同票同向算一次), 封顶 12; 没有真人账本(UP / 对照组)= 8
每次"重定"后, 该链各关注票的基准价重置为此刻价格
数据: 3 秒盘口 book_snap(collect_book; 不在名单的票用 snapshot 缓存现价) · open_live.json · books/<账本>.json · results/<链>/live-<日>/ 的 04 产物
产物: results/_shadow/<日>/events.jsonl(每次触发: 时刻 / 链 / 原因列表 / 是否被冷却或上限拦下) + summary.md(收盘后: 每链次数 vs 原固定时段次数 + 估算花费)
用法: python shadow_exec.py --ensure | --run [--date D] | --replay --date D(用当日已落盘数据重放) | --summary --date D
启动: check md --only mix 每 5 分钟调 --ensure(交易日 09:20~15:00 没在跑就后台拉起, 无窗口, pid 锁)
"""
import argparse
import datetime as dt
import gzip
import json
import math
import os
import re
import statistics as st
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MKT = ROOT / "downloads" / "market"
OUT = ROOT / "results" / "_shadow"
LOCK = ROOT / "scripts" / "temp" / "shadow_exec.pid"
LOG = ROOT / "scripts" / "temp" / "shadow_exec.log"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts" / "market"))
sys.path.insert(0, str(ROOT / "scripts" / "tzzb"))
import mentors   # noqa: E402
sys.path.insert(0, str(HERE))
import event_chain   # noqa: E402

K_BAND = float(os.environ.get("SHADOW_K", "1.0"))   # 策略区间倍数(回放做敏感性: 0.5 ≈ 波动放大一倍)
NO_SLOTS = os.environ.get("SHADOW_NO_SLOTS", "1") == "1"   # 10/21 用户 D1①: 固定时段不再必判, 全交给事件 + 60 分钟心跳兜底(10/22 起默认; =0 回旧口径对比)
HEARTBEAT = int(os.environ.get("SHADOW_HEARTBEAT", "60"))   # 分钟; >0 = 距上次重定满 N 分钟且有关注票就判一次
COOL_OPEN, COOL, CAP_MAX, CAP_DEFAULT = 3, 5, 12, 8
LIVE_HEARTBEAT = 60   # 10/21 用户: 真跑的链(EVENT_CHAIN_SKILLS)固定时段不必判, 心跳 60 分钟兜底
HB_DYNAMIC = os.environ.get("SHADOW_HB_DYNAMIC", "1") == "1"   # 10/21 晚: 心跳按导师动态 + 时段下限(heartbeat_min); 0 = 固定 60
HB_COUNTED = os.environ.get("SHADOW_HB_COUNTED", "0") == "1"   # 10/21 晚: 纯心跳不占重定上限(同执行器 SE_HB_COUNTED)
FIRE = False   # run() 实时模式置 True: 真跑链触发时拉起 event_chain; 回放不拉
COST_LITE, COST_SUB = 0.5, 1.1   # 估算单价(美元): 精简一步重定 / 现在的子链 sub3; 精简一步的真实单价待带模型影子测


def log(*a):
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{dt.datetime.now():%m-%d %H:%M:%S}] " + " ".join(str(x) for x in a) + "\n")


def _jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def mm(t):
    return int(t[:2]) * 60 + int(t[3:5])


# ---------------- 配置: 各链子链时刻 / 上限 ----------------
def chain_slots():
    """sys_job 里 paperChainHandler 各链的时刻(只读; 结果缓存到 results/_shadow/slots.json, 取不到用缓存)"""
    cache = OUT / "slots.json"
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
        import manual_backfill as mb
        cur = mb.db().cursor()
        cur.execute("select job_handler_param from sys_job where status=0 and is_deleted=0 and job_handler_name='paperChainHandler'")
        out = {}
        for (p,) in cur.fetchall():
            m = re.fullmatch(r"(?:(\w+):)?(\d{4})", (p or "").strip())
            if m:
                out.setdefault(m.group(1) or "taoge", set()).add(m.group(2))
        out = {k: sorted(v) for k, v in out.items()}
        OUT.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        return out
    except Exception as e:   # noqa: BLE001
        log("读 sys_job 失败, 用缓存", repr(e))
        return _jl(cache, {}) or {}


CAP_K1 = float(os.environ.get("SHADOW_CAP_K1", "2"))   # 10/21 12:04 用户定: tzzb 导师(真人账本逐笔) k1 = 2
CAP_K2 = float(os.environ.get("SHADOW_CAP_K2", str(2 * CAP_K1)))   # B站 UP(抽帧核销, 不准) k2 = 2 × k1 = 4; 上限 = 全天自由触发次数(成交后 / 首版 / 固定时段必判不占)
CAP_K3 = float(os.environ.get("SHADOW_CAP_K3", str(CAP_K1)))   # 10/21 12:18 用户定: 没有真人数据的链(趋势天哥 / 对照组) 用 k3 × 全体有数据链日均的平均数; 暂定 k3 = 2(= k1, 但独立可调)
_AVG = {}


def real_cap(skill, D):
    """(全天自由触发上限, 真人日均出手) = 向上取整(k × 日均); k: tzzb 导师 / 对照组 = k1, B站 UP = k2。
    10/21 用户定: 桃哥 / 卢本圆 用抽帧核销的全期日均(up_ops_stats); 没数据的(趋势天哥 / 对照组) 用全体有数据链日均的平均数, 再乘各自的 k"""
    k = CAP_K2 if skill in mentors.ids("UP") else CAP_K1
    avg = real_avg(skill, D)
    if avg is None:   # 没数据: 不分 UP / tzzb, 一律 k3 × 全体有数据链日均的平均数(10/21 用户定暂用混合平均)
        xs = [a for a in (real_avg(s, D) for s in mentors.active_ids()) if a is not None]
        if not xs:
            return CAP_DEFAULT, None
        return max(1, math.ceil(CAP_K3 * st.mean(xs))), None
    return max(1, math.ceil(k * avg)), avg


def real_avg(skill, D):
    if (skill, D) in _AVG:
        return _AVG[(skill, D)]
    _AVG[(skill, D)] = v = _real_avg(skill, D)
    return v


def _real_avg(skill, D):
    if skill in mentors.ids("UP"):
        try:
            sys.path.insert(0, str(ROOT / "scripts" / "bilibili"))
            import up_ops_stats as U
            prev = (dt.date.fromisoformat(D) - dt.timedelta(days=1)).isoformat()
            v = U.build(days=99999, asof=prev).get(skill) or {}
            return round(v["ops"] / v["days"], 2) if v.get("days") and v.get("active_days", 0) >= 5 else None   # 天哥全期只核销出 1 天操作 = 当没数据
        except Exception:   # noqa: BLE001
            return None
    try:
        from gen_tzzb_profile import load_legs
        legs = load_legs(skill)
    except Exception:   # noqa: BLE001
        return None
    days = sorted({str(x.get("trans_date", ""))[:10] for x in legs if str(x.get("trans_date", ""))[:10] < D})
    dp = _jl(ROOT / "downloads" / "tzzb" / skill / "day_positions.json", {}) or {}
    rec = sorted(k for k in dp if k < D.replace("-", ""))[-60:]
    if not rec:
        return None
    rs = {f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in rec}
    acts = {(str(x.get("trans_date", ""))[:10], str(x.get("stock_code")), x.get("op")) for x in legs if str(x.get("trans_date", ""))[:10] in rs}
    return round(len(acts) / len(rs), 2)


# ---------------- 心跳(10/21 晚用户定: 按导师动态, 无上限, 下限按时段) ----------------
HB_FLOOR = [("09:30", 5), ("10:00", 10), ("10:30", 15), ("13:00", 30), ("14:30", 10), ("14:50", 5)]   # 用户定的分时段下限(分钟)
HB_DEFAULT, HB_MIN_N, HB_MERGE = 60, 15, 5   # 没数据 / 间隔样本 < 15 → 60; 5 分钟内的连续成交并成一次决策
_HB = {}


def real_hb(skill, D):
    """(真人日内相邻两次决策间隔 P75 分钟, 间隔样本数); 口径同 real_avg: tzzb 近 60 个记录日, 09:25~15:00 成交, 午休 90 分钟扣掉。B站 UP 没有分钟级成交 → (None, 0)"""
    if (skill, D) in _HB:
        return _HB[(skill, D)]
    p75, n = None, 0
    try:
        if skill not in mentors.ids("UP"):
            from gen_tzzb_profile import load_legs
            legs = load_legs(skill)
            dp = _jl(ROOT / "downloads" / "tzzb" / skill / "day_positions.json", {}) or {}
            rs = {f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in sorted(k for k in dp if k < D.replace("-", ""))[-60:]}
            by = {}
            for x in legs:
                t = str(x.get("trans_date", ""))
                if t[:10] in rs and len(t) >= 16 and "09:25" <= t[11:16] <= "15:00":
                    v = mm(t[11:16])
                    by.setdefault(t[:10], set()).add(v - 90 if v >= 780 else v)
            gaps = []
            for ts in by.values():
                dec = []
                for v in sorted(ts):
                    if not dec or v - dec[-1] > HB_MERGE:
                        dec.append(v)
                gaps += [b - a for a, b in zip(dec, dec[1:])]
            n = len(gaps)
            if gaps:
                p75 = sorted(gaps)[n * 3 // 4]
    except Exception:   # noqa: BLE001
        pass
    _HB[(skill, D)] = (p75, n)
    return p75, n


def heartbeat_min(skill, D, hm, dynamic=True):
    """当前时刻的心跳分钟 = max(本导师真人决策间隔 P75, 该时段下限); 样本不足用 60; dynamic=False = 旧口径固定 60"""
    if not dynamic:
        return HB_DEFAULT
    p75, n = real_hb(skill, D)
    base = p75 if p75 is not None and n >= HB_MIN_N else HB_DEFAULT
    floor = HB_FLOOR[0][1]
    for t, f in HB_FLOOR:
        if hm >= t:
            floor = f
    return max(base, floor)


# ---------------- 取数 ----------------
class Tape:
    """3 秒盘口 → {code: {HH:MM: 最后价}}; 实时模式每分钟增量读文件尾"""
    def __init__(self, D, live):
        self.D, self.live, self.px, self.pos = D, live, {}, 0
        if not live:
            for f, op in ((MKT / D / "book_snap.jsonl", open), (MKT / D / "book_snap.jsonl.gz", gzip.open)):
                if f.exists():
                    with op(f, "rt", encoding="utf-8") as fh:
                        for l in fh:
                            self._eat(l)
                    break

    def _eat(self, l):
        try:
            r = json.loads(l)
        except ValueError:
            return
        if r.get("p") and r.get("t", "") >= "09:25:00":
            self.px.setdefault(str(r["s"])[2:], {})[r["t"][:5]] = float(r["p"])

    def refresh(self):
        f = MKT / self.D / "book_snap.jsonl"
        if not f.exists():
            return
        with f.open("r", encoding="utf-8") as fh:
            fh.seek(self.pos)
            for l in fh:
                self._eat(l)
            self.pos = fh.tell()

    def at(self, c, hm):
        s = self.px.get(c)
        if not s:
            return None
        ks = [k for k in s if k <= hm]
        return s[max(ks)] if ks else None


_AMP = {}


def amp(c, D):
    if c not in _AMP:
        k = (_jl(ROOT / "downloads" / "quotes" / "daily" / f"{c}.json", {}) or {}).get("klines") or []
        k = [x for x in k if x.get("d", "") < D][-31:]
        a = [(x["h"] - x["l"]) / p["c"] for p, x in zip(k, k[1:]) if p.get("c")]
        _AMP[c] = st.median(a) if len(a) >= 5 else 0.05
    return _AMP[c]


def up_limit(c, D):
    f = MKT / D / "kline_day.jsonl"
    # 涨停价: 当日 kline_day 盘后才有; 盘中用前一日收盘 × 板限近似
    try:
        k = (_jl(ROOT / "downloads" / "quotes" / "daily" / f"{c}.json", {}) or {}).get("klines") or []
        prev = [x for x in k if x["d"] < D][-1]["c"]
        r = 0.2 if c.startswith(("30", "68")) else 0.3 if c.startswith(("8", "4", "92")) else 0.1
        return round(prev * (1 + r), 2)
    except Exception:   # noqa: BLE001
        return None


def watch_codes(skill, book, D, hm):
    """此刻关注票: 持仓 + 未成交挂单 + 本链 ≤ 此刻最近一次 04 的候选(有产物时刻的)"""
    pos = [c for c, p in (book.get("positions") or {}).items() if int(p.get("qty") or 0) > 0]
    opens = [o["code"] for o in book.get("orders") or [] if o.get("date") == D and o.get("status") == "open"]
    rd = ROOT / "results" / f"{skill}_chain" / f"live-{D.replace('-', '')}"
    cands = []
    for f in sorted(rd.glob("slots/*/04_plan.md"), key=lambda f: f.parent.name):
        if dt.datetime.fromtimestamp(f.stat().st_mtime).strftime("%H:%M") > hm:
            continue
        m = re.findall(r"```contract\s*(\{.*?\})\s*```", f.read_text(encoding="utf-8", errors="ignore"), re.S)
        try:
            cands = [str(x.get("code")) for x in (json.loads(m[-1]) if m else {}).get("candidates") or [] if re.fullmatch(r"\d{6}", str(x.get("code") or ""))]
        except ValueError:
            pass
    return list(dict.fromkeys(pos + opens + cands))


def fills_at(book, D):
    """账本 chain 事件里当日"成交"的北京时间 HH:MM 列表"""
    out = []
    for e in book.get("chain") or []:
        if str(e.get("why", "")).startswith("成交") and D.replace("-", "") in str(e.get("why", "")).replace("-", "") or (str(e.get("why", "")).startswith("成交") and str(e.get("at", ""))[:10] == D):
            try:
                t = dt.datetime.fromisoformat(str(e["at"]).replace("Z", "+00:00")).astimezone(dt.timezone(dt.timedelta(hours=8)))
                if t.date().isoformat() == D:
                    out.append(t.strftime("%H:%M"))
            except ValueError:
                pass
    return out


def flips(D):
    o = _jl(MKT / D / "open_live.json", {}) or {}
    J = o.get("judgments") or []
    return {f"{j['t'][:2]}:{j['t'][2:]}": f"开盘实况 {p['label']}→{j['label']}" for p, j in zip(J, J[1:]) if p["label"] != j["label"]}


# ---------------- 主循环 ----------------
class Chain:
    def __init__(self, skill, D, slots):
        self.skill, self.D = skill, D
        self.book_name = mentors.book(skill)
        self.live = skill in event_chain.live_skills()
        self.slots = set() if self.live else {f"{s[:2]}:{s[2:]}" for s in slots if s != "0915"}
        self.hb = LIVE_HEARTBEAT if self.live else HEARTBEAT
        self.cap, self.real_avg = real_cap(skill, D)
        self.base, self.last, self.n, self.blocked, self.sealed, self.capped_hours = {}, None, 0, [], {}, set()

    def step(self, hm, tape, flip_map, out):
        book = _jl(ROOT / "scripts" / "dfcf" / "paper" / "books" / f"{self.book_name}.json", {}) or {}
        codes = watch_codes(self.skill, book, self.D, hm)
        why, must = [], False
        if hm in self.slots and not NO_SLOTS:
            why.append(f"原固定时段 {hm}"); must = True
        hb = heartbeat_min(self.skill, self.D, hm, dynamic=HB_DYNAMIC) if self.hb else 0
        hb_hit = bool(hb and codes and mm(hm) - mm(self.last or "09:25") - (90 if (self.last or "09:25") <= "11:30" < hm else 0) >= hb)
        if hb_hit:
            why.append(f"心跳 {hb} 分钟")
        if hm in fills_at(book, self.D):
            why.append("本链成交"); must = True
        if hm in flip_map and codes:
            why.append(flip_map[hm])
        for c in codes:
            p = tape.at(c, hm)
            if not p:
                continue
            if c not in self.base:
                self.base[c] = p
                continue
            a = amp(c, self.D)
            if abs(p / self.base[c] - 1) >= K_BAND * a:
                why.append(f"{c} 越出策略区间 {(p / self.base[c] - 1) * 100:+.1f}%(±{K_BAND * a * 100:.1f}%)")
            ul = up_limit(c, self.D)
            if ul:
                s = p >= ul - 0.005
                if c in self.sealed and s != self.sealed[c]:
                    why.append(f"{c} {'封板' if s else '炸板'}")
                self.sealed[c] = s
        if not why:
            return
        cool = COOL_OPEN if hm <= "10:30" else COOL
        reason = None
        if not must and self.last and mm(hm) - mm(self.last) < cool:
            reason = "冷却"
        elif not must and self.n >= self.cap and not (hb_hit and len(why) == 1 and not HB_COUNTED):
            reason = "到上限"
        rec = {"t": hm, "skill": self.skill, "why": why, "must": must, "blocked": reason, "watch": len(codes), **({"live": True} if self.live else {})}
        if reason == "到上限":   # 到上限后每分钟都会命中, 只按小时记一次, 防日志灌水
            if hm[:2] in self.capped_hours:
                return
            self.capped_hours.add(hm[:2])
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out.flush()
        if reason:
            self.blocked.append(rec)
            return
        self.n += 0 if must or (hb_hit and len(why) == 1 and not HB_COUNTED) else 1   # 必判(成交 / 原固定时段)和纯心跳(10/21 晚)不占上限
        self.last = hm
        if self.live and FIRE:
            try:
                event_chain.fire(self.skill, self.D, hm, why)
            except Exception as e:   # noqa: BLE001
                log("ERR fire", self.skill, hm, repr(e))
        for c in codes:
            p = tape.at(c, hm)
            if p:
                self.base[c] = p


def minutes():
    t = dt.datetime.strptime("09:25", "%H:%M")
    while t.strftime("%H:%M") <= "14:57":
        hm = t.strftime("%H:%M")
        if not ("11:31" <= hm <= "12:59") and not ("09:26" <= hm <= "09:29" and hm != "09:27"):
            yield hm
        t += dt.timedelta(minutes=1)


def orig_slots(D):
    """当日开盘前冻结的原时段表(10/21 起: 暂停负收益链 / 真跑链停固定子链后, sys_job 不再是原设计, 影子对比要按原表)"""
    return _jl(OUT / f"slots_orig_{D.replace('-', '')}.json") or chain_slots()


def run(D, replay=False):
    global FIRE
    FIRE = not replay
    slots = orig_slots(D)
    chains = [Chain(s, D, slots.get(s, [])) for s in mentors.active_ids()]
    tape = Tape(D, live=not replay)
    od = OUT / D / os.environ["SHADOW_TAG"] if os.environ.get("SHADOW_TAG") else OUT / D
    od.mkdir(parents=True, exist_ok=True)
    with (od / "events.jsonl").open("w", encoding="utf-8") as out:
        for hm in minutes():
            if not replay:
                while dt.datetime.now().strftime("%H:%M") < hm:
                    time.sleep(5)
                time.sleep(10)
                tape.refresh()
            fm = flips(D)
            for ch in chains:
                try:
                    ch.step(hm, tape, fm, out)
                except Exception as e:   # noqa: BLE001
                    log("ERR", ch.skill, hm, repr(e))
    return summary(D, chains)


def summary(D, chains=None):
    od = OUT / D / os.environ["SHADOW_TAG"] if os.environ.get("SHADOW_TAG") else OUT / D
    ev = [json.loads(l) for l in (od / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    slots = orig_slots(D)
    L = [f"# 零成本影子 {D}: 若改成\"模型定策略 + 机械盯盘\", 各链要重定策略几次", "",
         f"口径: 原固定时段 / 开盘实况翻转 / 本链成交 / 关注票越出策略区间(±{K_BAND}×日振幅中位) / 封板炸板; 冷却开盘 3 分钟、其后 5 分钟; 上限 向上取整(k×真人日均出手), tzzb k1={CAP_K1:g}、UP k2={CAP_K2:g}、没数据 k3={CAP_K3:g}×全体日均平均数( 成交 / 固定时段必判不占上限)",
         f"估算单价: 精简一步 ${COST_LITE} / 现子链 ${COST_SUB}(精简一步真实单价待带模型影子测)", "",
         "| 链 | 原子链次数 | 影子重定次数 | 其中新增 | 冷却拦 | 到上限(按小时) | 上限 | 估算多花(精简 / 子链价) |", "|---|---|---|---|---|---|---|---|"]
    tot_old = tot_new = 0
    for s in mentors.active_ids():
        e = [x for x in ev if x["skill"] == s]
        done = [x for x in e if not x["blocked"]]
        old = len([x for x in slots.get(s, []) if x != "0915"])
        cap = (chains and next((c.cap for c in chains if c.skill == s), None)) or real_cap(s, D)[0]
        new = len(done)
        tot_old += old; tot_new += new
        L.append(f"| {s} | {old} | {new} | {new - sum(1 for x in done if x['must'] and any('原固定时段' in w for w in x['why']))} | "
                 f"{sum(1 for x in e if x['blocked'] == '冷却')} | {sum(1 for x in e if x['blocked'] == '到上限')} | {cap} | "
                 f"${new * COST_LITE - old * COST_SUB:+.1f} / ${(new - old) * COST_SUB:+.1f} |")
    L += ["", f"合计: 原子链 {tot_old} 次 → 影子 {tot_new} 次; 估算多花 精简价 ${tot_new * COST_LITE - tot_old * COST_SUB:+.1f} / 子链价 ${(tot_new - tot_old) * COST_SUB:+.1f}(只算盘中重定, 0915 全链和 07 不变)"]
    from collections import Counter
    kinds = Counter()
    for x in ev:
        if not x["blocked"]:
            for w in x["why"]:
                kinds[re.sub(r"^\d{6} ", "", re.sub(r"[ (].*$", "", w))] += 1
    L += ["", "触发原因分布(没被拦的): " + ", ".join(f"{k} {v}" for k, v in kinds.most_common())]
    (od / "summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return "\n".join(L)


def alive():
    try:
        pid = int(LOCK.read_text())
        return str(pid) in subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, creationflags=NOWIN).stdout
    except (OSError, ValueError):
        return False


def ensure():
    import a_rules as AR
    hm = dt.datetime.now().strftime("%H%M")
    if not ("0920" <= hm <= "1500") or not AR._is_trade_day_fallback(dt.date.today().isoformat()) or alive():
        return
    p = subprocess.Popen([sys.executable, "-X", "utf8", str(Path(__file__)), "--run"], cwd=ROOT, creationflags=NOWIN | getattr(subprocess, "DETACHED_PROCESS", 0),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    LOCK.parent.mkdir(exist_ok=True)
    LOCK.write_text(str(p.pid))
    log("拉起", p.pid)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensure", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    if a.ensure:
        ensure()
    elif a.run:
        LOCK.parent.mkdir(exist_ok=True)
        LOCK.write_text(str(os.getpid()))
        log("开始", a.date)
        print(run(a.date))
        log("结束", a.date)
    elif a.replay:
        print(run(a.date, replay=True))
    elif a.summary:
        print(summary(a.date))


if __name__ == "__main__":
    main()
