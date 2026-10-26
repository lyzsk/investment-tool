# -*- coding: utf-8 -*-
"""range_engine.py — 区间引擎(10/25 夜建; 只读本地文件, 零 token, 不接实盘)

做什么: 给"某只股票 D 日 T 时刻的盘中状态", 在历史 1 分钟数据里找"同状态"样本, 返回之后 N 分钟(30 / 60 / 到收盘)
       最高 / 最低 / 收盘 相对此刻价格的分布(n / P10 / P25 / P50 / P75 / P90 / 均值 / 最差 / 最好), 以及
       "能碰到分时均价 / 开盘价 / 昨收 / 涨停 / 跌停 / 再创新低"的概率。
       用途: 条件单组(bracket_sim.py)的价位分档由这里给, 模型只选方案、分仓位, 不自己推价格数字(10/25 用户)。

严禁偷看未来: 查 D 日 T 时刻 → 样本池 = D 之前的交易日(lookback 天) + D 当天 T 之前已经走完的窗口(只给 30 / 60 分钟口径, 窗口终点 ≤ T);
             此刻状态特征只用 D 当天 ≤ T 的分钟线 + D 之前的日线(箱体 / 振幅)。selftest 会断言这一条。

数据(只读):
  downloads/market/<D>/kline_minute.jsonl      10/09 起关注集 1 分钟 OHLC(tdx; 09:30 那根 = 开盘集合竞价, 这里并进 09:31)
  downloads/market/<D>/kline_day.jsonl         当天日线(昨收 / 开盘 / 涨跌停价)
  downloads/quotes/stock/minute_path/<D>.jsonl 5/28 起股票 240 点收盘价路径(无高低价 → 高 = 低 = 收, 标 src=0 "只有收盘价")
  downloads/market/history/kline_day/<sym>.jsonl 历史日线(只用 高/低 比值算振幅, 用收盘比值算箱体位置; 与复权无关)
缓存: results/_bracket/cache/day_<D>.npz(分钟矩阵) / pool_<D>.npz(样本池分块); 源数据变了加 --rebuild

时间轴: 一天 240 根, k=0 → 09:31(含开盘竞价那一笔), k=119 → 11:30, k=120 → 13:01, k=239 → 15:00; "此刻 HH:MM" = 标签 ≤ HH:MM 的最后一根已走完

状态特征(分桶; 样本不够按 RELAX 顺序逐级放宽, 输出里标 level / dropped):
  lim  0 正常 / 1 封涨停(收盘价=涨停价) / 2 今天碰过涨停、现在开着 / 3 在跌停 / 4 今天碰过跌停、现在离开
  brd  0 主板 10% / 1 创业板科创板 20% / 2 ST 5%
  dev  离分时均价: ≤−3% / −3~−1 / −1~−0.2 / −0.2~+0.5 / +0.5~+2 / >+2(%)
  macd 1 分钟 MACD(12/26/9, 用昨天 240 根预热): 0 绿柱≥3 根 / 1 绿柱 1~2 根 / 2 红柱 1~2 根 / 3 红柱≥3 根
  tb   时段: 09:31~35 / ~45 / ~10:00 / ~10:30 / ~11:30 / 13:01~14:00 / ~15:00
  ddo  开盘后最大跌幅(日内最低 / 开盘 −1): ≤−8% / −8~−5 / −5~−3 / −3~−1 / >−1
  rb   离日内最低的反弹: <0.5% / 0.5~1.5 / 1.5~3 / ≥3
  rsi  RSI6(通达信 SMA 口径): <20 / 20~50 / 50~80 / ≥80
  gap  开盘缺口: ≤−5% / −5~−2 / −2~0 / 0~2 / 2~5 / >5
  vr   量能 = 近 5 根均量 / 之前 30 根均量: <0.7 / 0.7~1.5 / ≥1.5(开盘前 10 根不算, 记 0.7~1.5)
  box  日线 20 日箱体位置(收盘高低): <0 跌出箱体 / 0~1/3 / 1/3~2/3 / 2/3~1 / >1 站上箱体

用法:
  python range_engine.py build [--from 2026-08-01] [--rebuild]      建缓存(第一次约几分钟)
  python range_engine.py query <代码> <D> <HH:MM> [--h 30,60,eod] [--min-n 40] [--lookback 40]
  python range_engine.py selftest                                     断言: 不偷看未来 / 特征因果 / 分布单调
"""
import argparse
import json
import math
import sys
import time
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
MK = ROOT / "downloads" / "market"
MP = ROOT / "downloads" / "quotes" / "stock" / "minute_path"
HD = MK / "history" / "kline_day"
CACHE = ROOT / "results" / "_bracket" / "cache"
NB = 240
STEP = 2                 # 样本池每 2 根取一个时点(相邻时点高度相关, 全取只是放大 n)
HORIZ = (30, 60)         # 固定窗口; 另有 eod = 到收盘

KEYS = ("lim", "brd", "dev", "macd", "tb", "ddo", "rb", "rsi", "gap", "vr", "box")
# 逐级放宽: 每一级 = 这一级还保留的键; tbc = 时段粗分(早盘前 30 分钟 / 上午其余 / 下午)
RELAX = [
    ("lim", "brd", "dev", "macd", "tb", "ddo", "rb", "rsi", "gap", "vr", "box"),
    ("lim", "brd", "dev", "macd", "tb", "ddo", "rb", "rsi", "gap", "vr"),
    ("lim", "brd", "dev", "macd", "tb", "ddo", "rb", "rsi", "gap"),
    ("lim", "brd", "dev", "macd", "tb", "ddo", "rb", "rsi"),
    ("lim", "brd", "dev", "macd", "tb", "ddo", "rb"),
    ("lim", "brd", "dev", "macd", "tb", "ddo"),
    ("lim", "brd", "dev", "macd", "tbc", "ddo"),
    ("lim", "brd", "dev", "macd", "tbc"),
    ("lim", "brd", "dev", "tbc"),
    ("lim", "brd", "dev"),
]
OUTS = ("mx30", "mn30", "cl30", "mx60", "mn60", "cl60", "mxE", "mnE", "clE")
AUX = ("vw_rel", "op_rel", "pc_rel", "up_rel", "dn_rel", "lo_rel")
NAMES = {
    "lim": ["正常", "封涨停", "碰过涨停现在开着", "在跌停", "碰过跌停现在离开"],
    "brd": ["主板10%", "创业板/科创板20%", "ST 5%"],
    "dev": ["离均价≤−3%", "−3%~−1%", "−1%~−0.2%", "−0.2%~+0.5%", "+0.5%~+2%", ">+2%"],
    "macd": ["绿柱≥3根", "绿柱1~2根", "红柱1~2根", "红柱≥3根"],
    "tb": ["09:31~09:35", "09:36~09:45", "09:46~10:00", "10:01~10:30", "10:31~11:30", "13:01~14:00", "14:01~15:00"],
    "tbc": ["开盘30分钟内", "10:01~11:30", "下午"],
    "ddo": ["开盘后最大跌幅≤−8%", "−8%~−5%", "−5%~−3%", "−3%~−1%", ">−1%"],
    "rb": ["离日内最低<0.5%", "0.5%~1.5%", "1.5%~3%", "≥3%"],
    "rsi": ["RSI6<20", "20~50", "50~80", "≥80"],
    "gap": ["开盘缺口≤−5%", "−5%~−2%", "−2%~0", "0~+2%", "+2%~+5%", ">+5%"],
    "vr": ["量能<0.7", "0.7~1.5", "≥1.5"],
    "box": ["跌出20日箱体", "箱体下1/3", "箱体中1/3", "箱体上1/3", "站上箱体"],
}


# ---------------------------------------------------------------- 时间轴 ----------------------------------------------------------------
def hm2k(hm):
    """'HH:MM' → 最后一根已走完的 k(09:30 及以前 → -1)"""
    h, m = int(hm[:2]), int(hm[3:5])
    t = h * 60 + m
    if t < 9 * 60 + 31:
        return -1
    if t <= 11 * 60 + 30:
        return t - (9 * 60 + 31)
    if t < 13 * 60 + 1:
        return 119
    return min(239, 120 + t - (13 * 60 + 1))


def k2hm(k):
    t = (9 * 60 + 31 + k) if k < 120 else (13 * 60 + 1 + k - 120)
    return f"{t // 60:02d}:{t % 60:02d}"


def tb_of(k):
    return np.digitize(k, [5, 15, 30, 60, 120, 180])


def tbc_of(tb):
    return np.where(tb <= 2, 0, np.where(tb <= 4, 1, 2))


def brd_of(code, st=False):
    if st:
        return 2
    return 1 if code[:2] in ("30", "68") else 0


# ---------------------------------------------------------------- 交易日 ----------------------------------------------------------------
@lru_cache(None)
def trade_days():
    ds = {p.stem for p in MP.glob("*.jsonl")}
    ds |= {p.parent.name for p in MK.glob("20*/kline_minute.jsonl")}
    return tuple(sorted(ds))


def prev_day(D):
    ds = trade_days()
    i = np.searchsorted(ds, D)
    return ds[i - 1] if i > 0 else None


def next_day(D):
    ds = trade_days()
    i = np.searchsorted(ds, D, side="right")
    return ds[i] if i < len(ds) else None


@lru_cache(None)
def st_codes():
    out = set()
    for D in reversed(trade_days()):
        f = MK / D / "security_master.jsonl"
        if f.exists():
            for l in f.open(encoding="utf-8"):
                a = json.loads(l)
                if a.get("isSt") or "ST" in (a.get("name") or ""):
                    out.add(a.get("code") or a["symbol"][2:])
            break
    return frozenset(out)


def _lim(code, D, prev):
    try:
        import a_rules as AR
        up, dn = AR.limit_prices(code, D, prev, is_st=code in st_codes())
        if up and dn:
            return float(up), float(dn)
    except Exception:   # noqa: BLE001
        pass
    b = 0.05 if code in st_codes() else (0.2 if code[:2] in ("30", "68") else 0.1)
    return round(prev * (1 + b) + 1e-9, 2), round(prev * (1 - b) + 1e-9, 2)


# ---------------------------------------------------------------- 一天的分钟矩阵 ----------------------------------------------------------------
class Day:
    """一天全部股票的 240 根 1 分钟线(S×240): O/H/L/C/V/A; 每只票 prev / open / up / dn / src(1=OHLC, 0=只有收盘价)"""
    F = ("O", "H", "L", "C", "V", "A")

    def __init__(self, D, codes, arr, prev, opn, up, dn, src):
        self.D, self.codes = D, list(codes)
        self.idx = {c: i for i, c in enumerate(self.codes)}
        self.O, self.H, self.L, self.C, self.V, self.A = arr
        self.prev, self.open, self.up, self.dn, self.src = prev, opn, up, dn, src

    def save(self, f):
        np.savez_compressed(f, codes=np.array(self.codes), arr=np.stack([self.O, self.H, self.L, self.C, self.V, self.A]),
                            prev=self.prev, open=self.open, up=self.up, dn=self.dn, src=self.src)

    @classmethod
    def load_npz(cls, D, f):
        z = np.load(f)
        return cls(D, [str(x) for x in z["codes"]], tuple(z["arr"]), z["prev"], z["open"], z["up"], z["dn"], z["src"])

    def row(self, code):
        i = self.idx.get(code)
        if i is None:
            return None
        return {k: getattr(self, k)[i] for k in self.F} | {"prev": float(self.prev[i]), "open": float(self.open[i]), "up": float(self.up[i]),
                                                           "dn": float(self.dn[i]), "src": int(self.src[i]), "code": code, "D": self.D}


def _stock(code):
    return len(code) == 6 and code[:2] in ("00", "30", "60", "68")


def _build_day(D):
    bars, dayk = {}, {}
    km = MK / D / "kline_minute.jsonl"
    if km.exists():
        for l in km.open(encoding="utf-8"):
            a = json.loads(l)
            c = a["symbol"][2:]
            if not _stock(c):
                continue
            hm = a["barTime"][11:16]
            if hm < "09:30" or hm > "15:00":
                continue
            k = max(0, hm2k(hm))
            b = bars.setdefault(c, {})
            x = (a["open"], a["high"], a["low"], a["close"], a["volume"] or 0, a.get("amount") or 0)
            if hm == "09:30":
                b["auc"] = x
            else:
                b[k] = x
        for c, b in bars.items():   # 09:30 竞价那根并进 09:31(开 = 竞价价, 高低取并, 收 = 09:31 收, 量额相加)
            au = b.pop("auc", None)
            if au is None:
                continue
            if 0 in b:
                o, h, lo, cc, v, am = b[0]
                b[0] = (au[0], max(h, au[1]), min(lo, au[2]), cc, v + au[4], am + au[5])
            else:
                b[0] = au
        kd = MK / D / "kline_day.jsonl"
        if kd.exists():
            for l in kd.open(encoding="utf-8"):
                a = json.loads(l)
                c = a["symbol"][2:]
                if c in bars:
                    dayk[c] = a
    mp = MP / f"{D}.jsonl"
    paths = {}
    if mp.exists():
        for l in mp.open(encoding="utf-8"):
            a = json.loads(l)
            if _stock(a["code"]) and a["code"] not in bars and len(a.get("p") or []) >= 200 and a.get("prev"):
                paths[a["code"]] = a
    codes = sorted(set(bars) | set(paths))
    S = len(codes)
    arr = np.full((6, S, NB), np.nan, dtype=np.float64)
    prev, opn, up, dn = (np.full(S, np.nan) for _ in range(4))
    src = np.zeros(S, dtype=np.int8)
    for i, c in enumerate(codes):
        if c in bars:
            b = bars[c]
            kd_ = dayk.get(c) or {}
            first = b[min(b)]
            pc = kd_.get("preClose") or None
            last_c = None
            for k in range(NB):
                if k in b:
                    o, h, lo, cc, v, am = b[k]
                    last_c = cc
                else:
                    if last_c is None:
                        last_c = first[0]
                    o = h = lo = cc = last_c
                    v = am = 0.0
                arr[:, i, k] = (o, h, lo, cc, v, am)
            src[i] = 1
            opn[i] = kd_.get("open") or first[0]
            if pc:
                prev[i] = pc
            up[i] = kd_.get("limitUp") or np.nan
            dn[i] = kd_.get("limitDown") or np.nan
        else:
            a = paths[c]
            p = np.array(a["p"][:NB], dtype=float)
            v = np.array((a.get("v") or [0] * len(p))[:NB], dtype=float) * 100
            if len(p) < NB:
                p = np.concatenate([p, np.full(NB - len(p), p[-1])])
                v = np.concatenate([v, np.zeros(NB - len(v))])
            arr[0, i] = arr[1, i] = arr[2, i] = arr[3, i] = p
            arr[4, i] = v
            arr[5, i] = p * v
            prev[i] = a["prev"]
            opn[i] = p[0]
        if not np.isfinite(prev[i]):
            prev[i] = opn[i]
        if not (np.isfinite(up[i]) and np.isfinite(dn[i])):
            up[i], dn[i] = _lim(c, D, float(prev[i]))
    return Day(D, codes, tuple(arr), prev, opn, up, dn, src)


_DAYS = {}


def load_day(D, rebuild=False):
    if D in _DAYS and not rebuild:
        return _DAYS[D]
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"day_{D}.npz"
    if f.exists() and not rebuild:
        d = Day.load_npz(D, f)
    else:
        d = _build_day(D)
        d.save(f)
    _DAYS[D] = d
    return d


# ---------------------------------------------------------------- 日线: 振幅 / 箱体(只用 D 之前) ----------------------------------------------------------------
@lru_cache(None)
def _hist_daily(code):
    """{date: (o, h, l, c)}; 历史文件(可能复权, 只用比值) + 10/09 起 market 日线"""
    out = {}
    for pre in ("sh", "sz"):
        f = HD / f"{pre}{code}.jsonl"
        if f.exists():
            lines = f.read_text(encoding="utf-8").splitlines()[-160:]
            for l in lines:
                try:
                    a = json.loads(l)
                    out[a["tradeDate"]] = (a["open"], a["high"], a["low"], a["close"])
                except (ValueError, KeyError):
                    pass
            break
    return out


@lru_cache(None)
def _mk_daily(D):
    f = MK / D / "kline_day.jsonl"
    out = {}
    if f.exists():
        for l in f.open(encoding="utf-8"):
            a = json.loads(l)
            out[a["symbol"][2:]] = (a["open"], a["high"], a["low"], a["close"])
    return out


def daily_before(code, D, n=20):
    """D 之前最近 n 个交易日 (o,h,l,c) 列表(同一来源内比值可比); 优先 market 日线(原始价), 不够再用历史文件"""
    ds = [d for d in trade_days() if d < D][-n:]
    mk = [(_mk_daily(d).get(code)) for d in ds]
    if all(mk) and mk:
        return mk
    h = _hist_daily(code)
    hs = sorted(d for d in h if d < D)[-n:]
    return [h[d] for d in hs]


def amp20(code, D, n=20):
    """D 之前 n 日日内振幅(最高 / 最低 −1)的中位数; 拿不到 → None"""
    rows = daily_before(code, D, n)
    a = [r[1] / r[2] - 1 for r in rows if r and r[2] and r[1]]
    return float(np.median(a)) if len(a) >= 5 else None


def box_ref(code, D, n=20):
    """(箱体低 / 昨收, 箱体高 / 昨收): 用 n 日收盘高低, 与昨收同源比值 → 和原始价可比"""
    rows = daily_before(code, D, n)
    if len(rows) < 5:
        return None
    cs = [r[3] for r in rows]
    return min(cs) / cs[-1], max(cs) / cs[-1]


# ---------------------------------------------------------------- 指标(向量化, 因果) ----------------------------------------------------------------
def _ema_loop(X, n):
    a = 2.0 / (n + 1)
    out = np.empty_like(X)
    e = X[:, 0].copy()
    for t in range(X.shape[1]):
        e = e + a * (X[:, t] - e)
        out[:, t] = e
    return out


def _sma_tdx(X, n, m=1):
    out = np.empty_like(X)
    y = X[:, 0].copy()
    for t in range(X.shape[1]):
        y = (m * X[:, t] + (n - m) * y) / n
        out[:, t] = y
    return out


def macd_rsi(Cseq):
    """Cseq: S×T 收盘(可含昨天预热段) → dif, dea, rsi6 (同形状)"""
    dif = _ema_loop(Cseq, 12) - _ema_loop(Cseq, 26)
    dea = _ema_loop(dif, 9)
    d = np.diff(Cseq, axis=1, prepend=Cseq[:, :1])
    up = _sma_tdx(np.maximum(d, 0), 6)
    ab = _sma_tdx(np.abs(d), 6)
    rsi = np.where(ab > 1e-12, up / np.maximum(ab, 1e-12) * 100, 50.0)
    return dif, dea, rsi


def _runs(mask):
    out = np.zeros(mask.shape, dtype=np.int16)
    r = np.zeros(mask.shape[0], dtype=np.int16)
    for t in range(mask.shape[1]):
        r = np.where(mask[:, t], r + 1, 0).astype(np.int16)
        out[:, t] = r
    return out


def features(day, upto=None, rows=None):
    """day 的因果特征(每个 k 只用 ≤k 的分钟线 + 昨天分钟线预热 + D 之前日线)。upto = 只算到第 upto 根(先截断再算, 用于断言不偷看)
    rows = 只算这些行(索引数组); 返回 dict, 每项 S'×K"""
    rows = np.arange(len(day.codes)) if rows is None else np.asarray(rows)
    K = NB if upto is None else upto + 1
    O, H, L, C, V, A = (getattr(day, f)[rows, :K] for f in Day.F)
    prev, opn, up, dn = day.prev[rows], day.open[rows], day.up[rows], day.dn[rows]
    pd_ = prev_day(day.D)
    if pd_:
        P = load_day(pd_)
        pc = np.array([P.C[P.idx[c]] if c in P.idx else np.full(NB, np.nan) for c in (day.codes[i] for i in rows)])
        pc = np.where(np.isfinite(pc), pc, prev[:, None])
    else:
        pc = np.repeat(prev[:, None], NB, axis=1)
    Cs = np.concatenate([pc, C], axis=1)
    dif, dea, rsi = macd_rsi(Cs)
    dif, dea, rsi = dif[:, NB:], dea[:, NB:], rsi[:, NB:]
    red = _runs(dif > dea)
    green = _runs(dif <= dea)
    cv, ca = np.cumsum(V, axis=1), np.cumsum(A, axis=1)
    vw = np.where(cv > 0, ca / np.maximum(cv, 1e-9), C)
    bad = (vw / C > 1.5) | (vw / C < 0.67)       # 单位异常 → 用收盘
    vw = np.where(bad, C, vw)
    lo = np.minimum.accumulate(np.minimum(L, opn[:, None]), axis=1)
    hi = np.maximum.accumulate(np.maximum(H, opn[:, None]), axis=1)
    kk = np.arange(K)[None, :]
    lo_at = np.maximum.accumulate(np.where(L <= lo + 1e-9, kk, -1), axis=1)
    cs = np.concatenate([np.zeros((len(rows), 1)), np.cumsum(V, axis=1)], axis=1)
    k5 = np.clip(kk - 4, 0, None)
    v5 = (cs[:, kk[0] + 1] - cs[:, k5[0]]) / (kk - k5 + 1)
    k35 = np.clip(kk - 34, 0, None)
    v30 = (cs[:, k5[0]] - cs[:, k35[0]]) / np.maximum(k5 - k35, 1)
    vr = np.where((kk >= 10) & (v30 > 0), v5 / np.maximum(v30, 1e-9), 1.0)
    tol = 0.005
    sealed = C >= up[:, None] - tol
    t_up = np.maximum.accumulate(H >= up[:, None] - tol, axis=1)
    at_dn = C <= dn[:, None] + tol
    t_dn = np.maximum.accumulate(L <= dn[:, None] + tol, axis=1)
    opened = np.zeros_like(sealed)
    opened[:, 1:] = sealed[:, :-1] & (L[:, 1:] < up[:, None] - tol)
    n_open = np.cumsum(opened, axis=1)
    lim = np.where(sealed, 1, np.where(at_dn, 3, np.where(t_up, 2, np.where(t_dn, 4, 0))))
    box = np.full(len(rows), np.nan), np.full(len(rows), np.nan)
    for j, i in enumerate(rows):
        b = box_ref(day.codes[i], day.D)
        if b:
            box[0][j], box[1][j] = b
    r_prev = C / prev[:, None]
    boxpos = (r_prev - box[0][:, None]) / np.maximum(box[1][:, None] - box[0][:, None], 1e-6)
    return {"C": C, "H": H, "L": L, "O": O, "V": V, "vw": vw, "dif": dif, "dea": dea, "rsi": rsi, "red": red, "green": green, "lo": lo, "hi": hi, "lo_at": lo_at,
            "vr": vr, "sealed": sealed, "t_up": t_up, "n_open": n_open, "lim": lim, "boxpos": boxpos, "prev": prev, "open": opn, "up": up, "dn": dn,
            "brd": np.array([brd_of(day.codes[i], day.codes[i] in st_codes()) for i in rows])}


def bucket(F, k=None):
    """特征 → 分桶码(dict of int arrays); k=None 全部时点"""
    sl = (slice(None), slice(None)) if k is None else (slice(None), k)
    C = F["C"][sl]
    o = F["open"] if k is not None else F["open"][:, None]
    p = F["prev"] if k is not None else F["prev"][:, None]
    dev = (C / F["vw"][sl] - 1) * 100
    ddo = (F["lo"][sl] / o - 1) * 100
    rb = (C / F["lo"][sl] - 1) * 100
    red, green = F["red"][sl], F["green"][sl]
    macd = np.where(red >= 3, 3, np.where(red >= 1, 2, np.where(green >= 3, 0, 1)))
    kk = np.arange(F["C"].shape[1]) if k is None else k
    tb = tb_of(kk) * np.ones_like(macd)
    gap = (o / p - 1) * 100 * np.ones_like(C)
    bx = F["boxpos"][sl]
    out = {
        "lim": F["lim"][sl].astype(np.int8),
        "brd": (F["brd"] if k is not None else F["brd"][:, None] * np.ones_like(macd)).astype(np.int8),
        "dev": np.digitize(dev, [-3, -1, -0.2, 0.5, 2]).astype(np.int8),
        "macd": macd.astype(np.int8),
        "tb": tb.astype(np.int8),
        "ddo": (4 - np.digitize(ddo, [-8, -5, -3, -1], right=True)).astype(np.int8),
        "rb": np.digitize(rb, [0.5, 1.5, 3]).astype(np.int8),
        "rsi": np.digitize(F["rsi"][sl], [20, 50, 80]).astype(np.int8),
        "gap": np.digitize(gap, [-5, -2, 0, 2, 5], right=True).astype(np.int8),
        "vr": np.digitize(F["vr"][sl], [0.7, 1.5]).astype(np.int8),
        "box": np.where(np.isfinite(bx), np.digitize(np.nan_to_num(bx), [0, 1 / 3, 2 / 3, 1.0]), 2).astype(np.int8),
    }
    out["ddo"] = np.clip(out["ddo"], 0, 4)
    out["tbc"] = tbc_of(out["tb"]).astype(np.int8)
    return out


def _fwd_max(X, w):
    """out[:, k] = max(X[:, k+1 : k+1+w]); 越过收盘截断; 最后一根 = nan"""
    S, T = X.shape
    pad = np.concatenate([X[:, 1:], np.full((S, w), np.nan)], axis=1)
    win = np.lib.stride_tricks.sliding_window_view(pad, w, axis=1)[:, :T]
    with np.errstate(all="ignore"):
        return np.nanmax(win, axis=2)


def outcomes(F):
    C, H, L = F["C"], F["H"], F["L"]
    o = {}
    S, T = C.shape
    for w in HORIZ:
        mx = _fwd_max(H, w)
        mn = -_fwd_max(-L, w)
        idx = np.minimum(np.arange(T) + w, T - 1)
        cl = C[:, idx]
        o[f"mx{w}"], o[f"mn{w}"], o[f"cl{w}"] = mx / C - 1, mn / C - 1, cl / C - 1
    sufmx = np.maximum.accumulate(H[:, ::-1], axis=1)[:, ::-1]
    sufmn = np.minimum.accumulate(L[:, ::-1], axis=1)[:, ::-1]
    mxE = np.concatenate([sufmx[:, 1:], np.full((S, 1), np.nan)], axis=1)
    mnE = np.concatenate([sufmn[:, 1:], np.full((S, 1), np.nan)], axis=1)
    o["mxE"], o["mnE"], o["clE"] = mxE / C - 1, mnE / C - 1, C[:, -1:] / C - 1
    o["clE"][:, -1] = np.nan
    return o


def aux(F):
    C = F["C"]
    return {"vw_rel": F["vw"] / C - 1, "op_rel": F["open"][:, None] / C - 1, "pc_rel": F["prev"][:, None] / C - 1,
            "up_rel": F["up"][:, None] / C - 1, "dn_rel": F["dn"][:, None] / C - 1, "lo_rel": F["lo"] / C - 1}


# ---------------------------------------------------------------- 样本池 ----------------------------------------------------------------
def build_pool_day(D, rebuild=False):
    f = CACHE / f"pool_{D}.npz"
    if f.exists() and not rebuild:
        return
    day = load_day(D, rebuild=rebuild)
    ok = np.isfinite(day.C).all(axis=1) & (np.nansum(day.V, axis=1) > 0) & np.isfinite(day.prev) & (day.prev > 0)
    rows = np.where(ok)[0]
    F = features(day, rows=rows)
    B = bucket(F)
    O_ = outcomes(F)
    X = aux(F)
    ks = np.arange(0, NB - 1, STEP)
    out = {k: B[k][:, ks].ravel() for k in list(KEYS) + ["tbc"]}
    for k in OUTS:
        out[k] = O_[k][:, ks].ravel().astype(np.float32)
    for k in AUX:
        out[k] = X[k][:, ks].ravel().astype(np.float32)
    out["k"] = np.tile(ks, len(rows)).astype(np.int16)
    out["src"] = np.repeat(day.src[rows], len(ks)).astype(np.int8)
    out["row"] = np.repeat(rows, len(ks)).astype(np.int32)
    np.savez_compressed(f, **out)


class Pool:
    """按日加载样本池分块; get(days) → 拼好的列字典(缓存最近一次)"""

    def __init__(self):
        self.parts = {}
        self._key, self._cat = None, None

    def part(self, D):
        if D not in self.parts:
            f = CACHE / f"pool_{D}.npz"
            if not f.exists():
                build_pool_day(D)
            z = np.load(f)
            self.parts[D] = {k: z[k] for k in z.files}
        return self.parts[D]

    def get(self, days):
        key = tuple(days)
        if key != self._key:
            ps = [self.part(d) for d in days]
            self._cat = {k: np.concatenate([p[k] for p in ps]) for k in ps[0]} if ps else {}
            self._key = key
        return self._cat


POOL = Pool()


def _dist(x):
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return {"n": 0}
    q = np.percentile(x, [10, 25, 50, 75, 90])
    r = lambda v: round(float(v) * 100, 2)   # noqa: E731
    return {"n": int(len(x)), "P10": r(q[0]), "P25": r(q[1]), "P50": r(q[2]), "P75": r(q[3]), "P90": r(q[4]), "mean": r(x.mean()), "min": r(x.min()), "max": r(x.max())}


def state_at(code, D, hm=None, k=None):
    """D 日 k(或 HH:MM)时刻这只票的状态: 特征原值 + 分桶码(只用 ≤k 的数据: 先截断再算)"""
    day = load_day(D)
    if code not in day.idx:
        return None
    k = hm2k(hm) if k is None else k
    if k < 0:
        return None
    i = day.idx[code]
    F = features(day, upto=k, rows=[i])
    B = bucket(F, k=k)
    C = float(F["C"][0, k])
    raw = {"px": C, "vwap": round(float(F["vw"][0, k]), 4), "dev%": round((C / F["vw"][0, k] - 1) * 100, 2),
           "开盘后最大跌幅%": round((F["lo"][0, k] / F["open"][0] - 1) * 100, 2), "离日内最低%": round((C / F["lo"][0, k] - 1) * 100, 2),
           "红柱根数": int(F["red"][0, k]), "绿柱根数": int(F["green"][0, k]), "MACD柱": round(float(2 * (F["dif"][0, k] - F["dea"][0, k])), 4),
           "RSI6": round(float(F["rsi"][0, k]), 1), "量能比": round(float(F["vr"][0, k]), 2), "开盘缺口%": round((F["open"][0] / F["prev"][0] - 1) * 100, 2),
           "涨跌幅%": round((C / F["prev"][0] - 1) * 100, 2), "开板次数": int(F["n_open"][0, k]),
           "箱体位置": None if not np.isfinite(F["boxpos"][0, k]) else round(float(F["boxpos"][0, k]), 2),
           "日内最低": float(F["lo"][0, k]), "日内最高": float(F["hi"][0, k]), "开盘": float(F["open"][0]), "昨收": float(F["prev"][0]),
           "涨停价": float(F["up"][0]), "跌停价": float(F["dn"][0]), "src": int(day.src[i])}
    codes = {kk: int(np.asarray(B[kk]).ravel()[0]) for kk in list(KEYS) + ["tbc"]}
    return {"code": code, "D": D, "k": k, "t": k2hm(k), "raw": raw, "codes": codes, "F": F}


class RangeEngine:
    def __init__(self, lookback=40, min_n=40, src="all", same_day=True):
        self.lookback, self.min_n, self.src, self.same_day = lookback, min_n, src, same_day
        self._qc = {}

    def days_for(self, D):
        ds = [d for d in trade_days() if d < D]
        return ds[-self.lookback:]

    @staticmethod
    def _enc(cols, keys):
        """一组分桶码 → int64(每键 3 bit)"""
        v = None
        for kk in keys:
            c = np.asarray(cols[kk]).astype(np.int64)
            v = c if v is None else (v << 3) | c
        return v

    def _index(self, days):
        """样本池按每一级放宽的组合键排序 → 二分查找(比逐行掩码快两个数量级)"""
        key = (tuple(days), self.src)
        if getattr(self, "_ix_key", None) == key:
            return self._ix
        P = POOL.get(days)
        base = np.ones(len(P["k"]), dtype=bool) if self.src != "ohlc" else (P["src"] == 1)
        sel = np.where(base)[0]
        ix = {}
        for lvl, keys in enumerate(RELAX):
            code = self._enc({kk: P[kk][sel] for kk in keys}, keys)
            order = np.argsort(code, kind="stable")
            sc = code[order]
            u, st, cnt = np.unique(sc, return_index=True, return_counts=True)
            ix[lvl] = (u, st, cnt, sel[order])
        self._ix_key, self._ix = key, ix
        return ix

    def _lookup(self, days, codes, lvl):
        u, st, cnt, rows = self._index(days)[lvl]
        q = int(self._enc({kk: [codes[kk]] for kk in RELAX[lvl]}, RELAX[lvl])[0])
        i = np.searchsorted(u, q)
        if i < len(u) and u[i] == q:
            return rows[st[i]: st[i] + cnt[i]]
        return rows[:0]

    def _mask(self, P, codes, keys):
        m = np.ones(len(P["k"]), dtype=bool)
        for kk in keys:
            m &= P[kk] == codes[kk]
        if self.src == "ohlc":
            m &= P["src"] == 1
        return m

    def query(self, code=None, D=None, hm=None, k=None, st=None, horizons=("30", "60", "eod")):
        """st = state_at(...) 的结果(可复用); 返回分布 dict(百分比数值)"""
        st = st or state_at(code, D, hm=hm, k=k)
        if st is None:
            return {"err": "没有这只票这天的分钟数据"}
        D, k, codes = st["D"], st["k"], st["codes"]
        ck = (D, k if self.same_day else -1, tuple(sorted(codes.items())), tuple(horizons))
        if ck in self._qc:
            r = dict(self._qc[ck])
            r["state"] = st["raw"]
            return r
        days = self.days_for(D)
        P = POOL.get(days)
        Pd = POOL.part(D) if (self.same_day and D in trade_days()) else None
        res = None
        for lvl, keys in enumerate(RELAX):
            m = self._lookup(days, codes, lvl)
            n = len(m)
            if n >= self.min_n or lvl == len(RELAX) - 1:
                res = (lvl, keys, m)
                break
        lvl, keys, m = res
        out = {"code": st["code"], "D": D, "t": st["t"], "level": lvl, "keys": list(keys), "dropped": [x for x in KEYS if x not in keys and not (x == "tb" and "tbc" in keys)],
               "bucket": {kk: NAMES[kk][codes[kk]] for kk in keys}, "days": f"{days[0]}~{days[-1]} ({len(days)} 天)" if days else "",
               "n_hist": int(len(m)), "h": {}}
        sel = {kk: P[kk][m] for kk in OUTS + AUX}
        sd = None
        if Pd is not None:
            md = self._mask(Pd, codes, keys)
            sd = {kk: Pd[kk][md] for kk in OUTS + AUX}
            sd["k"] = Pd["k"][md]
        for h in horizons:
            if h == "eod":
                mx, mn, cl = sel["mxE"], sel["mnE"], sel["clE"]
                aux_ = sel
            else:
                mx, mn, cl = sel[f"mx{h}"], sel[f"mn{h}"], sel[f"cl{h}"]
                aux_ = sel
                if sd is not None:   # 当天 T 之前已经走完的窗口(窗口终点 ≤ k)
                    ok = sd["k"] + int(h) <= k
                    if ok.any():
                        mx = np.concatenate([mx, sd[f"mx{h}"][ok]])
                        mn = np.concatenate([mn, sd[f"mn{h}"][ok]])
                        cl = np.concatenate([cl, sd[f"cl{h}"][ok]])
                        aux_ = {kk: np.concatenate([sel[kk], sd[kk][ok]]) for kk in AUX}
            fin = np.isfinite(mx)
            e = 1e-6
            ev = {
                "碰到均价": float(np.mean((mx >= aux_["vw_rel"] - e)[fin])) if fin.any() else None,
                "碰到开盘价": float(np.mean((mx >= aux_["op_rel"] - e)[fin])) if fin.any() else None,
                "碰到昨收": float(np.mean((mx >= aux_["pc_rel"] - e)[fin])) if fin.any() else None,
                "碰到涨停": float(np.mean((mx >= aux_["up_rel"] - e)[fin])) if fin.any() else None,
                "碰到跌停": float(np.mean((mn <= aux_["dn_rel"] + e)[fin])) if fin.any() else None,
                "再创新低": float(np.mean((mn < aux_["lo_rel"] - e)[fin])) if fin.any() else None,
            }
            out["h"][h] = {"最高": _dist(mx), "最低": _dist(mn), "收盘": _dist(cl), "事件": {kk: (None if v is None else round(v, 3)) for kk, v in ev.items()}}
        conf = "高" if out["n_hist"] >= 300 and lvl <= 4 else ("中" if out["n_hist"] >= 80 and lvl <= 7 else "低")
        out["置信"] = conf
        self._qc[ck] = dict(out)
        out["state"] = st["raw"]
        return out

    def quantile_px(self, res, h, side_key, q):
        """res 的 h 窗口 side_key(最高 / 最低 / 收盘) 第 q 分位 → 价格(相对 res.state.px)"""
        d = res["h"][str(h)][side_key]
        if not d.get("n"):
            return None
        return res["state"]["px"] * (1 + d[f"P{q}"] / 100)


def fmt(res):
    """人看的一段话"""
    if res.get("err"):
        return res["err"]
    s = res["state"]
    lines = [f"{res['code']} {res['D']} {res['t']} 现价 {s['px']} 均价 {s['vwap']}(离均价 {s['dev%']}%) 开盘后最大跌幅 {s['开盘后最大跌幅%']}% "
             f"红柱 {s['红柱根数']} 绿柱 {s['绿柱根数']} RSI6 {s['RSI6']} 量能比 {s['量能比']}",
             f"同状态样本: {res['days']} 共 {res['n_hist']} 个(放宽到第 {res['level']} 级, 去掉 {','.join(res['dropped']) or '无'}; 置信 {res['置信']})"]
    for h, v in res["h"].items():
        mx, mn, cl = v["最高"], v["最低"], v["收盘"]
        if not mx.get("n"):
            continue
        name = "到收盘" if h == "eod" else f"之后 {h} 分钟"
        lines.append(f"  {name}: 最高 P10 {mx['P10']}% / P25 {mx['P25']}% / 中位 {mx['P50']}% / P75 {mx['P75']}% / P90 {mx['P90']}%(均值 {mx['mean']}%, 最差 {mx['min']}%)"
                     f"; 最低 中位 {mn['P50']}% P10 {mn['P10']}% 最差 {mn['min']}%; 收盘 中位 {cl['P50']}% P10 {cl['P10']}% P90 {cl['P90']}%; "
                     + " ".join(f"{k} {round(x * 100)}%" for k, x in v["事件"].items() if x is not None))
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI ----------------------------------------------------------------
def build(frm="2026-08-01", rebuild=False):
    ds = [d for d in trade_days() if d >= frm]
    t0 = time.time()
    for d in ds:
        load_day(d, rebuild=rebuild)
    for d in ds:
        build_pool_day(d, rebuild=rebuild)
        print(d, f"{time.time() - t0:.0f}s", flush=True)


def selftest():
    ok = True
    D = "2026-10-23"
    day = load_day(D)
    code = "600851"
    i = day.idx[code]
    # ① 截断计算 = 全天计算(特征因果)
    Ffull = features(day, rows=[i])
    for k in (5, 37, 130):
        Fk = features(day, upto=k, rows=[i])
        for name in ("vw", "dif", "dea", "rsi", "red", "lo", "vr", "lim"):
            a, b = Ffull[name][0, k], Fk[name][0, k]
            if not (np.isclose(a, b, equal_nan=True)):
                print("FAIL 特征不因果", name, k, a, b)
                ok = False
    # ② 样本池只含 D 之前的日子 + 当天已走完窗口
    E = RangeEngine()
    ds = E.days_for(D)
    assert all(d < D for d in ds), "样本池含 D 及以后"
    # 篡改 D 当天 T 之后的数据, 结果必须不变
    k = hm2k("09:36")
    r1 = E.query(code, D, "09:36")
    saved = day.C[i, k + 1:].copy(), day.H[i, k + 1:].copy(), day.L[i, k + 1:].copy()
    day.C[i, k + 1:] *= 1.5
    day.H[i, k + 1:] *= 1.5
    day.L[i, k + 1:] *= 0.5
    E2 = RangeEngine()
    r2 = E2.query(code, D, "09:36")
    day.C[i, k + 1:], day.H[i, k + 1:], day.L[i, k + 1:] = saved
    if json.dumps(r1["h"], sort_keys=True) != json.dumps(r2["h"], sort_keys=True) or r1["state"] != r2["state"]:
        print("FAIL 改了 T 之后的数据, 结果变了(偷看未来)")
        ok = False
    # ③ 分位单调
    for h, v in r1["h"].items():
        for kk in ("最高", "最低", "收盘"):
            d = v[kk]
            if d.get("n") and not (d["P10"] <= d["P25"] <= d["P50"] <= d["P75"] <= d["P90"]):
                print("FAIL 分位不单调", h, kk)
                ok = False
    # ④ 时间轴
    assert hm2k("09:31") == 0 and hm2k("11:30") == 119 and hm2k("13:01") == 120 and hm2k("15:00") == 239 and k2hm(120) == "13:01"
    # ⑤ 海欣 10/23 09:36: 价格 8.16 在均价 8.26 下方, MACD 绿
    s = r1["state"]
    if not (abs(s["px"] - 8.16) < 1e-6 and s["dev%"] < 0 and s["绿柱根数"] >= 1):
        print("FAIL 海欣 09:36 状态不对", s)
        ok = False
    print(fmt(r1))
    print("selftest", "OK" if ok else "FAIL")
    return ok


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--from", dest="frm", default="2026-08-01")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--min-n", type=int, default=40)
    ap.add_argument("--lookback", type=int, default=40)
    ap.add_argument("--src", default="all")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.frm, a.rebuild)
    elif a.cmd == "query":
        code, D, hm = a.args[:3]
        E = RangeEngine(lookback=a.lookback, min_n=a.min_n, src=a.src)
        r = E.query(code, D, hm)
        print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else fmt(r))
    elif a.cmd == "selftest":
        sys.exit(0 if selftest() else 1)


if __name__ == "__main__":
    main()
