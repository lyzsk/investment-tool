# -*- coding: utf-8 -*-
"""
reverse_lianghua_v2.py — 「量化短线小号实验」(lianghuaxiaohao) 选股还原第二轮: 加竞价 + 开盘头几分钟(2026-10-16 建, 零 token)

第一轮(reverse_lianghua.py)结论: 执行层可还原, 选股用日线特征还原不出来(时间外 Top2 0%, Top50 11.5%)。
本轮假设: 他 09:31~09:41 下单、回避回落 → 选股依赖竞价/开盘头几分钟信息。

  ① --fetch [--days N] [--max-stocks N]
       对他每个新开仓买入日 D 构造候选池(只用 D 前一日收盘信息, 见 build_pool), 用通达信历史逐笔取池内每只票当日最早一段逐笔
       (09:25 竞价撮合 + 09:30 起连续竞价, 截到 10:00), 缓存 scripts/tzzb/reverse_lianghua/open_ticks/<D>.jsonl(断点续跑)。
       顺序: 由近及远(先出最近 N 个买入日的初步结论)。请求间隔 0.15~0.30s 随机。他实际买的票若不在池内也取(标 in_pool=false, 只做描述, 不进排序评估)。
  ② --analyze        选股还原第二轮(池内排序, 前 70% 买入日定、后 30% 验) → docs/research/reverse_lianghua_v2_20261016.md + reverse_lianghua/v2_analysis.json
  ③ --signal --date D [--asof HH:MM]
       D 日前 30 名候选: 盘前(无竞价) = 日线排序; 09:25 后 = 加竞价; 09:3x 后 = 加开盘 N 分钟。
       历史日用通达信历史逐笔; 当日用行情库 call_auction(只读) 的竞价 + 通达信当日逐笔/分时。→ scripts/tzzb/model_out/lianghua_v2_signal_<D>.json
  ④ --validate-auction   近几日 call_auction(行情库, 只读) vs 通达信逐笔 09:25 竞价 的价/量对照
  ⑤ --selftest

数据: 只读行情库(kline_day/security_master/lhb_stock/call_auction), 通达信行情(pytdx); 不访问东财/腾讯/新浪/同花顺接口, 不调 LLM, 不写库, 不起子进程。
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/reverse_lianghua_v2.py [--fetch|--analyze|--signal --date D|--validate-auction|--selftest]
"""
import argparse
import datetime as dtm
import json
import math
import random
import socket
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/tzzb"))
sys.path.insert(0, str(ROOT / "scripts/market"))
sys.path.insert(0, str(ROOT / "scripts/quotes"))
import reverse_lianghua as rl  # noqa: E402  (只 import 函数/类, 不跑其 main)
import mentor_fingerprint as mf  # noqa: E402

LEDGER = rl.LEDGER
OUT_DIR = rl.OUT_DIR
TICK_DIR = OUT_DIR / "open_ticks"
SIG_DIR = rl.SIG_DIR
REPORT = ROOT / "docs/research/reverse_lianghua_v2_20261016.md"
FEATS = rl.FEATS
POOL_LR_N, POOL_AMT_N = 300, 150        # 候选池 = 板块内 v1 日线模型前 300 ∪ 昨成交额前 150 (主板/创业板/科创板, 非 ST)
POOL_ASSETS = ("MAIN", "GEM", "STAR")
TICK_WANT = 1000                         # 每票取当日最早 ~1000 笔(活跃票 3 秒一笔 ≈ 50 分钟)
TICK_CUT = "10:00"                       # 只存 10:00 之前
CHECKPOINTS = ["09:25", "09:31", "09:33", "09:35", "09:40", "09:45", "09:50", "09:55"]   # 决策时点: 只用时刻 < 该点的逐笔(09:25=只有竞价)
SEED = 20261016
log = mf.log
socket.setdefaulttimeout(20)


# ====================================================================================
# 0. 面板 / 候选池(只用 D 前一日收盘信息)
# ====================================================================================
_CTX = {}


def ctx():
    """行情面板 + 真人事件 + v1 冻结模型(参数训练截至 2026-07-21, 见 reverse_lianghua/model_params.json)"""
    if not _CTX:
        M = rl.FixedMarket()
        mt = mf.Mentor(LEDGER, M)
        SH = rl.SelfHist(M, mt)
        pos = rl.positives_by_row(M, mt)
        P = json.loads((OUT_DIR / "model_params.json").read_text(encoding="utf-8"))
        _CTX.update(M=M, mt=mt, SH=SH, pos=pos, v1=rl.LRModel.from_json(P["model"]), v1_until=P["trained_until"])
    return _CTX


def build_pool(M, SH, v1, i):
    """面板行 i(D 日) 的候选池: 只用 i-1 行(D 前一日收盘)的日线特征 + v1 冻结模型。
    返回 js(列号, 已按 v1 分降序), Xd(日线特征), src(入池原因)
    注: v1 模型用 2026-07-21 前的真人买入训练 → 07-21 前的买入日池子构成是样本内(只影响训练集负样本), 07-21 起完全事前。"""
    js, X = rl.day_features(M, SH, i - 1)
    base = np.isin(M.asset[js], POOL_ASSETS) & (X[:, FEATS.index("st")] == 0)
    if i < len(M.dates):
        base &= M.has[i, js] if M.has.shape[0] > i else True
    sc = np.where(base, v1.score(X), -np.inf)
    am = np.where(base, X[:, FEATS.index("lamt")], -np.inf)
    a = set(np.argsort(-sc)[:POOL_LR_N][np.isfinite(np.sort(-sc)[:POOL_LR_N])].tolist())
    b = set(np.argsort(-am)[:POOL_AMT_N].tolist())
    ks = sorted(a | b, key=lambda k: -sc[k])
    src = {int(js[k]): ("lr" if k in a else "") + ("+amt" if k in b else "") for k in ks}
    ks = np.array(ks, int)
    return js[ks], X[ks], src, sc[ks]


def buy_days(C):
    """他的新开仓买入日(面板行) 升序"""
    return sorted(i for i in C["pos"] if C["pos"][i])


# ====================================================================================
# 1. 通达信: 当日最早一段逐笔
# ====================================================================================
def _get(api, sym, start, count, ymd):
    r = api.get_history_transaction_data(rl_cm().tdx_market(sym), sym[2:], start, count, ymd)
    time.sleep(random.uniform(0.15, 0.30))
    return list(r) if r else []


_CM = []


def rl_cm():
    if not _CM:
        import collect_minute as cm  # noqa: E402  (pytdx 封装: connect/all_ticks/tdx_market)
        _CM.append(cm)
    return _CM[0]


def connect(ymd, offset=0):
    """同 collect_minute.connect(要求两市都有 ymd 逐笔), 但从第 offset 台服务器开始找 —— 多 worker 时各用一台, 单台请求间隔仍 ≥0.15s"""
    from pytdx.config.hosts import hq_hosts
    from pytdx.hq import TdxHq_API
    hosts = hq_hosts[offset:] + hq_hosts[:offset]
    for name, ip, port in hosts:
        api = TdxHq_API(raise_exception=False)
        try:
            if api.connect(ip, port, time_out=3) and api.get_security_count(1):
                if ymd and not (api.get_history_transaction_data(0, "002714", 0, 5, ymd) and api.get_history_transaction_data(1, "600000", 0, 5, ymd)):
                    api.disconnect()
                    continue
                log(f"通达信 {ip}:{port}")
                return api
        except Exception:   # noqa: BLE001
            continue
    raise RuntimeError(f"通达信服务器全部不可用(或都没有 {ymd} 逐笔)")


def earliest_ticks(api, sym, ymd, want=TICK_WANT):
    """取当日最早 want 笔逐笔(pytdx start=距末尾偏移). 活跃票全天 ≈4800 笔(3 秒快照), 先探 start=3800 → 多数 1 次请求拿到开盘段。
    返回 (ticks 升序, 全天笔数估计 or None, 请求次数)"""
    nreq = 0
    s, c = 3500, 1300                        # 覆盖全天 3500~4800 笔(活跃票主体), 拿到的开盘段 = total-3500 笔
    for _ in range(6):                       # 全天 > 4800 笔: 往前翻
        r = _get(api, sym, s, c, ymd); nreq += 1
        if r and len(r) == c and r[0]["time"] > "09:25":
            s += c
            continue
        break
    if r:
        total = s + len(r) if len(r) < c else None
        if total and len(r) < 600:           # 开盘段太短(<~30 分钟): 已知全天笔数, 精确取最早 want 笔
            r2 = _get(api, sym, max(0, total - want), want, ymd); nreq += 1
            if r2:
                r = r2
        return r, total, nreq
    # 空 → 全天 ≤ s 笔
    r = _get(api, sym, 1800, 2000, ymd); nreq += 1
    if r:
        total = 1800 + len(r)
        if len(r) >= 600:
            return r, total, nreq
        r = _get(api, sym, max(0, total - want), want, ymd); nreq += 1
        return r, total, nreq
    r = _get(api, sym, 0, 2000, ymd); nreq += 1
    return r, len(r), nreq


def ticks_valid(ticks, o, h, l):
    """防通达信流错位(10/14 实录串票): 价格全部落在当日日线 [低, 高]±1%; 首笔是 09:25 时 ≈ 开盘价 ±0.3%"""
    ps = [x["price"] for x in ticks if x["vol"] > 0]
    if not ps:
        return False
    if h and l and (max(ps) > h * 1.01 or min(ps) < l * 0.99):
        return False
    if ticks[0]["time"] == "09:25" and o and abs(ticks[0]["price"] / o - 1) > 0.003:
        return False
    return True


def tick_file(day):
    return TICK_DIR / f"{day}.jsonl"


def load_ticks(day):
    """open_ticks/<D>.jsonl → {symbol: rec}; rec = {sym, in_pool, src, ticks:[[hhmm, price, vol手, bs]], total, miss?}"""
    f = tick_file(day)
    out = {}
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            out[r["sym"]] = r
    return out


def cmd_fetch(n_days=None, max_stocks=None, since=None, worker=0, nworkers=1):
    C = ctx()
    M, SH, v1, pos = C["M"], C["SH"], C["v1"], C["pos"]
    cm = rl_cm()
    days = buy_days(C)[::-1]                 # 由近及远
    if since:
        days = [i for i in days if M.dates[i] >= since]
    if n_days:
        days = days[:n_days]
    days = days[worker::nworkers]
    host_off = [0, 5, 8, 11][worker % 4]
    TICK_DIR.mkdir(parents=True, exist_ok=True)
    api, t0, n_req, n_ok, n_miss, n_stock = None, time.time(), 0, 0, 0, 0
    try:
        for di, i in enumerate(days):
            day = M.dates[i]
            ymd = int(day.replace("-", ""))
            js, _X, src, _sc = build_pool(M, SH, v1, i)
            want = [(int(j), True, src[int(j)]) for j in js]
            inpool = set(int(j) for j in js)
            want += [(int(j), False, "real_only") for j in pos[i] if int(j) not in inpool and M.asset[j] in POOL_ASSETS]
            have = load_ticks(day)
            todo = [w for w in want if M.syms[w[0]] not in have]
            if not todo:
                continue
            if api is None:
                api = connect(ymd, host_off)
            day_miss = 0
            with tick_file(day).open("a", encoding="utf-8") as fh:
                for j, inp, s in todo:
                    if max_stocks is not None and n_stock >= max_stocks:
                        raise StopIteration
                    sym = M.syms[j]
                    o, h, l = (float(M.O[i, j]) if np.isfinite(M.O[i, j]) else None, float(M.H[i, j]) if np.isfinite(M.H[i, j]) else None,
                               float(M.L[i, j]) if np.isfinite(M.L[i, j]) else None)
                    rec = {"sym": sym, "in_pool": inp, "src": s}
                    for attempt in range(2):
                        try:
                            ticks, total, nr = earliest_ticks(api, sym, ymd)
                            n_req += nr
                        except Exception as e:   # noqa: BLE001  连接断: 重连重取
                            ticks, total = [], None
                            log(f"  失败 {day} {sym}: {e}")
                            try:
                                api.disconnect()
                            except Exception:   # noqa: BLE001
                                pass
                            api = connect(ymd, host_off)
                            continue
                        if ticks and ticks_valid(ticks, o, h, l):
                            break
                        if ticks and attempt == 0:
                            log(f"  校验不过 {day} {sym}(疑流错位), 重连重取")
                            try:
                                api.disconnect()
                            except Exception:   # noqa: BLE001
                                pass
                            api = connect(ymd, host_off)
                        ticks = []
                    n_stock += 1
                    if ticks:
                        rec["ticks"] = [[x["time"], x["price"], x["vol"], x["buyorsell"]] for x in ticks if x["time"] < TICK_CUT]
                        rec["total"] = total
                        rec["t_last"] = ticks[-1]["time"]
                        n_ok += 1
                    else:
                        rec["miss"] = True
                        n_miss += 1; day_miss += 1
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fh.flush()
            el = time.time() - t0
            log(f"[{time.strftime('%H:%M:%S')}] {day} 池 {len(js)} + 真人池外 {len(want) - len(js)} | 本日新取 {len(todo)} 缺 {day_miss} | "
                f"累计 {di + 1}/{len(days)} 日 {n_stock} 只 {n_req} 请求 {el:.0f}s ({el / max(n_stock, 1):.2f}s/只)")
            if day_miss > 0.3 * len(todo):        # 本服务器该日缺得多(如只有一市逐笔): 换服务器
                try:
                    api.disconnect()
                except Exception:   # noqa: BLE001
                    pass
                api = None
    except StopIteration:
        pass
    finally:
        if api is not None:
            try:
                api.disconnect()
            except Exception:   # noqa: BLE001
                pass
    log(f"[fetch 完成] {n_stock} 只, 成功 {n_ok}, 缺 {n_miss}, 请求 {n_req}, 用时 {time.time() - t0:.0f}s")


# ====================================================================================
# 2. 竞价/开盘特征(只用决策时点之前的逐笔)
# ====================================================================================
OPEN_FEATS = ["auc_gap", "auc_lamt", "auc_vr", "auc_amt_rk",          # 竞价: 涨幅 / log 额 / 竞价量÷昨日量 / 池内竞价额排名(log)
              "ret", "ret_o", "hi", "dd", "lo_o", "vwap_r", "lvr", "amt_rk", "buy_frac", "mom3", "ntk", "to_lu",
              "peer_auc", "peer_ret", "rel_peer"]      # 板块强度代理: 池内近 60 日日收益相关最高的 10 只"同伴"的竞价涨幅/当前涨幅; 自身-同伴
OPEN_CN = {"auc_gap": "竞价涨幅", "auc_lamt": "竞价额(log)", "auc_vr": "竞价量÷昨日量", "auc_amt_rk": "池内竞价额排名(小=大)",
           "ret": "当前涨幅(相对昨收)", "ret_o": "相对开盘涨幅", "hi": "开盘以来最高涨幅", "dd": "距开盘以来最高回撤", "lo_o": "开盘以来最低(相对开盘)",
           "vwap_r": "相对分时均价", "lvr": "开盘以来量÷昨日量(log)", "amt_rk": "池内开盘成交额排名(小=大)", "buy_frac": "主动买占比",
           "mom3": "近3分钟涨速", "ntk": "逐笔笔数(log)", "to_lu": "距涨停空间",
           "peer_auc": "同伴(相关板块)竞价涨幅", "peer_ret": "同伴(相关板块)当前涨幅", "rel_peer": "自身-同伴涨幅(领涨度)"}
PEER_N, PEER_LOOK = 10, 60


def open_feats_one(rec, pc, prev_vol, cp, lu=None):
    """单票: 决策时点 cp(HH:MM, 只用 time < cp 的逐笔; cp='09:25' 时只有竞价) → dict
    pc=昨收, prev_vol=昨日成交量(股), lu=涨停价(昨收算出, 盘前已知)"""
    if rec.get("rt"):
        return open_feats_rt(rec, pc, prev_vol, cp, lu)
    t = rec.get("ticks") or []
    if not t or not pc or not np.isfinite(pc):
        return None
    if cp > "09:25" and (rec.get("t_last") or "15:00") < cp:       # 取到的逐笔没覆盖到决策点(约 1%): 记缺, 不拿半截数据算
        return None
    auc = [x for x in t if x[0] == "09:25"]
    a_px = auc[0][1] if auc else None
    a_vol = sum(x[2] for x in auc) * 100.0
    f = {"auc_gap": (a_px / pc - 1) if a_px else np.nan, "auc_lamt": math.log10(a_vol * (a_px or pc) + 1),
         "auc_vr": (a_vol / prev_vol) if prev_vol and np.isfinite(prev_vol) and prev_vol > 0 else np.nan}
    cont = [x for x in t if "09:30" <= x[0] < cp] if cp > "09:25" else []
    o = a_px or (cont[0][1] if cont else None)
    if cont and o:
        ps = np.array([x[1] for x in cont]); vs = np.array([x[2] for x in cont], float) * 100
        last, hi, lo = ps[-1], max(ps.max(), o), min(ps.min(), o)
        amt = float((ps * vs).sum()); vol = float(vs.sum())
        f.update({"ret": last / pc - 1, "ret_o": last / o - 1, "hi": hi / pc - 1, "dd": last / hi - 1, "lo_o": lo / o - 1,
                  "vwap_r": (last / (amt / vol) - 1) if vol else 0.0,
                  "lvr": math.log1p(min(vol / prev_vol, 5) * 100) if prev_vol and np.isfinite(prev_vol) and prev_vol > 0 else np.nan,
                  "_amt": amt, "buy_frac": float(vs[np.array([x[3] == 0 for x in cont])].sum() / vol) if vol else 0.5,
                  "ntk": math.log1p(len(cont))})
        # 最近 3 分钟涨速: 决策点前 3 个"分钟"
        h, m = map(int, cp.split(":")); m3 = f"{h:02d}:{max(m - 3, 0):02d}" if m >= 3 else f"{h - 1:02d}:{m + 57:02d}"
        prev = [x for x in cont if x[0] < m3]
        f["mom3"] = last / (prev[-1][1] if prev else o) - 1
    else:
        f.update({k: np.nan for k in ("ret", "ret_o", "hi", "dd", "lo_o", "vwap_r", "lvr", "buy_frac", "mom3", "ntk")})
        f["_amt"] = 0.0
        last = a_px
    f["to_lu"] = (lu / last - 1) if (lu and last and np.isfinite(lu)) else np.nan
    return f


def day_open_matrix(M, i, js, recs, cp):
    """池 js 在 D(行 i) 决策时点 cp 的开盘特征矩阵 [len(js), len(OPEN_FEATS)] + 有数据掩码"""
    F = np.full((len(js), len(OPEN_FEATS)), np.nan)
    ok = np.zeros(len(js), bool)
    amts, aamts = np.full(len(js), np.nan), np.full(len(js), np.nan)
    for k, j in enumerate(js):
        rec = recs.get(M.syms[j])
        if not rec or rec.get("miss"):
            continue
        pc = float(M.PC[i, j]) if i < len(M.dates) and np.isfinite(M.PC[i, j]) else float(M.C[i - 1, j])
        # TODO(10/16 主会话): 涨跌停口径以后统一走 scripts/lib/a_rules.py(尚未生成), 现沿用 mentor_fingerprint 的 M.lu / LIMIT_R
        lu = float(M.lu[i, j]) if i < len(M.dates) and np.isfinite(M.lu[i, j]) else round(pc * (1 + mf.LIMIT_R.get(M.asset[j], 0.1)) + 1e-9, 2)
        f = open_feats_one(rec, pc, float(M.V[i - 1, j]), cp, lu)
        if not f:
            continue
        ok[k] = True
        for q, nm in enumerate(OPEN_FEATS):
            if nm in f:
                F[k, q] = f[nm]
        amts[k] = f["_amt"]; aamts[k] = f["auc_lamt"]
    # 池内排名(0=最大), log
    for nm, v in (("amt_rk", amts), ("auc_amt_rk", aamts)):
        if cp == "09:25" and nm == "amt_rk":
            continue
        vv = np.where(ok & np.isfinite(v), v, -np.inf)
        rk = np.empty(len(js)); rk[np.argsort(-vv)] = np.arange(len(js))
        F[:, OPEN_FEATS.index(nm)] = np.where(ok, np.log10(rk + 1), np.nan)
    # 同伴(板块强度代理, 无行业库): D 前 60 日日收益相关最高的 10 只池内票
    P = peers(M, i, js)
    a, r = F[:, OPEN_FEATS.index("auc_gap")], F[:, OPEN_FEATS.index("ret")]
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pa = np.nanmean(a[P], axis=1); pr = np.nanmean(r[P], axis=1)
    F[:, OPEN_FEATS.index("peer_auc")] = pa
    F[:, OPEN_FEATS.index("peer_ret")] = pr if cp > "09:25" else np.nan
    own = r if cp > "09:25" else a
    F[:, OPEN_FEATS.index("rel_peer")] = own - (pr if cp > "09:25" else pa)
    return F, ok


_PEERS = {}


def peers(M, i, js):
    """池内每只票的 PEER_N 个同伴(列下标): D 前 PEER_LOOK 个交易日日收益相关系数最高(不含自己); 只用 D 前数据"""
    key = (i, len(js), int(js[0]) if len(js) else -1)
    if key not in _PEERS:
        R = np.nan_to_num(M.pct[max(0, i - PEER_LOOK):i, js], nan=0.0)
        R = (R - R.mean(0)) / (R.std(0) + 1e-9)
        Cm = (R.T @ R) / max(len(R), 1)
        np.fill_diagonal(Cm, -9)
        _PEERS.clear()
        _PEERS[key] = np.argsort(-Cm, axis=1)[:, :PEER_N]
    return _PEERS[key]


# ====================================================================================
# 3. 池内排序模型: 条件 logit(每日从池中"选"票, 日内 softmax; 市场整体涨跌这类日级因素自动抵消)
# ====================================================================================
DAILY_CONT = rl.CONT                      # 11 个连续日线特征(昨收盘状态)
DAILY_BIN = rl.BINF                       # 14 个 0/1(或小整数)日线特征


def pct_rank(v):
    """日内百分位(0~1), NaN → 0.5(中性)"""
    out = np.full(len(v), 0.5)
    m = np.isfinite(v)
    if m.sum() > 1:
        r = np.argsort(np.argsort(v[m]))
        out[m] = r / (m.sum() - 1)
    return out


def design(Xd, F, use_open, open_names=None, v1s=None):
    """日线部分: v1s 给了 → 只用第一轮日线模型分(池内百分位+平方偏离, 低自由度"先验"); 否则 25 个日线特征(连续→百分位+平方偏离; 0/1 原样)
    [+ 开盘特征(池内百分位+平方偏离)] → Z, 列名"""
    cols, names = [], []
    if v1s is not None:
        r = pct_rank(np.asarray(v1s, float)); cols += [r, (r - 0.5) ** 2]; names += ["v1", "v1^2"]
    else:
        for nm in DAILY_CONT:
            r = pct_rank(Xd[:, FEATS.index(nm)]); cols += [r, (r - 0.5) ** 2]; names += [nm, nm + "^2"]
        for nm in DAILY_BIN:
            v = np.nan_to_num(Xd[:, FEATS.index(nm)].astype(float)); cols.append(v); names.append(nm)
    if use_open:
        for nm in (open_names or OPEN_FEATS):
            v = F[:, OPEN_FEATS.index(nm)]
            r = pct_rank(v); cols += [r, (r - 0.5) ** 2]; names += ["o:" + nm, "o:" + nm + "^2"]
    return np.column_stack(cols), names


def design_d(d, cp, use_open, open_names=None, mode="v1"):
    return design(d["Xd"], d["F"][cp], use_open, open_names, d["v1s"] if mode == "v1" else None)


class CLogit:
    """条件 logit: P(选 k | 当日池) = softmax(Z w); 多只正样本按独立选择近似; L2 + Adam; numpy 实现"""
    def __init__(self, l2=0.02, iters=400, lr=0.05):
        self.l2, self.iters, self.lr = l2, iters, lr

    def fit(self, groups):
        """groups: [(Z_d, y_d)] → self"""
        Zs = [g[0] for g in groups if g[1].sum() > 0]
        ys = [g[1] for g in groups if g[1].sum() > 0]
        Z = np.vstack(Zs); y = np.concatenate(ys)
        self.mu, self.sd = Z.mean(0), Z.std(0) + 1e-9
        Z = (Z - self.mu) / self.sd
        seg = np.cumsum([0] + [len(x) for x in Zs])
        npos = np.array([x.sum() for x in ys])
        gid = np.repeat(np.arange(len(Zs)), [len(x) for x in Zs])
        k = Z.shape[1]
        w = np.zeros(k); m1 = np.zeros(k); v1 = np.zeros(k)
        N = npos.sum()
        for it in range(1, self.iters + 1):
            s = Z @ w
            mx = np.maximum.reduceat(s, seg[:-1])
            e = np.exp(s - mx[gid])
            den = np.add.reduceat(e, seg[:-1])
            p = e / den[gid]
            g = -(Z.T @ (y - p * npos[gid])) / N + self.l2 * w
            m1 = 0.9 * m1 + 0.1 * g; v1 = 0.999 * v1 + 0.001 * g * g
            w -= self.lr * (m1 / (1 - 0.9 ** it)) / (np.sqrt(v1 / (1 - 0.999 ** it)) + 1e-8)
        self.w = w
        return self

    def score(self, Z):
        return ((Z - self.mu) / self.sd) @ self.w

    def to_json(self, names):
        return {"names": names, "w": self.w.tolist(), "mu": self.mu.tolist(), "sd": self.sd.tolist(), "l2": self.l2}

    @classmethod
    def from_json(cls, d):
        m = cls(); m.w, m.mu, m.sd = np.array(d["w"]), np.array(d["mu"]), np.array(d["sd"])
        return m


def first_new_buy(C):
    """(行 i) → 当日新开仓最早买入时刻 HH:MM:SS; (行 i, 列 j) → 该票首腿时刻"""
    M = C["M"]
    day_t, pair_t = {}, {}
    for e in C["mt"].buys:
        if not e["new_open"] or e["row"] is None:
            continue
        s = mf.symbol_of(e["code"]); j = M.sidx.get(s) if s else None
        if j is None or M.asset[j] not in POOL_ASSETS:
            continue
        i = e["row"]
        pair_t[(i, j)] = e["t_first"]
        day_t[i] = min(day_t.get(i, "99"), e["t_first"])
    return day_t, pair_t


def cp_ok(cp, t_first):
    """决策时点 cp 的信息是否都在买入之前: cp=09:25(竞价结果) 要求 09:30 后买; 其余要求买入时刻 ≥ cp"""
    return t_first >= ("09:30:00" if cp == "09:25" else cp + ":00")


def load_days(C, rows):
    """逐日: 池 + 日线特征 + 各决策时点的开盘特征(全部内存缓存)"""
    M, SH, v1, pos = C["M"], C["SH"], C["v1"], C["pos"]
    D = {}
    for i in rows:
        day = M.dates[i]
        recs = load_ticks(day)
        if not recs:
            continue
        js, Xd, src, v1s = build_pool(M, SH, v1, i)
        pool_set = set(int(j) for j in js)
        allpos = {int(j) for j in pos[i] if M.asset[j] in POOL_ASSETS}
        done = sum(1 for j in js if M.syms[j] in recs)
        if done < 0.97 * len(js):                # 当日还没取完 → 不用
            continue
        Fs, oks = {}, {}
        for cp in CHECKPOINTS:
            Fs[cp], oks[cp] = day_open_matrix(M, i, js, recs, cp)
        y = np.isin(js, list(allpos)).astype(float)
        D[i] = {"day": day, "js": js, "Xd": Xd, "v1s": v1s, "F": Fs, "ok": oks, "y": y, "allpos": allpos, "inpool": allpos & pool_set,
                "recs": recs}
    return D


_TIE = np.random.default_rng(SEED + 7)


def topn_cover(D, rows, scorer, Ns=(2, 5, 10, 30, 50)):
    """rows 上逐日池内排序 → 他当日新开仓(主板/创业/科创)落在 TopN 的比例(分母含池外/缺数据的票 = 记为未命中)"""
    hit = Counter(); npos = 0; nd = 0; prs = []
    for i in rows:
        d = D[i]
        sc = scorer(i, d)
        if sc is None:
            continue
        nd += 1
        order = np.lexsort((_TIE.random(len(sc)), -np.asarray(sc, float)))     # 并列随机打散
        rank = np.empty(len(sc), int); rank[order] = np.arange(len(sc))
        npos += len(d["allpos"])
        for k in np.where(d["y"] == 1)[0]:
            prs.append(rank[k] / len(sc))
            for N in Ns:
                hit[N] += rank[k] < N
    return {"days": nd, "pos": npos, "cover": {N: round(hit[N] / npos, 4) if npos else None for N in Ns},
            "inpool_pct_rank_med": round(float(np.median(prs)), 3) if prs else None, "n_inpool": len(prs)}


L2_GRID = (0.01, 0.05, 0.2, 1.0, 5.0)


class Naive:
    """对角近似(朴素贝叶斯式)打分: 权重 = (正样本均值 - 池均值)/池标准差, 只有"方向+强度", 自由度低 → 小样本下抗过拟合"""
    def fit(self, groups):
        Z = np.vstack([g[0] for g in groups]); y = np.concatenate([g[1] for g in groups])
        self.mu, self.sd = Z.mean(0), Z.std(0) + 1e-9
        Zs = (Z - self.mu) / self.sd
        self.w = Zs[y == 1].mean(0) if (y == 1).any() else np.zeros(Z.shape[1])
        return self

    def score(self, Z):
        return ((Z - self.mu) / self.sd) @ self.w

    def to_json(self, names):
        return {"kind": "naive", "names": names, "w": self.w.tolist(), "mu": self.mu.tolist(), "sd": self.sd.tolist()}


def groups_of(D, rows, cp, use_open, open_names=None, mode="v1"):
    groups, names = [], None
    for i in rows:
        d = D[i]
        Z, names = design_d(d, cp, use_open, open_names, mode)
        groups.append((Z, d["y"]))
    return groups, names


def mean_rank(model, groups):
    """正样本在池内的平均百分位(0=第一, 越小越好)"""
    rs = []
    for Z, y in groups:
        if y.sum() == 0:
            continue
        sc = model.score(Z); r = np.empty(len(sc)); r[np.argsort(-sc)] = np.arange(len(sc))
        rs += list(r[y == 1] / len(sc))
    return float(np.mean(rs)) if rs else 1.0


def per_day_hits(D, rows, scorer, Ns=(10, 30)):
    """逐日 (命中数@N..., 当日他的票数) → 供 bootstrap"""
    out = []
    for i in rows:
        d = D[i]
        sc = scorer(i, d)
        r = np.empty(len(sc), int); r[np.lexsort((_TIE.random(len(sc)), -np.asarray(sc, float)))] = np.arange(len(sc))
        ks = np.where(d["y"] == 1)[0]
        out.append([sum(int(r[k] < N) for k in ks) for N in Ns] + [len(d["allpos"])])
    return np.array(out, float)


def boot_diff(H1, H0, n=2000, seed=SEED):
    """按日重抽样: 覆盖率(模型) - 覆盖率(基线) 的 90% 区间; H=[日, (hit@N..., npos)]"""
    rng = np.random.default_rng(seed)
    k = H1.shape[1] - 1
    res = []
    for q in range(k):
        ds = []
        for _ in range(n):
            ix = rng.integers(0, len(H1), len(H1))
            den = H1[ix, -1].sum()
            if den:
                ds.append((H1[ix, q].sum() - H0[ix, q].sum()) / den)
        res.append([round(float(np.percentile(ds, 5)), 3), round(float(np.percentile(ds, 95)), 3)] if ds else None)
    return res


def fit_cl(D, rows, cp, use_open, open_names=None, l2=None, kind="clogit", mode="v1"):
    """kind=clogit: L2 由训练窗内前向两折按正样本平均百分位选; kind=naive: 对角打分. mode=v1: 日线部分=第一轮模型分; full: 25 个日线特征池内重训"""
    groups, names = groups_of(D, rows, cp, use_open, open_names, mode)
    if not groups or sum(g[1].sum() for g in groups) == 0:
        return None, None
    if kind == "naive":
        return Naive().fit(groups), names
    if l2 is None:                       # 前向两折: [0,50%)→[50%,75%), [0,75%)→[75%,100%), 平均正样本百分位最小者
        n = len(groups)
        folds = [(groups[:n // 2], groups[n // 2:3 * n // 4]), (groups[:3 * n // 4], groups[3 * n // 4:])]
        folds = [(a, b) for a, b in folds if sum(g[1].sum() for g in a) and sum(g[1].sum() for g in b)]
        best = None
        for c in L2_GRID:
            if not folds:
                break
            sc = float(np.mean([mean_rank(CLogit(l2=c).fit(a), b) for a, b in folds]))
            if best is None or sc < best[0]:
                best = (sc, c)
        l2 = best[1] if best else 1.0
    m = CLogit(l2=l2).fit(groups)
    m.l2_chosen = l2
    return m, names


def cl_scorer(model, cp, use_open, open_names=None, mode="v1"):
    def f(i, d):
        Z, _ = design_d(d, cp, use_open, open_names, mode)
        return model.score(Z)
    return f


SPECS = [("clogit", "v1"), ("naive", "v1"), ("clogit", "full"), ("naive", "full")]
PRIMARY = ("clogit", "v1")      # 事先指定的主模型(低自由度: 第一轮日线分 + 开盘特征), 不按验证窗结果挑


def sec_v2(C, D):
    M = C["M"]
    day_t, pair_t = first_new_buy(C)
    rows = sorted(D)
    cut = int(len(rows) * rl.TRAIN_FRAC)
    tr, te = rows[:cut], rows[cut:]
    A = {"rows": len(rows), "window": [M.dates[rows[0]], M.dates[rows[-1]]], "train": [M.dates[tr[0]], M.dates[tr[-1]]],
         "test": [M.dates[te[0]], M.dates[te[-1]]], "n_train": len(tr), "n_test": len(te)}
    for nm, rr in (("train", tr), ("test", te), ("all", rows)):
        a = sum(len(D[i]["allpos"]) for i in rr); b = sum(len(D[i]["inpool"]) for i in rr)
        A[f"pool_cover_{nm}"] = round(b / a, 3) if a else None
    A["pool_size_med"] = int(np.median([len(D[i]["js"]) for i in rows]))
    A["tick_ok_rate"] = round(float(np.mean([D[i]["ok"]["09:25"].mean() for i in rows])), 3)
    A["first_buy_dist"] = {cp: round(float(np.mean([cp_ok(cp, day_t.get(i, "99")) for i in rows])), 3) for cp in CHECKPOINTS}
    # 基线: v1 全市场模型(第一轮)在同一批测试日(分母同口径: 主板/创业/科创新开仓)
    SH, v1 = C["SH"], C["v1"]
    Ns = (2, 5, 10, 30, 50)
    hit = Counter(); npos = 0
    for i in te:
        js, X = rl.day_features(M, SH, i - 1)
        live = M.has[i, js]; js, X = js[live], X[live]
        sc = v1.score(X); order = np.argsort(-sc); rk = {int(j): r for r, j in enumerate(js[order])}
        for j in D[i]["allpos"]:
            npos += 1
            for N in Ns:
                hit[N] += rk.get(j, 10 ** 9) < N
    A["v1_fullmarket_test"] = {"cover": {N: round(hit[N] / npos, 4) for N in Ns}, "pos": npos}
    A["v1_in_pool_test"] = topn_cover(D, te, lambda i, d: d["v1s"])
    rng = np.random.default_rng(SEED)
    A["random_in_pool_test"] = topn_cover(D, te, lambda i, d: rng.random(len(d["js"])))
    A["rule_auc_amt_test"] = topn_cover(D, te, lambda i, d: -np.nan_to_num(d["F"]["09:25"][:, OPEN_FEATS.index("auc_amt_rk")], nan=9))
    # 模型: 日线 / +竞价 / +开盘 N 分钟; 每个决策点只用"他在该点之后才买"的日子训练与验证(防后见)
    A["models"] = {}
    models = {}                     # (kind, mode, cp) → (model, names)
    for kind, mode in SPECS:
        for cp in ["pre"] + CHECKPOINTS:
            cpk = "09:25" if cp == "pre" else cp
            trc = [i for i in tr if cp == "pre" or cp_ok(cp, day_t.get(i, "99"))]
            tec = [i for i in te if cp == "pre" or cp_ok(cp, day_t.get(i, "99"))]
            m, names = fit_cl(D, trc, cpk, cp != "pre", kind=kind, mode=mode)
            if m is None or not tec:
                continue
            models[(kind, mode, cp)] = (m, names)
            r_te = topn_cover(D, tec, cl_scorer(m, cpk, cp != "pre", mode=mode))
            r_tr = topn_cover(D, trc, cl_scorer(m, cpk, cp != "pre", mode=mode))
            if cp != "pre":
                m0, _ = fit_cl(D, trc, cpk, False, kind=kind, mode=mode)
                r0 = topn_cover(D, tec, cl_scorer(m0, cpk, False, mode=mode))
            else:
                r0 = r_te
            top = sorted(zip(names, m.w.round(3).tolist()), key=lambda z: -abs(z[1]))[:12]
            A["models"][f"{kind}/{mode}@{cp}"] = {"kind": kind, "mode": mode, "cp": cp, "train_days": len(trc), "test_days": len(tec), "test": r_te,
                                                  "train": r_tr, "test_daily_only_same_days": r0, "top_w": top, "l2": getattr(m, "l2_chosen", None)}
            log(f"  [{kind}/{mode}@{cp}] 训练 {len(trc)} / 验证 {len(tec)} 日: 验证 {r_te['cover']} (同日日线-only {r0['cover']}) l2={getattr(m, 'l2_chosen', None)}")

    def dyn_cp(i, spec):
        t = day_t.get(i, "99")
        ok = [cp for cp in CHECKPOINTS if cp_ok(cp, t) and (spec + (cp,)) in models]
        return ok[-1] if ok else "pre"

    def dyn_scorer(spec):
        def f(i, d):
            cp = dyn_cp(i, spec)
            return models[spec + (cp,)][0].score(design_d(d, "09:25" if cp == "pre" else cp, cp != "pre", mode=spec[1])[0])
        return f

    def pre_scorer(spec):
        return lambda i, d: models[spec + ("pre",)][0].score(design_d(d, "09:25", False, mode=spec[1])[0])
    A["dynamic_cp_dist_test"] = dict(Counter(dyn_cp(i, PRIMARY) for i in te))
    A["dynamic_specs"] = {}
    for spec in SPECS:
        A["dynamic_specs"]["/".join(spec)] = {"test": topn_cover(D, te, dyn_scorer(spec)), "train": topn_cover(D, tr, dyn_scorer(spec)),
                                              "test_pre": topn_cover(D, te, pre_scorer(spec))}
    A["dynamic_kind"] = "/".join(PRIMARY)
    A["dynamic_test"] = A["dynamic_specs"]["/".join(PRIMARY)]["test"]
    A["dynamic_train"] = A["dynamic_specs"]["/".join(PRIMARY)]["train"]
    Hd = per_day_hits(D, te, dyn_scorer(PRIMARY))
    Hv = per_day_hits(D, te, lambda i, d: d["v1s"])
    rng2 = np.random.default_rng(SEED + 1)
    Hr = np.mean([per_day_hits(D, te, lambda i, d: rng2.random(len(d["js"]))) for _ in range(50)], axis=0)
    A["boot_dyn_minus_v1pool"] = dict(zip(("top10", "top30"), boot_diff(Hd, Hv)))
    A["boot_dyn_minus_random"] = dict(zip(("top10", "top30"), boot_diff(Hd, Hr)))
    A["random_in_pool_test_mean50"] = {"top10": round(float(Hr[:, 0].sum() / Hr[:, -1].sum()), 4), "top30": round(float(Hr[:, 1].sum() / Hr[:, -1].sum()), 4)}
    # 单特征: 训练窗定方向, 验证窗 TopN
    single = []
    for cp in ("09:25", "09:35"):
        etr = [i for i in tr if cp_ok(cp, day_t.get(i, "99"))]; ete = [i for i in te if cp_ok(cp, day_t.get(i, "99"))]
        for nm in OPEN_FEATS:
            k = OPEN_FEATS.index(nm)
            if not any(np.isfinite(D[i]["F"][cp][:, k]).any() for i in etr[:5]):
                continue
            best = None
            for sgn in (1, -1):
                f = (lambda sgn_: (lambda i, d: sgn_ * np.nan_to_num(d["F"][cp][:, k], nan=-sgn_ * 1e9)))(sgn)
                r = topn_cover(D, etr, f)
                if best is None or r["cover"][30] > best[1]["cover"][30]:
                    best = (sgn, r, f)
            rte = topn_cover(D, ete, best[2])
            single.append({"cp": cp, "feat": nm, "cn": OPEN_CN.get(nm, nm), "dir": "大优先" if best[0] == 1 else "小优先",
                           "train30": best[1]["cover"][30], "test": rte["cover"], "test_pct_rank_med": rte["inpool_pct_rank_med"]})
    A["single"] = single
    # 消融(09:35): 拿掉/只用 一组开盘特征
    cp = "09:35"
    etr = [i for i in tr if cp_ok(cp, day_t.get(i, "99"))]; ete = [i for i in te if cp_ok(cp, day_t.get(i, "99"))]
    groups = {"竞价组": ["auc_gap", "auc_lamt", "auc_vr", "auc_amt_rk"], "价格路径组": ["ret", "ret_o", "hi", "dd", "lo_o", "vwap_r", "mom3", "to_lu"],
              "量能组": ["lvr", "amt_rk", "buy_frac", "ntk"], "同伴组": ["peer_auc", "peer_ret", "rel_peer"]}
    abl = {}
    kd, md = PRIMARY
    fm, _ = fit_cl(D, etr, cp, True, kind=kd, mode=md)
    abl["日线+全部开盘特征"] = topn_cover(D, ete, cl_scorer(fm, cp, True, mode=md))
    m0, _ = fit_cl(D, etr, cp, False, kind=kd, mode=md)
    abl["只日线"] = topn_cover(D, ete, cl_scorer(m0, cp, False, mode=md))
    for g, fs in groups.items():
        keep = [x for x in OPEN_FEATS if x not in fs]
        m, _ = fit_cl(D, etr, cp, True, keep, kind=kd, mode=md)
        abl["去掉" + g] = topn_cover(D, ete, cl_scorer(m, cp, True, keep, mode=md))
        m, _ = fit_cl(D, etr, cp, True, fs, kind=kd, mode=md)
        abl["日线+只" + g] = topn_cover(D, ete, cl_scorer(m, cp, True, fs, mode=md))
    abl["_kind"] = "/".join(PRIMARY)
    A["ablation_0935"] = abl
    return A, models, (tr, te)


def sec_profile(C, D, rows=None):
    """描述: 他的票在买入那一分钟前的开盘特征 在当日池内的百分位(0.5=无偏好); 只用他买入前的逐笔. rows=只用这些日子(默认全部)"""
    M = C["M"]
    _day_t, pair_t = first_new_buy(C)
    per = defaultdict(list); raw = defaultdict(lambda: ([], []))
    for i, d in D.items():
        if rows is not None and i not in rows:
            continue
        pool_set = set(int(x) for x in d["js"])
        for j in d["allpos"]:
            t = pair_t.get((i, j))
            if not t:
                continue
            cp = min(t[:5], "10:00")
            if cp < "09:30":
                continue
            js = d["js"] if j in pool_set else np.append(d["js"], j)
            F, ok = day_open_matrix(M, i, js, d["recs"], cp)
            k = int(np.where(js == j)[0][0])
            if not ok[k]:
                continue
            for q, nm in enumerate(OPEN_FEATS):
                v = F[:, q]
                if not np.isfinite(v[k]):
                    continue
                m = ok & np.isfinite(v)
                per[nm].append(float((v[m] < v[k]).mean() + 0.5 * ((v[m] == v[k]).mean() - 1.0 / m.sum())))
                raw[nm][0].append(float(v[k])); raw[nm][1].append(float(np.nanmedian(v[m])))
    out = {}
    for nm in OPEN_FEATS:
        if per[nm]:
            a = np.array(per[nm])
            out[nm] = {"cn": OPEN_CN[nm], "n": len(a), "pct_med": round(float(np.median(a)), 3), "pct_mean": round(float(a.mean()), 3),
                       "share_top30pct": round(float((a >= 0.7).mean()), 3), "share_bottom30pct": round(float((a <= 0.3).mean()), 3),
                       "his_med": round(float(np.median(raw[nm][0])), 4), "pool_med": round(float(np.median(raw[nm][1])), 4)}
    return out


def call_auction_final(day, syms=None):
    """行情库 call_auction(只读): 当日开盘竞价最后一笔快照(≥09:25:00 的第一行 = 撮合结果; 无则取最后一行) → {symbol: (价, 量股, 时刻)}"""
    from kline_db import db
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("select symbol, snap_time, cast(price as double), matched_volume from call_auction "
                    "where trade_date=%s and phase='OPEN' and status=0 and is_deleted=0 order by symbol, snap_time", (day,))
        rows = cur.fetchall()
    finally:
        conn.close()
    out = {}
    for sym, t, px, vol in rows:
        if syms and sym not in syms:
            continue
        ts = t.strftime("%H:%M:%S")
        cur_ = out.get(sym)
        if cur_ is None or cur_[2] < "09:25:00":       # 直到第一条 ≥09:25:00 为止一直覆盖
            out[sym] = (px, vol, ts)
    return out


def cmd_validate_auction():
    """近几日 call_auction(新浪源, 行情库只读) vs 通达信逐笔 09:25 撮合 —— 价/量对照"""
    days = sorted(f.stem for f in TICK_DIR.glob("20*.jsonl") if f.stem >= "2026-10-12")
    res = {}
    for day in days:
        recs = load_ticks(day)
        ca = call_auction_final(day, set(recs))
        dp, dv, n, nomatch = [], [], 0, 0
        for sym, r in recs.items():
            t = [x for x in (r.get("ticks") or []) if x[0] == "09:25"]
            if not t or sym not in ca:
                nomatch += 1
                continue
            px, vol, ts = ca[sym]
            if not px or not vol:
                continue
            n += 1
            dp.append(abs(t[0][1] / px - 1)); dv.append(sum(x[2] for x in t) * 100 / vol - 1)
        if n:
            res[day] = {"n": n, "unmatched": nomatch, "price_exact_share": round(float(np.mean(np.array(dp) < 1e-4)), 3),
                        "price_absdiff_p95": round(float(np.percentile(dp, 95)), 5), "vol_ratio_minus1_med": round(float(np.median(dv)), 4),
                        "vol_within_1pct_share": round(float(np.mean(np.abs(dv) < 0.01)), 3)}
        log(f"[竞价对照] {day}: {res.get(day)}")
    return res


def jsonable(o):
    return rl.jsonable(o)


# ====================================================================================
# 1b. 全市场宽口径(诊断用): 最近 N 个买入日 × 全部主板/创业/科创(非 ST, 昨成交额 ≥0.3 亿) 的通达信历史分时
#     (1 请求/只/日; 240 点 价+量, 首点含竞价量; 竞价价=日线开盘价) → open_ticks/wide_<D>.jsonl
# ====================================================================================
WIDE_MIN_AMT = 0.3e8
WIDE_KEEP = 60                           # 只存 09:31~10:30 共 60 点


def wide_universe(M, i):
    """D(行 i) 全市场宽口径: 只用 D 前一日信息(+ D 日是否停牌)"""
    js = np.where(np.isin(M.asset, POOL_ASSETS) & ~M.is_st & M.has[i - 1] & (M.nbars[i - 1] >= 20)
                  & (np.nan_to_num(M.amt[i - 1], nan=0) >= WIDE_MIN_AMT))[0]
    if i < len(M.dates):
        js = js[M.has[i, js]]
    return js


def wide_file(day):
    return TICK_DIR / f"wide_{day}.jsonl"


def load_wide(day):
    out = {}
    f = wide_file(day)
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            out[r["sym"]] = r
    return out


def cmd_fetch_wide(n_days=20, worker=0, nworkers=1, host=8):
    C = ctx()
    M = C["M"]
    cm = rl_cm()
    days = buy_days(C)[::-1][:n_days][worker::nworkers]
    TICK_DIR.mkdir(parents=True, exist_ok=True)
    api, t0, n = None, time.time(), 0
    for di, i in enumerate(days):
        day = M.dates[i]; ymd = int(day.replace("-", ""))
        js = wide_universe(M, i)
        have = load_wide(day)
        todo = [j for j in js if M.syms[j] not in have]
        miss = 0
        if not todo:
            continue
        if api is None:
            api = connect(ymd, host)
        with wide_file(day).open("a", encoding="utf-8") as fh:
            for j in todo:
                sym = M.syms[j]
                h, l, c = float(M.H[i, j]), float(M.L[i, j]), float(M.C[i, j])
                rec = {"sym": sym}
                for attempt in range(2):
                    try:
                        r = api.get_history_minute_time_data(cm.tdx_market(sym), sym[2:], ymd)
                        time.sleep(random.uniform(0.15, 0.30))
                    except Exception as e:   # noqa: BLE001
                        log(f"  失败 {day} {sym}: {e}")
                        r = None
                        try:
                            api.disconnect()
                        except Exception:   # noqa: BLE001
                            pass
                        api = connect(ymd, host)
                        continue
                    ps = [x["price"] for x in (r or [])]
                    if r and len(r) >= 200 and abs(ps[-1] / c - 1) <= 0.01 and max(ps) <= h * 1.01 and min(ps) >= l * 0.99:
                        rec["mt"] = [[round(x["price"], 3), int(x["vol"])] for x in r[:WIDE_KEEP]]
                        break
                    if r and attempt == 0:
                        try:
                            api.disconnect()
                        except Exception:   # noqa: BLE001
                            pass
                        api = connect(ymd, host)
                if "mt" not in rec:
                    rec["miss"] = True; miss += 1
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
        el = time.time() - t0
        log(f"[{time.strftime('%H:%M:%S')}] 宽口径 {day}: {len(js)} 只, 新取 {len(todo)} 缺 {miss} | {di + 1}/{len(days)} 日 累计 {n} 只 {el:.0f}s ({el / max(n, 1):.2f}s/只)")
    if api is not None:
        api.disconnect()


def wide_feats(M, i, js, W, cp):
    """宽口径特征(分时版): 决策时点 cp 只用标签 ≤ cp 的分钟点(标签 09:31 = 09:30:00~09:30:59)"""
    names = ["auc_gap", "ret", "ret_o", "hi", "dd", "lvr", "mom3", "to_lu", "rel_peer", "peer_ret"]
    F = np.full((len(js), len(names)), np.nan); ok = np.zeros(len(js), bool)
    nlab = max(0, (int(cp[:2]) * 60 + int(cp[3:]) - (9 * 60 + 30)))          # 可用点数
    for k, j in enumerate(js):
        r = W.get(M.syms[j])
        if not r or r.get("miss"):
            continue
        pc, o = float(M.PC[i, j]), float(M.O[i, j])
        if not (np.isfinite(pc) and np.isfinite(o) and pc > 0):
            continue
        ok[k] = True
        F[k, 0] = o / pc - 1
        lu = float(M.lu[i, j]) if np.isfinite(M.lu[i, j]) else np.nan
        pts = r["mt"][:nlab]
        if pts:
            ps = np.array([p for p, _ in pts]); vol = sum(v for _, v in pts) * 100.0
            last, hi = ps[-1], max(ps.max(), o)
            pv = float(M.V[i - 1, j])
            F[k, 1:8] = [last / pc - 1, last / o - 1, hi / pc - 1, last / hi - 1,
                         math.log1p(min(vol / pv, 5) * 100) if pv > 0 else np.nan, last / (ps[-4] if len(ps) >= 4 else o) - 1, lu / last - 1]
        else:
            F[k, 7] = lu / o - 1
    P = peers(M, i, js)
    own = np.where(np.isfinite(F[:, 1]), F[:, 1], F[:, 0])
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pr = np.nanmean(own[P], axis=1)
    F[:, 9] = pr; F[:, 8] = own - pr
    return F, ok, names


def v1_wide(C, i, js):
    """第一轮全市场日线模型分(行 i 用 i-1 收盘) → 对齐到 js"""
    M = C["M"]
    ja, Xa = rl.day_features(M, C["SH"], i - 1)
    mp = dict(zip(ja.tolist(), C["v1"].score(Xa).tolist()))
    return np.array([mp.get(int(j), np.nan) for j in js])


def sec_wide(C, wts=None, train_rows=()):
    """全市场宽口径诊断: 他的票买入前那一刻, 在全市场(主板/创业/科创)里的百分位 + 单特征/组合 全市场 TopN。
    wts: {特征: 权重} 来自池内训练窗画像(百分位中位-0.5), 组合分 = Σ w·池内百分位 + w_v1·第一轮日线分百分位(w_v1 由训练窗全市场算)"""
    M = C["M"]
    _day_t, pair_t = first_new_buy(C)
    days = [i for i in buy_days(C) if wide_file(M.dates[i]).exists()]
    res = {"days": [], "profile": {}, "single": {}}
    per = defaultdict(list); hits = defaultdict(Counter); npos = 0; size = []
    # w_v1: 训练窗他的票在全市场(宽口径同条件)第一轮日线分的百分位中位 - 0.5
    pv = []
    for i in train_rows:
        js_ = wide_universe(M, i)
        v = v1_wide(C, i, js_); jset_ = {int(j): k for k, j in enumerate(js_)}
        for j in C["pos"][i]:
            k = jset_.get(int(j))
            if k is not None and np.isfinite(v[k]):
                m = np.isfinite(v)
                pv.append(float((v[m] < v[k]).mean()))
    w_v1 = (float(np.median(pv)) - 0.5) if pv else 0.0
    res["w_v1"] = round(w_v1, 3); res["weights"] = {k: round(x, 3) for k, x in (wts or {}).items()}
    for i in days:
        day = M.dates[i]
        js = wide_universe(M, i)
        W = load_wide(day)
        if sum(1 for j in js if M.syms[j] in W) < 0.97 * len(js):
            continue
        res["days"].append(day); size.append(len(js))
        jset = {int(j): k for k, j in enumerate(js)}
        for j in C["pos"][i]:
            t = pair_t.get((i, int(j)))
            if not t or t[:5] < "09:30" or int(j) not in jset:
                continue
            cp = min(t[:5], "10:30")
            F, ok, names = wide_feats(M, i, js, W, cp)
            k = jset[int(j)]
            if not ok[k]:
                continue
            npos += 1
            v1r = pct_rank(v1_wide(C, i, js))
            co = np.zeros(len(js))
            for q, nm in enumerate(names):
                if wts and nm in wts:
                    co = co + wts[nm] * pct_rank(np.where(ok, F[:, q], np.nan))
            F = np.column_stack([F, w_v1 * v1r + co, v1r, co]); names = names + ["combo", "v1only", "openonly"]
            for q, nm in enumerate(names):
                v = F[:, q]; m = ok & np.isfinite(v)
                if not np.isfinite(v[k]) or m.sum() < 10:
                    continue
                pr_ = float((v[m] < v[k]).mean() + 0.5 * ((v[m] == v[k]).mean() - 1.0 / m.sum()))
                per[nm].append(pr_)
                eq = int((v[m] == v[k]).sum()) - 1                     # 并列(如回撤=0 的一大片)按中间名次, 不让并列白捡名次
                rk_hi, rk_lo = int((v[m] > v[k]).sum()) + eq / 2, int((v[m] < v[k]).sum()) + eq / 2
                for N in (10, 30, 50, 100, 300):
                    hits[(nm, "大")][N] += rk_hi < N; hits[(nm, "小")][N] += rk_lo < N
    res["universe_med"] = int(np.median(size)) if size else 0
    res["n_pos"] = npos
    WCN = {"auc_gap": "竞价涨幅(=开盘缺口)", "ret": "当前涨幅", "ret_o": "相对开盘涨幅", "hi": "开盘以来最高涨幅", "dd": "距最高回撤",
           "lvr": "开盘以来量(含竞价)÷昨日量", "mom3": "近3分钟涨速", "to_lu": "距涨停空间", "rel_peer": "自身-同伴涨幅", "peer_ret": "同伴涨幅",
           "combo": "组合分(开盘画像定权 + 第一轮日线分)", "v1only": "只第一轮日线分(对照)", "openonly": "只开盘画像组合(对照)"}
    for nm, a in per.items():
        a = np.array(a)
        res["profile"][nm] = {"cn": WCN[nm], "n": len(a), "pct_med": round(float(np.median(a)), 3), "top10pct": round(float((a >= 0.9).mean()), 3),
                              "top30pct": round(float((a >= 0.7).mean()), 3), "bottom30pct": round(float((a <= 0.3).mean()), 3)}
        for d_ in ("大", "小"):
            res["single"][f"{WCN[nm]}·{d_}优先"] = {N: round(hits[(nm, d_)][N] / npos, 3) for N in (10, 30, 50, 100, 300)} if npos else None
    return res


def fetch_status(C):
    M = C["M"]
    rows = buy_days(C)
    done = 0; part = 0
    for i in rows:
        n = len(load_ticks(M.dates[i]))
        if n >= 300:
            done += 1
        elif n:
            part += 1
    return {"buy_days": len(rows), "days_done": done, "days_partial": part, "first": M.dates[rows[0]], "last": M.dates[rows[-1]]}


def cmd_analyze(no_report=False):
    t0 = time.time()
    C = ctx()
    M = C["M"]
    rows = buy_days(C)
    D = load_days(C, rows)
    log(f"[数据] 买入日 {len(rows)}, 逐笔齐全 {len(D)} 日 ({time.time() - t0:.0f}s)")
    A, models, (tr, te) = sec_v2(C, D)
    A["profile"] = sec_profile(C, D)
    # 池内 vs 池外 他的票: 昨成交额 / 股价 / 第一轮全市场日线分名次
    oop = {"in": defaultdict(list), "out": defaultdict(list)}
    for i, d in D.items():
        ps = set(int(x) for x in d["js"])
        for j in d["allpos"]:
            g_ = oop["in" if j in ps else "out"]
            g_["amt_e8"].append(float(M.amt[i - 1, j]) / 1e8); g_["px"].append(float(M.C[i - 1, j]))
    A["pool_in_out"] = {k: {kk: round(float(np.nanmedian(vv)), 2) for kk, vv in v.items()} | {"n": len(v["px"])} for k, v in oop.items()}
    tr_rows = sorted(D)[:int(len(D) * rl.TRAIN_FRAC)]
    ptr = sec_profile(C, D, set(tr_rows))
    wts = {k: x["pct_med"] - 0.5 for k, x in ptr.items()
           if k in ("auc_gap", "ret", "ret_o", "hi", "dd", "lvr", "mom3", "to_lu", "rel_peer", "peer_ret") and abs(x["pct_med"] - 0.5) >= 0.05}
    A["profile_train_weights"] = {k: round(v_, 3) for k, v_ in wts.items()}
    A["wide"] = sec_wide(C, wts, [i for i in tr_rows if i in C["pos"]][-40:])
    A["fetch"] = fetch_status(C)
    A["auction_check"] = cmd_validate_auction()
    A["generated"] = dtm.datetime.now().isoformat(timespec="seconds")
    # 给 --signal 用: 每个决策点用全部已取日子重训(走步: 只含 < 信号日的数据, 信号日一般在样本之后)
    day_t, _ = first_new_buy(C)
    full = {}
    for cp in ["pre"] + CHECKPOINTS:
        cpk = "09:25" if cp == "pre" else cp
        rr = [i for i in sorted(D) if cp == "pre" or cp_ok(cp, day_t.get(i, "99"))]
        m, names = fit_cl(D, rr, cpk, cp != "pre", kind=PRIMARY[0], mode=PRIMARY[1])
        if m is not None:
            full[cp] = m.to_json(names) | {"days": len(rr), "until": M.dates[max(rr)], "kind": PRIMARY[0], "mode": PRIMARY[1]}
    params = {"ledger": LEDGER, "pool": {"lr_top": POOL_LR_N, "amt_top": POOL_AMT_N, "assets": POOL_ASSETS, "v1_params": "reverse_lianghua/model_params.json"},
              "checkpoints": CHECKPOINTS, "models": full, "generated": A["generated"]}
    (OUT_DIR / "v2_params.json").write_text(json.dumps(jsonable(params), ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT_DIR / "v2_analysis.json").write_text(json.dumps(jsonable(A), ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[完成] {time.time() - t0:.0f}s → {OUT_DIR / 'v2_analysis.json'}")
    narrative(A)
    A["residual"] = residual_probs(A)
    (OUT_DIR / "v2_analysis.json").write_text(json.dumps(jsonable(A), ensure_ascii=False, indent=1), encoding="utf-8")
    if not no_report:
        write_report(A)
    return A


def realtime_tick_recs(api, M, js):
    """当日实时逐笔(get_transaction_data, 开盘后 1 小时内每只 1 次请求即全量) → 与历史 open_ticks 同格式的 rec"""
    cm = rl_cm()
    out = {}
    for j in js:
        sym = M.syms[j]
        ticks, start = [], 0
        for _ in range(4):
            r = api.get_transaction_data(cm.tdx_market(sym), sym[2:], start, 2000)
            time.sleep(random.uniform(0.15, 0.30))
            if not r:
                break
            ticks = list(r) + ticks
            start += len(r)
            if len(r) < 2000:
                break
        if ticks and ticks[0]["time"] <= "09:30":
            out[sym] = {"sym": sym, "ticks": [[x["time"], x["price"], x["vol"], x.get("buyorsell", 2)] for x in ticks if x["time"] < TICK_CUT],
                        "t_last": ticks[-1]["time"], "total": len(ticks), "rt_ticks": True}
    return out


def realtime_recs(api, M, js, i, day):
    """当日实时(通达信快照 get_security_quotes, 每 80 只一请求) → {symbol: rec(rt=True)}:
    竞价 = 行情库 call_auction 的 09:25 撮合(只读; 无则用快照开盘价 + 09:30 前的快照成交量); 连续竞价段 = 快照 开/高/低/现价/量/额。
    主动买占比/近3分钟涨速/逐笔笔数 快照里没有 → NaN(排序时按中性 0.5)"""
    cm = rl_cm()
    syms = [M.syms[j] for j in js]
    ca = call_auction_final(day, set(syms))
    out = {}
    now = dtm.datetime.now().strftime("%H:%M")
    for k in range(0, len(syms), 80):
        part = syms[k:k + 80]
        q = api.get_security_quotes([(cm.tdx_market(s), s[2:]) for s in part]) or []
        time.sleep(random.uniform(0.15, 0.30))
        for x in q:
            s = ("sh" if x.get("market") == 1 else "sz") + str(x.get("code"))
            if s not in ca and not x.get("open"):
                continue
            a = ca.get(s)
            out[s] = {"sym": s, "rt": True, "now": now, "q": {k_: float(x.get(k_) or 0) for k_ in ("open", "high", "low", "price", "vol", "amount")},
                      "auc_px": (a[0] if a and a[0] else float(x.get("open") or 0)) or None,
                      "auc_vol": (float(a[1]) if a and a[1] else (float(x.get("vol") or 0) * 100 if now < "09:30" else None))}
    return out


def open_feats_rt(rec, pc, prev_vol, cp, lu=None):
    """实时快照版 open_feats_one(口径尽量对齐逐笔版)"""
    q, a_px, a_vol = rec["q"], rec.get("auc_px"), rec.get("auc_vol")
    if not pc or not a_px:
        return None
    f = {"auc_gap": a_px / pc - 1, "auc_lamt": math.log10((a_vol or 0) * a_px + 1),
         "auc_vr": (a_vol / prev_vol) if a_vol and prev_vol and np.isfinite(prev_vol) and prev_vol > 0 else np.nan}
    for k_ in ("ret", "ret_o", "hi", "dd", "lo_o", "vwap_r", "lvr", "buy_frac", "mom3", "ntk"):
        f[k_] = np.nan
    f["_amt"] = 0.0
    last = a_px
    if cp > "09:25" and rec["now"] >= "09:30" and q["price"] > 0 and q["vol"] > 0:
        last = q["price"]; hi = max(q["high"], a_px); lo = min(q["low"], a_px)
        vol = max(q["vol"] * 100 - (a_vol or 0), 0); amt = max(q["amount"] - (a_vol or 0) * a_px, 0)
        f.update({"ret": last / pc - 1, "ret_o": last / a_px - 1, "hi": hi / pc - 1, "dd": last / hi - 1, "lo_o": lo / a_px - 1,
                  "vwap_r": last / (q["amount"] / (q["vol"] * 100)) - 1,
                  "lvr": math.log1p(min(vol / prev_vol, 5) * 100) if prev_vol and np.isfinite(prev_vol) and prev_vol > 0 else np.nan, "_amt": amt})
    f["to_lu"] = (lu / last - 1) if (lu and last and np.isfinite(lu)) else np.nan
    return f


def cmd_signal(day, asof=None, topn=30):
    """D 日前 30 名候选。盘前(asof<09:25)=只有日线排序; 09:25 后=+竞价; 09:3x 后=+开盘 N 分钟(只用 asof 之前的数据)"""
    C = ctx()
    M, SH, v1 = C["M"], C["SH"], C["v1"]
    pf = OUT_DIR / "v2_params.json"
    if not pf.exists():
        raise SystemExit("缺 reverse_lianghua/v2_params.json, 先跑 --analyze")
    P = json.loads(pf.read_text(encoding="utf-8"))
    today = dtm.date.today().isoformat()
    if day in M.didx:
        i = M.didx[day]
    elif day > M.dates[-1]:
        i = len(M.dates)
    else:
        raise SystemExit(f"{day} 不是交易日")
    is_rt = day > today or (day == today and dtm.datetime.now().strftime("%H:%M") < "15:05")   # 当日收盘后改走历史逐笔
    if asof is None:
        asof = dtm.datetime.now().strftime("%H:%M") if is_rt else "09:45"
    if is_rt and day > today:
        asof = "09:00"                          # 未来日: 只能出盘前
    js, Xd, src, v1sc = build_pool(M, SH, v1, i)
    stage_cps = [cp for cp in CHECKPOINTS if (asof >= "09:25" if cp == "09:25" else asof >= cp)]
    if is_rt and stage_cps:
        stage_cps = stage_cps[-1:]              # 实时只有"现在"一个快照: 用最后一档模型
    recs, rt_src = {}, None
    if stage_cps:
        if is_rt:
            api = connect(None)
            try:
                recs = realtime_tick_recs(api, M, js)            # 首选: 当日实时逐笔(与回测同口径)
                rt_src = "tdx_ticks_today"
                if len(recs) < 0.5 * len(js):
                    recs = realtime_recs(api, M, js, i, day)     # 退路: 快照
                    rt_src = "tdx_quotes"
            finally:
                api.disconnect()
            if len(recs) < 0.5 * len(js):
                log(f"[信号] 实时数据只拿到 {len(recs)}/{len(js)} 只(非交易时段/服务器不给实时?) → 只输出盘前档")
                stage_cps = []
        else:
            recs = load_ticks(day)
            miss = [j for j in js if M.syms[j] not in recs]
            if miss:
                ymd = int(day.replace("-", ""))
                api = connect(ymd)
                TICK_DIR.mkdir(parents=True, exist_ok=True)
                try:
                    with tick_file(day).open("a", encoding="utf-8") as fh:
                        for j in miss:
                            ticks, total, _n = earliest_ticks(api, M.syms[j], ymd)
                            rec = {"sym": M.syms[j], "in_pool": True, "src": src[int(j)], "signal_fetch": True}
                            if ticks:
                                rec.update(ticks=[[x["time"], x["price"], x["vol"], x["buyorsell"]] for x in ticks if x["time"] < TICK_CUT], total=total)
                            else:
                                rec["miss"] = True
                            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                            recs[M.syms[j]] = rec
                finally:
                    api.disconnect()
    stages = {}
    for cp in ["pre"] + stage_cps:
        mj = P["models"].get(cp)
        if not mj:
            continue
        model = CLogit.from_json(mj)          # naive 与 clogit 打分形式相同: ((Z-mu)/sd) @ w
        cpk = "09:25" if cp == "pre" else cp
        F, ok = day_open_matrix(M, i, js, recs, cpk)
        Z, names = design(Xd, F, cp != "pre", None, v1sc if mj.get("mode", "v1") == "v1" else None)
        sc = model.score(Z)
        order = np.argsort(-sc)[:topn]
        rows_ = []
        for r, k in enumerate(order):
            j = js[k]
            f = {nm: (round(float(F[k, OPEN_FEATS.index(nm)]), 4) if np.isfinite(F[k, OPEN_FEATS.index(nm)]) else None) for nm in ("auc_gap", "auc_vr", "ret", "dd", "vwap_r")}
            rows_.append({"rank": r + 1, "symbol": M.syms[j], "name": M.name.get(M.syms[j]), "score": round(float(sc[k]), 3), "pool_src": src[int(j)],
                          "prev_close": round(float(M.C[i - 1, j]), 3), **({"open": f} if cp != "pre" else {})})
        stages[cp] = {"model_days": mj.get("days"), "model_until": mj.get("until"), "top": rows_, "data_ok": int(ok.sum()) if cp != "pre" else None, "cpk": cpk}
    last = (["pre"] + stage_cps)[-1]
    ex = json.loads((OUT_DIR / "model_params.json").read_text(encoding="utf-8"))["exec"]
    AN = json.loads((OUT_DIR / "v2_analysis.json").read_text(encoding="utf-8")) if (OUT_DIR / "v2_analysis.json").exists() else {}
    out = {
        "ledger": LEDGER, "date": day, "asof": asof, "realtime": bool(is_rt), "realtime_source": rt_src, "pool_size": len(js), "stage_used": last,
        "candidates": stages[last]["top"] if last in stages else [],
        "recommend": ("时间外验证: 加竞价/开盘特征的池内排序没有胜过盘前日线排序(Top30 甚至更低) → 挑票参考优先看 stages.pre 的前 30; "
                      "开盘档(09:25/09:3x)只用来剔除「开盘后走弱/回落」的票(他的票在全市场开盘强度 0.85~0.9 分位, 池内 0.6~0.7)。"),
        "stages": stages,
        "stage_note": "盘前(<09:25)只能给日线排序(pre); 09:25 竞价撮合后可更新为 09:25 排序; 09:31/09:33/09:35/09:40/09:45 再逐次更新(只用该时刻之前的数据)。"
                      "真人首买中位 ~09:41, 用到的最晚一档应在他下单前。",
        "exec_rule": {"K": ex["K"], "buy_window": f"09:31 ~ 10:00, 目标首买 {ex['first_buy_hhmm']}", "sizing": "1/K 可用资金逐只, 末只全仓",
                      "avoid": "距开盘以来最高回撤≥2% 或 跌破分时均价 1% 不买", "exit": "次日开盘窗清仓(竞价缺口≥阈值走竞价)"},
        "fidelity": {"v2_dynamic_test_cover": (AN.get("dynamic_test") or {}).get("cover"), "v1_fullmarket_test_cover": (AN.get("v1_fullmarket_test") or {}).get("cover"),
                     "note": "覆盖率=他当日新开仓落在本排序 TopN 的比例(时间外), 详见 docs/research/reverse_lianghua_v2_20261016.md"},
        "realtime_caveat": ("当日实时: 首选通达信当日逐笔(与回测同口径); 拿不到时退到快照(主动买占比/近3分钟涨速/笔数缺失按中性处理, 与回测口径有差); "
                            "两者都拿不到(非交易时段)只输出盘前档。10/17 夜间实测两个实时接口都返回空, 交易时段可用性未验证") if is_rt else None,
        "generated": dtm.datetime.now().isoformat(timespec="seconds"),
    }
    SIG_DIR.mkdir(parents=True, exist_ok=True)
    f = SIG_DIR / f"lianghua_v2_signal_{day}.json"
    f.write_text(json.dumps(jsonable(out), ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(jsonable({"date": day, "asof": asof, "stage_used": last, "pool": len(js),
                               "top10": [(c["rank"], c["symbol"], c["name"], c["score"]) for c in out["candidates"][:10]]}), ensure_ascii=False, indent=1))
    log(f"[信号] {f}")
    return out


def selftest():
    ok = 0
    # earliest_ticks: 假 api(全天 n 笔, start=距末尾偏移)
    global _get
    real_get = _get

    class FakeApi:
        pass
    for n in (120, 1500, 2500, 3600, 3801, 4500, 4790, 6100):
        day = [{"time": "09:25" if k == 0 else ("09:30" if k < 50 else "10:30"), "price": 10.0, "vol": 1, "buyorsell": 2 if k == 0 else 0} for k in range(n)]

        def fake(api, sym, start, count, ymd, day=day):
            hi = len(day) - start
            return day[max(0, hi - count):max(0, hi)] if hi > 0 else []
        _get = fake
        try:
            r, total, nreq = earliest_ticks(FakeApi(), "sz000001", 20260101)
        finally:
            _get = real_get
        assert r and r[0]["time"] == "09:25" and len(r) >= min(n, 600), (n, len(r), total)
        assert nreq <= 4, (n, nreq)
    ok += 1
    # open_feats_one: 竞价 +2%, 之后涨到 +5% 回落到 +3%
    rec = {"ticks": [["09:25", 10.2, 100, 2], ["09:30", 10.3, 50, 0], ["09:31", 10.5, 50, 0], ["09:32", 10.3, 50, 1], ["09:40", 11.0, 10, 0]]}
    f = open_feats_one(rec, 10.0, 100000, "09:33", lu=11.0)
    assert abs(f["auc_gap"] - 0.02) < 1e-9 and abs(f["auc_vr"] - 0.1) < 1e-9
    assert abs(f["ret"] - 0.03) < 1e-9 and abs(f["hi"] - 0.05) < 1e-9 and abs(f["dd"] - (10.3 / 10.5 - 1)) < 1e-9 and abs(f["buy_frac"] - 2 / 3) < 1e-9
    assert abs(f["to_lu"] - (11.0 / 10.3 - 1)) < 1e-9
    f0 = open_feats_one(rec, 10.0, 100000, "09:25", lu=11.0)
    assert not np.isfinite(f0["ret"]) and abs(f0["to_lu"] - (11.0 / 10.2 - 1)) < 1e-9 and f0["auc_gap"] > 0   # 09:25 只看竞价
    ok += 1
    # 决策点 vs 买入时刻
    assert cp_ok("09:25", "09:30:05") and not cp_ok("09:25", "09:25:00") and cp_ok("09:35", "09:35:00") and not cp_ok("09:35", "09:34:59")
    ok += 1
    # 条件 logit: 植入"第 0 列大的被选"
    rng = np.random.default_rng(0)
    groups = []
    for _ in range(150):
        Z = rng.normal(size=(200, 4)); s = 2.5 * Z[:, 0]
        p = np.exp(s - s.max()); p /= p.sum()
        y = np.zeros(200); y[rng.choice(200, p=p)] = 1
        groups.append((Z, y))
    m = CLogit(l2=0.0, iters=300).fit(groups)
    assert m.w[0] > 1.5 and abs(m.w[1]) < 0.5, m.w
    m2 = CLogit.from_json(json.loads(json.dumps(m.to_json(["a", "b", "c", "d"]))))
    assert np.allclose(m2.score(groups[0][0]), m.score(groups[0][0]))
    ok += 1
    # 百分位
    r = pct_rank(np.array([3.0, np.nan, 1.0, 2.0]))
    assert list(r) == [1.0, 0.5, 0.0, 0.5]
    ok += 1
    print(f"selftest OK ({ok} 组)")


def pc_(x, nd=1):
    return "—" if x is None else f"{x * 100:.{nd}f}%"


def cov_row(name, r, Ns=(2, 5, 10, 30, 50), extra=""):
    if not r:
        return f"| {name} | " + " | ".join("—" for _ in Ns) + " | — | — |"
    c = r["cover"]
    return (f"| {name} | " + " | ".join(pc_(c.get(N) if N in c else c.get(str(N))) for N in Ns) +
            f" | {r.get('inpool_pct_rank_med', '—')} | {r.get('days', '—')} 日/{r.get('pos', '—')} 只{extra} |")


# 剩余解释的概率分布(主观, 看完本轮数据后定; 依据写在报告里)
RESIDUAL = None   # 由 write_report 按结果填(见 residual_probs)


def residual_probs(A):
    """选股还解释不了的部分 → 可能来源的主观概率(合计 100%)。似然比思路同第一轮 prog_probability: 等先验 × 证据似然比, 归一"""
    hyp = ["题材/新闻/公告驱动(盘前读消息定方向)", "同花顺热榜/人气榜/问财等外部排行榜", "盘中实时选股器(全市场分时条件, 我们的池子装不下)",
           "主观盘感挑票(无稳定规则)", "其他/证据不足"]
    prior = np.ones(len(hyp))
    ev = []
    dyn = (A.get("dynamic_test") or {}).get("cover", {})
    v1p = (A.get("v1_in_pool_test") or {}).get("cover", {})
    g = lambda d, N: d.get(N, d.get(str(N))) or 0
    lift = (g(dyn, 30) + 1e-3) / (g(v1p, 30) + 1e-3)
    pool_cov = A.get("pool_cover_all") or 0
    prof = A.get("profile") or {}
    rel = (prof.get("rel_peer") or {}).get("pct_med", 0.5)
    ret = (prof.get("ret") or {}).get("pct_med", 0.5)
    # 1) 开盘特征带来的提升小 → 不像纯盘中量价选股器
    if lift < 1.3:
        ev.append((f"加竞价/开盘特征后池内 Top30 覆盖仅为日线版的 ×{lift:.2f}", [1.2, 1.1, 0.6, 1.2, 1.0]))
    elif lift < 2:
        ev.append((f"加竞价/开盘特征后池内 Top30 覆盖为日线版 ×{lift:.2f}(有提升但不锐利)", [1.0, 1.0, 1.1, 1.0, 1.0]))
    else:
        ev.append((f"加竞价/开盘特征后池内 Top30 覆盖为日线版 ×{lift:.2f}", [0.8, 1.0, 1.6, 0.8, 1.0]))
    # 2) 池子覆盖低 → 选的票经常不在"日线强势 + 高成交额"池里
    if pool_cov < 0.6:
        ev.append((f"日线候选池(~{A.get('pool_size_med')} 只)只装下他 {pool_cov:.0%} 的票", [1.3, 1.2, 1.2, 1.1, 1.0]))
    # 3) 他的票开盘相对同伴更强 → 有"盘中看强弱"的成分
    if ret >= 0.6 or rel >= 0.6:
        ev.append((f"他的票买入前涨幅池内百分位中位 {ret:.2f}, 相对同伴领涨度 {rel:.2f}(偏强但不极端)", [1.0, 1.2, 1.2, 1.0, 1.0]))
    else:
        ev.append((f"他的票买入前涨幅池内百分位中位 {ret:.2f}, 领涨度 {rel:.2f}(没有明显偏强)", [1.2, 1.0, 0.7, 1.2, 1.0]))
    # 4) 第一轮: 日线连全天信息(后见)也只到 Top50 12%; 账户名「量化」、每日 2~3 只、09:31 后逐只手动下单
    wp = (A.get("wide") or {}).get("profile") or {}
    if wp:
        hi_ = (wp.get("hi") or {}).get("pct_med", 0.5)
        ev.append((f"全市场口径: 他的票买入前「开盘以来最高涨幅」百分位中位 {hi_:.2f}, 组合分前 300 名覆盖约一半, 但前 30 名挑不中", [1.0, 1.3, 1.2, 0.9, 1.0]))
    ev.append(("第一轮: 连当日全天量价(后见)都只把 Top50 抬到 12%; 下单是 App 按钮式逐只手动", [1.2, 1.2, 0.8, 1.1, 1.0]))
    ev.append(("账户自称「量化短线小号实验」, 9 个月几乎每日出手、只数/时段机械", [0.9, 1.2, 1.3, 0.6, 1.0]))
    post = prior.copy()
    for _, lr in ev:
        post *= np.array(lr)
    post /= post.sum()
    pr = [int(round(x * 100)) for x in post]
    pr[-1] += 100 - sum(pr)
    return {"hyp": hyp, "post": pr, "evidence": ev}


def narrative(A):
    """结论文字(数字全部从 A 取; 判断阈值写死在这里)"""
    g = lambda d, N: (d or {}).get(N, (d or {}).get(str(N))) or 0
    prof = A.get("profile") or {}
    top = sorted(prof.items(), key=lambda kv: -abs(kv[1]["pct_med"] - 0.5))[:5]
    W = A.get("wide") or {}
    wp = W.get("profile") or {}
    dyn, v1p = A.get("dynamic_test") or {}, A.get("v1_in_pool_test") or {}
    ab = A.get("ablation_0935") or {}
    lift30 = g(dyn.get("cover"), 30) - g(v1p.get("cover"), 30)
    txt = ("描述层(他买入前那一刻, 池内百分位, 0.5=无偏好): " + "; ".join(f"{x['cn']} {x['pct_med']:.2f}" for _, x in top) +
           " —— 偏「开盘后在走强、相对自身放量、但成交额/竞价额在池里偏小」的票; 竞价涨幅({:.2f})、竞价量比({:.2f})本身没有偏好。".format(
               (prof.get("auc_gap") or {}).get("pct_med", 0.5), (prof.get("auc_vr") or {}).get("pct_med", 0.5)))
    if wp:
        wt = sorted(((k, x) for k, x in wp.items() if k not in ("combo", "v1only", "openonly")), key=lambda kv: -kv[1]["pct_med"])[:3]
        txt += " 全市场口径: " + "; ".join(f"{x['cn']} {x['pct_med']:.2f}" for _, x in wt) + "(他的票在全市场偏强一档, 但远不到「榜首」)。"
    bt = (A.get("boot_dyn_minus_v1pool") or {}).get("top30") or [0, 0]
    sig = "区间不含 0, 显著更差" if bt[1] < 0 else ("区间不含 0, 显著更好" if bt[0] > 0 else "区间跨 0")
    ws = W.get("single") or {}
    gw = lambda k, N: (ws.get(k) or {}).get(N, (ws.get(k) or {}).get(str(N)))
    txt += (f" 预测层(池内): 偏好太温和(百分位 0.6~0.7), 加开盘特征后时间外 Top30 比池内日线排序 {lift30 * 100:+.1f} 个百分点(bootstrap 90% {bt}, {sig})。")
    if ws:
        txt += (f" 预测层(全市场, 最近 {len(W.get('days', []))} 个买入日, 时间外): 组合分 Top30/Top100/Top300 = {pc_(gw('组合分(开盘画像定权 + 第一轮日线分)·大优先', 30))}/"
                f"{pc_(gw('组合分(开盘画像定权 + 第一轮日线分)·大优先', 100))}/{pc_(gw('组合分(开盘画像定权 + 第一轮日线分)·大优先', 300))}, "
                f"只日线 {pc_(gw('只第一轮日线分(对照)·大优先', 30))}/{pc_(gw('只第一轮日线分(对照)·大优先', 100))}/{pc_(gw('只第一轮日线分(对照)·大优先', 300))}, "
                f"只开盘 {pc_(gw('只开盘画像组合(对照)·大优先', 30))}/{pc_(gw('只开盘画像组合(对照)·大优先', 100))}/{pc_(gw('只开盘画像组合(对照)·大优先', 300))} —— "
                "只用开盘强度也能把他的票从全市场 4000+ 只粗筛到前几百(Top300 约为随机的 5 倍), 但不如昨日日线分, 叠加到日线分上不增反降; 前 30 名都挑不中(样本 <50 只)。")
    A["key_feature_text"] = txt
    A["paper_verdict"] = ("**选股层仍不能规则化接 paper**: 竞价/开盘特征没有带来可验证的时间外提升, `--signal` 的前 30 名只能当 LLM 挑票的候选池/参考; "
                          "执行层(次日开盘窗清仓、09:3x 后逐只买、回避回落)沿用第一轮 --signal 的规则。若要接, 建议 A-lianghuaxiaohao 链"
                          "盘前读 v2 `stages.pre` 前 30 作候选、09:3x 用开盘档剔除开盘后走弱的票, 再结合当日题材/热榜信息让 LLM 选 2~3 只; 把 v2 Top30 命中率当链的监控指标, 不用 Top2 直接下单。")
    A["discussion"] = ["", "### 判读", "",
                       f"- 候选池上限: 日线池(~{A.get('pool_size_med')} 只)平均只装下他 {pc_(A.get('pool_cover_all'), 0)} 的票。池外的票 {((A.get('pool_in_out') or {}).get('out') or {}).get('n')} 只: 昨成交额中位 {((A.get('pool_in_out') or {}).get('out') or {}).get('amt_e8')} 亿、股价中位 {((A.get('pool_in_out') or {}).get('out') or {}).get('px')}(池内的 {((A.get('pool_in_out') or {}).get('in') or {}).get('amt_e8')} 亿 / {((A.get('pool_in_out') or {}).get('in') or {}).get('px')}) —— 选股相当一部分落在「日线强势+高成交额」口径之外。",
                       "- 池内: 加了竞价/开盘特征的条件 logit 在训练窗能把 Top30 抬到 ~20%, 时间外掉回随机附近 → 训练窗里的提升是过拟合, 不是稳定规则。",
                       "- 池内 vs 全市场的反差: 在已经是「日线强势+高成交额」的池子里, 大家开盘都偏强, 他的票只到池内 0.6~0.7 分位; 放到全市场, 他的票开盘以来最高涨幅/量比在 0.85~0.9 分位 —— 开盘强度更像他的**入门条件**(粗筛), 不是**挑哪只**的决定因素; 且这份强度和昨日日线强势高度重叠(全市场叠加后不增反降)。",
                       f"- 消融(09:35 档): 只日线 Top30 {pc_(g((ab.get('只日线') or {}).get('cover'), 30))}, 加全部开盘特征 {pc_(g((ab.get('日线+全部开盘特征') or {}).get('cover'), 30))}; 去掉任一组(竞价/价格路径/量能/同伴)变化都在 1~2 只票以内 —— 没有哪一组是「关键」。",
                       "- 他的首买时刻在逐月后移(3 月后中位 ~09:55), 验证窗大多数日子能用到 09:50~09:55 的信息, 但越晚的档模型越差 → 不是「等开盘信息越多越准」的选股器形态。"]
    A["doubts"] = [
        "候选池用第一轮冻结日线模型 + 成交额构造, 07-21 前的日子池子构成是样本内; 池外的票只做描述, 覆盖率分母把它们算作未命中(口径保守)。",
        f"时间外验证只有 {A.get('n_test')} 个买入日、~{(A.get('dynamic_test') or {}).get('pos')} 只票, Top10/Top30 的 1 只票 ≈ 1.4 个百分点; bootstrap 区间宽, 「无提升」的结论只能排除大的提升(≥ +6~10 个百分点), 排除不了小的。",
        "条件 logit 把同日多只正样本当独立选择近似; 特征一律转成池内百分位(丢了绝对水平, 例如「竞价涨 3%」和「竞价涨 0.5%」在弱市/强市里百分位可能一样)。",
        "逐笔时间只到分钟, 决策点 cp 用「时间 < cp」的逐笔, 同一分钟内先后不可分; 他的首腿秒级时刻在 cp 当分钟内时, 档位判定可能差 1 分钟。",
        "全市场宽口径只有最近 ~20 个买入日、用分时(无逐笔方向/无 OHLC), 首分钟量含竞价量; 只做描述和无训练的单特征/组合排序, 样本 < 50 只。",
        "同伴(板块强度)用近 60 日收益相关最高 10 只代替行业/概念, 没有真实板块归属; 「板块开盘强度」这条假设没被充分检验。",
        "没有同花顺热度榜/问财/新闻公告数据, 概率分布里这几项是按「排除法 + 账户行为」推的主观似然比, 不是直接证据。",
        "涨停价沿用 mentor_fingerprint 的口径(TODO: 统一走 scripts/lib/a_rules.py, 尚未生成); 当日实时 --signal 的两个通达信实时接口 10/17 夜间实测都返回空, 交易时段可用性未验证。",
    ]
    return A


def write_report(A):
    L = []
    g = lambda d, N: (d or {}).get(N, (d or {}).get(str(N)))
    ms = A.get("models", {})
    dyn = A.get("dynamic_test") or {}
    v1f = A.get("v1_fullmarket_test") or {}
    fs = A.get("fetch") or {}
    L += ["# 逆向工程第二轮: 「量化短线小号实验」选股 = 竞价 + 开盘头几分钟?（2026-10-16）", "",
          f"> 生成: {A['generated']} | 脚本: `scripts/tzzb/reverse_lianghua_v2.py`(零 token; 通达信历史逐笔 + 行情库只读) | "
          f"评估窗: {A['window'][0]} ~ {A['window'][1]}({A['rows']} 个买入日; 前 70% {A['train'][0]}~{A['train'][1]} 定参, 后 30% {A['test'][0]}~{A['test'][1]} 验证)",
          f"> 数据完成度: 他共 {fs.get('buy_days')} 个新开仓买入日({fs.get('first')}~{fs.get('last')}), 逐笔已取齐 {fs.get('days_done')} 日"
          f"{'(未取完的在后台续跑, 重跑 --analyze 即更新本报告)' if fs.get('days_done', 0) < fs.get('buy_days', 0) else '(全部完成)'}。", ""]
    L += ["## 结论速览", "",
          "| 问题 | 结论 |", "| --- | --- |"]
    pk = "/".join(PRIMARY)
    best_cp = max((k for k, x in ms.items() if x["cp"] != "pre" and f"{x['kind']}/{x['mode']}" == pk), key=lambda k: g(ms[k]["test"]["cover"], 30) or 0, default=None)
    L.append(f"| 覆盖率(时间外, 他的票落在排序 Top2/5/10/30) | 第二轮「买入前最新一档」动态模型: **{pc_(g(dyn['cover'], 2))} / {pc_(g(dyn['cover'], 5))} / {pc_(g(dyn['cover'], 10))} / {pc_(g(dyn['cover'], 30))}**; "
             f"同一批验证日第一轮(全市场日线模型): {pc_(g(v1f['cover'], 2))} / {pc_(g(v1f['cover'], 5))} / {pc_(g(v1f['cover'], 10))} / {pc_(g(v1f['cover'], 30))} |")
    L.append(f"| 上限约束 | 候选池(日线, 事前)只装下他 {pc_(A.get('pool_cover_all'), 0)} 的票(验证窗 {pc_(A.get('pool_cover_test'), 0)}) → 不论池内怎么排, 覆盖率封顶于此 |")
    L.append(f"| 关键特征 | {A.get('key_feature_text', '见第三节')} |")
    rp = A.get("residual") or residual_probs(A)
    L.append("| 剩余解释不了的部分 | " + "; ".join(f"{h} {p}%" for h, p in zip(rp["hyp"], rp["post"])) + " |")
    L.append(f"| 能否接进 paper 链 | {A.get('paper_verdict', '见第五节')} |")
    L += ["", "## 一、补了什么数据", ""]
    L.append(f"- 候选池(每个买入日 D, 只用 D 前一日收盘信息): 主板/创业板/科创板、非 ST、D 日未停牌, 按第一轮冻结的日线逻辑回归(参数训练截至 2026-07-21)取前 {POOL_LR_N} ∪ 昨成交额前 {POOL_AMT_N}, 日均 {A.get('pool_size_med')} 只。"
             "他实际买的票若不在池内也取了逐笔(只做第三节描述, 不进排序评估、不当正样本)。")
    L.append("- 每只票取当日最早 ~1000 笔通达信历史逐笔(含 09:25 竞价撮合那一笔), 只存 10:00 前, 缓存 `scripts/tzzb/reverse_lianghua/open_ticks/<日>.jsonl`; 每请求间隔 0.15~0.30s, 两个进程各连一台服务器。"
             f"池内取到率 {pc_(A.get('tick_ok_rate'))}。")
    ac = A.get("auction_check") or {}
    if ac:
        L.append("- 竞价校验(行情库 call_auction 近几日关注集快照, 只读): " + "; ".join(
            f"{d}: {v['n']} 只, 价完全一致 {pc_(v['price_exact_share'], 0)}, 量差<1% {pc_(v['vol_within_1pct_share'], 0)}" for d, v in ac.items()) + " → 逐笔 09:25 那一笔就是竞价撮合结果, 口径可靠。")
    L.append(f"- 特征(决策时点 cp 之前的逐笔, cp ∈ {'/'.join(CHECKPOINTS)}): " + "、".join(f"{OPEN_CN[k]}" for k in OPEN_FEATS) +
             "; 日线特征沿用第一轮(昨日收盘状态 + 回头票)。全部转成「当日池内百分位」再进模型(消掉大盘当天整体涨跌)。")
    L.append(f"- 防后见: 某个决策时点只在「他当天首笔新开仓买入 ≥ 该时点」的日子上训练/验证(他买之前看得到)。各时点可用日占比: "
             + ", ".join(f"{k} {pc_(v, 0)}" for k, v in (A.get("first_buy_dist") or {}).items()) + "。")
    L += ["", "## 二、覆盖率(时间外验证窗; 分母=他当日新开仓的主板/创业/科创票, 池外的记未命中)", "",
          "| 排序 | Top2 | Top5 | Top10 | Top30 | Top50 | 池内百分位中位(0=第一) | 样本 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    L.append(cov_row("第一轮: 全市场日线 LR(同一批验证日)", {"cover": v1f.get("cover", {}), "days": A.get("n_test"), "pos": v1f.get("pos")}))
    L.append(cov_row("池内随机", A.get("random_in_pool_test")))
    L.append(cov_row("池内按第一轮日线分", A.get("v1_in_pool_test")))
    L.append(cov_row("池内按竞价额排", A.get("rule_auc_amt_test")))
    for cp in ["pre"] + CHECKPOINTS:
        k = f"{pk}@{cp}"
        if k in ms:
            r = ms[k]
            L.append(cov_row(f"第二轮主模型 {('盘前(只日线)' if cp == 'pre' else '日线+开盘 @' + cp)}", r["test"]))
            if cp != "pre":
                L.append(cov_row(f"  ↳ 消融: 同一批日子只用日线", r["test_daily_only_same_days"]))
    L.append(cov_row("**第二轮主模型 动态(每天用他买入前最新一档)**", dyn, extra=f"; 档位分布 {A.get('dynamic_cp_dist_test')}"))
    L.append(cov_row("(主模型 训练窗内, 动态)", A.get("dynamic_train")))
    for k, x in (A.get("dynamic_specs") or {}).items():
        if k != pk:
            L.append(cov_row(f"对照模型 {k} 动态", x["test"]))
            L.append(cov_row(f"  ↳ 对照模型 {k} 盘前(只日线)", x["test_pre"]))
    L += ["", "读法: 「↳ 消融」行是同一批日子、同样训练方式但拿掉全部开盘特征 —— 两行之差才是竞价/开盘信息的真实贡献; 和第一轮比还混着「换成池内排序」的效应。"
          f" 主模型={A.get('dynamic_kind')}(事先指定: 条件 logit, 日线部分只用第一轮冻结模型分 → 自由度低; 另三种为对照, 不按验证窗挑)。",
          f"- 按日 bootstrap 90% 区间(验证窗): 动态 − 池内第一轮日线分: Top10 {A.get('boot_dyn_minus_v1pool', {}).get('top10')}, Top30 {A.get('boot_dyn_minus_v1pool', {}).get('top30')}; "
          f"动态 − 池内随机(50 次均值 Top10 {pc_((A.get('random_in_pool_test_mean50') or {}).get('top10'))} / Top30 {pc_((A.get('random_in_pool_test_mean50') or {}).get('top30'))}): "
          f"Top10 {A.get('boot_dyn_minus_random', {}).get('top10')}, Top30 {A.get('boot_dyn_minus_random', {}).get('top30')}(区间跨 0 = 与对照无显著差)。", ""]
    L += ["## 三、关键特征", "", "### 3.1 他的票在买入前那一刻, 开盘特征处在当日池内什么位置(全样本描述, 0.5=无偏好)", "",
          "| 特征 | 样本 | 池内百分位中位 | 处在池内前 30% 的占比 | 后 30% 占比 | 他的中位 | 池中位 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    prof = A.get("profile") or {}
    for nm, x in sorted(prof.items(), key=lambda kv: -abs(kv[1]["pct_med"] - 0.5)):
        L.append(f"| {x['cn']} | {x['n']} | {x['pct_med']:.2f} | {pc_(x['share_top30pct'], 0)} | {pc_(x['share_bottom30pct'], 0)} | {x['his_med']} | {x['pool_med']} |")
    L += ["", "(随机挑票时「前 30% 占比」≈30%; 用的是他每只票自己的首腿时刻之前的逐笔, 池外票也算在内。)", "",
          "### 3.2 单特征排序(训练窗定方向, 验证窗覆盖)", "", "| 时点 | 特征 | 方向 | 训练 Top30 | 验证 Top5 | 验证 Top10 | 验证 Top30 | 验证池内百分位中位 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for x in sorted(A.get("single", []), key=lambda z: -(g(z["test"], 30) or 0))[:16]:
        L.append(f"| {x['cp']} | {x['cn']} | {x['dir']} | {pc_(x['train30'])} | {pc_(g(x['test'], 5))} | {pc_(g(x['test'], 10))} | {pc_(g(x['test'], 30))} | {x['test_pct_rank_med']} |")
    L += ["", "### 3.3 消融(09:35 档, 验证窗)", "", "| 特征集 | Top2 | Top5 | Top10 | Top30 | Top50 | 池内百分位中位 | 样本 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for k, r in (A.get("ablation_0935") or {}).items():
        if not k.startswith("_"):
            L.append(cov_row(k, r))
    if best_cp:
        L += ["", f"### 3.4 权重最大的项({best_cp} 档模型, 标准化后; o:=开盘特征, ^2=偏离中位的平方 → 负=偏好中间)", ""]
        L.append("; ".join(f"`{n}` {w:+.2f}" for n, w in ms[best_cp]["top_w"]))
    Wd = A.get("wide") or {}
    if Wd.get("days"):
        L += ["", f"### 3.5 全市场宽口径诊断(最近 {len(Wd['days'])} 个买入日 {Wd['days'][0]}~{Wd['days'][-1]}, 主板/创业/科创非 ST 且昨成交额≥0.3 亿, 日均 {Wd['universe_med']} 只; 他的票 {Wd['n_pos']} 只)", "",
              "数据=通达信历史分时(1 分钟价/量, 首点含竞价量; 竞价价=日线开盘价), 每只票用自己首腿时刻之前的分时(最晚截到 10:30)。这里没有池子截断: 看他的票在**全市场**里处在什么位置。"
              f" 组合分权重(事前: 池内训练窗画像的百分位中位-0.5, |偏离|≥0.05 才入): {Wd.get('weights')}; 第一轮日线分权重 {Wd.get('w_v1')}(训练窗末 40 个买入日全市场画像)。", "",
              "| 特征 | 样本 | 全市场百分位中位 | 前 10% 占比 | 前 30% 占比 | 后 30% 占比 |", "| --- | --- | --- | --- | --- | --- |"]
        for nm, x in sorted(Wd["profile"].items(), key=lambda kv: -abs(kv[1]["pct_med"] - 0.5)):
            L.append(f"| {x['cn']} | {x['n']} | {x['pct_med']:.2f} | {pc_(x['top10pct'], 0)} | {pc_(x['top30pct'], 0)} | {pc_(x['bottom30pct'], 0)} |")
        L += ["", "全市场单特征排序(无训练, 两个方向都列; 他的票落在 TopN 的比例; 随机期望 Top30≈" + (f"{30 / max(Wd['universe_med'], 1):.1%}" if Wd.get('universe_med') else "—") + "):", "",
              "| 排序 | Top10 | Top30 | Top50 | Top100 | Top300 |", "| --- | --- | --- | --- | --- | --- |"]
        sing = sorted(Wd["single"].items(), key=lambda kv: -((kv[1] or {}).get(300) or (kv[1] or {}).get("300") or 0))[:12]
        for k, x in sing:
            L.append(f"| {k} | " + " | ".join(pc_(x.get(N, x.get(str(N)))) for N in (10, 30, 50, 100, 300)) + " |")
    L += ["", "## 四、剩余解释不了的部分(概率分布, 合计 100%)", "", "| 假设 | 概率 |", "| --- | --- |"]
    for h, p in zip(rp["hyp"], rp["post"]):
        L.append(f"| {h} | {p}% |")
    L += ["", "算法同第一轮: 等先验 × 证据的主观似然比(下表, `residual_probs()` 里可改), 归一。只表达相对倾向。", "", "| 证据 | 似然比(题材新闻/外部榜单/实时选股器/主观/其他) |", "| --- | --- |"]
    for e, lr in rp["evidence"]:
        L.append(f"| {e} | {' / '.join(str(x) for x in lr)} |")
    L += A.get("discussion", [])
    L += ["", "## 五、接进 `--signal`", "",
          "```", "scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/reverse_lianghua_v2.py --signal --date 2026-10-19            # 盘前: 只给日线排序(pre)",
          "scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/reverse_lianghua_v2.py --signal --date 2026-10-19            # 当日 09:25 后再跑: +竞价(行情库 call_auction 只读 + 通达信快照)",
          "scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/reverse_lianghua_v2.py --signal --date 2026-10-19            # 09:31/09:33/09:35/09:40 后再跑: +开盘 N 分钟(通达信快照)",
          "scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/reverse_lianghua_v2.py --signal --date 2026-10-15 --asof 09:35  # 历史日: 用通达信历史逐笔, 只用 09:35 之前",
          "```",
          "- 输出 `scripts/tzzb/model_out/lianghua_v2_signal_<D>.json`: `candidates`=当前可用最新一档的前 30 名; `stages` 里每一档都列(pre / 09:25 / 09:3x), `stage_note` 写明「盘前只能给到竞价为止的排序, 09:3x 再更新」。",
          "- 当日实时: 首选通达信当日逐笔(get_transaction_data, 与回测同口径), 拿不到退到快照(get_security_quotes; 主动买占比/近3分钟涨速/逐笔笔数缺失按中性); 两个都拿不到只输出盘前档。10/17 凌晨实测两个实时接口都返回空(非交易时段), 交易时段可用性未验证。",
          "- `recommend` 字段写明: 时间外验证里开盘档没有胜过盘前日线档, 前 30 名优先参考 stages.pre, 开盘档只做「剔除开盘后走弱」。",
          f"- 建议: {A.get('paper_verdict', '')}"]
    L += ["", "## 不自信点", ""] + [f"{k + 1}. {x}" for k, x in enumerate(A.get("doubts", []))]
    L += ["", "## 复现", "", "```",
          "scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/reverse_lianghua_v2.py --fetch [--days 60] [--worker 0 --nworkers 2]   # 补逐笔(断点续跑, 由近及远)",
          "scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/reverse_lianghua_v2.py --analyze                                        # 本报告 + v2_analysis.json + v2_params.json",
          "scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/reverse_lianghua_v2.py --validate-auction",
          "scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/reverse_lianghua_v2.py --selftest", "```"]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    log(f"[报告] {REPORT}")
    return REPORT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--days", type=int)
    ap.add_argument("--since")
    ap.add_argument("--max-stocks", type=int)
    ap.add_argument("--worker", type=int, default=0)
    ap.add_argument("--nworkers", type=int, default=1)
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--fetch-wide", action="store_true", help="全市场宽口径分时(诊断), 最近 --days 个买入日(默认 20)")
    ap.add_argument("--host", type=int, default=8)
    ap.add_argument("--signal", action="store_true")
    ap.add_argument("--date")
    ap.add_argument("--asof", help="HH:MM, 只用该时刻之前的数据(历史日默认 09:45; 当日默认=现在)")
    ap.add_argument("--validate-auction", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.fetch:
        cmd_fetch(a.days, a.max_stocks, a.since, a.worker, a.nworkers)
    elif a.fetch_wide:
        cmd_fetch_wide(a.days or 20, a.worker, a.nworkers, a.host)
    elif a.analyze:
        cmd_analyze()
    elif a.signal:
        if not a.date:
            ap.error("--signal 需要 --date D")
        cmd_signal(a.date, a.asof)
    elif a.validate_auction:
        print(json.dumps(cmd_validate_auction(), ensure_ascii=False, indent=1))
    elif a.selftest:
        selftest()
    else:
        ap.print_help()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
