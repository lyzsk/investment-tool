# 财联社图片 -> md 小节内容
# 用法:
#   python cls_image_ocr.py <图片路径> --type wp|sp      # 午评/收评: 13档涨跌分布表
#   python cls_image_ocr.py <图片路径> --type wjzt|zt    # 涨停分析长图: 题材分组+归因+个股表
# 输出: stdout 打印该小节的 md 内容(不含 ## 标题行), Java 侧替换小节用
# 失败闭环: 任何校验不过 -> 非0退出 PARSE_FAIL + 原因, Java 不写 md 只告警
import argparse, re, sys
from pathlib import Path

# md 模板 13 列(与 stocks md 的 ## 午评/## 收评 表头一致)
BINS = ["涨停", "大于+8%", "+8%", "+6%", "+4%", "+2%", "0%",
        "-2%", "-4%", "-6%", "-8%", "小于-8%", "跌停"]


_OCR = None

def _rapidocr():
    """RapidOCR 单例(批量跑几百张图时避免每张都初始化模型)"""
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR()
    return _OCR


def ocr_lines(path):
    lines, _ = _rapidocr()(str(path))
    # [(cx, cy, text, score)]
    out = []
    for box, text, score in (lines or []):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        out.append((sum(xs) / 4, sum(ys) / 4, text, score))
    return out


def parse_overview(lines):
    """概况区: 上涨/下跌/涨停/跌停/持平/停牌 家数 + 成交额。
    布局: 标签token 右侧最近(同y带)的"N家"token 即其值; 兼容"上涨1070家"连写"""
    kv = {}
    jia = [(cx, cy, re.fullmatch(r"(\d+)家", t.replace(" ", "")).group(1))
           for cx, cy, t, s in lines if re.fullmatch(r"\d+家", t.replace(" ", ""))]
    for key in ["上涨", "下跌", "涨停", "跌停", "持平", "停牌"]:
        for cx, cy, t, s in lines:
            tt = t.replace(" ", "")
            m = re.fullmatch(key + r"(\d+)家", tt)
            if m:
                kv[key] = m.group(1)
                break
            if tt == key:
                cands = sorted(((cx2 - cx, v) for cx2, cy2, v in jia
                                if abs(cy2 - cy) < 40 and cx2 > cx - 10),
                               key=lambda c: c[0])
                if cands:
                    kv[key] = cands[0][1]
                break
    # 位置法兜底(模板固定两行三列): 标签OCR失败时按格子坐标推断
    # 上行: [上涨, 持平, 下跌]; 下行: [涨停, 停牌, 跌停]
    if len(jia) >= 6 and any(k not in kv for k in ("上涨", "下跌", "涨停", "跌停")):
        clusters = []
        for cx, cy, v in jia:
            for cl in clusters:
                if abs(cl["cy"] - cy) < 40:
                    cl["items"].append((cx, v))
                    break
            else:
                clusters.append({"cy": cy, "items": [(cx, v)]})
        tri = sorted((cl for cl in clusters if len(cl["items"]) == 3),
                     key=lambda cl: cl["cy"])
        if len(tri) >= 2:
            up_items = sorted(tri[0]["items"])
            dn_items = sorted(tri[1]["items"])
            for key, (_, v) in zip(["上涨", "持平", "下跌"], up_items):
                kv.setdefault(key, v)
            for key, (_, v) in zip(["涨停", "停牌", "跌停"], dn_items):
                kv.setdefault(key, v)
    for cx, cy, t, s in lines:
        if "两市成交额" in t:
            m = re.search(r"([\d.]+万亿)", t)
            if m:
                kv["成交额"] = m.group(1)
            else:
                near = sorted(((cx2 - cx, re.search(r"[\d.]+万亿", t2).group(0))
                               for cx2, cy2, t2, s2 in lines
                               if abs(cy2 - cy) < 40 and cx2 > cx
                               and re.search(r"[\d.]+万亿", t2)), key=lambda c: c[0])
                if near:
                    kv["成交额"] = near[0][1]
            break
    return kv


def parse_breadth(lines, img_path=None):
    """直方图区: 干净标签行(同一水平线)拟合均匀网格 -> 每格正上方最近数字。
    缺格三级兜底: 概况区(涨/跌停/持平) -> 掩膜+识别器直读 -> 家数反解。
    数据口径(实测): 上涨=sum(row[1:6])不含涨停, 下跌=sum(row[7:12])不含跌停"""
    # 1) 干净标签(排除"大于/小于"第二行碎片和概况区重复): 取 y 带内最多的主行
    lab = [(cx, cy, t.replace(" ", "")) for cx, cy, t, s in lines
           if t.replace(" ", "") in BINS]
    if len(lab) < 8:
        return None, f"bin labels only {len(lab)}"
    ys = sorted(cy for _, cy, _ in lab)
    y_mode = ys[len(ys) // 2]
    main = sorted([(cx, t) for cx, cy, t in lab if abs(cy - y_mode) <= 12])
    if len(main) < 8:
        return None, f"main-row labels only {len(main)}"
    # 2) 均匀网格: 用最左/最右锚点(涨停/跌停必在两端)拟合 13 格
    x0, x12 = main[0][0], main[-1][0]
    step = (x12 - x0) / 12.0
    if step < 40 or step > 220:
        return None, f"grid step {step:.0f} abnormal"
    grid_x = [x0 + i * step for i in range(13)]
    # 3) 每格找数字: 标签线上方, |dx| < step*0.6, 取最近(y最大)
    nums = [(cx, cy, t) for cx, cy, t, s in lines
            if re.fullmatch(r"\d{1,5}", t) and cy < y_mode - 5]
    row = [None] * 13
    for i, gx in enumerate(grid_x):
        cands = [n for n in nums if abs(n[0] - gx) < step * 0.6]
        if cands:
            cands.sort(key=lambda n: -n[1])
            row[i] = cands[0][2]
    kv = parse_overview(lines)
    # 4a) 概况区兜底: 涨停/跌停/持平
    for idx, key in ((0, "涨停"), (12, "跌停"), (6, "持平")):
        if row[idx] is None and kv.get(key):
            row[idx] = kv[key]
    # 4b) 仍缺: 掩膜+识别器直读(召回检测器漏掉的孤立小数字)
    for i in range(13):
        if row[i] is None and img_path:
            row[i] = reocr_cell(img_path, grid_x[i], step, y_mode)
    # 4c) 仍缺且只缺一格: 用 上涨/下跌 家数反解(口径: 1..5=上涨, 7..11=下跌)
    missing = [i for i in range(13) if row[i] is None]
    if len(missing) == 1:
        i = missing[0]
        if 1 <= i <= 5 and kv.get("上涨"):
            row[i] = str(int(kv["上涨"]) - sum(int(row[j]) for j in range(1, 6) if j != i))
        elif 7 <= i <= 11 and kv.get("下跌"):
            row[i] = str(int(kv["下跌"]) - sum(int(row[j]) for j in range(7, 12) if j != i))
        if row[i] is not None and int(row[i]) < 0:
            row[i] = None  # 反解出负数=其它格有错, 不可信
    # 5) 交叉校验: 涨/跌停精确; 上涨/下跌和容差±2(±1误读放行但留警告)
    for idx, key in ((0, "涨停"), (12, "跌停")):
        if row[idx] and kv.get(key) and row[idx] != kv[key]:
            return None, f"cross-check fail: bin {BINS[idx]}={row[idx]} vs 概况 {kv[key]}"
    warns = []
    if all(row[i] for i in range(1, 6)) and kv.get("上涨"):
        d = sum(int(row[i]) for i in range(1, 6)) - int(kv["上涨"])
        if abs(d) > 2:
            return None, f"sum-check fail: 档1-5和 vs 上涨 {kv['上涨']} 差{d}"
        if d:
            warns.append(f"正档和 vs 上涨 差{d:+d}")
    if all(row[i] for i in range(7, 12)) and kv.get("下跌"):
        d = sum(int(row[i]) for i in range(7, 12)) - int(kv["下跌"])
        if abs(d) > 2:
            return None, f"sum-check fail: 档7-11和 vs 下跌 {kv['下跌']} 差{d}"
        if d:
            warns.append(f"负档和 vs 下跌 差{d:+d}")
    missing = [BINS[i] for i in range(13) if row[i] is None]
    if missing:
        return None, f"missing bins: {missing}"
    return (row, warns), None


_REC = None

def _recognizer():
    """PP-OCRv3 识别器(绕过检测器——孤立小数字检测器不触发)"""
    global _REC
    if _REC is None:
        import rapidocr_onnxruntime
        from rapidocr_onnxruntime.utils import read_yaml
        from rapidocr_onnxruntime.ch_ppocr_v3_rec import TextRecognizer
        root = Path(rapidocr_onnxruntime.__file__).parent
        cfg = read_yaml(str(root / "config.yaml"))["Rec"]
        cfg["model_path"] = str(root / "models" / "ch_PP-OCRv3_rec_infer.onnx")
        _REC = TextRecognizer(cfg)
    return _REC


def reocr_cell(img_path, gx, step, y_mode):
    """单格兜底: 竖条裁剪 -> 颜色掩膜(红涨/绿跌/灰平) -> 连通域找数字字形(排除扁宽柱条)
    -> 合并bbox -> 识别器直读。返回数字str或None"""
    try:
        import cv2
        import numpy as np
        img = cv2.imread(str(img_path))
        if img is None:
            return None
        h, w = img.shape[:2]
        x1 = max(0, int(gx - step / 2)); x2 = min(w, int(gx + step / 2))
        y1 = max(0, int(y_mode - 500)); y2 = min(h, int(y_mode + 2))
        strip = img[y1:y2, x1:x2].astype(np.int16)
        b, g, r = strip[:, :, 0], strip[:, :, 1], strip[:, :, 2]
        colored = (((g - r > 25) & (g - b > 25) & (g > 100)) |      # 绿
                   ((r - g > 25) & (r - b > 25) & (r > 100)))       # 红
        dark = (r < 160) & (g < 160) & (b < 160)                    # 灰/黑(0%档)
        dark[int(strip.shape[0] * 0.7):, :] = False                 # 深色掩膜排除底部标签区
        for mask_src in (colored, dark):
            mask = mask_src.astype(np.uint8)
            n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
            # 数字笔画: 高>=10 且 高>宽 (柱子是扁宽条, 排除)
            keep = [i for i in range(1, n) if stats[i, 3] >= 10 and stats[i, 3] > stats[i, 2]]
            if not keep:
                continue
            gx1 = min(stats[i, 0] for i in keep); gy1 = min(stats[i, 1] for i in keep)
            gx2 = max(stats[i, 0] + stats[i, 2] for i in keep)
            gy2 = max(stats[i, 1] + stats[i, 3] for i in keep)
            glyph = 255 - (mask[gy1:gy2 + 1, gx1:gx2 + 1] * 255)
            glyph = cv2.copyMakeBorder(glyph, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
            glyph = cv2.cvtColor(glyph, cv2.COLOR_GRAY2BGR)
            out, _ = _recognizer()(glyph)
            # 单字符天然低分(实测"1"≈0.34), 阈值放宽到0.25; 最终把关靠全局和校验
            if out and re.fullmatch(r"\d{1,5}", out[0][0]) and out[0][1] >= 0.25:
                return out[0][0]
        return None
    except Exception:
        return None


def render_wp_md(row, kv, warns):
    out = []
    out.append("| " + " | ".join(BINS) + " |")
    out.append("| " + " | ".join([":--:"] * 13) + " |")
    out.append("| " + " | ".join(row) + " |")
    out.append("")
    parts = []
    if "上涨" in kv and "下跌" in kv:
        parts.append(f"上涨 {kv['上涨']}家 / 下跌 {kv['下跌']}家")
    if "涨停" in kv and "跌停" in kv:
        parts.append(f"涨停 {kv['涨停']}家 / 跌停 {kv['跌停']}家")
    if "成交额" in kv:
        parts.append(f"两市成交额 {kv['成交额']}")
    if parts:
        out.append("**概况：** " + "；".join(parts) + "。")
    for wtext in warns:
        out.append(f"<!-- OCR校验警告: {wtext} -->")
    return "\n".join(out)


# ==================== wjzt/zt 涨停分析长图 ====================
# 结构(实测9/24): 红头(日期+标题~230px) -> 若干题材块 -> 版权尾(~260px)
# 题材块 = 红色大字体名(x<250) + "归因："段落 + 五列表头(股票名称/板数/涨跌幅/涨停时间/上涨逻辑) + 行
# 行 = 名称(粗体x<200) + 代码(名称正下方6位小字) + 板数(可缺) + 涨跌幅 + 涨停时间(可缺=未涨停) + 逻辑(可两行)
# 纯 OCR 几何解析, 不用 VLM: 布局刚性, OCR 零幻觉, 代码数是硬校验锚点


def ocr_sliced(path, strip_h=2000, overlap=150):
    """长图切条分别 OCR(det_limit_side_len 默认736会缩图, 必须切), y 加偏移, 重叠区去重。
    返回 [(cx, cy, text, score, box_abs)] 按 y,x 排序"""
    import cv2
    img = cv2.imread(str(path))
    h, w = img.shape[:2]
    out = []
    for y0 in range(0, h, strip_h - overlap):
        y1 = min(h, y0 + strip_h)
        lines, _ = _rapidocr()(img[y0:y1])
        for box, text, score in (lines or []):
            cx = sum(p[0] for p in box) / 4
            cy = sum(p[1] for p in box) / 4 + y0
            box_abs = [[p[0], p[1] + y0] for p in box]
            dup = any(abs(c[1] - cy) < 15 and abs(c[0] - cx) < 15 and c[2] == text
                      for c in out)
            if not dup:
                out.append((cx, cy, text, float(score), box_abs))
        if y1 >= h:
            break
    # 重叠区去重: 同一物理行在两条带各读一次, 文本可能不同(碎片)但位置重合
    # -> 按分数从高到低, 抑制 同一行(cy<12) 且 x 区间重叠>30% 的低分碎片
    def xr(c):
        xs = [p[0] for p in c[4]]
        return min(xs), max(xs)
    out.sort(key=lambda c: -c[3])
    kept = []
    for cand in out:
        x1, x2 = xr(cand)
        dup = False
        for k in kept:
            if abs(k[1] - cand[1]) >= 12:
                continue
            k1, k2 = xr(k)
            ov = min(x2, k2) - max(x1, k1)
            if ov > 0.3 * min(x2 - x1, k2 - k1):
                dup = True
                break
        if not dup:
            kept.append(cand)
    kept.sort(key=lambda c: (c[1], c[0]))
    return kept


def _red_ratio(img, box):
    """bbox 内红字像素占比(题材名/连板数是红色)"""
    xs = [p[0] for p in box]; ys = [p[1] for p in box]
    x1, x2 = max(0, int(min(xs))), int(max(xs)); y1, y2 = max(0, int(min(ys))), int(max(ys))
    crop = img[y1:y2, x1:x2].astype(int)
    if crop.size == 0:
        return 0.0
    b, g, r = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    red = (r - g > 60) & (r - b > 60) & (r > 120)
    return float(red.mean())


def parse_zt(img_path):
    """涨停分析长图 -> (themes, warns, err)。themes = [{name, attribution, rows:[...]}]
    行硬校验: 代码(6位)+涨跌幅 缺一不可; 区域代码总数必须=解析行数(防漏行)"""
    import cv2
    img = cv2.imread(str(img_path))
    if img is None:
        return None, None, "cannot read image"
    h, w = img.shape[:2]
    lines = ocr_sliced(img_path)
    # 1) 题材锚点: 红色大字(h>28)在左栏(x<250), 排除红头区(y<230)
    themes_y = [(cy, t.replace(" ", "")) for cx, cy, t, s, box in lines
                if _red_ratio(img, box) > 0.25
                and abs(box[3][1] - box[0][1]) > 28 and cx < 250 and cy > 230]
    themes_y.sort()
    if not themes_y:
        return None, None, "no theme anchors"
    bounds = [y for y, _ in themes_y] + [h - 260]  # 版权尾
    themes = []
    for i, (ty, tname) in enumerate(themes_y):
        seg = [l for l in lines if ty < l[1] < bounds[i + 1]]
        # 2) 表头定位(股票名称), 归因=主题名到表头之间的全部文本(可无, 如"其他")
        header = [l for l in seg if l[2].replace(" ", "") == "股票名称"]
        if not header:
            return None, None, f"theme {tname}: no table header"
        header_y = header[0][1]
        attr_toks = sorted((l for l in seg if ty + 30 < l[1] < header_y - 20),
                           key=lambda l: l[1])
        attribution = "".join(l[2].replace(" ", "") for l in attr_toks)
        attribution = re.sub(r"^归因[：:]", "", attribution)
        # 3) 行锚点: 名称=左栏(x<200)中文token, 排除6位代码
        #    (h 不设高阈值: 紧贴表头的首行名称 OCR 框可能畸形, 实测有 h=23;
        #     漏锚=漏行, 错锚会被代码缺失/行数校验拦住, 宁宽勿漏)
        name_anchors = sorted((l for l in seg if l[1] > header_y + 20
                               and l[0] < 200
                               and abs(l[4][3][1] - l[4][0][1]) >= 18
                               and not re.fullmatch(r"\d{6}", l[2].replace(" ", ""))
                               and re.search(r"[一-鿿]", l[2])),
                              key=lambda l: l[1])
        rows = []
        nys = [l[1] for l in name_anchors]
        for j, nl in enumerate(name_anchors):
            y_top = (nys[j - 1] + nl[1]) / 2 if j else header_y + 20
            y_bot = (nl[1] + nys[j + 1]) / 2 if j + 1 < len(nys) else bounds[i + 1]
            band = [l for l in seg if y_top <= l[1] < y_bot]
            code = next((l[2].replace(" ", "") for l in band
                         if l[0] < 200 and re.fullmatch(r"\d{6}", l[2].replace(" ", ""))), None)
            boards = next((l[2].replace(" ", "") for l in band
                           if 200 < l[0] < 420
                           and re.fullmatch(r"(首板|\d+天\d+板|ST|退市)", l[2].replace(" ", ""))), None)
            pct = next((l[2].replace(" ", "") for l in band
                        if 420 < l[0] < 600
                        and re.fullmatch(r"\d{1,3}\.\d{2}%", l[2].replace(" ", ""))), None)
            ztime = next((l[2].replace(" ", "") for l in band
                          if 600 < l[0] < 800
                          and re.fullmatch(r"\d{1,2}[:：]\d{2}", l[2].replace(" ", ""))), None)
            logic = "".join(l[2].replace(" ", "") for l in sorted(band, key=lambda l: l[1])
                            if l[0] >= 800)
            rows.append({"name": nl[2].replace(" ", ""), "code": code,
                         "boards": boards or "--", "pct": pct,
                         "time": (ztime or "--").replace("：", ":"), "logic": logic})
        # 4) 校验: 代码/涨跌幅齐全; 区域代码数=行数(漏行检测)
        bad = [r["name"] for r in rows if not r["code"] or not r["pct"]]
        if bad:
            return None, None, f"theme {tname}: rows missing code/pct: {bad}"
        region_codes = sum(1 for l in seg if l[1] > header_y + 20 and l[0] < 200
                           and re.fullmatch(r"\d{6}", l[2].replace(" ", "")))
        if region_codes != len(rows):
            return None, None, (f"theme {tname}: {region_codes} codes in region "
                                f"but {len(rows)} rows parsed (漏行或错锚)")
        themes.append({"name": tname, "attribution": attribution, "rows": rows})
    return themes, [], None


def render_zt_md(themes, warns):
    out = []
    for th in themes:
        out.append(f"### {th['name']}")
        out.append("")
        if th["attribution"]:
            out.append(f"**归因：** {th['attribution']}")
            out.append("")
        out.append("| 股票名称 | 板数 | 涨跌幅 | 涨停时间 | 上涨逻辑 |")
        out.append("| :-- | :-- | :-- | :-- | :-- |")
        for r in th["rows"]:
            out.append(f"| {r['name']} <br>{r['code']} | {r['boards']} | {r['pct']} "
                       f"| {r['time']} | {r['logic']} |")
        out.append("")
    for wtext in warns:
        out.append(f"<!-- OCR校验警告: {wtext} -->")
    return "\n".join(out).rstrip()


def main():
    # Windows 控制台/重定向默认 GBK, Java ProcessBuilder 按 UTF-8 读会乱码
    # stderr 也要: sys.exit("PARSE_FAIL: ...") 走的是 stderr
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--type", required=True, choices=["wp", "sp", "wjzt", "zt"])
    args = ap.parse_args()
    if not Path(args.image).exists():
        sys.exit(f"image not found: {args.image}")
    if args.type in ("wjzt", "zt"):
        themes, warns, err = parse_zt(args.image)
        if err:
            sys.exit(f"PARSE_FAIL: {err}")
        print(render_zt_md(themes, warns))
        return
    lines = ocr_lines(args.image)
    result, err = parse_breadth(lines, args.image)
    if err:
        # 失败模式闭环: 非0退出+原因, Java 侧不写 md 只告警
        sys.exit(f"PARSE_FAIL: {err}")
    row, warns = result
    kv = parse_overview(lines)
    print(render_wp_md(row, kv, warns))


if __name__ == "__main__":
    main()
