# -*- coding: utf-8 -*-
"""drain_pending.py — 换会话(07:58) / hermes 重启(04:00) 之前扫一遍交互 Claude 会话的 jsonl, 把用户睡着时没送达的东西清掉(10/27 用户令; 零 token)

为什么: 07:58 session_rollover 直接 taskkill 旧会话 —— 排队还没轮到的消息、答到一半的回复跟着丢; 04:00 hermes 重启那几秒里推的微信
        发失败进 outbox, 以前只能手动 --flush。用户醒来看不到 = 白答。
扫什么(10/27 用户定窗口: 你睡着那段 = 睡前最后一条消息 ~ 早上第一条消息(还没醒 = 现在); 睡着 = 最近一段 ≥3 小时没发消息的空档;
       睡前发的、回复是睡着后才写完的也算; 只看 24 小时内写过、entrypoint=cli 的交互会话;
       已处理过的消息记在 state/drain_state.json, 04:00 和 07:58 不重复):
  ① lost     排队了(queue-operation enqueue)但到文件末尾都没送进会话        → 带进新会话
  ② open     送进去了但这一轮没答完(没有 turn_duration)                      → 带进新会话(连同已写出的部分)
  ③ unpushed 答完了、按规矩该推微信(消息里要求发微信 / 带 →pc1 前缀的实盘类), 但这一轮没有成功的推送 → 现在补推
  ④ outbox   wx_outbox.jsonl 里窗口内没发出去的 → 补发; 更早的不动(过期的盘中卡片补发没意义, 手动 wx_send --flush)
  补推被限频 = 进 outbox, 起 --watch 后台等你下一条微信(额度恢复)再发, 最长到 --watch-until
用法:
  python drain_pending.py --mode rollover [--dry]     session_rollover.py 关旧会话前调(也可 import: run("rollover"))
  python drain_pending.py --mode hermes0400 --restart  04:00 计划任务: 先扫+补推 → 重启 hermes gateway → 等 weixin 连上 → 补发 outbox
  python drain_pending.py --report                     只看不动(= --dry)
  python drain_pending.py --watch [--watch-until 10:00]  等用户回微信后补发 outbox(被前两种模式自动拉起)
日志: scripts/temp/drain_pending.log
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import wx_send as W   # noqa: E402

PROJ = Path(os.path.expanduser(r"~\.claude\projects"))
STATE_F = HERE / "state" / "drain_state.json"
LOG = ROOT / "scripts" / "temp" / "drain_pending.log"
HERMES_LOG = ROOT / "scripts" / "temp" / "hermes_gw_restart.log"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACH = NOWIN | getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

MARK = re.compile(r"^\s*(\[[A-Za-z0-9_\-]+→pc1 \d{6}\])")
WX_ASK = re.compile(r"(?<![已没不别])(发(我)?微信|推(到|送到?)?(我)?微信|发到微信|推给我)(?!的|没有)|微信(上)?(发|推|告诉)我")   # "已发微信 / 你发我微信的那条 / 发微信没有" 不算要求
WX_NO = re.compile(r"(不要|不用|别|无需|除非[^。；;\n]{0,12})(发|推)(我)?(到)?微信")   # 明说别推
LIVE = re.compile(r"挂单|改单|竞价单|撤单|持仓|成交|止损|做[Tt]|仓位|怎么挂")   # 只认盘中(09:15~15:00)从手机转来的: 10/26 起工程讨论由 PC3 自己 --fetch, 不推微信
PUSH_CMD = re.compile(r"python\S*\s[^\n;&|]*(wx_send\.py|fmt_cli_reply\.py[^\n;&|]*--send|order_push\.py|rule_review_push\.py)|wx_send\.send\(|hermes(\.exe)?\"?\s+send\b")   # 真在执行推送(grep / sed 读源码不算)
PUSH_NOT = re.compile(r"--(dry|quota|report|help)\b")
PUSH_BAD = re.compile(r"限频|发送失败|outbox|置信度闸|\[dry\]|自动 dry|Traceback|rate limited")


def log(*a):
    LOG.parent.mkdir(exist_ok=True)
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] " + " ".join(str(x) for x in a)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _state():
    try:
        return json.loads(STATE_F.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(s):
    cut = (dt.datetime.now() - dt.timedelta(days=3)).isoformat()
    s = {k: v for k, v in s.items() if v.get("at", "") >= cut}   # 只留 3 天
    STATE_F.parent.mkdir(exist_ok=True)
    STATE_F.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


# ================================================================ 扫 jsonl
def interactive_files(hours=24):
    """最近 hours 小时写过的交互会话(entrypoint=cli; 后台 claude -p 是 sdk-cli)"""
    lim = time.time() - hours * 3600
    out = []
    for f in PROJ.glob("*/*.jsonl"):
        if f.stat().st_mtime < lim:
            continue
        with f.open(encoding="utf-8", errors="replace") as fh:
            for i, l in enumerate(fh):
                m = re.search(r'"entrypoint":"([^"]+)"', l)
                if m:
                    if m.group(1) == "cli":
                        out.append(f)
                    break
                if i > 200:
                    break
    return sorted(out, key=lambda p: p.stat().st_mtime)


def _text(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _human(r):
    """真人消息(直接输入 / 排队插话) → 文本; 其他 → None。系统通知、后台任务通知、贴图占位、定时任务触发都不算"""
    if r.get("type") == "user":
        c = (r.get("message") or {}).get("content")
        if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            return None
        if (r.get("origin") or {}).get("kind") not in (None, "human") or r.get("isMeta") or r.get("isCompactSummary") or r.get("promptSource") == "system":
            return None   # promptSource=system = 持久定时触发的提示词; isCompactSummary = 压缩上下文的摘要, 都不是你发的
        s = _text(c).strip()
    elif r.get("type") == "attachment" and (r.get("attachment") or {}).get("type") == "queued_command":
        a = r["attachment"]
        if (a.get("origin") or {}).get("kind") not in (None, "human"):
            return None
        s = _text(a.get("prompt")).strip()
    else:
        return None
    if not s or s.startswith(("<task-notification>", "<system-reminder>", "[Image", "<command-", "<local-command")):
        return None
    return s


def _need_push(text, ts):
    """按规矩该推微信: 你在消息里要求发微信; 或盘中(09:15~15:00)从手机转来(带 →pc1 前缀)的实盘类"""
    if WX_NO.search(text):
        return False
    if WX_ASK.search(text):
        return True
    if not (MARK.match(text) and LIVE.search(text)):
        return False
    try:
        hm = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except ValueError:
        return False
    return "09:15" <= hm <= "15:00"


def _turn_start(r):
    if r.get("type") != "user":
        return False
    c = (r.get("message") or {}).get("content")
    return not (isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c))


def scan(f):
    """→ 这个会话里每条你的消息: {uuid, ts, end(这一轮答完的时间), text, mark, status(lost/open/done), reply, pushed, need_push}"""
    rows = []
    for l in f.open(encoding="utf-8", errors="replace"):
        try:
            rows.append(json.loads(l))
        except ValueError:
            pass
    msgs, cur, queue = [], None, []
    tool_res = {}
    for r in rows:
        c = (r.get("message") or {}).get("content") if r.get("type") == "user" else None
        for b in c if isinstance(c, list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                tool_res[b.get("tool_use_id")] = json.dumps(b.get("content"), ensure_ascii=False)
    for r in rows:
        t = r.get("type")
        if t == "queue-operation":
            op, c = r.get("operation"), (r.get("content") or "")
            if op == "enqueue":
                queue.append(r)
            elif op == "remove":
                i = next((i for i, q in enumerate(queue) if (q.get("content") or "") == c), None)
                if i is not None:
                    queue.pop(i)
            elif op == "dequeue" and queue:
                queue.pop(0)
            continue
        h = _human(r)
        if h is not None:
            m = {"uuid": r.get("uuid"), "ts": r.get("timestamp", ""), "text": h, "texts": [], "push": []}
            if cur is None or cur["done"]:   # 一轮没结束时进来的(排队插话 / 一起出队的几条 / 打断后重说)并进同一轮
                cur = {"done": False, "msgs": []}
            cur["msgs"].append(m)
            msgs.append((m, cur))
            continue
        if t == "user" and _turn_start(r) and cur and cur["done"]:
            cur = {"done": False, "msgs": []}       # 定时任务 / 通知开的新一轮, 不算真人消息
        if cur is None:
            continue
        if t == "assistant":
            for b in (r.get("message") or {}).get("content") or []:
                if not isinstance(b, dict):
                    continue
                for m in cur["msgs"]:
                    if b.get("type") == "text" and b.get("text", "").strip():
                        m["texts"].append(b["text"].strip())
                    elif b.get("type") == "tool_use":
                        cmd = str((b.get("input") or {}).get("command") or "")
                        if PUSH_CMD.search(cmd) and not PUSH_NOT.search(cmd):
                            m["push"].append(b.get("id"))
        elif t == "system" and r.get("subtype") == "turn_duration":
            cur["done"] = True
            cur["end"] = r.get("timestamp", "")
    out = []
    for m, turn in msgs:
        mk = MARK.match(m["text"])
        pushed = any(pid in tool_res and not PUSH_BAD.search(tool_res[pid]) for pid in m["push"])
        out.append({"uuid": m["uuid"], "ts": m["ts"], "end": turn.get("end", ""), "text": m["text"], "mark": mk.group(1) if mk else "",
                    "status": "done" if turn["done"] else "open", "reply": "\n\n".join(m["texts"]), "pushed": pushed,
                    "need_push": _need_push(m["text"], m["ts"])})
    for q in queue:   # 到文件末尾还在排队 = 没送进会话
        s = (q.get("content") or "").strip()
        if s and not s.startswith("<task-notification>"):
            mk = MARK.match(s)
            out.append({"uuid": "q:" + q.get("timestamp", ""), "ts": q.get("timestamp", ""), "end": "", "text": s, "mark": mk.group(1) if mk else "",
                        "status": "lost", "reply": "", "pushed": False, "need_push": _need_push(s, q.get("timestamp", ""))})
    return out


def _z(d):
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def in_window(x, start, end):
    """睡着那段: 睡前最后一条消息本身; 以及更早发的、但回复是你睡着后才写完(或到现在都没写完 / 还在排队)的; 早上第一条及之后的不算"""
    s, e = _z(start), _z(end)
    if x["ts"] >= e:
        return False
    if x["ts"] >= s:
        return True
    return x["ts"] >= _z(start - dt.timedelta(hours=12)) and (not x["end"] or x["end"] > s)


def _human_ts(f):
    """这个会话里你每条消息的时间(UTC 字符串)"""
    out = []
    for l in f.open(encoding="utf-8", errors="replace"):
        if '"queued_command"' not in l and '"type":"user"' not in l and '"queue-operation"' not in l:
            continue
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if (r.get("type") == "queue-operation" and r.get("operation") == "enqueue") or _human(r) is not None:
            out.append(r.get("timestamp", "")[:19])
    return out


def window(gap_hours=3):
    """10/27 用户定: 只扫"睡前最后一条消息 → 早上第一条消息"中间这段。
    睡觉 = 最近一段 ≥ gap_hours 小时你没发消息的空档(算到现在为止): 起点 = 空档前你最后一条, 终点 = 空档后你第一条(还没醒 = 现在)。
    → (会话文件, 起点, 终点) 本地时区 datetime"""
    files = interactive_files()
    now = dt.datetime.now().astimezone()
    ts = sorted({t for f in files for t in _human_ts(f) if t})
    pts = [dt.datetime.fromisoformat(t).replace(tzinfo=dt.timezone.utc).astimezone() for t in ts] + [now]
    for i in range(len(pts) - 1, 0, -1):
        if pts[i] - pts[i - 1] >= dt.timedelta(hours=gap_hours):
            return files, pts[i - 1], pts[i]
    return files, (pts[-2] if len(pts) > 1 else now - dt.timedelta(hours=gap_hours)), now   # 没睡(一直有消息): 只看最后一条之后


def _local(ts):
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except ValueError:
        return ts[11:16]


# ================================================================ outbox
def fresh_outbox(cut):
    """cut = (起, 止) 本地时间 'YYYY-MM-DDTHH:MM:SS'(和 outbox 的 ts 同格式); → (窗口内的, 窗口外的)"""
    if not W.OUTBOX.exists():
        return [], []
    rows = [json.loads(l) for l in W.OUTBOX.read_text(encoding="utf-8").splitlines() if l.strip()]
    inw = [r for r in rows if cut[0] <= r.get("ts", "") < cut[1]]
    return inw, [r for r in rows if r not in inw]


def _cut(start, end):
    f = lambda d: d.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")   # noqa: E731
    return f(start), f(end)


def flush_fresh(cut, dry=False, wait=20):
    """只补发窗口内的 outbox; 窗口外的原样留着"""
    fresh, stale = fresh_outbox(cut)
    if not fresh or dry:
        return 0, len(fresh)
    left = []
    for i, r in enumerate(fresh):
        if W.send_one(r["text"], r.get("src", "") + "(补发)", r.get("kind", ""), wait, verbose=False) != "ok":
            left = fresh[i:]
            break
    newer = [r for r in fresh_outbox(cut)[0] if r not in fresh]   # 发送期间别人新写进来的也保留
    W.OUTBOX.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in stale + left + newer), encoding="utf-8")
    return len(fresh) - len(left), len(left)


def spawn_watch(until, cut):
    subprocess.Popen([sys.executable, "-X", "utf8", str(Path(__file__)), "--watch", "--watch-until", until, "--since", cut[0], "--to", cut[1]],
                     cwd=str(ROOT), creationflags=DETACH, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def watch(until, cut):
    """outbox 有被限频的: 等你在微信回消息(额度恢复)就补发, 最长到 until"""
    end = dt.datetime.combine(dt.date.today(), dt.time.fromisoformat(until))
    t0 = W.last_inbound()
    log(f"watch: 等微信新消息后补发 outbox({cut[0]} ~ {cut[1]}), 最长到 {until}")
    while dt.datetime.now() < end:
        if not fresh_outbox(cut)[0]:
            log("watch: outbox 已空, 退出")
            return 0
        t1 = W.last_inbound()
        if t1 and (not t0 or t1 > t0):
            sent, left = flush_fresh(cut)
            log(f"watch: 你 {t1:%H:%M} 回了消息 → 补发 {sent} 条, 剩 {left}")
            t0 = t1
        time.sleep(15)
    log(f"watch: 到 {until} 还剩 {len(fresh_outbox(cut)[0])} 条没发出去(手动 wx_send.py --flush)")
    return 0


# ================================================================ 主流程
def run(mode, gap=3, dry=False, watch_until="10:00"):
    """→ {"carry": [没答完 / 没送进会话的消息], "pushed": n, "outbox_left": n, "lines": [给交接用的说明]}"""
    st = _state()
    files, start, end = window(gap)
    cut = _cut(start, end)
    log(f"{mode}: 扫你睡着那段 {start:%m-%d %H:%M}(睡前最后一条) ~ {end:%m-%d %H:%M}(早上第一条 / 现在), 会话 {len(files)} 个")
    carry, pushed, notes = [], 0, []
    for f in files:
        for x in (x for x in scan(f) if in_window(x, start, end) or (mode == "rollover" and x["status"] in ("lost", "open") and x["ts"] >= _z(end))):
            # ↑ 10/27 用户要: 07:58 前已醒、发了消息但还没答完就被换掉的, 也带进新会话(04:00 会话还活着, 不需要)
            if x["uuid"] in st:
                continue
            q = x["text"][:40].replace("\n", " ")
            if x["status"] in ("lost", "open"):
                if mode != "rollover":      # 04:00 会话还活着, 没答完的让它接着答, 不动
                    continue
                carry.append({**x, "file": str(f)})
                st[x["uuid"]] = {"at": dt.datetime.now().isoformat(), "st": "carry"}
                continue
            if not (x["need_push"] and not x["pushed"] and x["reply"]):
                continue
            body = f"【补发 {_local(x['ts'])} 那条的回复(当时没推到微信)】你问: {q}…\n\n{x['reply']}"
            res = "dry" if dry else W.send(body, src=f"drain_{mode}", wait=20, verbose=False)
            log(f"补推 {_local(x['ts'])} 「{q}」 → {res}")
            if res == "noconf":            # 置信度闸拦下: 不强发; 04:00 先不记, 留给 07:58 带进新会话补齐再推
                if mode != "rollover":
                    continue
                carry.append({**x, "file": str(f), "status": "noconf"})
            pushed += res == "ok"
            if not dry:
                st[x["uuid"]] = {"at": dt.datetime.now().isoformat(), "st": res}
    if not dry:
        _save_state(st)
    sent, left = flush_fresh(cut, dry)
    if sent or left:
        log(f"outbox({cut[0]} ~ {cut[1]}): 补发 {sent} 条, 剩 {left} 条" + ("(dry)" if dry else ""))
    if left and not dry:
        spawn_watch(watch_until, cut)
    for c in carry:
        tag = {"lost": "排队了没送进会话", "open": "没答完", "noconf": "答完了但补推被置信度闸拦下(要补齐置信度 / 不自信点 / 失效条件再推)"}[c["status"]]
        notes += [f"### {_local(c['ts'])} {c['mark']} —— {tag}" + ("（要推微信）" if c["need_push"] else ""), "", "原话:", "", c["text"], ""]
        if c["reply"]:
            notes += ["当时已写出的部分:", "", c["reply"][:3000], ""]
    if left:
        notes += [f"- 微信 outbox 还有 {left} 条最近的没发出去(限频)" + ("" if dry else f", 已起后台 watch 等你回微信补发, 最长到 {watch_until}") + "; 之后手动 `wx_send.py --flush`", ""]
    log(f"{mode}: 补推 {pushed} 条 / 带进新会话 {len(carry)} 条 / outbox 剩 {left}" + ("(dry)" if dry else ""))
    return {"carry": carry, "pushed": pushed, "outbox_left": left, "lines": notes, "cut": cut}


def hermes_restart():
    """= gw_restart.vbs 那一行; 等到 gateway.log 出现新的 'weixin connected'"""
    gl = W.GATEWAY_LOG
    pos = gl.stat().st_size if gl.exists() else 0
    with HERMES_LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"[{dt.datetime.now():%Y/%m/%d %H:%M:%S}] restart (drain_pending)\n")
        fh.flush()
        try:
            subprocess.run([W.HERMES, "gateway", "restart"], stdout=fh, stderr=fh, creationflags=NOWIN, timeout=180)
        except (OSError, subprocess.TimeoutExpired) as e:
            fh.write(f"restart error: {e!r}\n")
    for _ in range(40):
        time.sleep(3)
        try:
            with gl.open("rb") as fh:
                fh.seek(pos)
                if b"weixin connected" in fh.read():
                    time.sleep(10)
                    return True
        except OSError:
            pass
    return False


def main():
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["rollover", "hermes0400"], default="rollover")
    ap.add_argument("--restart", action="store_true", help="hermes0400: 扫完补推后重启 hermes gateway, 连上后补发 outbox")
    ap.add_argument("--gap", type=float, default=3, help="你多少小时没发消息算睡着(10/27 用户定窗口: 睡前最后一条 ~ 早上第一条)")
    ap.add_argument("--since", default="", help="watch 用: outbox 窗口起(本地时间)")
    ap.add_argument("--to", default="", help="watch 用: outbox 窗口止(本地时间)")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--report", action="store_true", help="只看: 列出每条消息的判定, 不推不记")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--watch-until", default="10:00")
    a = ap.parse_args()
    if a.watch:
        return watch(a.watch_until, (a.since, a.to) if a.since and a.to else _cut(*window(a.gap)[1:]))
    if a.report:
        files, start, end = window(a.gap)
        print(f"窗口(你睡着那段): {start:%m-%d %H:%M} 睡前最后一条 ~ {end:%m-%d %H:%M} 早上第一条 / 现在")
        done = _state()
        for f in files:
            xs = [x for x in scan(f) if in_window(x, start, end)]
            if not xs:
                continue
            print(f"## {f}")
            for x in xs:
                print(f"{_local(x['ts'])} {x['status']:4} 要推={'是' if x['need_push'] else '否'} 已推={'是' if x['pushed'] else '否'} "
                      f"回复{len(x['reply'])}字 {'[已处理]' if x['uuid'] in done else ''} {x['text'][:50]!r}")
        fresh, stale = fresh_outbox(_cut(start, end))
        print(f"outbox: 窗口内 {len(fresh)} 条 / 窗口外 {len(stale)} 条(不动)")
        return 0
    try:
        r = run(a.mode, a.gap, a.dry, a.watch_until)
    except Exception as e:   # noqa: BLE001  扫描出错也不能耽误 04:00 的 hermes 重启
        log(f"扫描出错: {e!r}")
        now = dt.datetime.now().astimezone()
        r = {"carry": [], "lines": [], "cut": _cut(now - dt.timedelta(hours=8), now)}
    if a.restart and not a.dry:
        ok = hermes_restart()
        log(f"hermes gateway 重启 → {'weixin 已连上' if ok else '等了 2 分钟没看到 weixin connected'}")
        sent, left = flush_fresh(r["cut"])
        log(f"重启后 outbox: 补发 {sent} 条, 剩 {left} 条")
        if left:
            spawn_watch(a.watch_until, r["cut"])
    if r["carry"]:
        out = ROOT / "scripts" / "temp" / f"carry_{a.mode}_{dt.datetime.now():%Y%m%d_%H%M}.md"
        out.write_text("\n".join([f"# {a.mode} 时没处理完的消息", ""] + r["lines"]) + "\n", encoding="utf-8")
        log(f"没处理完的写在 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
