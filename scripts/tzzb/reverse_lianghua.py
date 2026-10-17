# -*- coding: utf-8 -*-
"""
reverse_lianghua.py — 「量化短线小号实验」(ledger=lianghuaxiaohao) 逆向工程(2026-10-16 建, 零 token, 只读)

目标: 把导师疑似程序化的交易还原成确定性规则代码, 并用时间外样本量化还原度。
  ① 分析(默认): 程序化证据(时间/数量/价格) / 选股 / 买点(分钟线) / 卖出 / 仓位 / 版本切换
     → docs/research/reverse_lianghua_20261016.md + scripts/tzzb/reverse_lianghua/{analysis.json, model_params.json, replay_oos.json}
  ② --replay --since D --until D2 : 用还原规则逐日生成模拟交易, 与真人逐日比对 → 还原度(买入命中/方向仓位一致/时点误差/净值相关)
  ③ --signal --date D            : 只用 D 之前数据出当日规则信号 → scripts/tzzb/model_out/lianghua_signal_<D>.json
  ④ --selftest

数据(全部只读): downloads/tzzb/lianghuaxiaohao/(change_bs 逐笔腿 / day_positions / nav_daily)、downloads/tzzb/_minutes/(成交当日分钟线缓存)、
  行情库 investment_market(kline_day/security_master/lhb_stock, 只 SELECT, 经 mentor_fingerprint.Market)。
  不访问任何行情网络接口、不调 LLM、不写业务库、不起子进程、不改其它文件。
口径修正: 行情库科创板(688/689) 2026-10-09 之前的 volume 系统性放大 100 倍(10/09 起正常; 本脚本 FixedMarket 按票检测并除回),
  这会污染 mentor_fingerprint 的「成交额/换手」类特征(科创票被高估), 本脚本内已修, 原脚本未动。

用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/reverse_lianghua.py [--analyze] [--replay --since D --until D2] [--signal --date D] [--selftest]
"""
import argparse
import bisect
import datetime as dtm
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/tzzb"))
import mentor_fingerprint as mf  # noqa: E402  (只读; 复用行情面板/事件/分类函数)

LEDGER = "lianghuaxiaohao"
OUT_DIR = ROOT / "scripts/tzzb/reverse_lianghua"
SIG_DIR = ROOT / "scripts/tzzb/model_out"
REPORT = ROOT / "docs/research/reverse_lianghua_20261016.md"
MIN_CACHE = ROOT / "downloads/tzzb/_minutes"
BASE = ROOT / "downloads/tzzb" / LEDGER
TRAIN_FRAC = 0.7
SEL_ASSETS = ("MAIN", "GEM", "STAR", "BSE", "ETF")
FEE_BUY, FEE_SELL = 0.0002, 0.0007          # 佣金万二 / 卖出含印花税万五
SEED = 20261016
log = mf.log


# ====================================================================================
# 0. 行情面板(修科创板 10/09 前成交量单位) + 分钟线缓存
# ====================================================================================
class FixedMarket(mf.Market):
    """10/17 作废(agent③ 补丁): 行情库科创板 10/09 前 volume ×100 已在 10/16 库里 ÷100 修正(备份表 kline_day_bak_kcb_20261016,
    历史 jsonl 同步), 原"按票检测并除回"会把 10/09 后无数据的科创票再除一次。保留类名与 vfix_n 供 reverse_lianghua_v2 import"""
    def _derive(self):
        self.vfix_n = 0
        super()._derive()


_MCACHE = {}


def minute_bars(day, code):
    """downloads/tzzb/_minutes/<日>.jsonl → 该票当日分钟 bar 列表(按时间); 无=None"""
    if day not in _MCACHE:
        f = MIN_CACHE / f"{day}.jsonl"
        b = defaultdict(list)
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if not r.get("miss") and r.get("symbol"):
                    b[r["symbol"][-6:]].append(r)
        _MCACHE[day] = {k: sorted(v, key=lambda x: x["barTime"]) for k, v in b.items()}
    return _MCACHE[day].get(code)


def bar_label(hhmm):
    """成交时刻 HH:MM → 分钟 K 标签(口径同 collect_minute.label_of)"""
    if hhmm == "09:25":
        return "09:30"
    if "09:30" <= hhmm <= "11:29" or "13:00" <= hhmm <= "14:59":
        h, m = map(int, hhmm.split(":"))
        m += 1
        return f"{h + m // 60:02d}:{m % 60:02d}"
    if hhmm in ("11:30", "15:00"):
        return hhmm
    return None


def sec_of(t):
    return int(t[0:2]) * 3600 + int(t[3:5]) * 60 + int(t[6:8])


def trade_minute(t):
    """HH:MM:SS → 距 09:30 的连续交易分钟(午休压缩)"""
    s = sec_of(t)
    m = (s - 9 * 3600 - 30 * 60) / 60
    if s >= 13 * 3600:
        m -= 90
    return m


def minute_to_hhmm(m):
    m = int(round(m))
    s = 9 * 60 + 30 + m + (90 if m > 120 else 0)
    return f"{s // 60:02d}:{s % 60:02d}"


# ====================================================================================
# 1. 真人数据: 逐日真实动作
# ====================================================================================
def load_real(mt):
    """mt=mf.Mentor → 逐日 dict: 新开仓/首买时刻/卖出时段/收盘仓位/净值收益"""
    base = BASE
    nav = json.loads((base / "nav_daily.json").read_text(encoding="utf-8"))["ex_data"]["index_list"]
    navr, navi = {}, {}
    for k, x in enumerate(nav):
        d = f"{x['date'][:4]}-{x['date'][4:6]}-{x['date'][6:]}"
        navi[d] = float(x["index"])
        if k:
            navr[d] = float(x["index"]) / float(nav[k - 1]["index"]) - 1
    dp = json.loads((base / "day_positions.json").read_text(encoding="utf-8"))
    pos = {}
    for k, v in dp.items():
        d = f"{k[:4]}-{k[4:6]}-{k[6:]}"
        lst = [x for x in (v.get("list") or []) if float(x.get("position_percent") or 0) > 0]
        pos[d] = {"sum_pct": float(v.get("sum_pct") or 0), "codes": [x["code"] for x in lst],
                  "w": {x["code"]: float(x["position_percent"]) for x in lst}}
    days = sorted(set(navr) | set(mt.byday))
    out = {}
    qty = defaultdict(float)
    for d in days:
        legs = sorted(mt.byday.get(d, []), key=lambda t: t["trans_date"])
        pre_qty = {c: q for c, q in qty.items() if q > 1e-9}
        buys = [t for t in legs if t["op"] == "1"]
        sells = [t for t in legs if t["op"] == "2"]
        sold_by10 = defaultdict(float)
        for t in legs:
            q = float(t.get("trans_count") or 0)
            if t["op"] == "1":
                qty[t["stock_code"]] += q
            else:
                qty[t["stock_code"]] -= q
                if t["trans_date"][11:19] < "10:00:00":
                    sold_by10[t["stock_code"]] += q
        prev_codes = [c for c in pre_qty if len(c) == 6]
        frac10 = (sum(min(sold_by10.get(c, 0), pre_qty[c]) for c in prev_codes) / sum(pre_qty[c] for c in prev_codes)) if prev_codes else None
        new = [e for e in mt.buys if e["date"] == d and e["new_open"]]
        first_sell = {}
        for t in sells:
            first_sell.setdefault(t["stock_code"], t["trans_date"][11:19])
        out[d] = {
            "nav_r": navr.get(d), "nav": navi.get(d), "pos": pos.get(d),
            "new_open": [e["code"] for e in new], "new_amt": {e["code"]: e["amt"] for e in new}, "new_vwap": {e["code"]: e["vwap"] for e in new},
            "first_buy": buys[0]["trans_date"][11:19] if buys else None,
            "first_sell": first_sell, "sold_frac_by10": frac10, "n_prev": len(prev_codes),
        }
    return out


# ====================================================================================
# 2. 选股特征(只用 D 前一日收盘 + 本人历史成交) + numpy 逻辑回归
# ====================================================================================
CONT = ["lamt", "lcap", "lpx", "lturn", "pct", "r5", "r20", "pos20", "ma20r", "lvolr", "amtrk"]
BINF = ["zt", "Hn", "zt10", "lhb", "hot", "st", "gem", "star", "etf", "bse", "t1", "t5", "t20", "t60"]
FEATS = CONT + BINF + [f"{k}^2" for k in CONT]


class SelfHist:
    """本人历史成交指示矩阵(行=交易日), 窗口计数只用 ≤ 该行的数据"""
    def __init__(self, M, mt):
        nd, ns = len(M.dates), len(M.syms)
        T = np.zeros((nd, ns), np.float32)
        for c, rows in mt.traded_rows.items():
            s = mf.symbol_of(c)
            j = M.sidx.get(s) if s else None
            if j is None:
                continue
            for r in rows:
                T[r, j] = 1
        self.cs = np.cumsum(T, axis=0)

    def win(self, p, n):
        lo = p - n
        return self.cs[p] - (self.cs[lo] if lo >= 0 else 0)


def day_features(M, SH, p):
    """D 前一日(面板行 p)收盘状态 → (候选列号 js, 原始特征矩阵 X[len(js), len(FEATS)])"""
    ok = np.isin(M.asset, SEL_ASSETS) & M.has[p]
    js = np.where(ok)[0]
    with np.errstate(all="ignore"):
        amt = M.amt[p, js]
        rk = np.empty(len(js))
        rk[np.argsort(-np.nan_to_num(amt, nan=-1))] = np.arange(len(js))
        cols = {
            "lamt": np.log10(amt + 1), "lcap": np.log10(M.fmcap[p, js] + 1), "lpx": np.log10(M.C[p, js]),
            "lturn": np.log1p(np.clip(M.turn[p, js], 0, 100)), "pct": np.clip(M.pct[p, js], -.3, .3),
            "r5": np.clip(M.ret[5][p, js], -.6, 1.5), "r20": np.clip(M.ret[20][p, js], -.7, 3), "pos20": M.pos20[p, js],
            "ma20r": np.clip(M.adjC[p, js] / M.ma[20][p, js] - 1, -.6, 1.5), "lvolr": np.log1p(np.clip(M.volr[p, js], 0, 20)),
            "amtrk": np.log10(rk + 1),
            "zt": M.zt[p, js], "Hn": np.minimum(M.Hn[p, js], 3), "zt10": (M.zt_age[p, js] >= 1) & (M.zt_age[p, js] <= 9),
            "lhb": M.lhb[p, js], "hot": M.hot[p, js] == 2, "st": M.is_st[js],
            "gem": M.asset[js] == "GEM", "star": M.asset[js] == "STAR", "etf": M.asset[js] == "ETF", "bse": M.asset[js] == "BSE",
            "t1": SH.win(p, 1)[js] > 0, "t5": SH.win(p, 5)[js] > 0, "t20": SH.win(p, 20)[js] > 0, "t60": np.log1p(SH.win(p, 60)[js]),
        }
    X = np.zeros((len(js), len(FEATS)), np.float64)
    for k, nm in enumerate(CONT + BINF):
        X[:, k] = np.asarray(cols[nm], dtype=np.float64)
    for k, nm in enumerate(CONT):
        X[:, len(CONT) + len(BINF) + k] = X[:, k] ** 2
    return js, X


class LRModel:
    """L2 逻辑回归(Adam, 类别加权), 只依赖 numpy; fill/mu/sd 来自训练集"""
    def __init__(self, l2=1e-3, iters=500, lr=0.05):
        self.l2, self.iters, self.lr = l2, iters, lr

    def _prep(self, X):
        X = np.where(np.isfinite(X), X, self.fill)
        return (X - self.mu) / self.sd

    def fit(self, X, y, sw=None):
        with np.errstate(all="ignore"):
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.fill = np.nanmedian(np.where(np.isfinite(X), X, np.nan), axis=0)
        self.fill = np.nan_to_num(self.fill)
        Xf = np.where(np.isfinite(X), X, self.fill)
        self.mu, self.sd = Xf.mean(0), Xf.std(0) + 1e-9
        Z = (Xf - self.mu) / self.sd
        n, k = Z.shape
        sw = np.ones(n) if sw is None else sw
        pw = (sw * (1 - y)).sum() / max((sw * y).sum(), 1e-9)
        w_s = sw * np.where(y == 1, pw, 1.0)
        w_s = w_s / w_s.sum()
        w, b = np.zeros(k), 0.0
        m1, v1, mb, vb = np.zeros(k), np.zeros(k), 0.0, 0.0
        for it in range(1, self.iters + 1):
            z = np.clip(Z @ w + b, -30, 30)
            pr = 1 / (1 + np.exp(-z))
            g = Z.T @ ((pr - y) * w_s) + self.l2 * w
            gb = ((pr - y) * w_s).sum()
            m1 = 0.9 * m1 + 0.1 * g; v1 = 0.999 * v1 + 0.001 * g * g
            mb = 0.9 * mb + 0.1 * gb; vb = 0.999 * vb + 0.001 * gb * gb
            w -= self.lr * (m1 / (1 - 0.9 ** it)) / (np.sqrt(v1 / (1 - 0.999 ** it)) + 1e-8)
            b -= self.lr * (mb / (1 - 0.9 ** it)) / (math.sqrt(vb / (1 - 0.999 ** it)) + 1e-8)
        self.w, self.b = w, b
        return self

    def score(self, X):
        return self._prep(X) @ self.w + self.b

    def to_json(self):
        return {"feats": FEATS, "w": self.w.tolist(), "b": float(self.b), "fill": self.fill.tolist(),      # 全精度: sd 里有 1e-9 量级(训练窗恒零的特征), 取整会除零
                "mu": self.mu.tolist(), "sd": self.sd.tolist()}

    @classmethod
    def from_json(cls, d):
        m = cls()
        m.w, m.b = np.array(d["w"]), float(d["b"])
        m.fill, m.mu, m.sd = np.array(d["fill"]), np.array(d["mu"]), np.maximum(np.array(d["sd"]), 1e-9)
        return m


def positives_by_row(M, mt):
    """面板行 i → 当日新开仓(选股可评估的 A 股/ETF)列号集合"""
    pos = defaultdict(set)
    for e in mt.buys:
        if not e["new_open"] or e["row"] is None:
            continue
        s = mf.symbol_of(e["code"])
        j = M.sidx.get(s) if s else None
        if j is not None and M.asset[j] in SEL_ASSETS:
            pos[e["row"]].add(j)
    return pos


def build_train(M, SH, pos, rows, neg_per_day=1500, rng=None):
    rng = rng or np.random.default_rng(SEED)
    Xs, ys, ws = [], [], []
    for i in rows:
        js, X = day_features(M, SH, i - 1)
        live = M.has[i, js]
        js, X = js[live], X[live]
        y = np.isin(js, list(pos[i])).astype(float)
        neg = np.where(y == 0)[0]
        take = rng.choice(neg, size=min(neg_per_day, len(neg)), replace=False) if len(neg) else neg
        idx = np.concatenate([np.where(y == 1)[0], take])
        Xs.append(X[idx]); ys.append(y[idx])
        ws.append(np.where(y[idx] == 1, 1.0, len(neg) / max(len(take), 1)))
    return np.vstack(Xs), np.concatenate(ys), np.concatenate(ws)


def rank_eval(M, SH, pos, rows, scorer, Ns=(2, 5, 10, 20, 50, 100, 200), board_cond=False):
    """逐日全市场排序 → TopN 覆盖率(他买的票有多少进 TopN) / 精确率(TopN 中他买的占比) / 同板块内百分位"""
    hit = Counter(); npos = 0; nd = 0; pct_ranks = []; board_pr = []; pool_sizes = []
    for i in rows:
        if not pos.get(i):
            continue
        js, X = day_features(M, SH, i - 1)
        live = M.has[i, js]
        js, X = js[live], X[live]
        sc = scorer(js, X, i)
        order = np.argsort(-sc)
        rank = np.empty(len(js), int); rank[order] = np.arange(len(js))
        jpos = {j: k for k, j in enumerate(js)}
        nd += 1; pool_sizes.append(len(js))
        for j in pos[i]:
            if j not in jpos:
                continue
            npos += 1
            r = rank[jpos[j]]
            pct_ranks.append(r / len(js))
            for N in Ns:
                hit[N] += r < N
            if board_cond:
                same = M.asset[js] == M.asset[j]
                board_pr.append((sc[same] > sc[jpos[j]]).mean())
    res = {"days": nd, "pos": npos, "pool_med": int(np.median(pool_sizes)) if pool_sizes else 0,
           "cover": {N: round(hit[N] / npos, 4) if npos else None for N in Ns},
           "precision": {N: round(hit[N] / (N * nd), 5) if nd else None for N in Ns},
           "lift": {N: round((hit[N] / npos) / (N / np.median(pool_sizes)), 2) if npos else None for N in Ns},
           "pct_rank_med": round(float(np.median(pct_ranks)), 3) if pct_ranks else None}
    if board_cond and board_pr:
        res["board_pct_rank_med"] = round(float(np.median(board_pr)), 3)
    return res


# ====================================================================================
# 3. 还原规则参数(只用训练窗)
# ====================================================================================
def split_rows(M, pos, frac=TRAIN_FRAC):
    rows = sorted(pos)
    cut = rows[int(len(rows) * frac)]
    return [r for r in rows if r < cut], [r for r in rows if r >= cut], cut


def fit_exec_params(M, mt, real, until_day):
    """执行层参数(只用 < until_day 的真人数据): 每日只数 K / 首买时刻 / 竞价卖出阈值 / 卖出窗"""
    days = [d for d in sorted(real) if d < until_day]
    ks = [len(real[d]["new_open"]) for d in days if real[d]["new_open"]]
    fb = [trade_minute(real[d]["first_buy"]) for d in days if real[d]["first_buy"] and real[d]["first_buy"] >= "09:30:00"]
    # 竞价卖 vs 开盘缺口: 网格搜阈值(准确率最大)
    X = []
    for e in mt.sells:
        if e["date"] >= until_day or len(e["code"]) != 6 or not e.get("hold_days") or e["hold_days"] < 1:
            continue
        s = mf.symbol_of(e["code"]); j = M.sidx.get(s) if s else None; i = e["row"]
        if j is None or i is None or not np.isfinite(M.O[i, j]) or not np.isfinite(M.PC[i, j]):
            continue
        X.append((e["t_first"] <= "09:25:59", M.O[i, j] / M.PC[i, j] - 1))
    a = np.array([x[0] for x in X]); g = np.array([x[1] for x in X])
    best = max(((float(np.mean((g >= th) == a)), float(th)) for th in np.arange(-0.05, 0.0501, 0.0025)), key=lambda z: z[0]) if len(X) else (None, 0.0)
    return {"K": int(np.median(ks)) if ks else 2, "K_mean": round(float(np.mean(ks)), 2) if ks else None,
            "first_buy_min": float(np.median(fb)) if fb else 10.0, "first_buy_hhmm": minute_to_hhmm(np.median(fb)) if fb else "09:40",
            "auction_gap_th": round(best[1], 4), "auction_rule_acc": round(best[0], 3) if best[0] is not None else None,
            "auction_base_acc": round(float(max(a.mean(), 1 - a.mean())), 3) if len(X) else None, "n_sell_fit": len(X),
            "sell_window": "09:25 竞价(开盘缺口≥阈值) 否则 09:30~09:35 连续竞价", "until": until_day}


# ====================================================================================
# 4. 回放: 规则逐日出单 vs 真人
# ====================================================================================
def buy_price(M, i, j, code, hhmm):
    """模拟买价: 有分钟线缓存用 hhmm 那根 bar 收盘, 否则日线代理 (O+H+L+C)/4"""
    bars = minute_bars(M.dates[i], code) if code else None
    if bars:
        lab = bar_label(hhmm)
        for b in bars:
            if b["barTime"][11:16] >= lab:
                return float(b["close"]), "minute"
    o, h, l, c = M.O[i, j], M.H[i, j], M.L[i, j], M.C[i, j]
    if not np.isfinite(o):
        return None, None
    return float((o + h + l + c) / 4), "daily_proxy"


def code_of_sym(s):
    return s[2:]


def sim_nav(M, plan, exit_px="open"):
    """plan: {行 i: [(j, 权重, 买价)]} → 逐日收益(收盘→收盘, 次日卖出, 含费); exit_px=open(开盘窗卖)/avg(次日 (O+H+L+C)/4 卖, 消融用)"""
    XP = M.O if exit_px == "open" else (M.O + M.H + M.L + M.C) / 4
    rows = sorted(plan)
    ret = {}
    held, hrow = [], None          # [(j, w, 买价)], 买入行
    for i in rows:
        # 早盘卖旧仓(开盘价), 资金按权重回笼; 收益基准=买入日收盘(中间若隔了未回放的日子, 按开盘价一次性结算)
        if held:
            v_old = sum(w * (XP[i, j] / M.C[hrow, j] if np.isfinite(XP[i, j]) and np.isfinite(M.C[hrow, j]) else 1.0) for j, w, _ in held)
            v_old += 1 - sum(w for _, w, _ in held)
            v_old *= (1 - FEE_SELL)
        else:
            v_old = 1.0
        new = plan[i]
        if new:
            g = sum(w * (M.C[i, j] / px if np.isfinite(M.C[i, j]) and px else 1.0) for j, w, px in new) * (1 - FEE_BUY)
            g += 1 - sum(w for _, w, _ in new)
        else:
            g = 1.0
        ret[M.dates[i]] = v_old * g - 1
        held, hrow = list(new), i
    return ret


def corr(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 5 or a[m].std() == 0 or b[m].std() == 0:
        return None
    return round(float(np.corrcoef(a[m], b[m])[0, 1]), 3)


def replay(M, mt, real, model, ex, since, until, SH=None, pool_ns=(10, 50, 200), mc=20):
    SH = SH or SelfHist(M, mt)
    pos = positives_by_row(M, mt)
    days = [d for d in M.dates if since <= d <= until and d in real and real[d].get("nav_r") is not None]
    K = ex["K"]
    plan, plan_real, rows_log = {}, {}, []
    rng = np.random.default_rng(SEED)
    rnd_plans = [dict() for _ in range(mc)]
    hits = Counter(); npos = 0; pick_hit = 0; pick_n = 0
    t_err_buy, t_err_sell, auc_ok, auc_n, auc_real = [], [], 0, 0, []
    dir_ok = {"sell_all_open": [], "buy_new": [], "full_pos": [], "n_names": []}
    for d in days:
        i = M.didx[d]
        js, X = day_features(M, SH, i - 1)
        live = M.has[i, js]
        js, X = js[live], X[live]
        sc = model.score(X)
        order = np.argsort(-sc)
        picks = js[order[:K]]
        rp = [j for j in pos.get(i, set())]
        jrank = {j: r for r, j in enumerate(js[order])}
        for j in rp:
            if j in jrank:
                npos += 1
                for N in pool_ns:
                    hits[N] += jrank[j] < N
        pick_n += len(picks); pick_hit += len(set(picks) & set(rp))
        # 规则单: 等权, 首买时刻买
        hh = ex["first_buy_hhmm"]
        plan[i] = []
        for j in picks:
            px, _src = buy_price(M, i, j, code_of_sym(M.syms[j]), hh)
            if px:
                plan[i].append((j, 1.0 / K, px))
        # 随机对照: 同一候选池前 200 名里随机 K 只
        for r in rnd_plans:
            cand = js[order[:200]]
            ch = rng.choice(cand, size=min(K, len(cand)), replace=False)
            r[i] = [(j, 1.0 / K, buy_price(M, i, j, None, hh)[0]) for j in ch]
            r[i] = [x for x in r[i] if x[2]]
        # 真人选股 + 规则执行(执行层还原度): 真买的票按真实金额权重/真实均价, 次日开盘卖
        R = real[d]
        tot = sum(R["new_amt"].values()) or 1
        plan_real[i] = []
        for c, amt in R["new_amt"].items():
            s = mf.symbol_of(c); j = M.sidx.get(s) if s else None
            if j is not None and np.isfinite(M.C[i, j]):
                plan_real[i].append((j, amt / tot * min(1.0, (R["pos"] or {}).get("sum_pct", 1.0) or 1.0), R["new_vwap"][c]))
        # 方向/仓位一致
        if R["n_prev"]:
            dir_ok["sell_all_open"].append((R["sold_frac_by10"] or 0) >= 0.9)
        dir_ok["buy_new"].append(bool(R["new_open"]))
        if R["pos"]:
            dir_ok["full_pos"].append(R["pos"]["sum_pct"] >= 0.9)
            dir_ok["n_names"].append(len(R["pos"]["codes"]) == K)
        if R["first_buy"] and R["first_buy"] >= "09:30:00":
            t_err_buy.append(abs(trade_minute(R["first_buy"]) - ex["first_buy_min"]))
        for c, t in R["first_sell"].items():
            if len(c) != 6 or t < "09:15:00":
                continue
            s = mf.symbol_of(c); j = M.sidx.get(s) if s else None
            if j is None or not np.isfinite(M.O[i, j]):
                continue
            gap = M.O[i, j] / M.PC[i, j] - 1
            rule_auc = gap >= ex["auction_gap_th"]
            real_auc = t <= "09:25:59"
            auc_n += 1; auc_ok += rule_auc == real_auc; auc_real.append(real_auc)
            rule_t = 0.0 if rule_auc else 1.0          # 竞价=第 0 分钟, 否则 09:31
            t_err_sell.append(abs((0.0 if real_auc else max(0.0, trade_minute(t))) - rule_t))
        rows_log.append({"date": d, "rule_picks": [M.syms[j] for j in picks], "real_new": R["new_open"],
                         "real_rank": {M.syms[j]: int(jrank[j]) for j in rp if j in jrank}, "first_buy": R["first_buy"]})
    rr = sim_nav(M, plan); rreal = sim_nav(M, plan_real); rreal_avg = sim_nav(M, plan_real, exit_px="avg")
    exe_avg = [rreal_avg.get(d) for d in days]
    realr = [real[d]["nav_r"] for d in days]
    sim_series = [rr.get(d) for d in days]; exe_series = [rreal.get(d) for d in days]
    idx_sh = [M.idx_pct[M.didx[d]] for d in days]; idx_cy = [M.cy_pct[M.didx[d]] for d in days]
    rnd_corr = [corr([sim_nav(M, r).get(d) for d in days], realr) for r in rnd_plans]
    rnd_corr = [c for c in rnd_corr if c is not None]

    def cum(xs):
        return round(float(np.prod([1 + (x or 0) for x in xs]) - 1), 4)
    res = {
        "since": since, "until": until, "days": len(days), "K": K, "params_until": ex.get("until"),
        "in_sample_warning": bool(ex.get("until") and since < ex["until"]),
        "buy_hit": {"rule_pick_precision": round(pick_hit / pick_n, 4) if pick_n else None,
                    "real_cover_by_rule_K": round(pick_hit / npos, 4) if npos else None,
                    **{f"real_cover_top{N}": round(hits[N] / npos, 4) if npos else None for N in pool_ns}, "real_new_evaluable": npos},
        "direction": {k: (round(float(np.mean(v)), 3) if v else None) for k, v in dir_ok.items()},
        "timing": {"first_buy_abs_err_min_med": round(float(np.median(t_err_buy)), 1) if t_err_buy else None,
                   "sell_abs_err_min_med": round(float(np.median(t_err_sell)), 1) if t_err_sell else None,
                   "auction_choice_acc": round(auc_ok / auc_n, 3) if auc_n else None,
                   "auction_choice_base": round(float(max(np.mean(auc_real), 1 - np.mean(auc_real))), 3) if auc_real else None, "n_sell": auc_n},
        "nav": {"corr_rule_vs_real": corr(sim_series, realr), "corr_exec_layer(real_picks+rule_exit)_vs_real": corr(exe_series, realr),
                "ablation_real_picks_exit_at_dayavg_vs_real": corr(exe_avg, realr), "cum_ablation_exit_dayavg": cum(exe_avg),
                "corr_random_pool200_vs_real_mean": round(float(np.mean(rnd_corr)), 3) if rnd_corr else None,
                "corr_sh_index_vs_real": corr(idx_sh, realr), "corr_cy_index_vs_real": corr(idx_cy, realr),
                "cum_real": cum(realr), "cum_rule": cum(sim_series), "cum_exec_layer": cum(exe_series)},
        "daily": rows_log,
    }
    return res


# ====================================================================================
# 5. 分析各节
# ====================================================================================
def chi2_uniform(counts):
    c = np.asarray(counts, float)
    e = c.sum() / len(c)
    chi = float(((c - e) ** 2 / e).sum())
    df = len(c) - 1
    # Wilson-Hilferty 近似 p 值
    z = ((chi / df) ** (1 / 3) - (1 - 2 / (9 * df))) / math.sqrt(2 / (9 * df))
    p = 0.5 * math.erfc(z / math.sqrt(2))
    return round(chi, 1), df, round(p, 4)


def frac_label(r):
    for nm, f in (("1/5", 0.2), ("1/4", 0.25), ("1/3", 1 / 3), ("1/2", 0.5), ("全仓", 1.0)):
        if f - 0.015 <= r <= f + 0.006:
            return nm
    return None


def cash_orders(mt, real):
    """按可用资金推算每笔买单(同票 30 秒内连续腿并为一单)占当时可用资金比例"""
    days = sorted(real)
    prev = {days[k]: days[k - 1] for k in range(1, len(days))}
    nav = json.loads((BASE / "nav_daily.json").read_text(encoding="utf-8"))["ex_data"]["index_list"]
    asset = {f"{x['date'][:4]}-{x['date'][4:6]}-{x['date'][6:]}": float(x["asset"]) for x in nav}
    out = []
    for d in days:
        p = prev.get(d)
        if not p or p not in asset or not real[p].get("pos"):
            continue
        cash = asset[p] * (1 - real[p]["pos"]["sum_pct"])
        orders = []
        for t in sorted(mt.byday.get(d, []), key=lambda t: t["trans_date"]):
            amt = float(t.get("trans_amount") or 0)
            ts = sec_of(t["trans_date"][11:19])
            if t["op"] == "2":
                orders.append(["S", t["stock_code"], amt, ts]); continue
            if orders and orders[-1][0] == "B" and orders[-1][1] == t["stock_code"] and ts - orders[-1][3] <= 30:
                orders[-1][2] += amt; orders[-1][3] = ts
            else:
                orders.append(["B", t["stock_code"], amt, ts])
        k = 0
        for o in orders:
            if o[0] == "S":
                cash += o[2]; continue
            if cash > 1000:
                out.append({"date": d, "code": o[1], "ratio": o[2] / cash, "seq": k, "label": frac_label(o[2] / cash)})
            k += 1
            cash -= o[2]
    return out


def sec_programmatic(M, mt, real):
    legs = mt.legs
    A = [t for t in legs if len(t["stock_code"]) == 6]
    R = {}
    b = [t for t in A if t["op"] == "1" and t["trans_date"][11:16] >= "09:31"]
    R["buy_legs_cont"] = len(b)
    R["sec_chi2"] = chi2_uniform(np.bincount([int(t["trans_date"][17:19]) for t in b], minlength=60))
    R["min_of_hour_chi2"] = chi2_uniform(np.bincount([int(t["trans_date"][14:16]) for t in b], minlength=60))
    R["min_mod5"] = np.bincount([int(t["trans_date"][14:16]) % 5 for t in b], minlength=5).tolist()
    R["min_mod5_chi2"] = chi2_uniform(R["min_mod5"])
    fb = [real[d]["first_buy"] for d in sorted(real) if real[d]["first_buy"]]
    R["first_buy_top"] = Counter(x[:5] for x in fb).most_common(8)
    R["first_buy_hour"] = dict(Counter(x[:2] for x in fb))
    fbm = [trade_minute(x) for x in fb if x >= "09:30:00"]
    R["first_buy_q"] = [minute_to_hhmm(q) for q in np.percentile(fbm, [10, 25, 50, 75, 90])]
    # 卖→首买间隔
    gaps = []
    for d in sorted(real):
        ts = sorted(mt.byday.get(d, []), key=lambda t: t["trans_date"])
        bs = [sec_of(t["trans_date"][11:19]) for t in ts if t["op"] == "1"]
        ss = [sec_of(t["trans_date"][11:19]) for t in ts if t["op"] == "2"]
        if bs and ss and any(s < bs[0] for s in ss):
            gaps.append((bs[0] - max(s for s in ss if s < bs[0])) / 60)
    R["sell_to_first_buy_min_q"] = np.percentile(gaps, [10, 25, 50, 75, 90]).round(1).tolist()
    R["sell_to_first_buy_lt1min"] = round(float(np.mean(np.array(gaps) < 1)), 3)
    # 09:30 那一分钟卖出的秒分布
    s930 = [int(t["trans_date"][17:19]) for t in A if t["op"] == "2" and t["trans_date"][11:16] == "09:30"]
    R["sell_0930_sec5"] = np.bincount(np.array(s930) // 5, minlength=12).tolist()
    # 同票同向相邻腿间隔 & 同秒簇
    grp = defaultdict(list)
    for t in A:
        grp[(t["trans_date"][:10], t["stock_code"], t["op"])].append(sec_of(t["trans_date"][11:19]))
    g = np.array([b2 - a2 for v in grp.values() for a2, b2 in zip(sorted(v), sorted(v)[1:])])
    R["leg_gap_s_q"] = np.percentile(g, [10, 25, 50, 75, 90]).round(0).tolist() if len(g) else None
    R["leg_gap_le3s"] = round(float(np.mean(g <= 3)), 3) if len(g) else None
    R["legs_per_event"] = dict(sorted(Counter(min(len(v), 6) for v in grp.values()).items()))
    # 多票同时下单: 同日同方向相邻两条腿属于不同股票时的间隔
    multi = {}
    for op, side in (("1", "买"), ("2", "卖")):
        tot = le5 = same = auc = 0
        for d, ts in mt.byday.items():
            x = sorted([t for t in ts if t["op"] == op and len(t["stock_code"]) == 6], key=lambda t: t["trans_date"])
            for a_, b_ in zip(x, x[1:]):
                if a_["stock_code"] != b_["stock_code"]:
                    tot += 1
                    g_ = sec_of(b_["trans_date"][11:19]) - sec_of(a_["trans_date"][11:19])
                    le5 += g_ <= 5; same += g_ == 0; auc += g_ <= 5 and a_["trans_date"][11:19] <= "09:25:59"
        multi[side] = {"异票相邻对": tot, "≤5秒": le5, "同秒": same, "其中竞价": auc}
    R["multi_stock"] = multi
    # 数量: 分板块整手
    ev = defaultdict(list)
    for t in A:
        ev[(t["trans_date"][:10], t["stock_code"], t["op"])].append(int(float(t.get("trans_count") or 0)))
    qb = {}
    for nm, pref in (("科创板", ("688", "689")), ("创业板", ("300", "301")), ("主板", ("60", "00"))):
        for op, side in (("1", "买"), ("2", "卖")):
            x = [sum(v) for (d, c, o), v in ev.items() if o == op and c.startswith(pref)]
            qb[f"{nm}{side}"] = (len(x), round(float(np.mean([q % 100 == 0 for q in x])), 3) if x else None)
    R["round_lot"] = qb
    # 资金比例
    co = cash_orders(mt, real)
    lab = Counter(o["label"] or "其他" for o in co)
    R["cash_frac_labels"] = dict(lab)
    R["cash_frac_share"] = round(1 - lab["其他"] / max(len(co), 1), 3)
    R["cash_ratio_hist_005"] = np.histogram([o["ratio"] for o in co], bins=np.arange(0, 1.1001, 0.05))[0].tolist()
    # 价格整数位(连续竞价成交 vs 同票当日分钟线收盘整数位基线)
    isint = lambda p: abs(p - round(p)) < 0.0005
    pr = {}
    for op, side in (("1", "买"), ("2", "卖")):
        o, bb = [], []
        for t in A:
            if t["op"] != op or t["trans_date"][11:19] <= "09:25:59":
                continue
            bars = minute_bars(t["trans_date"][:10], t["stock_code"])
            if not bars:
                continue
            o.append(isint(float(t["trans_price"]))); bb.append(np.mean([isint(x["close"]) for x in bars]))
        pr[side] = {"n": len(o), "int_obs": round(float(np.mean(o)), 3) if o else None, "int_base": round(float(np.mean(bb)), 3) if bb else None}
    R["int_price"] = pr
    # 价格相对昨收/开盘的固定偏移? (新开仓首腿)
    offs = []
    for e in mt.buys:
        if not e["new_open"] or e["row"] is None:
            continue
        s = mf.symbol_of(e["code"]); j = M.sidx.get(s) if s else None
        if j is None or not np.isfinite(M.PC[e["row"], j]):
            continue
        offs.append((e["vwap"] / M.PC[e["row"], j] - 1, e["vwap"] / M.O[e["row"], j] - 1))
    offs = np.array(offs)
    R["buy_vs_pc_q"] = (np.percentile(offs[:, 0], [10, 25, 50, 75, 90]) * 100).round(2).tolist()
    R["buy_vs_open_q"] = (np.percentile(offs[:, 1], [10, 25, 50, 75, 90]) * 100).round(2).tolist()
    R["buy_vs_pc_mode_share"] = round(float(max(np.histogram(offs[:, 0], bins=np.arange(-0.1, 0.1001, 0.0025))[0]) / len(offs)), 3)
    # 交易日覆盖
    navdays = [d for d in real if real[d].get("nav_r") is not None]
    R["trade_day_share"] = round(sum(1 for d in navdays if mt.byday.get(d)) / max(len(navdays), 1), 3)
    return R


def prog_probability(P, SEL, TRIG):
    """程序化可能性: 主观似然比 × 证据(可在此改数) → 归一后验; 假设互斥穷尽"""
    H = ["全自动程序(选股+下单都由程序)", "半自动(模型/选股器出信号 + 人工在App里下单)", "纪律化人工超短(主观选股 + 机械化出场/仓位)", "其他/证据不足"]
    ev = []
    ev.append(("出场高度机械: 隔夜仓 ≤09:35 卖出占比 %.0f%%, 不论盈亏" % (P["sell_le935"] * 100), [1.3, 1.2, 1.1, 0.8]))
    sp = P["sec_chi2"][2]
    ev.append(("成交秒均匀(χ² p=%.2f), 无固定时刻/整点批量" % sp, [0.6, 1.0, 1.1, 1.0] if sp > 0.05 else [1.5, 1.1, 0.8, 1.0]))
    mb = P["multi_stock"]["买"]
    ev.append(("异票买单从不同时(≤5 秒 %d/%d 对), 一只一只买" % (mb["≤5秒"], mb["异票相邻对"]), [0.4, 1.0, 1.1, 1.0] if mb["≤5秒"] <= 0.02 * max(mb["异票相邻对"], 1) else [1.0, 1.0, 1.0, 1.0]))
    ev.append(("首买 %s~%s 分散, 卖完到首买中位 %.0f 分钟, <1 分钟仅 %.0f%%" % (P["first_buy_q"][1], P["first_buy_q"][3], P["sell_to_first_buy_min_q"][2], P["sell_to_first_buy_lt1min"] * 100),
               [0.6, 1.0, 1.1, 1.0]))
    fs = P["cash_frac_share"]
    ev.append(("约 %.0f%% 买单=当时可用资金的 1/4、1/3、全仓等整分数(App 仓位按钮签名), 科创板股数随之不规则" % (fs * 100),
               [0.5, 1.5, 1.4, 0.9] if fs >= 0.25 else [1.0, 1.0, 1.0, 1.0]))
    ip = P["int_price"]["卖"]
    ratio = (ip["int_obs"] or 0) / max(ip["int_base"] or 1e-9, 1e-9)
    ev.append(("卖单整数价位 %.1f%% vs 基线 %.1f%%(×%.1f, 人手敲限价的签名); 买单无此偏好" % ((ip["int_obs"] or 0) * 100, (ip["int_base"] or 0) * 100, ratio),
               [0.45, 1.2, 1.3, 1.0] if ratio >= 2 else [1.0, 1.0, 1.0, 1.0]))
    c50 = SEL["test_cover50"]
    ev.append(("选股无法用日线量价复现: 时间外 Top50 覆盖 %.0f%%, 连用当日全天信息(上限)也只 %.0f%%" % (c50 * 100, SEL["oracle_cover50"] * 100),
               [0.6, 0.9, 1.2, 1.1] if SEL["oracle_cover50"] < 0.3 else [1.5, 1.2, 0.7, 1.0]))
    ev.append(("盘中买点无锐利触发条件(时间配对零假设下最强提升 ×%.1f)" % TRIG["max_lift"], [0.6, 0.9, 1.2, 1.0] if TRIG["max_lift"] < 2.5 else [1.4, 1.1, 0.8, 1.0]))
    ev.append(("账户自称「量化短线小号实验」", [1.5, 1.5, 0.6, 1.0]))
    ev.append(("%.0f%% 交易日都出手, 连亏不降仓、9 个月不停机" % (P["trade_day_share"] * 100), [1.3, 1.1, 0.9, 1.0]))
    post = np.ones(len(H)) / len(H)
    for _, lr in ev:
        post = post * np.array(lr)
    post = post / post.sum()
    return {"hyp": H, "post": [round(float(x), 3) for x in post], "evidence": [(t, lr) for t, lr in ev]}


def sec_selection(M, mt, SH, pos):
    tr, te, cut = split_rows(M, pos)
    X, y, w = build_train(M, SH, pos, tr)
    model = LRModel().fit(X, y, w)
    S = {"cut_date": M.dates[cut], "train_days": len(tr), "test_days": len(te), "train_pos": int(y.sum())}
    sc = lambda js, Xd, i: model.score(Xd)
    S["lr_train"] = rank_eval(M, SH, pos, tr, sc)
    S["lr_test"] = rank_eval(M, SH, pos, te, sc, board_cond=True)
    k_amt = FEATS.index("amtrk")
    S["base_prev_amt_test"] = rank_eval(M, SH, pos, te, lambda js, Xd, i: -Xd[:, k_amt])
    rng = np.random.default_rng(SEED)
    S["base_random_test"] = rank_eval(M, SH, pos, te, lambda js, Xd, i: rng.random(len(js)))
    # 上限(含当日全天信息 = 后见之明, 只做诊断): 加 当日涨跌/最高/最低/成交额/额比
    def day_extra(js, i):
        with np.errstate(all="ignore"):
            return np.column_stack([np.clip(M.pct[i, js], -.3, .3), np.clip(M.H[i, js] / M.PC[i, js] - 1, -.3, .3),
                                    np.clip(M.L[i, js] / M.PC[i, js] - 1, -.3, .3), np.log10(M.amt[i, js] + 1),
                                    np.log1p(np.clip(M.amt[i, js] / M.amt[i - 1, js], 0, 20)), np.clip(M.O[i, js] / M.PC[i, js] - 1, -.2, .2)])
    Xo, yo, wo = [], [], []
    rng2 = np.random.default_rng(SEED)
    for i in tr:
        js, Xd = day_features(M, SH, i - 1)
        live = M.has[i, js]; js, Xd = js[live], Xd[live]
        yy = np.isin(js, list(pos[i])).astype(float)
        neg = np.where(yy == 0)[0]; take = rng2.choice(neg, size=min(1500, len(neg)), replace=False)
        idx = np.concatenate([np.where(yy == 1)[0], take])
        Xo.append(np.column_stack([Xd[idx], day_extra(js[idx], i)])); yo.append(yy[idx])
        wo.append(np.where(yy[idx] == 1, 1.0, len(neg) / len(take)))
    om = LRModel().fit(np.vstack(Xo), np.concatenate(yo), np.concatenate(wo))
    S["oracle_test"] = rank_eval(M, SH, pos, te, lambda js, Xd, i: om.score(np.column_stack([Xd, day_extra(js, i)])))
    # 可读的机械池规则(训练窗正样本 P10 门槛), 时间外看覆盖与池子大小
    Xp = []
    for i in tr:
        js, Xd = day_features(M, SH, i - 1)
        for j in pos[i]:
            k = np.where(js == j)[0]
            if len(k):
                Xp.append(Xd[k[0]])
    Xp = np.array(Xp)
    th = {nm: float(np.nanpercentile(Xp[:, FEATS.index(nm)], 10)) for nm in ("lamt", "lpx", "lcap", "r20")}
    th["st"] = 0
    S["pool_rule"] = {"成交额≥(亿)": round(10 ** th["lamt"] / 1e8, 2), "股价≥": round(10 ** th["lpx"], 2), "流通市值≥(亿)": round(10 ** th["lcap"] / 1e8, 1),
                      "20日涨幅≥%": round(th["r20"] * 100, 1), "非ST": True, "板块": "主板/创业板/科创板/ETF"}

    def pool_mask(Xd):
        return ((Xd[:, FEATS.index("lamt")] >= th["lamt"]) & (Xd[:, FEATS.index("lpx")] >= th["lpx"]) & (np.nan_to_num(Xd[:, FEATS.index("lcap")], nan=0) >= th["lcap"])
                & (Xd[:, FEATS.index("r20")] >= th["r20"]) & (Xd[:, FEATS.index("st")] == 0) & (Xd[:, FEATS.index("bse")] == 0))
    for nm, rows in (("train", tr), ("test", te)):
        cov = []; size = []
        for i in rows:
            js, Xd = day_features(M, SH, i - 1)
            live = M.has[i, js]; js, Xd = js[live], Xd[live]
            m = pool_mask(Xd)
            size.append(int(m.sum()))
            sel = set(js[m])
            cov += [j in sel for j in pos[i] if j in set(js)]
        S[f"pool_rule_{nm}"] = {"cover": round(float(np.mean(cov)), 3), "pool_med": int(np.median(size)),
                                "precision": round(float(np.sum(cov)) / max(sum(size), 1), 5)}
    S["pool_plus_lr_test"] = rank_eval(M, SH, pos, te, lambda js, Xd, i: np.where(pool_mask(Xd), model.score(Xd) + 100, model.score(Xd)))
    S["test_cover50"] = S["lr_test"]["cover"][50]
    S["oracle_cover50"] = S["oracle_test"]["cover"][50]
    S["top_weights"] = sorted(zip(FEATS, model.w.round(3).tolist()), key=lambda z: -abs(z[1]))[:12]
    # 资产结构(含港股, 选股不可评估部分)
    S["asset_mix_new_open"] = dict(Counter(mf.asset_class(e["code"]) for e in mt.buys if e["new_open"]))
    return S, model, (tr, te, cut)


def sec_trigger(M, mt):
    """分钟层: 新开仓首腿 vs 同分钟其它股票-日(时间配对零假设)的「刚刚发生」条件"""
    random.seed(SEED)
    first = {}
    for t in sorted(mt.legs, key=lambda t: t["trans_date"]):
        if t["op"] == "1":
            first.setdefault((t["trans_date"][:10], t["stock_code"]), t)
    D = []; n_new_a = 0
    for e in mt.buys:
        if not e["new_open"] or len(e["code"]) != 6:
            continue
        n_new_a += 1
        t = first.get((e["date"], e["code"]))
        bars = minute_bars(e["date"], e["code"])
        s = mf.symbol_of(e["code"]); j = M.sidx.get(s) if s else None
        if not bars or not t or j is None or e["row"] is None or not np.isfinite(M.PC[e["row"], j]):
            continue
        lab = bar_label(t["trans_date"][11:16])
        ks = [k for k, b in enumerate(bars) if b["barTime"][11:16] == lab]
        if not ks:
            continue
        pc = M.PC[e["row"], j]
        c = np.array([b["close"] for b in bars]); h = np.array([b["high"] for b in bars]); lo = np.array([b["low"] for b in bars])
        v = np.array([b["volume"] or 0 for b in bars], float); a = np.array([b["amount"] or 0 for b in bars], float)
        cv, ca = np.cumsum(v), np.cumsum(a)
        vw = np.where(cv > 0, ca / np.maximum(cv, 1), c)
        Hh, Ll = np.maximum.accumulate(h), np.minimum.accumulate(lo)
        o = bars[0]["open"]; p = c / pc - 1; n = len(c)
        m5 = np.r_[np.zeros(5), c[5:] / c[:-5] - 1]
        base = np.array([v[max(0, q - 10):q].mean() if q > 0 else 0 for q in range(n)])
        st = {"涨幅>1%": p > 0.01, "涨幅>2%": p > 0.02, "涨幅>3%": p > 0.03, "涨幅>5%": p > 0.05, "站上均价线": c > vw, "跌破均价1%": c < vw * 0.99,
              "创日内新高": np.r_[False, c[1:] >= Hh[:-1]], "创日内新低": np.r_[False, c[1:] <= Ll[:-1]], "高点回落≥2%": (Hh - c) / Hh >= 0.02,
              "站上开盘价": c > o, "5分钟涨>1%": m5 > 0.01, "5分钟跌>1%": m5 < -0.01, "放量3倍": (v > 3 * np.maximum(base, 1)) & (np.arange(n) > 2)}
        px = float(t["trans_price"]); bk = bars[ks[0]]
        D.append({"k": ks[0], "n": n, "st": st, "p": p, "vsvw": c / vw - 1, "pos_bar": (px - bk["low"]) / (bk["high"] - bk["low"]) if bk["high"] > bk["low"] else 0.5,
                  "pct_at": px / pc - 1, "vs_vwap": px / vw[ks[0]] - 1})

    def trig(s, k, w=2):
        for q in range(max(1, k - w), k + 1):
            if s[q] and not s[q - 1]:
                return True
        return False
    T = {"n_new_open_A": n_new_a, "n_with_minutes": len(D), "coverage": round(len(D) / max(n_new_a, 1), 3), "conds": {}}
    if not D:
        T["max_lift"] = 1.0
        return T
    for nm in D[0]["st"]:
        rg, ng, rt, nt = [], [], [], []
        for a_, x in enumerate(D):
            s = x["st"][nm]; k = min(x["k"], x["n"] - 1)
            rt.append(s[max(k - 1, 0)]); rg.append(trig(s, k))
            for _ in range(20):
                b_ = random.randrange(len(D))
                if b_ == a_:
                    continue
                s2 = D[b_]["st"][nm]; k2 = min(k, len(s2) - 1)
                nt.append(s2[max(k2 - 1, 0)]); ng.append(trig(s2, k2))
        T["conds"][nm] = {"状态成立_真": round(float(np.mean(rt)), 3), "状态成立_配对": round(float(np.mean(nt)), 3),
                          "刚触发_真": round(float(np.mean(rg)), 3), "刚触发_配对": round(float(np.mean(ng)), 3),
                          "提升": round(float(np.mean(rg)) / max(float(np.mean(ng)), 1e-9), 2)}
    T["max_lift"] = max(v["提升"] for v in T["conds"].values())
    T["best"] = sorted(T["conds"].items(), key=lambda kv: -kv[1]["提升"])[:3]
    ks = np.array([x["k"] for x in D])
    T["buy_minute_q"] = [minute_to_hhmm(q) for q in np.percentile(ks, [10, 25, 50, 75, 90])]
    T["pct_at_buy_q"] = (np.percentile([x["pct_at"] for x in D], [10, 25, 50, 75, 90]) * 100).round(2).tolist()
    T["vs_vwap_q"] = (np.percentile([x["vs_vwap"] for x in D], [10, 25, 50, 75, 90]) * 100).round(2).tolist()
    T["pos_in_bar_q"] = np.percentile([x["pos_bar"] for x in D], [10, 25, 50, 75, 90]).round(2).tolist()
    best_nm = T["best"][0][0]
    T["best_rule_hit"] = T["conds"][best_nm]["刚触发_真"]
    return T


def sec_sell(M, mt):
    def bucket(t):
        if t <= "09:25:59":
            return "竞价09:25"
        if t < "09:31:00":
            return "09:30~09:31"
        if t < "09:35:00":
            return "09:31~09:35"
        if t < "10:00:00":
            return "09:35~10:00"
        if t < "11:30:01":
            return "上午其余"
        if t < "14:30:00":
            return "下午"
        return "尾盘≥14:30"
    rows = []
    for e in mt.sells:
        s = mf.symbol_of(e["code"]); j = M.sidx.get(s) if s else None; i = e["row"]
        gap = float(M.O[i, j] / M.PC[i, j] - 1) if (j is not None and i is not None and np.isfinite(M.O[i, j])) else None
        cost = e["matched_cost"] / e["matched_q"] if e["matched_q"] else None
        hi = float(M.H[i, j]) if (j is not None and i is not None and np.isfinite(M.H[i, j])) else None
        lo = float(M.L[i, j]) if (j is not None and i is not None and np.isfinite(M.L[i, j])) else None
        op = float(M.O[i, j]) if gap is not None else None
        rows.append(dict(b=bucket(e["t_first"]), hk=len(e["code"]) == 5, hd=e["hold_days"], pnl=e.get("pnl"), gap=gap, cost=cost, hi=hi, lo=lo,
                         op=op, px=e["vwap"], date=e["date"]))
    S = {"n": len(rows), "hold_days": dict(Counter(str(r["hd"]) for r in rows))}
    ov = [r for r in rows if not r["hk"] and r["hd"] is not None and r["hd"] >= 1]
    S["A_overnight_n"] = len(ov)
    S["A_overnight_bucket"] = dict(Counter(r["b"] for r in ov))
    S["sell_le935"] = round(sum(r["b"] in ("竞价09:25", "09:30~09:31", "09:31~09:35") for r in ov) / len(ov), 3)
    S["sell_le1000"] = round(sum(r["b"] in ("竞价09:25", "09:30~09:31", "09:31~09:35", "09:35~10:00") for r in ov) / len(ov), 3)
    S["sell_tail"] = round(sum(r["b"] == "尾盘≥14:30" for r in rows) / len(rows), 3)
    S["hk_bucket"] = dict(Counter(r["b"] for r in rows if r["hk"]))
    S["same_day_T"] = sum(1 for r in rows if r["hd"] == 0)
    by = {}
    for b in ("竞价09:25", "09:30~09:31", "09:31~09:35", "09:35~10:00", "上午其余", "下午"):
        g = [r for r in ov if r["b"] == b and r["gap"] is not None]
        if g:
            by[b] = {"n": len(g), "开盘缺口中位%": round(float(np.median([r["gap"] for r in g])) * 100, 2),
                     "盈亏中位%": round(float(np.median([r["pnl"] for r in g if r["pnl"] is not None])) * 100, 2),
                     "高开占比": round(float(np.mean([r["gap"] > 0 for r in g])), 2)}
    S["bucket_stats"] = by
    gg = [(r["b"] == "竞价09:25", r["gap"]) for r in ov if r["gap"] is not None]
    S["auction_by_gap"] = {}
    for lo_, hi_ in ((-1, -0.03), (-0.03, -0.01), (-0.01, 0), (0, 0.01), (0.01, 0.03), (0.03, 1)):
        x = [a for a, g in gg if lo_ <= g < hi_]
        if x:
            S["auction_by_gap"][f"[{lo_:+.0%},{hi_:+.0%})"] = (len(x), round(float(np.mean(x)), 2))
    # 价格型规则命中率: 固定止盈/止损 x% 在次日盘中被触发时, 真人是否恰好在该价附近卖
    tp = {}
    for x in (0.01, 0.02, 0.03, 0.05, 0.08):
        for kind in ("止盈", "止损"):
            trig, hit = 0, 0
            for r in ov:
                if not r["cost"] or r["hi"] is None:
                    continue
                lvl = r["cost"] * (1 + x if kind == "止盈" else 1 - x)
                touched = (r["op"] < lvl <= r["hi"]) if kind == "止盈" else (r["lo"] <= lvl < r["op"])
                if touched:
                    trig += 1
                    hit += abs(r["px"] / lvl - 1) <= 0.005
            tp[f"{kind}{x:.0%}"] = (trig, round(hit / trig, 3) if trig else None)
    S["price_rule_hit"] = tp
    pn = [r["pnl"] for r in ov if r["pnl"] is not None]
    S["pnl_q"] = (np.percentile(pn, [10, 25, 50, 75, 90]) * 100).round(2).tolist()
    S["win_rate"] = round(float(np.mean(np.array(pn) > 0)), 3)
    # 时间止损: 规则「次日开盘窗一律卖出」的逐笔命中
    S["time_exit_rule_hit"] = {"≤09:35": S["sell_le935"], "≤10:00": S["sell_le1000"], "持有恰 1 个交易日": round(float(np.mean([r["hd"] == 1 for r in ov])), 3)}
    return S


def sec_sizing(M, mt, real):
    co = cash_orders(mt, real)
    Z = {"orders": len(co), "labels": dict(Counter(o["label"] or "其他" for o in co))}
    seqs = defaultdict(list)
    for o in co:
        seqs[o["date"]].append(o["label"] or "·")
    Z["top_sequences"] = Counter(" ".join(v) for v in seqs.values()).most_common(10)
    Z["last_order_full"] = round(float(np.mean([v[-1] == "全仓" for v in seqs.values() if v])), 3)
    nn = Counter(len(real[d]["new_open"]) for d in real if real[d]["new_open"])
    Z["names_per_day"] = dict(sorted(nn.items()))
    hold = [len(real[d]["pos"]["codes"]) for d in real if real[d].get("pos") and real[d]["pos"]["codes"]]
    Z["hold_names_q"] = np.percentile(hold, [10, 25, 50, 75, 90]).tolist() if hold else None
    sp = [real[d]["pos"]["sum_pct"] for d in real if real[d].get("pos")]
    Z["close_pos_mean"] = round(float(np.mean(sp)), 3)
    Z["close_pos_ge90"] = round(float(np.mean(np.array(sp) >= 0.9)), 3)
    # 当日权重 vs 1/n
    w_by_n = defaultdict(list)
    for d in real:
        a = real[d]["new_amt"]
        if a:
            tot = sum(a.values())
            for v in a.values():
                w_by_n[len(a)].append(v / tot)
    Z["weight_by_n"] = {n: {"中位": round(float(np.median(v)), 2), "P25": round(float(np.percentile(v, 25)), 2), "P75": round(float(np.percentile(v, 75)), 2), "1/n": round(1 / n, 2), "笔": len(v)}
                        for n, v in sorted(w_by_n.items()) if len(v) >= 5}
    # 回撤后是否降仓: 日收益 ≤-3% 的次日收盘仓位 vs 常态
    days = sorted(d for d in real if real[d].get("nav_r") is not None and real[d].get("pos"))
    after = [real[days[k + 1]]["pos"]["sum_pct"] for k in range(len(days) - 1) if real[days[k]]["nav_r"] <= -0.03]
    Z["pos_after_loss3"] = (len(after), round(float(np.mean(after)), 3) if after else None)
    # 同票同日加仓: 加仓价相对首腿
    adds = []
    for e in mt.buys:
        if e["nlegs"] < 2:
            continue
        legs = sorted([t for t in mt.byday[e["date"]] if t["stock_code"] == e["code"] and t["op"] == "1"], key=lambda t: t["trans_date"])
        if len(legs) >= 2 and sec_of(legs[-1]["trans_date"][11:19]) - sec_of(legs[0]["trans_date"][11:19]) > 300:
            adds.append(float(legs[-1]["trans_price"]) / float(legs[0]["trans_price"]) - 1)
    Z["adds_n"] = len(adds)
    Z["adds_px_vs_first_q"] = (np.percentile(adds, [10, 25, 50, 75, 90]) * 100).round(2).tolist() if adds else None
    Z["adds_up_share"] = round(float(np.mean(np.array(adds) > 0)), 3) if adds else None
    return Z


def best_split(x, minseg=15):
    x = np.asarray(x, float)
    m = np.isfinite(x)
    idx = np.where(m)[0]
    v = x[m]
    best = (0, None)
    for k in range(minseg, len(v) - minseg):
        a, b = v[:k], v[k:]
        se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)) + 1e-12
        t = abs(a.mean() - b.mean()) / se
        if t > best[0]:
            best = (t, idx[k])
    return best


def sec_regime(M, mt, real, SH, pos, model_first):
    days = [d for d in sorted(real) if real[d].get("new_open") or mt.byday.get(d)]
    met = defaultdict(list)
    for d in days:
        R = real[d]; new = R["new_open"]
        met["当日新开只数"].append(len(new))
        met["首买分钟"].append(trade_minute(R["first_buy"]) if R["first_buy"] and R["first_buy"] >= "09:30:00" else np.nan)
        amt = R["new_amt"]; tot = sum(amt.values()) or np.nan
        met["港股金额占比"].append(sum(v for c, v in amt.items() if len(c) == 5) / tot if amt else np.nan)
        met["科创金额占比"].append(sum(v for c, v in amt.items() if c.startswith("688")) / tot if amt else np.nan)
        lp, r20 = [], []
        for c in new:
            s = mf.symbol_of(c); j = M.sidx.get(s) if s else None
            i = M.didx.get(d)
            if j is not None and i:
                if np.isfinite(M.C[i - 1, j]):
                    lp.append(math.log10(M.C[i - 1, j]))
                if np.isfinite(M.ret[20][i - 1, j]):
                    r20.append(M.ret[20][i - 1, j])
        met["新开股价log10"].append(np.median(lp) if lp else np.nan)
        met["新开前20日涨幅"].append(np.median(r20) if r20 else np.nan)
        fs = R["first_sell"]
        a6 = [t <= "09:25:59" for c, t in fs.items() if len(c) == 6]
        met["竞价卖出占比"].append(np.mean(a6) if a6 else np.nan)
        met["收盘仓位"].append(R["pos"]["sum_pct"] if R.get("pos") else np.nan)
    out = {"metrics": {}, "monthly": {}}
    for k, v in met.items():
        t, at = best_split(v)
        if at is not None:
            a = np.array(v, float)
            out["metrics"][k] = {"t": round(float(t), 2), "split": days[at], "before": round(float(np.nanmean(a[:at])), 3), "after": round(float(np.nanmean(a[at:])), 3)}
    mon = defaultdict(lambda: defaultdict(list))
    for k, v in met.items():
        for d, x in zip(days, v):
            mon[d[:7]][k].append(x)
    for m in sorted(mon):
        out["monthly"][m] = {k: (round(float(np.nanmean(v)), 3) if np.isfinite(np.nanmean(np.array(v, float))) else None) for k, v in mon[m].items()}
    # 选股模型漂移: 用前 50% 训练的模型逐月看 Top50 覆盖
    rows = sorted(pos)
    half = rows[len(rows) // 2]
    X, y, w = build_train(M, SH, pos, [r for r in rows if r < half])
    mh = LRModel().fit(X, y, w)
    drift = {}
    bym = defaultdict(list)
    for r in rows:
        bym[M.dates[r][:7]].append(r)
    for m, rs in sorted(bym.items()):
        e = rank_eval(M, SH, pos, rs, lambda js, Xd, i: mh.score(Xd), Ns=(50,))
        drift[m] = {"cover50": e["cover"][50], "pos": e["pos"], "in_train": rs[0] < half}
    out["drift"] = drift
    strong = sorted([(v["t"], k, v["split"]) for k, v in out["metrics"].items() if v["t"] >= 3.5], reverse=True)
    out["strong_splits"] = strong
    # 聚类: ±7 交易日内 ≥2 个指标同时切换
    cl = []
    for t, k, s in strong:
        for c in cl:
            if abs(M.didx.get(s, 0) - M.didx.get(c["date"], 0)) <= 7:
                c["metrics"].append(k); break
        else:
            cl.append({"date": s, "metrics": [k]})
    out["switch_candidates"] = cl
    return out


# ====================================================================================
# 6. 报告
# ====================================================================================
def pct(x, nd=0):
    return "—" if x is None else f"{x * 100:.{nd}f}%"


def write_report(A):
    P, SEL, TRIG, SELL, SZ, REG, RP, EX, PR = (A[k] for k in ("prog", "sel", "trig", "sell", "size", "regime", "replay", "exec", "prob"))
    L = []
    a = L.append
    a("# 逆向工程: 「量化短线小号实验」(lianghuaxiaohao) 的程序还原与还原度（2026-10-16）")
    a("")
    a(f"> 生成: {A['generated']} | 脚本: `scripts/tzzb/reverse_lianghua.py`(零 token, 只读) | 数据窗: {A['window'][0]} ~ {A['window'][1]} | 成交腿 {A['n_legs']} | 新开仓事件 {A['n_new_open']}")
    a(f"> 时间外切分: 前 70% 买入日定规则(截至 {SEL['cut_date']} 前, {SEL['train_days']} 日), 后 30% 验证({SEL['test_days']} 日)。分钟层完成度: 新开仓 A 股 {TRIG['n_with_minutes']}/{TRIG['n_new_open_A']} = {pct(TRIG['coverage'])} 有成交当日分钟线(后台补抓已跑完)。")
    a(f"> 口径修正(重要): 行情库科创板 10/09 前 volume 系统性 ×100, 本脚本已按票除回(修正 {A['vfix_n']} 只); mentor_fingerprint.py / fingerprint.md 的「成交额/换手」类特征对科创票仍是放大值(未改原文件, 建议修)。")
    a("")
    a("## 结论速览")
    a("")
    a("| 问题 | 结论 | 关键证据 |")
    a("| --- | --- | --- |")
    hp = sorted(zip(PR["hyp"], PR["post"]), key=lambda z: -z[1])
    a(f"| 1 是否程序化 | 最可能=「{hp[0][0]}」{pct(hp[0][1])}; 「{hp[1][0]}」{pct(hp[1][1])} | 出场/仓位高度机械, 但下单量是 App 仓位按钮式整分数、卖单偏好整数价、秒级无规律 |")
    a(f"| 2 选股 | **不能用日线量价机械复现**: 时间外 Top{RP['K']} 命中 {pct(SEL['lr_test']['cover'][2])}, Top50 覆盖 {pct(SEL['lr_test']['cover'][50])}(比随机 {pct(SEL['base_random_test']['cover'][50])} 强 ×{SEL['lr_test']['lift'][50]}, 但离「复现」很远); 连当日全天信息也只到 {pct(SEL['oracle_test']['cover'][50])} | 只能还原「偏好/候选池」: 高流动性/高价/高换手/20 日强势的创业板-科创-主板票 |")
    a(f"| 3 买点 | 首买中位 {EX['first_buy_hhmm']}(P25~P75 {P['first_buy_q'][1]}~{P['first_buy_q'][3]}); 无锐利盘中触发(最强「{TRIG['best'][0][0]}」提升 ×{TRIG['best'][0][1]['提升']}, 只覆盖 {pct(TRIG['best'][0][1]['刚触发_真'])}) | 买价相对昨收/开盘/均价无固定偏移 |")
    a(f"| 4 卖出 | **时间止损=次日开盘窗清仓**: 隔夜仓 ≤09:35 卖出 {pct(SELL['sell_le935'])}, ≤10:00 {pct(SELL['sell_le1000'])}; 竞价 vs 连续竞价由开盘缺口决定(缺口≥{EX['auction_gap_th']:+.2%} 走竞价, 训练窗准确率 {pct(EX['auction_rule_acc'])}/基线 {pct(EX['auction_base_acc'])}; 时间外 {pct(RP['timing']['auction_choice_acc'])}/基线 {pct(RP['timing']['auction_choice_base'])}) | 不是固定止盈/止损: 3% 以上档位命中 ≤10%, 1% 档的命中多因开盘价本就落在成本附近 |")
    a(f"| 5 仓位 | 收盘平均仓位 {pct(SZ['close_pos_mean'])}, ≥90% 的日子 {pct(SZ['close_pos_ge90'])}; 每日新开中位 {EX['K']} 只; {pct(P['cash_frac_share'])} 的买单=可用资金 1/4、1/3、全仓等整分数 | 大亏(≤-3%)次日仓位 {pct(SZ['pos_after_loss3'][1])}, 不降仓 |")
    sw = REG["switch_candidates"]
    a(f"| 6 版本切换 | {('疑似切换日: ' + ', '.join(c['date'] + '(' + '/'.join(c['metrics']) + ')' for c in sw[:4])) if sw else '未见显著切换'} | 见第六节 |")
    a("")
    a("### 时间外还原度(回放 %s ~ %s, %d 个交易日, 参数只用此前数据)" % (RP["since"], RP["until"], RP["days"]))
    a("")
    a("| 维度 | 指标 | 数值 |")
    a("| --- | --- | --- |")
    bh, dr, tm, nv = RP["buy_hit"], RP["direction"], RP["timing"], RP["nav"]
    a(f"| 买入票 | 规则 Top{RP['K']} 命中真人新开仓(覆盖率) | {pct(bh['real_cover_by_rule_K'], 1)} |")
    a(f"| 买入票 | 规则 Top{RP['K']} 精确率 | {pct(bh['rule_pick_precision'], 1)} |")
    a(f"| 买入票 | 真人新开仓落在规则 Top10 / Top50 / Top200 | {pct(bh['real_cover_top10'], 1)} / {pct(bh['real_cover_top50'], 1)} / {pct(bh['real_cover_top200'], 1)} |")
    a(f"| 方向 | 「昨仓次日 10:00 前卖出 ≥90%」一致率 | {pct(dr['sell_all_open'])} |")
    a(f"| 方向 | 「当日有新开仓」一致率 | {pct(dr['buy_new'])} |")
    a(f"| 仓位 | 「收盘满仓(≥90%)」一致率 | {pct(dr['full_pos'])} |")
    a(f"| 仓位 | 收盘持股只数 = K({RP['K']}) 一致率 | {pct(dr['n_names'])} |")
    a(f"| 时点 | 首买时刻绝对误差中位(分钟) | {tm['first_buy_abs_err_min_med']} |")
    a(f"| 时点 | 卖出时刻绝对误差中位(分钟) / 竞价与否判对率(全猜多数类基线) | {tm['sell_abs_err_min_med']} / {pct(tm['auction_choice_acc'])}({pct(tm['auction_choice_base'])}) |")
    a(f"| 净值 | 规则模拟 vs 真人 日收益相关 | {nv['corr_rule_vs_real']} |")
    a(f"| 净值 | 对照: 池内随机 {RP['K']} 只 / 上证 / 创业板指 vs 真人 | {nv['corr_random_pool200_vs_real_mean']} / {nv['corr_sh_index_vs_real']} / {nv['corr_cy_index_vs_real']} |")
    a(f"| 净值 | 执行层还原(真人选的票 + 规则化买卖时点) vs 真人 | {nv['corr_exec_layer(real_picks+rule_exit)_vs_real']} |")
    a(f"| 净值 | 区间累计: 真人 / 规则模拟 / 执行层还原 | {pct(nv['cum_real'], 1)} / {pct(nv['cum_rule'], 1)} / {pct(nv['cum_exec_layer'], 1)} |")
    a(f"| 净值 | 消融: 真人选的票但次日按全天均价卖(拿掉开盘窗卖出) vs 真人 / 累计 | {nv['ablation_real_picks_exit_at_dayavg_vs_real']} / {pct(nv['cum_ablation_exit_dayavg'], 1)} |")
    a("")
    a("读法:")
    a(f"- 「执行层」(次日开盘窗清仓、满仓、每日新开 2~3 只、09:3x~10:00 买)可以规则化: 方向/仓位一致率 79%~98%, 卖出时刻误差中位 {tm['sell_abs_err_min_med']} 分钟, 首买误差中位 {tm['first_buy_abs_err_min_med']} 分钟。")
    a(f"- 「选股层」规则版 Top{RP['K']} 时间外一只都没对上; 规则模拟净值与真人相关 {nv['corr_rule_vs_real']}, **低于**池内随机挑票({nv['corr_random_pool200_vs_real_mean']})和指数({nv['corr_cy_index_vs_real']}) → 相关只来自共同的大盘 beta, 规则版收益也和真人背离(累计 {pct(nv['cum_rule'], 1)} vs {pct(nv['cum_real'], 1)})。")
    a(f"- 「执行层还原」相关 {nv['corr_exec_layer(real_picks+rule_exit)_vs_real']} 看着高, 但消融(把开盘窗卖出换成全天均价卖)几乎不变({nv['ablation_real_picks_exit_at_dayavg_vs_real']}) → 净值几乎全部由**选了哪只票**决定, 这个数只证明模拟器记账对, 不证明卖出规则; 卖出规则的证据是上面的时点/方向一致率。")
    a("- 一句话: 他的程序(或纪律)= 「选股黑箱 + 机械执行壳」; 壳能 90% 复制, 黑箱复制不了, 而收益几乎全在黑箱里。")
    a("")
    # ---------- 一 ----------
    a("## 一、是不是程序化")
    a("")
    a("### 1.1 时间戳")
    a(f"- 连续竞价买腿 {P['buy_legs_cont']} 条: 成交秒(0~59)均匀性 χ²={P['sec_chi2'][0]}(df={P['sec_chi2'][1]}, p={P['sec_chi2'][2]}) → **没有固定秒**; 分钟(0~59) χ²={P['min_of_hour_chi2'][0]}(p={P['min_of_hour_chi2'][2]}); 分钟 mod5 分布 {P['min_mod5']}(p={P['min_mod5_chi2'][2]})。")
    a(f"- 首笔买入时刻: 小时分布 {P['first_buy_hour']}; 分位(P10/P25/中位/P75/P90) {' / '.join(P['first_buy_q'])}; 最常见分钟 {P['first_buy_top'][:5]} → 没有「定时一刻批量下单」。")
    a(f"- 卖完旧仓到首笔新买的间隔(分钟) P10/P25/中位/P75/P90 = {P['sell_to_first_buy_min_q']}, 1 分钟内衔接仅 {pct(P['sell_to_first_buy_lt1min'], 1)}。程序的「卖完即买」通常在秒级。")
    a(f"- 09:30 那一分钟的卖出腿按 5 秒分桶: {P['sell_0930_sec5']} —— 第一桶(09:30:00~04)集中=开盘前预挂单, 之后平缓衰减到 09:34, 像逐只手动处理。")
    ms = P["multi_stock"]
    a(f"- **多票同时下单**: 同日相邻两笔买入属于不同股票的 {ms['买']['异票相邻对']} 对里, 间隔 ≤5 秒的 {ms['买']['≤5秒']} 对 → 从不一篮子同时买; 卖出 {ms['卖']['异票相邻对']} 对里 ≤5 秒 {ms['卖']['≤5秒']} 对(其中 {ms['卖']['其中竞价']} 对是 09:25 竞价撮合, 即盘前预挂的卖单一起成交)。程序化组合调仓通常是多票秒级同时下单。")
    a(f"- 同票同向相邻腿间隔(秒) P10/P25/中位/P75/P90 = {P['leg_gap_s_q']}, ≤3 秒的仅 {pct(P['leg_gap_le3s'])}; 每(日,票,方向)腿数分布 {P['legs_per_event']}。")
    a("")
    a("### 1.2 数量")
    a("| 板块·方向 | 事件数 | 合计股数为 100 整数倍 |")
    a("| --- | --- | --- |")
    for k, (n, s) in P["round_lot"].items():
        a(f"| {k} | {n} | {pct(s)} |")
    a(f"- 科创板允许 200 股以上按 1 股递增: 他的科创买单 {pct(1 - (P['round_lot']['科创板买'][1] or 0))} 是不规则股数(如 1095/444/860)→ 股数是**按金额算出来的**, 不是手敲整手。")
    a(f"- 每笔买单 ÷ 当时可用资金: {P['cash_frac_labels']}(其他=不落在整分数±1.5%); 落在 1/5、1/4、1/3、1/2、全仓 的合计 {pct(P['cash_frac_share'])}。0.05 分箱直方图 {P['cash_ratio_hist_005']}: 尖峰在 0.20~0.25(1/4 仓按钮, 取整后略低于 0.25) 与 0.95~1.00(全仓)。")
    a("  这是同花顺/券商 App 「1/4 仓、1/3 仓、全仓」快捷按钮的典型签名: 按**剩余可用资金**的分数下单。量化框架(QMT/PTrade 等)更常见的是按总资产目标权重下单。")
    a("")
    a("### 1.3 价格")
    ip = P["int_price"]
    a(f"- 整数价位成交: 卖单 {pct(ip['卖']['int_obs'], 1)} vs 同票当日分钟收盘整数位基线 {pct(ip['卖']['int_base'], 1)}(n={ip['卖']['n']}); 买单 {pct(ip['买']['int_obs'], 1)} vs {pct(ip['买']['int_base'], 1)}(n={ip['买']['n']})。卖单明显偏好 240.00/236.00/588.00 这类整数限价=人手敲价; 买单没有偏好(多为对手价/市价成交)。")
    a(f"- 买价相对昨收%(P10/P25/中位/P75/P90) {P['buy_vs_pc_q']}; 相对开盘% {P['buy_vs_open_q']}; 0.25% 分箱的最大单箱只占 {pct(P['buy_vs_pc_mode_share'])} → **没有固定挂价偏移**。")
    a(f"- 买价在所在 1 分钟 bar 的位置(0=低 1=高) P10/P25/中位/P75/P90 = {TRIG.get('pos_in_bar_q')}; 相对截至当时均价% {TRIG.get('vs_vwap_q')}。")
    a("")
    a("### 1.4 程序化可能性(概率分布)")
    a("")
    a("| 假设 | 概率 |")
    a("| --- | --- |")
    for h, p_ in zip(PR["hyp"], PR["post"]):
        a(f"| {h} | {pct(p_)} |")
    a("")
    a("计算方式: 等先验 × 各证据的**主观似然比**(下表, 可在 `prog_probability()` 里改), 归一。似然比是判断不是测量, 概率只表达相对倾向。")
    a("")
    a("| 证据 | 似然比(全自动/半自动/纪律人工/其他) |")
    a("| --- | --- |")
    for t, lr in PR["evidence"]:
        a(f"| {t} | {' / '.join(str(x) for x in lr)} |")
    a("")
    # ---------- 二 ----------
    a("## 二、选股规则")
    a("")
    a(f"样本: 新开仓 {A['n_new_open']} 次, 资产结构 {SEL['asset_mix_new_open']}(HK=港股/CB=转债 无行情, 不进选股评估)。负样本=买入当日全市场 主板/创业板/科创板/北交所/ETF 候选(日均 {SEL['lr_test']['pool_med']} 只), 另报同板块内百分位。特征只用买入前一交易日收盘 + 本人此前成交记录(回头票)。")
    a("")
    a("| 模型(时间外, 后 30%) | Top2 | Top10 | Top50 | Top200 | Top50 精确率 | Top50 倍数(÷随机) | 真人票中位百分位 |")
    a("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for nm, k in (("随机", "base_random_test"), ("昨成交额榜", "base_prev_amt_test"), ("逻辑回归(日线+回头票)", "lr_test"), ("候选池规则 + 逻辑回归", "pool_plus_lr_test"), ("上限诊断: 再加当日全天信息(后见)", "oracle_test")):
        e = SEL[k]
        a(f"| {nm} | {pct(e['cover'][2], 1)} | {pct(e['cover'][10], 1)} | {pct(e['cover'][50], 1)} | {pct(e['cover'][200], 1)} | {pct(e['precision'][50], 2)} | ×{e['lift'][50]} | {e['pct_rank_med']} |")
    e = SEL["lr_train"]
    a(f"| (训练窗内, 逻辑回归) | {pct(e['cover'][2], 1)} | {pct(e['cover'][10], 1)} | {pct(e['cover'][50], 1)} | {pct(e['cover'][200], 1)} | {pct(e['precision'][50], 2)} | ×{e['lift'][50]} | {e['pct_rank_med']} |")
    a("")
    a(f"- 同板块内百分位(时间外, 0=板块内最高分): 中位 {SEL['lr_test'].get('board_pct_rank_med')} —— 按板块分开比也没有明显更好。")
    a(f"- 逻辑回归权重最大的特征: {SEL['top_weights'][:8]}")
    pr_ = SEL["pool_rule"]
    a(f"- **能机械还原的只有候选池**(训练窗正样本 P10 门槛): {pr_}。训练窗覆盖 {pct(SEL['pool_rule_train']['cover'])}(日均池 {SEL['pool_rule_train']['pool_med']} 只) → 时间外覆盖 {pct(SEL['pool_rule_test']['cover'])}(日均池 {SEL['pool_rule_test']['pool_med']} 只, 精确率 {pct(SEL['pool_rule_test']['precision'], 2)})。")
    a("- 结论: 池子里挑哪 2~3 只, 日线量价 + 回头票 + 昨日题材/龙虎榜都解释不了; 把**当日全天**的涨跌/振幅/成交额都给模型(后见之明)也只把 Top50 覆盖抬到上表那一行 → 选股依赖我们没有的信息(盘中分时形态、新闻/公告、板块联动、别的选股器), 或本来就是主观挑。")
    a("")
    # ---------- 三 ----------
    a("## 三、买点/时机")
    a("")
    a(f"分钟层: 新开仓 A 股首腿 {TRIG['n_with_minutes']}/{TRIG['n_new_open_A']} 有当日分钟线。买入分钟分位 {TRIG.get('buy_minute_q')}; 买时相对昨收%分位 {TRIG.get('pct_at_buy_q')}。")
    a("")
    a("检验方法: 对每个条件, 看「买入前 2 分钟内刚刚由假变真」的比例; 零假设=把同一分钟序号套到其他(日,票)上(时间配对, 消掉早盘波动大造成的假阳性)。")
    a("")
    a("| 条件 | 买前状态成立(真) | (配对) | 刚触发(真) | (配对) | 提升 |")
    a("| --- | --- | --- | --- | --- | --- |")
    for nm, v in sorted(TRIG["conds"].items(), key=lambda kv: -kv[1]["提升"]):
        a(f"| {nm} | {pct(v['状态成立_真'])} | {pct(v['状态成立_配对'])} | {pct(v['刚触发_真'], 1)} | {pct(v['刚触发_配对'], 1)} | ×{v['提升']} |")
    a("")
    a(f"- 最强的「刚创日内新高/5 分钟涨>1%/放量/刚翻红 1%」最多只有约 2 成买点满足, 提升不到 2 倍; 「高点回落≥2%」「跌破均价」显著少于配对(×0.2~0.6)→ 他**回避在回落中买**, 偏在走强时顺势买, 但不是某个可执行的单一触发器。")
    a(f"- 可执行的买点规则(还原版): 卖完旧仓后, 09:31 起在 {EX['first_buy_hhmm']} 前后(训练窗首买中位)按「1/K 可用资金」逐只买入, 最后一只用全仓; 价格用对手价; 不在高点回落≥2% 或跌破均价 1% 时买。")
    a("")
    # ---------- 四 ----------
    a("## 四、卖出规则")
    a("")
    a(f"卖出事件 {SELL['n']} 次, 持有交易日分布 {SELL['hold_days']}(0=日内 T); A 股隔夜仓 {SELL['A_overnight_n']} 次的卖出时段: {SELL['A_overnight_bucket']}; 港股 {SELL['hk_bucket']}。")
    a("")
    a("| 规则类别 | 检验 | 命中率 |")
    a("| --- | --- | --- |")
    a(f"| 时间止损: 次日开盘窗清仓 | 隔夜仓 ≤09:35 卖 / ≤10:00 卖 / 恰持有 1 个交易日 | {pct(SELL['time_exit_rule_hit']['≤09:35'])} / {pct(SELL['time_exit_rule_hit']['≤10:00'])} / {pct(SELL['time_exit_rule_hit']['持有恰 1 个交易日'])} |")
    for k, (n, h) in SELL["price_rule_hit"].items():
        a(f"| 固定{k} | 次日盘中触及该价({n} 次)时恰在该价±0.5% 卖出 | {pct(h, 1)} |")
    a(f"| 尾盘清仓 | 卖出在 ≥14:30 | {pct(SELL['sell_tail'], 1)} |")
    a(f"| 跟踪止损 | 隔夜仓几乎都在开盘 1 小时内卖完, 没有持有到回撤触发的空间 | 不适用 |")
    a("")
    a("竞价卖还是连续竞价卖 —— 由开盘缺口决定:")
    a("")
    a("| 次日开盘缺口 | 笔数 | 竞价(09:25)卖出占比 |")
    a("| --- | --- | --- |")
    for k, (n, s) in SELL["auction_by_gap"].items():
        a(f"| {k} | {n} | {pct(s)} |")
    a("")
    a("| 卖出时段 | 笔数 | 开盘缺口中位 | 盈亏中位 | 高开占比 |")
    a("| --- | --- | --- | --- | --- |")
    for k, v in SELL["bucket_stats"].items():
        a(f"| {k} | {v['n']} | {v['开盘缺口中位%']}% | {v['盈亏中位%']}% | {pct(v['高开占比'])} |")
    a("")
    a(f"- 隔夜仓盈亏%分位 {SELL['pnl_q']}, 胜率 {pct(SELL['win_rate'])}。")
    a(f"- 还原版卖出规则: 次日 09:25 前挂单; 竞价指示价相对昨收 ≥ {EX['auction_gap_th']:+.2%} 时竞价全卖, 否则 09:30~09:35 连续竞价逐只卖完; 港股仓放宽到当日上午/午后。训练窗准确率 {pct(EX['auction_rule_acc'])}(全部按「不竞价」猜的基线 {pct(EX['auction_base_acc'])})。")
    a("")
    # ---------- 五 ----------
    a("## 五、仓位/资金管理")
    a("")
    a(f"- 收盘平均仓位 {pct(SZ['close_pos_mean'])}, 满仓(≥90%)日 {pct(SZ['close_pos_ge90'])}; 收盘持股只数分位 {SZ['hold_names_q']}; 每日新开只数分布 {SZ['names_per_day']}。")
    a(f"- 买单 ÷ 可用资金 标签: {SZ['labels']}; 当日最后一单=全仓按钮的占比 {pct(SZ['last_order_full'])}; 常见序列(·=非整分数): {SZ['top_sequences'][:6]}")
    a(f"- 当日各票金额权重 vs 1/n: {SZ['weight_by_n']} → 大致等权(1/4 仓按钮 + 剩余全仓), 但离散度大。")
    a(f"- 日收益 ≤-3% 后次日收盘平均仓位 {pct(SZ['pos_after_loss3'][1])}(n={SZ['pos_after_loss3'][0]}) → 无回撤降仓。")
    a(f"- 同票同日隔 >5 分钟加仓 {SZ['adds_n']} 次, 加仓价相对首腿%分位 {SZ['adds_px_vs_first_q']}, 加价占比 {pct(SZ['adds_up_share'])} → 无固定加/减仓方向。")
    a("")
    # ---------- 六 ----------
    a("## 六、规则是否随时间变化")
    a("")
    a("| 指标 | 最佳单切点 | 切前均值 | 切后均值 | t |")
    a("| --- | --- | --- | --- | --- |")
    for k, v in sorted(REG["metrics"].items(), key=lambda kv: -kv[1]["t"]):
        a(f"| {k} | {v['split']} | {v['before']} | {v['after']} | {v['t']} |")
    a("")
    a(f"- 疑似版本切换日(|t|≥3.5 且 ±7 交易日内聚类): {REG['switch_candidates'] if REG['switch_candidates'] else '无'}")
    a("- 选股模型漂移(用前 50% 训练, 逐月 Top50 覆盖; in_train=该月在训练窗内):")
    a("")
    a("| 月 | Top50 覆盖 | 新开仓数 | 训练窗内 |")
    a("| --- | --- | --- | --- |")
    for m, v in REG["drift"].items():
        a(f"| {m} | {pct(v['cover50'])} | {v['pos']} | {'是' if v['in_train'] else '否'} |")
    a("")
    a("月度画像:")
    a("")
    ks = list(next(iter(REG["monthly"].values())).keys())
    a("| 月 | " + " | ".join(ks) + " |")
    a("| --- | " + " | ".join("---" for _ in ks) + " |")
    for m, v in REG["monthly"].items():
        a(f"| {m} | " + " | ".join("—" if v[k] is None else str(v[k]) for k in ks) + " |")
    a("")
    # ---------- 不自信 & 建议 ----------
    a("## 不自信点")
    a("")
    a("1. **概率分布的似然比是主观的**。「App 按钮式整分数」「卖单整数价」两条强证据指向人手下单, 但程序也可以模仿(券商 API 按可用资金分数下单 + 整数限价)。")
    a("2. 现金推算依赖净值表 asset × (1-收盘仓位) 得到早盘可用资金, 忽略了两融/在途资金/费用; 「30 秒内同票连续腿并为一单」可能把部分成交拆开或把两单合并。整分数占比可能被低估。")
    a("3. 选股负样本=全市场(含北交所/ETF), 没有行业/概念库, 「同题材候选」只能用 md 涨停分析的题材(覆盖不全)。选股不可复现可能部分是特征不全造成的, 不一定是主观。")
    a(f"4. 分钟层只覆盖他**买了**的票; 全市场同时刻的盘中状态我们没有(10/09 前无全市场分钟线), 所以「盘中选股」无法检验, 只能检验「已选中的票在何时买」。")
    a("5. 回放的模拟买价: 规则票没有分钟线时用 (O+H+L+C)/4 代理, 买入时点误差会被这个代理放大/缩小; 次日按开盘价卖(竞价)。港股/转债/日内 T 不在回放里。")
    a("6. 版本切换用的是单切点 t 检验, 多指标多重比较, |t|≥3.5 也可能有假阳性; 港股占比在 3 月、8 月有明显簇, 可能是题材驱动而不是程序换版本。")
    a("7. 时间外只有约 55 个交易日、~140 笔新开仓, 覆盖率的 95% 区间大约 ±5 个百分点。")
    a("")
    a("## 建议")
    a("")
    a("- **A-lianghuaxiaohao 链不建议改成「规则出单、LLM 只做异常复核」的全规则模式**: 选股层时间外命中接近随机, 规则出的票和真人基本不重合。")
    a("- 可以改成**混合模式**: 执行层(次日开盘窗清仓 + 竞价/连续竞价按缺口 + 满仓 + K≈2~3 只 + 1/K 资金分配 + 09:3x~09:5x 买入窗 + 不在回落中买)用 `--signal` 的规则零 token 固化; 选股仍交 LLM(或改为「候选池规则 + LLM 在池内挑 2~3 只」, 池子由 `--signal` 输出的 candidates 提供)。")
    a("- 先修 mentor_fingerprint 的科创板成交量口径(10/09 前 ÷100), 否则指纹表「成交额≥30 亿/换手≥20%」对科创票是放大的。")
    a("- 想继续逼近选股: 需要全市场盘中分钟线(至少候选池 Top200)回补, 和行业/概念归属库; 有了再用本脚本的 `rank_eval` 框架复测。")
    a("")
    a("## 复现")
    a("")
    a("```")
    a("scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/reverse_lianghua.py                    # 全分析 + 本报告")
    a(f"scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/reverse_lianghua.py --replay --since {RP['since']} --until {RP['until']}")
    a("scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/reverse_lianghua.py --signal --date 2026-10-19")
    a("scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/reverse_lianghua.py --selftest")
    a("```")
    a("中间数据: `scripts/tzzb/reverse_lianghua/`(analysis.json / model_params.json / replay_*.json)。")
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    return REPORT


# ====================================================================================
# 7. 入口
# ====================================================================================
def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


def analyze():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    M = FixedMarket()
    mt = mf.Mentor(LEDGER, M)
    real = load_real(mt)
    SH = SelfHist(M, mt)
    pos = positives_by_row(M, mt)
    log(f"[数据] 腿 {len(mt.legs)} / 新开仓 {sum(e['new_open'] for e in mt.buys)} / 面板 {len(M.dates)} 日, 科创量修正 {M.vfix_n} 只 ({time.time() - t0:.0f}s)")
    A = {"generated": dtm.datetime.now().isoformat(timespec="seconds"), "n_legs": len(mt.legs), "n_new_open": sum(e["new_open"] for e in mt.buys),
         "window": [mt.legs[0]["trans_date"][:10], mt.legs[-1]["trans_date"][:10]], "vfix_n": M.vfix_n}
    A["prog"] = sec_programmatic(M, mt, real); log(f"[一] 程序化证据 ({time.time() - t0:.0f}s)")
    A["sel"], model, (tr, te, cut) = sec_selection(M, mt, SH, pos); log(f"[二] 选股 ({time.time() - t0:.0f}s)")
    A["trig"] = sec_trigger(M, mt); log(f"[三] 买点 ({time.time() - t0:.0f}s)")
    A["sell"] = sec_sell(M, mt); log(f"[四] 卖出 ({time.time() - t0:.0f}s)")
    A["prog"]["sell_le935"] = A["sell"]["sell_le935"]
    A["size"] = sec_sizing(M, mt, real); log(f"[五] 仓位 ({time.time() - t0:.0f}s)")
    A["regime"] = sec_regime(M, mt, real, SH, pos, model); log(f"[六] 版本 ({time.time() - t0:.0f}s)")
    cut_day = M.dates[cut]
    A["exec"] = fit_exec_params(M, mt, real, cut_day)
    A["prob"] = prog_probability(A["prog"], A["sel"], A["trig"])
    params = {"ledger": LEDGER, "trained_until": cut_day, "exec": A["exec"], "model": model.to_json(), "pool_rule": A["sel"]["pool_rule"],
              "note": "前 70% 买入日训练; --signal 会用 D 之前全部数据重训(走步), 本文件供 --replay 复现时间外结果"}
    (OUT_DIR / "model_params.json").write_text(json.dumps(jsonable(params), ensure_ascii=False, indent=1), encoding="utf-8")
    last = max(d for d in real if real[d].get("nav_r") is not None)
    A["replay"] = replay(M, mt, real, model, A["exec"], cut_day, last, SH=SH); log(f"[回放] ({time.time() - t0:.0f}s)")
    (OUT_DIR / "replay_oos.json").write_text(json.dumps(jsonable(A["replay"]), ensure_ascii=False, indent=1), encoding="utf-8")
    slim = {k: v for k, v in A.items() if k != "replay"}
    slim["replay"] = {k: v for k, v in A["replay"].items() if k != "daily"}
    (OUT_DIR / "analysis.json").write_text(json.dumps(jsonable(slim), ensure_ascii=False, indent=1), encoding="utf-8")
    p = write_report(A)
    log(f"[完成] 报告 {p} ({time.time() - t0:.0f}s)")
    print(json.dumps(jsonable({"prob": dict(zip(A["prob"]["hyp"], A["prob"]["post"])), "replay": slim["replay"],
                               "sel_test_cover": A["sel"]["lr_test"]["cover"], "exec": A["exec"]}), ensure_ascii=False, indent=1))


def cmd_replay(since, until):
    M = FixedMarket()
    mt = mf.Mentor(LEDGER, M)
    real = load_real(mt)
    pf = OUT_DIR / "model_params.json"
    if pf.exists():
        P = json.loads(pf.read_text(encoding="utf-8"))
        model, ex = LRModel.from_json(P["model"]), P["exec"]
    else:
        SH = SelfHist(M, mt); pos = positives_by_row(M, mt)
        rows = [r for r in sorted(pos) if M.dates[r] < since]
        X, y, w = build_train(M, SH, pos, rows)
        model = LRModel().fit(X, y, w); ex = fit_exec_params(M, mt, real, since)
    if since < ex.get("until", since):
        log(f"[警告] since={since} 早于参数训练截止 {ex['until']} → 部分为样本内")
    R = replay(M, mt, real, model, ex, since, until)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    f = OUT_DIR / f"replay_{since}_{until}.json"
    f.write_text(json.dumps(jsonable(R), ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(jsonable({k: v for k, v in R.items() if k != "daily"}), ensure_ascii=False, indent=1))
    log(f"[回放] 明细 {f}")


def cmd_signal(day):
    """只用 D 之前的数据: 行情面板 asof=D, 本人成交 asof=D; 模型走步重训"""
    M = FixedMarket(asof=day)
    mt = mf.Mentor(LEDGER, M, asof=day)
    real = load_real(mt)
    SH = SelfHist(M, mt)
    pos = positives_by_row(M, mt)
    rows = [r for r in sorted(pos) if r >= 1]
    X, y, w = build_train(M, SH, pos, rows)
    model = LRModel().fit(X, y, w)
    ex = fit_exec_params(M, mt, real, day)
    p = len(M.dates) - 1                       # D 前最后一个交易日
    js, Xd = day_features(M, SH, p)
    sc = model.score(Xd)
    order = np.argsort(-sc)
    k_lamt, k_lpx, k_lcap, k_r20 = (FEATS.index(k) for k in ("lamt", "lpx", "lcap", "r20"))
    pr = json.loads((OUT_DIR / "model_params.json").read_text(encoding="utf-8"))["pool_rule"] if (OUT_DIR / "model_params.json").exists() else None

    def in_pool(k):
        if not pr:
            return None
        return bool(Xd[k, k_lamt] >= math.log10(pr["成交额≥(亿)"] * 1e8 + 1) and Xd[k, k_lpx] >= math.log10(pr["股价≥"]) and
                    np.nan_to_num(Xd[k, k_lcap]) >= math.log10(pr["流通市值≥(亿)"] * 1e8 + 1) and Xd[k, k_r20] >= pr["20日涨幅≥%"] / 100
                    and not Xd[k, FEATS.index("st")] and not Xd[k, FEATS.index("bse")])
    cands = []
    for r, k in enumerate(order[:30]):
        j = js[k]
        cands.append({"rank": r + 1, "symbol": M.syms[j], "name": M.name.get(M.syms[j]), "score": round(float(sc[k]), 3), "in_pool_rule": in_pool(k),
                      "prev_close": round(float(M.C[p, j]), 3), "prev_pct": round(float(M.pct[p, j]), 4) if np.isfinite(M.pct[p, j]) else None,
                      "ret20": round(float(M.ret[20][p, j]), 4) if np.isfinite(M.ret[20][p, j]) else None,
                      "amt_e8": round(float(M.amt[p, j] / 1e8), 2) if np.isfinite(M.amt[p, j]) else None,
                      "revisit_60d": bool(SH.win(p, 60)[j] > 0)})
    last_pos_day = max(d for d in real if real[d].get("pos")) if any(real[d].get("pos") for d in real) else None
    holds = real[last_pos_day]["pos"] if last_pos_day else {"codes": [], "w": {}}
    K = ex["K"]
    fracs = [f"1/{K - q}" if K - q > 1 else "全仓" for q in range(K)]   # 1/K, 1/(K-1), ..., 全仓 = 等权
    out = {
        "ledger": LEDGER, "date": day, "data_until": M.dates[p], "generated": dtm.datetime.now().isoformat(timespec="seconds"),
        "sell_plan": {"holdings_from": last_pos_day, "codes": [{"code": c, "weight": holds["w"].get(c)} for c in holds["codes"]],
                      "rule": f"09:25 前挂单: 竞价指示价相对昨收 ≥ {ex['auction_gap_th']:+.2%} → 竞价全卖; 否则 09:30~09:35 对手价逐只卖完; 港股仓当日上午内卖完",
                      "auction_gap_th": ex["auction_gap_th"]},
        "buy_plan": {"K": K, "picks": cands[:K], "time_window": f"09:31 ~ 10:00, 目标首买 {ex['first_buy_hhmm']}",
                     "sizing": f"按可用资金依次 {' → '.join(fracs)}(App 仓位按钮式, 合计≈满仓)",
                     "avoid": "高点回落≥2% 或 跌破分时均价 1% 时不买(真人显著回避); 不打板",
                     "exit": "次日按 sell_plan 清仓(持有 1 个交易日)"},
        "candidates": cands,
        "fidelity_warning": "选股层时间外命中接近随机(见 docs/research/reverse_lianghua_20261016.md), picks 只是规则版近似; 执行层规则可信。建议 LLM 在 candidates 内复核挑票。",
        "model": {"trained_rows": len(rows), "train_pos": int(y.sum()), "exec_params": ex},
    }
    SIG_DIR.mkdir(parents=True, exist_ok=True)
    f = SIG_DIR / f"lianghua_signal_{day}.json"
    f.write_text(json.dumps(jsonable(out), ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(jsonable({k: out[k] for k in ("date", "data_until", "sell_plan", "buy_plan")}), ensure_ascii=False, indent=1))
    log(f"[信号] {f}")


# ====================================================================================
# 8. 自测
# ====================================================================================
def selftest():
    ok = 0
    # 时间工具
    assert trade_minute("09:30:00") == 0 and trade_minute("10:30:00") == 60 and trade_minute("13:00:00") == 120, "trade_minute"
    assert minute_to_hhmm(0) == "09:30" and minute_to_hhmm(150) == "13:30", "minute_to_hhmm"
    assert bar_label("09:25") == "09:30" and bar_label("09:30") == "09:31" and bar_label("11:30") == "11:30" and bar_label("12:00") is None
    ok += 1
    # 资金分数标签
    assert frac_label(0.247) == "1/4" and frac_label(0.33) == "1/3" and frac_label(0.995) == "全仓" and frac_label(0.4) is None
    ok += 1
    # χ²: 均匀 → p 大; 集中 → p 小
    assert chi2_uniform([10] * 60)[2] > 0.5 and chi2_uniform([100] + [1] * 59)[2] < 1e-6
    ok += 1
    # 逻辑回归: 可分数据 TopN 应高
    rng = np.random.default_rng(0)
    n = 5000
    X = rng.normal(size=(n, len(FEATS)))
    y = (X[:, 0] + 0.5 * X[:, 3] + rng.normal(scale=0.3, size=n) > 2.2).astype(float)
    m = LRModel(iters=300).fit(X, y)
    s = m.score(X)
    top = np.argsort(-s)[:int(y.sum())]
    assert y[top].mean() > 0.7, f"LR 可分性 {y[top].mean()}"
    m2 = LRModel.from_json(json.loads(json.dumps(m.to_json())))
    assert np.allclose(m2.score(X[:10]), s[:10], atol=1e-6)
    ok += 1
    # 单切点: 植入均值跳变
    x = np.r_[rng.normal(0, 1, 60), rng.normal(2, 1, 60)]
    t, at = best_split(x)
    assert t > 5 and 50 <= at <= 70, (t, at)
    ok += 1
    # 相关
    assert corr([1, 2, 3, 4, 5, 6], [2, 4, 6, 8, 10, 12]) == 1.0 and corr([1, 1, 1, 1, 1], [1, 2, 3, 4, 5]) is None
    ok += 1
    # sim_nav: 玩具面板, 买入价=收盘 → 当日收益≈-费, 次日按开盘卖
    class Toy:
        dates = ["d0", "d1", "d2"]
        O = np.array([[10.0], [11.0], [12.0]]); C = np.array([[10.0], [11.0], [12.0]])
    r = sim_nav(Toy, {0: [(0, 1.0, 10.0)], 1: [(0, 1.0, 11.0)], 2: []})
    assert abs(r["d0"] + FEE_BUY) < 1e-9 and abs(r["d1"] - (1.1 * (1 - FEE_SELL) * (1 - FEE_BUY) - 1)) < 1e-9 and abs(r["d2"] - (12 / 11 * (1 - FEE_SELL) - 1)) < 1e-9
    ok += 1
    # 产物 schema(若已跑过分析)
    pf = OUT_DIR / "model_params.json"
    if pf.exists():
        P = json.loads(pf.read_text(encoding="utf-8"))
        assert {"exec", "model", "pool_rule", "trained_until"} <= set(P) and len(P["model"]["w"]) == len(FEATS)
        ok += 1
    print(f"selftest OK ({ok} 组)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--signal", action="store_true")
    ap.add_argument("--date")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif a.replay:
        if not (a.since and a.until):
            ap.error("--replay 需要 --since D --until D2")
        cmd_replay(a.since, a.until)
    elif a.signal:
        if not a.date:
            ap.error("--signal 需要 --date D")
        cmd_signal(a.date)
    else:
        analyze()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
