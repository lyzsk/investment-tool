# -*- coding: utf-8 -*-
"""chain_steps.py — 策略执行器的 01→06 串行链(10/21 晚用户令: 每次触发都完整跑 01→06, 3 分钟内出结果, 今晚验证)

为什么快: 不用 claude -p、不让模型读文件。01 由脚本把材料一次备齐(人设 / 规则 / 事实包 / 账户 / 候选池逐只盘中特征 / 指数 / 开盘实况),
02~06 各一次直连 API 流式调用(scripts/lib/claude_api.py), 每步限结构和篇幅; 人设 + 规则是 1 小时缓存前缀, 01 材料是本次触发内 5 分钟缓存前缀,
02 之后每步只付"读缓存"; 03 多 / 空两边同时开。
步骤: 01 脚本事实 → 02 市况 → 03 多 ∥ 空 → 04 选票 → 05 风控(脚本算数 + 模型判) → 06 终裁 + 拟人自检(出执行器规则)
时限: 整条链 CHAIN_BUDGET 秒(默认 170); 每步有自己的上限, 某步超时 / 失败按降级走(02 → 用机械市况; 03 → 无辩论; 05 → 只用脚本数; 04 / 06 失败 → 本次作废沿用上一版)
落盘: <版本目录>/01_facts.md 02_market.md/.json 03_bull/03_bear .md/.json 04_pick.md/.json 05_risk.md/.json 06_final.md/.json timing.json
用法(离线回放 10/21 某触发时刻测耗时): python chain_steps.py --skill meiyuelu --date 2026-10-21 --at 10:05:00 --why "回放"
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import math
import re
import statistics as st
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]   # 10/21 晚从 scripts/dfcf/paper/ 挪到 scripts/chain/(用户令: chain 改名 chain, 触发后跑的链新旧两版放一起)
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts" / "dfcf" / "paper"))
sys.path.insert(0, str(HERE))
import ipv4_first   # noqa: E402,F401
import a_rules as AR   # noqa: E402
import claude_api as API   # noqa: E402
import mentors   # noqa: E402
import trigger_stats as SX   # noqa: E402

MKT = ROOT / "downloads" / "market"
CHAIN_BUDGET = 170
STEP = {"02": (6000, 80),   # 10/21 晚: 02 篇幅不限后 11 次里 5 次撞 3000 上限没 JSON → 6000 / 60 秒
         "03": (3000, 35), "04": (4500, 80), "05": (2000, 25), "06": (4500, 60)}   # 10/22 09:1x: high 04 在 112.5 秒(45×2.5)被截断 5 链首版作废、02 撞 150 秒 → 04 80 秒、02 80 秒; (max_tokens 含思考, 秒上限); 10/21 首测 03 空方 1400 / 05 1000 撞上限
FIRST_BYTE = {"02": 75, "03": 50, "04": 60, "05": 30, "06": 70}   # 10/22 09:5x 首字看门狗(秒): 超过 = 卡死, claude_api 断开重发一次; 中转不回传思考, 实测首个内容事件 = 首字, 阈值取 10/21~22 成功调用首字 P95(02 72 / 03 42 / 04 53 / 05 28 / 06 67)略放宽
POOL_MAX = 100   # 10/24 用户: 30 → 100(3 秒盘口压测 300 只无错; 模型看的表每行约 150 字, 100 行约 15KB)
RULES_INLINE_MAX = 150 * 1024   # rules.md 超过这个大小(桃哥 1.2MB)只给索引


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def rd(p):
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ---------------- 01 材料(脚本, 零 token) ----------------
_NAMES = {}


def names(D):
    if not _NAMES:
        days = sorted(p.parent.name for p in MKT.glob("20*/security_master.jsonl") if p.parent.name <= D)
        for l in rd(MKT / days[-1] / "security_master.jsonl").splitlines() if days else []:
            try:
                r = json.loads(l)
                _NAMES[str(r["code"])] = r.get("name") or ""
            except (ValueError, KeyError):
                pass
    return _NAMES


def prev_close(c, D):
    try:   # 10/27 事故: 日线缓存盘中被写过(百洋股份 10-26 c=10.13 是 09:36 现价, 真收盘 11.28)→ 先用前一交易日正式日线 downloads/market/<日>/kline_day.jsonl
        sys.path.insert(0, str(ROOT / "scripts" / "lib"))
        import official_close as OC
        v = OC.prev_close(c, D)
        if v:
            return v
    except Exception:   # noqa: BLE001
        pass
    k = (jl(ROOT / "downloads" / "quotes" / "daily" / f"{c}.json", {}) or {}).get("klines") or []
    k = [x for x in k if x.get("d", "") < D]
    return k[-1]["c"] if k else None


def snap_lines(D):
    """当天 3 秒盘口逐行(book_snap.jsonl, 收盘后压成 .gz 也认)"""
    import gzip
    f = MKT / D / "book_snap.jsonl"
    if f.exists():
        with f.open(encoding="utf-8") as fh:
            yield from fh
    elif f.with_suffix(".jsonl.gz").exists():
        with gzip.open(f.with_suffix(".jsonl.gz"), "rt", encoding="utf-8") as fh:
            yield from fh


def bars_from_snap(D, until):
    """没有 kline_minute_live(10/21 前)时: 由 3 秒盘口现合成 1 分钟线(收盘价 = 该分钟最后一笔, 均价 = 累计成交额 / 累计成交量)"""
    out = {}
    for l in snap_lines(D):
        try:
            r = json.loads(l)
        except ValueError:
            continue
        t = r.get("t", "")
        if t > until:
            continue
        if not r.get("p") or t < "09:30:00":
            continue
        c, m, p = str(r["s"])[2:], t[:5], float(r["p"])
        bs = out.setdefault(c, [])
        avg = (r["a"] / r["v"]) if r.get("v") and r.get("a") else None
        if avg and not (0.5 < avg / p < 2):   # 量的单位是手时换算成股
            avg = avg / 100 if 0.5 < avg / 100 / p < 2 else None
        if bs and bs[-1]["barTime"][11:16] == m:
            b = bs[-1]
            b["high"], b["low"], b["close"], b["avgPrice"] = max(b["high"], p), min(b["low"], p), p, avg or b["avgPrice"]
        else:
            bs.append({"barTime": f"{D}T{m}:00", "open": p, "high": p, "low": p, "close": p, "avgPrice": avg})
    return out


def minute_bars(D, until):
    """kline_minute_live.jsonl → {code: [bar...]}(barTime ≤ until); 当天没有这个文件就由 3 秒盘口合成"""
    out = {}
    if not (MKT / D / "kline_minute_live.jsonl").exists():
        return bars_from_snap(D, until)
    for l in rd(MKT / D / "kline_minute_live.jsonl").splitlines():
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if r.get("barTime", "")[11:19] <= until:
            out.setdefault(r["symbol"][2:], []).append(r)
    return out


def auction_snap(D, until):
    """竞价段(09:15~09:25) book_snap: 现价=0, 撮合价在买一=卖一, 未匹配量在买二 / 卖二 → {code: {t, px, matched, unmatched_buy, unmatched_sell}}"""
    out = {}
    if until < "09:15:00":
        return out
    try:
        if True:
            for l in snap_lines(D):
                if '"t":"09:2' not in l and '"t":"09:1' not in l:
                    if '"t":"09:3' in l:
                        break
                    continue
                r = json.loads(l)
                t = r.get("t", "")
                if not ("09:15:00" <= t <= min(until, "09:25:59")):
                    continue
                b, k = r.get("b") or [], r.get("k") or []
                c = str(r["s"])[2:]
                if r.get("p"):
                    out[c] = {"t": t, "px": r["p"], "final": True}
                elif b and b[0][0]:
                    out[c] = {"t": t, "px": b[0][0], "matched": b[0][1], "unmatched_buy": (b[1][1] if len(b) > 1 else 0), "unmatched_sell": (k[1][1] if len(k) > 1 else 0)}
    except OSError:
        pass
    try:   # 10/22 用户追问发现: 澳弘 09:36 前不在 3 秒名单 → 土豆 09:24 那版 01 看不到它的竞价; 名单外的票补读新浪全市场竞价快照(collect_auction, 约 15 秒一张)
        raw = MKT / D / "call_auction_open_raw.jsonl"
        if raw.exists():
            lim = D + "T" + min(until, "09:25:59")
            for l in raw.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    r = json.loads(l)
                except ValueError:
                    continue
                if not ("T09:15:00" <= r.get("at", "")[10:] and r.get("at", "") <= lim):
                    continue
                c, f = str(r.get("symbol", ""))[2:], r.get("fields") or []
                if c in out and out[c].get("src") != "sina" or len(f) < 32:
                    continue
                px = float(f[11] or 0)   # 竞价段: 买一价 = 虚拟撮合价, 买一量 = 匹配量, 买二量 = 未匹配买, 卖二量 = 未匹配卖(同 book_snap 口径)
                if px:
                    out[c] = {"t": f[31], "px": px, "matched": int(float(f[10] or 0)), "unmatched_buy": int(float(f[12] or 0)), "unmatched_sell": int(float(f[22] or 0)), "src": "sina"}
    except OSError:
        pass
    return out


def sina_snap(codes):
    """池里没有分钟线的票(实时模式): 一次新浪请求拿 今开 / 昨收 / 现价 / 最高 / 最低 / 成交量额"""
    out = {}
    if not codes:
        return out
    try:
        req = urllib.request.Request("http://hq.sinajs.cn/list=" + ",".join(AR.symbol(c) for c in codes), headers={"Referer": "https://finance.sina.com.cn"})
        for line in urllib.request.urlopen(req, timeout=5).read().decode("gbk", "replace").splitlines():
            m = re.match(r'var hq_str_\w\w(\d{6})="([^"]*)"', line)
            if m and m.group(2):
                x = m.group(2).split(",")
                if float(x[3]) > 0:
                    out[m.group(1)] = {"name": x[0], "o": float(x[1]), "pc": float(x[2]), "p": float(x[3]), "h": float(x[4]), "l": float(x[5]),
                                       "vwap": (float(x[9]) / float(x[8])) if float(x[8]) else None}
    except Exception:   # noqa: BLE001
        pass
    return out


def ema(xs, n):
    k, e, out = 2 / (n + 1), None, []
    for x in xs:
        e = x if e is None else e + k * (x - e)
        out.append(e)
    return out


def rsi(xs, n=14):
    if len(xs) <= n:
        return None
    g = [max(0, b - a) for a, b in zip(xs, xs[1:])][-n:]
    l_ = [max(0, a - b) for a, b in zip(xs, xs[1:])][-n:]
    ag, al = sum(g) / n, sum(l_) / n
    return 100.0 if al == 0 else round(100 - 100 / (1 + ag / al), 1)


def feat(c, D, bars, snap, q):
    """一只票的盘中特征(脚本算好给 04); bars=1 分钟线, snap=新浪快照, q=3 秒盘口"""
    pc = prev_close(c, D)
    f = {"pc": pc}
    if bars:
        cl = [b["close"] for b in bars]
        f.update(o=bars[0]["open"], h=max(b["high"] for b in bars), l=min(b["low"] for b in bars), p=cl[-1], vwap=bars[-1].get("avgPrice"))
        f["r30"] = round((cl[-1] / cl[-31] - 1) * 100, 2) if len(cl) > 30 else None
        c5 = cl[4::5] if len(cl) >= 5 else []
        if len(c5) >= 10:
            dif = [a - b for a, b in zip(ema(c5, 12), ema(c5, 26))]
            hist = [a - b for a, b in zip(dif, ema(dif, 9))]
            f["macd5"] = ("红" if hist[-1] > 0 else "绿") + ("↑" if len(hist) > 1 and hist[-1] > hist[-2] else "↓")
        f["rsi1"] = rsi(cl)
        f["src"] = "1分钟线"
    elif snap:
        f.update(o=snap["o"], h=snap["h"], l=snap["l"], p=snap["p"], vwap=snap.get("vwap"), src="新浪快照")
    if q and q.get("p"):
        f["p"] = q["p"]
        f["h"] = max(f.get("h") or 0, q["p"]) or q["p"]
        f["l"] = min(f.get("l") or q["p"], q["p"])
    p = f.get("p")
    if p and pc:
        f["chg"] = round((p / pc - 1) * 100, 2)
        if f.get("o"):
            f["gap"] = round((f["o"] / pc - 1) * 100, 2)
        if f.get("h") and f.get("l") and f["h"] > f["l"]:
            f["pos"] = round((p - f["l"]) / (f["h"] - f["l"]) * 100)
            f["dd"] = round((p / f["h"] - 1) * 100, 2)
        if f.get("vwap"):
            f["vs_vwap"] = round((p / f["vwap"] - 1) * 100, 2)
    if pc:   # 10/21 晚回放: 竞价段 / 没现价时涨跌停价也要给(原来只在有现价时算, 09:15 首版没有价格锚)
        f["up"], f["dn"] = AR.limit_prices(c, D, pc)
    f["amp"] = round(SX.amp(c, D) * 100, 2)
    return f


def fmt(x, nd=2, pct=False):
    if x is None or x == "":
        return "-"
    return f"{x:+.{nd}f}%" if pct else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def pool(skill, D, state, strategy, facts, at=None):
    """候选池(上限 30, 标来源): 持仓 → 当前策略里的票 → 用户加 → 今日强题材(圈内最多 30 只, 保底) → 事实包本导师小节里的票 → 事实包其余出现次数多的票
    10/24 模块 4: ①导师本人只认本导师那一节(到下一个 ## / ### 标题为止; 原来往后截 8000 字, 把别的导师和涨跌幅榜都算成"导师本人", 10/23 三本账 28~29 只同一批误收)
                  ②新增"今日强题材"来源(strong_themes.candidates: 盘中涨停池 + T-1 涨停分析, 按导师能力圈), 排在导师本人前, 不被 30 只截掉"""
    src = {}
    for c in state.get("positions") or {}:
        src.setdefault(c, "持仓")
    for x in (strategy or {}).get("codes") or []:
        src.setdefault(str(x.get("code")), "上一版策略")
    try:   # 10/22 用户令: 手动加进候选池(chain_flags.txt EXEC_POOL_EXTRA=代码逗号分隔, 每次触发现读; 排在导师本人 / 事实包前, 不被 30 只上限截掉)
        for line in (ROOT / "scripts" / "claude_profile" / "chain_flags.txt").read_text(encoding="utf-8").splitlines():
            k, _, val = line.split("#")[0].partition("=")
            if k.strip() == "EXEC_POOL_EXTRA":
                for c in re.findall(r"(?<!\d)\d{6}(?!\d)", val):
                    src.setdefault(c, "用户加")
    except OSError:
        pass
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "paper_line" / "tools"))
        import strong_themes as STH
        for c, why in STH.candidates(skill, D, at or "09:00:00"):
            src.setdefault(c, "强题材·" + why.split("·", 1)[1].split("(")[0])
        if STH.scope(skill)["cb"]:   # 10/24: 转债导师 —— 前一交易日成交额前 30 的转债(否则 100 只里 99 只是事实包里的股票, 对他没用)
            for c, why in STH.cb_active(D):
                src.setdefault(c, "转债活跃")
    except Exception:   # noqa: BLE001  强题材算不出来不挡候选池
        pass
    try:   # 10/24 用户: 导师 T−n 持仓 / 操作过的(当时结算入选的全体导师; n = 各导师回头操作间隔 P80; mentor_recent.py) —— 不进池 04 就不可能导师式回头买
        sys.path.insert(0, str(ROOT / "scripts" / "paper_line" / "tools"))
        import mentor_recent as MR
        for c, e in MR.load(D)["codes"].items():
            if e["tier"] in ("must", "pool"):
                src.setdefault(c, f"导师近期·T-{e['k']}")
    except Exception:   # noqa: BLE001
        pass
    try:   # 10/27 晚: 挪到导师近期之后(备案是项目推测, 排在导师本人 / 强题材 / 导师近期后面) · 10/26 晚用户令: 明日备案(前一晚 check md 机械算: 明日聚焦题材的梯队票 / 题材套利债)提前埋进候选池; 转债导师拿转债, 其余拿股票
        sys.path.insert(0, str(ROOT / "scripts" / "paper_line" / "tools"))
        import expect as EXP
        import strong_themes as STH0
        e_ = EXP.load(D) or {}
        for c, th in ((e_.get("候选") or {}).get("转债" if STH0.scope(skill)["cb"] else "股票") or [])[:16]:
            src.setdefault(str(c), f"备案·{th}")
    except Exception:   # noqa: BLE001  备案没有 / 算不出来不挡候选池
        pass
    try:   # 10/25 用户: live line 暂停的线盘前选过的票不出池, 都是重点观察对象 —— 其他线最新一版策略里的票进本线候选池
        live = ROOT / "results" / "_live" / D
        for d_ in sorted(live.glob("live_*")):
            if d_.name == f"live_{skill}":
                continue
            sp = sorted((d_ / "strategies").glob("*.json"))
            if sp:
                for x in (json.loads(sp[-1].read_text(encoding="utf-8")).get("strategy") or {}).get("codes") or []:
                    src.setdefault(str(x.get("code")), f"其他线选的·{d_.name[5:]}")
    except Exception:   # noqa: BLE001
        pass
    try:   # 10/25 用户选 D: 被加红电报点名封板 / 冲板的票进候选池(开板 / 炸板不叫醒 chain, 想接由 06 提前挂 board_dip; 先跑几天看)
        sys.path.insert(0, str(ROOT / "scripts" / "paper_line" / "tools"))
        import telegraph_now as TGN
        for c in TGN.limit_named(D, at or "09:00:00")[:15]:
            src.setdefault(c, "电报点名·涨停")
    except Exception:   # noqa: BLE001
        pass
    pat = r"(?<!\d)([036]\d{5}|11\d{4}|12\d{4}|15\d{4}|5[16]\d{4})(?!\d)"
    head = mentors.head(skill)
    i = facts.find("### " + head) if head else -1
    i = i if i >= 0 else (facts.find(head) if head else -1)
    if i >= 0:
        m = re.search(r"\n#{2,3} ", facts[i + 4:])
        sec = facts[i:i + 4 + m.start()] if m else facts[i:i + 3000]
        for c in re.findall(pat, sec):
            src.setdefault(c, "导师本人")
    cnt = {}
    for c in re.findall(pat, facts):
        cnt[c] = cnt.get(c, 0) + 1
    for c, _ in sorted(cnt.items(), key=lambda kv: -kv[1]):
        src.setdefault(c, "事实包")
    return dict(list(src.items())[:POOL_MAX])


IDX_ORDER = [("sh000001", "上证"), ("sz399001", "深证成指"), ("sz399006", "创业板"), ("sh000688", "科创50"), ("sh000300", "沪深300"), ("sz399303", "国证2000")]
SPREADS = [("sz399303", "sh000001", "国证2000 − 上证(大小盘: 正 = 中小票强, 即白线在黄线下方)"), ("sz399006", "sh000001", "创业板 − 上证(成长 / 题材 vs 权重)")]


def index3_block(D, until):
    """10/21 晚用户令: 6 个 A 股指数 3 秒级(collect_book → index_snap.jsonl): 现价 / 当日涨跌 / 开盘以来高低 / 近 30 分钟; 两个剪刀差的现值、30 分钟前、今日穿越 0 轴时刻"""
    rows = {}
    for l in rd(MKT / D / "index_snap.jsonl").splitlines():
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if r.get("t", "") <= until and r.get("p") and r.get("pc"):
            rows.setdefault(r["s"], []).append(r)
    if not rows:
        return "(3 秒级指数暂无, 看下方分钟面板)"
    t30 = (dt.datetime.strptime(until[:8], "%H:%M:%S") - dt.timedelta(minutes=30)).strftime("%H:%M:%S")
    pct = lambda r: (r["p"] / r["pc"] - 1) * 100   # noqa: E731
    L = [f"数据截至 {max(v[-1]['t'] for v in rows.values())}(3 秒级, 新浪)"]
    for s, n in IDX_ORDER:
        v = rows.get(s)
        if not v:
            continue
        a = [r for r in v if r["t"] <= t30]
        hi, lo = max(r["p"] for r in v if r["t"] >= "09:30:00" or r is v[-1]), min(r["p"] for r in v if r["t"] >= "09:30:00" or r is v[-1])
        L.append(f"- {n} {v[-1]['p']:.2f} {pct(v[-1]):+.2f}%(今日高 {(hi / v[-1]['pc'] - 1) * 100:+.2f}% / 低 {(lo / v[-1]['pc'] - 1) * 100:+.2f}%)"
                 + (f", 近 30 分钟 {(v[-1]['p'] / a[-1]['p'] - 1) * 100:+.2f}%" if a else ""))
    for x, y, name in SPREADS:
        vx, vy = rows.get(x), rows.get(y)
        if not vx or not vy:
            continue
        by = {r["t"][:5]: pct(r) for r in vy}
        seq = []
        for r in vx:
            m = r["t"][:5]
            if m in by and r["t"] >= "09:30:00":
                if not seq or seq[-1][0] != m:
                    seq.append((m, pct(r) - by[m]))
        if not seq:
            continue
        crosses, side = [], None
        for m, d in seq:   # 穿越 0 轴且离开 0 轴 ≥ 0.05 个百分点才算(防在 0 附近来回抖)
            if abs(d) >= 0.05:
                sd = d > 0
                if side is not None and sd != side:
                    crosses.append(f"{m}{'转正' if sd else '转负'}")
                side = sd
        ago = [d for m, d in seq if m <= t30[:5]]
        L.append(f"- 剪刀差 {name}: 现 {seq[-1][1]:+.2f} 个百分点" + (f", 30 分钟前 {ago[-1]:+.2f}" if ago else "") + f"; 今日穿越 0 轴: {' '.join(crosses) or '无'}")
    try:   # 10/24 用户定: 大盘 / 小盘各一组 路径 + 结构变化日志(不用单一枚举), 段编号 M大n / M小n 供 02 / 04 引用
        sys.path.insert(0, str(ROOT / "scripts" / "paper_line" / "tools"))
        import market_path as MP
        L.append("\n" + MP.text(D, until, reader=rd))
    except Exception as e:   # noqa: BLE001
        L.append(f"(大小盘路径计算失败 {e!r})"[:120])
    return "\n".join(L)


def index_block(D, until):
    """多指数 / 外围面板(panel_minute.jsonl)最新一点 + 30 分钟前"""
    last, ago = {}, {}
    hm = until[:5]
    t30 = (dt.datetime.strptime(hm, "%H:%M") - dt.timedelta(minutes=30)).strftime("%H:%M")
    for l in rd(MKT / D / "panel_minute.jsonl").splitlines():
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if not str(r.get("ts", "")).startswith(D) or r.get("t", "")[:5] > hm or r.get("p") is None:   # 10/21 晚: 开盘前面板有空价行
            continue
        last[r["k"]] = r
        if r.get("t", "")[:5] <= t30:
            ago[r["k"]] = r
    L = []
    for k, r in last.items():
        a = ago.get(k)
        d30 = f", 近 30 分钟 {(r['p'] / a['p'] - 1) * 100:+.2f}%" if a and a.get("p") else ""
        L.append(f"- {r.get('n') or k} {r['t'][:5]} {(r.get('pct') or 0):+.2f}%{d30}")
    return "\n".join(L) or "(指数面板暂无)"


def mimic_stats(skill, D, state, px):
    """05 用: 本链此刻 vs 导师真人近 60 个记录日(持股只数 / 单票最大仓位)"""
    nav = state["cash"] + sum(p["qty"] * (px.get(c) or p.get("cost") or 0) for c, p in state["positions"].items())
    pcts = sorted(((p["qty"] * (px.get(c) or p.get("cost") or 0)) / nav * 100 for c, p in state["positions"].items()), reverse=True) if nav else []
    dp = jl(ROOT / "downloads" / "tzzb" / skill / "day_positions.json", {}) or {}
    days = sorted(k for k in dp if k < D.replace("-", ""))[-60:]
    n_hold = [sum(1 for x in (dp[d].get("list") or []) if (x.get("position_percent") or 0) > 0) for d in days]
    mx = [max([x.get("position_percent") or 0 for x in (dp[d].get("list") or [])] or [0]) * 100 for d in days]
    real = f"真人近 {len(days)} 个记录日: 持股只数中位 {st.median(n_hold) if n_hold else '-'}(P25~P75 {sorted(n_hold)[len(n_hold) // 4] if n_hold else '-'}~{sorted(n_hold)[len(n_hold) * 3 // 4] if n_hold else '-'}), 单票最大仓位中位 {st.median(mx):.0f}%" if days else "真人持仓日表: 无(B站 UP / 无数据)"
    avg = SX.real_avg(skill, D)
    st0 = state.get("start") or {}
    base = (float(st0.get("cash") or 0) + sum(int(q.get("qty") or 0) * (prev_close(c, D) or q.get("cost") or 0) for c, q in (st0.get("positions") or {}).items())) if st0 else 0
    pnl = f"; 今日盈亏 {nav - base:+.0f} 元({(nav / base - 1) * 100:+.2f}%)" if base else ""
    return (f"本链此刻: 持股 {len(pcts)} 只, 单票仓位 {', '.join(f'{x:.0f}%' for x in pcts) or '空仓'}, 现金 {state['cash'] / nav * 100 if nav else 100:.0f}%; 今日已成交 {len(state.get('trades') or [])} 笔{pnl}\n"
            f"{real}; 真人日均出手 {avg if avg is not None else '-'} 次")


LAST_FEATS = {}   # 最近一次 01 里每只候选的盘中特征(给 chain_lookup 的"相似历史买点"用)


LAST_ROWS = {}   # 10/25 叫醒只发增量: 最近一次 01 每只候选的 (现价, 涨跌%, 振幅中位%)


def build_01(skill, D, at, why, state, strategy, fired, quotes, facts, open_text, prev02, live=True, inc=None):
    """inc = 上次已发给本会话的候选行 {代码: (现价, 涨跌%, 振幅中位%)}(None = 发全表); 给了就只列: 持仓 / 当前策略里的票 / 新进池 / 涨跌比上次变了 ≥ 本票振幅中位一半(至少 1 个点)的,
    其余写一行"另 N 只和上次比没明显变化"; 发出去的行会更新进 inc"""
    nm = names(D)
    P = pool(skill, D, state, strategy, facts, at)
    bars = minute_bars(D, at)
    need = [c for c in P if c not in bars and not (quotes.get(c) or {}).get("p")]
    snaps = sina_snap(need) if live and at >= "09:30:00" else {}
    auc = auction_snap(D, at) if at < "09:31:00" else {}
    rows, px = [], {}
    keep_codes = set(state.get("positions") or {}) | {str(x.get("code")) for x in (strategy or {}).get("codes") or []}
    n_same = 0
    LAST_ROWS.clear()
    for i, (c, s) in enumerate(P.items(), 1):
        f = feat(c, D, bars.get(c), snaps.get(c), quotes.get(c) if (quotes.get(c) or {}).get("p") else ({"p": auc[c]["px"]} if c in auc else None))   # 竞价段用撮合价当现价锚
        LAST_FEATS[c] = f
        px[c] = f.get("p")
        LAST_ROWS[c] = (f.get("p"), f.get("chg"), f.get("amp"))
        if inc is not None and c not in keep_codes and c in inc:
            p0, chg0, amp0 = inc[c]
            thr = max(1.0, 0.5 * float(f.get("amp") or amp0 or 2.0))
            if f.get("chg") is not None and chg0 is not None and abs(float(f["chg"]) - float(chg0)) < thr:
                n_same += 1
                continue
        if inc is not None:
            inc[c] = LAST_ROWS[c]
        a = auc.get(c) or {}
        aj = (f"竞价 {a['t'][3:]} 撮合 {a['px']}" + (f" 匹配 {a.get('matched')} 未匹配买 {a.get('unmatched_buy')} / 卖 {a.get('unmatched_sell')}" if not a.get("final") else " (已定)")) if a else ""
        rows.append(f"| {i} | {c} | {nm.get(c) or (snaps.get(c) or {}).get('name') or ''} | {s} | {fmt(f.get('p'), 3)} | {fmt(f.get('chg'), pct=True)} | {fmt(f.get('gap'), pct=True)} | "
                    f"{fmt(f.get('vs_vwap'), pct=True)} | {fmt(f.get('pos'))} | {fmt(f.get('dd'), pct=True)} | {fmt(f.get('r30'), pct=True)} | {f.get('macd5') or '-'} | {fmt(f.get('rsi1'), 0)} | "
                    f"{fmt(f.get('amp'), pct=False)}% | {fmt(f.get('up'))}/{fmt(f.get('dn'))} | {f.get('src') or '无盘中数据'} | {aj} |")
    nav = state["cash"] + sum(p["qty"] * (px.get(c) or p.get("cost") or 0) for c, p in state["positions"].items())
    pos = [f"- {c} {nm.get(c, '')} {p['qty']} 股(今天可卖 {p.get('sellable', 0)}) 成本 {fmt(p.get('cost'), 3)} 现价 {fmt(px.get(c), 3)} 浮盈 "
           f"{fmt(((px.get(c) or 0) / p['cost'] - 1) * 100 if p.get('cost') and px.get(c) else None, pct=True)}" for c, p in state["positions"].items()] or ["- 空仓"]
    tr = [f"- {t['t']} {t['side']} {t['code']} {t.get('name') or ''} {t['qty']}@{t['px']}" for t in state.get("trades") or []] or ["- 无"]
    cur = []
    for x in (strategy or {}).get("codes") or []:
        for r in x.get("rules") or []:
            done = any(k.endswith(f":{x['code']}:{r['id']}") for k in fired or ())
            cur.append(f"- {x['code']} {r['side']} 价{r['op']}{r['px']} ×{r['qty']}{' (已成交)' if done else ''} | {str(r.get('why', ''))[:60]}")
    phase = "集合竞价(09:15~09:25 只读不成交, 09:25 竞价单按撮合价一次成交)" if at < "09:25:00" else "竞价已定, 09:30 开始连续竞价" if at < "09:30:00" else "午休" if "11:30:00" < at < "13:00:00" else "连续竞价"
    auc_path = ""
    if "09:15:00" <= at < "09:31:00":   # 10/24 用户批(❓14): 竞价路径(首价 / 09:15~09:20 高低 / 09:20 后抬压价 / 疑似撤单), 候选池前 12 只
        try:
            sys.path.insert(0, str(ROOT / "scripts" / "paper_line" / "tools"))
            import auction_path as AP
            auc_path = AP.text(D, at, list(P)[:12], lambda c: AP.prev_close(c, D), nm)
        except Exception as e:   # noqa: BLE001
            auc_path = ("## 竞价路径" + chr(10) + f"(计算失败 {e!r})")[:160]
    hz = (jl(ROOT / "scripts" / "chain" / "horizon_days.json", {}) or {})
    try:   # 10/24 用户批(❓12): 盘面情绪面板(全市场 13 档 / 涨停 / 炸板 / 跌停 / 封板率 / 梯队; collect_panel 循环每 5 分钟采)
        sys.path.insert(0, str(ROOT / "scripts" / "market"))
        import collect_mood as CMood
        mood = CMood.block(D, at)
    except Exception as e:   # noqa: BLE001
        mood = f"## 盘面情绪{chr(10)}(读取失败 {e!r})"[:160]
    try:   # 10/24 模块 4: 今日强题材 / 盘中题材强度(按本导师能力圈分圈内 / 圈外)
        import strong_themes as STH
        mood += chr(10) * 2 + STH.block(skill, D, at)
    except Exception as e:   # noqa: BLE001
        mood += chr(10) * 2 + f"(今日强题材读取失败 {e!r})"[:120]
    try:   # 10/26 晚用户令: 明日备案(前一晚机械算的项目整合视角, 全线共用): 情绪聚焦 / 明日聚焦题材(延续概率 + 流转)/ 梯队 / 题材套利债
        ef = ROOT / "results" / "_live" / D / "expect.md"
        if ef.exists():
            mood += chr(10) * 2 + ef.read_text(encoding="utf-8")
    except OSError:
        pass
    h = hz.get(skill) or hz.get("_default") or {}
    rebound_txt = ""
    try:   # 10/27 晚用户批: 「反抽」四样(起点 / 起算 / 结束 / 走强改判)按本票近 30 天分时动态算, 持仓 + 上一版策略里的票都给; REBOUND_CARD=0 关
        _rb_on = not re.search(r"(?m)^\s*REBOUND_CARD\s*=\s*0", (ROOT / "scripts" / "claude_profile" / "chain_flags.txt").read_text(encoding="utf-8"))
        if _rb_on:
            sys.path.insert(0, str(ROOT / "scripts" / "paper_line" / "tools"))
            import rebound_card as RBC
            rc_codes = list(dict.fromkeys(list(state.get("positions") or {}) + [str(x.get("code")) for x in (strategy or {}).get("codes") or []]))[:8]
            if rc_codes:
                rebound_txt = RBC.block(rc_codes, D)
    except Exception as e:   # noqa: BLE001
        rebound_txt = f"(反抽卡算失败 {type(e).__name__})"
    txt = f"""# 01 事实({D} {at}, 脚本生成)
触发原因: {why}
交易阶段: {phase}
多日展望天数: 中位 {h.get('med', 2)} 天 / 上限 {h.get('cap', 5)} 天({h.get('src', '')})

## 账户(模拟账, 唯一账本)
总资产约 {nav:.0f}, 现金 {state['cash']:.0f}
{chr(10).join(pos)}
今日成交:
{chr(10).join(tr)}
当前生效策略(上一版 06):
{chr(10).join(cur) or '- 无'}

## 开盘实况(机械判定, 每次触发现读)
{open_text}

{rebound_txt}

## A 股指数(3 秒级) + 大小盘 / 风格剪刀差
{index3_block(D, at)}

## 指数 / 外围面板(分钟级)
{index_block(D, at)}

{mood}

{auc_path}

## 候选池(脚本按 持仓 → 上一版策略 → 导师本人 → 事实包 取前 {POOL_MAX}; 04 只能从这里选, 写行号)
| 行 | 代码 | 名称 | 来源 | 现价 | 涨跌 | 开盘缺口 | 相对均价 | 日内位置% | 离高点 | 近30分钟 | 5分MACD | RSI14(1分) | 近30日振幅中位 | 涨停/跌停 | 数据 | 竞价 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}{(chr(10) + f"(另 {n_same} 只和上次给你的比没明显变化(涨跌变动 < 本票近 30 日振幅中位的一半), 不重发; 要选它们写代码即可)") if n_same else ""}

## 上一版(02 全文 / 06 结论 / 今日各版一览; 供"和上一版比变了什么", 上一版写的下一轮预期和失效条件这次要逐条回应)
{prev02 or '(今天第一版)'}

## 今日事实包(零 token 机械构建: 大盘 / 外围 / 资讯 / 六榜 / 导师信号)
{facts}
"""
    return txt, P, px, nav


# ---------------- 02~06 ----------------
PERSONA_PROFILE_CAP = 20000   # 画像按步适用节原文合计上限(字节)
PERSONA_RULES_CAP = 64000     # 规则全文合计上限(10/22 用户令去路径依赖: 30KB→64KB, 不再只给上一版引用过的)
PERSONA_CASES_CAP = 12000     # 按候选池票名捞的案例全文合计上限
RID_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{1,3}\d{1,3}[a-z]?)(?![A-Za-z0-9])")


def _sections(text, head_re):
    """按标题切块: [(标题行, 起行号, 正文)]"""
    lines = text.split("\n")
    hs = [i for i, l in enumerate(lines) if head_re.match(l)]
    return [(lines[i], i + 1, "\n".join(lines[i:(hs[k + 1] if k + 1 < len(hs) else len(lines))]).rstrip()) for k, i in enumerate(hs)]


def cited_ids(skill, strategy, prev_texts):
    """上一版引用过的规则编号(上一版 06 / 04 JSON + 上一版 02 原文里出现、且在本导师规则索引里的编号)"""
    idx = set(re.findall(r"^- ([A-Z]{1,3}\d{1,3}[a-z]?)\s", rd(ROOT / "skills" / f"{skill}-skill" / "persona" / "rules_index.md"), re.M))
    blob = json.dumps(strategy or {}, ensure_ascii=False) + "\n".join(t or "" for t in prev_texts)
    seen = []
    for m in RID_RE.findall(blob):
        if m in idx and m not in seen:
            seen.append(m)
    return seen


def persona(skill, cited, pool_names, pool_codes=()):
    """10/21 晚用户令(B3 推广到全部有索引的文件): 常驻 = 画像核心摘要 + 画像目录 + 规则索引 + 指纹; 原文只按需捞:
    画像 = profile_index 里"适用步骤"含 02~06 的节(按优先级装到上限); 规则 = 上一版引用过的编号; 案例 = 标题里出现候选池 / 持仓票名的卡。
    返回 (常驻块, 按需块, 说明 dict)"""
    d = ROOT / "skills" / f"{skill}-skill" / "persona"
    head = (f"你是 {skill} 导师的模拟盘决策链里的一步(A 股, 模拟账)。下面是导师画像摘要与目录、规则索引、指纹, 以及按需摘录的原文(画像适用节 / 上一版引用过的规则全文 / 和当前候选票有关的案例)。"
            "判断以这些为准, 引用规则写编号; 只看到索引没看到全文的规则也可以引用, 按索引里的一句话理解。风格跟导师走(拟人), 教训可以让你偏离导师但要写理由。"
            "所有输出用中文。材料已经全部给你, 不要说要读文件, 不要编造材料里没有的数字。")
    stable, var, info = [head], [], {}
    pack = None
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "md"))
        import gen_profile_index as gpi
        idx = gpi.read_index(d / "profile_index.md")
        if idx and idx[2]:
            cur = {(s["title"], s["sha8"]): s for s in gpi.parse_sections(rd(d / "profile.md"))}
            pack = {"summary": idx[1], "rows": [{**r, **cur[(r["title"], r["sha8"])]} for r in idx[2] if (r["title"], r["sha8"]) in cur]}
    except Exception as e:   # noqa: BLE001
        info["profile_err"] = repr(e)[:120]
    if pack:
        inj, used = [], 0
        for r in sorted(pack["rows"], key=lambda r: (r["prio"], r["start"])):
            if set(r["steps"]) & {"02", "03", "04", "05", "06"} and used + r["bytes"] <= PERSONA_PROFILE_CAP:
                inj.append(r)
                used += r["bytes"]
        ids = {r["id"] for r in inj}
        stable.append("# 导师画像核心摘要(profile_index.md)\n" + (pack["summary"] or "(无)") + "\n\n# 画像目录(★ = 下方已附原文)\n" +
                      "\n".join(f"- {'★' if r['id'] in ids else ' '} {r['id']} {r['title']}: {r['about']}" for r in sorted(pack["rows"], key=lambda r: r["start"])))
        var.append("# 画像原文(适用 02~06 的节)\n" + "\n\n".join(f"## 【{r['id']}】{r['title']}\n{r['text']}" for r in sorted(inj, key=lambda r: r["start"])))
        info["profile"] = f"{len(inj)} 节 {used / 1024:.1f}KB"
    else:   # 没有画像索引: 退回整份画像(截到上限)
        var.append("# 导师画像 profile.md(无索引, 截前 20KB)\n" + rd(d / "profile.md")[:PERSONA_PROFILE_CAP])
        info["profile"] = "无索引, 整份截断"
    stable.append("# 规则索引 rules_index.md\n" + rd(d / "rules_index.md"))
    if (d / "fingerprint.md").exists():
        stable.append("# 导师指纹 fingerprint.md\n" + rd(d / "fingerprint.md"))
    rs = {}
    for t, _, body in _sections(rd(d / "rules.md"), re.compile(r"^### ")):
        m = RID_RE.match(t[4:].strip())
        if m:
            rs.setdefault(m.group(1), body)
    # 10/22 用户令(去路径依赖): 原来只给"上一版引用过的"规则全文 → 第一版没引用到的规则(如卖点)永远只剩一句话索引。
    # 改为按优先级装满上限: ① 上一版引用过的 ② 正文提到当前候选 / 持仓票名或代码的 ③ 其余按规则文件原顺序; 装不下的仍有索引一句话
    keys = [k for k in [*pool_names, *pool_codes] if k]
    order = list(dict.fromkeys([*[c for c in cited if c in rs], *[k for k, b in rs.items() if any(x in b for x in keys)], *rs.keys()]))
    got, used, n_cited = [], 0, 0
    for c in order:
        b = rs[c]
        if used + len(b.encode()) > PERSONA_RULES_CAP:
            continue
        got.append(b)
        used += len(b.encode())
        n_cited += c in cited
    if got:
        var.append(f"# 规则全文({len(got)}/{len(rs)} 条; 先上一版引用过的, 再提到当前票的, 再按原顺序装到 {PERSONA_RULES_CAP // 1024}KB)\n" + "\n\n".join(got))
    info["rules"] = f"{len(got)}/{len(rs)} 条(含上一版引用 {n_cited}/{len(cited)}) {used / 1024:.1f}KB"
    # 10/22 用户令: 原来只认"### 标题含票名"的卡 → 土豆的案例是按"逃顶 / 卖飞"分节的大表, 票名都在表格行里, 一张也匹配不上。
    # 改为两级: 标题含票名 → 整节; 否则逐行扫(表格行 / 列表行), 含票名或代码的行连同所在节标题 + 表头一起给
    cs, used, n_rows = [], 0, 0
    for t, _, body in _sections(rd(d / "cases.md"), re.compile(r"^#{2,3} ")):
        if any(k in t for k in keys):
            if used + len(body.encode()) <= PERSONA_CASES_CAP:
                cs.append(body)
                used += len(body.encode())
            continue
        lines = body.split("\n")
        hdr = next((i for i, l in enumerate(lines) if l.startswith("|") and i + 1 < len(lines) and set(lines[i + 1].replace("|", "").strip()) <= set("-: ")), None)
        hit = [l for l in lines[1:] if l.startswith(("|", "- ", "* ")) and any(k in l for k in keys)]
        if not hit:
            continue
        blk = "\n".join([lines[0], *([lines[hdr], lines[hdr + 1]] if hdr is not None else []), *hit])
        if used + len(blk.encode()) <= PERSONA_CASES_CAP:
            cs.append(blk)
            used += len(blk.encode())
            n_rows += len(hit)
    if cs:
        var.append(f"# 案例原文(含当前候选 / 持仓票名或代码的 {len(cs)} 处, 其中表格 / 列表行 {n_rows} 条)\n" + "\n\n".join(cs))
    info["cases"] = f"{len(cs)} 处 / 行 {n_rows} {used / 1024:.1f}KB"
    return "\n\n".join(stable), "\n\n".join(var), info


def prefix(skill):
    d = ROOT / "skills" / f"{skill}-skill" / "persona"
    rules = d / "rules.md"
    body = [f"你是 {skill} 导师的模拟盘决策链里的一步(A 股, 模拟账 10 万起步)。下面是导师画像、规则索引{'、规则全文' if rules.exists() and rules.stat().st_size <= RULES_INLINE_MAX else ''}。"
            "判断以这些为准, 引用规则写编号; 风格跟导师走(拟人), 教训可以让你偏离导师但要写理由。所有输出用中文。材料已经全部给你, 不要说要读文件, 不要编造材料里没有的数字。",
            "# 导师画像 profile.md\n" + rd(d / "profile.md"), "# 规则索引 rules_index.md\n" + rd(d / "rules_index.md")]
    if rules.exists() and rules.stat().st_size <= RULES_INLINE_MAX:
        body.append("# 规则全文 rules.md\n" + rd(rules))
    return "\n\n".join(body)


ASK = {
    "02": """【第 02 步 市况】写本时点的市况段(篇幅不限, 按需要写; 10/21 晚用户定不定死字数): 状态 / 态度(偏多 / 中性 / 偏空) / 最多 3 个方向 / 和上一版比变了什么 / 3~4 条证据(必须引用 01 里开盘实况的机械判定或指数数字) / 多日展望(按 01 给的天数) / 开盘至今情景解读(竞价结果、开盘情景兑现了哪个、翻转序列、指数与主线走势, 你自己判断写多少)。
机械判定和你的结论不一致时写理由。最后给 ```json {"state": "...", "attitude": "偏多|中性|偏空", "directions": ["..."], "changed": "...", "horizon_days": N, "mismatch": "无|理由"}""",
    "03b": """【第 03 步 多方】你是多方。基于 01 事实和 02 市况, 为"现在该积极做"写恰好 3 条论点, 每条引用一个 01 里的具体数字(写出数字)或一个规则编号。不写空话。
最后 ```json {"score": 0~100(多方把握), "args": [{"claim": "...", "cite": "..."}], "key_risk": "多方最怕什么"}""",
    "03r": """【第 03 步 空方】你是空方。基于 01 事实和 02 市况, 为"现在该收缩 / 不动 / 减仓"写恰好 3 条论点, 每条引用一个 01 里的具体数字(写出数字)或一个规则编号。不写空话。
最后 ```json {"score": 0~100(空方把握), "args": [{"claim": "...", "cite": "..."}], "key_risk": "空方最怕什么"}""",
    "04": """【第 04 步 选票】只能从 01 候选池里选(写行号)。目标是像导师一样赚钱且稳: 先看材料里「本导师各打法的真实战绩」和「当前候选 ↔ 导师历史上最像的买点」——优先导师历史上赚钱的打法和位置, 导师自己都亏钱的打法(5 日均收益为负、胜率低)要写理由才做。对每只持仓给动作(持有 / 加 / 减 / 清), 新开仓按导师节奏和能力圈(空仓 10 万时要建仓, 不要因为"没候选"空着)。
每只写: 目标仓位% / 打法(打板 / 低吸 / 半路 / 趋势 / 做T…) / 理由(引用池里的盘中特征数字 + 规则编号) / 权衡了多空哪条。篇幅 300~600 字。
最后 ```json {"picks": [{"row": 行号, "code": "...", "action": "建|加|减|清|持有|观望", "target_pct": 数字, "play": "...", "why": "...", "rules": ["编号"]}], "cash_pct": 数字}""",
    "05": """【第 05 步 风控】(10/21 晚用户定: 05 只管两项; 拟人度 / 单票仓位由 06 的五维拟人自检管; 交易规则类硬拦——方向 / 涨跌停 / 股数 / T+1 / 现金——由脚本最后做, 你都不用管)
对 04 的选票判断两项, 每项一句话并给结论:
① 过度交易: 今天已成交几笔、和导师日均出手比(看下面的统计), 本轮还该不该新开、最多新开几笔
② 当日亏损: 今天模拟账盈亏多少(看下面的统计), 要不要收手 / 暂停新买(卖出和减仓不受限)
最后 ```json {"checks": [{"item": "过度交易|当日亏损", "verdict": "放行|限制|拦", "why": "..."}], "max_new_trades": 本轮最多新开几笔(整数, 不限写 -1), "pause_buy": true|false}""",
    "06": """【第 06 步 终裁】把 04 的选票按 05 的限制落成执行器规则。执行器每 3 秒读盘口, 只按你写的规则机械成交; 出区间 / 有成交 / 市况翻转 / 心跳到点才会再叫整条链。
策略要覆盖"涨了怎么办 / 跌了怎么办"两头。(旧链踩过的坑, 10/21 晚并入) 这是模拟盘, 没有用户: 不许把任何决定交给用户 / 待确认; 不动也要在 view 里写清为什么不动; 维持上一版的单就原样写回(价格 / 数量 / 方向不变), 不要换锚重下。先写规则, 再写五维拟人自检(持股只数 / 单票仓位 / 开仓时段 / 持有期 / 能力圈, 每维一句: 像 / 不像 + 不像的理由或已改写), 再写下一轮预期和失效条件。
硬约束: BUY 只能 op "<=", SELL 只能 op ">="(限价思路); px 在涨跌停之间; qty 为 100 的整数倍(卖出可等于全部可卖); 同一只票所有 BUY 合计不超过现金, SELL 合计不超过今天可卖; band = 出了就重新叫链的价格区间(一般 ±0.5~1.5 倍日振幅); 只能写候选池里的代码。
{auction}
rest_of_day: 你判断今天剩下的时间不会再主动操作了(例: 已满仓或接近满仓、按导师节奏今天已做完、只等明天处理), 就写 stop=true 并写理由——之后执行器只按你挂的规则机械成交, 不再因心跳 / 出区间 / 翻转叫你(固定时刻的版本和本链成交照样会叫); 还要看盘就写 false。
最后只要一个 ```json {{"view": "一句话: 现在怎么打、为什么(引规则编号)", "codes": [{{"code": "...", "name": "...", "band": [下沿, 上沿], "rules": [{{"id": "r1", "side": "BUY|SELL", "op": "<=|>=", "px": 价格, "qty": 股数, {auc_field}"why": "规则编号+理由"}}]}}], "next": "下一轮预期", "invalid": "失效条件", "rest_of_day": {{"stop": true|false, "why": "..."}}, "mimic": "五维自检一句话汇总", "valid_until": "HH:MM"}}""",
}


def run(skill, D, at, why, state, strategy, fired, quotes, facts, open_text, prev02, out_dir, live=True, budget=CHAIN_BUDGET, effort="low", step_scale=1.0, pre01=None, tag_skill=None, tool_mode=False, model=None):
    """返回 (strategy 或 None, 花费美元, timing dict)。strategy 和 exec_base 现有格式一致, 外加 next / invalid / mimic / chain 字段"""
    t0 = time.time()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    T = {"start": dt.datetime.now().strftime("%H:%M:%S"), "at": at, "why": why, "steps": {}}
    # pre01: 调用方已建好的 01(正式链和 high 陪跑链共用同一份快照, 10/21 晚 ★10 实验 1)
    f01, P, px, nav = pre01 if pre01 else build_01(skill, D, at, why, state, strategy, fired, quotes, facts, open_text, prev02, live)
    (out / "01_facts.md").write_text(f01, encoding="utf-8")
    T["steps"]["01"] = {"secs": round(time.time() - t0, 1), "pool": len(P), "chars": len(f01)}
    nm = names(D)
    pool_names = [nm.get(c) for c in P if nm.get(c)]
    cited = cited_ids(skill, strategy, [prev02])
    stable, var, pinfo = persona(skill, cited, pool_names, list(P))
    # 10/21 晚用户定: skills / 07 复盘 / md 原文 / 今日更早版本推理 / 拓扑 —— 脚本按本次涉及的票和规则编号检索, 摘相关段落附上(零 token)
    try:
        import chain_lookup as LK
        live_dir = out.parent.parent if out.parent.name == "versions" else None
        vdone = sorted(d.name for d in (live_dir / "versions").glob("*") if d.is_dir() and (d / "06_final.md").exists()) if live_dir else []
        focus = list(dict.fromkeys([*state.get("positions", {}), *[str(x.get("code")) for x in (strategy or {}).get("codes") or []],
                                    *[c for c, src_ in P.items() if src_ in ("持仓", "上一版策略", "导师本人")]]))[:12]
        pk = LK.auto_pack(skill, D, focus, [nm.get(c) for c in focus], cited, live_dir=live_dir, skip_ver=vdone[-1] if vdone else None,
                           feats={c: LAST_FEATS[c] for c in list(dict.fromkeys([*focus, *P]))[:8] if c in LAST_FEATS})
        var = var + "\n\n" + pk
        pinfo["lookup_kb"] = round(len(pk.encode()) / 1024, 1)
    except Exception as e:   # noqa: BLE001
        pinfo["lookup_err"] = repr(e)[:120]
    T["steps"]["01"]["persona"] = {**pinfo, "stable_kb": round(len(stable.encode()) / 1024, 1), "var_kb": round(len(var.encode()) / 1024, 1), "cited": cited}
    (out / "01_persona.md").write_text(f"{stable}\n\n{var}", encoding="utf-8")
    # 缓存断点: 常驻块(画像摘要 / 目录 / 规则索引 / 指纹, 一天不变) → 按需原文 + 01 事实(本次触发内 6 次调用共用)
    sysb = [(stable, "5m"), var, (f01, "5m")]
    cost = 0.0

    def left():
        return budget - (time.time() - t0)

    def sc(k):   # 测试用: 按倍数放大每步 max_tokens 与时限(effort=high 时思考更多, 不放大会撞上限)
        return int(STEP[k][0] * step_scale), STEP[k][1] * step_scale

    tools_ = None
    if tool_mode:   # 对照变体 C(@toolcall): 模型可以自己调 lookup 查料, 每步最多 2 次
        import chain_lookup as LK2
        _ld = out.parent.parent if out.parent.name == "versions" else None
        tools_ = {"defs": [LK2.TOOL], "max_calls": 2,
                  "run": lambda name, args: LK2.lookup(skill, D, _ld, (args or {}).get("query"), (args or {}).get("source") or "all")}

    def call(step, user, mt, lim, own=False, floor=0, eff=None):
        """own=True: 本步用自己的时限, 不和整条预算抢(10/21 晚: 05)"""
        dl = lim if own else max(floor, min(lim, max(5, left() - 5)))   # floor: 本步保底秒数(10/22: 06 保底 60 秒, 关键节点不被前面卡死饿死)
        r = API.stream(system=sysb, user=user, tools=tools_, model=model, tag=f"se-chain-{tag_skill or skill}-{'shadow-' if str(why).startswith('(影子)') else ''}{eff or effort}-{step}", max_tokens=mt, effort=eff or effort, deadline_s=dl,
                       first_byte_s=FIRST_BYTE.get(step[:2]))
        T["steps"][step] = {"secs": r.secs, "ttft": r.ttft, "first_ev": r.first_ev, "gate_wait": r.gate_wait, "stuck_retry": r.stuck_retry, "ok": r.ok, "out": (r.usage or {}).get("output_tokens"), "cache_read": (r.usage or {}).get("cache_read_input_tokens"),
                            "cache_write": (r.usage or {}).get("cache_creation_input_tokens"), "usd": r.cost_usd, "err": r.error[:120]}
        (out / f"{step}.md").write_text(r.text or f"(失败: {r.error})", encoding="utf-8")
        return r

    # 02
    r2 = call("02_market", ASK["02"], *sc("02"))
    cost += r2.cost_usd
    m02 = r2.text if r2.ok else f"(02 失败, 降级用机械市况)\n{open_text}"
    # 03 多 ∥ 空
    u3 = f"## 本次 02 市况\n{m02}\n\n"
    with cf.ThreadPoolExecutor(2) as ex:
        fb, fr = ex.submit(call, "03_bull", u3 + ASK["03b"], *sc("03")), ex.submit(call, "03_bear", u3 + ASK["03r"], *sc("03"))
        rb, rr = fb.result(), fr.result()
    cost += rb.cost_usd + rr.cost_usd
    sb, sr = (rb.json or {}).get("score"), (rr.json or {}).get("score")
    div = abs((sb or 50) - (sr or 50))
    d03 = (f"## 03 多方(把握 {sb})\n{rb.text if rb.ok else '(多方失败)'}\n\n## 03 空方(把握 {sr})\n{rr.text if rr.ok else '(空方失败)'}\n\n分歧度 {div}"
           if (rb.ok or rr.ok) else "(03 两边都失败, 本次无辩论)")
    # 04
    r4 = call("04_pick", f"## 02 市况\n{m02}\n\n{d03}\n\n" + ASK["04"], *sc("04"))
    cost += r4.cost_usd
    if not r4.ok and len(r4.text or "") >= 400 and not r4.error.startswith("卡死"):   # 10/22 用户令: 写了大半被时限掐断 / 没写 json 块 ≠ 系统错, 用已写的部分接着走(04 正文就是给 06 读的)
        r4.ok = True
        T["steps"]["04_pick"]["salvaged"] = f"部分输出 {len(r4.text)} 字照用({r4.error[:40]})"
    if not r4.ok:
        T["result"] = "04 失败, 本次作废沿用上一版"
        T["total"] = round(time.time() - t0, 1)
        (out / "timing.json").write_text(json.dumps(T, ensure_ascii=False, indent=1), encoding="utf-8")
        return None, cost, T
    # 05
    stats = mimic_stats(skill, D, state, px)
    # 10/21 晚用户定: 05 永远跑、用自己的时限; 超时 / 失败 → 直接放行(不重试、不作废、不用脚本凑), 06 补判 05 里它没覆盖的两项
    r5 = call("05_risk", f"## 04 选票\n{r4.text}\n\n## 拟人统计(脚本)\n{stats}\n\n" + ASK["05"], *sc("05"), own=True)
    cost += r5.cost_usd
    if r5.ok:
        d05 = r5.text
    else:
        T["steps"]["05_risk"]["passed"] = "05 超时 / 失败放行, 06 补判过度交易与当日亏损"
        d05 = ("(05 本次超时未判, 已放行。请你在写规则之前先各写一句: ① 过度交易——今天已成交笔数和导师日均出手比, 要不要少做;"
               " ② 当日亏损——今天盈亏多少, 要不要收手。拟人度和单票仓位照你的五维自检。)\n" + stats)
    # 06
    pre = at < "09:25:00"
    a06 = ASK["06"].format(auction="现在是集合竞价阶段: 想在 09:25 竞价成交的规则加 \"auction\": true(按 09:25 撮合价一次成交: 买价 ≥ 撮合价 / 卖价 ≤ 撮合价), 没加的规则 09:30 起才生效。" if pre else "",
                           auc_field='"auction": true|false, ' if pre else "")
    u6 = f"## 02 市况\n{m02}\n\n## 04 选票\n{r4.text}\n\n## 05 风控\n{d05}\n\n" + a06
    r6 = call("06_final", u6, *sc("06"), floor=60)
    cost += r6.cost_usd
    # 10/22 用户令(06 失败分原因): ①写了但没写完(时限掐断 / 没出 json 块) → 不作废: 已写部分里有完整 json 就照用, 没有就让它按草稿立刻收尾出 json ②卡死 / API 报错(一个字没有) → 才作废重试
    if not r6.ok and r6.text:
        j6 = API.last_json(r6.text)
        if isinstance(j6, dict) and j6.get("codes") is not None:
            r6.json, r6.ok = j6, True
            T["steps"]["06_final"]["salvaged"] = "截断前已写出完整 json, 照用"
        elif len(r6.text) >= 200:
            n6 = len(r6.text)
            rf = call("06_finish", u6 + f"\n\n## 你上一轮已写的草稿(时限到被截断, 没写完)\n{r6.text[-6000:]}\n\n**现在只做一件事: 按草稿已有的结论, 立刻输出最终 ```json 块(字段同上面要求), 不要再分析, json 之外最多 3 句话。**",
                      *sc("06"), own=True, eff="low")   # 收尾只是照草稿誊 json, 用 low 求快(不是 low 实验)
            cost += rf.cost_usd
            if rf.ok and isinstance(rf.json, dict) and rf.json.get("codes") is not None:
                r6 = rf
                T["steps"]["06_final"]["salvaged"] = f"草稿 {n6} 字 → 06_finish 收尾出 json"
    T["total"] = round(time.time() - t0, 1)
    T["usd"] = round(cost, 4)
    s = None
    if r6.ok and isinstance(r6.json, dict) and r6.json.get("codes") is not None:
        s = r6.json
        s["chain"] = {"02": r2.json, "03": {"bull": sb, "bear": sr, "div": div}, "04": r4.json, "05": (r5.json if r5 is not None else None)}
        T["result"] = "ok"
    else:
        T["result"] = f"06 失败({r6.error}), 本次作废沿用上一版" + ("(卡死 / API 错, 无草稿可收尾)" if not r6.text else "(收尾也没出 json)")
    for k, r in (("02_market", r2), ("03_bull", rb), ("03_bear", rr), ("04_pick", r4), ("05_risk", r5), ("06_final", r6)):
        if r is not None and r.json is not None:
            (out / f"{k}.json").write_text(json.dumps(r.json, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "timing.json").write_text(json.dumps(T, ensure_ascii=False, indent=1), encoding="utf-8")
    return s, cost, T


# ---------------- 离线回放(测耗时 / 看质量) ----------------
def replay(skill, D, at, why, effort):
    base = ROOT / "results" / "_live" / D / f"se_{skill}"
    stj = jl(base / "state.json", {}) or {}
    start = stj.get("start") or {"cash": 100000.0, "positions": {}}
    state = {"cash": float(start.get("cash") or 0), "positions": json.loads(json.dumps(start.get("positions") or {})), "trades": []}
    for t in stj.get("trades") or []:   # 起点 + 回放时刻之前的成交 = 当时的账
        if t["t"] >= at:
            continue
        p = state["positions"].setdefault(t["code"], {"qty": 0, "cost": t["px"], "sellable": 0})
        amt = t["px"] * t["qty"]
        if t["side"] == "BUY":
            p["cost"] = ((p.get("cost") or 0) * p["qty"] + amt) / (p["qty"] + t["qty"])
            p["qty"] += t["qty"]
            state["cash"] -= amt + (t.get("fee") or 0)
        else:
            p["qty"] -= t["qty"]
            p["sellable"] = max(0, p.get("sellable", 0) - t["qty"])
            state["cash"] += amt - (t.get("fee") or 0)
            if p["qty"] <= 0:
                state["positions"].pop(t["code"])
        state["trades"].append(t)
    vs = [f for f in sorted((base / "strategies").glob("*.json")) if f.name[3:7] <= at.replace(":", "")[:4]]
    sj = jl(vs[-1], {}) if vs else {}
    strategy, fired = (sj or {}).get("strategy"), set((sj or {}).get("fired") or [])
    facts = rd(base / "facts.txt")
    import exec_base as E
    o = jl(MKT / D / "open_live.json", {}) or {}
    J = [j for j in o.get("judgments") or [] if j.get("t", "") <= at.replace(":", "")[:4]]
    open_text = (f"最新判定 {J[-1].get('t')}: {J[-1].get('label')}(分 {J[-1].get('score')})\n" + "\n".join(f"- {x}" for x in J[-1].get("factors") or [])) if J else "(开盘实况还没出判定)"
    out = ROOT / "results" / "inv-stock" / "paper" / "chain_replay" / D / skill / at.replace(":", "")
    s, cost, T = run(skill, D, at, why, state, strategy, fired, {}, facts, open_text, None, out, live=False, effort=effort)
    if s:
        s2, dropped = E.SE.check(type("X", (), {"state": state, "D": D, "codes": lambda self=None: list(state["positions"]), "facts_codes": lambda self=None: set(re.findall(r"\d{6}", rd(out / "01_facts.md")))})(), s)
        T["dropped"] = dropped
        (out / "timing.json").write_text(json.dumps(T, ensure_ascii=False, indent=1), encoding="utf-8")
    return T, out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--at", required=True, help="HH:MM:SS 回放时刻")
    ap.add_argument("--why", default="离线回放")
    ap.add_argument("--effort", default="low")
    a = ap.parse_args()
    T, out = replay(a.skill, a.date, a.at, a.why, a.effort)
    print(json.dumps({k: v for k, v in T.items() if k != "why"}, ensure_ascii=False))
    print("落盘:", out)


if __name__ == "__main__":
    main()
