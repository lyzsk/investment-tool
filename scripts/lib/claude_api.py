# -*- coding: utf-8 -*-
"""claude_api.py — 直连 Messages API(官方 anthropic SDK, 流式)的公共调用口(10/21 晚建: 执行器 01→06 必须 3 分钟内, claude -p + 读文件工具多轮太慢)

和 claude_call.py(claude -p)的分工: 要工具 / 要读写文件的长会话 → claude_call; 材料由脚本备齐、只要模型写一段文字 + JSON 的短步骤 → 本模块
凭据: 和 claude -p 用同一把 key —— rotation 当前配置(--settings 文件)的 env > ~/.claude/settings.json 的 env > 进程环境变量; 只读, 不改任何 settings
缓存: system 块打 cache_control(1 小时), 同一导师各步共用前缀(人设 + 规则), 只付一次写缓存
记账: 每次调用一行 scripts/lib/claude_cost.csv(列同 claude_call; 美元按官方单价算, gravitex 系数 = 1)
用法: from claude_api import stream
      r = stream(system=[...], user="...", tag="se-meiyuelu-02", max_tokens=3000, effort="low")
      r.ok / r.text / r.json / r.ttft / r.secs / r.usage / r.cost_usd / r.error
"""
import csv
import datetime as dt
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COST_LOG = Path(__file__).resolve().parent / "claude_cost.csv"
MODEL = os.environ.get("SE_MODEL", "claude-opus-5-5")
# 官方单价 美元 / 百万 token: (输入, 输出, 缓存读, 缓存写 5 分钟, 缓存写 1 小时)
PRICE = {"claude-opus-5-5": (4.0, 20.0, 0.20, 5.0, 8.0), "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5, 4.0)}


def creds():
    """(base_url, token): 跟 claude -p 走同一把 key"""
    envs = []
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "claude_profile"))
        import rotation
        a = rotation.settings_args()
        if a and len(a) == 2:
            envs.append((json.loads(Path(a[1]).read_text(encoding="utf-8")) or {}).get("env") or {})
    except Exception:   # noqa: BLE001
        pass
    try:
        envs.append((json.loads((Path.home() / ".claude" / "settings.json").read_text(encoding="utf-8")) or {}).get("env") or {})
    except Exception:   # noqa: BLE001
        pass
    envs.append(os.environ)
    for e in envs:
        tok = e.get("ANTHROPIC_AUTH_TOKEN") or e.get("ANTHROPIC_API_KEY")
        if tok:
            return (e.get("ANTHROPIC_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL") or None), tok
    return None, None


_CLIENT = {}
GATE_DIR = ROOT / "scripts" / "temp" / "api_gate"


def _gate_n():
    """10/22 09:4x 用户令: 全进程在途 API 请求 ≤ N 路(chain_flags.txt API_MAX_INFLIGHT, 默认 8; 0 = 不限)"""
    v = os.environ.get("API_MAX_INFLIGHT")
    if v is None:
        try:
            for line in (ROOT / "scripts" / "claude_profile" / "chain_flags.txt").read_text(encoding="utf-8").splitlines():
                k, _, val = line.split("#")[0].partition("=")
                if k.strip() == "API_MAX_INFLIGHT":
                    v = val.strip()
        except OSError:
            pass
    try:
        return int(v) if v not in (None, "") else 8
    except ValueError:
        return 8


def gate_acquire(max_wait=180):
    """跨进程信号量: N 个槽文件, msvcrt 锁一个字节(进程死了锁自动释放, 不会留死锁); 等不到 max_wait 秒就放行(不让闸卡死链)。返回 (fd|None, 等待秒)"""
    n = _gate_n()
    if n <= 0:
        return None, 0.0
    import msvcrt
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    while True:
        for i in range(n):
            fd = os.open(str(GATE_DIR / f"slot_{i}"), os.O_RDWR | os.O_CREAT)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return fd, round(time.time() - t0, 1)
            except OSError:
                os.close(fd)
        if time.time() - t0 > max_wait:
            return None, round(time.time() - t0, 1)
        time.sleep(0.5)


def gate_release(fd):
    if fd is None:
        return
    import msvcrt
    try:
        os.lseek(fd, 0, 0)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    finally:
        os.close(fd)


def client():
    import anthropic
    base, tok = creds()
    k = (base, tok)
    if k not in _CLIENT:
        _CLIENT.clear()
        _CLIENT[k] = anthropic.Anthropic(base_url=base, auth_token=tok, api_key=None, max_retries=1, timeout=150)
    return _CLIENT[k]


@dataclass
class R:
    ok: bool = False
    text: str = ""
    json: object = None
    ttft: float = -1
    secs: float = 0
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    error: str = ""
    stop: str = ""
    first_ev: float = -1   # 第一个内容事件(思考或正文)的秒数
    gate_wait: float = 0.0
    stuck_retry: bool = False


def last_json(text):
    m = re.findall(r"```json\s*\n([\s\S]*?)```", text or "")
    for b in reversed(m):
        try:
            return json.loads(b)
        except ValueError:
            continue
    return None


def cost(model, u):
    p = PRICE.get(model, PRICE["claude-opus-5-5"])
    cc = u.get("cache_creation") or {}
    w1h = cc.get("ephemeral_1h_input_tokens") or 0
    w5m = (u.get("cache_creation_input_tokens") or 0) - w1h
    return ((u.get("input_tokens") or 0) * p[0] + (u.get("output_tokens") or 0) * p[1] + (u.get("cache_read_input_tokens") or 0) * p[2]
            + max(0, w5m) * p[3] + w1h * p[4]) / 1e6


def _log(tag, r, model):
    new = not COST_LOG.exists()
    with COST_LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts", "tag", "returncode", "ok", "is_error", "subtype", "duration_s", "in_tokens", "out_tokens", "cache_read", "cache_create", "cost_usd", "session_id", "window_waits", "errors"])
        u = r.usage
        w.writerow([dt.datetime.now().isoformat(timespec="seconds"), tag, 0 if r.ok else 1, int(r.ok), int(not r.ok), "api:" + model, round(r.secs, 1),
                    u.get("input_tokens"), u.get("output_tokens"), u.get("cache_read_input_tokens"), u.get("cache_creation_input_tokens"), r.cost_usd, "", 0, r.error[:300]])


def stream(*, system, user, tag, max_tokens=4000, effort="low", model=None, need_json=True, deadline_s=None, tools=None, first_byte_s=None):
    """10/22 09:4x 包一层: ①全局并发闸(排队时间不算本步时限) ②首字看门狗: first_byte_s 秒内没收到任何内容事件(思考 / 正文都算)= 卡死,
    断开重发一次(剩余时限 ≥ 30 秒才重发); 卡死两次 = 返回失败(error 带"卡死"); 其余参数同 _stream"""
    fd, waited = gate_acquire()
    try:
        t0 = time.time()
        r = _stream(system=system, user=user, tag=tag, max_tokens=max_tokens, effort=effort, model=model, need_json=need_json, deadline_s=deadline_s, tools=tools, first_byte_s=first_byte_s)
        left = (deadline_s - (time.time() - t0)) if deadline_s else None
        if r.error.startswith("卡死") and (left is None or left >= 30):
            r1 = r
            r = _stream(system=system, user=user, tag=tag + "-retry", max_tokens=max_tokens, effort=effort, model=model, need_json=need_json, deadline_s=left, tools=tools, first_byte_s=first_byte_s)
            r.secs = round(r.secs + r1.secs, 1)
            r.stuck_retry = True
        r.gate_wait = waited
        return r
    finally:
        gate_release(fd)


def _stream(*, system, user, tag, max_tokens=4000, effort="low", model=None, need_json=True, deadline_s=None, tools=None, first_byte_s=None):
    """system: 列表, 每项 字符串(不打缓存) 或 (字符串, "1h"|"5m")(在这块末尾打缓存断点; 1h 的必须排在 5m 前面); user: 本次动态材料。
    流式取全文, 记首字节与总耗时。deadline_s: 超过就中断(返回 ok=False, 已写出的文字保留在 text)
    tools: {"defs": [工具定义], "run": fn(name, input) -> str, "max_calls": N} —— 10/21 晚对照变体 C: 模型可调工具查料, 用满 N 次后不再给工具、要求直接写答案"""
    model = model or MODEL
    sys_blocks = []
    for it in system:
        t, ttl = (it if isinstance(it, tuple) else (it, None))
        if not t:
            continue
        b = {"type": "text", "text": t}
        if ttl:
            b["cache_control"] = {"type": "ephemeral", **({"ttl": "1h"} if ttl == "1h" else {})}
        sys_blocks.append(b)
    r, t0, parts = R(), time.time(), []
    msgs = [{"role": "user", "content": user}]
    usage_sum, n_calls, rounds = {}, 0, 0
    try:
        cl = client().with_options(timeout=float(deadline_s), max_retries=0) if deadline_s else client()   # 10/21 晚回放: 首字节前卡死原来要等 150 秒 × 2(读超时 = 本步时限, 不自动重试)
        if first_byte_s and (not deadline_s or first_byte_s < deadline_s):
            import anthropic
            cl = cl.with_options(timeout=anthropic.Timeout(float(deadline_s or 600), connect=15.0, read=float(first_byte_s)))   # SDK 自带的 Timeout(它底层是 httpx2, 不能用 httpx.Timeout)   # 连 ping 都没有 = 读超时 → 当卡死
        while True:
            rounds += 1
            kw = {}
            if tools and n_calls < tools.get("max_calls", 2):
                kw["tools"] = tools["defs"]
            elif tools:   # 工具用满: 历史里有 tool_use 块, 仍要声明工具定义, 但用 tool_choice none 禁止再调
                kw["tools"] = tools["defs"]
                kw["tool_choice"] = {"type": "none"}
            parts_round = []
            with cl.messages.stream(model=model, max_tokens=max_tokens, system=sys_blocks, messages=msgs,
                                    output_config={"effort": effort}, **kw) as s:
                for ev in s:
                    if r.first_ev < 0 and ev.type in ("content_block_start", "content_block_delta"):
                        r.first_ev = round(time.time() - t0, 1)
                    if first_byte_s and r.first_ev < 0 and time.time() - t0 > first_byte_s:
                        r.error = f"卡死: {first_byte_s}s 内没有任何内容事件"
                        break
                    if ev.type == "content_block_delta" and getattr(ev.delta, "type", "") == "text_delta":
                        if r.ttft < 0:
                            r.ttft = round(time.time() - t0, 1)
                        parts_round.append(ev.delta.text)
                    if deadline_s and time.time() - t0 > deadline_s:
                        r.error = f"超时 {deadline_s}s 中断"
                        break
                if r.error:
                    parts += parts_round
                    break
                m = s.get_final_message()
            u = m.usage.model_dump() if hasattr(m.usage, "model_dump") else dict(m.usage)
            for k, v in u.items():
                if isinstance(v, (int, float)):
                    usage_sum[k] = usage_sum.get(k, 0) + v
                elif k not in usage_sum:
                    usage_sum[k] = v
            r.stop = m.stop_reason or ""
            parts += parts_round
            if not (tools and m.stop_reason == "tool_use"):
                break
            res = []
            for b in m.content:
                if getattr(b, "type", "") == "tool_use":
                    n_calls += 1
                    try:
                        out = tools["run"](b.name, b.input)
                    except Exception as e:   # noqa: BLE001
                        out = f"(查料出错: {e!r})"
                    res.append({"type": "tool_result", "tool_use_id": b.id, "content": str(out)[:12000]})
            msgs.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in m.content]})
            msgs.append({"role": "user", "content": res + ([{"type": "text", "text": "查料次数已用完, 不要再查, 直接按要求写完答案(含最后的 json 块)。"}] if n_calls >= tools.get("max_calls", 2) else [])})
        r.usage = usage_sum
        if tools:
            r.usage["tool_calls"], r.usage["rounds"] = n_calls, rounds
    except Exception as e:   # noqa: BLE001
        r.error = f"{type(e).__name__}: {str(e)[:300]}"
        if first_byte_s and r.first_ev < 0 and "Timeout" in type(e).__name__ and time.time() - t0 < (deadline_s or 9e9) - 1:
            r.error = f"卡死: {first_byte_s}s 内没有任何字节({type(e).__name__})"
        r.usage = usage_sum or r.usage
    r.secs = round(time.time() - t0, 1)
    r.text = "".join(parts)
    r.cost_usd = round(cost(model, r.usage), 4) if r.usage else 0.0
    if not r.error:
        r.json = last_json(r.text) if need_json else None
        r.ok = (r.json is not None) if need_json else bool(r.text)
        if not r.ok:
            r.error = f"没有可解析的 ```json 块(stop={r.stop})"
    try:
        _log(tag, r, model)
    except Exception:   # noqa: BLE001
        pass
    return r


if __name__ == "__main__":
    x = stream(system=[("你是测试助手。", "1h")], user='只回一个 ```json 块: {"ok": true}', tag="api-selftest", max_tokens=300)
    print(x.ok, x.ttft, x.secs, x.json, x.usage.get("output_tokens"), x.cost_usd, x.error)
