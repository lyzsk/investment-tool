# -*- coding: utf-8 -*-
"""t_swing.py — 波段T(跨日 先卖后接)paper 账本(10/20 用户定"今天先让 paper 有数据"; 机械版零 token, 决策版花 token)

用户 10/20 凌晨: "下跌行情先卖然后慢慢接回也算 T —— 银行 / 纳指要重点想, 因为已引入指标方向判断, 这是比日内 T 更高阶的、基于箱体 / 单边 / 无形态三态判断的长线 T"
账本(各 10 万开户, 同 t_bot 只动 1 万, 底仓 = 1 万的 50%):
  A-sbank / A-sndq  机械波段T(三态表机械执行, 零 token)
  A-wbank / A-wndq  决策波段T(LLM 每天 2 次: 0935 / 1435, 单次目标 ≤2 分钟)
  对照: 不T = A-hbank / A-hndq(同样 50% 底仓只拿着, t_bot 已在跑); 日内 T = A-tbank/A-tndq(机械) A-dbank/A-dndq(决策)
一笔波段 = 从第一笔卖出(持仓 < 底仓)到股数回到底仓为止, 可跨多天; 只做"先卖后接", 不做先买(先买后卖归日内 T 账本)
三态 = downloads/market/<D 之前最近一日>/indicators.jsonl(每晚 indicators_db.py: 上涨趋势 / 下跌趋势 / 箱体 / 无规则 + 箱体上下沿 + ATR14%)
机械规则(三态表, 决策版也受同样的硬上限约束):
  下跌趋势 且无波段  → 0935 卖 1/2 底仓(现价 −0.5% 限价); 接回分两档挂: 昨收 −1×ATR、昨收 −2×ATR, 各接一半(每天重挂, 当日有效)
  箱体 且昨收在箱体上 1/4 且无波段 → 0935 卖 1/3 底仓; 接回挂 箱体下沿 + 1/4 箱高
  上涨趋势 / 无规则  → 不开新波段
  收口(14:45 检查, 机械 + 决策两版都执行): ①三态从开仓时的 下跌/箱体 变成 上涨趋势 ②止损: 现价 ≥ 卖出均价 + 1×ATR(踏空认错) ③波段满 20 个交易日
        → 现价 +1% 限价把差额全部接回
  硬上限: 卖出累计 ≤ 2/3 底仓; 只用底仓里可卖的(银行 T+1: 当天买回的不能当天再卖); 买入只接回差额, 不超过底仓
产物: 账本 books/<src>.json; 状态 t_swing_state.json(每本: 当前波段 起始日 / 起始三态 / 卖出均价; 已结波段列表 差价 = 卖出额 − 接回额 − 费用)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/t_swing.py --tick [--date D] [--dry] [--force-slot 0935]   (check md 每 5 分钟顺带调, 幂等)
"""
import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import t_bot as TB          # noqa: E402  共用: params/snap/write_import/lot/tick_px/book/base_qty
import a_rules as AR        # noqa: E402

BOTS = {"A-sbank": {"code": "601988", "name": "中国银行·机械波段T", "t0": False, "mode": "mech"},
        "A-sndq": {"code": "159941", "name": "纳指ETF·机械波段T", "t0": True, "mode": "mech"},
        "A-wbank": {"code": "601988", "name": "中国银行·决策波段T", "t0": False, "mode": "llm", "skill": "bank"},
        "A-wndq": {"code": "159941", "name": "纳指ETF·决策波段T", "t0": True, "mode": "llm", "skill": "nasdaq"}}
OPEN_AT, CLOSE_AT, LLM_SLOTS = "0935", "1445", ("0935", "1435")
MAX_SELL, MAX_DAYS = 2 / 3, 20
DATA = TB.DATA
STATE = DATA / "t_swing_state.json"
MKT = ROOT / "downloads" / "market"


def regime(code, D):
    """D 之前最近一日收盘的三态 / 箱体 / ATR(不偷看当天)"""
    days = sorted(p.parent.name for p in MKT.glob("20*/indicators.jsonl") if p.parent.name < D)
    if not days:
        return None
    s = f'"{AR.symbol(code)}"'
    for l in (MKT / days[-1] / "indicators.jsonl").open(encoding="utf-8"):
        if s in l:
            r = json.loads(l)
            r["_day"] = days[-1]
            return r
    return None


def tdays_between(d0, d1):
    return len([p for p in MKT.glob("20*/kline_day.jsonl") if d0 < p.parent.name <= d1])


def sold_avg(b, code, since):
    tr = [t for t in b.get("trades") or [] if t.get("code") == code and str(t.get("id", ""))[:10] >= since]
    s = [t for t in tr if t["side"] == "SELL"]
    q = sum(int(t["qty"]) for t in s)
    return (sum(float(t["price"]) * int(t["qty"]) for t in s) / q) if q else None, tr


def line(hm, src, side, code, px, qty, ref, why):
    return f"- {hm[:2]}:{hm[2:]} | {src} | {side} | {code} | {TB.tick_px(code, px):g} | {qty} | day | {ref:g} | - | {why}"


def mech_open(src, code, base, sellable, R, prev, sell_px=None):
    """机械开波段: 返回 (卖量, 理由, [(接回价, 说明)]) 或 None; 接回价以 min(昨收, 卖出价) 为锚往下, 保证低于卖出价(10/20 自测: 原按昨收算, 低开时接回1 = 卖出价, 白交费)"""
    a = min(prev, sell_px or prev)
    rg, atr = R.get("regime"), float(R.get("atr14_pct") or 0.02)
    lo, hi = R.get("box_lo"), R.get("box_hi")
    if rg == "下跌趋势":
        q = min(TB.lot(code, base / 2), TB.lot(code, sellable))
        tiers = [(a * (1 - atr), "接回1 锚−1ATR"), (a * (1 - 2 * atr), "接回2 锚−2ATR")]
        why = f"机械波段 开: 三态=下跌趋势 卖1/2底仓"
    elif rg == "箱体" and lo and hi and hi > lo and prev >= hi - (hi - lo) / 4:
        q = min(TB.lot(code, base / 3), TB.lot(code, sellable))
        tiers = [(lo + (hi - lo) / 4, "接回 箱体下沿+1/4箱高")]
        why = f"机械波段 开: 三态=箱体 昨收在上1/4({lo}~{hi}) 卖1/3底仓"
    else:
        return None
    if q <= 0:
        return None
    return q, why, tiers


def llm_decide(src, cfg, D, slot, b, base, pos, sellable, R, P, q0, sw):
    """决策波段T: 一次 claude -p(目标 ≤2 分钟), 输出 JSON; 驱动器按硬上限校验"""
    from claude_call import call, LEAN_ARGS
    import t_decide as TD
    code = cfg["code"]
    last = float(q0.get("last") or 0) or P["prev"]
    ind = {k: R.get(k) for k in ("regime", "er20", "atr14_pct", "box_lo", "box_hi", "box_pos", "ema20", "ema60", "ema120", "stops")} if R else {}
    owe = max(0, base - pos)
    prompt = f"""你是波段做 T 交易员, 管理 paper 账本 {src}: {cfg['name'].split('·')[0]}({code}), 底仓 {base} 股, 现持 {pos} 股(差额 {owe} 股 = 正在进行的波段已卖未接), 今天可卖 {sellable} 股。现在 {D} {dt.datetime.now():%H:%M}(时段 {slot})。
波段T = 跨日的"先卖后接": 判断接下来几天要跌 → 先卖一部分底仓, 跌下去分批接回, 股数回到底仓 = 一笔波段结束, 赚的是卖出价和接回价的差。不做先买后卖(那是日内 T 账本的事)。
目标: 一笔波段的差价扣费后 > 0, 并且整体跑赢"底仓一直拿着"。看不清就观望, 观望也是决策。

## 三态 / 指标(截至 {R.get('_day') if R else '?'} 收盘; 三态 = 上涨趋势 / 下跌趋势 / 箱体 / 无规则): {json.dumps(ind, ensure_ascii=False)}
## 近 30 日振幅(相对昨收): 最高涨幅中位 {P['up']:.2%}, 最大跌幅中位 {P['dn']:.2%}; 昨收 {P['prev']}
## 当前行情: 开 {q0.get('open')} 高 {q0.get('high')} 低 {q0.get('low')} 现 {q0.get('last')} 涨跌 {q0.get('pct')}%
## 当前波段: {json.dumps(sw, ensure_ascii=False) if sw else '无(持仓 = 底仓)'}
## 隔夜外围 / 期货:
{TD.facts_sections(D)[:1500]}
## 资料索引(结构 / 拓扑邻居 / md 命中; ❌ 的项不要假设):
{TD.ctx_pack(code, D, slot)[:3500]}
## 本品种 skill(画像 + 规则 + 最近日卡):
{TD.skill_notes(cfg['skill'], n_cases=5)[:5000]}

## 硬上限(驱动器机械校验, 超了直接砍): 累计卖出 ≤ 2/3 底仓; 今天只能卖 {sellable} 股; 买只接回差额(≤ {owe} 股 + 本次新卖的); 价格在涨跌停内且离现价 ±2% 内(价格笼子);
   以下情况驱动器 14:45 会强制接回全部差额: 三态变成上涨趋势 / 现价 ≥ 卖出均价 + 1×ATR / 波段满 20 个交易日。
## 费用: 每笔最低 5 元, 银行卖出另收印花税 0.05%; 1/3 底仓一笔约 1500~1700 元 → 来回约 0.7%, 预期差价不到 1.5% 就别开新波段。

只输出一个 ```json 块:
{{"action":"开波段|加卖|接回|观望|撤单","reason":"一两句, 依据哪些信号(三态/箱体位置/外围/量能)",
 "cancel_open": true/false,
 "orders":[{{"side":"SELL|BUY","price":数值,"frac":底仓比例(0~2/3),"why":"情景"}}],
 "plan":"接下来几天的打算: 什么价位/什么信号接回, 什么情况认错"}}"""
    t0 = time.time()
    r = call(prompt, tag=f"t-swing:{src}", permission="default", timeout=180, extra_args=LEAN_ARGS + ["--tools", ""], json_tag="json")
    m = re.findall(r"```json\s*\n([\s\S]*?)```", r.result or "")
    try:
        dec = json.loads(m[-1]) if m else {}
    except ValueError:
        dec = {}
    return dec, round(r.cost_usd or 0, 3), round(time.time() - t0, 1)


def validate(dec, code, base, pos, sellable, last, prev):
    up_px, dn_px = AR.limit_prices(code, None, prev)[:2] if hasattr(AR, "limit_prices") else (prev * 1.1, prev * 0.9)
    out, errs = [], []
    sold_cap = max(0, TB.lot(code, base * MAX_SELL) - max(0, base - pos))   # 还能再卖多少(累计 ≤ 2/3 底仓)
    sell_left, owe = min(sellable, sold_cap), max(0, base - pos)
    for o in dec.get("orders") or []:
        try:
            side, px, frac = str(o["side"]).upper(), float(o["price"]), float(o["frac"])
        except (KeyError, TypeError, ValueError):
            errs.append(f"坏单 {o}")
            continue
        if (up_px and px > up_px) or (dn_px and px < dn_px) or abs(px / last - 1) > 0.02:
            errs.append(f"价 {px} 出涨跌停或 ±2% 笼子(现价 {last})")
            continue
        q = TB.lot(code, base * frac)
        if side == "SELL":
            q = min(q, TB.lot(code, sell_left))
            sell_left -= q
            owe += q
        elif side == "BUY":
            q = min(q, owe)
            owe -= q
        else:
            errs.append(f"坏单 {o}")
            continue
        if q <= 0:
            errs.append(f"{side} 数量 0(超硬上限 / 没有差额可接)")
            continue
        out.append((side, px, q, str(o.get("why") or "")[:40]))
    return out, errs


def tick(D, dry, force_slot=None):
    now = force_slot or dt.datetime.now().strftime("%H%M")
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    out = []
    for src, cfg in BOTS.items():
        code = cfg["code"]
        st = state.setdefault(src, {"swing": None, "closed": [], "days": {}})
        sd = st["days"].setdefault(D, {})
        b = TB.book(src)
        base = int(b.get("_t_base") or 0)
        pos = int(((b.get("positions") or {}).get(code) or {}).get("qty") or 0)
        if not base:   # 第 1 天: 同 t_bot 建底仓, 当天不做波段
            if not sd.get("base_order") and now >= "0930":
                q0 = TB.snap(code) or {}
                last = float(q0.get("last") or 0) if not q0.get("stale") else 0
                if not last:
                    TB.FAILS.append(f"{src} 建底仓取不到 {code} 现价")
                    continue
                ln = line(now, src, "BUY", code, last * 1.005, TB.base_qty(cfg, last), last, "波段T 建底仓 50%(开盘后按现价)")
                if not dry:
                    sd["base_order"] = {"at": now, "imp": TB.write_import(D, src, [ln])}
                out.append(f"{src} 建底仓: {ln}")
            if sd.get("base_order") and not sd.get("base_set") and now >= CLOSE_AT and pos:
                b["_t_base"] = pos
                if not dry:
                    TB.set_base(src, b["_t_base"])
                sd["base_set"] = pos
                out.append(f"{src} 底仓记 {pos}")
            continue
        P = TB.params(code, D)
        R = regime(code, D) or {}
        today_buy = sum(int(t["qty"]) for t in b.get("trades") or [] if str(t.get("id", ""))[:10] == D and t.get("code") == code and t["side"] == "BUY")
        sellable = max(0, pos - (0 if cfg["t0"] else today_buy))
        sw = st.get("swing")
        if pos >= base and sw:   # 股数回到底仓 = 波段结束 → 结算
            avg, tr = sold_avg(b, code, sw["start"])
            sell_amt = sum(float(t["price"]) * int(t["qty"]) for t in tr if t["side"] == "SELL")
            buy_amt = sum(float(t["price"]) * int(t["qty"]) for t in tr if t["side"] == "BUY")
            fee = sum(float(t.get("fee") or 0) for t in tr)
            st["closed"].append({**sw, "end": D, "sell_amt": round(sell_amt, 2), "buy_amt": round(buy_amt, 2), "fee": round(fee, 2),
                                 "pnl": round(sell_amt - buy_amt - fee, 2), "days": tdays_between(sw["start"], D)})
            st["swing"] = sw = None
            out.append(f"{src} 波段结束: 差价 {st['closed'][-1]['pnl']:+.2f} 元")
        if pos < base and not sw:   # 有差额但没记录(比如今天刚卖) → 记一笔
            st["swing"] = sw = {"start": D, "regime0": R.get("regime"), "atr": R.get("atr14_pct")}
        lines = []
        hm = now
        # ---- 开 / 调(机械 0935 一次; 决策 0935 / 1435 各一次) ----
        if cfg["mode"] == "mech" and now >= OPEN_AT and not sd.get("open") and now < CLOSE_AT:
            sd["open"] = {"at": now, "regime": R.get("regime")}
            q0 = TB.snap(code) or {}
            last = float(q0.get("last") or 0) or P["prev"]
            if not sw:
                mo = mech_open(src, code, base, sellable, R, P["prev"], last * 0.995)
                if mo:
                    q, why, tiers = mo
                    lines.append(line(hm, src, "SELL", code, last * 0.995, q, last, why))
                    for i, (px, w) in enumerate(tiers):
                        qq = TB.lot(code, q / len(tiers)) if i < len(tiers) - 1 else q - TB.lot(code, q / len(tiers)) * (len(tiers) - 1)
                        if qq > 0 and px < last * 0.98:   # 离现价超 2% 的接回单盘中会被笼子拒 → 当天先不挂, 次日按新昨收重挂
                            sd.setdefault("deferred", []).append({"px": round(px, 3), "qty": qq, "why": w})
                        elif qq > 0:
                            lines.append(line(hm, src, "BUY", code, px, qq, last, f"机械波段 {w}"))
                    sd["open"]["plan"] = {"sell": q, "tiers": [(round(p, 3), w) for p, w in tiers]}
                else:
                    sd["open"]["note"] = f"三态={R.get('regime')} 不开波段"
            else:   # 波段进行中: 每天重挂接回(差额按两档; 档位按开波段时的三态)
                owe = base - pos
                atr = float(R.get("atr14_pct") or sw.get("atr") or 0.02)
                tiers = [P["prev"] * (1 - atr), P["prev"] * (1 - 2 * atr)] if sw.get("regime0") == "下跌趋势" else \
                        [((R.get("box_lo") or P["prev"] * (1 - atr)) + ((R.get("box_hi") or P["prev"]) - (R.get("box_lo") or P["prev"])) / 4)]
                avg, _ = sold_avg(b, code, sw["start"])
                cap_px = avg * (1 - atr / 2) if avg else None   # 接回价必须低于卖出均价半个 ATR, 否则不挂(等收口规则)
                for i, px in enumerate(tiers):
                    qq = TB.lot(code, owe / len(tiers)) if i < len(tiers) - 1 else owe - TB.lot(code, owe / len(tiers)) * (len(tiers) - 1)
                    px = max(px, last * 0.98 + AR.tick(code))   # 夹进价格笼子
                    if qq > 0 and (not cap_px or px <= cap_px):
                        lines.append(line(hm, src, "BUY", code, px, qq, last, f"机械波段 续挂接回{i + 1}"))
                    elif qq > 0:
                        sd.setdefault("deferred", []).append({"px": round(px, 3), "qty": qq, "why": f"续挂接回{i + 1} 价不低于卖出均价−0.5ATR({cap_px:.3f}), 今天不挂"})
        if cfg["mode"] == "llm":
            due = [x for x in LLM_SLOTS if x <= now and x not in sd] if not force_slot else ([force_slot] if force_slot in LLM_SLOTS else [])
            if due and now < CLOSE_AT:
                sl = due[-1]
                for x in due:
                    sd.setdefault(x, {"skip": "过时"} if x != sl else None)
                q0 = TB.snap(code) or {}
                last = float(q0.get("last") or 0) if not q0.get("stale") else 0
                if not last:
                    sd[sl] = {"error": "取不到现价, 本时段不决策"}
                    TB.FAILS.append(f"{src} {sl} 取不到现价")
                elif dry:
                    sd[sl] = {"dry": True}
                else:
                    dec, cost, secs = llm_decide(src, cfg, D, sl, b, base, pos, sellable, R, P, q0, sw)
                    rec = {"at": dt.datetime.now().isoformat(timespec="seconds"), "cost": cost, "secs": secs, "decision": dec, "regime": R.get("regime")}
                    if dec:
                        if dec.get("cancel_open") or dec.get("action") == "撤单":
                            for o in b.get("orders") or []:
                                if o.get("status") == "open" and o.get("date") == D:
                                    lines.append(f"- {hm[:2]}:{hm[2:]} | {src} | CXL | {code} | - | - | - | - | oid={o['id']} | 决策波段 撤单({sl})")
                        vl, errs = validate(dec, code, base, pos, sellable, last, P["prev"])
                        for side, px, qty, why in vl:
                            lines.append(line(hm, src, side, code, px, qty, last, f"决策波段 {dec.get('action')} {why}"))
                        rec["rejected"] = errs
                    else:
                        rec["error"] = "模型输出解析失败"
                    sd[sl] = rec
                    out.append(f"{src} {sl}({secs}s ${cost}): {json.dumps(dec, ensure_ascii=False)[:200]}")
        # ---- 收口(两版都机械执行) ----
        if now >= CLOSE_AT and not sd.get("close") and pos < base:
            q0 = TB.snap(code) or {}
            last = float(q0.get("last") or 0) or P["prev"]
            avg, _ = sold_avg(b, code, (sw or {}).get("start", D))
            atr_px = P["prev"] * float(R.get("atr14_pct") or 0.02)
            why = ("三态转上涨趋势" if R.get("regime") == "上涨趋势" and (sw or {}).get("regime0") in ("下跌趋势", "箱体") else
                   f"止损: 现价 {last} ≥ 卖出均价 {avg:.3f} + 1×ATR" if avg and last >= avg + atr_px else
                   f"满 {MAX_DAYS} 个交易日" if sw and tdays_between(sw["start"], D) >= MAX_DAYS else None)
            sd["close"] = {"at": now, "why": why}
            if why:
                for o in b.get("orders") or []:
                    if o.get("status") == "open" and o.get("date") == D and o.get("side") == "BUY":
                        lines.append(f"- {hm[:2]}:{hm[2:]} | {src} | CXL | {code} | - | - | - | - | oid={o['id']} | 波段收口 撤旧接回单")
                lines.append(line(hm, src, "BUY", code, last * 1.01, base - pos, last, f"波段收口 全部接回({why})"))
        elif now >= CLOSE_AT and not sd.get("close"):
            sd["close"] = {"at": now, "why": None}
        if lines:
            if not dry:
                sd.setdefault("imports", []).append({"at": now, "lines": lines, "imp": TB.write_import(D, src, lines)})
            out.append(f"{src}: " + " | ".join(lines))
    if not dry:
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(out) or f"{now} 波段T 无到点动作")
    if TB.FAILS and "0930" <= dt.datetime.now().strftime("%H%M") <= "1500":
        print("ERROR: " + " | ".join(TB.FAILS))
        sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tick", action="store_true")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--force-slot")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.status:
        for src, cfg in BOTS.items():
            R = regime(cfg["code"], a.date) or {}
            print(src, cfg["name"], R.get("_day"), R.get("regime"), R.get("box_lo"), R.get("box_hi"), R.get("atr14_pct"))
    if a.tick:
        tick(a.date, a.dry, a.force_slot)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
