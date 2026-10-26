# -*- coding: utf-8 -*-
"""board_knowledge.py — 炸板 / 回封知识卡的统计部分(10/22 晚用户令; 零 token, 只读本地)

数据: downloads/quotes/stock/minute_path/<日>.jsonl(通达信历史分时, 每分钟价 + 量, 240 点; 第一期 937 只 × 30 天: 刘忆青 / 芷影历史票 + 近 30 日涨停过 + UP 提到)
      + 行情库日线(当日开高低收、次日开高收、上证涨跌、全市场涨停家数)
板型(用户 10/22 定义): 一字 / T字(一字开板后回封) / 厂字(开盘后一路拉到涨停、封住后不再开) / 烂板回封(开板 ≥2 次最后封住) / 回封(开 1 次封住)
      / 炸板不回封(早盘 = 首封 < 10:30、盘中、尾盘 = 首封 ≥ 14:00) / 天地 / 地天 / 天地天 / 地天地(触及也算; 顺序用分钟路径, 触及用日线高低)
开板事件: 封住后价格离开涨停价 → 记 开板时刻 / 第几次开板 / 开板最深 / 开板时长 / 连板高度 / 上证 / 涨停家数 → 结果: 有没有回封、收盘封没封;
      "开板时接(开板那一分钟的价) → 当天收盘 / 次日最高 / 次日收盘"相对接的价
局限(写进报告): 分钟路径只有每分钟价格, 没有分钟内高低 → "开板最深"偏浅、1 分钟内开板又回封会漏; 封单量 / 漏单只有 3 秒盘口(10/19 起, 只覆盖盯盘名单)才有, 这里不算
产物: docs/research/board_reseal_20261023.md
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/test/board_knowledge.py
"""
import collections
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
MP = ROOT / "downloads" / "quotes" / "stock" / "minute_path"
OUT = ROOT / "docs" / "research" / "board_reseal_20261023.md"
TM = [f"{9 + (i + 31) // 60:02d}:{(i + 31) % 60:02d}" if i < 120 else f"{13 + (i - 119) // 60:02d}:{(i - 119) % 60:02d}" for i in range(240)]


def lim_of(code, name=""):
    if "ST" in (name or ""):
        return 0.05
    return 0.2 if code.startswith(("300", "301", "688", "689")) else 0.1


def zt(pc, lim):
    return round(pc * (1 + lim) + 1e-9, 2)


def dt_(pc, lim):
    return round(pc * (1 - lim) + 1e-9, 2)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    write(*collect())


def collect():
    """→ (types 板型计数, opens 开板事件列表, cases, days); 10/24 拆出来给事件本体(scripts/ontology)复用"""
    import manual_backfill as mb
    cur = mb.db().cursor()
    cur.execute("use investment_market")
    files = sorted(MP.glob("*.jsonl"))
    days = [f.stem for f in files]
    cur.execute("select symbol, name from security_master where sec_type='STOCK'")
    NM = {s[2:]: n or "" for s, n in cur.fetchall()}
    d0 = days[0]
    cur.execute("select symbol, trade_date, open, high, low, close, pre_close from kline_day where is_deleted=0 and trade_date >= date_sub(%s, interval 20 day) "
                "and (symbol like 'sh6%%' or symbol like 'sz0%%' or symbol like 'sz3%%' or symbol='sh000001')", (d0,))
    K = collections.defaultdict(dict)
    for s, d, o, h, l, c, pc in cur.fetchall():
        if o and c and pc:
            K[s[2:] if s != "sh000001" else "IDX"][str(d)] = (float(o), float(h), float(l), float(c), float(pc))
    ztn = collections.Counter()
    for code, dd in K.items():
        if code == "IDX":
            continue
        lim = lim_of(code, NM.get(code))
        for d, (o, h, l, c, pc) in dd.items():
            if c >= zt(pc, lim) - 0.005:
                ztn[d] += 1
    alld = sorted({d for dd in K.values() for d in dd})

    def height(code, d):
        """今天之前连续封死涨停几天(今天是第 n+1 板)"""
        dd, n = K.get(code, {}), 0
        lim = lim_of(code, NM.get(code))
        prev = [x for x in alld if x < d]
        for x in reversed(prev):
            r = dd.get(x)
            if r and r[3] >= zt(r[4], lim) - 0.005:
                n += 1
            else:
                break
        return n

    def nxt(code, d):
        later = [x for x in alld if x > d and x in K.get(code, {})]
        return K[code][later[0]] if later else None

    types, opens, cases, rebound = collections.Counter(), [], [], []
    for f in files:
        D = f.stem
        idx = K["IDX"].get(D)
        mkt = ((idx[3] / idx[4] - 1) * 100) if idx else 0
        for l in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(l)
            code, p = r["code"], r["p"]
            if code[:1] not in ("0", "3", "6") or "ST" in NM.get(code, "") or len(p) < 240:
                continue
            k = K.get(code, {}).get(D)
            if not k:
                continue
            o, h, lo, c, pc = k
            lim = lim_of(code, NM.get(code))
            up, dn = zt(pc, lim), dt_(pc, lim)
            touch_up, touch_dn = h >= up - 0.005, lo <= dn + 0.005
            if not (touch_up or touch_dn):
                continue
            sealed = [x >= up - 0.005 for x in p]
            down = [x <= dn + 0.005 for x in p]
            close_sealed = c >= up - 0.005
            # 板型
            ev = []   # 涨停 / 跌停 触及顺序
            for i in range(240):
                tag = "天" if sealed[i] else "地" if down[i] else None
                if tag and (not ev or ev[-1] != tag):
                    ev.append(tag)
            seq = "".join(ev) or ("天" if touch_up else "地")
            if touch_up and touch_dn and len(seq) >= 2:
                typ = {"天地": "天地", "地天": "地天", "天地天": "天地天", "地天地": "地天地"}.get(seq[:3] if len(seq) >= 3 else seq, seq[:3] + "…")
            elif not touch_up:
                typ = "跌停(没碰涨停)"
            else:
                n_open = sum(1 for i in range(1, 240) if sealed[i - 1] and not sealed[i])
                first = next((i for i in range(240) if sealed[i]), None)
                if o >= up - 0.005 and all(sealed) and close_sealed:
                    typ = "一字"
                elif o >= up - 0.005 and close_sealed:
                    typ = "T字"
                elif close_sealed and n_open == 0:
                    typ = "厂字(一路拉板)"
                elif close_sealed and n_open == 1:
                    typ = "回封(开 1 次)"
                elif close_sealed:
                    typ = "烂板回封(开 ≥2 次)"
                else:
                    t0 = TM[first] if first is not None else "盘中(分钟路径没捕到)"
                    typ = "炸板不回封·早盘(首封<10:30)" if t0 < "10:30" else "炸板不回封·尾盘(首封≥14:00)" if t0 >= "14:00" else "炸板不回封·盘中"
            types[typ] += 1
            # 10/25 用户: 反包板 = 前一天跌 ≤ −5% / 炸板 / 跌停, 今天收盘封住涨停(和上面的板型叠加统计, 不改板型分布)
            if close_sealed:
                prv = [x for x in alld if x < D and x in K.get(code, {})]
                if prv:
                    po, ph, pl, pcl, ppc = K[code][prv[-1]]
                    why = ("前一天跌停" if pcl <= dt_(ppc, lim) + 0.005 else "前一天炸板" if ph >= zt(ppc, lim) - 0.005 and pcl < zt(ppc, lim) - 0.005
                           else "前一天跌 ≤−5%" if (pcl / ppc - 1) <= -0.05 else None)
                    if why:
                        nd0 = nxt(code, D)
                        rebound.append({"D": D, "code": code, "name": NM.get(code, ""), "why": why, "typ": typ, "height": height(code, D) + 1,
                                        "next_open": ((nd0[0] / c - 1) * 100) if nd0 else None, "next_hi": ((nd0[1] / c - 1) * 100) if nd0 else None,
                                        "next_co": ((nd0[3] / c - 1) * 100) if nd0 else None, "next_zt": (nd0[3] >= zt(c, lim) - 0.005) if nd0 else None})
            # 开板事件
            hgt = height(code, D)
            nd = nxt(code, D)
            i, k_open = 0, 0
            while i < 240:
                if i > 0 and sealed[i - 1] and not sealed[i]:
                    k_open += 1
                    j = i
                    while j < 240 and not sealed[j]:
                        j += 1
                    seg = p[i:j]
                    depth = (min(seg) / up - 1) * 100
                    ent = p[i]
                    deep = {}   # 盘中能用的口径(不偷看): 开板后价格跌到离涨停 x% 时接 → 之后能不能封回 / 当天收盘 / 次日
                    for x in (2, 3, 5, 7):
                        px = up * (1 - x / 100)
                        hit = next((m for m in range(i, j) if p[m] <= px + 1e-9), None)
                        if hit is not None:
                            deep[x] = {"code": code, "name": NM.get(code, ""), "D": D, "ret_close": (c / px - 1) * 100, "next_hi": ((nd[1] / px - 1) * 100) if nd else None, "next_co": ((nd[3] / px - 1) * 100) if nd else None,
                                       "resealed": j < 240, "close_sealed": close_sealed}
                    e = {"D": D, "code": code, "name": NM.get(code, ""), "t": TM[i], "k": k_open, "depth": depth, "dur": j - i, "resealed": j < 240,
                         "close_sealed": close_sealed, "height": hgt + 1, "mkt": mkt, "ztn": ztn.get(D, 0), "typ": typ,
                         "ret_close": (c / ent - 1) * 100, "next_hi": ((nd[1] / ent - 1) * 100) if nd else None, "next_co": ((nd[3] / ent - 1) * 100) if nd else None, "deep": deep}
                    opens.append(e)
                    i = j
                else:
                    i += 1
            if typ.startswith(("T字", "回封", "烂板", "炸板", "天地", "地天")) and D >= "2026-10-19":
                cases.append((D, code, NM.get(code, ""), typ, hgt + 1, ztn.get(D, 0), round(mkt, 2), (nd and round((nd[3] / c - 1) * 100, 2))))
    return types, opens, cases, days, rebound


def pct(xs, f):
    xs = [x for x in xs if f(x) is not None]
    return f"{sum(1 for x in xs if f(x)) / len(xs):.0%}" if xs else "-"


def med(xs, k):
    """10/24 用户令: 不能只报中位 → 一格里写 中位 / 均值 / P10 / 最差(带票名日期)"""
    v = sorted(((x[k], x) for x in xs if x.get(k) is not None), key=lambda p: p[0])
    if not v:
        return "-"
    vals = [a for a, _ in v]
    w = v[0][1]
    wt = f"{w.get('code', '')}{w.get('name', '')} {w.get('D', '')}".strip()
    return f"中{vals[len(vals) // 2]:+.2f} 均{sum(vals) / len(vals):+.2f} P10 {vals[int(len(vals) * .1)]:+.2f} 最差{vals[0]:+.2f}({wt})"


def grp(opens, key, order=None):
    G = collections.defaultdict(list)
    for e in opens:
        G[key(e)].append(e)
    ks = order or sorted(G)
    rows = []
    for k_ in ks:
        xs = G.get(k_) or []
        if not xs:
            continue
        rows.append(f"| {k_} | {len(xs)} | {pct(xs, lambda e: e['resealed'])} | {pct(xs, lambda e: e['close_sealed'])} | {med(xs, 'ret_close')} | {med(xs, 'next_hi')} | {med(xs, 'next_co')} |")
    return ["| 分组 | 开板次数 | 开板后又封回(当时) | 收盘封住 | 开板时接 → 当天收盘 | → 次日最高 | → 次日收盘 |", "|---|---|---|---|---|---|---|"] + rows


def write(types, opens, cases, days, rebound=()):
    def dep(e):
        d = -e["depth"]
        return "开 ≤2%" if d <= 2 else "开 2~4%" if d <= 4 else "开 4~7%" if d <= 7 else "开 >7%"

    def tm(e):
        return "早盘 <10:00" if e["t"] < "10:00" else "上午 10:00~11:30" if e["t"] <= "11:30" else "下午 13:00~14:00" if e["t"] < "14:00" else "尾盘 ≥14:00"
    L = [f"# 炸板 / 回封知识卡 · 统计部分（{days[0]} ~ {days[-1]}，{len(days)} 个交易日；零 token）", "",
         "数据: 通达信历史分时（每分钟价 + 量）第一期 937 只 × 30 天（刘忆青 / 芷影历史票 + 近 30 日涨停过 + UP 提到）+ 行情库日线；脚本 `scripts/test/board_knowledge.py`", "",
         "**局限**: 只有每分钟价格、没有分钟内高低 → \"开板最深\"偏浅、1 分钟内开板又回封的会漏；封单量 / 漏单只有 3 秒盘口（10/19 起、只覆盖盯盘名单），这里没算；样本是\"我们关注的票\"不是全市场 → 结论偏向导师常做的那类票", "",
         "## 1. 板型分布（触及过涨停或跌停的票-日）", "", "| 板型 | 次数 |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in types.most_common()]
    L += ["", f"### 1.1 反包板（10/25 加: 前一天跌 ≤−5% / 炸板 / 跌停, 今天收盘封住涨停; 和上表叠加, 不改板型分布）共 {len(rebound)} 次", "",
          "| 前一天 | 次数 | 今天板型(前 3) | 次日继续涨停 | 次日开盘(相对今天收盘) | 次日最高 | 次日收盘 |", "|---|---|---|---|---|---|---|"]
    for w in ("前一天跌停", "前一天炸板", "前一天跌 ≤−5%"):
        xs = [e for e in rebound if e["why"] == w]
        if xs:
            tt = collections.Counter(e["typ"] for e in xs).most_common(3)
            L.append(f"| {w} | {len(xs)} | {' / '.join(f'{k} {v}' for k, v in tt)} | {pct(xs, lambda e: e['next_zt'])} | {med(xs, 'next_open')} | {med(xs, 'next_hi')} | {med(xs, 'next_co')} |")
    if rebound:
        L.append(f"| 合计 | {len(rebound)} | — | {pct(rebound, lambda e: e['next_zt'])} | {med(rebound, 'next_open')} | {med(rebound, 'next_hi')} | {med(rebound, 'next_co')} |")
    L += ["", f"## 2. 开板后会不会回封（共 {len(opens)} 次开板；\"开板时接\" = 开板那一分钟的价格买进，近似你说的\"开板按卖二接\"）", ""]
    L += ["### 2.1 按开板深度（开板期间最低离涨停价多远）", ""] + grp(opens, dep, ["开 ≤2%", "开 2~4%", "开 4~7%", "开 >7%"])
    L += ["", "### 2.2 按连板高度（今天是第几板）", ""] + grp(opens, lambda e: "首板" if e["height"] == 1 else "二板" if e["height"] == 2 else "三板+", ["首板", "二板", "三板+"])
    L += ["", "### 2.3 按开板时刻", ""] + grp(opens, tm, ["早盘 <10:00", "上午 10:00~11:30", "下午 13:00~14:00", "尾盘 ≥14:00"])
    L += ["", "### 2.4 按第几次开板", ""] + grp(opens, lambda e: "第 1 次" if e["k"] == 1 else "第 2 次" if e["k"] == 2 else "第 3 次+", ["第 1 次", "第 2 次", "第 3 次+"])
    L += ["", "### 2.5 按大盘（上证当天涨跌）", ""] + grp(opens, lambda e: "上证 ≥+0.5%" if e["mkt"] >= 0.5 else "上证 ≤−0.5%" if e["mkt"] <= -0.5 else "上证平", ["上证 ≥+0.5%", "上证平", "上证 ≤−0.5%"])
    L += ["", "### 2.6 按当天全市场涨停家数（情绪）", ""] + grp(opens, lambda e: "涨停 <30" if e["ztn"] < 30 else "30~60" if e["ztn"] < 60 else "60~100" if e["ztn"] < 100 else "≥100", ["涨停 <30", "30~60", "60~100", "≥100"])
    L += ["", "### 2.7 开板已经持续多久还没回封（盘中能用的条件概率：开了 X 分钟还没封回，之后还能不能封）", "",
          "| 已开板 | 样本 | 之后还能封回 | 收盘封住 |", "|---|---|---|---|"]
    for x in (1, 3, 5, 10, 20, 30):
        xs = [e for e in opens if e["dur"] >= x]
        if xs:
            L.append(f"| ≥{x} 分钟 | {len(xs)} | {pct(xs, lambda e: e['resealed'])} | {pct(xs, lambda e: e['close_sealed'])} |")
    L += ["", "### 2.8 盘中能用的口径（不偷看）：开板后价格跌到离涨停 x% 时接（炸板接单的 floor 怎么定看这张）", "",
          "| 跌到离涨停 | 样本 | 之后还能封回 | 收盘封住 | 接 → 当天收盘 | → 次日最高 | → 次日收盘 |", "|---|---|---|---|---|---|---|"]
    for x in (2, 3, 5, 7):
        xs = [e["deep"][x] for e in opens if x in e["deep"]]
        if xs:
            L.append(f"| −{x}% | {len(xs)} | {pct(xs, lambda e: e['resealed'])} | {pct(xs, lambda e: e['close_sealed'])} | {med(xs, 'ret_close')} | {med(xs, 'next_hi')} | {med(xs, 'next_co')} |")
    L += ["", "> 读法: 2.1 \"按开板深度\"是事后分组(要等开完才知道开了多深, 有幸存者偏差: 开得浅的里面多半是已经封回的), 只用来看规律; 盘中挂炸板接单用 2.7(已经开了多久)和 2.8(已经跌到哪)"]
    L += ["", f"## 3. 10/19 以来的事件清单（{len(cases)} 个；逐笔复盘卡的底稿，封单 / 题材 / 龙虎榜等字段待补）", "",
          "| 日期 | 代码 | 名称 | 板型 | 第几板 | 当天涨停家数 | 上证% | 次日收盘相对当天收盘 |", "|---|---|---|---|---|---|---|---|"]
    L += [f"| {a} | {b} | {c} | {d} | {e} | {f} | {g} | {'-' if h is None else f'{h:+.2f}%'} |" for a, b, c, d, e, f, g, h in sorted(cases)[-60:]]
    L += ["", "## 4. 待你点头才写进 skill 的候选规则（先放这里，不进 market-skill / 导师 skill）", "",
          "- 看上面 2.1 / 2.7：开板越浅、开板越短越容易封回；用数字定\"接\"的深度下限和\"等多久不封就放弃\"",
          "- 看 2.2 / 2.6：高度和情绪对回封率的影响，决定炸板接单只在哪类票 / 哪种情绪下用",
          "- 置信：样本是关注票（不是全市场），**低~中**；每格已带 中位 / 均值 / P10 / 最差案例（10/24 起）"]
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:60]))


if __name__ == "__main__":
    main()
