# -*- coding: utf-8 -*-
"""kline_reader.py — K 线识别器 v0(10/26 15:2x 用户令: "先做 K 线识别器, 预测 K 线也好、让你读 K 线和我的理解对齐也好, 先做出来"; 零 token)

一只票 + 一天(+ 可选截至时刻) → 用术语表(scripts/live/glossary.yaml)和用户口径的词, 机械地读出:
  ①日线层  近期 N 天 M 板 / 当前连板 / 昨日状态 / 20·60 日位置 / 均线关系
  ②分时层  开盘方式 · 板型(一字 / T字 / 厂字(一路拉板)/ 回封 / 烂板回封 / 炸板 / 烂板)· 上板方式(低开分波 / 午后封 / 直线拉板)
            · 波段(每一波起止时刻 / 价 / 幅度)· 均价关系(全天在上 / 跌破均价后企稳)· 横盘蓄势段 · 冲高A杀 · 收盘位置
  每个标签都带证据(时刻 + 价), 不许没有数字的结论; 读不出来就写"无"
数据: 日线 downloads/quotes/daily/<代码>.json · 1 分钟线 downloads/market/<日>/kline_minute_live.jsonl(带均价)· 3 秒盘口(tape.seal_story 秒级封板过程)
用途: 截图收件 / 盘中二次确认 / U 规则机械口径 / v2 预测特征 / 主会话读盘 都调这个, 口径只有一份
用法: python kline_reader.py 002696 [--date 2026-10-26] [--at 13:40] [--json]
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(ROOT / "scripts" / "live")]
MKT = ROOT / "downloads" / "market"
QD = ROOT / "downloads" / "quotes" / "daily"

P = {
    "WAVE_MIN": 0.015,     # 波段最小幅度(相对价格; 再取 max(本值, 0.35 × 30 日振幅中位))
    "BOX_MIN": 15,         # 横盘蓄势至少多少分钟
    "BOX_RANGE": 0.025,    # 横盘期间振幅上限(10cm 口径, 20cm ×2)
    "LINE_UP": 0.05,       # 直线拉板: 1 分钟内涨幅(10cm 口径)
    "LINE_FLAT": 0.02,     # 直线拉板前 30 分钟振幅上限
    "DEEP_OPEN": -0.03,    # 低开分波: 开盘 ≤ −3%
    "ASHA_UP": 0.05,       # 冲高A杀: 最高 ≥ +5% 且收盘 ≤ 最高 −6%(scen_v2 同口径)
    "ASHA_DROP": 0.06,
}


def _f(x):
    return f"{x:+.2f}%"


def daily(code, D, n=400):
    f = QD / f"{code}.json"
    ks = [k for k in json.loads(f.read_text(encoding="utf-8")).get("klines") or [] if k.get("d", "") <= D] if f.exists() else []
    if len(ks) >= 300 or ks and not str(code).isdigit():
        return ks
    # 10/26 晚: downloads/quotes/daily 只有 1610 只(榕基软件 / 南方路机 / 平安电工 都没有)→ 退回行情库 kline_day(只读)
    try:
        import db_ro
        import tape as TP
        c = db_ro.connect("investment_market")
        try:
            with c.cursor() as cur:
                cur.execute("select trade_date, open, high, low, close, volume from kline_day where is_deleted=0 and symbol=%s and trade_date<=%s and open>0 "
                            "order by trade_date desc limit %s", (TP.sym(code), D, n))
                rows = cur.fetchall()
        finally:
            c.close()
    except Exception:   # noqa: BLE001 库连不上就用文件里的
        return ks
    db = [{"d": str(r[0])[:10], "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4]), "v": float(r[5] or 0)} for r in reversed(rows)]
    return db if len(db) > len(ks) else ks


def minutes(code, D, at=None):
    import tape as TP
    s, out = TP.sym(code), []
    full, live = MKT / D / "kline_minute.jsonl", MKT / D / "kline_minute_live.jsonl"
    # 10/26: 收盘后有全天分钟线(通达信, 241 根)就用它; 盘中只有 live(只录盘口池里的票, 可能缺前半天)
    f = full if full.exists() and (not at or at >= "15:00") else live
    if f.exists():
        for l in f.open(encoding="utf-8"):
            if s not in l[:30]:
                continue
            j = json.loads(l)
            if j.get("symbol") != s:
                continue
            t = j["barTime"][11:16]
            if at and t > at:
                continue
            out.append({"t": t, "o": j["open"], "h": j["high"], "l": j["low"], "c": j["close"], "v": j.get("volume") or 0, "avg": j.get("avgPrice")})
    out.sort(key=lambda r: r["t"])
    if not out and f == full and live.exists():   # 全天分钟线没有这只(例 转债不在通达信文件里)→ 退回 live
        return minutes_file(code, live, at)
    return out


def minutes_file(code, f, at=None):
    import tape as TP
    s, out = TP.sym(code), []
    for l in f.open(encoding="utf-8"):
        if s not in l[:30]:
            continue
        j = json.loads(l)
        if j.get("symbol") != s:
            continue
        t = j["barTime"][11:16]
        if at and t > at:
            continue
        out.append({"t": t, "o": j["open"], "h": j["high"], "l": j["low"], "c": j["close"], "v": j.get("volume") or 0, "a": j.get("amount") or 0, "avg": j.get("avgPrice")})
    return sorted(out, key=lambda r: r["t"])


def zigzag(ms, thr):
    """按收盘价分波: 反向走出 thr 才确认上一个拐点 → [(t, 价, 'H'/'L')]"""
    if not ms:
        return []
    piv, dirn, ext, ext_t = [(ms[0]["t"], ms[0]["o"], "S")], 0, ms[0]["o"], ms[0]["t"]
    for r in ms:
        hi = lo = r["c"]   # 按收盘价分波(用最高最低会在同一根里来回确认, 碎波太多)
        if dirn >= 0:
            if hi >= ext:
                ext, ext_t = hi, r["t"]
                dirn = 1 if hi > piv[-1][1] * (1 + thr) or dirn == 1 else dirn
            if dirn == 1 and lo <= ext * (1 - thr):
                piv.append((ext_t, ext, "H"))
                dirn, ext, ext_t = -1, lo, r["t"]
        if dirn <= 0:
            if lo <= ext:
                ext, ext_t = lo, r["t"]
                dirn = -1 if lo < piv[-1][1] * (1 - thr) or dirn == -1 else dirn
            if dirn == -1 and hi >= ext * (1 + thr):
                piv.append((ext_t, ext, "L"))
                dirn, ext, ext_t = 1, hi, r["t"]
    piv.append((ext_t, ext, "H" if dirn == 1 else "L" if dirn == -1 else "E"))
    return piv


def dn_story(code, D, dn, at=None):
    """跌停过程(秒级, 3 秒盘口): 首次封跌停 / 每次开板(多久、反弹到多少)/ 是否二封; 封跌停 = 价在跌停且买一空"""
    import tape as TP
    B = [r for r in TP.book(code, D) if 34200 <= r[0] < 53820 and (not at or r[1][:5] <= at)]
    if not B or not dn:
        return None
    sealed = lambda r: r[2] <= dn + 0.005 and not (r[5] and float(r[5][0][0] or 0) > 0 and int(r[5][0][1] or 0) > 0)   # noqa: E731
    first, opens, cur = None, [], None
    for r in B:
        s_ = sealed(r)
        if s_ and first is None:
            first = r[1]
        if first and not s_ and cur is None:
            cur = {"开": r[1], "最高": r[2], "x0": r[0]}
        elif cur is not None:
            if s_:
                cur.update(二封=r[1], 开了秒=r[0] - cur["x0"])
                opens.append(cur)
                cur = None
            else:
                cur["最高"] = max(cur["最高"], r[2])
                if r[0] - cur["x0"] <= 300:
                    cur["5分钟内最高"] = max(cur.get("5分钟内最高", r[2]), r[2])
    if cur is not None:
        cur["二封"] = None
        opens.append(cur)
    return {"首封跌停": first, "开板": opens, "收盘封跌停": bool(B and sealed(B[-1]))}


def auction(code, D, pc, up, dn, tick):
    """开盘集合竞价路径 → {读: 一句话, 类型, ...}; 没数据 → None"""
    import tape as TP
    f = MKT / D / "auction_live_open.json"
    if not f.exists() or not pc:
        return None
    try:
        a = (json.loads(f.read_text(encoding="utf-8")).get("symbols") or {}).get(TP.sym(code))
    except ValueError:
        return None
    if not a or not (a.get("fin") or {}).get("px"):
        return None
    def lv(px):
        return "跌停" if dn and px <= dn + tick / 2 else "涨停" if up and px >= up - tick / 2 else _f((px / pc - 1) * 100)
    def um(x):
        u = x.get("unm")
        return "" if u in (None, 0) else f"(未匹配{'买' if u > 0 else '卖'} {abs(u) / 1e4:.1f} 万股)"
    p1, p2f, p2, fin = a.get("p1") or {}, a.get("p2_first") or {}, a.get("p2") or {}, a["fin"]
    s0 = f"09:20 前 {lv(p1['px'])}{um(p1)}" if p1.get("px") else ""
    s1 = f"09:24:57 {lv(p2['px'])}{um(p2)}" if p2.get("px") else ""
    s2 = f"09:25 开 {fin['px']:g}({lv(fin['px'])})"
    d = (fin["px"] / pc - 1) * 100 - (p2f.get("pct") if p2f.get("pct") is not None else (fin["px"] / pc - 1) * 100)
    kind = None
    at_dn = lambda x: dn and x.get("px") and x["px"] <= dn + tick / 2   # noqa: E731
    at_up = lambda x: up and x.get("px") and x["px"] >= up - tick / 2   # noqa: E731
    if (at_dn(p1) or at_dn(p2f)) and not at_dn(fin):
        kind = f"竞价跌停被抢上来(开 {lv(fin['px'])}, 比 09:20 抬 {d:+.1f} 个点)"
    elif (at_dn(p1) or at_dn(p2f)) and at_dn(fin):
        kind = "竞价一直跌停, 跌停开" + ("(最后 5 秒未匹配变成买单 = 有人在跌停价接)" if (p2.get("unm") or 0) > 0 else "")
    elif (at_up(p1) or at_up(p2f)) and not at_up(fin):
        kind = f"竞价涨停被砸下来(开 {lv(fin['px'])}, 比 09:20 {d:+.1f} 个点)"
    elif abs(d) >= 2:
        kind = f"9:20 后{'抬价' if d > 0 else '压价'} {d:+.1f} 个点"
    tags = "、".join(a.get("tags") or [])
    txt = " → ".join(x for x in (s0, s1, s2) if x) + (f"; {kind}" if kind else "") + (f"; {tags}" if tags else "")
    return {"读": txt, "类型": kind, "开": fin["px"], "09:20": p2f.get("px"), "量比昨日": a.get("vol_ratio")}


def close_auction(code, D, pc, up, dn, tick, ms):
    import tape as TP
    f = MKT / D / "auction_live_close.json"
    if not f.exists() or not pc:
        return None
    try:
        a = (json.loads(f.read_text(encoding="utf-8")).get("symbols") or {}).get(TP.sym(code))
    except ValueError:
        return None
    if not a or not (a.get("fin") or {}).get("px"):
        return None
    pre = next((r for r in reversed(ms) if r["t"] <= "14:56"), None)
    p0 = pre["c"] if pre else None
    fin, p1 = a["fin"]["px"], a.get("p1") or {}
    def lv(px):
        return "涨停" if up and px >= up - tick / 2 else "跌停" if dn and px <= dn + tick / 2 else _f((px / pc - 1) * 100)
    u = p1.get("unm")
    um = "" if u in (None, 0) else f", 最后未匹配{'买' if u > 0 else '卖'} {abs(u) / 1e4:.1f} 万股"
    rng = f", 竞价区间 {_f(a['p1_lo'])}~{_f(a['p1_hi'])}" if a.get("p1_lo") is not None and a.get("p1_hi") is not None and a["p1_lo"] != a["p1_hi"] else ""
    d = (fin / p0 - 1) * 100 if p0 else 0.0
    kind = ("尾盘竞价抢筹(收盘比 14:56 抬 {:+.2f}%)".format(d) if d >= 0.5 else "尾盘竞价砸盘(收盘比 14:56 {:+.2f}%)".format(d) if d <= -0.5 else "尾盘竞价平稳")
    if up and fin >= up - tick / 2:
        kind += " · 封涨停收" + ("(未匹配买单堆着 = 明天有溢价预期)" if (u or 0) > 0 else "")
    txt = (f"14:56 {p0:g}({lv(p0)}) → " if p0 else "") + f"15:00 收 {fin:g}({lv(fin)}){rng}{um}; {kind}; 竞价量 = 昨日全天 {a.get('vol_ratio', 0) * 100:.1f}%"
    return {"读": txt, "类型": kind, "收": fin, "14:56": p0}


def read(code, D, at=None):
    import signals as G
    import tape as TP
    m = G.Meta(D).get(code)
    pc, up, dn, tick = m.get("prev"), m.get("up"), m.get("dn"), m.get("tick") or 0.01
    lim = (up / pc - 1) if (up and pc) else 0.1
    k = 0.1 / lim if lim else 1          # 20cm 票阈值 ×2
    amp = m.get("amp30") or 0.05
    out = {"code": code, "name": m.get("name"), "D": D, "截至": at or "收盘", "昨收": pc, "涨停价": up, "跌停价": dn, "日线": {}, "分时": {}, "读盘稿": []}
    say = out["读盘稿"].append

    # ---------- ①日线层(截至 T−1; 今天在分时层) ----------
    ks = [x for x in daily(code, D) if x["d"] < D]
    if len(ks) >= 2:
        def is_zt(a, b):
            return b["c"] >= round(a["c"] * (1 + lim), 2) - 0.005
        zts = [ks[i]["d"] for i in range(1, len(ks)) if is_zt(ks[i - 1], ks[i])]
        last20 = [x["d"] for x in ks[-20:]]
        z20 = [d for d in zts if d in last20]
        streak = 0
        for i in range(len(ks) - 1, 0, -1):
            if is_zt(ks[i - 1], ks[i]):
                streak += 1
            else:
                break
        if z20:
            n = len(last20) - last20.index(z20[0])
            out["日线"]["近期"] = f"{n}天{len(z20)}板"
        out["日线"]["T−1 连板"] = streak
        a, b = ks[-2], ks[-1]
        touch = b["h"] >= round(a["c"] * (1 + lim), 2) - 0.005
        st = "涨停" if is_zt(a, b) else "炸板(触板没封住)" if touch else "跌停" if b["c"] <= round(a["c"] * (1 - lim), 2) + 0.005 else f"{_f((b['c'] / a['c'] - 1) * 100)}"
        out["日线"]["T−1"] = st
        h20, l20 = max(x["h"] for x in ks[-20:]), min(x["l"] for x in ks[-20:])
        out["日线"]["20日位置%"] = round((b["c"] - l20) / (h20 - l20) * 100) if h20 > l20 else None
        ma = lambda n_: sum(x["c"] for x in ks[-n_:]) / n_ if len(ks) >= n_ else None   # noqa: E731
        m5, m20 = ma(5), ma(20)
        out["日线"]["均线"] = ("MA5 上" if m5 and b["c"] >= m5 else "MA5 下") + (" / MA20 上" if m20 and b["c"] >= m20 else " / MA20 下" if m20 else "")
        # 长期压力(10/26 晚用户图: 榕基软件 涨停价 7.82 刚过 MA300 7.68、南方路机 涨停价 35.17 ≈ MA300 35.10, 都是竞价顶板 → 开盘封 → 炸; 长期均线 / 前高 = 套牢盘解放位)
        pres = []
        upx = round(b["c"] * (1 + lim), 2)
        for n_ in (144, 250, 300):
            mv = ma(n_)
            if mv and b["c"] < mv * 1.03 and abs(upx / mv - 1) <= 0.03:
                pres.append(f"MA{n_} {mv:.2f}(离今天涨停价 {_f((mv / upx - 1) * 100)})")
        if len(ks) >= 120:
            h_ = max(x["h"] for x in ks[-250:-20]) if len(ks) > 40 else None
            if h_ and b["c"] < h_ and abs(upx / h_ - 1) <= 0.03:
                pres.append(f"前高 {h_:g}(20~250 日前, 离今天涨停价 {_f((h_ / upx - 1) * 100)})")
        if pres:
            out["日线"]["长期压力"] = pres
        say(f"日线: {out['日线'].get('近期', '近 20 日无涨停')}, T−1 {st}(连板 {streak}), 20 日位置 {out['日线']['20日位置%']}%, {out['日线']['均线']}"
            + (f"; 今天涨停价贴着长期压力: {' / '.join(pres)}(只是位置描述: 全市场 2024~2026 主板触板封住率 贴线 63.7% n=4960 vs 其余 67.8% n=54475, 2025 年后无差别 → 不当炸板信号; scripts/temp/ma_pressure_stat.py)" if pres else ""))

    # ---------- ②分时层 ----------
    ms = minutes(code, D, at)
    if not ms or not pc:
        say("分时: 没有 1 分钟线")
        return out
    o = ms[0]["o"]
    late = ms[0]["t"] > "09:31"
    if late:   # 盘中才进盘口池(例 东百集团 11:00), 第一根不是开盘 → 开盘价用 09:25 竞价撮合价
        au0 = auction(code, D, pc, up, dn, tick)
        if au0 and au0.get("开"):
            o = au0["开"]
        say(f"注意: 1 分钟线从 {ms[0]['t']} 才有(盘中才进盘口池), 之前的走势读不到; 最高 / 最低 / 波段只算 {ms[0]['t']} 以后")
    hi = max(r["h"] for r in ms)
    lo = min(r["l"] for r in ms)
    c = ms[-1]["c"]
    t_hi = next(r["t"] for r in ms if r["h"] == hi)
    t_lo = next(r["t"] for r in ms if r["l"] == lo)
    og = (o / pc - 1) * 100
    if up and o >= up - tick / 2 and lo >= up - tick / 2:
        op = "一字板"
    elif dn and o <= dn + tick / 2:
        op = "跌停开"
    elif up and o >= up - tick / 2:
        op = "涨停开"
    else:
        op = "高开" if og >= 0.5 else "低开" if og <= -0.5 else "平开"
    out["分时"]["开盘"] = f"{op} {o:g}({_f(og)})"
    # 竞价层(10/26 用户: 百洋股份"竞价跌停、被抢到 −7.3% 开"是关键信息, 原来漏了) —— auction_live_open.json: 09:20 前(可撤)/ 09:20~09:25(不可撤)/ 09:25 撮合
    au = auction(code, D, pc, up, dn, tick)
    if au:
        out["竞价"] = au
        say("竞价: " + au["读"])
    say(f"开盘: {out['分时']['开盘']}; 日内最高 {hi:g}({_f((hi / pc - 1) * 100)}, {t_hi}) 最低 {lo:g}({_f((lo / pc - 1) * 100)}, {t_lo}) 现/收 {c:g}({_f((c / pc - 1) * 100)})")

    # 板型(3 秒盘口秒级)
    seal = TP.seal_story(code, D, up) if up and hi >= up - tick / 2 else None
    if seal and seal.get("首封(秒)") and (not at or seal["首封(秒)"][:5] <= at):
        t0, opens = seal["首封(秒)"], [x for x in seal["开板"] if not at or x["开"][:5] <= at]
        closed = seal.get("14:57 时封住") if not at else not (opens and opens[-1].get("回封") is None)
        seg = "早盘" if t0 < "10:30" else "午后" if "13:00" <= t0 < "14:00" else "尾盘" if t0 >= "14:00" else "盘中"
        if op == "一字板":
            bt = "一字板" if not opens else "T字板" if closed else "一字开板(没回封)"
        elif not opens:
            pre_ = [r for r in ms if r["t"] < t0[:5]]
            dd_, pk_ = 0.0, (pre_[0]["h"] if pre_ else 0)
            for r in pre_:
                pk_ = max(pk_, r["h"])
                dd_ = max(dd_, (pk_ - r["l"]) / pk_)
            bt = ("厂字板(开盘一路拉板, 封住不开)" if dd_ < 0.02 else "首封即封死(封板后没开过)") if closed else "炸板"
        elif closed:
            bt = "回封板(开 1 次)" if len(opens) == 1 else f"烂板回封(开 {len(opens)} 次)"
        else:
            bt = "烂板(开 {} 次, 最终没封住)".format(len(opens)) if len(opens) >= 2 else "炸板(开板没回封)"
        out["分时"]["板型"] = f"{bt} · 首封 {t0}({seg})"
        out["分时"]["开板"] = [f"{x['开']} 开 {x.get('开了秒', '?')} 秒 砸到 {x['砸到%']:+.2f}% → {'回封 ' + x['回封'] if x.get('回封') else '没回封'}" for x in opens]
        if seal.get("封单额(万) 首封时 / 最大 / 收盘"):
            a0, amx, acl = seal["封单额(万) 首封时 / 最大 / 收盘"]
            out["分时"]["封单(万)"] = f"首封 {a0} / 最大 {amx}({seal.get('最大封单时刻')}) / 收盘 {acl}"
        if opens and not closed:   # 10/26 晚: 南方路机 烂板后 14:02 再冲到 35.16(差 1 分)没封 → 要写出来
            t_last = opens[-1]["开"][:5]
            re_ = [r for r in ms if r["t"] > t_last and r["h"] >= up - 2.5 * tick and r["t"] > (dt.datetime.strptime(t_last, "%H:%M") + dt.timedelta(minutes=10)).strftime("%H:%M")]
            if re_:
                out["分时"]["再冲未封"] = f"{re_[0]['t']} 再冲到 {re_[0]['h']:g}(离涨停 {round((up - re_[0]['h']) / tick):d} 档)没封住"
        say(f"板型: {out['分时']['板型']}" + (f"; {out['分时']['再冲未封']}" if out["分时"].get("再冲未封") else "") + (f"; 开板 {len(opens)} 次: " + "; ".join(out["分时"]["开板"]) if opens else "") + (f"; 封单 {out['分时'].get('封单(万)')}" if out["分时"].get("封单(万)") else ""))

    # 尾盘集合竞价(14:57~15:00; 10/26 用户: 早盘竞价和尾盘竞价都是重要的盘口语言, 读 K 线不能忽略)
    if not at or at >= "15:00":
        ca = close_auction(code, D, pc, up, dn, tick, ms)
        if ca:
            out["尾盘竞价"] = ca
            say("尾盘竞价: " + ca["读"])

    # 跌停板型 / 地天 / 天地(10/26 用户: 海洋王跌停开这种要认)
    if dn and lo <= dn + tick / 2:
        ds = dn_story(code, D, dn, at) or {}
        t_dn = ds.get("首封跌停") or t_lo
        ops = ds.get("开板") or []
        if op == "跌停开" and (not ds.get("首封跌停") or ds["首封跌停"][:5] > ms[0]["t"]):
            # 跌停开盘、09:30 第一笔就打开(3 秒盘口从 09:30 起录, 抓不到"封着"那段) → 补一条"开盘即打开"
            m5 = [r for r in ms if r["t"] <= "09:35"]
            ops = [{"开": "09:30 开盘即打开", "最高": max(r["h"] for r in m5) if m5 else o, "5分钟内最高": max(r["h"] for r in m5) if m5 else o,
                    "二封": ds["首封跌停"] if ds.get("首封跌停") else None}] + ops
        if op == "跌停开":
            kind = "一字跌停" if not ops else ("跌停开·开板后二封跌停" if ds.get("收盘封跌停") or any(o_.get("二封") for o_ in ops) else "跌停开·开板没再封(走强)")
        else:
            kind = "盘中封跌停" + ("·收盘封死" if ds.get("收盘封跌停") else "·又打开")
        t_up = seal["首封(秒)"] if seal and seal.get("首封(秒)") else (t_hi if up and hi >= up - tick / 2 else None)
        if t_up and t_dn:
            kind += " · " + ("地天(先跌停后涨停)" if t_dn < t_up else "天地(先涨停后跌停)")
        out["分时"]["跌停板型"] = kind
        det = []
        for o_ in ops[:4]:
            fast = o_.get("5分钟内最高")
            det.append(f"{o_['开']} 开板, 最高 {o_['最高']:g}(离跌停 {_f((o_['最高'] / dn - 1) * 100)})" + (f", 5 分钟内拉到 {_f((fast / dn - 1) * 100)}{' = 急拉(U5)' if fast >= dn * 1.05 else ' = 慢拉'}" if fast else "") + (f", {o_['二封']} 二封跌停(弱)" if o_.get("二封") else ", 没再封(U5: 在走强)"))
        out["分时"]["跌停开板"] = det
        say(f"跌停板型: {kind}" + (f"; 首次封跌停 {t_dn}" if ds.get("首封跌停") else "") + ("; " + "; ".join(det) if det else ""))

    # 波段
    thr = max(P["WAVE_MIN"], 0.35 * amp)
    piv = zigzag(ms, thr)
    waves = []
    for (t1, p1, _), (t2, p2, _) in zip(piv, piv[1:]):
        if abs(p2 / p1 - 1) >= thr * 0.6:
            waves.append(f"{t1}→{t2} {p1:g}→{p2:g}({_f((p2 / p1 - 1) * 100)})")
    out["分时"]["波段"] = waves
    # 低点复盘(给"该在哪买"做学习样本): 每个波段低点 → 相对均价 / 跌停 / 是否抬高低点 / 之后 60 分钟最高 / 到收盘(或截至时刻)
    lows, prev_l, avg_at = [], None, {r["t"]: r.get("avg") for r in ms}
    for t_, p_, k_ in piv:
        if k_ != "L":
            continue
        after = [r for r in ms if r["t"] > t_]
        a60 = [r for r in after if r["t"] <= (dt.datetime.strptime(t_, "%H:%M") + dt.timedelta(minutes=60)).strftime("%H:%M")]
        mx = max((r["h"] for r in a60), default=p_)
        av_ = avg_at.get(t_)
        tag = ("抬高低点" if prev_l and p_ > prev_l else "新低" if prev_l else "首个低点")
        lows.append(f"{t_} {p_:g}({tag}" + (f", 均价{'上' if p_ >= av_ else '下'} {_f((p_ / av_ - 1) * 100)}" if av_ else "") + (f", 离跌停 {_f((p_ / dn - 1) * 100)}" if dn and p_ <= dn * 1.03 else "") + f") → 60 分钟内最高 {_f((mx / p_ - 1) * 100)}, 到{'收盘' if not at else at} {_f((c / p_ - 1) * 100)}")
        prev_l = p_
    out["分时"]["低点复盘"] = lows
    if lows:
        say("低点复盘(哪里买): " + " | ".join(lows))
    say(f"波段(阈 {thr * 100:.1f}%): " + (" | ".join(waves) if waves else "无明显波段(窄幅)"))

    # 均价关系
    av = [(r["t"], r["c"], r["avg"]) for r in ms if r.get("avg")]
    if av:
        above = sum(1 for _, p_, a_ in av if p_ >= a_) / len(av)
        rel = "全天在均价上方" if above >= 0.95 else "全天在均价下方" if above <= 0.05 else f"均价上方 {above * 100:.0f}% 的时间"
        breaks, seg_ = [], None
        for t_, p_, a_ in av:   # 跌破均价的段: 起点 / 最低 / 回到均价
            if p_ < a_ * (1 - 0.003):
                seg_ = seg_ or {"起": t_, "低": p_, "低t": t_}
                if p_ < seg_["低"]:
                    seg_["低"], seg_["低t"] = p_, t_
            elif seg_ and p_ >= a_:
                seg_["回"] = t_
                breaks.append(seg_)
                seg_ = None
        if seg_:
            breaks.append(seg_)
        big = [b for b in breaks if (b.get("回") or ms[-1]["t"]) > b["起"]]
        out["分时"]["均价"] = rel
        out["分时"]["跌破均价"] = [f"{b['起']} 跌破, {b['低t']} 最低 {b['低']:g}, " + (f"{b['回']} 收回" if b.get("回") else "没收回") for b in big[:5]]
        say(f"均价: {rel}" + ("; 跌破均价: " + "; ".join(out["分时"]["跌破均价"]) if big else ""))

    # 横盘蓄势(在均价上方、振幅 ≤ BOX_RANGE、≥ BOX_MIN 分钟)
    boxes, i = [], 0
    rng = P["BOX_RANGE"] / k
    t_seal = (seal or {}).get("首封(秒)", "99")[:5] if seal else "99"
    while i < len(ms):
        j, h_, l_ = i, ms[i]["h"], ms[i]["l"]
        while j + 1 < len(ms) and (max(h_, ms[j + 1]["h"]) - min(l_, ms[j + 1]["l"])) / pc <= rng and (ms[j + 1].get("avg") is None or ms[j + 1]["c"] >= ms[j + 1]["avg"]):
            j += 1
            h_, l_ = max(h_, ms[j]["h"]), min(l_, ms[j]["l"])
        if j - i + 1 >= P["BOX_MIN"] and ms[i]["t"] < t_seal and not (up and h_ >= up - tick / 2 and l_ >= up - tick / 2):
            boxes.append(f"{ms[i]['t']}~{ms[j]['t']} 在 {l_:g}~{h_:g}(离涨停 {_f((h_ / up - 1) * 100) if up else '?'}~{_f((l_ / up - 1) * 100) if up else '?'})")
            i = j + 1
        else:
            i += 1
    out["分时"]["横盘蓄势"] = boxes
    if boxes:
        say("横盘蓄势(均价上方): " + "; ".join(boxes))

    # 上板方式
    how = []
    if seal and seal.get("首封(秒)"):
        t0 = seal["首封(秒)"][:5]
        pre = [r for r in ms if r["t"] < t0]
        if og / 100 <= P["DEEP_OPEN"] and op != "跌停开" and len([w for w in waves if w.split("→")[0] < t0 and "(+" in w]) >= 2:
            how.append(f"低开分波上攻(开 {_f(og)}, 非跌停开, 封板前 ≥2 波上攻)")
        if "13:00" <= t0 <= "13:05":
            m1129 = next((r for r in reversed(ms) if r["t"] <= "11:30"), None)
            if m1129 and up and (up - m1129["c"]) / up <= 0.01 * (lim / 0.1):
                how.append(f"午前蓄势、午后开盘即封(11:30 离涨停 {_f((m1129['c'] / up - 1) * 100)})")
        bar = next((r for r in ms if r["t"] == t0), None)
        if bar and pre:
            last30 = pre[-30:]
            flat = (max(r["h"] for r in last30) - min(r["l"] for r in last30)) / pc
            if (bar["h"] - bar["o"]) / pc >= P["LINE_UP"] / k and flat <= P["LINE_FLAT"] / k * 1.5:
                how.append(f"直线拉板({t0} 一分钟 {bar['o']:g}→{bar['h']:g}, 之前 30 分钟振幅 {flat * 100:.1f}%; U20 疑量化)")
        if pre:
            dd, peak = 0.0, pre[0]["h"]
            for r in pre:
                peak = max(peak, r["h"])
                dd = max(dd, (peak - r["l"]) / peak)
            if dd < 0.02 and not how:
                how.append(f"一路拉板(封板前最大回撤 {dd * 100:.1f}%)")
    if how:
        out["分时"]["上板方式"] = how
        say("上板方式: " + "; ".join(how))

    # 冲高A杀 / 收盘位置
    if (hi / pc - 1) >= P["ASHA_UP"] / k and (c / hi - 1) <= -P["ASHA_DROP"] / k:
        out["分时"]["冲高A杀"] = f"最高 {hi:g}({_f((hi / pc - 1) * 100)}, {t_hi}) → {c:g}(从最高 {_f((c / hi - 1) * 100)})"
        say("冲高A杀: " + out["分时"]["冲高A杀"])
    if hi > lo:
        out["分时"]["收盘位置%"] = round((c - lo) / (hi - lo) * 100)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--at")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    r = read(a.code, a.date, a.at)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(f"== {r['name']}({r['code']}) {r['D']} 截至 {r['截至']} · 昨收 {r['昨收']} 涨停 {r['涨停价']}")
        for l in r["读盘稿"]:
            print("  " + l)


if __name__ == "__main__":
    main()
