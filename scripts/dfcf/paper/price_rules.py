# -*- coding: utf-8 -*-
"""price_rules.py — 挂价交给规则(TODO 三-2b, 10/17 ② agent; 零 token, 只读)

LLM 在 06 只选"挂法"(style), 价格由本模块按导师去偏挂单深度 + 当时快照机械算; 改单 = 挂出 X 分钟没成交向现价靠一半(只一次)。
消费方: scripts/dfcf/paper/quality_hooks.py(驱动器开关 CHAIN_PRICE_RULES, 默认 0; 关=驱动器不 import)。

挂法(style) → 价格:
  追价  买=现价×(1+chase_pad) 向上取价位, 卖=现价×(1−chase_pad) 向下取; 不超涨停/跌停与连续竞价价格笼子(a_rules.price_cage)。
        盘前单(0915 主链)的"现价"=快照 last(竞价期为虚拟匹配价, 拿不到=前收)。
  低吸  被动挂单(卖单=挂高等): 买=锚×(1−k×A), 卖=锚×(1+k×A); A=该票前 30 个交易日振幅(高−低)/昨收 的中位数(与 order_inference 同口径),
        k=导师去偏深度系数 depth_amp_ipw P50(orders_inferred.json; 先按打法, 有效样本<10 退该导师全体, 再退全体导师中位)。
        锚: 盘前单=前收(报告 §6.7: 开盘急杀里成交的单更像按昨收挂的), 盘中=现价。取不到 A 时用导师绝对深度 depth_ipw P50。
        结果夹在 (跌停价, 锚−1 价位] (买) / [锚+1 价位, 涨停价) (卖)。
        附 reprice=X 分钟: X=clamp(导师被动单存续上界中位 rest_upper_min.p50, REPRICE_MIN, REPRICE_MAX)(matcher 执行: 到点未成交, 价格向现价靠一半, 只一次)。
  排板  买=涨停价(matcher: 封板排队, 开板才成交); 卖单不许排板。
  开盘  只在盘前单有效: 买=参考价×(1+open_pad) 封顶涨停(集合竞价按开盘价成交的意图, paper 撮合按挂价记账=保守);
        卖=改为 op "开盘卖"(市价卖, 已有动词)。盘中写"开盘"=按"追价"处理并注明。

CLI(scripts/venv/Scripts/python.exe -X utf8):
  price_rules.py --show [--skill gaogailvfuli]      各导师挂法分布/k/X 参数表
  price_rules.py --quote --skill liuyiqing --code 600000 --prev 10 --last 10.2 [--slot 0915] [--side 买]   四种挂法的规则价
  price_rules.py --selftest
"""
import argparse
import json
import math
import statistics
import sys
from datetime import date as _date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKILLS = ROOT / "skills"
DAILY = ROOT / "downloads" / "quotes" / "daily"
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import a_rules as AR  # noqa: E402

STYLES = ("追价", "低吸", "排板", "开盘")
ALIAS = {"chase": "追价", "对价": "追价", "主动": "追价", "主动追价": "追价", "市价": "追价",
         "passive": "低吸", "被动": "低吸", "挂低": "低吸", "挂高": "低吸", "挂单": "低吸", "被动限价": "低吸", "高抛": "低吸",
         "limit_up": "排板", "打板": "排板", "封板": "排板",
         "open": "开盘", "auction": "开盘", "竞价": "开盘", "集合竞价": "开盘"}
CHASE_PAD = 0.002          # 追价垫价(对价单约等于卖一/买一, 0.2% 近似 1~2 档)
OPEN_PAD = 0.01            # 开盘买垫价(集合竞价"保证成交"意图)
REPRICE_MIN, REPRICE_MAX = 3, 30   # 改单等待分钟数夹逼(导师存续上界中位多为 1~20 分钟; 下限 3 防 1 分钟撮合粒度下瞬间追价)
ESS_MIN = 10               # 去偏有效样本量下限(同 order_inference 报告的 † 口径)
N_PLAY_MIN = 8
AMP_WIN, AMP_MIN_N = 30, 10
MODE_CN = {"集合竞价": "开盘", "排板": "排板", "被动限价": "低吸", "主动追价": "追价", "改单追上": "追价"}

_PROF, _POOLED = {}, {}


def norm_style(s):
    s = str(s or "").strip()
    return s if s in STYLES else ALIAS.get(s) or ALIAS.get(s.lower())


def _jl(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _q(block, key, p="p50"):
    v = ((block or {}).get(key) or {}).get(p)
    return float(v) if isinstance(v, (int, float)) else None


def _side_params(block):
    """一个 orders_inferred 分组(all 或 by_play[x]) → {k, k25, k75, depth, rest, mode, n, ess, src}"""
    if not block:
        return None
    ess = float(block.get("ess_ipw") or 0)
    use_ipw = ess >= ESS_MIN
    k = _q(block, "depth_amp_ipw" if use_ipw else "depth_amp_raw")
    out = {"k": k, "k25": _q(block, "depth_amp_ipw" if use_ipw else "depth_amp_raw", "p25"),
           "k75": _q(block, "depth_amp_ipw" if use_ipw else "depth_amp_raw", "p75"),
           "depth": _q(block, "depth_ipw" if use_ipw else "depth_raw"), "rest": _q(block, "rest_upper_min"),
           "mode": block.get("mode") or {}, "n": int(block.get("n") or 0), "ess": ess, "src": "去偏" if use_ipw else "成交口径(ESS<10)"}
    return out


def profile(skill):
    """导师挂单画像 {buy:{all, by_play}, sell:{all}, file} ; 无 orders_inferred(B站 UP/对照组)=None"""
    if skill in _PROF:
        return _PROF[skill]
    d = _jl(SKILLS / f"{skill}-skill" / "persona" / "orders_inferred.json")
    p = None
    if d:
        p = {"file": f"skills/{skill}-skill/persona/orders_inferred.json", "generated": d.get("generated")}
        for side in ("buy", "sell"):
            blk = d.get(side) or {}
            p[side] = {"all": _side_params(blk.get("all")),
                       "by_play": {k: _side_params(v) for k, v in (blk.get("by_play") or {}).items()
                                   if int(v.get("n") or 0) >= N_PLAY_MIN and float(v.get("ess_ipw") or 0) >= ESS_MIN}}
    _PROF[skill] = p
    return p


def pooled(side):
    """全体导师中位(无画像导师/缺字段兜底)"""
    if side in _POOLED:
        return _POOLED[side]
    ks, ds, rs, modes = [], [], [], {}
    for f in sorted(SKILLS.glob("*-skill/persona/orders_inferred.json")):
        p = profile(f.parent.parent.name[:-6])
        a = (p or {}).get(side, {}).get("all") if p else None
        if not a:
            continue
        if a.get("ess", 0) >= ESS_MIN and a.get("k") is not None:
            ks.append(a["k"])
        if a.get("depth") is not None:
            ds.append(a["depth"])
        if a.get("rest") is not None:
            rs.append(a["rest"])
        for m, v in (a.get("mode") or {}).items():
            modes.setdefault(m, []).append(float(v))
    out = {"k": statistics.median(ks) if ks else 0.15, "depth": statistics.median(ds) if ds else 0.005,
           "rest": statistics.median(rs) if rs else 5.0, "mode": {m: round(statistics.median(v), 3) for m, v in modes.items()},
           "n": len(ks), "src": f"全体导师中位(n={len(ks)})"}
    _POOLED[side] = out
    return out


def params_for(skill, side, play=None):
    """返回 (参数 dict, 来源说明)。side=buy|sell"""
    p = profile(skill)
    base = pooled(side)
    if not p or not p.get(side, {}).get("all"):
        return dict(base), base["src"]
    a = dict(p[side]["all"])
    src = f"{skill} 全体{a['src']}"
    if play and play in p[side].get("by_play", {}):
        bp = p[side]["by_play"][play]
        if bp.get("k") is not None:
            a.update({k: bp[k] for k in ("k", "k25", "k75", "depth") if bp.get(k) is not None})
            src = f"{skill}·{play}{bp['src']}"
    if a.get("k") is None or a.get("ess", 0) < ESS_MIN:
        a["k"], src = base["k"], src + "→k 退全体中位"
    for k in ("depth", "rest"):
        if a.get(k) is None:
            a[k] = base[k]
    return a, src


def amp30(code, date_dash, kdir=None):
    """该票 date_dash 之前 30 个交易日 (高−低)/昨收 中位数; 样本 <10 = None"""
    try:
        k = [x for x in json.loads(Path(kdir or DAILY, f"{code}.json").read_text(encoding="utf-8"))["klines"] if x["d"] < date_dash]
    except (OSError, ValueError, KeyError):
        return None
    xs = [(b["h"] - b["l"]) / a["c"] for a, b in zip(k[-AMP_WIN - 1:-1], k[-AMP_WIN:]) if a.get("c") and b.get("h") and b.get("l")]
    return statistics.median(xs) if len(xs) >= AMP_MIN_N else None


def _tick_round(px, code, up):
    t = AR.tick(code)
    n = px / t
    n = math.ceil(n - 1e-9) if up else math.floor(n + 1e-9)
    return round(n * t, AR.price_decimals(code))


def reprice_minutes(skill, side="buy"):
    a, _ = params_for(skill, side)
    r = a.get("rest") or REPRICE_MIN
    return int(min(REPRICE_MAX, max(REPRICE_MIN, round(r))))


def rule_price(skill, op, style, snap, code, date_dash, preopen, play=None, kdir=None):
    """→ dict(ok, px, style, op, ref, ref_src, k, amp, depth, reprice, why) 或 dict(ok=False, err)。
    op=买|卖; snap={prevClose,last,...}; preopen=盘前单(0915 主链, 09:30 前挂出)"""
    st = norm_style(style)
    if not st:
        return {"ok": False, "err": f"挂法 style 只许 {'/'.join(STYLES)}: {style}"}
    buy = op == "买"
    side = "buy" if buy else "sell"
    prev = float((snap or {}).get("prevClose") or 0)
    last = float((snap or {}).get("last") or 0)
    if prev <= 0:
        return {"ok": False, "err": f"{code} 无前收快照, 规则价算不了"}
    name = (snap or {}).get("name") or None
    up, dn = AR.limit_prices(code, date_dash, prev, name=name, lookup=False)
    t = AR.tick(code)
    cur = last if last > 0 else prev
    cur_src = "现价" if last > 0 else "前收(无现价)"
    out = {"ok": True, "style": st, "op": op, "reprice": None, "k": None, "amp": None, "depth": None}

    def clamp(px):
        if up is not None:
            px = min(px, up)
        if dn is not None:
            px = max(px, dn)
        return round(px, AR.price_decimals(code))

    def cage(px, base):
        if preopen:   # 盘前单走集合竞价, 不吃连续竞价笼子(同 matcher 审计#1)
            return px
        lim = AR.price_cage(code, date_dash, "BUY" if buy else "SELL", base)
        if lim is None:
            return px
        return min(px, lim) if buy else max(px, lim)

    if st == "开盘" and not preopen:
        st, out["style"] = "追价", "追价"
        out["note"] = "盘中写开盘=按追价处理"
    if st == "排板":
        if not buy:
            return {"ok": False, "err": "卖单不能排板(排板=涨停价排队买入); 卖出用 追价/低吸(挂高)/开盘"}
        if up is None:
            return {"ok": False, "err": f"{code} 无涨跌幅限制(新股/特殊品种), 不能排板"}
        out.update(px=up, ref=prev, ref_src="前收", why=f"排板=涨停价 {up:g}(封板排队, 开板才成交)")
        return out
    if st == "开盘":
        ref = cur
        if not buy:
            out.update(op="开盘卖", px=_tick_round(ref, code, False), ref=ref, ref_src=cur_src,
                       why=f"开盘卖=市价卖(挂价列=参考 {ref:g})")
            return out
        px = clamp(_tick_round(ref * (1 + OPEN_PAD), code, True))
        out.update(px=px, ref=ref, ref_src=("竞价参考价" if last > 0 else "前收"),
                   why=f"开盘买=参考 {ref:g}×(1+{OPEN_PAD:.1%}) 封顶涨停 → {px:g}(paper 按挂价记账, 偏保守)")
        return out
    if st == "追价":
        ref = cur
        raw = ref * (1 + CHASE_PAD) if buy else ref * (1 - CHASE_PAD)
        px = _tick_round(raw, code, buy)
        if buy and px <= ref:
            px = round(ref + t, AR.price_decimals(code))
        if not buy and px >= ref:
            px = round(ref - t, AR.price_decimals(code))
        px = clamp(cage(px, ref))
        out.update(px=px, ref=ref, ref_src=cur_src, why=f"追价={cur_src} {ref:g}{'+' if buy else '−'}{CHASE_PAD:.1%} → {px:g}(笼子/涨跌停内)")
        out.update(out.get("note") and {"why": out["why"] + "; " + out["note"]} or {})
        return out
    # 低吸(被动)
    a, src = params_for(skill, side, play)
    ref, ref_src = (prev, "前收(盘前单)") if preopen else (cur, cur_src)
    amp = amp30(code, date_dash, kdir)
    if amp is not None and a.get("k") is not None:
        depth = a["k"] * amp
        how = f"k={a['k']:.3f}×30日振幅中位 {amp:.2%}"
    else:
        depth = float(a.get("depth") or 0.005)
        how = f"导师绝对深度 {depth:.2%}(无振幅)"
    raw = ref * (1 - depth) if buy else ref * (1 + depth)
    px = _tick_round(raw, code, not buy)
    if buy:
        px = min(px, round(ref - t, AR.price_decimals(code)))
    else:
        px = max(px, round(ref + t, AR.price_decimals(code)))
    px = clamp(px)
    if buy and dn is not None and px <= dn:
        px = round(dn + t, AR.price_decimals(code))
    if not buy and up is not None and px >= up:
        px = round(up - t, AR.price_decimals(code))
    rp = reprice_minutes(skill, side)
    out.update(px=px, ref=ref, ref_src=ref_src, k=a.get("k"), amp=amp, depth=round(depth, 5), reprice=rp, src=src,
               why=f"{'低吸' if buy else '挂高'}={ref_src} {ref:g}×(1{'−' if buy else '+'}{depth:.2%}) [{how}; {src}] → {px:g}; "
                   f"挂出 {rp} 分钟未成交向现价靠一半(只一次)")
    return out


def quote_all(skill, op, snap, code, date_dash, preopen, play=None, kdir=None):
    """四种挂法的规则价(06 prompt 价格表用); 不适用的挂法=None"""
    res = {}
    for st in STYLES:
        r = rule_price(skill, op, st, snap, code, date_dash, preopen, play, kdir)
        res[st] = r if r.get("ok") else None
    return res


def mode_line(skill, side="buy"):
    """导师成交方式分布 → 挂法占比(其他/证据不足 单列)"""
    p = profile(skill)
    a = (p or {}).get(side, {}).get("all") if p else None
    mode = (a or {}).get("mode") or pooled(side)["mode"]
    agg = {}
    for m, v in mode.items():
        agg[MODE_CN.get(m, "其他")] = agg.get(MODE_CN.get(m, "其他"), 0.0) + float(v)
    order = ["开盘", "排板", "低吸", "追价", "其他"]
    src = "本导师" if a else "全体导师中位(本链无真人挂单数据)"
    return src + ": " + " / ".join(f"{k} {agg[k]:.0%}" for k in order if k in agg)


# ---------------------------------------------------------------- CLI
def _show(only=None):
    rows = []
    for f in sorted(SKILLS.glob("*-skill/persona/orders_inferred.json")):
        sk = f.parent.parent.name[:-6]
        if only and sk != only:
            continue
        b, sb = params_for(sk, "buy")
        s, ss = params_for(sk, "sell")
        rows.append(f"| {sk} | {mode_line(sk, 'buy')} | {b['k']:.3f} ({sb}) | {s['k']:.3f} ({ss}) | {reprice_minutes(sk, 'buy')}/{reprice_minutes(sk, 'sell')} |")
    print("| 导师 | 买入挂法分布 | 买 k | 卖 k | 改单 X(买/卖, 分) |\n|---|---|---|---|---|\n" + "\n".join(rows))
    pb = pooled("buy")
    print(f"\n全体中位兜底: 买 k={pb['k']:.3f} 深度={pb['depth']:.2%} 存续={pb['rest']}")


def selftest():
    import tempfile
    fails = []

    def chk(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="price_rules_"))
    # 合成日线: 前 30 日振幅恒 4%(h-l=0.4, 昨收 10)
    kl = [{"d": f"2026-09-{i:02d}", "o": 10, "c": 10, "h": 10.2, "l": 9.8} for i in range(1, 31)]
    (tmp / "600000.json").write_text(json.dumps({"klines": kl}), encoding="utf-8")
    (tmp / "113052.json").write_text(json.dumps({"klines": [dict(x, c=120, h=122.4, l=117.6) for x in kl]}), encoding="utf-8")
    chk("amp30=4%", abs(amp30("600000", "2026-10-01", tmp) - 0.04) < 1e-9)
    chk("amp30 样本不足=None", amp30("600000", "2026-09-05", tmp) is None)
    snap = {"prevClose": 10.0, "last": 10.2, "name": "测试"}
    d = "2026-10-16"
    # 低吸: 盘前锚=前收, 盘中锚=现价
    r0 = rule_price("gaogailvfuli", "买", "低吸", snap, "600000", d, True, kdir=tmp)
    k = params_for("gaogailvfuli", "buy")[0]["k"]
    chk("低吸 盘前锚前收", r0["ok"] and r0["ref"] == 10.0 and abs(r0["px"] - math.floor(10 * (1 - k * 0.04) * 100 + 1e-9) / 100) < 1e-9)
    r1 = rule_price("gaogailvfuli", "买", "低吸", snap, "600000", d, False, kdir=tmp)
    chk("低吸 盘中锚现价且低于现价", r1["ok"] and r1["ref"] == 10.2 and r1["px"] < 10.2 and r1["reprice"] >= REPRICE_MIN)
    chk("低吸 改单 X 在夹逼区间", REPRICE_MIN <= r1["reprice"] <= REPRICE_MAX)
    r2 = rule_price("gaogailvfuli", "卖", "挂高", snap, "600000", d, False, kdir=tmp)
    chk("卖 挂高>现价", r2["ok"] and r2["px"] > 10.2 and r2["style"] == "低吸")
    # 深挂型(刘忆青)比浅挂型(星见野)深
    rl = rule_price("liuyiqing", "买", "低吸", snap, "600000", d, False, kdir=tmp)
    rx = rule_price("xingjianye", "买", "低吸", snap, "600000", d, False, kdir=tmp)
    chk("刘忆青挂得比星见野深", rl["px"] < rx["px"])
    # 追价: 买≥现价+1价位, 不超笼子/涨停
    r3 = rule_price("a658", "买", "追价", snap, "600000", d, False, kdir=tmp)
    chk("追价买 > 现价且 ≤ 现价×1.02", r3["ok"] and 10.2 < r3["px"] <= 10.2 * 1.02 + 1e-9)
    r3s = rule_price("a658", "卖", "追价", snap, "600000", d, False, kdir=tmp)
    chk("追价卖 < 现价", r3s["ok"] and r3s["px"] < 10.2)
    r3u = rule_price("a658", "买", "追价", {"prevClose": 10.0, "last": 10.99}, "600000", d, False, kdir=tmp)
    chk("追价买封顶涨停 11.00", r3u["px"] == 11.0)
    # 排板
    r4 = rule_price("stzhilang", "买", "排板", snap, "600000", d, True, kdir=tmp)
    chk("排板=涨停价 11.00", r4["ok"] and r4["px"] == 11.0)
    chk("卖单排板=错", not rule_price("stzhilang", "卖", "排板", snap, "600000", d, True)["ok"])
    r4b = rule_price("stzhilang", "买", "排板", {"prevClose": 120.0, "last": 121}, "113052", d, True, kdir=tmp)
    chk("转债排板=+20% 144.000", r4b["ok"] and abs(r4b["px"] - 144.0) < 1e-9)
    # 开盘
    r5 = rule_price("liuyiqing", "买", "开盘", {"prevClose": 10.0, "last": 0}, "600000", d, True, kdir=tmp)
    chk("开盘买=前收×1.01=10.10", r5["ok"] and r5["px"] == 10.1)
    r5s = rule_price("liuyiqing", "卖", "开盘", snap, "600000", d, True, kdir=tmp)
    chk("开盘卖→op 开盘卖", r5s["ok"] and r5s["op"] == "开盘卖")
    r5i = rule_price("liuyiqing", "买", "开盘", snap, "600000", d, False, kdir=tmp)
    chk("盘中开盘=追价", r5i["ok"] and r5i["style"] == "追价")
    # 兜底: 无画像(对照组)用全体中位; 无振幅用绝对深度
    r6 = rule_price("control", "买", "低吸", snap, "600000", d, False, kdir=tmp)
    chk("对照组走全体中位", r6["ok"] and "全体导师中位" in r6["src"])
    r7 = rule_price("gaogailvfuli", "买", "低吸", snap, "000002", d, False, kdir=tmp)
    chk("无振幅=绝对深度", r7["ok"] and r7["amp"] is None and r7["px"] < 10.2)
    chk("非法挂法=错", not rule_price("a658", "买", "乱写", snap, "600000", d, False)["ok"])
    chk("无前收=错", not rule_price("a658", "买", "追价", {"last": 10}, "600000", d, False)["ok"])
    chk("别名 打板→排板", norm_style("打板") == "排板" and norm_style("chase") == "追价")
    # 低吸价格不穿跌停
    r8 = rule_price("liuyiqing", "买", "低吸", {"prevClose": 10.0, "last": 9.05}, "600000", d, False, kdir=tmp)
    chk("低吸不穿跌停", r8["px"] > 9.0)
    chk("mode_line 有低吸占比", "低吸" in mode_line("gaogailvfuli"))
    print("SELFTEST " + ("PASS" if not fails else f"FAIL {fails}"))
    return 0 if not fails else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--quote", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--skill")
    ap.add_argument("--code")
    ap.add_argument("--prev", type=float)
    ap.add_argument("--last", type=float, default=0)
    ap.add_argument("--slot", default="1000")
    ap.add_argument("--side", default="买")
    ap.add_argument("--date", default=_date.today().isoformat())
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if a.show:
        _show(a.skill)
        return
    if a.quote:
        q = quote_all(a.skill, a.side, {"prevClose": a.prev, "last": a.last}, a.code, a.date, a.slot == "0915")
        for st, r in q.items():
            print(f"{st}: {r['px'] if r else '—'}  {r['why'] if r else ''}")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
