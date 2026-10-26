# -*- coding: utf-8 -*-
"""rule_dsl.py — rule_triggers.json 的触发条件小 DSL + 字段登记(什么时候能知道 → 防偷看)

一条规则(skills/<id>-skill/persona/rule_triggers.json 的 rules[] 一项):
  {"id": "R38", "kind": "pos|open|day",
   "when":   {条件...},          情境: 只许用决策时刻已知的字段(见 FIELDS 的 known 档); 用了更晚的字段 → 自动标"含当日信息", 不计入整套指标
   "given":  {条件...},          (可选) 条件于他当天已经做了的事(例: 当天卖了 → 卖得早不早; 当天新开了 → 怎么开), 不算偷看, 不满足就不算命中
   "act":    "清|清不补|卖|不早卖|持|不清|减|低吸不清|加|不加|反T|动|卖则早|卖则晚|无方向|<open/day 动作名>",
   "by": "10:15" / "after": "13:00" / "window": ["09:31","10:35"]   (pos 动作的时刻约束; 加 → 约束首买, 其余 → 约束首卖)
   "expect": {条件...},          open / day: 动作的可判形式(对样本的结果字段判真假)
   "dim": "竞价首笔", "sign": 1|-1,   (可选, open / day) 同 dim 异号 = 冲突
   "route": 1..4,                (可选) 该 skill 有"处置路由: 取第一条命中"时的顺位
   "broad": true, "specific": 0.31, "look": true(人工强制标含当日信息), "modified": "2026-10-25", "src": "...", "note": "..."}
条件写法(when / given / expect 同一套):
  {"字段": 值}                    等于
  {"字段": [值, 值]}              属于
  {"字段": {"op": 值, ...}}        op: eq ne in nin > >= < <= abs<= abs< null(true=缺失) exists(true=有值); 多个 op 同时满足
  {"any": [{...}, {...}]}         或;  {"all": [...]} 且;  {"not": {...}} 非
  顶层多个键 = 且
缺失值: FIELDS 里登记了 default 的按 default 算(和诊断脚本 `p.get(x) or 0` 口径一致), 没登记的缺失 → 比较一律为假(nin / ne 为真)
"""

# known 档(从早到晚): 盘前 < 竞价 < 开仓时(只对 open 样本: 这笔买入本身的价格 / 时刻) < 盘中 < 收盘 < 结果
ORDER = {"盘前": 0, "竞价": 1, "开仓时": 2, "盘中": 3, "收盘": 4, "结果": 5}
# 每类样本的决策时刻: 允许用到哪一档
DECIDE_AT = {"pos": "竞价", "open": "开仓时", "day": "竞价"}

# 字段: (known 档, 说明, default)
FIELDS = {
    # ---- 通用 / 市况 ----
    "date": ("盘前", "交易日", None),
    "idx_gap": ("竞价", "上证开盘缺口(09:25 定)", 0.0),
    "idx_prev": ("盘前", "上证昨日涨跌", 0.0),
    "idx_5d_prev": ("盘前", "上证截至昨收 5 日涨跌", 0.0),
    "zt_n_prev": ("盘前", "昨日涨停家数", 99),
    "up_prev": ("盘前", "昨日上涨占比", None),
    "pre_holiday": ("盘前", "节前最后交易日", None),
    "idx_day": ("收盘", "上证当日涨跌(含当日信息)", 0.0),
    "zt_n_day": ("收盘", "当日涨停家数(含当日信息)", None),
    "up_day": ("收盘", "当日上涨占比(含当日信息)", 1.0),
    # ---- 持仓日 pos ----
    "yest_new": ("盘前", "昨日新开(持仓起点=昨日)", None),
    "st_prev": ("盘前", "昨日板态 一字/封住/炸板/未触板/跌停", None),
    "yn_unsealed": ("盘前", "昨日新开且没封住(未触板/炸板)", None),
    "h_prev": ("盘前", "昨收连板高度", None),
    "pct_prev": ("盘前", "昨日涨跌", None),
    "tot0": ("盘前", "昨收合计仓位", None),
    "pp0": ("盘前", "昨收单票仓位", None),
    "rate0": ("盘前", "昨收浮盈(新开当日占位值已按买入均价重算)", 0.0),
    "hold": ("盘前", "已持交易日数(含昨日)", None),
    "play_open": ("盘前", "这笔仓的买入打法(cases_auto play)", None),
    "fam": ("盘前", "熟票(一年内做过)", None),
    "box_prev_close": ("盘前", "日线箱体位置(按昨收)", None),
    "gap": ("竞价", "今日开盘缺口(09:25 定)", 0.0),
    "hi30": ("盘中", "开盘 30 分钟最高(10:00 才知道)", None),
    "lo30": ("盘中", "开盘 30 分钟最低(10:00 才知道)", None),
    "high": ("收盘", "当日最高(含当日信息)", 0.0),
    "low": ("收盘", "当日最低(含当日信息)", None),
    "close": ("收盘", "当日收盘(含当日信息)", None),
    "st_day": ("收盘", "当日板态(含当日信息)", None),
    "hit_lu_day": ("收盘", "当日触过涨停(含当日信息)", None),
    # ---- 新开仓 open(条件于"他今天新开了这只"; 买入价 / 时刻本身属开仓时) ----
    "play": ("开仓时", "买入打法(依赖买价, 不依赖收盘)", None),
    "buy_vs_pc1": ("开仓时", "首笔买价较昨收", None),
    "t_buy1": ("开仓时", "首笔买入时刻", None),
    "buy_pos_in_day": ("开仓时", "首笔买入时的日内位置(fills_rt, 只到 10/16 前后)", None),
    "buy_at_limit": ("开仓时", "买在涨停价(fills_rt)", None),
    "buy_below_open": ("开仓时", "买价低于开盘价 0.5% 以上", None),
    "first_open_today": ("开仓时", "当日第一只新开", None),
    "prev_round_loss": ("盘前", "上一轮(最近有卖出的日子)平均亏", None),
    "loss_rounds": ("盘前", "连亏轮数", None),
    "sc_drop3": ("盘前", "双创近 3 日有单日 ≤−2%(含当日)", None),
    "pp1": ("结果", "收盘单票仓位", None),
    "first5_amt_ratio": ("结果", "首笔起 5 分钟买入额 / 昨日资产", None),
    "buy_amt_ratio": ("结果", "当日买入额 / 昨日资产", None),
    "first5_share": ("结果", "首 5 分钟买入额 / 当日买入额", None),
    "day_tot1": ("结果", "当日收盘合计仓位", None),
    # ---- 账户日 day ----
    "empty_prev": ("盘前", "昨收空仓", None),
    "nav_chg_prev": ("盘前", "昨日资产涨跌", None),
    "loss_streak": ("盘前", "截至昨日连续卖出全亏天数", None),
    "loss_sell_prev": ("盘前", "昨日有亏损卖出", None),
    "cleared_any": ("盘中", "当日清掉了某只隔夜仓(他自己的先手动作)", None),
    "tot1": ("结果", "收盘合计仓位", None),
    "d_tot": ("结果", "收盘合计仓位 − 昨收", None),
    "n_hold1": ("结果", "收盘持股数", None),
    "n_new": ("结果", "当日新开只数", None),
    "traded": ("结果", "当日有成交", None),
    "n_sell": ("结果", "当日卖出笔数(只在 given 里用)", None),
    "n_buy": ("结果", "当日买入笔数(只在 given 里用)", None),
    "empty_close": ("结果", "收盘空仓", None),
    # ---- 不吃土豆0 账户日 ----
    "has_main": ("盘前", "有阶段主做债(前 10 个交易日成交腿最多的转债)", None),
    "main_bond": ("盘前", "主做债代码", None),
    "stk_auc": ("竞价", "正股 09:24 虚拟撮合(10/12 前用最终开盘价近似)", None),
    "bond_auc": ("竞价", "主做债 09:24 虚拟撮合(10/12 前用最终开盘价近似)", None),
    "stk_open": ("收盘", "正股最终开盘价(09:25 撮合 = 他竞价单成交之后才知道)", None),
    "bond_open": ("收盘", "转债最终开盘价(同上)", None),
    "auction_main": ("结果", "首笔 09:25 竞价买主做债", None),
    "auction_any": ("结果", "首笔 09:25 竞价", None),
    "first_channel": ("结果", "首笔通道 竞价/死窗/追单/盘中", None),
    "first_buy": ("结果", "首笔买入时刻", None),
    "rt1_secs": ("结果", "首笔回合持有秒数(从 09:30 起算)", None),
    "late_buy": ("结果", "09:35 后还有买入", None),
    "notional_first": ("结果", "首笔名义(万)", None),
}

_MISSING = object()


def get(s, f, raw=False):
    v = s.get(f, None)
    if v is None and not raw:
        d = FIELDS.get(f, (None, None, None))[2]
        return d
    return v


def _cmp(v, op, x):
    if op == "null":
        return (v is None) == bool(x)
    if op == "exists":
        return (v is not None) == bool(x)
    if op == "eq":
        return v == x
    if op == "ne":
        return v != x
    if op == "in":
        return v in x
    if op == "nin":
        return v not in x
    if v is None:
        return False
    if op == ">":
        return v > x
    if op == ">=":
        return v >= x
    if op == "<":
        return v < x
    if op == "<=":
        return v <= x
    if op == "abs<=":
        return abs(v) <= x
    if op == "abs<":
        return abs(v) < x
    raise ValueError(f"未知 op: {op}")


def match(cond, s):
    """cond 对样本 s 判真假; cond 为空 / None = 恒真"""
    if not cond:
        return True
    for k, c in cond.items():
        if k == "any":
            if not any(match(x, s) for x in c):
                return False
        elif k == "all":
            if not all(match(x, s) for x in c):
                return False
        elif k == "not":
            if match(c, s):
                return False
        else:
            if isinstance(c, dict):
                raw = any(op in ("null", "exists") for op in c)
                v = get(s, k, raw=raw)
                if not all(_cmp(v if op not in ("null", "exists") else get(s, k, raw=True), op, x) for op, x in c.items()):
                    return False
            elif isinstance(c, list):
                if get(s, k) not in c:
                    return False
            else:
                if get(s, k) != c:
                    return False
    return True


def fields_of(cond, out=None):
    out = set() if out is None else out
    if not cond:
        return out
    for k, c in cond.items():
        if k in ("any", "all"):
            for x in c:
                fields_of(x, out)
        elif k == "not":
            fields_of(c, out)
        else:
            out.add(k)
    return out


def look_fields(rule):
    """when 里用到的、决策时刻还不知道的字段(→ 含当日信息); 未登记字段也算(不认识 = 不敢信)"""
    lim = ORDER[DECIDE_AT.get(rule.get("kind"), "竞价")]
    bad = []
    for f in sorted(fields_of(rule.get("when"))):
        k = FIELDS.get(f)
        if k is None or ORDER[k[0]] > lim:
            bad.append(f"{f}({k[0] if k else '未登记'})")
    return bad


# ---------------------------------------------------------------- 持仓日动作判定 ----------------------------------------------------------------
# o = 真实结果 {act: 清/减/加/做T/不动, b: 有买, s: 有卖, ts: 首卖时刻, tb: 首买时刻}
ACTIVE = {"清", "清不补", "卖", "减", "低吸不清", "加", "反T", "动"}            # 叫"做某事": 没做 = 误报
PASSIVE = {"不早卖", "持", "不清", "不加", "卖则早", "卖则晚"}                    # 叫"别做 / 等": 做了 = 反向
COND_SELL = {"卖则早", "卖则晚"}                                               # 只在当天有卖出时才算命中
L1 = {"清": True, "清不补": True, "持": False, "不清": False, "减": False, "低吸不清": False}   # 推"当天清 / 不清"(基线对照用)


def _t(x):
    if x is None:
        return None
    return x if len(x) == 8 else (x + ":00" if len(x) == 5 else x)


def pos_ok(r, o):
    a = r["act"]
    by, af, win = _t(r.get("by")), _t(r.get("after")), r.get("window")
    ts, tb = o["ts"], o["tb"]

    def tsell():
        if by and not (ts is not None and ts <= by):
            return False
        if af and not (ts is not None and ts > af):
            return False
        if win and not (ts is not None and _t(win[0]) < ts <= _t(win[1])):
            return False
        return True

    if a == "清":
        return o["act"] == "清" and tsell()
    if a == "清不补":
        return o["act"] == "清" and not o["b"] and tsell()
    if a == "卖":
        return o["s"] and tsell()
    if a == "减":
        return o["act"] == "减" and tsell()
    if a == "不早卖":
        return (not o["s"]) or ts > af
    if a == "持":
        return o["act"] in ("不动", "做T", "加")
    if a == "不清":
        return o["act"] != "清"
    if a == "低吸不清":
        return o["b"] and o["act"] != "清"
    if a == "加":
        return o["b"] and (not by or (tb is not None and tb <= by))
    if a == "不加":
        return not o["b"]
    if a == "反T":
        return o["s"] and o["b"] and ts < tb
    if a == "动":
        return o["act"] != "不动"
    if a == "卖则早":
        return (not o["s"]) or (ts is not None and ts <= by)
    if a == "卖则晚":
        return (not o["s"]) or (ts is not None and ts > af)
    raise ValueError(f"未知动作 {a} ({r['id']})")


def outcomes():
    """冲突检测用的合成结果空间(抄 distill_diag/eval_rules.outcomes)"""
    import itertools
    T = ["09:25:00", "09:30:30", "09:33:00", "09:40:00", "09:50:00", "10:05:00", "10:20:00", "10:32:00", "10:40:00", "11:00:00", "13:30:00", "14:55:00"]
    res = []
    for act in ("清", "减", "加", "做T", "不动"):
        for b, s in itertools.product((0, 1), (0, 1)):
            if act == "不动" and (b or s):
                continue
            if act in ("清", "减") and not s:
                continue
            if act == "加" and not b:
                continue
            if act == "做T" and not (b and s):
                continue
            if act != "不动" and not (b or s):
                continue
            for ts in (T if s else [None]):
                for tb in (T if b else [None]):
                    if ts and tb and ts == tb:
                        continue
                    res.append({"act": act, "b": bool(b), "s": bool(s), "ts": ts, "tb": tb})
    return res


OUTS = outcomes()


def real_o(p):
    return {"act": p["act"], "b": p["n_buy"] > 0, "s": p["n_sell"] > 0, "ts": p.get("t_sell1"), "tb": p.get("t_buy1")}


def pos_feasible(rules):
    """命中的给方向规则能不能同时成立(存在某个结果让它们全对)"""
    return any(all(pos_ok(r, x) for r in rules) for x in OUTS)
