# -*- coding: utf-8 -*-
"""line_dirs.py — 账本目录命名(10/25 用户令统一改名: paper v3 → paper line, 实盘线 → live line; 目录前缀 v3_ 废除)
  live line:  线号 live_<skill>  → 目录 live_<skill>
  paper line: 线号 <id>(zhiying / tudou …) → 目录 paper_<id>
"""
from pathlib import Path


def ldir(lid):
    """线号 → 目录名"""
    lid = str(lid)
    return lid if lid.startswith(("live_", "paper_")) else "paper_" + lid


def lid_of(name):
    """目录名 → 线号"""
    name = str(name)
    return name[6:] if name.startswith("paper_") else name


def line_dirs(day, sub=""):
    """某天(或回放日)目录下全部账本目录(live_* + paper_*); sub = 目录下的相对路径(如 "state.json"), 给了就返回那些文件"""
    day = Path(day)
    out = sorted([*day.glob("live_*"), *day.glob("paper_*")])
    out = [p for p in out if p.is_dir()]
    if sub:
        out = [p / sub for p in out if (p / sub).exists()]
    return out
