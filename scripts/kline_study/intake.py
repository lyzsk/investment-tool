# -*- coding: utf-8 -*-
"""intake.py — K 线 / 分时 / 涨停图收件 → 自动分析 → 记成案例 → 到期自动对答案 → 沉淀进 market-skill(K 线案例)(10/24 用户: 以后重点给 K 线、分时、涨停图, 写代码来接, 沉淀成自己的 skill)

一张图怎么走:
  ①认图: 截图类型(分时 / 五日 / 日 K, 看顶部 tab 蓝色下划线的位置)+ 股票(--code; 截图顶部的名称代码由看图的人填, 本机还没装 OCR)
     日 K 图再用 annotate_shot 的实体校准认出"最右一根是哪天"(截图常是往左滑过的历史窗口)
  ②机械事实(零 token, 只读行情库): 截止日的开高低收 / 涨跌 / 收位(在当天振幅的百分位)/ 量比 / 连板数 / 板型(一字 / T 字 / 厂字 / 回封 / 烂板回封 / 炸板 / 烂板 / 地天)
     / 首次封板时刻 / 开板次数 / 收盘 vs 均价 / 段式日线箱体位置(draw_box)
  ③统计: strong_next 同状态次日分布 + scen_next.scen3 三日情景(强 / 震荡 / 弱 概率 + 代表真实样本)
  ④落盘(10/25 用户定: 案例和 downloads 原图解耦 —— downloads 有定时物理删除):
     原图 downloads/kline/<yyyy.mm.dd>/(只放原图; 收件状态在 results 那边的 _status.json, 不进 DB)
     案例库 results/kline/cases.jsonl(一个案例 = 同一只票同一截止日的几张图; 图只记文件名 + 类型 + 最右一根, 不依赖原图还在)
     产物 results/kline/<yyyy.mm.dd>/(日 K 标注图 / 未来 3 日续画图)
  ③b 盘后信息: 龙虎榜(席位 / 游资风格 / 近 10 日时间线 / 主买游资后续)/ 题材梯队 / 监管电报(peers.query)+ 发哥提到 + 加红电报点名
  ③c 导师买卖点: 同花顺投资账本全体导师在这只票上近 20 个交易日的逐笔(时刻 / 价 / 在当天振幅的位置 / 相对当时均价 / 相对首封), 日 K 图上直接标出来
  ⑤对答案(--resolve, 每晚 check md 22 点后那轮调): 截止日之后满 3 个交易日的案例, 补真实 3 日路径 + 落在哪个情景 + 当时给的概率 → 追加到 skills/market-skill/persona/kline_cases.md
用法:
  python intake.py <图片>... --code 603278            收一张或几张同一只票的图
  python intake.py --resolve                           对答案(到期的)
  python intake.py --list                              看案例库
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(Path(__file__).resolve().parent), str(ROOT / "scripts" / "paper_line" / "tools"), str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "lib")]
BASE = ROOT / "results" / "kline"
CASES = BASE / "cases.jsonl"
INBOX = ROOT / "downloads" / "kline"


def day_dir(d=None):
    """yyyy.mm.dd 目录名(收件日; 默认今天)"""
    return (d or dt.date.today().isoformat()).replace("-", ".")
SKILL_CASES = ROOT / "skills" / "market-skill" / "persona" / "kline_cases.md"   # 10/25 market-skill(K 线) 并入 market-skill


def cur():
    import manual_backfill as mb
    return mb.db().cursor()


def sym(code):
    return ("sh" if code.startswith(("6", "9", "11", "5")) else "bj" if code.startswith(("4", "8")) else "sz") + code


def chart_type(img):
    """顶部 tab(分时 / 五日 / 日K / 周K / 月K)蓝色下划线的横向位置 → 类型"""
    W, H = img.size
    a = np.asarray(img.convert("RGB")).astype(int)[int(H * 0.26):int(H * 0.33)]   # tab 行在 0.27~0.31(带 1 行 / 2 行公告两种版式)
    blue = (a[..., 2] > 180) & (a[..., 0] < 100) & (a[..., 1] > 100) & (a[..., 1] < 190)
    ys, xs = np.where(blue)
    if not len(xs):
        return "未知"
    x = float(np.median(xs)) / W
    return "分时" if x < 0.14 else "五日" if x < 0.28 else "日K" if x < 0.42 else "周K" if x < 0.56 else "月K"


def daily_rows(code, end, n=80):
    c = cur()
    c.execute("select trade_date, open, high, low, close, pre_close, volume, amount from investment_market.kline_day where symbol=%s and is_deleted=0 and trade_date<=%s "
              "order by trade_date desc limit %s", (sym(code), end, n))
    return [(str(d), *(float(x or 0) for x in r)) for d, *r in c.fetchall()][::-1]


def lim_pct(code, name=""):
    if "ST" in (name or "").upper():
        return 0.05
    if code.startswith(("11", "12")):   # 转债: 涨跌幅 ±20%(上市首日除外), 盘中 ±20% 临停
        return 0.20
    return 0.20 if code.startswith(("300", "301", "688", "689")) else 0.30 if code.startswith(("4", "8", "92")) else 0.10


def zt(pc, p):
    return round(pc * (1 + p) + 1e-9, 2)


def facts(code, end, name=""):
    """截止日机械事实"""
    R = daily_rows(code, end)
    d, o, h, l_, cl, pc, v, amt = R[-1]
    p = lim_pct(code, name)
    up, dn = zt(pc, p), round(pc * (1 - p) + 1e-9, 2)
    boards = 0
    for r in R[::-1]:
        if r[4] >= zt(r[5], p) - 0.005:
            boards += 1
        else:
            break
    vol5 = np.mean([r[6] for r in R[-6:-1]]) if len(R) > 5 else 0
    zt5 = sum(1 for r in R[-5:] if r[4] >= zt(r[5], p) - 0.005)   # "5 天 3 板"这种不连续的也算
    F = {"截止日": d, "开": o, "高": h, "低": l_, "收": cl, "昨收": pc, "涨跌%": round((cl / pc - 1) * 100, 2), "开盘%": round((o / pc - 1) * 100, 2),
         "最高%": round((h / pc - 1) * 100, 2), "最低%": round((l_ / pc - 1) * 100, 2), "收位%": round((cl - l_) / (h - l_) * 100) if h > l_ else 100,
         "量比5日": round(v / vol5, 2) if vol5 else None, "成交额亿": round(amt / 1e8, 2), "涨停价": up, "跌停价": dn, "连板": boards, "近5日涨停": zt5}
    try:   # 10/24 用户: 小票拉板要的资金少、大票难 —— 流通市值(成交额 ÷ 换手率)分档, 宽泛口径: <50 亿 小 / 50~200 中 / ≥200 大
        c0 = cur()
        c0.execute("select turnover_rate from investment_market.kline_day where symbol=%s and trade_date=%s and is_deleted=0", (sym(code), d))
        tr = (c0.fetchone() or [None])[0]
        if tr and float(tr) > 0 and not code.startswith(("11", "12")):
            fv = amt / (float(tr) / 100) / 1e8
            F["流通市值亿"] = round(fv)
            F["市值档"] = "小票(<50亿)" if fv < 50 else "中票(50~200亿)" if fv < 200 else "大票(≥200亿)"
    except Exception:   # noqa: BLE001
        pass
    c = cur()
    c.execute("select bar_time, close, avg_price, volume from investment_market.kline_minute where symbol=%s and trade_date=%s and is_deleted=0 order by bar_time", (sym(code), d))
    m = [(str(t)[11:16], float(x), float(a or 0), float(vv or 0)) for t, x, a, vv in c.fetchall() if x]
    sealed = cl >= up - 0.005
    touched = h >= up - 0.005
    if m:
        at = [x[1] >= up - 0.005 for x in m]
        first = next((m[i][0] for i, z in enumerate(at) if z), None)
        opens = sum(1 for a_, b_ in zip(at, at[1:]) if a_ and not b_)
        lo_t = min(m, key=lambda x: x[1])[0]
        tv = sum(x[3] for x in m)
        vwap = sum(x[1] * x[3] for x in m) / tv if tv else None
        F.update({"首次封板": first, "开板次数(分钟级)": opens, "最低点时刻": lo_t, "收盘vs均价%": round((cl / vwap - 1) * 100, 2) if vwap else None})
    else:
        opens, first = None, None
        F["分钟线"] = "库里没有当天分钟线"
    yizi = o >= up - 0.005 and l_ >= up - 0.005
    if yizi:
        bt = "一字板"
    elif sealed and l_ <= dn + 0.005:
        bt = "地天板"
    elif sealed and o >= up - 0.005:
        bt = "T字板" if (opens or 0) <= 1 else "烂板回封"
    elif sealed:
        if (opens or 0) >= 2:
            bt = "烂板回封"
        elif (opens or 0) == 1:
            bt = "回封板"
        elif (o - l_) / pc * 100 <= 1.5:
            bt = "厂字板(一路拉板)"
        elif (l_ / pc - 1) * 100 > -5:   # 10/24 好上好: 只探到 −2.9% 不算大分歧
            bt = f"探底后封板(先探到 {(l_ / pc - 1) * 100:+.1f}% 再封)"
        else:   # 10/24 大业股份: 低开 −4%、盘中 −8.8% 再一路封住 —— 不是厂字(厂字 = 开盘后一路拉), 单列
            bt = f"大分歧后封板(开盘后先跌到 {(l_ / pc - 1) * 100:+.1f}% 再封)"
    elif touched:
        bt = "烂板(反复开板最终没封住)" if (opens or 0) >= 2 else "炸板"
    else:
        bt = "未触板"
    F["板型"] = bt
    try:
        import draw_box as DB
        name_, dd, oo, hh, ll, cc, pp, vv = DB.load(code, end, 120)
        _, _, _, _, atr = DB.boxes(hh, ll, cc, pp)
        segs = DB.seg_boxes(oo, hh, ll, cc, atr, 0)
        cur_ = segs[-1] if segs and segs[-1][1] == len(cc) - 1 else None
        F["日线箱体"] = {"上沿": round(cur_[2], 2), "下沿": round(cur_[3], 2), "起": dd[cur_[0]], "位置%": round((cc[-1] - cur_[3]) / (cur_[2] - cur_[3]) * 100)} if cur_ else "不在箱体里(趋势段)"
    except Exception as e:   # noqa: BLE001
        F["日线箱体"] = f"算不出 {e!r}"[:80]
    return F


def next_day(D):
    c = cur()
    c.execute("select min(trade_date) from investment_market.kline_day where symbol='sh000001' and trade_date>%s", (D,))
    x = c.fetchone()[0]
    if x:
        return str(x)
    d = dt.date.fromisoformat(D) + dt.timedelta(days=1)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d.isoformat()


def stats(code, end):
    import scen_next as SN
    import strong_next as S
    D = next_day(end)
    out = {}
    if code.startswith(("11", "12")):   # 转债: 用转债相似日库(正股前一日 / 转债前一日 / K 线 / 价位 / 大盘逐级放宽)
        try:
            sys.path.insert(0, str(ROOT / "scripts" / "paper_line"))
            import pack
            r = pack._cb_similar().query(code, D, None)
            t = next((x for x in r.get("tiers") or [] if x.get("n", 0) >= 7), (r.get("tiers") or [{}])[-1])
            out["次日(转债相似日)"] = {"特征": r.get("当前特征"), "按": t.get("按"), "n": t.get("n"), **{k: v for k, v in t.items() if k not in ("按", "n")}}
        except Exception as e:   # noqa: BLE001
            out["err"] = repr(e)[:200]
        return json.loads(json.dumps(out, ensure_ascii=False, default=str))
    try:
        r = S.query(code, D)
        if r.get("tiers"):
            t = r["tiers"][0]
            out["次日"] = {"状态": r["当前状态"], "n": t["n"], "开盘P25/中/P75": t.get("次日开盘 P25/中位/P75"), "冲高P25/中/P75": t.get("次日最高(冲高) P25/中位/P75"),
                         "收盘": {k: t.get("次日收盘 全分布", {}).get(k) for k in ("P10", "P25", "中位", "P75", "P90")}, "一字比例": t.get("一字涨停(买不进)比例")}
        else:
            out["次日"] = {"状态": r.get("状态"), "n": 0}
        F = facts(code, end)
        if F["连板"] >= 3 and F["收"] >= F["涨停价"] - 0.005 and F["最低%"] <= -5:
            out["高位大分歧回封"] = diverge_stat(F["连板"], F["最低%"], end)
        s3 = SN.scen3(code, D)
        out["3日"] = {"n": s3["n"], "情景": [{k: s[k] for k in ("名", "概率", "n", "第3天收盘 P25/中位/P75")} | {"代表": f"{s['代表样本']['code']} {s['代表样本']['d']}"} for s in s3["情景"]]}
    except Exception as e:   # noqa: BLE001
        out["err"] = repr(e)[:200]
    return out


def mentor_legs(code, end, n_before=20, n_after=0):
    """10/24 用户: 导师(同花顺投资账本)在这只票上的逐笔买卖点 —— 截止日前 n_before 个交易日(+ 之后 n_after 天), 每笔带: 当天开高低收里的位置 / 那一分钟相对均价 / 相对首次封板
    导师按 skill 中文名; 标 入选 / 样例(截止日当天开盘时的 mentor_select 口径)"""
    import skill_names as SN
    c = cur()
    c.execute("select distinct trade_date from investment_market.kline_day where symbol='sh000001' and trade_date<=%s order by trade_date desc limit %s", (end, n_before))
    d0 = min(str(x[0]) for x in c.fetchall())
    c.execute("select distinct trade_date from investment_market.kline_day where symbol='sh000001' and trade_date>%s order by trade_date limit %s", (end, max(n_after, 1)))
    d1 = max([str(x[0]) for x in c.fetchall()] or [end]) if n_after else end
    c.execute("select ledger, record_time, side, price, qty from investment_tool.tzzb_record where record_type='bs_leg' and is_deleted=0 and stock_code=%s "
              "and date(record_time)>=%s and date(record_time)<=%s order by record_time", (code, d0, d1))
    legs = c.fetchall()
    if not legs:
        return []
    try:
        import mentor_select as MS
        sel = {x["id"]: x["role"] for x in MS.select(next_day(end))["ranked"]}
    except Exception:   # noqa: BLE001
        sel = {}
    day = {r[0]: r for r in daily_rows(code, d1, 60)}
    mins = {}
    out = []
    try:   # 已删导师(10/24 大兴)业务库行还在, 不当样本
        import mentors as MT
        alive = {e["id"] for e in MT.all()}
        legs = [x for x in legs if x[0] in alive]
    except Exception:   # noqa: BLE001
        pass
    for led, t, side, px, q in legs:
        d, hm = str(t)[:10], str(t)[11:16]
        px = float(px or 0)
        r = day.get(d)
        try:   # 登记表有中文名就用(liurenih / elangking 这类没有 skill 目录的导师 SN.cn 只能给英文 id)
            import mentors as MT
            nm_ = (MT.get(led) or {}).get("display") or SN.cn(led)
        except Exception:   # noqa: BLE001
            nm_ = SN.cn(led)
        e = {"日": d, "时": hm, "导师": nm_ + "skill", "身份": sel.get(led, "?"), "方向": "买" if "买" in str(side) else "卖", "价": px, "股数": int(q or 0)}
        if r:
            _, o, h, l_, cl, pc = r[:6]
            e["相对昨收%"] = round((px / pc - 1) * 100, 2)
            e["在当天振幅位置%"] = round((px - l_) / (h - l_) * 100) if h > l_ else None
            e["当天收盘相对买卖价%"] = round((cl / px - 1) * 100, 2) if px else None
            up = zt(pc, lim_pct(code))
            e["是否涨停价"] = abs(px - up) < 0.006
        if d not in mins:
            c.execute("select bar_time, close, volume from investment_market.kline_minute where symbol=%s and trade_date=%s and is_deleted=0 order by bar_time", (sym(code), d))
            mins[d] = [(str(a)[11:16], float(b), float(v or 0)) for a, b, v in c.fetchall() if b]
        m = mins[d]
        if m:
            upto = [x for x in m if x[0] <= hm] or m[:1]
            tv = sum(x[2] for x in upto)
            if tv:
                e["相对当时均价%"] = round((px / (sum(x[1] * x[2] for x in upto) / tv) - 1) * 100, 2)
            if r:
                fz = next((x[0] for x in m if x[1] >= zt(r[5], lim_pct(code)) - 0.005), None)
                e["首次封板"] = fz
        out.append(e)
    return out


def context(code, end):
    """龙虎榜 / 题材梯队 / 监管电报(peers.query, 截止日收盘后已知)+ 发哥提到(截止日 / 下一交易日的盘前推演)+ 加红电报点名"""
    out = {}
    try:
        import peers as PE
        r = PE.query(code, next_day(end))
        lh = r.get("龙虎榜") or {}
        out["龙虎榜"] = {k: lh.get(k) for k in ("上榜", "原因", "净买前列", "净卖前列", "机构") if k in lh}
        for x in out["龙虎榜"].get("净买前列") or []:
            x.pop("_ev", None)
        out["龙虎榜时间线"] = r.get("龙虎榜时间线(近10日)")
        out["主买游资后续"] = r.get("主买游资后续")
        out["题材梯队"] = r.get("题材 / 梯队")
        out["监管筹码电报"] = r.get("监管 / 筹码 / 电报")
    except Exception as e:   # noqa: BLE001
        out["龙虎榜"] = {"err": repr(e)[:200]}
    try:
        import watch_set as WS
        fg = {}
        for d in (end, next_day(end)):
            t = WS.fage(d).get(code)
            if t:
                fg[d] = t[:160]
        out["发哥"] = fg or "近两天没提到"
    except Exception as e:   # noqa: BLE001
        out["发哥"] = f"读不到 {e!r}"[:80]
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "paper_line"))
        import pack
        tl = pack.telegraph_links(end)
        out["加红电报点名"] = [f"{t} {s}" for t, u, s in tl.get(code, [])] or "当天没点名"
    except Exception as e:   # noqa: BLE001
        out["加红电报点名"] = f"读不到 {e!r}"[:80]
    return json.loads(json.dumps(out, ensure_ascii=False, default=str))


def draw_marks(img_path, code, end, legs, outp):
    """日 K 截图原图上标: 段式箱体 + 导师买卖点(B 红 / S 绿, 按校准后的 x / 价格 y)"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import draw_box as DB
    import draw_future as DF
    from PIL import ImageDraw, ImageFont
    img = Image.open(img_path).convert("RGB")
    C = DF.calib_daily(img, code, end)
    name, d, o, h, l_, cl, pc, v = DB.load(code, end, 120)
    idx = {str(x): i for i, x in enumerate(d)}
    xof = lambda dd: C["xr"] - (len(d) - 1 - idx[dd]) * C["dx"]   # noqa: E731
    dr = ImageDraw.Draw(img, "RGBA")
    f = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 22)
    _, _, _, _, atr = DB.boxes(h, l_, cl, pc)
    for a_, b_, r, s_, _, _ in DB.seg_boxes(o, h, l_, cl, atr, 0):
        if b_ < len(d) - 70:
            continue
        dr.rectangle([xof(str(d[max(a_, 0)])) - C["dx"] / 2, C["py"](r), xof(str(d[b_])) + C["dx"] / 2, C["py"](s_)], fill=(255, 212, 59, 40), outline=(255, 170, 0, 255), width=2)
    agg = {}   # 同一天同一导师合成一个点(土豆这种每天竞价 T 的, 一天十几笔会糊成一片): 当天有买有卖 = T(标均买价 + 做 T 盈亏), 只买 = B, 只卖 = S
    for e in legs:
        a = agg.setdefault((e["日"], e["导师"]), {"bq": 0, "bv": 0.0, "sq": 0, "sv": 0.0})
        k_ = "b" if e["方向"] == "买" else "s"
        a[k_ + "q"] += e["股数"]
        a[k_ + "v"] += e["价"] * e["股数"]
    for (dd, who), a in agg.items():
        if dd not in idx:
            continue
        bp = a["bv"] / a["bq"] if a["bq"] else None
        sp = a["sv"] / a["sq"] if a["sq"] else None
        x = xof(dd)
        if bp and sp:
            col, lab, y = ((255, 60, 60, 255) if sp >= bp else (60, 220, 120, 255)), f"T{(sp / bp - 1) * 100:+.1f}%", C["py"](bp)
        elif bp:
            col, lab, y = (255, 60, 60, 255), "B", C["py"](bp)
        else:
            col, lab, y = (60, 220, 120, 255), "S", C["py"](sp)
        dr.ellipse([x - 7, y - 7, x + 7, y + 7], outline=col, width=3)
        if len(agg) <= 12 or lab != "T+0.0%":
            dr.text((x - 10, y + 10), lab, font=ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 16), fill=col)
    who_all = sorted({w for _, w in agg})
    dr.text((20, C["py"](C["close"]) - 60 if False else 30), "导师: " + "、".join(who_all) + "(B 买 / S 卖 / T 当天买卖都有)", font=f, fill=(255, 220, 80, 255))
    img.save(outp)
    return outp, C["err"]


def diverge_stat(boards, low_pct, end):
    """同类: 主板 ≥min(boards,5) 连板当天盘中跌到 ≤ −5%(地天 = 触跌停)再封涨停 → 之后 1 / 3 日(只用 end 之前; 缓存 parquet 由 scripts/kline_study/load_daily.py 生成)"""
    import glob
    import pandas as pd
    f = sorted(glob.glob("C:/Users/admin/dev/_kline_extract/cache/kline_day_*.parquet"))
    if not f:
        return {"err": "没有日线缓存(先跑 load_daily.py)"}
    d = pd.read_parquet(f[-1]).sort_values(["symbol", "trade_date"])
    d = d[(d.board_type == "MAIN") & (d.is_st != 1) & ~d.name.astype(str).str.contains("ST|退")].copy()   # 非 ST 主板(ST 5% 涨跌停, 地天只差 10 个点, 不同类)
    lim = 0.10
    d["zt"] = d.close >= np.round(d.pre_close * (1 + lim), 2) - 0.005
    d["dt"] = d.low <= np.round(d.pre_close * (1 - lim), 2) + 0.005
    g = d.groupby("symbol", sort=False)
    d["run"] = g["zt"].transform(lambda s_: s_.groupby((~s_).cumsum()).cumsum())
    d["l%"] = (d.low / d.pre_close - 1) * 100
    for k in (1, 3):
        d[f"r{k}"] = (g["close"].shift(-k) / d["close"] - 1) * 100
    d["h1"] = (g["high"].shift(-1) / d["close"] - 1) * 100
    d["o1"] = (g["open"].shift(-1) / d["close"] - 1) * 100
    x = d[(d.run >= min(boards, 5)) & d.zt & (d["l%"] <= -5) & d.r3.notna() & (d.trade_date < pd.Timestamp(end))]
    out = {"口径": f"主板 ≥{min(boards, 5)} 连板当天盘中 ≤−5% 再封涨停", "n": int(len(x))}
    if len(x):
        q = lambda v: [round(float(v.quantile(t)), 1) for t in (0.1, 0.25, 0.5, 0.75, 0.9)]   # noqa: E731
        out.update({"次日开 P10/25/50/75/90": q(x.o1), "次日冲高": q(x.h1), "次日收": q(x.r1), "3日收": q(x.r3),
                    "3日 强/震荡/弱 %": [round(float((x.r3 >= 5).mean() * 100)), round(float(((x.r3 > -5) & (x.r3 < 5)).mean() * 100)), round(float((x.r3 <= -5).mean() * 100))],
                    "次日继续涨停 %": round(float((x.r1 >= 9.9).mean() * 100))})
        y = x[x.dt]
        if len(y):
            out["其中地天(触跌停)"] = {"n": int(len(y)), "3日收": q(y.r3), "3日 强/震荡/弱 %": [round(float((y.r3 >= 5).mean() * 100)), round(float(((y.r3 > -5) & (y.r3 < 5)).mean() * 100)), round(float((y.r3 <= -5).mean() * 100))],
                                    "次日继续涨停 %": round(float((y.r1 >= 9.9).mean() * 100)), "例": [f"{a_} {b_.date()}" for a_, b_ in zip(y.name.tail(6), y.trade_date.tail(6))]}
    return out


def load_cases():
    if not CASES.exists():
        return []
    return [json.loads(l) for l in CASES.read_text(encoding="utf-8").splitlines() if l.strip()]


def save_cases(L):
    BASE.mkdir(parents=True, exist_ok=True)
    CASES.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in L), encoding="utf-8")


def intake(paths, code, end=None, note="", redo=False, out_day=None):
    import annotate_shot as A
    import draw_box as DB
    L = load_cases()
    imgs = []
    for p in paths:
        p = Path(p)
        img = Image.open(p).convert("RGB")
        ty = chart_type(img)
        last = None
        if ty == "日K" and end:   # 看图的人 / OCR 横轴已经确认最右一根就不再猜
            last = end
            ty += f"(最右一根 {end}, 已确认)"
        elif ty == "日K":
            try:
                W, H = img.size
                name, d, o, h, l_, cl, pc, v = DB.load(code, end or dt.date.today().isoformat(), 300)
                cand = [(len(A.bars(img, int(H * t), int(H * (t + 0.165)), int(W * 0.015), int(W * 0.975))), t) for t in (0.395, 0.41, 0.425)]
                t = max(cand)[1]
                B = A.bars(img, int(H * t), int(H * (t + 0.165)), int(W * 0.015), int(W * 0.975))
                xs = np.array([b[0] for b in B])
                colr = np.array([b[3] for b in B])
                sp = np.diff(xs)
                dx0 = float(np.median(sp[(sp > 8) & (sp < 40)]))
                best = None
                for dx in np.arange(dx0 * 0.9, dx0 * 1.1, 0.1):
                    for e in range(0, 250):
                        pos = np.round((xs.max() - xs) / dx).astype(int)
                        idx = len(cl) - 1 - e - pos
                        ok = idx >= 0
                        if ok.sum() < 10:
                            break
                        mis = float(np.mean((cl >= o)[idx[ok]] != (colr[ok] == "red")))
                        P = np.concatenate([np.maximum(o, cl)[idx[ok]], np.minimum(o, cl)[idx[ok]]])
                        Y = np.concatenate([np.array([q[1] for q in B])[ok], np.array([q[2] for q in B])[ok]])
                        k, c0 = np.polyfit(P, Y, 1)
                        err = float(np.median(np.abs(Y - (k * P + c0))) / abs(k)) if k else 99
                        if k < 0 and (best is None or mis * 10 + err + 0.01 * e < best[0]):   # 10/24: 涨停 K 线是黄色 / 紫色(DK 点)认不出颜色 → 小罚往前推, 默认当截图就是最新
                            best = (mis * 10 + err + 0.01 * e, e, mis, err)
                last = str(d[len(cl) - 1 - best[1]])
                ty += f"(最右一根 {last}, 颜色对不上 {best[2]:.0%})"
            except Exception as e:   # noqa: BLE001
                ty += f"(认最右一根失败 {e!r})"[:80]
        imgs.append({"file": p.name, "原图": str(p), "类型": ty, "最右一根": last})
    end = end or next((x["最右一根"] for x in imgs if x["最右一根"]), None) or str(daily_rows(code, dt.date.today().isoformat(), 1)[-1][0])
    key = f"{code}@{end}"
    old = next((x for x in L if x["key"] == key), None)
    if old and redo:
        L.remove(old)
        old = None
    if old:
        old["图"] += [x for x in imgs if x["file"] not in {y["file"] for y in old["图"]}]
        if note:
            old["备注"] = (old.get("备注", "") + " | " + note).strip(" |")
        case = old
    else:
        sys.path.insert(0, str(ROOT / "scripts" / "lib"))
        try:
            c = cur()
            c.execute("select name from investment_market.security_master where code=%s limit 1", (code,))
            name = (c.fetchone() or [""])[0]
        except Exception:   # noqa: BLE001
            name = ""
        case = {"key": key, "code": code, "name": name, "截止日": end, "收件": dt.datetime.now().isoformat(timespec="seconds"), "图": imgs,
                "事实": facts(code, end, name), "统计": stats(code, end), "导师买卖点": mentor_legs(code, end), "盘后信息": context(code, end),
                "看图判断": "", "备注": note, "对答案": None}
        try:
            enrich(case)
        except Exception as e:   # noqa: BLE001
            case["盘口err"] = repr(e)[:200]
        for g in imgs:   # 日 K 图: 原图上标箱体 + 导师买卖点
            if g["类型"].startswith("日K"):
                try:
                    od = BASE / day_dir(out_day)
                    od.mkdir(parents=True, exist_ok=True)
                    op, err = draw_marks(g["原图"], code, end, case["导师买卖点"], od / f"{code}_{Path(g['file']).stem}_标注.png")
                    g["标注图"] = str(Path(op).relative_to(ROOT))
                except Exception as e:   # noqa: BLE001
                    g["标注图"] = f"失败 {e!r}"[:100]
        L.append(case)
    save_cases(L)
    return case


PRIV = ROOT / "scripts" / "dfcf" / "snapshots" / "kline_cases"   # 用户实盘腿 × 盘口: 隐私区(已 gitignore), 不进 cases.jsonl / skill


def enrich(case):
    """3 秒盘口: 截止日涨停过程(秒级)+ 导师腿逐笔盘口上下文 + 用户实盘腿(只写隐私区)"""
    import tape as TP
    code, end, F = case["code"], case["截止日"], case["事实"]
    if "导师买卖点" not in case:   # 早期收件的案例还没有导师 / 盘后信息
        case["导师买卖点"] = mentor_legs(code, end)
        case["盘后信息"] = context(code, end)
    if F.get("最高%", 0) >= lim_pct(code, case.get("name", "")) * 100 - 0.5:
        case["涨停过程(3秒)"] = TP.seal_story(code, end, F["涨停价"])
    days = {}
    for e in case.get("导师买卖点") or []:
        if e["日"] not in days:
            R = daily_rows(code, e["日"], 1)
            days[e["日"]] = R[-1] if R and R[-1][0] == e["日"] else None
        r = days[e["日"]]
        up, dn = (zt(r[5], lim_pct(code)), round(r[5] * (1 - lim_pct(code)) + 1e-9, 2)) if r else (None, None)
        if TP.book(code, e["日"]):
            e["盘口"] = TP.leg_ctx(code, e["日"], e["时"], e["价"], e["方向"], up, dn)
    U = TP.user_legs(code, (case.get("导师买卖点") or [{"日": end}])[0]["日"] if case.get("导师买卖点") else end, end)
    if U:
        PRIV.mkdir(parents=True, exist_ok=True)
        rows = []
        for d, t, sd, px, q in U:
            R = daily_rows(code, d, 1)
            r = R[-1] if R and R[-1][0] == d else None
            up, dn = (zt(r[5], lim_pct(code)), round(r[5] * (1 - lim_pct(code)) + 1e-9, 2)) if r else (None, None)
            rows.append({"日": d, "时": t, "方向": sd, "价": px, "数量": q, "盘口": TP.leg_ctx(code, d, t, px, sd, up, dn)})
        (PRIV / f"{case['key'].replace('@', '_')}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        case["用户实盘"] = f"有 {len(U)} 笔(明细 + 盘口在 scripts/dfcf/snapshots/kline_cases/, 隐私不进这里)"
    return case


def resolve():
    """截止日后满 3 个交易日的案例 → 补真实路径 + 落在哪个情景 → 追加到 market-skill kline_cases.md"""
    L = load_cases()
    out = []
    for x in L:
        if x.get("对答案"):
            continue
        R = daily_rows(x["code"], "2099-01-01", 400)
        i = next((k for k, r in enumerate(R) if r[0] == x["截止日"]), None)
        if i is None or len(R) - 1 - i < 3:
            continue
        base = R[i][4]
        path = [{"d": r[0], "开%": round((r[1] / base - 1) * 100, 1), "高%": round((r[2] / base - 1) * 100, 1), "低%": round((r[3] / base - 1) * 100, 1), "收%": round((r[4] / base - 1) * 100, 1)} for r in R[i + 1:i + 4]]
        c3 = path[-1]["收%"]
        nm = "强" if c3 >= 5 else "弱" if c3 <= -5 else "震荡"
        sc = next((s for s in (x.get("统计", {}).get("3日", {}).get("情景") or []) if s["名"] == nm), None)
        d1 = x.get("统计", {}).get("次日", {})
        hit1 = None
        if d1.get("收盘") and d1["收盘"].get("P25") is not None:
            hit1 = d1["收盘"]["P25"] <= path[0]["收%"] <= d1["收盘"]["P75"]
        x["对答案"] = {"路径": path, "落在": nm, "当时给的概率": sc and sc["概率"], "次日收盘落在 P25~P75": hit1, "对答案时间": dt.datetime.now().isoformat(timespec="seconds")}
        out.append(x)
    save_cases(L)
    if out:
        t = SKILL_CASES.read_text(encoding="utf-8")
        add = []
        for x in out:
            a = x["对答案"]
            F = x["事实"]
            add.append(f"\n### {x['截止日']} {x['name']}({x['code']}) 看图案例 · 自动对答案 {a['对答案时间'][:10]}\n"
                       f"- 图: {'；'.join(g['类型'] for g in x['图'])}\n"
                       f"- 截止日: {F.get('板型')} · 连板 {F.get('连板')} · 涨跌 {F.get('涨跌%')}% · 收位 {F.get('收位%')}% · 量比 {F.get('量比5日')} · 首封 {F.get('首次封板')} · 开板 {F.get('开板次数(分钟级)')} · 箱体 {F.get('日线箱体')}\n"
                       f"- 当时 3 日情景: " + "；".join(f"{s['名']} {s['概率']}%" for s in (x.get('统计', {}).get('3日', {}).get('情景') or [])) + "\n"
                       f"- 看图判断: {x.get('看图判断') or '(无)'}\n"
                       f"- 真实 3 日: " + "；".join(f"{p['d'][5:]} 收 {p['收%']:+.1f}%(高 {p['高%']:+.1f} 低 {p['低%']:+.1f})" for p in a["路径"]) + f" → 落在 **{a['落在']}**(当时给 {a['当时给的概率']}%); 次日收盘落在 P25~P75: {a['次日收盘落在 P25~P75']}\n")
        SKILL_CASES.write_text(t.rstrip("\n") + "\n" + "".join(add), encoding="utf-8")
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("imgs", nargs="*")
    ap.add_argument("--code")
    ap.add_argument("--end")
    ap.add_argument("--note", default="")
    ap.add_argument("--resolve", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--redo", action="store_true", help="同一只票同一截止日重算(规则改了以后)")
    ap.add_argument("--enrich", action="store_true", help="给库里已有案例补 3 秒盘口(涨停过程 / 导师腿 / 用户腿), 保留看图判断")
    a = ap.parse_args()
    if a.resolve:
        r = resolve()
        print(f"对答案 {len(r)} 个: " + "; ".join(f"{x['name']} {x['截止日']} → {x['对答案']['落在']}" for x in r))
    elif a.enrich:
        L = load_cases()
        for x in L:
            enrich(x)
            print(x["key"], x["name"], "涨停过程" if x.get("涨停过程(3秒)") else "", sum(1 for e in x.get("导师买卖点") or [] if e.get("盘口")), "腿有盘口", x.get("用户实盘", ""))
        save_cases(L)
    elif a.list:
        for x in load_cases():
            print(x["key"], x["name"], "图", len(x["图"]), "对答案", (x.get("对答案") or {}).get("落在", "待"))
    else:
        c = intake(a.imgs, a.code, a.end, a.note, a.redo)
        print(json.dumps({k: c.get(k) for k in ("key", "name", "图", "事实", "统计", "导师买卖点", "盘后信息")}, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
