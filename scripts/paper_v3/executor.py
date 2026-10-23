# -*- coding: utf-8 -*-
"""executor.py — paper v3 执行器(一本账一个进程; 10/22 晚建)

继承 v2 se_exec.SE: 3 秒盘口撮合 / 记账 / T+1 / 费用 / 09:25 竞价 / 15:00 尾盘竞价 / 触发判定 / 断点续跑 / nav 曲线 —— 这些 v2 跑过一整天, 原样复用
只换"叫模型"那一段(_chain): v2 = 直连 API 每次独立跑 01→06; v3 = 同一个 claude -p 会话(session.py, A2)里接着想
  09:00 启动: 第 1 条消息 = 材料包(pack.boot_msg) + 02 → 04 → 05 → 06(每轮一次 --resume)
  盘中触发: 01(脚本拼: 账户 / 开盘实况 / 指数 / 候选池 + 焦点票必查; 事实包没变不重发) + 04 → 05 → 06
  竞价段(09:15~09:25)触发: 04 → 06(跳过 05: 开盘前过度交易 / 当日亏损都为 0; 10/22 晚按 v2 耗时倒推)
  06 每条规则要写"依据："; 漏写 → 同会话追问补一次(竞价段 / 尾盘不追问), 补不上照用并标"依据：无(未补)"
两种模式(lines.json mode; 10/22 晚用户定名): watch = 盯盘模式(v2 触发全保留); plan = 计划模式(原"作战卡"), 只有出 band(失效)、失败重试、手动 KICK、固定时刻(09:20 竞价复核 / 14:51 尾盘)才叫醒
账本: results/_live/<D>/v3_<线>/(state.json / strategies / versions / session.json / events.jsonl / curve.csv / nav.csv); 起点 = 前一交易日本线收盘状态, 没有 = 10 万空仓
用法:
  python executor.py --line tudou                 (正式: 等到 09:00 + 错峰启动, 跑到收盘)
  python executor.py --line tudou --fake          (桩: 不调模型, 假会话回固定条件单, 跑通全流程)
  python executor.py --line tudou --boot-only     (彩排: 只跑 09:00 启动这一套 02→04→05→06, 打印耗时 / 花费 / 条件单, 不进盘中循环)
"""
import argparse
import collections
import datetime as dt
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V3 = ROOT / "scripts" / "paper_v3"
sys.path[:0] = [str(V3), str(ROOT / "scripts" / "dfcf" / "paper"), str(ROOT / "scripts" / "chain"), str(ROOT / "scripts" / "lib")]
import mentors   # noqa: E402
import pack   # noqa: E402
import se_exec as X   # noqa: E402
from session import Session   # noqa: E402

_book = mentors.book
mentors.book = lambda s: _book(s) if s in mentors.ids() else f"V3-{s}"   # bank / nasdaq 不在导师名单: 给个假账本名(只用于读"旧 paper 账本", v3 不用)
INIT_CASH = 100000.0
MEMDIR = V3 / "memory"
LIVE = ROOT / "results" / "_live"   # 账本根目录(彩排回放换成 results/_replay)   # 本线记忆目录(桩测试会换成临时目录, 免得测试数据进明天的启动材料)

# ---- 一个进程管多本账(10/22 晚用户定: 总控起 9 个会话、统一叫醒) ----
# 每本账自己的开关(尾盘错峰时刻 / 决策 T 固定心跳)放线程局部, 其余开关全进程共用; v2 的 flag() 先读这里
_TL = threading.local()
_flag0 = X.flag


def _flag(name, default=""):
    ov = getattr(_TL, "ov", None)
    if ov and name in ov:
        return ov[name]
    return _flag0(name, default)


X.flag = _flag
_B01 = threading.Lock()   # build_01 期间临时换 se_chain.pool(决策 T 线只给本线标的) → 多本账同进程时串行


def dyn_cap(line, D):
    """自由触发上限(10/22 23:3x 用户令改回动态, 系数我定): ceil(k × 导师近 20 个交易日日均出手) 夹在 [下限, 上限]; 决策 T 线没有导师 = 固定值;
    计划模式 = 盯盘模式各拟人导师上限的平均(向上取整)
    出手 = 同一天同一只票同一方向算一次(同花顺逐笔腿); 开关 V3_CAP_K=5 / V3_CAP_MIN=6 / V3_CAP_MAX=20 / V3_CAP_DT=8"""
    import math
    k, lo, hi = float(_flag0("V3_CAP_K", "5") or 5), int(_flag0("V3_CAP_MIN", "6") or 6), int(_flag0("V3_CAP_MAX", "20") or 20)
    if line["kind"] == "dt":
        return int(_flag0("V3_CAP_DT", "8") or 8)
    if line.get("mode") == "plan":   # 10/22 23:4x 用户定: 计划模式 = 盯盘模式在跑的 tzzb 拟人线(按导师去重, 噪声基线不重复算)各自上限的平均, 向上取整
        seen, caps = set(), []
        for ln in pack.lines().values():
            if ln["kind"] == "mimic" and ln.get("mode") == "watch" and ln["skill"] not in seen:
                seen.add(ln["skill"])
                caps.append(dyn_cap(ln, D))
        return math.ceil(sum(caps) / len(caps)) if caps else lo
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
        import manual_backfill as mb
        c = mb.db().cursor()
        c.execute("use investment_market")
        c.execute("select distinct trade_date from kline_day where symbol='sh000001' and trade_date < %s order by trade_date desc limit 20", (D,))
        days = [str(x[0]) for x in c.fetchall()]
        if not days:
            return lo
        c.execute("use investment_tool")
        c.execute("select date(record_time), stock_code, side from tzzb_record where record_type='bs_leg' and is_deleted=0 and ledger=%s and record_time >= %s and record_time < %s",
                  (line["skill"], min(days), D))
        n = len({(str(d), cd, sd) for d, cd, sd in c.fetchall()})
        return max(lo, min(hi, math.ceil(k * n / len(days))))
    except Exception:   # noqa: BLE001
        return lo


class Gate:
    """统一叫醒队列: 同时最多 n 个会话在跑(claude -p), 其余按优先级排队(数字小先; 同级先到先得)。
    极端情况(09:20 竞价复核 / 大盘翻转 / 10:30 空仓提醒)9 本同时要叫醒 → 不再一起打到中转站(10/22 v2 事故根因)"""
    def __init__(self, n):
        self.n, self.busy, self.wait, self.cv, self.seq, self.log = n, 0, [], threading.Condition(), 0, []

    def acquire(self, prio, who="", k=1):
        """k = 这次要同时占几个名额(带 03 的账: 主会话 + 多方 + 空方 = 3)"""
        k = min(k, self.n)
        with self.cv:
            self.seq += 1
            me = (prio, self.seq, who)
            self.wait.append(me)
            self.wait.sort()
            while not (self.busy + k <= self.n and self.wait[0] == me):
                self.cv.wait(1)
            self.wait.pop(0)
            self.busy += k
            self.log.append(("in", who, prio, time.time(), self.busy))
            self.cv.notify_all()

    def release(self, who="", k=1):
        k = min(k, self.n)
        with self.cv:
            self.busy -= k
            self.log.append(("out", who, None, time.time(), self.busy))
            self.cv.notify_all()


def gate_n():
    """叫醒队列上限(10/23 用户令: 理论最大 13 之外取高一点防特殊 bug = 全部同花顺导师 skill + 3 位 B 站 UP skill 的个数, 随导师增加自动变)
    V3_MAX_INFLIGHT=auto → 数: downloads/tzzb/<导师> 且 skills/<导师>-skill 存在 + skills 里 taoge / qushitiange / lubenyuan; 填数字 = 固定值"""
    v = (_flag0("V3_MAX_INFLIGHT", "auto") or "auto").strip()
    if v.isdigit():
        return int(v)
    sk = ROOT / "skills"
    tz = [d.name for d in (ROOT / "downloads" / "tzzb").glob("*") if d.is_dir() and not d.name.startswith("_") and d.name != "rank" and (sk / f"{d.name}-skill").is_dir()]
    up = [u for u in ("taoge", "qushitiange", "lubenyuan") if (sk / f"{u}-skill").is_dir()]
    return max(13, len(tz) + len(up))


GATE = Gate(gate_n())

ASK02 = """【02 市况】上面是今天的全部材料。先写本时点的市况：状态 / 态度(偏多 / 中性 / 偏空) / 最多 3 个方向 / 3~4 条证据(引用 01 开盘实况或指数里的具体数字) / 多日展望 / 今天开盘情景预案(高开 / 平开 / 低开各怎么看)。机械判定和你的结论不一致时写理由。篇幅按需要。
最后 ```json {"state": "...", "attitude": "偏多|中性|偏空", "directions": ["..."], "horizon_days": N, "mismatch": "无|理由"}"""
ASK04_BOOT = """【04 选票】只能从 01 候选池里选(写行号；决策 T 线只做给定标的)。目标是像导师一样赚钱且稳：优先导师历史上赚钱的打法和位置(看材料里导师打法战绩、必查结果里的"导师同票" "相似日" "题材")，导师自己都亏钱的打法要写理由才做。对每只持仓给动作(持有 / 加 / 减 / 清)，新开仓按导师节奏和能力圈(空仓 10 万时要按导师习惯建仓，不要因为"没把握"一直空着)。
每只写：目标仓位% / 打法 / 理由(引用盘中特征数字 + 规则编号 + 必查 E 编号) / 如果错了最可能错在哪。
最后 ```json {"picks": [{"row": 行号, "code": "...", "action": "建|加|减|清|持有|观望", "target_pct": 数字, "play": "...", "why": "...", "rules": ["编号"], "evidence": ["E3"]}], "cash_pct": 数字}"""
ASK04_TRIG = """【04 选票(盘中触发)】上面是这次触发的"变了什么"(账户 / 盘口 / 指数 / 候选池) 和焦点票的必查结果。先用两三句话更新市况判断(和上一版比变了什么，上一版写的下一轮预期和失效条件逐条回应)，再按 04 的要求选票 / 给持仓动作。
最后 ```json {"picks": [{"row": 行号, "code": "...", "action": "建|加|减|清|持有|观望", "target_pct": 数字, "play": "...", "why": "...", "rules": ["编号"], "evidence": ["E3"]}], "cash_pct": 数字, "market_change": "..."}"""
ASK05 = """【05 风控】只管两项，每项一句话 + 结论(拟人度 / 单票仓位由 06 自检；方向 / 涨跌停 / 股数 / T+1 / 现金由执行器硬校验)：
① 过度交易：今天已成交几笔、和导师日均出手比(看下面统计)，本轮还该不该新开、最多新开几笔
② 当日亏损：今天账本盈亏多少，要不要暂停新买(卖出不受限)
{stats}
最后 ```json {{"checks": [{{"item": "过度交易|当日亏损", "verdict": "放行|限制|拦", "why": "..."}}], "max_new_trades": 整数(不限写 -1), "pause_buy": true|false}}"""
CRIT = (("09:15:00", "09:31:00"), ("14:50:00", "15:01:00"))   # 关键时段: 不追问证据、少查资料
WAKE_ASK = """
另在 json 里加 "wake": 结构化失效条件列表(执行器每 3 秒机械判, 命中就叫醒你重判; 文字版 invalid 照写给人看)。{card}每条一种:
  {{"type": "price", "code": "代码", "op": ">=|<=", "px": 价格, "why": "为什么到这就要重判"}}
  {{"type": "time", "at": "HH:MM", "unless": {{"type": "price", "code": "代码", "op": ">=", "px": 价格}}, "why": "时间止损: 到点还没达到 unless 就叫醒"}}
  {{"type": "index", "code": "sh000001|sz399006|sh000688|sz399303", "op": ">=|<=", "pct": 当日涨跌幅%, "why": "..."}}
时间止损、指数转弱、关键价位破位都要写成 wake; 没有就写 "wake": []。时间止损只能写**将来**的时刻(已过去的会被执行器剔除); 价格 / 指数条件在你写下时就已成立的, 要等它先回到不成立(满 1 分钟)再成立才会叫醒你。
每张普通限价单的 why 里写"成交概率 x%"(取上面"挂在这里今天能成交的概率"或必查"触及概率"里最接近的那格, 不要自己估): ≥50% = 正常单; 30~50% = 写一句为什么不挂近一点; <30% = 预案单(如"等大跌才接"), 必须写清在等什么情景。成交概率只说"买不买得到 / 卖不卖得掉", 不说"该不该做"; 该不该做看导师规则和当下情景, 目的是这一单最后赚钱。每张单的 why 用一两句回答三件事(按导师的做法答, 不必套格式): ①目的: 建仓 / 加仓 / 打板接力 / 做T(正T 先买后卖、反T 先卖后买)/ 止盈 / 止损 / 换仓; ②怎么收尾: 买单打算在哪个价、什么时候卖(或接着拿, 拿到什么情况才走); 卖单是不是要接回、在哪接回, 不接回也写; ③最怕什么、为什么还做: 买单 = 买了继续跌(看振幅、关键价位、导师同状态亏损的案例); 卖单 = 卖飞(看必查里导师"卖后 3 日最高"、强势股次日冲高分布)、卖在成本下方是止损还是做T。**挂价先按导师规则 / 关键价位 / 情景定, 概率只用来检查"是不是根本够不着"; 不许为了凑高概率把单挪到现价附近**, 要挪价必须写出是哪条规则或盘面变化让你挪, 写不出就保持原价并标成预案单(决策T 线例外: 本线说明里"能成交优先、挂价贴近买一 / 卖一"照旧, 前提是价差够费用门槛)。
有先后顺序的单(先卖后买 / 先买后卖)用 "after": 例 买回单写 "after": "r1" = 只有 r1 成交之后这张才生效; 不写 after 的单价格碰到就成交, 不管先后。
炸板接单(可选, 少用): 只在**导师历史上真有"开板接 / 排板回封"做法**的票型上用, why 里要引用对应的规则或案例编号; 它只是补充, **不能代替导师当天会直接下的单**(导师多数是开盘后看盘直接分批买 / 卖, 照导师的节奏写普通限价单)。开板到回封常常只有 1 分钟, 叫醒你来不及, 所以要用就事先写好。**统计参考**(docs/research/board_reseal_20261023.md, 30 天关注票、置信低~中): 开板后跌到离涨停 −2% 时接, 之后能封回 49%、当天收盘中位 −0.4%、次日最高中位 +2.0%、次日收盘中位 −2.7%; 跌到 −5% 再接封回只有 21%; 开板 ≥5 分钟还没封回, 之后封回 58%、≥20 分钟 37% —— 整体是负期望, 只有导师有对应案例、且准备次日冲高就卖时才用。写法(放进该票 rules):
  {{"id": "r9", "side": "BUY", "op": "<=", "type": "board_dip", "px": 接的上沿(如涨停价 × 0.98), "floor": 接的下沿(如涨停价 × 0.93, 再低就不接), "qty": 股数, "why": "为什么判断会回封 依据：…"}}
  执行器只在 这只票今天封过涨停 → 现在开板(有卖单) → 价格落在 [floor, px] 时, 按此刻卖二价买一次; 一直封死或跌破 floor 都不买。"""


def now():
    return X.now()


def critical(at):
    return any(a <= at < b for a, b in CRIT)


def lines():
    return pack.lines()


class V3(X.SE):
    def __init__(self, line, D, dry=False, fake=False):
        self.line, self.mode, self.fake = line, line["mode"], fake
        base = LIVE / D / f"v3_{line['id']}"
        super().__init__(line["skill"], D, dry, base=base, cap=dyn_cap(line, D))
        self.key = f"v3_{line['id']}"
        if fake:
            self.facts_build = False   # 桩测试不现做事实包(facts.mjs 会打外部行情源; 10/22 晚桩测试多打了几次)
        self.sess = Session(line["id"], D, base, effort=X.flag("V3_EFFORT", "high") or "high")
        self.facts_sent = None

    # ---------- 账本起点: 接本线前一交易日收盘, 否则 10 万空仓 ----------
    def _init_state(self):
        prev = sorted(p for p in LIVE.glob(f"20*/v3_{self.line['id']}/state.json") if p.parent.parent.name < self.D)
        if prev:
            ps = X.jl(prev[-1], {}) or {}
            pos = {c: {"qty": int(q["qty"]), "cost": q.get("cost"), "sellable": int(q["qty"]), "days": int(q.get("days") or 0) + 1}
                   for c, q in (ps.get("positions") or {}).items() if int(q.get("qty") or 0) > 0}
            cash, frm = round(float(ps.get("cash") or 0), 2), f"carry:{prev[-1].parent.parent.name}"
        else:
            pos, cash, frm = {}, float(self.line.get("cash") or INIT_CASH), "genesis"   # 决策T 两本只给 1 万(10/22 深夜用户定, 和旧决策T 同口径好对照)
        st = {"cash": cash, "positions": pos, "trades": [], "start": {"cash": cash, "positions": json.loads(json.dumps(pos)), "from": frm, "at": now().isoformat(timespec="seconds")}}
        self._save(st)
        return st

    @staticmethod
    def _auc_test_skills():
        return set()   # v2 的"土豆竞价测试"路径 v3 不走

    @property
    def _after_auc_high(self):   # v2: 09:21 low 落地后立刻 high 重跑; v3 全程一个档, 不重跑
        return False

    @_after_auc_high.setter
    def _after_auc_high(self, v):
        pass

    def refresh_facts(self):
        if self.line["kind"] != "dt":
            return super().refresh_facts()
        import se_facts   # 决策 T 线没有导师小节: 直接用当天共享事实包全文(市况 / 外围 / 资讯参考)
        cur = se_facts.latest(self.D)
        if cur:
            (self.dir / "facts.txt").write_text(cur.read_text(encoding="utf-8"), encoding="utf-8")
        self.ev(kind="事实包", src=str(cur) if cur else None)
        return {"ok": bool(cur)}

    def facts_codes(self):
        return super().facts_codes() | getattr(self, "_pool", set()) | set(self.line.get("universe") or [])

    def check(self, s):
        s, dropped = super().check(s)
        # 10/23 凌晨彩排查出: 新版把同一张单(同票同方向同价)原样保留时, 真实柜台里这张单一直挂着、排队位置不变; 原来每出新版都当新单重新排到队尾 → 中行 7.17 那张因此没排到
        old_q = {(x["code"], r["side"], r.get("px")): r for x in (self.strategy or {}).get("codes") or [] for r in x.get("rules") or []
                 if r.get("rest") and f"{self.ver}:{x['code']}:{r['id']}" not in self.fired}
        for x in s.get("codes") or []:   # 标"排队单": 落地这一刻不能立刻成交(买: 卖一空或卖一 > 买价; 卖: 买一空或买一 < 卖价) → 将来被穿过时按挂单价成交
            q_ = self.feed.q.get(x["code"]) or {}   # 例 星光 10/22: 2.70 排板时封死、卖一空 → 排队单; 09:40 开板砸到 2.58 → 按 2.70 成交
            a1, b1 = q_.get("a1") or 0, q_.get("b1") or 0
            for r in x.get("rules") or []:
                r["rest"] = not (a1 and a1 <= r["px"]) if r["side"] == "BUY" else not (b1 and b1 >= r["px"])
                prev = old_q.get((x["code"], r["side"], r.get("px")))
                if r["rest"] and prev is not None:   # 同一张单原样保留 → 沿用原来的排队位置和已推进的成交量
                    r.update({k: prev.get(k) for k in ("_ahead", "_vol", "_vlast", "_queued_ok")})
                elif r["rest"]:   # 排队: 挂单时这个价位上排在前面的量(五档里找得到才算; 找不到 = 看不到队列, 只认穿价)
                    lv = q_.get("b") if r["side"] == "BUY" else q_.get("k")
                    ahead = next((int(b_) for a_, b_ in (lv or []) if a_ and abs(float(a_) - r["px"]) < 1e-6), None)
                    better = (r["side"] == "BUY" and b1 and r["px"] > b1) or (r["side"] == "SELL" and a1 and r["px"] < a1)   # 挂在买一卖一之间 = 新价位, 前面没人
                    r["_ahead"] = 0 if better else ahead
                    r["_vol"], r["_vlast"], r["_queued_ok"] = 0, q_.get("v"), False
                r["depth"] = True   # 立刻成交的单按五档吃单算价(se_exec.depth_fill)
                if r.get("type") == "board_dip":
                    try:
                        r["floor"] = float(r.get("floor") or 0)
                    except (TypeError, ValueError):
                        r["floor"] = 0.0
                    if r["side"] != "BUY" or not (0 < r["floor"] < r["px"]):
                        dropped.append(f"{x['code']} {r['id']} 炸板接单要 BUY 且 0 < floor < px")
                        r["type"] = "invalid"
        uni = set(self.line.get("universe") or [])
        if uni:
            keep = [x for x in s.get("codes") or [] if x["code"] in uni]
            dropped += [f"{x['code']} 不是本线标的" for x in s.get("codes") or [] if x["code"] not in uni]
            s["codes"] = keep
        hm, wk = now().strftime("%H:%M"), []   # 10/22 23:5x 用户令(根因): 时间止损只能写将来的时刻, 写已经过去的时刻 = 剔除并告诉模型
        for c in s.get("wake") or []:
            if isinstance(c, dict) and c.get("type") == "time" and str(c.get("at", "")) <= hm:
                dropped.append(f"时间止损 {c.get('at')} 已经过了(现在 {hm}), 只能写将来的时刻")
            else:
                wk.append(c)
        if "wake" in s:
            s["wake"] = wk
        return s, dropped

    # ---------- 结构化失效条件(wake): 执行器每 3 秒机械判, 命中就叫醒(10/22 晚: 文字版 invalid 执行器读不懂, 计划模式只认 band 会漏掉时间止损 / 指数条件) ----------
    def idx_now(self):
        """3 秒指数尾读(collect_book → index_snap.jsonl): {sh000001: (现价, 昨收)}"""
        f = X.MKT / self.D / "index_snap.jsonl"
        if not hasattr(self, "_idx"):
            self._idx, self._idx_pos = {}, 0
        if f.exists():
            with f.open("rb") as fh:
                fh.seek(self._idx_pos)
                for l in fh:
                    if not l.endswith(b"\n"):
                        break
                    self._idx_pos += len(l)
                    try:
                        r = json.loads(l)
                    except ValueError:
                        continue
                    if r.get("p") and r.get("pc"):
                        self._idx[r["s"]] = (float(r["p"]), float(r["pc"]))
        return self._idx

    def _cond(self, c):
        """单个条件现在成立吗(数据缺 = 不成立)"""
        op = c.get("op")
        if c.get("type") == "price":
            q = self.feed.q.get(str(c.get("code")))
            return bool(q) and (q["p"] >= float(c["px"]) if op == ">=" else q["p"] <= float(c["px"]))
        if c.get("type") == "index":
            v = self.idx_now().get(str(c.get("code")))
            if not v:
                return False
            pct = (v[0] / v[1] - 1) * 100
            return pct >= float(c["pct"]) if op == ">=" else pct <= float(c["pct"])
        return False

    def wake_hits(self, hm):
        """10/22 23:4x 回放桩测出死循环(芷影 11:11 前叫醒 416 次): 命中后新版策略原样写回同一条 → 立刻又命中, 叫醒不占上限会一直烧 token
        修: 时间类按时刻每天只响一次(不分版本; check 另把已过去的时刻剔掉); 价格 / 指数类只在"不成立 → 成立"时响:
            条件要先连续不成立满 V3_BAND_HOLD_S 秒(默认 60, 同出区间去抖)才"上膛", 上膛后一成立就响(每版每条一次)
            → 新版写进来时已成立的不响; 在价位附近来回抖也不会反复响
            10/23 01:2x 用户令改动态(验证见 results/inv-stock/test/cooldown_validate.md): 价格类"上膛" = 价格退到价位另一侧 ≥ max(2 个最小价位, V3_WAKE_R × σ)
            并待满 30 秒(噪声比固定 60 秒少 78%); 指数类、σ 取不到的票仍用"不成立满 V3_BAND_HOLD_S 秒"; 箱体规则验证无额外好处, 不用"""
        out = []
        fired = getattr(self, "_wake_fired", set())
        armed = getattr(self, "_wake_armed", set())
        since = getattr(self, "_wake_false_since", {})
        hold = float(X.flag("V3_BAND_HOLD_S", "60") or 0)
        dyn = X.flag("V3_SIGMA_DYNAMIC", "1") == "1"
        rk = float(X.flag("V3_WAKE_R", "0.25") or 0)
        t = now()
        for i, c in enumerate((self.strategy or {}).get("wake") or []):
            if not isinstance(c, dict):
                continue
            try:
                if c.get("type") == "time":
                    k = f"time:{c.get('at')}"
                    hit = k not in fired and hm >= str(c.get("at", "99:99")) and not (isinstance(c.get("unless"), dict) and self._cond(c["unless"]))
                else:
                    k = f"{self.ver}:{i}"
                    if self._cond(c):
                        since.pop(k, None)
                        hit = k in armed and k not in fired
                    else:
                        need_s, away = hold, True
                        if dyn and c.get("type") == "price":
                            code = str(c.get("code"))
                            sg, q = self.sigma(code), self.feed.q.get(code)
                            if sg and q:
                                tick = 0.001 if code.startswith(("1", "5")) else 0.01
                                lvl = float(c["px"])
                                away = (lvl - q["p"] if c.get("op") == ">=" else q["p"] - lvl) >= max(2 * tick, rk * sg)
                                need_s = 30
                        if away:
                            since.setdefault(k, t)
                            if (t - since[k]).total_seconds() >= need_s:
                                armed.add(k)
                        else:
                            since.pop(k, None)
                        hit = False
            except (KeyError, TypeError, ValueError):
                continue
            if hit:
                fired.add(k)
                out.append(f"失效条件命中: {c.get('why') or json.dumps(c, ensure_ascii=False)}")
        self._wake_fired, self._wake_armed, self._wake_false_since = fired, armed, since
        return out

    def _band_view(self):
        """出区间去抖(10/22 实测芷影 10:27 前出区间 6 次用光上限, 多是开盘尖刺); 不满的票返回放宽到现价的 band
        10/23 01:2x 用户令改动态(零 token 验证 results/inv-stock/test/cooldown_validate.md 定系数): 越过边沿 ≥ V3_BAND_M × σ 才开始计时,
        持续 H = clamp(V3_BAND_BASE × σ% / 3%, 30, 180) 秒才算出区间; σ 取不到 → 退回固定 V3_BAND_HOLD_S 秒"""
        s = self.strategy
        if not s:
            return s
        hold = float(X.flag("V3_BAND_HOLD_S", "60") or 0)
        dyn = X.flag("V3_SIGMA_DYNAMIC", "1") == "1"
        mk, base = float(X.flag("V3_BAND_M", "0.1") or 0), float(X.flag("V3_BAND_BASE", "15") or 15)
        since = getattr(self, "_out_since", {})
        t = now()
        out = []
        for x in s.get("codes") or []:
            q = self.feed.q.get(x["code"])
            lo, hi = x["band"]
            sg = self.sigma(x["code"]) if dyn and q else None
            mg = mk * sg if sg else 0.0
            H = min(180.0, max(30.0, base * (sg / q["p"]) / 0.03)) if sg and q and q.get("p") else hold
            if q and not (lo - mg <= q["p"] <= hi + mg):
                since.setdefault((self.ver, x["code"]), t)
                if (t - since[(self.ver, x["code"])]).total_seconds() < H:
                    x = {**x, "band": [min(lo, q["p"]), max(hi, q["p"])]}
            else:
                since.pop((self.ver, x["code"]), None)
                if q and not (lo <= q["p"] <= hi):   # 越过了但没超出 m·σ 余量: 不算出区间
                    x = {**x, "band": [min(lo, q["p"]), max(hi, q["p"])]}
            out.append(x)
        self._out_since = since
        return {**s, "codes": out}

    # ---------- 噪声单位 σ(10/23 01:2x 用户令: 防超频的冷却 / 去抖都按票的波动定, 区分大票小票) ----------
    def _amp_A(self, code):
        """A = 近 5 个交易日日内振幅((高−低)/昨收)中位 × 最近收盘价(价格单位); 只用 D 之前的日线, 每天每票查一次"""
        cache = self.__dict__.setdefault("_ampA", {})
        if code not in cache:
            try:
                import manual_backfill as mb
                cur = mb.db().cursor()
                cur.execute("use investment_market")
                sym = ("sh" if code.startswith(("6", "5", "11")) else "sz") + code
                cur.execute("select high, low, pre_close, close from kline_day where is_deleted=0 and symbol=%s and trade_date < %s order by trade_date desc limit 5", (sym, self.D))
                rows = [(float(h), float(l), float(pc), float(c)) for h, l, pc, c in cur.fetchall() if h and l and pc and c]
                rs = sorted((h - l) / pc for h, l, pc, _ in rows)
                cache[code] = rs[len(rs) // 2] * rows[0][3] if rs else None
            except Exception:   # noqa: BLE001  取不到 → 退回固定规则
                cache[code] = None
        return cache[code]

    def _track_all(self):
        """近 30 分钟分时(每 3 秒一点), 算 σ 的 B 部分"""
        hs = self.__dict__.setdefault("_hist", {})
        hl = self.__dict__.setdefault("_dayhl", {})   # 今天已走出的最低 / 最高(09:30 后; 触及概率的"此刻口径"用)
        t = now()
        for code, q in list(self.feed.q.items()):
            if not q.get("p"):
                continue
            if t.strftime("%H:%M") >= "09:30":
                lo_, hi_ = hl.get(code, (q["p"], q["p"]))
                hl[code] = (min(lo_, float(q["p"])), max(hi_, float(q["p"])))
            h = hs.setdefault(code, collections.deque())
            if not h or (t - h[-1][0]).total_seconds() >= 3:
                h.append((t, float(q["p"])))
            while h and (t - h[0][0]).total_seconds() > 1800:
                h.popleft()

    def sigma(self, code):
        """σ = max(A, B); B = 近 30 分钟里"5 分钟振幅"的中位(不足 5 分钟只用 A)。都取不到返回 None"""
        A = self._amp_A(code)
        h = (getattr(self, "_hist", {}) or {}).get(code)
        B = None
        if h and (h[-1][0] - h[0][0]).total_seconds() >= 300:
            mins = collections.OrderedDict()
            for t_, v_ in h:
                m = t_.replace(second=0, microsecond=0)
                lo_, hi_ = mins.get(m, (v_, v_))
                mins[m] = (min(lo_, v_), max(hi_, v_))
            bars = list(mins.values())
            rng = sorted(max(b[1] for b in bars[j:j + 5]) - min(b[0] for b in bars[j:j + 5]) for j in range(max(1, len(bars) - 4)))
            B = rng[len(rng) // 2]
        v = max(A or 0.0, B or 0.0)
        return v or None

    def codes(self):
        cs = set(super().codes())
        for c in (self.strategy or {}).get("wake") or []:
            for x in (c, c.get("unless") if isinstance(c, dict) else None):
                if isinstance(x, dict) and x.get("type") == "price" and x.get("code"):
                    cs.add(str(x["code"]))
        return sorted(cs)

    # ---------- 计划模式: 只有计划失效(出 band / wake 命中)才叫醒 ----------
    def restrategize(self, why, counted=True, effort=None, tag=None):
        if tag == "auction" and self.line["kind"] == "dt":   # 10/22 晚: 银行 / 纳指 ETF 不靠竞价单, 竞价复核让给拟人线(并发队列里少排 2 个)
            self.ev(kind="决策T 不做竞价复核", why=why)
            return
        fill_ok = bool(self.line.get("wake_on_fill")) and re.match(r"^(\(排队补叫\) )?(本链成交|竞价成交)", why)   # 10/23 凌晨用户定: 计划模式另开一本"成交叫醒"做对照
        if self.mode == "plan" and not fill_ok and re.match(r"^(\(排队补叫\) )?(本链成交|竞价成交|心跳)", why):
            self.ev(kind="计划模式不唤醒", why=why)
            return
        if counted and now().strftime("%H:%M") < (X.flag("V3_CAP_FROM", "10:30") or "10:30"):
            counted = False   # 10/22 晚用户令: 上限从 10:30 起才算(开盘段是导师最活跃的时候; 10/22 芷影 6 次出区间全在 10:28 前用光上限, 真人 09:34~10:41 出手 11 笔)
        return super().restrategize(why, counted, effort, tag)

    # ---------- 空仓提醒(10/22 晚用户批): 拟人线 10:30 / 13:30 还是 0 仓位、而导师通常有仓位 → 叫醒一次让它建仓或写理由(不强制, 不占上限) ----------
    def mentor_hold(self):
        """导师近 20 个交易日收盘持仓快照(同花顺账本 position_snap): (有持仓天数占比, 平均仓位%, 天数); 一个进程只查一次"""
        if not hasattr(self, "_mhold"):
            self._mhold = (None, None, 0)
            try:
                sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
                import manual_backfill as mb
                c = mb.db().cursor()
                c.execute("use investment_tool")
                c.execute("select date(record_time), payload_json from tzzb_record where record_type='position_snap' and is_deleted=0 and ledger=%s "
                          "and record_time < %s and record_time >= date_sub(%s, interval 45 day)", (self.skill, self.D, self.D))
                day = {}
                for d, pj in c.fetchall():
                    try:
                        pp = float((json.loads(pj or "{}") or {}).get("position_percent") or 0)
                    except ValueError:
                        pp = 0
                    day[str(d)] = day.get(str(d), 0) + pp
                ds = sorted(day)[-20:]
                if ds:
                    self._mhold = (sum(1 for d in ds if day[d] > 0) / len(ds), sum(min(day[d], 1) for d in ds) / len(ds) * 100, len(ds))
            except Exception as e:   # noqa: BLE001
                self.ev(kind="导师持仓统计失败", err=repr(e)[:200])
        return self._mhold

    def empty_nudge(self, hm):
        if self.line["kind"] != "mimic" or hm not in ("10:30", "13:30") or self.state.get("positions"):
            return
        done = getattr(self, "_nudged", set())
        if hm in done:
            return
        done.add(hm)
        self._nudged = done
        ratio, avg, n = self.mentor_hold()
        if ratio is None or ratio < 0.5:
            self.ev(kind="空仓提醒不触发", at=hm, mentor_ratio=ratio, n=n)
            return
        self.restrategize(f"空仓提醒: 现在 {hm} 本账仍是 0 仓位; 导师近 {n} 个交易日 {ratio:.0%} 的日子收盘有持仓、平均仓位约 {avg:.0f}%。"
                          "请按导师习惯建仓, 或写明今天不建仓的理由(不强制)", counted=False)

    def need_re(self, hm, fills):
        self._track_all()
        self._maybe_keepalive(hm)
        self.empty_nudge(hm)
        wk = self.wake_hits(hm) if now().strftime("%H:%M") < X.flag("SE_LAST_CHAIN", "14:51") else []
        if wk:
            self.restrategize("; ".join(wk), counted=False)   # 失效条件 = 必判, 不占上限、不看冷却(在算时会排队合并)
        held = self._band_view()
        if self.mode != "plan":
            with self.lock:   # 出 band 不满 V3_BAND_HOLD_S 秒的票: 给 v2 的判定看"放宽到现价"的 band(拿着锁, 新起的链线程要等换回真 band 才读策略)
                real, self.strategy = self.strategy, held
                try:
                    return super().need_re(hm, fills)
                finally:
                    self.strategy = real
        why = []
        if fills and self.line.get("wake_on_fill"):   # 计划模式 + 成交叫醒: 成交 = 必判(和盯盘模式一样不计上限)
            why.append("本链成交 " + ",".join(f"{t['side']}{t['code']}" for t in fills))
        rt = getattr(self, "retry", None)
        if rt and time.time() >= rt[0] and not self.pending:
            self.retry = None
            why.append("(失败重试) " + str(rt[1])[:120])
        kick = self.dir / "KICK"
        if kick.exists():
            why.append("手动: " + (kick.read_text(encoding="utf-8", errors="replace").strip() or "手动重定")[:100])
            kick.unlink(missing_ok=True)
        for x in (held or {}).get("codes") or []:
            q = self.feed.q.get(x["code"])
            if q and not (x["band"][0] <= q["p"] <= x["band"][1]):
                why.append(f"{x['code']} {q['p']} 出区间 {x['band'][0]}~{x['band'][1]}(失效)")
        if not why or now().strftime("%H:%M") >= X.flag("SE_LAST_CHAIN", "14:51"):
            return
        must = any(w.startswith(("(失败重试)", "手动", "本链成交")) for w in why)
        if self.last_re and (now() - self.last_re).total_seconds() < (3 if hm <= "10:30" else 5) * 60 and not must:
            return
        if not must and hm >= (X.flag("V3_CAP_FROM", "10:30") or "10:30") and self.n_re >= self.cap:   # 10/22 23:2x 用户定: 计划模式的出 band 和盯盘一样 10:30 起计上限(共用上限值、各本分别计数)
            if not getattr(self, "_capped", False):
                self._capped = True
                self.ev(kind="到上限", why=why)
            return
        self.restrategize("; ".join(why), counted=not must)   # 10:30 前 restrategize 内部自动改成不计

    # ---------- 叫模型: 同一会话里接着想 ----------
    # ---------- 缓存保温(10/23 00:5x 彩排发现: 5 分钟缓存过期 → 每次叫醒重写 33 万 token ≈ $1.7; 改 1 小时缓存后, 空闲满 V3_KEEPALIVE_MIN 分钟发一句短话续期) ----------
    def _maybe_keepalive(self, hm):
        kp = float(X.flag("V3_KEEPALIVE_MIN", "50") or 0)
        last = getattr(self, "_last_ask", None)
        if not kp or self.fake or self.pending or not self.sess.booted or last is None or not ("09:30" <= hm < "14:50"):
            return
        if (now() - last).total_seconds() < kp * 60:
            return
        self.pending = True   # 占住本账: 保温期间来的叫醒按原机制排队补叫, 不会和保温同时 --resume 同一个会话
        self._last_ask = now()
        threading.Thread(target=self._keepalive, name=f"keep-{self.line['id']}", daemon=True).start()

    def _keepalive(self):
        """不占叫醒名额(10/23 01:0x 用户令), 也不算触发次数; 本账 pending 期间来的叫醒照原机制排队补叫"""
        try:
            r = self.sess.ask("（保温：只为续上提示缓存，不用分析、不用改策略，回复「1」即可）", "keep", timeout=180)
            u = r.get("usage") or {}
            self.ev(kind="缓存保温", ok=r.get("ok"), secs=r.get("secs"), usd=round(r.get("usd") or 0, 4), cache_read=u.get("cache_read_input_tokens"), cache_write=u.get("cache_creation_input_tokens"))
        except Exception as e:   # noqa: BLE001  保温失败不影响交易
            self.ev(kind="缓存保温失败", err=repr(e)[:200])
        finally:
            self._last_ask = now()
            self.pending = False

    def _tmo(self, rnd, boot=False):
        """每轮超时(10/23 01:3x 用户令: 按当日实际最大耗时算, 不同线不同): = clamp(V3_TMO_K × 本线今天这一步见过的最长耗时, V3_TMO_MIN, V3_TMO_MAX);
        启动轮直接给上限。只防"真挂死占着叫醒名额"——超时被杀 = 这一轮作废、下次叫醒重来; 竞价 / 尾盘段不再单独缩短(竞价没赶上 09:24:57 有草稿兜底挂单,
        迟到的正式版照样用于连续竞价), 所以关键时段也不杀想得久的轮次"""
        lo, k, hi = (float(X.flag(n, d) or d) for n, d in (("V3_TMO_MIN", "600"), ("V3_TMO_K", "3"), ("V3_TMO_MAX", "1800")))
        if boot:
            return hi
        return min(hi, max(lo, k * self.__dict__.setdefault("_step_max", {}).get(rnd, 0)))

    def _ask(self, rnd, text, vd, T, timeout, boot=False):
        timeout = self._tmo(rnd, boot)   # 调用方传的旧固定值(120 / 300 / 600)不再用
        if self.fake and boot:   # 桩: 假装建了会话(否则每次触发都当启动)
            self.sess.st = {"date": self.D, "line": self.line["id"], "sid": "fake", "boot_tag": self.sess.tag, "turns": []}
            self.sess._save()
        r = self._fake(rnd, text) if self.fake else self.sess.ask(text, rnd, timeout=timeout, boot=boot)
        self._last_ask = now()
        if r.get("ok") and r.get("secs"):
            sm = self.__dict__.setdefault("_step_max", {})
            sm[rnd] = max(sm.get(rnd, 0), float(r["secs"]))
        (vd / f"{rnd}.md").write_text(r["text"] or f"(失败: {r['err']})", encoding="utf-8")
        if r.get("json") is not None:
            (vd / f"{rnd}.json").write_text(json.dumps(r["json"], ensure_ascii=False, indent=1), encoding="utf-8")
        u = r.get("usage") or {}
        T["steps"][rnd] = {"secs": r["secs"], "ok": r["ok"], "usd": r["usd"], "cache_read": u.get("cache_read_input_tokens"), "cache_write": u.get("cache_creation_input_tokens"),
                           "in": u.get("input_tokens"), "out": u.get("output_tokens"), "err": (r.get("err") or "")[:200]}
        return r

    def prio(self, why):
        """叫醒优先级: 0 启动 / 竞价复核 → 1 成交 / 失效条件 / 空仓提醒 / 失败重试 / 手动 → 2 出区间 / 翻转 / 尾盘 → 3 心跳; 同级: 有持仓的先, 再按 lines.json 顺序(土豆在前)"""
        t = now().strftime("%H:%M:%S")
        c = 0 if (why.startswith("开盘前首版") or "竞价段" in why or t < "09:25:00") else 3 if why.startswith("心跳") else             1 if re.search(r"成交|失效条件|空仓提醒|失败重试|手动", why) else 2
        order = list(pack.lines()).index(self.line["id"]) if self.line["id"] in pack.lines() else 99
        return c * 1000 + (0 if self.state.get("positions") else 100) + order

    def _chain(self, why, effort="high"):
        p = self.prio(why)
        self.ev(kind="排队叫醒", prio=p, inflight=GATE.busy, waiting=len(GATE.wait))
        k = 3 if self.debate_now() else 1   # 带 03: 多方 / 空方两个分支和主会话同时在跑
        GATE.acquire(p, self.line["id"], k)
        try:
            return self._chain_run(why, effort)
        finally:
            GATE.release(self.line["id"], k)

    def debate_now(self):
        """这本账这次跑不跑 03: lines.json debate=true 且不在竞价段(竞价复核不跑 03, 你 23:5x 定)"""
        return bool(self.line.get("debate")) and now().strftime("%H:%M:%S") >= "09:25:00" or (bool(self.line.get("debate")) and not self.sess.booted)

    def _debate(self, vd, T):
        """03 多空辩论(10/22 23:5x 用户定: 和 v1 / TradingAgents 一样多方空方独立并行): 从主会话分出两个分支同时跑, 彼此看不到, 也不写回主会话 → 两份结论交给 04 当裁判"""
        import se_chain
        res = {}

        def one(name, ask):
            res[name] = self._fake(name, ask) if self.fake else self.sess.fork(ask, name, timeout=self._tmo("03"))
        ths = [threading.Thread(target=one, args=("03_bull", se_chain.ASK["03b"])), threading.Thread(target=one, args=("03_bear", se_chain.ASK["03r"]))]
        [t.start() for t in ths]
        [t.join() for t in ths]
        cost = 0.0
        parts = []
        for name, title in (("03_bull", "多方(独立研究员)"), ("03_bear", "空方(独立研究员)")):
            r = res.get(name) or {"ok": False, "text": "", "secs": 0, "usd": 0, "usage": {}, "err": "没跑"}
            (vd / f"{name}.md").write_text(r["text"] or f"(失败: {r.get('err')})", encoding="utf-8")
            T["steps"][name] = {"secs": r["secs"], "ok": r["ok"], "usd": r["usd"], "err": (r.get("err") or "")[:200]}
            cost += r["usd"] or 0
            parts.append(f"## 03 {title}{chr(10)}" + (r["text"] if r["ok"] else "(这一方失败, 本次没有它的论点)"))
        nl2 = chr(10) * 2
        return nl2.join(parts) + nl2 + "上面是两位独立研究员的多空论点(他们彼此看不到对方)。请你作为裁判权衡后做 04, 在理由里写清采纳了哪方哪条、为什么。" + nl2, cost

    def _chain_run(self, why, effort="high"):
        import se_chain
        t0 = time.time()
        vd = self.dir / "versions" / f"{self.ver + 1:02d}_{now():%H%M%S}"
        vd.mkdir(parents=True, exist_ok=True)
        with self.lock:
            state = json.loads(json.dumps(self.state))
            strat, fired = (json.loads(json.dumps(self.strategy)) if self.strategy else None), set(self.fired)
        at, quotes, oc = now().strftime("%H:%M:%S"), dict(self.feed.q), self.open_ctx()
        ff = self.facts_file()
        src = f"{ff}:{ff.stat().st_mtime:.0f}" if ff.exists() else None
        if self.sess.booted and src and src == self.facts_sent:
            facts = "(事实包和上一次给你的相同, 没变, 见前文)"
        else:
            try:
                facts = f"(本份事实包生成于 {dt.datetime.fromtimestamp(ff.stat().st_mtime):%H:%M:%S}, 不是此刻)\n" + ff.read_text(encoding="utf-8", errors="replace")
                facts = re.sub(r"## 昨日账本状态[\s\S]*?(?=\n## (?!A-))", "## 昨日账本状态\n(旧 paper 账本, v3 不用)\n", facts, count=1)
            except OSError:
                facts = "(今日事实包缺)"
        uni = list(self.line.get("universe") or [])
        with _B01:
            pool0 = se_chain.pool
            if uni:   # 决策 T 线: 候选池 = 给定标的(不从事实包抓票)
                se_chain.pool = lambda *a, **k: {c: "本线标的" for c in uni}
            try:
                f01, P, px, nav = se_chain.build_01(self.skill, self.D, at, why, state, strat, fired, quotes, facts, oc, "(同一会话: 上一版的 02 / 06 见前文)", live=not self.dry)
            finally:
                se_chain.pool = pool0
        names = se_chain.names(self.D)
        f01 = f01 + self.stock_block(P, at, names)   # 10/23 01:5x 用户问: 转债进了候选池, 正股要跟着进(竞价 / 盘口), 原来 01 只有转债一行、模型写"正股竞价未知"
        self._pool = set(P)   # 本次候选池 = 06 可以写的代码(v2 只认 持仓 / 上一版 / 事实包, 候选池里别的来源的票会被剔 —— 10/22 桩测试抓到)
        T = {"start": at, "why": why, "boot": not self.sess.booted, "steps": {}}
        (vd / "01_facts.md").write_text(f01, encoding="utf-8")
        auction = at < "09:25:00"
        crit = critical(at)
        lim = 120 if crit else 300
        cost = 0.0

        def fail(msg):
            T.update(result=msg, total=round(time.time() - t0, 1), usd=round(cost, 4))
            (vd / "timing.json").write_text(json.dumps(T, ensure_ascii=False, indent=1), encoding="utf-8")
            return None, cost, T

        if not self.sess.booted:
            msg, stat = pack.boot_msg(self.line, self.D, f01, P, names, state, ASK02)
            T["pack"] = stat
            (vd / "00_boot_msg.md").write_text(msg, encoding="utf-8")
            r2 = self._ask("02", msg, vd, T, 600, boot=True)
            cost += r2["usd"]
            if not r2["ok"]:
                self.sess.st = {}   # 启动失败: 下次重新启动(新会话号)
                self.sess.f.unlink(missing_ok=True)
                return fail(f"启动 02 失败: {r2['err']}")
            d03 = ""
            if self.line.get("debate"):
                d03, c3 = self._debate(vd, T)
                cost += c3
            r4 = self._ask("04", d03 + ASK04_BOOT, vd, T, lim)
        else:
            focus = list(dict.fromkeys([*state.get("positions", {}), *[x["code"] for x in (strat or {}).get("codes") or []], *uni]))
            msg, n = pack.trigger_msg(self.line, self.D, f01, P, names, state, quotes, focus, ASK04_TRIG)
            (vd / "00_trigger_msg.md").write_text(msg, encoding="utf-8")
            if self.line.get("debate") and not auction:   # 带 03: 先把 01 交给主会话(只读), 再分叉多空, 最后 04 裁判
                core = msg.rsplit("---", 1)[0]
                r1 = self._ask("01", core + chr(10) * 2 + "---" + chr(10) * 2 + "先只读这次的变化和必查结果, 回复「收到」即可, 下一条消息再做 04。", vd, T, 120)
                cost += r1["usd"]
                d03, c3 = self._debate(vd, T)
                cost += c3
                r4 = self._ask("04", d03 + ASK04_TRIG, vd, T, lim)
            else:
                r4 = self._ask("04", msg, vd, T, lim)
        cost += r4["usd"]
        self.facts_sent = src
        if not r4["ok"] and not r4["text"]:
            return fail(f"04 失败: {r4['err']}")
        if not auction:
            try:
                stats = se_chain.mimic_stats(self.skill, self.D, state, px)
            except Exception as e:   # noqa: BLE001
                stats = f"(拟人统计不可用: {e!r})"[:200]
            r5 = self._ask("05", ASK05.format(stats=stats), vd, T, 120)
            cost += r5["usd"]
        a06 = se_chain.ASK["06"].format(
            auction="现在是集合竞价阶段: 想在 09:25 竞价成交的规则加 \"auction\": true(买价 ≥ 撮合价 / 卖价 ≤ 撮合价按撮合价一次成交), 没加的 09:30 起生效。" if auction else "",
            auc_field='"auction": true|false, ' if auction else "")
        a06 = "【06 终裁】" + a06.split("】", 1)[-1] + "\n每条规则的 why 末尾写 `依据：规则编号 / E编号 / 相似日 / 关键价位 / 卖点 / 题材`(可多项, 没有写 `依据：无(理由)`)。" + WAKE_ASK.format(
            card="你是计划模式: 盘中**只有** band 出界或 wake 命中才会叫醒你(成交 / 心跳 / 市况翻转都不会), 所以失效条件要写全。" if self.mode == "plan" else "")
        a06 = self.fresh_block(at, P, state, strat, r4.get("json"), px) + "\n\n" + a06   # 10/22 晚用户令: 06 拍板前现取一次此刻盘口 / 竞价(01 是开跑时的快照, 04 想完已过 1~3 分钟)
        (vd / "06_fresh.md").write_text(a06.split("【06 终裁】")[0], encoding="utf-8")
        r6 = self._ask("06", a06, vd, T, lim)
        cost += r6["usd"]
        s = r6["json"] if isinstance(r6.get("json"), dict) and r6["json"].get("codes") is not None else None
        if s is None and r6["text"] and not self.fake:   # 写了但没出完整 json → 同会话让它立刻誊 json(不作废)
            rf = self._ask("06_finish", "你上一轮没有给出完整的最终 ```json 块。现在只做一件事: 按你上一轮已有的结论, 立刻输出最终 ```json(字段同上), 不要再分析。", vd, T, 90)
            cost += rf["usd"]
            s = rf["json"] if isinstance(rf.get("json"), dict) and rf["json"].get("codes") is not None else None
        if s is None:
            return fail(f"06 失败: {r6['err'] or '没有 json'}")
        miss = [r_["id"] for x in s.get("codes") or [] for r_ in x.get("rules") or [] if "依据" not in str(r_.get("why", ""))]
        if miss and not crit and not self.fake:
            re_ = self._ask("06_evidence", f"这些规则的 why 没写依据: {', '.join(miss)}。只回一个同格式的最终 ```json, 把它们的 why 末尾补上 `依据：…`, 其余内容不变。", vd, T, 90)
            cost += re_["usd"]
            if isinstance(re_.get("json"), dict) and re_["json"].get("codes") is not None:
                s = re_["json"]
                miss = [r_["id"] for x in s.get("codes") or [] for r_ in x.get("rules") or [] if "依据" not in str(r_.get("why", ""))]
        for x in s.get("codes") or []:
            for r_ in x.get("rules") or []:
                if r_["id"] in miss:
                    r_["why"] = f"{r_.get('why', '')} 依据：无(未补)"
        T.update(result="ok", total=round(time.time() - t0, 1), usd=round(cost, 4), no_evidence=miss)
        (vd / "timing.json").write_text(json.dumps(T, ensure_ascii=False, indent=1), encoding="utf-8")
        self.ev(kind="链耗时", secs=T["total"], usd=round(cost, 3), steps={k: v.get("secs") for k, v in T["steps"].items()}, result="ok", boot=T["boot"])
        return s, cost, T

    def close(self):
        super().close()
        f = self.dir / "summary.md"
        if f.exists():
            f.write_text(self._clean(f.read_text(encoding="utf-8")), encoding="utf-8")
        try:
            self.write_memory()
        except Exception as e:   # noqa: BLE001
            self.ev(kind="写本线记忆失败", err=repr(e)[:200])

    def write_memory(self, keep=10):
        """收盘写本线记忆(scripts/paper_v3/memory/<线>.md, 下一个交易日启动材料里的「本线记忆」): 开盘 / 收盘持仓、今日成交、最后一版的看法 / 下一步 / 失效条件;
        决策 T 线额外写"未完成的 T"(收盘股数和开盘不一样 = 隔夜正 T / 反 T 待处理; 10/23 凌晨用户: 允许隔日 / 隔几日的 T)。只留最近 keep 天"""
        md = MEMDIR
        md.mkdir(parents=True, exist_ok=True)
        f = md / f"{self.line['id']}.md"
        st0 = {c: int(p["qty"]) for c, p in ((self.state.get("start") or {}).get("positions") or {}).items()}
        st1 = {c: (int(p["qty"]), p.get("cost")) for c, p in (self.state.get("positions") or {}).items()}
        s = self.strategy or {}
        L = [f"## {self.D} 收盘", f"- 开盘持仓: {st0 or '空仓'}；收盘持仓: " + ("、".join(f"{c} {q} 股(成本 {cst:.3f})" for c, (q, cst) in st1.items() if cst) or "空仓") + f"；现金 {self.state['cash']:.0f}",
             "- 今日成交: " + ("；".join(f"{t['t']} {t['side']} {t['code']} {t['qty']}@{t['px']}" for t in self.state.get("trades") or []) or "无"),
             f"- 最后一版看法: {str(s.get('view') or '-')[:200]}", f"- 下一步: {str(s.get('next') or '-')[:200]}", f"- 失效条件: {str(s.get('invalid') or '-')[:200]}"]
        if self.line["kind"] == "dt":
            for c in set(st0) | set(st1):
                d = st1.get(c, (0, None))[0] - st0.get(c, 0)
                if st0 and d:
                    L.append(f"- **未完成的 T**: {c} 收盘比开盘{'多' if d > 0 else '少'} {abs(d)} 股 = 隔夜{'正' if d > 0 else '反'} T，{'等冲高卖出' if d > 0 else '等低位接回'}")
        old = f.read_text(encoding="utf-8").split("\n## ") if f.exists() else []
        blocks = [b if b.startswith("## ") else "## " + b for b in old if b.strip() and not b.startswith("# ")]
        blocks = [b for b in blocks if not b.startswith(f"## {self.D} ")][-(keep - 1):] + [chr(10).join(L)]
        f.write_text(f"# 本线记忆 {self.line['id']}(收盘自动写, 只留最近 {keep} 天)\n\n" + "\n\n".join(blocks) + "\n", encoding="utf-8")

    def _clean(self, msg):
        """10/22 用户令"影子"一词不用 + v3 目录名"""
        return (msg.replace("(影子链另 $0.00)", "").replace("影子链", "陪跑链").replace("影子账", "模拟账").replace("影子 vs 真实", "模拟账 vs 起点")
                .replace("策略执行器", "v3 执行器").replace(f"se_{self.key}", self.key))

    def wx(self, msg, alert=False):
        """10/23 00:5x 用户令: 今天芷影 / 刘忆青 / 土豆三本主线(盯盘)出现挂单就推微信(V3_PUSH_LINES, 按线号不按 skill —— 同一导师的计划模式 / 噪声 / 03 几本不推);
        新版策略只在"挂单真的变了"时推(同样的单重复出版不推, 省微信配额), 成交照推; 告警(alert)不受限"""
        msg = self._clean(msg)
        if self.fake:   # 桩测试不推微信(含告警)
            print("WX(桩)>", msg.replace(chr(10), " | ")[:200])
            return
        if not alert:
            push = {x.strip() for x in (X.flag("V3_PUSH_LINES", "") or "").split(",") if x.strip()}
            if self.line["id"] not in push:
                self.ev(kind="未推微信", msg=msg[:120])
                return
            if "执行器 v" in msg and "成交" not in msg.split("\n")[0]:
                sig = sorted((x["code"], r.get("side"), r.get("op"), r.get("px"), r.get("qty"), r.get("type")) for x in (self.strategy or {}).get("codes") or [] for r in x.get("rules") or [])
                key_ver = "开盘前首版" in msg or "竞价段" in msg   # 10/23 用户问: 盘前版和竞价版一定推(没挂单也推, 让你知道今天的计划)
                if not key_ver and (not sig or sig == getattr(self, "_wx_sig", None)):
                    self.ev(kind="未推微信", msg="挂单没变 / 没有挂单: " + msg[:80])
                    return
                self._wx_sig = sig
            msg = self._pretty(msg)
        else:
            msg = f"⚠️ [paper v3 · {self.line.get('name', self.line['id'])}] " + msg
        X.subprocess.Popen([str(X.PY), "-X", "utf8", "scripts/hermes/wx_send.py", msg[:3000], "--raw", "--src", f"v3_{self.line['id']}"] + (["--dry"] if self.dry else []),
                           cwd=ROOT, creationflags=X.NOWIN, stdout=X.subprocess.DEVNULL, stderr=X.subprocess.DEVNULL)

    def _pretty(self, msg):
        """10/23 01:3x 用户令: 推微信的挂单要手机 / 电脑微信都好读 —— 短行、不用表格、一张单一块; 版本消息按当前策略重排, 成交按最新一笔重排, 其余加线名抬头"""
        nm = self.line.get("name", self.line["id"])
        mode = {"watch": "盯盘", "plan": "计划"}.get(self.mode, "")
        head = msg.split("\n")[0]
        side_cn = {"BUY": "买", "SELL": "卖"}
        if "成交" in head and self.state.get("trades"):
            t = self.state["trades"][-1]
            pos = (self.state.get("positions") or {}).get(t["code"]) or {}
            return "\n".join([f"✅ {nm} 成交 {str(t.get('t'))[:5]}",
                              f"{side_cn.get(t['side'], t['side'])} {t.get('name') or ''} {t['code']}",
                              f"{t['qty']} 股 @ {t['px']}" + ("（开板接）" if "炸板接" in head else ""),
                              f"理由：{str(t.get('why') or '')[:60]}",
                              f"现持 {pos.get('qty', 0)} 股 · 现金 {self.state.get('cash', 0):,.0f}"])
        m = re.match(r"【.*?执行器 v(\d+) (\d\d:\d\d)】因: (.*)", head)
        if m and self.strategy:
            s = self.strategy
            L = [f"📋 {nm}（{mode}）第 {m.group(1)} 版 {m.group(2)}", f"触发：{m.group(3)[:40]}", f"看法：{str(s.get('view') or '')[:110]}", ""]
            n_rule = sum(len(x.get("rules") or []) for x in s.get("codes") or [])
            L.append(f"挂单 {n_rule} 张" if n_rule else "挂单：暂不挂（只设区间 / 叫醒条件）")
            for x in s.get("codes") or []:
                for r in x.get("rules") or []:
                    if r.get("type") == "board_dip":
                        how = f"开板时按卖二接，区间 {r.get('floor')}~{r['px']}"
                    elif r.get("auction"):
                        how = f"竞价 {'≤' if r['side'] == 'BUY' else '≥'}{r['px']}"
                    else:
                        how = f"{'≤' if r['side'] == 'BUY' else '≥'}{r['px']}" + ("（排队）" if r.get("rest") else "")
                    pf = ""
                    if r.get("type") != "board_dip" and not r.get("auction"):
                        try:
                            import fill_prob as FP
                            lo_, hi_ = getattr(self, "_dayhl", {}).get(x["code"], (None, None))
                            fr = FP.prob(x["code"], self.D, r["side"], float(r["px"]), lo_, hi_)
                            if not fr.get("err"):
                                pf = " · 今天到过" if fr.get("touched") else f" · 成交概率 {fr['p15']:.0%}" + (f"(此刻 {fr['now_px']:.0%})" if fr.get("now_px") is not None else "")
                        except Exception:   # noqa: BLE001
                            pass
                    L += [f"▪ {side_cn.get(r['side'], r['side'])} {x.get('name') or ''} {x['code']}", f"  {r['qty']} 股 · {how}{pf}" + (f" · 等 {r['after']} 成交后" if r.get("after") else ""),
                          f"  {str(r.get('why') or '')[:50]}"]
            bands = "；".join(f"{x.get('name') or x['code']} {x['band'][0]}~{x['band'][1]}" for x in s.get("codes") or [] if x.get("band"))
            if bands:
                L += ["", f"区间（出了会重想）：{bands[:150]}"]
            wk = []
            for c in s.get("wake") or []:
                if isinstance(c, dict):
                    wk.append(f"{c.get('at')} 时间止损" if c.get("type") == "time" else
                              f"{c.get('code')} {'≥' if c.get('op') == '>=' else '≤'}{c.get('px', c.get('pct'))}{'%' if c.get('type') == 'index' else ''}")
            if wk:
                L.append(f"叫醒条件：{'；'.join(wk)[:150]}")
            tail = re.search(r"本次 \$[\d.]+.*", msg)
            if tail:
                L.append(tail.group(0)[:60])
            return "\n".join(L)
        if "收盘" in head:
            return f"🔔 {nm} 收盘\n" + "\n".join(msg.split("\n")[0:]).split("】", 1)[-1].strip()
        return f"[paper v3 · {nm}] " + msg

    # ---------- 炸板接(10/22 晚用户教: T 字板开板时按卖二接, 回封就赚; 现场叫模型来不及, 由 06 预写、执行器每 3 秒机械判) ----------
    def _limit_up(self, c):
        if not hasattr(self, "_lim"):
            self._lim = {}
        if c not in self._lim:
            pc = X.prev_close(c, self.D)
            self._lim[c] = X.AR.limit_prices(c, self.D, pc)[0] if pc else None
        return self._lim[c]

    def tick(self, hm, auction=False):
        if not auction:   # 停牌保护(10/23 凌晨用户提醒: 纳指 ETF 溢价高时常临时停牌 09:30~10:30): 买一卖一同时为空 = 不可交易, 这一跳不撮合
            for c in [c for c, q_ in self.feed.q.items() if not (q_.get("b1") or 0) and not (q_.get("a1") or 0)]:
                self.feed.q.pop(c, None)
        for x in (self.strategy or {}).get("codes") or []:   # 排队单的队列推进: 价格停在挂单价期间的成交量累计 > 前面排队量 → 算排到
            q_ = self.feed.q.get(x["code"]) or {}
            v_, p_ = q_.get("v"), q_.get("p")
            for r in x.get("rules") or []:
                if not r.get("rest") or r.get("_queued_ok") or r.get("_ahead") is None or v_ is None or not p_:
                    continue
                if abs(p_ - r["px"]) < 1e-6 and r.get("_vlast") is not None:
                    r["_vol"] = (r.get("_vol") or 0) + max(0, int(v_) - int(r["_vlast"]))
                    if r["_vol"] > r["_ahead"]:
                        r["_queued_ok"] = True
                r["_vlast"] = v_
        sealed = getattr(self, "_sealed", set())
        for x in (self.strategy or {}).get("codes") or []:   # 记"今天封过涨停": 价 = 涨停价且卖一空
            q_ = self.feed.q.get(x["code"]) or {}
            up = self._limit_up(x["code"])
            if up and q_.get("p") and q_["p"] >= up - 1e-6 and not (q_.get("a1") or 0):
                sealed.add(x["code"])
        self._sealed = sealed
        fills = super().tick(hm, auction)
        if auction or hm < "09:30":
            return fills
        more = []
        with self.lock:
            s = self.strategy or {}
            for x in s.get("codes") or []:
                c = x["code"]
                for r in x.get("rules") or []:
                    key = f"{self.ver}:{c}:{r['id']}"
                    if r.get("type") != "board_dip" or key in self.fired or c not in sealed:
                        continue
                    q_ = self.feed.q.get(c) or {}
                    p_, a1 = q_.get("p"), q_.get("a1") or 0
                    if not p_ or not a1 or not (r["floor"] <= p_ <= r["px"]):   # 还封着(卖一空) / 不在接的区间 → 不动
                        continue
                    k = [lv for lv in (q_.get("k") or []) if lv and lv[0]]
                    px = float(k[1][0]) if len(k) > 1 else float(a1)   # 你的实盘习惯: 按卖二挂, 多付一档换成交
                    n = min(int(r["qty"]), X.AR.round_qty(c, (self.state["cash"] - max(5.0, self.state["cash"] * 0.0003)) / px))
                    self.fired.add(key)
                    if n <= 0:
                        self.ev(kind="炸板接命中但没钱", rule=key, p=p_)
                        continue
                    amt = px * n
                    fe = self.fee(c, "BUY", amt)
                    pos = self.state["positions"].setdefault(c, {"qty": 0, "cost": None, "sellable": 0})
                    pos["cost"] = ((pos["cost"] or 0) * pos["qty"] + amt + fe) / (pos["qty"] + n)
                    pos["qty"] += n
                    if X.AR.is_t0(c, x.get("name")):
                        pos["sellable"] += n
                    self.state["cash"] = round(self.state["cash"] - amt - fe, 2)
                    t = {"t": now().strftime("%H:%M:%S"), "code": c, "name": x.get("name"), "side": "BUY", "px": round(px, 3), "qty": n, "fee": fe, "rule": key,
                         "why": r.get("why"), "board_dip": True, "tape": {k_: q_.get(k_) for k_ in ("p", "t", "b", "k")}}
                    self.state["trades"].append({k_: v for k_, v in t.items() if k_ != "tape"})
                    with (self.dir / "actions.jsonl").open("a", encoding="utf-8") as f:
                        f.write(json.dumps(t, ensure_ascii=False) + chr(10))
                    more.append(t)
            if more:
                self._save()
        for t in more:
            self.wx(f"【{self.skill} 成交(炸板接) {t['t']}】BUY {t.get('name') or ''}{t['code']} {t['qty']}@{t['px']} 规则 {t['rule']} | 现金 {self.state['cash']:.0f}")
        return fills + more

    # ---------- 06 前现取此刻数据(零 token) ----------
    def stock_block(self, P, at, names):
        """候选池 / 持仓里的转债 → 正股此刻的竞价(09:15~09:25)或 3 秒盘口; 正股名单靠 collect_book 跟着转债自动录(转债在执行器策略里就会带上正股)"""
        import se_chain
        cbs = [c for c in list(P)[:30] if c.startswith(("11", "12"))]
        if not cbs:
            return ""
        if not hasattr(self, "_cb2stk"):
            self._cb2stk = {}
            try:
                import glob as _g
                fs = sorted(_g.glob(str(ROOT / "downloads" / "quotes" / "cb" / "meta" / "RPT_BOND_CB_LIST_all_*.json")))
                m = json.loads(Path(fs[-1]).read_text(encoding="utf-8")) if fs else []
                rows = m if isinstance(m, list) else ((m.get("result") or {}).get("data") or m.get("data") or [])
                self._cb2stk = {str(r.get("SECURITY_CODE")): (str(r.get("CONVERT_STOCK_CODE") or ""), str(r.get("SECURITY_SHORT_NAME") or r.get("CONVERT_STOCK_NAME") or "")) for r in rows}
            except Exception:   # noqa: BLE001
                pass
        auc = se_chain.auction_snap(self.D, at) if at < "09:31:00" else {}
        if at >= "09:25:00":
            self.feed.refresh([self._cb2stk.get(c, ("",))[0] for c in cbs])
        L = ["", "## 转债的正股此刻(脚本现取; 正股竞价 / 盘口取不到的写'无')", "| 转债 | 正股 | 名称 | 此刻 | 相对昨收 | 竞价匹配 / 未匹配买 / 卖 |", "|---|---|---|---|---|---|"]
        for c in cbs:
            sc, sn = self._cb2stk.get(c, ("", ""))
            if not sc:
                continue
            pc = X.prev_close(sc, self.D)
            a = auc.get(sc) or {}
            q = self.feed.q.get(sc) or {}
            px = a.get("px") or q.get("p")
            chg = f"{(px / pc - 1) * 100:+.2f}%" if px and pc else "-"
            aj = (f"{a.get('matched', '-')} / {a.get('unmatched_buy', '-')} / {a.get('unmatched_sell', '-')}" if a and not a.get("final") else ("已定" if a else "-"))
            L.append(f"| {c} {names.get(c, '')} | {sc} | {sn or names.get(sc, '')} | {px or '无'} | {chg} | {aj} |")
        return chr(10).join(L) if len(L) > 4 else ""

    def fresh_block(self, at0, P, state, strat, j4, px0):
        """竞价段(09:25:30 前) = 此刻竞价撮合价 / 匹配量 / 未匹配买卖 + 相对 01 那份(at0)的变化; 其余时段 = 此刻 3 秒盘口现价 / 买一 / 卖一 + 相对 01 的变化"""
        import se_chain
        t = now().strftime("%H:%M:%S")
        picks = [str(x.get("code")) for x in ((j4 or {}).get("picks") or []) if isinstance(x, dict) and x.get("code")]
        codes = list(dict.fromkeys([*state.get("positions", {}), *[x["code"] for x in (strat or {}).get("codes") or []], *picks, *list(P)[:10],
                                    *(self.line.get("universe") or [])]))[:20]
        names = se_chain.names(self.D)
        L = []
        if t < "09:25:30":
            cur, base = se_chain.auction_snap(self.D, t), se_chain.auction_snap(self.D, at0)
            L.append(f"## 此刻竞价({t} 脚本现取; 04 用的 01 是 {at0} 的快照)")
            L.append("用法: 只用来**校准竞价单价格 / 决定撤不撤**; 只有撮合价变化超过该票日振幅的一半, 或未匹配量方向翻转(买多卖少 ↔ 卖多买少), 才考虑推翻 04 的选票")
            L.append("| 代码 | 名称 | 此刻撮合价 | 相对 01 时 | 匹配量 | 未匹配买 | 未匹配卖 | 快照时刻 |")
            L.append("|---|---|---|---|---|---|---|---|")
            for c in codes:
                a = cur.get(c)
                if not a:
                    L.append(f"| {c} | {names.get(c, '')} | 无此刻数据, 以 01 为准 | - | - | - | - | - |")
                    continue
                b = base.get(c) or {}
                d = f"{(a['px'] / b['px'] - 1) * 100:+.2f}%" if b.get("px") else "-"
                L.append(f"| {c} | {names.get(c, '')} | {a['px']} | {d} | {a.get('matched', '-')} | {a.get('unmatched_buy', '-')} | {a.get('unmatched_sell', '-')} | {a.get('t', '')} |")
        else:
            self.feed.refresh(codes)
            L.append(f"## 此刻盘口({t} 脚本现取; 04 用的 01 是 {at0} 的快照)")
            L.append("用法: 只用来**校准挂单价格 / 决定撤不撤**; 只有价格变化超过该票日振幅的一半才考虑推翻 04 的选票(几分钟内的正常波动不改主意)")
            L.append("| 代码 | 名称 | 此刻价 | 相对 01 时 | 买一 | 卖一 | 盘口时刻 |")
            L.append("|---|---|---|---|---|---|---|")
            for c in codes:
                q_ = self.feed.q.get(c)
                if not q_:
                    L.append(f"| {c} | {names.get(c, '')} | 无此刻数据, 以 01 为准 | - | - | - | - |")
                    continue
                p0 = (px0 or {}).get(c)
                d = f"{(q_['p'] / p0 - 1) * 100:+.2f}%" if p0 else "-"
                L.append(f"| {c} | {names.get(c, '')} | {q_['p']} | {d} | {q_.get('b1', '-')} | {q_.get('a1', '-')} | {q_.get('t', '')} |")
        if not any("|" in x and "无此刻数据" not in x for x in L[4:]):
            L.append("(焦点票此刻都没有新数据, 按 01 的快照)")
        try:   # 10/23 01:4x 用户批: 挂单今天触及概率价梯(相对此刻价 ± 档; 每格 = 近 15 日口径 / 此刻口径), 客观数, 不要自己估
            import fill_prob as FP
            hl = getattr(self, "_dayhl", {})
            lad = []
            for c in codes[:10]:
                ref = (self.feed.q.get(c) or {}).get("p") or (px0 or {}).get(c)
                if ref:
                    lo_, hi_ = hl.get(c, (None, None))
                    lad.append(f"- {c} {names.get(c, '')}(参照价 {ref}): {FP.ladder(c, self.D, ref, lo_, hi_)}")
            if lad:
                L += ["", "## 挂在这里今天能成交的概率(脚本算; 近 15 日日线 + 今天已走出的高低点; '此刻'口径盘中越晚越高估)"] + lad
        except Exception as e:   # noqa: BLE001
            L.append(f"(触及概率算不出: {e!r})"[:120])
        return "\n".join(L)

    # ---------- 桩: 不调模型 ----------
    def _fake(self, rnd, text):
        time.sleep(0.2)
        if rnd != "06":
            return {"ok": True, "text": f"(桩 {rnd}) 收到 {len(text)} 字\n```json\n{{}}\n```", "json": {}, "secs": 0.2, "usd": 0.0, "usage": {}, "err": ""}
        c = (self.line.get("universe") or [None])[0] or next(iter(self.state["positions"]), None)
        if not c:
            m = re.search(r"\| 1 \| (\d{6}) \|", (self.dir / "versions").joinpath(sorted(p.name for p in (self.dir / "versions").iterdir())[-1], "01_facts.md").read_text(encoding="utf-8"))
            c = m.group(1) if m else "601988"
            self._pool = getattr(self, "_pool", set()) | {c}   # 桩: 没有事实包时候选池可能是空的, 让桩选的票合法
        p = (self.feed.q.get(c) or {}).get("p") or X.prev_close(c, self.D) or 10
        q = 10 if c.startswith(("11", "12")) else 100
        auc = now().strftime("%H:%M:%S") < "09:25:00"
        j = {"view": "桩", "codes": [{"code": c, "name": "", "band": [round(p * 0.97, 3), round(p * 1.03, 3)],
                                       "rules": [{"id": "r1", "side": "BUY", "op": "<=", "px": round(p * 1.002, 3), "qty": q, "auction": auc, "why": "桩 依据：无(桩)"}]}],
             "wake": [{"type": "time", "at": "10:30", "unless": {"type": "price", "code": c, "op": ">=", "px": round(p * 1.05, 3)}, "why": "桩时间止损"}],
             "next": "-", "invalid": "-", "rest_of_day": {"stop": False}, "mimic": "-", "valid_until": "15:00"}
        return {"ok": True, "text": "(桩 06)\n```json\n" + json.dumps(j, ensure_ascii=False) + "\n```", "json": j, "secs": 0.2, "usd": 0.0, "usage": {}, "err": ""}


def take_lock(line_id):
    """同一本账只许一个执行器: 锁文件存 pid; 持有者还活着且命令行是 executor.py --line 同线 → 拒绝启动(v2 的 take_lock 只认 se_exec.py)"""
    import psutil
    f = ROOT / "scripts" / "temp" / f"v3_{line_id}.lock"
    for _ in range(3):
        try:
            fd = os.open(str(f), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return f
        except FileExistsError:
            try:
                pid = int(f.read_text().strip() or 0)
                cmd = " ".join(psutil.Process(pid).cmdline())
                if pid != os.getpid() and "executor.py" in cmd and f"--line {line_id}" in cmd and "--boot-only" not in cmd:
                    sys.exit(f"v3 执行器 {line_id} 已在跑(pid {pid}), 本进程退出")
            except (ValueError, OSError, psutil.Error):
                pass
            f.unlink(missing_ok=True)
    sys.exit(f"抢不到锁 {f}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--line", required=True)
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--fake", action="store_true")
    ap.add_argument("--boot-only", action="store_true")
    a = ap.parse_args()
    L = lines()
    ln = L[a.line]
    idx = list(L).index(a.line)
    # v2 的全局开关按本进程覆盖(flag() 先读环境变量): 竞价复核 09:20:00、尾盘错峰、不走土豆竞价测试
    os.environ.update(SE_AUC_TEST_SKILLS="", SE_AUC_AT=X.flag("V3_AUC_AT", "09:20:00") or "09:20:00", SE_SHADOW_EFFORT="", SE_FLEET_VARIANTS="",
                      SE_TAIL_AT=(dt.datetime.strptime(X.flag("V3_TAIL_AT", "14:51:00") or "14:51:00", "%H:%M:%S") + dt.timedelta(seconds=8 * idx)).strftime("%H:%M:%S"),
                      SE_EFFORT=X.flag("V3_EFFORT", "high") or "high", SE_FIRST_EFFORT=X.flag("V3_EFFORT", "high") or "high", SE_AUC_EFFORT=X.flag("V3_EFFORT", "high") or "high")
    os.environ["SE_FULL_PAUSE"] = "0"   # 10/22 晚用户批: v3 满仓 / 06 判"今天不再操作"都不停触发(10/22 刘忆青 09:37 停触发, 错过真人 10:56 卖 + 13:06 换股)
    if ln["kind"] == "dt":
        os.environ["SE_HB_DYNAMIC"] = "0"   # 心跳按导师真人间隔算, 决策 T 线没有导师账本 → 固定 60 分钟
    first = (dt.datetime.strptime(X.flag("V3_FIRST", "09:00:00") or "09:00:00", "%H:%M:%S") + dt.timedelta(seconds=20 * idx)).strftime("%H:%M:%S")
    if a.boot_only:
        e = V3(ln, a.date, dry=False, fake=a.fake)
        e.refresh_facts()
        s, cost, T = e._chain("开盘前首版策略(彩排)")
        print(json.dumps({"ok": s is not None, "secs": T.get("total"), "usd": round(cost, 3), "steps": T.get("steps"), "pack": T.get("pack"), "result": T.get("result"),
                          "strategy": s}, ensure_ascii=False, indent=1))
        return
    lk = take_lock(a.line)
    try:
        V3(ln, a.date, dry=False, fake=a.fake).run(t_strategy=first)
    finally:
        try:
            if lk.read_text().strip() == str(os.getpid()):
                lk.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
