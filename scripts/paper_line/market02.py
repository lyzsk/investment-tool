# -*- coding: utf-8 -*-
"""market02.py — 02 市况全体共用(10/24 📋1: 02 市况只算一次、各本共用; 用户同意"按将来按 token 计费的方式省")

一个"市况会话"(和各本账一样是 claude -p 会话: 第一次 --session-id, 之后 --resume)只写 02(态度 / 证据编号 / 方向 / 翻转条件, 同 harness.ASK02_V2):
  盘前首跑: 总控 08:52 现做事实包之后跑一次(09:00 各本盘前首跑前写好) → 各本盘前首跑材料里直接带"02 共用市况", 不再各写一份 02
  刷新(10/24 用户: 不要固定时段, 触发式): 每 15 秒机械检查一次, 命中任一条就刷新(只发新材料, 续同一会话) → 各本下一次触发消息里带"02 共用市况(HH:MM 版, 因: …)"
    ① 上一版 02 自己写的 flip_if(指数涨跌幅条件)成立
    ② 大盘(上证) / 小盘(国证2000) 路径的结构变化日志多了一条(突破前高 / 跌破前低, 带滞回)
    ③ 上证 / 国证2000 相对上一版 02 时刻又走了 ≥ IDX_MOVE(上证 0.6 个点 / 国证2000 1.0 个点)
    ④ 盘面情绪相对上一版: 涨停家数变化 ≥ 30% 且 ≥ 15 家, 或炸板率变化 ≥ 15 个点, 或跌停家数变化 ≥ 20 家
    ⑤ 竞价定格(09:25 撮合出结果, 盘前首跑那版还看不到竞价)
    冷却: 两次刷新至少隔 COOL_MIN 分钟(⑤ 不受限); 每天最多 MAX_N 次; 阈值可在 harness.yaml steps.02.refresh 改
材料(只用 ≤ 此刻的数据, 回放不偷看): 大小盘路径 + 3 秒指数 · 外围面板 · 盘面情绪 · 开盘实况 · 近 10 日情绪周期 · 近 5 日题材 · 今天 md 盘前(早报 / 发哥) · 前一天 md 摘要
     + 10/25 方向证据包(tools/market02_extra.py): 导师 T−1 / T−2 / T−3 实际买卖 → 题材方向(按近 20 日收益加权) · UP 近 3 日定调 · 发哥近 3 日推演 + 近 20 日核销命中率 · 指数 K 线结构 · market-skill 全文
产物: results/_live/<D>/_market/(session.json · 02_<HHMM>.md · 02_<HHMM>.json · log.jsonl); 回放写回放目录
开关: harness.yaml steps.02.shared(默认 true); false = 各本照旧自己写 02
"""
import datetime as dt
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V3 = ROOT / "scripts" / "paper_line"
sys.path[:0] = [str(V3), str(V3 / "tools"), str(ROOT / "scripts" / "chain"), str(ROOT / "scripts" / "market")]
TRIG = {"idx_move": {"sh000001": 0.6, "sz399303": 1.0}, "zt_ratio": 0.3, "zt_min": 15, "zbr_pts": 15, "dt_n": 20, "cool_min": 10, "max_n": 12}


def trig_cfg():
    try:
        import yaml
        d = yaml.safe_load((ROOT / "scripts" / "live" / "harness.yaml").read_text(encoding="utf-8")) or {}
        return {**TRIG, **((((d.get("steps") or {}).get("02") or {}).get("refresh")) or {})}
    except Exception:   # noqa: BLE001
        return dict(TRIG)


def snap(D, at):
    """此刻的机械市况快照(只用 ≤ at): 指数涨跌幅 / 大小盘结构变化条数 / 情绪"""
    import market_path as MP
    out = {"t": at, "pct": {}, "log": {}, "mood": {}}
    try:
        R = MP._rows(D, at)
        for s, v in R.items():
            out["pct"][s] = round((v[-1]["p"] / v[-1]["pc"] - 1) * 100, 2)
        b = MP.build(D, at)
        for k in ("大", "小"):
            if b.get(k):
                out["log"][k] = [f"{x[0]} {x[1]}" for x in b[k]["log"]]
    except Exception:   # noqa: BLE001
        pass
    try:
        import collect_mood as CM
        rs = CM.rows(D, at)
        if rs:
            out["mood"] = {k: rs[-1].get(k) for k in ("zt", "zb", "dt", "seal", "t")}
    except Exception:   # noqa: BLE001
        pass
    return out


def _flip_hit(fl, pct):
    for x in fl or []:
        if not isinstance(x, dict) or x.get("code") not in pct or not isinstance(x.get("pct"), (int, float)):
            continue
        v = pct[x["code"]]
        if (x.get("op") == ">=" and v >= x["pct"]) or (x.get("op") == "<=" and v <= x["pct"]):
            return f"上一版翻转条件成立: {x['code']} {x['op']} {x['pct']}%(现 {v:+.2f}%; {x.get('why', '')})"
    return None


def trigger(last, now, cfg):
    """→ 触发原因(字符串) 或 None; last = 上一版 02 的 rec(含 base 快照)"""
    base = (last or {}).get("base") or {}
    if not base:
        return None
    if now["t"] >= "09:25:05" and base.get("t", "") < "09:25:00":
        return "竞价定格(09:25 撮合结果出来了)"
    hit = _flip_hit(((last or {}).get("json") or {}).get("flip_if"), now["pct"])
    if hit:
        return hit
    nm = {"大": "大盘(上证)", "小": "小盘(国证2000)"}
    for k in ("大", "小"):
        a, b = base.get("log", {}).get(k) or [], now["log"].get(k) or []
        if len(b) > len(a):
            return f"{nm[k]}结构变化: {b[-1]}"
    for s, th in cfg["idx_move"].items():
        if s in now["pct"] and s in base.get("pct", {}) and abs(now["pct"][s] - base["pct"][s]) >= th:
            return f"{'上证' if s == 'sh000001' else '国证2000'} 相对上一版又走了 {now['pct'][s] - base['pct'][s]:+.2f} 个点(阈值 {th})"
    m0, m1 = base.get("mood") or {}, now["mood"] or {}
    if m0 and m1 and m1.get("t") != m0.get("t"):
        z0, z1 = m0.get("zt") or 0, m1.get("zt") or 0
        if abs(z1 - z0) >= max(cfg["zt_min"], cfg["zt_ratio"] * max(z0, 1)):
            return f"涨停家数 {z0} → {z1}"
        if m0.get("seal") is not None and m1.get("seal") is not None and abs((100 - m1["seal"]) - (100 - m0["seal"])) >= cfg["zbr_pts"]:
            return f"炸板率 {100 - m0['seal']}% → {100 - m1['seal']}%"
        if abs((m1.get("dt") or 0) - (m0.get("dt") or 0)) >= cfg["dt_n"]:
            return f"跌停家数 {m0.get('dt')} → {m1.get('dt')}"
    return None
OUT = {"dir": None}   # 回放时改成回放目录


def out_dir(D):
    return Path(OUT["dir"]) / D / "_market" if OUT["dir"] else ROOT / "results" / "_live" / D / "_market"


def shared_on():
    try:
        import harness as H
        return bool(H.cfg().get("shared02", True))
    except Exception:   # noqa: BLE001
        return True


def open_text(D, until):
    try:
        o = json.loads((ROOT / "downloads" / "market" / D / "open_live.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "(开盘实况还没出判定)"
    hm = lambda t: (t[:2] + ":" + t[2:4]) if len(t) == 4 and ":" not in t else t[:5]   # noqa: E731  open_live 的 t 是 "0957"(没冒号), 直接和 "09:00:00" 比会把 09:57 当成更早 → 偷看
    J = [j for j in o.get("judgments") or [] if hm(str(j.get("t", ""))) <= until[:5]]
    if not J:
        return "(开盘实况还没出判定)"
    j = J[-1]
    return f"最新判定 {j.get('t')}: {j.get('label')}(分 {j.get('score')})\n" + "\n".join(f"- {x}" for x in j.get("factors") or [])


def material(D, at, open_fn=None):
    import pack
    import chain_steps as SC
    secs = []

    def add(title, fn):
        try:
            secs.append((title, fn()))
        except Exception as e:   # noqa: BLE001  一块失败照常出其它块, 写明缺什么
            secs.append((title, f"(取不到: {e!r})"[:160]))
    add("A 股指数(3 秒级) + 大小盘路径", lambda: SC.index3_block(D, at))
    add("指数 / 外围面板(分钟级)", lambda: SC.index_block(D, at))
    add("盘面情绪", lambda: __import__("collect_mood").block(D, at))
    add("开盘实况(机械判定)", lambda: (open_fn or open_text)(D, at))
    add("近 10 日情绪周期", lambda: pack.emotion_table(D))
    add("近 5 日最活跃题材及阶段", lambda: pack.theme_top(D))
    add("今天 md 盘前(财联社早报 / 发哥)", lambda: _md_pre(pack, D))
    add("前一天 md 摘要", lambda: pack.md_digest(pack.rd(pack.md_path(pack.prev_day(D))), ""))
    try:   # 10/25 用户批 ❓7: 方向证据包(导师 T−1~T−3 实际买卖 / UP 近 3 日 / 发哥命中率 / 指数 K 线 / market-skill)
        import market02_extra as MX2
        secs += MX2.blocks(D, at)
    except Exception as e:   # noqa: BLE001
        secs.append(("方向证据包", f"(取不到: {e!r})"[:160]))
    return "\n\n".join(f"## {t}\n{b}" for t, b in secs)


def _md_pre(pack, D):
    import re
    t = pack.rd(pack.md_path(D)) or ""
    m = re.search(r"^## 盘前.*?(?=^## |\Z)", t, re.S | re.M)
    if not m:
        return "(今天的 md 还没有盘前节)"
    # 10/25 修回放偷看(示例 02 自己发现的): 发哥小节末尾的「【核销 当日】」是当天收盘后才追加的 → 盘前材料里去掉
    return "\n".join(l for l in m.group(0).splitlines() if not l.lstrip().startswith("【核销"))


_LOCK = threading.Lock()
BUSY = [0]   # 回放时钟用: 市况 02 在想的时候时钟按真实速度走(同各本账的 GATE)


def run(D, at, fake=False, open_fn=None, why="盘前首跑"):
    """跑一次 02(盘前首跑或刷新) → dict(t, json, text, usd) 并落盘; 失败返回 None"""
    import harness as H
    from session import Session
    od = out_dir(D)
    od.mkdir(parents=True, exist_ok=True)
    with _LOCK:
      BUSY[0] += 1
      try:
        s = Session("_market", D, od, effort="medium")
        mat = material(D, at, open_fn)
        hm = at[:5].replace(":", "")
        if fake:
            r = {"ok": True, "text": f"(桩 02 {at})", "json": {"attitude": "中性", "why": ["桩 M大1"], "directions": [], "vs_mech": "无", "flip_if": [], "state": "桩"}, "usd": 0.0}
            s.st = {"date": D, "line": "_market", "sid": "fake", "turns": []}
        elif not s.booted:
            r = s.ask(f"{s.tag} 市况会话: 只写 02 市况, 给全部账本共用(不涉及任何导师)。数据截至 {at}。\n\n{mat}\n\n---\n\n{H.ASK02_V2}", "02", timeout=300, boot=True)
        else:
            r = s.ask(f"[刷新 {at}] 触发原因: {why}。下面是此刻的新材料(之前的你都看过)。按同样要求重写 02; 和上一版比变了什么写进 note。\n\n{mat}\n\n---\n\n{H.ASK02_V2}", "02", timeout=240)
        if not r.get("ok") and not fake:
            _log(od, {"t": at, "kind": "02 失败", "err": r.get("err")})
            return None
        V = H.gate02(r.get("json"), r.get("text"), mat)
        rec = {"t": at, "why": why, "json": r.get("json"), "text": r.get("text"), "usd": round(float(r.get("usd") or 0), 4), "gate": V, "base": snap(D, at)}
        (od / f"02_{hm}.md").write_text(r.get("text") or "", encoding="utf-8")
        (od / f"02_{hm}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        _log(od, {"t": at, "kind": "02", "why": why, "usd": rec["usd"], "gate": V[:6], "real": dt.datetime.now().strftime("%H:%M:%S")})
        return rec
      finally:
        BUSY[0] -= 1


def _log(od, x):
    with (od / "log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(x, ensure_ascii=False) + "\n")


def latest(D, until):
    """≤ until 的最新一版 → dict 或 None"""
    od = out_dir(D)
    fs = sorted(f for f in od.glob("02_*.json") if f.stem[3:] <= until[:5].replace(":", ""))
    if not fs:
        return None
    try:
        return json.loads(fs[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def block(rec):
    """给各本看的文字版"""
    j = rec.get("json") or {}
    if not j:
        return f"## 02 共用市况({rec.get('t', '')[:5]} 版)\n{(rec.get('text') or '')[-1500:]}"
    fl = "; ".join(f"{x.get('code')} {x.get('op')} {x.get('pct')}%({x.get('why', '')})" for x in j.get("flip_if") or [] if isinstance(x, dict))
    dirs = "、".join(f"{d.get('theme')}({d.get('ref', '')})" if isinstance(d, dict) else str(d) for d in j.get("directions") or [])
    return (f"## 02 共用市况({rec.get('t', '')[:5]} 版, 因: {rec.get('why', '盘前首跑')}; 市况会话写, 全部账本共用; 你按本导师的打法用它, 不用重写 02)\n"
            f"- 态度: {j.get('attitude')}({j.get('state', '')})\n- 依据: " + " | ".join(str(w) for w in j.get("why") or []) +
            f"\n- 方向: {dirs or '无'}\n- 和机械状态不一致: {j.get('vs_mech', '-')}\n- 翻转条件: {fl or '-'}" + (f"\n- 备注: {j.get('note')}" if j.get("note") else "")
            + ("\n- UP 近 3 日: " + " | ".join(f"{k}: {v}" for k, v in (j.get("up_views") or {}).items()) if j.get("up_views") else ""))


def scheduler(D, now_fn, fake=False, stop=lambda: False, open_fn=None, sleep=time.sleep):
    """后台线程: 每 15 秒(按 now_fn 的时钟)机械检查一次触发条件, 命中就刷新 02(盘前首跑那版由调用方先跑); 冷却 / 每日上限见 TRIG"""
    cfg = trig_cfg()
    last_chk, n = None, 0
    while not stop():
        now_dt = now_fn()
        t = now_dt.strftime("%H:%M:%S")
        if t >= "15:00:00":
            break
        if ("11:30:30" <= t < "13:00:00") or (last_chk and (now_dt - last_chk).total_seconds() < 15):
            sleep(1)
            continue
        last_chk = now_dt
        last = latest(D, t)
        if not last or n >= cfg["max_n"]:
            sleep(1)
            continue
        try:
            why = trigger(last, snap(D, t), cfg)
            if why and not why.startswith("竞价定格"):
                lt = dt.datetime.strptime(last["t"][:8], "%H:%M:%S")
                if (dt.datetime.strptime(t, "%H:%M:%S") - lt).total_seconds() < cfg["cool_min"] * 60:
                    why = None
            if why:
                n += 1
                run(D, t, fake=fake, open_fn=open_fn, why=why)
        except Exception as e:   # noqa: BLE001
            _log(out_dir(D), {"t": t, "kind": "02 刷新异常", "err": repr(e)[:200]})
        sleep(1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = sys.argv[1:]
    D, at = (a + [dt.date.today().isoformat(), "09:00:00"])[:2]
    m = material(D, at)
    print(f"材料 {len(m)} 字 ≈ {len(m.encode()) // 1024} KB")
    print(m[:3000])
