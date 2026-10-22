# -*- coding: utf-8 -*-
"""quality_hooks.py — 决策质量新功能的驱动器接入层(10/17 ② agent; 零 token)

驱动器 scripts/chain/run_chain.py 只做三件事(补丁 scripts/temp/b_patch/apply_quality.py 打进去):
  ① prompt 末尾追加 block(step, ctx, qf)          ② VALIDATORS["06"] 外包一层: pre06 → 原校验 → post06
  ③ emit_plans 把 a["_reprice"] 写成 cond reprice=N、把 a["_style"] 写进 note
开关(chain_flags.txt, 全部默认 0; 关=本模块不被调用, 驱动器逐字节旧行为):
  CHAIN_PRICE_RULES    2b 挂价交给规则: 06 每个买/卖写 style(追价/低吸/排板/开盘), 价格由 price_rules 算, 低吸单带改单生命周期
  CHAIN_SLOT_BUDGET    2c 出手时段跟真人走: 04/06 注入时段分布; 0915 立即生效新开仓金额超预算只提醒记账(10/17 A12 起不回炉)
  CHAIN_T_PROFILE      2e T 法: 04/06 注入 T 法画像; "不学T"导师禁同票日内回转(软闸, 回炉一次)
  CHAIN_SIMILAR_DAYS   2f 相似市况: 0915 主链 02/04 注入相似 3 天 + 导师当时怎么做
  CHAIN_OVERRIDE_LOCK  override 锁层: overrides/locks.json 锁住的层, 06 必须接受基线(需 CHAIN_LEDGER_CONSTRAINTS 开着才有基线; 硬闸, 末次放行)
  CHAIN_RULE_CHECK     三-3 第二期: 引用规则方向与动作相符 + 机械触发规则漏用(rule_tags; 软闸, 回炉一次)
ctx 约定(补丁在 run_chain 起跑时写): ctx["_q"] = {"slot", "skill", "watch"(facts 持仓快照)}; 其余用驱动器已有键
  (date_dash/sub/nav/book/pc/snap/ledger/contracts/final_attempt/_soft_seen)。任何异常 = 该功能本次不生效(fail-open, 打 WARN)。
"""
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
FLAGS = ("CHAIN_PRICE_RULES", "CHAIN_SLOT_BUDGET", "CHAIN_T_PROFILE", "CHAIN_SIMILAR_DAYS", "CHAIN_OVERRIDE_LOCK", "CHAIN_RULE_CHECK", "CHAIN_RISK_SIZE")
SELL_OPS = ("卖", "开盘卖")
LOG_DIR = {"price": HERE / "price_rules", "quality": HERE / "quality_log"}
_WARNED = set()


def _warn(key, e):
    if key not in _WARNED:
        _WARNED.add(key)
        print(f"WARN: quality_hooks {key} 异常(本功能本次不生效, fail-open): {e} {traceback.format_exc()[-300:]}")


def _soft_once(ctx, key):
    """同驱动器 _soft_once: 首次命中回炉, 再命中或末次尝试放行"""
    if ctx.get("final_attempt"):
        return True
    seen = ctx.setdefault("_soft_seen", set())
    if key in seen:
        return True
    seen.add(key)
    return False


def _q(ctx):
    return ctx.get("_q") or {}


def _skill(ctx):
    return _q(ctx).get("skill") or ""


def _slot(ctx):
    return _q(ctx).get("slot") or ("1000" if ctx.get("sub") else "0915")


def _preopen(ctx):
    return _slot(ctx) == "0915" and not ctx.get("sub")


def _nav(ctx):
    return float((ctx.get("pc") or {}).get("nav") or ctx.get("nav") or 0) or 0.0


def _snap_of(ctx, code):
    s = (ctx.get("snap") or {}).get(code) or (_q(ctx).get("watch") or {}).get(code)
    return s if s and float(s.get("prevClose") or 0) > 0 else None


def log(kind, ctx, rec, base=None):
    if ctx.get("_shadow"):
        rec = {**rec, "shadow": True}
    try:
        d = Path(base or LOG_DIR.get(kind, LOG_DIR["quality"]))
        d.mkdir(parents=True, exist_ok=True)
        with (d / f"{ctx.get('date_dash') or datetime.now().strftime('%Y-%m-%d')}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), "skill": _skill(ctx), "slot": _slot(ctx), "sub": bool(ctx.get("sub")),
                                "kind": kind, **rec}, ensure_ascii=False, default=list) + "\n")
    except Exception:   # noqa: BLE001
        pass


# ================================================================ prompt 块
def block(step, ctx, qf):
    out = []
    for name, fn in (("CHAIN_SIMILAR_DAYS", _blk_similar), ("CHAIN_SLOT_BUDGET", _blk_slot), ("CHAIN_T_PROFILE", _blk_t),
                     ("CHAIN_PRICE_RULES", _blk_price), ("CHAIN_OVERRIDE_LOCK", _blk_lock), ("CHAIN_RULE_CHECK", _blk_rule)):
        if not qf.get(name):
            continue
        try:
            t = fn(step, ctx)
        except Exception as e:   # noqa: BLE001
            _warn(f"block {name}", e)
            t = ""
        if t:
            out.append(t)
    if not out:
        return ""
    return "\n\n# 驱动器注入: 决策质量参考(10/17; 数字全由驱动器机械算)\n" + "\n".join(out)


def _blk_similar(step, ctx):
    if step not in ("02", "04") or ctx.get("sub") or _skill(ctx) == "control":
        return ""
    import similar_days as S
    return S.text_block(_skill(ctx), ctx["date_dash"])


def _blk_slot(step, ctx):
    if step not in ("04", "06"):
        return ""
    import slot_profile as P
    return P.text_block(_skill(ctx), ctx["date_dash"], _slot(ctx), _nav(ctx), bool(ctx.get("sub")))


def _blk_t(step, ctx):
    if step != "06" and not (step == "04" and ctx.get("sub")):   # 0915 只在 06 注入(省 token); 子链 04 也要(盘中 T 在 04 定方案)
        return ""
    import t_profile as T
    return T.text_block(_skill(ctx), ctx["date_dash"], bool(ctx.get("sub")))


def _codes_for_table(ctx, cap=12):
    codes = []
    for c in list((ctx.get("snap") or {}).keys()) + list(((ctx.get("book") or {}).get("positions") or {}).keys()):
        c = str(c)
        if c not in codes and _snap_of(ctx, c):
            codes.append(c)
    return codes[:cap]


def _blk_price(step, ctx):
    if step != "06":
        return ""
    import price_rules as PR
    sk, pre = _skill(ctx), _preopen(ctx)
    held = set(((ctx.get("book") or {}).get("positions") or {}).keys())
    L = ["- **挂价交给规则(本链已开)**: 每个买/卖 action 必须写 \"style\": \"追价\"|\"低吸\"|\"排板\"|\"开盘\"(卖单的\"低吸\"=挂高等卖); "
         "价格由驱动器按本导师去偏挂单深度+当时快照机械算(trigger_price 可不写, 写了也会被规则价覆盖, 只留档对比); "
         "低吸单挂出一段时间没成交, 撮合会自动向现价靠一半(只一次)。你只需决定: 买不买/卖不卖、多少量、用哪种挂法。",
         f"  - 本导师真人挂法分布(买单, orders_inferred): {PR.mode_line(sk, 'buy')}——挂法比例尽量像他",
         "  - 开盘=只在盘前单有效(买=参考价+1% 保证开盘成交; 卖=改成开盘卖市价); 排板=涨停价排队(只许买); 追价=现价附近立即成交",
         "  - cancel_below(买单失效线)必须低于规则价; 下表是此刻各票四种挂法的规则价(驱动器校验时会按同一快照重算):"]
    rows = []
    for c in _codes_for_table(ctx):
        s = _snap_of(ctx, c)
        qb = PR.quote_all(sk, "买", s, c, ctx["date_dash"], pre)
        cell = lambda r: "—" if not r else f"{r['px']:g}"
        line = f"    - {c} {s.get('name') or ''}(前收 {s.get('prevClose')}, 现 {s.get('last')}): 买 追价 {cell(qb['追价'])} / 低吸 {cell(qb['低吸'])} / 排板 {cell(qb['排板'])}" \
               + (f" / 开盘 {cell(qb['开盘'])}" if pre else "")
        if c in held:
            qs = PR.quote_all(sk, "卖", s, c, ctx["date_dash"], pre)
            line += f"; 卖 追价 {cell(qs['追价'])} / 挂高 {cell(qs['低吸'])}" + (" / 开盘=开盘卖(市价)" if pre else "")
        rows.append(line)
    return "\n".join(L + (rows or ["    - (此刻无可用快照, 规则价在校验时现算)"]))


def _blk_lock(step, ctx):
    if step != "06":
        return ""
    import override_stats as O
    lk = O.locks_of(_skill(ctx))
    if not lk:
        return ""
    cn = {"L1": "出手", "L2": "方向", "L3": "选股打法", "L4": "总仓"}
    return ("- **override 锁层**: 你近 20 个交易日改基线的 " + "、".join(f"{L}({cn.get(L, L)}, 净 {v.get('net20')})" for L, v in sorted(lk.items()))
            + " 改得比基线差(拟人度净负) → 这些层今天必须接受统计基线, 不许写 override 改它们(驱动器校验)")


def _blk_rule(step, ctx):
    if step != "06":
        return ""
    import rule_tags as R
    return R.text_block(_skill(ctx), ctx)


# ================================================================ 06 校验
def wrap06(fn, qf):
    def v_quality(c, ctx):
        e = pre06(c, ctx, qf)
        if e:
            return e
        return fn(c, ctx) or post06(c, ctx, qf)
    v_quality.__wrapped__ = fn
    return v_quality


def pre06(c, ctx, qf):
    if not qf.get("CHAIN_PRICE_RULES"):
        return None
    try:
        return _price_pre(c, ctx)
    except Exception as e:   # noqa: BLE001
        _warn("pre06 price", e)
        return None


def _price_pre(c, ctx):
    import price_rules as PR
    sk, pre = _skill(ctx), _preopen(ctx)
    miss, conflicts, recs = [], [], []
    for a in c.get("actions") or []:
        op = a.get("op")
        if op not in ("买", "卖", "开盘卖"):
            continue
        code = str(a.get("code") or "")
        st = PR.norm_style(a.get("style")) if a.get("style") is not None else ("开盘" if op == "开盘卖" else None)
        if not st:
            miss.append(f"{a.get('name') or code}" + (f"(style={a.get('style')} 不认识)" if a.get("style") is not None else ""))
            continue
        s = _snap_of(ctx, code)
        if not s:
            recs.append({"code": code, "style": st, "skip": "无快照, 沿用 LLM 价"})
            continue
        r = PR.rule_price(sk, "买" if op == "买" else "卖", st, s, code, ctx["date_dash"], pre, a.get("play") or a.get("打法"))
        if not r.get("ok"):
            conflicts.append(f"{a.get('name') or code}: {r.get('err')}")
            continue
        llm_px = a.get("trigger_price")
        if r["op"] == "开盘卖":
            a["op"] = "开盘卖"
            a.setdefault("anchor", r["px"])
            a["trigger_price"] = None
        else:
            if op == "开盘卖":   # 开盘卖但写了别的 style → 按 style 改回普通卖
                a["op"] = "卖"
            a["trigger_price"] = f"{r['px']:g}"
        if a.get("anchor") in (None, ""):
            a["anchor"] = float(s.get("last") or s.get("prevClose"))
        a["_style"], a["_reprice"] = r["style"], r.get("reprice")
        if a.get("op") == "买" and isinstance(a.get("cancel_below"), (int, float)) and a["cancel_below"] >= r["px"]:
            if _soft_once(ctx, f"q_cb_{code}"):
                print(f"WARN: {a.get('name')} cancel_below {a['cancel_below']} ≥ 规则价 {r['px']}, 末次放行: 去掉 cancel_below")
                a["cancel_below"] = None
            else:
                conflicts.append(f"{a.get('name') or code}: cancel_below {a['cancel_below']} 不低于规则价 {r['px']}({r['style']}), 失效线要低于挂价")
        recs.append({"code": code, "op": a["op"], "style": r["style"], "rule_px": r["px"], "llm_px": llm_px, "ref": r.get("ref"),
                     "k": r.get("k"), "amp": r.get("amp"), "reprice": r.get("reprice"), "why": r.get("why")})
    if recs:
        log("price", ctx, {"actions": recs, "attempt_final": bool(ctx.get("final_attempt"))})
    if conflicts:
        if not _soft_once(ctx, "q_price_conflict"):
            return "挂价规则: " + " | ".join(conflicts)
        print(f"WARN: 挂价规则冲突末次放行(这些单沿用 LLM 原价): {conflicts}")
    if miss:
        if not _soft_once(ctx, "q_style"):
            return ("挂价交给规则: 这些买/卖 action 没写 style(或不认识): " + "、".join(miss)
                    + "——每个买/卖写 \"style\": \"追价\"|\"低吸\"|\"排板\"|\"开盘\", 价格由驱动器按本导师挂单习惯算")
        print(f"WARN: 末次放行 缺 style(沿用 LLM 原价): {miss}")
    return None


def _new_codes(ctx):
    book = ctx.get("book") or {}
    held = {str(c) for c, p in (book.get("positions") or {}).items() if int(p.get("qty") or 0) > 0}
    ob = {str(o.get("code")) for o in book.get("orders") or [] if o.get("status") == "open" and o.get("side") == "BUY"}
    return held | ob


def post06(c, ctx, qf):
    errs = []
    acts = c.get("actions") or []
    for name, fn in (("CHAIN_SLOT_BUDGET", _post_slot), ("CHAIN_T_PROFILE", _post_t), ("CHAIN_OVERRIDE_LOCK", _post_lock),
                     ("CHAIN_RULE_CHECK", _post_rule), ("CHAIN_RISK_SIZE", _post_risk)):
        if not qf.get(name):
            # 10/18 用户定"关着的也要攒数据": 时段预算 / 改单锁层 关着时跑影子模式——照算照记(quality 日志带 shadow=true), 从不回炉、不打印
            if name in ("CHAIN_SLOT_BUDGET", "CHAIN_OVERRIDE_LOCK"):
                try:
                    sc = dict(ctx, final_attempt=True, _shadow=True)
                    fn(c, json.loads(json.dumps(acts, default=str)), sc)
                except Exception as ex:   # noqa: BLE001
                    _warn(f"post06 shadow {name}", ex)
            continue
        try:
            e = fn(c, acts, ctx)
        except Exception as ex:   # noqa: BLE001
            _warn(f"post06 {name}", ex)
            e = None
        if e:
            errs.append(e)
    return " | ".join(errs) if errs else None


def _post_risk(c, acts, ctx):
    """10/18 晚(用户定"周三接, 先备好"; 开关 CHAIN_RISK_SIZE): 06 每张买单按风险倒推的建议股数, **只记账不拦单**(quality 日志 check=risk_size)。
    止损 = 06 自己给的 stop_below / cancel_below, 没给 = indicators 快照的止损候选(箱体下沿 / 收 − 2ATR 里较近的);
    风险 = 账户 1%; 另记该导师在该票三态下的 ¼凯利上限(regime_trades.json)。用来周末对比"链的仓位 vs 风险仓位"谁更好"""
    sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
    import indicators_db as ID
    nav = _nav(ctx)
    if not nav:
        return None
    ind = {}
    try:
        mk = ROOT / "downloads" / "market"
        dd = sorted(x.name for x in mk.iterdir() if x.name < ctx["date_dash"] and (x / "indicators.jsonl").exists())
        want = {str(a.get("code")) for a in acts if a.get("op") == "买"}
        if dd and want:
            for l in (mk / dd[-1] / "indicators.jsonl").read_text(encoding="utf-8").splitlines():
                x = json.loads(l)
                if x["symbol"][2:] in want:
                    ind[x["symbol"][2:]] = x
    except (OSError, ValueError):
        pass
    try:
        R = (json.loads((ROOT / "scripts" / "tzzb" / "model_out" / "regime_trades.json").read_text(encoding="utf-8")).get("mentors") or {}).get(_skill(ctx)) or {}
    except (OSError, ValueError):
        R = {}
    items = []
    for a in acts:
        if a.get("op") != "买":
            continue
        code = str(a.get("code"))
        x = ind.get(code) or {}
        try:
            px = float(a.get("trigger_price") or x.get("close") or 0)
        except (TypeError, ValueError):
            px = float(x.get("close") or 0)
        stop = a.get("stop_below") or a.get("cancel_below")
        try:
            stop = float(stop) if stop else None
        except (TypeError, ValueError):
            stop = None
        if not stop or stop >= px:
            cand = [v for v in (x.get("stops") or {}).values() if v and v < px]
            stop = max(cand) if cand else None
        k = (R.get(f"状态|{x.get('regime')}") or {}).get("kelly4")
        items.append({"code": code, "regime": x.get("regime"), "px": px, "stop": stop, "chain_qty": a.get("qty"),
                      "risk_qty": ID.sizing(nav, px, stop) if stop else None, "kelly4_cap_qty": int(nav * k / px // 100 * 100) if k and px else None})
    if items:
        log("quality", ctx, {"check": "risk_size", "verdict": "只记账", "items": items})
    return None


def _post_slot(c, acts, ctx):
    if ctx.get("sub") or _slot(ctx) != "0915" or c.get("no_trade"):
        return None
    import slot_profile as P
    old = _new_codes(ctx)
    for a in acts:
        a["_new"] = a.get("op") == "买" and str(a.get("code")) not in old
    e, S = P.check_0915(_skill(ctx), ctx["date_dash"], acts, _nav(ctx))
    # 10/17 用户批 A12: 时段预算改纯提醒——A 股轮动 / 投机, 导师习惯出手时段只在短周期有效; 超预算只记账 + 打印, 不回炉
    verdict = "通过" if not e else "提醒(超预算, 不拦)"
    log("quality", ctx, {"check": "slot_budget", "verdict": verdict, "stat": S})
    if e and not ctx.get("_shadow"):
        print(f"提醒: 0915 开仓预算 {e}")
    return None


def _post_t(c, acts, ctx):
    import t_profile as T
    e = T.check_no_t(_skill(ctx), ctx["date_dash"], acts, ctx.get("book"), ctx["date_dash"])
    if not e:
        return None
    verdict = "回炉" if not _soft_once(ctx, "q_not") else "末次放行"
    log("quality", ctx, {"check": "no_t", "verdict": verdict, "msg": e})
    if verdict == "回炉":
        return e
    print(f"WARN: 不学T 闸末次放行: {e}")
    return None


def _post_lock(c, acts, ctx):
    lg = ctx.get("ledger") or {}
    b = lg.get("base")
    if not b:
        return None
    import override_stats as O
    lk = O.locks_of(_skill(ctx))
    if not lk:
        return None
    sys.path.insert(0, str(HERE))
    import ledger_limits as ll
    st = ll.chain_state(ctx.get("book") or {}, ctx["date_dash"])
    cv = ll.chain_view(acts, st, _nav(ctx))
    bad = []
    if "L1" in lk and b.get("trade") is not None and bool(b.get("trade")) != cv["trade"]:
        bad.append(f"L1 出手: 基线={'出手' if b.get('trade') else '不出手'}, 本单={'出手' if cv['trade'] else '不出手'}")
    if "L2" in lk and cv["trade"] and b.get("dir") not in (None, cv["dir"]):
        bad.append(f"L2 方向: 基线={b.get('dir')}, 本单={cv['dir']}")
    if not bad:
        return None
    log("quality", ctx, {"check": "override_lock", "verdict": "末次放行" if ctx.get("final_attempt") else "回炉", "bad": bad})
    if ctx.get("final_attempt") and not ctx.get("_shadow"):
        print(f"WARN: override 锁层末次放行: {bad}")
        return None
    return "override 锁层(近 20 日改基线净负, 该层必须接受基线): " + "; ".join(bad)


def _post_rule(c, acts, ctx):
    import rule_tags as R
    e = R.check(_skill(ctx), c, acts, ctx)
    if not e:
        return None
    verdict = "回炉" if not _soft_once(ctx, "q_rule") else "末次放行"
    log("quality", ctx, {"check": "rule_check", "verdict": verdict, "msg": e})
    if verdict == "回炉":
        return e
    print(f"WARN: 规则方向/漏用末次放行: {e}")
    return None


# ================================================================ plans 行
def plan_conds(a, qf):
    """emit_plans 追加的 cond 片段(list[str])"""
    if qf.get("CHAIN_PRICE_RULES") and a.get("_reprice") and a.get("op") in ("买", "卖"):
        return [f"reprice={int(a['_reprice'])}"]
    return []


def plan_note(a, qf):
    if qf.get("CHAIN_PRICE_RULES") and a.get("_style"):
        return f" 挂法:{a['_style']}(规则价)"
    return ""
