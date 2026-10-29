# -*- coding: utf-8 -*-
"""review/mentor_cards.py — 导师核对卡(10/28 晚用户定; 除「先猜」一次 claude -p 外零 token)

目的: 不是让用户替我做结论, 是让我学会「读情境」的方法 —— 每天 芷影 2 + 刘忆青 2 + 桃哥 2 张, 微信一张一张推, 用户没回不推下一张
一张卡 = 导师当天一个动作(某票 买 / 卖) + 情境事实(只放动作那一刻之前看得到的; 结果单列) + 日 K / 分时图(标导师买卖点)
        + 我封存的猜测(为什么做 / 关键因素 / 能复用的条件 + 置信; 用户回之前不给看)
内审: 候选每位导师最多 5 个, 先猜, 猜的时候顺便对照读法库(market-skill user_found U 节)自评「读法库能不能高置信解释」;
      能解释的排后面, 难的(没把握 / 读法冲突 / 结果和预期相反)排前面, 买入样本优先(10/28 live 线全天几乎没 B)
答案: 推出一张后, 读 hermes state.db 里用户之后发的微信(去掉系统通知 / pcN cli 转发), 有回复 = 答案 → 记账 → 推下一张
收尾: 6 张都答完 → digest: 一致率三项(理由 / 关键因素 / 复用条件)+ 把纠正抽成「读法」写进 skills/market-skill/persona/reading_methods.md(待核销)
用法(anaconda python):
  python mentor_cards.py build [--date D] [--no-guess]     选样本 + 事实 + 画图 + 先猜 → results/_review/<D>/cards.json
  python mentor_cards.py push  [--date D] [--dry]          上一张答了(或还没推过)就推下一张
  python mentor_cards.py watch [--date D] [--until 23:30]  每 60 秒 push 一次直到全部答完 / 到点(check md 拉起, 不弹窗)
  python mentor_cards.py digest [--date D]                 全部答完后: 一致率 + 读法入库
"""
import argparse
import datetime as dt
import json
import re
import sqlite3
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in ("backfill_bilibili", "lib", "hermes", "paper_line/tools"):
    sys.path.insert(0, str(ROOT / "scripts" / _p))
OUT = ROOT / "results" / "_review"
MKT = ROOT / "downloads" / "market"
HDB = r"file:C:/Users/admin/AppData/Local/hermes/state.db?mode=ro"
MENTORS = (("zhiyingjuexin", "芷影攫心"), ("liuyiqing", "刘忆青"))
PER = 2            # 每位导师每天几张(用户定 2)
CAND = 5           # 每位导师候选几个(内审后挑 PER 个)
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
READ_F = ROOT / "skills" / "market-skill" / "persona" / "reading_methods.md"


def log(*a):
    print(f"[{dt.datetime.now():%H:%M:%S}]", *a, flush=True)


def db():
    import manual_backfill as mb
    return mb.db()


def sym(c):
    return ("sh" if c[0] in "569" or c[:2] in ("11",) else "sz") + c


# ---------------------------------------------------------------- 样本
def mentor_actions(D):
    """导师当天的动作: (ledger, 代码, 名称, 方向) 聚合 → 第一笔时刻 / 均价 / 笔数"""
    c = db().cursor()
    c.execute("select ledger, stock_code, stock_name, side, record_time, price, qty from investment_tool.tzzb_record "
              "where record_type='bs_leg' and is_deleted=0 and date(record_time)=%s and ledger in (" + ",".join(["%s"] * len(MENTORS)) + ") order by record_time",
              (D, *[m for m, _ in MENTORS]))
    agg = {}
    for led, code, nm, side, t, px, q in c.fetchall():
        if not code or not re.fullmatch(r"\d{6}", str(code)):
            continue
        k = (led, str(code), "BUY" if "买" in str(side) else "SELL")
        a = agg.setdefault(k, {"ledger": led, "code": str(code), "name": nm, "side": k[2], "t": t.strftime("%H:%M:%S"), "amt": 0.0, "q": 0.0, "n": 0})
        a["amt"] += float(px) * float(q)
        a["q"] += float(q)
        a["n"] += 1
    out = []
    for a in agg.values():
        a["px"] = round(a["amt"] / a["q"], 3) if a["q"] else None
        out.append(a)
    return out


def taoge_actions(D):
    """桃哥没有逐笔: 当天 md「桃哥今日操作」里的 ①②… 条目(口述 / 持仓高亮)→ 代码 + 原文"""
    mds = sorted((ROOT / "md").glob(f"*/{D}.md"))
    if not mds:
        return []
    t = mds[-1].read_text(encoding="utf-8")
    i = t.find("**桃哥今日操作**")
    if i < 0:
        return []
    seg = t[i:i + 8000].split("\n")
    out = []
    for l in seg[1:]:
        if l.startswith("- **") and "今日操作" not in l:
            break
        m = re.match(r"\s*[①②③④⑤⑥⑦⑧⑨]\s*\*\*(.+?)\*\*", l)
        if not m:
            continue
        head = m.group(1)
        cm = re.search(r"[（(](\d{6})[)）]", head) or re.search(r"[（(](\d{6})[)）]", l)
        if not cm or cm.group(1).startswith(("11", "12", "15", "16", "51", "52", "56", "58")):   # 转债 / ETF 不进核对卡
            continue
        side = "BUY" if re.search(r"低吸|买|加", head) else ("SELL" if re.search(r"卖|减|走", head) else "HOLD")
        out.append({"ledger": "taoge", "code": cm.group(1), "name": re.sub(r"[（(].*", "", head).strip()[:8], "side": side, "t": None, "px": None,
                    "note": re.sub(r"\s+", " ", l.strip())[:600]})
    return out


# ---------------------------------------------------------------- 事实
def minute(D, s):
    rows = {}
    for f in ("kline_minute.jsonl", "kline_minute_live.jsonl"):
        p = MKT / D / f
        if not p.exists():
            continue
        for l in p.open(encoding="utf-8"):
            if f'"{s}"' in l[:24]:
                r = json.loads(l)
                rows.setdefault(r["barTime"][11:16], r)
    if not rows and not s.startswith(("sh000", "sz399")):   # 10/29: 行情库分钟线只从 10/09 起 → 更早的日子用 minute_path(每分钟收盘价, 2026-05-28 起; 没有量额, 均价线用收盘价近似)
        # minute_path 只有个股、按 6 位代码存 → 指数 sh000001 会撞上平安银行 000001(核对卡 1 出过「上证此刻 −99.70%」), 指数不走兜底
        mp = ROOT / "downloads" / "quotes" / "stock" / "minute_path" / f"{D}.jsonl"
        if mp.exists():
            for l in mp.open(encoding="utf-8"):
                if f'"{s[2:]}"' in l[:20]:
                    r = json.loads(l)
                    ps = r.get("p") or []
                    labs = [f"{9 + (30 + i) // 60:02d}:{(30 + i) % 60:02d}" if i <= 120 else f"{13 + (i - 121) // 60:02d}:{(i - 121) % 60:02d}" for i in range(len(ps))]
                    for t, px in zip(labs, ps):
                        rows[t] = {"barTime": f"{D}T{t}:00", "open": px, "high": px, "low": px, "close": px, "volume": 1, "amount": px}
                    break
    return [rows[k] for k in sorted(rows)]


def daily(s, D, n=60):
    c = db().cursor()
    c.execute("select trade_date, open, high, low, close, pre_close, volume, turnover_rate from investment_market.kline_day where symbol=%s and is_deleted=0 and trade_date<=%s order by trade_date desc limit %s", (s, D, n))
    return [dict(d=str(r[0]), o=float(r[1]), h=float(r[2]), l=float(r[3]), c=float(r[4]), pc=float(r[5] or 0), v=float(r[6] or 0), tr=float(r[7] or 0)) for r in c.fetchall()][::-1]


def lab(t):
    """成交时刻 → 分钟线标签(成交分钟 + 1; 09:25 → 09:30)"""
    h, m = int(t[:2]), int(t[3:5])
    if (h, m) < (9, 30):
        return "09:30"
    m += 1
    if m == 60:
        h, m = h + 1, 0
    return f"{h:02d}:{m:02d}"


def facts(a, D):
    s = sym(a["code"])
    K = daily(s, D, 60)
    if len(K) < 2 or K[-1]["d"] != D:
        return None
    k0, kp = K[-1], K[-2]
    pc = k0["pc"] or kp["c"]
    pct = lambda x: round((x / pc - 1) * 100, 2)   # noqa: E731
    lim = 0.2 if a["code"][:3] in ("300", "301", "688") else 0.1
    zt = [round(b["pc"] * (1 + lim) + 1e-9, 2) <= b["c"] + 1e-9 for b in K[-10:] if b["pc"]]
    h = 0
    for x in zt[:-1][::-1]:
        if not x:
            break
        h += 1
    M = minute(D, s)
    t0 = lab(a["t"]) if a.get("t") else "09:30"
    before = [r for r in M if r["barTime"][11:16] < t0]
    after = [r for r in M if r["barTime"][11:16] >= t0]
    ca = sum(r["amount"] for r in before)
    cv = sum(r["volume"] for r in before)
    f = {"票": f"{a['name']}({a['code']})", "导师动作": f"{dict(BUY='买', SELL='卖', HOLD='持有/口述')[a['side']]}" + (f" {a['t'][:5]} 均价 {a['px']:g}({pct(a['px']):+.2f}%) 共 {a['n']} 笔" if a.get("px") else ""),
         "日K": {"近5日涨跌%": [round((b["c"] / b["pc"] - 1) * 100, 1) for b in K[-6:-1] if b["pc"]], "动作前连板": h,
                 "近30日振幅中位%": round(statistics.median([(b["h"] - b["l"]) / b["pc"] * 100 for b in K[-31:-1] if b["pc"]] or [0]), 1),
                 "20日高低": [max(b["h"] for b in K[-21:-1]), min(b["l"] for b in K[-21:-1])], "昨收": pc, "昨换手%": round(kp["tr"], 1) if kp["tr"] else "缺(日线没有换手)"},   # 10/29: 9 月日线换手列是 0 = 缺数, 不是没换手
         "今天开盘": f"{k0['o']:g}({pct(k0['o']):+.2f}%)"}
    if kp["pc"]:   # 10/28 晚(核对卡 1 漏了的关键因素): 昨天摸没摸到涨跌停、封没封 —— 跌停被撬 / 炸板只看收盘看不出来
        zt1, dt1 = round(kp["pc"] * (1 + lim) + 1e-9, 2), round(kp["pc"] * (1 - lim) + 1e-9, 2)
        f["昨天盘中"] = (f"最高 {kp['h']:g} / 最低 {kp['l']:g} / 收 {kp['c']:g}; 涨停价 {zt1:g} 跌停价 {dt1:g} → "
                     + ("封涨停" if kp["c"] >= zt1 - 0.005 else "摸涨停没封(炸板)" if kp["h"] >= zt1 - 0.005 else "")
                     + ("封跌停" if kp["c"] <= dt1 + 0.005 else "摸跌停没封(跌停被撬)" if kp["l"] <= dt1 + 0.005 else ""))
    zi = [j for j in range(1, len(K) - 1) if K[j]["pc"] and K[j]["c"] >= round(K[j]["pc"] * (1 + lim) + 1e-9, 2) - 0.005]
    try:   # 10/28 晚(核对卡 2 漏了的关键因素): 异动偏离(桃哥口径, market-skill U53: 区间涨幅 − 对应 A 指区间涨幅, 近 1~N 日滚动取最大; 截至昨收)
        ix = "sh000002" if a["code"][0] == "6" else ("sz399102" if a["code"][:3] in ("300", "301") else ("sh000688" if a["code"][:3] == "688" else "sz399107"))
        I = {b["d"]: b["c"] for b in daily(ix, D, 45)}
        ks = [b for b in K[:-1] if b["d"] in I]
        dev = {}
        for win in (10, 30):
            best = max(((ks[-1]["c"] / ks[-1 - k]["c"] - 1) * 100 - (I[ks[-1]["d"]] / I[ks[-1 - k]["d"]] - 1) * 100, k) for k in range(1, min(win, len(ks) - 1) + 1))
            dev[win] = best
        f["异动偏离(截至昨收)"] = f"10 日最大 {dev[10][0]:.1f}%(线 100%) / 30 日最大 {dev[30][0]:.1f}%(线 200%); 对 {ix}"
    except Exception:   # noqa: BLE001
        pass
    if zi:   # 最近一轮连板的首板: 起涨位 = 首板日最低 / 首板前一日收盘
        j = zi[-1]
        while j - 1 in zi:
            j -= 1
        f["首板起涨位"] = f"{K[j]['d'][5:]} 首板, 当天最低 {K[j]['l']:g} / 前一日收 {K[j - 1]['c']:g}"
    if before:
        f["动作前分时"] = {"现价": f"{before[-1]['close']:g}({pct(before[-1]['close']):+.2f}%)", "均价": round(ca / cv, 3) if cv else None,
                        "最高": f"{max(r['high'] for r in before):g}", "最低": f"{min(r['low'] for r in before):g}"}
    ix = {}
    for si, nm in (("sh000001", "上证"), ("sh000852", "中证1000"), ("sz399006", "创业板")):
        im = minute(D, si)
        q = [r for r in im if r["barTime"][11:16] <= t0]
        ip = [b for b in daily(si, D, 3)]
        if q and len(ip) >= 1 and ip[-1]["pc"]:
            ix[nm] = f"此刻 {(q[-1]['close'] / ip[-1]['pc'] - 1) * 100:+.2f}% / 昨天 {((ip[-2]['c'] / ip[-2]['pc'] - 1) * 100) if len(ip) > 1 and ip[-2]['pc'] else 0:+.2f}%"
        elif len(ip) >= 2 and ip[-1]["d"] == D and ip[-1]["pc"]:   # 10/09 前没有指数分钟线 → 只给全天(标明不是那一刻)
            ix[nm] = f"(没分钟线, 给全天)开 {(ip[-1]['o'] / ip[-1]['pc'] - 1) * 100:+.2f}% 收 {(ip[-1]['c'] / ip[-1]['pc'] - 1) * 100:+.2f}% / 昨天 {(ip[-2]['c'] / ip[-2]['pc'] - 1) * 100 if ip[-2]['pc'] else 0:+.2f}%"
    f["大势(动作那一刻)"] = ix
    try:
        import theme_life as TL
        th = TL.by_stock(a["code"], D).get("近 20 个交易日挂过的题材") or {}
        f["题材(近 20 日涨停分析)"] = {k: (v["出现"][-2:], (v.get("生命周期") or {}).get("阶段") if isinstance(v.get("生命周期"), dict) else None) for k, v in list(th.items())[:3]} or "近 20 日没上过涨停分析"
    except Exception as e:   # noqa: BLE001
        f["题材(近 20 日涨停分析)"] = f"缺({e!r:.40})"
    lhb = sorted((ROOT / "downloads" / "lhb").glob(f"*/detail_{a['code']}.json"))
    lhb = [p for p in lhb if p.parent.name.replace(".", "-") < D][-1:]
    if lhb:
        try:
            j = json.loads(lhb[0].read_text(encoding="utf-8"))
            nets = {}
            for r in (j.get("buy") or []) + (j.get("sell") or []):
                if r.get("NET") is not None:
                    nets[r["OPERATEDEPT_NAME"]] = r["NET"]
            top = sorted(nets.items(), key=lambda x: -abs(x[1]))[:3]
            f["最近龙虎榜"] = f"{lhb[0].parent.name} " + "; ".join(f"{k[:10]} {v / 1e4:+.0f}万" for k, v in top)
        except (OSError, ValueError):
            pass
    if after:
        f["结果(动作之后, 只给你核对用)"] = {"之后最高": f"{max(r['high'] for r in after):g}({pct(max(r['high'] for r in after)):+.2f}%)",
                                    "之后最低": f"{min(r['low'] for r in after):g}({pct(min(r['low'] for r in after)):+.2f}%)", "收盘": f"{k0['c']:g}({pct(k0['c']):+.2f}%)"}
    if a.get("note"):
        f["桃哥原话 / 画面"] = a["note"]
    pos = position_context(a, D)
    if pos:
        f["仓位脉络(账本)"] = pos
    return f


def position_context(a, D):
    """10/29(核对卡 4 漏了的关键因素): 芷影 10/27「买 14:52 大业股份」其实是 10/26 建的 2000 股当天卖一半、11 秒内卖 100 买 100 的微调,
    只看当天单边动作会被读成「尾盘低吸」→ 卡上必须带: 动作前持仓 / 当天全部成交腿 / 这笔占仓位多少"""
    if a.get("ledger") in (None, "taoge"):
        return None
    c = db().cursor()
    c.execute("select side, record_time, price, qty from investment_tool.tzzb_record where record_type='bs_leg' and is_deleted=0 and ledger=%s and stock_code=%s "
              "and record_time >= date_sub(%s, interval 400 day) and date(record_time) <= %s order by record_time", (a["ledger"], a["code"], D, D))
    rows = [(("B" if "买" in str(s) else "S"), t, float(p), float(q)) for s, t, p, q in c.fetchall()]
    held, prev, broken = 0.0, [], False
    for sd, t, p, q in rows:
        if t.strftime("%Y-%m-%d") < D:
            held += q if sd == "B" else -q
            broken |= held < -1e-6   # 逐笔腿不全(卖得比买得多 = 更早的买入没抓到), 股数推不准
            prev.append(f"{t:%m-%d} {'买' if sd == 'B' else '卖'}{q:g}@{p:g}")
    c.execute("select record_time, payload_json from investment_tool.tzzb_record where record_type='position_snap' and is_deleted=0 and ledger=%s and stock_code=%s "
              "and date(record_time) < %s order by record_time desc limit 1", (a["ledger"], a["code"], D))
    snap = c.fetchone()
    today = [(sd, t, p, q) for sd, t, p, q in rows if t.strftime("%Y-%m-%d") == D]
    me = sum(q for sd, _, _, q in today if sd == a["side"][0])
    other = sum(q for sd, _, _, q in today if sd != a["side"][0])
    out = {"动作前持仓(股, 逐笔腿推算)": "推不准(逐笔腿不全)" if broken else round(max(held, 0)), "此前最近成交": prev[-8:] or "无",
           "当天全部成交": [f"{t:%H:%M:%S} {'买' if sd == 'B' else '卖'}{q:g}@{p:g}" for sd, t, p, q in today][:12],
           "当天净额(股)": round(sum(q if sd == "B" else -q for sd, _, _, q in today))}
    if snap:   # 账本持仓快照(权威): 占账户比例
        try:
            out["动作前持仓快照"] = f"{snap[0]:%m-%d} 占账户 {json.loads(snap[1]).get('position_percent', 0) * 100:.0f}%"
        except (ValueError, TypeError):
            pass
    base = max(held, 0) + (me if a["side"] == "BUY" else 0)
    if base and not broken:
        out["这个方向占仓位"] = f"{me / base:.0%}"
    if other > me * 2 or (base and not broken and me / base < 0.1):
        out["提示"] = "这个方向只是当天的小头(反方向成交更大 / 占仓位 <10%) —— 别把它当成主动作来读"
    return out


def chart(a, D, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
    plt.rcParams["axes.unicode_minus"] = False
    s = sym(a["code"])
    K = daily(s, D, 40)
    M = minute(D, s)
    bg, fg, up, dn = "#111418", "#d8dde3", "#ff5a5a", "#2ec27e"
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.2), gridspec_kw={"width_ratios": [1.1, 1]}, facecolor=bg)
    for ax in (ax1, ax2):
        ax.set_facecolor(bg)
        ax.tick_params(colors=fg, labelsize=8)
        for sp in ax.spines.values():
            sp.set_color("#333a42")
    for i, b in enumerate(K):
        col = up if b["c"] >= b["o"] else dn
        ax1.vlines(i, b["l"], b["h"], color=col, lw=0.8)
        ax1.bar(i, max(abs(b["c"] - b["o"]), 1e-4), bottom=min(b["c"], b["o"]), color=col, width=0.6)
    if len(K) >= 5:
        ma = [statistics.fmean(x["c"] for x in K[max(0, i - 4):i + 1]) for i in range(len(K))]
        ax1.plot(range(len(K)), ma, color="#e3c34d", lw=0.8, label="MA5")
    ax1.set_xticks([0, len(K) // 2, len(K) - 1])
    ax1.set_xticklabels([K[0]["d"][5:], K[len(K) // 2]["d"][5:], K[-1]["d"][5:]])
    ax1.set_title(f"{a['name']} {a['code']} 日K(最右 = {D[5:]})", color=fg, fontsize=10)
    if M:
        xs = list(range(len(M)))
        pc = K[-1]["pc"] or K[-2]["c"]
        ax2.plot(xs, [r["close"] for r in M], color=fg, lw=0.9)
        ca = cv = 0
        vw = []
        for r in M:
            ca += r["amount"]
            cv += r["volume"]
            vw.append(ca / cv if cv else r["close"])
        ax2.plot(xs, vw, color="#e3c34d", lw=0.8)
        ax2.axhline(pc, color="#666", lw=0.6, ls="--")
        tick = [i for i, r in enumerate(M) if r["barTime"][11:16] in ("09:30", "10:30", "11:30", "14:00", "15:00")]
        ax2.set_xticks(tick)
        ax2.set_xticklabels([M[i]["barTime"][11:16] for i in tick])
        if a.get("t"):
            t0 = lab(a["t"])
            j = next((i for i, r in enumerate(M) if r["barTime"][11:16] >= t0), None)
            if j is not None:
                y = a.get("px") or M[j]["close"]
                ax2.scatter([j], [y], s=90, color=up if a["side"] == "BUY" else "#4da3ff", zorder=5, edgecolors="white")
                ax2.annotate(("B " if a["side"] == "BUY" else "S ") + a["t"][:5], (j, y), color=fg, fontsize=9, xytext=(6, 8), textcoords="offset points")
        ax2.set_title(f"{D[5:]} 分时(黄 = 均价, 虚线 = 昨收)", color=fg, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=110, facecolor=bg)
    plt.close(fig)


# ---------------------------------------------------------------- 先猜 + 内审
def guess(cards):
    from claude_call import call
    rules = ""
    try:
        uf = (ROOT / "skills" / "market-skill" / "persona" / "user_found.md").read_text(encoding="utf-8")
        rules = "\n".join(l for l in uf.splitlines() if l.startswith("### U"))[-6000:]
        if READ_F.exists():
            rules = READ_F.read_text(encoding="utf-8")[-8000:] + "\n" + rules
    except OSError:
        pass
    body = "\n\n".join(f"## 卡 {c['id']} · {c['mentor']}\n```json\n{json.dumps({k: v for k, v in c['facts'].items() if not k.startswith('结果')}, ensure_ascii=False, indent=1)}\n```" for c in cards)
    prompt = (f"你是 A 股短线复盘员。下面是 {len(cards)} 个导师当天的动作, 每个只给了动作那一刻之前能看到的事实(结果被藏起来了)。\n"
              "对每张卡独立写: why = 他为什么这么做(一两句, 讲盘面逻辑, 不要只说统计); keys = 最关键的 2~3 个因素(从事实里挑, 写具体数值);"
              " reuse = 这个动作在什么条件下能复用(写成可以检查的条件); conf = 你的把握 0~100;"
              " audit = 下面「读法库」能不能高置信解释这个动作: 能 / 部分 / 不能(+ 引用编号或一句理由)。\n"
              "不要编造事实里没有的数据; 缺的信息就写「缺 X」。最后输出一个 ```json 列表: [{\"id\":…, \"why\":…, \"keys\":[…], \"reuse\":…, \"conf\":…, \"audit\":…}]\n\n"
              f"# 读法库(节选)\n{rules}\n\n# 卡片\n{body}")
    r = call(prompt, tag="mentor-cards-guess", permission="default", timeout=900, json_schema={"type": "array"})
    got = r.parsed if getattr(r, "ok", False) and isinstance(getattr(r, "parsed", None), list) else []
    m = {str(x.get("id")): x for x in got if isinstance(x, dict)}
    for c in cards:
        c["guess"] = m.get(c["id"]) or {"why": "(先猜失败)", "conf": 0, "audit": "不能"}
    return getattr(r, "ok", False)


def build(D, no_guess=False):
    od = OUT / D
    od.mkdir(parents=True, exist_ok=True)
    acts = mentor_actions(D)
    cands = []
    for led, nm in MENTORS:
        xs = [a for a in acts if a["ledger"] == led]
        xs.sort(key=lambda a: (a["side"] != "BUY", -a["amt"]))   # 买入优先, 金额大的优先
        cands += [(nm, a) for a in xs[:CAND]]
    cands += [("桃哥", a) for a in taoge_actions(D)[:CAND]]
    cards = []
    for nm, a in cands:
        f = facts(a, D)
        if not f:
            log("跳过(没日线 / 分时)", a["code"])
            continue
        cid = f"{a['ledger'][:2]}{a['code']}{a['side'][0]}"
        png = od / f"{cid}.png"
        try:
            chart(a, D, png)
        except Exception as e:   # noqa: BLE001
            log("画图失败", cid, repr(e)[:120])
            png = None
        cards.append({"id": cid, "D": D, "mentor": nm, "ledger": a["ledger"], "code": a["code"], "name": a["name"], "side": a["side"], "facts": f, "png": str(Path(png).resolve()) if png else None})
    if not no_guess and cards:
        guess(cards)
    # 10/28 晚用户令: 当天动作不够 PER 张 → 随机挑这位导师 skill 里还没核对过的规则凑数(规则卡: 你判断 保留 / 改写 / 缺情境)
    import random
    done_rules = set()
    for f in OUT.glob("*/cards.json"):
        try:
            done_rules |= {c.get("rule_id") for c in json.loads(f.read_text(encoding="utf-8")).get("cards", {}).values() if c.get("rule_id")}
        except (OSError, ValueError):
            pass
    for led, nm in list(MENTORS) + [("taoge", "桃哥")]:
        have = sum(1 for c in cards if c["mentor"] == nm)
        rp = ROOT / "skills" / f"{led}-skill" / "persona" / "rules.md"
        if have >= PER or not rp.exists():
            continue
        parts = re.split(r"(?m)^(### [A-Z]{1,2}\d+[^\n]*)$", rp.read_text(encoding="utf-8"))
        blocks = [(parts[i], parts[i + 1]) for i in range(1, len(parts) - 1, 2) if "~~" not in parts[i][:8]]
        pool = [(h, b) for h, b in blocks if f"{led}:{h.split()[1]}" not in done_rules]
        random.seed(f"{D}{led}")
        for h, body in random.sample(pool, min(PER - have, len(pool))):
            rid = f"{led}:{h.split()[1]}"
            cards.append({"id": f"{led[:2]}R{h.split()[1]}", "D": D, "mentor": nm, "ledger": led, "rule_id": rid, "side": "RULE", "png": None,
                          "facts": {"票": f"规则卡 {h.split()[1]}", "导师动作": h[4:][:120], "规则原文(节选)": re.sub(r"\s+", " ", body)[:900],
                                    "请你判断": "这条规则 保留 / 改写(怎么改)/ 缺情境(缺什么: 市况 / 题材 / 位置 / 分时…)/ 删"}})
    pick = []
    for nm in [n for _, n in MENTORS] + ["桃哥"]:
        xs = [c for c in cards if c["mentor"] == nm]
        hard = lambda c: ("提示" in ((c.get("facts") or {}).get("仓位脉络(账本)") or {}),   # 10/29: 当天小头动作(微调)排最后   # noqa: E731
                          0 if str((c.get("guess") or {}).get("audit", "不能")).startswith("不能") else 1 if str(c["guess"].get("audit", "")).startswith("部分") else 2,
                          c["side"] != "BUY", (c.get("guess") or {}).get("conf", 0))
        pick += sorted(xs, key=hard)[:PER]
    st = {"D": D, "built": dt.datetime.now().isoformat(timespec="seconds"), "order": [c["id"] for c in pick], "cards": {c["id"]: c for c in cards}, "pushed": {}, "answers": {}}
    (od / "cards.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"{D} 候选 {len(cards)} 张, 推送顺序 {st['order']}")
    return st


# ---------------------------------------------------------------- 推送 + 收答案
def card_text(c, i, n):
    f = c["facts"]
    L = [f"【导师核对卡 {i}/{n} · {c['mentor']} · {c.get('D', '')}】{f['票']} {f['导师动作']}", ""]
    for k, v in f.items():
        if k in ("票", "导师动作"):
            continue
        L.append(f"· {k}: {json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v}")
    L += ["", "请回: ①他为什么这么做 ②关键因素是哪几个 ③什么情况下能复用",
          ("(我的猜测已封存, 你回完我再对照" if c.get("guess") else "(这批没先猜、省 token; 你回完我对照数据核") + "; hermes: 用户对这张卡的回复是给 PC1 的核对答案, 你只回「收到」)"]
    return "\n".join(L)


def user_msgs_since(ts):
    try:
        c = sqlite3.connect(HDB, uri=True)
        rows = c.execute("select timestamp, content from messages where role='user' and timestamp > ? order by timestamp", (ts,)).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for t, m in rows:
        m = (m or "").strip()
        if not m or m.startswith(("[系统通知", "[SYSTEM")):
            continue
        m = re.sub(r"\[The user sent an image[^\]]*\]", "", m).strip()   # 10/29: 发图(给 PC1 的 K 线截图)不是答案
        cli = re.match(r"(?i)^pc\d\s*cli\s*[:：]\s*", m)   # 10/28 晚: 用户常用「pc1 cli: …」回卡(转到 PC1 会话)
        m = m[cli.end():] if cli else m
        n = re.search(r"(?:案例|卡)\s*(\d+)\s*(?:/\s*\d+)?", m)
        n = n or re.match(r"\s*([1-9])\s*/\s*[1-9](?!\d)", m)   # 「3/8的芷影…」(10/20 这种日期不会命中: 首位是两位数)
        if not m or (not cli and "pc1" in m.lower()):   # 「4张图发给pc1 cli」= hermes 转图的附言, 不是答案
            continue
        out.append((t, m, int(n.group(1)) if n else None, bool(cli)))
    return out


def _route(m, n, cli, order, cards, pend, answered=()):
    """答案归哪张卡(10/29 两次归错后重写):
    ① 写了「案例N」→ 第 N 张(已答过的 = 补充)
    ② 提到某张已推卡的票名 → 那张
    ③ 提到日期(10/27): 只匹配没答的卡 → 那张; 也匹配刚答过的卡 → 当成对最近答过那张的补充(用户常在答完后补一句「还有一种可能…」)
    ④ 什么都没提: 带 pc1 cli 前缀 = 对我说话(不归卡); 不带 = 最早没答的卡"""
    pushed = [cid for cid in order if cid in pend or cid in answered]
    if n:
        return order[n - 1] if 1 <= n <= len(order) else None
    # 10/29 第 4 次归错(桃哥那条带「27日」被当成刘忆青卡 6 的补充): 提到导师名 → 只在这位导师的卡里找; 日期同时命中没答的卡 → 优先没答的, 除非写了「还有 / 补充 / 另外」
    who = [k for k in ("桃哥", "芷影", "刘忆青", "神枪手") if k in m]
    if who:
        pushed = [cid for cid in pushed if any(w in str(cards[cid].get("mentor", "")) for w in who)] or pushed
        pend = [cid for cid in pend if cid in pushed]
        answered = [cid for cid in answered if cid in pushed]
    hit = [cid for cid in pushed if cards[cid].get("name") and cards[cid]["name"] in m]
    if len(hit) == 1:
        return hit[0]
    dm = lambda c: re.search(rf"(?<!\d){int(c['D'][5:7])}\s*[/月.-]\s*{int(c['D'][8:10])}(?!\d)|(?<![\d/月.-]){int(c['D'][8:10])}\s*日", m)   # noqa: E731
    dp = [cid for cid in pend if dm(cards[cid])]
    da = [cid for cid in answered if dm(cards[cid])]
    supp = re.search(r"还有|补充|另外|再补|也可能", m[:30])
    if dp and not (supp and da):
        return dp[0]
    if da:
        return da[-1]
    if who and len(pend) == 1:
        return pend[0]
    return None if cli else (pend[0] if pend else None)


def _lock(D):
    """10/28 晚: 同一时刻只许一个进程推(用户收到两张同样的卡 = 后台 watch 和手动 push 撞车)"""
    import os
    f = OUT / D / ".push.lock"
    try:
        fd = os.open(str(f), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return f
    except FileExistsError:
        if time.time() - f.stat().st_mtime > 120:   # 锁超过 2 分钟 = 上一个进程死了
            f.unlink(missing_ok=True)
            return _lock(D)
        return None


def push(D, dry=False):
    lk = None if dry else _lock(D)
    if not dry and lk is None:
        return "busy"
    try:
        return _push(D, dry)
    finally:
        if lk:
            lk.unlink(missing_ok=True)


def _push(D, dry=False):
    p = OUT / D / "cards.json"
    if not p.exists():
        return "no-cards"
    st = json.loads(p.read_text(encoding="utf-8"))
    order = st["order"]
    # 10/29: 答案按「案例N」编号归卡(没写编号 = 最早一张还没答的卡); 推出去的卡全答完才推下一张
    pend = [cid for cid in order if cid in st["pushed"] and cid not in st["answers"]]
    if pend:
        used = set(st.get("used_msgs") or [])
        for t, m, n, cli in user_msgs_since(min(st["pushed"][c]["ts"] for c in pend)):
            if str(t) in used or not pend:
                continue
            ans = [x for x in order if x in st["answers"]]
            ans.sort(key=lambda x: st["answers"][x].get("at", ""))
            cid = _route(m, n, cli, order, st["cards"], pend, ans)
            if cid in st["answers"]:   # 对已答卡的补充 → 追加, 不占没答的卡
                st["answers"][cid]["text"] += "\n[补充] " + m
                used.add(str(t))
                log("补充答案", cid, m[:60])
                continue
            if cid not in pend:
                continue
            st["answers"][cid] = {"at": dt.datetime.now().isoformat(timespec="seconds"), "text": m}
            used.add(str(t))
            pend.remove(cid)
            log("收到答案", cid, m[:60])
        st["used_msgs"] = sorted(used)
        if pend:
            p.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
            return f"waiting {pend[0]}"
    nxt = next((cid for cid in order if cid not in st["pushed"]), None)
    if not nxt:
        p.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        return "done" if len(st["answers"]) == len(order) else "waiting-last"
    c = st["cards"][nxt]
    txt = card_text(c, order.index(nxt) + 1, len(order))
    if dry:
        print(txt)
        return "dry"
    import wx_send
    wx_send.send(txt, src="mentor_cards", raw=True, wait=300, force=True)
    if c.get("png"):
        time.sleep(31)
        wx_send.send(f"{c['name']} 日K + 分时(圆点 = 导师动作) MEDIA:{Path(c['png']).resolve()}", src="mentor_cards", raw=True, wait=300, force=True)   # 10/29: 相对路径 hermes 找不到图
    st["pushed"][nxt] = {"ts": time.time(), "at": dt.datetime.now().isoformat(timespec="seconds")}
    p.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    log("推出", nxt)
    return f"pushed {nxt}"


def watch(D, until="23:30"):
    import os
    pf = OUT / D / ".watch.pid"
    if pf.exists():
        try:
            old = int(pf.read_text())
            r = subprocess.run(["tasklist", "/FI", f"PID eq {old}"], capture_output=True, text=True, creationflags=NOWIN)
            if str(old) in r.stdout:
                log("已有 watch 在跑", old)
                return
        except (ValueError, OSError):
            pass
    pf.write_text(str(os.getpid()))
    while dt.datetime.now().strftime("%H:%M") < until:
        r = push(D)
        if r in ("done", "no-cards"):
            if r == "done":
                digest(D)
            return
        time.sleep(60)


# ---------------------------------------------------------------- 收尾: 一致率 + 读法入库
def digest(D):
    from claude_call import call
    st = json.loads((OUT / D / "cards.json").read_text(encoding="utf-8"))
    if st.get("digested"):
        return
    items = [{"id": cid, "mentor": st["cards"][cid]["mentor"], "票": st["cards"][cid]["facts"]["票"], "动作": st["cards"][cid]["facts"]["导师动作"],
              "事实": st["cards"][cid]["facts"], "我的猜测": st["cards"][cid].get("guess"), "用户答案": (st["answers"].get(cid) or {}).get("text")} for cid in st["order"]]
    prompt = ("下面是今天的导师核对卡: 每张有事实、我封存的猜测、用户给的答案。\n"
              "①对每张按三项打分(理由 / 关键因素 / 复用条件), 每项 对 / 部分 / 错; ②把用户的纠正抽成「读法」—— 读法是一种看盘方法(怎么读情境), 不是某只票的结论;"
              " 每条读法写: 名称 / 什么时候用(触发条件, 尽量能用数据判定) / 怎么读 / 来源卡 id / 能不能机械化(能的话写特征口径)。和已有读法重复的写「强化 R-xx」。\n"
              "输出 ```json {\"scores\":[{\"id\":…, \"理由\":…, \"关键因素\":…, \"复用条件\":…}], \"methods\":[{\"name\":…, \"when\":…, \"how\":…, \"from\":[…], \"mech\":…}]}\n\n"
              f"# 已有读法库\n{READ_F.read_text(encoding='utf-8')[-6000:] if READ_F.exists() else '(空)'}\n\n# 今天的卡\n```json\n{json.dumps(items, ensure_ascii=False, indent=1)}\n```")
    r = call(prompt, tag="mentor-cards-digest", permission="default", timeout=900, json_schema={"type": "object"})
    j = r.parsed if getattr(r, "ok", False) and isinstance(getattr(r, "parsed", None), dict) else None
    if not j:
        log("digest 失败")
        return
    sc = j.get("scores") or []
    rate = {k: round(sum(1 for x in sc if x.get(k) == "对") / len(sc) * 100) if sc else None for k in ("理由", "关键因素", "复用条件")}
    st.update(digested=dt.datetime.now().isoformat(timespec="seconds"), scores=sc, rate=rate)
    (OUT / D / "cards.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    L = [] if READ_F.exists() else ["# market-skill · 读法库(用户核对卡纠正抽出来的看盘方法; 状态 = 待核销, 够 2 个情境相近的样例 = 核销; 10/28 建)", ""]
    for m in j.get("methods") or []:
        L += [f"### {m.get('name')} [读法 · {D} · 来源 {', '.join(m.get('from') or [])} · 待核销]", f"- 什么时候用: {m.get('when')}", f"- 怎么读: {m.get('how')}", f"- 机械化: {m.get('mech')}", ""]
    with READ_F.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    with (OUT / "consistency.csv").open("a", encoding="utf-8") as fh:
        fh.write(f"{D},{len(sc)},{rate['理由']},{rate['关键因素']},{rate['复用条件']}\n")
    log(f"digest 完成: 一致率 {rate}, 新读法 {len(j.get('methods') or [])} 条")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "push", "watch", "digest"])
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--no-guess", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--until", default="23:30")
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.date, a.no_guess)
    elif a.cmd == "push":
        print(push(a.date, a.dry))
    elif a.cmd == "watch":
        watch(a.date, a.until)
    else:
        digest(a.date)


if __name__ == "__main__":
    main()
