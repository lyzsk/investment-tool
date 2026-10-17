# -*- coding: utf-8 -*-
"""mimicry_score.py — paper A 线(skill 链) vs 导师真人(tzzb 账本) 分层拟人度 + 延续基线(零 token, 只读; 2026-10-16 建)

口径来源: docs/research/ai_trading_frameworks_20261016.md 建议 1(MILA 分层 + 延续基线)。用户定: 权重=拟人度×真人业绩, 拟人度为主。
每个交易日 d、每对(A-<导师> 链, 导师真人)算四层指标, 每个指标同时对两条基线算同一个分:
  延续基线 = 导师真人 d-1 的状态/动作原样当作 d 的预测(MILA: 今天=昨天)
  对照基线 = A-control(裸模型、persona 空)当天的状态/动作
  lift = 链得分 − 基线得分(误差类指标取 基线误差 − 链误差), >0 才算"比基线更像"
层与指标(真值=导师真人 d 日):
  L1 交不交易: L1_交易 / L1_买 / L1_卖 = 当天有无成交(买/卖分开)是否一致(0/1)
  L2 方向    : L2_方向 = 净加仓 / 净减仓 / 不动 三分类是否一致; 净额 = 当天动过的票的"去价格漂移"权重变化之和, 阈值 eps_dir(params.yaml mimicry 节, 按导师动态 auto, 回落 ±5% 资产)
  L3 标的    : L3_买入Jaccard(当天买入票集合) / L3_持仓Jaccard(收盘持仓集合; 双空=无定义不计)
               L3_板块 / L3_行业 = 足迹(收盘持仓∪当天买入, 每票等权)的分布重合度 Σmin(p,q); 任一方足迹空=不计
               行业=downloads/f10 缓存的东财二级行业(mentor_scope.py 同口径 tags[1]), 本脚本不联网, 缓存没有的票记"未知"并剔除
  L4 仓位    : L4_总仓误差 / L4_总仓分档(空<5%/轻<35%/半<65%/重<95%/满) / L4_只数误差 / L4_最大仓误差 / L4_换手误差
               换手 = 当天动过的票 Σ|去漂移权重变化|(收盘对收盘口径, 日内 T 不可见, 双方同口径)
小样本: 0/1 指标给 Wilson 95% 区间; lift 给按日配对 bootstrap 95% 区间(2000 次, 固定种子); 配对天数 < MIN_RANK 标"不足以排序"。
数据(全部只读): scripts/dfcf/paper/books/A-*.json(成交流水重放到 d 日收盘, 同 similarity.mjs simState) /
  downloads/tzzb/<ledger>/day_positions.json(收盘持仓+当日 op 码) + position_change_p*/change_bs_*(逐笔腿, 补 op 码) + nav_daily.json /
  本地行情库日线(scripts/quotes/kline_db.py 只读 SELECT, 子进程 CREATE_NO_WINDOW; 不可用时退化为成交价/中性漂移) / downloads/f10 缓存
用法:
  scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/mimicry_score.py --date 2026-10-16
  scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/mimicry_score.py --since 2026-10-08 [--until 2026-10-16]
  scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/mimicry_score.py --selftest
产物: scripts/dfcf/paper/mimicry/<日>.md+.json(--date) / cum_<起>_<止>.md+.json(--since)
"""
import argparse
import collections
import datetime as dt
import glob
import json
import math
import os
import random
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 不在现有目录留 pyc
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BOOKS = HERE / "books"
TZ = ROOT / "downloads" / "tzzb"
F10 = ROOT / "downloads" / "f10"
OUT = HERE / "mimicry"
KLINE_DB = ROOT / "scripts" / "quotes" / "kline_db.py"
sys.path.insert(0, str(ROOT / "scripts" / "tzzb"))
from mentor_scope import NOISE, board, norm_op  # noqa: E402  复用 tzzb 板块/腿方向口径

# 同 run_taoge_chain.py TZZB_LEDGERS(10/16); 另加 A-cb↔buchitudou0(转债导师, 真人基本只做日内 T+逆回购, 结果单列看)
TZZB_LEDGERS = ["liuyiqing", "lianghuaxiaohao", "a658", "bianbenling", "xingjianye", "daxingdaxingdadangxing",
                "gaogailvfuli", "xuanqiucaijing", "stzhilang", "chong5000w", "antoo", "zhiyingjuexin", "zjwzlclf", "ynw01", "wudaokongfang"]
PAIRS = [("A-" + l, l) for l in TZZB_LEDGERS] + [("A-cb", "buchitudou0")]
CONTROL = "A-control"
START = "2026-10-08"          # 10/8 实盘重新开户(real_vs_chain.mjs 同口径)
# 阈值(10/16 晚: 挪到 params.yaml mimicry 节, 支持按导师动态 auto; 下面四个=回落值/无配置时的默认, 也是 selftest 口径)
EPS_DIR = 0.05                # 方向阈值: 净额 > 5% 资产才算净加/净减
MIN_W = 0.02                  # 实质持仓门槛: 真人账本常留 0.1%~1% 的碎仓/观察仓, 不计入持仓集合/只数/板块(总仓照算)
TP_BINS = (0.05, 0.35, 0.65, 0.95)
MIN_RANK = 20                 # 配对天数少于此 → 不足以排序
DEF_TH = {"eps_dir": EPS_DIR, "min_w": MIN_W, "tp_bins": TP_BINS, "min_rank": MIN_RANK}
DEF_CFG = {"lookback_days": 120,
           "eps_dir": {"mode": "fixed", "fixed": EPS_DIR, "pct": 20, "lo": 0.01, "hi": 0.10, "min_n": 8},
           "min_w": {"mode": "fixed", "fixed": MIN_W, "pct": 10, "lo": 0.003, "hi": 0.05, "min_n": 20},
           "tp_bins": {"mode": "fixed", "fixed": list(TP_BINS), "pcts": [20, 40, 60, 80], "min_gap": 0.05, "min_n": 20},
           "min_rank": {"mode": "fixed", "fixed": MIN_RANK, "active_days": 10, "lo": 10, "hi": 40}}
BOOT_N, SEED = 2000, 20261016
BUY_OPS, SELL_OPS = {"1", "3", "7", "9"}, {"2", "4", "8", "9"}   # day_positions op: 3 建/7,1 加/4 清/8,2 减/9 当日有买有卖/0 不动
MAIN = ["L1_交易", "L2_方向", "L3_持仓Jaccard", "L4_总仓误差"]
METRICS = {  # 名称: (类型 acc=0/1 越高越好, sim=0~1 越高越好, err=越低越好, 层)
    "L1_交易": ("acc", "L1"), "L1_买": ("acc", "L1"), "L1_卖": ("acc", "L1"),
    "L2_方向": ("acc", "L2"),
    "L3_买入Jaccard": ("sim", "L3"), "L3_持仓Jaccard": ("sim", "L3"), "L3_板块": ("sim", "L3"), "L3_行业": ("sim", "L3"),
    "L4_总仓误差": ("err", "L4"), "L4_总仓分档": ("acc", "L4"), "L4_只数误差": ("err", "L4"),
    "L4_最大仓误差": ("err", "L4"), "L4_换手误差": ("err", "L4"),
}


def load(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def is_repo(code, name=""):
    return str(code).startswith(("204", "1318")) or any(x in (name or "") for x in ("GC0", "R-00"))


def symbol(code):
    c = str(code)
    if len(c) != 6 or not c.isdigit():
        return None   # 港股等: 库里没有
    if c.startswith(("92", "4", "8")):
        return "bj" + c
    return ("sh" if c.startswith(("6", "5", "9", "11")) else "sz") + c


_IND = {}


def industry(code):
    """东财 F10 缓存二级行业(mentor_scope tags[1] 口径); 无缓存=None。不联网。"""
    if code not in _IND:
        bs = (load(F10 / f"{code}.json") or {}).get("boards") or []
        tags = [b["name"] for b in bs[:3] if not any(x in b["name"] for x in NOISE)]
        _IND[code] = tags[1] if len(tags) >= 2 else (tags[0] if tags else None)
    return _IND[code]


# ---------------- 行情(只读本地库) ----------------
class Prices:
    def __init__(self, closes=None, cal=None):
        self.c = closes or {}          # code -> {date: close}
        self.cal = sorted(cal or [])   # 交易日历 yyyy-mm-dd
        self.ok = bool(cal)

    @classmethod
    def from_db(cls, codes, beg):
        syms = sorted({s for s in (symbol(c) for c in codes) if s} | {"sh000001"})
        flags = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
        py = ROOT / "scripts" / "venv" / "Scripts" / "python.exe"
        try:
            r = subprocess.run([str(py if py.exists() else sys.executable), "-X", "utf8", str(KLINE_DB), ",".join(syms), "--beg", beg.replace("-", "")],
                               capture_output=True, timeout=180, creationflags=flags)
            j = json.loads(r.stdout.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"[行情库不可用, 退化为成交价/中性漂移] {e}", file=sys.stderr)
            return cls()
        closes = {s[2:]: {b[0]: b[4] for b in v["bars"] if b[4]} for s, v in j["data"].items() if s != "sh000001"}
        cal = [b[0] for b in j["data"].get("sh000001", {}).get("bars", [])]
        return cls(closes, cal)

    def close(self, code, d):
        m = self.c.get(code)
        if not m:
            return None
        if d in m:
            return m[d]
        ks = [k for k in m if k <= d]
        return m[max(ks)] if ks else None

    def ret(self, code, d0, d1):
        a, b = self.close(code, d0), self.close(code, d1)
        return b / a - 1 if a and b else None

    def prev(self, d):
        ks = [k for k in self.cal if k < d]
        return ks[-1] if ks else None


# ---------------- 快照: {date, hold{code:w}, buy set, sell set, nav, names} ----------------
class Real:
    """导师真人: day_positions 收盘持仓(position_percent=占总资产) + op 码 ∪ 逐笔腿 → 当日买/卖集合。剔逆回购。"""

    def __init__(self, ledger):
        d = TZ / ledger
        self.ledger = ledger
        self.dp = load(d / "day_positions.json") or {}
        il = ((load(d / "nav_daily.json") or {}).get("ex_data") or {}).get("index_list") or []
        self.idx = {x["date"]: float(x["index"]) for x in il if x.get("index")}
        self.legs = collections.defaultdict(lambda: {"buy": set(), "sell": set()})
        seen = set()
        for f in glob.glob(str(d / "position_change_p*.json")) + glob.glob(str(d / "change_bs_*.json")):
            for t in ((load(f) or {}).get("ex_data") or {}).get("change_list") or []:
                k = (t.get("trans_date"), t.get("stock_code"), t.get("trans_count"), t.get("trans_price"), t.get("op"))
                if k in seen or not t.get("trans_date") or not t.get("stock_code") or is_repo(t["stock_code"], t.get("stock_name")):
                    continue
                seen.add(k)
                op = norm_op(t)
                if op in ("1", "2"):
                    self.legs[t["trans_date"][:10]]["buy" if op == "1" else "sell"].add(t["stock_code"])
        self.names = {}
        self.last = max(self.dp) if self.dp else None

    def has(self, d):
        return d and d.replace("-", "") in self.dp

    def snap(self, d, min_w=None):
        if not self.has(d):
            return None
        k8 = d.replace("-", "")
        rec = self.dp[k8] or {}
        if rec.get("note") and not rec.get("list"):   # "空仓或无数据": 前一记录日有实质持仓却无清仓记录=无数据, 不当空仓
            ks = sorted(k for k in self.dp if k < k8)
            prev = (self.dp.get(ks[-1]) or {}).get("list") or [] if ks else []
            mw = MIN_W if min_w is None else min_w
            if any(float(x.get("position_percent") or 0) >= mw and not is_repo(x.get("code"), x.get("name")) for x in prev):
                return None
        hold, buy, sell = {}, set(self.legs[d]["buy"]), set(self.legs[d]["sell"])
        for x in rec.get("list") or []:
            code, name = str(x.get("code")), x.get("name")
            if is_repo(code, name):
                continue
            self.names[code] = name
            w = float(x.get("position_percent") or 0)
            if w > 0:
                hold[code] = w
            op = str(x.get("op"))
            if op in BUY_OPS:
                buy.add(code)
            if op in SELL_OPS:
                sell.add(code)
        return {"date": d, "hold": hold, "buy": buy, "sell": sell, "nav": self.idx.get(d.replace("-", "")), "names": self.names}


class Chain:
    """A 线账本: trades 按 id 前缀日期重放到 d 日收盘; 权重 = qty×收盘价/当日 nav。"""

    def __init__(self, book, names=None):
        self.book = book
        p = BOOKS / f"{book}.json"
        b = load(p) or {}
        self.mtime = dt.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds") if p.exists() else None
        self.trades = sorted(b.get("trades") or [], key=lambda t: str(t.get("id")))
        self.nav = {n["date"]: float(n["nav"]) for n in b.get("nav") or [] if n.get("nav") is not None}
        self.navrec = {n["date"]: n for n in b.get("nav") or []}
        self.names = names or {}

    def has(self, d):
        return d in self.nav

    def nav_at(self, d):
        if d in self.nav:
            return self.nav[d]
        ks = [k for k in self.nav if k < d]
        return self.nav[max(ks)] if ks else 100000.0

    def snap(self, d, px):
        qty, lastpx, buy, sell = {}, {}, set(), set()
        for t in self.trades:
            td = str(t.get("id"))[:10]
            if td > d:
                break
            c = str(t["code"])
            qty[c] = qty.get(c, 0) + (t["qty"] if t["side"] == "BUY" else -t["qty"])
            lastpx[c] = float(t["price"])
            if td == d and not is_repo(c):
                (buy if t["side"] == "BUY" else sell).add(c)
        nav = self.nav_at(d)
        hold = {}
        for c, q in qty.items():
            if q > 0 and not is_repo(c):
                p = (px.close(c, d) if px else None) or lastpx[c]
                hold[c] = q * p / nav
        return {"date": d, "hold": hold, "buy": buy, "sell": sell, "nav": nav, "names": self.names}


# ---------------- 特征与比较(纯函数, selftest 直接喂构造数据) ----------------
def tp_bin(x, bins=None):
    return sum(x >= e for e in (bins or TP_BINS))


# ---------------- 阈值: params.yaml mimicry 节 + 按导师动态(auto) ----------------
def load_cfg():
    """params.yaml mimicry 节(缺/坏 → DEF_CFG 全 fixed); 每项浅合并默认值"""
    cfg = json.loads(json.dumps(DEF_CFG))
    try:
        import yaml
        y = (yaml.safe_load((HERE / "params.yaml").read_text(encoding="utf-8")) or {}).get("mimicry") or {}
    except Exception as e:  # noqa: BLE001
        print(f"WARN: params.yaml mimicry 读取失败, 用固定默认值: {e}", file=sys.stderr)
        y = {}
    for k, v in y.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


def pctl(xs, q):
    """线性插值分位数(q=0~100)"""
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q / 100
    i = int(math.floor(k))
    j = min(i + 1, len(xs) - 1)
    return xs[i] + (xs[j] - xs[i]) * (k - i)


def calibrate(snaps, cfg):
    """按导师自己的分布定阈值。snaps=[(iso日, 快照)] 时间升序(真人 day_positions, 截到评估窗末日为止的 lookback 段)。
    返回 (th, info): th 同 DEF_TH 结构; info[阈值]={value, src, n}——src=auto(..)/fixed(配置|样本不足|退化)"""
    th, info = dict(DEF_TH), {}

    def fixed(k, why, n=None):
        v = cfg[k]["fixed"]
        th[k] = tuple(v) if k == "tp_bins" else v
        info[k] = {"value": th[k], "src": f"fixed({why})", "n": n}

    clamp = lambda v, c: min(max(v, c["lo"]), c["hi"])  # noqa: E731
    # 1) 碎仓门槛: 非零持仓占比的 P10
    c = cfg["min_w"]
    ws = [w for _, sn in snaps for w in sn["hold"].values() if w > 0]
    if c.get("mode") != "auto":
        fixed("min_w", "配置")
    elif len(ws) < c["min_n"]:
        fixed("min_w", "样本不足", len(ws))
    else:
        th["min_w"] = round(clamp(pctl(ws, c["pct"]), c), 4)
        info["min_w"] = {"value": th["min_w"], "src": f"auto(非零持仓占比 P{c['pct']}, 夹 {c['lo']}~{c['hi']})", "n": len(ws)}
    # 2) 方向阈值: 有动作日 |净仓位变化| 的 P20(净额用本导师 min_w 口径; 无单票行情 → 按账户收益中性去漂移)
    c = cfg["eps_dir"]
    nets = []
    for (_, a), (_, b) in zip(snaps, snaps[1:]):
        f = derive(a, b, lambda x: None, th)
        if f["trade"] and f["net"] is not None:
            nets.append(abs(f["net"]))
    if c.get("mode") != "auto":
        fixed("eps_dir", "配置")
    elif len(nets) < c["min_n"]:
        fixed("eps_dir", "样本不足", len(nets))
    else:
        th["eps_dir"] = round(clamp(pctl(nets, c["pct"]), c), 4)
        info["eps_dir"] = {"value": th["eps_dir"], "src": f"auto(有动作日|净仓位变化| P{c['pct']}, 夹 {c['lo']}~{c['hi']})", "n": len(nets)}
    # 3) 总仓分档: 收盘总仓分布的等频分位
    c = cfg["tp_bins"]
    tps = [min(1.0, sum(sn["hold"].values())) for _, sn in snaps]   # 封顶 100%: 融资 >100% 的导师(链不能加杠杆)不能把分档推到 1 以上
    if c.get("mode") != "auto":
        fixed("tp_bins", "配置")
    elif len(tps) < c["min_n"]:
        fixed("tp_bins", "样本不足", len(tps))
    else:
        edges = [round(pctl(tps, q), 3) for q in c["pcts"]]
        if edges[0] <= 0 or any(y - x < c["min_gap"] for x, y in zip(edges, edges[1:])):
            fixed("tp_bins", f"分布退化 {edges}", len(tps))
        else:
            th["tp_bins"] = tuple(edges)
            info["tp_bins"] = {"value": th["tp_bins"], "src": f"auto(收盘总仓 P{'/'.join(str(q) for q in c['pcts'])})", "n": len(tps)}
    # 4) 排序最少配对天数: 攒够 active_days 个"真人有交易"日所需天数
    c = cfg["min_rank"]
    tflags = [bool(sn["buy"] or sn["sell"]) for _, sn in snaps]
    rate = (sum(tflags) / len(tflags)) if tflags else 0
    if c.get("mode") != "auto":
        fixed("min_rank", "配置")
    elif rate <= 0:
        fixed("min_rank", "无交易日样本", len(tflags))
    else:
        th["min_rank"] = int(clamp(math.ceil(c["active_days"] / rate), c))
        info["min_rank"] = {"value": th["min_rank"], "src": f"auto(ceil({c['active_days']}/交易日占比 {rate:.0%}), 夹 {c['lo']}~{c['hi']})",
                            "n": len(tflags)}
    return th, info


def real_snaps(real, end_day, cfg):
    """真人 lookback 段快照(≤ end_day 的最近 lookback_days 个有记录日); 无数据日(snap=None)跳过"""
    ks = sorted(k for k in real.dp if k <= end_day.replace("-", ""))[-int(cfg.get("lookback_days") or 120):]
    out = []
    for k in ks:
        d = f"{k[:4]}-{k[4:6]}-{k[6:]}"
        sn = real.snap(d, cfg["min_w"]["fixed"])
        if sn is not None:
            out.append((d, sn))
    return out


def derive(prev, cur, ret, th=None):
    """cur 当日快照 → 行为特征; prev=前一交易日快照(无则方向/换手无定义); ret(code)=该票 prev→cur 收益(None=未知, 按账户收益中性处理)
    th=阈值(该导师 calibrate 结果; None=固定默认)"""
    th = th or DEF_TH
    names = cur.get("names") or {}
    trade = bool(cur["buy"] or cur["sell"])
    real_hold = {c: w for c, w in cur["hold"].items() if w >= th["min_w"]}   # 实质持仓: 剔碎仓/观察仓(只计入总仓)
    foot = set(real_hold) | set(cur["buy"])
    f = {"trade": trade, "buy": bool(cur["buy"]), "sell": bool(cur["sell"]), "hold": set(real_hold), "buys": set(cur["buy"]),
         "tp": sum(cur["hold"].values()), "n": len(real_hold), "mx": max(cur["hold"].values(), default=0.0),
         "boards": collections.Counter(board(c, names.get(c, "")) for c in foot),
         "inds": collections.Counter(i for i in (industry(c) for c in foot) if i), "foot_n": len(foot),
         "ind_known": sum(1 for c in foot if industry(c)), "net": None, "turn": None, "dir": None}
    if prev is None:
        return f
    if prev.get("nav") and cur.get("nav"):
        R = cur["nav"] / prev["nav"] - 1
    else:   # 无净值: 用昨日持仓加权收益近似
        R = sum(w * (ret(c) or 0.0) for c, w in prev["hold"].items())
    flows = {}
    for c in (set(cur["buy"]) | set(cur["sell"])):   # 只有当天动过的票才有资金流, 没动的票漂移=0
        wp = prev["hold"].get(c, 0.0)
        r = ret(c)
        r = R if r is None else r
        flows[c] = cur["hold"].get(c, 0.0) - wp * (1 + r) / (1 + R)
    net, turn = sum(flows.values()), sum(abs(v) for v in flows.values())
    eps = th["eps_dir"]
    f.update(net=net, turn=turn, dir=0 if not trade else (1 if net > eps else -1 if net < -eps else 0))
    return f


def jac(a, b):
    u = a | b
    return None if not u else len(a & b) / len(u)


def overlap(ca, cb):
    na, nb = sum(ca.values()), sum(cb.values())
    if not na or not nb:
        return None
    return sum(min(ca[k] / na, cb[k] / nb) for k in set(ca) | set(cb))


def compare(a, b, th=None):
    """a=候选(链/基线)特征, b=真人当日特征 → 指标值(None=无定义); th=该导师阈值(总仓分档边界)"""
    if a is None or b is None:
        return None
    bins = (th or DEF_TH)["tp_bins"]
    return {
        "L1_交易": float(a["trade"] == b["trade"]), "L1_买": float(a["buy"] == b["buy"]), "L1_卖": float(a["sell"] == b["sell"]),
        "L2_方向": None if a["dir"] is None or b["dir"] is None else float(a["dir"] == b["dir"]),
        "L3_买入Jaccard": jac(a["buys"], b["buys"]), "L3_持仓Jaccard": jac(a["hold"], b["hold"]),
        "L3_板块": overlap(a["boards"], b["boards"]), "L3_行业": overlap(a["inds"], b["inds"]),
        "L4_总仓误差": abs(a["tp"] - b["tp"]), "L4_总仓分档": float(tp_bin(a["tp"], bins) == tp_bin(b["tp"], bins)),
        "L4_只数误差": float(abs(a["n"] - b["n"])), "L4_最大仓误差": abs(a["mx"] - b["mx"]),
        "L4_换手误差": None if a["turn"] is None or b["turn"] is None else abs(a["turn"] - b["turn"]),
    }


# ---------------- 统计 ----------------
def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def boot_ci(xs, n=BOOT_N, seed=SEED):
    if len(xs) < 3:   # 1~2 个样本的 bootstrap 区间没有意义(会退化成点, 被误判"显著")
        return (None, None)
    if len(set(xs)) == 1:
        return (xs[0], xs[0])
    rnd = random.Random(seed)
    ms = sorted(sum(rnd.choice(xs) for _ in xs) / len(xs) for _ in range(n))
    return (ms[int(0.025 * n)], ms[int(0.975 * n) - 1])


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def verdict(lift, ci, n, min_rank=None):
    if not n:
        return "无数据"
    if ci[0] is not None and ci[0] > 0:
        v = "显著赢"
    elif ci[1] is not None and ci[1] < 0:
        v = "显著输"
    else:
        v = "点赢" if lift > 1e-12 else "点输" if lift < -1e-12 else "平"
    return v + ("·不足以排序" if n < (MIN_RANK if min_rank is None else min_rank) else "")


def aggregate(rows, metric, min_rank=None):
    kind = METRICS[metric][0]
    cv = [r["chain"][metric] for r in rows if r["chain"] and r["chain"].get(metric) is not None]
    out = {"kind": kind, "n_chain": len(cv), "chain": mean(cv)}
    out["chain_ci"] = wilson(sum(cv), len(cv)) if kind == "acc" else boot_ci(cv)
    for base in ("persist", "ctrl"):
        pr = [(r["chain"][metric], r[base][metric]) for r in rows
              if r["chain"] and r.get(base) and r["chain"].get(metric) is not None and r[base].get(metric) is not None]
        diffs = [(y - x) if kind == "err" else (x - y) for x, y in pr]
        lift = mean(diffs)
        ci = boot_ci(diffs)
        out[base] = {"n": len(pr), "base": mean([y for _, y in pr]), "chain_paired": mean([x for x, _ in pr]),
                     "lift": lift, "lift_ci": ci, "verdict": verdict(lift or 0, ci, len(pr), min_rank), "diffs": diffs}
    return out


# ---------------- 主计算 ----------------
def build_days(pair, chain, real, ctrl, px, days, th=None):
    rows = []
    for d in days:
        if not (real.has(d) and chain.has(d)):
            continue
        p1 = px.prev(d)
        p2 = px.prev(p1) if p1 else None
        ret = lambda c, a=p1, b=d: px.ret(c, a, b) if a else None  # noqa: E731
        mw = (th or DEF_TH)["min_w"]
        rs = real.snap(d, mw)
        rp1 = real.snap(p1, mw) if p1 else None
        rf = derive(rp1, rs, ret, th)
        cf = derive(chain.snap(p1, px) if p1 else None, chain.snap(d, px), ret, th)
        pf = derive(real.snap(p2, mw) if p2 else None, rp1, lambda c, a=p2, b=p1: px.ret(c, a, b) if a else None, th) if rp1 else None
        kf = derive(ctrl.snap(p1, px) if p1 else None, ctrl.snap(d, px), ret, th) if ctrl and ctrl.has(d) else None
        rows.append({"date": d, "real": rf, "chainf": cf, "persistf": pf, "ctrlf": kf,
                     "chain": compare(cf, rf, th), "persist": compare(pf, rf, th), "ctrl": compare(kf, rf, th)})
    return rows


def diagnose(rows):
    """区分"真像"与"只是不交易/空仓像"(启发式, 报告里写明)"""
    n = len(rows)
    if not n:
        return {}
    act = [r for r in rows if r["real"]["trade"]]
    rate = lambda key, who: mean([float(bool(r[who][key])) for r in rows if r[who]])  # noqa: E731
    d = {"days": n, "真人交易率": rate("trade", "real"), "链交易率": rate("trade", "chainf"),
         "真人空仓率": mean([float(r["real"]["n"] == 0) for r in rows]), "链空仓率": mean([float(r["chainf"]["n"] == 0) for r in rows]),
         "真人动日链也动": mean([float(r["chainf"]["trade"]) for r in act]) if act else None,
         "延续_真人动日也动": mean([float(r["persistf"]["trade"]) for r in act if r["persistf"]]) if act else None,
         "L1一致中双静占比": None}
    agree = [r for r in rows if r["chainf"]["trade"] == r["real"]["trade"]]
    if agree:
        d["L1一致中双静占比"] = mean([float(not r["real"]["trade"]) for r in agree])
    hold_days = [r for r in rows if r["real"]["n"] > 0]
    d["真人有仓日链有同票"] = mean([float(bool(r["chainf"]["hold"] & r["real"]["hold"])) for r in hold_days]) if hold_days else None
    tags = []
    if n < 3:   # 1~2 天不打标签
        d["标签"] = tags
        return d
    if (d["链交易率"] or 0) < (d["真人交易率"] or 0) - 0.3:
        tags.append("交易显著少于真人")
    if (d["链交易率"] or 0) > (d["真人交易率"] or 0) + 0.3:
        tags.append("交易显著多于真人")
    if (d["链空仓率"] or 0) > (d["真人空仓率"] or 0) + 0.3:
        tags.append("空仓显著多于真人")
    if (d["链空仓率"] or 0) < (d["真人空仓率"] or 0) - 0.3:
        tags.append("空仓显著少于真人")
    if d["L1一致中双静占比"] is not None and d["L1一致中双静占比"] > 0.5:
        tags.append("L1 一致主要来自双方都不动")
    if hold_days and not d["真人有仓日链有同票"]:
        tags.append("持仓从未与真人重合")
    d["标签"] = tags
    return d


CFG = load_cfg()


def run(days, mode_label):
    names = load(HERE / "names.json") or {}
    pairs = [(b, l) for b, l in PAIRS if (BOOKS / f"{b}.json").exists() and (TZ / l / "day_positions.json").exists()]
    reals = {l: Real(l) for _, l in pairs}
    chains = {b: Chain(b, names) for b, _ in pairs}
    ctrl = Chain(CONTROL, names) if (BOOKS / f"{CONTROL}.json").exists() else None
    # 行情: 窗口前 20 天起, 覆盖真人持仓/动作票 + 链成交票
    beg = (dt.date.fromisoformat(days[0]) - dt.timedelta(days=25)).isoformat()
    codes = set()
    for r in reals.values():
        for k, rec in r.dp.items():
            if k >= beg.replace("-", ""):
                codes |= {str(x.get("code")) for x in (rec or {}).get("list") or []}
    for c in list(chains.values()) + ([ctrl] if ctrl else []):
        codes |= {str(t["code"]) for t in c.trades}
    px = Prices.from_db(codes, beg)
    if not px.ok:   # 退化日历: 真人 day_positions 日期并集(工作日)
        cal = sorted({f"{k[:4]}-{k[4:6]}-{k[6:]}" for r in reals.values() for k in r.dp if dt.date(int(k[:4]), int(k[4:6]), int(k[6:])).weekday() < 5})
        px = Prices({}, cal)
    tdays = [d for d in days if d in px.cal] if px.cal else days
    res = {"mode": mode_label, "days": tdays, "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
           "books_read": {b: c.mtime for b, c in chains.items()} | ({CONTROL: ctrl.mtime} if ctrl else {}),
           "params": {"fallback": {"EPS_DIR": EPS_DIR, "MIN_W": MIN_W, "TP_BINS": TP_BINS, "MIN_RANK": MIN_RANK}, "BOOT_N": BOOT_N, "SEED": SEED,
                      "mimicry_cfg": CFG},
           "price_source": "本地行情库 kline_day" if px.c else "无(成交价/中性漂移)", "pairs": {}, "skipped": {}, "checks": {}}
    pooled = collections.defaultdict(lambda: {"persist": [], "ctrl": []})
    ind_cov = [0, 0]
    for b, l in pairs:
        real, chain = reals[l], chains[b]
        th, th_info = calibrate(real_snaps(real, (tdays or days)[-1], CFG), CFG)   # 10/16 晚: 按导师动态阈值(params.yaml mimicry)
        rows = build_days((b, l), chain, real, ctrl, px, tdays, th)
        if not rows:
            res["skipped"][b] = f"窗口内无配对日(真人数据最新 {real.last}, 链 nav 最新 {max(chain.nav) if chain.nav else None})"
            continue
        # 校验: 重放持仓市值 vs 账本 nav.mv
        dev = []
        for r in rows:
            rec = chain.navrec.get(r["date"]) or {}
            if rec.get("nav"):
                dev.append(abs(r["chainf"]["tp"] - float(rec.get("mv") or 0) / float(rec["nav"])))
        res["checks"][b] = {"重放仓位vs账本mv最大偏差": round(max(dev), 4) if dev else None}
        for r in rows:
            for f in (r["real"], r["chainf"]):
                ind_cov[0] += f["ind_known"]
                ind_cov[1] += f["foot_n"]
        aggs = {m: aggregate(rows, m, th["min_rank"]) for m in METRICS}
        for m, a in aggs.items():
            for base in ("persist", "ctrl"):
                pooled[m][base] += a[base]["diffs"]
        wins = sum(1 for m in MAIN if (aggs[m]["persist"]["lift"] or 0) > 1e-12)
        res["pairs"][b] = {"ledger": l, "name": l, "real_last": real.last, "n_days": len(rows), "thresholds": th_info,
                           "metrics": {m: {k: v for k, v in a.items()} | {"persist": {k: v for k, v in a["persist"].items() if k != "diffs"},
                                                                          "ctrl": {k: v for k, v in a["ctrl"].items() if k != "diffs"}}
                                       for m, a in aggs.items()},
                           "main_wins_vs_persist": wins, "diagnosis": diagnose(rows),
                           "daily": [{"date": r["date"], "real": brief(r["real"], real.names), "chain": brief(r["chainf"], names),
                                      "persist": brief(r["persistf"], real.names) if r["persistf"] else None,
                                      "scores": {"chain": r["chain"], "persist": r["persist"], "ctrl": r["ctrl"]}} for r in rows]}
    led_names = {x["ledger"]: x.get("name") for x in load(ROOT / "scripts" / "tzzb" / "tzzb_ledgers.json") or []}
    for b, p in res["pairs"].items():
        p["name"] = led_names.get(p["ledger"], p["ledger"])
    res["industry_coverage"] = round(ind_cov[0] / ind_cov[1], 3) if ind_cov[1] else None
    res["pooled"] = {}
    for m in METRICS:
        res["pooled"][m] = {}
        for base in ("persist", "ctrl"):
            xs = pooled[m][base]
            ci = boot_ci(xs)
            res["pooled"][m][base] = {"n": len(xs), "lift": mean(xs), "lift_ci": ci, "verdict": verdict(mean(xs) or 0, ci, len(xs))}
    return res


def brief(f, names):
    if f is None:
        return None
    nm = lambda s: sorted(names.get(c, c) for c in s)  # noqa: E731
    return {"trade": f["trade"], "buy": nm(f["buys"]), "hold": nm(f["hold"]), "tp": round(f["tp"], 3), "n": f["n"], "mx": round(f["mx"], 3),
            "dir": f["dir"], "net": None if f["net"] is None else round(f["net"], 3), "turn": None if f["turn"] is None else round(f["turn"], 3),
            "boards": dict(f["boards"])}


# ---------------- 输出 ----------------
def fmt(x, kind="sim"):
    if x is None:
        return "—"
    return f"{x:.0%}" if kind in ("acc", "sim") else f"{x:.2f}"


def fmt_lift(x, kind):
    if x is None:
        return "—"
    return (f"{x:+.0%}" if kind in ("acc", "sim") else f"{x:+.2f}")


def markdown(res):
    L = [f"# 分层拟人度(A 线 vs 导师真人) {res['mode']}", "",
         f"> 生成 {res['generated_at']}(零 token, 只读) | 交易日 {', '.join(res['days'])} | 价格源: {res['price_source']} | 行业缓存覆盖率 {fmt(res['industry_coverage'])}",
         f"> books 读取的是生成时刻的实盘版(文件修改时间见 json books_read; 今晚重跑后会整本替换, 届时需重算)",
         "> 基线: 延续=导师真人前一交易日原样当今天的预测(MILA 口径); 对照=A-control(无 persona)。lift>0=链比基线更像; 误差类 lift=基线误差−链误差。",
         f"> 配对天数 < 该导师 min_rank(见阈值表; 全链合并用固定 {MIN_RANK})一律标\"不足以排序\"; 区间=Wilson(0/1)/bootstrap(lift) 95%。", "",
         "## 一、主指标(每层一个) 链 / 延续 / lift(vs 延续) / lift(vs 对照)", "",
         "| 链 | 导师 | 天 | L1 交易一致 | L2 方向一致 | L3 持仓 Jaccard | L4 总仓误差 | 主指标赢延续 | 诊断标签 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for b, p in res["pairs"].items():
        cells = []
        for m in MAIN:
            a = p["metrics"][m]
            k = a["kind"]
            cells.append(f"{fmt(a['chain'], k)} / {fmt(a['persist']['base'], k)} / {fmt_lift(a['persist']['lift'], k)} / {fmt_lift(a['ctrl']['lift'], k)}")
        L.append(f"| {b} | {p['name']} | {p['n_days']} | " + " | ".join(cells) + f" | {p['main_wins_vs_persist']}/4 | {'、'.join(p['diagnosis'].get('标签') or []) or '—'} |")
    if res["skipped"]:
        L += ["", "未进表: " + "; ".join(f"{b}: {why}" for b, why in res["skipped"].items())]
    L += ["", f"## 阈值(params.yaml mimicry 节; auto=按该导师近 {CFG.get('lookback_days')} 个有记录日的分布算, 样本不足/退化回落 fixed)", "",
          "| 链 | 导师 | 方向阈值 eps_dir | 碎仓门槛 min_w | 总仓分档 tp_bins | 排序最少天数 min_rank |", "|---|---|---|---|---|---|"]
    for b, p in res["pairs"].items():
        t = p.get("thresholds") or {}
        tc = lambda k: (f"{t[k]['value']} · {t[k]['src']}" + (f" n={t[k]['n']}" if t[k].get("n") is not None else "")) if k in t else "—"  # noqa: E731
        L.append(f"| {b} | {p['name']} | {tc('eps_dir')} | {tc('min_w')} | {tc('tp_bins')} | {tc('min_rank')} |")
    L += ["", "## 二、全链合并(所有导师配对日拼在一起; 检验\"LLM 链整体\"是否赢基线)", "",
          "| 指标 | vs 延续: n / lift [95%] / 判定 | vs 对照: n / lift [95%] / 判定 |", "|---|---|---|"]
    for m, v in res["pooled"].items():
        k = METRICS[m][0]
        cell = lambda x: f"{x['n']} / {fmt_lift(x['lift'], k)} [{fmt_lift(x['lift_ci'][0], k)}, {fmt_lift(x['lift_ci'][1], k)}] / {x['verdict']}"  # noqa: E731
        L.append(f"| {m} | {cell(v['persist'])} | {cell(v['ctrl'])} |")
    L += ["", "## 三、逐链全部指标", ""]
    for b, p in res["pairs"].items():
        dg = p["diagnosis"]
        L += [f"### {b}({p['name']}, 真人数据至 {p['real_last']}, {p['n_days']} 天)", "",
              f"- 交易率 真人 {fmt(dg.get('真人交易率'))} / 链 {fmt(dg.get('链交易率'))}; 空仓率 真人 {fmt(dg.get('真人空仓率'))} / 链 {fmt(dg.get('链空仓率'))}; "
              f"真人动的日子链也动 {fmt(dg.get('真人动日链也动'))}(延续 {fmt(dg.get('延续_真人动日也动'))}); L1 一致里双静占 {fmt(dg.get('L1一致中双静占比'))}; "
              f"真人有仓日链持同票 {fmt(dg.get('真人有仓日链有同票'))}", "",
              "| 指标 | n | 链 [95%] | 延续(配对) | lift vs 延续 [95%] | 判定 | 对照(配对) | lift vs 对照 | 判定 |", "|---|---|---|---|---|---|---|---|---|"]
        for m, a in p["metrics"].items():
            k = a["kind"]
            ps, cs = a["persist"], a["ctrl"]
            L.append(f"| {m} | {a['n_chain']} | {fmt(a['chain'], k)} [{fmt(a['chain_ci'][0], k)}, {fmt(a['chain_ci'][1], k)}] | {fmt(ps['base'], k)} | "
                     f"{fmt_lift(ps['lift'], k)} [{fmt_lift(ps['lift_ci'][0], k)}, {fmt_lift(ps['lift_ci'][1], k)}] | {ps['verdict']} | "
                     f"{fmt(cs['base'], k)} | {fmt_lift(cs['lift'], k)} | {cs['verdict']} |")
        L.append("")
        if len(p["daily"]) <= 12:
            L += ["| 日 | 真人 持仓(总仓) / 买入 / 方向 | 链 持仓(总仓) / 买入 / 方向 |", "|---|---|---|"]
            dn = {1: "加", -1: "减", 0: "平", None: "?"}
            for x in p["daily"]:
                r, c = x["real"], x["chain"]
                L.append(f"| {x['date'][5:]} | {'、'.join(r['hold']) or '空'}({r['tp']:.0%}) / {'、'.join(r['buy']) or '—'} / {dn[r['dir']]} | "
                         f"{'、'.join(c['hold']) or '空'}({c['tp']:.0%}) / {'、'.join(c['buy']) or '—'} / {dn[c['dir']]} |")
            L.append("")
    L += ["## 口径备注", "",
          "- 链持仓=成交流水按 trade id 日期重放到当日收盘(同 similarity.mjs), 权重=股数×行情库收盘价/账本当日 nav; 真人=day_positions position_percent(占总资产, 融资可 >100%), 剔逆回购。",
          "- 真人当日买/卖 = day_positions op 码(3 建/7·1 加/4 清/8·2 减/9 当日有买有卖) ∪ 逐笔腿方向; 港股等链买不到的票照样计入真人行为。",
          "- 方向/换手用\"去价格漂移\"权重变化: 只算当天动过的票, f=w_今 − w_昨×(1+r_票)/(1+r_账户); 日内 T(收盘仓不变)对方向/换手不可见, 双方同口径。",
          f"- 实质持仓门槛 min_w(按导师见阈值表, 回落 {MIN_W:.0%}): 低于它的碎仓/观察仓不进持仓集合、只数、板块/行业足迹, 只计入总仓; 同一配对里链/延续/对照都用该导师的阈值。",
          f"- 方向阈值 eps_dir(回落 ±{EPS_DIR:.0%} 资产)、总仓分档边界 tp_bins(回落 {TP_BINS})按导师见阈值表; 持仓/买入 Jaccard 双空=无定义不计(不把\"一起空仓\"记成像); 板块/行业=足迹每票等权的分布重合。",
          "- 行业来自 downloads/f10 缓存(东财二级行业, mentor_scope 口径), 本脚本不联网, 缓存缺失的票不计入行业层(覆盖率见页首)。", ""]
    return "\n".join(L)


def strip_diffs(res):
    return json.loads(json.dumps(res, ensure_ascii=False, default=lambda o: sorted(o) if isinstance(o, set) else str(o)))


def write(res, stem):
    OUT.mkdir(parents=True, exist_ok=True)
    md = markdown(res)
    (OUT / f"{stem}.md").write_text(md, encoding="utf-8")
    (OUT / f"{stem}.json").write_text(json.dumps(strip_diffs(res), ensure_ascii=False, indent=1), encoding="utf-8")
    return md


# ---------------- 自测(构造数据, 不读真实文件) ----------------
def selftest():
    ok = [0, 0]

    def check(name, cond):
        ok[1] += 1
        ok[0] += bool(cond)
        print(("  PASS " if cond else "  FAIL ") + name)

    S = lambda d, hold, buy=(), sell=(), nav=None: {"date": d, "hold": dict(hold), "buy": set(buy), "sell": set(sell), "nav": nav, "names": {}}  # noqa: E731
    flat = lambda c: None  # noqa: E731
    print("[L1/L2 基本]")
    a0, a1 = S("d0", {}), S("d1", {"600000": 0.5}, buy=["600000"], nav=1.0)
    f = derive(S("d0", {}, nav=1.0), a1, flat)
    check("新开半仓 → 交易/买/方向+1/换手0.5", f["trade"] and f["buy"] and not f["sell"] and f["dir"] == 1 and abs(f["turn"] - 0.5) < 1e-9)
    g = derive(None, a1, flat)
    check("无昨日快照 → 方向/换手无定义", g["dir"] is None and g["turn"] is None)
    # 去漂移: 持仓 50% 票涨 10%, 账户涨 5%, 没交易
    p, c = S("d0", {"600000": 0.5}, nav=1.0), S("d1", {"600000": 0.5 * 1.1 / 1.05}, nav=1.05)
    h = derive(p, c, lambda x: 0.10)
    check("只涨价不交易 → 方向 0、换手 0", h["dir"] == 0 and h["turn"] == 0 and not h["trade"])
    # 做 T: 有买有卖但收盘仓位不变 → 交易=1 方向=0
    c2 = S("d1", {"600000": 0.5 * 1.1 / 1.05}, buy=["600000"], sell=["600000"], nav=1.05)
    t = derive(p, c2, lambda x: 0.10)
    check("日内 T → 交易一致可见、方向=平", t["trade"] and t["dir"] == 0 and abs(t["turn"]) < 1e-9)
    # 减仓: 卖一半
    c3 = S("d1", {"600000": 0.25}, sell=["600000"], nav=1.0)
    check("卖出一半 → 方向 −1", derive(p, c3, lambda x: 0.0)["dir"] == -1)
    # 换股: 卖 A 买 B 等额 → 方向 平, 换手 1.0
    p4 = S("d0", {"600000": 0.5}, nav=1.0)
    c4 = S("d1", {"000001": 0.5}, buy=["000001"], sell=["600000"], nav=1.0)
    x4 = derive(p4, c4, lambda x: 0.0)
    check("等额换股 → 方向平、换手 1.0", x4["dir"] == 0 and abs(x4["turn"] - 1.0) < 1e-9)
    print("[L3]")
    check("Jaccard 双空 = 无定义", jac(set(), set()) is None)
    check("Jaccard 一空一有 = 0", jac({"a"}, set()) == 0)
    check("Jaccard {a,b} vs {b,c} = 1/3", abs(jac({"a", "b"}, {"b", "c"}) - 1 / 3) < 1e-9)
    fa = derive(None, S("d", {"600000": 0.5}), flat)
    fb = derive(None, S("d", {"300001": 0.5}), flat)
    fc = derive(None, S("d", {"601398": 0.3}, buy=["300750"]), flat)
    check("板块: 主板 vs 创业板 = 0", overlap(fa["boards"], fb["boards"]) == 0)
    check("板块: 主板 vs (主板+创业板) = 0.5", abs(overlap(fa["boards"], fc["boards"]) - 0.5) < 1e-9)
    check("板块: 空足迹 = 无定义", overlap(collections.Counter(), fa["boards"]) is None)
    dz = derive(None, S("d", {"600000": 0.5, "000002": 0.005}), flat)
    check("碎仓 <2% 不进持仓集合/只数, 总仓照算", dz["hold"] == {"600000"} and dz["n"] == 1 and abs(dz["tp"] - 0.505) < 1e-9)
    check("逆回购剔除", is_repo("204001") and is_repo("131810") and not is_repo("600000"))
    print("[L4]")
    m = compare(derive(None, S("d", {"600000": 0.9, "000001": 0.1}), flat), derive(None, S("d", {"600000": 0.4}), flat))
    check("总仓误差 0.6 / 只数误差 1 / 最大仓误差 0.5 / 分档不同", abs(m["L4_总仓误差"] - 0.6) < 1e-9 and m["L4_只数误差"] == 1
          and abs(m["L4_最大仓误差"] - 0.5) < 1e-9 and m["L4_总仓分档"] == 0)
    ident = compare(fc, fc)
    check("与自身比较: 全部满分/零误差", all((v in (1.0, 0.0, None)) for v in ident.values()) and ident["L1_交易"] == 1 and ident["L4_总仓误差"] == 0
          and ident["L3_持仓Jaccard"] == 1 and ident["L3_板块"] == 1)
    print("[统计]")
    lo, hi = wilson(5, 10)
    check("Wilson 5/10 ≈ [0.237, 0.763]", abs(lo - 0.2366) < 1e-3 and abs(hi - 0.7634) < 1e-3)
    check("Wilson 0/0 = 无", wilson(0, 0) == (None, None))
    check("bootstrap 常数序列区间=点", boot_ci([0.2] * 5) == (0.2, 0.2))
    check("verdict n<MIN_RANK 带\"不足以排序\"", verdict(0.1, (0.05, 0.2), 5) == "显著赢·不足以排序")
    check("verdict 区间跨 0 = 点赢", verdict(0.1, (-0.1, 0.3), 30) == "点赢")
    check("样本 <3 不给 bootstrap 区间, 判定只给点估计", boot_ci([0.5, 0.5]) == (None, None) and verdict(0.5, boot_ci([0.5]), 1) == "点赢·不足以排序")
    print("[基线逻辑: 端到端构造序列]")
    # 真人: 长拿型, 4 天都持 600000 不动; 链A: 每天换票; 链B: 抄真人昨日(=延续) → lift 0
    days = ["d1", "d2", "d3", "d4"]
    real = {d: S(d, {"600000": 0.9}, nav=1.0) for d in ["d0"] + days}
    chainA = {"d0": S("d0", {}, nav=1.0)}
    for i, d in enumerate(days):
        code = f"00000{i + 1}"
        prevc = list(chainA[(["d0"] + days)[i]]["hold"])
        chainA[d] = S(d, {code: 0.9}, buy=[code], sell=prevc, nav=1.0)
    rows = []
    allds = ["d0"] + days
    for i, d in enumerate(days):
        p1 = allds[i]
        p2 = allds[i - 1] if i >= 1 else None
        rf = derive(real[p1], real[d], lambda c: 0.0)
        pf = derive(real[p2] if p2 else None, real[p1], lambda c: 0.0)
        cf = derive(chainA[p1], chainA[d], lambda c: 0.0)
        rows.append({"date": d, "real": rf, "chainf": cf, "persistf": pf, "ctrlf": None,
                     "chain": compare(cf, rf), "persist": compare(pf, rf), "ctrl": None})
    a = aggregate(rows, "L1_交易")
    check("长拿真人: 延续 L1=100%, 天天换票链 L1=0% → lift −100%", a["persist"]["base"] == 1 and a["chain"] == 0 and a["persist"]["lift"] == -1)
    check("  → 判定 显著输·不足以排序", a["persist"]["verdict"] == "显著输·不足以排序")
    j = aggregate(rows, "L3_持仓Jaccard")
    check("长拿真人: 延续持仓 Jaccard=1, 链=0", j["persist"]["base"] == 1 and j["chain"] == 0)
    e = aggregate(rows, "L4_总仓误差")
    check("总仓都 90% → 误差类 lift=0(平)", e["persist"]["lift"] == 0 and e["persist"]["verdict"].startswith("平"))
    check("对照缺失 → n=0 无数据", a["ctrl"]["n"] == 0 and a["ctrl"]["verdict"] == "无数据")
    # 快轮动真人: 每天换票; 链完美复制当天 → 赢延续
    realF = {"d0": S("d0", {"600001": 0.9}, nav=1.0)}
    for i, d in enumerate(days):
        realF[d] = S(d, {f"60000{i + 2}": 0.9}, buy=[f"60000{i + 2}"], sell=[f"60000{i + 1}"], nav=1.0)
    rows2 = []
    for i, d in enumerate(days):
        p1, p2 = allds[i], (allds[i - 1] if i >= 1 else None)
        rf = derive(realF[p1], realF[d], lambda c: 0.0)
        pf = derive(realF[p2] if p2 else None, realF[p1], lambda c: 0.0)
        rows2.append({"date": d, "real": rf, "chainf": rf, "persistf": pf, "ctrlf": None, "chain": compare(rf, rf), "persist": compare(pf, rf), "ctrl": None})
    j2 = aggregate(rows2, "L3_买入Jaccard")
    check("快轮动真人: 完美复制链 买入 Jaccard=1, 延续=0 → lift +100%", j2["chain"] == 1 and j2["persist"]["base"] == 0 and j2["persist"]["lift"] == 1)
    l2 = aggregate(rows2, "L2_方向")
    check("快轮动等额换股: 方向都=平, 延续首日无定义被剔除(n=3)", l2["persist"]["n"] == 3 and l2["chain"] == 1)
    dg = diagnose(rows)
    check("诊断: 长拿真人 vs 天天换票链 → 标签含\"持仓从未与真人重合\"", "持仓从未与真人重合" in dg["标签"])
    print("[动态阈值 calibrate]")
    cfgA = json.loads(json.dumps(DEF_CFG))
    for k in ("eps_dir", "min_w", "tp_bins", "min_rank"):
        cfgA[k]["mode"] = "auto"
    sn, prevw = [], 0.5   # 构造导师: 30 天, 主仓 0.5~0.9 轮换 + 0.5% 碎仓, 隔天交易
    for i in range(30):
        w = 0.5 + 0.1 * (i % 5)
        tr = i % 2 == 1
        sn.append((f"2026-09-{i + 1:02d}", S(f"d{i}", {"600000": w, "000002": 0.005}, buy=["600000"] if tr and w > prevw else [],
                                             sell=["600000"] if tr and w <= prevw else [], nav=1.0)))
        prevw = w
    thA, infA = calibrate(sn, cfgA)
    check("auto min_w: 碎仓 0.5% 落在 P10 → 在 [0.003, 0.02)", 0.003 <= thA["min_w"] < 0.02 and infA["min_w"]["src"].startswith("auto"))
    check("auto eps_dir: 在 [0.01, 0.10] 内且来自 auto", 0.01 <= thA["eps_dir"] <= 0.10 and infA["eps_dir"]["src"].startswith("auto"))
    check("auto tp_bins: 4 个边界递增", len(thA["tp_bins"]) == 4 and list(thA["tp_bins"]) == sorted(thA["tp_bins"]) and infA["tp_bins"]["src"].startswith("auto"))
    check("auto min_rank: 交易日占比 50% → ceil(10/0.5)=20", thA["min_rank"] == 20)
    thB, infB = calibrate(sn[:5], cfgA)
    check("样本不足 → 回落 fixed 并写明原因", thB["min_w"] == MIN_W and "样本不足" in infB["min_w"]["src"] and thB["eps_dir"] == EPS_DIR)
    full = [(f"2026-09-{i + 1:02d}", S(f"d{i}", {"600000": 1.0}, nav=1.0)) for i in range(25)]
    thC, infC = calibrate(full, cfgA)
    check("恒满仓 → 总仓分档退化回落 fixed; 无交易 → min_rank 回落", tuple(thC["tp_bins"]) == TP_BINS and "退化" in infC["tp_bins"]["src"]
          and thC["min_rank"] == MIN_RANK)
    thD, _ = calibrate(sn, json.loads(json.dumps(DEF_CFG)))
    check("mode=fixed → 全用配置值", thD["min_w"] == MIN_W and thD["eps_dir"] == EPS_DIR and tuple(thD["tp_bins"]) == TP_BINS and thD["min_rank"] == MIN_RANK)
    p0, c0 = S("d0", {"600000": 0.5}, nav=1.0), S("d1", {"600000": 0.53}, buy=["600000"], nav=1.0)
    check("eps_dir=2% 时 +3% 净加仓判 +1(固定 5% 判 0)", derive(p0, c0, lambda x: 0.0, {**DEF_TH, "eps_dir": 0.02})["dir"] == 1
          and derive(p0, c0, lambda x: 0.0)["dir"] == 0)
    check("verdict 用导师 min_rank", verdict(0.1, (0.05, 0.2), 15, 12) == "显著赢" and verdict(0.1, (0.05, 0.2), 15) == "显著赢·不足以排序")
    check("params.yaml mimicry 节可读", isinstance(load_cfg().get("eps_dir"), dict) and load_cfg()["eps_dir"].get("mode") in ("auto", "fixed"))
    print(f"自测 {ok[0]}/{ok[1]} 通过")
    return ok[0] == ok[1]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(0 if selftest() else 1)
    today = dt.date.today().isoformat()
    if a.date:
        days, stem, label = [a.date], a.date, f"单日 {a.date}"
    else:
        since = a.since or START
        until = a.until or today
        d0, d1 = dt.date.fromisoformat(since), dt.date.fromisoformat(until)
        days = [(d0 + dt.timedelta(i)).isoformat() for i in range((d1 - d0).days + 1)]
        stem, label = f"cum_{since}_{until}", f"累计 {since}~{until}"
    res = run(days, label)
    md = write(res, stem)
    if not a.quiet:
        print(md)
    print(f"写出 {OUT / (stem + '.md')} / .json", file=sys.stderr)


if __name__ == "__main__":
    main()
