# -*- coding: utf-8 -*-
"""live v2 单会话：每天首轮 --session-id，之后仅 --resume；不加载导师 skill。"""
import datetime as dt
import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import claude_call as CC  # noqa: E402

CWD = Path(r"C:\Users\admin\dev\_live_v2_cwd")
NO_TOOLS = ["Read", "Grep", "Glob", "Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Agent"]
SYSTEM = """你是 live v2 的盘中复核器，不扮演任何导师，不调用任何 skill。
只能使用用户消息里的事件包，不得自行读取文件或联网。你不执行交易、不生成自动订单。
必须基于事件、当时可见情境和证据给出明确复核，包括方向、机械执行边界、证据、置信度、失效条件和下一检查点。
证据不足也要说明缺什么以及下一步检查什么，禁止只说无法判断。输出一个 JSON 代码块，不要其他正文。"""
SCHEMA = {"type": "object", "required": ["stance", "action", "evidence", "confidence", "invalid_if", "next_check"],
          "properties": {"stance": {"type": "string", "minLength": 1}, "action": {"type": "string", "minLength": 1},
                         "evidence": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                         "confidence": {"type": "object", "required": ["raw"], "properties": {"raw": {"type": "string"}, "n": {"type": "integer"}, "reason": {"type": "string"}}},
                         "invalid_if": {"type": "string", "minLength": 1}, "next_check": {"type": "string", "minLength": 1}}}


class V2Session:
    def __init__(self, day, out_dir, call_fn=CC.call, system=SYSTEM, tag="live-v2", schema=SCHEMA,
                 allowed_tools=None, disallowed_tools=NO_TOOLS):
        self.day, self.dir, self.call_fn = day, Path(out_dir), call_fn
        self.system, self.tag, self.schema = system, tag, schema
        self.allowed_tools, self.disallowed_tools = allowed_tools, disallowed_tools
        self.path = self.dir / "session.json"
        try:
            self.st = json.loads(self.path.read_text(encoding="utf-8"))
            if self.st.get("date") != day:
                raise ValueError("隔日会话禁止 resume")
        except (OSError, ValueError):
            self.st = {"date": day, "sid": "", "cost_cum": 0.0, "turns": []}

    def save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.st, ensure_ascii=False, indent=1), encoding="utf-8")

    def ask(self, prompt, sig, timeout_s=None, effort=None, fork_from=None, parent_cost=0.0):
        boot = not self.st.get("sid")
        if boot:
            self.st["sid"] = str(uuid.uuid4())
            self.st["boot_at"] = dt.datetime.now().isoformat(timespec="seconds")
            self.save()
        sid = self.st["sid"]
        if fork_from:
            extra, resume = ["--fork-session"], fork_from
        else:
            extra, resume = (["--session-id", sid] if boot else []), (None if boot else sid)
        if effort:
            extra += ["--effort", effort]
        CWD.mkdir(parents=True, exist_ok=True)
        if self.allowed_tools and any(x.startswith("Bash(./q") for x in self.allowed_tools):
            src = Path(r"C:\Users\admin\dev\_paper_line_cwd\q")
            dst = CWD / "q"
            if src.exists() and not dst.exists():
                shutil.copyfile(src, dst)
                dst.chmod(0o755)
        r = self.call_fn(prompt, tag=f"{self.tag}-{sig}", cwd=CWD, timeout=timeout_s or 300, permission="default",
                         allowed_tools=self.allowed_tools, disallowed_tools=self.disallowed_tools, append_system=self.system, resume=resume,
                         extra_args=extra, use_rotation=False, json_schema=self.schema)
        returned = getattr(r, "session_id", "") or ""
        sid_ok = bool(returned) and (returned != fork_from if fork_from else returned == sid)
        ok = bool(getattr(r, "ok", False)) and sid_ok
        if fork_from and returned:
            self.st["sid"] = returned
        cum = float(getattr(r, "cost_usd", 0.0) or 0.0)
        usd = max(0.0, cum - max(float(self.st.get("cost_cum") or 0.0), float(parent_cost or 0.0)))
        self.st["cost_cum"] = max(cum, float(self.st.get("cost_cum") or 0.0))
        self.st.setdefault("turns", []).append({"t": dt.datetime.now().isoformat(timespec="seconds"), "sig": sig,
                                                "ok": ok, "sid_ok": sid_ok, "usd": round(usd, 6),
                                                "cum_raw": cum, "usage": getattr(r, "usage", {}) or {},
                                                "errors": getattr(r, "errors", []) or ([] if ok else ["返回 session_id 不一致"])})
        self.save()
        self.last_result = r
        if not ok:
            raise RuntimeError(f"live v2 会话/输出校验失败: {getattr(r, 'errors', [])}; returned_sid={returned}, expected={sid}")
        return r
