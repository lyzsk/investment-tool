# -*- coding: utf-8 -*-
"""ledger_limits.py — paper 决策链"账本统计硬约束 + 本导师候选池 + 统计基线建议"的机械层(10/16 晚 TODO 三-2 + A2①③, 零 token, 只读)

消费方: scripts/taoge-chain/run_chain.py(开关 chain_flags.txt CHAIN_LEDGER_CONSTRAINTS; 关=驱动器不 import 本模块)。
本模块只读文件、不写业务库、不调 LLM; 唯一的写=ensure_artifact() 现场补产 pools/<日>.json·model_out/<日>.json(调导师脚本子进程, CREATE_NO_WINDOW)
和 log_jsonl()(overrides/ledger 日志)。

一、硬约束参数 ledger_limits(skill, asof): 真人账本近 WINDOW 个记录日(as-of 只用 asof 之前), 分位 P_HI(=P80):
  - n_hold_max   有持仓日的收盘持股只数 P80(day_positions, 去逆回购; 空仓日不计), 至少 1
  - new_open_max 有新开仓那天的新开仓只数 P80(逐笔腿: 当日买入且前一记录日收盘不持有), 至少 1
                 (只看"开仓日": 开不开仓归"导师不动链也不动"闸管, 两闸分工不重叠)
  - turnover_max 近 5 日换手 P80 = Σ近5记录日买入额 / 第 1 日前一收盘总资产(nav_daily asset)
  - trade_ratio  出手日占比(有任一成交腿的日 / 窗口日); < LOW_FREQ → 低频导师, 开新仓须基线 p_trade ≥ GATE_P
  - cap_single   单票最大仓位 P80(收盘最大一只的 position_percent, 封顶 1.0); conc=单票最大仓位中位 ≥ CONC_MED(恒满仓单票型)
  - first_frac   0915 首笔金额上限 = fingerprint.md 盘中节奏「首笔占前一日总资产」中位; 只在「先小仓试错」成立(≥25% 买入日)时给
  样本 < MIN_DAYS 记录日: 持股只数回退 mentor_scope n_hold_med, 其余维度跳过; 无账本(B站 UP/对照组)=None(全部跳过)
  土豆(转债 T+0, 收盘恒空): 持股只数维度跳过(收盘口径不适用), 单票上限维持原固定口径
二、候选池 pool_view(): pools/<日>.json Top-N + 联动扩展(①本链持仓在池子里时同题材的池内后排票 ②昨日热点题材(池内涨停票题材计数 Top3)的池内后排票
  ③scripts/dfcf/snapshots/live/related_<日>.json 若恰好含本链持仓则带上其关联票; 拿不到就跳过)
  池外预算 = ceil(真人越池比例 × 候选数), 至少 1(越池比例=fingerprint.md 盘中节奏⑤ Top50 池外); 指纹「不清晰」/无池=只用打法约束
三、统计基线 baseline_of(): scripts/tzzb/model_out/<日>.json 的 baseline_suggestion + L1/L2/L4 概率
交易成本: 口径同 scripts/dfcf/paper/matcher.mjs CONFIG(佣金万 2.5 最低 5 元 + 卖出印花税万 5; 不改 matcher)。
  TODO(a_rules): scripts/lib/a_rules.py 出来后费用/涨跌停统一从它取(下面已优先 import, 拿不到回退本地常量)

CLI(scripts/venv/Scripts/python.exe -X utf8):
  ledger_limits.py --show [--asof 2026-10-16]                 逐导师参数表
  ledger_limits.py --backtest --since 2026-10-08 --until 2026-10-16 [--json out.json]   用 books 回算"开关当时开着会拦下多少单"
"""
import argparse, json, math, os, re, subprocess, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TZ = ROOT / "downloads" / "tzzb"
TZZB = ROOT / "scripts" / "tzzb"
PAPER = ROOT / "scripts" / "dfcf" / "paper"
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import mentors  # noqa: E402  10/17 二B-4: 导师登记表

WINDOW, MIN_DAYS, P_HI = 60, 15, 0.8
LOW_FREQ = 0.6          # 出手日占比 < 60%(不到六成交易日有成交) = 低频导师(导师不动链也不动); 10/16 实测: A658 58%/边学 33%/星见野 38%/宣秋 53%/土豆 55%/冲5000w 30%
GATE_P = 0.5            # 低频导师开新仓: 基线 L1 p_trade ≥ 0.5(基线判"今天更可能出手")
GATE_STALE = 3          # 基线状态滞后 > 3 个交易日(导师没上传)=闸 fail-open
CATCHUP_GAP = 0.3       # 10/18 追仓豁免: 链此刻总仓(持仓+未成交买单) 比导师真人昨收总仓低 ≥30% nav → "导师不动"闸不拦开新仓
#   (星见野 10/15 沙盒五组全空仓: 链清了遗留中行后空仓, 真人红太阳满仓不动 → 闸把"导师不动"执行成"链保持空仓", 方向反了)


def gate_state(lim, base, chain_tp=None):
    """低频导师"导师不动链也不动"闸状态: None(不适用) / "fail-open" / "拦" / "放" / "追仓"(链远低于导师真人仓位, 豁免)"""
    if not lim or not lim.get("low_freq"):
        return None
    if not base or base.get("p_trade") is None or (base.get("stale") or 0) > GATE_STALE:
        return "fail-open"
    if float(base["p_trade"]) >= GATE_P:
        return "放"
    tp = (base.get("state") or {}).get("tp_prev")
    if chain_tp is not None and tp is not None and min(float(tp), 1.0) - float(chain_tp) >= CATCHUP_GAP:
        return "追仓"
    return "拦"
CONC_MED = 0.8          # 单票最大仓位中位 ≥ 80% = 恒满仓单票型
TRIAL_OK = 0.25         # 「先小仓试错」日占买入日 ≥25% = 成立(与 mentor_fingerprint 判定口径一致)
PLAY_MIN = 0.05         # 打法约束: 候选打法须在导师新开仓打法分布里 ≥5%
POOL_TOPN = 20
NO_LEDGER = set(mentors.ids("UP", "对照"))   # 10/17 读登记表
REPO = ("204", "1318")  # 逆回购不算持仓/买入

# ---- 交易成本(matcher.mjs CONFIG 同口径) ----
FEE_RATE, FEE_MIN, STAMP = 0.00025, 5.0, 0.0005
try:   # TODO(a_rules): 统一规则模块就位后以它为准
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))
    import a_rules as _AR   # noqa: E402
except Exception:   # noqa: BLE001
    _AR = None


def fee(side, amt, code=None, date=None):
    """10/17: 走 a_rules.fees(同 matcher.mjs fee: 佣金+印花税只收股票卖方, 转债/ETF 免; 过户费不计); code=None 按股票算。
    原写法探 _AR.fee(不存在, a_rules 只有 fees)→ 恒走本地口径; a_rules 导入失败仍回退本地口径"""
    if _AR is not None:
        try:
            f = _AR.fees(side, amt, code or "600000", date, commission_rate=FEE_RATE, min_commission=FEE_MIN)
            return float(f["commission"] + f["stamp"])
        except Exception:   # noqa: BLE001  签名不符=回退本地口径
            pass
    f = max(FEE_MIN, amt * FEE_RATE)
    return f + amt * STAMP if side == "SELL" else f


def roundtrip_cost(amt):
    return fee("BUY", amt) + fee("SELL", amt)


def fee_line(nav, cap_amt=None):
    """constraint_text 用的一行成本说明(数字机械算)"""
    nav = float(nav or 0) or 100000.0
    out = []
    for a in sorted({round(x) for x in (5000, 20000, cap_amt or 0) if x and x > 0}):
        c = roundtrip_cost(a)
        out.append(f"{a:.0f} 元一来回≈{c:.1f} 元({c / a:.2%} 单额, {c / nav:.3%} nav)")
    return ("- 交易成本(matcher 口径: 佣金万 2.5 最低 5 元/笔 + 卖出印花税万 5): " + "; ".join(out)
            + "。小额单最低佣金吃掉更多; 一买一卖不赚过成本的单=净亏, 换手越高成本越高")


# ---------- 真人账本 ----------
_CACHE = {}


def _jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def _load(skill):
    if skill in _CACHE:
        return _CACHE[skill]
    d = TZ / skill
    dp = _jl(d / "day_positions.json", {}) or {}
    nav = {}
    for x in ((_jl(d / "nav_daily.json", {}) or {}).get("ex_data") or {}).get("index_list") or []:
        try:
            nav[x["date"]] = float(x["asset"])
        except (KeyError, TypeError, ValueError):
            pass
    legs = []
    try:
        sys.path.insert(0, str(TZZB))
        from gen_tzzb_profile import load_legs   # 只读 json(去重+两融 op 归一)
        legs = load_legs(skill)
    except Exception:   # noqa: BLE001
        legs = []
    _CACHE[skill] = (dp, nav, legs)
    return _CACHE[skill]


def _held(rec):
    out = {}
    for p in (rec or {}).get("list") or []:
        c = str(p.get("code") or p.get("stock_code") or "")
        if c.startswith(REPO):
            continue
        try:
            v = float(p.get("position_percent"))
        except (TypeError, ValueError):
            continue
        if v > 0:
            out[c] = v
    return out


def _q(a, p):
    return sorted(a)[min(len(a) - 1, int(len(a) * p))] if a else None


def _med(a):
    if not a:
        return None
    s = sorted(a)
    return s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2


def _cut(asof):
    return (asof or datetime.now().strftime("%Y-%m-%d")).replace("-", "")


def mentor_series(skill, asof=None):
    """逐记录日序列(窗口内): [{day, n_hold, max_pos, new_open, traded, buy_amt, turnover5}]"""
    dp, nav, legs = _load(skill)
    cut = _cut(asof)
    days = sorted(k for k in dp if k < cut)
    if not days:
        return [], {}
    buys, traded = {}, set()
    for t in legs:
        day = str(t.get("trans_date") or "")[:10].replace("-", "")
        code = str(t.get("stock_code") or "")
        if not day or day >= cut or code.startswith(REPO):
            continue
        traded.add(day)
        if t.get("op") == "1":
            try:
                amt = float(t.get("trans_amount") or 0) or float(t.get("trans_price") or 0) * float(t.get("trans_count") or 0)
            except (TypeError, ValueError):
                amt = 0.0
            buys.setdefault(day, {}).setdefault(code, 0.0)
            buys[day][code] += amt
    idx = {d: i for i, d in enumerate(days)}
    out = []
    for d in days[-WINDOW:]:
        i = idx[d]
        h = _held(dp[d])
        prev = _held(dp[days[i - 1]]) if i else {}
        bd = buys.get(d) or {}
        b5 = sum(sum((buys.get(x) or {}).values()) for x in days[max(0, i - 4):i + 1])
        prior = [nav[x] for x in days[max(0, i - 5):i] if nav.get(x, 0) > 0]
        base = _med(prior) if prior else nav.get(d)   # 前 5 个记录日总资产中位(防单日异常资产值, 10/16 高概率有一天资产≈0)
        out.append({"day": d, "n_hold": len(h), "max_pos": min(1.0, max(h.values())) if h else 0.0,
                    "new_open": len([c for c in bd if c not in prev]), "traded": d in traded, "buy_amt": sum(bd.values()),
                    "turnover5": (b5 / base) if base else None})
    meta = {"legs": bool(legs), "legs_end": max(traded) if traded else None, "days_end": days[-1]}
    return out, meta


EMPTY_TP = 0.3   # 10/20 下限收窄: 收盘总仓 < 30% = 空仓日(真人 day_positions / 链 nav 同口径)


def real_empty_spell_max(skill, asof=None, window=120):
    """真人近 window(默认 120, 10/20 用户批的口径)个记录日(< asof)里, 收盘总仓 < EMPTY_TP 的最长连续天数; 无账本=None(A658 10/20 = 3)"""
    dp = _load(skill)[0]
    days = sorted(k for k in dp if k < _cut(asof))[-window:]
    if not days:
        return None
    best = run = 0
    for d in days:
        run = run + 1 if sum(_held(dp[d]).values()) < EMPTY_TP else 0
        best = max(best, run)
    return best


def chain_empty_days(book, date_dash):
    """本链到上一交易日收盘为止连续空仓(收盘 mv/nav < EMPTY_TP)的天数(10/8 实盘重新开户起算)"""
    n = 0
    for x in sorted((x for x in book.get("nav") or [] if "2026-10-08" <= x.get("date", "") < date_dash), key=lambda x: x["date"], reverse=True):
        if float(x.get("nav") or 0) > 0 and float(x.get("mv") or 0) / float(x["nav"]) < EMPTY_TP:
            n += 1
        else:
            break
    return n


def _scope(skill):
    sc = (_jl(TZZB / "mentor_scope.json", {}) or {}).get(skill) or {}
    return None if sc.get("kind") == "no_stat" else sc


def fingerprint_meta(skill):
    """fingerprint.md(只读)→ 打法分布/清晰度/越池比例/首笔占总资产中位/先小仓试错日占比"""
    f = ROOT / "skills" / f"{skill}-skill" / "persona" / "fingerprint.md"
    try:
        t = f.read_text(encoding="utf-8")
    except OSError:
        return None
    plays = {}
    sec = t.split("## 一、打法分布", 1)[1].split("\n## ", 1)[0] if "## 一、打法分布" in t else ""
    for m in re.finditer(r"^\|\s*([^|\-\s][^|]*?)\s*\|\s*(\d+)%\s*\|\s*(\d+)\s*\|", sec, re.M):
        plays[m.group(1).strip()] = int(m.group(2)) / 100
    m = re.search(r"指纹清晰度=([^\n(]+)", t)
    clarity = m.group(1).strip() if m else "未知"
    m = re.search(r"Top50 池外 (\d+)%", t)
    out_ratio = int(m.group(1)) / 100 if m else None
    m = re.search(r"占前一日总资产: ([\d.]+)", t)
    first_frac = float(m.group(1)) if m else None
    m = re.search(r"「先小仓试错」日[^:]*: (\d+)%", t)
    trial = int(m.group(1)) / 100 if m else None
    return {"plays": plays, "clarity": clarity, "out_ratio": out_ratio, "first_frac": first_frac, "trial": trial,
            "allowed_plays": [k for k, v in sorted(plays.items(), key=lambda kv: -kv[1]) if v >= PLAY_MIN and k not in ("数据缺失", "其他")]}


def ledger_limits(skill, asof=None):
    """返回该导师的账本硬约束参数(见模块头); 无账本=None"""
    if skill in NO_LEDGER:
        return None
    if not (TZ / skill / "day_positions.json").exists():
        return None
    ser, meta = mentor_series(skill, asof)
    lim = {"skill": skill, "asof": asof, "n_days": len(ser), "window": [ser[0]["day"], ser[-1]["day"]] if ser else None,
           "skip": [], "notes": []}
    cb = skill == "buchitudou0"
    sc = _scope(skill) or {}
    enough = len(ser) >= MIN_DAYS
    if cb:
        lim["n_hold_max"] = None
        lim["skip"].append("持股只数(转债 T+0 收盘恒空, 收盘口径不适用)")
    elif enough and sum(1 for r in ser if r["n_hold"] > 0) >= MIN_DAYS // 2:   # 只看有持仓的日子(空仓日不说明"拿几只", 空不空仓归出手闸/总仓下限)
        lim["n_hold_max"] = max(1, _q([r["n_hold"] for r in ser if r["n_hold"] > 0], P_HI))
    elif sc.get("n_hold_med") is not None:
        lim["n_hold_max"] = max(1, int(math.ceil(float(sc["n_hold_med"]))))
        lim["notes"].append(f"记录日仅 {len(ser)} 天, 持股只数回退 mentor_scope 中位")
    else:
        lim["n_hold_max"] = None
        lim["skip"].append("持股只数(样本不足)")
    if enough and meta.get("legs"):
        nod = [r["new_open"] for r in ser if r["new_open"] > 0]
        lim["new_open_max"] = max(1, _q(nod, P_HI)) if nod else 1
        tv = [r["turnover5"] for r in ser if r["turnover5"] is not None]
        lim["turnover_max"] = round(_q(tv, P_HI), 3) if len(tv) >= MIN_DAYS else None
        if lim["turnover_max"] is None:
            lim["skip"].append("近5日换手(缺总资产序列)")
        lim["trade_ratio"] = round(sum(1 for r in ser if r["traded"]) / len(ser), 3)
        lim["open_day_ratio"] = round(len(nod) / len(ser), 3)
    else:
        lim.update(new_open_max=None, turnover_max=None, trade_ratio=None, open_day_ratio=None)
        lim["skip"].append("新开仓/换手/出手日占比(" + ("样本不足" if not enough else "无逐笔腿") + ")")
    lim["low_freq"] = bool(lim.get("trade_ratio") is not None and lim["trade_ratio"] < LOW_FREQ)
    mx = [r["max_pos"] for r in ser if r["n_hold"] > 0]
    if cb:
        lim.update(cap_single=None, conc=False)
    else:
        med = _med(mx) if len(mx) >= MIN_DAYS else sc.get("max_pos_med")
        lim["conc"] = bool(med is not None and float(med) >= CONC_MED)
        lim["max_pos_med"] = round(float(med), 3) if med is not None else None
        lim["cap_single"] = min(1.0, round(_q(mx, P_HI) * 20) / 20) if len(mx) >= MIN_DAYS else None
    fp = fingerprint_meta(skill) or {}
    lim["fp"] = {k: fp.get(k) for k in ("clarity", "out_ratio", "first_frac", "trial", "allowed_plays", "plays")}
    lim["first_frac"] = fp.get("first_frac") if (fp.get("trial") is not None and fp["trial"] >= TRIAL_OK and not cb) else None
    lim["data_end"] = ser[-1]["day"] if ser else None
    return lim


def limits_text(lim):
    """一行可读摘要(注入/汇报共用)"""
    if not lim:
        return "无账本统计(跳过)"
    p = []
    if lim.get("n_hold_max") is not None:
        p.append(f"持股≤{lim['n_hold_max']}只")
    if lim.get("new_open_max") is not None:
        p.append(f"单日新开仓≤{lim['new_open_max']}只")
    if lim.get("turnover_max") is not None:
        p.append(f"近5日换手≤{lim['turnover_max']:.0%}nav")
    if lim.get("trade_ratio") is not None:
        p.append(f"出手日占比{lim['trade_ratio']:.0%}" + ("(低频→开新仓须基线出手概率≥%d%%)" % round(GATE_P * 100) if lim.get("low_freq") else ""))
    if lim.get("cap_single") is not None:
        p.append(f"单票P80 {lim['cap_single']:.0%}" + ("(恒满仓单票型)" if lim.get("conc") else ""))
    if lim.get("first_frac") is not None:
        p.append(f"0915首笔≤{lim['first_frac']:.1%}nav")
    return "; ".join(p) or "全部维度跳过"


# ---------- 基线建议 / 池子 产物 ----------
def _no_window():
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {}


def artifact_path(kind, date_dash):
    return (TZZB / "pools" / f"{date_dash}.json") if kind == "pool" else (TZZB / "model_out" / f"{date_dash}.json")


def ensure_artifact(kind, date_dash, timeout=300):
    """pools/<日>.json(kind=pool) 或 model_out/<日>.json(kind=model) 不存在就现场调导师脚本生成; 多链并发用 O_EXCL 锁, 只一个跑, 其余等文件。
    超时/失败=返回 False(fail-open, 链照跑不注入)"""
    f = artifact_path(kind, date_dash)
    if f.exists():
        return True
    lock = f.parent / f".gen_{kind}_{date_dash}.lock"
    f.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode()); os.close(fd)
    except FileExistsError:
        if time.time() - lock.stat().st_mtime > timeout * 2:   # 死锁残留
            try:
                lock.unlink()
            except OSError:
                pass
            return ensure_artifact(kind, date_dash, timeout)
        while time.time() - t0 < timeout:
            if f.exists():
                return True
            if not lock.exists():
                return f.exists()
            time.sleep(3)
        return f.exists()
    try:
        py = str(ROOT / "scripts" / "venv" / "Scripts" / "python.exe")
        script = "mentor_fingerprint.py" if kind == "pool" else "mentor_model.py"
        args = [py if Path(py).exists() else sys.executable, "-X", "utf8", str(TZZB / script)] + (["--pool"] if kind == "pool" else ["--predict"]) + ["--date", date_dash]
        r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, **_no_window())
        if r.returncode != 0:
            print(f"WARN: {script} --date {date_dash} 失败 rc={r.returncode}: {(r.stderr or r.stdout or '')[-200:]}")
    except Exception as e:   # noqa: BLE001  超时/环境错=fail-open
        print(f"WARN: 现场生成 {kind} {date_dash} 失败(fail-open): {e}")
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
    return f.exists()


def baseline_of(skill, date_dash):
    d = _jl(artifact_path("model", date_dash))
    m = ((d or {}).get("mentors") or {}).get(skill)
    if not m or not m.get("baseline_suggestion"):
        return None
    bs = m["baseline_suggestion"]
    l1, l2, l4 = m.get("L1") or {}, m.get("L2") or {}, m.get("L4") or {}
    return {"trade": bs.get("trade"), "dir": bs.get("dir"), "tp_target": bs.get("tp_target"), "n_new": bs.get("n_new_if_buy"),
            "src": bs.get("src") or {}, "p_trade": l1.get("p_trade"), "p_dir": l2.get("p_dir_given_trade") or l2.get("p_dir") or {},
            "tp_p25": l4.get("p25"), "tp_p75": l4.get("p75"), "stale": m.get("stale_days"), "state_day": m.get("state_day"),
            "state": m.get("state") or {}, "play_top": list(((m.get("L3") or {}).get("play_dist") or {}).items())[:3]}


def baseline_text(b, step):
    if not b:
        return ""
    pd = " / ".join(f"{k} {float(v):.0%}" for k, v in sorted((b.get("p_dir") or {}).items(), key=lambda kv: -float(kv[1])))
    st = b.get("state") or {}
    L = [f"- 统计基线(scripts/tzzb/mentor_model.py, 只用 {b.get('state_day')} 及以前的真人数据; 真人昨收: 总仓 {float(st.get('tp_prev') or 0):.0%} / {st.get('n_hold')} 只 / 昨日{'有' if st.get('trade_prev') else '无'}成交"
         + (f"; ⚠ 真人数据滞后 {b['stale']} 个交易日" if (b.get("stale") or 0) > 1 else "") + ")",
         f"  - L1 今天出手(有任何买卖)概率 {float(b.get('p_trade') or 0):.0%} → 基线判 {'出手' if b.get('trade') else '不出手'}(选源: {b['src'].get('L1', '?')})",
         f"  - L2 若出手方向: {pd or '无'} → 基线 {b.get('dir')}(选源: {b['src'].get('L2', '?')})",
         f"  - L4 目标收盘总仓 {float(b.get('tp_target') or 0):.0%}" + (f"(P25~P75 {float(b['tp_p25']):.0%}~{float(b['tp_p75']):.0%})" if b.get("tp_p25") is not None else "")
         + f"; 若买入, 新买只数 {b.get('n_new')}"]
    if b.get("play_top"):
        L.append("  - L3 打法分布参考: " + " / ".join(f"{k} {float(v):.0%}" for k, v in b["play_top"]))
    if step == "06":
        L.append("  - 默认接受基线的 L1/L2/L4; 你要改其中任何一层(如基线判不出手你却开新仓、基线判加你却减、总仓明显偏离 P25~P75), contract 写可选字段 "
                 "\"override\": [{\"layer\":\"L1|L2|L4\",\"baseline\":\"基线值\",\"mine\":\"你的值\",\"p\":你认为自己对的概率0~1,\"why\":\"一句话理由(≥8字)\"}]"
                 "(驱动器记账, 收盘统计 override 胜负; 不写=按接受基线记)")
    else:
        L.append("  - 这是机械统计的默认答案(样本外: 出手层延续/常数最准、方向层模型显著赢基线); 你的判断与它不同要有具体理由, 06 会要求写 override")
    return "\n".join(L)


def _play_hint(why):
    s = " ".join(why or [])
    if re.search(r"连板=(2板|3板)", s):
        return "连板接力"
    if "连板=1板" in s or "昨涨跌=涨停" in s:
        return "首板次日"
    if "昨炸板=是" in s:
        return "炸板次日"
    return ""


def pool_view(skill, date_dash, held_codes=(), topn=POOL_TOPN):
    """本导师候选池块: 返回 {use_pool, codes{code:name}, names, out_ratio, allowed_plays, text} 或 None(无池也无打法统计)"""
    fp = fingerprint_meta(skill) or {}
    d = _jl(artifact_path("pool", date_dash)) or {}
    ent = (d.get("mentors") or {}).get(skill) or {}
    pool = ent.get("pool") or []
    clar = fp.get("clarity") or "未知"
    use_pool = bool(pool) and not clar.startswith(("不清晰", "无法评估"))
    allowed = fp.get("allowed_plays") or []
    if not use_pool and not allowed:
        return None
    L = ["## 本导师候选池(驱动器注入; 指纹池=scripts/tzzb/mentor_fingerprint.py --pool 只用前一交易日收盘数据, 无后见)"]
    plays = fp.get("plays") or {}
    if allowed:
        L.append("- 本导师新开仓打法分布(fingerprint.md): " + " / ".join(f"{k} {plays[k]:.0%}" for k in allowed)
                 + f"; 候选的 play 字段只许写这些打法(占比 ≥{PLAY_MIN:.0%} 的), 写别的=驱动器回炉")
    codes, names = {}, set()
    if use_pool:
        top, rest = pool[:topn], pool[topn:]
        ratio = fp.get("out_ratio")
        L.append(f"- 指纹清晰度: {clar}; 真人新开仓落在自己 Top50 指纹池外的比例 {ratio:.0%}" if ratio is not None else f"- 指纹清晰度: {clar}")
        L.append(f"- 指纹池 Top{len(top)}(分数=朴素贝叶斯 log 倍数和, 只用于排序; 打法提示=由入池理由粗推):")
        for i, x in enumerate(top, 1):
            hint = _play_hint(x.get("why"))
            L.append(f"  {i}. {x.get('name')}({x.get('code')}) 分{x.get('score')} 昨涨{float(x.get('pct_prev') or 0):+.1%}"
                     + (f" [{hint}]" if hint else "") + f" | {'; '.join(x.get('why') or [])} | 题材: {'、'.join(t for t in x.get('themes') or [] if t != '其他') or '-'}")
            codes[str(x.get("code"))] = x.get("name")
        # 联动扩展: ①本链持仓在池里时同题材的后排票 ②昨日热点题材(池内昨涨停票的题材计数 Top3)的后排票
        from collections import Counter
        hot = Counter(t for x in pool if x.get("zt_prev") for t in x.get("themes") or [] if t != "其他")
        hot_top = [k for k, _ in hot.most_common(3)]
        held_th = {t for x in pool if str(x.get("code")) in set(held_codes) for t in x.get("themes") or [] if t != "其他"}
        ext, plain = [], []
        for x in rest:
            th = set(x.get("themes") or [])
            why = ("持仓同题材" if th & held_th else "") or ("昨日热点题材" if th & set(hot_top) else "")
            (ext.append((x, why)) if why else plain.append(x))
            codes[str(x.get("code"))] = x.get("name")   # 后排(Top N 之后)也算池内: 越池比例是按 Top50 口径测的, 池子文件只有 Top30
        if plain:
            L.append(f"- 池内后排(第 {len(top) + 1} 名起, 算池内): " + "、".join(f"{x.get('name')}({x.get('code')})" for x in plain))
        rel = _jl(ROOT / "scripts" / "dfcf" / "snapshots" / "live" / f"related_{date_dash}.json") or {}
        for h in set(held_codes) & set((rel.get("holdings") or {}).keys()):
            for r in ((rel["holdings"][h] or {}).get("related") or [])[:5]:
                c = str(r.get("code") or "")
                if re.fullmatch(r"\d{6}", c):
                    ext.append(({"code": c, "name": r.get("name"), "themes": []}, f"持仓联动({r.get('kind') or r.get('rel') or '关联'})"))
        if ext:
            L.append(f"- 联动扩展(后排里与持仓同题材/昨日热点题材的票 + 持仓关联票, 算池内; 昨日热点题材: {'、'.join(hot_top) or '无'}):")
            for x, why in ext[:10]:
                codes[str(x.get("code"))] = x.get("name")
                L.append(f"  - {x.get('name')}({x.get('code')}) [{why}] 题材: {'、'.join(t for t in x.get('themes') or [] if t != '其他') or '-'}")
        L.append("- 候选规则: 新票优先从池内(Top 列表+后排+联动扩展)选; 池外票数量 ≤ 池外预算 = ceil(越池比例 × 候选数), 至少 1(持仓/未成交挂单票不占预算); "
                 "超了驱动器回炉。池外票在 candidates 里加 \"off_pool_why\":\"一句话为什么值得越池\"")
    else:
        L.append(f"- 指纹清晰度: {clar} → 本导师不用指纹池约束选股(只用上面的打法约束)")
    names = {n for n in codes.values() if n}
    return {"use_pool": use_pool, "codes": codes, "names": names, "out_ratio": fp.get("out_ratio"), "allowed_plays": allowed,
            "clarity": clar, "text": "\n".join(L)}


def pool_budget(ratio, n_cands):
    return max(1, int(math.ceil((ratio if ratio is not None else 1.0) * n_cands)))


def check_04(view, cands, exempt_codes):
    """返回 (硬违规文本|None, 软违规文本|None, 统计 dict)。exempt=持仓/未成交挂单(不占池外预算, 不要求 play)。
    硬=打法越界/池外超预算(回炉, 末次放行); 软=新票缺 play 字段(回炉一次)"""
    if not view:
        return None, None, {}
    new = [x for x in cands if str(x.get("code") or "") not in exempt_codes]
    errs, soft, st = [], None, {"n": len(cands), "new": len(new)}
    if view["allowed_plays"]:
        bad = [x for x in new if x.get("play") is not None and not any(p in str(x.get("play")) for p in view["allowed_plays"])]
        miss = [x for x in new if x.get("play") is None]
        st.update(play_bad=len(bad), play_miss=len(miss))
        if bad:
            errs.append(f"候选 {[(x.get('name'), x.get('play')) for x in bad]} 的 play 不在本导师打法分布(≥{PLAY_MIN:.0%})内: 只许 {'/'.join(view['allowed_plays'])}")
        if miss:
            soft = f"新票候选 {[x.get('name') for x in miss]} 缺 play 字段(从本导师打法分布里选一个: {'/'.join(view['allowed_plays'])})"
    if view["use_pool"]:
        out = [x for x in new if str(x.get("code") or "") not in view["codes"] and x.get("name") not in view["names"]]
        bud = pool_budget(view.get("out_ratio"), len(cands))
        st.update(off_pool=len(out), budget=bud)
        if len(out) > bud:
            errs.append(f"池外候选 {len(out)} 只 {[x.get('name') for x in out]} > 池外预算 {bud} 只(越池比例 {float(view.get('out_ratio') or 1):.0%}×候选 {len(cands)} 只, 向上取整)"
                        "——换成本导师候选池/联动扩展里的票, 或删掉证据最弱的池外票")
    return ("; ".join(errs) or None), soft, st


# ---------- 06 硬约束 ----------
SELL_OPS = ("卖", "开盘卖")


def chain_state(book, date_dash):
    """本链账本此刻状态: 日初持仓/今日已新开仓/未成交买单/近 4 个交易日+今日已成交买入额"""
    pos = {c: int(p.get("qty") or 0) for c, p in (book.get("positions") or {}).items() if int(p.get("qty") or 0) > 0}
    tb, ts = {}, {}
    for t in book.get("trades") or []:
        if str(t.get("id", ""))[:10] != date_dash:
            continue
        (tb if t.get("side") == "BUY" else ts).setdefault(str(t["code"]), 0)
        if t.get("side") == "BUY":
            tb[str(t["code"])] += int(t.get("qty") or 0)
        else:
            ts[str(t["code"])] += int(t.get("qty") or 0)
    open_q = {c: pos.get(c, 0) - tb.get(c, 0) + ts.get(c, 0) for c in set(pos) | set(tb) | set(ts)}
    day_open = {c for c, q in open_q.items() if q > 0}
    new_done = {c for c in tb if c not in day_open}
    open_buy = {}
    for o in book.get("orders") or []:
        if o.get("status") == "open" and o.get("side") == "BUY":
            open_buy[str(o["code"])] = open_buy.get(str(o["code"]), 0.0) + float(o.get("price") or 0) * int(o.get("qty") or 0)
    prev_days = sorted({n["date"] for n in book.get("nav") or [] if n.get("date", "") < date_dash})[-4:]
    win = set(prev_days) | {date_dash}
    buy5 = sum(float(t.get("price") or 0) * int(t.get("qty") or 0) for t in book.get("trades") or []
               if t.get("side") == "BUY" and str(t.get("id", ""))[:10] in win)
    return {"pos": pos, "day_open": day_open, "new_done": new_done, "open_buy": open_buy, "buy5": buy5, "win": sorted(win)}


def check_06(lim, st, acts, nav, base=None, slot="0915", sub=False, chain_tp=None):
    """返回 (硬违规 list[str], 软违规 list[str], 统计 dict)。acts=v06 校验后的 actions(买单带 _px)
    chain_tp=链此刻总仓占 nav(持仓+未成交买单, 驱动器传; None=不做追仓豁免, 旧行为)"""
    hard, soft = [], []
    if not lim:
        return hard, soft, {}
    nav = float(nav or 0) or 1.0
    px = lambda a: float(a.get("_px") or a.get("trigger_price") or a.get("anchor") or 0)
    buys = [a for a in acts if a.get("op") == "买"]
    bcodes = {str(a.get("code")) for a in buys}
    cxl = {a["_cxl"]["code"] for a in acts if a.get("op") == "撤单" and a.get("_cxl") and a["_cxl"].get("side") == "BUY"}
    ob = {c: v for c, v in st["open_buy"].items() if c not in cxl and c not in bcodes}   # 同票新单会 CXL 旧单
    sold_out = {str(a.get("code")) for a in acts if a.get("op") in SELL_OPS and int(a.get("qty") or 0) >= st["pos"].get(str(a.get("code")), 0) > 0}
    before = set(st["pos"]) | set(st["open_buy"])
    after = (set(st["pos"]) | set(ob) | bcodes) - sold_out
    new_add = {c for c in bcodes if c not in st["day_open"]}
    new_all = st["new_done"] | {c for c in ob if c not in st["day_open"]} | new_add
    buy_amt = sum(px(a) * int(a.get("qty") or 0) for a in buys)
    tv = (st["buy5"] + sum(ob.values()) + buy_amt) / nav
    S = {"hold_after": len(after), "hold_before": len(before), "new_today": len(new_all), "new_add": len(new_add), "turnover5": round(tv, 3)}
    if lim.get("n_hold_max") is not None and len(after) > lim["n_hold_max"] and len(after) > len(before):
        hard.append(f"本单后持股(含未成交买单) {len(after)} 只 > 本导师上限 {lim['n_hold_max']} 只(真人近 {lim['n_days']} 个交易日收盘持股只数 P80)——"
                    "先卖/撤再买, 或少开新票、把钱加在已有持仓上")
    if lim.get("new_open_max") is not None and new_add and len(new_all) > lim["new_open_max"]:
        hard.append(f"本日新开仓 {len(new_all)} 只(含今日已成交/未成交新票) > 本导师上限 {lim['new_open_max']} 只(真人开仓日新开只数 P80)——只留最有把握的")
    if lim.get("turnover_max") is not None and buys and tv > lim["turnover_max"]:
        hard.append(f"近 5 日换手(买入额/nav, 含今日已成交+未成交+本单) {tv:.0%} > 本导师上限 {lim['turnover_max']:.0%}(真人近 5 日换手 P80)——"
                    f"本单最多再买约 {max(0.0, lim['turnover_max'] * nav - st['buy5'] - sum(ob.values())):.0f} 元")
    S["gate"] = None
    if lim.get("low_freq") and new_add:
        g = gate_state(lim, base, chain_tp)
        if g == "fail-open":
            S["gate"] = "无基线(fail-open)" if not base or base.get("p_trade") is None else f"基线滞后 {base['stale']} 日(fail-open)"
        elif g == "拦":
            S["gate"] = "拦"
            hard.append(f"导师不动链也不动: 本导师出手日只占 {lim['trade_ratio']:.0%}(低频), 统计基线今天出手概率 {float(base['p_trade']):.0%} < {GATE_P:.0%}, "
                        f"本日不许开新仓 {sorted(new_add)}——只许持仓处置(卖/撤/持有/已有持仓加减)")
        else:
            S["gate"] = g
    if lim.get("first_frac") is not None and slot == "0915" and not sub:
        for a in buys:
            c, amt = str(a.get("code")), px(a) * int(a.get("qty") or 0)
            if c in new_add and int(a.get("qty") or 0) > 100 and amt > lim["first_frac"] * nav:
                soft.append(f"{a.get('name')}({c}) 首笔 {amt:.0f} 元 = {amt / nav:.0%} nav > 本导师首笔习惯 {lim['first_frac']:.0%} nav"
                            "(真人「先小仓试错」成立: 竞价/开盘先小仓, 方向对了盘中再加)——0915 先下小仓(1 手不受限)")
    return hard, soft, S


def norm_override(ov):
    """06 contract override 规范化+校验 → (list|None, 错误|None)"""
    if ov is None:
        return None, None
    if isinstance(ov, dict):
        ov = [ov]
    if not isinstance(ov, list):
        return None, "override 须为列表 [{layer,baseline,mine,p,why}]"
    out = []
    for i, x in enumerate(ov):
        if not isinstance(x, dict):
            return None, f"override[{i}] 须为对象"
        lay = str(x.get("layer") or "").upper().strip()
        m = re.match(r"L[1-4]", lay)
        if not m:
            return None, f"override[{i}].layer 只许 L1(出手)/L2(方向)/L3(选股打法)/L4(总仓): {x.get('layer')}"
        if len(str(x.get("why") or "").strip()) < 8:
            return None, f"override[{i}].why 太短(一句话理由 ≥8 字)"
        p = x.get("p")
        if p is not None:
            try:
                p = float(p)
            except (TypeError, ValueError):
                return None, f"override[{i}].p 须为 0~1 的数: {x.get('p')}"
            if not 0 <= p <= 1:
                return None, f"override[{i}].p 须在 0~1: {p}"
        out.append({"layer": m.group(0), "baseline": x.get("baseline"), "mine": x.get("mine"), "p": p, "why": str(x.get("why")).strip()})
    return out, None


def chain_view(acts, st, nav):
    """本单相对基线的层值(记账用): trade/dir/n_new"""
    px = lambda a: float(a.get("_px") or a.get("trigger_price") or a.get("anchor") or 0)
    b = sum(px(a) * int(a.get("qty") or 0) for a in acts if a.get("op") == "买")
    s = sum(px(a) * int(a.get("qty") or 0) for a in acts if a.get("op") in SELL_OPS)
    net = (b - s) / (float(nav or 0) or 1.0)
    return {"trade": bool([a for a in acts if a.get("op") != "撤单"]), "dir": "加" if net > 0.02 else "减" if net < -0.02 else "不动",
            "n_new": len({str(a.get("code")) for a in acts if a.get("op") == "买" and str(a.get("code")) not in st["day_open"]}), "net_pct": round(net, 4)}


def log_jsonl(dirpath, date_dash, rec):
    try:
        f = Path(dirpath) / f"{date_dash}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:   # noqa: BLE001
        pass


# ---------- CLI ----------
TZZB_SKILLS = [x for x in mentors.ids("tzzb") if x != "buchitudou0"] + ["buchitudou0"]   # 10/17 读登记表; 土豆排末(原展示顺序)


def _show(asof):
    print(f"| 导师 | 窗口 | 持股只数上限 | 单日新开仓上限 | 近5日换手上限 | 出手日占比 | 开新仓门槛 | 单票上限(P80/集中型) | 0915首笔 | 跳过 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for s in TZZB_SKILLS:
        L = ledger_limits(s, asof)
        if not L:
            print(f"| {s} | 无账本 |"); continue
        g = f"基线 p_trade≥{GATE_P:.0%}" if L["low_freq"] else "不设"
        print(f"| {s} | {L['window'][0] if L['window'] else '-'}~{L['window'][1] if L['window'] else '-'}({L['n_days']}) | {L.get('n_hold_max')} | {L.get('new_open_max')} | "
              f"{'-' if L.get('turnover_max') is None else format(L['turnover_max'], '.0%')} | {'-' if L.get('trade_ratio') is None else format(L['trade_ratio'], '.0%')} | {g} | "
              f"{'-' if L.get('cap_single') is None else format(L['cap_single'], '.0%')}{'/集中' if L.get('conc') else ''} | "
              f"{'-' if L.get('first_frac') is None else format(L['first_frac'], '.1%')} | {'; '.join(L['skip']) or '-'} |")


def _backtest(since, until, out_json=None):
    """books 回算: 每链每日每 slot 的挂单(=当时 06 actions 落地的 plans 行)按当日开着约束逐单判定。
    状态近似: 日初持仓由成交回推; 同日前一 slot 的成交/未成交挂单计入; 订单金额=挂价×股数"""
    res = {}
    for s in TZZB_SKILLS:
        src = "A-cb" if s == "buchitudou0" else f"A-{s}"
        book = _jl(PAPER / "books" / f"{src}.json")
        if not book:
            continue
        orders = [o for o in book.get("orders") or [] if since <= str(o.get("date", "")) <= until]
        last = {}   # 账本重导入会在同 slot 留下被 CXL 的旧副本: 同(日,slot,方向,代码)只留最后一张
        for i, o in enumerate(orders):
            last[(o["date"], o.get("time"), o.get("side"), o["code"])] = i
        orders = [o for i, o in enumerate(orders) if last[(o["date"], o.get("time"), o.get("side"), o["code"])] == i]
        trades = book.get("trades") or []
        tid = {t["id"]: t for t in trades}
        days = sorted({o["date"] for o in orders})
        R = {"orders": 0, "buy_orders": 0, "blocked": 0, "by": {}, "rows": []}
        for d in days:
            lim = ledger_limits(s, d)
            base = baseline_of(s, d)
            if base is None:
                bp = TZZB / "model_out" / f"asof_{d}" / f"{d}.json"
                if bp.exists():
                    m = ((_jl(bp) or {}).get("mentors") or {}).get(s)
                    base = {"p_trade": ((m or {}).get("L1") or {}).get("p_trade"), "stale": (m or {}).get("stale_days")} if m else None
            # 日初账本: 回滚当日及以后的成交
            pos = {}
            for t in trades:
                if str(t["id"])[:10] < d:
                    q = int(t["qty"]) * (1 if t["side"] == "BUY" else -1)
                    pos[t["code"]] = pos.get(t["code"], 0) + q
            nav = next((n["nav"] for n in reversed(book.get("nav") or []) if n["date"] < d), 100000.0)
            slots = sorted({o.get("time", "09:15") for o in orders if o["date"] == d})
            for hm in slots:
                # 本 slot 之前当日已成交(订单 time < hm 且已 filled)与仍挂着的买单
                tday = [dict(id=f"{d}-x", side=tid[o["id"]]["side"], code=o["code"], qty=tid[o["id"]]["qty"], price=tid[o["id"]]["price"])
                        for o in orders if o["date"] == d and o.get("time", "09:15") < hm and o["id"] in tid]
                p_now = dict(pos)
                for t in tday:
                    p_now[t["code"]] = p_now.get(t["code"], 0) + int(t["qty"]) * (1 if t["side"] == "BUY" else -1)
                opens = [dict(o, status="open") for o in orders if o["date"] == d and o.get("time", "09:15") < hm and o["side"] == "BUY" and o["id"] not in tid
                         and o.get("status") not in ("void", "invalid", "blocked")]
                fake = {"positions": {c: {"qty": q} for c, q in p_now.items() if q > 0},
                        "trades": [t for t in trades if str(t["id"])[:10] < d] + tday,
                        "orders": opens, "nav": [n for n in book.get("nav") or [] if n["date"] < d]}
                st = chain_state(fake, d)
                acts = []
                for o in orders:
                    if o["date"] != d or o.get("time", "09:15") != hm or o.get("side") not in ("BUY", "SELL"):
                        continue
                    acts.append({"op": "买" if o["side"] == "BUY" else "卖", "code": o["code"], "name": o["code"], "qty": int(o["qty"]), "_px": float(o["price"]), "_id": o["id"]})
                if not acts:
                    continue
                hard, soft, S = check_06(lim, st, acts, nav, base, slot=hm.replace(":", ""), sub=hm != "09:15")
                nb = sum(1 for a in acts if a["op"] == "买")
                R["orders"] += len(acts); R["buy_orders"] += nb
                drop, keep, h2 = 0, list(acts), hard
                while h2:   # 最少要砍几张买单才过硬约束(先砍新开仓票, 从后往前; 软约束=首笔缩量, 不砍)
                    nj = [j for j, a in enumerate(keep) if a["op"] == "买" and a["code"] not in st["day_open"]]
                    i = max(nj or [j for j, a in enumerate(keep) if a["op"] == "买"])
                    keep.pop(i); drop += 1
                    h2, _, _ = check_06(lim, st, keep, nav, base, slot=hm.replace(":", ""), sub=hm != "09:15")
                R["dropped"] = R.get("dropped", 0) + drop
                R["resize"] = R.get("resize", 0) + len(soft)
                if hard or soft:
                    R["blocked"] += nb   # 06 整单退回: 计本 slot 的买单数
                    for h in hard + soft:
                        k = ("持股只数" if "持股" in h else "新开仓" if "新开仓" in h and "不动" not in h else "换手" if "换手" in h else
                             "导师不动" if "不动" in h else "0915首笔" if "首笔" in h else "其他")
                        R["by"][k] = R["by"].get(k, 0) + 1
                    R["rows"].append({"date": d, "slot": hm, "buys": nb, "why": [x[:60] for x in hard + soft], "stat": S})
        res[s] = R
    if out_json:
        Path(out_json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    tot_b = sum(r["buy_orders"] for r in res.values()); tot_x = sum(r["blocked"] for r in res.values())
    tot_d = sum(r.get("dropped", 0) for r in res.values())
    print("| 导师 | 挂单数 | 买单 | 所在 slot 会被退回的买单 | 至少要砍的买单(硬约束) | 0915 首笔需缩量 | 触发原因(slot 次数) |")
    print("|---|---|---|---|---|---|---|")
    for s, r in res.items():
        print(f"| {s} | {r['orders']} | {r['buy_orders']} | {r['blocked']} ({r['blocked'] / max(1, r['buy_orders']):.0%}) | {r.get('dropped', 0)} ({r.get('dropped', 0) / max(1, r['buy_orders']):.0%}) | "
              f"{r.get('resize', 0)} | {', '.join(f'{k}{v}' for k, v in r['by'].items()) or '-'} |")
    print(f"| 合计 | {sum(r['orders'] for r in res.values())} | {tot_b} | {tot_x} ({tot_x / max(1, tot_b):.0%}) | {tot_d} ({tot_d / max(1, tot_b):.0%}) | {sum(r.get('resize', 0) for r in res.values())} | |")
    return res


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--asof")
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--since", default="2026-10-08")
    ap.add_argument("--until", default="2026-10-16")
    ap.add_argument("--json")
    a = ap.parse_args()
    if a.show:
        _show(a.asof)
    if a.backtest:
        _backtest(a.since, a.until, a.json)
