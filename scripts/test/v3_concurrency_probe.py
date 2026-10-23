# -*- coding: utf-8 -*-
"""v3_concurrency_probe.py — paper v3 叫醒队列上限压测(10/23 00:5x 用户令: 并发压测先跑)

问题: 同时起 N 个 claude -p(走同一个中转站)会不会卡死 / 变慢? 定 V3_MAX_INFLIGHT(候选 4 / 6)
做法(和明天真实情况一致: cwd 仓库外 + paper 专用 system prompt + effort high):
  每档 N: ①启动轮: 同时新建 N 个会话, 第 1 条消息带约 60 KB 材料(bank-skill + nasdaq-skill + 资料目录 + 一段 md), 要求写一段市况分析
         ②续问轮: 同时对这 N 个会话 --resume, 问一道中等长度的题(模拟 09:20 竞价复核)
  每次调用用 stream-json 记: 首字时间(第一个 assistant 事件) / 总耗时 / 是否卡死(120 秒没首字) / 报错 / 花费 / 缓存读写
产物: results/inv-stock/test/v3_concurrency_<时刻>.json + 打印汇总表
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/test/v3_concurrency_probe.py [--levels 4,6]
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "lib"), str(ROOT / "scripts" / "paper_v3")]
import claude_call as CC   # noqa: E402

CWD = r"C:\Users\admin\dev\_paper_v3_cwd"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
STALL_S = 120


def material():
    parts = []
    for sk in ("bank", "nasdaq"):
        for f in sorted((ROOT / "skills" / f"{sk}-skill" / "persona").glob("*.md")):
            parts.append(f"# {sk} · {f.name}\n" + f.read_text(encoding="utf-8", errors="replace"))
    parts.append((ROOT / "scripts" / "paper_v3" / "catalog" / "data_catalog.md").read_text(encoding="utf-8"))
    md = sorted((ROOT / "md").glob("2026S4/2026-10-2*.md"))
    if md:
        parts.append(md[-1].read_text(encoding="utf-8", errors="replace")[:30000])
    return "\n\n".join(parts)


def call(args, text, rec):
    t0 = time.time()
    first, res, lines = None, None, []
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_MODEL"}
    cmd = CC.claude_exe() + ["-p", "--output-format", "stream-json", "--verbose", "--effort", "high", "--disallowedTools", "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Task",
                             "--system-prompt", (ROOT / "scripts" / "paper_v3" / "prompt" / "common.md").read_text(encoding="utf-8")] + args
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=CWD, env=env, creationflags=NOWIN)
        p.stdin.write(text.encode("utf-8"))
        p.stdin.close()
        for raw in p.stdout:
            try:
                ev = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if ev.get("type") == "assistant" and first is None:
                first = time.time() - t0
            if ev.get("type") == "result":
                res = ev
        p.wait(timeout=60)
        err = p.stderr.read().decode("utf-8", "replace")[-300:]
    except Exception as e:   # noqa: BLE001
        err = repr(e)[:300]
    u = (res or {}).get("usage") or {}
    rec.update(secs=round(time.time() - t0, 1), first=None if first is None else round(first, 1), stalled=first is None or first > STALL_S,
               ok=bool(res) and not res.get("is_error"), sid=(res or {}).get("session_id"), usd=(res or {}).get("total_cost_usd"),
               cache_read=u.get("cache_read_input_tokens"), cache_write=u.get("cache_creation_input_tokens"), out=u.get("output_tokens"),
               err="" if res and not res.get("is_error") else (str((res or {}).get("result") or err)[:300]))


def burst(n, mk):
    recs = [{} for _ in range(n)]
    ths = [threading.Thread(target=call, args=(*mk(i), recs[i])) for i in range(n)]
    t0 = time.time()
    [t.start() for t in ths]
    [t.join() for t in ths]
    return recs, round(time.time() - t0, 1)


def summ(name, n, recs, wall):
    fs = sorted(r["first"] for r in recs if r.get("first") is not None)
    ss = sorted(r["secs"] for r in recs if r.get("secs") is not None)
    q = lambda xs, p: xs[min(len(xs) - 1, int(len(xs) * p))] if xs else None   # noqa: E731
    return {"轮": name, "并发": n, "成功": sum(1 for r in recs if r.get("ok")), "卡死(>120 秒没首字)": sum(1 for r in recs if r.get("stalled")),
            "首字 中位 / 最慢": (q(fs, .5), fs[-1] if fs else None), "总耗时 中位 / 最慢": (q(ss, .5), ss[-1] if ss else None), "整轮墙钟": wall,
            "花费": round(sum(r.get("usd") or 0 for r in recs), 3), "报错": [r["err"] for r in recs if r.get("err")][:3]}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default="4,6")
    a = ap.parse_args()
    mat = material()
    print(f"材料 {len(mat.encode()) // 1024} KB", flush=True)
    out = {"at": dt.datetime.now().isoformat(timespec="seconds"), "material_kb": len(mat.encode()) // 1024, "levels": {}}
    for n in [int(x) for x in a.levels.split(",")]:
        sids = [str(uuid.uuid4()) for _ in range(n)]
        boot, w1 = burst(n, lambda i: (["--session-id", sids[i]], f"[BOOT 压测 {i}]\n\n{mat}\n\n---\n\n你是中国银行 / 纳指 ETF 的决策 T 会话(压测第 {i} 号)。根据上面材料, 写一段 300 字左右的今日做 T 预案: 先卖后买还是先买后卖、挂价区间、规模档、失效条件, 引用规则编号。"))
        print(json.dumps(summ("启动轮", n, boot, w1), ensure_ascii=False), flush=True)
        res, w2 = burst(n, lambda i: (["--resume", sids[i]], "09:20 更新: 竞价显示中行高开 0.6%, 纳指 ETF 低开 0.4%, 隔夜纳指 −0.8%。预案要不要改? 给出改后的挂单(价 / 量 / 先后顺序), 200 字以内。"))
        print(json.dumps(summ("续问轮", n, res, w2), ensure_ascii=False), flush=True)
        out["levels"][n] = {"boot": boot, "resume": res, "summary": [summ("启动轮", n, boot, w1), summ("续问轮", n, res, w2)]}
        time.sleep(20)
    f = ROOT / "results" / "inv-stock" / "test" / f"v3_concurrency_{dt.datetime.now():%m%d_%H%M}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("->", f)


if __name__ == "__main__":
    main()
