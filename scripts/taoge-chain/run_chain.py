#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_chain.py — taoge-skill 七步决策链驱动器（2026-10-02 按 chain.md 契约重建, 与 plan-a 无关）

图纸=skills/taoge-skill/workflows/chain.md（唯一契约源, prompt 模板从 <!-- step:NN --> 段机械抽取）。
驱动器只做机械事: 填占位符→claude -p→验哨兵(产物文件末行)/mtime 新鲜度/contract JSON 重算→
单步回炉≤2→每步落地回溯重验 01..当前→06 actions 机械转 plans 行(LLM 不直接写 plans)。
C6 方案 B: persona 反问修复=01 模板头已有"任务优先, 禁反问"元指令(注入在 prompt 层, SKILL.md 不动)。

用法:
  python scripts/taoge-chain/run_chain.py --slot 0915 [--date 20261002] [--source A-taoge]
  python scripts/taoge-chain/run_chain.py --review --date 20261002
  python scripts/taoge-chain/run_chain.py --selftest     # 不烧 token 的机械自测
  python scripts/taoge-chain/run_chain.py --skill liuyiqing --slot 0915 --date 20260928 --asof <沙盒>  # as-of 回放(10/10)
出口: 0=链完成 1=链中止(回炉耗尽/校验败) 2=用法/环境错 3=ESCALATE_FULL_CHAIN(市况变, 子链升级)
"""
import argparse, json, os, re, shutil, subprocess, sys, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "claude_profile"))
import rotation  # 10/11 多 key 轮换(scripts/claude_profile/rotation.py)

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
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import mentors as MENTORS  # noqa: E402  10/17 二B-4: 导师登记表(全体链名单唯一真源)

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
TOKEN_LOG = Path(os.environ["PAPER_TOKEN_LOG"]) if os.environ.get("PAPER_TOKEN_LOG") else PAPER / "token_log.csv"  # 10/12: env 覆盖=A/B 回放另记
# 10/13 链改造 F/G 开关(10/13 晚用户拍板 G+F 上线): 默认值读 scripts/claude_profile/chain_flags.txt(一行一个 名=0/1, 改文件下次跑链生效, 不用重启应用),
# 环境变量优先(=1 强开, =0 强关; 回放对照用)。文件缺失=全关=改造前行为。
#   CHAIN_COMPACT       G: 04/05/06 改用 chain.md 的 04c/05c/06c 精简模板(模型只写推理+contract), 人看表由驱动器从 contract 渲染
#   CHAIN_PROFILE_INDEX F: 按 persona/profile_index.md 把「适用步骤」含本步的画像节原文机械拼进 02~06 prompt(gen_profile_index.py 生成)
def _flag(name):
    v = os.environ.get(name)
    if v in ("0", "1"):
        return v == "1"
    try:
        for line in (Path(__file__).resolve().parents[1] / "claude_profile" / "chain_flags.txt").read_text(encoding="utf-8").splitlines():
            k, _, val = line.split("#")[0].partition("=")
            if k.strip() == name:
                return val.strip() == "1"
    except OSError:
        pass
    return False


COMPACT = _flag("CHAIN_COMPACT")
PROFILE_IDX = _flag("CHAIN_PROFILE_INDEX")
# 10/14 晚 子链五修 + 触发闸 + 合并(chain_flags.txt; 文件缺失/=0 → 该项与改造前逐字节一致, selftest 从全关基线起)
FIX_FLOOR_EXIT = _flag("CHAIN_FIX_FLOOR_EXIT")      # ① 总仓下限只约束主动减仓: 止损/保护线/失效条件卖单(exit_kind)放行
FIX_NO_DEFER = _flag("CHAIN_FIX_NO_DEFER")          # ② contract 把决定交用户(交用户/待用户/用户裁…)=回炉
FIX_ESC_RERUN = _flag("CHAIN_FIX_ESC_RERUN")        # ④ 子链 ESCALATE(02 市况变/06 escalate)=本 slot 带提示重跑 02→04→06 一次
FIX_SUB_APPROVED = _flag("CHAIN_FIX_SUB_APPROVED")  # ⑤ 子链 04 注入 0915-05 批准名单+挂单, v04 校验候选 ⊆ 批准∪持仓∪挂单
FIX_HOLDS = _flag("CHAIN_FIX_HOLDS")                # 06 actions 空 ⇒ 必须给 holds 或 no_trade_reason
SUB_GATE = _flag("CHAIN_SUBCHAIN_GATE")             # 零 token 触发闸 A: 子链开跑前机械判断, 无触发=跳过本 slot
SUB_MERGE = _flag("CHAIN_SUBCHAIN_MERGE")           # 子链合并 D: 02/04/06 一次调用, 分块校验, 坏块 --resume 只重写那块
# 10/14 夜 0915 降本三改造(§3-A6; 只管 0915 全链且非转债链; 全关=与改造前逐字节一致, selftest+scripts/temp/a6_1014/identity_check.py 证明)
INLINE_CTX = _flag("CHAIN_INLINE_CTX")              # 1 材料内联: 每步模板要"读"的文件由驱动器原文附进 prompt(保留 Read 工具补读)
SHARED_PREFIX = _flag("CHAIN_SHARED_PREFIX")        # 2 共用开头: facts.md+01_market+通用规范 做成同 slot 全链共享的首会话, 各步 --fork-session 分叉(需 1)
MAIN_SESSION = _flag("CHAIN_MAIN_SESSION")          # 3 A6 主会话: 02→04→06 同一会话 --resume 续接; 03/05/盲审 独立会话, 产物以"已附"回注(需 1)
# 10/16 晚 持有期改造(用户定: 先当下再多日 + 沉淀 know-how): 02/03/04/07 末尾注入"本导师持有期参考"(horizon_days.json),
# 04 注入"持仓论点回看"(买入日/当时理由/计划持有天数/已持有天数), 07 注入"多日核对"(到期 outlook/到期持有计划)+导师真人当日操作。
# 新 contract 字段(02 outlook / 04 hold_days·exit_plan·thesis_check / 07 lessons·多日核对)一律可选: 有就校验格式, 没有不拦(开关开时只 WARN; 07 lessons 缺=软回炉一次)
HORIZON = _flag("CHAIN_HORIZON")
# 10/16 晚 TODO 三-2+A2①③ 账本统计硬约束/本导师候选池/统计基线建议(机械层 scripts/dfcf/paper/ledger_limits.py; 驱动器侧 ledger_prepare/ledger_block/_ledger_v04/_ledger_v06):
# 关=不 import 该模块、prompt 与校验逐字节不变(selftest _selftest_ledger 覆盖); 噪声带实验(scripts/temp/noise_20261016)跑完再开
LEDGER = _flag("CHAIN_LEDGER_CONSTRAINTS")
# 10/18 自动记忆开关(开关名 CLAUDE_NO_AUTOMEMORY; 默认 0=现状记忆照常读+写; 实际生效在 call_claude: 开=子进程注入
#   CLAUDE_CODE_DISABLE_AUTO_MEMORY=1(Claude Code 官方变量), 项目记忆目录不再读也不再写; 只关自动记忆一项, 全局 CLAUDE.md 等不受影响)
NO_AUTOMEMORY = _flag("CLAUDE_NO_AUTOMEMORY")
# 10/17 ② 决策质量新功能(TODO 三-2b/2c/2e/2f + override 锁层 + 三-3 第二期; 机械层 scripts/dfcf/paper/quality_hooks.py; 全部默认 0, 关=不 import、逐字节旧行为)
QF = {k: _flag(k) for k in ("CHAIN_PRICE_RULES", "CHAIN_SLOT_BUDGET", "CHAIN_T_PROFILE", "CHAIN_SIMILAR_DAYS", "CHAIN_OVERRIDE_LOCK", "CHAIN_RULE_CHECK", "CHAIN_RISK_SIZE")}   # 10/18 晚 +RISK_SIZE(周三开)
# 10/18 用户批(仓位太轻, docs/research/position_light_20261018.md): ①tzzb 导师链新开仓买单 ≥ 导师单票习惯(真人单票最大仓位中位)的 75%, 拆小单=回炉
#   ②买单 cancel_below 离挂价不得小于该票近 30 日日振幅中位的一半, 太近驱动器自动放宽(不回炉, 省 token); 关=逐字节旧行为
SIZE_RULES = _flag("CHAIN_SIZE_RULES")
SIZE_MIN_FRAC, CXL_AMP_FRAC = 0.75, 0.5
# 10/10 as-of 回放(9/28-30 补跑语义修复): --asof <沙盒目录> 时 books/plans/facts 走沙盒, 行情走 D 前一交易日日线;
# token_log/params.yaml 仍走真目录。ASOF=链日 YYYY-MM-DD(None=实盘)
PAPER_DATA = PAPER
ASOF = None
# 10/17 晚 审计#4 头号风险(回放读到未来画像): as-of 沙盒里有 <沙盒>/persona/<skill>/(persona_asof.py 还原的 D 日 09:15 前版本)时,
#   整条链改读它——Python 侧路径走 persona_dir(), prompt 里的 skills/<skill>-skill/persona 由 call_claude 统一替换; 实盘恒为 None=原行为
PERSONA_REL = None


def persona_rel():
    return PERSONA_REL or f"skills/{SKILL_NAME}-skill/persona"


def persona_dir():
    return ROOT / persona_rel()


def _persona_redirect(prompt):
    if not PERSONA_REL:
        return prompt
    real = f"skills/{SKILL_NAME}-skill/persona"
    note = (f"[as-of 画像版本·最高优先级] 本导师画像只读 {PERSONA_REL}/ (= {ASOF} 09:15 盘前那一版); "
            f"{real}/ 是之后蒸馏过的新版本, 含回放日之后的信息, 禁止读取。\n\n")
    return note + prompt.replace(real, PERSONA_REL)


def _lock_chain_md(pa):
    """10/18 全 skill 版本化: persona_asof 同时把 D 09:15 前的 chain.md 还原到 <沙盒>/persona/<skill>/_workflows/chain.md → 模板也锁;
    共享 01m / 通用规范读 taoge 的 chain.md, 沙盒里有 taoge 锁版也改读它(没有=照旧读当前)"""
    global CHAIN_MD
    cm = pa / "_workflows" / "chain.md"
    if cm.exists():
        CHAIN_MD = cm.resolve()
        print(f"as-of chain.md: {CHAIN_MD}")
    else:
        print("WARN: as-of 沙盒无 _workflows/chain.md, 模板读的是当前 chain.md(可能含回放日之后的改动)")
    tc = pa.parent / "taoge" / "_workflows" / "chain.md"
    if tc.exists():
        SKILL_CFG["taoge"]["chain_md"] = tc.resolve()


ASOF_NOTE = ("[as-of 回放声明·最高优先级] 本链为历史回放: 视当前时刻为 {date_dash} 09:15 盘前, 本链生效日=当日 {date_dash}"
             "(不是系统真实日期, 禁止推算成其他生效日)。禁止读取或引用 {date_dash} 09:15 之后才可能知道的任何信息: "
             "md/ 下 {date_dash} 及更晚日期的文件、results/ 下其他日期目录、scripts/dfcf/paper/ 下的实盘账本与 plans。"
             "前一交易日 md 中'【核销 T+1】'之类事后补记行(会引用 {date_dash} 及以后的行情)一律忽略。"
             "价格锚以 facts.txt/cand_snap.md 为准(=前一交易日收盘口径)。\n\n")
# 10/14 晚: 盘中子链 as-of 回放(子链合并 A/B)用——原 ASOF_NOTE 写死"09:15 盘前", 子链 slot 改按 slot 时刻声明; 只在 ASOF+子链时用
ASOF_NOTE_SUB = ("[as-of 回放声明·最高优先级] 本链为历史回放: 视当前时刻为 {date_dash} {hm} 盘中(slot {slot}), 本链生效日=当日 {date_dash}"
                 "(不是系统真实日期, 禁止推算成其他生效日)。禁止读取或引用 {date_dash} {hm} 之后才可能知道的任何信息: "
                 "md/ 下 {date_dash} 及更晚日期的文件、results/ 下除本 run_dir 以外的任何目录(尤其 live-*)、scripts/dfcf/paper/ 下的实盘账本与 plans。"
                 "盘中价格以 facts.txt(本 slot 实时快照)为准; cand_snap.md 是前一交易日收盘口径(只作前收/板限锚)。\n\n")
MAX_RETRY = 2
# 10/15 用户定 0915 链 08:15 开跑(为看到 07:17~08:02 发文的发哥), 配两道闸防意外拖过开盘(只管实盘当日 0915 全链, as-of/补跑/其他 slot 不受影响; CHAIN_RUSH=0 整体关):
#   赶工闸: 09:00 起开始的步骤回炉上限 2→1; 09:05 还没进 04 的跳过 03 辩论(写说明文件, 04 只依据 01/02)
#   截止闸: 09:25 后才导入的挂单 note 标【迟到单 HH:MM 导入·非竞价】(matcher 本就只在导入后按实时快照撮合, 不偷看; 标出来是为了统计口径)
RUSH_RETRY_AT, RUSH_SKIP03_AT, LATE_ORDER_AT = "09:00", "09:05", "09:25"


def _rush(date_dash, slot, hhmm):
    """实盘当日 0915 链且现在 ≥ hhmm(赶工/截止闸判定)"""
    if ASOF or slot != "0915" or os.environ.get("CHAIN_RUSH", "1") == "0":
        return False
    now = datetime.now()
    return date_dash == now.strftime("%Y-%m-%d") and now.strftime("%H:%M") >= hhmm
# headless 权限: acceptEdits=允许写产物文件不逐次询问; 模型只有 Write 需求, 不给 bash
# claude 入口=npm 全局 native exe(.cmd 走 cmd /c 有 8k 字符+转义坑, shim 是 sh 脚本 python 调不动)
_CLAUDE_EXE = os.path.join(os.environ.get("APPDATA", ""), r"npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe")
# 10/12 精简: 关掉链用不到的 skill 列表/MCP/动态段, 工具只留 6 个(实测固定开销 45k→20k token, -55%;
# 项目 .claude/CLAUDE.md 为空, 全局 CLAUDE.md+记忆索引照常加载=模型所见指令不变; --bare 拒 OAuth 订阅制不能用)。
# --tools 是可变参数会吞掉其后的位置参数, 故 prompt 改走 stdin(顺带免 Windows 命令行 32k 上限)
CLAUDE = [(_CLAUDE_EXE if os.path.exists(_CLAUDE_EXE) else "claude"),
          "-p", "--output-format", "json", "--permission-mode", "acceptEdits",
          "--exclude-dynamic-system-prompt-sections", "--disable-slash-commands", "--strict-mcp-config",
          "--tools", "Read,Write,Edit,Grep,Glob,Bash"]

# ---------- skill 参数化(10/4 盲区修复⑦: 同一驱动器多链, 差集全在这张表; 10/7 键正名 cb→buchitudou0) ----------
_SUB = ["02", "04", "05", "06", "blind"]   # 10/16 用户令: 子链加回 05 风控 + 取消名单闸(原 02/04/06); 10/16 晚 A3: 子链也跑拟人审(仅本时段 06 有新买单时)
_UP_SLOTS = {"0915": ["01", "02", "03", "04", "05", "06", "blind"],  # 盘前全链+盘中子链(10/7 4档→10/9 用户令扩9档对齐 taoge 时刻表)
             "0927": _SUB, "0945": _SUB, "1000": _SUB, "1030": _SUB, "1100": _SUB, "1127": _SUB,
             "1230": _SUB, "1300": _SUB, "1400": _SUB, "1430": _SUB, "1455": _SUB}


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
                       "0927": _SUB, "0935": _SUB, "1000": _SUB},
        "art": {"01": "01_facts.md", "02": "02_analysis.md", "04": "04_plan.md", "05": "05_risk.md",
                "06": "06_verdict.md", "07": "07_review.md", "blind": "validate_report.md"},
        "expand": {},
        "rule_id": r"R\d+", "high_pos": set(),
        "cap_ratio": 1.0, "floor_key": "tzzb",  # cb 仓位纪律(10/4 用户拍板): T+0 转债不做仓位管理——有把握全仓进, 没把握半仓+半仓; 上限=全仓
        "code_re": r"(11|12)\d{4}",  # 转债代码闸: 禁拿正股冒充转债
    },
}
# 10/17 二B-4: 其余链(趋势天哥/卢本圆 10/7; tzzb 导师 10/7 晚起陆续; 对照组 10/11 persona 恒空=裸模型基准)一律走 _up_cfg 工厂,
# 名单与顺序读导师登记表(scripts/lib/mentors.py; 加导师=登记表加一行, 这里不用再改)
SKILL_CFG.update({m: _up_cfg(m) for m in MENTORS.ids() if m not in SKILL_CFG})
def apply_skill(name):
    global SKILL, CHAIN_MD, SLOT_STEPS, ART, EXPAND, RESULTS_DIR, SKILL_NAME
    SKILL, SKILL_NAME = SKILL_CFG[name], name
    CHAIN_MD, SLOT_STEPS, ART, EXPAND = SKILL["chain_md"], SKILL["slot_steps"], SKILL["art"], SKILL["expand"]
    RESULTS_DIR = SKILL["results_dir"]
apply_skill("taoge")  # 默认 taoge, main 里按 --skill 重挂

# ---------- prompt 模板抽取(图纸与施工队分离: 模板只认 chain.md) ----------
def _templates_of(path):
    text = path.read_text(encoding="utf-8")
    return {m.group(1): m.group(2).strip()
            for m in re.finditer(r"<!-- step:(\w+) -->[\s\S]*?````prompt\n([\s\S]*?)````", text)}


def load_templates():
    out = _templates_of(CHAIN_MD)
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
# 10/14 晚 修②: paper 链没有用户——contract 把决定推给用户(10/13~14 子链 5 次"交用户裁/待用户裁/S3 交用户")=回炉; 末次尝试放行+WARN(不因措辞中止链)
DEFER_RE = re.compile(r"交(?:给|由)?用户|待用户|由用户(?:裁|决定|定夺|拍板|处理)|请用户|等用户|用户未?裁|用户(?:来|自行)(?:决定|定夺)")


def _soft_once(ctx, key):
    """软闸(修②/holds)每步每次运行最多回炉一次: 首次命中记账并回炉, 再命中或末次尝试放行"""
    if ctx.get("final_attempt"):
        return True
    seen = ctx.setdefault("_soft_seen", set())
    if key in seen:
        return True
    seen.add(key)
    return False


def defer_check(c, ctx, step):
    if not FIX_NO_DEFER:
        return None
    m = DEFER_RE.search(json.dumps({k: v for k, v in c.items() if not str(k).startswith("_")}, ensure_ascii=False))
    if not m:
        return None
    if _soft_once(ctx, f"defer{step}"):
        print(f"WARN: {step} contract 仍把决定交用户('{m.group(0)}'), 已回炉过一次, 放行(控时长: 子链 Java 超时 40min)")
        return None
    return (f"contract 把决定交给用户('{m.group(0)}')——paper 模拟链没有用户, 必须在规则内自己裁决"
            f"(拿不准就按更保守的一侧执行并写明理由), contract 里不许出现交用户/待用户/用户裁之类字样")


def v01(c, ctx):
    if c.get("date") != ctx["date_dash"]:
        return f"date 字段 {c.get('date')} != {ctx['date_dash']}"
    if not c.get("digest"):
        return "digest 空"

MARKET_STATES, LEADING_LAYERS = ("有主线", "无主线退潮", "普跌"), ("板块层", "资金惯性层")


def norm_enum(v, allowed):
    """10/12: 模型常在枚举后加注释('有主线(修复初段)'/'板块层先行'), 原先直接判非法回炉(10/12 07:39 实录 3 次);
    现以枚举值开头即归一为标准值; 10/12 晚补: 写成某标准值的唯一前缀(如'无主线'→无主线退潮, 10/12 08:29 天哥实录)也认; 其余仍判非法"""
    s = str(v or "").strip()
    hits = [a for a in allowed if s.startswith(a)]
    if hits:
        return max(hits, key=len)
    pre = [a for a in allowed if len(s) >= 2 and a.startswith(s)]
    return pre[0] if len(pre) == 1 else None


def v02(c, ctx):
    ms, ll = norm_enum(c.get("market_state"), MARKET_STATES), norm_enum(c.get("leading_layer"), LEADING_LAYERS)
    if not ms:
        return f"market_state 非法: {c.get('market_state')}(只许 有主线/无主线退潮/普跌 之一, 注释写正文不写进字段)"
    if not ll:
        return f"leading_layer 非法: {c.get('leading_layer')}(只许 板块层/资金惯性层 之一)"
    c["market_state"], c["leading_layer"] = ms, ll
    if not c.get("directions"):
        return "directions 空"
    # 10/14 §3-A 第 8 条: 盘前态度 多/中立/空(可选; 缺省或写法不认识=按"多", 打 WARN 不回炉, 兼容旧模板与转债链)
    st = norm_enum(c.get("stance"), STANCES)
    if c.get("stance") and not st:
        print(f"WARN: 02 stance 写法不认识({c.get('stance')}), 按'多'处理")
    c["stance"] = st or "多"
    return outlook_check(c, ctx) or evidence_check(c, ctx) or defer_check(c, ctx, "02")


# ---------- 10/16 晚 持有期改造: 新字段校验(全部可选; 有就校验格式, 没有不拦) ----------
THESIS_STATES = ("成立", "部分成立", "不成立")
LESSON_TYPES = ("规则草案", "规则修正", "错误归因", "case卡")   # case卡=tzzb 导师链拟人偏差教训(情境→真人怎么做→我们怎么做→差异原因→下次怎么识别)
MIMIC_ITEMS = ("交不交易", "方向", "标的", "仓位", "时段")
MIMIC_CAUSES = ("事实包缺信息", "理解错导师框架", "其他")
MULTI_RESULTS = ("对", "部分对", "错", "无法判断")


def _pos_int(v, hi=250):
    """正整数(容忍 "3"/3.0/"3天"); 非法=None"""
    m = re.fullmatch(r"\s*(\d+)(?:\.0+)?\s*(?:个交易日|交易日|天|日)?\s*", str(v)) if v is not None and not isinstance(v, bool) else None
    n = int(m.group(1)) if m else None
    return n if n and 1 <= n <= hi else None


def outlook_check(c, ctx):
    """02 outlook={"horizon_days":N,"view":"多|中立|空","thesis":"...","invalid_if":"..."}: 缺=放行(开关开时 WARN), 有=格式全对"""
    o = c.get("outlook")
    if o is None:
        if HORIZON and SKILL_NAME != "buchitudou0":
            print("WARN: 02 未给 outlook(未来 N 日判断), 放行(兼容旧产物)")
        return None
    if not isinstance(o, dict):
        return "outlook 须为对象 {\"horizon_days\":N,\"view\":\"多|中立|空\",\"thesis\":\"一句话依据\",\"invalid_if\":\"出现什么算看错\"}"
    n = _pos_int(o.get("horizon_days"), 60)
    if not n:
        return f"outlook.horizon_days 须为 1~60 的整数(交易日数, 取 prompt 末尾持有期参考的中位天数): {o.get('horizon_days')}"
    v = norm_enum(o.get("view"), STANCES)
    if not v:
        return f"outlook.view 非法: {o.get('view')}(只许 多/中立/空 之一)"
    for k in ("thesis", "invalid_if"):
        if not str(o.get(k) or "").strip():
            return f"outlook.{k} 空(thesis=一句话依据, invalid_if=出现什么算看错, 都要可核对)"
    o["horizon_days"], o["view"] = n, v
    return _over_cap(n, o, ctx, "02", "outlook.horizon_days")


def _over_cap(n, obj, ctx, step, label):
    """10/16 晚用户定: 默认=中位, 上限=P75; 超过 P75 必须写 over_cap_why(仅有真人统计的导师; 首次回炉, 末次放行+WARN)"""
    if not HORIZON or SKILL_NAME == "buchitudou0":
        return None
    h = horizon_of(SKILL_NAME)
    if not h["stat"] or n <= h["cap"] or str(obj.get("over_cap_why") or "").strip():
        return None
    if _soft_once(ctx, f"overcap{step}"):
        print(f"WARN: {label}={n} 超本导师持仓天数 P75={h['cap']} 且无 over_cap_why, 放行")
        return None
    return (f"{label}={n} 超过本导师拿得住的上限(真人持仓天数 P75={h['cap']} 天)——要么改到 ≤{h['cap']}, "
            f"要么在同一对象里写 over_cap_why(一句话: 什么条件下比真人 75% 的持仓拿得还久)")


def horizon_cand_check(c, ctx):
    """04 candidates 可选字段: hold_days(1~250 整数)/exit_plan(一句话)/thesis_check(成立|部分成立|不成立)+thesis_note(一句理由)。
    有就校验; 缺的只在开关开时 WARN(持仓票缺 thesis_check 时首次软回炉一次, 末次放行)"""
    held = set(((ctx.get("book") or {}).get("positions") or {}).keys())
    miss_plan, miss_th = [], []
    for x in c.get("candidates") or []:
        nm = x.get("name")
        exit_today = str(x.get("hold_days")).strip() in ("0", "0.0") and (x.get("group") == "遗留" or str(x.get("code") or "") in held)
        if exit_today:
            x["hold_days"] = 0   # 10/17 用户批 A1: 遗留仓/现有持仓写 0 = 今日离场, 合法(原判非法→无意义回炉 ~$0.9/次)
        elif x.get("hold_days") is not None:
            n = _pos_int(x.get("hold_days"))
            if not n:
                return f"{nm} hold_days 须为正整数(预期持有交易日数; 遗留仓/现有持仓今日离场可写 0): {x.get('hold_days')}"
            x["hold_days"] = n
            err = _over_cap(n, x, ctx, "04", f"{nm} hold_days")
            if err:
                return err
        if x.get("exit_plan") is not None and not str(x.get("exit_plan")).strip():
            return f"{nm} exit_plan 空(一句话: 止损/止盈/时间离场)"
        if x.get("thesis_check") is not None:
            th = norm_enum(x.get("thesis_check"), THESIS_STATES)
            if not th:
                return f"{nm} thesis_check 非法: {x.get('thesis_check')}(只许 成立/部分成立/不成立, 理由写 thesis_note)"
            if not str(x.get("thesis_note") or "").strip():
                return f"{nm} 给了 thesis_check 但 thesis_note 空(一句话: 对照买入时论点, 为什么成立/不成立)"
            x["thesis_check"] = th
        if x.get("group") != "遗留" and (x.get("hold_days") is None or not x.get("exit_plan")):
            miss_plan.append(nm)
        if str(x.get("code") or "") in held and x.get("thesis_check") is None:
            miss_th.append(nm)
    if HORIZON and SKILL_NAME != "buchitudou0":
        if miss_plan:
            print(f"WARN: 04 候选缺 hold_days/exit_plan: {miss_plan}(放行)")
        if miss_th and ctx.get("thesis_n") and not _soft_once(ctx, "thesis04"):
            return (f"持仓票 {miss_th} 没给 thesis_check——先对照 prompt 末尾「持仓论点回看」里买入时写下的论点, "
                    f"给 thesis_check(成立/部分成立/不成立)+thesis_note(一句理由): 论点还成立就拿, 不成立才卖, 不要每天从零评估")
        if miss_th:
            print(f"WARN: 04 持仓票缺 thesis_check: {miss_th}(放行)")
    return None


STANCES = ("多", "中立", "空")
STANCE_FACTOR = {"多": 1.0, "中立": 0.5, "空": 0.0}


def apply_stance(ctx):
    """10/14 §3-A 第 8 条(用户 10/13 定 B): 总仓下限再乘态度系数(多=1/中立=0.5/空=0), 单票上限不变; 转债链不适用。
    纯观望仍违规——空也要给进场条件单(v06 三选一契约照旧)"""
    pc, c02 = ctx.get("pc"), ctx["contracts"].get("02") or {}
    if not pc or SKILL_NAME == "buchitudou0" or "base_floor" in pc:
        return
    if SKILL_NAME in TZZB_LEDGERS:   # 10/16 审计#3: 下限已按导师近 5 日真实仓位算, 再乘态度系数=把满仓型导师(A658/芷影/量化)压到 1~5 成仓
        pc["base_floor"], pc["stance"] = pc["floor"], (c02.get("stance") or "多")
        return
    import math
    st = c02.get("stance") or "多"
    pc["base_floor"], pc["stance"] = pc["floor"], st
    pc["floor"] = round(pc["floor"] * STANCE_FACTOR.get(st, 1.0) * 20) / 20
    pc["gap"] = round(max(0.0, pc["floor"] * pc["nav"] - sum(pc["held"].values()) - sum(pc["open_buy"].values())), 2)
    pc["need_n"] = math.ceil(pc["gap"] / (pc["cap"] * 0.9)) if pc["gap"] > 0 and pc["cap"] > 0 else 0
    if st != "多":
        print(f"态度={st}: 总仓下限 {pc['base_floor']:.0%} → {pc['floor']:.0%}")

# ---------- 10/16 晚 03 保留分歧版(DEBATE_V2; 报告 10/18 已删, 去留看沙盒"停03"组) ----------
# 10/12~16 旧版 03j 70 次判多 68 次(=常数): "必须分出高下"+"看空降权(空方需写死两倍证据)"把分歧在设计上抹掉了。
# 新版: 03j 不二选一, 给两方"经核验仍成立的论据强度"分 B/S(各自 0-100, 非零和); 驱动器用有效空分 S'=S/k 机械算倾向/分歧度/折扣。
# k=空方折算系数(用户定: LLM 偏空要约束空方, 原意≈1.5 倍、应在 [1,2] 动态): 先验 1.5, 按链用近 20 日 (B,S)+标签滚动拟合并向 1.5 收缩。
# 用法只有两处: ①04/05/06 约束块注入分歧摘要+少数派风险+翻转条件 ②0915 追价买单(开盘即成交)单票金额按系数打折, 回踩条件单不限。
# 旧格式 contract(未改模板的链)照旧校验, 不产生任何新行为。
DEBATE_V2 = True
DEBATE_LEAN_HI, DEBATE_LEAN_LO = 0.6, 0.4        # p=B/(B+S') ≥0.6 倾向多, ≤0.4 倾向空, 其间=均衡
DEBATE_MARGIN_HI, DEBATE_MARGIN_LO = 0.2, 0.5    # margin=|p-0.5|×2: <0.2 分歧高(势均力敌), <0.5 分歧中, 其余分歧低
DEBATE_WEAK = 40                                 # 两方原始分最高 <40 = 双方都弱(信息弱), 按分歧高处理
DEBATE_FACTOR = {("多", "低"): 1.0, ("多", "中"): 0.75, ("空", "中"): 0.5, ("空", "低"): 0.25}   # 其余(均衡/分歧高/信息弱)=0.5
DEBATE_CHASE = 0.995                             # 买单挂价 ≥ 现价锚×0.995 = 开盘即大概率成交(与拟人审"本单机械统计"同口径)
DEBATE_K0, DEBATE_K_LO, DEBATE_K_HI, DEBATE_K_STEP = 1.0, 0.5, 2.0, 0.05   # 空方折算 k: 先验/区间/网格步长(10/17 A6: 原 1.5/[1,2] 假设"LLM 偏空", 实测裁判反而偏多 → 中性先验+双向区间)
DEBATE_K_APPLY = False   # 10/17 用户定(A6): 多空辩论不加系数(有效空分=空分); k 照算照记(debate.json k_obs)只作"LLM 偏多/偏空"的持续测量, 不进决策
DEBATE_K_WIN, DEBATE_K_M, DEBATE_K_MIN = 20, 10, 5                          # 拟合窗口(交易日)/收缩强度 m/最少有标签样本
DEBATE_LABEL_N, DEBATE_LABEL_DEAD = 2, 0.003     # UP/对照链标签: 上证 d−1 收盘→d+N−1 收盘, |涨跌|<0.3% 不计


def _dnum(v):
    try:
        x = float(str(v).strip().rstrip("分"))
    except (TypeError, ValueError):
        return None
    return x if 0 <= x <= 100 else None


def _strs(v):
    return [str(x).strip() for x in (v if isinstance(v, list) else ([v] if v else [])) if str(x).strip()]


def _flag_list(name):
    """逗号分隔的 skill 白名单: 环境变量优先(含空串=显式清空), 否则读 chain_flags.txt 同名行; 缺=空集"""
    v = os.environ.get(name)
    if v is None:
        try:
            for line in (Path(__file__).resolve().parents[1] / "claude_profile" / "chain_flags.txt").read_text(encoding="utf-8").splitlines():
                k, _, val = line.split("#")[0].partition("=")
                if k.strip() == name:
                    v = val
        except OSError:
            pass
    return {s.strip() for s in (v or "").split(",") if s.strip()}


def no03_on():
    """A/B 停 03 臂(CHAIN_NO03_SKILLS 白名单)"""
    return SKILL_NAME in _flag_list("CHAIN_NO03_SKILLS")


def debate_fit_k(samples):
    """samples=[(B, S, 标签 ±1)] → (k, k_fit, n)。网格 [1,2] 步 0.05, 取 sign(B−S/k) 与标签一致数最多者(并列取离 1.5 最近),
    再向先验收缩 k=(n·k_fit+m·1.5)/(n+m); 有标签样本 n<5 → (1.5, None, n)"""
    xs = [(float(b), float(s), int(y)) for b, s, y in samples if y in (1, -1)]
    n = len(xs)
    if n < DEBATE_K_MIN:
        return DEBATE_K0, None, n
    grid = [round(DEBATE_K_LO + DEBATE_K_STEP * i, 2) for i in range(int(round((DEBATE_K_HI - DEBATE_K_LO) / DEBATE_K_STEP)) + 1)]
    sgn = lambda v: (v > 1e-9) - (v < -1e-9)
    hit = lambda k: sum(sgn(b - s / k) == y for b, s, y in xs)
    kf = max(grid, key=lambda k: (hit(k), -abs(k - DEBATE_K0)))
    return round((n * kf + DEBATE_K_M * DEBATE_K0) / (n + DEBATE_K_M), 3), kf, n


def _debate_hist(cut):
    """本链 cut 日之前的 03 两方原始分 [(日, B, S)] 最近 20 个: live-*/debate.json + 可选种子 debate_seed.jsonl(校准回放产出, 用户批准后才写)"""
    base = ROOT / "results" / RESULTS_DIR
    rows = {}
    seed = base / "debate_seed.jsonl"
    if seed.exists():
        for line in seed.read_text(encoding="utf-8").splitlines():
            try:
                j = json.loads(line)
                rows[str(j["date"])] = (float(j["bull"]), float(j["bear"]))
            except (ValueError, KeyError, TypeError):
                continue
    for p in base.glob("live-*/debate.json"):
        mm = re.fullmatch(r"live-(\d{4})(\d{2})(\d{2})", p.parent.name)
        if not mm:
            continue
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
            rows[f"{mm[1]}-{mm[2]}-{mm[3]}"] = (float(j["bull"]), float(j["bear"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return [(d, *rows[d]) for d in sorted(rows) if d < cut][-DEBATE_K_WIN:]


def _debate_labels_tzzb(dates, skill=None):
    """tzzb 导师真人当日方向(mimicry_score.py L2 口径: 去价格漂移净权重变化 >5% 资产=净加 +1 / <−5%=净减 −1; 不动/无数据不计)"""
    d_ = str(Path(__file__).resolve().parents[1] / "dfcf" / "paper")
    if d_ not in sys.path:
        sys.path.insert(0, d_)
    import mimicry_score as ms
    real = ms.Real(skill or SKILL_NAME)
    keys = sorted(real.dp)
    out = {}
    for d in dates:
        k8 = d.replace("-", "")
        pk = [k for k in keys if k < k8]
        if k8 not in real.dp or not pk:
            continue
        cur, prev = real.snap(d), real.snap(f"{pk[-1][:4]}-{pk[-1][4:6]}-{pk[-1][6:]}")
        if cur and prev:
            y = ms.derive(prev, cur, lambda c: None)["dir"]
            if y in (1, -1):
                out[d] = y
    return out


def _debate_labels_mkt(dates, cut):
    """UP 链/对照组: 上证指数 d−1 收盘→d+N−1 收盘涨跌方向(本地行情库只读, 子进程不弹窗); 窗口末日须 < cut(as-of 不偷看)"""
    if not dates:
        return {}
    beg = datetime.fromordinal(datetime.strptime(min(dates), "%Y-%m-%d").toordinal() - 20).strftime("%Y%m%d")
    py = ROOT / "scripts" / "venv" / "Scripts" / "python.exe"
    r = subprocess.run([str(py if py.exists() else sys.executable), "-X", "utf8", str(ROOT / "scripts" / "quotes" / "kline_db.py"), "sh000001", "--beg", beg],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    bars = json.loads(r.stdout)["data"]["sh000001"]["bars"]
    cal, cl = [b[0] for b in bars], {b[0]: b[4] for b in bars}
    out = {}
    for d in dates:
        if d not in cl:
            continue
        i = cal.index(d)
        j = i + DEBATE_LABEL_N - 1
        if i < 1 or j >= len(cal) or cal[j] >= cut or not cl[cal[i - 1]]:
            continue
        ret = cl[cal[j]] / cl[cal[i - 1]] - 1
        if abs(ret) >= DEBATE_LABEL_DEAD:
            out[d] = 1 if ret > 0 else -1
    return out


def debate_label_desc(skill=None):
    return ("导师真人当日净加/减仓(mimicry_score L2 口径, 不动日不计)" if (skill or SKILL_NAME) in TZZB_LEDGERS
            else f"上证指数 d-1 收盘→d+{DEBATE_LABEL_N - 1} 收盘涨跌(±{DEBATE_LABEL_DEAD:.1%} 内不计)")


def debate_k(cut):
    """本链空方折算 k(fail-open=先验 1.5): {"k","k_fit","n"(有标签样本),"hist"(有分数的交易日),"label"(标签口径)}"""
    info = {"k": DEBATE_K0, "k_fit": None, "n": 0, "hist": 0, "label": debate_label_desc()}
    try:
        hist = _debate_hist(cut)
        info["hist"] = len(hist)
        if len(hist) >= DEBATE_K_MIN:
            dates = [d for d, _, _ in hist]
            lab = _debate_labels_tzzb(dates) if SKILL_NAME in TZZB_LEDGERS else _debate_labels_mkt(dates, cut)
            info["k"], info["k_fit"], info["n"] = debate_fit_k([(b, s, lab[d]) for d, b, s in hist if d in lab])
    except Exception as e:   # noqa: BLE001  校准坏=用先验, 不阻断链
        print(f"WARN: 03 空方折算 k 校准失败, 用先验 {DEBATE_K0}: {e}")
    if not DEBATE_K_APPLY:
        info["k_obs"], info["k"] = info["k"], 1.0
    return info


def debate_summary(c, k=None):
    """03j contract → 分歧摘要(纯机械; 有效空分 S'=S/k); 旧格式/坏数=None(不产生新行为)"""
    if not isinstance(c, dict):
        return None
    b, s = _dnum(c.get("bull_score")), _dnum(c.get("bear_score"))
    if b is None or s is None:
        return None
    k = min(DEBATE_K_HI, max(DEBATE_K_LO, float(k or DEBATE_K0)))
    se = s / k
    p = round(b / (b + se), 6) if b + se > 0 else 0.5
    margin = round(abs(p - 0.5) * 2, 6)   # 取整防边界被浮点误差判到另一档
    weak = max(b, s) < DEBATE_WEAK
    lean = "多" if p >= DEBATE_LEAN_HI else ("空" if p <= DEBATE_LEAN_LO else "均衡")
    level = "高" if (margin < DEBATE_MARGIN_HI or weak) else ("中" if margin < DEBATE_MARGIN_LO else "低")
    return {"bull": b, "bear": s, "k": round(k, 3), "bear_eff": round(se, 1), "p_bull": round(p, 3), "margin": round(margin, 3), "weak": weak,
            "lean": lean, "level": level, "factor": DEBATE_FACTOR.get((lean, level), 0.5), "model_lean": c.get("lean"),
            "minority_risks": _strs(c.get("minority_risks"))[:3], "flip_triggers": _strs(c.get("flip_triggers"))[:3],
            "fabricated": _strs(c.get("fabricated"))}


def _v03_legacy(c, ctx):
    if c.get("winner") not in ("多", "空"):
        return f"winner 非法: {c.get('winner')}"
    if not c.get("decisive_reason"):
        return "decisive_reason 空(必须分高下)"


def v03(c, ctx):
    """03j 双格式: 含 bull_score/bear_score=保留分歧版; 否则旧 winner 版(处理组模板下写旧格式=回炉)"""
    if "bull_score" not in c and "bear_score" not in c:
        if ctx.get("debate_v2"):
            return "保留分歧版 03j: contract 须给 bull_score/bear_score(两方核验分 0-100, 各自独立打) + minority_risks + flip_triggers, 不再写 winner"
        return _v03_legacy(c, ctx)
    for k in ("bull_score", "bear_score"):
        if _dnum(c.get(k)) is None:
            return f"{k} 非法: {c.get(k)}(须 0-100 的数)"
    if not str(c.get("decisive_reason") or "").strip():
        return "decisive_reason 空(写两方分数的依据)"
    if not isinstance(c.get("flip_triggers"), list) or not _strs(c.get("flip_triggers")):
        return "flip_triggers 空(竞价/早盘可观测的翻转条件 1~3 条, 写具体数)"
    if not isinstance(c.get("minority_risks"), list):
        return "minority_risks 须为列表"
    if min(_dnum(c["bull_score"]), _dnum(c["bear_score"])) >= 20 and not _strs(c.get("minority_risks")):
        return "minority_risks 空(较弱一方分≥20=它有论据经核验成立, 必须写成 1~3 条风险句交给 04/05/06; 这是保留分歧的唯一出口)"
    if c.get("lean") not in (None, "", "多", "空", "均衡"):
        return f"lean 非法: {c.get('lean')}(多/空/均衡; 驱动器按两方分复算)"
    return None


def _debate_k_line(d):
    if not DEBATE_K_APPLY:
        obs = d.get("k_obs")
        return (f"多空不加系数(10/17 A6): 有效空分 = 空分 = {d['bear']:.0f}"
                + (f"; 观测用 k={obs:g}(只记录, 不进决策; 标签={d.get('k_label') or debate_label_desc()})" if obs is not None else ""))
    if d.get("k_fit") is not None:
        how = f"本链近 {d.get('k_hist', 0)} 个有 03 分数的交易日里 {d.get('k_n', 0)} 个有标签, 拟合 {d['k_fit']:g} 后向 {DEBATE_K0:g} 收缩(m={DEBATE_K_M})"
    else:
        how = f"有标签样本 {d.get('k_n', 0)} 个 <{DEBATE_K_MIN}(有 03 分数的交易日 {d.get('k_hist', 0)} 个), 用先验 {DEBATE_K0:g}"
    return f"空方折算 k={d['k']:g}({how}; 标签={d.get('k_label') or debate_label_desc()}): 有效空分 = 空分/k = {d['bear']:.0f}/{d['k']:g} = {d['bear_eff']:.1f}"


def _debate_render(run_dir, d):
    """03_debate.md 的末个 contract 块之前插"驱动器复算"块(幂等; 哨兵仍在末行, contract 仍是末块)"""
    f = Path(run_dir) / ART["03j"]
    try:
        t = f.read_text(encoding="utf-8")
    except OSError:
        return
    i = t.rfind("```contract")
    if i < 0 or "## 驱动器复算(DEBATE_V2" in t:
        return
    blk = ["## 驱动器复算(DEBATE_V2, 机械算; 04/05/06 以此为准)", "",
           f"- 多方 {d['bull']:.0f} / 空方 {d['bear']:.0f}", f"- {_debate_k_line(d)}",
           f"- 倾向 {d['lean']}(p=多/(多+有效空)={d['p_bull']:.2f}), 分歧度 {d['level']}" + ("(双方论据都弱)" if d.get("weak") else "")
           + f", 追价买单折扣系数 {d['factor']}" + (f"; 裁判自报倾向 {d['model_lean']} 与复算不同, 以复算为准" if d.get("model_lean") and d["model_lean"] != d["lean"] else ""), "", ""]
    _write_lf(f, t[:i] + "\n".join(blk) + t[i:])


def debate_apply(ctx, run_dir=None, kinfo=None):
    """03j 通过后(或中段起跑载入旧产物时): 分歧摘要进 pc(04/05/06 约束块 + v06 追价折扣闸); 盘中子链不用 0915 的 03(时过境迁)。
    kinfo=None 时现场校准 k(debate_k); 自测/回放可直接给"""
    pc = ctx.get("pc")
    if not DEBATE_V2 or ctx.get("sub") or not pc or SKILL_NAME == "buchitudou0":
        return None
    c = ctx["contracts"].get("03j")
    pc.pop("debate", None)
    if debate_summary(c) is None:
        return None
    ki = kinfo or debate_k(ctx.get("date_dash") or datetime.now().strftime("%Y-%m-%d"))
    d = debate_summary(c, ki["k"])
    d.update(k_fit=ki.get("k_fit"), k_n=ki.get("n", 0), k_hist=ki.get("hist", 0), k_label=ki.get("label"), k_obs=ki.get("k_obs"),
             chase_cap=round(float(pc.get("cap") or 0) * d["factor"], 2))
    pc["debate"] = d
    if d["model_lean"] and d["model_lean"] != d["lean"]:
        print(f"WARN: 03j 自报倾向 {d['model_lean']} ≠ 两方分复算 {d['lean']}(以复算为准)")
    print(f"03 分歧: 多 {d['bull']:.0f} / 空 {d['bear']:.0f}(k={d['k']:g}, 有效空 {d['bear_eff']:.1f}; 拟合 {d['k_fit']} 样本 {d['k_n']}/{d['k_hist']})"
          f" → 倾向 {d['lean']} 分歧{d['level']}" + ("(双方都弱)" if d["weak"] else "") + f" → 追价买单系数 {d['factor']}")
    if run_dir is not None:
        try:
            _write_lf(Path(run_dir) / "debate.json", json.dumps(d, ensure_ascii=False, indent=1))
            _write_lf(Path(run_dir) / "pos_constraints.json", json.dumps(pc, ensure_ascii=False, indent=1))
            _debate_render(run_dir, d)
        except OSError as e:
            print(f"WARN: debate.json/复算块落盘失败(不影响链): {e}")
    return d


def debate_text(pc, step):
    """constraint_text 末尾的"03 分歧"块(04/05/06); 无 pc["debate"]=空列表(旧行为逐字节不变)"""
    d = (pc or {}).get("debate")
    if not d or step not in ("04", "05", "06"):
        return []
    L = [f"- 03 分歧(保留分歧版, 驱动器按 03j 两方核验分机械算): 多方 {d['bull']:.0f} / 空方 {d['bear']:.0f} → 倾向 {d['lean']}, 分歧度 {d['level']}"
         + ("(双方论据都弱)" if d.get("weak") else ""), f"- {_debate_k_line(d)}"]
    if d["factor"] < 1 and _flag("CHAIN_DEBATE_GATE"):   # 10/16 晚: 读 chain_flags.txt(环境变量优先), 缺省=关
        L.append(f"- 追价折扣(03 分歧{d['level']}/倾向{d['lean']}): 挂价≥现价锚(开盘即大概率成交)的买单, 单票金额 ≤ 单票上限×{d['factor']} ≈ {d['chase_cap']:.0f} 元, 超了驱动器回炉; "
                 "回踩条件单(挂价低于现价锚, 盘中回落才成交)不受此折扣, 仍按单票上限")
    if d.get("minority_risks"):
        L.append("- 少数派风险(03 核验后仍成立, 不因倾向而作废): " + "; ".join(f"{i + 1}) {_cell(r, 160)}" for i, r in enumerate(d["minority_risks"])))
    if d.get("flip_triggers"):
        L.append("- 翻转条件(竞价/早盘可观测): " + "; ".join(_cell(r, 120) for r in d["flip_triggers"]))
    L.append({"04": "- 本步: 分歧高/倾向空时, 候选可以照常列, 但触发价优先给回踩条件价; 少数派风险命中的票在三件套里写明",
              "05": "- 本步: 每只候选对照上面的少数派风险逐条看是否命中, 命中的写进该票 reason(条件批准写清条件, 必要时用 cap 压仓); 不命中不必硬扯",
              "06": "- 本步: 少数派风险/翻转条件能用价格表达的, 落到 cancel_below/invalid_if; 分歧高时少下/只挂条件单/不开新仓都合法"}[step])
    L.append("- 以本导师画像为准: 03 分歧只调仓位与挂法, 不改变本导师的能力圈与出手习惯(方案 A)")
    return L


def _debate_gate(c, ctx):
    """v06 通过后的追价折扣闸(只 0915 盘前, 只买单, 只追价单); 返回失败原因或 None; 末次放行(WARN)"""
    d = (ctx.get("pc") or {}).get("debate")
    if not d or ctx.get("sub") or d["factor"] >= 1 or not _flag("CHAIN_DEBATE_GATE"):
        return None
    lim = d.get("chase_cap") or 0
    for a in c.get("actions") or []:
        if a.get("op") != "买":
            continue
        try:
            px = float(a.get("_px") if a.get("_px") is not None else a.get("trigger_price"))
            anc = float(a.get("anchor"))
            q = int(a.get("qty"))
        except (TypeError, ValueError):
            continue
        if anc <= 0 or px < anc * DEBATE_CHASE or px * q <= lim + 1e-6:
            continue
        why = (f"{a.get('name')} 是追价买单(挂价 {px:g} ≥ 现价锚 {anc:g}, 开盘即大概率成交), 金额 {px * q:.0f} 超 03 分歧折扣上限 {lim:.0f}"
               f"(03 倾向{d['lean']}/分歧{d['level']}, 系数 {d['factor']}): 改成回踩条件单(挂价低于现价锚)或把 qty 降到 ≤{_AR.round_qty(str(a.get('code', '')), lim // px)} 股")
        if ctx.get("final_attempt"):
            print(f"WARN: 末次放行 {why}")
            return None
        return why
    return None


def _debate_wrap_v06(fn):
    def v06_debate(c, ctx):
        return fn(c, ctx) or _debate_gate(c, ctx)
    v06_debate.__wrapped__ = fn
    return v06_debate


def _selftest_debate():
    """10/17 A6: 机制自测按旧参数(k 先验 1.5/区间 [1,2]/应用 k)跑, 保证"开回系数"时逻辑仍对; 末尾另测实盘口径(不加系数)"""
    global DEBATE_K0, DEBATE_K_LO, DEBATE_K_APPLY
    keep = (DEBATE_K0, DEBATE_K_LO, DEBATE_K_APPLY)
    DEBATE_K0, DEBATE_K_LO, DEBATE_K_APPLY = 1.5, 1.0, True
    try:
        f = _selftest_debate_core()
    finally:
        DEBATE_K0, DEBATE_K_LO, DEBATE_K_APPLY = keep
    if not DEBATE_K_APPLY:
        line = _debate_k_line({"bear": 75, "k_obs": 1.3})
        if "不加系数" not in line or "1.3" not in line:
            f.append(f"A6 不加系数口径渲染错: {line}")
    return f


def _selftest_debate_core():
    """DEBATE_V2 单测(零 token): 两格式 v03 / 分歧映射(k=1 与 k=1.5) / k 拟合与收缩 / concede_if / 追价折扣闸 / 注入块 / 复算块 / 停 03 白名单"""
    import tempfile
    f = []
    _gate_env = os.environ.get("CHAIN_DEBATE_GATE")
    os.environ["CHAIN_DEBATE_GATE"] = "1"   # 自测按"闸开"测折扣逻辑(实盘开关在 chain_flags.txt, 10/16 晚默认关); 末尾还原
    cx = {"sub": False}
    K15 = {"k": 1.5, "k_fit": None, "n": 0, "hist": 0, "label": "自测"}
    ok2 = {"bull_score": 70, "bear_score": 45, "minority_risks": ["r"], "flip_triggers": ["t"], "decisive_reason": "x"}
    if v03({"winner": "多", "decisive_reason": "r"}, cx) or v03(ok2, cx):
        f.append("03j 双格式正例被误杀")
    for bad, why in (({**ok2, "bull_score": 120}, "分数越界"), ({**ok2, "flip_triggers": []}, "缺翻转条件"),
                     ({**ok2, "minority_risks": []}, "较弱方≥20 少数派风险空"), ({**ok2, "decisive_reason": ""}, "理由空"),
                     ({**ok2, "lean": "偏多"}, "lean 非法")):
        if not v03(bad, cx):
            f.append(f"03j v2 {why}未抓")
    if v03({**ok2, "bear_score": 10, "minority_risks": []}, cx):
        f.append("03j v2 较弱方<20 可无少数派风险, 被误杀")
    if not v03({"winner": "多", "decisive_reason": "r"}, {"debate_v2": True}):
        f.append("处理组写旧 winner 格式未抓")
    exp1 = {(80, 20): ("多", "低", 1.0), (60, 40): ("多", "中", 0.75), (50, 45): ("均衡", "高", 0.5), (20, 80): ("空", "低", 0.25),
            (35, 60): ("空", "中", 0.5), (30, 25): ("均衡", "高", 0.5), (39, 5): ("多", "高", 0.5)}
    exp15 = {(50, 45): ("多", "中", 0.75), (60, 90): ("均衡", "高", 0.5), (20, 80): ("空", "中", 0.5), (40, 100): ("空", "中", 0.5), (80, 20): ("多", "低", 1.0)}
    for k, exp in ((1.0, exp1), (1.5, exp15)):
        for (b, s), e in exp.items():
            d = debate_summary({"bull_score": b, "bear_score": s}, k)
            if (d["lean"], d["level"], d["factor"]) != e:
                f.append(f"分歧映射错 k={k} {b}/{s}: {(d['lean'], d['level'], d['factor'])} ≠ {e}")
    if debate_summary({"bull_score": 50, "bear_score": 50}, 5)["k"] != DEBATE_K_HI or debate_summary({"bull_score": 50, "bear_score": 50})["k"] != DEBATE_K0:
        f.append("k 未夹到 [1,2] / 缺省非 1.5")
    if debate_summary({"winner": "多"}) is not None or debate_summary({"bull_score": "x", "bear_score": 1}) is not None:
        f.append("旧格式/坏数应无分歧摘要")
    # k 拟合: 真 k≈1.8 的两个关键样本只有 k∈[1.65,1.85] 同时判对 → 并列取近 1.5 = 1.65 → 收缩 (6×1.65+10×1.5)/16
    core = [(50, 80, 1), (50, 95, -1), (80, 20, 1), (20, 80, -1), (70, 40, 1), (30, 90, -1)]
    if debate_fit_k(core) != (1.556, 1.65, 6):
        f.append(f"k 拟合/收缩错: {debate_fit_k(core)}")
    if debate_fit_k(core[:4] + [(50, 50, 0)]) != (DEBATE_K0, None, 4):
        f.append("有标签样本<5 应用先验 1.5(标签 0 不计)")
    if debate_fit_k(core[2:] + [(90, 10, 1)])[1] != DEBATE_K0:
        f.append("各 k 一致率并列时应取 1.5")
    if not (DEBATE_K_LO <= debate_fit_k([(50, 99, 1)] * 6)[0] <= DEBATE_K_HI):
        f.append("k 越出 [1,2]")
    vs = v03side("多")
    if vs({"side": "多", "strongest_args": ["a", "b"], "honest_weakness": "w"}, {}) or \
            not vs({"side": "多", "strongest_args": ["a", "b"], "honest_weakness": "w"}, {"debate_v2": True}) or \
            vs({"side": "多", "strongest_args": ["a", "b"], "honest_weakness": "w", "concede_if": "c"}, {"debate_v2": True}):
        f.append("concede_if 只在处理组必填: 判定错")
    pc = {"cap": 20000.0}
    cg = {"sub": False, "pc": pc, "contracts": {"03j": {**ok2, "bull_score": 50, "bear_score": 75}}}   # k=1.5 → 有效空 50 → 均衡/高/0.5
    d = debate_apply(cg, kinfo=K15)
    buy = lambda px, q, anc=10.0, op="买": {"name": "X", "op": op, "_px": px, "qty": q, "anchor": anc}
    chk = _debate_wrap_v06(lambda c, ctx: None)
    if not d or d["chase_cap"] != 10000.0 or d["bear_eff"] != 50.0:
        f.append(f"debate_apply 未写 pc/chase_cap/有效空分: {d}")
    elif not chk({"actions": [buy(10.0, 1500)]}, cg):
        f.append("追价买单超折扣上限未抓")
    else:
        for acts, why in (([buy(9.5, 1500)], "回踩条件单"), ([buy(10.0, 900)], "追价单未超"), ([buy(10.0, 3000, op="卖")], "卖单"),
                          ([{"op": "撤单", "order_id": "o1"}], "撤单(无价)")):
            if chk({"actions": acts}, cg):
                f.append(f"追价折扣闸误杀: {why}")
        if chk({"actions": [buy(10.0, 1500)]}, {**cg, "final_attempt": True}) or chk({"actions": [buy(10.0, 1500)]}, {**cg, "sub": True}):
            f.append("追价折扣闸 末次/子链 应放行")
        if _debate_wrap_v06(lambda c, ctx: "原 v06 失败")({"actions": []}, cg) != "原 v06 失败":
            f.append("外包层吞了原 v06 失败原因")
        old = os.environ.get("CHAIN_DEBATE_GATE")
        os.environ["CHAIN_DEBATE_GATE"] = "0"
        if chk({"actions": [buy(10.0, 1500)]}, cg):
            f.append("CHAIN_DEBATE_GATE=0 未关闸")
        os.environ.pop("CHAIN_DEBATE_GATE") if old is None else os.environ.__setitem__("CHAIN_DEBATE_GATE", old)
        t = debate_text(pc, "05")
        if not any("少数派风险" in x for x in t) or not any("追价折扣" in x for x in t) or not any("k=1.5" in x for x in t) \
                or debate_text(pc, "02") or debate_text({"cap": 1}, "06"):
            f.append(f"注入块错: {t}")
    with tempfile.TemporaryDirectory() as td:   # 复算块: 插在末个 contract 前, contract/哨兵不变, 幂等
        body = f"# 03\n正文\n```contract\n{json.dumps(cg['contracts']['03j'], ensure_ascii=False)}\n```\nSTEP_OK 03j 20260930\n"
        _write_lf(Path(td) / ART["03j"], body)
        debate_apply(dict(cg, pc={"cap": 1000.0}), td, kinfo=K15)
        debate_apply(dict(cg, pc={"cap": 1000.0}), td, kinfo=K15)
        t2 = (Path(td) / ART["03j"]).read_text(encoding="utf-8")
        if t2.count("驱动器复算(DEBATE_V2") != 1 or "k=1.5" not in t2 or contract_of(t2)[0] != cg["contracts"]["03j"] \
                or sentinel_ok(t2, "03j", "20260930") is not True or not (Path(td) / "debate.json").exists():
            f.append("03j 复算块渲染/幂等/contract 保持 错")
    if debate_apply({"sub": True, "pc": {"cap": 1.0}, "contracts": {"03j": ok2}}, kinfo=K15) is not None:
        f.append("盘中子链不应用 0915 的 03 分歧")
    pc2 = {"cap": 1.0, "debate": {"x": 1}}
    debate_apply({"sub": False, "pc": pc2, "contracts": {"03j": {"winner": "多", "decisive_reason": "r"}}})
    if "debate" in pc2:
        f.append("旧格式 03j 应清掉残留 pc.debate")
    old = os.environ.get("CHAIN_NO03_SKILLS")
    os.environ["CHAIN_NO03_SKILLS"] = f"{SKILL_NAME}, foo"
    on = no03_on()
    os.environ["CHAIN_NO03_SKILLS"] = "foo"
    off = no03_on()
    os.environ.pop("CHAIN_NO03_SKILLS") if old is None else os.environ.__setitem__("CHAIN_NO03_SKILLS", old)
    if not on or off:
        f.append(f"停 03 白名单判定错: on={on} off={off}")
    if _gate_env is None:
        os.environ.pop("CHAIN_DEBATE_GATE", None)
    else:
        os.environ["CHAIN_DEBATE_GATE"] = _gate_env
    return f


def v03side(want):
    def v(c, ctx):
        if c.get("side") != want:
            return f"side 非法: {c.get('side')}(应为{want})"
        if len(c.get("strongest_args") or []) < 2:
            return "strongest_args<2 条"
        if not c.get("honest_weakness"):
            return "honest_weakness 空(不许藏弱)"
        if ctx.get("debate_v2") and not str(c.get("concede_if") or "").strip():   # 10/16 晚 保留分歧版: 认输条件=下游翻转条件的来源
            return "concede_if 空(写出竞价/早盘出现什么可观测事实你方就认输, 带具体数)"
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
    # 10/14 晚 修⑤: 子链没有 05, 04 候选只能 ⊆ 0915-05 批准∪条件批准 ∪ 持仓 ∪ 未成交挂单(10/14 大兴 1455 上海电影被 06 驳回案); 末次尝试=机械剔除+WARN
    allow = ctx.get("sub_allow") if FIX_SUB_APPROVED and ctx.get("sub") else None
    if allow:
        bad = [x for x in cands if x.get("name") not in allow["names"] and str(x.get("code") or "") not in allow["codes"]]
        if bad and not ctx.get("final_attempt"):
            return (f"子链候选 {[x.get('name') for x in bad]} 不在 0915-05 批准名单/持仓/未成交挂单内——子链没有 05 风控, "
                    f"名单外新票不能进候选(删掉或换成约束块列出的名单内票)")
        if bad:
            print(f"WARN: 子链 04 末次仍有名单外候选 {[x.get('name') for x in bad]}, 驱动器机械剔除")
            c["candidates"] = cands = [x for x in cands if x not in bad]
    # 10/12: 总仓下限需 need_n 只买入票时, 候选不足当场回炉(末次尝试放行, 不因数量闸中止链; 有断链说明=推不出个股, 不硬凑)
    need = (ctx.get("pc") or {}).get("need_n", 0)
    if allow:   # 子链名单有限: 要求的候选数不超过名单内可买票数(否则两闸互逼)
        need = min(need, len(allow["approved"]))
    if need and len(cands) < need and not c.get("断链说明") and not ctx.get("final_attempt") and not soft_floor(ctx.get("pc")):
        return f"候选 {len(cands)} 只 < {need} 只(总仓下限还差 {ctx['pc']['gap']:.0f} 元, 单票上限 {ctx['pc']['cap']:.0f})——扩候选(同方向次选/遗留票), 证据不足的降置信度而非删"
    return horizon_cand_check(c, ctx) or defer_check(c, ctx, "04")

def v05(c, ctx):
    got = {v.get("name") for v in (c.get("verdicts") or [])}
    want = {x.get("name") for x in (ctx["contracts"].get("04", {}).get("candidates") or [])}
    if got != want:
        return f"05 名单 != 04 候选: 缺{sorted(want - got)} 多{sorted(got - want)}"
    for v in c.get("verdicts") or []:
        if v.get("result") not in ("批准", "否决", "条件批准"):
            return f"verdict 非法: {v.get('result')}"
    # 10/12: 批准数不够凑下限=06 必回炉, 改在 05 当场回炉(04 候选本身不够则 05 无解, 不拦; 末次尝试放行)
    pc = ctx.get("pc") or {}
    need = pc.get("need_n", 0)
    n_ok = sum(1 for v in c.get("verdicts") or [] if v.get("result") in ("批准", "条件批准"))
    if need and n_ok < need <= len(want) and not ctx.get("final_attempt") and not soft_floor(ctx.get("pc")):
        return (f"批准+条件批准 {n_ok} 只 < 至少 {need} 只(总仓下限还差 {pc['gap']:.0f} 元÷单票上限 {pc['cap']:.0f}), 06 必然凑不满——"
                f"复核否决: 有硬伤(否决条款池/选股硬过滤命中)的照旧否决, 仅形态担忧/证据偏弱的改条件批准(更严触发价/失效条件)")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import a_rules as _AR  # noqa: E402  10/16 晚: 交易规则统一模块(出处 docs/rules/a_share_trading_rules.md)


def limit_of(code, date=None, name=None):
    """板限判定阈值%(板限-0.3pt 余量, 与 snapshot.mjs limitOf 同口径)。10/16 晚改走 a_rules: 转债 20%(原误按 10%)、
    主板 ST 2026-07-06 前 5%、新股前 5 日/北交所首日无涨跌幅(=inf)、科创/创业类 ETF 20%; date=None 按今天规则"""
    p = _AR.limit_pct(code, date, name=name, lookup=False)
    return float("inf") if p is None else round(p * 100 - 0.3, 4)

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

def _verdict_caps(ctx):
    """10/14 §3-A 第 3 条: 05 verdicts 里逐票的 cap(元, 可选, 正数)→ {票名: cap}"""
    out = {}
    for v in ctx["contracts"].get("05", {}).get("verdicts") or []:
        try:
            cv = float(v.get("cap"))
        except (TypeError, ValueError):
            continue
        if cv > 0:
            out[v.get("name")] = cv
    return out


EXIT_KINDS = ("stop", "protect", "invalid", "discretionary")


def _held_codes(ctx):
    pc = ctx.get("pc")
    if pc and "held" in pc:
        return set(pc["held"])
    return set(((ctx.get("book") or {}).get("positions") or {}))


def forced_exit(a):
    """10/14 晚 修①: 止损/保护线/失效条件触发的离场卖单(exit_kind 非 discretionary)——不受总仓下限约束; 开关关=恒假"""
    return FIX_FLOOR_EXIT and a.get("op") in SELL_OPS and str(a.get("exit_kind") or "discretionary") in ("stop", "protect", "invalid")


# ---------- 10/16 审计#2/#12: 06 新动词(全可选; 不写=旧行为逐字节不变) ----------
# op="开盘卖": 持仓票市价卖——盘前单=开盘价/开盘后首个快照价, 盘中单=下一次撮合现价; 不受 ±2% 笼子; plans 行=SELL+cond open_sell=1, 挂价列=anchor(仅参考)
# op="撤单": 撤指定未成交挂单, order_id(paper_state.json open_orders 的 id) 或 code+side(买/卖); 驱动器按账本解析成挂单号 → plans CXL 行 cond oid=<id>
# not_before="HH:MM": 该单此刻前不撮合(三种撮合模式都执行; 生效后按连续竞价新报单对待, 吃笼子); plans cond not_before=HHMM
SELL_OPS = ("卖", "开盘卖")
OP_ALIAS = {"market_open_sell": "开盘卖", "open_sell": "开盘卖", "cancel": "撤单", "撤": "撤单", "auction_t": "竞价T", "竞价t": "竞价T"}
# 10/18 op="竞价T"(转债 T+0, 土豆 R8): 0915 盘前单, 集合竞价按开盘价买(trigger_price=愿付上限, 开盘价高于它=没买到), matcher 开盘后首个价自动卖; plans=BUY+cond t0_open_exit=1


def _norm_nb(v):
    """not_before 规范化: "H:MM"/"HH:MM"/"HHMM" → "HH:MM", 须在连续竞价 [09:30, 15:00) 内; 非法=None"""
    m = re.fullmatch(r"(\d{1,2}):?(\d{2})", str(v).strip())
    if not m or int(m.group(2)) > 59:
        return None
    s = f"{int(m.group(1)):02d}:{m.group(2)}"
    return s if "09:30" <= s < "15:00" else None


def _cxl_check(a, ctx):
    """op=撤单: 校验 order_id 或 code+side, 按账本未成交挂单解析出目标 → a["_cxl"]={id,code,side}; 找不到=WARN 不落 plans(可能已成交/已撤)"""
    oid = str(a.get("order_id") or "").strip()
    code = str(a.get("code") or "").strip()
    side = {"买": "BUY", "卖": "SELL", "BUY": "BUY", "SELL": "SELL"}.get(str(a.get("side") or "").strip())
    if not oid and not (re.fullmatch(r"\d{6}", code) and side):
        return "撤单须给 order_id(paper_state.json open_orders 里的 id) 或 code(6位)+side(买/卖)"
    if oid and not re.fullmatch(r"[\w-]+", oid):
        return f"撤单 order_id 非法: {oid}"
    if a.get("not_before") is not None:
        return "撤单不带 not_before(撤单导入即生效)"
    opens = [o for o in ((ctx.get("book") or {}).get("orders") or []) if o.get("status") == "open"]
    hit = next((o for o in opens if o.get("id") == oid), None) if oid else \
        next((o for o in opens if str(o.get("code")) == code and o.get("side") == side), None)
    if hit and oid and code and str(hit.get("code")) != code:
        return f"撤单 order_id {oid} 的代码是 {hit.get('code')}, 与 code {code} 不符"
    a["_cxl"] = {"id": hit["id"], "code": str(hit["code"]), "side": hit.get("side")} if hit else None
    if not hit:
        print(f"WARN: 撤单 {oid or code + '/' + side} 无匹配未成交挂单(可能已成交/已撤), 本条不落 plans")
    return None


def _new_codes(acts):
    """总仓口径里"本次涉及的票"(其未成交买单不再重复计): 交易动作的 code + 撤单撤掉的买单 code(无撤单时=旧口径)"""
    return {str(a.get("code")) for a in acts if a.get("op") != "撤单"} | {
        a["_cxl"]["code"] for a in acts if a.get("op") == "撤单" and a.get("_cxl") and a["_cxl"]["side"] == "BUY"}


def esc06(c):
    """10/14 晚 修④: 06 发起升级 = contract escalate=true, 或 supersedes 里写了 ESCALATE(10/13 桃哥 1127 只写在正文/supersedes, 驱动器原先看不见)"""
    if c.get("escalate") is True:
        return True
    # 只认"发起/触发/申请 ESCALATE"(10/13 桃哥 1127 原文"06发起ESCALATE_FULL_CHAIN"); 引述往期升级("1230档ESCALATE停跑")与否定式不算
    s = str(c.get("supersedes", ""))
    for m in re.finditer(r"(发起|触发|申请|请求|提请)\s*(?:全链)?\s*ESCALATE", s, re.I):
        if not re.search(r"(不|未|无需|无须|禁止|不再|不必|没有|非)\s*$", s[max(0, m.start() - 6):m.start()]):
            return True
    return False


def holds_check(c, acts, ctx):
    """10/14 晚 holds: actions 空时必须说明维持了什么(holds)或为何不动(no_trade_reason), 二选一; 末次尝试放行+WARN"""
    if not FIX_HOLDS:
        return None
    holds, ntr = c.get("holds"), str(c.get("no_trade_reason") or "").strip()
    err = None
    if holds is not None and (not isinstance(holds, list) or any(
            not isinstance(h, dict) or not (h.get("order_id") or h.get("code")) or not str(h.get("why") or "").strip() for h in holds)):
        err = "holds 格式非法(须 [{\"order_id\":\"挂单号\" 或 \"code\":\"6位代码\",\"why\":\"为何维持\"}, ...])"
    elif not acts and not holds and not ntr:
        err = ("actions 为空但没写 holds/no_trade_reason——二选一: holds=[{\"order_id\"或\"code\",\"why\"}] 列出本次维持的挂单/持仓, "
               "或 no_trade_reason=一句话说明为何本次不动")
    if err and _soft_once(ctx, "holds"):
        print(f"WARN: 06 {err}; 已回炉过一次, 放行")
        return None
    return err


def v06(c, ctx):
    acts = c.get("actions") or []
    approved = {v["name"] for v in (ctx["contracts"].get("05", {}).get("verdicts") or [])
                if v.get("result") in ("批准", "条件批准")}
    vcaps = _verdict_caps(ctx)
    snaps = ctx.get("snap") or {}
    sk = ctx["skill"]  # skill 差集(10/4 参数化): 规则 id 正则/高位类集合/code 闸/仓位上限
    held_codes = _held_codes(ctx) if FIX_FLOOR_EXIT else set()
    for a in acts:
        if a.get("op") in OP_ALIAS:   # 10/16 新动词: 英文别名归一
            a["op"] = OP_ALIAS[a["op"]]
        if a.get("op") == "撤单":     # 撤单不是交易: 不过 05 批准集/价/量/锚校验
            err = _cxl_check(a, ctx)
            if err:
                return f"{a.get('name') or a.get('order_id') or a.get('code')} {err}"
            continue
        if a.get("not_before") is not None:
            nb = _norm_nb(a.get("not_before"))
            if not nb:
                return f"{a.get('name')} not_before 非法: {a.get('not_before')}(须 \"HH:MM\", 在 09:30~14:59 之间)"
            a["_nb"] = nb
        if a.get("op") == "竞价T":   # 10/18: 只许 0915 盘前、转债; 校验完当买单走后续闸(批准集/数量/价格/单票上限), plans 带 t0_open_exit
            if ctx.get("sub") or not re.fullmatch(r"1[12]\d{4}", str(a.get("code", ""))):
                return f"{a.get('name')} 竞价T 只许 0915 盘前单、转债(11/12 开头); 盘中子链或股票不能用"
            if a.get("cancel_below") is not None or a.get("stop_below") is not None or a.get("_nb"):
                return f"{a.get('name')} 竞价T=竞价买+开盘即卖, 不带 cancel_below/stop_below/not_before"
            a["op"], a["_t0"] = "买", True
        if a.get("op") == "开盘卖":
            if str(a.get("code", "")) not in _held_codes(ctx):
                return f"{a.get('name')} 开盘卖只许卖现有持仓, {a.get('code')} 不在持仓"
            if a.get("cancel_below") is not None or a.get("stop_below") is not None:
                return f"{a.get('name')} 开盘卖=市价卖, 不带 cancel_below/stop_below"
        if FIX_FLOOR_EXIT and a.get("exit_kind") is not None:
            if str(a.get("exit_kind")) not in EXIT_KINDS:
                return f"{a.get('name')} exit_kind 非法: {a.get('exit_kind')}(只许 stop/protect/invalid/discretionary)"
            if forced_exit(a) is False and str(a.get("exit_kind")) != "discretionary":
                return f"{a.get('name')} exit_kind={a.get('exit_kind')} 只许用于卖单(买单不写或写 discretionary)"
            if forced_exit(a) and str(a.get("code", "")) not in held_codes:
                return f"{a.get('name')} exit_kind={a.get('exit_kind')} 只许用于现有持仓的离场卖单, {a.get('code')} 不在持仓"
        # 修①: 已持仓票的止损/保护线/失效离场卖单不受 05 批准集约束(05 只管开仓/调仓, 离场纪律不能被"未过堂"卡住)
        if a.get("name") not in approved and not (forced_exit(a) and str(a.get("code", "")) in held_codes):
            return f"06 标的 {a.get('name')} ∉ 05 批准集"
        if not re.fullmatch(sk["code_re"], str(a.get("code", ""))):
            return f"{a.get('name')} code 不符本链闸({sk['code_re']}): {a.get('code')}"
        if not (isinstance(a.get("qty"), int) and a["qty"] > 0):
            return f"{a.get('name')} qty 非正整数: {a.get('qty')}"
        if a.get("op") == "买":   # 10/16 晚: 申报数量规则(主板/创业板 100 股整数倍; 科创板 200 股起 1 股递增; 北交所 100 股起 1 股递增; 转债 10 张整数倍)
            _okq, _why = _AR.valid_qty(str(a.get("code", "")), a["qty"], "BUY")
            if not _okq:
                return f"{a.get('name')} qty {a['qty']} 不合申报规则: {_why}"
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
        if a.get("op") == "开盘卖":   # 市价卖: 不用 trigger_price, 挂价列=anchor(参考价, 照过区间闸/算账)
            px, formula = resolve_px(a.get("anchor"), None)
            if px is None:
                return f"{a.get('name')} 开盘卖须给 anchor(数值, 取 facts 快照价): {a.get('anchor')}"
        else:
            px, formula = resolve_px(a.get("trigger_price"), prev)
        if px is None:
            return f"{a.get('name')} trigger_price 非数值/可求值公式(Z*系数): {a.get('trigger_price')}"
        a["_px"], a["_formula"] = px, formula  # 回填取数口, emit_plans 直接用(不再二次解析)
        if prev:   # 10/16 晚: 按 a_rules 精确涨跌停价(转债 20%/0.001 价位、ST 按日期、新股无涨跌幅=不设区间)
            nm = (snaps.get(code) or {}).get("name") or a.get("name")
            hi, lo = _AR.limit_prices(code, ctx.get("date_dash"), prev, name=nm, lookup=False)
            half = _AR.tick(code) / 2
            if hi is not None and not (lo - half <= px <= hi + half):
                return f"{a.get('name')} 挂单价 {px} 出当日涨跌停区间 [{lo},{hi}](前收{prev})=编造嫌疑 C7-①"
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
        if a.get("chase_cap") is not None:   # 10/20 晚 ②: 追价上限价(可选, 只许买单; ≥ 挂价且 ≤ 涨停价)
            cc = a["chase_cap"]
            if a.get("op") != "买" or not isinstance(cc, (int, float)) or cc < a["_px"]:
                return f"{a.get('name')} chase_cap 只许买单带, 且是不低于挂价的数值(你写的 {cc}, 挂价 {a['_px']})"
        if MIMIC_REVIEW and a.get("op") == "买" and isinstance(a.get("cancel_below"), (int, float)) and a["cancel_below"] > a["_px"]:   # 10/16 晚: 原盲审⑥语义矛盾价归机械层
            return f"{a.get('name')} 买单 cancel_below {a['cancel_below']} 高于挂单价 {a['_px']}(跌到挂单价之前先触发撤单=永远成交不了), 撤单线要低于挂单价"
        cap = (ctx.get("pc") or {}).get("cap") or sk["cap_ratio"] * ctx["nav"]  # 单票上限: 10/13 起=pos_constraints 按导师习惯算的动态值(无 pc=旧固定口径)
        tight = vcaps.get(a.get("name"))
        if a.get("op") == "买" and tight and tight < cap and a["_px"] * a["qty"] > tight:
            return f"{a.get('name')} 金额 {a['_px'] * a['qty']:.0f} 超 05 给该票定的上限 {tight:.0f}(05 风控意见是硬约束; 要凑总仓请加别的批准票)"
        if a.get("op") == "买" and a["_px"] * a["qty"] > cap:
            return f"{a.get('name')} 金额 {a['_px'] * a['qty']:.0f} 超单票上限 {cap:.0f}"
        e_fr = floor_rule_check(a, ctx, held_codes if FIX_FLOOR_EXIT else _held_codes(ctx))   # 10/20 下限收窄: 新开仓须引买规则
        if e_fr:
            return e_fr
        if SIZE_RULES and a.get("op") == "买" and SKILL_NAME in TZZB_LEDGERS:
            pcx = ctx.get("pc") or {}
            sm = pcx.get("single_med")
            if sm and code not in held_codes:   # ① 新开仓首笔: 不低于导师单票习惯的 75%(现金不够就按现金, 05 给的逐票上限优先)
                need = min(SIZE_MIN_FRAC * sm * (pcx.get("nav") or ctx["nav"]), cap, tight or cap, 0.98 * float(pcx.get("cash") or 0))
                lim_l = ((ctx.get("ledger") or {}).get("lim") or {}) if LEDGER else {}
                if lim_l.get("turnover_max"):   # 和账本"单日换手上限"不打架: 一单的最小金额不超过换手预算的 9 成
                    need = min(need, 0.9 * float(lim_l["turnover_max"]) * (pcx.get("nav") or ctx["nav"]))
                trial = lim_l.get("first_frac") is not None and (ctx.get("ledger") or {}).get("slot") == "0915" and not ctx.get("sub")
                if trial:   # 和账本"0915 先小仓试错"不打架: 本导师习惯开盘先小仓、方向对了再加, 0915 不要求下够(盘中加仓是已持仓, 也不受本条约束)
                    need = 0
                if need > 0 and a["_px"] * a["qty"] < need * 0.9:   # 0.9 = 整手取整余量
                    return (f"{a.get('name')} 新开仓金额 {a['_px'] * a['qty']:.0f} 元 < 本导师单票习惯的 75%(≈{need:.0f} 元; 真人单票最大仓位中位 {sm:.0%})——"
                            f"导师是集中下注的, 不要拆成很多小单: 少挑几只、每只新开仓至少按这个金额下(多挂几只备选也行, 现金先到先得)")
            cb = a.get("cancel_below")   # ② 失效线不能比当天正常波动还近: 自动放宽到 挂价 × (1 − 半个日振幅中位)
            if isinstance(cb, (int, float)) and 0 < cb < a["_px"]:
                amp = _amp_median(code, ctx.get("date_dash"), 30)
                if amp:
                    lo_ok = a["_px"] * (1 - CXL_AMP_FRAC * amp / 100)
                    if cb > lo_ok:
                        tk = _AR.tick(code)
                        new = round(int(lo_ok / tk) * tk, 3)
                        print(f"失效线放宽: {a.get('name')}({code}) cancel_below {cb} → {new}(挂价 {a['_px']}, 近 30 日日振幅中位 {amp:.1f}%, 失效线至少离挂价半个振幅)")
                        a["cancel_below"] = new
    # 10/13 F: 可选字段 persona_sections(依据了画像哪几节)——仅 F 开启(ctx 有 profile_ids)时校验编号存在; 不填不拦
    ps = c.get("persona_sections")
    if ctx.get("profile_ids") is not None and ps is not None:
        bad = [x for x in (ps if isinstance(ps, list) else [ps]) if str(x) not in ctx["profile_ids"]]
        if bad or not isinstance(ps, list):
            return f"persona_sections 须为画像目录编号列表(如 [\"S05\"]), 不存在的编号: {bad or ps}"
    if c.get("no_trade") and not acts and not str(c.get("no_trade_reason") or "").strip():
        return "no_trade=true 且无 actions 时要写 no_trade_reason(一句话为何今天不动)"   # 10/16 审计#6: 允许纯观望(真人一周不动是常态), 只要求给理由
    # 10/7 晚定稿(分层): 首跑期测试下限——真人拟人链 0.4 / tzzb 系 0.8, 防空仓白测; 可多票凑足
    # 10/12 修: 口径=总仓(现有持仓市值+未成交买单+本次买单−本次卖单), 原只算本次买单(子链对已近满仓账户逼买);
    # 05 批准集按单票上限都凑不满时=不可达, 放行+WARN(回炉也无解, 白烧 token)
    _floor = (ctx["pc"]["floor"] if ctx.get("pc") and "floor" in ctx["pc"]
              else {"tzzb": TEST_FLOOR_TZZB, "like": TEST_FLOOR}.get(sk.get("floor_key"), TEST_FLOOR))   # 10/13 起=动态下限
    if _floor and not c.get("no_trade"):
        pc = ctx.get("pc") or {"held": {}, "open_buy": {}}
        new_codes = _new_codes(acts)   # 10/16: 撤单动作不算新单, 但撤掉的买单不再计入未成交买单
        held = dict(pc["held"])
        _sell = 0.0
        _forced = 0.0
        for a in acts:
            if a.get("op") in SELL_OPS:
                if forced_exit(a):   # 10/14 晚 修①: 止损/保护线/失效离场不计入下限口径(下限只约束主动减仓)
                    _forced += a["_px"] * a["qty"]
                    continue
                v = min(a["_px"] * a["qty"], held.get(str(a["code"]), 0.0))
                held[str(a["code"])] = held.get(str(a["code"]), 0.0) - v
                _sell += v
        _ob = sum(v for k, v in pc["open_buy"].items() if k not in new_codes)  # 同票新单会 CXL 旧单, 不重复计
        _total_buy = sum(a["_px"] * a["qty"] for a in acts if a.get("op") == "买")
        _base = sum(held.values()) + _ob
        _total, _req = _base + _total_buy, _floor * ctx["nav"]
        if _total < _req:
            _cap = (ctx.get("pc") or {}).get("cap") or sk["cap_ratio"] * ctx["nav"]
            _room = sum(min(_cap, vcaps.get(n, _cap)) for n in approved)   # 10/14: 05 逐票更严上限计入可达性
            if soft_floor(ctx.get("pc")):   # 10/15 晚: 软下限——不凑满放行, 记一笔供复盘(没有本导师风格的票就不硬凑)
                print(f"WARN: 软下限未凑满(总仓 {_total:.0f} < 参考下限 {_req:.0f}), 按软约束放行")
                ctx["floor_short"] = round(_req - _total, 2)
            elif _base + _room < _req:
                print(f"WARN: 总仓下限不可达(05 批准 {len(approved)} 只按逐票上限可买 {_room:.0f} + 现有 {_base:.0f} < {_req:.0f}), 放行不回炉")
            else:
                return (f"总仓 {_total:.0f}(持仓≈{sum(pc['held'].values()):.0f}+未成交买单{_ob:.0f}+本次买{_total_buy:.0f}−本次卖{_sell:.0f}) "
                        f"< 测试下限 {_floor*100:.0f}% nav={_req:.0f}, 还差 {_req - _total:.0f}——从 05 批准集加买单凑足(单票≤{_cap:.0f})"
                        + (f"(止损/保护线/失效离场卖单 {_forced:.0f} 已按 exit_kind 豁免, 不计入)" if _forced else ""))
    if ctx["sub"] and "首裁" not in str(c.get("supersedes", "")) \
            and not re.search(r"维持|取代", str(c.get("supersedes", ""))):
        return "盘中重跑 supersedes 未显式含 维持/取代"
    if not ctx["sub"] and not re.search(r"首[裁日次]|回炉|首日建链", str(c.get("supersedes", ""))):
        # 10/13 bug 修复(用户令, 直接生效): 盘前首裁不再因 supersedes 措辞回炉(10/13 实盘 4 次回炉 3 次是这个)——驱动器归一为"首裁"
        print(f"WARN: 盘前首裁 supersedes 缺'首裁/首日/回炉'字样, 驱动器归一为'首裁'(原文: {str(c.get('supersedes', ''))[:80]})")
        c["supersedes"] = "首裁"
    return holds_check(c, acts, ctx) or defer_check(c, ctx, "06")

def v07(c, ctx):
    if not c.get("预案对照"):
        return "预案对照 空"
    if ATTRIBUTION and SKILL_NAME != "control":   # 10/20 晚 ④: 根因必答(软闸, 回炉一次)
        rc = c.get("root_causes")
        if not isinstance(rc, list) and not _soft_once(ctx, "root07"):
            return ("contract 缺 root_causes: 每个亏损来源落到一层 [{\"layer\":\"数据|驱动器|规则|判断|撮合\",\"item\":\"哪一项\",\"fix\":\"改哪里\",\"affects\":\"波及哪些链\","
                    "\"replay\":\"用今天数据回放改了是否更好\"}](当天确实没亏损来源写 [] 并在正文说明)")
    return lessons_check(c, ctx)


def lessons_check(c, ctx):
    """10/16 晚: 07 lessons=[{"type":"规则草案|规则修正|错误归因","text":"…","evidence":"…"}] / 多日核对=[{"date","horizon_days","view","result":"对|部分对|错|无法判断","why"}]
    有就校验格式; lessons 缺: 开关开=软回炉一次(末次放行), 开关关=放行"""
    ls = c.get("lessons")
    if ls is None:
        if HORIZON and SKILL_NAME != "buchitudou0" and not _soft_once(ctx, "lessons07"):
            return ("contract 缺 lessons——know-how 反思四问(因/导师会怎么做/我们差在哪/下次怎么改)的结论要落成 "
                    "lessons:[{\"type\":\"规则草案|规则修正|错误归因\",\"text\":\"可证伪的一条\",\"evidence\":\"出处\"}](今天确实无可沉淀=写 [] 并在正文说明)")
        return None
    if not isinstance(ls, list):
        return "lessons 须为列表"
    for i, x in enumerate(ls):
        if not isinstance(x, dict):
            return f"lessons[{i}] 须为对象"
        t = norm_enum(x.get("type"), LESSON_TYPES)
        if not t:
            return f"lessons[{i}].type 非法: {x.get('type')}(只许 规则草案/规则修正/错误归因/case卡)"
        x["type"] = t
        for k in ("text", "evidence"):
            if not str(x.get(k) or "").strip():
                return f"lessons[{i}].{k} 空(text=一条可证伪的规则/修正/归因, evidence=证据出处: 哪天哪步哪只票/真人哪笔操作)"
    md = c.get("多日核对")
    if md is not None:
        if not isinstance(md, list):
            return "多日核对 须为列表"
        for i, x in enumerate(md):
            r = norm_enum((x or {}).get("result") if isinstance(x, dict) else None, MULTI_RESULTS)
            if not r:
                return f"多日核对[{i}].result 非法: {(x or {}).get('result') if isinstance(x, dict) else x}(只许 对/部分对/错/无法判断)"
            x["result"] = r
            if not str(x.get("why") or "").strip():
                return f"多日核对[{i}].why 空(对照实际走势一句话说明对错)"
    mm = c.get("拟人对照")   # 10/16 晚: tzzb 导师链 07 主轴=拟人偏差(真人当日操作=标签)
    if mm is not None:
        if not isinstance(mm, list):
            return "拟人对照 须为列表"
        for i, x in enumerate(mm):
            if not isinstance(x, dict) or not norm_enum(x.get("项"), MIMIC_ITEMS):
                return f"拟人对照[{i}].项 非法: {x.get('项') if isinstance(x, dict) else x}(只许 交不交易/方向/标的/仓位/时段)"
            x["项"] = norm_enum(x.get("项"), MIMIC_ITEMS)
            if not isinstance(x.get("一致"), bool):
                return f"拟人对照[{i}].一致 须为 true/false"
            if not x["一致"]:
                cause = norm_enum(x.get("原因"), MIMIC_CAUSES)
                if not cause:
                    return f"拟人对照[{i}]({x['项']}) 不一致时 原因 只许 事实包缺信息/理解错导师框架/其他: {x.get('原因')}"
                x["原因"] = cause
    return None

def vblind(c, ctx):
    if c.get("verdict") not in ("pass", "fail"):
        return "盲审 contract verdict 非法"

VALIDATORS = {"01": v01, "02": v02, "03b": v03side("多"), "03s": v03side("空"), "03j": v03, "04": v04, "05": v05, "06": v06, "07": v07, "blind": vblind}
VALIDATORS["06"] = _debate_wrap_v06(VALIDATORS["06"])   # 10/16 晚 保留分歧版: 0915 追价买单按 03 分歧打折(无 pc.debate=原 v06 逐字节同行为)


# ---------- 10/16 晚 言行一致性机械检查(TODO 三-3 第一期 + 二B-7 引用核对; 开关 chain_flags.txt CHAIN_CONSISTENCY, 关=原 v06 逐字节同行为) ----------
# 一致性: 本单净方向(主动买−主动卖占 nav; 止损/保护/失效离场不计) vs 预期方向(02 态度 + 0915 的 03 倾向, 两者同向才算明确);
#   按导师对市况的敏感度打折: 真人近 60 日收盘总仓"日变动 >20%"的天数占比 <15% = 仓位不随市况变(如星见野恒满仓) → 不查;
#   矛盾(预期多却净卖 >5% nav / 预期空却净买 >5% nav) 或 盘中同日先卖后买回同一只 → 06 须填 deviation_reason(≥8 字), 缺=回炉, 末次放行记日志
# 引用核对: 每个 action 的 code 必须在 01/cand_snap 快照、持仓或 01_facts.md 里出现; 快照里有名称时 name 须对得上(防编造/张冠李戴)
CONSIST_EPS = 0.05


def _mentor_insensitive(skill):
    try:
        d = json.loads((ROOT / "downloads" / "tzzb" / skill / "day_positions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cut = (ASOF or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
    tot = []
    for day in sorted(k for k in d if k < cut)[-61:]:
        tot.append(min(1.5, sum(float(p.get("position_percent") or 0) for p in (d[day] or {}).get("list") or []
                                if not str(p.get("code") or "").startswith(("204", "1318")))))
    if len(tot) < 20:
        return None
    moves = sum(1 for a, b in zip(tot, tot[1:]) if abs(b - a) > 0.2) / (len(tot) - 1)
    return moves < 0.15


def consistency_eval(c, ctx):
    pc, snaps = ctx.get("pc") or {}, ctx.get("snap") or {}
    nav = float(pc.get("nav") or ctx.get("nav") or 0) or 1.0
    net = 0.0
    for a in c.get("actions") or []:
        try:
            px = float(a.get("_px") or a.get("anchor") or (snaps.get(str(a.get("code"))) or {}).get("last") or 0)
        except (TypeError, ValueError):
            px = 0.0
        amt = px * float(a.get("qty") or 0)
        if a.get("op") == "买":
            net += amt
        elif a.get("op") in SELL_OPS and not forced_exit(a):
            net -= amt
    st = {"多": 1, "空": -1}.get(pc.get("stance") or (ctx["contracts"].get("02") or {}).get("stance"), 0)
    d = pc.get("debate")
    lean = {"多": 1, "空": -1}.get((d or {}).get("lean"), 0) if d else None
    exp = st if lean is None else (st if st == lean else 0)
    # 10/18: 判空却净买时, 补仓位下限(pc.gap=下限缺口)的那部分是驱动器逼的, 不算言行背离(沙盒 37 次背离约 2/3 是这种); 只查超出下限的主动加仓
    fill = min(max(net, 0.0), float(pc.get("gap") or 0)) if exp < 0 else 0.0
    netp = (net - fill) / nav
    contra = (exp > 0 and netp < -CONSIST_EPS) or (exp < 0 and netp > CONSIST_EPS)
    back = []
    if ctx.get("sub"):
        today = ctx.get("date_dash") or ""
        sold = {t["code"] for t in (ctx.get("book") or {}).get("trades") or [] if str(t.get("id", ""))[:10] == today and t.get("side") == "SELL"}
        back = [a.get("name") for a in c.get("actions") or [] if a.get("op") == "买" and str(a.get("code")) in sold]
    insens = _mentor_insensitive(SKILL_NAME) if SKILL_NAME in TZZB_LEDGERS else None
    return {"net_pct": round(netp, 4), "floor_fill_pct": round(fill / nav, 4), "stance": st, "lean": lean, "expected": exp, "contra": bool(contra and not insens), "insensitive": insens,
            "buy_back": back, "reason": str(c.get("deviation_reason") or "").strip()}


def _consist_log(ctx, ev, verdict):
    try:
        f = PAPER_DATA / "consistency" / f"{ctx.get('date_dash') or datetime.now().strftime('%Y-%m-%d')}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), "skill": SKILL_NAME, "slot": ctx.get("slot"), "sub": bool(ctx.get("sub")),
                                 "verdict": verdict, **ev}, ensure_ascii=False) + "\n")
    except Exception:   # noqa: BLE001
        pass


def consistency_gate(c, ctx):
    if not _flag("CHAIN_CONSISTENCY") or SKILL_NAME == "buchitudou0":
        return None
    snaps, held = ctx.get("snap") or {}, _held_codes(ctx)
    facts = ""
    try:
        facts = (Path(ctx["run_dir"]) / ART["01"]).read_text(encoding="utf-8") if ctx.get("run_dir") else ""
    except (OSError, KeyError):
        pass
    for a in c.get("actions") or []:   # 二B-7 引用核对
        code, nm = str(a.get("code") or ""), str(a.get("name") or "")
        if a.get("op") == "撤单" or not code:
            continue
        sn = snaps.get(code) or {}
        if not sn and code not in held and code not in facts:
            return f"{nm}({code}) 在 01 事实包/候选快照/持仓里都找不到(编造嫌疑), 只许下事实包里出现过的票"
        sname = str(sn.get("name") or "")
        if sname and nm and sname.replace(" ", "") not in nm.replace(" ", "") and nm.replace(" ", "") not in sname.replace(" ", ""):
            return f"{nm}({code}) 名称与快照不符(快照={sname}), 代码和票名要对上"
    ev = consistency_eval(c, ctx)
    need = ev["contra"] or ev["buy_back"]
    ok = (not need) or len(ev["reason"]) >= 8
    verdict = "一致" if not need else ("背离有理由" if ok else "背离缺理由")
    if not ok and not ctx.get("final_attempt"):
        why = ("本单净" + ("卖" if ev["net_pct"] < 0 else "买") + f" {abs(ev['net_pct']):.0%} nav, 与 02 态度/03 倾向(预期{'多' if ev['expected'] > 0 else '空'})相反"
               if ev["contra"] else f"盘中同日先卖后买回 {'、'.join(ev['buy_back'])}")
        return why + "——逆着自己的判断做可以, 但 contract 要写 \"deviation_reason\": \"一句话为什么(≥8 字)\""
    if not ok:
        print(f"WARN: 末次放行 言行背离缺理由 {ev}")
        verdict = "背离缺理由(末次放行)"
    _consist_log(ctx, ev, verdict)
    return None


def _consist_wrap_v06(fn):
    def v06_consist(c, ctx):
        return fn(c, ctx) or consistency_gate(c, ctx)
    v06_consist.__wrapped__ = fn
    return v06_consist


VALIDATORS["06"] = _consist_wrap_v06(VALIDATORS["06"])

class BlindDowngrade(Exception):
    """盲审失败降级信号(10/11): 捕获后不中止链, 照发 06 并标【未过盲审】"""

# ---------- 机械层对接 ----------
def build_facts(date_dash, slot):
    out = PAPER_DATA / "facts" / date_dash / slot / "facts.md"
    if ASOF and out.exists():  # as-of: 编排脚本每日预建一次, 并发链复用(防同目录竞写+东财封 IP)
        return out
    # 10/11 实盘共享: 同日同 slot 的 15 条链只由首个抢到锁的构建, 其余等锁释放后复用(原 15 进程同写一目录+齐打东财)
    out.parent.mkdir(parents=True, exist_ok=True)
    lock, fresh = out.parent / ".build.lock", lambda: out.exists() and time.time() - out.stat().st_mtime < 1200
    if fresh():
        return out
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY); os.close(fd)
    except FileExistsError:
        for _ in range(60):   # 等构建者 ≤10min; 锁残留(构建者崩)则超时后自建
            if not lock.exists() and fresh():
                print(f"facts 复用同 slot 他链构建: {out}")
                return out
            time.sleep(10)
        lock.unlink(missing_ok=True)
        return build_facts(date_dash, slot)
    try:
        r = subprocess.run(["node", "scripts/dfcf/paper/facts.mjs", "--slot", slot, "--date", date_dash],
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        lock.unlink(missing_ok=True)
    if r.returncode != 0:
        sys.exit(f"facts 构建败: {r.stderr[-300:] if r.stderr else r.stdout[-300:]}")
    return out

def load_book(source):
    f = PAPER_DATA / "books" / f"{source}.json"
    if not f.exists():
        sys.exit(f"账本不存在: {f}(先 matcher.mjs --init)")
    for i in range(4):   # 10/17 审计中-6: 撮合正在写盘时可能读到半截 → 等 1 秒重试
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            if i == 3:
                raise
            time.sleep(1)

def book_nav(book):
    """10/11 修: 优先最近一次 EOD 市值 nav(含浮盈亏); 原口径=现金+持仓成本≈恒为初始资金(浮盈亏不进仓位帽/测试下限)。
    无 EOD 记录(新账本首日)才退回成本口径"""
    if book.get("nav"):
        return book["nav"][-1]["nav"]
    return book["cash"] + sum(p["qty"] * p["cost"] for p in book["positions"].values())

def write_paper_state(book, run_dir):
    state = {"source": book["source"], "cash": book["cash"], "nav_est": round(book_nav(book), 2),
             "positions": book["positions"],
             "open_orders": [o for o in book["orders"] if o["status"] == "open"]}
    (run_dir / "paper_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

# ---------- 仓位约束(10/12: 驱动器算好注入 04/05/06, params.yaml 为唯一数字源) ----------
# 原病灶: chain.md 写死"总买仓≥50%"、驱动器按 params 校 40%(土豆 80%)、05 看不到下限只按单票批 2~3 只 → 06 凑不够反复回炉;
# 盘中子链只算本次新买单不算已有持仓 → 已近满仓的刘忆青被判"总买仓 0<40%"逼着再买(10/12 8 次回炉)
def _regime_caps():
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "scripts/dfcf/paper/params.yaml").read_text(encoding="utf-8"))
        return {k: float(v.get("max_total_position", 0)) for k, v in (cfg["stock"].get("regime") or {}).items()}
    except Exception:
        return {}


def watch_snaps(date_dash, slot):
    """持仓估值取数口: 同 slot facts.json 的 watch(facts.mjs 已拉的持仓/挂单快照, 零新请求; 缺=按成本估)"""
    f = PAPER_DATA / "facts" / date_dash / slot / "facts.json"
    try:
        return {w["code"]: w for w in json.loads(f.read_text(encoding="utf-8")).get("watch", []) if w.get("code")}
    except (OSError, ValueError):
        return {}


def _px_of(w):
    return (w or {}).get("last") or (w or {}).get("prevClose")


# ---------- 动态仓位(10/13 用户定: 按各导师真实持仓习惯学单票上限与总仓下限, 见 params.yaml dynamic_position) ----------
DYNAMIC_POS = True    # selftest 关掉(夹具按固定 15%/40% 写)
TZZB_LEDGERS = set(MENTORS.ids("tzzb")) - {"buchitudou0"}   # 10/17 读登记表; 土豆=转债链(固定口径)不在此列


def mentor_pos_params(skill):
    """返回 {cap, floor, src}: 有 tzzb 账本的导师按其最近 window 日真实持仓分位算; 无账本=默认; 土豆/关闭=原固定口径。
    as-of 回放只用回放日之前的记录(防后见之明)"""
    fixed = {"cap": SKILL_CFG[skill]["cap_ratio"],
             "floor": {"tzzb": TEST_FLOOR_TZZB, "like": TEST_FLOOR}.get(SKILL_CFG[skill].get("floor_key"), TEST_FLOOR), "src": "固定口径"}
    try:
        import yaml
        cfg = (yaml.safe_load((ROOT / "scripts/dfcf/paper/params.yaml").read_text(encoding="utf-8")) or {}).get("dynamic_position") or {}
    except Exception:
        cfg = {}
    if not DYNAMIC_POS or not cfg.get("enabled") or skill == "buchitudou0":
        return fixed
    default = {"cap": float(cfg.get("default_cap", 0.25)), "floor": float(cfg.get("default_floor", 0.4)), "src": "默认(无导师账本)"}
    if skill not in TZZB_LEDGERS:
        return default
    f = ROOT / "downloads" / "tzzb" / skill / "day_positions.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    cut = (ASOF or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
    days = sorted(k for k in d if k < cut)[-int(cfg.get("window", 120)):]
    mx, tot = [], []
    for day in days:
        ps = []
        for p in (d[day] or {}).get("list") or []:
            code = str(p.get("code") or p.get("stock_code") or "")
            if code.startswith(("204", "1318")):        # 逆回购不算持仓
                continue
            try:
                v = float(p.get("position_percent"))
            except (TypeError, ValueError):
                continue
            if v > 0:
                ps.append(v)
        tot.append(min(1.0, sum(ps)))
        if ps:
            mx.append(min(1.0, max(ps)))
    if len(days) < 10 or not mx:
        return {**default, "src": f"默认(导师账本仅 {len(days)} 日)"}
    q = lambda a, p: sorted(a)[min(len(a) - 1, int(len(a) * p))]
    r5 = lambda x: round(x * 20) / 20
    cap = max(float(cfg.get("cap_min", 0.25)), min(1.0, r5(q(mx, float(cfg.get("cap_pct", 0.75))))))
    nrec = int(cfg.get("floor_recent_days", 0) or 0)
    if nrec:   # 10/15 晚用户定: 下限跟导师近期实际仓位走(近 N 日收盘总仓中位数 × 系数), 不再用 120 日 P25 固定值
        rec = sorted(tot[-nrec:])
        med = rec[len(rec) // 2] if len(rec) % 2 else (rec[len(rec) // 2 - 1] + rec[len(rec) // 2]) / 2
        floor = min(float(cfg.get("floor_max", 0.8)), r5(med * float(cfg.get("floor_recent_factor", 0.8))))
        fsrc = f"收盘总仓近 {len(rec)} 日中位 {med:.0%}×{cfg.get('floor_recent_factor', 0.8)}"
    else:
        floor = min(float(cfg.get("floor_max", 0.8)), r5(q(tot, float(cfg.get("floor_pct", 0.25)))))
        fsrc = f"收盘总仓 P{int(float(cfg.get('floor_pct', .25)) * 100)}"
    return {"cap": cap, "floor": floor, "src": f"导师真实持仓 {days[0]}~{days[-1]} 共 {len(days)} 日(单票最大仓位 P{int(float(cfg.get('cap_pct', .75)) * 100)}, {fsrc})"}


def soft_floor(pc=None):
    """10/15 晚: 总仓下限软约束(params.yaml dynamic_position.soft_floor); 对照组 control 保持硬约束当基准"""
    if not DYNAMIC_POS:   # selftest 关 DYNAMIC_POS=按硬下限夹具测; 10/16 审计#10: 对照组也用软下限(原硬下限=和导师链口径不一致, 无法归因)
        return False
    if pc and pc.get("ledger_soft_floor"):   # 10/17: 低频导师今天"导师不动闸"关着(不许开新仓)→ 硬下限只能靠加仓已有持仓凑, 退回软约束(见 ledger_prepare)
        return True
    if pc and (pc.get("floor_relax") or {}).get("relaxed"):   # 10/20 用户批: 硬下限导师连续空仓未超真人最长空仓段 → 软约束 + 新开仓须引买规则(v06)
        return True
    if LEDGER and SKILL_NAME in TZZB_LEDGERS:   # 10/16 晚用户: 满仓型导师"每天都有票做" → 收盘总仓中位 ≥80% 的导师在账本约束模式下改硬下限
        try:                                     # (软下限时链只有三到五成仓; 候选池保证凑仓用的是本导师风格的票, 不再拿银行/宽基凑)
            if float((json.loads((ROOT / "scripts" / "tzzb" / "mentor_scope.json").read_text(encoding="utf-8")).get(SKILL_NAME) or {}).get("total_pos_med") or 0) >= 0.8:
                return False
        except (OSError, ValueError, TypeError):
            pass
    try:
        import yaml
        return bool(((yaml.safe_load((ROOT / "scripts/dfcf/paper/params.yaml").read_text(encoding="utf-8")) or {}).get("dynamic_position") or {}).get("soft_floor"))
    except Exception:
        return False


# ---------- 10/16 晚用户定: 盲审 → 拟人审(只审"这张单像不像本导师"; 价格锚/编造价归机械层 v06 理论区间 + anchor 3% 废单 + cancel_below 校验) ----------
MIMIC_REVIEW = True   # 对照组 control 无导师可像, 仍走原盲审


def mimic_on():
    return MIMIC_REVIEW and SKILL_NAME != "control"


def _mimic_board(code, name=""):
    c = str(code)
    if "ST" in str(name).upper():
        return "ST"
    if c.startswith(("688", "689")):
        return "科创板"
    if c.startswith(("300", "301")):
        return "创业板"
    if c.startswith(("4", "8", "92")):
        return "北交所"
    if c.startswith(("11", "12")):
        return "可转债"
    if c.startswith(("5", "15", "16", "18")):
        return "ETF/基金"
    return "沪深主板"


def _mimic_recent(skill, n=5):
    """导师真人近 n 个交易日收盘(as-of 只取回放日之前): [(日, 总仓, 持股只数)]"""
    try:
        d = json.loads((ROOT / "downloads" / "tzzb" / skill / "day_positions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    cut = (ASOF or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
    out = []
    for day in sorted(k for k in d if k < cut)[-n:]:
        ps = []
        for p in (d[day] or {}).get("list") or []:
            if str(p.get("code") or p.get("stock_code") or "").startswith(("204", "1318")):
                continue
            try:
                v = float(p.get("position_percent"))
            except (TypeError, ValueError):
                continue
            if v > 0:
                ps.append(v)
        out.append((day, min(1.0, sum(ps)), len(ps)))
    return out


def mimic_block(ctx):
    """拟人审注入块: 导师真实成交统计(scripts/tzzb/mentor_scope.json + day_positions 近 5 日) + 本单机械统计(驱动器算, 模型不自己换算)。
    失败=只给能给的部分(fail-open, 不中止链)"""
    if not mimic_on():
        return ""
    L = ["\n\n# 驱动器注入: 拟人审对照材料(10/16 晚用户定; 数字全由驱动器机械算)", "", "## 导师真实成交统计"]
    sc = None
    try:
        sc = json.loads((ROOT / "scripts" / "tzzb" / "mentor_scope.json").read_text(encoding="utf-8")).get(SKILL_NAME)
    except (OSError, ValueError):
        pass
    if sc and sc.get("kind") == "no_stat":   # 10/16 晚: mentor_scope 给 B站 UP/土豆 的是占位条目, 不是统计
        sc = None
    if sc:
        pct = lambda m: " / ".join(f"{k} {v:.0%}" for k, v in sorted(m.items(), key=lambda kv: -kv[1]))
        L += [f"- 样本: {sc.get('window', ['?', '?'])[0]}~{sc.get('window', ['?', '?'])[-1]} 共 {sc.get('days')} 个交易日 {sc.get('buys')} 笔买入",
              f"- 买入板块分布: {pct(sc.get('board') or {})}",
              f"- 买入时段分布: {pct(sc.get('buy_time') or {})}",
              f"- 常做行业: {'、'.join(f'{k}({n})' for k, n in (sc.get('industry') or [])[:8])}",
              f"- 常做题材: {'、'.join(f'{k}({n})' for k, n in (sc.get('concept') or [])[:8])}",
              f"- 买得最多的票: {'、'.join(f'{t.get(chr(110) + chr(97) + chr(109) + chr(101))}({t.get(chr(99) + chr(111) + chr(117) + chr(110) + chr(116))})' for t in (sc.get('top') or [])[:10])}",
              f"- 持股天数: 中位 {sc.get('hold_days_med')} 天(默认看几天)" + (f", P75 {sc['hold_days_p75']} 天(拿得住的上限)" if sc.get("hold_days_p75") is not None else ""),
              f"- 持股只数中位 {sc.get('n_hold_med')}; 单票最大仓位中位 {float(sc.get('max_pos_med') or 0):.0%}; 收盘总仓中位 {float(sc.get('total_pos_med') or 0):.0%}"]
        rec = _mimic_recent(SKILL_NAME)
        if rec:
            L.append("- 近 5 日真人收盘: " + "; ".join(f"{d[4:6]}/{d[6:]} 总仓 {t:.0%} {n} 只" for d, t, n in rec))
    else:
        up = None
        if SKILL_NAME in MENTORS.ids("UP"):   # 10/16 晚用户纠正: B站 UP 有核销/画面 BS 点 → md「今日操作」机械统计
            try:
                sys.path.insert(0, str(ROOT / "scripts" / "bilibili"))
                import up_ops_stats
                up = up_ops_stats.up_scope(SKILL_NAME, ASOF)
            except Exception:   # noqa: BLE001
                up = None
        fpm = persona_dir() / "fingerprint.md"
        if up and up.get("ops"):
            pct = lambda m: " / ".join(f"{k} {v:.0%}" for k, v in m.items())
            L += [f"- 来源: {up['source']}; 窗口 {up['window'][0]}~{up['window'][1]} 共 {up['days']} 期视频, 有操作 {up['active_days']} 期, 买 {up['buy']} 笔 / 卖 {up['sell']} 笔, 有操作那天平均 {up['per_active_day']} 笔",
                  f"- 买入板块分布: {pct(up.get('board') or {})}",
                  f"- 买入时段(口述时段词): {pct(up.get('time') or {})}",
                  "- 近 5 期: " + "; ".join(f"{r['date'][5:]} {r['n']} 笔(买 {r['buy']})" for r in up.get("recent5") or [])]
        elif up is not None:
            L.append(f"- {up.get('name')} 近 {up.get('days')} 期视频「今日操作」全为\"无\"(本人不披露买卖): 仓位/持股数/时段三维判\"无据\", 只看能力圈与持有预期是否合画像")
        elif fpm.exists():   # 土豆等: 有账本但不进 mentor_scope(转债 T+0) → 用指纹的打法/盘中节奏
            txt = fpm.read_text(encoding="utf-8")
            L += ["- 来源: 本导师 fingerprint.md(账本逐笔机械统计) 摘录:", txt[:1800]]
        else:
            L.append("- 无真人成交统计: 五维只对照画像核心摘要; 画像没写到的维度判\"无据\"")
    try:
        pack = profile_pack() if SKILL_NAME not in SHARED01_SKIP else None
        if pack and pack.get("summary"):
            L += ["", "## 画像核心摘要(驱动器从 profile.md 摘录; 不必整读 profile.md)", pack["summary"]]
    except Exception:   # noqa: BLE001
        pass
    c06, pc = ctx.get("contracts", {}).get("06") or {}, ctx.get("pc") or {}
    nav = float(pc.get("nav") or ctx.get("nav") or 0)
    snaps, book = ctx.get("snap") or {}, ctx.get("book") or {}
    L += ["", f"## 本单机械统计(slot {ctx.get('slot') or '0915'}; 盘前挂单: 挂价≥现价=开盘成交, 低吸价=盘中回落才成交)"]
    if nav <= 0:
        L.append("- (nav 缺失, 只看 06 原文)")
        return "\n".join(L)
    held_qty = {c: p["qty"] for c, p in (book.get("positions") or {}).items()}
    held_val = dict(pc.get("held") or {})
    tot = sum(held_val.values()) + sum((pc.get("open_buy") or {}).values())
    after = set(held_qty)
    for a in c06.get("actions") or []:
        code, q = str(a.get("code", "")), a.get("qty") or 0
        try:
            px = float(a.get("_px") or a.get("trigger_price"))
        except (TypeError, ValueError):
            px = float((snaps.get(code) or {}).get("prevClose") or 0)
        amt = px * q
        if a.get("op") == "买":
            tot += amt; after.add(code)
            try:
                anc = float(a.get("anchor") or 0)
            except (TypeError, ValueError):
                anc = 0.0
            when = ("" if not (anc > 0 and px > 0) else " | 挂价≥现价锚=开盘即大概率成交" if px >= anc * 0.995
                    else f" | 挂价低于现价锚 {1 - px / anc:.1%}=要等盘中回落才成交(时段不定)")
            L.append(f"- 买 {a.get('name')}({code}) [{_mimic_board(code, a.get('name'))}] {q} 股 ≈ {amt:.0f} 元 = {amt / nav:.0%} nav{when}")
        else:
            tot -= amt
            if q >= held_qty.get(code, 0):
                after.discard(code)
            L.append(f"- 卖 {a.get('name')}({code}) {q} 股" + (" (清仓)" if q >= held_qty.get(code, 0) else ""))
    if not c06.get("actions"):
        L.append(f"- 本单无动作(no_trade={c06.get('no_trade')}, 理由: {str(c06.get('no_trade_reason') or '')[:80]})")
    L.append(f"- 本单全部成交后: 总仓 ≈ {max(0.0, tot) / nav:.0%} nav, 持股 {len(after)} 只(成交前 {len(held_qty)} 只)")
    return "\n".join(L)


def pos_constraints(book, nav, snaps):
    """总仓口径=现有持仓市值+未成交买单+本次买单−本次卖单(10/12 修: 原只算本次买单)。need_n=凑满下限至少要几只买入票
    (单票上限按 0.9 打折: 100 股取整后很难贴满上限)"""
    import math
    mp = mentor_pos_params(SKILL_NAME)
    floor, cap_ratio = mp["floor"], mp["cap"]
    cap = cap_ratio * nav
    held = {c: p["qty"] * (_px_of(snaps.get(c)) or p["cost"]) for c, p in book["positions"].items()}
    open_buy = {}
    for o in book["orders"]:
        if o.get("status") == "open" and o.get("side") == "BUY":
            open_buy[o["code"]] = open_buy.get(o["code"], 0) + o["price"] * o["qty"]
    gap = max(0.0, floor * nav - sum(held.values()) - sum(open_buy.values()))
    need_n = math.ceil(gap / (cap * 0.9)) if gap > 0 and cap > 0 else 0
    return {"floor": floor, "cap_ratio": cap_ratio, "cap": round(cap, 2), "nav": round(nav, 2), "src": mp["src"],
            "cash": round(book["cash"], 2), "held": {c: round(v, 2) for c, v in held.items()},
            "open_buy": {c: round(v, 2) for c, v in open_buy.items()}, "gap": round(gap, 2), "need_n": need_n}


def constraint_text(pc, step):
    """注入 04/05/06 prompt 末尾的约束块(数字全由驱动器算, 模型不再自己换算口径)"""
    h, ob = sum(pc["held"].values()), sum(pc["open_buy"].values())
    lines = [f"\n\n# 驱动器仓位约束(10/13 起按本导师真实持仓习惯动态算: {pc.get('src', 'params.yaml')}; 本链唯一数字口径, 模板/persona/profile 里任何仓位数字与此冲突一律以此为准)",
             f"- nav={pc['nav']:.0f} 元(最近 EOD 市值口径), 现金 {pc['cash']:.0f}",
             f"- 单票上限: 每只买单 qty×挂单价 ≤ {pc['cap']:.0f} 元({pc['cap_ratio']:.0%} nav), 超限=驱动器回炉"]
    if pc.get("base_floor") is not None and pc.get("stance") != "多":
        lines.append(f"- 今日态度(02 判定): {pc['stance']} → 总仓下限按态度调整 {pc['base_floor']:.0%} → {pc['floor']:.0%}(多=原值/中立=减半/空=0)")
    if not pc["floor"]:
        lines.append("- 总仓下限: 无(本导师常空仓收盘或今日态度为空, 可以不买); 不买时 contract 写 no_trade=true + no_trade_reason(一句话), 有把握的进场条件单可以挂也可以不挂(10/16 审计#6: 原\"纯观望=违规\"逼出过度交易)")
    soft = soft_floor(pc)
    if pc["floor"] and soft:   # 10/15 晚用户定: 软下限, 不许拿导师不碰的票凑仓(10/13 大兴"工商银行只在落不到下限时启用"案)
        lines.append(f"- 总仓下限(参考·软约束, 跟导师近期实际仓位走): 现有持仓市值+未成交买单+本次买单−本次卖单 ≈ {pc['floor'] * pc['nav']:.0f} 元"
                     f"({pc['floor']:.0%} nav)。有**符合本导师风格/能力圈**的候选就向它靠; 没有就不凑, 正文写一句原因即可, 驱动器不回炉。"
                     "**禁止**为了凑仓位买本导师平时不碰的票(如银行/宽基 ETF/与其风格无关的防御票)")
    elif pc["floor"]:
        lines.append(f"- 总仓下限(按导师习惯, 防空仓白测): 现有持仓市值+未成交买单+本次买单−本次卖单 ≥ {pc['floor'] * pc['nav']:.0f} 元"
                     f"({pc['floor']:.0%} nav); 下限优先于 regime 总仓上限, 禁止 no_trade 空仓收场")
        if FIX_FLOOR_EXIT:   # 10/14 晚 修①(10/13 大兴/边学: 止损/保护线卖单被下限闸挡住不敢下)
            lines.append("- 下限只约束**主动减仓**: 止损/保护线/失效条件已触发的离场卖单一律放行、不计入上式的\"本次卖单\"——"
                         "这类卖单在 action 里写 \"exit_kind\":\"stop\"(止损)|\"protect\"(保护线/移动止盈)|\"invalid\"(买入逻辑失效), "
                         "只许用于现有持仓; 主动调仓/止盈减仓写 \"discretionary\" 或不写(照旧受下限约束)。离场后仓位跌破下限的缺口留给后续 slot 补, 不许为了守下限放弃止损")
        lines.append(f"- 现状: 持仓市值≈{h:.0f}({len(pc['held'])} 只) + 未成交买单 {ob:.0f} → "
                     + (f"还差 {pc['gap']:.0f} 元, 按单票上限至少需要 {pc['need_n']} 只买入票" if pc["gap"] > 0
                        else "已满足下限, 本次无最低买入要求(卖出后仍须不低于下限)"))
    # 10/14 修(动态仓位回放发现): regime 总仓上限是桃哥规则(A1/A2), 按导师真实持仓定仓位的 tzzb 链不再注入——
    # 否则下限为 0 的链(刘忆青/ST之狼)被"普跌 5%/退潮 15%"压成轻仓, 离真人重仓习惯更远(10/13 回放实证)
    caps = _regime_caps() if SKILL_NAME == "taoge" else {}   # 10/16 审计#11: regime 总仓上限是桃哥规则(A1/A2), 只给桃哥链(原还注入天哥/卢本圆/对照组)
    if caps:
        lines.append("- regime 总仓上限参考(params.yaml): " + " / ".join(f"{k} {v:.0%}" for k, v in caps.items()) + "(低于下限时下限优先)")
    if step == "06" and _flag("CHAIN_CONSISTENCY") and SKILL_NAME != "buchitudou0":   # 10/16 晚 言行一致性(三-3)
        lines.append("- 言行一致: 本单若与 02 态度/03 倾向相反(如判多却净卖 >5% nav、判空却净买 >5% nav), 或盘中卖出后又买回同一只, 可以做, 但 contract 必须写 "
                     "\"deviation_reason\": \"一句话为什么逆着自己的判断(≥8 字)\"; 只许下 01 事实包/候选快照/持仓里出现过的票, 代码和名称要对上")
    if step == "05":   # 10/14 §3-A 第 3 条: 05 对个别票要更严的仓位, 写进 contract, 驱动器在 06 按较小值校验(原只写正文, 06 为凑下限会突破)
        lines.append("- 逐票上限(可选): 某只票你要求比上面单票上限更严的仓位(如 ETF/高位票只给小仓), 就在 verdicts 该票加 \"cap\": <金额元, 正数>; "
                     "驱动器在 06 按 min(单票上限, 你给的 cap) 校验, 06 超了会回炉")
    if pc["need_n"] and soft:
        lines.append(f"- 参考: 按单票上限, 凑到下限约需 {pc['need_n']} 只买入票——只在有本导师风格候选时才凑, 数量不足不回炉")
    elif pc["need_n"]:
        lines.append({"04": f"- 本步: 可买候选(遗留+方向组)至少 {pc['need_n'] + 2} 只, 给 05 否决留余量; 少于 {pc['need_n']} 只=驱动器回炉",
                      "05": f"- 本步: 批准+条件批准 至少 {pc['need_n']} 只, 否则 06 必然凑不满下限; 不够=驱动器在本步当场回炉。"
                            f"有硬伤(否决条款池/选股硬过滤命中)的照旧否决; 仅形态担忧/证据偏弱的改条件批准(用更严的触发价/失效条件控风险)",
                      "06": f"- 本步: 从 05 批准集里至少下 {pc['need_n']} 只买单凑满下限, qty 按上面单票上限金额换算"}.get(step, ""))
    if LEDGER:   # 10/16 晚 三-2: 单票上限按集中度放宽说明 + 交易成本(ledger_prepare 写进 pc; 关=无此键)
        lines += pc.get("ledger_lines") or []
    lines += debate_text(pc, step)   # 10/16 晚 保留分歧版: 无 pc.debate=空列表
    return "\n".join(l for l in lines if l)


# ---------- 10/14 晚 子链五修: 0915 批准名单(⑤) + 修复提示块(①②④⑤holds; 全关=空串) ----------
def _contract_file(f):
    try:
        c, _ = contract_of(Path(f).read_text(encoding="utf-8"))
        return c
    except OSError:
        return None


def sub_allow_list(run_dir, ctx, snaps):
    """子链名单: 0915-05 批准∪条件批准(优先 slots/0915/05_risk.md, 缺=顶层 05) + 持仓 + 未成交挂单。
    names/codes 供 v04 校验, approved 供提示块; 票名从 0915-04 候选/facts 快照补。拿不到 0915-05=None(不设闸)"""
    c05 = _contract_file(run_dir / "slots" / "0915" / ART["05"]) or ctx["contracts"].get("05")
    if not c05 or not c05.get("verdicts"):
        return None
    c04 = _contract_file(run_dir / "slots" / "0915" / ART["04"]) or {}
    code_of = {x.get("name"): str(x.get("code") or "") for x in c04.get("candidates") or []}
    approved = [(v.get("name"), code_of.get(v.get("name"), ""), v.get("result"), str(v.get("reason") or "")[:80])
                for v in c05["verdicts"] if v.get("result") in ("批准", "条件批准")]
    book = ctx.get("book") or {}
    held = list((book.get("positions") or {}).keys())
    opens = [o for o in book.get("orders") or [] if o.get("status") == "open"]
    names = {a[0] for a in approved} | {(snaps.get(c) or {}).get("name") for c in held + [str(o.get("code")) for o in opens]}
    codes = {a[1] for a in approved if a[1]} | set(held) | {str(o.get("code")) for o in opens}
    return {"approved": approved, "held": held, "opens": opens, "names": {n for n in names if n}, "codes": codes}


def fix_block(step, ctx):
    """10/14 晚: 修复提示块(注入 02/04/05/06 末尾)。所有相关开关关=空串(prompt 逐字节不变)"""
    out = []
    if FIX_NO_DEFER and step in ("02", "04", "05", "06"):
        out.append("- paper 模拟链**没有用户**: 不许把任何决定交给用户/待用户裁/留给用户确认(contract 里出现这类字样=驱动器回炉)。"
                   "规则内拿不准的, 自己按更保守的一侧裁决并写明理由")
    allow = ctx.get("sub_allow") if ctx.get("sub") else None
    if FIX_SUB_APPROVED and allow and step in ("04", "06"):
        sn = ctx.get("snap_names") or {}
        out.append("- **子链名单(硬约束, 子链没有 05 风控)**: 候选/终裁标的只能来自 ① 0915 盘前 05 批准∪条件批准名单 ② 现有持仓 ③ 未成交挂单; "
                   "名单外新票本 slot 不许进候选(驱动器校验, 违者回炉)。")
        out.append("  - 0915-05 批准名单: " + ("; ".join(f"{n}{'(' + c + ')' if c else ''}[{r}]{(' ' + why) if why else ''}" for n, c, r, why in allow["approved"]) or "(空)"))
        out.append("  - 现有持仓: " + (", ".join(f"{c} {sn.get(c, '')}".strip() for c in allow["held"]) or "无"))
        out.append("  - 未成交挂单: " + ("; ".join(f"{o.get('id')} {o.get('side')} {o.get('code')} {sn.get(str(o.get('code')), '')} {o.get('qty')}@{o.get('price')}"
                                                for o in allow["opens"]) or "无"))
    if step == "06" and FIX_HOLDS:
        out.append("- contract 新增可选字段: actions 为空(本次不新挂不撤)时**必须二选一**给出 "
                   "\"holds\":[{\"order_id\":\"挂单号\"或\"code\":\"6位代码\",\"why\":\"为何维持\"}](列出本次维持的挂单/持仓) "
                   "或 \"no_trade_reason\":\"一句话为何不动\"; 两者都缺=驱动器回炉")
    if step == "06" and ctx.get("sub") and FIX_ESC_RERUN:
        out.append("- 若你判断市况已变到盘前 03/05 框架失效、本子链无法在当前框架内正确决策, 在 contract 加 \"escalate\":true"
                   "(驱动器会在本 slot 带'市况已重判'提示把 02→04→06 重跑一次); 能在现有框架内处理的不要 escalate")
    if ctx.get("esc_note") and step in ("02", "04", "05", "06"):
        out.append(ctx["esc_note"])
    return ("\n\n# 驱动器补充约束(10/14 晚 子链修复)\n" + "\n".join(out)) if out else ""


# ---------- 10/16 晚 TODO 三-2 + A2①③: 账本统计硬约束 / 本导师候选池 / 统计基线建议(开关 CHAIN_LEDGER_CONSTRAINTS; 关=以下全不生效) ----------
# 参数全由 scripts/dfcf/paper/ledger_limits.py 从真人账本机械算(近 60 个记录日 P80, as-of 只用链日之前); B站 UP/对照组无账本=跳过; 土豆有账本(持股只数维度跳过)
# 06 硬约束(持股只数/本日新开仓/近 5 日换手/低频导师"导师不动链也不动")超了回炉, 末次放行记 PAPER_DATA/ledger/<日>.jsonl; 0915 首笔(先小仓试错型)软约束回炉一次
# 04 候选池(指纹池 Top-N + 联动扩展; 池外预算=ceil(越池比例×候选数)≥1; 指纹不清晰=只用打法约束); 02/04/06 注入 baseline_suggestion; 06 可选 override → PAPER_DATA/overrides/<日>.jsonl
LEDGER_NO = set(MENTORS.ids("UP", "对照"))   # 10/17 读登记表


def _ll():
    d = str(Path(__file__).resolve().parents[1] / "dfcf" / "paper")
    if d not in sys.path:
        sys.path.insert(0, d)
    import ledger_limits
    return ledger_limits


def ledger_prepare(ctx, run_dir, slot, sub, dry=False):
    """链起跑时(pos_constraints 之后)算本导师账本约束/基线/候选池 → ctx["ledger"]; 恒满仓单票型放宽 pc 单票上限; 成本行进 pc["ledger_lines"]。
    盘前 0915 全链: pools/model_out 当日产物缺就现场生成(超时 fail-open)。任何异常=本链不启用(fail-open)"""
    if not LEDGER or SKILL_NAME in LEDGER_NO:
        return
    try:
        import math
        ll, dd = _ll(), ctx["date_dash"]
        if not sub and not dry:
            if SKILL_NAME in TZZB_LEDGERS and not ll.ensure_artifact("pool", dd, timeout=300):
                print(f"WARN: 指纹池 pools/{dd}.json 生成失败, 本链不注入候选池(fail-open)")
            if not ll.ensure_artifact("model", dd, timeout=300):
                print(f"WARN: 统计基线 model_out/{dd}.json 生成失败, 本链不注入基线建议(fail-open)")
        lim = ll.ledger_limits(SKILL_NAME, dd)
        base = ll.baseline_of(SKILL_NAME, dd)
        held = list(((ctx.get("book") or {}).get("positions") or {}).keys())
        view = ll.pool_view(SKILL_NAME, dd, held) if SKILL_NAME in TZZB_LEDGERS else None
        pc = ctx["pc"]
        lines = []
        if lim and lim.get("max_pos_med"):   # 10/18 SIZE_RULES: 真人单票最大仓位中位 → v06 新开仓最小金额
            pc["single_med"] = float(lim["max_pos_med"])
            if SIZE_RULES and pc["single_med"] > 0:
                trial = lim.get("first_frac") is not None and not sub and str(slot) == "0915"
                mn = SIZE_MIN_FRAC * pc["single_med"] * pc["nav"]
                if lim.get("turnover_max"):
                    mn = min(mn, 0.9 * float(lim["turnover_max"]) * pc["nav"])
                lines.append(("- 新开仓大小: 本导师习惯开盘先小仓试错, 0915 首笔按下面「0915 首笔」上限即可; 盘中子链确认方向后加仓到导师习惯的单票仓位"
                              if trial else
                              f"- 新开仓大小(驱动器硬约束): 每只新开仓买单至少 ≈{mn:.0f} 元(本导师真人单票最大仓位中位 {pc['single_med']:.0%} 的 75%; 现金不够按现金)。"
                              "导师是集中下注的——少挑几只、每只下够, 不要拆成很多小单")
                             + "; 买单失效线(cancel_below)离挂价至少半个日振幅, 太近的驱动器会自动放宽")
        if lim and lim.get("conc") and lim.get("cap_single") and lim["cap_single"] > pc["cap_ratio"]:   # 恒满仓单票型: 放宽到真实水平(只放宽不收紧)
            old = pc["cap_ratio"]
            pc["cap_ratio"], pc["cap"] = lim["cap_single"], round(lim["cap_single"] * pc["nav"], 2)
            pc["need_n"] = math.ceil(pc["gap"] / (pc["cap"] * 0.9)) if pc["gap"] > 0 and pc["cap"] > 0 else 0
            lines.append(f"- 单票上限按本导师集中度放宽 {old:.0%} → {pc['cap_ratio']:.0%} nav(恒满仓单票型: 真人单票最大仓位中位 {float(lim.get('max_pos_med') or 0):.0%}, "
                         f"近 {lim['n_days']} 个交易日 P80 {lim['cap_single']:.0%}); 有把握的票按真人习惯重仓一只即可, 不必为分散拆成多只")
        lines.append(ll.fee_line(pc["nav"], pc["cap"]))
        # 10/17 沙盒验证发现(星见野 10/16): 低频导师今天"导师不动闸"关着(不许开新仓)时, 满仓型硬下限只能靠加仓已有持仓凑——
        #   已有持仓若是导师不碰的票(该链遗留的中国银行), 06 被逼把 66% nav 压进去, 拟人审三轮驳回、不可达。闸关着的日子下限退回软约束
        if ll.gate_state(lim, base, _chain_tp(pc)) == "拦" and pc.get("floor"):   # 10/18: 追仓豁免时闸开着, 下限照旧硬
            pc["ledger_soft_floor"] = True
            lines.append("- 今天导师不动闸关着(不许开新仓) → 总仓下限按软约束执行: 不许为凑仓位加仓本导师不碰的已有持仓, 凑不满写一句原因即可")
        floor_relax_prepare(pc, ctx, lines, ll)
        pc["ledger_lines"] = lines
        ctx["ledger"] = {"lim": lim, "base": base, "view": view, "slot": slot}
        _write_lf(run_dir / "ledger.json", json.dumps({"slot": slot, "lim": lim, "base": base,
                                                       "pool": {k: v for k, v in (view or {}).items() if k not in ("text", "names")}},
                                                      ensure_ascii=False, indent=1, default=list))
        print(f"账本约束: {ll.limits_text(lim)} | 基线: {'有' if base else '无'} | 候选池: "
              + ("无" if not view else ("指纹池+打法" if view["use_pool"] else "仅打法")))
    except Exception as e:  # noqa: BLE001
        print(f"WARN: 账本约束准备失败, 本链不启用(fail-open): {e}")
        ctx["ledger"] = None


FLOOR_RELAX = _flag("CHAIN_FLOOR_RELAX")   # 10/20 用户批: 硬下限收窄(见 floor_relax_prepare / floor_rule_check)
_NOT_MET = re.compile(r"不满足|不成立|未满足|没满足|不引用|不作为.{0,4}依据")


def floor_relax_prepare(pc, ctx, lines, ll):
    """10/20 用户批(A658 正强案: 06 自认"R10/R7 不满足, 只靠 R5 恒满仓 + 下限"满仓买进 -1608):
    硬下限导师(软约束之外)链连续空仓天数 < 真人近 120 记录日最长空仓段 → 今天下限按软约束, 且新开仓买单必须引一条方向=买、情境成立的规则;
    连续空仓 ≥ 真人最长段 → 恢复硬下限(不加规则闸)。结果写 pc["floor_relax"] 供 soft_floor / v06 读"""
    if not FLOOR_RELAX or SKILL_NAME not in TZZB_LEDGERS or not pc.get("floor") or soft_floor(pc):
        return
    try:
        mx = ll.real_empty_spell_max(SKILL_NAME, ctx["date_dash"])
        n = ll.chain_empty_days(ctx.get("book") or {}, ctx["date_dash"])
    except Exception as e:  # noqa: BLE001
        print(f"WARN: 下限收窄取数失败, 按原硬下限(fail-closed 到旧行为): {e}")
        return
    if mx is None:
        return
    relaxed = n < mx
    pc["floor_relax"] = {"relaxed": relaxed, "chain_empty": n, "real_max": mx}
    if relaxed:
        lines.append(f"- 总仓下限今天按软约束(10/20 收窄): 本链已连续空仓 {n} 天 < 真人近 120 个记录日最长空仓 {mx} 天。新开仓买单必须在 rules 里引**至少一条方向=买、"
                     f"且今天情境成立**的入场规则(仓位类规则如\"恒满仓\"只能定大小, 不能单独当买入理由); 没有合格买点就不买, 写一句原因(no_trade 或 holds)")
    else:
        lines.append(f"- 总仓下限今天按硬约束: 本链已连续空仓 {n} 天, 达到真人近 120 个记录日最长空仓 {mx} 天, 不能再空着(按本导师习惯挑票补仓)")
    print(f"下限收窄: 链连续空仓 {n} 天 / 真人最长 {mx} 天 → {'软约束+买规则闸' if relaxed else '恢复硬下限'}")


def floor_rule_check(a, ctx, held_codes):
    """v06 用: floor_relax 生效时, 新开仓买单须引方向=买(rule_tags)且 ctx 未自认情境不满足的规则; 不合格=回炉文案, 合格/不适用=None"""
    fr = (ctx.get("pc") or {}).get("floor_relax") or {}
    if not fr.get("relaxed") or a.get("op") != "买" or str(a.get("code")) in held_codes:
        return None
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "dfcf" / "paper"))
        import rule_tags as _RT
        tags = (_RT.load(SKILL_NAME) or {}).get("rules") or {}
    except Exception as e:  # noqa: BLE001
        print(f"WARN: rule_tags 读取失败, 买规则闸不生效(fail-open): {e}")
        return None
    if not tags:
        return None
    cited = [r if isinstance(r, dict) else {"id": str(r)} for r in (a.get("rules") or [])]
    ok = [r["id"] for r in cited if (tags.get(str(r.get("id"))) or {}).get("dir") == "买" and not _NOT_MET.search(str(r.get("ctx") or ""))]
    if ok:
        return None
    if ctx.get("final_attempt"):   # 同其他软闸: 末次放行记日志(不因此中止链/丢全部单)
        print(f"WARN: 买规则闸末次放行: {a.get('name')} 仍未引方向=买且情境成立的规则(引了 {[r.get('id') for r in cited]})")
        return None
    buy_ids = [k for k, v in tags.items() if v.get("dir") == "买" and not v.get("struck")]
    got = "、".join(f"{r.get('id')}={(tags.get(str(r.get('id'))) or {}).get('dir') or '未标'}" for r in cited) or "无"
    return (f"{a.get('name')} 新开仓没有引用方向=买且情境成立的入场规则(引了: {got}); 本链连续空仓 {fr['chain_empty']} 天 < 真人最长空仓 {fr['real_max']} 天, "
            f"今天不必凑下限——要么引一条今天情境成立的买规则({'、'.join(buy_ids[:12])}), 要么删掉这张买单(没别的动作就写 no_trade=true + no_trade_reason)")


def _chain_tp(pc):
    """10/18 追仓豁免用: 链此刻总仓占 nav(持仓市值 + 未成交买单, 取自 pos_constraints); 拿不到=None(闸按旧口径)"""
    try:
        nav = float((pc or {}).get("nav") or 0)
        return (sum((pc.get("held") or {}).values()) + sum((pc.get("open_buy") or {}).values())) / nav if nav > 0 else None
    except (TypeError, ValueError, AttributeError):
        return None


def ledger_block(step, ctx):
    """02/04/06 prompt 末尾: 统计硬约束摘要(04/06) + 统计基线建议(02/04/06) + 本导师候选池(04)。关/无数据=空串"""
    lg = ctx.get("ledger") if LEDGER else None
    if not lg or step not in ("02", "04", "06"):
        return ""
    try:
        ll = _ll()
        L = ["\n\n# 驱动器注入: 账本统计约束 + 统计基线建议(10/16 晚 TODO 三-2; 数字全由驱动器从真人账本机械算, 模型不必自己换算)"]
        lim = lg.get("lim")
        if lim and step in ("04", "06"):
            nav = float((ctx.get("pc") or {}).get("nav") or ctx.get("nav") or 0) or 1.0
            st = ll.chain_state(ctx.get("book") or {}, ctx["date_dash"])
            w = lim.get("window") or ["?", "?"]
            L.append(f"- 真人近 {lim['n_days']} 个交易日({w[0]}~{w[1]})统计约束(驱动器在 06 校验, 超了退回重写, 末次放行记日志): {ll.limits_text(lim)}"
                     + (f"; 跳过: {'; '.join(lim['skip'])}" if lim.get("skip") else ""))
            L.append(f"- 本链此刻: 持股 {len(st['pos'])} 只 + 未成交买单 {len(st['open_buy'])} 只; 今日已新开仓 {len(st['new_done'])} 只; "
                     f"近 5 日(含今日)已成交买入 {st['buy5']:.0f} 元 = {st['buy5'] / nav:.0%} nav")
            b = lg.get("base")
            if lim.get("low_freq"):
                g = ll.gate_state(lim, b, _chain_tp(ctx.get("pc")))
                if g == "fail-open":
                    L.append(f"- 导师不动链也不动: 本导师出手日只占 {lim['trade_ratio']:.0%}(低频); 今天基线缺失/滞后, 本闸不生效")
                elif g == "追仓":
                    L.append(f"- 导师不动链也不动: 本导师低频、今天基线不出手, 但本链此刻总仓 {_chain_tp(ctx.get('pc')):.0%} 比导师真人昨收 "
                             f"{min(float((b.get('state') or {}).get('tp_prev') or 0), 1.0):.0%} 低 ≥{ll.CATCHUP_GAP:.0%} → **追仓豁免: 今天可以开新仓**, "
                             "按导师习惯集中补到他的仓位水平(导师不动=他满仓拿着不动, 不是让链空仓不动)")
                elif g == "拦":
                    L.append(f"- **导师不动链也不动**: 本导师出手日只占 {lim['trade_ratio']:.0%}(低频), 统计基线今天出手概率 {float(b['p_trade']):.0%} < {ll.GATE_P:.0%} "
                             "→ 今天**不许开新仓**(新票买单=驱动器回炉), 只做持仓处置: 卖/撤/持有/已有持仓加减")
                else:
                    L.append(f"- 导师不动链也不动: 本导师低频, 但统计基线今天出手概率 {float(b['p_trade']):.0%} ≥ {ll.GATE_P:.0%} → 今天可以开新仓")
            if lim.get("first_frac") is not None and lg.get("slot") == "0915" and not ctx.get("sub"):
                L.append(f"- 0915 首笔: 本导师「先小仓试错」成立(竞价/开盘先小仓, 方向对了盘中再加), 新票首笔金额 ≤ {lim['first_frac']:.1%} nav ≈ {lim['first_frac'] * nav:.0f} 元"
                         "(1 手不受限; 超了回炉一次)")
        if lg.get("base"):
            L.append(ll.baseline_text(lg["base"], step))
        if step == "04" and lg.get("view"):
            L.append(lg["view"]["text"])
        return "\n".join(L) if len(L) > 1 else ""
    except Exception as e:  # noqa: BLE001
        print(f"WARN: 账本约束注入失败(本步不注入): {e}")
        return ""


def _ledger_log(kind, ctx, rec):
    try:
        lg = ctx.get("ledger") or {}
        _ll().log_jsonl(PAPER_DATA / kind, ctx["date_dash"], {"ts": datetime.now().isoformat(timespec="seconds"), "skill": SKILL_NAME,
                                                              "slot": lg.get("slot"), "sub": bool(ctx.get("sub")), **rec})
    except Exception:   # noqa: BLE001
        pass


def _ledger_v04(c, ctx):
    lg = ctx.get("ledger") if LEDGER else None
    if not lg or not lg.get("view"):
        return None
    book = ctx.get("book") or {}
    exempt = set(book.get("positions") or {}) | {str(o.get("code")) for o in book.get("orders") or [] if o.get("status") == "open"}
    hard, soft, S = _ll().check_04(lg["view"], c.get("candidates") or [], exempt)
    if hard and not ctx.get("final_attempt"):
        return "本导师候选池约束: " + hard
    if soft and not _soft_once(ctx, "ledger04"):
        return "本导师候选池约束: " + soft
    if hard or soft:
        print(f"WARN: 04 候选池约束末次放行: {hard or soft}")
    _ledger_log("ledger", ctx, {"step": "04", "verdict": "末次放行" if hard else "通过", "hard": hard, "soft": soft, "stat": S})
    return None


def _ledger_v06(c, ctx):
    lg = ctx.get("ledger") if LEDGER else None
    if not lg:
        return None
    ll = _ll()
    acts = c.get("actions") or []
    ov, oerr = ll.norm_override(c.get("override"))
    if oerr:
        if not _soft_once(ctx, "ledger_ov"):
            return oerr
        print(f"WARN: 06 override 格式仍不对, 放行不记: {oerr}")
        ov = None
    st = ll.chain_state(ctx.get("book") or {}, ctx["date_dash"])
    nav = float((ctx.get("pc") or {}).get("nav") or ctx.get("nav") or 0)
    hard, soft, S = ll.check_06(lg.get("lim"), st, acts, nav, lg.get("base"), lg.get("slot") or "0915", bool(ctx.get("sub")), chain_tp=_chain_tp(ctx.get("pc")))
    if hard and not ctx.get("final_attempt"):
        return "账本统计硬约束: " + " | ".join(hard)
    if soft and not _soft_once(ctx, "ledger_first"):
        return "账本统计软约束: " + " | ".join(soft)
    verdict = ("硬约束末次放行" if hard else "通过") + ("+软约束放行" if soft else "")
    if hard or soft:
        print(f"WARN: 06 账本约束{verdict}: {hard + soft}")
    _ledger_log("ledger", ctx, {"step": "06", "verdict": verdict, "hard": hard, "soft": soft, "stat": S})
    b = lg.get("base")
    if b:   # override 记账(收盘统计胜负的原料): 基线 vs 本单 + 声明的 override + 未声明的偏离层
        cv = ll.chain_view(acts, st, nav)
        lay = {x["layer"] for x in ov or []}
        und = [k for k, dev in (("L1", bool(b.get("trade")) != cv["trade"]), ("L2", cv["trade"] and b.get("dir") not in (None, cv["dir"]))) if dev and k not in lay]
        _ledger_log("overrides", ctx, {"baseline": {k: b.get(k) for k in ("trade", "dir", "tp_target", "n_new", "p_trade")}, "chain": cv,
                                       "override": ov or [], "undeclared": und})
    return None


def _ledger_wrap(fn, step):
    chk = _ledger_v04 if step == "04" else _ledger_v06

    def v_ledger(c, ctx):
        return fn(c, ctx) or chk(c, ctx)
    v_ledger.__wrapped__ = fn
    return v_ledger


VALIDATORS["04"] = _ledger_wrap(VALIDATORS["04"], "04")
VALIDATORS["06"] = _ledger_wrap(VALIDATORS["06"], "06")

# ---------- 10/17 ② 决策质量新功能(机械层 scripts/dfcf/paper/quality_hooks.py + price_rules/slot_profile/t_profile/similar_days/override_stats/rule_tags) ----------
# 开关见 QF(chain_flags.txt, 全部默认 0); 全关=不 import、prompt/校验/plans 逐字节旧行为(selftest _selftest_quality 覆盖); 任何异常 fail-open
def _qh():
    d = str(Path(__file__).resolve().parents[1] / "dfcf" / "paper")
    if d not in sys.path:
        sys.path.insert(0, d)
    import quality_hooks
    return quality_hooks


def quality_block(step, ctx):
    """02/04/06 prompt 末尾: 相似市况/出手时段/T 法/挂价规则价表/锁层/规则方向 提示; 全关=空串"""
    if not any(QF.values()):
        return ""
    try:
        return _qh().block(step, ctx, QF)
    except Exception as e:  # noqa: BLE001
        print(f"WARN: 决策质量注入失败(本步不注入): {e}")
        return ""


def _quality_wrap(fn):
    def v_quality(c, ctx):
        if not any(QF.values()):
            return fn(c, ctx)
        try:
            q = _qh()
        except Exception as e:  # noqa: BLE001
            print(f"WARN: quality_hooks 载入失败(本次不生效): {e}")
            return fn(c, ctx)
        return q.wrap06(fn, QF)(c, ctx)
    v_quality.__wrapped__ = fn
    return v_quality


if any(QF.values()):
    VALIDATORS["06"] = _quality_wrap(VALIDATORS["06"])



# ---------- 10/14 晚 零 token 触发闸 A(CHAIN_SUBCHAIN_GATE): 子链开跑前机械判断要不要跑 ----------
GATE_DEFAULT = {"price_move_pct": 1.5, "amp_half_factor": 0.5, "amp_window": 30, "index_move_pt": 0.8,
                "force_slots": ["1000", "1455"], "esc_rerun_max_elapsed_s": 900}
GATE_IDX = ("sh000001", "sz399006")
_MINUTE_CACHE = {}


def gate_cfg():
    try:
        import yaml
        cfg = (yaml.safe_load((ROOT / "scripts/dfcf/paper/params.yaml").read_text(encoding="utf-8")) or {}).get("subchain_gate") or {}
    except Exception:
        cfg = {}
    out = {**GATE_DEFAULT, **cfg}
    out["force_slots"] = [str(s) for s in out["force_slots"]]
    return out


def _sym(code):
    code = str(code)
    if code in GATE_IDX:
        return code
    return ("sh" if re.match(r"^(60|68|11[0138]|5)", code) else "bj" if re.match(r"^(8|4|920)", code) else "sz") + code


def _minute_px(date_dash, slot, syms):
    """as-of/历史回算取数: downloads/market/<日>/kline_minute.jsonl(收盘后采集) 中 bar_time ≤ slot 的最近一根收盘价; slot=0915 取前一交易日末根"""
    mdir = ROOT / "downloads" / "market"
    if slot <= "0925":
        days = sorted(d.name for d in mdir.iterdir() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name) and d.name < date_dash
                      and (d / "kline_minute.jsonl").exists())
        if not days:
            return {}
        date_dash, slot = days[-1], "1500"
    key = date_dash
    if key not in _MINUTE_CACHE:
        rows = {}
        f = mdir / date_dash / "kline_minute.jsonl"
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                rows.setdefault(r["symbol"], []).append((r["barTime"][11:16].replace(":", ""), r["close"]))
        _MINUTE_CACHE[key] = rows
    out = {}
    for s in syms:
        bars = [px for t, px in _MINUTE_CACHE[key].get(s, []) if t <= slot]
        if bars:
            out[s] = bars[-1]
    return out


def _tencent_batch(syms):
    """实盘取数: 腾讯 qt 一次请求批量(含指数); 返回 {sym: (last, prevClose)}; 失败=空(调用方 fail-open)"""
    import urllib.request
    try:
        req = urllib.request.Request("https://qt.gtimg.cn/q=" + ",".join(syms), headers={"Referer": "https://gu.qq.com/"})
        raw = urllib.request.urlopen(req, timeout=8).read().decode("gbk", errors="replace")
    except Exception as e:  # noqa: BLE001
        print(f"WARN: 触发闸腾讯批量取数失败: {e}")
        return {}
    out = {}
    for m in re.finditer(r'v_(\w+)="([^"]*)"', raw):
        f = m.group(2).split("~")
        try:
            if len(f) > 4 and float(f[3]) > 0:
                out[m.group(1)] = (float(f[3]), float(f[4]))
        except ValueError:
            pass
    return out


def _amp_median(code, date_dash, window):
    """近 window 个交易日(链日之前)日振幅中位数 %; 无日线=None"""
    try:
        k = [x for x in json.loads((ROOT / "downloads/quotes/daily" / f"{code}.json").read_text(encoding="utf-8"))["klines"] if x["d"] < date_dash]
    except (OSError, ValueError, KeyError):
        return None
    amps = [(b["h"] - b["l"]) / a["c"] * 100 for a, b in zip(k[-window - 1:-1], k[-window:]) if a.get("c")]
    if len(amps) < 5:
        return None
    amps.sort()
    return amps[len(amps) // 2]


def _last_ran(run_dir, slot):
    """本 run_dir 中 slot 之前最近一次真跑(非 dry/非闸跳过)的 (slot, ts 本地时间)"""
    best = None
    try:
        lines = (run_dir / "run_meta.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        s = str(r.get("slot"))
        if not re.fullmatch(r"\d{4}", s) or s >= slot or r.get("dry") or r.get("skipped"):
            continue
        if best is None or (s, r.get("ts", "")) > best:
            best = (s, r.get("ts", ""))
    return best


def _ledger_events(book, since_local, until_local=None):
    """账本事件日志里 since 之后由撮合产生的事件(成交/止损/失效撤单/拒买/废单…); 链自己的 挂单/CXL/EOD 不算; 撤单工具单的自失效不算"""
    orders = {o.get("id"): o for o in book.get("orders") or []}
    out = []
    for e in book.get("chain") or []:
        try:
            at = datetime.fromisoformat(str(e["at"]).replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
        except (KeyError, ValueError):
            continue
        why = str(e.get("why", ""))
        if at <= since_local or (until_local and at > until_local) or why.startswith(("挂单", "CXL", "EOD")):
            continue
        oid = why.split()[-1] if why.split() else ""
        o = orders.get(oid) or {}
        cb = (o.get("cond") or {}).get("cancel_below")
        if why.startswith("失效撤单") and o.get("side") == "BUY" and cb and cb > o.get("price", 0):
            continue   # 自撤式工具单(cancel_below>挂价, 首快照即失效)=链的撤单手段, 不是市场事件
        out.append(f"{at:%H:%M} {why[:60]}")
    return out


def _dir_tokens(directions):
    toks = set()
    for d in directions or []:
        for t in re.split(r"[/／、,，()（）\[\]【】\s·+|\-—:：;；]+", str(d)):
            t = re.sub(r"(热点中|衰减中|新启动|节外|方向|板块|概念|防御兜底|兜底|主线|支线|迁移|启动)$", "", t.strip())
            if len(t) >= 2 and not re.fullmatch(r"[\d.%]+", t):
                toks.add(t)
    return toks


def _telegraphs(paper_data, date_dash, last, slot):
    """(last, slot] 之间各 slot facts.md「新到电报」节的条目(各 slot 包只含上一包以来的电报, 并起来=自上一已跑 slot 以来全部)"""
    d = paper_data / "facts" / date_dash
    items = []
    for s in sorted(p.name for p in d.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}", p.name) and last < p.name <= slot) if d.is_dir() else []:
        try:
            t = (d / s / "facts.md").read_text(encoding="utf-8")
        except OSError:
            continue
        sec = t.split("## 新到电报", 1)[1].split("\n## ", 1)[0] if "## 新到电报" in t else ""
        items += [l.strip() for l in sec.splitlines() if l.strip().startswith("- [")]
    return items


def _slot_share(slot):
    """导师真人成交落在该 slot 窗口(到下一 slot)的占比(scripts/dfcf/paper/slot_activity.json, 由 fills_rt 统计); 无数据=None"""
    try:
        return (json.loads((ROOT / "scripts" / "dfcf" / "paper" / "slot_activity.json").read_text(encoding="utf-8")).get(SKILL_NAME) or {}).get(slot)
    except (OSError, ValueError):
        return None


def gate_decide(run_dir, date_dash, slot, book, open_orders=None, positions=None, paper_data=None, minute_src=None, now_px=None, until=None):
    """返回 (run: bool, reasons[list], metrics{dict}, gate_json{dict})。纯机械零 token, 任何取数失败都按"照跑"(fail-open)。
    book=当前账本(含 chain 事件日志); positions/open_orders 缺省取 book; minute_src=True 走分钟线(as-of/回算), 缺省 as-of 即分钟线、实盘走腾讯批量"""
    cfg = gate_cfg()
    paper_data = paper_data or PAPER_DATA
    minute_src = bool(ASOF) if minute_src is None else minute_src
    positions = book.get("positions") or {} if positions is None else positions
    open_orders = [o for o in book.get("orders") or [] if o.get("status") == "open"] if open_orders is None else open_orders
    reasons, metrics = [], {"slot": slot}
    gj = {"slot": slot, "ts": datetime.now().isoformat(timespec="seconds"), "prices": {}, "idx": {}}
    last = _last_ran(run_dir, slot)
    metrics["last_ran"] = last[0] if last else None
    # e 强制 slot
    if slot in cfg["force_slots"]:
        share = _slot_share(slot)   # 10/16 晚 A13③: 导师真人在这个时段窗口的成交占比 < min_force_share → 不强制跑(价格异动等触发照常)
        if share is None or share >= float(cfg.get("min_force_share", 0.05)):
            reasons.append(f"e 强制 slot {slot}")
        else:
            metrics["force_skipped"] = f"导师该时段成交占比 {share:.0%} < {float(cfg.get('min_force_share', 0.05)):.0%}"
    if not last:
        reasons.append("无上一已跑 slot(fail-open)")
    elif not (run_dir / "slots" / last[0] / ART["06"]).exists():
        reasons.append(f"上一已跑 slot {last[0]} 没出 06(中止/升级), 照跑")
    # 关注票: 持仓+挂单+0915 候选
    c04 = _contract_file(run_dir / "slots" / "0915" / ART["04"]) or {}
    cand = {str(x.get("code")): x.get("name") for x in c04.get("candidates") or [] if re.fullmatch(r"\d{6}", str(x.get("code") or ""))}
    codes = set(positions) | {str(o.get("code")) for o in open_orders} | set(cand)
    try:
        watch = {w["code"]: w for w in json.loads((paper_data / "facts" / date_dash / slot / "facts.json").read_text(encoding="utf-8")).get("watch", [])}
    except (OSError, ValueError):
        watch = {}
    names = {c: (watch.get(c) or {}).get("name") or cand.get(c) for c in codes}
    cur = {c: (watch.get(c) or {}).get("last") for c in codes if (watch.get(c) or {}).get("last")}
    need = [c for c in codes if c not in cur] + list(GATE_IDX)
    if now_px is not None:
        fetched = now_px
    elif minute_src:
        fetched = {s: (px, None) for s, px in _minute_px(date_dash, slot, [_sym(c) for c in need]).items()}
    else:   # 实盘: 同 slot 15 链共享一个报价缓存(只补缺的票, 抖动 0~3s 防同时打腾讯)
        cache_f = paper_data / "facts" / date_dash / slot / "gate_quotes.json"
        cache = _contract_file_json(cache_f) or {}
        fetched = {k: tuple(v) for k, v in (cache.get("q") or {}).items()} if time.time() - float(cache.get("t", 0)) < 300 else {}
        miss = [_sym(c) for c in need if _sym(c) not in fetched and not re.match(r"^(8|4|920)", c)]
        if miss:
            import random
            time.sleep(random.uniform(0, 3))
            fetched.update(_tencent_batch(miss))
            try:
                cache_f.parent.mkdir(parents=True, exist_ok=True)
                cache_f.write_text(json.dumps({"t": time.time(), "q": fetched}, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
    for c in need:
        v = fetched.get(_sym(c))
        if v and c not in GATE_IDX:
            cur[c] = v[0]
    idx_now = {i: fetched[i][0] for i in GATE_IDX if fetched.get(i)}
    gj["prices"], gj["idx"] = cur, idx_now
    if not last:
        return True, reasons, metrics, gj
    # 基线: 上一已跑 slot 的 gate.json; 缺=该 slot facts.json watch + 0915 cand_snap(盘前=前收) / 分钟线
    base = _contract_file_json(run_dir / "slots" / last[0] / "gate.json")
    bpx, bidx = dict((base or {}).get("prices") or {}), dict((base or {}).get("idx") or {})
    if not base:
        try:
            bpx.update({w["code"]: w["last"] for w in json.loads((paper_data / "facts" / date_dash / last[0] / "facts.json").read_text(encoding="utf-8")).get("watch", []) if w.get("last")})
        except (OSError, ValueError):
            pass
        try:
            for s in json.loads((run_dir / "slots" / last[0] / "cand_snap.json").read_text(encoding="utf-8")).get("snaps", []):
                if s.get("code") and (s.get("last") or s.get("prevClose")) and s["code"] not in bpx:
                    bpx[s["code"]] = s.get("last") or s.get("prevClose")
        except (OSError, ValueError):
            pass
        if minute_src:
            miss = [c for c in codes if c not in bpx] + list(GATE_IDX)
            mp = _minute_px(date_dash, last[0], [_sym(c) for c in miss])
            bpx.update({c: mp[_sym(c)] for c in miss if c not in GATE_IDX and _sym(c) in mp})
            bidx.update({i: mp[i] for i in GATE_IDX if i in mp})
        elif last[0] <= "0925":   # 盘前已跑: 指数基线=前收(实盘批量取数第二字段)
            bidx.update({i: fetched[i][1] for i in GATE_IDX if fetched.get(i) and fetched[i][1]})
    # a 账本事件
    try:
        since = datetime.fromisoformat(last[1])
        ev = _ledger_events(book, since, until)   # until=历史回算用(实盘 None)
    except ValueError:
        ev = ["上一 slot 时间戳坏(fail-open)"]
    metrics["ledger_events"] = ev
    if ev:
        reasons.append(f"a 账本事件 {len(ev)} 条: {'; '.join(ev[:3])}")
    # b 价格
    moves = {}
    for c in sorted(codes):
        if c not in cur:
            continue   # 当前取不到价=数据问题, 不因此触发(北交所/停牌)
        if not bpx.get(c):
            reasons.append(f"b {c}{names.get(c) or ''} 无基线价(fail-open)")
            continue
        mv = (cur[c] / bpx[c] - 1) * 100
        if abs(mv) > 2 * limit_of(c) + 1:   # 超两个板限=数据错(除权/分钟线串号), 记入 metrics 不触发
            moves[c] = (round(mv, 2), None)
            continue
        amp = _amp_median(c, date_dash, int(cfg["amp_window"]))
        th = min(float(cfg["price_move_pct"]), amp * float(cfg["amp_half_factor"])) if amp else float(cfg["price_move_pct"])
        moves[c] = (round(mv, 2), round(th, 2))
        if abs(mv) >= th:
            reasons.append(f"b {c}{names.get(c) or ''} {mv:+.2f}% ≥ {th:.2f}%")
    metrics["moves"] = moves
    # c 指数
    for i in GATE_IDX:
        if i in idx_now and bidx.get(i):
            d = (idx_now[i] / bidx[i] - 1) * 100
            metrics[f"idx_{i}"] = round(d, 2)
            if abs(d) >= float(cfg["index_move_pt"]):
                reasons.append(f"c {'上证' if i == 'sh000001' else '创业板'} {d:+.2f}pt ≥ {cfg['index_move_pt']}")
        else:
            reasons.append(f"c {i} 取数缺失(fail-open)")
    # d 电报
    c02 = _contract_file(run_dir / ART["02"]) or {}
    kws = {n for n in names.values() if n and len(n) >= 2} | set(codes) | _dir_tokens(c02.get("directions"))
    tg = _telegraphs(paper_data, date_dash, last[0], slot)
    hits = [(t[:50], sorted(k for k in kws if k in t)) for t in tg]
    hits = [h for h in hits if h[1]]
    metrics["telegraph"] = {"n": len(tg), "hits": hits[:5]}
    if hits:
        reasons.append(f"d 电报命中 {len(hits)} 条: {hits[0][1][:3]} ← {hits[0][0]}")
    # f 开盘实况市况结论变了(10/20 晚用户批: open_live.py 09:31~10:30 机械判定; 上一已跑 slot 时刻的结论 vs 现在)
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "market"))
        import open_live as _OL
        t0 = datetime.fromisoformat(last[1]).strftime("%H%M")
        now_hm = until.strftime("%H%M") if hasattr(until, "strftime") else (slot if ASOF else datetime.now().strftime("%H%M"))
        a0, a1 = _OL.label_at(date_dash, t0), _OL.label_at(date_dash, str(now_hm))
        metrics["open_live"] = {"last": a0, "now": a1}
        if a1 and (a0 or {}).get("label") != a1["label"] and not (a0 is None and a1["label"] == "震荡"):
            reasons.append(f"f 开盘实况市况 {(a0 or {}).get('label') or '无'} → {a1['label']}({a1['t'][:2]}:{a1['t'][2:]} 判定, 打分 {a1['score']:+d})")
    except Exception as e:  # noqa: BLE001  取数失败不触发(f 是加触发条件, 不是 fail-open 照跑)
        metrics["open_live"] = f"取数失败: {e}"
    return bool(reasons), reasons, metrics, gj


def _contract_file_json(f):
    try:
        return json.loads(Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_gate_skip(run_dir, date, date_dash, slot, book, last, metrics):
    """闸跳过产物: 顶层 06_verdict.md(哨兵/contract 同 06 契约, actions 空 + holds/no_trade_reason + gate_skipped), 下游 ingest/report/settle 零改动可读"""
    prev06 = _contract_file(run_dir / "slots" / str(last) / ART["06"]) or _contract_file(run_dir / ART["06"]) or {}   # 上一真跑 slot 的 06(连续跳过也不套娃)
    opens = [o for o in book.get("orders") or [] if o.get("status") == "open"]
    holds = [{"order_id": o.get("id"), "code": o.get("code"), "why": "触发闸跳过: 自上一已跑 slot 无新触发, 原挂单维持"} for o in opens]
    reason = (f"零 token 触发闸: 自上一已跑 slot {last} 以来无新成交/挂单失效, 持仓/挂单/0915 候选与上证/创业板波动未达阈值, "
              f"无命中加红电报, 本 slot 非强制 slot")
    c = {"supersedes": f"维持 {last} slot 06 全部决策(触发闸跳过, 未调用模型)", "actions": [], "no_trade": False,
         "holds": holds, "no_trade_reason": reason, "gate_skipped": True}
    mv = metrics.get("moves") or {}
    body = [f"# 06 终裁 · {SKILL_NAME} · {date_dash} {slot}(零 token 触发闸跳过)", "",
            f"> {reason}。本文件由驱动器机械生成(CHAIN_SUBCHAIN_GATE), 未调用模型; 顶层 02/04 仍是 slot {last} 的版本。", "",
            "## 闸判据", f"- 账本事件: {len(metrics.get('ledger_events') or [])} 条",
            "- 价格变动(相对 slot " + str(last) + ", 实际%/阈值%): " + (", ".join(f"{k} {v[0]:+.2f}/" + (f"{v[1]:.2f}" if v[1] is not None else "数据异常不计") for k, v in mv.items()) or "无关注票"),
            f"- 指数: 上证 {metrics.get('idx_sh000001')}pt / 创业板 {metrics.get('idx_sz399006')}pt",
            f"- 电报: 新到 {(metrics.get('telegraph') or {}).get('n', 0)} 条, 命中 0", "",
            f"## 维持的上一已跑 slot({last}) 06 contract 原文", "```json", json.dumps(prev06, ensure_ascii=False), "```", "",
            "```contract", json.dumps(c, ensure_ascii=False), "```", f"STEP_OK 06 {date}", ""]
    _write_lf(run_dir / ART["06"], "\n".join(body))
    return c


# ---------- 10/14 晚 子链合并 D(CHAIN_SUBCHAIN_MERGE): 02/04/06 一次调用三块产物, 分块校验, 坏块 --resume 只重写那块 ----------
MERGE_HEAD = ("# 盘中子链合并调用(驱动器 CHAIN_SUBCHAIN_MERGE): 本次在**一个会话**里依次完成下面几个任务(02 分析 → 04 交易方案 → 05 风控 → 06 终裁; 10/16 起子链含 05)。\n"
              "- 严格按顺序: 先完成任务一并写入 02_analysis.md, 再做后面的任务(每一步以你刚写的上游产物为准; 05 审 04 的全部候选: 已持仓/未成交挂单可按 0915 口径快速复核, 本时段新增的票要认真审)。\n"
              "- 每个文件各自独立完整: 各自正文 + 末个 ```contract 块 + 末行哨兵(STEP_OK <步> {date}), 不许写\"见上文/同上\"。\n"
              "- {run_dir}/cand_snap.md 已由驱动器在本次调用前按 持仓/未成交挂单/0915 候选 拉好(06 的价格锚用它); 04 新增代码的锚以 facts.txt 快照为准(10/16 起子链不设名单闸, 本导师能力圈内可选新票)。\n"
              "- 写完后驱动器逐块机械校验, 哪块不过会在本会话里让你只重写那一块。\n")


def merge_prompt(parts, date, run_dir):
    head = MERGE_HEAD.replace("{date}", date).replace("{run_dir}", str(run_dir).replace("\\", "/"))
    seg = [head]
    for i, (step, p) in enumerate(parts, 1):
        seg.append(f"\n\n==================== 任务{'一二三四'[i - 1]}: 决策链 {step} ====================\n\n{p}")
    return "".join(seg)


def presnap_codes(run_dir, ctx):
    allow = ctx.get("sub_allow") or {}
    c04 = _contract_file(run_dir / "slots" / "0915" / ART["04"]) or {}
    codes = set(allow.get("codes") or []) | {str(x.get("code")) for x in c04.get("candidates") or []}
    codes |= set(((ctx.get("book") or {}).get("positions") or {}))
    return sorted(c for c in codes if re.fullmatch(r"\d{6}", c))

# ---------- claude -p 调用 + token 台账 ----------
# 10/11 修 429 误判: 原对 stdout+stderr 全文搜 "429" → 模型正文里的金额(如 42976)命中 → 整链白等 45min
# (10/9 taoge 0915 链 197min 元凶之一)。现仅在调用失败(非 0 退出或 JSON is_error)时, 查 stderr+错误正文, 且 429 须为独立数字
WINDOW_RE = re.compile(r"usage limit|5-hour limit|rate.?limit|\b429\b|quota exceeded|overloaded", re.I)
WINDOW_DEFER_S = 2700                                           # 顺延 45min(10/4 用户: 顺延不跳过)
# 10/11 全局并发闸: 跨进程最多 N 个 claude -p 同时跑(9:15 曾 14 链齐发, 额度窗口被瞬间打满); 槽=文件锁, 持有进程死亡即回收
# 10/12 用户令: 每条链各自串行=一条车道, 15 条链(14 skill+对照)同时各占一条 → 默认 15(6 时 9 条链排队, 0915 拖 2h+)
# 切回订阅制时 15 并发吃不消: 改 scripts/claude_profile/max_concurrency.txt 一个数字即可(下次链运行生效, 不用重启应用); 环境变量优先
def _max_concurrency():
    if os.environ.get("CLAUDE_MAX_CONCURRENCY"):
        return int(os.environ["CLAUDE_MAX_CONCURRENCY"])
    f = Path(__file__).resolve().parents[1] / "claude_profile" / "max_concurrency.txt"
    try:
        v = f.read_text(encoding="utf-8").split()[0]
        if v.lower() == "auto":   # 10/17 晚用户定: 车道数 = 链数(一条链同一时刻最多占 1 条车道 → 永不排队)
            sys.path.insert(0, str(ROOT / "scripts" / "lib"))
            import mentors as _M   # noqa: PLC0415
            return max(1, len(_M.ids()))
        return max(1, int(v))
    except (OSError, ValueError, IndexError, ImportError):
        return 15


MAX_CLAUDE = _max_concurrency()
SLOT_DIR = Path(__file__).resolve().parent / ".claude_slots"

def _claude_json(stdout):
    """10/11: claude -p 经网关时会在 JSON 前打印提示横幅(如 auto mode 计费说明), 只取最后一个 JSON 对象行"""
    for line in reversed((stdout or "").strip().splitlines()):
        if line.lstrip().startswith("{"):
            return json.loads(line)
    return json.loads(stdout or "")


# ---------- 10/13 工具调用留痕(CHAIN_TRACE_TOOLS=1, 默认关; 回放打开, 实盘先不开) ----------
# 开启时 claude -p 改 --output-format stream-json --verbose, 每步的工具调用(Read/Grep 了哪些文件/行)落 run_dir/tool_calls/<step>.jsonl,
# 用于统计"06 引用了规则编号却没捞过原文"的比例、验证 F(画像节到底被读了没有)。结果/usage 解析两种输出格式都兼容
TRACE_TOOLS = _flag("CHAIN_TRACE_TOOLS")
_SLIM_KEYS = ("content", "new_string", "old_string")   # 写入类工具的大段正文只记长度
# 10/14 §3-A 第 6 条 决策日志+延迟结算+反思回注(默认关; 关=驱动器行为逐字节不变): CHAIN_REFLECTION=1 且 skill ∈ CHAIN_REFLECTION_SKILLS
# (逗号白名单, '*'=全部, 缺省/空=无) 时: 06 出单后每个 action 落 decisions/<skill>.jsonl; 04/06 prompt 末尾注入本链已结算反思。
# 结算/反思由 scripts/dfcf/paper/settle_decisions.py 收盘后跑; 读写逻辑在 scripts/dfcf/paper/decision_memory.py(仅开启时懒加载)
REFLECT = _flag("CHAIN_REFLECTION")
DECISION_LOG = _flag("CHAIN_DECISION_LOG")   # 10/19 晚: 决策日志 + 延迟结算对全链开(零 token), 和反思回注(花 token、改 prompt)分开
# 10/16 晚 TODO 二B-6 反思回注 FinCon 式触发(CHAIN_REFLECT_TRIGGER, 默认关; 关=逐字节旧行为): 收盘后 scripts/dfcf/paper/reflect_trigger.py --date D
# 机械判"拟人偏差连续 N 日同维度偏离导师真人 / 账户回撤超阈"(阈值 params.yaml reflection_trigger) → reflection/<D>.json;
# 开启时 04/06 prompt 末尾(紧随已结算反思块)注入"运行日之前最近一份"里本链的 inject 原文(只含执行参数 + ≤3 条 07 case, 不改画像/规则); 本链未触发=不注入
REFLECT_TRIGGER = _flag("CHAIN_REFLECT_TRIGGER")
REFLECT_TRIGGER_DIR = Path(__file__).resolve().parents[1] / "dfcf" / "paper" / "reflection"   # 固定真目录(同 _dm; 自测改指临时目录)


def _claude_result(stdout):
    """stream-json(多行事件, 取末个 type=result) 与 json(单个结果对象) 通吃; 无 JSON=抛 JSONDecodeError(与 _claude_json 同口径)"""
    objs = []
    for line in (stdout or "").splitlines():
        s = line.strip()
        if s.startswith("{"):
            try:
                objs.append(json.loads(s))
            except json.JSONDecodeError:
                pass
    for o in reversed(objs):
        if o.get("type") == "result":
            return o
    if objs:
        return objs[-1]
    raise json.JSONDecodeError("stdout 无 JSON 对象", stdout or "", 0)


def _dump_tool_calls(stdout, trace):
    """stream-json 事件 → tool_calls jsonl: 每个 tool_use 一行(含工具结果是否报错) + 一行 result 汇总(含 is_error/末段报错文本, 便于查'会话没写产物')"""
    path, meta = trace
    try:
        recs, by_id = [], {}
        for line in (stdout or "").splitlines():
            s = line.strip()
            if not s.startswith("{"):
                continue
            try:
                o = json.loads(s)
            except json.JSONDecodeError:
                continue
            content = ((o.get("message") or {}).get("content") or []) if isinstance(o.get("message"), dict) else []
            if o.get("type") == "assistant":
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        inp = {k: (f"<{len(str(v))} chars>" if k in _SLIM_KEYS else v) for k, v in (c.get("input") or {}).items()}
                        rec = {**meta, "tool": c.get("name"), "input": inp, "error": False}
                        by_id[c.get("id")] = rec
                        recs.append(rec)
            elif o.get("type") == "user":
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("is_error") and c.get("tool_use_id") in by_id:
                        by_id[c["tool_use_id"]]["error"] = True
            elif o.get("type") == "result":
                recs.append({**meta, "type": "result", "is_error": o.get("is_error"), "subtype": o.get("subtype"),
                             "num_turns": o.get("num_turns"), "usage": o.get("usage"), "cost": o.get("total_cost_usd"),
                             "result_tail": str(o.get("result", ""))[-300:] if o.get("is_error") else ""})
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001  留痕失败不影响链
        print(f"WARN: 工具调用留痕失败: {e}")


def _acquire_slot():
    import psutil
    SLOT_DIR.mkdir(exist_ok=True)
    waited = 0
    while True:
        for i in range(MAX_CLAUDE):
            f = SLOT_DIR / f"slot_{i}.lock"
            try:
                fd = os.open(str(f), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode()); os.close(fd)
                if waited:
                    print(f"并发闸: 等待 {waited}s 后取得槽 {i}")
                return f
            except FileExistsError:
                try:
                    if not psutil.pid_exists(int(f.read_text() or 0)):
                        f.unlink(missing_ok=True)   # 持有者已死=回收, 下一轮重抢
                except (ValueError, OSError):
                    pass
        time.sleep(10); waited += 10

LAST_SESSION = {"id": ""}   # 10/14 晚 子链合并 D: 最近一次 claude -p 的 session_id(--resume 用); 其余调用方不读


def call_claude(prompt, trace=None, resume=None, fork=False):
    """10/7 晚修正(用户令: 模仿 k3 cruise_loop 语义): window 错误=顺延不跳过——
    无限顺延(每次 45min)直到窗口重置, 不设次数上限, 欠账永远留账不丢。
    10/11: 本机有 scripts/claude_profile/rotation.txt 时多 key 轮换——撞窗先切下一套立即重试, 全部耗尽才顺延
    10/13: trace=(jsonl 路径, 元信息) 且 CHAIN_TRACE_TOOLS=1 时走 stream-json 并落工具调用; 否则与原来完全相同"""
    traced = bool(TRACE_TOOLS and trace)
    prompt = _persona_redirect(prompt)
    cmd = ([CLAUDE[0], "-p", "--verbose"] + ["stream-json" if x == "json" else x for x in CLAUDE[2:]]) if traced else CLAUDE
    if resume:   # 10/14 晚 D: 同会话续写(只重写坏块); resume=None 时命令行与原来完全相同
        cmd = cmd + ["--resume", resume] + (["--fork-session"] if fork else [])   # 10/14 夜 A6: fork=从共享开头会话分叉(原会话不动)
    # 10/18 自动记忆开关(默认 0=现状): 开=子进程注入 CLAUDE_CODE_DISABLE_AUTO_MEMORY=1
    # 10/18 01:10 修致命 bug: 原来 env=memenv 只传这一个变量(关时甚至传空 dict)= 子进程环境被清空(没有 PATH/USERPROFILE/认证) → 所有调用秒败 rc=1;
    #   必须在宿主环境上叠加; 关时传 None = 继承宿主环境(与改造前逐字节一致)
    memenv = {**os.environ, "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"} if NO_AUTOMEMORY else None
    parse = _claude_result if traced else _claude_json
    n400 = 0   # 10/16 用户立法: API 400 同一请求重试 3 次, 3 次都 400 → 切 gravitex key 再试一次(rotation.on_api400)
    while True:
        slot = _acquire_slot()
        t0 = time.time()
        try:
            rotation.log_use(f"chain:{SKILL_NAME}")
            r = None
            for _try in range(6):   # 10/17: claude 程序自更新那几秒 exe 不在/不完整(WinError 2 / 216) → 等几秒重试, 不让整条链崩(A4 沙盒实测 4 条链被打断)
                try:
                    r = subprocess.run(cmd + rotation.settings_args(), input=prompt, cwd=ROOT, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=1800, env=memenv, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    break
                except OSError as oe:
                    if getattr(oe, "winerror", None) not in (2, 216, 32, 5) and not isinstance(oe, FileNotFoundError):
                        raise
                    print(f"WARN: 启动 claude 失败({oe}), 可能正在自动更新, {10 * (_try + 1)}s 后重试 {_try + 1}/6")
                    time.sleep(10 * (_try + 1))
            if r is None:
                r = subprocess.CompletedProcess(cmd, -1, "", "claude 程序 6 次启动都失败(自动更新中?)")
        except subprocess.TimeoutExpired:   # 原未捕获=整链崩溃; 现记失败交给回炉
            r = subprocess.CompletedProcess(cmd, -1, "", "claude -p 超时 1800s")
        finally:
            slot.unlink(missing_ok=True)
        dur = time.time() - t0
        if traced:
            _dump_tool_calls(r.stdout, trace)
        is_err = r.returncode != 0
        try:
            j = parse(r.stdout)
            is_err = is_err or bool(j.get("is_error"))
            err_text = (r.stderr or "") + (str(j.get("result", "")) if j.get("is_error") else "")
        except json.JSONDecodeError:
            err_text = (r.stderr or "") + (r.stdout or "")[-500:]
        if is_err and rotation.is_api400(err_text):
            n400 += 1
            if n400 < 3:
                time.sleep(5); continue
            if n400 == 3 and rotation.on_api400(f"chain:{SKILL_NAME}"):
                continue
        if is_err and WINDOW_RE.search(err_text):
            if rotation.on_window_limit():
                continue
            print(f"⚠ API window 限: 顺延 {WINDOW_DEFER_S // 60}min 后重试(欠账留账不跳过, k3 语义; manual-switch 模式下会先等你手动切, 返回后检查你切了没再决定顺延): {err_text[-120:]}")
            time.sleep(WINDOW_DEFER_S)
            continue
        break
    usage, cost = {}, ""
    LAST_SESSION["id"] = ""
    try:
        j = parse(r.stdout)
        usage = j.get("usage", {})
        cost = j.get("total_cost_usd", "")
        LAST_SESSION["id"] = j.get("session_id", "") or ""
    except json.JSONDecodeError:
        pass  # stdout 非 JSON=claude 层故障, 哨兵校验会抓到
    return r.returncode, usage, cost, dur

def log_tokens(date, slot, step, attempt, usage, cost, dur):
    """10/12: 末尾追加 skill/缓存读/缓存写/asof 四列(原 8 列不动, scorecard.mjs 按位置读不受影响);
    10/12 前的旧行只有 8 列。网关下 input_tokens 只剩个位数, 真实输入量在 cache_create/cache_read"""
    new = not TOKEN_LOG.exists()
    with TOKEN_LOG.open("a", encoding="utf-8") as f:
        if new:
            f.write("date,slot,step,attempt,in_tokens,out_tokens,cost_usd,duration_s,skill,cache_read,cache_create,asof\n")
        f.write(f"{date},{slot},{step},{attempt},{usage.get('input_tokens', '')},"
                f"{usage.get('output_tokens', '')},{cost},{dur:.0f},{SKILL_NAME},"
                f"{usage.get('cache_read_input_tokens', '')},{usage.get('cache_creation_input_tokens', '')},{1 if ASOF else 0}\n")


def log_retry(run_dir, date, slot, step, attempt, reason):
    """10/12: 回炉原因 → run_dir/retry_log.jsonl + 全局 scripts/dfcf/paper/retry_log.jsonl(按 skill 汇总统计用) + stdout"""
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "skill": SKILL_NAME, "date": date, "slot": slot,
           "step": step, "attempt": attempt, "reason": str(reason)[:500], "asof": bool(ASOF)}  # 10/12: 回放行可滤
    print(f"step {step} 回炉 {attempt}/{MAX_RETRY} 原因: {rec['reason'][:200]}", flush=True)
    for f in (Path(run_dir) / "retry_log.jsonl", PAPER / "retry_log.jsonl"):
        try:
            with f.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

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
                        "--json", str(js), "--md", str(md)] + (["--asof", ASOF] if ASOF else []),
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode == 2:
        print(f"WARN: 候选票快照源全灭, 06 价格锚校验降级: {(r.stdout or r.stderr or '')[-150:]}")
    snaps = {}
    if js.exists():
        try:
            snaps = {s["code"]: s for s in json.loads(js.read_text(encoding="utf-8"))["snaps"] if not s.get("error")}
        except (json.JSONDecodeError, KeyError):
            print("WARN: cand_snap.json 解析败, 验价降级")
    print(f"cand_snap: {len(snaps)}/{len(codes)} 票有价格锚 → {md.name}")
    if not ASOF and md.exists():   # 10/20 晚 想法 B(用户批: 只给信息不设闸): 每只候选附一句 3 秒盘口分时(as-of 回放不加, 防看到未来)
        try:
            sys.path.insert(0, str(ROOT / "scripts" / "lib"))
            import ctx_index as _CI
            dd = datetime.now().strftime("%Y-%m-%d")
            lines = [f"- {c}: {_CI.tape_l0(c, dd)[1]}" for c in codes]
            with md.open("a", encoding="utf-8") as fh:
                fh.write("\n\n## 分时一句话(3 秒盘口, 截至此刻; 不在采集名单的票写\"无\")\n" + "\n".join(lines) + "\n")
        except Exception as e:  # noqa: BLE001
            print(f"WARN: cand_snap 分时一句话失败(不影响链): {e}")
    return snaps

def emit_plans(date_dash, slot, source, contract, book, blind_note=""):
    acts = contract.get("actions") or []
    if not acts:
        print("06 无 actions(条件单在 no_trade 契约内或纯空仓), 不写 plans")
        return
    hm = f"{slot[:2]}:{slot[2:]}"
    # 10/16: 本次有显式撤单的票不再发同票自动 CXL(自动 CXL 不分买卖, 会误撤另一方向的单; 同向旧单由 matcher import 防重闸取代)
    cxl_codes = {a["_cxl"]["code"] for a in acts if a.get("op") == "撤单" and a.get("_cxl")}
    open_by_code = {}
    for o in book["orders"]:
        if o["status"] == "open":
            open_by_code.setdefault(o["code"], o)
    plans_dir = PAPER_DATA / "plans"
    plans_dir.mkdir(exist_ok=True)
    f = plans_dir / f"{date_dash}_{source}.md"
    # 10/9 修双成交案: 同 slot 回炉重 emit 时, 先删本 slot 旧行再 append(废版 plans 不得残留;
    # 行首 "- HH:MM |" 的 HH:MM=slot 标识)。matcher import 侧另有防重 CXL 闸双保险
    if f.exists():
        old = [l for l in f.read_text(encoding="utf-8").splitlines() if not l.startswith(f"- {hm} |")]
        f.write_text("\n".join(old) + ("\n" if old else ""), encoding="utf-8")
    lines = []
    for a in acts:
        if a.get("op") == "撤单":   # 10/16 新动词: 指定挂单号撤单(v06 已按账本解析; 解析不到=不落行)
            tg = a.get("_cxl")
            if tg:
                why = re.sub(r"\s+", " ", str(a.get("why") or "")).strip()[:80]
                lines.append(f"- {hm} | {source} | CXL | {tg['code']} | - | - | - | - | oid={tg['id']} | 撤单(slot {slot} 终裁)" + (f": {why}" if why else ""))
            continue
        side = "BUY" if a["op"] == "买" else "SELL"
        code = str(a["code"])
        if code in open_by_code and code not in cxl_codes:  # 版本链: 新单+CXL 旧单, 禁覆盖
            lines.append(f"- {hm} | {source} | CXL | {code} | - | - | - | - | 取代旧单(slot {slot} 终裁)")
        px = a.get("_px") or float(a.get("trigger_price"))  # v06 已回填求值结果(公式价代换后数值)
        conds = []
        if a.get("cancel_below"):  # C7-②: 失效条件结构化(matcher 哨兵执行, 不再只是 note 文字)
            conds.append(f"cancel_below={float(a['cancel_below']):g}")
        if a.get("stop_below"):
            conds.append(f"stop_below={float(a['stop_below']):g}")
        if a.get("op") == "开盘卖":   # 10/16 新动词: 市价卖, 挂价列=anchor 仅参考(matcher 按开盘/现价成交, 不吃笼子)
            conds.append("open_sell=1")
        if a.get("_t0"):              # 10/18 竞价T: matcher 竞价按开盘价买 + 开盘后首个价卖
            conds.append("t0_open_exit=1")
        if a.get("_nb"):            # 10/16 新字段: 此刻前不撮合
            conds.append(f"not_before={a['_nb'].replace(':', '')}")
        if a.get("op") == "买" and isinstance(a.get("chase_cap"), (int, float)) and a["chase_cap"] >= px:   # 10/20 晚 ②: 追价上限(matcher 按它判作废、改单不越过)
            conds.append(f"chase_cap={float(a['chase_cap']):g}")
        if any(QF.values()):        # 10/17 ② 2b: 规则低吸单的改单生命周期(matcher cond reprice=N); 全关=不加
            conds += _qh().plan_conds(a, QF)
        note = blind_note + (f"链终裁: 开盘卖(市价, 挂价列=锚{px:g}仅参考)" if a.get("op") == "开盘卖"
                             else (f"链终裁: 竞价T(竞价买上限{px:g}, 开盘即卖)" if a.get("_t0") else f"链终裁: 触发{px:g}" + (f"(公式 {a['_formula']})" if a.get("_formula") else "")))
        if _rush(date_dash, slot, LATE_ORDER_AT):   # 10/15 截止闸: 09:25 后才出的 0915 单=开盘后才挂上, 不是竞价单
            note = f"【迟到单 {datetime.now():%H:%M} 导入·非竞价】" + note
        if any(QF.values()):        # 10/17 ② 2b: note 记挂法
            note += _qh().plan_note(a, QF)
        if a.get("invalid_if"):
            note += f" 失效:{a['invalid_if']}"
        # plans 行第 8/9 字段=结构化 anchor+cond(matcher 锚偏离守卫+失效哨兵的取数口; v06 已保证 anchor 数值)
        anchor_s = f"{float(a['anchor']):g}" if a.get("anchor") is not None else "-"
        lines.append(f"- {hm} | {source} | {side} | {code} | {px:g} | {a['qty']} | day | {anchor_s} | {';'.join(conds) or '-'} | {note}")
    if not lines:   # 10/16: 只有解析不到目标的撤单时无行可落
        print("06 actions 只有无目标撤单, 不写 plans")
        return
    with f.open("a", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")
    print(f"plans 落 {len(lines)} 行 → {f}")
    # 机械衔接: 立即喂账本(import 行级哈希幂等, 重复喂=跳过; 盘中 MatchHandler 只跑 --once 不碰 import)
    r = subprocess.run(["node", "scripts/dfcf/paper/matcher.mjs", "--import", str(f)],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    tail = (r.stdout or "").strip().splitlines()
    print(f"matcher --import: {tail[-1] if tail else r.stderr[-200:]}")
    if r.returncode != 0:
        print("WARN: import 有坏行, plans 已落盘待人工看(链不中止)")

def late_news_block(step, run_dir, date_dash, slot):
    """10/16 用户令: 发哥有时早盘不发文、有时晚发, 不再提醒; 0915 链已开跑后才入库的发哥推演要点, 作为"晚到资讯"增量注入
    02~06(只在实盘当日 0915 链, 且建 facts 时发哥缺席才注入; 其余情况空串)。发哥定位=主观判断层/刹车参考"""
    if ASOF or slot != "0915" or step not in ("02", "03b", "03s", "03j", "04", "05", "06"):
        return ""
    spec = ROOT / "downloads" / "wechat" / "fage" / date_dash / "spec.md"
    try:
        facts = (run_dir / "facts.txt").read_text(encoding="utf-8")
        if not spec.exists() or "【推演要点】" in facts.split("### 红旗大街发哥", 1)[-1][:3000]:
            return ""
        lines = [l for l in spec.read_text(encoding="utf-8").splitlines() if l.startswith("【推演要点】")]
    except OSError:
        return ""
    if not lines:
        return ""
    return ("\n\n# 晚到资讯(驱动器增量注入: 本链建 facts 时发哥推演尚未入库, 现已入库)\n"
            "红旗大街发哥当日盘前推演要点(主观判断层; 定位=刹车参考——他喊回避/不追高时权重高, 点位力度类只作背景; 与本导师风格无关可不采纳):\n"
            + "\n".join(lines[:8]))


def slim_facts(f):
    """10/16 审计#5/#7: 共享 facts 原样保留(用户定资讯包全员同一份), 但每条导师链的 facts.txt 副本里
    ①「昨日账本状态」只留本链账本行(原全员持仓都可见, 10/14 曾 12 条链同下 002436)
    ②「导师信号速览」只留本导师小节 + 发哥(原全员规则都给, 还要逐个回应=串味)。对照组/转债链不动"""
    if SKILL_NAME in ("control", "buchitudou0"):
        return
    try:
        t = f.read_text(encoding="utf-8")
    except OSError:
        return
    src, kw = SKILL["source"], MENTOR_HEAD.get(SKILL_NAME)

    def section(text, head):
        i = text.find(head)
        if i < 0:
            return None
        j = i + len(head)
        while True:   # 账本状态节里每本账的行也是 "## A-xxx:", 节尾=下一个不是账本行的 "## "
            j = text.find("\n## ", j)
            if j < 0:
                return i, len(text)
            if not re.match(r"\n## [ABC]-", text[j:j + 8]):
                return i, j
            j += 4
    s1 = section(t, "## 昨日账本状态")
    if s1:
        body = t[s1[0]:s1[1]].split("\n")
        keep = [l for l in body if not re.match(r"## [ABC]-", l) or l.startswith(f"## {src}:")]
        t = t[:s1[0]] + "\n".join(keep) + t[s1[1]:]
    s2 = section(t, "## 导师信号速览")
    if s2 and kw:
        parts = t[s2[0]:s2[1]].split("\n### ")
        keep = [x for x in parts[1:] if x.startswith(kw) or x.startswith("发哥")]
        t = t[:s2[0]] + parts[0] + "".join("\n### " + x for x in keep) + "\n(其余导师的规则不在本链范围, 已省略)" + t[s2[1]:]
    f.write_text(t, encoding="utf-8")


def neg_warn() -> str:
    """负例警示卡随机 2 条(TODO §1.3 的 05 消费钩子, 10/8 夜)。
    negstats.md(gen_tzzb_negstats.py 产出)缺失/坏=空串, fail-open 零影响链。"""
    import random
    if SKILL_NAME in TZZB_LEDGERS:   # 10/16 审计#9: 负例卡(连亏不断仓/仓位无上限)与满仓扛单型导师风格相反, 推着链短拿快砍; tzzb 导师链不注入
        return ""
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

def reject_rules() -> str:
    """否决条款池全量注入(10/9 用户令: hermes 错题泛化; fail-open 同 neg_warn)。"""
    f = ROOT / "skills" / "tzzb-skill" / "references" / "reject_rules.md"
    try:
        text = f.read_text(encoding="utf-8")
        rows = [l for l in text.splitlines() if l.startswith("| RJ")]
        if not rows:
            return ""
        return ("\n\n# 否决条款池(形态级, 仅当证据满足才可用作否决依据; 仓位类永不在此):\n"
                + "\n".join(rows))
    except Exception:
        return ""

# ---------- 01 共享(10/12): 同 date/slot 的股票链共用一次市场摘要, 各链机械追加本链账户+导师信号(零 token) ----------
# 依据: 14 条股票链 01 模板逐字相同、facts.txt 同 slot 本就是同一份, 原来 14 次 LLM 消化同一份事实(单次约 5.6min/$1.3)。
# 模板=taoge chain.md 的 step:01m(主模板); 共享失败/超时=回落本链 01 原模板。CHAIN_SHARED_01=0 可整体关掉(回滚开关)
SHARED01_SKIP = {"buchitudou0"}   # 转债链 01 模板不同(转债域事实), 仍走本链 01
# skill → facts「导师信号速览」里该导师小节标题关键词(与 facts.mjs mentors 表一致; 无独立小节的导师不列)
MENTOR_HEAD = {m: MENTORS.head(m) for m in MENTORS.ids("UP", "tzzb")}   # 10/14 F3: 全员接线; 10/17 读登记表 short 字段括号前(facts.mjs 同源)


def _write_lf(f, text):
    with open(f, "w", encoding="utf-8", newline="\n") as fh:   # Windows 下 write_text 会写成 CRLF
        fh.write(text)


def _market_ok(f, date, date_dash, facts_mtime):
    if not f.exists() or f.stat().st_mtime < facts_mtime:
        return None
    t = f.read_text(encoding="utf-8")
    if not t.strip() or sentinel_ok(t, "01m", date) is not True:
        return None
    c, err = contract_of(t)
    return None if err or v01(c, {"date_dash": date_dash}) else t


def ensure_shared_01(date, date_dash, slot):
    """返回共享市场摘要全文; None=不可用(调用方回落本链 01)。首个抢到锁的链构建, 其余等; 构建失败留 .01m.failed 让其余链立即回落"""
    import psutil
    d = PAPER_DATA / "facts" / date_dash / slot
    out, lock, failed = d / "01_market.md", d / ".01m.lock", d / ".01m.failed"
    fm = (d / "facts.md").stat().st_mtime
    for _ in range(150):   # 等他链构建 ≤25min(单次约 5min, 含回炉)
        t = _market_ok(out, date, date_dash, fm)
        if t:
            return t
        if failed.exists() and failed.stat().st_mtime >= fm:
            return None
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode()); os.close(fd)
            break
        except FileExistsError:
            try:
                if not psutil.pid_exists(int(lock.read_text() or 0)):
                    lock.unlink(missing_ok=True)   # 构建者已死=回收重抢
                    continue
            except (ValueError, OSError):
                pass
            time.sleep(10)
    else:
        print("WARN: 01 共享摘要等待超时")
        return None
    try:
        tpl = _templates_of(SKILL_CFG["taoge"]["chain_md"]).get("01m")
        if not tpl:
            print("WARN: taoge chain.md 缺 step:01m 模板")
            return None
        prompt = tpl.replace("{date_dash}", date_dash).replace("{date}", date) \
            .replace("{facts_dir}", str(d).replace("\\", "/"))
        if ASOF:
            prompt = ASOF_NOTE.replace("{date_dash}", date_dash) + prompt
        fail = None
        for attempt in range(1, MAX_RETRY + 2):
            p = prompt if not fail else prompt + f"\n\n[驱动器回炉 {attempt - 1}/{MAX_RETRY}] 上次失败原因: {fail}。只修此问题, 产物要求不变。"
            if fail:
                log_retry(d, date, slot, "01m", attempt - 1, fail)
            since = time.time()
            rc, usage, cost, dur = call_claude(p, trace=(d / "tool_calls" / "01m.jsonl", {"slot": slot, "step": "01m", "attempt": attempt}))
            log_tokens(date, slot, "01m", attempt, usage, cost, dur)
            t = _market_ok(out, date, date_dash, max(fm, since))
            if t:
                print(f"step 01m ✅ 共享市场摘要已建 (attempt {attempt}, {dur:.0f}s) → {out}")
                return t
            fail = f"{out.name} 缺失/不新鲜/末行非 STEP_OK 01m {date}/contract 不合格(date 须 {date_dash}, digest 非空)"
        failed.write_text(f"{datetime.now():%H:%M:%S} {SKILL_NAME} 构建失败: {fail}\n", encoding="utf-8")
        return None
    finally:
        lock.unlink(missing_ok=True)


def assemble_01(run_dir, market_text, date, date_dash, slot, book, snaps):
    """本链 01_facts.md = 共享市场摘要 + 本链账户(账本机械摘录) + 本链导师信号(facts 原文摘录); 契约/哨兵同原 01"""
    mc, _ = contract_of(market_text)
    body = market_text[:market_text.rfind("```contract")].rstrip()
    out = [f"# 01 事实摘要 · {SKILL_NAME} · {date_dash} {slot}",
           f"> 10/12 起 01 共享: 第一节=同 slot 股票链共用的一次市场摘要(facts/{date_dash}/{slot}/01_market.md); "
           "第二、三节=驱动器从本链账本与 facts 机械追加(零 token, 只陈述不判断)", "",
           "## 一、市场事实(全链共用摘要)", body, "",
           f"## 二、本链账户({book['source']}, paper_state.json 机械摘录)",
           f"- nav≈{book_nav(book):.0f}(最近 EOD 市值口径) / 现金 {book['cash']:.0f} / 持仓 {len(book['positions'])} 只"]
    facts = (run_dir / "facts.txt").read_text(encoding="utf-8")
    if book["positions"]:
        # 10/13 修: as-of 回放 facts.json watch 无 name → 从 facts.txt「关注票实时快照」节按代码抠票名(行式: "- 000692 惠天热电(持仓): ...")
        qs = facts.split("## 关注票实时快照", 1)[1].split("\n## ", 1)[0] if "## 关注票实时快照" in facts else ""
        def _name(code, w):
            if w.get("name"):
                return w["name"]
            m = re.search(rf"^- {code} ([^\s(（:：]+)", qs, re.M)
            return m.group(1) if m else ""
        out += ["", "| 代码 | 名称 | 股数 | 成本 | 现价(facts 快照) | 市值≈ |", "|---|---|---|---|---|---|"]
        for code, p in book["positions"].items():
            w = snaps.get(code) or {}
            px = _px_of(w)
            out.append(f"| {code} | {_name(code, w)} | {p['qty']} | {p['cost']:.3f} | {px if px else '无快照'} | {p['qty'] * (px or p['cost']):.0f} |")
    opens = [o for o in book["orders"] if o.get("status") == "open"]
    out.append("- 未成交挂单: " + ("; ".join(f"{o['side']} {o['code']} {o['qty']}@{o['price']}" for o in opens) if opens else "无"))
    out += ["", "## 三、本链导师信号(facts.txt「导师信号速览」本导师小节原文)"]
    kw, sec = MENTOR_HEAD.get(SKILL_NAME), ""
    i = facts.find("## 导师信号速览")
    if kw and i >= 0:
        seg = facts[i:]
        j = re.search(r"^## ", seg[3:], re.M)
        seg = seg[:j.start() + 3] if j else seg
        m = re.search(rf"^### [^\n]*{re.escape(kw)}[^\n]*$", seg, re.M)
        if m:
            rest = seg[m.start():]
            k = re.search(r"^#{2,3} ", rest[3:], re.M)
            sec = (rest[:k.start() + 3] if k else rest).strip()
    out.append(sec or f"(facts 导师信号速览无本导师独立小节; 本导师规则见 skills/{SKILL_NAME}-skill/persona/rules_index.md, 02 起各步按需读)")
    contract = {"date": date_dash, "sources": list((mc or {}).get("sources") or []) + ["paper_state.json(机械)"],
                "digest": (mc or {}).get("digest", ""), "shared": f"facts/{date_dash}/{slot}/01_market.md"}
    out += ["", "```contract", json.dumps(contract, ensure_ascii=False), "```", f"STEP_OK 01 {date}", ""]
    _write_lf(run_dir / ART["01"], "\n".join(out))
    return contract


# ---------- 10/13 链改造 G: 精简模板选择 + 人看表机械渲染(仅 CHAIN_COMPACT=1) ----------
_COMPACT_WARNED = set()


def tpl_key(step, templates):
    """G 开且本链 chain.md 有 <step>c 模板 → 用精简版; 否则原模板(缺模板只告警一次, 不中止)"""
    if COMPACT and step in ("04", "05", "06"):
        if f"{step}c" in templates:
            return f"{step}c"
        if step not in _COMPACT_WARNED:
            _COMPACT_WARNED.add(step)
            print(f"WARN: CHAIN_COMPACT=1 但 {CHAIN_MD.name} 缺 step:{step}c 模板, 本步回落原模板")
    return step


def _cell(v, n=200):
    s = "" if v is None else str(v)
    s = s.replace("|", "／").replace("\r", " ").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "…"


def _render_04(c, ctx):
    pc, snaps, book = ctx.get("pc") or {}, ctx.get("snap") or {}, ctx.get("book") or {}
    pos = book.get("positions") or {}
    cands = c.get("candidates") or []
    n_leg = sum(1 for x in cands if x.get("group") == "遗留")
    out = ["## 驱动器渲染 · 04 候选表(CHAIN_COMPACT: contract 校验通过后机械生成, 零 token; 内容以 contract 为准)", "",
           f"- 候选 {len(cands)} 只(遗留 {n_leg} / 方向 {len(cands) - n_leg}); 驱动器约束: 单票上限 {pc.get('cap', 0):.0f} 元, "
           f"总仓下限缺口 {pc.get('gap', 0):.0f} 元 → 至少 {pc.get('need_n', 0)} 只买入票"]
    if c.get("断链说明"):
        out.append(f"- 断链说明: {_cell(c['断链说明'], 400)}")
    out += ["", "| 组 | 代码 | 票 | 方向 | 条件价/挂法 | 仓位 | 置信 | 前收(cand_snap) | 账本持仓 | 理由 |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for x in cands:
        code = str(x.get("code") or "")
        p = pos.get(code)
        ps = f"{p['qty']}股@{p['cost']:.2f}" if p else "—"
        out.append(f"| {_cell(x.get('group'))} | {_cell(code) or '—'} | {_cell(x.get('name'))} | {_cell(x.get('direction'), 40)} | "
                   f"{_cell(x.get('trigger'), 160)} | {_cell(x.get('pos'), 40)} | {_cell(x.get('conf'), 8)} | "
                   f"{(snaps.get(code) or {}).get('prevClose') or '—'} | {ps} | {_cell(x.get('why'), 160)} |")
    for pp in c.get("pool_proposals") or []:
        out.append(f"- 扩池提案: {_cell(pp.get('direction'))} ← {', '.join(map(str, pp.get('names') or []))}")
    return out


def _render_05(c, ctx):
    pc = ctx.get("pc") or {}
    c04 = {x.get("name"): x for x in (ctx["contracts"].get("04", {}).get("candidates") or [])}
    vs = c.get("verdicts") or []
    cnt = {k: sum(1 for v in vs if v.get("result") == k) for k in ("批准", "条件批准", "否决")}
    out = ["## 驱动器渲染 · 05 逐票结论(CHAIN_COMPACT: contract 校验通过后机械生成, 零 token; 内容以 contract 为准)", "",
           f"- 批准 {cnt['批准']} / 条件批准 {cnt['条件批准']} / 否决 {cnt['否决']}(共 {len(vs)} 只 = 04 候选); "
           f"驱动器要求批准+条件批准 ≥ {pc.get('need_n', 0)} 只", "",
           "| 票 | 代码 | 04 组 | 结论 | 理由/条件 |", "|---|---|---|---|---|"]
    for v in vs:
        x = c04.get(v.get("name")) or {}
        out.append(f"| {_cell(v.get('name'))} | {_cell(x.get('code')) or '—'} | {_cell(x.get('group'))} | {_cell(v.get('result'))} | {_cell(v.get('reason'), 240)} |")
    if c.get("portfolio"):
        out += ["", "组合级约束:"] + [f"- {_cell(p, 300)}" for p in (c["portfolio"] if isinstance(c["portfolio"], list) else [c["portfolio"]])]
    return out


def _render_06(c, ctx):
    pc, snaps = ctx.get("pc") or {"held": {}, "open_buy": {}}, ctx.get("snap") or {}
    acts = c.get("actions") or []
    out = ["## 驱动器渲染 · 06 挂单表与总仓算账(CHAIN_COMPACT: contract 校验通过后机械生成, 零 token; 落 plans 以 contract 为准)", "",
           f"- supersedes: {_cell(c.get('supersedes'), 200)} | no_trade={c.get('no_trade')} | {len(acts)} 笔", "",
           "| # | 操作 | 代码 | 票 | 挂价 | qty | 金额 | anchor | 前收 | cancel_below | stop_below | 规则 | 失效 | 理由 |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    held, buy, sell = dict(pc.get("held") or {}), 0.0, 0.0
    for i, a in enumerate(acts, 1):
        px = a.get("_px")
        amt = px * a["qty"] if px and isinstance(a.get("qty"), int) else None
        if amt and a.get("op") == "买":
            buy += amt
        elif amt and a.get("op") in SELL_OPS:
            v = min(amt, held.get(str(a.get("code")), 0.0))
            held[str(a.get("code"))] = held.get(str(a.get("code")), 0.0) - v
            sell += v
        pxs = (f"{px:g}" + (f"({a['_formula']})" if a.get("_formula") else "")) if px else _cell(a.get("trigger_price"))
        if a.get("op") == "开盘卖":   # 10/16 新动词: 挂价列=锚仅参考
            pxs = f"市价(参考{pxs})"
        elif a.get("op") == "撤单":
            pxs = f"撤 {(a.get('_cxl') or {}).get('id') or a.get('order_id') or (str(a.get('code')) + '/' + str(a.get('side')))}" + ("" if a.get("_cxl") else "(无匹配挂单, 未落 plans)")
        if a.get("_nb"):
            pxs += f" ≥{a['_nb']}"
        rules = ",".join(str(r.get("id")) for r in (a.get("rules") or []) if isinstance(r, dict))
        amts = f"{amt:,.0f}" if amt else "—"
        prev = (snaps.get(str(a.get("code"))) or {}).get("prevClose") or "—"
        out.append(f"| {i} | {_cell(a.get('op'))} | {_cell(a.get('code'))} | {_cell(a.get('name'))} | {pxs} | {a.get('qty')} | "
                   f"{amts} | {_cell(a.get('anchor'))} | {prev} | "
                   f"{_cell(a.get('cancel_below')) or '—'} | {_cell(a.get('stop_below')) or '—'} | {rules or '—'} | "
                   f"{_cell(a.get('invalid_if'), 160) or '—'} | {_cell(a.get('why'), 160)} |")
    new_codes = _new_codes(acts)
    ob = sum(v for k, v in (pc.get("open_buy") or {}).items() if k not in new_codes)
    h0 = sum((pc.get("held") or {}).values())
    total = h0 - sell + ob + buy
    out += ["", f"- 总仓算账(驱动器口径, 同 v06): 持仓≈{h0:,.0f} − 本次卖 {sell:,.0f} + 未成交买单 {ob:,.0f} + 本次买 {buy:,.0f} = **{total:,.0f}**"
            + (f"; 下限 {pc['floor'] * pc['nav']:,.0f}({pc['floor']:.0%} nav) → {'达标' if total >= pc['floor'] * pc['nav'] else '未达(驱动器已判不可达放行或末次放行)'}" if pc.get("floor") else "")
            + (f"; 单票上限 {pc['cap']:,.0f}; 现金 {pc['cash']:,.0f}" if pc.get("cap") else "")]
    if c.get("persona_sections"):
        out.append(f"- 依据画像节(persona_sections): {', '.join(map(str, c['persona_sections']))}")
    return out


def render_into(run_dir, step, c, ctx):
    """G: 人看表插到产物文件 contract 块之前(哨兵仍是末行、contract 仍是末个块); 先删旧渲染段(盲审回炉 06 可能抄回旧段)。失败只告警"""
    try:
        f = run_dir / ART[step]
        t = f.read_text(encoding="utf-8")
        t = re.sub(r"\n*<!-- render:begin -->[\s\S]*?<!-- render:end -->\n*", "\n\n", t)
        i = t.rfind("```contract")
        if i < 0:
            return
        body = {"04": _render_04, "05": _render_05, "06": _render_06}[step](c, ctx)
        block = "\n".join(["<!-- render:begin -->"] + body + ["<!-- render:end -->"])
        _write_lf(f, t[:i].rstrip() + "\n\n" + block + "\n\n" + t[i:])
    except Exception as e:  # noqa: BLE001  渲染失败不影响链(contract 已校验通过)
        print(f"WARN: {step} 人看表渲染失败: {e}")


# ---------- 10/13 链改造 F: 导师画像按目录+按步注入(仅 CHAIN_PROFILE_INDEX=1) ----------
PROFILE_STEP_CAP = 30000   # 单步注入画像原文上限(字节); 超出的节只列目录供按行号补读
_PROFILE_CACHE = {}


def profile_pack(pdir=None):
    """读 profile_index.md + 当前 profile.md, 按(节标题, sha8)重新定位(profile 被 distill 改过的节=stale 跳过, 不注入错位原文)。
    返回 {summary, rows[含当前行号/原文], stale[id], new[未标注新节]}; 无索引/解析败=None(调用方回落原行为)"""
    pdir = Path(pdir) if pdir else persona_dir()
    if str(pdir) in _PROFILE_CACHE:
        return _PROFILE_CACHE[str(pdir)]
    pack = None
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "md"))
        import gen_profile_index as gpi
        idx = gpi.read_index(pdir / "profile_index.md")
        if not idx or not idx[2]:
            print(f"WARN: CHAIN_PROFILE_INDEX=1 但 {pdir.name}/profile_index.md 缺失/无目录行, 本链不注入画像(先跑 gen_profile_index.py)")
        else:
            cur = gpi.parse_sections((pdir / "profile.md").read_text(encoding="utf-8"))
            by = {(s["title"], s["sha8"]): s for s in cur}
            rows, stale = [], []
            for r in idx[2]:
                s = by.get((r["title"], r["sha8"]))
                if s:
                    rows.append({**r, "start": s["start"], "end": s["end"], "text": s["text"], "bytes": s["bytes"]})
                else:
                    stale.append(r)
            known = {(r["title"], r["sha8"]) for r in idx[2]}
            pack = {"summary": idx[1], "rows": rows, "stale": stale, "new": [s for s in cur if (s["title"], s["sha8"]) not in known]}
            if stale or pack["new"]:
                print(f"WARN: profile_index 与当前 profile.md 有 {len(stale)} 节失配/{len(pack['new'])} 节未标注(profile 改过), 失配节不注入; 重跑 gen_profile_index.py 可增量补标")
    except Exception as e:  # noqa: BLE001
        print(f"WARN: profile_index 读取失败, 本链不注入画像: {e}")
    _PROFILE_CACHE[str(pdir)] = pack
    return pack


def profile_block(step, ctx, pdir=None):
    """F: 本步注入块 = 核心摘要 + 适用本步的节原文(按优先级装到上限, 再按原文顺序排) + 其余节目录; 关闭/不适用=空串"""
    if not PROFILE_IDX or SKILL_NAME in SHARED01_SKIP:
        return ""
    key = "03" if step.startswith("03") else step
    if key not in ("02", "03", "04", "05", "06"):
        return ""
    pack = profile_pack(pdir)
    if not pack:
        return ""
    ctx["profile_ids"] = {r["id"] for r in pack["rows"]}
    inj, rest, used = [], [], 0
    for r in sorted(pack["rows"], key=lambda r: (r["prio"], r["start"])):
        if key in r["steps"] and (used + r["bytes"] <= PROFILE_STEP_CAP or not inj):
            inj.append(r); used += r["bytes"]
        else:
            rest.append(r)
    pf = f"{persona_rel()}/profile.md"
    out = [f"\n\n# 导师画像按步注入(CHAIN_PROFILE_INDEX=1, 驱动器从 {pf} 机械摘录原文, 非转述)",
           f"- 本块=画像核心摘要 + 「适用步骤」含本步({key})的 {len(inj)} 节原文({used / 1024:.1f}KB)。**本步不必再整读 profile.md**(模板里\"读 profile.md\"由本块替代); "
           f"下方目录里的其余节确有需要时按行号 Read {pf} 补读(offset=起行, limit=行数)。rules_index.md 照常读。",
           "", "## 画像核心摘要", pack["summary"] or "(无)", "", "## 本步注入节(原文)"]
    for r in sorted(inj, key=lambda r: r["start"]):
        out += ["", f"### 【{r['id']}】{r['title']}(profile.md L{r['start']}-{r['end']})", r["text"]]
    out += ["", "## 画像目录(未注入节; 需要时按行号补读)"]
    for r in sorted(rest, key=lambda r: r["start"]):
        out.append(f"- {r['id']} {r['title']} L{r['start']}-{r['end']} {r['bytes'] / 1024:.1f}KB: {r['about']}"
                   f"(适用 {','.join(r['steps']) or '—'}{'; 超本步注入上限未注入' if key in r['steps'] else ''})")
    for s in pack["new"]:
        out.append(f"- (未标注新节) {s['title']} L{s['start']}-{s['end']} {s['bytes'] / 1024:.1f}KB")
    if key == "06":
        out += ["", "- contract 可选字段 `persona_sections`: 本裁决实际依据了画像哪几节, 填上面的编号列表如 [\"S05\",\"S12\"]"
                    "(驱动器校验编号存在, 填不存在的编号=回炉; 没依据画像可不填)"]
    return "\n".join(out)


# ---------- 10/14 决策日志 + 反思回注(仅 CHAIN_REFLECTION=1 且本 skill 在白名单; 关闭=全部空操作) ----------
def _dm():
    d = str(Path(__file__).resolve().parents[1] / "dfcf" / "paper")   # 固定真目录(PAPER 可被回放/自测改指沙盒)
    if d not in sys.path:
        sys.path.insert(0, d)
    import decision_memory
    return decision_memory


def _jl_names():
    """paper/names.json 代码 → 名称(07 反思按票挂接用); 读不到 = {}"""
    try:
        return json.loads((Path(__file__).resolve().parents[1] / "dfcf" / "paper" / "names.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def reflect_on():
    if not REFLECT:
        return False
    try:
        return _dm().skill_enabled(SKILL_NAME)
    except Exception as e:  # noqa: BLE001  模块坏=当关闭处理, 不阻断链
        print(f"WARN: decision_memory 加载失败, 反思回注按关闭处理: {e}")
        return False


def _reflection_block_v1(step, ctx):
    """04/06 prompt 末尾的已结算反思块: 同票(持仓+未成交挂单+06 时加 04 候选)每票 ≤5 条 + 本链其他票 ≤3 条;
    只取反思 resolved < 链运行日(as-of 防偷看未来)。读 PAPER_DATA/decisions, as-of 回放再并上实盘 decisions。关闭/失败=空串"""
    if step not in ("04", "06") or not reflect_on():
        return ""
    try:
        book = ctx.get("book") or {}
        codes = list((book.get("positions") or {}).keys()) + [str(o.get("code")) for o in book.get("orders") or [] if o.get("status") == "open"]
        if step == "06":
            codes += [str(x.get("code")) for x in (ctx["contracts"].get("04") or {}).get("candidates") or [] if x.get("code")]
        dirs = [PAPER_DATA / "decisions"] + ([PAPER / "decisions"] if PAPER_DATA != PAPER else [])
        text, ns, nc = _dm().past_context(dirs, SKILL_NAME, codes, ctx["date_dash"])
        ctx.setdefault("reflect_n", {})[step] = (ns, nc)
        return text
    except Exception as e:  # noqa: BLE001
        print(f"WARN: 反思回注失败(本步不注入): {e}")
        return ""


def reflection_block(step, ctx):
    """04/06 末尾反思块 = 已结算反思(CHAIN_REFLECTION) + FinCon 式偏离触发提示(CHAIN_REFLECT_TRIGGER); 两个都关=空串(逐字节旧行为)"""
    return _reflection_block_v1(step, ctx) + trigger_block(step, ctx)


def _trigger_stale_days():
    try:
        import yaml
        v = ((yaml.safe_load((Path(__file__).resolve().parents[1] / "dfcf" / "paper" / "params.yaml").read_text(encoding="utf-8")) or {})
             .get("reflection_trigger") or {}).get("stale_days")
        return int(v) if v else 10
    except Exception:  # noqa: BLE001
        return 10


def trigger_block(step, ctx):
    """10/16 晚 二B-6: 读 REFLECT_TRIGGER_DIR 下 日期 < 运行日(as-of 防偷看) 且 ≥ 运行日−stale_days 的最近一份 <日>.json, 本链 triggered 则返回 inject 原文。
    关闭/非 04·06/无文件/本链未触发/读失败=空串(失败只告警, 不阻断链)。同一 ctx 每步只算一次(回炉沿用同一份)"""
    if not REFLECT_TRIGGER or step not in ("04", "06"):
        return ""
    memo = ctx.setdefault("reflect_trigger", {})
    if step in memo:
        return memo[step]["text"]
    text, src = "", None
    try:
        from datetime import date as _date, timedelta as _td
        today = ctx["date_dash"]
        lo = (_date.fromisoformat(today) - _td(days=_trigger_stale_days())).isoformat()
        fs = sorted(f for f in REFLECT_TRIGGER_DIR.glob("????-??-??.json") if lo <= f.stem < today)
        if fs:
            src = fs[-1]
            row = (json.loads(src.read_text(encoding="utf-8")).get("chains") or {}).get(SKILL_NAME) or {}
            if row.get("triggered") and str(row.get("inject") or "").strip():
                text = str(row["inject"])
                print(f"偏离触发回注 {step}: {src.name} → " + "；".join(str(t.get("key")) for t in row.get("triggers") or []) + f"（{len(text)} 字）")
    except Exception as e:  # noqa: BLE001
        print(f"WARN: 偏离触发回注读取失败(本步不注入): {e}")
        text = ""
    memo[step] = {"text": text, "src": src.name if src else None}
    return text


def log_decisions(date_dash, slot, source, contract, ctx):
    """06 出单(emit_plans 之后)每个 action 落一条待结算记录 → PAPER_DATA/decisions/<skill>.jsonl。失败只告警"""
    try:
        dm = _dm()
        recs = dm.records_from_contract(contract, skill=SKILL_NAME, source=source, date=date_dash, slot=slot, sub=ctx.get("sub"),
                                        blind_fail=bool(ctx.get("blind_fail")), asof=bool(ASOF))
        dm.write_decisions(PAPER_DATA / "decisions", SKILL_NAME, recs)
        if recs:
            print(f"决策日志: {len(recs)} 条待结算 → {PAPER_DATA / 'decisions' / (SKILL_NAME + '.jsonl')}")
    except Exception as e:  # noqa: BLE001
        print(f"WARN: 决策日志写入失败(不影响出单): {e}")


# ---------- 10/16 晚 持有期改造: 持有期参考 / 持仓论点回看 / 多日核对 / 导师真人当日操作(零 token; 仅 CHAIN_HORIZON=1, 关闭=空串, 失败=空串+WARN) ----------
HORIZON_FILE = Path(os.environ.get("CHAIN_HORIZON_FILE") or (ROOT / "scripts/taoge-chain/horizon_days.json"))
HORIZON_DEFAULT = {"med": 2, "cap": 5, "src": "无统计，按画像(缺省参考 2 天/上限 5 天)", "stat": False}
HORIZON_STEPS = ("02", "03b", "03s", "03j", "04", "07")
REVIEW_LOOKBACK = 10   # 从没跑过 07 时, 多日核对回看的交易日数


def horizon_of(skill):
    """持有期表(gen_horizon.py 生成, 可手改): med=真人持仓天数中位(默认看几天), cap=P75(拿得住的上限, 超过须写理由); stat=有无真人统计。
    缺文件/缺键/null=缺省 2/5 且 stat=False(无统计，按画像: 只给参考, 不做超上限校验)"""
    try:
        tab = json.loads(HORIZON_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        tab = {}
    row = tab.get(skill) or {}
    med, cap = _pos_int(row.get("med"), 60), _pos_int(row.get("cap"))
    stat = bool(row.get("stat", True)) and bool(med)
    med = med or _pos_int((tab.get("_default") or {}).get("med"), 60) or HORIZON_DEFAULT["med"]
    cap = max(med, cap or _pos_int((tab.get("_default") or {}).get("cap")) or HORIZON_DEFAULT["cap"])
    return {"med": med, "cap": cap, "stat": stat, "src": str(row.get("src") or HORIZON_DEFAULT["src"])}


def _trade_cal(run_dir, book, today):
    """交易日历(机械近似): 本链 results 下 live-/asof- 目录日期 ∪ 账本 nav 日期 ∪ 今天(只取 ≤ 今天)"""
    ds = {today}
    try:
        for p in run_dir.parent.iterdir():
            m = re.match(r"(?:live|asof)-(\d{8})", p.name)
            if m:
                ds.add(f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}")
    except OSError:
        pass
    ds |= {str(n.get("date")) for n in (book or {}).get("nav") or [] if n.get("date")}
    return sorted(d for d in ds if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) and d <= today)


def _cal_from(cal, start):
    """日历早于 start 的部分用工作日补齐(链建之前买的票/日历缺口前的日期)"""
    from datetime import date as _d, timedelta
    if not cal or start >= cal[0]:
        return cal
    ext, d, end = [], _d.fromisoformat(start), _d.fromisoformat(cal[0])
    while d < end:
        if d.weekday() < 5:
            ext.append(d.isoformat())
        d += timedelta(days=1)
    return ext + cal


def _tdays(a, b, cal):
    """a→b 经过的交易日数(a 当天记 0)"""
    cal = _cal_from(cal, a)
    return sum(1 for d in cal if a < d <= b)


def _add_tdays(a, n, cal):
    """a 之后第 n 个交易日(n=0 即 a 本身或其后首个交易日); 超出日历(还没到)=None"""
    cal = _cal_from(cal, a)
    i = next((k for k, d in enumerate(cal) if d >= a), None)
    return cal[i + n] if i is not None and i + n < len(cal) else None


def _run_dir_of(run_dir, ctx, day):
    """同链同口径(live/asof+TAG)另一天的 run_dir"""
    return run_dir.parent / run_dir.name.replace(ctx["date_dash"].replace("-", ""), day.replace("-", ""), 1)


def _step_contract(rd, step, slot=None):
    """某天某 slot 的产物 contract: slots/<slot>/ 归档优先, 缺则顶层(可能是当天更晚 slot 的版本, 标 src)"""
    for f, tag in ((rd / "slots" / slot / ART[step], f"slots/{slot}") if slot else (None, None), (rd / ART[step], "顶层")):
        if f is not None and f.exists():
            c, _ = contract_of(f.read_text(encoding="utf-8"))
            if c:
                return c, tag
    return None, None


def _lots(book):
    """按成交顺序重放: 每段持仓(持股从 0 变正的那笔 BUY 起, 到清仓止) → [{code, buy, sells:[...], open:bool}]"""
    qty, cur, out = {}, {}, []
    for t in (book or {}).get("trades") or []:
        c, q = str(t.get("code")), int(t.get("qty") or 0)
        if t.get("side") == "BUY":
            if qty.get(c, 0) <= 0:
                cur[c] = {"code": c, "buy": t, "sells": [], "open": True}
                out.append(cur[c])
            qty[c] = qty.get(c, 0) + q
        elif t.get("side") == "SELL" and c in cur:
            qty[c] = qty.get(c, 0) - q
            cur[c]["sells"].append(t)
            if qty[c] <= 0:
                cur.pop(c)["open"] = False
    held = set(((book or {}).get("positions") or {}).keys())
    return [x for x in out if not x["open"] or x["code"] in held]


def _trade_meta(book, t):
    """成交 → (日期, slot, 挂单 note)"""
    o = next((o for o in (book or {}).get("orders") or [] if o.get("id") == t.get("id")), {})
    day = str(o.get("date") or t.get("date") or str(t.get("id") or "")[:10])
    return day, str(o.get("time") or "").replace(":", "") or None, str(o.get("note") or "")


def _plan_of(run_dir, ctx, day, slot, code):
    """买入那天(那个 slot)的 04 候选 + 06 动作里该票的计划: name/hold_days/exit_plan/why/src"""
    rd = _run_dir_of(run_dir, ctx, day)
    plan = {}
    c04, s04 = _step_contract(rd, "04", slot)
    x = next((x for x in (c04 or {}).get("candidates") or [] if str(x.get("code") or "") == code), None)
    if x:
        plan = {"name": x.get("name"), "hold_days": x.get("hold_days"), "exit_plan": x.get("exit_plan"),
                "why": x.get("why") or x.get("trigger"), "src": f"{day} {s04} 04"}
    c06, s06 = _step_contract(rd, "06", slot)
    a = next((a for a in (c06 or {}).get("actions") or [] if str(a.get("code") or "") == code and a.get("op") == "买"), None)
    if a:
        plan.setdefault("name", a.get("name"))
        plan["why06"] = a.get("why") or a.get("invalid_if")
        plan.setdefault("src", f"{day} {s06} 06")
    return plan


def thesis_entries(ctx, run_dir):
    """当前持仓每只票的买入论点(账本成交 → 买入日/slot → 当天 04 候选/06 动作)"""
    book, today = ctx.get("book") or {}, ctx["date_dash"]
    cal = _trade_cal(run_dir, book, today)
    out = []
    for lot in _lots(book):
        if not lot["open"]:
            continue
        t = lot["buy"]
        day, slot, note = _trade_meta(book, t)
        p = _plan_of(run_dir, ctx, day, slot, lot["code"])
        out.append({"code": lot["code"], "name": p.get("name") or "", "day": day, "slot": slot or "?", "px": t.get("price"),
                    "held": _tdays(day, today, cal), "hold_days": p.get("hold_days"), "exit_plan": p.get("exit_plan"),
                    "why": p.get("why") or p.get("why06") or note[:120], "src": p.get("src") or "挂单 note"})
    return out


def thesis_block(ctx, run_dir):
    ents = thesis_entries(ctx, run_dir)
    ctx["thesis_n"] = len(ents)
    if not ents:
        return ""
    L = ["\n## 持仓论点回看（驱动器注入）——持仓决策先对照买入时写下的判断: 论点还成立就拿(到 exit_plan 写的条件再走), 不成立才卖, 不要每天从零评估。"
         "04 遗留组每只持仓必须给 thesis_check(成立|部分成立|不成立)+thesis_note(一句理由: 当时论点的哪一环今天被证实/证伪); "
         "已持有天数超过计划持有天数=时间离场到期, 要么走, 要么写清为什么延长(延长也不超过持有期上限)",
         "| 代码 | 名称 | 买入日 slot | 买入价 | 已持有(交易日, 买入日记0) | 计划持有 | 离场计划 | 当时理由(出处) |", "|---|---|---|---|---|---|---|---|"]
    for e in ents:
        L.append(f"| {e['code']} | {_cell(e['name'], 20)} | {e['day']} {e['slot']} | {e['px']} | {e['held']} | "
                 f"{(str(e['hold_days']) + ' 天') if e['hold_days'] else '未写(旧产物)'} | {_cell(e['exit_plan'] or '未写', 80)} | {_cell(e['why'], 120)}（{e['src']}） |")
    return "\n".join(L)


def review_due_block(ctx, run_dir):
    """07 多日核对: 观察期已满的 02 outlook + 计划持有天数已到的建仓(区间=(上次 07 日, 今天])"""
    book, today = ctx.get("book") or {}, ctx["date_dash"]
    cal = _trade_cal(run_dir, book, today)
    prev = [d for d in cal if d < today and (_run_dir_of(run_dir, ctx, d) / ART["07"]).exists()]
    last = prev[-1] if prev else (cal[max(0, len(cal) - 1 - REVIEW_LOOKBACK)] if len(cal) > 1 else today)
    outl = []
    for d in cal[-60:]:
        c02, tag = _step_contract(_run_dir_of(run_dir, ctx, d), "02", "0915")
        o = (c02 or {}).get("outlook")
        n = _pos_int((o or {}).get("horizon_days"), 60) if isinstance(o, dict) else None
        if not n:
            continue
        exp = _add_tdays(d, n - 1, cal)
        if exp and last < exp <= today:
            outl.append(f"- {d}（{tag}）outlook: 未来 {n} 个交易日 view={o.get('view')}；thesis={_cell(o.get('thesis'), 160)}；invalid_if={_cell(o.get('invalid_if'), 120)}"
                        f"（观察区间 {d}~{exp}）")
    plans = []
    for lot in _lots(book):
        day, slot, _ = _trade_meta(book, lot["buy"])
        p = _plan_of(run_dir, ctx, day, slot, lot["code"])
        h = _pos_int(p.get("hold_days"))
        exp = _add_tdays(day, h, cal) if h else None
        if not exp or not (last < exp <= today):
            continue
        sells = "；".join(f"{_trade_meta(book, s)[0]} 卖 {s.get('qty')}@{s.get('price')}" for s in lot["sells"]) or "无"
        plans.append(f"- {lot['code']} {p.get('name') or ''}: {day} {slot or '?'} 买 {lot['buy'].get('qty')}@{lot['buy'].get('price')}, 计划持有 {h} 天(到 {exp}), "
                     f"离场计划: {_cell(p.get('exit_plan') or '未写', 100)}；实际卖出: {sells}；{'仍持有' if lot['open'] else '已清仓'}（{p.get('src')}）")
    L = [f"\n## 多日核对（驱动器注入）——下列判断的观察期/计划持有期在 ({last}, {today}] 内到期: 对照区间内实际走势(各日 md 收评/涨停分析、paper 成交)逐条判 对/部分对/错/无法判断, "
         "写进正文「多日核对」段 + contract 多日核对 字段 [{\"date\":\"判断日\",\"horizon_days\":N,\"view\":\"...\",\"result\":\"对|部分对|错|无法判断\",\"why\":\"...\"}]",
         "### 到期的 02 outlook", *(outl or ["- 无"]), "### 到期的持有计划（04 hold_days）", *(plans or ["- 无"])]
    if not outl and not plans:
        L.append("(今日无到期判断: 正文「多日核对」段写一句'今日无到期判断', contract 多日核对 写 [])")
    return "\n".join(L)


def _norm_leg_op(t):
    """tzzb 逐笔腿方向归一(与 scripts/tzzb/mentor_scope.py norm_op 同款): 1=买 2=卖"""
    if t.get("op") in ("1", "2"):
        return t["op"]
    bs = str(t.get("buy_sell"))
    return "1" if bs in ("1", "3", "7") else "2" if bs in ("2", "4", "8") else "1" if t.get("op") in ("252", "235") else "2" if t.get("op") == "256" else None


def mentor_real_block(skill, date_dash, cap=40, tz_dir=None):
    """07 第②问参照: tzzb 导师真人当日逐笔 + 收盘持仓(downloads/tzzb/<ledger>/); 无账本导师=提示读 md 小节"""
    if skill == "control":
        return "\n## 导师真人当日操作\n- 对照组无导师: know-how 第②问写'裸模型基准, 无导师可对照', 第③问改为'和 14 条导师链里今天做对的那条差在哪'(读 results/<导师>_chain/ 当日 06)"
    if skill not in TZZB_LEDGERS:
        return ("\n## 导师真人当日操作\n- 本导师无交易账本: 第②问参照当日 md 本导师小节(视频转写=导师亲口讲的'因')+persona/rules; "
                "md 没有当日小节=写'当日无导师原话, 按画像推断'并降置信度")
    import glob
    d = (tz_dir or ROOT / "downloads" / "tzzb") / skill
    legs, seen = [], set()
    for f in glob.glob(str(d / "position_change_p*.json")) + glob.glob(str(d / "change_bs_*.json")):
        try:
            lst = json.loads(Path(f).read_text(encoding="utf-8"))["ex_data"]["change_list"]
        except Exception:  # noqa: BLE001
            continue
        for t in lst:
            k = (t.get("trans_date"), t.get("stock_code"), t.get("trans_count"), t.get("trans_price"), t.get("op"))
            if k in seen or not str(t.get("trans_date") or "").startswith(date_dash):
                continue
            seen.add(k)
            legs.append(t)
    legs.sort(key=lambda t: t["trans_date"])
    L = [f"\n## 导师真人当日操作（驱动器注入, downloads/tzzb/{skill}/ 同花顺投资账本=只有'果'没有'因'; 第②问据此推'他为什么这么做'）"]
    for t in legs[:cap]:
        op = {"1": "买", "2": "卖"}.get(_norm_leg_op(t), "?")
        L.append(f"- {t['trans_date'][11:16]} {op} {t.get('stock_name') or ''}({t.get('stock_code')}) @{t.get('trans_price')}"
                 + (f" 仓位 {t.get('prePositionPercent')}→{t.get('aftPositionPercent')}" if t.get("aftPositionPercent") not in (None, "") else ""))
    if len(legs) > cap:
        L.append(f"- …另 {len(legs) - cap} 笔(全量见 downloads/tzzb/{skill}/)")
    if not legs:
        L.append("- 当日无成交(账本未更新或真人当日没动; 不动本身也是一种操作)")
    try:
        dp = json.loads((d / "day_positions.json").read_text(encoding="utf-8")).get(date_dash.replace("-", "")) or {}
        ps = [p for p in dp.get("list") or [] if float(p.get("position_percent") or 0) > 0]
        L.append("- 收盘持仓: " + ("、".join(f"{p.get('name')}({p.get('code')}) {float(p['position_percent']):.0%}" for p in ps[:15]) if ps else "空仓/无记录"))
    except (OSError, ValueError, TypeError):
        pass
    return "\n".join(L)


def _bucket(hm):
    """成交时段分桶(与 mentor_scope.py buy_time 同口径)"""
    return "竞价/开盘(≤09:35)" if hm <= "09:35" else "上午" if hm <= "11:30" else "午后(≤14:30)" if hm <= "14:30" else "尾盘(>14:30)"


def mimic_compare_block(ctx, tz_dir=None):
    """tzzb 导师链 07: 本链 vs 真人 当日机械对照(交不交易/方向/标的/仓位/时段) + 真人逐笔/收盘持仓; 真人账本当日未到=明说"""
    skill, day, book = SKILL_NAME, ctx["date_dash"], ctx.get("book") or {}
    real = mentor_real_block(skill, day, tz_dir=tz_dir)
    d = (tz_dir or ROOT / "downloads" / "tzzb") / skill
    try:
        dp = json.loads((d / "day_positions.json").read_text(encoding="utf-8")).get(day.replace("-", ""))
    except (OSError, ValueError):
        dp = None
    legs = [l for l in real.splitlines() if l.startswith("- ") and l[2:4].isdigit()]
    mine = [t for t in book.get("trades") or [] if _trade_meta(book, t)[0] == day]
    nav = next((n for n in reversed(book.get("nav") or []) if n.get("date") == day), None)
    L = [f"\n## 本链 vs 真人 当日对照（驱动器注入, 10/16 晚: tzzb 导师链 07 主轴=拟人偏差, 真人当日操作=标签; 先比像不像, 不比赚多少）"]
    if dp is None and not legs:
        L.append(f"- ⚠ 真人 {day} 账本未到(tzzb 15:10 起抓, 晚到可至 23:10): 拟人对照写 [] 并在正文注明'真人当日数据未到', 只做预案对照+多日核对")
    rb = sum(1 for l in legs if " 买 " in l)
    rs = sum(1 for l in legs if " 卖 " in l)
    mb = sum(1 for t in mine if t.get("side") == "BUY")
    ms = sum(1 for t in mine if t.get("side") == "SELL")
    rcodes = {re.search(r"\((\d{6})\)", l).group(1) for l in legs if re.search(r"\((\d{6})\)", l)}
    mcodes = {str(t.get("code")) for t in mine}
    rhold = {str(p.get("code")) for p in (dp or {}).get("list") or [] if float(p.get("position_percent") or 0) > 0}
    mhold = set((book.get("positions") or {}).keys())
    rsum = sum(float(p.get("position_percent") or 0) for p in (dp or {}).get("list") or [] if not str(p.get("code", "")).startswith(("204", "1318")))
    msum = (float(nav["mv"]) / float(nav["nav"])) if nav and nav.get("nav") else None
    rb_t = sorted({_bucket(l[2:7]) for l in legs})
    mb_t = sorted({_bucket(f"{(_trade_meta(book, t)[1] or '0915')[:2]}:{(_trade_meta(book, t)[1] or '0915')[2:]}") for t in mine})
    L += ["| 项 | 本链 | 真人 |", "|---|---|---|",
          f"| 交不交易 | 成交 {len(mine)} 笔 | 成交 {len(legs)} 笔 |",
          f"| 方向 | 买 {mb}/卖 {ms} | 买 {rb}/卖 {rs} |",
          f"| 标的 | 成交 {'、'.join(sorted(mcodes)) or '无'}；收盘持仓 {'、'.join(sorted(mhold)) or '空仓'} | 成交 {'、'.join(sorted(rcodes)) or '无'}；收盘持仓 {'、'.join(sorted(rhold)) or ('空仓' if dp is not None else '未到')}（重合: 成交 {'、'.join(sorted(mcodes & rcodes)) or '无'} / 持仓 {'、'.join(sorted(mhold & rhold)) or '无'}） |",
          f"| 仓位 | 收盘总仓 {msum:.0%} | 收盘总仓 {rsum:.0%} |" if msum is not None and dp is not None else f"| 仓位 | 收盘总仓 {f'{msum:.0%}' if msum is not None else '未结算'} | {'收盘总仓 ' + format(rsum, '.0%') if dp is not None else '未到'} |",
          f"| 时段 | {'、'.join(mb_t) or '无成交'}（按挂单 slot） | {'、'.join(rb_t) or '无成交'} |",
          "(本链成交时段按挂单 slot 近似, 不是撮合时刻; 真人仓位=账本 position_percent 之和, 两融可 >100%)"]
    return "\n".join(L) + real.replace("\n## 导师真人当日操作（", "\n### 真人逐笔与收盘持仓（", 1)


def tudou_t0_block(step, ctx):
    """10/18 土豆选债规则(scripts/tzzb/model_out/reports/tudou_select_20261018.md): 他 09:25 竞价买的那只 ≈ T-1 全市场转债成交额第一,
    103 天 top1 60% / top3 88%(时间外 68% / 95%); 机械算好前 3 名注入 0915 链 04/06, 配合 op=竞价T。非土豆 / 子链 / 缺数据 = 空串"""
    if SKILL_NAME != "buchitudou0" or step not in ("04", "06") or ctx.get("sub"):
        return ""
    try:
        mk = ROOT / "downloads" / "market"
        dd = ctx.get("date_dash") or datetime.now().strftime("%Y-%m-%d")
        prev = max(p.name for p in mk.iterdir() if re.fullmatch(r"\d{4}-\d\d-\d\d", p.name) and p.name < dd and (p / "kline_day.jsonl").exists())
        names = {}
        sm = mk / prev / "security_master.jsonl"
        if sm.exists():
            for l in sm.read_text(encoding="utf-8").splitlines():
                r = json.loads(l)
                if r.get("secType") == "CB":
                    names[r["symbol"]] = r.get("name")
        rows = []
        for l in (mk / prev / "kline_day.jsonl").read_text(encoding="utf-8").splitlines():
            r = json.loads(l)
            if re.fullmatch(r"(sh11|sz12)\d{4}", r.get("symbol", "")) and r.get("amount"):
                rows.append(r)
        rows.sort(key=lambda r: -float(r["amount"]))
        top = [f"{i}. {names.get(r['symbol'], '?')}({r['symbol'][2:]}) 成交额 {float(r['amount']) / 1e8:.1f} 亿, 收 {r['close']}"
               + (f"({(r['close'] / r['preClose'] - 1) * 100:+.1f}%)" if r.get("preClose") else "") for i, r in enumerate(rows[:3], 1)]
        if not top:
            return ""
        # 10/19 用户口述的转债逻辑(正股涨停→转债 20cm 空间 / 临赎回临期 / 负溢价拉回 / 同热点最强一支)落成事实表 → 注入精选(collect_cb_facts.py 每晚产)
        cbf = ""
        try:
            cbf = (mk / prev / "cb_facts.md").read_text(encoding="utf-8")
            cbf = "\n".join(l for l in cbf.splitlines() if not l.startswith("# "))[:3500]
        except OSError:
            cbf = ""
        return ("\n\n# 驱动器注入: 竞价T 机械选债(10/18 逆向他的 103 个竞价日: 09:25 竞价买的那只 ≈ 前一交易日全市场转债成交额第一, "
                "top1 命中 60% / 前三 88%, 时间外 68% / 95%; 他连做同一只时它通常仍是额第一, 掉出前二多半换票)\n"
                f"- {prev} 转债成交额前三: " + " | ".join(top) + "\n"
                "- 用法: 首选第 1 名下 op=\"竞价T\"(竞价买、开盘即卖), 金额按他的固定名义本金习惯; 正股竞价高开 ≥2% 时他胜率 91%(0915 看不到当天竞价, 这只是参考); "
                "第 1 名正股前一日大跌且他近 8 日做过别的熟票时, 他偶尔回到老票(17/103 天)。\n"
                + (f"\n## 前一交易日 {prev} 可转债事实表精选(collect_cb_facts.py; 只是事实, 用不用按 R0 阶段妖债 / R4 / R6 / R8 裁决)\n{cbf}\n" if cbf else ""))
    except Exception as e:   # noqa: BLE001  fail-open
        print(f"WARN: 竞价T 选债注入失败(fail-open): {e}")
        return ""


def horizon_block(step, ctx):
    """02/03/04/07 prompt 末尾: 本导师持有期参考(+04 持仓论点回看 / 07 多日核对+导师真人当日操作)。关闭/转债链/其他步=空串"""
    if not HORIZON or SKILL_NAME == "buchitudou0" or step not in HORIZON_STEPS:
        return ""
    try:
        h, rd = horizon_of(SKILL_NAME), ctx.get("run_dir")
        head = (f"中位 {h['med']} 天/上限 {h['cap']} 天（驱动器注入, 10/16 持有期改造; {h['src']}; 中位=默认看几天, 上限=真人持仓天数 P75=拿得住的上限）" if h["stat"]
                else f"无统计，按画像（缺省参考: 中位 {h['med']} 天/上限 {h['cap']} 天; 本导师没有持仓天数统计, 以画像/规则里的持股习惯为准）")
        over = ("超过上限必须在 over_cap_why 字段写理由(什么条件下拿得比真人 75% 的持仓都久)" if h["stat"] else "超过参考上限在 why 里说明")
        L = [f"\n\n# 本导师持有期参考: {head}",
             f"- 优先级: 先当下(本 slot 此刻该不该做), 再多日(未来 {h['med']} 个交易日)。多日判断只作加减分: 不许用'过几天会涨'推翻当下'不该做', "
             "也不许因为'今天弱'就否定一个论点仍成立的持仓"]
        if step == "02":
            L.append(f"- contract 的 outlook.horizon_days 默认填 {h['med']}(=从今天起含今天的 {h['med']} 个交易日); 想看更长最多到 {h['cap']}, {over}")
        elif step in ("03b", "03s", "03j"):
            L.append("- 辩题仍是'当下该不该做'; 论证/裁决时顺带回答: 02 的 outlook(未来 N 日判断)是支持还是削弱当下这一侧")
        elif step == "04":
            L.append(f"- 每只候选写 hold_days(预期持有交易日数, 默认 {h['med']}, 符合条件可拿到 {h['cap']}; {over})"
                     "+exit_plan(一句话: 止损/止盈/时间离场各是什么)")
            if rd is not None:
                L.append(thesis_block(ctx, rd))
        elif step == "07" and rd is not None:
            L += [review_due_block(ctx, rd), mimic_compare_block(ctx) if SKILL_NAME in TZZB_LEDGERS else mentor_real_block(SKILL_NAME, ctx["date_dash"])]
        return "\n".join(x for x in L if x)
    except Exception as e:  # noqa: BLE001
        print(f"WARN: 持有期注入失败(本步不注入): {e}")
        return ""


# ---------- 10/14 夜 §3-A6 0915 降本三改造(CHAIN_INLINE_CTX / CHAIN_SHARED_PREFIX / CHAIN_MAIN_SESSION; 全关=本段不被调用) ----------
# 实测(10/13~14 token_log 486 行精确拟合): cache_create $5/M、cache_read $0.2/M、output $20/M → 成本 55% 在 cache_create(每个新会话
# 把系统提示+材料+工具结果重新写缓存), 31% 输出, 14% 缓存读。所以: 1 省的是工具往返与探索输出; 2 省的是跨会话重复写缓存(分叉会话
# 读父会话缓存, 实测 36k 前缀 fork 命中 read=36354/create=98); 3 省的是 02/04/06 三会话各写一遍上游材料。
# 注意: claude -p --resume(含 fork)返回的 total_cost_usd 是"父会话累计+本次", 记账须减父会话累计(SESSION_COST), 否则重复计。
A6_FILES = {"02": ["01", "@ri"], "03b": ["01", "02", "@ri"], "03s": ["01", "02", "@ri"], "03j": ["01", "02", "03b", "03s", "@ri"],
            "04": ["01", "02", "03j", "@ri", "@ps"], "05": ["01", "02", "03j", "04", "@cs", "@ri", "@ps"],
            "06": ["01", "02", "03j", "04", "05", "@cs", "@ri", "@ps"], "blind": ["01", "06", "@cs", "@ri"]}
A6_CHAIN_KEYS = ("01", "@ri")          # 共用开头开启时进"本链开头"会话的材料(本链 8 个会话都要读; 盲审也读这两样)
A6_MAIN_STEPS = ("02", "04", "06")     # 主会话步
A6_ATTACH_CAP = 300_000                # 单步附件总字节上限(超出的文件只列路径让模型自己读)
SESSION_COST = {}                      # session_id → claude 报的累计美元(resume/fork 记账减父会话累计)
# 10/18 用户批(省 token, 每步素材包 CHAIN_STEP_PACK; 依据: 10/18 沙盒 77 个主会话 02→04→06 平均 38 轮 / 40 次工具,
#   其中 ~11 次 ls/wc/cat 摸目录、~10 次 Read 已附或可附的文件(cand_snap/paper_state)、~3 次自己写 python 校验 contract、~5 次 grep+sed 翻 rules):
#   ①02 也附 cand_snap/paper_state ②附"工作目录清单"(文件名+大小)免摸目录 ③工作方式约定: 不自检 contract(驱动器写完立刻机械校验并回传原因)、产物一次写全、rules 按索引行号一次读
STEP_PACK = _flag("CHAIN_STEP_PACK")
STEP_PACK_EXTRA = {"02": ["@ps"]}   # 10/18 查因: 0915 的 cand_snap 要到 03j 后才生成, 02 附它 20/20 次都是"不存在" → 去掉
# 10/19 晚(TODO 二-13, 用户: "相关性只能参考, 最终 LLM 判断, 但要确保被消费、引发 LLM 思考"): 市场拓扑注入 04/06
#   持仓 + 已出现的候选票(02/03j/04/05 合同里的 6 位代码)各一行: 行业 | 前 3 邻居(昨日涨跌) | 期货; 只用前一晚的拓扑(不偷看); 子链不注入(省 token)
TOPOLOGY = _flag("CHAIN_TOPOLOGY")


# ---------- 10/20 晚 市况改造 R1(用户批): 02 必填因子表 evidence[], 结论与因子多数方向相反 → 回炉一次 ----------
REGIME_EVIDENCE = _flag("CHAIN_REGIME_EVIDENCE")
ATTRIBUTION = _flag("CHAIN_ATTRIBUTION")   # 10/20 晚 ④ 归因推导链注入 07 + root_causes 必答
EVIDENCE_FACTORS = ("外围过程", "亚洲盘实时", "多指数对比", "T-1结构", "开盘情景", "相似市况")
EVIDENCE_LEANS = ("偏强", "中性", "偏弱")


def regime_block(step, ctx):
    if step == "06" and SKILL_NAME != "buchitudou0":   # 10/20 晚 ② 追价上限 + 想法 B(用户批: 只给信息, 不设闸)
        return ("\n\n# 驱动器补充: 追价单(10/20)\n"
                "- 追价买单可以带 \"chase_cap\": 你愿意追到的最高价(数值, ≥ 挂价)。撮合时现价超过它才作废; 没超过就不按 3% 锚偏离作废, 改单也不会越过它。不写 = 照旧 3% 锚偏离\n"
                "- 追价单的正文要写清右侧条件(cand_snap.md 末尾有每只候选的分时一句话): ①分时冲高回踩有没有守住均价线 ②市况 ③板块 / 同题材有没有共振 "
                "④今天能不能继续走强甚至封板 ⑤明天能不能冲高; 以及没封住时的 T+1 处理(第二天冲高在哪个价 / 时段卖、走弱在哪认错)")
    if not REGIME_EVIDENCE or step != "02" or SKILL_NAME == "buchitudou0":
        return ""
    return ("\n\n# 驱动器补充: 市况因子表(10/20 市况改造 R1, 驱动器校验)\n"
            "contract 必须带 \"evidence\": [{\"factor\": 因子, \"fact\": \"事实包里的具体数字/原话(写清来自哪节、几点的数)\", \"lean\": \"偏强|中性|偏弱\"}, ...], 6 个因子逐个给(相似市况事实包没有就写 中性 + fact 写\"无\"):\n"
            "- 外围过程: 隔夜美股 / 中概 / 港股, 看过程不只看收盘(尾盘拉升还是跳水)\n"
            "- 亚洲盘实时: 多指数面板里 日经 / KOSPI / A50 连续 / 小纳指 现在的涨跌和近 15 分钟方向(面板是每分钟的, 写清是几点的数); 注意国内股指期货没有夜盘\n"
            "- 多指数对比: 多指数箱体位置表(在哪) + 面板(上证 / 中证2000 / 创业板谁强谁弱)\n"
            "- T-1结构: 昨日涨跌家数、成交额、涨停 / 跌停、连板梯队、主线\n"
            "- 开盘情景: 你给今天开盘三种情景的概率(高开 / 平开 / 低开, 合计 100%), lean 按概率最大的那个\n"
            "- 相似市况: 相似日检索的结果(没有就中性)\n"
            "stance(多/中立/空)要和因子表的多数方向一致: 偏强多于偏弱却判空、或偏弱多于偏强却判多 = 驱动器回炉一次; 坚持就在正文写清哪个因子分量最重、为什么压过多数")


def evidence_check(c, ctx):
    if not REGIME_EVIDENCE or SKILL_NAME == "buchitudou0":
        return None
    ev = c.get("evidence")
    if not isinstance(ev, list) or not ev:
        return None if ctx.get("final_attempt") else "contract 缺 evidence 因子表(6 个因子: " + "、".join(EVIDENCE_FACTORS) + "; 每个 {factor, fact, lean})"
    got = {}
    for x in ev:
        if not isinstance(x, dict):
            return "evidence 每项须为对象 {factor, fact, lean}"
        f = next((k for k in EVIDENCE_FACTORS if k.replace("-", "") in str(x.get("factor") or "").replace("-", "").replace(" ", "")), None)
        ln = norm_enum(x.get("lean"), EVIDENCE_LEANS)
        if not f or not ln:
            return f"evidence 项不认识: {json.dumps(x, ensure_ascii=False)[:80]}(factor 只许 {'/'.join(EVIDENCE_FACTORS)}, lean 只许 偏强/中性/偏弱)"
        x["factor"], x["lean"] = f, ln
        got[f] = ln
    miss = [k for k in EVIDENCE_FACTORS if k not in got]
    if len(miss) > 1 and not ctx.get("final_attempt"):
        return f"evidence 缺因子: {'、'.join(miss)}(6 个都要给, 事实包没有的写 中性 + fact 写\"无\")"
    up, dn = sum(v == "偏强" for v in got.values()), sum(v == "偏弱" for v in got.values())
    st = c.get("stance")
    if ((up > dn and st == "空") or (dn > up and st == "多")) and not _soft_once(ctx, "evidence02"):
        return f"stance={st} 和因子表多数方向相反(偏强 {up} / 偏弱 {dn}): 改 stance, 或在正文写清哪个因子分量最重、为什么压过多数(回炉只这一次)"
    return None


def topology_block(step, ctx):
    if not TOPOLOGY or step not in ("04", "06") or ctx.get("sub"):
        return ""
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "market"))
        import topology as TOPO
        held = list(((ctx.get("book") or {}).get("positions") or {}).keys())
        seen = re.findall(r"(?<!\d)([036]\d{5})(?!\d)", json.dumps({k: ctx["contracts"].get(k) for k in ("02", "03j", "04", "05")}, ensure_ascii=False))
        codes = list(dict.fromkeys(held + seen))[:10]
        rows = TOPO.brief(codes, ctx.get("date_dash") or datetime.now().strftime("%Y-%m-%d"))
        if not rows:
            return ""
        return ("\n\n# 驱动器补充: 市场拓扑(持仓 / 候选的关联票, 扣大盘后近 60/20 日联动 + 同行业 + 期货; 括号 = 昨日涨跌)\n"
                + "\n".join("- " + r for r in rows)
                + "\n- 用法: 对每只要动的票想一句 —— 它和邻居昨天同向还是背离? 同向 = 板块行情, 背离 = 个股消息/资金或补涨补跌(去事实包找原因)。"
                  "这是过去的统计, 题材刚切换会滞后, 只作参考, 不改变本导师的规则与判断")
    except Exception as e:  # noqa: BLE001
        print(f"WARN: 拓扑注入失败(本步不注入): {e}")
        return ""


# 10/19 晚(TODO 二-6 省钱, 用户令"没做的话现在可以做"): 子链版素材包 CHAIN_SUB_PACK —— 10/18 拆账: 盘中子链 sub3 80 个会话占全天输入 64%、花费 53%,
#   每个平均 16 轮 / 19.6 次工具(摸目录 / 重读 rules / 自写校验); 0915 的 CHAIN_STEP_PACK 没覆盖子链(代码路径不经过 _a6_prompt)。
#   开 = sub3 合并调用前面加同一份工作方式约定 + 直接附 rules_index / paper_state / cand_snap 原文(免 Read); 关 = 逐字节旧行为
SUB_PACK = _flag("CHAIN_SUB_PACK")


def sub_pack_block(run_dir):
    if not SUB_PACK:
        return ""
    try:
        att, used, missing = a6_attach(["@ri", "@ps", "@cs"], run_dir)
    except Exception as e:   # noqa: BLE001  fail-open
        print(f"WARN: 子链素材包附件失败(fail-open): {e}")
        att, used, missing = "", [], []
    keep = STEP_PACK
    globals()["STEP_PACK"] = True   # 复用同一段约定文字(不受 0915 开关影响)
    try:
        head = step_pack_block("sub3", run_dir).replace("CHAIN_STEP_PACK", "CHAIN_SUB_PACK")
    finally:
        globals()["STEP_PACK"] = keep
    return (head + "# 已附原文(不用再 Read): " + ("、".join(used) or "无") + ("; 未附: " + "、".join(missing) if missing else "") + "\n" + att + "\n")


def step_pack_block(step, run_dir):
    if not STEP_PACK:
        return ""
    rd = Path(run_dir)
    try:
        fs = sorted((p for p in rd.iterdir() if p.is_file()), key=lambda p: p.name)
    except OSError:
        fs = []
    man = "、".join(f"{p.name}({p.stat().st_size // 1024 + 1}KB)" for p in fs[:40]) or "(空)"
    return ("# 本步工作方式(驱动器约定, CHAIN_STEP_PACK)\n"
            f"- 工作目录 {_posix(rd)} 现有文件: {man}——**不必再 ls/wc/cat 摸目录**; 已附原文的文件不要重读\n"
            "- **不要自己写 python/grep 去校验 contract 格式**: 你 Write 完产物, 驱动器会立刻机械校验; 不通过会把具体原因原文发回给你, 只改那一处即可\n"
            "- 产物**一次 Write 写全**(正文 + 末个 ```contract 块 + 末行哨兵), 不要先写草稿再反复覆盖\n"
            "- 需要某条规则全文时: 先看已附的 rules_index.md 里该条的行号, 用 Read 的 offset/limit 一次读出那一段, 不要 grep 整个 rules.md 再 sed 多次\n\n")


def a6_path(key, run_dir):
    if key == "@ri":
        return persona_dir() / "rules_index.md"
    if key == "@ps":
        return Path(run_dir) / "paper_state.json"
    if key == "@cs":
        return Path(run_dir) / "cand_snap.md"
    return Path(run_dir) / ART[key]


def _posix(p):
    return str(p).replace("\\", "/")


def file_tag(path, text):
    return f'<file path="{_posix(path)}">\n{text.rstrip()}\n</file>\n'


def _elide_01(text, market_body):
    """共用开头里已有 01_market 正文时, 本链 01_facts 的「一、市场事实」节正文(=逐字同一段)省略, 防重复塞"""
    if market_body and len(market_body) > 200 and market_body in text:
        return text.replace(market_body, "(本节正文 = 开头共享材料 01_market.md 中 ```contract 块之前的全部正文, 逐字相同, 此处省略不重复)", 1)
    return text


def a6_attach(keys, run_dir, skip=(), market_body=None):
    """keys → (附件文本, 已附键列表, 未附说明列表)。同一份材料只放一次(skip=已在会话前文出现过的键)"""
    out, used, missing, total = [], [], [], 0
    seen_paths = set()
    for k in keys:
        if k in skip:
            continue
        p = a6_path(k, run_dir)
        if str(p) in seen_paths:
            continue
        seen_paths.add(str(p))
        if not p.exists():
            missing.append(f"{_posix(p)}(不存在)")
            continue
        t = p.read_text(encoding="utf-8")
        if k == "01":
            t = _elide_01(t, market_body)
        if total + len(t.encode("utf-8")) > A6_ATTACH_CAP and used:
            missing.append(f"{_posix(p)}(超附件上限未附, 需要请自己 Read)")
            continue
        total += len(t.encode("utf-8"))
        out.append(file_tag(p, t))
        used.append(k)
    return "".join(out), used, missing


def a6_head(n_files, missing, prefix_note=""):
    lines = ["# 驱动器已附材料(CHAIN_INLINE_CTX)",
             (f"- 下列 {n_files} 个 <file> 块是驱动器在本步开始时机械读取的文件原文(本步模板里要求\"读\"的文件), 视为你已经读过, **不要再用 Read 重读**。"
              if n_files else "- 本步模板里要求\"读\"的文件都已在本会话前文附过原文, 视为你已经读过, **不要再用 Read 重读**。")
             + prefix_note,
             "- 没附的(rules.md 按编号 grep 捞规则全文、facts.txt 细节、其他文件)仍按模板自己 Read/Grep; 产物照旧用 Write 工具写到模板指定路径。"]
    if missing:
        lines.append("- 未附: " + "; ".join(missing))
    return "\n".join(lines) + "\n\n"


def _general_section():
    t = SKILL_CFG["taoge"]["chain_md"].read_text(encoding="utf-8")
    i = t.find("## 通用规范")
    if i < 0:
        return ""
    j = t.find("\n## ", i + 5)
    return t[i:j if j > 0 else None].strip()


def public_facts(t):
    """10/16 晚 串链检查发现: 共享开头原样放 facts.md = 每条链都看到全部导师的信号速览和全部账本持仓(绕过了 slim_facts, 加剧趋同)。
    共享开头只留公共部分: 删「昨日账本状态」里所有账本行, 删「导师信号速览」里各导师小节(发哥/财联社等非导师源保留);
    本链自己的账本行与本导师小节在本链 01_facts.md(本链开头会话)里"""
    def section(text, head):
        i = text.find(head)
        if i < 0:
            return None
        j = i + len(head)
        while True:
            j = text.find("\n## ", j)
            if j < 0:
                return i, len(text)
            if not re.match(r"\n## [ABC]-", text[j:j + 8]):
                return i, j
            j += 4
    s1 = section(t, "## 昨日账本状态")
    if s1:
        body = t[s1[0]:s1[1]].split("\n")
        t = t[:s1[0]] + "\n".join(l for l in body if not re.match(r"## [ABC]-", l)) + "\n(各链账本状态见本链 01_facts.md)" + t[s1[1]:]
    s2 = section(t, "## 导师信号速览")
    if s2:
        kws = tuple(MENTOR_HEAD.values())
        parts = t[s2[0]:s2[1]].split("\n### ")
        keep = [x for x in parts[1:] if not x.startswith(kws)]
        t = t[:s2[0]] + parts[0] + "".join("\n### " + x for x in keep) + "\n(各导师小节见本链 01_facts.md)" + t[s2[1]:]
    return t


def prefix_text(fdir):
    """全链共享开头(同 date/slot 逐字节相同): facts.md 公共部分(public_facts) + 01_market.md + chain.md 通用规范"""
    facts = public_facts((fdir / "facts.md").read_text(encoding="utf-8"))
    mk = fdir / "01_market.md"
    parts = ["[驱动器共享开头 CHAIN_SHARED_PREFIX] 以下是本交易日本时段十几条导师决策链共用的材料原文(同一份发给每条链)。"
             "**本条消息只需回复 OK 两个字母, 不要调用任何工具**; 具体任务在下一条消息给出。\n\n",
             file_tag(fdir / "facts.md", facts).replace("\">\n", "\" note=\"=各链 run_dir/facts.txt 同一份\">\n", 1)]
    if mk.exists():
        parts.append(file_tag(mk, mk.read_text(encoding="utf-8")).replace("\">\n", "\" note=\"全链共用 01 市场摘要; 各链 01_facts.md 第一节=其正文\">\n", 1))
    gen = _general_section()
    if gen:
        parts.append(f"<chain_md_section name=\"通用规范(每步都适用)\">\n{gen}\n</chain_md_section>\n")
    return "".join(parts)


def a6_call(prompt, trace, resume=None, fork=False):
    """call_claude 包装: 记 session 累计成本, resume/fork 返回的成本扣掉父会话累计(防重复计); 返回 (rc, usage, cost, dur, sid)"""
    rc, usage, cost, dur = call_claude(prompt, trace=trace, resume=resume, fork=fork) if resume else call_claude(prompt, trace=trace)
    sid = LAST_SESSION["id"]
    try:
        c = float(cost)
    except (TypeError, ValueError):
        return rc, usage, cost, dur, sid
    base = SESSION_COST.get(resume, 0.0) if resume else 0.0
    if sid:
        SESSION_COST[sid] = c
    return rc, usage, (round(c - base, 6) if resume else cost), dur, sid


def ensure_prefix_session(date, slot):
    """同 date/slot 全链共享开头会话: 首个抢到锁的链发出(写缓存), 其余等它完成再分叉(比固定错开 5~10s 更稳: 分叉时缓存必已写好)。
    返回 session_id; None=不可用(调用方不用共享开头, 退回只内联)。会话信息存 facts 目录 .prefix_session.json(按内容 sha 判新鲜)"""
    import hashlib, psutil
    d = PAPER_DATA / "facts" / f"{date[:4]}-{date[4:6]}-{date[6:]}" / slot
    try:
        text = prefix_text(d)
    except OSError as e:
        print(f"WARN: 共享开头材料读取失败({e}), 本链不用共享开头")
        return None
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    meta, lock, failed = d / ".prefix_session.json", d / ".prefix.lock", d / ".prefix.failed"
    for _ in range(300):   # ≤10min
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
            if m.get("sha") == sha and m.get("sid"):
                SESSION_COST.setdefault(m["sid"], float(m.get("cost") or 0))
                return m["sid"]
        except (OSError, ValueError):
            pass
        if failed.exists() and failed.read_text(encoding="utf-8").strip() == sha:
            return None
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode()); os.close(fd)
            break
        except FileExistsError:
            try:
                if not psutil.pid_exists(int(lock.read_text() or 0)):
                    lock.unlink(missing_ok=True)
                    continue
            except (ValueError, OSError):
                pass
            time.sleep(2)
    else:
        print("WARN: 共享开头会话等待超时, 本链不用共享开头")
        return None
    try:
        rc, usage, cost, dur, sid = a6_call(text, None)
        log_tokens(date, slot, "prefix", 1, usage, cost, dur)
        if rc != 0 or not sid:
            failed.write_text(sha, encoding="utf-8")
            print(f"WARN: 共享开头会话构建失败(rc={rc}), 全链退回只内联")
            return None
        _write_lf(meta, json.dumps({"sid": sid, "sha": sha, "cost": cost, "ts": datetime.now().isoformat(timespec="seconds"),
                                    "by": SKILL_NAME, "bytes": len(text.encode("utf-8"))}, ensure_ascii=False))
        print(f"共享开头会话已建: {sid[:8]}(read={usage.get('cache_read_input_tokens')} create={usage.get('cache_creation_input_tokens')}, ${cost})")
        return sid
    finally:
        lock.unlink(missing_ok=True)


def a6_chain_session(st, date, slot, run_dir):
    """本链开头会话 = 分叉共享开头 + 本链 01_facts(市场正文省略)+rules_index, 只回 OK。本链各独立会话都从它分叉。失败=None"""
    if "csid" in st:
        return st["csid"]
    st["csid"] = None
    body, used, missing = a6_attach(A6_CHAIN_KEYS, run_dir, market_body=st.get("market_body"))
    text = ("[驱动器本链开头 CHAIN_SHARED_PREFIX] 以下是本链(导师 " + SKILL_NAME + ")各步共用的材料原文。"
            "**本条只需回复 OK 两个字母, 不要调用任何工具**; 具体任务在下一条消息。\n\n" + body)
    rc, usage, cost, dur, sid = a6_call(text, None, resume=st.get("gsid"), fork=bool(st.get("gsid")))
    log_tokens(date, slot, "cprime", 1, usage, cost, dur)
    if rc == 0 and sid:
        st["csid"], st["chain_keys"] = sid, set(used)
        print(f"本链开头会话已建: {sid[:8]}(read={usage.get('cache_read_input_tokens')} create={usage.get('cache_creation_input_tokens')}, ${cost})")
    else:
        print(f"WARN: 本链开头会话构建失败(rc={rc}), 本链各步不分叉")
    return st["csid"]


# ---------- 主链 ----------
def record_rules_version(run_dir, slot, steps, dry, extra=None):
    """10/11 N1(推进分析口径): 每次链运行记下所用 persona 版本 → run_dir/run_meta.jsonl 追加一行。
    事后可分样本内/外(规则是否已含该日信息)、统计规则变动次数(同 skill 跨运行 rules sha 变化数)。
    只读 persona, 失败只告警不阻断链。"""
    import hashlib
    try:
        pdir = persona_dir()
        files = {}
        for name in ("rules.md", "profile.md", "cases.md", "language.md"):
            f = pdir / name
            if f.exists():
                b = f.read_bytes()
                files[name] = {"sha12": hashlib.sha256(b).hexdigest()[:12], "bytes": len(b),
                               "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")}
        rules = pdir / "rules.md"
        n_rules = len(re.findall(r"^### ", rules.read_text(encoding="utf-8"), re.M)) if rules.exists() else 0
        rec = {"ts": datetime.now().isoformat(timespec="seconds"), "skill": SKILL_NAME, "slot": slot,
               "steps": steps, "asof": ASOF, "dry": dry, "rules_count": n_rules, "persona": files,
               "chain_md_sha12": hashlib.sha256(CHAIN_MD.read_bytes()).hexdigest()[:12]}
        try:   # 10/14 排查 0915 调度日志缺 14 条: 记下谁启动的本链(父进程链), 判断是不是 Java 任务线程拉起的
            import psutil
            me = psutil.Process()
            rec["launch"] = {"pid": me.pid, "parents": [f"{p.pid}:{p.name()}" for p in me.parents()[:4]]}
        except Exception:  # noqa: BLE001
            pass
        if COMPACT or PROFILE_IDX:   # 10/13 F/G 开关(默认关=不加此键, run_meta 行与改造前一致)
            rec["flags"] = {"compact": COMPACT, "profile_index": PROFILE_IDX}
        if reflect_on():   # 10/14 反思回注(关闭=不加键)
            rec.setdefault("flags", {})["reflection"] = True
        nf = {k: v for k, v in (("fix_floor_exit", FIX_FLOOR_EXIT), ("fix_no_defer", FIX_NO_DEFER), ("fix_esc_rerun", FIX_ESC_RERUN),
                                ("fix_sub_approved", FIX_SUB_APPROVED), ("fix_holds", FIX_HOLDS), ("sub_gate", SUB_GATE),
                                ("sub_merge", SUB_MERGE), ("inline_ctx", INLINE_CTX), ("shared_prefix", SHARED_PREFIX), ("main_session", MAIN_SESSION)) if v}
        if nf:   # 10/14 晚 子链修复/闸/合并开关(全关=不加键)
            rec.setdefault("flags", {}).update(nf)
        if extra:
            rec.update(extra)
        with (run_dir / "run_meta.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        print(f"WARN: rules 版本记录失败(不阻断): {e}")


def archive_slot(run_dir, slot, steps, t0):
    """10/12 用户令: 每次运行的产物按 slot 存档到 run_dir/slots/<slot>/(只收本次运行写过的文件, mtime≥起跑时刻)。
    原病灶: 盘中子链覆盖 02/04/06, 0915 版只剩一版 .prev.md, 第二个盘中时段一跑就没了, 无法回溯人工检查。
    run_dir 顶层文件照旧(驱动器/Java 入库/盲审都按固定文件名读顶层), slots/ 是只追加的历史"""
    try:
        d = run_dir / "slots" / slot
        names = [ART[s] for x in steps for s in EXPAND.get(x, [x]) if s in ART] + \
                ["cand_snap.md", "cand_snap.json", "pos_constraints.json", "facts.txt", "paper_state.json", "BLIND_FAILED.txt"]
        n = 0
        for name in names:
            f = run_dir / name
            if f.exists() and f.stat().st_mtime >= t0:
                d.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, d / name)
                n += 1
        if n:
            print(f"slot 存档: {n} 个文件 → {d}")
    except Exception as e:  # noqa: BLE001  存档失败不影响链结果
        print(f"WARN: slot 存档失败: {e}")


def run_chain(date, date_dash, slot, steps, source, dry=False):
    t0 = time.time()
    run_dir = ROOT / "results" / RESULTS_DIR / (f"{'asof' if ASOF else 'live'}-{date}"  # as-of 不覆盖旧 live-D 档
                                                + (f"-{os.environ['CHAIN_RUN_TAG']}" if ASOF and os.environ.get("CHAIN_RUN_TAG") else ""))  # 10/12: A/B 回放分目录
    run_dir.mkdir(parents=True, exist_ok=True)
    sub = steps != SLOT_STEPS["0915"] and steps != ["07"]
    # 10/11 同导师互斥: 盘前全链(45min+)未完时, 同 skill 盘中子链跳过(原=子链覆盖全链 02/04/06 产物); 持锁进程死亡=回收
    import atexit, psutil
    clock = run_dir / ".chain.lock"
    if clock.exists():
        try:
            holder = int(clock.read_text() or 0)
        except ValueError:
            holder = 0
        if holder and psutil.pid_exists(holder):
            print(f"同 skill 链在跑(pid {holder}), 本次 {slot} {'子链跳过' if sub else '全链跳过'}(防覆盖产物)")
            sys.exit(0)
    clock.write_text(str(os.getpid()))
    atexit.register(lambda: clock.unlink(missing_ok=True) if clock.exists() and clock.read_text() == str(os.getpid()) else None)
    atexit.register(archive_slot, run_dir, slot, steps, t0)   # 正常结束/链中止(sys.exit)都存档; 后注册先执行, 锁仍在
    book = load_book(source)
    ctx = {"date_dash": date_dash, "nav": book_nav(book), "sub": sub, "contracts": {}, "skill": SKILL, "book": book}
    ctx["run_dir"] = run_dir   # 10/16 晚 持有期改造: 持仓论点回看/多日核对要按同口径找别的日子的 run_dir
    ctx["_q"] = {"slot": slot, "skill": SKILL_NAME, "watch": {}}   # 10/17 ② quality_hooks 用(本时段/本导师/facts 持仓快照)
    # 中段起跑(手动 --steps 回炉)预载上游 contract: v04 查 02.directions / v05 查 04.candidates /
    # v06 查 05 批准集——不预载则跨步闸对空集误判(10/10 lianghuaxiaohao 04 假拒实录: direction
    # 逐字节命中 02.directions 仍报 ∉, 因该进程 --steps 03,04,... 未跑 02、ctx["02"] 缺位)。
    # 全链/盘中子链照常跑时 run_set 覆盖本进程要跑的步, 对应键不被预载(跑完以新 contract 覆盖), 行为不变。
    _run_set = {s for x in steps for s in EXPAND.get(x, [x])}
    for _s, _art in ART.items():
        if _s in _run_set or _s == "07":
            continue
        _f = run_dir / _art
        if _f.exists():
            _c, _ = contract_of(_f.read_text(encoding="utf-8"))
            if _c:
                ctx["contracts"][_s] = _c

    facts = build_facts(date_dash, slot)
    shutil.copy(facts, run_dir / "facts.txt")  # 01 的输入口(chain.md: harness 写 facts.txt)
    slim_facts(run_dir / "facts.txt")   # 10/16 审计#5/#7: 导师链只留本链账本+本导师信号(+发哥), 防串味/抄他链持仓
    write_paper_state(book, run_dir)
    snaps = watch_snaps(date_dash, slot)
    ctx["_q"]["watch"] = snaps
    ctx["pc"] = pos_constraints(book, ctx["nav"], snaps)   # 10/12: 仓位约束机械算好, 注入 04/05/06 + v04/v05/v06 共用
    if LEDGER:   # 10/16 晚 三-2: 账本统计硬约束/候选池/基线建议(关=不调用)
        ledger_prepare(ctx, run_dir, slot, sub, dry)
    if "02" in ctx["contracts"] and "02" not in _run_set:   # 10/14: 中段起跑(不重跑 02)时用已有 02 的态度
        v02(ctx["contracts"]["02"], ctx)
        apply_stance(ctx)
    if "03j" in ctx["contracts"] and "03j" not in _run_set:   # 10/16 晚 保留分歧版: 中段起跑用已有 03 的分歧(子链/旧格式=不生效)
        debate_apply(ctx)
    _write_lf(run_dir / "pos_constraints.json", json.dumps(ctx["pc"], ensure_ascii=False, indent=1))
    if sub and (FIX_SUB_APPROVED or SUB_MERGE):   # 10/14 晚 ⑤/D: 0915-05 批准名单+持仓+挂单(子链 04 硬约束 / 合并调用预拉价格锚)
        ctx["sub_allow"] = sub_allow_list(run_dir, ctx, snaps)
        ctx["snap_names"] = {c: w.get("name") for c, w in snaps.items() if w.get("name")}
    # 10/14 晚 零 token 触发闸 A: 只管排程内的盘中子链 slot(手动 --steps/盘前/复盘不管); 取数异常=照跑
    if sub and SUB_GATE and re.fullmatch(r"\d{4}", slot) and steps == SLOT_STEPS.get(slot):
        try:
            go, why, met, gj = gate_decide(run_dir, date_dash, slot, book)
        except Exception as e:  # noqa: BLE001
            go, why, met, gj = True, [f"闸异常(fail-open): {e}"], {}, None
        print(f"触发闸: {'跑' if go else '跳过'} | " + ("; ".join(why[:4]) if why else "无触发"))
        if gj is not None and not dry:
            (run_dir / "slots" / slot).mkdir(parents=True, exist_ok=True)
            _write_lf(run_dir / "slots" / slot / "gate.json", json.dumps({**gj, "go": go, "reasons": why, "metrics": met}, ensure_ascii=False, indent=1))
        if not go and not dry:
            write_gate_skip(run_dir, date, date_dash, slot, book, met.get("last_ran"), met)
            record_rules_version(run_dir, slot, steps, dry, extra={"skipped": True, "gate": {"last_ran": met.get("last_ran")}})
            print(f"链完成(触发闸跳过, 0 token) {date} slot {slot}: 写 06 维持产物, 不调模型")
            return
    # B3: 每轮起跑前重建 rules_index(rules.md 可能刚被 distill 改过, 索引不许 stale; 失败=用旧索引不致命)
    # as-of: 编排脚本每日建一次, 并发链不重复写(防竞写)
    r = subprocess.run(["node", "scripts/md/gen_rules_index.mjs", "--skill", SKILL_NAME], cwd=ROOT,  # 10/11: 原不带 --skill=只建 taoge 且 15 进程同写
                       capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) if not ASOF else None
    if r is not None and r.returncode != 0:
        print(f"WARN: rules_index 重建失败(用旧索引继续): {(r.stderr or r.stdout)[-200:]}")
    record_rules_version(run_dir, slot, steps, dry)

    templates = load_templates()
    ctx["debate_v2"] = "bull_score" in templates.get("03j", "")   # 10/16 晚 保留分歧版: 处理组模板含两方分字段
    if sub:  # 盘中重跑归档: 旧产物改名 *.prev.md(chain.md 通用规范; 只留最近一版不连环套娃)
        for s in ("02", "04", "05", "06"):
            f = run_dir / ART[s]
            if f.exists():
                shutil.copy(f, run_dir / ART[s].replace(".md", ".prev.md"))
        prev02 = prev_contract(run_dir, "02")
    else:
        prev02 = None

    def _prompt(step, asof_note=True):
        p_ = templates[tpl_key(step, templates)].replace("{date_dash}", date_dash) \
            .replace("{date}", date).replace("{run_dir}", str(run_dir).replace("\\", "/"))
        if ASOF and asof_note:
            p_ = _asof_note() + p_
        if step == "05":  # 05 双注入(10/9): 负例警示(neg_warn) + 否决条款池(reject_rules), 均 fail-open
            p_ += neg_warn() + reject_rules()
        p_ += profile_block(step, ctx)   # 10/13 F: 关闭/不适用=空串
        if step in ("04", "05", "06"):
            p_ += constraint_text(ctx["pc"], step)
        p_ += reflection_block(step, ctx)   # 10/14 §3-A 第 6 条: 关闭/非 04·06=空串
        p_ += fix_block(step, ctx)          # 10/14 晚 子链修复: 全关=空串
        p_ += ledger_block(step, ctx)       # 10/16 晚 三-2 账本约束/基线/候选池(02/04/06): 关=空串
        p_ += quality_block(step, ctx)      # 10/17 ② 决策质量参考(相似市况/时段/T 法/挂价规则): 全关=空串
        p_ += tudou_t0_block(step, ctx)     # 10/18 土豆竞价T 机械选债(非土豆=空串)
        p_ += topology_block(step, ctx)     # 10/19 晚 市场拓扑(CHAIN_TOPOLOGY; 关=空串)
        p_ += regime_block(step, ctx)       # 10/20 晚 市况改造 R1(CHAIN_REGIME_EVIDENCE; 关=空串)
        p_ += late_news_block(step, run_dir, date_dash, slot)   # 10/16: 0915 链开跑后才入库的发哥推演, 作增量注入后续步
        if SKILL_NAME not in ("taoge", "control", "buchitudou0") and step in ((("03b", "03s", "03j") if mimic_on() else ("blind", "03b", "03s", "03j"))):   # 10/16 审计#8: 盲审/辩论模板残留桃哥口径
            p_ += ("\n\n# 驱动器补充(10/16 方案 A): 本链按本导师自己的框架决策。盲审/辩论只按本导师的能力圈与规则审, "
                   "不得以\"回避方向赶上涨停潮=矛盾\"\"没回应能力圈外的涨停簇/主线\"\"索引无 C 类负面规则\"\"未引用桃哥规则编号(A/B/C/D/E)\"为不通过理由; "
                   "空仓/观望在本导师风格内是合理选项, 不必辩成\"最小试错仓\"")
        if step == "blind":   # 10/16 晚: 拟人审对照材料(导师真实成交统计 + 本单机械统计); 对照组=空串
            p_ += mimic_block(ctx)
        p_ += horizon_block(step, ctx)      # 10/16 晚 持有期改造(02/03/04/07 末尾): 关闭=空串
        if step == "07" and SKILL_NAME != "control":   # 10/17 用户定: 链自己的 T 成绩回灌 07(零 token; 失败=不注入)
            try:
                sys.path.insert(0, str(ROOT / "scripts" / "dfcf" / "paper"))
                import chain_t_stats as _CT   # noqa: PLC0415
                p_ += _CT.block_07(SKILL_NAME, ctx.get("book") or {}, date_dash)
            except Exception as e:   # noqa: BLE001
                print(f"WARN: 链 T 成绩注入失败(不影响 07): {e}")
        if step == "07" and ATTRIBUTION:   # 10/20 晚 ④ 归因推导链(用户批): 机械算好的逐票盈亏 / 检测项 / 反事实 / 跨链汇总 + 必答 root_causes
            try:
                sys.path.insert(0, str(ROOT / "scripts" / "dfcf" / "paper"))
                import attribution as _AT   # noqa: PLC0415
                p_ += _AT.block_07(SKILL_NAME, date_dash)
            except Exception as e:   # noqa: BLE001
                print(f"WARN: 归因推导链注入失败(不影响 07): {e}")
        if step == "07" and _flag("CHAIN_PACK07"):   # 10/21 凌晨用户批: 07 素材包(当日行情 / 导师腿 / 规则 + 相似规则 / cases 错题 / lessons / 多日结算 / 知识库目录, 包头覆盖表)
            try:
                sys.path.insert(0, str(ROOT / "scripts" / "dfcf" / "paper"))
                import pack07 as _P7   # noqa: PLC0415
                p_ += _P7.block_07(SKILL_NAME, date_dash)
            except Exception as e:   # noqa: BLE001
                print(f"WARN: 07 素材包注入失败(不影响 07): {e}")
        return p_

    def _asof_note():
        if sub and os.environ.get("CHAIN_ASOF_SUBNOTE") == "1":   # 10/14 晚: 子链 as-of 回放按 slot 时刻声明(仅回放显式开; 默认沿用原声明)
            return ASOF_NOTE_SUB.replace("{date_dash}", date_dash).replace("{hm}", f"{slot[:2]}:{slot[2:]}").replace("{slot}", slot)
        return ASOF_NOTE.replace("{date_dash}", date_dash)

    # 10/14 夜 §3-A6: 只管 0915 全链(steps==0915 映射)且非转债链; 关闭/不适用 → a6=None, 主循环走原路径(逐字节不变)
    a6 = None
    if (INLINE_CTX or SHARED_PREFIX or MAIN_SESSION) and not sub and SKILL_NAME not in SHARED01_SKIP and steps == SLOT_STEPS.get("0915"):
        if not INLINE_CTX:
            print("WARN: CHAIN_SHARED_PREFIX/CHAIN_MAIN_SESSION 依赖 CHAIN_INLINE_CTX=1, 本链不启用")
        else:
            a6 = {"prefix": SHARED_PREFIX, "main": MAIN_SESSION, "msid": None, "mseen": set(), "mdone": [], "main_broken": False, "tail": {}}
            print(f"A6 降本: 内联=开 共用开头={'开' if SHARED_PREFIX else '关'} 主会话={'开' if MAIN_SESSION else '关'}")

    def _a6_setup():
        if a6.get("ready"):
            return
        a6["ready"], a6["market_body"] = True, None
        if not a6["prefix"]:
            return
        a6["gsid"] = ensure_prefix_session(date, slot)
        if a6["gsid"]:
            try:
                mt = (PAPER_DATA / "facts" / date_dash / slot / "01_market.md").read_text(encoding="utf-8")
                a6["market_body"] = mt[:mt.rfind("```contract")].rstrip() if "```contract" in mt else None
            except OSError:
                pass
        a6_chain_session(a6, date, slot, run_dir)

    def _a6_prompt(step, attempt, fail_reason):
        """返回 (prompt, resume_sid, fork, 是否主会话步)"""
        _a6_setup()
        rd = _posix(run_dir)
        if step not in a6["tail"]:   # 每步算一次(neg_warn 随机抽卡, 回炉沿用同一份, 与原路径一致)
            a6["tail"][step] = (((neg_warn() + reject_rules()) if step == "05" else "") + profile_block(step, ctx)
                                + (constraint_text(ctx["pc"], step) if step in ("04", "05", "06") else "")
                                + reflection_block(step, ctx) + fix_block(step, ctx) + ledger_block(step, ctx) + quality_block(step, ctx) + horizon_block(step, ctx) + tudou_t0_block(step, ctx) + topology_block(step, ctx) + regime_block(step, ctx))
        tpl = templates[tpl_key(step, templates)].replace("{date_dash}", date_dash).replace("{date}", date).replace("{run_dir}", rd)
        main = a6["main"] and step in A6_MAIN_STEPS and not a6["main_broken"]
        if main and a6["msid"]:
            if fail_reason:   # 主会话内只重写那一块
                return (f"[驱动器校验 {attempt - 1}/{MAX_RETRY}] {ART[step]} 未通过: {fail_reason}。只重写 {rd}/{ART[step]} 这一个文件"
                        f"(Write 覆盖全文: 正文 + 末个 ```contract 块 + 末行只写 STEP_OK {step} {date}), 只修此问题, 其他文件不要改。"), a6["msid"], False, True
            body, used, missing = a6_attach(A6_FILES[step] + (STEP_PACK_EXTRA.get(step, []) if STEP_PACK else []), run_dir, skip=a6["mseen"])
            body += step_pack_block(step, run_dir)
            a6["pending"] = used
            head = (f"[主会话续接 CHAIN_MAIN_SESSION] 本会话前文你已完成决策链 {'/'.join(a6['mdone'])} 步(当时附的材料与你写的产物都视为已读, 不必重读)。"
                    "03 多空辩论、05 风控、盲审由独立会话完成, 其产物作为新材料附在下方。现在执行下一步(下面是该步完整模板, 照模板要求输出; "
                    "该步与前面步骤是独立任务, 以下方新材料+模板为准, 允许且应当推翻你前面步骤的判断)。\n\n")
            return head + a6_head(len(used), missing) + body + tpl + a6["tail"][step], a6["msid"], False, True
        csid, gsid = a6.get("csid"), a6.get("gsid")
        par = csid or gsid
        skip = a6.get("chain_keys", set()) if csid else set()
        body, used, missing = a6_attach(A6_FILES[step] + (STEP_PACK_EXTRA.get(step, []) if STEP_PACK else []), run_dir, skip=skip,
                                        market_body=None if csid else a6.get("market_body"))
        body += step_pack_block(step, run_dir)
        a6["pending"] = list(used) + (list(a6.get("chain_keys", ())) if csid else [])
        note = ""
        if par:
            note = (" 本会话前文的开头材料(" + ("facts.md/01_market.md/chain.md 通用规范" if gsid else "")
                    + ("; 本链 01_facts.md/rules_index.md" if csid else "") + ")同样视为已读。")
        p = (_asof_note() if ASOF else "") + a6_head(len(used), missing, note) + body + tpl + a6["tail"][step]
        if fail_reason:
            p += f"\n\n[驱动器回炉 {attempt - 1}/{MAX_RETRY}] 上次失败原因: {fail_reason}。只修此问题, 产物要求不变。"
        return p, par, bool(par), main

    def _a6_after(step, main, rc, sid):
        if not main:
            return
        if rc == 0 and sid:
            a6["msid"] = sid
            a6["mseen"] |= set(a6.get("pending") or []) | {step}
            if step not in a6["mdone"]:
                a6["mdone"].append(step)
        else:   # 主会话断了: 后续主会话步退回独立会话(全量内联), 不中止链
            print(f"WARN: 主会话 {step} 调用失败(rc={rc}), 后续主会话步退回独立会话")
            a6["main_broken"], a6["msid"] = True, None

    def _accept(step, c):
        """单步 contract 通过后的机械后处理(与原逐步路径相同)"""
        ctx["contracts"][step] = c
        if step == "07" and not dry:   # 10/21 用户批: 07 的 root_causes / lessons 按票挂到当天决策 = 反思记忆(代替原 15:50 LLM 反思), 以后 04/06 经 reflection_block 读
            try:
                n7 = _dm().reflects_from_07(PAPER_DATA / "decisions", SKILL_NAME, date_dash, c, _jl_names())
                print(f"07 → 反思记忆: {n7} 条")
            except Exception as e:  # noqa: BLE001
                print(f"WARN: 07 写反思记忆失败(不影响 07): {e}")
        if step == "02":   # 10/14 §3-A 第 8 条: 02 定了态度, 立刻按态度调总仓下限(04/05/06 的约束块与校验都用调后的)
            apply_stance(ctx)
            _write_lf(run_dir / "pos_constraints.json", json.dumps(ctx["pc"], ensure_ascii=False, indent=1))
        if step == "03j":   # 10/16 晚 保留分歧版: 分歧摘要进 pc(04/05/06 约束块 + v06 追价折扣闸) + debate.json(A/B 统计)
            debate_apply(ctx, run_dir)
        if step == "04":  # C7-①: 04 落地即拉候选票价格锚(v06 校验+盲审⑥维度消费)
            ctx["snap"] = snap_candidates(run_dir, c)
        if COMPACT and step in ("04", "05", "06"):   # 10/13 G: 人看表从 contract 机械渲染插进产物(contract 前)
            render_into(run_dir, step, c, ctx)
        for done_step in ctx["contracts"]:   # 回溯重验 01..当前(机械零 token)
            t2 = (run_dir / ART[done_step]).read_text(encoding="utf-8")
            if sentinel_ok(t2, done_step, date) is not True:
                sys.exit(f"回溯重验败: {done_step} 哨兵消失, 链中止")

    def _check(step, since):
        text, err = read_artifact(run_dir, step, since)
        if err:
            return None, err
        if sentinel_ok(text, step, date) is not True:
            return None, f"哨兵缺失/错位(末行非 STEP_OK {step} {date})"
        c, cerr = contract_of(text)
        if cerr:
            return None, cerr
        vfail = VALIDATORS[step](c, ctx)
        return (None, vfail) if vfail else (c, None)

    def _merged():
        """D: 一次调用产出 02/04/06, 逐块校验, 坏块 --resume 同会话只重写那块(≤MAX_RETRY 次)。返回已通过的步(02/04/06 的前缀); 其余调用方回落逐步"""
        ctx["snap"] = pre = snap_candidates(run_dir, {"candidates": [{"code": c} for c in presnap_codes(run_dir, ctx)]})
        msteps = [x for x in ("02", "04", "05", "06") if x in _seq[_i - 1:]]   # 10/16: 子链含 05 时四块, 否则三块
        parts = [(s, _prompt(s, asof_note=False)) for s in msteps]
        pc0 = ctx.get("pc") or {}
        if pc0.get("floor") and SKILL_NAME != "buchitudou0" and "base_floor" not in pc0:   # 10/14 晚回放发现: 合并时 04/06 约束块是态度前数字, 模型自己减半算错(取整口径不同)
            fl = {st: round(pc0["floor"] * STANCE_FACTOR[st] * 20) / 20 for st in STANCES}
            stance_note = ("\n- 今日态度系数(合并调用专用): 上面总仓下限是态度=多的原值; 以你在任务一(02)写的 stance 为准, 驱动器按下表校验(已按驱动器取整口径算好, 不要自己再算): "
                           + " / ".join(f"{st}={fl[st]:.0%} nav≈{fl[st] * pc0['nav']:.0f} 元" for st in STANCES))
        else:
            stance_note = ""
        parts = [(s, p_ + (stance_note if s in ("04", "05", "06") else "")) for s, p_ in parts]
        p_all = (_asof_note() if ASOF else "") + sub_pack_block(run_dir) + merge_prompt(parts, date, run_dir)
        since0 = time.time()
        ctx["final_attempt"] = False
        rc, usage, cost, dur = call_claude(p_all, trace=(run_dir / "tool_calls" / "sub3.jsonl", {"slot": slot, "step": "sub3", "attempt": 1}))
        log_tokens(date, slot, "sub3", 1, usage, cost, dur)
        sid = LAST_SESSION["id"]
        # 10/14 修记账: --resume 返回的 total_cost_usd = 会话累计(父+本次), 回炉行须减去上一次累计, 否则重复计(曾记 $2.28 实花 $0.19)
        try:
            sess_cum = float(cost)
        except (TypeError, ValueError):
            sess_cum = 0.0
        ok = []
        for s in msteps:
            since = since0
            c, fail = _check(s, since)
            attempt = 1
            while fail and attempt <= MAX_RETRY and sid:
                attempt += 1
                ctx["final_attempt"] = attempt == MAX_RETRY + 1
                log_retry(run_dir, date, slot, f"sub3-{s}", attempt - 1, fail)
                rp = (f"[驱动器校验 {attempt - 1}/{MAX_RETRY}] {ART[s]} 未通过: {fail}。"
                      f"只重写 {str(run_dir).replace(chr(92), '/')}/{ART[s]} 这一个文件(Write 覆盖全文: 正文 + 末个 ```contract 块 + 末行只写 STEP_OK {s} {date}), "
                      f"只修此问题, 其他文件不要改。")
                since = time.time()
                rc, usage, cost, dur = call_claude(rp, trace=(run_dir / "tool_calls" / "sub3.jsonl", {"slot": slot, "step": f"sub3-{s}", "attempt": attempt}), resume=sid)
                try:
                    cum = float(cost)
                    cost, sess_cum = round(max(0.0, cum - sess_cum), 6), cum
                except (TypeError, ValueError):
                    pass
                log_tokens(date, slot, f"sub3-{s}", attempt, usage, cost, dur)
                sid = LAST_SESSION["id"] or sid
                c, fail = _check(s, since)
            ctx["final_attempt"] = False
            if fail:
                print(f"WARN: 合并调用 {s} 块 {attempt} 次仍未过({fail}), 本步起回落逐步调用")
                return ok
            _accept(s, c)
            if s == "04":   # 04 落地重拉了候选价格锚; 并上预拉的名单/持仓锚(06 可能动名单内非 04 候选的持仓)
                ctx["snap"] = {**pre, **(ctx.get("snap") or {})}
            ok.append(s)
            print(f"step {s} ✅ (合并调用块, attempt {attempt})")
        return ok

    def _esc_kind(step):
        if step == "02" and sub and prev02 and not ctx.get("esc_round") and SKILL_NAME in ("control", "taoge"):   # 升级规则: 市况变→全链; 10/16 审计#4: 方案 A 后导师链不按桃哥市况三态升级(10/16 18 次 ESCALATE 重跑), 只对照组保留
            if norm_enum(ctx["contracts"]["02"].get("market_state"), MARKET_STATES) != norm_enum(prev02.get("market_state"), MARKET_STATES):
                print(f"ESCALATE_FULL_CHAIN {date}: 市况 {prev02.get('market_state')}→{ctx['contracts']['02'].get('market_state')}")
                return "esc02"
        if step == "06" and sub and FIX_ESC_RERUN and esc06(ctx["contracts"].get("06") or {}):
            print(f"ESCALATE_FULL_CHAIN {date}: 06 判市况变需升级({str(ctx['contracts']['06'].get('supersedes', ''))[:80]})")
            return "esc06"
        return None

    def _restore_prev(names):
        for s in names:   # 合并调用里 02 升级退出时, 模型已写但未校验的 04/06 恢复成上一版(下游不读到未校验产物)
            pf = run_dir / ART[s].replace(".md", ".prev.md")
            if pf.exists() and (run_dir / ART[s]).stat().st_mtime >= t0:
                shutil.copy(pf, run_dir / ART[s])

    def _esc_handle(kind):
        """None=无升级; esc02 原行为=exit 3; 修④开且未重跑过且时间预算够 → 存档第一轮产物, 本 slot 重跑 02→04→06 一次(返回 'rerun');
        esc06 重跑后仍升级/预算不够 → 标记 esc_exit(单照发后 exit 3)"""
        nonlocal _seq
        if not kind:
            return None
        budget = float(gate_cfg()["esc_rerun_max_elapsed_s"])
        if FIX_ESC_RERUN and not ctx.get("esc_round") and time.time() - t0 <= budget:
            d1 = run_dir / "slots" / slot / "esc_round1"
            d1.mkdir(parents=True, exist_ok=True)
            for s in ("02", "04", "05", "06"):
                f = run_dir / ART[s]
                if f.exists() and f.stat().st_mtime >= t0:
                    shutil.copy2(f, d1 / ART[s])
            what = (f"02 判市况 {prev02.get('market_state') if prev02 else '?'}→{ctx['contracts']['02'].get('market_state')}" if kind == "esc02"
                    else f"06 判市况变需升级: {str((ctx['contracts'].get('06') or {}).get('supersedes', ''))[:160]}")
            ctx["esc_round"], ctx["merge_failed"] = 1, False
            ctx["esc_note"] = (f"- [市况已重判] 本 slot 第一轮 {what}。驱动器已在本 slot 重跑 02→04→06(这就是升级后的重跑, 第一轮产物存档在 slots/{slot}/esc_round1/): "
                               "02 以当前事实重新定市况(不必迁就盘前三态); 04/05/06 在新市况下重新决策(选股仍限本导师能力圈), "
                               "仓位/去留/挂价/撤单按新市况调整; 本轮不要再 escalate")
            for s in ("02", "04", "05", "06"):
                ctx["contracts"].pop(s, None)
            if "base_floor" in (ctx.get("pc") or {}):   # 重跑的 02 可能改态度: 下限复位到态度前, 等新 02 重新 apply_stance
                ctx["pc"]["floor"] = ctx["pc"].pop("base_floor")
                ctx["pc"].pop("stance", None)
            _seq = _seq[:_i] + [x for x in ("02", "04", "05", "06") if x in steps]
            print(f"修④: ESCALATE 后本 slot 重跑 02→04→06 一次(已用 {time.time() - t0:.0f}s ≤ 预算 {budget:.0f}s)")
            return "rerun"
        if kind == "esc02":
            if SUB_MERGE:
                _restore_prev(("04", "05", "06"))
            sys.exit(3)
        ctx["esc_exit"] = True
        return "exit"

    _seq = [s for x in steps for s in EXPAND.get(x, [x])]  # 03→03b/03s/03j 拆环展开(10/4)
    _i = 0
    while _i < len(_seq):
        step = _seq[_i]
        _i += 1
        if dry:
            print(f"[dry] 跳过 claude 调用 step {step}")
            if step in ("04", "06") and reflect_on():   # 10/14: 冒烟可见回注条数(关闭=不打印, dry 输出不变)
                rb = reflection_block(step, ctx)
                print(f"[dry] 反思回注 {step}: 同票 {ctx.get('reflect_n', {}).get(step, (0, 0))[0]} 条 / 跨票 {ctx.get('reflect_n', {}).get(step, (0, 0))[1]} 条, {len(rb)} 字")
            continue
        if step == "01" and SKILL_NAME not in SHARED01_SKIP and os.environ.get("CHAIN_SHARED_01", "1") != "0":
            mt = ensure_shared_01(date, date_dash, slot)
            if mt:
                ctx["contracts"]["01"] = assemble_01(run_dir, mt, date, date_dash, slot, book, snaps)
                print("step 01 ✅ (共享市场摘要+本链账户/导师信号机械追加, 本链 0 token)")
                continue
            print("WARN: 01 共享摘要不可用, 回落本链 01 LLM 步")
        if SUB_MERGE and sub and step == "02" and _seq[_i:_i + 3] in (["04", "05", "06"], ["04", "06"]) and not ctx.get("merge_failed"):   # 10/14 晚 D
            okd = _merged()
            if not okd:
                ctx["merge_failed"] = True   # 02 块都没过: 本轮回落逐步, 从 02 重来
                _i -= 1
                continue
            _i += len(okd) - 1   # 未过的块从 _seq[_i] 起逐步补跑
            for s in okd:
                act = _esc_handle(_esc_kind(s))
                if act == "rerun":
                    break
            continue
        if step in ("03b", "03s", "03j") and no03_on():   # 10/16 晚 A/B 停 03 臂(CHAIN_NO03_SKILLS 白名单): 写说明文件, 04 只依据 01/02
            if step == "03j":
                _write_lf(run_dir / ART["03j"], f"# 03 辩论 · {date_dash} 0915\n\n> A/B 对照(停 03 臂, CHAIN_NO03_SKILLS): 本链本期不跑 03 多空辩论。"
                          "04 请只依据 01_facts.md 与 02_analysis.md 决策, 不要引用本文件。\n\nSTEP_OK 03j " + date + "\n")
            print(f"A/B 停 03 臂: 跳过 step {step}")
            continue
        if step in ("03b", "03s", "03j") and _rush(date_dash, slot, RUSH_SKIP03_AT):   # 10/15 赶工闸: 09:05 还没进 04 → 跳过辩论
            if step == "03j":
                _write_lf(run_dir / ART["03j"], f"# 03 辩论 · {date_dash} 0915\n\n> ⚠ 赶工闸: {datetime.now():%H:%M} 时 0915 链还没进 04(要在开盘前出单), "
                          "本日跳过 03 多空辩论。04 请只依据 01_facts.md 与 02_analysis.md 决策, 不要引用本文件。\n\nSTEP_OK 03j " + date + "\n")
            print(f"⚠ 赶工闸: {datetime.now():%H:%M} 跳过 step {step}")
            continue
        if step == "blind" and sub:   # 10/16 晚 A3: 子链拟人审只审新买单(只持有/只卖/观望=跳过, 省钱; 调研报告建议 7)
            if not (mimic_on() and any(a.get("op") == "买" for a in (ctx["contracts"].get("06") or {}).get("actions") or [])):
                print("子链拟人审跳过: 本时段 06 无新买单" + ("" if mimic_on() else "(对照组不跑)"))
                continue
        prompt = _prompt(step) if not (a6 and step in A6_FILES) else None
        try:  # 10/11 用户令: 盲审失败=降级照发(打【未过盲审】标), 不再整链中止; 06 用最后一版过机械校验的 contract
            fail_reason, done = None, False
            mr = 1 if _rush(date_dash, slot, RUSH_RETRY_AT) else MAX_RETRY   # 10/15 赶工闸: 09:00 起回炉上限 2→1
            for attempt in range(1, mr + 2):
                ctx["final_attempt"] = attempt == mr + 1   # 10/12: 数量类软闸末次放行(不因凑数中止链)
                if prompt is None:   # 10/14 夜 A6: 内联/共用开头/主会话(关闭时不走这里)
                    p, a6_rs, a6_fk, a6_mn = _a6_prompt(step, attempt, fail_reason)
                else:
                    p = prompt if not fail_reason else \
                        prompt + f"\n\n[驱动器回炉 {attempt - 1}/{mr}] 上次失败原因: {fail_reason}。只修此问题, 产物要求不变。"
                if fail_reason:   # 10/12: 每次回炉原因落盘(此前只在终败时打印, 02/06 约半数要回炉却查不到原因)
                    log_retry(run_dir, date, slot, step, attempt - 1, fail_reason)
                since = time.time()
                if prompt is None:
                    rc, usage, cost, dur, a6_sid = a6_call(p, (run_dir / "tool_calls" / f"{step}.jsonl", {"slot": slot, "step": step, "attempt": attempt}),
                                                           resume=a6_rs, fork=a6_fk)
                    _a6_after(step, a6_mn, rc, a6_sid)
                else:
                    rc, usage, cost, dur = call_claude(p, trace=(run_dir / "tool_calls" / f"{step}.jsonl", {"slot": slot, "step": step, "attempt": attempt}))
                log_tokens(date, slot, step, attempt, usage, cost, dur)
                text, err = read_artifact(run_dir, step, since)
                if err:
                    fail_reason = err
                    continue
                so = sentinel_ok(text, step, date)
                if step == "blind" and so == "FAIL":
                    c, _ = contract_of(text)
                    issues = (c or {}).get("issues", [])
                    if attempt > mr:
                        raise BlindDowngrade(f"盲审复审仍 FAIL: {';'.join(issues)[:300]}")
                    # 盲审 FAIL → 带意见回炉 06 一次, 再复审
                    c06, _ = contract_of((run_dir / ART["06"]).read_text(encoding="utf-8"))
                    p06 = (ASOF_NOTE.replace("{date_dash}", date_dash) if ASOF else "") + templates[tpl_key("06", templates)].replace("{date_dash}", date_dash).replace("{date}", date) \
                        .replace("{run_dir}", str(run_dir).replace("\\", "/")) + profile_block("06", ctx) + constraint_text(ctx["pc"], "06") + reflection_block("06", ctx) + fix_block("06", ctx) + ledger_block("06", ctx) + quality_block("06", ctx) + \
                        (f"\n\n[拟人审驳回] 这张单不像本导师之处: {';'.join(issues)}。按这些意见修订 06_verdict.md(不像的最好修法是不下/少下时就不下/少下)。" if mimic_on() else f"\n\n[盲审驳回] issues: {';'.join(issues)}。修订 06_verdict.md 回应这些意见。")
                    since = time.time()
                    _, u2, c2, d2 = call_claude(p06, trace=(run_dir / "tool_calls" / "06.jsonl", {"slot": slot, "step": "06", "attempt": f"blind-rej{attempt}"}))
                    log_tokens(date, slot, "06", attempt, u2, c2, d2)
                    # 回炉 06 必须重验+换约再进盲审复审(10/3 实录 bug: 旧约 emit plans=废版下单)
                    t06, e06 = read_artifact(run_dir, "06", since)
                    if e06 or sentinel_ok(t06 or "", "06", date) is not True:
                        raise BlindDowngrade(f"盲审回炉 06 产物/哨兵异常({e06 or '哨兵缺失'})")
                    c06n, cerr06 = contract_of(t06)
                    if cerr06:
                        raise BlindDowngrade(f"盲审回炉 06 contract 异常({cerr06})")
                    v06fail = VALIDATORS["06"](c06n, ctx)
                    if v06fail:
                        # C9-①(10/4): 死链修复——回炉版校验败不再直接 abort(9/29 实证: 公式价被数值校验拒→链中止无产出),
                        # 再给一次带失败原因的回炉; 仍败才中止。公式价合法性本体由 C9-② resolve_px 支持。
                        print(f"盲审回炉 06 校验败({v06fail}), 再给一次带原因回炉")
                        p06r = (ASOF_NOTE.replace("{date_dash}", date_dash) if ASOF else "") + templates[tpl_key("06", templates)].replace("{date_dash}", date_dash).replace("{date}", date) \
                            .replace("{run_dir}", str(run_dir).replace("\\", "/")) + profile_block("06", ctx) + constraint_text(ctx["pc"], "06") + reflection_block("06", ctx) + fix_block("06", ctx) + ledger_block("06", ctx) + quality_block("06", ctx) + \
                            f"\n\n[驱动器回炉] 上版 contract 校验败: {v06fail}。只修此问题, 重写 06_verdict.md。"
                        since2 = time.time()
                        _, u3, c3, d3 = call_claude(p06r, trace=(run_dir / "tool_calls" / "06.jsonl", {"slot": slot, "step": "06", "attempt": f"blind-rej{attempt}b"}))
                        log_tokens(date, slot, "06", attempt, u3, c3, d3)
                        t06b, e06b = read_artifact(run_dir, "06", since2)
                        if e06b or sentinel_ok(t06b or "", "06", date) is not True:
                            raise BlindDowngrade(f"盲审回炉 06 二版产物/哨兵异常({e06b or '哨兵缺失'})")
                        c06b, cerr06b = contract_of(t06b)
                        if cerr06b:
                            raise BlindDowngrade(f"盲审回炉 06 二版 contract 异常({cerr06b})")
                        v06fb = VALIDATORS["06"](c06b, ctx)
                        if v06fb:
                            raise BlindDowngrade(f"盲审回炉 06 二次校验仍败({v06fb})")
                        c06n = c06b
                    ctx["contracts"]["06"] = c06n
                    if COMPACT:   # 10/13 G: 盲审回炉版 06 重渲染人看表(复审读到的是新版)
                        render_into(run_dir, "06", c06n, ctx)
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
                _accept(step, c)   # 02 态度/04 价格锚/G 渲染/回溯重验 01..当前(10/14 晚抽成函数, 合并调用共用; 行为不变)
                print(f"step {step} ✅ (attempt {attempt}, {dur:.0f}s)")
                done = True
                break
            if not done:
                if step == "blind":
                    raise BlindDowngrade(f"盲审步回炉 {MAX_RETRY} 次仍败({fail_reason})")
                sys.exit(f"step {step} 回炉 {MAX_RETRY} 次仍败({fail_reason}), 链中止 exit 1")
        except BlindDowngrade as e:
            ctx["blind_fail"] = str(e)
            print(f"⚠ 盲审未通过 → 降级照发(单子标【未过盲审】): {e}")
            (run_dir / "BLIND_FAILED.txt").write_text(
                f"{datetime.now():%Y-%m-%d %H:%M} 盲审未通过, 降级照发(单子标【未过盲审】)\n原因: {e}\n", encoding="utf-8")

        _esc_handle(_esc_kind(step))   # 升级规则: 02 市况变 → exit 3(修④开: 本 slot 重跑一次); 06 escalate(仅修④开)

    # 扩池提案自动落 pools.json(10/4 用户拍板: 04 提案 v04 校验后机械 merge 零 token; 失败仅 WARN 不中止链)
    props = (ctx["contracts"].get("04") or {}).get("pool_proposals")
    if props and ASOF:
        print("as-of: 扩池提案不落 pools.json(回放不改实盘 persona 池)")
    elif props and SKILL_NAME != "taoge":   # 10/15 方案 A: pools.json 是桃哥的股票池, 只有桃哥链能扩(别的链往里加票=同质化源)
        print(f"扩池提案只收桃哥链, {SKILL_NAME} 的提案不落 pools.json")
    elif props:
        pf = run_dir / "pool_proposals.json"
        pf.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run(["node", "scripts/dfcf/paper/pool_merge.mjs", "--file", str(pf)],
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        tail = (r.stdout or "").strip().splitlines()
        print(f"pool_merge: {tail[-1] if tail else (r.stderr or '')[-200:]}")
        if r.returncode != 0:
            print("WARN: 扩池提案落 pools.json 失败(链不中止, 提案已存 run_dir/pool_proposals.json)")

    if "06" in steps:
        emit_plans(date_dash, slot, source, ctx["contracts"].get("06", {}), book,
                   (("【未过拟人审】" if mimic_on() else "【未过盲审】") if ctx.get("blind_fail") else ""))
        if reflect_on() or DECISION_LOG:   # 10/14 §3-A 第 6 条; 10/19 晚: 决策日志(零 token)与反思回注拆开 —— CHAIN_DECISION_LOG=1 全链都记, 回注仍看 CHAIN_REFLECTION
            log_decisions(date_dash, slot, source, ctx["contracts"].get("06", {}), ctx)
    print(f"链完成 {date} slot {slot} steps {'→'.join(steps)}")
    if ctx.get("esc_exit"):   # 10/14 晚 修④: 重跑后 06 仍 escalate(或时间预算不够重跑)——单照发, 出口 3 让 Java 记警告
        print(f"ESCALATE_FULL_CHAIN {date}: 本 slot {'已重跑一次仍' if ctx.get('esc_round') else '时间预算不足未重跑,'}判升级, 06 已照发, exit 3")
        sys.exit(3)

# ---------- 自测(不烧 token: 假产物喂校验器) ----------
def _selftest_subfix(ctx, ctx2, bk, pc_full, tmp):
    """10/14 晚 子链五修 + 触发闸 A + 合并 D 的用例。进入时全部开关为关, 退出时复位为关"""
    global FIX_FLOOR_EXIT, FIX_NO_DEFER, FIX_SUB_APPROVED, FIX_HOLDS
    fails = []
    sell = lambda q, **kw: {"name": "三花智控", "code": "002050", "op": "卖", "trigger_price": "12.0", "qty": q, "anchor": "12.5", **kw}
    cf = dict(ctx2, pc=pc_full, sub=True, book=bk)   # 持仓 002050 市值 5 万, 下限 40% nav=4 万
    # ---- 开关全关: 新字段/新措辞不改变任何判定(逐字节不变的单元层证明; 全链层见 scripts/temp/subfix_1014/identity_check.py)
    if fix_block("06", dict(cf, sub_allow={"approved": [], "held": [], "opens": [], "names": set(), "codes": set()})) != "":
        fails.append("开关全关时 fix_block 非空")
    if not v06({"supersedes": "取代", "actions": [sell(3000, exit_kind="stop")]}, cf):
        fails.append("修①关: 止损卖单(exit_kind=stop)应仍受下限约束")
    if v06({"supersedes": "维持: 交用户裁", "actions": []}, cf) or v02({"market_state": "普跌", "leading_layer": "资金惯性层", "directions": ["x"], "x": "待用户裁"}, ctx):
        fails.append("修②关: 交用户措辞不应回炉")
    if v06({"supersedes": "维持", "actions": []}, cf):
        fails.append("holds 关: actions 空且无 holds 不应回炉")
    if esc06({"supersedes": "06 发起 ESCALATE"}) is not True or esc06({"supersedes": "不发起 ESCALATE, 维持"}) or esc06({"escalate": True}) is not True             or esc06({"supersedes": "维持1127 06(1230档ESCALATE停跑无04/06, 本档承接1127)"}):
        fails.append("esc06 识别错")
    # ---- 修①: 下限只约束主动减仓
    FIX_FLOOR_EXIT = True
    try:
        for kind, want_ok in (("stop", True), ("protect", True), ("invalid", True), ("discretionary", False), (None, False)):
            r = v06({"supersedes": "取代", "actions": [sell(3000, **({"exit_kind": kind} if kind else {}))]}, cf)
            if bool(r) == want_ok:
                fails.append(f"修① exit_kind={kind}: 期望{'放行' if want_ok else '回炉'}, 实际 {r}")
        if not v06({"supersedes": "取代", "actions": [sell(100, exit_kind="止损")]}, cf):
            fails.append("修① exit_kind 非法值未抓")
        if not v06({"supersedes": "取代", "actions": [dict(sell(100), op="买", exit_kind="stop")]}, cf):
            fails.append("修① 买单带 exit_kind=stop 未抓")
        if not v06({"supersedes": "取代", "actions": [dict(sell(100, exit_kind="stop"), name="大亚", code="000910")]}, dict(cf, contracts={**cf["contracts"], "05": {"verdicts": []}})):
            fails.append("修① 非持仓票 exit_kind=stop 未抓")
        c05x = dict(cf, contracts={**cf["contracts"], "05": {"verdicts": []}})   # 持仓止损不受 05 批准集约束
        if v06({"supersedes": "取代", "actions": [sell(100, exit_kind="stop")]}, c05x) or not v06({"supersedes": "取代", "actions": [sell(100)]}, c05x):
            fails.append("修① 持仓止损卖单应豁免 05 批准集(主动卖仍须批准)")
        if "下限只约束**主动减仓**" not in constraint_text(pc_full, "06"):
            fails.append("修① 约束块缺主动减仓说明")
    finally:
        FIX_FLOOR_EXIT = False
    # ---- 修②: 交用户=回炉, 末次放行
    FIX_NO_DEFER = True
    try:
        for txt in ("下限冲突交用户裁", "待用户裁", "S3交用户", "用户未裁时≤100", "交由用户确认"):
            if not v06({"supersedes": f"维持 {txt}", "actions": [sell(100)]}, dict(cf, pc=None)):
                fails.append(f"修② 未抓: {txt}")
        if v06({"supersedes": "维持 用户令 10/13 已定口径", "actions": [sell(100)]}, dict(cf, pc=None)):
            fails.append("修② 误杀: '用户令' 不是推给用户")
        if v06({"supersedes": "维持 交用户裁", "actions": [sell(100)]}, dict(cf, pc=None, final_attempt=True)):
            fails.append("修② 末次尝试应放行")
        d2 = dict(cf, pc=None)
        if not v06({"supersedes": "维持 交用户裁", "actions": [sell(100)]}, d2) or v06({"supersedes": "维持 交用户裁", "actions": [sell(100)]}, d2):
            fails.append("修② 同步第二次应放行(每步最多回炉一次)")
        if not v02({"market_state": "普跌", "leading_layer": "资金惯性层", "directions": ["x"], "note": "待用户裁"}, ctx) \
                or not v04({"candidates": [{"name": "三花智控", "direction": "机器人", "group": "方向", "trigger": "交用户定"}], "断链说明": None}, ctx):
            fails.append("修② v02/v04 未抓交用户")
        if "没有用户" not in fix_block("02", ctx):
            fails.append("修② 02 提示块缺")
    finally:
        FIX_NO_DEFER = False
    # ---- 修⑤: 子链 04 候选 ⊆ 0915-05 批准∪持仓∪挂单
    FIX_SUB_APPROVED = True
    try:
        allow = {"approved": [("三花智控", "002050", "批准", "")], "held": ["000910"], "opens": [], "names": {"三花智控", "大亚"}, "codes": {"002050", "000910"}}
        sc = dict(ctx, sub=True, sub_allow=allow)
        ok4 = {"candidates": [{"name": "三花智控", "direction": "机器人", "group": "方向", "trigger": "1"},
                              {"name": "大亚(别名)", "code": "000910", "group": "遗留", "trigger": "1"}], "断链说明": None}
        bad4 = {"candidates": ok4["candidates"] + [{"name": "上海电影", "code": "601595", "direction": "机器人", "group": "方向", "trigger": "1"}], "断链说明": None}
        if v04(ok4, sc) or not v04(bad4, sc) or v04(dict(ok4), dict(ctx, sub_allow=allow)):
            fails.append("修⑤ v04 名单闸错(合法误杀/名单外未抓/盘前误拦)")
        b2 = json.loads(json.dumps(bad4))
        if v04(b2, dict(sc, final_attempt=True)) or [x["name"] for x in b2["candidates"]] != ["三花智控", "大亚(别名)"]:
            fails.append("修⑤ 末次应机械剔除名单外候选")
        fb = fix_block("04", sc)
        if "0915-05 批准名单: 三花智控(002050)[批准]" not in fb or "现有持仓: 000910" not in fb:
            fails.append(f"修⑤ 04 提示块缺名单: {fb[:200]}")
        # sub_allow_list 从 slots/0915 取
        sd = tmp / "slots" / "0915"
        sd.mkdir(parents=True, exist_ok=True)
        (sd / ART["05"]).write_text("x\n```contract\n" + json.dumps({"verdicts": [{"name": "三花智控", "result": "条件批准", "reason": "r"}, {"name": "X", "result": "否决"}]}, ensure_ascii=False) + "\n```\nSTEP_OK 05 20260930\n", encoding="utf-8")
        (sd / ART["04"]).write_text("x\n```contract\n" + json.dumps({"candidates": [{"name": "三花智控", "code": "002050"}]}, ensure_ascii=False) + "\n```\nSTEP_OK 04 20260930\n", encoding="utf-8")
        al = sub_allow_list(tmp, dict(ctx, book=bk), {"002050": {"name": "三花智控"}, "000910": {"name": "大亚"}})
        if not al or al["approved"] != [("三花智控", "002050", "条件批准", "r")] or al["codes"] != {"002050", "000910"} or "大亚" not in al["names"]:
            fails.append(f"修⑤ sub_allow_list 错: {al}")
    finally:
        FIX_SUB_APPROVED = False
    # ---- holds: actions 空必须 holds 或 no_trade_reason
    FIX_HOLDS = True
    try:
        e = dict(cf, pc=None)
        E = lambda **kw: dict(e, **kw)   # 每次新 ctx(软闸按 ctx 记"已回炉过一次")
        e2 = E()
        if not v06({"supersedes": "维持", "actions": []}, E()) or v06({"supersedes": "维持", "actions": [], "no_trade_reason": "无触发"}, E()) \
                or v06({"supersedes": "维持", "actions": [], "holds": [{"order_id": "x-1", "why": "挂单仍有效"}]}, E()) \
                or not v06({"supersedes": "维持", "actions": [], "holds": [{"why": "缺 id"}]}, E()) \
                or v06({"supersedes": "维持", "actions": []}, E(final_attempt=True)) \
                or not v06({"supersedes": "维持", "actions": []}, e2) or v06({"supersedes": "维持", "actions": []}, e2):
            fails.append("holds 校验错(缺省未抓/合法误杀/格式未抓/末次未放行/第二次未放行)")
        if "holds" not in fix_block("06", e):
            fails.append("holds 06 提示块缺")
    finally:
        FIX_HOLDS = False
    fails += _selftest_gate(tmp)
    fails += _selftest_minirun(tmp)
    return fails


def _selftest_gate(tmp):
    """触发闸 A 的 a~e 五条件 + fail-open + 跳过产物"""
    global FIX_HOLDS
    fails = []
    rd = tmp / "gate_rd"
    shutil.rmtree(rd, ignore_errors=True)
    (rd / "slots" / "1030").mkdir(parents=True)
    sb = tmp / "gate_sb"
    for s in ("1030", "1100"):
        (sb / "facts" / "2026-09-30" / s).mkdir(parents=True, exist_ok=True)
    w = lambda s, px, tg="": ((sb / "facts" / "2026-09-30" / s / "facts.json").write_text(json.dumps({"watch": [{"code": "002050", "name": "三花智控", "last": px}]}), encoding="utf-8"),
                             (sb / "facts" / "2026-09-30" / s / "facts.md").write_text(f"## 新到电报(自上一 slot)\n{tg}\n## 关注票实时快照\n", encoding="utf-8"))
    w("1030", 12.50)
    (rd / "run_meta.jsonl").write_text(json.dumps({"slot": "0915", "ts": "2026-09-30T08:00:00"}) + "\n"
                                       + json.dumps({"slot": "1030", "ts": "2026-09-30T10:30:00"}) + "\n", encoding="utf-8")
    (rd / "slots" / "1030" / ART["06"]).write_text("x", encoding="utf-8")
    (rd / "slots" / "1030" / "gate.json").write_text(json.dumps({"prices": {"002050": 12.50}, "idx": {"sh000001": 3800.0, "sz399006": 3000.0}}), encoding="utf-8")
    (rd / ART["02"]).write_text("x\n```contract\n" + json.dumps({"directions": ["机器人(热点中)", "PCB/元件"]}, ensure_ascii=False) + "\n```\n", encoding="utf-8")
    book = {"positions": {"002050": {"qty": 100, "cost": 12}}, "orders": [], "chain": []}
    idx = lambda a, b: {"sh000001": (a, None), "sz399006": (b, None)}
    case = lambda slot="1100", px=12.55, ix=(3810.0, 3010.0), tg="", bk=book: (
        w(slot, px, tg), gate_decide(rd, "2026-09-30", slot, bk, paper_data=sb, minute_src=True, now_px=idx(*ix)))[1]
    go, why, met, gj = case()
    if go or why:
        fails.append(f"闸: 无触发应跳过, 实际 {why}")
    if gj["prices"].get("002050") != 12.55 or gj["idx"].get("sh000001") != 3810.0:
        fails.append(f"闸: gate.json 取数错 {gj}")
    for tag, kw, key in (("b 价格 +1.6%", {"px": 12.70}, "b "), ("c 创业板 +0.9pt", {"ix": (3800.0, 3027.0)}, "c "),
                         ("d 电报命中持仓名", {"tg": "- [10:40] [三花智控公告中标]"}, "d "), ("d 电报命中方向词", {"tg": "- [10:40] [PCB 板块拉升]"}, "d "),
                         ("e 强制 slot", {"slot": "1455"}, "e ")):
        if kw.get("slot"):
            (sb / "facts" / "2026-09-30" / kw["slot"]).mkdir(parents=True, exist_ok=True)
        go, why, *_ = case(**kw)
        if not go or not any(r.startswith(key) for r in why):
            fails.append(f"闸 {tag} 未触发: {why}")
    go, why, *_ = case(tg="- [10:40] [欧盟央行利率决议]")
    if go:
        fails.append(f"闸: 无关电报不应触发: {why}")
    ev = {"positions": book["positions"], "orders": [{"id": "o1", "side": "BUY", "price": 12.0, "cond": {"cancel_below": 13.5}},
                                                     {"id": "o2", "side": "BUY", "price": 12.0, "cond": {"cancel_below": 11.5}}],
          "chain": [{"at": "2026-09-30T03:00:00.000Z", "why": "挂单 BUY 002050@12x100"},
                    {"at": "2026-09-30T03:00:01.000Z", "why": "失效撤单 o1"}]}   # 03:00Z=11:00 本地(UTC+8)
    go, why, *_ = case(bk=ev)
    if go:
        fails.append(f"闸 a: 挂单/撤单工具单自失效不应触发: {why}")
    ev["chain"].append({"at": "2026-09-30T03:01:00.000Z", "why": "失效撤单 o2"})
    go, why, *_ = case(bk=ev)
    if not go or not any(r.startswith("a ") for r in why):
        fails.append(f"闸 a: 真失效撤单未触发: {why}")
    # fail-open: 指数取数缺失 / 上一 slot 无 06 / 无上一已跑 slot
    w("1100", 12.55)
    g1 = gate_decide(rd, "2026-09-30", "1100", book, paper_data=sb, minute_src=True, now_px={})
    (rd / "slots" / "1030" / ART["06"]).unlink()
    g2 = case()
    g3 = gate_decide(rd, "2026-09-30", "0930", book, paper_data=sb, minute_src=True, now_px=idx(3810.0, 3010.0))
    if not (g1[0] and g2[0] and g3[0]):
        fails.append(f"闸 fail-open 错: 指数缺={g1[1]} / 上 slot 无 06={g2[1]} / 无上 slot={g3[1]}")
    # 跳过产物: 哨兵/contract/holds 合 06 契约, v06(子链, holds 开) 能过
    (rd / ART["06"]).write_text("x\n```contract\n" + json.dumps({"supersedes": "取代", "actions": [{"name": "三花智控"}]}, ensure_ascii=False) + "\n```\nSTEP_OK 06 20260930\n", encoding="utf-8")
    c = write_gate_skip(rd, "20260930", "2026-09-30", "1100", {"orders": [{"id": "o9", "code": "002050", "status": "open"}]}, "1030", {"moves": {"002050": (0.4, 1.5)}})
    t = (rd / ART["06"]).read_text(encoding="utf-8")
    FIX_HOLDS = True
    try:
        vbad = v06(contract_of(t)[0], {"date_dash": "2026-09-30", "nav": 1e5, "sub": True, "contracts": {}, "skill": SKILL_CFG["taoge"]})
    finally:
        FIX_HOLDS = False
    if sentinel_ok(t, "06", "20260930") is not True or contract_of(t)[0] != c or c["holds"][0]["order_id"] != "o9" or vbad or "```json" not in t:
        fails.append(f"闸跳过产物不合 06 契约: {vbad}")
    shutil.rmtree(rd, ignore_errors=True)
    shutil.rmtree(sb, ignore_errors=True)
    return fails


def _selftest_a6(tmp):
    """10/14 夜 §3-A6 单元层: 关=命令行不变 / fork 参数 / 附件去重+省略 01 市场正文 / resume 成本扣父会话累计(全链层见 scripts/temp/a6_1014/identity_check.py)"""
    fails = []
    if INLINE_CTX or SHARED_PREFIX or MAIN_SESSION:
        fails.append("A6 开关自测须从全关基线起")
    seen = []
    orig_run, orig_slot, orig_log = subprocess.run, _acquire_slot, rotation.log_use
    rotation.log_use = lambda tag: None
    js = '{"type":"result","is_error":false,"result":"ok","session_id":"S2","usage":{"output_tokens":5},"total_cost_usd":0.75}'
    subprocess.run = lambda args, **k: (seen.append(list(args)), type("R", (), {"returncode": 0, "stdout": js, "stderr": ""})())[1]
    globals()["_acquire_slot"] = lambda: tmp / "slot.fake"
    try:
        call_claude("p")
        call_claude("p", resume="S1")
        call_claude("p", resume="S1", fork=True)
        SESSION_COST["S1"] = 0.5
        r = a6_call("p", None, resume="S1", fork=True)
    finally:
        subprocess.run, rotation.log_use = orig_run, orig_log
        globals()["_acquire_slot"] = orig_slot
        SESSION_COST.clear()
    cl = [s for s in seen if s and s[0] == CLAUDE[0]]
    if cl[0][:len(CLAUDE)] != CLAUDE or "--resume" in cl[0] or cl[1][-4:-2] != ["--resume", "S1"] or "--fork-session" in cl[1] \
            or "--fork-session" not in cl[2] or r[2] != 0.25 or r[4] != "S2":
        fails.append(f"A6 fork 命令行/成本扣父会话累计错: {[c[len(CLAUDE):len(CLAUDE) + 3] for c in cl]} cost={r[2]}")
    rd = tmp / "a6rd"
    rd.mkdir(exist_ok=True)
    mb = "市场正文" * 100
    (rd / ART["01"]).write_text(f"# 01\n## 一、市场事实\n{mb}\n## 二、本链账户\nx\n", encoding="utf-8")
    (rd / ART["02"]).write_text("02 正文", encoding="utf-8")
    body, used, missing = a6_attach(["01", "02", "01", "@cs"], rd, skip=("02",), market_body=mb)
    if used != ["01"] or body.count("<file ") != 1 or mb in body or "此处省略不重复" not in body or not missing:
        fails.append(f"A6 附件去重/跳过/省略/缺失列表错: used={used} missing={missing}")
    return fails


def _selftest_minirun(tmp):
    """假 claude 跑 run_chain 子链(as-of 沙盒, 不碰实盘): 修④ 重跑 / 06 escalate / 合并 D(含 --resume 坏块重写) / 触发闸跳过 / 开关关原行为"""
    global FIX_ESC_RERUN, SUB_MERGE, SUB_GATE, PAPER_DATA, PAPER, ASOF, TOKEN_LOG
    import tempfile
    fails = []
    D, DD = "20260930", "2026-09-30"
    sb = Path(tempfile.mkdtemp(prefix="selftest_sub_"))
    (sb / "books").mkdir()
    (sb / "facts" / DD / "1030").mkdir(parents=True)
    (sb / "books" / "A-taoge.json").write_text(json.dumps({"source": "A-taoge", "cash": 100000, "positions": {}, "orders": [], "nav": [{"nav": 100000}], "chain": []}), encoding="utf-8")
    (sb / "facts" / DD / "1030" / "facts.md").write_text("# facts\n## 新到电报(自上一 slot)\n(无)\n", encoding="utf-8")
    (sb / "facts" / DD / "1030" / "facts.json").write_text(json.dumps({"watch": []}), encoding="utf-8")
    os.environ["CHAIN_RUN_TAG"] = "selftest-sub"
    rd = ROOT / "results" / RESULTS_DIR / f"asof-{D}-selftest-sub"
    saved = (PAPER_DATA, PAPER, ASOF, TOKEN_LOG, call_claude, snap_candidates, subprocess.run)
    calls = []
    scen = {}

    def mk(step, c):
        _write_lf(rd / ART[step], f"# {step}\n```contract\n{json.dumps(c, ensure_ascii=False)}\n```\nSTEP_OK {step} {D}\n")

    def seed():
        shutil.rmtree(rd, ignore_errors=True)
        (rd / "slots" / "0915").mkdir(parents=True)
        mk("01", {"date": DD, "sources": ["f"], "digest": "d"})
        mk("02", {"market_state": "有主线", "leading_layer": "板块层", "directions": ["机器人"]})
        for s in ("03b", "03s", "03j"):
            (rd / ART[s]).write_text(f"x\nSTEP_OK {s} {D}\n", encoding="utf-8")
        mk("04", {"candidates": [{"name": "三花智控", "code": "002050", "direction": "机器人", "group": "方向", "trigger": "1"}], "断链说明": None})
        mk("05", {"verdicts": [{"name": "三花智控", "result": "批准", "reason": "r"}]})
        mk("06", {"supersedes": "首裁", "actions": [], "no_trade": False})
        for s in ("04", "05", "06"):
            shutil.copy(rd / ART[s], rd / "slots" / "0915" / ART[s])
        (rd / "run_meta.jsonl").write_text(json.dumps({"slot": "0915", "ts": f"{DD}T08:00:00"}) + "\n", encoding="utf-8")
        calls.clear()

    def fake(prompt, trace=None, resume=None):
        calls.append((prompt, resume))
        time.sleep(0.03)
        if resume:
            steps_ = [k for k, v in ART.items() if f"/{v} 这一个文件" in prompt]
        else:
            steps_ = re.findall(rf"末行只写：STEP_OK (\w+) {D}", prompt)
        for s in steps_:
            q = scen.get(s) or []
            c = q.pop(0) if len(q) > 1 else (q[0] if q else {})
            mk(s, c)
        LAST_SESSION["id"] = f"sess{len(calls)}"
        return 0, {"input_tokens": 1, "output_tokens": 1}, "0.01", 0.1

    ok02 = {"market_state": "有主线", "leading_layer": "板块层", "directions": ["机器人"]}
    chg02 = {"market_state": "普跌", "leading_layer": "资金惯性层", "directions": ["机器人"]}
    ok04 = {"candidates": [{"name": "三花智控", "code": "002050", "direction": "机器人", "group": "方向", "trigger": "1"}], "断链说明": None}
    ok06 = {"supersedes": "维持盘前", "actions": [], "no_trade": False}
    esc6 = {"supersedes": "维持盘前; 市况变 06 发起 ESCALATE", "actions": [], "no_trade": False, "escalate": True}

    def run(**flags):
        global FIX_ESC_RERUN, SUB_MERGE, SUB_GATE
        FIX_ESC_RERUN, SUB_MERGE, SUB_GATE = flags.get("esc", False), flags.get("merge", False), flags.get("gate", False)
        (rd / ".chain.lock").unlink(missing_ok=True)
        try:
            run_chain(D, DD, "1030", SLOT_STEPS["1030"] if flags.get("gate") else flags.get("steps", ["02", "04", "06"]), "A-taoge")   # 10/16: 排程子链=02/04/05/06(闸只管排程内), 其余用例沿用三步
            code = 0
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
        finally:
            FIX_ESC_RERUN = SUB_MERGE = SUB_GATE = False
            (rd / ".chain.lock").unlink(missing_ok=True)
        return code

    try:
        PAPER_DATA = PAPER = sb
        ASOF, TOKEN_LOG = DD, sb / "tok.csv"
        globals()["call_claude"] = fake
        globals()["snap_candidates"] = lambda run_dir, c: {"002050": {"prevClose": 12.6}}
        orig_run = subprocess.run
        subprocess.run = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "JSON:{}\n", "stderr": ""})()
        # 1) 修④关: 02 市况变 → exit 3, 只 1 次调用(原行为)
        seed(); scen.update({"02": [chg02], "04": [ok04], "06": [ok06]})
        if run() != 3 or len(calls) != 1:
            fails.append(f"修④关: 02 市况变应 1 次调用后 exit 3, 实际 {len(calls)} 次")
        # 2) 修④开: 02 市况变 → 本 slot 重跑 02→04→06 → exit 0, 共 4 次; 第一轮存档; 重跑 prompt 带'市况已重判'
        seed(); scen.update({"02": [chg02], "04": [ok04], "06": [ok06]})
        rc = run(esc=True)
        if rc != 0 or len(calls) != 4 or "市况已重判" not in calls[1][0] or not (rd / "slots" / "1030" / "esc_round1" / ART["02"]).exists():
            fails.append(f"修④开 02 升级重跑错: rc={rc} 调用 {len(calls)} 次")
        # 3) 修④开: 06 两轮都 escalate → 重跑一次后照发+exit 3, 共 6 次
        seed(); scen.update({"02": [ok02], "04": [ok04], "06": [esc6]})
        rc = run(esc=True)
        if rc != 3 or len(calls) != 6:
            fails.append(f"修④开 06 两轮 escalate 应 6 次调用后 exit 3, 实际 rc={rc} {len(calls)} 次")
        # 4) 合并 D: 一次调用三块; 04 坏块 → --resume 只重写 04 → 共 2 次; 产物仍落 02/04/06
        seed(); scen.update({"02": [ok02], "04": [{"candidates": [], "断链说明": None}, ok04], "06": [ok06]})
        rc = run(merge=True)
        if rc != 0 or len(calls) != 2 or calls[1][1] != "sess1" or "04_plan.md 这一个文件" not in calls[1][0] or "任务三" not in calls[0][0] \
                or contract_of((rd / ART["04"]).read_text(encoding="utf-8"))[0] != ok04:
            fails.append(f"合并 D 错: rc={rc} 调用 {len(calls)} 次 resume={[c[1] for c in calls]}")
        # 5) 合并 D + 02 块重写也过不了 → 回落逐步(02→04→06 各一次)
        seed(); scen.update({"02": [{"market_state": "震荡"}] * 3 + [ok02], "04": [ok04], "06": [ok06]})
        rc = run(merge=True)
        if rc != 0 or len(calls) != 6 or calls[3][1] is not None:
            fails.append(f"合并 D 02 块失败回落逐步错: rc={rc} 调用 {len(calls)} 次")
        # 6) 合并 D + 修④: 02 市况变 → 合并重跑一次 → 共 2 次
        seed(); scen.update({"02": [chg02], "04": [ok04], "06": [ok06]})
        rc = run(merge=True, esc=True)
        if rc != 0 or len(calls) != 2 or "市况已重判" not in calls[1][0]:
            fails.append(f"合并 D+修④ 错: rc={rc} 调用 {len(calls)} 次")
        # 7) 触发闸: 上一已跑 0915, 无持仓/无候选价/指数不变/无电报 → 跳过, 0 调用, 写 06 维持产物 + run_meta skipped
        seed(); scen.update({"02": [ok02], "04": [ok04], "06": [ok06]})
        orig_mp = globals()["_minute_px"]
        globals()["_minute_px"] = lambda d, s, syms: {i: 3000.0 for i in syms if i in GATE_IDX}
        try:
            rc = run(gate=True)
        finally:
            globals()["_minute_px"] = orig_mp
        t6 = (rd / ART["06"]).read_text(encoding="utf-8")
        last_meta = json.loads((rd / "run_meta.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        if rc != 0 or calls or not (contract_of(t6)[0] or {}).get("gate_skipped") or not last_meta.get("skipped") \
                or not (rd / "slots" / "1030" / "gate.json").exists():
            fails.append(f"触发闸跳过错: rc={rc} 调用 {len(calls)} 次 meta={last_meta}")
        if _last_ran(rd, "1100") != ("0915", f"{DD}T08:00:00"):
            fails.append("闸跳过的 slot 不应成为下个 slot 的基线")
        # 8) 10/16 子链含 05: 合并调用四块(02/04/05/06)一次过 → 1 次调用, prompt 含"任务四", 05 产物落地; 名单闸关时新票不被 04 拦
        seed(); scen.update({"02": [ok02], "04": [ok04], "05": [{"verdicts": [{"name": "三花智控", "result": "批准", "reason": "r"}]}], "06": [ok06]})
        rc = run(merge=True, steps=["02", "04", "05", "06"])
        if rc != 0 or len(calls) != 1 or "任务四" not in calls[0][0] or "决策链 05" not in calls[0][0] or not (rd / ART["05"]).exists():
            fails.append(f"子链含 05 合并四块错: rc={rc} 调用 {len(calls)} 次")
    finally:
        PAPER_DATA, PAPER, ASOF, TOKEN_LOG = saved[:4]
        globals()["call_claude"], globals()["snap_candidates"] = saved[4], saved[5]
        subprocess.run = saved[6]
        FIX_ESC_RERUN = SUB_MERGE = SUB_GATE = False
        os.environ.pop("CHAIN_RUN_TAG", None)
        shutil.rmtree(rd, ignore_errors=True)
        shutil.rmtree(sb, ignore_errors=True)
    return fails


def _selftest_reflect_trigger():
    """二B-6: 关=reflection_block 逐字节同旧(含 CHAIN_REFLECTION 开时) / 开=只注入运行日前最近一份里本链 inject / 未触发·05·过期·当日文件=不注入"""
    global REFLECT_TRIGGER, REFLECT_TRIGGER_DIR, REFLECT, PAPER, PAPER_DATA
    import tempfile
    f = []
    o_trig, o_dir, o_refl, o_paper, o_data = REFLECT_TRIGGER, REFLECT_TRIGGER_DIR, REFLECT, PAPER, PAPER_DATA
    o_env = {k: os.environ.pop(k, None) for k in ("CHAIN_REFLECTION", "CHAIN_REFLECTION_SKILLS")}
    td = Path(tempfile.mkdtemp(prefix="selftest_rtrig_"))
    try:
        REFLECT_TRIGGER_DIR = td
        inj = "\n\n## 偏离触发提示（自测）\n- 触发1 交不交易·多动\n  本日执行参数: 本日默认不开新仓"
        mkf = lambda d, chains: (td / f"{d}.json").write_text(json.dumps({"date": d, "chains": chains}, ensure_ascii=False), encoding="utf-8")  # noqa: E731
        mkf("2026-10-14", {"a658": {"triggered": True, "inject": "旧一份", "triggers": [{"key": "仓位·偏轻"}]}})
        mkf("2026-10-15", {"a658": {"triggered": True, "inject": inj, "triggers": [{"key": "交不交易·多动"}]},
                           "liuyiqing": {"triggered": False, "inject": ""}})
        mkf("2026-10-16", {"a658": {"triggered": True, "inject": "当日文件=偷看未来", "triggers": []}})
        mkf("2026-09-20", {"a658": {"triggered": True, "inject": "过期", "triggers": []}})
        cx = lambda d="2026-10-16": {"date_dash": d, "sub": False, "contracts": {}, "book": {"positions": {}, "orders": []}}  # noqa: E731
        apply_skill("a658")
        # 关: 两个反思开关全关 / 只开已结算反思 两种基线下, 结果与旧函数逐字节一致
        REFLECT_TRIGGER = False
        for st in ("02", "04", "05", "06", "07"):
            if reflection_block(st, cx()) != _reflection_block_v1(st, cx()) or reflection_block(st, cx()) != "":
                f.append(f"偏离触发: 开关关时 reflection_block({st}) 与旧版不一致")
        PAPER = PAPER_DATA = Path(tempfile.mkdtemp(prefix="selftest_rtrig_dm_"))
        REFLECT = True
        os.environ["CHAIN_REFLECTION"], os.environ["CHAIN_REFLECTION_SKILLS"] = "1", "*"
        dm = _dm()
        rec = dm.records_from_contract({"actions": [{"name": "票", "code": "002050", "op": "买", "trigger_price": "10", "qty": 100, "anchor": "10"}]},
                                       skill="a658", source="A-a658", date="2026-10-12", slot="0915", sub=False, blind_fail=False, asof=False, ts="2026-10-12T09:15:00")
        dm.write_decisions(PAPER_DATA / "decisions", "a658", rec)
        dm.append_reflects(PAPER_DATA / "decisions", "a658", [{"id": rec[0]["id"], "resolved": "2026-10-13", "text": "已结算反思X", "guard": "ok"}])
        c1 = dict(cx(), book={"positions": {"002050": {"qty": 100}}, "orders": []})
        old = _reflection_block_v1("04", dict(c1))
        if "已结算反思X" not in old or reflection_block("04", dict(c1)) != old:
            f.append("偏离触发: 开关关+CHAIN_REFLECTION 开时 reflection_block 与旧版不一致")
        # 开
        REFLECT_TRIGGER = True
        c2 = dict(c1)
        b = reflection_block("04", c2)
        if b != old + inj or c2.get("reflect_trigger", {}).get("04", {}).get("src") != "2026-10-15.json":
            f.append(f"偏离触发: 开时应=已结算反思+运行日前最近一份 inject(不读当日文件): {b[-80:]!r}")
        if reflection_block("06", dict(cx())) != _reflection_block_v1("06", dict(cx())) + inj or trigger_block("05", cx()) or trigger_block("02", cx()) or trigger_block("07", cx()):
            f.append("偏离触发: 06 应注入 / 04·06 以外不应注入")
        if trigger_block("04", cx("2026-10-15")) != "旧一份":
            f.append("偏离触发: as-of 运行日 10-15 应取 10-14 那份")
        if trigger_block("04", cx("2026-10-09")):
            f.append("偏离触发: 运行日前 stale_days 内无文件(只有过期的 09-20)应不注入")
        apply_skill("liuyiqing")
        if trigger_block("04", cx()) or trigger_block("06", cx()):
            f.append("偏离触发: 本链未触发应不注入")
        apply_skill("control")
        if trigger_block("04", cx()):
            f.append("偏离触发: 文件里没有本链应不注入")
        (td / "2026-10-15.json").write_text("{坏json", encoding="utf-8")
        apply_skill("a658")
        if trigger_block("04", cx()):
            f.append("偏离触发: 文件损坏应 fail-open 为空串")
        memo = cx()
        mkf("2026-10-15", {"a658": {"triggered": True, "inject": inj, "triggers": []}})
        first = trigger_block("04", memo)
        mkf("2026-10-15", {"a658": {"triggered": True, "inject": "中途改了", "triggers": []}})
        if trigger_block("04", memo) != first:
            f.append("偏离触发: 同一 ctx 回炉应沿用首次结果")
    finally:
        shutil.rmtree(td, ignore_errors=True)
        if PAPER_DATA != o_data:
            shutil.rmtree(PAPER_DATA, ignore_errors=True)
        REFLECT_TRIGGER, REFLECT_TRIGGER_DIR, REFLECT, PAPER, PAPER_DATA = o_trig, o_dir, o_refl, o_paper, o_data
        os.environ.pop("CHAIN_REFLECTION", None); os.environ.pop("CHAIN_REFLECTION_SKILLS", None)
        for k, v in o_env.items():
            if v is not None:
                os.environ[k] = v
        apply_skill("taoge")
    return f


def _selftest_verbs(tmp):
    """10/16 审计#2/#12: 06 新动词 开盘卖/撤单/not_before——旧契约不变 + 新字段校验 + plans 行口径"""
    global PAPER_DATA
    import copy, tempfile
    fails = []
    bk = {"source": "A-taoge", "cash": 50000, "positions": {"002050": {"qty": 1000, "cost": 12.0}, "600519": {"qty": 100, "cost": 1500}},
          "orders": [{"id": "2026-09-30-A-taoge-001", "code": "002050", "side": "BUY", "status": "open", "price": 12.0, "qty": 100},
                     {"id": "2026-09-30-A-taoge-002", "code": "002050", "side": "SELL", "status": "open", "price": 13.0, "qty": 100},
                     {"id": "2026-09-30-A-taoge-003", "code": "600127", "side": "BUY", "status": "filled", "price": 9.0, "qty": 100}]}
    vctx = lambda: {"date_dash": "2026-09-30", "nav": 100000, "sub": False, "skill": SKILL_CFG["taoge"], "book": copy.deepcopy(bk),
                    "snap": {"002050": {"prevClose": 12.5}, "600519": {"prevClose": 1500.0}},
                    "contracts": {"05": {"verdicts": [{"name": "三花智控", "result": "批准"}, {"name": "贵州茅台", "result": "批准"}]}}}
    C = lambda *acts: {"supersedes": "首裁", "actions": [dict(a) for a in acts], "no_trade": False}
    buy = {"name": "三花智控", "code": "002050", "op": "买", "trigger_price": "12.3", "qty": 800, "anchor": "12.4"}
    osell = {"name": "贵州茅台", "code": "600519", "op": "开盘卖", "qty": 100, "anchor": "1500"}
    # ① 旧契约: v06 不新增任何内部字段(_nb/_cxl), op 不被改写
    c = C(buy, dict(buy, op="卖", trigger_price="12.8", stop_below=12.0))
    if v06(c, vctx()) or any(k in a for a in c["actions"] for k in ("_nb", "_cxl")) or [a["op"] for a in c["actions"]] != ["买", "卖"]:
        fails.append("新动词: 旧契约 v06 行为变了(误杀或多出 _nb/_cxl)")
    # ② 开盘卖 正例(+英文别名归一), 挂价列=anchor
    c = C(osell, dict(osell, name="三花智控", code="002050", op="market_open_sell", anchor="12.5", qty=500))
    if v06(c, vctx()) or c["actions"][0].get("_px") != 1500.0 or c["actions"][1]["op"] != "开盘卖":
        fails.append(f"新动词: 开盘卖正例被误杀/别名未归一/_px 错: {c['actions']}")
    for bad, tag in [(dict(osell, code="600127", name="三花智控"), "开盘卖非持仓未抓"),
                     (dict(osell, stop_below=1400.0), "开盘卖带 stop_below 未抓"),
                     (dict(osell, anchor=None), "开盘卖缺 anchor 未抓"),
                     (dict(osell, anchor="3000"), "开盘卖 anchor 出板限区间未抓")]:
        if not v06(C(bad), vctx()):
            fails.append("新动词: " + tag)
    # ③ not_before 规范化 + 非法值
    # ②b 10/18 竞价T: 股票 / 盘中子链 / 带 cancel_below 一律回炉(正例=转债 0915 单, 在 cb 链 + matcher 回放里验)
    for bad, kw, tag in [(dict(buy, op="竞价T"), {}, "竞价T 用于股票未抓"), (dict(buy, op="auction_t", code="113618"), {"sub": True}, "竞价T 盘中子链未抓"),
                         (dict(buy, op="竞价T", code="113618", cancel_below=100.0), {}, "竞价T 带 cancel_below 未抓")]:
        e = v06(C(bad), dict(vctx(), **kw))
        if not e or "竞价T" not in e:
            fails.append(f"新动词: {tag}: {e}")
    for raw, want in (("13:30", "13:30"), ("1330", "13:30"), ("9:45", "09:45"), ("14:59", "14:59")):
        c = C(dict(buy, not_before=raw))
        if v06(c, vctx()) or c["actions"][0].get("_nb") != want:
            fails.append(f"新动词: not_before {raw} 应规范为 {want}, 得 {c['actions'][0].get('_nb')}")
    for raw in ("09:00", "15:00", "25:00", "13:61", "下午", ""):
        if not v06(C(dict(buy, not_before=raw)), vctx()):
            fails.append(f"新动词: not_before 非法值 {raw!r} 未抓")
    # ④ 撤单: order_id / code+side 解析; 找不到=放行不落行; 缺参/代码不符/带 not_before=回炉; 不受 05 批准集约束
    c = C({"op": "撤单", "order_id": "2026-09-30-A-taoge-002"}, {"op": "撤单", "code": "002050", "side": "买"},
          {"op": "撤单", "order_id": "2026-09-30-A-taoge-003"}, {"op": "cancel", "code": "000001", "side": "卖"})
    if v06(c, vctx()) or [(a.get("_cxl") or {}).get("id") for a in c["actions"]] != ["2026-09-30-A-taoge-002", "2026-09-30-A-taoge-001", None, None] \
            or c["actions"][3]["op"] != "撤单":
        fails.append(f"新动词: 撤单解析错: {[a.get('_cxl') for a in c['actions']]}")
    for bad, tag in [({"op": "撤单"}, "撤单缺目标未抓"), ({"op": "撤单", "code": "002050"}, "撤单缺 side 未抓"),
                     ({"op": "撤单", "order_id": "2026-09-30-A-taoge-001", "code": "600519"}, "撤单 order_id/code 不符未抓"),
                     ({"op": "撤单", "order_id": "2026-09-30-A-taoge-001", "not_before": "13:00"}, "撤单带 not_before 未抓"),
                     ({"op": "撤单", "order_id": "x|y"}, "撤单 order_id 含非法字符未抓")]:
        if not v06(C(bad), vctx()):
            fails.append("新动词: " + tag)
    # ⑤ 总仓口径: 撤掉的买单不再计入未成交买单(下限闸)
    ctxf = vctx()
    ctxf["pc"] = {"held": {"002050": 12500.0}, "open_buy": {"002050": 1200.0, "600127": 40000.0}, "floor": 0.6, "nav": 100000, "cap": 100000}
    e_keep = v06(C(dict(buy, qty=100)), ctxf) or ""
    e_cxl = v06(C(dict(buy, qty=100), {"op": "撤单", "code": "600127", "side": "买"}), dict(ctxf, book=dict(bk, orders=bk["orders"] + [
        {"id": "2026-09-30-A-taoge-004", "code": "600127", "side": "BUY", "status": "open", "price": 10.0, "qty": 4000}]))) or ""
    if "未成交买单40000" not in e_keep or "未成交买单0" not in e_cxl:
        fails.append(f"新动词: 撤单后总仓口径未扣掉被撤买单: {e_keep[:80]} / {e_cxl[:80]}")
    # ⑥ plans 行: 开盘卖=SELL+open_sell=1(挂价列=锚) / not_before=HHMM / 撤单=CXL+oid / 有显式撤单的票不发自动 CXL / 无目标撤单不落行
    c = C({"op": "撤单", "order_id": "2026-09-30-A-taoge-002", "why": "竞价弱\n不卖了"}, dict(buy, not_before="13:30", cancel_below=11.8),
          osell, dict(osell, name="三花智控", code="002050", anchor="12.5", qty=300, not_before="14:50"), {"op": "撤单", "order_id": "nope-1"})
    if v06(c, vctx()):
        fails.append("新动词: 组合契约被误杀")
    orig_data, PAPER_DATA = PAPER_DATA, Path(tempfile.mkdtemp(prefix="selftest_verbs_"))
    pf = PAPER_DATA / "plans" / "2026-09-30_A-taoge.md"
    orig_run = subprocess.run
    subprocess.run = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "JSON:{}\n", "stderr": ""})()
    try:
        emit_plans("2026-09-30", "0915", "A-taoge", c, bk)
        got = pf.read_text(encoding="utf-8").splitlines()
        emit_plans("2026-09-30", "1030", "A-taoge", C({"op": "撤单", "order_id": "nope-2"}), bk)
        got2 = pf.read_text(encoding="utf-8").splitlines()
    finally:
        subprocess.run = orig_run
        shutil.rmtree(PAPER_DATA, ignore_errors=True)
        PAPER_DATA = orig_data
    want = ["- 09:15 | A-taoge | CXL | 002050 | - | - | - | - | oid=2026-09-30-A-taoge-002 | 撤单(slot 0915 终裁): 竞价弱 不卖了",
            "- 09:15 | A-taoge | BUY | 002050 | 12.3 | 800 | day | 12.4 | cancel_below=11.8;not_before=1330 | 链终裁: 触发12.3",
            "- 09:15 | A-taoge | SELL | 600519 | 1500 | 100 | day | 1500 | open_sell=1 | 链终裁: 开盘卖(市价, 挂价列=锚1500仅参考)",
            "- 09:15 | A-taoge | SELL | 002050 | 12.5 | 300 | day | 12.5 | open_sell=1;not_before=1450 | 链终裁: 开盘卖(市价, 挂价列=锚12.5仅参考)"]
    if got != want or got2 != got:
        fails.append("新动词: plans 行口径错:\n    " + "\n    ".join(got))
    return fails


def _selftest_horizon(tmp):
    """10/16 晚 持有期改造: 开关关=旧行为 / 02 outlook / 04 hold_days·exit_plan·thesis_check·超 P75 / 持仓论点回看 / 多日核对 / 07 lessons / 导师真人当日操作"""
    global HORIZON, HORIZON_FILE
    fails = []
    hz = tmp / "horizon"
    hz.mkdir(parents=True, exist_ok=True)
    orig_file = HORIZON_FILE
    HORIZON_FILE = hz / "horizon_days.json"
    HORIZON_FILE.write_text(json.dumps({"_default": {"med": 2, "cap": 5}, "liuyiqing": {"med": 1, "cap": 2, "stat": True, "src": "测试"},
                                        "qushitiange": {"med": None, "cap": None, "stat": False, "src": "无统计，按画像"}}, ensure_ascii=False), encoding="utf-8")
    base = lambda **kw: {"date_dash": "2026-10-16", "nav": 100000, "sub": False, "skill": SKILL_CFG["liuyiqing"], "contracts": {"02": {"directions": ["电力"]}}, **kw}
    c02 = lambda **o: {"market_state": "有主线", "leading_layer": "板块层", "directions": ["电力"], **o}
    ok_out = {"horizon_days": "2天", "view": "多（偏强）", "thesis": "电力连板梯队完整", "invalid_if": "龙头断板且跟风跌停"}
    cand = lambda **kw: {"name": "三花智控", "code": "002050", "direction": "电力", "group": "方向", "trigger": "12.5", **kw}
    try:
        apply_skill("liuyiqing")
        # ① 开关关: 注入空串, 缺新字段全放行(旧产物兼容), 07 缺 lessons 放行
        HORIZON = False
        if any(horizon_block(s, base(run_dir=hz)) for s in ("02", "03b", "03j", "04", "07")):
            fails.append("持有期: 开关关时仍注入")
        if v02(c02(), base()) or v04({"candidates": [cand()], "断链说明": None}, base()) or v07({"预案对照": [{"项": "x"}]}, base()):
            fails.append("持有期: 开关关时缺新字段被拦")
        # ② 02 outlook: 有就校验格式+归一, 没有不拦
        c = c02(outlook=dict(ok_out))
        if v02(c, base()) or c["outlook"]["horizon_days"] != 2 or c["outlook"]["view"] != "多":
            fails.append(f"持有期: outlook 正例误杀/未归一: {c['outlook']}")
        for bad, tag in [("x", "非对象"), (dict(ok_out, horizon_days="几天"), "horizon_days 非数"), (dict(ok_out, horizon_days=0), "horizon_days=0"),
                         (dict(ok_out, view="看涨"), "view 非法"), (dict(ok_out, thesis=""), "thesis 空"), ({k: v for k, v in ok_out.items() if k != "invalid_if"}, "缺 invalid_if")]:
            if not v02(c02(outlook=bad), base()):
                fails.append(f"持有期: outlook {tag} 未抓")
        # ③ 04 候选新字段格式
        good = cand(hold_days="2", exit_plan="破 12 止损/+8% 止盈/持 2 天不涨走")
        c = {"candidates": [good], "断链说明": None}
        if v04(c, base()) or c["candidates"][0]["hold_days"] != 2:
            fails.append("持有期: 04 hold_days/exit_plan 正例误杀/未转整数")
        for bad, tag in [(cand(hold_days=0), "hold_days=0"), (cand(hold_days="两天"), "hold_days 非数"), (cand(exit_plan=" "), "exit_plan 空"),
                         (cand(group="遗留", thesis_check="也许"), "thesis_check 非法"), (cand(group="遗留", thesis_check="成立"), "thesis_check 缺 thesis_note")]:
            if not v04({"candidates": [bad], "断链说明": None}, base()):
                fails.append(f"持有期: 04 {tag} 未抓")
        c = {"candidates": [cand(group="遗留", thesis_check="部分成立（量能不足）", thesis_note="板块还在, 龙头弱")], "断链说明": None}
        if v04(c, base()) or c["candidates"][0]["thesis_check"] != "部分成立":
            fails.append("持有期: thesis_check 正例误杀/未归一")
        # ④ 超 P75 须写 over_cap_why(开关开 + 有统计导师; 首次回炉, 末次放行); 无统计导师不拦
        HORIZON = True
        cx = base()
        e1 = v04({"candidates": [cand(hold_days=5, exit_plan="x")], "断链说明": None}, cx)
        e2 = v04({"candidates": [cand(hold_days=5, exit_plan="x")], "断链说明": None}, cx)
        if not e1 or "P75=2" not in e1 or e2:
            fails.append(f"持有期: 04 超 P75 首次应回炉、再次放行: {e1} / {e2}")
        if v04({"candidates": [cand(hold_days=5, exit_plan="x", over_cap_why="题材周期刚启动, 真人同类票拿过 5 天")], "断链说明": None}, base()):
            fails.append("持有期: 04 超 P75 但写了 over_cap_why 仍被拦")
        if not v02(c02(outlook=dict(ok_out, horizon_days=4)), base()):
            fails.append("持有期: 02 outlook 超 P75 无理由未抓")
        apply_skill("qushitiange")
        if v04({"candidates": [cand(hold_days=9, exit_plan="x")], "断链说明": None}, dict(base(), skill=SKILL_CFG["qushitiange"])):
            fails.append("持有期: 无统计导师不该做超上限校验")
        hq = horizon_block("02", base(run_dir=hz))
        if "无统计，按画像" not in hq or "中位 2 天/上限 5 天" not in hq:
            fails.append("持有期: 无统计导师注入文字错")
        apply_skill("liuyiqing")
        # ⑤ 注入: 02/03/04/07 有, 05/06/盲审 无, 转债链无
        h2 = horizon_block("02", base(run_dir=hz))
        if "本导师持有期参考: 中位 1 天/上限 2 天" not in h2 or "outlook.horizon_days 默认填 1" not in h2 or "over_cap_why" not in h2:
            fails.append(f"持有期: 02 注入文字错: {h2[:120]}")
        if "支持还是削弱" not in horizon_block("03j", base(run_dir=hz)) or horizon_block("05", base(run_dir=hz)) or horizon_block("06", base(run_dir=hz)) \
                or horizon_block("blind", base(run_dir=hz)):
            fails.append("持有期: 注入步骤范围错")
        apply_skill("buchitudou0")
        if horizon_block("02", base(run_dir=hz)):
            fails.append("持有期: 转债链不该注入")
        apply_skill("liuyiqing")
        # ⑥ 持仓论点回看: 账本成交 → 买入日/slot → 当天 slots/0915 的 04 候选/06 动作
        cd = hz / "liuyiqing_chain"
        cur, d14, d15 = cd / "live-20261016", cd / "live-20261014", cd / "live-20261015"
        for d in (cur, d14 / "slots" / "0915", d15):
            d.mkdir(parents=True, exist_ok=True)
        wr = lambda f, c, s: f.write_text(f"# x\n```contract\n{json.dumps(c, ensure_ascii=False)}\n```\nSTEP_OK {s} 20261014\n", encoding="utf-8")
        wr(d14 / "slots" / "0915" / ART["04"], {"candidates": [cand(hold_days=2, exit_plan="破12止损", why="电力回踩首板")]}, "04")
        wr(d14 / "slots" / "0915" / ART["06"], {"actions": [{"name": "三花智控", "code": "002050", "op": "买", "why": "06理由"}]}, "06")
        wr(d14 / "slots" / "0915" / ART["02"], {"directions": ["电力"], "outlook": {"horizon_days": 2, "view": "多", "thesis": "电力续强", "invalid_if": "龙头断板"}}, "02")
        bk = {"positions": {"002050": {"qty": 800, "cost": 12.5}}, "nav": [{"date": "2026-10-14"}, {"date": "2026-10-15"}],
              "orders": [{"id": "2026-10-14-A-liuyiqing-001", "date": "2026-10-14", "time": "09:15", "note": "链终裁: 触发12.5"},
                         {"id": "2026-10-13-A-liuyiqing-000", "date": "2026-10-13", "time": "10:00", "note": "旧票"}],
              "trades": [{"id": "2026-10-13-A-liuyiqing-000", "side": "BUY", "code": "600127", "price": 9.0, "qty": 100},
                         {"id": "2026-10-14-A-liuyiqing-000s", "side": "SELL", "code": "600127", "price": 9.5, "qty": 100},
                         {"id": "2026-10-14-A-liuyiqing-001", "side": "BUY", "code": "002050", "price": 12.5, "qty": 800}]}
        cx = base(run_dir=cur, book=bk)
        b4 = horizon_block("04", cx)
        if cx.get("thesis_n") != 1 or "| 002050 | 三花智控 | 2026-10-14 0915 | 12.5 | 2 | 2 天 | 破12止损 | 电力回踩首板（2026-10-14 slots/0915 04） |" not in b4 or "600127" in b4:
            fails.append(f"持有期: 持仓论点回看块错: {b4[b4.find('| 0'):][:200]}")
        e1 = v04({"candidates": [cand(group="遗留")], "断链说明": None}, cx)
        e2 = v04({"candidates": [cand(group="遗留")], "断链说明": None}, cx)
        if not e1 or "thesis_check" not in e1 or e2:
            fails.append(f"持有期: 持仓票缺 thesis_check 首次应回炉、再次放行: {e1} / {e2}")
        # ⑦ 交易日历: 链建之前按工作日补; 第 n 个交易日; 未到=None
        cal = ["2026-10-14", "2026-10-15", "2026-10-16"]
        if _tdays("2026-10-09", "2026-10-16", cal) != 5 or _add_tdays("2026-10-14", 1, cal) != "2026-10-15" or _add_tdays("2026-10-15", 2, cal) is not None:
            fails.append("持有期: 交易日历换算错")
        # ⑧ 多日核对: 观察期满的 outlook(10/14 起 2 日→10/15 到期) + 计划持有到期(10/14 买持 2 天→10/16); 上次 07 之后才列
        r7 = horizon_block("07", base(run_dir=cur, book=bk))
        if "2026-10-14（slots/0915）outlook: 未来 2 个交易日 view=多" not in r7 or "观察区间 2026-10-14~2026-10-15" not in r7 \
                or "002050 三花智控: 2026-10-14 0915 买 800@12.5, 计划持有 2 天(到 2026-10-16)" not in r7 or "仍持有" not in r7:
            fails.append(f"持有期: 多日核对块错: {r7[r7.find('## 多日核对'):][:400]}")
        (d15 / ART["07"]).write_text("x", encoding="utf-8")   # 10/15 跑过 07 → 10/15 到期的 outlook 已核对过, 不再列
        r7b = horizon_block("07", base(run_dir=cur, book=bk))
        if "view=多" in r7b or "计划持有 2 天" not in r7b:
            fails.append("持有期: 多日核对区间(上次 07 之后)错")
        if "本链 vs 真人 当日对照" not in r7 or "| 交不交易 |" not in r7:
            fails.append("持有期: tzzb 链 07 缺本链 vs 真人对照块")
        apply_skill("qushitiange")
        if "导师真人当日操作" not in horizon_block("07", base(run_dir=cur, book=bk)) or "本链 vs 真人" in horizon_block("07", base(run_dir=cur, book=bk)):
            fails.append("持有期: UP 链 07 应保持导师真人当日操作提示(无拟人对照表)")
        apply_skill("liuyiqing")
        # ⑨ 导师真人当日操作: tzzb 逐笔+收盘持仓 / UP / 对照组
        tz = hz / "tzzb" / "liuyiqing"
        tz.mkdir(parents=True)
        legs = [{"trans_date": "2026-10-16 14:56:12", "stock_code": "002696", "stock_name": "百洋股份", "op": "2", "trans_price": "9.66", "trans_count": ""},
                {"trans_date": "2026-10-16 09:31:00", "stock_code": "600127", "stock_name": "金健米业", "op": "235", "buy_sell": "", "trans_price": "5.1", "trans_count": "1"},
                {"trans_date": "2026-10-15 10:00:00", "stock_code": "000001", "stock_name": "平安银行", "op": "1", "trans_price": "10", "trans_count": "1"}]
        (tz / "position_change_p1.json").write_text(json.dumps({"ex_data": {"change_list": legs + legs[:1]}}, ensure_ascii=False), encoding="utf-8")
        (tz / "day_positions.json").write_text(json.dumps({"20261016": {"list": [{"code": "600127", "name": "金健米业", "position_percent": 0.5}]}}, ensure_ascii=False), encoding="utf-8")
        mr = mentor_real_block("liuyiqing", "2026-10-16", tz_dir=hz / "tzzb")
        if mr.count("\n- ") != 3 or "09:31 买 金健米业(600127) @5.1" not in mr or "14:56 卖 百洋股份(002696)" not in mr or "平安银行" in mr or "金健米业(600127) 50%" not in mr:
            fails.append(f"持有期: 导师真人当日操作块错: {mr}")
        if "无交易账本" not in mentor_real_block("qushitiange", "2026-10-16") or "对照组无导师" not in mentor_real_block("control", "2026-10-16"):
            fails.append("持有期: 无账本导师/对照组 第②问提示错")
        # ⑨b 拟人偏差机械对照(10/16 晚 tzzb 导师链 07 主轴): 本链当日成交/持仓/仓位/时段 vs 真人
        bk2 = dict(bk, trades=bk["trades"] + [{"id": "2026-10-16-A-liuyiqing-002", "side": "BUY", "code": "600127", "price": 5.0, "qty": 1000}],
                   orders=bk["orders"] + [{"id": "2026-10-16-A-liuyiqing-002", "date": "2026-10-16", "time": "14:30", "note": "x"}],
                   positions={"002050": {"qty": 800, "cost": 12.5}, "600127": {"qty": 1000, "cost": 5.0}},
                   nav=bk["nav"] + [{"date": "2026-10-16", "mv": 15000, "nav": 100000}])
        mc = mimic_compare_block(base(book=bk2), tz_dir=hz / "tzzb")
        for want in ("| 交不交易 | 成交 1 笔 | 成交 2 笔 |", "| 方向 | 买 1/卖 0 | 买 1/卖 1 |", "重合: 成交 600127 / 持仓 600127", "| 仓位 | 收盘总仓 15% | 收盘总仓 50% |",
                     "| 时段 | 午后(≤14:30)（按挂单 slot） | 尾盘(>14:30)、竞价/开盘(≤09:35) |", "### 真人逐笔与收盘持仓（"):
            if want not in mc:
                fails.append(f"持有期: 拟人对照块缺 {want!r}")
        if "账本未到" not in mimic_compare_block(base(book=bk2, date_dash="2026-10-17"), tz_dir=hz / "tzzb"):
            fails.append("持有期: 真人账本未到未提示")
        # ⑩ 07 lessons / 多日核对 / 拟人对照: 有就校验; 缺 lessons 开关开=软回炉一次
        L07 = lambda **kw: {"预案对照": [{"项": "x", "结果": "命中", "教训": "y"}], **kw}
        okl = [{"type": "规则草案", "text": "连板梯队断层次日不接力", "evidence": "10/14 0915 04 三花智控 + 真人 10/14 空仓"}]
        okm = [{"项": "标的", "本链": "三花智控", "真人": "金健米业", "一致": False, "原因": "理解错导师框架（只看了涨停池）", "说明": "x"}, {"项": "交不交易", "一致": True}]
        if v07(L07(lessons=okl + [dict(okl[0], type="case卡")], 多日核对=[{"date": "2026-10-14", "result": "错", "why": "龙头断板"}], 拟人对照=okm), base()) \
                or v07(L07(lessons=[]), base()):
            fails.append("持有期: 07 lessons/多日核对/拟人对照 正例误杀")
        for bad, tag in [(L07(lessons="x"), "lessons 非列表"), (L07(lessons=[dict(okl[0], type="心得")]), "type 非法"),
                         (L07(lessons=[dict(okl[0], evidence="")]), "evidence 空"), (L07(lessons=okl, 多日核对=[{"result": "大概对", "why": "x"}]), "多日核对 result 非法"),
                         (L07(lessons=okl, 多日核对=[{"result": "对"}]), "多日核对 why 空"),
                         (L07(lessons=okl, 拟人对照=[{"项": "心态", "一致": True}]), "拟人对照 项非法"),
                         (L07(lessons=okl, 拟人对照=[{"项": "仓位", "一致": "否"}]), "拟人对照 一致非布尔"),
                         (L07(lessons=okl, 拟人对照=[{"项": "仓位", "一致": False, "原因": "运气"}]), "拟人对照 不一致缺合法原因")]:
            if not v07(bad, base()):
                fails.append(f"持有期: 07 {tag} 未抓")
        cx = base()
        if not v07(L07(), cx) or v07(L07(), cx):
            fails.append("持有期: 07 缺 lessons 应首次回炉、再次放行")
    finally:
        HORIZON, HORIZON_FILE = False, orig_file
        apply_skill("taoge")
    return fails


def _selftest_ledger(tmp):
    """10/16 晚 三-2: 关=prompt/校验逐字节同旧 / 开=持股只数·新开仓·换手·导师不动闸·0915 首笔软闸·override·候选池预算·打法约束·末次放行记日志 /
    ledger_limits 合成账本参数 / ensure_artifact 缺文件现场生成+失败 fail-open。全程临时目录, 不读写真账本/真 model_out"""
    global LEDGER, PAPER_DATA
    import tempfile
    fails = []
    ll = _ll()
    saved = (LEDGER, PAPER_DATA, SKILL_NAME, ll.TZ, ll.TZZB, ll.ROOT, dict(ll._CACHE), subprocess.run)
    PAPER_DATA = Path(tempfile.mkdtemp(prefix="selftest_ledger_"))
    try:
        apply_skill("a658")
        nav = 100000.0
        book = {"positions": {"002050": {"qty": 1000, "cost": 12.0}}, "orders": [], "cash": 88000,
                "trades": [{"id": "2026-10-15-A-a658-001", "side": "BUY", "code": "002050", "price": 12.0, "qty": 1000}],
                "nav": [{"date": d, "nav": nav} for d in ("2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15")]}
        pc = {"floor": 0, "cap_ratio": 1.0, "cap": 100000.0, "nav": nav, "src": "x", "cash": 88000.0, "held": {"002050": 12000.0},
              "open_buy": {}, "gap": 0.0, "need_n": 0}
        lim = {"n_days": 60, "window": ["20260716", "20261015"], "skip": [], "n_hold_max": 2, "new_open_max": 1, "turnover_max": 0.6,
               "trade_ratio": 0.33, "low_freq": True, "cap_single": 1.0, "conc": True, "max_pos_med": 0.99, "first_frac": 0.2}
        base_hi = {"trade": True, "dir": "加", "tp_target": 0.9, "n_new": 1, "src": {"L1": "延续"}, "p_trade": 0.8, "p_dir": {"加": 0.7, "不动": 0.3},
                   "tp_p25": 0.5, "tp_p75": 0.99, "stale": 0, "state_day": "2026-10-15", "state": {"tp_prev": 0.9, "n_hold": 1}}
        # 10/18 追仓豁免: 闸"拦"的夹具=导师基线不出手且真人昨收轻仓(链 12% 不比导师低 ≥30%); 真人 90% 时链 12% 应豁免
        base_lo = dict(base_hi, p_trade=0.2, state={"tp_prev": 0.1, "n_hold": 1})
        view = {"use_pool": True, "codes": {"600001": "池票甲", "600002": "池票乙"}, "names": {"池票甲", "池票乙"}, "out_ratio": 0.3,
                "allowed_plays": ["涨停回调", "追涨"], "clarity": "清晰", "text": "## 本导师候选池(测试)"}
        mkctx = lambda **kw: {"date_dash": "2026-10-16", "nav": nav, "sub": False, "contracts": {"05": {"verdicts": [
            {"name": n, "result": "批准"} for n in ("三花智控", "池票甲", "池票乙", "野票")]}}, "skill": SKILL_CFG["a658"], "book": book,
            "pc": dict(pc), "snap": {}, **kw}
        buy = lambda name, code, px, q: {"name": name, "code": code, "op": "买", "trigger_price": str(px), "qty": q, "anchor": str(px)}
        c_ok = {"supersedes": "首裁", "actions": [buy("池票甲", "600001", 10.0, 1000)], "no_trade": False}
        # ① 关: ledger_block 空 / constraint_text 不带 ledger_lines / 校验同 __wrapped__ / ledger_prepare 不动 ctx
        LEDGER = False
        cx = mkctx(ledger={"lim": lim, "base": base_hi, "view": view, "slot": "0915"})
        if any(ledger_block(s, cx) for s in ("02", "04", "06")):
            fails.append("CHAIN_LEDGER_CONSTRAINTS 关时 ledger_block 非空")
        pcl = dict(pc, ledger_lines=["- LEDGER 行"])
        if constraint_text(pcl, "06") != constraint_text(pc, "06"):
            fails.append("CHAIN_LEDGER_CONSTRAINTS 关时 constraint_text 变了")
        big = {"supersedes": "首裁", "actions": [buy("池票甲", "600001", 10.0, 3000), buy("池票乙", "600002", 10.0, 2000)], "no_trade": False}
        for nm, c in (("ok", c_ok), ("big", big)):
            a, b = VALIDATORS["06"](json.loads(json.dumps(c)), mkctx(ledger=cx["ledger"])), VALIDATORS["06"].__wrapped__(json.loads(json.dumps(c)), mkctx())
            if a != b:
                fails.append(f"关时 v06 结果与未包装不同({nm}): {a} vs {b}")
        c4 = {"candidates": [{"name": "野票", "code": "600999", "direction": "x", "group": "遗留"}], "断链说明": None}
        if VALIDATORS["04"](c4, mkctx(ledger=cx["ledger"])) != VALIDATORS["04"].__wrapped__(c4, mkctx()):
            fails.append("关时 v04 结果与未包装不同")
        cx0 = mkctx()
        ledger_prepare(cx0, PAPER_DATA, "0915", False, dry=True)
        if "ledger" in cx0 or "ledger_lines" in cx0["pc"]:
            fails.append("关时 ledger_prepare 改了 ctx")
        # ② 开
        LEDGER = True
        lg = lambda base=base_hi, lim_=lim, slot="0915": {"lim": lim_, "base": base, "view": view, "slot": slot}
        v6 = lambda c, **kw: VALIDATORS["06"](json.loads(json.dumps(c)), mkctx(ledger=kw.pop("led", lg()), **kw))
        if v6(c_ok):
            fails.append(f"开: 合规单被误杀: {v6(c_ok)}")
        e = v6({"supersedes": "首裁", "actions": [buy("池票甲", "600001", 10.0, 500), buy("池票乙", "600002", 10.0, 500)], "no_trade": False})
        if not e or "持股" not in e or "新开仓" not in e:
            fails.append(f"开: 持股只数(1+2>2)/新开仓(2>1)未抓: {e}")
        e = v6({"supersedes": "首裁", "actions": [buy("池票甲", "600001", 10.0, 5000)], "no_trade": False})
        if not e or "换手" not in e:
            fails.append(f"开: 近5日换手(12000+50000>60% nav)未抓: {e}")
        e = v6({"supersedes": "首裁", "actions": [buy("池票甲", "600001", 10.0, 3000)], "no_trade": False})
        if not e or "首笔" not in e:
            fails.append(f"开: 0915 首笔(30000>20% nav)软约束未抓: {e}")
        cs = mkctx(ledger=lg())
        c3 = {"supersedes": "首裁", "actions": [buy("池票甲", "600001", 10.0, 3000)], "no_trade": False}
        if not VALIDATORS["06"](json.loads(json.dumps(c3)), cs) or VALIDATORS["06"](json.loads(json.dumps(c3)), cs):
            fails.append("开: 首笔软约束应回炉一次后放行")
        if v6(c3, led=lg(slot="1000"), sub=True):
            fails.append("开: 子链不该查 0915 首笔")
        e = v6(c_ok, led=lg(base=dict(base_lo)))
        if not e or "导师不动链也不动" not in e:
            fails.append(f"开: 低频导师基线不出手时开新仓未拦: {e}")
        e = v6(c_ok, led=lg(base=dict(base_hi, p_trade=0.2)))
        if e and "导师不动链也不动" in e:
            fails.append(f"开: 追仓豁免失效(真人 90% / 链 12%, 不该拦开新仓): {e}")
        if v6({"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "卖", "trigger_price": "12.5", "qty": 1000, "anchor": "12.5"}],
               "no_trade": False}, led=lg(base=dict(base_lo))):
            fails.append("开: 导师不动闸误拦持仓处置(卖)")
        if v6(c_ok, led=lg(base=dict(base_lo, stale=5))) or v6(c_ok, led=lg(base=None)):
            fails.append("开: 基线滞后/缺失时导师不动闸应 fail-open")
        if v6(c_ok, led=lg(lim_=None, base=None)):
            fails.append("开: 无账本统计(lim=None)应全部跳过")
        cf = mkctx(ledger=lg(base=dict(base_lo)), final_attempt=True)
        if VALIDATORS["06"](json.loads(json.dumps(c_ok)), cf):
            fails.append("开: 末次尝试应放行")
        logs = (PAPER_DATA / "ledger" / "2026-10-16.jsonl").read_text(encoding="utf-8") if (PAPER_DATA / "ledger" / "2026-10-16.jsonl").exists() else ""
        if "硬约束末次放行" not in logs:
            fails.append("开: 末次放行未记 ledger 日志")
        ov = {"layer": "L1", "baseline": "不出手", "mine": "出手", "p": 0.6, "why": "竞价资金明显回流主线票"}
        if not v6(dict(c_ok, override=[{"layer": "L9", "why": "xxxxxxxxxx"}])) or not v6(dict(c_ok, override=[dict(ov, p=2)])):
            fails.append("开: override 非法 layer/p 未抓")
        if v6(dict(c_ok, override=[ov])):
            fails.append("开: 合法 override 被误杀")
        orows = [json.loads(x) for x in (PAPER_DATA / "overrides" / "2026-10-16.jsonl").read_text(encoding="utf-8").splitlines()]
        if not any(r["override"] and r["override"][0]["layer"] == "L1" for r in orows):
            fails.append("开: override 未落 overrides/<日>.jsonl")
        # 候选池/打法
        v4 = lambda cands, **kw: VALIDATORS["04"]({"candidates": cands, "断链说明": None}, mkctx(ledger=lg(), **kw))
        cand = lambda n, code, play="涨停回调": {"name": n, "code": code, "direction": "x", "group": "遗留", "play": play}
        if v4([cand("池票甲", "600001"), cand("池票乙", "600002"), cand("野票", "600999")]):
            fails.append("开: 池外 1 只 ≤ 预算 ceil(0.3×3)=1 被误杀")
        e = v4([cand("池票甲", "600001"), cand("野票", "600999"), cand("野票2", "600998")])
        if not e or "池外预算" not in e:
            fails.append(f"开: 池外 2 只 > 预算 1 未抓: {e}")
        if v4([cand("三花智控", "002050", play=None), cand("池票甲", "600001")]):
            fails.append("开: 持仓票不占池外预算/不要求 play, 被误杀")
        e = v4([cand("池票甲", "600001", play="打板")])
        if not e or "打法" not in e:
            fails.append(f"开: 打法越界未抓: {e}")
        if v4([cand("池票甲", "600001", play="打板")], final_attempt=True):
            fails.append("开: 04 打法越界末次应放行")
        e = v4([dict(cand("池票甲", "600001"), play=None)])
        if not e or "play" not in e:
            fails.append("开: 新票缺 play 应软回炉一次")
        # 注入块
        b6 = ledger_block("06", mkctx(ledger=lg(base=dict(base_lo))))
        b4 = ledger_block("04", mkctx(ledger=lg()))
        b2 = ledger_block("02", mkctx(ledger=lg()))
        if "导师不动链也不动" not in b6 or "override" not in b6 or "本导师候选池" not in b4 or "本导师候选池" in b2 or "出手" not in b2 \
                or ledger_block("05", mkctx(ledger=lg())):
            fails.append("开: 注入块内容/步骤错")
        if "交易成本" not in ll.fee_line(nav, 25000) or abs(ll.roundtrip_cost(20000) - (5 + 5 + 10)) > 1e-6:
            fails.append(f"成本口径错(2万一来回应=佣金 5+5+印花税 10): {ll.roundtrip_cost(20000)}")
        # ③ ledger_limits 合成账本(临时 TZ; 注入 _CACHE 免读真腿)
        td = Path(tempfile.mkdtemp(prefix="selftest_tz_"))
        ll.TZ = td
        (td / "zztest").mkdir()
        days = [f"202609{d:02d}" for d in range(1, 31)][:25]
        dp = {d: {"list": [{"code": "600001", "position_percent": 0.95}] + ([{"code": "600002", "position_percent": 0.05}] if i % 5 == 0 else [])}
              for i, d in enumerate(days)}
        (td / "zztest" / "day_positions.json").write_text(json.dumps(dp), encoding="utf-8")
        legs = [{"trans_date": f"{d[:4]}-{d[4:6]}-{d[6:]} 09:31:00", "op": "1", "stock_code": "600002", "trans_amount": "50000"} for i, d in enumerate(days) if i % 5 == 0]
        ll._CACHE["zztest"] = (dp, {d: 100000.0 for d in days}, legs)
        L = ll.ledger_limits("zztest", "2026-10-01")
        if L["n_hold_max"] != 2 or L["new_open_max"] != 1 or abs(L["trade_ratio"] - 0.2) > 1e-6 or not L["low_freq"] or not L["conc"] \
                or L["cap_single"] != 0.95 or L["turnover_max"] != 0.5:
            fails.append(f"ledger_limits 合成账本参数错: {ll.limits_text(L)} {L}")
        if ll.ledger_limits("taoge") is not None or ll.ledger_limits("control") is not None:
            fails.append("B站 UP/对照组应无账本约束")
        # ④ ensure_artifact: 已存在=不起子进程; 缺=调脚本; 子进程失败=False
        ll.TZZB = td
        (td / "model_out").mkdir()
        calls = []

        def fake_run(args, **kw):
            calls.append(args)
            if "--predict" in args:
                (td / "model_out" / "2026-10-16.json").write_text("{}", encoding="utf-8")
            return type("R", (), {"returncode": 0 if "--predict" in args else 1, "stdout": "", "stderr": "boom"})()
        subprocess.run = fake_run
        if not ll.ensure_artifact("model", "2026-10-16", timeout=5) or len(calls) != 1 or not ll.ensure_artifact("model", "2026-10-16", timeout=5) or len(calls) != 1:
            fails.append(f"ensure_artifact 缺文件现场生成/已存在不重跑错: {calls}")
        if ll.ensure_artifact("pool", "2026-10-16", timeout=5):
            fails.append("ensure_artifact 子进程失败应返回 False(fail-open)")
        shutil.rmtree(td, ignore_errors=True)
    except Exception as e:   # noqa: BLE001
        import traceback
        fails.append(f"_selftest_ledger 异常: {e} {traceback.format_exc()[-400:]}")
    finally:
        shutil.rmtree(PAPER_DATA, ignore_errors=True)
        LEDGER, PAPER_DATA = saved[0], saved[1]
        ll.TZ, ll.TZZB, ll.ROOT = saved[3], saved[4], saved[5]
        ll._CACHE.clear(); ll._CACHE.update(saved[6])
        subprocess.run = saved[7]
        apply_skill(saved[2])
    LEDGER = False
    return fails


def _selftest_quality(tmp):
    """10/17 ② 决策质量: 各模块自测 + 关=prompt/校验逐字节同旧 + 开=挂价规则改写 trigger_price/缺 style 回炉一次/plans 行 reprice+挂法 + 0915 开仓预算软闸"""
    global PAPER_DATA
    import copy, io, contextlib, tempfile
    fails = []
    _sk0 = SKILL_NAME
    _logd = None
    try:
        q = _qh()
        _logd = dict(q.LOG_DIR)
        q.LOG_DIR.update({k: Path(tempfile.mkdtemp(prefix=f"selftest_qlog_{k}_")) for k in q.LOG_DIR})   # 自测日志不进真目录
        for m in ("price_rules", "slot_profile", "t_profile", "override_stats", "similar_days", "rule_tags"):
            mod = __import__(m)
            with contextlib.redirect_stdout(io.StringIO()):
                rc = mod.selftest()
            if rc:
                fails.append(f"决策质量: {m}.selftest 失败")
        apply_skill("gaogailvfuli")
        bk = {"source": "A-gaogailvfuli", "cash": 100000, "positions": {}, "orders": [], "trades": [], "nav": []}
        snap = {"600001": {"prevClose": 10.0, "last": 10.2, "name": "池票甲"}}
        mk = lambda **kw: {"date_dash": "2026-10-16", "nav": 100000, "sub": False, "skill": SKILL_CFG["gaogailvfuli"], "book": copy.deepcopy(bk),
                           "snap": dict(snap), "pc": {"nav": 100000, "held": {}, "open_buy": {}, "cap": 100000, "cap_ratio": 1.0, "floor": 0},
                           "contracts": {"05": {"verdicts": [{"name": "池票甲", "result": "批准"}]}},
                           "_q": {"slot": "1000", "skill": "gaogailvfuli", "watch": {}}, **kw}
        act = {"name": "池票甲", "code": "600001", "op": "买", "qty": 100, "anchor": "10.2", "trigger_price": "10.15"}
        C = lambda *a: {"supersedes": "维持", "actions": [dict(x) for x in a], "no_trade": False}
        # ① 全关: block 空 / 包装恒等(结果与内层一致, 不改 actions)
        if any(quality_block(s, mk()) for s in ("02", "04", "05", "06")):
            fails.append("决策质量: 全关时 quality_block 非空")
        wv = _quality_wrap(VALIDATORS["06"])
        c1, c2 = C(dict(act, style="低吸")), C(dict(act, style="低吸"))
        if wv(c1, mk(sub=True)) != VALIDATORS["06"](c2, mk(sub=True)) or c1 != c2:
            fails.append("决策质量: 全关时 06 校验/actions 与旧行为不一致")
        # ② 开 CHAIN_PRICE_RULES: 低吸 → 规则价 < 现价, 带 _reprice; 缺 style → 首次回炉、末次放行
        QF["CHAIN_PRICE_RULES"] = True
        try:
            c = C(dict(act, style="低吸", trigger_price=None))
            e = wv(c, mk(sub=True))
            a0 = c["actions"][0]
            if e or not (float(a0["trigger_price"]) < 10.2) or not a0.get("_reprice") or a0.get("_style") != "低吸":
                fails.append(f"决策质量: 挂价规则低吸未改写 trigger_price/_reprice: {e} {a0}")
            cx = mk(sub=True)
            e1 = wv(C(dict(act)), cx)
            e2 = wv(C(dict(act)), cx)
            if not e1 or "style" not in e1 or e2:
                fails.append(f"决策质量: 缺 style 未回炉一次/未末次放行: {e1} / {e2}")
            c = C(dict(act, style="排板", trigger_price=None))
            if wv(c, mk(sub=True)) or c["actions"][0]["trigger_price"] != "11":
                fails.append(f"决策质量: 排板未按涨停价: {c['actions'][0]}")
            if "挂价交给规则" not in quality_block("06", mk(sub=True)) or quality_block("04", mk(sub=True)):
                fails.append("决策质量: 06 价格表未注入或 04 误注入")
            c = C(dict(act, style="低吸", trigger_price=None))
            wv(c, mk(sub=True))
            orig_data, PAPER_DATA = PAPER_DATA, Path(tempfile.mkdtemp(prefix="selftest_quality_"))
            orig_run = subprocess.run
            subprocess.run = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "JSON:{}\n", "stderr": ""})()
            try:
                emit_plans("2026-10-16", "1000", "A-gaogailvfuli", c, bk)
                got = (PAPER_DATA / "plans" / "2026-10-16_A-gaogailvfuli.md").read_text(encoding="utf-8")
            finally:
                subprocess.run = orig_run
                shutil.rmtree(PAPER_DATA, ignore_errors=True)
                PAPER_DATA = orig_data
            if "reprice=" not in got or "挂法:低吸" not in got:
                fails.append(f"决策质量: plans 行缺 reprice/挂法: {got}")
        finally:
            QF["CHAIN_PRICE_RULES"] = False
        # ③ 全关后 emit_plans 不带新字段(旧口径)
        orig_data, PAPER_DATA = PAPER_DATA, Path(tempfile.mkdtemp(prefix="selftest_quality_"))
        orig_run = subprocess.run
        subprocess.run = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "JSON:{}\n", "stderr": ""})()
        try:
            emit_plans("2026-10-16", "1000", "A-gaogailvfuli", c, bk)
            got = (PAPER_DATA / "plans" / "2026-10-16_A-gaogailvfuli.md").read_text(encoding="utf-8")
        finally:
            subprocess.run = orig_run
            shutil.rmtree(PAPER_DATA, ignore_errors=True)
            PAPER_DATA = orig_data
        if "reprice=" in got or "挂法:" in got:
            fails.append(f"决策质量: 全关时 plans 行仍带新字段: {got}")
    except Exception as e:  # noqa: BLE001
        import traceback
        fails.append(f"_selftest_quality 异常: {e} {traceback.format_exc()[-400:]}")
    finally:
        QF.update(dict.fromkeys(QF, False))
        apply_skill(_sk0)
        if _logd:
            for d in q.LOG_DIR.values():
                shutil.rmtree(d, ignore_errors=True)
            q.LOG_DIR.update(_logd)
    return fails


def selftest():
    global TEST_FLOOR, TEST_FLOOR_TZZB, PAPER_DATA, COMPACT, PROFILE_IDX, TRACE_TOOLS, DYNAMIC_POS, REFLECT, PAPER
    global FIX_FLOOR_EXIT, FIX_NO_DEFER, FIX_ESC_RERUN, FIX_SUB_APPROVED, FIX_HOLDS, SUB_GATE, SUB_MERGE, INLINE_CTX, SHARED_PREFIX, MAIN_SESSION, HORIZON
    global REFLECT_TRIGGER, LEDGER
    LEDGER = False   # 10/16 晚 三-2 账本约束: 全关基线(_selftest_ledger 内临时开)
    QF.update(dict.fromkeys(QF, False))   # 10/17 ② 决策质量: 全关基线(_selftest_quality 内临时开)
    REFLECT_TRIGGER = False   # 10/16 晚 二B-6 偏离触发回注: 全关基线(_selftest_reflect_trigger 内临时开)
    HORIZON = False   # 10/16 晚 持有期改造: 全关基线(用例内临时开)
    INLINE_CTX = SHARED_PREFIX = MAIN_SESSION = False   # 10/14 夜 A6: 全关基线
    FIX_FLOOR_EXIT = FIX_NO_DEFER = FIX_ESC_RERUN = FIX_SUB_APPROVED = FIX_HOLDS = SUB_GATE = SUB_MERGE = False   # 10/14 晚: 全关基线(用例内按需临时开)
    TEST_FLOOR, TEST_FLOOR_TZZB = 0, 0   # 闸单测不受首跑期仓位下限干扰(夹具仓位小; 进程终止无需恢复)
    DYNAMIC_POS = False                  # 夹具按固定 15%/40% 口径写; 动态仓位另有专门用例(见末尾)
    COMPACT = PROFILE_IDX = TRACE_TOOLS = False   # 10/13 晚 G/F 实盘默认开(chain_flags.txt); 自测从"全关"基线起, 用例内按需临时打开
    REFLECT = False   # 10/14 反思回注: chain_flags.txt 对 control 开着, 自测同样从全关基线起
    _env_refl = {k: os.environ.pop(k, None) for k in ("CHAIN_REFLECTION", "CHAIN_REFLECTION_SKILLS")}
    os.environ["CHAIN_CONSISTENCY"] = "0"   # 10/17: chain_flags.txt 已开言行一致性; 自测从全关基线起(否则 _selftest_ledger 夹具票 600001 不在事实包, 被引用核对误拦; 进程终止无需恢复)
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
    fails += _selftest_debate()   # 10/16 晚 保留分歧版
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
    ctx2 = dict(ctx, snap={"002050": {"prevClose": 12.6}, "000910": {"prevClose": 7.6}, "300750": {"prevClose": 28.68}})   # 10/17: 价位缩 10 倍(286.8→28.68), 让 f20 的 100 股整手单不超单票上限 15000
    ctx2["contracts"] = {**ctx["contracts"], "05": {"verdicts": [  # 三票全批准, 让用例真正走到锚校验分支
        {"name": n, "result": "批准", "reason": "r"} for n in ("三花智控", "大亚", "宁德时代")]}}
    f06 = {"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买",
            "trigger_price": "Z*0.97", "qty": 800, "anchor": "12.5", "cancel_below": 11.5, "invalid_if": "破11.5"}], "no_trade": False}
    if v06(f06, ctx2) or abs(f06["actions"][0]["_px"] - 12.222) > 1e-6:
        fails.append("公式价 Z*0.97 正例被误杀/求值错")
    f20 = {"supersedes": "首裁", "actions": [{"name": "宁德时代", "code": "300750", "op": "买",
            "trigger_price": "Z*1.15", "qty": 400, "anchor": "28.65"}], "no_trade": False}  # 20cm 追板单不得被 10% 一刀切误杀(10/17: 原 qty 30 不合创业板 100 股整数倍申报规则=被新申报数量闸正确拦下 → 改 400 股@28.65)
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

    # 10/12 链改造: 枚举唯一前缀 / 总仓口径(含持仓) / 05 批准数闸 / 04 候选数闸 / 01 拼装
    if norm_enum("无主线", MARKET_STATES) != "无主线退潮" or norm_enum("有主线（多主题）", MARKET_STATES) != "有主线" \
            or norm_enum("无", MARKET_STATES) is not None or norm_enum("震荡", MARKET_STATES) is not None:
        fails.append("norm_enum 前缀归一错")
    TEST_FLOOR = 0.4
    bk = {"source": "A-taoge", "cash": 40000, "positions": {"002050": {"qty": 4000, "cost": 12.0}},
          "orders": [{"code": "000910", "side": "BUY", "price": 7.0, "qty": 1000, "status": "open"}]}
    pc_full = pos_constraints(bk, 100000, {"002050": {"last": 12.5}})   # 持仓 50000+挂单 7000 ≥ 40000
    if pc_full["gap"] != 0 or pc_full["need_n"] != 0 or pc_full["held"]["002050"] != 50000:
        fails.append(f"pos_constraints 持仓口径错: {pc_full}")
    pc_empty = pos_constraints({"source": "A-taoge", "cash": 100000, "positions": {}, "orders": []}, 100000, {})
    if pc_empty["gap"] != 40000 or pc_empty["need_n"] != 3:   # 40000/(15000*0.9)=2.96→3
        fails.append(f"pos_constraints 空仓 need_n 错: {pc_empty}")
    if "驱动器仓位约束" not in constraint_text(pc_empty, "05") or "至少 3 只" not in constraint_text(pc_empty, "05"):
        fails.append("constraint_text 05 缺至少几只")
    cf = dict(ctx2, pc=pc_full, sub=True)   # 子链 bug 回归: 已有持仓过下限, 本次不买也不得判"总买仓 0"
    if v06({"supersedes": "维持盘前决策", "actions": [{"name": "三花智控", "code": "002050", "op": "卖",
            "trigger_price": "13.0", "qty": 100, "anchor": "12.6"}], "no_trade": False}, cf):
        fails.append("v06 已有持仓仍被判总仓不足(子链 bug 未修)")
    if not v06({"supersedes": "取代盘前决策", "actions": [{"name": "三花智控", "code": "002050", "op": "卖",
                "trigger_price": "13.0", "qty": 3000, "anchor": "12.6"}], "no_trade": False}, cf):
        fails.append("v06 卖出后跌破下限未抓")
    ce = dict(ctx2, pc=pc_empty)
    if not v06({"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买",
                "trigger_price": "12.5", "qty": 800, "anchor": "12.4"}], "no_trade": False}, ce):
        fails.append("v06 空仓只买 1 万未抓下限")
    ce1 = dict(ce, contracts={**ctx2["contracts"], "05": {"verdicts": [{"name": "三花智控", "result": "批准"}]}})
    if v06({"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买",
            "trigger_price": "12.5", "qty": 800, "anchor": "12.4"}], "no_trade": False}, ce1):
        fails.append("v06 下限不可达(只批 1 只)仍回炉")
    c5 = dict(ctx, pc=pc_empty, contracts={**ctx["contracts"], "04": {"candidates": [{"name": n} for n in "ABCD"]}})
    v5 = {"verdicts": [{"name": "A", "result": "批准"}, {"name": "B", "result": "否决"}, {"name": "C", "result": "否决"}, {"name": "D", "result": "否决"}]}
    if not v05(v5, c5):
        fails.append("v05 批准数不足未抓")
    if v05(v5, dict(c5, final_attempt=True)):
        fails.append("v05 批准数闸末次未放行")
    if not v04({"candidates": [{"name": "三花智控", "direction": "机器人", "group": "方向", "trigger": "1"}], "断链说明": None}, dict(ctx, pc=pc_empty)):
        fails.append("v04 候选数不足未抓")
    TEST_FLOOR = 0
    (tmp / "facts.txt").write_text("## 导师信号速览(x)\n### 桃哥(主框架) ✅\nA1 三态\n### 发哥(刹车)\n1. 回避\n## 池子覆盖率\nx\n", encoding="utf-8")
    mtxt = "# 市场\n正文\n```contract\n" + json.dumps({"date": "2026-09-30", "sources": ["facts"], "digest": "d"}) + "\n```\nSTEP_OK 01m 20260930\n"
    if sentinel_ok(mtxt, "01m", "20260930") is not True:
        fails.append("01m 哨兵识别错")
    c01 = assemble_01(tmp, mtxt, "20260930", "2026-09-30", "0915", bk, {"002050": {"last": 12.5, "name": "三花智控"}})
    t01 = (tmp / ART["01"]).read_text(encoding="utf-8")
    if v01(c01, ctx) or sentinel_ok(t01, "01", "20260930") is not True or "A1 三态" not in t01 or "回避" in t01 \
            or "| 002050 | 三花智控 | 4000 |" not in t01 or contract_of(t01)[0] != c01:
        fails.append("assemble_01 拼装错(哨兵/契约/导师小节截取/持仓表)")
    # 10/14 §3-A 第 3 条: 05 逐票 cap 比单票上限更严 → 06 超了要回炉; 没超/没给 cap 不误杀
    cv = dict(ctx2, contracts={**ctx2["contracts"], "05": {"verdicts": [{"name": "三花智控", "result": "条件批准", "cap": 5000}]}})
    if not v06({"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买", "trigger_price": "12.5", "qty": 800, "anchor": "12.6"}], "no_trade": False}, cv):
        fails.append("v06 未按 05 逐票 cap(5000)拦下 10000 的买单")
    if v06({"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买", "trigger_price": "12.5", "qty": 400, "anchor": "12.6"}], "no_trade": False}, cv):
        fails.append("v06 05 逐票 cap 内(5000)的买单被误杀")
    # 10/16 审计#11: regime 总仓上限只给桃哥链
    _sk0 = globals()["SKILL_NAME"]
    try:
        globals()["SKILL_NAME"] = "taoge"
        has_t = "regime 总仓上限参考" in constraint_text({**pc_empty, "src": "默认(无导师账本)"}, "06")
        globals()["SKILL_NAME"] = "qushitiange"
        has_q = "regime 总仓上限参考" in constraint_text({**pc_empty, "src": "默认(无导师账本)"}, "06")
    finally:
        globals()["SKILL_NAME"] = _sk0
    if not has_t or has_q:
        fails.append("regime 总仓上限注入口径错(只桃哥链该有)")
    # 10/14 §3-A 第 8 条: 态度系数(多=1/中立=0.5/空=0), 缺省=多
    cs = dict(ctx, pc=dict(pc_empty), contracts={"02": {"market_state": "普跌", "leading_layer": "资金惯性层", "directions": ["x"], "stance": "中立"}})
    v02(cs["contracts"]["02"], cs); apply_stance(cs)
    if abs(cs["pc"]["floor"] - 0.2) > 1e-9 or cs["pc"]["need_n"] != 2:
        fails.append(f"态度=中立 下限应 40%→20%/need_n=2, 实际 {cs['pc']['floor']}/{cs['pc']['need_n']}")
    ce0 = dict(ctx, pc=dict(pc_empty), contracts={"02": {"market_state": "普跌", "leading_layer": "资金惯性层", "directions": ["x"], "stance": "空"}})
    v02(ce0["contracts"]["02"], ce0); apply_stance(ce0)
    if ce0["pc"]["floor"] != 0 or ce0["pc"]["need_n"] != 0 or "可以不买" not in constraint_text(ce0["pc"], "06"):
        fails.append("态度=空 下限应为 0 且约束块说明可以不买")
    cm = {"market_state": "有主线", "leading_layer": "板块层", "directions": ["x"]}
    if v02(cm, ctx) or cm["stance"] != "多":
        fails.append("02 缺 stance 应按'多'放行")

    # 盲审哨兵 REVIEW_FAIL 分支
    mk("blind", {"verdict": "fail", "issues": ["编造证据"]}, sentinel="REVIEW_FAIL 20260930")
    if sentinel_ok((tmp / ART["blind"]).read_text(encoding="utf-8"), "blind", "20260930") != "FAIL":
        fails.append("REVIEW_FAIL 分支未识别")

    # 10/13 链改造 G/F(开关默认关; 此处临时打开测完复位)
    if COMPACT or PROFILE_IDX:
        fails.append("selftest 须在开关默认关闭的环境跑(CHAIN_COMPACT/CHAIN_PROFILE_INDEX 未设)")
    if tpl_key("04", t) != "04" or profile_block("02", {}) != "":
        fails.append("开关关闭时 tpl_key/profile_block 改变了默认行为")
    for cm in sorted((ROOT / "skills").glob("*-skill/workflows/chain.md")):
        if cm.parts[-3] == "buchitudou0-skill":
            continue
        tt = _templates_of(cm)
        if not all(k in tt and "{run_dir}" in tt[k] and f"STEP_OK {k[:2]} {{date}}" in tt[k] for k in ("04c", "05c", "06c")):
            fails.append(f"{cm.parts[-3]} chain.md 缺 04c/05c/06c 精简模板或占位符/哨兵")
    COMPACT = True
    if tpl_key("05", t) != "05c" or tpl_key("02", t) != "02":
        fails.append("CHAIN_COMPACT tpl_key 选模板错")
    gctx = dict(ctx2, pc=pc_empty, book=bk, contracts={**ctx2["contracts"], "04": {"candidates": [
        {"name": "三花智控", "code": "002050", "group": "方向", "direction": "机器人", "trigger": "12.5|回踩", "why": "理由\n换行"}]}})
    for st, cc in (("04", gctx["contracts"]["04"]), ("05", {"verdicts": [{"name": "三花智控", "result": "批准", "reason": "r"}], "portfolio": ["簇帽 30%"]}),
                   ("06", {"supersedes": "首裁", "actions": [dict(name="三花智控", code="002050", op="买", trigger_price="Z*0.97", qty=800,
                                                                 anchor="12.5", _px=12.222, _formula="Z*0.97", why="w")], "no_trade": False})):
        mk(st, cc)
        render_into(tmp, st, cc, gctx)
        render_into(tmp, st, cc, gctx)   # 幂等: 二次渲染不叠段
        tr = (tmp / ART[st]).read_text(encoding="utf-8")
        if tr.count("<!-- render:begin -->") != 1 or sentinel_ok(tr, st, "20260930") is not True or contract_of(tr)[0] != cc \
                or tr.find("<!-- render:end -->") > tr.rfind("```contract") or "三花智控" not in tr.split("<!-- render:end -->")[0]:
            fails.append(f"G 渲染 {st} 错(段数/哨兵/contract/位置)")
    if "| 机器人 | 12.5／回踩 |" not in (tmp / ART["04"]).read_text(encoding="utf-8"):
        fails.append("G 渲染 04 单元格转义错")
    if "本次买 9,778" not in (tmp / ART["06"]).read_text(encoding="utf-8"):
        fails.append("G 渲染 06 总仓算账错")
    COMPACT = False
    # F: 假画像+假索引 → 按步注入/失配节跳过/persona_sections 校验
    sys.path.insert(0, str(ROOT / "scripts" / "md"))
    import gen_profile_index as gpi
    pd = tmp / "persona"
    pd.mkdir()
    prof = "# 画像\n简介\n\n## 打法\n- 低吸\n\n## 风控\n- 止损 3%\n\n## 修订记录\n- 10/1 改\n"
    (pd / "profile.md").write_text(prof, encoding="utf-8")
    secs = gpi.parse_sections(prof)
    if [s["title"] for s in secs] != ["画像", "打法", "风控", "修订记录"] or secs[1]["start"] != 4 or secs[1]["end"] != 5:
        fails.append(f"gen_profile_index.parse_sections 切节/行号错: {[(s['title'], s['start'], s['end']) for s in secs]}")
    stp = {"画像": "02,03,04,05,06", "打法": "04,06", "风控": "05", "修订记录": "—"}
    rows = [f"| S{k + 1:02d} | {s['title']} | x | L{s['start']}-{s['end']} | 0.1 | {stp[s['title']]} | 1 | {s['sha8'] if s['title'] != '风控' else '0' * 8} |"
            for k, s in enumerate(secs)]
    (pd / "profile_index.md").write_text("# idx\n> sha12=000000000000\n\n## 核心摘要\n摘要X\n\n## 目录\n| h |\n|---|\n" + "\n".join(rows) + "\n", encoding="utf-8")
    PROFILE_IDX = True
    fctx = {}
    b04, b05, b06 = (profile_block(s, fctx, pd) for s in ("04", "05", "06"))
    if "摘要X" not in b04 or "- 低吸" not in b04 or "- 10/1 改" in b04 or "【S02】打法" not in b04:
        fails.append("F 04 注入节错")
    if "止损 3%" in b05:   # 风控节 sha8 失配(profile 改过)=不注入
        fails.append("F 失配节仍被注入")
    if "persona_sections" not in b06 or fctx.get("profile_ids") != {"S01", "S02", "S04"}:
        fails.append(f"F 06 提示/profile_ids 错: {fctx.get('profile_ids')}")
    ok06 = {"supersedes": "首裁", "actions": [{"name": "三花智控", "code": "002050", "op": "买", "trigger_price": "12.5", "qty": 800, "anchor": "12.4"}], "no_trade": False}
    fc = dict(ctx, profile_ids=fctx["profile_ids"])
    if v06(dict(ok06, persona_sections=["S02"]), fc) or v06(ok06, fc) or not v06(dict(ok06, persona_sections=["S09"]), fc) \
            or v06(dict(ok06, persona_sections=["S09"]), ctx):
        fails.append("v06 persona_sections 校验错(合法误杀/非法未抓/F 关时误拦)")
    PROFILE_IDX = False
    _PROFILE_CACHE.clear()
    # 10/13 修复: 盘前 supersedes 措辞不回炉而归一 / as-of 01 账户表名称从 facts 抠
    sp = {"supersedes": "今日盘前决策", "actions": [{"name": "三花智控", "code": "002050", "op": "买", "trigger_price": "12.5", "qty": 800, "anchor": "12.4"}], "no_trade": False}
    if v06(sp, ctx) or sp["supersedes"] != "首裁":
        fails.append("v06 盘前 supersedes 缺字样未归一为首裁(仍回炉)")
    if not v06(dict(sp, supersedes="今日决策"), dict(ctx, sub=True)):
        fails.append("v06 盘中 supersedes 缺维持/取代 不应被归一(仍须回炉)")
    (tmp / "facts.txt").write_text("## 导师信号速览(x)\n### 桃哥 ✅\nA1\n## 关注票实时快照\n- 002050 三花智控(持仓): 12.5 (+1%)\n## 大盘六榜\n- 002050 别名(榜): x\n", encoding="utf-8")
    assemble_01(tmp, mtxt, "20260930", "2026-09-30", "0915", bk, {"002050": {"last": 12.5}})
    if "| 002050 | 三花智控 | 4000 |" not in (tmp / ART["01"]).read_text(encoding="utf-8"):
        fails.append("assemble_01 无 name 快照时未从 facts 关注票节补票名")
    # 10/13 工具调用留痕(CHAIN_TRACE_TOOLS): 两种输出格式解析 + 留痕落盘 + 命令行切换; 关闭时命令行不变
    js = '{"type":"result","is_error":false,"result":"ok","usage":{"output_tokens":5},"total_cost_usd":0.1}'
    sj = "\n".join(['banner', '{"type":"system","subtype":"init"}',
                    '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1","name":"Read","input":{"file_path":"a/profile.md","offset":10,"limit":5}},'
                    '{"type":"tool_use","id":"t2","name":"Write","input":{"file_path":"x.md","content":"很长正文"}}]}}',
                    '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t1","is_error":true}]}}', js])
    if _claude_result(js) != json.loads(js) or _claude_result(sj).get("total_cost_usd") != 0.1 or _claude_json("banner\n" + js) != json.loads(js):
        fails.append("stream-json/json 结果解析不兼容")
    _dump_tool_calls(sj, (tmp / "tool_calls" / "04.jsonl", {"step": "04", "attempt": 1}))
    tc = [json.loads(l) for l in (tmp / "tool_calls" / "04.jsonl").read_text(encoding="utf-8").splitlines()]
    if len(tc) != 3 or tc[0]["input"]["offset"] != 10 or not tc[0]["error"] or tc[1]["input"]["content"] != "<4 chars>" or tc[2].get("type") != "result":
        fails.append(f"工具调用留痕记录错: {tc}")
    seen = []
    orig_run, orig_slot, orig_log = subprocess.run, _acquire_slot, rotation.log_use
    rotation.log_use = lambda tag: None   # 不往真 key 轮换日志写测试行
    subprocess.run = lambda args, **k: (seen.append(list(args)), type("R", (), {"returncode": 0, "stdout": sj, "stderr": ""})())[1]
    globals()["_acquire_slot"] = lambda: tmp / "slot.fake"
    try:
        rc0 = call_claude("p", trace=(tmp / "tool_calls" / "06.jsonl", {"step": "06"}))   # 关: 命令行=原 CLAUDE
        TRACE_TOOLS = True
        rc1 = call_claude("p", trace=(tmp / "tool_calls" / "06.jsonl", {"step": "06"}))
        rc2 = call_claude("p")   # 开但无 trace 参数=原命令行
    finally:
        subprocess.run, TRACE_TOOLS, rotation.log_use = orig_run, False, orig_log
        globals()["_acquire_slot"] = orig_slot
    cl = [s for s in seen if s and s[0] == CLAUDE[0]]   # rotation.settings_args 自己也调 subprocess(切 key), 只看 claude 命令
    n_tc = len((tmp / "tool_calls" / "06.jsonl").read_text(encoding="utf-8").splitlines())
    if len(cl) != 3 or cl[0][:len(CLAUDE)] != CLAUDE or cl[2][:len(CLAUDE)] != CLAUDE or "stream-json" not in cl[1] \
            or "--verbose" not in cl[1] or "json" in cl[1] or rc1[2] != 0.1 or n_tc != 3:
        fails.append(f"CHAIN_TRACE_TOOLS 命令行切换/解析/留痕错: {[c[:5] for c in cl]} / rc1={rc1}")

    # plans 机械转换(假账本; 公式价+cond 列断言)
    book = {"source": "A-taoge", "cash": 100000, "positions": {},
            "orders": [{"id": "x", "code": "002050", "status": "open"}]}
    a_form = {"name": "大亚", "code": "000910", "op": "卖", "trigger_price": "Z*1.02", "qty": 1000, "anchor": "7.55", "stop_below": 8.1}
    a_form["_px"], a_form["_formula"] = resolve_px("Z*1.02", 7.6)  # 模拟 v06 回填后的取数口
    c06 = {"supersedes": "取代盘前决策:纠偏", "actions": [
        {"name": "三花智控", "code": "002050", "op": "买", "trigger_price": "12.5", "qty": 800, "anchor": "12.4", "invalid_if": "破12"}, a_form]}
    # 10/11: plans 落临时目录(原写真 plans/ 再删=若真文件同名会被删); emit_plans 会调 matcher --import, 打桩防污染真账本
    import tempfile
    orig_data, PAPER_DATA = PAPER_DATA, Path(tempfile.mkdtemp(prefix="selftest_paper_"))
    pf = PAPER_DATA / "plans" / "2026-09-30_A-taoge.md"
    orig_run = subprocess.run
    subprocess.run = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "JSON:{}\n", "stderr": ""})()
    try:
        emit_plans("2026-09-30", "0927", "A-taoge", c06, book)
    finally:
        subprocess.run = orig_run
        PAPER_DATA = orig_data
    got = pf.read_text(encoding="utf-8")
    if "CXL | 002050" not in got or "BUY | 002050 | 12.5 | 800 | day | 12.4 |" not in got:
        fails.append("plans 转换缺 CXL/BUY 行(或 anchor 字段)")
    if "SELL | 000910 | 7.752 | 1000 | day | 7.55 | stop_below=8.1 |" not in got:
        fails.append("plans 公式价代换/anchor/stop_below cond 列缺失")
    shutil.rmtree(pf.parent.parent, ignore_errors=True)

    # 10/14 §3-A 第 6 条: 决策日志+反思回注——关闭=空操作 / 白名单外不注入 / 只注入运行日前已结算 / 同票≤5 跨票≤3 / 护栏拦下的不注入
    import tempfile
    rctx = {"date_dash": "2026-10-13", "sub": False, "contracts": {"04": {"candidates": [{"code": "600001"}]}},
            "book": {"positions": {"002050": {"qty": 100, "cost": 10}}, "orders": []}}
    if reflect_on() or reflection_block("04", rctx) or reflection_block("06", rctx):
        fails.append("CHAIN_REFLECTION 关闭时 reflect_on 为真/反思块非空")
    orig_paper, orig_data = PAPER, PAPER_DATA
    PAPER = PAPER_DATA = Path(tempfile.mkdtemp(prefix="selftest_refl_"))   # 隔离: 不读实盘 decisions
    os.environ["CHAIN_REFLECTION"], os.environ["CHAIN_REFLECTION_SKILLS"] = "1", "control"
    REFLECT = True
    try:
        dmod, dd = _dm(), PAPER_DATA / "decisions"
        mkd = lambda date, code, slot="0915": dmod.records_from_contract(
            {"actions": [{"name": "票" + code, "code": code, "op": "买", "trigger_price": "10", "qty": 100, "anchor": "10"}]},
            skill="control", source="A-control", date=date, slot=slot, sub=False, blind_fail=False, asof=False, ts=f"{date}T09:15:00")[0]
        same = [mkd(f"2026-09-{d:02d}", "002050") for d in (22, 23, 24, 25, 26, 29)] + [mkd("2026-10-08", "002050"), mkd("2026-10-12", "002050")]
        cross = [mkd(f"2026-09-{d:02d}", "600999") for d in (22, 23, 24)] + [mkd("2026-10-09", "600888"), mkd("2026-10-09", "600777", "1000")]
        dmod.write_decisions(dd, "control", same + cross)
        nxt = {"2026-10-08": "2026-10-09", "2026-10-09": "2026-10-12", "2026-10-12": "2026-10-13"}
        refl = [{"id": r["id"], "resolved": nxt.get(r["date"], "2026-09-30"), "text": f"反思{r['date']}{r['code']}", "guard": "ok"} for r in same + cross]
        refl[-1]["guard"], refl[-1]["text"] = "rejected", "规则错了应改"
        dmod.append_reflects(dd, "control", refl)
        apply_skill("taoge")
        if reflect_on() or reflection_block("04", dict(rctx)):
            fails.append("白名单外(taoge)仍注入反思")
        apply_skill("control")
        c4 = dict(rctx)
        b4 = reflection_block("04", c4)
        if not reflect_on() or "反思2026-10-08002050" not in b4 or "反思2026-10-12002050" in b4 or "2026-10-13 之前" not in b4                 or c4.get("reflect_n", {}).get("04") != (5, 3) or "规则错了" in b4 or "反思2026-10-09600888" not in b4:
            fails.append(f"反思回注 as-of 过滤/条数/护栏错: n={c4.get('reflect_n')}")
        if "反思2026-10-12002050" not in reflection_block("04", dict(rctx, date_dash="2026-10-14")):
            fails.append("运行日之后应能看到 10/13 已结算的反思")
        if reflection_block("05", dict(rctx)) or reflection_block("02", dict(rctx)):
            fails.append("反思块注入了 04/06 以外的步")
        c06 = {"supersedes": "首裁", "actions": [dict(name="三花智控", code="002050", op="买", trigger_price="Z*0.97", qty=800, anchor="12.5",
                                                     _px=12.222, why="回踩", rules=[{"id": "A4", "ctx": "情境判定 xxxxxxxx"}])]}
        log_decisions("2026-10-13", "1000", "A-control", c06, dict(rctx, sub=True, blind_fail="x"))
        lg = [r for r in dmod.load_decisions(dd, "control").values() if r["date"] == "2026-10-13"]
        if len(lg) != 1 or lg[0]["px"] != 12.222 or lg[0]["slot"] != "1000" or not lg[0]["sub"] or not lg[0]["blind_fail"] or lg[0]["rules"] != ["A4"]:
            fails.append(f"决策日志记录错: {lg}")
    finally:
        shutil.rmtree(PAPER_DATA, ignore_errors=True)
        PAPER, PAPER_DATA, REFLECT = orig_paper, orig_data, False
        os.environ.pop("CHAIN_REFLECTION", None); os.environ.pop("CHAIN_REFLECTION_SKILLS", None)
        apply_skill("taoge")
    for k, v in _env_refl.items():
        if v is not None:
            os.environ[k] = v

    fails += _selftest_subfix(ctx, ctx2, bk, pc_full, tmp)
    fails += _selftest_a6(tmp)
    fails += _selftest_horizon(tmp)   # 10/16 晚 持有期改造
    fails += _selftest_verbs(tmp)   # 10/16 06 新动词
    fails += _selftest_reflect_trigger()   # 10/16 晚 二B-6 偏离触发回注
    fails += _selftest_ledger(tmp)
    fails += _selftest_quality(tmp)   # 10/17 ② 决策质量新功能(挂价规则/时段/T 法/相似市况/锁层/规则方向)   # 10/16 晚 三-2 账本统计硬约束/候选池/基线建议

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
    print("SELFTEST PASS: 模板抽取/哨兵/contract 校验器(正例不误杀+反例全抓, 含 C7 价格锚 5 反例+公式价+20cm 分档)/盲审 FAIL 分支/plans 转换(anchor+cond 列+公式价代换)/cb 链(模板+v06 转债闸)/10/13 F·G(开关默认关不变+14 链精简模板+人看表渲染幂等+画像按步注入/失配节跳过/persona_sections 校验)+10/13 修复(盘前 supersedes 归一/01 名称补齐)+工具调用留痕(json·stream-json 双解析/命令行开关)+10/14 反思回注(关闭空操作/白名单/as-of 过滤/条数上限/护栏/决策日志)+10/14 晚 子链(开关全关不变/修①下限只管主动减仓/修②交用户回炉/修④ESCALATE 本 slot 重跑一次/修⑤名单闸/holds/触发闸 a~e+fail-open+跳过产物/合并 D 分块 resume+回落逐步)+10/16 06 新动词(旧契约不变/开盘卖/撤单/not_before 校验+plans 口径)+10/16 晚 持有期改造(开关关不变/02 outlook/04 hold_days·exit_plan·thesis_check·超 P75 须写理由/持仓论点回看/多日核对/07 lessons/导师真人当日操作)+10/16 晚 账本统计硬约束(开关关不变/持股只数·新开仓·换手·导师不动闸·0915 首笔软闸·override 记账·候选池预算·打法约束·末次放行日志·合成账本参数·产物现场生成 fail-open)")

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
    ap.add_argument("--asof", metavar="SANDBOX", help="as-of 回放: 沙盒数据根(books/plans/facts), 链日=--date, 行情=前一交易日日线")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return
    apply_skill(a.skill)
    source = a.source or SKILL["source"]
    date = a.date
    date_dash = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    if a.asof:  # 10/10: 子进程(facts/snapshot/matcher)经 env 同步切沙盒+回放口径
        global PAPER_DATA, ASOF
        PAPER_DATA, ASOF = Path(a.asof).resolve(), date_dash
        if not (PAPER_DATA / "books").is_dir():
            sys.exit(f"沙盒无 books/: {PAPER_DATA}(先 PAPER_ROOT=<沙盒> node scripts/dfcf/paper/matcher.mjs --init)")
        os.environ["PAPER_ROOT"], os.environ["PAPER_ASOF"] = str(PAPER_DATA), date_dash
        global PERSONA_REL
        pa = PAPER_DATA / "persona" / SKILL_NAME
        if (pa / "_asof.json").exists():
            PERSONA_REL = pa.resolve().relative_to(ROOT).as_posix() if pa.resolve().is_relative_to(ROOT) else str(pa.resolve())
            print(f"as-of 画像: {PERSONA_REL} ({(pa / '_asof.json').read_text(encoding='utf-8')[:160].strip()})")
            _lock_chain_md(pa)
        elif os.environ.get("CHAIN_PERSONA_ASOF_REQUIRED") == "1":
            sys.exit(f"as-of 要求锁画像但沙盒没有 {pa}/_asof.json(先跑 persona_asof.py), 拒绝用当前画像回放")
        else:
            print(f"WARN: as-of 未锁画像, 读的是当前 persona(可能含 {date_dash} 之后的信息)")
    else:  # 实盘: 清掉残留的沙盒变量, 防 facts/matcher 子进程写沙盒而驱动器读实盘(10/11 预检实录)
        os.environ.pop("PAPER_ROOT", None)
        os.environ.pop("PAPER_ASOF", None)
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
