# -*- coding: utf-8 -*-
"""cb_auction_features.py — 转债集合竞价过程特征(10/22 用户令: 现在就开始攒, 每天自动跑; TODO 4.4)

数据: downloads/market/<日>/call_auction_open_raw.jsonl(collect_auction, 新浪全市场竞价快照约 15 秒一张; 全市场转债 10/20 起, 10/12~10/19 只有关注的 4~17 只)
      竞价段新浪字段: [2]=昨收 [10]=买一量(=匹配量) [11]=买一价(=虚拟撮合价) [12]=买二量(=未匹配买) [22]=卖二量(=未匹配卖) [31]=时间; 09:25 后 [1]=开盘价
每只转债(及其正股, 映射来自 cb meta RPT_BOND_CB_LIST)一行特征:
  p0915 / p0920 / p0923 / p_last(09:25 前最后一张) / open(09:25 撮合) 相对昨收的涨跌%(同字段加 _pct)
  path_red   = 竞价期间虚拟价高于昨收的快照占比          path_n = 快照张数
  late_dir   = 09:23 → 撮合 的涨跌(百分点, 最后 2 分钟方向)    pre20_vs_post20 = 09:20 后(不可撤单)相对 09:20 前的价差
  matched_growth = 撮合匹配量 / 09:20 那张的匹配量            unm_buy / unm_sell / unm_ratio = 撮合前最后一张的未匹配买 / 卖 / 买卖比
  from_limit = 09:15 起点是否在涨跌停附近(±9.5% 股票 / ±20% 内转债不判)
  stock_sync = 转债与正股虚拟价逐张同向变动的比例(0~1; 0.5 ≈ 不相关, 低 = 背离)
产物: downloads/market/<日>/cb_auction_features.jsonl(每天一个文件, 幂等重写)
用法: python cb_auction_features.py [--date 2026-10-22] [--since 2026-10-12]   无参数 = 今天(09:26 后跑); --since = 回补
"""
import argparse
import datetime as dt
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"


def cb_map():
    fs = sorted(glob.glob(str(ROOT / "downloads" / "quotes" / "cb" / "meta" / "RPT_BOND_CB_LIST_all_*.json")))
    if not fs:
        return {}
    m = json.loads(Path(fs[-1]).read_text(encoding="utf-8"))
    rows = m if isinstance(m, list) else ((m.get("result") or {}).get("data") or m.get("data") or [])
    return {str(r.get("SECURITY_CODE")): (str(r.get("CONVERT_STOCK_CODE") or ""), r.get("SECURITY_NAME_ABBR")) for r in rows}


def series(D):
    """{6 位代码: [(HH:MM:SS, 虚拟价, 匹配量, 未匹配买, 未匹配卖, 昨收, 开盘价)]}"""
    out = {}
    f = MKT / D / "call_auction_open_raw.jsonl"
    if not f.exists():
        return out
    for l in f.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(l)
        except ValueError:
            continue
        x = r.get("fields") or []
        if len(x) < 32:
            continue
        try:
            row = (x[31], float(x[11] or 0), float(x[10] or 0), float(x[12] or 0), float(x[22] or 0), float(x[2] or 0), float(x[1] or 0))
        except ValueError:
            continue
        out.setdefault(str(r.get("symbol", ""))[2:], []).append(row)
    for k in out:
        out[k].sort()
    return out


def feats(rows):
    pc = next((r[5] for r in rows if r[5]), 0)
    if not pc:
        return None
    pre = [r for r in rows if "09:15:00" <= r[0] < "09:25:00" and r[1] > 0]
    op = next((r[6] for r in rows if r[0] >= "09:25:00" and r[6] > 0), None)
    if not pre and not op:
        return None
    pct = lambda p: round((p / pc - 1) * 100, 3) if p else None   # noqa: E731
    at = lambda t: next((r for r in reversed(pre) if r[0] <= t), None)   # noqa: E731
    r15, r20, r23, rl = (pre[0] if pre else None), at("09:20:00"), at("09:23:00"), (pre[-1] if pre else None)
    post20 = [r[1] for r in pre if r[0] >= "09:20:00"]
    pre20 = [r[1] for r in pre if r[0] < "09:20:00"]
    return {
        "prev": pc, "p0915_pct": pct(r15 and r15[1]), "p0920_pct": pct(r20 and r20[1]), "p0923_pct": pct(r23 and r23[1]),
        "p_last_pct": pct(rl and rl[1]), "open": op, "open_pct": pct(op),
        "path_n": len(pre), "path_red": round(sum(1 for r in pre if r[1] > pc) / len(pre), 3) if pre else None,
        "late_dir": (round(pct(op) - pct(r23[1]), 3) if op and r23 else None),
        "pre20_vs_post20": (round((sum(post20) / len(post20)) / (sum(pre20) / len(pre20)) * 100 - 100, 3) if post20 and pre20 else None),
        "matched_growth": (round(rl[2] / r20[2], 2) if rl and r20 and r20[2] else None),
        "unm_buy": rl and rl[3], "unm_sell": rl and rl[4], "unm_ratio": (round(rl[3] / rl[4], 2) if rl and rl[4] else None),
        "_path": [(r[0], r[1]) for r in pre],
    }


def sync(a, b):
    """两条虚拟价路径按时间对齐后逐张同向变动的比例"""
    slot = lambda t: t[:6] + str(int(t[6:8]) // 15)   # noqa: E731  两边快照不在同一秒(新浪逐只返回), 按 15 秒槽对齐
    tb = {slot(t): p for t, p in b}
    pairs = [(p, tb.get(slot(t))) for t, p in a if tb.get(slot(t))]
    ch = [(x1 - x0, y1 - y0) for (x0, y0), (x1, y1) in zip(pairs, pairs[1:]) if (x1 - x0) and (y1 - y0)]
    return round(sum(1 for dx, dy in ch if dx * dy > 0) / len(ch), 3) if len(ch) >= 5 else None


def run(D):
    S, M = series(D), cb_map()
    out = []
    for code, rows in S.items():
        if code[:2] not in ("11", "12"):
            continue
        f = feats(rows)
        if not f:
            continue
        stk, name = M.get(code, ("", None))
        g = feats(S.get(stk) or []) if stk else None
        rec = {"D": D, "code": code, "name": name, "stock": stk, **{k: v for k, v in f.items() if k != "_path"}}
        if g:
            rec.update({f"stk_{k}": v for k, v in g.items() if k in ("p0915_pct", "p0920_pct", "p_last_pct", "open_pct", "path_red", "late_dir")})
            rec["stk_from_limit"] = bool(g.get("p0915_pct") is not None and abs(g["p0915_pct"]) >= 9.5)
            rec["stock_sync"] = sync(f["_path"], g["_path"])
        out.append(rec)
    if out:
        (MKT / D / "cb_auction_features.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--since")
    a = ap.parse_args()
    days = sorted(p.parent.name for p in MKT.glob("2026-*/call_auction_open_raw.jsonl") if p.parent.name >= a.since) if a.since else [a.date]
    for D in days:
        r = run(D)
        aw = next((x for x in r if x["code"] == "111024"), None)
        print(D, "转债", len(r), "有正股", sum(1 for x in r if x.get("stk_open_pct") is not None),
              "| 澳弘:", {k: aw.get(k) for k in ("p0915_pct", "p0920_pct", "p_last_pct", "open_pct", "late_dir", "path_red", "stk_open_pct", "stock_sync")} if aw else "-")


if __name__ == "__main__":
    main()
