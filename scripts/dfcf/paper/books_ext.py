# -*- coding: utf-8 -*-
"""books_ext.py — 把"不在 matcher 账本里"的账户导出成 report.html 能读的账本格式(10/22 凌晨; 用户: 我是通过 report.html 看的, BL / 导师真人 / 新 paper 要在一处比)

导出到 scripts/dfcf/paper/books_ext/<src>.json(**不进 books/**, matcher 不会碰; report.mjs 读 books/ 找不到时退到这里):
  S-<导师>[@变体]  新 paper 策略执行器影子账: results/_live/<日>/se_<key>/ 的 state.json(成交 / 持仓)+ nav.csv(收盘净值), 按日拼起来
  BL-<导师>        统计基线账户(开盘撮合)    scripts/dfcf/paper/baseline/BL-<导师>.json 原样转(本来就是同一格式)
  BLT-<导师>       统计基线账户(时机版)      scripts/dfcf/paper/baseline/BLT-<导师>.json
同时写 books_ext/accounts.json(src, 显示名, 分组)给 accounts.mjs 读。零 token、只读源数据。
用法: python books_ext.py   (check md 收盘后在基线账户之后调)
"""
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import mentors   # noqa: E402

OUT = HERE / "books_ext"
LIVE = ROOT / "results" / "_live"
BASE = HERE / "baseline"
FOCUS = ["zhiyingjuexin", "xingjianye", "liuyiqing", "antoo", "wudaokongfang", "meiyuelu", "buchitudou0", "lianghuaxiaohao"]


def disp(ledger):
    try:
        return (mentors.get(ledger) or {}).get("display") or ledger
    except Exception:   # noqa: BLE001
        return ledger


_PX = {}


def day_close(D):
    """{6 位代码: 当日收盘价}(downloads/market/<D>/kline_day.jsonl, 零网络)"""
    if D not in _PX:
        f = ROOT / "downloads" / "market" / D / "kline_day.jsonl"
        _PX[D] = {}
        if f.exists():
            for l in f.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(l)
                except ValueError:
                    continue
                if r.get("close"):
                    _PX[D][str(r["symbol"])[2:]] = float(r["close"])
    return _PX[D]


def se_book(key, pre="se", src_pre="S"):
    """pre = 账本目录前缀(se = v2 执行器 / v3 = paper v3); src_pre = report 里的账户前缀(S / V3)"""
    days = sorted({p.parent.parent.name for p in LIVE.glob(f"20*/{pre}_{key}/state.json") if p.parent.parent.name >= "2026-10-22"})
    if not days:
        return None
    nav, trades, last = [], [], None
    for D in days:
        d = LIVE / D / f"{pre}_{key}"
        st = json.loads((d / "state.json").read_text(encoding="utf-8"))
        for i, t in enumerate(st.get("trades") or [], 1):
            trades.append({"id": f"{D}-{src_pre}-{key}-{i:03d}", "side": t["side"], "code": t["code"], "price": t["px"], "qty": t["qty"], "fee": t.get("fee", 0),
                           "why": f"{t.get('t', '')} {t.get('rule', '')} {str(t.get('why') or '')[:80]}"})
        row = None
        if (d / "nav.csv").exists():
            rows = [r for r in csv.reader((d / "nav.csv").read_text(encoding="utf-8").splitlines()) if r and r[0] == D]
            row = rows[-1] if rows else None
        if row:
            cash, nv = float(row[1]), float(row[2])
            nav.append({"date": D, "cash": round(cash, 2), "mv": round(nv - cash, 2), "nav": round(nv, 2)})
        else:   # 10/22 晚用户令: 盘中被停掉的变体(没走到收盘, 无 nav.csv)按当日收盘价补算净值, 标"冻结"
            px = day_close(D)
            mv = sum(int(p_["qty"]) * px.get(c, p_.get("cost") or 0) for c, p_ in (st.get("positions") or {}).items())
            if mv or st.get("cash") is not None:
                nav.append({"date": D, "cash": round(st["cash"], 2), "mv": round(mv, 2), "nav": round(st["cash"] + mv, 2), "frozen": True})
        last = st
    pos = {c: {"qty": int(p["qty"]), "cost": p.get("cost")} for c, p in ((last or {}).get("positions") or {}).items() if int(p.get("qty") or 0) > 0}
    return {"source": f"{src_pre}-{key}", "kind": "se_executor" if pre == "se" else "paper_v3", "cash": (last or {}).get("cash"), "positions": pos, "orders": [], "trades": trades, "nav": nav,
            "note": "新 paper 策略执行器影子账(10/22 起 10 万), 由 books_ext.py 从 results/_live 导出; 不进 matcher"}


def main():
    OUT.mkdir(exist_ok=True)
    acc = []
    keys = sorted({p.name[3:] for p in LIVE.glob("20*/se_*") if p.is_dir() and p.parent.name >= "2026-10-22"})
    for k in keys:
        b = se_book(k)
        if b:
            (OUT / f"S-{k}.json").write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
            sk, _, var = k.partition("@")
            frozen = any(n.get("frozen") for n in b["nav"])
            acc.append([f"S-{k}", f"v2·{disp(sk)}" + (f"@{var}" if var else "") + ("(09:43 停, 收盘价估值)" if frozen else ""), "paper v2(10/22)"])
    # 10/23 凌晨: paper v3 账本(results/_live/<日>/v3_<线>/), 11 本; 决策T 两本本钱 1 万
    try:
        lines = {x["id"]: x for x in json.loads((ROOT / "scripts" / "paper_v3" / "lines.json").read_text(encoding="utf-8"))["lines"]}
    except (OSError, ValueError, KeyError):
        lines = {}
    for k in sorted({p.name[3:] for p in LIVE.glob("20*/v3_*") if p.is_dir() and p.parent.name >= "2026-10-23"}):
        b = se_book(k, "v3", "V3")
        if b:
            (OUT / f"V3-{k}.json").write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
            ln = lines.get(k) or {}
            mode = {"watch": "盯盘", "plan": "计划"}.get(ln.get("mode"), "")
            acc.append([f"V3-{k}", f"v3·{ln.get('name', k)}" + (f"({mode})" if mode else ""), "paper v3(10/23 起)"])
    for pre, lab in (("BL", "基线·开盘"), ("BLT", "基线·时机")):
        for l in FOCUS:
            f = BASE / f"{pre}-{l}.json"
            if f.exists():
                b = json.loads(f.read_text(encoding="utf-8"))
                b["source"] = f"{pre}-{l}"
                (OUT / f"{pre}-{l}.json").write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
                acc.append([f"{pre}-{l}", f"{lab}·{disp(l)}", "统计基线"])
    (OUT / "accounts.json").write_text(json.dumps(acc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"books_ext: {len(acc)} 个账户 → {OUT}")
    for a in acc:
        print(" ", a)


if __name__ == "__main__":
    main()
