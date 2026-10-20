# -*- coding: utf-8 -*-
"""cli_inject.py — 在【本机】正在跑的 Claude Code 窗口里"打字发送"一条消息, 或读回它的回复(10/13 建, 被 cli_relay.py 经 ssh 远程调用)

用法(本机):
  python cli_inject.py send <base64(UTF-8 消息)>   # ssh 会话里没有桌面 → 自动经 schtasks /it 以登录用户身份无窗口重跑 _send
  python cli_inject.py read <标记>                  # 读本机 Claude 会话记录(~/.claude/projects/*/*.jsonl), 输出一行 JSON
原理: AttachConsole 到交互式 claude.exe 的控制台 → WriteConsoleInputW 直写输入缓冲区(纯 ctypes, 不用装 pywin32)。
  先注入正文, 停 2 秒, 再另起一次注入单独发回车——同一次写入里回车会变成换行、不发送(10/13 PC3 实测)。
选进程: 父进程是 cmd/WindowsTerminal/powershell 的 claude.exe(排除 -p 后台会话), 取 CPU 时间最多的。
限制: 目标机必须已登录(锁屏可以, 注销不行); 消息里的换行会被替换成空格。
"""
import base64, ctypes, ctypes.wintypes as W, glob, json, os, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "state"          # gitignore
NOWIN = 0x08000000              # CREATE_NO_WINDOW(零弹窗立法)


# ---------------- send ----------------
def find_claude():
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='claude.exe'\" | ForEach-Object { $p=Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue; "
          "$pp=Get-CimInstance Win32_Process -Filter ('ProcessId='+$_.ParentProcessId); "
          "[pscustomobject]@{pid=$_.ProcessId; parent=$pp.Name; cpu=$p.CPU; cmd=$_.CommandLine} } | ConvertTo-Json -Compress")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, creationflags=NOWIN).stdout.strip()
    procs = json.loads(out) if out else []
    procs = procs if isinstance(procs, list) else [procs]
    procs = [p for p in procs if " -p " not in f" {p.get('cmd') or ''} " and (p.get("parent") or "").lower()
             in ("cmd.exe", "windowsterminal.exe", "powershell.exe", "pwsh.exe", "openconsole.exe")]
    return max(procs, key=lambda p: p.get("cpu") or 0)["pid"] if procs else None


class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [("bKeyDown", W.BOOL), ("wRepeatCount", W.WORD), ("wVirtualKeyCode", W.WORD),
                ("wVirtualScanCode", W.WORD), ("UnicodeChar", W.WCHAR), ("dwControlKeyState", W.DWORD)]


class _EV(ctypes.Union):
    _fields_ = [("KeyEvent", KEY_EVENT_RECORD), ("_pad", ctypes.c_byte * 16)]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [("EventType", W.WORD), ("Event", _EV)]


def _records(chars, enter=False):
    recs = []
    for ch in chars:
        for down in (True, False):
            r = INPUT_RECORD(); r.EventType = 1
            ke = r.Event.KeyEvent
            ke.bKeyDown, ke.wRepeatCount, ke.UnicodeChar = down, 1, ch
            if enter:
                ke.wVirtualKeyCode, ke.wVirtualScanCode = 0x0D, 0x1C
            recs.append(r)
    return (INPUT_RECORD * len(recs))(*recs), len(recs)


def _send(text, res_file):
    """在登录用户的交互会话里执行(由 schtasks 拉起)"""
    def done(s):
        Path(res_file).write_text(s, encoding="utf-8")
        sys.exit(0)
    pid = find_claude()
    if not pid:
        done("NO_CLAUDE 本机没有交互式 Claude Code 窗口")
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.FreeConsole()
    if not k.AttachConsole(pid):
        done(f"ATTACH_FAIL pid={pid} err={ctypes.get_last_error()}")
    k.CreateFileW.restype = W.HANDLE
    h = k.CreateFileW("CONIN$", 0xC0000000, 3, None, 3, 0, None)
    n = W.DWORD(0)
    body, cnt = _records(text.replace("\r\n", "\n").replace("\n", " "))
    if not k.WriteConsoleInputW(h, body, cnt, ctypes.byref(n)):
        done(f"WRITE_FAIL err={ctypes.get_last_error()}")
    done(f"SENT pid={pid} chars={len(text)}")      # 回车由 send() 另起一次注入单独发(同一次写入里回车会变换行, 10/13 实测)


def _enter(res_file, variant):
    """只发回车(诊断/补发): variant=cr 发回车键(VK_RETURN); lf 发换行字符"""
    pid = find_claude()
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.FreeConsole()
    if not pid or not k.AttachConsole(pid):
        Path(res_file).write_text(f"ATTACH_FAIL pid={pid}", encoding="utf-8"); return
    k.CreateFileW.restype = W.HANDLE
    h = k.CreateFileW("CONIN$", 0xC0000000, 3, None, 3, 0, None)
    ch = "\n" if variant == "lf" else "\r"
    recs, cnt = _records(ch, enter=(variant != "lf"))
    n = W.DWORD(0)
    ok = k.WriteConsoleInputW(h, recs, cnt, ctypes.byref(n))
    Path(res_file).write_text(f"SENT enter({variant}) pid={pid} ok={ok}", encoding="utf-8")


def _peek(res_file):
    """诊断: 读交互式 Claude 窗口的控制台屏幕(光标附近 40 行), 看输入框里卡着什么"""
    pid = find_claude()
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.FreeConsole()
    if not pid or not k.AttachConsole(pid):
        Path(res_file).write_text(f"ATTACH_FAIL pid={pid}", encoding="utf-8"); return
    k.CreateFileW.restype = W.HANDLE
    h = k.CreateFileW("CONOUT$", 0xC0000000, 3, None, 3, 0, None)

    class CSBI(ctypes.Structure):
        _fields_ = [("size", W._COORD), ("cursor", W._COORD), ("attr", W.WORD), ("win", W.SMALL_RECT), ("max", W._COORD)]
    info = CSBI(); k.GetConsoleScreenBufferInfo(h, ctypes.byref(info))
    width, lines = info.size.X, []
    top = max(0, info.win.Bottom - 40)
    for y in range(top, info.win.Bottom + 1):
        buf, n = ctypes.create_unicode_buffer(width), W.DWORD(0)
        k.ReadConsoleOutputCharacterW(h, buf, width, W._COORD(0, y), ctypes.byref(n))
        lines.append(buf.value.rstrip())
    Path(res_file).write_text(f"PEEK pid={pid} 窗口 {info.win.Left},{info.win.Top}-{info.win.Right},{info.win.Bottom} 光标 {info.cursor.X},{info.cursor.Y}\n" + "\n".join(lines), encoding="utf-8")


def send(b64, mode="_send"):
    """先注入正文, 停 2 秒, 再单独注入一次回车(两次独立写入才会被当成"按回车提交", 合在一次里回车变换行)"""
    rc = _schtask_run(b64, mode)
    if rc == 0 and mode == "_send":
        time.sleep(2)
        rc = _schtask_run(base64.b64encode(b"x").decode(), "_enter_cr", quiet=True)
    return rc


def _schtask_run(b64, mode, quiet=False):
    """ssh 会话没有桌面, 借计划任务(/it=登录用户的交互会话)无窗口重跑 mode, 等结果文件"""
    STATE.mkdir(exist_ok=True)
    stamp = time.strftime("%H%M%S")
    msg_f, res_f, vbs = STATE / f"msg_{stamp}.b64", STATE / f"msg_{stamp}.result", STATE / "inject.vbs"
    msg_f.write_text(b64, encoding="ascii")
    pyw = Path(sys.executable).with_name("pythonw.exe")
    pyw = pyw if pyw.exists() else Path(sys.executable)
    vbs.write_text(f'CreateObject("WScript.Shell").Run """{pyw}"" ""{Path(__file__)}"" {mode} ""{msg_f}"" ""{res_f}""", 0, True\r\n',
                   encoding="utf-16")
    tr = f'wscript.exe //B "{vbs}"'
    subprocess.run(["schtasks", "/create", "/tn", "ClaudeCliRelay", "/tr", tr, "/sc", "once", "/st", "23:59", "/it", "/f"],
                   capture_output=True, creationflags=NOWIN)
    subprocess.run(["schtasks", "/run", "/tn", "ClaudeCliRelay"], capture_output=True, creationflags=NOWIN)
    for _ in range(30):
        time.sleep(1)
        if res_f.exists():
            r = res_f.read_text(encoding="utf-8")
            for f in (msg_f, res_f):
                f.unlink(missing_ok=True)
            if not quiet:
                print(r)
            return 0 if r.startswith(("SENT", "PEEK")) else 1
    print("TIMEOUT 30 秒内注入任务没回结果(本机没人登录? 计划任务被拦?)")
    return 1


# ---------------- read ----------------
def _is_human(d):
    """会话记录里的 user 行有两种: 真人输入(文字/粘贴/附件) 与 工具结果(tool_result); 只有前者算新的一轮"""
    c = (d.get("message") or {}).get("content")
    if isinstance(c, str):
        return True
    return isinstance(c, list) and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)

def _is_notice(d):
    """系统塞进来的 user 行(后台任务完成通知 / 系统提醒), 不是真人新一轮"""
    c = (d.get("message") or {}).get("content")
    s = c if isinstance(c, str) else " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text") if isinstance(c, list) else ""
    return s.lstrip().startswith(("<task-notification>", "<system-reminder>"))

def _carries(d, mark):
    """这一行是不是"带标记的那条消息本身": 真人 user 行, 或对方忙时排队进来的 queued_command 附件行(不认 last-prompt 等元数据行)"""
    if d.get("type") == "user" and _is_human(d):
        return mark in json.dumps((d.get("message") or {}).get("content"), ensure_ascii=False)
    if d.get("type") == "attachment":
        return mark in json.dumps(d.get("attachment"), ensure_ascii=False)
    return False


def read(mark):
    files = sorted(glob.glob(os.path.expanduser(r"~\.claude\projects\*\*.jsonl")), key=os.path.getmtime, reverse=True)[:6]
    for f in files:
        rows = []
        for l in open(f, encoding="utf-8", errors="ignore").read().splitlines():
            try:
                rows.append(json.loads(l))
            except ValueError:
                pass
        start = max((i for i, d in enumerate(rows) if _carries(d, mark)), default=None)
        if start is None:
            continue
        texts, done = [], False
        for d in rows[start + 1:]:
            if d.get("type") == "user" and _is_human(d) and not _is_notice(d):
                break                                 # 下一条真人消息 = 本轮结束(对方没写 turn_duration 就开始新一轮)
            # 10/19 修(pc3 诊断): 旧版把所有 queued 附件都当"本轮结束"就 break —— ①后台 agent 的 <task-notification> 排队附件
            # ②用户在对方忙时的插话(排队附件, 回复写在插话之后)都会截断, 读到空 → pending → 30 分钟超时。
            # 现在: 排队附件一律不 break(通知跳过; 真人插话合并进同一轮回答), 只认 turn_duration / 新的真人 user 行
            if d.get("type") == "attachment":
                continue
            if d.get("type") == "assistant":
                for b in (d.get("message") or {}).get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip():
                        texts.append(b["text"].strip())
            if d.get("type") == "system" and d.get("subtype") == "turn_duration":
                done = True
                break                                 # 这一轮答完
        print(json.dumps({"status": "done" if done else "pending", "text": "\n\n".join(texts)}, ensure_ascii=False))
        return 0
    print(json.dumps({"status": "not_found", "text": ""}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "send":
        sys.exit(send(sys.argv[2]))
    if cmd == "enter":
        sys.exit(send(base64.b64encode(b"x").decode(), mode="_enter_" + (sys.argv[2] if len(sys.argv) > 2 else "cr")))
    if cmd.startswith("_enter_"):
        _enter(sys.argv[3], cmd[len("_enter_"):])
        sys.exit(0)
    if cmd == "peek":
        sys.exit(send(base64.b64encode(b"peek").decode(), mode="_peek"))
    if cmd == "_peek":
        _peek(sys.argv[3])
    elif cmd == "_send":
        _send(base64.b64decode(Path(sys.argv[2]).read_text(encoding="ascii")).decode("utf-8"), sys.argv[3])
    elif cmd == "read":
        sys.exit(read(sys.argv[2]))
    else:
        print(__doc__)
        sys.exit(2)
