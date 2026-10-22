# -*- coding: utf-8 -*-
"""
mentor_model.py — 导师行为统计模型 + 基线虚拟账户(2026-10-16 建, 零 token, 只读)

用户 10/16 晚定: 决策改为「基线先出单、LLM 只改单」。交不交易(L1)/方向(L2)/仓位(L4) 用从导师真实账本推出来的
统计模型做基线, LLM 主攻选哪只/什么打法(L3); 另跑「基线虚拟账户」每天和 LLM 链比(链输了 = LLM 负贡献)。

模型(样本 100~250 交易日/人, 刻意简单、可解释、抗小样本):
  L1 今日出手概率 / L2 方向(减/不动/加): 带 L2 正则的逻辑回归(L2 层 = multinomial), 自写 Newton 法(numpy, 不依赖 sklearn)。
     部分池化: 全体导师一起训练, 设计矩阵 = [全局截距 | 全局斜率 | 导师截距偏移 | 导师×特征斜率偏移],
     偏移项罚得更重(λ_b ≫ λ_g) → 样本少的导师自动收缩到群体(= 经验贝叶斯/随机效应的 ridge 近似)。
     特征(全部 D-1 收盘可知): 大盘(指数/创业板涨跌、5 日涨跌、涨停/跌停家数、上涨占比、最高连板)
       + 导师自身(总仓、空/满仓、只数、持仓天数、持仓浮盈亏、持仓票昨涨停/跌停占比、账户昨日收益、昨日出手/方向、近 5 日出手率)
       + 星期 + 画像规则特征(rules.md 里能机械判定的 5 条, 见 PERSONA)。
  L4 仓位: 条件经验分布查表。总仓 = 昨仓 + 中位数Δ(导师×昨仓档×市况 → 导师×昨仓档 → 导师 → 群体×昨仓档);
     新开仓单票仓位 = 中位数/P25/P75(导师×打法×市况 → 导师×打法 → 导师 → 群体)。
  L3 打法: P(打法 | 市况) 两级平滑频率表(导师×市况 → 导师 → 群体), 打法标签 = mentor_fingerprint.classify_play;
     个股排序直接用 mentor_fingerprint.build_pool 的朴素贝叶斯池(不重做)。
严格样本外: 扩张窗口, 每 REFIT 个交易日重训一次, 只用 D 之前的标签预测 D; 基线(延续/常数)按 D 之前全部数据逐日更新(对模型偏保守)。
  每层对比: 延续(导师昨日原样; 概率版 = 导师自身的平滑马尔可夫转移) / 常数(导师历史频率, 向群体收缩) / 统计模型。
基线虚拟账户: 每位导师按「该层样本外更好的来源(模型/延续/常数)」出 交不交易/方向/目标仓位 + fingerprint 池按打法挑票,
  开盘撮合(保守口径同 matcher --replay: 全天封涨停买不到、开过板按涨停价成交、全天封跌停卖不出; 费率同 matcher),
  写 scripts/dfcf/paper/baseline/BL-<ledger>.json(不进 books/, 不进 matcher SOURCES), 再用 mimicry_score 同口径算拟人度,
  出「LLM 链 vs 基线账户」逐日对比。

数据(全部只读): downloads/tzzb/<ledger>/(day_positions/nav_daily/change_bs_*) / 行情库 investment_market(只 SELECT, 经 mentor_fingerprint.Market)
  / scripts/dfcf/paper/books/A-*.json(只读) / skills/<ledger>-skill/persona/rules.md(人读, 规则在本文件 PERSONA 里手工编码)
不调 LLM、不访问任何行情网络接口、不写业务库、不起子进程、不写 git。

用法(scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/mentor_model.py ...):
  (无参)                                样本外评估 → scripts/tzzb/model_out/eval_<截止>.json/.md
  --asof 2026-09-01                     只用该日之前的数据(行情面板与账本都截断)做评估 → model_out/asof_<D>/
  --predict --date 2026-10-19           用 D 之前数据出 D 日各导师 L1/L2/L4 概率 + 打法分布 + 基线建议 → model_out/<D>.json
  --baseline-books --since 2026-10-08 [--until D]   基线虚拟账户 + LLM 链对比 → scripts/dfcf/paper/baseline/
  --selftest                            构造数据验证训练/正则/池化/样本外无泄漏/虚拟撮合
"""
import sys

sys.dont_write_bytecode = True   # 不在现有目录留 pyc(import 现有模块时)

import argparse  # noqa: E402
import bisect  # noqa: E402
import datetime as dt  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "dfcf" / "paper"))
import mentor_fingerprint as fp  # noqa: E402  (只读; Market=行情面板, Mentor=逐笔事件, classify_play/build_pool)
import mimicry_score as ms  # noqa: E402      (只读; Real/derive/compare/aggregate = 拟人度同口径)

OUT = HERE / "model_out"
BASE_DIR = ROOT / "scripts" / "dfcf" / "paper" / "baseline"
REPORT = ROOT / "scripts" / "tzzb" / "model_out" / "reports" / "mentor_model_20261016.md"
LEDGERS = list(fp.MENTORS)                     # kind=pos 13 人(含不吃土豆0 / 冲5000w)
NAME_OF = fp.NAME_OF
NO_ACCOUNT = {"buchitudou0": "转债日内 T 型, 指纹池不覆盖转债(fingerprint 不出池), 不建基线账户",
              "chong5000w": "真人账本止于 2026-07-06, 10/08 起无导师状态, 不建基线账户"}

# ---- 时间切分(样本外) ----
TUNE_TRAIN_END = "2026-01-15"   # 调参: 训练 < 此日
TUNE_VALID_END = "2026-03-01"   # 调参: 验证 [TUNE_TRAIN_END, 此日)
EVAL_START = "2026-03-01"       # 正式样本外评估起点(调参窗之后, 不重叠)
REFIT = 10                      # 每 10 个交易日重训一次(扩张窗口)
GRID = [(lg, lb, off) for off in (1, 0) for lg in (3.0, 30.0) for lb in (30.0, 300.0, 3000.0)]   # (λ_全局=λ_导师截距, λ_导师斜率偏移, 是否以马尔可夫延续为偏移) — 都在调参窗定
BIG = 1e6                       # "关掉某组参数"用的罚
MIN_CELL = 8                    # 查表格子最少样本, 不足就回退
ALPHA = 5.0                     # 频率表向上一级收缩强度(伪计数)
STALE_MAX = 5                   # 导师数据滞后 ≤5 个交易日时, 用最近一日状态出预测(标 stale)
REG_EDGES = (40, 80)            # 市况 = 昨日涨停家数: <40 冷 / 40~80 温 / ≥80 热
REG_CN = ["冷(<40)", "温(40-80)", "热(≥80)"]
TP_BINS = ms.TP_BINS            # 总仓分档同 mimicry: 空<5%/轻<35%/半<65%/重<95%/满
TP_CAP = 0.98                   # 虚拟账户无融资: 目标总仓上限
BOOT_N, SEED = 2000, 20261016
DIR_CN = ["减", "不动", "加"]
CONFIG = {"initCash": 100000.0, "feeRate": 0.00025, "minFee": 5.0, "stampTax": 0.0005}   # 同 matcher.mjs CONFIG

# ---- 特征 ----
MKT = ["idx_pct", "cy_pct", "idx_ret5", "zt_n", "dt_n", "up_ratio", "max_lb"]
SELF = ["tp", "empty", "full", "n_hold", "hold_days", "hold_pnl", "hold_zt", "hold_dt", "acct_ret",
        "trade_prev", "dir_prev_up", "dir_prev_dn", "act5"]
CAL = ["mon", "fri"]
PERSONA = ["p_overnight", "p_empty1", "p_empty2_5", "p_bigloss", "p_preholiday"]
FEATS = MKT + SELF + CAL + PERSONA
FEAT_CN = {"idx_pct": "上证昨涨跌", "cy_pct": "创业板昨涨跌", "idx_ret5": "上证5日涨跌", "zt_n": "昨涨停家数(log)", "dt_n": "昨跌停家数(log)",
           "up_ratio": "昨上涨占比", "max_lb": "昨最高连板", "tp": "昨收总仓", "empty": "昨空仓", "full": "昨满仓", "n_hold": "持股只数",
           "hold_days": "持仓天数(log)", "hold_pnl": "持仓浮盈亏", "hold_zt": "持仓昨涨停占比", "hold_dt": "持仓昨跌停占比", "acct_ret": "账户昨日收益",
           "trade_prev": "昨日出手", "dir_prev_up": "昨日净加", "dir_prev_dn": "昨日净减", "act5": "近5日出手率", "mon": "周一", "fri": "周五",
           "p_overnight": "隔夜仓", "p_empty1": "空仓第1天", "p_empty2_5": "空仓2~5天", "p_bigloss": "昨日大亏≤-5%", "p_preholiday": "长假前最后交易日"}
# 画像规则 → 特征(只挑能机械判定、且多人 rules.md 里有明确断言的; 其余规则要盘中信息或主观判断, 不编)
PERSONA_DEF = {
    "p_overnight": ("昨日新开仓且收盘仍持有(实质仓≥2%)",
                    "芷影 R1「T 日买一只重仓过夜, 下一交易日早盘卖掉」/ 量化小号 R1「T+1 开盘窗清隔夜仓」/ ST之狼 R1·R3「T 买 T+1 早盘卖」/ 刘忆青 R6"),
    "p_empty1": ("昨日收盘空仓且是空仓第 1 天",
                 "芷影 R4「空仓只停一晚」/ 边学 R9「清仓→1-3 个交易日内再满仓」"),
    "p_empty2_5": ("昨日收盘空仓且已连续空仓 2~5 天",
                   "ST之狼 R10「清仓→空仓 1~5 日→再入场」/ 刘忆青 R5「空仓日=清仓后的间歇」"),
    "p_bigloss": ("账户昨日收益 ≤ -5%",
                  "边学 R1「深亏日不动」/ 星见野 R7「重仓大跌日零动作」/ 芷影 R8「大亏后下一交易日照样满仓」/ antoo R7「大亏日之后没有机械刹车」"),
    "p_preholiday": ("今天是长假(休市≥3 天)前最后一个交易日",
                     "量化小号 R6「长假前均不降仓」"),
}
# 宣秋 R12「出手与否不看大盘宽度」→ 不编特征, 用「去掉大盘特征」消融直接检验


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def d8(d):
    return d.replace("-", "")


def regime_of(zt_n):
    return 0 if zt_n < REG_EDGES[0] else 1 if zt_n < REG_EDGES[1] else 2


def tp_bin(x):
    return ms.tp_bin(x)


# ====================================================================================
# 一、带 L2 正则的逻辑回归(二分类 IRLS / 多分类 Newton), 纯 numpy
# ====================================================================================
def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35, 35)))


def fit_logit(X, y, pen, iters=60, tol=1e-9, off=None):
    """min Σ[log(1+e^z) − y z] + ½ Σ pen_j b_j², z = Xb + off(偏移=基线 log-odds); Newton + 回溯线搜索"""
    P = X.shape[1]
    b = np.zeros(P)
    off = np.zeros(X.shape[0]) if off is None else off

    def obj(bb):
        z = X @ bb + off
        return float(np.sum(np.logaddexp(0, z) - y * z) + 0.5 * np.sum(pen * bb * bb))
    f = obj(b)
    for _ in range(iters):
        p = _sigmoid(X @ b + off)
        g = X.T @ (p - y) + pen * b
        H = (X * (p * (1 - p))[:, None]).T @ X + np.diag(pen)
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(H, g, rcond=None)[0]
        t = 1.0
        while True:
            nb = b - t * step
            nf = obj(nb)
            if nf <= f + 1e-12 or t < 1e-8:
                break
            t *= 0.5
        done = abs(f - nf) < tol * (1 + abs(f))
        b, f = nb, nf
        if done:
            break
    return b


def _softmax(Z):
    Z = Z - Z.max(1, keepdims=True)
    E = np.exp(Z)
    return E / E.sum(1, keepdims=True)


def fit_softmax(X, y, K, pen, iters=60, tol=1e-9, off=None):
    """对称参数化 multinomial: W P×K; min −Σ log p_{i,y_i} + ½ Σ_k Σ_j pen_j W_jk²(ridge 使对称参数可辨识)"""
    N, P = X.shape
    W = np.zeros((P, K))
    off = np.zeros((N, K)) if off is None else off
    Y = np.zeros((N, K))
    Y[np.arange(N), y] = 1

    def obj(WW):
        Z = X @ WW + off
        m = Z.max(1, keepdims=True)
        lse = (m[:, 0] + np.log(np.exp(Z - m).sum(1)))
        return float(np.sum(lse - Z[np.arange(N), y]) + 0.5 * np.sum(pen[:, None] * WW * WW))
    f = obj(W)
    for _ in range(iters):
        Pm = _softmax(X @ W + off)
        G = X.T @ (Pm - Y) + pen[:, None] * W
        H = np.zeros((K * P, K * P))
        for k in range(K):
            for l in range(k, K):
                w = Pm[:, k] * ((1.0 if k == l else 0.0) - Pm[:, l])
                B = (X * w[:, None]).T @ X
                if k == l:
                    B = B + np.diag(pen)
                H[k * P:(k + 1) * P, l * P:(l + 1) * P] = B
                if k != l:
                    H[l * P:(l + 1) * P, k * P:(k + 1) * P] = B.T
        g = G.T.ravel()
        try:
            step = np.linalg.solve(H + 1e-9 * np.eye(K * P), g)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(H, g, rcond=None)[0]
        S = step.reshape(K, P).T
        t = 1.0
        while True:
            nW = W - t * S
            nf = obj(nW)
            if nf <= f + 1e-12 or t < 1e-8:
                break
            t *= 0.5
        done = abs(f - nf) < tol * (1 + abs(f))
        W, f = nW, nf
        if done:
            break
    return W


class PooledLR:
    """部分池化逻辑回归。列 = [全局截距 | 全局斜率(F) | 导师截距(M) | 导师×斜率(M·F)]。
    罚: 全局截距 1e-3; 全局斜率 lam_g; 导师截距 lam_a; 导师斜率偏移 lam_b。特征按训练集标准化, 缺失=0(=训练均值)。"""

    def __init__(self, K, cols, ledgers, lam_g, lam_b, lam_a=None):
        self.K, self.cols, self.ledgers = K, list(cols), list(ledgers)
        self.lam_g, self.lam_b = lam_g, lam_b
        self.lam_a = lam_g if lam_a is None else lam_a
        self.midx = {l: i for i, l in enumerate(self.ledgers)}

    def _design(self, F, mids):
        Z = (F[:, self.cols] - self.mu) / self.sd
        Z = np.where(np.isfinite(Z), Z, 0.0)
        N, Fn = Z.shape
        M = len(self.ledgers)
        oh = np.zeros((N, M))
        ok = mids >= 0
        oh[np.where(ok)[0], mids[ok]] = 1
        inter = (oh[:, :, None] * Z[:, None, :]).reshape(N, M * Fn)
        return np.hstack([np.ones((N, 1)), Z, oh, inter])

    def _pen(self):
        Fn, M = len(self.cols), len(self.ledgers)
        return np.concatenate([[1e-3], np.full(Fn, self.lam_g), np.full(M, self.lam_a), np.full(M * Fn, self.lam_b)])

    def fit(self, F, mids, y, off=None):
        """off = 每行基线概率(N×K, 导师自身平滑马尔可夫延续) → 以其 log 作偏移: 模型只学「相对基线的修正」, 罚项把修正收缩到 0 = 收缩回基线"""
        self.use_off = off is not None
        X0 = F[:, self.cols]
        self.mu = np.nanmean(X0, 0)
        self.mu = np.where(np.isfinite(self.mu), self.mu, 0.0)
        sd = np.nanstd(X0, 0)
        self.sd = np.where(np.isfinite(sd) & (sd > 1e-6), sd, 1.0)
        X = self._design(F, mids)
        pen = self._pen()
        if self.K == 2:
            self.b = fit_logit(X, y.astype(float), pen, off=self._off(off))
        else:
            self.W = fit_softmax(X, y.astype(int), self.K, pen, off=self._off(off))
        self.n = len(y)
        self.n_by = Counter(mids.tolist())
        return self

    def _off(self, off):
        if off is None:
            return None
        lo = np.log(np.clip(np.asarray(off, float), 1e-6, 1.0))
        return lo[:, 1] - lo[:, 0] if self.K == 2 else lo

    def predict(self, F, mids, off=None):
        X = self._design(F, mids)
        o = self._off(off) if self.use_off else None
        if self.K == 2:
            p = _sigmoid(X @ self.b + (0 if o is None else o))
            return np.stack([1 - p, p], 1)
        return _softmax(X @ self.W + (0 if o is None else o))

    def mentor_offsets(self):
        """导师截距偏移(看收缩程度用)"""
        Fn, M = len(self.cols), len(self.ledgers)
        if self.K == 2:
            return {l: float(self.b[1 + Fn + i]) for i, l in enumerate(self.ledgers)}
        return {l: [float(x) for x in self.W[1 + Fn + i]] for i, l in enumerate(self.ledgers)}

    def global_coefs(self):
        Fn = len(self.cols)
        names = [FEATS[c] for c in self.cols]
        if self.K == 2:
            return {n: float(v) for n, v in zip(names, self.b[1:1 + Fn])}
        return {n: [float(x) for x in self.W[1 + i]] for i, n in enumerate(names)}


VARIANTS = {   # 名称: (特征列, (lam_g, lam_b, lam_a) 的变换); 偏移开关跟随调参结果, offset_flip = 把它反过来
    "full": (FEATS, None),
    "offset_flip": (FEATS, None),             # 主模型有「马尔可夫延续偏移」→ 去掉; 没有 → 加上
    "no_persona": ([f for f in FEATS if f not in PERSONA], None),
    "no_market": ([f for f in FEATS if f not in MKT], None),
    "complete_pool": (FEATS, "complete"),     # 无导师斜率(只导师截距)
    "no_pool": (FEATS, "nopool"),             # 每位导师单独 ridge(全局斜率关掉, 导师截距/斜率只受轻罚)
}
for _p in PERSONA:
    VARIANTS["drop_" + _p] = ([f for f in FEATS if f != _p], None)


def make_model(K, variant, lam):
    feats, mode = VARIANTS[variant]
    cols = [FEATS.index(f) for f in feats]
    lg, lb = lam[0], lam[1]
    if mode == "complete":
        return PooledLR(K, cols, LEDGERS, lg, BIG, lg)
    if mode == "nopool":
        return PooledLR(K, cols, LEDGERS, BIG, lg, 1.0)
    return PooledLR(K, cols, LEDGERS, lg, lb, lg)


# ====================================================================================
# 二、样本行: (导师, 交易日 D) → D-1 收盘可知的特征 + D 日标签(mimicry 同口径)
# ====================================================================================
class MarketFeats:
    def __init__(self, M):
        self.M = M
        stock = np.isin(M.asset, list(fp.STOCK_ASSETS))
        with np.errstate(all="ignore"):
            self.max_lb = np.array([int((M.Hn[i] * stock).max()) for i in range(len(M.dates))])

    def at(self, i):
        M = self.M
        up = M.up_n[i] / max(1, M.up_n[i] + M.down_n[i])
        return {"idx_pct": float(M.idx_pct[i]), "cy_pct": float(M.cy_pct[i]), "idx_ret5": float(M.idx_ret5[i]),
                "zt_n": math.log1p(int(M.zt_n[i])), "dt_n": math.log1p(int(M.dt_n[i])), "up_ratio": float(up),
                "max_lb": float(min(self.max_lb[i], 10)), "_zt_raw": int(M.zt_n[i])}


def jidx(M, code):
    s = fp.symbol_of(str(code))
    return M.sidx.get(s) if s else None


def mret(M, code, i0, i1):
    j = jidx(M, code)
    if j is None or i0 is None:
        return None
    a, b = M.C[i0, j], M.C[i1, j]
    return float(b / a - 1) if np.isfinite(a) and np.isfinite(b) and a > 0 else None


def next_gap_days(cal, k, extra_future=None):
    """cal[k] 到下一个交易日的自然日间隔; 面板外的最后一天按周末规则(周五=3 否则 1, 长假未知 → 不算长假)"""
    if k + 1 < len(cal):
        return (dt.date.fromisoformat(cal[k + 1]) - dt.date.fromisoformat(cal[k])).days
    wd = dt.date.fromisoformat(cal[k]).weekday()
    return 3 if wd == 4 else 1


def build_rows(ledger, real, M, MF, extra_day=None):
    """返回 rows(按日期升序)。cal = 面板交易日(+ extra_day 若在面板之后, 只出特征不出标签)。
    行 k 的特征只用 snap(≤k-1) 和面板 ≤k-1 行; 标签用 snap(k-1)/snap(k) 经 ms.derive(同 mimicry 口径)。"""
    cal = list(M.dates)
    if extra_day and extra_day > cal[-1]:
        cal.append(extra_day)
    n = len(cal)
    snaps, labs = [None] * n, [None] * n
    for k, d in enumerate(cal):
        if k < len(M.dates):
            snaps[k] = real.snap(d)
    runs = [None] * n          # code → (连续持有天数, 起始行)
    empt = [None] * n          # 连续空仓天数
    aret = [None] * n          # 账户当日收益
    for k in range(n):
        s = snaps[k]
        if s is None:
            continue
        ps = snaps[k - 1] if k else None
        i1 = M.didx.get(cal[k])
        i0 = M.didx.get(cal[k - 1]) if k else None
        f = ms.derive(ps, s, lambda c, a=i0, b=i1: mret(M, c, a, b) if a is not None and b is not None else None)
        labs[k] = {"trade": int(f["trade"]), "dir": f["dir"], "tp": f["tp"], "net": f["net"], "n": f["n"],
                   "buy": bool(s["buy"]), "sell": bool(s["sell"]), "buys": set(s["buy"])}
        r = {}
        prev_runs = runs[k - 1] if k and runs[k - 1] is not None else {}
        for c, w in s["hold"].items():
            if w < ms.MIN_W:
                continue
            if c in prev_runs:
                r[c] = (prev_runs[c][0] + 1, prev_runs[c][1])
            else:
                r[c] = (1, k)
        runs[k] = r
        e = f["tp"] < 0.05
        pe = empt[k - 1] if k and empt[k - 1] is not None else 0
        empt[k] = (pe + 1) if e else 0
        nv0 = real.idx.get(d8(cal[k - 1])) if k else None
        nv1 = real.idx.get(d8(cal[k]))
        if nv0 and nv1:
            aret[k] = nv1 / nv0 - 1
        elif ps is not None and i0 is not None and i1 is not None:
            aret[k] = sum(w * (mret(M, c, i0, i1) or 0.0) for c, w in ps["hold"].items())
    rows = []
    for k in range(1, n):
        last = None
        for kk in range(k - 1, max(-1, k - 2 - STALE_MAX), -1):
            if snaps[kk] is not None:
                last = kk
                break
        if last is None:
            continue
        stale = (k - 1) - last
        s, L = snaps[last], labs[last]
        ip = M.didx.get(cal[k - 1])
        if ip is None:
            continue
        mk = MF.at(ip)
        hold = {c: w for c, w in s["hold"].items() if w >= ms.MIN_W}
        tp = L["tp"]
        rr = runs[last] or {}
        tw = sum(hold.values())
        hd = sum(w * math.log1p(rr.get(c, (1, last))[0]) for c, w in hold.items()) / tw if tw > 0 else 0.0
        pnl, zt, dtw = 0.0, 0.0, 0.0
        il = M.didx.get(cal[last])
        for c, w in hold.items():
            j = jidx(M, c)
            if j is None or il is None:
                continue
            st = rr.get(c, (1, last))[1]
            ist = M.didx.get(cal[st])
            if ist is not None and np.isfinite(M.C[ist, j]) and np.isfinite(M.C[il, j]) and M.C[ist, j] > 0:
                pnl += w * (M.C[il, j] / M.C[ist, j] - 1)
            zt += w * bool(M.zt[il, j])
            dtw += w * bool(M.dtl[il, j])
        pnl = pnl / tw if tw > 0 else 0.0
        hist = [labs[x]["trade"] for x in range(max(0, last - 4), last + 1) if labs[x] is not None]
        dprev = L["dir"]
        ar = aret[last] if aret[last] is not None else 0.0
        es = empt[last] or 0
        wd = dt.date.fromisoformat(cal[k]).weekday()
        ovn = any(v[0] == 1 and c in L["buys"] for c, v in rr.items())
        x = dict(mk)
        x.update({"tp": min(tp, 2.5), "empty": float(tp < 0.05), "full": float(tp >= 0.95), "n_hold": float(min(len(hold), 5)),
                  "hold_days": hd, "hold_pnl": float(np.clip(pnl, -0.5, 0.5)), "hold_zt": zt / tw if tw > 0 else 0.0,
                  "hold_dt": dtw / tw if tw > 0 else 0.0, "acct_ret": float(np.clip(ar, -0.2, 0.2)),
                  "trade_prev": float(L["trade"]), "dir_prev_up": float(dprev == 1), "dir_prev_dn": float(dprev == -1),
                  "act5": float(np.mean(hist)) if hist else 0.0, "mon": float(wd == 0), "fri": float(wd == 4),
                  "p_overnight": float(ovn), "p_empty1": float(es == 1), "p_empty2_5": float(2 <= es <= 5),
                  "p_bigloss": float(ar <= -0.05), "p_preholiday": float(next_gap_days(cal, k) >= 4)})
        lab = labs[k] if (stale == 0 and k < len(M.dates)) else None
        ok = lab is not None and lab["dir"] is not None
        rows.append({"ledger": ledger, "date": cal[k], "prev": cal[last], "stale": stale, "x": x, "reg": regime_of(mk["_zt_raw"]),
                     "tp_prev": tp, "trade_prev": L["trade"], "dir_prev": 0 if dprev is None else dprev, "prev_ok": dprev is not None,
                     "hold_prev": hold, "runs_prev": {c: v[0] for c, v in rr.items()},
                     "y1": lab["trade"] if ok else None, "y2": (lab["dir"] + 1) if ok else None, "tp": lab["tp"] if ok else None,
                     "net": lab["net"] if ok else None, "y_buy": int(lab["buy"]) if ok else None, "y_sell": int(lab["sell"]) if ok else None})
    return rows


def feat_matrix(rows):
    F = np.array([[r["x"][f] for f in FEATS] for r in rows], float) if rows else np.zeros((0, len(FEATS)))
    mids = np.array([LEDGERS.index(r["ledger"]) if r["ledger"] in LEDGERS else -1 for r in rows], int)
    return F, mids


# ====================================================================================
# 三、基线(延续 / 常数) 与查表模型(L4 仓位, L3 打法)
# ====================================================================================
def expanding_baselines(rows, K, ykey, pkey):
    """逐日扩张(只用 < 该日的标签): 常数 = 导师类频率(向群体收缩); 马尔可夫延续 = P(今 | 昨, 导师)(向常数收缩); 硬延续 = 昨日标签。
    返回 {id(row): (const_probs, markov_probs, persist_label)}"""
    out = {}
    cm = defaultdict(lambda: np.zeros(K))
    cg = np.zeros(K)
    tm = defaultdict(lambda: np.zeros(K))
    bydate = defaultdict(list)
    for r in rows:
        bydate[r["date"]].append(r)
    for d in sorted(bydate):
        for r in bydate[d]:
            g = (cg + 1) / (cg.sum() + K)
            c = cm[r["ledger"]]
            const = (c + ALPHA * g) / (c.sum() + ALPHA)
            prev = int(r[pkey]) if pkey == "trade_prev" else int(r["dir_prev"]) + 1
            t = tm[(r["ledger"], prev)]
            mk = (t + ALPHA * const) / (t.sum() + ALPHA)
            out[id(r)] = (const, mk, prev)
        for r in bydate[d]:
            if r[ykey] is None or r["stale"]:
                continue
            y = int(r[ykey])
            cm[r["ledger"]][y] += 1
            cg[y] += 1
            if r["prev_ok"]:
                prev = int(r[pkey]) if pkey == "trade_prev" else int(r["dir_prev"]) + 1
                tm[(r["ledger"], prev)][y] += 1
    return out


def cell_lookup(tables, keys, min_n=MIN_CELL):
    """按 keys 顺序回退, 返回 (样本列表, 用到的层级名)"""
    for name, k in keys:
        xs = tables.get(k)
        if xs is not None and len(xs) >= min_n:
            return xs, name
    for name, k in reversed(keys):
        xs = tables.get(k)
        if xs:
            return xs, name + "(不足)"
    return [], "无"


class TPTable:
    """L4 总仓: tp_hat = 昨仓 + 中位数Δ; 分档 = 格子众数。格子: 导师×昨仓档×市况 → 导师×昨仓档 → 导师 → 群体×昨仓档"""

    def __init__(self, rows):
        self.d, self.b = defaultdict(list), defaultdict(list)
        self.tp = defaultdict(list)
        for r in rows:
            if r["tp"] is None or r["stale"]:
                continue
            pb = tp_bin(r["tp_prev"])
            for k in self._keys(r["ledger"], pb, r["reg"]):
                self.d[k[1]].append(r["tp"] - r["tp_prev"])
                self.b[k[1]].append(tp_bin(r["tp"]))
            self.tp[r["ledger"]].append(r["tp"])
            self.tp["*"].append(r["tp"])

    @staticmethod
    def _keys(l, pb, reg):
        return [("导师×昨仓档×市况", (l, pb, reg)), ("导师×昨仓档", (l, pb)), ("导师", (l,)), ("群体×昨仓档", ("*", pb))]

    def predict(self, l, tp_prev, reg):
        pb = tp_bin(tp_prev)
        xs, lvl = cell_lookup(self.d, self._keys(l, pb, reg))
        if xs:
            q = np.percentile(xs, [25, 50, 75])
            med = max(0.0, tp_prev + q[1])
            band = (max(0.0, tp_prev + q[0]), max(0.0, tp_prev + q[2]))
        else:
            med, band = tp_prev, (tp_prev, tp_prev)
        bs, _ = cell_lookup(self.b, self._keys(l, pb, reg))
        bmode = Counter(bs).most_common(1)[0][0] if bs else pb
        return {"tp_hat": med, "p25": band[0], "p75": band[1], "bin_hat": bmode, "cell": lvl, "n": len(xs)}

    def const(self, l):
        xs = self.tp.get(l) if len(self.tp.get(l, [])) >= MIN_CELL else self.tp.get("*")
        if not xs:
            return {"tp_hat": 0.5, "bin_hat": 2}
        return {"tp_hat": float(np.median(xs)), "bin_hat": Counter(tp_bin(x) for x in xs).most_common(1)[0][0]}


class PlayTable:
    """L3: P(打法 | 市况) = (n_{导师,市况,打法} + α·P(打法|导师)) / (n_{导师,市况} + α); P(打法|导师) 向群体收缩; 群体 Laplace。
    新开仓单票仓位: 导师×打法×市况 → 导师×打法 → 导师 → 群体 的中位数/P25/P75。"""

    def __init__(self, events):
        self.c = defaultdict(Counter)
        self.sz = defaultdict(list)
        for e in events:
            for k in (("*",), (e["ledger"],), (e["ledger"], e["reg"])):
                self.c[k][e["play"]] += 1
            if e.get("size"):
                for k in ((e["ledger"], e["play"], e["reg"]), (e["ledger"], e["play"]), (e["ledger"],), ("*",)):
                    self.sz[k].append(e["size"])
        self.labels = list(fp.PLAY_ORDER)

    def dist(self, l, reg):
        K = len(self.labels)
        g = self.c[("*",)]
        ng = sum(g.values())
        pg = {p: (g[p] + 1) / (ng + K) for p in self.labels}
        cm = self.c[(l,)]
        nm = sum(cm.values())
        pm = {p: (cm[p] + ALPHA * pg[p]) / (nm + ALPHA) for p in self.labels}
        cr = self.c[(l, reg)]
        nr = sum(cr.values())
        return {p: (cr[p] + ALPHA * pm[p]) / (nr + ALPHA) for p in self.labels}, pm, nm

    def size(self, l, play, reg):
        xs, lvl = cell_lookup(self.sz, [("导师×打法×市况", (l, play, reg)), ("导师×打法", (l, play)), ("导师", (l,)), ("群体", ("*",))], min_n=5)
        if not xs:
            return {"med": 0.3, "p25": 0.2, "p75": 0.5, "cell": "默认", "n": 0}
        q = np.percentile(xs, [25, 50, 75])
        return {"med": float(q[1]), "p25": float(q[0]), "p75": float(q[2]), "cell": lvl, "n": len(xs)}


def mentor_events(ledger, M):
    """导师新开仓事件(fingerprint 同口径打法) + 开仓当日收盘仓位(day_positions)"""
    mt = fp.Mentor(ledger, M)
    out = []
    for e in mt.buys:
        if not e["new_open"]:
            continue
        s = fp.symbol_of(e["code"])
        f = fp.event_features(M, s, e["row"], e["vwap"], e["t_first"], e["name"]) if e["row"] is not None else \
            {"symbol": s, "asset": fp.asset_class(e["code"]), "data": False}
        if f.get("asset") is None:
            f["asset"] = fp.asset_class(e["code"])
        play, _ = fp.classify_play(f)
        size = None
        for x in (mt.day_pos.get(e["date"]) or {}).get("list") or []:
            if str(x.get("code")) == e["code"]:
                size = float(x.get("position_percent") or 0) or None
        r = e["row"]
        reg = regime_of(int(M.zt_n[r - 1])) if r is not None and r >= 1 else 1
        out.append({"ledger": ledger, "date": e["date"], "code": e["code"], "play": play, "size": size, "reg": reg})
    out.sort(key=lambda e: e["date"])
    return out


# ====================================================================================
# 四、统计小工具
# ====================================================================================
def boot_ci(xs, n=BOOT_N, seed=SEED):
    xs = np.asarray([x for x in xs if x is not None and np.isfinite(x)], float)
    if len(xs) < 3:
        return (None, None)
    if np.all(xs == xs[0]):
        return (float(xs[0]), float(xs[0]))
    rng = np.random.default_rng(seed)
    ms_ = xs[rng.integers(0, len(xs), (n, len(xs)))].mean(1)
    return (float(np.quantile(ms_, 0.025)), float(np.quantile(ms_, 0.975)))


def verdict(diffs):
    """diffs = 基线损失 − 模型损失(>0 = 模型好)"""
    if not len(diffs):
        return "无数据", None, (None, None)
    m = float(np.mean(diffs))
    ci = boot_ci(diffs)
    if ci[0] is not None and ci[0] > 0:
        v = "显著赢"
    elif ci[1] is not None and ci[1] < 0:
        v = "显著输"
    else:
        v = "点赢" if m > 1e-12 else "点输" if m < -1e-12 else "平"
    return v, m, ci


def ll(p, y):
    return -math.log(max(float(p[y]), 1e-12))


# ====================================================================================
# 五、样本外评估
# ====================================================================================
def load_world(asof=None, extra_day=None):
    M = fp.Market(asof=asof)
    MF = MarketFeats(M)
    reals, rows = {}, []
    for l in LEDGERS:
        if not (ms.TZ / l / "day_positions.json").exists():
            continue
        reals[l] = ms.Real(l)
        if asof:
            reals[l].dp = {k: v for k, v in reals[l].dp.items() if k < d8(asof)}
            reals[l].idx = {k: v for k, v in reals[l].idx.items() if k < d8(asof)}
        rows += build_rows(l, reals[l], M, MF, extra_day=extra_day)
    rows.sort(key=lambda r: (r["date"], r["ledger"]))
    log(f"[样本] {len(rows)} 行(含特征-only/滞后行), 有标签 {sum(1 for r in rows if r['y1'] is not None)}")
    return M, MF, reals, rows


def labeled(rows, ykey, lo=None, hi=None):
    return [r for r in rows if r[ykey] is not None and not r["stale"] and (lo is None or r["date"] >= lo) and (hi is None or r["date"] < hi)]


LAYER_KEYS = {2: ("y1", "trade_prev"), 3: ("y2", "dir_prev")}


def offsets(rows, base, variant, lam=(0, 0, 1)):
    """该批行的偏移(= 导师平滑马尔可夫延续概率)。lam[2]=1 主模型带偏移; offset_flip 变体取反; 不带 → None"""
    use = bool(lam[2]) if len(lam) > 2 else True
    if variant == "offset_flip":
        use = not use
    if not use:
        return None
    return np.array([base[id(r)][1] for r in rows])


def tune(rows, K, ykey, base):
    tr = labeled(rows, ykey, hi=TUNE_TRAIN_END)
    va = labeled(rows, ykey, TUNE_TRAIN_END, TUNE_VALID_END)
    res = []
    if len(tr) < 50 or len(va) < 20:
        return GRID[2], [{"lam": GRID[2], "note": "调参样本不足, 用默认"}]
    Ft, mt_ = feat_matrix(tr)
    Fv, mv = feat_matrix(va)
    yt = np.array([r[ykey] for r in tr])
    yv = np.array([r[ykey] for r in va])
    for lam in GRID:
        m = make_model(K, "full", lam).fit(Ft, mt_, yt, offsets(tr, base, "full", lam))
        P = m.predict(Fv, mv, offsets(va, base, "full", lam))
        res.append({"lam": lam, "valid_logloss": float(np.mean([ll(P[i], yv[i]) for i in range(len(yv))])), "n_train": len(tr), "n_valid": len(va)})
    best = min(res, key=lambda x: x["valid_logloss"])["lam"]
    return best, res


def rolling_predict(rows, K, ykey, variant, lam, start, end, base, refit=REFIT):
    """扩张窗口: 把 [start,end) 内的标签日切成每 refit 个交易日一块, 每块只用块首日之前的标签训练。返回 {id(row): probs}"""
    ev = [r for r in rows if r[ykey] is not None and not r["stale"] and start <= r["date"] < end]
    dates = sorted({r["date"] for r in ev})
    out = {}
    for b in range(0, len(dates), refit):
        blk = set(dates[b:b + refit])
        tr = labeled(rows, ykey, hi=dates[b])
        if len(tr) < 30:
            continue
        F, mids = feat_matrix(tr)
        y = np.array([r[ykey] for r in tr])
        m = make_model(K, variant, lam).fit(F, mids, y, offsets(tr, base, variant, lam))
        te = [r for r in ev if r["date"] in blk]
        Fe, me = feat_matrix(te)
        P = m.predict(Fe, me, offsets(te, base, variant, lam))
        for r, p in zip(te, P):
            out[id(r)] = p
    return out


def eval_layer(rows, K, ykey, pkey, lam, start, end, variants, base):
    preds = {v: rolling_predict(rows, K, ykey, v, lam, start, end, base) for v in variants}
    recs = []
    for r in rows:
        if id(r) not in preds["full"] or not r["prev_ok"]:
            continue
        y = int(r[ykey])
        const, mk, prev = base[id(r)]
        rec = {"ledger": r["ledger"], "date": r["date"], "y": y,
               "ll": {"model": ll(preds["full"][id(r)], y), "markov": ll(mk, y), "const": ll(const, y)},
               "acc": {"model": float(int(np.argmax(preds["full"][id(r)])) == y), "persist": float(prev == y), "const": float(int(np.argmax(const)) == y)},
               "p_model": [round(float(x), 4) for x in preds["full"][id(r)]]}
        for v in variants:
            if v != "full" and id(r) in preds[v]:
                rec["ll"][v] = ll(preds[v][id(r)], y)
        recs.append(rec)
    return recs


def summarize_layer(recs, variants):
    by = defaultdict(list)
    for x in recs:
        by[x["ledger"]].append(x)
    by["全体"] = list(recs)
    out = {}
    for l, xs in by.items():
        if not xs:
            continue
        o = {"n": len(xs)}
        for k in ("model", "markov", "const"):
            o["ll_" + k] = float(np.mean([x["ll"][k] for x in xs]))
        for k in ("model", "persist", "const"):
            o["acc_" + k] = float(np.mean([x["acc"][k] for x in xs]))
        for b in ("markov", "const"):
            v, m, ci = verdict([x["ll"][b] - x["ll"]["model"] for x in xs])
            o["vs_" + b] = {"verdict": v, "lift": m, "ci": ci}
        v, m, ci = verdict([x["acc"]["model"] - x["acc"]["persist"] for x in xs])
        o["acc_vs_persist"] = {"verdict": v, "lift": m, "ci": ci}
        o["variants"] = {}
        for vname in variants:
            if vname == "full":
                continue
            ds = [x["ll"][vname] - x["ll"]["model"] for x in xs if vname in x["ll"]]   # >0 = 去掉该部分变差 = 该部分有增益
            v, m, ci = verdict(ds)
            o["variants"][vname] = {"verdict": v, "gain": m, "ci": ci, "n": len(ds)}
        o["choice"] = choose_source(o)
        out[l] = o
    return out


MIN_EFFECT = 0.005   # 选源最小效应(nats/日): 防「显著但可忽略」(如 0.001 vs 0.001)翻转选源


def choose_source(o):
    """该层用什么出单: 模型对数损失须同时显著赢马尔可夫延续和常数(且 lift ≥ MIN_EFFECT); 否则在 延续/常数 里取准确率高的(平手取延续)"""
    if all(o[k]["verdict"] == "显著赢" and (o[k]["lift"] or 0) >= MIN_EFFECT for k in ("vs_markov", "vs_const")):
        return "模型"
    return "延续" if o["acc_persist"] >= o["acc_const"] else "常数"


def eval_tp(rows, start, end):
    recs = []
    bydate = defaultdict(list)
    for r in rows:
        if r["tp"] is not None and not r["stale"] and start <= r["date"] < end:
            bydate[r["date"]].append(r)
    for d in sorted(bydate):
        T = TPTable([r for r in rows if r["date"] < d])
        for r in bydate[d]:
            p = T.predict(r["ledger"], r["tp_prev"], r["reg"])
            c = T.const(r["ledger"])
            y = r["tp"]
            recs.append({"ledger": r["ledger"], "date": d,
                         "err": {"model": abs(p["tp_hat"] - y), "persist": abs(r["tp_prev"] - y), "const": abs(c["tp_hat"] - y)},
                         "bin": {"model": float(p["bin_hat"] == tp_bin(y)), "persist": float(tp_bin(r["tp_prev"]) == tp_bin(y)),
                                 "const": float(c["bin_hat"] == tp_bin(y))}, "cell": p["cell"]})
    return recs


def summarize_tp(recs):
    by = defaultdict(list)
    for x in recs:
        by[x["ledger"]].append(x)
    by["全体"] = list(recs)
    out = {}
    for l, xs in by.items():
        o = {"n": len(xs)}
        for k in ("model", "persist", "const"):
            o["err_" + k] = float(np.mean([x["err"][k] for x in xs]))
            o["bin_" + k] = float(np.mean([x["bin"][k] for x in xs]))
        for b in ("persist", "const"):
            v, m, ci = verdict([x["err"][b] - x["err"]["model"] for x in xs])
            o["vs_" + b] = {"verdict": v, "lift": m, "ci": ci}
            v, m, ci = verdict([x["bin"]["model"] - x["bin"][b] for x in xs])
            o["bin_vs_" + b] = {"verdict": v, "lift": m, "ci": ci}
        # 选源: 模型须在「总仓误差」或「分档一致率」上同时显著赢延续和常数; 否则取分档一致率高的基线(平手取误差小的)。
        # 分档为主 = 拟人度报告的建议(绝对误差奖励停在中间仓位的「中庸」预测)
        win_err = o["vs_persist"]["verdict"] == "显著赢" and o["vs_const"]["verdict"] == "显著赢"
        win_bin = o["bin_vs_persist"]["verdict"] == "显著赢" and o["bin_vs_const"]["verdict"] == "显著赢"
        if win_err or win_bin:
            o["choice"] = "模型"
        elif abs(o["bin_persist"] - o["bin_const"]) > 1e-9:
            o["choice"] = "延续" if o["bin_persist"] > o["bin_const"] else "常数"
        else:
            o["choice"] = "延续" if o["err_persist"] <= o["err_const"] else "常数"
        o["cells"] = dict(Counter(x["cell"] for x in xs))
        out[l] = o
    return out


def eval_play(events, start, end):
    recs = []
    for e in events:
        if not (start <= e["date"] < end):
            continue
        past = [x for x in events if x["date"] < e["date"]]
        T = PlayTable(past)
        pr, pm, nm = T.dist(e["ledger"], e["reg"])
        mine = [x for x in past if x["ledger"] == e["ledger"]]
        last = mine[-1]["play"] if mine else None
        rec = {"ledger": e["ledger"], "date": e["date"], "play": e["play"],
               "ll": {"model": -math.log(pr[e["play"]]), "const": -math.log(pm[e["play"]])},
               "acc": {"model": float(max(pr, key=pr.get) == e["play"]), "const": float(max(pm, key=pm.get) == e["play"]),
                       "persist": float(last == e["play"])}}
        if e.get("size"):
            sz = T.size(e["ledger"], e["play"], e["reg"])
            msz = [x["size"] for x in mine if x.get("size")]
            const = float(np.median(msz)) if len(msz) >= 5 else T.size("*", "?", 0)["med"]
            pers = msz[-1] if msz else const
            rec["size_err"] = {"model": abs(sz["med"] - e["size"]), "const": abs(const - e["size"]), "persist": abs(pers - e["size"])}
        recs.append(rec)
    return recs


def summarize_play(recs):
    by = defaultdict(list)
    for x in recs:
        by[x["ledger"]].append(x)
    by["全体"] = list(recs)
    out = {}
    for l, xs in by.items():
        o = {"n": len(xs)}
        o["ll_model"] = float(np.mean([x["ll"]["model"] for x in xs]))
        o["ll_const"] = float(np.mean([x["ll"]["const"] for x in xs]))
        for k in ("model", "const", "persist"):
            o["acc_" + k] = float(np.mean([x["acc"][k] for x in xs]))
        o["vs_const"] = dict(zip(("verdict", "lift", "ci"), verdict([x["ll"]["const"] - x["ll"]["model"] for x in xs])))
        sz = [x for x in xs if "size_err" in x]
        o["n_size"] = len(sz)
        if sz:
            for k in ("model", "const", "persist"):
                o["size_err_" + k] = float(np.mean([x["size_err"][k] for x in sz]))
            o["size_vs_const"] = dict(zip(("verdict", "lift", "ci"), verdict([x["size_err"]["const"] - x["size_err"]["model"] for x in sz])))
            o["size_vs_persist"] = dict(zip(("verdict", "lift", "ci"), verdict([x["size_err"]["persist"] - x["size_err"]["model"] for x in sz])))
        o["choice"] = "模型" if o["vs_const"]["verdict"] == "显著赢" else "常数"          # 打法分布: 市况条件表 vs 导师无条件频率
        o["size_choice"] = "模型" if (o.get("size_vs_const") or {}).get("verdict") == "显著赢" else "常数"   # 单票仓位: 打法×市况表 vs 导师中位数
        out[l] = o
    return out


def run_eval(M, rows, events, cutoff, asof_label=None):
    """完整样本外评估。cutoff = 评估截止(不含), 默认面板最后一日之后。"""
    variants = list(VARIANTS)
    res = {"generated_at": dt.datetime.now().isoformat(timespec="seconds"), "asof": asof_label, "cutoff": cutoff,
           "split": {"tune_train_end": TUNE_TRAIN_END, "tune_valid_end": TUNE_VALID_END, "eval_start": EVAL_START, "refit": REFIT},
           "features": FEATS, "persona_def": PERSONA_DEF, "layers": {}}
    for layer, K, ykey, pkey in (("L1", 2, "y1", "trade_prev"), ("L2", 3, "y2", "dir_prev")):
        base = expanding_baselines(rows, K, ykey, pkey)
        lam, tres = tune(rows, K, ykey, base)
        log(f"[{layer}] 调参 λ=(全局 {lam[0]}, 导师斜率 {lam[1]})")
        recs = eval_layer(rows, K, ykey, pkey, lam, EVAL_START, cutoff, variants, base)
        log(f"[{layer}] 样本外 {len(recs)} 行")
        tr = labeled(rows, ykey, hi=cutoff)
        F, mids = feat_matrix(tr)
        final = make_model(K, "full", lam).fit(F, mids, np.array([r[ykey] for r in tr]), offsets(tr, base, "full", lam))
        res["layers"][layer] = {"lam": lam, "tuning": tres, "summary": summarize_layer(recs, variants),
                                "coefs": final.global_coefs(), "offsets": final.mentor_offsets(),
                                "n_train_by": {LEDGERS[k]: v for k, v in final.n_by.items() if k >= 0},
                                "records": [{k: v for k, v in x.items()} for x in recs]}
    tpr = eval_tp(rows, EVAL_START, cutoff)
    res["layers"]["L4"] = {"summary": summarize_tp(tpr), "records": tpr}
    pr = eval_play(events, EVAL_START, cutoff)
    res["layers"]["L3"] = {"summary": summarize_play(pr), "n": len(pr), "records": pr}
    res["persona_check"] = persona_check(rows)
    return res


def fmt_p(x, nd=0):
    return "—" if x is None else f"{x:.{nd}%}"


def fmt_f(x, nd=3, sign=False):
    if x is None:
        return "—"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def ci_s(ci, nd=3):
    return "—" if ci is None or ci[0] is None else f"[{ci[0]:+.{nd}f}, {ci[1]:+.{nd}f}]"


def eval_markdown(res):
    L = [f"# 导师行为统计模型 样本外评估(截止 {res['cutoff']}{', as-of ' + res['asof'] if res['asof'] else ''})", "",
         f"> 生成 {res['generated_at']} | 调参: 训练<{TUNE_TRAIN_END}, 验证<{TUNE_VALID_END} | 评估: [{EVAL_START}, {res['cutoff']}) 扩张窗口, 每 {REFIT} 交易日重训",
         "> 对数损失越低越好; lift = 基线损失 − 模型损失(>0 模型好), 区间 = 按日 bootstrap 95%。准确率 lift = 模型 − 硬延续。", ""]
    order = [l for l in LEDGERS] + ["全体"]
    for layer, title in (("L1", "L1 今天出不出手"), ("L2", "L2 方向(减/不动/加)")):
        lay = res["layers"][layer]
        S = lay["summary"]
        L += [f"## {title}(调参窗选定: λ 全局 {lay['lam'][0]} / 导师斜率 {lay['lam'][1]} / 马尔可夫延续偏移 {'有' if (lay['lam'][2] if len(lay['lam']) > 2 else 1) else '无'})", "",
              "| 导师 | n | 对数损失 模型/马尔可夫延续/常数 | lift vs 延续 [95%] | 判定 | lift vs 常数 [95%] | 判定 | 准确率 模型/硬延续/常数 | 用什么出单 |",
              "|---|---|---|---|---|---|---|---|---|"]
        for l in order:
            o = S.get(l)
            if not o:
                continue
            L.append(f"| {NAME_OF.get(l, l)} | {o['n']} | {o['ll_model']:.3f} / {o['ll_markov']:.3f} / {o['ll_const']:.3f} | "
                     f"{fmt_f(o['vs_markov']['lift'], sign=True)} {ci_s(o['vs_markov']['ci'])} | {o['vs_markov']['verdict']} | "
                     f"{fmt_f(o['vs_const']['lift'], sign=True)} {ci_s(o['vs_const']['ci'])} | {o['vs_const']['verdict']} | "
                     f"{fmt_p(o['acc_model'])} / {fmt_p(o['acc_persist'])} / {fmt_p(o['acc_const'])} | {o['choice']} |")
        L.append("")
        L += [f"### {layer} 消融(去掉某部分后对数损失增加多少; >0 = 该部分有增益)", "",
              "| 导师 | " + " | ".join(v for v in VARIANTS if v != "full") + " |", "|---|" + "---|" * (len(VARIANTS) - 1)]
        for l in order:
            o = S.get(l)
            if not o:
                continue
            L.append(f"| {NAME_OF.get(l, l)} | " + " | ".join(
                f"{fmt_f(o['variants'][v]['gain'], 4, True)}{'*' if o['variants'][v]['verdict'] == '显著赢' else '†' if o['variants'][v]['verdict'] == '显著输' else ''}"
                for v in VARIANTS if v != "full") + " |")
        L += ["", "\\* = 去掉后显著变差(该部分显著有用); † = 去掉后显著变好(该部分有害)。complete_pool = 只留导师截距; no_pool = 每人单独 ridge; offset_flip = 把调参选定的偏移开关反过来。", ""]
    S = res["layers"]["L4"]["summary"]
    L += ["## L4 总仓(条件经验分布查表)", "",
          "| 导师 | n | 总仓误差 模型/延续/常数 | lift vs 延续 [95%] | 判定 | 分档一致 模型/延续/常数 | 分档 lift vs 延续 | 用什么出单 |", "|---|---|---|---|---|---|---|---|"]
    for l in order:
        o = S.get(l)
        if not o:
            continue
        L.append(f"| {NAME_OF.get(l, l)} | {o['n']} | {o['err_model']:.3f} / {o['err_persist']:.3f} / {o['err_const']:.3f} | "
                 f"{fmt_f(o['vs_persist']['lift'], sign=True)} {ci_s(o['vs_persist']['ci'])} | {o['vs_persist']['verdict']} | "
                 f"{fmt_p(o['bin_model'])} / {fmt_p(o['bin_persist'])} / {fmt_p(o['bin_const'])} | {fmt_f(o['bin_vs_persist']['lift'], 3, True)} {o['bin_vs_persist']['verdict']} | {o['choice']} |")
    S = res["layers"]["L3"]["summary"]
    L += ["", "## L3 打法分布(新开仓事件) + 新开仓单票仓位", "",
          "| 导师 | 事件 n | 对数损失 模型(市况条件)/常数 | lift [95%] 判定 | Top1 命中 模型/常数/上一笔 | 仓位 n | 单票仓位误差 模型/常数/上一笔 | 判定 vs 常数 | 打法/仓位 用什么 |",
          "|---|---|---|---|---|---|---|---|---|"]
    for l in order:
        o = S.get(l)
        if not o:
            continue
        sz = (f"{o['size_err_model']:.3f} / {o['size_err_const']:.3f} / {o['size_err_persist']:.3f} | {o['size_vs_const']['verdict']}"
              if o.get("n_size") else "— | —")
        L.append(f"| {NAME_OF.get(l, l)} | {o['n']} | {o['ll_model']:.3f} / {o['ll_const']:.3f} | {fmt_f(o['vs_const']['lift'], sign=True)} "
                 f"{ci_s(o['vs_const']['ci'])} {o['vs_const']['verdict']} | {fmt_p(o['acc_model'])} / {fmt_p(o['acc_const'])} / {fmt_p(o['acc_persist'])} | "
                 f"{o.get('n_size', 0)} | {sz} | {o['choice']} / {o['size_choice']} |")
    pc = res.get("persona_check") or []
    L += ["", "## 画像规则的账本直检(全样本描述统计, 不是样本外; 区间 = 两比例差 95%)", "",
          "| 规则 | 导师 | 结果 | 规则成立日 n / 率 | 对照日(条件) n / 率 | 差 [95%] | 画像断言 |", "|---|---|---|---|---|---|---|"]
    ycn = {"y_sell": "卖出率", "y_buy": "买入率", "y1": "出手率", "y_red": "净减率"}
    for x in pc:
        if x.get("note"):
            ron = "" if x.get("rate_on") is None else f" / {x['rate_on']:.0%}"
            L.append(f"| {FEAT_CN[x['rule']]} | {NAME_OF.get(x['ledger'], '全体(不含土豆0)' if x['ledger'] == '*' else x['ledger'])} | {ycn.get(x.get('outcome'), '—')} | "
                     f"{x['n_on']}{ron} | {x['n_off']}({x.get('ctrl')}) | {x['note']} | {x.get('claim') or ''} |")
            continue
        L.append(f"| {FEAT_CN[x['rule']]} | {NAME_OF.get(x['ledger'], '全体(不含土豆0)' if x['ledger'] == '*' else x['ledger'])} | {ycn[x['outcome']]} | {x['n_on']} / {x['rate_on']:.0%} | "
                 f"{x['n_off']}({x['ctrl']}) / {x['rate_off']:.0%} | {x['diff']:+.0%} [{x['ci'][0]:+.0%}, {x['ci'][1]:+.0%}] | {x['claim']} |")
    L += ["", "## 全局系数(最终模型, 标准化特征; L2 列 = 减/不动/加 三类的对称系数)", "", "| 特征 | L1 出手 | L2 减 / 不动 / 加 |", "|---|---|---|"]
    c1, c2 = res["layers"]["L1"]["coefs"], res["layers"]["L2"]["coefs"]
    for f in FEATS:
        a = c1.get(f)
        b = c2.get(f)
        L.append(f"| {FEAT_CN[f]} | {fmt_f(a, 2, True)} | {' / '.join(fmt_f(x, 2, True) for x in b) if b else '—'} |")
    L.append("")
    return "\n".join(L)


# ====================================================================================
# 六、预测(--predict) 与 基线建议
# ====================================================================================
def all_bases(rows):
    return {2: expanding_baselines(rows, 2, "y1", "trade_prev"), 3: expanding_baselines(rows, 3, "y2", "dir_prev")}


PERSONA_CHECK = [   # (规则特征, 出处导师, 结果标签, 对照组条件, 画像断言的方向)
    ("p_overnight", ["zhiyingjuexin", "lianghuaxiaohao", "stzhilang", "liuyiqing"], "y_sell", "有仓非隔夜", "隔夜仓日卖出率更高"),
    ("p_empty1", ["zhiyingjuexin", "bianbenling"], "y_buy", "空仓≥2天", "空仓只停一晚: 空仓第 1 天次日买入率高(芷影应≈从不连续空仓)"),
    ("p_empty2_5", ["stzhilang", "liuyiqing"], "y_buy", "空仓第1天", "空仓 1~5 日后再入场: 2~5 天的买入率不低于第 1 天"),
    ("p_bigloss", ["bianbenling", "xingjianye", "zhiyingjuexin", "antoo"], "y1", "非大亏日", "边学/星见野: 大亏次日更少出手; 芷影/antoo: 无刹车(不更少)"),
    ("p_preholiday", ["lianghuaxiaohao"], "y_red", "其他交易日", "长假前不降仓(净减率不更高)"),
]


def persona_check(rows):
    """画像假设的账本直检(全样本描述统计, 非样本外): 规则成立日 vs 对照日 的结果率差 + 两比例差的 95% 区间"""
    out = []
    lab = [dict(r, y_red=int(r["y2"] == 0)) for r in rows if r["y1"] is not None and not r["stale"]]
    for feat, who, ykey, ctrl, claim in PERSONA_CHECK:
        for l in who + ["*"]:
            # 全体剔不吃土豆0: 转债日内 T, 收盘恒空仓却天天买, 「空仓」对他是结构性的, 会污染空仓类规则
            xs = [r for r in lab if (r["ledger"] == l if l != "*" else r["ledger"] != "buchitudou0")]
            on = [r for r in xs if r["x"][feat]]
            if feat == "p_overnight":
                off = [r for r in xs if not r["x"][feat] and r["tp_prev"] >= 0.05]
            elif feat == "p_empty1":
                off = [r for r in xs if r["x"]["empty"] and not r["x"][feat]]
            elif feat == "p_empty2_5":
                off = [r for r in xs if r["x"]["p_empty1"]]
            else:
                off = [r for r in xs if not r["x"][feat]]
            a = [r[ykey] for r in on]
            b = [r[ykey] for r in off]
            if not a or not b:
                out.append({"rule": feat, "ledger": l, "n_on": len(a), "n_off": len(b), "note": "对照组为空" if a else "样本不足",
                            "rate_on": float(np.mean(a)) if a else None, "outcome": ykey, "ctrl": ctrl, "claim": claim})
                continue
            pa, pb = float(np.mean(a)), float(np.mean(b))
            se = math.sqrt(pa * (1 - pa) / len(a) + pb * (1 - pb) / len(b)) or 1e-9
            out.append({"rule": feat, "ledger": l, "outcome": ykey, "ctrl": ctrl, "claim": claim, "n_on": len(a), "n_off": len(b),
                        "rate_on": pa, "rate_off": pb, "diff": pa - pb, "ci": (pa - pb - 1.96 * se, pa - pb + 1.96 * se)})
    return out


def layer_choices(ev, before=None):
    """从评估记录(只取 date < before)重算每位导师每层的出单来源; 无记录 → 延续"""
    ch = defaultdict(dict)
    for layer in ("L1", "L2"):
        recs = [x for x in ev["layers"][layer]["records"] if before is None or x["date"] < before]
        S = summarize_layer(recs, ["full"])
        for l in LEDGERS:
            ch[l][layer] = S[l]["choice"] if l in S else "延续"
            ch[l][layer + "_n"] = S[l]["n"] if l in S else 0
    recs = [x for x in ev["layers"]["L4"]["records"] if before is None or x["date"] < before]
    S = summarize_tp(recs)
    for l in LEDGERS:
        ch[l]["L4"] = S[l]["choice"] if l in S else "延续"
    recs = [x for x in ev["layers"]["L3"].get("records", []) if before is None or x["date"] < before]
    S = summarize_play(recs) if recs else {}
    for l in LEDGERS:
        ch[l]["L3"] = S[l]["choice"] if l in S else "常数"
        ch[l]["size"] = S[l]["size_choice"] if l in S else "常数"
    return dict(ch)


class DayModels:
    """D 日用的全部模型: L1/L2 用 < D 的标签训练; L4/L3 表用 < D 的数据"""

    def __init__(self, rows, events, D, lam1, lam2, bases, choice3=None):
        self.bases = bases
        self.lam1, self.lam2 = lam1, lam2
        self.choice3 = choice3 or {}
        tr1 = labeled(rows, "y1", hi=D)
        tr2 = labeled(rows, "y2", hi=D)
        F1, m1 = feat_matrix(tr1)
        F2, m2 = feat_matrix(tr2)
        self.m1 = make_model(2, "full", lam1).fit(F1, m1, np.array([r["y1"] for r in tr1]), offsets(tr1, bases[2], "full", lam1))
        self.m2 = make_model(3, "full", lam2).fit(F2, m2, np.array([r["y2"] for r in tr2]), offsets(tr2, bases[3], "full", lam2))
        past = [r for r in rows if r["date"] < D]
        self.tp = TPTable(past)
        self.play = PlayTable([e for e in events if e["date"] < D])
        self.base1 = defaultdict(list)
        self.base2 = defaultdict(list)
        self.nets = defaultdict(lambda: {"add": [], "red": []})
        self.nopen = defaultdict(Counter)
        for r in tr1:
            self.base1[r["ledger"]].append(r["y1"])
        for r in tr2:
            if r["y1"]:
                self.base2[r["ledger"]].append(r["y2"])
            if r["net"] is not None and r["y2"] == 2:
                self.nets[r["ledger"]]["add"].append(r["net"])
            if r["net"] is not None and r["y2"] == 0:
                self.nets[r["ledger"]]["red"].append(-r["net"])
        for e in events:
            if e["date"] < D:
                self.nopen[e["ledger"]][e["date"]] += 1

    def predict_row(self, r):
        F, mids = feat_matrix([r])
        p1 = self.m1.predict(F, mids, offsets([r], self.bases[2], "full", self.lam1))[0]
        p2 = self.m2.predict(F, mids, offsets([r], self.bases[3], "full", self.lam2))[0]
        tpp = self.tp.predict(r["ledger"], r["tp_prev"], r["reg"])
        tpc = self.tp.const(r["ledger"])
        pd_, pm, nm = self.play.dist(r["ledger"], r["reg"])
        src3 = self.choice3.get(r["ledger"], {}).get("L3", "常数")
        pd_ = pd_ if src3 == "模型" else pm
        notrade = float(p1[0])
        cond = np.array([p2[0], max(0.0, p2[1] - notrade), p2[2]])
        cond = cond / cond.sum() if cond.sum() > 0 else np.array([0, 1, 0.0])
        return {"p_trade": float(p1[1]), "p_dir": [float(x) for x in p2], "p_dir_given_trade": [float(x) for x in cond],
                "tp_model": tpp, "tp_const": tpc, "play": pd_, "play_src": src3, "play_n": nm,
                "p_markov_trade": float(self.bases[2][id(r)][1][1]), "p_markov_dir": [float(x) for x in self.bases[3][id(r)][1]]}

    def const_trade(self, l):
        xs = self.base1.get(l) or []
        return (np.mean(xs) if xs else 0.5) > 0.5

    def const_dir(self, l):
        xs = self.base2.get(l) or []
        return (Counter(xs).most_common(1)[0][0] - 1) if xs else 0

    def step_size(self, l, kind):
        xs = self.nets[l][kind]
        return float(np.median(xs)) if len(xs) >= 3 else 0.2

    def n_new(self, l):
        c = self.nopen.get(l)
        return int(min(3, max(1, round(np.median(list(c.values())))))) if c else 1

    def size_for(self, l, play, reg):
        """新开仓单票仓位: 选源=模型 → 打法×市况表; 否则导师中位数(都带回退)"""
        if self.choice3.get(l, {}).get("size") == "模型":
            return self.play.size(l, play, reg)
        return self.play.size(l, "?", -1)      # (l,"?",-1)/(l,"?") 不存在 → 回退到 导师 → 群体


def decide(r, pr, ch, DM):
    """基线决策: L1 出不出手 → L2 方向(条件于出手) → L4 目标总仓。返回 dict(全部用 D-1 可知信息)"""
    l = r["ledger"]
    src1, src2, src4 = ch.get("L1", "延续"), ch.get("L2", "延续"), ch.get("L4", "延续")
    if src1 == "模型":
        trade = pr["p_trade"] > 0.5
    elif src1 == "延续":
        trade = bool(r["trade_prev"])
    else:
        trade = DM.const_trade(l)
    if src2 == "模型":
        dirn = int(np.argmax(pr["p_dir_given_trade"])) - 1
    elif src2 == "延续":
        dirn = int(r["dir_prev"])
    else:
        dirn = DM.const_dir(l)
    if src4 == "模型":
        tp_hat = pr["tp_model"]["tp_hat"]
    elif src4 == "延续":
        tp_hat = r["tp_prev"]
    else:
        tp_hat = pr["tp_const"]["tp_hat"]
    # 三层对齐: L1/L2 是主决策, L4 只给幅度。不出手/不动 → 目标=昨仓; 加/减但 L4 目标方向相反 → 昨仓 ± 导师典型步长
    tp0, dd = r["tp_prev"], (dirn if trade else 0)
    if dd == 1:
        tp_final = tp_hat if tp_hat > tp0 + 0.02 else tp0 + DM.step_size(l, "add")
    elif dd == -1:
        tp_final = tp_hat if tp_hat < tp0 - 0.02 else max(0.0, tp0 - DM.step_size(l, "red"))
    else:
        tp_final = tp0
    return {"trade": bool(trade), "dir": dd, "tp_hat": float(tp_hat), "tp_target_cap": float(min(tp_hat, TP_CAP)),
            "tp_final": float(tp_final), "tp_final_cap": float(min(tp_final, TP_CAP)),
            "src": {"L1": src1, "L2": src2, "L4": src4}, "add_step": DM.step_size(l, "add"), "red_step": DM.step_size(l, "red"),
            "n_new": DM.n_new(l)}


def run_predict(D, refresh=False):
    M, MF, reals, rows = load_world(extra_day=D)
    events = [e for l in LEDGERS for e in mentor_events(l, M)]
    ev = load_or_eval(M, rows, events, D, refresh)
    ch = layer_choices(ev, before=D)
    lam1, lam2 = tuple(ev["layers"]["L1"]["lam"]), tuple(ev["layers"]["L2"]["lam"])
    DM = DayModels(rows, events, D, lam1, lam2, all_bases(rows), ch)
    out = {"date": D, "generated_at": dt.datetime.now().isoformat(timespec="seconds"), "feature_day": M.dates[M.row_before(D)],
           "eval_used": ev.get("_file"), "note": "全部只用 D 之前数据; 概率=样本外校准过的统计模型; 用什么出单=该层样本外评估(仅 D 之前记录)的胜者",
           "mentors": {}}
    for l in LEDGERS:
        rr = [r for r in rows if r["ledger"] == l and r["date"] == D]
        if not rr:
            out["mentors"][l] = {"name": NAME_OF.get(l, l), "note": f"无 D-1 状态(真人数据最新 {reals[l].last if l in reals else None}, 滞后超过 {STALE_MAX} 交易日)"}
            continue
        r = rr[0]
        pr = DM.predict_row(r)
        dc = decide(r, pr, ch[l], DM)
        top = sorted(pr["play"].items(), key=lambda kv: -kv[1])[:6]
        out["mentors"][l] = {
            "name": NAME_OF.get(l, l), "state_day": r["prev"], "stale_days": r["stale"], "regime": REG_CN[r["reg"]],
            "state": {"tp_prev": round(r["tp_prev"], 3), "n_hold": int(r["x"]["n_hold"]), "trade_prev": bool(r["trade_prev"]),
                      "dir_prev": DIR_CN[r["dir_prev"] + 1], "persona_flags": [FEAT_CN[p] for p in PERSONA if r["x"][p]]},
            "L1": {"p_trade": round(pr["p_trade"], 3), "source": ch[l]["L1"]},
            "L2": {"p_dir": dict(zip(DIR_CN, [round(x, 3) for x in pr["p_dir"]])),
                   "p_dir_given_trade": dict(zip(DIR_CN, [round(x, 3) for x in pr["p_dir_given_trade"]])), "source": ch[l]["L2"]},
            "L4": {"tp_hat": round(pr["tp_model"]["tp_hat"], 3), "p25": round(pr["tp_model"]["p25"], 3), "p75": round(pr["tp_model"]["p75"], 3),
                   "bin_hat": ["空", "轻", "半", "重", "满"][pr["tp_model"]["bin_hat"]], "cell": pr["tp_model"]["cell"], "source": ch[l]["L4"]},
            "L3": {"play_dist": {k: round(v, 3) for k, v in top}, "n_events": pr["play_n"],
                   "size_by_play": {k: {kk: (round(vv, 3) if isinstance(vv, float) else vv) for kk, vv in DM.play.size(l, k, r["reg"]).items()} for k, _ in top[:3]}},
            "baseline_suggestion": {"trade": dc["trade"], "dir": DIR_CN[dc["dir"] + 1], "tp_target": round(dc["tp_final"], 3),
                                    "tp_target_no_margin": round(dc["tp_final_cap"], 3), "tp_l4_raw": round(dc["tp_hat"], 3),
                                    "n_new_if_buy": dc["n_new"], "pool": f"scripts/tzzb/pools/{D}.json(mentor_fingerprint --pool --date {D})",
                                    "src": dc["src"]},
        }
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{D}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[predict] → {p}")
    return out


def load_or_eval(M, rows, events, cutoff, refresh=False):
    """复用最近一次评估缓存。无后见的理由: 调用方一律经 layer_choices(ev, before=D) 只取 date < D 的样本外记录,
    而这些记录与评估截止日无关(调参窗固定在 TUNE_VALID_END 之前, 重训块边界相同, 每块只用块首日前的标签);
    λ 只由调参窗决定。缓存不存在(或 --refresh)才现跑一次(截止=目标日)。"""
    OUT.mkdir(parents=True, exist_ok=True)
    cands = sorted(OUT.glob("eval_*.json"))
    if cands and not refresh and cutoff >= TUNE_VALID_END:
        ev = json.loads(cands[-1].read_text(encoding="utf-8"))
        if ev.get("split", {}).get("eval_start") == EVAL_START and ev.get("split", {}).get("refit") == REFIT:
            ev["_file"] = str(cands[-1].relative_to(ROOT))
            return ev
    ev = run_eval(M, rows, events, cutoff)
    write_eval(ev, OUT / f"eval_{cutoff}")
    ev["_file"] = str((OUT / f"eval_{cutoff}.json").relative_to(ROOT))
    return ev


def write_eval(res, stem):
    stem = Path(stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    Path(str(stem) + ".json").write_text(json.dumps(res, ensure_ascii=False, indent=0, default=lambda o: sorted(o) if isinstance(o, set) else str(o)), encoding="utf-8")
    Path(str(stem) + ".md").write_text(eval_markdown(res), encoding="utf-8")
    log(f"[eval] → {stem}.json/.md")


# ====================================================================================
# 七、基线虚拟账户
# ====================================================================================
def fee(side, amt):
    f = max(CONFIG["minFee"], amt * CONFIG["feeRate"])
    return f + (amt * CONFIG["stampTax"] if side == "SELL" else 0.0)


def lot_qty(code, amount, price):
    if price <= 0 or amount <= 0:
        return 0
    q = int(amount / price / 100) * 100
    if str(code).startswith("688") and q < 200:
        return 0
    return q


def bar_of(M, code, i):
    j = jidx(M, code)
    if j is None or i is None or not M.has[i, j]:
        return None
    lu = M.lu[i, j]
    ld = M.ld[i, j]
    return {"o": float(M.O[i, j]), "h": float(M.H[i, j]), "l": float(M.L[i, j]), "c": float(M.C[i, j]),
            "lu": float(lu) if np.isfinite(lu) else None, "ld": float(ld) if np.isfinite(ld) else None}


TIMING = {}   # 10/21 晚(用户: BL 账户只按开盘撮合、没有盘中时机 → 补): ledger → {"buy": 买点日内位置中位, "sell": 卖点日内位置中位}; 空 = 开盘撮合(原口径)


def timing_of(ledger):
    """导师真人买 / 卖在当日区间里的典型位置(fills_rt.jsonl 的 pos_so_far 中位, 0 = 日内最低 1 = 最高); 样本 < 15 = None(退回开盘价)"""
    import statistics as st_
    f = ROOT / "skills" / f"{ledger}-skill" / "persona" / "fills_rt.jsonl"
    b, s_ = [], []
    try:
        for line in f.read_text(encoding="utf-8").splitlines():
            x = json.loads(line)
            v = (x.get("rt") or {}).get("pos_so_far")
            if v is None:
                continue
            (b if x.get("side") == "买" else s_).append(float(v))
    except (OSError, ValueError):
        return None
    return {"buy": st_.median(b) if len(b) >= 15 else None, "sell": st_.median(s_) if len(s_) >= 15 else None, "nb": len(b), "ns": len(s_)}


def fill_at_pos(bar, pos, side):
    """按导师典型日内位置成交: 价 = 最低 + 位置 × (最高 − 最低); 撞涨停(买) / 跌停(卖)就按板价; 近似(用了当日高低, 只代表"导师一般在什么位置出手")"""
    px = bar["l"] + max(0.0, min(1.0, pos)) * (bar["h"] - bar["l"])
    if side == "BUY" and bar["lu"] is not None and px >= bar["lu"] - 0.001:
        return bar["lu"], f"导师典型买点位置 {pos:.2f} 撞涨停, 按涨停价"
    if side == "SELL" and bar["ld"] is not None and px <= bar["ld"] + 0.001:
        return bar["ld"], f"导师典型卖点位置 {pos:.2f} 撞跌停, 按跌停价"
    return round(px, 3), f"导师典型{'买' if side == 'BUY' else '卖'}点日内位置 {pos:.2f}"


def fill_buy(bar, pos=None):
    """开盘市价买(保守): 全天封涨停(最低≥涨停价) → 买不到; 开盘即涨停但盘中开过板 → 涨停价成交; 其余 → 开盘价。返回 (价, 原因)
    pos 给了(时机版 BLT): 不封死时按导师典型买点日内位置成交"""
    if bar is None or not (bar["o"] > 0):
        return None, "无行情/停牌"
    if bar["lu"] is not None and bar["l"] >= bar["lu"] - 0.001:
        return None, f"全天封涨停 {bar['lu']} 买不到"
    if pos is not None:
        return fill_at_pos(bar, pos, "BUY")
    if bar["lu"] is not None and bar["o"] >= bar["lu"] - 0.001:
        return bar["lu"], "开盘涨停、盘中开板, 按涨停价"
    return bar["o"], "开盘价"


def fill_sell(bar, pos=None):
    if bar is None or not (bar["o"] > 0):
        return None, "无行情/停牌"
    if bar["ld"] is not None and bar["h"] <= bar["ld"] + 0.001:
        return None, f"全天封跌停 {bar['ld']} 卖不出"
    if pos is not None:
        return fill_at_pos(bar, pos, "SELL")
    if bar["ld"] is not None and bar["o"] <= bar["ld"] + 0.001:
        return bar["ld"], "开盘跌停、盘中开板, 按跌停价"
    return bar["o"], "开盘价"


class Account:
    def __init__(self, src):
        self.src = src
        self.cash = CONFIG["initCash"]
        self.pos = {}          # code → {qty, cost, since}
        self.trades, self.nav, self.orders, self.daily = [], [], [], []
        self.ever = False
        self.seq = 0

    def mv(self, M, i, px_fallback=True):
        s = 0.0
        for c, p in self.pos.items():
            b = bar_of(M, c, i)
            s += p["qty"] * (b["c"] if b else p["cost"])
        return s

    def _tid(self, D):
        self.seq += 1
        return f"{D}-{self.src}-{self.seq:03d}"

    def buy(self, D, code, amount, bar, why):
        px, how = fill_buy(bar, (TIMING.get(self.src.split("-", 1)[1]) or {}).get("buy") if self.src.startswith("BLT-") else None)
        o = {"date": D, "side": "BUY", "code": code, "amount": round(amount, 2), "why": why}
        if px is None:
            o.update(status="reject", note=how)
            self.orders.append(o)
            return None
        q = lot_qty(code, min(amount, self.cash - 10), px)
        while q > 0 and q * px + fee("BUY", q * px) > self.cash:
            q -= 100
        if q <= 0:
            o.update(status="reject", note="资金不足一手")
            self.orders.append(o)
            return None
        amt = q * px
        f = fee("BUY", amt)
        self.cash -= amt + f
        p = self.pos.get(code, {"qty": 0, "cost": 0.0, "since": D})
        p["cost"] = (p["cost"] * p["qty"] + amt + f) / (p["qty"] + q)
        p["qty"] += q
        self.pos[code] = p
        t = {"id": self._tid(D), "side": "BUY", "code": code, "price": round(px, 3), "qty": q, "fee": round(f, 2), "why": f"{why} | {how}"}
        self.trades.append(t)
        o.update(status="filled", price=px, qty=q)
        self.orders.append(o)
        self.ever = True
        return t

    def sell(self, D, code, qty, bar, why):
        px, how = fill_sell(bar, (TIMING.get(self.src.split("-", 1)[1]) or {}).get("sell") if self.src.startswith("BLT-") else None)
        o = {"date": D, "side": "SELL", "code": code, "qty": qty, "why": why}
        p = self.pos.get(code)
        if p is None or p["since"] >= D:       # T+1: 当日买入不可卖(本账户买卖都在开盘, 这里只是兜底)
            o.update(status="reject", note="T+1/无持仓")
            self.orders.append(o)
            return None
        if px is None:
            o.update(status="reject", note=how)
            self.orders.append(o)
            return None
        qty = min(qty, p["qty"])
        amt = qty * px
        f = fee("SELL", amt)
        self.cash += amt - f
        p["qty"] -= qty
        if p["qty"] <= 0:
            del self.pos[code]
        t = {"id": self._tid(D), "side": "SELL", "code": code, "price": round(px, 3), "qty": qty, "fee": round(f, 2), "why": f"{why} | {how}"}
        self.trades.append(t)
        o.update(status="filled", price=px)
        self.orders.append(o)
        return t


def preopen_play(M, j, p):
    """候选票在 D 开盘前的打法(按昨收买入假设, 只用 D-1 收盘状态; 「首板打板/追涨/突破新高」需要成交价, 盘前判不出)"""
    with np.errstate(all="ignore"):
        f = {"asset": M.asset[j], "data": bool(M.has[p, j]), "H_prev": int(M.Hn[p, j]), "zb_prev": bool(M.zb[p, j]),
             "zt_age_prev": int(M.zt_age[p, j]) if M.zt_age[p, j] < 99 else None, "nbars_prev": int(M.nbars[p, j]),
             "brk20": False, "buy_pct": 0.0, "at_limit": False,
             "ret20_prev": fp._f(M.ret[20][p, j]), "ret5_prev": fp._f(M.ret[5][p, j]), "pos20_prev": fp._f(M.pos20[p, j]),
             "above_ma20_prev": bool(M.adjC[p, j] > M.ma[20][p, j]), "ma20_up_prev": bool(M.ma20_up[p, j]),
             "price_vs_ma5_prev": fp._f(M.adjC[p, j] / M.ma[5][p, j] - 1)}
    return fp.classify_play(f)[0]


def pick_stocks(M, pool, play_dist, k, exclude, p):
    """按打法挑票: 打法按 P(打法|市况) 从高到低, 在池里找盘前打法相符的最高分票; 凑不够就按池分数补"""
    cands = [x for x in pool if x["code"] not in exclude]
    for x in cands:
        j = M.sidx.get(x["symbol"])
        x["_play"] = preopen_play(M, j, p) if j is not None else "数据缺失"
    picks, used = [], set()
    for play, _pp in sorted(play_dist.items(), key=lambda kv: -kv[1]):
        if len(picks) >= k:
            break
        for x in cands:
            if x["code"] in used or x["_play"] != play:
                continue
            picks.append((x, play, "按打法"))
            used.add(x["code"])
            break
    for x in cands:
        if len(picks) >= k:
            break
        if x["code"] not in used:
            picks.append((x, x["_play"], "池分数补位"))
            used.add(x["code"])
    return picks[:k]


def run_baseline_books(since, until=None, refresh=False, timing=False):
    M, MF, reals, rows = load_world()
    until = until or M.dates[-1]
    days = [d for d in M.dates if since <= d <= until]
    events = [e for l in LEDGERS for e in mentor_events(l, M)]
    ev = load_or_eval(M, rows, events, since, refresh)
    ch = layer_choices(ev, before=since)
    lam1, lam2 = tuple(ev["layers"]["L1"]["lam"]), tuple(ev["layers"]["L2"]["lam"])
    if timing:   # 时机版: 同一套决策, 成交价换成导师典型日内位置(BLT-<导师>), 和开盘版 BL 并排比
        TIMING.update({l: timing_of(l) or {} for l in LEDGERS})
    accts = {l: Account(("BLT-" if timing else "BL-") + l) for l in LEDGERS if l not in NO_ACCOUNT}
    rowmap = {(r["ledger"], r["date"]): r for r in rows}
    bases = all_bases(rows)
    for D in days:
        log(f"[baseline] {D}")
        DM = DayModels(rows, events, D, lam1, lam2, bases, ch)
        i = M.didx[D]
        p = i - 1
        for l, A in accts.items():
            r = rowmap.get((l, D))
            rec = {"date": D, "orders": []}
            if r is None:
                rec["note"] = f"无导师 D-1 状态(滞后>{STALE_MAX} 交易日), 不出单"
            else:
                trade_day(A, l, r, D, i, p, M, DM, ch, rec)
            mv = A.mv(M, i)
            nav = A.cash + mv
            A.nav.append({"date": D, "cash": round(A.cash, 2), "mv": round(mv, 2), "nav": round(nav, 2),
                          "filled": sum(1 for o in rec["orders"] if o["filled"]), "orders": len(rec["orders"])})
            A.daily.append(rec)
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    gen = dt.datetime.now().isoformat(timespec="seconds")
    for l, A in accts.items():
        book = {"source": A.src, "kind": "baseline", "ledger": l, "name": NAME_OF.get(l, l), "generated_at": gen, "since": since, "until": until,
                "note": "基线虚拟账户(统计模型/延续/常数出 L1·L2·L4 + fingerprint 池按打法挑票), 不进 books/、不进 matcher SOURCES; 开盘撮合保守口径见 mentor_model.py",
                "layer_choice": ch[l], "eval_used": ev.get("_file"), "config": CONFIG,
                "cash": round(A.cash, 2), "positions": {c: {"qty": p["qty"], "cost": round(p["cost"], 4), "since": p["since"]} for c, p in A.pos.items()},
                "orders": A.orders, "trades": A.trades, "nav": A.nav, "daily": A.daily}
        (BASE_DIR / f"{A.src}.json").write_text(json.dumps(book, ensure_ascii=False, indent=1, default=lambda o: sorted(o) if isinstance(o, set) else str(o)), encoding="utf-8")
    log(f"[baseline] 账本 → {BASE_DIR}")
    cmp_ = compare_books(M, reals, accts, days, since, until)
    return cmp_


def trade_day(A, l, r, D, i, p, M, DM, ch, rec):
    """一位导师基线账户的一天: 决策(只用 D-1 可知信息) → 开盘先卖后买 → 写 rec"""
    pr = DM.predict_row(r)
    dc = decide(r, pr, ch[l], DM)
    navp = A.cash + A.mv(M, p)
    tp_acct = (navp - A.cash) / navp if navp > 0 else 0.0
    rec.update({"stale": r["stale"], "state_day": r["prev"], "p_trade": round(pr["p_trade"], 3),
                "p_dir_given_trade": [round(x, 3) for x in pr["p_dir_given_trade"]], "decision": dc, "tp_acct_prev": round(tp_acct, 3)})
    sells, buy_amt, why = [], 0.0, ""
    tgt = dc["tp_target_cap"]
    px_prev = lambda c, pp: (bar_of(M, c, p) or {}).get("c") or pp["cost"]  # noqa: E731
    if not A.ever and tgt >= 0.3:
        buy_amt, why = (tgt - tp_acct) * navp, f"建仓对齐: 目标总仓 {tgt:.0%}(账户从未持仓)"
    elif dc["trade"] and dc["dir"] == 1:
        t2 = min(TP_CAP, max(tgt, tp_acct + dc["add_step"]))
        buy_amt, why = (t2 - tp_acct) * navp, f"加仓: 目标总仓 {t2:.0%}"
    elif dc["trade"] and dc["dir"] == -1:
        t2 = max(0.0, min(tgt, tp_acct - dc["red_step"]))
        need = (tp_acct - t2) * navp
        for c, pp in sorted(A.pos.items(), key=lambda kv: kv[1]["since"]):
            if need <= 0:
                break
            cp = px_prev(c, pp)
            q = pp["qty"] if pp["qty"] * cp <= need * 1.2 else max(100, int(need / max(cp, 0.01) / 100) * 100)
            sells.append((c, q, f"减仓: 目标总仓 {t2:.0%}(持有最久优先)"))
            need -= q * cp
    elif dc["trade"] and dc["dir"] == 0 and A.pos:
        c, pp = sorted(A.pos.items(), key=lambda kv: kv[1]["since"])[0]
        sells.append((c, pp["qty"], "换股: 卖持有最久"))
        buy_amt, why = pp["qty"] * px_prev(c, pp), "换股: 等额买入新票"
    for c, q, w in sells:
        t = A.sell(D, c, q, bar_of(M, c, i), w)
        rec["orders"].append({"side": "SELL", "code": c, "filled": t is not None, "why": w,
                              **({"price": t["price"], "qty": t["qty"]} if t else {"note": A.orders[-1].get("note")})})
    if buy_amt > 1000:
        pool_res = fp.build_pool(l, M, D, 30)
        pool = pool_res.get("pool") or []
        if not pool:
            rec["note"] = f"指纹池不可用({pool_res.get('note', '空')}), 不买"
            return
        top_play = max(pr["play"], key=pr["play"].get)
        sz = DM.size_for(l, top_play, r["reg"])["med"]
        k = int(min(3, max(1, round(buy_amt / max(1.0, min(sz, TP_CAP) * navp)))))   # 只数 = 买入额 / 导师典型单票仓位
        rec["sizing"] = {"single_size": round(sz, 3), "k": k, "top_play": top_play}
        picks = pick_stocks(M, pool, pr["play"], k, set(A.pos), p)
        per = min(buy_amt, A.cash * 0.995) / max(1, len(picks))     # 先卖后买: 以卖后现金为上限(卖单可能被跌停拦住)
        for x, play, how in picks:
            t = A.buy(D, x["code"], per, bar_of(M, x["code"], i), f"{why} | 打法 {play}({how}) 池分 {x['score']}")
            rec["orders"].append({"side": "BUY", "code": x["code"], "name": x.get("name"), "play": play, "how": how,
                                  "filled": t is not None, **({"price": t["price"], "qty": t["qty"]} if t else {"note": A.orders[-1].get("note")})})


# ---------- LLM 链 vs 基线账户(mimicry 同口径) ----------
def chain_from_book(path, book, names):
    c = ms.Chain.__new__(ms.Chain)
    b = json.loads(Path(path).read_text(encoding="utf-8"))
    c.book = book
    c.mtime = dt.datetime.fromtimestamp(Path(path).stat().st_mtime).isoformat(timespec="seconds")
    c.trades = sorted(b.get("trades") or [], key=lambda t: str(t.get("id")))
    c.nav = {n["date"]: float(n["nav"]) for n in b.get("nav") or [] if n.get("nav") is not None}
    c.navrec = {n["date"]: n for n in b.get("nav") or []}
    c.names = names
    return c


def prices_for(M, codes, beg):
    i0 = bisect.bisect_left(M.dates, beg)
    closes = {}
    for c in codes:
        j = jidx(M, c)
        if j is None:
            continue
        closes[str(c)] = {M.dates[i]: float(M.C[i, j]) for i in range(i0, len(M.dates)) if np.isfinite(M.C[i, j])}
    return ms.Prices(closes, M.dates)


MAIN4 = ["L1_交易", "L2_方向", "L3_持仓Jaccard", "L4_总仓误差", "L4_总仓分档"]


def compare_books(M, reals, accts, days, since, until):
    names = ms.load(ms.HERE / "names.json") or {}
    names = {**{s[2:]: n for s, n in M.name.items()}, **names}
    beg = (dt.date.fromisoformat(since) - dt.timedelta(days=30)).isoformat()
    res = {"generated_at": dt.datetime.now().isoformat(timespec="seconds"), "since": since, "until": until, "days": days, "pairs": {}, "books_read": {}}
    pooled = defaultdict(list)
    for book, l in ms.PAIRS:
        if l not in accts:
            continue
        bp = ms.BOOKS / f"{book}.json"
        if not bp.exists():
            continue
        llm = chain_from_book(bp, book, names)
        base = chain_from_book(BASE_DIR / f"BL-{l}.json", "BL-" + l, names)
        res["books_read"][book] = llm.mtime
        codes = {str(t["code"]) for t in llm.trades + base.trades}
        for k, rec in reals[l].dp.items():
            if k >= d8(beg):
                codes |= {str(x.get("code")) for x in (rec or {}).get("list") or []}
        px = prices_for(M, codes, beg)
        rows = ms.build_days((book, l), base, reals[l], llm, px, days)
        llm0 = llm.nav_at((dt.date.fromisoformat(since) - dt.timedelta(days=1)).isoformat())
        daily = []
        for d in days:
            bn = base.nav.get(d)
            ln = llm.nav.get(d)
            daily.append({"date": d, "base_ret": None if bn is None else bn / CONFIG["initCash"] - 1,
                          "llm_ret": None if ln is None else ln / llm0 - 1})
        p = {"ledger": l, "name": NAME_OF.get(l, l), "n_days": len(rows), "real_last": reals[l].last,
             "cum": daily[-1] if daily else None, "nav_daily": daily, "metrics": {}, "daily": []}
        for m in ms.METRICS:
            a = ms.aggregate(rows, m)
            kind = a["kind"]
            lv = [r["ctrl"][m] for r in rows if r["ctrl"] and r["ctrl"].get(m) is not None]
            p["metrics"][m] = {"kind": kind, "base": a["chain"], "llm": ms.mean(lv) if lv else None, "persist": a["persist"]["base"],
                               "base_vs_llm": {k: v for k, v in a["ctrl"].items() if k != "diffs"},
                               "base_vs_persist": {k: v for k, v in a["persist"].items() if k != "diffs"}}
            pooled[m] += a["ctrl"]["diffs"]
        for r in rows:
            p["daily"].append({"date": r["date"], "real": ms.brief(r["real"], names), "base": ms.brief(r["chainf"], names),
                               "llm": ms.brief(r["ctrlf"], names) if r["ctrlf"] else None,
                               "score_base": {m: r["chain"][m] for m in MAIN4} if r["chain"] else None,
                               "score_llm": {m: r["ctrl"][m] for m in MAIN4} if r["ctrl"] else None})
        res["pairs"][book] = p
    res["pooled"] = {}
    for m, xs in pooled.items():
        ci = ms.boot_ci(xs)
        res["pooled"][m] = {"n": len(xs), "lift": ms.mean(xs), "ci": ci, "verdict": ms.verdict(ms.mean(xs) or 0, ci, len(xs))}
    stem = BASE_DIR / f"compare_{"timing_" if any(str(getattr(a, "src", "")).startswith("BLT-") for a in accts.values()) else ""}{since}_{until}"   # 时机版另存, 不覆盖开盘版对比
    Path(str(stem) + ".json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=lambda o: sorted(o) if isinstance(o, set) else str(o)), encoding="utf-8")
    Path(str(stem) + ".md").write_text(compare_markdown(res), encoding="utf-8")
    log(f"[compare] → {stem}.md/.json")
    return res


def compare_markdown(res):
    L = [f"# LLM 链 vs 基线虚拟账户 {res['since']}~{res['until']}", "",
         f"> 生成 {res['generated_at']} | books 读取时刻(文件修改时间): " + ", ".join(f"{k} {v}" for k, v in res["books_read"].items()),
         "> 收益: 基线账户 10 万起; LLM 链以 since 前一日 nav 为基。拟人度 = mimicry_score 同口径(真值=导师真人当日)。",
         "> 每格: 基线 / LLM 链 / 延续(参考)。L4 是误差(越低越好)。lift = 基线 − LLM(误差类反号), >0 = 基线更像。", "",
         "| 链 | 导师 | 天 | 累计收益 基线 / LLM | L1 交易一致 | L2 方向一致 | L3 持仓 Jaccard | L4 总仓误差 | L4 分档一致 |", "|---|---|---|---|---|---|---|---|---|"]
    for b, p in res["pairs"].items():
        c = p["cum"] or {}
        cells = []
        for m in MAIN4:
            x = p["metrics"][m]
            k = x["kind"]
            cells.append(f"{ms.fmt(x['base'], k)} / {ms.fmt(x['llm'], k)} / {ms.fmt(x['persist'], k)}")
        L.append(f"| {b} | {p['name']} | {p['n_days']} | {fmt_p(c.get('base_ret'), 2)} / {fmt_p(c.get('llm_ret'), 2)} | " + " | ".join(cells) + " |")
    L += ["", "## 全链合并: 基线 − LLM(按 链×日 配对)", "", "| 指标 | n | lift [95%] | 判定 |", "|---|---|---|---|"]
    for m, v in res["pooled"].items():
        k = ms.METRICS[m][0]
        L.append(f"| {m} | {v['n']} | {ms.fmt_lift(v['lift'], k)} [{ms.fmt_lift(v['ci'][0], k)}, {ms.fmt_lift(v['ci'][1], k)}] | {v['verdict']} |")
    L += ["", "## 逐日(净值收益 + 主指标)", ""]
    for b, p in res["pairs"].items():
        L += [f"### {b}({p['name']}, 真人数据至 {p['real_last']})", "",
              "| 日 | 累计 基线/LLM | 真人 持仓(总仓)/方向 | 基线 持仓(总仓)/方向 | LLM 持仓(总仓)/方向 | L1 基/L | L2 基/L | L3 基/L | L4误差 基/L |", "|---|---|---|---|---|---|---|---|---|"]
        nd = {x["date"]: x for x in p["nav_daily"]}
        dn = {1: "加", -1: "减", 0: "平", None: "?"}
        sh = lambda f: "—" if not f else f"{'、'.join(f['hold'][:3]) or '空'}({f['tp']:.0%})/{dn[f['dir']]}"  # noqa: E731
        for x in p["daily"]:
            sb, sl = x["score_base"] or {}, x["score_llm"] or {}
            n = nd.get(x["date"], {})
            g = lambda s, m, k="acc": ms.fmt(s.get(m), k)  # noqa: E731
            L.append(f"| {x['date'][5:]} | {fmt_p(n.get('base_ret'), 1)}/{fmt_p(n.get('llm_ret'), 1)} | {sh(x['real'])} | {sh(x['base'])} | {sh(x['llm'])} | "
                     f"{g(sb, 'L1_交易')}/{g(sl, 'L1_交易')} | {g(sb, 'L2_方向')}/{g(sl, 'L2_方向')} | {g(sb, 'L3_持仓Jaccard', 'sim')}/{g(sl, 'L3_持仓Jaccard', 'sim')} | "
                     f"{g(sb, 'L4_总仓误差', 'err')}/{g(sl, 'L4_总仓误差', 'err')} |")
        L.append("")
    return "\n".join(L)


# ====================================================================================
# 八、自测(构造数据, 不读真实文件)
# ====================================================================================
def selftest():
    ok = [0, 0]

    def check(name, cond):
        ok[1] += 1
        ok[0] += bool(cond)
        print(("  PASS " if cond else "  FAIL ") + name)
    rng = np.random.default_rng(7)
    print("[逻辑回归 + 正则]")
    N = 3000
    X = rng.normal(size=(N, 3))
    beta = np.array([1.5, -1.0, 0.0])
    y = (rng.random(N) < _sigmoid(X @ beta - 0.3)).astype(float)
    Xd = np.hstack([np.ones((N, 1)), X])
    b = fit_logit(Xd, y, np.array([1e-3, 1e-3, 1e-3, 1e-3]))
    check("二分类恢复系数(符号对, 误差<0.15)", np.all(np.abs(b[1:] - beta) < 0.15) and abs(b[0] + 0.3) < 0.15)
    b2 = fit_logit(Xd, y, np.array([1e-3, 1e4, 1e4, 1e4]))
    check("强 L2 正则把斜率压向 0", np.all(np.abs(b2[1:]) < 0.1 * np.abs(b[1:]).max()))
    yk = np.argmax(np.stack([X[:, 0], -X[:, 0], 0.5 * X[:, 1]], 1) * 2 + rng.gumbel(size=(N, 3)), 1)
    W = fit_softmax(Xd, yk, 3, np.full(4, 1e-2))
    P = _softmax(Xd @ W)
    check("多分类概率和=1", np.allclose(P.sum(1), 1))
    check("多分类准确率显著高于多数类", np.mean(P.argmax(1) == yk) > Counter(yk.tolist()).most_common(1)[0][1] / N + 0.15)
    print("[部分池化]")
    # 3 位导师: A/B 样本多, C 只有 12 个; 真实截距偏移 C=+1.5; 共同斜率 1.0
    rowsF, mids, ys = [], [], []
    for m, n, off in ((0, 800, -0.5), (1, 800, 0.5), (2, 12, 1.5)):
        x = rng.normal(size=(n, 1))
        p = _sigmoid(1.0 * x[:, 0] + off)
        rowsF.append(np.hstack([x, np.zeros((n, len(FEATS) - 1))]))
        mids += [m] * n
        ys.append((rng.random(n) < p).astype(int))
    F = np.vstack(rowsF)
    mids = np.array(mids)
    y = np.concatenate(ys)
    pm = PooledLR(2, [0], ["A", "B", "C"], 3.0, 300.0, 3.0).fit(F, mids, y)
    off = pm.mentor_offsets()
    npm = PooledLR(2, [0], ["A", "B", "C"], BIG, 3.0, 1e-3).fit(F, mids, y)
    off2 = npm.mentor_offsets()
    check("池化: 小样本导师 C 的截距偏移被收缩(|池化| < |不池化|)", abs(off["C"]) < abs(off2["C"]))
    check("池化: 大样本导师 A/B 方向正确(A<B)", off["A"] < off["B"])
    check("池化: 未见过的导师(-1) 走群体预测", np.allclose(pm.predict(F[:2], np.array([-1, -1])).sum(1), 1))
    offp = np.tile([0.2, 0.8], (len(y), 1))
    yb = (rng.random(len(y)) < 0.8).astype(int)          # 标签确实按基线 0.8 生成(全局截距不罚, 用来校准整体偏差)
    heavy = PooledLR(2, [0], ["A", "B", "C"], BIG, BIG, BIG)
    heavy.fit(F, mids, yb, offp)
    hp = heavy.predict(F[:5], mids[:5], offp[:5])
    check("偏移+全部强罚 → 预测≈基线概率(模型嵌套延续基线)", np.allclose(hp[:, 1], 0.8, atol=0.03))
    off3 = np.tile([0.1, 0.7, 0.2], (len(y), 1))
    y3 = rng.choice(3, size=len(y), p=[0.1, 0.7, 0.2])
    h3 = PooledLR(3, [0], ["A", "B", "C"], BIG, BIG, BIG).fit(F, mids, y3, off3)
    check("多分类偏移同理", np.allclose(h3.predict(F[:3], mids[:3], off3[:3]), off3[:3], atol=0.03))
    print("[样本外切分无泄漏]")
    rows = []
    base = dt.date(2026, 1, 5)
    ds = [(base + dt.timedelta(days=i)).isoformat() for i in range(60)]
    for l in LEDGERS[:3]:
        for i, d in enumerate(ds):
            x = {f: float(rng.normal()) for f in FEATS}
            rows.append({"ledger": l, "date": d, "stale": 0, "x": x, "y1": int(rng.random() < 0.4), "y2": int(rng.integers(0, 3)),
                         "prev_ok": True, "trade_prev": 0, "dir_prev": 0, "reg": 1, "tp_prev": 0.5, "tp": 0.5, "net": 0.0})
    target = ds[40]
    p_a = rolling_predict(rows, 2, "y1", "full", (3.0, 300.0), ds[30], ds[-1], expanding_baselines(rows, 2, "y1", "trade_prev"), refit=5)
    for r in rows:     # 篡改 target 及之后的标签与当日特征以外的未来特征
        if r["date"] >= target:
            r["y1"] = 1 - r["y1"]
            if r["date"] > target:
                r["x"] = {f: 99.0 for f in FEATS}
    p_b = rolling_predict(rows, 2, "y1", "full", (3.0, 300.0), ds[30], ds[-1], expanding_baselines(rows, 2, "y1", "trade_prev"), refit=5)
    same = [np.allclose(p_a[id(r)], p_b[id(r)]) for r in rows if r["date"] == target and id(r) in p_a]
    check("篡改 D 及之后的标签/未来特征, D 日预测不变", same and all(same))
    blk_first = [r for r in rows if r["date"] == ds[30]]
    check("每块训练只用块首日之前的标签(块首日行有预测)", all(id(r) in p_b for r in blk_first))
    eb = expanding_baselines(rows, 2, "y1", "trade_prev")
    r0 = [r for r in rows if r["date"] == ds[0]][0]
    check("扩张基线首日无历史 → 常数=均匀(0.5)", np.allclose(eb[id(r0)][0], [0.5, 0.5]))
    print("[查表回退]")
    T = TPTable([{"ledger": "a", "tp": 0.9, "tp_prev": 0.9, "reg": 1, "stale": 0}] * 3 +
                [{"ledger": "a", "tp": 0.2, "tp_prev": 0.9, "reg": 2, "stale": 0}] * 10)
    pz = T.predict("a", 0.9, 1)
    check("格子 n<8 回退到 导师×昨仓档", pz["cell"] == "导师×昨仓档" and pz["n"] == 13)
    pt = PlayTable([{"ledger": "a", "play": "连板接力", "reg": 1, "size": 0.5}] * 6 + [{"ledger": "b", "play": "转债", "reg": 0, "size": 0.9}] * 20)
    dd, pmm, _ = pt.dist("a", 1)
    check("打法分布: 导师主打法概率最高且和=1", max(dd, key=dd.get) == "连板接力" and abs(sum(dd.values()) - 1) < 1e-9)
    dd2, _, _ = pt.dist("zz", 0)
    check("新导师无样本 → 回退群体(转债最高)", max(dd2, key=dd2.get) == "转债")
    check("仓位表 导师×打法 n≥5 直接用", pt.size("a", "连板接力", 0)["cell"] == "导师×打法")
    print("[虚拟撮合]")
    check("全天封涨停 → 买不到", fill_buy({"o": 11, "h": 11, "l": 11, "c": 11, "lu": 11.0, "ld": 9.0})[0] is None)
    check("开盘涨停盘中开板 → 按涨停价", fill_buy({"o": 11, "h": 11, "l": 10.5, "c": 11, "lu": 11.0, "ld": 9.0})[0] == 11.0)
    check("正常 → 开盘价", fill_buy({"o": 10.2, "h": 10.8, "l": 10.0, "c": 10.5, "lu": 11.0, "ld": 9.0})[0] == 10.2)
    check("全天封跌停 → 卖不出", fill_sell({"o": 9, "h": 9, "l": 9, "c": 9, "lu": 11.0, "ld": 9.0})[0] is None)
    check("一手取整 + 科创板 200 股起", lot_qty("600000", 5000, 10.0) == 500 and lot_qty("688001", 1500, 10.0) == 0)
    A = Account("BL-t")
    bar = {"o": 10.0, "h": 10.5, "l": 9.8, "c": 10.2, "lu": 11.0, "ld": 9.0}
    t = A.buy("2026-10-08", "600000", 50000, bar, "t")
    check("买入扣款 = 金额 + 佣金(最低 5 元)", t and abs(A.cash - (100000 - 5000 * 10.0 - 12.5)) < 1e-6 and t["qty"] == 5000)
    check("T+1: 当日买入当日卖出被拒", A.sell("2026-10-08", "600000", 5000, bar, "t") is None)
    t2 = A.sell("2026-10-09", "600000", 5000, bar, "t")
    check("次日卖出: 佣金+印花税入账", t2 and abs(A.cash - (100000 - 50012.5 + 50000 - 12.5 - 25.0)) < 1e-6 and not A.pos)
    print(f"自测 {ok[0]}/{ok[1]} 通过")
    return ok[0] == ok[1]


# ====================================================================================
def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="导师行为统计模型 + 基线虚拟账户(零 token, 只读)")
    ap.add_argument("--asof", help="只用该日之前的数据做样本外评估(行情面板与账本都截断)")
    ap.add_argument("--predict", action="store_true")
    ap.add_argument("--date")
    ap.add_argument("--baseline-books", action="store_true")
    ap.add_argument("--timing", action="store_true", help="基线账户按导师典型日内买 / 卖位置成交(BLT-<导师>), 不按开盘价")
    ap.add_argument("--since", default="2026-10-08")
    ap.add_argument("--until")
    ap.add_argument("--refresh", action="store_true", help="不复用 model_out/eval_*.json 缓存, 重跑评估")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(0 if selftest() else 1)
    if a.predict:
        run_predict(a.date or dt.date.today().isoformat(), a.refresh)
        return
    if a.baseline_books:
        run_baseline_books(a.since, a.until, a.refresh, timing=a.timing)
        return
    if a.asof:
        M, MF, reals, rows = load_world(asof=a.asof)
        events = [e for l in LEDGERS for e in mentor_events(l, M) if e["date"] < a.asof]
        res = run_eval(M, rows, events, a.asof, asof_label=a.asof)
        write_eval(res, OUT / f"asof_{a.asof}" / f"eval_{a.asof}")
        return
    M, MF, reals, rows = load_world()
    events = [e for l in LEDGERS for e in mentor_events(l, M)]
    cutoff = (dt.date.fromisoformat(M.dates[-1]) + dt.timedelta(days=1)).isoformat()
    res = run_eval(M, rows, events, cutoff)
    write_eval(res, OUT / f"eval_{cutoff}")
    print(eval_markdown(res))


if __name__ == "__main__":
    main()
