# -*- coding: utf-8 -*-
"""t_bot.py — 单品种做 T paper 账本(10/18 用户定: 明天起跑 A-tbank 中国银行 + A-tndq 纳指 ETF 159941; 零 token, 纯规则)

目的: 用户计划资产到 12 万后拿 1 万做 T 银行、再 1 万做 T 纳指 ETF; 先在 paper 里按用户的做 T 纪律跑, 看扣费后能不能稳定跑赢"只拿着"。
跑法(用户纪律: 参数按近 30 日振幅分布定, 禁固定模板; T 规模三档里取 1/3; 收盘股数可浮动, 多出=隔夜正 T):
  第 1 天: 09:30 后按现价约 50% 净值建底仓, 当天不 T(银行 T+1)
  之后每天 09:15 挂两张日内单(都是限价, 当日有效):
     高抛  卖 底仓的 1/3, 价 = 昨收 × (1 + 近 30 日「最高/昨收−1」中位数)
     低吸  买 底仓的 1/3, 价 = 昨收 × (1 − 近 30 日「1−最低/昨收」中位数)
  14:45 收口: 卖了没买回 → 现价买回(回到底仓); 买了没卖出 → 纳指 ETF(T+0)现价卖掉, 银行(T+1)留着隔夜, 次日高抛单加上这部分
对照: 同一账本的"只拿着"收益 = 第 1 天底仓数量 × 价格变化 + 现金(报告里比两者, T 有没有增值一目了然)
撮合: 走 paper 同一套 matcher(费用 / T+1 / 价格笼子 / 停牌跳过 都一样); 由 check md 的 --only mix 每 5 分钟顺带调一次 --tick(幂等)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/t_bot.py --tick [--date D] [--dry]   |   --status
"""
import argparse
import datetime as dt
import json
import re
import os
import statistics as st
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import a_rules as AR   # noqa: E402
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DATA = Path(os.environ["PAPER_ROOT"]).resolve() if os.environ.get("PAPER_ROOT") else HERE
BOTS = {"A-tbank": {"code": "601988", "name": "中国银行", "t0": False},
        "A-tndq": {"code": "159941", "name": "纳指ETF(广发)", "t0": True},
        # 10/18 用户定: 每个品种三本对照 = 机械 T(上两本) / 决策 T(另建, 花 token) / 不 T(下两本: 同样 50% 底仓只拿着)
        "A-hbank": {"code": "601988", "name": "中国银行·不T", "t0": False, "hold": True},
        "A-hndq": {"code": "159941", "name": "纳指ETF·不T", "t0": True, "hold": True},
        # 10/18 晚用户定: 用户实盘持仓牧原也跑(私有: 底仓=用户真实持股数, 运行时从 snapshots 读, 代码里不写数; 用户清仓后自动停)
        "A-tmuyuan": {"code": "002714", "name": "牧原股份", "t0": False, "real": True},
        "A-hmuyuan": {"code": "002714", "name": "牧原股份·不T", "t0": False, "hold": True, "real": True}}
BASE_FRAC, T_FRAC = 0.5, 1 / 3
# 10/18 晚: 按用户真实计划只动 1 万(账本仍是 10 万开户, 其余 9 万现金不动 = 不改账本哈希链); 用户券商实收每笔最低 5 元(佣金+其他费用合计 5.00, 9/28 成交单核出),
#   matcher 已是 万2.5 + 最低 5 元 → 1 万规模下一笔 T 的 1/3 档约 1400~1600 元, 单边费用约 0.3%, 这正是要验证的"扣费后 T 值不值"
CAPITAL = 10000
RESERVE = 100000 - CAPITAL
SNAP = ROOT / "scripts" / "dfcf" / "snapshots"   # 实盘隐私唯一落点(gitignore)


def t_cash(b, cfg=None):
    """本账本可用于做 T 的现金: 银行/纳指 = 总现金减去不动的 9 万; 牧原(real) = 全部现金(按用户真实规模)"""
    return max(0.0, float(b.get("cash") or 0) - (0 if (cfg or {}).get("real") else RESERVE))


def _snap_files():
    return sorted(SNAP.glob("20??-??-??_成交_*.txt"))


def real_trades(D, codes=None):
    """用户当日实盘成交(snapshots/<D>_成交_*.txt; 两种导出格式都认): [(time, code, side, qty, price, amount, fee|None)], fee=佣金+其他+印花+过户(有费用列时)"""
    out = []
    for f in _snap_files():
        if not f.name.startswith(D):
            continue
        lines = f.read_text(encoding="utf-8").splitlines()
        fcode = next((m.group(1) for m in (re.search(r"(?<!\d)(\d{6})(?!\d)", x) for x in lines[:1]) if m), None)   # 手贴摘要版: 标题行带代码
        for l in lines:
            m = re.match(r"^(\d\d:\d\d:\d\d)\s+(买|卖)\s+(?:\d+→)?(\d+)\s+([\d.]+)\s+([\d.]+)", l)   # 摘要版流水: 时间 方向 数量(委托→成交 取成交) 价格 金额(无代码列)
            if m and fcode and (not codes or fcode in codes):
                out.append((m.group(1), fcode, "BUY" if m.group(2) == "买" else "SELL", int(m.group(3)), float(m.group(4)), float(m.group(5)), None))
                continue
            t = l.split()
            k = next((i for i, x in enumerate(t) if len(x) == 6 and x.isdigit() and i >= 1), None)
            if k is None or k + 5 >= len(t) or not any(":" in x for x in t[:k]):
                continue
            side = "BUY" if "买入" in t[k + 2] else "SELL" if "卖出" in t[k + 2] else None
            if not side or (codes and t[k] not in codes):
                continue
            try:
                qty, px, amt = int(t[k + 3]), float(t[k + 4]), float(t[k + 5])
                fee = sum(float(x) for x in t[k + 6:k + 10]) if len(t) >= k + 10 and "." in t[k + 6] else None
            except ValueError:
                continue
            out.append((next(x for x in t[:k] if ":" in x), t[k], side, qty, px, amt, fee))
    return out


def real_position(code):
    """用户最近一次导出里该票的持股数(没有导出 / 已清仓 = 0)"""
    for f in reversed(_snap_files()):
        for l in f.read_text(encoding="utf-8").splitlines():
            t = l.split()
            if len(t) >= 5 and t[0].isdigit() and len(t[0]) <= 3 and t[1] == code:
                return int(t[3])
    return 0


def real_qty(code, D):
    """10/20 用户定"跟随用户实盘": 持没持 = ≤D 最近一份 md「### 当前持仓」(只放名字, 隐私口径);
    持多少 = 最近一份带持仓表(表头含"持仓数量")的导出里该票股数(表里没有=0) + 之后各日成交净额(持仓表是收盘后导出, 同文件成交已含在内)。
    返回 (股数, 说明); md 列了但导出算出 ≤0 / 从没导出过持仓表 → (None, 说明), 调用方大声报错、不猜股数。
    10/20 教训: 原 real_position 只认持仓表, 清仓那天导出没有持仓表 → 回落到前一天的 2300 股, 清仓后照样做 T"""
    sys.path.insert(0, str(SNAP / "order-skill"))
    import holdings as HD
    if code not in [c for c, _ in HD.codes(D)]:
        return 0, f"md 当前持仓没有 {code}"
    md_d = HD.names(D)[1] or ""
    files = [f for f in _snap_files() if f.name[:10] <= D]
    base_d, qty, last_d = None, 0, ""
    for f in files:
        ls = f.read_text(encoding="utf-8").splitlines()
        if any("持仓数量" in l for l in ls):
            base_d, qty, last_d = f.name[:10], 0, f.name[:10]
            for l in ls:
                t = l.split()
                if len(t) >= 5 and t[0].isdigit() and len(t[0]) <= 3 and t[1] == code:
                    qty = int(t[3])
    if base_d is None:
        return None, f"md 当前持仓有 {code}, 但 snapshots 里从没有带持仓表的导出, 不知道股数"
    for d in sorted({f.name[:10] for f in files if f.name[:10] > base_d}):
        tr = real_trades(d, {code})
        qty += sum(q if side == "BUY" else -q for _, _, side, q, *_ in tr)
        last_d = d if tr else last_d
    if qty <= 0 and last_d >= md_d:   # 导出比 md 新: md 是早上写的, 当天 / 之后的成交把它清了 → 以导出为准
        return 0, f"md({md_d}) 当前持仓还有 {code}, 但 {last_d} 成交导出显示已清仓(导出更新, 以导出为准)"
    if qty <= 0:
        return None, f"md({md_d}) 当前持仓有 {code}, 但导出算出 {qty} 股(导出只到 {last_d}): 新买了还没贴成交?"
    return qty, f"md 当前持仓有 {code}, 导出算出 {qty} 股({base_d} 持仓表+之后成交)"


def real_follow(src, cfg, D, now, s, dry):
    """real 账本(牧原)先跟随用户实盘, 再做 T(10/20 用户定): 返回 True = 今天本账本不做 T。
    用户没持仓 → 账本有货就开盘市价清掉、底仓归 0、不挂单; 持仓股数变了(加/减仓) → 按现价补齐到用户股数、底仓改成用户股数、当天不 T;
    用户新持仓且账本空 → 返回 False 交给原"第 1 天建底仓"分支(股数 = real_qty)。md / 成交导出有变化(新贴了 txt)就重新对一次"""
    code = cfg["code"]
    files = [f.name for f in _snap_files() if f.name[:10] <= D]
    sig = f"{D}|{len(files)}|{files[-1] if files else ''}"
    f0 = s.get("follow") or {}
    if f0.get("sig") == sig:
        return f0.get("skip", False)
    b = book(src)
    pos = int(((b.get("positions") or {}).get(code) or {}).get("qty") or 0)
    base = int(b.get("_t_base") or 0)
    tgt, why = real_qty(code, D)
    if tgt is None:
        if now >= "0930":   # 开盘前 FAILS 不打印, 等开盘后再记(只记一次)
            FAILS.append(f"{src} 跟随实盘: {why}; 今天本账本不动")
            s["follow"] = {"sig": sig, "skip": True, "why": why}
        return True
    if (tgt == base and (pos or not tgt)) or (tgt and not base and not pos):   # 不用跟 / 新持仓走建底仓分支
        s["follow"] = {"sig": sig, "skip": not tgt, "why": why}
        return not tgt
    if tgt == pos:   # 只差底仓记账(如账本早已空、底仓还记着旧数)
        b["_t_base"] = tgt
        if not dry:
            (DATA / "books" / f"{src}.json").write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
        s["follow"] = {"sig": sig, "skip": True, "why": why + f"; 底仓改记 {tgt}"}
        return True
    if now < "0930":   # 跟随单等开盘后按现价下
        return True
    q0 = snap(code) or {}
    last = float(q0.get("last") or 0) if not q0.get("stale") else 0
    if not last:
        FAILS.append(f"{src} 跟随实盘取不到 {code} 现价, 下一轮再试")
        return True
    hm = f"{now[:2]}:{now[2:]}"
    if tgt < pos:
        line = f"- {hm} | {src} | SELL | {code} | {tick_px(code, last):g} | {pos - tgt} | day | {last:g} | open_sell=1 | 跟随用户实盘减到 {tgt} 股: {why}"
    else:
        line = f"- {hm} | {src} | BUY | {code} | {tick_px(code, last * 1.005):g} | {tgt - pos} | day | {last:g} | - | 跟随用户实盘加到 {tgt} 股: {why}"
    b["_t_base"] = tgt
    imp = None
    if not dry:
        (DATA / "books" / f"{src}.json").write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
        imp = write_import(D, src, [line])
    s["follow"] = {"sig": sig, "skip": True, "why": why, "line": line, "imp": imp}
    print(f"{src} 跟随实盘: {line}")
    return True


def base_qty(cfg, last, D=None):
    """第 1 天建底仓的股数: 牧原 = 用户真实持股数(real_qty, 股数不明=0 不建); 其他 = 1 万的 50%"""
    if cfg.get("real"):
        return real_qty(cfg["code"], D or dt.date.today().isoformat())[0] or 0
    return lot(cfg["code"], BASE_FRAC * CAPITAL / last)
STATE = DATA / "t_bot_state.json"


def kline(code, D, n=31):
    from kline_db import db
    c = db()
    try:
        cur = c.cursor()
        cur.execute("select trade_date, cast(high as double), cast(low as double), cast(close as double), cast(pre_close as double) from kline_day "
                    "where symbol=%s and is_deleted=0 and trade_date<%s order by trade_date desc limit %s", (AR.symbol(code), D, n))
        return list(reversed(cur.fetchall()))
    finally:
        c.close()


def params(code, D):
    k = kline(code, D)
    rows = [r for r in k if r[4]]
    up = st.median(r[1] / r[4] - 1 for r in rows[-30:])
    dn = st.median(1 - r[2] / r[4] for r in rows[-30:])
    return {"prev": k[-1][3], "prev_d": str(k[-1][0]), "up": round(up, 4), "dn": round(dn, 4)}


def book(src):
    return json.loads((DATA / "books" / f"{src}.json").read_text(encoding="utf-8"))


def lot(code, qty):
    q = AR.round_qty(code, qty) if hasattr(AR, "round_qty") else int(qty // 100 * 100)
    return max(0, int(q))


def tick_px(code, x):
    t = AR.tick(code)
    return round(round(x / t) * t, 3)


def write_import(D, src, lines):
    pdir = DATA / "plans"
    pdir.mkdir(parents=True, exist_ok=True)
    f = pdir / f"{D}_{src}.md"
    old = f.read_text(encoding="utf-8").splitlines() if f.exists() else [f"# {D} {src} 做T 机械单(t_bot.py, 零 token)", ""]
    f.write_text("\n".join(old + [l for l in lines if l not in old]) + "\n", encoding="utf-8")
    r = subprocess.run(["node", str(HERE / "matcher.mjs"), "--import", str(f)], cwd=ROOT, env=dict(os.environ), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-2:]


def snap(code):
    r = subprocess.run(["node", str(HERE / "snapshot.mjs"), "--codes", code], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", creationflags=NOWIN, timeout=60)
    for l in (r.stdout or "").splitlines():
        if l.startswith("JSON:"):
            break
    try:
        # 10/19 修: snapshot.mjs 末行是 "JSON:{"ok":1,...}", 旧写法 rindex("}") 把它也截进来 → json 解析失败 → 恒返回 None
        #   → 10/19 做T 6 本 + 决策T 3 本全天"无到点动作", 底仓一股没建(静默失败)。现在只取 JSON: 行之前的主体
        body = r.stdout.split("\nJSON:")[0]
        j = json.loads(body[body.index("{"):body.rindex("}") + 1])
        s = (j.get("snaps") or j.get("data") or {})
        s = s.get(code) if isinstance(s, dict) else next((x for x in s if x.get("code") == code), None)
        return s
    except Exception as e:   # noqa: BLE001
        print(f"WARN: snap({code}) 解析失败: {e}; stdout 尾 {(r.stdout or '')[-120:]!r} stderr {(r.stderr or '')[-120:]!r}", file=sys.stderr)
        return None


def tick(D, dry):
    now = dt.datetime.now().strftime("%H%M")
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    sd = state.setdefault(D, {})
    out = []
    for src, cfg in BOTS.items():
        code, s = cfg["code"], sd.setdefault(src, {})
        if cfg.get("real") and real_follow(src, cfg, D, now, s, dry):   # 10/20: 先跟随用户实盘(清仓/加减仓), 跟随日 / 不持仓日不做 T
            continue
        b = book(src)
        pos = int((b.get("positions") or {}).get(code, {}).get("qty") or 0)
        nav = float(b.get("cash") or 0) + pos * float(((b.get("positions") or {}).get(code) or {}).get("cost") or 0)
        P = params(code, D)
        base = int(b.get("_t_base") or 0)
        if not s.get("open") and now >= ("0930" if not base else "0900"):   # 早盘挂单(只一次); 建底仓等开盘后按现价(防价格笼子拒单)
            lines = []
            if not base:   # 第 1 天建底仓
                q0 = snap(code) or {}
                last = float(q0.get("last") or 0) if not q0.get("stale") else 0
                if not last:
                    # 10/19 教训: 这里原先静默 continue, snap 解析 bug 让 9 本账本全天没建底仓、日志只写"无到点动作"
                    FAILS.append(f"{src} 建底仓取不到 {code} 现价(snap={'None' if not q0 else 'stale'})")
                    continue
                q = base_qty(cfg, last, D)
                lines.append(f"- {now[:2]}:{now[2:]} | {src} | BUY | {code} | {tick_px(code, last * 1.005):g} | {q} | day | {last:g} | - | 做T 建底仓(开盘后按现价)")
                s["base_plan"] = q
            elif cfg.get("hold"):   # 不 T 对照: 建完底仓就只拿着
                s["open"] = {"at": now, "note": "不T 对照, 只拿底仓"}
                continue
            else:
                tq = lot(code, base * T_FRAC)
                extra = max(0, pos - base)   # 银行昨日隔夜正 T 的多出部分, 今天一并高抛
                sell_px, buy_px = tick_px(code, P["prev"] * (1 + P["up"])), tick_px(code, P["prev"] * (1 - P["dn"]))
                lines.append(f"- 09:15 | {src} | SELL | {code} | {sell_px:g} | {tq + extra} | day | {P['prev']:g} | - | 做T 高抛 1/3(昨收+近30日最高中位 {P['up']:.2%})" + (f" 含隔夜多出 {extra}" if extra else ""))
                lines.append(f"- 09:15 | {src} | BUY | {code} | {buy_px:g} | {tq} | day | {P['prev']:g} | - | 做T 低吸 1/3(昨收-近30日最低中位 {P['dn']:.2%})")
            if not dry:
                rc, msg = write_import(D, src, lines)
                s["open"] = {"at": now, "rc": rc, "lines": lines, "msg": msg}
            out.append(f"{src} 早盘: " + " | ".join(lines))
        if s.get("open") and not s.get("close") and now >= "1445":   # 收口
            if base and cfg.get("hold"):
                s["close"] = {"at": now, "note": "不T 对照"}
                continue
            if not base:
                b["_t_base"] = pos   # 第 1 天收盘把实际成交的底仓数量记下来
                if not dry:
                    (DATA / "books" / f"{src}.json").write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
                s["close"] = {"at": now, "base": pos}
                out.append(f"{src} 收口: 底仓记 {pos}")
                continue
            q = snap(code) or {}
            last = float(q.get("last") or P["prev"])
            lines = []
            if pos < base:
                lines.append(f"- 14:45 | {src} | BUY | {code} | {tick_px(code, last * 1.01):g} | {base - pos} | day | {last:g} | - | 做T 收口买回(回到底仓)")
            elif pos > base and cfg["t0"]:
                lines.append(f"- 14:45 | {src} | SELL | {code} | {tick_px(code, last * 0.99):g} | {pos - base} | day | {last:g} | - | 做T 收口卖出多出部分(T+0)")
            if lines and not dry:
                rc, msg = write_import(D, src, lines)
                s["close"] = {"at": now, "rc": rc, "lines": lines, "msg": msg}
            else:
                s["close"] = {"at": now, "lines": lines, "note": "无需收口" if not lines else "dry"}
            out.append(f"{src} 收口: " + (" | ".join(lines) or f"持 {pos} = 底仓 {base}" + ("(银行多出部分留隔夜)" if pos > base else "")))
    if not dry:
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(out) or f"{now} 无到点动作")
    if FAILS and "0930" <= now <= "1500":
        print("ERROR: " + " | ".join(FAILS))   # 盘中取不到价 = 失败退出(check_md 记"t_bot 失败", 体检变红), 不再静默
        sys.exit(2)


FAILS = []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tick", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.status:
        for src, cfg in BOTS.items():
            print(src, cfg["name"], params(cfg["code"], a.date))
    if a.tick:
        tick(a.date, a.dry)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
