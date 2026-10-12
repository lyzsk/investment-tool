# -*- coding: utf-8 -*-
"""ask_claude.py — 微信(hermes/kimi-k3) → Claude Code 交易问答桥(2026-10-11 用户定)

链路: 微信消息 → hermes(kimi) 判定为股票/操盘/挂单/做T 类(或「c:」前缀强制) → 终端调本脚本 → claude -p(跟随 PC1
  默认模型, 现 Opus) 在 investment-tool 目录作答 → stdout 答案原样回微信。「k:」前缀=强制 kimi 自答, 不走本桥。
设计:
- 同一交易日复用同一 Claude 会话(--resume), 追问有上下文; 会话 id 存 scripts/hermes/state/(gitignore)
- 只读: 允许 Read/Grep/Glob/行情快照与日线脚本/WebSearch, 禁写改(微信可能夹带转发文章, 防被文中指令驱动改文件)
- 超时 170s 输出 CLAUDE_TIMEOUT(hermes 侧由 kimi 兜底作答并注明)
- 问答落 scripts/dfcf/snapshots/hermes/claude_relay_<日期>.md(实盘隐私区, 已 gitignore; user 成长线素材)
- 子进程 CREATE_NO_WINDOW(10/8 零弹窗立法)
用法: python scripts/hermes/ask_claude.py "牧原今天能做T吗"  |  --file <问题文件(utf-8)>  |  stdin
"""
import json, os, subprocess, sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "scripts/hermes/state"
LOGDIR = ROOT / "scripts/dfcf/snapshots/hermes"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_EXE = os.path.join(os.environ.get("APPDATA", r"C:\Users\admin\AppData\Roaming"), r"npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe")
CLAUDE = _EXE if os.path.exists(_EXE) else "claude"
TIMEOUT_S = 170

def _claude_json(stdout):
    """10/11: claude -p 经网关时会在 JSON 前打印提示横幅(如 auto mode 计费说明), 只取最后一个 JSON 对象行"""
    for line in reversed((stdout or "").strip().splitlines()):
        if line.lstrip().startswith("{"):
            return json.loads(line)
    return json.loads(stdout or "")

ALLOWED = ("Read,Grep,Glob,WebSearch,"
           "Bash(node scripts/dfcf/paper/snapshot.mjs:*),Bash(node scripts/quotes/kline.mjs:*)")
DENIED = "Edit,Write,NotebookEdit"
SYSTEM = """你是用户的 A 股盘中交易参谋, 通过微信回答(用户在手机上看)。
- 先给结论(做/不做/挂什么价/仓位多少), 再给 2-4 条理由, 全文 ≤500 字, 纯文本, 不用 markdown 表格和标题
- 依据优先级: 实时行情(node scripts/dfcf/paper/snapshot.mjs --codes <代码>) > 当日 md(md/<季度>/<日期>.md 的加红电报/涨停分析) > 导师 skill(skills/<导师>-skill/persona/rules.md, 引用规则写明编号与情境是否满足) > 用户实盘记录(scripts/dfcf/snapshots/)
- 做T/挂单: 参数按该股近 30 日振幅分布定, 禁固定模板; 成本以用户报的数为准
- 拿不准就明说不确定点, 不编数据; 本会话只读, 不修改任何文件"""


def log_qa(q, a, sid):
    LOGDIR.mkdir(parents=True, exist_ok=True)
    f = LOGDIR / f"claude_relay_{datetime.now():%Y-%m-%d}.md"
    with f.open("a", encoding="utf-8") as fp:
        fp.write(f"\n## {datetime.now():%H:%M:%S} (session {sid or '-'})\n**问**: {q}\n\n**答**: {a}\n")


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--file":  # hermes 侧推荐: 原话先写文件, 免命令行引号/换行转义
        q = Path(sys.argv[2]).read_text(encoding="utf-8").strip()
    else:
        q = " ".join(sys.argv[1:]).strip() or sys.stdin.read().strip()
    if q[:2].lower() in ("c:", "c："):
        q = q[2:].strip()
    if not q:
        print("（空问题）")
        return
    STATE.mkdir(parents=True, exist_ok=True)
    sfile = STATE / f"claude_session_{datetime.now():%Y%m%d}.txt"
    sid = sfile.read_text(encoding="utf-8").strip() if sfile.exists() else ""
    cmd = [CLAUDE, "-p", "--output-format", "json", "--allowedTools", ALLOWED, "--disallowedTools", DENIED,
           "--append-system-prompt", SYSTEM] + (["--resume", sid] if sid else []) + [q]
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=TIMEOUT_S, creationflags=NOWIN)
    except subprocess.TimeoutExpired:
        print("CLAUDE_TIMEOUT")
        log_qa(q, "CLAUDE_TIMEOUT", sid)
        return
    try:
        j = _claude_json(r.stdout)
        ans, new_sid = (j.get("result") or "").strip(), j.get("session_id", "")
    except json.JSONDecodeError:
        ans, new_sid = "", ""
    if not ans:  # resume 失效(会话过期)→新开一次
        if sid:
            sfile.unlink(missing_ok=True)
            return main()
        print(f"CLAUDE_ERROR {(r.stderr or r.stdout)[-200:]}")
        return
    if new_sid:
        sfile.write_text(new_sid, encoding="utf-8")
    print(ans)
    log_qa(q, ans, new_sid)


if __name__ == "__main__":
    main()
