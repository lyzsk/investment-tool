#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_profile_index.py — persona/profile.md → persona/profile_index.md(链改造 F, 2026-10-13 建)

定位(照 gen_rules_index.mjs 思路): 导师画像不删内容做精简版, 而是加目录, 由链驱动器按步机械注入。
  - 节划分/行号/大小/sha8 = 机械(本脚本解析标题; 无子标题的超长节按行切片 ≤6KB, 不切断行)
  - 「讲什么」「适用步骤 02/03/04/05/06」「优先级」「核心摘要(2~3KB)」= 一次 claude -p 辅助标注, 结果落盘在索引表里可复查
  - 画像 ≤8KB(tzzb 机械画像 3KB 级)不调模型: 全部节标全步骤, 不另做摘要(注入=全文)
  - 增量: 重跑时(节标题, sha8)未变的节复用旧标注, 只有新/改过的节才调模型; --refresh 全量重标
驱动器侧(run_chain.py, env CHAIN_PROFILE_INDEX=1): 按(节标题, sha8)在当前 profile.md 里重新定位,
  改过的节自动跳过+告警(不会注入过期行号的内容), 所以 distill 改了 profile.md 后不重跑本脚本也不会注入错位原文。
用法:
  scripts/venv/Scripts/python.exe -X utf8 scripts/md/gen_profile_index.py --skill taoge [--refresh] [--no-llm]
  scripts/venv/Scripts/python.exe -X utf8 scripts/md/gen_profile_index.py --all          # 14 条股票链 skill(不含转债链 buchitudou0)
出口: 0=ok 1=某 skill 失败(模型标注失败时不写文件, 旧索引保留)
"""
import argparse, hashlib, json, re, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHUNK = 6000          # 无子标题的超长节切片上限(字节)
SMALL = 8000          # 画像总大小 ≤ 此值 = 不调模型, 全注入
STEPS = ("02", "03", "04", "05", "06")
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import mentors  # noqa: E402  10/17 二B-4: 导师登记表
STOCK_SKILLS = [m for m in mentors.ids() if m != "buchitudou0"]   # 股票链 = 全体链去掉转债链
HEAD_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$")


def _b(s):
    return len(s.encode("utf-8"))


def parse_sections(text):
    """profile.md → [{title, start, end(含), text, bytes, sha8}] (行号 1 起)。驱动器也 import 本函数(同一口径定位)。
    父标题(正文为空、紧跟更深一级子标题)不单列; 首个标题前的非空正文=「卷首」; 超长节按行切片"""
    lines = [l.rstrip("\r") for l in text.split("\n")]
    heads = [(i, len(m.group(1)), m.group(2)) for i, l in enumerate(lines) if (m := HEAD_RE.match(l))]
    raw = []
    if heads and any(l.strip() for l in lines[:heads[0][0]]):
        raw.append(("卷首", 0, heads[0][0] - 1, 9))
    if not heads:
        raw.append(("全文", 0, len(lines) - 1, 9))
    for k, (i, lv, title) in enumerate(heads):
        j = heads[k + 1][0] - 1 if k + 1 < len(heads) else len(lines) - 1
        body_empty = not any(l.strip() for l in lines[i + 1:j + 1])
        if body_empty and k + 1 < len(heads) and heads[k + 1][1] > lv:
            continue   # 纯父标题
        raw.append((title.replace("|", "／")[:60], i, j, lv))
    while raw and raw[-1][2] >= raw[-1][1] and not any(l.strip() for l in lines[raw[-1][1]:raw[-1][2] + 1]):
        raw.pop()
    out = []
    for title, i, j, _ in raw:
        while j > i and not lines[j].strip():
            j -= 1   # 去尾部空行(行号更紧)
        seg = lines[i:j + 1]
        if _b("\n".join(seg)) <= CHUNK:
            parts = [(i, j)]
        else:
            parts, s0, acc = [], i, 0
            for n in range(i, j + 1):
                lb = _b(lines[n]) + 1
                if acc and acc + lb > CHUNK:
                    parts.append((s0, n - 1)); s0, acc = n, 0
                acc += lb
            parts.append((s0, j))
        for k, (a, z) in enumerate(parts):
            t = "\n".join(lines[a:z + 1])
            out.append({"title": title if len(parts) == 1 else f"{title} ({k + 1}/{len(parts)})",
                        "start": a + 1, "end": z + 1, "text": t, "bytes": _b(t),
                        "sha8": hashlib.sha256(t.encode("utf-8")).hexdigest()[:8]})
    return out


ROW_RE = re.compile(r"^\| (S\d+) \| (.*?) \| (.*?) \| L(\d+)-(\d+) \| ([\d.]+) \| ([\d,]+|—) \| (\d) \| ([0-9a-f]{8}) \|$")


def read_index(path):
    """profile_index.md → (meta{sha12}, summary, rows[{id,title,about,start,end,steps,prio,sha8}]); 不存在=None"""
    p = Path(path)
    if not p.exists():
        return None
    t = p.read_text(encoding="utf-8")
    m = re.search(r"sha12=([0-9a-f]{12})", t)
    note = re.search(r"^> 标注来源: (.*?); 节划分", t, re.M)
    s = re.search(r"^## 核心摘要\n([\s\S]*?)\n## 目录", t, re.M)
    rows = []
    for l in t.splitlines():
        r = ROW_RE.match(l)
        if r:
            rows.append({"id": r.group(1), "title": r.group(2), "about": r.group(3), "start": int(r.group(4)),
                         "end": int(r.group(5)), "steps": [] if r.group(7) == "—" else r.group(7).split(","),
                         "prio": int(r.group(8)), "sha8": r.group(9)})
    return {"sha12": m.group(1) if m else None, "note": note.group(1) if note else ""}, (s.group(1).strip() if s else ""), rows


LABEL_PROMPT = """你是投资决策链的画像编目员。下面是导师「{name}」(skill={skill})的人格画像 profile.md 按节切开后的内容。决策链各步含义:
- 02 定市况/方向: 市况三态判定框架、情绪周期、轮动/方向认知
- 03 多空辩论: 可被多/空方引用的核心信念、认知偏差、经验记忆
- 04 交易方案(选股): 选股方法、买点偏好、熟票/池子、仓位习惯
- 05 风控: 禁区、认知偏差的代价、亏损应对/止损习惯、仓位上限习惯
- 06 终裁(下单): 买卖点执行、时刻纪律、仓位、失效条件
任务(不要调用任何工具, 直接输出一个 ```json 代码块):
1. 为下列每节给 about(≤40 字, 说清这节讲什么)、steps(适用步骤子集, 只标真正会改变该步决策的步; 修订记录/身份背景/与交易决策无关的给 []; 每节一般 1~3 个步)、prio(1=该步必读 2=有用 3=边缘)。
   约束: 同一步所有 steps 含它的节原文合计尽量 ≤25KB(各节 KB 已标注), 超了就把边缘节的步去掉。
2. summary: 2000~3000 字的「核心摘要」, 分四小节「风格」「打法」「仓位习惯」「禁区」, 只写画像里有证据的内容(可引节编号), 不确定的标"待验证"。这段会常驻每一步 prompt, 要高密度。
输出格式:
```json
{{"summary":"...","sections":[{{"id":"S01","about":"...","steps":["02","04"],"prio":1}}]}}
```
各节如下(超长节只给开头摘录):
{body}"""

SCHEMA = {"type": "object", "required": ["summary", "sections"], "properties": {
    "summary": {"type": "string"},
    "sections": {"type": "array", "items": {"type": "object", "required": ["id", "about", "steps", "prio"]}}}}


def build(skill, refresh=False, no_llm=False):
    pdir = ROOT / f"skills/{skill}-skill/persona"
    pf, out = pdir / "profile.md", pdir / "profile_index.md"
    raw = pf.read_bytes()
    text = raw.decode("utf-8")
    secs = parse_sections(text)
    for k, s in enumerate(secs):
        s["id"] = f"S{k + 1:02d}"
    total = len(raw)
    old = None if refresh else read_index(out)
    old_map = {(r["title"], r["sha8"]): r for r in (old[2] if old else [])}
    orig = (old[0].get("note") or "").split("原标注=")[-1] if old else ""
    summary, model_note = (old[1] if old else ""), "复用旧标注" + (f", 原标注={orig}" if orig else "")
    if total <= SMALL:
        for s in secs:
            s.update(about=s["text"].split("\n", 1)[-1].strip().replace("\n", " ").replace("|", "／")[:40] or s["title"],
                     steps=list(STEPS), prio=1)
        summary = f"(画像全文仅 {total / 1024:.1f}KB, 不另做摘要: 驱动器各步注入全部节原文)"
        model_note = "机械(画像 ≤8KB, 全节全步注入, 未调模型)"
    else:
        need = [s for s in secs if (s["title"], s["sha8"]) not in old_map]
        for s in secs:
            o = old_map.get((s["title"], s["sha8"]))
            if o:
                s.update(about=o["about"], steps=o["steps"], prio=o["prio"])
        if need and no_llm:
            for s in need:
                s.update(about="(未标注: --no-llm)", steps=[], prio=3)
            model_note = f"--no-llm: {len(need)} 节未标注(只按需补读)"
        elif need:
            sys.path.insert(0, str(ROOT / "scripts/lib"))
            from claude_call import call, LEAN_ARGS
            name = skill
            try:
                h = re.search(r"^#\s+(.+)$", text, re.M)
                name = h.group(1)[:30] if h else skill
            except Exception:
                pass
            parts = []
            for s in secs:
                body = s["text"] if s["bytes"] <= 3000 else s["text"][:1200] + "\n…(截断)"
                parts.append(f"=== {s['id']} 「{s['title']}」 L{s['start']}-{s['end']} {s['bytes'] / 1024:.1f}KB ===\n{body}")
            prompt = LABEL_PROMPT.format(name=name, skill=skill, body="\n\n".join(parts))
            res = None
            for attempt in (1, 2):
                res = call(prompt, tag=f"profile-index:{skill}", timeout=1800, permission="default",
                           json_schema=SCHEMA, use_rotation=True,
                           extra_args=LEAN_ARGS + ["--tools", ""])   # 10/15 A13①: 纯标注不需要工具
                if res.ok:
                    got = {x["id"]: x for x in res.parsed["sections"]}
                    miss = [s["id"] for s in secs if s["id"] not in got]
                    ln = len(res.parsed["summary"])
                    if not miss and 800 <= ln <= 4500:
                        break
                    res.ok, res.errors = False, [f"缺节 {miss[:10]} / 摘要 {ln} 字"]
                print(f"[{skill}] 标注第 {attempt} 次失败: {res.errors[:3]}")
            if not res.ok:
                print(f"[{skill}] 模型标注失败, 不写文件(旧索引保留)")
                return False
            for s in secs:
                x = got[s["id"]]
                s.update(about=str(x["about"]).replace("|", "／").replace("\n", " ")[:60],
                         steps=[st for st in STEPS if st in [str(v) for v in (x.get("steps") or [])]],
                         prio=min(3, max(1, int(x.get("prio") or 2))))
            summary = res.parsed["summary"].strip()
            model_note = f"claude -p 标注 {len(need)}/{len(secs)} 节(${res.cost_usd:.2f}, {res.duration_s:.0f}s)"
    for s in secs:   # 机械覆盖: 元指令(任务优先/禁反问/哨兵纪律)每步必注入——F 下模型不再整读 profile.md, 不能丢它
        if "元指令" in s["title"]:
            s.update(steps=list(STEPS), prio=1)
    per_step = {st: sum(s["bytes"] for s in secs if st in s["steps"]) for st in STEPS}
    lines = [f"# profile_index.md — {skill} 导师画像目录(链改造 F; 生成于 {datetime.now():%Y-%m-%d %H:%M})",
             f"> 源: skills/{skill}-skill/persona/profile.md sha12={hashlib.sha256(raw).hexdigest()[:12]} · "
             f"{text.count(chr(10)) + 1} 行 · {total / 1024:.1f}KB · {len(secs)} 节(超长节按行切片≤{CHUNK // 1000}KB)",
             "> 用途: 链驱动器开 `CHAIN_PROFILE_INDEX=1` 时, 按当前步把「适用步骤」含本步的节原文机械拼进 prompt"
             "(按 节+sha8 在当前 profile.md 重新定位, 改过的节跳过+告警); 其余节模型按行号补读。默认关闭=不读本文件。",
             f"> 标注来源: {model_note}; 节划分/行号/KB/sha8=机械。重跑: `scripts/venv/Scripts/python.exe -X utf8 scripts/md/gen_profile_index.py --skill {skill}`(未变节复用标注)",
             "> 各步注入量(全部适用节原文合计, 驱动器另有单步上限): " + " / ".join(f"{k} {v / 1024:.1f}KB" for k, v in per_step.items()),
             "", "## 核心摘要", summary, "", "## 目录",
             "| 编号 | 节 | 讲什么 | 行 | KB | 适用步骤 | 优先 | sha8 |", "|---|---|---|---|---|---|---|---|"]
    for s in secs:
        lines.append(f"| {s['id']} | {s['title']} | {s['about']} | L{s['start']}-{s['end']} | {s['bytes'] / 1024:.1f} | "
                     f"{','.join(s['steps']) or '—'} | {s['prio']} | {s['sha8']} |")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    chk = read_index(out)
    assert chk and len(chk[2]) == len(secs), "索引回读行数不符(表格转义问题)"
    print(f"[{skill}] → {out.relative_to(ROOT)}: {len(secs)} 节, {model_note}, 注入量 {per_step}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="忽略旧标注全量重标")
    ap.add_argument("--no-llm", action="store_true", help="不调模型(新/改节标为未标注)")
    a = ap.parse_args()
    skills = STOCK_SKILLS if a.all else [a.skill] if a.skill else ap.error("需 --skill 或 --all")
    ok = all([build(s, a.refresh, a.no_llm) for s in skills])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
