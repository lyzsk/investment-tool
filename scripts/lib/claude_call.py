"""claude_call.py — 无头 claude -p 调用公共模块(§5.3, 2026-10-12 建)
统一此前 7 个文件各写一套的调用方式(盘点见 docs/TODO.md §0.5 10/12):
  - prompt 一律走 stdin(cmd /c 传 argv 会在首个换行截断 = 10/11 实锤 bug; 原生 exe 传 argv 有 ~32k 命令行上限)
  - 一律 --output-format json, 解析信封: 跳过网关通知行取末个 JSON 行; is_error / subtype(非 success 即失败, 如 error_max_turns)
  - 额度窗口/限流只在**错误文本**里匹配(\\b429\\b 等严格词), 撞上 → rotation 切下一套 key, 全耗尽等 45min, 有上限
  - 哨兵: result 文本里按整行匹配(DISTILL_OK 2026-10-09 等), 可要求必须出现
  - 结构化输出: result 文本末个 ```json(或指定 tag) 代码块 → JSON 解析 → 迷你 JSON Schema 校验(type/required/properties/items/enum/pattern/min*/max*)
  - 副作用核验: expect_files 每个都必须在调用开始后被改过(mtime 新鲜), 防"只回了哨兵没写文件"
  - 成本账本: 每次调用一行 scripts/lib/claude_cost.csv(tag/耗时/token 含缓存/美元/会话 id/错误)
用法:
  import sys; sys.path.insert(0, "scripts/lib"); from claude_call import call
  r = call(prompt, tag="tzzb-distill", permission="skip", timeout=3600, sentinels=["ALL_DISTILL_DONE"], require_sentinels=True)
  if not r.ok: print(r.errors)
自测(离线, 用桩 exe 模拟 claude): scripts/venv/Scripts/python.exe -X utf8 scripts/lib/claude_call.py --selftest"""
import csv
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COST_LOG = Path(os.environ.get("CLAUDE_CALL_COST_LOG") or Path(__file__).resolve().parent / "claude_cost.csv")
_EXE = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
WINDOW_RE = re.compile(r"usage limit|5-hour limit|rate.?limit|\b429\b|quota exceeded|overloaded", re.I)
WINDOW_DEFER_S = 2700
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# 10/15 A13①: 精简参数(去动态系统提示段/斜杠命令与 skill 自动加载/MCP), 调用方按需再加 "--tools" 白名单;
#   提示词里"读 skills/xxx/SKILL.md"是按文件路径读, 不依赖斜杠命令, 不受影响(链驱动器 10/12 起即此口径)
LEAN_ARGS = ["--exclude-dynamic-system-prompt-sections", "--disable-slash-commands", "--strict-mcp-config"]
PERMISSIONS = {
    "acceptEdits": ["--permission-mode", "acceptEdits"],
    "skip": ["--dangerously-skip-permissions"],   # 会话要跑 Bash(curl/node/python)的批处理: -p 模式下 acceptEdits 会拒 Bash
    "default": [],
}


@dataclass
class Result:
    ok: bool
    errors: list = field(default_factory=list)
    result: str = ""
    session_id: str = ""
    is_error: bool = False
    subtype: str = ""
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    duration_s: float = 0.0
    returncode: int = 0
    parsed: object = None
    sentinels: dict = field(default_factory=dict)
    stdout_tail: str = ""
    stderr_tail: str = ""
    window_waits: int = 0


def claude_exe():
    override = os.environ.get("CLAUDE_CALL_EXE")   # 自测/特殊环境: 指向桩程序(可带参数, 空格分隔)
    if override:
        return override.split()
    return [str(_EXE)] if _EXE.exists() else ["claude"]


def parse_envelope(stdout):
    """末个以 { 开头的行 = 信封(前面可能有网关通知行); 都不是就整体解析"""
    for line in reversed((stdout or "").strip().splitlines()):
        if line.lstrip().startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return json.loads(stdout or "")


def sentinel_hits(text, sentinels):
    """哨兵按整行匹配(去首尾空白); 以 re: 开头的按正则整行匹配"""
    lines = [l.strip() for l in (text or "").splitlines()]
    hits = {}
    for s in sentinels or []:
        if s.startswith("re:"):
            rx = re.compile(s[3:])
            hits[s] = any(rx.fullmatch(l) for l in lines)
        else:
            hits[s] = s in lines
    return hits


def extract_json_block(text, tag="json"):
    blocks = re.findall(r"```" + re.escape(tag) + r"\s*\n([\s\S]*?)```", text or "")
    if not blocks:
        return None, f"result 里无 ```{tag} 代码块"
    try:
        return json.loads(blocks[-1]), None
    except json.JSONDecodeError as e:
        return None, f"```{tag} 块 JSON 解析失败: {e}"


_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def validate(obj, schema, path="$"):
    """迷你 JSON Schema(只支持本项目用得到的子集), 返回错误列表; 空=通过"""
    errs = []
    t = schema.get("type")
    if t:
        ts = t if isinstance(t, list) else [t]
        ok = False
        for x in ts:
            if x == "integer":
                ok |= isinstance(obj, int) and not isinstance(obj, bool)
            elif x == "number":
                ok |= isinstance(obj, (int, float)) and not isinstance(obj, bool)
            else:
                ok |= isinstance(obj, _TYPES[x])
        if not ok:
            return [f"{path}: 类型应为 {t}, 实为 {type(obj).__name__}"]
    if "enum" in schema and obj not in schema["enum"]:
        errs.append(f"{path}: {obj!r} 不在 {schema['enum']}")
    if isinstance(obj, str):
        if "minLength" in schema and len(obj) < schema["minLength"]:
            errs.append(f"{path}: 长度 {len(obj)} < {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], obj):
            errs.append(f"{path}: 不匹配 /{schema['pattern']}/")
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        if "minimum" in schema and obj < schema["minimum"]:
            errs.append(f"{path}: {obj} < {schema['minimum']}")
        if "maximum" in schema and obj > schema["maximum"]:
            errs.append(f"{path}: {obj} > {schema['maximum']}")
    if isinstance(obj, list):
        if "minItems" in schema and len(obj) < schema["minItems"]:
            errs.append(f"{path}: 元素 {len(obj)} < {schema['minItems']}")
        if "maxItems" in schema and len(obj) > schema["maxItems"]:
            errs.append(f"{path}: 元素 {len(obj)} > {schema['maxItems']}")
        if "items" in schema:
            for i, x in enumerate(obj):
                errs += validate(x, schema["items"], f"{path}[{i}]")
    if isinstance(obj, dict):
        for k in schema.get("required", []):
            if k not in obj:
                errs.append(f"{path}: 缺字段 {k}")
        props = schema.get("properties", {})
        for k, v in obj.items():
            if k in props:
                errs += validate(v, props[k], f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}: 多余字段 {k}")
    return errs


def _rotation():
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "claude_profile"))
        import rotation   # noqa: PLC0415  可选依赖: 没有就不轮换
        return rotation
    except Exception:   # noqa: BLE001
        return None


def _log_cost(tag, r):
    new = not COST_LOG.exists()
    with COST_LOG.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts", "tag", "returncode", "ok", "is_error", "subtype", "duration_s", "in_tokens", "out_tokens",
                        "cache_read", "cache_create", "cost_usd", "session_id", "window_waits", "errors"])
        u = r.usage or {}
        w.writerow([datetime.now().isoformat(timespec="seconds"), tag, r.returncode, int(r.ok), int(r.is_error), r.subtype,
                    round(r.duration_s), u.get("input_tokens", ""), u.get("output_tokens", ""),
                    u.get("cache_read_input_tokens", ""), u.get("cache_creation_input_tokens", ""), r.cost_usd,
                    r.session_id, r.window_waits, " | ".join(r.errors)[:500]])


def call(prompt, *, tag, cwd=ROOT, timeout=1800, permission="acceptEdits", allowed_tools=None, disallowed_tools=None,
         append_system=None, resume=None, extra_args=None, drop_env=("ANTHROPIC_MODEL",), use_rotation=True,
         max_window_waits=8, expect_files=None, sentinels=None, require_sentinels=False, json_schema=None,
         json_tag="json", log_cost=True):
    """跑一次 claude -p, 返回 Result(ok=信封成功 且 哨兵/JSON/文件核验都过). 不抛异常, 失败原因在 errors"""
    rot = _rotation() if use_rotation else None
    env = {k: v for k, v in os.environ.items() if k not in (drop_env or ())}   # 子进程继承宿主 ANTHROPIC_MODEL 会 400(10/11 实证)
    base = claude_exe() + ["-p", "--output-format", "json"] + PERMISSIONS[permission]
    if allowed_tools:
        base += ["--allowedTools", ",".join(allowed_tools)]
    if disallowed_tools:
        base += ["--disallowedTools", ",".join(disallowed_tools)]
    if append_system:
        base += ["--append-system-prompt", append_system]
    if resume:
        base += ["--resume", resume]
    base += list(extra_args or [])
    t_start = time.time()
    res = Result(ok=False)
    n400 = 0   # 10/16 用户立法: 同一请求 API 400 重试 3 次, 3 次都 400 → rotation.on_api400 切 gravitex 再试一次
    while True:
        args = base + (rot.settings_args() if rot else [])
        if rot:
            try:
                rot.log_use(tag)
            except Exception:   # noqa: BLE001
                pass
        t0 = time.time()
        try:
            # 按字节传 UTF-8: text 模式在 Windows 会把 LF 写成 CRLF 且受本地编码影响
            p = subprocess.run(args, input=prompt.encode("utf-8"), cwd=str(cwd), capture_output=True, timeout=timeout,
                               env=env, creationflags=NOWIN)
            rc, out, err = p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
        except subprocess.TimeoutExpired as e:
            rc, out, err = -1, (e.stdout or b"").decode("utf-8", "replace"), f"claude -p 超时 {timeout}s"
        except OSError as e:   # exe 不存在/无法启动: 不抛, 记进 errors
            rc, out, err = -2, "", f"claude 启动失败 {args[0]}: {e}"
        res.duration_s = time.time() - t0
        res.returncode, res.stdout_tail, res.stderr_tail = rc, (out or "")[-2000:], (err or "")[-2000:]
        env_ok = True
        try:
            j = parse_envelope(out)
        except (json.JSONDecodeError, ValueError):
            j, env_ok = {}, False
        res.is_error = bool(j.get("is_error")) or rc != 0 or not env_ok
        res.subtype = j.get("subtype", "")
        res.result = j.get("result", "") or ""
        res.session_id = j.get("session_id", "") or ""
        res.usage = j.get("usage", {}) or {}
        res.cost_usd = j.get("total_cost_usd", 0) or 0
        err_text = (err or "") + (res.result if j.get("is_error") else "") + ("" if env_ok else (out or "")[-1000:])
        if res.is_error and rot and hasattr(rot, "is_api400") and rot.is_api400(err_text):
            n400 += 1
            if n400 < 3:
                time.sleep(5); continue
            if n400 == 3 and rot.on_api400(tag):
                continue
        if res.is_error and WINDOW_RE.search(err_text) and res.window_waits < max_window_waits:
            res.window_waits += 1
            if rot and rot.on_window_limit():
                continue
            time.sleep(WINDOW_DEFER_S)
            continue
        break
    if not env_ok:
        res.errors.append(f"stdout 不是 JSON 信封(rc={rc}): {(out or err or '')[-300:]}")
    elif res.is_error:
        res.errors.append(f"claude 报错 rc={rc} subtype={res.subtype}: {(res.result or err or '')[-300:]}")
    elif res.subtype and res.subtype != "success":
        res.errors.append(f"subtype={res.subtype}(非 success)")
    res.sentinels = sentinel_hits(res.result, sentinels)
    if require_sentinels:
        miss = [s for s, ok in res.sentinels.items() if not ok]
        if miss:
            res.errors.append(f"缺哨兵: {miss}")
    if json_schema is not None:
        obj, e = extract_json_block(res.result, json_tag)
        if e:
            res.errors.append(e)
        else:
            res.parsed = obj
            res.errors += [f"schema: {x}" for x in validate(obj, json_schema)[:20]]
    for f in expect_files or []:
        f = Path(f)
        if not f.exists():
            res.errors.append(f"应写文件不存在: {f}")
        elif f.stat().st_mtime < t_start:
            res.errors.append(f"应写文件未更新(mtime 早于调用开始, 疑似只回哨兵没写): {f}")
    res.ok = not res.errors
    res.duration_s = time.time() - t_start
    if log_cost:
        _log_cost(tag, res)
    return res


def _selftest():
    """离线自测: 用 python 桩模拟 claude 的各种输出"""
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    stub = tmp / "stub.py"
    stub.write_text(r'''import sys, json, os
p = sys.stdin.buffer.read().decode("utf-8")
mode = os.environ["STUB_MODE"]
if mode == "ok":
    print("[gateway] notice: something")
    res = "做完了\n```json\n{\"date\": \"2026-10-09\", \"rules\": [\"A1\", \"B2\"]}\n```\nDISTILL_OK 2026-10-09"
    if os.environ.get("STUB_FILE"):
        open(os.environ["STUB_FILE"], "w").write("x")
    sys.stdout.flush()
    env = {"type": "result", "subtype": "success", "is_error": False, "result": res + "\nPROMPT_LEN=" + str(len(p)),
           "session_id": "s1", "total_cost_usd": 0.12, "usage": {"input_tokens": 10, "output_tokens": 5}}
    sys.stdout.buffer.write((json.dumps(env, ensure_ascii=False) + "\n").encode("utf-8"))
elif mode == "error":
    print(json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True, "result": "max turns"}))
elif mode == "text":
    print("plain text output, not json")
''', encoding="utf-8")
    os.environ["CLAUDE_CALL_EXE"] = f"{sys.executable} {stub}"
    global COST_LOG
    COST_LOG = tmp / "cost.csv"
    schema = {"type": "object", "required": ["date", "rules"], "properties": {
        "date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}, "rules": {"type": "array", "minItems": 1, "items": {"type": "string"}}}}
    prompt = "第一行\n第二行(换行不能截断)\n" + "长" * 50000
    os.environ["STUB_MODE"] = "ok"
    out = tmp / "out.txt"
    os.environ["STUB_FILE"] = str(out)
    r = call(prompt, tag="selftest", use_rotation=False, sentinels=["DISTILL_OK 2026-10-09", "re:PROMPT_LEN=\\d+"],
             require_sentinels=True, json_schema=schema, expect_files=[out])
    assert r.ok, r.errors
    assert f"PROMPT_LEN={len(prompt)}" in r.result, "stdin 传 prompt 长度不符(被截断?)"
    assert r.parsed["rules"] == ["A1", "B2"] and r.cost_usd == 0.12 and r.session_id == "s1"
    r = call("x", tag="selftest", use_rotation=False, sentinels=["NOPE"], require_sentinels=True)
    assert not r.ok and any("缺哨兵" in e for e in r.errors)
    r = call("x", tag="selftest", use_rotation=False, json_schema={"type": "object", "required": ["zzz"]})
    assert not r.ok and any("缺字段 zzz" in e for e in r.errors)
    os.environ.pop("STUB_FILE")
    stale = tmp / "stale.txt"
    stale.write_text("old")
    os.utime(stale, (time.time() - 3600, time.time() - 3600))
    r = call("x", tag="selftest", use_rotation=False, expect_files=[stale])
    assert not r.ok and any("未更新" in e for e in r.errors)
    os.environ["STUB_MODE"] = "error"
    r = call("x", tag="selftest", use_rotation=False)
    assert not r.ok and r.subtype == "error_max_turns"
    os.environ["STUB_MODE"] = "text"
    r = call("x", tag="selftest", use_rotation=False)
    assert not r.ok and any("不是 JSON 信封" in e for e in r.errors)
    rows = list(csv.reader(COST_LOG.open(encoding="utf-8")))
    assert rows[0][0] == "ts" and len(rows) == 7, len(rows)
    assert validate({"a": 1}, {"type": "object", "properties": {"a": {"type": "integer", "minimum": 2}}}) == ["$.a: 1 < 2"]
    print("claude_call 自测全过(桩: 成功/缺哨兵/schema 失败/文件未更新/subtype 报错/非 JSON 输出/成本账本/长 prompt 多行 stdin)")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
