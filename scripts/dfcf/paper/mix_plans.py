# -*- coding: utf-8 -*-
"""mix_plans.py — paper 混合 skill 跟跑账本(零 token, 不联网; 2026-10-16 建, TODO「三、接下来」第 2 条)

三本账(各 10 万): A-mix=主规则 / A-mix-eq=等权消融对照(不学习, 准入只要 ≥2 链) / A-mix-lhb=主规则+昨日龙虎榜修正
每个 slot 在所有导师链 emit_plans 之后跑: 读当日各导师链(不含 control / A-mix*)账本 date=D 的挂单 → 按权重合成
plans/<D>_A-mix*.md(行格式同 README「plans 行格式」) → node matcher.mjs --import(PAPER_ROOT 透传, 沙盒/实盘同一套)

合成规则(用户 10/16 定):
  准入   同票同方向 ≥2 条导师链在 0915~本 slot 看好(各链取该票该方向最新一单, 已被 CXL@≤slot 撤掉的不算; 自废工具单
         =BUY 且 cancel_below≥挂价 不算), 且至少 1 条是当日高权重链(权重前 3 或 ≥1.5×平均); 本 slot 必须有看好链出新单才出单
         lhb: 只有 1 条高权重链看好但昨日龙虎榜机构或北向净买 → 也放行; 昨日拉萨天团净买 → 目标金额 ×0.5
  金额   目标 = Σ_看好链 w_i × (该链挂单金额 / 该链昨日 nav) × 混合账本昨日 nav; 单票上限=看好链动态上限按权重平均
         (夹 [8%,45%]); 减去已持有; 现金扣掉其他未成交买单后不够则缩量; 100 股取整(转债 10 张, 科创板 <200 股不出)
  挂价   看好链触发价按权重的加权中位数(取实际某条链的价, 不造价); 锚=看好链锚的加权中位数
  卖出v1 混合账本昨日持仓, "所有持有它的导师链(昨收持有 + 今日≤slot 买入)都已出卖单"才卖; 价=这些卖单挂价加权中位数;
         没有任何导师链持有(都已在前几日卖光)→ 以昨收挂卖
  权重   score_i = 收缩命中率(当日 02 市况多数票分组, Beta(5,5), baselines.json days[] 的 06 买单命中, as-of d1<D)/全体均值
                 × exp(0.5 × 相对对照组日均超额(百分点) × n/(n+10)) × 导师真人 60 日收益分位先验(0.8~1.2, UP/缺数=中位)
         w = softmax(log score)(10/18 撤温度退火, T 恒 1); 拟人度 delta≤0 → ×0.5; × Hedge 乘子; 再投影:
         每链保底 3%、单链动态上限 25%×风险系数(近 10 日日收益波动反比, 均值归 1)×市况适配(收缩命中率/均值) 夹 [8%,45%]、
         风格簇上限 35%(10/16 晚起: 簇按导师真人近 120 日日收益相关性逐日自动分, 平均相关 ≥0.5 归一簇; 无账本/停更的链用链自己 paper 收益(≥20 日)否则各自一簇;
         算不出时回落手标簇: 两融高杠杆=宣秋/antoo/冲5000w, 连板接力=刘忆青/大兴/芷影, ST 系=ST之狼/A658, 转债=土豆/高概率)
  学习   --learn --date D(EOD 后): h ← 投影(h × exp(η × clip(该链当日收益 − 等权平均, ±5 百分点))), η=0.5; 记录进 mix_state.json
         days[D].learn(每日一条, --rollback --date D 删 D 及之后的记录, 先备份)
  A-mix-eq: 全部导师链等权, 不学习, 准入只要 ≥2 链, 金额/上限/卖出同主规则

用法(项目根目录, scripts/venv/Scripts/python.exe -X utf8):
  mix_plans.py --init                              建三本混合账本(缺的才建)
  mix_plans.py --date 2026-10-19 --slot 0915 [--dry]   出单+import(--dry=只打印)
  mix_plans.py --learn --date 2026-10-19 [--dry]   EOD 后 Hedge 学习
  mix_plans.py --rollback --date 2026-10-19        回滚学习/权重记录(删 ≥D)
  mix_plans.py --weights --date 2026-10-19         只看当日权重表
  mix_plans.py --dryrun 2026-10-12 2026-10-16 [--out scripts/dfcf/paper/reports/mix_dryrun_20261016.md]  历史回演(内存模拟, 不写账本)
  mix_plans.py --selftest                          零 token 自测
环境: PAPER_ROOT=沙盒数据根(books/plans/mix_state.json 全走沙盒), 同 matcher
出口: 0=ok 1=用法错 2=import 失败(部分)
"""
import argparse
import ast
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA = Path(os.environ["PAPER_ROOT"]).resolve() if os.environ.get("PAPER_ROOT") else HERE
RESULTS = ROOT / "results"
MKT = ROOT / "downloads" / "market"
KDIR = ROOT / "downloads" / "quotes" / "daily"
TZZB = ROOT / "downloads" / "tzzb"
LHB = ROOT / "downloads" / "lhb"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LIVE_START = "2026-10-08"
INIT = 100000.0
MIX = {"A-mix": "main", "A-mix-eq": "eq", "A-mix-lhb": "lhb", "A-mix-sw": "sw"}   # 10/17 晚 +sw=扬长避短(主规则 × 导师强项地图: 负期望格子不跟/正期望格子加权 + 组合回撤闸)
P = dict(prior_a=5, prior_b=5, ex_k=10, ex_scale=0.5, eta=0.2, ex_clip=5.0, floor=0.03, cluster_cap=0.35,   # 10/17: eta 0.5→0.2(噪声带实验: 单日收益噪声 0.33pp, 0.5 下 10 天光噪声权重就漂 0.6~1.7 倍)
         cap_base=0.25, cap_lo=0.08, cap_hi=0.45, high_topk=3, high_mult=1.5, sim_penalty=0.5, lasa_mult=0.5,
         vol_win=10, T_days=10, prior_lo=0.8, prior_hi=1.2, mentor_win=60, mentor_stale_days=10,
         corr_win=120, corr_min_n=40, corr_min_paper=20, corr_thr=0.5,
         sw_prior_lo=0.5, sw_prior_hi=2.0, deadzone_k=2.0, ex_sigma0=1.09)   # 10/18 R14: 死区=2σ(σ 动态估, 缺省实测 1.09pp)   # B13: skill_weights 先验倍数夹在 [0.5, 2]   # corr_*: 10/16 晚 相关性分簇(真人近 120 日, 重叠 ≥40 日; 链 paper ≥20 日; 平均相关 ≥0.5 归一簇)
STATES = ["有主线", "无主线退潮", "普跌"]
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import a_rules as _AR  # noqa: E402  10/17: 交易规则统一模块
import mentors  # noqa: E402  10/17 二B-4: 导师登记表
CLUSTERS = {}   # 风格簇(用户 10/16 按 mentor_scope.json 定; 10/17 搬进登记表 cluster 字段); 不在表里的链各自一簇
for _e in mentors.all():
    if _e.get("cluster"):
        CLUSTERS.setdefault(_e["cluster"], []).append(_e["book"])


def FEE(side, amt, code=None, date=None):
    """10/17: 同 matcher.mjs fee() = a_rules.fees 的 佣金(万2.5, 最低5元)+印花税(只收股票卖方; 转债/ETF/LOF 免), 过户费不计。
    code=None → 按股票算(= 10/16 前旧口径)"""
    f = _AR.fees(side, amt, code or "600000", date, commission_rate=0.00025, min_commission=5.0)
    return f["commission"] + f["stamp"]


# ---------------- 基础 ----------------
def mentor_chains():
    """导师链名单(UP/tzzb 导师, 不含对照组与混合账本) → [(book, 显示名)]; 10/17 唯一真源改为导师登记表(原解析 accounts.mjs 文本)"""
    # 10/19 修: 退出 paper 的导师(paper_excluded.json)不再出新单, 却仍分到权重(8 位约占 1/3 权重质量), 稀释了混合账本的目标金额和"高权重链"门槛 → 只算在跑的
    ex = mentors.excluded()
    return [(e["book"], e["display"]) for e in mentors.all() if e["type"] in ("UP", "tzzb") and e["id"] not in ex]


def cluster_of(src):
    for c, mem in ACTIVE_CLUSTERS.items():
        if src in mem:
            return c
    return src


# ---------------- 10/16 晚用户批: 风格簇改由"导师真人收益相关性"自动分组(不用等链攒数据; 手标 CLUSTERS 只作兜底/自测夹具) ----------------
ACTIVE_CLUSTERS = CLUSTERS
TZZB = ROOT / "downloads" / "tzzb"


def real_returns(src, d, win):
    """导师真人日收益(同花顺账本 nav_daily.json index_list), 只取 < d 的最近 win 日(防后见之明); 无账本=None"""
    led = "buchitudou0" if src == "A-cb" else src[2:]
    try:
        il = json.loads((TZZB / led / "nav_daily.json").read_text(encoding="utf-8"))["ex_data"]["index_list"]
        il = ast.literal_eval(il) if isinstance(il, str) else il
    except (OSError, ValueError, KeyError, SyntaxError, TypeError):
        return None
    cut = d.replace("-", "")
    il = [x for x in il if str(x.get("date")) < cut and float(x.get("index") or 0) > 0][-(win + 1):]
    if not il or (datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(str(il[-1]["date"]), "%Y%m%d")).days > 3 * P["mentor_stale_days"]:
        return None   # 停更账本(冲5000w 停在 07/06)的旧相关性不代表现在, 按无账本处理
    return {il[i]["date"]: float(il[i]["index"]) / float(il[i - 1]["index"]) - 1 for i in range(1, len(il))} or None


def _corr(a, b, min_n):
    ds = sorted(set(a) & set(b))
    if len(ds) < min_n:
        return None
    x, y = [a[k] for k in ds], [b[k] for k in ds]
    mx, my = sum(x) / len(x), sum(y) / len(y)
    vx, vy = sum((v - mx) ** 2 for v in x), sum((v - my) ** 2 for v in y)
    return None if vx <= 0 or vy <= 0 else sum((p - mx) * (q - my) for p, q in zip(x, y)) / (vx * vy) ** 0.5


def corr_clusters(d, chains, books=None):
    """两两相关: 双方都有真人账本=真人日收益(近 corr_win 日, 重叠 ≥corr_min_n); 否则用链自己的 paper 日收益(重叠 ≥corr_min_paper)。
    平均连接聚类: 两簇间平均相关(缺失按 0)≥ corr_thr 才合并。返回 ({簇名: [链]}, 相关矩阵); 失败调用方回落手标 CLUSTERS"""
    R = {s: real_returns(s, d, P["corr_win"]) for s in chains}
    paper = {}
    for s in chains:
        try:
            paper[s] = {k: v for k, v in daily_returns(books[s], upto=d)} if books and s in books else {}
        except Exception:   # noqa: BLE001
            paper[s] = {}
    C = {}
    for i, a in enumerate(chains):
        for b in chains[i + 1:]:
            c = _corr(R[a], R[b], P["corr_min_n"]) if R[a] and R[b] else _corr(paper[a], paper[b], P["corr_min_paper"])
            C[(a, b)] = C[(b, a)] = c
    groups = [[s] for s in chains]
    while True:
        best, pair = P["corr_thr"], None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                cs = [C.get((a, b)) or 0.0 for a in groups[i] for b in groups[j]]
                avg = sum(cs) / len(cs)
                if avg >= best:
                    best, pair = avg, (i, j)
        if not pair:
            break
        i, j = pair
        groups[i] += groups.pop(j)
    out = {"相关簇" + "+".join(sorted(x[2:] for x in g)): sorted(g) for g in groups if len(g) > 1}
    return out, C


def refresh_clusters(d, chains, books=None):
    """按日刷新 ACTIVE_CLUSTERS; 任何异常 → 回落手标 CLUSTERS(fail-open)"""
    global ACTIVE_CLUSTERS
    try:
        ACTIVE_CLUSTERS, _ = corr_clusters(d, chains, books)
    except Exception as e:   # noqa: BLE001
        print(f"WARN 相关性分簇失败, 回落手标风格簇: {e}")
        ACTIVE_CLUSTERS = CLUSTERS
    return ACTIVE_CLUSTERS


def skill_of(src):
    return "buchitudou0" if src == "A-cb" else src[2:]


def hm(slot):
    s = str(slot).replace(":", "")
    return f"{s[:2]}:{s[2:4]}"


def load_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


_TD = None


def trading_days():
    """md/<年S季>/<日>.md = Java 交易日 md(与 baselines/report 同口径)"""
    global _TD
    if _TD is None:
        s = set()
        md = ROOT / "md"
        for sub in md.iterdir() if md.exists() else []:
            if sub.is_dir():
                for f in sub.glob("????-??-??.md"):
                    s.add(f.stem)
        _TD = sorted(s)
    return _TD


def prev_td(d):
    xs = [x for x in trading_days() if x < d]
    return xs[-1] if xs else None


def lot_of(code):
    return 10 if re.match(r"^1[12]", code) else 100


def fmt_px(x):
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    return s or "0"


def wmedian(pairs):
    """加权中位数(下中位, 取实际元素): pairs=[(value, weight)]"""
    ps = sorted((v, w) for v, w in pairs if v is not None and w > 0)
    if not ps:
        return None
    tot, acc = sum(w for _, w in ps), 0.0
    for v, w in ps:
        acc += w
        if acc >= tot / 2 - 1e-12:
            return v
    return ps[-1][0]


# ---------------- 账本读 ----------------
def load_books(srcs, books_dir=None):
    d = Path(books_dir) if books_dir else DATA / "books"
    out = {}
    for s in srcs:
        b = load_json(d / f"{s}.json")
        if b:
            out[s] = b
    return out


def nav_before(b, d):
    xs = [n for n in b.get("nav", []) if LIVE_START <= n["date"] < d]
    return float(xs[-1]["nav"]) if xs else INIT


def daily_returns(b, upto=None, incl=False):
    """实盘段(≥10/8)日收益(百分点) {date: r}; upto=只到该日之前(incl=含当日)"""
    navs = sorted((n["date"], float(n["nav"])) for n in b.get("nav", []) if n["date"] >= LIVE_START)
    out, prev = {}, INIT
    for d, v in navs:
        if upto and (d > upto or (d == upto and not incl)):
            break
        if prev > 0:
            out[d] = (v / prev - 1) * 100
        prev = v
    return out


def start_positions(b, d):
    """D 日开盘前持仓(按流水重放 qty, trade id 以日期开头)"""
    pos = defaultdict(int)
    for t in b.get("trades", []):
        if str(t["id"])[:10] >= d:
            continue
        pos[t["code"]] += t["qty"] if t["side"] == "BUY" else -t["qty"]
    return {c: q for c, q in pos.items() if q > 0}


def is_tool_order(o):
    """自废工具单: BUY 且 cancel_below≥挂价(首快照即失效, 链拿它当撤单工具用, 不代表看好)"""
    cb = (o.get("cond") or {}).get("cancel_below")
    return o["side"] == "BUY" and cb is not None and cb >= o["price"]


def cxl_time(o):
    m = re.search(r"CXL@(\d{1,2}:\d{2})", o.get("note") or "")
    return m.group(1).zfill(5) if m else None


def views(book, d, slot_hm, side):
    """该链 D 日 0915~slot 对每只票该方向的最新有效单 {code: order}"""
    best = {}
    for o in book.get("orders", []):
        if o.get("date") != d or o.get("side") != side or o.get("time", "99:99") > slot_hm:
            continue
        if not (o.get("qty") or 0) > 0 or not (o.get("price") or 0) > 0:
            continue
        k = (o["time"], o["id"])
        if o["code"] not in best or k > (best[o["code"]]["time"], best[o["code"]]["id"]):
            best[o["code"]] = o
    out = {}
    for c, o in best.items():
        ct = cxl_time(o)
        if (ct and ct <= slot_hm) or is_tool_order(o):
            continue
        out[c] = o
    return out


# ---------------- 外部统计(全部本地只读) ----------------
def norm_state(v):
    s = str(v or "").strip()
    hit = [a for a in STATES if s.startswith(a)]
    if hit:
        return sorted(hit, key=len)[-1]
    pre = [a for a in STATES if a.startswith(s)] if len(s) >= 2 else []
    return pre[0] if len(pre) == 1 else None


def last_contract(f):
    try:
        bl = re.findall(r"```contract\s*\n([\s\S]*?)```", Path(f).read_text(encoding="utf-8"))
        return json.loads(bl[-1]) if bl else None
    except (OSError, ValueError):
        return None


_BASE = None


def baselines():
    global _BASE
    if _BASE is None:
        _BASE = load_json(DATA / "baselines.json") or load_json(HERE / "baselines.json") or {}
    return _BASE


REGIME_SLOT = None   # 10/20 晚(市况改造 R5 + open_live, 用户批): run_slot 设成当前时段 → 市况读 ≤ 该时段最新一次子链 02(子链已看过开盘实况), 没有才退回 0915


def chain_state(src, d):
    d8 = d.replace("-", "")
    for key in (f"live-{d8}", f"asof-{d8}"):
        dr = RESULTS / f"{skill_of(src)}_chain" / key
        if REGIME_SLOT:
            later = sorted(x.name for x in (dr / "slots").glob("*") if x.name.isdigit() and "0915" < x.name <= REGIME_SLOT and (x / "02_analysis.md").exists()) if (dr / "slots").exists() else []
            for s in reversed(later):
                st_ = norm_state((last_contract(dr / "slots" / s / "02_analysis.md") or {}).get("market_state"))
                if st_:
                    return st_
        f = dr / "slots" / "0915" / "02_analysis.md"
        if f.exists():
            return norm_state((last_contract(f) or {}).get("market_state"))
        if (dr / "02_analysis.md").exists() and not (dr / "02_analysis.prev.md").exists():
            return norm_state((last_contract(dr / "02_analysis.md") or {}).get("market_state"))
    for r in baselines().get("days", []):
        if r.get("d") == d and r.get("src") == src:
            return r.get("regime")
    return None


def _latest_02(src, d):
    """该链 ≤ REGIME_SLOT 最新一次 02 合同(子链优先, 没有退 0915 / 顶层)"""
    d8 = d.replace("-", "")
    for key in (f"live-{d8}", f"asof-{d8}"):
        dr = RESULTS / f"{skill_of(src)}_chain" / key
        if not dr.exists():
            continue
        cands = sorted(x.name for x in (dr / "slots").glob("*") if x.name.isdigit() and (not REGIME_SLOT or x.name <= REGIME_SLOT) and (x / "02_analysis.md").exists()) if (dr / "slots").exists() else []
        for s in reversed(cands):
            c = last_contract(dr / "slots" / s / "02_analysis.md")
            if c:
                return c
        if (dr / "02_analysis.md").exists():
            return last_contract(dr / "02_analysis.md")
    return None


def evidence_lean(d, srcs):
    """10/20 晚 市况改造 R4: 各链 02 evidence 因子表按 params.yaml regime_evidence_weights 加权 → 每链 [-1, 1], 再取平均(偏强 +1 / 中性 0 / 偏弱 −1)"""
    try:
        import yaml
        w = (yaml.safe_load((HERE / "params.yaml").read_text(encoding="utf-8")) or {}).get("regime_evidence_weights") or {}
    except Exception:   # noqa: BLE001
        w = {}
    w = w or {"外围过程": 1.0, "亚洲盘实时": 1.5, "多指数对比": 1.0, "T-1结构": 1.0, "开盘情景": 1.0, "相似市况": 0.5}
    val = {"偏强": 1, "中性": 0, "偏弱": -1}
    per = {}
    for s in srcs:
        ev = (_latest_02(s, d) or {}).get("evidence") or []
        num = sum(float(w.get(x.get("factor"), 0)) * val.get(x.get("lean"), 0) for x in ev if isinstance(x, dict))
        den = sum(float(w.get(x.get("factor"), 0)) for x in ev if isinstance(x, dict) and x.get("lean") in val)
        if den:
            per[s] = round(num / den, 3)
    return (round(sum(per.values()) / len(per), 3) if per else None), per


def day_regime(d, chains):
    votes = Counter(s for s in (chain_state(c, d) for c in chains) if s)
    # 10/20 晚 市况改造 R4(用户批, 开关 MIX_REGIME_R4): 市况结构标签不再按 16 个导师视角计票(各链按本导师能力圈判, 多数票≠全市场),
    #   改用对照组(无导师视角)的最新 02; 对照组缺 → 退回计票。各链 02 因子表加权得到的方向分(lean, −1~+1)一并记录
    if _mix_flag("MIX_REGIME_R4"):
        ctl = chain_state("A-control", d)
        lean, per = evidence_lean(d, list(chains) + ["A-control"])
        extra = {"_口径": "对照组 02" if ctl else "对照组缺, 退回计票", "_因子方向分": lean}
        if ctl:
            return ctl, {**dict(votes), **extra}
        if not votes:
            return None, extra
        return max(votes.items(), key=lambda kv: (kv[1], -STATES.index(kv[0])))[0], {**dict(votes), **extra}
    if not votes:
        return None, {}
    best = max(votes.items(), key=lambda kv: (kv[1], -STATES.index(kv[0])))[0]
    return best, dict(votes)


def hit_stats(d):
    """as-of 命中: baselines.json days[] 里 d1<D 的 06 买单(成交且已结算) → {src: {regime: [n, hit]}}"""
    out = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in baselines().get("days", []):
        if not r.get("d1") or r["d1"] >= d or not r.get("regime"):
            continue
        for x in (r.get("legs") or {}).get("06") or []:
            if x.get("fill") and x.get("gross") is not None:
                c = out[r["src"]][r["regime"]]
                c[0] += 1
                c[1] += 1 if x["gross"] > 0 else 0
    return out


def mentor_pct(chains, d):
    """导师真人 60 日收益(tzzb nav_daily index_list, 只取 <D) → 分位 0~1; UP/缺数/陈旧=None"""
    d8 = d.replace("-", "")
    stale = (datetime.strptime(d, "%Y-%m-%d") - timedelta(days=P["mentor_stale_days"])).strftime("%Y%m%d")
    ret = {}
    for src in chains:
        j = load_json(TZZB / skill_of(src) / "nav_daily.json")
        il = [x for x in ((j or {}).get("ex_data") or {}).get("index_list") or [] if x.get("date", "") < d8]
        if len(il) < 5 or il[-1]["date"] < stale:
            continue
        a, b = float(il[max(0, len(il) - 1 - P["mentor_win"])]["index"]), float(il[-1]["index"])
        if a > 0:
            ret[src] = b / a - 1
    if len(ret) < 2:
        return {s: None for s in chains}, ret
    xs = sorted(ret.values())
    pct = {s: (sum(1 for v in xs if v < r) + 0.5 * (sum(1 for v in xs if v == r) - 1)) / (len(xs) - 1) for s, r in ret.items()}
    return {s: pct.get(s) for s in chains}, ret


def sim_delta():
    j = load_json(DATA / "similarity.json") or load_json(HERE / "similarity.json") or {}
    return {r["book"]: r.get("delta") for r in j.get("summary", [])}


def lhb_flags(d):
    """昨日(D 前一交易日)龙虎榜: {code: {inst_bx: bool, lasa: bool}}; 缺数据={}"""
    pd = prev_td(d)
    if not pd:
        return {}, None
    dp = LHB / pd.replace("-", ".")
    if not dp.exists():
        return {}, pd
    sys.path.insert(0, str(ROOT / "scripts" / "lhb"))
    try:
        import lhb_lib as L   # noqa: PLC0415
    except Exception:
        return {}, pd
    r = L.load_day(dp)
    if not r:
        return {}, pd
    out = {}
    for st in r[1]:
        jg = sum(s["net"] for s in st["seats"] if s["is_jg"])
        bx = sum(s["net"] for s in st["seats"] if s["is_bx"])
        ls = sum(s["net"] for s in st["seats"] if L.YOUZI.get(s["short"]) == "拉萨天团")
        out[st["code"]] = {"inst_bx": jg > 0 or bx > 0, "lasa": ls > 0, "jg": jg, "bx": bx, "ls": ls}
    return out, pd


_BAR = {}


def day_bar(code, d):
    """不复权日线 {o,h,l,c,pc,lu}: downloads/market/<D>/kline_day.jsonl → 日线归档"""
    if d not in _BAR:
        m = {}
        f = MKT / d / "kline_day.jsonl"
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line:
                    continue
                r = json.loads(line)
                m[r["symbol"][-6:]] = {"o": r["open"], "h": r["high"], "l": r["low"], "c": r["close"], "pc": r.get("preClose"), "lu": r.get("limitUp")}
        _BAR[d] = m
    if code in _BAR[d]:
        return _BAR[d][code]
    kl = (load_json(KDIR / f"{code}.json") or {}).get("klines") or []
    for i, k in enumerate(kl):
        if k["d"] == d:
            return {"o": k["o"], "h": k["h"], "l": k["l"], "c": k["c"], "pc": kl[i - 1]["c"] if i else None, "lu": None}
    return None


def ref_close(code, d):
    pd = prev_td(d)
    b = day_bar(code, pd) if pd else None
    return b["c"] if b else None


# ---------------- 权重 ----------------
def project(w, caps, floor=None, ccap=None, iters=500):
    """投影到 {Σ=1, floor≤w_i≤cap_i, 每簇Σ≤ccap}(单链也是一簇); 迭代夹紧+按余量比例回填"""
    floor = P["floor"] if floor is None else floor
    ccap = P["cluster_cap"] if ccap is None else ccap
    keys = list(w)
    hi = {k: min(caps.get(k, 1.0), ccap) for k in keys}
    cl = defaultdict(list)
    for k in keys:
        cl[cluster_of(k)].append(k)
    tot = sum(max(v, 1e-12) for v in w.values())
    x = {k: max(w[k], 1e-12) / tot for k in keys}
    for _ in range(iters):
        x = {k: min(max(x[k], floor), hi[k]) for k in keys}
        for mem in cl.values():
            s = sum(x[m] for m in mem)
            if s > ccap + 1e-12:
                fl = floor * len(mem)
                f = (ccap - fl) / (s - fl) if s > fl else 0.0
                for m in mem:
                    x[m] = floor + (x[m] - floor) * f
        diff = 1.0 - sum(x.values())
        if abs(diff) < 1e-10:
            break
        if diff > 0:
            sat = {c for c, mem in cl.items() if sum(x[m] for m in mem) >= ccap - 1e-12}
            free = [k for k in keys if x[k] < hi[k] - 1e-12 and cluster_of(k) not in sat]
            base = sum(x[k] for k in free)
            if base <= 0:
                break
            for k in free:
                x[k] += diff * x[k] / base
        else:
            free = [k for k in keys if x[k] > floor + 1e-12]
            base = sum(x[k] - floor for k in free)
            if base <= 0:
                break
            for k in free:
                x[k] += diff * (x[k] - floor) / base
    return x


def compute_weights(inp):
    """纯函数. inp: chains, regime, hits{src:{reg:[n,h]}}, ex{src:(mean_pp,n)}, prior_pct{src:pct|None}, sim{src:delta},
    vol{src:std_pp|None}, days(实盘天数), hedge{src:h}|None → dict(w, eq, caps, high, parts)"""
    ch, reg = inp["chains"], inp["regime"]
    a, b = P["prior_a"], P["prior_b"]
    p = {}
    for s in ch:
        hs_ = inp["hits"].get(s, {})
        if reg:
            n, h = hs_.get(reg) or [0, 0]
        else:   # 当日市况未知(02 缺)=不分组, 各市况合并
            n, h = sum(v[0] for v in hs_.values()), sum(v[1] for v in hs_.values())
        p[s] = (h + a) / (n + a + b)
    pm = sum(p.values()) / len(ch)
    T = 1.0   # 10/18 审计④ R15(用户定)撤掉温度退火: 原 T=1/√(1+天数/10) 让集中度只随日历变大、和证据多少无关; 市场不平稳, 恒为 1
    parts, logit = {}, {}
    for s in ch:
        m, n = inp["ex"].get(s, (0.0, 0))
        exs = m * n / (n + P["ex_k"])
        sw = (inp.get("sw_prior") or {}).get(s)
        if sw is not None:   # 10/16 晚 B13: 长期先验=skill_weights(拟人度×真人业绩) 相对等权的倍数; 有它就不再用真人收益分位
            prior = min(P["sw_prior_hi"], max(P["sw_prior_lo"], sw))
        else:
            pr = inp["prior_pct"].get(s)
            prior = 1.0 if pr is None else P["prior_lo"] + (P["prior_hi"] - P["prior_lo"]) * pr
        score = (p[s] / pm) * math.exp(P["ex_scale"] * exs) * prior
        logit[s] = math.log(score) / T
        parts[s] = {"p": round(p[s], 4), "ex_shr": round(exs, 4), "prior": round(prior, 3), "score": round(score, 4)}
    mx = max(logit.values())
    raw = {s: math.exp(logit[s] - mx) for s in ch}
    for s in ch:
        dl = inp["sim"].get(s)
        if dl is not None and dl <= 0 and not inp.get("sw_prior"):   # B13: 拟人度已进 skill_weights 先验, 不再另外减半
            raw[s] *= P["sim_penalty"]
            parts[s]["sim_half"] = True
    hed = inp.get("hedge") or {}
    if hed:
        hs = sum(hed.get(s, 1 / len(ch)) for s in ch)
        for s in ch:
            raw[s] *= hed.get(s, 1 / len(ch)) / hs * len(ch)
    # 动态上限
    inv = {s: 1 / max(v, 0.05) for s, v in inp["vol"].items() if v is not None}
    im = sum(inv.values()) / len(inv) if inv else 1
    caps = {}
    for s in ch:
        risk = inv[s] / im if s in inv else 1.0
        fit = p[s] / pm
        caps[s] = min(max(P["cap_base"] * risk * fit, P["cap_lo"]), P["cap_hi"])
        parts[s].update(risk=round(risk, 3), fit=round(fit, 3), cap=round(caps[s], 4))
    w = project(raw, caps)
    eq = {s: 1 / len(ch) for s in ch}
    rank = sorted(ch, key=lambda s: -w[s])
    high = set(rank[:P["high_topk"]]) | {s for s in ch if w[s] >= P["high_mult"] / len(ch) - 1e-12}
    return {"w": w, "eq": eq, "caps": caps, "high": high, "parts": parts, "T": T}


def gather_inputs(d, books, chains, hedge):
    reg, votes = day_regime(d, chains)
    ctrl = daily_returns(books["A-control"], upto=d) if "A-control" in books else {}
    ex, vol = {}, {}
    for s in chains:
        r = daily_returns(books[s], upto=d) if s in books else {}
        both = [r[x] - ctrl[x] for x in r if x in ctrl]
        ex[s] = (sum(both) / len(both), len(both)) if both else (0.0, 0)
        last = [r[x] for x in sorted(r)][-P["vol_win"]:]
        if len(last) >= 3:
            mu = sum(last) / len(last)
            vol[s] = math.sqrt(sum((v - mu) ** 2 for v in last) / (len(last) - 1))
        else:
            vol[s] = None
    days = len([x for x in trading_days() if LIVE_START <= x < d])
    pct, ret60 = mentor_pct(chains, d)
    return {"sw_prior": skill_weights_prior(chains, d), "chains": chains, "regime": reg, "votes": votes, "hits": hit_stats(d), "ex": ex, "prior_pct": pct, "ret60": ret60,
            "sim": sim_delta(), "vol": vol, "days": days, "hedge": hedge}


def skill_weights_prior(chains, d):
    """10/16 晚 B13: 读 d 之前最新一份 weights/<日>.json(skill_weights.py, 拟人度×真人业绩), 换成相对等权的倍数(=w×N); 没有=None(回落旧先验)"""
    wd = HERE / "weights"
    try:
        fs = sorted(f for f in wd.glob("????-??-??.json") if f.stem < d)
        if not fs:
            return None
        rows = {r["src"]: r["w"] for r in json.loads(fs[-1].read_text(encoding="utf-8"))["rows"]}
        got = {s: rows[s] for s in chains if s in rows}
        if len(got) < 2:
            return None
        tot = sum(got.values())
        return {s: v / tot * len(got) for s, v in got.items()}
    except Exception:   # noqa: BLE001
        return None


# ---------------- 状态(mix_state.json) ----------------
class State:
    def __init__(self, path):
        self.path = Path(path)
        self.s = load_json(self.path) or {"version": 1, "params": P, "days": {}}

    def hedge_before(self, d, chains):
        ds = sorted(x for x, v in self.s["days"].items() if x < d and v.get("learn"))
        h = dict(self.s["days"][ds[-1]]["learn"]["h_after"]) if ds else {}
        h = {c: h.get(c, 1 / len(chains)) for c in chains}
        t = sum(h.values())
        return {c: v / t for c, v in h.items()}, (ds[-1] if ds else None)

    def put(self, d, key, val):
        self.s["days"].setdefault(d, {})[key] = val
        self.s["params"] = P

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.s, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def rollback(self, d):
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_name(f"mix_state.bak-{datetime.now():%Y%m%d%H%M%S}.json"))
        gone = sorted(x for x in self.s["days"] if x >= d)
        for x in gone:
            del self.s["days"][x]
        return gone


def weights_for(d, books, chains, state):
    refresh_clusters(d, chains, books)   # 10/16 晚: 风格簇按导师真人收益相关性逐日重算(只用 <d 的数据)
    hedge, hfrom = state.hedge_before(d, chains)
    inp = gather_inputs(d, books, chains, hedge)
    W = compute_weights(inp)
    W["regime"], W["votes"], W["hedge_from"], W["inp"] = inp["regime"], inp["votes"], hfrom, inp
    return W


def learn_update(h_before, rets, caps, sigma=None):
    """纯函数: Hedge 一步. rets={src: 当日收益百分点}(缺=不更新该链)
    10/18 审计④ R14(用户定"要动态学, 不要固定冻结天数"): 加死区——只学超出噪声的那部分: x = sign(d)·max(|d| − dz·σ, 0),
      σ = 链相对等权均值的日超额标准差, 由历史 learn 记录动态估(sigma 参数; 缺=实测 1.09pp); 单日超额在 dz·σ 以内=当噪声不调权重,
      真有本事的链会反复超出死区、权重自然累积上去; 不设冻结期"""
    have = {s: r for s, r in rets.items() if r is not None}
    mean = sum(have.values()) / len(have) if have else 0.0
    sig = sigma if sigma else P.get("ex_sigma0", 1.09)
    dz = P.get("deadzone_k", 2.0) * sig
    ex = {s: max(-P["ex_clip"], min(P["ex_clip"], have[s] - mean)) if s in have else 0.0 for s in h_before}
    x = {s: math.copysign(max(abs(v) - dz, 0.0), v) for s, v in ex.items()}
    raw = {s: h_before[s] * math.exp(P["eta"] * x[s]) for s in h_before}
    return project(raw, caps), ex, mean


def ex_sigma(state, d, lookback=20):
    """日超额噪声 σ(百分点): 近 lookback 个已学日的 ex_pp 全部样本的标准差; 少于 5 天 → None(用实测缺省)"""
    ds = sorted(x for x, v in state.s["days"].items() if x < d and (v.get("learn") or {}).get("ex_pp"))[-lookback:]
    if len(ds) < 5:
        return None
    vals = [float(v) for x in ds for v in state.s["days"][x]["learn"]["ex_pp"].values()]
    if len(vals) < 10:
        return None
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


def do_learn(d, books, chains, state):
    rets = {}
    for s in chains:
        r = daily_returns(books[s], upto=d, incl=True) if s in books else {}
        rets[s] = r.get(d)
    W = weights_for(d, books, chains, state)
    h_before, _ = state.hedge_before(d, chains)
    sig = ex_sigma(state, d)
    h_after, ex, mean = learn_update(h_before, rets, W["caps"], sig)
    rec = {"at": datetime.now().isoformat(timespec="seconds"), "eq_mean_pp": round(mean, 4), "ex_pp": {s: round(v, 4) for s, v in ex.items()},
           "sigma_pp": round(sig, 3) if sig else None, "deadzone_pp": round(P.get("deadzone_k", 2.0) * (sig or P.get("ex_sigma0", 1.09)), 3),
           "h_before": {s: round(v, 6) for s, v in h_before.items()}, "h_after": {s: round(v, 6) for s, v in h_after.items()},
           "missing": [s for s, r in rets.items() if r is None]}
    state.put(d, "learn", rec)
    return rec


# ---------------- A-mix-sw 扬长避短(10/17 晚; 设计 docs/research/mix_strengths_weaknesses_20261017.md) ----------------
def _sw_params():
    try:
        import yaml
        return (yaml.safe_load((HERE / "params.yaml").read_text(encoding="utf-8")) or {}).get("mix_sw") or {}
    except Exception:   # noqa: BLE001
        return {}


def _plays_of(sk, d):
    """该链 D 日 04 contract 里每只候选的打法标签 {code: play}(04 候选池约束要求写 play)"""
    d8 = d.replace("-", "")
    out = {}
    base = RESULTS / f"{sk}_chain"
    for rd in (base / f"live-{d8}", base / f"asof-{d8}"):
        for f in sorted(rd.glob("**/04_plan.md")) if rd.exists() else []:
            for m in re.finditer(r'"code"\s*:\s*"(\d{6})"[^{}]*?"play"\s*:\s*"([^"]+)"|"play"\s*:\s*"([^"]+)"[^{}]*?"code"\s*:\s*"(\d{6})"',
                                 f.read_text(encoding="utf-8", errors="replace")):
                code, play = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
                out[code] = play
    return out


def _temp_of(d, bins):
    """D 的前一交易日涨停家数 → 冷/温/热(与 edge_map 同口径)"""
    try:
        pd_ = prev_td(d)
        n = 0
        with open(MKT / pd_ / "kline_day.jsonl", encoding="utf-8") as fh:
            for line in fh:
                k = json.loads(line)
                if k.get("limitUp") and k.get("close") and abs(float(k["close"]) - float(k["limitUp"])) < 1e-6:
                    n += 1
        return "冷" if n < bins[0] else "温" if n < bins[1] else "热"
    except Exception:   # noqa: BLE001
        return "未知"


def sw_factors(d, chains_books):
    """{(src, code): 乘子} 与 {(src, code): 说明}: cut→0, boost→boost_mult, 其余 1; 地图=edge_map/<D>.json(缺=现算, 失败=全 1)"""
    sp = _sw_params()
    boost = float(sp.get("boost_mult", 1.5))
    try:
        sys.path.insert(0, str(HERE))
        import edge_map as EM   # noqa: PLC0415
        f = HERE / "edge_map" / f"{d}.json"
        em = json.loads(f.read_text(encoding="utf-8")) if f.exists() else EM.build(d)
        temp = _temp_of(d, (sp.get("temp_bins") or [40, 80]))
    except Exception as e:   # noqa: BLE001
        print(f"WARN: A-mix-sw 强项地图不可用, 本次按主规则: {e}")
        return {}, {}
    fac, note = {}, {}
    for s, b in chains_books.items():
        sk = skill_of(s)
        plays = _plays_of(sk, d)
        for o in b.get("orders", []):
            if o.get("date") != d or o.get("side") != "BUY":
                continue
            pl = plays.get(o["code"])
            if not pl:
                continue
            act, sh = EM.lookup(em, sk, pl, temp)
            if act == "cut":
                fac[(s, o["code"])], note[(s, o["code"])] = 0.0, f"{pl}|{temp} 弱项{sh:+.1%}"
            elif act == "boost":
                fac[(s, o["code"])], note[(s, o["code"])] = boost, f"{pl}|{temp} 强项{sh:+.1%}"
    return fac, note


def sw_dd_mult(mix, d):
    """组合回撤闸: 混合账本净值从高点回撤 ≥ dd_gate → 新开仓金额 × dd_mult"""
    sp = _sw_params()
    navs = [n["nav"] for n in mix.get("nav", []) if n.get("date", "") < d and n.get("nav")]
    if not navs:
        return 1.0
    dd = navs[-1] / max(navs) - 1
    return float(sp.get("dd_mult", 0.5)) if dd <= -abs(float(sp.get("dd_gate", 0.10))) else 1.0


# ---------------- 10/18 晚(用户定"周三接, 先备好"): 扬长避短按"三态"再加权, 开关 MIX_REGIME(chain_flags.txt; 环境变量优先), 关 = 逐字节旧行为 ----
# 该票前一交易日的三态(indicators.jsonl) → 这条链对应导师在该状态下的历史期望(regime_trades.json, ≥10 笔才用):
#   期望 ≤ 0 → ×0(这条链的看好不算); 否则 × clip(该状态期望 / 全部期望, 0.5, 1.5)
def _mix_flag(name):
    v = os.environ.get(name)
    if v in ("0", "1"):
        return v == "1"
    try:
        for line in (ROOT / "scripts" / "claude_profile" / "chain_flags.txt").read_text(encoding="utf-8").splitlines():
            k, _, val = line.split("#")[0].partition("=")
            if k.strip() == name:
                return val.strip() == "1"
    except OSError:
        pass
    return False


_RG = {}


def regime_mult(src, code, d):
    if "rt" not in _RG:
        try:
            _RG["rt"] = json.loads((ROOT / "scripts" / "tzzb" / "model_out" / "regime_trades.json").read_text(encoding="utf-8")).get("mentors") or {}
        except (OSError, ValueError):
            _RG["rt"] = {}
    if d not in _RG:
        st = {}
        try:
            dirs = sorted(x.name for x in MKT.iterdir() if x.name < d and (x / "indicators.jsonl").exists())
            if dirs:
                for l in (MKT / dirs[-1] / "indicators.jsonl").read_text(encoding="utf-8").splitlines():
                    x = json.loads(l)
                    st[x["symbol"][2:]] = x["regime"]
        except (OSError, ValueError):
            pass
        _RG[d] = st
    mid = "buchitudou0" if src == "A-cb" else src[2:]
    R = _RG["rt"].get(mid) or {}
    s, a = R.get(f"状态|{_RG[d].get(str(code))}"), R.get("全部|全部")
    if not s or not a or s.get("n", 0) < 10:
        return 1.0
    if s["exp"] <= 0:
        return 0.0
    return max(0.5, min(1.5, s["exp"] / a["exp"])) if a["exp"] > 0 else 1.0


# ---------------- 合成(纯函数) ----------------
def plan_slot(d, slot, chains_books, mix, mode, W, lhb, refc):
    """返回 (lines, diag). chains_books={src: book}; mix=混合账本 book; W=compute_weights 结果; lhb={code:{inst_bx,lasa}}; refc(code)→昨收"""
    S = hm(slot)
    src = [k for k, v in MIX.items() if v == mode][0]
    w = W["eq"] if mode == "eq" else W["w"]
    high = set() if mode == "eq" else W["high"]
    caps = W["caps"]
    navm = nav_before(mix, d)
    swf, sw_note = (sw_factors(d, chains_books) if mode == "sw" else ({}, {}))
    dd_mult = sw_dd_mult(mix, d) if mode == "sw" else 1.0
    lines, diag = [], []
    # ---- 买 ----
    fav = defaultdict(dict)
    for s, b in chains_books.items():
        for c, o in views(b, d, S, "BUY").items():
            fav[c][s] = o
    open_buy = {o["code"]: o["price"] * o["qty"] for o in mix.get("orders", []) if o.get("status") == "open" and o["side"] == "BUY"}
    for code in sorted(fav):
        f = fav[code]
        if not any(o["time"] == S for o in f.values()):
            continue    # 本 slot 没有看好链出新单 → 不重复出
        if mode == "sw":   # 扬长避短: 链在本票上落在导师负期望格子 → 这条链的看好不算; 正期望 → 加权
            if _mix_flag("MIX_REGIME"):   # 10/18 晚备好, 周三开: 再按该票三态 × 导师在该状态的期望加权
                for s in f:
                    m = regime_mult(s, code, d)
                    if m != 1.0:
                        swf[(s, code)] = swf.get((s, code), 1.0) * m
                        sw_note[(s, code)] = ((sw_note.get((s, code)) or "") + f" 三态×{m:.2f}").strip()
            cut = [s for s in f if swf.get((s, code), 1.0) <= 0]
            f = {s: o for s, o in f.items() if s not in cut}
            if not f:
                diag.append({"book": src, "code": code, "side": "BUY", "act": "全部看好链落在导师弱项格子(不跟)", "cut": cut})
                continue
        nh = sum(1 for s in f if s in high)
        why = None
        lh = lhb.get(code) or {}
        if len(f) >= 2 and (mode == "eq" or nh >= 1):
            why = f"{len(f)}链共识" + ("" if mode == "eq" else f"(高权重{nh})")
        elif mode == "lhb" and len(f) == 1 and nh == 1 and lh.get("inst_bx"):
            why = "1高权重链+昨日龙虎榜机构/北向净买"
        if not why:
            diag.append({"book": src, "code": code, "side": "BUY", "n": len(f), "high": nh, "act": "不准入"})
            continue
        frac = sum(w[s] * (swf.get((s, code), 1.0) if mode == "sw" else 1.0) * (o["price"] * o["qty"]) / max(nav_before(chains_books[s], d), 1) for s, o in f.items())
        if mode == "sw":
            frac *= dd_mult
            tags = [f"{s[2:]}:{sw_note.get((s, code))}" for s in f if sw_note.get((s, code))]
            why += ("; 强项格子 " + "、".join(tags) if tags else "") + (f"; 组合回撤闸×{dd_mult}" if dd_mult < 1 else "")
        if mode == "lhb" and lh.get("lasa"):
            frac *= P["lasa_mult"]
            why += "; 昨日拉萨天团净买×0.5"
        wsum = sum(w[s] for s in f)
        cap = min(max(sum(w[s] * caps[s] for s in f) / wsum, P["cap_lo"]), P["cap_hi"])
        tgt = min(frac, cap) * navm
        price = wmedian([(o["price"], w[s]) for s, o in f.items()])
        anchor = wmedian([(o.get("anchor"), w[s]) for s, o in f.items()])
        lot = lot_of(code)
        held = (mix.get("positions", {}).get(code) or {}).get("qty", 0)
        q = int(tgt / price // lot * lot) - held
        avail = mix.get("cash", INIT) - sum(v for c2, v in open_buy.items() if c2 != code)
        while q > 0 and q * price + FEE("BUY", q * price, code) > avail:
            q -= lot
        if code.startswith("688") and 0 < q < 200:
            q = 0
        rec = {"book": src, "code": code, "side": "BUY", "n": len(f), "high": nh, "frac": round(frac, 5), "cap": round(cap, 4),
               "tgt": round(tgt), "price": price, "qty": max(q, 0), "held": held}
        if q <= 0:
            rec["act"] = "金额不足一手/已持够/现金不足"
            diag.append(rec)
            continue
        if any(o["code"] == code and o["side"] == "BUY" and o.get("date") == d and o.get("status") == "open"
               and abs(o["price"] - price) < 1e-9 and o["qty"] == q for o in mix.get("orders", [])):
            rec["act"] = "同价同量单已挂(不重出)"
            diag.append(rec)
            continue
        names = "、".join(f"{s[2:]}{w[s] * 100:.0f}%" for s in sorted(f, key=lambda s: -w[s]))
        lines.append(f"- {S} | {src} | BUY | {code} | {fmt_px(price)} | {q} | day | {fmt_px(anchor) if anchor else '-'} | - | "
                     f"mix[{mode}] {why}; 目标{frac * 100:.2f}%nav(上限{cap * 100:.0f}%); 链: {names}")
        rec["act"] = "出单"
        diag.append(rec)
        open_buy[code] = q * price
    # ---- 卖 v1 ----
    pos0 = start_positions(mix, d) if mix.get("trades") else {}
    for code, qty in sorted(pos0.items()):
        if any(o["code"] == code and o["side"] == "SELL" and o.get("date") == d and o.get("status") in ("open", "filled") for o in mix.get("orders", [])):
            continue
        cur = (mix.get("positions", {}).get(code) or {}).get("qty", 0)
        bought_today = 0 if re.match(r"^1[12]", code) else sum(t["qty"] for t in mix.get("trades", []) if t["side"] == "BUY" and t["code"] == code and str(t["id"])[:10] == d)
        sellable = min(qty, cur - bought_today) if cur else 0
        if sellable <= 0:
            continue
        holders, sold, new_here = [], {}, False
        for s, b in chains_books.items():
            held0 = start_positions(b, d).get(code, 0) > 0
            buy_now = code in views(b, d, S, "BUY")
            if not (held0 or buy_now):
                continue
            holders.append(s)
            sv = views(b, d, S, "SELL").get(code)
            if sv:
                sold[s] = sv
                new_here = new_here or sv["time"] == S
        if holders and len(sold) < len(holders):
            continue
        if holders and not new_here:
            continue    # 条件早已满足的情况(前面 slot 已出过)由"今日已有卖单"闸挡; 这里只在最后一条卖单到来的 slot 出
        if holders:
            price = wmedian([(o["price"], w[s]) for s, o in sold.items()])
            anchor = wmedian([(o.get("anchor"), w[s]) for s, o in sold.items()])
            why = f"持有它的 {len(holders)} 条导师链全部已出卖单: " + "、".join(s[2:] for s in holders)
        else:
            price, anchor = refc(code), None
            why = "已无任何导师链持有(前几日已卖光), 按昨收挂卖"
            if not price:
                diag.append({"book": src, "code": code, "side": "SELL", "act": "缺昨收, 跳过"})
                continue
        lines.append(f"- {S} | {src} | SELL | {code} | {fmt_px(price)} | {sellable} | day | {fmt_px(anchor) if anchor else '-'} | - | mix[{mode}] 卖v1: {why}")
        diag.append({"book": src, "code": code, "side": "SELL", "qty": sellable, "price": price, "holders": len(holders), "act": "出单"})
    return lines, diag


# ---------------- 落盘 + import ----------------
def write_plans(d, slot, src, lines, plans_dir=None):
    pdir = Path(plans_dir) if plans_dir else DATA / "plans"
    pdir.mkdir(parents=True, exist_ok=True)
    f = pdir / f"{d}_{src}.md"
    S = hm(slot)
    old = f.read_text(encoding="utf-8").splitlines() if f.exists() else [f"# {d} {src} 混合账本 plans(mix_plans.py 机械合成, 零 token)", ""]
    keep = [l for l in old if not re.match(rf"^-\s*{re.escape(S)}\s*\|", l)]   # 同 slot 重跑=替换本 slot 段(幂等)
    with open(f, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(keep + lines) + "\n")
    return f


def matcher_import(f):
    r = subprocess.run(["node", str(HERE / "matcher.mjs"), "--import", str(f)], cwd=ROOT, env=dict(os.environ), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
    return r.returncode, (r.stdout or "").strip().splitlines()[-1:] + ((r.stderr or "").strip().splitlines()[-3:] if r.returncode else [])


def init_books():
    import hashlib   # noqa: PLC0415
    bd = DATA / "books"
    bd.mkdir(parents=True, exist_ok=True)
    made = []
    for src in MIX:
        f = bd / f"{src}.json"
        if f.exists():
            continue
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"), "why": "init 10万(mix_plans)", "prev": "GENESIS"}
        entry["hash"] = hashlib.sha256(json.dumps({"c": 100000, "p": {}, "n": 0, "prev": "GENESIS"}, separators=(",", ":")).encode()).hexdigest()[:16]
        b = {"source": src, "cash": 100000, "positions": {}, "orders": [], "trades": [], "nav": [], "chain": [entry], "lastHash": entry["hash"]}
        f.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
        made.append(src)
    return made


def run_slot(d, slot, dry):
    chains = [s for s, _ in mentor_chains()]
    if not dry:
        init_books()
    books = load_books(chains + ["A-control"] + list(MIX))
    state = State(DATA / "mix_state.json")
    global REGIME_SLOT
    REGIME_SLOT = slot
    W = weights_for(d, books, chains, state)
    if not dry:
        state.put(d, "weights", {"regime": W["regime"], "votes": W["votes"], "T": round(W["T"], 4), "hedge_from": W["hedge_from"],
                                 "w": {s: round(v, 5) for s, v in W["w"].items()}, "caps": {s: round(v, 4) for s, v in W["caps"].items()},
                                 "high": sorted(W["high"]), "parts": W["parts"], "at": datetime.now().isoformat(timespec="seconds")})
        state.save()
    lhb, _ = lhb_flags(d)
    cb = {s: books[s] for s in chains if s in books}
    rc = 0
    for src, mode in MIX.items():
        mix = books.get(src) or {"source": src, "cash": INIT, "positions": {}, "orders": [], "trades": [], "nav": []}
        lines, diag = plan_slot(d, slot, cb, mix, mode, W, lhb, lambda c: ref_close(c, d))
        print(f"[{src}] {d} {hm(slot)} 出 {len(lines)} 单; 未准入/不足 {sum(1 for x in diag if x['act'] != '出单')}")
        for l in lines:
            print("   " + l)
        if dry or not lines:
            continue
        f = write_plans(d, slot, src, lines)
        code, tail = matcher_import(f)
        print(f"   import rc={code} {' '.join(tail)}")
        rc = rc or (2 if code else 0)
    return rc


def print_weights(d):
    chains = [s for s, _ in mentor_chains()]
    books = load_books(chains + ["A-control"])
    W = weights_for(d, books, chains, State(DATA / "mix_state.json"))
    print(f"{d} 市况={W['regime']} 票={W['votes']} T={W['T']:.3f} Hedge 来自={W['hedge_from']}")
    print("  风格簇(真人收益相关 ≥%.2f): %s" % (P["corr_thr"], "; ".join(f"{k}" for k in ACTIVE_CLUSTERS) or "无(各链各自一簇)"))
    for s in sorted(chains, key=lambda s: -W["w"][s]):
        pt = W["parts"][s]
        print(f"  {s:28s} w={W['w'][s] * 100:5.2f}% cap={pt['cap'] * 100:4.1f}% p={pt['p']:.3f} ex={pt['ex_shr']:+.3f} prior={pt['prior']:.2f} "
              f"risk={pt['risk']:.2f}{' 拟人≤0减半' if pt.get('sim_half') else ''}{' 高' if s in W['high'] else ''}")


# ---------------- 历史回演(内存, 不写账本) ----------------
def sim_import(mix, d, lines):
    for l in lines:
        f = [x.strip() for x in l[1:].split("|")]
        t, side, code, price, qty = f[0], f[2], f[3], float(f[4]), int(f[5])
        for o in mix["orders"]:
            if o["code"] == code and o["side"] == side and o["status"] == "open":
                o["status"] = "cxl"
        mix["orders"].append({"id": f"{d}-{mix['source']}-{len(mix['orders']) + 1:03d}", "date": d, "time": t, "side": side, "code": code,
                              "price": price, "qty": qty, "status": "open", "note": f[-1]})


def sim_eod(mix, d):
    """日线保守撮合(买 low≤挂价/一字涨停不成; 卖 high≥挂价; T+1)+废单+nav. 时序近似: 不区分挂单时刻"""
    filled = voided = 0
    for o in mix["orders"]:
        if o["date"] != d or o["status"] != "open":
            continue
        bar = day_bar(o["code"], d)
        ok = False
        if bar:
            if o["side"] == "BUY":
                sealed = bar.get("lu") and bar["l"] >= bar["lu"] - 1e-6
                ok = bar["l"] <= o["price"] and not sealed
            else:
                ok = bar["h"] >= o["price"]
        if ok:
            amt = o["price"] * o["qty"]
            fee = FEE(o["side"], amt, o["code"], d)
            if o["side"] == "BUY":
                if mix["cash"] < amt + fee:
                    o["status"] = "reject"
                    continue
                mix["cash"] -= amt + fee
                p = mix["positions"].setdefault(o["code"], {"qty": 0, "cost": 0.0})
                p["cost"] = (p["cost"] * p["qty"] + amt + fee) / (p["qty"] + o["qty"])
                p["qty"] += o["qty"]
            else:
                p = mix["positions"].get(o["code"])
                if not p or p["qty"] < o["qty"]:
                    o["status"] = "reject"
                    continue
                p["qty"] -= o["qty"]
                mix["cash"] += amt - fee
                if not p["qty"]:
                    del mix["positions"][o["code"]]
            o["status"] = "filled"
            mix["trades"].append({"id": o["id"], "side": o["side"], "code": o["code"], "price": o["price"], "qty": o["qty"], "fee": round(fee, 2)})
            filled += 1
        else:
            o["status"] = "void"
            voided += 1
    mv = 0.0
    for c, p in mix["positions"].items():
        bar = day_bar(c, d)
        mv += p["qty"] * (bar["c"] if bar else p["cost"])
    nav = round(mix["cash"] + mv, 2)
    mix["nav"].append({"date": d, "nav": nav, "cash": round(mix["cash"], 2), "mv": round(mv, 2)})
    return filled, voided, nav


def dryrun(d0, d1, out):
    chains = [s for s, _ in mentor_chains()]
    books = load_books(chains + ["A-control"])
    cb = {s: books[s] for s in chains if s in books}
    tmpd = Path(tempfile.mkdtemp(prefix="mix_dryrun_"))
    state = State(tmpd / "mix_state.json")
    mixes = {s: {"source": s, "cash": INIT, "positions": {}, "orders": [], "trades": [], "nav": []} for s in MIX}
    days = [x for x in trading_days() if d0 <= x <= d1]
    rep = [f"# 混合账本 dry-run {d0} ~ {d1}(mix_plans.py --dryrun, {datetime.now():%Y-%m-%d %H:%M} 生成, 零 token, 不写账本)", "",
           "口径: 读实盘 books/ 里各导师链当日挂单(按 slot 时刻逐段回演), 三本混合账本在内存里从 10 万起跑; 成交=日线保守近似"
           "(买 low≤挂价且非一字涨停 / 卖 high≥挂价 / T+1), 不分挂单时刻(会高估午后单成交率); Hedge 学习每日 EOD 后更新(状态存临时目录)。",
           "已知前视: similarity.json(拟人度 delta)只有最新一份, 回演前几天也用了它; 其余(命中率 d1<D、nav、导师真人净值、龙虎榜昨日)均 as-of。", ""]
    summary, all_lines = [], []
    for d in days:
        W = weights_for(d, books, chains, state)
        lhb, lpd = lhb_flags(d)
        slots = sorted({o["time"].replace(":", "") for b in cb.values() for o in b.get("orders", []) if o.get("date") == d})
        lines_day = {s: [] for s in MIX}
        diag_day = {s: [] for s in MIX}
        for sl in slots:
            for src, mode in MIX.items():
                lines, diag = plan_slot(d, sl, cb, mixes[src], mode, W, lhb, lambda c: ref_close(c, d))
                sim_import(mixes[src], d, lines)
                lines_day[src] += lines
                diag_day[src] += diag
        res = {src: sim_eod(mixes[src], d) for src in MIX}
        rec = do_learn(d, books, chains, state)
        state.save()
        cand = {}
        for b in cb.values():
            for o in b.get("orders", []):
                if o.get("date") == d and o["side"] == "BUY" and not is_tool_order(o):
                    cand.setdefault(o["code"], set()).add(b["source"])
        multi = sum(1 for v in cand.values() if len(v) >= 2)
        top = sorted(chains, key=lambda s: -W["w"][s])[:3]
        rep += [f"## {d}  市况={W['regime']} {W['votes']}  T={W['T']:.2f}  龙虎榜用 {lpd}({len(lhb)} 只)", "",
                f"- 导师链当日 BUY 票 {len(cand)} 只, 其中 ≥2 链同买 {multi} 只; slot {len(slots)} 个",
                f"- 权重前 3: " + "、".join(f"{s[2:]} {W['w'][s] * 100:.1f}%" for s in top)
                + f"; 最低 {min(W['w'].values()) * 100:.1f}%; 高权重集合 {len(W['high'])} 条",
                f"- Hedge 学习: 等权均值 {rec['eq_mean_pp']:+.2f}pp; 超额最大 " + max(rec["ex_pp"].items(), key=lambda kv: kv[1])[0][2:]
                + f" {max(rec['ex_pp'].values()):+.2f}pp / 最小 " + min(rec["ex_pp"].items(), key=lambda kv: kv[1])[0][2:] + f" {min(rec['ex_pp'].values()):+.2f}pp"]
        for src in MIX:
            nb = sum(1 for l in lines_day[src] if "| BUY |" in l)
            ns = sum(1 for l in lines_day[src] if "| SELL |" in l)
            rej = Counter(x["act"] for x in diag_day[src] if x["act"] != "出单")
            fl, vd, nav = res[src]
            rep.append(f"- **{src}**: BUY {nb} / SELL {ns} 单, 成交 {fl} 废 {vd}, EOD nav {nav:,.0f}" + (f"; 未出单原因 {dict(rej)}" if rej else ""))
            summary.append((d, src, nb, ns, fl, nav))
        rep.append("")
        for src in MIX:
            for l in lines_day[src]:
                all_lines.append(f"{d} {l}")
    rep += ["## 汇总", "", "| 日期 | 账本 | BUY | SELL | 成交 | EOD nav |", "|---|---|---|---|---|---|"]
    rep += [f"| {d} | {s} | {b} | {se} | {f} | {n:,.0f} |" for d, s, b, se, f, n in summary]
    tot = defaultdict(lambda: [0, 0, 0])
    for _, s, b, se, f, _n in summary:
        tot[s][0] += b
        tot[s][1] += se
        tot[s][2] += f
    rep += ["", "合计: " + "; ".join(f"{s} BUY {v[0]} / SELL {v[1]} / 成交 {v[2]}" for s, v in tot.items()), "",
            "## 全部生成的 plans 行", "", "```"] + all_lines + ["```", ""]
    final = state.s["days"][days[-1]]["learn"]["h_after"] if days else {}
    rep += ["## 回演末日 Hedge 乘子(h_after, 归一)", "", "| 链 | h |", "|---|---|"]
    rep += [f"| {s} | {v * 100:.2f}% |" for s, v in sorted(final.items(), key=lambda kv: -kv[1])]
    txt = "\n".join(rep) + "\n"
    print(txt)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(txt, encoding="utf-8")
        print(f"→ {out}")
    shutil.rmtree(tmpd, ignore_errors=True)


# ---------------- 自测 ----------------
def selftest():
    ok = []

    def chk(cond, msg):
        if not cond:
            raise AssertionError(msg)
        ok.append(msg)

    D = "2026-10-20"

    def book(src, nav=100000.0, orders=(), trades=(), positions=None, cash=100000.0, navs=None):
        return {"source": src, "cash": cash, "positions": positions or {}, "orders": list(orders), "trades": list(trades),
                "nav": navs if navs is not None else [{"date": "2026-10-19", "nav": nav}]}

    def od(src, i, code, side, price, qty, t="09:15", anchor=None, note="", cond=None, status="open"):
        return {"id": f"{D}-{src}-{i:03d}", "date": D, "time": t, "side": side, "code": code, "price": price, "qty": qty,
                "anchor": anchor or price, "note": note, "cond": cond or {}, "status": status}

    # 1) wmedian / 工具单 / CXL
    chk(wmedian([(10, 0.2), (11, 0.5), (12, 0.3)]) == 11, "加权中位数取权重过半的实际元素")
    chk(wmedian([(10, 0.6), (11, 0.4)]) == 10, "加权中位数偏向大权重")
    b = book("A-x", orders=[od("A-x", 1, "600001", "BUY", 10, 100, note="| CXL@10:00: 取代"), od("A-x", 2, "600002", "BUY", 10, 100, cond={"cancel_below": 11})])
    chk(views(b, D, "09:15", "BUY").keys() == {"600001"}, "工具单(BUY cancel_below≥挂价)不算看好")
    chk(views(b, D, "10:00", "BUY") == {}, "CXL@≤slot 的单不算看好")
    # 2) 投影: 保底/上限/簇上限
    ch = [f"A-c{i}" for i in range(10)] + CLUSTERS["两融高杠杆"]
    raw = {s: 1.0 for s in ch}
    for s in CLUSTERS["两融高杠杆"]:
        raw[s] = 20.0
    raw["A-c0"] = 0.0001
    caps = {s: 0.45 for s in ch}
    caps["A-c1"] = 0.08
    raw["A-c1"] = 50
    w = project(raw, caps)
    chk(abs(sum(w.values()) - 1) < 1e-8, "投影后权重和=1")
    chk(min(w.values()) >= P["floor"] - 1e-9, "每链保底 3%")
    chk(w["A-c1"] <= 0.08 + 1e-9, "单链动态上限生效")
    chk(sum(w[s] for s in CLUSTERS["两融高杠杆"]) <= 0.35 + 1e-9, "风格簇上限 35%")
    chk(all(v <= 0.35 + 1e-9 for v in w.values()), "单链也是一簇(≤35%)")
    # 3) compute_weights: 样本为零 → 等权附近; 拟人度减半
    inp = {"chains": ch, "regime": "普跌", "hits": {}, "ex": {}, "prior_pct": {}, "sim": {}, "vol": {s: None for s in ch}, "days": 0, "hedge": None}
    W0 = compute_weights(inp)
    chk(max(W0["w"].values()) - min(W0["w"].values()) < 1e-9, "零样本=严格等权")
    inp2 = dict(inp, sim={"A-c2": -0.1})
    W2 = compute_weights(inp2)
    chk(W2["w"]["A-c2"] < W2["w"]["A-c3"] * 0.6, "拟人度 delta≤0 减半")
    inp3 = dict(inp, hits={"A-c4": {"普跌": [20, 18]}}, days=20)
    W3 = compute_weights(inp3)
    chk(W3["w"]["A-c4"] == max(W3["w"].values()) and "A-c4" in W3["high"], "高命中率链权重最高且进高权重集合")
    chk(W3["caps"]["A-c4"] > W3["caps"]["A-c5"], "市况适配抬高单链上限")
    # 4) 准入/金额/上限(固定权重)
    chs = ["A-h", "A-l1", "A-l2", "A-l3"]
    Wf = {"w": {"A-h": 0.4, "A-l1": 0.2, "A-l2": 0.2, "A-l3": 0.2}, "eq": {s: 0.25 for s in chs},
          "caps": {s: 0.25 for s in chs}, "high": {"A-h"}}
    cb = {
        "A-h": book("A-h", orders=[od("A-h", 1, "600100", "BUY", 10.0, 2000), od("A-h", 2, "600300", "BUY", 5.0, 1000), od("A-h", 3, "113001", "BUY", 120.0, 100)]),
        "A-l1": book("A-l1", orders=[od("A-l1", 1, "600100", "BUY", 10.2, 1000), od("A-l1", 2, "600200", "BUY", 8.0, 1000), od("A-l1", 3, "113001", "BUY", 121.0, 100)]),
        "A-l2": book("A-l2", orders=[od("A-l2", 1, "600200", "BUY", 8.1, 1000)]),
        "A-l3": book("A-l3"),
    }
    mixb = book("A-mix")
    L, dg = plan_slot(D, "0915", cb, mixb, "main", Wf, {}, lambda c: None)
    got = {l.split("|")[3].strip(): l for l in L}
    chk("600100" in got and "600200" not in got and "600300" not in got, "主规则: 2链含高权重准入 / 2 低权重链不准入 / 单链不准入")
    # 600100 目标 = 0.4×20000/100000 + 0.2×10200/100000 = 0.08+0.0204=0.1004 → 10040 元, 挂价加权中位=10.0 → 1000 股
    chk(got["600100"].split("|")[5].strip() == "1000" and got["600100"].split("|")[4].strip() == "10", "金额=Σw·链挂单金额/链nav×混合nav, 100 股取整, 加权中位挂价")
    q113 = int(got["113001"].split("|")[5].strip())
    chk(q113 % 10 == 0 and q113 == 60, "转债按 10 张取整(7220 元/120=60 张)")
    Le, _ = plan_slot(D, "0915", cb, book("A-mix-eq"), "eq", Wf, {}, lambda c: None)
    ge = {l.split("|")[3].strip(): l for l in Le}
    chk("600200" in ge and "600300" not in ge, "等权本: 只要 ≥2 链即准入, 单链不准入")
    Ll, _ = plan_slot(D, "0915", cb, book("A-mix-lhb"), "lhb", Wf, {"600300": {"inst_bx": True, "lasa": False}, "600100": {"inst_bx": False, "lasa": True}}, lambda c: None)
    gl = {l.split("|")[3].strip(): l for l in Ll}
    chk("600300" in gl, "lhb: 1 高权重链+昨日机构/北向净买放行")
    chk(int(gl["600100"].split("|")[5]) == 500, "lhb: 昨日拉萨天团净买 目标×0.5")
    # 上限: 高权重链挂 60% nav
    cb2 = {"A-h": book("A-h", orders=[od("A-h", 1, "600500", "BUY", 10.0, 6000)]), "A-l1": book("A-l1", orders=[od("A-l1", 1, "600500", "BUY", 10.0, 6000)])}
    L2, _ = plan_slot(D, "0915", cb2, book("A-mix"), "main", Wf, {}, lambda c: None)
    chk(int(L2[0].split("|")[5]) == 2500, "单票上限=看好链动态上限加权(25%)")
    # 已持够不重复买; 本 slot 无新单不重出
    L3, _ = plan_slot(D, "0915", cb, book("A-mix", positions={"600100": {"qty": 1000, "cost": 10}}), "main", Wf, {}, lambda c: None)
    chk(not any("600100" in l for l in L3), "已持有目标量不重复买")
    L4, _ = plan_slot(D, "1000", cb, book("A-mix"), "main", Wf, {}, lambda c: None)
    chk(not L4, "本 slot 无看好链新单 → 不重复出单")
    # 现金不足缩量
    L5, _ = plan_slot(D, "0915", cb, book("A-mix", cash=5000.0), "main", Wf, {}, lambda c: None)
    chk(all(int(l.split("|")[5]) * float(l.split("|")[4]) <= 5000 for l in L5), "现金不足按可用现金缩量")
    # 5) 卖出 v1
    prev = "2026-10-19"
    tb = lambda src, code, q: {"id": f"{prev}-{src}-001", "side": "BUY", "code": code, "price": 10.0, "qty": q, "fee": 5}
    mixs = book("A-mix", positions={"600700": {"qty": 500, "cost": 10}}, trades=[tb("A-mix", "600700", 500)])
    cs = {"A-h": book("A-h", trades=[tb("A-h", "600700", 1000)], orders=[od("A-h", 1, "600700", "SELL", 10.5, 1000)]),
          "A-l1": book("A-l1", trades=[tb("A-l1", "600700", 1000)]), "A-l2": book("A-l2")}
    S1, _ = plan_slot(D, "0915", cs, mixs, "main", Wf, {}, lambda c: 9.9)
    chk(not any("SELL" in l for l in S1), "卖出: 仍有持有链没卖 → 不卖")
    cs["A-l1"]["orders"].append(od("A-l1", 1, "600700", "SELL", 10.8, 1000, t="10:00"))
    S2, _ = plan_slot(D, "1000", cs, mixs, "main", Wf, {}, lambda c: 9.9)
    sl = [l for l in S2 if "SELL" in l]
    chk(len(sl) == 1 and sl[0].split("|")[4].strip() == "10.5" and sl[0].split("|")[5].strip() == "500", "卖出: 持有链全部出卖单 → 全卖, 价=卖单加权中位")
    S3, _ = plan_slot(D, "0915", {"A-h": book("A-h")}, mixs, "main", Wf, {}, lambda c: 9.9)
    chk(any("| SELL | 600700 | 9.9 |" in l for l in S3), "卖出: 已无导师链持有 → 按昨收挂卖")
    mixt = book("A-mix", positions={"600700": {"qty": 500, "cost": 10}}, trades=[{**tb("A-mix", "600700", 500), "id": f"{D}-A-mix-001"}])
    S4, _ = plan_slot(D, "0915", {"A-h": book("A-h")}, mixt, "main", Wf, {}, lambda c: 9.9)
    chk(not S4, "卖出: T+1 当日买入不卖")
    # 6) 学习 + 状态 + 回滚
    hb = {s: 0.25 for s in chs}
    ha, ex, mean = learn_update(hb, {"A-h": 3.0, "A-l1": 0.0, "A-l2": -1.0, "A-l3": None}, {s: 0.45 for s in chs})
    chk(ha["A-h"] > 0.25 > ha["A-l2"] and abs(sum(ha.values()) - 1) < 1e-8, "Hedge: 超额为正的链权重上升, 为负的下降, 和=1")
    chk(ex["A-l3"] == 0.0 and abs(mean - 2 / 3) < 1e-9, "Hedge: 缺当日收益的链不动, 等权均值只算有数的")
    _, ex2, _ = learn_update(hb, {"A-h": 30.0, "A-l1": 0.0, "A-l2": 0.0, "A-l3": 0.0}, {s: 0.45 for s in chs})
    chk(ex2["A-h"] == P["ex_clip"], "Hedge: 单日超额裁到 ±5pp")
    tmp = Path(tempfile.mkdtemp(prefix="mix_selftest_"))
    try:
        st = State(tmp / "mix_state.json")
        st.put("2026-10-19", "learn", {"h_after": ha})
        st.put("2026-10-20", "learn", {"h_after": hb})
        st.save()
        st2 = State(tmp / "mix_state.json")
        h, frm = st2.hedge_before("2026-10-20", chs)
        chk(frm == "2026-10-19" and abs(h["A-h"] - ha["A-h"]) < 1e-9, "状态: D 日用 <D 最近一条学习结果")
        gone = st2.rollback("2026-10-20")
        st2.save()
        chk(gone == ["2026-10-20"] and list(State(tmp / "mix_state.json").s["days"]) == ["2026-10-19"] and list(tmp.glob("mix_state.bak-*.json")),
            "回滚: 删 ≥D 记录并先备份")
        # plans 落盘幂等(同 slot 替换) + 行格式过 matcher LINE 正则
        f = write_plans(D, "0915", "A-mix-eq", Le, plans_dir=tmp)
        write_plans(D, "0915", "A-mix-eq", Le, plans_dir=tmp)
        write_plans(D, "1000", "A-mix-eq", ["- 10:00 | A-mix-eq | CXL | 600200 | - | - | - | - | t"], plans_dir=tmp)
        rows = [l for l in f.read_text(encoding="utf-8").splitlines() if l.startswith("-")]
        chk(len(rows) == len(Le) + 1, "plans 同 slot 重写=替换不重复")
        mt = (HERE / "matcher.mjs").read_text(encoding="utf-8")
        js = re.search(r"^const LINE = /(.*)/;\s*$", mt, re.M).group(1)
        r = subprocess.run(["node", "-e", f"const re=/{js}/;const ls=require('fs').readFileSync(process.argv[1],'utf8').split('\\n').map(l=>l.trim()).filter(l=>l.startsWith('-'));"
                            "const bad=ls.filter(l=>!re.test(l)||!/^A-mix/.test(l.match(re)[2]));console.log(bad.length);", str(f)],
                           capture_output=True, text=True, creationflags=NOWIN)
        chk(r.stdout.strip() == "0", "生成的 plans 行全部通过 matcher LINE 正则(含 A-mix-eq 连字符源名)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # 10/16 晚 相关性分簇: 合成收益(a≈b 高相关, c 独立, d 与 a 弱相关) → 只有 a+b 归一簇; 无数据=各自一簇
    import random
    rnd = random.Random(7)
    days = [f"2026{m:02d}{x:02d}" for m in (6, 7, 8) for x in range(1, 29)]
    base = {k: rnd.gauss(0, 1) for k in days}
    syn = {"A-sa": {k: base[k] + rnd.gauss(0, 0.3) for k in days}, "A-sb": {k: base[k] + rnd.gauss(0, 0.3) for k in days},
           "A-sc": {k: rnd.gauss(0, 1) for k in days}, "A-sd": {k: 0.3 * base[k] + rnd.gauss(0, 1) for k in days}, "A-se": None}
    _rr, _dr = globals()["real_returns"], globals()["daily_returns"]
    try:
        globals()["real_returns"] = lambda s, d, w: syn.get(s)
        globals()["daily_returns"] = lambda b, upto=None, incl=False: {}
        cl, _ = corr_clusters("2026-10-20", list(syn), {s: {} for s in syn})
        chk(list(cl.values()) == [["A-sa", "A-sb"]], f"相关性分簇: 高相关归一簇, 弱相关/独立/无数据各自一簇({cl})")
    finally:
        globals()["real_returns"], globals()["daily_returns"] = _rr, _dr
    ok = [m for m in ok if m]
    print(f"MIX SELFTEST PASS ({len(ok)} 项):")
    for m in ok:
        print("  ✓ " + m)


def main():
    ap = argparse.ArgumentParser(description="paper 混合 skill 跟跑账本")
    ap.add_argument("--date")
    ap.add_argument("--slot")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--learn", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--weights", action="store_true")
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dryrun", nargs=2, metavar=("D0", "D1"))
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.init:
        print("建账:", init_books() or "三本均已存在")
        return 0
    if a.dryrun:
        return dryrun(a.dryrun[0], a.dryrun[1], a.out)
    if not a.date:
        ap.error("需 --date")
    if a.weights:
        return print_weights(a.date)
    if a.rollback:
        st = State(DATA / "mix_state.json")
        print("回滚删除:", st.rollback(a.date))
        st.save()
        return 0
    if a.learn:
        chains = [s for s, _ in mentor_chains()]
        books = load_books(chains + ["A-control"])
        st = State(DATA / "mix_state.json")
        rec = do_learn(a.date, books, chains, st)
        print(json.dumps(rec, ensure_ascii=False, indent=1))
        if rec["missing"]:
            print(f"WARN 当日缺 nav 的链(未更新): {rec['missing']}——EOD 未跑完? 补跑后重跑 --learn 即覆盖当日记录")
        if not a.dry:
            st.save()
        return 0
    if not a.slot:
        ap.error("出单需 --slot HHMM")
    return run_slot(a.date, a.slot, a.dry)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main() or 0)
