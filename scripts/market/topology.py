# -*- coding: utf-8 -*-
"""topology.py — 市场拓扑自动生成(TODO 二-13, 10/19 用户定今晚做今晚上线; 零 token, 只读本地库)

每只 A 股的"邻居"= 它涨跌时应该一起看的票, 四条腿各自独立给证据, 来源越多越可信:
  ① 相关60  近 60 个交易日 **扣掉大盘后** 的日收益相关(残差 = 个股涨跌 − 当天全市场等权平均; 不扣的话 A 股齐涨齐跌, 谁跟谁都"相关")
  ② 相关20  同口径近 20 日(60 日窗口滞后, 题材刚切换时 20 日先反应; 两个窗口都高 = 稳定联动)
  ③ 同行业  东财行业(downloads/lhb/_industry/industry_em.json) / 申万三级(index_pit/stock_industry.jsonl 当前有效行)
  ④ 同概念  东财 F10 ★精准概念(downloads/f10 缓存, 目前只覆盖几百只关注票; 有就加分, 没有不扣分)
  可信度 conf = 相关强度(max(相关60, 相关20), 只有行业/概念腿时记 0.2) × 来源数, 每只留前 10 + 跷跷板(相关60 ≤ −0.6 且 相关20 ≤ −0.45, 只作参考)前 2
  期货: 按行业关键词映射(生猪养殖 → 生猪/玉米/豆粕 …) + 指数成分(上证50/沪深300/中证500/中证1000 → 对应股指期货)
用途(只做"多看哪些票 / 多预取哪些资料"的参考, **不进任何买卖规则**: 相关性是过去的统计, 题材切换会滞后):
  ctx_index 预取关键词 / md 命中 / 期货行(替代手写 KW 表, 手写表仍优先); paper_vs_real 同板块算半重合; 盯盘关联票 / facts 关注票(后续)
产物: downloads/market/<日>/topology.jsonl(每行一只: c 代码 / n 名 / ind 东财行业 / sw 申万 / fut 期货 / nb 邻居 / neg 跷跷板)
用法: python topology.py [--date D] [--show 002714]      (check md 每晚行情库采集后跑; 只用 D 及以前的日线)
API:  from topology import load; load("002714", D) → 该票一行(取 D 及以前最近一份), 没有 = None
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"
HIST = MKT / "history" / "kline_day"
IND_EM = ROOT / "downloads" / "lhb" / "_industry" / "industry_em.json"
IND_SW = MKT / "index_pit" / "stock_industry.jsonl"
IDX_CON = MKT / "index_pit" / "index_constituent.jsonl"
F10 = ROOT / "downloads" / "f10"
N_WIN, N_SHORT, TOP, NEG = 60, 20, 10, 2
# 10/21 用户教学: 多来源加权(近期涨停分析最高; rules.md 是桃哥 1~2 年前的地图, 不一定还有效; 统计类反映近 60/20 日真实联动)
# 配比 涨停近期 : rules.md : 统计类 : 其他(更早涨停) —— 用户给了 4:4:2:0.5 / 4:2.5:2.5:0.5 两档并让我自己设计; 默认取后者, 且按"本票有没有这类证据"重新归一:
#   本票近 120 日没上过涨停表 → 涨停两项不参与(不然冷门票永远没邻居); 本票不在 rules.md → rules 不参与
TOPO_W = {k: float(v) for k, v in zip(("lu", "rules", "stat", "old"), __import__("os").environ.get("TOPO_W", "4,2.5,2.5,0.5").split(","))}
# 行业关键词 → 期货(名字与 downloads/futures/<日>.md / facts 外围行一致); 子串匹配东财行业 + 申万三级名
FUT_MAP = [(r"生猪|养殖", ["生猪", "玉米", "豆粕"]), (r"饲料", ["豆粕", "玉米"]), (r"禽|鸡", ["鸡蛋", "玉米", "豆粕"]),
           (r"种植|农产品", ["玉米", "豆粕"]), (r"油气|石油|炼化|油服|油田", ["原油", "布伦特原油"]),
           (r"黄金|贵金属", ["黄金", "COMEX黄金"]), (r"白银", ["白银", "COMEX白银"]), (r"铜", ["铜"]),
           (r"工业金属|有色|铝|锌", ["铜"]), (r"钢|铁矿", ["螺纹钢", "铁矿石"]), (r"锂|能源金属|电池", ["碳酸锂"])]
IDX_FUT = {"000016": "上证50股指", "000300": "沪深300股指", "000905": "中证500股指", "000852": "中证1000股指"}
NOISE = re.compile(r"板块$|风格|大盘|中盘|小盘|股通|融资融券|标准普尔|富时|MSCI|HS300|深证|上证|中证|深成|机构重仓|转债标的|AH股|券商金股|中报|年报|季报|预增|预亏|首亏|高市净|昨日")


def _tail_rows(f, n):
    with f.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - 260 * (n + 10)))
        lines = fh.read().decode("utf-8", "ignore").splitlines()[1:] if size > 260 * (n + 10) else fh.read().decode("utf-8", "ignore").splitlines()
    out = []
    for l in lines[-(n + 5):]:
        try:
            out.append(json.loads(l))
        except ValueError:
            pass
    return out


def stock_universe(D):
    ms = sorted(p for p in MKT.glob("2026-*/security_master.jsonl") if p.parent.name <= D)
    out = {}
    for l in ms[-1].open(encoding="utf-8"):
        r = json.loads(l)
        if r.get("secType") == "STOCK" and r["symbol"][:2] in ("sh", "sz"):
            out[r["symbol"]] = r["name"]
    return out


def closes(D, syms):
    """symbol → {date: (close, preClose)}: 历史库尾部 + 每日 kline_day.jsonl(后者覆盖前者, preClose 已按除权调整)"""
    days = sorted(p.parent.name for p in MKT.glob("2026-*/kline_day.jsonl") if p.parent.name <= D)
    data = {s: {} for s in syms}
    for s in syms:
        f = HIST / f"{s}.jsonl"
        if f.exists():
            for r in _tail_rows(f, N_WIN + 5):
                if r.get("close") and r["tradeDate"] <= D:
                    data[s][r["tradeDate"]] = (r["close"], r.get("preClose"))
    for d in days[-(N_WIN + 5):]:
        for l in (MKT / d / "kline_day.jsonl").open(encoding="utf-8"):
            r = json.loads(l)
            s = r["symbol"]
            if s in data and r.get("close") and r.get("volume"):
                data[s][d] = (r["close"], r.get("preClose"))
    return data


def returns(data):
    alld = sorted({d for v in data.values() for d in v})
    dates = alld[-N_WIN:]
    syms = list(data)
    R = np.full((len(syms), len(dates)), np.nan, dtype=np.float32)
    for i, s in enumerate(syms):
        v = data[s]
        ds = sorted(v)
        pos = {d: k for k, d in enumerate(ds)}
        for j, d in enumerate(dates):
            if d not in v:
                continue
            c, pc = v[d]
            if not pc:
                k = pos[d]
                pc = v[ds[k - 1]][0] if k > 0 else None
            if pc:
                r = c / pc - 1
                if abs(r) < 0.31:      # 新股首日 / 数据错位不进
                    R[i, j] = r
    return syms, dates, R


def corr(R, min_n):
    import warnings
    warnings.simplefilter("ignore", RuntimeWarning)          # 停牌 / 新股整行 NaN, 下面按 ok 置空
    ok = np.sum(~np.isnan(R), axis=1) >= min_n
    X = R - np.nanmean(R, axis=0, keepdims=True)          # 扣掉当天全市场等权平均(残差)
    X = X - np.nanmean(X, axis=1, keepdims=True)
    sd = np.sqrt(np.nanmean(X ** 2, axis=1, keepdims=True))
    Z = np.where(np.isnan(X), 0, X / np.where(sd > 0, sd, 1)).astype(np.float32)
    C = (Z @ Z.T) / R.shape[1]
    C[~ok, :] = np.nan
    C[:, ~ok] = np.nan
    np.fill_diagonal(C, np.nan)
    return C


def industries(D):
    em = {}
    try:
        em = {k: v.get("board") for k, v in json.loads(IND_EM.read_text(encoding="utf-8"))["map"].items()}
    except (OSError, ValueError, KeyError):
        pass
    sw = {}
    if IND_SW.exists():
        for l in IND_SW.open(encoding="utf-8"):
            r = json.loads(l)
            if r.get("classification") == "SW" and r.get("inDate", "") <= D and (not r.get("outDate") or r["outDate"] > D):   # 同表还有证监会分类, 只取申万
                sw[r["code"]] = "/".join(x for x in (r.get("l2Name"), r.get("l3Name")) if x)
    return em, sw


def index_members(D):
    out = {}
    if IDX_CON.exists():
        for l in IDX_CON.open(encoding="utf-8"):
            r = json.loads(l)
            if r["indexCode"] in IDX_FUT and r.get("inDate", "") <= D and (not r.get("outDate") or r["outDate"] > D):
                out.setdefault(r["conCode"], []).append(IDX_FUT[r["indexCode"]])
    return out


def concepts():
    out = {}
    for f in F10.glob("*.json"):
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        out[j["code"]] = {b["name"] for b in j.get("boards", []) if b.get("precise") and not NOISE.search(b["name"])}
    return out


def _lu_s(x):
    return 1 - np.exp(-x / 1.0)


def build(D):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import topo_sources as TS
    LU, lu_seen = TS.lu_pairs(D)
    RC, MAN = TS.rules_clusters(), TS.manual()
    by_rules = {}
    for c0, ks in RC.items():
        for k in ks:
            by_rules.setdefault(k[1], set()).add(c0)
    uni = stock_universe(D)
    syms, dates, R = returns(closes(D, list(uni)))
    C60, C20 = corr(R, 45), corr(R[:, -N_SHORT:], 15)
    codes = [s[2:] for s in syms]
    idx = {c: k for k, c in enumerate(codes)}
    em, sw = industries(D)
    imem, con = index_members(D), concepts()
    by_em = {}
    for i, c in enumerate(codes):
        if em.get(c):
            by_em.setdefault(em[c], []).append(i)
    out = []
    for i, c in enumerate(codes):
        if np.all(np.isnan(C60[i])) and np.all(np.isnan(C20[i])):
            continue
        r60, r20 = np.nan_to_num(C60[i], nan=-9), np.nan_to_num(C20[i], nan=-9)
        cand = set(np.argpartition(-r60, 40)[:40]) | set(np.argpartition(-r20, 20)[:20])
        same = [j for j in by_em.get(em.get(c), []) if j != i]
        cand |= set(sorted(same, key=lambda j: -r60[j])[:15])
        lu = LU.get(c, {})
        cand |= {idx[x] for x, _ in sorted(lu.items(), key=lambda kv: -(kv[1][0] + 0.25 * kv[1][1]))[:30] if x in idx}
        mine = RC.get(c, [])
        for k in mine:
            cand |= {idx[x] for x in by_rules.get(k[1], ()) if x in idx and x != c}
        cand.discard(i)
        w = dict(TOPO_W)
        if c not in lu_seen:
            w["lu"] = w["old"] = 0.0
        if not mine:
            w["rules"] = 0.0
        wsum = sum(w.values()) or 1.0
        nb = []
        for j in cand:
            src, a, b = [], float(C60[i, j]), float(C20[i, j])
            if a >= 0.3:
                src.append("相关60")
            if b >= 0.4:
                src.append("相关20")
            if em.get(c) and em.get(codes[j]) == em[c]:
                src.append("同行业")
            if sw.get(c) and sw.get(codes[j]) == sw[c]:
                src.append("同申万")
            sc = con.get(c, set()) & con.get(codes[j], set())
            if sc:
                src.append("同概念:" + "/".join(sorted(sc)[:2]))
            s_stat = max(0.0, min(1.0, max(x for x in (a, b, 0.0) if x == x)))
            if any(t in src for t in ("同行业", "同申万")) or any(t.startswith("同概念") for t in src):
                s_stat = max(s_stat, 0.35)
            e = lu.get(codes[j])
            s_lu, s_old, lab_lu = (_lu_s(e[0]), 1 - np.exp(-e[1] / 2.0), max(e[2], key=e[2].get)) if e else (0.0, 0.0, None)
            if e and e[0] > 0:
                src.append(f"涨停共振:{lab_lu}")
            elif e:
                src.append(f"早期涨停共振:{lab_lu}")
            theirs = RC.get(codes[j], [])
            s_r, lab_r = 0.0, None
            for k in mine:
                for k2 in theirs:
                    v = 1.0 if k == k2 else 0.7 if k[1] == k2[1] else 0.35 if k[0] == k2[0] else 0.0
                    if v > s_r:   # 10/21 13:2x 用户: 簇名到最细一级(大类 > 子赛道 > 组); 只同大类时记邻居自己的子赛道, 不再停在"AI 硬件"
                        g = k2[2].split(":", 1)[1] if ":" in k2[2] else ""
                        s_r, lab_r = v, (f"{k2[0]}>{k2[1]}" + (f">{g}" if v == 1.0 and g else ""))
            if s_r:
                src.append(f"rules:{lab_r.split('>', 1)[1] if '>' in lab_r else lab_r}")
            if not src:
                continue
            sc = (w["lu"] * s_lu + w["rules"] * s_r + w["stat"] * s_stat + w["old"] * s_old) / wsum
            nb.append({"c": codes[j], "n": uni[syms[j]], "r60": round(a, 2) if a == a else None, "r20": round(b, 2) if b == b else None,
                       "src": src, "conf": round(sc, 3), "s": {"lu": round(s_lu, 2), "rules": round(s_r, 2), "stat": round(s_stat, 2), "old": round(s_old, 2)},
                       "_lab": {"lu": lab_lu if e and e[0] > 0 else None, "rules": lab_r, "stat": em.get(c) if s_stat >= 0.35 and em.get(codes[j]) == em.get(c) else None, "old": lab_lu if e else None}})
        nb.sort(key=lambda x: -x["conf"])
        lab = {}
        for x in nb[:30]:   # 主簇 / 次簇 = 邻居按来源贡献给各自的簇名加分, 取前两名
            for k, nmk in x.pop("_lab").items():
                if nmk:
                    lab[nmk] = lab.get(nmk, 0.0) + w[k] * x["s"][k] / wsum
        for x in nb[30:]:
            x.pop("_lab", None)
        clus = sorted(lab.items(), key=lambda kv: -kv[1])
        own = [f"{k[0]}>{k[1]}" + (f">{k[2].split(':', 1)[1]}" if ":" in k[2] else "") for k in mine]
        if own:   # 本票在 rules.md 里有归属: 主簇 = 自己最细的那级; 次簇 = 邻居加分最高、且不同子赛道的簇
            sec0 = own[0].split(">")[1]
            clus = [(own[0], 9.0)] + [(k, v) for k, v in clus if (k.split(">")[1] if ">" in k else k) != sec0]
        man = {k: v for k, v in (MAN.get(c) or {}).items()}
        neg = [{"c": codes[j], "n": uni[syms[j]], "r60": round(float(C60[i, j]), 2)} for j in np.argsort(r60 + (r60 == -9) * 99)[:NEG]
               if C60[i, j] <= -0.6 and C20[i, j] <= -0.45]   # 5000 只两两比 + 扣大盘后大小盘风格天然反向, −0.45 还有八成票命中(10/19 实测) → 只留极端的
        names = f"{em.get(c) or ''} {sw.get(c) or ''}"
        fut = [f for pat, fs in FUT_MAP if re.search(pat, names) for f in fs]
        fut = list(dict.fromkeys(fut + imem.get(c, [])))
        out.append({"c": c, "n": uni[syms[i]], "ind": em.get(c), "sw": sw.get(c), "fut": fut, "nb": nb[:TOP], "neg": neg,
                    "main": clus[0][0] if clus else None, "sub": clus[1][0] if len(clus) > 1 and clus[1][1] >= 0.1 else None,   # 次簇证据太弱(<0.1)不写, 宁缺 "clus": [[k, round(v, 3)] for k, v in clus[1:6]], "w": {k: round(v / wsum, 3) for k, v in w.items()},
                    **({"manual": man} if man else {})})
    return out, dates


_CACHE = {}


def load(code, D=None, strict=False):
    """strict=True 只取 D 之前的(盘中 / 回放用: D 当晚的拓扑含 D 收盘, 不偷看)"""
    D = D or dt.date.today().isoformat()
    fs = sorted(p for p in MKT.glob("2026-*/topology.jsonl") if (p.parent.name < D if strict else p.parent.name <= D))
    if not fs:
        return None
    f = fs[-1]
    if f not in _CACHE:
        _CACHE.clear()
        _CACHE[f] = {}
        for l in f.open(encoding="utf-8"):
            r = json.loads(l)
            _CACHE[f][r["c"]] = r
    return _CACHE[f].get(str(code))


def line(code, D=None, k=5, strict=False):
    """给模型 / 盯盘的一行文字: 行业 + 前 k 邻居(来源) + 期货; 没有 = 空串
    跷跷板不打出来: 扣大盘后大小盘风格天然反向, 具体到"哪只票"多半是噪音(10/19 实测牧原 → 富信科技/卓郎智能), 只留在数据里"""
    r = load(code, D, strict)
    if not r:
        return ""
    nb = " ".join(f"{x['n']}({'+'.join(s[:3] if s.startswith('同概念') else s for s in x['src'][-3:])})" for x in r["nb"][:k])
    man = "; ".join(f"{k}: {'/'.join(v)}" for k, v in (r.get("manual") or {}).items())
    return (f"拓扑(参考, 不是买卖信号): 主簇 {r.get('main') or '-'} / 次簇 {r.get('sub') or '-'} | 行业 {r.get('ind') or '-'} / {r.get('sw') or '-'} | 邻居 {nb or '-'} | 期货 {'/'.join(r['fut']) or '-'}"
            + (f" | 人工标注 {man}" if man else ""))


def brief(codes, D, k=3):
    """给 paper 链 04/06 的紧凑块: 每只(持仓 / 候选)一行 = 行业 | 前 k 邻居(昨日涨跌) | 期货; 只用 D 之前的拓扑和日线(不偷看)"""
    days = sorted(p.parent.name for p in MKT.glob("2026-*/kline_day.jsonl") if p.parent.name < D)
    rows = {}
    for c in codes:
        r = load(c, D, strict=True)
        if r:
            rows[c] = r
    if not rows:
        return []
    want = {x["c"] for r in rows.values() for x in r["nb"][:k]} | set(rows)
    pct = {}
    if days:
        for l in (MKT / days[-1] / "kline_day.jsonl").open(encoding="utf-8"):
            s = l[13:19] if l.startswith('{"symbol":"') else ""   # {"symbol":"sz002714",…
            if s in want:
                j = json.loads(l)
                if j.get("preClose"):
                    pct[s] = (j["close"] / j["preClose"] - 1) * 100
    f = lambda c: f"{pct[c]:+.1f}%" if c in pct else "?"   # noqa: E731
    return [f"{c} {r['n'].replace(' ', '')}({f(c)}): {r.get('ind') or '-'} | 邻居 " + " ".join(f"{x['n'].replace(' ', '')}({f(x['c'])})" for x in r["nb"][:k])
            + (f" | 期货 {'/'.join(r['fut'][:3])}" if r["fut"] else "") for c, r in rows.items()]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--show")
    a = ap.parse_args()
    if a.show:
        print(json.dumps(load(a.show, a.date), ensure_ascii=False, indent=1))
        print(line(a.show, a.date))
        return
    rows, dates = build(a.date)
    dd = MKT / a.date
    dd.mkdir(exist_ok=True)
    tmp = dd / "topology.jsonl.tmp"
    tmp.write_text("\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows) + "\n", encoding="utf-8")
    tmp.replace(dd / "topology.jsonl")
    multi = sum(1 for r in rows if r["nb"] and any(not s.startswith("相关") for s in r["nb"][0]["src"]))
    print(f"topology {a.date}: {len(rows)} 只(窗口 {dates[0]}~{dates[-1]} {len(dates)} 日), 首邻居有行业/概念印证 {multi} 只, 有跷跷板 {sum(1 for r in rows if r['neg'])} 只,有期货映射 {sum(1 for r in rows if r['fut'])} 只 → {(dd / 'topology.jsonl').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
