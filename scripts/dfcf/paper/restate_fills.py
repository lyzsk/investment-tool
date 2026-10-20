# -*- coding: utf-8 -*-
"""restate_fills.py — 按 10/19 新成交价口径重算某一天的盘中成交(不重跑链、零 token; 10/19 用户定"只重算今天")

新口径(matcher.mjs 10/19 晚已改, 规则文档 §2/§7):
  ①挂单排过队、后来被价格碰到 = 挂价  ②盘前单(time < 09:30, 无 not_before)首次撮合就越价 = 开盘价(不劣于挂价)
  ③盘中新单首次就越价 = 对手价(快照现价近似)  ④挂在涨停价的排板买单当天没摸到涨停 = 不成交
旧口径的问题: 一律按挂价记, 盘前单低开 / 高开时少记; A658 300045 挂涨停 15.24 当天最高 13.7 仍按 15.24 成交。
做法: 只处理该日 why 形如"现价X≤挂Y / 现价X≥挂Y"的撮合成交(开盘卖 / 止损 / 竞价T / 人工导入不动):
      盘前单 → 价改为 better(挂价, 当日开盘价); 排板单没触板 → 撤销成交(挂单改 void, 备注原因);
      盘中单无法知道当时是否"排过队"(旧账本没记 restedAt) → 不动(保守)
      改完按全部成交流水从 10 万重放现金 / 持仓(先校验旧流水能复现当前账本, 复现不了的账本跳过并报出), 再由 matcher --eod --restate 重算当日 nav
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/restate_fills.py --date 2026-10-19 [--dry]
备份: scripts/dfcf/paper/books.bak-restate<日>-<时刻>/(整目录)
"""
import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import a_rules as AR   # noqa: E402

INIT = 100000.0
FEE_RATE, MIN_FEE = 0.00025, 5.0


def fee(side, amt, code, D):
    f = AR.fees(side, amt, code, D, FEE_RATE, MIN_FEE)
    return f["commission"] + f["stamp"]


def replay(trades):
    cash, pos = INIT, {}
    for t in sorted(trades, key=lambda x: str(x["id"])):
        amt = float(t["price"]) * int(t["qty"])
        f = float(t.get("fee") or 0)
        p = pos.setdefault(t["code"], {"qty": 0, "cost": 0.0})
        if t["side"] == "BUY":
            cash -= amt + f
            p["cost"] = (p["cost"] * p["qty"] + amt + f) / (p["qty"] + int(t["qty"]))
            p["qty"] += int(t["qty"])
        else:
            cash += amt - f
            p["qty"] -= int(t["qty"])
            if p["qty"] <= 0:
                pos.pop(t["code"])
    return round(cash, 2), {c: v for c, v in pos.items() if v["qty"] > 0}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    D = a.date
    kd = {}
    for l in (ROOT / "downloads" / "market" / D / "kline_day.jsonl").open(encoding="utf-8"):
        r = json.loads(l)
        kd[r["symbol"][2:]] = r
    books = sorted((HERE / "books").glob("*.json"))
    if not a.dry:
        bak = HERE / f"books.bak-restate{D.replace('-', '')}-{dt.datetime.now():%H%M}"
        shutil.copytree(HERE / "books", bak)
        print(f"备份 → {bak.relative_to(ROOT)}")
    tot_delta, changed = 0.0, []
    for f in books:
        b = json.loads(f.read_text(encoding="utf-8"))
        imp = {str(x.get("id") if isinstance(x, dict) else x) for x in b.get("imported") or []}
        c0, p0 = replay(b["trades"])
        if abs(c0 - float(b["cash"])) > 1 or {k: v["qty"] for k, v in p0.items()} != {k: int(v["qty"]) for k, v in (b.get("positions") or {}).items() if int(v["qty"]) > 0}:
            if any(str(t["id"]).startswith(D) for t in b["trades"]):
                print(f"⚠️ {f.stem}: 流水重放复现不了当前账本(现金 {c0} vs {b['cash']}), 跳过")
            continue
        od = {o["id"]: o for o in b.get("orders") or []}
        keep, notes = [], []
        for t in b["trades"]:
            if not str(t["id"]).startswith(D) or str(t["id"]) in imp:
                keep.append(t)
                continue
            m = re.match(r"现价([\d.]+)([≤≥])挂([\d.]+)", str(t.get("why") or ""))
            o = od.get(t["id"], {})
            k = kd.get(t["code"])
            if not m or not o or not k:
                keep.append(t)
                continue
            cond = o.get("cond") or {}
            pre = str(o.get("time") or "") < "09:30" and not cond.get("not_before")
            up = k.get("limitUp")
            if t["side"] == "BUY" and up and float(o["price"]) >= up - AR.tick(t["code"]) / 2 and float(k["high"]) < up - AR.tick(t["code"]) / 2:
                notes.append(f"撤销 {t['code']} {t['qty']}@{t['price']}(挂涨停 {up} 排板, 当天最高 {k['high']} 没触板)")
                tot_delta += (float(t["price"]) - float(k["close"])) * int(t["qty"]) + float(t.get("fee") or 0)
                if not a.dry:
                    o["status"] = "void"
                    o["note"] = (o.get("note") or "") + f" | 10/19 重算: 排板单当天没触板(最高{k['high']}<涨停{up}), 撤销原成交"
                    o.pop("fillPrice", None)
                continue
            if pre and k.get("open"):
                op = float(k["open"])
                np_ = min(float(o["price"]), op) if t["side"] == "BUY" else max(float(o["price"]), op)
                if abs(np_ - float(t["price"])) > 1e-9:
                    q = int(t["qty"])
                    nf = fee(t["side"], np_ * q, t["code"], D)
                    d = ((float(t["price"]) - np_) * q if t["side"] == "BUY" else (np_ - float(t["price"])) * q) + float(t.get("fee") or 0) - nf
                    tot_delta += d
                    notes.append(f"{'买' if t['side'] == 'BUY' else '卖'} {t['code']} {q}: {t['price']} → 开盘价 {np_}(多记 {d:+.0f} 元)")
                    t = {**t, "price": np_, "fee": round(nf, 2), "why": t["why"] + f" | 10/19 重算: 盘前单按开盘价{np_}"}
                    if not a.dry:
                        o["fillPrice"] = np_
            keep.append(t)
        if not notes:
            continue
        changed.append(f.stem)
        print(f"{f.stem}: " + "; ".join(notes))
        if not a.dry:
            b["trades"] = keep
            b["cash"], pos = replay(keep)
            b["positions"] = {c: {"qty": v["qty"], "cost": round(v["cost"], 4)} for c, v in pos.items()}
            b.setdefault("restated_fills", []).append({"at": dt.datetime.now().isoformat(timespec="seconds"), "date": D, "notes": notes})
            f.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"改了 {len(changed)} 本, 账面合计变化约 {tot_delta:+.0f} 元(正 = 原来少记)")
    if changed and not a.dry:
        r = subprocess.run(["node", str(HERE / "matcher.mjs"), "--eod", "--date", D, "--restate"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=600)
        print("matcher --eod --restate:", (r.stdout or r.stderr)[-400:])


if __name__ == "__main__":
    main()
