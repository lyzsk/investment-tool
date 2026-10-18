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
  --only postclose: 10/17 A14① 盘后合成——cls 核对/tzzb 推测层/发哥核销三步的 LLM 活合成 1 个 claude 会话(全量轮默认就是合成; --only cls 等单点一步=照旧单独会话)
  --only index_pit: A7 指数成分/行业时点表动态更新(调样电报/日历/周六对账命中才刷新, 增量写库; 不看交易日)
  --only slot_weekly: A9 时段周检(零 token, 只在周六/周日跑, 不看交易日; 产物 scripts/dfcf/paper/reports/slot_weekly_<yyyyMMdd>.md)
  --date 缺省: 09:00 前(含 00:00 收尾轮)=上一个交易日, 之后=今天; 非交易日直接退出
  --deadline: 过了这个时刻不再开新的 claude 会话(早上兜底轮 07:45, 给 07:50 的 0915 链让路); 缺省=早上轮 07:45, 晚上不限
出口: 0=本轮正常结束(含"有步骤没就绪") 1=有步骤执行失败 2=用法/环境错 3=主步骤正常但收尾步骤有失败(10/17 M14); 末行 JSON:{...} 供 Java 记日志
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
UP_WINDOW_DAYS = 3        # UP 步只追最近 3 天的欠账(晚到稿/顺延稿); 更早的历史欠账归 backfill
TZZB_DISTILL_AFTER = "23:30"   # tzzb 账本 15:10~23:10 每小时抓, 当天 23:30 前不蒸馏当天(没出齐); 00:00 收尾轮(按上一交易日算)来做(单会话 11 人, 做完不再重做)
CATCHUP_SINCE = "2026-10-13"   # 补"上一个交易日"的起点: 更早的日子由人工/子代理做过, 无状态记录, 不回头重做
LHB_READY_HHMM = "18:00"       # 交易所 16:30~17:30 出齐(公开口径), 东财晚几分钟; 18:00 前抓的 list.json 视为临时版, 下一轮重抓覆盖
LHB_BACKFILL_FROM = "2025-01-07"
LHB_BACKFILL_MAX_DAYS = 150    # 10/14 实测(全量 425 天): 每天 3~5 次请求/平均 16s(含 10s 日间隔), 0 限流; 150 天≈40 分钟/≈500 次; 历史已补完, 现每晚空转 ≈2s
LHB_BACKFILL_UNTIL = "06:40"   # 06:40 后不开新的一天(单日 ≤20s), 07:00 前必停

sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import mentors as _MENTORS  # noqa: E402  10/17 导师登记表(唯一真源; scripts/lib 已在 sys.path)
UPS = [(m, "#### " + _MENTORS.get(m)["name"]) for m in _MENTORS.ids("UP")]   # 10/17: 原写死三 UP, 改读登记表(顺序同)
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


def _mkt_off(d, hol):
    """10/17 健壮性 M13: A 股交易所口径的休市日(周末一律休市; 调休上班的周六也不开市)。
    b.is_off_day 是"工作日"口径(holiday-cn isOffDay=false 的调休周六算上班), 只给 B站时间窗用, 不能判交易日"""
    return d.weekday() >= 5 or bool(hol.get(d.isoformat(), False))


def target_date(arg, b):
    hol = b.load_holidays()
    if arg:
        d = dt.date.fromisoformat(arg)
        return d, _mkt_off(d, hol)
    now = dt.datetime.now()
    d = now.date()
    if now.hour < 9:                      # 次日早上的兜底轮: 补的是上一个交易日
        d -= dt.timedelta(days=1)
        while _mkt_off(d, hol):
            d -= dt.timedelta(days=1)
        return d, False
    return d, _mkt_off(d, hol)


def prev_trading_day(d, b):
    hol = b.load_holidays()
    x = d - dt.timedelta(days=1)
    while _mkt_off(x, hol):
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
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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
    def __init__(self, d, deadline, dry, batch=False):
        self.d, self.deadline, self.dry = d, deadline, dry
        self.md = md_path(d)
        self.results = {}       # step -> 完成/跳过/失败 + 原因
        self.tzzb_has_data = None   # tzzb_sum 本轮算出的"有数据账本"名单(⑤补蒸馏用); None=本轮没算
        self.batch = batch      # 10/17 A14①: True=cls/tzzb 推测层/fage 的 LLM 活先登记, 由 postclose 步合成 1 个会话
        self.jobs = []

    def can_llm(self):
        return not self.deadline or dt.datetime.now().strftime("%H:%M") < self.deadline

    def md_text(self):
        return self.md.read_text(encoding="utf-8") if self.md.exists() else ""


# ---------- 10/17 A14①「盘后合成」: cls 核对 / tzzb 推测层 / 发哥核销 三步都是读当天 md 写各自小节 → 同一轮里合成 1 个 claude 会话 ----------
POSTCLOSE_STEPS = ("cls", "tzzb_sum", "fage")
POSTCLOSE_LABEL = {"cls": "cls 四小节核对", "tzzb_sum": "tzzb 推测层", "fage": "发哥当日核销"}


def llm_task(c, step, tag, sentinel, body, tail, timeout, on_ok, fail_msg="失败"):
    """batch 模式=登记待合成(返回占位结果, 由 step_postclose 回填); 否则=立即单独跑(与改造前逐字相同的提示词)"""
    if c.batch:
        c.jobs.append({"step": step, "tag": tag, "sentinel": sentinel, "body": body, "tail": tail, "timeout": timeout, "on_ok": on_ok, "fail": fail_msg})
        return "待盘后合成"
    ok, out = claude(body + tail, tag, sentinel, timeout=timeout)
    return on_ok(out) if ok else fail_msg


def step_postclose(c):
    if c.dry:
        names = [s for s in POSTCLOSE_STEPS if str(c.results.get(s, "")).startswith("dry: 将")]
        return f"dry: 将把 {'+'.join(names)} 合成 1 个会话" if len(names) >= 2 else ("dry: 单步照旧" if names else "dry: 无 LLM 任务")
    jobs, c.jobs = c.jobs, []
    if not jobs:
        return "无待合成任务"
    if not c.can_llm():
        for j in jobs:
            c.results[j["step"]] = "跳过(已过截止时刻)"
        return f"跳过(已过截止, {len(jobs)} 项未做)"
    if len(jobs) == 1:      # 只有一项: 按原单步提示词/标签跑, 行为与改造前一致
        j = jobs[0]
        ok, out = claude(j["body"] + j["tail"], j["tag"], j["sentinel"], timeout=j["timeout"])
        c.results[j["step"]] = j["on_ok"](out) if ok else j["fail"]
        return f"单项 {j['step']}: {c.results[j['step']]}"
    parts = [f"### 任务{i}: {POSTCLOSE_LABEL[j['step']]}(完成标记 {j['sentinel']})\n{j['body']}" for i, j in enumerate(jobs, 1)]
    prompt = (f"本会话是 check md「盘后合成」({c.d.isoformat()}): 依次完成下面 {len(jobs)} 个互相独立的任务。它们都是读当天 md 写各自的小节, "
              "互不改对方的小节; 一个任务做完再做下一个(按编号顺序)。某个任务做不成就跳过它、继续后面的任务, 做不成的任务不写它的完成标记。"
              "读文件只读需要的段, Bash 输出过长先截断。\n\n" + "\n\n".join(parts) + "\n\n"
              "最终回复(会话最后一条消息)的格式: 每个任务先用 1~5 行说明做了什么(cls 核对写修了什么, 没问题写'无需修正'; tzzb 推测层逐行复述 SPEC_OK 行); "
              "然后把已完成任务的完成标记各占一行单独写出(这一行只写标记本身); 最后一行只写: POSTCLOSE_DONE")
    from claude_call import call, LEAN_ARGS
    t0 = time.time()
    sents = [j["sentinel"] for j in jobs]
    r = call(prompt, tag="checkmd-postclose", permission="skip", timeout=sum(j["timeout"] for j in jobs), sentinels=sents + ["POSTCLOSE_DONE"],
             extra_args=LEAN_ARGS + ["--tools", "Read,Write,Edit,Grep,Glob,Bash"])
    out = r.result or ""
    res = []
    for j in jobs:
        hit = bool(r.sentinels.get(j["sentinel"]))
        c.results[j["step"]] = j["on_ok"](out) if hit else j["fail"]
        res.append(f"{j['step']} {'✓' if hit else '✗'}")
    log(f"  claude[checkmd-postclose] {' / '.join(res)} {time.time() - t0:.0f}s ${r.cost_usd:.2f}"
        + ("" if all(r.sentinels.get(s) for s in sents) else f" | {' | '.join(r.errors)[:200]}"))
    return f"合成 {len(jobs)} 项: {' / '.join(res)}" + (" (有项目失败)" if not all(r.sentinels.get(s) for s in sents) else "")


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
              "缺图或解析失败按 SKILL 的补齐办法处理。任务优先, 禁反问, 不要改其他小节。")
    tail = "最终回复(会话最后一条消息)先用 3~8 行列出修了什么(没问题就写'无需修正'), 最后一行只写: CLS_CHECK_DONE"

    def ok(out):
        mark_done(state, c.d, "cls", ("盘后合成会话" if c.batch else (out.strip().splitlines()[0][:200] if out.strip() else "")))
        return "完成"
    return llm_task(c, "cls", "checkmd-cls", "CLS_CHECK_DONE", prompt, tail, 2400, ok)


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
    try:   # 10/16 用户令: 实测东财每天几点出齐——每次抓都记 时刻/只数/条数(16:00~18:00 每 20 分钟一轮的盘后抓取任务写这里), 攒一周定正式时刻
        with open(ROOT / "downloads" / "lhb" / "ready_log.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"day": c.d.isoformat(), "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "rc": rc,
                                 "stocks": j.get("stocks"), "records": j.get("records")}, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass
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
    if rc == 0 and str(j.get("md") or "").startswith("已写"):   # 10/16 修: ST 小节同时写时 md="已写+ST股已写", 原 == 判成失败
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
    # 10/17 A13: 先按导师登记表补齐 + 排序同花顺小节(模板里不再需要写死导师名; 无数据写占位), 再按小节生成
    if not c.dry:
        run([PY, "-X", "utf8", "scripts/tzzb/order_tzzb_sections.py", "--date", c.d.isoformat(), "--write"], "同花顺小节补齐/排序(前)", 120)
    # 只做 md 骨架里已有小节的高手(tzzb_ledgers.json 含观察中的新账本, 还没建 skill/md 小节的不写)
    heads = {re.sub(r"\s+", "", m.group(1)) for m in re.finditer(r"^#### (.+)$", c.md_text(), re.M)}
    ledgers = [L for L in ledgers if re.sub(r"\s+", "", L["name"]) in heads]
    if c.dry:
        return f"dry: 将跑 gen_tzzb_md ×{len(ledgers)} + 推测层"
    run(["node", "scripts/quotes/fetch_quotes.mjs", "--market", "cb", "--trends-all"], "cb 分时归档(土豆 sum 前置)", 900)
    has_data, gen_fail = [], []
    for L in ledgers:
        rc, out = run(["node", "scripts/tzzb/gen_tzzb_md.mjs", "--ledger", L["ledger"], "--date", c.d.isoformat(), "--write"],
                      f"gen_tzzb_md {L['ledger']}", 300)
        if rc == 0 and "覆盖" in out:
            has_data.append(L)
        elif rc != 0:
            gen_fail.append(L["ledger"])   # 10/17 健壮性 M15: 生成失败原先被当"无数据"吞掉
    _ex = _MENTORS.excluded()   # 10/18: 退出 paper 的导师只做零 token 维护(硬数据层照写), 不蒸馏、不补【推测】
    c.tzzb_has_data = sorted(L["ledger"] for L in has_data if L.get("kind") == "pos" and L["ledger"] not in _ex)
    run([PY, "-X", "utf8", "scripts/tzzb/order_tzzb_sections.py", "--date", c.d.isoformat(), "--write"], "同花顺小节补齐/排序(后: 刷新占位)", 120)
    t = c.md_text()
    todo = []
    for L in has_data:
        sec = None
        for m in re.finditer(r"^#### (.+)$", t, re.M):
            if re.sub(r"\s+", "", m.group(1)) == re.sub(r"\s+", "", L["name"]):
                sec = section(t, m.group(0))
                break
        if sec is not None and "【推测】" not in sec and L["ledger"] not in _ex:
            todo.append(L)
    head = f"有数据 {len(has_data)}/{len(ledgers)}" + (f"; gen_tzzb_md 失败 {gen_fail}" if gen_fail else "")
    if not todo:
        return f"{head}, 推测层已齐"
    if not c.can_llm():
        return f"{head}, 推测层待补 {[L['ledger'] for L in todo]}(过截止)"
    names = ", ".join(f"{L['ledger']}(#### {L['name']})" for L in todo)
    prompt = (f"按 skills/tzzb-skill/workflows/sum.md 的【推测】层规则, 为 {c.d.isoformat()} 补写以下高手在 "
              f"{c.md.relative_to(ROOT).as_posix()} 对应小节末尾的【推测】段: {names}。"
              "硬数据层已由 gen_tzzb_md 写好, 只读不改; 推测必须带锚点, 原文/数据没有的不硬凑。逐人串行, 每完成一人打印一行 SPEC_OK <ledger>。")
    tail = "最终回复(会话最后一条消息)开头逐行复述全部 SPEC_OK 行, 最后一行只写: TZZB_SPEC_DONE"
    r = llm_task(c, "tzzb_sum", "checkmd-tzzb-spec", "TZZB_SPEC_DONE", prompt, tail, 3000,
                 lambda out: f"{head}, 推测层补 {len(todo)} 人完成", f"{head}, 推测层补 {len(todo)} 人失败")
    return f"{head}, 推测层补 {len(todo)} 人待盘后合成" if r == "待盘后合成" else r


# ---------- ⑦ 07 复盘(10/16 晚用户定; 10/17 定稿: 答案到了就跑 + 到点兜底) ----------
# 链日 D 的 07 优先拿 D 的标准答案复盘; 等到兜底时刻答案仍没到(如 tzzb 选手当天空仓不报单/没上传、UP 没发视频)就不再等, 按"无答案"跑:
#   tzzb 导师(含土豆转债) = 账本 lastNavDate ≥ D(D 的成交日内/隔夜上传都行, 次日 15:10 起的抓取会补上)
#   桃哥 / 天哥 = D 当天视频总结进 D 的 md 小节
#   卢本圆 = 他次日早盘前发的视频讲 D 的操作, 挂在下一交易日 md 的本人小节 → 下一交易日 md 小节有内容即 D 的答案到了
#   对照组 = 设计上没有真人答案, D 收盘后的市场事实齐了就跑(无需等)
#   兜底时刻: UP 22:00 / tzzb 23:40(同花顺最后一轮 23:10 抓取跑完之后; 23:40 专门的 --only review07 轮, 兜底链通常 3~6 条, 23:59 前跑完); 卢本圆的答案本来就在次日, 兜底=次日 22:00
#   保险: 等满 REVIEW_GIVEUP_TD 个交易日仍没跑成(停机/漏轮)也按无答案跑
# 每轮扫 今天 + 往前几个交易日里还没 07 的链日(补停机漏掉的); 当天没跑链(无 live-<日> 目录, 如停更的冲5000w)=不跑
# 发起=交给 review07_queue.py 排队执行器(无窗口, 同时最多 4 条, 输出进 run_dir/review07.log); 每链日只跑一次(已有 07_review.md=跳过), 排队后 4 小时仍无产物重发, 最多 2 次
REVIEW_UP_HEAD = dict(UPS)
REVIEW_NEXT_DAY = {"lubenyuan"}     # 答案在下一交易日 md
REVIEW_NO_LABEL = {"control"}       # 永远没有答案
REVIEW_GIVEUP_TD = 2                # 保险: 漏轮/停机时最多等 N 个交易日
REVIEW_FALLBACK_UP, REVIEW_FALLBACK_TZZB = "22:00", "23:40"   # 兜底时刻(答案日当天); 10/17 审计高-1: tzzb 22:10 那轮抓取可能 22:34 才完 → 兜底挪到 23:10 那轮抓取之后的 23:40(专门定时)
REVIEW_SINCE = "2026-10-15"         # 全链 07 从 10/15 起才有; 更早的链日不回头补


def _review_chains():
    """10/17: 原解析 accounts.mjs 文本, 改读导师登记表(UP + tzzb + 对照, 顺序同 accounts 槽位)"""
    return _MENTORS.ids()


def _next_td(d, hol):
    x = d + dt.timedelta(days=1)
    while _mkt_off(x, hol):
        x += dt.timedelta(days=1)
    return x


def _td_between(a, b_, hol):
    """a 之后到 b_(含)的交易日数"""
    n, x = 0, a
    while x < b_:
        x += dt.timedelta(days=1)
        n += 0 if _mkt_off(x, hol) else 1
    return n


def _review_label(sk, day, today, hol):
    """(答案到了?, 说明)"""
    d8 = day.strftime("%Y%m%d")
    if sk in REVIEW_NO_LABEL:
        return (dt.datetime.now() >= dt.datetime.combine(day, dt.time(15, 30)) or day < today), "对照组无真人答案, 收盘后即跑"
    if sk in REVIEW_UP_HEAD:
        md_day = _next_td(day, hol) if sk in REVIEW_NEXT_DAY else day
        f = md_path(md_day)
        txt = f.read_text(encoding="utf-8") if f.exists() else ""
        return filled(section(txt, REVIEW_UP_HEAD[sk]) or ""), ("次日视频已进下一交易日 md" if sk in REVIEW_NEXT_DAY else "当日视频已进 md")
    try:
        nav = json.loads((ROOT / "downloads" / "tzzb" / sk / "state.json").read_text(encoding="utf-8")).get("lastNavDate", "")
    except (OSError, ValueError):
        nav = ""
    return str(nav) >= d8, "真人账本已到"


def _wait_last_fetch(today, hol):
    """10/17 审计 Q-1: 23:40 兜底时 23:10 那轮同花顺抓取可能还没抓到某些导师(18 位约 30 分钟) → 兜底前先等这轮把"还没答案"的导师抓完。
    只等: 今天有链、还没 07、账本还没到今天、且这轮(23:10 起)还没抓到的 tzzb 导师; 最多等到 23:52(留 07 跑完的时间), 5 分钟没进展就不等。
    这轮根本没在跑(没有任何导师 23:10 后被抓过、也没有抓取锁)=不等。返回说明"""
    if _mkt_off(today, hol):
        return ""
    d8 = today.strftime("%Y%m%d")
    rnd = dt.datetime.combine(today, dt.time(23, 10))
    stop = dt.datetime.combine(today, dt.time(23, 52))
    lock = ROOT / "downloads" / "tzzb" / "_guard" / "fetch.lock"

    def fetched_at(sk):
        try:
            s = json.loads((ROOT / "downloads" / "tzzb" / sk / "state.json").read_text(encoding="utf-8"))
            t = dt.datetime.fromisoformat(s["lastFetch"].replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
            return t, str(s.get("lastNavDate") or "")
        except Exception:   # noqa: BLE001
            return None, ""
    tz = [sk for sk in _MENTORS.ids("tzzb") if (ROOT / "results" / f"{sk}_chain" / f"live-{d8}").exists()
          and not (ROOT / "results" / f"{sk}_chain" / f"live-{d8}" / "slots" / "review" / "07_review.md").exists()]
    waited, last_n = 0, None
    while True:
        st = {sk: fetched_at(sk) for sk in tz}
        need = [sk for sk, (t, nav) in st.items() if nav < d8 and (t is None or t < rnd)]
        running = lock.exists() or any(t and t >= rnd for t, _ in st.values())
        if not need or not running or dt.datetime.now() >= stop:
            break
        if last_n is not None and len(need) == last_n and waited >= 300 and not lock.exists():
            break
        if len(need) != last_n:
            last_n, waited = len(need), 0
        time.sleep(30)
        waited += 30
    return (f"等最后一轮抓取: 仍未抓到 {need}" if need and running else "") if tz else ""


def step_review07(c, state):
    now, today = dt.datetime.now(), dt.date.today()
    hol = _bb().load_holidays()
    if not c.dry and dt.time(23, 40) <= now.time() < dt.time(23, 59) and c.d == today:
        w = _wait_last_fetch(today, hol)
        if w:
            log(f"  [review07] {w}(到点仍兜底)")
        now = dt.datetime.now()
    days, x = [c.d], c.d
    if c.d >= today - dt.timedelta(days=1):   # 今天/昨天那轮顺带扫更早还没核销的链日
        for _ in range(REVIEW_GIVEUP_TD + 2):
            x -= dt.timedelta(days=1)
            while _mkt_off(x, hol):
                x -= dt.timedelta(days=1)
            if x.isoformat() >= max(CATCHUP_SINCE, REVIEW_SINCE):
                days.append(x)
    started, done, waiting, skipped, jobs = [], 0, [], [], []
    for day in days:
        d8 = day.strftime("%Y%m%d")
        rec = state.setdefault(day.isoformat(), {}).setdefault("review07", {})
        # 整日重跑过的日子(scripts/temp/rerun_<日>/, 如 10/16): 账本已换成重跑结果, 07 复盘重跑的 asof 目录; 合入(MERGED)前不跑
        rerun = ROOT / "scripts" / "temp" / f"rerun_{d8}"
        if rerun.exists() and not (rerun / "MERGED").exists():
            waiting.append(f"{day:%m-%d} 全部(等重跑合入)")
            continue
        for sk in _review_chains():
            rd = ROOT / "results" / f"{sk}_chain" / (f"asof-{d8}" if rerun.exists() else f"live-{d8}")
            if not rd.exists():
                continue
            if (rd / "slots" / "review" / "07_review.md").exists() or (rd / "07_review.md").exists():
                done += 1
                r = rec.setdefault(sk, {})
                if not r.get("ingested") and not c.dry and (r.get("at") or sk != "taoge"):   # 本步发起的 07 → 经 Java 接口入链路表(应用未重启/接口失败=下轮再试)
                    try:
                        import urllib.parse, urllib.request
                        q = urllib.parse.urlencode({"skill": sk, "mode": "ASOF" if rerun.exists() else "LIVE", "date": d8, "slot": "review"})
                        with urllib.request.urlopen(urllib.request.Request(f"http://localhost:8888/api/paper/chain/ingest?{q}", method="POST"), timeout=60) as resp:
                            if json.loads(resp.read().decode("utf-8")).get("code") == "200":
                                r["ingested"] = dt.datetime.now().isoformat(timespec="seconds")
                                save_state(state)
                    except Exception as e:   # noqa: BLE001
                        log(f"  07 入库 {sk} {day} 未成功(下轮重试): {str(e)[:120]}")
                continue
            ready, why = _review_label(sk, day, today, hol)
            if not ready:
                ans_day = _next_td(day, hol) if sk in REVIEW_NEXT_DAY else day      # 答案应该出现的那天
                cut = REVIEW_FALLBACK_TZZB if sk not in REVIEW_UP_HEAD else REVIEW_FALLBACK_UP
                if dt.datetime.now() >= dt.datetime.combine(ans_day, dt.time(int(cut[:2]), int(cut[3:]))) or _td_between(day, today, hol) >= REVIEW_GIVEUP_TD:
                    ready, why = True, f"兜底(到 {ans_day:%m-%d} {cut} 答案仍没到)"
            if not ready:
                waiting.append(f"{sk}@{day:%m-%d}")
                continue
            r = rec.get(sk) or {}
            if r.get("at") and (now - dt.datetime.fromisoformat(r["at"])).total_seconds() < 4 * 3600:
                waiting.append(f"{sk}@{day:%m-%d}(排队/跑着)")
                continue
            if r.get("n", 0) >= 2:
                skipped.append(f"{sk}@{day:%m-%d}(已发 2 次仍无产物)")
                continue
            if c.dry or not c.can_llm():
                waiting.append(f"{sk}@{day:%m-%d}({'dry 将跑: ' + why if c.dry else '过截止'})")
                continue
            jobs.append({"skill": sk, "date": d8, "asof": str(rerun / "sb") if rerun.exists() else ""})
            rec[sk] = {"at": now.isoformat(timespec="seconds"), "n": r.get("n", 0) + 1, "why": why}
            started.append(f"{sk}@{day:%m-%d}({why})")
    if jobs:   # 交给排队执行器: 同时最多 REVIEW07_MAX(默认 4)条, 跑完一条补一条(scripts/md/review07_queue.py; 耗时记 logs/review07_runs.jsonl)
        sys.path.insert(0, str(ROOT / "scripts" / "md"))
        import review07_queue
        review07_queue.enqueue(jobs)
        save_state(state)
    return (f"新排队 {len(started)}: {', '.join(started) or '-'} | 已有 {done} | 等答案 {', '.join(waiting) or '-'}"
            + (f" | 不跑 {', '.join(skipped)}" if skipped else ""))


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
                               cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            continue
        if r.returncode == 0 and r.stdout.strip():
            got.append(L["ledger"])
    c.tzzb_has_data = sorted(x for x in got if x not in _MENTORS.excluded())   # 10/18: 退出 paper 的不蒸馏
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
    # 10/17 晚用户定: 当天没报单(账本没有当天记录 = md 小节无硬数据)的导师不调模型; 报了单但持仓不动 / 空仓无操作的照常蒸馏(分析他为什么拿着)
    if not has:
        mark_done(state, c.d, "tzzb_distill", "当日全部导师无账本记录, 未调模型", ledgers=[])
        return "完成(当日无人报单, 未调模型)"
    rc, out = run([PY, "-X", "utf8", "scripts/tzzb/distill_daily.py", "--date", c.d.isoformat(), "--ledgers", ",".join(has)], f"tzzb distill_daily({len(has)} 人有当日记录)", 4000)
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
              "跨日判断只核当日能核的部分并注明后续观察。任务优先, 禁反问, 不改其他小节。")
    return llm_task(c, "fage", "checkmd-fage", "FAGE_VERIFY_DONE", prompt, "最终回复最后一行只写: FAGE_VERIFY_DONE", 1800, lambda out: "完成")


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


def step_slot_weekly(date_arg, dry):
    """A9 时段周检: 链 sys_job 时段 vs 真人出手时段, 产物 scripts/dfcf/paper/reports/slot_weekly_<yyyyMMdd>.md; 出口 4=有错配(提醒, 不算失败)"""
    if dt.date.today().weekday() < 5:
        msg = "跳过(只在周六/周日跑)"
    else:
        cmd = [PY, "-X", "utf8", "scripts/dfcf/paper/slot_weekly.py"] + (["--date", date_arg] if date_arg else []) + (["--dry"] if dry else [])
        rc, out = run(cmd, "时段周检 slot_weekly" + (" --dry" if dry else ""), 600)
        j = _json_tail(out)
        if rc in (0, 4) and "error" not in j:
            msg = f"完成(错配 {len(j.get('mismatch') or [])} 条链: {','.join(j.get('mismatch') or []) or '无'}; {j.get('report') or 'dry 未落盘'})"
        else:
            msg = f"失败(exit {rc}: {j.get('error', '')[:120]})"
    log(f"[slot_weekly] → {msg}")
    return msg


def step_index_pit(date_arg, dry):
    """A7(10/17): 指数成分/行业时点表动态更新(scripts/market/index_rebalance.py run; 零 token): 电报调样事件/日历/周六对账命中才刷新, 增量写库"""
    cmd = [PY, "-X", "utf8", "scripts/market/index_rebalance.py", "run"] + (["--date", date_arg] if date_arg else []) + (["--dry"] if dry else [])
    rc, out = run(cmd, "指数时点表 index_pit" + (" --dry" if dry else ""), 3600)
    j = _json_tail(out)
    msg = (("刷新完成" if j.get("due") else "今天不用刷新") + (f"({'; '.join(j.get('why') or [])[:120]})" if j.get("why") else "")
           + ("; 部分源失败/部分指数冻结未更新(如国证), 其余已更新, 看日志" if j.get("rc") == 4 else "; 变动超 20% 请看日志" if rc == 4 else "")) if rc in (0, 4) else f"失败(exit {rc})"
    log(f"[index_pit] → {msg}")
    return msg


def main():
    global LOG_FH
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--deadline")
    ap.add_argument("--only")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # 10/17 A9: 时段周检(零 token, 只读; 只在周六/周日跑) — 周末非交易日, 必须在交易日判定之前处理; 不占单实例锁
    if a.only and "slot_weekly" in a.only.split(","):
        rest = [x for x in a.only.split(",") if x != "slot_weekly"]
        sw = step_slot_weekly(a.date, a.dry)
        if not rest:
            print("JSON:" + json.dumps({"slot_weekly": sw}, ensure_ascii=False))
            return 1 if sw.startswith("失败") else 0
        a.only = ",".join(rest)
    # 10/17 A7: 指数时点表(交易日看调样事件/日历, 周六对账) — 不看交易日, 不占单实例锁
    if a.only and "index_pit" in a.only.split(","):
        rest = [x for x in a.only.split(",") if x != "index_pit"]
        ip = step_index_pit(a.date, a.dry)
        if not rest:
            print("JSON:" + json.dumps({"index_pit": ip}, ensure_ascii=False))
            return 1 if ip.startswith("失败") else 0
        a.only = ",".join(rest)
    b = _bb()
    d, off = target_date(a.date, b)
    if off:
        print(f"{d} 非交易日, 不做 check md")
        print("JSON:" + json.dumps({"date": d.isoformat(), "skip": "非交易日"}, ensure_ascii=False))
        return 0
    morning = dt.datetime.now().hour < 9
    deadline = a.deadline or ("07:45" if morning else None)

    # 单实例: 上一轮没跑完, 本轮直接退出(不排队, 下一轮会接上)
    # 10/17 审计 Q-2: 原来先 exists 再 write 不是原子的, 16:40/17:40 lhb 与 review07 同分钟起会双双拿到锁 → 改 O_EXCL 原子创建, 持有者已死才清掉重试
    import psutil
    for _try in range(2):
        try:
            fd = os.open(str(LOCK_F), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                pid = int(LOCK_F.read_text().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            # pid 还没写进去(对方刚建锁)也算在跑; 只有 pid 已死, 或空锁放了超过 60 秒, 才算残留
            stale = (pid and not psutil.pid_exists(pid)) or (not pid and time.time() - LOCK_F.stat().st_mtime > 60 if LOCK_F.exists() else True)
            if not stale or _try:
                print(f"上一轮 check md 还在跑(pid {pid}), 本轮跳过")
                print("JSON:" + json.dumps({"date": d.isoformat(), "skip": "上一轮在跑"}, ensure_ascii=False))
                return 0
            LOCK_F.unlink(missing_ok=True)   # 持有者已死: 清掉再抢一次
    LOG_FH = open(LOG_DIR / f"check_md_{d.isoformat()}.log", "a", encoding="utf-8")
    try:
        only = set(a.only.split(",")) if a.only else None
        # 10/17 A14①: 全量轮 / --only postclose / --only 里同时点了 ≥2 个盘后步 → 三步的 LLM 活合成 1 个会话; 单点一步(--only cls)=照旧单独跑
        # 10/17 晚: 合成默认关(用户问"之前 3 个是为了什么"——三步本来就是串行, 合成省 2 次开头费但后面背前面的上下文、一个坏了连坐;
        #   在省钱被证实前回到三步各自独立的会话); 要试合成: --only postclose
        batch = only is not None and "postclose" in only
        if only is not None and batch:
            only = only | ({"postclose"} | (set(POSTCLOSE_STEPS) if "postclose" in only else set()))
        state = load_state()
        days = [d] if a.date else [x for x in (prev_trading_day(d, b), d) if x.isoformat() >= CATCHUP_SINCE]
        summary, failed = {}, []
        for day in days:
            c = Ctx(day, deadline, a.dry, batch)
            tag = "上一交易日遗留" if day != d else "今天"
            log(f"===== check md {day}({tag}) 开始(截止 {deadline or '不限'}{', dry' if a.dry else ''}) =====")
            if not c.md.exists():
                log(f"md 不存在: {c.md}(Java 交易日 md 生成任务没跑?), 跳过这一天")
                summary[day.isoformat()] = {"skip": "md 不存在"}
                continue
            # 10/17 A14①: fage 提到 tzzb_distill 之前(两者无依赖), 让 cls/tzzb 推测层/fage 在 postclose 合成; tzzb_distill 仍在推测层之后
            steps = [("cls", lambda: step_cls(c, state)), ("lhb", lambda: step_lhb(c, state)),
                     ("ztpool", lambda: step_ztpool(c, state)), ("up", lambda: step_up(c, b)),
                     ("tzzb_sum", lambda: step_tzzb_sum(c)), ("fage", lambda: step_fage(c)),
                     ("postclose", lambda: step_postclose(c)),
                     ("tzzb_distill", lambda: step_tzzb_distill(c, state, morning)),
                     ("review07", lambda: step_review07(c, state))]
            if not batch:
                steps = [s for s in steps if s[0] != "postclose"]
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
        # 10/16 用户发现: report.html 15:05 由 matcher EOD 生成时 tzzb 当天净值还没抓(15:10~23:10 陆续到), "相对导师真人"口径缺当天
        #  → 每轮 check md 末尾重生成一次(零 token, 读本地账本+tzzb)
        if (not only or "report" in only) and not a.dry:
            rc_p, _ = run(["node", "scripts/dfcf/paper/report.mjs"], "paper 报告重生成(带当天导师真人净值)", 300)
            summary["report"] = "完成" if rc_p == 0 else "失败"
        # 10/16 用户令: 全市场期货每日收盘后存档(零 token, 1 次请求; 盘中由 facts/live_watch 现场拉)
        if (not only or "futures" in only) and not a.dry:
            rc_f, _ = run(["node", "scripts/quotes/futures.mjs", "--write", "--date", d.isoformat()], "期货存档", 120)
            summary["futures"] = "完成" if rc_f == 0 else "失败"
        # 10/16 晚用户令 B8: paper skill 权重初版直接上线(零 token; 先重算拟人度累计, 再算权重; 日报读最新一份)
        if (not only or "weights" in only) and not a.dry:
            run([PY, "-X", "utf8", "scripts/dfcf/paper/mimicry_score.py", "--since", "2026-10-08", "--quiet"], "拟人度累计重算", 1800)
            rc_w, _ = run([PY, "-X", "utf8", "scripts/dfcf/paper/skill_weights.py", "--date", d.isoformat()], "skill 权重(初版)", 1800)
            summary["weights"] = "完成" if rc_w == 0 else "失败"
            # 10/16 晚 B6: 反思回注触发判定(连续偏离/回撤; 驱动器次日读 reflection/<日>.json, 开关 CHAIN_REFLECT_TRIGGER)
            rc_rt, _ = run([PY, "-X", "utf8", "scripts/dfcf/paper/reflect_trigger.py", "--date", d.isoformat()], "反思回注触发判定", 900)
            summary["reflect_trigger"] = "完成" if rc_rt == 0 else "失败"
            # 10/17 ② 决策质量产物(时段预算/T 法/相似市况/规则标注/override 锁层; 零 token ~17s): 给下一交易日用; 各功能开关在 chain_flags.txt
            try:
                hol, nx = b.load_holidays(), d + dt.timedelta(days=1)
                while b.is_off_day(nx, hol):
                    nx += dt.timedelta(days=1)
                rc_q, _ = run([PY, "-X", "utf8", "scripts/dfcf/paper/quality_daily.py", "--date", nx.isoformat()], f"决策质量产物({nx})", 600)
                summary["quality_daily"] = "完成" if rc_q == 0 else "失败"
            except Exception as e:   # noqa: BLE001
                summary["quality_daily"] = f"失败({e})"
            # 10/16 晚 B11: 画像版本评估(只告警, 绝不回滚)
            run([PY, "-X", "utf8", "scripts/skills_ver/persona_versions.py", "check", "--until", d.isoformat()], "画像版本评估", 600)
        # 10/16 晚用户批: 全市场开盘前 15 分钟分时(研究导师选股的竞价/开盘特征, 往后每天攒; 幂等, 当日已做=秒退; 约 10~15 分钟, 通达信)
        if (not only or "open15" in only) and not a.dry:
            rc_o, out_o = run([PY, "-X", "utf8", "scripts/market/collect_open15.py"], "全市场开盘 15 分钟分时", 3600)
            summary["open15"] = ("完成" if rc_o == 0 else "失败") + f"({(out_o or '').strip().splitlines()[-1][:80] if (out_o or '').strip() else ''})"
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
        # 10/18 审计④ R10(用户批): 统计基线影子账户每天跑一次(零 token, 纯统计"笨办法跟单"), 攒"LLM 链比基线强多少"的对比数据;
        #   10/16 只跑过一次就没再跑。注意口径: 链能看到基线建议, 所以对比的是"LLM+基线提示 比 基线多出来多少"
        if (not only or "baseline" in only) and not a.dry and dt.datetime.now().hour >= 16:
            st_bl = state.setdefault(d.isoformat(), {})
            if not (st_bl.get("baseline_books") or {}).get("ok"):
                rc_b, out_b = run([PY, "-X", "utf8", "scripts/tzzb/mentor_model.py", "--baseline-books", "--since", "2026-10-08", "--until", d.isoformat()], "统计基线影子账户", 1800)
                st_bl["baseline_books"] = {"at": dt.datetime.now().isoformat(timespec="seconds"), "ok": rc_b == 0}
                save_state(state)
                summary["baseline_books"] = "完成" if rc_b == 0 else "失败"
        # 10/16 晚 一-9: 混合账本(mix_plans.py)盘中跟单 + 收盘学习; 只在显式 --only mix / mix_learn 时跑(sys_job 每 5 分钟 + 15:25 各一条)
        if only and "mix" in only and not a.dry:
            # 10/18 晚 P3: 盘口五档快照采集器(新浪, 不占腾讯额度)没在跑就后台拉起(无窗口); 挂了下一轮自动重拉
            run([PY, "-X", "utf8", "scripts/market/collect_book.py", "--ensure"], "盘口快照采集", 60)
            st_mix = state.setdefault(d.isoformat(), {}).setdefault("mix", {})
            import manual_backfill as _mb   # noqa: PLC0415  (UP 步已把 backfill_bilibili 加进 path)
            cur = _mb.db().cursor()
            cur.execute("select job_handler_param, cron_expression from sys_job where job_handler_name='paperChainHandler' and status=0 and is_deleted=0")
            fire = {}   # 时段 → 实际触发 HHMM(取 cron 的时:分, 多条取最早)
            for p, cr in cur.fetchall():
                s = (p or "").split(":")[-1]
                if not s.isdigit():
                    continue
                try:
                    _, mi, hh = (cr or "").split()[:3]
                    hm = f"{int(hh):02d}{int(mi):02d}"
                except ValueError:
                    hm = s
                fire[s] = min(fire.get(s, hm), hm)
            slots = sorted(fire)
            now_hm = dt.datetime.now().strftime("%H%M")
            due = []
            for s in slots:
                # 10/17 审计 Q-3: 原来按时段名+15 分钟, 1455 时段实际 14:35 触发却算成 15:10 就绪, 而 mix 只跑到 14:55 → 永远吃不到; 改按实际触发时刻+15
                ready = "0918" if s == "0915" else (dt.datetime.strptime(fire[s], "%H%M") + dt.timedelta(minutes=15)).strftime("%H%M")
                if ready <= now_hm and s not in st_mix:
                    due.append(s)
            res = []
            for s in due[-2:]:   # 只补最近两个到点的时段(漏掉的更早时段已过时, 不补)
                rc_m, out_m = run([PY, "-X", "utf8", "scripts/dfcf/paper/mix_plans.py", "--date", d.isoformat(), "--slot", s], f"混合账本 {s}", 600)
                st_mix[s] = {"at": dt.datetime.now().isoformat(timespec="seconds"), "rc": rc_m}
                res.append(f"{s}:{'ok' if rc_m == 0 else rc_m}")
            for s in due[:-2]:
                st_mix[s] = {"at": dt.datetime.now().isoformat(timespec="seconds"), "rc": "skip(过时)"}
            save_state(state)
            summary["mix"] = ", ".join(res) or "无到点时段"
            # 10/18 晚: 做T 两本(A-tbank 中行 / A-tndq 纳指ETF 159941)搭混合账本的 5 分钟车; 幂等(早盘挂单一次 / 14:45 收口一次)
            rc_t, out_t = run([PY, "-X", "utf8", "scripts/dfcf/paper/t_bot.py", "--tick", "--date", d.isoformat()], "做T 账本", 180)
            summary["t_bot"] = "ok" if rc_t == 0 else "失败"
            # 10/18 晚: 决策 T 两本(A-dbank / A-dndq, 花 token; 时段 0915/0933/1033/1303/1433 + 14:45 机械收口; 幂等, 到点才调模型)
            rc_d, _ = run([PY, "-X", "utf8", "scripts/dfcf/paper/t_decide.py", "--tick", "--date", d.isoformat()], "决策T 账本", 900)
            summary["t_decide"] = "ok" if rc_d == 0 else "失败"
        if only and "mix_learn" in only and not a.dry:
            rc_l, _ = run([PY, "-X", "utf8", "scripts/dfcf/paper/mix_plans.py", "--learn", "--date", d.isoformat()], "混合账本收盘学习", 600)
            summary["mix_learn"] = "完成" if rc_l == 0 else "失败"
        # 10/17 晚用户批: 规则时间状态(建立 / 最后验证 / 活跃·待复核·已否定) 机械补齐 + 刷新, 再重建规则索引(零 token, 秒级)
        if (not only or "persona_snap" in only) and not a.dry:
            rc_ts, out_ts = run([PY, "-X", "utf8", "scripts/md/rule_time_state.py", "--all", "--write"], "规则时间状态", 300)
            import ast   # noqa: PLC0415
            for ln in (out_ts or "").splitlines():
                mm = re.match(r"^(\S+): (\{.*\})$", ln.strip())
                try:
                    r_ = ast.literal_eval(mm.group(2)) if mm else {}
                except (ValueError, SyntaxError):
                    r_ = {}
                if r_.get("新增") or r_.get("刷新"):
                    run(["node", "scripts/md/gen_rules_index.mjs", "--skill", mm.group(1)], f"规则索引 {mm.group(1)}", 120)
            summary["rule_time"] = "完成" if rc_ts == 0 else "失败"
        # 10/16 晚 B11: 每轮末尾给画像打快照(本轮蒸馏改了才升版本, 没改=秒退); --only persona_snap = 08:00 盘前兜底
        if (not only or "persona_snap" in only) and not a.dry:
            rc_ps, _ = run([PY, "-X", "utf8", "scripts/skills_ver/persona_versions.py", "snapshot", "--all", "--why", f"check-md {d.isoformat()} {dt.datetime.now():%H:%M}"], "画像快照", 600)
            summary["persona_snap"] = "完成" if rc_ps == 0 else "失败"
        # 10/18: 导师名片按最新账本数据给下一交易日重算(原只在次日 0915 facts 首次用到时懒生成, 已存在就不再刷新 → 当晚补进的账本数据进不去)
        if (not only or "case_log" in only) and not a.dry:   # 10/18 用户定: 停用 32B 推测层, 改由全量操作日志卡(机械, 零 token, 幂等; 全量重算约 3 秒)
            rc_cl, _ = run([PY, "-X", "utf8", "scripts/tzzb/case_log.py"], "导师操作日志卡", 300)
            run([PY, "-X", "utf8", "scripts/tzzb/hold_mining.py"], "持仓手法挖掘(滚动验证)", 300)
            summary["case_log"] = "完成" if rc_cl == 0 else "失败"
            run([PY, "-X", "utf8", "scripts/dfcf/paper/t_review.py", "--date", d.isoformat()], "做T 复盘(事后最优 T 标签)", 300)   # 10/18 晚
            run([PY, "-X", "utf8", "scripts/dfcf/paper/t_knowledge.py"], "做T 知识包", 120)   # 10/18 晚: 全体 skill 做T 技巧(正反面)给决策T
            run([PY, "-X", "utf8", "scripts/dfcf/paper/t_skill.py"], "品种 skill 数据画像(银行股/纳指)", 120)   # 10/18 晚
            run([PY, "-X", "utf8", "scripts/dfcf/paper/t_private_report.py"], "牧原私有报告(snapshots/report_private.html)", 120)   # 10/18 晚: 不进 git
            run([PY, "-X", "utf8", "scripts/dfcf/paper/rand_baseline.py"], "RAND 抛硬币基准", 600)   # 10/18 晚 P0: 各链 vs 随机选股
            run([PY, "-X", "utf8", "scripts/dfcf/paper/signal_lab.py"], "分钟级信号实验室", 1200)   # 10/18 晚 P2: MOM/REV/VWAP/TFI/RAND 滚动验证
            run([PY, "-X", "utf8", "scripts/quotes/indicators_db.py", "--date", d.isoformat()], "均线/三态/风险仓位 全市场快照", 900)   # 10/18 晚 A+C: downloads/market/<日>/indicators.jsonl
            run([PY, "-X", "utf8", "scripts/tzzb/regime_trades.py"], "导师×三态 胜率/盈亏比/期望", 1200)   # 10/18 晚 B: 写各导师 fingerprint.md AUTO:三态 块
            run([PY, "-X", "utf8", "scripts/bilibili/up_case_log.py"], "B站 UP 日卡", 600)   # 10/18 晚: 画面 BS / 持仓 / 原话 + 行情
        if (not only or "mentor_cards" in only) and not a.dry:
            nd = _next_td(d, _bb().load_holidays()).isoformat()
            rc_mc, _ = run([PY, "-X", "utf8", "scripts/tzzb/mentor_cards.py", "--date", nd], f"导师名片 {nd}", 300)
            summary["mentor_cards"] = "完成" if rc_mc == 0 else "失败"
        # 10/14 用户令(爬虫要主动报问题, 不能等用户发现): 每轮末尾零 token 采集健康巡检, 红/黄写进本轮摘要, 报告 scripts/health/reports/<日>.md
        if not a.dry and not (only and only <= {"mix", "mix_learn", "persona_snap", "review07"}):
            rc_h, out_h = run([PY, "-X", "utf8", "scripts/health/daily_health.py"], "采集健康巡检", 300)
            hj = _json_tail(out_h)
            summary["health"] = f"红 {hj.get('red', '?')} / 黄 {hj.get('yellow', '?')}(详见 {hj.get('report', 'scripts/health/reports/')})"
            log(f"[health] → {summary['health']}")
            # 10/18 用户定: 暂停中的导师(如冲5000w)真人账本恢复更新 → 推微信提醒(只提醒不自动开; 同一次复活只提醒一次)
            rc_rv, out_rv = run([PY, "-X", "utf8", "scripts/health/revival_check.py"], "导师复活检查", 120)
            summary["revival"] = f"提醒 {_json_tail(out_rv).get('alerts', '?')} 条" if rc_rv == 0 else "失败"
        # 10/17 健壮性 M14: 收尾步骤失败原先只写进 summary, 退出码仍 0 → sys_job_log 记成功, daily_health 红线看不到
        tail_failed = [k for k, v in summary.items() if isinstance(v, str) and v.startswith("失败")]
        if tail_failed:
            summary["tail_failed"] = tail_failed
        log(f"===== 本轮结束: {json.dumps(summary, ensure_ascii=False)} =====")
        print("JSON:" + json.dumps(summary, ensure_ascii=False))
        return 1 if failed else (3 if tail_failed else 0)
    finally:
        if LOG_FH:
            LOG_FH.close()
        if LOCK_F.exists() and LOCK_F.read_text().strip() == str(os.getpid()):
            LOCK_F.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
