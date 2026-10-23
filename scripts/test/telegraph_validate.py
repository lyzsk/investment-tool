# -*- coding: utf-8 -*-
"""telegraph_validate.py — 加红电报点名票"怎么用"的持续验证(10/22 13:3x 用户令, 跑到 10/30 周五, 10/31 出结论; TODO ❓3.14)

问题: 10/21 盘中加红电报点名 32 次, 30 次点名时该票当天最高点已出现 → 不进追涨候选。要验证的是两种间接用法:
  ① 正向补涨: 点名票的拓扑邻居(同簇不同子簇)、点名时还没涨的 → 点名后有没有超额
  ② 反向: 点名票杀跌时, 邻居 / 反方向簇怎么走
口径(零 token, 只读):
  - 事件 = 当日 md「## 加红电报」节里 09:30~14:50 的电报, 正文点名的 A 股(security_master STOCK 名称 ≥3 字 或 6 位代码)
  - 价格 = 行情库 kline_minute(只覆盖关注集, 每天约 300~1000 只; 不在库的票记"无分钟数据"不算)
  - 基准 = 上证 sh000001 同窗口; 超额 = 票收益 − 上证收益
  - 窗口 = 点名分钟收盘 → +30 分钟 / +60 分钟 / 当日收盘(午休不算时间, 按交易分钟数)
  - 邻居 = topology.load(code, D, strict=True) 前 5(只用 D 之前的拓扑, 不偷看); 10/19 前没有拓扑文件 → 只算点名票本身
  - "点名时还没涨" = 邻居 开盘→点名分钟 涨幅 < 点名票同期涨幅的一半
  - "已见顶" = 点名分钟之前的日内最高 ≥ 之后的最高
产物: results/inv-stock/test/telegraph/<日>.jsonl(逐事件) + summary.md(累计, 每次重算)
用法: python telegraph_validate.py [--date 2026-10-22] [--since 2026-10-09]    无参数 = 补齐 since 起所有还没算的交易日 + 重出 summary
"""
import argparse
import datetime as dt
import json
import re
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "market")]
OUT = ROOT / "results" / "inv-stock" / "test" / "telegraph"
WIN = (30, 60)


def db():
    import manual_backfill as mb
    c = mb.db()
    c.cursor().execute("use investment_market")
    return c


def md_path(D):
    for p in (ROOT / "md").glob(f"*/{D}.md"):
        return p
    return None


def telegraphs(D):
    p = md_path(D)
    if not p:
        return []
    m = re.search(r"\n## 加红电报\n(.*?)(?:\n## |\Z)", p.read_text(encoding="utf-8", errors="replace"), re.S)
    out = []
    for t, txt in re.findall(r"^- \[(\d{4}-\d\d-\d\d \d\d:\d\d):\d\d\] \[(.*?)\]\(", m.group(1) if m else "", re.M):
        if t[:10] == D and "09:30" <= t[11:16] <= "14:50":
            out.append((t[11:16], txt))
    return out


def names(cur):
    cur.execute("select symbol, code, name from security_master where sec_type='STOCK' and (delist_date is null)")
    by_name, by_code = {}, {}
    for sym, code, nm in cur.fetchall():
        nm = (nm or "").replace(" ", "").replace("*", "")
        by_code[code] = sym
        if len(nm) >= 3 and not nm.startswith("ST"):
            by_name[nm] = sym
    return by_name, by_code


def mentions(txt, by_name, by_code):
    hit = {}
    for nm, sym in by_name.items():
        i = txt.find(nm)
        if i < 0:
            continue
        nxt = txt[i + len(nm): i + len(nm) + 1]
        if len(nm) == 3 and nxt and "一" <= nxt <= "鿿":   # 3 字名后面紧跟汉字 = 多半是词的一部分(10/21 "数字人民币" 误认成"数字人")
            continue
        hit[sym] = nm
    for c in re.findall(r"(?<!\d)([036]\d{5})(?!\d)", txt):
        if c in by_code:
            hit.setdefault(by_code[c], c)
    return hit


TG_MIN = ROOT / "downloads" / "market" / "telegraph_min"   # 10/23: telegraph_backfill.py 用通达信历史分时补的(只有每分钟价格, 高 = 收 = 价)
_TGC = {}


def tg_min(D):
    if D not in _TGC:
        f = TG_MIN / f"{D}.json"
        _TGC[D] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    return _TGC[D]


def bars(cur, D, sym, cache):
    if (D, sym) not in cache:
        cur.execute("select date_format(bar_time,'%%H:%%i'), high, close from kline_minute where trade_date=%s and symbol=%s order by bar_time", (D, sym))
        cache[(D, sym)] = [(t, float(h), float(c)) for t, h, c in cur.fetchall()] or [(t, p, p) for t, p, _ in tg_min(D).get(sym, [])]
    return cache[(D, sym)]


def ret(b, t0, n):
    """点名分钟收盘 → 之后第 n 根(n=None: 收盘) 的收益; 没有该分钟数据返回 None"""
    i = next((k for k, x in enumerate(b) if x[0] >= t0), None)
    if i is None:
        return None
    j = len(b) - 1 if n is None else min(len(b) - 1, i + n)
    return b[j][2] / b[i][2] - 1 if b[i][2] else None


def day_stats(b, t0):
    pre = [x for x in b if x[0] <= t0]
    post = [x for x in b if x[0] > t0]
    if not pre or not post:
        return None, None
    return max(x[1] for x in pre) >= max(x[1] for x in post), pre[-1][2] / b[0][2] - 1


def run_day(cur, D, by_name, by_code):
    import topology as TOPO
    cache, rows = {}, []
    ib = bars(cur, D, "sh000001", cache)
    if not ib:
        return None
    for t0, txt in telegraphs(D):
        for sym, nm in mentions(txt, by_name, by_code).items():
            b = bars(cur, D, sym, cache)
            r = {"D": D, "t": t0, "sym": sym, "name": nm, "text": txt[:120], "has_min": bool(b)}
            if b:
                peaked, up_to = day_stats(b, t0)
                r.update(peaked=peaked, up_to_t=up_to)
                for n in (*WIN, None):
                    k = f"ex_{n or 'close'}"
                    a, i = ret(b, t0, n), ret(ib, t0, n)
                    r[k] = None if a is None or i is None else a - i
                nb = []
                for x in ((TOPO.load(sym[2:], D, strict=True) or {}).get("nb") or [])[:5]:
                    s2 = next((p + x["c"] for p in ("sh", "sz") if bars(cur, D, p + x["c"], cache)), None)
                    if not s2:
                        continue
                    b2 = bars(cur, D, s2, cache)
                    _, u2 = day_stats(b2, t0)
                    e = {"sym": s2, "name": x.get("n"), "up_to_t": u2, "lag": (u2 is not None and up_to is not None and u2 < up_to / 2)}
                    for n in (*WIN, None):
                        a, i = ret(b2, t0, n), ret(ib, t0, n)
                        e[f"ex_{n or 'close'}"] = None if a is None or i is None else a - i
                    nb.append(e)
                r["nb"] = nb
            rows.append(r)
    return rows


def summary():
    R = []
    for f in sorted(OUT.glob("2026-*.jsonl")):
        R += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    days = sorted({r["D"] for r in R})
    has = [r for r in R if r.get("has_min")]

    def agg(xs, lab):
        L = []
        for k in ("ex_30", "ex_60", "ex_close"):
            v = [x[k] for x in xs if x.get(k) is not None]
            L.append(f"{st.median(v) * 100:+.2f}% / 胜 {sum(1 for y in v if y > 0) / len(v):.0%} (n={len(v)})" if v else "-")
        return f"| {lab} | " + " | ".join(L) + " |"
    nb = [e for r in has for e in r.get("nb") or []]
    md = [f"# 加红电报验证 · 累计 {days[0] if days else '-'} ~ {days[-1] if days else '-'}（{len(days)} 个交易日，{dt.datetime.now():%m-%d %H:%M} 重算）", "",
          f"- 点名事件 {len(R)} 次，其中有分钟数据 {len(has)} 次；点名时当日最高已出现 {sum(1 for r in has if r.get('peaked'))} 次",
          "- 超额 = 票收益 − 上证同窗口；格式 = 中位数 / 跑赢上证比例", "",
          "| 组 | 点名后 30 分钟 | 60 分钟 | 到收盘 |", "|---|---|---|---|",
          agg(has, "点名票本身"), agg([r for r in has if r.get("up_to_t") is not None and r["up_to_t"] > 0], "点名票·点名时已涨"),
          agg([r for r in has if r.get("up_to_t") is not None and r["up_to_t"] <= 0], "点名票·点名时未涨/在跌（反向用法看这行）"),
          agg(nb, "拓扑邻居（全部）"), agg([e for e in nb if e.get("lag")], "拓扑邻居·点名时还没涨（正向补涨用法）"),
          agg([e for r in has if r.get("up_to_t") is not None and r["up_to_t"] <= 0 for e in r.get("nb") or []], "点名票在跌时的邻居（反向用法）"), "",
          "## 每日", ""]
    for d in days:
        x = [r for r in has if r["D"] == d]
        md.append(agg(x, f"{d} 点名票 {len(x)}") + "  ")
    md += ["", "不自信点: 分钟线只覆盖关注集(冷门票缺); 10/19 前没有拓扑, 邻居组样本从 10/19 起; 名称匹配可能误认(如电报里出现同名词); 一周样本仍偏少, 结论按中位 + 胜率 + n 一起看"]
    (OUT / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return "\n".join(md)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--since", default="2026-10-09")
    ap.add_argument("--redo", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    con = db()
    cur = con.cursor()
    by_name, by_code = names(cur)
    cur.execute("select distinct trade_date from kline_minute where trade_date >= %s and symbol='sh000001' order by trade_date", (a.since,))
    days = sorted({str(x[0]) for x in cur.fetchall()} | {f.stem for f in TG_MIN.glob("*.json") if f.stem >= a.since})   # 10/23: 加上回补缓存里的历史日
    if a.date:
        days = [a.date]
    for D in days:
        f = OUT / f"{D}.jsonl"
        if f.exists() and not a.redo and not a.date:
            continue
        rows = run_day(cur, D, by_name, by_code)
        if rows is None:
            print(D, "没有上证分钟线, 跳过")
            continue
        f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(D, "点名", len(rows), "有分钟", sum(1 for r in rows if r.get("has_min")))
    print(summary())


if __name__ == "__main__":
    main()
