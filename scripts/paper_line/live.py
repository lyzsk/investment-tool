# -*- coding: utf-8 -*-
"""live.py — 实盘线专属逻辑(10/24 模块 5; 线怎么生成见 pack.live_lines, 休眠见 executor.V3.dormant)

一天怎么跑(10/24 用户定):
  08:28 计划任务 PaperLineFleet 拉起总控 → mentor_select 出名单(selected_mentors.json, 保留用户已挑的 keep)
  → 盘前首跑(串行): 第 1 本先跑(写热共享开头的提示缓存), 它第一轮回来后每 LIVE_BOOT_GROUP 本一组放行(前一组第一轮都回来 / 等满 LIVE_BOOT_WAIT 秒)
  → 盘前各版不逐条推, 全部落地(或到 LIVE_DIGEST_AT)合成一条「盘前汇总」推微信
  → 用户回"留下 芷影攫心,刘忆青"(keep.py 写 keep) → 09:19 起没留下的线休眠, 留下的照常触发; 随时可加回 / 收束
  → 09:19 用户还没挑 = 按 LIVE_DEFAULT_KEEP(默认入选导师前 3 位)
开关(chain_flags.txt): LIVE_LINE · LIVE_FIRST · LIVE_BOOT_GROUP · LIVE_BOOT_WAIT · LIVE_KEEP_AT · LIVE_DEFAULT_KEEP · LIVE_DIGEST_AT · LIVE_PUSH
"""
import datetime as dt
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V3 = ROOT / "scripts" / "paper_line"
sys.path[:0] = [str(V3), str(V3 / "tools"), str(ROOT / "scripts" / "lib")]
import pack   # noqa: E402

PY = ROOT / "scripts" / "venv" / "Scripts" / "python.exe"


def first_at():
    return pack.flag("LIVE_FIRST", "08:35:00") or "08:35:00"


def boot_wait(idx, ids, books, now=dt.datetime.now, sleep=time.sleep):
    """第 idx 本(按名单顺序)盘前首跑前等多久: 0 号不等; 1~G 号等 0 号第一轮回来; 之后每组等上一组全部第一轮回来; 每组最多等 LIVE_BOOT_WAIT 秒
    books: {线号: V3 对象}(还没建好的当没回来)。返回等了几秒"""
    if idx == 0:
        return 0
    g = max(1, int(pack.flag("LIVE_BOOT_GROUP", "3") or 3))
    cap = float(pack.flag("LIVE_BOOT_WAIT", "240") or 240)
    k = (idx - 1) // g
    prev = [ids[0]] if k == 0 else ids[1 + (k - 1) * g: 1 + k * g]
    t0 = now()

    def back(lid):
        b = books.get(lid)
        return bool(b and ((b.sess.st.get("turns") or []) or b.strategy))
    while not all(back(x) for x in prev) and (now() - t0).total_seconds() < cap * (k + 1):
        sleep(3)
    return round((now() - t0).total_seconds(), 1)


def _tg_tag(code, D):
    """10/25 用户选 J: 盘前汇总里标出被电报点名的票(盘前电报 + 前一晚的不算: 只看 D 当天 ≤ 此刻)"""
    if (pack.flag("TG_TAG_PUSH", "0") or "0") != "1":   # 10/25 用户: 周一先不上, 周二再开
        return ""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
        import telegraph_now as TGN
        return TGN.tag(str(code), D, pack.clock_hms())
    except Exception:   # noqa: BLE001
        return ""


def digest_text(D, books, sel):
    """盘前汇总(一条微信): 每条线的看法 + 挂单, 末尾告诉用户怎么留下(模块 6 计划表做好后换成计划表格式)"""
    import skill_names as SN
    side_cn = {"BUY": "买", "SELL": "卖"}
    keep_def = sorted(pack.keep_of(D), key=lambda s: (sel.get("premarket") or []).index(s) if s in (sel.get("premarket") or []) else 99)
    rank = {x["id"]: x for x in sel.get("ranked") or []}
    pre = sel.get("premarket") or []
    # 10/25: 编号 = 盘前名单顺序(keep.py「留下 1、3」按这个序号解析); 原来按各本建好的先后排, 并发建本时可能和名单顺序不一致
    books = dict(sorted(books.items(), key=lambda kv: pre.index(kv[1].line["skill"]) if kv[1].line["skill"] in pre else 99))
    L = [f"📋 实盘线盘前汇总 {D}（{len(books)} 条线）", ""]
    for lid, b in books.items():
        i = pre.index(b.line["skill"]) + 1 if b.line["skill"] in pre else len(pre) + 1
        s, ln = b.strategy or {}, b.line
        r = rank.get(ln["skill"]) or {}
        perf = f"近20日 {r['ret20']:+.1f}% 日均 {r['avg']:+.2f}%" if r.get("ret20") is not None else "UP"
        L.append(f"{i}. {ln['name']}skill（{perf}）")
        if not s:
            L.append("  （盘前版还没出 / 失败）")
            continue
        L.append(f"  看法：{str(s.get('view') or '')[:90]}")
        n = 0
        for x in s.get("codes") or []:
            tgt = _tg_tag(x.get("code"), D)
            rid = {str(rl.get("id")): rl for rl in x.get("rules") or []}
            sc = [y for y in x.get("scenarios") or [] if isinstance(y, dict)]
            if sc:   # 模块 6 计划表: 一只票一块, 每个情景一行(条件 → 动作 · 概率 · 单)
                L.append(f"  ▪ {x.get('name') or ''}{x['code']}{' ' + tgt if tgt else ''}")
                for y in sc[:4]:
                    pr = y.get("prob") or {}
                    pv = f" {pr['value']:.0%}({pr.get('ref')})" if isinstance(pr, dict) and isinstance(pr.get("value"), (int, float)) else ""
                    od = "、".join(f"{side_cn.get(rid[i].get('side'), '')}{rid[i].get('qty')}{b.qty_pct(x['code'], rid[i].get('side'), rid[i].get('qty') or 0, rid[i].get('px') or 0)}@{rid[i].get('px')}" for i in map(str, y.get("rules") or []) if i in rid)
                    L.append(f"    {y.get('id')} {str(y.get('when'))[:40]} → {y.get('action')}{pv}{' · ' + od if od else ''}")
                n += len(rid)
                continue
            for rl in x.get("rules") or []:
                n += 1
                if n <= 4:
                    L.append(f"  ▪ {side_cn.get(rl.get('side'), rl.get('side'))} {x.get('name') or ''}{x['code']} {rl.get('qty')} 股{b.qty_pct(x['code'], rl.get('side'), rl.get('qty') or 0, rl.get('px') or 0)} {'竞价' if rl.get('auction') else ''}{'≤' if rl.get('side') == 'BUY' else '≥'}{rl.get('px')}{' ' + tgt if tgt else ''}")
        if n > 4 and not any(x.get("scenarios") for x in s.get("codes") or []):
            L.append(f"  …共 {n} 张单")
        elif not n:
            L.append("  不挂单")
    L += ["", f"回复「留下 1、3」(编号或名字) 选今天跟哪几条；随时「暂停 2」「恢复 2」；{(pack.flag('LIVE_KEEP_AT', '09:19:00') or '09:19:00')[:5]} 前没回 = 默认留下："
          + "、".join(SN.cn(x) for x in keep_def)]
    return "\n".join(L)


def digest(D, books, now=dt.datetime.now, sleep=time.sleep, send=True):
    """等盘前各版都落地(或到 LIVE_DIGEST_AT)→ 推一条盘前汇总; 一天只推一次(标记文件 premarket_digest.txt)"""
    mark = ROOT / "results" / "_live" / D / "premarket_digest.txt"
    if mark.exists():
        return None
    until = pack.flag("LIVE_DIGEST_AT", "09:12:00") or "09:12:00"
    get = books if callable(books) else (lambda: books)   # 可传函数: 各本 V3 对象是陆续建好的
    while now().strftime("%H:%M:%S") < until and not (get() and all(b.strategy for b in get().values()) and len(get()) >= len(pack.live_sel(D).get("premarket") or [])):
        sleep(5)
    txt = digest_text(D, get(), pack.live_sel(D))
    mark.parent.mkdir(parents=True, exist_ok=True)
    mark.write_text(txt, encoding="utf-8")
    if send:
        for i, part in enumerate(chunks(txt)):   # 一条微信 ≤ 2800 字: 按线切, 不拆一条线的计划表
            if i:
                time.sleep(2)
            subprocess.Popen([str(PY), "-X", "utf8", "scripts/hermes/wx_send.py", part, "--raw", "--src", "live_digest"], cwd=ROOT,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), stdout=open(mark.with_suffix(".log"), "a", encoding="utf-8"), stderr=subprocess.STDOUT)
        late = [lid for lid, b in get().items() if not b.strategy]
        if late:   # 10/25 用户: 09:12 没赶上的线, 盘前版一落地就补发(进合并推送总线, 和别的消息合成一条), 一直等到 LIVE_KEEP_AT
            threading.Thread(target=_late_digest, args=(D, get, late, now, sleep), name="live-digest-late", daemon=True).start()
    return txt


def _late_digest(D, get, late, now=dt.datetime.now, sleep=time.sleep):
    keep_at = pack.flag("LIVE_KEEP_AT", "09:19:00") or "09:19:00"
    left = list(late)
    while left and now().strftime("%H:%M:%S") < keep_at:
        B = get()
        ready = [lid for lid in left if B.get(lid) is not None and B[lid].strategy]
        if ready:
            txt = digest_text(D, {lid: B[lid] for lid in ready}, pack.live_sel(D)).replace("📋 实盘线盘前汇总", "📋 补发: 盘前汇总里没赶上的线", 1)
            try:
                sys.path.insert(0, str(ROOT / "scripts" / "hermes"))
                import push_bus as PB
                if PB.on():
                    PB.enqueue(txt, src="live_digest", urgent=True, D=D)
                else:
                    subprocess.Popen([str(PY), "-X", "utf8", "scripts/hermes/wx_send.py", txt[:2800], "--raw", "--src", "live_digest"], cwd=ROOT,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:   # noqa: BLE001
                pass
            left = [x for x in left if x not in ready]
        sleep(5)


def chunks(txt, cap=2800):
    """按"空行 / 编号线开头"切块再拼, 每块 ≤ cap; 单条线超 cap 硬切"""
    blocks, cur = [], []
    for l in txt.split("\n"):
        if re.match(r"^\d+\. ", l) and cur:
            blocks.append("\n".join(cur))
            cur = []
        cur.append(l)
    blocks.append("\n".join(cur))
    out, buf = [], ""
    for b in blocks:
        while len(b) > cap:
            out.append(b[:cap])
            b = b[cap:]
        if buf and len(buf) + 1 + len(b) > cap:
            out.append(buf)
            buf = b
        else:
            buf = f"{buf}\n{b}" if buf else b
    if buf:
        out.append(buf)
    return [f"({i}/{len(out)}) {p}" if len(out) > 1 else p for i, p in enumerate(out, 1)]


# ---------- 留下名单(keep.py / hermes / 主会话都调这里) ----------
def resolve(D, names):
    """名字 → skill id: 认 skill id / 线号 live_xxx / 中文名(skill_names)/ 登记表 name / display / 前缀; 只在盘前名单里找。返回 (ids, 认不出的)"""
    import skill_names as SN
    sel = pack.live_sel(D)
    pre = sel.get("premarket") or []
    out, bad = [], []
    for n in names:
        n0 = re.sub(r"(skill|的线|线|号)$", "", n.strip(), flags=re.I).strip()
        if not n0:
            continue
        if n0.isdigit():   # 10/25 用户: 按盘前汇总里的编号(1、3、6)留下 / 暂停 / 恢复
            k = int(n0)
            if 1 <= k <= len(pre):
                out.append(pre[k - 1])
            else:
                bad.append(n)
            continue
        hit = [s for s in pre if n0 in (s, f"live_{s}", SN.cn(s))]
        if not hit:
            hit = [s for s in pre if SN.cn(s).startswith(n0) or n0.startswith(SN.cn(s)) or s.startswith(n0.lower())]
        if len(hit) == 1:
            out.append(hit[0])
        else:
            bad.append(n)
    return list(dict.fromkeys(out)), bad


def set_keep(D, ids, how="set"):
    """how: set = 只留这几位 / add = 加回 / drop = 收束掉 / reset = 清空(回到默认); 写 selected_mentors.json keep + active; 新留下的线写 KICK 立刻重想一次"""
    import mentor_select as MS
    sel = pack.live_sel(D)
    old = set(pack.keep_of(D))
    cur = set(sel["keep"]) if sel.get("keep") is not None else old   # 全部收束 = 空名单(不是回到默认)
    new = {"set": set(ids), "add": cur | set(ids), "drop": cur - set(ids), "reset": None}[how]
    pre = sel.get("premarket") or []
    sel["keep"] = [x for x in pre if x in new] if new is not None else None
    sel["active"] = sel["keep"] if sel["keep"] is not None else pre
    sel.setdefault("keep_log", []).append({"t": dt.datetime.now().isoformat(timespec="seconds"), "how": how, "ids": list(ids), "keep": sel["keep"]})
    f = MS.path(D)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(sel, ensure_ascii=False, indent=1), encoding="utf-8")
    now_keep = set(pack.keep_of(D))
    late = dt.datetime.now().strftime("%H:%M:%S") >= (pack.flag("LIVE_KEEP_AT", "09:19:00") or "09:19:00")
    for s in now_keep - old if late else []:   # 09:19 后加回来的线: 叫它按现在的盘面重想一次(休眠期间没想过)
        d = ROOT / "results" / "_live" / D / f"live_{s}"
        if d.exists():
            (d / "KICK").write_text("用户把这条线加回实盘线(之前休眠), 按现在的盘面重新给计划", encoding="utf-8")
    return sel["keep"], sorted(now_keep - old), sorted(old - now_keep)
