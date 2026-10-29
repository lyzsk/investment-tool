# -*- coding: utf-8 -*-
"""collect_book.py — 盘口五档快照采集(10/18 晚用户定 P3: 给 QI / DI / OFI 攒数据; 零 token)

源: 新浪 hq.sinajs.cn 五档(批量, 一次请求带全部票) —— 特意不用腾讯: 撮合 / 盯盘已在用腾讯 qt, 腾讯约 1.6 次/秒会封, 分开源互不抢额度
节奏: 09:14~15:01 每 3 秒一次(≈0.33 次/秒); 同一只票快照时间没变(新浪约 3 秒刷新一次)就不重复写
名单(约 40 只, 每 10 分钟刷新): 做 T 账本标的 + paper 各账本持仓 / 未成交挂单 + 当日计划单 + 用户实盘持仓(snapshots 最近一次导出)
存储: downloads/market/<日>/book_snap.jsonl(盘中追加, 一行 = 一只票一个快照), 收盘后压成 book_snap.jsonl.gz; 每天约 30MB 原始 / 5MB 压缩
  字段: s 代码, t 时间, p 现价, v 累计量(股), a 累计额(元), b [[买1价,量],...买5], k [[卖1价,量],...卖5]
启动: check md --only mix(每 5 分钟)调 --ensure: 没在跑且在时段内 → 后台拉起(无窗口); 挂了下一轮自动重拉; pid 锁防双开
失败: 单次请求失败指数退避(3s→最多 60s), 不抛出; 连续失败 20 次写日志继续等; 永不影响撮合 / 盯盘
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/market/collect_book.py --ensure | --run | --gzip [--date D]
"""
import argparse
import datetime as dt
import glob
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"
PAPER = ROOT / "scripts" / "dfcf" / "paper"
LOCK = ROOT / "scripts" / "temp" / "collect_book.pid"
LOG = ROOT / "scripts" / "temp" / "collect_book.log"
START, END, STEP, MAXN = "0914", "1501", 3.0, 300   # 10/28 12:4x 用户令扩大盯盘范围: 200 → 300(10/24 压测 300 只 0.28 秒无错)   # 10/24 用户: 以压测为准(300 只 0.28 秒无错), 60 → 200 留余量
FILL_TO, POOL_TOP = 300, 30   # 10/25: 150 → 200(用户定 3 秒盘口 200 只, 压测 300 只 0.28 秒无错; 空余名额给主线题材成员 + 转债); 10/24: 50/5 → 150/30(候选池 30 → 100 行, 每本前 30 名进 3 秒盘口);   # 10/23 用户令: 恒定录 50 只, 分 6 档(T0 执行要用的 / T1 转债正股 / T2 导师昨日持仓与成交 / T3 v3 候选池前 5 / T4 昨日连板梯队 / T5 拓扑邻居与其余), 连续失败每 3 次从最低档砍一档
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import ipv4_first   # noqa: E402,F401  10/21: 本机 IPv6 不通, 先走 IPv4


def log(*a):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{dt.datetime.now():%m-%d %H:%M:%S}] " + " ".join(str(x) for x in a) + "\n")


def sym(code):
    try:
        import a_rules as AR
        return AR.symbol(code)
    except Exception:   # noqa: BLE001
        return ("sh" if code[0] in "569" else "sz") + code


EXTRA = set()   # 手动加录名单(scripts/temp/collect_book_extra.txt), watch() 每次刷新
EXPIRED = set()   # 10/28 用户: 手动点名超过 2 个交易日(且不是持仓)→ 降到最低档(池满先让位), 不删文件


def prev_tdays(D, n):
    """D 之前 n 个交易日(按 downloads/market 有数据的日子)"""
    ds = sorted(p.name for p in (ROOT / "downloads" / "market").iterdir() if p.is_dir() and re.fullmatch(r"20\d\d-\d\d-\d\d", p.name) and p.name < D)
    return ds[-n:]


def extra_split(text, D, n=2):
    """→ (有效, 过期): 自动段(# >>> … # <<<)每天重生成, 一律有效; 手动行注释带 MM/DD 日期, 早于 D 前第 n 个交易日 = 过期; 没日期 = 有效"""
    pv = prev_tdays(D, n)
    cut_d = pv[0] if len(pv) == n else "0000-00-00"
    act, exp, auto = set(), set(), False
    for l in text.splitlines():
        if l.startswith("# >>>"):
            auto = True
        elif l.startswith("# <<<"):
            auto = False
        cs = re.findall(r"(?<!\d)\d{6}(?!\d)", l.split("#")[0])
        if not cs:
            continue
        m = re.search(r"#\s*(\d{1,2})/(\d{1,2})", l)
        if not auto and m and f"{D[:4]}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" < cut_d:
            exp.update(cs)
        else:
            act.update(cs)
    return act, exp


def live_codes(D, stk):
    """10/28 用户令「盘中自动」档: 实时涨停池 + 炸板池(mood.jsonl 最新一行, 财联社每分钟) + 每只的拓扑前 3 邻居(主 / 次簇) + 它们的转债"""
    out = []
    try:
        ls = (ROOT / "downloads" / "market" / D / "mood.jsonl").read_text(encoding="utf-8").strip().splitlines()
        m = json.loads(ls[-1]) if ls else {}
        hot = [str(x[0]) for x in (m.get("up") or [])] + [str(x[0]) for x in (m.get("zb_list") or [])]
    except (OSError, ValueError, IndexError, TypeError):
        return out
    cb_of = {v: k for k, v in (stk or {}).items() if v}
    out += hot + [cb_of[c] for c in hot if c in cb_of]   # 顺序 = 优先级: 涨停 / 炸板本身 → 它们的转债 → 拓扑邻居 → 邻居的转债(池满从后面砍)
    nb = []
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "market"))
        import topology as TOPO
        for c in hot:
            nb += [x["c"] for x in ((TOPO.load(c, D, strict=True) or {}).get("nb") or [])[:3]]
    except Exception:   # noqa: BLE001
        pass
    out += nb + [cb_of[c] for c in nb if c in cb_of]
    return list(dict.fromkeys(out))


def watch(D):
    codes = {"601988", "159941"}   # 做 T 账本标的(10/23 去掉牧原 002714: 用户 10/20 已清仓, 牧原三本账跟随实盘不再做 T; 实盘持仓由下面 snapshots 导出自动加)
    real = set()   # 用户实盘成交里出现过的票
    for f in (PAPER / "books").glob("*.json"):
        if f.name.startswith("_"):   # 10/23: _void_* = 作废归档的旧账本(如 10/03 作废的桃哥账里还有牧原 1200 股), 不进名单
            continue
        try:
            b = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        codes |= set((b.get("positions") or {}).keys())
        codes |= {str(o.get("code")) for o in b.get("orders") or [] if o.get("status") == "open"}
    for f in glob.glob(str(PAPER / "plans" / f"{D}_*.md")):
        codes |= set(re.findall(r"\|\s*(?:BUY|SELL)\s*\|\s*(\d{6})\s*\|", Path(f).read_text(encoding="utf-8")))
    try:
        sys.path.insert(0, str(PAPER))
        import t_bot as TB
        for f in TB._snap_files()[-1:]:
            for l in f.read_text(encoding="utf-8").splitlines():
                t = l.split()
                if len(t) >= 5 and t[0].isdigit() and len(t[0]) <= 3 and len(t[1]) == 6 and t[1].isdigit():
                    codes.add(t[1])
                    real.add(t[1])
    except Exception:   # noqa: BLE001
        pass
    try:   # 10/21 用户: 转债要连正股一起录(澳弘转债在名单、澳弘电子不在, 复盘没有正股盘口) + 手动加录名单 scripts/temp/collect_book_extra.txt
        metas = sorted(glob.glob(str(ROOT / "downloads" / "quotes" / "cb" / "meta" / "RPT_BOND_CB_LIST_all_*.json")))
        if metas:   # 10/23: 不再要求 codes 里已有转债(v3 的转债只在执行器策略里, 下面 se 段才加进来)
            m = json.loads(Path(metas[-1]).read_text(encoding="utf-8"))
            rows = m if isinstance(m, list) else ((m.get("result") or {}).get("data") or m.get("data") or [])
            stk = {str(r.get("SECURITY_CODE")): str(r.get("CONVERT_STOCK_CODE") or "") for r in rows}   # 下面 se 段也用
            codes |= {stk[c] for c in list(codes) if stk.get(c, "").isdigit()}
        ex = ROOT / "scripts" / "temp" / "collect_book_extra.txt"
        if ex.exists():
            EXTRA.clear()
            act, exp = extra_split(ex.read_text(encoding="utf-8"), D)
            EXTRA.update(act)
            EXPIRED.clear()
            EXPIRED.update(exp - act)
            codes |= EXTRA
    except Exception:   # noqa: BLE001
        pass
    se = set()   # 10/21 晚: 新 paper 策略执行器(15 条)的持仓 + 当前策略里的票, 优先录(成交要靠 3 秒盘口)
    live = ROOT / "results" / "_live" / D
    for d in [*live.glob("se_*"), *live.glob("v3_*"), *live.glob("live_*"), *live.glob("paper_*")]:   # 10/23 凌晨彩排查出: 原来只读 v2 的 se_*, v3 账本(v3_*)的持仓 / 挂单票进不了 3 秒盘口 → 只能靠新浪 10 秒补价, 没有五档深度和成交量
        try:
            se |= set((json.loads((d / "state.json").read_text(encoding="utf-8")).get("positions") or {}).keys())
            sp = sorted((d / "strategies").glob("*.json"))
            if sp:
                se |= {str(x.get("code")) for x in (json.loads(sp[-1].read_text(encoding="utf-8")).get("strategy") or {}).get("codes") or []}
        except (OSError, ValueError, AttributeError):
            continue
    # 10/23 03:1x 用户令: 恒定录 FILL_TO(50) 只, 不同来源分档定优先级; 请求连续失败时从最低档往上一档一档砍, 永远先保住 T0 持仓
    T0 = set(codes) & ({"601988", "159941"} | real | se)   # T0 执行要用的: 做 T 标的 / 你的实盘持仓 / paper 执行器持仓 + 当前策略里的票
    try:
        T1 = {stk[c] for c in T0 if stk.get(c, "").isdigit()} - T0   # T1 这些转债的正股
        T1 |= EXTRA - T0   # 10/26 用户令: 手动加录名单是用户点名要看的(东百集团 / 国芳集团), 原来落在最低档被 FILL_TO 挤掉 → 提到 T1
    except NameError:
        T1 = set()
    T2 = mentor_hold_codes(D)   # T2 导师真人昨天收盘持仓 + 昨天成交过的
    try:   # 10/28 用户: 导师 T−1 / T−2 都没持有、没操作的票降级 → 排到最低档(池满先让位), 不占 T2
        sys.path.insert(0, str(ROOT / "scripts" / "paper_line" / "tools"))
        import mentor_recent as MR
        _k = {c: e.get("k", 1) for c, e in MR.load(D)["codes"].items()}
        T2_OLD = sorted((c for c in T2 if _k.get(c, 1) > 2), key=lambda c: _k.get(c, 1))   # 回头间隔 P90 以外的 mentor_recent 本来就不给(MR.codes "book" 档)
        T2 = sorted((c for c in T2 if _k.get(c, 1) <= 2), key=lambda c: _k.get(c, 1))   # 10/28 晚用户定: T−1 / T−2 操作过(含清仓)都留; 池满先退 T−2 再退 T−1(名单靠后的先被挤出)
    except Exception:   # noqa: BLE001
        T2_OLD = []
    T3 = v3_pool_codes(D)   # T3 v3 各本账 01 候选池前几名(模型可能临时买)
    try:   # 10/27 晚: 奥普特 09:36 后掉出 3 秒盘口(奥普转债在点名名单, 正股只进了最低档被挤掉) → 名单里所有转债的正股都进 T1(翻红拉升 S10 要靠正股盘口)
        T1 |= {stk[c] for c in (set(codes) | EXTRA | set(T2) | set(T3)) if stk.get(c, "").isdigit()} - T0
    except NameError:
        pass
    try:   # 10/25 用户选 D: 被加红电报点名封板 / 冲板的票进 3 秒盘口(之后开板 / 回封有秒级数据; 不叫醒 chain)
        sys.path.insert(0, str(ROOT / "scripts" / "paper_line" / "tools"))
        import telegraph_now as TGN
        T3 = list(T3) + [c for c in TGN.limit_named(D, time.strftime("%H:%M:%S"))[:20] if c not in set(T3)]
    except Exception:   # noqa: BLE001
        pass
    T4 = ladder_codes(D)   # T4 昨天连板梯队
    try:   # 10/25 用户问福莱新材 / 福莱转债为什么不在 3 秒盘口: 近 5 日最强 2 个主线题材的成员(涨停分析里出现过的) + 它们的转债, 排在梯队后面, 只填空余名额(上限 200 不挤别人)
        sys.path.insert(0, str(ROOT / "scripts" / "paper_line" / "tools"))
        import theme_life as TLF
        d5 = sorted({r[0] for r in TLF.rows_canon() if r[0] < D})[-5:]
        # 10/28 晚用户令: 题材数要动态(多题材并行时不止 2 个), 且 T−1 新冒头的题材第一天就要进(原来只看近 5 日累计前 2 → 新题材进不来)
        from collections import Counter as _Cn
        c5 = _Cn(r[1] for r in TLF.rows_canon() if r[0] in d5 and r[5])
        c1 = _Cn(r[1] for r in TLF.rows_canon() if d5 and r[0] == d5[-1] and r[5])
        tot5, acc, tops = sum(c5.values()) or 1, 0, []
        for th, n_ in c5.most_common():
            if n_ < 3 or (acc / tot5 >= 0.7 and len(tops) >= 2):
                break
            tops.append(th)
            acc += n_
        tops += [th for th, n_ in c1.most_common() if n_ >= 3 and th not in tops]   # T−1 当天 ≥3 家涨停的题材(含新冒头)
        tops = [t for t in tops if t not in getattr(TLF, "NOT_THEME", set())][:8]
        mem = sorted({str(r[3]) for r in TLF.rows_canon() if r[0] in d5 and r[1] in tops and str(r[3]).isdigit()})
        cb_of = {v: k for k, v in (stk or {}).items() if v}
        T4 = list(T4) + [c for c in mem if c not in set(T4)] + [cb_of[c] for c in mem if c in cb_of]
    except Exception:   # noqa: BLE001
        pass
    nbr = []
    try:   # T5 拓扑邻居(10/19 晚: 实盘 / 做T / 执行器票的前 3 邻居, ctx_index 给模型看"邻居此刻涨跌") + 其余(旧账本 / 计划单 / 手动加录)
        sys.path.insert(0, str(ROOT / "scripts" / "market"))
        import topology as TOPO
        for c in sorted(T0):
            nbr += [x["c"] for x in ((TOPO.load(c, D, strict=True) or {}).get("nb") or [])[:3]]
    except Exception:   # noqa: BLE001
        pass
    ok = lambda c: bool(re.fullmatch(r"\d{6}", c)) and not c.startswith(("204", "1318"))   # noqa: E731
    order = []
    TIER.clear()
    try:
        LIVEC = live_codes(D, stk)
    except NameError:
        LIVEC = live_codes(D, {})
    for lv, grp in enumerate([sorted(T0), sorted(T1), T2, T3, LIVEC, T4, nbr + sorted(set(codes) - T0) + T2_OLD + sorted(EXPIRED)]):
        for c in grp:
            if ok(c) and c not in TIER:
                TIER[c] = lv
                order.append(c)
    keep = FILL_TO if len(order) >= FILL_TO else len(order)
    keep = max(keep, sum(1 for c in order if TIER[c] <= 3))   # 10/23 用户令: 盘中新增的 T0~T3(执行票 / 正股 / 导师昨日票 / 候选池)可以把名单撑到 MAXN(60); 到 60 后按档替换 —— 名单按档排序, 低档(T4 梯队 / T5 邻居)先被挤出
    out = [sym(c) for c in order[:keep]]
    out = [x for x in out if x and not x.startswith("bj")]
    CORE_N["n"] = sum(1 for c in order[:keep] if TIER[c] == 0)
    return out[:MAXN]


def cut(syms, level):
    """降级: level = 砍掉的档数(1 = 砍最低档, … 6 = 只剩 T0); 10/28 加了「盘中自动」档(lv4), 共 7 档"""
    return [x for x in syms if TIER.get(x[2:], 6) <= 6 - level]


_LADDER, CORE_N, _MHOLD, TIER = {}, {}, {}, {}


def mentor_hold_codes(D):
    """v3 拟人线导师(lines.json kind=mimic)真人 T−1 收盘持仓 + T−1 成交过的票(10/23 用户: 漏了昨日导师持仓票 —— 导师今天最可能卖 / 加的就是它们); 每天读一次"""
    if D not in _MHOLD:
        out = []
        try:
            sys.path[:0] = [str(ROOT / "scripts" / "paper_line"), str(ROOT / "scripts" / "paper_line" / "tools")]
            import pack
            sks = list(dict.fromkeys(x["skill"] for x in pack.lines().values() if x.get("kind") == "mimic"))
            for sk in sks:
                t = pack.mentor_t1(sk, D)
                i = t.find("收盘持仓")
                out += re.findall(r"\((\d{6})\)", t[i:] if i >= 0 else "")   # 持仓先
                out += re.findall(r"\((\d{6})\)", t[:i] if i >= 0 else t)   # 再是昨天成交过的
        except Exception:   # noqa: BLE001  取不到不影响采集
            pass
        try:   # 10/24 用户: 导师 T−n 持仓 / 操作(当时结算入选; n = 各导师回头操作间隔 P90; mentor_recent.py, 零 token)
            sys.path.insert(0, str(ROOT / "scripts" / "paper_line" / "tools"))
            import mentor_recent as MR
            out += list(MR.codes(D, "book"))
        except Exception:   # noqa: BLE001
            pass
        _MHOLD[D] = list(dict.fromkeys(out))
    return _MHOLD[D]


def ladder_codes(D):
    """T−1 收盘的连板梯队(二板及以上, 封死的; 高度高的先)—— strong_next 库(每晚重建)里状态日 = D 前一交易日的记录; 每天读一次"""
    if D not in _LADDER:
        out = []
        try:   # 10/28 凌晨: 强势股库只收"有次日结果"的日子(strong_next 建库 range(20, len(k)−1)), 最新收盘日永远不在里面 → 梯队停在前一天;
            #   先读 watch_seed.json(check md 收盘后按当天日 K 算的续板, D = 下一交易日), 没有再退回强势股库
            ws = json.loads((ROOT / "results" / "_live" / D / "watch_seed.json").read_text(encoding="utf-8"))
            lv = []
            for x in ws.get("seed") or []:
                if "续板" in (x.get("tags") or []):
                    m = re.match(r"(\d+) 连板 →", (x.get("why") or [""])[0])   # 只认"N 连板 → 明天冲"(海洋王"6 连板断板后今天回封"= 1 板, 不算)
                    if m and int(m.group(1)) >= 2:
                        lv.append((int(m.group(1)), x["code"]))
            if lv:
                _LADDER[D] = [c for _, c in sorted(lv, key=lambda t: -t[0])]
                return _LADDER[D]
        except (OSError, ValueError, KeyError):
            pass
        try:
            f = MKT / "similar" / "stock_strong.jsonl"
            rows, last = [], ""
            with f.open(encoding="utf-8") as fh:
                for l in fh:
                    if '"state": "二板"' not in l and '"state": "三板+"' not in l:
                        continue
                    r = json.loads(l)
                    if r["d"] < D and r.get("sealed"):
                        rows.append(r)
                        last = max(last, r["d"])
            rows = [r for r in rows if r["d"] == last]
            rows.sort(key=lambda r: (r["state"] != "三板+", -float(r.get("pct") or 0)))
            out = [r["code"] for r in rows]
        except (OSError, ValueError, KeyError):
            pass
        _LADDER[D] = out
    return _LADDER[D]


def v3_pool_codes(D):
    """v3 各本账最新一版 01 候选池前 POOL_TOP 名(轮流取, 每本先取第 1 名再取第 2 名 …)"""
    per = []
    for d in sorted([*(ROOT / "results" / "_live" / D).glob("live_*"), *(ROOT / "results" / "_live" / D).glob("paper_*")]):
        vs = sorted((d / "versions").glob("*/01_facts.md"))
        if vs:
            try:
                per.append(re.findall(r"(?m)^\| \d+ \| (\d{6}) \|", vs[-1].read_text(encoding="utf-8", errors="replace"))[:POOL_TOP])
            except OSError:
                continue
    out = []
    for i in range(POOL_TOP):
        out += [p[i] for p in per if len(p) > i]
    return list(dict.fromkeys(out))


# 10/21 晚用户定: 6 个 A 股指数跟个股同一个请求 3 秒一采(零额外请求), 单独写 index_snap.jsonl
# (指数代码去前缀会和个股重名: sh000001 → 000001 = 平安银行, 绝不能混进 book_snap)
INDEX = {"sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指", "sh000688": "科创50", "sh000300": "沪深300", "sz399303": "国证2000"}


def fetch(syms):
    r = urllib.request.Request("https://hq.sinajs.cn/list=" + ",".join(syms), headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"})
    txt = urllib.request.urlopen(r, timeout=8).read().decode("gbk", errors="replace")
    out = []
    for l in txt.strip().splitlines():
        m = re.match(r'var hq_str_(\w+)="([^"]*)"', l)
        if not m or not m.group(2):
            continue
        f = m.group(2).split(",")
        if len(f) < 32:
            continue
        num = lambda x: float(x) if x not in ("", None) else 0.0   # noqa: E731
        if m.group(1) in INDEX:
            out.append({"s": m.group(1), "n": INDEX[m.group(1)], "t": f[31], "p": num(f[3]), "pc": num(f[2]), "o": num(f[1]), "h": num(f[4]), "l": num(f[5]),
                        "v": int(num(f[8])), "a": round(num(f[9]), 2), "d": f[30], "idx": True})
            continue
        out.append({"s": m.group(1), "t": f[31], "p": num(f[3]), "v": int(num(f[8])), "a": round(num(f[9]), 2),
                    "b": [[num(f[11 + 2 * i]), int(num(f[10 + 2 * i]))] for i in range(5)],
                    "k": [[num(f[21 + 2 * i]), int(num(f[20 + 2 * i]))] for i in range(5)], "d": f[30]})
    return out


def run(D):
    LOCK.write_text(str(os.getpid()))
    day_dir = MKT / D
    day_dir.mkdir(parents=True, exist_ok=True)
    fp = day_dir / "book_snap.jsonl"
    last_t, syms, refreshed, fails, back, n, level = {}, [], 0.0, 0, STEP, 0, 0
    log(f"开始 {D} pid={os.getpid()}")
    try:
        with fp.open("a", encoding="utf-8") as fh, (day_dir / "index_snap.jsonl").open("a", encoding="utf-8") as fi:
            while True:
                now = dt.datetime.now()
                hm = now.strftime("%H%M")
                if hm > END:
                    break
                if hm < START:
                    time.sleep(10)
                    continue
                if time.time() - refreshed > 60:   # 10/21 晚: 10 分钟 → 1 分钟(执行器新仓 / 新策略票要尽快进 3 秒盘口; 只读本地文件, 不多打行情源)
                    syms, refreshed = watch(D), time.time()
                    if level:   # 10/23 保险: 请求出过事 → 当天按档降级(先砍低档), 保住持仓票的 3 秒盘口
                        syms = cut(syms, level)
                    log(f"名单 {len(syms)} 只" + (f" (已降级 {level} 档)" if level else ""))
                t0 = time.time()
                try:
                    rows = fetch(syms + [x for x in INDEX if x not in syms])
                    fails, back = 0, STEP
                    for r in rows:
                        if r.pop("d") != D or last_t.get(r["s"]) == r["t"]:
                            continue   # 不是今天的(停牌 / 盘前残留) 或 快照没刷新 → 不写
                        last_t[r["s"]] = r["t"]
                        if r.pop("idx", False):
                            fi.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")
                            continue
                        fh.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")
                        n += 1
                    fh.flush()
                    fi.flush()
                except Exception as e:   # noqa: BLE001
                    fails += 1
                    back = min(60.0, back * 2)
                    if fails % 3 == 0 and level < 6:   # 连续失败每 3 次砍一档(T5 → T4 → … 最后只剩 T0), 当天不恢复
                        level, refreshed = level + 1, 0.0
                        log(f"连续失败 {fails} 次 → 降级到砍掉 {level} 档(只录 T0~T{5 - level})")
                    if fails in (1, 5) or fails % 20 == 0:
                        log(f"请求失败 {fails} 次, 退避 {back:.0f}s: {e}")
                time.sleep(max(0.2, (back if fails else STEP) - (time.time() - t0)))
    finally:
        log(f"结束 {D}: 写 {n} 行")
        try:
            LOCK.unlink()
        except OSError:
            pass
    gz(D)


def gz(D):
    fp = MKT / D / "book_snap.jsonl"
    if fp.exists() and fp.stat().st_size:
        with fp.open("rb") as a, gzip.open(str(fp) + ".gz", "ab") as b:
            shutil.copyfileobj(a, b)
        fp.unlink()
        log(f"压缩 {D} → book_snap.jsonl.gz")


def alive():
    try:
        pid = int(LOCK.read_text())
    except (OSError, ValueError):
        return False
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return str(pid) in (r.stdout or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensure", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--gzip", action="store_true")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    if a.run:
        return run(a.date)
    if a.gzip:
        return gz(a.date)
    if a.ensure:
        hm = dt.datetime.now().strftime("%H%M")
        if not ("0900" <= hm < END) or dt.date.today().weekday() >= 5:
            print("盘口采集: 不在时段")
            return 0
        if alive():
            print("盘口采集: 运行中")
            return 0
        subprocess.Popen([sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--run", "--date", a.date], cwd=ROOT, creationflags=NOWIN,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        print("盘口采集: 已拉起")
    return 0


if __name__ == "__main__":
    sys.exit(main())
