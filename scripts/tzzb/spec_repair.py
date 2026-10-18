# -*- coding: utf-8 -*-
"""spec_repair.py — 32B 推测层初稿: 机械质检不过的条目交给在线模型只修这几条(10/18 用户定的交接方式; 先 1 位导师试跑)

流程(每位导师):
  ① 机械质检(零 token): 逐条看 "(32B初稿)" 推测行
       空话   = 套话词(可能/或因/反映/风格/风控/纪律…) 且 推测句里没有具体股票代码或数字
       锚点错 = 锚点里写了股票代码 / 价格 / 百分比, 但一个都不在当天硬数据里出现(放宽: 有一个对上就算过)
     通过的条目原样保留, 不花钱
  ② 不过的条目连同当天硬数据(小节里【推测】之前的部分, 截断 1500 字)和不过原因, 按 BATCH 天打成一包, 一次 claude -p(不给工具)
     让它对每条输出: 改写后的一句(必须带"(锚点: …)"且锚点取自硬数据原文) 或 DELETE(硬数据支撑不了任何具体推测)
  ③ 改写结果再跑一遍机械质检, 过了才写回 md(行尾标记换成"(32B初稿→云端修)"), 不过就删掉该行; 写回前重读文件、只替换这一行、原子替换
  ④ 报告: 修 / 删 / 保留 各几条, 花费(claude_cost.csv tag=tzzb-spec-repair), 抽样前后对照
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/spec_repair.py --ledger zuoshoudeirong [--dry] [--limit-days N] [--batch 30]
"""
import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import mentors as M  # noqa: E402

TAG_OLD, TAG_NEW = "(32B初稿)", "(32B初稿→云端修)"
VAGUE = re.compile(r"可能|或因|或许|反映|体现|风格|控制交易频率|风控|摩擦成本|纪律|偏好|倾向|谨慎|稳健|预留|安全边际")
CODE = re.compile(r"\d{6}")
NUM = re.compile(r"\d+(?:\.\d+)?%?")
OUT = ROOT / "scripts" / "temp" / "spec_repair"


def section_bounds(text, name):
    m = re.search(rf"^#### {re.escape(name)}\n(.*?)(?=^#### |^### |^## |\Z)", text, re.S | re.M)
    return m


def qc(line, hard):
    """→ None(通过) 或 原因"""
    claim = line.split("(锚点")[0].split("（锚点")[0]
    am = re.search(r"锚点[:：]\s*([^)）]*)", line)
    anchor = am.group(1) if am else ""
    if VAGUE.search(claim) and not (CODE.search(claim) or re.search(r"\d", claim)):
        return "空话(套话, 推测句里没有具体股票代码或数字)"
    if not anchor:
        return "没有锚点"
    keys = CODE.findall(anchor) + [x for x in NUM.findall(anchor) if len(x.rstrip("%")) >= 3]
    if keys and not any(k in hard for k in keys):
        return f"锚点对不上(锚点里的 {', '.join(keys[:4])} 在当天硬数据里都找不到)"
    return None


def collect(name, limit_days=None):
    items = []   # {date, file, old, reason, hard}
    days = 0
    for f in sorted(glob.glob(str(ROOT / "md" / "2026S*" / "*.md"))):
        t = open(f, encoding="utf-8").read()
        m = section_bounds(t, name)
        if not m or TAG_OLD not in m.group(1):
            continue
        body = m.group(1)
        hard = body.split("【推测】")[0].strip()
        bad = []
        for line in body.splitlines():
            if TAG_OLD in line:
                r = qc(line, hard)
                if r:
                    bad.append((line, r))
        if bad:
            days += 1
            if limit_days and days > limit_days:
                break
            for line, r in bad:
                items.append({"date": Path(f).stem, "file": f, "old": line, "reason": r, "hard": hard[:1500]})
    return items


class _Batch(list):
    """可打标记的批(拆半重试只重试一轮)"""
    _split = False


def prompt_of(name, batch):
    by = {}
    for i, it in enumerate(batch):
        by.setdefault(it["date"], {"hard": it["hard"], "lines": []})["lines"].append((i, it["old"], it["reason"]))
    parts = []
    for d, v in by.items():
        parts.append(f"### {d}\n硬数据(事实):\n{v['hard']}\n待修推测:")
        for i, old, r in v["lines"]:
            parts.append(f"[{i}] {old.strip()}\n    质检不过原因: {r}")
    return (f"你在给同花顺投资账本导师「{name}」的每日【推测】层做复核修订。下面每天给出该导师当天的硬数据(净值/持仓/成交, 是事实)和若干条本地小模型写的推测, "
            "这些推测已被机械质检判为不合格(原因已标)。逐条处理:\n"
            "- 若当天硬数据能支撑一条具体、可证伪的推测(说清是哪只票、什么动作、什么时间或价格, 以及背后可能的意图), 就改写成一句, 格式: "
            "\"- <推测> (锚点: <从硬数据原文里摘的数字/票名/时刻>)\"; 锚点必须能在上面的硬数据里原样找到\n"
            "- 若硬数据支撑不了任何具体推测(例如只是\"无操作\"\"空仓\"), 输出 DELETE\n"
            "- 不要写\"可能/或许/反映风格/风控纪律\"这类没有信息量的话\n"
            "只输出一个 JSON 数组, 不要别的文字: [{\"i\": 序号, \"new\": \"改写后的整行\" 或 \"DELETE\"}]\n\n" + "\n".join(parts))


def apply(it, new_line):
    f = it["file"]
    t = open(f, encoding="utf-8").read()
    if it["old"] not in t:
        return False
    t2 = t.replace(it["old"] + "\n", (new_line + "\n") if new_line else "", 1)
    tmp = f + ".tmp_repair"
    open(tmp, "w", encoding="utf-8", newline="").write(t2)
    os.replace(tmp, f)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit-days", type=int)
    ap.add_argument("--batch", type=int, default=30, help="每次调用最多多少条(按天聚合)")
    a = ap.parse_args()
    name = M.get(a.ledger)["name"]
    items = collect(name, a.limit_days)
    total = 0
    for f in glob.glob(str(ROOT / "md" / "2026S*" / "*.md")):
        m = section_bounds(open(f, encoding="utf-8").read(), name)
        total += m.group(1).count(TAG_OLD) if m else 0
    print(f"{name}: 初稿约 {total} 条, 质检不过 {len(items)} 条(空话 {sum('空话' in x['reason'] for x in items)} / 锚点 {sum('锚点' in x['reason'] for x in items)})")
    if a.dry or not items:
        return
    from claude_call import call as claude_call, LEAN_ARGS   # noqa: PLC0415
    OUT.mkdir(parents=True, exist_ok=True)
    log = open(OUT / f"{a.ledger}.jsonl", "a", encoding="utf-8")
    stat = {"修": 0, "删": 0, "改后仍不过→删": 0, "写回失败": 0, "调用失败": 0}
    cost = 0.0
    def parse(txt):
        """10/18: 整段 JSON 数组解析失败时退回逐个对象解析(模型偶尔在某条 new 里带未转义引号, 原先整批作废=白花钱)"""
        mm = re.search(r"\[[\s\S]*\]", txt or "")
        try:
            return {int(x["i"]): str(x["new"]) for x in json.loads(mm.group(0))} if mm else {}
        except (ValueError, KeyError, TypeError):
            pass
        got = {}
        for m in re.finditer(r"\{[^{}]*?\"i\"\s*:\s*(\d+)[^{}]*?\}", txt or ""):
            try:
                x = json.loads(m.group(0))
                got[int(x["i"])] = str(x["new"])
            except (ValueError, KeyError, TypeError):
                nm = re.search(r"\"new\"\s*:\s*\"([\s\S]*)\"\s*\}$", m.group(0))
                if nm:
                    got[int(m.group(1))] = nm.group(1)
        return got

    queue = [items[s:s + a.batch] for s in range(0, len(items), a.batch)]
    nb = 0
    while queue:
        batch = queue.pop(0)
        nb += 1
        r = claude_call(prompt_of(name, batch), tag="tzzb-spec-repair", permission="default", timeout=900,
                        extra_args=LEAN_ARGS + ["--tools", ""])
        cost += r.cost_usd or 0
        outs = parse(r.result or "")
        if not outs:
            (OUT / f"{a.ledger}_fail_{nb}.txt").write_text(f"errors={r.errors}\n\n{r.result or ''}", encoding="utf-8")   # 留原文查因
            if len(batch) > 5 and not getattr(batch, "_split", False):   # 10/18: 解析不出 → 拆两半各重试一次(只重试一轮, 防无限烧钱)
                h = len(batch) // 2
                for part in (batch[:h], batch[h:]):
                    part = _Batch(part)
                    part._split = True
                    queue.insert(0, part)
                print(f"批 {nb}: 解析失败 {r.errors[:2]}, 拆成两半重试(原文 {a.ledger}_fail_{nb}.txt)")
                continue
            stat["调用失败"] += len(batch)
            print(f"批 {nb}: 解析失败且已重试 {r.errors[:2]}")
            continue
        for i, it in enumerate(batch):
            new = outs.get(i, "DELETE").strip()
            if new == "DELETE" or not new:
                ok, kind, line = apply(it, None), "删", None
            else:
                line = (new if new.startswith("- ") else "- " + new.lstrip("- ")).replace(TAG_OLD, "").rstrip() + " " + TAG_NEW
                why = qc(line, it["hard"])
                if why:
                    ok, kind, line = apply(it, None), "改后仍不过→删", None
                else:
                    ok, kind = apply(it, line), "修"
            stat[kind if ok else "写回失败"] += 1
            log.write(json.dumps({"date": it["date"], "reason": it["reason"], "old": it["old"].strip(), "new": line, "kind": kind if ok else "写回失败"}, ensure_ascii=False) + "\n")
        print(f"批 {nb}: ${r.cost_usd:.2f} 累计 ${cost:.2f} {stat}", flush=True)
    log.close()
    print(f"完成: {stat}; 花费 ${cost:.2f}; 明细 {(OUT / (a.ledger + '.jsonl')).relative_to(ROOT)}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
