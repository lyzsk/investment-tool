# -*- coding: utf-8 -*-
"""open_live.py — 开盘实况(10/20 晚用户批"就这么做"; 零 token, 只读本地实时产物)

为什么: 10/9~10/20 共 8 天分钟线, 09:35 之后到 10:30 指数最大偏移中位 上证 0.43% / 创业板 1.35%, 偏移 ≥0.4% 首次出现在 09:39~10:11,
        09:35 的方向到收盘反向 7/16 → 只在 09:35 复核一次不够, 开盘到 10:30 要持续盯; 3 秒盘口 / 面板早就在采, 导师链从没读过
窗口: 09:25 竞价结果 → 09:31~10:30 每分钟算一次; 固定必判 09:31 / 09:45 / 10:00 / 10:30, 中间触发才判, 两次判定至少隔 3 分钟(必判不受冷却)
触发(任一): ① 上证 / 创业板 / 中证2000 距上次判定变动 ≥ 0.3 × 该指数 ATR14(前一交易日 indicators.jsonl; 10/20 约 上证 0.44% / 创业板 1.0%)
            ② 指数穿越昨收或时间均价线(09:30 起分钟价平均; 指数没有可用成交量做 VWAP)且站稳 2 分钟
            ③ A50 连续 / 小纳指 距上次判定 ≥ 0.5%
            ④ 关注票(3 秒盘口名单 = 各链持仓 + 挂单 + 计划单 + 用户持仓) ≥3 只同时偏离 09:31 价超过 1 个日振幅中位(近 30 日)
判定(机械打分, 不是 LLM): 三个 A 股指数各 3 分(相对昨收 / 相对时间均价线 / 近 10 分钟方向) + A50 / 小纳指 近 15 分钟方向各 1 分
            + 关注票站上 / 跌破自身 VWAP 的净比例 1 分 → 总分 ≥ +4 偏强 / ≤ −4 偏弱 / 其余 震荡(滞回: 回到 ±1 以内才退出); 因子表全部落盘
数据源: 面板 downloads/market/<日>/panel_minute.jsonl(collect_panel, 每分钟) · 3 秒盘口 book_snap.jsonl(collect_book) · 竞价 auction_live_open.json(collect_auction)
产物: downloads/market/<日>/open_live.json(原子重写): {state running|final, auction, idx, watch, judgments[{t, why, label, score, factors}], current, flips}
消费: facts.mjs「开盘实况」节(0927~1030 时段全链) · run_chain 子链闸条件 f(市况结论变了) · mix_plans(市况复核读 current) · ctx_index(决策T / 实盘复核)
API: from open_live import load, label_at, text; label_at(D, "0945") → 该时刻及以前最近一次判定的结论(没有 = None)
用法: python open_live.py --ensure | --run [--date D] | --replay --date D(用当日已落盘数据逐分钟重放, 自测 / 回看) | --show [--date D] [--before HHMM]
启动: check md --only mix 每 5 分钟调 --ensure(09:20~10:31 之间没在跑就后台拉起, 无窗口, pid 锁防双开)
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
ROOT = HERE.parents[1]
MKT = ROOT / "downloads" / "market"
LOCK = ROOT / "scripts" / "temp" / "open_live.pid"
LOG = ROOT / "scripts" / "temp" / "open_live.log"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
sys.path.insert(0, str(HERE))
import collect_panel as PANEL   # noqa: E402

START, FIRST, END = "0914", "0931", "1030"   # 10/20 晚 R2: 09:14 起先盯盘前外围回流
PRE_KEYS = {"A50": "A50连续", "NQ": "小纳指", "NKY": "日经", "KOSPI": "KOSPI"}
PRE_MUST = ("0914", "0920", "0925", "0927")
MUST = ("0931", "0945", "1000", "1030")
COOL_MIN = 3
IDX = {"SH": ("上证", "sh000001", 0.012), "CYB": ("创业板", "sz399006", 0.025), "CSI2000": ("中证2000", "sz399303", 0.025)}   # (名, ATR 取数代码(中证2000 用国证2000 近似), 缺省 ATR)
EXT = {"A50": "A50连续", "NQ": "小纳指"}
ATR_K, EXT_TH, WATCH_N, LABEL_TH, EXIT_TH = 0.3, 0.5, 3, 4, 1   # 滞回: ≥+4 进偏强, 回到 ≤+1 才退(偏弱对称), 防在阈值附近来回翻、反复触发子链


def log(*a):
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{dt.datetime.now():%m-%d %H:%M:%S}] " + " ".join(str(x) for x in a) + "\n")


def _jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def _hm(t):   # "09:31:05" / "0931" → "0931"
    return t.replace(":", "")[:4]


# ---------------- 取数 ----------------
def atr_pct(D):
    """前一交易日 indicators.jsonl 的 atr14_pct; 缺 = 缺省值"""
    out = {k: v[2] for k, v in IDX.items()}
    prev = sorted(p for p in MKT.glob("20??-??-??") if p.name < D and (p / "indicators.jsonl").exists())
    if not prev:
        return out
    want = {v[1]: k for k, v in IDX.items()}
    for l in (prev[-1] / "indicators.jsonl").open(encoding="utf-8"):
        if not any(s in l for s in want):
            continue
        r = json.loads(l)
        if r.get("symbol") in want and r.get("atr14_pct"):
            out[want[r["symbol"]]] = float(r["atr14_pct"])
    return out


def amp_median(code, D, n=30):
    k = (_jl(ROOT / "downloads" / "quotes" / "daily" / f"{code}.json", {}) or {}).get("klines") or []
    k = [x for x in k if x.get("d", "") < D][-(n + 1):]
    a = [(x["h"] - x["l"]) / p["c"] for p, x in zip(k, k[1:]) if p.get("c")]
    return st.median(a) if len(a) >= 5 else None


def book_rows(D, before):
    """3 秒盘口 → {code: [(t, p, vwap)]}(t ≤ before 的 HH:MM:59)"""
    f = MKT / D / "book_snap.jsonl"
    op = open
    if not f.exists():
        f = MKT / D / "book_snap.jsonl.gz"
        op = gzip.open
        if not f.exists():
            return {}
    cut = f"{before[:2]}:{before[2:]}:59"
    out = {}
    with op(f, "rt", encoding="utf-8") as fh:
        for l in fh:
            try:
                r = json.loads(l)
            except ValueError:
                continue
            t = r.get("t") or ""
            if t > cut or t < "09:30:00" or not r.get("p"):
                continue
            out.setdefault(str(r["s"])[2:], []).append((t, float(r["p"]), (float(r["a"]) / float(r["v"])) if r.get("v") else None))
    return out


def idx_series(D, before):
    """面板分钟价 → {key: [(hhmm, p, pc)]}, 只取当日 09:30 起(A50 / 小纳指 含 09:30 前一个点作起点)"""
    by = PANEL.rows_of(D, before)
    out = {}
    for k in list(IDX) + list(EXT):
        rs = [r for r in by.get(k) or [] if r.get("ts", "").startswith(D)]
        out[k] = [(_hm(r["t"]), r["p"], r.get("pc")) for r in rs if (_hm(r["t"]) >= "0930" or k in EXT)]
    return out


def auction_part(D):
    a = _jl(MKT / D / "auction_live_open.json", {}) or {}
    s = a.get("symbols") or {}
    out = {}
    for k, (n, sym, _) in IDX.items():
        x = s.get({"CSI2000": "sz399303"}.get(k, sym)) or s.get(sym)
        if x and x.get("fin"):
            out[n] = x["fin"].get("pct")
    return {"state": a.get("state"), "idx": out}


# ---------------- 计算 ----------------
def _at(series, hm):
    """≤ hm 的最后一个点"""
    v = [x for x in series if x[0] <= hm]
    return v[-1] if v else None


def snapshot(D, hm, atr, amps, base31):
    """hm 时刻的状态: 指数 / 外围 / 关注票 + 打分因子"""
    S = idx_series(D, hm)
    B = book_rows(D, hm)
    idx, fac, score = {}, [], 0
    for k, (n, _, _) in IDX.items():
        s = S.get(k) or []
        if not s or not s[-1][2]:
            idx[n] = None
            fac.append(f"{n} 缺数据(0 分)")
            continue
        t, p, pc = s[-1]
        twap = st.mean(x[1] for x in s)
        p10 = (_at(s, (dt.datetime.strptime(t, "%H%M") - dt.timedelta(minutes=10)).strftime("%H%M")) or s[0])[1]
        pct, d10 = (p / pc - 1) * 100, (p / p10 - 1) * 100
        a = atr[k] * 100
        s1 = (pct >= 0.1) - (pct <= -0.1)
        s2 = (p > twap * 1.0005) - (p < twap * 0.9995)
        s3 = (d10 >= 0.1 * a) - (d10 <= -0.1 * a)
        score += s1 + s2 + s3
        idx[n] = {"t": t, "p": p, "pct": round(pct, 2), "twap_gap": round((p / twap - 1) * 100, 2), "d10": round(d10, 2), "side_pc": s1, "side_twap": s2}
        fac.append(f"{n} {pct:+.2f}%(昨收 {s1:+d}) 离均价线 {(p / twap - 1) * 100:+.2f}%({s2:+d}) 近10分钟 {d10:+.2f}%({s3:+d})")
    ext = {}
    for k, n in EXT.items():
        s = S.get(k) or []
        if len(s) < 2:
            ext[n] = None
            continue
        p = s[-1][1]
        p15 = (_at(s, (dt.datetime.strptime(s[-1][0], "%H%M") - dt.timedelta(minutes=15)).strftime("%H%M")) or s[0])[1]
        d15 = (p / p15 - 1) * 100
        sc = (d15 >= 0.15) - (d15 <= -0.15)
        score += sc
        ext[n] = {"p": p, "pct": round((p / s[-1][2] - 1) * 100, 2) if s[-1][2] else None, "d15": round(d15, 2)}
        fac.append(f"{n} 近15分钟 {d15:+.2f}%({sc:+d})")
    watch, up, dn, moved = {}, 0, 0, []
    for c, rs in B.items():
        t, p, vw = rs[-1]
        w = {"p": p}
        if vw:
            w["vwap_gap"] = round((p / vw - 1) * 100, 2)
            up += p > vw * 1.001
            dn += p < vw * 0.999
        b = base31.get(c)
        if b and amps.get(c):
            w["from31"] = round((p / b - 1) * 100, 2)
            if abs(p / b - 1) >= amps[c]:
                moved.append(c)
        watch[c] = w
    n = len(watch)
    if n >= 5:
        r = (up - dn) / n
        sw = (r >= 0.3) - (r <= -0.3)
        score += sw
        fac.append(f"关注票 {n} 只: 站上自身均价 {up} / 跌破 {dn}({sw:+d})")
    return {"idx": idx, "ext": ext, "watch": watch, "moved": moved, "score": score, "factors": fac}


def hysteresis(score, prev, prev_score=None):
    """滞回 + 确认: 进入偏强 / 偏弱要本分钟和上一分钟都 ≥ +4(≤ −4); 退出要回到 ±1 以内(10/20 重放: 不加确认一天翻 5~6 次, 每次都触发全部子链)"""
    if prev == "偏强" and score > EXIT_TH:
        return "偏强"
    if prev == "偏弱" and score < -EXIT_TH:
        return "偏弱"
    ps = score if prev_score is None else prev_score
    return "偏强" if min(score, ps) >= LABEL_TH else "偏弱" if max(score, ps) <= -LABEL_TH else "震荡"


def triggers(cur, last, hist2, atr):
    """相对上次判定的触发原因(空 = 不触发)"""
    why = []
    for k, (n, _, _) in IDX.items():
        a, b = cur["idx"].get(n), (last or {}).get("idx", {}).get(n)
        if a and b and b.get("p"):
            d = (a["p"] / b["p"] - 1) * 100
            th = ATR_K * atr[k] * 100
            if abs(d) >= th:
                why.append(f"① {n} 距上次判定 {d:+.2f}% ≥ {th:.2f}%")
        if a and b:   # ② 穿越昨收 / 均价线且站稳 2 分钟(前两分钟同侧)
            for key, nm in (("side_pc", "昨收"), ("side_twap", "均价线")):
                if a[key] and b.get(key) is not None and a[key] != b[key] and all((h.get("idx", {}).get(n) or {}).get(key) == a[key] for h in hist2):
                    why.append(f"② {n} {'站上' if a[key] > 0 else '跌破'}{nm}并站稳 2 分钟")
    for n in EXT.values():
        a, b = cur["ext"].get(n), (last or {}).get("ext", {}).get(n)
        if a and b and b.get("p"):
            d = (a["p"] / b["p"] - 1) * 100
            if abs(d) >= EXT_TH:
                why.append(f"③ {n} 距上次判定 {d:+.2f}% ≥ {EXT_TH}%")
    if len(cur["moved"]) >= WATCH_N and len(cur["moved"]) > len((last or {}).get("moved") or []):
        why.append(f"④ 关注票 {len(cur['moved'])} 只偏离 09:31 价超过 1 个日振幅中位: {'、'.join(cur['moved'][:6])}")
    return why


def step(D, hm, S, atr, amps):
    """跑一个分钟: S = 状态(judgments / hist / base31)"""
    if not S.get("base31") and hm >= FIRST:
        B = book_rows(D, FIRST)
        S["base31"] = {c: rs[-1][1] for c, rs in B.items()}
    cur = snapshot(D, hm, atr, amps, S.get("base31") or {})
    J = S["judgments"]
    last = J[-1] if J else None
    cur["label"] = hysteresis(cur["score"], last["label"] if last else None, S["hist"][-1]["score"] if S["hist"] else None)
    why = []
    if hm in MUST:
        why.append(f"固定必判 {hm[:2]}:{hm[2:]}")
    cool = last and (dt.datetime.strptime(hm, "%H%M") - dt.datetime.strptime(last["t"], "%H%M")).seconds < COOL_MIN * 60
    if not cool or hm in MUST:
        why += triggers(cur, last, S["hist"][-2:], atr) if last else []
    if why and (not last or last["t"] != hm):
        J.append({"t": hm, "why": why, **{k: cur[k] for k in ("label", "score", "factors", "idx", "ext", "moved")}})
    S["hist"].append(cur)
    S["hist"] = S["hist"][-3:]
    S["cur"] = cur
    return cur


def pre_step(D, hm, S):
    """10/20 晚 市况改造 R2(用户批): 09:14~09:30 外围回流 —— 面板 A50 连续 / 小纳指 / 日经 / KOSPI 的当日过程标记(深跌后反转 / 冲高回落);
    09:14 / 09:20 / 09:25 / 09:27 必记一次, 中间出现新标记就记 + 推微信提示(每个标记每天只推一次)"""
    sm = {x["k"]: x for x in PANEL.summary(D, hm) if not x.get("缺")}
    snap = {n: {"pct": sm[k]["pct"], "d15": sm[k]["d15"], "tag": list(sm[k].get("tag") or [])} for k, n in PRE_KEYS.items() if k in sm}
    seen = S.setdefault("pre_tags", set())
    new = [f"{n}{t}" for n, v in snap.items() for t in v["tag"] if f"{n}{t}" not in seen]
    if hm in PRE_MUST or new:
        S.setdefault("pre", []).append({"t": hm, "new": new, "snap": snap})
    for x in new:
        seen.add(x)
    if new and not S.get("replay"):
        msg = f"[开盘实况 {hm[:2]}:{hm[2:]}] 外围回流: " + "、".join(new) + " | " + " / ".join(f"{n} {v['pct']:+.2f}%(近15分钟 {v['d15']:+.2f}%)" for n, v in snap.items())
        try:
            sys.path.insert(0, str(ROOT / "scripts" / "hermes"))
            import wx_send
            wx_send.send(msg, src="open_live")
        except Exception as e:   # noqa: BLE001
            log("推送失败", repr(e))


def write(D, S, state):
    J = S["judgments"]
    flips = [{"t": j["t"], "from": p["label"], "to": j["label"]} for p, j in zip(J, J[1:]) if p["label"] != j["label"]]
    cur = S.get("cur") or {}
    out = {"date": D, "updated": dt.datetime.now().isoformat(timespec="seconds"), "state": state, "auction": auction_part(D),
           "idx": cur.get("idx"), "ext": cur.get("ext"), "watch": cur.get("watch"),
           "pre": S.get("pre") or [],
           "judgments": [{k: j[k] for k in ("t", "why", "label", "score", "factors")} for j in J],
           "current": ({k: J[-1][k] for k in ("t", "label", "score")} if J else None), "flips": flips,
           "params": {"atr_k": ATR_K, "ext_th": EXT_TH, "watch_n": WATCH_N, "label_th": LABEL_TH, "exit_th": EXIT_TH, "cool_min": COOL_MIN, "must": MUST}}
    f = MKT / D / "open_live.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)
    return out


def _amps(D):
    B = book_rows(D, "1500")
    return {c: a for c in B if (a := amp_median(c, D))}


def run(D, replay=False):
    atr = atr_pct(D)
    S = {"judgments": [], "hist": []}
    amps = _amps(D) if replay else {}
    if replay:
        t = dt.datetime.strptime("0931", "%H%M")
        while t.strftime("%H%M") <= END:
            step(D, t.strftime("%H%M"), S, atr, amps)
            t += dt.timedelta(minutes=1)
        return write(D, S, "final")
    log("开始", D, "ATR", atr)
    while True:
        hm = dt.datetime.now().strftime("%H%M")
        if hm > END:
            break
        if hm < "0930":
            try:
                pre_step(D, hm, S)
            except Exception as e:   # noqa: BLE001
                log("ERR pre", hm, repr(e))
        if hm >= FIRST:
            if not amps:
                amps = _amps(D)
            try:
                step(D, hm, S, atr, amps)
            except Exception as e:   # noqa: BLE001  单轮失败不退出, 下一分钟再算
                log("ERR", hm, repr(e))
        try:
            write(D, S, "running")
        except OSError as e:
            log("写盘失败", repr(e))
        time.sleep(60 - dt.datetime.now().second + 8)   # 每分钟 :08 秒算(面板 :00 采, 留 8 秒)
    out = write(D, S, "final")
    log("结束", D, "判定", len(out["judgments"]), "翻转", out["flips"])
    return out


# ---------------- 消费 API ----------------
def load(D):
    return _jl(MKT / D / "open_live.json")


def label_at(D, hhmm):
    """该时刻及以前最近一次判定 → {t, label, score} | None"""
    J = [j for j in (load(D) or {}).get("judgments") or [] if j["t"] <= hhmm.replace(":", "")[:4]]
    return {k: J[-1][k] for k in ("t", "label", "score")} if J else None


def text(D, before=None):
    o = load(D)
    if not o:
        return ""
    cut = (before or "2359").replace(":", "")[:4]
    J = [j for j in o.get("judgments") or [] if j["t"] <= cut]
    a = (o.get("auction") or {}).get("idx") or {}
    L = [f"开盘实况(open_live, 零 token 机械判定; 09:31~10:30 每分钟算, 触发才判; 状态 {o.get('state')}):"]
    P = [x for x in o.get("pre") or [] if x["t"] <= cut]
    if P:
        x = P[-1]
        tags = [t for y in P for t in y["new"]]
        L.append(f"- 盘前外围({x['t'][:2]}:{x['t'][2:]}): " + " / ".join(f"{n} {v['pct']:+.2f}%(近15分钟 {v['d15']:+.2f}%{'; ' + '、'.join(v['tag']) if v['tag'] else ''})" for n, v in x["snap"].items())
                 + (f"; 09:14 后新出现: {'、'.join(tags)}" if tags else ""))
    if a:
        L.append("- 竞价 09:25: " + " / ".join(f"{k} {v:+.2f}%" for k, v in a.items() if v is not None))
    if not J:
        L.append("- 09:31 前还没有判定")
        return "\n".join(L)
    flips = [f"{p['t'][:2]}:{p['t'][2:]} {p['label']}→{j['t'][:2]}:{j['t'][2:]} {j['label']}" for p, j in zip(J, J[1:]) if p["label"] != j["label"]]
    L.append(f"- 当前结论({J[-1]['t'][:2]}:{J[-1]['t'][2:]}): **{J[-1]['label']}**(打分 {J[-1]['score']:+d}, ≥+4 偏强 / ≤−4 偏弱)" + (f"; 结论变化: {'; '.join(flips)}" if flips else "; 开盘以来结论未变"))
    L.append("- 因子: " + " | ".join(J[-1]["factors"]))
    L.append("- 判定记录: " + "; ".join(f"{j['t'][:2]}:{j['t'][2:]} {j['label']}({j['score']:+d}) ← {j['why'][0]}" + (f" 等 {len(j['why'])} 条" if len(j["why"]) > 1 else "") for j in J[-6:]))
    return "\n".join(L)


# ---------------- 守护 ----------------
def alive():
    try:
        pid = int(LOCK.read_text())
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return str(pid) in out
    except (OSError, ValueError):
        return False


def ensure():
    hm = dt.datetime.now().strftime("%H%M")
    if dt.date.today().weekday() >= 5 or not (START <= hm <= END) or alive():
        return
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))
    try:
        import a_rules as AR
        if not AR._is_trade_day_fallback(dt.date.today().isoformat()):
            return
    except Exception:   # noqa: BLE001
        pass
    p = subprocess.Popen([sys.executable, "-X", "utf8", str(Path(__file__)), "--run"], cwd=ROOT, creationflags=NOWIN,
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
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--before")
    a = ap.parse_args()
    if a.ensure:
        ensure()
    elif a.run:
        LOCK.parent.mkdir(exist_ok=True)
        LOCK.write_text(str(os.getpid()))
        run(a.date)
    elif a.replay:
        o = run(a.date, replay=True)
        print(text(a.date))
        print(f"判定 {len(o['judgments'])} 次, 翻转 {o['flips']}")
    elif a.show:
        print(text(a.date, a.before) or "(无 open_live)")


if __name__ == "__main__":
    main()
