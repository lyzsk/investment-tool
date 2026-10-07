# fix_spacing.py — 批量修正 md 标题前后空行(2026-10-07, 32B 追加无尾空行事故修复)
# 规则: 正文→标题 / 标题→正文 之间必须恰好一个空行; 标题→标题不加; 3+连空行压缩为1; 幂等
# 用法: scripts/venv/Scripts/python.exe -X utf8 scripts/md/fix_spacing.py   (cwd=项目根, 零参数)
#       扫描范围: md/ + skills/ + docs/ 全部 .md; 自动挂 PostToolUse hook(每次 Edit/Write 后触发)
import pathlib, re, sys
sys.stdout.reconfigure(encoding="utf-8")
fixed = 0
for f in sorted(list(pathlib.Path("md").rglob("*.md")) + list(pathlib.Path("skills").rglob("*.md")) + list(pathlib.Path("docs").rglob("*.md"))):
    try: lines = f.read_text(encoding="utf-8").split("\n")
    except Exception: continue
    out = []
    for i, ln in enumerate(lines):
        is_h = re.match(r'^#{1,4} ', ln)
        if out:
            prev = out[-1]
            prev_h = re.match(r'^#{1,4} ', prev)
            if is_h and prev.strip() and not prev_h:
                out.append("")            # 正文→标题 补空行
            elif not is_h and ln.strip() and prev_h and not is_h:
                out.append("")            # 标题→正文 补空行
        out.append(ln)
    # 压缩 3+ 连空行 → 1
    compressed = []
    for ln in out:
        if ln == "" and compressed and compressed[-1] == "" and len(compressed) >= 2 and compressed[-2] == "":
            continue
        compressed.append(ln)
    new = "\n".join(compressed)
    if new != "\n".join(lines):
        f.write_text(new, encoding="utf-8")
        fixed += 1
print(f"修正 {fixed} 个文件")
