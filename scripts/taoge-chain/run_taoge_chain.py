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

def _cap_single():
    """B6(10/5): 单票仓位上限从 scripts/dfcf/paper/params.yaml 读(stock.cap_single), 缺文件/无 yaml 库回退 0.15"""
    try:
        import yaml  # anaconda 自带; 无则回退
        cfg = yaml.safe_load((ROOT / "scripts/dfcf/paper/params.yaml").read_text(encoding="utf-8"))
        v = float(cfg["stock"]["cap_single"])
        return v if 0 < v <= 1 else 0.15
    except Exception:
        return 0.15
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):  # Windows GBK 控制台防乱码
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CAP_SINGLE = _cap_single()  # B6: params.yaml 驱动, 见 _cap_single

def _test_floor():
    """10/7 晚定稿(分层): 首跑期总仓测试下限——真人拟人链 0.4 / tzzb 系 0.8(满仓文化), params.yaml 驱动; 缺省 (0,0)=不拦"""
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "scripts/dfcf/paper/params.yaml").read_text(encoding="utf-8"))
        tf = cfg.get("test_floor", {})
        a = float(tf.get("min_total_position", 0))
        b = float(tf.get("min_total_position_tzzb", a))
        return (v if 0 <= v <= 1 else 0 for v in (a, b))
    except Exception:
        return (0, 0)
TEST_FLOOR, TEST_FLOOR_TZZB = _test_floor()
CHAIN_MD = ROOT / "skills/taoge-skill/workflows/chain.md"
PAPER = ROOT / "scripts/dfcf/paper"
TOKEN_LOG = PAPER / "token_log.csv"
MAX_RETRY = 2
# headless 权限: acceptEdits=允许写产物文件不逐次询问; 模型只有 Write 需求, 不给 bash
# claude 入口=npm 全局 native exe(.cmd 走 cmd /c 有 8k 字符+转义坑, shim 是 sh 脚本 python 调不动)
_CLAUDE_EXE = os.path.join(os.environ.get("APPDATA", ""), r"npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe")
CLAUDE = [(_CLAUDE_EXE if os.path.exists(_CLAUDE_EXE) else "claude"),
          "-p", "--output-format", "json", "--permission-mode", "acceptEdits"]

# ---------- skill 参数化(10/4 盲区修复⑦: 同一驱动器多链, 差集全在这张表; 10/7 键正名 cb→buchitudou0) ----------
_SUB = ["02", "04", "06"]
_UP_SLOTS = {"0915": ["01", "02", "03", "04", "05", "06", "blind"],  # 盘前全链+盘中子链(10/7 4档→10/9 用户令扩9档对齐 taoge 时刻表)
             "0927": ["02", "04", "06"], "0945": ["02", "04", "06"], "1000": ["02", "04", "06"],
             "1030": ["02", "04", "06"], "1100": ["02", "04", "06"], "1127": ["02", "04", "06"],
             "1230": ["02", "04", "06"], "1300": ["02", "04", "06"],
             "1400": ["02", "04", "06"], "1430": ["02", "04", "06"], "1455": ["02", "04", "06"]}


def _up_cfg(up: str) -> dict:
    """bilibili UP 链配置工厂(10/7 A 级扩容): chain.md=taoge 模板盖章产物, 股票域 6 位码, A-E 规则 id。"""
    return {
        "chain_md": ROOT / f"skills/{up}-skill/workflows/chain.md",
        "source": f"A-{up}", "results_dir": f"{up}_chain",
        "slot_steps": dict(_UP_SLOTS),
        "art": {"01": "01_facts.md", "02": "02_analysis.md", "03b": "03_debate_bull.md", "03s": "03_debate_bear.md",
                "03j": "03_debate.md", "04": "04_plan.md", "05": "05_risk.md", "06": "06_verdict.md",
                "07": "07_review.md", "blind": "validate_report.md"},
        "expand": {"03": ["03b", "03s", "03j"]},
        "rule_id": r"[A-Z]\d+", "high_pos": set(),  # UP 规则编号冷启动期不定型, 放宽为字母+数字; 高位档位待 persona 成型再收
        "cap_ratio": CAP_SINGLE, "code_re": r"\d{6}", "floor_key": "like",
    }

SKILL_CFG = {
    "taoge": {
        "chain_md": ROOT / "skills/taoge-skill/workflows/chain.md",
        "source": "A-taoge", "results_dir": "taoge_chain",
        "slot_steps": {"0915": ["01", "02", "03", "04", "05", "06", "blind"],
                       "0927": _SUB, "0945": _SUB, "1000": _SUB, "1030": _SUB,
                       "1127": _SUB, "1230": _SUB, "1400": _SUB, "1430": _SUB, "1455": _SUB},
        "art": {"01": "01_facts.md", "02": "02_analysis.md", "03b": "03_debate_bull.md", "03s": "03_debate_bear.md",
                "03j": "03_debate.md", "04": "04_plan.md", "05": "05_risk.md", "06": "06_verdict.md",
                "07": "07_review.md", "blind": "validate_report.md"},
        "expand": {"03": ["03b", "03s", "03j"]},  # 03 拆环(10/4): 多/空独立会话真对抗, 裁判读双方陈词
        "rule_id": r"[A-E]\d+", "high_pos": {"A4", "B43", "B45", "C24"},  # 高位类规则引用必带周期档位(A23)
        "cap_ratio": CAP_SINGLE, "code_re": r"\d{6}", "floor_key": "like",  # B6(10/5): 单票上限 params.yaml 驱动
    },
    "buchitudou0": {   # 10/7 键正名(用户令): 原键 "cb", sys_job param cb:HHMM→buchitudou0:HHMM
        "chain_md": ROOT / "skills/buchitudou0-skill/workflows/chain.md",
        "source": "A-cb", "results_dir": "buchitudou0_chain",
        "slot_steps": {"0915": ["01", "02", "04", "05", "06", "blind"],  # 无 03(v1 砍, TODO 拆环)
                       "0927": ["02", "04", "06"], "0935": ["02", "04", "06"], "1000": ["02", "04", "06"]},
        "art": {"01": "01_facts.md", "02": "02_analysis.md", "04": "04_plan.md", "05": "05_risk.md",
                "06": "06_verdict.md", "07": "07_review.md", "blind": "validate_report.md"},
        "expand": {},
        "rule_id": r"R\d+", "high_pos": set(),
        "cap_ratio": 1.0, "floor_key": "tzzb",  # cb 仓位纪律(10/4 用户拍板): T+0 转债不做仓位管理——有把握全仓进, 没把握半仓+半仓; 上限=全仓
        "code_re": r"(11|12)\d{4}",  # 转债代码闸: 禁拿正股冒充转债
    },
    "qushitiange": _up_cfg("qushitiange"),   # 10/7 A 级扩容: 趋势天哥链(chain.md=taoge 模板盖章)
    "lubenyuan": _up_cfg("lubenyuan"),       # 10/7 A 级扩容: 卢本圆链
    "liuyiqing": _up_cfg("liuyiqing"),                    # 10/7 晚: tzzb 导师独立链
    "lianghuaxiaohao": _up_cfg("lianghuaxiaohao"),                    # 10/7 晚: tzzb 导师独立链
    "a658": _up_cfg("a658"),                    # 10/7 晚: tzzb 导师独立链
    "bianbenling": _up_cfg("bianbenling"),                    # 10/7 晚: tzzb 导师独立链
    "xingjianye": _up_cfg("xingjianye"),                    # 10/7 晚: tzzb 导师独立链
    "daxingdaxingdadangxing": _up_cfg("daxingdaxingdadangxing"),                    # 10/7 晚: tzzb 导师独立链
    "gaogailvfuli": _up_cfg("gaogailvfuli"),                    # 10/7 晚: tzzb 导师独立链
    "xuanqiucaijing": _up_cfg("xuanqiucaijing"),                    # 10/7 晚: tzzb 导师独立链
    "stzhilang": _up_cfg("stzhilang"),                    # 10/7 晚: tzzb 导师独立链
    "chong5000w": _up_cfg("chong5000w"),                    # 10/7 晚: tzzb 导师独立链

}
def apply_skill(name):
    global SKILL, CHAIN_MD, SLOT_STEPS, ART, EXPAND, RESULTS_DIR
    SKILL = SKILL_CFG[name]
    CHAIN_MD, SLOT_STEPS, ART, EXPAND = SKILL["chain_md"], SKILL["slot_steps"], SKILL["art"], SKILL["expand"]
    RESULTS_DIR = SKILL["results_dir"]
apply_skill("taoge")  # 默认 taoge, main 里按 --skill 重挂

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

def v03side(want):
    def v(c, ctx):
        if c.get("side") != want:
            return f"side 非法: {c.get('side')}(应为{want})"
        if len(c.get("strongest_args") or []) < 2:
            return "strongest_args<2 条"
        if not c.get("honest_weakness"):
            return "honest_weakness 空(不许藏弱)"
    return v

def v04(c, ctx):
    cands = c.get("candidates") or []
    if not cands and not c.get("断链说明"):
        return "candidates 空且无断链说明(B72)"
    dirs = set(ctx["contracts"].get("02", {}).get("directions", []))
    for x in cands:
        if x.get("group") == "方向" and x.get("direction") not in dirs:
            return f"方向组 {x.get('name')} 的 direction '{x.get('direction')}' ∉ 02.directions"
        code = str(x.get("code") or "")
        if code and code not in ("None", "null") and not re.fullmatch(r"\d{6}", code):
            return f"{x.get('name')} code 非 6 位数字: {code}"  # C7-①: code 供 04 后拉价格锚
    # 扩池提案(可选; facts 覆盖率 WARN 触发时 prompt 义务必填)——结构化留给用户确认后落 pools.json
    props = c.get("pool_proposals")
    if props is not None and (
        not isinstance(props, list)
        or any(not isinstance(p, dict) or not p.get("direction") or not isinstance(p.get("names"), list) or not p["names"] for p in props)
    ):
        return "pool_proposals 格式非法(须 [{\"direction\":\"...\",\"names\":[\"票名\",...]}])"

def v05(c, ctx):
    got = {v.get("name") for v in (c.get("verdicts") or [])}
    want = {x.get("name") for x in (ctx["contracts"].get("04", {}).get("candidates") or [])}
    if got != want:
        return f"05 名单 != 04 候选: 缺{sorted(want - got)} 多{sorted(got - want)}"
    for v in c.get("verdicts") or []:
        if v.get("result") not in ("批准", "否决", "条件批准"):
            return f"verdict 非法: {v.get('result')}"

def limit_of(code):
    """板限%(与 snapshot.mjs limitOf 同款; 2026-07-06 起主板 ST 同 10% 无需特判)"""
    if re.match(r"^(30|68)", code): return 19.7
    if re.match(r"^(8|4|920)", code): return 29.7
    return 9.7

def resolve_px(v, prev):
    """trigger_price 求值(C9-②): 数值直返; `Z*0.97`/`0.97*Z` 公式用前收代换(Z|P0|前收|昨收);
    不可求值=(None, None)。返回(数值, 公式原文|None)"""
    if v is None: return None, None
    s = str(v).strip()
    try: return float(s), None
    except ValueError: pass
    if not prev: return None, None
    m = re.search(r"(?:(\d+(?:\.\d+)?)\s*\*\s*(?:Z|z|P0|前收|昨收)|(?:Z|z|P0|前收|昨收)\s*\*\s*(\d+(?:\.\d+)?))", s)
    if m:
        coef = float(m.group(1) or m.group(2))
        return round(prev * coef, 3), s
    return None, None

def v06(c, ctx):
    acts = c.get("actions") or []
    approved = {v["name"] for v in (ctx["contracts"].get("05", {}).get("verdicts") or [])
                if v.get("result") in ("批准", "条件批准")}
    snaps = ctx.get("snap") or {}
    sk = ctx["skill"]  # skill 差集(10/4 参数化): 规则 id 正则/高位类集合/code 闸/仓位上限
    for a in acts:
        if a.get("name") not in approved:
            return f"06 标的 {a.get('name')} ∉ 05 批准集"
        if not re.fullmatch(sk["code_re"], str(a.get("code", ""))):
            return f"{a.get('name')} code 不符本链闸({sk['code_re']}): {a.get('code')}"
        if not (isinstance(a.get("qty"), int) and a["qty"] > 0):
            return f"{a.get('name')} qty 非正整数: {a.get('qty')}"
        # 规则引用情境校验(10/4 用户立法): 引用=结构化 {"id","ctx"}, ctx=该规则情境字段当前是否满足的判定
        for r in (a.get("rules") or []):
            if not re.fullmatch(sk["rule_id"], str(r.get("id", ""))):
                return f"{a.get('name')} 引用规则 id 非法: {r.get('id')}"
            rctx = str(r.get("ctx", ""))
            if len(rctx) < 10:
                return f"{a.get('name')} 引用 {r.get('id')} 缺情境满足判定(引用规则必须先答情境是否满足, 襄阳案=A4/C24 情境错配)"
            if r["id"] in sk["high_pos"] and not re.search(r"冰点|修复|主升", rctx):
                return f"{a.get('name')} 引用高位类规则 {r['id']} 未给周期档位(冰点/修复/主升, A23)"
        # C7-①+C9-②: 价格求值(数值或公式)→ 锚定前收的当日理论区间校验(防 9/28 大亚 14.00 型编造价)
        code = str(a["code"])
        prev = snaps.get(code, {}).get("prevClose")
        px, formula = resolve_px(a.get("trigger_price"), prev)
        if px is None:
            return f"{a.get('name')} trigger_price 非数值/可求值公式(Z*系数): {a.get('trigger_price')}"
        a["_px"], a["_formula"] = px, formula  # 回填取数口, emit_plans 直接用(不再二次解析)
        if prev:
            lim = limit_of(code)
            lo, hi = prev * (1 - lim / 100 - 0.005), prev * (1 + lim / 100 + 0.005)
            if not (lo <= px <= hi):
                return f"{a.get('name')} 挂单价 {px} 出当日理论区间 [{lo:.2f},{hi:.2f}](前收{prev}, 板限{lim:g}%)=编造嫌疑 C7-①"
        else:
            print(f"WARN: {a.get('name')}({code}) 无价格锚快照, 验价降级(matcher 第四道防线兜底)")
        try:  # anchor=模型自报估算锚(它认为该票现在的价位), matcher 按 |前收/现价-锚|>3% 自动废单——编锚=单废(10/3 大亚教训)
            anchor = float(a.get("anchor"))
            if anchor <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return f"{a.get('name')} anchor 缺失/非正数(取 facts 快照价, 禁凭印象编): {a.get('anchor')}"
        # C7-②: 结构化失效条件
        for k in ("cancel_below", "stop_below"):
            if a.get(k) is not None and not (isinstance(a.get(k), (int, float)) and a[k] > 0):
                return f"{a.get('name')} {k} 非正数: {a.get(k)}"
        if a.get("stop_below") is not None and a.get("op") != "卖":
            return f"{a.get('name')} stop_below 只许卖单带(止损哨兵)"
        cap = sk["cap_ratio"] * ctx["nav"]  # 单票上限(skill 差集: taoge=params.yaml / cb=1.0 全仓; 驱动器重算非模型自声明)
        if a.get("op") == "买" and a["_px"] * a["qty"] > cap:
            return f"{a.get('name')} 金额 {a['_px'] * a['qty']:.0f} 超单票上限 {cap:.0f}"
    if c.get("no_trade") and not acts:
        return "no_trade=true 但 actions 无进场条件单(三选一契约)"
    # 10/7 晚定稿(分层): 首跑期测试下限——真人拟人链 0.4 / tzzb 系 0.8, 防空仓白测; 可多票凑足
    _floor = {"tzzb": TEST_FLOOR_TZZB, "like": TEST_FLOOR}.get(sk.get("floor_key"), TEST_FLOOR)
    if _floor and not c.get("no_trade"):
        _total_buy = sum(a["_px"] * a["qty"] for a in acts if a.get("op") == "买")
        if _total_buy < _floor * ctx["nav"]:
            return f"总买仓 {_total_buy:.0f} < 测试下限 {_floor*100:.0f}% nav(10/7 分层令, 防空仓白测; 可多票凑足)——重裁"
    if ctx["sub"] and "首裁" not in str(c.get("supersedes", "")) \
            and not re.search(r"维持|取代", str(c.get("supersedes", ""))):
        return "盘中重跑 supersedes 未显式含 维持/取代"
    if not ctx["sub"] and not re.search(r"首[裁日次]|回炉|首日建链", str(c.get("supersedes", ""))):
        return "盘前首裁 supersedes 应含'首裁/首日/回炉'(10/8 修: 模型常用'回炉N版'表述首日, 不再只认'首裁'二字)"

def v07(c, ctx):
    if not c.get("预案对照"):
        return "预案对照 空"

def vblind(c, ctx):
    if c.get("verdict") not in ("pass", "fail"):
        return "盲审 contract verdict 非法"

VALIDATORS = {"01": v01, "02": v02, "03b": v03side("多"), "03s": v03side("空"), "03j": v03, "04": v04, "05": v05, "06": v06, "07": v07, "blind": vblind}

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
WINDOW_RE = re.compile(r"usage limit|5-hour|429|quota", re.I)   # 同 cruise_loop(k3 立法口径)
WINDOW_DEFER_S = 2700                                           # 顺延 45min(10/4 用户: 顺延不跳过)

def call_claude(prompt):
    """10/7 晚修正(用户令: 模仿 k3 cruise_loop 语义): window 错误=顺延不跳过——
    无限顺延(每次 45min)直到窗口重置, 不设次数上限, 欠账永远留账不丢。"""
    while True:
        t0 = time.time()
        r = subprocess.run(CLAUDE + [prompt], cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=1800)
        dur = time.time() - t0
        blob = (r.stdout or "") + (r.stderr or "")
        if WINDOW_RE.search(blob):
            print(f"⚠ API window 限: 顺延 {WINDOW_DEFER_S // 60}min 后重试(欠账留账不跳过, k3 语义)")
            time.sleep(WINDOW_DEFER_S)
            continue
        break
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
def snap_candidates(run_dir, c04):
    """C7-①: 04 后按候选票 code 机械拉价格锚快照(snapshot.mjs 多源 fallback)→ cand_snap.md/.json
    06 的 trigger_price 锚定它+盲审⑥维度消费它; 部分失败不挡链(消费方按票降级)"""
    codes = [str(x.get("code")) for x in (c04.get("candidates") or [])]
    codes = [c for c in codes if re.fullmatch(r"\d{6}", c)]
    if not codes:
        print("cand_snap: 04 无 code 候选, 跳过价格锚")
        return {}
    js, md = run_dir / "cand_snap.json", run_dir / "cand_snap.md"
    r = subprocess.run(["node", "scripts/dfcf/paper/snapshot.mjs", "--codes", ",".join(codes),
                        "--json", str(js), "--md", str(md)],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    if r.returncode == 2:
        print(f"WARN: 候选票快照源全灭, 06 价格锚校验降级: {(r.stdout or r.stderr or '')[-150:]}")
    snaps = {}
    if js.exists():
        try:
            snaps = {s["code"]: s for s in json.loads(js.read_text(encoding="utf-8"))["snaps"] if not s.get("error")}
        except (json.JSONDecodeError, KeyError):
            print("WARN: cand_snap.json 解析败, 验价降级")
    print(f"cand_snap: {len(snaps)}/{len(codes)} 票有价格锚 → {md.name}")
    return snaps

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
            lines.append(f"- {hm} | {source} | CXL | {code} | - | - | - | - | 取代旧单(slot {slot} 终裁)")
        px = a.get("_px") or float(a.get("trigger_price"))  # v06 已回填求值结果(公式价代换后数值)
        conds = []
        if a.get("cancel_below"):  # C7-②: 失效条件结构化(matcher 哨兵执行, 不再只是 note 文字)
            conds.append(f"cancel_below={float(a['cancel_below']):g}")
        if a.get("stop_below"):
            conds.append(f"stop_below={float(a['stop_below']):g}")
        note = f"链终裁: 触发{px:g}" + (f"(公式 {a['_formula']})" if a.get("_formula") else "")
        if a.get("invalid_if"):
            note += f" 失效:{a['invalid_if']}"
        # plans 行第 8/9 字段=结构化 anchor+cond(matcher 锚偏离守卫+失效哨兵的取数口; v06 已保证 anchor 数值)
        anchor_s = f"{float(a['anchor']):g}" if a.get("anchor") is not None else "-"
        lines.append(f"- {hm} | {source} | {side} | {code} | {px:g} | {a['qty']} | day | {anchor_s} | {';'.join(conds) or '-'} | {note}")
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

def neg_warn() -> str:
    """负例警示卡随机 2 条(TODO §1.3 的 05 消费钩子, 10/8 夜)。
    negstats.md(gen_tzzb_negstats.py 产出)缺失/坏=空串, fail-open 零影响链。"""
    import random
    f = ROOT / "skills" / "tzzb-skill" / "references" / "negstats.md"
    try:
        text = f.read_text(encoding="utf-8")
        seg = text.split("## 05 注入警示卡", 1)[1].split("##", 1)[0]
        cards = [l.strip("- \r\n") for l in seg.splitlines() if l.strip().startswith("- **")]
        if not cards:
            return ""
        pick = random.sample(cards, min(2, len(cards)))
        return "\n\n# 负例警示(真实亏家实录, 决策须自证不犯同类):\n- " + "\n- ".join(pick)
    except Exception:
        return ""

# ---------- 主链 ----------
def run_chain(date, date_dash, slot, steps, source, dry=False):
    run_dir = ROOT / "results" / RESULTS_DIR / f"live-{date}"
    run_dir.mkdir(parents=True, exist_ok=True)
    sub = steps != SLOT_STEPS["0915"] and steps != ["07"]
    book = load_book(source)
    ctx = {"date_dash": date_dash, "nav": book_nav(book), "sub": sub, "contracts": {}, "skill": SKILL}

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

    for step in [s for x in steps for s in EXPAND.get(x, [x])]:  # 03→03b/03s/03j 拆环展开(10/4)
        if dry:
            print(f"[dry] 跳过 claude 调用 step {step}")
            continue
        prompt = templates[step].replace("{date_dash}", date_dash) \
            .replace("{date}", date).replace("{run_dir}", str(run_dir).replace("\\", "/"))
        if step == "05":  # 负例警示注入(TODO §1.3 钩子): fail-open, negstats 不在=零追加
            prompt += neg_warn()
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
                    # C9-①(10/4): 死链修复——回炉版校验败不再直接 abort(9/29 实证: 公式价被数值校验拒→链中止无产出),
                    # 再给一次带失败原因的回炉; 仍败才中止。公式价合法性本体由 C9-② resolve_px 支持。
                    print(f"盲审回炉 06 校验败({v06fail}), 再给一次带原因回炉")
                    p06r = templates["06"].replace("{date_dash}", date_dash).replace("{date}", date) \
                        .replace("{run_dir}", str(run_dir).replace("\\", "/")) + \
                        f"\n\n[驱动器回炉] 上版 contract 校验败: {v06fail}。只修此问题, 重写 06_verdict.md。"
                    since2 = time.time()
                    _, u3, c3, d3 = call_claude(p06r)
                    log_tokens(date, slot, "06", attempt, u3, c3, d3)
                    t06b, e06b = read_artifact(run_dir, "06", since2)
                    if e06b or sentinel_ok(t06b or "", "06", date) is not True:
                        sys.exit(f"盲审回炉 06 二版产物/哨兵异常({e06b or '哨兵缺失'}), 链中止(未 emit)")
                    c06b, cerr06b = contract_of(t06b)
                    if cerr06b:
                        sys.exit(f"盲审回炉 06 二版 contract 异常({cerr06b}), 链中止(未 emit)")
                    v06fb = VALIDATORS["06"](c06b, ctx)
                    if v06fb:
                        sys.exit(f"盲审回炉 06 二次校验仍败({v06fb}), 链中止(未 emit)")
                    c06n = c06b
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
            if step == "04":  # C7-①: 04 落地即拉候选票价格锚(v06 校验+盲审⑥维度消费)
                ctx["snap"] = snap_candidates(run_dir, c)
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

    # 扩池提案自动落 pools.json(10/4 用户拍板: 04 提案 v04 校验后机械 merge 零 token; 失败仅 WARN 不中止链)
    props = (ctx["contracts"].get("04") or {}).get("pool_proposals")
    if props:
        pf = run_dir / "pool_proposals.json"
        pf.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run(["node", "scripts/dfcf/paper/pool_merge.mjs", "--file", str(pf)],
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        tail = (r.stdout or "").strip().splitlines()
        print(f"pool_merge: {tail[-1] if tail else (r.stderr or '')[-200:]}")
        if r.returncode != 0:
            print("WARN: 扩池提案落 pools.json 失败(链不中止, 提案已存 run_dir/pool_proposals.json)")

    if "06" in steps:
        emit_plans(date_dash, slot, source, ctx["contracts"].get("06", {}), book)
    print(f"链完成 {date} slot {slot} steps {'→'.join(steps)}")

# ---------- 自测(不烧 token: 假产物喂校验器) ----------
def selftest():
    global TEST_FLOOR, TEST_FLOOR_TZZB
    TEST_FLOOR, TEST_FLOOR_TZZB = 0, 0   # 闸单测不受首跑期仓位下限干扰(夹具仓位小; 进程终止无需恢复)
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

    ctx = {"date_dash": "2026-09-30", "nav": 100000, "sub": False, "contracts": {}, "skill": SKILL_CFG["taoge"]}
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

    # 03 拆环三件套校验器(多方/空方独立立场 + 裁判)
    if v03side("多")({"side": "多", "strongest_args": ["a", "b"], "honest_weakness": "w"}, ctx):
        fails.append("03b 正例被误杀")
    if not v03side("空")({"side": "多", "strongest_args": ["a", "b"], "honest_weakness": "w"}, ctx):
        fails.append("03s 立场错位未抓")
    if not v03side("多")({"side": "多", "strongest_args": ["a"], "honest_weakness": "w"}, ctx):
        fails.append("03b 论据不足未抓")
    if not v03side("多")({"side": "多", "strongest_args": ["a", "b"]}, ctx):
        fails.append("03b 藏弱未抓")
    if v03({"winner": "多", "decisive_reason": "r"}, ctx):
        fails.append("03j 正例被误杀")
    mk("04", {"candidates": [{"name": "三花智控", "direction": "机器人", "group": "方向", "trigger": "12.5"}], "断链说明": None})
    if v04(contract_of((tmp / ART["04"]).read_text(encoding="utf-8"))[0], ctx):
        fails.append("04 正例被误杀")
    bad04 = {"candidates": [{"name": "X", "direction": "AI", "group": "方向", "trigger": "1"}], "断链说明": None}
    if not v04(bad04, ctx):
        fails.append("04 direction 越界未抓")
    # 扩池提案(10/4 双池制): 合规不误杀 / 缺 names 必抓
    ok04p = {"candidates": [{"name": "三花智控", "direction": "机器人", "group": "方向", "trigger": "1"}], "断链说明": None,
             "pool_proposals": [{"direction": "医药", "names": ["康希诺"]}]}
    if v04(ok04p, ctx):
        fails.append("04 合规扩池提案被误杀")
    if not v04({**ok04p, "pool_proposals": [{"direction": "医药"}]}, ctx):
        fails.append("04 非法扩池提案(缺 names)未抓")
    ctx["contracts"]["04"] = contract_of((tmp / ART["04"]).read_text(encoding="utf-8"))[0]
    if not v05({"verdicts": [{"name": "别的票", "result": "批准", "reason": "r"}]}, ctx):
        fails.append("05 名单不等未抓")
    mk("05", {"verdicts": [{"name": "三花智控", "result": "批准", "reason": "r"}]})
    ctx["contracts"]["05"] = contract_of((tmp / ART["05"]).read_text(encoding="utf-8"))[0]
    if v06({"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买",
            "trigger_price": "12.5", "qty": 800, "anchor": "12.4", "invalid_if": "破12"}], "no_trade": False}, ctx):
        fails.append("06 正例被误杀")
    for bad, tag in [
        ({"supersedes": "首裁", "actions": [{"name": "三花智控", "op": "买", "trigger_price": "12.5", "qty": 800, "anchor": "12.4"}], "no_trade": False}, "缺 code 未抓"),
        ({"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买", "trigger_price": "12.5", "qty": 99999, "anchor": "12.4"}], "no_trade": False}, "超 1.5 成未抓"),
        ({"supersedes": "首裁", "actions": [{"name": "野票", "code": "600127", "op": "买", "trigger_price": "1", "qty": 100, "anchor": "1"}], "no_trade": False}, "05 未批准票未抓"),
        ({"supersedes": "首裁", "actions": [], "no_trade": True}, "no_trade 无条件单未抓"),
        ({"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买", "trigger_price": "12.5", "qty": 800}], "no_trade": False}, "缺 anchor 未抓"),
        ({"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买", "trigger_price": "12.5", "qty": 800, "anchor": "P0*0.97"}], "no_trade": False}, "anchor 公式价未抓"),
        ({"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买", "trigger_price": "12.5", "qty": 800, "anchor": "12.4", "rules": [{"id": "A4"}]}], "no_trade": False}, "规则引用缺情境判定未抓"),
        ({"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买", "trigger_price": "12.5", "qty": 800, "anchor": "12.4", "rules": [{"id": "A4", "ctx": "板块昨日高潮=是, 故不追"}]}], "no_trade": False}, "高位类规则引用缺周期档位未抓"),
    ]:
        if not v06(bad, ctx):
            fails.append(f"06 {tag}")
    # 情境校验正例(带合规 rules 引用不误杀)
    if v06({"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买",
            "trigger_price": "12.5", "qty": 800, "anchor": "12.4",
            "rules": [{"id": "A4", "ctx": "情境判定: 当前=修复期, 机器人板块昨日非高潮, A4 情境不满足, 不构成目送依据"}]}], "no_trade": False}, ctx):
        fails.append("06 带合规规则引用正例被误杀")

    # C7-①/C9-② 价格锚+公式价(带快照锚的 ctx; 002050 主板/000910 主板/300750 创业板20cm)
    ctx2 = dict(ctx, snap={"002050": {"prevClose": 12.6}, "000910": {"prevClose": 7.6}, "300750": {"prevClose": 286.8}})
    ctx2["contracts"] = {**ctx["contracts"], "05": {"verdicts": [  # 三票全批准, 让用例真正走到锚校验分支
        {"name": n, "result": "批准", "reason": "r"} for n in ("三花智控", "大亚", "宁德时代")]}}
    f06 = {"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买",
            "trigger_price": "Z*0.97", "qty": 800, "anchor": "12.5", "cancel_below": 11.5, "invalid_if": "破11.5"}], "no_trade": False}
    if v06(f06, ctx2) or abs(f06["actions"][0]["_px"] - 12.222) > 1e-6:
        fails.append("公式价 Z*0.97 正例被误杀/求值错")
    f20 = {"supersedes": "首裁", "actions": [{"name": "宁德时代", "code": "300750", "op": "买",
            "trigger_price": "Z*1.15", "qty": 30, "anchor": "286.5"}], "no_trade": False}  # 20cm 追板单不得被 10% 一刀切误杀
    if v06(f20, ctx2):
        fails.append("20cm 板限分档误杀追板单")
    for bad, tag in [
        ({"supersedes": "首裁", "actions": [{"name": "大亚", "code": "000910", "op": "买", "trigger_price": "14.00", "qty": 800, "anchor": "7.6"}], "no_trade": False}, "编造价(9/28 大亚案)未抓"),
        ({"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买", "trigger_price": "突破前高", "qty": 800, "anchor": "12.5"}], "no_trade": False}, "不可求值公式未抓"),
        ({"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买", "trigger_price": "12.5", "qty": 800, "anchor": "12.5", "stop_below": 11.9}], "no_trade": False}, "买单带 stop_below 未抓"),
        ({"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买", "trigger_price": "12.5", "qty": 800, "anchor": "12.5", "cancel_below": -1}], "no_trade": False}, "cancel_below 负数未抓"),
        ({"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买", "trigger_price": "1.0", "qty": 800, "anchor": "12.5"}], "no_trade": False}, "价格锚区间下界越界未抓"),
    ]:
        if not v06(bad, ctx2):
            fails.append(f"06 价格锚 {tag}")
    if not v04({"candidates": [{"name": "X", "direction": "机器人", "group": "方向", "trigger": "1", "code": "123"}], "断链说明": None}, ctx):
        fails.append("04 code 非 6 位未抓")

    # 盲审哨兵 REVIEW_FAIL 分支
    mk("blind", {"verdict": "fail", "issues": ["编造证据"]}, sentinel="REVIEW_FAIL 20260930")
    if sentinel_ok((tmp / ART["blind"]).read_text(encoding="utf-8"), "blind", "20260930") != "FAIL":
        fails.append("REVIEW_FAIL 分支未识别")

    # plans 机械转换(假账本; 公式价+cond 列断言)
    book = {"source": "A-taoge", "cash": 100000, "positions": {},
            "orders": [{"id": "x", "code": "002050", "status": "open"}]}
    a_form = {"name": "大亚", "code": "000910", "op": "卖", "trigger_price": "Z*1.02", "qty": 1000, "anchor": "7.55", "stop_below": 8.1}
    a_form["_px"], a_form["_formula"] = resolve_px("Z*1.02", 7.6)  # 模拟 v06 回填后的取数口
    c06 = {"supersedes": "取代盘前决策:纠偏", "actions": [
        {"name": "三花智控", "code": "002050", "op": "买", "trigger_price": "12.5", "qty": 800, "anchor": "12.4", "invalid_if": "破12"}, a_form]}
    pf = PAPER / "plans" / "2026-09-30_A-taoge.md"
    # emit_plans 现在会自动调 matcher --import, 自测打桩防污染真账本
    orig_run = subprocess.run
    subprocess.run = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "JSON:{}\n", "stderr": ""})()
    try:
        emit_plans("2026-09-30", "0927", "A-taoge", c06, book)
    finally:
        subprocess.run = orig_run
    got = pf.read_text(encoding="utf-8")
    if "CXL | 002050" not in got or "BUY | 002050 | 12.5 | 800 | day | 12.4 |" not in got:
        fails.append("plans 转换缺 CXL/BUY 行(或 anchor 字段)")
    if "SELL | 000910 | 7.752 | 1000 | day | 7.55 | stop_below=8.1 |" not in got:
        fails.append("plans 公式价代换/anchor/stop_below cond 列缺失")
    os.remove(pf)

    # cb 链(10/4 盲区修复⑦): 模板抽取 + v06 cb 模式(转债 code 闸/R 规则 id/3 成上限)
    apply_skill("buchitudou0")
    tcb = load_templates()
    if set(tcb) < set(ART) - {"07"}:
        fails.append(f"cb chain.md 模板不全: {sorted(set(ART) - {'07'} - set(tcb))}")
    cctx = {"date_dash": "2026-09-30", "nav": 100000, "sub": False,
            "contracts": {"05": {"verdicts": [{"name": "测试转债", "result": "批准"}]}}, "skill": SKILL_CFG["buchitudou0"]}
    if v06({"supersedes": "首裁", "actions": [{"name": "测试转债", "code": "123456", "op": "买", "trigger_price": "100",
            "qty": 600, "anchor": "99.5", "rules": [{"id": "R1", "ctx": "情境判定: 当前 09:27 落在开盘主战场窗口内"}]}], "no_trade": False}, cctx):
        fails.append("cb 06 正例被误杀")
    for bad, tag in [
        ({"supersedes": "首裁", "actions": [{"name": "测试转债", "code": "002050", "op": "买", "trigger_price": "10", "qty": 100, "anchor": "10"}], "no_trade": False}, "cb 正股 code 未抓"),
        ({"supersedes": "首裁", "actions": [{"name": "测试转债", "code": "123456", "op": "买", "trigger_price": "100", "qty": 100, "anchor": "100",
            "rules": [{"id": "A4", "ctx": "情境判定: 这是桃哥规则不该出现在 cb 链"}]}], "no_trade": False}, "cb 桃哥规则 id 未抓"),
        ({"supersedes": "首裁", "actions": [{"name": "测试转债", "code": "123456", "op": "买", "trigger_price": "100", "qty": 1200, "anchor": "100"}], "no_trade": False}, "cb 超全仓上限未抓"),
    ]:
        if not v06(bad, cctx):
            fails.append(f"cb 06 {tag}")
    apply_skill("taoge")  # 复位(防后续维护者在转债链态下误加用例)

    shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        print("SELFTEST FAIL:")
        for f in fails:
            print(" -", f)
        sys.exit(1)
    print("SELFTEST PASS: 模板抽取/哨兵/contract 校验器(正例不误杀+反例全抓, 含 C7 价格锚 5 反例+公式价+20cm 分档)/盲审 FAIL 分支/plans 转换(anchor+cond 列+公式价代换)/cb 链(模板+v06 转债闸)")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--slot")
    ap.add_argument("--steps")  # 显式覆盖, 如 02,04,06
    ap.add_argument("--review", action="store_true")
    ap.add_argument("--skill", choices=list(SKILL_CFG), default="taoge")  # 10/4: 同驱动器跑 cb 链
    ap.add_argument("--source")  # 缺省=skill 默认账本(A-taoge/A-cb)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dry", action="store_true", help="走全流程但不调 claude(冒烟用)")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return
    apply_skill(a.skill)
    source = a.source or SKILL["source"]
    date = a.date
    date_dash = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    if a.review:
        run_chain(date, date_dash, "review", ["07"], source, a.dry)
        return
    if not a.slot and not a.steps:
        ap.error("需 --slot <HHMM> 或 --steps 01,02,... 或 --review")
    steps = a.steps.split(",") if a.steps else SLOT_STEPS.get(a.slot)
    if not steps:
        sys.exit(f"slot {a.slot} 不在 {a.skill} 映射表(SLOT_STEPS 与 chain.md 同步维护)")
    run_chain(date, date_dash, a.slot or "manual", steps, source, a.dry)

if __name__ == "__main__":
    main()
