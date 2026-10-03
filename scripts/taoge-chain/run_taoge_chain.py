#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_taoge_chain.py — taoge-skill 七步决策链驱动器（2026-10-02 按 chain.md 契约重建, 与 plan-a 无关）

图纸=skills/taoge-skill/workflows/chain.md（唯一契约源, prompt 模板从 <!-- step:NN --> 段机械抽取）。
驱动器只做机械事: 填占位符→claude -p→验哨兵(产物文件末行)/mtime 新鲜度/contract JSON 重算→
单步回炉≤2→每步落地回溯重验 01..当前→06 actions 机械转 plans 行(LLM 不直接写 plans)。
C6 方案 B: persona 反问修复=01 模板头已有"任务优先, 禁反问"元指令(注入在 prompt 层, SKILL.md 不动)。

用法:
  python scripts/taoge-chain/run_taoge_chain.py --slot 0915 [--date 20261002] [--source A-taoge]
  python scripts/taoge-chain/run_taoge_chain.py --review --date 20261002
  python scripts/taoge-chain/run_taoge_chain.py --selftest     # 不烧 token 的机械自测
出口: 0=链完成 1=链中止(回炉耗尽/校验败) 2=用法/环境错 3=ESCALATE_FULL_CHAIN(市况变, 子链升级)
"""
import argparse, json, os, re, shutil, subprocess, sys, time
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):  # Windows GBK 控制台防乱码
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CHAIN_MD = ROOT / "skills/taoge-skill/workflows/chain.md"
PAPER = ROOT / "scripts/dfcf/paper"
TOKEN_LOG = PAPER / "token_log.csv"
MAX_RETRY = 2
# headless 权限: acceptEdits=允许写产物文件不逐次询问; 模型只有 Write 需求, 不给 bash
# claude 入口=npm 全局 native exe(.cmd 走 cmd /c 有 8k 字符+转义坑, shim 是 sh 脚本 python 调不动)
_CLAUDE_EXE = os.path.join(os.environ.get("APPDATA", ""), r"npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe")
CLAUDE = [(_CLAUDE_EXE if os.path.exists(_CLAUDE_EXE) else "claude"),
          "-p", "--output-format", "json", "--permission-mode", "acceptEdits"]
SLOT_STEPS = {  # chain.md "slot→steps 映射"节的机械镜像(改 chain.md 要同步改这里, 反之亦然)
    "0915": ["01", "02", "03", "04", "05", "06", "blind"],
    "0927": ["02", "04", "06"], "0945": ["02", "04", "06"], "1000": ["02", "04", "06"],
    "1030": ["02", "04", "06"], "1127": ["02", "04", "06"], "1230": ["02", "04", "06"],
    "1400": ["02", "04", "06"], "1430": ["02", "04", "06"], "1455": ["02", "04", "06"],
}
ART = {"01": "01_facts.md", "02": "02_analysis.md", "03": "03_debate.md", "04": "04_plan.md",
       "05": "05_risk.md", "06": "06_verdict.md", "07": "07_review.md", "blind": "validate_report.md"}

# ---------- prompt 模板抽取(图纸与施工队分离: 模板只认 chain.md) ----------
def load_templates():
    text = CHAIN_MD.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"<!-- step:(\w+) -->[\s\S]*?````prompt\n([\s\S]*?)````", text):
        out[m.group(1)] = m.group(2).strip()
    need = set(ART) - {"07"}  # 07 模板也在 chain.md, 只是默认不跑
    missing = [s for s in need if s not in out]
    if missing:
        sys.exit(f"chain.md 缺模板: {missing}")
    return out

# ---------- contract / 哨兵机械校验 ----------
def read_artifact(run_dir, step, since):
    f = run_dir / ART[step]
    if not f.exists():
        return None, f"{ART[step]} 不存在"
    if f.stat().st_mtime <= since:
        return None, f"{ART[step]} mtime 不新鲜(stale 哨兵嫌疑)"
    t = f.read_text(encoding="utf-8")
    return t, None

def sentinel_ok(text, step, date):
    last = [l for l in text.strip().splitlines() if l.strip()][-1].strip()
    want = f"REVIEW_OK {date}" if step == "blind" else f"STEP_OK {step} {date}"
    if step == "blind" and last == f"REVIEW_FAIL {date}":
        return "FAIL"
    return last == want

def contract_of(text):
    blocks = re.findall(r"```contract\s*\n([\s\S]*?)```", text)
    if not blocks:
        return None, "无 contract 块"
    try:
        return json.loads(blocks[-1]), None
    except json.JSONDecodeError as e:
        return None, f"contract JSON 解析败: {e}"

def prev_contract(run_dir, step):
    """子链重跑前归档的旧 contract(升级规则比对用)"""
    f = run_dir / ART[step].replace(".md", ".prev.md")
    if f.exists():
        c, _ = contract_of(f.read_text(encoding="utf-8"))
        return c
    return None

# 各步 contract 校验器: 返回 None=过, str=失败原因(回炉用)
def v01(c, ctx):
    if c.get("date") != ctx["date_dash"]:
        return f"date 字段 {c.get('date')} != {ctx['date_dash']}"
    if not c.get("digest"):
        return "digest 空"

def v02(c, ctx):
    if c.get("market_state") not in ("有主线", "无主线退潮", "普跌"):
        return f"market_state 非法: {c.get('market_state')}"
    if c.get("leading_layer") not in ("板块层", "资金惯性层"):
        return f"leading_layer 非法: {c.get('leading_layer')}"
    if not c.get("directions"):
        return "directions 空"

def v03(c, ctx):
    if c.get("winner") not in ("多", "空"):
        return f"winner 非法: {c.get('winner')}"
    if not c.get("decisive_reason"):
        return "decisive_reason 空(必须分高下)"

def v04(c, ctx):
    cands = c.get("candidates") or []
    if not cands and not c.get("断链说明"):
        return "candidates 空且无断链说明(B72)"
    dirs = set(ctx["contracts"].get("02", {}).get("directions", []))
    for x in cands:
        if x.get("group") == "方向" and x.get("direction") not in dirs:
            return f"方向组 {x.get('name')} 的 direction '{x.get('direction')}' ∉ 02.directions"

def v05(c, ctx):
    got = {v.get("name") for v in (c.get("verdicts") or [])}
    want = {x.get("name") for x in (ctx["contracts"].get("04", {}).get("candidates") or [])}
    if got != want:
        return f"05 名单 != 04 候选: 缺{sorted(want - got)} 多{sorted(got - want)}"
    for v in c.get("verdicts") or []:
        if v.get("result") not in ("批准", "否决", "条件批准"):
            return f"verdict 非法: {v.get('result')}"

def v06(c, ctx):
    acts = c.get("actions") or []
    approved = {v["name"] for v in (ctx["contracts"].get("05", {}).get("verdicts") or [])
                if v.get("result") in ("批准", "条件批准")}
    for a in acts:
        if a.get("name") not in approved:
            return f"06 标的 {a.get('name')} ∉ 05 批准集"
        if not re.fullmatch(r"\d{6}", str(a.get("code", ""))):
            return f"{a.get('name')} code 非 6 位数字: {a.get('code')}"
        if not (isinstance(a.get("qty"), int) and a["qty"] > 0):
            return f"{a.get('name')} qty 非正整数: {a.get('qty')}"
        try:
            px = float(a.get("trigger_price"))
        except (TypeError, ValueError):
            return f"{a.get('name')} trigger_price 非数值: {a.get('trigger_price')}"
        cap = 0.15 * ctx["nav"]  # 单票≤1.5 成(10/2 params 立法), 驱动器重算非模型自声明
        if a.get("op") == "买" and px * a["qty"] > cap:
            return f"{a.get('name')} 金额 {px * a['qty']:.0f} 超单票上限 {cap:.0f}"
    if c.get("no_trade") and not acts:
        return "no_trade=true 但 actions 无进场条件单(三选一契约)"
    if ctx["sub"] and "首裁" not in str(c.get("supersedes", "")) \
            and not re.search(r"维持|取代", str(c.get("supersedes", ""))):
        return "盘中重跑 supersedes 未显式含 维持/取代"
    if not ctx["sub"] and "首裁" not in str(c.get("supersedes", "")):
        return "盘前首裁 supersedes 应含'首裁'"

def v07(c, ctx):
    if not c.get("预案对照"):
        return "预案对照 空"

def vblind(c, ctx):
    if c.get("verdict") not in ("pass", "fail"):
        return "盲审 contract verdict 非法"

VALIDATORS = {"01": v01, "02": v02, "03": v03, "04": v04, "05": v05, "06": v06, "07": v07, "blind": vblind}

# ---------- 机械层对接 ----------
def build_facts(date_dash, slot):
    r = subprocess.run(["node", "scripts/dfcf/paper/facts.mjs", "--slot", slot, "--date", date_dash],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit(f"facts 构建败: {r.stderr[-300:] if r.stderr else r.stdout[-300:]}")
    return PAPER / "facts" / date_dash / slot / "facts.md"

def load_book(source):
    f = PAPER / "books" / f"{source}.json"
    if not f.exists():
        sys.exit(f"账本不存在: {f}(先 matcher.mjs --init)")
    return json.loads(f.read_text(encoding="utf-8"))

def book_nav(book):
    return book["cash"] + sum(p["qty"] * p["cost"] for p in book["positions"].values())

def write_paper_state(book, run_dir):
    state = {"source": book["source"], "cash": book["cash"], "nav_est": round(book_nav(book), 2),
             "positions": book["positions"],
             "open_orders": [o for o in book["orders"] if o["status"] == "open"]}
    (run_dir / "paper_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

# ---------- claude -p 调用 + token 台账 ----------
def call_claude(prompt):
    t0 = time.time()
    r = subprocess.run(CLAUDE + [prompt], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=1800)
    dur = time.time() - t0
    usage, cost = {}, ""
    try:
        j = json.loads(r.stdout)
        usage = j.get("usage", {})
        cost = j.get("total_cost_usd", "")
    except json.JSONDecodeError:
        pass  # stdout 非 JSON=claude 层故障, 哨兵校验会抓到
    return r.returncode, usage, cost, dur

def log_tokens(date, slot, step, attempt, usage, cost, dur):
    new = not TOKEN_LOG.exists()
    with TOKEN_LOG.open("a", encoding="utf-8") as f:
        if new:
            f.write("date,slot,step,attempt,in_tokens,out_tokens,cost_usd,duration_s\n")
        f.write(f"{date},{slot},{step},{attempt},{usage.get('input_tokens', '')},"
                f"{usage.get('output_tokens', '')},{cost},{dur:.0f}\n")

# ---------- 06 actions → plans 行(机械转换, LLM 不直接写 plans) ----------
def emit_plans(date_dash, slot, source, contract, book):
    acts = contract.get("actions") or []
    if not acts:
        print("06 无 actions(条件单在 no_trade 契约内或纯空仓), 不写 plans")
        return
    hm = f"{slot[:2]}:{slot[2:]}"
    open_by_code = {}
    for o in book["orders"]:
        if o["status"] == "open":
            open_by_code.setdefault(o["code"], o)
    plans_dir = PAPER / "plans"
    plans_dir.mkdir(exist_ok=True)
    f = plans_dir / f"{date_dash}_{source}.md"
    lines = []
    for a in acts:
        side = "BUY" if a["op"] == "买" else "SELL"
        code = str(a["code"])
        if code in open_by_code:  # 版本链: 新单+CXL 旧单, 禁覆盖
            lines.append(f"- {hm} | {source} | CXL | {code} | - | - | - | 取代旧单(slot {slot} 终裁)")
        note = f"链终裁: 触发{a['trigger_price']}"
        if a.get("invalid_if"):
            note += f" 失效:{a['invalid_if']}"
        lines.append(f"- {hm} | {source} | {side} | {code} | {float(a['trigger_price']):g} | {a['qty']} | day | {note}")
    with f.open("a", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")
    print(f"plans 落 {len(lines)} 行 → {f}")
    # 机械衔接: 立即喂账本(import 行级哈希幂等, 重复喂=跳过; 盘中 MatchHandler 只跑 --once 不碰 import)
    r = subprocess.run(["node", "scripts/dfcf/paper/matcher.mjs", "--import", str(f)],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = (r.stdout or "").strip().splitlines()
    print(f"matcher --import: {tail[-1] if tail else r.stderr[-200:]}")
    if r.returncode != 0:
        print("WARN: import 有坏行, plans 已落盘待人工看(链不中止)")

# ---------- 主链 ----------
def run_chain(date, date_dash, slot, steps, source, dry=False):
    run_dir = ROOT / "results/taoge_chain" / f"live-{date}"
    run_dir.mkdir(parents=True, exist_ok=True)
    sub = steps != SLOT_STEPS["0915"] and steps != ["07"]
    book = load_book(source)
    ctx = {"date_dash": date_dash, "nav": book_nav(book), "sub": sub, "contracts": {}}

    facts = build_facts(date_dash, slot)
    shutil.copy(facts, run_dir / "facts.txt")  # 01 的输入口(chain.md: harness 写 facts.txt)
    write_paper_state(book, run_dir)
    # B3: 每轮起跑前重建 rules_index(rules.md 可能刚被 distill 改过, 索引不许 stale; 失败=用旧索引不致命)
    r = subprocess.run(["node", "scripts/md/gen_rules_index.mjs"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(f"WARN: rules_index 重建失败(用旧索引继续): {(r.stderr or r.stdout)[-200:]}")

    templates = load_templates()
    if sub:  # 盘中重跑归档: 旧产物改名 *.prev.md(chain.md 通用规范; 只留最近一版不连环套娃)
        for s in ("02", "04", "06"):
            f = run_dir / ART[s]
            if f.exists():
                shutil.copy(f, run_dir / ART[s].replace(".md", ".prev.md"))
        prev02 = prev_contract(run_dir, "02")
    else:
        prev02 = None

    for step in steps:
        if dry:
            print(f"[dry] 跳过 claude 调用 step {step}")
            continue
        prompt = templates[step].replace("{date_dash}", date_dash) \
            .replace("{date}", date).replace("{run_dir}", str(run_dir).replace("\\", "/"))
        fail_reason, done = None, False
        for attempt in range(1, MAX_RETRY + 2):
            p = prompt if not fail_reason else \
                prompt + f"\n\n[驱动器回炉 {attempt - 1}/{MAX_RETRY}] 上次失败原因: {fail_reason}。只修此问题, 产物要求不变。"
            since = time.time()
            rc, usage, cost, dur = call_claude(p)
            log_tokens(date, slot, step, attempt, usage, cost, dur)
            text, err = read_artifact(run_dir, step, since)
            if err:
                fail_reason = err
                continue
            so = sentinel_ok(text, step, date)
            if step == "blind" and so == "FAIL":
                c, _ = contract_of(text)
                issues = (c or {}).get("issues", [])
                if attempt > MAX_RETRY:
                    sys.exit("盲审复审仍 FAIL, 链中止")
                # 盲审 FAIL → 带意见回炉 06 一次, 再复审
                c06, _ = contract_of((run_dir / ART["06"]).read_text(encoding="utf-8"))
                p06 = templates["06"].replace("{date_dash}", date_dash).replace("{date}", date) \
                    .replace("{run_dir}", str(run_dir).replace("\\", "/")) + \
                    f"\n\n[盲审驳回] issues: {';'.join(issues)}。修订 06_verdict.md 回应这些意见。"
                since = time.time()
                _, u2, c2, d2 = call_claude(p06)
                log_tokens(date, slot, "06", attempt, u2, c2, d2)
                # 回炉 06 必须重验+换约再进盲审复审(10/3 实录 bug: 旧约 emit plans=废版下单)
                t06, e06 = read_artifact(run_dir, "06", since)
                if e06 or sentinel_ok(t06 or "", "06", date) is not True:
                    sys.exit(f"盲审回炉 06 产物/哨兵异常({e06 or '哨兵缺失'}), 链中止(未 emit)")
                c06n, cerr06 = contract_of(t06)
                if cerr06:
                    sys.exit(f"盲审回炉 06 contract 异常({cerr06}), 链中止(未 emit)")
                v06fail = VALIDATORS["06"](c06n, ctx)
                if v06fail:
                    sys.exit(f"盲审回炉 06 校验败({v06fail}), 链中止(未 emit)")
                ctx["contracts"]["06"] = c06n
                continue
            if so is not True:
                fail_reason = f"哨兵缺失/错位(末行非 STEP_OK {step} {date})"
                continue
            c, cerr = contract_of(text)
            if cerr:
                fail_reason = cerr
                continue
            vfail = VALIDATORS[step](c, ctx)
            if vfail:
                fail_reason = vfail
                continue
            ctx["contracts"][step] = c
            # 回溯重验 01..当前(机械零 token, chain.md 交叉验证表)
            for done_step in ctx["contracts"]:
                t2 = (run_dir / ART[done_step]).read_text(encoding="utf-8")
                if sentinel_ok(t2, done_step, date) is not True:
                    sys.exit(f"回溯重验败: {done_step} 哨兵消失, 链中止")
            print(f"step {step} ✅ (attempt {attempt}, {dur:.0f}s)")
            done = True
            break
        if not done:
            sys.exit(f"step {step} 回炉 {MAX_RETRY} 次仍败({fail_reason}), 链中止 exit 1")

        if step == "02" and sub and prev02:  # 升级规则: 市况变→全链
            if ctx["contracts"]["02"].get("market_state") != prev02.get("market_state"):
                print(f"ESCALATE_FULL_CHAIN {date}: 市况 {prev02.get('market_state')}→{ctx['contracts']['02'].get('market_state')}")
                sys.exit(3)

    if "06" in steps:
        emit_plans(date_dash, slot, source, ctx["contracts"].get("06", {}), book)
    print(f"链完成 {date} slot {slot} steps {'→'.join(steps)}")

# ---------- 自测(不烧 token: 假产物喂校验器) ----------
def selftest():
    tmp = ROOT / "results/taoge_chain/selftest-tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    fails = []

    def mk(step, contract, sentinel="STEP_OK {s} 20260930"):
        c = json.dumps(contract, ensure_ascii=False)
        (tmp / ART[step]).write_text(f"# 假产物\n```contract\n{c}\n```\n{sentinel.format(s=step)}\n", encoding="utf-8")

    # 模板抽取
    t = load_templates()
    if set(t) < set(ART):
        fails.append(f"模板不全: {sorted(t)}")
    if "{date}" not in t["01"]:
        fails.append("01 模板缺占位符")

    ctx = {"date_dash": "2026-09-30", "nav": 100000, "sub": False, "contracts": {}}
    since = time.time() - 1

    # 01 正常
    mk("01", {"date": "2026-09-30", "sources": ["facts"], "digest": "x"})
    text, err = read_artifact(tmp, "01", since)
    if err or sentinel_ok(text, "01", "20260930") is not True or v01(contract_of(text)[0], ctx):
        fails.append("01 正例被误杀")
    ctx["contracts"]["01"] = contract_of(text)[0]

    # 02 方向→04 越界→05 名单不齐→06 code 缺位 的拒绝链
    mk("02", {"market_state": "有主线", "leading_layer": "板块层", "directions": ["机器人"]})
    ctx["contracts"]["02"] = contract_of((tmp / ART["02"]).read_text(encoding="utf-8"))[0]
    mk("04", {"candidates": [{"name": "三花智控", "direction": "机器人", "group": "方向", "trigger": "12.5"}], "断链说明": None})
    if v04(contract_of((tmp / ART["04"]).read_text(encoding="utf-8"))[0], ctx):
        fails.append("04 正例被误杀")
    bad04 = {"candidates": [{"name": "X", "direction": "AI", "group": "方向", "trigger": "1"}], "断链说明": None}
    if not v04(bad04, ctx):
        fails.append("04 direction 越界未抓")
    ctx["contracts"]["04"] = contract_of((tmp / ART["04"]).read_text(encoding="utf-8"))[0]
    if not v05({"verdicts": [{"name": "别的票", "result": "批准", "reason": "r"}]}, ctx):
        fails.append("05 名单不等未抓")
    mk("05", {"verdicts": [{"name": "三花智控", "result": "批准", "reason": "r"}]})
    ctx["contracts"]["05"] = contract_of((tmp / ART["05"]).read_text(encoding="utf-8"))[0]
    if v06({"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买",
            "trigger_price": "12.5", "qty": 800, "invalid_if": "破12"}], "no_trade": False}, ctx):
        fails.append("06 正例被误杀")
    for bad, tag in [
        ({"supersedes": "首裁", "actions": [{"name": "三花智控", "op": "买", "trigger_price": "12.5", "qty": 800}], "no_trade": False}, "缺 code 未抓"),
        ({"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买", "trigger_price": "12.5", "qty": 99999}], "no_trade": False}, "超 1.5 成未抓"),
        ({"supersedes": "首裁", "actions": [{"name": "野票", "code": "600127", "op": "买", "trigger_price": "1", "qty": 100}], "no_trade": False}, "05 未批准票未抓"),
        ({"supersedes": "首裁", "actions": [], "no_trade": True}, "no_trade 无条件单未抓"),
    ]:
        if not v06(bad, ctx):
            fails.append(f"06 {tag}")

    # 盲审哨兵 REVIEW_FAIL 分支
    mk("blind", {"verdict": "fail", "issues": ["编造证据"]}, sentinel="REVIEW_FAIL 20260930")
    if sentinel_ok((tmp / ART["blind"]).read_text(encoding="utf-8"), "blind", "20260930") != "FAIL":
        fails.append("REVIEW_FAIL 分支未识别")

    # plans 机械转换(假账本)
    book = {"source": "A-taoge", "cash": 100000, "positions": {},
            "orders": [{"id": "x", "code": "002050", "status": "open"}]}
    c06 = {"supersedes": "取代盘前决策:纠偏", "actions": [
        {"name": "三花智控", "code": "002050", "op": "买", "trigger_price": "12.5", "qty": 800, "invalid_if": "破12"}]}
    pf = PAPER / "plans" / "2026-09-30_A-taoge.md"
    # emit_plans 现在会自动调 matcher --import, 自测打桩防污染真账本
    orig_run = subprocess.run
    subprocess.run = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "JSON:{}\n", "stderr": ""})()
    try:
        emit_plans("2026-09-30", "0927", "A-taoge", c06, book)
    finally:
        subprocess.run = orig_run
    got = pf.read_text(encoding="utf-8")
    if "CXL | 002050" not in got or "BUY | 002050 | 12.5 | 800" not in got:
        fails.append("plans 转换缺 CXL/BUY 行")
    os.remove(pf)

    shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        print("SELFTEST FAIL:")
        for f in fails:
            print(" -", f)
        sys.exit(1)
    print("SELFTEST PASS: 模板抽取/哨兵/contract 校验器(正例不误杀+5 反例全抓)/盲审 FAIL 分支/plans 转换")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--slot")
    ap.add_argument("--steps")  # 显式覆盖, 如 02,04,06
    ap.add_argument("--review", action="store_true")
    ap.add_argument("--source", default="A-taoge")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dry", action="store_true", help="走全流程但不调 claude(冒烟用)")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return
    date = a.date
    date_dash = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    if a.review:
        run_chain(date, date_dash, "review", ["07"], a.source, a.dry)
        return
    if not a.slot and not a.steps:
        ap.error("需 --slot <HHMM> 或 --steps 01,02,... 或 --review")
    steps = a.steps.split(",") if a.steps else SLOT_STEPS.get(a.slot)
    if not steps:
        sys.exit(f"slot {a.slot} 不在映射表(SLOT_STEPS 与 chain.md 同步维护)")
    run_chain(date, date_dash, a.slot or "manual", steps, a.source, a.dry)

if __name__ == "__main__":
    main()
