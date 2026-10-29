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
    "S4P_SIGMA_K": 1.5, "S4P_NEAR": 0.02, "S4C_GAP": 45, "S4C_GAP_MAX": 240, "FAST_SIGS": ("S1", "S7", "S4p", "S4c", "S4b", "S4a", "S8", "S9", "D1", "D2", "D3", "S10", "S11", "S12", "S13", "D4", "D5", "R1", "S2"),   # 10/26 20:0x 用户: S1 / S7 也走快车道; 10/27 S10 翻红拉升
    "POOL_SIGS": ("S3", "S4a", "S4p", "S4c", "S4b", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12", "S13", "D4", "D5", "D1", "D2", "D3", "S2", "R1"), "POOL_DIP_AFTER_ZB": (),   # 10/28 12:2x 用户: 盯盘池出低吸不用过大盘门槛、也不用先炸板(噪声交给统计期望闸 SIG_ODDS)   # 10/26 20:1x 用户"股票推送少": 盘口池里不在盯盘名单的股票(盯盘池)也出 强势 / 板类信号; 低吸只在当天炸过板之后(炸板回踩)
    "PICK_STOCK": (40, 80), "PICK_CB": (15, 30),   # 10/28 12:4x 用户: 盯盘范围扩大(有统计期望闸兜噪声); 原 20~40 / 10~20   # 10/26 晚用户: 盯盘池股票 20~40 / 名单转债 10~20, 只数按盘面活跃度动态(Picker)
    "CD_BASE_MIN": 30, "CD_MAX_MIN": 45, "CD_CODE_N": 3, "CD_CODE_WIN_MIN": 30,   # 10/26 20:0x 用户批动态冷却(只管普通 / 慢通道的推送, signals.jsonl 照记)
    "SLOW_SIGS": (), "S8_NEAR": 0.07, "S8_RANGE": 0.025, "S8_HOLD": 900, "S9_NEAR": 0.01,   # 10/26 用户批 S8 / S9(百洋股份 / 锋龙股份上板方式 U21); 10/28 用户: S2 回踩均价来不及看 → SLOW_SIGS 清空走快车道
      # 10/26 用户: 回封提醒要提前 45 秒~1 分钟(原 S4b 只比真回封早 3~6 秒)
    "D_START": "09:40:00", "D_BOUNCE_K": 0.3,   # 10/26: 反弹门槛 = max(2 价位, 0.3×σ5×价) —— 转债一个价位 ≈0.0006% 形同虚设
     "S10_DIP": 0.005, "S10_DIP_AMP_K": 0.15, "S10_EPS": 0.001, "S10_CROSS_WIN": 600, "S10_LOW_WIN": 1500, "S10_RISE_MIN": 0.01, "S10_RISE_K": 0.3, "S10_VOL_WIN": 180, "S10_VOL_K": 2.0, "S10_MAX": 3,
     "S11_LOOK": 1800, "S11_BANDS": 3, "S11_Z": 3.0, "S11_REARM": 2, "S11_MAX": 3,   # 10/27 用户: 连续跨越 13 档 3 档(奥普特 10:30); 快慢按本票 σ5 定: 涨幅 / (σ5·√(用时/5分钟)) ≥ 3 才算"连续"(本票少见的快)   # 10/27 晚用户: 绿翻红(尤其放量)是重要反转信号, 转债的正股翻红拉升必须提醒(奥普特 10:30 翻红拉升 → 奥普转债 +5%, 当天没任何提醒)
     "WALL_K": 4.0, "WALL_AMT_K": 0.25, "WALL_SEEN": 2, "WALL_AGE": 30, "WALL_KEEP": 600, "WALL_GO_TICKS": 3, "WALL_GO_SIGMA": 0.5, "WALL_GAP": 60, "WALL_FLIP_WIN": 1200, "WALL_NEAR_TICKS": 2, "WALL_MAX": 2, "WALL_START": "09:35:00",   # 10/28 晚用户批: 墙位翻转(大业股份 09:30 17.40 卖 1538 手 → 09:49 被吃穿 → 09:53 同价买一 1290 手托住 = 转强)
     "D1_K": 2.0, "D1_HOLD": 180, "D2_BAND": 0.003, "D2_HOLD": 180, "D3_K": 0.8, "D3_HOLD": 180,   # 10/26 用户批: 低吸信号 D1~D3(银轮转债 10:11 回到开盘价没任何提醒)
    "DEDUP_D_MIN": 90, "DEDUP_MIN": 30, "PUSH_GAP_MIN": 30, "MAX_LINES": 12, "STALE_MIN": 5, "QUOTA_SOFT": 8,   # 10/24 主会话: K 2→3、推送间隔 15→30 分钟(agent 回放: 一天约 7~9 条, 微信额度约 10 条)
}
NAMES = {"S1": "急跌后拉起", "S2": "回踩均价线不破", "S3": "二次冲高", "S4a": "炸板", "S4p": "拉回贴近涨停", "S4c": "冲击涨停价", "S4b": "回封动作", "S5": "尾盘拉升", "S6": "竞价抢筹", "S7": "开盘冲高到位", "S8": "蓄势预警", "S9": "午后冲板候选", "D1": "跌破均价后企稳", "D2": "冲高回落到开盘价", "D3": "回撤到振幅位企稳", "S10": "绿翻红拉升", "S11": "连续跨越 13 档 3 档", "S12": "卖墙变买墙", "S13": "买墙变卖墙", "D4": "跌停封单松动", "D5": "跌停撬板", "R1": "指数共振低点"}
MUST_SIGS = ("S10", "S11")   # 10/27 用户"必须提醒": 名单 / 持仓 / 点名里的票(含转债)不受 Picker 名额限制
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
            amp = None
            try:   # 10/26 D3: 本票近 30 日振幅中位(日线 (高−低)/昨收); 转债没日线文件 → 用 S7_X(开盘 30 分钟冲高 P80)×2 近似
                k30 = [x for x in json.loads((QUOTES / "daily" / f"{c}.json").read_text(encoding="utf-8")).get("klines") or [] if x.get("d", "") < self.D][-31:]
                amps = sorted((float(b["h"]) - float(b["l"])) / float(a["c"]) for a, b in zip(k30, k30[1:]) if float(a["c"]) > 0)
                amp = amps[len(amps) // 2] if amps else None
            except (OSError, ValueError, KeyError):
                pass
            if amp is None and dp.get("S7_X"):
                amp = 2 * float(dp["S7_X"]) / 100
            try:   # 平时 1 分钟成交额(近 20 日日均成交额 / 240)
                k_ = json.loads((QUOTES / "daily" / f"{c}.json").read_text(encoding="utf-8")).get("klines") or []
                k_ = [x for x in k_ if x.get("d", "") < self.D and x.get("a")][-20:]
                if k_:
                    amt1 = statistics.fmean(float(x["a"]) for x in k_) / 240
            except (OSError, ValueError):
                pass
            self._cache[c] = {"prev": prev, "up": up, "dn": dn, "tick": tk, "sigma": sg, "sigma_src": src, "name": self.name(c), "dp": dp, "amt1": amt1, "amp30": amp}
            stk = cb_stock(c)
            if stk:   # 10/26 15:2x 用户: 转债敏感度 = 正股动态数值 × (转债涨跌幅 / 正股涨跌幅) —— 10cm 正股 ×2, 20cm / 30cm 正股复用同一套(×1)
                try:
                    sm = self.get(stk)
                    f_ = (0.2 / ((sm["up"] / sm["prev"]) - 1)) if sm.get("up") and sm.get("prev") else 2.0
                    f_ = max(1.0, min(2.0, round(f_, 2)))
                    m_ = self._cache[c]
                    if sm.get("sigma_src") != "默认":
                        m_["sigma"], m_["sigma_src"] = sm["sigma"] * f_, f"正股{stk}×{f_:g}"
                    else:   # 正股没分钟 / 日线: 用全市场正股 σ5 中位 × 系数, 且不低于转债自己的
                        g_ = float((DYN.get("_global") or {}).get("σ5中位") or P["SIGMA_DEFAULT"]) * f_
                        if g_ > m_["sigma"]:
                            m_["sigma"], m_["sigma_src"] = g_, f"全市场正股σ5中位×{f_:g}"
                    if sm.get("amp30"):
                        m_["amp30"] = sm["amp30"] * f_
                    for key in ("S2_BAND", "S3_RISE", "S3_PULLBACK", "S7_X", "S6_UP"):
                        if key in (sm.get("dp") or {}):
                            m_["dp"][key] = sm["dp"][key] * f_
                    m_["stock"], m_["cb_k"] = stk, f_
                except Exception:   # noqa: BLE001  正股取不到就用转债自己的
                    pass
        return self._cache[c]


_CB = {}
_BANDS = {}
_IDX = {"t": 0.0, "D": None, "rows": {}}   # 10/28: 指数此刻(index_snap.jsonl, 60 秒重读) —— 低吸信号带上「此刻上证 / 创业板」, 回放 10/19~27: 普跌日低吸到收盘中位 −1.8%


def idx_now(D, t):
    """→ "上证 −0.52% / 创业板 +0.10%"(t 时刻及以前最近一笔); 没数据 = """""
    import bisect as _bs
    if _IDX["D"] != D or time.time() - _IDX["t"] > 60:
        rows = {}
        try:
            for l in (MKT / D / "index_snap.jsonl").open(encoding="utf-8"):
                if '"sh000001"' in l[:20] or '"sz399006"' in l[:20]:
                    r = json.loads(l)
                    if r.get("p") and r.get("pc"):
                        rows.setdefault(r["s"], []).append((r["t"], (r["p"] / r["pc"] - 1) * 100))
        except OSError:
            pass
        for v in rows.values():
            v.sort()
        _IDX.update(t=time.time(), D=D, rows=rows)
    out = []
    for s_, nm in (("sh000001", "上证"), ("sz399006", "创业板")):
        v = _IDX["rows"].get(s_) or []
        i = _bs.bisect_right([x for x, _ in v], t) - 1
        if i >= 0:
            out.append(f"{nm} {v[i][1]:+.2f}%")
    return " / ".join(out)   # 10/28: S11 每个涨跌幅限制的档位表(别和 _CB 混用)


# ---------- 10/28 12:2x 用户令: 统计期望闸 + 指数共振低点 ----------
_ODDS = {"t": 0.0, "rows": {}}
D_NOW = {}   # run() 设当天日期(odds_of 取此刻指数用)
_RES = {"until": -1, "fired": [], "last": -10 ** 9, "info": ""}   # 共振窗口(交易秒) / 已报过的低点 / 上次报的时刻


def odds_of(e):
    """信号的历史盈利率(scripts/live/signal_odds.py 回放: 信号价买入, 转债当天之后最高 / 正股次日最高 ≥ +TGT%) → (p, n, tgt); 没表 = None"""
    if time.time() - _ODDS["t"] > 600:
        try:
            _ODDS["rows"] = json.loads((LIVE / "signal_odds.json").read_text(encoding="utf-8")).get("rows") or {}
        except (OSError, ValueError):
            _ODDS["rows"] = {}
        _ODDS["t"] = time.time()
    cb = e["code"][:2] in ("11", "12")
    tgt = float(_flag("SIG_ODDS_TGT_CB", "2") if cb else _flag("SIG_ODDS_TGT_STOCK", "3"))
    base = f"{e['sig']}|{'cb' if cb else 'stock'}"
    z = _ODDS["rows"].get(base)
    try:   # 10/28: 先用「上证此刻红 / 绿」分组的数(样本 ≥20), 不够退回整体
        ix = idx_now(D_NOW["D"], e["t"]) if D_NOW.get("D") else ""
        zb = _ODDS["rows"].get(f"{base}|{'up' if float(ix.split('上证 ')[1].split('%')[0]) >= 0 else 'dn'}")
        if zb and int(zb.get("n") or 0) >= 20:
            z = zb
    except (IndexError, ValueError):
        pass
    if not z:
        return None
    return z.get(f"win{tgt:g}"), int(z.get("n") or 0), tgt


def odds_gate(e):
    """True = 过闸(推); False = 只记不推。门槛 SIG_ODDS_MIN(默认 0.25) / 样本 < SIG_ODDS_MIN_N(默认 10) 也不推; R1 不过闸"""
    if e["sig"] == "R1" or _flag("SIG_ODDS", "1") != "1":
        return True
    o = odds_of(e)
    if not o or o[0] is None:
        e["odds"] = None
        return False
    e["odds"] = {"p": o[0], "n": o[1], "tgt": o[2]}
    return o[1] >= int(_flag("SIG_ODDS_MIN_N", "10")) and o[0] >= float(_flag("SIG_ODDS_MIN", "0.25"))


def res_check(D, t):
    """指数共振低点: 上证和创业板在 5 分钟内各自出现近 15 分钟分时低点(离近 60 分钟高点回落 ≥ 上证 0.25 / 创业板 0.4 个百分点),
    之后 120 秒不创新低且反弹 ≥ 上证 0.08 / 创业板 0.15 个百分点 → 返回说明; 一个低点只报一次, 每天 ≤3 次, 间隔 ≥30 分钟"""
    if t < "09:40:00" or lunch(t) or t >= "14:55:00" or len(_RES["fired"]) >= int(_flag("SIG_RES_MAX", "6")):
        return None
    idx_now(D, t)
    x = secs(t)
    lows = {}
    for s_, nm, dmin, bmin in (("sh000001", "上证", 0.25, 0.08), ("sz399006", "创业板", 0.4, 0.15)):
        v = [(tt, pc) for tt, pc in _IDX["rows"].get(s_) or [] if "09:30:00" <= tt <= t and x - secs(tt) <= 3600]
        if len(v) < 20:
            return None
        lo_t, lo = min([y for y in v if x - secs(y[0]) <= 900], key=lambda y: (y[1], -secs(y[0])))   # 近 15 分钟的分时低点(不要求全天 / 60 分钟新低: 10/28 创业板 10:44 是比 10:24 高的次低点)
        hi = max(pc for _, pc in v)
        cur = v[-1][1]
        if not (hi - lo >= dmin and cur - lo >= bmin and 120 <= x - secs(lo_t) <= 900):
            return None
        lows[nm] = (lo_t, lo, cur, hi, (hi - lo) / dmin)
    ts = [secs(v[0]) for v in lows.values()]
    if max(ts) - min(ts) > 300:
        return None
    key = max(v[0] for v in lows.values())
    if key in _RES["fired"] or trs(t) - _RES["last"] < 1800:
        return None
    _RES["fired"].append(key)
    _RES["last"] = trs(t)
    _RES["until"] = trs(t) + 900
    _RES["k"] = max(0.0, sum(v[4] for v in lows.values()) / len(lows) - 1) + 1.0
    _RES["info"] = " / ".join(f"{nm} {v[0][:5]} 低 {v[1]:+.2f}% → 现 {v[2]:+.2f}%(近 60 分钟高 {v[3]:+.2f}%)" for nm, v in lows.items())
    return _RES["info"]


def res_on(t):
    return trs(t) <= _RES["until"]


def cb_stock(c):
    """转债代码 → 正股代码(东财转债列表最新一份); 不是转债 → None"""
    if not c.startswith(("11", "12")):
        return None
    if not _CB:
        try:
            fs = sorted((ROOT / "downloads" / "quotes" / "cb" / "meta").glob("RPT_BOND_CB_LIST_all_*.json"))
            m = json.loads(fs[-1].read_text(encoding="utf-8"))
            rows = m if isinstance(m, list) else ((m.get("result") or {}).get("data") or m.get("data") or [])
            _CB.update({str(r.get("SECURITY_CODE")): str(r.get("CONVERT_STOCK_CODE") or "") for r in rows})
        except (OSError, ValueError, IndexError):
            _CB["_"] = ""
    v = _CB.get(c) or ""
    return v if re.fullmatch(r"\d{6}", v) else None


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
        self.s4 = {"sealed": False, "t_open": None, "low": None, "s_open": None, "a_fired": False, "b_fired": False, "mx": 0.0, "p_fired": False, "att": False, "att_n": 0, "att_mx": 0.0, "prev_mx": 0.0, "c_last": -10 ** 9, "c_n": 0}
        self.s5 = {"L": None, "tL": None}
        self.d = {"hi": None, "d1": None, "d2": None, "d3": None}
        self.s10 = {"lo": None, "xlo": None, "tlo": None, "xb": None, "armed": False, "n": 0, "aw": collections.deque()}   # 10/27 绿翻红拉升
        self.s11 = {"w": collections.deque(), "fired_band": None, "n": 0}   # 10/27 跨档: (交易秒, 档序号, 价)
        self.wall = {"ask": {}, "bid": {}, "brk": [], "fired": set(), "n": {"S12": 0, "S13": 0}}   # 10/28 墙位翻转: 候选墙 {价: {cnt, mx, t, x, ref}} / 被穿的墙
        self.s8 = None   # 蓄势: 进入"离涨停 ≤2% 且在均价上方"的起点   # 10/26 低吸 D1~D3 状态


class Picker:
    """10/26 晚用户: 盯盘池股票 20~40 只、转债 10~20 只, 多少按盘面动态定(股票比转债多, 转债也重要; 今天转债重复提同几只、又怕遗漏)
    活跃分(每只票可比, 0~9): 3×今天碰过涨停(转债看正股) + 现涨跌幅 / 本票 30 日振幅(封顶 3) + 今天成交额 / 平时同时段成交额(封顶 3);
    最近 30 分钟每推一次 −1(让位给没推过的, 治"重复提同几只"); 名额 = 活跃分 ≥ ACT_TH 的只数, 夹在 [下限, 上限] 内(盘面热 → 多看, 冷 → 少看);
    刚出过信号的票 15 分钟内留在集合里(炸板后的回封 / 低吸不断档); 持仓 / 点名 / 线上盯盘名单里的股票不占名额、一直在"""
    ACT_TH = 3.0

    def __init__(self, det, meta):
        self.det, self.meta = det, meta
        self.hist = collections.defaultdict(list)   # 代码 → [事件交易秒]
        self.at, self.out = -10 ** 9, (set(), set())

    def note(self, c, x):
        self.hist[c].append(x)

    def score(self, c, S_, xnow):
        p_, pv = S_.win[-1][1], S_.m.get("prev")
        if not pv:
            return None
        amp = S_.m.get("amp30") or 3.0
        hi = (S_.d or {}).get("hi") or p_
        up = S_.m.get("up")
        touched = bool(up and hi >= up - S_.m["tick"] / 2)
        stk = cb_stock(c)
        if stk and stk in self.det.st and self.det.st[stk].win:   # 转债: 正股碰过涨停也算
            T_ = self.det.st[stk]
            uph = T_.m.get("up")
            touched = touched or bool(uph and ((T_.d or {}).get("hi") or 0) >= uph - T_.m["tick"] / 2)
        move = min(3.0, abs(p_ / pv - 1) * 100 / max(0.5, amp))
        a1 = S_.m.get("amt1")
        mins = max(1.0, (getattr(S_, "x_last", 0) or 0) / 60)
        ar = min(3.0, (getattr(S_, "a_cum", 0) or 0) / (a1 * mins)) if a1 else 1.0
        pen = sum(1 for t in self.hist.get(c, []) if xnow - t < 1800)
        return 3.0 * touched + move + ar - pen

    def pick(self, want, keep, xnow, force=False):
        """→ (盯盘池股票集合, 在看的转债集合); 每 60 交易秒算一次"""
        if not force and xnow - self.at < 60:
            return self.out
        st_rows, cb_rows = [], []
        for c, S_ in self.det.st.items():
            if not S_.win or c in keep:
                continue
            is_cb = c[:2] in ("11", "12")
            if is_cb and c not in want:
                continue   # 转债只在名单里(土豆候选等)挑
            if not is_cb and (c in want or c[:1] not in ("0", "3", "6")):
                continue
            sc = self.score(c, S_, xnow)
            if sc is None:
                continue
            (cb_rows if is_cb else st_rows).append((sc, c))
        recent = {c for c, ts in self.hist.items() if ts and xnow - ts[-1] < 900}

        def take(rows, lo, hi):   # 名额含"刚出过信号留着的", 总数不超过上限
            rows.sort(reverse=True)
            n = min(hi, max(lo, sum(1 for sc, _ in rows if sc >= self.ACT_TH)))
            got = [c for _, c in rows if c in recent][:n]
            for _, c in rows:
                if len(got) >= n:
                    break
                if c not in got:
                    got.append(c)
            return set(got)
        lo_s, hi_s = P["PICK_STOCK"]
        lo_c, hi_c = P["PICK_CB"]
        self.out = (take(st_rows, lo_s, hi_s), take(cb_rows, lo_c, hi_c))
        self.at = xnow
        return self.out


class Detector:
    def __init__(self, D, meta=None, emit=None):
        self.D = D
        self.meta = meta or Meta(D)
        self.st = {}
        self.emit_filter = emit   # callable(code) -> bool; None = 全部
        self.must = None   # callable(code) -> bool: MUST_SIGS 绕过 emit_filter(名单 / 持仓 / 点名)
        self._rev = None   # 正股 → [转债]

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
        S.vw_now = vw   # 10/28: 指数共振低点 R1 列"此刻均价下方"的票用
        S.a_cum, S.x_last = a, x   # 10/26 晚: 动态选票(Picker)用 —— 今天累计成交额 / 最近时刻
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
        self._dip(S, ctx, out)   # 10/26: 低吸 D1~D3
        self._s89(S, ctx, out)   # 10/26: S8 蓄势预警 / S9 午后冲板候选
        self._s10(S, ctx, out)   # 10/27: 绿翻红拉升(正股翻红 → 同时报它的转债)
        self._s11(S, ctx, out)   # 10/27: 连续跨越 13 档 3 档(正股 → 同时报转债)
        self._dt(S, ctx, out)    # 10/28 晚: D4 跌停封单松动 / D5 跌停撬板
        self._wall(S, ctx, out)  # 10/28: 墙位翻转 S12 卖墙变买墙(转强) / S13 买墙变卖墙(转弱)
        return out

    def _ev(self, S, c, t, sig, px, detail, out):
        if self.emit_filter and not self.emit_filter(c) and not (sig in MUST_SIGS and self.must and self.must(c)):
            return
        if sig in ("D1", "D2", "D3"):   # 10/28: 低吸要看大盘 —— 回放 10/19~27: 上证收 −1.3% 以下的两天低吸到收盘中位 −1.4% / −1.8%, 上证收 +0.9% 那天 +2.8%
            ix = idx_now(self.D, t)
            if ix:
                detail = f"{detail}; 此刻 {ix}"
        ev = {"t": t, "code": c, "name": S.m["name"], "sig": sig, "sig_name": NAMES.get(sig, sig), "px": px, "detail": detail}
        pv, up = S.m.get("prev"), S.m.get("up")
        if pv and px:   # 10/28: 推送带当日涨跌和离涨停(大业股份 +2.8% 被标成【板】, 用户看不出是水下翻水上)
            ev["pct"] = round((px / pv - 1) * 100, 2)
            if up:
                ev["to_up"] = round((px / up - 1) * 100, 2)
                ev["lim"] = round((up / pv - 1) * 100)
        out.append(ev)

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
        fresh = dict(mx=0.0, a_fired=False, b_fired=False, p_fired=False, att=False, att_n=0, att_mx=0.0, prev_mx=0.0, c_last=-10 ** 9, c_n=0)
        if sealed:
            z.update(sealed=True, t_open=None, **fresh)
            return
        if z["sealed"]:   # 刚开板
            z.update(sealed=False, t_open=x, s_open=t, low=p, **fresh)
            return
        if z["t_open"] is None:
            return
        z["low"] = min(z["low"], p)
        dur = x - z["t_open"]
        if not z["a_fired"] and dur >= n_open:   # S4a: 开板持续 ≥ N 秒(全市场开板时长 P25)才算炸板, 排除秒开秒封
            z["a_fired"] = True
            self._ev(S, c, t, "S4a", p, f"{z['s_open']} 开板, 已开 {dur} 秒(≥{n_open:g} 秒算炸板), 现价离涨停 {(p / up - 1) * 100:+.2f}%, 开板后最低 {(z['low'] / up - 1) * 100:+.2f}%", out)
        lim = (up / S.m["prev"] - 1) if S.m.get("prev") else 0.1
        near = P["S4P_NEAR"] * lim / 0.1   # 10cm 2% / 20cm 4%
        # 10/26 用户: 拉回幅度用动态 —— 本票 5 分钟波动 σ5 × K(波动大的票要拉回更多才算), 至少 2 个价位, 最多开板深度的 60%(浅开板也能报)
        need = min(max(2 * S.m["tick"], P["S4P_SIGMA_K"] * float(S.m.get("sigma") or P["SIGMA_DEFAULT"]) * up), 0.6 * (up - z["low"]))
        if z["a_fired"] and not z["p_fired"] and p >= up * (1 - near) and up > z["low"] and (p - z["low"]) >= need and p > z["low"]:
            # 10/26 S4p: 炸板后从开板低点拉回 ≥ 动态幅度 且离涨停 ≤2% → 提前预警(襄阳轴承 09:51:57 / 真回封 09:52:54)
            z["p_fired"] = True
            self._ev(S, c, t, "S4p", p, f"{z['s_open']} 开板后最低 {z['low']:g}({(z['low'] / up - 1) * 100:+.2f}%), 已拉回 {(p - z['low']) / up * 100:.2f}%(阈 {need / up * 100:.2f}% = {P['S4P_SIGMA_K']:g}×本票σ5)到离涨停 {(p / up - 1) * 100:+.2f}%, 可能回封", out)
        # 10/26 用户: S4c 不等卖一到涨停价, 而是涨停价进了卖五档(= 卖一离涨停 ≤4 个价位)就算冲击; 冷却动态: 同一次开板里每报一次冷却翻倍(45 → 90 → 180, 封顶 240 秒)
        lv = next((i for i, a in enumerate(k[:5]) if a and a[0] and abs(float(a[0]) - up) < S.m["tick"] / 2), None) if k else None
        if lv is None and z["att"]:   # 一次冲击结束(涨停价退出卖五档)
            z.update(att=False, prev_mx=max(z["prev_mx"], z["att_mx"]), att_mx=0.0)
        if lv is not None:
            vl = float(k[lv][1] or 0)   # 涨停价那一档的卖单量
            if not z["att"]:
                z.update(att=True, att_n=z["att_n"] + 1, att_mx=0.0)
                gap = min(P["S4C_GAP"] * 2 ** z["c_n"], P["S4C_GAP_MAX"])
                if z["a_fired"] and x - z["c_last"] >= gap:
                    # 10/26 S4c: 冲到涨停价附近都报(动态冷却), 带涨停价卖单量和上次比 —— 大业股份第 3 次冲击 09:58:18, 真回封 09:59:30
                    z["c_last"], z["c_n"] = x, z["c_n"] + 1
                    cmp_ = f", 上次冲击最多 {z['prev_mx'] / 100:.0f} 手({'变小 = 抛压在减' if vl < z['prev_mx'] else '变大'})" if z["prev_mx"] else ""
                    self._ev(S, c, t, "S4c", p, f"{z['s_open']} 开板后第 {z['att_n']} 次冲向涨停价(涨停价在卖{lv + 1}), 涨停价卖单 {vl / 100:.0f} 手{cmp_}", out)
            z["att_mx"] = max(z["att_mx"], vl)
        at_lim = lv == 0
        if at_lim:   # 卖一挂在涨停价 = 正在往回封
            va = float(k[0][1] or 0)
            z["mx"] = max(z["mx"], va)
            if z["a_fired"] and not z["b_fired"] and z["mx"] > 0 and va <= (1 - drop) * z["mx"]:   # S4b: 涨停价上的卖单被吃掉 ≥ DROP(近 3 日真回封前的降幅中位)
                z["b_fired"] = True
                self._ev(S, c, t, "S4b", p, f"{z['s_open']} 开板后, 卖一挂涨停价 {up:g} 的量从 {z['mx']:.0f} 降到 {va:.0f}(降 {(1 - va / z['mx']) * 100:.0f}%, 阈 {drop * 100:.0f}%), 有回封动作", out)
        if dur > P["S4_N"] * 60:
            z["t_open"] = None   # 开板太久(N 分钟)不再等

    # ---------- D4 / D5 跌停封单松动 / 跌停撬板(10/28 晚用户令: 一字跌停次日跌停开 = 大量恐慌筹码, 要有「卖单松弛 / 买单出现」的提醒; 南方路机 / 吉大正元 / 大丰实业) ----------
    def _dt(self, S, ctx, out):
        c, t, x, p, v, vw, b, k = ctx
        dn = S.m.get("dn")
        if not dn or c[:2] in ("11", "12"):
            return
        z = S.__dict__.setdefault("dtz", {"sealed": False, "mx": 0.0, "f4": 0, "f5": 0, "t_open": None, "s_open": None, "lo_t": None})
        tick = S.m.get("tick") or 0.01
        b1p = float(b[0][0]) if b and b[0] and b[0][0] else 0.0
        sealed = p <= dn + tick / 2 and (not b1p or b1p <= dn + tick / 2) and k and k[0] and abs(float(k[0][0] or 0) - dn) < tick / 2   # 卖一挂跌停价 = 封着跌停
        if sealed:
            va = float(k[0][1] or 0)   # 跌停价上的卖单(封单)
            if not z["sealed"]:
                z.update(sealed=True, mx=va, t_open=None)
            z["mx"] = max(z["mx"], va)
            drop = float(DYN.get("_global", {}).get("S4b_DROP") or 0.6)
            if z["f4"] < 2 and z["mx"] > 0 and va <= (1 - drop) * z["mx"]:   # D4: 跌停封单被吃掉 ≥ 和涨停回封同一个阈值
                z["f4"] += 1
                z["mx"] = va
                self._ev(S, c, t, "D4", p, f"跌停价 {dn:g} 上的封单从最多 {(va / (1 - drop)) / 100:.0f} 手降到 {va / 100:.0f} 手(降 ≥{drop * 100:.0f}%) = 卖单松弛 / 有人在跌停价接; 买一 {b1p:g}", out)
            return
        if z["sealed"]:   # 刚撬板
            z.update(sealed=False, t_open=x, s_open=t)
            return
        if z["t_open"] is not None and z["f5"] < 2 and x - z["t_open"] >= int(P.get("D5_HOLD", 30)) and p > dn + tick / 2:
            z["f5"] += 1
            pv = S.m.get("prev")
            self._ev(S, c, t, "D5", p, f"{z['s_open']} 撬开跌停板, 已离开跌停价 {x - z['t_open']} 秒, 现价 {p:g}({(p / pv - 1) * 100:+.2f}%), 离跌停价 +{(p / dn - 1) * 100:.2f}%"
                                         + (f"; 均价 {vw:.3f}" if vw else "") + " —— 拉到水上 = 次日有卖点, 拉不上水 = 次日卖点不保证(用户 10/28)", out)
            z["t_open"] = None

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


    # ---------- S8 蓄势预警 / S9 午后冲板候选(10/26 用户批; U21 百洋股份离涨停 2% 横 30 分钟后拉板、锋龙股份午前离涨停 0.8% 午后开盘即封) ----------
    def _s89(self, S, ctx, out):
        c, t, x, p, v, vw, b, k = ctx
        up = S.m["up"]
        if not up or not vw:
            return
        sealed = bool(b and float(b[0][0] or 0) >= up - S.m["tick"] / 2)
        lim = (up / S.m["prev"] - 1) if S.m.get("prev") else 0.1
        if "S8" not in S.done:
            # 离涨停 ≤ S8_NEAR(10cm 7% / 20cm 14%)、在均价上方、没封板, 连续 S8_HOLD 秒且这段振幅 ≤ S8_RANGE = 高位横盘蓄势
            ok = not sealed and up * (1 - P["S8_NEAR"] * lim / 0.1) <= p < up and p >= vw
            if not ok:
                S.s8 = None
            else:
                if S.s8 is None:
                    S.s8 = {"x0": x, "t0": t, "hi": p, "lo": p}
                z = S.s8
                z["hi"], z["lo"] = max(z["hi"], p), min(z["lo"], p)
                if (z["hi"] - z["lo"]) / up > P["S8_RANGE"] * lim / 0.1:
                    S.s8 = {"x0": x, "t0": t, "hi": p, "lo": p}   # 振幅超了 = 不是横盘, 从这里重新算
                elif x - z["x0"] >= P["S8_HOLD"]:
                    S.done.add("S8")
                    self._ev(S, c, t, "S8", p, f"{z['t0']} 起在 {z['lo']:g}~{z['hi']:g} 横盘 {(x - z['x0']) // 60} 分钟(振幅 {(z['hi'] - z['lo']) / up * 100:.2f}%), 一直在均价 {vw:.3f} 上方; 现 {p:g} 离涨停 {(p / up - 1) * 100:+.2f}%", out)
        if "S9" not in S.done and "11:29:00" <= t <= "11:30:05" and not sealed and up * (1 - P["S9_NEAR"] * lim / 0.1) <= p < up:
            S.done.add("S9")
            self._ev(S, c, t, "S9", p, f"午前收盘 {p:g} 离涨停 {(p / up - 1) * 100:+.2f}%(≤{P['S9_NEAR'] * lim / 0.1 * 100:.0f}%), 均价 {vw:.3f}; 午后开盘可能直接冲板", out)

    # ---------- S10 绿翻红拉升(10/27 用户: 从绿翻红是重要反转信号, 尤其放量; 要冷却) ----------
    def cbs_of(self, stk):
        if self._rev is None:
            cb_stock("110000")   # 触发 _CB 加载
            self._rev = collections.defaultdict(list)
            for b_, s_ in _CB.items():
                if re.fullmatch(r"\d{6}", s_ or ""):
                    self._rev[s_].append(b_)
        return self._rev.get(stk, [])

    def _s10(self, S, ctx, out):
        """先在水下 ≥ max(0.5%, 0.15×本票 30 日振幅中位)(= 待命), 再拉回昨收上方 ≥0.1%, 且 离上次在水下 ≤10 分钟、从 25 分钟内的低点拉起 ≥ max(1%, 0.3×振幅);
        放量 = 最近 3 分钟成交额 / 平时同长度成交额(近 20 日均 / 240 × 分钟数), ≥2 倍标 🔥;
        冷却: 触发后要重新跌到待命深度才再认, 每天每票最多 3 次, 节流表同票 30 分钟一次; 股票触发时它的转债(在盘口里)同时出一条(转债名单 / 持仓 / 点名必推)"""
        c, t, x, p, v, vw, b, k = ctx
        pv = S.m.get("prev")
        z = S.s10
        z["aw"].append((x, getattr(S, "a_cum", 0) or 0))
        while z["aw"] and z["aw"][0][0] < x - P["S10_VOL_WIN"]:
            z["aw"].popleft()
        if not pv or t < "09:31:00" or c[:2] in ("11", "12"):   # 转债不单独算(跟正股走)
            return
        amp = S.m.get("amp30") or 0.04
        dip = max(P["S10_DIP"], P["S10_DIP_AMP_K"] * amp)
        if p < pv:
            z["xb"] = x
            if z["lo"] is None or p < z["lo"] or x - z["xlo"] > P["S10_LOW_WIN"]:
                z["lo"], z["xlo"], z["tlo"] = p, x, t
            if p <= pv * (1 - dip):
                z["armed"] = True
            return
        rise = max(P["S10_RISE_MIN"], P["S10_RISE_K"] * amp)
        if not (z["armed"] and z["n"] < P["S10_MAX"] and z["lo"] and p >= pv * (1 + P["S10_EPS"]) and z["xb"] is not None
                and x - z["xb"] <= P["S10_CROSS_WIN"] and x - z["xlo"] <= P["S10_LOW_WIN"] and (p - z["lo"]) / pv >= rise):
            return
        a1, (x0, a0), base = S.m.get("amt1"), z["aw"][0], "平时"
        if not a1 and x0 > 300:   # 没有日线成交额(没日线文件) → 用今天开盘以来的每分钟均额(开盘 5 分钟内不算, 太短)
            a1, base = (getattr(S, "a_cum", 0) or 0) / (x / 60) if x > 0 else None, "今天均额"
        vr = (S.a_cum - a0) / (a1 * (x - x0) / 60) if a1 and x - x0 >= 60 else None
        hot = vr is not None and vr >= P["S10_VOL_K"]
        vtxt = f"近 {(x - x0) // 60} 分钟成交额是{base} {vr:.1f} 倍{'(放量)' if hot else ''}" if vr is not None else "量比未知"
        lo, tlo = z["lo"], z["tlo"]
        z.update(armed=False, n=z["n"] + 1, lo=None, xlo=None, tlo=None)
        det = f"{tlo} 低点 {lo:g}({(lo / pv - 1) * 100:+.2f}%) → {t} 翻红到 {p:g}({(p / pv - 1) * 100:+.2f}%), 拉起 {(p - lo) / pv * 100:.2f}%(阈 {rise * 100:.2f}%); {vtxt}"
        self._ev(S, c, t, "S10", p, det, out)
        if out and out[-1]["code"] == c and out[-1]["sig"] == "S10":
            out[-1]["hot"] = hot
            if hot:
                out[-1]["sig_name"] = "绿翻红放量拉升"
        for cb in self.cbs_of(c):
            T_ = self.st.get(cb)
            if not T_ or not T_.win:
                continue
            cp, cpv = T_.win[-1][1], T_.m.get("prev")
            n0 = len(out)
            self._ev(T_, cb, t, "S10", cp, f"正股 {S.m['name']}({c}) {det}; 转债现 {cp:g}" + (f"({(cp / cpv - 1) * 100:+.2f}%)" if cpv else ""), out)
            if len(out) > n0:
                out[-1].update(stock=c, hot=hot, sig_name=f"正股{S.m['name']}绿翻红{'放量' if hot else ''}拉升")

    # ---------- S11 连续跨越 13 档 3 档(10/27 用户: 奥普转债 10:30 正股从绿翻红跨越 3 档时该果断进; 13 档口径同 open_bins, 20cm 外延) ----------
    def _s11(self, S, ctx, out):
        c, t, x, p, v, vw, b, k = ctx
        pv = S.m.get("prev")
        if not pv or t < "09:31:00" or c[:2] in ("11", "12"):
            return
        try:
            import open_bins as OB
        except Exception:   # noqa: BLE001
            sys.path.insert(0, str(ROOT / "scripts" / "skills_ver"))
            import open_bins as OB
        lim = OB.lim_of(c)
        key_ = ("bands", lim)
        if key_ not in _BANDS:   # 本品种实际会出现的档(主板 13 档 / 20cm 外延), 按涨跌幅从低到高; "跨 N 档" 按这张表数, 不按 ORDER 全表
            seq = []
            for i_ in range(-int(lim * 100), int(lim * 100) + 1):
                lb = OB.bin13(i_ / 100, lim)
                if not seq or seq[-1] != lb:
                    seq.append(lb)
            _BANDS[key_] = seq
        bands = _BANDS[key_]
        lab = OB.bin13((p / pv - 1) * 100, lim)
        bi = bands.index(lab) if lab in bands else 0
        z = S.s11
        z["w"].append((x, bi, p))
        while z["w"] and z["w"][0][0] < x - P["S11_LOOK"]:
            z["w"].popleft()
        if z["fired_band"] is not None:
            if bi <= z["fired_band"] - P["S11_REARM"]:
                z["fired_band"] = None   # 跌回 2 档以上 = 重新待命
            return
        if z["n"] >= P["S11_MAX"]:
            return
        lo = min(z["w"], key=lambda r: (r[1], -r[0]))
        if bi - lo[1] < P["S11_BANDS"]:
            return
        dt_ = max(60, x - lo[0])
        sg = S.m.get("sigma") or P["SIGMA_DEFAULT"]
        zz = (p / lo[2] - 1) / (sg * math.sqrt(dt_ / 300))
        if zz < P["S11_Z"]:
            return
        z["fired_band"], z["n"] = bi, z["n"] + 1
        det = f"{dt_ // 60} 分钟内 {bands[lo[1]]} → {bands[bi]}(跨 {bi - lo[1]} 档), {lo[2]:g} → {p:g}(+{(p / lo[2] - 1) * 100:.2f}%, 本票 σ5 {sg * 100:.2f}% 的 {zz:.1f} 倍)"
        self._ev(S, c, t, "S11", p, det, out)
        for cb in self.cbs_of(c):
            T_ = self.st.get(cb)
            if not T_ or not T_.win:
                continue
            cp, cpv = T_.win[-1][1], T_.m.get("prev")
            n0 = len(out)
            self._ev(T_, cb, t, "S11", cp, f"正股 {S.m['name']}({c}) {det}; 转债现 {cp:g}" + (f"({(cp / cpv - 1) * 100:+.2f}%)" if cpv else ""), out)
            if len(out) > n0:
                out[-1].update(stock=c, sig_name=f"正股{S.m['name']}连续跨 3 档")

    # ---------- S12 / S13 墙位翻转(10/28 晚用户批; 只看 3 秒盘口五档, 阈值按本票动态) ----------
    def _wall(self, S, ctx, out):
        """墙 = 某档挂单 ≥ max(WALL_K × 同侧其他档中位, 本票平时 1 分钟成交额 × WALL_AMT_K ÷ 价), 且至少被看见 WALL_SEEN 次(防一闪而过的单);
        涨跌停价上的封单不算(归 S4)。卖墙被成交价越过 = 吃穿; 吃穿后 WALL_FLIP_WIN 秒内回踩到墙价 ~ 墙价 + WALL_NEAR_TICKS 个价位, 且同价买盘也成墙 → S12 转强;
        镜像: 买墙被砸穿后反抽到墙价附近, 同价卖盘成墙 → S13 转弱。同票同价同方向只报一次, 每方向每天 ≤ WALL_MAX 次"""
        c, t, x, p, v, vw, b, k = ctx
        if t < P["WALL_START"] or not b or not k:
            return
        tk = S.m.get("tick") or 0.01
        go = max(P["WALL_GO_TICKS"] * tk, P["WALL_GO_SIGMA"] * (S.m.get("sigma") or P["SIGMA_DEFAULT"]) * p)   # 穿过去要走出去这么远才算真突破
        up, dn = S.m.get("up"), S.m.get("dn")
        floor_amt = (S.m.get("amt1") or 0) * P["WALL_AMT_K"]
        W = S.wall

        def need(levels, px):
            oth = [float(vv) for pp, vv in levels if pp and vv and abs(pp - px) > tk / 2]
            med = statistics.median(oth) if oth else 0.0
            return max(P["WALL_K"] * med, floor_amt / px if px else 0.0), med

        def vol_at(levels, px):
            return next((float(vv) for pp, vv in levels if pp and abs(pp - px) < tk / 2), 0.0)

        for side, lv in (("ask", k), ("bid", b)):
            for pp, vv in lv:
                if not pp or not vv or (up and pp >= up - tk / 2) or (dn and pp <= dn + tk / 2):
                    continue
                nd, med = need(lv, pp)
                if nd > 0 and vv >= nd:
                    z = W[side].get(round(pp, 4))
                    if z:
                        z.update(cnt=z["cnt"] + 1, mx=max(z["mx"], vv), x=x)
                    else:
                        W[side][round(pp, 4)] = {"cnt": 1, "mx": float(vv), "t": t, "x": x, "x0": x, "ref": med}
            for L, z in list(W[side].items()):
                if x - z["x"] > P["WALL_KEEP"]:
                    del W[side][L]
                elif z["cnt"] >= P["WALL_SEEN"] and z["x"] - z["x0"] >= P["WALL_AGE"] and ((side == "ask" and p >= L + tk - 1e-9) or (side == "bid" and p <= L - tk + 1e-9)):
                    W["brk"].append({"side": side, "L": L, "xb": x, "tb": t, "w": z, "ext": p})
                    del W[side][L]
        cb = c[:2] in ("11", "12")

        def fm(vv, px):
            return (f"{vv / 100:.0f} 手" if not cb else f"{vv:.0f}") + f"(约 {vv * px / 1e4:.0f} 万)"

        for z in list(W["brk"]):
            if x - z["xb"] > P["WALL_FLIP_WIN"]:
                W["brk"].remove(z)
                continue
            L, near, ask = z["L"], P["WALL_NEAR_TICKS"] * tk, z["side"] == "ask"
            z["ext"] = max(z["ext"], p) if ask else min(z["ext"], p)   # 穿过之后走到的最远处
            if abs(z["ext"] - L) < go or x - z["xb"] < P["WALL_GAP"]:
                continue
            if ask and not (L - tk / 2 <= p <= L + near + 1e-9):
                continue
            if not ask and not (L - near - 1e-9 <= p <= L + tk / 2):
                continue
            lv = b if ask else k
            vol = vol_at(lv, L)
            nd, med = need(lv, L)
            if nd <= 0 or vol < nd:
                continue
            sig = "S12" if ask else "S13"
            W["brk"].remove(z)
            if (sig, L) in W["fired"] or W["n"][sig] >= P["WALL_MAX"]:
                continue
            W["fired"].add((sig, L))
            W["n"][sig] += 1
            w = z["w"]
            det = (f"{w['t'][:8]} {L:g} {'卖' if ask else '买'}墙 最大 {fm(w['mx'], L)}(同侧其他档中位 {fm(w['ref'], L)}) → {z['tb'][:8]} 被{'吃' if ask else '砸'}穿 → "
                   f"最远 {z['ext']:g} → {t[:8]} {'回踩' if ask else '反抽'}到 {p:g}, {L:g} {'买' if ask else '卖'}盘挂 {fm(vol, L)}(同侧其他档中位 {fm(med, L)}) = "
                   + ("转强: 阻力变支撑" if ask else "转弱: 支撑变阻力"))
            self._ev(S, c, t, sig, p, det, out)

    # ---------- D1~D3 低吸(10/26 用户批; 只是盘面事实, 参数按本票波动 / 振幅动态) ----------
    def _dip(self, S, ctx, out):
        c, t, x, p, v, vw, b, k = ctx
        z = S.d
        z["hi"] = p if z["hi"] is None else max(z["hi"], p)
        if t < P["D_START"]:
            return
        tk = S.m["tick"]
        # D1 跌破均价后企稳: 跌到均价下方 ≥ D1_K × σ5, 之后 D1_HOLD 秒不创新低、离低点反弹 ≥2 个价位、仍在均价下方
        if vw:
            d1 = z["d1"]
            if p <= vw * (1 - P["D1_K"] * S.m["sigma"]) and not z.get("d1_wait"):
                if d1 is None or p < d1["L"]:
                    z["d1"] = d1 = {"L": p, "tL": x, "tLs": t}
            elif p >= vw:
                z["d1"] = d1 = None   # 回到均价上方 = 这一段结束
                z["d1_wait"] = False   # 10/28: 报过一次后要先回到均价上方, 下一次跌破才算"第二次回踩"(冷却缩到 3 分钟, 防同一段反复报)
            if d1 and x - d1["tL"] >= P["D1_HOLD"] and p >= d1["L"] + max(2 * tk, P["D_BOUNCE_K"] * S.m["sigma"] * p) and p < vw:
                self._ev(S, c, t, "D1", p, f"{d1['tLs']} 跌到 {d1['L']:g}(均价下方 {(1 - d1['L'] / vw) * 100:.2f}%, 阈 {P['D1_K']:g}×σ5={P['D1_K'] * S.m['sigma'] * 100:.2f}%), {x - d1['tL']} 秒没创新低, 现 {p:g} 均价 {vw:.3f}", out)
                if out and out[-1]["sig"] == "D1":
                    out[-1]["low"] = d1["L"]
                z["d1"] = None
                z["d1_wait"] = True
        # D2 冲高回落到开盘价: 当天出过 S7 冲高到位, 回落到开盘价 ±D2_BAND 内并守住 D2_HOLD 秒(没跌破下沿)
        if "S7" in S.done and S.open:
            lo, hi = S.open * (1 - P["D2_BAND"]), S.open * (1 + P["D2_BAND"])
            d2 = z["d2"]
            if p < lo:
                z["d2"] = None
            elif p <= hi and d2 is None:
                z["d2"] = d2 = {"t0": x, "t0s": t}
            elif d2 and p > hi * (1 + P["D2_BAND"]):
                z["d2"] = d2 = None   # 已经弹走了, 不算守住
            if d2 and x - d2["t0"] >= P["D2_HOLD"] and "D2" not in S.done:
                S.done.add("D2")
                self._ev(S, c, t, "D2", p, f"冲高到位后 {d2['t0s']} 回落到开盘价 {S.open:g} ±{P['D2_BAND'] * 100:.1f}%, 守住 {x - d2['t0']} 秒没跌破, 现 {p:g}", out)
                z["d2"] = None
        # D3 回撤到振幅位企稳: 从日内最高回撤 ≥ D3_K × 本票 30 日振幅中位, 之后 D3_HOLD 秒不创新低、反弹 ≥2 个价位
        amp = S.m.get("amp30")
        if amp and z["hi"]:
            d3 = z["d3"]
            if (z["hi"] - p) / z["hi"] >= P["D3_K"] * amp:
                if d3 is None or p < d3["L"]:
                    z["d3"] = d3 = {"L": p, "tL": x, "tLs": t, "H": z["hi"]}
            if d3 and x - d3["tL"] >= P["D3_HOLD"] and p >= d3["L"] + max(2 * tk, P["D_BOUNCE_K"] * S.m["sigma"] * p):
                self._ev(S, c, t, "D3", p, f"日内最高 {d3['H']:g} 回撤到 {d3['L']:g}({d3['tLs']}, −{(1 - d3['L'] / d3['H']) * 100:.2f}%, 阈 {P['D3_K']:g}×30 日振幅中位 {amp * 100:.2f}%), {x - d3['tL']} 秒没创新低, 现 {p:g}", out)
                if out and out[-1]["sig"] == "D3":
                    out[-1]["low"] = d3["L"]
                z["d3"] = None
                z["hi"] = p   # 重新从这里算下一次回撤


# ================================================================ 节流 + 推送
class Throttle:
    """同票同信号 DEDUP_MIN 分钟(事件时间)内只记一次"""
    def __init__(self):
        self.last = {}
        self.low = {}   # 10/26: D1 / D3 上次报的低点
        self.nth = {}   # 10/28: 低吸类同票同信号今天第几次

    def ok(self, e):
        key, x = (e["code"], e["sig"]), secs(e["t"])
        if e["sig"] in ("S4p", "S4c"):   # 10/26: 每次开板 / 每次冲击都要报, 检测器自己限频
            return True
        if e["sig"] in ("D1", "D2", "D3", "S2"):
            # 10/28 12:4x 用户: 5~30 分钟冷却太长, 要看到首次 / 二次回踩 —— 低吸类同票同信号间隔 3 分钟(指数共振窗口里 1 分钟), 不要求更低的低点; 每天每票每信号 ≤4 次, 带"第 N 次"
            gap = 60 if res_on(e["t"]) else 180
            if key in self.last and x - self.last[key] < gap:
                return False
            self.nth[key] = self.nth.get(key, 0) + 1
            if self.nth[key] > 4:
                return False
            e["nth"] = self.nth[key]
        elif e["sig"] in ("D1", "D3") and key in self.last:
            # 10/26 14:5x 用户(鼎捷转债 14:39 均价下方企稳没推): 同票低吸 90 分钟一次会漏掉"更低的第二个低点" →
            # 30 分钟后, 这次的低点比上次报的低点更低(新的一段下跌后企稳)就再报; 否则仍按 90 分钟
            dt_ = x - self.last[key]
            lo, lo0 = e.get("low"), self.low.get(key)
            if dt_ < P["DEDUP_MIN"] * 60 or (dt_ < P["DEDUP_D_MIN"] * 60 and not (lo and lo0 and lo < lo0)):
                return False
        elif key in self.last and x - self.last[key] < (P["DEDUP_D_MIN"] if e["sig"] == "D2" else P["DEDUP_MIN"]) * 60:
            return False
        self.last[key] = x
        if e.get("low"):
            self.low[key] = e["low"]
        return True


def line(e):
    pc = f"({e['pct']:+.2f}%)" if e.get("pct") is not None else ""
    return f"{e['name']}({e['code']}) {e['sig']} {e['sig_name']} {e['t'][:5]} 价 {e['px']:g}{pc}"


def cat_of(e):
    """类别: SIG_CAT 默认; S8 蓄势按离涨停远近 —— 离涨停 ≤ 2%(20cm 按比例 4%) 才算【板】, 更远是【蓄势】(10/28 大业股份 +2.8% 离板 6.6% 被标【板】)"""
    em, cat = SIG_CAT.get(e["sig"], ("•", e["sig"]))
    if e["sig"] == "S8" and e.get("to_up") is not None and e["to_up"] < -2.0 * (e.get("lim") or 10) / 10:
        return "🟠", "蓄势"
    return em, cat


SIG_EMOJI = {"S8": "🔋", "S9": "⏰", "D1": "🔴🛬", "D2": "🔴↩️", "D3": "🔴🪂", "S1": "📈", "S2": "➖", "S3": "🔼", "S4a": "💥", "S4p": "⤴️", "S4c": "⚡", "S4b": "🔁", "S5": "🌇", "S6": "🎯", "S7": "🚀", "S10": "🟥↗", "S11": "🪜", "S12": "🧱↗", "S13": "🧱↘", "D4": "🩸", "D5": "🔓", "R1": "🌊"}
SIG_CAT = {   # 10/28 13:0x 用户定类别(一个 emoji + 【类别】, 不用两个 emoji 连写): 低吸 / 追涨 / 板 / 炸板 / 炸板有希望回封 / 冲高回落 / 深V拉升 / 共振, 我补 冲高到位 / 尾盘 / 竞价
    "D1": ("🔵", "低吸"), "D3": ("🔵", "低吸"), "S2": ("🔵", "低吸"),
    "D2": ("🟢", "冲高回落"),           # 冲高到位后回落到开盘价守住(既是冲高回落, 也是开盘价低吸位)
    "S10": ("🔴", "追涨"), "S11": ("🔴", "追涨"),
    "S1": ("🟣", "深V拉升"),            # 急跌后拉起
    "S4c": ("⚡", "板"), "S8": ("⚡", "板"), "S9": ("⚡", "板"),   # 冲击涨停 / 蓄势预警 / 午后冲板候选
    "S4a": ("💥", "炸板"),
    "S4b": ("🔁", "炸板有希望回封"), "S4p": ("🔁", "炸板有希望回封"),
    "S7": ("🚀", "冲高到位"), "S3": ("🚀", "冲高到位"),   # 开盘冲高到位 / 二次冲高: 持仓的卖点参考
    "S5": ("🌇", "尾盘"), "S6": ("🎯", "竞价"), "R1": ("🌊", "共振"),
    "S12": ("🔺", "转强"), "S13": ("🔻", "转弱"), "D4": ("🔵", "低吸"), "D5": ("🔵", "低吸")}   # 10/28 晚用户批: 墙位翻转 = 转强 / 转弱提醒
_WHY = {"t": 0.0, "map": {}, "seen": set()}


def watch_why(D):
    """10/26 用户: 推送里新增的盯盘票要有 emoji 标识 + 为什么在盯 —— 读各线 must_state.json 的 watch 来源标签(60 秒缓存)"""
    if time.time() - _WHY["t"] < 60:
        return _WHY["map"]
    m = {}
    for f in [*(LIVE / D).glob("live_*/must_state.json"), *(LIVE / D).glob("paper_*/must_state.json")]:
        try:
            w = json.loads(f.read_text(encoding="utf-8")).get("watch") or {}
        except (OSError, ValueError):
            continue
        for c, v in (w.items() if isinstance(w, dict) else [(x, []) for x in w]):
            for r in v or []:
                r = str(r)
                k = "候选池" if "候选池" in r else "导师操作" if "导师T" in r else "UP提到" if "UP" in r else "持仓" if "持仓" in r else "盘前提到" if "盘前" in r else "电报点名" if "电报" in r else r[:8]
                m.setdefault(str(c), set()).add(k)
    for c in extra_codes():
        m.setdefault(c, set()).add("你点名")
    _WHY.update(t=time.time(), map=m)
    return m


KEY_TAGS = ("持仓", "你点名")   # 10/26 晚用户定: 低吸 / 炸板类 + 持仓 + 点名 = 快车道(利益相关); 回踩均价(S2)延迟攒批; 其余盯盘池的票攒批带冷却


def is_key(code, D):
    """重点票 = 持仓 / UP 提到 / 导师操作 / 发哥提到 / 用户点名(必查池来源标签)"""
    tags = watch_why(D).get(code) or set()
    return any(t in KEY_TAGS for t in tags)


def compose(evs, D, hold):
    """合并成一条: 持仓在前, 同组按时间; 最多 MAX_LINES 行; 10/26: 每条带信号 emoji, 当天第一次推的盯盘票标 🆕 + 进盯盘原因"""
    hs = sorted([e for e in evs if e["code"] in hold], key=lambda e: e["t"])
    ot = sorted([e for e in evs if e["code"] not in hold and not e.get("pool")], key=lambda e: e["t"])
    vs = sorted([e for e in evs if e["code"] not in hold and e.get("pool")], key=lambda e: e["t"])
    why = watch_why(D)
    L, n = [f"分时信号 {dt.datetime.now():%H:%M}"], 0   # 10/26 用户: "同票 30 分钟只报一次 / 盘面事实不是买卖建议"已知, 不推(省字数)
    for title, grp in (("💼 持仓:", hs), ("👀 盯盘票:", ot), ("🔭 盯盘池(触发盯盘条件进池的股票 / 转债):", vs)):
        if not grp:
            continue
        L.append(title)
        for e in grp:
            if n >= P["MAX_LINES"]:
                break
            em, cat = cat_of(e)
            s = f"{em}【{cat}】{line(e)}"
            if e["sig"] == "R1":
                s = f"{em}【{cat}】指数共振低点 {e['t'][:5]}: {e['detail']}"
            if e.get("nth"):
                s += f"〔第 {e['nth']} 次〕"
            o = e.get("odds")
            if o and o.get("p") is not None:
                s += f"〔历史+{o['tgt']:g}% 盈利率 {o['p'] * 100:.0f}% n{o['n']}〕"
            if e["sig"] in ("D1", "D2", "D3") and "此刻 " in (e.get("detail") or ""):   # 10/28: 低吸带上大盘此刻(普跌日低吸到收盘中位 −1.8%)
                s += f"〔{e['detail'].rsplit('此刻 ', 1)[1]}〕"
            if e["code"] not in hold and e["code"] not in _WHY["seen"] and not e.get("pool"):
                s = f"{s} 〔新进盯盘: {'/'.join(sorted(why.get(e['code']) or [])) or '来源不明'}〕"   # 10/28: 去掉 🆕, 一行只留一个 emoji
            _WHY["seen"].add(e["code"])
            L.append(s)
            n += 1
    if len(evs) > n:
        L.append(f"另 {len(evs) - n} 条见 results/_live/{D}/signals.jsonl")
    return "\n".join(L)


class Pusher:
    def __init__(self, D, hold_fn, dry=False):
        self.D, self.hold_fn, self.dry = D, hold_fn, dry
        self.ratio = 2.0          # 10/27 晚用户: 股票推送约是转债的 2 倍, 按两边活跃只数动态(run 每分钟按 Picker 选中的 股票 / 转债 只数更新, 夹在 1~3)
        self._pushed = collections.deque()   # (time, 是转债)
        self._cb_day, self._t0 = 0, time.time()   # 今天累计推的转债条数 / 开始时刻(算每小时平均, 当股票配额的底)
        self.pending, self.lock, self.busy = [], threading.Lock(), False
        self.sf = LIVE / D / "signals_push.json"
        try:
            self.last_push = json.loads(self.sf.read_text(encoding="utf-8")).get("last_push", 0.0)
        except (OSError, ValueError):
            self.last_push = 0.0

    def add(self, e):
        with self.lock:
            self.pending.append(e)

    def _balance(self, rest, hold):
        """10/27 晚用户: 股票:转债 推送 ≈ ratio:1(ratio 动态 = Picker 当前选中的股票只数 / 转债只数, 夹 1~3); 只管普通通道里非持仓的股票 ——
        近 60 分钟已推股票 > ratio × max(1, 已推转债) 时, 这批普通股票只记不推(signals.jsonl 照记); 转债不受限"""
        now_ = time.time()
        while self._pushed and now_ - self._pushed[0][0] > 3600:
            self._pushed.popleft()
        n_cb = sum(1 for _, cb in self._pushed if cb)
        n_st = len(self._pushed) - n_cb
        if self.ratio is None:   # Picker 没选中任何转债 = 今天没转债可看, 不限股票
            return rest
        cb_avg = self._cb_day / max(1.0, (now_ - self._t0) / 3600)   # 今天每小时平均转债推送, 防"这一小时刚好没转债信号就把股票全压住"
        out = []
        for e in rest:
            is_cb = e["code"][:2] in ("11", "12")
            if not is_cb and e["code"] not in hold and n_st >= self.ratio * max(1, n_cb, cb_avg):
                continue
            self._cb_day += is_cb
            out.append(e)
            n_cb += is_cb
            n_st += not is_cb
            self._pushed.append((now_, is_cb))
        return out

    def _cool_ok(self, e):
        """动态冷却(只管普通 / 慢通道推送; 10/26 20:0x 用户批): 同票同信号第 n 次推 要距上次 ≥ CD_BASE × 2^(n−1) 分钟(封顶 CD_MAX);
        同一只票 CD_CODE_WIN 分钟内已推 ≥ CD_CODE_N 次普通信号 → 这段时间不再推它(signals.jsonl 照记, 只是不推)"""
        now_, k = time.time(), (e["code"], e["sig"])
        pc = self.__dict__.setdefault("_pc", {})
        hist = self.__dict__.setdefault("_ph", collections.defaultdict(list))
        n, last = pc.get(k, (0, 0.0))
        if n and now_ - last < min(P["CD_MAX_MIN"], P["CD_BASE_MIN"] * 2 ** (n - 1)) * 60:
            return False
        h = [t for t in hist[e["code"]] if now_ - t < P["CD_CODE_WIN_MIN"] * 60]
        if len(h) >= P["CD_CODE_N"]:
            hist[e["code"]] = h
            return False
        pc[k] = (n + 1, now_)
        hist[e["code"]] = h + [now_]
        return True

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
            key = {e["code"] for e in evs if is_key(e["code"], self.D)} | {e["code"] for e in evs if e["code"] in hold}   # 持仓 + 你点名 = 快车道
            # 10/26 20:0x 用户: 快车道 = 快信号(低吸 / 炸板 / 回封类 / S1 / S7 / S8 / S9)或 持仓 / 点名票; 其余分 普通 / 慢(只有回踩均价 S2), 两条都动态攒批 + 动态冷却
            # 10/28 13:0x 用户: 通道按统计期望分(历史盈利率 p = 信号价买入摸到目标价的比例, 见 odds_gate): p ≥ 50% 快车道 / 35~50% 普通(动态攒批 15 秒~3 分钟 + 动态冷却) / 25~35% 慢通道(3~10 分钟攒一批); <25% 已在闸里只记不推
            # 例外: 持仓 / 你点名 / 指数共振 一律快车道; 板类(炸板 / 回封 / 冲板)抢的是秒级, 最慢走普通不进慢通道
            fast_p, norm_p = float(_flag("SIG_LANE_FAST", "0.5")), float(_flag("SIG_LANE_NORM", "0.35"))

            def lane(e):
                if e["code"] in key or e["sig"] == "R1":
                    return "fast"
                pz = (e.get("odds") or {}).get("p")
                pz = 0.0 if pz is None else pz
                ln = "fast" if pz >= fast_p else "norm" if pz >= norm_p else "slow"
                return "norm" if ln == "slow" and e["sig"] in ("S4a", "S4b", "S4p", "S4c") else ln
            for e in evs:
                e["lane"] = lane(e)
            fe = [e for e in evs if e["lane"] == "fast"]
            ne = [e for e in evs if e["lane"] == "norm" and self._cool_ok(e)]
            se = [e for e in evs if e["lane"] == "slow" and self._cool_ok(e)]
            self._pushed.extend((time.time(), e["code"][:2] in ("11", "12")) for e in fe)   # 快车道推出去的也计入比例
            self._cb_day += sum(1 for e in fe if e["code"][:2] in ("11", "12"))
            ne, se = self._balance(ne, hold), self._balance(se, hold)
            if fe:
                PB.enqueue(compose(fe, self.D, hold), src="live_signal", urgent=True, fast=True, D=self.D)
            if ne:
                PB.enqueue(compose(ne, self.D, hold), src="live_signal", D=self.D)
            if se:
                PB.enqueue(compose(se, self.D, hold), src="live_signal", slow=True, D=self.D)
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
    return out | v3_holds(D) | real_holds() | extra_codes()


def _flag(k, d=""):
    """chain_flags.txt 开关(k=v, # 注释)"""
    try:
        for l in (ROOT / "scripts" / "claude_profile" / "chain_flags.txt").read_text(encoding="utf-8").splitlines():
            kk, _, v = l.split("#")[0].partition("=")
            if kk.strip() == k:
                return v.strip()
    except OSError:
        pass
    return os.environ.get(k, d)


def extra_codes():
    """10/26 用户点名加的票(scripts/temp/collect_book_extra.txt, 和 3 秒盘口池同一份)也出信号"""
    try:
        t = (ROOT / "scripts" / "temp" / "collect_book_extra.txt").read_text(encoding="utf-8")
    except OSError:
        return set()
    try:   # 10/28 用户: 手动点名超过 2 个交易日自动退出(和 3 秒盘口同一口径 collect_book.extra_split)
        sys.path.insert(0, str(ROOT / "scripts" / "market"))
        import collect_book as CBK
        return CBK.extra_split(t, dt.date.today().isoformat())[0]
    except Exception:   # noqa: BLE001
        return set(re.findall(r"(?<!\d)\d{6}(?!\d)", t))


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
    D_NOW["D"] = D
    state = {"want": fixed or watch_codes(D), "at": time.time(), "hold": v3_holds(D) | real_holds()}

    def refresh():
        if time.time() - state["at"] > 60:
            state.update(at=time.time(), hold=v3_holds(D) | real_holds())
            if not fixed:
                state["want"] = watch_codes(D)

    pool_on = (_flag("SIG_POOL", _flag("SIG_VISION", "1")) == "1") and not fixed   # 盯盘池: 盘口池里不在名单、触发盯盘条件的股票(转债另走 Picker 名额), 只出 POOL_SIGS, 走普通通道 + 动态冷却
    is_stock = lambda c: str(c)[:2] not in ("11", "12") and str(c)[:1] in ("0", "3", "6")   # noqa: E731
    vis = {"st": set(), "cb": set()}
    keep_of = lambda: state["hold"] | extra_codes()   # noqa: E731  持仓 / 点名: 不占名额、一直在

    def emit_ok(c):
        if c in keep_of():
            return True
        if not pool_on:
            return c in state["want"]
        if c[:2] in ("11", "12"):
            return c in vis["cb"]   # 名单里的转债: 只看 Picker 挑出来的 10~20 只
        return c in state["want"] or c in vis["st"]
    det = Detector(D, meta, emit=None if all_ else emit_ok)
    det.must = lambda c: c in state["want"] or c in keep_of()   # 10/27 S10 必须提醒: 名单 / 持仓 / 点名(含转债)不受 Picker 名额限制
    picker = Picker(det, meta)
    zb = set()   # 今天炸过板的盯盘池票(之后的 D1 / D3 = 炸板回踩低吸)
    th = Throttle()
    out_f = LIVE / D / "signals.jsonl"
    try:   # 10/26: 重启后 🆕 标识不重复 —— 今天已推过信号的票算"见过"
        _WHY["seen"] |= {json.loads(l)["code"] for l in out_f.read_text(encoding="utf-8").splitlines() if l.strip() and not json.loads(l).get("stale")}
    except (OSError, ValueError, KeyError):
        pass
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
            if e["code"] not in state["want"]:
                if e["sig"] == "S4a":
                    zb.add(e["code"])
                if not (e["sig"] in P["POOL_SIGS"] or (e["sig"] in P["POOL_DIP_AFTER_ZB"] and e["code"] in zb)):
                    continue
                if e["sig"] == "S10" and not e.get("hot"):
                    continue   # 10/27: 盘口池里不在名单的票, 翻红只报放量的(10/27 回放全池 79 条 / 天, 放量约一半)
                e["pool"] = True
            key = (e["code"], e["sig"], e["t"])
            if key in seen or not th.ok(e):
                continue
            picker.note(e["code"], trs(e["t"]))
            seen.add(key)
            e["hold"] = e["code"] in state["hold"]
            passed = odds_gate(e) or e["hold"]   # 10/28 用户: 统计期望闸(历史盈利率 ≥25% 才推); 你的持仓照推(卖点信息)
            if not passed:
                e["gated"] = True
            stale = secs(now_hm) - secs(e["t"]) > P["STALE_MIN"] * 60
            if stale:
                e["stale"] = True
            with out_f.open("a", encoding="utf-8") as w:
                w.write(json.dumps(e, ensure_ascii=False) + "\n")
            if not stale and passed:
                pusher.add(e)
    try:
        while True:
            hm = dt.datetime.now().strftime("%H:%M:%S")
            if hm > "15:00:30":
                break
            refresh()
            if not fixed and _flag("SIG_RES", "1") == "1":   # 10/28 用户: 指数共振低点 R1 —— 一次列出此刻在均价下方的盯盘 / 盯盘池 / 持仓票
                try:
                    info = res_check(D, hm)
                except Exception as e_:   # noqa: BLE001
                    info = None
                    print(f"[signals] 共振检测失败 {e_!r}", file=sys.stderr, flush=True)
                if info:
                    cand = state["want"] | vis["st"] | vis["cb"] | keep_of()
                    rows_ = []
                    for c_, S_ in det.st.items():
                        vw_ = getattr(S_, "vw_now", None)
                        if c_ in cand and S_.win and vw_:
                            dev = S_.win[-1][1] / vw_ - 1
                            if dev <= -max(0.003, S_.m.get("sigma") or 0.005):
                                rows_.append((dev, c_, S_))
                    rows_.sort()
                    lst = "、".join(f"{S_.m['name']}({c_}) 均价下 {dev * 100:.1f}%" for dev, c_, S_ in rows_[:10])
                    e = {"t": hm, "code": "000001", "name": "指数共振", "sig": "R1", "sig_name": NAMES["R1"], "px": 0,
                         "detail": f"{info}; 此刻均价下方 {len(rows_)} 只" + (f": {lst}" if lst else ""), "hold": False}
                    with out_f.open("a", encoding="utf-8") as w:
                        w.write(json.dumps(e, ensure_ascii=False) + "\n")
                    pusher.add(e)
            if not fixed and not dry and "09:25:45" <= hm <= "09:29:30" and not state.get("auction_pushed") and _flag("AUCTION_PUSH", "1") == "1":   # 10/28: 竞价结果推送(auction_push.py), 一天一次
                state["auction_pushed"] = True
                if not (LIVE / D / "auction_result.md").exists():
                    def _ap():
                        try:
                            sys.path.insert(0, str(ROOT / "scripts" / "live"))
                            import auction_push as AUP
                            AUP.run(D)
                        except Exception as e_:   # noqa: BLE001
                            print(f"[signals] 竞价结果推送失败 {e_!r}", file=sys.stderr, flush=True)
                    threading.Thread(target=_ap, daemon=True).start()
            if pool_on:
                xs = [S_.x_last for S_ in list(det.st.values())[:50] if getattr(S_, "x_last", None)]
                if xs:
                    vis["st"], vis["cb"] = picker.pick(state["want"], keep_of(), max(xs))
                    pusher.ratio = max(1.0, min(3.0, len(vis["st"]) / len(vis["cb"]))) if vis["cb"] else None   # 10/27 晚: 股票:转债 推送比例跟两边活跃只数走
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
            time.sleep(1)   # 10/26: 3→1 秒, 回封预警少等 2 秒
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
