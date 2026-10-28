# -*- coding: utf-8 -*-
"""ocr_shot.py — 东方财富手机截图 OCR 解析(10/25; RapidOCR onnxruntime CPU, 一张约 5 秒, 限 2 线程)

parse(图片) → {
  name / code(顶部标题; 代码 6 位)/ 类型(分时 / 五日 / 日K / 周K / 月K: 看 tab 蓝色下划线的横向位置)
  axis(分时 / 五日的价格轴): {top_y, top_pct, top_px, zero_y, bot_y, base(0% 对应价)} —— 左上角价格 + 右侧百分比 + 0.00% 那一行的 y, 续画未来分时用
  x 轴日期(五日图 10/19 … 10/23)/ 光标(顶部"价格:"而不是"最新:" = 十字光标停在某处, 顶部数字不是收盘)
  texts: 全部识别结果 [(x, y, 文本)](原图坐标)}
用法: python ocr_shot.py <图片>
"""
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

_O = {}
PCT = re.compile(r"^-?\d{1,3}\.\d{2}%$")
NUM = re.compile(r"^\d{1,4}\.\d{2,3}$")


def ocr():
    if "o" not in _O:
        import onnxruntime as ort
        import rapidocr_onnxruntime.utils as RU
        from rapidocr_onnxruntime import RapidOCR

        class _Opt(ort.SessionOptions):   # 10/25 实测: RapidOCR 不认线程参数, 默认吃满 24 个逻辑核(CPU 2200%)→ 改 onnx 会话为 2 线程
            def __init__(self):
                super().__init__()
                self.intra_op_num_threads = 2
                self.inter_op_num_threads = 1
        RU.SessionOptions = _Opt
        _O["o"] = RapidOCR()
    return _O["o"]


def chart_type(img):
    """tab 行(分时 / 五日 / 日K / 周K / 月K)蓝色下划线的横向位置"""
    W, H = img.size
    a = np.asarray(img.convert("RGB")).astype(int)[int(H * 0.26):int(H * 0.33)]
    blue = (a[..., 2] > 180) & (a[..., 0] < 100) & (a[..., 1] > 100) & (a[..., 1] < 190)
    ys, xs = np.where(blue)
    if not len(xs):
        return "未知"
    x = float(np.median(xs)) / W
    return "分时" if x < 0.14 else "五日" if x < 0.28 else "日K" if x < 0.42 else "周K" if x < 0.56 else "月K"


def chart_type_ocr(img, T):
    """10/28: 按 OCR 认出的 tab 文字位置找蓝色下划线(原 chart_type 只扫 26%~33% 高度的固定带: 区间统计 / 超级复盘页 tab 行下移到 ~36%,
    扫到别处的蓝色 → 五日判「未知」、日K 判「月K」); 每个 tab 字下方 0.5%~3% 高度里蓝色像素最多的那个 = 选中的 tab"""
    W, H = img.size
    a = np.asarray(img.convert("RGB")).astype(int)
    best, bn = None, 0
    for x, y, t in T:
        tt = t.replace("k", "K")
        if tt not in ("分时", "五日", "日K", "周K", "月K") or not (H * 0.2 < y < H * 0.45):
            continue
        x0, x1 = max(0, int(x - W * 0.01)), min(W, int(x + W * 0.09))
        y0, y1 = int(y + H * 0.005), min(H, int(y + H * 0.03))
        blk = a[y0:y1, x0:x1]
        if not blk.size:
            continue
        n = int(((blk[..., 2] > 180) & (blk[..., 0] < 100) & (blk[..., 1] > 100) & (blk[..., 1] < 190)).sum())
        if n > bn:
            best, bn = tt, n
    if bn >= 20:
        return best
    # 选中的 tab 是蓝字, OCR 常常认不出 → 认出了其余 tab、只缺一个时, 按相邻 tab 的间距插出它的位置, 那里(字 + 下划线)有蓝色就是它
    order = ["分时", "五日", "日K", "周K", "月K"]
    got = {t.replace("k", "K"): (x, y) for x, y, t in T if t.replace("k", "K") in order and H * 0.2 < y < H * 0.45}
    miss = [t for t in order if t not in got]
    if len(got) >= 3 and len(miss) == 1:
        i = order.index(miss[0])
        xs = sorted((order.index(k), v[0]) for k, v in got.items())
        step = (xs[-1][1] - xs[0][1]) / max(1, xs[-1][0] - xs[0][0])
        xm = xs[0][1] + (i - xs[0][0]) * step
        ym = sorted(v[1] for v in got.values())[len(got) // 2]
        x0, x1 = max(0, int(xm - W * 0.01)), min(W, int(xm + W * 0.09))
        y0, y1 = max(0, int(ym - H * 0.015)), min(H, int(ym + H * 0.03))
        blk = a[y0:y1, x0:x1]
        if blk.size and int(((blk[..., 2] > 180) & (blk[..., 0] < 100) & (blk[..., 1] > 100) & (blk[..., 1] < 190)).sum()) >= 20:
            return miss[0]
    return None


def parse(path):
    img = Image.open(path).convert("RGB")
    W, H = img.size
    r, _ = ocr()(np.array(img))
    T = [(float(b[0][0]), float((b[0][1] + b[2][1]) / 2), str(t).strip()) for b, t, s in (r or [])]
    out = {"file": Path(path).name, "W": W, "H": H, "类型": chart_type_ocr(img, T) or chart_type(img), "texts": T}
    tabs = {t for x, y, t in T if t in ("分时", "五日", "日K", "周K", "月K", "日k", "周k", "月k") and H * 0.2 < y < H * 0.4}
    if len(tabs) < 2:   # 10/25: 只看蓝色下划线会把别的图(matplotlib 蓝线)误认成行情页 → 还要认出 tab 行文字(分时 / 五日 / 日K …)至少 2 个
        out["类型"] = "未知"
    head = [t for t in T if t[1] < H * 0.10]
    code = next((m.group(0) for x, y, t in head for m in [re.search(r"(?<!\d)\d{6}(?!\d)", t)] if m), None)
    out["code"] = code
    if code:
        cy = next(y for x, y, t in head if code in t)
        nm = [t for x, y, t in head if y < cy - 10 and len(t) >= 2 and not re.search(r"\d|东方|财富", t)]
        out["name"] = nm[-1] if nm else None
    out["光标"] = any(re.match(r"^价格[:：]", t) for x, y, t in T if H * 0.33 < y < H * 0.41)   # 五日 / 分时顶部"价格:"= 十字光标在某处
    if out["类型"].startswith(("日K", "周K", "月K")):   # 日 K 横轴日期标签(20260713 … 20261023): 最右那个贴着右边 = 截图最右一根就是它
        lab = sorted((x, t) for x, y, t in T if re.fullmatch(r"20\d{6}", t) and H * 0.82 < y < H * 0.93)
        out["日期轴"] = [t for x, t in lab]
        if lab:
            x, t = lab[-1]
            out["最右日期"] = f"{t[:4]}-{t[4:6]}-{t[6:]}"
            out["最右日期贴边"] = bool(x > W * 0.75)
    if any("超级复盘" in t for x, y, t in T):   # 日 K 下面弹出"超级复盘"(某一天的分时): 横轴被盖住; 弹出的那天 = 复盘日
        out["超级复盘"] = True
        dd = [t for x, y, t in T if re.fullmatch(r"20\d{6}", t) and H * 0.60 < y < H * 0.76]
        if dd:
            out["复盘日"] = f"{dd[0][:4]}-{dd[0][4:6]}-{dd[0][6:]}"
    if out["类型"] in ("分时", "五日"):
        right = [(x, y, t) for x, y, t in T if PCT.match(t) and x > W * 0.6 and H * 0.30 < y < H * 0.72]
        left = [(x, y, t) for x, y, t in T if NUM.match(t) and x < W * 0.15 and H * 0.30 < y < H * 0.72]
        if right:
            top = min(right, key=lambda z: z[1])
            bot = max(right, key=lambda z: z[1])
            zero = next((z for z in right if z[2] in ("0.00%", "-0.00%")), None)
            tp = next((z for z in left if abs(z[1] - top[1]) < 25), None) if not top[2].startswith("-") else None
            bp = next((z for z in left if abs(z[1] - bot[1]) < 25), None)
            ax = {"top_y": top[1], "top_pct": abs(float(top[2][:-1])), "bot_y": bot[1]}
            ax["zero_y"] = zero[1] if zero else (top[1] + bot[1]) / 2
            if tp:
                ax["top_px"] = float(tp[2])
                ax["base"] = round(ax["top_px"] / (1 + ax["top_pct"] / 100), 3)
            elif bp:   # 10/26: 左上价格被十字光标价格框盖住 → 用底部那对(价格 + 负百分比)反推 0% 价
                ax["base"] = round(float(bp[2]) / (1 + float(bot[2][:-1]) / 100), 3)
            if bot[1] - top[1] < 50 and ax.get("base"):   # 10/26: 顶部百分比被价格线压花(读成 "%666")只剩一个 → 左侧价格标签换算成百分比, 直线拟合 y = zero_y - k·pct
                pts = [(y, float(t[:-1])) for x, y, t in right] + [(y, (float(t) / ax["base"] - 1) * 100) for x, y, t in left]
                if max(p for y, p in pts) - min(p for y, p in pts) > 2:
                    n = len(pts)
                    my, mp = sum(y for y, p in pts) / n, sum(p for y, p in pts) / n
                    k = -sum((y - my) * (p - mp) for y, p in pts) / sum((p - mp) ** 2 for y, p in pts)
                    pm = max(abs(p) for y, p in pts if (y, p) in [(yy, float(t[:-1])) for x, yy, t in right]) or ax["top_pct"]
                    ax["zero_y"] = round(my + k * mp, 1)
                    ax["top_pct"], ax["top_y"], ax["bot_y"] = pm, round(ax["zero_y"] - k * pm, 1), round(ax["zero_y"] + k * pm, 1)
                    ax["拟合"] = n
            out["axis"] = ax
        out["日期轴"] = [t for x, y, t in T if re.match(r"^\d{1,2}/\d{1,2}$", t) and y > H * 0.70]
    return out


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for f in sys.argv[1:]:
        o = parse(f)
        print({k: v for k, v in o.items() if k != "texts"})
