# -*- coding: utf-8 -*-
"""按需决策检索：必要数据代码强制查询并留痕；额外数据只走 ./q，不设固定KB上限。"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
Q = ROOT / "scripts" / "paper_line" / "q.py"
PY = ROOT / "scripts" / "venv" / "Scripts" / "python.exe"
PYTHON = PY if PY.exists() else Path(sys.executable)


def required_queries(skill, code, name, day, at, pattern="普通"):
    queries = [
        ("levels", "关键价位与退出路径", ["levels", code, day, "-", at]),
        ("peers", "同题材/同逻辑/梯队拓扑", ["peers", code, day]),
        ("themeof", "个股题材及生命周期", ["themeof", name or code, day]),
        ("cases", "指定导师同票正负案例", ["cases", skill, code, day]),
        ("events", "当日事件与关联", ["events", code, day]),
        ("pattern", "近期形态与后续分布", ["pattern", code, day, "10"]),
    ]
    if code.startswith(("11", "12")):
        queries += [("cbpath", "转债自身历史路径", ["cbpath", code, day, "10"]),
                    ("similar", "转债相似日与退出分布", ["similar", code, day])]
    if pattern in ("趋势", "转强候选", "普通"):
        queries += [("themetop", "市场题材总览(非只连板)", ["themetop", day])]
    return [{"id": qid, "why": why, "args": args, "required": True} for qid, why, args in queries]


def deferred_queries(code, day):
    """慢版必查的重计算；不阻塞 fast，也不因超时伪称无数据。"""
    return [] if code.startswith(("11", "12")) else [{"id": "window", "why": "股票相似窗口(含趋势中军)",
                                                     "args": ["window", code, day, "stock", "10"], "required": True, "stage": "slow"}]


def run_query(q, timeout=None):
    cmd = [str(PYTHON), "-X", "utf8", str(Q), *q["args"]]
    timeout = timeout or (120 if q["id"] in ("window", "wminute") else 45)
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        text = p.stdout.decode("utf-8", "replace")
        err = p.stderr.decode("utf-8", "replace")
        ok = p.returncode == 0 and bool(text.strip()) and not text.lstrip().startswith('{"err"')
        return {"ok": ok, "text": text, "error": "" if ok else (err or text or f"rc={p.returncode}")}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "text": "", "error": f"{type(e).__name__}: {e}"}


def retrieve(skill, code, name, day, at, pattern="普通", query_runner=run_query):
    rows, missing = [], []
    for q in required_queries(skill, code, name, day, at, pattern):
        r = query_runner(q)
        text = r["text"]
        row = {**q, "ok": r["ok"], "bytes": len(text.encode("utf-8")), "sha1": hashlib.sha1(text.encode("utf-8")).hexdigest(),
               "text": text, "error": r["error"]}
        rows.append(row)
        if not r["ok"]:
            missing.append({"query": q["id"], "why": q["why"], "error": r["error"]})
    return {"required": rows, "missing": missing, "deferred": deferred_queries(code, day),
            "policy": "必要查询必须执行；缺失显式列出；额外数据仅允许 ./q 只读命名查询，不按KB截断",
            "coverage": {"required": len(rows), "ok": len(rows) - len(missing), "missing": len(missing)}}


def retrieve_deferred(pack, query_runner=run_query):
    """slow 阶段补重计算，结果仍带 ok/error；缺失败只写 missing_slow。"""
    retrieval = pack["retrieval"]
    for q in retrieval.get("deferred") or []:
        if any(x["id"] == q["id"] for x in retrieval["required"]):
            continue
        r = query_runner(q)
        text = r["text"]
        retrieval["required"].append({**q, "ok": r["ok"], "bytes": len(text.encode("utf-8")), "sha1": hashlib.sha1(text.encode("utf-8")).hexdigest(),
                                      "text": text, "error": r["error"]})
        if not r["ok"]:
            retrieval.setdefault("missing_slow", []).append({"query": q["id"], "why": q["why"], "error": r["error"]})
    return retrieval


def focus01(text, code):
    """保留01市场/盘口事实，但候选表只留当前标的；其他股票由peers等命名查询按需展开。"""
    lines, out, in_pool = text.splitlines(), [], False
    for line in lines:
        if line.startswith("## 候选池"):
            in_pool = True
            out.append(line)
            continue
        if in_pool and line.startswith("## "):
            in_pool = False
        if in_pool:
            if line.startswith("| 行 |") or line.startswith("|---") or re_match_code(line, code):
                out.append(line)
            continue
        if line.startswith("## 上一版") or line.startswith("## 今日事实包"):
            break
        out.append(line)
    return "\n".join(out)


def re_match_code(line, code):
    return line.startswith("|") and f"| {code} |" in line
