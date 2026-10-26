# -*- coding: utf-8 -*-
"""bracket_sim.py — 条件单组离线模拟器(10/25 夜建; 只离线, 不接 executor, 零 token)

一组单 = 一个方向(SELL / BUY) + 若干条规则; 规则字段对齐 scripts/paper_line/executor.py 10/25 的条件单(type="cond"):
  {"id", "side", "type": "limit|cond|market", "qty": 占底仓(卖) / 计划仓(买)的比例 0~1,
   限价单: "px": 价格 或 "px_from": {"h": "30|60|eod", "key": "最高|最低|收盘", "q": 10|25|50|75|90}   ← 由区间引擎在生效那一刻给价, 模型不推数字
   条件单: "ref": "涨停价|开盘价|昨收|跌停价|日内最高|日内最低|具体价格(数字)" (+ 本模拟器扩展: "@low" 生效时的日内最低 / "@high" / "@vwap" / "@px" 生效时现价),
          "dir": "up|down", "pct": 数字 或 {"amp_k": k} (= k × 本票 20 日振幅中位数, 百分数), "book": "b1|b2|a1|a2", "arm": 缺省同 executor,
   "after": "规则 id"(那张成交过才生效; 与 executor 同义)}
  本模拟器扩展(executor 还没有, 上线前要主会话加): "gate"(生效时机: rebound 反抽 / panic_done 恐慌盘卖完 / vwap_vol 站上均价且放量 / n_open 第 n 次开板后 / time),
  "unless_filled": [ids](这些成交过就作废, 防踏空只在低吸没买到时追), "cancel_below": 买单跌破这个价(或 "@low-x%")就撤, "expire": "HH:MM"

撮合(逐分钟; 每根按 O→L→H→C(阳线) / O→H→L→C(阴线) 走一遍):
  限价卖: 价格穿过挂价(高于挂价)才算全部成交, 只碰到挂价(本根最高 = 挂价)只成交剩余的 50%; 开盘跳空越过挂价 → 按开盘价成交
  条件单: 参考价涨 / 回落到 pct 时按 book 档一次成交(卖 b1 = 触发价向下取整到 0.01, b2 再让 1 分; 买 a1 向上取整, a2 再加 1 分);
          ref=涨停价 / 日内最高 / 日内最低 默认 arm(先碰到参考价才开始算); 日内最高 / 最低 = 这张单生效后的最高 / 最低(同 executor)
  市价: 下一根开盘价
  涨停封死(本根 高 = 低 = 涨停价)买不进; 跌停封死卖不出; 成本每边 0.1%(在评估里扣)
  决策只用 ≤ 本根收盘的数据(特征来自 range_engine.features, 因果), 生效从下一根开始

用法:
  python bracket_sim.py demo                         10/23 海欣股份 / 北新路桥 两个示例
  python bracket_sim.py run <代码> <D> <HH:MM> <spec.json>
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import range_engine as R   # noqa: E402

TICK = 0.01
EPS = 1e-6
COST = 0.001


def fl(x):
    return math.floor(x / TICK + 1e-6) * TICK


def ce(x):
    return math.ceil(x / TICK - 1e-6) * TICK


class Path:
    """一只票一天的分钟线 + 因果特征"""

    def __init__(self, code, D):
        self.code, self.D = code, D
        day = R.load_day(D)
        if code not in day.idx:
            raise KeyError(f"{code} {D} 没有分钟数据")
        i = day.idx[code]
        self.src = int(day.src[i])
        F = R.features(day, rows=[i])
        self.F = {k: (v[0] if hasattr(v, "ndim") and v.ndim >= 1 and v.shape[0] == 1 else v) for k, v in F.items()}
        self.O, self.H, self.L, self.C = (np.asarray(day.__dict__[k][i], dtype=float) for k in ("O", "H", "L", "C"))
        self.open, self.prev, self.up, self.dn = float(day.open[i]), float(day.prev[i]), float(day.up[i]), float(day.dn[i])
        self.vw, self.red, self.rsi, self.lo, self.hi, self.lo_at, self.vr, self.n_open = (self.F[k] for k in ("vw", "red", "rsi", "lo", "hi", "lo_at", "vr", "n_open"))
        self._amp = None

    def amp(self):
        if self._amp is None:
            self._amp = R.amp20(self.code, self.D) or 0.05
        return self._amp

    def sealed_up(self, j):
        return self.H[j] <= self.up + EPS and self.L[j] >= self.up - EPS

    def sealed_dn(self, j):
        return self.H[j] <= self.dn + EPS and self.L[j] >= self.dn - EPS

    def pts(self, j):
        o, h, l_, c = self.O[j], self.H[j], self.L[j], self.C[j]
        return [o, l_, h, c] if c >= o else [o, h, l_, c]


def _gate_ok(g, P, j):
    if not g:
        return True
    t = g.get("type")
    if t == "rebound":   # 术语表「反抽」: 红柱连续 ≥red 根 + RSI6 > rsi + 价 ≥ 均价 × (1 + tol)
        ok = P.red[j] >= g.get("red", 3) and P.C[j] >= P.vw[j] * (1 + g.get("tol", -0.002))
        if g.get("rsi") is not None:
            ok = ok and P.rsi[j] > g["rsi"]
        return bool(ok)
    if t == "panic_done":   # 术语表「恐慌盘卖完」: 不再创新低 nolow 根 + MACD 红柱
        return bool((j - P.lo_at[j]) >= g.get("nolow", 3) and P.red[j] >= g.get("red", 1)
                    and (P.lo[j] / P.open - 1) <= g.get("min_drop", 0.0))
    if t == "vwap_vol":   # 站上均价且放量
        return bool(P.C[j] >= P.vw[j] * (1 + g.get("tol", 0.0)) and P.vr[j] >= g.get("vr", 1.5))
    if t == "n_open":
        return bool(P.n_open[j] >= g.get("n", 2))
    if t == "time":
        return j >= R.hm2k(g["at"])
    if t == "price":
        return bool(P.C[j] >= g["px"]) if g.get("op", ">=") == ">=" else bool(P.C[j] <= g["px"])
    raise ValueError(f"未知 gate {t}")


class Rule:
    def __init__(self, d, side):
        self.d = dict(d)
        self.id = d.get("id")
        self.side = d.get("side", side)
        self.type = d.get("type") or ("cond" if "ref" in d else ("market" if d.get("market") else "limit"))
        self.qty = float(d.get("qty", 1.0))
        self.left = self.qty
        self.active = False
        self.dead = False
        self.px = None
        self.ref_fixed = None
        self.hi = self.lo = None
        self.armed = False
        self.pct = None
        self.filled = 0.0
        self.t_act = None
        self.note = ""


def run(P, spec, k0, engine=None):
    """spec = {"side", "rules": [...], "deadline": "14:56", "eod": "sell|hold|cancel"}; k0 = 决策时刻的那根(规则从 k0+1 起生效; k0=-1 → 从开盘价起)
    返回 {"fills": [(k, px, q, rid, why)], "left": 剩余仓位(卖) / 未买(买), "notes": [...]}"""
    side = spec["side"]
    rules = [Rule(r, side) for r in spec["rules"]]
    byid = {r.id: r for r in rules}
    kd = R.hm2k(spec.get("deadline", "14:56"))
    pos = 1.0 if side == "SELL" else 0.0     # 卖: 剩余底仓; 买: 已买
    fills, notes = [], []
    filled_ids = set()

    def activate(r, j):
        r.active, r.t_act = True, j
        ref_px = P.C[j] if j >= 0 else P.open
        if r.d.get("unless_filled") and any(x in filled_ids for x in r.d["unless_filled"]):
            r.dead = True
            r.note = "已买到, 防踏空作废"
            return
        if r.type == "limit":
            if "px_from" in r.d:
                pf = r.d["px_from"]
                res = engine.query(st=R.state_at(P.code, P.D, k=max(j, 0)))
                q = res["h"][str(pf.get("h", "60"))][pf.get("key", "最高" if r.side == "SELL" else "最低")]
                if not q.get("n"):
                    r.dead = True
                    r.note = "区间引擎无样本"
                    return
                v = ref_px * (1 + q[f"P{pf.get('q', 50)}"] / 100)
                r.px = ce(v) if r.side == "SELL" else fl(v)
                r.note = f"区间 {pf.get('h', '60')} 分钟{pf.get('key', '')} P{pf.get('q', 50)} = {q[f'P{pf.get(chr(113), 50)}']}%(n={q['n']}, 放宽 {res['level']} 级)"
            else:
                r.px = float(r.d["px"])
            r.px = min(max(r.px, P.dn), P.up)
        elif r.type == "cond":
            ref = r.d["ref"]
            if isinstance(ref, str) and ref.startswith("@"):
                r.ref_fixed = {"@low": P.lo[j], "@high": P.hi[j], "@vwap": P.vw[j], "@px": ref_px}[ref.split("-")[0]] if j >= 0 else P.open
            pct = r.d.get("pct", 0)
            if isinstance(pct, dict) and "q" in pct:   # 区间引擎给: 同状态之后 h 分钟 最低(卖止损) / 最高(买追) 的第 q 分位
                res = engine.query(st=R.state_at(P.code, P.D, k=max(j, 0)))
                dd = res["h"][str(pct.get("h", "60"))][pct.get("key", "最低")]
                v = abs(dd.get(f"P{pct['q']}", -1.0) or 0) if dd.get("n") else 1.0
                pct = max(pct.get("min", 0.3), min(pct.get("max", 8.0), v + pct.get("buf", 0.0)))
                r.note = f"止损距离 = 同状态 {pct}%(区间引擎 P{r.d['pct']['q']}, n={dd.get('n')})"
            elif isinstance(pct, dict):
                pct = max(pct.get("min", 0.3), min(pct.get("max", 8.0), pct["amp_k"] * P.amp() * 100))
            r.pct = float(pct) / 100
            r.hi = r.lo = ref_px
            r.armed = not r.d.get("arm", ref in ("涨停价", "日内最高", "日内最低")) or ref in ("日内最高", "日内最低")
        if r.d.get("cancel_below") is not None:
            cb = r.d["cancel_below"]
            if isinstance(cb, str) and cb.startswith("@low"):
                x = float(cb[4:] or 0) / 100
                r.d["_cb"] = (P.lo[j] if j >= 0 else P.open) * (1 + x)
            else:
                r.d["_cb"] = float(cb)

    def ref_of(r):
        ref = r.d["ref"]
        if r.ref_fixed is not None:
            return r.ref_fixed
        if isinstance(ref, (int, float)) or (isinstance(ref, str) and ref.replace(".", "", 1).isdigit()):
            return float(ref)
        return {"昨收": P.prev, "开盘价": P.open, "涨停价": P.up, "跌停价": P.dn, "日内最高": r.hi, "日内最低": r.lo}[ref]

    def do_fill(r, j, px, q, why):
        nonlocal pos
        if r.side == "SELL":
            q = min(q, pos, r.left)
        else:
            q = min(q, r.left, 1.0 - pos)   # 买: 总量不超过计划仓位
        if q <= EPS:
            return
        r.left -= q
        r.filled += q
        if r.side == "SELL":
            pos -= q
        else:
            pos += q
        filled_ids.add(r.id)
        fills.append((j, round(px, 3), round(q, 4), r.id, why))

    # 生效检查: 在第 j 根收盘时决定, 下一根开始撮合
    def check_activation(j):
        for r in rules:
            if r.active or r.dead:
                continue
            if r.d.get("after") and r.d["after"] not in filled_ids:
                continue
            g = r.d.get("gate")
            if g is not None and (j < 0 or not _gate_ok(g, P, j)):
                continue
            activate(r, j)

    check_activation(k0)
    prevC = P.C[k0] if k0 >= 0 else P.open
    for j in range(k0 + 1, min(kd, 239) + 1):
        pts = [prevC] + P.pts(j)
        if j == 0:
            pts = [P.open] + P.pts(j)
        su, sd = P.sealed_up(j), P.sealed_dn(j)
        touched = {}
        crossed = set()
        for si in range(len(pts) - 1):
            a, b = pts[si], pts[si + 1]
            jump = si == 0
            for r in rules:
                if not r.active or r.dead or r.left <= EPS:
                    continue
                if r.side == "SELL" and pos <= EPS:
                    continue
                if r.side == "BUY" and pos >= 1.0 - EPS:
                    continue
                if r.d.get("unless_filled") and any(x in filled_ids for x in r.d["unless_filled"]):
                    r.dead = True
                    r.note = "低吸单已成交, 防踏空作废"
                    continue
                if r.d.get("_cb") is not None and min(a, b) < r.d["_cb"] - EPS:
                    r.dead = True
                    r.note = f"跌破 {round(r.d['_cb'], 3)} 撤单"
                    continue
                if r.type == "market":
                    if (r.side == "SELL" and sd) or (r.side == "BUY" and su):
                        continue
                    do_fill(r, j, b if jump else a, r.left, "市价")
                    continue
                if r.type == "limit":
                    if r.side == "SELL":
                        if sd:
                            continue
                        if max(a, b) > r.px + EPS:
                            do_fill(r, j, max(r.px, b) if jump else r.px, r.left, "限价卖穿过")
                            crossed.add(r.id)
                        elif max(a, b) >= r.px - EPS:
                            if r.px >= P.up - EPS:   # 挂在涨停价卖: 碰到涨停 = 有排队买单, 按全部成交
                                do_fill(r, j, r.px, r.left, "涨停价卖")
                                crossed.add(r.id)
                            else:
                                touched[r.id] = r
                    else:
                        if su:
                            continue
                        if min(a, b) < r.px - EPS:
                            do_fill(r, j, min(r.px, b) if jump else r.px, r.left, "限价买穿过")
                            crossed.add(r.id)
                        elif min(a, b) <= r.px + EPS:
                            if r.px <= P.dn + EPS:   # 挂在跌停价买: 碰到跌停 = 有排队卖单
                                do_fill(r, j, r.px, r.left, "跌停价买")
                                crossed.add(r.id)
                            else:
                                touched[r.id] = r
                    continue
                # 条件单: 在 a→b 这段上更新参考 / arm / 判命中
                if b >= a:   # 上行段
                    if r.d["dir"] == "up":
                        ref = ref_of(r)
                        lvl = ref * (1 + r.pct)
                        if r.armed and b >= lvl - EPS and not (r.side == "BUY" and su):
                            px = max(lvl, a) if not jump else b
                            px = ce(px) + (TICK if r.d.get("book") in ("a2",) else 0)
                            do_fill(r, j, px, r.left, f"{r.d['ref']}涨{round(r.pct * 100, 2)}%")
                    r.hi = max(r.hi, b)
                    if not r.armed and r.d["dir"] == "down" and b >= ref_of(r) - EPS:
                        r.armed = True
                else:        # 下行段
                    r.lo = min(r.lo, b)
                    if r.d["dir"] == "down":
                        ref = ref_of(r)
                        lvl = ref * (1 - r.pct)
                        if r.armed and b <= lvl + EPS and not (r.side == "SELL" and sd):
                            px = min(lvl, a) if not jump else b
                            px = fl(px) - (TICK if r.d.get("book") == "b2" else 0)
                            do_fill(r, j, px, r.left, f"{r.d['ref']}回落{round(r.pct * 100, 2)}%")
                    if not r.armed and r.d["dir"] == "up" and b <= ref_of(r) + EPS:
                        r.armed = True
        for rid, r in touched.items():   # 只碰到没穿过: 成交 50%
            if rid not in crossed and r.left > EPS and not r.dead:
                do_fill(r, j, r.px, r.left * 0.5, "只碰到挂价(50%)")
        for r in rules:
            if r.active and r.d.get("expire") and j >= R.hm2k(r.d["expire"]):
                r.dead = True
        prevC = P.C[j]
        check_activation(j)
    # 收尾
    eod = spec.get("eod", "sell" if side == "SELL" else "cancel")
    if side == "SELL" and pos > EPS:
        if eod == "sell":
            j = min(kd, 239)
            if P.sealed_dn(j):
                notes.append("收尾时跌停封死, 卖不出, 按收盘价记")
            fills.append((j, round(float(P.C[j]), 3), round(pos, 4), "EOD", "到点卖剩余"))
            pos = 0.0
        else:
            notes.append(f"剩 {round(pos, 3)} 拿着, 按收盘价 {P.C[-1]} 记")
    for r in rules:
        if r.note:
            notes.append(f"{r.id}: {r.note}" + (f" → 挂价 {round(r.px, 3)}" if r.px else ""))
    return {"fills": fills, "pos": pos, "notes": notes, "rules": {r.id: {"px": r.px, "act": None if r.t_act is None else R.k2hm(r.t_act), "filled": round(r.filled, 3),
                                                                           "pct": None if r.pct is None else round(r.pct * 100, 2)} for r in rules}}


def evaluate(P, res, k0, side, cost=COST, fly=0.03):
    """卖: 均价 / 相对收盘 / 在 k0 之后区间里的位置 / 卖飞; 买: 均价 / 成交比例 / 位置 / 踏空 / 到收盘"""
    fills = res["fills"]
    j0 = max(k0 + 1, 0)
    hiA, loA = float(np.max(P.H[j0:])), float(np.min(P.L[j0:]))
    if k0 < 0:
        hiA, loA = max(hiA, P.open), min(loA, P.open)
    rng = max(hiA - loA, 1e-9)
    close = float(P.C[-1])
    q = sum(f[2] for f in fills)
    out = {"n_fill": len(fills), "filled": round(q, 3)}
    if q <= EPS:
        out.update({"avg": None})
        if side == "BUY":
            ref = P.C[k0] if k0 >= 0 else P.open
            out["踏空"] = bool(close >= ref * 1.02 or hiA >= ref * 1.03)
        return out
    avg = sum(f[1] * f[2] for f in fills) / q
    same = [f for f in fills if f[3] != "HOLD"]   # HOLD = 拿过夜按次日开盘估值, 不算当天区间位置
    sq = sum(f[2] for f in same)
    last_k = max(f[0] for f in same) if same else 239
    out["avg"] = round(avg, 4)
    out["pos"] = round((sum(f[1] * f[2] for f in same) / sq - loA) / rng, 3) if sq > EPS else None        # 0 = 区间最低, 1 = 区间最高
    out["hold_part"] = round(q - sq, 3)
    if side == "SELL":
        out["vs_close"] = round((avg * (1 - cost) / close - 1) * 100, 3)   # 卖价比拿到收盘好多少(%)
        after = P.H[last_k + 1:] if last_k + 1 < 240 else np.array([])
        mx_after = float(np.max(after)) if len(after) else avg
        last_px = [f[1] for f in same if f[0] == last_k][-1] if same else avg
        out["卖后回封"] = bool(same) and bool(np.any(P.H[last_k + 1:] >= P.up - EPS)) if last_k + 1 < 240 else False
        out["卖后最高%"] = round((mx_after / last_px - 1) * 100, 2)
        out["卖飞"] = bool(mx_after >= last_px * (1 + fly))
        out["止损"] = any(str(f[3]).startswith("stop") for f in fills)
        out["trail"] = any(str(f[3]).startswith("trail") for f in fills)
        out["eod_part"] = round(sum(f[2] for f in fills if f[3] == "EOD"), 3)
    else:
        out["to_close"] = round((close * (1 - cost) / (avg * (1 + cost)) - 1) * 100, 3)
        out["chase"] = round(sum(f[2] for f in fills if str(f[3]).startswith("chase")), 3)
        ref = P.C[k0] if k0 >= 0 else P.open
        out["踏空"] = bool(q < 0.5 - EPS and (close >= ref * 1.02 or hiA >= ref * 1.03))
        out["失败"] = bool(close < avg * 0.97)
    return out


def demo():
    E = R.RangeEngine()
    P = Path("600851", "2026-10-23")
    spec = {"side": "SELL", "deadline": "14:56", "rules": [
        {"id": "t1", "type": "limit", "qty": 0.5, "px_from": {"h": "60", "key": "最高", "q": 50}, "gate": {"type": "rebound", "red": 3, "rsi": 80}},
        {"id": "trail", "type": "cond", "qty": 0.5, "ref": "日内最高", "dir": "down", "pct": {"amp_k": 0.3}, "book": "b1", "after": "t1"},
        {"id": "stop", "type": "cond", "qty": 1.0, "ref": "@low", "dir": "down", "pct": 0.5, "book": "b1", "gate": {"type": "rebound", "red": 3, "rsi": 80}},
    ]}
    r = run(P, spec, R.hm2k("09:36"), E)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    print(evaluate(P, r, R.hm2k("09:36"), "SELL"))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = sys.argv[1:]
    if not a or a[0] == "demo":
        return demo()
    if a[0] == "run":
        code, D, hm, f = a[1:5]
        spec = json.loads(Path(f).read_text(encoding="utf-8"))
        P = Path(code, D)
        k0 = R.hm2k(hm)
        r = run(P, spec, k0, R.RangeEngine())
        print(json.dumps(r, ensure_ascii=False, indent=1))
        print(json.dumps(evaluate(P, r, k0, spec["side"]), ensure_ascii=False))


if __name__ == "__main__" and not (len(sys.argv) > 1 and sys.argv[1] == "selftest"):
    main()


# ---------------------------------------------------------------- 自测(断言撮合语义) ----------------------------------------------------------------
class _Fake:
    """合成路径: 给 O/H/L/C 序列, 其余特征用最简单的值(只测撮合, 不测信号)"""

    def __init__(self, bars, prev=10.0, up=11.0, dn=9.0, amp=0.04):
        n = len(bars)
        pad = [bars[-1]] * (240 - n)
        b = np.array(bars + pad, dtype=float)
        self.code, self.D, self.src = "600000", "2099-01-01", 1
        self.O, self.H, self.L, self.C = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
        self.open, self.prev, self.up, self.dn = float(b[0, 0]), prev, up, dn
        self.vw = np.full(240, b[0, 0])
        self.red = np.full(240, 5)
        self.rsi = np.full(240, 90.0)
        self.lo = np.minimum.accumulate(self.L)
        self.hi = np.maximum.accumulate(self.H)
        self.lo_at = np.zeros(240)
        self.vr = np.ones(240)
        self.n_open = np.zeros(240)
        self._amp = amp

    amp = Path.amp
    sealed_up = Path.sealed_up
    sealed_dn = Path.sealed_dn
    pts = Path.pts


def selftest():
    ok = True

    def chk(name, cond, got):
        nonlocal ok
        if not cond:
            ok = False
            print("FAIL", name, got)

    # ① 限价卖: 只碰到 = 50%, 穿过 = 全部
    P = _Fake([(10, 10.2, 9.9, 10.1), (10.1, 10.3, 10.0, 10.2), (10.2, 10.4, 10.1, 10.3)])
    r = run(P, {"side": "SELL", "rules": [{"id": "a", "type": "limit", "qty": 1.0, "px": 10.3}], "eod": "hold"}, 0)
    chk("碰到挂价 50%", r["fills"][0][2] == 0.5 and r["fills"][0][0] == 1, r["fills"])
    chk("下一根穿过 → 剩余全部", len(r["fills"]) == 2 and abs(r["pos"]) < 1e-9, r["fills"])
    # ② 跳空越过挂价 → 按开盘价成交(更好的价)
    P = _Fake([(10, 10.1, 9.9, 10.0), (10.5, 10.6, 10.4, 10.5)])
    r = run(P, {"side": "SELL", "rules": [{"id": "a", "type": "limit", "qty": 1.0, "px": 10.2}], "eod": "hold"}, 0)
    chk("跳空按开盘价", r["fills"] and r["fills"][0][1] == 10.5, r["fills"])
    # ③ 跌停封死卖不出(条件单)
    P = _Fake([(10, 10, 9.5, 9.5), (9.0, 9.0, 9.0, 9.0), (9.0, 9.0, 9.0, 9.0), (9.0, 9.3, 9.0, 9.2)], dn=9.0)
    r = run(P, {"side": "SELL", "rules": [{"id": "s", "type": "cond", "qty": 1.0, "ref": "昨收", "dir": "down", "pct": 5}], "eod": "hold"}, 0)
    chk("跌停封死不成交, 打开后成交", r["fills"] and r["fills"][0][0] == 3, r["fills"])
    # ④ 涨停封死买不进
    P = _Fake([(10.5, 11, 10.5, 11), (11, 11, 11, 11), (11, 11, 10.8, 10.9)], up=11.0)
    r = run(P, {"side": "BUY", "rules": [{"id": "b", "type": "market", "qty": 1.0}], "eod": "cancel"}, 0)
    chk("涨停封死买不进, 开板后买", r["fills"] and r["fills"][0][0] == 2, r["fills"])
    # ⑤ 移动止盈: 日内最高(生效后)回落 2% 卖
    P = _Fake([(10, 10.1, 9.9, 10.0), (10.0, 10.5, 10.0, 10.5), (10.5, 10.6, 10.5, 10.6), (10.6, 10.6, 10.3, 10.35)])
    r = run(P, {"side": "SELL", "rules": [{"id": "trail", "type": "cond", "qty": 1.0, "ref": "日内最高", "dir": "down", "pct": 2}], "eod": "hold"}, 0)
    chk("移动止盈在 10.6×0.98 下方一分成交", r["fills"] and r["fills"][0][0] == 3 and abs(r["fills"][0][1] - 10.38) < 1e-6, r["fills"])
    # ⑥ 涨停价回落 (arm): 没碰过涨停不触发
    P = _Fake([(10, 10.5, 9.9, 10.4), (10.4, 10.5, 10.0, 10.1)], up=11.0)
    r = run(P, {"side": "SELL", "rules": [{"id": "z", "type": "cond", "qty": 1.0, "ref": "涨停价", "dir": "down", "pct": 3}], "eod": "hold"}, 0)
    chk("没碰涨停不触发", not r["fills"], r["fills"])
    P = _Fake([(10, 11, 9.9, 11), (11, 11, 10.6, 10.65)], up=11.0)
    r = run(P, {"side": "SELL", "rules": [{"id": "z", "type": "cond", "qty": 1.0, "ref": "涨停价", "dir": "down", "pct": 3}], "eod": "hold"}, 0)
    chk("碰过涨停后回落 3% 触发", r["fills"] and abs(r["fills"][0][1] - 10.67) < 1e-6, r["fills"])
    # ⑦ after: t2 只在 t1 成交后生效; unless_filled: 低吸成交后防踏空作废
    P = _Fake([(10, 10.1, 9.9, 10.0), (10.0, 10.0, 9.7, 9.8), (9.8, 10.3, 9.8, 10.3)])
    r = run(P, {"side": "BUY", "rules": [{"id": "b1", "type": "limit", "qty": 0.5, "px": 9.75},
                                         {"id": "chase", "type": "cond", "qty": 0.5, "ref": "日内最低", "dir": "up", "pct": 3, "unless_filled": ["b1"]}], "eod": "cancel"}, 0)
    chk("低吸成交后不追", [f[3] for f in r["fills"]] == ["b1"], r["fills"])
    P = _Fake([(10, 10.1, 9.9, 10.0), (10.0, 10.0, 9.8, 9.85), (9.85, 10.3, 9.85, 10.3)])
    r = run(P, {"side": "BUY", "rules": [{"id": "b1", "type": "limit", "qty": 0.5, "px": 9.75},
                                         {"id": "chase", "type": "cond", "qty": 0.5, "ref": "日内最低", "dir": "up", "pct": 3, "unless_filled": ["b1"]}], "eod": "cancel"}, 0)
    chk("低吸没成交, 反弹 3% 追", [f[3] for f in r["fills"]] == ["chase"] and r["fills"][0][0] == 2, r["fills"])
    # ⑧ 不偷看: 决策 k0 之前的路径不影响 k0 之后的撮合起点
    P = _Fake([(10, 12, 8, 10), (10, 10.05, 9.95, 10)])
    r = run(P, {"side": "SELL", "rules": [{"id": "a", "type": "limit", "qty": 1.0, "px": 11}], "eod": "hold"}, 0)
    chk("k0 那根的高点不算成交", not r["fills"], r["fills"])
    print("bracket_sim selftest", "OK" if ok else "FAIL")
    return ok


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "selftest":
    sys.exit(0 if selftest() else 1)
