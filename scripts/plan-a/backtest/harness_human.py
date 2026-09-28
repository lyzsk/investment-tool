# harness_human.py — 人读版回测 harness(2026-09-28 用户拍板, 替代旧机器读 runs)
# 三组: A=照抄桃哥(机械提取 md 操作) B=纯LLM基线 C=taoge-skill 人格七环节
# 闭环: 事实采集(本文件+factpack.mjs, 确定性代码)→分析→辩论×2→方案→风控→终裁→复盘(6 个隔离 claude -p)
# 铁律: ①信息截止=T-1(agent 只见 ≤T-1, T 日 bar 只给结算) ②persona 物理快照进 runs 目录 ③每环节留痕文件
#       ④账本 ledger.json 断点续跑 ⑤STAGE_OK 哨兵才记账 ⑥事实=代码, 拟人只做判断评分表态
# 口径: 日线粒度(2025 窗口分钟线已不可得, 腾讯 m60 上限 8 个月); 次日开盘价成交(照抄者最早能跟的时点);
#       费用买万2.5/卖万7.5(sim.mjs 同口径); 单票买入=净值20%整百股; 股票 T+1, 转债(11/12 开头)T+0; 初始资金 100 万
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]           # investment-tool/ (harness 在 scripts/plan-a/backtest/ 下三层)
STOCKS = ROOT / "stocks"
SKILL = ROOT / "skills" / "taoge-skill"
CHECKLIST = ROOT / "scripts" / "backfill_taoge" / "md_checklist.md"
FACTPACK = ROOT / "scripts" / "plan-a" / "backtest" / "replay" / "factpack.mjs"
PY = ROOT / "scripts" / "venv" / "Scripts" / "python.exe"

FEE_B, FEE_S = 0.00025, 0.00075
INIT_CASH = 1_000_000.0
POS_PCT = 0.20          # 单票买入 = 净值 20%
MAX_DAYS, MIN_DAYS = 7, 3
MAX_CALLS = 70          # token 预算闸: 约 80min 跑批窗口(06:08→07:30)
CALL_TIMEOUT = 600

# ---------- 工具 ----------
def log(msg):
    line = f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(RUN_DIR / "harness.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")

def load_ledger():
    f = RUN_DIR / "ledger.json"
    return set(json.loads(f.read_text(encoding="utf-8"))["done"]) if f.exists() else set()

def save_ledger(done):
    (RUN_DIR / "ledger.json").write_text(json.dumps({"done": sorted(done)}, ensure_ascii=False, indent=1), encoding="utf-8")

def trading_calendar():
    out = []
    for d in STOCKS.glob("2*S*"):
        for f in d.glob("2*.md"):
            out.append(f.stem)
    return sorted(out)

def md_file(date):
    y, q = date[:4], (int(date[5:7]) - 1) // 3 + 1
    p = STOCKS / f"{y}S{q}" / f"{date}.md"
    return p if p.exists() else None

def taoge_section(date):
    p = md_file(date)
    if not p:
        return None
    m = re.search(r"### 桃哥([\s\S]*?)(?=\n### |\n## (?!#)|$)", p.read_text(encoding="utf-8", errors="ignore"))
    return m.group(1).strip() if m else None

# ---------- 窗口选择: ✅+🧠 最密连续交易日簇 ----------
def pick_window(done, checklist_text):
    eligible = []
    for line in checklist_text.splitlines():
        m = re.match(r"\| (\d{4}-\d{2}-\d{2}) \|.*✅.*(🧠)", line)
        if m:
            eligible.append(m.group(1))
    cal = trading_calendar()
    idx = {d: i for i, d in enumerate(cal)}
    eligible = sorted(d for d in eligible if d in idx)
    best, cur = [], []
    for d in eligible:
        if cur and idx[d] - idx[cur[-1]] <= 1:
            cur.append(d)
        else:
            cur = [d]
        if len(cur) > len(best):
            best = cur[:]
    if len(best) < MIN_DAYS:
        return None, eligible
    return best[-MAX_DAYS:], eligible   # 取簇尾(最新, 沉淀最饱满的一侧)

# ---------- claude 调用(哨兵+超时+一次重试) ----------
# 9/28 冒烟事故: cmd /c 包一层会把 prompt 里的双引号/换行解析烂 → agent 收到空 prompt 回"已就绪请说任务"。
# 修法: 直调 claude.exe + list argv(CreateProcessW 正确引用), 不走 cmd。
CLAUDE_EXE = os.environ.get("CLAUDE_EXE", r"C:\Users\admin\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe")
CALLS = {"n": 0}
def claude(prompt, tag, out_file=None, timeout=CALL_TIMEOUT):
    """返回 (ok, stdout)。out_file: 要求 agent 用 Write 落盘的绝对路径, 校验存在且非空。"""
    CALLS["n"] += 1
    for attempt in (1, 2):
        try:
            r = subprocess.run([CLAUDE_EXE, "-p", "--dangerously-skip-permissions", prompt],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout, cwd=str(ROOT))
        except subprocess.TimeoutExpired:
            log(f"{tag} 超时(第{attempt}次)"); time.sleep(30); continue
        tail = (r.stdout or "").strip().splitlines()
        sentinel_ok = tail and tail[-1].strip() == f"STAGE_OK {tag}"
        file_ok = True
        if out_file:
            p = Path(out_file)
            file_ok = p.exists() and p.stat().st_size > 50
        if r.returncode == 0 and sentinel_ok and file_ok:
            return True, r.stdout
        err = (r.stderr or "").strip().replace("\n", " ")[:150]
        log(f"{tag} 失败(第{attempt}次): exit={r.returncode} 哨兵={bool(sentinel_ok)} 文件={file_ok} err={err}")
        time.sleep(60 if attempt == 1 else 0)
    return False, ""

# ---------- 行情(factpack.mjs 桥) ----------
def node_factpack(mode, out_file, **kw):
    args = ["node", str(FACTPACK), mode, f"--out={out_file}"] + [f"--{k}={v}" for k, v in kw.items()]
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=300, cwd=str(ROOT / "scripts" / "plan-a" / "backtest" / "replay"))
    return r.returncode == 0 and Path(out_file).exists()

def code_of(raw):   # 6 位裸代码 → 带市场前缀; 转债 11→sh 12→sz
    if re.match(r"^(60|68|11)", raw): return "sh" + raw
    if re.match(r"^(00|30|12)", raw): return "sz" + raw
    if re.match(r"^(83|87|92)", raw): return "bj" + raw
    return None

CODE_RE = re.compile(r"(?<!\d)((?:60|68|00|30|11|12)\d{4})(?!\d)")

# ---------- 结算 ----------
def settle(account, orders, bars_t, date, group, trades):
    """orders: [{code,name,side,limit_price,factor,ref}]; bars_t: {code: barT}。改 account, 追加 trades。"""
    equity0 = account["cash"] + sum(p["qty"] * ((bars_t.get(c) or {}).get("c") or p["cost"]) for c, p in account["pos"].items())
    for o in orders:
        code, side = o.get("code"), o.get("side")
        bar = bars_t.get(code)
        rec = {"date": date, "group": group, "code": code, "name": o.get("name", ""), "side": side,
               "factor": o.get("factor", ""), "ref": o.get("ref", "")}
        if not code or code not in CODE_RE_PATTERN_OK(code):
            trades.append({**rec, "status": "SKIP", "reason": "代码缺失/非法"}); continue
        if not bar:
            trades.append({**rec, "status": "SKIP", "reason": "当日无bar(停牌/未上市/数据缺)"}); continue
        lim = o.get("limit_price")
        if side == "buy":
            if lim and bar["l"] > lim:
                trades.append({**rec, "status": "SKIP", "reason": f"限价{lim}未到(最低{bar['l']})"}); continue
            px = min(bar["o"], lim) if lim else bar["o"]
            qty = int(min(equity0 * POS_PCT, account["cash"]) / (px * (1 + FEE_B)) / 100) * 100
            if qty <= 0:
                trades.append({**rec, "status": "SKIP", "reason": "现金不足一手"}); continue
            amt = px * qty; fee = round(amt * FEE_B, 2)
            account["cash"] -= amt + fee
            p = account["pos"].setdefault(code, {"qty": 0, "cost": 0.0, "name": o.get("name", ""), "buy_date": date})
            p["cost"] = (p["cost"] * p["qty"] + amt) / (p["qty"] + qty) if p["qty"] else px
            p["qty"] += qty; p["buy_date"] = date
            trades.append({**rec, "status": "OK", "price": px, "qty": qty, "amount": round(amt, 2), "fee": fee})
        elif side == "sell":
            p = account["pos"].get(code)
            if not p or p["qty"] <= 0:
                trades.append({**rec, "status": "SKIP", "reason": "无持仓"}); continue
            if p["buy_date"] == date and not re.match(r"^(sh11|sz12)", code):
                trades.append({**rec, "status": "SKIP", "reason": "T+1 当日买入不可卖"}); continue
            if lim and bar["h"] < lim:
                trades.append({**rec, "status": "SKIP", "reason": f"限价{lim}未到(最高{bar['h']})"}); continue
            px = max(bar["o"], lim) if lim else bar["o"]
            amt = px * p["qty"]; fee = round(amt * FEE_S, 2)
            account["cash"] += amt - fee
            trades.append({**rec, "status": "OK", "price": px, "qty": p["qty"], "amount": round(amt, 2), "fee": fee})
            del account["pos"][code]
    return equity0

def CODE_RE_PATTERN_OK(code):
    return [code] if re.match(r"^(sh|sz|bj)\d{6}$", code or "") else []

def mark_equity(account, bars_t):
    return account["cash"] + sum(p["qty"] * (bars_t.get(c) or {}).get("c", p["cost"]) for c, p in account["pos"].items())

# ---------- prompt 模板(中文走 argv, CreateProcessW 安全) ----------
def p_common(t_minus1, t):
    return (f"硬性纪律: ①信息截止={t_minus1} 晚, 严禁使用任何晚于该日的市场知识/个股后续走势 "
            f"②你只是在回测沙盒里扮演, 不要声称真实交易 ③所有输出用中文。\n")

def prompt_a(section_file, t_minus1, t):
    return (p_common(t_minus1, t) +
            f"你是机械提取器, 不做任何投资判断。用 Read 读文件 {section_file} (桃哥 {t_minus1} 晚视频小节), "
            f"提取他口述或画面确认的【实际操作】与【明确计划】, 组装成 {t} 开盘可执行的照抄单。\n"
            "规则: ①只提取他明确说的买卖/计划买卖, 禁止推测禁止脑补 ②'今天我卖了X'(已完成)→照抄者次日才能跟, side=sell;"
            "'明天/企稳我再进X'(计划)→side=buy ③他给了价位就填 limit_price, 没给填 null(=开盘价成交)"
            "④每条必须带 quote=原文锚点短句 ⑤只收小节里出现过 6 位代码的票; 只有名字没代码的票名放进 unresolvable 数组"
            "⑥无操作日=orders 空数组, 这也是正常结果。\n"
            f"输出: 用 Write 把纯 JSON 写入 {RUN_DIR}/a_extract/{t}.json, 结构 "
            '{"orders":[{"code":"sh600127","name":"","side":"buy|sell","limit_price":null,"factor":"他说的一句话理由","quote":"原文锚点"}],"unresolvable":[],"notes":""}'
            f"\n写完在 stdout 末行打印 STAGE_OK A-{t}")

def prompt_b(facts_file, t_minus1, t):
    return (p_common(t_minus1, t) +
            f"你是无风格的通用交易者 AI 基线。用 Read 读 {facts_file} ({t_minus1} 晚信息包: 指数与候选票日线+一位主播观点原文), "
            f"给出 {t} 开盘执行的订单。没有规则库没有人格, 按你自己的判断; 可以不买。\n"
            "纪律: 只用信息包里出现的 6 位代码; 每笔给 factor(一句理由)。\n"
            f"用 Write 把纯 JSON 写入 {RUN_DIR}/b_llm/{t}.json, 结构同 "
            '{"orders":[{"code":"sh600127","name":"","side":"buy|sell","limit_price":null,"factor":""}],"notes":""}'
            f"\n写完在 stdout 末行打印 STAGE_OK B-{t}")

SNAP = None  # 运行期赋值为 persona 快照目录

def prompt_c(stage, t_minus1, t, files):
    reads = " ".join(str(f) for f in files)
    base = (p_common(t_minus1, t) +
            f"你在扮演 B站主播桃哥做历史回测。先用 Read 读齐人格文件: {SNAP}/SKILL.md {SNAP}/persona/profile.md "
            f"{SNAP}/persona/rules.md {SNAP}/persona/cases.md {SNAP}/persona/language.md , 再读输入: {reads}\n")
    out = RUN_DIR / "c_chain" / t
    stages = {
        "analysis": ("做今日盘前分析: 大盘情绪判断+候选票(可含信息包外你自己知道的票, 但需给名称和理由)+每个判断引用 rules.md 规则编号。"
                     f"写入 {out}/01_analysis.md", f"C-{t}-analysis"),
        "bull": ("你是多方辩手: 基于分析稿找最强做多理由(引用规则编号)。"
                 f"写入 {out}/02_debate_bull.md", f"C-{t}-bull"),
        "bear": ("你是空方辩手: 基于分析稿逐条攻击候选票与大盘判断, 找证伪点(引用规则编号/cases.md 学费案例)。"
                 f"写入 {out}/03_debate_bear.md", f"C-{t}-bear"),
        "plan": ("综合分析与正反辩论, 出交易方案草案: 每笔=代码/方向/限价(可无)/仓位想法/因素/引用规则。注意 rules.md E 区: 语料无止损规则, 不要编造止损线。"
                 f"写入 {out}/04_plan.md", f"C-{t}-plan"),
        "risk": ("风控审查: 逐笔检查方案——情绪过热? 追高违反 profile? 仓位超限? 与辩论空方意见冲突未回应? 给出每笔 放行/否决 及理由。"
                 f"写入 {out}/05_risk.md", f"C-{t}-risk"),
        "verdict": ("终裁: 综合方案与风控意见出最终订单。可以是空仓。只收有 6 位代码的票(信息包外新票给名称进 new_names)。"
                    f"用 Write 把纯 JSON 写入 {out}/06_verdict.json, 结构 "
                    '{"orders":[{"code":"sh600127","name":"","side":"buy|sell","limit_price":null,"factor":"","rule_refs":["B12"],"risk_note":""}],'
                    '"rejected":[{"name":"","reason":""}],"new_names":[]}'
                    f"\n写完在 stdout 末行打印 STAGE_OK C-{t}-verdict", f"C-{t}-verdict"),
        "review": ("复盘: 对照终裁与当日实际执行/走势结果, 回答三问: 判断对在哪错在哪/哪条规则帮了或坑了/人格哪里需要长。不改 rules.md, 只写复盘稿。"
                   f"写入 {out}/07_review.md", f"C-{t}-review"),
    }
    body, tag = stages[stage]
    return base + body + ("" if stage == "verdict" else f"\n写完在 stdout 末行打印 STAGE_OK {tag}"), tag

# ---------- 主流程 ----------
def main():
    global RUN_DIR, SNAP
    done_ledger_arg = "--fresh" not in sys.argv
    checklist = CHECKLIST.read_text(encoding="utf-8")
    window, eligible = pick_window(None, checklist)
    if not window:
        print(f"窗口不足: ✅+🧠 最密连续簇 <{MIN_DAYS} 天 (当前合格日 {len(eligible)} 天: {eligible})", flush=True)
        sys.exit(2)
    RUN_DIR = ROOT / "scripts" / "plan-a" / "backtest" / "runs" / f"human-{window[0]}_{window[-1]}"
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    for sub in ("a_extract", "b_llm", "c_chain", "facts"):
        (RUN_DIR / sub).mkdir(exist_ok=True)
    # persona 物理快照(可追溯铁律: 报告注明用了哪版规则)
    SNAP = RUN_DIR / "persona_snapshot"
    if SNAP.exists():
        shutil.rmtree(SNAP)
    shutil.copytree(SKILL, SNAP)
    log(f"窗口={window[0]}..{window[-1]} ({len(window)} 交易日, 簇内), 合格日全表={eligible}")
    log(f"persona 快照已落 {SNAP} (rules.md {os.path.getsize(SNAP/'persona/rules.md')}B)")

    ledger = load_ledger() if done_ledger_arg else set()
    accounts = {g: {"cash": INIT_CASH, "pos": {}} for g in ("A", "B", "C")}
    trades, equity_rows = [], []
    cal = trading_calendar()
    idx_of = {d: i for i, d in enumerate(cal)}

    for t in window:
        i = idx_of[t]
        t_minus1 = cal[i - 1]
        if CALLS["n"] >= MAX_CALLS:
            log(f"token 预算闸触发({MAX_CALLS} calls), 剩余天数放弃, 部分结果收尾")
            break
        log(f"===== {t} (信息截止 {t_minus1}) =====")
        # --- 事实采集(确定性代码): md 小节 + 候选票代码 + 日线(≤T-1 给 agent, T 日留结算) ---
        sec = taoge_section(t_minus1)
        if not sec:
            log(f"{t}: {t_minus1} 无桃哥小节, 跳过"); continue
        sec_file = RUN_DIR / "facts" / f"{t}_section.md"
        sec_file.write_text(sec, encoding="utf-8")
        codes = sorted({c for c in (code_of(m) for m in CODE_RE.findall(sec)) if c} | {"sh000001"})
        bars_file = RUN_DIR / "facts" / f"{t}_bars.json"
        if not f"{t}:facts" in ledger:
            ok = node_factpack("bars", str(bars_file), codes=",".join(codes),
                               **{"from": _shift(cal, i, -40), "to": t})
            if not ok:
                log(f"{t}: 事实采集失败(bars), 跳过"); continue
            ledger.add(f"{t}:facts"); save_ledger(ledger)
        bars = json.loads(bars_file.read_text(encoding="utf-8"))
        # 信息包(≤T-1): 指数与候选票近 10 日 OHLC 摘要 + md 小节
        facts_md = RUN_DIR / "facts" / f"{t}_infopack.md"
        lines = [f"# {t} 盘前信息包(信息截止 {t_minus1})\n", f"## 桃哥 {t_minus1} 晚视频小节原文\n", sec, "\n## 候选票日线(截至 T-1)\n"]
        for c in codes:
            if c == "sh000001" or not isinstance(bars.get(c), list):
                continue
            hist = [b for b in bars[c] if b["t"] < t.replace("-", "")][-10:]
            if hist:
                lines.append(f"- {c}: " + " ".join(f"{b['t'][4:]}O{b['o']}C{b['c']}" for b in hist))
        idx_hist = [b for b in (bars.get("sh000001") or []) if b["t"] < t.replace("-", "")][-10:]
        if idx_hist:
            lines.append(f"\n## 上证指数近10日: " + " ".join(f"{b['t'][4:]}C{b['c']}" for b in idx_hist))
        facts_md.write_text("\n".join(lines), encoding="utf-8")

        orders = {}
        # --- A 组: 机械照抄 ---
        a_file = RUN_DIR / "a_extract" / f"{t}.json"
        if f"{t}:A" not in ledger:
            ok, _ = claude(prompt_a(sec_file, t_minus1, t), f"A-{t}", out_file=a_file)
            if ok: ledger.add(f"{t}:A"); save_ledger(ledger)
        orders["A"] = _read_orders(a_file)
        # --- B 组: 纯 LLM 基线 ---
        b_file = RUN_DIR / "b_llm" / f"{t}.json"
        if f"{t}:B" not in ledger:
            ok, _ = claude(prompt_b(facts_md, t_minus1, t), f"B-{t}", out_file=b_file)
            if ok: ledger.add(f"{t}:B"); save_ledger(ledger)
        orders["B"] = _read_orders(b_file)
        # --- C 组: taoge-skill 七环节 ---
        c_out = RUN_DIR / "c_chain" / t
        c_out.mkdir(exist_ok=True)
        stage_files = {
            "analysis": [], "bull": [c_out / "01_analysis.md"], "bear": [c_out / "01_analysis.md"],
            "plan": [c_out / "01_analysis.md", c_out / "02_debate_bull.md", c_out / "03_debate_bear.md"],
            "risk": [c_out / "04_plan.md"], "verdict": [c_out / "04_plan.md", c_out / "05_risk.md"],
        }
        prev_ok = True
        for stage in ("analysis", "bull", "bear", "plan", "risk", "verdict"):
            key = f"{t}:C:{stage}"
            if key in ledger:
                continue
            if not prev_ok or CALLS["n"] >= MAX_CALLS:
                break
            p, tag = prompt_c(stage, t_minus1, t, [facts_md] + stage_files[stage])
            out_f = c_out / ("06_verdict.json" if stage == "verdict" else
                             f"0{('analysis','bull','bear','plan','risk').index(stage)+1}_{stage if stage!='bull' and stage!='bear' else 'debate_'+stage}.md")
            ok, _ = claude(p, tag, out_file=out_f)
            prev_ok = ok
            if ok:
                ledger.add(key); save_ledger(ledger)
        orders["C"] = _read_orders(c_out / "06_verdict.json")
        # C 组信息包外新票: 解析→抓 bar→并入结算
        new_names = _read_new_names(c_out / "06_verdict.json")
        if new_names:
            res_file = RUN_DIR / "facts" / f"{t}_resolve.json"
            node_factpack("resolve", str(res_file), names=",".join(new_names))
            res = json.loads(res_file.read_text(encoding="utf-8")) if res_file.exists() else {}
            extra = [v["code"] for v in res.values() if v.get("code")]
            if extra:
                node_factpack("bars", str(RUN_DIR / "facts" / f"{t}_bars_extra.json"), codes=",".join(extra),
                              **{"from": _shift(cal, i, -5), "to": t})
                ex = json.loads((RUN_DIR / "facts" / f"{t}_bars_extra.json").read_text(encoding="utf-8"))
                for k, v in ex.items():
                    if isinstance(v, list):
                        bars[k] = v
            for o in orders["C"]:
                if not o.get("code") and o.get("name") in res and res[o["name"]].get("code"):
                    o["code"] = res[o["name"]]["code"]
        # --- 结算(三组同口径) ---
        bars_t = {c: next((b for b in v if b["t"] == t.replace("-", "")), None)
                  for c, v in bars.items() if isinstance(v, list)}
        for g in ("A", "B", "C"):
            settle(accounts[g], orders[g], bars_t, t, g, trades)
            eq = mark_equity(accounts[g], bars_t)
            equity_rows.append({"date": t, "group": g, "equity": round(eq, 2),
                                "cash": round(accounts[g]["cash"], 2), "n_pos": len(accounts[g]["pos"])})
        # --- C 组复盘(结算后, 用当日真实结果) ---
        if f"{t}:C:review" not in ledger and CALLS["n"] < MAX_CALLS and orders["C"] is not None:
            exec_file = RUN_DIR / "c_chain" / t / "exec_result.json"
            exec_file.write_text(json.dumps({"date": t, "executed": [x for x in trades if x["date"] == t],
                                             "bars_t": bars_t}, ensure_ascii=False, indent=1), encoding="utf-8")
            p, tag = prompt_c("review", t_minus1, t, [c_out / "06_verdict.json", exec_file])
            ok, _ = claude(p, tag, out_file=c_out / "07_review.md")
            if ok:
                ledger.add(f"{t}:C:review"); save_ledger(ledger)
        log(f"{t} 结算: " + " ".join(f"{g}={mark_equity(accounts[g], bars_t):,.0f}" for g in "ABC"))

    _finalize(window, trades, equity_rows, accounts, eligible)
    log("DONE")

def _shift(cal, i, n):
    return cal[max(0, i + n)]

def _read_orders(f):
    try:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        return d.get("orders", [])
    except (OSError, json.JSONDecodeError):
        return []

def _read_new_names(f):
    try:
        return json.loads(Path(f).read_text(encoding="utf-8")).get("new_names", [])
    except (OSError, json.JSONDecodeError):
        return []

# ---------- 收尾: CSV + 曲线 + 人读报告骨架 ----------
def _finalize(window, trades, equity_rows, accounts, eligible):
    import csv
    BOM = "﻿"
    with open(RUN_DIR / "trades.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, ["date", "group", "code", "name", "side", "status", "reason", "price", "qty", "amount", "fee", "factor", "ref"])
        w.writeheader()
        for t in trades:
            w.writerow({k: t.get(k, "") for k in w.fieldnames})
    with open(RUN_DIR / "equity.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, ["date", "group", "equity", "cash", "n_pos"])
        w.writeheader()
        for r in equity_rows:
            w.writerow(r)
    # 曲线图(BS 点按日粒度; 2025 窗口无分钟线, 报告明示)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
        plt.rcParams["axes.unicode_minus"] = False
        fig, ax = plt.subplots(figsize=(11, 5))
        for g, color in (("A", "tab:blue"), ("B", "tab:gray"), ("C", "tab:red")):
            rows = [r for r in equity_rows if r["group"] == g]
            xs = [r["date"][5:] for r in rows]
            ax.plot(xs, [r["equity"] / INIT_CASH for r in rows], marker="o", label=f"{g}组", color=color)
            for tr in trades:
                if tr["group"] == g and tr.get("status") == "OK":
                    yi = next((r["equity"] / INIT_CASH for r in rows if r["date"] == tr["date"]), None)
                    if yi:
                        ax.annotate("B" if tr["side"] == "buy" else "S", (tr["date"][5:], yi),
                                    color="green" if tr["side"] == "buy" else "red", fontsize=8, ha="center")
        ax.axhline(1.0, ls="--", lw=0.5)
        ax.set_title(f"人读版回测 {window[0]}..{window[-1]} 净值曲线(日粒度, B/S=成交点)")
        ax.legend(); fig.tight_layout()
        fig.savefig(RUN_DIR / "equity.png", dpi=110)
    except Exception as e:
        log(f"绘图失败(不影响数据): {e}")
    # 报告骨架(07:42 cron 可在此基础上补偏差归因细读)
    fin = {g: next((r["equity"] for r in reversed(equity_rows) if r["group"] == g), INIT_CASH) for g in "ABC"}
    rep = [f"# 人读版回测报告 {window[0]}..{window[-1]}",
           f"\n> 生成: {dt.datetime.now():%Y-%m-%d %H:%M} · 规则快照: persona_snapshot/(rules.md {os.path.getsize(SNAP / 'persona' / 'rules.md')}B) · 合格沉淀日: {eligible}",
           "\n## 口径",
           "- 日线粒度(2025 窗口分钟线已超出腾讯 m60 八个月上限, 日内分时不可得 → BS 点只有日期无分时, 如实标注)",
           "- 成交: 次日开盘价(照抄者最早能跟的时点); 限价单=日内触及才成交; 费用买万2.5/卖万7.5; 单票=净值20%整百; 股票T+1/转债T+0; 初始100万",
           "- A=机械照抄 md 操作(零判断) / B=纯LLM基线 / C=taoge-skill 七环节(分析→辩论×2→方案→风控→终裁→复盘)",
           f"\n## 终值(归一) A={fin['A']/INIT_CASH:.4f} B={fin['B']/INIT_CASH:.4f} C={fin['C']/INIT_CASH:.4f}",
           "\n曲线: equity.png · 明细: trades.csv / equity.csv · 全链路留痕: a_extract/ b_llm/ c_chain/ facts/",
           "\n## 每日并排 A vs C(偏差四问: 选股/分析/情绪风控/终裁, 归因到规则编号)\n"]
    for t in window:
        rep.append(f"### {t}")
        rep.append(f"- A 组单: {_orders_brief(RUN_DIR/'a_extract'/f'{t}.json')}")
        rep.append(f"- C 终裁: {_orders_brief(RUN_DIR/'c_chain'/t/'06_verdict.json')}")
        rep.append(f"- C 链路: [分析](c_chain/{t}/01_analysis.md) [多](c_chain/{t}/02_debate_bull.md) [空](c_chain/{t}/03_debate_bear.md) [方案](c_chain/{t}/04_plan.md) [风控](c_chain/{t}/05_risk.md) [复盘](c_chain/{t}/07_review.md)")
    (RUN_DIR / "report.md").write_text("\n".join(rep), encoding="utf-8")
    state = (f"# harness STATE\n窗口 {window[0]}..{window[-1]} · calls={CALLS['n']} · 完成 {dt.datetime.now():%H:%M}\n"
             f"终值 A={fin['A']:,.0f} B={fin['B']:,.0f} C={fin['C']:,.0f}\n")
    (RUN_DIR / "STATE.md").write_text(state, encoding="utf-8")

def _orders_brief(f):
    try:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        if not d.get("orders"):
            return "空仓"
        return "; ".join(f"{o.get('side')== 'buy' and '买' or '卖'} {o.get('name') or o.get('code')}" for o in d["orders"])
    except (OSError, json.JSONDecodeError):
        return "(缺文件/未产出)"

RUN_DIR = None
if __name__ == "__main__":
    main()
