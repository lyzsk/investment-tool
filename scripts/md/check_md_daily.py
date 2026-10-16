#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_md_daily.py — 每日盘后 check md 编排器(2026-10-13 用户令: 做成定时任务, Java sys_job 调本脚本)

七步(顺序=用户 CLAUDE.md 口径): ①cls 四小节核对 ①b 龙虎榜(lhb, 零 token) ②三 UP sum ③三 UP distill ④tzzb sum(硬数据+推测层) ⑤tzzb distill ⑥发哥收盘后当日核销
  + 00:00 收尾轮末尾: 龙虎榜历史回填(lhb_backfill, 倒序到 2025-01-07 补完即空转; 06:40 后不开新日, 07:00 前必停, 给 07:50 的 0915 链让路)
  ⑤ 补蒸馏(10/14): 蒸馏完成时把"有数据的账本名单"记进 state; 后续轮次若有数据名单多出来(晚到账本), 只对新增的跑 distill_daily --ledgers
设计=状态驱动增量扫(10/13 用户定: 一个定时任务, 18:00~23:00 每整点 + 00:00 收尾): 每轮先补"上一个交易日"遗留, 再做"今天"——
每步只做"前置已就绪且还没做"的, 已做的跳过; 晚到的(天哥 18 点后发的稿、23:10 前陆续出齐的 tzzb 账本)由后面的整点轮接上。
tzzb distill 在 00:00 那轮做(账本 23:10 最后一次抓取之后, 当天已出齐); 00:00 没做成的由次日轮作为遗留补。
单实例: 上一轮没跑完(如 18:00 轮跑到 19:30), 19:00 轮直接跳过, 20:00 轮再接。
LLM 步一律串行, 同一时刻只有一个 claude -p(用户立法); 本脚本单实例(上一轮没跑完, 新一轮直接退出)。

用法: scripts/venv/Scripts/python.exe -X utf8 scripts/md/check_md_daily.py [--date yyyy-MM-dd] [--deadline HH:MM] [--only cls,lhb,up,tzzb_sum,tzzb_distill,fage,lhb_backfill] [--dry]
  --date 缺省: 09:00 前(含 00:00 收尾轮)=上一个交易日, 之后=今天; 非交易日直接退出
  --deadline: 过了这个时刻不再开新的 claude 会话(早上兜底轮 07:45, 给 07:50 的 0915 链让路); 缺省=早上轮 07:45, 晚上不限
出口: 0=本轮正常结束(含"有步骤没就绪") 1=有步骤执行失败 2=用法/环境错; 末行 JSON:{...} 供 Java 记日志
产物: scripts/md/logs/check_md_<date>.log(逐轮追加) + scripts/md/logs/check_md_state.json(cls/tzzb_distill 完成记录)
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / "scripts" / "venv" / "Scripts" / "python.exe")
LOG_DIR = ROOT / "scripts" / "md" / "logs"          # logs/ 已在 .gitignore
STATE_F = LOG_DIR / "check_md_state.json"
LOCK_F = LOG_DIR / "check_md.lock"
UPS = [("taoge", "#### 股市 - 桃哥复盘"), ("qushitiange", "#### 趋势天哥"), ("lubenyuan", "#### 卢本圆复盘")]
UP_WINDOW_DAYS = 3        # UP 步只追最近 3 天的欠账(晚到稿/顺延稿); 更早的历史欠账归 backfill
TZZB_DISTILL_AFTER = "23:30"   # tzzb 账本 15:10~23:10 每小时抓, 当天 23:30 前不蒸馏当天(没出齐); 00:00 收尾轮(按上一交易日算)来做(单会话 11 人, 做完不再重做)
CATCHUP_SINCE = "2026-10-13"   # 补"上一个交易日"的起点: 更早的日子由人工/子代理做过, 无状态记录, 不回头重做
LHB_READY_HHMM = "18:00"       # 交易所 16:30~17:30 出齐(公开口径), 东财晚几分钟; 18:00 前抓的 list.json 视为临时版, 下一轮重抓覆盖
LHB_BACKFILL_FROM = "2025-01-07"
LHB_BACKFILL_MAX_DAYS = 150    # 10/14 实测(全量 425 天): 每天 3~5 次请求/平均 16s(含 10s 日间隔), 0 限流; 150 天≈40 分钟/≈500 次; 历史已补完, 现每晚空转 ≈2s
LHB_BACKFILL_UNTIL = "06:40"   # 06:40 后不开新的一天(单日 ≤20s), 07:00 前必停

sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
LOG_FH = None


def log(msg):
    line = f"[{dt.datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    if LOG_FH:
        LOG_FH.write(line + "\n")
        LOG_FH.flush()


# ---------- 交易日 / 目标日 ----------
def _bb():
    """backfill_bilibili 模块(复用其节假日判断与 UP 欠账计算; import 时会解析 argv, 先清空)"""
    saved = sys.argv
    sys.argv = [saved[0]]
    try:
        import backfill_bilibili as b
    finally:
        sys.argv = saved
    return b


def target_date(arg, b):
    hol = b.load_holidays()
    if arg:
        d = dt.date.fromisoformat(arg)
        return d, b.is_off_day(d, hol)
    now = dt.datetime.now()
    d = now.date()
    if now.hour < 9:                      # 次日早上的兜底轮: 补的是上一个交易日
        d -= dt.timedelta(days=1)
        while b.is_off_day(d, hol):
            d -= dt.timedelta(days=1)
        return d, False
    return d, b.is_off_day(d, hol)


def prev_trading_day(d, b):
    hol = b.load_holidays()
    x = d - dt.timedelta(days=1)
    while b.is_off_day(x, hol):
        x -= dt.timedelta(days=1)
    return x


def md_path(d):
    return ROOT / "md" / f"{d.year}S{(d.month - 1) // 3 + 1}" / f"{d.isoformat()}.md"


def section(text, head):
    """取 md 小节正文(从标题行到下一个同级或更高级标题前); 不存在=None"""
    level = len(head) - len(head.lstrip("#"))
    m = re.search(rf"^{re.escape(head)}\s*$", text, re.M)
    if not m:
        return None
    rest = text[m.end():]
    nxt = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


def filled(sec, min_chars=40):
    return sec is not None and len(re.sub(r"\s+", "", re.sub(r"<!--[\s\S]*?-->", "", sec))) >= min_chars


# ---------- 状态 ----------
def load_state():
    try:
        return json.loads(STATE_F.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def mark_done(state, d, step, info="", **extra):
    state.setdefault(d.isoformat(), {})[step] = {"at": dt.datetime.now().isoformat(timespec="seconds"), "info": info, **extra}
    save_state(state)


def save_state(state):
    STATE_F.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------- 子进程 / claude ----------
def run(cmd, label, timeout_s=3600):
    log(f"  $ {label}")
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s)
    except subprocess.TimeoutExpired:
        log(f"  ✗ {label} 超时 {timeout_s}s")
        return 1, ""
    out = (r.stdout or "") + (r.stderr or "")
    tail = [l for l in out.splitlines() if l.strip()][-3:]
    log(f"  {'✓' if r.returncode == 0 else '✗'} exit={r.returncode} | " + " / ".join(t[:150] for t in tail))
    return r.returncode, out


def claude(prompt, tag, sentinel, timeout=3600):
    from claude_call import call, LEAN_ARGS
    t0 = time.time()
    # 10/15 A13①: 精简参数(去动态系统提示/斜杠命令/MCP + 工具白名单; 提示词按文件路径读 skill, 不依赖斜杠命令)
    r = call(prompt, tag=tag, permission="skip", timeout=timeout, sentinels=[sentinel], extra_args=LEAN_ARGS + ["--tools", "Read,Write,Edit,Grep,Glob,Bash"])
    hit = bool(r.sentinels.get(sentinel))
    log(f"  claude[{tag}] {'✓' if hit else '✗'} {time.time() - t0:.0f}s ${r.cost_usd:.2f}"
        + ("" if hit else f" | {' | '.join(r.errors)[:200]} | 末行: {(r.result or '').strip().splitlines()[-1][:80] if (r.result or '').strip() else '空'}"))
    return hit, r.result or ""


class Ctx:
    def __init__(self, d, deadline, dry):
        self.d, self.deadline, self.dry = d, deadline, dry
        self.md = md_path(d)
        self.results = {}       # step -> 完成/跳过/失败 + 原因
        self.tzzb_has_data = None   # tzzb_sum 本轮算出的"有数据账本"名单(⑤补蒸馏用); None=本轮没算

    def can_llm(self):
        return not self.deadline or dt.datetime.now().strftime("%H:%M") < self.deadline

    def md_text(self):
        return self.md.read_text(encoding="utf-8") if self.md.exists() else ""


# ---------- ① cls 四小节核对 ----------
def step_cls(c, state):
    if state.get(c.d.isoformat(), {}).get("cls"):
        return "已完成"
    t = c.md_text()
    need = {h: filled(section(t, h)) for h in ("## 午评", "## 午间涨停分析", "## 收评", "## 涨停分析")}
    if not (need["## 收评"] and need["## 涨停分析"]):
        return f"未就绪(收评/涨停分析还没灌进 md: {[h for h, ok in need.items() if not ok]})"
    if not c.can_llm():
        return "跳过(已过截止时刻)"
    if c.dry:
        return "dry: 将跑 cls 核对"
    prompt = (f"执行 check-cls-md 流程(先读 skills/check-cls-md/SKILL.md, 按其检查流程做), 对 {c.d.isoformat()} 检查并修正 "
              f"{c.md.relative_to(ROOT).as_posix()} 里 cls OCR 填充的四小节(午评/午间涨停分析/收评/涨停分析): 列错位、丢字断词、错字、缺张都要修; "
              "缺图或解析失败按 SKILL 的补齐办法处理。任务优先, 禁反问, 不要改其他小节。"
              "最终回复(会话最后一条消息)先用 3~8 行列出修了什么(没问题就写'无需修正'), 最后一行只写: CLS_CHECK_DONE")
    ok, out = claude(prompt, "checkmd-cls", "CLS_CHECK_DONE", timeout=2400)
    if ok:
        mark_done(state, c.d, "cls", out.strip().splitlines()[0][:200] if out.strip() else "")
        return "完成"
    return "失败"


# ---------- ①b 龙虎榜(零 token): 东财当日榜出了就抓 + 整节覆盖 md ### 龙虎榜 ----------
def _json_tail(out):
    for l in reversed(out.splitlines()):
        if l.startswith("JSON:"):
            try:
                return json.loads(l[5:])
            except ValueError:
                return {}
    return {}


def lhb_done(c):
    """完成判据: md ### 龙虎榜 → #### 概况 里已有总表(至少一行 "名 代码" 数据行), 且原始数据不是 18:00 前抓的临时版"""
    sec = section(c.md_text(), "### 龙虎榜")
    if not sec:
        return False
    m = re.search(r"^#### 概况\s*$([\s\S]*?)(?=^#### |\Z)", sec, re.M)
    # 表头随模板可改(fetch_lhb 从模板现读), 判据不认表头文字, 只认"至少一行首格是 '名 6位代码' 的数据行"
    if not (m and re.search(r"^\| [^|\n]+ \d{6} \|", m.group(1), re.M)):
        return False
    try:
        L = json.loads((ROOT / "downloads" / "lhb" / c.d.strftime("%Y.%m.%d") / "list.json").read_text(encoding="utf-8"))
        return L.get("fetched_at", "") >= f"{c.d.isoformat()} {LHB_READY_HHMM}"
    except (OSError, ValueError):
        return True     # 表在、原始数据被挪走: 以 md 为准, 不重抓


def step_lhb(c, state):
    if lhb_done(c):
        return "已完成"
    if c.dry:
        return "dry: 将跑 fetch_lhb --write(前置=东财当日龙虎榜已出, 空榜=未就绪)"
    rc, out = run(["node", "scripts/lhb/fetch_lhb.mjs", "--date", c.d.isoformat(), "--write"], "龙虎榜 fetch_lhb --write", 900)
    j = _json_tail(out)
    if rc == 3:
        return "未就绪(东财当日龙虎榜还没出, 下一轮再试)"
    if rc == 0 and j.get("md") == "无复盘节(只存json)":
        return "跳过(md 无 ## 复盘 节, 只存 json)"
    if rc == 0 and lhb_done(c):
        # 记首次就绪时刻(整点轮粒度), 积累几天即得"东财每天几点出齐"的实测
        mark_done(state, c.d, "lhb", f"{j.get('stocks')} 只/{j.get('records')} 条, 请求 {j.get('requests')} 次, {j.get('secs')}s")
        return f"完成({j.get('stocks')} 只, 请求 {j.get('requests')} 次)"
    if rc == 0 and j.get("provisional"):
        return "未就绪(18:00 前抓到的是临时版, 下一轮重抓)"
    return f"失败(exit {rc}{', 反爬' if rc == 5 else ''}: {str(j.get('msg', ''))[:120]})"


def step_ztpool(c, state):
    """10/14 用户定: 财联社涨停池 → md ## 涨停梯队(fetch_cls_pool.mjs --write; 只覆盖空小节或本脚本写过的, 人工内容不动)。
    注意: 财联社池子只给"最近一个交易日", 只能当天(或次日开盘前)抓, 补不了历史"""
    sec = section(c.md_text(), "## 涨停梯队") or ""
    if f"> 财联社涨停池 {c.d.isoformat()}" in sec:
        return "已完成"
    if sec.strip():
        return "跳过(小节已有人工内容)"
    import datetime as _dt
    if c.d != _dt.date.today() and not (c.d == _dt.date.today() - _dt.timedelta(days=1) and _dt.datetime.now().hour < 9):
        return "跳过(财联社池只给最近一个交易日, 补不了历史)"
    if c.dry:
        return "dry: 将跑 fetch_cls_pool --write"
    rc, out = run(["node", "scripts/cls/fetch_cls_pool.mjs", "--write"], "涨停梯队 fetch_cls_pool --write", 300)
    j = _json_tail(out)
    if rc == 0 and j.get("tradeDate") != c.d.isoformat():
        return f"未就绪(池子交易日={j.get('tradeDate')}, 不是 {c.d})"
    if rc == 0 and j.get("md") == "已写":
        mark_done(state, c.d, "ztpool", f"涨停 {j.get('zt')} / 炸板 {j.get('zb')} / 跌停 {j.get('dt')}")
        return f"完成(涨停 {j.get('zt')} 只)"
    return f"失败(exit {rc}: {j.get('md') or str(out[-1:])[:120]})"


# ---------- ②③ 三 UP sum + distill(复用 backfill_bilibili --llm-batch, 自带幂等与 distill 锁) ----------
def step_up(c, b):
    lo = (c.d - dt.timedelta(days=UP_WINDOW_DAYS)).isoformat()
    hi = c.d.isoformat()
    parts = []
    for up, _head in UPS:
        b.apply_up(up)
        _asr, full = b.scan_done()
        md_p = [x for x in b._pending_md_days(full) if lo <= x <= hi]
        dist = b.load_distilled()
        dd_p = [x for x in b._pending_distill_days(dist) if lo <= x <= hi]
        if not md_p and not dd_p:
            parts.append(f"{up}=无欠账")
            continue
        if not c.can_llm():
            parts.append(f"{up}=跳过(过截止)")
            continue
        if c.dry:
            parts.append(f"{up}=dry(md {md_p} / distill {dd_p})")
            continue
        n = max(1, len([x for x in md_p if x not in dist]))
        rc, out = run([PY, "-X", "utf8", "scripts/backfill_bilibili/backfill_bilibili.py", "--up", up, "--llm-batch", "--max", str(n)],
                      f"{up} llm-batch --max {n}(md {md_p} / distill {dd_p})", timeout_s=2 * 3600)
        b.apply_up(up)
        dist2 = b.load_distilled()
        left = [x for x in b._pending_distill_days(dist2) if lo <= x <= hi]
        parts.append(f"{up}={'完成' if rc == 0 and not left else f'未完(exit {rc}, 余 {left})'}")
    return "; ".join(parts)


# ---------- ④ tzzb sum: 硬数据层(零 token, 每轮覆盖) + 推测层(LLM, 有硬数据且无【推测】的才补) ----------
def step_tzzb_sum(c):
    ledgers = json.loads((ROOT / "scripts" / "tzzb" / "tzzb_ledgers.json").read_text(encoding="utf-8"))
    if not c.md.exists():
        return "未就绪(当日 md 不存在)"
    # 只做 md 骨架里已有小节的高手(tzzb_ledgers.json 含观察中的新账本, 还没建 skill/md 小节的不写)
    heads = {re.sub(r"\s+", "", m.group(1)) for m in re.finditer(r"^#### (.+)$", c.md_text(), re.M)}
    ledgers = [L for L in ledgers if re.sub(r"\s+", "", L["name"]) in heads]
    if c.dry:
        return f"dry: 将跑 gen_tzzb_md ×{len(ledgers)} + 推测层"
    run(["node", "scripts/quotes/fetch_quotes.mjs", "--market", "cb", "--trends-all"], "cb 分时归档(土豆 sum 前置)", 900)
    has_data = []
    for L in ledgers:
        rc, out = run(["node", "scripts/tzzb/gen_tzzb_md.mjs", "--ledger", L["ledger"], "--date", c.d.isoformat(), "--write"],
                      f"gen_tzzb_md {L['ledger']}", 300)
        if rc == 0 and "覆盖" in out:
            has_data.append(L)
    c.tzzb_has_data = sorted(L["ledger"] for L in has_data if L.get("kind") == "pos")
    t = c.md_text()
    todo = []
    for L in has_data:
        sec = None
        for m in re.finditer(r"^#### (.+)$", t, re.M):
            if re.sub(r"\s+", "", m.group(1)) == re.sub(r"\s+", "", L["name"]):
                sec = section(t, m.group(0))
                break
        if sec is not None and "【推测】" not in sec:
            todo.append(L)
    head = f"有数据 {len(has_data)}/{len(ledgers)}"
    if not todo:
        return f"{head}, 推测层已齐"
    if not c.can_llm():
        return f"{head}, 推测层待补 {[L['ledger'] for L in todo]}(过截止)"
    names = ", ".join(f"{L['ledger']}(#### {L['name']})" for L in todo)
    prompt = (f"按 skills/tzzb-skill/workflows/sum.md 的【推测】层规则, 为 {c.d.isoformat()} 补写以下高手在 "
              f"{c.md.relative_to(ROOT).as_posix()} 对应小节末尾的【推测】段: {names}。"
              "硬数据层已由 gen_tzzb_md 写好, 只读不改; 推测必须带锚点, 原文/数据没有的不硬凑。逐人串行, 每完成一人打印一行 SPEC_OK <ledger>。"
              "最终回复(会话最后一条消息)开头逐行复述全部 SPEC_OK 行, 最后一行只写: TZZB_SPEC_DONE")
    ok, _ = claude(prompt, "checkmd-tzzb-spec", "TZZB_SPEC_DONE", timeout=3000)
    return f"{head}, 推测层补 {len(todo)} 人{'完成' if ok else '失败'}"


# ---------- ⑤ tzzb distill(单会话 11 人, 23:30 后才做, 做完记状态+有数据名单; 之后晚到的账本只补蒸馏新增的) ----------
def tzzb_has_data(c):
    """有数据的正样本账本名单: 本轮 tzzb_sum 算过就用它; 否则只读跑 gen_tzzb_md(不带 --write, 有数据=stdout 非空)"""
    if c.tzzb_has_data is not None:
        return c.tzzb_has_data
    ledgers = json.loads((ROOT / "scripts" / "tzzb" / "tzzb_ledgers.json").read_text(encoding="utf-8"))
    heads = {re.sub(r"\s+", "", m.group(1)) for m in re.finditer(r"^#### (.+)$", c.md_text(), re.M)}
    got = []
    for L in ledgers:
        if L.get("kind") != "pos" or re.sub(r"\s+", "", L["name"]) not in heads:
            continue
        try:
            r = subprocess.run(["node", "scripts/tzzb/gen_tzzb_md.mjs", "--ledger", L["ledger"], "--date", c.d.isoformat()],
                               cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        except subprocess.TimeoutExpired:
            continue
        if r.returncode == 0 and r.stdout.strip():
            got.append(L["ledger"])
    c.tzzb_has_data = sorted(got)
    return c.tzzb_has_data


def step_tzzb_distill(c, state, morning):
    """当天 23:30 前不做当天(账本没出齐); 次日那轮作为"上一个交易日遗留"来做"""
    rec = state.get(c.d.isoformat(), {}).get("tzzb_distill")
    if rec:
        return _tzzb_distill_late(c, state, rec)
    if not morning and c.d == dt.date.today() and dt.datetime.now().strftime("%H:%M") < TZZB_DISTILL_AFTER:
        return "留到 00:00 收尾轮(当天账本 23:10 前才出齐)"
    if not c.can_llm():
        return "跳过(过截止)"
    if c.dry:
        return f"dry: 将跑 distill_daily(全部 11 人; 完成时记有数据名单 {tzzb_has_data(c)})"
    has = tzzb_has_data(c)     # 先取名单再蒸馏: 蒸馏期间晚到的账本不在名单里, 下一轮会被当新增补上(宁可多补一次不漏)
    rc, out = run([PY, "-X", "utf8", "scripts/tzzb/distill_daily.py", "--date", c.d.isoformat()], "tzzb distill_daily", 4000)
    if "ALL_DISTILL_DONE" in out:
        mark_done(state, c.d, "tzzb_distill", next((l for l in out.splitlines() if "哨兵" in l), "")[:200], ledgers=has)
        return f"完成(有数据 {len(has)} 家已记名单)"
    return "失败"


def _tzzb_distill_late(c, state, rec):
    """已蒸馏过: 有数据名单比蒸馏时多出来的(晚到账本)只补这几家; 旧记录(10/14 前, 无名单)以当前名单为基线不补跑"""
    now_has = tzzb_has_data(c)
    base = rec.get("ledgers")
    if base is None:
        if c.dry:
            return f"已完成(旧记录无名单, 将以当前 {len(now_has)} 家为基线)"
        rec["ledgers"] = now_has
        save_state(state)
        return f"已完成(旧记录, 补记基线名单 {len(now_has)} 家)"
    new = [x for x in now_has if x not in base]
    if not new:
        return "已完成"
    if not c.can_llm():
        return f"晚到 {new} 待补蒸馏(过截止)"
    if c.dry:
        return f"dry: 将补蒸馏晚到的 {new}(distill_daily --ledgers)"
    rc, out = run([PY, "-X", "utf8", "scripts/tzzb/distill_daily.py", "--date", c.d.isoformat(), "--ledgers", ",".join(new)],
                  f"tzzb 补蒸馏晚到 {new}", 2400)
    if "ALL_DISTILL_DONE" in out:
        rec["ledgers"] = sorted(set(base) | set(new))
        rec.setdefault("late", []).append({"at": dt.datetime.now().isoformat(timespec="seconds"), "ledgers": new})
        save_state(state)
        return f"补蒸馏晚到 {new} 完成"
    return f"补蒸馏晚到 {new} 失败"


# ---------- ⑥ 发哥收盘后当日核销 ----------
def step_fage(c):
    spec = ROOT / "downloads" / "wechat" / "fage" / c.d.isoformat() / "spec.md"
    t = c.md_text()
    sec = section(t, "#### 红旗大街发哥")
    if sec is not None and "【核销 当日】" in sec:
        return "已完成"
    if not spec.exists():
        return "未就绪(当日发哥盘前推演未挂载: 没贴链接或没做盘前蒸馏)"
    if not filled(section(t, "## 收评")):
        return "未就绪(收评还没进 md)"
    if not c.can_llm():
        return "跳过(过截止)"
    if c.dry:
        return "dry: 将跑发哥核销"
    prompt = (f"按 skills/fage-skill/SKILL.md 的「入口②: 收盘后当日核销」, 对 {c.d.isoformat()} 发哥盘前推演做当日核销: "
              f"推演要点在 {spec.relative_to(ROOT).as_posix()} 与 {c.md.relative_to(ROOT).as_posix()} 的 #### 红旗大街发哥 小节, "
              "当日实际看同一 md 的收评/涨停分析节(需要时可读 scripts/dfcf/paper/facts/ 当日事实包)。核销行写进该小节, 格式按 SKILL(【核销 当日】命中x 半命中x 打脸x 不可证x · ...), "
              "跨日判断只核当日能核的部分并注明后续观察。任务优先, 禁反问, 不改其他小节。最终回复最后一行只写: FAGE_VERIFY_DONE")
    ok, _ = claude(prompt, "checkmd-fage", "FAGE_VERIFY_DONE", timeout=1800)
    return "完成" if ok else "失败"


def step_lhb_backfill(d, dry):
    """龙虎榜历史回填(倒序 新→旧, 到 2025-01-07 补完后每晚只剩秒级空转): 只在 00:00 收尾轮调; 硬超时=到 06:55"""
    cmd = ["node", "scripts/lhb/backfill_lhb.mjs", "--from", LHB_BACKFILL_FROM, "--to", d.isoformat(),
           "--max-days", str(LHB_BACKFILL_MAX_DAYS), "--write", "--until", LHB_BACKFILL_UNTIL, "--gap", "10"]
    if dry:
        return "dry: 将跑 " + " ".join(cmd[1:])
    now = dt.datetime.now()
    hard = now.replace(hour=6, minute=55, second=0, microsecond=0)
    if now >= hard:
        return "跳过(已过 06:55)"
    rc, out = run(cmd, f"龙虎榜回填 --max-days {LHB_BACKFILL_MAX_DAYS}", int((hard - now).total_seconds()))
    j = _json_tail(out)
    if not j:
        return f"失败(exit {rc}, 无 JSON 输出)"
    return (f"{'完成' if rc == 0 else '失败' if rc == 1 else '反爬中止'}: {j.get('stop')}; 真抓 {j.get('fetched')} 天, 请求 {j.get('requests')} 次, "
            f"写 md {j.get('md_written')}, 无复盘只存json {len(j.get('no_fupan', []))}, 失败 {len(j.get('failed', []))}, 余 {j.get('remaining')} 天, "
            f"{j.get('secs')}s, push2 金丝雀 {'正常' if j.get('canary_end') else '异常'}")


def main():
    global LOG_FH
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--deadline")
    ap.add_argument("--only")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    b = _bb()
    d, off = target_date(a.date, b)
    if off:
        print(f"{d} 非交易日, 不做 check md")
        print("JSON:" + json.dumps({"date": d.isoformat(), "skip": "非交易日"}, ensure_ascii=False))
        return 0
    morning = dt.datetime.now().hour < 9
    deadline = a.deadline or ("07:45" if morning else None)

    # 单实例: 上一轮没跑完, 本轮直接退出(不排队, 下一轮会接上)
    if LOCK_F.exists():
        try:
            import psutil
            pid = int(LOCK_F.read_text().strip() or 0)
            if pid and psutil.pid_exists(pid):
                print(f"上一轮 check md 还在跑(pid {pid}), 本轮跳过")
                print("JSON:" + json.dumps({"date": d.isoformat(), "skip": "上一轮在跑"}, ensure_ascii=False))
                return 0
        except (ValueError, ImportError):
            pass
    LOCK_F.write_text(str(os.getpid()))
    LOG_FH = open(LOG_DIR / f"check_md_{d.isoformat()}.log", "a", encoding="utf-8")
    try:
        only = set(a.only.split(",")) if a.only else None
        state = load_state()
        days = [d] if a.date else [x for x in (prev_trading_day(d, b), d) if x.isoformat() >= CATCHUP_SINCE]
        summary, failed = {}, []
        for day in days:
            c = Ctx(day, deadline, a.dry)
            tag = "上一交易日遗留" if day != d else "今天"
            log(f"===== check md {day}({tag}) 开始(截止 {deadline or '不限'}{', dry' if a.dry else ''}) =====")
            if not c.md.exists():
                log(f"md 不存在: {c.md}(Java 交易日 md 生成任务没跑?), 跳过这一天")
                summary[day.isoformat()] = {"skip": "md 不存在"}
                continue
            steps = [("cls", lambda: step_cls(c, state)), ("lhb", lambda: step_lhb(c, state)),
                     ("ztpool", lambda: step_ztpool(c, state)), ("up", lambda: step_up(c, b)),
                     ("tzzb_sum", lambda: step_tzzb_sum(c)),
                     ("tzzb_distill", lambda: step_tzzb_distill(c, state, morning)), ("fage", lambda: step_fage(c))]
            if day != d:   # 遗留日: UP 步由今天那天的 3 天窗口一并覆盖, 不重复扫
                steps = [s for s in steps if s[0] != "up"]
            for name, fn in steps:
                if only and name not in only:
                    continue
                log(f"[{name}]")
                try:
                    c.results[name] = fn()
                except Exception as e:  # noqa: BLE001  单步异常不拖垮整轮
                    c.results[name] = f"失败(异常: {e})"
                log(f"[{name}] → {c.results[name]}")
            failed += [f"{day}:{k}" for k, v in c.results.items() if "失败" in v]
            summary[day.isoformat()] = c.results
        # 10/13 晚: 链改造 F 已上线——导师画像被蒸馏改动后, 画像目录(profile_index.md)要跟着补标注; 脚本增量(只标改过的节, 没改=零成本)
        if (not only or "profile_index" in only) and not a.dry:
            dl_ok = not deadline or dt.datetime.now().strftime("%H:%M") < deadline
            if dl_ok:
                log("[profile_index]")
                rc, out = run([PY, "-X", "utf8", "scripts/md/gen_profile_index.py", "--all"], "画像目录增量更新(F)", 1800)
                summary["profile_index"] = "完成" if rc == 0 else "失败(旧目录保留, 驱动器会跳过改过的节)"
                log(f"[profile_index] → {summary['profile_index']}")
        # 10/14 用户令: 龙虎榜历史回填只在 00:00 收尾轮末尾跑(不跟 18:00~23:00 抢), 06:40 后不开新日, 07:00 前必停(0915 链 07:50)
        if (not only or "lhb_backfill" in only) and not a.date and dt.datetime.now().hour < 6:
            log("[lhb_backfill]")
            summary["lhb_backfill"] = step_lhb_backfill(d, a.dry)
            log(f"[lhb_backfill] → {summary['lhb_backfill']}")
        # 10/15 用户令: 持仓票的关联妖股每天收盘后重挑(零 token; live_watch 次日开盘读最新一份)
        if (not only or "related" in only) and not a.dry:
            rc_y, _ = run(["node", "scripts/dfcf/related_yao.mjs", "--date", d.isoformat()], "关联妖股", 900)
            if rc_y == 0:   # 10/15: 再并入"中军/资金惯性"联动股(行情库零请求, 如牧原→温氏/东瑞股份)
                rc_y, _ = run([PY, "-X", "utf8", "scripts/dfcf/related_inertia.py", "--date", d.isoformat()], "资金惯性联动股", 300)
            summary["related"] = "完成" if rc_y == 0 else "失败"
            log(f"[related] → {summary['related']}")
        # 10/15 用户令: B 线(导师真人) vs A 线(链) 对照全表; 15:05 微信日报时 tzzb 当天多半还没抓, 这里晚间重算一版(零 token)
        if (not only or "realvs" in only) and not a.dry:
            rc_r, _ = run(["node", "scripts/dfcf/paper/real_vs_chain.mjs", "--date", d.isoformat()], "真人对照表", 120)
            summary["realvs"] = f"scripts/dfcf/paper/real_vs_chain/{d.isoformat()}.md" if rc_r == 0 else "失败"
            log(f"[realvs] → {summary['realvs']}")
        # 10/14 用户令(爬虫要主动报问题, 不能等用户发现): 每轮末尾零 token 采集健康巡检, 红/黄写进本轮摘要, 报告 scripts/health/reports/<日>.md
        if not a.dry:
            rc_h, out_h = run([PY, "-X", "utf8", "scripts/health/daily_health.py"], "采集健康巡检", 300)
            hj = _json_tail(out_h)
            summary["health"] = f"红 {hj.get('red', '?')} / 黄 {hj.get('yellow', '?')}(详见 {hj.get('report', 'scripts/health/reports/')})"
            log(f"[health] → {summary['health']}")
        log(f"===== 本轮结束: {json.dumps(summary, ensure_ascii=False)} =====")
        print("JSON:" + json.dumps(summary, ensure_ascii=False))
        return 1 if failed else 0
    finally:
        if LOG_FH:
            LOG_FH.close()
        if LOCK_F.exists() and LOCK_F.read_text().strip() == str(os.getpid()):
            LOCK_F.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
