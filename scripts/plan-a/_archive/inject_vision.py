# vision JSON -> md ### 桃哥 下插入 #### 画面 (2026-09-24 晚)
# 文字+视频联合表述设计:
#   #### 转写(ASR)在上, #### 画面(视觉)在中, #### 解读(LLM综合)在下
#   画面的学习价值 = ①口述未提的票(沉默信息: 他手上在看/持有的) ②与口述互证的票 ③板块/指数精确点位
# 可靠性规则:
#   - 股票名: VLM ≥2帧投票 或 (1帧 + OCR同帧确认)
#   - 代码: 只采信 OCR 同帧共现(名称与代码同屏)投票; VLM 单独给的代码不采信(实测会错)
#   - 价位/涨跌幅: 取该名出现帧里时间戳最大的一帧, 标注为"参考"(数值 VLM 偶有位数误差)
# 用法: python inject_vision.py [--dates 2026-07-01:2026-09-30]
import json, re, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VISION_DIR = ROOT / "downloads" / "vision"
ANALYSIS_DIR = ROOT / "downloads" / "analysis"
Q3_MAP = ROOT / "downloads" / "q3_videos.json"
STOCKS = ROOT.parent.parent / "stocks"

HEADER = "#### 画面"
# A股(60/00/30/68) + 北交所(43/83/87/92) 号段
CODE_RE = re.compile(r"^(?:60|00|30|68|43|83|87|92)\d{4}$")


def norm_name(t):
    t = re.sub(r"^[·\s]+", "", str(t or "").strip())
    return t


def frame_ts(tag):
    m = re.search(r"([\d.]+)", tag)
    return float(m.group(1)) if m else 0.0


def aggregate(vis):
    """vlm+ocr 聚合 -> [{name, code, price, pct, frames, ocr_ok}]"""
    vlm = vis.get("vlm") or {}
    ocr = vis.get("ocr") or {}
    # OCR: 每帧的 token 文本集; 名称-代码同帧共现投票
    ocr_frame_texts = {}
    for tag, items in ocr.items():
        if isinstance(items, list):
            ocr_frame_texts[tag] = [str(it.get("text", "")) for it in items if isinstance(it, dict)]
    # VLM 按名聚帧
    by_name = {}
    for tag, payload in vlm.items():
        entries = payload if isinstance(payload, list) else [payload]
        for e in entries:
            if not isinstance(e, dict) or not e.get("股票名"):
                continue
            name = norm_name(e["股票名"])
            if len(name) < 2:
                continue
            by_name.setdefault(name, []).append((tag, e))
    out = []
    for name, frs in by_name.items():
        # OCR 确认: 名称出现在任一 OCR 帧
        ocr_frames = [tag for tag, toks in ocr_frame_texts.items()
                      if any(name in t for t in toks)]
        ocr_ok = bool(ocr_frames)
        if len(frs) < 2 and not ocr_ok:
            continue  # 单帧无 OCR 佐证 = 幻觉高发区, 弃
        # 代码: OCR 同帧共现投票(名称所在帧里的6位数字)
        # 约束: A股/北交所号段前缀; 得票>=2 且严格多于第二名(自选股页同屏多只票, 票数容易打平)
        code_votes = Counter()
        for tag in ocr_frames:
            for t in ocr_frame_texts[tag]:
                for c in re.findall(r"(?<!\d)(\d{6})(?!\d)", t):
                    if CODE_RE.match(c):
                        code_votes[c] += 1
        top2 = code_votes.most_common(2)
        code = (top2[0][0] if top2 and top2[0][1] >= 2
                and (len(top2) == 1 or top2[0][1] > top2[1][1]) else None)
        # 价位/涨跌幅: 时间戳最大帧, 要求数值型
        tag, e = max(frs, key=lambda te: frame_ts(te[0]))
        price = e.get("最新价") if isinstance(e.get("最新价"), (int, float)) else None
        pct = e.get("涨跌幅%") if isinstance(e.get("涨跌幅%"), (int, float)) else None
        out.append({"name": name, "code": code, "price": price, "pct": pct,
                    "frames": len(frs), "ocr_ok": ocr_ok})
    out.sort(key=lambda r: -r["frames"])
    return out


def render(rows, spoken_names):
    增量 = [r for r in rows if r["name"] not in spoken_names and not is_index(r)]
    互证 = [r for r in rows if r["name"] in spoken_names and not is_index(r)]
    指数 = [r for r in rows if is_index(r)]
    lines = [HEADER, ""]
    if 增量:
        lines.append("- **口述未提**: " + " · ".join(fmt(r) for r in 增量))
    if 互证:
        lines.append("- **画面互证**: " + " · ".join(fmt(r) for r in 互证))
    if 指数:
        lines.append("- **板块指数**: " + " · ".join(fmt(r) for r in 指数))
    return "\n".join(lines)


def is_index(r):
    n = r["name"]
    return ("指数" in n or "板块" in n or (r["code"] or "").startswith("88")
            or n in ("上证", "沪指", "大盘") or len(n) <= 2)


def fmt(r):
    # 板块/指数行不渲染代码(同屏共现投票对成分股页不可靠)
    s = r["name"] + (f"({r['code']})" if r["code"] and not is_index(r) else "")
    if r["price"] is not None:
        s += f" {r['price']:g}"
    if r["pct"] is not None:
        s += f"({r['pct']:+.2f}%)"
    return s


def inject(md_path, section_md):
    lines = md_path.read_text(encoding="utf-8").splitlines()
    # 找 ### 桃哥 块
    t0 = next((i for i, l in enumerate(lines) if l.rstrip() == "### 桃哥"), None)
    if t0 is None:
        return False, "无 ### 桃哥"
    t1 = next((j for j in range(t0 + 1, len(lines))
               if lines[j].startswith("### ") or lines[j].startswith("## ")), len(lines))
    block = lines[t0:t1]
    # 已有 #### 画面 -> 替换其 body(幂等); 否则插到 #### 解读 前(无解读则块尾)
    v0 = next((i for i, l in enumerate(block) if l.startswith("#### 画面")), None)
    if v0 is not None:
        v1 = next((j for j in range(v0 + 1, len(block)) if block[j].startswith("#### ")),
                  len(block))
        block[v0:v1] = section_md.splitlines() + [""]
        lines[t0:t1] = block
        how = "replace"
    else:
        j0 = next((i for i, l in enumerate(block) if l.startswith("#### 解读")), None)
        pos = t0 + (j0 if j0 is not None else len(block))
        lines[pos:pos] = section_md.splitlines() + [""]
        how = "insert"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True, how


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    q3 = json.load(open(Q3_MAP, encoding="utf-8"))
    stats = {"insert": 0, "replace": 0, "skip": 0}
    for date, bvid in sorted(q3.items()):
        vf = VISION_DIR / f"{bvid}.json"
        md_path = STOCKS / f"2026S3" / f"{date}.md"
        if not vf.exists() or not md_path.exists():
            stats["skip"] += 1
            continue
        vis = json.load(open(vf, encoding="utf-8"))
        if not vis.get("vlm"):
            stats["skip"] += 1
            print(f"[skip] {date} {bvid} 无 vlm 数据")
            continue
        rows = aggregate(vis)
        if not rows:
            stats["skip"] += 1
            print(f"[skip] {date} {bvid} 聚合为空")
            continue
        spoken = set()
        af = ANALYSIS_DIR / f"{date}.json"
        if af.exists():
            ana = json.load(open(af, encoding="utf-8"))
            spoken = {m.get("name", "") for m in ana.get("mentions", [])}
        sec = render(rows, spoken)
        ok, how = inject(md_path, sec)
        stats[how if how in ("insert", "replace") else "skip"] += 1
        names = " ".join(r["name"] for r in rows[:6])
        print(f"[{how}] {date} {bvid} 票{len(rows)}: {names}")
    print("== 汇总 ==", stats)


if __name__ == "__main__":
    main()
