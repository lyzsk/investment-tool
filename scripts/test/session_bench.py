# -*- coding: utf-8 -*-
"""session_bench.py — paper v3 承载方式对比(10/22 晚用户令: A1 vs A2 vs B 先测定下来)
同一份材料(土豆 skill 全文 ≈ 11 万字节, 走 --append-system-prompt-file; 命令行传会超 Windows 长度上限)
4 轮: 第 1 轮"灌料 + 出盘前计划" → 3 轮追问(模拟盘中触发: 只给"变了什么")
  A1 = 一个 claude -p 进程开着, stream-json 输入输出, 4 轮都在这个进程里
  A2 = 第 1 轮 claude -p --session-id <自定 uuid>, 后 3 轮各起一个新进程 --resume <uuid>(第 3 轮前故意什么都不留, 等价于"进程早就退了")
  B  = Claude Agent SDK(anaconda; 装好才测)
每轮记: 耗时 / 缓存读 / 缓存写 / 未缓存输入 / 花费 / 会话号; 结果写 results/inv-stock/test/session_bench_<时刻>.json
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/test/session_bench.py [--only A1|A2]
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "lib"), str(ROOT / "scripts" / "claude_profile")]
import claude_call as CC   # noqa: E402

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
P = ROOT / "skills" / "buchitudou0-skill" / "persona"
MAT = "\n\n".join(f"# {f}\n" + (P / f).read_text(encoding="utf-8") for f in ("profile.md", "rules.md", "cases.md", "fingerprint.md"))
TURNS = [
    "[BOOT 2026-10-22 bench] 你是不吃土豆0 模拟盘的决策会话。上面已经给了他的全部画像 / 规则 / 案例 / 指纹。不要读任何文件。"
    "假设今天是 10/23 盘前: 澳弘转债 111024 昨收 253.92, 正股澳弘电子昨收 67.75。按他的规则给出今天的竞价T 计划(竞价买价 / 数量档 / 开盘卖出条件 / 止损 / 时间止损), 引用规则编号, 300 字以内。",
    "09:22 更新: 正股竞价虚拟价 +2.4%, 转债竞价虚拟价 +1.8%。计划要不要改? 100 字以内。",
    "09:25 撮合: 转债开 258.50, 你的竞价单已成交。09:30:20 转债 261.0。现在怎么做? 80 字以内。",
    "复述你今天第一轮给的竞价买价和引用的规则编号(检验记忆是否连续)。50 字以内。",
]


def env_args():
    rot = CC._rotation()
    return rot.settings_args() if rot else []


def matfile():
    f = Path(tempfile.gettempdir()) / "bench_material.md"
    f.write_text(MAT, encoding="utf-8")
    return f


def row(j, t0):
    u = j.get("usage") or {}
    return {"secs": round(time.time() - t0, 1), "read": u.get("cache_read_input_tokens"), "create": u.get("cache_creation_input_tokens"),
            "input": u.get("input_tokens"), "out": u.get("output_tokens"), "usd": j.get("total_cost_usd"), "sid": j.get("session_id"),
            "is_error": j.get("is_error"), "text": str(j.get("result") or "")[:160]}


def run_a2(mf):
    sid, res = str(uuid.uuid4()), []
    for i, q in enumerate(TURNS):
        args = CC.claude_exe() + ["-p", "--output-format", "json", "--permission-mode", "default", "--disallowedTools", "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Task"] + env_args()
        args += ["--session-id", sid] if i == 0 else ["--resume", sid]
        t0 = time.time()
        q = ("# 不吃土豆0 全部材料(画像 / 规则 / 案例 / 指纹)" + chr(10) * 2 + MAT + chr(10) * 2 + "---" + chr(10) * 2 + q) if i == 0 else q   # 10/22 实测 --append-system-prompt-file 没进上下文 → 材料走第 1 条消息(stdin, 无长度上限)
        p = subprocess.run(args, input=q.encode("utf-8"), capture_output=True, cwd=str(ROOT), creationflags=NOWIN, timeout=600)
        try:
            j = CC.parse_envelope(p.stdout.decode("utf-8", "replace"))
        except Exception:   # noqa: BLE001
            j = {"is_error": True, "result": (p.stderr or p.stdout).decode("utf-8", "replace")[-300:]}
        r = row(j, t0)
        r["sid_same"] = r["sid"] == sid
        res.append(r)
        print("A2", i, r, flush=True)
    return {"sid": sid, "turns": res}


def run_a1(mf):
    sid = str(uuid.uuid4())
    args = CC.claude_exe() + ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose", "--permission-mode", "default",
                              "--disallowedTools", "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Task", "--session-id", sid] + env_args()
    pr = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(ROOT), creationflags=NOWIN)
    res = []
    for i, q in enumerate(TURNS):
        t0 = time.time()
        q = ("# 不吃土豆0 全部材料(画像 / 规则 / 案例 / 指纹)" + chr(10) * 2 + MAT + chr(10) * 2 + "---" + chr(10) * 2 + q) if i == 0 else q
        pr.stdin.write((json.dumps({"type": "user", "message": {"role": "user", "content": q}}, ensure_ascii=False) + "\n").encode("utf-8"))
        pr.stdin.flush()
        j = None
        while True:
            line = pr.stdout.readline()
            if not line:
                break
            try:
                ev = json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                continue
            if ev.get("type") == "result":
                j = ev
                break
        r = row(j or {"is_error": True, "result": pr.stderr.read(500).decode("utf-8", "replace") if not line else "无 result"}, t0)
        r["sid_same"] = r["sid"] == sid
        res.append(r)
        print("A1", i, r, flush=True)
        if not j:
            break
    try:
        pr.stdin.close()
        pr.wait(timeout=30)
    except Exception:   # noqa: BLE001
        pr.kill()
    return {"sid": sid, "turns": res}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    a = ap.parse_args()
    mf = matfile()
    out = {"at": dt.datetime.now().isoformat(timespec="seconds"), "material_bytes": len(MAT.encode())}
    for k, fn in (("A2", run_a2), ("A1", run_a1)):
        if a.only and a.only != k:
            continue
        out[k] = fn(mf)
    f = ROOT / "results" / "inv-stock" / "test" / f"session_bench_{dt.datetime.now():%m%d_%H%M}.json"
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("->", f)


if __name__ == "__main__":
    main()
