# cls 图批量填 md (固化脚本, 2026-09-24 晚; 明天 Java sys_job 的蓝本)
# 用法:
#   python fill_cls_md.py --from 2026-07-01 --to 2026-09-30            # 只填空小节/模板/已带OCR标记的
#   python fill_cls_md.py --from 2026-07-01 --to 2026-09-30 --overwrite --backup backups/xxx
# 规则(与 Java 侧约定):
#   - 映射: wp→## 午评, wjzt→## 午间涨停分析, sp→## 收评, zt→## 涨停分析
#   - Java 默认跳过"非空且非空表模板"的小节(保护手工内容, 不需要任何标记行)
#   - cls_image_ocr 返回 PARSE_FAIL -> 不写 md, 记入日志告警
#   - 图不存在 -> 跳过(幂等)
import argparse, datetime, re, shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cls_image_ocr as C

ROOT = Path(__file__).resolve().parents[2]             # investment-tool/(10/2 迁入 scripts/cls/)
CLS_DIR = ROOT / "downloads" / "cls"
STOCKS = ROOT / "stocks"

SECTION = {"wp": "午评", "wjzt": "午间涨停分析", "sp": "收评", "zt": "涨停分析"}


def quarter_dir(date):
    """yyyy-mm-dd -> stocks/2026SX"""
    m = int(date[5:7])
    return f"2026S{(m - 1) // 3 + 1}"


def find_section(lines, name):
    """返回 (start_idx, end_idx) : ## name 行号 到 下一个 ## 前行号(不含), 没有则 (None, None)"""
    start = None
    for i, ln in enumerate(lines):
        if ln.rstrip() == f"## {name}":
            start = i
            break
    if start is None:
        return None, None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return start, end


def body_state(body_lines):
    """empty=全空白 | template=13档空表模板 | manual=非空内容(默认跳过)"""
    text = "\n".join(body_lines)
    if not text.strip():
        return "empty"
    if "大于+8%" in text and not re.search(r"\d+\s*(?:家|<br>)", text):
        return "template"
    return "manual"


def ocr_one(img_path, typ):
    """调 cls_image_ocr 对应解析器, 返回 (md_text, err)"""
    if typ in ("wp", "sp"):
        lines = C.ocr_lines(img_path)
        result, err = C.parse_breadth(lines, img_path)
        if err:
            return None, err
        row, warns = result
        kv = C.parse_overview(lines)
        return C.render_wp_md(row, kv, warns), None
    themes, warns, err = C.parse_zt(img_path)
    if err:
        return None, err
    return C.render_zt_md(themes, warns), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="dfrom", required=True)
    ap.add_argument("--to", dest="dto", required=True)
    ap.add_argument("--overwrite", action="store_true", help="连人工内容也覆盖(需 --backup)")
    ap.add_argument("--backup", help="覆盖前先整体备份 stocks 到该目录")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if args.overwrite and not args.backup:
        sys.exit("--overwrite 必须配 --backup")
    if args.backup:
        bdir = Path(args.backup)
        if not bdir.exists():
            shutil.copytree(STOCKS, bdir / "stocks")
            print(f"[backup] {STOCKS} -> {bdir / 'stocks'}")

    d0 = datetime.date.fromisoformat(args.dfrom)
    d1 = datetime.date.fromisoformat(args.dto)
    stats = {"fill": 0, "skip_manual": 0, "skip_noimg": 0, "fail": 0, "nomd": 0}
    fails = []

    day = d0
    while day <= d1:
        date = day.isoformat()
        day += datetime.timedelta(days=1)
        cls_dir = CLS_DIR / date.replace("-", ".")
        md_path = STOCKS / quarter_dir(date) / f"{date}.md"
        if not md_path.exists():
            if cls_dir.exists():
                print(f"[nomd] {date}")
                stats["nomd"] += 1
            continue
        lines = md_path.read_text(encoding="utf-8").splitlines()
        changed = False
        for typ, sec in SECTION.items():
            imgs = sorted(cls_dir.glob(f"cls_{typ}_*.jpg")) if cls_dir.exists() else []
            if not imgs:
                stats["skip_noimg"] += 1
                continue
            start, end = find_section(lines, sec)
            if start is None:
                print(f"[nosec] {date} 无 ## {sec} 小节, 跳过")
                continue
            state = body_state(lines[start + 1:end])
            if state == "manual" and not args.overwrite:
                stats["skip_manual"] += 1
                print(f"[skip] {date} ## {sec} 有人工内容")
                continue
            md_text, err = ocr_one(imgs[0], typ)
            if err:
                stats["fail"] += 1
                fails.append(f"{date} {typ}: {err}")
                print(f"[FAIL] {date} {typ}: {err}")
                continue
            new_body = ["", *md_text.splitlines(), ""]
            lines[start + 1:end] = new_body
            changed = True
            stats["fill"] += 1
            print(f"[fill] {date} ## {sec} <- {imgs[0].name}")
        if changed:
            md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n== 汇总 ==", stats)
    if fails:
        print("== PARSE_FAIL 清单(需人工看) ==")
        for f in fails:
            print(" ", f)


if __name__ == "__main__":
    main()
