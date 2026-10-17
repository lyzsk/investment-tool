# -*- coding: utf-8 -*-
"""up_ops_stats.py — B站三位 UP 的"真人操作"统计(10/16 晚用户指出: UP 有核销/画面 BS 点, 拟人审不该判"无据")
数据: md 各交易日 UP 小节里的「今日操作」(由视频口述 + 抽帧 BS 买卖点/持仓高亮核销后写入, 见 workflows/sum.md), 零 token 正则解析
输出: scripts/bilibili/up_scope.json  {up: {name, days, active_days, ops, buy, sell, per_active_day, time(时段词分布), board(板块分布), recent5[...]}}
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/bilibili/up_ops_stats.py [--days 60] [--asof YYYY-MM-DD]
被 import: up_scope(skill, asof) → dict 或 None(驱动器拟人审用)
"""
import argparse, json, re, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MD = ROOT / "md"
OUT = ROOT / "scripts" / "bilibili" / "up_scope.json"
UPS = {"taoge": ("#### 股市 - 桃哥复盘", "桃哥"), "qushitiange": ("#### 趋势天哥", "趋势天哥"), "lubenyuan": ("#### 卢本圆复盘", "卢本圆")}
BUY = re.compile(r"买|吸|加仓|跟了|跟板|打板|上车|建仓|进场|接")
SELL = re.compile(r"卖|出了|先出|减仓|清仓|走了|止盈|止损|兑现")
TIMEW = [("竞价", r"竞价"), ("开盘", r"开盘|早盘|一开"), ("盘中", r"盘中|上午"), ("午后", r"午后|下午"), ("尾盘", r"尾盘|收盘前|14[:：]5")]
CODE = re.compile(r"[（(](\d{6})[）)]")


def board(c):
    if c.startswith(("688", "689")):
        return "科创板"
    if c.startswith(("300", "301")):
        return "创业板"
    if c.startswith(("4", "8", "92")):
        return "北交所"
    if c.startswith(("11", "12")):
        return "可转债"
    if c.startswith(("5", "15", "16", "18")):
        return "ETF/基金"
    return "沪深主板"


def section(text, head):
    m = re.search(rf"^{re.escape(head)}\s*$", text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    n = re.search(r"^#{1,4} ", rest, re.M)
    return rest[:n.start()] if n else rest


def ops_block(sec):
    """「今日操作」那条顶层 bullet 及其缩进子项"""
    lines, out, on = sec.splitlines(), [], False
    for l in lines:
        if re.match(r"^- \*\*[^*]*今日操作", l):
            on = True
            out.append(l)
            continue
        if on:
            if re.match(r"^- \*\*", l) or re.match(r"^#{1,4} ", l):
                break
            out.append(l)
    return "\n".join(out)


def parse_day(text, head):
    blk = ops_block(section(text, head))
    if not blk:
        return None
    first = blk.splitlines()[0]
    if re.search(r"今日操作[^:：]*[:：]\s*\**\s*无", first) and not CODE.search(blk.split("仓位口径")[0]):
        return {"ops": []}
    ops = []
    items = re.split(r"(?=[①②③④⑤⑥⑦⑧⑨⑩])", blk)
    for it in items:
        m = CODE.search(it)
        if not m or "沉默持仓" in it[:20] or "提及" in it[:10]:
            continue
        head_txt = it[:160]
        side = "买" if BUY.search(head_txt) and not SELL.search(head_txt[:head_txt.find(m.group(0)) + 40]) else ("卖" if SELL.search(head_txt) else None)
        if not side:
            continue
        tw = next((k for k, rx in TIMEW if re.search(rx, head_txt)), None)
        ops.append({"code": m.group(1), "side": side, "time": tw})
    return {"ops": ops}


def build(days=60, asof=None):
    files = sorted(p for p in MD.rglob("20??-??-??.md") if not asof or p.stem < asof)[-days:]
    out = {}
    for up, (head, name) in UPS.items():
        per = []
        for f in files:
            r = parse_day(f.read_text(encoding="utf-8", errors="replace"), head)
            if r is not None:
                per.append((f.stem, r["ops"]))
        if not per:
            continue
        ops = [o for _, x in per for o in x]
        act = [d for d, x in per if x]
        tc = Counter(o["time"] or "未说时段" for o in ops if o["side"] == "买")
        bc = Counter(board(o["code"]) for o in ops if o["side"] == "买")
        nb = sum(1 for o in ops if o["side"] == "买")
        out[up] = {"name": name, "kind": "up_ops", "window": [per[0][0], per[-1][0]], "days": len(per), "active_days": len(act),
                   "ops": len(ops), "buy": nb, "sell": len(ops) - nb, "per_active_day": round(len(ops) / len(act), 2) if act else 0,
                   "time": {k: round(v / max(1, nb), 2) for k, v in tc.most_common()}, "board": {k: round(v / max(1, nb), 2) for k, v in bc.most_common()},
                   "recent5": [{"date": d, "n": len(x), "buy": sum(o["side"] == "买" for o in x)} for d, x in per[-5:]],
                   "source": "md 本人小节「今日操作」(口述+画面 BS 点核销), 正则解析"}
    return out


def up_scope(skill, asof=None):
    try:
        return build(asof=asof).get(skill)
    except Exception:   # noqa: BLE001
        return None


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--asof")
    a = ap.parse_args()
    res = build(a.days, a.asof)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in res.items():
        print(k, {x: v[x] for x in ("window", "days", "active_days", "ops", "buy", "sell", "per_active_day", "time", "board")})
