# gen_md_checklist.py — results/ ↔ stocks md 回写 一一对应检查表(2026-09-27 用户要速查表)
# 用法: scripts/venv/Scripts/python.exe scripts/backfill_taoge/gen_md_checklist.py
# 产物: scripts/backfill_taoge/md_checklist.md (覆盖重写, 随时重跑取最新)
import datetime as dt
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent.parent
MID = "625315686"
RESULTS = ROOT / "results" / "bilibili" / MID
STOCKS = ROOT / "stocks"
OUT = SCRIPT_DIR / "md_checklist.md"
DISTILL_STATE = SCRIPT_DIR.parent / "distill_state.json"  # 9/28: 账本真实位置 scripts/(backfill_taoge.py 的 SCRIPT_DIR=scripts/)
SKIP = {"2026-09-24": "定稿样板不动"}  # 9/18 手稿 9/27 用户指令已覆盖, 备份 md_backup_2026-09-18_before.md


def load_distilled():
    try:
        return set(json.loads(DISTILL_STATE.read_text(encoding="utf-8")).get("done", []))
    except (OSError, json.JSONDecodeError):
        return set()


def quarter_path(pub_date):
    y, m, _ = pub_date.split("-")
    return STOCKS / f"{y}S{(int(m) - 1) // 3 + 1}" / f"{pub_date}.md"


rows = []
distilled = load_distilled()
for day_dir in sorted(RESULTS.iterdir()):
    if not day_dir.is_dir():
        continue
    pub_date = dt.datetime.strptime(day_dir.name, "%Y.%m.%d").strftime("%Y-%m-%d")
    txts = [f for f in day_dir.glob("BV*.txt")
            if not f.name.endswith((".raw.txt", ".correct.log")) and f.stat().st_size > 0]
    n_txt = len(txts)
    n_full = 0
    for t in txts:
        vj = t.with_name(t.name[:-4] + ".vision.json")
        if vj.exists():
            try:
                if json.loads(vj.read_text(encoding="utf-8")).get("ocr"):
                    n_full += 1
            except Exception:
                pass
    prod = "齐" if n_full and n_full == n_txt else ("部分" if n_txt else "无")
    md = quarter_path(pub_date)
    if pub_date in SKIP:
        st = f"⏭ {SKIP[pub_date]}"
    elif not md.exists():
        st = "➖ 无md(未预建)"
    elif n_full == 0:
        st = "⏳ 等产物"
    else:
        try:
            st = "✅ 新格式" if "**画面增量" in md.read_text(encoding="utf-8", errors="ignore") else "⬜ 旧格式待回写"
        except OSError:
            st = "? 读取失败"
    rows.append((pub_date, n_txt, n_full, prod, st, "🧠" if pub_date in distilled else "·"))

done = sum(1 for r in rows if r[4].startswith("✅"))
todo = sum(1 for r in rows if r[4].startswith("⬜"))
wait = sum(1 for r in rows if r[4].startswith(("⏳", "➖")))
lines = ["# results ↔ md ↔ skill沉淀 检查表", "",
         f"> 生成: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · "
         f"产物目录 {len(rows)} 天 | ✅已回写 {done} | ⬜待回写 {todo} | ⏳/➖ {wait} | 🧠已沉淀 {sum(1 for r in rows if r[5] == '🧠')}",
         "> 重跑更新: `scripts/venv/Scripts/python.exe scripts/backfill_taoge/gen_md_checklist.py`", "",
         "| 日期 | 视频数 | 产物齐 | 产物 | md 状态 | 沉淀 |", "|---|---|---|---|---|---|"]
for r in rows:
    lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} |")
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"{OUT} | total={len(rows)} md_done={done} md_todo={todo} wait={wait} distilled={sum(1 for r in rows if r[5] == chr(129504))}")
