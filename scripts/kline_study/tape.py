# -*- coding: utf-8 -*-
"""tape.py — 买卖腿 × 3 秒盘口(10/24 用户: 实盘买卖腿和 3 秒数据好好和图关联起来学)

数据:
  3 秒盘口 downloads/market/<日>/book_snap.jsonl(.gz)(collect_book, 一行 = 一只票一个快照: t 时刻 / p 现价 / v 累计量 / a 累计额 / b 买五档 / k 卖五档; 竞价段 买一=卖一=撮合价, 买二量=未匹配买)
  导师逐笔 tzzb_record bs_leg(只到分钟)· 用户实盘成交 scripts/dfcf/snapshots/<日>_成交_*.txt(秒; 隐私, 结果只写 snapshots/kline_cases/)
每一腿的盘口上下文(leg_ctx):
  成交前: 现价 / 买一卖一及量 / 五档买卖比(买五档总量 ÷ 卖五档总量)/ 相对当时均价(a ÷ v)/ 离涨跌停 / 前 60 秒、前 3 分钟涨跌 / 前 60 秒成交量是全天 3 秒均量的几倍 / 在当时为止日内高低区间的位置
  成交后: 5 / 15 / 30 分钟内最高、最低, 收盘(都相对成交价 %)—— 买得好不好、卖得好不好一眼能看
涨停过程(seal_story): 首次封板秒级时刻、每次开板(起止 / 最低砸到哪 / 开了几秒)、封单额(涨停价买一量 × 价)随时间: 首封时 / 最大 / 收盘
用法: python tape.py <代码> <日>   (打印涨停过程 + 当天全部导师 / 用户腿的盘口上下文)
"""
import bisect
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"
SNAP = ROOT / "scripts" / "dfcf" / "snapshots"
_B = {}


def sym(code):
    return ("sh" if code.startswith(("6", "9", "11", "5")) else "sz") + code


def book(code, D):
    """→ [(秒数, t, p, v, a, b, k)] 按时间排序; 没有 → []"""
    key = (code, D)
    if key in _B:
        return _B[key]
    s = sym(code)
    f, g = MKT / D / "book_snap.jsonl.gz", MKT / D / "book_snap.jsonl"
    rows = []
    if f.exists() or g.exists():
        fh = gzip.open(f, "rt", encoding="utf-8") if f.exists() else g.open(encoding="utf-8")
        with fh:
            for l in fh:
                if s not in l[:20]:
                    continue
                j = json.loads(l)
                if j.get("s") != s or not j.get("p"):
                    continue
                h, m, sec = (int(x) for x in j["t"][:8].split(":"))
                rows.append((h * 3600 + m * 60 + sec, j["t"][:8], float(j["p"]), float(j.get("v") or 0), float(j.get("a") or 0), j.get("b") or [], j.get("k") or []))
    rows.sort()
    _B[key] = rows
    return rows


def secs(hms):
    p = [int(x) for x in hms.split(":")] + [0, 0]
    return p[0] * 3600 + p[1] * 60 + p[2]


def leg_ctx(code, D, hms, px, side, up=None, dn=None):
    """一腿的 3 秒盘口上下文; hms 只到分钟的(导师)按该分钟末尾对齐"""
    B = book(code, D)
    if not B:
        return {"盘口": "当天没有 3 秒盘口"}
    t = secs(hms) + (59 if len(hms) <= 5 else 0)
    cont = [r for r in B if r[0] >= 34200]   # 09:30 后连续竞价
    i = bisect.bisect_right([r[0] for r in B], t) - 1
    if i < 0:
        return {"盘口": f"{hms} 之前没有快照"}
    r = B[i]
    _, tt, p, v, a, b, k = r
    bv = sum(int(x[1] or 0) for x in b[:5])
    kv = sum(int(x[1] or 0) for x in k[:5])
    o = {"快照": tt, "现价": p, "买一": b[0] if b else None, "卖一": k[0] if k else None, "五档买/卖比": round(bv / kv, 2) if kv else ("卖盘空(封涨停)" if bv else None)}
    if v:
        o["相对当时均价%"] = round((px / (a / v) - 1) * 100, 2) if a / v > 0 else None
    if up:
        o["离涨停%"] = round((up / px - 1) * 100, 2)
    if dn:
        o["离跌停%"] = round((px / dn - 1) * 100, 2)

    def back(sec):
        j = bisect.bisect_right([x[0] for x in B], t - sec) - 1
        return B[j] if j >= 0 else None
    for nm, sec in (("前60秒涨跌%", 60), ("前3分钟涨跌%", 180)):
        r0 = back(sec)
        if r0 and r0[2]:
            o[nm] = round((p / r0[2] - 1) * 100, 2)
    r0 = back(60)
    if r0 and cont:
        tot = cont[-1][3] - cont[0][3]
        per3 = tot / max(1, (cont[-1][0] - cont[0][0]) / 3)
        o["前60秒量/全天3秒均量"] = round((v - r0[3]) / 20 / per3, 2) if per3 else None
    seen = [x[2] for x in B[:i + 1] if x[0] >= 34200] or [p]
    hi_, lo_ = max(seen), min(seen)
    o["在当时日内区间位置%"] = round((px - lo_) / (hi_ - lo_) * 100) if hi_ > lo_ else None
    for nm, sec in (("5分钟", 300), ("15分钟", 900), ("30分钟", 1800)):
        fut = [x[2] for x in B[i + 1:] if x[0] <= t + sec]
        if fut:
            o[f"之后{nm}最高%"] = round((max(fut) / px - 1) * 100, 2)
            o[f"之后{nm}最低%"] = round((min(fut) / px - 1) * 100, 2)
    o["收盘相对成交价%"] = round((B[-1][2] / px - 1) * 100, 2)
    good = (o["收盘相对成交价%"] >= 0) == (side == "买")
    o["当天看买卖对不对"] = "对" if good else "错"
    return o


def seal_story(code, D, up):
    """涨停过程(秒级): 首封 / 每次开板 / 封单额"""
    B = [r for r in book(code, D) if 34200 <= r[0] < 53820]   # 09:30 ~ 14:57 连续竞价(14:57 后收盘集合竞价卖一不空, 会被误判成开板)
    if not B or not up:
        return None
    sealed = lambda r: r[2] >= up - 0.005 and not (r[6] and float(r[6][0][0] or 0) > 0 and int(r[6][0][1] or 0) > 0)   # noqa: E731  价在涨停且卖一空
    fa = lambda r: (int(r[5][0][1] or 0) * up / 1e4) if r[5] and abs(float(r[5][0][0] or 0) - up) < 0.006 else 0   # noqa: E731  封单额(万元; 量单位按股)
    first, opens, cur = None, [], None
    amts = []
    for r in B:
        s = sealed(r)
        if s and first is None:
            first = r[1]
        if first and not s and cur is None:
            cur = {"开": r[1], "最低": r[2]}
        elif cur is not None:
            if s:
                cur["回封"] = r[1]
                cur["开了秒"] = secs(r[1]) - secs(cur["开"])
                cur["砸到%"] = round((cur["最低"] / up - 1) * 100, 2)
                opens.append(cur)
                cur = None
            else:
                cur["最低"] = min(cur["最低"], r[2])
        if s:
            amts.append((r[1], fa(r)))
    if cur is not None:
        cur["回封"] = None
        cur["砸到%"] = round((cur["最低"] / up - 1) * 100, 2)
        opens.append(cur)
    out = {"首封(秒)": first, "开板": opens, "开板次数": len(opens), "14:57 时封住": bool(B and sealed(B[-1]))}
    if amts:
        out["封单额(万) 首封时 / 最大 / 收盘"] = [round(amts[0][1]), round(max(a for _, a in amts)), round(fa(B[-1]))]
        out["最大封单时刻"] = max(amts, key=lambda x: x[1])[0]
    return out


def user_legs(code, d0, d1):
    """用户实盘成交(隐私): snapshots/<日>_成交_*.txt 里这只票的成交行 → [(日, 时刻, 方向, 价, 数量)]"""
    out = []
    for f in sorted(SNAP.glob("20*_成交_*.txt")):
        d = f.name[:10]
        if not (d0 <= d <= d1):
            continue
        for l in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^(\d\d:\d\d:\d\d)(?:~\d\d)?\s+(\d{6})\s+\S+\s+(买|卖)\s+([\d/]+)(?:\(=(\d+)\))?\s+([\d.]+)", l.strip())
            if m and m.group(2) == code:
                q = int(m.group(5) or sum(int(x) for x in m.group(4).split("/")))
                out.append((d, m.group(1), m.group(3), float(m.group(6)), q))
    return out


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    code, D = sys.argv[1], sys.argv[2]
    sys.path[:0] = [str(Path(__file__).resolve().parent)]
    import intake as I
    F = I.facts(code, D)
    print("事实", {k: F.get(k) for k in ("涨跌%", "板型", "连板", "首次封板", "开板次数(分钟级)")})
    print("涨停过程(3秒)", json.dumps(seal_story(code, D, F["涨停价"]), ensure_ascii=False))
    for e in I.mentor_legs(code, D):
        if e["日"] == D:
            print("导师", e["导师"], e["时"], e["方向"], e["价"], json.dumps(leg_ctx(code, D, e["时"], e["价"], e["方向"], F["涨停价"], F["跌停价"]), ensure_ascii=False))
    for d, t, s, px, q in user_legs(code, D, D):
        print("用户", t, s, px, json.dumps(leg_ctx(code, D, t, px, s, F["涨停价"], F["跌停价"]), ensure_ascii=False))
