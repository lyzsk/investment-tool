# reset_for_new_skill.py — 新 skill 口径归零器(2026-09-28 用户立法: 凡新加 skill 内容全部重跑)
# 用户说"开始"后执行: 归档 persona + 清 distill 账本。幂等, 可重复跑; results/ 产物不动(复用)
# 前置已就绪(无需本脚本): ①backfill_taoge.py MD_NEW_MARKER 已 bump 为 "**持仓逆向"(旧 md 自动重新合成)
#                       ②回填/清扫队列已改倒序(最新日期先跑, 临时能用上)
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PERSONA = ROOT / "skills" / "taoge-skill" / "persona"
DISTILL_STATE = ROOT / "scripts" / "distill_state.json"
STAMP = datetime.now().strftime("%Y%m%d_%H%M")


def main():
    dry = "--apply" not in sys.argv
    # 1) persona 归档(不清空目录本身, 留空壳: taoge-skill 引用路径不变, 内容从零沉淀)
    archive = PERSONA.parent / f"persona_archive_{STAMP}"
    files = [f for f in PERSONA.glob("*.md")] if PERSONA.is_dir() else []
    print(f"persona 文件 {len(files)} 个 -> {archive}" + (" [DRY]" if dry else ""))
    if not dry and files:
        archive.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.move(str(f), archive / f.name)
    # 2) distill 账本归零(旧账本随 persona 一起归档, 可追溯)
    try:
        old = json.loads(DISTILL_STATE.read_text(encoding="utf-8")).get("done", [])
    except (OSError, json.JSONDecodeError):
        old = []
    print(f"distill 账本 {len(old)} 天 -> 归零" + (" [DRY]" if dry else ""))
    if not dry:
        if old:
            (ROOT / "scripts" / f"distill_state_archive_{STAMP}.json").write_text(
                json.dumps({"done": old}, ensure_ascii=False, indent=1), encoding="utf-8")
        DISTILL_STATE.write_text('{"done": []}', encoding="utf-8")
    print("完成。下一步: 删 scripts/PAUSE 并重启 backfill_taoge.py --ignore-window"
          "(倒序: 从最新交易日往回, md 合成(新 skill)→distill 逐日咬合)")


if __name__ == "__main__":
    main()
