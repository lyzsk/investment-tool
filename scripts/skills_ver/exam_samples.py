# -*- coding: utf-8 -*-
"""exam_samples.py — 规则体检的样本库: 把导师最近 N 个交易日的真实动作 + 当时情境变量整理成样本(只读, 零 token)

10/26 凌晨从 scripts/temp/distill_diag/build_samples.py(诊断 agent 写的)产品化: 截止日 / 天数参数化, 不依赖 scripts/temp,
加了不吃土豆0 的账户日样本(主做债 = 前 10 个交易日成交腿最多的转债, 不再写死澳弘)。
数据(全部只读; 业务库只发 SELECT, 连接抄 scripts/live/plan_review.py 的 db()):
  investment_tool.tzzb_record  bs_leg(逐笔成交) / position_snap / nav_day
  downloads/tzzb/<id>/day_positions.json   每日收盘仓位% + 浮盈(rate)
  skills/<id>-skill/persona/cases_auto.jsonl  买入打法 play / 熟票 / 卖出盈亏(只读)
  skills/<id>-skill/persona/fills_rt.jsonl    成交那一分钟的盘中状态
  investment_market.kline_day  日线(板态 / 开盘缺口 / 连板 / 箱体); downloads/market/<D>/kline_minute.jsonl(10/09 起)
  downloads/market/<D>/auction_live_open.json  09:24 虚拟撮合(10/12 起); downloads/quotes/cb/meta|kline  转债正股映射 / 转债日线兜底
样本三类(股票导师): pos=持仓日(前一交易日收盘持有的每只 × 当日) / open=新开仓 / day=账户日; 土豆: day=账户日(出不出手 / 首笔通道 ...)
字段"什么时候能知道"登记在 rule_dsl.FIELDS(防偷看); 本文件只负责算, 不判对错。
用法(调试): scripts/venv/Scripts/python.exe -X utf8 scripts/skills_ver/exam_samples.py zhiyingjuexin [--end 2026-10-23] [--days 20] [--lookback 160]
"""
import argparse
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts/paper_line/tools"), str(ROOT / "scripts/lib"), str(ROOT / "scripts/quotes"), str(ROOT / "scripts/tzzb"),
                str(ROOT / "scripts/backfill_bilibili")]
import pymysql  # noqa: E402

REPO = ("204", "1318", "GC", "131")
TRIO = ("连板接力", "首板次日", "涨停回调")
UNSEALED = ("未触板", "炸板")
SEALED = ("封住", "一字")
CACHE = ROOT / "results/skill_exam/_cache"


def db(name="investment_tool"):
    """连接抄 scripts/live/plan_review.py 的 db(); 本模块只发 SELECT"""
    yml = (ROOT / "inv-admin/src/main/resources/application.yml").read_text(encoding="utf-8")
    pw = re.search(r"password:\s*\"?([^\"\r\n]+)", yml).group(1).strip()
    return pymysql.connect(host="localhost", port=3306, user="root", password=pw, database=name, charset="utf8mb4", autocommit=True)


def q(conn, sql, args=()):
    assert sql.strip().lower().startswith("select"), "只读: 只许 SELECT"
    c = conn.cursor()
    c.execute(sql, args)
    return c.fetchall()


def jl(p):
    p = Path(p)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def is_repo(code, name=""):
    return str(code).startswith(REPO) or "GC0" in (name or "") or (name or "").startswith("R-")


def pct(a, b):
    return None if (a is None or not b) else round(a / b - 1, 4)


class Market:
    """行情只读访问(日线 / 板态 / 箱体 / 分钟线 / 交易日历 / 市场广度), 一个进程共享一份"""

    def __init__(self, end):
        self.con = db("investment_market")
        self.TD = [str(r[0]) for r in q(self.con, "select trade_date from kline_day where symbol='sh000001' and is_deleted=0 and trade_date>='2025-01-01' "
                                                  "and trade_date<=%s order by trade_date", (end,))]
        self.PREV = {d: self.TD[i - 1] for i, d in enumerate(self.TD) if i}
        self.NEXT = {d: self.TD[i + 1] for i, d in enumerate(self.TD[:-1])}
        self.end = end
        self._kd, self._min = {}, {}
        self.zt_n, self.up_r = self._breadth()
        import a_rules as AR
        self.AR = AR

    def kday(self, code):
        """日线 dict: date → {o,h,l,c,pc,lu,ld}"""
        if code in self._kd:
            return self._kd[code]
        try:
            sym = code if code[:2] in ("sh", "sz", "bj") else self.AR.symbol(code)
        except Exception:  # noqa: BLE001
            self._kd[code] = {}
            return {}
        rows = q(self.con, "select trade_date, cast(open as double), cast(high as double), cast(low as double), cast(close as double), cast(pre_close as double), "
                           "cast(limit_up as double), cast(limit_down as double) from kline_day where symbol=%s and is_deleted=0 and trade_date between %s and %s "
                           "order by trade_date", (sym, "2025-01-01", self.end))
        out = {}
        for td, o, h, l, c, pc, lu, ld in rows:
            d = str(td)
            if (not lu) and pc and code[:2] not in ("sh", "sz"):
                try:
                    lu, ld = self.AR.limit_prices(code, d, pc)[:2]
                except Exception:  # noqa: BLE001
                    lu = None
            out[d] = {"o": o, "h": h, "l": l, "c": c, "pc": pc, "lu": lu, "ld": ld}
        self._kd[code] = out
        return out

    @staticmethod
    def status(k):
        """当日收盘板态: 一字 / 封住 / 炸板 / 未触板 / 跌停(按日线)"""
        if not k or not k.get("lu"):
            return None
        lu, ld = k["lu"], k.get("ld")
        if k["c"] >= lu - 0.005:
            return "一字" if k["l"] >= lu - 0.005 else "封住"
        if k["h"] >= lu - 0.005:
            return "炸板"
        if ld and k["c"] <= ld + 0.005:
            return "跌停"
        return "未触板"

    def board_height(self, code, d):
        kd = self.kday(code)
        n = 0
        i = self.TD.index(d) if d in self.TD else None
        while i is not None and i >= 0 and self.status(kd.get(self.TD[i])) in SEALED:
            n += 1
            i -= 1
        return n

    def box(self, code, D, px):
        """段式箱体(kline_struct 同口径), 只用 D 之前的日线"""
        try:
            import kline_struct as K
            R = K.daily(code, D)
        except Exception:  # noqa: BLE001
            return "无数据", None
        if not R:
            return "无数据", None
        d, o, h, l_, cl, pc = R
        atr = K.atr14(h, l_, cl, pc)
        bx = K.seg_boxes(o, h, l_, cl, atr)
        if not bx:
            return "无箱", None
        last = bx[-1]
        if last[1] >= len(cl) - 3:
            Rr, S = last[2], last[3]
            pos = (px - S) / (Rr - S) * 100 if Rr > S else 50
            if pos > 100:
                return "越上沿", round(pos)
            if pos < 0:
                return "破下沿", round(pos)
            return ("箱下部" if pos < 33 else "箱中部" if pos <= 66 else "箱上部"), round(pos)
        return ("离箱向上" if px > last[2] else "离箱向下" if px < last[3] else "回箱内"), None

    def path30(self, D, code, pc):
        """开盘后 30 分钟最高 / 最低(相对昨收); 10/09 起才有分钟线"""
        if D not in self._min:
            self._min[D] = {}
        cache = self._min[D]
        if code not in cache:
            want = self.AR.symbol(code)
            bars = []
            f = ROOT / "downloads/market" / D / "kline_minute.jsonl"
            if f.exists():
                with open(f, encoding="utf-8") as fh:
                    for line in fh:
                        if want not in line[:60]:
                            continue
                        r = json.loads(line)
                        if r.get("symbol") == want:
                            bars.append((r["barTime"][11:16], r["open"], r["high"], r["low"], r["close"]))
            cache[code] = sorted(bars)
        b = [x for x in cache[code] if x[0] <= "10:00"]
        if not b or not pc:
            return None
        hi, lo = max(x[2] for x in b), min(x[3] for x in b)
        return {"hi30": round(hi / pc - 1, 4), "lo30": round(lo / pc - 1, 4)}

    def _breadth(self):
        """日期 → 涨停家数 / 上涨占比: 抄 scripts/tzzb/case_log.py market_breadth 口径(汇自全体导师 cases_auto feat)"""
        zt, up = {}, {}
        for f in sorted((ROOT / "skills").glob("*-skill/persona/cases_auto.jsonl")):
            for r in jl(f):
                fe = r.get("feat") or {}
                d = r.get("date")
                if fe.get("zt_n_day") is not None:
                    zt.setdefault(d, fe["zt_n_day"])
                if fe.get("zt_n_prev") is not None and d in self.PREV:
                    zt.setdefault(self.PREV[d], fe["zt_n_prev"])
                if fe.get("up_ratio_prev") is not None and d in self.PREV:
                    up.setdefault(self.PREV[d], fe["up_ratio_prev"])
        return zt, up

    def mkt(self, D):
        idx = self.kday("sh000001")
        P0 = self.PREV[D]
        ki = idx.get(D, {})
        i0 = self.TD.index(P0)
        nxt = self.NEXT.get(D)
        return {"idx_gap": pct(ki.get("o"), ki.get("pc")), "idx_day": pct(ki.get("c"), ki.get("pc")),
                "idx_prev": pct(idx.get(P0, {}).get("c"), idx.get(P0, {}).get("pc")),
                "idx_5d_prev": pct(idx.get(P0, {}).get("c"), idx.get(self.TD[i0 - 5], {}).get("c")) if i0 >= 5 else None,
                "zt_n_prev": self.zt_n.get(P0), "zt_n_day": self.zt_n.get(D), "up_prev": self.up_r.get(P0), "up_day": self.up_r.get(D),
                # 节前最后交易日: 下一交易日隔 ≥4 个自然日(日历未知时按 a_rules 兜底判)
                "pre_holiday": self._pre_holiday(D, nxt)}

    def _pre_holiday(self, D, nxt):
        x = dt.date.fromisoformat(D)
        if not nxt:
            for k in range(1, 15):
                y = x + dt.timedelta(days=k)
                if self.AR._is_trade_day_fallback(y.isoformat()):
                    nxt = y.isoformat()
                    break
        return bool(nxt) and (dt.date.fromisoformat(nxt) - x).days >= 4


def window(M, n_days, lookback):
    """[全部样本日(含训练段)], [考卷窗口 = 最后 n_days 个交易日]"""
    TD = M.TD
    win = TD[-n_days:]
    allw = TD[-(n_days + lookback):]
    return allw, win


# ------------------------------------------------------------------ 股票导师: 持仓日 / 新开仓 / 账户日 ------------------------------------------------------------------
def build_stock(M, sk, days_all):
    con = db()
    d0 = M.PREV[days_all[0]]
    end_x = (dt.date.fromisoformat(days_all[-1]) + dt.timedelta(days=1)).isoformat()
    legs = collections.defaultdict(list)
    names = {}
    for rt, code, name, side, px, qty in q(con, "select record_time, stock_code, stock_name, side, cast(price as double), cast(qty as double) from tzzb_record "
                                               "where ledger=%s and record_type='bs_leg' and is_deleted=0 and record_time>=%s and record_time<%s order by record_time",
                                           (sk, d0, end_x)):
        if is_repo(code, name):
            continue
        legs[(str(rt)[:10], code)].append((str(rt)[11:19], "买" if "买" in side else "卖", px, qty))
        names[code] = name
    navs = {str(rt)[:10]: float(json.loads(pj).get("asset") or 0) for rt, pj in
            q(con, "select record_time, payload_json from tzzb_record where ledger=%s and record_type='nav_day' and is_deleted=0 and record_time>=%s", (sk, d0))}
    con.close()
    dp_raw = json.loads((ROOT / "downloads/tzzb" / sk / "day_positions.json").read_text(encoding="utf-8"))
    DP = {}
    for k, v in dp_raw.items():
        D = f"{k[:4]}-{k[4:6]}-{k[6:]}"
        DP[D] = {}
        for p in (v or {}).get("list") or []:
            c = str(p.get("code"))
            if is_repo(c, p.get("name")):
                continue
            DP[D][c] = {"pp": float(p.get("position_percent") or 0), "rate": p.get("rate"), "name": p.get("name")}
            names.setdefault(c, p.get("name"))
    CA = jl(ROOT / f"skills/{sk}-skill/persona/cases_auto.jsonl")
    RT = {(r["date"], r["time"], str(r["code"]), r["side"]): r.get("rt") for r in jl(ROOT / f"skills/{sk}-skill/persona/fills_rt.jsonl") if r.get("rt")}
    buys_hist = collections.defaultdict(list)
    play_of = {}
    sells_pnl = collections.defaultdict(list)
    for r in CA:
        if r.get("side") == "买" and r.get("code"):
            buys_hist[str(r["code"])].append(r["date"])
            if r.get("new_open"):
                play_of[(r["date"], str(r["code"]))] = r.get("play")
            play_of.setdefault(("any", r["date"], str(r["code"])), r.get("play"))
        if r.get("side") == "卖" and (r.get("result") or {}).get("pnl") is not None:
            sells_pnl[r["date"]].append(r["result"]["pnl"])
    TD = M.TD

    def run_start(code, D):
        i = TD.index(D)
        s = D
        while i > 0 and DP.get(TD[i - 1], {}).get(code, {}).get("pp", 0) > 0:
            i -= 1
            s = TD[i]
        return s

    def fam(code, ref):
        lo = (dt.date.fromisoformat(ref) - dt.timedelta(days=365)).isoformat()
        return any(lo <= d < ref for d in buys_hist.get(code, []))

    pos, opens, days = [], [], []
    for D in days_all:
        P0 = M.PREV[D]
        if D not in DP:
            days.append({"date": D, "missing": True, "nav": navs.get(D)})
            continue
        H0 = {c: dict(v) for c, v in DP.get(P0, {}).items() if v["pp"] > 0.001}
        H1 = {c: v for c, v in DP.get(D, {}).items() if v["pp"] > 0.001}
        tot0, tot1 = round(sum(v["pp"] for v in H0.values()), 3), round(sum(v["pp"] for v in H1.values()), 3)
        mkt = M.mkt(D)
        codes_today = {c for (d, c) in legs if d == D}
        n_new = 0
        for c in sorted(set(H0) | codes_today):
            L = legs.get((D, c), [])
            kd = M.kday(c)
            k, kp = kd.get(D), kd.get(P0)
            b = [x for x in L if x[1] == "买"]
            s = [x for x in L if x[1] == "卖"]
            qb, qs = sum(x[3] for x in b), sum(x[3] for x in s)
            pp0 = H0.get(c, {}).get("pp", 0.0)
            pp1 = DP.get(D, {}).get(c, {}).get("pp", 0.0)
            f = {"date": D, "code": c, "name": names.get(c), "pp0": round(pp0, 3), "pp1": round(pp1, 3), "tot0": tot0, "tot1": tot1,
                 "n_buy": len(b), "n_sell": len(s), "t_buy1": b[0][0] if b else None, "t_sell1": s[0][0] if s else None,
                 "auction_buy": any(x[0] <= "09:25:59" for x in b), **mkt}
            if k and k.get("pc"):
                f.update({"gap": pct(k["o"], k["pc"]), "high": pct(k["h"], k["pc"]), "low": pct(k["l"], k["pc"]), "close": pct(k["c"], k["pc"]),
                          "st_day": M.status(k), "hit_lu_day": bool(k.get("lu") and k["h"] >= k["lu"] - 0.005)})
                bvp = [pct(x[2], k["pc"]) for x in b]
                f["buy_vs_pc1"] = bvp[0] if bvp else None
                f["buy_below_open"] = any(x[2] < k["o"] * 0.995 for x in b)
            if kp and kp.get("pc"):
                f.update({"st_prev": M.status(kp), "pct_prev": pct(kp["c"], kp["pc"]), "h_prev": M.board_height(c, P0)})
            if D >= "2026-10-09" and k and k.get("pc"):
                pth = M.path30(D, c, k["pc"])
                if pth:
                    f.update(pth)
            rts = [r for r in (RT.get((D, x[0], c, "买")) for x in b) if r]
            if rts:
                f["buy_pos_in_day"] = rts[0].get("pos_so_far")
                f["buy_at_limit"] = any(r.get("at_limit") for r in rts)
            if pp0 > 0.001:
                rs = run_start(c, P0)
                hold = sum(1 for x in TD if rs <= x <= P0)
                if pp1 <= 0.005:
                    act = "清"
                elif pp1 - pp0 > 0.08 or (qb > qs and pp1 > pp0 + 0.02):
                    act = "加"
                elif pp0 - pp1 > 0.08 or (qs > qb and pp1 < pp0 - 0.02):
                    act = "减"
                elif L:
                    act = "做T"
                else:
                    act = "不动"
                gap_flag = None
                if rs >= d0 and not any(x[1] == "买" for x in legs.get((rs, c), [])):
                    gap_flag = f"持仓起点 {rs} 没有买入腿(快照有仓位, 成交腿缺)"
                # 浮盈: tzzb 的 rate 在新开当日收盘常是占位值 −0.0001 / 0 → 用持仓起点以来的买入均价重算
                r0 = H0[c].get("rate")
                buys_run = [x for dd in TD if rs <= dd <= P0 for x in legs.get((dd, c), []) if x[1] == "买"]
                if (r0 is None or abs(float(r0)) <= 0.0002) and buys_run and kp:
                    cost = sum(x[2] * x[3] for x in buys_run) / sum(x[3] for x in buys_run)
                    r0 = round(kp["c"] / cost - 1, 4)
                f.update({"kind": "pos", "act": act, "data_gap": gap_flag, "hold": hold, "run_start": rs, "yest_new": rs == P0,
                          "rate0": None if r0 is None else float(r0), "play_open": play_of.get((rs, c)), "fam": fam(c, rs)})
                f["yn_unsealed"] = bool(f["yest_new"] and f.get("st_prev") in UNSEALED)
                if kp:
                    f["box_prev_close"] = M.box(c, D, kp["c"])[0]
                pos.append(f)
            elif b:
                n_new += 1
                amt_all = sum(x[2] * x[3] for x in b)
                t0 = dt.datetime.strptime(b[0][0], "%H:%M:%S")
                amt5 = sum(x[2] * x[3] for x in b if (dt.datetime.strptime(x[0], "%H:%M:%S") - t0).total_seconds() <= 300)
                nav0 = navs.get(P0)
                f.update({"kind": "open", "play": play_of.get((D, c)) or play_of.get(("any", D, c)), "fam": fam(c, D),
                          "first5_amt_ratio": round(amt5 / nav0, 3) if nav0 else None, "buy_amt_ratio": round(amt_all / nav0, 3) if nav0 else None,
                          "first5_share": round(amt5 / amt_all, 3) if amt_all else None, "vwap": round(amt_all / qb, 4) if qb else None})
                if f.get("vwap"):
                    f["box_buy"] = M.box(c, D, f["vwap"])[0]
                opens.append(f)
        days.append({"date": D, "tot0": tot0, "tot1": tot1, "d_tot": round(tot1 - tot0, 3), "n_hold0": len(H0), "n_hold1": len(H1), "n_new": n_new,
                     "traded": any(d == D for (d, c) in legs), "empty_prev": tot0 <= 0.005, "empty_close": tot1 <= 0.005, "nav": navs.get(D), **mkt})
    _enrich(M, sk, pos, opens, days, sells_pnl)
    return {"skill": sk, "kind": "stock", "pos": pos, "open": opens, "day": days, "last_dp": max(DP) if DP else None}


def _enrich(M, sk, pos, opens, days, sells):
    """账户日 / 新开仓的派生字段(抄 distill_diag/eval_rules.enrich; 只用决策前或同日已发生的信息)"""
    navs = {d["date"]: d.get("nav") for d in days}
    for d in days:
        if d.get("missing"):
            continue
        P1 = M.PREV.get(d["date"])
        P2 = M.PREV.get(P1) if P1 else None
        if P1 and P2 and navs.get(P1) and navs.get(P2):
            d["nav_chg_prev"] = round(navs[P1] / navs[P2] - 1, 4)
        d["cleared_any"] = any(p["date"] == d["date"] and p["act"] == "清" for p in pos)
    alld = sorted(set(sells) | {d["date"] for d in days})
    streak, st_of = 0, {}
    for x in alld:
        if sells.get(x):
            streak = streak + 1 if all(v < 0 for v in sells[x]) else 0
        st_of[x] = streak
    for d in days:
        if d.get("missing"):
            continue
        j = alld.index(d["date"])
        pd_ = alld[j - 1] if j else None
        d["loss_streak"] = st_of.get(pd_, 0) if pd_ else 0
        d["loss_sell_prev"] = bool(pd_ and sells.get(pd_) and any(v < 0 for v in sells[pd_]))
    seen = set()
    dayinfo = {d["date"]: d for d in days}
    for p in sorted(opens, key=lambda x: (x["date"], x["t_buy1"] or "")):
        p["first_open_today"] = p["date"] not in seen
        seen.add(p["date"])
        p["day_tot1"] = dayinfo.get(p["date"], {}).get("tot1", 0)
        prev_days = [x for x in alld if x < p["date"] and sells.get(x)]
        if prev_days:
            p["prev_round_loss"] = sum(sells[prev_days[-1]]) / len(sells[prev_days[-1]]) < 0
            n = 0
            for x in reversed(prev_days):
                if sum(sells[x]) / len(sells[x]) < 0:
                    n += 1
                else:
                    break
            p["loss_rounds"] = n
    # 双创(创业板指 / 科创50)近 3 个交易日有单日 ≤−2%
    drop = collections.defaultdict(float)
    for sym in ("sz399006", "sh000688"):
        for d, k in M.kday(sym).items():
            if k.get("pc"):
                drop[d] = min(drop[d], k["c"] / k["pc"] - 1)
    for p in opens:
        ds = [x for x in sorted(drop) if x <= p["date"]][-3:]
        p["sc_drop3"] = any(drop[x] <= -0.02 for x in ds)


# ------------------------------------------------------------------ 不吃土豆0: 账户日 ------------------------------------------------------------------
def _cb_meta():
    fs = sorted((ROOT / "downloads/quotes/cb/meta").glob("RPT_BOND_CB_LIST_all_*.json"))
    if not fs:
        return {}
    return {r["SECURITY_CODE"]: r.get("CONVERT_STOCK_CODE") for r in json.loads(fs[-1].read_text(encoding="utf-8"))}


def _cb_k(M, code):
    """转债日线: 先行情库, 缺的日子用 downloads/quotes/cb/kline/<code>.json 补(那里没有昨收 → 取前一行收盘)"""
    sym = ("sh" if code.startswith("11") else "sz") + code
    out = {d: (k["o"], k["pc"]) for d, k in M.kday(sym).items() if k.get("o") and k.get("pc")}
    f = ROOT / "downloads/quotes/cb/kline" / f"{code}.json"
    if f.exists():
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            ds = sorted(raw)
            for i, d in enumerate(ds[1:], 1):
                if d not in out and raw[d].get("o") and raw[ds[i - 1]].get("c"):
                    out[d] = (raw[d]["o"], raw[ds[i - 1]]["c"])
        except Exception:  # noqa: BLE001
            pass
    return out, sym


def _auc(D, sym):
    f = ROOT / "downloads/market" / D / "auction_live_open.json"
    if not f.exists():
        return None
    try:
        s = (json.loads(f.read_text(encoding="utf-8")).get("symbols") or {}).get(sym)
    except Exception:  # noqa: BLE001
        return None
    v = ((s or {}).get("p2") or {}).get("pct")
    return None if v is None else round(v / 100, 4)


def build_tudou(M, sk, days_all):
    con = db()
    d0 = M.TD[max(0, M.TD.index(days_all[0]) - 12)]
    legs = collections.defaultdict(list)
    for rt, code, name, side, px, qty in q(con, "select record_time, stock_code, stock_name, side, cast(price as double), cast(qty as double) from tzzb_record "
                                               "where ledger=%s and record_type='bs_leg' and is_deleted=0 and record_time>=%s order by record_time", (sk, d0)):
        if is_repo(code, name):
            continue
        legs[str(rt)[:10]].append((str(rt)[11:19], str(code), name, "买" if "买" in side else "卖", px, qty))
    navd = {str(r[0])[:10] for r in q(con, "select record_time from tzzb_record where ledger=%s and record_type='nav_day' and is_deleted=0 and record_time>=%s", (sk, d0))}
    con.close()
    meta = _cb_meta()
    TD = M.TD
    rows = []
    loss_days = []
    for D in days_all:
        i = TD.index(D)
        prior = TD[max(0, i - 10):i]
        cnt = collections.Counter(x[1] for d in prior for x in legs.get(d, []) if x[3] == "买")
        main = cnt.most_common(1)[0][0] if cnt else None
        L = legs.get(D, [])
        r = {"date": D, "missing": (not L and D not in navd), "traded": bool(L), "main_bond": main, "has_main": bool(main), **M.mkt(D)}
        if main:
            bk, bsym = _cb_k(M, main)
            stk = meta.get(main)
            bo = bk.get(D)
            r["bond_open"] = round(bo[0] / bo[1] - 1, 4) if bo else None
            r["bond_v924"] = _auc(D, bsym)
            if stk:
                kd = M.kday(stk).get(D)
                r["stk_open"] = pct(kd["o"], kd["pc"]) if kd else None
                try:
                    r["stk_v924"] = _auc(D, M.AR.symbol(stk))
                except Exception:  # noqa: BLE001
                    r["stk_v924"] = None
            # 决策时(09:24)能看到的: 有虚拟撮合用它, 没有(10/12 前)用最终开盘价近似
            r["stk_auc"] = r.get("stk_v924") if r.get("stk_v924") is not None else r.get("stk_open")
            r["bond_auc"] = r.get("bond_v924") if r.get("bond_v924") is not None else r.get("bond_open")
            r["auc_src"] = "09:24 虚拟撮合" if r.get("stk_v924") is not None else "开盘价近似"
        # 连亏(按日首笔回合)
        r["loss_streak"] = 0
        for x in reversed(loss_days):
            if x:
                r["loss_streak"] += 1
            else:
                break
        if L:
            b = [x for x in L if x[3] == "买"]
            s = [x for x in L if x[3] == "卖"]
            if b:
                fb = b[0]
                r.update({"first_buy": fb[0], "first_buy_name": fb[2], "n_buy": len(b),
                          "auction_main": any(x[0] == "09:25:00" and x[1] == main for x in b),
                          "auction_any": fb[0] == "09:25:00",
                          "first_channel": "竞价" if fb[0] == "09:25:00" else "死窗" if fb[0] == "09:30:00" else "追单" if fb[0] <= "09:35:59" else "盘中",
                          "late_buy": any(x[0] > "09:35:59" for x in b), "notional_first": round(fb[4] * fb[5] / 1e4, 1)})
                s1 = [x for x in s if x[1] == fb[1]]
                if s1:
                    r["first_sell"] = s1[0][0]
                    r["rt1"] = round(s1[0][4] / fb[4] - 1, 4)
                    t0 = max(dt.datetime.strptime(fb[0], "%H:%M:%S"), dt.datetime.strptime("09:30:00", "%H:%M:%S"))
                    r["rt1_secs"] = (dt.datetime.strptime(s1[0][0], "%H:%M:%S") - t0).total_seconds()
            loss_days.append((r.get("rt1") or 0) < 0)
        else:
            r.setdefault("auction_main", False)
            r.setdefault("auction_any", False)
        rows.append(r)
    return {"skill": sk, "kind": "tudou", "pos": [], "open": [], "day": rows, "last_dp": max((d for d in legs), default=None)}


TUDOU = {"buchitudou0"}


def build(sk, end, n_days, lookback=160, use_cache=True):
    """返回 {skill, kind, pos, open, day, window, days_all, last_dp}; 缓存: 源文件(day_positions / cases_auto)没变就复用"""
    CACHE.mkdir(parents=True, exist_ok=True)
    cf = CACHE / f"samples_{sk}_{end}_{n_days}_{lookback}.json"
    srcs = [ROOT / "downloads/tzzb" / sk / "day_positions.json", ROOT / f"skills/{sk}-skill/persona/cases_auto.jsonl", Path(__file__)]
    if use_cache and cf.exists() and all((not s.exists()) or s.stat().st_mtime < cf.stat().st_mtime for s in srcs) \
            and (dt.datetime.now() - dt.datetime.fromtimestamp(cf.stat().st_mtime)).total_seconds() < 6 * 3600:
        return json.loads(cf.read_text(encoding="utf-8"))
    M = Market(end)
    days_all, win = window(M, n_days, lookback)
    res = (build_tudou if sk in TUDOU else build_stock)(M, sk, days_all)
    res.update({"window": win, "days_all": days_all, "end": end, "built_at": dt.datetime.now().isoformat(timespec="seconds")})
    cf.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return res


def last_trade_day(today=None):
    con = db("investment_market")
    r = q(con, "select max(trade_date) from kline_day where symbol='sh000001' and is_deleted=0 and trade_date<=%s", ((today or dt.date.today().isoformat()),))
    con.close()
    return str(r[0][0])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("skill")
    ap.add_argument("--end")
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument("--lookback", type=int, default=160)
    a = ap.parse_args()
    import time
    t = time.time()
    end = a.end or last_trade_day()
    for s in a.skill.split(","):
        R = build(s, end, a.days, a.lookback, use_cache=False)
        print(s, "end", end, "pos", len(R["pos"]), "open", len(R["open"]), "day", len(R["day"]), "last", R["last_dp"], f"{time.time() - t:.0f}s")
