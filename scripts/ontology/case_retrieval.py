# -*- coding: utf-8 -*-
"""ontology/case_retrieval.py — 相似案例检索原型(10/25 晚用户批设计; 只做原型 + 验证, 不接实盘; 零 token, 只读业务库, 产物写 downloads/ontology/case_vec/)

回答: "导师在类似情境下怎么做的" —— 给焦点票 / 建·加的票附: 情境格子的整体分布 → 正样本最像 1~2 个 + 负样本最像 1 个(附原文 + 为什么算像)
案例单位 = 决策点: 同导师同日同票同方向, 相隔 >15 分钟算新的一次(10/26: 原来按"日"合并, 当天加仓 / 越跌越买找不到对应案例)
四层:
  ① 硬条件过滤(格子): 品种(股票 / 转债 / 妖债) · 方向 —— 永不放宽; 昨日状态(涨停 / 炸板·收涨 / 炸板·收跌 / 跌停 / 大涨 / 大跌 / 平) · 动作类(act_of, 决策时可知)
     · 价位档(成交价较昨收) · 开盘区间 · 持仓状态(按决策价算浮盈, 含当天更早的腿) · 连板高度 · 正股开盘区间(转债) · 箱体位置 · 市况 · 总仓位
     格子 n(导师×日×票) < 15 自动放宽: 按 RELAX 步骤先去掉最弱的, 再"并邻档", 最后才去掉; 附件写"已放宽 k 步: …"
  ② 拓扑加分: 同票 · 同题材 · 梯队位置(龙头 / 跟风 / 补涨…) · 同席位(昨日龙虎榜同一营业部) · 同导师(全部只用 D 前一交易日及以前的本体事件)
  ③ 语义排序: bge-m3(本地 ollama 127.0.0.1:11434/api/embed, keep_alive), 查询"一句话" vs 案例文字(情境 + 日卡成交 / 竞价 / 解读 + md 推测, 不含结果)
  ④ 正负标签(用户 10/25 口径, 截至查询日 D 重算): 买 = T+1~T+3 任一天最高 ≥ 买价×(1+X%) 正 / 3 天都没冲到且 T+3 收 < 买价 负 / 其余平;
     卖(本脚本提议, 置信低) = T+1~T+3 任一天收盘 ≥ 卖价×(1+X%) 负(卖飞) / 3 天收盘都没到且 T+3 收 ≤ 卖价 正(卖对) / 其余平
     负样本只当"如果错了"的教训, 不当依据; 负样本账户(洋大人 / 猎人IH / 护卫港 / 买入太急 / 鳄狼King)不进"正样本最像"
  默认权重 DEF_W = 结构 0.7 / 拓扑 0.2 / 语义 0.1(10/26 验证, 见 docs/research/retrieval_eval_20261026.md)
防偷看(查询日 D): 案例只取 d < D; 标签只用 D 之前的行情重算; "之后怎么卖"只显示 D 之前的; 日卡解读只在案例次日 < D 时显示,
  否则语义也改用不含解读的基础向量(cases_emb_base.npy); 原文库只取已知日 < D(cases.md 条目已知日 = 条目里提到的最晚日期);
  查询情境: 昨日及以前的日线 + D 的开盘价(09:25 已知) + 成交价; D 的最高 / 最低 / 收盘读行情时就截掉
用法:
  python case_retrieval.py build [--since 2025-09-01] [--no-embed]   每晚建索引(读 ontology.db / samples.jsonl → 放在 04:00 重算之后; 增量约 2 分钟, 首次全量 embed 约 17 分钟; 用 GPU 前建 scripts/PAUSE)
  python case_retrieval.py query --code 002368 --date 2026-10-23 [--side 买] [--px 14.08] [--t 09:25]
         [--ctx '{"hold_pnl": -10.8, "pos_total": 46}'] [--text "竞价低开 8% 低吸降成本"] [--skill zhiyingjuexin] [--w 0.7,0.2,0.1] [--json]
  ctx 可填(都可省, 省了自动从行情算): asset 品种 / prev 昨日状态 / h 连板高度 / gap 开盘% / px_pct 成交价较昨收% / box 箱体位置 / mkt 市况 / hold 持仓状态 /
      hold_pnl 该票浮盈%(按决策价) / pos_total 总仓位% / theme 题材 / tier 梯队位置 / stk_gap 正股开盘%(转债用) / act 动作类 /
      addon 当天加仓位置, 或 first_buy_px 当天首笔买价 + n_buys_before 当天已买几次
  进程内用: q = query_situation(code, D, side, px, t, ctx); q["skill"] = 导师; R = retrieve(q, text); print(render(R, text))
"""
import argparse
import bisect
import collections
import datetime as dt
import hashlib
import json
import pickle
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "tzzb"), str(ROOT / "scripts" / "paper_line" / "tools"),
                str(ROOT / "scripts" / "lib"), str(ROOT / "scripts" / "ontology")]
OUTD = ROOT / "downloads" / "ontology" / "case_vec"
ONTO = ROOT / "downloads" / "ontology" / "ontology.db"
SAMPLES = ROOT / "downloads" / "ontology" / "samples.jsonl"
OLLAMA = "http://127.0.0.1:11434/api/embed"   # 不写 localhost: Windows 先试 IPv6 ::1 失败再回落, 每次白等约 2 秒
MODEL = "bge-m3"
KEEP = "30m"
NEG_ACCTS = {"yangdaren", "liurenih", "huweigang", "mairutaiji", "elangking"}
UP_NAMES = {"桃哥": "taoge", "趋势天哥": "qushitiange", "卢本圆": "lubenyuan"}   # 小节名包含即算(股市 - 桃哥复盘 / 卢本圆复盘)
DEF_W = (0.7, 0.2, 0.1)   # 10/26 验证: 结构为主(严判像 49% vs 0.5/0.3/0.2 的 44%, 成簇配对差 +1~+8 点); 只语义最差
MIN_N = 15
# 硬条件(重要 → 不重要); 放宽从列表尾部开始逐个去掉
CONDS = ["prev", "act", "pxb", "gapb", "hold", "h", "stk_gapb", "box", "mkt", "posb"]
CN = {"asset": "品种", "side": "方向", "act": "动作类", "addon": "当天加仓位置", "prev": "昨日状态", "pxb": "价位档", "gapb": "开盘区间", "hold": "持仓状态", "h": "连板高度", "stk_gapb": "正股开盘区间",
      "box": "箱体位置", "mkt": "市况", "posb": "总仓位"}
SW = {"prev": .18, "act": .12, "pxb": .14, "gapb": .14, "hold": .13, "h": .08, "stk_gapb": .06, "box": .06, "mkt": .05, "posb": .04, "addon": .08}   # 结构分权重(和 = 1)
ORD = {"gapb": ["跌停开", "≤−7", "−7~−3", "−3~−1", "−1~+1", "+1~+3", "+3~+7", "≥+7", "涨停开"],
       "pxb": ["跌停价", "≤−5", "−5~−1", "−1~+1", "+1~+5", "≥+5", "涨停价"],
       "box": ["已离箱向下", "越下沿", "下沿", "中部", "上沿", "越上沿", "已离箱向上"],
       "hold": ["被套>5%", "被套0~5%", "浮盈0~5%", "浮盈>5%"],
       "posb": ["空仓", "<3成", "3~7成", "≥7成"], "h": ["0", "1", "2", "3+"], "addon": ["加仓·更低", "加仓·持平", "加仓·更高"]}
ORD["stk_gapb"] = ORD["gapb"]


def log(*a):
    print(f"[{dt.datetime.now():%H:%M:%S}]", *a, flush=True)


def cur():
    import manual_backfill as mb
    c = mb.db().cursor()
    try:
        c.execute("set session transaction read only")
    except Exception:   # noqa: BLE001
        pass
    return c


# ---------------------------------------------------------------- 分档 ----------------------------------------------------------------
def gap_b(g, lim):
    if g is None:
        return None
    L = lim * 100
    if g >= L - 0.15:
        return "涨停开"
    if g <= -L + 0.15:
        return "跌停开"
    return "≤−7" if g <= -7 else "−7~−3" if g <= -3 else "−3~−1" if g <= -1 else "−1~+1" if g < 1 else "+1~+3" if g < 3 else "+3~+7" if g < 7 else "≥+7"


def px_b(p, lim):
    if p is None:
        return None
    L = lim * 100
    if p >= L - 0.15:
        return "涨停价"
    if p <= -L + 0.15:
        return "跌停价"
    return "≤−5" if p <= -5 else "−5~−1" if p <= -1 else "−1~+1" if p < 1 else "+1~+5" if p < 5 else "≥+5"


def hold_b(qty, pnl):
    if not qty:
        return "未持有"
    if pnl is None:
        return "持有(盈亏未知)"
    return "被套>5%" if pnl < -5 else "被套0~5%" if pnl < 0 else "浮盈0~5%" if pnl < 5 else "浮盈>5%"


def pos_b(p):
    if p is None:
        return None
    return "空仓" if p < 3 else "<3成" if p < 30 else "3~7成" if p < 70 else "≥7成"


def regime(idx_pct, ztn):
    a = "强" if idx_pct > 0.5 else "弱" if idx_pct < -0.5 else "平"
    b = "冷" if ztn < 50 else "热" if ztn >= 100 else "中"
    return f"{a}·{b}"


def lim_of(code, name=""):
    if code.startswith(("11", "12")):
        return 0.20
    if "ST" in (name or "").upper():
        return 0.05
    return 0.20 if code.startswith(("300", "301", "688", "689")) else 0.10


def zt(pc, lim):
    return round(pc * (1 + lim) + 1e-9, 2)


def dtp(pc, lim):
    return round(pc * (1 - lim) + 1e-9, 2)


def sym(code):
    return ("sh" if code.startswith(("6", "9", "11", "5")) else "sz") + code


def asset_of(code, pc=None, X=None):
    if code.startswith(("11", "12")):
        return "妖债" if (pc and pc >= 200) or (X and X >= 6) else "转债"
    return "股票"


# ---------------------------------------------------------------- 情境特征(建库和查询共用一份, 保证同口径) ----------------------------------------------------------------
def feats(code, name, K, i, px, mk, topo, stkK=None, stk_i=None, stk_lim=0.10):
    """K = [(日, 开, 高, 低, 收, 昨收)], i = D 在 K 里的下标(D 那行只用开盘价; i == len(K) 表示 D 还没有日线);
    px = 成交价(None → 用开盘价 / 昨收); mk = {日: (上证%, 涨停家数)}; topo = 拓扑表; 只用 D 之前 + D 开盘"""
    import sample_lib as SL
    lim = lim_of(code, name)
    prev = K[i - 1]
    pc = prev[4]
    hasD = i < len(K)
    op = K[i][1] if hasD else None
    if px is None:
        px = op or pc
    amp = [(K[j][2] - K[j][3]) / K[j][5] * 100 for j in range(max(0, i - 30), i) if K[j][5]]
    X = round(sorted(amp)[len(amp) // 2], 2) if amp else 5.0
    # 昨日状态 + 连板高度
    p0 = prev[5]
    st = "平"
    if p0:
        pct = (prev[4] / p0 - 1) * 100
        if prev[4] >= zt(p0, lim) - 0.005 and not code.startswith(("11", "12")):
            st = "涨停"
        elif prev[2] >= zt(p0, lim) - 0.005 and not code.startswith(("11", "12")):
            st = "炸板·收涨" if pct >= 0 else "炸板·收跌"   # 10/26 拆: 炸板收红 vs 天地板式收绿(百洋股份 10-22 −6.75%)是两种处境
        elif prev[4] <= dtp(p0, lim) + 0.005 and not code.startswith(("11", "12")):
            st = "跌停"
        elif pct >= 5:
            st = "大涨"
        elif pct <= -5:
            st = "大跌"
    h = 0
    if not code.startswith(("11", "12")):
        for j in range(i - 1, max(-1, i - 15), -1):
            if K[j][5] and K[j][4] >= zt(K[j][5], lim) - 0.005:
                h += 1
            else:
                break
    gap = round((op / pc - 1) * 100, 2) if op and pc else None
    pxp = round((px / pc - 1) * 100, 2) if pc else None
    A = np.array([k[1:5] for k in K[max(0, i - 160):i]])
    try:
        box, bpos = SL.box_pos(A[:, 0], A[:, 1], A[:, 2], A[:, 3], px) if len(A) else ("无箱体", None)
    except Exception:   # noqa: BLE001
        box, bpos = "无箱体", None
    D = K[i][0] if hasD else None
    pdD = prev[0]
    ip, zn = mk.get(pdD, (None, None))
    f = {"asset": asset_of(code, pc, X), "lim": lim, "X": X, "pc": pc, "px": round(px, 3), "prev": st, "prev_pct": round((prev[4] / p0 - 1) * 100, 2) if p0 else None,
         "h": "3+" if h >= 3 else str(h), "gap": gap, "gapb": gap_b(gap, lim), "px_pct": pxp, "pxb": px_b(pxp, lim), "box": box, "box_pos": bpos,
         "mkt": regime(ip, zn) if ip is not None else None, "ret5": round((pc / K[i - 6][4] - 1) * 100, 1) if i >= 6 and K[i - 6][4] else None}
    if stkK is not None and stk_i is not None and 0 < stk_i <= len(stkK):
        spc = stkK[stk_i - 1][4]
        sop = stkK[stk_i][1] if stk_i < len(stkK) else None
        f["stk_gap"] = round((sop / spc - 1) * 100, 2) if sop and spc else None
        f["stk_gapb"] = gap_b(f["stk_gap"], stk_lim)
        sp0 = stkK[stk_i - 1][5]
        f["stk_prev_pct"] = round((spc / sp0 - 1) * 100, 2) if sp0 else None
    tp = topo_at(topo, code, pdD) if topo else {}
    f.update(tp)
    return f


def topo_at(topo, code, pdD):
    """D 前一交易日及以前的题材 / 梯队 / 席位(防偷看: 只用 ≤ 昨日收盘已知的)"""
    out = {}
    th = topo["theme"].get(code) or []
    ds = [x[0] for x in th]
    j = bisect.bisect_right(ds, pdD) - 1
    if j >= 0 and (dt.date.fromisoformat(pdD) - dt.date.fromisoformat(th[j][0])).days <= 30:
        out["theme"], out["tier"], out["stage"], out["theme_d"] = th[j][1], th[j][2], th[j][3], th[j][0]
    se = topo["seat"].get(code) or {}
    if pdD in se:
        out["seats"] = se[pdD]
    return out


def act_of(f, side, t):
    """决策时可知的动作类(10/26 加): 只用 成交价 vs 开盘 / 昨收、时刻、持仓浮盈; 不用当天之后的走势
    买: 竞价(≤09:25) / 打板(涨停价) / 追涨(较开盘 ≥+2 点 或 较昨收 ≥+5%) / 低吸(较开盘 ≤−2 点) / 平价
    卖: 日内T(当天先买后卖) / 止损(浮盈 <−1%) / 冲高止盈(浮盈 ≥3% 且较开盘 ≥+1 点) / 止盈(浮盈 ≥1%) / 平走"""
    vo = (f["px_pct"] - f["gap"]) if f.get("px_pct") is not None and f.get("gap") is not None else None
    if side == "买":
        if (t or "")[:5] and (t or "")[:5] <= "09:25":
            return "竞价"
        if f.get("pxb") == "涨停价":
            return "打板"
        if (vo is not None and vo >= 2) or (f.get("px_pct") or 0) >= 5:
            return "追涨"
        if vo is not None and vo <= -2:
            return "低吸"
        return "平价"
    if f.get("hold") == "当天先买后卖(T)":
        return "日内T"
    hp = f.get("hold_pnl")
    if hp is None:
        return "平走"
    if hp < -1:
        return "止损"
    if hp >= 3 and vo is not None and vo >= 1:
        return "冲高止盈"
    return "止盈" if hp >= 1 else "平走"


def addon_b(px, first_px, n_before):
    """当天加仓位置(决策时可知): 首笔 / 加仓·更低(较当天首笔 ≤−1%) / 加仓·更高(≥+1%) / 加仓·持平"""
    if not n_before or not first_px:
        return "首笔"
    r = (px / first_px - 1) * 100
    return "加仓·更低" if r <= -1 else "加仓·更高" if r >= 1 else "加仓·持平"


def addon_pass(cases):
    """买的决策点: 同导师同日同票更早的买决策点 → 当天第几笔 + 较首笔的位置(K2 "越跌越买" 要这个; 10/26 加)"""
    by = collections.defaultdict(list)
    for cs in cases:
        if cs["side"] == "买":
            by[cs.get("day_key", cs["id"])].append(cs)
    for v in by.values():
        v.sort(key=lambda x: x["t"])
        first = v[0]["legs"][0][1] if v[0].get("legs") else v[0]["px"]
        for j, cs in enumerate(v):
            px = cs["legs"][0][1] if cs.get("legs") else cs["px"]
            cs["f"]["addon"] = addon_b(px, first, j)
            cs["f"]["addon_pct"] = round((px / first - 1) * 100, 2) if j else None
    for cs in cases:
        cs["f"].setdefault("addon", None)


def tier_cn(pos):
    return {"题材内最高": "龙头", "补涨": "补涨", "首板": "首板", "大涨": "大涨跟随", "跟风": "跟风"}.get(pos or "", pos)


# ---------------------------------------------------------------- 标签(截至 D) ----------------------------------------------------------------
def label_asof(c, D):
    """→ (标签, {指标}); c["path"] = [(日, 最高%, 收盘%)] T+1..T+3(相对成交价)"""
    P = [p for p in c.get("path", []) if p[0] < D]
    X = c["X"]
    m = {}
    if P:
        m["hmax"] = max(p[1] for p in P)
        m["c1"] = P[0][2]
        m["cmax"] = max(p[2] for p in P)
    if len(P) >= 3:
        m["c3"] = P[2][2]
    if c["side"] == "买":
        if any(p[1] >= X for p in P):
            return "正", m
        if len(P) < 3:
            return f"待核{3 - len(P)}", m
        return ("负" if P[2][2] < 0 else "平"), m
    if any(p[2] >= X for p in P):
        return "负", m
    if len(P) < 3:
        return f"待核{3 - len(P)}", m
    return ("正" if P[2][2] <= 0 else "平"), m


# ---------------------------------------------------------------- 文字库解析 ----------------------------------------------------------------
DATE_RE = re.compile(r"(20\d\d)-(\d\d)-(\d\d)")
MD_RE = re.compile(r"(?<![\d-])(\d{1,2})-(\d{2})(?![\d-])")


def max_date(text, base):
    """文字里提到的最晚日期(全日期 + "10-15" 这种月-日, 年取 base 的年; 跨年回退)"""
    ds = [base]
    for y, m, d in DATE_RE.findall(text):
        try:
            ds.append(dt.date(int(y), int(m), int(d)).isoformat())
        except ValueError:
            pass
    by = int(base[:4])
    for m, d in MD_RE.findall(text):
        try:
            x = dt.date(by, int(m), int(d))
        except ValueError:
            continue
        if x.isoformat() < base and (dt.date.fromisoformat(base) - x).days > 200:
            x = dt.date(by + 1, int(m), int(d))
        if (x - dt.date.fromisoformat(base)).days <= 120:
            ds.append(x.isoformat())
    return max(ds)


def parse_cards(skill):
    """case_log 日卡 → {日: {"pos_total", "holds": {名: (仓位%, 浮%, 持天)}, "auction": {名: 文}, "trades": [行], "result": 文, "interp": 文, "tags"}}"""
    out = {}
    for f in sorted((ROOT / "skills" / f"{skill}-skill" / "persona" / "case_log").glob("20*.md")):
        txt = f.read_text(encoding="utf-8", errors="replace")
        for blk in re.split(r"^### ", txt, flags=re.M)[1:]:
            m = re.match(r"(\d{4}-\d{2}-\d{2})\S*\s*\S*\s*\|?\s*(.*)", blk)
            if not m:
                continue
            d = m.group(1)
            card = {"tags": m.group(2).strip(), "holds": {}, "auction": {}, "trades": [], "result": "", "interp": "", "pos_total": None, "mkt": ""}
            sec = None
            for line in blk.splitlines()[1:]:
                s = line.strip()
                if sec == "tr" and line.startswith(("  -", "	-")):
                    card["trades"].append(s[1:].strip())
                    continue
                if s.startswith("- 大盘:"):
                    card["mkt"] = s[5:].strip()
                elif s.startswith("- 昨收持仓"):
                    mm = re.search(r"合计\s*(\d+)%", s)
                    card["pos_total"] = float(mm.group(1)) if mm else (0.0 if "空仓" in s else None)
                    for nm, pct, fl, days in re.findall(r"([^\s:;：]+?)\s+(\d+)%\(浮([+\-]?\d+\.?\d*)%(?:, 持(\d+)天)?", s):
                        card["holds"][nm] = (float(pct), float(fl), int(days) if days else None)
                elif s.startswith("- 竞价"):
                    for part in s.split(":", 1)[-1].split(" | "):
                        nm = part.strip().split(" ")[0]
                        card["auction"][nm] = part.strip()
                elif s.startswith("- 成交"):
                    sec = "tr"
                elif s.startswith("- 结果"):
                    card["result"] = s[2:]
                    sec = None
                elif s.startswith("- 解读"):
                    card["interp"] = s[2:]
                    sec = None
                elif s.startswith("- "):
                    sec = None
            out[d] = card
    return out


def md_files():
    fs = []
    for f in sorted(ROOT.glob("md/20*S*/*.md")):
        if re.match(r"\d{4}-\d{2}-\d{2}$", f.stem):
            fs.append(f)
    return fs


def section(txt, head, level=3):
    h = "#" * level
    m = re.search(rf"^{h} {re.escape(head)}\s*$(.*?)(?=^#{{1,{level}}} |\Z)", txt, re.S | re.M)
    return m.group(1) if m else ""


def subblocks(sec, level=4):
    h = "#" * level
    parts = re.split(rf"^{h} ", sec, flags=re.M)
    out = []
    for p in parts[1:]:
        nm, _, body = p.partition("\n")
        out.append((nm.strip(), body.strip()))
    return out


def chunks(text, n=700):
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, buf = [], ""
    for p in paras:
        if len(p) > n * 1.6:
            for k in range(0, len(p), n):
                out.append(p[k:k + n])
            continue
        if len(buf) + len(p) > n and buf:
            out.append(buf)
            buf = ""
        buf = (buf + "\n" + p).strip()
    if buf:
        out.append(buf)
    return out


def nkey(s):
    return re.sub(r"[\s\\*]", "", s or "")


# ---------------------------------------------------------------- 向量 ----------------------------------------------------------------
def embed(texts, batch=64):
    out = []
    for k in range(0, len(texts), batch):
        body = json.dumps({"model": MODEL, "input": [t[:1000] for t in texts[k:k + batch]], "keep_alive": KEEP}).encode()
        for attempt in range(3):
            try:
                r = urllib.request.urlopen(urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"}), timeout=300)
                E = json.loads(r.read())["embeddings"]
                break
            except Exception as e:   # noqa: BLE001
                if attempt == 2:
                    raise RuntimeError(f"bge-m3 embed 失败(ollama 没起 / 模型没拉?): {e!r}")
                time.sleep(3)
        out.extend(E)
        if len(texts) > 200 and (k // batch) % 50 == 0:
            log(f"  embed {k + len(E)}/{len(texts)}")
    a = np.array(out, dtype=np.float32)
    a /= np.linalg.norm(a, axis=1, keepdims=True) + 1e-9
    return a


def embed_cached(texts):
    """按文字 sha1 增量: 文字没变就复用上次的向量(每晚重建只 embed 新增的)"""
    cf = OUTD / "emb_cache.pkl"
    cache = pickle.loads(cf.read_bytes()) if cf.exists() else {}
    keys = [hashlib.sha1(t.encode("utf-8")).hexdigest() for t in texts]
    miss = sorted({k for k in keys if k not in cache})
    if miss:
        idx = {k: t for k, t in zip(keys, texts)}
        log(f"embed 新增 {len(miss)} 段(复用 {len(set(keys)) - len(miss)})")
        V = embed([idx[k] for k in miss])
        for k, v in zip(miss, V):
            cache[k] = v.astype(np.float16)
    keep = {k: cache[k] for k in set(keys)}
    cf.write_bytes(pickle.dumps(keep))
    return np.stack([keep[k].astype(np.float32) for k in keys]) if keys else np.zeros((0, 1024), np.float32)


# ---------------------------------------------------------------- 建库 ----------------------------------------------------------------
def load_topo():
    """事件本体(只读): 题材(code → [(日, 题材, 梯队位置, 阶段)]) + 席位(code → {日: [(营业部, 别名, 风格)]})"""
    con = sqlite3.connect(f"file:{ONTO}?mode=ro", uri=True)
    th = collections.defaultdict(list)
    for code, d, tags in con.execute("select code, d, tags from event where kind='theme' order by d"):
        t = json.loads(tags)
        th[code].append((d, t.get("theme"), t.get("pos"), t.get("stage")))
    se = collections.defaultdict(lambda: collections.defaultdict(list))
    for code, d, tags in con.execute("select code, d, tags from event where kind='seat'"):
        t = json.loads(tags)
        se[code][d].append((t.get("dept"), t.get("alias"), t.get("style")))
    con.close()
    # 同一天多个题材: 取第一个(和 sample_lib 口径一致: 涨停分析里先出现的)
    th2 = {}
    for code, v in th.items():
        seen, out = set(), []
        for x in v:
            if x[0] not in seen:
                seen.add(x[0])
                out.append(x)
        th2[code] = out
    return {"theme": th2, "seat": {k: dict(v) for k, v in se.items()}}


def market_map(c, d0):
    import sample_lib as SL
    return SL.market_days(d0)


def load_kline(c, codes, d0):
    K = {}
    syms = sorted({sym(x) for x in codes})
    for k in range(0, len(syms), 400):
        part = syms[k:k + 400]
        c.execute("select symbol, trade_date, open, high, low, close, pre_close from investment_market.kline_day where is_deleted=0 and trade_date>=%s and symbol in (" +
                  ",".join(["%s"] * len(part)) + ") order by symbol, trade_date", (d0, *part))
        for s, d, o, h, l_, cl, pc in c.fetchall():
            if o and cl and pc:
                K.setdefault(s[2:], []).append((str(d), float(o), float(h), float(l_), float(cl), float(pc)))
    return K


_CBM = {}


def cb_map():
    if "m" in _CBM:
        return _CBM["m"]
    sys.path.insert(0, str(ROOT / "scripts" / "market"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("_sd", ROOT / "scripts" / "market" / "similar_days.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    _CBM["m"] = m.cb_map()
    return _CBM["m"]


def names_map():
    reg = {}
    for e in json.loads((ROOT / "scripts" / "tzzb" / "tzzb_ledgers.json").read_text(encoding="utf-8")):
        reg[e["ledger"]] = {"name": e.get("name") or e["ledger"], "display": e.get("display") or e.get("name") or e["ledger"], "neg": e.get("kind") == "neg"}
    return reg


def _sec(t):
    h, m, s_ = map(int, str(t)[:8].split(":"))
    return h * 3600 + m * 60 + s_


def decision_points(L, gap_s=900):
    """一个导师一只票的逐笔腿 [(日, 时, 买?, 价, 量, 名)] → 决策点(同日同方向相隔 ≤ gap_s 的腿并成一次)
    每个决策点带: 昨收持股 q_yday / 成本 c_yday(均价法回放) + 决策前一刻的持股 q_before / 成本 c_before(含当天更早的腿) + 当天第几次 k"""
    out = []
    qty, cost = 0.0, 0.0
    days = collections.OrderedDict()
    for x in L:
        days.setdefault(x[0], []).append(x)
    for d, xs in days.items():
        groups = []
        for side in (True, False):
            for x in [x for x in xs if x[2] == side]:
                g = next((g for g in groups[::-1] if g["buy"] == side), None)
                if g and _sec(x[1]) - _sec(g["legs"][-1][1]) <= gap_s:
                    g["legs"].append(x)
                else:
                    groups.append({"buy": side, "legs": [x]})
        groups.sort(key=lambda g: g["legs"][0][1])
        for k, g in enumerate(groups):
            rq, rc = qty, cost
            for x in xs:
                if (x[1], not x[2]) >= (g["legs"][0][1], not g["buy"]):
                    break
                if x[2]:
                    rc += x[3] * x[4]
                    rq += x[4]
                else:
                    if rq > 0:
                        rc *= max(0.0, 1 - x[4] / rq)
                    rq = max(0.0, rq - x[4])
            ys = g["legs"]
            v = sum(y[3] * y[4] for y in ys)
            q = sum(y[4] for y in ys)
            out.append({"d": d, "name": ys[0][5], "side": "买" if g["buy"] else "卖", "t": ys[0][1][:8], "px_avg": round(v / q, 4), "px_first": ys[0][3], "qty": q,
                        "n_legs": len(ys), "legs": [(y[1][:8], y[3], y[4]) for y in ys][:30], "q_yday": qty, "c_yday": cost, "q_before": rq, "c_before": rc, "k": k,
                        "day_had_buy_before": any(x[2] and x[1] < ys[0][1] for x in xs)})
        for x in xs:   # 盘后更新持仓(均价法; 卖超出记录持仓 → 清零)
            if x[2]:
                cost += x[3] * x[4]
                qty += x[4]
            else:
                if qty > 0:
                    cost *= max(0.0, 1 - x[4] / qty)
                qty = max(0.0, qty - x[4])
                if qty == 0:
                    cost = 0.0
    return out


def hold_state(e, card, pc, px):
    """决策那一刻的持仓状态 + 浮盈(按决策价算: 现价 / 持仓均价 − 1); 昨收持仓优先用日卡(账本起点前建的仓逐笔回放算不出成本)
    → (持仓档, 浮盈%, 昨收总仓位%)"""
    nm = nkey(e["name"])
    hh = None
    if card:
        hh = card["holds"].get(nm) or next((v for k, v in card["holds"].items() if nkey(k)[:3] == nm[:3]), None)
    pos_total = card["pos_total"] if card else None
    yq, yc = e["q_yday"], e["c_yday"]
    if hh and hh[1] is not None and pc:
        cps = pc / (1 + hh[1] / 100)   # 日卡昨收浮盈 → 每股成本
        yq = yq if yq > 0 else 1.0
        yc = cps * yq
    elif card and card["pos_total"] is not None and not hh:
        yq, yc = 0.0, 0.0   # 日卡说昨收没有这只
    tq = e["q_before"] - e["q_yday"]   # 当天这一刻之前的净变动
    tc = e["c_before"] - e["c_yday"]
    q, c = yq + tq, yc + tc
    if q > 1e-9 and c > 0:
        pnl = round((px / (c / q) - 1) * 100, 2)
        return hold_b(1, pnl), pnl, pos_total
    if e["side"] == "卖":
        return ("当天先买后卖(T)" if e.get("day_had_buy_before") else "持有(账本起点前建仓)"), None, pos_total
    return "未持有", None, pos_total


def build(since="2025-09-01", do_embed=True):
    t0 = time.time()
    OUTD.mkdir(parents=True, exist_ok=True)
    c = cur()
    reg = names_map()
    md2skill = {nkey(v["name"]): k for k, v in reg.items()}
    # 1) 逐笔腿 → 交易事件(导师 × 日 × 票 × 方向)
    c.execute("select ledger, date(record_time), time(record_time), stock_code, stock_name, side, price, qty from investment_tool.tzzb_record "
              "where record_type='bs_leg' and is_deleted=0 and record_time >= %s order by ledger, stock_code, record_time", (since,))
    legs = collections.defaultdict(list)
    for led, d, t, code, nm, sd, px, q in c.fetchall():
        code = str(code or "")
        if len(code) != 6 or not px or not q or not (code[:1] in "036" or code[:2] in ("11", "12")):
            continue
        legs[(led, code)].append((str(d), str(t).zfill(8), "买" in str(sd), float(px), float(q), nm or ""))
    E = []
    for (led, code), L in legs.items():
        for e in decision_points(L):
            e.update({"skill": led, "code": code})
            E.append(e)
    log(f"决策点 {len(E)} 个(同票同方向相隔 >15 分钟算新的一次), {len({e['skill'] for e in E})} 个账本")
    # 2) 行情
    cbm = cb_map()
    codes = {e["code"] for e in E} | {cbm.get(e["code"]) for e in E if e["code"][:2] in ("11", "12") and cbm.get(e["code"])}
    d0 = (dt.date.fromisoformat(since) - dt.timedelta(days=260)).isoformat()
    K = load_kline(c, codes, d0)
    mk = market_map(c, (dt.date.fromisoformat(since) - dt.timedelta(days=15)).isoformat())
    days = sorted(mk)
    log(f"日线 {sum(len(v) for v in K.values())} 行, 市况 {len(mk)} 天")
    topo = load_topo()
    log(f"本体: 题材 {sum(len(v) for v in topo['theme'].values())} · 席位票日 {sum(len(v) for v in topo['seat'].values())}")
    # sample_lib 事后板型(只做展示) — 读一份快照
    SB = {}
    if SAMPLES.exists():
        for l in SAMPLES.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                SB[r["id"]] = (r.get("board"), r.get("label"))
    # 3) 特征 + 路径
    cards_cache = {}
    cases = []
    for e in E:
        KK = K.get(e["code"])
        if not KK:
            continue
        ix = {k[0]: j for j, k in enumerate(KK)}
        i = ix.get(e["d"])
        if i is None or i < 2:
            continue
        stkK, si = None, None
        if e["code"][:2] in ("11", "12"):
            sc = cbm.get(e["code"])
            stkK = K.get(sc) if sc else None
            if stkK:
                si = next((j for j, k in enumerate(stkK) if k[0] == e["d"]), None)
        px = e["px_first"]
        f = feats(e["code"], e["name"], KK, i, px, mk, topo, stkK, si, lim_of(cbm.get(e["code"], "000000")))
        # 持仓状态(决策那一刻): 日卡昨收 + 当天更早的腿
        if e["skill"] not in cards_cache:
            cards_cache[e["skill"]] = parse_cards(e["skill"])
        card = cards_cache[e["skill"]].get(e["d"])
        f["hold"], f["hold_pnl"], pos_total = hold_state(e, card, f["pc"], px)
        f["act"] = act_of(f, e["side"], e["t"])
        f["pos_total"] = pos_total
        f["posb"] = pos_b(pos_total)
        # 结果路径(相对成交均价)
        pxa = e["px_avg"]
        path = []
        for k in (1, 2, 3):
            if i + k < len(KK):
                path.append((KK[i + k][0], round((KK[i + k][2] / pxa - 1) * 100, 2), round((KK[i + k][4] / pxa - 1) * 100, 2)))
        r0 = round((KK[i][4] / pxa - 1) * 100, 2)
        sid = f"{e['skill']}:{e['d']}:{e['code']}"
        cs = {"id": f"{sid}:{e['side']}:{e['k']}", "day_key": f"{sid}:{e['side']}", "k": e["k"], "skill": e["skill"], "mentor": reg.get(e["skill"], {}).get("display", e["skill"]), "neg_acct": e["skill"] in NEG_ACCTS,
              "d": e["d"], "t": e["t"], "code": e["code"], "name": e["name"], "side": e["side"], "px": round(pxa, 3), "qty": e["qty"], "n_legs": e["n_legs"],
              "legs": e["legs"], "X": f["X"], "f": f, "path": path, "r0": r0, "board_post": SB.get(sid, (None, None))[0]}
        cases.append(cs)
    # 4) 卖出去向 / 回补(按时间; 查询时按 D 截断)
    by = collections.defaultdict(list)
    for cs in cases:
        by[(cs["skill"], cs["code"])].append(cs)
    for v in by.values():
        v.sort(key=lambda x: (x["d"], x["t"]))
        for j, cs in enumerate(v):
            want = "卖" if cs["side"] == "买" else "买"
            nx = next((y for y in v[j + 1:] if y["side"] == want and (y["d"], y["t"]) > (cs["d"], cs["t"])), None)
            if nx:
                cs["next"] = {"d": nx["d"], "t": nx["t"], "side": nx["side"], "px": nx["px"], "pnl": round((nx["px"] / cs["px"] - 1) * 100, 2)}
    addon_pass(cases)
    log(f"案例 {len(cases)} 个")
    # 5) 文字: 日卡 + md 推测 + cases.md
    mdtxt = {}
    for f_ in md_files():
        mdtxt[f_.stem] = f_.read_text(encoding="utf-8", errors="replace")
    md_mentor = {}   # (skill, 日) → 推测块
    docs = []
    for d, txt in mdtxt.items():
        # 有些天 md 漏了 "### 同花顺投资账本" 标题, 账本小节挂在 bilibili 下面 → 两节合起来按小节名分流(10/26 修: 悟到空方为悟道 被当成 B站)
        blocks = [("acc", nm, body) for nm, body in subblocks(section(txt, "同花顺投资账本"))] + [("bili", nm, body) for nm, body in subblocks(section(txt, "bilibili"))]
        for src, nm, body in blocks:
            sk = md2skill.get(nkey(nm))
            up = next((v for k, v in UP_NAMES.items() if k in nkey(nm)), None)
            if sk and not up:
                if (sk, d) in md_mentor:
                    continue
                md_mentor[(sk, d)] = body
                spec = body.split("【推测】", 1)[-1] if "【推测】" in body else ""
                for ch in chunks(spec, 600):
                    docs.append({"kind": "账本推测", "src": f"md {d} 同花顺投资账本 · {nm}", "d": d, "known": d, "skill": sk, "text": ch})
                continue
            if src != "bili" or not up:
                continue
            for ch in chunks(body, 600):
                if len(ch) < 60:
                    continue
                docs.append({"kind": "B站原话", "src": f"md {d} bilibili · {nm}", "d": d, "known": d, "skill": up, "text": ch})
        if d >= "2026-10-01":
            for head in ("午评", "收评", "复盘"):
                body = section(txt, head, level=2)
                body = re.split(r"^### 龙虎榜", body, flags=re.M)[0]
                for ch in chunks(body, 600):
                    if len(ch) >= 80:
                        docs.append({"kind": "复盘叙述", "src": f"md {d} {head}", "d": d, "known": d, "skill": None, "text": ch})
    for sd in sorted((ROOT / "skills").glob("*-skill")):
        f_ = sd / "persona" / "cases.md"
        if not f_.exists():
            continue
        sk = sd.name[:-6]
        txt = f_.read_text(encoding="utf-8", errors="replace")
        for blk in re.split(r"^### ", txt, flags=re.M)[1:]:
            m = DATE_RE.search(blk.splitlines()[0])
            if not m:
                continue
            d = m.group(0)
            body = "### " + blk.strip()
            docs.append({"kind": "导师案例", "src": f"skills/{sd.name}/persona/cases.md", "d": d, "known": max_date(body, d), "skill": sk, "text": body[:2500],
                         "title": blk.splitlines()[0][:120]})
    # 电报: 近 95 个自然日(约 60 个交易日)加红
    tg_since = (dt.date.today() - dt.timedelta(days=95)).isoformat()
    c.execute("select publish_time, title, brief, content from investment_tool.cls_telegraph where is_deleted=0 and level='B' and publish_time >= %s order by publish_time", (tg_since,))
    ntg = 0
    for pt, ti, br, co in c.fetchall():
        t = (ti or "") + " " + (br or co or "")
        t = re.sub(r"<[^>]+>", "", t).strip()[:700]
        if len(t) < 20:
            continue
        d = str(pt)[:10]
        docs.append({"kind": "加红电报", "src": f"财联社 {str(pt)[:16]}", "d": d, "known": d, "skill": None, "text": t})
        ntg += 1
    log(f"原文库 {len(docs)} 段(电报 {ntg}) · md {len(mdtxt)} 天")
    # 案例文字(不含结果)
    for cs in cases:
        card = cards_cache.get(cs["skill"], {}).get(cs["d"])
        nm = nkey(cs["name"])
        tl = [x for x in (card or {}).get("trades", []) if nm[:3] and nm[:3] in nkey(x) and f" {cs['side']} " in x[:14]]
        auc = next((v for k, v in (card or {}).get("auction", {}).items() if nm[:3] and nm[:3] in nkey(k)), "")
        res = (card or {}).get("result", "")
        res_mine = "; ".join(p for p in re.split(r"[;；]", res) if nm[:3] and nm[:3] in nkey(p))
        mt = md_mentor.get((cs["skill"], cs["d"]), "")
        spec = [b for b in re.split(r"\n- ", mt.split("【推测】", 1)[-1]) if nm[:3] and nm[:3] in nkey(b)] if "【推测】" in mt else []
        cs["txt"] = {"card_trades": tl[:4], "card_auction": auc, "card_hold": (card or {}).get("holds", {}).get(cs["name"]) if card else None,
                     "card_pos": (card or {}).get("pos_total") if card else None, "card_tags": (card or {}).get("tags", ""),
                     "card_result": res_mine or "", "interp": (card or {}).get("interp", ""), "md_spec": [s.strip()[:500] for s in spec[:3]]}
        cs["etext"] = case_text(cs)
        cs["etext_base"] = case_text(cs, base=True)
    # 6) 向量
    meta = {"built": dt.datetime.now().isoformat(timespec="seconds"), "since": since, "cases": len(cases), "docs": len(docs), "model": MODEL,
            "onto_built": sqlite3.connect(f"file:{ONTO}?mode=ro", uri=True).execute("select v from meta where k='built'").fetchone()[0]}
    if do_embed:
        t1 = time.time()
        CE = embed_cached([cs["etext"] for cs in cases] + [cs["etext_base"] for cs in cases] + [dd["text"] for dd in docs])
        n = len(cases)
        CE, CB, DE = CE[:n], CE[n:2 * n], CE[2 * n:]
        np.save(OUTD / "cases_emb_base.npy", CB.astype(np.float16))
        meta["embed_s"] = round(time.time() - t1, 1)
        np.save(OUTD / "cases_emb.npy", CE.astype(np.float16))
        np.save(OUTD / "docs_emb.npy", DE.astype(np.float16))
    (OUTD / "cases.pkl").write_bytes(pickle.dumps(cases))
    (OUTD / "docs.pkl").write_bytes(pickle.dumps(docs))
    (OUTD / "topo.pkl").write_bytes(pickle.dumps(topo))
    (OUTD / "mkt.json").write_text(json.dumps(mk, ensure_ascii=False), encoding="utf-8")
    meta["total_s"] = round(time.time() - t0, 1)
    (OUTD / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"完成 {OUTD}: {meta}")


def case_text(cs, base=False):
    """base=True: 不含日卡解读 / md 推测(那些是事后写的; 案例的次日 ≥ 查询日 D 时只能用 base 版, 防偷看)"""
    f = cs["f"]
    s = [f"{cs['mentor']} {cs['side']} {cs['name']} {f['asset']}", f"昨日{f['prev']}({f.get('prev_pct')}%) 连板{f['h']}", f"开盘{f.get('gap')}% 成交价较昨收{f.get('px_pct')}%",
         f"箱体{f['box']} 市况{f.get('mkt')}", f"持仓{f['hold']}" + (f" 浮{f['hold_pnl']}%" if f.get("hold_pnl") is not None else ""),
         f"题材{f.get('theme') or '-'} 梯队{tier_cn(f.get('tier')) or '-'}"]
    if f.get("stk_gap") is not None:
        s.append(f"正股开盘{f['stk_gap']}%")
    T = cs.get("txt") or {}
    body = " | ".join(s)
    for x in T.get("card_trades") or []:
        body += " | " + re.sub(r"卖后当日收较卖价[+\-\d.%]+", "", x)
    if T.get("card_auction"):
        body += " | 竞价 " + T["card_auction"]
    if base:
        return body[:1500]
    if T.get("interp"):
        body += " | " + T["interp"][:400]
    for x in T.get("md_spec") or []:
        body += " | " + x[:250]
    return body[:1500]


# ---------------------------------------------------------------- 查询 ----------------------------------------------------------------
_S = {}


def store():
    if not _S:
        _S["cases"] = pickle.loads((OUTD / "cases.pkl").read_bytes())
        _S["docs"] = pickle.loads((OUTD / "docs.pkl").read_bytes())
        _S["topo"] = pickle.loads((OUTD / "topo.pkl").read_bytes())
        _S["mk"] = json.loads((OUTD / "mkt.json").read_text(encoding="utf-8"))
        _S["CE"] = np.load(OUTD / "cases_emb.npy").astype(np.float32) if (OUTD / "cases_emb.npy").exists() else None
        _S["CB"] = np.load(OUTD / "cases_emb_base.npy").astype(np.float32) if (OUTD / "cases_emb_base.npy").exists() else None
        _S["idx"] = {cs["id"]: j for j, cs in enumerate(_S["cases"])}
        if any("addon" not in cs["f"] for cs in _S["cases"][:50]):
            addon_pass(_S["cases"])
        for cs in _S["cases"]:
            if "act" not in cs["f"]:
                cs["f"]["act"] = act_of(cs["f"], cs["side"], cs["t"])
        _S["DE"] = np.load(OUTD / "docs_emb.npy").astype(np.float32) if (OUTD / "docs_emb.npy").exists() else None
        _S["meta"] = json.loads((OUTD / "meta.json").read_text(encoding="utf-8"))
    return _S


def query_situation(code, D, side="买", px=None, t=None, ctx=None, c=None):
    """查询情境: 行情只取 D 之前 + D 开盘; ctx 覆盖"""
    S = store()
    ctx = dict(ctx or {})
    c = c or cur()
    c.execute("select trade_date, open, high, low, close, pre_close from investment_market.kline_day where symbol=%s and is_deleted=0 and trade_date <= %s "
              "and trade_date >= %s order by trade_date", (sym(code), D, (dt.date.fromisoformat(D) - dt.timedelta(days=400)).isoformat()))
    K = [(str(a), *(float(x or 0) for x in r)) for a, *r in c.fetchall()]
    K = [k for k in K if k[1] and k[5]]
    c.execute("select name from investment_market.security_master where code=%s limit 1", (code,))
    r = c.fetchone()
    name = ctx.get("name") or (r[0] if r else code)
    i = len(K) if not K or K[-1][0] < D else len(K) - 1
    if K and i < len(K):
        K = K[:i] + [(K[i][0], K[i][1], None, None, None, K[i][5])]   # D 只留开盘价
    stkK, si = None, None
    if code[:2] in ("11", "12"):
        sc = cb_map().get(code)
        if sc:
            c.execute("select trade_date, open, high, low, close, pre_close from investment_market.kline_day where symbol=%s and is_deleted=0 and trade_date <= %s "
                      "and trade_date >= %s order by trade_date", (sym(sc), D, (dt.date.fromisoformat(D) - dt.timedelta(days=60)).isoformat()))
            stkK = [(str(a), *(float(x or 0) for x in rr)) for a, *rr in c.fetchall()]
            si = len(stkK) if not stkK or stkK[-1][0] < D else len(stkK) - 1
            if si < len(stkK):
                stkK = stkK[:si] + [(stkK[si][0], stkK[si][1], None, None, None, stkK[si][5])]
    mk = S["mk"]
    pdD = K[i - 1][0]
    if pdD not in mk:   # 建库后才收盘的那天: 现算
        import sample_lib as SL
        mk = dict(mk)
        mk.update(SL.market_days(pdD))
    if "gap" in ctx and ctx["gap"] is not None:
        pc = K[i - 1][4]
        op = pc * (1 + float(ctx["gap"]) / 100)
        K = K[:i] + [(D, op, None, None, None, pc)]
    if px is None and ctx.get("px_pct") is not None:
        px = K[i - 1][4] * (1 + float(ctx["px_pct"]) / 100)
    f = feats(code, name, K, i, px, mk, S["topo"], stkK, si, lim_of(cb_map().get(code, "000000")) if code[:2] in ("11", "12") else 0.10)
    if "stk_gap" in ctx:
        f["stk_gap"] = ctx["stk_gap"]
        f["stk_gapb"] = gap_b(ctx["stk_gap"], 0.10)
    hp = ctx.get("hold_pnl")
    held = ctx.get("held", hp is not None)
    f["hold_pnl"] = hp
    f["hold"] = ctx.get("hold") or hold_b(1 if held else 0, hp)
    f["pos_total"] = ctx.get("pos_total")
    f["posb"] = pos_b(f["pos_total"])
    for k in ("asset", "prev", "h", "box", "mkt", "theme", "tier", "pxb", "gapb"):
        if ctx.get(k) is not None:
            f[k] = ctx[k]
    f["act"] = ctx.get("act") or act_of(f, side, t)
    if side == "买":   # 当天加仓位置: ctx 给 addon, 或给 first_buy_px(当天首笔买价) + n_buys_before(当天已买几次)
        f["addon"] = ctx.get("addon") or addon_b(f["px"], ctx.get("first_buy_px"), ctx.get("n_buys_before") or 0)
    else:
        f["addon"] = None
    return {"code": code, "name": name, "D": D, "side": side, "t": t, "f": f}


def t_b(t):
    t = (t or "")[:5]
    if not t:
        return None
    return "竞价" if t <= "09:25" else "开盘5分钟" if t <= "09:35" else "早盘" if t <= "10:30" else "上午" if t <= "11:30" else "午后"


def sim_struct(qf, cf, qt=None, ct=None):
    s = 0.0
    for k, w in SW.items():
        a, b = qf.get(k), cf.get(k)
        if a is None or b is None:
            s += w * 0.5 if (k != "stk_gapb" or qf.get("asset") != "股票") else w
            continue
        if a == b:
            s += w
        elif k in ORD and a in ORD[k] and b in ORD[k] and abs(ORD[k].index(a) - ORD[k].index(b)) == 1:
            s += w * 0.5
    # 连续量: 开盘 / 成交价越近越像(细分同档内)
    for k in ("gap", "px_pct"):
        a, b = qf.get(k), cf.get(k)
        if a is not None and b is not None:
            s += 0.05 * max(0.0, 1 - abs(a - b) / 6)
    a, b = qf.get("prev_pct"), cf.get("prev_pct")   # 昨日涨跌越近越像(10/26 加)
    if a is not None and b is not None:
        s += 0.04 * max(0.0, 1 - abs(a - b) / 8)
    a, b = qf.get("hold_pnl"), cf.get("hold_pnl")   # 持仓浮盈越近越像(深套 −10% 和 −5% 是两种处境; 10/26 K2 加)
    if a is not None and b is not None:
        s += 0.06 * max(0.0, 1 - abs(a - b) / 8)
    a, b = t_b(qt), t_b(ct)   # 时段(竞价 / 开盘 5 分钟 / 早盘 / 上午 / 午后): 软加分, 不做硬过滤
    if a and b and a == b:
        s += 0.06
    return s / 1.34


def sim_topo(q, cs):
    qf, cf = q["f"], cs["f"]
    why, s = [], 0.0
    if cs["code"] == q["code"]:
        s += 0.5
        why.append("同票")
    if qf.get("theme") and qf.get("theme") == cf.get("theme"):
        s += 0.3
        why.append(f"同题材 {qf['theme']}")
    if qf.get("tier") and qf.get("tier") == cf.get("tier"):
        s += 0.1
        why.append(f"同梯队位置 {tier_cn(qf['tier'])}")
    qs = {x[0] for x in qf.get("seats") or []}
    shared = [x for x in cf.get("seats") or [] if x[0] in qs]
    if shared:
        s += 0.25
        why.append("同席位 " + "/".join(sorted({(x[1] if x[1] and x[1] != '营业部' else x[0]) for x in shared}))[:40])
    if q.get("skill") and cs["skill"] == q["skill"]:
        s += 0.2
        why.append("同导师")
    return min(1.0, s), why


def sem_map(cos):
    return float(min(1.0, max(0.0, (cos - 0.35) / 0.45)))


# 放宽步骤(默认; 10/26 验证后定): 先去掉最弱的三项, 再把 持仓 / 开盘区间 / 价位档 "并邻档", 然后才逐个去掉; 品种 + 方向永不放宽
# 步骤 = (动作, 条件): drop = 去掉; coarse = 并邻档(有序档 ±1; 持仓 = 只分 未持有 / 浮盈 / 被套)
RELAX = [("drop", "posb"), ("drop", "mkt"), ("drop", "box"), ("coarse", "hold"), ("coarse", "gapb"), ("coarse", "stk_gapb"), ("drop", "asset"),
         ("coarse", "pxb"), ("drop", "h"), ("drop", "gapb"), ("coarse", "prev"), ("drop", "stk_gapb"), ("drop", "act"), ("drop", "pxb"), ("drop", "hold")]
RELAX_OLD = [("drop", k) for k in reversed(CONDS) if k != "act"] + [("drop", "act")]   # 10/25 初版: 按 CONDS 从尾部逐个去掉(验证里对照用)
PREV_G = {"涨停": "强", "炸板·收涨": "炸板", "炸板·收跌": "炸板", "大涨": "强", "平": "平", "大跌": "弱", "跌停": "弱"}


def _hold_g(h):
    return "浮盈" if (h or "").startswith("浮盈") else "被套" if (h or "").startswith("被套") else h


def _ok(k, mode, a, b):
    if a is None:
        return True
    if mode == "exact" or b is None:
        return a == b
    if k == "hold":
        return _hold_g(a) == _hold_g(b)
    if k == "prev":
        return PREV_G.get(a) == PREV_G.get(b)
    o = ORD.get(k)
    return a == b or bool(o and a in o and b in o and abs(o.index(a) - o.index(b)) <= 1)


def cell_filter(q, cands, conds):
    """conds = {条件: "exact" | "coarse"}"""
    qf = q["f"]
    return [cs for cs in cands if all(_ok(k, m, qf.get(k), cs["f"].get(k)) for k, m in conds.items())]


def step_cn(st):
    return ("去掉了 " if st[0] == "drop" else "并邻档 ") + CN.get(st[1], st[1])


def retrieve(q, text=None, w=DEF_W, relax=None, qvec=None, min_n=MIN_N):
    """→ dict(格子 / 放宽 / 分布 / 正样本 top2 / 负样本 top1 / 原文 top2 / 耗时); relax = 放宽步骤表(默认 RELAX; [] = 不做硬过滤)"""
    S = store()
    t0 = time.time()
    D, qf = q["D"], q["f"]
    fam = (lambda a: "转债" if a in ("转债", "妖债") else a)
    base = [cs for cs in S["cases"] if cs["d"] < D and cs["side"] == q["side"] and fam(cs["f"]["asset"]) == fam(qf["asset"])]
    steps = list(RELAX if relax is None else relax)
    keys = [k for k in CONDS if qf.get(k) is not None and not (k == "stk_gapb" and qf.get("asset") == "股票")]
    if qf.get("asset") in ("转债", "妖债"):
        keys.append("asset")   # 妖债 / 转债 区分(可放宽)
    skipped = [k for k in CONDS if qf.get(k) is None and not (k == "stk_gapb" and qf.get("asset") == "股票")]
    conds = {k: "exact" for k in keys} if relax != [] else {}
    dropped = []
    cell = cell_filter(q, base, conds)
    for st in steps:
        if len({cs.get("day_key", cs["id"]) for cs in cell}) >= min_n:
            break
        act, k = st
        if k not in conds or (act == "coarse" and conds[k] == "coarse"):
            continue
        if act == "drop":
            del conds[k]
        else:
            conds[k] = "coarse"
        dropped.append(st)
        cell = cell_filter(q, base, conds)
    # 打分
    vec = None
    if S["CE"] is not None and (text or qvec is not None):
        vec = qvec if qvec is not None else embed([text])[0]
    idx = S["idx"]
    scored = []
    for cs in cell:
        a = sim_struct(qf, cs["f"], q.get("t"), cs["t"])
        b, why_t = sim_topo(q, cs)
        e = None
        if vec is not None:
            late = not cs.get("path") or cs["path"][0][0] >= D   # 次日 ≥ D: 解读是事后写的 → 用不含解读的 base 向量
            if late and S.get("CB") is None:
                e = None
            else:
                e = float((S["CB"] if late else S["CE"])[idx[cs["id"]]] @ vec)
        sc = w[0] * a + w[1] * b + (w[2] * sem_map(e) if e is not None else 0)
        lb, m = label_asof(cs, D)
        scored.append((sc, a, b, e, why_t, lb, m, cs))
    scored.sort(key=lambda x: -x[0])
    n_dp = len(scored)
    seen, uniq = set(), []   # 同一导师同日同票同方向的多个决策点只算一次(分布按"日"计, 防一天拆成 6 笔把分布灌水)
    for x in scored:
        if x[7].get("day_key", x[7]["id"]) not in seen:
            seen.add(x[7].get("day_key", x[7]["id"]))
            uniq.append(x)
    scored = uniq
    pos = [x for x in scored if x[5] == "正" and not x[7]["neg_acct"]][:2]
    neg = [x for x in scored if x[5] == "负"][:1]
    # 原文库: 语义 + 同票 / 同导师加分
    docs = []
    if vec is not None and S["DE"] is not None:
        sims = S["DE"] @ vec
        cand = []
        for j in np.argsort(-sims)[:400]:
            dd = S["docs"][j]
            if dd["known"] >= D:
                continue
            bonus = (0.08 if q["name"][:2] in dd["text"] else 0) + (0.04 if q.get("skill") and dd.get("skill") == q.get("skill") else 0)
            cand.append((float(sims[j]) + bonus, float(sims[j]), dd))
        cand.sort(key=lambda x: -x[0])
        seen = set()
        for x in cand:
            if x[2]["kind"] in seen and len(seen) < 3:
                continue
            seen.add(x[2]["kind"])
            docs.append(x)
            if len(docs) >= 2:
                break
    return {"q": q, "conds": conds, "dropped": dropped, "skipped": skipped, "cell": scored, "n_dp": n_dp, "pos": pos, "neg": neg, "docs": docs, "ms": round((time.time() - t0) * 1000)}


def _pct(v, p):
    return v[min(len(v) - 1, int(len(v) * p))]


def dist_line(scored, key):
    v = sorted([x[6][key] for x in scored if key in x[6]])
    if not v:
        return "n=0"
    return f"n={len(v)} 均{sum(v) / len(v):+.1f}% P10 {_pct(v, .1):+.1f}% 中位{_pct(v, .5):+.1f}% 最差{v[0]:+.1f}%"


def fmt_case(x, q, tag):
    sc, a, b, e, why_t, lb, m, cs = x
    D = q["D"]
    f, qf = cs["f"], q["f"]
    match = [CN[k] for k in ("prev", "act", "addon", "pxb", "gapb", "hold", "h", "stk_gapb", "box", "mkt", "posb") if qf.get(k) is not None and f.get(k) == qf.get(k)]
    if t_b(q.get("t")) and t_b(q.get("t")) == t_b(cs["t"]):
        match.append(f"时段={t_b(cs['t'])}")
    L = [f"【{tag}】{cs['mentor']}{'(负样本账户)' if cs['neg_acct'] else ''} {cs['d']} {cs['t'][:5]} {f.get('act', '')}{cs['side']}{'(' + f['addon'] + ')' if f.get('addon') and f['addon'] != '首笔' else ''} {cs['name']}({cs['code']}) @{cs['px']} ×{cs['n_legs']}腿 → 标签 {lb}"]
    L.append(f"  当时: 昨日{f['prev']}({f.get('prev_pct')}%) 连板{f['h']} · 开盘{f.get('gap')}% · 成交价较昨收{f.get('px_pct')}% · 箱体{f['box']} · 市况{f.get('mkt')} · 持仓{f['hold']}"
             + (f"(浮{f['hold_pnl']}%)" if f.get("hold_pnl") is not None else "") + (f" · 总仓位{f['pos_total']:.0f}%" if f.get("pos_total") is not None else "")
             + (f" · 正股开盘{f['stk_gap']}%" if f.get("stk_gap") is not None else "") + (f" · 题材 {f['theme']}({tier_cn(f.get('tier'))})" if f.get("theme") else ""))
    L.append(f"  为什么算像: 结构对上 {len(match)} 项[{'/'.join(match) or '无'}] 结构分{a:.2f} · 拓扑[{'; '.join(why_t) or '无'}] {b:.2f} · 语义相似度 {e:.2f}" if e is not None else
             f"  为什么算像: 结构对上 {len(match)} 项[{'/'.join(match) or '无'}] 结构分{a:.2f} · 拓扑[{'; '.join(why_t) or '无'}] {b:.2f}")
    T = cs.get("txt") or {}
    nd = next((p[0] for p in cs.get("path", [])[:1]), "9999")
    legs = ", ".join(f"{t[:5]} {p}×{int(qq)}" for t, p, qq in (cs.get("legs") or [])[:6])
    card_line = next((x for x in T.get("card_trades") or [] if x[:5] == cs["t"][:5]), None)   # 日卡成交行按方向汇总一天, 只有当天首个决策点能对上时刻
    if card_line:
        L.append("  他怎么做(日卡): " + re.sub(r"卖后当日收较卖价[+\-\d.%]+", "", card_line)[:220])
    else:
        L.append(f"  他怎么做(逐笔, 当天第 {cs.get('k', 0) + 1} 次): " + legs + (" | 日卡同方向汇总: " + re.sub(r"卖后当日收较卖价[+\-\d.%]+", "", T["card_trades"][0])[:160]
                                                                         if T.get("card_trades") else ""))
    if T.get("interp") and nd < D:
        L.append("  他怎么想(日卡解读, 模型推测): " + re.sub(r"^解读\([^)]*\):\s*", "", T["interp"]).split("对应规则")[0][:300])
    if T.get("md_spec") and cs["d"] < D:
        L.append("  md 推测: " + re.sub(r"\s+", " ", T["md_spec"][0])[:260])
    res = [f"T+0 收{cs['r0']:+.1f}%"] + [f"T+{k + 1} {p[0][5:]} 高{p[1]:+.1f}/收{p[2]:+.1f}" for k, p in enumerate(cs.get("path", [])) if p[0] < D]
    nx = cs.get("next")
    if nx and nx["d"] < D:
        res.append(f"之后 {nx['d'][5:]} {nx['t'][:5]} {nx['side']} @{nx['px']}({nx['pnl']:+.1f}%)")
    L.append("  结果: " + " · ".join(res) + f" (X={cs['X']}%)")
    return "\n".join(L)


def render(R, text=None):
    q, qf = R["q"], R["q"]["f"]
    cell = R["cell"]
    cnt = collections.Counter(x[5][:2] for x in cell)
    bym = collections.Counter(x[7]["mentor"] for x in cell)
    keyname = " × ".join(f"{CN[k]}={qf.get(k)}" + ("(含邻档)" if m == "coarse" else "") for k, m in R["conds"].items() if k in CN)
    L = [f"## 相似案例 · {q['name']}({q['code']}) {q['D']} {q['side']}" + (f" · {text}" if text else ""),
         f"情境: {qf['asset']} · {qf.get('act')}{q['side']}" + (f"({qf['addon']})" if qf.get("addon") else "") + f" · 昨日{qf['prev']}({qf.get('prev_pct')}%) 连板{qf['h']} · 开盘{qf.get('gap')}% · 价位{qf.get('px_pct')}% · 箱体{qf['box']} · 市况{qf.get('mkt')} · 持仓{qf['hold']}"
         + (f" · 总仓位{qf['pos_total']}%" if qf.get('pos_total') is not None else "") + (f" · 正股开盘{qf['stk_gap']}%" if qf.get('stk_gap') is not None else "")
         + (f" · 题材 {qf['theme']}({tier_cn(qf.get('tier'))})" if qf.get('theme') else ""),
         f"格子[{keyname or '只按品种 + 方向'}]: n={len(cell)}(导师×日×票; 决策点 {R.get('n_dp', len(cell))}) · 正 {cnt['正']} / 负 {cnt['负']} / 平 {cnt['平']} / 待核 {cnt['待核']}"
         + (f" · 正率 {cnt['正'] / max(1, cnt['正'] + cnt['负'] + cnt['平']):.0%}" if cnt['正'] + cnt['负'] + cnt['平'] else ""),
         (f"已放宽 {len(R['dropped'])} 步: " + " → ".join(step_cn(st) for st in R["dropped"]) + f"(原格子 n<{MIN_N})") if R["dropped"] else "未放宽",
         ("情境里缺: " + "、".join(CN.get(k, k) for k in R["skipped"]) + "(没参与过滤)") if R["skipped"] else ""]
    if q["side"] == "买":
        L.append(f"- 3 日内最高(能卖到的): {dist_line(cell, 'hmax')}")
        L.append(f"- T+3 收盘(拿着不动): {dist_line(cell, 'c3')}")
    else:
        L.append(f"- 卖后次日收(负 = 卖对): {dist_line(cell, 'c1')}")
        L.append(f"- 卖后 3 日最高收: {dist_line(cell, 'cmax')}")
    L.append("- 哪些导师: " + "、".join(f"{m} {n}" for m, n in bym.most_common(8)))
    pa = [x for x in cell if not x[7]["neg_acct"]]   # 10/26: 负样本账户(洋大人 / 猎人IH / 护卫港 / 买入太急 / 鳄狼King)常占格子一半, 单列正样本账户的分布
    if len(pa) != len(cell):
        cp = collections.Counter(x[5][:2] for x in pa)
        L.append(f"- 只看正样本账户: n={len(pa)} · 正 {cp['正']} / 负 {cp['负']} / 平 {cp['平']}" + (f" · {'3 日内最高' if q['side'] == '买' else '卖后次日收'} {dist_line(pa, 'hmax' if q['side'] == '买' else 'c1')}" if pa else ""))
    if q["side"] == "买":   # 实际怎么出的(截至 D): 日内T 型导师看这个, 3 日标签对秒级出场的人意义不大
        ex = collections.defaultdict(list)
        for x in cell:
            nx = x[7].get("next")
            if nx and nx["d"] < q["D"]:
                k = sum(1 for p in x[7].get("path", []) if p[0] <= nx["d"])
                ex["当天卖" if nx["d"] == x[7]["d"] else f"T+{k}卖" if k <= 3 else "3 天后才卖"].append(nx["pnl"])
            else:
                ex["截至 D 还没卖 / 无记录"].append(None)
        L.append("- 实际怎么出的(截至 D): " + " · ".join(f"{k} {len(v)} 笔" + (f"(卖出收益 均{sum(y for y in v if y is not None) / max(1, sum(1 for y in v if y is not None)):+.1f}% 最差{min(y for y in v if y is not None):+.1f}%)" if any(y is not None for y in v) else "")
                                                for k, v in sorted(ex.items(), key=lambda kv: -len(kv[1]))))
    L = [x for x in L if x]
    for x in R["pos"]:
        L.append(fmt_case(x, q, "正样本·最像"))
    if not R["pos"]:
        L.append("【正样本】格子里没有(截至 D 已判正的)")
    for x in R["neg"]:
        L.append(fmt_case(x, q, "负样本·如果错了(只当教训, 不当依据)"))
    if not R["neg"]:
        L.append("【负样本】格子里没有")
    for s, s0, dd in R["docs"]:
        L.append(f"【原文参考·{dd['kind']}】{dd['src']}(相似度 {s0:.2f}): " + re.sub(r"\s+", " ", dd["text"])[:260])
    L.append(f"(检索 {R['ms']} ms; 只用 {q['D']} 之前的案例与标签)")
    return "\n".join(L)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "query"])
    ap.add_argument("--since", default="2025-09-01")
    ap.add_argument("--no-embed", action="store_true")
    ap.add_argument("--code")
    ap.add_argument("--date")
    ap.add_argument("--side", default="买")
    ap.add_argument("--px", type=float)
    ap.add_argument("--t")
    ap.add_argument("--ctx", default="{}")
    ap.add_argument("--text")
    ap.add_argument("--skill")
    ap.add_argument("--w", default=",".join(map(str, DEF_W)))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.cmd == "build":
        return build(a.since, not a.no_embed)
    t0 = time.time()
    q = query_situation(a.code, a.date, a.side, a.px, a.t, json.loads(a.ctx))
    q["skill"] = a.skill
    R = retrieve(q, a.text, tuple(float(x) for x in a.w.split(",")))
    if a.json:
        print(json.dumps({"q": q, "dropped": R["dropped"], "n": len(R["cell"]), "pos": [x[7]["id"] for x in R["pos"]], "neg": [x[7]["id"] for x in R["neg"]]}, ensure_ascii=False, default=str))
    else:
        print(render(R, a.text))
    print(f"(总耗时 {time.time() - t0:.2f}s, 含载入)")


if __name__ == "__main__":
    main()
