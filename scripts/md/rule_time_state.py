# -*- coding: utf-8 -*-
"""rule_time_state.py — 规则的"时间状态"(建立日 / 最后验证日 / 状态)机械补齐与刷新(10/17 晚用户批; 零 token, 只改 persona/rules.md 的这一行)

为什么: 画像是"当时"做的; 导师会成长、会否定自己以前的做法; 推测也会被后来的证据推翻。规则只有日期证据、没有"这条现在还算不算数",
        链和蒸馏就会把 40 天没被验证过、甚至已被导师自己放弃的规则当铁律用。
格式(每条规则一行, 规则头下第一条要点):
    - **时间状态**: 建立 2026-10-11 · 最后验证 2026-10-16 · 状态 活跃
  状态三态: 活跃(最近 STALE_TD 个交易日内有新证据) / 待复核(超过 STALE_TD 个交易日没新证据, 链降权用、蒸馏优先核) /
           已否定(YYYY-MM-DD, 由 Rxx 取代)——旧规则不删, 保留以便看出导师哪天变了、回放旧日子用当时的认识
  列表式规则(趋势天哥 / 卢本圆: "- **A1 标题** ...")写成下一行缩进子项 "  - 时间状态: ..."
来源(机械): 建立日 = 规则头"(MM/DD 新增)" > git 里该规则头第一次出现的提交日 > 画像快照首版日 > 今天;
           最后验证日 = 规则块里"验证状态"行 / "MM-DD 补"行中最晚的日期(不晚于今天), 没有就=建立日;
           已否定 = 规则头或标签带 已证伪 / 已失效 / ❌(否定日期机械拿不到 → "日期待补", 之后由蒸馏写)
之后谁维护: 蒸馏工作流(新规则写建立日; 核销兑现/打脸写最后验证日; 否定写状态, 不删规则); 本脚本每晚只按"最后验证日"刷新 活跃/待复核 两态,
           不碰"已否定", 不改蒸馏写的日期。
用法: python rule_time_state.py [--skill a,b | --all] [--write] [--selftest]
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
STALE_TD = 20
HEAD = re.compile(r"^(#{3,4}) ([A-Z]+\d+[a-z]?) (.*)$")
LIST = re.compile(r"^- \*\*([A-Z]+\d+) ")
TS_LINE = re.compile(r"^(\s*)- (\*\*)?时间状态(\*\*)?[:：]\s*(.*)$")
DATE = re.compile(r"(?<!\d)(?:(20\d\d)[-/])?(\d{1,2})[-/](\d{1,2})(?!\d)")
NEW_TAG = re.compile(r"[（(](\d{1,2})/(\d{1,2}) ?新增")
NEG = re.compile(r"已证伪|已失效|❌|已否定")


def _date(y, m, d, today):
    try:
        y = int(y) if y else today.year
        x = dt.date(y, int(m), int(d))
        if not y or x > today:   # 没写年份且比今天晚 → 去年
            x = dt.date(y - 1, int(m), int(d)) if x > today else x
        return x
    except ValueError:
        return None


def _td(a, b):
    """a 之后到 b 的工作日数(节假日忽略, 粗算)"""
    n, x = 0, a
    while x < b:
        x += dt.timedelta(days=1)
        n += x.weekday() < 5
    return n


def _git_first(path, needle):
    try:
        r = subprocess.run(["git", "log", "--reverse", "--format=%cs", "-S", needle, "--", str(path.relative_to(ROOT))],
                           cwd=ROOT, capture_output=True, text=True, timeout=120, creationflags=NOWIN)
        ls = r.stdout.split()
        return dt.date.fromisoformat(ls[0]) if ls else None
    except Exception:   # noqa: BLE001
        return None


def _snap_first(skill):
    f = ROOT / "skills_versions" / skill / "index.json"
    try:
        v = json.loads(f.read_text(encoding="utf-8"))["versions"]
        return dt.datetime.fromisoformat(v[0]["ts"]).date() if v else None
    except Exception:   # noqa: BLE001
        return None


def blocks(lines):
    """[(规则号, 头行下标, 块结束下标(不含), 是否列表式, 头级别)]"""
    out = []
    for i, l in enumerate(lines):
        m = HEAD.match(l)
        if m:
            out.append([m.group(2), i, None, False, len(m.group(1))])
        elif LIST.match(l):
            out.append([LIST.match(l).group(1), i, None, True, 9])
    for k, b in enumerate(out):
        end = len(lines)
        for j in range(b[1] + 1, len(lines)):
            l = lines[j]
            if HEAD.match(l) or (b[3] and LIST.match(l)) or (b[3] and l.strip() and not l.startswith((" ", "\t"))):
                end = j
                break
            hm = re.match(r"^(#{1,6}) ", l)
            if hm and len(hm.group(1)) <= b[4]:
                end = j
                break
        b[2] = end
    return out


NOISE = re.compile(r"(?:20\d\d-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2})\s*(?:批量\S*|回填|重沉淀|修订|新增|降级|生成)|(?:信息截止|截止|生成于|修订记录)\s*[\d/\-]+")


def compute(skill, path, lines, b, today, git_cache):
    """(建立日, 最近证据日) —— 证据日=规则块里(含规则头标签)出现的最晚事件日期; 处理日期(批量回填/重沉淀/信息截止/新增/修订)不算"""
    rid, i, end, is_list, _ = b
    head = lines[i]
    m = NEW_TAG.search(head)
    born = _date(None, m.group(1), m.group(2), today) if m else None
    if not born:
        needle = head.split("**")[1].split(" ")[0] + " " if is_list else head.split(" ", 2)[0] + " " + rid + " "
        born = git_cache.setdefault(needle, _git_first(path, needle)) or _snap_first(skill) or today
    ev = []
    for l in [head] + lines[i + 1:end]:
        if TS_LINE.match(l):
            continue
        s = NOISE.sub(" ", l)
        ev += [x for x in (_date(*g, today) for g in DATE.findall(s)) if x and x <= today]
    return born, (max(ev) if ev else born), bool(ev)


def process(skill, write, today):
    path = ROOT / "skills" / f"{skill}-skill" / "persona" / "rules.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    bl = blocks(lines)
    git_cache, todo, have_ts = {}, [], []
    for b in bl:
        rid, i, end, is_list, _ = b
        have = next((j for j in range(i + 1, end) if TS_LINE.match(lines[j])), None)
        if have is not None:
            have_ts.append(have)
        else:
            todo.append((b, *compute(skill, path, lines, b, today, git_cache)))
    # 知识前沿 = 本画像所有规则里最晚的证据日(不晚于今天): 实盘导师≈今天; B站历史回填中的 UP=回填进度, 不会因为还没回填到今天就全判过期
    lasts = [x[2] for x in todo if x[3] and not NEG.search(lines[x[0][1]])]   # 没有证据日期的、已否定的不参与定前沿
    for j in have_ts:
        ml = re.search(r"最后验证 (\d{4}-\d{2}-\d{2})", lines[j])
        mb = re.search(r"建立 (\d{4}-\d{2}-\d{2})", lines[j])
        if ml and "已否定" not in lines[j] and not (mb and mb.group(1) == ml.group(1)):   # 已否定 / 没有证据(验证日=建立日)的不参与定前沿
            lasts.append(dt.date.fromisoformat(ml.group(1)))
    front = min(max(lasts), today) if lasts else today
    stale = lambda last: "待复核" if _td(last, front) > STALE_TD else "活跃"   # noqa: E731
    upd, ins = 0, []
    for j in have_ts:
        cur = TS_LINE.match(lines[j]).group(4)
        ml = re.search(r"最后验证 (\d{4}-\d{2}-\d{2})", cur)
        if "已否定" in cur or not ml:
            continue
        new = re.sub(r"状态 \S+", f"状态 {stale(dt.date.fromisoformat(ml.group(1)))}", cur)
        if new != cur:
            lines[j] = lines[j].replace(cur, new)
            upd += 1
    for b, born, last, _ev in todo:
        rid, i, end, is_list, _ = b
        state = "已否定(日期待补)" if NEG.search(lines[i]) else stale(last)
        txt = f"建立 {born} · 最后验证 {last} · 状态 {state}"
        if is_list:
            ins.append((i + 1, f"  - 时间状态: {txt}"))
        else:
            k = next((j for j in range(i + 1, end) if lines[j].startswith("- ")), None)
            ins.append((k if k is not None else i + 1, f"- **时间状态**: {txt}"))
    for pos, l in sorted(ins, reverse=True):
        lines.insert(pos, l)
    new = "\n".join(lines)
    if write and new != text:
        path.write_text(new, encoding="utf-8", newline="")
    states = {}
    for l in lines:
        m = TS_LINE.match(l)
        if m:
            s = re.search(r"状态 (\S+)", m.group(4))
            k = (s.group(1) if s else "?").split("(")[0]
            states[k] = states.get(k, 0) + 1
    return {"rules": len(bl), "新增": len(ins), "刷新": upd, "前沿": str(front), "状态": states}


def selftest():
    import tempfile
    global ROOT
    keep = ROOT
    try:
        ROOT = Path(tempfile.mkdtemp())
        p = ROOT / "skills" / "x-skill" / "persona"
        p.mkdir(parents=True)
        (p / "rules.md").write_text(
            "# rules\n\n## 入场\n\n### R1 老规则 [待验证]（10/11 新增）\n\n- **规则**: a\n- **验证状态**: [样本 3] 10-16 +1\n\n"
            "### R2 很久没验证（07/20 新增）\n\n- **规则**: b\n- **验证状态**: 08-01 样本\n\n### R3 被打脸 [已证伪]\n\n- **规则**: c\n\n## 出场\n\n"
            "- **A1 列表式规则** `[画像]`: 正文 09-30\n  - 证据 09-30\n- **A2 另一条**: x\n", encoding="utf-8")
        today = dt.date(2026, 10, 17)
        r = process("x", True, today)
        t = (p / "rules.md").read_text(encoding="utf-8")
        assert "建立 2026-10-11 · 最后验证 2026-10-16 · 状态 活跃" in t, t
        assert "最后验证 2026-08-01 · 状态 待复核" in t, t
        assert "状态 已否定(日期待补)" in t, t
        assert t.count("  - 时间状态:") == 2, t
        assert t.index("- **时间状态**") < t.index("- **规则**: a"), "应插在规则头下第一条要点前"
        r2 = process("x", True, today)
        assert r2["新增"] == 0 and (p / "rules.md").read_text(encoding="utf-8") == t, "第二次应幂等"
        r3 = process("x", True, dt.date(2026, 12, 1))   # 过期按"知识前沿"(最晚证据日 10-16)算, 不按日历: 没新证据时不会全体变待复核
        t3 = (p / "rules.md").read_text(encoding="utf-8")
        assert r3["前沿"] == "2026-10-16" and "最后验证 2026-10-16 · 状态 活跃" in t3 and "最后验证 2026-08-01 · 状态 待复核" in t3, (r3, t3)
        print("RULE_TIME_STATE SELFTEST PASS", r)
    finally:
        ROOT = keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    sks = [p.name[:-6] for p in sorted((ROOT / "skills").glob("*-skill")) if (p / "persona" / "rules.md").exists()] if a.all else a.skill.split(",")
    today = dt.date.today()
    tot = {}
    for sk in sks:
        r = process(sk, a.write, today)
        if r:
            print(f"{sk}: {r}")
            for k, v in r["状态"].items():
                tot[k] = tot.get(k, 0) + v
    print("JSON:" + json.dumps({"skills": len(sks), "状态合计": tot, "write": a.write}, ensure_ascii=False))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
