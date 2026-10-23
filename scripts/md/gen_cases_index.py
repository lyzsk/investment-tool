# -*- coding: utf-8 -*-
"""gen_cases_index.py — cases.md → cases_index.md(案例目录; 10/22 晚用户令: 画像 / 规则 / 案例都要有索引, 不论现在多小, 将来量级会很大)

目录一行 = cases.md 里一个 ## / ### 小节: 行号区间 + 标题 + 表格 / 列表条数 + 小节里出现的票名(前 12 个)
各导师 cases.md 写法不一(刘忆青 = 每案一个 ###; 土豆 = 大表格; bank / nasdaq = 每日一个 ###), 所以只按标题切, 票名从标题和表格首列抽
用法: python gen_cases_index.py --skill buchitudou0 | --all     (幂等; check_md_daily 在 cases.md 比索引新时自动重跑)
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sections(lines):
    secs, cur = [], None
    for i, l in enumerate(lines, 1):
        m = re.match(r"^(#{2,3}) (.+)$", l)
        if m:
            if cur:
                cur["end"] = i - 1
                secs.append(cur)
            cur = {"lv": len(m.group(1)), "title": m.group(2).strip(), "start": i, "rows": 0, "names": []}
            continue
        if cur is None:
            continue
        if l.startswith("|") and not re.match(r"^\|\s*:?-", l) and "股票" not in l and "日期" not in l[:12]:
            cur["rows"] += 1
            c = [x.strip() for x in l.strip().strip("|").split("|")]
            for x in c[:3]:
                n = re.sub(r"<br>.*|\(.*|（.*", "", x).strip()
                if re.match(r"^[一-龥A-Z*]{2,8}(转债|转2|ETF)?$", n) and not re.match(r"^(首板|买|卖|是|否|合计)$", n):
                    if n not in cur["names"]:
                        cur["names"].append(n)
                    break
        elif l.startswith("- "):
            cur["rows"] += 1
    if cur:
        cur["end"] = len(lines)
        secs.append(cur)
    return secs


def build(skill):
    src = ROOT / "skills" / f"{skill}-skill" / "persona" / "cases.md"
    if not src.exists():
        return None
    lines = src.read_text(encoding="utf-8").splitlines()
    secs = sections(lines)
    out = [f"# cases_index.md — {skill} 案例目录(生成于 {dt.datetime.now():%Y-%m-%d %H:%M}; 源 cases.md {len(lines)} 行 / {src.stat().st_size // 1024} KB, {len(secs)} 个小节)",
           "> 用法: 先看这张目录定位, 再按行号读 cases.md 对应区间; 票名列只抽了标题和表格首列, 不全时用 grep 搜票名", ""]
    for s in secs:
        ind = "  " if s["lv"] == 3 else ""
        nm = ("｜票: " + "、".join(s["names"][:12]) + ("…" if len(s["names"]) > 12 else "")) if s["names"] else ""
        out.append(f"{ind}- L{s['start']}-{s['end']} {s['title']}｜{s['rows']} 条{nm}")
    dst = src.with_name("cases_index.md")
    dst.write_text("\n".join(out) + "\n", encoding="utf-8")
    return len(secs), dst


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    sks = [p.name[:-6] for p in sorted((ROOT / "skills").glob("*-skill")) if (p / "persona" / "cases.md").exists()] if a.all else [a.skill]
    for s in sks:
        r = build(s)
        print(s, "无 cases.md" if r is None else f"{r[0]} 个小节 → {r[1].relative_to(ROOT)}")


if __name__ == "__main__":
    main()
