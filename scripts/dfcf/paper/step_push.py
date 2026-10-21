# -*- coding: utf-8 -*-
"""step_push.py — 盯盘链逐步推导推微信(10/21 用户令: 选一条在跑的 paper, 全链路每一步推导发微信, 用户人工审核判异常)

做什么: 盯 results/<skill>_chain/live-<日>/ 顶层各步产物(02/03/04/05/06/盲审), 某步写完(contract 能解析且 20 秒没再改)就把这一步的
        要点(市况/态度/候选/批否/动作/盲审结论)排成一条推微信; 同一步被回炉重写=再推一次并标"重写"。不调模型、不改任何产物。
产物: results/_shadow/<日>/step_push_<skill>.json(已推版本, 防重推)
用法: python step_push.py --skill meiyuelu [--until 1505] [--dry]
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
STEPS = [("02", "02_analysis.md", "02 市况/态度"), ("03b", "03_debate_bull.md", "03 多方"), ("03s", "03_debate_bear.md", "03 空方"),
         ("03j", "03_debate.md", "03 裁判"), ("04", "04_plan.md", "04 候选/计划"), ("05", "05_risk.md", "05 风控批否"),
         ("06", "06_verdict.md", "06 动作"), ("blind", "validate_report.md", "盲审")]


def contract(text):
    b = re.findall(r"```contract\s*\n([\s\S]*?)```", text)
    try:
        return json.loads(b[-1]) if b else None
    except ValueError:
        return None


def cut(s, n):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n] + "…"


def render(step, c, text):
    L = []
    if step == "02":
        L.append(f"市况={c.get('market_state')} 态度={c.get('stance')} 领先层={cut(c.get('leading_layer'), 60)}")
        for d in c.get("directions") or []:
            L.append(f"· 方向: {cut(d, 90)}")
        o = c.get("outlook") or {}
        if o:
            L.append(f"展望 {o.get('horizon_days')}天 {o.get('view')}: {cut(o.get('thesis'), 160)}")
            L.append(f"失效: {cut(o.get('invalid_if'), 140)}")
        ev = c.get("evidence")
        if ev:
            L.append(f"因子: {cut(json.dumps(ev, ensure_ascii=False), 200)}")
    elif step == "04":
        for x in c.get("candidates") or []:
            L.append(f"· {x.get('name')}({x.get('code')}) [{x.get('group')}/{x.get('conf')}] 触发: {cut(x.get('trigger'), 110)} | 仓: {cut(x.get('pos'), 50)} | 因: {cut(x.get('why'), 90)}")
        if not L:
            L.append(cut(json.dumps(c, ensure_ascii=False), 500))
    elif step == "05":
        for v in c.get("verdicts") or []:
            L.append(f"· {v.get('name')}: {v.get('result')} — {cut(v.get('reason'), 140)}")
        for p in (c.get("portfolio") or [])[:3]:
            L.append(f"组合: {cut(p, 100)}")
    elif step == "06":
        if c.get("supersedes"):
            L.append(f"改了啥: {cut(c.get('supersedes'), 200)}")
        for a in c.get("actions") or []:
            L.append("· 动作: " + cut(" ".join(f"{k}={v}" for k, v in a.items() if k not in ("why",) and v not in (None, "")), 160) + f" | 因: {cut(a.get('why'), 90)}")
        for h in c.get("holds") or []:
            L.append(f"· 维持 {h.get('order_id') or h.get('code')}: {cut(h.get('why'), 100)}")
        if c.get("no_trade_reason"):
            L.append(f"不交易: {cut(c.get('no_trade_reason'), 140)}")
    elif step == "blind":
        m = re.search(r"(PASS|FAIL)[^\n]*", text)
        L.append(cut(m.group(0) if m else text[-300:], 300))
    else:   # 03 多/空/裁判: 字段各链不一, 原样压缩
        L.append(cut(json.dumps(c, ensure_ascii=False), 600))
    return "\n".join(L)


def push(msg, src, dry):
    cmd = [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "hermes" / "wx_send.py"), msg, "--raw", "--src", src] + (["--dry"] if dry else [])
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
    return (r.stdout or r.stderr or "").strip()[-80:]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--date", default=dt.date.today().strftime("%Y%m%d"))
    ap.add_argument("--until", default="1505")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--once", action="store_true", help="扫一遍就退(自测用)")
    a = ap.parse_args()
    rd = ROOT / "results" / f"{a.skill}_chain" / f"live-{a.date}"
    D = f"{a.date[:4]}-{a.date[4:6]}-{a.date[6:]}"
    sf = ROOT / "results" / "_shadow" / D / f"step_push_{a.skill}{'_dry' if a.dry else ''}.json"
    sf.parent.mkdir(parents=True, exist_ok=True)
    seen = json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else {}
    while True:
        for step, name, label in STEPS:
            f = rd / name
            if not f.exists():
                continue
            mt = f.stat().st_mtime
            if time.time() - mt < 20 or seen.get(name, {}).get("mt") == mt:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            c = contract(text) if step != "blind" else {}
            if c is None:
                continue   # 还没写完 / 回炉中
            n = seen.get(name, {}).get("n", 0) + 1
            hm = dt.datetime.fromtimestamp(mt).strftime("%H:%M")
            msg = f"【{a.skill} {label} {hm}{' 重写#' + str(n) if n > 1 else ''}】\n" + render(step, c, text)
            out = push(msg[:1500], f"step_{a.skill}", a.dry)
            print(f"[{dt.datetime.now():%H:%M:%S}] {name} n={n} {len(msg)}字 → {out}", flush=True)
            seen[name] = {"mt": mt, "n": n}
            sf.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
        if a.once or dt.datetime.now().strftime("%H%M") >= a.until:
            break
        time.sleep(15)


if __name__ == "__main__":
    main()
