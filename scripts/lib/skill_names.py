# -*- coding: utf-8 -*-
"""skill_names.py — skill 英文 id → 中文名(10/24 用户: skill 都是英文名, 看 xxx-skill/SKILL.md 确认中文名; 推送格式 "<中文名>skill: <内容>")

取法: SKILL.md 第一个 "# xxx-skill · <中文名>(…)" 标题里 · 后面那段, 去掉括号和"人格画像 / 行为画像 / 决策规则"这类后缀;
      取出来不像名字(为空 / 太长 / 是描述)就退回导师登记表的名字(md 小节名)
用法: import skill_names as SN; SN.cn("zhiyingjuexin") → "芷影攫心"; SN.tag("zhiyingjuexin") → "芷影攫心skill"
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_C = {}
SUFFIX = re.compile(r"(人格画像|行为画像|画像|与|决策规则|规则|实验|复盘|\s*skill)+$", re.I)
FIXED = {"fage": "发哥"}   # SKILL.md 标题是描述不是名字的, 在这里固定


def _from_skill_md(sid):
    f = ROOT / "skills" / f"{sid}-skill" / "SKILL.md"
    if not f.exists():
        return ""
    for l in f.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^#\s+\S+-skill\s*·\s*(.+)$", l)
        if m:
            s = re.split(r"[（(]", m.group(1))[0].strip()
            return SUFFIX.sub("", s).strip()
    return ""


def cn(sid):
    if sid in _C:
        return _C[sid]
    if sid in FIXED:
        return FIXED[sid]
    reg = ""
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "lib"))
        import mentors as MT
        e = MT.get(sid) or {}
        reg = (e.get("name") or e.get("display") or "").strip()
    except Exception:   # noqa: BLE001
        pass
    s = _from_skill_md(sid)
    bad = not s or len(s) > 10 or any(k in s for k in ("高手", "转债", "人格", "画像"))
    _C[sid] = reg if bad and reg else (s or reg or sid)
    return _C[sid]


def tag(sid):
    return f"{cn(sid)}skill"


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for d in sorted((ROOT / "skills").glob("*-skill")):
        sid = d.name[:-6]
        print(f"{sid:<18} SKILL.md→{_from_skill_md(sid)!r:<22} 用: {tag(sid)}")
