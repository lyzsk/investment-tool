# -*- coding: utf-8 -*-
"""wx_send.py — PC1 → 微信 的统一出口(10/19 建; 零 token)

所有"PC1 脚本 / Claude Code 会话 → hermes → 微信"的推送都走这里, 只管"怎么发", 排版交给 fmt_cli_reply.py:
  ① 排版: 默认 auto —— 短消息(≤280 字且 ≤4 行)只去 md 粗体 / 反引号; 长消息按类型(挂单 / 日报 / 预判 / 通用)重排; --raw 原样
  ② 分段: 超过 --max 字(默认 1800)按空行 / 小节切成几条, 每条带 (1/3); 注意每段都占一次微信配额
  ③ 配额: 微信 iLink 不是按时间冷却, 而是"用户每给 hermes 发一条消息, 之后只能主动推约 10 条"(10/16、10/19 两次实测, 见
          scripts/dfcf/snapshots/order-skill/lessons.md L7)。所以: 记录每次成功推送 → 算"自用户上一条消息以来已推几条";
          ≥8 条时在消息末尾提示"回个字补额度"; 被限频时盯 hermes gateway.log 等用户新消息(新 inbound 一出现立刻重发), 同时每 120 秒试一次, 最多 --wait 秒(默认 600)
  ④ 去重: 10 分钟内完全相同的内容不重发(--force 跳过)
  ⑤ 落账: scripts/hermes/state/wx_sent.jsonl(时间 / 来源 / 类型 / 字数 / 结果); 发不出去的进 wx_outbox.jsonl, --flush 补发
用法:
  python wx_send.py "文本" [--src 脚本名] [--raw] [--kind order|report|forecast|generic] [--wait 600] [--max 1800] [--dry] [--force]
  echo 文本 | python wx_send.py -          stdin
  python wx_send.py --file a.txt
  python wx_send.py --quota                自用户上一条微信消息以来已推几条
  python wx_send.py --flush                补发 outbox
Python 内调用: sys.path.insert(0, ".../scripts/hermes"); import wx_send; wx_send.send(text, src="xxx", raw=False)
退出码: 0 已发 / 2 限频没发出去(已进 outbox) / 1 其他失败
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fmt_cli_reply as F   # noqa: E402

HERMES = r"C:\Users\admin\AppData\Local\hermes\hermes-agent\bin\hermes.exe"
GATEWAY_LOG = Path(r"C:\Users\admin\AppData\Local\hermes\logs\gateway.log")
STATE = HERE / "state"
SENT = STATE / "wx_sent.jsonl"
OUTBOX = STATE / "wx_outbox.jsonl"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
QUOTA = 10          # 每条用户消息后约 10 条
QUOTA_WARN = 8
INBOUND_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ .*\[Weixin\] inbound from=")
REPLY_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ .*\[Weixin\] Sending response")


# ================================================================ 配额
def _gw_tail(nbytes=400_000):
    try:
        with GATEWAY_LOG.open("rb") as fh:
            fh.seek(0, 2)
            n = fh.tell()
            fh.seek(max(0, n - nbytes))
            return fh.read().decode("utf-8", "ignore").splitlines()
    except OSError:
        return []


def last_inbound():
    """用户最后一条微信消息的时间(本地)"""
    t = None
    for l in _gw_tail():
        m = INBOUND_RE.match(l)
        if m:
            t = m.group(1)
    return dt.datetime.strptime(t, "%Y-%m-%d %H:%M:%S") if t else None


def used_since(t0):
    """t0 之后已占用的推送: 本出口成功推送 + hermes 自己回复用户的条数"""
    if t0 is None:
        return 0
    n = 0
    for l in _gw_tail():
        m = REPLY_RE.match(l)
        if m and dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") > t0:
            n += 1
    if SENT.exists():
        for l in SENT.read_text(encoding="utf-8").splitlines()[-300:]:
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if r.get("ok") and dt.datetime.fromisoformat(r["ts"]) > t0:
                n += 1
    return n


def quota():
    t0 = last_inbound()
    return t0, used_since(t0)


# ================================================================ 排版 / 分段
def render(text, raw=False, kind=None):
    text = text.strip()
    if raw:
        return "raw", text
    if len(text) < 50:   # 10/20 用户: <50 字的短消息不套"日报 / 挂单"等格式头, 直接裸发
        return "raw", text
    if not kind and len(text) <= 280 and text.count("\n") <= 3:
        return "short", F.clean_inline(text)
    k, msg = F.format_text(text, kind=kind)
    # 10/20 事故: 我给 T1 影响点 / key 逻辑 指定 --kind report, 日报排版器按"日报结构"抽取, 正文全丢, 只发出"【日报】✅ 正常: 📋概要 9 项"(18~29 字)
    # → 排版后正文剩不到原文 40% = 排版器认错了类型, 退回原文(只去 md 记号), 不发残缺的假格式
    if len(msg) < len(text) * 0.4:
        return "raw-fallback", F.clean_inline(text)
    return k, msg


def split(msg, mx):
    """超长按"空行 > 换行"在 mx 前最近处切; 不会切出只有标题的碎段"""
    if len(msg) <= mx:
        return [msg]
    parts, rest = [], msg
    while len(rest) > mx:
        cut = rest.rfind("\n\n", 0, mx)
        if cut < mx // 3:
            cut = rest.rfind("\n", 0, mx)
        if cut < mx // 3:
            cut = mx
        parts.append(rest[:cut].strip("\n"))
        rest = rest[cut:].lstrip("\n")
    if rest.strip():
        parts.append(rest)
    return [f"({i}/{len(parts)}) {p}" for i, p in enumerate(parts, 1)] if len(parts) > 1 else parts


# ================================================================ 发送
def _hermes(msg):
    fd, p = tempfile.mkstemp(suffix=".txt", prefix="wx_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(msg)
        r = subprocess.run([HERMES, "send", "--to", "weixin", "--file", p], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", creationflags=NOWIN, timeout=90)
        out = (r.stdout or "") + (r.stderr or "")
        return ("ok" if "Sent to" in out else ("rate" if "rate limited" in out else "fail")), out.strip()[-200:]
    except Exception as e:   # noqa: BLE001
        return "fail", str(e)[-200:]
    finally:
        try:
            os.unlink(p)
        except OSError:
            pass


def _log(f, rec):
    STATE.mkdir(exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _dup(h):
    if not SENT.exists():
        return False
    lim = dt.datetime.now() - dt.timedelta(minutes=10)
    for l in SENT.read_text(encoding="utf-8").splitlines()[-50:]:
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if r.get("ok") and r.get("hash") == h and dt.datetime.fromisoformat(r["ts"]) > lim:
            return True
    return False


def send_one(msg, src="", kind="", wait=600, verbose=True):
    """发一条; 限频时等用户新消息或每 120 秒重试, 最多 wait 秒。返回 ok|rate|fail"""
    t_start, t0 = time.time(), last_inbound()
    st, out = _hermes(msg)
    while st == "rate" and time.time() - t_start < wait:
        if verbose:
            print(f"微信配额用完(用户上条消息 {t0:%H:%M} 后已推 {used_since(t0)} 条), 等用户在微信回消息或 120 秒后重试…" if t0 else "微信限频, 等待重试…",
                  file=sys.stderr, flush=True)
        t_try = time.time() + 120
        while time.time() < min(t_try, t_start + wait):
            time.sleep(5)
            t1 = last_inbound()
            if t1 and t0 and t1 > t0:   # 用户来新消息 = 额度恢复
                break
        t0 = last_inbound() or t0
        st, out = _hermes(msg)
    _log(SENT, {"ts": dt.datetime.now().isoformat(timespec="seconds"), "src": src, "kind": kind, "chars": len(msg), "ok": st == "ok",
                "st": st, "hash": hashlib.md5(msg.encode("utf-8")).hexdigest(), "err": "" if st == "ok" else out})
    return st


CONF_EXEMPT = re.compile(r"^(aohong_alert|se_|event_|step_|session_rollover|open_live|todo_sync|schedule|plan1021)")   # 告警 / 状态 / 回执; 出单和分析不豁免
PRED = re.compile(r"概率|胜率|期望|次日|明天|明早|预计|大概率|会冲|冲高|套利|值得|倾向|判断|建议.*(买|卖|做|接)")


def conf_lint(text, src=""):
    """判断 / 预测类消息必须带置信度标注 + 不自信点; 返回缺什么(空=合格)。告警 / 状态 / 回执类 src 豁免"""
    if CONF_EXEMPT.search(src or "") or len(PRED.findall(text)) < 2:
        return ""
    miss = []
    if not re.search(r"置信\s*[:：]?\s*\d{1,3}\s*%", text):   # 10/21 用户立法: 置信度用百分比(odds.confidence), 档位可附在后面
        miss.append("没有 置信 N%")
    if not re.search(r"\d{1,3}(\.\d)?\s*%", re.sub(r"置信\s*[:：]?\s*\d{1,3}\s*%", "", text)):
        miss.append("没有 概率百分比")
    if not re.search(r"不自信|没把握|不确定", text):
        miss.append("没有 不自信点")
    if not re.search(r"失效|证伪|作废", text):
        miss.append("没有 失效条件")
    return "、".join(miss)


def send(text, src="", raw=False, kind=None, wait=600, mx=1800, dry=False, force=False, verbose=True):
    # 10/20 用户令: 测试推送一律 --dry, 不许真发到微信 —— src / 正文里带 test / selftest / 自测 / 测试推送 的自动转 dry(防忘加 --dry)
    if not dry and re.search(r"(?i)\b(self)?test\b|自测|测试推送", f"{src} {text[:80]}"):
        print(f"[自动 dry] src={src!r} 像测试推送, 不真发(10/20 用户令); 真要发请换 src", file=sys.stderr)
        dry = True
    miss = conf_lint(text, src)
    if miss and not force:   # 10/21 用户批评"分析缺乏置信度": 判断类推送缺置信度标注 → 不发, 退回补齐(--force 强发)
        print(f"[置信度闸] 不发: 这条像判断 / 预测, 但{miss}。每条结论要带 [置信 高/中/低 · 样本 n · 失效条件], 末尾列不自信点; 确认不需要请加 --force", file=sys.stderr)
        return "noconf"
    k, msg = render(text, raw, kind)
    t0, used = quota()
    parts = split(msg, mx)
    if t0 and used + len(parts) >= QUOTA_WARN and not raw:
        parts[-1] += f"\n\n(微信推送额度: 你上条消息 {t0:%H:%M} 后已推 {used + len(parts)} 条, 约 {QUOTA} 条会卡, 方便时回个字)"
    if dry:
        print("\n----- 分段 -----\n".join(parts))
        print(f"[dry] 类型={k} 段数={len(parts)} 用户上条消息={t0} 已推={used}", file=sys.stderr)
        return "dry"
    h = hashlib.md5(msg.encode("utf-8")).hexdigest()
    if not force and _dup(h):
        if verbose:
            print("10 分钟内已发过同样内容, 跳过(--force 强发)", file=sys.stderr)
        return "dup"
    res = "ok"
    for i, p in enumerate(parts):
        st = send_one(p, src, k, wait, verbose)
        if st != "ok":
            for q in parts[i:]:
                _log(OUTBOX, {"ts": dt.datetime.now().isoformat(timespec="seconds"), "src": src, "kind": k, "text": q, "st": st})
            res = st
            break
    if verbose:
        print({"ok": "sent", "rate": "限频没发出去, 已进 outbox(用户回消息后 --flush)", "fail": "发送失败, 已进 outbox"}[res], file=sys.stderr)
    return res


def flush(wait=60):
    if not OUTBOX.exists():
        print("outbox 空")
        return 0
    rows = [json.loads(l) for l in OUTBOX.read_text(encoding="utf-8").splitlines() if l.strip()]
    left = []
    for i, r in enumerate(rows):
        st = send_one(r["text"], r.get("src", "") + "(补发)", r.get("kind", ""), wait)
        if st != "ok":
            left = rows[i:]
            break
    OUTBOX.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in left), encoding="utf-8")
    print(f"补发 {len(rows) - len(left)} 条, 剩 {len(left)} 条")
    return 0 if not left else 2


def main():
    for s in (sys.stdout, sys.stderr, sys.stdin):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?")
    ap.add_argument("--file")
    ap.add_argument("--src", default="")
    ap.add_argument("--raw", action="store_true")
    ap.add_argument("--kind", choices=["order", "report", "forecast", "generic"])
    ap.add_argument("--wait", type=int, default=600)
    ap.add_argument("--max", type=int, default=1800)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--quota", action="store_true")
    ap.add_argument("--flush", action="store_true")
    a = ap.parse_args()
    if a.quota:
        t0, n = quota()
        print(f"用户上条微信消息 {t0:%m-%d %H:%M:%S}, 之后已推 {n} 条(约 {QUOTA} 条会被限频)" if t0 else "gateway.log 里没找到用户消息")
        return 0
    if a.flush:
        return flush(a.wait)
    if a.file:
        text = Path(a.file).read_text(encoding="utf-8")
    elif a.text and a.text != "-":
        text = a.text
    else:
        text = sys.stdin.read()
    if not text.strip():
        print("空消息, 不发", file=sys.stderr)
        return 1
    r = send(text, a.src, a.raw, a.kind, a.wait, a.max, a.dry, a.force)
    return {"ok": 0, "dry": 0, "dup": 0, "rate": 2}.get(r, 1)


if __name__ == "__main__":
    sys.exit(main())
