# -*- coding: utf-8 -*-
"""replay_report.py — paper v3 放量彩排报告(10/22 晚用户令: 彩排结果做成 HTML, "能看得非常清晰, 哪里出现问题了")

读 results/_replay/<日>/: replay_meta.json(真实耗时 / 队列日志 / 报错) + 每本账 v3_<线>/(versions/*/timing.json 每次链的步骤耗时和花费、events.jsonl、state.json、nav.csv) + wx.jsonl + memory/
出: results/_replay/<日>/report.html + 打印一段纯文本摘要(写 TODO / 推微信用)
自动标红的问题: 链失败 / 步骤报错 · 单次链 > 10 分钟 · 06 规则没写依据 · 排队等 > 2 分钟 · 尾盘版 14:56:30 后才出 · 没写本线记忆 · 回放脚本报错
尾盘版最晚开跑时刻 = 14:57:00 − (各本尾盘版 排队 + 链耗时 的最大值) − 60 秒余量
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/paper_line/replay_report.py [--date 2026-10-22]
"""
import argparse
import datetime as dt
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import line_dirs as LDS   # noqa: E402  10/25 账本目录命名(live_<skill> / paper_<id>)
CHAIN_WARN_S, WAIT_WARN_S, TAIL_DEADLINE = 600, 120, "14:56:30"
QTY = "qty"


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def jlines(p):
    out = []
    try:
        for l in Path(p).read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(l))
            except ValueError:
                pass
    except OSError:
        pass
    return out


def sec(hms):
    h, m, s = (int(x) for x in str(hms)[:8].split(":"))
    return h * 3600 + m * 60 + s


def hms(x):
    x = int(x)
    return f"{x // 3600:02d}:{x % 3600 // 60:02d}:{x % 60:02d}"


def book(d, lid, memdir):
    ev = jlines(d / "events.jsonl")
    st = jl(d / "state.json", {}) or {}
    navl = (d / "nav.csv").read_text(encoding="utf-8").strip().splitlines() if (d / "nav.csv").exists() else []
    nav = float(navl[-1].split(",")[2]) if navl else None
    queued = [e for e in ev if e.get("kind") == "排队叫醒"]
    vers, probs = [], []
    for i, vd in enumerate(sorted((d / "versions").glob("*"))):
        t = jl(vd / "timing.json")
        if not t:
            continue
        start = t.get("start", "")
        q = [e for e in queued if e["t"] <= start]
        wait = sec(start) - sec(q[-1]["t"]) if q and start else 0
        steps = t.get("steps") or {}
        errs = [f"{k}: {v.get('err')}" for k, v in steps.items() if v.get("err") or not v.get("ok", True)]
        end = hms(sec(start) + (t.get("total") or 0)) if start else ""
        v = {"name": vd.name, "start": start, "end": end, "why": t.get("why", ""), "boot": t.get("boot"), "wait": wait, "total": t.get("total") or 0,
             "usd": t.get("usd") or 0, "result": t.get("result"), "steps": {k: (v.get("secs"), v.get("usd"), v.get("cache_read"), v.get("cache_write"), v.get("out")) for k, v in steps.items()},
             "kb": (t.get("pack") or {}).get("kb"), "noev": t.get("no_evidence") or [], "errs": errs, "tail": "尾盘" in t.get("why", "")}
        vers.append(v)
        tag = f"{lid} {vd.name}({start} {v['why'][:30]})"
        if v["result"] != "ok" or errs:
            probs.append(("红", f"{tag} 链没跑通: {v['result']} {'; '.join(errs)[:200]}"))
        if v["total"] > CHAIN_WARN_S:
            probs.append(("黄", f"{tag} 单次链 {v['total']:.0f} 秒(> {CHAIN_WARN_S})"))
        if wait > WAIT_WARN_S:
            probs.append(("黄", f"{tag} 排队等了 {wait} 秒"))
        if v["noev"]:
            probs.append(("黄", f"{tag} 06 规则没写依据: {v['noev'][:3]}"))
        if v["tail"] and end and end > TAIL_DEADLINE:
            probs.append(("红", f"{tag} 尾盘版 {end} 才出(要在 {TAIL_DEADLINE} 前)"))
    if not vers or not vers[0]["boot"] or vers[0]["result"] != "ok":
        probs.append(("红", f"{lid} 09:00 启动没成功"))
    if not (memdir / f"{lid}.md").exists():
        probs.append(("红", f"{lid} 收盘没写本线记忆"))
    nomoney = [e for e in ev if e.get("kind") == "规则命中但没钱/没可卖"]
    trades = st.get("trades") or []
    return {"id": lid, "vers": vers, "probs": probs, "nav": nav, "trades": trades, "nomoney": len(nomoney), "usd": sum(v["usd"] for v in vers),
            "positions": st.get("positions") or {}, "events": ev}


def bar(x, mx, w=160):
    return f'<span class="bar" style="width:{int(w * x / mx) if mx else 0}px"></span>'


def load_tape(D):
    """回放用的 3 秒盘口: {代码: [(秒, 价, 买一, 卖一)]}(只要有价的行)"""
    import gzip
    f = ROOT / "downloads" / "market" / D / "book_snap.jsonl"
    op, src = (open, f) if f.exists() else (gzip.open, f.with_suffix(".jsonl.gz"))
    T = {}
    try:
        with op(src, "rt", encoding="utf-8") as fh:
            for l in fh:
                try:
                    r = json.loads(l)
                except ValueError:
                    continue
                if r.get("p"):
                    T.setdefault(str(r["s"])[2:], []).append((r.get("t", ""), float(r["p"]), ((r.get("b") or [[0]])[0][0] or 0), ((r.get("k") or [[0]])[0][0] or 0)))
    except OSError:
        pass
    for v in T.values():
        v.sort()
    return T


def order_audit(bdir, tape, trades):
    """每一版的链路(为什么叫醒 → 04 选了什么 → 06 原文摘要)+ 每张挂单成没成交、没成交的原因(对照这一版有效期内的 3 秒盘口)"""
    vers = sorted((bdir / "versions").glob("*"))
    strs = {int(p.name[:2]): p for p in (bdir / "strategies").glob("*.json") if p.name[:2].isdigit()}
    times = sorted((k, p.stem.split("_")[-1]) for k, p in strs.items())
    filled = {str(t.get("rule")) for t in trades}
    out = []
    for vd in vers:
        n = int(vd.name[:2]) if vd.name[:2].isdigit() else None
        tm = jl(vd / "timing.json", {}) or {}
        sp = strs.get(n)
        S = (jl(sp, {}) or {}) if sp else {}
        st = S.get("strategy") or {}
        t0 = sp.stem.split("_")[-1] if sp else ""
        t0 = f"{t0[:2]}:{t0[2:]}:00" if t0 else tm.get("start", "")
        nxt = next((f"{h[:2]}:{h[2:]}:00" for k, h in times if n is not None and k > n), "15:00:00")
        j4 = jl(vd / "04.json", {}) or {}
        picks = "; ".join(f"{x.get('code')} {x.get('action')} {x.get('target_pct')}% {str(x.get('play') or '')[:16]}" for x in (j4.get("picks") or []) if isinstance(x, dict)) or "(无)"
        r6 = (vd / "06.md").read_text(encoding="utf-8", errors="replace")[:1500] if (vd / "06.md").exists() else "(没有 06)"
        rows = []
        for x in st.get("codes") or []:
            c = x["code"]
            seg = [r for r in tape.get(c, []) if t0 <= r[0] < nxt]
            for r in x.get("rules") or []:
                key = f"{n}:{c}:{r['id']}"
                if key in filled:
                    why = "✅ 成交"
                elif t0 < "09:20:00" and not st.get("auc_submitted"):
                    why = "09:20 前的草稿版: 竞价单不挂、不撮合(09:20 竞价复核那版才挂)"
                elif r.get("type") == "board_dip":
                    why = "炸板接单: 有效期内没出现'封过板 → 开板 → 落在接的区间'"
                elif not tape.get(c):
                    why = "⚠️ 3 秒盘口里全天没有这只票(彩排数据缺口; 实盘有新浪每 10 秒补价)"
                elif not seg and tape[c][0][0] >= nxt:
                    why = f"⚠️ 这只票 {tape[c][0][0][:5]} 才进 3 秒名单, 这一版有效期内彩排看不到它的价格(数据缺口; 实盘有新浪补价)"
                elif not seg:
                    why = f"这一版有效期({t0[:5]}~{nxt[:5]})内没有盘口数据"
                elif r.get("after") and not any(str(t.get("rule")) == f"{n}:{c}:{r['after']}" for t in trades):
                    why = f"前置单 {r['after']} 没成交, 这张不生效"
                else:
                    lo, hi = min(s[1] for s in seg), max(s[1] for s in seg)
                    if r["side"] == "BUY":
                        if lo > r["px"]:
                            why = f"价格没下来: 有效期内最低 {lo} > 买价 {r['px']}(差 {(lo / r['px'] - 1) * 100:.2f}%)"
                        elif r.get("rest") and lo == r["px"]:
                            why = f"只碰到买价 {r['px']} 没穿过, 排队量没排到"
                        elif all(s[3] == 0 for s in seg if s[1] <= r["px"]):
                            why = "到价时卖一空(涨停封死), 买不进"
                        else:
                            why = f"到过买价(最低 {lo})但没成交 → 现金不够 / 已被别的单用掉 / 版本切换, 要细查"
                    else:
                        if hi < r["px"]:
                            why = f"价格没上去: 有效期内最高 {hi} < 卖价 {r['px']}(差 {(r['px'] / hi - 1) * 100:.2f}%)"
                        elif r.get("rest") and hi == r["px"]:
                            why = f"只碰到卖价 {r['px']} 没穿过, 排队量没排到"
                        else:
                            why = f"到过卖价(最高 {hi})但没成交 → 可卖不够(T+1) / 版本切换, 要细查"
                rows.append(f"<tr><td>{c} {html.escape(str(x.get('name') or ''))}</td><td>{r['side']} {r.get('op')} {r['px']} × {r['qty']}{' 竞价' if r.get('auction') else ''}{' 排队' if r.get('rest') else ''}{' ' + r['type'] if r.get('type') else ''}</td>"
                            f"<td>{html.escape(str(r.get('why') or '')[:90])}</td><td>{html.escape(why)}</td></tr>")
        out.append(f'<details><summary>{vd.name} · {html.escape(str(tm.get("why", ""))[:50])} · 有效 {t0[:5]}~{nxt[:5]} · 挂单 {len(rows)} 张</summary>'
                   f'<div class="box">04 选了: {html.escape(picks)}\n看法: {html.escape(str(st.get("view") or "")[:300])}\n剔除: {html.escape("; ".join(S.get("dropped") or []) or "无")}</div>'
                   f'<table><tr><th>票</th><th>挂单</th><th>理由</th><th>成没成交 / 为什么</th></tr>{"".join(rows) or "<tr><td colspan=4>这一版没挂单(只用区间 / 叫醒条件)</td></tr>"}</table>'
                   f'<details><summary>06 原文(前 1500 字)</summary><div class="box">{html.escape(r6)}</div></details></details>')
    return "".join(out)


def mentor_day(lid, D):
    """拟人线: 导师真人在 D 当天的全部成交 + 收盘持仓(pack.mentor_t1 取"下一个交易日的 T−1" = D); 决策T 线返回空"""
    ln = next((x for x in (jl(ROOT / "scripts" / "paper_line" / "lines.json", {}) or {}).get("lines") or [] if x["id"] == lid), None)
    if not ln or ln.get("kind") != "mimic":
        return ""
    try:
        sys.path[:0] = [str(ROOT / "scripts" / "paper_line"), str(ROOT / "scripts" / "paper_line" / "tools")]
        import pack
        d = dt.date.fromisoformat(D) + dt.timedelta(days=1)
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        return pack.mentor_t1(ln["skill"], d.isoformat())
    except Exception as e:   # noqa: BLE001
        return f"(导师当天操作取不到: {e!r})"[:200]


def cost_vs_v1(B, names):
    """10/23 用户令: 盯 v3(1 小时缓存 + 保温)和 v1 的每线花费差。v1 = scripts/dfcf/paper/token_log.csv 10/13~10/20 实盘日(不含回放), 每线每天(含 07 复盘)
    彩排只重放 09:00~11:30 + 尾盘, 不是整天 → 另给"按叫醒次数外推到整天"的粗估(下午按上午叫醒次数的 80% 算)"""
    import csv
    import collections
    day = collections.defaultdict(lambda: collections.defaultdict(float))
    try:
        for r in csv.DictReader(open(ROOT / "scripts" / "dfcf" / "paper" / "token_log.csv", encoding="utf-8")):
            if "20261013" <= r["date"] <= "20261020" and r.get("asof") in (None, "", "0") and r.get("skill"):
                day[r["date"]][r["skill"]] += float(r["cost_usd"] or 0)
    except OSError:
        return "v1 花费对照: token_log.csv 读不到"
    per = [x for v in day.values() for x in v.values()]
    v1avg = sum(per) / len(per) if per else 0
    skill_of = {x["id"]: x.get("skill") for x in (jl(ROOT / "scripts" / "paper_line" / "lines.json", {}) or {}).get("lines") or []}
    rows = []
    for b in B:
        n_wake = len([v for v in b["vers"] if not v["boot"]])
        boot = sum(v["usd"] for v in b["vers"] if v["boot"])
        wake = (b["usd"] - boot) / n_wake if n_wake else 0
        full = boot + wake * n_wake * 1.8   # 下午 ≈ 上午叫醒次数的 80%
        sk = skill_of.get(b["id"])
        v1 = [day[d][sk] for d in day if sk in day[d]]
        rows.append(f"{b['id']} 彩排 ${b['usd']:.1f}(启动 ${boot:.1f} + 叫醒 {n_wake} 次 × ${wake:.2f}) → 整天粗估 ${full:.0f}" + (f" | v1 同导师 ${sum(v1) / len(v1):.1f}/天" if v1 else ""))
    return f"花费对照 v1(10/13~10/20 实盘, 平均每线每天 ${v1avg:.1f}, 含 07 复盘):\n" + "\n".join("  " + r for r in rows)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-10-22")
    ap.add_argument("--dir", default="", help="回放输出目录名(默认 = --date; 桩回放 = <日>_stub, 10/23 起分开存)")
    a = ap.parse_args()
    base = ROOT / "results" / "_replay" / (a.dir or a.date)
    meta = jl(base / "replay_meta.json", {}) or {}
    lines = (jl(ROOT / "scripts" / "paper_line" / "lines.json", {}) or {}).get("lines") or []
    names = {x["id"]: (x.get("name", ""), x.get("mode", ""), x.get("kind", "")) for x in lines}
    B = [book(base / a.date / LDS.ldir(lid), lid, base / "memory") for lid in meta.get("lines") or [] if (base / a.date / LDS.ldir(lid)).exists()]
    probs = [p for b in B for p in b["probs"]] + [("红", f"回放脚本报错 {lid}: {e[-200:]}") for lid, e in meta.get("errors") or []]
    usd = sum(b["usd"] for b in B)
    # 队列: 同时在想的最大数 + 时间线
    busy, mx_busy = 0, 0
    for g in meta.get("gate_log") or []:
        busy = g[4] if len(g) > 4 else busy
        mx_busy = max(mx_busy, busy)
    tails = [(b["id"], v) for b in B for v in b["vers"] if v["tail"]]
    worst_tail = max((v["wait"] + v["total"] for _, v in tails), default=0)
    latest = hms(sec("14:57:00") - worst_tail - 60) if tails else "—"
    chain_all = [v["total"] for b in B for v in b["vers"] if not v["boot"]]
    boots = [v["total"] for b in B for v in b["vers"] if v["boot"]]
    q = lambda xs, p: sorted(xs)[min(len(xs) - 1, int(len(xs) * p))] if xs else 0   # noqa: E731
    red = [p for p in probs if p[0] == "红"]
    text = [f"paper v3 放量彩排({a.date} 行情重放 09:00~11:30 + 14:51~15:00, {len(B)} 本账真调模型)",
            f"真实耗时 {meta.get('real_secs', 0) / 60:.0f} 分钟; 模型花费合计 ${usd:.2f}; 同时在想最多 {mx_busy} 个(队列上限 {meta.get('gate_n')})",
            f"启动链 中位 {q(boots, .5):.0f} 秒 / 最慢 {max(boots, default=0):.0f} 秒; 盘中链 中位 {q(chain_all, .5):.0f} 秒 / P90 {q(chain_all, .9):.0f} 秒 / 最慢 {max(chain_all, default=0):.0f} 秒",
            f"尾盘版: 最慢一本 排队+链 {worst_tail:.0f} 秒 → 尾盘版最晚开跑约 {latest}(现设 14:51)",
            f"问题: 红 {len(red)} 条 / 黄 {len(probs) - len(red)} 条" + ("".join(f"\n- {p[1]}" for p in red[:8]) if red else "")]
    text.insert(2, cost_vs_v1(B, names))
    rows = []
    for b in B:
        nm, mode, kind = names.get(b["id"], ("", "", ""))
        st = 100000 if kind != "dt" else 10000
        ret = (b["nav"] / st - 1) * 100 if b["nav"] else None
        nr = len([v for v in b["vers"] if not v["boot"]])
        tot = [v["total"] for v in b["vers"] if not v["boot"]]
        flag = "red" if any(p[0] == "红" for p in b["probs"]) else ("yel" if b["probs"] else "")
        rows.append(f'<tr class="{flag}"><td>{html.escape(b["id"])}</td><td>{html.escape(nm)}</td><td>{mode}</td><td>{"" if ret is None else f"{ret:+.2f}%"}</td><td>{len(b["trades"])}</td>'
                    f'<td>{nr}</td><td>{q(tot, .5):.0f} / {max(tot, default=0):.0f}</td><td>${b["usd"]:.2f}</td><td>{b["nomoney"]}</td><td>{len(b["probs"])}</td>'
                    f'<td>{html.escape(", ".join(f"{c}×{p.get(QTY)}" for c, p in b["positions"].items()))}</td></tr>')
    det, tape = [], load_tape(a.date)
    mxt = max((v["total"] for b in B for v in b["vers"]), default=1)
    for b in B:
        vr = []
        for v in b["vers"]:
            stp = " · ".join(f"{k} {s[0] or 0:.0f}s ${s[1] or 0:.2f}" for k, s in v["steps"].items())
            cls = "red" if v["errs"] or v["result"] != "ok" else ""
            vr.append(f'<tr class="{cls}"><td>{v["name"]}</td><td>{v["start"]}→{v["end"]}</td><td>{html.escape(v["why"][:60])}</td><td>{v["wait"]}s</td>'
                      f'<td>{bar(v["total"], mxt)} {v["total"]:.0f}s</td><td>{stp}</td><td>${v["usd"]:.2f}</td><td>{v["kb"] or ""}</td>'
                      f'<td>{html.escape("; ".join(v["errs"])[:120])}{"; 无依据 " + str(len(v["noev"])) if v["noev"] else ""}</td></tr>')
        tr = "".join(f'<tr><td>{t.get("t")}</td><td>{t.get("side")}</td><td>{t.get("code")} {html.escape(str(t.get("name") or ""))}</td><td>{t.get("px")}</td><td>{t.get("qty")}</td>'
                     f'<td>{html.escape(str(t.get("why") or "")[:80])}</td></tr>' for t in b["trades"])
        pr = "".join(f'<li class="{"r" if p[0] == "红" else "y"}">{html.escape(p[1])}</li>' for p in b["probs"]) or "<li>无</li>"
        mt = mentor_day(b["id"], a.date)
        oa = order_audit(base / a.date / LDS.ldir(b["id"]), tape, b["trades"])
        det.append(f'<details{" open" if b["probs"] else ""}><summary><b>{b["id"]}</b> {html.escape(names.get(b["id"], ("",))[0])} — 叫醒 {len(b["vers"])} 次, 成交 {len(b["trades"])} 笔, ${b["usd"]:.2f}, 问题 {len(b["probs"])}</summary>'
                   f'<ul>{pr}</ul><table><tr><th>版本</th><th>开始→出结果</th><th>为什么叫醒</th><th>排队</th><th>链耗时</th><th>各步</th><th>花费</th><th>材料KB</th><th>报错</th></tr>{"".join(vr)}</table>'
                   f'<h4>成交</h4><table><tr><th>时刻</th><th>方向</th><th>票</th><th>价</th><th>量</th><th>理由</th></tr>{tr or "<tr><td colspan=6>无</td></tr>"}</table>'
                   + f'<h4>链路 + 每张挂单成没成交(点开每一版)</h4>{oa}'
                   + (f'<h4>导师真人当天(对照; 彩排跳过了 11:30~14:50)</h4><div class="box">{html.escape(mt)}</div>' if mt else "") + '</details>')
    page = f"""<!doctype html><meta charset="utf-8"><title>paper v3 放量彩排 {a.date}</title>
<style>body{{font:14px/1.5 -apple-system,"Microsoft YaHei",sans-serif;margin:24px;color:#222}}table{{border-collapse:collapse;margin:8px 0}}td,th{{border:1px solid #ddd;padding:3px 8px;text-align:left;vertical-align:top}}
th{{background:#f4f4f4}}tr.red td{{background:#fde8e8}}tr.yel td{{background:#fff7e0}}li.r{{color:#b00}}li.y{{color:#a60}}.bar{{display:inline-block;height:9px;background:#5b8def;vertical-align:middle}}
.box{{background:#f7f9fc;border:1px solid #dde4ee;padding:10px 14px;white-space:pre-wrap}}details{{margin:10px 0;border:1px solid #e5e5e5;padding:6px 10px}}summary{{cursor:pointer}}</style>
<h2>paper v3 放量彩排 · {a.date} 行情重放</h2><div class="box">{html.escape(chr(10).join(text))}</div>
<h3>问题清单(红 = 明天会出事 / 黄 = 要留意)</h3><ul>{"".join(f'<li class="{"r" if p[0] == "红" else "y"}">{html.escape(p[1])}</li>' for p in sorted(probs, key=lambda p: p[0] != "红")) or "<li>无</li>"}</ul>
<h3>各本账</h3><table><tr><th>账</th><th>名</th><th>模式</th><th>收盘收益</th><th>成交</th><th>盘中叫醒</th><th>链耗时 中位/最慢 秒</th><th>花费</th><th>规则命中没钱</th><th>问题</th><th>收盘持仓</th></tr>{"".join(rows)}</table>
<h3>每本账逐次叫醒(点开看)</h3>{"".join(det)}
<p style="color:#888">生成 {dt.datetime.now():%Y-%m-%d %H:%M}; 口径见 scripts/paper_line/replay.py / replay_report.py。收益只是重放半天(午后 11:30~14:50 跳过), 不代表真实表现; 主要看流程有没有出事。</p>"""
    (base / "report.html").write_text(page, encoding="utf-8")
    print("\n".join(text))
    print("→", base / "report.html")


if __name__ == "__main__":
    main()
