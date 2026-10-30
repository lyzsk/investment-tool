# -*- coding: utf-8 -*-
"""draw_future.py — 在东方财富截图原图上续画未来 3 日(10/24 用户考题; 一个情景一张图)
日 K 图 → 续画 3 根未来日 K; 5 日分时图 → 续画 3 个未来日的分时
情景 / 路径: scen_next.scen3 —— 同状态历史样本(strong_next 匹配, 只用 10/23 之前)之后 3 个交易日的真实日 K, 按第 3 天收盘分 强 ≥+5% / 震荡 / 弱 ≤−5%;
  每档画"代表样本"的真实 3 根 K 线(按百分比套到本票 10/23 收盘价上), 文字给概率 + 第 3 天收盘 P25/中位/P75
日 K 校准: annotate_shot.bars 认实体 → 搜间距 / 最右一根 / 价格↔像素(颜色对得上 + 残差最小)
分时: 代表样本有 1 分钟线就画真实分时(按百分比套用), 没有就按它当天开高低收画示意(阳线先低后高, 阴线先高后低)
用法: python draw_future.py
v2(10/26): draw_v2(截图, "daily" / "intra", 代码, scen_v2.scen(...) 的输出, 输出目录, 截止日, C=, g=, pa=, pa_md=) —— 续画 2 天;
  每张截图 4 张: 两日组合 top3 各一张(_v2_1/_v2_2/_v2_3) + 极端合成一张(_v2_X极端); 右侧总表 = 票型 / 单日 top3 / 两日 top3 / 极端概率 / 置信·样本 /
  本图情景 / pa_reason 关键结论(K1 形态·箱体·抛压支撑·竞价切换表) / 不自信点; 分时续画的价格轴 = 原图 OCR 价格轴(越界就把框外延, 不另起刻度)
  上面的 3 日旧版(daily / intraday, scen3 强/震荡/弱)留作 kline_inbox 的兜底
"""
import json
import re
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
# 每张截图出 4 张: 两日组合 top3 各一张(_v2_1 / _v2_2 / _v2_3) + 极端合成一张(_v2_X极端: 涨停 / 跌停 / 冲高A杀 / 深V 不在单日 top3 且 ≥3% 的, 各画自己的代表样本)
# 每张右侧同一块总表: 票型 · 单日 top3 · 两日 top3 · 极端概率 · 置信 / 样本 · 本图情景 · pa_reason 关键结论 · 不自信点
COL_V2 = {"涨停": (255, 60, 60), "单边上涨": (255, 110, 110), "冲高A杀": (255, 160, 0), "高开低走": (230, 180, 60), "震荡": (230, 230, 230),
          "深V": (180, 120, 255), "单边下跌": (40, 210, 200), "跌停": (0, 170, 90)}
EXT_V2 = ("涨停", "跌停", "冲高A杀", "深V")
PANEL_W = 1180
YEL, GRY, WHT, CYN = (255, 200, 0), (150, 150, 150), (230, 230, 230), (120, 200, 255)


UP_W = ("涨停", "单边上涨", "深V")
DN_W = ("跌停", "单边下跌", "冲高A杀", "高开低走")


def wdir(w):
    return "涨" if w in UP_W else "跌" if w in DN_W else "平"


def v2_pair(v2, fac=lambda a: []):
    """10/28 晚用户定: 每只票只画 2 张 —— 正例 = 两日组合概率第 1(标过不过半)/ 反例 = 首日方向和正例相反的里概率最高的那个
    (候选 = 两日 top3 的其余 + 极端情景 涨停 / 跌停 / 冲高A杀 / 深V; 正例是「平(震荡)」时取涨向 / 跌向里概率最高的); 连板 / 连跌停票的涨跌停就在这里一起排"""
    cand = []
    for x in v2.get("top3_两日") or []:
        a = x["名"].split("→")[0]
        cand.append({"名": x["名"], "首日": a, "概率": x["概率"], "口径": "两日组合", "票型基线": x.get("票型基线"), "代表样本": x.get("代表样本"),
                     "近邻路径": x.get("近邻路径") or {}, "因子": fac(a), "T+2分布": next((v for k, v in x.items() if k.endswith("T+2 分布%")), None)})
    for e, y in ((v2.get("极端") or {}).get("极端代表样本") or {}).items():
        if y.get("代表样本"):
            cand.append({"名": e, "首日": e, "概率": v2["极端"]["T+1"][e]["模型"], "口径": "T+1 单日", "票型基线": v2["极端"]["T+1"][e]["票型基线"],
                         "代表样本": y["代表样本"], "近邻路径": y.get("近邻路径") or {}, "因子": fac(e)})
    cand = [c for c in cand if c.get("代表样本")]
    if not cand:
        return []
    allw = v2.get("全部走法%") or {}
    side = {k: round(sum(float(v["模型"] if isinstance(v, dict) else v) for w, v in allw.items() if wdir(w) == k), 1) for k in ("涨", "跌", "平")} if allw else {}
    # 正例 = 涨向 / 跌向 / 平(震荡) 三个方向里合计概率最高的那个方向; 反例 = 涨跌里另一个方向(正例是平时 = 涨跌里大的那个)
    ps = max(side, key=side.get) if side else wdir(cand[0]["首日"])
    rs = ("跌" if ps == "涨" else "涨") if ps != "平" else max(("涨", "跌"), key=lambda k: side.get(k, 0))

    def best(sd):
        xs = [c for c in cand if wdir(c["首日"]) == sd]
        return max(xs, key=lambda c: (c["口径"] == "两日组合", c["概率"])) if xs else None
    out = []
    for lab, sd in (("1正例", ps), ("2反例", rs)):
        c = best(sd)
        if c:
            c = dict(c)
            c.update(标签=lab, 方向=sd, 方向概率=side.get(sd), 过半=(side.get(sd) or 0) >= 50, 方向合计=side)
            out.append(c)
    return out


def v2_items(v2, with_extreme=True):
    """scen_v2 输出 → 待画情景: 默认两日组合 top1 / top2 各一张(10/30 用户定);
    KLINE_PAIR=1 退回旧「正例 + 反例」; KLINE_PAIR=0 退回两日 top3 + 极端。两天路径 = 同一个代表样本的真实 T+1 / T+2"""
    fc = v2.get("因子贡献") or {}
    by_sc, single = fc.get("按情景") or {}, fc.get("单因子(按情景, 绝对值最大 5 个)") or {}

    def fac(a):
        f1 = next((y for y in v2["top3_单日"] if y["名"] == a), None)
        return ((f1 or {}).get("单因子top3") or single.get(a) or [f"{g} {v:+.1f}pp" for g, v in list((by_sc.get(a) or {}).items())[:3]])[:3]
    import os
    mode = os.environ.get("KLINE_PAIR", "top2")   # 10/30 用户定: 默认只画两日组合概率 top1 / top2; 1 = 旧正例+反例; 0 = 旧 top3 + 极端
    if mode == "1":
        return v2_pair(v2, fac)
    out = []
    pairs = v2["top3_两日"][:2] if mode == "top2" else v2["top3_两日"]
    for i, x in enumerate(pairs):
        a = x["名"].split("→")[0]
        out.append({"标签": str(i + 1), "名": x["名"], "首日": a, "概率": x["概率"], "票型基线": x.get("票型基线"), "代表样本": x.get("代表样本"),
                    "近邻路径": x.get("近邻路径") or {}, "因子": fac(a), "T+2分布": next((v for k, v in x.items() if k.endswith("T+2 分布%")), None)})
    if with_extreme and mode != "top2":
        ex = []
        for e, y in ((v2.get("极端") or {}).get("极端代表样本") or {}).items():
            if y.get("代表样本"):
                ex.append({"名": e, "首日": e, "概率": v2["极端"]["T+1"][e]["模型"], "票型基线": v2["极端"]["T+1"][e]["票型基线"],
                           "代表样本": y["代表样本"], "近邻路径": y.get("近邻路径") or {}, "因子": fac(e)})
        if ex:
            out.append({"标签": "X", "名": "极端", "首日": "极端", "子": ex, "代表样本": ex[0]["代表样本"]})
    return [x for x in out if x.get("代表样本")]


def _pa_n(pa):
    m = re.search(r"→ n=(\d+)", ((pa or {}).get("未来2根") or {}).get("样本", ""))
    return int(m.group(1)) if m else None


def _ledger_calib_line(v2):
    """预测核销账本 → 图右侧「本类事前命中」; 样本 <10 不显示, 不阻塞画图"""
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
        import forecast_ledger as FL
        c = FL.db()
        r = FL.calib(c, "kline_v2", "two_day_top1", f"票型:{v2.get('票型') or '未知'}")
        c.close()
        if r["n"] >= 10 and r["hit"] is not None:
            return f"本类事前 top1 命中 {r['hit']:.0%} · 基线 {r['baseline']:.0%} · n={r['n']}"
    except Exception:   # noqa: BLE001
        pass
    return None


def v2_summary(v2):
    """每张图都一样的总表: 票型 / top3 / 两日 top3 / 极端 / 置信 / 样本"""
    s = v2.get("状态摘要") or {}
    lim = 20 if v2.get("20cm") else 10
    import os
    if os.environ.get("KLINE_SHORT", "1") == "1":   # 10/28 晚用户: 行文太费劲 → 只留 3 行(票 / 方向合计 / 命中参考)
        allw = v2.get("全部走法%") or {}
        side = {k: round(sum(float(v["模型"] if isinstance(v, dict) else v) for w, v in allw.items() if wdir(w) == k), 1) for k in ("涨", "跌", "平")}
        return [(f"{v2.get('name', '')}({v2['code']}) {v2['T'][5:]} 收 {v2['收盘']:.2f} · {v2['票型']}" + (f" · {v2['连板高度']} 连板" if v2.get("连板高度") else ""), YEL),
                (f"明后两天方向: 涨 {side['涨']}% · 跌 {side['跌']}% · 平 {side['平']}%(涨停价 {v2['收盘'] * (1 + lim / 100):.2f} / 跌停价 {v2['收盘'] * (1 - lim / 100):.2f})", WHT),
                ("参考: 方向命中率 44%(54 只回算, 永远猜震荡 43%)—— 当参考, 不当结论", GRY)] + ([(_ledger_calib_line(v2), GRY)] if _ledger_calib_line(v2) else [])
    L = [(f"{v2.get('name', '')}({v2['code']}) 截止 {v2['T']} 收 {v2['收盘']:.2f} · 票型「{v2['票型']}」"
          + (f" · {v2['连板高度']} 连板" if v2.get("连板高度") else "") + (" · 20cm" if v2.get("20cm") else ""), YEL),
         (f"当天 {s.get('当天涨跌%')}% · 收在当天 {s.get('收在当天位置')} · 量比 {s.get('量比5日')} · 近20日涨停 {s.get('近20日涨停次数')} 次 · {s.get('箱体', '')}", GRY),
         ("── v2 引擎(多因子 GBDT + 近邻样本, 样本外验证) ──", CYN),
         ("T+1 单日 top3(模型 / 同票型基线):", WHT)]
    for i, x in enumerate(v2["top3_单日"]):
        L.append((f"  {i + 1}. {x['名']} {x['概率']}%(基线 {x['票型基线']}%)", COL_V2.get(x["名"], WHT)))
    L.append(("两日组合 top3(T+1→T+2, 模型 / 同票型基线):", WHT))
    for i, x in enumerate(v2["top3_两日"]):
        L.append((f"  {i + 1}. {x['名']} {x['概率']}%(基线 {x.get('票型基线')}%)", COL_V2.get(x["名"].split("→")[0], WHT)))
    e = v2.get("极端") or {}
    L.append(("极端 T+1(模型 / 基线): " + " · ".join(f"{k} {v['模型']}/{v['票型基线']}%" for k, v in (e.get("T+1") or {}).items()), (255, 140, 140)))
    L.append(("极端 T+2: " +" · ".join(f"{k} {v}%" for k, v in (e.get("T+2") or {}).items())
              + f" · 两天内至少一次涨停 {e.get('两天内至少一次涨停%')}% / 跌停 {e.get('两天内至少一次跌停%')}%", (255, 140, 140)))
    L.append((f"(T+1 涨停价 ≈ {v2['收盘'] * (1 + lim / 100):.2f} / 跌停价 ≈ {v2['收盘'] * (1 - lim / 100):.2f})", GRY))
    bt = (v2.get("样本外") or {}).get("本票型") or {}
    L.append((f"置信 {v2.get('置信', '?')}", YEL))
    if bt:
        L.append((f"样本: 本票型{('(' + bt['口径'] + ')') if bt.get('口径') else ''}样本外 n={bt.get('n')} · 单日 top3 命中 模型 {bt.get('单日top3_模型', 0):.0%} / 基线 {bt.get('单日top3_票型基线', 0):.0%}"
                  f" · 两日 top3 命中 模型 {bt.get('两日top3_模型', 0):.0%} / 基线 {bt.get('两日top3_票型基线', 0):.0%}", YEL))
    if _ledger_calib_line(v2):
        L.append((_ledger_calib_line(v2), GRY))
    return L


def v2_scen_lines(v2, it, p0, days):
    """本图画的情景"""
    if it["标签"] == "X":
        L = [("── 本图: 极端情景(不在单日 top3 的, 各画一个最像的真实样本) ──", (255, 140, 140))]
        for x in it["子"]:
            rep = x["代表样本"]
            L.append((f"{x['名']} {x['概率']}%(基线 {x['票型基线']}%) · {rep['code']}{rep.get('name', '')} {rep['d']} 之后 2 天:", COL_V2.get(x["名"], WHT)))
            L.append(("    " + " → ".join(f"{dd} 收 {p0 * (1 + p['c'] / 100):.2f}({p['c']:+.1f}%, 高 {p0 * (1 + p['h'] / 100):.2f} 低 {p0 * (1 + p['l'] / 100):.2f})"
                                          for dd, p in zip(days, rep["path"])), WHT))
            if x["因子"]:
                L.append(("    因子: " + "; ".join(x["因子"][:2]), GRY))
        return L
    col = COL_V2.get(it["首日"], WHT)
    rep, st = it["代表样本"], it["近邻路径"]
    if it.get("方向"):   # 正例 / 反例: 一行结论 + 一行路径
        return [(f"── {it['标签'][1:]}: 偏{it['方向']} {it.get('方向概率')}%{'(过半)' if it.get('过半') else '(没过半)'} · 画的是这个方向里最可能的「{it['名']}」{it['概率']}%" + ("(深V = 先杀后拉, 收盘可能仍收绿)" if it['首日'] == '深V' else "") + " ──", col),
                ("  " + " → ".join(f"{dd} 收 {p0 * (1 + p['c'] / 100):.2f}({p['c']:+.1f}%)" for dd, p in zip(days, rep["path"])), WHT)]
    L = [(f"── 本图: 两日组合 {it['标签']}  {it['名']}  {it['概率']}%(同票型基线 {it.get('票型基线')}%) ──", col)]
    if it.get("T+2分布"):
        L.append((f"T+1={it['首日']} 时 T+2: " + " / ".join(f"{k} {v}%" for k, v in it["T+2分布"].items()), GRY))
    for dd, p in zip(days, rep["path"]):
        L.append((f"{dd} 开 {p0 * (1 + p['o'] / 100):.2f} 高 {p0 * (1 + p['h'] / 100):.2f} 低 {p0 * (1 + p['l'] / 100):.2f} 收 {p0 * (1 + p['c'] / 100):.2f}({p['c']:+.1f}%)", WHT))
    if st:
        q1, q2 = st.get("T+1收 P25/中位/P75"), st.get("T+2收(相对T收) P25/中位/P75")
        L.append((f"最像的 {st.get('近邻n')} 个同情景样本: 第1天收 P25/中位/P75 {q1[0]:+.1f}/{q1[1]:+.1f}/{q1[2]:+.1f}%, "
                  f"第2天收(相对今收) {q2[0]:+.1f}/{q2[1]:+.1f}/{q2[2]:+.1f}%", GRY))
    if it["因子"]:
        L.append((f"因子(把 T+1「{it['首日']}」推高 + / 压低 −): " + "; ".join(it["因子"][:3]), GRY))
    L.append((f"画的是 {rep['code']}{rep.get('name', '')} {rep['d']} 之后 2 天的真实走势(按百分比套到本票收盘)", GRY))
    return L


def pa_lines(pa, md=None):
    if not pa:
        return [("── pa_reason: 没有(ST / 北交所 / 生成失败), 只看 v2 ──", GRY)]
    Fu = pa.get("未来2根") or {}
    L = [(f"── pa_reason 逐根推理(另一套: 同状态历史样本 n={_pa_n(pa)}, 没做样本外) ──", CYN)]
    k1 = (pa.get("逐根") or [{}])[-1]
    L.append((f"K1 {str(k1.get('日', ''))[5:]} {k1.get('形态', '')}", WHT))
    for kk in ("谁被套 / 抛压", "谁在买", "支撑"):
        for s_ in (k1.get(kk) or [])[:1]:
            L.append(("  " + s_, GRY))
    bg = pa.get("背景") or {}
    for kk in ("日线箱体(KD1)", "近 5 日上方套牢盘"):
        if bg.get(kk):
            L.append((f"{kk.split('(')[0]}: {bg[kk]}", GRY))
    if Fu.get("T+1 走法"):
        L.append(("pa T+1 走法: " + " / ".join(f"{x['走法']} {x['概率%']}%(基准 {x['基准%']})" for x in Fu["T+1 走法"][:4]), WHT))
    for s_ in (Fu.get("推理步") or [])[:3]:
        L.append((f"{s_['步'].split(':')[0]}: {s_['统计']}", GRY))
    if Fu.get("竞价开盘切换"):
        L.append(("竞价开盘 → 情景切换(9:25 可看):", YEL))
        L += [("  " + x, YEL) for x in Fu["竞价开盘切换"]]
    if md:
        L.append((f"全文: {md}", GRY))
    return L


def v2_doubts(v2, pa=None):
    """不自信点(机器按数据生成)"""
    D = []
    top = v2["top3_单日"]
    s3 = sum(x["概率"] for x in top)
    if s3 < 80:
        D.append(f"单日 top3 合计只有 {s3:.0f}%: 另 {100 - s3:.0f}% 落在其他 5 种走法")
    bt = (v2.get("样本外") or {}).get("本票型") or {}
    m2, b2 = bt.get("两日top3_模型"), bt.get("两日top3_票型基线")
    if m2 is not None and b2 is not None:
        D.append(f"两日组合样本外 top3 命中只有 {m2:.0%}(只按票型 {b2:.0%})" + (": 没赢基线, 两日只当参考" if m2 <= b2 + 0.01 else ""))
    single = (v2.get("因子贡献") or {}).get("单因子(按情景, 绝对值最大 5 个)") or {}
    names = {x["名"] for x in top}
    cand = top + [{"名": e, "概率": v["模型"], "票型基线": v["票型基线"]} for e, v in ((v2.get("极端") or {}).get("T+1") or {}).items() if e not in names]
    dev = []
    for x in cand:
        if x.get("票型基线") is not None and abs(x["概率"] - x["票型基线"]) >= 8:
            f = single.get(x["名"]) or []
            dev.append(f"{x['名']} {x['概率']} vs {x['票型基线']}" + (f"({f[0].split(' → ')[0]} {f[0].split(' → ')[-1]})" if f else ""))
    if dev:
        D.append("模型和同票型基线偏离 ≥8pp(靠下列因子拉开, 偏离越大越要打折): " + "; ".join(dev))
    zt20 = (v2.get("状态摘要") or {}).get("近20日涨停次数") or 0
    if v2.get("票型") in ("箱体震荡", "趋势") and zt20 >= 2:
        D.append(f"票型归「{v2['票型']}」但近 20 日涨停 {zt20} 次: 同票型基线代表普通票、不像本票(样本外口径已换成活跃平常票)")
    k = 0
    for ev in v2.get("同类证据") or []:
        for s_ in ev.get("相对同票型全体偏离最大") or []:
            nm, v = s_.rsplit(" ", 1)
            try:
                val = float(v.replace("pp", ""))
            except ValueError:
                continue
            if nm in EXT_V2 and abs(val) >= 8 and k < 2:
                D.append(f"模型外信号「{ev['信号']}」: 同票型 n={ev['同票型样本n']} 里 {nm} {v}(这类数据没进模型)")
                k += 1
    pt = ((pa or {}).get("未来2根") or {}).get("T+1 走法") or []
    if pt:
        pm = {x["走法"]: x["概率%"] for x in pt}
        vm = {k_: v["模型"] for k_, v in (v2.get("全部走法%") or {}).items()}
        if pt[0]["走法"] != top[0]["名"]:
            D.append(f"和 pa_reason 首选不一致: pa {pt[0]['走法']} {pt[0]['概率%']}% vs v2 {top[0]['名']} {top[0]['概率']}%")
        diff = [f"{w} pa {pm[w]}% / v2 {vm[w]}%" for w in EXT_V2 if w in pm and w in vm and abs(pm[w] - vm[w]) >= 5]
        if diff:
            D.append("两套口径极端概率差 ≥5pp: " + "; ".join(diff))
    D.append("续画画的是 1 个最像的真实样本(不是中位路径), 区间看「最像的 50 个」P25~P75")
    D.append("题材 / 消息 / 盘口 / 竞价没进模型; 9:25 竞价出来按上面切换表改判")
    return D


def _wrap(lines, f, width):
    dr = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    out = []
    for t, c in lines:
        cur = ""
        for ch in t:
            if dr.textlength(cur + ch, font=f) > width and cur.strip():
                out.append((cur, c))
                cur = "      " + ch
            else:
                cur += ch
        out.append((cur, c))
    return out


def v2_panel_lines(v2, it, p0, days, pa=None, pa_md=None, extra=None):
    import os
    if os.environ.get("KLINE_SHORT", "1") == "1" and it.get("方向"):   # 10/28 晚用户: 行文太费劲 → 结论 + 两个概率 + 路径 + 不自信点一句; 衔接校准 / pa 全文 / 长不自信点 进 _status.json 和 pa_reason md
        ds = v2_doubts(v2, pa)
        return v2_summary(v2) + [("", WHT)] + v2_scen_lines(v2, it, p0, days) + [("", WHT), ("不自信点: " + (ds[0] if ds else "样本少"), (255, 170, 170))]
    L = v2_summary(v2) + [("", WHT)] + v2_scen_lines(v2, it, p0, days) + (extra or []) + [("", WHT)] + pa_lines(pa, pa_md) + [("", WHT)]
    L.append(("不自信点:", (255, 120, 120)))
    L += [(f"  · {x}", (255, 170, 170)) for x in v2_doubts(v2, pa)]
    return L


def _panel(cv, x, lines, H):
    """自动选字号放下全部文字; 返回实际高度"""
    dr = ImageDraw.Draw(cv)
    for fs in (25, 23, 21, 19):
        f = ImageFont.truetype(FONT, fs)
        w = _wrap(lines, f, PANEL_W - 20)
        lh = int(fs * 1.4)
        if 30 + len(w) * lh <= H - 20 or fs == 19:
            break
    y = 30
    for t, c in w:
        dr.text((x, y), t, font=f, fill=c)
        y += lh
    return y


def _candle(dr, x, half, py, P, label=None, fx=None):
    up = P[3] >= P[0]
    cc = (255, 70, 70) if up else (40, 210, 200)
    dr.line([x, py(P[1]), x, py(P[2])], fill=cc, width=3)
    y_top, y_bot = py(max(P[0], P[3])), py(min(P[0], P[3]))
    dr.rectangle([x - half, y_top, x + half, max(y_bot, y_top + 3)], fill=None if up else cc, outline=cc, width=3)
    if label:
        dr.text((x - 26, py(P[2]) + 8), label, font=fx, fill=(200, 200, 200))


def daily_v2(shot, code, v2, it, outp, end, days=None, pa=None, pa_md=None):
    """日 K 截图 → 续画 2 根(代表样本真实开高低收按百分比套到本票收盘; 价格↔像素用 calib_daily 校准, 和原图对齐); 返回 C(分时续画要用)"""
    days = days or next_days(end, 2)
    img = Image.open(shot).convert("RGB")
    W, H = img.size
    C = calib_daily(img, code, end)
    dxw = C["dx"] * 1.6
    slot = dxw * 2.2
    groups = it["子"] if it["标签"] == "X" else [it]
    gw = slot * 2 + (slot * 0.8 if len(groups) > 1 else 0)
    xa = W + 40
    area = gw * len(groups)
    px = int(xa + area + 40)
    cv = Image.new("RGB", (px + PANEL_W + 20, H), (16, 16, 20))
    cv.paste(img, (0, 0))
    dr = ImageDraw.Draw(cv)
    fs, fx = ImageFont.truetype(FONT, 28), ImageFont.truetype(FONT, 20)
    p0, py = C["close"], C["py"]
    dr.line([W + 8, py(p0 * 1.2), W + 8, py(p0 * 0.8)], fill=YEL, width=2)
    dr.text((W + 14, py(p0 * 1.2) - 34), "预测 2 日→", font=fs, fill=YEL)
    dr.line([C["xr"], py(p0), xa + area, py(p0)], fill=YEL, width=1)
    dr.text((xa + area - 70, py(p0) - 24), f"{p0:.2f}", font=fx, fill=YEL)
    for gi, g_ in enumerate(groups):
        gx = xa + gi * gw
        path = g_["代表样本"]["path"]
        if len(groups) > 1:
            top_p = max(p0 * (1 + p["h"] / 100) for p in path)
            dr.text((gx, py(top_p) - 72), f"{g_['名']}\n{g_['概率']}%", font=ImageFont.truetype(FONT, 22), fill=COL_V2.get(g_["名"], WHT))
        for i, (dd, p) in enumerate(zip(days, path)):
            P = [p0 * (1 + p[k] / 100) for k in ("o", "h", "l", "c")]
            _candle(dr, gx + slot * (i + 0.5), dxw * 0.45, py, P, dd, fx)
    _panel(cv, px, v2_panel_lines(v2, it, p0, days, pa, pa_md), H)
    cv.save(outp)
    return C


def _intra_pts(rep, i, p0, xa, day_w, py, rng):
    """第 i 天的分时点: 代表样本有 1 分钟线就用真实的, 没有按开高低收示意(阳线先低后高, 阴线先高后低)"""
    mp = (rep.get("分钟(相对样本T收盘%)") or {}).get(f"T+{i + 1}")
    if mp:
        return [(xa + 4 + j / (len(mp) - 1) * (day_w - 8), py(p0 * (1 + v / 100))) for j, v in enumerate(mp)], True
    p = rep["path"][i]
    P = {k: p0 * (1 + p[k] / 100) for k in ("o", "h", "l", "c")}
    seq = [("o", 0), ("l", .25), ("h", .75), ("c", 1)] if P["c"] >= P["o"] else [("o", 0), ("h", .2), ("l", .7), ("c", 1)]
    key = [(xa + 4 + t * (day_w - 8), py(P[k])) for k, t in seq]
    pts = []
    for (a1, b1), (a2, b2) in zip(key, key[1:]):
        for s_ in np.linspace(0, 1, 16, endpoint=False):
            pts.append((a1 + (a2 - a1) * s_, b1 + (b2 - b1) * s_ + rng.normal(0, 3)))
    pts.append(key[-1])
    return pts, False


def snap_axis(img, g):
    """OCR 的 top_y / bot_y 是刻度文字中心, 东方财富把刻度字放在框线内侧(10/26 实测 6 张: 文字中心比框线往里 19~22px) → 上沿百分比对应的是框线;
    0% 用虚线行。找得到框线 / 虚线就换成它们(价格↔像素和原图曲线对齐, 实测 9.244 那根线误差 1px), 找不到保持 OCR 值"""
    a = np.asarray(img.convert("L")).astype(int)
    H, W = a.shape
    xs = slice(int(W * 0.08), int(W * 0.45))

    def frame(y0, dr):
        for d in range(3, 41):
            y = int(round(y0)) + dr * d
            if not 3 <= y < H - 3:
                return None
            r = a[y, xs]
            m = np.median(r)
            if m > 22 and (np.abs(np.diff(r)) < 6).mean() > 0.8 and max(np.median(a[y - 3, xs]), np.median(a[y + 3, xs])) < m - 6:
                return y
        return None
    t, b = frame(g["top"], -1), frame(g["bot"], 1)
    zs = [y for y in range(int(g["zero"]) - 8, int(g["zero"]) + 9) if 0 <= y < H and ((a[y, xs] > 45) & (a[y, xs] < 140)).mean() > 0.3]
    out = dict(g)
    if zs:
        near = min(zs, key=lambda y: abs(y - g["zero"]))
        out["zero"] = float(np.mean([y for y in zs if abs(y - near) <= 2]))
    ob = (b - g["bot"]) if b else None
    if t:
        out["top"] = float(t)
    elif ob and 10 <= ob <= 35:
        out["top"] = g["top"] - ob
    if b:
        out["bot"] = float(b)
    out["校准"] = f"框线 上 {g['top']:.0f}→{out['top']:.0f} 0% {g['zero']:.0f}→{out['zero']:.0f} 下 {g['bot']:.0f}→{out['bot']:.0f}"
    return out


def intraday_v2(shot, code, v2, it, outp, C, g, days=None, end=None, pa=None, pa_md=None):
    """分时 / 五日截图 → 续画 2 天分时; 价格↔像素一律用原图价格轴(OCR axis, 不另起刻度), 路径越出原图上下沿就把框往外延
    g: 价格轴(原图坐标) {top, zero, bot, pmax, base, day_w}; C: 至少有 close"""
    days = days or next_days(end or v2["T"], 2)
    img = Image.open(shot).convert("RGB")
    W, H = img.size
    p0 = C["close"]
    g = snap_axis(img, g)

    def py(p):
        return g["zero"] - ((p / g["base"] - 1) * 100) / g["pmax"] * (g["zero"] - g["top"])
    groups = it["子"] if it["标签"] == "X" else [it]
    rng = np.random.default_rng(7)
    day_w = int(g.get("day_w", 249))
    x0 = W - 18
    curves, used = [], []
    for g_ in groups:
        for i in range(min(2, len(g_["代表样本"]["path"]))):
            pts, real = _intra_pts(g_["代表样本"], i, p0, x0 + i * day_w, day_w, py, rng)
            curves.append((g_, i, pts))
            used.append((g_["名"], i, real))
    ys = [y for _, _, pts in curves for _, y in pts]
    y_hi = max(5, min(g["top"], min(ys) - 15))
    y_lo = min(H - 40, max(g["bot"], max(ys) + 15))
    px = x0 + day_w * 2 + 185
    cv = Image.new("RGB", (px + PANEL_W + 20, H), (16, 16, 20))
    cv.paste(img, (0, 0))
    dr = ImageDraw.Draw(cv)
    fx, f20 = ImageFont.truetype(FONT, 24), ImageFont.truetype(FONT, 20)
    for i, dd in enumerate(days[:2]):
        xa = x0 + i * day_w
        dr.rectangle([xa, y_hi, xa + day_w, y_lo], outline=(70, 70, 70), width=1)
        dr.text((xa + 50, y_lo + 8), dd, font=fx, fill=YEL)
    xr = x0 + day_w * 2
    lim = 20 if v2.get("20cm") else 10
    marks = [(g["base"] * (1 + g["pmax"] / 100), "原图上沿", (110, 110, 110)), (g["base"], "原图 0%", (110, 110, 110)),
             (g["base"] * (1 - g["pmax"] / 100), "原图下沿", (110, 110, 110)),
             (p0, "今收", YEL), (p0 * (1 + lim / 100), "T+1 涨停", (255, 90, 90)), (p0 * (1 - lim / 100), "T+1 跌停", (40, 200, 120))]
    for pv, nm, cc in marks:
        y = py(pv)
        if y_hi - 2 <= y <= y_lo + 2:
            for xs in range(int(x0), int(xr), 12):
                dr.line([xs, y, xs + 6, y], fill=cc, width=1)
            dr.text((xr + 6, y - 12), f"{pv:.2f} {nm}", font=f20, fill=cc)
    for g_, i, pts in curves:
        col = COL_V2.get(g_["首日"] if g_ is it else g_["名"], WHT)
        dr.line(pts, fill=col, width=3)
        if len(groups) == 1:
            prev_c = 0 if i == 0 else g_["代表样本"]["path"][i - 1]["c"]
            yc = py(p0 * (1 + prev_c / 100))
            xa = x0 + i * day_w
            dr.line([xa, yc, xa + day_w, yc], fill=YEL, width=1)   # 前一日收盘
    if len(groups) > 1:
        for k, g_ in enumerate(groups):
            dr.text((x0 + 8, y_hi + 6 + k * 28), f"— {g_['名']} {g_['概率']}%", font=f20, fill=COL_V2.get(g_["名"], WHT))
    extra = [("分时: " + " / ".join(f"{('' if len(groups) == 1 else nm + ' ')}第{i + 1}天{'真实 1 分钟线' if r else '无分钟线, 按开高低收示意'}" for nm, i, r in used), GRY),
             (f"续画区价格轴 = 原图价格轴(0% = {g['base']}" + (f"(库; OCR 读的 {g['ocr_base']})" if g.get("ocr_base") and abs(g["ocr_base"] - g["base"]) > 1e-6 else "") + f", 上沿 +{g['pmax']}%; {g.get('校准', '')}), 越出原图上下沿的部分把框往外延", GRY)]
    _panel(cv, px, v2_panel_lines(v2, it, p0, days, pa, pa_md, extra), H)
    cv.save(outp)


def draw_v2(shot, kind, code, v2, out_dir, end, C=None, g=None, with_extreme=True, days=None, pa=None, pa_md=None):
    """一张截图 × v2 的每个情景 → 一张图(文件名 {code}_{图stem}_v2_{1|2|3}{T+1走法}-{T+2走法}.png / _v2_X极端.png);
    kind = "daily"(日 K)/ "intra"(分时 / 五日, 要给 g, C 可选); 返回 (输出路径列表, C)
    kline_inbox.predict 接法: 先对日 K 调(拿 C), 再对分时 / 五日调(g 由 OCR axis 换算)"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    days = days or next_days(end, 2)
    outs = []
    for it in v2_items(v2, with_extreme):
        op = out_dir / f"{code}_{Path(shot).stem}_v2_{it['标签']}{it['名'].replace('→', '-')}.png"
        if kind == "daily":
            C = daily_v2(shot, code, v2, it, op, end, days, pa, pa_md)
        else:
            intraday_v2(shot, code, v2, it, op, C or {"close": v2["收盘"]}, g, days, end, pa, pa_md)
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
