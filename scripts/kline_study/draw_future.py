# -*- coding: utf-8 -*-
"""draw_future.py — 在东方财富截图原图上续画未来 3 日(10/24 用户考题; 一个情景一张图)
日 K 图 → 续画 3 根未来日 K; 5 日分时图 → 续画 3 个未来日的分时
情景 / 路径: scen_next.scen3 —— 同状态历史样本(strong_next 匹配, 只用 10/23 之前)之后 3 个交易日的真实日 K, 按第 3 天收盘分 强 ≥+5% / 震荡 / 弱 ≤−5%;
  每档画"代表样本"的真实 3 根 K 线(按百分比套到本票 10/23 收盘价上), 文字给概率 + 第 3 天收盘 P25/中位/P75
日 K 校准: annotate_shot.bars 认实体 → 搜间距 / 最右一根 / 价格↔像素(颜色对得上 + 残差最小)
分时: 代表样本有 1 分钟线就画真实分时(按百分比套用), 没有就按它当天开高低收画示意(阳线先低后高, 阴线先高后低)
用法: python draw_future.py
v2(10/26): draw_v2(截图, "daily" / "intra", 代码, scen_v2.scen(...) 的输出, 输出目录, 截止日, C=, g=) —— 续画 2 天, 每个情景一张(top3 两日组合 + 极端)
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import annotate_shot as A   # noqa: E402
import draw_box as DB   # noqa: E402
import scen_next as SN   # noqa: E402

DL = Path("C:/Users/admin/Downloads")
FONT = "C:/Windows/Fonts/msyh.ttc"
COL = {"强": (255, 80, 80), "震荡": (230, 230, 230), "弱": (40, 210, 200)}
DAYS = ["10/26", "10/27", "10/28"]   # 默认(10/24 考题); 通用调用传 days=


def next_days(end, n=3):
    """end 之后 n 个交易日的 MM/DD(库里有就用库, 没有按工作日推; 节假日推不准, 只是标签)"""
    import datetime as dt_
    out, d = [], dt_.date.fromisoformat(end)
    while len(out) < n:
        d += dt_.timedelta(days=1)
        if d.weekday() < 5:
            out.append(d.strftime("%m/%d"))
    return out


def fail_text(nm, hi, lo):
    return {"强": f"失效: 跌破 10/23 最低 {lo:.2f}", "震荡": f"失效: 收盘越出 {lo:.2f}~{hi:.2f}", "弱": f"失效: 放量站上 10/23 最高 {hi:.2f}"}[nm]


def calib_daily(img, code, end):
    W, H = img.size
    cand = [(len(A.bars(img, int(H * t), int(H * (t + 0.165)), int(W * 0.015), int(W * 0.975))), t) for t in (0.395, 0.41, 0.425)]
    t = max(cand)[1]
    B = A.bars(img, int(H * t), int(H * (t + 0.165)), int(W * 0.015), int(W * 0.975))
    name, d, o, h, l_, cl, pc, v = DB.load(code, end, 120)
    xs = np.array([b[0] for b in B])
    colr = np.array([b[3] for b in B])
    sp = np.diff(xs)
    dx0 = float(np.median(sp[(sp > 8) & (sp < 40)]))
    best = None
    for dx in np.arange(dx0 * 0.9, dx0 * 1.1, 0.05):
        for sh in range(0, 6):
            xr = xs.max() + sh * dx
            pos = np.round((xr - xs) / dx).astype(int)
            if (np.abs((xr - xs) / dx - pos) > 0.3).mean() > 0.2:
                continue
            idx = len(cl) - 1 - pos
            ok = idx >= 0
            mis = float(np.mean((cl >= o)[idx[ok]] != (colr[ok] == "red")))
            P = np.concatenate([np.maximum(o, cl)[idx[ok]], np.minimum(o, cl)[idx[ok]]])
            Y = np.concatenate([np.array([q[1] for q in B])[ok], np.array([q[2] for q in B])[ok]])
            k, c0 = np.polyfit(P, Y, 1)
            res = np.abs(Y - (k * P + c0))
            keep = res <= max(np.percentile(res, 80), 2)
            k, c0 = np.polyfit(P[keep], Y[keep], 1)
            err = float(np.median(np.abs(Y - (k * P + c0))) / abs(k)) if k else 99
            if k < 0 and (best is None or mis * 10 + err < best[0]):
                best = (mis * 10 + err, dx, xr, k, c0, err, mis)
    _, dx, xr, k, c0, err, mis = best
    return {"dx": dx, "xr": xr, "py": lambda p: k * p + c0, "err": err, "mis": mis, "close": cl[-1], "high": h[-1], "low": l_[-1], "date": d[-1], "name": name}


def text_panel(dr, x, y, lines, f):
    for t, c in lines:
        dr.text((x, y), t, font=f, fill=c)
        y += int(f.size * 1.45)


def info_lines(name, tag, sc, S_, p0, hi, lo, days=None):
    days = days or DAYS
    col = COL[sc["名"]]
    rep = sc["代表样本"]
    q = sc["第3天收盘 P25/中位/P75"]
    L = [(f"{name} 情景{tag}: {sc['名']}(3 日)", col), (f"概率 {sc['概率']}%(样本 {sc['n']}/{S_['n']})", col)]
    for dd, p in zip(days, rep["path"]):
        L.append((f"{dd} 开 {p0 * (1 + p['o'] / 100):.2f} 高 {p0 * (1 + p['h'] / 100):.2f} 低 {p0 * (1 + p['l'] / 100):.2f} 收 {p0 * (1 + p['c'] / 100):.2f}({p['c']:+.1f}%)", (230, 230, 230)))
    L += [(f"本档第 3 天收盘 P25 / 中位 / P75: {q[0]:+.1f}% / {q[1]:+.1f}% / {q[2]:+.1f}%", (190, 190, 190)),
          (fail_text(sc["名"], hi, lo), (255, 200, 0)),
          (f"置信 {'中 55%' if S_['n'] >= 60 else '低 35%'} · 样本 {S_['n']}", (255, 200, 0)), ("(只看同状态统计, 没算题材 / 资金 / 消息)", (150, 150, 150)),
          (f"画的是代表样本 {rep['code']} {rep['d']} 之后 3 天的真实走势", (150, 150, 150)), ("(按百分比套到本票 10/23 收盘价上)", (150, 150, 150))]
    return L


def daily(shot, code, sc, tag, S_, outp, end="2026-10-23", days=None):
    days = days or DAYS
    img = Image.open(shot).convert("RGB")
    W, H = img.size
    C = calib_daily(img, code, end)
    dxw = C["dx"] * 1.6
    ext = int(dxw * 3 * 2.2 + 1050)
    cv = Image.new("RGB", (W + ext, H), (16, 16, 20))
    cv.paste(img, (0, 0))
    dr = ImageDraw.Draw(cv)
    fs, fx = ImageFont.truetype(FONT, 28), ImageFont.truetype(FONT, 20)
    p0, py = C["close"], C["py"]
    dr.line([W + 8, py(p0 * 1.2), W + 8, py(p0 * 0.8)], fill=(255, 200, 0), width=2)
    dr.text((W + 14, py(p0 * 1.2) - 34), "预测 3 日→", font=fs, fill=(255, 200, 0))
    dr.line([C["xr"], py(p0), W + 40 + dxw * 6.6, py(p0)], fill=(255, 200, 0), width=1)
    for i, (dd, p) in enumerate(zip(days, sc["代表样本"]["path"])):
        x = W + 40 + dxw * (i + 0.5) * 2.2
        P = [p0 * (1 + p[k] / 100) for k in ("o", "h", "l", "c")]
        up = P[3] >= P[0]
        cc = (255, 70, 70) if up else (40, 210, 200)
        dr.line([x, py(P[1]), x, py(P[2])], fill=cc, width=3)
        y_top, y_bot = py(max(P[0], P[3])), py(min(P[0], P[3]))
        dr.rectangle([x - dxw * 0.45, y_top, x + dxw * 0.45, max(y_bot, y_top + 3)], fill=None if up else cc, outline=cc, width=3)
        dr.text((x - 26, py(P[2]) + 8), dd, font=fx, fill=(200, 200, 200))
    text_panel(dr, int(W + 80 + dxw * 6.6), int(H * 0.25), info_lines(C["name"], tag, sc, S_, p0, C["high"], C["low"], days), fs)
    cv.save(outp)
    return C


# 5 日分时版式(显示坐标, ×1.39 = 原图): 上沿 / 0% / 下沿 y, 上沿百分比, 0% 对应价
INTRA = {"img_4eb83c6eef7c": {"top": 728, "zero": 1040, "bot": 1348, "pmax": 19.77, "base": 9.66},
         "img_4e724b4cf9c5": {"top": 792, "zero": 1100, "bot": 1408, "pmax": 9.77, "base": 8.70},
         "img_2ed145704786": {"top": 728, "zero": 1040, "bot": 1348, "pmax": 25.17, "base": 2.98}}


def intraday(shot, code, sc, tag, S_, outp, C, g=None, days=None):
    """g: 价格轴(原图坐标) {top, zero, bot, pmax, base}; 不给就按 INTRA 表(10/24 考题三张)"""
    days = days or DAYS
    img = Image.open(shot).convert("RGB")
    W, H = img.size
    g = g or {k: (v * 1.39 if k in ("top", "zero", "bot") else v) for k, v in INTRA[Path(shot).stem].items()}
    p0 = C["close"]

    def py0(p):
        return g["zero"] - ((p / g["base"] - 1) * 100) / g["pmax"] * (g["zero"] - g["top"])
    rp = sc["代表样本"]["path"]
    fut = [C["close"] * (1 + q[k] / 100) for q in rp for k in ("h", "l")]
    lo_p, hi_p = g["base"] * (1 - g["pmax"] / 100), g["base"] * (1 + g["pmax"] / 100)
    rescale = max(fut) > hi_p or min(fut) < lo_p   # 10/25: 单日分时只有 ±10%, 3 日路径会画出框 → 续画区用自己的价格轴(标出刻度)
    if rescale:
        lo2, hi2 = min(min(fut), lo_p), max(max(fut), hi_p)
        pad = (hi2 - lo2) * 0.05
        lo2, hi2 = lo2 - pad, hi2 + pad

        def py(p):
            return g["bot"] - (p - lo2) / (hi2 - lo2) * (g["bot"] - g["top"])
    else:
        py = py0
    day_w = int(g.get("day_w", 249))
    ext = day_w * 3 + 1050
    cv = Image.new("RGB", (W + ext, H), (16, 16, 20))
    cv.paste(img, (0, 0))
    dr = ImageDraw.Draw(cv)
    fs, fx = ImageFont.truetype(FONT, 28), ImageFont.truetype(FONT, 24)
    x0 = W - 18
    col = COL[sc["名"]]
    rep = sc["代表样本"]
    rng = np.random.default_rng(7)
    used_real = []
    for i, (dd, p) in enumerate(zip(days, rep["path"])):
        xa = x0 + i * day_w
        dr.rectangle([xa, g["top"], xa + day_w, g["bot"]], outline=(70, 70, 70), width=1)
        dr.line([xa, py(g["base"]), xa + day_w, py(g["base"])], fill=(110, 110, 110), width=1)
        if rescale and i == 0:   # 续画区自己的刻度(和左边原图刻度不同)
            for pv in (hi2, (hi2 + lo2) / 2, lo2, C["close"]):
                dr.text((xa + 4, py(pv) - 22), f"{pv:.2f}", font=ImageFont.truetype(FONT, 20), fill=(160, 160, 160))
        dr.text((xa + 50, g["bot"] + 8), dd, font=fx, fill=(255, 200, 0))
        prev_c = 0 if i == 0 else rep["path"][i - 1]["c"]
        mp = SN.minute_path(rep["sym"], p["d"])
        if mp:   # 真实分时: 样本当天每分钟价 / 样本当天收盘 × 本票按百分比折算的当天收盘
            pc_ = p0 * (1 + p["c"] / 100)
            pts = [(xa + 4 + j / (len(mp) - 1) * (day_w - 8), py(pc_ * v / mp[-1][1])) for j, (_, v) in enumerate(mp)]
            used_real.append(True)
        else:
            P = {k: p0 * (1 + p[k] / 100) for k in ("o", "h", "l", "c")}
            seq = [("o", 0), ("l", .25), ("h", .75), ("c", 1)] if P["c"] >= P["o"] else [("o", 0), ("h", .2), ("l", .7), ("c", 1)]
            key = [(xa + 4 + t * (day_w - 8), py(P[k])) for k, t in seq]
            pts = []
            for (a1, b1), (a2, b2) in zip(key, key[1:]):
                for s in np.linspace(0, 1, 16, endpoint=False):
                    pts.append((a1 + (a2 - a1) * s, b1 + (b2 - b1) * s + rng.normal(0, 3)))
            pts.append(key[-1])
            used_real.append(False)
        dr.line(pts, fill=col, width=3)
        yc = py(p0 * (1 + prev_c / 100))
        dr.line([xa, yc, xa + day_w, yc], fill=(255, 200, 0), width=1)   # 前一日收盘
    L = info_lines(C["name"], tag, sc, S_, p0, C["high"], C["low"], days)
    L.append(("分时: " + ("真实 1 分钟线" if all(used_real) else "代表样本没有分钟线, 按它当天开高低收画示意"), (150, 150, 150)))
    L.append(("(阳线先低后高, 阴线先高后低)" if not all(used_real) else "", (150, 150, 150)))
    text_panel(dr, x0 + day_w * 3 + 30, int(H * 0.25), [x for x in L if x[0]], fs)
    cv.save(outp)


# ================================================================ v2(10/26): 吃 scen_v2.scen() 的输出, 续画 2 天
COL_V2 = {"涨停": (255, 60, 60), "单边上涨": (255, 110, 110), "冲高A杀": (255, 160, 0), "高开低走": (230, 180, 60), "震荡": (230, 230, 230),
          "深V": (180, 120, 255), "单边下跌": (40, 210, 200), "跌停": (0, 170, 90)}


def v2_items(v2, which="两日", with_extreme=True):
    """scen_v2 输出 → 待画情景列表 [{名, 首日, 概率, 票型基线, 标签, 代表样本, 近邻路径, 因子}]
    which = "两日": top3 两日组合(2 天路径 = 同一个代表样本的真实 T+1 / T+2); "单日": top3 单日走法(T+2 照代表样本真实走势画)
    with_extreme: 涨停 / 跌停 / 冲高A杀 / 深V 不在 top3 但概率 ≥3% 的, 各出一张(标"极端")"""
    src = v2["top3_两日"] if which == "两日" else v2["top3_单日"]
    by_sc = v2.get("因子贡献", {}).get("按情景", {})
    out = []
    for i, x in enumerate(src):
        a = x["名"].split("→")[0]
        f1 = next((y for y in v2["top3_单日"] if y["名"] == a), None)
        fac = (f1 or {}).get("单因子top3") or (f1 or {}).get("因子贡献top3") or [f"{g} {v:+.1f}pp" for g, v in list((by_sc.get(a) or {}).items())[:3]]
        out.append({"名": x["名"], "首日": a, "概率": x["概率"], "票型基线": x.get("票型基线"), "标签": "ABC"[i], "代表样本": x["代表样本"],
                    "近邻路径": x.get("近邻路径") or {}, "因子": fac})
    if with_extreme:
        for e, y in (v2.get("极端", {}).get("极端代表样本") or {}).items():
            out.append({"名": e + "(极端)", "首日": e, "概率": v2["极端"]["T+1"][e]["模型"], "票型基线": v2["极端"]["T+1"][e]["票型基线"], "标签": "X",
                        "代表样本": y["代表样本"], "近邻路径": y.get("近邻路径") or {},
                        "因子": ((v2.get("因子贡献", {}).get("单因子(按情景, 绝对值最大 5 个)") or {}).get(e) or
                               [f"{g} {v:+.1f}pp" for g, v in list((by_sc.get(e) or {}).items())[:3]])[:3]})
    return out


def v2_lines(v2, it, p0, days):
    col = COL_V2.get(it["首日"], (230, 230, 230))
    rep = it["代表样本"]
    st = it["近邻路径"]
    L = [(f"{v2.get('name', '')} 情景{it['标签']}: {it['名']}", col),
         (f"概率 {it['概率']}%(同票型基线 {it.get('票型基线')}%) · 票型 {v2['票型']}", col)]
    for dd, p in zip(days, rep["path"]):
        L.append((f"{dd} 开 {p0 * (1 + p['o'] / 100):.2f} 高 {p0 * (1 + p['h'] / 100):.2f} 低 {p0 * (1 + p['l'] / 100):.2f} 收 {p0 * (1 + p['c'] / 100):.2f}({p['c']:+.1f}%)",
                  (230, 230, 230)))
    if st:
        q1, q2 = st.get("T+1收 P25/中位/P75"), st.get("T+2收(相对T收) P25/中位/P75")
        L.append((f"最像的 {st.get('近邻n')} 个同情景样本 P25/中位/P75: 第1天收 {q1[0]:+.1f}/{q1[1]:+.1f}/{q1[2]:+.1f}%", (190, 190, 190)))
        L.append((f"    第2天收(相对今天收盘) {q2[0]:+.1f}/{q2[1]:+.1f}/{q2[2]:+.1f}%", (190, 190, 190)))
    L.append(("因子贡献(这个因子让本情景概率 ±pp):", (255, 200, 0)))
    for x in it["因子"][:3]:
        L.append(("    " + x, (255, 200, 0)))
    L.append((f"置信 {v2.get('置信', '?')}", (255, 200, 0)))
    L.append((f"画的是代表样本 {rep['code']}{rep.get('name', '')} {rep['d']} 之后 2 天的真实走势", (150, 150, 150)))
    L.append(("(按百分比套到本票收盘价; 多因子 GBDT, 样本外见 docs/research/scen_v2_20261026.md)", (150, 150, 150)))
    return L


def daily_v2(shot, code, v2, it, outp, end, days=None):
    """日 K 截图 → 续画 2 根(代表样本真实开高低收按百分比套到本票收盘); 返回校准信息 C(分时续画要用)"""
    days = days or next_days(end, 2)
    img = Image.open(shot).convert("RGB")
    W, H = img.size
    C = calib_daily(img, code, end)
    dxw = C["dx"] * 1.6
    nd = 2
    cv = Image.new("RGB", (W + int(dxw * nd * 2.2 + 1250), H), (16, 16, 20))
    cv.paste(img, (0, 0))
    dr = ImageDraw.Draw(cv)
    fs, fx = ImageFont.truetype(FONT, 28), ImageFont.truetype(FONT, 20)
    p0, py = C["close"], C["py"]
    dr.line([W + 8, py(p0 * 1.2), W + 8, py(p0 * 0.8)], fill=(255, 200, 0), width=2)
    dr.text((W + 14, py(p0 * 1.2) - 34), f"预测 {nd} 日→", font=fs, fill=(255, 200, 0))
    dr.line([C["xr"], py(p0), W + 40 + dxw * nd * 2.2, py(p0)], fill=(255, 200, 0), width=1)
    for i, (dd, p) in enumerate(zip(days, it["代表样本"]["path"])):
        x = W + 40 + dxw * (i + 0.5) * 2.2
        P = [p0 * (1 + p[k] / 100) for k in ("o", "h", "l", "c")]
        up = P[3] >= P[0]
        cc = (255, 70, 70) if up else (40, 210, 200)
        dr.line([x, py(P[1]), x, py(P[2])], fill=cc, width=3)
        y_top, y_bot = py(max(P[0], P[3])), py(min(P[0], P[3]))
        dr.rectangle([x - dxw * 0.45, y_top, x + dxw * 0.45, max(y_bot, y_top + 3)], fill=None if up else cc, outline=cc, width=3)
        dr.text((x - 26, py(P[2]) + 8), dd, font=fx, fill=(200, 200, 200))
    text_panel(dr, int(W + 80 + dxw * nd * 2.2), int(H * 0.2), v2_lines(v2, it, p0, days), fs)
    cv.save(outp)
    return C


def intraday_v2(shot, code, v2, it, outp, C, g, days=None, end=None):
    """分时 / 五日截图 → 续画 2 天分时; 代表样本有 1 分钟线(scen_v2 的 "分钟(相对样本T收盘%)")就画真实分时, 没有按开高低收画示意
    g: 价格轴(原图坐标) {top, zero, bot, pmax, base, day_w}(kline_inbox 里由 OCR axis 换算, 同旧版 intraday); C: 至少有 close"""
    days = days or next_days(end or v2["T"], 2)
    img = Image.open(shot).convert("RGB")
    W, H = img.size
    p0 = C["close"]
    rep = it["代表样本"]
    mins = rep.get("分钟(相对样本T收盘%)") or {}

    def py0(p):
        return g["zero"] - ((p / g["base"] - 1) * 100) / g["pmax"] * (g["zero"] - g["top"])
    fut = [p0 * (1 + q[k] / 100) for q in rep["path"] for k in ("h", "l")]
    lo_p, hi_p = g["base"] * (1 - g["pmax"] / 100), g["base"] * (1 + g["pmax"] / 100)
    rescale = max(fut) > hi_p or min(fut) < lo_p
    if rescale:   # 续画路径越出原图价格轴 → 续画区用自己的价格轴(标出刻度)
        lo2, hi2 = min(min(fut), lo_p), max(max(fut), hi_p)
        pad = (hi2 - lo2) * 0.05
        lo2, hi2 = lo2 - pad, hi2 + pad

        def py(p):
            return g["bot"] - (p - lo2) / (hi2 - lo2) * (g["bot"] - g["top"])
    else:
        py = py0
    day_w = int(g.get("day_w", 249))
    cv = Image.new("RGB", (W + day_w * 2 + 1250, H), (16, 16, 20))
    cv.paste(img, (0, 0))
    dr = ImageDraw.Draw(cv)
    fs, fx = ImageFont.truetype(FONT, 28), ImageFont.truetype(FONT, 24)
    x0 = W - 18
    col = COL_V2.get(it["首日"], (230, 230, 230))
    rng = np.random.default_rng(7)
    used = []
    for i, (dd, p) in enumerate(zip(days, rep["path"])):
        xa = x0 + i * day_w
        dr.rectangle([xa, g["top"], xa + day_w, g["bot"]], outline=(70, 70, 70), width=1)
        if rescale and i == 0:
            for pv in (hi2, (hi2 + lo2) / 2, lo2, p0):
                dr.text((xa + 4, py(pv) - 22), f"{pv:.2f}", font=ImageFont.truetype(FONT, 20), fill=(160, 160, 160))
        dr.text((xa + 50, g["bot"] + 8), dd, font=fx, fill=(255, 200, 0))
        prev_c = 0 if i == 0 else rep["path"][i - 1]["c"]
        mp = mins.get(f"T+{i + 1}")
        if mp:
            pts = [(xa + 4 + j / (len(mp) - 1) * (day_w - 8), py(p0 * (1 + v / 100))) for j, v in enumerate(mp)]
            used.append(True)
        else:
            P = {k: p0 * (1 + p[k] / 100) for k in ("o", "h", "l", "c")}
            seq = [("o", 0), ("l", .25), ("h", .75), ("c", 1)] if P["c"] >= P["o"] else [("o", 0), ("h", .2), ("l", .7), ("c", 1)]
            key = [(xa + 4 + t * (day_w - 8), py(P[k])) for k, t in seq]
            pts = []
            for (a1, b1), (a2, b2) in zip(key, key[1:]):
                for s_ in np.linspace(0, 1, 16, endpoint=False):
                    pts.append((a1 + (a2 - a1) * s_, b1 + (b2 - b1) * s_ + rng.normal(0, 3)))
            pts.append(key[-1])
            used.append(False)
        dr.line(pts, fill=col, width=3)
        yc = py(p0 * (1 + prev_c / 100))
        dr.line([xa, yc, xa + day_w, yc], fill=(255, 200, 0), width=1)   # 前一日收盘
    L = v2_lines(v2, it, p0, days)
    L.append(("分时: " + " / ".join(f"第{i + 1}天" + ("真实 1 分钟线" if u else "无分钟线, 按开高低收示意") for i, u in enumerate(used)), (150, 150, 150)))
    text_panel(dr, x0 + day_w * 2 + 30, int(H * 0.2), L, fs)
    cv.save(outp)


def draw_v2(shot, kind, code, v2, out_dir, end, C=None, g=None, which="两日", with_extreme=True, days=None):
    """一张截图 × v2 的每个情景 → 一张图; kind = "daily"(日 K)/ "intra"(分时 / 五日, 要给 g, C 可选)
    返回 (输出路径列表, C); kline_inbox.predict 接法: 先对日 K 调(拿 C), 再对分时 / 五日调(g 同旧版由 OCR axis 换算)"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    days = days or next_days(end, 2)
    outs = []
    for it in v2_items(v2, which, with_extreme):
        op = out_dir / f"{code}_{Path(shot).stem}_v2_{it['标签']}{it['名'].replace('→', '-').replace('(极端)', '')}.png"
        if kind == "daily":
            C = daily_v2(shot, code, v2, it, op, end, days)
        else:
            intraday_v2(shot, code, v2, it, op, C or {"close": v2["收盘"]}, g, days, end)
        outs.append(str(op))
    return outs, C


JOBS = [("1", "img_5712e53a9513", "600851", "daily"), ("2", "img_4723f2c4b6d3", "002307", "daily"), ("3", "img_f6b5f1403cae", "002696", "daily"),
        ("4", "img_4eb83c6eef7c", "002696", "intra"), ("5", "img_4e724b4cf9c5", "600851", "intra"), ("6", "img_2ed145704786", "002307", "intra")]

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cache, cal = {}, {}
    out = []
    for no, stem, code, kind in JOBS:
        if code not in cache:
            f = ROOT / "scripts" / "temp" / f"scen3_{code}.json"
            cache[code] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else SN.scen3(code, "2026-10-26")
        S_ = cache[code]
        for i, sc in enumerate(S_["情景"]):
            tag = "ABC"[i]
            p = DL / f"q{no}_{code}_{tag}{sc['名']}.png"
            if kind == "daily":
                C = daily(DL / f"{stem}.jpg", code, sc, tag, S_, p)
                cal[code] = C
                if i == 0:
                    print(no, code, f"最右一根 {C['date']} 收 {C['close']:.2f} 颜色对不上 {C['mis']:.0%} 校准误差 {C['err']:.3f} 元")
            else:
                intraday(DL / f"{stem}.jpg", code, sc, tag, S_, p, cal[code])
            out.append(str(p))
    print("\n".join(out))
