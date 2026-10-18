# -*- coding: utf-8 -*-
"""build_panel.py — 不吃土豆0 竞价选债逆向: 候选池面板构建(10/18 建; 零 token, 零网络, 只读库)

对他每个"首笔=09:25 竞价买"的日子 D, 列出 D 日全部在交易的转债作为候选, 每只给出 09:25 前可知特征:
  转债: T-1 收盘(价位) / T-1 涨幅 / T-1 振幅 / T-1 成交额(代理)+当日排名 / 5 日涨幅 / 5 日均额排名 / 上市天数 / D 开盘缺口(09:25 竞价结果)
  正股: T-1 涨幅 / T-1 是否涨停 / 连板数 / T-1 成交额 / D 开盘缺口 / D 是否一字(竞价)涨停
  他自己: 近 N 日是否做过该债(任意通道) / 距上次做的交易日数 / 上一个竞价票 / 最近一笔交易的债 / 近 5 日该债 RT 数 / 上次该债盈亏
数据源(只读): 行情库 kline_day(sh11*/sz12* 转债 + 正股) ∪ downloads/quotes/cb/kline/<code>.json(他做过的 51 只, 含已退市)
  转债→正股: 51 只用东财 meta CONVERT_STOCK_CODE; 其余用"名称前两字匹配同交易所股票 + 日收益相关系数最高"推断(在 51 只上自检)
已知偏差(报告必写): 行情库转债只有"现存"券(已退市的不在库), 而他做过的已退市券有文件 → 候选池对他的票有幸存者富集; 另给"仅库内"口径。
产物: scripts/tzzb/tudou_select/cache/panel.json
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/tudou_select/build_panel.py
"""
import json, re, sys, statistics as st
from collections import defaultdict, Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts" / "tzzb"))
sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
META = ROOT / "downloads" / "quotes" / "cb" / "meta" / "RPT_BOND_CB_LIST_tudou51_20261017.json"
KDIR = ROOT / "downloads" / "quotes" / "cb" / "kline"
BEG = "2025-10-01"


def cb_sym(code):
    return ("sh" if code.startswith("11") else "sz") + code


def stk_sym(code):
    return ("sh" if code.startswith(("6", "9")) else "sz") + code


def stk_lim(code, name):
    if name and "ST" in name.upper():
        return 0.05
    return 0.2 if code.startswith(("300", "301", "688", "689")) else 0.1


def load_db():
    from kline_db import db
    c = db()
    cur = c.cursor()
    cur.execute("select trade_date from kline_day where symbol='sh000001' and trade_date>=%s order by trade_date", (BEG,))
    cal = [r[0].isoformat() for r in cur.fetchall()]
    cur.execute("select symbol, trade_date, open, high, low, close, pre_close, volume, amount from kline_day "
                "where (symbol like 'sh11%%' or symbol like 'sz12%%') and trade_date>=%s order by symbol, trade_date", (BEG,))
    cb = defaultdict(dict)
    for s, d, o, h, l, cl, pc, v, a in cur.fetchall():
        o, h, l, cl = float(o or 0), float(h or 0), float(l or 0), float(cl or 0)
        if cl <= 0:
            continue
        amt = float(a) if a else float(v or 0) * cl          # tencent 源 amount 为空, volume 单位=张 → 额≈张×收盘
        cb[s[2:]][d.isoformat()] = {"o": o, "h": h, "l": l, "c": cl, "amt": amt}
    cur.execute("select symbol, name from security_master where sec_type='CB'")
    cbname = {s[2:]: n for s, n in cur.fetchall()}
    cur.execute("select symbol, name from security_master where sec_type='STOCK'")
    stkname = {s: n for s, n in cur.fetchall()}
    c.close()
    return cal, cb, cbname, stkname


def load_stocks(syms):
    from kline_db import db
    c = db()
    cur = c.cursor()
    out = defaultdict(dict)
    syms = sorted(syms)
    for i in range(0, len(syms), 300):
        part = syms[i:i + 300]
        ph = ",".join(["%s"] * len(part))
        cur.execute(f"select symbol, trade_date, open, high, low, close, pre_close, amount from kline_day where symbol in ({ph}) and trade_date>=%s", (*part, BEG))
        for s, d, o, h, l, cl, pc, a in cur.fetchall():
            if not cl:
                continue
            out[s][d.isoformat()] = {"o": float(o or 0), "h": float(h or 0), "l": float(l or 0), "c": float(cl), "pc": float(pc) if pc else None, "amt": float(a or 0)}
    c.close()
    return out


def rets(series, cal):
    ds = [d for d in cal if d in series]
    return {ds[i]: series[ds[i]]["c"] / series[ds[i - 1]]["c"] - 1 for i in range(1, len(ds))}


def corr(a, b):
    ks = [k for k in a if k in b]
    if len(ks) < 30:
        return None, len(ks)
    x = [a[k] for k in ks]; y = [b[k] for k in ks]
    try:
        return st.correlation(x, y), len(ks)
    except st.StatisticsError:
        return None, len(ks)


def cb_prefix(name):
    n = re.sub(r"^(N|XD|XR|DR)", "", name or "")
    m = re.match(r"([一-龥A-Za-z]{2})", n)
    return m.group(1) if m else None


def main():
    from tudou_deep import load_legs, round_trips, channel, phase
    cal, cbdb, cbname, stkname = load_db()
    raw = json.loads(META.read_text(encoding="utf-8"))["result"]["data"]
    meta = {x["SECURITY_CODE"]: {"reason": str(x.get("EXECUTE_REASON_SH") or ""), "notice": (x.get("NOTICE_DATE_SH") or "")[:10] or None,
                                 "delist": (x.get("DELIST_DATE") or "")[:10] or None, "stock": x.get("CONVERT_STOCK_CODE"),
                                 "conv0": x.get("INITIAL_TRANSFER_PRICE"), "name": x.get("SECURITY_NAME_ABBR")} for x in raw}
    # ---- 合并转债日线: 文件(他做过的 51 只, 含退市)优先, 库补其余 ----
    cb = {}
    src = {}
    for f in KDIR.glob("*.json"):
        j = json.loads(f.read_text(encoding="utf-8"))
        cb[f.stem] = {d: {"o": v["o"], "h": v["h"], "l": v["l"], "c": v["c"], "amt": v.get("amt") or v.get("vol", 0) * 10 * v["c"]} for d, v in j.items() if d >= BEG and v.get("c")}
        src[f.stem] = "file"
    for code, s in cbdb.items():
        if code not in cb:
            cb[code] = s; src[code] = "db"
        else:
            for d, v in s.items():          # 文件止于抓取日, 之后的日子用库补
                cb[code].setdefault(d, v)
    names = {c: (meta.get(c, {}).get("name") or cbname.get(c) or c) for c in cb}
    # ---- 转债→正股映射: meta 优先; 否则 名称子序列匹配(前两字按序出现在股票名里)+日收益相关 ≥0.35, 再否则 全同所股票相关 ≥0.6 且领先第二名 ≥0.15 ----
    import numpy as np
    pool = {s: re.sub(r"^(\*?ST|XD|XR|DR|N|C)", "", n or "") for s, n in stkname.items() if (s[:3] == "sh6") or (s[:3] in ("sz0", "sz3"))}
    stk = load_stocks(set(pool))
    syms = sorted(stk)
    T = len(cal)
    def vec(series):
        v = np.full(T, np.nan)
        prev = None
        for i, d in enumerate(cal):
            if d in series:
                if prev is not None and i - prev == 1:
                    v[i] = series[d]["c"] / series[cal[prev]]["c"] - 1
                prev = i
        return v
    S = np.array([vec(stk[x]) for x in syms])
    S = np.clip(S, -0.25, 0.25)
    exa = np.array([x[:2] for x in syms])
    def subseq(p, n):
        i = 0
        for ch in n:
            if i < len(p) and ch == p[i]:
                i += 1
        return i == len(p)
    mapping, mcheck = {}, []
    for c in cb:
        ex = "sh" if c.startswith("11") else "sz"
        cv = np.clip(vec(cb[c]), -0.25, 0.25)
        m = ~np.isnan(cv)[None, :] & ~np.isnan(S) & (exa == ex)[:, None]
        n = m.sum(1)
        X = np.where(m, S, 0.0); Y = np.where(m, cv[None, :], 0.0)
        with np.errstate(invalid="ignore", divide="ignore"):
            mx = X.sum(1) / n; my = Y.sum(1) / n
            cov = (X * Y).sum(1) / n - mx * my
            vx = (X * X).sum(1) / n - mx * mx; vy = (Y * Y).sum(1) / n - my * my
            r = cov / np.sqrt(vx * vy)
        r = np.where(n >= 15, r, np.nan)
        p = cb_prefix(names[c]) or ""
        nm = [i for i, x in enumerate(syms) if x[:2] == ex and p and subseq(p, pool[x]) and not np.isnan(r[i])]
        inferred, how, rc = None, "none", None
        if nm:
            i = max(nm, key=lambda i: r[i])
            if r[i] >= 0.35:
                inferred, how, rc = syms[i], "name+corr", float(r[i])
        if inferred is None and np.isfinite(r).any():
            rr = np.where(np.isnan(r), -9, r)
            o = np.argsort(-rr)
            if rr[o[0]] >= 0.6 and rr[o[0]] - rr[o[1]] >= 0.15:
                inferred, how, rc = syms[o[0]], "corr-only", float(rr[o[0]])
        true = stk_sym(meta[c]["stock"]) if c in meta and meta[c].get("stock") else None
        if true:
            mcheck.append((c, names[c], true, inferred, how, round(rc, 2) if rc else None))
        mapping[c] = {"stock": true or inferred, "how": "meta" if true else how, "corr": rc}
    ok = sum(1 for x in mcheck if x[2] == x[3]); miss = sum(1 for x in mcheck if x[3] is None)
    print(f"映射自检(51 只 meta): 推断正确 {ok}/{len(mcheck)}, 推断不出 {miss}, 推错 {len(mcheck) - ok - miss}")
    for x in mcheck:
        if x[2] != x[3]:
            print("  ", x)
    # ---- 他的历史 ----
    legs = load_legs()
    rts = round_trips(legs)
    for r in rts:
        r["channel"] = channel(r["buy_t"])
    by_day = defaultdict(list)
    for r in rts:
        by_day[r["d"]].append(r)
    days_he = sorted(by_day)
    first = {d: min(L, key=lambda r: r["buy_t"]) for d, L in by_day.items()}
    auc_days = [d for d in days_he if first[d]["channel"] == "竞价"]
    ci = {d: i for i, d in enumerate(cal)}
    # ---- 面板 ----
    panel = []
    for D in auc_days:
        if D not in ci:
            continue
        iD = ci[D]
        T1, T2 = cal[iD - 1], cal[iD - 2]
        pick = first[D]
        prior = [d for d in days_he if d < D]
        last_auc = next((first[d]["code"] for d in reversed(prior) if first[d]["channel"] == "竞价"), None)
        prev_day = prior[-1] if prior else None
        last_bond = max(by_day[prev_day], key=lambda r: r["buy_t"])["code"] if prev_day else None
        prev_first = first[prev_day]["code"] if prev_day else None
        # 他近 5 日各债 RT 数 / 名义额
        tr_last = {}
        n5 = Counter(); not5 = Counter(); pnl_last = {}
        for d in prior:
            k = iD - ci[d]
            for r in by_day[d]:
                tr_last[r["code"]] = k
                pnl_last[r["code"]] = r["pnl"]
                if k <= 5:
                    n5[r["code"]] += 1; not5[r["code"]] += r["notional"]
        cands = []
        amts1 = []
        for c, s in cb.items():
            if D not in s or T1 not in s or s[D]["o"] <= 0:
                continue
            amts1.append((s[T1]["amt"], c))
        amts1.sort(reverse=True)
        arank = {c: i + 1 for i, (_, c) in enumerate(amts1)}
        avg5 = []
        for _, c in amts1:
            s = cb[c]
            xs = [s[cal[iD - k]]["amt"] for k in range(1, 6) if cal[iD - k] in s]
            avg5.append((sum(xs) / len(xs), c))
        avg5.sort(reverse=True)
        a5rank = {c: i + 1 for i, (_, c) in enumerate(avg5)}
        for _, c in amts1:
            s = cb[c]
            b1, bD = s[T1], s[D]
            b2 = s.get(T2)
            first_bar = min(s)
            row = {"code": c, "name": names[c], "src": src[c], "in_db": c in cbdb,
                   "pc": b1["c"], "gap": bD["o"] / b1["c"] - 1,
                   "ret1": b1["c"] / b2["c"] - 1 if b2 else None,
                   "amp1": (b1["h"] - b1["l"]) / b2["c"] if b2 else None,
                   "amt1": b1["amt"], "arank1": arank[c], "arank5": a5rank[c],
                   "ret5": (b1["c"] / s[cal[iD - 6]]["c"] - 1) if cal[iD - 6] in s else None,
                   "age": sum(1 for d in s if d < D),
                   "list_after_beg": first_bar > BEG,
                   "he_k": tr_last.get(c), "he_n5": n5.get(c, 0), "he_not5": not5.get(c, 0), "he_pnl_last": pnl_last.get(c),
                   "is_last_auc": c == last_auc, "is_last_bond": c == last_bond, "is_prev_first": c == prev_first,
                   "map": mapping[c]["how"]}
            ss = mapping[c]["stock"]
            sv = stk.get(ss, {}) if ss else {}
            if ss and D in sv and T1 in sv:
                s1, sD = sv[T1], sv[D]
                s2 = sv.get(T2)
                pc1 = s1["pc"] or (s2["c"] if s2 else None)
                lim = stk_lim(ss[2:], stkname.get(ss))
                row["s_ret1"] = s1["c"] / pc1 - 1 if pc1 else None
                row["s_zt1"] = bool(pc1 and s1["c"] >= round(pc1 * (1 + lim), 2) - 0.005)
                nb = 0
                for k in range(1, 15):
                    dk, dk1 = cal[iD - k], cal[iD - k - 1]
                    if dk in sv and dk1 in sv and sv[dk]["c"] >= round((sv[dk]["pc"] or sv[dk1]["c"]) * (1 + lim), 2) - 0.005:
                        nb += 1
                    else:
                        break
                row["s_boards"] = nb
                row["s_amt1"] = s1["amt"]
                pcD = sD["pc"] or s1["c"]
                row["s_gap"] = sD["o"] / pcD - 1
                row["s_zt_open"] = sD["o"] >= round(pcD * (1 + lim), 2) - 0.005
                row["s_lim"] = lim
            if c in meta:
                ph, off = phase(meta, c, D, cal)
                row["phase"] = ph
            cands.append(row)
        panel.append({"d": D, "pick": pick["code"], "pick_name": pick["name"], "pick_pnl": pick["pnl"], "pick_sell_t": pick["sell_t"],
                      "last_auc": last_auc, "last_bond": last_bond, "prev_day": prev_day, "gap_days_prev": iD - ci[prev_day] if prev_day else None,
                      "n_cand": len(cands), "pick_in_db": pick["code"] in cbdb, "cands": cands})
    (HERE / "cache").mkdir(exist_ok=True)
    (HERE / "cache" / "panel.json").write_text(json.dumps({"mapping_check": mcheck, "mapping": mapping, "panel": panel,
                                                            "he_days": days_he, "first": {d: {"code": first[d]["code"], "ch": first[d]["channel"]} for d in days_he},
                                                            "he_codes_by_day": {d: sorted({r["code"] for r in by_day[d]}) for d in days_he}},
                                                           ensure_ascii=False), encoding="utf-8")
    print(f"竞价日 {len(panel)}; 候选数 中位 {st.median(p['n_cand'] for p in panel)}; 他的票在库内 {sum(p['pick_in_db'] for p in panel)}/{len(panel)}")
    print("映射方式分布(全部券):", Counter(m["how"] for m in mapping.values()))
    print("pick 在候选里:", sum(any(c['code'] == p['pick'] for c in p['cands']) for p in panel))


if __name__ == "__main__":
    main()
