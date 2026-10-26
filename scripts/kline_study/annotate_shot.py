# -*- coding: utf-8 -*-
"""annotate_shot.py — 在东方财富日 K 截图原图上标箱体 + 画之后 N 天的走势区间(10/24 用户要"在原图上标, 再预测之后走势")
做法: ①扫截图 K 线区的彩色像素 → 每根 K 线的列位置 + 影线最高 / 最低像素 ②最右一根 = 截止日, 往左对上库里日线 ③影线像素 vs 库里最高 / 最低价 线性回归 → 价格 ↔ 像素
     ④段式箱体(draw_box.seg_boxes)画回原图 ⑤box_forecast 本票历史同箱体位置之后 N 天分布(P10 / 中位 / P90)画成右侧扩展的扇形 + 文字
用法: python annotate_shot.py <截图> <代码> <截止日> [N=5] [输出]
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import box_forecast as BF   # noqa: E402
import draw_box as DB   # noqa: E402

FONT = "C:/Windows/Fonts/msyh.ttc"


def bars(img, y0, y1, x0, x1):
    """只认 K 线实体(均线是 2~3 像素细线, 实体每列 ≥6 个彩色像素); 空心红 K 两条竖边间隔小 → 合并; → [(中心 x, 实体顶 y, 实体底 y, 颜色)]"""
    a = np.asarray(img.convert("RGB")).astype(int)[y0:y1, x0:x1]
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    red = (r > 170) & (g < 90) & (b < 90)
    cyan = (g > 150) & (b > 150) & (r < 120)
    out = []
    for colr, m in (("red", red), ("cyan", cyan)):
        cnt = m.sum(0)
        xs = np.where(cnt >= 6)[0]
        groups, cur = [], []
        for x in xs:
            if cur and x - cur[-1] > 6:   # 空心红 K 左右两条边相隔 < 6 像素算同一根
                groups.append(cur)
                cur = []
            cur.append(x)
        if cur:
            groups.append(cur)
        for gx in groups:
            if gx[-1] - gx[0] > 30:
                continue
            sub = m[:, gx[0]:gx[-1] + 1]
            rows = np.where(sub.sum(1) >= max(2, (gx[-1] - gx[0] + 1) // 2))[0]   # 实体行: 这一行有一半以上列是彩色(影线只有 1~2 列)
            if not len(rows):
                continue
            out.append((x0 + (gx[0] + gx[-1]) / 2, y0 + rows.min(), y0 + rows.max(), colr))
    return sorted(out)


def main(shot, code, end, N=5, outp=None, ytop=None, _depth=0):
    img = Image.open(shot).convert("RGB")
    W, H = img.size
    # 东方财富 iOS 竖屏日 K: 主图区约 y 0.425~0.59(带"相关 ETF / 三季报"两行) 或 0.395~0.565(只有一行), x 0.015~0.975(按 1280×2774 量的比例)
    if ytop is None:
        cand = [(len(bars(img, int(H * t), int(H * (t + 0.165)), int(W * 0.015), int(W * 0.975))), t) for t in (0.395, 0.41, 0.425)]
        ytop = max(cand)[1]
    y0, y1, x0, x1 = int(H * ytop), int(H * (ytop + 0.165)), int(W * 0.015), int(W * 0.975)
    B = bars(img, y0, y1, x0, x1)
    o_, (d, o, h, l_, cl, atr, segs) = BF.stats(code, end, N)
    xs = np.array([b[0] for b in B])
    colr = np.array([b[3] for b in B])
    sp = np.diff(xs)
    dx0 = float(np.median(sp[(sp > 8) & (sp < 40)]))
    best = None   # 搜 K 线间距 dx 和最右一根的位置: 颜色要对得上(红 = 收 ≥ 开), 实体像素和库里价格线性关系残差最小
    for dx in np.arange(dx0 * 0.9, dx0 * 1.1, 0.05):
        for sh, e in [(sh, e) for sh in range(0, 6) for e in range(0, 300)]:   # e = 截图最右一根离截止日几根(截图常是往左滑过的历史窗口)
            xr = xs.max() + sh * dx
            pos = np.round((xr - xs) / dx).astype(int)
            if (np.abs((xr - xs) / dx - pos) > 0.3).mean() > 0.2:
                continue
            idx = len(cl) - 1 - e - pos
            ok = idx >= 0
            if ok.sum() < 10:
                continue
            up = (cl >= o)[idx[ok]]
            mis = float(np.mean(up != (colr[ok] == "red")))
            P = np.concatenate([np.maximum(o, cl)[idx[ok]], np.minimum(o, cl)[idx[ok]]])
            Y = np.concatenate([np.array([q[1] for q in B])[ok], np.array([q[2] for q in B])[ok]])
            k, c0 = np.polyfit(P, Y, 1)
            res = np.abs(Y - (k * P + c0))
            keep = res <= max(np.percentile(res, 80), 2)
            k, c0 = np.polyfit(P[keep], Y[keep], 1)
            err = float(np.median(np.abs(Y - (k * P + c0))) / abs(k)) if k else 99
            sc = mis * 10 + err
            if k < 0 and (best is None or sc < best[0]):
                best = (sc, dx, xr, k, c0, err, mis, e)
    _, dx, xr, k, c0, errp, mis, e_end = best
    err = errp * abs(k)
    xs = np.array([xr - i * dx for i in range(len(cl))])[::-1][-len(cl):]   # xs[-1] = 截止日那根
    n = int(round((xr - min(q[0] for q in B)) / dx)) + 1
    if e_end and _depth == 0:   # 截图是往左滑过的历史窗口 → 截止日改成截图最右一根, 预测只用那天以前的数据, 再拿之后真实走势对答案
        return main(shot, code, str(d[len(cl) - 1 - e_end]), N, outp, ytop, 1)
    print(f"校准: K 线间距 {dx:.2f} 像素, 颜色对不上 {mis:.0%}, 价格误差中位 {errp:.3f} 元, 截图最右一根 = {d[len(cl) - 1 - e_end]}(往前 {e_end} 根)")
    py = lambda p: k * p + c0   # noqa: E731
    ext = int(dx * (N + 4) + 360)   # 右侧扩展画预测
    canvas = Image.new("RGB", (W + ext, H), (16, 16, 20))
    canvas.paste(img, (0, 0))
    ov = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(ov)
    f = ImageFont.truetype(FONT, 26)
    fs = ImageFont.truetype(FONT, 22)
    first = len(cl) - n
    for a_, b_, r, s, ut, sp in segs:
        if b_ < first:
            continue
        xa = xs[max(a_, first)] - dx / 2
        xb = xs[b_] + dx / 2
        dr.rectangle([xa, py(r), xb, py(s)], fill=(255, 212, 59, 45), outline=(255, 170, 0, 255), width=3)
        dr.text((xb + 6, py(r) - 30), f"上沿 {r:.2f}", font=fs, fill=(255, 170, 0, 255))
        dr.text((xb + 6, py(s) + 2), f"下沿 {s:.2f}", font=fs, fill=(80, 170, 255, 255))
    # 预测扇形(本票历史同箱体位置之后 N 天)
    xl = xs[-1]
    p0 = cl[-1]
    if o_.get("n"):
        xe = xl + dx * N
        for lab, q, colr in (("P90", o_["P90"], (255, 90, 90, 255)), ("中位", o_["中位"], (240, 240, 240, 255)), ("P10", o_["P10"], (60, 200, 120, 255))):
            pe = p0 * (1 + q / 100)
            dr.line([xl, py(p0), xe, py(pe)], fill=colr, width=3)
            dr.text((xe + 8, py(pe) - 14), f"{N}日 {lab} {pe:.2f}({q:+.1f}%)", font=fs, fill=colr)
        dr.polygon([(xl, py(p0)), (xe, py(p0 * (1 + o_["P90"] / 100))), (xe, py(p0 * (1 + o_["P10"] / 100)))], fill=(255, 255, 255, 30))
        if o_.get("box"):
            dr.line([xl, py(o_["box"]["上沿"]), xe, py(o_["box"]["上沿"])], fill=(255, 170, 0, 200), width=2)
            dr.line([xl, py(o_["box"]["下沿"]), xe, py(o_["box"]["下沿"])], fill=(80, 170, 255, 200), width=2)
    tx = W + 20
    L = [f"{o_['name']}({code}) 截至 {o_['end']}",
         f"日线箱体 {o_['box']['下沿']}~{o_['box']['上沿']}" if o_.get("box") else "当前不在箱体里",
         f"现价在箱体 {o_['pos_now']}% 位置" if o_.get("pos_now") is not None else "",
         f"本票历史同位置样本 n={o_['n']}" if o_.get("box") else f"{o_.get('口径', '')} n={o_['n']}",
         f"之后 {N} 天: 中位 {o_.get('中位', 0):+.1f}%",
         f"P10 {o_.get('P10', 0):+.1f}% / P90 {o_.get('P90', 0):+.1f}%",
         f"最好 {o_.get('最好', 0):+.1f}% 最差 {o_.get('最差', 0):+.1f}%",
         f"{N} 天内向上离箱 {o_.get('向上离箱', 0)}%",
         f"向下离箱 {o_.get('向下离箱', 0)}% 仍在箱内 {o_.get('仍在箱内', 0)}%",
         f"(像素校准误差 ≈{err / abs(k):.2f} 元)"]
    yy = int(H * 0.215)
    for t in L:
        if t:
            dr.text((tx, yy), t, font=f, fill=(255, 255, 255, 255))
            yy += 40
    canvas = Image.alpha_composite(canvas.convert("RGBA"), ov).convert("RGB")
    outp = outp or str(Path(shot).with_name(Path(shot).stem + "_标注.png"))
    canvas.save(outp)
    print(outp, f"K线根数 {n} 校准误差 {err / abs(k):.3f} 元", o_)
    return outp, o_


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], a[2], int(a[3]) if len(a) > 3 else 5, a[4] if len(a) > 4 else None)
