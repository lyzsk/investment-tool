# -*- coding: utf-8 -*-
"""t_event.py — 决策T 事件驱动(10/20 晚用户批 TODO 一-2: 7 个触发条件, 先落地纳指 A-dndq; 零 token 盯盘, 触发才调模型)

为什么: 固定时段(09:33 / 10:33 / 13:03 / 14:33)要么错过行情(纳指 ETF 常停牌到 10:30, 复牌后几分钟波动最大), 要么没变化也花一次模型钱。
做什么: 09:30~14:50 每分钟(:12 秒)读本地实时产物, 对每个开了事件驱动的账本算 7 个触发条件, 满足 → `t_decide.py --tick --only <账本> --force-slot E<HHMM>`
  ① 价格: 距上次决策价 ≥ 0.3 × 近 30 日日内振幅中位
  ② 溢价率(ETF): 距上次决策 ≥ 1 个百分点(面板 NDQETF 每分钟一笔)
  ③ 穿越: 分时均价线 / 昨收 / 开盘价, 或创当日新高 / 新低(09:35 后; 新高新低要比上次决策时的高低点再多 1 个价位)
  ④ 量: 最近 1 分钟成交量 ≥ 3 × 之前 20 分钟每分钟均量(至少有 10 分钟数据)
  ⑤ 自己的挂单: 上次决策后有新成交, 或现价离未成交挂单 ≤ 1 个价位
  ⑥ 多指数面板新标记: 小纳指 / 纳指ETF 出现"深跌后反转 / 冲高回落"且上次决策时没有
  ⑦ 心跳: 距上次决策 ≥ 60 分钟
时段(纳指, 用户 10/20 批): 正常日 必判 09:33 / 10:00 / 10:30 / 11:00 / 11:30 / 13:05 / 14:00; 开盘停牌(常见到 10:30)的日子 复牌后第 3 分钟必判, 之后 11:00 / 11:30 / 13:05 / 14:00;
  开盘窗口(正常日 09:30~10:00 / 停牌日 复牌后 30 分钟)冷却 3 分钟, 窗口外冷却 5 分钟; 必判不受冷却; 每天模型调用上限 16 次(必判也计入, 到上限只留必判);
  14:45 后不再决策, 14:50 由 t_decide 机械收口; 停牌中不判
数据: 3 秒盘口 book_snap.jsonl(collect_book; 纳指 ETF 是做T 标的, 恒在名单) · 面板 panel_minute.jsonl(collect_panel: 溢价率 / 停牌 / 小纳指) · 账本 books/<账本>.json
开关: chain_flags.txt T_EVENT=1(t_decide 同一个开关: 开 = 事件账本只跑 0915 固定时段, 其余交给本脚本)
状态: scripts/dfcf/paper/t_event_state.json {日: {账本: {decisions:[{t, why, px, prem, hi, lo, n_trades}], calls}}}; 日志 scripts/temp/t_event.log
用法: python t_event.py --ensure | --run [--date D] | --replay --date D [--dry](用当日已落盘数据逐分钟重放, 只打印会在哪些分钟触发, 不调模型)
"""
import argparse
import datetime as dt
import gzip
import json
import os
import statistics as st
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MKT = ROOT / "downloads" / "market"
STATE = HERE / "t_event_state.json"
LOCK = ROOT / "scripts" / "temp" / "t_event.pid"
LOG = ROOT / "scripts" / "temp" / "t_event.log"
PY = ROOT / "scripts" / "venv" / "Scripts" / "python.exe"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "market"))

BOTS = {"A-dndq": {"code": "159941", "sym": "sz159941", "panel": "NDQETF", "tick": 0.001,
                   "must": ["0933", "1000", "1030", "1100", "1130", "1305", "1400"], "must_halt": ["1100", "1130", "1305", "1400"]}}
START, STOP, END = "0930", "1445", "1450"
K_PX, PREM_PP, VOL_X, HEART_MIN, COOL_IN, COOL_OUT, CAP = 0.3, 1.0, 3.0, 60, 3, 5, 16
K_EDGE = 0.1   # ③ 穿越 / 新高新低 要越过 max(2 个价位, 0.1 × 振幅中位 × 价) 才算(10/20 重放: 差 1 个价位就触发, 一天 17 次, 趋势里每创 1 分新低都判)
LUNCH = ("1131", "1259")


def log(*a):
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{dt.datetime.now():%m-%d %H:%M:%S}] " + " ".join(str(x) for x in a) + "\n")


def _jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def _min(hm):
    return int(hm[:2]) * 60 + int(hm[2:])


def _hm(m):
    return f"{m // 60:02d}{m % 60:02d}"


# ---------------- 取数 ----------------
def tape(D, sym, before):
    """3 秒盘口 → 按分钟聚合 [(hhmm, last, cum_vol, cum_amt, hi_so_far, lo_so_far)](只取 09:30 起, ≤ before)"""
    f, op = MKT / D / "book_snap.jsonl", open
    if not f.exists():
        f, op = MKT / D / "book_snap.jsonl.gz", gzip.open
        if not f.exists():
            return [], None
    cut = f"{before[:2]}:{before[2:]}:59"
    by, opn = {}, None
    with op(f, "rt", encoding="utf-8") as fh:
        for l in fh:
            if sym not in l:
                continue
            try:
                r = json.loads(l)
            except ValueError:
                continue
            t = r.get("t") or ""
            if r.get("s") != sym or t > cut or t < "09:30:00" or not r.get("p"):
                continue
            if opn is None and r.get("v"):
                opn = r["p"]
            by[t[:5].replace(":", "")] = (float(r["p"]), float(r.get("v") or 0), float(r.get("a") or 0))
    out, hi, lo = [], None, None
    for hm in sorted(by):
        p, v, a = by[hm]
        hi, lo = max(hi or p, p), min(lo or p, p)
        out.append((hm, p, v, a, hi, lo))
    return out, opn


def panel(D, key, before):
    """面板该键 ≤ before 的行(含停牌行)"""
    import collect_panel as P
    return (P.rows_raw(D, before) or {}).get(key) or []


def panel_tags(D, before):
    import collect_panel as P
    return {x["k"]: tuple(x.get("tag") or []) for x in P.summary(D, before) if not x.get("缺")}


def amp_median(code, D, n=30):
    k = (_jl(ROOT / "downloads" / "quotes" / "daily" / f"{code}.json", {}) or {}).get("klines") or []
    k = [x for x in k if x.get("d", "") < D][-(n + 1):]
    a = [(x["h"] - x["l"]) / p["c"] for p, x in zip(k, k[1:]) if p.get("c")]
    return (st.median(a) if len(a) >= 5 else 0.015), (k[-1]["c"] if k else None)


def book_state(src, D):
    b = _jl(HERE / "books" / f"{src}.json", {}) or {}
    trades = [t for t in b.get("trades") or [] if str(t.get("id", "")).startswith(D)]
    opens = [o for o in b.get("orders") or [] if o.get("status") == "open" and o.get("date") == D]
    return len(trades), [float(o["price"]) for o in opens if o.get("price")]


# ---------------- 判定 ----------------
def evaluate(D, src, cfg, hm, S, amp, prev, halted_at_open):
    """返回 (why[], snapshot{}) ; why 空 = 不判"""
    tp, opn = tape(D, cfg["sym"], hm)
    pr = [r for r in panel(D, cfg["panel"], hm) if str(r.get("ts", "")).startswith(D)]
    halt_now = bool(pr and pr[-1].get("halt"))
    if not tp or halt_now:
        return [], {"halt": halt_now}
    hm_last, p, v, a, hi, lo = tp[-1]
    prem = next((r.get("prem") for r in reversed(pr) if r.get("prem") is not None), None)
    n_tr, opens = book_state(src, D)
    vwap = a / v if v else None
    edge = max(2 * cfg["tick"], K_EDGE * amp * p)
    side = lambda ref: ((p > ref + edge) - (p < ref - edge)) if ref else 0   # 离参考价不到 edge = 0(不算在哪一侧, 防贴线来回)
    snap = {"t": hm, "px": p, "prem": prem, "hi": hi, "lo": lo, "n_trades": n_tr, "vwap": vwap,
            "side_vwap": side(vwap), "side_prev": side(prev), "side_open": side(opn), "tags": panel_tags(D, hm)}
    resume = S.setdefault("resume", tp[0][0])
    musts = [_hm(_min(resume) + 3)] + cfg["must_halt"] if halted_at_open else cfg["must"]
    J = S.setdefault("decisions", [])
    last = J[-1] if J else None
    why = []
    if hm in musts or (not last and _min(hm) >= _min(musts[0])):
        why.append(f"必判 {hm[:2]}:{hm[2:]}")
    if last:
        th = K_PX * amp * last["px"]
        if abs(p - last["px"]) >= th:
            why.append(f"① 价格距上次决策 {p - last['px']:+.3f}(≥ {th:.3f} = 0.3×振幅中位 {amp:.2%})")
        if prem is not None and last.get("prem") is not None and abs(prem - last["prem"]) >= PREM_PP:
            why.append(f"② 溢价率 {last['prem']:.2f}% → {prem:.2f}%")
        for k, nm in (("side_vwap", "均价线"), ("side_prev", "昨收"), ("side_open", "开盘价")):
            if snap[k] and last.get(k) and snap[k] != last[k]:   # 两次都明确在某一侧且换了边
                why.append(f"③ {'站上' if snap[k] > 0 else '跌破'}{nm}")
        if hm >= "0935":
            if last.get("hi") and hi >= last["hi"] + edge and p >= hi - cfg["tick"]:
                why.append(f"③ 创当日新高 {hi:g}")
            if last.get("lo") and lo <= last["lo"] - edge and p <= lo + cfg["tick"]:
                why.append(f"③ 创当日新低 {lo:g}")
        if len(tp) >= 11:
            vols = [tp[i][2] - tp[i - 1][2] for i in range(max(1, len(tp) - 21), len(tp))]
            base = vols[:-1][-20:]
            if base and st.mean(base) > 0 and vols[-1] >= VOL_X * st.mean(base):
                why.append(f"④ 1 分钟量 {vols[-1]:.0f} ≥ {VOL_X}× 前 {len(base)} 分钟均量 {st.mean(base):.0f}")
        if n_tr > last.get("n_trades", 0):
            why.append(f"⑤ 上次决策后新成交 {n_tr - last.get('n_trades', 0)} 笔")
        near = [o for o in opens if abs(o - p) <= cfg["tick"] + 1e-9]
        if near:
            why.append(f"⑤ 现价 {p:g} 离挂单 {near[0]:g} ≤ 1 个价位")
        for k in ("NQ", cfg["panel"]):
            new = set(snap["tags"].get(k) or ()) - set((last.get("tags") or {}).get(k) or ())
            if new:
                why.append(f"⑥ 面板 {k} 新标记 {'、'.join(new)}")
        gap = _min(hm) - _min(last["t"]) - (89 if last["t"] <= LUNCH[0] < hm else 0)   # 午休 11:30~13:00 不算时长
        if gap >= HEART_MIN:
            why.append(f"⑦ 心跳: 距上次决策 {gap} 个交易分钟")
    if not why:
        return [], snap
    must = any(w.startswith("必判") for w in why)
    win_end = _min(resume) + 30 if halted_at_open else _min("1000")
    cool = COOL_IN if _min(hm) <= win_end else COOL_OUT
    if not must and last and _min(hm) - _min(last["t"]) < cool:
        return [], snap
    if not must and S.get("calls", 0) >= CAP:
        return [], snap
    return why, snap


def fire(D, src, hm, dry):
    if dry:
        return 0, "dry"
    r = subprocess.run([str(PY), "-X", "utf8", str(HERE / "t_decide.py"), "--tick", "--date", D, "--only", src, "--force-slot", f"E{hm}"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN, timeout=900)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()[-300:]


def halted_open(D, cfg, hm):
    """开盘停牌: 09:30~09:33 面板标停牌, 或 3 秒盘口 09:35 前没有任何成交"""
    pr = [r for r in panel(D, cfg["panel"], hm) if str(r.get("ts", "")).startswith(D) and "09:30:00" <= r.get("t", "") <= "09:33:59"]
    if any(r.get("halt") for r in pr):
        return True
    tp, _ = tape(D, cfg["sym"], min(hm, "0935"))
    return hm >= "0935" and not tp


def run(D, dry=False, replay=False):
    state = _jl(STATE, {}) if not replay else {}
    sd = state.setdefault(D, {})
    meta = {src: amp_median(cfg["code"], D) for src, cfg in BOTS.items()}
    log("开始", D, "replay" if replay else "", {k: f"振幅中位 {v[0]:.2%} 昨收 {v[1]}" for k, v in meta.items()})
    m = _min(START)
    while True:
        hm = _hm(m) if replay else dt.datetime.now().strftime("%H%M")
        if hm > STOP:
            break
        if hm >= START and not (LUNCH[0] <= hm <= LUNCH[1]):
            for src, cfg in BOTS.items():
                S = sd.setdefault(src, {})
                if S.get("done_" + hm):
                    continue
                S["done_" + hm] = 1
                try:
                    ho = S.get("halted_open")
                    if ho is None and hm >= "0935":
                        ho = S["halted_open"] = halted_open(D, cfg, hm)
                    why, snap = evaluate(D, src, cfg, hm, S, meta[src][0], meta[src][1], bool(ho))
                except Exception as e:   # noqa: BLE001
                    log("ERR", src, hm, repr(e))
                    continue
                if not why:
                    continue
                S["calls"] = S.get("calls", 0) + 1
                rc, msg = fire(D, src, hm, dry or replay)
                S["decisions"].append({**{k: snap.get(k) for k in ("t", "px", "prem", "hi", "lo", "n_trades", "side_vwap", "side_prev", "side_open", "tags")}, "why": why, "rc": rc})
                log(src, hm, "触发:", " | ".join(why), "→ rc", rc, msg[-120:].replace("\n", " "))
            for k in list(sd.get(src, {})):
                if k.startswith("done_") and k < "done_" + _hm(max(0, _min(hm) - 5)):
                    del sd[src][k]
            if not replay:
                STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        if replay:
            m += 1
        else:
            time.sleep(60 - dt.datetime.now().second + 12)
    return sd


def alive():
    try:
        pid = int(LOCK.read_text())
        return str(pid) in subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, creationflags=NOWIN).stdout
    except (OSError, ValueError):
        return False


def ensure():
    import decision_memory as DM
    if (DM.flag_raw("T_EVENT") or "0") != "1":
        return
    hm = dt.datetime.now().strftime("%H%M")
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))
    import a_rules as AR
    if not ("0925" <= hm <= STOP) or not AR._is_trade_day_fallback(dt.date.today().isoformat()) or alive():
        return
    p = subprocess.Popen([str(PY), "-X", "utf8", str(Path(__file__)), "--run"], cwd=ROOT, creationflags=NOWIN | getattr(subprocess, "DETACHED_PROCESS", 0),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    LOCK.parent.mkdir(exist_ok=True)
    LOCK.write_text(str(p.pid))
    log("拉起", p.pid)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensure", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    if a.ensure:
        ensure()
    elif a.run:
        LOCK.parent.mkdir(exist_ok=True)
        LOCK.write_text(str(os.getpid()))
        run(a.date, a.dry)
    elif a.replay:
        sd = run(a.date, replay=True)
        for src, S in sd.items():
            print(f"{src} 开盘停牌={S.get('halted_open')} 复牌={S.get('resume')} 决策 {len(S.get('decisions') or [])} 次:")
            for d in S.get("decisions") or []:
                print(f"  {d['t'][:2]}:{d['t'][2:]} 价 {d['px']:g} ← {' | '.join(d['why'])}")


if __name__ == "__main__":
    main()
