# -*- coding: utf-8 -*-
"""auction_push.py — 09:25 竞价结果推送(10/27 用户令: "竞价确认后实时推送我的竞价结果"; "竞价一字板的要研究它的拓扑大簇和小簇, 09:25-09:30 推送, 关联票先进 3 秒盘口"; 零 token)

读: downloads/market/<D>/auction_live_open.json(collect_auction, 09:25:40 定稿) + results/_live/<D>/expect.json(明日预案) + watch_seed.json(种子池)
    + results/_live/<D>/live_*/strategies/*.json(盘前首跑 chain 最新一版) + downloads/market/<D−1>/topology.jsonl(拓扑邻居)
出: 一条微信(推送总线, 快车道) + results/_live/<D>/auction_result.md
   ① 预案簇: 明日聚焦题材 / 字辈 / 续板梯队, 每簇 竞价涨幅中位 + 竞价涨停几只 / 跌停几只 + 每只 13 档 + 未匹配(买 + / 卖 −)
   ② 竞价一字(涨停价撮合 + 买方未匹配): 每只的拓扑邻居前 3(大簇 = 同行业 / 小簇 = 联动最强的邻居)此刻竞价 → 邻居写进 collect_book_extra 的「竞价自动」块(3 秒盘口 60 秒内接上, 出信号才进盯盘池)
   ③ 三方对照: 每条实盘线盘前 chain 选的票 竞价落在哪一档、是不是预案里的
用法: python auction_push.py [--date D] [--dry]     (signals.py --run 在 09:25:45 后自动调一次; 也可手动)
不自信点: 「一字」只看 09:25 撮合价 = 涨停价, 没看封单金额; 拓扑邻居取 topology.jsonl 前 3, 是历史联动不是当天题材
"""
import argparse
import datetime as dt
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"
LIVE = ROOT / "results" / "_live"
EXTRA = ROOT / "scripts" / "temp" / "collect_book_extra.txt"
BEGIN, END = "# >>> 竞价自动(auction_push.py 生成, 别手改这段)", "# <<< 竞价自动"
for _p in ("skills_ver", "market", "hermes", "lib"):
    sys.path.insert(0, str(ROOT / "scripts" / _p))


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def band(code, pct):
    import open_bins as OB
    return OB.bin13(pct, OB.lim_of(code), code[:2] in ("11", "12"))


def lim_hit(code, s):
    """竞价撮合价是不是涨停价(差半个价位内)"""
    import a_rules as AR
    try:
        up, dn = AR.limit_prices(code, None, s["prev"])
    except Exception:   # noqa: BLE001
        lim = 0.2 if code[:3] in ("300", "301", "688", "689") else 0.1
        up, dn = round(s["prev"] * (1 + lim), 2), round(s["prev"] * (1 - lim), 2)
    px = (s.get("fin") or {}).get("px")
    if not px:
        return None
    return "涨停" if px >= up - 0.005 else "跌停" if px <= dn + 0.005 else None


def row(code, A, names):
    s = A.get(("sh" if code[:1] in ("6", "9", "5") or code[:2] == "11" else "sz") + code)
    if not s or not s.get("fin"):
        return None
    f = s["fin"]
    unm = f.get("unm")
    return {"code": code, "name": s.get("name") or names.get(code, code), "pct": f.get("pct"), "band": band(code, f.get("pct") or 0),
            "lim": lim_hit(code, s), "unm": unm, "d920": s.get("d_after920")}


def fmt(r):
    u = r.get("unm")
    us = "" if not u else (f" 未匹配买 {u / 100:.0f} 手" if u > 0 else f" 未匹配卖 {-u / 100:.0f} 手")
    return f"{r['name']} {r['pct']:+.2f}%({r['band']}){'🔒' + r['lim'] if r['lim'] else ''}{us}"


def build(D):
    A = (jl(MKT / D / "auction_live_open.json", {}) or {}).get("symbols") or {}
    if not A:
        return None, "auction_live_open.json 还没有"
    names = {k[2:]: v.get("name") for k, v in A.items()}
    L = [f"竞价结果 {D} 09:25(参考: 下单依据仍走盘前 chain / 盘中复核)"]
    idx = [f"{A[k]['name']} {A[k]['fin']['pct']:+.2f}%" for k in ("sh000001", "sz399001", "sz399006") if k in A and A[k].get("fin")]
    if idx:
        L.append("指数: " + " · ".join(idx))
    allr = [r for r in (row(k[2:], A, names) for k in A if k[2:3] in ("0", "3", "6") and k[:2] in ("sh", "sz") and not k[2:].startswith(("000001", "399"))) if r]
    ups, dns = [r for r in allr if r["lim"] == "涨停"], [r for r in allr if r["lim"] == "跌停"]
    pcts = [r["pct"] for r in allr if r["pct"] is not None]
    if pcts:
        L.append(f"采集 {len(allr)} 只: 竞价涨停 {len(ups)} / 跌停 {len(dns)} · 涨幅中位 {statistics.median(pcts):+.2f}% · 红 {sum(p > 0 for p in pcts)} / 绿 {sum(p < 0 for p in pcts)}")
    # ① 预案簇
    E = jl(LIVE / D / "expect.json", {}) or {}
    W = jl(LIVE / D / "watch_seed.json", {}) or {}
    clusters = []
    for f in (E.get("明日聚焦") or [])[:6]:
        cs = [m.group(1) for g in f.get("梯队") or [] for m in [re.search(r"\((\d{6})\)", g)] if m]
        clusters.append((f"预案·{f['题材']}", cs))
    for p_ in E.get("题材预案") or []:
        cs = [m.group(1) for g in p_.get("个股") or [] for m in [re.search(r"\((\d{6})\)", g)] if m][:6]
        clusters.append((f"预案·{p_['题材']}", cs))
    zb = {}
    for x in W.get("seed") or []:
        for t in x.get("tags") or []:
            if t.startswith("字辈"):
                zb.setdefault(t, []).append(x["code"])
            elif t == "续板":
                zb.setdefault("续板梯队", []).append(x["code"])
    clusters += list(zb.items())
    L.append("")
    L.append("① 预案 / 种子簇:")
    for nm, cs in clusters:
        rs = [r for r in (row(c, A, names) for c in cs) if r]
        if not rs:
            continue
        med = statistics.median([r["pct"] for r in rs])
        rs.sort(key=lambda r: -(r["pct"] or 0))
        L.append(f"- {nm}: 中位 {med:+.2f}% · 涨停 {sum(r['lim'] == '涨停' for r in rs)} / 跌停 {sum(r['lim'] == '跌停' for r in rs)} | " + " / ".join(fmt(r) for r in rs[:5]))
    # ② 竞价一字的拓扑邻居
    nb_codes = []
    if ups:
        L.append("")
        L.append("② 竞价涨停(一字候选)+ 拓扑邻居(大簇=同行业 / 小簇=联动最强):")
        try:
            import topology as TOPO
            for r in sorted(ups, key=lambda r: -(r.get("unm") or 0))[:8]:
                t_ = TOPO.load(r["code"], D, strict=True) or {}
                nbs = [x["c"] for x in (t_.get("nb") or [])[:3]]
                nb_codes += nbs
                nr = [row(c, A, names) for c in nbs]
                L.append(f"- {fmt(r)} · 行业 {t_.get('ind') or '?'} → 邻居: " + (" / ".join(fmt(x) if x else f"{c}(没采到竞价)" for c, x in zip(nbs, nr)) or "无"))
        except Exception as e:   # noqa: BLE001
            L.append(f"(拓扑读取失败 {type(e).__name__})")
    # ③ 三方对照
    L.append("")
    L.append("③ 盘前 chain 选的票 × 竞价(× 是否在预案里):")
    pre = {c for _, cs in clusters for c in cs}
    for d_ in sorted((LIVE / D).glob("live_*")):
        sp = sorted((d_ / "strategies").glob("*.json"))
        if not sp:
            continue
        codes = [str(x.get("code")) for x in ((jl(sp[-1], {}) or {}).get("strategy") or {}).get("codes") or []]
        rs = [(c, row(c, A, names)) for c in codes]
        if rs:
            L.append(f"- {d_.name[5:]}: " + " / ".join((fmt(r) if r else c) + ("〔预案〕" if c in pre else "") for c, r in rs[:6]))
    return {"text": "\n".join(L), "nb": list(dict.fromkeys(nb_codes))}, None


def write_extra(codes, dry=False):
    t = EXTRA.read_text(encoding="utf-8") if EXTRA.exists() else ""
    t = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", t, flags=re.S)
    if codes:
        t = t.rstrip("\n") + f"\n{BEGIN}\n" + " ".join(codes) + f"\n{END}\n"
    if not dry:
        EXTRA.write_text(t, encoding="utf-8")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    run(a.date, a.dry)


def run(D, dry=False):
    out, err = build(D)
    if err:
        print(err)
        return 1
    (LIVE / D).mkdir(parents=True, exist_ok=True)
    (LIVE / D / "auction_result.md").write_text(out["text"], encoding="utf-8")
    write_extra(out["nb"], dry)
    print(out["text"])
    if not dry:
        import push_bus as PB
        if PB.on():
            PB.enqueue(out["text"], src="auction_result", urgent=True, fast=True, D=D)
        else:
            import wx_send
            wx_send.send(out["text"], src="auction_result", raw=True, wait=120, force=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
