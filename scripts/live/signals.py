# -*- coding: utf-8 -*-
"""signals.py — 实盘线 模块 8: 分时信号检测器(10/24 建; 零 token, 只读本地文件, 不发任何行情请求)

做什么: 读当天 3 秒盘口录像 downloads/market/<D>/book_snap.jsonl(.gz), 每只票增量维护状态, 命中 harness.yaml signals 段的 S1~S7 就出一个事件
       {t, code, name, sig, sig_name, px, detail, hold}; 实盘模式把事件追加写 results/_live/<D>/signals.jsonl, 按节流规则合并推微信。
用法:
  python signals.py --replay D [--until HH:MM] [--codes a,b] [--all] [--samples 5]   离线回放, 打印命中统计 + 样例, 不推送
  python signals.py --run D [--codes a,b] [--all] [--dry]                           实盘: 每 3 秒读新增行, 直到 15:00; --dry = 推送只打印
  python signals.py --run D --push-test                                              用假事件走一遍推送排版(强制 dry)
要盯的票: --codes 优先; 否则 = results/_live/<D>/v3_*/must_state.json 的 watch 键 + 各本 state.json 持仓 + 用户实盘持仓(snapshots 最近一份成交导出);
         --all = 录像里所有票都算(回放统计噪声用)。持仓票(v3 持仓 + 实盘持仓)推送时排前面。

────────────────── 机械口径(定义来自 harness.yaml signals; 标 [补定] 的是定义没写清、这里自定的, 参数都在下面 P 里, 改数即可) ──────────────────
时间: 连续竞价用"交易秒"(09:30=0, 11:30=7200, 13:00 接着 7200 往后), 午休不算时长; 11:30~13:00 之间的快照忽略; 14:57 以后(收盘集合竞价)不再出连续竞价信号
均价线: 累计成交额 / 累计成交量(含开盘集合竞价那一笔); 单位按首笔自动校准 —— a/v 和现价差 10 的整数次方时自动换算(实测 10/23 股票 / 转债 / ETF 都是 1:1)
开盘价: 09:25:00~09:29:59 那笔快照的现价(开盘集合竞价结果); 没有 → 竞价段最后一笔撮合价 b[0][0] → 09:30 后第一笔现价

S1 急跌后拉起
  σ [补定] = 本票 D 之前 20 个交易日 1 分钟收盘路径(downloads/quotes/{stock,cb}/minute_path)里, 每天不重叠的 5 分钟收益率(p[i+5]/p[i]-1, i=0,5,…)的标准差;
            分钟路径里没有这只票(ETF 等) → 日线 20 日 Parkinson 估计: σ日 = sqrt(mean(ln(H/L)^2)/(4ln2)), σ5 = σ日/sqrt(48); 都没有 → 0.5%
  急跌 = 现价比"过去 5 分钟(300 交易秒)内最高价"低 ≥ max(K·σ, MIN_TICKS 个最小价位) [补定: 价位地板, 防中行这种低波票 2 个价位就报]
  [补定] 09:31 前不认(开盘第一分钟价格乱跳, 10/23 回放里 3 只票 09:30 全触发); 5 分钟窗口也只用 09:31 以后的价格(09:30 那一分钟的高点不当"急跌前高点")
  拉起 = 急跌后的最低点出现后 60 秒内, 价格收回 ≥ 一半跌幅(L + 0.5·(H−L)) 且 > 均价线 → 触发; 最低点后 60 秒没拉起就作废, 再创新低重新计
S2 回踩均价线不破
  [补定] 先"上方待命": 价格 ≥ 均价 × (1 + ARM) 才算在均价线上方(ARM=0.6%, 即带宽的 2 倍); 然后回到均价 ±0.3% 带内 = 回踩开始(记 t0)
  t0 起任何一笔 < 均价 × (1 − 0.3%) = 破了, 作废并重新等"上方待命"; t0 满 3 分钟(180 交易秒)后第一次 > 均价 × (1 + 0.3%) = 回升 → 触发
  09:35 前不认(均价线刚形成); 均价线随时间变, 每笔都按当时的均价算
S3 二次冲高
  [补定] 第一波: 开盘后到 WAVE1_END(10:30)之间的盘中最高价 H1 不断刷新, 直到"回落确认" = 价格 ≤ H1 × (1 − PULLBACK 2%) 且 H1 ≥ 开盘价 × (1 + RISE 2%)(先冲高再回落)
         第一波量 = H1 那一刻之前 5 分钟的成交量(累计量差; 不足 5 分钟从开盘算, 不含开盘竞价量)
  回落确认后, 距 H1 至少 GAP(10 分钟) [补定: 不加时 10/23 有 3 只票在 H1 后 30 秒~1 分钟内就"二次冲高", 是同一波的抖动], 价格 ≥ H1 × (1 − 1%) 且 最近 5 分钟成交量 ≥ 第一波量 × 70% → 触发; 每天每票只认一次二次冲高
S4 炸板回封(N=10, 读 yaml)
  涨停价 = a_rules.limit_prices(代码, D, 昨收); 封板 = 买一价 ≥ 涨停价(半个价位容差); 开板 = 封过之后买一价 < 涨停价
  开板后 N 分钟内(交易秒)重新封住 → 触发(detail 带开板时长和开板期间最低价); 超过 N 分钟才回封不报
S5 尾盘拉升
  14:25:00~14:45:00 之间的滚动最低点 L(实时只能用"到此刻为止"的最低点), 最低点之后 10 分钟内价格 ≥ L × (1 + 1.5%) → 触发; 每天一次
S6 竞价抢筹
  09:20 基准 = 09:20:00 之后第一笔撮合价(录像里这只票 09:20:30 后才出现 → 用 auction_path.series 从新浪全市场竞价快照补)
  09:20 之后任一笔: 撮合价 ≥ 基准 × (1 + 3%) 且 未匹配买(b[1][1]) > 未匹配卖(k[1][1]) → 触发; 每天一次
S7 开盘冲高到位(x=6, 读 yaml)
  开盘后 30 分钟内(09:30~10:00), 现价 ≥ 开盘价 × (1 + x%) → 触发; 每天一次

────────────────── 推送节流(微信 iLink: 用户每发一条消息后只能主动推约 10 条) ──────────────────
  ① 同一只票同一信号 30 分钟(按事件时间)内只记一次(只记一次 = 只写 signals.jsonl 一次, 也只进推送一次)
  ② 推送合并成一条, 两次推送至少间隔 15 分钟; 第一条事件来了且距上次推送已满 15 分钟就立刻推
  ③ 持仓票排前面; 一条最多 MAX_LINES 行, 多的写"另 N 条见 signals.jsonl"
  ④ 配额: 推之前看 wx_send.quota(), 用户上条消息后已推 ≥ 8 条时只推含持仓票的批次, 其余留到下一轮(并在末尾提示回个字)
  ⑤ 重启续跑: 已在 signals.jsonl 里的事件不重复记 / 推; 追赶旧录像时产生的事件(比当前时刻早 5 分钟以上)只记不推
  走 scripts/hermes/wx_send.py 的 send(text, src="live_signal", raw=True) —— src 以 v3_ 开头免置信度闸; 推送在后台线程里, 不阻塞检测
"""
import argparse
import collections
import datetime as dt
import glob
import gzip
import json
import math
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"
QUOTES = ROOT / "downloads" / "quotes"
LIVE = ROOT / "results" / "_live"
YAML = ROOT / "scripts" / "live" / "harness.yaml"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # 本脚本不起子进程; 留给挂接方(计划任务 / 总控)起本脚本时用
for _p in ("lib", "paper_line/tools", "hermes", "backfill_bilibili", "dfcf/paper"):
    sys.path.insert(0, str(ROOT / "scripts" / _p))

# ⚙️ 可调参数(补定口径); harness.yaml signals 段里有 params 的(S4.N / S7.x)以 yaml 为准, 启动时覆盖
P = {
    "S1_K": 3.0, "S1_WIN": 300, "S1_BACK": 60, "S1_RECOVER": 0.5, "S1_MIN_TICKS": 3, "S1_START": "09:31:00", "SIGMA_DAYS": 20, "SIGMA_DEFAULT": 0.005,
    "S2_BAND": 0.003, "S2_ARM": 0.006, "S2_HOLD": 180, "S2_START": "09:35:00",
    "S3_RISE": 0.02, "S3_PULLBACK": 0.02, "S3_NEAR": 0.01, "S3_VOL": 0.7, "S3_WAVE1_END": "10:30:00", "S3_GAP": 600,
    "S4_N": 10,   # 10/25 起 S4 拆成 S4a 炸板 / S4b 回封动作(参数动态, 见 scripts/live/signal_params.py), S4_N 只留作 S4b 的"开板太久不再等"上限(分钟)
    "S2_ARM_HOLD": 120,   # 10/25 agent 建议 + 用户批: 待命要在均价线上方(ARM = 2 × 本票带宽)持续这么多交易秒才算
    "S6_MIN_AMT_K": 0.5,  # 10/25: 竞价未匹配买入金额 ≥ 本票平时 1 分钟成交额 × 这个系数(防小票几手单子推高)
    "S5_FROM": "14:25:00", "S5_TO": "14:45:00", "S5_WIN": 600, "S5_UP": 0.015,
    "S6_UP": 0.03, "S6_BASE_LATE": "09:20:30",
    "S7_X": 6.0, "S7_WIN": 1800,
    "DEDUP_MIN": 30, "PUSH_GAP_MIN": 30, "MAX_LINES": 12, "STALE_MIN": 5, "QUOTA_SOFT": 8,   # 10/24 主会话: K 2→3、推送间隔 15→30 分钟(agent 回放: 一天约 7~9 条, 微信额度约 10 条)
}
NAMES = {"S1": "急跌后拉起", "S2": "回踩均价线不破", "S3": "二次冲高", "S4a": "炸板", "S4b": "回封动作", "S5": "尾盘拉升", "S6": "竞价抢筹", "S7": "开盘冲高到位"}
DYN = {}   # 10/25 动态参数(signal_params.build; "_global" + 每只票), 启动时 load_dyn(D) 填


def load_yaml():
    """读 harness.yaml 的 signals 段(只读): 名字 + params(N / x)"""
    try:
        import yaml
        sg = (yaml.safe_load(YAML.read_text(encoding="utf-8")) or {}).get("signals") or {}
    except Exception:   # noqa: BLE001
        return
    for k, v in sg.items():
        if isinstance(v, dict):
            if v.get("name"):
                NAMES[k] = str(v["name"]).strip()
            pr = v.get("params") or {}
            if k in ("S4", "S4b") and "N" in pr:
                P["S4_N"] = float(pr["N"])
            if k == "S7" and "x" in pr:
                P["S7_X"] = float(pr["x"])


def load_dyn(D):
    """10/25 用户批: 参数按每只票自己的历史分布(σ5 / 开盘 30 分钟冲高分位 / 竞价变动分位 / 开板时长分位); 算不出来照旧用 P 里的固定值"""
    try:
        import signal_params as SPM
        DYN.clear()
        DYN.update(SPM.build(D))
        g = DYN.get("_global") or {}
        print(f"[signals] 动态参数: σ5 中位 {g.get('σ5中位')} · S4a 开板 ≥{g.get('S4a_N秒')} 秒 · S4b 卖一量降 ≥{g.get('S4b_DROP')} · 个股参数 {len(DYN) - 1} 只", file=sys.stderr, flush=True)
    except Exception as e:   # noqa: BLE001
        print(f"[signals] 动态参数算不出来, 用固定值: {e!r}", file=sys.stderr, flush=True)


def prm(S, name):
    """这只票的参数: 动态(个股 → 全体池) → 固定 P"""
    d = S.m.get("dp") or {}
    if name in d:
        return d[name]
    g = DYN.get("_global") or {}
    if name == "S7_X" and g.get("S7_X_pool"):
        return g["S7_X_pool"]
    if name == "S6_UP" and g.get("S6_UP_pool"):
        return g["S6_UP_pool"] / 100
    return P[name]


# ================================================================ 时间
def secs(t):
    h, m, s = (int(x) for x in t.split(":"))
    return h * 3600 + m * 60 + s


def trs(t):
    """交易秒: 09:30=0; 午休压掉; 竞价段为负数"""
    s = secs(t)
    if s <= 41400:
        return s - 34200
    if s < 46800:
        return 7200
    return 7200 + s - 46800


def lunch(t):
    return "11:30:05" < t < "13:00:00"


# ================================================================ 静态资料(名字 / 昨收 / 涨停 / σ)
class Meta:
    def __init__(self, D):
        self.D = D
        self._names, self._sig, self._cache = None, None, {}

    def names(self, codes=None):
        if self._names is None:
            self._names = {}
            try:
                import manual_backfill as mb
                cur = mb.db().cursor()
                cur.execute("select code, name, sec_type from investment_market.security_master where is_deleted=0 and sec_type in ('STOCK','CB','ETF')")
                for c, n, _ in cur.fetchall():
                    self._names.setdefault(str(c), str(n))
            except Exception as e:   # noqa: BLE001  库连不上 → 本地当天证券表
                print(f"[signals] 查 security_master 失败({e}), 改读本地 security_master.jsonl", file=sys.stderr)
                for f in sorted(MKT.glob("*/security_master.jsonl"))[-1:]:
                    for l in f.open(encoding="utf-8"):
                        try:
                            r = json.loads(l)
                            self._names.setdefault(str(r["code"]), r["name"])
                        except (ValueError, KeyError):
                            continue
        return self._names

    def name(self, c):
        return self.names().get(c, c)

    def sigmas(self):
        """一次扫完 D 前 20 个交易日的分钟路径, 算全部票的 5 分钟收益率 σ(只存 n / Σr / Σr², 不占内存)"""
        if self._sig is None:
            acc = collections.defaultdict(lambda: [0, 0.0, 0.0])
            for kind in ("stock", "cb"):
                fs = [f for f in sorted(glob.glob(str(QUOTES / kind / "minute_path" / "*.jsonl"))) if Path(f).stem < self.D][-int(P["SIGMA_DAYS"]):]
                for f in fs:
                    with open(f, encoding="utf-8") as fh:
                        for l in fh:
                            try:
                                r = json.loads(l)
                            except ValueError:
                                continue
                            p, a = r.get("p") or [], acc[str(r.get("code"))]
                            for i in range(0, len(p) - 5, 5):
                                if p[i] and p[i + 5] and p[i] > 0:
                                    x = p[i + 5] / p[i] - 1
                                    a[0] += 1
                                    a[1] += x
                                    a[2] += x * x
            self._sig = {}
            for c, (n, s1, s2) in acc.items():
                if n >= 100:
                    var = max(0.0, s2 / n - (s1 / n) ** 2)
                    self._sig[c] = (math.sqrt(var), "分钟")
        return self._sig

    def sigma(self, c):
        v = self.sigmas().get(c)
        if v and v[0] > 0:
            return v
        try:   # 日线 Parkinson 兜底
            k = json.loads((QUOTES / "daily" / f"{c}.json").read_text(encoding="utf-8")).get("klines") or []
            k = [x for x in k if x.get("d", "") < self.D and x.get("h") and x.get("l")][-int(P["SIGMA_DAYS"]):]
            if len(k) >= 5:
                pk = math.sqrt(statistics.fmean(math.log(x["h"] / x["l"]) ** 2 for x in k) / (4 * math.log(2)))
                return pk / math.sqrt(48), "日线"
        except (OSError, ValueError, ZeroDivisionError):
            pass
        return P["SIGMA_DEFAULT"], "默认"

    def get(self, c):
        if c not in self._cache:
            import a_rules as AR
            import auction_path as AP
            prev = AP.prev_close(c, self.D)
            try:
                up, dn = AR.limit_prices(c, self.D, prev) if prev else (None, None)
            except Exception:   # noqa: BLE001
                up, dn = None, None
            try:
                tk = AR.tick(c)
            except Exception:   # noqa: BLE001
                tk = 0.01
            sg, src = self.sigma(c)
            dp = dict(DYN.get(c) or {})
            if "S6_UP" in dp:
                dp["S6_UP"] = dp["S6_UP"] / 100   # signal_params 存的是 %
            amt1 = None
            try:   # 平时 1 分钟成交额(近 20 日日均成交额 / 240)
                k_ = json.loads((QUOTES / "daily" / f"{c}.json").read_text(encoding="utf-8")).get("klines") or []
                k_ = [x for x in k_ if x.get("d", "") < self.D and x.get("a")][-20:]
                if k_:
                    amt1 = statistics.fmean(float(x["a"]) for x in k_) / 240
            except (OSError, ValueError):
                pass
            self._cache[c] = {"prev": prev, "up": up, "dn": dn, "tick": tk, "sigma": sg, "sigma_src": src, "name": self.name(c), "dp": dp, "amt1": amt1}
        return self._cache[c]


# ================================================================ 检测器
class St:
    """一只票的增量状态"""
    def __init__(self, m):
        self.m = m
        self.open_px = None     # 09:25 快照的现价 = 开盘价
        self.v_auc = None       # 09:25 快照的累计量 = 开盘竞价成交量
        self.auc_px = None      # 最后一笔竞价撮合价(没有 09:25 快照时当开盘价)
        self.p20 = None         # 09:20 基准
        self.p20_tried = False
        self.open = None
        self.scale = None       # 均价单位换算
        self.win = collections.deque()    # (交易秒, 价, 累计量) 最近 300 秒
        self.v0 = None          # 09:30 后第一笔累计量(5 分钟量起点)
        self.done = set()       # 每天一次的信号
        self.s1 = None          # {H, L, tL}
        self.s2 = {"armed": False, "t0": None}
        self.s3 = {"H1": None, "tH": None, "vol1": None, "ok": False}
        self.s4 = {"sealed": False, "t_open": None, "low": None, "s_open": None, "a_fired": False, "b_fired": False, "mx": 0.0}
        self.s5 = {"L": None, "tL": None}


class Detector:
    def __init__(self, D, meta=None, emit=None):
        self.D = D
        self.meta = meta or Meta(D)
        self.st = {}
        self.emit_filter = emit   # callable(code) -> bool; None = 全部

    def _state(self, c):
        if c not in self.st:
            self.st[c] = St(self.meta.get(c))
        return self.st[c]

    def feed(self, r):
        """喂一行快照 → [事件]"""
        s = str(r.get("s", ""))
        c, t = s[2:], r.get("t") or ""
        if not re.fullmatch(r"\d{6}", c) or not t or r.get("idx"):
            return []
        S = self._state(c)   # 名单外的票也维护状态(盘中名单会变, 新进名单的票不至于从半路算起), 只在出事件时按名单过滤
        out = []
        p = float(r.get("p") or 0)
        b, k = r.get("b") or [], r.get("k") or []
        if t < "09:30:00" or p <= 0:
            if p > 0 and t >= "09:25:00":   # 09:25 开盘集合竞价结果: 现价 = 开盘价, 累计量 = 竞价成交量(这时 b/k 已是普通五档, 不是撮合价)
                S.open_px, S.v_auc = p, int(r.get("v") or 0)
            elif p <= 0 and "09:15:00" <= t <= "09:25:59" and b and b[0][0]:
                self._auction(S, c, t, r, out)
            return out
        if lunch(t) or t >= "14:57:00":
            return out
        x = trs(t)
        v, a = int(r.get("v") or 0), float(r.get("a") or 0)
        if S.open is None:
            S.open = S.open_px or S.auc_px or p
        if S.v0 is None:
            S.v0 = S.v_auc if S.v_auc is not None else v
        if S.scale is None and v > 0 and a > 0:
            ratio = a / v / p
            S.scale = 10 ** round(math.log10(ratio)) if ratio > 0 else 1
        vw = a / v / S.scale if v > 0 and a > 0 and S.scale else None
        S.win.append((x, p, v))
        while S.win and S.win[0][0] < x - P["S1_WIN"]:
            S.win.popleft()
        ctx = (c, t, x, p, v, vw, b, k)
        self._s1(S, ctx, out)
        self._s2(S, ctx, out)
        self._s3(S, ctx, out)
        self._s4(S, ctx, out)   # 10/25: S4a 炸板 + S4b 回封动作
        self._s5(S, ctx, out)
        self._s7(S, ctx, out)
        return out

    def _ev(self, S, c, t, sig, px, detail, out):
        if self.emit_filter and not self.emit_filter(c):
            return
        out.append({"t": t, "code": c, "name": S.m["name"], "sig": sig, "sig_name": NAMES.get(sig, sig), "px": px, "detail": detail})

    # ---------- S6 竞价抢筹 + 开盘价 ----------
    def _auction(self, S, c, t, r, out):
        b, k = r["b"], r.get("k") or []
        px = float(b[0][0])
        S.auc_px = px
        if t < "09:20:00":
            return
        if S.p20 is None and not S.p20_tried:
            S.p20_tried = True
            if t <= P["S6_BASE_LATE"]:
                S.p20 = (t, px)
            else:   # 这只票 09:20 后很晚才进 3 秒名单 → 新浪全市场竞价快照补 09:20 基准
                try:
                    import auction_path as AP
                    ser = AP.series(self.D, P["S6_BASE_LATE"], [c]).get(c) or []
                    q = [z for z in ser if z[0] >= "09:20:00"]
                    if q:
                        S.p20 = (q[0][0], q[0][1])
                except Exception:   # noqa: BLE001
                    pass
        if S.p20 is None or "S6" in S.done:
            return
        ub = int(b[1][1]) if len(b) > 1 else 0
        us = int(k[1][1]) if len(k) > 1 else 0
        up6, amt1 = prm(S, "S6_UP"), S.m.get("amt1")
        min_amt = (amt1 or 0) * P["S6_MIN_AMT_K"]
        if px >= S.p20[1] * (1 + up6) and ub > us and ub * px >= min_amt:
            S.done.add("S6")
            pv = S.m["prev"]
            pc = f"(较昨收 {(px / pv - 1) * 100:+.2f}%)" if pv else ""
            self._ev(S, c, t, "S6", px, f"09:20 基准 {S.p20[1]:g}({S.p20[0]}) → {px:g}{pc} 抬高 {(px / S.p20[1] - 1) * 100:.2f}%(本票阈 {up6 * 100:.2f}%); 未匹配 买 {ub} > 卖 {us}, 买入金额 {ub * px / 1e4:.0f} 万(阈 {min_amt / 1e4:.0f} 万)", out)

    # ---------- S1 急跌后拉起 ----------
    def _s1(self, S, ctx, out):
        c, t, x, p, v, vw, b, k = ctx
        if t < P["S1_START"]:
            return
        thr = max(P["S1_K"] * S.m["sigma"], P["S1_MIN_TICKS"] * S.m["tick"] / p)
        x0 = trs(P["S1_START"])
        ps = [z[1] for z in S.win if z[0] >= x0]
        iH = max(range(len(ps)), key=ps.__getitem__)
        H = ps[iH]
        newlow = p <= min(ps[iH:])   # 此刻是窗口高点之后的最低价(只有"最低点"才能起算 60 秒)
        pd = S.s1
        if pd and x - pd["tL"] > P["S1_BACK"] and p > pd["L"]:
            pd = S.s1 = None   # 最低点后 60 秒没拉起, 作废
        if (H - p) / H >= thr and newlow and (pd is None or p < pd["L"]):
            S.s1 = {"H": H, "L": p, "tL": x, "tLs": t, "thr": thr}
            return
        if pd and p < pd["L"]:   # 再创新低但 5 分钟内跌幅不够(慢跌) → 低点跟着走
            pd.update(L=p, tL=x, tLs=t)
            return
        if pd and x - pd["tL"] <= P["S1_BACK"] and p >= pd["L"] + P["S1_RECOVER"] * (pd["H"] - pd["L"]) and vw and p > vw:
            self._ev(S, c, t, "S1", p, f"5 分钟内 {pd['H']:g} → {pd['L']:g}({pd['tLs']}) 跌 {(pd['H'] - pd['L']) / pd['H'] * 100:.2f}%(阈 {pd['thr'] * 100:.2f}%, σ5={S.m['sigma'] * 100:.2f}%[{S.m['sigma_src']}]),"
                                           f" {x - pd['tL']} 秒后收回到 {p:g} 站上均价 {vw:.3f}", out)
            S.s1 = None

    # ---------- S2 回踩均价线不破 ----------
    def _s2(self, S, ctx, out):
        c, t, x, p, v, vw, b, k = ctx
        if not vw or t < P["S2_START"]:
            return
        z, bd = S.s2, prm(S, "S2_BAND")
        arm = 2 * bd   # 10/25: 待命线 = 2 × 本票带宽, 且要在上方持续 S2_ARM_HOLD 秒
        d = p / vw - 1
        if z["t0"] is None:
            if d >= arm:
                z.setdefault("above", x)
                if x - z["above"] >= P["S2_ARM_HOLD"]:
                    z["armed"] = True
            else:
                z.pop("above", None)
            if d >= arm:
                return
            elif z["armed"] and abs(d) <= bd:
                z.update(t0=x, t0s=t, low=p)
            return
        z["low"] = min(z["low"], p)
        if d < -bd:   # 破了
            z.update(armed=False, t0=None)
            z.pop("above", None)
            return
        if x - z["t0"] >= P["S2_HOLD"] and d > bd:
            self._ev(S, c, t, "S2", p, f"{z['t0s']} 回到均价线 ±{bd * 100:.2f}%(本票带宽)内, {(x - z['t0']) // 60} 分钟没破(期间最低 {z['low']:g}), 回升到均价 {vw:.3f} 上方 {d * 100:.2f}%", out)
            z.update(armed=True, t0=None)

    # ---------- S3 二次冲高 ----------
    def _s3(self, S, ctx, out):
        c, t, x, p, v, vw, b, k = ctx
        z = S.s3
        if "S3" in S.done:
            return

        def vol5(at_x, at_v):
            base = S.v0
            for (xx, _, vv) in S.win:   # win 只留 300 秒: 取窗口里最早一笔(不足 5 分钟 = 从 09:30 起)
                if xx >= at_x - 300:
                    base = vv
                    break
            return at_v - base
        if not z["ok"]:
            if t <= P["S3_WAVE1_END"] and (z["H1"] is None or p > z["H1"]):
                z.update(H1=p, tH=x, tHs=t, vol1=vol5(x, v))
                return
            if z["H1"] and z["H1"] >= S.open * (1 + prm(S, "S3_RISE")) and p <= z["H1"] * (1 - prm(S, "S3_PULLBACK")):
                z.update(ok=True, low=p, okt=t)
            return
        z["low"] = min(z["low"], p)
        v5 = vol5(x, v)
        if x - z["tH"] >= P["S3_GAP"] and p >= z["H1"] * (1 - prm(S, "S3_NEAR")) and z["vol1"] and v5 >= P["S3_VOL"] * z["vol1"]:
            S.done.add("S3")
            self._ev(S, c, t, "S3", p, f"第一波 开 {S.open:g} → 高 {z['H1']:g}({z['tHs']}, +{(z['H1'] / S.open - 1) * 100:.2f}%), 回落到 {z['low']:g}; 再到 {p:g}(相对前高 {(p / z['H1'] - 1) * 100:+.2f}%),"
                                           f" 5 分钟量 {v5} = 第一波 {z['vol1']} 的 {v5 / z['vol1'] * 100:.0f}%", out)

    # ---------- S4a 炸板 / S4b 回封动作(10/25 用户: 动作发生时就提醒, 不等结果; 参数动态见 signal_params) ----------
    def _s4(self, S, ctx, out):
        c, t, x, p, v, vw, b, k = ctx
        up = S.m["up"]
        if not up or not b:
            return
        z = S.s4
        g = DYN.get("_global") or {}
        n_open, drop = float(g.get("S4a_N秒") or 18), float(g.get("S4b_DROP") or 0.5)
        sealed = float(b[0][0] or 0) >= up - S.m["tick"] / 2
        if sealed:
            z.update(sealed=True, t_open=None, mx=0.0, a_fired=False, b_fired=False)
            return
        if z["sealed"]:   # 刚开板
            z.update(sealed=False, t_open=x, s_open=t, low=p, mx=0.0, a_fired=False, b_fired=False)
            return
        if z["t_open"] is None:
            return
        z["low"] = min(z["low"], p)
        dur = x - z["t_open"]
        if not z["a_fired"] and dur >= n_open:   # S4a: 开板持续 ≥ N 秒(全市场开板时长 P25)才算炸板, 排除秒开秒封
            z["a_fired"] = True
            self._ev(S, c, t, "S4a", p, f"{z['s_open']} 开板, 已开 {dur} 秒(≥{n_open:g} 秒算炸板), 现价离涨停 {(p / up - 1) * 100:+.2f}%, 开板后最低 {(z['low'] / up - 1) * 100:+.2f}%", out)
        if k and k[0][0] and abs(float(k[0][0]) - up) < S.m["tick"] / 2:   # 卖一挂在涨停价 = 正在往回封
            va = float(k[0][1] or 0)
            z["mx"] = max(z["mx"], va)
            if z["a_fired"] and not z["b_fired"] and z["mx"] > 0 and va <= (1 - drop) * z["mx"]:   # S4b: 涨停价上的卖单被吃掉 ≥ DROP(近 3 日真回封前的降幅中位)
                z["b_fired"] = True
                self._ev(S, c, t, "S4b", p, f"{z['s_open']} 开板后, 卖一挂涨停价 {up:g} 的量从 {z['mx']:.0f} 降到 {va:.0f}(降 {(1 - va / z['mx']) * 100:.0f}%, 阈 {drop * 100:.0f}%), 有回封动作", out)
        if dur > P["S4_N"] * 60:
            z["t_open"] = None   # 开板太久(N 分钟)不再等

    # ---------- S5 尾盘拉升 ----------
    def _s5(self, S, ctx, out):
        c, t, x, p, v, vw, b, k = ctx
        if "S5" in S.done or t < P["S5_FROM"]:
            return
        z = S.s5
        if t <= P["S5_TO"] and (z["L"] is None or p < z["L"]):
            z.update(L=p, tL=x, tLs=t)
            return
        if z["L"] and x - z["tL"] <= P["S5_WIN"] and p >= z["L"] * (1 + prm(S, "S5_UP")):
            S.done.add("S5")
            self._ev(S, c, t, "S5", p, f"14:25~14:45 低点 {z['L']:g}({z['tLs']}), {(x - z['tL']) // 60} 分钟内涨到 {p:g}(+{(p / z['L'] - 1) * 100:.2f}%, 本票阈 {prm(S, 'S5_UP') * 100:.2f}%)", out)

    # ---------- S7 开盘冲高到位 ----------
    def _s7(self, S, ctx, out):
        c, t, x, p, v, vw, b, k = ctx
        if "S7" in S.done or x > P["S7_WIN"] or not S.open:
            return
        x7 = prm(S, "S7_X")   # 10/25: 本票近 30 日开盘 30 分钟最高的 P80
        tgt = S.open * (1 + x7 / 100)
        if p >= tgt - 1e-9:
            S.done.add("S7")
            self._ev(S, c, t, "S7", p, f"开盘 {S.open:g} × (1+{x7:g}%[本票近 30 日 P80]) = {tgt:.3f}, {t} 到 {p:g}", out)


# ================================================================ 节流 + 推送
class Throttle:
    """同票同信号 DEDUP_MIN 分钟(事件时间)内只记一次"""
    def __init__(self):
        self.last = {}

    def ok(self, e):
        key, x = (e["code"], e["sig"]), secs(e["t"])
        if key in self.last and x - self.last[key] < P["DEDUP_MIN"] * 60:
            return False
        self.last[key] = x
        return True


def line(e):
    return f"{e['name']}({e['code']}) {e['sig']} {e['sig_name']} {e['t'][:5]} 价 {e['px']:g}"


def compose(evs, D, hold):
    """合并成一条: 持仓在前, 同组按时间; 最多 MAX_LINES 行"""
    hs = sorted([e for e in evs if e["code"] in hold], key=lambda e: e["t"])
    ot = sorted([e for e in evs if e["code"] not in hold], key=lambda e: e["t"])
    L, n = [f"分时信号 {dt.datetime.now():%H:%M}(同票同信号 {P['DEDUP_MIN']} 分钟只报一次, 只是盘面事实不是买卖建议)"], 0
    for title, grp in (("持仓:", hs), ("盯盘票:", ot)):
        if not grp:
            continue
        L.append(title)
        for e in grp:
            if n >= P["MAX_LINES"]:
                break
            L.append(line(e))
            n += 1
    if len(evs) > n:
        L.append(f"另 {len(evs) - n} 条见 results/_live/{D}/signals.jsonl")
    return "\n".join(L)


class Pusher:
    def __init__(self, D, hold_fn, dry=False):
        self.D, self.hold_fn, self.dry = D, hold_fn, dry
        self.pending, self.lock, self.busy = [], threading.Lock(), False
        self.sf = LIVE / D / "signals_push.json"
        try:
            self.last_push = json.loads(self.sf.read_text(encoding="utf-8")).get("last_push", 0.0)
        except (OSError, ValueError):
            self.last_push = 0.0

    def add(self, e):
        with self.lock:
            self.pending.append(e)

    def tick(self):
        try:   # 10/25 用户批: 合并推送总线开着 → 不再自己攒 30 分钟, 来了就交给总线(总线按剩余额度动态攒批, 和 live line 挂单合成一条)
            import push_bus as PB
            bus = PB.on() and not self.dry
        except Exception:   # noqa: BLE001
            bus = False
        if bus and self.pending:
            hold = self.hold_fn()
            with self.lock:
                evs, self.pending = list(self.pending), []
            PB.enqueue(compose(evs, self.D, hold), src="live_signal", urgent=any(e["code"] in hold for e in evs) or any(e["sig"] == "S4b" for e in evs), D=self.D)
            return
        if self.busy or not self.pending or time.time() - self.last_push < P["PUSH_GAP_MIN"] * 60:
            return
        hold = self.hold_fn()
        with self.lock:
            evs = list(self.pending)
        has_hold = any(e["code"] in hold for e in evs)
        try:
            import wx_send
            t0, used = wx_send.quota()
        except Exception:   # noqa: BLE001
            t0, used = None, 0
        if t0 and used >= P["QUOTA_SOFT"] and not has_hold:
            return   # 配额紧: 没有持仓票的批次先攒着
        text = compose(evs, self.D, hold)
        if t0 and used >= P["QUOTA_SOFT"]:
            text += f"\n(微信额度: 你 {t0:%H:%M} 后已推 {used} 条, 方便时回个字)"
        with self.lock:
            self.pending = [e for e in self.pending if e not in evs]
        self.busy, self.last_push = True, time.time()
        try:
            self.sf.write_text(json.dumps({"last_push": self.last_push, "at": dt.datetime.now().isoformat(timespec="seconds"), "n": len(evs)}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        threading.Thread(target=self._send, args=(text,), daemon=True).start()

    def _send(self, text):
        try:
            import wx_send
            r = wx_send.send(text, src="live_signal", raw=True, wait=120, dry=self.dry, verbose=True)
            print(f"[signals] 推送 {r}", file=sys.stderr, flush=True)
        except Exception as e:   # noqa: BLE001
            print(f"[signals] 推送失败: {e}", file=sys.stderr, flush=True)
        finally:
            self.busy = False


# ================================================================ 盯哪些票 / 持仓
def v3_holds(D):
    out = set()
    for f in [*(LIVE / D).glob("live_*/state.json"), *(LIVE / D).glob("paper_*/state.json")]:
        try:
            out |= set((json.loads(f.read_text(encoding="utf-8")).get("positions") or {}).keys())
        except (OSError, ValueError, AttributeError):
            continue
    return out


def real_holds():
    """用户实盘持仓代码(snapshots 最近一份成交导出; 只取代码, 数量金额不出内存 —— 实盘隐私)"""
    out = set()
    try:
        import t_bot as TB
        for f in TB._snap_files()[-1:]:
            for l in f.read_text(encoding="utf-8").splitlines():
                w = l.split()
                if len(w) >= 5 and w[0].isdigit() and len(w[0]) <= 3 and len(w[1]) == 6 and w[1].isdigit():
                    out.add(w[1])
    except Exception:   # noqa: BLE001
        pass
    return out


def watch_codes(D):
    out = set()
    for f in [*(LIVE / D).glob("live_*/must_state.json"), *(LIVE / D).glob("paper_*/must_state.json")]:
        try:
            w = json.loads(f.read_text(encoding="utf-8")).get("watch") or {}
            out |= {str(x) for x in (w.keys() if isinstance(w, dict) else w)}
        except (OSError, ValueError, AttributeError):
            continue
    out = {c for c in out if re.fullmatch(r"\d{6}", c)}
    return out | v3_holds(D) | real_holds()


def snap_files(D):
    f = MKT / D / "book_snap.jsonl"
    return [x for x in (f.with_suffix(".jsonl.gz"), f) if x.exists()]


def iter_rows(D):
    for f in snap_files(D):
        op = gzip.open if f.suffix == ".gz" else open
        with op(f, "rt", encoding="utf-8", errors="replace") as fh:
            for l in fh:
                try:
                    yield json.loads(l)
                except ValueError:
                    continue


# ================================================================ 回放
def sim_pushes(evs):
    """模拟 Pusher(每 3 秒看一次): 攒着的事件在"上次推送 + 间隔"那一刻推出; 间隔已满时新事件立刻推。时间用事件钟点, 午休会被算进间隔(略偏少)"""
    gap, last, n, pend = P["PUSH_GAP_MIN"] * 60, -10 ** 9, 0, 0
    for x in sorted(secs(e["t"]) for e in evs):
        if pend and last + gap <= x:
            n, last, pend = n + 1, last + gap, 0
        if x >= last + gap:
            n, last = n + 1, x
        else:
            pend += 1
    return n + (1 if pend else 0)


def replay(D, until=None, codes=None, all_=False, samples=5):
    load_yaml()
    load_dyn(D)
    meta = Meta(D)
    want = None if all_ else set(codes or watch_codes(D))
    det = Detector(D, meta, emit=(lambda c: c in want) if want is not None else None)
    th = Throttle()
    raw, kept = [], []
    t0 = time.time()
    for r in iter_rows(D):
        if until and (r.get("t") or "") > until + ":59":
            continue
        for e in det.feed(r):
            raw.append(e)
            if th.ok(e):
                kept.append(e)
    n_codes = len(det.st)
    print(f"== {D} 回放{' 至 ' + until if until else ''}: {n_codes} 只票, 用时 {time.time() - t0:.1f}s; 口径参数 S4.N={P['S4_N']:g} S7.x={P['S7_X']:g}")
    if want is not None:
        print("票: " + "、".join(f"{meta.name(c)}({c})" for c in sorted(want)))
    print(f"{'信号':<14}{'原始':>6}{'去重后':>8}{'涉及票':>8}{'单票最多':>9}")
    for sg in NAMES:
        rs = [e for e in raw if e["sig"] == sg]
        ks = [e for e in kept if e["sig"] == sg]
        cc = collections.Counter(e["code"] for e in ks)
        print(f"{sg} {NAMES[sg]:<10}{len(rs):>6}{len(ks):>8}{len(cc):>8}{(max(cc.values()) if cc else 0):>9}")
    print(f"合计 原始 {len(raw)} / 去重后 {len(kept)}(平均每只 {len(kept) / max(1, n_codes):.1f} 条); 按 {P['PUSH_GAP_MIN']} 分钟合并推送 → 约 {sim_pushes(kept)} 条微信"
          + ("" if want is not None else "(--all 只看噪声, 实盘只推名单内的票)"))
    for sg in NAMES:
        ks = [e for e in kept if e["sig"] == sg]
        if not ks:
            continue
        print(f"\n-- {sg} {NAMES[sg]} 样例(前 {samples} 条) --")
        for e in ks[:samples]:
            print(f"  {line(e)} | {e['detail']}")
    return kept


# ================================================================ 实盘
def run(D, codes=None, all_=False, dry=False):
    load_yaml()
    load_dyn(D)
    meta = Meta(D)
    meta.sigmas()
    fixed = set(codes) if codes else None
    state = {"want": fixed or watch_codes(D), "at": time.time(), "hold": v3_holds(D) | real_holds()}

    def refresh():
        if time.time() - state["at"] > 60:
            state.update(at=time.time(), hold=v3_holds(D) | real_holds())
            if not fixed:
                state["want"] = watch_codes(D)

    det = Detector(D, meta, emit=None if all_ else (lambda c: c in state["want"]))
    th = Throttle()
    out_f = LIVE / D / "signals.jsonl"
    out_f.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    if out_f.exists():   # 重启续跑: 已记过的不重复记 / 推, 节流表也接上
        for l in out_f.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(l)
            except ValueError:
                continue
            seen.add((e["code"], e["sig"], e["t"]))
            th.ok(e)
    pusher = Pusher(D, lambda: state["hold"], dry)
    print(f"[signals] {D} 开始 pid={os.getpid()} 盯 {'全部' if all_ else len(state['want'])} 只 → {out_f}", file=sys.stderr, flush=True)
    f = MKT / D / "book_snap.jsonl"
    fh, buf = None, ""

    def handle(r):
        now_hm = dt.datetime.now().strftime("%H:%M:%S")
        for e in det.feed(r):
            key = (e["code"], e["sig"], e["t"])
            if key in seen or not th.ok(e):
                continue
            seen.add(key)
            e["hold"] = e["code"] in state["hold"]
            stale = secs(now_hm) - secs(e["t"]) > P["STALE_MIN"] * 60
            if stale:
                e["stale"] = True
            with out_f.open("a", encoding="utf-8") as w:
                w.write(json.dumps(e, ensure_ascii=False) + "\n")
            if not stale:
                pusher.add(e)
    try:
        while True:
            hm = dt.datetime.now().strftime("%H:%M:%S")
            if hm > "15:00:30":
                break
            refresh()
            if fh is None:
                if f.exists():
                    fh = f.open("r", encoding="utf-8", errors="replace")
                elif f.with_suffix(".jsonl.gz").exists() and hm > "15:00:00":
                    break
            if fh is not None:
                chunk = fh.read()
                if chunk:
                    buf += chunk
                    *lines, buf = buf.split("\n")
                    for l in lines:
                        try:
                            handle(json.loads(l))
                        except ValueError:
                            continue
                elif not f.exists():   # 被收盘压缩挪走
                    break
            pusher.tick()
            time.sleep(3)
    finally:
        if fh:
            fh.close()
        if pusher.pending:   # 收盘前还没推的, 最后合并推一次(不受 15 分钟间隔限制)
            pusher.last_push = 0
            pusher.tick()
            for _ in range(60):
                if not pusher.busy:
                    break
                time.sleep(1)
        print(f"[signals] {D} 结束", file=sys.stderr, flush=True)


def push_test(D):
    load_yaml()
    load_dyn(D)
    meta = Meta(D)
    evs = [{"t": "10:12:03", "code": "002307", "name": meta.name("002307"), "sig": "S2", "sig_name": NAMES["S2"], "px": 3.56, "detail": ""},
           {"t": "10:05:30", "code": "601988", "name": meta.name("601988"), "sig": "S1", "sig_name": NAMES["S1"], "px": 7.09, "detail": ""}]
    import wx_send
    return wx_send.send(compose(evs, D, {"601988"}), src="live_signal", raw=True, dry=True)


def main():
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay")
    ap.add_argument("--run")
    ap.add_argument("--until")
    ap.add_argument("--codes")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--push-test", action="store_true")
    a = ap.parse_args()
    codes = [c.strip()[-6:] for c in a.codes.split(",") if c.strip()] if a.codes else None
    if a.replay:
        replay(a.replay, a.until, codes, a.all, a.samples)
    elif a.run and a.push_test:
        push_test(a.run)
    elif a.run:
        run(a.run, codes, a.all, a.dry)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
