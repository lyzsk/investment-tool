# -*- coding: utf-8 -*-
"""session_bench_sdk.py — 承载方式 B: Claude Agent SDK(在 anaconda 跑, 用户 10/22 令)
同 session_bench.py 的 4 轮(材料走第 1 条消息), 一个 ClaudeSDKClient 连着发 4 轮; 记每轮耗时 / 缓存 / 花费 / 会话号
用法: C:/Users/admin/anaconda3/python.exe -X utf8 scripts/test/session_bench_sdk.py
"""
import asyncio
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "test"), str(ROOT / "scripts" / "lib"), str(ROOT / "scripts" / "claude_profile")]
import session_bench as SB   # noqa: E402  复用同一份材料和问题
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage   # noqa: E402


async def main():
    sa = SB.env_args()
    opts = ClaudeAgentOptions(cwd=str(ROOT), disallowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch", "Task"],
                              permission_mode="default", cli_path=SB.CC.claude_exe()[0], settings=sa[1] if len(sa) == 2 else None)
    res = []
    async with ClaudeSDKClient(options=opts) as cl:
        for i, q in enumerate(SB.TURNS):
            if i == 0:
                q = "# 不吃土豆0 全部材料(画像 / 规则 / 案例 / 指纹)" + chr(10) * 2 + SB.MAT + chr(10) * 2 + "---" + chr(10) * 2 + q
            t0 = time.time()
            await cl.query(q)
            j = {}
            async for m in cl.receive_response():
                if isinstance(m, ResultMessage):
                    j = {"usage": m.usage or {}, "total_cost_usd": m.total_cost_usd, "session_id": m.session_id, "result": m.result, "is_error": m.is_error}
            r = SB.row(j, t0)
            res.append(r)
            print("B", i, r, flush=True)
    f = ROOT / "results" / "inv-stock" / "test" / f"session_bench_sdk_{dt.datetime.now():%m%d_%H%M}.json"
    f.write_text(json.dumps({"B": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("->", f)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(main())
