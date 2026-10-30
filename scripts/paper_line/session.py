# -*- coding: utf-8 -*-
"""session.py — paper v3 会话管理(A2: 每次触发起一个 claude -p, 第一次 --session-id 新建, 之后 --resume; 10/22 晚用户定)

一本账一个会话, 状态在 results/_live/<D>/v3_<line>/session.json: {date, line, sid, boot_tag, boot_at, turns: [...]}
三道"当天会话"校验(10/22 用户问"怎么证明 --resume 用的是当天自动启动的那个"):
  ①session.json 的 date ≠ 今天 → 拒绝 resume(要重新启动)
  ②会话记录文件(~/.claude/projects/<cwd 编码>/<sid>.jsonl)前两条用户消息必须含本线 BOOT 暗号 [BOOT D line v3](10/29 起从当天预热会话分叉: 第 1 条 = 共享开头, 暗号在第 2 条)
  ③每次返回的 session_id 必须等于记录的 sid
隔离(10/22 20:00 实测, TODO 3.0): cwd = 仓库外 C:/Users/admin/dev/_paper_line_cwd(不加载项目记忆, 首轮少 4 万 token); --system-prompt = paper 专用指令;
  --add-dir 仓库(只读工具能读); 只放行 Read / Grep / Glob / Bash(./q:*)
"""
import datetime as dt
import hashlib
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V3 = ROOT / "scripts" / "paper_line"
CWD = Path(r"C:\Users\admin\dev\_paper_line_cwd")
sys.path[:0] = [str(ROOT / "scripts" / "lib"), str(ROOT / "scripts" / "claude_profile")]
import claude_call as CC   # noqa: E402

TOOLS = ["Read", "Grep", "Glob", "Bash(./q:*)"]
NO_TOOLS = ["Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Agent"]


def system_prompt():
    t = (V3 / "prompt" / "common.md").read_text(encoding="utf-8")
    try:   # 10/24 用户令: 术语表统一口径(全部会话一样 → 吃缓存)
        sys.path.insert(0, str(V3))
        import harness as H
        t += H.glossary_text()
    except Exception:   # noqa: BLE001
        pass
    return t


def transcript(sid):
    base = Path.home() / ".claude" / "projects"
    fs = list(base.glob(f"*/{sid}.jsonl"))
    return fs[0] if fs else None


def first_user_text(f, n=1):
    """前 n 条用户消息全文(10/29 预热分叉: 第 1 条 = 共享开头, 本线 BOOT 暗号在第 2 条 → check 用 n=2)"""
    out = []
    try:
        for l in f.read_text(encoding="utf-8", errors="replace").splitlines():
            j = json.loads(l)
            if j.get("type") == "user":
                c = (j.get("message") or {}).get("content")
                if isinstance(c, list):
                    c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
                out.append(str(c or ""))   # 10/24: 共享开头放最前面, BOOT 暗号不在开头了 → 返回全文, 校验用"包含"
                if len(out) >= n:
                    break
    except (OSError, ValueError):
        pass
    return "\n".join(out)


SHARED_MARK = "[共享开头: "   # = pack.SHARED_HEAD 开头(session 不 import pack)
WARM_ASK = "\n\n(以上是今天全部账本共用的开头材料; 现在先不要分析、不要调用工具, 只回答两个字: 收到)"
_WARM_LOCK = threading.Lock()


def _flag(name, default=""):
    if os.environ.get(name) is not None:
        return os.environ[name]
    try:
        for l in (ROOT / "scripts" / "claude_profile" / "chain_flags.txt").read_text(encoding="utf-8").splitlines():
            k, _, v = l.split("#")[0].partition("=")
            if k.strip() == name:
                return v.strip()
    except OSError:
        pass
    return default


def split_head(text):
    """第一条消息 → (共享开头, 本线部分); 没有共享开头 / 开关关 → (None, text)"""
    if not text.startswith(SHARED_MARK) or (_flag("PAPER_WARM_FORK", "1") or "1") != "1":
        return None, text
    i = text.find("\n\n---\n\n[BOOT ")
    return (text[:i], text[i + len("\n\n---\n\n"):]) if i > 0 else (None, text)


def warm_session(head, out_dir, effort, timeout=600):
    """10/29 收盘后真调(scripts/temp/cache_probe_1029*.py): 中转站按会话号 + 第一条消息分流上游, 各线第一条消息不同 → 共享开头永远读不到别人的缓存(0/7)。
    改法: 当天一个预热会话, 第一条 = 共享开头; 各线 --resume 它 --fork-session 发本线材料 → 第一条逐字相同, 分叉首轮读到共享开头(2/2, read 43K)。
    同一天同一份开头只建一次(results/_live/<D>/_warm_<hash>.json); 失败 → None(调用方退回老办法新建会话)"""
    f = Path(out_dir).parent / f"_warm_{hashlib.sha1((head + effort).encode('utf-8')).hexdigest()[:10]}.json"
    with _WARM_LOCK:
        try:
            w = json.loads(f.read_text(encoding="utf-8"))
            if w.get("sid") and transcript(w["sid"]):
                return {**w, "new": False}
        except (OSError, ValueError):
            pass
        sid = str(uuid.uuid4())
        t0 = time.time()
        r = CC.call(head + WARM_ASK, tag="v3-warm", cwd=CWD, timeout=timeout, permission="default", allowed_tools=TOOLS, disallowed_tools=NO_TOOLS,
                    extra_args=["--session-id", sid, "--system-prompt", system_prompt(), "--add-dir", str(ROOT), "--effort", effort], json_tag="json")
        if r.is_error or (r.session_id or "") != sid or not transcript(sid):
            return None
        u = r.usage or {}
        w = {"sid": sid, "cum": float(r.cost_usd or 0.0), "at": dt.datetime.now().isoformat(timespec="seconds"), "secs": round(time.time() - t0, 1),
             "cache_read": u.get("cache_read_input_tokens"), "cache_write": u.get("cache_creation_input_tokens")}
        f.write_text(json.dumps(w, ensure_ascii=False, indent=1), encoding="utf-8")
        return {**w, "new": True}


class Session:
    def __init__(self, line_id, D, out_dir, effort="high"):
        self.line, self.D, self.dir, self.effort = line_id, D, Path(out_dir), effort
        self.dir.mkdir(parents=True, exist_ok=True)
        self.f = self.dir / "session.json"
        self.st = self._load()
        self.tag = f"[BOOT {D} {line_id} line]"

    def _load(self):
        try:
            st = json.loads(self.f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return st if st.get("date") == self.D else {}   # 校验①: 不是今天的会话一律不接

    def _save(self):
        self.f.write_text(json.dumps(self.st, ensure_ascii=False, indent=1), encoding="utf-8")

    @property
    def booted(self):
        return bool(self.st.get("sid"))

    def check(self):
        """校验②③之前的一道: 会话记录在不在、第一条是不是本线今天的 BOOT → (ok, 说明)"""
        if not self.booted:
            return False, "还没启动"
        if self.st.get("date") != self.D:
            return False, f"会话日期 {self.st.get('date')} ≠ {self.D}"
        tf = transcript(self.st["sid"])
        if not tf:
            return False, "找不到会话记录文件"
        if self.tag not in first_user_text(tf, 2):
            return False, "会话记录第一条不含本线今天的 BOOT 暗号"
        return True, "ok"

    def fork(self, text, rnd, timeout=300):
        """从主会话分出一个独立分支问一轮(--resume --fork-session): 看得到主会话已有内容, 说的话不写回主会话(10/22 23:5x 实测); 03 多方 / 空方并行用"""
        ok, why = self.check()
        if not ok:
            return {"ok": False, "err": f"会话校验失败: {why}", "text": "", "json": None, "secs": 0, "usd": 0, "usage": {}}
        t0 = time.time()
        r = CC.call(text, tag=f"v3-{self.line}-{rnd}", cwd=CWD, timeout=timeout, permission="default", allowed_tools=TOOLS, disallowed_tools=NO_TOOLS, resume=self.st["sid"],
                    extra_args=["--fork-session", "--system-prompt", system_prompt(), "--add-dir", str(ROOT), "--effort", self.effort], json_tag="json")
        secs = round(time.time() - t0, 1)
        forked = bool(r.session_id) and r.session_id != self.st["sid"]   # 分支必须是新会话号; 等于主会话号 = 没分叉成功, 内容写进了主会话
        u = r.usage or {}
        usd = max(0.0, (r.cost_usd or 0.0) - float(self.st.get("cost_cum") or 0.0))   # 10/23 凌晨压测实测: 返回的是会话累计花费(分支 = 主会话累计 + 分支这一轮), 只记增量
        self.st.setdefault("turns", []).append({"t": dt.datetime.now().strftime("%H:%M:%S"), "round": rnd, "fork": r.session_id, "secs": secs, "ok": bool(r.result) and not r.is_error and forked,
                                                 "usd": round(usd, 4), "cum_raw": r.cost_usd, "cache_read": u.get("cache_read_input_tokens"), "out": u.get("output_tokens"), "err": " | ".join(r.errors)[:300] if r.errors else ""})
        self._save()
        return {"ok": bool(r.result) and not r.is_error and forked, "text": r.result or "", "json": CC.extract_json_block(r.result or "")[0] if r.result else None,
                "secs": secs, "usd": usd, "usage": u, "err": "" if forked else "没有分叉出新会话"}

    def ask(self, text, rnd, timeout=300, boot=False):
        """发一轮 → dict(ok, text, json, secs, usd, usage, err)。boot=True: 新建会话(text 必须以 BOOT 暗号开头)"""
        if boot:
            assert self.tag in text[:600000], "第一条消息必须含 BOOT 暗号"   # 10/24: 共享开头在前, 暗号在共享开头之后
            self.st = {"date": self.D, "line": self.line, "sid": str(uuid.uuid4()), "boot_tag": self.tag, "boot_at": dt.datetime.now().isoformat(timespec="seconds"), "turns": []}
            head, rest = split_head(text)
            warm = warm_session(head, self.dir, self.effort) if head else None
            if warm:   # 10/29: 从当天预热会话分叉(第一条 = 共享开头), 本线材料当第二条发; 新会话号以返回为准
                text = rest
                self.st.update(sid="", warm=warm["sid"], cost_cum=warm["cum"])
                extra, resume = ["--fork-session"], warm["sid"]
            else:
                extra, resume = ["--session-id", self.st["sid"]], None
            self._save()
        else:
            ok, why = self.check()
            if not ok:
                return {"ok": False, "err": f"会话校验失败: {why}", "text": "", "json": None, "secs": 0, "usd": 0, "usage": {}}
            extra, resume = [], self.st["sid"]
        extra += ["--system-prompt", system_prompt(), "--add-dir", str(ROOT), "--effort", self.effort]
        t0 = time.time()
        r = CC.call(text, tag=f"v3-{self.line}-{rnd}", cwd=CWD, timeout=timeout, permission="default", allowed_tools=TOOLS, disallowed_tools=NO_TOOLS,
                    resume=resume, extra_args=extra, json_tag="json")
        secs = round(time.time() - t0, 1)
        if boot and self.st.get("warm") and r.session_id and r.session_id != self.st["warm"]:
            self.st["sid"] = r.session_id   # 分叉出的新会话号 = 本线会话号
        sid_ok = bool(self.st["sid"]) and (r.session_id or "") == self.st["sid"]   # 校验③
        j = CC.extract_json_block(r.result or "")[0] if r.result else None
        u = r.usage or {}
        cum = float(r.cost_usd or 0.0)
        usd = max(0.0, cum - float(self.st.get("cost_cum") or 0.0))   # 10/23 凌晨压测实测: --resume 返回的 total_cost_usd 是会话累计, 这一轮花费 = 本次累计 − 上次累计
        if cum:
            self.st["cost_cum"] = max(cum, float(self.st.get("cost_cum") or 0.0))
        turn = {"t": dt.datetime.now().strftime("%H:%M:%S"), "round": rnd, "secs": secs, "ok": bool(r.result) and not r.is_error and sid_ok, "sid_ok": sid_ok,
                "usd": round(usd, 4), "cum_raw": r.cost_usd, "in": u.get("input_tokens"), "cache_read": u.get("cache_read_input_tokens"), "cache_write": u.get("cache_creation_input_tokens"),
                "out": u.get("output_tokens"), "err": " | ".join(r.errors)[:300] if r.errors else ""}
        if boot and warm:
            turn.update(warm=warm["sid"], warm_new=warm["new"])
            if warm["new"]:   # 预热那一轮的钱记在建它的这条线上(当天总账不漏)
                turn.update(warm_usd=round(warm["cum"], 4), usd=round(usd + warm["cum"], 4), warm_cache_write=warm.get("cache_write"))
                usd = turn["usd"]
        self.st.setdefault("turns", []).append(turn)
        self._save()
        err = turn["err"] if not turn["ok"] else ""
        if not sid_ok and r.session_id:
            err = f"会话号不一致: 返回 {r.session_id} ≠ 记录 {self.st['sid']}"
        return {"ok": turn["ok"], "text": r.result or "", "json": j, "secs": secs, "usd": usd, "usage": u, "err": err}
