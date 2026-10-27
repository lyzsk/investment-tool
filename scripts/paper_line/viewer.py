# -*- coding: utf-8 -*-
"""viewer.py — paper v3 当日交互式回看页(10/24 用户令: 一个 HTML 看清每一步的例子 / 耗时 / 花费, 拿来参考设计实盘线; 零 token)

读 results/_live/<日>/v3_*/(versions/*/ 每一版的输入输出文件 + timing.json、events.jsonl、state.json、actions.jsonl、summary.md)
   + downloads/market/<日>/kline_minute.jsonl(分时) + tzzb_record(导师真人当天逐笔) + scripts/dfcf/snapshots/<日>_成交_*.txt(你的实盘, 可选)
出 results/inv-stock/paper_line/viewer_<日>.html(单文件, 浏览器直接打开; 文本 gzip+base64 内嵌、点开才解压; results/ 不进 git)
花费: 实际 = timing.json 的 usd(当天中转站 Claude 价); 预估 = 按 K3 API 价重算(输入 ¥20 / 输出 ¥100 / 缓存命中 ¥2 / 缓存写入 ¥20 每百万 token),
      没有 token 明细的步骤(03 多空分叉)按当天"K3 ¥ / 实际 $"整体比例估, 页面上标"估"
10/24 B 版(viewer_extra.py): 每张挂单的结局(复用 replay_report.order_audit) + 之后走势 / 排队等待 vs 链计算 / 每分钟 token 对照 K3 TPM / 导师真人对照(mentor_day) / 缓存保温体检 / 瘦身计算器;
      自测: scripts/venv/Scripts/python.exe -X utf8 scripts/paper_line/viewer_check.py [--date 2026-10-23]
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/paper_line/viewer.py [--date 2026-10-23] [--no-user]
"""
import argparse
import base64
import glob
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import line_dirs as LDS   # noqa: E402  10/25 账本目录命名(live_<skill> / paper_<id>)
sys.path[:0] = [str(ROOT / "scripts" / "backfill_bilibili"), str(Path(__file__).resolve().parent)]
K3 = {"in": 20.0, "out": 100.0, "cache_read": 2.0, "cache_write": 20.0}   # 元 / 百万 token(用户 10/23 晚给的价)
FILES = ["00_boot_msg.md", "00_trigger_msg.md", "01_facts.md", "01.md", "02.md", "02.json", "03_ask.md", "03.md", "03.json", "03_bull.md", "03_bear.md", "04_ask.md", "04.md", "04.json",
         "04_gate_ask.md", "04_gate.md", "05.md", "05_mech.json", "06_fresh.md", "06_ask.md", "06.md", "06.json", "06_evidence.md", "06_finish.md", "q_results.md"]   # 10/25: 实盘线每步提问原文(*_ask.md)+ ask 查询结果
NOISY = {"指数事件(只记)", "剪刀差事件(只记)", "未推微信", "事实包", "曲线图失败"}


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:   # noqa: BLE001
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


def gz(text):
    return base64.b64encode(gzip.compress(text.encode("utf-8"), 9)).decode("ascii")


def k3(s):
    if not any(k in s for k in K3):
        return None
    return sum((s.get(k) or 0) / 1e6 * v for k, v in K3.items())


def trade_audit(bdir, trades, ev):
    """10/26 用户: 回看页里逐笔人工审 BS 点的来源和触发 —— 成交 → 哪一版 chain(规则 key = 版本号:代码:规则 id)→ 这版为什么被叫醒 → 04 对这只票的结论 → 06 这条规则原文 → 执行器怎么撮合(守卫改单 / 条件单)"""
    vdirs = sorted(bdir.glob("versions/*"))
    out = []
    for t in trades:
        key = str(t.get("rule") or "")
        parts = key.split(":")
        vi = int(parts[0]) if parts and parts[0].isdigit() else None
        vd = vdirs[vi - 1] if vi and 0 < vi <= len(vdirs) else None
        a = {"t": t.get("t"), "side": t.get("side"), "code": t.get("code"), "name": t.get("name"), "qty": t.get("qty"), "px": t.get("px"), "rule": key, "cond": t.get("cond"),
             "ver": vd.name if vd else None}
        if vd:
            tm = jl(vd / "timing.json", {}) or {}
            a["why_wake"] = tm.get("why")
            a["chain_start"] = tm.get("start")
            j4 = jl(vd / "04.json", {}) or {}
            for c in (j4.get("picks") or j4.get("codes") or []):
                if isinstance(c, dict) and str(c.get("code")) == str(t.get("code")):
                    a["pick04"] = {k: c.get(k) for k in ("action", "why", "default", "checked", "rebut") if c.get(k)}
                    break
            j6 = jl(vd / "06.json", {}) or {}
            for c in j6.get("codes") or []:
                if str(c.get("code")) == str(t.get("code")):
                    rid = parts[2] if len(parts) > 2 else None
                    r = next((r for r in c.get("rules") or [] if r.get("id") == rid), None)
                    if r:
                        a["rule06"] = {k: v for k, v in r.items() if not str(k).startswith("_")}
                    a["kline06"] = c.get("kline")
                    break
            a["view06"] = str(j6.get("view") or "")[:300]
        tt = str(t.get("t") or "")
        a["exec"] = [e for e in ev if str(t.get("code")) in json.dumps(e, ensure_ascii=False) and e.get("kind") in ("守卫: 挂价偏离现价, 改条件单", "条件单成交", "06 自动修", "竞价单挂出", "未见成交剔买单", "板事件叫醒")
                     and (not tt or abs(_sec(e.get("t")) - _sec(tt)) <= 600)][:6]
        out.append(a)
    return out


def _sec(t):
    try:
        h, m, s = (int(x) for x in str(t)[:8].split(":"))
        return h * 3600 + m * 60 + s
    except ValueError:
        return 0


def book(bdir, line):
    vers = []
    for vd in sorted(bdir.glob("versions/*")):
        t = jl(vd / "timing.json", {}) or {}
        steps = []
        for name, s in (t.get("steps") or {}).items():
            steps.append({"name": name, "secs": s.get("secs"), "usd": round(s.get("usd") or 0, 4), "ok": s.get("ok"), "err": (s.get("err") or "")[:200],
                          "cr": s.get("cache_read"), "cw": s.get("cache_write"), "in": s.get("in"), "out": s.get("out"), "k3": k3(s)})
        files = {}
        for f in FILES:
            p = vd / f
            if p.exists():
                files[f] = gz(p.read_text(encoding="utf-8", errors="replace"))
        s06 = jl(vd / "06.json", {}) or {}
        orders = [{"code": c.get("code"), "name": c.get("name"), **{k: r.get(k) for k in ("id", "side", "op", "px", "qty", "auction", "type", "after", "why")}}
                  for c in s06.get("codes") or [] for r in c.get("rules") or []]
        hhmmss = vd.name.split("_")[1] if "_" in vd.name else ""
        vers.append({"dir": vd.name, "trig": f"{hhmmss[:2]}:{hhmmss[2:4]}:{hhmmss[4:6]}", "start": t.get("start"), "why": t.get("why"), "boot": t.get("boot"),
                     "total": t.get("total"), "result": t.get("result"), "usd": round(t.get("usd") or sum(x["usd"] for x in steps), 4),
                     "steps": steps, "files": files, "orders": orders, "view": str(s06.get("view") or "")[:400],
                     "stop": bool((s06.get("rest_of_day") or {}).get("stop")) if isinstance(s06.get("rest_of_day"), dict) else False,
                     "sizes": {f: (vd / f).stat().st_size for f in FILES if (vd / f).exists()}})
    ev = jlines(bdir / "events.jsonl")
    keep = [e for e in ev if e.get("kind") == "缓存保温"]
    st = jl(bdir / "state.json", {}) or {}
    summ = (bdir / "summary.md").read_text(encoding="utf-8").split("\n")[0] if (bdir / "summary.md").exists() else ""
    m = re.search(r"模拟账 (\d+)\(开盘 (\d+), ([+-][\d.]+)%\)", summ)
    audit = trade_audit(bdir, st.get("trades") or [], ev)
    return {"id": line["id"], "name": line.get("name"), "mode": line.get("mode"), "kind": line.get("kind"), "skill": line.get("skill"), "audit": audit,
            "nav0": int(m.group(2)) if m else None, "nav1": int(m.group(1)) if m else None, "ret": float(m.group(3)) if m else None,
            "trades": st.get("trades") or [], "positions": st.get("positions") or {},
            "events": [e for e in ev if e.get("kind") not in NOISY],
            "keep": [{"t": e.get("t"), "secs": e.get("secs"), "usd": round(e.get("usd") or 0, 4), "k3": k3(e), "cr": e.get("cache_read"), "cw": e.get("cache_write")} for e in keep],
            "versions": vers}


def charts(D, codes):
    out = {}
    for l in (ROOT / "downloads" / "market" / D / "kline_minute.jsonl").open(encoding="utf-8"):
        x = json.loads(l)
        c = x.get("symbol", "")[2:]
        if c in codes:
            out.setdefault(c, []).append([x["barTime"][11:16], x["close"], x["high"], x["low"]])
    return {c: sorted(v) for c, v in out.items()}


def mentor_trades(D, skills):
    try:
        import manual_backfill as mb
        c = mb.db().cursor()
        c.execute("select ledger, date_format(record_time,'%%H:%%i:%%s'), stock_code, stock_name, side, price, qty from tzzb_record "
                  "where record_type='bs_leg' and is_deleted=0 and date(record_time)=%s order by record_time", (D,))
        out = {}
        for led, t, code, nm, side, px, q in c.fetchall():
            if led in skills:
                out.setdefault(led, []).append([t, code, nm, "BUY" if "买" in (side or "") else "SELL", float(px or 0), float(q or 0)])
        return out
    except Exception as e:   # noqa: BLE001
        print("导师逐笔读取失败:", e)
        return {}


def user_trades(D):
    out = []
    for f in (ROOT / "scripts" / "dfcf" / "snapshots").glob(f"{D}_成交_*.txt"):
        for l in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"(\d\d:\d\d:\d\d)(?:~\d\d)? (\d{6}) (\S+) (买|卖) (\S+) ([\d.]+)", l)
            if m and m.group(2) != "204001":
                g = m.group(5)
                q = int(g.split("(=")[1].rstrip(")")) if "(=" in g else int(g)
                out.append([m.group(1), m.group(2), m.group(3), "BUY" if m.group(4) == "买" else "SELL", float(m.group(6)), q])
    return sorted(out)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-10-23")
    ap.add_argument("--no-user", action="store_true", help="不放你的实盘成交")
    ap.add_argument("--root", default="", help="账本根(默认 results/_live; 回放 = results/_replay/<标签>, 其下有 <日>/live_*)")
    a = ap.parse_args()
    D = a.date
    lines = {x["id"]: x for x in (jl(ROOT / "scripts" / "paper_line" / "lines.json", {}) or {}).get("lines") or []}
    base = (ROOT / a.root / D if (ROOT / a.root / D).is_dir() else ROOT / a.root) if a.root else ROOT / "results" / "_live" / D
    import skill_names as SN
    for d in sorted(base.glob("live_*")):   # 10/25: 实盘线线号 live_<skill>, 不在 lines.json 里
        lines.setdefault(d.name, {"id": d.name, "name": SN.cn(d.name[5:]) + "skill", "mode": "watch", "kind": "mimic", "skill": d.name[5:], "live": True})
    B = [book(base / LDS.ldir(lid), ln) for lid, ln in lines.items() if (base / LDS.ldir(lid)).exists()]
    # 没有 token 明细的步骤: 按当天整体 K3¥ / $ 比例估
    pairs = [(s["k3"], s["usd"]) for b in B for v in b["versions"] for s in v["steps"] if s["k3"] is not None and s["usd"]]
    ratio = sum(x for x, _ in pairs) / max(1e-9, sum(y for _, y in pairs))
    for b in B:
        for v in b["versions"]:
            for s in v["steps"]:
                if s["k3"] is None:
                    s["k3"], s["est"] = s["usd"] * ratio, True
            v["k3"] = sum(s["k3"] or 0 for s in v["steps"])
        for k in b["keep"]:
            if k["k3"] is None:
                k["k3"] = k["usd"] * ratio
    codes = set()
    for b in B:
        codes |= {t["code"] for t in b["trades"]} | set(b["positions"]) | {o["code"] for v in b["versions"] for o in v["orders"] if o.get("code")}
    U = [] if a.no_user else user_trades(D)
    codes |= {x[1] for x in U}
    M = mentor_trades(D, {b["skill"] for b in B})
    for v in M.values():
        codes |= {x[1] for x in v}
    # 10/24 B 版附加: 挂单结局 / 排队等待 / 每分钟 token / 导师对照 / 保温体检 / 瘦身计算器默认值(viewer_extra.py)
    import viewer_extra as X
    import replay_report as rr
    bars, tape, probs = charts(D, codes), rr.load_tape(D), []
    for b in B:
        bdir = base / LDS.ldir(b["id"])
        probs += X.order_fates(bdir, b, tape, bars)
        probs += X.queue_waits(b, jlines(bdir / "events.jsonl"))
        probs += X.keep_check(b, ratio)
        b["mentor_day"] = X.mentor_block(b, M, D)
        probs += [f"{b['id']} {v['dir']} 缺 timing.json(没有开始时刻 / 耗时)" for v in b["versions"] if not v.get("start")]
    data = {"date": D, "k3": K3, "ratio": ratio, "books": B, "charts": bars, "mentor": M, "user": U,
            "tpm": X.tpm(B), "limits": {"t2": {"tpm": 3e6, "rpm": 100, "conc": 40}, "t4": {"tpm": 4e6, "rpm": 200, "conc": 60}},
            "calc": X.calc_defaults(B), "probs": probs, "keep_design": X.KEEP_DESIGN_USD}
    out = (base / "review" / "viewer.html") if a.root else ROOT / "results" / "inv-stock" / "paper_line" / f"viewer_{D}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    html = (Path(__file__).parent / "viewer_tpl.html").read_text(encoding="utf-8").replace("/*__DATA__*/", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    out.write_text(html, encoding="utf-8")
    nv = sum(len(b["versions"]) for b in B)
    print(f"→ {out}  ({out.stat().st_size / 1e6:.1f} MB; {len(B)} 本 / {nv} 版 / 分时 {len(data['charts'])} 只 / 导师逐笔 {sum(len(v) for v in M.values())} / 你的成交 {len(U)}; K3¥/$ = {ratio:.2f})")
    T = data["tpm"]
    pk = {m: max(x + y for x, y in zip(T[m]["all"]["tok"], T[m]["all"]["est"])) / 1e6 for m in ("spread", "start")}
    print(f"峰值(含 03 估): 每分钟 token(摊) {pk['spread']:.2f}M / (按发出分钟) {pk['start']:.2f}M; 每分钟请求 {T['rpm']['max']} @{T['rpm']['at']}; 并发 {T['conc']['max']} @{T['conc']['at']}")
    print(f"数据问题 {len(probs)} 条:" + "".join(f"\n- {p}" for p in probs))


if __name__ == "__main__":
    main()
