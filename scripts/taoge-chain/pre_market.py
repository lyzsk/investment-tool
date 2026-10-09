#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pre_market.py — 盘前档引擎 v0(2026-10-08 夜, TODO §1.1; 10 导师单会话精简链)

定位: tzzb 导师线 0915 盘前档, qwen3:32b 本地单会话替代云端七步链, 省 quota(14万/周撑不起 11 条日链)。
产物对齐 run_taoge_chain.py 的 06_verdict 契约(md 正文 + ```contract JSON``` + STEP_OK 哨兵),
emit_plans 为其同名函数的精简复制(v0 不 import 主驱动器, 避免其模块级 apply_up 副作用)。
抽检(云端复核)与深度 contract 重算(v01..v06 校验器)为 v1 计划, 见 TODO §1.1。

用法(scripts/venv/Scripts/python.exe, cwd=项目根):
  python scripts/taoge-chain/pre_market.py --skill liuyiqing [--date 20261009]
  python scripts/taoge-chain/pre_market.py --skill liuyiqing --dry    # 只装配素材不调 32B
出口: 0=完成(plans 已落+matcher import) 1=素材/环境错 2=用法错 3=32B 产出校验败(ESCALATE, 云端兜底口)
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "models"))
from local_llm import chat, LocalLLMError, QWEN_DRAFT  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "scripts" / "dfcf" / "paper"
SKILL_DIR = ROOT / "skills"
CAP_SINGLE = 0.15        # 与 run_taoge_chain B6 同源口径; v1 接 params.yaml
CAP_TOTAL = 1.0          # 总仓硬顶(满仓文化, 不做 0.85 软帽)
SLOT_HM = "09:15"        # 盘前档挂单时间戳(生效语义 ≥09:31 由 invalid_if/驱动器承担)
CTX = 20480              # 10/8 实测 16k 挤爆输出(截断), 提到 20k
TAIL_MARK = "(32B盘前档)"  # 产物尾标, 复核 grep 即得, 不冒充云端链产物


def gpu_busy() -> bool:
    """与 llm_batch_tzzb.py 同款显存闸: 外部占用(总-ollama自驻留)>6G=让路(ASR/VLM 在跑)。"""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10)
        used = int(r.stdout.strip().splitlines()[0])
    except Exception:
        return False
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=5) as w:
            held = sum(int(m.get("size_vram", 0)) // 1024 // 1024
                       for m in json.loads(w.read().decode("utf-8")).get("models", []))
    except Exception:
        held = 0
    return (used - held) > 6000


def load_book(source: str) -> dict:
    f = PAPER / "books" / f"{source}.json"
    if not f.exists():
        sys.exit(f"账本不存在: {f}(先 matcher.mjs --init)")
    return json.loads(f.read_text(encoding="utf-8"))


def fetch_rules(skill: str, facts_head: str) -> tuple[str, str]:
    """规则面: 有向量索引→bge-m3 捞 top-8(带 id/标题); 冷启动→profile.md 全文。
    返回 (规则文本, 通道说明)。"""
    vec = SKILL_DIR / f"{skill}-skill" / "persona" / "rules_index.vec.json"
    if vec.exists():
        r = subprocess.run(["node", "scripts/md/gen_rules_index.mjs", "--skill", skill,
                            "--query", facts_head[:500], "--top", "8"],
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip(), "bge-m3 top-8(向量索引)"
        print(f"WARN: 向量检索败, 回退画像全文: {r.stderr[-120:]}")
    prof = SKILL_DIR / f"{skill}-skill" / "persona" / "profile.md"
    if not prof.exists():
        sys.exit(f"画像不存在(冷启动两无): {prof}")
    return prof.read_text(encoding="utf-8"), "profile.md 全文(冷启动, 规则库未建)"


def build_prompt(skill, source, facts, rules_text, book, date) -> str:
    nav = book["cash"] + sum(p["qty"] * p["cost"] for p in book["positions"].values())
    pos = json.dumps(book["positions"], ensure_ascii=False) if book["positions"] else "(空仓)"
    opens = json.dumps([o for o in book["orders"] if o["status"] == "open"], ensure_ascii=False) or "[]"
    if len(facts) > 12000:   # ctx 预算: 10/8 实测 21.5k 字 prompt 挤爆输出, 砍头尾保预算
        facts = facts[:10000] + "\n…(中略)…\n" + facts[-2000:]
    return f"""你是A股短线导师「{skill}」的盘前决策引擎。以下是你的机械画像/规则、今日盘前素材、模拟账本状态。
任务: 像{skill}本人一样, 给出今日盘前挂单计划(条件单), 只输出一次决策, 不反问。

# 你的画像/规则
{rules_text}

# 今日盘前素材(facts)
{facts}

# 模拟账本(source={source}, nav≈{nav:.0f})
- 持仓: {pos}
- 在市单(会被新计划全部撤换): {opens}

# 输出契约(严格遵守)
先写 ≤40 行的决策要点 md(情境判断/簇与票/风控门), 然后 fenced block 输出 ```contract JSON:
{{"supersedes":"<一句话血缘说明>","actions":[{{"name":"票名","code":"6位代码","op":"买"或"卖",
"trigger_price":"数字或简单公式如 昨收*0.97","qty":正整数,"anchor":"该票价格锚=昨收/现价的数值(与trigger_price同量级, 如 trigger 18.89 则 anchor≈19 上下, 禁填金额)","cancel_below":数字或null,
"stop_below":null,"rules":[{{"id":"规则id或画像条款","ctx":"为何此刻此票"}}],"invalid_if":"竞价门/失效/止损条款文本"}}],
"no_trade":false}}
约束: 单票金额=trigger_price×qty ≤ {CAP_SINGLE:.0%}×nav({nav*CAP_SINGLE:.0f} 元); 组合总金额 ≤ nav;
qty 按导师颗粒度(画像时刻纪律); 全部为 day 条件单语义; 行为红线=不打板/不追高开/每单带失效条款。
最后一行必须恰是: STEP_OK 06 {date}"""


def parse_contract(out: str):
    m = re.search(r"```contract\s*([\s\S]*?)```", out)
    raw = None
    if m:
        raw = m.group(1)
    else:
        # 容错(10/8 实测 32B 常漏围栏): 裸 JSON=首 { 到末 }
        s, e = out.find("{"), out.rfind("}")
        if s >= 0 and e > s:
            raw = out[s:e + 1]
    if raw is None:
        return None, "输出无 contract JSON"
    try:
        return json.loads(raw), ""
    except json.JSONDecodeError:
        # 截断容错: 数组未闭合时补 ]}(10/8 实测输出被 ctx 掐尾)
        for patch in ("]}", "}]}"):
            try:
                return json.loads(raw + patch), "(截断修复)"
            except json.JSONDecodeError:
                continue
        return None, f"contract JSON 解析败: {raw[-120:]}"


def validate(c: dict, book: dict, source: str) -> list:
    """v0 机械校验: schema + 代码/数量/价格 + 单票与总仓上限。深度 contract 重算=v1。"""
    errs = []
    acts = c.get("actions") or []
    if c.get("no_trade") and not acts:
        return []           # no_trade 契约内零 actions=合法
    nav = book["cash"] + sum(p["qty"] * p["cost"] for p in book["positions"].values())
    total = 0.0
    for i, a in enumerate(acts):
        tag = f"action[{i}:{a.get('name','?')}]"
        for k in ("name", "code", "op", "trigger_price", "qty", "anchor", "rules", "invalid_if"):
            if k not in a:
                errs.append(f"{tag} 缺字段 {k}")
        if not re.fullmatch(r"\d{6}", str(a.get("code", ""))):
            errs.append(f"{tag} code 非6位")
        if a.get("op") not in ("买", "卖"):
            errs.append(f"{tag} op 非买/卖")
        try:
            px = float(a["trigger_price"]); an = float(a["anchor"]); q = int(a["qty"])
            if px <= 0 or an <= 0 or q <= 0:
                errs.append(f"{tag} 价格/数量非正")
            if an / px > 1.6 or px / an > 1.6:   # 10/8 实测 32B 把金额(15112)当 anchor, 量级校验拦
                errs.append(f"{tag} anchor={an} 与 trigger={px} 量级不符(应≈昨收/现价)")
            amt = px * q
            total += amt
            # 10/9 六线实测: 32B 配仓常卡线超 21~112 块(15021 vs 15000), 2% 容差放行; 真超(>2%)仍拒
            if amt > nav * CAP_SINGLE * 1.02:
                errs.append(f"{tag} 单票 {amt:.0f} 超上限 {nav*CAP_SINGLE:.0f}(含2%容差)")
        except (TypeError, ValueError):
            errs.append(f"{tag} 价格/数量不可数值化(v1 接公式求值器)")
        if not isinstance(a.get("rules"), list) or not a["rules"]:
            errs.append(f"{tag} rules 空(每单必须有依据)")
    if acts and total > nav * CAP_TOTAL:
        errs.append(f"总仓 {total:.0f} 超 nav {nav:.0f}")
    return errs


def emit_plans(date_dash, source, contract, book) -> int:
    """run_taoge_chain.emit_plans 精简复制(v0): 新单+CXL 旧在市单, 行尾带 {TAIL_MARK}。"""
    acts = contract.get("actions") or []
    if not acts:
        print("no_trade/零 actions, 不写 plans")
        return 0
    open_by_code = {o["code"]: o for o in book["orders"] if o["status"] == "open"}
    plans_dir = PAPER / "plans"
    plans_dir.mkdir(exist_ok=True)
    f = plans_dir / f"{date_dash}_{source}.md"
    lines = []
    for a in acts:
        side = "BUY" if a["op"] == "买" else "SELL"
        code = str(a["code"])
        if code in open_by_code:
            lines.append(f"- {SLOT_HM} | {source} | CXL | {code} | - | - | - | - | 盘前档换单 {TAIL_MARK}")
        px = float(a["trigger_price"])
        conds = []
        if a.get("cancel_below") is not None:
            conds.append(f"cancel_below={float(a['cancel_below']):g}")
        if a.get("stop_below") is not None:
            conds.append(f"stop_below={float(a['stop_below']):g}")
        anchor_s = f"{float(a['anchor']):g}"
        note = f"盘前档32B: 触发{px:g} 失效:{a.get('invalid_if','')[:80]} {TAIL_MARK}"
        lines.append(f"- {SLOT_HM} | {source} | {side} | {code} | {px:g} | {a['qty']} | day | "
                     f"{anchor_s} | {';'.join(conds) or '-'} | {note}")
    with f.open("a", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")
    print(f"plans 落 {len(lines)} 行 → {f}")
    r = subprocess.run(["node", "scripts/dfcf/paper/matcher.mjs", "--import", str(f)],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = (r.stdout or "").strip().splitlines()
    print(f"matcher --import: {tail[-1] if tail else r.stderr[-200:]}")
    return len(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--date", default=None, help="yyyymmdd, 缺省=今天")
    ap.add_argument("--dry", action="store_true", help="只装配素材不调 32B")
    a = ap.parse_args()
    import datetime as dt
    date = a.date or dt.date.today().strftime("%Y%m%d")
    date_dash = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    source = f"A-{a.skill}" if a.skill != "buchitudou0" else "A-cb"

    run_dir = ROOT / "results" / f"{a.skill}_chain" / f"live-{date}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1. 素材(facts.mjs 幂等; 产物=共享目录 facts/<date>/<slot>/facts.md, 与主驱动器 build_facts 同契约)
    r = subprocess.run(["node", "scripts/dfcf/paper/facts.mjs", "--slot", "0915", "--date", date_dash],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    facts_f = PAPER / "facts" / date_dash / "0915" / "facts.md"
    if r.returncode != 0 or not facts_f.exists():
        print((r.stdout or "")[-300:], (r.stderr or "")[-300:])
        sys.exit(f"facts.mjs 未产出 {facts_f} (exit 1)")
    facts = facts_f.read_text(encoding="utf-8")
    print(f"facts {len(facts)} 字 ← {facts_f}")

    # 2. 账本
    book = load_book(source)

    # 3. 规则/画像通道
    rules_text, channel = fetch_rules(a.skill, facts)
    print(f"规则通道: {channel} ({len(rules_text)} 字)")

    if a.dry:
        prompt = build_prompt(a.skill, source, facts, rules_text, book, date)
        print(f"--dry: prompt 装配 {len(prompt)} 字, 校验/32B/plans 跳过")
        return

    # 4. 单会话 32B(显存闸: ASR 在跑则让路等待)
    for attempt in range(1, 4):
        if not gpu_busy():
            break
        print(f"显存被占(ASR/VLM?), 第{attempt}次等待 120s 让路…")
        import time; time.sleep(120)
    prompt = build_prompt(a.skill, source, facts, rules_text, book, date)
    try:
        out = chat(QWEN_DRAFT, prompt, timeout=900, num_ctx=CTX, temperature=0.2)
    except LocalLLMError as e:
        sys.exit(f"32B 调用败(exit 1): {e}")

    # 5. 解析+校验(败→带错误回炉 1 次, 10/9 六线实测 32B 卡线/公式价多为一次可纠正)
    def retry_with(reason):
        nonlocal out
        print(f"回炉: {reason[:120]}, 重调 32B…")
        return chat(QWEN_DRAFT, prompt + f"\n\n[校验器] 上次输出被拒: {reason}。"
                    f"修正后重新输出完整结果(md+```contract```+末行哨兵), 公式的 trigger_price 请直接给数字。",
                    timeout=900, num_ctx=CTX, temperature=0.2)
    c, err = parse_contract(out)
    if c is None:
        out = retry_with(err)
        c, err = parse_contract(out)
        if c is None:
            print(f"ESCALATE(回炉后仍无 contract): {err}\n--- 尾部 ---\n{out[-600:]}")
            sys.exit(3)
    errs = validate(c, book, source)
    if errs:
        out = retry_with("; ".join(errs))
        c2, _ = parse_contract(out)
        if c2 is None:
            print(f"ESCALATE(回炉后格式坏): {'; '.join(errs)}")
            sys.exit(3)
        errs = validate(c2, book, source)
        c = c2
        if errs:
            print("ESCALATE: 回炉后仍败:")
            for e in errs:
                print("  -", e)
            sys.exit(3)

    # 6. 落产物(06_verdict 同构) + plans
    verdict = run_dir / "06_verdict.md"
    body = re.sub(r"```contract[\s\S]*?```", "", out).strip()
    m = re.search(r"```contract\s*([\s\S]*?)```", out)
    verdict.write_text(
        f"# {a.skill} 盘前档 32B {date_dash}\n\n> 引擎=pre_market.py v0, 通道={channel}, 尾标={TAIL_MARK}\n\n"
        f"{body}\n\n```contract\n{json.dumps(c, ensure_ascii=False, indent=1)}\n```\n\nSTEP_OK 06 {date}\n",
        encoding="utf-8")
    print(f"06_verdict 落盘 → {verdict}")
    n = emit_plans(date_dash, source, c, book)
    print(f"盘前档完成: {a.skill} {date_dash} actions={len(c.get('actions') or [])} plans={n}")


if __name__ == "__main__":
    main()
