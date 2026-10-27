# -*- coding: utf-8 -*-
"""executor.py — paper v3 执行器(一本账一个进程; 10/22 晚建)

继承 v2 exec_base.SE: 3 秒盘口撮合 / 记账 / T+1 / 费用 / 09:25 竞价 / 15:00 尾盘竞价 / 触发判定 / 断点续跑 / nav 曲线 —— 这些 v2 跑过一整天, 原样复用
只换"叫模型"那一段(_chain): v2 = 直连 API 每次独立跑 01→06; v3 = 同一个 claude -p 会话(session.py, A2)里接着想
  09:00 启动: 第 1 条消息 = 材料包(pack.boot_msg) + 02 → 04 → 05 → 06(每轮一次 --resume)
  盘中触发: 01(脚本拼: 账户 / 开盘实况 / 指数 / 候选池 + 焦点票必查; 事实包没变不重发) + 04 → 05 → 06
  竞价段(09:15~09:25)触发: 04 → 06(跳过 05: 开盘前过度交易 / 当日亏损都为 0; 10/22 晚按 v2 耗时倒推)
  06 每条规则要写"依据："; 漏写 → 同会话追问补一次(竞价段 / 尾盘不追问), 补不上照用并标"依据：无(未补)"
两种模式(lines.json mode; 10/22 晚用户定名): watch = 盯盘模式(v2 触发全保留); plan = 计划模式(原"作战卡"), 只有出 band(失效)、失败重试、手动 KICK、固定时刻(09:20 竞价复核 / 14:51 尾盘)才叫醒
账本: results/_live/<D>/<live_skill | paper_线>/(state.json / strategies / versions / session.json / events.jsonl / curve.csv / nav.csv); 起点 = 前一交易日本线收盘状态, 没有 = 10 万空仓
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
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import line_dirs as LDS   # noqa: E402  10/25 账本目录命名(live_<skill> / paper_<id>)
V3 = ROOT / "scripts" / "paper_line"
sys.path[:0] = [str(V3), str(ROOT / "scripts" / "dfcf" / "paper"), str(ROOT / "scripts" / "chain"), str(ROOT / "scripts" / "lib")]
import mentors   # noqa: E402
import pack   # noqa: E402
import harness as H   # noqa: E402  (10/24: 03 一次调用 / 04 必填 + 内容闸 / 05 机械风控)
import exec_base as X   # noqa: E402
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
_B01 = threading.Lock()   # build_01 期间临时换 chain_steps.pool(决策 T 线只给本线标的) → 多本账同进程时串行


def dyn_cap(line, D):
    """自由触发上限(10/22 23:3x 用户令改回动态, 系数我定): ceil(k × 导师近 20 个交易日日均出手) 夹在 [下限, 上限]; 决策 T 线没有导师 = 固定值;
    计划模式 = 盯盘模式各拟人导师上限的平均(向上取整)
    出手 = 同一天同一只票同一方向算一次(同花顺逐笔腿); 开关 PAPER_CAP_K=5 / PAPER_CAP_MIN=6 / PAPER_CAP_MAX=20 / PAPER_CAP_DT=8"""
    import math
    k, lo, hi = float(_flag0("PAPER_CAP_K", "5") or 5), int(_flag0("PAPER_CAP_MIN", "6") or 6), int(_flag0("PAPER_CAP_MAX", "20") or 20)
    if line["kind"] == "dt":
        return int(_flag0("PAPER_CAP_DT", "8") or 8)
    if line.get("mode") == "plan":   # 10/22 23:4x 用户定: 计划模式 = 盯盘模式在跑的 tzzb 拟人线(按导师去重, 噪声基线不重复算)各自上限的平均, 向上取整
        seen, caps = set(), []
        for ln in pack.lines(D).values():
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
    PAPER_MAX_INFLIGHT=auto → 数: downloads/tzzb/<导师> 且 skills/<导师>-skill 存在 + skills 里 taoge / qushitiange / lubenyuan; 填数字 = 固定值"""
    v = (_flag0("PAPER_MAX_INFLIGHT", "auto") or "auto").strip()
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
PLAN_ASK = """

【实盘线 · 盘前计划表(这一版就是用户今天的计划)】codes 里每只票再加 "scenarios"(2~4 个, 覆盖竞价 / 开盘涨跌两头的主要走法), 每个:
{"id": "S1", "when": "机械条件", "action": "开盘买|等回落买|等信号买|不动|减仓|清仓", "rules": ["本情景下生效的规则 id"], "prob": {"ref": "E/Q 编号", "value": 0.42}, "invalid_if": "失效条件", "fear": "最怕什么(负样例只能写这里)"}
- when 只许用代码在 09:20 / 09:25 判得出的变量: 竞价涨幅 / 未匹配买 / 未匹配卖 / 上证开盘涨幅 / 国证2000开盘涨幅 / 一字 / 涨停价 / 昨收(数值比较 >= <= > < =, 用 且 / 或 连接; 例 "竞价涨幅 >= 3 且 未匹配买 > 未匹配卖")。写不成机械条件的情景就别写
- rules 列本情景下才生效的规则 id(空 [] = 这个情景不挂单); 没被任何情景列到的规则 = 所有情景都生效
- 09:20 / 09:25 代码判竞价落在哪个情景: 落上 → 只留该情景的规则, 不叫你; 一个都没落上(偏离计划)才叫你重想 —— 所以情景要覆盖全, 同一只票的情景之间不要重叠
- prob 只能引用必查 / ./q 里代码算好的数(写编号); 没有可引用的统计写 {"ref": null, "value": null, "why": "原因"}, 不许自己编
"""


WAKE_ASK = """
另在 json 里加 "wake": 结构化失效条件列表(执行器每 3 秒机械判, 命中就叫醒你重判; 文字版 invalid 照写给人看)。{card}每条一种:
  {{"type": "price", "code": "代码", "op": ">=|<=", "px": 价格, "why": "为什么到这就要重判"}}
  {{"type": "time", "at": "HH:MM", "unless": {{"type": "price", "code": "代码", "op": ">=", "px": 价格}}, "why": "时间止损: 到点还没达到 unless 就叫醒"}}
  {{"type": "index", "code": "sh000001|sz399006|sh000688|sz399303", "op": ">=|<=", "pct": 当日涨跌幅%, "why": "..."}}
  {{"type": "cond", "code": "代码", "ref": "涨停价|开盘价|昨收|跌停价|日内最高|日内最低|具体价格", "dir": "down|up", "pct": 2.0, "why": "..."}}   (10/25: 和条件单同一种写法, 命中只叫醒你重判、不自动下单; 例 "涨停价回落 2% 叫醒""从日内最高回落 3% 叫醒")
时间止损、指数转弱、关键价位破位都要写成 wake; 没有就写 "wake": []。时间止损只能写**将来**的时刻(已过去的会被执行器剔除); 价格 / 指数条件在你写下时就已成立的, 要等它先回到不成立(满 1 分钟)再成立才会叫醒你。
每张普通限价单的 why 里写"成交概率 x%"(取上面"挂在这里今天能成交的概率"或必查"触及概率"里最接近的那格, 不要自己估): ≥50% = 正常单; 30~50% = 写一句为什么不挂近一点; <30% = 预案单(如"等大跌才接"), 必须写清在等什么情景。成交概率只说"买不买得到 / 卖不卖得掉", 不说"该不该做"; 该不该做看导师规则和当下情景, 目的是这一单最后赚钱。每张单的 why 用一两句回答三件事(按导师的做法答, 不必套格式): ①目的: 建仓 / 加仓 / 打板接力 / 做T(正T 先买后卖、反T 先卖后买)/ 止盈 / 止损 / 换仓; ②怎么收尾: 买单打算在哪个价、什么时候卖(或接着拿, 拿到什么情况才走); 卖单是不是要接回、在哪接回, 不接回也写; ③最怕什么、为什么还做: 买单 = 买了继续跌(看振幅、关键价位、导师同状态亏损的案例); 卖单 = 卖飞(看必查里导师"卖后 3 日最高"、强势股次日冲高分布)、卖在成本下方是止损还是做T。**挂价先按导师规则 / 关键价位 / 情景定, 概率只用来检查"是不是根本够不着"; 不许为了凑高概率把单挪到现价附近**, 要挪价必须写出是哪条规则或盘面变化让你挪, 写不出就保持原价并标成预案单(决策T 线例外: 本线说明里"能成交优先、挂价贴近买一 / 卖一"照旧, 前提是价差够费用门槛)。
引用任何统计(强势股次日 / 相似日 / 同逻辑邻居 / 触及概率 / 回封)都要**同时写中位和最差情景**(必查里每条都给了 均值 / 中位 / P10 / 最差案例), 只写中位或只写好的一面会被内容闸打回(10/24 用户令)。
有先后顺序的单(先卖后买 / 先买后卖)用 "after": 例 买回单写 "after": "r1" = 只有 r1 成交之后这张才生效; 不写 after 的单价格碰到就成交, 不管先后。
炸板接单(可选, 少用): 只在**导师历史上真有"开板接 / 排板回封"做法**的票型上用, why 里要引用对应的规则或案例编号; 它只是补充, **不能代替导师当天会直接下的单**(导师多数是开盘后看盘直接分批买 / 卖, 照导师的节奏写普通限价单)。开板到回封常常只有 1 分钟, 叫醒你来不及, 所以要用就事先写好。**统计参考**(docs/research/board_reseal_20261023.md, 30 天关注票、置信低~中): 开板后跌到离涨停 −2% 时接, 之后能封回 49%、当天收盘中位 −0.4%、次日最高中位 +2.0%、次日收盘中位 −2.7%; 跌到 −5% 再接封回只有 21%; 开板 ≥5 分钟还没封回, 之后封回 58%、≥20 分钟 37% —— 整体是负期望, 只有导师有对应案例、且准备次日冲高就卖时才用。写法(放进该票 rules):
  {{"id": "r9", "side": "BUY", "op": "<=", "type": "board_dip", "px": 接的上沿(如涨停价 × 0.98), "floor": 接的下沿(如涨停价 × 0.93, 再低就不接), "qty": 股数, "why": "为什么判断会回封 依据：…"}}
  执行器只在 这只票今天封过涨停 → 现在开板(有卖单) → 价格落在 [floor, px] 时, 按此刻卖二价买一次; 一直封死或跌破 floor 都不买。
**两种单你自己选(10/25 用户令)**: ①限价单(上面的普通写法: 价格碰到 px 就成交) ②**条件单**(像人在券商 App 里挂的条件单: 某个参考价涨 / 回落到 x% 时, 按买 n / 卖 n 档的价一次成交), 适合"冲板失败就走""从高点回落 x% 卖(防卖飞)""从低点反弹 x% 买(防踏空)""跌破开盘价 x% 止损"这类你等不及被叫醒的情况:
  {{"id": "r5", "side": "SELL", "type": "cond", "ref": "涨停价|开盘价|昨收|跌停价|日内最高|日内最低|具体价格", "dir": "down|up", "pct": 2.0, "book": "b1|b2|a1|a2", "qty": 股数, "why": "… 依据：…"}}
  **全天守卫(10/25)**: 普通限价单的价格比现价差 ≥3%(卖单低于现价 / 买单高于现价 = 一碰就按市价成交)会被执行器自动改成条件单(卖 → 日内最高回落 0.8×振幅; 买 → 日内最低反弹 0.5×振幅); 真要立刻按市价成交的(止损清仓)在那条规则里写 "now": true。
  含义: 参考价 ref 涨(dir=up)≥ pct% 或 回落(dir=down)≥ pct% 时, 按 book 档价成交(卖用 b1 买一 / b2 买二, 买用 a1 卖一 / a2 卖二; 多让一档换成交)。
  "日内最高" = 这张单生效后的最高价(回落卖出 = 移动止盈), "日内最低" = 生效后的最低价(反弹买入); ref = 涨停价 / 日内最高 / 日内最低 时默认先要碰到参考价才开始算(arm), 别的参考价立刻生效, 要改写 "arm": true / false。
  例: 封板后开板回落就走 → {{"side": "SELL", "type": "cond", "ref": "涨停价", "dir": "down", "pct": 1.5, "book": "b1", "qty": …}};
      移动止盈防卖飞 → {{"side": "SELL", "type": "cond", "ref": "日内最高", "dir": "down", "pct": 0.8×本票振幅(夹在 1.5~6), "book": "b1", "qty": 剩余}};
      低吸防踏空 → {{"side": "BUY", "type": "cond", "ref": "日内最低", "dir": "up", "pct": 0.5×本票振幅, "book": "a1", "qty": …}}
  **参数参考(振幅 = 本票近 20 日日内振幅中位, 必查「振幅分布」有)**:
   涨停价回落 **1.5%~1.75%**(10/25 用户实盘经验, market-skill U7: 票越强、短线情绪越和它共振(题材在发酵 / 梯队完整 / 情绪上升段)越往 1.75% 放, 弱票 / 退潮 / 孤板用 1.5%; 1% 容易误杀炸板回封; 事件本体 n=2115: 开板深度 ≤2% 的 97% 会回封、收盘封住 73%, 2~4% 回封 66%, 4~7% 只 26% —— 浅开板多数会回封, 别一碰就走) · 日内最高回落 0.8×振幅(0.25~0.5 太紧) · 日内最低反弹 0.5×振幅(高振幅 >5.6% 的票用 0.8);
   开盘后急跌的票: 等反抽 / 分批卖能把卖飞从 48% 降到 10%、左尾 P10 从 −7.0% 收到 −2.6%(n=1332, 10 天), 均值和"一半立即卖一半收盘卖"差不多; 急跌后加硬止损反而亏(48% 被止损) —— 别在反抽前挂紧止损;
   **回封成功(开板后又封住到收盘)的票, 次日普遍有溢价高点**: 次日最高相对当日收盘 中位 首板 +5.9% / 二板 +6.8% / 三板+ +7.6%(P25 约 +3%, n=1824 / 320 / 170), 次日收盘中位只 +1.2%(P25 约 −3%) —— 拿过夜要计划次日冲高卖(用条件单: 次日 日内最高回落), 不是拿到次日收盘; 用户经验(U7): **低位**(相对当天最高连板, 暂定 ≤ 最高连板 × 0.4)二封次日溢价更明显; 这是全市场纯统计, 没分票的好坏(题材 / 梯队 / 资金), 好坏要你结合必查判断"""


STYLE_ASK = """
【意图(10/26 晚用户批, 首选这样写)】你只决定 卖不卖 / 买不买 / 多少 / 多急, **怎么挂由执行器在落单那一刻按盘面选**:
  {"id": "r1", "intent": "必须走|想走|冲高卖|低吸|打板|必须买", "ratio": 0.5, "why": "… 依据：…"}   (ratio: 卖 = 占持仓比例, 买 = 占总资产比例)
  选型表(落单那一刻的盘面 → 挂法; 离线 10 天 n=1332 验证, docs/research/bracket_offline_20261026.md):
   必须走 → 立即按买一卖(逻辑破坏 / 止损) · 必须买 → 立即按卖一买 · 打板 → 排板(涨停价排队)
   想走 / 冲高卖: 封着涨停 → 炸板走 · 急跌中(开盘后跌 ≥3% 或从日内高点回落 ≥max(3%, 0.6×振幅)) → 一半等反抽(日内最低反弹 0.8×振幅卖, 60 分钟没反抽到点卖) + 一半移动止盈(日内最高回落 0.8×振幅)
                  已经在冲高(贴着日内高点、在开盘价和昨收上方) → 一半挂高(规则价) + 一半移动止盈 · 平稳 → 现价卖(追价)
                  开盘 5 分钟内: 低于昨收开盘(水下, 例 百洋股份 10/26 竞价跌停被抢上来) → 全部移动止盈、不在第一波砸; 平开 / 高开 → 现价卖 · 盘前 → 移动止盈 · **不挂硬止损**(急跌后止损一半样本会被止损在低点)
   低吸 → 一半低吸限价 + 一半防踏空(日内最低反弹 max(1.5%, 0.5×振幅) 追买; 低吸那半成交了就不追)
   **浮亏的持仓票盘中补仓**(10/26 用户原则, market-skill U24: 越跌越补是教训): 执行器一律改成"等反转(日内最低反弹 max(1.5%, 0.5×振幅))才买, 14:50 还没反转就尾盘补"; 要立刻补必须写 "now": true 或引规则编号
  要推翻选型表(导师本人的特定卖法 / 关键价位): 照旧写 style 或 px + "人工价": true, **why 里必须引规则或材料编号**(R / E / Q / U / KS …); 没引编号的 style 按选型表执行(你写的 style 留档), 每晚复盘对比推翻 vs 选型表谁更好。

【选挂法(旧写法, 推翻选型表时用)】每条规则可以**不写 px / qty**, 改写:
  {"id": "r1", "side": "BUY|SELL", "style": "追价|低吸|挂高|排板|开盘|等反抽|移动止盈|防踏空|炸板走|立即", "ratio": 0.3, "strength": "强|中|弱", "why": "… 依据：…"}
  ratio = 卖出占这只票持仓的比例(1 = 全卖) / 买入占总资产的比例; 价格由执行器在落单那一刻按当时盘口算:
  追价 = 现价 ±0.2%(笼子内) · 低吸 / 挂高 = 现价(盘前用昨收)×(1 ∓ k×本票 30 日振幅), k = 导师自己被动挂单的去偏深度 · 排板 = 涨停价 · 开盘 = 竞价单(买保证成交 / 卖按跌停价挂保证卖掉) ·
  等反抽 / 移动止盈 = 条件单: 日内最高回落 0.8×振幅卖 · 防踏空 = 条件单: 日内最低反弹 0.5×振幅买 · 炸板走 = 条件单: 涨停价回落 1.5%(strength 强 = 1.75%) · 立即 = 按买一 / 卖一立刻成交(止损清仓用)
  低吸 / 挂高 / 追价 挂出一段时间(导师被动单存续时间, 默认 30 / 30 / 5 分钟)没成交会叫醒你重判。
  区间也可以不写数字, 写 "band_w": "宽|中|窄"(= 此刻现价 ± 1.0 / 0.6 / 0.35 × 振幅, 代码再乘时段系数(开盘 30 分钟 ×1.5 → 尾盘 ×0.7)和当日波动比, 持仓票下沿紧上沿松、空仓票反过来)。
  你确实要指定价格(关键价位 / 箱体上沿 …)就照旧写 px 并加 "人工价": true, why 里写清是哪个价位、哪条规则; 没写"人工价"的 px 只留档对比, 执行按规则价。"""


def now():
    return X.now()


def inc_on():
    """10/25 用户认可: 叫醒消息只发增量(事实包小节去重 + 候选池只列变化行); PAPER_INC=0 回到全量"""
    return (X.flag("PAPER_INC", "1") or "1").strip() == "1"


def critical(at):
    return any(a <= at < b for a, b in CRIT)


def lines(D=None):
    return pack.lines(D)


class V3(X.SE):
    def __init__(self, line, D, dry=False, fake=False):
        self.line, self.mode, self.fake = line, line["mode"], fake
        base = LIVE / D / LDS.ldir(line["id"])
        super().__init__(line["skill"], D, dry, base=base, cap=dyn_cap(line, D))
        self.key = LDS.ldir(line["id"])
        if fake:
            self.facts_build = False   # 桩测试不现做事实包(facts.mjs 会打外部行情源; 10/22 晚桩测试多打了几次)
        self.sess = Session(line["id"], D, base, effort=X.flag("PAPER_EFFORT", "high") or "high")
        self.facts_sent = None

    # ---------- 账本起点: 接本线前一交易日收盘, 否则 10 万空仓 ----------
    def _init_state(self):
        own = self.line.get("skill") in {x.strip() for x in (X.flag("LIVE_OWN_BOOK", "buchitudou0") or "").split(",") if x.strip()}
        rs = pack.real_start(self.D) if self.line.get("live") and not own and (X.flag("LIVE_REAL_START", "1") or "1") == "1" else None   # 10/25 用户: 土豆只做转债 → 不跟你的持仓, 自己的账接着跑(LIVE_OWN_BOOK)
        if rs:   # 10/25 用户令: live line 每天从用户真实持仓 + 仓位分布起步(去掉中国银行); 隐私: state.json 在 results(gitignore)
            pos = {c: {"qty": int(q["qty"]), "cost": q.get("cost"), "sellable": int(q["qty"]), "days": 1} for c, q in rs["positions"].items()}
            cash, scaled = rs["cash"], None
            if (X.flag("LIVE_SCALE_TO_MENTOR", "1") or "1") == "1" and self.line.get("kind") == "mimic" and self.line.get("role") != "UP" and pos:
                # 10/25 晚用户令: 持仓结构照你的、总仓位等比例缩放到导师 T−1 收盘仓位(10/23 回放: 你约 80% → 芷影走"仓位 ≥50% 只卖", 真人 46% 走低吸; 防仓位不同造成的歧义)
                try:
                    mp = pack.mentor_pos_pct(self.skill, self.D)
                    px_ = {c: float(X.prev_close(c, self.D) or q.get("cost") or 0) for c, q in pos.items()}
                    val = sum(q["qty"] * px_[c] for c, q in pos.items())
                    tot = cash + val
                    if mp and tot > 0 and val > 0:
                        k = mp[0] * tot / val
                        for c, q in pos.items():
                            q["qty"] = q["sellable"] = int(X.AR.round_qty(c, q["qty"] * k)) if k < 1 else int(q["qty"] * k // 100 * 100)
                        val2 = sum(q["qty"] * px_[c] for c, q in pos.items())
                        if val2 > tot:   # 放大时不能超过总资产
                            val2 = val
                        cash = round(tot - val2, 2)
                        pos = {c: q for c, q in pos.items() if q["qty"] > 0}
                        scaled = {"user_pct": round(val / tot, 4), "mentor_pct": round(mp[0], 4), "why": mp[1], "k": round(k, 4), "nav": round(tot, 2)}
                except Exception as e:   # noqa: BLE001  缩放失败 → 照你的真实仓位, 不拦启动
                    scaled = {"err": repr(e)[:200]}
            st = {"cash": cash, "positions": pos, "trades": [], "start": {"cash": cash, "positions": json.loads(json.dumps(pos)), "from": f"real:{rs['from']}",
                                                                          "at": now().isoformat(timespec="seconds"), **({"scaled": scaled} if scaled else {})}}
            if scaled:
                self.ev(kind="起点仓位缩放到导师", **scaled)
            self._save(st)
            return st
        prev = sorted(p for p in LIVE.glob(f"20*/{LDS.ldir(self.line['id'])}/state.json") if p.parent.parent.name < self.D)
        if prev:
            ps = X.jl(prev[-1], {}) or {}
            pos = {c: {"qty": int(q["qty"]), "cost": q.get("cost"), "sellable": int(q["qty"]), "days": int(q.get("days") or 0) + 1}
                   for c, q in (ps.get("positions") or {}).items() if int(q.get("qty") or 0) > 0}
            cash, frm = round(float(ps.get("cash") or 0), 2), f"carry:{prev[-1].parent.parent.name}"
        else:
            pos, cash, frm = {}, float(self.line.get("cash") or INIT_CASH), "genesis"   # 决策T 两本只给 1 万(10/22 深夜用户定, 和旧决策T 同口径好对照)
            if own:   # 自己跑的 live 线第一天: 本钱 = 你的总资产(持仓按成本 + 现金), 全部现金起步, 和其他线规模可比
                rs0 = pack.real_start(self.D)
                if rs0:
                    cash = round(rs0["cash"] + sum(q["qty"] * (q.get("cost") or 0) for q in rs0["positions"].values()), 2)
                    frm = "own:genesis"
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
        import facts_pack   # 决策 T 线没有导师小节: 直接用当天共享事实包全文(市况 / 外围 / 资讯参考)
        cur = facts_pack.latest(self.D)
        if cur:
            (self.dir / "facts.txt").write_text(cur.read_text(encoding="utf-8"), encoding="utf-8")
        self.ev(kind="事实包", src=str(cur) if cur else None)
        return {"ok": bool(cur)}

    def facts_codes(self):
        return super().facts_codes() | getattr(self, "_pool", set()) | set(self.line.get("universe") or [])

    def _seal_map(self):
        out = {}
        for c, q_ in list(self.feed.q.items()):
            up, p_ = self._limit_up(c), q_.get("p")
            if up and p_:
                out[c] = p_ >= up - 0.005 and not (q_.get("a1") or 0)
        return out

    def _seal_changed(self, s):
        """10/26 用户批(林州重机): 06 落单前机械复核盘面 —— 06 看盘口时封着、落单时已开板(或反过来)的票, 打板 / 排板买单不落, 排队重判(零 token)"""
        fresh, bad = getattr(self, "_fresh_seal", None), []
        if not fresh or not self.line.get("live"):
            return bad
        now_ = self._seal_map()
        for x in (s or {}).get("codes") or []:
            c = x["code"]
            if c not in fresh or c not in now_ or fresh[c] == now_[c]:
                continue
            up = self._limit_up(c)
            keep = []
            for r in x.get("rules") or []:
                boardy = r.get("side") == "BUY" and (r.get("style") == "排板" or (up and r.get("px") and float(r["px"]) >= up - 0.005))
                if boardy:
                    bad.append(f"{c} {r.get('id')} 06 看盘口时{'封板' if fresh[c] else '没封'}, 落单时已{'开板' if fresh[c] else '封板'} → 这张打板单不落, 重判")
                else:
                    keep.append(r)
            x["rules"] = keep
        if bad:
            with self.lock:
                rr = "盘面变了重判: " + "; ".join(bad)[:200]
                self.queued = f"{self.queued}; {rr}" if self.queued else rr
                self.queued_counted = False
        return bad

    def check(self, s):
        self._autofix = []
        bad_seal = self._seal_changed(s)
        bad_style = self._style_prep(s) + bad_seal
        bad_cond = self._cond_prep(s)
        s, dropped = super().check(s)
        dropped += bad_style + bad_cond
        # 10/26 晚 selftest ⑮: 落单时已经封死涨停的 涨停价买单 = 真排队(开板时按涨停价成交), 守卫不能再把它改成"到涨停价才买"的条件单
        qs = self.__dict__.setdefault("_qsealed", {})
        sm = self._seal_map()
        for x in (s or {}).get("codes") or []:
            up = self._limit_up(x["code"])
            for r in x.get("rules") or []:
                if r.get("side") == "BUY" and r.get("px") and up and float(r["px"]) >= up - 0.005:
                    qs[(x["code"], r.get("id"), float(r["px"]))] = bool(sm.get(x["code"]))
        if self._autofix:   # 10/25 少重写 ②: 代码自动修过的机械错误记一笔(不叫模型重写)
            self.ev(kind="06 自动修", n=len(self._autofix), items=self._autofix[:20])
        # 10/23 凌晨彩排查出: 新版把同一张单(同票同方向同价)原样保留时, 真实柜台里这张单一直挂着、排队位置不变; 原来每出新版都当新单重新排到队尾 → 中行 7.17 那张因此没排到
        old_q = {(x["code"], r["side"], r.get("px")): r for x in (self.strategy or {}).get("codes") or [] for r in x.get("rules") or []
                 if r.get("rest") and f"{self.ver}:{x['code']}:{r['id']}" not in self.fired}
        for x in s.get("codes") or []:   # 标"排队单": 落地这一刻不能立刻成交(买: 卖一空或卖一 > 买价; 卖: 买一空或买一 < 卖价) → 将来被穿过时按挂单价成交
            q_ = self.feed.q.get(x["code"]) or {}   # 例 星光 10/22: 2.70 排板时封死、卖一空 → 排队单; 09:40 开板砸到 2.58 → 按 2.70 成交
            a1, b1 = q_.get("a1") or 0, q_.get("b1") or 0
            for r in x.get("rules") or []:
                r["rest"] = not (a1 and a1 <= r["px"]) if r["side"] == "BUY" else not (b1 and b1 >= r["px"])
                if r["rest"] and not r.get("auction") and now().strftime("%H:%M:%S") < "09:30:00" and str(q_.get("t") or "")[:8] < "09:30:00":
                    # 10/25 回放抓到: 09:20 竞价虚拟价 8.83(跌停)时挂的卖 9.00, 09:30 开在 10.09 → 原来按"排队单"在 9.00 成交(少算 11%);
                    # 开盘前落地的非竞价单 09:30 才生效, 那一刻能成交就按当时盘口成交, 不按竞价时的虚拟价判排队
                    r["rest"], r["_pre_open"] = False, True
                prev = old_q.get((x["code"], r["side"], r.get("px")))
                if r["rest"] and prev is not None:   # 同一张单原样保留 → 沿用原来的排队位置和已推进的成交量
                    r.update({k: prev.get(k) for k in ("_ahead", "_vol", "_vlast", "_queued_ok")})
                elif r["rest"]:   # 排队: 挂单时这个价位上排在前面的量(五档里找得到才算; 找不到 = 看不到队列, 只认穿价)
                    lv = q_.get("b") if r["side"] == "BUY" else q_.get("k")
                    ahead = next((int(b_) for a_, b_ in (lv or []) if a_ and abs(float(a_) - r["px"]) < 1e-6), None)
                    better = (r["side"] == "BUY" and b1 and r["px"] > b1) or (r["side"] == "SELL" and a1 and r["px"] < a1)   # 挂在买一卖一之间 = 新价位, 前面没人
                    r["_ahead"] = 0 if better else ahead
                    r["_vol"], r["_vlast"], r["_queued_ok"] = 0, q_.get("v"), False
                r["depth"] = True   # 立刻成交的单按五档吃单算价(exec_base.depth_fill)
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
        try:   # 10/24 用户令: 06 写到被财联社加红电报点名的票, why 里必须带 "HH:MM:SS CLS电报点名 + 链接" —— 代码补(不叫模型重写), 只认此刻之前发出的电报
            tl = pack.telegraph_links(self.D, now().strftime("%H:%M:%S"))
            for x in s.get("codes") or []:
                hit = tl.get(str(x.get("code")))
                if not hit:
                    continue
                note = "；".join(f"{t} CLS电报点名 {u}" for t, u, _ in hit[-2:])
                for r in x.get("rules") or []:
                    if "CLS电报点名" not in str(r.get("why") or ""):
                        r["why"] = f"{r.get('why') or ''}【{note}】"
        except Exception as e:   # noqa: BLE001
            self.ev(kind="电报备注失败", err=repr(e)[:200])
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
        if c.get("type") == "cond":   # 10/25 用户: 叫醒条件也用条件单的写法(参考价涨 / 回落 x%), 命中只叫醒不下单
            code = str(c.get("code"))
            p_ = (self.feed.q.get(code) or {}).get("p")
            if not p_:
                return False
            c["_hi"] = max(c.get("_hi") or p_, p_)
            c["_lo"] = min(c.get("_lo") or p_, p_)
            ref = self._cond_ref(code, c.get("ref"), c)
            if not ref:
                return False
            pct = float(c.get("pct") or 0) / 100
            if c.get("arm", c.get("ref") in ("涨停价",)) and not c.get("_armed"):
                if (c.get("dir") == "down" and p_ >= ref - 1e-6) or (c.get("dir") == "up" and p_ <= ref + 1e-6):
                    c["_armed"] = True
                return False
            return p_ >= ref * (1 + pct) - 1e-9 if c.get("dir") == "up" else p_ <= ref * (1 - pct) + 1e-9
        return False

    def wake_hits(self, hm):
        """10/22 23:4x 回放桩测出死循环(芷影 11:11 前叫醒 416 次): 命中后新版策略原样写回同一条 → 立刻又命中, 叫醒不占上限会一直烧 token
        修: 时间类按时刻每天只响一次(不分版本; check 另把已过去的时刻剔掉); 价格 / 指数类只在"不成立 → 成立"时响:
            条件要先连续不成立满 PAPER_BAND_HOLD_S 秒(默认 60, 同出区间去抖)才"上膛", 上膛后一成立就响(每版每条一次)
            → 新版写进来时已成立的不响; 在价位附近来回抖也不会反复响
            10/23 01:2x 用户令改动态(验证见 results/inv-stock/test/cooldown_validate.md): 价格类"上膛" = 价格退到价位另一侧 ≥ max(2 个最小价位, PAPER_WAKE_R × σ)
            并待满 30 秒(噪声比固定 60 秒少 78%); 指数类、σ 取不到的票仍用"不成立满 PAPER_BAND_HOLD_S 秒"; 箱体规则验证无额外好处, 不用"""
        out = []
        fired = getattr(self, "_wake_fired", set())
        armed = getattr(self, "_wake_armed", set())
        since = getattr(self, "_wake_false_since", {})
        hold = float(X.flag("PAPER_BAND_HOLD_S", "60") or 0)
        dyn = X.flag("PAPER_SIGMA_DYNAMIC", "1") == "1"
        rk = float(X.flag("PAPER_WAKE_R", "0.25") or 0)
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
        10/23 01:2x 用户令改动态(零 token 验证 results/inv-stock/test/cooldown_validate.md 定系数): 越过边沿 ≥ PAPER_BAND_M × σ 才开始计时,
        持续 H = clamp(PAPER_BAND_BASE × σ% / 3%, 30, 180) 秒才算出区间; σ 取不到 → 退回固定 PAPER_BAND_HOLD_S 秒"""
        s = self.strategy
        if not s:
            return s
        hold = float(X.flag("PAPER_BAND_HOLD_S", "60") or 0)
        dyn = X.flag("PAPER_SIGMA_DYNAMIC", "1") == "1"
        mk, base = float(X.flag("PAPER_BAND_M", "0.1") or 0), float(X.flag("PAPER_BAND_BASE", "15") or 15)
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

    # ---------- 实盘线(10/24 用户定): 盘前全跑, 09:19 起只有留下的线(keep)叫模型; 没留下的 = 休眠(不叫模型 / 不保温, 已挂的单照样机械撮合), 随时可加回 ----------
    def dormant(self):
        if not self.line.get("live") or now().strftime("%H:%M:%S") < (X.flag("LIVE_KEEP_AT", "09:19:00") or "09:19:00"):
            return False
        stop_at = {k.strip(): v.strip() for k, _, v in (x.partition("@") for x in (X.flag("LIVE_STOP_AFTER", "buchitudou0@10:00:00") or "").split(",")) if k.strip()}
        if self.line.get("skill") in stop_at and now().strftime("%H:%M:%S") >= stop_at[self.line["skill"]]:   # 10/25 用户: 土豆只有开盘段的规则, 10:00 后不再叫醒(已挂的单照样机械撮合)
            if not getattr(self, "_stop_logged", False):
                self._stop_logged = True
                self.ev(kind="定时停(不再叫模型)", at=stop_at[self.line["skill"]])
            return True
        t = time.time()
        if t - getattr(self, "_keep_t", 0) > 5:   # 5 秒读一次留下名单(keep.py 随时改)
            self._keep_t = t
            try:
                self._keep = pack.keep_of(self.D)
            except Exception as e:   # noqa: BLE001  读不到名单 → 不休眠(宁可多花钱, 不让留下的线停掉)
                self.ev(kind="读留下名单失败", err=repr(e)[:200])
                self._keep = None
        d = self._keep is not None and self.skill not in self._keep
        if d != getattr(self, "_dormant_logged", None):
            self._dormant_logged = d
            try:
                why = pack.keep_why(self.D, self.skill)
            except Exception as e:   # noqa: BLE001
                why = f"原因没读到: {e!r}"[:200]
            # 10/25: why = 谁 / 几点改的名单(scripts/live/line_periods.py 拼成"叫模型时段", 晚上核销 + C 方案"部分时段"用)
            self.ev(kind="休眠(没留下, 不叫模型)" if d else "留下(叫模型)", keep=sorted(self._keep or []), why=why)
        return d

    # ---------- 实盘线竞价对照(10/24 模块 7): 09:20 / 09:25 代码判竞价落在计划哪个情景; 落上 = 只留该情景的规则、不叫模型; 偏离才叫 ----------
    def _scen_vars(self, code):
        q = self.feed.q.get(code) or {}
        pc = X.prev_close(code, self.D)
        V = {}
        if pc and q.get("p"):
            V["竞价涨幅"] = V["开盘涨幅"] = (q["p"] / pc - 1) * 100
            V["昨收"] = pc
            up = self._limit_up(code)
            if up:
                V["涨停价"] = up
                V["一字"] = V["一字板"] = float(q["p"] >= up - 1e-6)
        b, k = q.get("b") or [], q.get("k") or []   # 竞价段口径(auction_path): 买二量 = 未匹配买, 卖二量 = 未匹配卖
        if len(b) > 1 and len(k) > 1:
            V["未匹配买"], V["未匹配卖"] = float(b[1][1] or 0), float(k[1][1] or 0)
        for nm, sym in (("上证", "sh000001"), ("国证2000", "sz399303")):
            v = (self.idx_now() or {}).get(sym)
            if v and v[0] and v[1]:
                V[f"{nm}开盘涨幅"] = (v[0] / v[1] - 1) * 100
        return V

    def scen_compare(self, stage):
        """→ (偏离清单, 落上清单); 有情景的票: 落上 → 本情景 rules 生效、其他情景独有的 rules 停用(记进 fired; 换情景时恢复); 都没落上 / 判不了 → 偏离"""
        s = self.strategy or {}
        if not any(x.get("scenarios") for x in s.get("codes") or []):
            return None, []
        sys.path.insert(0, str(ROOT / "scripts" / "live"))
        import plan_review as PR
        dev, hit = [], []
        off = getattr(self, "_scen_off", set())
        with self.lock:
            for x in s.get("codes") or []:
                sc = [y for y in x.get("scenarios") or [] if isinstance(y, dict)]
                if not sc:
                    continue
                c, V = x["code"], self._scen_vars(x["code"])
                m, why = None, []
                for y in sc:
                    ok, w = PR.eval_when(str(y.get("when") or ""), V)
                    if ok:
                        m = y
                        break
                    if ok is None:
                        why.append(f"{y.get('id')}: {w}")
                scoped = {str(i) for y in sc for i in (y.get("rules") or [])}
                live_ids = {str(i) for i in (m.get("rules") or [])} if m else set()
                for r in x.get("rules") or []:
                    key = f"{self.ver}:{c}:{r['id']}"
                    if str(r["id"]) in scoped and str(r["id"]) not in live_ids and m:
                        if key not in self.fired:
                            self.fired.add(key)
                            off.add(key)
                    elif key in off:   # 换了情景: 之前停用的恢复
                        self.fired.discard(key)
                        off.discard(key)
                vs = {k_: round(v_, 2) for k_, v_ in V.items() if k_ in ("竞价涨幅", "未匹配买", "未匹配卖", "上证开盘涨幅", "国证2000开盘涨幅")}
                if m:
                    hit.append(f"{x.get('name') or ''}{c} 落在 {m.get('id')}「{m.get('when')}」→ {m.get('action')}")
                else:
                    dev.append(f"{x.get('name') or ''}{c} 竞价 {vs} 不在计划任何情景" + (f"(判不了: {'; '.join(why)[:120]})" if why else ""))
        self._scen_off = off
        self.ev(kind="竞价对照", stage=stage, hit=hit, dev=dev, off=sorted(off))
        return dev, hit

    # ---------- 计划模式: 只有计划失效(出 band / wake 命中)才叫醒 ----------
    def restrategize(self, why, counted=True, effort=None, tag=None):
        if self.dormant() and not why.startswith("开盘前首版"):
            return
        if tag == "auction" and self.line.get("live") and not self.pending:   # 模块 7: 09:20 竞价复核 → 先代码对照计划情景
            dev, hit = self.scen_compare("09:20")
            skip = (X.flag("LIVE_AUC_SKIP", "0") or "0") == "1"   # 10/25 用户: 漏叫一次的代价 > 多叫一次 → 默认同 paper v3(09:20 照样叫模型, 对照结果附在叫醒原因里); =1 才是"全落在情景内就不叫"
            if skip and dev is not None and not dev:
                with self.lock:
                    if self.strategy and not self.strategy.get("auc_submitted"):
                        self.strategy["auc_submitted"] = now().strftime("%H:%M:%S")   # 计划里的竞价单照挂
                return
            if dev:
                why = f"{why}; 竞价对照偏离计划: {'; '.join(dev)[:300]}"
            elif hit:
                why = f"{why}; 竞价对照: 全部落在计划情景内({'; '.join(hit)[:300]})"
        if tag == "auction" and self.line["kind"] == "dt":   # 10/22 晚: 银行 / 纳指 ETF 不靠竞价单, 竞价复核让给拟人线(并发队列里少排 2 个)
            self.ev(kind="决策T 不做竞价复核", why=why)
            return
        fill_ok = bool(self.line.get("wake_on_fill")) and re.match(r"^(\(排队补叫\) )?(本链成交|竞价成交)", why)   # 10/23 凌晨用户定: 计划模式另开一本"成交叫醒"做对照
        if self.mode == "plan" and not fill_ok and re.match(r"^(\(排队补叫\) )?(本链成交|竞价成交|心跳)", why):
            self.ev(kind="计划模式不唤醒", why=why)
            return
        if counted and now().strftime("%H:%M") < (X.flag("PAPER_CAP_FROM", "10:30") or "10:30"):
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

    def last_chain_at(self):
        """10/25 用户: 尾盘闸动态化 —— 14:57~15:00 是尾盘集合竞价, 15:00 前出的单都能进尾盘竞价撮合;
        最晚开链时刻 = PAPER_CLOSE_DEADLINE(默认 14:59:45) − 本线今天链耗时 P90(没有就按最近几天, 再没有 300 秒) − 30 秒余量; 夹在 14:45~14:57; 返回 HH:MM"""
        if "--fixed" in (X.flag("PAPER_LAST_CHAIN", "auto") or "auto"):
            return X.flag("EXEC_LAST_CHAIN", "14:51")
        if getattr(self, "_lc_cache", (None, None))[0] == now().strftime("%H:%M"):
            return self._lc_cache[1]
        secs = [float(e.get("secs") or 0) for e in self._events() if e.get("kind") == "链耗时" and not e.get("boot") and e.get("secs")]
        if len(secs) < 3:   # 今天样本不够 → 最近几天同一条线
            for f in sorted(LIVE.glob(f"20*/{LDS.ldir(self.line['id'])}/events.jsonl"))[-4:-1]:
                for l in f.read_text(encoding="utf-8").splitlines():
                    try:
                        e = json.loads(l)
                    except ValueError:
                        continue
                    if e.get("kind") == "链耗时" and not e.get("boot") and e.get("secs"):
                        secs.append(float(e["secs"]))
        secs.sort()
        p90 = secs[min(len(secs) - 1, int(len(secs) * 0.9))] if secs else 300.0
        dl = dt.datetime.strptime(X.flag("PAPER_CLOSE_DEADLINE", "14:59:45") or "14:59:45", "%H:%M:%S")
        t = (dl - dt.timedelta(seconds=p90 + 30)).strftime("%H:%M")
        t = min(max(t, "14:45"), "14:57")
        self._lc_cache = (now().strftime("%H:%M"), t)
        if t != getattr(self, "_lc_logged", None):
            self._lc_logged = t
            self.ev(kind="尾盘最晚开链", at=t, p90_secs=round(p90), n=len(secs))
        return t

    def need_re(self, hm, fills):
        _TL.ov = dict(getattr(_TL, "ov", None) or {})
        _TL.ov["EXEC_LAST_CHAIN"] = self.last_chain_at()   # 10/25 尾盘闸动态: exec_base 里所有"最晚开链"判断都读这个
        if self.dormant():
            self._track_all()
            return
        self._track_all()
        self._maybe_keepalive(hm)
        self.empty_nudge(hm)
        wk = self.wake_hits(hm) if now().strftime("%H:%M") < X.flag("EXEC_LAST_CHAIN", "14:51") else []
        if now().strftime("%H:%M") < X.flag("EXEC_LAST_CHAIN", "14:51"):
            wk += [f"挂单超时: {t_}" for t_ in self._ttl_check(hm)]   # 10/26 选挂法: 挂出 ttl 分钟没成交叫醒一次(只读策略, 不拿锁; need_re 和 tick 同一线程)
        if wk:
            self.restrategize("; ".join(wk), counted=False)   # 失效条件 = 必判, 不占上限、不看冷却(在算时会排队合并)
        held = self._band_view()
        if self.mode != "plan":
            with self.lock:   # 出 band 不满 PAPER_BAND_HOLD_S 秒的票: 给 v2 的判定看"放宽到现价"的 band(拿着锁, 新起的链线程要等换回真 band 才读策略)
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
        if not why or now().strftime("%H:%M") >= X.flag("EXEC_LAST_CHAIN", "14:51"):
            return
        must = any(w.startswith(("(失败重试)", "手动", "本链成交")) for w in why)
        if self.last_re and (now() - self.last_re).total_seconds() < (3 if hm <= "10:30" else 5) * 60 and not must:
            return
        if not must and hm >= (X.flag("PAPER_CAP_FROM", "10:30") or "10:30") and self.n_re >= self.cap:   # 10/22 23:2x 用户定: 计划模式的出 band 和盯盘一样 10:30 起计上限(共用上限值、各本分别计数)
            if not getattr(self, "_capped", False):
                self._capped = True
                self.ev(kind="到上限", why=why)
            return
        self.restrategize("; ".join(why), counted=not must)   # 10:30 前 restrategize 内部自动改成不计

    # ---------- 叫模型: 同一会话里接着想 ----------
    # ---------- 缓存保温(10/23 00:5x 彩排发现: 5 分钟缓存过期 → 每次叫醒重写 33 万 token ≈ $1.7; 改 1 小时缓存后, 空闲满 PAPER_KEEPALIVE_MIN 分钟发一句短话续期) ----------
    def _maybe_keepalive(self, hm):
        kp = float(X.flag("PAPER_KEEPALIVE_MIN", "50") or 0)
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
        """每轮超时(10/23 01:3x 用户令: 按当日实际最大耗时算, 不同线不同): = clamp(PAPER_TMO_K × 本线今天这一步见过的最长耗时, PAPER_TMO_MIN, PAPER_TMO_MAX);
        启动轮直接给上限。只防"真挂死占着叫醒名额"——超时被杀 = 这一轮作废、下次叫醒重来; 竞价 / 尾盘段不再单独缩短(竞价没赶上 09:24:57 有草稿兜底挂单,
        迟到的正式版照样用于连续竞价), 所以关键时段也不杀想得久的轮次"""
        lo, k, hi = (float(X.flag(n, d) or d) for n, d in (("PAPER_TMO_MIN", "600"), ("PAPER_TMO_K", "3"), ("PAPER_TMO_MAX", "1800")))
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
        if not boot:   # 10/25 用户要逐步审示例: 每步发给模型的提问原文也落盘(盘前首跑那条 = 00_boot_msg.md, 已有)
            try:
                (vd / f"{rnd}_ask.md").write_text(text, encoding="utf-8")
            except OSError:
                pass
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
        L = pack.lines(self.D)
        order = list(L).index(self.line["id"]) if self.line["id"] in L else 99
        return c * 1000 + (0 if self.state.get("positions") else 100) + order

    def _chain(self, why, effort="high"):
        p = self.prio(why)
        self.ev(kind="排队叫醒", prio=p, inflight=GATE.busy, waiting=len(GATE.wait))
        k = 3 if self.debate_now() and self.d03_mode() == "fork" else 1   # 带 03 分叉: 多方 / 空方两个分支和主会话同时在跑; 一次调用模式只占 1 个
        GATE.acquire(p, self.line["id"], k)
        try:
            return self._chain_run(why, effort)
        finally:
            GATE.release(self.line["id"], k)

    @staticmethod
    def d03_mode():
        """10/24 用户批: 03 默认一次调用写空方 + 多方(PAPER_03_MODE=one); fork = 10/22 版的两个独立分叉"""
        return (_flag0("PAPER_03_MODE", "one") or "one").strip()

    def _d03_one(self, prefix, vd, T, material=None, crit=False):
        """03 一次调用: 在主会话里写(04 直接看得到, 缓存共用); 10/24 步骤边界 v2: 03 闸(每方 3 条 / 引用真实 / 有负样本时空方必须引), 不过打回一次"""
        r = self._ask("03", (prefix + chr(10) * 2 + "---" + chr(10) * 2 if prefix else "") + H.ASK03_ONE, vd, T, 300)
        if self.gate_on() and not self.fake and r.get("ok"):
            V = H.gate03(r.get("json"), material or prefix)
            if V and not crit and H.cfg()["on_fail"] == "retry":
                rg = self._ask("03_gate", "你的 03 没通过 harness 闸:\n- " + "\n- ".join(V[:10]) + "\n\n只做一件事: 按原来的判断改正, 输出同格式的完整最终 ```json(不要重新分析)。", vd, T, 120)
                r = {**r, "usd": r["usd"] + rg["usd"], **({"json": rg["json"]} if isinstance(rg.get("json"), dict) else {})}
                V2 = H.gate03(r.get("json"), material or prefix)
            else:
                V2 = V
            if V:
                self.ev(kind="03 闸", n=len(V), after_retry=len(V2), items=V[:6])
                T["gate03"] = {"first": V[:10], "after": V2[:10]}
        return r

    # ---------- 10/24 必查状态(范围 / 全天固定的 E 编号 / 已发全量的票 / 上一版提到的票)落盘: 进程中途重启也接得上 ----------
    def _facts_delta(self, facts):
        """事实包按「## 小节」切开, 已经发过一字不差的小节换成一行"同前"; 返回要发的文本(10/25 叫醒只发增量)"""
        import hashlib
        sent = self.__dict__.setdefault("_facts_sent_secs", {})
        parts = re.split(r"(?m)^(## [^\n]+)$", facts)
        out, same = [parts[0]], []
        for i in range(1, len(parts) - 1, 2):
            h, body = parts[i], parts[i + 1]
            key = re.sub(r"[（(].*", "", h).strip()
            dig = hashlib.md5(body.encode("utf-8")).hexdigest()
            if sent.get(key) == dig:
                same.append(key[3:].strip()[:24])
            else:
                out.append(h + body)
                sent[key] = dig
        if same:
            out.append(f"\n(以下 {len(same)} 个小节和之前发给你的一字不差, 不重发, 见前文: {'、'.join(same)})\n")
        return "".join(out)

    def _must_f(self):
        return self.dir / "must_state.json"

    def _must_save(self):
        try:
            self._must_f().write_text(json.dumps({"watch": getattr(self, "_watch", {}), "ereg": [[*k, v] for k, v in (getattr(self, "_ereg", {}) or {}).items()],
                                                  "seen": sorted(getattr(self, "_seen", set())), "mentioned": sorted(getattr(self, "_mentioned", set())),
                                                  "slim": sorted(getattr(self, "_slim", set())), "promoted": sorted(getattr(self, "_promoted", set()))}, ensure_ascii=False), encoding="utf-8")
        except Exception:   # noqa: BLE001
            pass

    def _must_load(self):
        if getattr(self, "_ereg", None) is not None and hasattr(self, "_seen"):
            return
        try:
            d = json.loads(self._must_f().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        self._watch = d.get("watch") or {}
        self._ereg = {(a, b, c): e for a, b, c, e in d.get("ereg") or []}
        self._seen = set(d.get("seen") or [])
        self._mentioned = set(d.get("mentioned") or [])
        self._slim, self._promoted = set(d.get("slim") or []), set(d.get("promoted") or [])

    def _boot_material(self):
        if getattr(self, "_boot_text", None):
            return self._boot_text
        try:
            fs = sorted((self.dir / "versions").glob("*/00_boot_msg.md"))
            self._boot_text = fs[-1].read_text(encoding="utf-8") if fs else ""
        except OSError:
            self._boot_text = ""
        return self._boot_text

    def gate_on(self):
        """10/24: harness 闸总开关(PAPER_GATE04=1 且拟人线) —— 02 / 03 / 04 / 06 的步骤边界都跟这个开关"""
        return (_flag0("PAPER_GATE04", "1") or "1").strip() == "1" and self.line.get("kind") == "mimic"

    def debate_now(self):
        """这本账这次跑不跑 03: lines.json debate=true 且不在竞价段(竞价复核不跑 03, 你 23:5x 定)"""
        return bool(self.line.get("debate")) and now().strftime("%H:%M:%S") >= "09:25:00" or (bool(self.line.get("debate")) and not self.sess.booted)

    def _debate(self, vd, T):
        """03 多空辩论(10/22 23:5x 用户定: 和 v1 / TradingAgents 一样多方空方独立并行): 从主会话分出两个分支同时跑, 彼此看不到, 也不写回主会话 → 两份结论交给 04 当裁判"""
        import chain_steps
        res = {}

        def one(name, ask):
            res[name] = self._fake(name, ask) if self.fake else self.sess.fork(ask, name, timeout=self._tmo("03"))
        ths = [threading.Thread(target=one, args=("03_bull", chain_steps.ASK["03b"])), threading.Thread(target=one, args=("03_bear", chain_steps.ASK["03r"]))]
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

    # ---------- 10/26 用户令: 06 选挂法(LLM 出意图, 规则出价格和数量); 06 可以不写 px / qty, 写 style + ratio, 落单那一刻由代码按当时盘口算 ----------
    STYLES = ("追价", "低吸", "挂高", "排板", "开盘", "等反抽", "移动止盈", "防踏空", "炸板走", "立即", "反抽卖")
    INTENTS = ("必须走", "想走", "冲高卖", "低吸", "打板", "必须买")   # 10/26 晚用户批: 06 只写意图, 执行器在落单那一刻按盘面选挂法(选型表 _intent_expand)
    REF_RE = re.compile(r"(?<![A-Za-z])(R|E|Q|U|KS|KD|M|B)\d+")   # 推翻选型表要引的依据编号

    def _mkt_state(self, c, amp):
        """落单那一刻的盘面: 封板 / 急跌 / 冲高 / 平稳 / 盘前(离线实验 docs/research/bracket_offline_20261026.md 的口径)"""
        hm = now().strftime("%H:%M:%S")
        if hm < "09:30:00":
            return "盘前"
        q_ = self.feed.q.get(c) or {}
        p_ = q_.get("p")
        if not p_:
            return "平稳"
        up = self._limit_up(c)
        if up and p_ >= up - 0.005 and not (q_.get("a1") or 0):
            return "封板"
        o = (getattr(self, "_dopen", {}) or {}).get(c)
        lo_, hi_ = getattr(self, "_dayhl", {}).get(c, (None, None))
        a = (amp or 3.0) / 100
        pc0 = X.prev_close(c, self.D)
        if hm < "09:35:00":   # v2(10/26 晚回放): 开盘 5 分钟内没有日内走势可判 → 按开盘情境: 低于昨收开 = 拿着等(百洋股份 10/26 水下被抢上来), 平 / 高开 = 现价卖
            return "开盘水下" if (o and pc0 and o < pc0 * 0.995) else "开盘水上"
        if (o and p_ <= o * 0.97) or (hi_ and p_ <= hi_ * (1 - max(0.03, 0.6 * a))):
            return "急跌"
        pc = X.prev_close(c, self.D)
        if hi_ and p_ >= hi_ * (1 - 0.25 * a) and (not o or p_ >= o) and (not pc or p_ > pc):
            return "冲高"
        return "平稳"

    def _no_avg_down(self, x, amp, hm):
        """10/26 22:0x 用户原则(market-skill U24): 越跌越补仓是教训 —— 浮亏的持仓票盘中再买, 要等反转信号, 没等到就尾盘补:
        已有持仓且现价 < 成本 的盘中买单(非排板 / 非 now / 没引规则编号推翻)→ 条件单「日内最低反弹 max(1.5%, 0.5×振幅) 才买」, 14:50 还没反转按卖一尾盘补"""
        if (X.flag("EXEC_NO_AVG_DOWN", "1") or "1") != "1" or hm < "09:30:00" or hm >= "14:50:00":
            return
        c = x["code"]
        pos = (self.state.get("positions") or {}).get(c) or {}
        p_ = (self.feed.q.get(c) or {}).get("p")
        if not (int(pos.get("qty") or 0) > 0 and pos.get("cost") and p_ and p_ < float(pos["cost"])):
            return
        keep, hit = [], []
        for r in x.get("rules") or []:
            if r.get("side") != "BUY" or r.get("now") or r.get("auction") or str(r.get("style") or "") in ("排板", "立即") or r.get("type") in ("board_dip",)                     or r.get("_override") or (r.get("人工价") and self.REF_RE.search(str(r.get("why") or ""))):
                keep.append(r)
            else:
                hit.append(r)
        if not hit:
            return
        # 这只票的盘中补仓单合成一张: 等反转(日内最低反弹)买全部; 14:50 没反转按卖一尾盘补
        q = sum(int(r.get("qty") or 0) for r in hit)
        ra = sum(float(r.get("ratio") or 0) for r in hit if not r.get("qty"))
        m = {k: v for k, v in hit[0].items() if k not in ("px", "type", "qty", "ratio", "unless", "ref", "dir", "pct", "book", "_armed")}
        m.update(style="防踏空", _pct_floor=1.5, deadline="14:50:00", _no_avg_down={"cost": pos["cost"], "p": p_, "at": hm, "orig": [(r.get("id"), r.get("style"), r.get("px"), r.get("qty") or r.get("ratio")) for r in hit]})
        if q:
            m["qty"] = q
        if ra:
            m["ratio"] = round(ra, 4)
        x["rules"] = keep + [m]

    def _intent_expand(self, x, amp):
        """意图 → 具体挂法(选型表, 10/26 晚用户批); 06 写了 style 没写 intent: 有依据编号(R / E / Q …)= 推翻选型表照它挂, 没有依据 = 按选型表(原 style 留档)"""
        if (X.flag("EXEC_INTENT_TABLE", "1") or "1") != "1":
            return
        c = x["code"]
        held = int(((self.state.get("positions") or {}).get(c) or {}).get("sellable") or 0)
        out = []
        for r in x.get("rules") or []:
            it = str(r.get("intent") or "").strip()
            sty = str(r.get("style") or "").strip()
            if not it and sty and sty not in ("排板", "开盘", "立即") and not r.get("人工价"):
                if self.REF_RE.search(str(r.get("why") or "")):
                    r["_override"] = "推翻选型表(有依据)"
                    out.append(r)
                    continue
                it = ("想走" if r.get("side") == "SELL" else "低吸") if sty in self.STYLES else ""
                if it:
                    r["_style_ignored"] = sty
            if not it or it not in self.INTENTS:
                out.append(r)
                continue
            side = "SELL" if it in ("必须走", "想走", "冲高卖") else "BUY"
            st_ = self._mkt_state(c, amp)
            base = {k: v for k, v in r.items() if k not in ("style", "px", "qty", "ratio", "type", "ref", "dir", "pct", "book")}
            base.update(side=side, intent=it, _state=st_)
            try:
                R = float(r.get("ratio") or (1 if side == "SELL" else 0))
            except (TypeError, ValueError):
                R = 0
            keepq = {k: r[k] for k in ("qty", "ratio") if r.get(k)}
            if it in ("必须走", "必须买"):
                out.append({**base, "style": "立即", **keepq})
            elif it == "打板":
                out.append({**base, "style": "排板", **keepq})
            elif it == "低吸":   # 低吸限价一半 + 防踏空一半(低吸成交了就不追; 追买门槛下限 1.5%, 太极股份 10/23 0.5×振幅 = 1.33% 追早了)
                q0 = int(r.get("qty") or 0)
                if q0:   # 06 写的是股数(不是 ratio): 按股数对半分
                    qa = int(X.AR.round_qty(c, q0 / 2)) or q0
                    ha, hb = {"qty": qa}, {"qty": q0 - qa}
                else:
                    ha = hb = {"ratio": round(R / 2, 4)}
                out.append({**base, "id": f"{r['id']}a", "style": "低吸", **ha})
                if hb.get("qty", 1):
                    out.append({**base, "id": f"{r['id']}b", "style": "防踏空", **hb, "unless": f"{r['id']}a", "_pct_floor": 1.5})
            else:   # 想走 / 冲高卖
                tot = min(held, int(r["qty"])) if r.get("qty") else (held if R >= 0.99 else int(X.AR.round_qty(c, held * R)))
                q1 = int(X.AR.round_qty(c, tot / 2))
                q2 = tot - q1
                if not tot:
                    out.append({**base, "style": "移动止盈", "ratio": R})   # 没可卖: 交给数量那段报"已经没有可卖"
                elif st_ == "封板":
                    out.append({**base, "style": "炸板走", "qty": tot})
                elif st_ == "急跌":   # 等反抽: 日内最低反弹 0.8×振幅 卖一半(60 分钟没反抽到点卖) + 剩余 日内最高回落 0.8×振幅
                    if q1:
                        out.append({**base, "id": f"{r['id']}a", "style": "反抽卖", "qty": q1})
                    if q2:
                        out.append({**base, "id": f"{r['id']}b", "style": "移动止盈", "qty": q2})
                elif st_ == "冲高":   # 已经在冲高: 不等反抽, 一半挂高(规则价) + 一半移动止盈
                    if q1:
                        out.append({**base, "id": f"{r['id']}a", "style": "挂高", "qty": q1})
                    if q2:
                        out.append({**base, "id": f"{r['id']}b", "style": "移动止盈", "qty": q2})
                elif st_ in ("开盘水下", "盘前"):   # 水下开 / 盘前: 全部移动止盈(不在开盘第一波砸)
                    out.append({**base, "style": "移动止盈", "qty": tot})
                else:   # 平稳 / 开盘水上: 现价卖(追价) —— 10/26 晚回放: 这两种盘面移动止盈比模型直接卖差(中位 −1.3%), 离线实验也只证明了"急跌后等反抽"
                    out.append({**base, "style": "追价", "qty": tot})
        x["rules"] = out
    STYLE_TTL = {"追价": 5, "低吸": 30, "挂高": 30}   # 挂出多少分钟没成交 → 叫醒重判(低吸 / 挂高优先用导师被动单存续时间)

    def _style_prep(self, s):
        if (X.flag("PAPER_STYLE", "1") or "1") != "1":
            return []
        bad = []
        st = self.state or {}
        nav = float(st.get("cash") or 0) + sum(int(q.get("qty") or 0) * float(q.get("cost") or 0) for q in (st.get("positions") or {}).values())
        hm = now().strftime("%H:%M:%S")
        preopen = hm < "09:30:00"
        for x in (s or {}).get("codes") or []:
            c = x["code"]
            q_ = self.feed.q.get(c) or {}
            pc = X.prev_close(c, self.D)
            cur = q_.get("p") or pc
            amp = self._amp(c)
            if not x.get("band") and x.get("band_w") and cur:
                # 区间 = 此刻现价 ± 档位 k × 本票振幅 × 时段系数 × 当日波动比, 上下按持仓方向不对称(10/26 用户批成熟做法 1~3; 系数暂定, 周一晚回测校准)
                k = {"宽": 1.0, "中": 0.6, "窄": 0.35}.get(str(x["band_w"]), 0.6) * amp / 100
                hm5 = hm[:5]
                tf = 1.5 if hm5 < "10:00" else 1.0 if hm5 < "13:00" else 0.85 if hm5 < "14:30" else 0.7
                lo_, hi_ = getattr(self, "_dayhl", {}).get(c, (None, None))
                vr = 1.0
                if lo_ and hi_ and pc and amp and hm5 >= "09:31":
                    mins = max(1.0, (dt.datetime.strptime(hm5, "%H:%M") - dt.datetime.strptime("09:30", "%H:%M")).total_seconds() / 60 - (90 if hm5 >= "13:00" else 0))
                    exp_ = amp * min(1.0, (mins / 240) ** 0.5)
                    vr = min(1.8, max(0.7, ((hi_ - lo_) / pc * 100) / exp_)) if exp_ > 0 else 1.0
                held_ = int(((st.get("positions") or {}).get(c) or {}).get("qty") or 0) > 0
                dn_k, up_k = (0.7, 1.3) if held_ else (1.3, 0.7)   # 持仓: 下沿紧(跌破就想走不走) / 上沿松(冲高先别叫); 空仓等买反过来
                kk = k * tf * vr
                x["band"] = [round(cur * (1 - kk * dn_k), 3), round(cur * (1 + kk * up_k), 3)]
                x["_band_calc"] = {"k": round(k * 100, 2), "时段": tf, "波动比": round(vr, 2), "持仓": held_}
            self._intent_expand(x, amp)
            self._no_avg_down(x, amp, hm)
            keep = []
            for r in x.get("rules") or []:
                sty = str(r.get("style") or "").strip()
                if not sty:
                    keep.append(r)
                    continue
                if sty not in self.STYLES:
                    bad.append(f"{c} {r.get('id')} 挂法 {sty} 不认识(只许 {'/'.join(self.STYLES)})")
                    continue
                side = r.get("side")
                if side not in ("BUY", "SELL"):
                    bad.append(f"{c} {r.get('id')} 挂法单缺 side")
                    continue
                if r.get("px") and r.get("人工价"):   # 模型指定价: 必须写依据, 照用(和规则价一起留档)
                    r["_price_src"] = "人工价"
                elif r.get("px"):
                    r["model_px"] = r.pop("px")
                try:
                    if sty in ("等反抽", "移动止盈"):
                        r.update(type="cond", side="SELL", ref="日内最高", dir="down", pct=round(min(6.0, max(1.5, 0.8 * amp)), 2), book="b1", _armed=True)
                    elif sty == "防踏空":
                        k_ = 0.8 if amp > 5.6 else 0.5
                        r.update(type="cond", side="BUY", ref="日内最低", dir="up", pct=round(min(6.0, max(float(r.get("_pct_floor") or 1.0), k_ * amp)), 2), book="a1", _armed=True)
                    elif sty == "反抽卖":   # 10/26 晚: 急跌后等反抽 = 日内最低(生效后)反弹 0.8×振幅 卖; 60 分钟没反抽到点按买一卖(北新路桥 10/23 一路跌)
                        r.update(type="cond", side="SELL", ref="日内最低", dir="up", pct=round(min(6.0, max(1.5, 0.8 * amp)), 2), book="b1", _armed=True,
                                 deadline=(now() + dt.timedelta(minutes=int(X.flag("EXEC_REBOUND_DEADLINE_MIN", "60") or 60))).strftime("%H:%M:%S"))
                    elif sty == "炸板走":
                        r.update(type="cond", side="SELL", ref="涨停价", dir="down", pct=1.75 if str(r.get("strength")) == "强" else 1.5, book="b1")
                    elif sty == "立即":
                        lv = (q_.get("b1") if side == "SELL" else q_.get("a1")) or cur
                        r.update(px=round(float(lv), 3), now=True)
                    elif not r.get("px"):
                        import price_rules as PRC
                        snap = {"prevClose": pc, "last": q_.get("p") or 0, "name": x.get("name")}
                        st_ = {"挂高": "低吸"}.get(sty, sty)
                        rp = PRC.rule_price(self.skill, "买" if side == "BUY" else "卖", st_, snap, c, self.D, preopen)
                        if not rp.get("ok"):
                            bad.append(f"{c} {r.get('id')} 规则价算不出: {rp.get('err')}")
                            continue
                        r["px"] = rp["px"]
                        r["_rule_why"] = str(rp.get("why") or "")[:160]
                        if sty == "开盘":
                            r["auction"] = True
                            if side == "SELL" and pc:   # 开盘卖 = 保证卖掉: 竞价按跌停价挂(按撮合价成交)
                                r["px"] = X.AR.limit_prices(c, self.D, pc)[1] or r["px"]
                        if rp.get("reprice"):
                            r.setdefault("ttl", int(rp["reprice"]))
                        r.setdefault("ttl", self.STYLE_TTL.get(sty))
                        r["_price_src"] = "规则价"
                except Exception as e:   # noqa: BLE001
                    bad.append(f"{c} {r.get('id')} 挂法换价失败 {e!r}"[:160])
                    continue
                if not r.get("qty"):   # 数量: ratio = 卖出占持仓 / 买入占总资产
                    try:
                        ratio = float(r.get("ratio") or 0)
                    except (TypeError, ValueError):
                        ratio = 0
                    px_ = float(r.get("px") or cur or 0)
                    if side == "SELL":
                        held = int(((st.get("positions") or {}).get(c) or {}).get("sellable") or 0)
                        r["qty"] = held if ratio >= 0.99 else int(X.AR.round_qty(c, held * ratio))
                    elif px_ > 0:
                        r["qty"] = int(X.AR.round_qty(c, nav * ratio / px_))
                    if not r.get("qty"):
                        bad.append(f"{c} {r.get('id')} 挂法单数量为 0(ratio={r.get('ratio')}" + (", 已经没有可卖: 本版开跑后这只已成交卖完" if side == "SELL" else "") + ")")
                        continue
                r["_land"] = hm
                keep.append(r)
            x["rules"] = keep
        return bad

    def _ttl_check(self, hm):
        """挂法单挂出 ttl 分钟还没成交 → 叫醒一次(不撤单, 让模型决定改单 / 放弃)"""
        out = []
        t_now = now()
        for x in (self.strategy or {}).get("codes") or []:
            for r in x.get("rules") or []:
                key = f"{self.ver}:{x['code']}:{r['id']}"
                if not r.get("ttl") or not r.get("_land") or key in self.fired or r.get("_ttl_woke"):
                    continue
                try:
                    land = dt.datetime.combine(t_now.date(), dt.datetime.strptime(max(r["_land"], "09:30:00"), "%H:%M:%S").time())
                except ValueError:
                    continue
                if (t_now - land).total_seconds() >= int(r["ttl"]) * 60:
                    r["_ttl_woke"] = True
                    out.append(f"{x.get('name') or ''}{x['code']} {r.get('style')}单挂出 {r['ttl']} 分钟没成交({'买' if r['side'] == 'BUY' else '卖'} {r.get('px')})")
        return out

    # ---------- 10/25 用户令: 条件单(像人在券商 App 里挂的条件单) ----------
    COND_REFS = ("昨收", "开盘价", "涨停价", "跌停价", "日内最高", "日内最低")

    def _cond_ref(self, c, ref, r):
        """条件单参考价; 日内最高 / 日内最低 = 这张单生效后的最高 / 最低(回落卖出 / 反弹买入)"""
        if isinstance(ref, (int, float)) or (isinstance(ref, str) and re.fullmatch(r"\d+(\.\d+)?", ref)):
            return float(ref)
        if ref == "昨收":
            return X.prev_close(c, self.D)
        if ref == "开盘价":
            return (getattr(self, "_dopen", {}) or {}).get(c)
        if ref == "涨停价":
            return self._limit_up(c)
        if ref == "跌停价":
            pc = X.prev_close(c, self.D)
            return X.AR.limit_prices(c, self.D, pc)[1] if pc else None
        if ref == "日内最高":
            return r.get("_hi")
        if ref == "日内最低":
            return r.get("_lo")
        return None

    def _cond_prep(self, s):
        """06 写的条件单 → 补齐基类校验要的 op / px(px 只是校验用的参考, 撮合按条件); 字段不全的剔掉"""
        bad = []
        for x in (s or {}).get("codes") or []:
            keep = []
            for r in x.get("rules") or []:
                if r.get("type") != "cond":
                    keep.append(r)
                    continue
                c = x["code"]
                try:
                    pct = float(r.get("pct"))
                    ok = r.get("side") in ("BUY", "SELL") and r.get("dir") in ("up", "down") and (r.get("ref") in self.COND_REFS or re.fullmatch(r"\d+(\.\d+)?", str(r.get("ref")))) \
                        and 0 <= pct <= 30 and str(r.get("book") or "b1") in ("b1", "b2", "b3", "a1", "a2", "a3") and int(r.get("qty") or 0) > 0
                except (TypeError, ValueError):
                    ok = False
                if not ok:
                    bad.append(f"{c} {r.get('id')} 条件单字段不全(side / ref / dir / pct / book / qty)")
                    continue
                r["op"] = "<=" if r["side"] == "BUY" else ">="
                if not r.get("px"):
                    p_ = (self.feed.q.get(c) or {}).get("p") or X.prev_close(c, self.D) or 0
                    ref0 = self._cond_ref(c, r["ref"], r) or p_
                    r["px"] = round(ref0 * (1 + pct / 100) if r["dir"] == "up" else ref0 * (1 - pct / 100), 3) if ref0 else p_
                    pc_ = X.prev_close(c, self.D)
                    if pc_:   # 校验用参考价夹在涨跌停内(真正触发看条件)
                        up_, dn_ = X.AR.limit_prices(c, self.D, pc_)
                        if up_ and dn_:
                            r["px"] = min(max(r["px"], dn_), up_)
                keep.append(r)
            x["rules"] = keep
        return bad

    def _cond_tick(self, hm):
        """条件单撮合(每 3 秒): 条件成立 → 按买 n / 卖 n 档价一次成交; arm = 先要碰到参考价才开始算回落(涨停价 / 日内最高 默认要)"""
        more = []
        s = self.strategy or {}
        for x in s.get("codes") or []:
            c = x["code"]
            q_ = self.feed.q.get(c) or {}
            p_ = q_.get("p")
            if not p_:
                continue
            for r in x.get("rules") or []:
                key = f"{self.ver}:{c}:{r['id']}"
                if r.get("type") != "cond" or key in self.fired:
                    continue
                if r.get("after") and not any(str(t.get("rule", "")) == f"{self.ver}:{c}:{r['after']}" for t in self.state.get("trades") or []):
                    continue
                if r.get("unless") and any(str(t.get("rule", "")) == f"{self.ver}:{c}:{r['unless']}" for t in self.state.get("trades") or []):
                    continue   # 10/26 晚: 低吸那一半成交了 → 防踏空不追
                r["_hi"] = max(r.get("_hi") or p_, p_)
                r["_lo"] = min(r.get("_lo") or p_, p_)
                ref = self._cond_ref(c, r["ref"], r)
                if not ref:
                    continue
                pct = float(r["pct"]) / 100
                arm = r.get("arm", r["ref"] in ("涨停价", "日内最高", "日内最低"))
                if arm and not r.get("_armed"):   # 回落类: 先要到过参考价; 反弹类: 先要到过最低(日内最低天然成立)
                    if (r["dir"] == "down" and p_ >= ref - 1e-6) or (r["dir"] == "up" and p_ <= ref + 1e-6) or r["ref"] in ("日内最高", "日内最低"):
                        r["_armed"] = True
                    else:
                        continue
                hit = p_ >= ref * (1 + pct) - 1e-9 if r["dir"] == "up" else p_ <= ref * (1 - pct) + 1e-9
                if not hit and r.get("deadline") and now().strftime("%H:%M:%S") >= r["deadline"]:
                    hit = True   # 截止时间到了还没触发 → 按档价成交(反抽卖: 一路跌不反抽也要走)
                    r["_deadline_hit"] = True
                if not hit:
                    continue
                bk = str(r.get("book") or ("b1" if r["side"] == "SELL" else "a1"))
                lv = [l for l in (q_.get("b") if bk[0] == "b" else q_.get("k")) or [] if l and l[0]]
                n_ = int(bk[1]) - 1
                if r["side"] == "SELL" and not (q_.get("b1") or 0):
                    continue   # 跌停封死卖不出
                if r["side"] == "BUY" and not (q_.get("a1") or 0):
                    continue   # 涨停封死买不进
                px = float(lv[n_][0]) if len(lv) > n_ else float(p_)
                pos = self.state["positions"].setdefault(c, {"qty": 0, "cost": None, "sellable": 0})
                if r["side"] == "SELL":
                    n = min(int(r["qty"]), int(pos.get("sellable") or 0))
                else:
                    n = min(int(r["qty"]), X.AR.round_qty(c, (self.state["cash"] - max(5.0, self.state["cash"] * 0.0003)) / px))
                self.fired.add(key)
                if n <= 0:
                    self.ev(kind="条件单触发但没钱 / 没可卖", rule=key, p=p_)
                    continue
                amt = px * n
                fe = self.fee(c, r["side"], amt)
                if r["side"] == "BUY":
                    pos["cost"] = ((pos["cost"] or 0) * pos["qty"] + amt + fe) / (pos["qty"] + n)
                    pos["qty"] += n
                    if X.AR.is_t0(c, x.get("name")):
                        pos["sellable"] += n
                    self.state["cash"] = round(self.state["cash"] - amt - fe, 2)
                else:
                    pos["qty"] -= n
                    pos["sellable"] -= n
                    self.state["cash"] = round(self.state["cash"] + amt - fe, 2)
                    if pos["qty"] <= 0:
                        self.state["positions"].pop(c, None)
                cond_txt = f"{r['ref']}{'涨' if r['dir'] == 'up' else '回落'}{r['pct']}%(参考 {round(ref, 3)}) → 按{'买' if bk[0] == 'b' else '卖'}{bk[1]}" + (f"(截止 {r['deadline']} 到点成交)" if r.get("_deadline_hit") else "") + (f" · {r.get('intent')}@{r.get('_state')}" if r.get("intent") else "")
                t = {"t": now().strftime("%H:%M:%S"), "code": c, "name": x.get("name"), "side": r["side"], "px": round(px, 3), "qty": n, "fee": fe, "rule": key,
                     "why": r.get("why"), "cond": cond_txt, "tape": {k_: q_.get(k_) for k_ in ("p", "t", "b", "k")}}
                self.state["trades"].append({k_: v for k_, v in t.items() if k_ != "tape"})
                with (self.dir / "actions.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps(t, ensure_ascii=False) + chr(10))
                self.ev(kind="条件单成交", rule=key, cond=cond_txt, px=round(px, 3), qty=n)
                more.append(t)
        return more

    def _run_ask(self, j, vd, T, crit, state):
        """→ 放在 06 提问最前面的 Q 结果块(没有查询 → ''); 违规只记录不打回(10/25 用户定)"""
        import ask_q as AQ
        material = ""
        try:
            material = (vd / ("00_boot_msg.md" if T["boot"] else "00_trigger_msg.md")).read_text(encoding="utf-8")
        except OSError:
            pass
        V = AQ.ask_check(j, material, getattr(self, "_prev_ask", ()), crit=crit)
        asked = [str((x or {}).get("cmd") or "").strip() if isinstance(x, dict) else str(x).strip() for x in (j.get("ask") or [])[:AQ.MAX_ASK]] if isinstance(j.get("ask"), list) else []
        asked = [a for a in asked if a]
        self._prev_ask = asked
        lim_codes = set()
        try:   # 涨跌停 / 点名封板的票 → 情景自动查 events
            import telegraph_now as TN
            lim_codes = set(TN.limit_named(self.D, now().strftime("%H:%M:%S")))
        except Exception:   # noqa: BLE001
            pass
        for c, q in dict(self.feed.q or {}).items():
            try:
                pc = X.prev_close(c, self.D)
                if pc and q.get("p") and abs(q["p"] / pc - 1) >= 0.095:
                    lim_codes.add(c)
            except Exception:   # noqa: BLE001
                pass
        auto = [] if crit else AQ.auto_asks(j, list((state.get("positions") or {}).keys()), self.skill, self.line.get("kind") != "dt", lim_codes, asked)
        cmds = asked + auto
        T["ask"] = {"asked": asked, "auto": auto, "violations": V[:10], "no_ask_why": str(j.get("no_ask_why") or "")[:200]}
        if V:
            self.ev(kind="ask 闸(只记录)", n=len(V), items=V[:6])
        if not cmds:
            return ""
        t0 = time.time()
        res = AQ.run_many(cmds, self.D, self.dir.parent)
        T["ask"].update(secs=round(time.time() - t0, 1), ok=[bool(ok) for ok, _ in res])
        L = ["【查询结果(你在 04 要的 + 代码按情景补的; 代码已经替你跑好, 06 引用写 Q 编号, 例 '依据：Q2')】"]
        for i, (cmd, (ok, out)) in enumerate(zip(cmds, res), 1):
            src = "你要的" if i <= len(asked) else "代码按情景补的"
            L.append(f"### Q{i}({src}) `{cmd}`{'' if ok else ' —— 没查成'}\n{out}")
        txt = "\n\n".join(L) + "\n\n"
        (vd / "q_results.md").write_text(txt, encoding="utf-8")
        return txt

    def qty_pct(self, code, side, qty, px):
        """10/25 用户: 线的股数是按缩放到导师仓位后的账算的, 和你的实际股数不同 → 推送 / 汇总里股数后面加百分比, 你按比例换算
        卖 = 占这只票现有持仓的 %; 买 = 占本线总资产的 %"""
        try:
            st = self.state or {}
            if side == "SELL":
                held = int(((st.get("positions") or {}).get(str(code)) or {}).get("qty") or 0) or int((((st.get("start") or {}).get("positions") or {}).get(str(code)) or {}).get("qty") or 0)
                return f"（持仓的 {min(100, qty / held * 100):.0f}%）" if held else ""
            nav = float(st.get("cash") or 0) + sum(int(q.get("qty") or 0) * float(q.get("cost") or 0) for q in (st.get("positions") or {}).values())
            return f"（总资产的 {qty * float(px) / nav * 100:.0f}%）" if nav > 0 and px else ""
        except Exception:   # noqa: BLE001
            return ""

    def _amp(self, c):
        """本票近 20 个交易日日内振幅(高−低)/昨收 的中位 %; 取不到 → 4.0"""
        if not hasattr(self, "_ampc"):
            self._ampc = {}
        if c not in self._ampc:
            v = 4.0
            try:
                sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
                import manual_backfill as mb
                cur = mb.db().cursor()
                sym = ("sh" if c.startswith(("6", "5", "11")) else "sz") + c
                cur.execute("select high, low, pre_close from investment_market.kline_day where is_deleted=0 and symbol=%s and trade_date < %s and pre_close > 0 "
                            "order by trade_date desc limit 20", (sym, self.D))
                xs = sorted((float(h) - float(l)) / float(pc) * 100 for h, l, pc in cur.fetchall())
                if xs:
                    v = xs[len(xs) // 2]
            except Exception:   # noqa: BLE001
                pass
            self._ampc[c] = v
        return self._ampc[c]

    def _board_watch(self, hm, now_ts=None):
        """10/26 用户批: 必查池 / 持仓 / 有挂单的票出现 首次封板 / 炸板 / 回封 → 叫醒这条线(必判, 不占上限)
        冷却(用户: 防重复唤起快慢两版): 同票 LIVE_BOARD_CD 秒(默认 180)内只叫一次, 期间的新事件只记"最新板态"并进下一次;
        正在算时的事件由 restrategize 排队合并(不并发); 炸板 = 开板持续 ≥ LIVE_BOARD_OPEN_S 秒(默认 18, 同 S4a)"""
        if (X.flag("LIVE_BOARD_WAKE", "1") or "1") != "1" or self.dormant() or hm >= (X.flag("EXEC_LAST_CHAIN", "14:51") or "14:51"):
            return []
        ts = now_ts if now_ts is not None else time.time()
        cd = float(X.flag("LIVE_BOARD_CD", "180") or 180)
        n_open = float(X.flag("LIVE_BOARD_OPEN_S", "18") or 18)
        st = self.__dict__.setdefault("_bst", {})
        codes = {x["code"] for x in (self.strategy or {}).get("codes") or []} | set((self.state.get("positions") or {}).keys())
        try:
            codes |= set((json.loads((self.dir / "must_state.json").read_text(encoding="utf-8")).get("watch") or {}).keys()) if (self.dir / "must_state.json").exists() else set()
        except (OSError, ValueError, AttributeError):
            pass
        fired = []
        for c in sorted(codes):
            q_ = self.feed.q.get(c) or {}
            up, p_ = self._limit_up(c), q_.get("p")
            if not up or not p_:
                continue
            sealed_now = p_ >= up - 0.005 and not (q_.get("a1") or 0) and bool(q_.get("b1") or 0)
            z = st.setdefault(c, {"sealed": False, "ever": False, "open_t": None, "broke": False, "last": -1e9, "pend": None})
            ev = None
            if sealed_now and not z["sealed"]:
                ev = "回封" if z["broke"] else (None if z["ever"] else "首次封板")
                z.update(sealed=True, ever=True, open_t=None)
            elif not sealed_now and z["sealed"]:
                z.update(sealed=False, open_t=ts)
            elif not sealed_now and z["open_t"] is not None and not z["broke"] and ts - z["open_t"] >= n_open:
                ev = "炸板"
                z["broke"] = True
            if sealed_now and z["broke"] and ev is None:
                pass
            if ev:
                z["pend"] = f"{ev}({hm}, 现价 {p_:g}, 涨停 {up:g})"
            if z["pend"] and ts - z["last"] >= cd:
                name = ""
                for x in (self.strategy or {}).get("codes") or []:
                    if x["code"] == c:
                        name = x.get("name") or ""
                fired.append(f"{name}{c} {z['pend']}")
                z.update(last=ts, pend=None)
        if fired:
            self.ev(kind="板事件叫醒", items=fired)
            self.restrategize("板事件: " + "; ".join(fired)[:300], counted=False)
        return fired

    def _guard(self, hm):
        """10/25 晚用户令: 全天守卫(零 token, 每 3 秒随盘口判) —— 普通限价单的价格偏离现价 ≥ g%(卖单比现价低 / 买单比现价高 = 一碰就按市价成交,
        多半是按过时的盘面写的, 例 芷影 09:20 按竞价跌停 8.83 挂百洋卖 9.00, 开盘 10.09)→ 不让它按市价成交, 改成条件单:
          卖 → 移动止盈(日内最高回落 0.8×振幅, 夹 1.5~6%; 10/26 离线测试参数)  买 → 低吸防踏空(日内最低反弹 0.5×振幅)
        不拦: 条件单 / 竞价单 / 炸板接单 / 06 写了 "now": true 的(要立刻按市价成交的止损清仓)
        默认不叫模型(用户: 0 token); LIVE_GUARD_WAKE=1 时同时叫醒重判"""
        g = float(X.flag("LIVE_OPEN_GUARD_PCT", "3") or 3) / 100
        done = []
        with self.lock:
            for x in (self.strategy or {}).get("codes") or []:
                c = x["code"]
                p_ = (self.feed.q.get(c) or {}).get("p")
                if not p_:
                    continue
                for r in x.get("rules") or []:
                    key = f"{self.ver}:{c}:{r['id']}"
                    if r.get("auction") or r.get("type") in ("board_dip", "cond") or r.get("now") or key in self.fired or not r.get("px"):
                        continue
                    px = float(r["px"])
                    if not ((r["side"] == "SELL" and p_ >= px * (1 + g)) or (r["side"] == "BUY" and p_ <= px * (1 - g))):
                        continue
                    up_ = self._limit_up(c)
                    if r["side"] == "BUY" and up_ and px >= up_ - 0.005 and (getattr(self, "_qsealed", {}) or {}).get((c, r.get("id"), px)):
                        continue   # 落单时封死 = 已在涨停价排队, 开板按涨停价成交是对的(星光 10/22 例)
                    if r["side"] == "BUY" and up_ and (r.get("style") == "排板" or px >= up_ - 0.005):
                        # 10/26 用户复盘芷影林州重机: 06 写"涨停价 3.33 排板、开板才成交", 但普通限价买 3.33 在现价 3.05 时 = 立刻按卖一成交(不是排板);
                        # 守卫原来把它改成"日内最低反弹 2.32% 买" = 意图从打板变成低吸, 09:34:42 在 3.13 买进 4000 股。
                        # 改成真正的排板: 条件单"价格到涨停价才买"(封死时卖一空买不进 = 排队, 有卖单 / 开板才成交)
                        r.update(type="cond", ref="涨停价", dir="up", pct=0, arm=False, book="a1",
                                 _guarded={"orig_px": r.get("px"), "orig_op": r.get("op"), "at": hm, "p": p_})
                        done.append(f"{x.get('name') or ''}{c} 原单 买{px:g}(涨停价, 现价 {p_} = 一碰就按市价买, 不是排板) → 改成 排板条件单: 价格到涨停价 {up_:g} 才买")
                        continue
                    amp = self._amp(c)
                    old = {k: r.get(k) for k in ("px", "op")}
                    if r["side"] == "SELL":
                        r.update(type="cond", ref="日内最高", dir="down", pct=round(min(6.0, max(1.5, 0.8 * amp)), 2), book="b1")
                    else:
                        r.update(type="cond", ref="日内最低", dir="up", pct=round(min(6.0, max(1.0, 0.5 * amp)), 2), book="a1")
                    r.update(_guarded={"orig_px": old["px"], "at": hm, "p": p_}, _hi=p_, _lo=p_, _armed=True)
                    done.append(f"{x.get('name') or ''}{c} 原单 {'卖' if r['side'] == 'SELL' else '买'}{old['px']}(现价 {p_}, 差 {(p_ / px - 1) * 100:+.1f}%, 一碰就按市价成交) → "
                                f"改成 条件单: {'日内最高回落' if r['side'] == 'SELL' else '日内最低反弹'} {r['pct']}% 才{'卖' if r['side'] == 'SELL' else '买'}")   # 10/26 PC3 建议: 推送写清 原单 → 改成什么
        if done:
            self.ev(kind="守卫: 挂价偏离现价, 改条件单", items=done[:10], g_pct=g * 100)
            self.wx(f"【{self.skill} 守卫 {hm}】挂价离现价太远(一碰就按市价成交), 已改条件单: " + "; ".join(done)[:500])
            if (X.flag("LIVE_GUARD_WAKE", "0") or "0") == "1":
                threading.Timer(1.0, lambda: self.restrategize("守卫改了条件单: " + "; ".join(done)[:300], counted=False)).start()

    def _promote(self, codes, why_kind):
        """10/25 A / B: codes 里盘前只给过简版、今天还没补过全量的票 → 完整必查文本(每只一天一次, 一次最多 4 只); 没有 → ''"""
        self._promoted_now = []
        slim, done = getattr(self, "_slim", set()), getattr(self, "_promoted", set())
        want = [c for c in sorted(codes) if c in slim and c not in done][:4]
        if not want:
            return ""
        try:
            mf = (self.dir / "must_full.md").read_text(encoding="utf-8")
        except OSError:
            return ""
        import ask_q as AQ
        blocks = [(c, AQ.full_block(mf, c)) for c in want]
        blocks = [(c, b) for c, b in blocks if b]
        if not blocks:
            return ""
        self._promoted = set(done) | {c for c, _ in blocks}
        self._promoted_now = [c for c, _ in blocks]
        self.ev(kind="简版票补全量", why=why_kind, codes=self._promoted_now)
        head = ("## 焦点票的完整必查(盘前首跑只给过简版; 现在它成了焦点, 完整版在这里, E 编号和盘前一致)" if why_kind == "焦点" else
                "【你在 04 选了这些票, 但之前只看过它们的简版必查 —— 完整必查如下(E 编号和盘前一致), 06 落单前先看完; 看完改主意就照实写】")
        return head + "\n\n" + "\n\n".join(b for _, b in blocks)

    # ---------- 10/25 上下文第 ② 招: 午休换新会话 + 机械交接(PAPER_NOON_RESET=1 才开, 默认关; 用户 10/25 定今晚真调回放一起测) ----------
    def _noon_due(self, at):
        if (_flag0("PAPER_NOON_RESET", "0") or "0").strip() != "1" or self.sess.st.get("noon"):
            return False
        return at >= (_flag0("PAPER_NOON_AT", "11:30:00") or "11:30:00")

    def handoff_text(self, at):
        """上午交接: 全部由代码从版本目录 / 账本拼出来(不让模型总结, 免得丢细节或编); 06 观点是它当时自己写的原话"""
        nl = chr(10)
        L = [f"## 午休交接({at}, 代码拼的, 不是总结)", "",
             "午休把你换成了新会话(上午对话太长)。上面是现在的全部材料(同盘前首跑的格式, 数据是此刻的); 下面是你上午的记录。上午的原文都在, 想看哪一版就 Read 对应目录。", ""]
        L.append("### 上午各版策略(时刻 · 叫醒原因 · 你当时写的 06 观点)")
        for vd in sorted((self.dir / "versions").glob("*_*")):
            try:
                t = json.loads((vd / "timing.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if t.get("result") != "ok":
                continue
            try:
                view = str((json.loads((vd / "06.json").read_text(encoding="utf-8")) or {}).get("view") or "")
            except (OSError, ValueError):
                view = ""
            L.append(f"- {t.get('start', '')[:5]} {vd.name} · {str(t.get('why') or '')[:80]} → {view[:220]}" + (f"(原文 {vd / '06.md'})" if view else ""))
        with self.lock:
            st = json.loads(json.dumps(self.state))
            strat = json.loads(json.dumps(self.strategy)) if self.strategy else None
        tr = st.get("trades") or []
        L += ["", "### 上午成交(账本)"] + ([f"- {x.get('t', '')[:8]} {'买' if x['side'] == 'BUY' else '卖'} {x.get('name') or ''} {x['code']} {x['qty']} 股 @ {x['px']} · 规则 {x.get('rule')}" for x in tr] or ["- 无"])
        pos = st.get("positions") or {}
        nm = {str(cd.get("code")): cd.get("name") for cd in ((strat or {}).get("codes") or [])}
        for c, p in pos.items():
            p.setdefault("name", nm.get(c) or ((st.get("start") or {}).get("positions") or {}).get(c, {}).get("name"))
        L += ["", f"### 现在持仓(现金 {float(st.get('cash') or 0):,.0f})"] + ([f"- {p.get('name') or c} {c} {p.get('qty')} 股(可卖 {p.get('sellable')}) 成本 {float(p.get('cost') or 0):.3f}" for c, p in pos.items()] or ["- 空仓"])
        L += ["", "### 现在生效的策略(执行器正在按这一版撮合; 你这一轮的 06 会整版替换它)"]
        if strat:
            for cd in strat.get("codes") or []:
                rs = "; ".join(f"{r.get('id')} {'买' if r.get('side') == 'BUY' else '卖'} {r.get('op', '')}{r.get('px', '')} × {r.get('qty', '')}" + (" 竞价" if r.get("auction") else "") for r in cd.get("rules") or [])
                L.append(f"- {cd.get('name') or ''} {cd.get('code')} 区间 {cd.get('band')} · {rs or '无挂单'}")
            if strat.get("wake"):
                L.append(f"- 叫醒条件: {json.dumps(strat.get('wake'), ensure_ascii=False)[:400]}")
        else:
            L.append("- 无")
        return nl.join(L) + nl * 2

    def _noon_reset(self, at):
        old = dict(self.sess.st)
        (self.dir / "session_am.json").write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
        self._noon_handoff = self.handoff_text(at)
        self.sess.st = {}
        self.sess.f.unlink(missing_ok=True)
        self.facts_sent = None
        self.__dict__.pop("_inc_rows", None)   # 增量对照表作废: 新会话没见过上午发的全表
        self.ev(kind="午休换会话", at=at, old_sid=old.get("sid"), old_turns=len(old.get("turns") or []), handoff_chars=len(self._noon_handoff))

    def _chain_run(self, why, effort="high"):
        import chain_steps
        t0 = time.time()
        vd = self.dir / "versions" / f"{self.ver + 1:02d}_{now():%H%M%S}"
        vd.mkdir(parents=True, exist_ok=True)
        with self.lock:
            state = json.loads(json.dumps(self.state))
            strat, fired = (json.loads(json.dumps(self.strategy)) if self.strategy else None), set(self.fired)
        at, quotes, oc = now().strftime("%H:%M:%S"), dict(self.feed.q), self.open_ctx()
        if self.sess.booted and not self.fake and self._noon_due(at):
            self._noon_reset(at)
        ff = self.facts_file()
        src = f"{ff}:{ff.stat().st_mtime:.0f}" if ff.exists() else None
        if self.sess.booted and src and src == self.facts_sent:
            facts = "(事实包和上一次给你的相同, 没变, 见前文)"
        else:
            try:
                facts = f"(本份事实包生成于 {dt.datetime.fromtimestamp(ff.stat().st_mtime):%H:%M:%S}, 不是此刻)\n" + ff.read_text(encoding="utf-8", errors="replace")
                facts = re.sub(r"## 昨日账本状态[\s\S]*?(?=\n## (?!A-))", "## 昨日账本状态\n(旧 paper 账本, v3 不用)\n", facts, count=1)
                if self.sess.booted and inc_on():   # 10/25 用户认可第 1 招: 事实包按小节比对, 和已发过的一字不差的小节不重发(盘前资讯 / 龙虎榜 / 导师信号 / 竞价…)
                    facts = self._facts_delta(facts)
                elif inc_on():
                    self._facts_delta(facts)   # 盘前首跑: 只登记各小节指纹
            except OSError:
                facts = "(今日事实包缺)"
        uni = list(self.line.get("universe") or [])
        with _B01:
            pool0 = chain_steps.pool
            if uni:   # 决策 T 线: 候选池 = 给定标的(不从事实包抓票)
                chain_steps.pool = lambda *a, **k: {c: "本线标的" for c in uni}
            try:
                f01, P, px, nav = chain_steps.build_01(self.skill, self.D, at, why, state, strat, fired, quotes, facts, oc, "(同一会话: 上一版的 02 / 06 见前文)", live=not self.dry,
                                                        inc=self.__dict__.setdefault("_inc_rows", {}) if inc_on() and self.sess.booted else None)
                if inc_on() and not self.sess.booted:   # 盘前首跑发了全表 → 登记每行的价 / 涨跌, 之后触发只发变化
                    self._inc_rows = dict(chain_steps.LAST_ROWS)
            finally:
                chain_steps.pool = pool0
        names = chain_steps.names(self.D)
        f01 = f01 + self.stock_block(P, at, names)   # 10/23 01:5x 用户问: 转债进了候选池, 正股要跟着进(竞价 / 盘口), 原来 01 只有转债一行、模型写"正股竞价未知"
        prev_pool = getattr(self, "_pool_src", None)
        if prev_pool is not None:   # 10/24 模块 4: 候选池进出留痕(进了谁、出了谁、来源)
            add = {c: s for c, s in P.items() if c not in prev_pool}
            out_ = {c: s for c, s in prev_pool.items() if c not in P}
            if add or out_:
                self.ev(kind="候选池变化", add=[f"{c}({s})" for c, s in add.items()][:12], out=[f"{c}({s})" for c, s in out_.items()][:12])
        self._pool_src = dict(P)
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

        mimic = self.line.get("kind") != "dt"
        # 10/24 用户批: 05 改机械风控(PAPER_05=mech), 04 之前算好上限给模型看, 06 落地后执行器强制
        try:
            st0 = state.get("start") or {}
            nav_open = (float(st0.get("cash") or 0) + sum(int(q.get("qty") or 0) * (chain_steps.prev_close(c, self.D) or q.get("cost") or 0) for c, q in (st0.get("positions") or {}).items())) if st0 else nav
            m05 = H.mech05(self.line, self.D, state, nav, nav_open or nav)
        except Exception as e:   # noqa: BLE001
            m05 = {"max_new": -1, "pause_buy": False, "text": f"05 机械风控算不出来({e!r})"[:200]}
            self.ev(kind="05 机械风控失败", err=repr(e)[:200])
        use_mech05 = (_flag0("PAPER_05", "mech") or "mech").strip() == "mech"
        gate_on = (_flag0("PAPER_GATE04", "1") or "1").strip() == "1" and mimic
        req04 = (chr(10) * 2 + m05["text"] + (H.REQ04 + H.RULES_REQ + (H.DEFAULT_REQ if (_flag0("PAPER_DEFAULT_REQ", "1") or "1") == "1" else "") if gate_on else "")) if use_mech05 or gate_on else ""
        ask_on = gate_on and (_flag0("PAPER_ASK", "1") or "1").strip() == "1"   # 10/25 用户批 ask 机制: 04 必答 ask, 代码代查, 只记录不打回
        if ask_on:
            import ask_q as AQ
            req04 += AQ.ASK_REQ
        one03 = self.d03_mode() == "one"
        sh02 = None
        if gate_on:   # 10/24 📋1: 02 全体共用(市况会话 market02.py 写); 有就直接用, 本线不再自己写 02
            try:
                import market02 as M2
                sh02 = M2.latest(self.D, at) if M2.shared_on() else None
            except Exception as e:   # noqa: BLE001
                self.ev(kind="02 共用读取失败", err=repr(e)[:200])
        if not self.sess.booted:
            r02 = (M2.block(sh02) + chr(10) * 2 + "上面是今天的全部材料和全体共用的 02 市况(不用重写)。这一条只回复「收到」两个字, 下一条做 04。") if sh02 else (H.ASK02_V2 if gate_on else ASK02)
            if sh02:
                T["shared02"] = sh02.get("t")
                self._seen02 = sh02.get("t")
            noon = getattr(self, "_noon_handoff", None)
            if noon:   # 午休换会话: 交接放在材料之后、02 指令之前(共用开头不动 → 照样吃缓存)
                r02 = noon + r02
                T["noon"] = at
            W = None
            if self.line.get("kind") != "dt":   # 10/24 用户定: 必查范围 = 持仓 + 发哥 + 入选导师 T-1 + UP + 盘前提到 + 候选池前 50(全量, 编号全天固定)
                try:
                    import watch_set as WS
                    W = WS.build(self.D, list((state.get("positions") or {}).keys()), list(P))
                except Exception as e:   # noqa: BLE001
                    self.ev(kind="必查范围失败", err=repr(e)[:200])
            self._watch, self._ereg = dict(W or {}), {}
            msg, stat = pack.boot_msg(self.line, self.D, f01, P, names, state, r02, watch=W, ereg=self._ereg)   # 10/24 步骤边界 v2
            self._seen = set(W or []) | set((state.get("positions") or {}).keys()) | set(list(P)[:pack.MAX_CHECK])
            self._boot_text = msg
            self._must_save()
            if stat.get("must_full"):   # 10/25 分级进查询: 简版票的完整必查落盘, ./q must <代码> <线号> 取回
                mf = stat.pop("must_full")
                (self.dir / "must_full.md").write_text(mf, encoding="utf-8")
                import ask_q as AQ   # 10/25 A: 记下哪些票只给了简版, 变焦点时代码补全量(回放 0 次 ./q, 不指望模型自己查)
                self._slim, self._promoted = AQ.slim_codes(msg, mf), set()
                T["slim_n"] = len(self._slim)
            T["pack"] = stat
            (vd / "00_boot_msg.md").write_text(msg, encoding="utf-8")
            r2 = self._ask("02", msg, vd, T, 600, boot=True)
            cost += r2["usd"]
            if not r2["ok"]:
                self.sess.st = {}   # 启动失败: 下次重新启动(新会话号)
                self.sess.f.unlink(missing_ok=True)
                return fail(f"启动 02 失败: {r2['err']}")
            if noon:
                self.sess.st["noon"] = at   # 一天只换一次
                self.sess._save()
                self._noon_handoff = None
            if gate_on and not self.fake and not sh02:   # 10/24 步骤边界 v2: 02 闸(共用 02 时由市况会话自己过闸)(态度枚举 / 证据只写编号 / 翻转条件代码能判 / 篇幅), 不过打回一次
                V = H.gate02(r2.get("json"), r2.get("text"), msg)
                if V and not crit and H.cfg()["on_fail"] == "retry":   # 10/24 用户: 默认 guide = 只记录不打回
                    rg = self._ask("02_gate", "你的 02 没通过 harness 闸:" + chr(10) + "- " + (chr(10) + "- ").join(V[:10]) + chr(10) * 2 + "只做一件事: 按原来的判断改正, 输出同格式的完整最终 ```json(不要重新分析)。", vd, T, 120)
                    cost += rg["usd"]
                    V2 = H.gate02(rg.get("json"), rg.get("text"), msg) if isinstance(rg.get("json"), dict) else V
                else:
                    V2 = V
                if V:
                    self.ev(kind="02 闸", n=len(V), after_retry=len(V2), items=V[:6])
                    T["gate02"] = {"first": V[:10], "after": V2[:10]}
            d03 = ""
            if self.line.get("debate"):
                if one03:
                    r3 = self._d03_one("", vd, T, material=msg, crit=crit)
                    cost += r3["usd"]
                    d03 = "上面 03 已经写了空方和多方; 请你作为裁判, 在理由里写清采纳了哪方哪条、为什么。" + (" 每只 建 / 加 的票在 json 里写 \"rebut\": 空方最有力的那条、你怎么回应。" if gate_on else "") + chr(10) * 2
                else:
                    d03, c3 = self._debate(vd, T)
                    cost += c3
            r4 = self._ask("04", d03 + ASK04_BOOT + req04 + (H.req_checked(msg) if gate_on else ""), vd, T, lim)
        else:
            base = list(dict.fromkeys([*state.get("positions", {}), *[x["code"] for x in (strat or {}).get("codes") or []], *uni]))
            self._must_load()
            tags = None
            focus = base
            if self._watch and self.line.get("kind") != "dt":   # 10/24: 必查范围动态出池(只影响必查, 不影响 3 秒盘口 / 候选池)
                try:
                    import watch_set as WS
                    for c in list(P)[:WS.POOL_N]:
                        self._watch.setdefault(c, ["候选池前50"])
                    W2, drop = WS.prune(self._watch, at, set(getattr(self, "_mentioned", set())) | set(base), list(P))
                    if drop:
                        self.ev(kind="必查动态出池", n=len(drop), out=[f"{c}({(tg or ['-'])[0][:20]})" for c, tg in drop][:20])
                    self._watch = dict(W2)
                    focus, tags = list(dict.fromkeys([*base, *W2])), W2
                except Exception as e:   # noqa: BLE001
                    self.ev(kind="必查动态出池失败", err=repr(e)[:200])
            msg, n = pack.trigger_msg(self.line, self.D, f01, P, names, state, quotes, focus, ASK04_TRIG, tags=tags, ereg=self._ereg, seen=self._seen,
                                     hot=set(base) | set(getattr(self, "_mentioned", set())))   # 10/24: 只给 持仓 / 上一版 04·06 提到的 / 新进的票 重发价位
            self._seen |= set(focus)
            prom = self._promote(set(base) | set(getattr(self, "_mentioned", set())) | set(re.findall(r"\b\d{6}\b", why or "")), "焦点")
            if prom:   # 10/25 A: 盘前只给过简版的票变成焦点 → 完整必查放进这次的材料(在提问之前)
                head_, sep_, tail_ = msg.rpartition("\n---")
                msg = (head_ + "\n\n" + prom + sep_ + tail_) if sep_ else (msg + "\n\n" + prom)
                T["promoted"] = list(self._promoted_now)
            self._must_save()
            if sh02 and sh02.get("t") != getattr(self, "_seen02", None):   # 02 共用市况刷新了 → 放在这次触发消息最前面
                msg = M2.block(sh02) + chr(10) * 2 + msg
                self._seen02 = sh02.get("t")
                T["shared02"] = sh02.get("t")
            (vd / "00_trigger_msg.md").write_text(msg, encoding="utf-8")
            fast = why.startswith("板事件") and (X.flag("LIVE_BOARD_FAST", "1") or "1") == "1" and isinstance(getattr(self, "_last04", None), dict) and not auction
            if fast:   # 10/26 用户批: 板事件 → 先只跑 06 快裁(沿用上一版 04 的选票, 不新增票), 同时排队一轮整链重审(未成交的单由重审版替换)
                r4 = {"ok": True, "json": self._last04, "text": "(板事件快裁: 沿用上一版 04, 没有重跑 02~04)", "usd": 0.0, "err": ""}
                T["fast06"] = True
                with self.lock:
                    rr = "板事件后整链重审: " + why[4:][:200]
                    if rr not in (self.queued or ""):
                        self.queued = f"{self.queued}; {rr}" if self.queued else rr
                        self.queued_counted = False
                self.ev(kind="板事件快裁", why=why[:200])
            elif self.line.get("debate") and not auction:   # 带 03: 先把 01 交给主会话(只读), 再分叉多空, 最后 04 裁判
                core = msg.rsplit("---", 1)[0]
                if one03:   # 一次调用: 这次的变化 + 03 合成一条消息
                    r3 = self._d03_one(core, vd, T, material=msg, crit=crit)
                    cost += r3["usd"]
                    d03 = "上面 03 已经写了空方和多方; 请你作为裁判, 在理由里写清采纳了哪方哪条、为什么。" + (" 每只 建 / 加 的票在 json 里写 \"rebut\": 空方最有力的那条、你怎么回应。" if gate_on else "") + chr(10) * 2
                else:
                    r1 = self._ask("01", core + chr(10) * 2 + "---" + chr(10) * 2 + "先只读这次的变化和必查结果, 回复「收到」即可, 下一条消息再做 04。", vd, T, 120)
                    cost += r1["usd"]
                    d03, c3 = self._debate(vd, T)
                    cost += c3
                r4 = self._ask("04", d03 + ASK04_TRIG + req04 + (H.req_checked(msg) if gate_on else ""), vd, T, lim)
            else:
                r4 = self._ask("04", msg + req04 + (H.req_checked(msg) if gate_on else ""), vd, T, lim)
        cost += r4["usd"]
        self.facts_sent = src
        if not r4["ok"] and not r4["text"]:
            return fail(f"04 失败: {r4['err']}")
        if not T.get("fast06") and isinstance(r4.get("json"), dict):
            self._last04 = r4["json"]   # 板事件快裁沿用这一版 04
        if gate_on and not self.fake and not T.get("fast06"):   # 10/24 用户批: 04 内容闸(必填深度 / 广度字段、E 编号真实、负样本不当依据、确定性用词带百分比); 不过 → 打回一次
            material = (vd / ("00_boot_msg.md" if T["boot"] else "00_trigger_msg.md")).read_text(encoding="utf-8")
            if not T["boot"]:   # 10/24: E 编号全天固定, 触发消息只重发随价格变的项 → 闸要合看盘前首跑材料
                material = self._boot_material() + chr(10) * 2 + material
            held_now = set((state.get("positions") or {}).keys())
            need_rb = bool(self.line.get("debate")) and one03 and "03" in T["steps"]
            V = H.gate04(r4.get("json"), r4.get("text"), material, held=held_now, need_rebut=need_rb)
            V2 = V
            if V and not crit and H.cfg()["on_fail"] == "retry":
                rg = self._ask("04_gate", H.gate04_msg(V) + H.req_checked(material), vd, T, 180)
                cost += rg["usd"]
                if isinstance(rg.get("json"), dict) and rg["json"].get("picks") is not None:
                    r4 = {**r4, "json": rg["json"]}
                    V2 = H.gate04(rg["json"], rg.get("text"), material, held=held_now, need_rebut=need_rb)
            if V:
                self.ev(kind="04 内容闸", n=len(V), after_retry=len(V2), crit=crit, items=V[:6])
                T["gate04"] = {"first": V[:15], "after": V2[:15]}
            tgr = H.tg_reply_check(r4.get("json"), material)   # 10/25 用户选 B: 电报点名回应只记录, 不打回
            if tgr["need"]:
                self.ev(kind="电报点名回应", **tgr)
                T["tg_reply"] = tgr
            dfc = H.default_check(r4.get("json"))   # 10/25 B: 默认动作 / 偏离要引窄规则(只记录)
            if dfc["n"]:
                self.ev(kind="04 默认动作", **dfc)
                T["default"] = dfc
            rcs = H.rules_check(r4.get("json"), material)   # 10/25 用户定: 04 考虑过的规则只记录, 等看通过率再定打不打回
            self.ev(kind="04 考虑过的规则", **rcs)
            T["rules_considered"] = rcs
        if not auction and not use_mech05:
            try:
                stats = chain_steps.mimic_stats(self.skill, self.D, state, px)
            except Exception as e:   # noqa: BLE001
                stats = f"(拟人统计不可用: {e!r})"[:200]
            r5 = self._ask("05", ASK05.format(stats=stats), vd, T, 120)
            cost += r5["usd"]
        elif use_mech05:
            (vd / "05_mech.json").write_text(json.dumps(m05, ensure_ascii=False, indent=1), encoding="utf-8")
        a06 = chain_steps.ASK["06"].format(
            auction="现在是集合竞价阶段: 想在 09:25 竞价成交的规则加 \"auction\": true(买价 ≥ 撮合价 / 卖价 ≤ 撮合价按撮合价一次成交), 没加的 09:30 起生效。" if auction else "",
            auc_field='"auction": true|false, ' if auction else "")
        a06 = "【06 终裁】" + a06.split("】", 1)[-1] + ("\n【harness 指引】06 只把 04 的结论落成单: 新开买单写 04 选了 建 / 加 的票(或上一版已挂的); 04 判清仓的票不再买; 不改 04 的选票和方向。" if gate_on else "") + "\n每条规则的 why 末尾写 `依据：规则编号 / E编号 / 相似日 / 关键价位 / 卖点 / 题材`(可多项, 没有写 `依据：无(理由)`)。" + ("\n【K 线看法(10/25 用户定: K 线是 06 输出的一部分)】codes 里每只有挂单的票加 \"kline\": {\"box\": \"日线 / 15 分钟箱体上下沿 + 现价位置(引用必查「K线结构」的 E 编号)\", \"struct\": \"上升 / 下降 / 震荡 + 关键 K 线事件(假突破 / 假跌破 / 放量长上影 / 缩量回踩…)\", \"view\": \"今天剩余时间 + 明天的走法看法\", \"prob\": {\"ref\": \"E / Q 编号(只能引用必查里代码算好的概率)\", \"value\": 0.0}}; 没有可引用的统计就 \"prob\": {\"ref\": null, \"value\": null, \"why\": \"…\"}" if self.line.get("live") else "") + WAKE_ASK.format(
            card="你是计划模式: 盘中**只有** band 出界或 wake 命中才会叫醒你(成交 / 心跳 / 市况翻转都不会), 所以失效条件要写全。" if self.mode == "plan" else "")
        if self.line.get("live") and (X.flag("LIVE_BOARD_WAKE", "1") or "1") == "1":   # 10/26 用户: 告诉模型板事件会叫醒它, 不用为了怕错过提前排板
            a06 += chr(10) + "【板事件叫醒】你必查池 / 持仓 / 有挂单的票出现 首次封板 / 炸板 / 回封 都会自动叫醒你重判(同票 3 分钟一次), 所以不用为了怕错过提前排板; 排板单只在你确定要在板上买时用。"
        if T.get("fast06"):
            a06 = "【板事件快裁】" + why[:300] + chr(10) + "只处理上一版 04 已选的票和持仓: 买 / 不买 / 撤单 / 改价, 不新增票; 按下面此刻盘口拍板。几分钟后会整链重审, 没成交的单会被重审版替换。" + chr(10) * 2 + a06
        picks_ = [p_ for p_ in ((r4.get("json") or {}).get("picks") or []) if isinstance(p_, dict)] if isinstance(r4.get("json"), dict) else []
        promB = self._promote({str(p_.get("code")) for p_ in picks_ if p_.get("action") in ("建", "加")}, "04 选了")
        if promB:   # 10/25 B: 04 建 / 加 的票之前只看过简版 → 06 拍板前先看完整必查(同一条 06 消息, 不多一轮)
            a06 = promB + "\n\n" + a06
            T["promoted_04"] = list(self._promoted_now)
        if ask_on and isinstance(r4.get("json"), dict):   # 10/25 ask: 04 要的查询 + 代码按情景补的查询 → 本地跑(零 token) → Q1.. 放 06 最前面
            try:
                a06 = self._run_ask(r4["json"], vd, T, crit, state) + a06
            except Exception as e:   # noqa: BLE001  查询出错不拦 06
                self.ev(kind="04 查询失败", err=repr(e)[:200])
        self._fresh_seal = self._seal_map()   # 10/26 林州重机: 记下 06 看盘口那一刻每只票封没封, 落单时对照
        a06 = self.fresh_block(at, P, state, strat, r4.get("json"), px) + "\n\n" + a06   # 10/22 晚用户令: 06 拍板前现取一次此刻盘口 / 竞价(01 是开跑时的快照, 04 想完已过 1~3 分钟)
        if use_mech05:   # 10/24: 机械风控上限给 06 看(超了执行器会剔)
            a06 = m05["text"] + "\n\n" + a06
        if self.line.get("live") and (X.flag("PAPER_STYLE", "1") or "1") == "1":   # 10/26 用户令: 06 选挂法
            a06 += STYLE_ASK
        if self.line.get("live") and why.startswith("开盘前首版") and (X.flag("LIVE_PLAN", "1") or "1") == "1":   # 10/24 模块 6: 实盘线盘前版 = 计划表
            a06 += PLAN_ASK
        (vd / "06_fresh.md").write_text(a06.split("【06 终裁】")[0], encoding="utf-8")
        r6 = self._ask("06", a06, vd, T, lim)
        if T.get("ask"):   # 06 引用了哪些 Q(每晚统计: 要了的查询有没有被用上)
            import ask_q as AQ
            T["ask"]["cited"] = AQ.cited(r6.get("text") or "")
            self.ev(kind="04 查询", **T["ask"])
        cost += r6["usd"]
        s = r6["json"] if isinstance(r6.get("json"), dict) and r6["json"].get("codes") is not None else None
        if s is None and r6["text"] and not self.fake:   # 写了但没出完整 json → 同会话让它立刻誊 json(不作废)
            rf = self._ask("06_finish", "你上一轮没有给出完整的最终 ```json 块。现在只做一件事: 按你上一轮已有的结论, 立刻输出最终 ```json(字段同上), 不要再分析。", vd, T, 90)
            cost += rf["usd"]
            s = rf["json"] if isinstance(rf.get("json"), dict) and rf["json"].get("codes") is not None else None
        if s is None:
            return fail(f"06 失败: {r6['err'] or '没有 json'}")
        slim_left = sorted({str(x.get("code")) for x in s.get("codes") or [] if x.get("rules")} & (getattr(self, "_slim", set()) - getattr(self, "_promoted", set())))
        if slim_left:   # 10/25 B: 06 给只看过简版必查的票下了单(04 没选它、也没成过焦点) → 记一笔, 下一轮触发时代码补全量(_promote 焦点含上一版挂单的票)
            self.ev(kind="06 给简版票下单", codes=slim_left)
            T["slim_orders"] = slim_left
        miss = [r_["id"] for x in s.get("codes") or [] for r_ in x.get("rules") or [] if "依据" not in str(r_.get("why", ""))]
        if miss and not crit and not self.fake:   # 10/25 少重写 ③: 只问缺的那几条的依据(回一个小 json), 代码合并回原单, 不让它重出整份
            re_ = self._ask("06_evidence", f"这些规则的 why 没写依据: {', '.join(miss)}。只回一个小 ```json {{\"规则 id\": \"依据：规则编号 / E编号 / …\"}}, 每条一句, 不要重写整份。", vd, T, 90)
            cost += re_["usd"]
            ev_ = re_.get("json") if isinstance(re_.get("json"), dict) else {}
            if ev_.get("codes") is not None:   # 模型还是重出了整份 → 照旧整份替换
                s = ev_
            else:
                for x in s.get("codes") or []:
                    for r_ in x.get("rules") or []:
                        add = ev_.get(str(r_.get("id"))) or ev_.get(f"{x.get('code')}:{r_.get('id')}")
                        if add and "依据" not in str(r_.get("why", "")):
                            r_["why"] = f"{r_.get('why', '')} {add if str(add).startswith('依据') else '依据：' + str(add)}"
            miss = [r_["id"] for x in s.get("codes") or [] for r_ in x.get("rules") or [] if "依据" not in str(r_.get("why", ""))]
        for x in s.get("codes") or []:
            for r_ in x.get("rules") or []:
                if r_["id"] in miss:
                    r_["why"] = f"{r_.get('why', '')} 依据：无(未补)"
        try:   # 10/24: 记下这一版 04 / 06 提到的票 → 下次触发的必查动态出池用
            self._mentioned = {str(p.get("code")) for p in ((r4.get("json") or {}).get("picks") or []) if isinstance(p, dict)} | {str(x.get("code")) for x in s.get("codes") or []}
            self._must_save()
        except Exception:   # noqa: BLE001
            pass
        if gate_on:   # 10/24 术语闸: 股票简称 / 术语表禁用词(指引模式, 只记录)
            try:
                VT = H.gate_terms((r4.get("text") or "") + chr(10) + (r6.get("text") or ""))
                if VT:
                    self.ev(kind="术语闸", n=len(VT), items=VT[:8])
                    T["terms"] = VT[:15]
            except Exception as e:   # noqa: BLE001
                self.ev(kind="术语闸失败", err=repr(e)[:200])
        if gate_on:   # 10/24 步骤边界 v2: 06 只能落 04 选中的票(建 / 加) + 持仓 + 上一版已有的票; 04 清仓的票不许买 → 机械剔掉
            try:
                drop06 = H.enforce06(s, r4.get("json"), set((state.get("positions") or {}).keys()), {str(x.get("code")) for x in (strat or {}).get("codes") or []},
                                     dry=H.cfg()["only06"] != "drop")
            except Exception as e:   # noqa: BLE001
                drop06 = []
                self.ev(kind="06 越界剔单失败", err=repr(e)[:200])
            if drop06:
                T["dropped06"] = drop06
                self.ev(kind="06 越界剔单" if H.cfg()["only06"] == "drop" else "06 越界(只记录)", dropped=drop06)
        if use_mech05:   # 10/24 用户批: 05 机械硬闸 —— 新开买单超上限 / 暂停新买 → 剔掉, 04 的 market_risk 只能收紧
            try:
                drop05 = H.enforce05(s, m05, set((state.get("positions") or {}).keys()), tighten=(r4.get("json") or {}).get("market_risk") if isinstance(r4.get("json"), dict) else None)
            except Exception as e:   # noqa: BLE001
                drop05 = []
                self.ev(kind="05 机械剔单失败", err=repr(e)[:200])
            if drop05:
                T["dropped05"] = drop05
                self.ev(kind="05 机械剔单", dropped=drop05, max_new=m05.get("max_new"), pause_buy=m05.get("pause_buy"))
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
        """收盘写本线记忆(scripts/paper_line/memory/<线>.md, 下一个交易日启动材料里的「本线记忆」): 开盘 / 收盘持仓、今日成交、最后一版的看法 / 下一步 / 失效条件;
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
        """10/23 00:5x 用户令: 今天芷影 / 刘忆青 / 土豆三本主线(盯盘)出现挂单就推微信(PAPER_PUSH_LINES, 按线号不按 skill —— 同一导师的计划模式 / 噪声 / 03 几本不推);
        新版策略只在"挂单真的变了"时推(同样的单重复出版不推, 省微信配额), 成交照推; 告警(alert)不受限"""
        msg = self._clean(msg)
        raw_head = msg.split(chr(10))[0]
        if self.fake:   # 桩测试不推微信(含告警)
            print("WX(桩)>", msg.replace(chr(10), " | ")[:200])
            return
        if not alert:
            push = {x.strip() for x in (X.flag("PAPER_PUSH_LINES", "") or "").split(",") if x.strip()}
            if self.line.get("live"):   # 实盘线: 盘前各版不逐条推(总控等盘前全部跑完合成一条盘前汇总); 09:19 起只推留下的线(LIVE_PUSH=0 全不推)
                ok = (X.flag("LIVE_PUSH", "1") or "1") == "1" and now().strftime("%H:%M:%S") >= (X.flag("LIVE_KEEP_AT", "09:19:00") or "09:19:00") and not self.dormant()
                push = {self.line["id"]} if ok else set()
            if self.line["id"] not in push:
                self.ev(kind="未推微信", msg=msg[:120])
                return
            if "执行器 v" in msg and "成交" not in msg.split("\n")[0]:
                st_ = self.strategy or {}
                sig = sorted((x["code"], r.get("side"), r.get("op"), r.get("px"), r.get("qty"), r.get("type"), r.get("style")) for x in st_.get("codes") or [] for r in x.get("rules") or [])
                # 10/26 15:3x 用户: 任何一条线挂单 / 叫醒条件 / 成交变了都要推这条线(多线同时出由总线合并) —— 原来"没挂单就不推", 空仓线只剩叫醒线时一条都看不到
                wk = json.dumps(st_.get("wake"), ensure_ascii=False, sort_keys=True, default=str)
                key_ver = "开盘前首版" in msg or "竞价段" in msg   # 10/23 用户问: 盘前版和竞价版一定推(没挂单也推, 让你知道今天的计划)
                if not key_ver and (sig, wk) == getattr(self, "_wx_sig", None):
                    self.ev(kind="未推微信", msg="挂单 / 叫醒条件都没变: " + msg[:80])
                    return
                self._wx_sig = (sig, wk)
            msg = self._pretty(msg)
        else:
            msg = (f"⚠️ [实盘线] {self.line['name']}skill: " if self.line.get("live") else f"⚠️ [paper v3 · {self.line.get('name', self.line['id'])}] ") + msg
        # 10/23 用户批: 原来 stdout / stderr 都丢 DEVNULL, wx_send 拦下(置信度闸 / 限频 / 失败)完全看不见 → 输出追加进本账 wx_send.log
        try:
            wlog = open(self.dir / "wx_send.log", "a", encoding="utf-8")
            wlog.write(f"[{dt.datetime.now():%H:%M:%S}] {msg.splitlines()[0][:80]}\n")
            wlog.flush()
        except Exception:   # noqa: BLE001
            wlog = X.subprocess.DEVNULL
        if self.line.get("live") and (X.flag("PUSH_BUS", "1") or "1") == "1" and not self.dry:   # 10/25 用户批: 进合并推送总线(动态攒批, 同一条线新版顶掉没发出的旧版; 成交 / 告警算急件)
            try:
                sys.path.insert(0, str(ROOT / "scripts" / "hermes"))
                import push_bus as PB
                head0 = msg.split("\n")[0]
                is_ver = head0.startswith("📋")
                PB.enqueue(msg[:3000], src=LDS.ldir(self.line["id"]), urgent=alert or head0.startswith("✅") or "成交" in raw_head, key=f"{self.line['id']}:ver" if is_ver else None, D=self.D)
                return
            except Exception as e:   # noqa: BLE001  总线坏了 → 照旧直接发
                self.ev(kind="推送总线失败, 改直接发", err=repr(e)[:200])
        X.subprocess.Popen([str(X.PY), "-X", "utf8", "scripts/hermes/wx_send.py", msg[:3000], "--raw", "--src", LDS.ldir(self.line["id"])] + (["--dry"] if self.dry else []),
                           cwd=ROOT, creationflags=X.NOWIN, stdout=wlog, stderr=X.subprocess.STDOUT)

    def _pretty(self, msg):
        """10/23 01:3x 用户令: 推微信的挂单要手机 / 电脑微信都好读 —— 短行、不用表格、一张单一块; 版本消息按当前策略重排, 成交按最新一笔重排, 其余加线名抬头"""
        nm = self.line.get("name", self.line["id"]) + ("skill" if self.line.get("live") else "")   # 10/24 用户: 推送导师统一 "<中文名>skill"
        mode = "实盘线" if self.line.get("live") else {"watch": "盯盘", "plan": "计划"}.get(self.mode, "")
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
                    elif r.get("type") == "cond":
                        how = (f"{r['style']}·" if r.get("style") else "") + f"条件单：{r.get('ref')}{'涨' if r.get('dir') == 'up' else '回落'} {r.get('pct')}% 时按{'买' if str(r.get('book', 'b1'))[0] == 'b' else '卖'}{str(r.get('book', 'b1'))[1:]}档"
                    elif r.get("auction"):
                        how = f"竞价 {'≤' if r['side'] == 'BUY' else '≥'}{r['px']}"
                    else:
                        how = f"{'≤' if r['side'] == 'BUY' else '≥'}{r['px']}" + ("（排队）" if r.get("rest") else "") + (f"（{r['style']}·{r.get('_price_src') or '规则价'}）" if r.get("style") else "")
                    pf = ""
                    if r.get("type") not in ("board_dip", "cond") and not r.get("auction"):
                        try:
                            import fill_prob as FP
                            lo_, hi_ = getattr(self, "_dayhl", {}).get(x["code"], (None, None))
                            fr = FP.prob(x["code"], self.D, r["side"], float(r["px"]), lo_, hi_)
                            if not fr.get("err"):
                                pf = " · 今天到过" if fr.get("touched") else f" · 成交概率 {fr['p15']:.0%}" + (f"(此刻 {fr['now_px']:.0%})" if fr.get("now_px") is not None else "")
                        except Exception:   # noqa: BLE001
                            pass
                    tgt = ""
                    try:   # 10/25 用户选 J: 推送里标出被电报点名的票(哪一类 / 领跟)
                        import telegraph_now as TGN
                        tgt = TGN.tag(x["code"], self.D, now().strftime("%H:%M:%S")) if (X.flag("TG_TAG_PUSH", "0") or "0") == "1" else ""   # 10/25 用户: 周一先不上, 看推送密不密, 周二再开
                    except Exception:   # noqa: BLE001
                        pass
                    L += [f"▪ {side_cn.get(r['side'], r['side'])} {x.get('name') or ''} {x['code']}" + (f" {tgt}" if tgt else ""), f"  {r['qty']} 股{self.qty_pct(x['code'], r['side'], r['qty'], r['px'])} · {how}{pf}" + (f" · 等 {r['after']} 成交后" if r.get("after") else ""),
                          f"  {str(r.get('why') or '').split('【')[0][:50]}"]
                    tg = re.search(r"【([^】]*CLS电报点名[^】]*)】", str(r.get("why") or ""))
                    if tg:   # 10/24 用户令: 电报点名备注推送里单独一行, 不被 50 字截掉
                        L.append(f"  📣 {tg.group(1)}")
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
        return (f"[实盘线] {nm}: " if self.line.get("live") else f"[paper v3 · {nm}] ") + msg

    # ---------- 炸板接(10/22 晚用户教: T 字板开板时按卖二接, 回封就赚; 现场叫模型来不及, 由 06 预写、执行器每 3 秒机械判) ----------
    def _limit_up(self, c):
        if not hasattr(self, "_lim"):
            self._lim = {}
        if c not in self._lim:
            pc = X.prev_close(c, self.D)
            self._lim[c] = X.AR.limit_prices(c, self.D, pc)[0] if pc else None
        return self._lim[c]

    def tick(self, hm, auction=False):
        dev925 = None
        if auction is True and self.line.get("live") and not self.dormant():   # 模块 7: 09:25 竞价定格 → 撮合前再对照一次计划情景(停用不符情景的单), 偏离就叫模型
            dev925, _ = self.scen_compare("09:25")
        if dev925:
            threading.Timer(1.0, lambda: self.restrategize("竞价定格偏离计划: " + "; ".join(dev925)[:300], counted=False)).start()
        if self.line.get("live") and (auction is True or (not auction and hm >= "09:30")) and not dev925:
            self._guard(hm)
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
        if not auction and hm >= "09:30" and self.line.get("live"):
            self._board_watch(hm)
        fills = super().tick(hm, auction)
        if auction is True:   # 条件单的"开盘价" = 09:25 撮合价
            self._dopen = {c: q_.get("p") for c, q_ in self.feed.q.items() if q_.get("p")}
        if auction or hm < "09:30":
            return fills
        with self.lock:
            for c, q_ in self.feed.q.items():   # 没赶上 09:25 的票: 第一跳当开盘价
                if q_.get("p"):
                    self.__dict__.setdefault("_dopen", {}).setdefault(c, q_["p"])
            cmore = self._cond_tick(hm)
            if cmore:
                self._save()
        for t in cmore:
            self.wx(f"【{self.skill} 成交(条件单) {t['t']}】{t['side']} {t.get('name') or ''}{t['code']} {t['qty']}@{t['px']} 条件 {t['cond']} | 规则 {t['rule']} | 现金 {self.state['cash']:.0f}")
        fills = fills + cmore
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
        import chain_steps
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
        auc = chain_steps.auction_snap(self.D, at) if at < "09:31:00" else {}
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
        import chain_steps
        t = now().strftime("%H:%M:%S")
        picks = [str(x.get("code")) for x in ((j4 or {}).get("picks") or []) if isinstance(x, dict) and x.get("code")]
        codes = list(dict.fromkeys([*state.get("positions", {}), *[x["code"] for x in (strat or {}).get("codes") or []], *picks, *list(P)[:10],
                                    *(self.line.get("universe") or [])]))[:20]
        names = chain_steps.names(self.D)
        L = []
        if t < "09:25:30":
            cur, base = chain_steps.auction_snap(self.D, t), chain_steps.auction_snap(self.D, at0)
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
    """同一本账只许一个执行器: 锁文件存 pid; 持有者还活着且命令行是 executor.py --line 同线 → 拒绝启动(v2 的 take_lock 只认 exec_base.py)"""
    import psutil
    f = ROOT / "scripts" / "temp" / f"line_{line_id}.lock"
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
    L = lines(a.date)
    ln = L[a.line]
    idx = list(L).index(a.line)
    # v2 的全局开关按本进程覆盖(flag() 先读环境变量): 竞价复核 09:20:00、尾盘错峰、不走土豆竞价测试
    os.environ.update(EXEC_AUC_TEST_SKILLS="", EXEC_AUC_AT=X.flag("PAPER_AUC_AT", "09:20:00") or "09:20:00", EXEC_SHADOW_EFFORT="", EXEC_FLEET_VARIANTS="",
                      EXEC_TAIL_AT=(dt.datetime.strptime(X.flag("PAPER_TAIL_AT", "14:51:00") or "14:51:00", "%H:%M:%S") + dt.timedelta(seconds=8 * idx)).strftime("%H:%M:%S"),
                      EXEC_EFFORT=X.flag("PAPER_EFFORT", "high") or "high", EXEC_FIRST_EFFORT=X.flag("PAPER_EFFORT", "high") or "high", EXEC_AUC_EFFORT=X.flag("PAPER_EFFORT", "high") or "high")
    os.environ["EXEC_FULL_PAUSE"] = "0"   # 10/22 晚用户批: v3 满仓 / 06 判"今天不再操作"都不停触发(10/22 刘忆青 09:37 停触发, 错过真人 10:56 卖 + 13:06 换股)
    if ln["kind"] == "dt":
        os.environ["EXEC_HB_DYNAMIC"] = "0"   # 心跳按导师真人间隔算, 决策 T 线没有导师账本 → 固定 60 分钟
    first = (dt.datetime.strptime(X.flag("PAPER_FIRST", "09:00:00") or "09:00:00", "%H:%M:%S") + dt.timedelta(seconds=20 * idx)).strftime("%H:%M:%S")
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
