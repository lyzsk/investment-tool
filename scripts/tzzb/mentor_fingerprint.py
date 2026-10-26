# -*- coding: utf-8 -*-
"""
mentor_fingerprint.py — tzzb 导师深度沉淀·机械层(2026-10-16 建, 零 token, 只读)

从导师的"果"(成交腿/持仓)机械还原"因": 每笔真实买卖发生时该股与市场的状态
  → 打法分布 / 选股指纹 / 买点指纹 / 卖出指纹 / 市况-仓位 / 盘中节奏 + 机械规则 + 指纹池时间外验证。
统一打法分类器 classify_play()/classify_sell() 是纯函数(输入=特征 dict), 配套 event_features() 由行情面板算特征,
  可被 paper 等脚本直接 import 复用(本脚本内已用它给 paper 链成交分类)。

数据(全部只读):
  downloads/tzzb/<ledger>/change_bs_*.json(逐笔腿, 复用 gen_tzzb_profile.load_legs 的去重+两融归一) / day_positions.json / nav_daily.json
  行情库 investment_market: kline_day / security_master / lhb_stock(只 SELECT)
  md/<年>S<季>/<日>.md 的「## 涨停分析」(题材归属, 2026-01-15 起有)
  scripts/dfcf/paper/books/A-*.json(paper 链成交, 只读)
不调 LLM、不访问任何行情网络接口、不写业务库、不起子进程。

用法(scripts/venv/Scripts/python.exe -X utf8):
  mentor_fingerprint.py --all                     全部 kind=pos 导师: persona/fingerprint.md + cases_auto.jsonl + 研究报告
  mentor_fingerprint.py --ledger liuyiqing        单人(只写该人 persona 两文件)
  mentor_fingerprint.py --all --asof 2026-09-01   只用 D 之前数据(防后见之明); 产物写 scripts/tzzb/pools/asof_<D>/, 不碰 persona
  mentor_fingerprint.py --pool --date 2026-10-19  用 D 之前数据出 D 日各导师模拟自选股池 → scripts/tzzb/pools/<D>.json
  mentor_fingerprint.py --selftest
"""
import argparse
import bisect
import datetime as dtm
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/tzzb"))
from gen_tzzb_profile import load_legs  # noqa: E402  (只读 json, 无副作用)
sys.path.insert(0, str(ROOT / "scripts/lib"))
import a_rules as AR  # noqa: E402  10/16 晚: 交易规则统一模块(涨跌停按日期; 本文件只留向量化实现, 口径与它一致)

POOL_DIR = ROOT / "scripts/tzzb/pools"
BOOKS = ROOT / "scripts/dfcf/paper/books"
REPORT = ROOT / "scripts/tzzb/model_out/reports/mentor_fingerprint_20261016.md"
LEDGERS = json.loads((ROOT / "scripts/tzzb/tzzb_ledgers.json").read_text(encoding="utf-8"))
MENTORS = [l["ledger"] for l in LEDGERS if l.get("kind") == "pos"]
NAME_OF = {l["ledger"]: l["name"] for l in LEDGERS}

PANEL_START = "2025-06-01"      # 最早买入 2025-09-25, 留 60+ 交易日回看
POOL_N = (30, 50)               # 模拟自选股池大小
TRAIN_FRAC = 0.7                # 时间外验证: 前 70% 买入日定规则, 后 30% 验证
RULE_DAILY_MAX = 60             # 单条规则每日命中股数上限(池子几十只量级)
LOOKBACK_TRADED = 60            # "回头票"= 近 60 交易日内本人交易过
THEME_LOOK = 120                # 个股题材归属回看 120 交易日
INDEX_SH, INDEX_CY = "sh000001", "sz399006"
STOCK_ASSETS = ("MAIN", "GEM", "STAR", "BSE")
ASSET_CN = {"MAIN": "主板", "GEM": "创业板", "STAR": "科创板", "BSE": "北交所", "ETF": "ETF", "CB": "转债",
            "HK": "港股", "REPO": "逆回购", "OTHER": "其他", "INDEX": "指数"}
LIMIT_R = {"MAIN": 0.10, "GEM": 0.20, "STAR": 0.20, "BSE": 0.30}   # 股票基础档(面板 2025-06 起: 创业板早已 20%); ST/新股/转债/ETF 见 Market._derive
ST_MAIN_10_FROM = AR.D_RULES_2026   # 2026-07-06 起主板 ST 由 5% 改 10%(沪深交易规则 2026 修订)


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ====================================================================================
# 一、代码/板块/涨停价 —— 纯函数
# ====================================================================================
def asset_class(code):
    """6 位代码(tzzb 口径, 无交易所前缀) → 资产类别"""
    c = str(code)
    if re.fullmatch(r"\d{5}", c):
        return "HK"
    if not re.fullmatch(r"\d{6}", c):
        return "OTHER"
    if c[:3] in ("688", "689"):
        return "STAR"
    if c[:2] == "60":
        return "MAIN"
    if c[:3] in ("000", "001", "002", "003", "004"):
        return "MAIN"
    if c[:2] == "30":
        return "GEM"
    if c[:2] == "92" or c[0] in "48":
        return "BSE"
    if c[:2] in ("51", "52", "56", "58", "53", "55", "50", "15", "16", "18"):
        return "ETF"
    if c[:3] in ("110", "111", "113", "118", "123", "127", "128"):
        return "CB"
    if c[:3] in ("204", "131"):
        return "REPO"
    return "OTHER"


def symbol_of(code):
    a = asset_class(code)
    if a in ("HK", "OTHER", "REPO"):
        return None
    if a == "BSE":
        return "bj" + code
    if code[0] in "65" or code[:2] == "11":
        return "sh" + code
    return "sz" + code


def asset_of_symbol(sym):
    ex, c = sym[:2], sym[2:]
    if (ex == "sh" and c[:3] == "000") or (ex == "sz" and c[:3] == "399"):
        return "INDEX"
    if ex not in ("sh", "sz", "bj"):
        return "OTHER"
    a = asset_class(c)
    if ex == "sh" and a == "MAIN" and c[0] != "6":
        return "OTHER"
    return a


def round2(x):
    return np.floor(np.asarray(x, dtype=np.float64) * 100 + 0.5 + 1e-6) / 100


def limit_price(pre_close, asset, is_st=False, day_high=None, day_low=None, date=None):
    """涨/跌停价(单值, 股票)。主板 ST: 2026-07-06 起=10%(交易规则 2026 修订); 之前=5%——但 ST 身份只知道"现在"或成交名称,
    所以 2026-07-06 前用当日区间验证: 最高≤+5%价且最低≥-5%价 → 当时是 ST(5% 档), 超出 → 当时不是 ST(10% 档)。
    date=None 按今天的规则(10/16 晚修: 原"2025 年起两档并存"说法错误, 两档是按日期切换不是并存)"""
    r = LIMIT_R.get(asset)
    if r is None or not pre_close or pre_close != pre_close:
        return None, None
    up, dn = float(round2(pre_close * (1 + r))), float(round2(pre_close * (1 - r)))
    if is_st and asset == "MAIN" and AR.ndate(date) < ST_MAIN_10_FROM:
        u5, d5 = float(round2(pre_close * 1.05)), float(round2(pre_close * 0.95))
        if (day_high is None or day_high <= u5 + 0.005) and (day_low is None or day_low >= d5 - 0.005):
            up, dn = u5, d5
    return up, dn


# ====================================================================================
# 二、统一打法分类器 —— 纯函数(输入 dict, 不碰 IO)
# ====================================================================================
PLAY_ORDER = ["连板接力", "首板打板", "首板次日", "炸板次日", "涨停回调", "次新", "突破新高", "追涨", "超跌反弹",
              "趋势回踩", "趋势跟随", "弱势震荡", "ETF/宽基", "转债", "数据缺失", "其他"]
PLAY_DEF = {
    "连板接力": "昨日已≥2连板(任意价买), 或昨日首板+今日在涨停价买(二板打板)",
    "首板打板": "昨日非涨停, 买价≥今日涨停价-0.005(在涨停价成交)",
    "首板次日": "昨日首板(1 连板), 今日未在涨停价买(半路/低吸/弱转强)",
    "炸板次日": "昨日盘中触及涨停但收盘未封(炸板), 今日买",
    "涨停回调": "D-10~D-2 内有过涨停(昨日不是), 今日买(多为回调低吸/再起)",
    "次新": "上市不足 30 个交易日(面板内 K 线<30 根)且不属以上",
    "突破新高": "买价(复权)>前 20 日最高价",
    "追涨": "买价相对昨收涨幅≥5% 且不在涨停价",
    "超跌反弹": "昨日 20 日涨幅≤-15%, 或 5 日涨幅≤-10%, 或 20 日区间位置≤0.1 且 20 日涨幅≤-8%",
    "趋势回踩": "昨收>MA20 且 MA20 较 5 日前上行, 买价(复权)≤MA5×1.01(回踩 5 日线附近)",
    "趋势跟随": "昨收>MA20 且 MA20 上行, 买价在 MA5 上方",
    "弱势震荡": "以上皆否(MA20 下方或 MA20 不上行、未超跌、未追涨)",
    "ETF/宽基": "ETF/LOF 等场内基金",
    "转债": "可转债(转债 T)",
    "数据缺失": "港股/本地无该日行情(退市转债、10/09 前北交所)",
    "其他": "有行情但关键特征缺失",
}


def time_bucket(tstr):
    if not tstr or tstr in ("00:00:00", "00:00"):
        return None
    t = tstr[:8]
    if t <= "09:25:59":
        return "竞价"
    if t < "09:35:00":
        return "开盘5分钟"
    if t < "10:30:00":
        return "早盘"
    if t < "14:30:00":
        return "盘中"
    return "尾盘"


def classify_play(f):
    """买入打法分类. f = event_features() 输出(或同键 dict). 返回 (主标签, [副标签])。
    主标签只依赖"买入前状态(D-1 收盘)+买价+当日涨停价", 不依赖当日收盘 → 实盘/paper 可同口径实时用。
    副标签: 时段(要成交时刻)、执行(打板/追涨/低吸, 低吸用当日最终高低区间=日线降级口径)、放量/热点/龙虎榜/ST/降级标记。"""
    subs = []
    a = f.get("asset")
    tb = time_bucket(f.get("time"))
    if tb:
        subs.append(tb)
    if a == "ETF":
        return "ETF/宽基", subs
    if a == "CB":
        return "转债", subs
    if not f.get("data"):
        return "数据缺失", subs + [ASSET_CN.get(a, a or "?")]
    if f.get("price_degraded"):
        subs.append("降级:无成交价按收盘")
    at_lim = bool(f.get("at_limit"))
    bp = f.get("buy_pct")
    if at_lim:
        subs.append("打板")
    elif bp is not None and bp >= 0.05:
        subs.append("追涨")
    elif f.get("pos_in_day") is not None and f["pos_in_day"] <= 0.3 and (bp is None or bp <= 0.01):
        subs.append("低吸")
    if (f.get("volr_day") or 0) >= 2:
        subs.append("放量")
    if f.get("hot_prev") == 1 or f.get("hot_day") == 1:
        subs.append("热点题材")
    if f.get("lhb_prev"):
        subs.append("昨龙虎榜")
    if f.get("is_st"):
        subs.append("ST")
    H = f.get("H_prev") or 0
    if H >= 2 or (H == 1 and at_lim):
        return "连板接力", subs
    if at_lim:
        return "首板打板", subs
    if H == 1:
        return "首板次日", subs
    if f.get("zb_prev"):
        return "炸板次日", subs
    age = f.get("zt_age_prev")
    if age is not None and 1 <= age <= 9:
        return "涨停回调", subs
    if (f.get("nbars_prev") or 0) < 30:
        return "次新", subs
    if f.get("brk20"):
        return "突破新高", subs
    if bp is not None and bp >= 0.05:
        return "追涨", subs
    r20, r5, p20 = f.get("ret20_prev"), f.get("ret5_prev"), f.get("pos20_prev")
    if r20 is None and r5 is None:
        return "其他", subs
    if (r20 is not None and r20 <= -0.15) or (r5 is not None and r5 <= -0.10) or \
            (p20 is not None and r20 is not None and p20 <= 0.1 and r20 <= -0.08):
        return "超跌反弹", subs
    if f.get("above_ma20_prev") and f.get("ma20_up_prev"):
        if f.get("price_vs_ma5_prev") is not None and f["price_vs_ma5_prev"] <= 0.01:
            return "趋势回踩", subs
        return "趋势跟随", subs
    return "弱势震荡", subs


SELL_ORDER = ["日内T", "止损", "冲高止盈", "止盈", "时间止损/平走", "小盈亏快出", "成本未知"]
SELL_DEF = {
    "日内T": "卖出的筹码是当日买入的(T+0 回转, 两融/底仓做T)",
    "止损": "相对 FIFO 成本 ≤-3%",
    "冲高止盈": "≥+3% 且卖价在当日区间上 40%(位置≥0.6) 且卖出时相对昨收≥+2%",
    "止盈": "≥+3% 其余(回落兑现/低位兑现)",
    "时间止损/平走": "|盈亏|<3% 且持有≥5 个交易日",
    "小盈亏快出": "|盈亏|<3% 且持有<5 个交易日",
    "成本未知": "卖出筹码早于数据窗口(无 FIFO 成本)",
}


def classify_sell(pnl, hold_days, same_day, sell_pos_in_day=None, sell_pct=None):
    if same_day:
        return "日内T"
    if pnl is None:
        return "成本未知"
    if pnl <= -0.03:
        return "止损"
    if pnl >= 0.03:
        if sell_pos_in_day is not None and sell_pos_in_day >= 0.6 and sell_pct is not None and sell_pct >= 0.02:
            return "冲高止盈"
        return "止盈"
    if hold_days is not None and hold_days >= 5:
        return "时间止损/平走"
    return "小盈亏快出"


def dist(labels, order=None):
    c = Counter(labels)
    n = sum(c.values())
    keys = order or [k for k, _ in c.most_common()]
    return {k: c.get(k, 0) / n for k in keys if c.get(k, 0)} if n else {}


def js_distance(p, q):
    """Jensen-Shannon 距离(sqrt(JSD), log2, ∈[0,1]); p/q 为 {标签: 概率}"""
    ks = set(p) | set(q)
    if not ks:
        return None
    P = np.array([p.get(k, 0.0) for k in ks]); Q = np.array([q.get(k, 0.0) for k in ks])
    if P.sum() == 0 or Q.sum() == 0:
        return None
    P, Q = P / P.sum(), Q / Q.sum()
    Mx = (P + Q) / 2

    def kl(a, b):
        m = a > 0
        return float(np.sum(a[m] * np.log2(a[m] / b[m])))
    return math.sqrt(max(0.0, 0.5 * kl(P, Mx) + 0.5 * kl(Q, Mx)))


def overlap(p, q):
    return sum(min(p.get(k, 0), q.get(k, 0)) for k in set(p) | set(q))


# ====================================================================================
# 三、题材(md 涨停分析)
# ====================================================================================
def md_path(day):
    y, m = day[:4], int(day[5:7])
    return ROOT / "md" / f"{y}S{(m + 2) // 3}" / f"{day}.md"


def norm_name(s):
    return re.sub(r"[\s\*＊]", "", s or "").replace("Ａ", "A")


def parse_md_themes(day):
    """→ [(题材, 名称, 代码或None, 是否涨停)]; 无该节返回 None"""
    p = md_path(day)
    if not p.exists():
        return None
    c = p.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"\n## 涨停分析\n(.*?)(?=\n## |\Z)", c, re.S)
    if not m:
        return None
    out, theme = [], None
    for line in m[1].split("\n"):
        h = re.match(r"###\s+(.+)", line)
        if h:
            theme = re.sub(r"\s+", "", h[1])
            continue
        if not theme:
            continue
        if line.startswith("|"):
            cells = [x.strip() for x in line.strip().strip("|").split("|")]
            if len(cells) < 3 or re.fullmatch(r":?-+:?", cells[0]) or cells[0] in ("股票名称", "股票"):
                continue
            nm = cells[0]
            code = None
            mc = re.search(r"(\d{6})", nm)
            if mc:
                code = mc[1]
                nm = nm[:mc.start()]
            nm = norm_name(re.sub(r"<br>", "", nm))
            board = cells[1] if len(cells) > 1 else ""
            if not nm:
                continue
            out.append((theme, nm, code, board.strip() not in ("--", "-", "")))
        else:
            ms = re.match(r"\d+\.\s*\\?([^|]+)\|.*?\|\s*(\d{6})\s*\|", line)   # ST 股节列表格式
            if ms:
                out.append((theme, norm_name(ms[1]), ms[2], True))
    return out if out else None


THEME_EXCLUDE = {"其他", "ST股"}


# ====================================================================================
# 四、行情面板(全市场日线矩阵, 只读 SELECT)
# ====================================================================================
def _db():
    sys.path.insert(0, str(ROOT / "scripts/quotes"))
    from kline_db import db   # 只读连接 investment_market
    return db()


NUM_BINS = {   # 名称: (面板属性, 边界, 单位, 标签格式)
    "股价": ("close", [5, 10, 20, 50], "元"),
    "流通市值": ("fmcap_e8", [30, 60, 150, 500], "亿"),
    "成交额": ("amt_e8", [1, 3, 10, 30], "亿"),
    "换手": ("turn", [2, 5, 10, 20], "%"),
    "5日涨幅": ("ret5p", [-10, -3, 3, 10, 25], "%"),
    "20日涨幅": ("ret20p", [-15, 0, 15, 40], "%"),
    "20日位置": ("pos20", [0.2, 0.5, 0.8], ""),
    "量比": ("volr", [0.7, 1.5, 3], ""),
}
CAT_LABELS = {
    "板块": ["主板", "创业板", "科创板", "北交所", "ETF"],
    "昨涨跌": ["≤-5%", "-5~-2%", "-2~0%", "0~2%", "2~5%", "≥5%未板", "涨停"],
    "连板": ["0", "1板", "2板", "3板+"],
    "近10日涨停(非昨日)": ["否", "是"],
    "昨炸板": ["否", "是"],
    "均线形态": ["MA20上且上行", "MA20上未上行", "MA20下且上行", "MA20下且下行"],
    "昨热点题材": ["否", "是"],
    "昨龙虎榜": ["否", "是"],
    "ST": ["否", "是"],
    "次新(上市<60交易日)": ["否", "是"],
    "回头票": ["否", "是"],
}
ORDERED = set(NUM_BINS) | {"昨涨跌", "连板"}


def num_labels(edges, unit):
    labs = [f"<{edges[0]}{unit}"]
    for a, b in zip(edges[:-1], edges[1:]):
        labs.append(f"{a}~{b}{unit}")
    labs.append(f"≥{edges[-1]}{unit}")
    return labs


for _k, (_a, _e, _u) in NUM_BINS.items():
    CAT_LABELS[_k] = num_labels(_e, _u)


class Market:
    def __init__(self, asof=None, start=PANEL_START):
        t0 = time.time()
        self.asof = asof
        end = asof or "2999-12-31"
        conn = _db()
        try:
            cur = conn.cursor()
            cur.execute("select symbol, trade_date, cast(open as double), cast(high as double), cast(low as double), cast(close as double), "
                        "cast(pre_close as double), volume, cast(amount as double), cast(turnover_rate as double) "
                        "from kline_day where trade_date >= %s and trade_date < %s", (start, end))
            rows = cur.fetchall()
            cur.execute("select symbol, name, is_st, list_date from security_master")
            sm = cur.fetchall()
            cur.execute("select distinct trade_date, symbol from lhb_stock where trade_date >= %s and trade_date < %s", (start, end))
            lhb = cur.fetchall()
            # 流通股本=静态属性: 只有 10/09 起有换手率, 用 量/换手 反推(as-of 模式也用它 = 已知的轻度后见, 股本变动慢)
            cur.execute("select symbol, volume, cast(turnover_rate as double) from kline_day where trade_date >= '2026-10-09' and turnover_rate > 0 and volume > 0")
            fsr = cur.fetchall()
        finally:
            conn.close()
        log(f"[行情] DB 读 {len(rows)} 行 {time.time() - t0:.1f}s")
        sa = {s: asset_of_symbol(s) for s in {r[0] for r in rows}}
        keep_assets = set(STOCK_ASSETS) | {"ETF", "CB", "INDEX"}
        dates_o = sorted({r[1] for r in rows if r[0] == INDEX_SH})
        self.dates = [d.isoformat() for d in dates_o]
        self.didx = {d: i for i, d in enumerate(self.dates)}
        dmap = {d: i for i, d in enumerate(dates_o)}
        keep = [r for r in rows if sa[r[0]] in keep_assets and r[1] in dmap]
        self.syms = sorted({r[0] for r in keep})
        self.sidx = {s: j for j, s in enumerate(self.syms)}
        self.asset = np.array([sa[s] for s in self.syms])
        nd, ns = len(self.dates), len(self.syms)
        n = len(keep)
        ii = np.fromiter((dmap[r[1]] for r in keep), np.int32, n)
        jj = np.fromiter((self.sidx[r[0]] for r in keep), np.int32, n)
        for nm, k in (("O", 2), ("H", 3), ("L", 4), ("C", 5), ("PC", 6), ("V", 7), ("A", 8), ("T", 9)):
            arr = np.full((nd, ns), np.nan)
            arr[ii, jj] = np.array([np.nan if r[k] is None else float(r[k]) for r in keep])
            setattr(self, nm, arr)
        del rows, keep
        smap = {r[0]: r for r in sm}
        self.name = {s: (smap[s][1] if s in smap else s) for s in self.syms}
        st_extra = set()                          # 历史 ST: 当前 is_st 之外, 任一导师成交腿名称带 ST 的票也按 ST(5%/10% 档再由当日区间判)
        for l in LEDGERS:
            try:
                for t in load_legs(l["ledger"]):
                    if "ST" in (t.get("stock_name") or ""):
                        st_extra.add(symbol_of(t["stock_code"]))
            except (OSError, KeyError, ValueError):
                pass
        self.is_st = np.array([(bool(smap[s][2]) if s in smap and smap[s][2] is not None else ("ST" in (smap.get(s, (0, ""))[1] or ""))) or s in st_extra
                               for s in self.syms])
        self.list_date = {s: smap[s][3].isoformat() for s in self.syms if s in smap and smap[s][3]}
        self.name2sym = {}
        for s in self.syms:
            if self.asset[self.sidx[s]] in STOCK_ASSETS:
                self.name2sym.setdefault(norm_name(self.name[s]), s)
        g = defaultdict(list)
        for s, v, t in fsr:
            g[s].append(float(v) / (t / 100))
        self._fs = {s: float(np.median(x)) for s, x in g.items()}
        self.lhb = np.zeros((nd, ns), bool)
        for d, s in lhb:
            i, j = dmap.get(d), self.sidx.get(s)
            if i is not None and j is not None:
                self.lhb[i, j] = True
        self._derive()
        self._themes()
        self._cats()
        log(f"[行情] 面板 {nd} 日 × {ns} 标的 ({self.dates[0]}~{self.dates[-1]}) 共 {time.time() - t0:.1f}s")

    # ---------- 派生指标(每行只依赖 ≤ 该行的数据, 无后见) ----------
    def _derive(self):
        C, PC, H, L, O, V, A, T = self.C, self.PC, self.H, self.L, self.O, self.V, self.A, self.T
        nd, ns = C.shape
        has = np.isfinite(C)
        self.has = has
        with np.errstate(all="ignore"):
            self.pct = C / PC - 1
            lr = np.log(C / PC)
            lr[~np.isfinite(lr)] = 0
            adj = np.exp(np.cumsum(lr, axis=0))
            adjC = np.where(has, adj, np.nan)
            k = adjC / C
            adjH, adjL = H * k, L * k
        self.adjC = adjC
        self.adjk = k                     # 原价 → 复权价 系数
        dfC = pd.DataFrame(adjC)
        dfF = dfC.ffill()
        self.adjF = dfF.values
        self.ma = {n: dfC.rolling(n, min_periods=max(3, int(n * 0.6))).mean().values for n in (5, 10, 20, 60)}
        self.ret = {n: (dfF / dfF.shift(n) - 1).values for n in (3, 5, 20)}
        self.hh20prev = pd.DataFrame(adjH).rolling(20, min_periods=10).max().shift(1).values
        hh = pd.DataFrame(adjH).rolling(20, min_periods=10).max().values
        ll = pd.DataFrame(adjL).rolling(20, min_periods=10).min().values
        with np.errstate(all="ignore"):
            self.pos20 = (adjC - ll) / (hh - ll)
            self.volr = V / pd.DataFrame(V).rolling(5, min_periods=3).mean().shift(1).values
            approx_amt = V * (O + H + L + C) / 4
            self.amt = np.where(np.isfinite(A) & (A > 0), A, approx_amt)
        self.fs = np.full(ns, np.nan)
        for s, v in self._fs.items():                            # 流通股本(10/09 起有换手率的日子反推, 历史沿用=降级)
            j = self.sidx.get(s)
            if j is not None:
                self.fs[j] = v
        with np.errstate(all="ignore"):
            self.fmcap = C * self.fs[None, :]
            self.turn = np.where(np.isfinite(T) & (T > 0), T, V / self.fs[None, :] * 100)
        self.nbars = np.cumsum(has, axis=0)
        self.ma20_up = np.zeros((nd, ns), bool)
        self.ma20_up[5:] = self.ma[20][5:] > self.ma[20][:-5]
        # 涨跌停(10/16 晚按 scripts/lib/a_rules.py 口径重写): 股票按板块; 转债 20%(上市首日 +57.3%/-43.3%); ETF 10%(科创/创业类 20%);
        #   主板 ST 只在 2026-07-06 前是 5%(且用当日区间验证当时是否 ST, 见 limit_price); 新股无涨跌幅窗口: 沪深前 5 日、北交所首日
        r = np.array([LIMIT_R.get(a, np.nan) for a in self.asset])
        for j, s in enumerate(self.syms):
            if self.asset[j] in ("ETF", "CB"):
                band = AR.limit_band(s, self.dates[-1], name=self.name.get(s), is_st=False, listing_n=99, lookup=False)
                r[j] = band[0] if band else np.nan
        dec = np.where(np.isin(self.asset, ("ETF", "CB")), 1000.0, 100.0)[None, :]   # 最小价位: 股票 0.01, 转债/ETF 0.001
        rnd = lambda x: np.floor(x * dec + 0.5 + 1e-6) / dec   # noqa: E731  四舍五入到最小价位
        with np.errstate(all="ignore"):
            lu, ld = rnd(PC * (1 + r)), rnd(PC * (1 - r))
            u5, d5 = round2(PC * 1.05), round2(PC * 0.95)
            st_main = (self.is_st & (self.asset == "MAIN"))[None, :]
            pre26 = (np.array(self.dates) < ST_MAIN_10_FROM)[:, None]
            reg5 = st_main & pre26 & (H <= u5 + 0.005) & (L >= d5 - 0.005)
        lu = np.where(reg5, u5, lu)
        ld = np.where(reg5, d5, ld)
        for s, ldt in self.list_date.items():                     # 新股无涨跌幅限制: 沪深前 5 个交易日, 北交所首日
            j = self.sidx[s]
            i0 = bisect.bisect_left(self.dates, ldt)
            if i0 < nd:
                k = 1 if self.asset[j] == "BSE" else 5
                lu[i0:i0 + k, j] = np.nan
                ld[i0:i0 + k, j] = np.nan
        has_cb = np.isfinite(C) & (self.asset == "CB")[None, :]
        for j in np.where(has_cb.any(axis=0))[0]:                  # 转债上市首日(面板内首根且不是面板首日): +57.3%/-43.3%(前收=发行价)
            i0 = int(np.argmax(has_cb[:, j]))
            if i0 > 0 and np.isfinite(PC[i0, j]):
                lu[i0, j] = np.floor(PC[i0, j] * 1.573 * 1000 + 0.5 + 1e-6) / 1000
                ld[i0, j] = np.floor(PC[i0, j] * 0.567 * 1000 + 0.5 + 1e-6) / 1000
        self.lu, self.ld = lu, ld
        with np.errstate(all="ignore"):
            half = 0.5 / dec   # 半个最小价位
            self.zt = has & np.isfinite(lu) & (C >= lu - half)
            self.zb = has & np.isfinite(lu) & (H >= lu - half) & ~self.zt
            self.dtl = has & np.isfinite(ld) & (C <= ld + half)
        Hn = np.zeros((nd, ns), np.int16)
        age = np.full((nd, ns), 99, np.int16)
        for i in range(nd):
            prevH = Hn[i - 1] if i else np.zeros(ns, np.int16)
            prevA = age[i - 1] if i else np.full(ns, 98, np.int16)
            Hn[i] = np.where(self.zt[i], prevH + 1, 0)
            age[i] = np.where(self.zt[i], 0, np.minimum(prevA + 1, 99))
        self.Hn, self.zt_age = Hn, age
        # 市场宽度
        stock = np.isin(self.asset, STOCK_ASSETS)[None, :] & has
        with np.errstate(all="ignore"):
            self.up_n = ((self.pct > 0) & stock).sum(1)
            self.down_n = ((self.pct < 0) & stock).sum(1)
            self.zt_n = (self.zt & stock).sum(1)
            self.dt_n = (self.dtl & stock).sum(1)
            self.stock_n = stock.sum(1)
            self.med_pct = np.nanmedian(np.where(stock, self.pct, np.nan), axis=1)
        js, jc = self.sidx.get(INDEX_SH), self.sidx.get(INDEX_CY)
        self.idx_pct = self.pct[:, js] if js is not None else np.full(nd, np.nan)
        self.cy_pct = self.pct[:, jc] if jc is not None else np.full(nd, np.nan)
        self.idx_ret5 = self.ret[5][:, js] if js is not None else np.full(nd, np.nan)

    # ---------- 题材 ----------
    def _themes(self):
        nd, ns = self.C.shape
        self.md_ok = np.zeros(nd, bool)
        self.hot3 = [set() for _ in range(nd)]
        self.ladder = [set() for _ in range(nd)]
        self.theme_zt = [Counter() for _ in range(nd)]
        hist = defaultdict(list)          # sym → [(row, theme)]
        matched = unmatched = 0
        for i, day in enumerate(self.dates):
            rows = parse_md_themes(day)
            if not rows:
                continue
            self.md_ok[i] = True
            cnt = Counter()
            for th, nm, code, is_zt in rows:
                s = None
                if code:
                    s = symbol_of(code)
                    s = s if s in self.sidx else None
                if s is None:
                    s = self.name2sym.get(nm)
                if s is None:
                    unmatched += 1
                    continue
                matched += 1
                hist[s].append((i, th))
                if is_zt and th not in THEME_EXCLUDE:
                    cnt[th] += 1
            self.theme_zt[i] = cnt
            self.hot3[i] = {t for t, _ in cnt.most_common(3)}
            self.ladder[i] = {t for t, n in cnt.items() if n >= 3}
        self.theme_hist = {s: (np.array([r for r, _ in v]), [t for _, t in v]) for s, v in hist.items()}
        self.theme_match = (matched, unmatched)
        hot = np.zeros((nd, ns), np.int8)            # 0=当日无 md, 1=否, 2=是
        for i in range(nd):
            if not self.md_ok[i]:
                continue
            hot[i] = 1
            for s in self.theme_hist:
                if self.themes_of(s, i) & self.hot3[i]:
                    hot[i, self.sidx[s]] = 2
        self.hot = hot

    def themes_of(self, sym, i, look=THEME_LOOK):
        h = self.theme_hist.get(sym)
        if h is None:
            return set()
        rows, ths = h
        lo, hi = bisect.bisect_left(rows, i - look), bisect.bisect_right(rows, i)
        return set(ths[lo:hi])

    # ---------- 分箱特征矩阵(行 = 某日收盘状态) ----------
    def _cats(self):
        nd, ns = self.C.shape
        cats = {}
        amap = {"MAIN": 1, "GEM": 2, "STAR": 3, "BSE": 4, "ETF": 5}
        cats["板块"] = np.broadcast_to(np.array([amap.get(a, 0) for a in self.asset], np.int8), (nd, ns)).copy()
        src = {"close": self.C, "fmcap_e8": self.fmcap / 1e8, "amt_e8": self.amt / 1e8, "turn": self.turn,
               "ret5p": self.ret[5] * 100, "ret20p": self.ret[20] * 100, "pos20": self.pos20, "volr": self.volr}
        for k, (attr, edges, _u) in NUM_BINS.items():
            x = src[attr]
            c = (np.searchsorted(np.array(edges, float), np.nan_to_num(x, nan=-1e18), side="right") + 1).astype(np.int8)
            c[~np.isfinite(x)] = 0
            cats[k] = c
        p = self.pct * 100
        c = (np.searchsorted(np.array([-5, -2, 0, 2, 5], float), np.nan_to_num(p, nan=-1e18), side="right") + 1).astype(np.int8)
        c[self.zt] = 7
        c[~np.isfinite(p)] = 0
        cats["昨涨跌"] = c
        cats["连板"] = (np.minimum(self.Hn, 3) + 1).astype(np.int8)
        cats["近10日涨停(非昨日)"] = np.where((self.zt_age >= 1) & (self.zt_age <= 9), 2, 1).astype(np.int8)
        cats["昨炸板"] = np.where(self.zb, 2, 1).astype(np.int8)
        with np.errstate(all="ignore"):
            above = self.adjC > self.ma[20]
        up = self.ma20_up
        mc = np.where(above & up, 1, np.where(above, 2, np.where(up, 3, 4))).astype(np.int8)
        mc[~np.isfinite(self.ma[20]) | ~self.has] = 0
        cats["均线形态"] = mc
        cats["昨热点题材"] = self.hot.copy()
        cats["昨龙虎榜"] = np.where(self.lhb, 2, 1).astype(np.int8)
        cats["ST"] = np.broadcast_to(np.where(self.is_st, 2, 1).astype(np.int8), (nd, ns)).copy()
        cx = np.ones((nd, ns), np.int8)
        for s, ldt in self.list_date.items():          # 上市日来自 security_master(北交所无上市日 → 一律按否)
            i0 = bisect.bisect_left(self.dates, ldt)
            if i0 < nd:
                cx[max(0, i0):min(nd, i0 + 60), self.sidx[s]] = 2
        cats["次新(上市<60交易日)"] = cx
        for k in cats:
            if k != "板块":
                cats[k][~self.has] = 0
        self.cats = cats

    def row_before(self, day):
        """D 之前最后一个交易日行号(D 本身不在面板也可, 用于盘前出池)"""
        i = bisect.bisect_left(self.dates, day) - 1
        return i if i >= 0 else None


def _f(x, nd=4):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if math.isfinite(x) else None


def event_features(M, sym, d, price=None, tstr=None, name=None):
    """某标的在面板第 d 行(交易日)的买卖事件特征。pre=第 d-1 行收盘状态(买入前可知); day=第 d 行(当日, 描述性)。
    price=成交价(None → 按当日收盘降级); tstr='HH:MM:SS'。"""
    asset = asset_of_symbol(sym) if sym else None
    f = {"symbol": sym, "asset": asset, "time": tstr, "data": False}
    if sym is None or d is None:
        return f
    j = M.sidx.get(sym)
    if j is None or d < 1 or not M.has[d, j]:
        return f
    p = d - 1
    is_st = bool(M.is_st[j]) or ("ST" in (name or ""))
    f["data"] = bool(M.has[p, j]) or asset in ("ETF", "CB")
    f["is_st"] = is_st
    pc, o, h, l, c = M.PC[d, j], M.O[d, j], M.H[d, j], M.L[d, j], M.C[d, j]
    if is_st and not M.is_st[j]:
        lu, _ld = limit_price(pc, asset, True, h, l, M.dates[d])
    else:
        lu = M.lu[d, j] if np.isfinite(M.lu[d, j]) else None
    deg = price is None or not price
    px = c if deg else float(price)
    f["price_degraded"] = deg
    with np.errstate(all="ignore"):
        k_d = M.adjk[d, j]
        f.update({
            "close_prev": _f(M.C[p, j], 3), "pct_prev": _f(M.pct[p, j]), "ret3_prev": _f(M.ret[3][p, j]),
            "ret5_prev": _f(M.ret[5][p, j]), "ret20_prev": _f(M.ret[20][p, j]),
            "zt_prev": bool(M.zt[p, j]), "zb_prev": bool(M.zb[p, j]), "dt_prev": bool(M.dtl[p, j]),
            "H_prev": int(M.Hn[p, j]), "zt_age_prev": int(M.zt_age[p, j]) if M.zt_age[p, j] < 99 else None,
            "pos20_prev": _f(M.pos20[p, j]), "nbars_prev": int(M.nbars[p, j]),
            "ma5r_prev": _f(M.adjC[p, j] / M.ma[5][p, j] - 1), "ma20r_prev": _f(M.adjC[p, j] / M.ma[20][p, j] - 1),
            "ma60r_prev": _f(M.adjC[p, j] / M.ma[60][p, j] - 1),
            "above_ma20_prev": bool(M.adjC[p, j] > M.ma[20][p, j]), "ma20_up_prev": bool(M.ma20_up[p, j]),
            "volr_prev": _f(M.volr[p, j], 2), "amt_prev_e8": _f(M.amt[p, j] / 1e8, 2), "turn_prev": _f(M.turn[p, j], 2),
            "fmcap_prev_e8": _f(M.fmcap[p, j] / 1e8, 1),
            "hot_prev": int(M.hot[p, j]) - 1 if M.hot[p, j] else None, "lhb_prev": bool(M.lhb[p, j]),
            # 当日
            "open_pct": _f(o / pc - 1), "high_pct": _f(h / pc - 1), "low_pct": _f(l / pc - 1), "close_pct": _f(c / pc - 1),
            "zt_day": bool(M.zt[d, j]), "zb_day": bool(M.zb[d, j]), "dt_day": bool(M.dtl[d, j]), "lu_day": _f(lu, 3),
            "volr_day": _f(M.volr[d, j], 2), "amt_day_e8": _f(M.amt[d, j] / 1e8, 2), "turn_day": _f(M.turn[d, j], 2),
            "hot_day": int(M.hot[d, j]) - 1 if M.hot[d, j] else None, "lhb_day": bool(M.lhb[d, j]),
            # 买卖点
            "price": _f(px, 3), "buy_pct": _f(px / pc - 1),
            "at_limit": bool(lu is not None and px >= lu - AR.tick(sym) / 2) if not deg else bool(M.zt[d, j]),
            "pos_in_day": _f((px - l) / (h - l), 3) if h > l else 0.5, "vs_open": _f(px / o - 1),
            "brk20": bool(np.isfinite(M.hh20prev[d, j]) and px * k_d > M.hh20prev[d, j] + 1e-9),
            "price_vs_ma5_prev": _f(px * k_d / M.ma[5][p, j] - 1),
            # 结果(事后, 只用于案例/卖出评估, 不进分类)
            "r_close": _f(c / px - 1),
            "r_next": _f(M.C[d + 1, j] / px - 1) if d + 1 < len(M.dates) and M.has[d + 1, j] else None,
            "r_5d": _f(M.adjF[min(d + 5, len(M.dates) - 1), j] / (px * k_d) - 1) if d + 5 < len(M.dates) else None,
            # 大盘
            "idx_pct_prev": _f(M.idx_pct[p]), "idx_pct_day": _f(M.idx_pct[d]), "idx_ret5_prev": _f(M.idx_ret5[p]),
            "zt_n_prev": int(M.zt_n[p]), "dt_n_prev": int(M.dt_n[p]),
            "up_ratio_prev": _f(M.up_n[p] / max(1, M.up_n[p] + M.down_n[p]), 3),
            "zt_n_day": int(M.zt_n[d]), "up_ratio_day": _f(M.up_n[d] / max(1, M.up_n[d] + M.down_n[d]), 3),
        })
    if f["above_ma20_prev"] is False and not np.isfinite(M.ma[20][p, j]):
        f["above_ma20_prev"] = None
    f["themes"] = sorted(M.themes_of(sym, d))
    return f


# ====================================================================================
# 五、导师事件(买/卖按 日×票 聚合, FIFO 成本, 持仓矩阵)
# ====================================================================================
def sec_of(t):
    return int(t[0:2]) * 3600 + int(t[3:5]) * 60 + int(t[6:8])


class Mentor:
    def __init__(self, ledger, M, asof=None):
        self.ledger, self.name, self.M = ledger, NAME_OF.get(ledger, ledger), M
        legs = [t for t in load_legs(ledger) if not asof or t["trans_date"][:10] < asof]
        for t in legs:
            t["_q"] = float(t.get("trans_count") or 0)
            t["_p"] = float(t.get("trans_price") or 0)
        legs.sort(key=lambda t: (t["trans_date"], t["op"] != "1"))
        self.legs = legs
        base = ROOT / "downloads/tzzb" / ledger
        dp = json.loads((base / "day_positions.json").read_text(encoding="utf-8")) if (base / "day_positions.json").exists() else {}
        self.day_pos = {f"{k[:4]}-{k[4:6]}-{k[6:]}": v for k, v in dp.items() if not asof or f"{k[:4]}-{k[4:6]}-{k[6:]}" < asof}
        nav = json.loads((base / "nav_daily.json").read_text(encoding="utf-8"))["ex_data"]["index_list"]
        self.asset_by_day = {f"{x['date'][:4]}-{x['date'][4:6]}-{x['date'][6:]}": float(x.get("asset") or 0) for x in nav}
        self.nav_days = sorted(d for d in self.asset_by_day if not asof or d < asof)
        self._events()

    def _events(self):
        M = self.M
        byday = defaultdict(list)
        for t in self.legs:
            byday[t["trans_date"][:10]].append(t)
        self.byday = byday
        qty = defaultdict(float)
        lots = defaultdict(list)              # code → [[qty, price, row, day]]
        buys, sells = [], []
        held_close = {}                        # day → set(code) 收盘持有(腿推算 ∪ day_positions)
        all_days = sorted(set(byday) | set(self.day_pos))
        for day in all_days:
            d = M.didx.get(day)
            pre_qty = {c: q for c, q in qty.items() if q > 1e-9}
            agg = {}
            for t in byday.get(day, []):
                code = t["stock_code"]
                key = (code, t["op"])
                e = agg.setdefault(key, {"date": day, "code": code, "name": t.get("stock_name"), "side": "B" if t["op"] == "1" else "S",
                                         "qty": 0.0, "amt": 0.0, "t_first": t["trans_date"][11:19], "t_last": "", "nlegs": 0,
                                         "matched_q": 0.0, "matched_cost": 0.0, "matched_rev": 0.0, "first_lot_day": None, "sameday_q": 0.0})
                e["qty"] += t["_q"]; e["amt"] += t["_q"] * t["_p"]; e["nlegs"] += 1; e["t_last"] = t["trans_date"][11:19]
                if t["op"] == "1":
                    qty[code] += t["_q"]
                    lots[code].append([t["_q"], t["_p"], d, day])
                else:
                    qty[code] -= t["_q"]
                    need = t["_q"]
                    while need > 1e-9 and lots[code]:
                        lot = lots[code][0]
                        take = min(need, lot[0])
                        e["matched_q"] += take; e["matched_cost"] += take * lot[1]; e["matched_rev"] += take * t["_p"]
                        if lot[3] == day:
                            e["sameday_q"] += take
                        elif e["first_lot_day"] is None or lot[3] < e["first_lot_day"]:
                            e["first_lot_day"] = lot[3]
                        lot[0] -= take; need -= take
                        if lot[0] <= 1e-9:
                            lots[code].pop(0)
            dp_codes = {x.get("code") for x in (self.day_pos.get(day) or {}).get("list") or [] if float(x.get("position_percent") or 0) > 0}
            held_close[day] = {c for c, q in qty.items() if q > 1e-9} | dp_codes
            for (code, op), e in agg.items():
                e["row"] = d
                e["vwap"] = e["amt"] / e["qty"] if e["qty"] else None
                e["held_qty_prev"] = pre_qty.get(code, 0.0)
                (buys if op == "1" else sells).append(e)
        self.held_close = held_close
        days_sorted = sorted(held_close)
        prev_of = {days_sorted[i]: days_sorted[i - 1] for i in range(1, len(days_sorted))}
        traded_rows = defaultdict(list)
        for t in self.legs:
            r = M.didx.get(t["trans_date"][:10])
            if r is not None:
                traded_rows[t["stock_code"]].append(r)
        self.traded_rows = {c: sorted(set(v)) for c, v in traded_rows.items()}
        for e in buys:
            pday = prev_of.get(e["date"])
            prev_held = held_close.get(pday, set()) if pday else set()
            e["new_open"] = e["code"] not in prev_held and e["held_qty_prev"] <= 1e-9
            rows = self.traded_rows.get(e["code"], [])
            r = e["row"]
            e["revisit"] = bool(r is not None and any(r - LOOKBACK_TRADED <= x < r for x in rows))
        for e in sells:
            if e["matched_q"] > 0:
                e["pnl"] = e["matched_rev"] / e["matched_cost"] - 1 if e["matched_cost"] else None
            else:
                e["pnl"] = None
            e["same_day"] = e["matched_q"] > 0 and e["sameday_q"] >= 0.5 * e["matched_q"]
            fr = M.didx.get(e["first_lot_day"]) if e["first_lot_day"] else None
            e["hold_days"] = (e["row"] - fr) if (fr is not None and e["row"] is not None) else (0 if e["same_day"] else None)
        self.buys, self.sells = buys, sells

    def held_matrix(self):
        """收盘持仓矩阵 nd×ns(行=某日收盘后仍持有)"""
        M = self.M
        H = np.zeros((len(M.dates), len(M.syms)), bool)
        days = sorted(self.held_close)
        if not days:
            return H
        cur = set()
        k = 0
        for i, day in enumerate(M.dates):
            while k < len(days) and days[k] <= day:
                cur = self.held_close[days[k]]
                k += 1
            for c in cur:
                s = symbol_of(c)
                j = M.sidx.get(s) if s else None
                if j is not None:
                    H[i, j] = True
        return H

    def revisit_matrix(self):
        """回头票矩阵: 行 i = 截至第 i 日收盘, 近 LOOKBACK_TRADED 交易日内交易过(含当日)"""
        M = self.M
        nd, ns = len(M.dates), len(M.syms)
        X = np.zeros((nd + 1, ns), np.int32)
        for c, rows in self.traded_rows.items():
            s = symbol_of(c)
            j = M.sidx.get(s) if s else None
            if j is None:
                continue
            for r in rows:
                X[r + 1, j] += 1
        cs = np.cumsum(X, axis=0)
        out = np.zeros((nd, ns), bool)
        for i in range(nd):
            lo = max(0, i + 1 - LOOKBACK_TRADED)
            out[i] = (cs[i + 1] - cs[lo]) > 0
        return out


# ====================================================================================
# 六、规则挖掘 + 朴素贝叶斯指纹池
# ====================================================================================
def mentor_cats(M, revisit):
    cats = dict(M.cats)
    cats["回头票"] = np.where(revisit, 2, 1).astype(np.int8)
    return cats


def universe(M, mt_assets):
    allow = set(STOCK_ASSETS) | ({"ETF"} if mt_assets.get("ETF", 0) >= 0.05 else set())
    return np.isin(M.asset, list(allow))[None, :] & M.has & (np.nan_to_num(M.V) > 0)


def targets_of(mt, M, U):
    """新开仓买入(可进池评估的): (买入日行 d, 列 j, 事件)"""
    out = []
    for e in mt.buys:
        if not e["new_open"] or e["row"] is None or e["row"] < 1:
            continue
        s = symbol_of(e["code"])
        j = M.sidx.get(s) if s else None
        if j is None or not U[e["row"] - 1, j]:
            continue
        out.append((e["row"], j, e))
    return out


def nb_fit(cats, rows, bg_mask, tr, alpha=5.0, feats=None):
    """rows: 背景行号数组(=买入日-1); bg_mask: 对应行的候选掩码 (len(rows)×ns); tr: [(row-1, j)] 目标。
    平滑: 导师箱概率向背景收缩 p=(n_b+α·q_b)/(n+α) → 小样本箱倍数趋 1; 背景为 0 的箱倍数=1(不可外推)"""
    model = {}
    rr = np.array([r for r, _ in tr]); jj = np.array([j for _, j in tr])
    for k, X in cats.items():
        if feats is not None and k not in feats:
            continue
        B = len(CAT_LABELS[k]) + 1
        bgc = np.bincount(X[rows][bg_mask].astype(np.int64), minlength=B)[:B].astype(float)
        tc = np.bincount(X[rr, jj].astype(np.int64), minlength=B)[:B].astype(float)
        q = bgc / max(1.0, bgc.sum())
        pm = (tc + alpha * q) / (tc.sum() + alpha)
        with np.errstate(all="ignore"):
            lr = np.where(q > 0, np.log(np.maximum(pm, 1e-12) / np.where(q > 0, q, 1)), 0.0)
        lr[0] = 0.0                                   # 缺失箱不计分(北交所/新股缺历史 ≠ 导师偏好)
        model[k] = lr
    return model


def nb_score_row(cats, model, r):
    s = None
    for k, lr in model.items():
        v = lr[cats[k][r].astype(np.int64)]
        s = v if s is None else s + v
    return s


def atom_text(k, vals):
    labs = CAT_LABELS[k]
    vs = sorted(vals)
    if k in ORDERED and len(vs) > 1:
        a, b = labs[vs[0] - 1], labs[vs[-1] - 1]
        return f"{k} {a}…{b}"
    return f"{k}=" + "/".join(labs[v - 1] for v in vs)


def gen_atoms(cats):
    atoms = []
    for k in cats:
        nb = len(CAT_LABELS[k])
        if k in ORDERED:
            for a in range(1, nb + 1):
                for b in range(a, min(nb, a + 2) + 1):
                    if not (a == 1 and b == nb):
                        atoms.append((k, tuple(range(a, b + 1))))
        elif nb == 2:
            atoms.append((k, (2,)))
        else:
            for v in range(1, nb + 1):
                atoms.append((k, (v,)))
    return atoms


def mine_rules(cats, rows, cand, tr, max_rules=5, beam=15, daily_max=RULE_DAILY_MAX):
    """顺序覆盖 + 束搜索: 规则=≤3 个原子的合取; 约束 日均命中≤daily_max; 目标=覆盖率(相同取 lift 高)"""
    R = len(rows)
    if R == 0 or not tr:
        return []
    rr = np.array([r for r, _ in tr]); jj = np.array([j for _, j in tr])
    pos = {r: i for i, r in enumerate(rows)}
    ri = np.array([pos[r] for r in rr])
    base_rate = len(tr) / max(1, cand.sum())
    amask = {}
    for k, vals in gen_atoms(cats):
        m = np.isin(cats[k][rows], vals) & cand
        hit = m[ri, jj]
        if hit.mean() < 0.08:
            continue
        lift = (hit.sum() / max(1, m.sum())) / base_rate
        if lift < 1.15:
            continue
        amask[(k, vals)] = (m, hit)
    rules, covered = [], np.zeros(len(tr), bool)
    for _ in range(max_rules):
        remain = ~covered
        if remain.sum() < max(3, 0.05 * len(tr)):
            break

        def evaluate(atoms_):
            m = None
            for a in atoms_:
                m = amask[a][0] if m is None else (m & amask[a][0])
            hit = m[ri, jj]
            n = m.sum()
            prec = hit.sum() / max(1, n)
            return {"atoms": atoms_, "mask": m, "hit": hit, "daily": n / R, "cov": hit.mean(),
                    "cov_new": (hit & remain).sum() / len(tr), "prec": prec, "lift": prec / base_rate}
        level = sorted((evaluate((a,)) for a in amask), key=lambda x: -x["cov_new"] * math.log(max(1.0001, x["lift"])))[:beam]
        best = None
        for depth in range(3):
            for x in level:
                if x["daily"] <= daily_max and x["cov_new"] > 0 and (best is None or (x["cov_new"], x["lift"]) > (best["cov_new"], best["lift"])):
                    best = x
            if depth == 2:
                break
            nxt = {}
            for x in level:
                used = {a[0] for a in x["atoms"]}
                for a in amask:
                    if a[0] in used:
                        continue
                    key = tuple(sorted(x["atoms"] + (a,)))
                    if key in nxt:
                        continue
                    y = evaluate(key)
                    if y["cov_new"] <= 0:
                        continue
                    nxt[key] = y
            level = sorted(nxt.values(), key=lambda x: -x["cov_new"] * math.log(max(1.0001, x["lift"])) * (1.0 if x["daily"] <= daily_max else 0.5))[:beam]
            if not level:
                break
        if best is None or best["cov_new"] < 0.05:
            break
        covered |= best["hit"]
        rules.append({"atoms": best["atoms"], "text": " 且 ".join(atom_text(k, v) for k, v in best["atoms"]),
                      "cov": float(best["cov"]), "cov_new": float(best["cov_new"]), "daily": float(best["daily"]),
                      "prec": float(best["prec"]), "lift": float(best["lift"])})
    return rules


def rule_eval(cats, rule, rows, cand, tr):
    if not len(rows) or not tr:
        return None
    pos = {r: i for i, r in enumerate(rows)}
    ri = np.array([pos[r] for r, _ in tr]); jj = np.array([j for _, j in tr])
    m = cand.copy()
    for k, vals in rule["atoms"]:
        m &= np.isin(cats[k][rows], vals)
    hit = m[ri, jj]
    base = len(tr) / max(1, cand.sum())
    prec = hit.sum() / max(1, m.sum())
    return {"cov": float(hit.mean()), "daily": float(m.sum() / len(rows)), "prec": float(prec), "lift": float(prec / base) if base else None}


def pool_eval(M, cats, model, te_pre, cand_fn, Ns=POOL_N):
    """时间外: te_pre=[(买入日前一行 r, j)]; 每个测试买入日用 r 行(前一日收盘)打分取 TopN; 命中=新开仓落池。
    基线: 随机 / 昨涨幅榜 / 昨成交额榜 / 昨涨停按成交额; 候选=有行情且前一日收盘未持有"""
    byrow = defaultdict(list)
    for r, j in te_pre:
        byrow[r].append(j)
    res = {N: Counter() for N in Ns}
    for r, js in byrow.items():
        cand = cand_fn(r)
        idx = np.where(cand)[0]
        if not len(idx):
            continue
        sc = nb_score_row(cats, model, r)[idx]
        pct = np.nan_to_num(M.pct[r, idx], nan=-9)
        amt = np.nan_to_num(M.amt[r, idx], nan=0)
        ztk = np.where(M.zt[r, idx], amt, -1)
        for N in Ns:
            n = min(N, len(idx))
            sets = {
                "pool": set(idx[np.argsort(-sc, kind="stable")[:n]]),
                "gain": set(idx[np.argsort(-pct, kind="stable")[:n]]),
                "amt": set(idx[np.argsort(-amt, kind="stable")[:n]]),
                "zt": set(idx[np.argsort(-ztk, kind="stable")[:n]]),
            }
            c = res[N]
            c["targets"] += len(js); c["days"] += 1; c["rand"] += len(js) * n / len(idx); c["cand"] += len(idx)
            for k, s in sets.items():
                c[k] += sum(1 for j in js if j in s)
    out = {}
    for N, c in res.items():
        t = c["targets"]
        if not t:
            out[N] = None
            continue
        out[N] = {"targets": t, "days": c["days"], "hit": c["pool"] / t, "rand": c["rand"] / t, "gain": c["gain"] / t,
                  "amt": c["amt"] / t, "zt": c["zt"] / t, "cand_avg": c["cand"] / c["days"]}
    return out


# ====================================================================================
# 七、单导师分析
# ====================================================================================
def qs(xs, ps=(0.25, 0.5, 0.75)):
    xs = [x for x in xs if x is not None and math.isfinite(x)]
    if not xs:
        return None
    a = np.array(xs)
    return [float(np.quantile(a, p)) for p in ps]


def pct_s(x, nd=0):
    return "—" if x is None else f"{x * 100:.{nd}f}%"


def share(xs, cond):
    xs = [x for x in xs if x is not None]
    return (sum(1 for x in xs if cond(x)) / len(xs), len(xs)) if xs else (None, 0)


def analyze(ledger, M, asof=None):
    t0 = time.time()
    mt = Mentor(ledger, M, asof)
    R = {"ledger": ledger, "name": mt.name, "asof": asof, "generatedAt": dtm.datetime.now().isoformat(timespec="seconds")}
    if not mt.buys:
        R["empty"] = True
        return R, mt
    # --- 逐笔特征 + 打法 ---
    for e in mt.buys:
        s = symbol_of(e["code"])
        e["f"] = event_features(M, s, e["row"], e["vwap"], e["t_first"], e["name"]) if e["row"] is not None else \
            {"symbol": s, "asset": asset_class(e["code"]), "data": False, "time": e["t_first"]}
        if e["f"].get("asset") is None:
            e["f"]["asset"] = asset_class(e["code"])
        e["play"], e["subs"] = classify_play(e["f"])
    for e in mt.sells:
        s = symbol_of(e["code"])
        e["f"] = event_features(M, s, e["row"], e["vwap"], e["t_first"], e["name"]) if e["row"] is not None else {"data": False}
        e["kind"] = classify_sell(e["pnl"], e["hold_days"], e["same_day"], e["f"].get("pos_in_day"), e["f"].get("buy_pct"))
    buys_all = mt.buys
    nb = [e for e in buys_all if e["new_open"]]
    R["window"] = (min(e["date"] for e in buys_all), max(e["date"] for e in buys_all))
    R["n_buy_events"], R["n_new_open"], R["n_sell_events"] = len(buys_all), len(nb), len(mt.sells)
    R["n_legs"] = len(mt.legs)
    R["asset_mix"] = dist([e["f"]["asset"] for e in nb])
    R["play_new"] = dist([e["play"] for e in nb], PLAY_ORDER)
    R["play_all"] = dist([e["play"] for e in buys_all], PLAY_ORDER)
    R["play_new_n"] = Counter(e["play"] for e in nb)
    R["subs_new"] = Counter(s for e in nb for s in e["subs"])
    R["play_since_1008"] = dist([e["play"] for e in nb if e["date"] >= "2026-10-08"], PLAY_ORDER)
    R["play_since_1008_n"] = sum(1 for e in nb if e["date"] >= "2026-10-08")
    R["data_ok_new"] = sum(1 for e in nb if e["f"].get("data")) / max(1, len(nb))

    # --- 选股指纹: 导师新开仓(买入前一日状态) vs 同日全市场候选 ---
    U = universe(M, R["asset_mix"])
    held = mt.held_matrix()
    revisit = mt.revisit_matrix()
    cats = mentor_cats(M, revisit)
    tr_all = targets_of(mt, M, U)
    R["n_targets"] = len(tr_all)
    sel = {}
    if tr_all:
        rows_all = np.array(sorted({r - 1 for r, _, _ in tr_all}))
        cand_all = U[rows_all] & ~held[rows_all]
        pos = {r: i for i, r in enumerate(rows_all)}
        for k, X in cats.items():
            B = len(CAT_LABELS[k])
            xb = X[rows_all][cand_all]
            bg = np.bincount(xb.astype(np.int64), minlength=B + 1)[1:B + 1].astype(float)
            tv = np.array([X[r - 1, j] for r, j, _ in tr_all])
            tc = np.bincount(tv.astype(np.int64), minlength=B + 1)[1:B + 1].astype(float)
            na = float((tv == 0).mean())
            if tc.sum() == 0 or bg.sum() == 0:
                continue
            sel[k] = {"mentor": (tc / tc.sum()).tolist(), "base": (bg / bg.sum()).tolist(), "n": int(tc.sum()), "na": na}
        del pos
    R["sel"] = sel
    # 连续特征分位(新开仓, 买入前一日)
    F = [e["f"] for e in nb if e["f"].get("data")]
    R["quant"] = {
        "流通市值(亿)": qs([x.get("fmcap_prev_e8") for x in F]), "股价": qs([x.get("close_prev") for x in F]),
        "昨成交额(亿)": qs([x.get("amt_prev_e8") for x in F]), "昨换手%": qs([x.get("turn_prev") for x in F]),
        "昨涨跌%": qs([None if x.get("pct_prev") is None else x["pct_prev"] * 100 for x in F]),
        "5日涨幅%": qs([None if x.get("ret5_prev") is None else x["ret5_prev"] * 100 for x in F]),
        "20日涨幅%": qs([None if x.get("ret20_prev") is None else x["ret20_prev"] * 100 for x in F]),
        "距MA20%": qs([None if x.get("ma20r_prev") is None else x["ma20r_prev"] * 100 for x in F]),
        "20日位置": qs([x.get("pos20_prev") for x in F]),
    }
    if tr_all:
        rows_all = np.array(sorted({r - 1 for r, _, _ in tr_all}))
        cand_all = U[rows_all] & ~held[rows_all]
        R["quant_base"] = {
            "流通市值(亿)": float(np.nanmedian(np.where(cand_all, M.fmcap[rows_all] / 1e8, np.nan))),
            "股价": float(np.nanmedian(np.where(cand_all, M.C[rows_all], np.nan))),
            "昨成交额(亿)": float(np.nanmedian(np.where(cand_all, M.amt[rows_all] / 1e8, np.nan))),
            "昨换手%": float(np.nanmedian(np.where(cand_all, M.turn[rows_all], np.nan))),
            "昨涨跌%": float(np.nanmedian(np.where(cand_all, M.pct[rows_all] * 100, np.nan))),
            "5日涨幅%": float(np.nanmedian(np.where(cand_all, M.ret[5][rows_all] * 100, np.nan))),
            "20日涨幅%": float(np.nanmedian(np.where(cand_all, M.ret[20][rows_all] * 100, np.nan))),
        }
    # 当日(买入当天收盘后才知道的)题材/梯队
    Fd = [e for e in nb if e["f"].get("data")]
    R["day_ctx"] = {
        "当日热点题材(top3)": share([e["f"].get("hot_day") for e in Fd], lambda v: v == 1),
        "昨日热点题材(top3)": share([e["f"].get("hot_prev") for e in Fd], lambda v: v == 1),
        "当日在涨停梯队板块(≥3 板)": share([(1 if set(e["f"].get("themes") or []) & M.ladder[e["row"]] else 0) if M.md_ok[e["row"]] else None for e in Fd], lambda v: v == 1),
        "当日上龙虎榜": share([e["f"].get("lhb_day") for e in Fd], bool),
        "昨日上龙虎榜": share([e["f"].get("lhb_prev") for e in Fd], bool),
        "当日收涨停": share([e["f"].get("zt_day") for e in Fd], bool),
        "回头票(近60日交易过)": share([e["revisit"] for e in nb], bool),
    }
    # --- 买点指纹 ---
    R["buy_time"] = dist([time_bucket(e["t_first"]) or "无时刻" for e in nb], ["竞价", "开盘5分钟", "早盘", "盘中", "尾盘", "无时刻"])
    R["buy_time_all"] = dist([time_bucket(e["t_first"]) or "无时刻" for e in buys_all], ["竞价", "开盘5分钟", "早盘", "盘中", "尾盘", "无时刻"])
    R["buy_q"] = {
        "买价相对昨收%": qs([None if e["f"].get("buy_pct") is None else e["f"]["buy_pct"] * 100 for e in Fd]),
        "买价在当日区间位置": qs([e["f"].get("pos_in_day") for e in Fd]),
        "买价相对开盘%": qs([None if e["f"].get("vs_open") is None else e["f"]["vs_open"] * 100 for e in Fd]),
        "当日收盘相对买价%": qs([None if e["f"].get("r_close") is None else e["f"]["r_close"] * 100 for e in Fd]),
        "次日收盘相对买价%": qs([None if e["f"].get("r_next") is None else e["f"]["r_next"] * 100 for e in Fd]),
    }
    R["buy_exec"] = {
        "在涨停价成交(打板)": share([e["f"].get("at_limit") for e in Fd], bool),
        "买价≥+5%未板(追涨)": share([e["f"].get("buy_pct") for e in Fd if not e["f"].get("at_limit")], lambda v: v >= 0.05),
        "买价≤昨收(绿盘买)": share([e["f"].get("buy_pct") for e in Fd], lambda v: v <= 0),
        "区间下30%(低吸, 日线口径)": share([e["f"].get("pos_in_day") for e in Fd], lambda v: v <= 0.3),
        "区间上30%": share([e["f"].get("pos_in_day") for e in Fd], lambda v: v >= 0.7),
        "当日放量(量比≥2)": share([e["f"].get("volr_day") for e in Fd], lambda v: v >= 2),
    }
    # --- 卖出指纹 ---
    S = mt.sells
    R["sell_kind"] = dist([e["kind"] for e in S], SELL_ORDER)
    R["sell_n"] = len(S)
    Sx = [e for e in S if not e["same_day"] and e["pnl"] is not None]
    R["sell_q"] = {
        "盈亏%(非日内)": qs([e["pnl"] * 100 for e in Sx]),
        "持有交易日(非日内)": qs([e["hold_days"] for e in Sx if e["hold_days"] is not None]),
        "卖价在当日区间位置": qs([e["f"].get("pos_in_day") for e in S if e["f"].get("data")]),
        "卖出时相对昨收%": qs([None if e["f"].get("buy_pct") is None else e["f"]["buy_pct"] * 100 for e in S if e["f"].get("data")]),
        "卖后次日收盘相对卖价%": qs([None if e["f"].get("r_next") is None else e["f"]["r_next"] * 100 for e in S if e["f"].get("data")]),
    }
    R["sell_hold_dist"] = dist(["日内" if e["same_day"] else ("1日" if e["hold_days"] == 1 else "2-4日" if e["hold_days"] is not None and e["hold_days"] <= 4 else
                                 "5-20日" if e["hold_days"] is not None and e["hold_days"] <= 20 else ">20日" if e["hold_days"] is not None else "未知") for e in S],
                               ["日内", "1日", "2-4日", "5-20日", ">20日", "未知"])
    R["sell_time"] = dist([time_bucket(e["t_first"]) or "无时刻" for e in S], ["竞价", "开盘5分钟", "早盘", "盘中", "尾盘", "无时刻"])
    R["sell_ctx"] = {
        "卖出日该股涨停": share([e["f"].get("zt_day") for e in S if e["f"].get("data")], bool),
        "在涨停价卖": share([e["f"].get("at_limit") for e in S if e["f"].get("data")], bool),
        "卖出日该股收跌": share([e["f"].get("close_pct") for e in S if e["f"].get("data")], lambda v: v < 0),
        "卖出日大盘收跌": share([e["f"].get("idx_pct_day") for e in S if e["f"].get("data")], lambda v: v < 0),
        "卖出日收跌停": share([e["f"].get("dt_day") for e in S if e["f"].get("data")], bool),
    }
    # --- 市况-仓位 ---
    R["regime"] = regime_stats(mt, M)
    # --- 盘中节奏 ---
    R["intraday"] = intraday_seq(mt, M)
    # --- 规则 + 时间外验证 ---
    R["valid"] = validate(mt, M, U, held, cats, tr_all)
    R["elapsed"] = round(time.time() - t0, 1)
    mt.U, mt.heldM, mt.cats, mt.tr_all = U, held, cats, tr_all
    return R, mt


def regime_stats(mt, M):
    rows = []
    days_with_buy = {e["date"] for e in mt.buys}
    days_with_new = {e["date"] for e in mt.buys if e["new_open"]}
    days_with_act = set(mt.byday)
    for day in mt.nav_days:
        i = M.didx.get(day)
        if i is None or i < 1:
            continue
        lst = (mt.day_pos.get(day) or {}).get("list")
        if lst is None:
            continue
        hs = [x for x in lst if not re.match(r"^(204|1318|131)", x.get("code", "")) and float(x.get("position_percent") or 0) > 0]
        rows.append({"day": day, "pos": sum(float(x["position_percent"]) for x in hs), "nh": len(hs),
                     "act": day in days_with_act, "buy": day in days_with_buy, "new": day in days_with_new,
                     "idx": M.idx_pct[i], "idx_prev": M.idx_pct[i - 1], "zt_prev": M.zt_n[i - 1], "ret5_prev": M.idx_ret5[i - 1],
                     "up_prev": M.up_n[i - 1] / max(1, M.up_n[i - 1] + M.down_n[i - 1]), "dt_prev": M.dt_n[i - 1]})
    if not rows:
        return None

    def group(keyf, labels):
        g = defaultdict(list)
        for r in rows:
            k = keyf(r)
            if k is not None:
                g[k].append(r)
        out = []
        for lab in labels:
            xs = g.get(lab, [])
            if not xs:
                continue
            out.append({"bucket": lab, "n": len(xs), "pos": float(np.mean([x["pos"] for x in xs])),
                        "nh": float(np.mean([x["nh"] for x in xs])), "act": float(np.mean([x["act"] for x in xs])),
                        "new": float(np.mean([x["new"] for x in xs]))})
        return out

    def b_idx(v):
        if v is None or not np.isfinite(v):
            return None
        return "≤-1%" if v <= -0.01 else "-1~0%" if v < 0 else "0~1%" if v < 0.01 else "≥1%"

    def b_zt(v):
        return "<40" if v < 40 else "40-80" if v < 80 else "80-120" if v < 120 else "≥120"

    def b_r5(v):
        if v is None or not np.isfinite(v):
            return None
        return "≤-3%" if v <= -0.03 else "-3~0%" if v < 0 else "0~3%" if v < 0.03 else "≥3%"

    def b_up(v):
        return "<30%" if v < 0.3 else "30-50%" if v < 0.5 else "50-70%" if v < 0.7 else "≥70%"
    return {
        "n_days": len(rows),
        "pos_mean": float(np.mean([r["pos"] for r in rows])), "act_rate": float(np.mean([r["act"] for r in rows])),
        "new_rate": float(np.mean([r["new"] for r in rows])), "nh_mean": float(np.mean([r["nh"] for r in rows])),
        "当日大盘(收盘仓位)": group(lambda r: b_idx(r["idx"]), ["≤-1%", "-1~0%", "0~1%", "≥1%"]),
        "昨日大盘": group(lambda r: b_idx(r["idx_prev"]), ["≤-1%", "-1~0%", "0~1%", "≥1%"]),
        "昨日涨停家数": group(lambda r: b_zt(r["zt_prev"]), ["<40", "40-80", "80-120", "≥120"]),
        "昨日上涨占比": group(lambda r: b_up(r["up_prev"]), ["<30%", "30-50%", "50-70%", "≥70%"]),
        "前5日指数涨跌": group(lambda r: b_r5(r["ret5_prev"]), ["≤-3%", "-3~0%", "0~3%", "≥3%"]),
    }


HYP_DEF = {
    "同日多票": {
        "换方向": "首只 2 个交易日内亏损卖出(×3) / 首只当日收盘低于买价(×1.5) / 后买票与首只题材不同(×1.5, 相同×0.4) / 两笔间隔≤10 分钟(×0.5) / 首只持有≥3 日(×0.5)",
        "两边押": "两只都持有到次日收盘(×2.5) / 金额比 0.5~2(×1.5) / 题材不同(×1.5) / 间隔≤10 分钟(×0.6)",
        "计划内多只": "间隔≤10 分钟(×3, >60 分钟×0.5) / 金额比 0.67~1.5(×1.5) / 两笔都在 09:35 前(×1.3)",
        "追联动加仓": "同题材且后买票在涨停价/当日热点(×3) / 仅同题材(×2) / 后买票涨停价或热点且首只当日收盘高于买价(×1.5) / 题材不同(×0.3)",
        "其他/证据不足": "基础分 1; 题材未知(×1.5) / 缺行情(×1.5)",
    },
    "换股": {
        "止损换股": "卖出票亏损(×3) / 题材不同(×1.3)",
        "止盈轮动": "卖出票盈利(×2.5) / 新买票在涨停价或当日热点(×1.5)",
        "同题材换股": "两票同题材(×3, 不同×0.3)",
        "计划内调仓": "卖后 5 分钟内买(×2) / 卖在 09:35 前(×1.3)",
        "其他/证据不足": "基础分 1; 题材未知(×1.5) / 卖出成本未知(×1.5)",
    },
    "同票加仓": {
        "右侧确认加仓": "加仓价≥首笔+0.5%(×2.5) / 加仓在涨停价或当日收涨停(×1.5)",
        "左侧摊低": "加仓价≤首笔-0.5%(×2.5)",
        "拆单分批执行": "间隔≤15 分钟(×2) / 价差<0.5%(×2)",
        "其他/证据不足": "基础分 1",
    },
    "同票先买后卖": {
        "有底仓做T": "买前已有持仓(×3)",
        "试错止损": "买前无持仓且卖价<买价(×2.5)",
        "日内冲高兑现": "卖价≥买价+1%(×2.5)",
        "其他/证据不足": "基础分 1",
    },
}


def hyp_norm(sc):
    tot = sum(sc.values())
    return {k: round(v / tot, 3) for k, v in sc.items()}


def intraday_seq(mt, M):
    """盘中节奏(成交腿秒级时刻还原顺序; 当日有 00:00:00 手录腿的日子剔除) + 逐事件互斥假设分布(合计 100%, 含其他/证据不足)"""
    st = Counter()
    first_ratio_day, first_ratio_asset, buy_codes_n = [], [], []
    later_rel = Counter(); later_lim = later_hot = later_n = 0
    first_lim = first_hot = first_n = 0
    probe_days = probe_cut = 0
    bt_sell_gap, swap_gap = [], []
    add_same = 0
    events = []
    asset_days = sorted(mt.asset_by_day)
    held_days = sorted(mt.held_close)
    sell_ev = defaultdict(list)                       # code → [(row, pnl, t_first, date)]
    for e in mt.sells:
        if e["row"] is not None:
            sell_ev[e["code"]].append((e["row"], e["pnl"], e["t_first"], e["date"]))
    sell_by = {(e["date"], e["code"]): e for e in mt.sells}
    prevq_by = {(e["date"], e["code"]): e["held_qty_prev"] for e in mt.buys}

    def held_on(day, code):
        k = bisect.bisect_right(held_days, day) - 1
        return k >= 0 and code in mt.held_close[held_days[k]]

    def tsec(t):
        return sec_of(t["trans_date"][11:19])

    for day, legs in sorted(mt.byday.items()):
        if any(t["trans_date"][11:19] == "00:00:00" for t in legs):
            st["skip_notime"] += 1
            continue
        d = M.didx.get(day)
        legs = sorted(legs, key=lambda t: t["trans_date"])
        buys = [t for t in legs if t["op"] == "1"]
        sells = [t for t in legs if t["op"] != "1"]

        def ctx(code, ts):
            s = symbol_of(code)
            j = M.sidx.get(s) if s else None
            if d is None or j is None or not M.has[d, j]:
                return None
            px = next((t["_p"] for t in buys if t["stock_code"] == code and tsec(t) >= ts), None)
            if px is None:
                px = next(t["_p"] for t in buys if t["stock_code"] == code)
            lu = M.lu[d, j]
            return {"lim": bool(np.isfinite(lu) and px >= lu - 0.005), "hot": (M.hot[d, j] == 2) if M.md_ok[d] else None,
                    "th": M.themes_of(s, d), "sym": s, "j": j, "px": px, "r_close": float(M.C[d, j] / px - 1) if px else 0.0,
                    "zt_day": bool(M.zt[d, j])}

        def theme_rel(a, b):
            if a and b and a["th"] and b["th"]:
                return "同" if a["th"] & b["th"] else "异"
            return None
        # ③ 同票先买后卖
        for code in dict.fromkeys(t["stock_code"] for t in buys):
            b0 = next(t for t in buys if t["stock_code"] == code)
            ss = [t for t in sells if t["stock_code"] == code and tsec(t) > tsec(b0)]
            if not ss:
                continue
            st["buy_then_sell"] += 1
            gap = (tsec(ss[0]) - tsec(b0)) / 60
            bt_sell_gap.append(gap)
            prev_q = prevq_by.get((day, code), 0)
            sc = {"有底仓做T": 1.0, "试错止损": 1.0, "日内冲高兑现": 1.0, "其他/证据不足": 1.0}
            ev = {"买前持仓": prev_q > 0, "卖/买价": round(ss[0]["_p"] / b0["_p"], 4) if b0["_p"] else None, "间隔分钟": round(gap, 1)}
            if prev_q > 0:
                sc["有底仓做T"] *= 3
            elif ss[0]["_p"] < b0["_p"]:
                sc["试错止损"] *= 2.5
            if ss[0]["_p"] >= b0["_p"] * 1.01:
                sc["日内冲高兑现"] *= 2.5
            events.append({"type": "同票先买后卖", "date": day, "time": b0["trans_date"][11:19], "codes": [code], "names": [b0.get("stock_name")],
                           "evidence": ev, "hyp": hyp_norm(sc)})
        # 换股: 先卖 A 后买新票 B(B 当日此前未买)
        for s_ in sells:
            ts = tsec(s_)
            later_new = [t for t in buys if tsec(t) > ts and t["stock_code"] != s_["stock_code"]
                         and not any(x["stock_code"] == t["stock_code"] and tsec(x) <= ts for x in buys)]
            if not later_new:
                continue
            b = later_new[0]
            st["swap"] += 1
            gap = (tsec(b) - ts) / 60
            swap_gap.append(gap)
            se = sell_by.get((day, s_["stock_code"]))
            pnl = se["pnl"] if se else None
            sA = symbol_of(s_["stock_code"])
            thA = M.themes_of(sA, d) if (sA and d is not None) else set()
            cb = ctx(b["stock_code"], tsec(b))
            rel = ("同" if thA & cb["th"] else "异") if (cb and thA and cb["th"]) else None
            sc = {"止损换股": 1.0, "止盈轮动": 1.0, "同题材换股": 1.0, "计划内调仓": 1.0, "其他/证据不足": 1.0}
            if pnl is not None:
                if pnl < 0:
                    sc["止损换股"] *= 3
                else:
                    sc["止盈轮动"] *= 2.5
            else:
                sc["其他/证据不足"] *= 1.5
            if rel == "同":
                sc["同题材换股"] *= 3
            elif rel == "异":
                sc["同题材换股"] *= 0.3
                sc["止损换股"] *= 1.3
            else:
                sc["其他/证据不足"] *= 1.5
            if cb and (cb["lim"] or cb["hot"]):
                sc["止盈轮动"] *= 1.5
            if gap <= 5:
                sc["计划内调仓"] *= 2
            if s_["trans_date"][11:19] < "09:35:00":
                sc["计划内调仓"] *= 1.3
            events.append({"type": "换股", "date": day, "time": s_["trans_date"][11:19], "codes": [s_["stock_code"], b["stock_code"]],
                           "names": [s_.get("stock_name"), b.get("stock_name")],
                           "evidence": {"卖出盈亏": _f(pnl), "题材": rel or "未知", "新票涨停价/热点": bool(cb and (cb["lim"] or cb["hot"])), "间隔分钟": round(gap, 1)},
                           "hyp": hyp_norm(sc)})
            break
        if not buys:
            continue
        st["buy_days"] += 1
        order = list(dict.fromkeys(t["stock_code"] for t in buys))
        buy_codes_n.append(len(order))
        c0 = order[0]
        b0 = next(t for t in buys if t["stock_code"] == c0)
        t0 = tsec(b0)
        unit = sum(t["_q"] * t["_p"] for t in buys if t["stock_code"] == c0 and tsec(t) <= t0 + 300)
        total = sum(t["_q"] * t["_p"] for t in buys)
        if total > 0:
            first_ratio_day.append(unit / total)
        k = bisect.bisect_left(asset_days, day) - 1
        fa = None
        if k >= 0 and mt.asset_by_day[asset_days[k]] > 0:
            fa = unit / mt.asset_by_day[asset_days[k]]
            first_ratio_asset.append(fa)
        c0x = ctx(c0, t0)
        adds = [t for t in buys if t["stock_code"] == c0 and tsec(t) > t0 + 300]
        if adds:
            add_same += 1
            a = adds[0]
            gap = (tsec(a) - t0) / 60
            pr = a["_p"] / b0["_p"] - 1 if b0["_p"] else 0.0
            sc = {"右侧确认加仓": 1.0, "左侧摊低": 1.0, "拆单分批执行": 1.0, "其他/证据不足": 1.0}
            if pr >= 0.005:
                sc["右侧确认加仓"] *= 2.5
            if pr <= -0.005:
                sc["左侧摊低"] *= 2.5
            if c0x and (c0x["zt_day"] or (np.isfinite(M.lu[d, c0x["j"]]) and a["_p"] >= M.lu[d, c0x["j"]] - 0.005)):
                sc["右侧确认加仓"] *= 1.5
            if gap <= 15:
                sc["拆单分批执行"] *= 2
            if abs(pr) < 0.005:
                sc["拆单分批执行"] *= 2
            events.append({"type": "同票加仓", "date": day, "time": a["trans_date"][11:19], "codes": [c0], "names": [b0.get("stock_name")],
                           "evidence": {"加仓价/首笔-1": round(pr, 4), "间隔分钟": round(gap, 1)}, "hyp": hyp_norm(sc)})
        if c0x:
            first_n += 1; first_lim += c0x["lim"]; first_hot += bool(c0x["hot"])
        if len(order) < 2:
            continue
        st["multi_days"] += 1
        if total > 0 and unit / total <= 1 / 3 and (fa is None or fa <= 0.25):
            probe_days += 1
            if any(t["stock_code"] == c0 and tsec(t) > t0 for t in sells):
                probe_cut += 1
        amtA = sum(t["_q"] * t["_p"] for t in buys if t["stock_code"] == c0)
        nxt_day = M.dates[d + 1] if (d is not None and d + 1 < len(M.dates)) else None
        for c in order[1:]:
            bc = next(t for t in buys if t["stock_code"] == c)
            tc = tsec(bc)
            cx = ctx(c, tc)
            rel = theme_rel(c0x, cx)
            if not cx:
                later_rel["无行情"] += 1
            else:
                later_n += 1; later_lim += cx["lim"]; later_hot += bool(cx["hot"])
                later_rel["同题材(联动)" if rel == "同" else "不同题材(换方向)" if rel == "异" else "题材未知"] += 1
            gap = (tc - t0) / 60
            amtB = sum(t["_q"] * t["_p"] for t in buys if t["stock_code"] == c)
            ratio = amtB / amtA if amtA > 0 else None
            a_cut = None
            if d is not None:
                xs = [x for x in sell_ev.get(c0, []) if (x[0] == d and x[2] > bc["trans_date"][11:19]) or d < x[0] <= d + 2]
                a_cut = any(x[1] is not None and x[1] < 0 for x in xs) if xs else False
            a_weak = (c0x["r_close"] < 0) if c0x else None
            both_held = (held_on(nxt_day, c0) and held_on(nxt_day, c)) if nxt_day else None
            a_long = bool(d is not None and d + 3 < len(M.dates) and held_on(M.dates[d + 3], c0))
            sc = {"换方向": 1.0, "两边押": 1.0, "计划内多只": 1.0, "追联动加仓": 1.0, "其他/证据不足": 1.0}
            if a_cut:
                sc["换方向"] *= 3
            if a_weak:
                sc["换方向"] *= 1.5
            if rel == "异":
                sc["换方向"] *= 1.5
                sc["两边押"] *= 1.5
                sc["追联动加仓"] *= 0.3
            elif rel == "同":
                sc["换方向"] *= 0.4
                sc["追联动加仓"] *= 3 if (cx and (cx["lim"] or cx["hot"])) else 2
            else:
                sc["其他/证据不足"] *= 1.5
            if cx and (cx["lim"] or cx["hot"]) and c0x and c0x["r_close"] > 0:
                sc["追联动加仓"] *= 1.5
            if gap <= 10:
                sc["换方向"] *= 0.5
                sc["两边押"] *= 0.6
                sc["计划内多只"] *= 3
            elif gap > 60:
                sc["计划内多只"] *= 0.5
            if a_long:
                sc["换方向"] *= 0.5
            if both_held:
                sc["两边押"] *= 2.5
            if ratio is not None and 0.5 <= ratio <= 2:
                sc["两边押"] *= 1.5
            if ratio is not None and 0.67 <= ratio <= 1.5:
                sc["计划内多只"] *= 1.5
            if b0["trans_date"][11:19] < "09:35:00" and bc["trans_date"][11:19] < "09:35:00":
                sc["计划内多只"] *= 1.3
            if not c0x or not cx:
                sc["其他/证据不足"] *= 1.5
            events.append({"type": "同日多票", "date": day, "time": bc["trans_date"][11:19], "codes": [c0, c],
                           "names": [b0.get("stock_name"), bc.get("stock_name")],
                           "evidence": {"间隔分钟": round(gap, 1), "金额比(后/首)": _f(ratio, 2), "题材": {"同": "同", "异": "异"}.get(rel, "未知"),
                                        "首只2日内亏损卖": a_cut, "首只当日收盘低于买价": a_weak, "两只都持有到次日": both_held,
                                        "后买票涨停价/热点": bool(cx and (cx["lim"] or cx["hot"])), "首只持有≥3日": a_long},
                           "hyp": hyp_norm(sc)})
    bd = max(1, st["buy_days"])
    hyp_sum = {}
    for typ in HYP_DEF:
        xs = [e["hyp"] for e in events if e["type"] == typ]
        if xs:
            hyp_sum[typ] = {"n": len(xs), "mean": {k: float(np.mean([x[k] for x in xs])) for k in HYP_DEF[typ]}}
    mt.intraday_events = events
    return {
        "buy_days": st["buy_days"], "skip_notime": st["skip_notime"],
        "first_ratio_day_q": qs(first_ratio_day), "first_ratio_asset_q": qs(first_ratio_asset),
        "first_ratio_asset_small": share(first_ratio_asset, lambda v: v <= 0.2),
        "multi_rate": st["multi_days"] / bd, "codes_per_day_q": qs(buy_codes_n),
        "probe_rate": probe_days / bd, "probe_days": probe_days, "probe_cut_rate": probe_cut / max(1, probe_days),
        "add_same_rate": add_same / bd,
        "later_rel": dict(later_rel),
        "first_lim": first_lim / max(1, first_n), "first_hot": first_hot / max(1, first_n), "first_n": first_n,
        "later_lim": later_lim / max(1, later_n) if later_n else None, "later_hot": later_hot / max(1, later_n) if later_n else None, "later_n": later_n,
        "buy_then_sell": st["buy_then_sell"], "buy_then_sell_gap_q": qs(bt_sell_gap),
        "swap_days": st["swap"], "swap_rate": st["swap"] / max(1, len(mt.byday)), "swap_gap_q": qs(swap_gap),
        "hyp_sum": hyp_sum,
    }


def validate(mt, M, U, held, cats, tr_all):
    out = {"n_targets": len(tr_all)}
    days = sorted({r for r, _, _ in tr_all})
    if len(tr_all) < 20 or len(days) < 8:
        out["note"] = f"新开仓可评估样本不足(n={len(tr_all)}, 买入日 {len(days)}), 不做规则挖掘/验证"
        return out
    cut = days[int(len(days) * TRAIN_FRAC)]
    tr = [(r - 1, j) for r, j, _ in tr_all if r < cut]
    te = [(r - 1, j) for r, j, _ in tr_all if r >= cut]
    out["cut_date"] = M.dates[cut]
    out["n_train"], out["n_test"] = len(tr), len(te)
    rows_tr = np.array(sorted({r for r, _ in tr}))
    rows_te = np.array(sorted({r for r, _ in te}))
    cand_tr = U[rows_tr] & ~held[rows_tr]
    cand_te = U[rows_te] & ~held[rows_te]
    rules = mine_rules(cats, rows_tr, cand_tr, tr)
    for ru in rules:
        ru["test"] = rule_eval(cats, ru, rows_te, cand_te, te)
    out["rules"] = rules
    # 规则并集覆盖(训练/测试)
    def union_cov(rows, cand, tg):
        if not len(rows) or not tg:
            return None, None
        pos = {r: i for i, r in enumerate(rows)}
        ri = np.array([pos[r] for r, _ in tg]); jj = np.array([j for _, j in tg])
        m = np.zeros_like(cand)
        for ru in rules:
            mm = cand.copy()
            for k, vals in ru["atoms"]:
                mm &= np.isin(cats[k][rows], vals)
            m |= mm
        return float(m[ri, jj].mean()), float(m.sum() / len(rows))
    out["union_train"] = union_cov(rows_tr, cand_tr, tr)
    out["union_test"] = union_cov(rows_te, cand_te, te)
    model = nb_fit(cats, rows_tr, cand_tr, tr)
    def cand_fn(r):
        return U[r] & ~held[r]
    out["pool"] = pool_eval(M, cats, model, te, cand_fn)
    model_nr = {k: v for k, v in model.items() if k != "回头票"}
    out["pool_no_revisit"] = pool_eval(M, cats, model_nr, te, cand_fn)
    out["nb_top"] = top_lifts(model)
    return out


def top_lifts(model, k=8):
    xs = []
    for f, lr in model.items():
        for b in range(1, len(lr)):
            xs.append((float(lr[b]), f, CAT_LABELS[f][b - 1]))
    xs.sort(reverse=True)
    return [(f, lab, round(math.exp(v), 2)) for v, f, lab in xs[:k]]


# ====================================================================================
# 八、模拟自选股池(盘前: 用 D 之前数据)
# ====================================================================================
def build_pool(ledger, M, day, N=POOL_N[0]):
    mt = Mentor(ledger, M, asof=day)
    for e in mt.buys:
        e["f"] = {"asset": asset_class(e["code"])}
    nbx = [e for e in mt.buys if e["new_open"]]
    mix = dist([asset_class(e["code"]) for e in nbx])
    U = universe(M, mix)
    held = mt.held_matrix()
    revisit = mt.revisit_matrix()
    cats = mentor_cats(M, revisit)
    tr_all = targets_of(mt, M, U)
    r = M.row_before(day)
    res = {"name": mt.name, "n_train": len(tr_all), "feature_day": M.dates[r] if r is not None else None}
    if len(tr_all) < 20 or r is None:
        res["note"] = "样本不足, 不出池"
        return res
    tr = [(x - 1, j) for x, j, _ in tr_all]
    rows = np.array(sorted({x for x, _ in tr}))
    model = nb_fit(cats, rows, U[rows] & ~held[rows], tr)
    cand = U[r] & ~held[r]
    idx = np.where(cand)[0]
    sc = nb_score_row(cats, model, r)[idx]
    top = idx[np.argsort(-sc, kind="stable")[:N]]
    pool = []
    for j in top:
        contrib = sorted(((float(model[k][cats[k][r, j]]), k, CAT_LABELS[k][cats[k][r, j] - 1] if cats[k][r, j] else "缺失") for k in model), reverse=True)[:3]
        pool.append({"code": M.syms[j][2:], "symbol": M.syms[j], "name": M.name.get(M.syms[j]), "score": round(float(np.nanmax([sc[np.where(idx == j)[0][0]]])), 3),
                     "why": [f"{k}={lab}(×{math.exp(v):.1f})" for v, k, lab in contrib],
                     "pct_prev": _f(M.pct[r, j]), "zt_prev": bool(M.zt[r, j]), "themes": sorted(M.themes_of(M.syms[j], r))[:4]})
    res["pool"] = pool
    res["cand_n"] = int(len(idx))
    return res


# ====================================================================================
# 九、paper 链成交打法分布(只读 books)
# ====================================================================================
def paper_dist(M, chain, since="2026-10-08"):
    p = BOOKS / f"A-{chain}.json"
    if not p.exists():
        return None
    b = json.loads(p.read_text(encoding="utf-8"))
    otime = {o["id"]: o.get("time") for o in b.get("orders", [])}
    pos = defaultdict(float)
    labs, labs_new, rows = [], [], []
    for t in b.get("trades", []):
        day = t["id"][:10]
        code = str(t.get("code"))
        if t.get("side") == "BUY":
            if day >= since:
                s = symbol_of(code)
                f = event_features(M, s, M.didx.get(day), t.get("price"), None, None)
                if f.get("asset") is None:
                    f["asset"] = asset_class(code)
                pl, subs = classify_play(f)
                labs.append(pl)
                if pos[code] <= 0:
                    labs_new.append(pl)
                rows.append({"date": day, "code": code, "price": t.get("price"), "play": pl, "subs": subs, "new_open": pos[code] <= 0,
                             "order_time": otime.get(t["id"])})
            pos[code] += float(t.get("qty") or 0)
        else:
            pos[code] -= float(t.get("qty") or 0)
    return {"chain": chain, "n": len(labs), "n_new": len(labs_new), "dist": dist(labs, PLAY_ORDER), "dist_new": dist(labs_new, PLAY_ORDER), "rows": rows}


# ====================================================================================
# 十、输出: fingerprint.md / cases_auto.jsonl / 研究报告
# ====================================================================================
def q_s(q, nd=1, unit=""):
    return "—" if not q else f"{q[1]:.{nd}f}{unit}(P25-P75 {q[0]:.{nd}f}~{q[2]:.{nd}f})"


def dist_line(dd, nmap=None, k=None):
    items = [(a, b) for a, b in dd.items() if b > 0]
    items.sort(key=lambda x: -x[1])
    if k:
        items = items[:k]
    return " / ".join(f"{a} {b * 100:.0f}%" + (f"({nmap[a]})" if nmap and a in nmap else "") for a, b in items)


def one_liner(R):
    if R.get("empty"):
        return "无买入记录"
    pn = R["play_new"]
    top = sorted(((k, v) for k, v in pn.items()), key=lambda x: -x[1])[:3]
    s = "打法以" + "/".join(f"{k}{v * 100:.0f}%" for k, v in top)
    q = R["quant"].get("流通市值(亿)")
    if q:
        s += f"; 流通市值中位 {q[1]:.0f} 亿"
    hot = R["day_ctx"]["当日热点题材(top3)"][0]
    if hot is not None:
        s += f"; 当日热点题材内 {hot * 100:.0f}%"
    rv = R["day_ctx"]["回头票(近60日交易过)"][0]
    if rv is not None:
        s += f"; 回头票 {rv * 100:.0f}%"
    return s


def clarity(R):
    v = R.get("valid") or {}
    p = (v.get("pool") or {}).get(POOL_N[1])
    if not p:
        return "无法评估(样本不足)", None
    best_base = max(p["rand"], p["gain"], p["amt"], p["zt"])
    ratio = p["hit"] / best_base if best_base > 0 else None
    if p["targets"] < 15:
        tag = "样本太少(测试<15笔)"
    elif p["hit"] >= 0.25:
        tag = "清晰·个性化" if ratio and ratio >= 1.5 else "清晰·≈通用热门清单"
    elif p["hit"] >= 0.12:
        tag = "中等" if ratio and ratio >= 1.3 else "中等·≈通用热门清单"
    else:
        tag = "不清晰"
    return tag, ratio


def write_fingerprint(R, M, out_md):
    L = []
    w = R.get("window") or ("—", "—")
    L.append(f"# {R['name']}({R['ledger']}) 交易指纹·机械层")
    L.append("")
    L.append(f"> 生成: {R['generatedAt']} | 脚本: scripts/tzzb/mentor_fingerprint.py(零 token, 只读) | as-of: {R.get('asof') or '全量'}")
    L.append(f"> 数据窗口: {w[0]} ~ {w[1]} | 成交腿 {R.get('n_legs')} | 买入事件(日×票) {R.get('n_buy_events')}, 其中新开仓 {R.get('n_new_open')} | 卖出事件 {R.get('n_sell_events')}")
    L.append(f"> 行情面板: {M.dates[0]} ~ {M.dates[-1]}(行情库 kline_day, 不复权价+交易所昨收) | 新开仓中有行情的占 {pct_s(R.get('data_ok_new'))}")
    L.append("> 缺失/降级: 历史成交额=量×OHLC 均价近似; 流通市值/换手=用 10/09 起换手率反推流通股本后套历史(股本变动未计); 北交所 10/09 前无行情;"
             " 退市/到期转债无行情; 题材=md「涨停分析」(2026-01-15 起, 只覆盖当日涨停股及大涨股的题材归属, 非完整行业/概念库); 行业/概念强弱排名缺。")
    L.append("> 口径: 「买入前」=买入日前一交易日收盘状态(盘前可知, 用于选股/出池); 「当日」=买入日收盘后才完整知道(描述性)。新开仓=买入前一日收盘不持有。")
    L.append("")
    if R.get("empty"):
        L.append("无买入记录。")
        out_md.write_text("\n".join(L) + "\n", encoding="utf-8")
        return
    # 一、打法分布
    L.append("## 一、打法分布(统一分类器, 新开仓)")
    L.append("")
    L.append("| 打法 | 新开仓占比 | 笔数 | 全部买入占比 |")
    L.append("| --- | --- | --- | --- |")
    for k in PLAY_ORDER:
        if R["play_new_n"].get(k) or R["play_all"].get(k):
            L.append(f"| {k} | {pct_s(R['play_new'].get(k))} | {R['play_new_n'].get(k, 0)} | {pct_s(R['play_all'].get(k))} |")
    L.append("")
    sn = R["subs_new"]
    nn = max(1, R["n_new_open"])
    L.append("副标签(新开仓, 可多选): " + " / ".join(f"{k} {v / nn * 100:.0f}%" for k, v in sn.most_common(12)))
    L.append("")
    if R["play_since_1008_n"]:
        L.append(f"10/08 以来新开仓(n={R['play_since_1008_n']}): {dist_line(R['play_since_1008'])}")
        L.append("")
    L.append("分类器定义见 scripts/tzzb/model_out/reports/mentor_fingerprint_20261016.md「打法分类器」; 主标签只用买入前状态+买价, 副标签里的时段/低吸依赖成交时刻与日线区间。")
    L.append("")
    # 二、选股指纹
    L.append("## 二、选股指纹(新开仓, 买入前一日状态 vs 同日全市场候选)")
    L.append("")
    L.append(f"资产结构: {dist_line({ASSET_CN.get(k, k): v for k, v in R['asset_mix'].items()})}")
    L.append("")
    L.append("| 指标 | 导师中位(P25~P75) | 全市场同日中位 |")
    L.append("| --- | --- | --- |")
    for k, q in R["quant"].items():
        b = (R.get("quant_base") or {}).get(k)
        L.append(f"| {k} | {q_s(q, 1)} | {'—' if b is None else f'{b:.1f}'} |")
    L.append("")
    L.append("分箱对照(导师占比 / 市场基线占比 → 倍数; 只列倍数≥1.5 或 ≤0.5 且导师占比≥8% 的箱):")
    L.append("")
    L.append("| 特征 | 箱 | 导师 | 基线 | 倍数 | n |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    rows_ = []
    for k, v in R["sel"].items():
        for b, (m, bs) in enumerate(zip(v["mentor"], v["base"])):
            if m >= 0.08 and bs > 0 and (m / bs >= 1.5 or m / bs <= 0.5):
                rows_.append((m / bs, k, CAT_LABELS[k][b], m, bs, v["n"]))
    rows_.sort(key=lambda x: -abs(math.log(x[0])))
    for lift, k, lab, m, bs, n in rows_[:24]:
        L.append(f"| {k} | {lab} | {m * 100:.0f}% | {bs * 100:.1f}% | ×{lift:.1f} | {n} |")
    L.append("")
    L.append("题材/热度(新开仓):")
    L.append("")
    for k, (v, n) in R["day_ctx"].items():
        L.append(f"- {k}: {pct_s(v)}(n={n})")
    L.append("")
    # 三、买点指纹
    L.append("## 三、买点指纹")
    L.append("")
    L.append(f"- 首笔成交时段(新开仓): {dist_line(R['buy_time'])}")
    L.append(f"- 首笔成交时段(全部买入): {dist_line(R['buy_time_all'])}")
    for k, q in R["buy_q"].items():
        L.append(f"- {k}: {q_s(q, 2 if '位置' in k else 1)}")
    for k, (v, n) in R["buy_exec"].items():
        L.append(f"- {k}: {pct_s(v)}(n={n})")
    L.append("")
    # 四、卖出指纹
    L.append("## 四、卖出指纹")
    L.append("")
    L.append(f"- 卖出类型(n={R['sell_n']}): {dist_line(R['sell_kind'])}")
    L.append(f"- 持有期: {dist_line(R['sell_hold_dist'])}")
    L.append(f"- 卖出时段: {dist_line(R['sell_time'])}")
    for k, q in R["sell_q"].items():
        L.append(f"- {k}: {q_s(q, 2 if '位置' in k else 1)}")
    for k, (v, n) in R["sell_ctx"].items():
        L.append(f"- {k}: {pct_s(v)}(n={n})")
    L.append("")
    L.append("卖出分类口径: " + "; ".join(f"{k}={v}" for k, v in SELL_DEF.items()))
    L.append("")
    # 五、市况-仓位
    rg = R.get("regime")
    L.append("## 五、市况-仓位行为")
    L.append("")
    if rg:
        L.append(f"覆盖 {rg['n_days']} 个净值日: 平均收盘总仓 {pct_s(rg['pos_mean'])}, 平均持股 {rg['nh_mean']:.1f} 只, 有成交日 {pct_s(rg['act_rate'])}, 有新开仓日 {pct_s(rg['new_rate'])}")
        L.append("")
        for k in ("当日大盘(收盘仓位)", "昨日大盘", "昨日涨停家数", "昨日上涨占比", "前5日指数涨跌"):
            L.append(f"**按{k}分组**")
            L.append("")
            L.append("| 分组 | 天数 | 平均总仓 | 平均持股数 | 成交率 | 新开仓率 |")
            L.append("| --- | --- | --- | --- | --- | --- |")
            for g in rg[k]:
                L.append(f"| {g['bucket']} | {g['n']} | {pct_s(g['pos'])} | {g['nh']:.1f} | {pct_s(g['act'])} | {pct_s(g['new'])} |")
            L.append("")
    else:
        L.append("无 day_positions 数据。")
        L.append("")
    # 六、盘中节奏
    it = R["intraday"]
    L.append("## 六、盘中节奏(成交腿秒级时刻还原)")
    L.append("")
    L.append(f"- 有买入的交易日 {it['buy_days']}(含 00:00:00 手录腿的 {it['skip_notime']} 天剔除)")
    L.append(f"- ① 首笔买入(首只票开仓后 5 分钟内的成交)占当日买入总额: {q_s(it['first_ratio_day_q'], 2)}; 占前一日总资产: {q_s(it['first_ratio_asset_q'], 3)}, 其中≤20% 资产的占 {pct_s(it['first_ratio_asset_small'][0])}")
    L.append(f"- ② 同日买入≥2 只的天数占比 {pct_s(it['multi_rate'])}; 每日买入只数 {q_s(it['codes_per_day_q'], 0)}; 后续买入票 vs 首笔票: {it['later_rel'] or '—'}")
    L.append(f"- 「先小仓试错」日(≥2 只且首笔≤当日买入额 1/3 且≤总资产 25%): {pct_s(it['probe_rate'])}(n={it['probe_days']}), 其中首笔当日即卖(试错即砍) {pct_s(it['probe_cut_rate'])}; 首笔票 5 分钟后同日加仓: {pct_s(it['add_same_rate'])}")
    L.append(f"- ③ 同票同日先买后卖 {it['buy_then_sell']} 次, 间隔分钟 {q_s(it['buy_then_sell_gap_q'], 0)}; 同日先卖后买新票(换股)的天数 {it['swap_days']}(占有成交日 {pct_s(it['swap_rate'])}), 间隔分钟 {q_s(it['swap_gap_q'], 0)}")
    L.append(f"- ④ 首笔票: 在涨停价买 {pct_s(it['first_lim'])} / 当日热点题材 {pct_s(it['first_hot'])}(n={it['first_n']}); 后续票: 涨停价买 {pct_s(it['later_lim'])} / 当日热点题材 {pct_s(it['later_hot'])}(n={it['later_n']})")
    v = R.get("valid") or {}
    p30 = (v.get("pool") or {}).get(POOL_N[0])
    p50 = (v.get("pool") or {}).get(POOL_N[1])
    if p30:
        L.append(f"- ⑤ 时间外样本新开仓落在自己指纹池外的比例: Top{POOL_N[0]} 池外 {pct_s(1 - p30['hit'])} / Top{POOL_N[1]} 池外 {pct_s(1 - p50['hit'])}(n={p30['targets']}) → 链里「池外自主挑票」预算参考")
    else:
        L.append("- ⑤ 池外比例: 样本不足未评估")
    L.append("")
    L.append("**「为什么」的假设分布**(逐事件按可观测后果打分并归一, 互斥穷尽合计 100%, 含「其他/证据不足」; 只是基于后果的推断, 观测不到真实动机; 逐事件明细见 cases_auto.jsonl 的 side=日内事件):")
    L.append("")
    for typ, hs in (it.get("hyp_sum") or {}).items():
        L.append(f"- {typ} {hs['n']} 次: " + " / ".join(f"{k}≈{v * 100:.0f}%" for k, v in sorted(hs["mean"].items(), key=lambda kv: -kv[1])))
    if not it.get("hyp_sum"):
        L.append("- 无可分析事件")
    L.append("")
    L.append("打分规则(基础分各 1, 命中证据乘系数, 再归一): " + " ‖ ".join(f"{typ}: " + "; ".join(f"{h}={d}" for h, d in hs.items()) for typ, hs in HYP_DEF.items()))
    L.append("")
    # 七、规则
    L.append("## 七、典型选股规则(机械可判, 买入前一日状态; 前 70% 买入日挖掘, 后 30% 验证)")
    L.append("")
    if v.get("rules"):
        L.append(f"训练截止 {v['cut_date']}(训练 {v['n_train']} 笔 / 测试 {v['n_test']} 笔新开仓)。覆盖率=导师新开仓中满足规则的比例; 日均命中=每天全市场满足规则的股数; 精确率=命中股中被导师当日买入的比例; 倍数=精确率/随机。")
        L.append("")
        L.append("| # | 规则 | 训练覆盖 | 增量覆盖 | 日均命中 | 精确率 | 倍数 | 测试覆盖 | 测试日均 | 测试倍数 |")
        L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for i, ru in enumerate(v["rules"], 1):
            t = ru.get("test") or {}
            L.append(f"| R{i} | {ru['text']} | {pct_s(ru['cov'])} | {pct_s(ru['cov_new'])} | {ru['daily']:.0f} | {ru['prec'] * 100:.2f}% | ×{ru['lift']:.1f} | "
                     f"{pct_s(t.get('cov'))} | {t.get('daily', 0):.0f} | {'—' if not t.get('lift') else f'×{t['lift']:.1f}'} |")
        ut, ue = v.get("union_train"), v.get("union_test")
        L.append("")
        L.append(f"规则并集: 训练覆盖 {pct_s(ut[0])}(日均 {ut[1]:.0f} 只) / 测试覆盖 {pct_s(ue[0] if ue else None)}(日均 {0 if not ue or ue[1] is None else ue[1]:.0f} 只)")
        L.append("")
        L.append("朴素贝叶斯指纹池最强特征(倍数=导师占比/市场占比): " + "; ".join(f"{f}={lab} ×{x}" for f, lab, x in v.get("nb_top", [])))
    else:
        L.append(v.get("note") or "未挖出满足约束的规则")
    L.append("")
    # 八、反例/例外
    L.append("## 八、反例与例外")
    L.append("")
    ex = R.get("exceptions") or []
    if ex:
        L.append("不满足任何规则的新开仓, 按打法统计: " + (R.get("exc_dist") or "—"))
        L.append("")
        for e in ex[:10]:
            L.append(f"- {e}")
    else:
        L.append("—")
    L.append("")
    # 九、验证
    L.append("## 九、指纹池时间外验证")
    L.append("")
    if p30:
        L.append("| 池大小 | 测试笔数 | 指纹池命中 | 随机 | 昨涨幅榜 | 昨成交额榜 | 昨涨停(按成交额) | 去掉回头票特征 | 日均候选 |")
        L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for N in POOL_N:
            p = v["pool"][N]; pn = (v.get("pool_no_revisit") or {}).get(N) or {}
            L.append(f"| Top{N} | {p['targets']} | {pct_s(p['hit'], 1)} | {pct_s(p['rand'], 1)} | {pct_s(p['gain'], 1)} | {pct_s(p['amt'], 1)} | {pct_s(p['zt'], 1)} | {pct_s(pn.get('hit'), 1)} | {p['cand_avg']:.0f} |")
        tag, ratio = clarity(R)
        L.append("")
        L.append(f"结论: 指纹清晰度={tag}" + (f"(Top{POOL_N[1]} 命中/最好基线 = ×{ratio:.1f})" if ratio else ""))
    else:
        L.append(v.get("note") or "—")
    L.append("")
    try:   # 10/25 用户: 板型买点(一字 / T字 / 厂字 / 烂板回封 / 炸板 / 深V / 反包)—— 给机械层更多打法选项; scripts/tzzb/board_entry.py
        import board_entry as BE
        L += BE.section(R["ledger"])
    except Exception as e:   # noqa: BLE001
        L += ["## 十、板型买点", "", f"(这次没算出来: {e!r})"[:200], ""]
    out_md.write_text("\n".join(L) + "\n", encoding="utf-8")


def exceptions_of(R, mt):
    v = R.get("valid") or {}
    rules = v.get("rules") or []
    if not rules:
        return
    ex, labs = [], []
    for r, j, e in mt.tr_all:
        ok = any(all(mt.cats[k][r - 1, j] in vals for k, vals in ru["atoms"]) for ru in rules)
        if not ok:
            labs.append(e["play"])
            f = e["f"]
            ex.append(f"{e['date']} {e['code']} {e['name']}: {e['play']}; 昨涨跌 {pct_s(f.get('pct_prev'), 1)}, 20日 {pct_s(f.get('ret20_prev'))}, 市值 {f.get('fmcap_prev_e8')} 亿, 买价 {pct_s(f.get('buy_pct'), 1)}")
    R["exc_n"] = len(ex)
    R["exc_dist"] = f"n={len(ex)}/{len(mt.tr_all)}: " + dist_line(dist(labs), k=6) if labs else None
    R["exceptions"] = ex[-10:]


def write_cases(R, mt, out_jsonl):
    keep = ["asset", "pct_prev", "ret5_prev", "ret20_prev", "zt_prev", "zb_prev", "H_prev", "zt_age_prev", "pos20_prev", "ma20r_prev",
            "above_ma20_prev", "ma20_up_prev", "volr_prev", "amt_prev_e8", "turn_prev", "fmcap_prev_e8", "hot_prev", "lhb_prev", "is_st",
            "open_pct", "close_pct", "high_pct", "low_pct", "zt_day", "zb_day", "hot_day", "lhb_day", "buy_pct", "at_limit", "pos_in_day",
            "vs_open", "brk20", "idx_pct_prev", "idx_pct_day", "idx_ret5_prev", "zt_n_prev", "up_ratio_prev", "zt_n_day", "themes"]
    with out_jsonl.open("w", encoding="utf-8") as fh:
        for e in sorted(mt.buys + mt.sells, key=lambda x: (x["date"], x["t_first"])):
            f = e.get("f") or {}
            rec = {"date": e["date"], "time": e["t_first"], "code": e["code"], "name": e["name"], "side": "买" if e["side"] == "B" else "卖",
                   "vwap": _f(e["vwap"], 3), "nlegs": e["nlegs"], "feat": {k: f.get(k) for k in keep if k in f}}
            if e["side"] == "B":
                rec.update({"new_open": e["new_open"], "revisit": e["revisit"], "play": e["play"], "play_subs": e["subs"],
                            "result": {"r_close": f.get("r_close"), "r_next": f.get("r_next"), "r_5d": f.get("r_5d")}})
            else:
                rec.update({"sell_kind": e["kind"], "result": {"pnl": _f(e["pnl"]), "hold_days": e["hold_days"], "same_day": e["same_day"],
                                                                "r_next_after_sell": f.get("r_next")}})
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        for ev in getattr(mt, "intraday_events", []):
            rec = {"date": ev["date"], "time": ev.get("time"), "side": "日内事件", "event": ev["type"], "codes": ev["codes"], "names": ev["names"],
                   "evidence": ev["evidence"], "hyp": ev["hyp"], "hyp_note": "基于可观测后果的打分推断, 非真实动机; 规则见 fingerprint.md 盘中节奏节"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def hypo_verdict(R):
    it = R["intraday"]
    v = R.get("valid") or {}
    p50 = (v.get("pool") or {}).get(POOL_N[1])
    out = {}
    bd = it["buy_days"]
    if bd < 10:
        return {"note": f"买入日仅 {bd}, 不判"}
    pr = it["probe_rate"]
    cpd = (it.get("codes_per_day_q") or [0, 0, 0])[1]
    if cpd >= 4:
        out["先小仓试错"] = f"不适用(撒网/拆单型: 每日买入中位 {cpd:.0f} 只, 首笔小是常态不是试错)"
    else:
        out["先小仓试错"] = "成立" if pr >= 0.25 else "部分" if pr >= 0.10 else "不成立"
    lr = it["later_rel"]
    same, diff = lr.get("同题材(联动)", 0), lr.get("不同题材(换方向)", 0)
    if same + diff >= 5:
        out["后续买入=换方向"] = "多为换方向" if diff > same * 1.5 else "多为同题材联动" if same > diff * 1.5 else "两者相当"
    else:
        out["后续买入=换方向"] = "样本不足"
    if it["later_n"] >= 5:
        dh = (it["later_hot"] or 0) - it["first_hot"]
        dl = (it["later_lim"] or 0) - it["first_lim"]
        out["追联动(后续更偏涨停/热点)"] = "成立" if (dh >= 0.10 or dl >= 0.10) else "不成立" if (dh <= 0 and dl <= 0) else "弱"
    else:
        out["追联动(后续更偏涨停/热点)"] = "样本不足"
    out["试错即砍"] = "常见" if it["probe_days"] >= 5 and it["probe_cut_rate"] >= 0.4 else "少见" if it["probe_days"] >= 5 else "样本不足"
    out["池外比例(Top50)"] = None if not p50 else 1 - p50["hit"]
    return out


def write_report(results, papers, M, path):
    L = []
    now = dtm.datetime.now().isoformat(timespec="seconds")
    L.append("# tzzb 导师深度沉淀·机械层: 交易指纹 + 统一打法分类器(2026-10-16)")
    L.append("")
    L.append(f"> 脚本: `scripts/tzzb/mentor_fingerprint.py`(零 token, 只读) | 生成: {now} | 行情面板 {M.dates[0]}~{M.dates[-1]}")
    L.append("> 产物: 各 `skills/<ledger>-skill/persona/fingerprint.md` + `cases_auto.jsonl`; 盘前池 `scripts/tzzb/pools/<日>.json`")
    L.append("> 背景: 拟人度首跑(mimicry_metric_20261016.md)显示选股层与真人重合≈0。本报告把口径从「同一只票」换成「同一种打法」, 并给出导师自选股池的机械还原。")
    L.append("")
    # 总表
    L.append("## 一、逐导师指纹要点与命中率")
    L.append("")
    L.append(f"命中率=时间外测试段(每人后 30% 买入日)导师**新开仓**落在前一日收盘出的指纹池里的比例; 基线同池大小。清晰度: Top{POOL_N[1]} 命中≥25%=清晰, 12~25%=中等, <12%=不清晰; 再看「命中/最好基线(随机、昨涨幅榜、昨成交额榜、昨涨停)」: ≥1.5(中等档≥1.3)标「个性化」, 否则标「≈通用热门清单」(=导师选股基本就是市场通用的昨日强势股清单, 指纹清楚但没有个人增量)。测试<15 笔标样本太少。")
    L.append("")
    L.append(f"| 导师 | 新开仓 n | 一句话指纹 | Top{POOL_N[0]} 命中 | Top{POOL_N[1]} 命中 | 随机 | 昨涨幅榜 | 昨成交额榜 | 昨涨停 | 去回头票 | 清晰度 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for R in results:
        v = R.get("valid") or {}
        p30 = (v.get("pool") or {}).get(POOL_N[0]); p50 = (v.get("pool") or {}).get(POOL_N[1])
        pn = (v.get("pool_no_revisit") or {}).get(POOL_N[1]) or {}
        tag, ratio_ = clarity(R)
        if ratio_:
            tag = f"{tag}(×{ratio_:.1f})"
        if p50:
            L.append(f"| {R['name']} | {R.get('n_new_open')} | {one_liner(R)} | {pct_s(p30['hit'], 1)} | {pct_s(p50['hit'], 1)}(n={p50['targets']}) | {pct_s(p50['rand'], 1)} | "
                     f"{pct_s(p50['gain'], 1)} | {pct_s(p50['amt'], 1)} | {pct_s(p50['zt'], 1)} | {pct_s(pn.get('hit'), 1)} | {tag} |")
        else:
            L.append(f"| {R['name']} | {R.get('n_new_open')} | {one_liner(R)} | — | — | — | — | — | — | — | {tag}: {v.get('note', '')} |")
    L.append("")
    # 规则
    L.append("## 二、各导师典型规则(训练段挖掘, 测试段复核)")
    L.append("")
    for R in results:
        v = R.get("valid") or {}
        if not v.get("rules"):
            continue
        L.append(f"**{R['name']}**(截止 {v['cut_date']}, 训练 {v['n_train']} / 测试 {v['n_test']})")
        L.append("")
        for i, ru in enumerate(v["rules"], 1):
            t = ru.get("test") or {}
            L.append(f"- R{i} {ru['text']}: 训练覆盖 {pct_s(ru['cov'])}, 日均 {ru['daily']:.0f} 只, 倍数 ×{ru['lift']:.1f} → 测试覆盖 {pct_s(t.get('cov'))}, 倍数 {'—' if not t.get('lift') else f'×{t['lift']:.1f}'}")
        L.append("")
    # 区分度
    L.append("## 三、哪些特征最有区分度(跨导师汇总)")
    L.append("")
    agg = defaultdict(list)
    for R in results:
        v = R.get("valid") or {}
        for f, lab, x in v.get("nb_top", [])[:8]:
            agg[f].append((R["name"], lab, x))
    for f, xs in sorted(agg.items(), key=lambda kv: -len(kv[1])):
        L.append(f"- {f}(在 {len(xs)} 人的 Top8 强特征里): " + "; ".join(f"{n} {lab} ×{x}" for n, lab, x in xs))
    L.append("")
    # 打法分类器
    L.append("## 四、统一打法分类器(classify_play, 纯函数可 import)")
    L.append("")
    L.append("调用: `from mentor_fingerprint import Market, event_features, classify_play`; `f = event_features(M, 'sz002074', M.didx['2026-10-09'], 30.05, '10:31:23')`; `main, subs = classify_play(f)`。")
    L.append("主标签互斥, 按下表顺序取第一个命中的; 只用「买入前一日收盘状态 + 买价 + 当日涨停价(由昨收算)」, 不用当日收盘 → paper 成交/盘中实时都能同口径判。")
    L.append("")
    L.append("| 优先级 | 主标签 | 判定 |")
    L.append("| --- | --- | --- |")
    for i, k in enumerate(PLAY_ORDER, 1):
        L.append(f"| {i} | {k} | {PLAY_DEF[k]} |")
    L.append("")
    L.append("涨停价(规则口径=scripts/lib/a_rules.py, 出处见 docs/rules/a_share_trading_rules.md): 主板 10%/创业板·科创板 20%/北交所 30%/转债 20%(上市首日 +57.3%)/ETF 10%(科创·创业类 20%); "
             "主板 ST 2026-07-06 起 10%, 之前 5%(ST 身份只知当前与成交名称, 07-06 前用当日最高≤+5%价且最低≥-5%价验证当时是否 ST); 沪深新股前 5 日、北交所首日无涨停价。"
             "在涨停价成交=买价≥涨停价-半个最小价位。")
    L.append("")
    L.append("副标签(可多个): 时段 竞价(≤09:25:59)/开盘5分钟/早盘(<10:30)/盘中/尾盘(≥14:30); 执行 打板/追涨(≥+5%未板)/低吸(买价在当日最终高低区间下 30% 且≤+1%); 放量(当日量比≥2)/热点题材/昨龙虎榜/ST/降级标记。")
    L.append("")
    L.append("**降级规则**: ①无成交价(只有日线收盘)→ 买价按收盘, 「在涨停价」改判为「收盘封板」, 副标签加「降级:无成交价按收盘」; ②无成交时刻(paper 成交只有挂单时段、tzzb 手录 00:00:00 腿)→ 不出时段副标签; "
             "③「低吸」用的是当日最终高低区间(盘中当时并不知道最终低点), 只作副标签不进主标签; 有分钟线的日子(10/09 起约 800 只)以后可改成「成交时相对此前日内高点回落幅度」。竞价/尾盘之所以不做主标签: 时段是执行细节, 与形态正交, 而且 paper 成交没有真实时刻, 放进主标签会让真人与 paper 不可比。")
    L.append("")
    tot = Counter(); tot_new = Counter()
    for R in results:
        if R.get("empty"):
            continue
        for k, n in R["play_new_n"].items():
            tot_new[k] += n
    n_all = sum(tot_new.values())
    L.append(f"**覆盖率**(全部导师新开仓 n={n_all}): " + " / ".join(f"{k} {tot_new[k] / n_all * 100:.1f}%" for k in PLAY_ORDER if tot_new.get(k)))
    L.append("")
    L.append(f"落入「其他」{tot_new.get('其他', 0) / max(1, n_all) * 100:.1f}%; 「数据缺失」{tot_new.get('数据缺失', 0) / max(1, n_all) * 100:.1f}%(港股/退市转债/早期北交所)。「弱势震荡」是兜底但有明确定义(不在 MA20 上行通道、未超跌、未追涨), 不等于「其他」。")
    L.append("")
    L.append("| 导师 | " + " | ".join(PLAY_ORDER[:14]) + " |")
    L.append("| --- |" + " --- |" * 14)
    for R in results:
        if R.get("empty"):
            continue
        L.append(f"| {R['name']}(n={R['n_new_open']}) | " + " | ".join(("" if not R['play_new'].get(k) else f"{R['play_new'][k] * 100:.0f}%") for k in PLAY_ORDER[:14]) + " |")
    L.append("")
    # paper 对比
    L.append("## 五、paper 链打法分布 vs 导师真人(替代「同一只票」的拟人度选股层口径)")
    L.append("")
    L.append("paper = `scripts/dfcf/paper/books/A-<导师>.json` 的 trades 中 10/08 起的 BUY(只读; 注意 books 今晚可能整本重跑替换, 届时需重算)。真人分布=该导师全历史新开仓。"
             "JS=Jensen-Shannon 距离(0 相同, 1 完全不同); 重合度=Σmin(p,q)。对照列=A-control(裸模型)与同一导师的距离: skill 链若不比对照组更近, 说明 persona 没把打法学进去。")
    L.append("")
    L.append("| 导师 | 真人新开仓 n | 链新开仓/全部买入 | 链 JS | 链重合度 | 对照组 JS | 对照组重合度 | 真人 10/08 后 n | 真人近期 vs 全史 JS | 链主打法 | 真人主打法 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    ctrl = papers.get("control")
    for R in results:
        if R.get("empty"):
            continue
        pp = papers.get(R["ledger"])
        real = R["play_new"]
        if not pp or not pp["n"]:
            L.append(f"| {R['name']} | {R['n_new_open']} | 0 | — | — | — | — | {R['play_since_1008_n']} | — | — | {dist_line(real, k=2)} |")
            continue
        jsd = js_distance(pp["dist_new"], real); ov = overlap(pp["dist_new"], real)
        cj = js_distance(ctrl["dist_new"], real) if ctrl and ctrl["n_new"] else None
        co = overlap(ctrl["dist_new"], real) if ctrl and ctrl["n_new"] else None
        rj = js_distance(R["play_since_1008"], real) if R["play_since_1008_n"] else None
        L.append(f"| {R['name']} | {R['n_new_open']} | {pp['n_new']}/{pp['n']} | {jsd:.2f} | {ov * 100:.0f}% | {'—' if cj is None else f'{cj:.2f}'} | {'—' if co is None else f'{co * 100:.0f}%'} | "
                 f"{R['play_since_1008_n']} | {'—' if rj is None else f'{rj:.2f}'} | {dist_line(pp['dist_new'], k=2)} | {dist_line(real, k=2)} |")
    L.append("")
    if ctrl:
        L.append(f"A-control(对照组)10/08 起新开仓买入 n={ctrl['n_new']}: {dist_line(ctrl['dist_new'])}")
        L.append("")
        ctop = max(ctrl["dist_new"].items(), key=lambda kv: kv[1])[0] if ctrl["dist_new"] else None
        chains = [(R["name"], papers[R["ledger"]]) for R in results if R["ledger"] in papers and papers[R["ledger"]]["n_new"]]
        same_top = [n for n, pp in chains if pp["dist_new"] and max(pp["dist_new"].items(), key=lambda kv: kv[1])[0] == ctop]
        closer = [R["name"] for R in results if R["ledger"] in papers and papers[R["ledger"]]["n_new"] and ctrl["n_new"]
                  and js_distance(papers[R["ledger"]]["dist_new"], R["play_new"]) < js_distance(ctrl["dist_new"], R["play_new"]) - 0.05]
        L.append(f"**读法**: {len(same_top)}/{len(chains)} 条导师链的第一打法与对照组相同(={ctop}), 说明链的选股打法主要由驱动器/LLM 默认偏好决定, 不随导师变化; "
                 f"链 JS 比对照组小 0.05 以上(persona 确实把打法往导师方向拉了)的只有: {'、'.join(closer) or '无'}。")
        L.append("")
    L.append("「真人近期 vs 全史 JS」= 导师自己 10/08 后的打法分布与其全历史的距离, 是「同一个人换个时间段」的自然波动下限参考: 链 JS 接近这个数才算像。样本小(多为个位数)时 JS 偏大, 不可单独排序。")
    L.append("")
    # 盘中节奏
    L.append("## 六、盘中节奏: 用户假设逐导师检验")
    L.append("")
    L.append("假设(10/16 晚): 真人会先小仓试错(竞价买 1/5 仓), 方向不对就换另一只(小仓), 看到热点确认再追已封板票的同板块联动票加仓。")
    L.append("")
    L.append("| 导师 | 买入日 | 首笔占当日买入额(中位) | 首笔占总资产(中位) | ≥2只买入日 | 先小仓试错日 | 试错即砍 | 后续 同题材/不同题材 | 首笔 涨停价/热点 | 后续 涨停价/热点 | 同票先买后卖 | 换股日 | Top50 池外 | 判定 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for R in results:
        if R.get("empty"):
            continue
        it = R["intraday"]; hv = R.get("hypo") or {}
        lr = it["later_rel"]
        fr = it["first_ratio_day_q"]; fa = it["first_ratio_asset_q"]
        verdict = "; ".join(f"{k}:{v}" for k, v in hv.items() if k != "池外比例(Top50)" and v is not None)
        L.append(f"| {R['name']} | {it['buy_days']} | {'—' if not fr else f'{fr[1] * 100:.0f}%'} | {'—' if not fa else f'{fa[1] * 100:.1f}%'} | {pct_s(it['multi_rate'])} | "
                 f"{pct_s(it['probe_rate'])} | {pct_s(it['probe_cut_rate']) if it['probe_days'] else '—'} | {lr.get('同题材(联动)', 0)}/{lr.get('不同题材(换方向)', 0)}(未知 {lr.get('题材未知', 0)}) | "
                 f"{pct_s(it['first_lim'])}/{pct_s(it['first_hot'])} | {pct_s(it['later_lim'])}/{pct_s(it['later_hot'])} | {it['buy_then_sell']} | {it['swap_days']} | "
                 f"{pct_s(hv.get('池外比例(Top50)'))} | {verdict or hv.get('note', '')} |")
    L.append("")
    grp = defaultdict(list)
    for R in results:
        hv = R.get("hypo") or {}
        if R.get("empty") or "note" in hv:
            grp["不判(买入日<10)"].append(R["name"])
            continue
        v0 = hv.get("先小仓试错", "")
        grp["成立" if v0.startswith("成立") else "部分" if v0.startswith("部分") else "不适用" if v0.startswith("不适用") else "不成立"].append(R["name"])
    L.append("**「先小仓试错」逐导师结论**: " + "; ".join(f"{k}: {'、'.join(v)}" for k, v in grp.items() if v))
    fol = [R["name"] for R in results if (R.get("hypo") or {}).get("追联动(后续更偏涨停/热点)") == "成立"]
    sw = [R["name"] for R in results if (R.get("hypo") or {}).get("后续买入=换方向") == "多为换方向"]
    lk = [R["name"] for R in results if (R.get("hypo") or {}).get("后续买入=换方向") == "多为同题材联动"]
    L.append("")
    L.append(f"**后续买入是换方向还是联动**: 多为换方向(不同题材): {'、'.join(sw) or '无'}; 多为同题材联动: {'、'.join(lk) or '无'}; 其余样本不足或两者相当。**追联动(后续票更偏涨停价/热点)成立**: {'、'.join(fol) or '无'}。")
    L.append("")
    L.append("判定口径: 先小仓试错=「≥2 只买入且首笔(首只票开仓 5 分钟内成交额)≤当日买入总额 1/3 且≤前一日总资产 25%」的天数占买入日 ≥25% 成立 / 10~25% 部分 / <10% 不成立; "
             "追联动=后续票在涨停价买或在当日热点题材的比例比首笔高≥10pp 成立; 换方向=后续票与首笔题材无交集的次数 >1.5×有交集。题材只覆盖 2026-01-15 起且只认识上过涨停分析的股, 「题材未知」占比高的导师该项不可信。")
    L.append("")
    L.append(f"「池外比例」直接可做链里「池外自主挑票预算」: 例如池外 70% = 真人 10 次新开仓有 7 次不在自己的机械习惯池(Top{POOL_N[1]})里, 链就不该被池子硬约束。")
    L.append("")
    L.append("### 6.1 逐事件「为什么」假设分布(按导师汇总, 合计 100%)")
    L.append("")
    L.append("| 导师 | 同日多票 | 换股 | 同票加仓 | 同票先买后卖 |")
    L.append("| --- | --- | --- | --- | --- |")
    for R in results:
        if R.get("empty"):
            continue
        hs = R["intraday"].get("hyp_sum") or {}
        cells = []
        for typ in HYP_DEF:
            x = hs.get(typ)
            cells.append("—" if not x else f"n={x['n']}: " + " / ".join(f"{k}{v * 100:.0f}%" for k, v in sorted(x["mean"].items(), key=lambda kv: -kv[1])))
        L.append(f"| {R['name']} | " + " | ".join(cells) + " |")
    L.append("")
    L.append("**打分规则**: 每类事件预设互斥穷尽的假设集合(必含「其他/证据不足」), 每个假设写出它应留下的可观测后果; 基础分各 1, 命中一条证据乘对应系数(支持>1, 反驳<1), 最后归一成百分比。逐事件分布+所用证据写在 cases_auto.jsonl(side=日内事件)。")
    L.append("")
    for typ, hs in HYP_DEF.items():
        L.append(f"- **{typ}**: " + "; ".join(f"{h} ← {d}" for h, d in hs.items()))
    L.append("")
    L.append("**局限**: ①观测不到真实动机, 分布只是「哪种解释与留下的后果更相容」; ②系数是人定的先验(未用标注数据校准), 绝对百分比不可当概率, 只适合导师间横比与同一导师随时间比; "
             "③「其他/证据不足」在题材未知/缺行情时被加权, 证据越弱它越大(同日多票证据全缺时≈36%, 加仓/先买后卖无证据命中时=25%), 不会被压成 0; ④同日多票只拿「首只」和后续每只两两比较, 3 只以上的复杂序列被拆成多对; "
             "⑤后果用了事后信息(首只 2 日内是否亏损卖、是否持有到次日), 所以这是复盘归因, 不可在盘中实时用。")
    L.append("")
    return L


def write_report_tail(L, results, M, path):
    L.append("## 七、数据缺口")
    L.append("")
    mm = M.theme_match
    L.append(f"- 行情: 行情库 kline_day 2025-06 起; 10/09 前无成交额/换手率(成交额用 量×OHLC 均价近似, 换手/流通市值用 10/09 后换手率反推流通股本套历史, 有增发/解禁的票会偏), 10/09 前无北交所; 退市/到期转债无行情(不吃土豆0 的转债大面积「数据缺失」)。")
    L.append(f"- 题材: 只有 md「## 涨停分析」(2026-01-15 起), 名称→代码匹配 {mm[0]} 条 / 未匹配 {mm[1]} 条(OCR 错字/改名); 只认识上过涨停分析的股, 没有完整行业/概念成分库与板块涨幅排名 → 「当日涨幅前列板块」用「当日涨停数前三题材」代替; 2026-01-15 前的买入题材特征为缺失。")
    L.append("- 龙虎榜: lhb_stock 2025-01 起, 有。涨跌家数/涨停家数: 从全市场日线自算(不依赖 md)。")
    L.append("- 分钟线: 只有 10/09 起约 800 只, 本版未用(买点低吸/冲高只用日线区间, 已标降级)。")
    L.append("- 港股(量化小号/星见野少量)无行情 → 「数据缺失」。")
    L.append("")
    L.append("## 八、建议怎么接入")
    L.append("")
    L.append("1. **事实包加「本导师自选股池」**: 盘前跑 `mentor_fingerprint.py --pool --date <今天>` → `scripts/tzzb/pools/<日>.json`, 每位导师 Top30(含打分理由/题材), 作为 01/04 步的候选来源之一; 只用前一日收盘数据, 无后见。")
    L.append("2. **04 候选约束**: 候选票须(a)落在本导师池内, 或(b)占用「池外预算」(=该导师时间外池外比例, 见第六节), 并且(c)候选的打法主标签须在导师打法分布里占比≥5%(用 classify_play 对挂单价预判)。指纹「不清晰」的导师只用(c), 不用(a)。")
    L.append("3. **拟人度选股层主口径改为打法分布 JS**: 用第五节的方法每日/滚动算链 vs 真人, 以「对照组 JS」和「真人近期 vs 全史 JS」为上下界。")
    L.append("4. **LLM 深蒸馏输入包**: `cases_auto.jsonl` 逐笔(买入前状态+打法+结果), 按打法分组抽样(每类 ≤10 笔, 正负结果各半)喂给蒸馏, 让 LLM 只做「为什么在这些情形下买/不买」的归纳, 统计数字以 fingerprint.md 为准不许改写。")
    L.append("")
    L.append("## 九、不自信点")
    L.append("")
    L.append("1. 题材特征覆盖窄且有 OCR 噪声; 热点=当日涨停数前三题材, 题材名跨日不统一(如「AI应用」vs「AI智能体」)会低估「同题材」。")
    L.append("2. 流通市值/换手/历史成交额是近似值, 分箱边界附近的票会错箱。2026-07-06 前主板 ST 档位用当日区间推断(当时已摘帽、现名不带 ST 又不在导师成交名单里的票会被当 10% 档, 漏判其 5% 涨停); 07-06 起按新规一律 10%。")
    L.append("3. 朴素贝叶斯假设特征独立, 实际高度相关(昨涨停/连板/近10日涨停/量比), 分数只用于排序, 倍数不可当概率。")
    L.append("4. 时间外样本小的导师(大兴/边学/宣秋/冲5000w)命中率置信区间很宽; 冲5000w 数据止于 07/06, 其测试段是 2026 上半年, 与当前行情不同期。")
    L.append("5. 「新开仓」靠腿推算持仓 ∪ day_positions, 数据窗口之前的老仓若没出现在 day_positions 里会被当新开仓。antoo 拆单极碎, 日×票聚合后同日多次进出被合并。")
    L.append("6. 卖出 FIFO 成本按本人数据窗口内的腿算, 窗口前买入的筹码=「成本未知」; 两融/做T 账户的 FIFO 与真实成本(券商摊薄)不同。")
    L.append("7. paper 链只有 10/08 起 7 个交易日, 每条链几笔到十几笔买入, JS 波动大; books 今晚可能被整日重跑替换。")
    L.append("8. 指纹池命中只算新开仓(选股层); 加仓/做T 不进池评估。基线「昨涨停按成交额」与打板型导师天然接近, 这些人的「倍数」偏低不代表指纹差。")
    L.append("")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


# ====================================================================================
# 十一、selftest
# ====================================================================================
def selftest():
    ok = True

    def chk(name, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok &= bool(cond)
    chk("round2 3.33*1.1=3.66", float(round2(3.33 * 1.1)) == 3.66)
    chk("round2 10*1.1=11.0", float(round2(10 * 1.1)) == 11.0)
    chk("round2 12.35*1.1=13.59", float(round2(12.35 * 1.1)) == 13.59)
    chk("ST 5%档(2026-07-03 前)", limit_price(10.0, "MAIN", True, 10.5, 9.8, "2026-07-03") == (10.5, 9.5))
    chk("ST 10%档(07-06 前但当日最高超5%=当时非ST)", limit_price(10.0, "MAIN", True, 10.8, 9.8, "2026-07-03") == (11.0, 9.0))
    chk("ST 2026-07-06 起一律 10%", limit_price(10.0, "MAIN", True, 10.5, 9.8, "2026-07-06") == (11.0, 9.0))
    chk("与 a_rules 同口径(ST 07-03 5%/07-06 10%)", AR.limit_prices("600001", "2026-07-03", 10.0, is_st=True, lookup=False) == (10.5, 9.5)
        and AR.limit_prices("600001", "2026-07-06", 10.0, is_st=True, lookup=False) == (11.0, 9.0))
    chk("创业板20%", limit_price(10.0, "GEM") == (12.0, 8.0))
    chk("代码分类", [asset_class(c) for c in ("600000", "688001", "002074", "300750", "920199", "510300", "159915", "113618", "123150", "00700", "204001")]
        == ["MAIN", "STAR", "MAIN", "GEM", "BSE", "ETF", "ETF", "CB", "CB", "HK", "REPO"])
    chk("symbol", [symbol_of(c) for c in ("600000", "002074", "920199", "510300", "159915", "113618", "123150")]
        == ["sh600000", "sz002074", "bj920199", "sh510300", "sz159915", "sh113618", "sz123150"])
    chk("指数符号", asset_of_symbol("sh000001") == "INDEX" and asset_of_symbol("sz000001") == "MAIN")
    base = {"data": True, "asset": "MAIN", "H_prev": 0, "zb_prev": False, "zt_age_prev": None, "nbars_prev": 200, "brk20": False,
            "buy_pct": 0.01, "at_limit": False, "ret20_prev": 0.0, "ret5_prev": 0.0, "pos20_prev": 0.5,
            "above_ma20_prev": False, "ma20_up_prev": False, "price_vs_ma5_prev": 0.03, "time": "10:00:00"}
    cases = [({"H_prev": 2}, "连板接力"), ({"H_prev": 1, "at_limit": True}, "连板接力"), ({"at_limit": True}, "首板打板"),
             ({"H_prev": 1}, "首板次日"), ({"zb_prev": True}, "炸板次日"), ({"zt_age_prev": 3}, "涨停回调"),
             ({"nbars_prev": 10}, "次新"), ({"brk20": True}, "突破新高"), ({"buy_pct": 0.06}, "追涨"),
             ({"ret20_prev": -0.2}, "超跌反弹"), ({"above_ma20_prev": True, "ma20_up_prev": True, "price_vs_ma5_prev": 0.0}, "趋势回踩"),
             ({"above_ma20_prev": True, "ma20_up_prev": True}, "趋势跟随"), ({}, "弱势震荡"), ({"asset": "ETF"}, "ETF/宽基"),
             ({"asset": "CB"}, "转债"), ({"data": False, "asset": "HK"}, "数据缺失"), ({"ret20_prev": None, "ret5_prev": None}, "其他")]
    for over, want in cases:
        got, subs = classify_play({**base, **over})
        chk(f"classify_play {over} → {want}", got == want)
    _m, subs = classify_play({**base, "time": "09:25:00", "at_limit": True})
    chk("副标签 竞价+打板", "竞价" in subs and "打板" in subs)
    chk("classify_sell", [classify_sell(0.05, 3, True), classify_sell(-0.05, 3, False), classify_sell(0.05, 2, False, 0.8, 0.03),
                          classify_sell(0.05, 2, False, 0.2, 0.0), classify_sell(0.0, 6, False), classify_sell(0.01, 2, False), classify_sell(None, None, False)]
        == ["日内T", "止损", "冲高止盈", "止盈", "时间止损/平走", "小盈亏快出", "成本未知"])
    chk("JS 相同=0", js_distance({"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5}) < 1e-9)
    chk("JS 不相交=1", abs(js_distance({"a": 1.0}, {"b": 1.0}) - 1) < 1e-9)
    chk("time_bucket", [time_bucket(x) for x in ("09:25:03", "09:31:00", "10:00:00", "13:00:00", "14:45:00", "00:00:00")]
        == ["竞价", "开盘5分钟", "早盘", "盘中", "尾盘", None])
    rows = parse_md_themes("2026-08-12")
    chk("md 涨停分析解析(2026-08-12)", rows is not None and any(r[0] == "光通信" and r[1] == "通宇通讯" for r in rows))
    # 行情面板相关(需要 DB): 价格对齐 + 无后见
    try:
        M = Market(start="2026-08-01")
        d = M.didx.get("2026-10-09")
        f = event_features(M, "sz002074", d, 30.05, "10:31:23", "国轩高科")
        chk("event_features 国轩 10/09 有数据", f["data"] and f["buy_pct"] is not None and abs(f["buy_pct"] - (30.05 / 31.3 - 1)) < 1e-4)
        Mt = Market(asof="2026-10-09", start="2026-08-01")
        r = Mt.row_before("2026-10-09")
        j1, j2 = M.sidx.get("sz002074"), Mt.sidx.get("sz002074")
        same = all(np.array_equal(M.cats[k][r, j1], Mt.cats[k][r, j2]) for k in M.cats)
        chk("无后见: 截断到 10/09 前的面板, 10/08 行分箱特征与全量面板一致", same and Mt.dates[-1] < "2026-10-09")
        chk("ST 档位矩阵: 涨停数合理(10/09 全市场 20~400)", 20 <= int(M.zt_n[d]) <= 400)
    except Exception as ex:  # noqa: BLE001
        print(f"SKIP 行情库相关自测: {ex}")
    print("SELFTEST", "OK" if ok else "FAILED")
    return ok


# ====================================================================================
# main
# ====================================================================================
def run_ledgers(ledgers, asof=None, write_persona=True, report=False):
    M = Market(asof=asof)
    results, mts = [], {}
    outdir = POOL_DIR / f"asof_{asof}" if asof else None
    if outdir:
        outdir.mkdir(parents=True, exist_ok=True)
    for lg in ledgers:
        log(f"[{lg}] 分析中 …")
        R, mt = analyze(lg, M, asof)
        if not R.get("empty"):
            exceptions_of(R, mt)
            R["hypo"] = hypo_verdict(R)
        results.append(R)
        mts[lg] = mt
        if outdir:
            md, cj = outdir / f"{lg}_fingerprint.md", outdir / f"{lg}_cases_auto.jsonl"
        else:
            pdir = ROOT / "skills" / f"{lg}-skill" / "persona"
            if not pdir.is_dir():
                log(f"[{lg}] 无 persona 目录, 跳过写文件")
                continue
            md, cj = pdir / "fingerprint.md", pdir / "cases_auto.jsonl"
        if write_persona or outdir:
            write_fingerprint(R, M, md)
            if not R.get("empty"):
                write_cases(R, mt, cj)
        v = R.get("valid") or {}
        p50 = (v.get("pool") or {}).get(POOL_N[1])
        log(f"[{lg}] 完成 {R.get('elapsed')}s | 新开仓 {R.get('n_new_open')} | Top{POOL_N[1]} 命中 {pct_s(p50['hit'], 1) if p50 else '—'} | {one_liner(R)}")
    if report:
        papers = {}
        for ch in [r["ledger"] for r in results] + ["control"]:
            pdx = paper_dist(M, ch)
            if pdx:
                papers[ch] = pdx
        path = (outdir / "mentor_fingerprint_report.md") if outdir else REPORT
        L = write_report(results, papers, M, path)
        write_report_tail(L, results, M, path)
        log(f"[报告] {path}")
    return results


def main():
    ap = argparse.ArgumentParser(description="tzzb 导师交易指纹·机械层(零 token, 只读)")
    ap.add_argument("--ledger")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--asof", help="只用该日之前的数据(YYYY-MM-DD); 产物写 scripts/tzzb/pools/asof_<D>/")
    ap.add_argument("--pool", action="store_true")
    ap.add_argument("--date", help="--pool 的目标日(YYYY-MM-DD), 用该日之前数据出池")
    ap.add_argument("--n", type=int, default=POOL_N[0], help="池大小(默认 30)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(0 if selftest() else 1)
    if a.pool:
        day = a.date or dtm.date.today().isoformat()
        M = Market(asof=day)
        lgs = [a.ledger] if a.ledger else [m for m in MENTORS if m != "buchitudou0"]
        out = {"date": day, "generatedAt": dtm.datetime.now().isoformat(timespec="seconds"), "feature_day": M.dates[M.row_before(day)],
               "params": {"N": a.n, "model": "朴素贝叶斯(分箱特征 log 倍数之和), 训练=该日之前全部新开仓, 背景=同日全市场候选(去掉已持有)",
                          "universe": "A股(主板/创业板/科创板/北交所有行情者)+ETF(导师 ETF 新开仓≥5% 时)"}, "mentors": {}}
        for lg in lgs:
            log(f"[pool] {lg}")
            out["mentors"][lg] = build_pool(lg, M, day, a.n)
        POOL_DIR.mkdir(parents=True, exist_ok=True)
        p = POOL_DIR / f"{day}.json"
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"[pool] → {p}")
        return
    if a.all:
        run_ledgers(MENTORS, a.asof, report=True)
    elif a.ledger:
        if a.ledger not in NAME_OF:
            sys.exit(f"未知 ledger {a.ledger}")
        run_ledgers([a.ledger], a.asof, report=False)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
