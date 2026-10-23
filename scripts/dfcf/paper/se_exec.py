# -*- coding: utf-8 -*-
"""se_exec.py — "模型定策略 + 机械执行器" v0 试点(10/21 用户令: 至少做一个 paper 看效果; 先挂梅月路, 影子账本不碰真实账)

和事件触发子链(event_chain.py)的区别: 子链每次触发都要模型重出整张单; 这里模型一次给"策略"(每只票的区间 + 一组条件单规则),
执行器每 3 秒读盘口机械执行, 只有出了区间 / 成交 / 开盘实况翻转 / 60 分钟心跳时才叫模型重定策略。
账本: 自己的影子账(results/_live/<日>/se_<链>/state.json), 起点 = 该链真实账本开盘前状态; 执行器是这本账唯一写入者(D3 ③ 的最小版)。
撮合口径(同 paper 10/19 定): BUY 规则 价≤px 时按 min(px, 卖一) 成交, SELL 规则 价≥px 时按 max(px, 买一) 成交; 每条规则一次; 股数按 A 股申报规则;
         T+1(跨境 ETF 等 T+0 例外, a_rules.is_t0); 费用 = 佣金万 2.5(最低 5 元) + 股票卖出印花税万 5。
重定策略: 冷却 10:30 前 3 分钟 / 之后 5 分钟, 每天上限同影子(4 + 2 × 真人日均出手, 封顶 12); 重定时执行器照旧按老策略跑, 新策略到了再换。
日志(D3 ② 的最小版): strategies/NN_HHMM.json(每版策略 + 当时输入) · actions.jsonl(每次成交: 规则 / 价格 / 五档) · events.jsonl(重定原因 / 拦截) · nav.csv
用法: python se_exec.py --skill meiyuelu [--date D] [--dry(不调模型, 用桩策略自测)]
10/21 09:3x 抢救版补丁: ①事实包 = se_facts.py 零 token 生成到本目录 facts.txt(重定时 60 秒内能现做就现做, 否则用最近一份; 失败不拦重定)
②断点续跑: n_re / n_all / last_re / 到上限 / flips_seen 从 events.jsonl + strategies/ + heartbeat.txt 恢复; pid 锁 scripts/temp/se_<链>.lock 防双开
③curve.csv 每分钟一行(影子 nav vs 真实链账本 nav, 同一份盘口价), 收盘调 se_curve.py 画图 ④heartbeat.txt 每轮写; 盘中有成交时重定在算 → 排队, 算完补叫
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(HERE))
import ipv4_first   # noqa: E402,F401  10/21: 本机 IPv6 不通, 先走 IPv4
import a_rules as AR   # noqa: E402
import shadow_exec as SX   # noqa: E402

PY = ROOT / "scripts" / "venv" / "Scripts" / "python.exe"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MKT = ROOT / "downloads" / "market"
HB_MIN = 60   # 旧口径固定心跳; 10/21 晚起实际用 SX.heartbeat_min(SE_HB_DYNAMIC=0 时回到 60)
INIT_CASH = 100000.0


def flag(name, default=""):
    """chain_flags.txt 同名行(环境变量优先)"""
    v = os.environ.get(name)
    if v is not None:
        return v
    try:
        for line in (ROOT / "scripts" / "claude_profile" / "chain_flags.txt").read_text(encoding="utf-8").splitlines():
            k, _, val = line.split("#")[0].partition("=")
            if k.strip() == name:
                return val.strip()
    except OSError:
        pass
    return default
SCHEMA = {"type": "object", "required": ["view", "codes"], "properties": {
    "view": {"type": "string"},
    "codes": {"type": "array", "items": {"type": "object", "required": ["code", "band", "rules"], "properties": {
        "code": {"type": "string", "pattern": r"^\d{6}$"},
        "band": {"type": "array"},
        "rules": {"type": "array", "items": {"type": "object", "required": ["id", "side", "op", "px", "qty"], "properties": {
            "side": {"enum": ["BUY", "SELL"]}, "op": {"enum": ["<=", ">="]}}}}}}}}}


def now():
    return dt.datetime.now()


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def prev_close(c, D):
    k = (jl(ROOT / "downloads" / "quotes" / "daily" / f"{c}.json", {}) or {}).get("klines") or []
    k = [x for x in k if x.get("d", "") < D]
    return k[-1]["c"] if k else None


class Feed:
    """3 秒盘口尾读(collect_book 的 book_snap.jsonl); 名单外的票每 10 秒新浪批量补"""
    def __init__(self, D):
        self.f, self.pos, self.q, self.extra_t = MKT / D / "book_snap.jsonl", 0, {}, 0

    def refresh(self, codes):
        if self.f.exists():
            with self.f.open("rb") as fh:   # 二进制读: tell() 便宜, 半截尾行可识别
                fh.seek(self.pos)
                while True:
                    l = fh.readline()
                    if not l:
                        break
                    if not l.endswith(b"\n"):   # 写入方写到一半的尾行: 下轮再读
                        break
                    self.pos = fh.tell()
                    try:
                        r = json.loads(l)
                    except ValueError:
                        continue
                    if r.get("p"):
                        self.q[str(r["s"])[2:]] = {"p": float(r["p"]), "t": r.get("t"), "b1": (r.get("b") or [[0]])[0][0], "a1": (r.get("k") or [[0]])[0][0],
                                                   "b": r.get("b"), "k": r.get("k"), "v": r.get("v")}   # v = 全天累计成交量(v3 排队成交判断用)
        miss = [c for c in codes if c not in self.q or self._stale(c)]
        if miss and time.time() - self.extra_t >= 10:
            self.extra_t = time.time()
            try:
                req = urllib.request.Request("http://hq.sinajs.cn/list=" + ",".join(AR.symbol(c) for c in miss), headers={"Referer": "https://finance.sina.com.cn"})
                for line in urllib.request.urlopen(req, timeout=5).read().decode("gbk", "replace").splitlines():
                    m = re.match(r'var hq_str_\w\w(\d{6})="([^"]*)"', line)
                    if m and m.group(2):
                        x = m.group(2).split(",")
                        if float(x[3]) > 0:
                            self.q[m.group(1)] = {"p": float(x[3]), "t": x[31] if len(x) > 31 else "", "b1": float(x[11]), "a1": float(x[21]), "src": "sina"}
            except Exception:   # noqa: BLE001
                pass

    def _stale(self, c):
        t = self.q[c].get("t") or ""
        return not t or (now() - dt.datetime.combine(now().date(), dt.time.fromisoformat(t[:8]))).total_seconds() > 60 if re.fullmatch(r"\d\d:\d\d:\d\d", t[:8]) else True


class SE:
    def __init__(self, skill, D, dry, base=None, cap=None, variant=None):
        import mentors
        self.skill, self.D, self.dry = skill, D, dry
        self.variant = variant or ""   # 10/21 晚用户令: 同一导师的对照变体(nolimit = effort 全 high、不限时长、跑到 11:30); 目录 / 锁 / 花费都按 key 分开
        self.key = skill + (f"@{variant}" if variant else "")
        self.base_given = bool(base)
        self.dir = Path(base) if base else ROOT / "results" / "_live" / D / f"se_{self.key}"
        (self.dir / "strategies").mkdir(parents=True, exist_ok=True)
        self.book_name = mentors.book(skill)
        self.state = jl(self.dir / "state.json") or self._init_state()
        self.strategy, self.ver, self.fired = None, 0, set()
        self.last_re, self.n_re, self.n_all, self.pending = None, 0, 0, False
        self.cap = cap if cap is not None else SX.real_cap(skill, D)[0]
        self.feed = Feed(D)
        self.lock = threading.Lock()
        self.flips_seen = set()
        self._capped, self.queued, self.interrupted = False, None, None
        self.facts_build, self.last_curve = True, None
        self._fix_start()
        self._restore()

    def _events(self):
        out = []
        try:
            for l in (self.dir / "events.jsonl").read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(l))
                except ValueError:
                    pass
        except OSError:
            pass
        return out

    def _restore(self):
        """断点续跑(10/21): 策略版本 / fired 从 strategies/ 接; 计数 / 冷却 / 到上限 / 翻转已看 从 events.jsonl + heartbeat.txt 接"""
        old = sorted((self.dir / "strategies").glob("*.json"))
        if old:
            s = jl(old[-1], {}) or {}
            self.strategy, self.ver = s.get("strategy"), int(old[-1].name[:2]) if old[-1].name[:2].isdigit() else len(old)
            self.fired = set(s.get("fired") or [])
        evs = []
        try:
            for l in (self.dir / "events.jsonl").read_text(encoding="utf-8").splitlines():
                try:
                    evs.append(json.loads(l))
                except ValueError:
                    pass
        except OSError:
            pass
        res = [e for e in evs if e.get("kind") == "重定"]
        self.n_all = len(res)
        self.n_re = max([int(e.get("n") or 0) for e in res] + [0])
        self._capped = any(e.get("kind") == "到上限" for e in evs)
        day = dt.date.fromisoformat(self.D)
        if res:
            self.last_re = dt.datetime.combine(day, dt.time.fromisoformat(res[-1]["t"]))
            # 重定次数 > 落地版本 + 失败 + 异常 = 最后一轮被重启打断(重启时由 run() 补叫一次, 不占上限)
            ended = len(old) + sum(e.get("kind") in ("重定失败", "重定异常") for e in evs)
            if self.n_all > ended:
                self.interrupted = res[-1].get("why")
            # 10/21 晚回放: 崩溃前挂着的失败重试也要接上(最后一个"重定"之后紧跟失败 / 异常且没到 3 次)
            tail = [e for e in evs if e.get("kind") in ("重定", "重定失败", "重定异常")]
            if tail and tail[-1].get("kind") != "重定" and int(tail[-1].get("n_fail") or 0) < 3:
                self.fail_n = int(tail[-1].get("n_fail") or 0)
                self.retry = (time.time() + 90, res[-1].get("why"))
        hb = ""
        try:
            hb = (self.dir / "heartbeat.txt").read_text(encoding="utf-8").split()[0][:5]
        except (OSError, IndexError):
            pass
        # 彩排 B1: 只把"上次重定那一分钟之前"的翻转和"真正写进某次重定原因"的翻转标为已看; 冷却中被挡、还没叫链的翻转重启后照样补叫
        fm = SX.flips(self.D)
        lr = self.last_re.strftime("%H:%M") if self.last_re else ""
        whys = " ".join(str(e.get("why") or "") for e in res)
        self.flips_seen = {k for k, v in fm.items() if (lr and k < lr) or v in whys}
        _ = hb
        if old or evs:
            self.ev(kind="续跑恢复", ver=self.ver, n_re=self.n_re, n_all=self.n_all, last_re=self.last_re.strftime("%H:%M:%S") if self.last_re else None,
                    capped=self._capped, flips_seen=sorted(self.flips_seen), interrupted=self.interrupted, fired=len(self.fired))

    def _init_state(self):
        """起点(10/21 晚用户令: 10/22 起全部导师 10 万从 0 开始, 旧账目归档):
        SE_GENESIS 之后的交易日 = 接前一个交易日本链影子账收盘状态(持仓 / 现金 / 成本, 隔夜后全部可卖); 找不到 = 10 万现金空仓;
        SE_GENESIS 之前(或自测) = 旧口径: 复制旧 paper 账本"""
        gen = flag("SE_GENESIS")
        if gen and self.D >= gen and not self.base_given:
            prev = sorted(p for p in (ROOT / "results" / "_live").glob(f"20*/se_{self.key}/state.json")
                          if gen <= p.parent.parent.name < self.D)
            if prev:
                ps = jl(prev[-1], {}) or {}
                pos = {c: {"qty": int(q["qty"]), "cost": q.get("cost"), "sellable": int(q["qty"])} for c, q in (ps.get("positions") or {}).items() if int(q.get("qty") or 0) > 0}
                cash, frm = round(float(ps.get("cash") or 0), 2), f"carry:{prev[-1].parent.parent.name}"
            else:
                pos, cash, frm = {}, INIT_CASH, "genesis"
            st = {"cash": cash, "positions": pos, "trades": [],
                  "start": {"cash": cash, "positions": json.loads(json.dumps(pos)), "from": frm, "at": now().isoformat(timespec="seconds")}}
            self._save(st)
            return st
        b = jl(ROOT / "scripts" / "dfcf" / "paper" / "books" / f"{self.book_name}.json", {}) or {}
        pos = {c: {"qty": int(p["qty"]), "cost": p.get("cost"), "sellable": int(p["qty"])} for c, p in (b.get("positions") or {}).items() if int(p.get("qty") or 0) > 0}
        st = {"cash": round(float(b.get("cash") or 0), 2), "positions": pos, "trades": [],
              "start": {"cash": b.get("cash"), "positions": json.loads(json.dumps(pos)), "from": self.book_name, "at": now().isoformat(timespec="seconds")}}   # 10/21 修: 原来起点和当前持仓是同一个 dict, 成交会把起点一起改掉
        self._save(st)
        return st

    def _fix_start(self):
        """起点持仓 = 当前持仓 倒推今天成交(精确); 和 state.json 里记的不一致 → 修正(10/21 首批进程起点被成交改坏)"""
        if not str(self.state.get("start", {}).get("from", "")).startswith("A-"):
            return   # 10/22 起新口径(接续 / genesis)起点在建账时就是独立副本, 不用修
        pos = {c: int(p["qty"]) for c, p in self.state["positions"].items()}
        for t in self.state["trades"]:
            pos[t["code"]] = pos.get(t["code"], 0) + (t["qty"] if t["side"] == "SELL" else -t["qty"])
        pos = {c: q for c, q in pos.items() if q > 0}
        st = self.state["start"]
        if pos != {c: int(p["qty"]) for c, p in (st.get("positions") or {}).items() if int(p.get("qty") or 0) > 0}:
            bk = (jl(ROOT / "scripts" / "dfcf" / "paper" / "books" / f"{self.book_name}.json", {}) or {}).get("positions") or {}
            old = st.get("positions")
            st["positions"] = {c: {"qty": q, "cost": (bk.get(c) or {}).get("cost"), "sellable": q} for c, q in pos.items()}
            self._save()
            self.ev(kind="起点修复", old=old, new=st["positions"])
            cf = self.dir / "curve.csv"   # 已写的曲线按修正后的起点重算 %
            if cf.exists():
                s0 = self.start_nav()
                L = cf.read_text(encoding="utf-8").splitlines()
                out = L[:1]
                for l in L[1:]:
                    x = l.split(",")
                    try:
                        out.append(f"{x[0]},{x[1]},{x[2]},{(float(x[1]) / s0 - 1) * 100:.3f},{(float(x[2]) / s0 - 1) * 100:.3f},{s0:.2f}")
                    except (IndexError, ValueError):
                        pass
                cf.write_text("\n".join(out) + "\n", encoding="utf-8")

    def _save(self, st=None):
        (self.dir / "state.json").write_text(json.dumps(st or self.state, ensure_ascii=False, indent=1), encoding="utf-8")

    def ev(self, **k):
        with (self.dir / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": now().strftime("%H:%M:%S"), **k}, ensure_ascii=False) + "\n")

    def wx(self, msg, alert=False):
        """10/21 晚: 15 条同跑, 微信配额约 10 条/用户消息 → 只有 SE_PUSH_SKILLS 里的链推(10/21 晚用户定默认空 = 全不推; * = 全推); 其余只落盘
        alert=True: 告警(花费到线等)不受 SE_PUSH_SKILLS 限制"""
        ps = {x.strip() for x in flag("SE_PUSH_SKILLS", "").split(",") if x.strip()}
        if not alert and "*" not in ps and self.skill not in ps:
            self.ev(kind="未推微信", msg=msg[:120])
            return
        subprocess.Popen([str(PY), "-X", "utf8", "scripts/hermes/wx_send.py", msg[:1500], "--raw", "--src", f"se_{self.skill}"] + (["--dry"] if self.dry else []),
                         cwd=ROOT, creationflags=NOWIN, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ---------------- 模型定策略 ----------------
    def codes(self):
        cs = set(self.state["positions"])
        if self.strategy:
            cs |= {x["code"] for x in self.strategy.get("codes") or []}
        rd = ROOT / "results" / f"{self.skill}_chain" / f"live-{self.D.replace('-', '')}"
        for f in (rd / "04_plan.md",):
            if f.exists():
                m = re.findall(r"```contract\s*\n([\s\S]*?)```", f.read_text(encoding="utf-8", errors="replace"))
                try:
                    cs |= {str(x.get("code")) for x in json.loads(m[-1]).get("candidates") or [] if re.fullmatch(r"\d{6}", str(x.get("code") or ""))}
                except (ValueError, IndexError):
                    pass
        return sorted(cs)

    def facts_codes(self):
        """本链今日事实包里出现的代码(导师本人持仓 / 近期买卖 / 榜单): 允许策略写, 名单外的执行器用新浪补价"""
        f = self.facts_file()
        try:
            return set(re.findall(r"(?<!\d)([036]\d{5}|1[125]\d{4}|5[16]\d{4})(?!\d)", f.read_text(encoding="utf-8", errors="replace")))   # 10/21 晚: 含 11 / 12 开头转债(同 se_chain 候选池)
        except OSError:
            return set()

    def facts_file(self):
        """10/21: 优先读抢救版自己的事实包(se_facts.py 生成到本目录); 没有才退回旧链目录(今天旧链已停, 只作兜底)"""
        f = self.dir / "facts.txt"
        if f.exists() and f.stat().st_size > 0:
            return f
        return ROOT / "results" / f"{self.skill}_chain" / f"live-{self.D.replace('-', '')}" / "facts.txt"

    def refresh_facts(self):
        """重定前备事实包: 60 秒内能现做就现做(三链共享, 15 分钟内有新的就复用), 否则用最近一份; 失败只记 events 不拦重定(fail-open)"""
        try:
            import se_facts
            r = se_facts.refresh(self.skill, self.D, self.dir, allow_build=self.facts_build, wait=0 if flag("SE_CHAIN", "0") == "1" and se_facts.latest(self.D) else 90)   # 10/21 晚回放: 等 60 秒是心跳逼近 180 秒的主因 → 链模式后台现做、本次用最近一份; 当天还没有任何事实包(09:00 首版)就等它做完(最多 90 秒)
        except Exception as e:   # noqa: BLE001
            r = {"ok": False, "src": None, "note": repr(e)[:200]}
        self.ev(kind="事实包" if r.get("ok") else "事实包失败", **r)
        return r

    def open_ctx(self):
        """开盘实况(open_live.json 最新一次判定: 标签 + 指数/外围因子), 零请求"""
        o = jl(MKT / self.D / "open_live.json", {}) or {}
        J = o.get("judgments") or []
        if not J:
            return "(今天开盘实况还没出判定)"
        j = J[-1]
        fl = "; ".join(f"{k} {v}" for k, v in sorted(SX.flips(self.D).items())) or "无"
        L = [f"最新判定 {j.get('t')}: {j.get('label')}(分 {j.get('score')})"] + [f"- {x}" for x in j.get("factors") or []] + [f"今日翻转: {fl}"]
        return "\n".join(L)

    def _chain_ctx(self):
        rd = ROOT / "results" / f"{self.skill}_chain" / f"live-{self.D.replace('-', '')}"
        out = []
        for name in ("02_analysis.md", "03_debate.md", "04_plan.md", "05_risk.md", "06_verdict.md"):
            f = rd / name
            if f.exists():
                m = re.findall(r"```contract\s*\n([\s\S]*?)```", f.read_text(encoding="utf-8", errors="replace"))
                if m:
                    out.append(f"### 本链今日 {name}({dt.datetime.fromtimestamp(f.stat().st_mtime):%H:%M} 写) contract\n{m[-1].strip()[:3000]}")
        return "\n\n".join(out) or "(本链今日盘前全链还没出任何步骤产物)"

    def prompt(self, why):
        cs = self.codes()
        self.feed.refresh(cs)
        rows = []
        for c in cs:
            q, pc = self.feed.q.get(c) or {}, prev_close(c, self.D)
            up, dn = AR.limit_prices(c, self.D, pc) if pc else (None, None)
            rows.append(f"| {c} | {q.get('p')} | {q.get('b1')} | {q.get('a1')} | {pc} | {up} | {dn} | {SX.amp(c, self.D) * 100:.2f}% |")
        st = {k: self.state[k] for k in ("cash", "positions")}
        recent = self.state["trades"][-8:]
        fp = self.facts_file()
        try:
            ff = str(fp.relative_to(ROOT)).replace("\\", "/")
        except ValueError:
            ff = str(fp).replace("\\", "/")
        fv = f"{dt.datetime.fromtimestamp(fp.stat().st_mtime):%H:%M}" if fp.exists() else "缺"
        return f"""你是 {self.skill} skill(同花顺投资账本导师的模拟盘决策者)。现在是 {self.D} {now():%H:%M}, 要你给"机械执行器"写一份盘中策略。
执行器每 3 秒读盘口, 只按你写的规则机械成交; 出了你写的区间 / 有成交 / 开盘实况翻转 / 满 60 分钟才会再叫你。所以策略要能独立跑一段时间, 覆盖"涨了怎么办 / 跌了怎么办"两头。

本次叫你的原因: {why}

先读(必读): skills/{self.skill}-skill/persona/rules_index.md, skills/{self.skill}-skill/persona/profile.md; 需要细节再读 rules.md / cases.md; 今日事实包(大盘/外围/指数面板/资讯/六榜/本导师信号, 零 token 机械构建, {fv} 版) = {ff}, 定策略前至少看「多指数面板」「今日盘前资讯」「导师信号速览」三节。
风格跟导师走(拟人), 教训可以让你偏离导师, 但要写理由。**view / why 等所有文字一律用中文写**。
起点为空仓(10 万现金)时: 按导师的建仓节奏和能力圈从事实包里选票建仓, 不要因为"没有候选"就空着; 只能写事实包里出现的代码。

## 影子账当前状态(执行器唯一账本; sellable=今天可卖股数)
{json.dumps(st, ensure_ascii=False)}
最近成交: {json.dumps(recent, ensure_ascii=False)}

## 标的(下表 = 持仓 + 本链候选, 现价/买一/卖一来自 3 秒盘口; 也可以写 {ff} 里出现的其他代码(如导师本人近期买卖的票), 执行器用新浪补价, 其余代码会被剔除)
| 代码 | 现价 | 买一 | 卖一 | 昨收 | 涨停 | 跌停 | 近30日日振幅中位 |
|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

## 开盘实况(盘中市况判定, 每次重定现读)
{self.open_ctx()}

## 本链(同导师的盘前全链 / 事件子链)今天的结论, 供参考, 不必照抄
{self._chain_ctx()}

## 输出(只要最后一个 ```json 块, 字段如下)
{{"view": "一句话: 今天怎么打、为什么(引规则编号)",
  "codes": [{{"code": "159941", "name": "纳指ETF", "band": [下沿, 上沿],
              "rules": [{{"id": "r1", "side": "SELL", "op": ">=", "px": 价格, "qty": 股数, "why": "规则编号+理由"}},
                        {{"id": "r2", "side": "BUY", "op": "<=", "px": 价格, "qty": 股数, "why": "..."}}]}}],
  "valid_until": "HH:MM 预计这份策略管到几点"}}
硬约束: band=执行器的"出区间就叫你"线(打板/短线型窄, 趋势型宽; 一般 ±0.5~1.5 倍日振幅); BUY 只能 op "<=", SELL 只能 op ">="(都是限价挂单思路);
px 在涨跌停之间; qty 为 100 的整数倍(卖出可等于全部可卖); 同一只票所有 BUY 合计不超过现金, SELL 合计不超过 sellable; 不想动就 rules 为空但 band 必填。"""

    def restrategize(self, why, counted=True, effort=None, tag=None):
        """counted=False: 首版策略 / 成交后必判, 不占每日上限(10/21 用户定上限只卡自由触发)
        effort: 本轮 01→06 用的思考档(None = 开关 SE_EFFORT; 首版 SE_FIRST_EFFORT); tag: "auction" = 09:21 竞价正式版(落地后立刻 high 重跑)"""
        hm_ = now().strftime("%H:%M")
        pz = self._paused() if tag is None and not why.startswith(("开盘前首版", "竞价", "本链成交", "(排队补叫) 本链成交")) else ""
        if pz and self.variant == "keepband" and "出区间" in why:   # 对照变体: 停触发期间"出区间"照样叫链(价格大幅偏离时不至于没人管)
            pz = ""
        if pz:   # 10/21 晚用户令: 满仓 / 06 判"今天不再操作" → 停事件触发
            if getattr(self, "_full_logged", "") != pz:
                self._full_logged = pz
                self.ev(kind="停触发", reason=pz, cash=round(self.state["cash"], 2), why=why)
            return
        self._full_logged = ""
        if tag == "tail" and hm_ > "14:52":   # 尾盘版排队到 14:52 后才轮到 = 来不及 15:00 前出, 不跑
            self.ev(kind="尾盘版来不及", why=why)
            return
        if hm_ >= flag("SE_LAST_CHAIN", "14:54") and not why.startswith("开盘前首版") and tag != "tail":   # 10/21 晚彩排 B2: 截止放在唯一入口, 排队补叫 / 重试也挡住
            if not getattr(self, "_cut_logged", False):
                self._cut_logged = True
                self.ev(kind="收盘前不再重定", cut=flag("SE_LAST_CHAIN", "14:54"), why=why)
            return
        if "11:30" < hm_ < "13:00":   # 午休不发起: 挂到 13:00:05 当失败重试补叫(必判)
            dt13 = dt.datetime.combine(now().date(), dt.time(13, 0, 5))
            self.retry = (time.time() + max(0.0, (dt13 - now()).total_seconds()), why)
            self.ev(kind="午休延后到 13:00", why=why)
            return
        if self.pending:   # 10/21 10:2x: 在算时来的事件(成交 / 开盘实况翻转 / 出区间)一律排队合并, 算完立刻补叫(原来自由触发直接丢, 09:53 翻转被吞)
            if why not in (self.queued or ""):   # 彩排 B3: 合并照做, 日志一轮只记一次
                self.queued = f"{self.queued}; {why}" if self.queued else why
                if not getattr(self, "_queue_logged", False):
                    self._queue_logged = True
                    self.ev(kind="重定排队", why=why, reason="上一轮还在算")
            self.queued_counted = getattr(self, "queued_counted", True) and counted
            if effort:
                self.queued_effort = effort
            if tag:
                self.queued_tag = tag
            return
        self.pending = True
        self.n_re += 1 if counted else 0
        self.n_all += 1
        self.last_re = now()
        t_start = self.last_re.strftime("%H:%M:%S")
        n_tr0 = len(self.state.get("trades") or [])   # 开跑时已有的成交笔数: 之后新增的才算"这版没看到"(按时间比会把触发本轮的那笔成交也算进去)
        eff = effort or (flag("SE_FIRST_EFFORT", "") if why.startswith("开盘前首版") else "") or flag("SE_EFFORT", "low") or "low"
        if self.variant == "nolimit":
            eff = "high"
        elif self.variant in ("low", "sonnet_low"):   # 10/21 晚对照: 全天 low(真成交) / Sonnet 5.5 low
            eff = "low"
        elif self.variant == "sonnet_high":
            eff = "high"
        self.ev(kind="重定", why=why, n=self.n_re, effort=eff, tag=tag)

        def work():
            try:
                self.refresh_facts()
                use_chain = flag("SE_CHAIN", "0") == "1" and not self.dry
                p = "(01→06 串行链, 各步材料与原文见 versions/ 目录)" if use_chain else self.prompt(why)
                if self.dry:
                    s, cost = self._stub(), 0.0
                elif use_chain:   # 10/21 晚: 01→06 串行链, 直连 API, 3 分钟内(se_chain.py)
                    s, cost, tm = self._chain(why, eff)
                    if s is None:
                        k = getattr(self, "fail_n", 0) + 1
                        self.fail_n = k
                        self.ev(kind="重定失败", errors=[str(tm.get("result"))[:200]], n_fail=k, chain=tm.get("total"))
                        if k < 3:
                            self.retry = (time.time() + 90, why)
                        self.wx(f"【{self.key} 策略执行器】01→06 失败({k}/3), 沿用上一版{', 90 秒后自动重试' if k < 3 else ', 不再重试'}: {str(tm.get('result'))[:160]}", alert=(k >= 2))
                        return
                    self.fail_n, self.retry = 0, None   # 成功了就撤掉挂着的重试
                else:
                    from claude_call import call
                    r = call(p, tag=f"se-{self.skill}", allowed_tools=["Read", "Grep", "Glob"], timeout=360, json_schema=SCHEMA)
                    cost = r.cost_usd
                    if not r.ok and re.search(r"ECONNRESET|Connection (dropped|error|refused)|socket hang up|ETIMEDOUT|overloaded|\b5\d\d\b", " ".join(r.errors)):   # 10/21 09:54 两次 API 断连: 网络类错误重试一次
                        self.ev(kind="重定重试", errors=r.errors[:2])
                        time.sleep(10)
                        r = call(p, tag=f"se-{self.skill}", allowed_tools=["Read", "Grep", "Glob"], timeout=360, json_schema=SCHEMA)
                        cost += r.cost_usd
                    s = r.parsed if r.ok else None
                    if not r.ok:
                        k = getattr(self, "fail_n", 0) + 1
                        self.fail_n = k
                        self.ev(kind="重定失败", errors=r.errors[:3], n_fail=k)
                        if k < 3:   # 失败不丢: 90 秒后带原因自动再叫(不占上限), 连续 3 次都失败才放弃
                            self.retry = (time.time() + 90, why)
                        self.wx(f"【{self.skill} 策略执行器】重定失败({k}/3), 沿用上一版{', 90 秒后自动重试' if k < 3 else ', 不再重试'}: {'; '.join(r.errors[:2])[:160]}", alert=k >= 2)   # 10/22 09:1x 补: TODO 1.6 写的"失败第 2 次起推告警"原来只覆盖代码异常, 链失败没告警
                        return
                    self.fail_n, self.retry = 0, None   # 成功了就撤掉挂着的重试
                s, dropped = self.check(s)
                with self.lock:
                    self._unseen_fills(s, dropped, t_start, n_tr0)   # 链开跑后才发生的成交(如 09:25 竞价成交): 新版本没看到, 对这些票的买单先拿掉, 等补叫的那版再定
                    self._auction_swap(s, dropped)   # 10/21 晚(★12): 09:20 前落地 = 草稿; 09:20~09:24:57 第一个落地的挂竞价单; 之后到 09:25 冻结
                    self.ver += 1
                    self.strategy, self.fired = s, set()
                    self._rest_stop = bool((s.get("rest_of_day") or {}).get("stop")) if isinstance(s.get("rest_of_day"), dict) else False
                    (self.dir / "strategies" / f"{self.ver:02d}_{now():%H%M}.json").write_text(
                        json.dumps({"why": why, "effort": eff, "tag": tag, "strategy": s, "dropped": dropped, "cost_usd": cost, "fired": [], "prompt": p}, ensure_ascii=False, indent=1), encoding="utf-8")
                if tag == "auction":
                    self._after_auc_high = True
                L = [f"【{self.skill} 策略执行器 v{self.ver} {now():%H:%M}】因: {why}", f"看法: {str(s.get('view'))[:200]}"]
                for x in s.get("codes") or []:
                    L.append(f"· {x.get('name') or ''}{x['code']} 区间 {x['band'][0]}~{x['band'][1]}")
                    for r_ in x.get("rules") or []:
                        L.append(f"   {r_['side']} 价{r_['op']}{r_['px']} ×{r_['qty']} | {str(r_.get('why', ''))[:70]}")
                if dropped:
                    L.append("执行器剔除: " + "; ".join(dropped)[:200])
                L.append(f"管到 {s.get('valid_until')} | 本次 ${cost:.2f} | 今日第 {self.n_all} 次(自由触发 {self.n_re}/{self.cap}, 首版和成交后不占)")
                self.wx("\n".join(L))
            except Exception as e:   # noqa: BLE001
                k = getattr(self, "fail_n", 0) + 1   # 10/21 晚回放: 代码异常原来不重试不计数, 首版直接丢
                self.fail_n = k
                self.ev(kind="重定异常", err=repr(e)[:300], n_fail=k)
                self.wx(f"【{self.key} 策略执行器 异常】{repr(e)[:200]}(第 {k} 次; {'90 秒后重试' if k < 3 else '不再重试'})", alert=True)
                if k < 3:
                    self.retry = (time.time() + 90, why)
            finally:
                self.last_done = now()
                try:
                    self.spend_check()
                except Exception:   # noqa: BLE001
                    pass
                self.pending, self._queue_logged = False, False
                q, self.queued = self.queued, None
                qc, self.queued_counted = getattr(self, "queued_counted", True), True
                qe, self.queued_effort = getattr(self, "queued_effort", None), None
                qt, self.queued_tag = getattr(self, "queued_tag", None), None
                if getattr(self, "_after_auc_high", False):   # ★12: 09:21 low 落地 → 立刻 high 重跑完整 01→06(排队的原因一并带上)
                    self._after_auc_high = False
                    self.restrategize("竞价正式版落地后 high 重跑" + (f"; {q}" if q else ""), counted=False, effort=flag("SE_EFFORT", "high") or "high")
                elif q:
                    self.restrategize("(排队补叫) " + q, counted=qc, effort=qe, tag=qt)
        threading.Thread(target=work, daemon=True).start()

    def _chain(self, why, effort="low"):
        """跑一遍 01→06(se_chain.run), 版本目录 versions/NN_HHMMSS/; 返回 (strategy|None, 美元, timing)
        10/21 晚(★12): effort 非 low 时每步上限 / 时限 ×2.5、整条预算 600 秒; 同一份 01 快照另起一条影子链(SE_SHADOW_EFFORT, 只落盘不执行)"""
        sys.path.insert(0, str(ROOT / "scripts" / "chain"))   # 10/21 晚: 01→06 链在 scripts/chain/se_chain.py
        import se_chain
        vd = self.dir / "versions" / f"{self.ver + 1:02d}_{now():%H%M%S}"
        prev = sorted((self.dir / "versions").glob("*/02_market.md"))
        prev02 = self._continuity(prev)   # 10/21 晚: 链之间的"记忆" = 上一版 02 全文(原来截 2500 字) + 上一版 06 的看法 / 下一轮预期 / 失效条件 / 今天停不停 + 今日各版一览
        try:
            ff = self.facts_file()
            facts = f"(本份慢层材料生成于 {dt.datetime.fromtimestamp(ff.stat().st_mtime):%H:%M:%S}, 不是此刻; 价格 / 持仓以上面快层为准)\n" + ff.read_text(encoding="utf-8", errors="replace")
            # 10/21 晚: 事实包里"昨日账本状态"是旧 paper 账本(A-<导师>), 和新 paper 影子账(10 万起)冲突 → 拿掉, 账户以 01 的"账户"块为准
            facts = re.sub(r"## 昨日账本状态[\s\S]*?(?=\n## (?!A-))","## 昨日账本状态\n(旧 paper 账本, 新 paper 不用; 账户以上面 01 的「账户」块为准)\n", facts, count=1)
        except OSError:
            facts = "(今日事实包缺)"
        with self.lock:
            state = json.loads(json.dumps(self.state))
            strat, fired = json.loads(json.dumps(self.strategy)) if self.strategy else None, set(self.fired)
        at, quotes, oc = now().strftime("%H:%M:%S"), dict(self.feed.q), self.open_ctx()
        pre01 = se_chain.build_01(self.skill, self.D, at, why, state, strat, fired, quotes, facts, oc, prev02, live=True)
        kw = lambda e: {"effort": e, "step_scale": 1.0 if e == "low" else 2.5, "budget": se_chain.CHAIN_BUDGET if e == "low" else 600, "tag_skill": self.key}   # noqa: E731
        if self.variant == "nolimit":   # 不限时长: 每步上限 / 时限 ×10(02 约 10 分钟、06 约 45000 token)、整条不设预算, 让它自然结束
            kw = lambda e: {"effort": e, "step_scale": 10.0, "budget": 99999, "tag_skill": self.key}   # noqa: E731
        if self.variant == "toolcall":   # 对照 C: 同正式版的 effort / 时限, 但模型可自己调 lookup 查料(每步最多 2 次)
            _k0 = kw
            kw = lambda e: {**_k0(e), "tool_mode": True, "budget": 900 if e != "low" else 300}   # noqa: E731
        if self.variant in ("sonnet_low", "sonnet_high"):   # 10/21 晚对照: 换 Sonnet 5.5(其余同正式版)
            _k1 = kw
            kw = lambda e: {**_k1(e), "model": "claude-sonnet-5-5"}   # noqa: E731
        sh = "high" if self.skill in self._auc_test_skills() else ("" if self.variant else flag("SE_SHADOW_EFFORT", ""))   # 竞价测试链: 正式 low + 同快照 high
        if sh and sh != effort and not getattr(self, "_shadow_busy", False):
            self._shadow_busy = True

            def shadow():
                try:
                    s2, c2, t2 = se_chain.run(self.skill, self.D, at, "(影子) " + why, state, strat, fired, quotes, facts, oc, prev02, vd / f"shadow_{sh}", live=True, pre01=pre01, **kw(sh))
                    self.ev(kind="影子链", effort=sh, ver=vd.name, secs=t2.get("total"), usd=round(c2, 3), ok=s2 is not None, result=t2.get("result"),
                            codes=[x.get("code") for x in (s2 or {}).get("codes") or []], n_rules=sum(len(x.get("rules") or []) for x in (s2 or {}).get("codes") or []))
                except Exception as e:   # noqa: BLE001
                    self.ev(kind="影子链异常", err=repr(e)[:200])
                finally:
                    self._shadow_busy = False
            threading.Thread(target=shadow, daemon=True).start()
        elif sh and sh != effort:
            self.ev(kind="影子链跳过", why="上一条影子还在跑")
        s, cost, tm = se_chain.run(self.skill, self.D, at, why, state, strat, fired, quotes, facts, oc, prev02, vd, live=True, pre01=pre01, **kw(effort))
        self.ev(kind="链耗时", effort=effort, secs=tm.get("total"), usd=round(cost, 3), steps={k: v.get("secs") for k, v in (tm.get("steps") or {}).items() if isinstance(v, dict)}, result=tm.get("result"))
        return s, cost, tm

    def _unseen_fills(self, s, dropped, t_start, n_tr0=None):
        """10/21 晚(用户确认的开盘口径): low 的竞价单成交就按事实成交; high 版是成交前开跑的、没看到这笔成交 → 落地时对这些票的 BUY 规则先拿掉(防重复买),
        10/21 晚用户确认: 卖单同理 —— 这些票的买单和卖单都先不挂; 成交本身已触发"竞价成交"必判, 排队到这版落地后立刻补叫, 由补叫那版重新定这些票"""
        tr = self.state.get("trades") or []
        codes = {t["code"] for t in (tr[n_tr0:] if n_tr0 is not None else [x for x in tr if str(x.get("t", "")) > t_start])}
        if not codes or not s:
            return
        n = 0
        for x in s.get("codes") or []:
            if x.get("code") in codes:
                keep = []
                n += len(x.get("rules") or []) - len(keep)
                x["rules"] = keep
        if n:
            dropped.append(f"本版开跑({t_start})后 {','.join(sorted(codes))} 已成交, 本版没看到 → 这些票的规则 {n} 条(买 + 卖)先不挂, 等补叫的下一版")
            self.ev(kind="未见成交剔买单", codes=sorted(codes), n=n, t_start=t_start)

    def _continuity(self, prev02_files):
        """给下一条链的连续性材料(每次触发都由脚本按同一格式现拼, 不依赖模型会话)
        10/21 晚用户令: 上一轮 01→06 的全部推理(02~06 原文, 约 15~20KB)整份给; 不给上一轮 01(那是旧快照, 这次 01 已按此刻数据重算, 给旧的反而混淆价格);
        更早的各版给 06 结论(看法 / 下一轮预期 / 失效条件)+ 一行一览"""
        L = []
        vdirs = sorted(d for d in (self.dir / "versions").glob("*") if d.is_dir() and (d / "06_final.md").exists())
        if vdirs:
            v = vdirs[-1]
            parts = []
            for name, title in (("02_market.md", "02 市况"), ("03_bull.md", "03 多方"), ("03_bear.md", "03 空方"), ("04_pick.md", "04 选票"), ("05_risk.md", "05 风控"), ("06_final.md", "06 终裁")):
                f = v / name
                if f.exists():
                    parts.append(f"#### {title}\n" + f.read_text(encoding="utf-8", errors="replace"))
            L.append(f"### 上一轮 01→06 全文(版本 {v.name}; 01 不给——本次 01 已按此刻数据重算)\n" + "\n\n".join(parts))
        elif prev02_files:
            L.append("### 上一版 02 市况(全文)\n" + prev02_files[-1].read_text(encoding="utf-8", errors="replace"))
        s = self.strategy or {}
        if s:
            t = "### 上一版 06 结论\n" + "\n".join(f"- {k}: {str(s.get(k))[:600]}" for k in ("view", "next", "invalid", "mimic", "valid_until") if s.get(k))
            if s.get("rest_of_day"):
                t += f"\n- 今天停不停: {json.dumps(s.get('rest_of_day'), ensure_ascii=False)}"
            if (s.get("chain") or {}).get("05"):
                t += f"\n- 上一版 05: {json.dumps(s['chain']['05'], ensure_ascii=False)[:400]}"
            L.append(t)
        vl, older = [], []
        files = sorted((self.dir / "strategies").glob("*.json"))
        for f in files:
            d = jl(f, {}) or {}
            st_ = d.get("strategy") or {}
            vl.append(f"- v{f.name[:2]} {f.name[3:7]} [{d.get('effort') or ''}] 因: {str(d.get('why'))[:60]} | 看法: {str(st_.get('view'))[:80]}")
            if f is not files[-1] and (st_.get("next") or st_.get("invalid")):
                older.append(f"- v{f.name[:2]} {f.name[3:7]}: 下一轮预期 {str(st_.get('next'))[:200]} | 失效条件 {str(st_.get('invalid'))[:200]}")
        if vl:
            L.append("### 今日各版一览(时间 / effort / 触发原因 / 看法)\n" + "\n".join(vl[-12:]))
        if older:
            L.append("### 更早各版的下一轮预期 / 失效条件(看今天的判断哪些兑现了)\n" + "\n".join(older[-10:]))
        return "\n\n".join(L) or None

    def _auction_swap(self, s, dropped):
        """10/21 晚(★12) 竞价单规则(调用方已拿执行锁): 落地 < 09:20 = 草稿(竞价单不挂); 09:20 ≤ 落地 < 09:25:05 且还没挂过 → 本版挂竞价单;
        已挂过 → 冻结: 沿用已挂的竞价单(标 carried, 只参加 09:25 撮合, 09:30 后不当限价单), 本版的竞价单丢弃; 09:25:05 后 = 竞价结束, 整份替换"""
        t = now().strftime("%H:%M:%S")
        if t >= "09:25:05" or not s:
            return
        old = self.strategy or {}
        if t < "09:20:00":
            s["auc_draft"] = t
            return
        if not old.get("auc_submitted"):
            s["auc_submitted"] = t
            self.ev(kind="竞价单挂出", at=t, n=sum(1 for x in s.get("codes") or [] for r in x.get("rules") or [] if r.get("auction")))
            return
        s["auc_submitted"] = old["auc_submitted"]
        lost = 0
        for x in s.get("codes") or []:
            n0 = len(x.get("rules") or [])
            x["rules"] = [r for r in x.get("rules") or [] if not r.get("auction")]
            lost += n0 - len(x["rules"])
        keep = [(x, r) for x in old.get("codes") or [] for r in x.get("rules") or [] if r.get("auction") and f"{self.ver}:{x['code']}:{r['id']}" not in self.fired]
        for x, r in keep:
            tgt = next((y for y in s.get("codes") or [] if y.get("code") == x["code"]), None)
            if tgt is None:
                tgt = {"code": x["code"], "name": x.get("name"), "band": x.get("band"), "rules": []}
                s.setdefault("codes", []).append(tgt)
            tgt["rules"].append({**r, "id": "c_" + str(r["id"]), "carried": True})
        self.ev(kind="竞价单冻结", at=t, kept=len(keep), dropped_new=lost)
        if lost:
            dropped.append(f"09:20 后竞价单不可撤: 本版 {lost} 条竞价单丢弃, 沿用已挂的 {len(keep)} 条")

    def _stub(self):
        cs = self.codes()
        self.feed.refresh(cs)
        out = []
        for c in cs:
            p = (self.feed.q.get(c) or {}).get("p") or prev_close(c, self.D)
            if not p:
                continue
            a = SX.amp(c, self.D)
            held = self.state["positions"].get(c, {}).get("sellable", 0)
            rules = [{"id": "s1", "side": "SELL", "op": ">=", "px": round(p * (1 + a / 2), 3), "qty": held // 200 * 100, "why": "桩: 冲高卖一半"}] if held >= 200 else []
            out.append({"code": c, "band": [round(p * (1 - a), 3), round(p * (1 + a), 3)], "rules": rules})
        return {"view": "桩策略(自测)", "codes": out, "valid_until": "15:00"}

    def check(self, s):
        """执行器硬校验: 不合法的规则剔掉(不回炉, 记下来推给用户看)"""
        dropped, codes = [], []
        cash, ok_codes = self.state["cash"], set(self.codes()) | self.facts_codes()
        for x in (s or {}).get("codes") or []:
            c = str(x.get("code"))
            if c not in ok_codes:
                dropped.append(f"{c} 不在可用标的")
                continue
            try:
                lo, hi = float(x["band"][0]), float(x["band"][1])
            except (KeyError, IndexError, TypeError, ValueError):
                dropped.append(f"{c} band 非法")
                continue
            pc = prev_close(c, self.D)
            up, dn = AR.limit_prices(c, self.D, pc) if pc else (None, None)
            held = self.state["positions"].get(c, {}).get("sellable", 0)
            rules, buy_amt, sell_q = [], 0.0, 0
            for r in x.get("rules") or []:
                try:
                    px, q = float(r["px"]), int(r["qty"])
                except (KeyError, TypeError, ValueError):
                    dropped.append(f"{c} {r.get('id')} 价/量非法")
                    continue
                if (r["side"] == "BUY") != (r["op"] == "<="):
                    dropped.append(f"{c} {r['id']} 方向与条件不配")
                    continue
                if up and not (dn <= px <= up):
                    dropped.append(f"{c} {r['id']} 价 {px} 超涨跌停")
                    continue
                okq, why = AR.valid_qty(c, q, r["side"], held if r["side"] == "SELL" else None)
                if not okq:
                    dropped.append(f"{c} {r['id']} {why}")
                    continue
                if r["side"] == "BUY":
                    buy_amt += px * q
                else:
                    sell_q += q
                rules.append({**r, "px": px, "qty": q})
            if sell_q > held:
                dropped.append(f"{c} 卖出合计 {sell_q} > 可卖 {held}(仍保留, 执行时按可卖截断)")
            codes.append({**x, "code": c, "band": [lo, hi], "rules": rules})
            cash -= 0   # 买入合计超现金不剔(执行时按现金截断), 只提示
            if buy_amt > self.state["cash"]:
                dropped.append(f"{c} 买入合计 {buy_amt:.0f} > 现金 {self.state['cash']:.0f}(执行时按现金截断)")
        return {**(s or {}), "codes": codes}, dropped

    # ---------------- 机械执行 ----------------
    def fee(self, c, side, amt):
        f = max(5.0, amt * 0.00025)
        if side == "SELL" and AR.board(c) not in ("ETF", "LOF", "CB"):
            f += amt * 0.0005
        return round(f, 2)

    def tick(self, hm, auction=False):
        """auction="close": 15:00 尾盘集合竞价一次撮合(10/21 晚用户令) —— 14:57 时还活着的所有规则 + 14:57~15:00 新落地版本的规则一起参加, 按收盘价成交(买价 ≥ 收盘价 / 卖价 ≤ 收盘价)
        auction=True: 09:25 竞价一次撮合(10/21 晚用户认): 只看带 "auction": true 的规则, 开盘价 = 09:25 后盘口现价;
        买价 ≥ 开盘价 / 卖价 ≤ 开盘价 → 按开盘价成交; 没成交的竞价单 09:30 起按普通限价单继续有效"""
        fills, nofill = [], False
        with self.lock:
            s = self.strategy
            if not s:
                return fills
            for x in s.get("codes") or []:
                c, q = x["code"], self.feed.q.get(x["code"])
                if not q or (auction is True and str(q.get("t") or "")[:8] < "09:25:00") or (auction == "close" and str(q.get("t") or "")[:8] < "15:00:00"):
                    continue
                p = q["p"]
                for r in x.get("rules") or []:
                    key = f"{self.ver}:{c}:{r['id']}"
                    if r.get("type") == "board_dip":   # 10/22 晚(v3): 炸板接单由 paper_v3/executor 单独撮合(要看"今天封过板 + 现在开板 + 落在区间"), 这里跳过; v2 规则没有 type
                        continue
                    if r.get("after") and not any(str(t.get("rule", "")) == f"{self.ver}:{c}:{r['after']}" for t in self.state.get("trades") or []):
                        continue   # 10/22 深夜(v3): 前置条件 —— after 指的那张单成交之前, 这张不生效(先卖后买 / 先买后卖的顺序); v2 规则没有 after
                    if key in self.fired or (auction is True and not (r.get("auction") and s.get("auc_submitted"))) or (auction != True and r.get("carried")):   # noqa: E712   # ★12: 只撮合已挂出的竞价单(草稿不撮合); 冻结沿用的竞价单 09:30 后不当限价单
                        continue
                    if auction:
                        hit = r["px"] >= p if r["side"] == "BUY" else r["px"] <= p
                    elif r.get("rest"):   # 10/23 凌晨用户定"穿价 + 成交量"双保险: 排队单 = 价格穿过挂单价才成交; 正好碰到挂单价时, 要累计成交量超过挂单时排在前面的量(_queued_ok, 由 v3 executor 维护)
                        hit = (p < r["px"] if r["side"] == "BUY" else p > r["px"]) or (p == r["px"] and bool(r.get("_queued_ok")))
                    else:
                        hit = p <= r["px"] if r["side"] == "BUY" else p >= r["px"]
                    if not hit:
                        continue
                    if not auction and not q.get("src") and q.get("t") and self.feed._stale(c):   # 10/21 晚回放: 盘口断流(>60 秒没更新)不按旧价撮合(没时间戳的 = 自测桩, 不判)
                        if getattr(self, "_stale_logged", {}).get(c) != hm:
                            self._stale_logged = {**getattr(self, "_stale_logged", {}), c: hm}
                            self.ev(kind="盘口陈旧不撮合", code=c, t=q.get("t"))
                        continue
                    pc_ = prev_close(c, self.D)
                    up_, dn_ = AR.limit_prices(c, self.D, pc_) if pc_ else (None, None)
                    if not auction and r["side"] == "BUY" and up_ and p >= up_ - 1e-6 and not (q.get("a1") or 0):
                        continue   # 涨停封板(卖一空)买不进: 不算触发, 规则留着等开板
                    if not auction and r["side"] == "SELL" and dn_ and p <= dn_ + 1e-6 and not (q.get("b1") or 0):
                        continue   # 跌停封板(买一空)卖不出
                    pos = self.state["positions"].setdefault(c, {"qty": 0, "cost": None, "sellable": 0})
                    if auction:
                        px = p
                        n = min(r["qty"], AR.round_qty(c, (self.state["cash"] - max(5.0, self.state["cash"] * 0.0003)) / px)) if r["side"] == "BUY" else min(r["qty"], pos["sellable"])
                    elif r["side"] == "BUY":
                        # 10/22 晚(v3): 挂单时就在排队的单(rest = 当时买价 < 现价) 被价格穿过时按挂单价成交, 不享受"价格改善";
                        # 例 星光 10/22 09:40 开板砸到 2.58, 2.70 排板单实际在 2.70 成交, 原逻辑按 2.58 买 → 账面虚高 4.4%。v2 规则没有 rest 字段, 行为不变
                        px = r["px"] if r.get("rest") else (min(r["px"], q.get("a1") or p) or p)
                        n = min(r["qty"], AR.round_qty(c, (self.state["cash"] - max(5.0, self.state["cash"] * 0.0003)) / px))
                        if not r.get("rest") and r.get("depth"):   # 10/22 晚(v3): 立刻成交的单按盘口深度吃档(卖一量不够吃到卖二、卖三), 加权价; 限价内深度不够只成交够的部分
                            px, n = depth_fill(q.get("k"), r["px"], n, "BUY", c) or (px, n)
                    else:
                        px = r["px"] if r.get("rest") else max(r["px"], q.get("b1") or p)
                        n = min(r["qty"], pos["sellable"])
                        if not r.get("rest") and r.get("depth"):
                            px, n = depth_fill(q.get("b"), r["px"], n, "SELL", c) or (px, n)
                    self.fired.add(key)
                    if n <= 0:
                        self.ev(kind="规则命中但没钱/没可卖", rule=key, p=p)
                        nofill = True   # 彩排 B4: fired 也要落盘, 否则重启后这条规则复活
                        continue
                    amt = px * n
                    fe = self.fee(c, r["side"], amt)
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
                    t = {"t": now().strftime("%H:%M:%S"), "code": c, "name": x.get("name"), "side": r["side"], "px": round(px, 3), "qty": n, "fee": fe,
                         "rule": key, "why": r.get("why"), **({"auction": True} if auction else {}), "tape": {k: q.get(k) for k in ("p", "t", "b", "k")}}
                    self.state["trades"].append({k: v for k, v in t.items() if k != "tape"})
                    with (self.dir / "actions.jsonl").open("a", encoding="utf-8") as f:
                        f.write(json.dumps(t, ensure_ascii=False) + "\n")
                    fills.append(t)
            if fills:
                self._rest_stop = False   # 有成交 = 06 "今天不再操作"的前提变了, 恢复触发(成交本身会叫一次链重判)
            if fills or nofill:
                if fills:
                    self._save()
                sp = sorted((self.dir / "strategies").glob(f"{self.ver:02d}_*.json"))
                if sp:
                    d = jl(sp[-1], {})
                    d["fired"] = sorted(self.fired)
                    sp[-1].write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        for t in fills:
            self.wx(f"【{self.skill} 策略执行器 成交 {t['t']}】{t['side']} {t.get('name') or ''}{t['code']} {t['qty']}@{t['px']} 规则 {t['rule']} | {str(t.get('why'))[:80]} | 现金 {self.state['cash']:.0f}")
        return fills

    def _spend(self):
        """(本链今天全部模型花费, 其中影子链) —— claude_cost.csv 里 se-<链> / se-chain-<链>-* 当天行"""
        tot = sh = 0.0
        try:
            import csv
            with (ROOT / "scripts" / "lib" / "claude_cost.csv").open(encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    t = r.get("tag", "")
                    if r.get("ts", "").startswith(self.D) and (t == f"se-{self.key}" or t.startswith(f"se-chain-{self.key}-")):
                        c = float(r.get("cost_usd") or 0)
                        tot += c
                        sh += c if t.startswith(f"se-chain-{self.key}-shadow-") else 0
        except (OSError, ValueError):
            pass
        return tot, sh

    def _paused(self):
        """停触发的原因(空串 = 不停): 现金买不起 1 手 / 06 判今天不再操作"""
        if flag("SE_FULL_PAUSE", "1") != "1":
            return ""
        if self._full_invested():
            return "满仓(现金买不起 1 手)"
        if getattr(self, "_rest_stop", False):
            return "06 判今天不再操作: " + str(((self.strategy or {}).get("rest_of_day") or {}).get("why") or "")[:60]
        return ""

    def _full_invested(self):
        """10/21 晚用户令: 仓位 = 100% / 现金买不起 1 手 → 停事件触发(出区间 / 翻转 / 心跳 / 失败重试 / 手动 / 排队补叫)。
        "1 手" 取本链此刻可选标的(持仓 + 当前策略里的票)里最便宜的一手(股票 100 股、科创 200 股、转债 10 张) + 手续费; 都没价就按 100 股 × 1 元算。
        不停的(用户确认的口径): 首版 / 09:21 竞价版 / 竞价后 high 重跑 / 14:51 尾盘版(固定时刻的版本, 否则隔夜满仓的链一整天没有卖出规则);
        已挂规则照常机械成交; 一旦有卖出成交、现金够一手, 自然恢复(成交本身是必判触发)。开关 SE_FULL_PAUSE=0 关掉"""
        if flag("SE_FULL_PAUSE", "1") != "1":
            return False
        lots = []
        for c in set(self.state.get("positions") or {}) | {str(x.get("code")) for x in (self.strategy or {}).get("codes") or []}:
            p = (self.feed.q.get(c) or {}).get("p") or prev_close(c, self.D)
            if p:
                lots.append(p * AR.lot_rule(c)["min"])
        need = (min(lots) if lots else 100.0) + 5.0
        return self.state["cash"] < need

    def spend_check(self):
        """10/21 晚(★1-G): 本链今天模型花费(claude_cost.csv 里 se-<链> / se-chain-<链>-* 当天行合计, 含失败的调用)到 SE_COST_ALERT 美元推一条告警, 照跑不停; 一天只推一次"""
        lim = float(flag("SE_COST_ALERT", "30") or 0)
        if lim <= 0 or getattr(self, "_cost_alerted", False) or self.dry:
            return
        tot = 0.0
        try:
            import csv
            with (ROOT / "scripts" / "lib" / "claude_cost.csv").open(encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    if r.get("ts", "").startswith(self.D) and (r.get("tag") == f"se-{self.skill}" or r.get("tag", "").startswith(f"se-chain-{self.skill}-")):
                        tot += float(r.get("cost_usd") or 0)
        except (OSError, ValueError):
            return
        if tot >= lim:
            self._cost_alerted = True
            self.ev(kind="花费到线", usd=round(tot, 2), lim=lim)
            self.wx(f"【{self.skill} 策略执行器 花费告警】今天模型花费已 ${tot:.1f}(提醒线 ${lim:.0f}), 照跑不停; 已重定 {self.n_all} 次", alert=True)

    def need_re(self, hm, fills):
        why, must = [], False
        if fills:
            why.append("本链成交 " + ",".join(f"{t['side']}{t['code']}" for t in fills)); must = True
        rt = getattr(self, "retry", None)
        if rt and time.time() >= rt[0] and not self.pending:
            self.retry = None
            why.append("(失败重试) " + re.sub(r"^(\(失败重试\) |\(排队补叫\) )+", "", str(rt[1]))[:120]); must = True
        kick = self.dir / "KICK"   # 手动叫重定: 往影子账目录写 KICK(内容=原因), 必判不占上限, 读完即删
        if kick.exists():
            why.append("手动: " + (kick.read_text(encoding="utf-8", errors="replace").strip() or "手动重定")[:100]); must = True
            kick.unlink(missing_ok=True)
        s = self.strategy or {}
        for x in s.get("codes") or []:
            q = self.feed.q.get(x["code"])
            if q and not (x["band"][0] <= q["p"] <= x["band"][1]):
                why.append(f"{x['code']} {q['p']} 出区间 {x['band'][0]}~{x['band'][1]}")
        fm = SX.flips(self.D)
        new_flips = []   # 10/21 晚修: 原来先标"已看过"再判冷却, 冷却中来的翻转被永久吞掉(梅月路 10:06); 现在真正叫链(或到上限)时才标
        for k, v in fm.items():
            if k <= hm and k not in self.flips_seen:
                if k >= (self.last_re.strftime("%H:%M") if self.last_re else "00:00"):
                    why.append(v)
                    new_flips.append(k)
                else:
                    self.flips_seen.add(k)
        hb_hit = False
        ref = self.last_re
        if ref and not self.pending:   # 10/21 晚用户: 任何一次重定(成交 / 出区间 / 翻转 …)都把心跳往后推, 从那次触发时刻(精确到秒)重新计; 例 5 分钟档 09:32:00 触发 → 下次心跳 09:37:00; 在算时不判心跳
            gap = (now() - ref).total_seconds() / 60 - (90 if ref.strftime("%H:%M") <= "11:30" < hm else 0)
            hb = SX.heartbeat_min(self.skill, self.D, hm, dynamic=flag("SE_HB_DYNAMIC", "1") == "1")   # 10/21 晚: 按导师真人决策间隔 P75 + 时段下限, 无上限
            if gap >= hb:
                why.append(f"心跳 {hb} 分钟")
                hb_hit = True
        if not why:
            return
        cut = flag("SE_LAST_CHAIN", "14:54")   # 10/21 晚(★1-D): 14:54 后不再发起新的重定(14:57 停, 之后发起的跑不完、挂单收盘作废); 已挂规则照常机械成交
        if now().strftime("%H:%M") >= cut:
            if not getattr(self, "_cut_logged", False):
                self._cut_logged = True
                self.ev(kind="收盘前不再重定", cut=cut, why=why)
            return
        cool = 3 if hm <= "10:30" else 5
        if not must and self.last_re and (now() - self.last_re).total_seconds() < cool * 60:
            return   # 冷却中(不记日志, 防每 3 秒灌水; 出区间会在冷却后再判)
        self.flips_seen.update(new_flips)
        if must or (hb_hit and len(why) == 1 and flag("SE_HB_COUNTED", "0") != "1"):   # 纯心跳不占上限(10/21 晚)
            self.restrategize("; ".join(why), counted=False)
            return
        if self.n_re >= self.cap:
            if not getattr(self, "_capped", False):
                self._capped = True
                self.ev(kind="到上限", why=why)
                self.wx(f"【{self.skill} 策略执行器】今日重定已到上限 {self.cap} 次, 之后只按最后一版策略机械执行")
            return
        self.restrategize("; ".join(why))

    def px(self, c):
        return (self.feed.q.get(c) or {}).get("p") or prev_close(c, self.D) or 0

    def nav(self):
        return round(self.state["cash"] + sum(p["qty"] * self.px(c) for c, p in self.state["positions"].items()), 2)

    def real_book(self):
        """同链真实账本(只读; 撮合写盘时可能读到半截 → 沿用上一次读到的)"""
        b = jl(ROOT / "scripts" / "dfcf" / "paper" / "books" / f"{self.book_name}.json")
        if b:
            self._real = b
        return getattr(self, "_real", None) or {}

    def real_codes(self):
        return {c for c, p in (self.real_book().get("positions") or {}).items() if int(p.get("qty") or 0) > 0}

    def real_nav(self):
        """对照线: 旧口径 = 同链旧 paper 账本; 新口径(接续 / genesis) = "不操作"基准 = 起点持仓按现价 + 起点现金"""
        st = self.state.get("start") or {}
        if not str(st.get("from", "")).startswith("A-"):
            return round(float(st.get("cash") or 0) + sum(int(p["qty"]) * self.px(c) for c, p in (st.get("positions") or {}).items()), 2)
        b = self.real_book()
        return round(float(b.get("cash") or 0) + sum(int(p.get("qty") or 0) * self.px(c) for c, p in (b.get("positions") or {}).items()), 2)

    def start_nav(self):
        st = self.state["start"]
        return (st.get("cash") or 0) + sum(p["qty"] * (prev_close(c, self.D) or 0) for c, p in st["positions"].items())

    def curve(self, hm, force=False):
        """每分钟一行: 时刻, 影子 nav, 真实链账本 nav, 两者相对开盘起点 %(同一份盘口价)"""
        if not force and self.last_curve == hm:
            return
        self.last_curve = hm
        f = self.dir / "curve.csv"
        s0, nv, rv = self.start_nav(), self.nav(), self.real_nav()
        new = not f.exists()
        with f.open("a", encoding="utf-8") as fh:
            if new:
                fh.write("t,shadow_nav,real_nav,shadow_pct,real_pct,start_nav\n")
            fh.write(f"{now():%H:%M:%S},{nv},{rv},{(nv / s0 - 1) * 100 if s0 else 0:.3f},{(rv / s0 - 1) * 100 if s0 else 0:.3f},{s0:.2f}\n")

    def heartbeat(self, note=""):
        try:
            (self.dir / "heartbeat.txt").write_text(f"{now():%H:%M:%S} pid={os.getpid()} ver={self.ver} n_re={self.n_re}/{self.cap} n_all={self.n_all} "
                                                    f"pending={self.pending} queued={bool(self.queued)} quotes={len(self.feed.q)} {note}\n", encoding="utf-8")
        except OSError:
            pass

    def close(self):
        nv = self.nav()
        with (self.dir / "nav.csv").open("a", encoding="utf-8") as f:
            f.write(f"{self.D},{self.state['cash']},{nv},{len(self.state['trades'])},{self.n_all}\n")   # 彩排 B7: 记全部重定次数(原 n_re = 只自由触发)
        real, start = self.real_nav(), self.start_nav()
        try:
            self.curve(now().strftime("%H:%M"), force=True)
        except Exception as e:   # noqa: BLE001
            self.ev(kind="曲线异常", err=repr(e)[:200])
        cost = sum((jl(f, {}) or {}).get("cost_usd") or 0 for f in (self.dir / "strategies").glob("*.json"))
        sp_all, sp_sh = self._spend()
        cost = max(cost, sp_all - sp_sh)   # 01→06 模式按 claude_cost.csv 记(含失败的调用); 影子链另报
        msg = (f"【{self.skill} 策略执行器 收盘】影子账 {nv:.0f}(开盘 {start:.0f}, {(nv / start - 1) * 100:+.2f}%) vs {"旧 paper 账本" if str(self.state["start"].get("from", "")).startswith("A-") else "起点持仓不动"} {real:.0f}({(real / start - 1) * 100:+.2f}%)\n"
               f"成交 {len(self.state['trades'])} 笔, 重定 {self.n_all} 次(其中自由触发 {self.n_re}), 模型花费 ${cost:.2f}(影子链另 ${sp_sh:.2f}); 明细 results/_live/{self.D}/se_{self.key}/")
        (self.dir / "summary.md").write_text(msg + "\n", encoding="utf-8")
        pic = None
        try:   # 三条链各自收盘都画一次, 最后收盘的那次 = 全量图(未收盘的链图上标"未收盘"); 彩排 B6: 临时目录(自测 / 回放)不画真实目录的图
            if self.base_given:
                raise RuntimeError("临时目录, 不画 results/_live 的曲线图")
            r = subprocess.run([str(PY), "-X", "utf8", str(HERE / "se_curve.py"), "--date", self.D], cwd=ROOT, creationflags=NOWIN,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            pic = (r.stdout or "").strip().splitlines()[-1] if r.returncode == 0 and r.stdout.strip() else None
            if not pic:
                self.ev(kind="曲线图失败", err=(r.stderr or "")[-200:])
        except Exception as e:   # noqa: BLE001
            self.ev(kind="曲线图失败", err=repr(e)[:200])
        if pic:
            msg += f"\n影子 vs 真实曲线图: {pic}"
        self.wx(msg)

    @staticmethod
    def _auc_test_skills():
        return {x.strip() for x in flag("SE_AUC_TEST_SKILLS", "").split(",") if x.strip()}

    def run_auc_test(self, cont=False):
        """10/21 晚用户令(土豆 = 专测竞价): SE_AUC_TEST_AT(09:24:01) 用同一份 01 同时跑 low(正式) + high(影子) 两条完整 01→06, 记两份结果和耗时;
        low 若 09:25:03 前落地就挂竞价单参加撮合(实测 low 约 2 分钟, 大概率赶不上); 两条都跑完就收盘结束当天, 不进连续竞价
        cont=True(10/22 08:1x 用户令"土豆进程跑到 10:00 后才算结束"): 竞价撮合完就返回, 由 run() 接着进连续竞价到 SE_AUC_TEST_END; 在跑的两条链后台照常落地"""
        at = flag("SE_AUC_TEST_AT", "09:24:01") or "09:24:01"
        while now().strftime("%H:%M:%S") < at:
            self.heartbeat("等竞价测试")
            time.sleep(1)
        if not any(e.get("tag") == "auctest" for e in self._events()) and now().strftime("%H:%M:%S") < "09:25:00":   # 续跑时已过竞价段就不补测
            self.restrategize(f"竞价测试({at} low 正式 + 同快照 high 影子)", counted=False, effort="low", tag="auctest")
        auc_done = False
        t_end = time.time() + 20 * 60
        while time.time() < t_end:
            hms = now().strftime("%H:%M:%S")
            if not auc_done and hms >= "09:25:03":
                auc_done = True
                if hms < "09:30:00" and not any(e.get("kind") == "竞价撮合" for e in self._events()):   # 续跑防重复撮合
                    try:
                        self.feed.refresh(sorted(set(self.codes()) | self.real_codes()))
                        fills = self.tick(hms[:5], auction=True)
                        self.ev(kind="竞价撮合", fills=len(fills), submitted=bool((self.strategy or {}).get("auc_submitted")))
                        if cont and fills:
                            self.restrategize("竞价成交 " + ",".join(f"{t['side']}{t['code']}" for t in fills), counted=False)
                    except Exception as e:   # noqa: BLE001
                        self.ev(kind="竞价撮合异常", err=repr(e)[:300])
            if cont and auc_done:
                self.ev(kind="竞价测试结束", note=f"进连续竞价, 跑到 {flag('SE_AUC_TEST_END', '10:00')} 收盘")
                return
            if auc_done and not self.pending and not getattr(self, "_shadow_busy", False):
                break
            self.heartbeat("竞价测试中")
            time.sleep(3)
        self.ev(kind="竞价测试结束", note="两条链都已落地(或 20 分钟到), 当天不进连续竞价")
        self.close()
        self.heartbeat("已收盘(竞价测试)")

    def _log_events(self, hm):
        """10/21 晚(★10 实验 5): 指数事件(θ, 系数 0.35, 检查点 = 本链上次重定或上次记的事件)和 国证2000 − 上证 剪刀差事件, 每分钟算一次, 只记日志不叫链"""
        sys.path.insert(0, str(ROOT / "scripts" / "market"))
        import index_event as IE
        import spread_event as SPE
        cp_t = max([t for t in (self.last_re, getattr(self, "_ie_cp", None)) if t] or [now()])
        bars = IE.bars_today(self.D, "SH", before=hm)
        n_ie = getattr(self, "_ie_n", 0)
        hit, mv, th, note = IE.check(self.D, cp_t.strftime("%H%M"), hm.replace(":", ""), bars, key="SH", n_today=n_ie)
        if hit:
            self._ie_n, self._ie_cp = n_ie + 1, now()
            self.ev(kind="指数事件(只记)", n=n_ie + 1, move=mv, theta=th, note=note[:160])
        rows = {}
        for l in (MKT / self.D / "index_snap.jsonl").read_text(encoding="utf-8").splitlines() if (MKT / self.D / "index_snap.jsonl").exists() else []:
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if r.get("s") in ("sh000001", "sz399303") and r.get("p") and r.get("pc") and r.get("t", "") >= "09:30:00":
                rows.setdefault(r["s"], {})[r["t"][:5].replace(":", "")] = (r["p"] / r["pc"] - 1) * 100
        a, b = rows.get("sh000001") or {}, rows.get("sz399303") or {}
        seq, la, lb = [], None, None
        for m_ in SPE.MINS:
            if m_ > hm.replace(":", ""):
                break
            la, lb = a.get(m_, la), b.get(m_, lb)
            seq.append(None if la is None or lb is None else lb - la)
        st_ = getattr(self, "_spe_state", {})
        e = SPE.check(seq, st_, H=SPE.H_DEF, M=SPE.M_DEF)
        self._spe_state = st_
        if e:
            self.ev(kind="剪刀差事件(只记)", at=SPE.MINS[e[0]], dir="转正(中小票转强)" if e[1] > 0 else "转负(权重转强)", spread=round(seq[e[0]], 3))

    def run(self, t_strategy="09:15:00", t_open="09:30", t_end="14:57"):
        if self.variant == "nolimit":
            t_end = flag("SE_NOLIMIT_END", "11:30") or "11:30"
        auc_test = self.skill in self._auc_test_skills() and not self.variant
        if auc_test:
            t_end = flag("SE_AUC_TEST_END", "")   # 空 = 旧行为(竞价测完就收盘)
            if not t_end:
                return self.run_auc_test()
            self.run_auc_test(cont=True)
        while now().strftime("%H:%M:%S") < t_strategy:
            time.sleep(10)
        if auc_test:   # 竞价测试链: 首版就是 09:24:01 那两条, 不另叫; 续跑补叫照做
            if self.interrupted and not self.pending:
                self.restrategize("(续跑补叫) " + self.interrupted, counted=False)
        elif not self.strategy:
            self.restrategize("开盘前首版策略", counted=False)
        elif self.interrupted:   # 续跑: 上一进程被重启时有一轮重定没算完 → 补叫(不占上限)
            self.restrategize("(续跑补叫) " + self.interrupted, counted=False)
        auc_done = auc_test   # 竞价测试链已在 run_auc_test 里撮合过
        auc_at = flag("SE_AUC_AT", "")   # ★12: 09:21:00 low 竞价正式版; 空 = 不另跑
        auc_run = True if auc_test else (bool(any(e.get("tag") == "auction" for e in self._events())) if auc_at else True)
        while now().strftime("%H:%M") < t_open:   # 09:15~09:25 只读竞价不成交(链自己读竞价盘口); 09:25 竞价单一次撮合; 09:25~09:30 不成交
            hms = now().strftime("%H:%M:%S")
            if not auc_run and hms >= auc_at and hms < "09:24:30":
                auc_run = True
                self.restrategize("竞价段正式版(看 09:20 后可信竞价)", counted=False, effort=flag("SE_AUC_EFFORT", "low") or "low", tag="auction")
            if "09:24:57" <= hms < "09:25:03" and self.strategy and not self.strategy.get("auc_submitted"):
                with self.lock:   # 正式版没赶上 / 失败: 按草稿挂竞价单
                    self.strategy["auc_submitted"] = hms
                self.ev(kind="竞价单按草稿挂出", at=hms, ver=self.ver)
            rt = getattr(self, "retry", None)   # 盘前也处理失败重试(原来只在 09:30 后的 need_re 里)
            if rt and time.time() >= rt[0] and not self.pending:
                self.retry = None
                self.restrategize("(失败重试) " + re.sub(r"^(\(失败重试\) |\(排队补叫\) )+", "", str(rt[1]))[:120], counted=False)
            if not auc_done and hms >= "09:25:03":
                try:
                    self.feed.refresh(sorted(set(self.codes()) | self.real_codes()))
                    fills = self.tick(hms[:5], auction=True)
                    auc_done = True
                    self.ev(kind="竞价撮合", fills=len(fills))
                    if fills:
                        self.restrategize("竞价成交 " + ",".join(f"{t['side']}{t['code']}" for t in fills), counted=False)
                except Exception as e:   # noqa: BLE001
                    self.ev(kind="竞价撮合异常", err=repr(e)[:300])
            self.heartbeat("竞价" if hms < "09:25:00" else "等开盘")
            time.sleep(3)
        while True:
            hm = now().strftime("%H:%M")
            if now().strftime("%H:%M:%S") >= t_end + ":00":   # 10/21 晚回放: 原 hm > "14:57" 要到 14:58 才停
                break
            tail_at = flag("SE_TAIL_AT", "")   # 10/21 晚(尾盘竞价): 固定时刻必跑一版(high), 15:00 前出结果进尾盘竞价
            if tail_at and not self.variant:   # 10/22 09:4x 用户令错峰: 按 SE_FLEET_SKILLS 顺序每条晚 8 秒(14:51:00 / :08 / :16), 不同一秒挤 API
                try:
                    _i = [x.strip() for x in flag("SE_FLEET_SKILLS", "").split(",") if x.strip()].index(self.skill)
                    tail_at = (dt.datetime.strptime(tail_at, "%H:%M:%S") + dt.timedelta(seconds=8 * _i)).strftime("%H:%M:%S")
                except ValueError:
                    pass
            if tail_at and now().strftime("%H:%M:%S") >= tail_at and not getattr(self, "_tail_run", False):
                self._tail_run = True
                if not any(e.get("tag") == "tail" for e in self._events()):
                    self.restrategize("尾盘竞价版(15:00 前出, 规则进 14:57~15:00 尾盘竞价)", counted=False, tag="tail")
            if "11:30" < hm < "13:00":
                self.heartbeat("午休")
                time.sleep(20)
                continue
            try:
                self.feed.refresh(sorted(set(self.codes()) | self.real_codes()))
                fills = self.tick(hm)
                self.need_re(hm, fills)
            except Exception as e:   # noqa: BLE001
                self.ev(kind="执行器异常", err=repr(e)[:300])
            try:
                self.curve(hm)
            except Exception as e:   # noqa: BLE001
                if getattr(self, "_curve_err", None) != hm:
                    self._curve_err = hm
                    self.ev(kind="曲线异常", err=repr(e)[:200])
            if flag("SE_LOG_EVENTS", "0") == "1" and getattr(self, "_ev_min", None) != hm:
                self._ev_min = hm
                try:
                    self._log_events(hm)
                except Exception as e:   # noqa: BLE001
                    if not getattr(self, "_ev_err", False):
                        self._ev_err = True
                        self.ev(kind="只记事件异常", err=repr(e)[:200])
            self.heartbeat()
            time.sleep(3)
        if t_end < "14:00":   # 对照变体只跑到上午(11:30) / 竞价测试链跑到 10:00: 不进尾盘竞价, 等在跑的那轮落地(最多 30 分钟)就收盘(不强平)
            self.queued, self.retry = None, None   # 收盘不再补叫: 在跑那轮落地后不接新链
            for _ in range(180):
                if not self.pending:
                    break
                time.sleep(10)
            self.close()
            self.heartbeat("已收盘(竞价测试)" if auc_test else "已收盘(变体)")
            return
        # 10/21 晚用户令: 14:57~15:00 尾盘集合竞价——不再连续撮合; 14:57 前发起、这段时间落地的版本照装(它的规则直接进尾盘竞价); 15:00:03 一次撮合
        close_done = False
        while now().strftime("%H:%M:%S") < "15:00:40":
            hms = now().strftime("%H:%M:%S")
            if not close_done and hms >= "15:00:03":
                close_done = True
                try:
                    self.feed.refresh(sorted(set(self.codes()) | self.real_codes()))
                    fills = self.tick(hms[:5], auction="close")
                    self.ev(kind="尾盘竞价撮合", fills=len(fills))
                except Exception as e:   # noqa: BLE001
                    self.ev(kind="尾盘竞价撮合异常", err=repr(e)[:300])
                break
            self.heartbeat("尾盘竞价")
            time.sleep(3)
        if self.pending:
            self.ev(kind="收盘时链还没跑完", note="15:00 后落地的版本不再撮合")
        self.close()
        self.heartbeat("已收盘")


def depth_fill(levels, limit, n, side, code):
    """按五档吃单: levels = [[价, 量], ...](买单传卖盘 k, 卖单传买盘 b); 只吃限价以内的档 → (加权价, 成交量) 或 None(没有深度数据)"""
    lv = [(float(a), int(b)) for a, b in (levels or []) if a and b and (float(a) <= limit if side == "BUY" else float(a) >= limit)]
    if not lv:
        return None
    got, amt = 0, 0.0
    for a, b in lv:
        take = min(b, n - got)
        got += take
        amt += take * a
        if got >= n:
            break
    got = AR.round_qty(code, got) if got < n else n
    return (round(amt / max(got, 1), 3), got) if got > 0 else None


def take_lock(skill, d=None):
    """同一 skill 只许一个 se_exec(10/21 防双开): 锁文件存本进程 pid; 锁里的 pid 还活着且确实是 se_exec --skill 同链 → 拒绝启动"""
    import psutil
    f = Path(d or ROOT / "scripts" / "temp") / f"se_{skill}.lock"
    me = os.getpid()
    for _ in range(3):
        try:
            fd = os.open(str(f), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(me).encode())
            os.close(fd)
            return f
        except FileExistsError:
            try:
                pid = int(f.read_text().strip() or 0)
                pr = psutil.Process(pid)
                cmd = " ".join(pr.cmdline())
                sk_, _, var_ = skill.partition("@")
                same = sk_ in cmd and ((f"--variant {var_}" in cmd) if var_ else "--variant" not in cmd)
                if pid != me and "se_exec.py" in cmd and same and "--selftest" not in cmd:
                    sys.exit(f"se_exec --skill {skill} 已在跑(pid {pid}), 本进程退出")
            except (ValueError, OSError, psutil.Error):
                pass
            f.unlink(missing_ok=True)   # 残留锁(持有者已死) → 回收重抢
    sys.exit(f"抢不到锁 {f}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--first", default="09:15:00", help="首版策略时刻 HH:MM:SS(se_fleet 错峰用)")
    ap.add_argument("--selftest", action="store_true", help="用今天目录外的临时目录跑一遍桩: 定策略→命中规则→成交→记账, 断言结果")
    ap.add_argument("--variant", default="", help="对照变体(nolimit = effort 全 high 不限时长, 跑到 11:30)")
    a = ap.parse_args()
    if a.selftest:
        return selftest(a.skill)
    lk = take_lock(a.skill + (f"@{a.variant}" if a.variant else ""))
    try:
        SE(a.skill, a.date, a.dry, variant=a.variant or None).run(t_strategy=a.first)
    finally:
        try:
            if lk.read_text().strip() == str(os.getpid()):
                lk.unlink()
        except OSError:
            pass


def selftest(skill):
    """不调真模型(dry 桩)、不推微信(wx 换成 print)、不写今天的真目录(临时目录); 只读真实账本"""
    import tempfile
    import se_curve
    D = dt.date.today().isoformat()
    tmp = Path(tempfile.mkdtemp())
    base = tmp / "live" / f"se_{skill}"
    global now
    os.environ["SE_FULL_PAUSE"] = "0"   # 自测账户可能是满仓旧账本, 不让"满仓停触发"挡住自测
    _t0, _real = dt.datetime.now(), now
    now = lambda: dt.datetime.combine(_t0.date(), dt.time(10, 0, 0)) + (dt.datetime.now() - _t0)   # noqa: E731  10/21 晚: 自测钟固定从 10:00 走(晚上跑自测会撞 14:48 截止 / 午休)
    SE.wx = lambda self, m, alert=False: print("WX>", m.replace("\n", " | ")[:300])   # 类级桩: 续跑新建的实例也不推
    se = SE(skill, D, True, base=base, cap=9)
    se.facts_build = False   # 自测不现做事实包(不打行情), 只复制今天最近一份
    assert se.ver == 0 and se.n_all == 0 and se.strategy is None, "空目录不该有续跑状态"

    def settle(x):
        for _ in range(300):
            if not x.pending:
                return
            time.sleep(0.2)
        raise AssertionError("重定 60 秒没落地")
    if not any(prev_close(x, D) for x in se.state["positions"]):   # 10/22: 空仓起步, 或现有持仓都没有本地日线(自测账户读到旧账本 002368 之类)时; 起 SE_GENESIS = 10 万空仓起步: 自测只在临时目录里塞一只底仓(沪深300ETF), 不碰真目录
        _pc = prev_close("510300", D)
        se.state["positions"]["510300"] = {"qty": 1000, "cost": _pc, "sellable": 1000}
        se.state["cash"] -= 1000 * _pc
        se.state["start"].setdefault("positions", {})["510300"] = dict(se.state["positions"]["510300"])   # 起点也要有(断言"成交不改起点"用)
    c = next(x for x in se.state["positions"] if prev_close(x, D))
    pc = prev_close(c, D)
    q0 = se.state["positions"][c]["sellable"]
    se.restrategize("自测首版", counted=False)
    settle(se)
    assert se.strategy and se.ver == 1, "首版策略没落地"
    ff = base / "facts.txt"
    assert ff.exists() and ff.stat().st_size > 1000, f"事实包没生成到本目录: {ff}"
    assert se.facts_file() == ff, "prompt 没优先读本目录事实包"
    sp = jl(next((base / "strategies").glob("01_*.json")), {})
    assert str(ff.relative_to(ROOT) if ff.is_relative_to(ROOT) else ff).replace("\\", "/") in sp["prompt"] and "## 开盘实况" in sp["prompt"], "prompt 没带事实包路径 / 开盘实况"
    if (jl(MKT / D / "open_live.json", {}) or {}).get("judgments"):
        assert "最新判定" in sp["prompt"], "有 open_live.json 但 prompt 没带开盘实况判定"
    se.strategy = {"view": "t", "codes": [{"code": c, "name": "纳指ETF", "band": [pc * 0.9, pc * 1.1], "rules": [{"id": "s1", "side": "SELL", "op": ">=", "px": round(pc * 1.01, 3), "qty": 100, "why": "t"},
                                                                                         {"id": "b1", "side": "BUY", "op": "<=", "px": round(pc * 0.99, 3), "qty": 100, "why": "t"}]}]}
    cash0 = se.state["cash"]
    se.feed.q[c] = {"p": round(pc * 1.02, 3), "b1": round(pc * 1.019, 3), "a1": round(pc * 1.021, 3)}
    f = se.tick("10:00")
    assert len(f) == 1 and f[0]["side"] == "SELL" and f[0]["px"] == round(pc * 1.019, 3), f"卖规则应按买一成交: {f}"
    assert se.state["positions"][c]["sellable"] == q0 - 100 and se.state["cash"] > cash0, "卖出后账不对"
    assert se.tick("10:00") == [], "同一规则只该成交一次"
    se.feed.q[c] = {"p": round(pc * 0.98, 3), "b1": round(pc * 0.979, 3), "a1": round(pc * 0.981, 3)}
    f = se.tick("10:01")
    assert len(f) == 1 and f[0]["side"] == "BUY" and f[0]["px"] == round(pc * 0.981, 3), f"买规则应按卖一成交: {f}"
    assert se.state["start"]["positions"][c]["qty"] == q0, "成交改坏了起点持仓(起点和当前持仓共用了一个 dict)"
    se.state["start"]["positions"].pop(c)   # 模拟 10/21 首批进程被改坏的起点 → 新实例应倒推修正
    se._save()
    se_fix = SE(skill, D, True, base=base, cap=9)
    assert se_fix.state["start"]["positions"][c]["qty"] == q0, "起点没按成交倒推修正"
    assert abs(se_fix.nav() / se_fix.start_nav() - 1) < 0.2, f"起点 nav 不合理: {se_fix.start_nav()}"
    se.state = se_fix.state
    s2, dropped = se.check({"view": "x", "codes": [{"code": c, "band": [1, 2], "rules": [{"id": "x", "side": "BUY", "op": ">=", "px": pc, "qty": 100},
                                                                                     {"id": "y", "side": "SELL", "op": ">=", "px": pc * 5, "qty": 100},
                                                                                     {"id": "z", "side": "BUY", "op": "<=", "px": pc, "qty": 150}]},
                                                   {"code": "000001", "band": [1, 2], "rules": []}]})
    assert len(s2["codes"]) == 1 and not s2["codes"][0]["rules"] and len(dropped) == 4, f"校验应剔 4 处: {dropped}"
    # 曲线 + 心跳
    se.curve("10:01")
    se.curve("10:01")
    se.curve("10:02")
    rows = (base / "curve.csv").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 3 and rows[0].startswith("t,shadow_nav,real_nav") and float(rows[1].split(",")[2]) > 0 and abs(float(rows[1].split(",")[3])) < 20, f"curve.csv 应 表头+2 行(同一分钟只写一次), 真实 nav>0: {rows}"
    se.heartbeat()
    assert (base / "heartbeat.txt").read_text(encoding="utf-8").startswith(now().strftime("%H:%M")), "heartbeat.txt 没写"
    # 自由触发 1 次(占上限) + 成交排队补叫
    se.restrategize("自测自由触发")
    se.restrategize("自测成交", counted=False)   # 上一轮还在算 → 排队
    assert se.queued == "自测成交", "成交后必判在算时应排队, 不该丢"
    settle(se)
    time.sleep(0.5)
    settle(se)
    assert se.ver == 3 and se.n_re == 1 and se.n_all == 3 and se.queued is None, f"排队补叫后应 v3/自由 1/共 3: v{se.ver} {se.n_re} {se.n_all}"
    se.fired.add("3:x:y")
    sp = sorted((base / "strategies").glob("03_*.json"))[-1]
    d = jl(sp, {})
    d["fired"] = sorted(se.fired)
    sp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    se.ev(kind="到上限", why=["t"])
    # 断点续跑: 新实例从目录恢复
    se2 = SE(skill, D, True, base=base, cap=9)
    assert se2.ver == 3 and se2.n_re == 1 and se2.n_all == 3, f"续跑计数没恢复: v{se2.ver} n_re={se2.n_re} n_all={se2.n_all}"
    assert se2.last_re and se2.last_re.strftime("%H:%M:%S") == se.last_re.strftime("%H:%M:%S"), f"last_re 没恢复(冷却会失效): {se2.last_re} vs {se.last_re}"
    assert se2.fired == se.fired and se2._capped and se2.interrupted is None, f"fired/到上限/打断 恢复不对: {se2.fired} {se2._capped} {se2.interrupted}"
    assert se2.state["cash"] == se.state["cash"], "影子账没续上"
    se2.ev(kind="重定", why="被打断的一轮", n=1)   # 模拟: 叫了模型还没回来进程就被重启
    se3 = SE(skill, D, True, base=base, cap=9)
    assert se3.interrupted == "被打断的一轮" and se3.ver == 3, f"被打断的重定应识别出来补叫: {se3.interrupted}"
    # pid 锁: 残留锁(死 pid)可回收; 活的同链 se_exec 会拒绝(这里只验回收 + 写入本 pid)
    (tmp / f"se_{skill}.lock").write_text("999999")
    lk = take_lock(skill, tmp)
    assert lk.read_text().strip() == str(os.getpid()), "残留锁没回收"
    # 曲线图(临时目录)
    (base / "summary.md").write_text("x", encoding="utf-8")
    pic = se_curve.draw(D, tmp / "live")
    assert pic and pic.exists() and pic.stat().st_size > 1000, f"曲线图没画出来: {pic}"
    print("SELFTEST PASS", tmp, "| 图:", pic.name)


if __name__ == "__main__":
    main()
