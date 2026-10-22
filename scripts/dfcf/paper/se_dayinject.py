# -*- coding: utf-8 -*-
"""se_dayinject.py — 策略执行器全天回放的"注入演示"(10/21 晚用户令: 所有可能发生的极端情况都展示出来; 没自然发生的用注入补齐, 页面标"注入(非自然发生)")

每个场景 = 从主回放(se_dayreplay.py)某一分钟的快照分叉, 在一段时间窗里用同一个回放引擎跑, 只改一处(注入点), 其余全照真实行情 / 真实规则代码:
  - 模型一律用桩(未真调模型, 零花费), 各步耗时 / 成败由场景给定(虚拟时钟); se_chain.run 的降级 / 预算逻辑、se_exec.SE.check 校验、
    se_exec.SE._restore(续跑) / _init_state(次日接续) 都是调真代码
  - 产物: <主回放目录>/inject/<场景>/ (events.jsonl / actions.jsonl / 每次链子目录 / summary.json / scenario.json)
用法: python se_dayinject.py --base results/inv-stock/paper/day_replay/2026-10-21/meiyuelu [--only s01,s02]
"""
import argparse
import copy
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import se_dayreplay as R   # noqa: E402  (先 import: 它负责把 scripts/chain 排到 sys.path 前面)
from se_dayreplay import E, SC, SX, hs, sh, jl   # noqa: E402

CONN = "APIConnectionError: Connection error.(注入: 模拟 ECONNRESET, 10/21 09:56 实盘真遇到过)"


def keep_strategy(eng, note="桩: 未真调模型, 06 原样沿用当前生效策略"):
    s = copy.deepcopy(eng.strategy) or {"codes": []}
    s["view"] = f"({note}) " + str(s.get("view") or "")[:200]
    return s


def keep_unfired(eng, extra=None):
    """桩 06: 沿用当前策略里还没成交的规则(新版本 fired 会清零, 原样沿用会让已成交规则再成交一次)"""
    s = keep_strategy(eng, "桩: 未真调模型, 06 沿用当前策略里未成交的规则")
    s["codes"] = [{**x, "rules": [r for r in x.get("rules") or [] if f"{eng.ver}:{x['code']}:{r['id']}" not in eng.fired]} for x in s.get("codes") or []]
    for c, r in (extra or {}).items():
        x = next((y for y in s["codes"] if y["code"] == c), None)
        if x is None:
            x = {"code": c, "name": SC.names(eng.D).get(c, ""), "band": [0.01, 9999.0], "rules": []}
            s["codes"].append(x)
        x["rules"].append(r)
    return s


def plan_seq(seq):
    """seq[i] = 第 i 次链的方案(dict 或 callable(eng, kind, why, ts)); 超出用最后一个; 方案里没给 06 json 的 → 沿用当前策略"""
    st_ = {"i": 0}

    def fn(eng, kind, why, ts):
        p = seq[min(st_["i"], len(seq) - 1)]
        st_["i"] += 1
        p = p(eng, kind, why, ts) if callable(p) else copy.deepcopy(p)
        p.setdefault("06_final", {})
        if "json" not in p["06_final"] and "fail" not in p["06_final"] and "stall" not in p["06_final"]:
            p["06_final"]["json"] = keep_strategy(eng)
        return p
    return fn


def all_fail(secs=2.5):
    return {k: {"fail": CONN, "secs": secs} for k in R.STEP_ORDER}


def px_now(eng, c, ts):
    return (eng.quote(c, ts) or {}).get("p") or eng.M.limits(c)[0]


def narrow(eng, ts, pct):
    """把当前策略每只票的 band 收到现价 ±pct(规则清空): 演示出区间反复触发"""
    s = copy.deepcopy(eng.strategy) or {"codes": []}
    codes = s.get("codes") or []
    if not codes:
        codes = [{"code": c, "name": SC.names(eng.D).get(c, "")} for c in list(eng.state["positions"])[:2] or ["600900"]]
    for x in codes:
        p = px_now(eng, x["code"], ts)
        x["band"] = [round(p * (1 - pct), 3), round(p * (1 + pct), 3)]
        x["rules"] = []
    s["codes"], s["view"] = codes, f"(注入: band 收窄到现价 ±{pct * 100:.2f}%, 规则清空; 桩未真调模型)"
    return s


def quiet(eng, ts, pct=0.2):
    """band 放到 ±20%、规则清空: 只让心跳 / 翻转 / 指数事件说话"""
    s = narrow(eng, ts, pct)
    s["view"] = "(注入: 宽区间无规则, 只观察心跳 / 翻转 / 指数事件; 桩未真调模型)"
    return s


# ---------------- 场景 ----------------
def scenarios(D):
    S = []

    def add(sid, title, items, fork, t_end, desc, **cfg):
        S.append({"id": sid, "title": title, "items": items, "fork": fork, "t_end": t_end, "desc": desc, "cfg": cfg})

    add("s01_api_down", "API 断连 → 90 秒重试 → 连续失败放弃", ["api_retry", "api_giveup"], "10:40:00", "10:50:00",
        "10:40:20 手动叫一次重定; 之后 4 次链的每个 API 调用都返回连接错误(各 2.5 秒)。02 失败降级、03 两边失败、04 失败 → 本次作废沿用上一版 → 90 秒后自动重试 → … 第 4 次失败后 fail_n=4 > 3 不再重试。",
        kicks=[("10:40:20", "注入: 叫一次重定(随后 API 全断)")], plan=[all_fail()] * 4 + [{}])
    add("s02_02_timeout", "02 市况超时 → 用机械市况继续", ["deg_02", "kick"], "11:00:00", "11:06:00",
        "11:00:10 手动叫重定; 02 卡 50 秒 > 02 步上限 45 秒 → se_chain 中断 02, 用开盘实况机械判定当市况, 03~06 照跑。",
        kicks=[("11:00:10", "注入: 叫一次重定(02 将超时)")], plan=[{"02_market": {"secs": 50}}])
    add("s03_03_oneside", "03 空方失败 → 只有多方, 链继续", ["deg_03"], "11:10:00", "11:16:00",
        "11:10:10 手动叫重定; 03 空方 API 连接错误, 多方正常 → 03 只剩一边(无对辩), 04~06 照跑。",
        kicks=[("11:10:10", "注入: 叫一次重定(03 空方将失败)")], plan=[{"03_bear": {"fail": CONN, "secs": 3}}])
    add("s04_05_skip", "前面慢 → 05 时间不够只用脚本统计", ["deg_05"], "11:20:00", "11:27:00",
        "11:20:10 手动叫重定; 02 40 秒 + 03 34 秒 + 04 44 秒 → 04 结束剩约 51 秒 < 70 秒 → 05 不调模型只用脚本拟人统计, 06 照跑。",
        kicks=[("11:20:10", "注入: 叫一次重定(前几步都慢)")], plan=[{"02_market": {"secs": 40}, "03_bull": {"secs": 34}, "03_bear": {"secs": 30}, "04_pick": {"secs": 44}}])
    add("s05_04_06_fail", "04 失败 / 06 失败 → 本次作废沿用上一版 → 重试成功", ["fail_04", "fail_06", "api_retry"], "13:05:00", "13:15:00",
        "13:05:10 手动叫重定; 第 1 次链 04 连接错误 → 作废(沿用上一版) → 90 秒后重试; 第 2 次链 06 输出没有可解析 JSON → 作废 → 90 秒后重试; 第 3 次正常生效。",
        kicks=[("13:05:10", "注入: 叫一次重定(04 将失败)")],
        plan=[{"04_pick": {"fail": CONN, "secs": 3}}, {"06_final": {"fail": "没有可解析的 ```json 块(stop=max_tokens)(注入)", "secs": 60}}, {}])
    add("s06_over_170", "整条链超 170 秒 + 期间来事件排队合并", ["over_170", "queue_merge"], "13:20:00", "13:32:00",
        "13:20:10 手动叫重定; 02~05 正常, 06 首字节前卡死 150 秒(anthropic 客户端 timeout=150; claude_api.stream 的 deadline 只在收到流事件时检查, 卡在首字节前管不住) → 06 失败作废, 整条链约 240 秒 > 180;"
        " 链在跑的 13:22:30 再来一次手动重定 → 排队, 链结束立即合并补跑。",
        kicks=[("13:20:10", "注入: 叫一次重定(06 将卡死)"), ("13:22:30", "注入: 链在跑时再叫一次")],
        plan=[{"06_final": {"stall": True, "secs": 150}}, {}])
    add("s07_cooldown_flip", "冷却挡掉 → 翻转冷却结束后补触发", ["cooldown", "flip_kept"], "10:05:00", "10:20:00",
        "10:05:55 手动叫重定(必判, 计冷却起点) → 10:06 开盘实况 偏强→震荡 翻转落在 3 分钟冷却里被挡, 翻转保留 → 冷却结束(10:08:55)补触发 → 10:09 震荡→偏弱 又落在新冷却里 → 再补触发。",
        kicks=[("10:05:55", "注入: 叫一次重定(制造冷却起点)")], flips_reset=["10:06", "10:09"], plan=[{}])
    add("s08_band_cap", "出区间反复触发 → 到自由触发上限 → 只机械执行", ["band_repeat", "cap"], "10:31:00", "11:31:00",
        "10:31 起把每只票 band 收到现价 ±0.15%(每版生效都按当时现价重设), 价格一动就出区间; 自由触发每 5 分钟(10:30 后冷却)一次, 第 6 次后到上限(上限 = SX.real_cap = 6), 之后只机械执行, 心跳仍照跑(不占上限)。",
        n_re=0, init_strategy=lambda eng, ts: narrow(eng, ts, 0.0015), plan=[lambda eng, k, w, ts: {"06_final": {"json": narrow(eng, ts, 0.0015)}}])
    add("s09_hb_tiers", "心跳各时段档位(假设导师真人决策间隔很短 → 时段下限说了算)", ["hb_tiers", "hb_push"], "09:31:00", "14:57:00",
        "梅月路真人决策间隔 P75 = 43 分钟, 比所有时段下限都大, 所以真实回放里心跳全天都是 43 分钟。这里注入: 把 P75 换成 3 分钟(样本足), 心跳 = 时段下限: 09:30 5 分 / 10:00 10 / 10:30 15 / 13:00 30 / 14:30 10 / 14:50 5;"
        " 策略换成宽区间无规则, 只看心跳; 任何触发(含翻转)都把心跳往后推。",
        hb_fn=lambda hm: max(3, next(f for t, f in reversed(SX.HB_FLOOR) if hm >= t) if hm >= "09:30" else 5), index_event=False,
        init_strategy=lambda eng, ts: quiet(eng, ts), plan=[lambda eng, k, w, ts: {"06_final": {"json": quiet(eng, ts)}}])
    add("s10_index_event", "指数事件(θ 调低演示)", ["index_event"], "09:31:00", "14:57:00",
        "上证 10/21 全天单边慢跌, 动态 θ≈0.29%: 主回放里检查点之间若没走满 θ 就不会触发。这里注入: θ 系数 X 从 0.45 调到 0.15(被下限 0.27σd 截住, θ≈0.18%), 宽区间无规则, 看指数事件按检查点(上次触发时刻)滚动触发, 第 5 次起每次加码 25%; 自由触发上限照样管它。",
        idx_kw={"x": 0.15}, init_strategy=lambda eng, ts: quiet(eng, ts), plan=[lambda eng, k, w, ts: {"06_final": {"json": quiet(eng, ts)}}])
    add("s11_auction", "竞价单: 一条按撮合价成交、一条没够到 09:30 起转普通限价单", ["auction_fill", "auction_limit"], "09:15:00", "09:45:00",
        "从 09:15 起(10 万空仓), 首版(桩)给两条竞价单: 长江电力 BUY 价≤29.75 ×1000(09:25 撮合价 29.70 → 成交)、中国银行 BUY 价≤7.15 ×1000(撮合价 7.17 没够到 → 09:30 起当限价单, 09:30:12 跌到 7.12 成交)。",
        fresh=True, plan=[{"06_final": {"json": {"view": "(注入: 竞价单演示; 桩未真调模型)", "codes": [
            {"code": "600900", "name": "长江电力", "band": [29.0, 30.2], "rules": [{"id": "a1", "side": "BUY", "op": "<=", "px": 29.75, "qty": 1000, "auction": True, "why": "注入: 竞价买(够得到)"}]},
            {"code": "601988", "name": "中国银行", "band": [7.0, 7.3], "rules": [{"id": "a1", "side": "BUY", "op": "<=", "px": 7.15, "qty": 1000, "auction": True, "why": "注入: 竞价买(够不到)"}]}],
            "valid_until": "10:00"}}}, lambda eng, k, w, ts: {"06_final": {"json": keep_unfired(eng)}}])
    add("s12_limit", "涨停买不进 / 跌停卖不出(真实封板盘口)", ["limit_up", "limit_down", "void_close"], "14:03:00", "15:00:00",
        "注入持仓: 昨日持有 603200 上海洗霸 1000 股(可卖); 注入规则: SELL 603200 价≥47.88(跌停价) ×1000 —— 13:26:38 起跌停封板(买一为空)直到 14:57 → 卖不出, 收盘作废;"
        " BUY 603629 利通电子 价≤92.03(涨停价) ×100 —— 14:02 起涨停封板(卖一为空) → 买不进, 14:48:30 开板(卖一 91.75) → 成交。",
        set_state={"cash": 50000.0, "positions": {"603200": {"qty": 1000, "cost": 53.0, "sellable": 1000}}, "trades": []},
        init_strategy=lambda eng, ts: {"view": "(注入: 涨跌停封板演示; 桩未真调模型)", "codes": [
            {"code": "603200", "name": "上海洗霸", "band": [40.0, 60.0], "rules": [{"id": "x1", "side": "SELL", "op": ">=", "px": 47.88, "qty": 1000, "why": "注入: 跌停价卖"}]},
            {"code": "603629", "name": "利通电子", "band": [80.0, 100.0], "rules": [{"id": "x2", "side": "BUY", "op": "<=", "px": 92.03, "qty": 100, "why": "注入: 涨停价买"}]}]},
        plan=[lambda eng, k, w, ts: {"06_final": {"json": keep_unfired(eng)}}])
    add("s13_t1_cash_sell", "T+1 当日买的卖不了 / 现金不够按现金截断 / 卖出超过可卖截断 / 没钱", ["t1", "cash_trunc", "sell_trunc", "no_cash"], "10:40:00", "10:50:00",
        "注入账户: 现金 5 万 + 昨日持有 601988 中国银行 1000 股(可卖 1000)。注入一版「做T」规则(经 se_exec.SE.check 真代码校验, 卖出合计 1400 > 可卖 1000 只提示不剔), 同一轮按顺序撮合:"
        " ① SELL 601988 ≥7.0 ×700 → 成交(可卖剩 300) ② SELL 601988 ≥7.0 ×500 → 按可卖截断成 300 ③ BUY 601988 ≤7.5 ×1000 → 成交(当日买入, 可卖 0)"
        " ④ SELL 601988 ≥7.0 ×200 → 持有 1000 但可卖 0 = T+1 卖不了 ⑤ BUY 600900 ≤现价+0.5 ×100000 → 按现金截断 ⑥ BUY 600900 ×100 → 现金不够 1 手 = 没钱。"
        " 成交后必跑的下一版(桩)给 600900 挂 SELL(刚买的, 可卖 0) → 校验按「超过持仓」剔除(T+1 在校验阶段就拦)。",
        set_state={"cash": 50000.0, "positions": {"601988": {"qty": 1000, "cost": 7.2, "sellable": 1000}}, "trades": []},
        init_strategy=lambda eng, ts: {"view": "(注入: 账户约束演示; 桩未真调模型)", "codes": [
            {"code": "601988", "name": "中国银行", "band": [6.5, 8.0], "rules": [
                {"id": "s2", "side": "SELL", "op": ">=", "px": 7.0, "qty": 700, "why": "注入: 先卖"},
                {"id": "s3", "side": "SELL", "op": ">=", "px": 7.0, "qty": 500, "why": "注入: 再卖(超可卖)"},
                {"id": "b2", "side": "BUY", "op": "<=", "px": 7.5, "qty": 1000, "why": "注入: 接回"},
                {"id": "s4", "side": "SELL", "op": ">=", "px": 7.0, "qty": 200, "why": "注入: 卖刚接回的(T+1)"}]},
            {"code": "600900", "name": "长江电力", "band": [25.0, 35.0], "rules": [
                {"id": "b1", "side": "BUY", "op": "<=", "px": round(px_now(eng, "600900", ts) + 0.5, 2), "qty": 100000, "why": "注入: 超现金买"},
                {"id": "b3", "side": "BUY", "op": "<=", "px": round(px_now(eng, "600900", ts) + 0.5, 2), "qty": 100, "why": "注入: 没钱再买"}]}]},
        plan=[lambda eng, k, w, ts: {"06_final": {"json": keep_unfired(eng, {"600900": {"id": "t1", "side": "SELL", "op": ">=", "px": 32.0, "qty": 100, "why": "注入: 卖今天刚买的"}})}}])
    add("s14_check_drop", "执行器校验剔除(超涨跌停价 / 非 100 股整数倍 / 不在候选池 / 方向条件不配)", ["check_drop"], "10:55:00", "11:00:00",
        "10:55:10 手动叫重定; 桩 06 故意给 5 条坏规则 + 1 条好规则, 经 se_exec.SE.check(真代码)校验。",
        kicks=[("10:55:10", "注入: 叫一次重定(06 将给坏规则)")],
        plan=[lambda eng, k, w, ts: {"06_final": {"json": {"view": "(注入: 校验剔除演示; 桩未真调模型)", "codes": [
            {"code": "600900", "name": "长江电力", "band": [28.5, 30.5], "rules": [
                {"id": "g1", "side": "BUY", "op": "<=", "px": 29.0, "qty": 100, "why": "注入: 好规则"},
                {"id": "x1", "side": "BUY", "op": "<=", "px": 35.0, "qty": 100, "why": "注入: 超涨停 32.66"},
                {"id": "x2", "side": "BUY", "op": "<=", "px": 29.0, "qty": 150, "why": "注入: 150 股非整百"},
                {"id": "x3", "side": "BUY", "op": ">=", "px": 29.0, "qty": 100, "why": "注入: BUY 配 >="},
                {"id": "x4", "side": "SELL", "op": ">=", "px": 30.0, "qty": 100, "why": "注入: 没持仓卖(超可卖)"}]},
            {"code": "000001", "name": "平安银行", "band": [10, 12], "rules": [{"id": "x5", "side": "BUY", "op": "<=", "px": 11.0, "qty": 100, "why": "注入: 不在候选池"}]}],
            "valid_until": "11:30"}}}, {}])
    add("s15_suspend_stale", "停牌票(纳指ETF 09:30~10:30 真停牌) + 盘口断流(注入 600900 3 分钟无更新)", ["suspend", "stale"], "09:31:00", "10:36:00",
        "注入规则: BUY 159941 纳指ETF 价≤1.73 ×10000 —— 09:30~10:30 溢价停牌(1 分钟线成交量 0, 盘口现价 0) → 不撮合, 10:30 复牌 1.725 → 成交;"
        " 另把 600900 的 3 秒盘口在 10:00:00~10:03:00 丢掉(模拟采集断流) → 超 60 秒判陈旧 → 新浪补价(回放用 1 分钟线)。",
        drop_ticks={"600900": ("10:00:00", "10:03:00")}, set_state={"cash": 100000.0, "positions": {}, "trades": []},
        init_strategy=lambda eng, ts: {"view": "(注入: 停牌 / 断流演示; 桩未真调模型)", "codes": [
            {"code": "159941", "name": "纳指ETF", "band": [1.65, 1.78], "rules": [{"id": "n1", "side": "BUY", "op": "<=", "px": 1.73, "qty": 10000, "why": "注入: 停牌中挂买"}]},
            {"code": "600900", "name": "长江电力", "band": [28.5, 30.5], "rules": []}]},
        plan=[lambda eng, k, w, ts: {"06_final": {"json": keep_unfired(eng)}}])
    add("s16_facts_missing", "事实包缺", ["facts_missing"], "10:50:00", "10:55:00",
        "10:50:10 手动叫重定; 事实包文件读不到 → se_exec._chain 传 \"(今日事实包缺)\"; 01(真脚本)候选池只剩持仓 + 上一版策略里的票; 06 桩沿用当前策略。",
        kicks=[("10:50:10", "注入: 叫一次重定(事实包缺)")], facts_override="(今日事实包缺)", plan=[{}])
    add("s17_crash_restore", "进程崩溃 → 续跑(断点恢复)", ["crash_restore"], "10:20:00", "10:40:00",
        "10:24:30 手动叫重定, 链在跑的 10:25:00 进程被杀(在算的那轮丢了), 10:28:00 重启: 按 se_exec 落盘格式写 events / strategies / heartbeat / state 到临时目录,"
        " 用 se_exec.SE(真代码)._restore 恢复 版本 / fired / 计数 / 冷却起点 / 翻转已看 / 被打断那轮 → 补叫(续跑补叫, 不占上限)。进程死掉的 3 分钟里不撮合、不判。",
        kicks=[("10:24:30", "注入: 叫一次重定(随后进程被杀)")], crash=("10:25:00", "10:28:00"), plan=[{}])
    add("s18_close_unfinished", "收盘时链还没跑完 / 排队作废 / 收盘作废", ["close_late", "queue_void", "void_close"], "14:50:00", "15:00:00",
        "14:55:40 手动叫重定(事实包等 + 链约 110 秒 → 14:57 之后才出结果 → 不再生效); 14:56:30 再叫一次 → 排队 → 链结束已收盘 → 排队作废。",
        kicks=[("14:55:40", "注入: 尾盘叫一次重定"), ("14:56:30", "注入: 尾盘再叫一次")], plan=[{}])
    return S


# ---------------- 跑一个场景 ----------------
def load_snaps(base):
    out = []
    f = base / "snapshots.jsonl"
    for l in f.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(l))
        except ValueError:
            pass
    return out


def pick_snap(snaps, t):
    c = [s for s in snaps if s["t"] <= t and not s.get("running")]
    return c[-1] if c else None


def run_one(M, base, sc, skill, D, main_runs):
    out = base / "inject" / sc["id"]
    if out.exists():
        shutil.rmtree(out)
    cfg_in = sc["cfg"]
    t_fork = hs(sc["fork"])
    if cfg_in.get("fresh"):
        init = None
    else:
        snap = pick_snap(load_snaps(base), t_fork)
        if not snap:
            raise SystemExit(f"{sc['id']}: 主回放在 {sc['fork']} 前没有空闲快照")
        init = copy.deepcopy(snap)
        init["t"] = t_fork
    cfg = {"out": out, "skill": skill, "D": D, "mode": "stub", "label": sc["id"], "t_start": sc["fork"], "t_end": sc["t_end"], "verbose": False,
           "plan_fn": plan_seq(cfg_in.get("plan") or [{}]), "patch_on_crash": True}
    for k in ("hb_fn", "idx_kw", "facts_override", "index_event"):
        if k in cfg_in:
            cfg[k] = cfg_in[k]
    cfg["kicks"] = [(hs(t), w) for t, w in cfg_in.get("kicks") or []]
    if cfg_in.get("drop_ticks"):
        cfg["drop_ticks"] = {c: (hs(a), hs(b)) for c, (a, b) in cfg_in["drop_ticks"].items()}
    if init is not None:
        if cfg_in.get("set_state"):
            init["state"] = copy.deepcopy(cfg_in["set_state"])
        if "n_re" in cfg_in:
            init["n_re"] = cfg_in["n_re"]
            init["capped"] = False
        if cfg_in.get("flips_reset"):
            init["flips_seen"] = [k for k in init.get("flips_seen") or [] if k not in cfg_in["flips_reset"]]
        cfg["init"] = init
    eng = R.Engine(M, cfg)
    eng.ev(t_fork, "注入说明", sc["desc"], inj=True, note="注入演示(非自然发生); 桩模型(未真调模型)")
    if cfg_in.get("set_state") and init is not None:
        ss = cfg_in["set_state"]
        eng.ev(t_fork, "注入账户", f"现金 {ss['cash']:.0f}; 持仓: " + ("; ".join(f"{c} {p['qty']} 股(昨日持有, 可卖 {p['sellable']}, 成本 {p['cost']})" for c, p in ss["positions"].items()) or "空仓"), inj=True)
    if cfg_in.get("init_strategy") and init is not None:
        s = cfg_in["init_strategy"](eng, t_fork)
        X = eng.checker()
        X.strategy = s   # 注入策略里的票算"策略里的票"(se_exec.SE.codes), 否则名单外的票会被当成不在候选池剔掉
        s, dropped = E.SE.check(X, s)
        eng.ver += 1
        eng.strategy, eng.fired = s, set()
        eng.ev(t_fork, "生效", f"v{eng.ver} 注入策略生效(不经链, 但过 se_exec.SE.check): {len(s.get('codes') or [])} 只票 {sum(len(x.get('rules') or []) for x in s.get('codes') or [])} 条规则"
               + (f"; 校验提示 / 剔除 {len(dropped)} 处" if dropped else ""), ver=eng.ver, inj=True, strategy=s, dropped=dropped)
    if cfg_in.get("crash"):
        cfg["crash"] = (hs(cfg_in["crash"][0]), hs(cfg_in["crash"][1]))
        cfg["on_crash"] = lambda e, t: on_crash(e, t, main_runs)
        cfg["on_restart"] = on_restart
    S = eng.run()
    meta = {k: v for k, v in sc.items() if k != "cfg"}
    meta["cfg"] = {k: (str(v) if callable(v) else v) for k, v in cfg_in.items() if k != "plan"}
    meta["fork_snapshot"] = sh(init["t"]) if init else "09:15:00(10 万空仓起步, 不分叉)"
    meta["summary"] = {k: S[k] for k in ("ret_pct", "calls", "usd", "n_events", "n_free", "cap_free")}
    (out / "scenario.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return out


# ---------------- 崩溃 / 续跑(调 se_exec 真代码) ----------------
def on_crash(eng, t, main_runs):
    """进程被杀: 在算的那轮丢掉; 按 se_exec 落盘格式把"杀之前"写到临时目录(重启时 se_exec.SE._restore 读)"""
    tmp = Path(tempfile.mkdtemp(prefix="se_crash_"))
    d = tmp / "live" / f"se_{eng.skill}"
    (d / "strategies").mkdir(parents=True)
    lost = eng.running["run"]["id"] if eng.running else None
    evs = []
    for r in main_runs:   # 分叉点之前主回放的重定(se_exec 的 n_re 从 events 里"重定"行的 n 恢复)
        if hs(r["trig"]) < hs(eng.cfg["t_start"]):
            evs.append({"t": r["trig"], "kind": "重定", "why": r["why"][:80], "n": r.get("n_re", 0)})
            if r.get("err"):
                evs.append({"t": r["trig"], "kind": "重定异常", "err": r["err"][:80]})
            elif not r.get("applied"):
                evs.append({"t": r.get("end") or r["trig"], "kind": "重定失败"})
    for r in eng.runs:
        evs.append({"t": r["trig"], "kind": "重定", "why": r["why"][:80], "n": r.get("n_re", 0)})
        if r.get("chain_dur") is not None and not r.get("applied") and r["id"] != lost:
            evs.append({"t": r.get("end") or r["trig"], "kind": "重定失败"})
    (d / "events.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in evs), encoding="utf-8")
    for v in range(1, eng.ver + 1):   # 每个已生效版本一份(只有最后一版内容要紧: _restore 取最后一个文件)
        (d / "strategies" / f"{v:02d}_0000.json").write_text(json.dumps({"why": "", "strategy": eng.strategy if v == eng.ver else {}, "fired": sorted(eng.fired) if v == eng.ver else []},
                                                                         ensure_ascii=False), encoding="utf-8")
    (d / "heartbeat.txt").write_text(f"{sh(t)} pid=0 ver={eng.ver} 崩溃前最后一次心跳\n", encoding="utf-8")
    st_ = copy.deepcopy(eng.state)
    st_["start"] = {"cash": R.INIT_CASH, "positions": {}, "from": "genesis", "at": "replay"}
    (d / "state.json").write_text(json.dumps(st_, ensure_ascii=False), encoding="utf-8")
    before = {"ver": eng.ver, "n_re": eng.n_re, "n_all_day": len([e for e in evs if e["kind"] == "重定"]), "last_re": sh(eng.last_re) if eng.last_re is not None else None,
              "fired": sorted(eng.fired), "flips_seen": sorted(eng.flips_seen), "retry": eng.retry, "fail_n": eng.fail_n, "queued": len(eng.queued)}
    eng.crash_ctx = {"dir": d, "tmp": tmp, "lost": lost, "before": before}
    eng.running, eng.queued = None, []
    eng.ev(t, "进程崩溃", f"执行器进程被杀(注入)" + (f"; 在算的链 {lost} 丢失, 结果永远不会落地" if lost else "") + f"; 落盘: {d}",
           inj=True, before=before, note="se_exec 每次 重定 / 成交 / 收盘 才写盘; 内存里的 queued / retry / fail_n 不落盘")


def on_restart(eng, t):
    c = eng.crash_ctx
    se = E.SE(eng.skill, eng.D, True, base=c["dir"])   # se_exec 真代码: __init__ → _restore
    restored = {"ver": se.ver, "n_re": se.n_re, "n_all_day": se.n_all, "last_re": se.last_re.strftime("%H:%M:%S") if se.last_re else None,
                "fired": sorted(se.fired), "flips_seen": sorted(se.flips_seen), "capped": se._capped, "interrupted": se.interrupted,
                "retry": getattr(se, "retry", None), "fail_n": getattr(se, "fail_n", 0), "queued": se.queued}
    lost = [k for k in ("retry", "fail_n", "queued") if c["before"].get(k) and not restored.get(k)]
    eng.ver, eng.fired, eng.strategy = se.ver, set(se.fired), se.strategy or eng.strategy
    eng.n_re, eng.capped, eng.flips_seen = se.n_re, se._capped, set(se.flips_seen)
    eng.last_re = hs(se.last_re.strftime("%H:%M:%S")) if se.last_re else eng.last_re
    eng.retry, eng.fail_n = None, 0
    restore_ev = (Path(c["dir"]) / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    eng.ev(t, "续跑恢复", f"重启, se_exec.SE._restore 恢复: v{se.ver} / 自由触发 {se.n_re} / 今日重定 {se.n_all} 次 / 冷却起点 {restored['last_re']} / 翻转已看 {restored['flips_seen']}"
           + (f" / 被打断的一轮: {se.interrupted}" if se.interrupted else ""), inj=True, before=c["before"], restored=restored, se_event=restore_ev,
           note=("没恢复的内存状态: " + ", ".join(lost)) if lost else "内存状态都能从落盘恢复")
    shutil.rmtree(c["tmp"], ignore_errors=True)
    if se.interrupted:
        eng.fire(t, "续跑补叫", "(续跑补叫) " + se.interrupted, counted=False, inj=True)


# ---------------- 次日接续(调 se_exec._init_state 真代码) ----------------
def next_day(base, skill):
    """把主回放收盘账当成 SE_GENESIS 首日(10/22)收盘, 在临时 ROOT 下用 se_exec.SE(真代码)建 10/22 与 10/23 的开盘账"""
    close = jl(base / "state_close.json", {}) or {}
    tmp = Path(tempfile.mkdtemp(prefix="se_nextday_"))
    old_root, old_env = E.ROOT, os.environ.get("SE_GENESIS")
    res = {}
    try:
        E.ROOT = tmp
        os.environ["SE_GENESIS"] = "2026-10-22"
        s22 = E.SE(skill, "2026-10-22", True)   # 首日: 前面没有 ≥ GENESIS 的影子账 → 10 万 genesis
        res["d1022"] = {"cash": s22.state["cash"], "positions": s22.state["positions"], "from": s22.state["start"]["from"]}
        st_ = {"cash": close.get("cash"), "positions": {c: {"qty": p["qty"], "cost": p.get("cost"), "sellable": p.get("sellable", 0)} for c, p in (close.get("positions") or {}).items()},
               "trades": close.get("trades") or []}
        (tmp / "results" / "_live" / "2026-10-22" / f"se_{skill}" / "state.json").write_text(json.dumps(st_, ensure_ascii=False), encoding="utf-8")
        s23 = E.SE(skill, "2026-10-23", True)   # 次日: 接 10/22 收盘(持仓 / 现金 / 成本照搬, 隔夜全部可卖)
        res["d1023"] = {"cash": s23.state["cash"], "positions": s23.state["positions"], "from": s23.state["start"]["from"]}
        res["close"] = st_
    finally:
        E.ROOT = old_root
        if old_env is None:
            os.environ.pop("SE_GENESIS", None)
        else:
            os.environ["SE_GENESIS"] = old_env
        shutil.rmtree(tmp, ignore_errors=True)
    (base / "inject" / "next_day.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--skill", default="meiyuelu")
    ap.add_argument("--date", default="2026-10-21")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    base = Path(a.base)
    R.apply_index_patch()   # 主回放已经演示过 index_block 崩溃; 注入场景一律用补丁版, 免得每个场景重演
    M = R.Market(a.date, extra_codes=("603200", "603629", "159941", "601988", "600900", "000001"))
    main_runs = (jl(base / "summary.json", {}) or {}).get("runs") or []
    (base / "inject").mkdir(exist_ok=True)
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    for sc in scenarios(a.date):
        if only and not any(sc["id"].startswith(o) for o in only):
            continue
        out = run_one(M, base, sc, a.skill, a.date, main_runs)
        S = jl(out / "summary.json", {})
        print(f"{sc['id']}: 事件 {S.get('n_events')} 条, 链 {S.get('calls')} 次 → {out}", flush=True)
    if not only or "next" in only:
        print("次日接续:", json.dumps(next_day(base, a.skill), ensure_ascii=False)[:400])


if __name__ == "__main__":
    main()
