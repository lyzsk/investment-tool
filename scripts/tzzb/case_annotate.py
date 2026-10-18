# -*- coding: utf-8 -*-
"""case_annotate.py — 给逐日操作日志卡补"解读"(10/18 用户定: 案例覆盖交易日要过 75%; 不另写叙事案例, 在日卡上加解读)

为什么: 日卡(scripts/tzzb/case_log.py)是 100% 覆盖的事实, 缺"这天用的什么手法 / 为什么 / 对应哪条规则"。叙事案例只留精选,
        覆盖率由日卡 + 解读保证; 蒸馏 / 加厚从解读里攒"新手法候选"升规则。
口径: 只解读有成交的日子(无成交日 case_log.py 机械标"持仓不动"); 动机永远是推测 → 每天给 2~3 个竞争假设 + 概率(合计 1);
      手法类尽量复用该导师已有的类名(提示词里给), 保持口径一致; 不认识的标 new=true(新手法候选)。
排队(用户定): 按月份从新到旧, 每个月轮一遍所有导师再进下一个月 → 各导师进度持平; 每个会话 = 一位导师的一个月(>20 天拆两批); 串行。
产物: skills/<id>-skill/persona/case_log/annotations.jsonl(追加; case_log.py 渲染时并进日卡末尾, 每晚重算不会丢);
      暂存 results/case_annot/<id>/<月>_<k>.jsonl; 进度 results/case_annot/progress.json; 断点续跑(已解读的日期跳过)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/case_annotate.py [--ledger a,b] [--months 2026-10,2026-09] [--max-sessions N] [--dry]
"""
import argparse
import collections
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from claude_call import call as claude_call   # noqa: E402
import mentors as M                          # noqa: E402

PY = str(ROOT / "scripts" / "venv" / "Scripts" / "python.exe")
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LEAN_ARGS = ["--exclude-dynamic-system-prompt-sections", "--disable-slash-commands", "--strict-mcp-config", "--tools", "Read,Write,Edit,Grep,Glob"]
STAGE = ROOT / "results" / "case_annot"
CHUNK = 40
WIN = 2   # 一轮 = 2 个月; 每轮所有导师各做一次再进下一轮(进度持平), 一个会话最多 40 天

PROMPT = """任务: 给 tzzb 导师「{name}」(ledger={id}) {month} 的逐日操作日志卡写"解读"。元指令: 任务优先, 禁反问; 只读下面列的文件, 只写 {out}。

读: `skills/{id}-skill/persona/case_log/` 下 {files} 里这些日期的日卡(只看这些): {dates}
参考: `skills/{id}-skill/persona/rules_index.md`(他的规则, 一行一条, 编号 R<n>); 需要细节再按行号读 rules.md。
他已有的手法类(尽量复用, 保持口径一致): {classes}

每个日期写一行 JSON(JSON Lines, 不要别的文字)到 `{out}`, 字段:
  {{"date":"YYYY-MM-DD","class":"手法类(4~8 字, 如 低开砍仓 / 满仓换股 / 竞价建仓 / 冲高减仓 / 尾盘建仓 / 正T / 下跌加仓)",
    "why":[{{"h":"动机假设一(一句话, 要具体到当天的盘面/持仓事实)","p":0.6}},{{"h":"假设二","p":0.4}}],
    "rules":["R11"],   // 当天行为对应的现有规则编号, 没有就 []
    "new":false,       // 现有规则都解释不了的手法 = true(新手法候选)
    "note":"可选: 一句值得记的细节(挂价/分笔/先卖后买/亏损处理), 没有就省略"}}
要求: 每个列出的日期都要写且只写一行; why 2~3 个, p 合计 1; 动机是推测, 但必须基于日卡里的事实(价格、时刻、仓位、竞价、次日结果只用于说明"结果", 不能当他当时就知道);
写完后单独一行输出 `ANNOT_OK {id} {month}`。
"""


def months_of(sk):
    d = ROOT / "skills" / f"{sk}-skill" / "persona" / "case_log"
    return sorted((f.stem for f in d.glob("20??-??.md")), reverse=True) if d.exists() else []


def action_days(sk, month):
    """该月有成交的日期(卡里有'- 成交'行)"""
    f = ROOT / "skills" / f"{sk}-skill" / "persona" / "case_log" / f"{month}.md"
    out = []
    for blk in re.split(r"^### ", f.read_text(encoding="utf-8"), flags=re.M)[1:]:
        d = blk[:10]
        if re.fullmatch(r"\d{4}-\d\d-\d\d", d) and re.search(r"^- 成交", blk, re.M):
            out.append(d)
    return out


def annotated(sk):
    f = ROOT / "skills" / f"{sk}-skill" / "persona" / "case_log" / "annotations.jsonl"
    A = {}
    if f.exists():
        for l in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(l)
                A[r["date"]] = r
            except (ValueError, KeyError):
                pass
    return A


def validate(rows, dates):
    ok, bad = [], []
    for r in rows:
        try:
            if r["date"] not in dates or not str(r.get("class") or "").strip():
                raise ValueError("日期不在本批或缺 class")
            why = r.get("why") or []
            if not (1 <= len(why) <= 3) or abs(sum(float(h.get("p") or 0) for h in why) - 1) > 0.05:
                raise ValueError("why 须 1~3 个且 p 合计 1")
            r["rules"] = [x for x in (r.get("rules") or []) if re.fullmatch(r"[A-Z]\d+", str(x))]
            ok.append(r)
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            bad.append(f"{r.get('date')}: {e}")
    return ok, bad


def session(sk, month, dates, k, dry):
    out = STAGE / sk / f"{month}_{k}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    A = annotated(sk)
    classes = [c for c, _ in collections.Counter(a.get("class") for a in A.values() if a.get("class")).most_common(25)]
    files = " / ".join(f"{m}.md" for m in sorted({d[:7] for d in dates}))
    prompt = PROMPT.format(name=M.get(sk)["name"], id=sk, month=month, files=files, dates=", ".join(dates), out=str(out.relative_to(ROOT)).replace("\\", "/"),
                           classes=" / ".join(classes) or "(还没有, 你来定, 后面的会沿用)")
    if dry:
        print(f"[dry] {sk} {month}#{k}: {len(dates)} 天")
        return 0, 0.0
    r = claude_call(prompt, tag=f"tzzb-annot:{sk}", permission="acceptEdits", timeout=2400, extra_args=LEAN_ARGS,
                    sentinels=[f"ANNOT_OK {sk} {month}"], require_sentinels=True, expect_files=[out])
    rows = []
    if out.exists():
        for l in out.read_text(encoding="utf-8").splitlines():
            l = l.strip()
            if l.startswith("{"):
                try:
                    rows.append(json.loads(l))
                except ValueError:
                    pass
    ok, bad = validate(rows, set(dates))
    if ok:
        stamp = dt.datetime.now().isoformat(timespec="minutes")
        with (ROOT / "skills" / f"{sk}-skill" / "persona" / "case_log" / "annotations.jsonl").open("a", encoding="utf-8") as fh:
            for x in ok:
                fh.write(json.dumps({**x, "by": f"claude {stamp[5:10]}", "at": stamp}, ensure_ascii=False) + "\n")
    print(f"{sk} {month}#{k}: 解读 {len(ok)}/{len(dates)} 天, 不合格 {len(bad)}{(' ' + '; '.join(bad[:3])) if bad else ''}, ${r.cost_usd:.2f} {r.duration_s:.0f}s"
          + ("" if r.ok else f" 调用问题 {r.errors[:2]}"), flush=True)
    return len(ok), r.cost_usd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger")
    ap.add_argument("--months")
    ap.add_argument("--max-sessions", type=int, default=999)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    ids = a.ledger.split(",") if a.ledger else M.active_ids("tzzb")   # 10/18: 退出 paper 的导师不解读(花 token)
    allm = sorted({m for sk in ids for m in months_of(sk)}, reverse=True)
    if a.months:
        allm = [m for m in allm if m in a.months.split(",")]
    n_s, n_ok, cost = 0, 0, 0.0
    prog = STAGE / "progress.json"
    STAGE.mkdir(parents=True, exist_ok=True)
    rounds = [allm[i:i + WIN] for i in range(0, len(allm), WIN)]
    for rnd in rounds:                # 按时间从新到旧, 每轮(2 个月)所有导师各做一次 → 进度持平
        m = rnd[-1] + ".." + rnd[0] if len(rnd) > 1 else rnd[0]
        for sk in ids:
            ms = [x for x in rnd if x in months_of(sk)]
            if not ms:
                continue
            done = annotated(sk)
            todo = sorted(d for x in ms for d in action_days(sk, x) if d not in done)
            for k, i in enumerate(range(0, len(todo), CHUNK)):
                if n_s >= a.max_sessions:
                    print(f"到会话上限 {a.max_sessions}, 停")
                    return
                ok, c = session(sk, m, todo[i:i + CHUNK], k, a.dry)
                n_s += 1
                n_ok += ok
                cost += c
                if not a.dry:
                    subprocess.run([PY, "-X", "utf8", "scripts/tzzb/case_log.py", "--ledger", sk], cwd=ROOT, creationflags=NOWIN, capture_output=True)
                    prog.write_text(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "month": m, "skill": sk, "sessions": n_s,
                                                "annotated": n_ok, "cost": round(cost, 2)}, ensure_ascii=False), encoding="utf-8")
    print(f"完成: 会话 {n_s}, 解读 {n_ok} 天, ${cost:.2f}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
