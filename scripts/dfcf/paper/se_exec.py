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
"""
import argparse
import datetime as dt
import json
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
import a_rules as AR   # noqa: E402
import shadow_exec as SX   # noqa: E402

PY = ROOT / "scripts" / "venv" / "Scripts" / "python.exe"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MKT = ROOT / "downloads" / "market"
HB_MIN = 60
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
            with self.f.open("r", encoding="utf-8") as fh:
                fh.seek(self.pos)
                for l in fh:
                    try:
                        r = json.loads(l)
                    except ValueError:
                        continue
                    if r.get("p"):
                        self.q[str(r["s"])[2:]] = {"p": float(r["p"]), "t": r.get("t"), "b1": (r.get("b") or [[0]])[0][0], "a1": (r.get("k") or [[0]])[0][0],
                                                   "b": r.get("b"), "k": r.get("k")}
                self.pos = fh.tell()
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
    def __init__(self, skill, D, dry):
        import mentors
        self.skill, self.D, self.dry = skill, D, dry
        self.dir = ROOT / "results" / "_live" / D / f"se_{skill}"
        (self.dir / "strategies").mkdir(parents=True, exist_ok=True)
        self.book_name = mentors.book(skill)
        self.state = jl(self.dir / "state.json") or self._init_state()
        self.strategy, self.ver, self.fired = None, 0, set()
        self.last_re, self.n_re, self.pending = None, 0, False
        self.cap = SX.real_cap(skill, D)[0]
        self.feed = Feed(D)
        self.lock = threading.Lock()
        self.flips_seen = set()
        old = sorted((self.dir / "strategies").glob("*.json"))
        if old:   # 断点续跑: 接上最后一版策略
            s = jl(old[-1])
            self.strategy, self.ver = s.get("strategy"), len(old)
            self.fired = set(s.get("fired") or [])

    def _init_state(self):
        b = jl(ROOT / "scripts" / "dfcf" / "paper" / "books" / f"{self.book_name}.json", {}) or {}
        pos = {c: {"qty": int(p["qty"]), "cost": p.get("cost"), "sellable": int(p["qty"])} for c, p in (b.get("positions") or {}).items() if int(p.get("qty") or 0) > 0}
        st = {"cash": round(float(b.get("cash") or 0), 2), "positions": pos, "trades": [], "start": {"cash": b.get("cash"), "positions": pos, "from": self.book_name, "at": now().isoformat(timespec="seconds")}}
        self._save(st)
        return st

    def _save(self, st=None):
        (self.dir / "state.json").write_text(json.dumps(st or self.state, ensure_ascii=False, indent=1), encoding="utf-8")

    def ev(self, **k):
        with (self.dir / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": now().strftime("%H:%M:%S"), **k}, ensure_ascii=False) + "\n")

    def wx(self, msg):
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
        f = ROOT / "results" / f"{self.skill}_chain" / f"live-{self.D.replace('-', '')}" / "facts.txt"
        try:
            return set(re.findall(r"(?<!\d)([036]\d{5}|15\d{4}|5[16]\d{4})(?!\d)", f.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            return set()

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
        rd = f"results/{self.skill}_chain/live-{self.D.replace('-', '')}"
        return f"""你是 {self.skill} skill(同花顺投资账本导师的模拟盘决策者)。现在是 {self.D} {now():%H:%M}, 要你给"机械执行器"写一份盘中策略。
执行器每 3 秒读盘口, 只按你写的规则机械成交; 出了你写的区间 / 有成交 / 开盘实况翻转 / 满 60 分钟才会再叫你。所以策略要能独立跑一段时间, 覆盖"涨了怎么办 / 跌了怎么办"两头。

本次叫你的原因: {why}

先读(必读): skills/{self.skill}-skill/persona/rules_index.md, skills/{self.skill}-skill/persona/profile.md; 需要细节再读 rules.md / cases.md、{rd}/facts.txt。
风格跟导师走(拟人), 教训可以让你偏离导师, 但要写理由。

## 影子账当前状态(执行器唯一账本; sellable=今天可卖股数)
{json.dumps(st, ensure_ascii=False)}
最近成交: {json.dumps(recent, ensure_ascii=False)}

## 标的(下表 = 持仓 + 本链候选, 现价/买一/卖一来自 3 秒盘口; 也可以写 {rd}/facts.txt 里出现的其他代码(如导师本人近期买卖的票), 执行器用新浪补价, 其余代码会被剔除)
| 代码 | 现价 | 买一 | 卖一 | 昨收 | 涨停 | 跌停 | 近30日日振幅中位 |
|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

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

    def restrategize(self, why):
        if self.pending:
            self.ev(kind="重定被拦", why=why, reason="上一轮还在算")
            return
        self.pending = True
        self.n_re += 1
        self.last_re = now()
        self.ev(kind="重定", why=why, n=self.n_re)

        def work():
            try:
                p = self.prompt(why)
                if self.dry:
                    s, cost = self._stub(), 0.0
                else:
                    from claude_call import call
                    r = call(p, tag=f"se-{self.skill}", allowed_tools=["Read", "Grep", "Glob"], timeout=900, json_schema=SCHEMA)
                    s, cost = (r.parsed if r.ok else None), r.cost_usd
                    if not r.ok:
                        self.ev(kind="重定失败", errors=r.errors[:3])
                        self.wx(f"【{self.skill} 策略执行器】重定失败, 沿用上一版: {'; '.join(r.errors[:2])[:200]}")
                        return
                s, dropped = self.check(s)
                with self.lock:
                    self.ver += 1
                    self.strategy, self.fired = s, set()
                    (self.dir / "strategies" / f"{self.ver:02d}_{now():%H%M}.json").write_text(
                        json.dumps({"why": why, "strategy": s, "dropped": dropped, "cost_usd": cost, "fired": [], "prompt": p}, ensure_ascii=False, indent=1), encoding="utf-8")
                L = [f"【{self.skill} 策略执行器 v{self.ver} {now():%H:%M}】因: {why}", f"看法: {str(s.get('view'))[:200]}"]
                for x in s.get("codes") or []:
                    L.append(f"· {x.get('name') or ''}{x['code']} 区间 {x['band'][0]}~{x['band'][1]}")
                    for r_ in x.get("rules") or []:
                        L.append(f"   {r_['side']} 价{r_['op']}{r_['px']} ×{r_['qty']} | {str(r_.get('why', ''))[:70]}")
                if dropped:
                    L.append("执行器剔除: " + "; ".join(dropped)[:200])
                L.append(f"管到 {s.get('valid_until')} | 本次 ${cost:.2f} | 今日第 {self.n_re}/{self.cap} 次")
                self.wx("\n".join(L))
            except Exception as e:   # noqa: BLE001
                self.ev(kind="重定异常", err=repr(e)[:300])
            finally:
                self.pending = False
        threading.Thread(target=work, daemon=True).start()

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

    def tick(self, hm):
        fills = []
        with self.lock:
            s = self.strategy
            if not s:
                return fills
            for x in s.get("codes") or []:
                c, q = x["code"], self.feed.q.get(x["code"])
                if not q:
                    continue
                p = q["p"]
                for r in x.get("rules") or []:
                    key = f"{self.ver}:{c}:{r['id']}"
                    if key in self.fired:
                        continue
                    hit = p <= r["px"] if r["side"] == "BUY" else p >= r["px"]
                    if not hit:
                        continue
                    pos = self.state["positions"].setdefault(c, {"qty": 0, "cost": None, "sellable": 0})
                    if r["side"] == "BUY":
                        px = min(r["px"], q.get("a1") or p) or p
                        n = min(r["qty"], AR.round_qty(c, (self.state["cash"] - 5) / px))
                    else:
                        px = max(r["px"], q.get("b1") or p)
                        n = min(r["qty"], pos["sellable"])
                    self.fired.add(key)
                    if n <= 0:
                        self.ev(kind="规则命中但没钱/没可卖", rule=key, p=p)
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
                         "rule": key, "why": r.get("why"), "tape": {k: q.get(k) for k in ("p", "t", "b", "k")}}
                    self.state["trades"].append({k: v for k, v in t.items() if k != "tape"})
                    with (self.dir / "actions.jsonl").open("a", encoding="utf-8") as f:
                        f.write(json.dumps(t, ensure_ascii=False) + "\n")
                    fills.append(t)
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

    def need_re(self, hm, fills):
        why, must = [], False
        if fills:
            why.append("本链成交 " + ",".join(f"{t['side']}{t['code']}" for t in fills)); must = True
        s = self.strategy or {}
        for x in s.get("codes") or []:
            q = self.feed.q.get(x["code"])
            if q and not (x["band"][0] <= q["p"] <= x["band"][1]):
                why.append(f"{x['code']} {q['p']} 出区间 {x['band'][0]}~{x['band'][1]}")
        fm = SX.flips(self.D)
        for k, v in fm.items():
            if k <= hm and k not in self.flips_seen:
                self.flips_seen.add(k)
                if k >= (self.last_re.strftime("%H:%M") if self.last_re else "00:00"):
                    why.append(v)
        if self.last_re:
            gap = (now() - self.last_re).total_seconds() / 60 - (90 if self.last_re.strftime("%H:%M") <= "11:30" < hm else 0)
            if gap >= HB_MIN:
                why.append(f"心跳 {HB_MIN} 分钟")
        if not why:
            return
        cool = 3 if hm <= "10:30" else 5
        if not must and self.last_re and (now() - self.last_re).total_seconds() < cool * 60:
            return   # 冷却中(不记日志, 防每 3 秒灌水; 出区间会在冷却后再判)
        if self.n_re >= self.cap:
            if not getattr(self, "_capped", False):
                self._capped = True
                self.ev(kind="到上限", why=why)
                self.wx(f"【{self.skill} 策略执行器】今日重定已到上限 {self.cap} 次, 之后只按最后一版策略机械执行")
            return
        self.restrategize("; ".join(why))

    def nav(self):
        v = self.state["cash"]
        for c, p in self.state["positions"].items():
            q = self.feed.q.get(c) or {}
            v += p["qty"] * (q.get("p") or prev_close(c, self.D) or 0)
        return round(v, 2)

    def close(self):
        nv = self.nav()
        with (self.dir / "nav.csv").open("a", encoding="utf-8") as f:
            f.write(f"{self.D},{self.state['cash']},{nv},{len(self.state['trades'])},{self.n_re}\n")
        b = jl(ROOT / "scripts" / "dfcf" / "paper" / "books" / f"{self.book_name}.json", {}) or {}
        real = (b.get("cash") or 0) + sum(int(p.get("qty") or 0) * ((self.feed.q.get(c) or {}).get("p") or prev_close(c, self.D) or 0) for c, p in (b.get("positions") or {}).items())
        st = self.state["start"]
        start = (st.get("cash") or 0) + sum(p["qty"] * (prev_close(c, self.D) or 0) for c, p in st["positions"].items())
        cost = sum((jl(f, {}) or {}).get("cost_usd") or 0 for f in (self.dir / "strategies").glob("*.json"))
        msg = (f"【{self.skill} 策略执行器 收盘】影子账 {nv:.0f}(开盘 {start:.0f}, {(nv / start - 1) * 100:+.2f}%) vs 真实链账本 {real:.0f}({(real / start - 1) * 100:+.2f}%)\n"
               f"成交 {len(self.state['trades'])} 笔, 重定 {self.n_re} 次, 模型花费 ${cost:.2f}; 明细 results/_live/{self.D}/se_{self.skill}/")
        (self.dir / "summary.md").write_text(msg + "\n", encoding="utf-8")
        self.wx(msg)

    def run(self, t_strategy="09:15", t_open="09:30", t_end="14:57"):
        while now().strftime("%H:%M") < t_strategy:
            time.sleep(10)
        if not self.strategy:
            self.restrategize("开盘前首版策略")
        while now().strftime("%H:%M") < t_open:
            time.sleep(5)
        while True:
            hm = now().strftime("%H:%M")
            if hm > t_end:
                break
            if "11:30" < hm < "13:00":
                time.sleep(20)
                continue
            try:
                self.feed.refresh(self.codes())
                fills = self.tick(hm)
                self.need_re(hm, fills)
            except Exception as e:   # noqa: BLE001
                self.ev(kind="执行器异常", err=repr(e)[:300])
            time.sleep(3)
        for _ in range(60):   # 等最后一轮重定落地
            if not self.pending:
                break
            time.sleep(10)
        self.close()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="用今天目录外的临时目录跑一遍桩: 定策略→命中规则→成交→记账, 断言结果")
    a = ap.parse_args()
    if a.selftest:
        return selftest(a.skill)
    SE(a.skill, a.date, a.dry).run()


def selftest(skill):
    import tempfile
    D = dt.date.today().isoformat()
    se = SE.__new__(SE)
    se.skill, se.D, se.dry = skill, D, True
    se.dir = Path(tempfile.mkdtemp()) / "se"
    (se.dir / "strategies").mkdir(parents=True)
    import mentors
    se.book_name = mentors.book(skill)
    se.state = se._init_state()
    se.strategy, se.ver, se.fired, se.last_re, se.n_re, se.pending, se.cap = None, 0, set(), None, 0, False, 9
    se.feed, se.lock, se.flips_seen = Feed(D), threading.Lock(), set()
    se.wx = lambda m: print("WX>", m.replace("\n", " | ")[:300])
    c = next(iter(se.state["positions"]))
    pc = prev_close(c, D)
    q0 = se.state["positions"][c]["sellable"]
    se.restrategize("自测")
    for _ in range(100):
        if not se.pending:
            break
        time.sleep(0.2)
    assert se.strategy and se.ver == 1, "首版策略没落地"
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
    s2, dropped = se.check({"view": "x", "codes": [{"code": c, "band": [1, 2], "rules": [{"id": "x", "side": "BUY", "op": ">=", "px": pc, "qty": 100},
                                                                                     {"id": "y", "side": "SELL", "op": ">=", "px": pc * 5, "qty": 100},
                                                                                     {"id": "z", "side": "BUY", "op": "<=", "px": pc, "qty": 150}]},
                                                   {"code": "000001", "band": [1, 2], "rules": []}]})
    assert len(s2["codes"]) == 1 and not s2["codes"][0]["rules"] and len(dropped) == 4, f"校验应剔 4 处: {dropped}"
    print("SELFTEST PASS", se.dir)


if __name__ == "__main__":
    main()
