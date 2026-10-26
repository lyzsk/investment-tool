# -*- coding: utf-8 -*-
"""cache_ttl_probe.py — 1 小时提示缓存经中转站是否生效(10/23 凌晨彩排发现: 叫醒间隔 > 5 分钟缓存过期, 每次叫醒重写 33 万 token ≈ $1.7)

两个会话同时跑(同材料约 150 KB, 和 v3 一样 cwd 在仓库外 + paper 专用 system prompt + effort high):
  A: 默认(5 分钟缓存)   B: 环境变量 CLAUDE_CODE_PROMPT_CACHE_TTL=1h + ENABLE_PROMPT_CACHING_1H=1
建会话 → 等 WAIT 秒(> 5 分钟) → 两边各 --resume 问一句 → 看续问那轮 cache_read / cache_write
产物: results/inv-stock/test/cache_ttl_probe_<时刻>.json + 打印
"""
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
sys.path[:0] = [str(ROOT / "scripts" / "lib"), str(ROOT / "scripts" / "test")]
import claude_call as CC   # noqa: E402
import v3_concurrency_probe as P   # noqa: E402

WAIT = int(sys.argv[1]) if len(sys.argv) > 1 else 400


def run(args, text, extra_env):
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_MODEL"}
    env.update(extra_env)
    cmd = CC.claude_exe() + ["-p", "--output-format", "json", "--effort", "high", "--disallowedTools", "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Task",
                             "--system-prompt", (ROOT / "scripts" / "paper_line" / "prompt" / "common.md").read_text(encoding="utf-8")] + args
    t0 = time.time()
    p = subprocess.run(cmd, input=text.encode("utf-8"), capture_output=True, cwd=P.CWD, env=env, creationflags=P.NOWIN, timeout=900)
    try:
        r = json.loads(p.stdout.decode("utf-8", "replace"))
    except ValueError:
        return {"err": p.stderr.decode("utf-8", "replace")[-300:], "secs": round(time.time() - t0, 1)}
    u = r.get("usage") or {}
    return {"secs": round(time.time() - t0, 1), "usd_cum": r.get("total_cost_usd"), "cache_read": u.get("cache_read_input_tokens"),
            "cache_write": u.get("cache_creation_input_tokens"), "cache_write_detail": u.get("cache_creation"), "in": u.get("input_tokens"), "out": u.get("output_tokens"),
            "is_error": r.get("is_error")}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    mat = P.material()
    arms = {"A_5m": {}, "B_1h": {"CLAUDE_CODE_PROMPT_CACHE_TTL": "1h", "ENABLE_PROMPT_CACHING_1H": "1"}}
    sid = {k: str(uuid.uuid4()) for k in arms}
    out = {"at": dt.datetime.now().isoformat(timespec="seconds"), "wait": WAIT, "kb": len(mat.encode()) // 1024}
    res = {}

    def boot(k):
        res[k] = {"boot": run(["--session-id", sid[k]], f"[BOOT ttl {k}]\n\n{mat}\n\n---\n\n读完回复「收到」。", arms[k])}
    ths = [threading.Thread(target=boot, args=(k,)) for k in arms]
    [t.start() for t in ths]
    [t.join() for t in ths]
    print(json.dumps(res, ensure_ascii=False), flush=True)
    time.sleep(WAIT)

    def again(k):
        res[k]["resume"] = run(["--resume", sid[k]], "现在 10:30, 一句话说你刚才读的材料里第一个 skill 是什么。", arms[k])
    ths = [threading.Thread(target=again, args=(k,)) for k in arms]
    [t.start() for t in ths]
    [t.join() for t in ths]
    out["arms"] = res
    f = ROOT / "results" / "inv-stock" / "test" / f"cache_ttl_probe_{dt.datetime.now():%m%d_%H%M}.json"
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
