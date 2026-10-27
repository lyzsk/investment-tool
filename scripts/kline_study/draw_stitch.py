# -*- coding: utf-8 -*-
"""draw_stitch.py — 衔接式续画(10/26 晚用户要: 续画的 K 线 / 分时要和截图里的接在一起, 像同一张图的延续)

做法(路线 A = 直接在原截图上续画, 为什么不选 B 见 docs/research/pa_agent_kline_drawing_notes.md 第四节):
  ①找图框: 主图右边框(竖灰线)/ 网格横线(等距)/ 分时的竞价阴影区(09:30、15:00 的 x)/ 五日的日分隔线(一天多宽)
  ②价格轴(日 K, 三条路线, 都用库里近 20 根真实 K 线的实体上下沿像素误差打分, 优先级 价格线 > 刻度 > K 线拟合):
     价格线 = 东方财富主图里的红色涨停价 / 绿色跌停价 / 米色最新价横虚线(价格由库算出, 最准; 10/26 实测三条互相印证残差 ≤0.3px)
     刻度   = 左侧刻度标签(两遍 OCR: 原色 ×2 + 只留灰字反白 ×3; 小数点被吃的补成候选)× 等距网格线 → RANSAC(实测刻度并不精确落在网格线上, 603280 图顶差 4px, 所以排第二)
     K 线   = 库里近 25 根 K 线实体拟合(上面两条都不行时的后备)
     截止日那根的 x: 东方财富最右一根中心在右边框左边约 20px(实测 17 张全是 1240.6~1241.2 / 右框 1261), 小空心红 K 没认出来时按这个补根数
     分时 / 五日 = 原图价格轴(ocr_shot axis + draw_future.snap_axis 吸附到框线 / 0% 虚线); 盘中截图(状态栏时刻 < 15:00)→ 线尾之后到 15:00 用库里 1 分钟线补灰线
  接口误差(写进右侧总表"衔接校准"): 日 K = 截止日那根 K 线收盘那条颜色边界 vs 收盘价换算的 y; 分时 / 五日 = 白色价格线尾端 vs 今收(盘中 = 线尾那分钟的库价)
  ③K 线间距 dx / 实体宽 bw / 红绿颜色: 从截图里认出来的 K 线实体量(不用固定值)
  ④把截图在"图框右边框"处竖着剖开, 插入预测区(只剖图表那几行; 剖开处的背景 / 网格线 / 虚线按行续上), 右边框 / 五档盘口整体右移
  ⑤预测 K 线: 同间距、同实体宽、同红(空心阳)/ 青(实心阴), 预测用"虚线框 + 半透明"(学 PA_Agent 的未收盘 K 线画法); 均线 MA5/10/20 按预测收盘推算后用同色虚线接上
     预测分时: 同一价格轴、同一天宽(分时 = 截图 09:30~15:00 的宽度; 五日 = 一天一格), 白线 = 价格, 黄虚线 = 均价(无量, 按价格累计均值示意)
  ⑥日 K 另出"近日放大": 截图最近 ~22 根原样放大 + 预测 K 线(同一变换), 放在右侧总表上面(用户原话: 把近日 K 单独挑出来再补上你的 K 线)
  右侧总表 = draw_future.v2_panel_lines(票型 · 单日 top3 · 两日 top3 · 极端概率 · 置信 · pa_reason · 不自信点), 末尾加"衔接校准"实测误差

接口: draw_v2_stitch(...) 与 draw_future.draw_v2 同参数、同输出文件名({code}_{图stem}_v2_{1|2|3|X}{名}.png), kline_inbox 用开关 KLINE_STITCH=1 / --stitch 切换(默认关)
自测: python draw_stitch.py --trial   → results/kline/_draw_trial/(10/26 三只票 9 张图)
"""
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import draw_future as DF   # noqa: E402

FONT = DF.FONT
YEL, GRY, WHT = DF.YEL, DF.GRY, DF.WHT
TINT = (90, 130, 255, 22)          # 预测区底色(很淡的蓝, 只为分清哪段是预测)
DIV = (130, 140, 170)              # 今 / 预测 分界虚线
PRICE_W = (235, 235, 235)          # 分时价格线(东方财富白)
AVG_Y = (240, 200, 40)             # 分时均价线(黄)
_CACHE = {}


def _f(sz):
    return ImageFont.truetype(FONT, max(10, int(sz)))


def _arr(img):
    return np.asarray(img.convert("RGB")).astype(np.int16)


# ================================================================ 图框 / 网格

def gray_mask(a):
    g = a.mean(-1)
    sat = a.max(-1) - a.min(-1)
    return (g > 22) & (g < 95) & (sat < 16)


def right_border(a, y0, y1, xmin=None):
    """图表区 [y0, y1) 行里最靠右的一条灰竖线(图框右边线)"""
    H, W, _ = a.shape
    frac = gray_mask(a[y0:y1]).mean(0)
    xs = [x for x in range(int(xmin if xmin is not None else W * 0.45), W) if frac[x] > 0.7]
    if not xs:
        return None
    x = max(xs)
    while x - 1 in xs:   # 2~3 像素粗的线取最左一列(剖开处从线本身开始, 线跟着右移)
        x -= 1
    return x


def vlines(a, y0, y1, x0, x1):
    frac = gray_mask(a[y0:y1, x0:x1]).mean(0)
    xs = [x0 + i for i in range(len(frac)) if frac[i] > 0.7]
    return _cluster(xs)


def hlines(a, x0, x1, y0, y1, th=0.6):
    frac = gray_mask(a[y0:y1, x0:x1]).mean(1)
    ys = [y0 + i for i in range(len(frac)) if frac[i] > th]
    return _cluster(ys)


def _cluster(v, gap=2):
    out, cur = [], []
    for x in v:
        if cur and x - cur[-1] > gap:
            out.append(float(np.mean(cur)))
            cur = []
        cur.append(x)
    if cur:
        out.append(float(np.mean(cur)))
    return out


def bg_color(a, y0, y1, x0, x1):
    return np.median(a[y0:y1, x0:x1].reshape(-1, 3), 0)


def row_empty(a, y, x0, bg, tol=14):
    return bool((np.abs(a[y, x0:] - bg).max(-1) <= tol).all())


def band_rows(a, split, y_top_need, y_bot_need, bg, ymin=0, ymax=None):
    """要整体右移的行段: 从需要的上沿往上找到 [split−2, W) 整行是背景的一行(不把任何字 / 按钮横着剖开), 下沿同理往下"""
    H = a.shape[0]
    ymax = ymax or H - 1
    y0 = int(max(ymin, y_top_need))
    while y0 > ymin and not row_empty(a, y0, split - 2, bg):
        y0 -= 1
    y1 = int(min(ymax, y_bot_need))
    while y1 < ymax and not row_empty(a, y1, split - 2, bg):
        y1 += 1
    return y0, y1


def _row_fill(seg, ext, bg, phase_x):
    """一行剖开处的续接像素: 整行实线(网格 / 框线 / 日期条)→ 同色实线; 细虚线(0% 线 / 涨跌停价线)→ 同色同节奏虚线; 其他 → 背景"""
    d = np.abs(seg - bg).max(-1) > 18
    f = d.mean()
    if f > 0.85:   # 整行同色(网格 / 框线 / 日期条)才续; 量柱底那一行红青混杂 → 背景
        if seg[d].std(0).max() < 22:
            return np.tile(np.median(seg[d], 0), (ext, 1)), "solid"
        return np.tile(bg, (ext, 1)), "bg"
    if f > 0.3:
        on = seg[d]
        if on.std(0).max() < 28:
            runs, cur, val = [], 0, d[0]
            for v in d:
                if v == val:
                    cur += 1
                else:
                    runs.append((val, cur))
                    val, cur = v, 1
            runs.append((val, cur))
            ons = [n for v, n in runs[1:-1] if v]
            offs = [n for v, n in runs[1:-1] if not v]
            if len(ons) >= 6 and np.std(ons) < 3 and offs:
                p_on, p_off = int(round(np.median(ons))), int(round(np.median(offs)))
                col = np.median(on, 0)
                out = np.tile(bg, (ext, 1)).astype(float)
                per = p_on + p_off
                for i in range(ext):
                    if (i + phase_x) % per < p_on:
                        out[i] = col
                return out, "dash"
    return np.tile(bg, (ext, 1)), "bg"


def stitch_canvas(img, split, ext, y0, y1, xl, bg):
    """把截图在 split 处竖着剖开插入 ext 像素宽的续接区(只剖 [y0, y1) 行; 别的行原样, 右侧延伸用最右一列补)"""
    a = _arr(img)
    H, W, _ = a.shape
    out = np.empty((H, W + ext, 3), np.int16)
    out[:, :W] = a
    out[:, W:] = a[:, W - 1:W]
    out[y0:y1, split + ext:W + ext] = a[y0:y1, split:W]
    thin = gray_mask(a[:, xl:split]).mean(1)
    for y in range(y0, y1):
        seg = a[y, xl:split]
        fill, kind = _row_fill(seg, ext, bg, split - xl)
        if kind == "dash" or kind == "solid":   # 只续细线(上下 5 行没有同样的线); 量柱 / 指标线成片的行不当线续
            dd = np.abs(seg - bg).max(-1) > 18
            fu = (np.abs(a[max(0, y - 5), xl:split] - bg).max(-1) > 18).mean() if y >= 5 else 0
            fd = (np.abs(a[min(H - 1, y + 5), xl:split] - bg).max(-1) > 18).mean() if y + 5 < H else 0
            if kind == "dash" and max(fu, fd) > 0.6 * dd.mean():
                fill = np.tile(bg, (ext, 1))
        out[y, split:split + ext] = fill
    del thin
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


# ================================================================ 日 K: K 线实体 / 价格轴

def kbars(a, y0, y1, x0, x1):
    """认 K 线实体(含 DK 点涂的黄 / 紫): 每种颜色 → 空心红先填洞 → 开运算去掉均线(细线) → 连通块; 返回 [(xc, 宽, 实体顶, 实体底, 颜色, 影线顶, 影线底)]"""
    from scipy import ndimage as nd
    s = a[y0:y1, x0:x1]
    r, g, b = s[..., 0], s[..., 1], s[..., 2]
    masks = {"red": (r > 110) & (g < 58) & (b < 72) & (r - g > 70),   # 空心红 K 的细边框 JPEG 压缩后红色只剩 120~170; g<58 排除 MA300 暗红线(g≈68)
             "cyan": (g > 140) & (b > 140) & (r < 130),
             "orange": (r > 200) & (g > 120) & (g < 210) & (b < 70),
             "purple": (r > 90) & (b > 180) & (g < 110)}
    raw = []

    def comps(cn, mf, m, side_m=None):
        side_m = m if side_m is None else side_m
        op = nd.binary_opening(mf, structure=np.ones((4, 4)))
        lab, n = nd.label(op)
        for i, sl in enumerate(nd.find_objects(lab)):
            ys, xs = sl
            w = xs.stop - xs.start
            if w < 4 or w > 40:
                continue
            if (lab[sl] == i + 1).mean() < 0.86:   # 不是矩形(翻页圆点 / 按钮)
                continue
            side = [side_m[ys, x].mean() for x in (xs.start - 3, xs.stop + 2) if 0 <= x < m.shape[1]]
            if side and min(side) > 0.5:   # 左右紧挨着还是同色 = 横线(均线 / 价格线)碎段, 不是 K 线
                continue
            raw.append((cn, m, ys, xs))
    for cn in ("cyan", "orange", "purple"):
        m = masks[cn] & ~(masks[cn].mean(1) > 0.4)[:, None]
        comps(cn, m, m)
    ws = [z[3].stop - z[3].start for z in raw if z[0] == "cyan"]
    bw0 = float(np.median(ws)) if ws else 12.0
    # 空心红 K: JPEG 后上下横边常断, 填洞不可靠 → 竖边配对: 同一行里两段竖边相距 ≈ 实体宽(青 K 量的)就把中间填满
    m = masks["red"] & ~(masks["red"].mean(1) > 0.4)[:, None]
    vert = nd.binary_opening(m, structure=np.ones((5, 1)))
    fill = m.copy()
    for y in np.where(vert.any(1))[0]:
        xs_ = np.where(vert[y])[0]
        runs = []
        for x in xs_:
            if runs and x - runs[-1][1] <= 1:
                runs[-1][1] = x
            else:
                runs.append([x, x])
        for (a0, a1), (b0, b1) in zip(runs, runs[1:]):
            if bw0 - 7 <= b0 - a1 - 1 <= bw0 + 1 and (a1 - a0) <= 4 and (b1 - b0) <= 4:
                fill[y, a0:b1 + 1] = True
    fill = nd.binary_fill_holes(nd.binary_closing(fill, structure=np.ones((3, 1))))
    comps("red", fill, m, (r > 100) & (r - g > 40) & (r - b > 50))   # 两侧判横线用宽松红(含 MA300 线芯 g≈80)
    raw.sort(key=lambda z: (z[3].start + z[3].stop) / 2)
    merged = []   # 均线横穿实体会切成上下两段 → 同一 x 的合并
    for cn, m, ys, xs in raw:
        xc = (xs.start + xs.stop - 1) / 2
        hit = next((q for q in merged if q[0] == cn and abs(q[1] - xc) <= 2.5 and ys.start - q[3] <= 16), None)   # 只合并被均线切开的(几条均线挤在一起时断口可到 10 多像素)
        if hit:
            hit[2], hit[3] = min(hit[2], ys.start), max(hit[3], ys.stop)
            hit[4], hit[5] = min(hit[4], xs.start), max(hit[5], xs.stop)
        else:
            merged.append([cn, xc, ys.start, ys.stop, xs.start, xs.stop, m])
    out = []
    for cn, _, y_a, y_b, x_a, x_b, m in merged:
        ys, xs = slice(y_a, y_b), slice(x_a, x_b)
        w = x_b - x_a
        xc = (xs.start + xs.stop - 1) / 2
        col = m[:, int(round(xc))]
        top, bot = ys.start, ys.stop - 1
        wt, wb = top, bot   # 影线: 实体中心列上下连续的同色像素(容 2 像素断点)
        gap = 0
        for y in range(top - 1, -1, -1):
            if col[y]:
                wt, gap = y, 0
            else:
                gap += 1
                if gap > 2:
                    break
        gap = 0
        for y in range(bot + 1, len(col)):
            if col[y]:
                wb, gap = y, 0
            else:
                gap += 1
                if gap > 2:
                    break
        out.append((x0 + xc, w, y0 + top, y0 + bot, cn, y0 + wt, y0 + wb))
    out.sort()
    if out:   # 宽度离群(残留线段 / 涨跌停价虚线碎段)剔掉; 基准 = 青 K 实体宽(最稳)
        mw = bw0 if ws else np.median([q[1] for q in out])
        out = [q for q in out if 0.7 * mw <= q[1] <= 1.5 * mw]
    return out


def xgrid(B):
    """K 线中心 → 间距 dx / 最右一根 xr: 以最右一根为锚, 细扫 dx 让最多的中心落在整数格上, 再最小二乘(允许缺根 / 误认)"""
    xs = np.array([q[0] for q in B])
    xr0 = xs.max()
    d = np.diff(xs)
    d = d[d > 3]
    rough = float(np.median(d[d <= np.percentile(d, 30) * 1.5]))
    best = None
    for dx in np.arange(rough * 0.8, rough * 1.25, 0.01):
        r = (xr0 - xs) / dx
        hit = np.abs(r - np.round(r)) < 0.15
        sc = hit.sum() - 0.5 * np.abs(r - np.round(r))[hit].sum()
        if best is None or sc > best[0]:
            best = (sc, dx)
    base, xr = best[1], xr0
    for _ in range(3):
        k = np.round((xr - xs) / base)
        res = xs - (xr - k * base)
        ok = np.abs(res) < 0.2 * base
        A = np.vstack([np.ones(ok.sum()), -k[ok]]).T
        (xr, base), *_ = np.linalg.lstsq(A, xs[ok], rcond=None)
    return float(base), float(xr), np.round((xr - xs) / base).astype(int)


def db_daily(code, end, n=160):
    import db_ro
    sym = ("sh" if code.startswith(("6", "9", "11", "5")) else "bj" if code.startswith(("4", "8")) else "sz") + code
    df = db_ro.query("select trade_date, open, high, low, close from kline_day where symbol=%s and is_deleted=0 and trade_date<=%s "
                     "order by trade_date desc limit %s", (sym, end, n))
    df = df.iloc[::-1].reset_index(drop=True)
    return [str(x) for x in df.trade_date], *(df[c].astype(float).to_numpy() for c in ("open", "high", "low", "close"))


def _num_cands(t):
    """OCR 文本 → 候选价: 带小数点的直接用; 纯数字串(小数点被吃掉: 10384 / 2902)补成 2 位 / 3 位小数两种"""
    t = t.replace(" ", "")
    m = re.findall(r"\d{1,5}\.\d{1,3}", t)
    if m:
        return [float(m[-1])]
    m = re.findall(r"\d{3,6}", t)
    if m:
        d = m[-1]
        return [float(d[:-2] + "." + d[-2:]), float(d[:-3] + "." + d[-3:])] if len(d) >= 4 else [float(d[:-2] + "." + d[-2:])]
    return []


def lim_pct(code, name=""):
    if "ST" in (name or "").upper():
        return 0.05
    if code.startswith(("300", "301", "688", "689", "11", "12")):   # 创业板 / 科创板 / 转债 20%
        return 0.20
    return 0.30 if code.startswith(("4", "8", "92")) else 0.10


def price_lines(a, x0, x1, y0, y1):
    """主图里东方财富画的三条横虚线(价格精确已知, 是最准的价格轴锚点): 红 = 涨停价 / 绿 = 跌停价 / 米色 = 最新价;
    认法: 该颜色在整行占 ≥25% 且是一段一段的虚线(≥12 段, 段长整齐 → 排除均线); 返回 {类: y 中心}"""
    blk = a[y0:y1, x0:x1]
    r, g, b = blk[..., 0], blk[..., 1], blk[..., 2]
    ms = {"涨停": (r > 120) & (g < 60) & (b < 60), "跌停": (g > 80) & (r < 70) & (b < 70),
          "最新": (r > 150) & (g > 125) & (b > 95) & (r - b > 20) & (r - b < 90)}
    out = {}
    for k, m in ms.items():
        rows = []
        for i in range(m.shape[0]):
            f = m[i].mean()
            if f < 0.25:
                continue
            on = np.diff(np.concatenate([[0], m[i].astype(int), [0]]))
            st_, en_ = np.where(on == 1)[0], np.where(on == -1)[0]
            L = en_ - st_
            if len(L) >= 12 and np.std(L[1:-1]) < 3.5:
                rows.append((y0 + i, f))
        if rows:
            cl = [[rows[0]]]
            for y, f in rows[1:]:
                (cl[-1].append((y, f)) if y - cl[-1][-1][0] <= 2 else cl.append([(y, f)]))
            best = max(cl, key=lambda z: sum(f for _, f in z))
            out[k] = float(sum(y * f for y, f in best) / sum(f for _, f in best))
    return out


def ocr_labels(img, x0, x1, y0, y1):
    """左侧刻度标签, 两遍 OCR 合并: ①原色放大 2 倍 ②只留灰色字(彩色 K 线 / 均线 / 涨跌停价抹掉)反成白底黑字放大 3 倍
    (整图 OCR 常把 121.64 读成 14.64; 刻度字是深灰, 对比度低); 返回 [(y 原图, [候选价], 原文)]"""
    import ocr_shot as OS
    crop = img.crop((x0, y0, x1, y1))
    out = []
    big = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
    for box, t, s_ in (OS.ocr()(np.array(big))[0] or []):
        out.append(((box[0][1] + box[2][1]) / 4 + y0, str(t)))
    a = np.asarray(crop).astype(int)
    txt = ((a.max(2) - a.min(2)) < 40) & (a.mean(2) > 85)
    bw_ = Image.fromarray(np.where(txt, 0, 255).astype(np.uint8)).resize((crop.width * 3, crop.height * 3), Image.LANCZOS).convert("RGB")
    pad = Image.new("RGB", (bw_.width + 80, bw_.height + 80), (255, 255, 255))
    pad.paste(bw_, (40, 40))
    for box, t, s_ in (OS.ocr()(np.array(pad))[0] or []):
        out.append((((box[0][1] + box[2][1]) / 2 - 40) / 3 + y0, str(t)))
    res = []
    for y, t in out:
        if "停" in t or "价" in t:
            continue
        c = _num_cands(t)
        if c:
            res.append((float(y), c, t))
    return res


def label_fit(labels, lines):
    """标签 → 最近的网格线(≤45 像素); RANSAC: 任取两条不同网格线上的候选价定直线, 每条网格线最多算一个内点(取残差最小的候选);
    内点 ≥ 2 → 最小二乘 y = a + b·价; 返回 (a, b, 内点数, 说明) 或 None"""
    pairs = []
    for y, cands, t in labels:
        j = int(np.argmin([abs(y - L) for L in lines]))
        if abs(y - lines[j]) <= 45:
            pairs += [(j, lines[j], v) for v in cands]
    best = None
    for i in range(len(pairs)):
        for k in range(i + 1, len(pairs)):
            (ja, ya, va), (jb, yb, vb) = pairs[i], pairs[k]
            if ja == jb or va == vb:
                continue
            b = (ya - yb) / (va - vb)
            if b >= 0:
                continue
            a = ya - b * va
            per = {}
            for j, y, v in pairs:
                r = abs((y - a) / b - v)
                if r <= 0.004 * abs(v) + 0.011 and (j not in per or r < per[j][0]):
                    per[j] = (r, y, v)
            if best is None or len(per) > len(best[2]) or (len(per) == len(best[2]) and sum(q[0] for q in per.values()) < sum(q[0] for q in best[2].values())):
                best = (a, b, per)
    if not best or len(best[2]) < 2:
        return None
    P = np.array([q[2] for q in best[2].values()])
    Y = np.array([q[1] for q in best[2].values()])
    b, a = np.polyfit(P, Y, 1)
    return a, b, len(best[2]), "、".join(f"{v:g}" for v in sorted(P, reverse=True))


def legend_ma(img, T, y_lo, y_hi):
    """均线图例(MA5:29.38 / 10:28.15 / 20:27.76 …)→ {周期: (值, 颜色)}; 颜色 = 图例文字像素的中位色"""
    a = _arr(img)
    out = {}
    for x, y, t in T:
        if not (y_lo <= y <= y_hi):
            continue
        m = re.match(r"^(?:MA)?(\d{1,3})[:：](\d+\.\d+)", t.replace(" ", ""))
        if not m:
            continue
        n = int(m.group(1))
        blk = a[int(y) - 12:int(y) + 12, int(x):int(x) + 150].reshape(-1, 3)
        br = blk[blk.max(1) > 110]
        if len(br):
            out[n] = (float(m.group(2)), tuple(int(v) for v in np.median(br, 0)))
    return out


def close_edge(a, x, bw, y_pred, up, win=30):
    """接口误差: 截止日那根 K 线所在的几列里, 找离"收盘价换算的 y"最近的一条颜色边界行(空心红 K 的上边 / 青 K 实体的下边 / DK 涂色 K 的边);
    不靠实体识别(空心红 K 常被均线截掉半截), 返回像素误差或 None"""
    x0, x1 = int(round(x - bw / 2 + 1)), int(round(x + bw / 2 - 1))
    y0, y1 = int(y_pred - win), int(y_pred + win)
    blk = a[max(0, y0):y1, max(0, x0):x1 + 1]
    if blk.size == 0 or blk.shape[1] < 3:
        return None
    r, g, b = blk[..., 0], blk[..., 1], blk[..., 2]
    ms = [(r > 110) & (g < 75) & (r - g > 60), (g > 140) & (b > 140) & (r < 130), (r > 200) & (g > 120) & (g < 210) & (b < 70)]
    best = None
    for m in ms:
        f = m.mean(1) >= 0.5
        for i in range(len(f)):
            if f[i] and ((i == 0 or not f[i - 1]) or (i == len(f) - 1 or not f[i + 1])):
                yy = max(0, y0) + i + (0.5 if (i == len(f) - 1 or not f[i + 1]) else -0.5)   # 边界在像素之间
                d_ = abs(yy - y_pred)
                if best is None or d_ < best:
                    best = d_
    return float(best) if best is not None else None


def daily_geom(img, code, end, ocr=None):
    """日 K 截图 → 图框 / 价格轴 / K 线间距 / 颜色 / 均线 + 实测对齐误差"""
    a = _arr(img)
    H, W, _ = a.shape
    T = (ocr or {}).get("texts") or []
    y_leg = max([y for x, y, t in T if re.match(r"^(MA)?\d{1,3}[:：]\d", t.replace(" ", "")) and H * 0.25 < y < H * 0.5] or [H * 0.38])
    y_vol = min([y for x, y, t in T if t.startswith(("成交额", "成交量", "VOL")) and y > y_leg] or [H * 0.58])
    xb = right_border(a, int(y_leg + 20), int(y_vol - 20))
    if xb is None:
        raise ValueError("找不到日 K 主图右边框")
    hl = hlines(a, int(W * 0.05), xb - 5, int(y_leg + 15), int(y_vol - 15))
    if len(hl) < 2:
        raise ValueError(f"主图网格线不够({len(hl)} 条)")
    top, bot = hl[0], hl[-1]
    if len(hl) >= 3:   # 网格线等距: 被均线 / 按钮挡住没认出来的补上
        step = min(np.diff(hl))
        nint = int(round((bot - top) / step))
        if nint >= 2 and all(min(abs(y - (top + i * (bot - top) / nint)) for i in range(nint + 1)) <= 3 for y in hl):
            hl = [top + i * (bot - top) / nint for i in range(nint + 1)]
    xl = next((x for x in vlines(a, int(top + 5), int(bot - 5), 0, int(W * 0.1))), 18)
    bg = bg_color(a, int(top + 3), int(bot - 3), int(xl + 5), int(xb - 5))
    B = kbars(a, int(top - 2), int(bot + 2), int(xl + 2), int(xb - 1))
    if len(B) < 12:
        raise ValueError(f"认出的 K 线实体太少({len(B)})")
    dx, xr, K = xgrid(B)
    d, o, h, l_, c = db_daily(code, end)
    # 价格轴 ⓪价格线(涨停 / 跌停 / 最新价 横虚线, 价格由库算出 → 最准)
    fits = []
    pl = price_lines(a, int(xl + 5), int(xb - 5), int(top - 6), int(bot + 6))
    lim = lim_pct(code, (ocr or {}).get("name") or "")
    pv = {"涨停": round(c[-2] * (1 + lim) + 1e-9, 2), "跌停": round(c[-2] * (1 - lim) + 1e-9, 2), "最新": float(c[-1])} if len(c) >= 2 and d[-1] == end else {}
    anc = [(k, y, pv[k]) for k, y in pl.items() if k in pv]
    if len(anc) >= 2:
        P_, Y_ = np.array([q[2] for q in anc]), np.array([q[1] for q in anc])
        b_, a_ = np.polyfit(P_, Y_, 1)
        res_ = np.abs(Y_ - (a_ + b_ * P_))
        if b_ < 0 and res_.max() <= 2.5:   # 三条线互相印证(两条时必然过点, 靠后面 K 线评分把关)
            fits.append(("价格线", a_, b_, "截图价格线 " + " / ".join(f"{k}价 {v:g}@y{y:.1f}" for k, y, v in anc) + (f"(残差 ≤{res_.max():.1f}px)" if len(anc) > 2 else "")))
    # ①刻度标签 × 网格线
    labs = ocr_labels(img, 0, int(W * 0.2), int(top - 10), int(bot + 10))
    lf = label_fit(labs, hl)
    if lf and lf[2] >= 3:   # 只有 2 个标签对上时不可信(001359: 121.64 读成 154.64 也能和 86.0 连成一条线)
        fits.append(("刻度", lf[0], lf[1], f"截图左侧刻度 {lf[3]}(OCR {len(labs)} 个, 内点 {lf[2]})+ 网格线"))
    # ②库里 K 线拟合(后备 / 对照): 实体上下沿像素 vs 开收价
    real = [(q, k) for q, k in zip(B, K) if k < len(c)]
    bw0 = float(np.median([q[1] for q in B]))
    RECENT = 20   # 评分 / 拟合只用最近 20 根(预测接在这里; 窗口里有除权时库里不复权价和截图前复权价对不上, 远处的 K 线会把比例带歪)

    def fit_bars(e):
        P, Y = [], []
        for q, k in real:
            i = len(c) - 1 - k - e
            if i < 0 or k > RECENT + 5:
                continue
            P += [max(o[i], c[i]), min(o[i], c[i])]
            Y += [q[2], q[3]]
        P, Y = np.array(P), np.array(Y)
        b, a0 = np.polyfit(P, Y, 1)
        res = np.abs(Y - (a0 + b * P))
        keep = res <= max(np.percentile(res, 80), 2)
        b, a0 = np.polyfit(P[keep], Y[keep], 1)
        return a0, b

    def score(a0, b, e):
        """对库里 K 线: 实体上下沿 / 影线顶底 的像素误差 + 颜色对不上的比例"""
        eb, ew, mis = [], [], []
        for q, k in real:
            i = len(c) - 1 - k - e
            if i < 0 or k > RECENT:
                continue
            eb += [q[2] - (a0 + b * max(o[i], c[i])), q[3] - (a0 + b * min(o[i], c[i]))]
            ew += [q[5] - (a0 + b * h[i]), q[6] - (a0 + b * l_[i])]
            if q[4] in ("red", "cyan"):
                mis.append((q[4] == "red") != (c[i] >= o[i]))
        eb, ew = np.abs(eb), np.abs(ew)
        tc = close_edge(a, xr + e * dx, bw0, a0 + b * c[-1], c[-1] >= o[-1])
        return {"今收px": tc, "实体px中位": float(np.median(eb)), "实体px_P90": float(np.percentile(eb, 90)), "影线px中位": float(np.median(ew)),
                "影线px_P90": float(np.percentile(ew, 90)), "颜色错": float(np.mean(mis)) if mis else 1.0, "n": int(len(eb) // 2)}
    cands = []
    for e in range(0, 5):   # 最右几根是小空心红 K 没认出来时 = 截图最右一根在认出的最右一根右边 e 根(先验: 东方财富最右一根中心在右边框左边约 20px)
        for nm, a0, b, why in fits:
            cands.append((e, nm, a0, b, why, score(a0, b, e)))
        try:
            a0, b = fit_bars(e)
            if b < 0:
                cands.append((e, "K线", a0, b, "库里近 K 线实体拟合(刻度没认出来时的后备)", score(a0, b, e)))
        except (ValueError, np.linalg.LinAlgError, TypeError):
            pass
    # 优先级 价格线 > 刻度 > K 线拟合: 对近 20 根的实体误差比后面的大不过 0.75 / 1.5 像素就用前面的
    # (10/26 实测: 东方财富左侧刻度并不精确落在网格线上, 603280 按刻度在图顶差 4px; 价格线三条互相印证到 ≤1px)
    edge = xb - 20.3
    cands.sort(key=lambda z: z[5]["实体px中位"] + 20 * z[5]["颜色错"] + {"价格线": 0, "刻度": 0.75}.get(z[1], 1.5)
               + (4.0 if abs(xr + z[0] * dx - edge) > dx / 2 else 0))
    e, nm, a0, b, why, sc = cands[0]
    xr = xr + e * dx
    K = K + e
    bw = float(np.median([q[1] for q in B if q[4] in ("red", "cyan")] or [q[1] for q in B]))
    cols = {}
    for cn in ("red", "cyan"):
        px = []
        for q in B:
            if q[4] == cn and q[3] - q[2] >= 4:
                blk = a[int(q[2]):int(q[3]) + 1, int(q[0] - q[1] / 2):int(q[0] + q[1] / 2) + 1].reshape(-1, 3)
                px.append(blk[np.abs(blk - bg).max(1) > 60])
        if px:
            px = np.concatenate(px)
            if len(px):
                cols[cn] = tuple(int(v) for v in np.median(px, 0))
    ma = legend_ma(img, T, y_leg - 130, y_leg + 10)
    return {"W": W, "H": H, "xb": xb, "xl": xl, "top": top, "bot": bot, "hl": hl, "bg": bg, "dx": dx, "xr": xr, "bw": bw, "a": a0, "b": b,
            "py": (lambda p, a0=a0, b=b: a0 + b * p), "src": nm, "why": why, "score": sc, "e": e, "n_bars": len(B),
            "up": cols.get("red", (255, 60, 60)), "dn": cols.get("cyan", (0, 210, 210)), "ma": ma, "db": (d, o, h, l_, c),
            "y_vol": y_vol, "y_leg": y_leg, "texts": T, "labels": labs}


# ================================================================ 分时 / 五日: 时间轴

def intra_geom(img, kind, g, ocr=None):
    """分时 / 五日截图 → 图框右边 / 一天多宽 / 09:30、15:00 的 x / 小时网格线 + 价格轴(snap_axis 吸附后的 g)"""
    a = _arr(img)
    H, W, _ = a.shape
    g = DF.snap_axis(img, g)
    top, bot = int(g["top"]), int(g["bot"])
    xb = right_border(a, top + 5, bot - 5, xmin=W * 0.3)
    if xb is None:
        raise ValueError("找不到分时图右边框")
    vs = vlines(a, top + 5, bot - 5, 0, xb + 3)
    xl = vs[0] if vs else 18
    bg = bg_color(a, top + 5, bot - 5, int(xl + 5), int(xb - 5))
    out = {"g": g, "xb": xb, "xl": xl, "bg": bg, "W": W, "H": H}   # noqa
    if kind == "五日":
        inner = [x for x in vs if xl + 20 < x < xb - 20]
        sep = [xl] + inner + [xb]
        dw = float(np.median(np.diff(sep))) if len(sep) >= 3 else (xb - xl) / 5
        out.update({"day_w": dw, "x_open": xb - dw, "x_close": xb, "gap": 0.0, "hour": []})
    else:   # 分时: 左 / 右两块淡蓝阴影 = 集合竞价 / 盘后, 中间才是 09:30~15:00
        med = np.median(a[top + 5:bot - 5], 0)
        blue = (med[:, 2] - med[:, 0] > 6) & (med.max(1) < 70)
        xs = [x for x in range(int(xl) + 2, int(xb) - 1) if blue[x]]
        lft = [x for x in xs if x < (xl + xb) / 2]
        rgt = [x for x in xs if x > (xl + xb) / 2]
        x_open = (max(lft) + 1) if lft else xl
        x_close = min(rgt) if rgt else xb
        out.update({"day_w": float(x_close - x_open), "x_open": float(x_open), "x_close": float(x_close), "gap": 24.0,
                    "hour": [x for x in vs if x_open + 20 < x < x_close - 20]})
    T = (ocr or {}).get("texts") or []
    out["texts"] = T
    ax = [y for x, y, t in T if (re.fullmatch(r"\d{1,2}/\d{1,2}", t) or re.fullmatch(r"\d{2}:\d{2}(/\d{2}:\d{2})?", t)) and y > bot and x < xb]   # x < 右边框: 盘口"分时成交"的 14:56 不算
    out["y_axis"] = min(ax) if ax else bot + 40
    gm = gray_mask(a[top + 5:bot - 5, int(xl + 3):int(xb - 3)])   # 网格线颜色 = 图框里灰线像素的中位色
    out["grid_col"] = tuple(int(v) for v in np.median(a[top + 5:bot - 5, int(xl + 3):int(xb - 3)][gm], 0)) if gm.any() else (40, 40, 40)
    return out


# ================================================================ 画法零件(全部带变换 tf: 原图坐标 → 画布坐标, s = 放大倍数)

def _dash_line(dr, p0, p1, fill, width=1, on=8, off=6):
    (x0, y0), (x1, y1) = p0, p1
    L = math.hypot(x1 - x0, y1 - y0)
    if L < 1:
        return
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    t = 0.0
    while t < L:
        e = min(t + on, L)
        dr.line([(x0 + ux * t, y0 + uy * t), (x0 + ux * e, y0 + uy * e)], fill=fill, width=width)
        t += on + off


def _dash_rect(dr, box, fill, width, on, off):
    x0, y0, x1, y1 = box
    for p, q in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        _dash_line(dr, p, q, fill, width, on, off)


def pred_candle(dr, x, half, P, py, tf, s, up_col, dn_col, ylim):
    """预测 K 线: 东方财富配色(阳 = 红空心 / 阴 = 青实心)+ PA_Agent 未收盘棒画法(虚线框 + 半透明填充); ylim = 可画的上下界(原图坐标)"""
    o, h, l_, c = P
    up = c >= o
    col = up_col if up else dn_col

    def Y(p):
        return min(max(py(p), ylim[0]), ylim[1])
    X0, _ = tf(x - half, 0)
    X1, _ = tf(x + half, 0)
    Xc, _ = tf(x, 0)
    yt, yb = tf(0, Y(max(o, c)))[1], tf(0, Y(min(o, c)))[1]
    yb = max(yb, yt + max(2, 2 * s))
    yh, yl = tf(0, Y(h))[1], tf(0, Y(l_))[1]
    lw = max(1, int(round(1.6 * s)))
    dr.line([(Xc, yh), (Xc, yt)], fill=col + (255,), width=lw)
    dr.line([(Xc, yb), (Xc, yl)], fill=col + (255,), width=lw)
    dr.rectangle([X0, yt, X1, yb], fill=col + ((50,) if up else (110,)))
    on = max(3, 4 * s)
    _dash_rect(dr, (X0, yt, X1, yb), col + (255,), max(1, int(round(1.5 * s))), on, on * 0.6)
    for lim, p in ((ylim[0], h), (ylim[1], l_)):   # 越出可画范围: 画箭头 + 价
        if (py(p) < ylim[0] and lim == ylim[0]) or (py(p) > ylim[1] and lim == ylim[1]):
            yy = tf(0, lim)[1]
            dr.polygon([(Xc - 6 * s, yy + (8 * s if lim == ylim[0] else -8 * s)), (Xc + 6 * s, yy + (8 * s if lim == ylim[0] else -8 * s)), (Xc, yy)], fill=col + (255,))
            dr.text((Xc + 8 * s, yy - 2 if lim == ylim[0] else yy - 14 * s), f"{p:.2f}", font=_f(13 * s), fill=col + (255,))


def ma_future(c_hist, closes, n):
    """均线 n 在 T, T+1, T+2 的值(预测收盘接在库里收盘后面)"""
    seq = list(c_hist) + list(closes)
    m = len(c_hist)
    return [float(np.mean(seq[m - 1 + k - n + 1:m + k])) for k in range(len(closes) + 1)]


# ================================================================ 日 K 衔接续画

def _daily_layout(G, it, days):
    groups = it["子"] if it["标签"] == "X" else [it]
    slots = []   # (组号, 第几天, 槽位 k: x = xr + k·dx)
    k = 1
    for gi, g_ in enumerate(groups):
        for i in range(min(2, len(g_["代表样本"]["path"]))):
            slots.append((gi, i, k))
            k += 1
        k += 1 if len(groups) > 1 else 0
    n_slots = max(s_[2] for s_ in slots)
    return groups, slots, n_slots


def draw_daily(shot, code, v2, it, outp, end, days, pa=None, pa_md=None, G=None):
    img = Image.open(shot).convert("RGB")
    G = G or daily_geom(img, code, end, _ocr(shot))
    W, H = G["W"], G["H"]
    p0 = v2["收盘"]
    py, dx, xr, bw = G["py"], G["dx"], G["xr"], G["bw"]
    groups, slots, n_slots = _daily_layout(G, it, days)
    label_room = 75 if len(groups) == 1 else 40
    x_end = xr + (n_slots + 0.5) * dx + label_room
    ext = int(math.ceil(max(0, x_end - G["xb"]) + 8))
    paths = [[[p0 * (1 + p[k_] / 100) for k_ in ("o", "h", "l", "c")] for p in g_["代表样本"]["path"][:2]] for g_ in groups]
    ys = [py(v) for P in paths for Q in P for v in Q[1:3]]
    a = _arr(img)
    lim = 20 if v2.get("20cm") else 10
    need_top = min([G["top"]] + [y - 12 for y in ys])
    y0, y1 = band_rows(a, G["xb"], need_top, G["y_vol"] + 10, G["bg"], ymin=int(G["y_leg"] + 30))
    y_date = max([y for x, y, t in G["texts"] if re.fullmatch(r"20\d{6}", t)] or [0])
    if y_date:   # 剖到日期轴那一行(副图 / 日期条跟着一起续上)
        y1 = band_rows(a, G["xb"], y0, y_date + 25, G["bg"])[1]
    E0 = stitch_canvas(img, G["xb"], ext, y0, y1, int(G["xl"] + 3), G["bg"])
    d, o, h, l_, c = G["db"]
    # 均线续接(图例认得出的 5 / 10 / 20 日; 库里收盘 + 预测收盘)
    mas = {n: col for n, (v, col) in G["ma"].items() if n in (5, 10, 20)}

    def draw_pred(dr, tf, s, ylim, zone, dates_at=None, glabels=False):
        """zone = 预测区底色的上下沿(原图坐标); ylim = K 线可画范围; 放大图里两者都外延到能放下整条路径"""
        X0 = tf(xr + dx / 2, 0)[0]
        X1 = tf(x_end - 10, 0)[0]
        zt, zb = tf(0, zone[0])[1], tf(0, zone[1])[1]
        dr.rectangle([X0, zt, X1, zb], fill=TINT)
        _dash_line(dr, (X0, zt), (X0, zb), DIV + (255,), max(1, int(s)), 6 * s, 5 * s)
        dr.text((X0 + 3 * s, zb - 20 * s), "预测", font=_f(14 * s), fill=YEL + (255,))
        yp0 = tf(0, py(p0))[1]
        _dash_line(dr, (tf(xr, 0)[0], yp0), (X1, yp0), YEL + (150,), max(1, int(s)), 4 * s, 4 * s)
        if len(groups) == 1:
            closes = [P[3] for P in paths[0]]
            for n, col in mas.items():
                mv = ma_future(c, closes, n)
                pts = [tf(xr + k_ * dx, min(max(py(v), ylim[0]), ylim[1])) for k_, v in enumerate(mv)]
                for p_, q_ in zip(pts, pts[1:]):
                    _dash_line(dr, p_, q_, col + (230,), max(1, int(round(1.6 * s))), 5 * s, 3 * s)
        for (gi, i, k_) in slots:
            P = paths[gi][i]
            x = xr + k_ * dx
            pred_candle(dr, x, bw / 2, P, py, tf, s, G["up"], G["dn"], ylim)
            Xc = tf(x, 0)[0]
            if dates_at is not None and (gi == 0 or len(groups) == 1):
                dr.text((Xc - 14 * s, dates_at + i * 13 * s), days[i], font=_f(11 * s), fill=YEL + (255,))
            if len(groups) == 1 and i == len(paths[0]) - 1 and ylim[0] <= py(P[3]) <= ylim[1]:
                dr.text((tf(x + bw / 2 + 3, 0)[0], tf(0, py(P[3]))[1] - 9 * s), f"{P[3]:.2f}", font=_f(15 * s), fill=YEL + (255,))
        if glabels and len(groups) > 1:
            for gi, g_ in enumerate(groups):
                k_ = next(s_[2] for s_ in slots if s_[0] == gi)
                top_p = max(P[1] for P in paths[gi])
                Xg, Yg = tf(xr + k_ * dx - bw / 2, min(max(py(top_p), ylim[0]), ylim[1]))
                dr.text((Xg, Yg - 30 * s), f"{g_['名']}\n{g_['概率']}%", font=_f(10 * s), fill=DF.COL_V2.get(g_["名"], WHT) + (255,), spacing=0)

    # ①整图(原尺寸): 越出主图上下沿的只画箭头 + 价
    full = E0.convert("RGBA")
    ov = Image.new("RGBA", full.size, (0, 0, 0, 0))
    ylim_n = (max(y0 + 4, G["top"] - 40), G["bot"] - 2)
    draw_pred(ImageDraw.Draw(ov), lambda x, y: (x, y), 1.0, ylim_n, (ylim_n[0], G["bot"]))
    drf = ImageDraw.Draw(ov)
    if y_date:   # 原图日期轴那一行: 一个合并标签(两根才 36 像素宽, 分开写会叠字)
        drf.text((xr + dx * 0.6, y_date - 14), f"{days[0]}~{days[1][-2:]}", font=_f(20), fill=YEL + (255,))
    full = Image.alpha_composite(full, ov).convert("RGB")
    # ②近日放大: 最近 nz 根 + 预测; 只裁主图框内, 路径越出上下沿就按同一比例在上 / 下补空间(网格线按原间距外延, 右侧标价)
    cw_target = DF.PANEL_W / 2.15
    nz = int(max(12, min(40, (cw_target - (x_end - xr)) / dx)))
    cx0 = max(G["xl"] + 2, xr - (nz - 0.5) * dx)
    cx1 = x_end
    cy0, cy1 = G["top"] - 2, G["bot"] + 4
    head = max(0.0, cy0 - (min(ys) - 34))
    foot = max(0.0, (max(ys) + 14) - cy1)
    sc = min(3.0, DF.PANEL_W / (cx1 - cx0))
    zoom = E0.crop((int(cx0), int(cy0), int(math.ceil(cx1)), int(math.ceil(cy1))))
    zoom = zoom.resize((int(zoom.width * sc), int(zoom.height * sc)), Image.LANCZOS)
    HD = 40 + int(head * sc)
    zh = HD + zoom.height + int(foot * sc) + 70
    Z = Image.new("RGBA", (zoom.width, zh), tuple(int(v) for v in G["bg"]) + (255,))
    Z.paste(zoom, (0, HD))
    zov = Image.new("RGBA", Z.size, (0, 0, 0, 0))
    zd = ImageDraw.Draw(zov)

    def tfz(x, y):
        return ((x - int(cx0)) * sc, (y - int(cy0)) * sc + HD)
    step = (G["hl"][1] - G["hl"][0]) if len(G["hl"]) > 1 else 120
    gcol = (48, 48, 52, 255)
    for yy in [G["top"] - k * step for k in range(1, 8)] + [G["bot"] + k * step for k in range(1, 8)]:   # 外延网格线 + 价
        if (yy < cy0 and yy >= cy0 - head) or (yy > cy1 and yy <= cy1 + foot):
            Y = tfz(0, yy)[1]
            _dash_line(zd, (0, Y), (zoom.width, Y), gcol, 1, 6, 6)
            zd.text((8, Y - 26), f"{(yy - G['a']) / G['b']:.2f}", font=_f(22), fill=(170, 170, 170, 255))
    if head:
        zd.text((8, HD - 30), "↑ 截图图框上沿(上面按同一比例补的空间)", font=_f(18), fill=(130, 130, 130, 255))
    zlim = (cy0 - head + 4, cy1 + foot - 4)
    draw_pred(zd, tfz, sc, zlim, (min(cy0, cy0 - head + 2), G["bot"] + foot), dates_at=HD + zoom.height + int(foot * sc) + 4, glabels=True)
    for kk in range(5, nz, 5):   # 真实 K 线的日期(库; 最右一根不写, 让给预测日期)
        i = len(d) - 1 - kk
        if i >= 0:
            X = tfz(xr - kk * dx, 0)[0]
            if X > 10:
                zd.text((X - 18 * sc, HD + zoom.height + int(foot * sc) + 4), d[i][5:].replace("-", "/"), font=_f(12 * sc), fill=(120, 120, 120, 255))
    zd.text((6, 6), f"近 {nz} 日 K(截图原样放大 ×{sc:.1f})+ 预测 2 日(虚线框); 均线虚线 = 用预测收盘推算的 MA5/10/20", font=_f(22), fill=YEL + (255,))
    Z = Image.alpha_composite(Z, zov).convert("RGB")
    # ③拼: 整图 | (近日放大 + 总表)
    sc_ = G["score"]
    extra = [("── 衔接校准(和截图对齐的实测) ──", DF.CYN),
             (f"价格轴: {G['why']}; 每像素 {abs(1 / G['b']):.4f} 元", GRY),
             ((f"接口(截止日收盘 {p0:.2f})像素误差 {sc_['今收px']:.1f}px(≈{sc_['今收px'] / abs(G['b']):.3f} 元)" if sc_.get("今收px") is not None else "截止日那根是 DK 涂色 / 没认出, 接口误差没量"), YEL),
             (f"对库里近 {sc_['n']} 根 K 线: 实体上下沿误差中位 {sc_['实体px中位']:.1f}px(≈{sc_['实体px中位'] / abs(G['b']):.3f} 元)/ P90 {sc_['实体px_P90']:.1f}px; "
              f"影线顶底中位 {sc_['影线px中位']:.1f}px / P90 {sc_['影线px_P90']:.1f}px; 阴阳色对不上 {sc_['颜色错']:.0%}", GRY),
             (f"K 线间距 {dx:.2f}px · 实体宽 {bw:.1f}px(预测 K 线同宽同间距)· 截图认出 {G['n_bars']} 根" + (f" · 最右一根实体太小没认出, 往右补 {G['e']} 根" if G["e"] else ""), GRY)]
    lines = DF.v2_panel_lines(v2, it, p0, days, pa, pa_md, extra)
    _compose(full, Z, lines, outp)
    return {"close": p0, "high": float(h[-1]), "low": float(l_[-1]), "name": v2.get("name"), "date": d[-1], "dx": dx, "err": sc_}


def _compose(full, Z, lines, outp):
    """左 = 衔接后的整图; 右 = (近日放大) + 总表(字号自动, 放不下就加高画布)"""
    W1, H = full.size
    zw, zh = (Z.size if Z is not None else (0, 0))
    pw = max(DF.PANEL_W + 20, zw + 20)
    y_txt = (zh + 30) if Z is not None else 30
    for fs in (25, 23, 21, 19):
        f = _f(fs)
        w = DF._wrap(lines, f, pw - 40)
        lh = int(fs * 1.4)
        if y_txt + len(w) * lh <= H - 20 or fs == 19:
            break
    Ht = max(H, y_txt + len(w) * lh + 20)
    cv = Image.new("RGB", (W1 + pw, Ht), (16, 16, 20))
    cv.paste(full, (0, 0))
    if Z is not None:
        cv.paste(Z, (W1 + 10, 10))
    dr = ImageDraw.Draw(cv)
    y = y_txt
    for t, c in w:
        dr.text((W1 + 20, y), t, font=f, fill=c)
        y += lh
    cv.save(outp)


# ================================================================ 分时 / 五日 衔接续画

def minute_today(code, day):
    """截止日 1 分钟线(行情库只读): [(分钟序号 0~240: 09:30=0 / 11:30=120 / 13:01=121 / 15:00=240, 收盘, 均价)]"""
    import db_ro
    sym = ("sh" if code.startswith(("6", "9", "11", "5")) else "bj" if code.startswith(("4", "8")) else "sz") + code
    df = db_ro.query("select bar_time, close, avg_price from kline_minute where symbol=%s and trade_date=%s and is_deleted=0 order by bar_time", (sym, day))
    out = []
    for t, c, av in zip(df.bar_time, df.close, df.avg_price):
        hm = t.hour * 60 + t.minute
        m = hm - 570 if hm <= 690 else hm - 780 + 120
        if 0 <= m <= 240 and c:
            out.append((m, float(c), float(av or c)))
    return out


def shot_clock(G, shot, end):
    """截图是不是盘中截的: 状态栏时刻(OCR, 最上面一行的 HH:MM)< 15:00 且收件日(目录名 yyyy.mm.dd)= 截止日"""
    H = G.get("H") or 2774
    t = next((m.group(1).zfill(2) + ":" + m.group(2) for x_, y_, t_ in G.get("texts") or [] if y_ < H * 0.035
              for m in [re.match(r"^(\d{1,2}):(\d{2})", t_)] if m and int(m.group(1)) < 24), None)   # 状态栏常带图标残字: "18:17 4"
    folder = Path(shot).parent.name.replace(".", "-")
    if not t:
        return None, None   # 认不出时刻 → 让调用方两种都试
    return t, bool(folder == end and "09:15" <= t < "15:00")


def intra_interface(G, img, py, p0, code, end, shot):
    """分时 / 五日的接口误差 = 截图白色价格线尾端 vs 价格换算的 y
    收盘后截图: 15:00 前最后 6 列的白线 vs 今收;
    盘中截图(状态栏时刻 < 15:00): 找白线尾端(去掉刻度文字框 / 0% 虚线, 连续 4 列) vs 那一分钟的库价, 并从库里取尾端之后到 15:00 的
    真实 1 分钟线(画成灰线补上, 预测从真实收盘接)"""
    gg = G["g"]
    a0 = _arr(img)
    ya, yb_ = int(gg["top"]) - 5, int(gg["bot"]) + 5
    xo, xc_ = int(G["x_open"]), int(G["x_close"])
    blk = a0[ya:yb_, xo:xc_ + 1]
    clock, intraday = shot_clock(G, shot, end)
    G.update({"今收px": None, "线尾x": None, "盘中": bool(intraday), "补线": None, "接口说明": "截图里找不到白色价格线, 接口误差没量"})
    if not intraday:
        wm = (blk.min(-1) > 150) & (blk.max(-1) - blk.min(-1) < 45)
        yp = py(p0) - ya
        d1 = [np.min(np.abs(np.where(wm[:, j])[0] - yp)) for j in range(wm.shape[1] - 6, wm.shape[1]) if wm[:, j].any()]
        d1 = [v for v in d1 if v <= 40]   # 只在换算位置 ±40px 里找(一字板价格线贴着框线 / 被百分比字盖住时找不到 → 如实写没量到)
        if d1 and (intraday is False or min(d1) <= 15):   # 时刻认出来是收盘后 → 就按收盘量; 时刻没认出来且 15:00 处对不上 → 再按盘中试
            G["今收px"], G["线尾x"] = float(min(d1)), xc_
            G["接口说明"] = f"接口(今收 {p0:.2f}; 截图 {clock or '时刻没认出'} 收盘后)像素误差 {G['今收px']:.1f}px"
            return
        if intraday is False:
            G["接口说明"] = f"截图 {clock} 收盘后, 但 15:00 处今收 ±40px 内找不到白色价格线(一字板贴框线 / 被字盖住), 接口误差没量到"
            return
        G["盘中"] = True
    wm = (blk.min(-1) > 175) & (blk.max(-1) - blk.min(-1) < 40)
    z_ = int(gg["zero"] - ya)
    wm[max(0, z_ - 4):z_ + 5] = False   # 0% 虚线(灰白)
    for x_, y_, t_ in G.get("texts") or []:
        wm[max(0, int(y_ - 20 - ya)):max(0, int(y_ + 20 - ya)), max(0, int(x_ - 6 - xo)):max(0, int(x_ + 24 * len(t_) - xo))] = False
    run = wm[:, 3:] & wm[:, 2:-1] & wm[:, 1:-2] & wm[:, :-3]
    cols = np.where(run.any(0))[0]
    if not len(cols):
        G["接口说明"] = f"盘中截图({clock}), 找不到白色价格线尾端, 接口误差没量"
        return
    j = int(cols.max())
    xt = j + 3 + xo
    ys_ = np.where(run[:, j])[0] + ya
    G["线尾x"] = xt
    dw = G["day_w"]
    m_t = int(round((xt - xo) / dw * 240))
    try:
        M = minute_today(code, end)
    except Exception as e:   # noqa: BLE001
        M = []
        G["接口说明"] = f"盘中截图({clock}, 线尾 ≈ 第 {m_t} 分钟), 库里分钟线取不到: {e!r}"[:120]
    if M:
        near = min(M, key=lambda r: abs(r[0] - m_t))
        dd_ = float(np.min(np.abs(ys_ - py(near[1]))))
        G["今收px"] = dd_ if dd_ <= 40 else None
        hm = near[0] + 570 if near[0] <= 120 else near[0] - 120 + 780
        G["补线"] = [(xo + m / 240 * dw, py(c), py(av)) for m, c, av in M if m >= near[0]]
        G["接口说明"] = (f"盘中截图({clock}; 线尾 {hm // 60:02d}:{hm % 60:02d}, 库价 {near[1]:.2f}): 线尾像素误差 " + (f"{G['今收px']:.1f}px; " if G["今收px"] is not None else f"没量到(差 {dd_:.0f}px, 多半线尾认错); ") +
                       f"之后到 15:00 用库里真实 1 分钟线补上(灰线), 预测从真实收盘 {p0:.2f} 接")


def draw_intra(shot, code, v2, it, outp, C, g, kind, days, pa=None, pa_md=None, G=None):
    img = Image.open(shot).convert("RGB")
    G = G or intra_geom(img, kind, g, _ocr(shot))
    gg = G["g"]
    p0 = C["close"]

    def py(p):
        return gg["zero"] - ((p / gg["base"] - 1) * 100) / gg["pmax"] * (gg["zero"] - gg["top"])
    if "今收px" not in G:
        intra_interface(G, img, py, p0, code, v2["T"], shot)
    groups = it["子"] if it["标签"] == "X" else [it]
    dw, gap, xb = G["day_w"], G["gap"], G["xb"]
    x_day = [xb + gap + i * (dw + gap) for i in range(2)]   # 第 i 天 09:30 的 x
    label_room = 175
    ext = int(math.ceil(gap + 2 * (dw + gap) + label_room))
    rng = np.random.default_rng(7)
    curves, used = [], []
    for g_ in groups:
        for i in range(min(2, len(g_["代表样本"]["path"]))):
            pts, real = DF._intra_pts(g_["代表样本"], i, p0, x_day[i] - 4, dw + 8, py, rng)
            curves.append((g_, i, pts))
            used.append((g_["名"], i, real))
    lim = 20 if v2.get("20cm") else 10
    ys = [y for _, _, pts in curves for _, y in pts] + [py(p0 * (1 + lim / 100)), py(p0 * (1 - lim / 100))]
    a = _arr(img)
    y0, y1 = band_rows(a, xb, min(gg["top"], min(ys) - 14), max(G["y_axis"] + 22, max(ys) + 14), G["bg"], ymin=int(gg["top"] - 260))
    clip = []   # 越出可画范围(上面 = 截图表头, 不剖)的点压到边上, 标出真实价
    for j, (g_, i, pts) in enumerate(curves):
        lo_y = y0 + 6
        if min(y for _, y in pts) < lo_y:
            k = int(np.argmin([y for _, y in pts]))
            clip.append((pts[k][0], lo_y, gg["base"] * (1 + ((gg["zero"] - pts[k][1]) / (gg["zero"] - gg["top"]) * gg["pmax"]) / 100), g_))
            curves[j] = (g_, i, [(x, max(y, lo_y)) for x, y in pts])
    E0 = stitch_canvas(img, xb, ext, y0, y1, int(G["xl"] + 3), G["bg"])
    full = E0.convert("RGBA")
    ov = Image.new("RGBA", full.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(ov)
    yt, ybt = y0 + 2, max(gg["bot"], min(y1 - 30, max(ys) + 14))
    X1 = xb + ext - 6
    dr.rectangle([xb + 1, yt, X1 - label_room + 10, ybt], fill=TINT)
    if G.get("补线"):   # 盘中截图: 截图时刻 → 15:00 的真实走势(灰), 均价(暗黄)
        F = G["补线"]
        dr.line([(x, y) for x, y, _ in F], fill=(165, 165, 165, 255), width=3)
        dr.line([(x, y) for x, _, y in F], fill=(170, 140, 40, 220), width=2)
        dr.text((F[0][0] + 6, min(y for _, y, _ in F) - 30), "截图后真实走势(库)", font=_f(20), fill=(185, 185, 185, 255))
    gc = G["grid_col"] + (255,)
    for i in range(2):   # 日分隔线 / 小时线(和原图同色)
        xa = x_day[i]
        xs_ = xa - gap / 2 if gap else xa
        _dash_line(dr, (xs_, yt), (xs_, ybt), DIV + (200,), 2 if i == 0 else 1, 7, 5)   # 日分隔(第 1 条 = 今 / 预测 分界)
        if kind == "分时":
            for hh in range(1, 4):
                xh = xa + dw * hh / 4
                dr.line([(xh, gg["top"]), (xh, gg["bot"])], fill=gc, width=1 if hh != 2 else 2)
        dr.text((xa + dw / 2 - 30, G["y_axis"] - 14), days[i], font=_f(26), fill=(175, 175, 175, 255))
    _dash_line(dr, (xb, py(p0)), (X1 - label_room + 10, py(p0)), YEL + (170,), 1, 6, 5)
    for pv, nm, cc in ((p0 * (1 + lim / 100), "T+1 涨停", (255, 90, 90)), (p0 * (1 - lim / 100), "T+1 跌停", (40, 200, 120))):
        _dash_line(dr, (x_day[0], py(pv)), (x_day[0] + dw, py(pv)), cc + (200,), 1, 6, 5)
        dr.text((x_day[0] + 6, py(pv) - (26 if "涨" in nm else -4)), f"{nm} {pv:.2f}", font=_f(20), fill=cc + (255,))
    for g_, i, pts in curves:
        if len(groups) == 1:
            dr.line(pts, fill=PRICE_W + (235,), width=3)
            pr = [p0 * (1 + ((gg["zero"] - y) / (gg["zero"] - gg["top"]) * gg["pmax"]) / 100) for _, y in pts]
            pr = [gg["base"] * (1 + ((gg["zero"] - y) / (gg["zero"] - gg["top"]) * gg["pmax"]) / 100) for _, y in pts]
            av = np.cumsum(pr) / np.arange(1, len(pr) + 1)
            apts = [(x, py(v)) for (x, _), v in zip(pts, av)]
            for p_, q_ in zip(apts[::3], apts[3::3]):
                dr.line([p_, q_], fill=AVG_Y + (200,), width=2)
            prev_c = p0 if i == 0 else p0 * (1 + g_["代表样本"]["path"][i - 1]["c"] / 100)
            if i == 1:
                _dash_line(dr, (x_day[1], py(prev_c)), (x_day[1] + dw, py(prev_c)), (150, 150, 150, 200), 1, 6, 5)
        else:
            dr.line(pts, fill=DF.COL_V2.get(g_["名"], WHT) + (240,), width=3)
    if len(groups) == 1:
        rep = it["代表样本"]["path"]
        for i, p in enumerate(rep[:2]):
            pc = p0 * (1 + p["c"] / 100)
            dr.text((x_day[i] + dw - 60, py(pc) + (8 if i == 0 else -30)), f"{pc:.2f}", font=_f(22), fill=YEL + (255,))
    else:
        for k, g_ in enumerate(groups):
            dr.text((x_day[0] + 8, yt + 8 + k * 28), f"— {g_['名']} {g_['概率']}%", font=_f(22), fill=DF.COL_V2.get(g_["名"], WHT) + (255,))
    dr.text((x_day[0] + dw * 0.45, yt + 4 if len(groups) == 1 else yt + 8 + len(groups) * 28), "预测", font=_f(24), fill=YEL + (255,))
    for x, y, pv, g_ in clip:
        cc = DF.COL_V2.get(g_["名"] if g_ is not it else g_["首日"], WHT)
        dr.polygon([(x - 7, y + 10), (x + 7, y + 10), (x, y - 2)], fill=cc + (255,))
        dr.text((x + 10, y - 2), f"↑{pv:.2f} 超出图框", font=_f(20), fill=cc + (255,))
    for pv, nm, cc in ((gg["base"] * (1 + gg["pmax"] / 100), "原图上沿", (130, 130, 130)), (gg["base"], "原图 0%", (130, 130, 130)),
                       (gg["base"] * (1 - gg["pmax"] / 100), "原图下沿", (130, 130, 130)), (p0, "今收", YEL)):
        y = py(pv)
        if yt <= y <= ybt:
            dr.text((X1 - label_room + 16, y - 12), f"{pv:.2f} {nm}", font=_f(19), fill=cc + (255,))
    full = Image.alpha_composite(full, ov).convert("RGB")
    extra = [("── 衔接校准 ──", DF.CYN),
             (G["接口说明"] + (f"(≈{G['今收px'] * gg['base'] * gg['pmax'] / 100 / (gg['zero'] - gg['top']):.3f} 元)" if G.get("今收px") is not None else ""), YEL),
             ("分时: " + " / ".join(f"{('' if len(groups) == 1 else nm + ' ')}第{i + 1}天{'真实 1 分钟线' if r else '无分钟线, 按开高低收示意'}" for nm, i, r in used), GRY),
             (f"价格轴 = 原图价格轴(0% = {gg['base']}" + (f"(库; OCR 读的 {gg['ocr_base']})" if gg.get("ocr_base") and abs(gg["ocr_base"] - gg["base"]) > 1e-6 else "")
              + f", 上沿 +{gg['pmax']}%; {gg.get('校准', '')}); 一天宽 {dw:.0f}px = 原图" + ("09:30~15:00 宽度" if kind == "分时" else "五日每格宽度")
              + "; 原图右边框 / 盘口整体右移, 预测接在边框处", GRY),
             ("黄虚线 = 均价(没有量, 按价格累计均值示意)", GRY) if len(groups) == 1 else ("", GRY)]
    lines = DF.v2_panel_lines(v2, it, p0, days, pa, pa_md, [x for x in extra if x[0]])
    _compose(full, None, lines, outp)


# ================================================================ 入口(和 draw_future.draw_v2 同参数 / 同文件名)

def _ocr(shot):
    k = str(shot)
    if k not in _CACHE:
        import ocr_shot as OS
        _CACHE[k] = OS.parse(shot)
    return _CACHE[k]


def draw_v2_stitch(shot, kind, code, v2, out_dir, end, C=None, g=None, with_extreme=True, days=None, pa=None, pa_md=None, ocr=None):
    """kind = "daily" / "intra"(分时 / 五日, 要给 g); 返回 (输出路径列表, C)"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    days = days or DF.next_days(end, 2)
    if ocr is not None:
        _CACHE[str(shot)] = ocr
    img = Image.open(shot).convert("RGB")
    o = _ocr(shot)
    if kind == "daily":
        G = daily_geom(img, code, end, o)
    else:
        ty = o.get("类型") if o.get("类型") in ("分时", "五日") else ("五日" if g.get("day_w") == 249 else "分时")
        G = intra_geom(img, ty, g, o)
    outs = []
    for it in DF.v2_items(v2, with_extreme):
        op = out_dir / f"{code}_{Path(shot).stem}_v2_{it['标签']}{it['名'].replace('→', '-')}.png"
        if kind == "daily":
            C = draw_daily(shot, code, v2, it, op, end, days, pa, pa_md, G)
        else:
            draw_intra(shot, code, v2, it, op, C or {"close": v2["收盘"]}, g, ty, days, pa, pa_md, G)
        outs.append(str(op))
    meta = {"src": G.get("src"), "score": G.get("score")} if kind == "daily" else {"day_w": G["day_w"], "校准": G["g"].get("校准"), "今收px": G.get("今收px"), "盘中": G.get("盘中")}
    return outs, (C or {}) | {"stitch": meta}


# ================================================================ 自测(10/26 三只票)

TRIAL = {"603280": ("微信图片_20261026193939_456_6", "微信图片_20261026193939_457_6", "微信图片_20261026193940_458_6"),
         "002474": ("微信图片_20261026193744_451_6", "微信图片_20261026193744_450_6", "微信图片_20261026193745_452_6"),
         "001359": ("微信图片_20261026193746_454_6", "微信图片_20261026193746_453_6", "微信图片_20261026193747_455_6")}


def trial(codes=None, only=None):
    import kline_inbox as KI
    day, end = "2026.10.26", "2026-10-26"
    st = KI.load_st(day)
    cases = {x["key"]: x for x in KI.I.load_cases()}
    od = ROOT / "results" / "kline" / "_draw_trial"
    tmp = ROOT / "scripts" / "temp" / "draw_trial_1026"
    rep = []
    for code, names in TRIAL.items():
        if codes and code not in codes:
            continue
        f = tmp / f"v2_{code}.json"
        if f.exists():
            v2 = json.loads(f.read_text(encoding="utf-8"))
        else:
            import scen_v2 as SV
            v2 = SV.scen(code, end)
        pa, pa_md, _ = KI.pa_load(code, end)
        days = DF.next_days(end, 2)
        C = None
        for n in names:
            gst = st["images"][n + ".jpg"]
            ocr_f = tmp / f"ocr_{n}.json"
            ocr = json.loads(ocr_f.read_text(encoding="utf-8")) if ocr_f.exists() else None
            shot = KI.INBOX / day / (n + ".jpg")
            ty = gst.get("类型") or ""
            if only and not ty.startswith(only):
                continue
            if ty.startswith("日K"):
                outs, C = draw_v2_stitch(shot, "daily", code, v2, od, end, days=days, pa=pa, pa_md=pa_md, ocr=ocr)
                rep.append((code, n, ty[:2], C["stitch"]))
            else:
                gg, why = KI._intra_axis(gst, cases[gst["case"]])
                if not gg:
                    rep.append((code, n, ty, f"跳过 {why}"))
                    continue
                outs, _ = draw_v2_stitch(shot, "intra", code, v2, od, end, C=C, g=gg, days=days, pa=pa, pa_md=pa_md, ocr=ocr)
                rep.append((code, n, ty, _["stitch"]))
            print(code, n, ty[:2], "\n  " + "\n  ".join(outs))
    for r in rep:
        print(r)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--trial" in sys.argv:
        args = [x for x in sys.argv[1:] if not x.startswith("--")]
        trial(codes=[x for x in args if x.isdigit()] or None, only=next((x for x in args if not x.isdigit()), None))
