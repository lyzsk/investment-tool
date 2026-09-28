# fill_today_cls.py — 2026-09-28 一次性: Java 传参 bug 致 sp/wjzt OCR 没进 md, 手动补填(数据=裸 OCR, 待 Claude 复核)
# 口径对齐 Java replaceSection: marker 行到下一个 "## " 之间整段替换; 先备份
import shutil
import sys
from pathlib import Path

MD = Path(r"C:\Users\admin\dev\investment-tool\stocks\2026S3\2026-09-28.md")
TMP = Path(r"C:\Users\admin\AppData\Local\Temp")
JOBS = [("## 收评", TMP / "ocr_sp.txt"), ("## 午间涨停分析", TMP / "ocr_wjzt.txt")]


def replace_section(content: str, marker: str, body: str) -> str:
    i = content.index(marker)
    eol = content.index("\n", i)
    nxt = content.find("\n## ", eol + 1)
    end = len(content) if nxt == -1 else nxt
    return content[: eol + 1] + "\n" + body.strip() + "\n" + content[end:]


def main():
    shutil.copy(MD, MD.with_suffix(".md.bak_0928_cls"))
    text = MD.read_text(encoding="utf-8")
    for marker, f in JOBS:
        body = f.read_text(encoding="utf-8").strip()
        if not body:
            sys.exit(f"{f} 为空, 拒绝写")
        text = replace_section(text, marker, body)
        print(f"已填 {marker} <- {f.name} ({len(body)}B)")
    MD.write_text(text, encoding="utf-8")
    print("写盘完成, 备份:", MD.with_suffix(".md.bak_0928_cls"))


if __name__ == "__main__":
    main()
