# -*- coding: utf-8 -*-
"""build_distill_pack.py — 蒸馏「素材包」(零 token, 10/17 建, TODO A14②; 参照 scripts/bilibili/build_pack.py 的写 md 素材包)
动机: 蒸馏会话单次读缓存 4~5M(≈80~96 轮工具调用), 大头是模型自己 grep/cat md、翻 rules/profile、找同票历史——全是机械活。
  前移成脚本: 会话先跑本脚本(一次 Bash), 读一份 pack 就能核销+沉淀, 只有 pack 没覆盖的才按索引补读。
内容(信息截止=目标日, 只用 ≤ 目标日的 md):
  ① 当天本人小节全文(md #### 小节)  ② 当日盘面: 收评 + 涨停分析/龙虎榜里与本人同票的行
  ③ 近 5 个交易日本人小节里提到同票的行  ④ 规则: 同票/同名规则全文(按命中数排序, 限长) + 待验证规则索引行(含行号, 供核销挑选)
  ⑤ 画像目录(profile_index.md 的目录表, 压成一行一节)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/md/build_distill_pack.py --skill liuyiqing[,a658,...] --date 2026-10-16[,2026-10-15] [--print]
  skill = tzzb 账本 id(同 skill 名) 或 taoge/qushitiange/lubenyuan
产物: downloads/distill_pack/<yyyy-MM-dd>/<skill>.md(幂等覆盖); stdout 每个 skill 一行 "PACK <skill> <路径> <KB> | 摘要", 末行 JSON:{...}
出口: 0=全部生成(含"当天无小节"的空包) 1=有 skill 失败 2=用法错
自测: --selftest(离线, 用内置样例)
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MD = ROOT / "md"
OUT = ROOT / "downloads" / "distill_pack"
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import mentors  # noqa: E402  10/17 二B-4: 导师登记表(UP 的 md 小节名=name 字段)
UP_HEAD = {m: "#### " + mentors.get(m)["name"] for m in mentors.ids("UP")}
RECENT_N = 5
CAP_RULES, CAP_IDX, CAP_RECENT, CAP_MKT = 15_000, 6_000, 6_000, 6_000   # 字符数(中文≈1 token/字)
NAME_CODE = re.compile(r"([一-龥A-Za-z*]{2,8})\s*[（(](\d{6})[）)]")
RULE_HEAD = re.compile(r"^#{3,4} ([A-Z]{1,2}\d+[a-z]?)\b")


def md_path(d):
    x = dt.date.fromisoformat(d)
    return MD / f"{x.year}S{(x.month - 1) // 3 + 1}" / f"{d}.md"


def _ns(s):
    return re.sub(r"\s+", "", s)


def section(text, head):
    """按标题文字(忽略空白)取小节正文(到下一个同级或更高级标题前); 无=None"""
    level = len(head) - len(head.lstrip("#"))
    want = _ns(head)
    for m in re.finditer(r"^(#{1,6}) (.+?)\s*$", text, re.M):
        if len(m.group(1)) == level and _ns(m.group(0)) == want:
            rest = text[m.end():]
            nxt = re.search(rf"^#{{1,{level}}} ", rest, re.M)
            return rest[:nxt.start()] if nxt else rest
    return None


def head_of(skill):
    if skill in UP_HEAD:
        return UP_HEAD[skill]
    for L in json.loads((ROOT / "scripts" / "tzzb" / "tzzb_ledgers.json").read_text(encoding="utf-8")):
        if L["ledger"] == skill:
            return f"#### {L['name']}"
    return None


def stocks(sec):
    """{code: name}"""
    out = {}
    for name, code in NAME_CODE.findall(sec or ""):
        out.setdefault(code, name.lstrip("*"))
    return out


def hit_lines(text, keys, width=300):
    return [l.strip()[:width] for l in (text or "").splitlines() if l.strip() and any(k in l for k in keys)]


def cap(lines, n):
    out, tot = [], 0
    for l in lines:
        if tot + len(l) > n:
            out.append(f"…(超出 {n // 1000}k 字截断, 其余自己按需读)")
            break
        out.append(l)
        tot += len(l) + 1
    return out


def rule_blocks(rules_text):
    """[(id, 起始行号, 块文本)]"""
    lines = rules_text.splitlines()
    heads = [(i, m.group(1)) for i, l in enumerate(lines) if (m := RULE_HEAD.match(l))]
    out = []
    for k, (i, rid) in enumerate(heads):
        j = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        out.append((rid, i + 1, "\n".join(lines[i:j]).rstrip()))
    return out


def idx_line(l):
    """rules_index 一行 → 压缩: '- ID 状态 标题 [→Lnnn]'"""
    m = re.search(r"\(rules\.md#L(\d+)\)", l)
    body = re.split(r"｜| → ", l, maxsplit=1)[0].strip()
    return f"{body[:120]}{f' [L{m.group(1)}]' if m else ''}"


def prev_days(d, n):
    days = sorted(p.stem for p in MD.rglob("20??-??-??.md") if p.stem < d)
    return days[-n:]


def build(skill, d):
    head = head_of(skill)
    if not head:
        raise ValueError(f"未知 skill/账本: {skill}")
    pdir = ROOT / "skills" / f"{skill}-skill" / "persona"
    mdf = md_path(d)
    text = mdf.read_text(encoding="utf-8") if mdf.exists() else ""
    sec = section(text, head)
    st = stocks(sec)
    keys = list(st) + [n for n in st.values() if len(n) >= 2]
    L = [f"# 蒸馏素材包 · {skill} · {d}", "",
         f"> 零 token 机械生成(scripts/md/build_distill_pack.py, {dt.datetime.now():%m-%d %H:%M}); 信息截止={d}。数字/原文照抄, 不要重算; 包里没有的才去读原件。",
         f"> 同票: {', '.join(f'{n}({c})' for c, n in st.items()) or '无(当日小节无 名称(代码) 形式的标的)'}", ""]
    L += [f"## ① 当天本人小节 `{head}`({mdf.relative_to(ROOT).as_posix()})", ""]
    L += [sec.strip() if sec and sec.strip() else "(当天无此小节或小节为空 = 无可沉淀/空仓日, 照工作流按正常结果处理)", ""]
    # ② 盘面
    mk = ["## ② 当日盘面(同一 md)", "", "### 收评", "", ((section(text, "## 收评") or "(无)").strip())[:3000], ""]
    if keys:
        zt = hit_lines(section(text, "## 涨停分析") or "", keys)
        lhb = []
        sec_l = section(text, "### 龙虎榜") or ""
        for c in st:
            m = re.search(rf"^#### [^\n]*{c}\s*$([\s\S]*?)(?=^#### |\Z)", sec_l, re.M)
            if m:
                lhb.append(f"- 龙虎榜 {st[c]}({c}): " + " / ".join(x.strip() for x in m.group(1).splitlines() if x.strip())[:600])
        mk += ["### 涨停分析里的同票行", ""] + (zt or ["(无)"]) + ["", "### 龙虎榜同票", ""] + (lhb or ["(无)"]) + [""]
    L += cap(mk, CAP_MKT + 3000)
    # ③ 近 5 天同票
    L += [f"## ③ 近 {RECENT_N} 个交易日本人小节里的同票记录", ""]
    rec = []
    if keys:
        for pd in prev_days(d, RECENT_N):
            s2 = section(md_path(pd).read_text(encoding="utf-8"), head) if md_path(pd).exists() else None
            hl = hit_lines(s2, keys)
            if hl:
                rec += [f"**{pd}**"] + [f"- {x.lstrip('- ')}" for x in hl]
    L += cap(rec, CAP_RECENT) if rec else ["(无)"]
    L.append("")
    # ④ 规则
    rf = pdir / "rules.md"
    blocks = rule_blocks(rf.read_text(encoding="utf-8")) if rf.exists() else []
    scored = sorted(((sum(b.count(k) for k in keys), rid, ln, b) for rid, ln, b in blocks if keys), key=lambda x: -x[0])
    same = [x for x in scored if x[0] > 0]
    L += [f"## ④ 规则(源 {rf.relative_to(ROOT).as_posix()}, 共 {len(blocks)} 条)", "", f"### 同票/同名规则全文({len(same)} 条, 按命中数排序)", ""]
    body, tot, shown = [], 0, 0
    for n, rid, ln, b in same:
        if len(b) > 3000:   # 单条规则验证记录很长(桃哥单条可达 1 万字+): 只给前 3000 字, 余下按行号补读
            b = b[:3000] + f"\n…(本条余下 {len(b) - 3000} 字未展开, rules.md 第 {ln} 行起)"
        if tot + len(b) > CAP_RULES and shown:
            body.append(f"…其余 {len(same) - shown} 条超 {CAP_RULES // 1000}k 字未展开(按行号补读): " + ", ".join(f"{x[1]}(L{x[2]})" for x in same[shown:][:40]))
            break
        body += [f"<!-- R {rid} rules.md 第 {ln} 行起, 命中 {n} -->", b[:CAP_RULES], ""]
        tot += len(b)
        shown += 1
    L += body or ["(无)", ""]
    ri = pdir / "rules_index.md"
    if ri.exists():
        pend = [idx_line(l) for l in ri.read_text(encoding="utf-8").splitlines() if l.startswith("- ") and "⏳" in l]
        L += ["", f"### 待验证规则索引({len(pend)} 条; 核销时按 [L行号] 只读需要的那几条)", ""] + cap(pend, CAP_IDX)
    else:
        L += ["", "### 待验证规则索引", "", "(rules_index.md 缺失: 按工作流 grep rules.md 的 [待验证])"]
    # ⑤ 画像目录
    pi = pdir / "profile_index.md"
    L += ["", f"## ⑤ 画像目录(源 {pi.relative_to(ROOT).as_posix()}; 改画像时按行号只读对应节)", ""]
    if pi.exists():
        for l in pi.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\| (S\d+) \| ([^|]+) \| ([^|]*) \| (L[\d-]+) \|", l)
            if m:
                L.append(f"- {m.group(1)} {m.group(2).strip()[:40]} {m.group(4)}｜{m.group(3).strip()[:60]}")
    else:
        L.append("(profile_index.md 缺失)")
    L.append("")
    out = OUT / d / f"{skill}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    return out, {"stocks": len(st), "sec": bool(sec and sec.strip()), "same_rules": len(same), "recent_lines": len([x for x in rec if x.startswith("- ")])}


def selftest():
    t = "# d\n## 收评\n沪指涨\n## 涨停分析\n- 百洋股份 涨停 医药\n- 别的 涨停\n## 复盘\n### bilibili\n#### 刘 忆青\n\n- 百洋股份(002696): 14:56 卖\n【推测】\n- 跌停走\n#### A658\nx\n"
    s = section(t, "#### 刘忆青")
    assert s and "002696" in s and "A658" not in s, s
    assert stocks(s) == {"002696": "百洋股份"}
    rb = rule_blocks("# x\n### R1 甲\na\n### R2 乙 百洋股份\nb\n## 修订\n#### R3 丙\nc\n")
    assert [r[0] for r in rb] == ["R1", "R2", "R3"] and rb[1][1] == 4 and "百洋" in rb[1][2]
    assert idx_line("- R6 ⏳ 标题｜后面 → 规则: x [→正文](rules.md#L25)") == "- R6 ⏳ 标题 [L25]"
    assert hit_lines(section(t, "## 涨停分析"), ["百洋股份"]) == ["- 百洋股份 涨停 医药"]
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill")
    ap.add_argument("--date")
    ap.add_argument("--print", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return 0
    if not a.skill or not a.date:
        print("用法: --skill <x>[,<y>] --date yyyy-MM-dd[,yyyy-MM-dd]")
        return 2
    res, fail = {}, []
    for d in [x.strip() for x in a.date.split(",") if x.strip()]:
        for sk in [x.strip() for x in a.skill.split(",") if x.strip()]:
            key = f"{sk}@{d}"
            try:
                p, info = build(sk, d)
                kb = p.stat().st_size / 1024
                res[key] = p.relative_to(ROOT).as_posix()
                print(f"PACK {sk} {res[key]} {kb:.1f}KB | 同票 {info['stocks']} / 同票规则 {info['same_rules']} / 近{RECENT_N}天同票行 {info['recent_lines']}"
                      + ("" if info["sec"] else " / 当天无小节"))
                if a.print:
                    print(p.read_text(encoding="utf-8"))
            except Exception as e:   # noqa: BLE001
                fail.append(key)
                print(f"PACK_FAIL {key}: {type(e).__name__}: {e}")
    print("JSON:" + json.dumps({"date": a.date, "packs": res, "fail": fail}, ensure_ascii=False))
    return 1 if fail else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
