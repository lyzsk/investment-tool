# -*- coding: utf-8 -*-
"""market_path.py — 大盘(上证指数) / 小盘(国证2000) 开盘到此刻的路径(10/24 用户定: 喂模型路径和变化日志, 枚举只留给代码用; 零 token)

为什么不用单一枚举: chain 一天触发很多次, 每次只看"单边走弱 / 震荡 / 弱转强"一个词 → 阈值边上来回跳、把事后才知道的"转强"说成确定
给模型的是(每次触发都是同一条时间线往后长, 前后不矛盾):
  ① 连续量: 现价相对昨收 / 相对开盘、当日区间位置(0~100%)、距今日高 / 低、近 30 分钟
  ② zigzag 分段: 每段 起止时刻 / 方向 / 幅度, 最后一段标"进行中"; 段编号 M大1 / M小1 … 供 02 / 04 引用
  ③ 结构变化日志(带滞回): 只有价格突破上一个确认的波段高点才记"转强", 跌破上一个确认的波段低点才记"转弱"; 不突破就不改状态
  ④ 大小盘背离: 国证2000 − 上证 的涨跌差现值 / 30 分钟前 / 穿越 0 轴时刻
  代码标签 tag(给 harness / 回测 / 本体用, 模型不以它为主): 单边走强 / 单边走弱 / 震荡 / 弱转强@HH:MM / 强转弱@HH:MM
数据: downloads/market/<日>/index_snap.jsonl(3 秒级, collect_book) → 按分钟取最后一笔; 只用 ≤ until 的行
阈值: zigzag 回撤阈值 上证 0.5% / 国证2000 0.8%(⚙️ 先用, 回测后调; harness.yaml market_path 可改)
用法: python market_path.py <D> [HH:MM:SS]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MKT = ROOT / "downloads" / "market"
GROUPS = [("sh000001", "上证指数", "大", 0.5), ("sz399303", "国证2000", "小", 0.8)]   # 10/24 实测 0.3 / 0.5 太碎(10/22 沪深300 切 17 段); 10/24 用户: 大盘看上证不看沪深300
BREAK = 1 / 3   # 突破前高 / 跌破前低至少超出 阈值 × 这个比例才改状态(防刚碰一下就翻)


def _rows(D, until, reader=None):
    p = MKT / D / "index_snap.jsonl"
    txt = reader(p) if reader else (p.read_text(encoding="utf-8") if p.exists() else "")
    out = {}
    for l in txt.splitlines():
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if r.get("t", "") <= until and r.get("p") and r.get("pc"):
            out.setdefault(r["s"], []).append(r)
    return out


def _minutes(v):
    """→ 开盘价, [(HH:MM, 价)] 09:30 起每分钟最后一笔"""
    o = next((r["p"] for r in v if r["t"] >= "09:25:00"), None)
    m = {"09:29": o} if o else {}   # 起点 = 开盘价(键 09:29, 显示时换成"开盘")(不用 09:30 那一分钟的末价, 否则会把盘中低价当"前高")
    for r in v:
        if r["t"] >= "09:30:00":
            m[r["t"][:5]] = r["p"]
    return o, sorted(m.items())


def zigzag(seq, th):
    """seq = [(t, p)]; th = 回撤阈值 %. → 已确认拐点 [(t, p, 'H'|'L')] + 当前未确认的极值"""
    if not seq:
        return [], None
    piv, d = [], 0          # d: 1 = 上涨段中, -1 = 下跌段中, 0 = 未定
    ext_t, ext_p = seq[0]
    start = seq[0]
    for t, p in seq[1:]:
        if d >= 0 and p > ext_p or d <= 0 and p < ext_p:
            if d == 0:
                if abs(p / start[1] - 1) * 100 >= th:
                    d = 1 if p > start[1] else -1
                    piv.append((start[0], start[1], "L" if d == 1 else "H"))
            ext_t, ext_p = t, p
            continue
        if d == 1 and (ext_p - p) / ext_p * 100 >= th:
            piv.append((ext_t, ext_p, "H"))
            d, ext_t, ext_p = -1, t, p
        elif d == -1 and (p - ext_p) / ext_p * 100 >= th:
            piv.append((ext_t, ext_p, "L"))
            d, ext_t, ext_p = 1, t, p
        elif d == 0 and abs(p / start[1] - 1) * 100 >= th:
            d = 1 if p > start[1] else -1
            piv.append((start[0], start[1], "L" if d == 1 else "H"))
            ext_t, ext_p = t, p
    return piv, (ext_t, ext_p, d)


def structure(seq, th):
    """逐分钟回放: 用到那一刻为止的确认拐点判结构, 只在突破 / 跌破时改状态(滞回) → 变化日志 [(t, 状态, 说明)]"""
    log, state = [], "未定"
    for i in range(2, len(seq) + 1):
        piv, _ = zigzag(seq[:i], th)
        t, p = seq[i - 1]
        hs = [x for x in piv if x[2] == "H"]
        ls = [x for x in piv if x[2] == "L"]
        new = None
        mg = th * BREAK / 100
        if hs and p > hs[-1][1] * (1 + mg) and state in ("未定", "走弱", "强转弱"):
            new = ("弱转强" if state in ("走弱", "强转弱") else "走强", f"上破前高 {hs[-1][1]:.2f}({hs[-1][0]})")
        elif ls and p < ls[-1][1] * (1 - mg) and state in ("未定", "走强", "弱转强"):
            new = ("强转弱" if state in ("走强", "弱转强") else "走弱", f"跌破前低 {ls[-1][1]:.2f}({ls[-1][0]})")
        elif state == "未定" and piv:
            first = piv[0]
            if len(piv) == 1:
                new = ("走强", f"开盘后首段上涨 ≥{th}%") if first[2] == "L" else ("走弱", f"开盘后首段下跌 ≥{th}%")
        if new and new[0] != state:
            state = new[0]
            log.append((t, state, new[1]))
    return log


def group(v, th):
    o, seq = _minutes(v)
    if not seq or not o:
        return None
    pc = v[-1]["pc"]
    now_t, now = seq[-1]
    hi, lo = max(max(p for _, p in seq), o), min(min(p for _, p in seq), o)
    piv, cur = zigzag(seq, th)
    pts = [(seq[0][0] if seq else "09:30", o)] + [(t, p) for t, p, _ in piv if t != seq[0][0]] + [(now_t, now)]
    segs = []
    for (t1, p1), (t2, p2) in zip(pts, pts[1:]):
        if t1 == t2:
            continue
        segs.append({"from": t1, "to": t2, "pct": round((p2 / p1 - 1) * 100, 2)})
    if segs:
        segs[-1]["进行中"] = True
    log = structure(seq, th)
    t30 = [p for t, p in seq if t <= f"{int(now_t[:2]) - (1 if int(now_t[3:]) < 30 else 0):02d}:{(int(now_t[3:]) - 30) % 60:02d}"]
    if not log:
        tag = "未走出趋势(震荡)"
    elif len(log) == 1:
        tag = f"单边{log[-1][1]}"
    else:
        tag = f"{log[-1][1]}@{log[-1][0]}(今日第 {len(log) - 1} 次翻转)"
    return {"pct": round((now / pc - 1) * 100, 2), "vs_open": round((now / o - 1) * 100, 2), "open": round((o / pc - 1) * 100, 2),
            "pos": round((now - lo) / (hi - lo) * 100) if hi > lo else 50, "from_hi": round((now / hi - 1) * 100, 2), "from_lo": round((now / lo - 1) * 100, 2),
            "m30": round((now / t30[-1] - 1) * 100, 2) if t30 else None, "segs": segs, "log": log, "tag": tag, "t": now_t, "th": th}


def build(D, until, reader=None):
    R = _rows(D, until, reader)
    out = {}
    for s, name, k, th in GROUPS:
        if R.get(s):
            g = group(R[s], th)
            if g:
                out[k] = dict(g, name=name)
    if "大" in out and "小" in out:
        b = {r["t"][:5]: (r["p"] / r["pc"] - 1) * 100 for r in R["sh000001"] if r["t"] >= "09:30:00"}
        seq, side, cross = [], None, []
        for r in R["sz399303"]:
            m = r["t"][:5]
            if r["t"] >= "09:30:00" and m in b and (not seq or seq[-1][0] != m):
                seq.append((m, (r["p"] / r["pc"] - 1) * 100 - b[m]))
        for m, d in seq:
            if abs(d) >= 0.1:
                if side is not None and (d > 0) != side:
                    cross.append(f"{m}{'小盘转强' if d > 0 else '大盘转强'}")
                side = d > 0
        if seq:
            now_t = seq[-1][0]
            ago = [d for m, d in seq if m <= f"{int(now_t[:2]) - (1 if int(now_t[3:]) < 30 else 0):02d}:{(int(now_t[3:]) - 30) % 60:02d}"]
            out["背离"] = {"now": round(seq[-1][1], 2), "ago30": round(ago[-1], 2) if ago else None, "cross": cross}
    return out


def text(D, until, reader=None):
    r = build(D, until, reader)
    if not r:
        return "(大小盘路径: 暂无 3 秒指数)"
    L = ["大小盘路径(代码按 3 秒指数逐分钟算; 段编号供引用; 状态只在突破前高 / 跌破前低时才改 = 不在阈值边上来回跳; 末尾的代码标签只给代码用, 判断请看路径本身)"]
    for k in ("大", "小"):
        g = r.get(k)
        if not g:
            continue
        segs = " | ".join(f"[M{k}{i}] {s['from']}-{s['to'] if not s.get('进行中') else '现在'} {'↑' if s['pct'] >= 0 else '↓'}{s['pct']:+.2f}%{'(进行中)' if s.get('进行中') else ''}"
                          for i, s in enumerate(g["segs"], 1))
        log = " → ".join(f"{t} {st}({why})" for t, st, why in g["log"]) or "无(还没走出一段 ≥ 阈值的行情)"
        L.append(f"- {g['name']}({'大盘' if k == '大' else '小盘'}): 现 {g['pct']:+.2f}%(开盘 {g['open']:+.2f}%, 相对开盘 {g['vs_open']:+.2f}%), 区间位置 {g['pos']}%, "
                 f"距今日高 {g['from_hi']:+.2f}% / 距低 {g['from_lo']:+.2f}%" + (f", 近 30 分钟 {g['m30']:+.2f}%" if g["m30"] is not None else "") +
                 f"\n  分段(zigzag 阈值 {g['th']}%): {segs}\n  结构变化: {log}\n  代码标签: {g['tag']}")
    b = r.get("背离")
    if b:
        L.append(f"- 大小盘差(国证2000 − 上证): 现 {b['now']:+.2f} 个百分点" + (f", 30 分钟前 {b['ago30']:+.2f}" if b["ago30"] is not None else "") +
                 f"; 今日穿越: {' '.join(b['cross']) or '无'}")
    return "\n".join(L).replace("09:29", "开盘")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = sys.argv[1:]
    print(text(a[0], a[1] if len(a) > 1 else "15:01:00"))
