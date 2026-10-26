# -*- coding: utf-8 -*-
"""selftest.py — paper v3 桩测试(不调模型、不推微信、写到假日期 2099-01-02 的目录, 测完删)

断言(10/19 立法: 自测要断言该发生的事发生了, 不只看没报错):
  ①09:00 启动 → 落第 1 版策略, 会话已"启动", 版本目录有 00_boot_msg.md / 01_facts.md / 06.json / timing.json
  ②09:00 版是草稿(竞价单没挂); 09:20:30 竞价复核落地 → 竞价单挂出(auc_submitted), 且竞价段没跑 05
  ③09:25 竞价撮合: 买单按撮合价成交 → 持仓 + 现金减少(含费用) + 股票 T+1 今天不可卖
  ④盘中触发不重新启动(没有 00_boot_msg.md, 有 00_trigger_msg.md), 跑了 05
  ⑤结构化失效条件: 10:30 时间止损(价格没到 unless) → 叫醒; 同一条只叫一次
  ⑥计划模式账: "本链成交" / "心跳" 不叫醒; 出 band 叫醒
  ⑦决策 T 线: 非本线标的被剔
  ⑧收盘: nav.csv 有一行, summary.md 里没有"影子"
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/paper_line/selftest.py
"""
import datetime as dt
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper_line"))
import executor as E   # noqa: E402
import tempfile   # noqa: E402
E.MEMDIR = E.pack.MEMDIR = Path(tempfile.mkdtemp()) / "memory"   # 本线记忆写临时目录, 不污染明天的启动材料
E.LIVE = Path(tempfile.mkdtemp()) / "_live"   # 10/24 修: 账本根也换临时目录 —— 原来 2099 测试日会把 results/_live 里最近一天(10/23 真实账本)当起点仓位, 6 项断言因此失败
E.LIVE.mkdir(parents=True)

D = "2099-01-02"
import os   # noqa: E402
os.environ["EXEC_FULL_PAUSE"] = "0"   # 同 executor.main(v3 不停触发)
os.environ["LIVE_LINE"] = "0"   # 10/24: 基础用例按 lines.json 的 paper v3 账本跑; 实盘线用例(live_tests)自己临时打开
CLK = {"t": "09:00:05"}
E.X.now = lambda: dt.datetime.combine(dt.date.fromisoformat(D), dt.time.fromisoformat(CLK["t"]))   # 假钟(exec_base 里所有 now() 都走它)
OK, BAD = [], []


def check(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(("✅ " if cond else "❌ ") + name + (f"  [{info}]" if info and not cond else ""))


def settle(e, n=3000):
    t0 = time.time()
    for _ in range(n):
        if not e.pending:
            evs = [x for x in e._events() if x.get("kind") in ("重定异常", "重定失败")]
            if evs:
                print("   事件:", evs[-1])
            print(f"   (落地 {time.time() - t0:.1f} 秒)")
            return
        time.sleep(0.1)
    raise AssertionError("等链落地超时: " + str(e._events()[-3:]))


def latest_vd(e):
    return sorted((e.dir / "versions").iterdir())[-1]


def live_tests(base):
    """㊻ 实盘线(10/24 模块 5): 动态线 / 留下名单 / 休眠 / 盘前串行 / 推送 / 盘前首跑预算"""
    import live as LV
    import mentor_select as MS
    pk = E.pack
    sel = {"D": D, "ranked": [{"id": "zhiyingjuexin", "ret20": 75.4, "avg": 2.95}, {"id": "liuyiqing", "ret20": 19.7, "avg": 1.05}, {"id": "buchitudou0", "ret20": 21.4, "avg": 0.99}],
           "premarket": ["zhiyingjuexin", "liuyiqing", "buchitudou0", "zuoshoudeirong", *MS.UPS], "keep": None}
    old_path, old_env = MS.path, {k: os.environ.get(k) for k in ("LIVE_LINE", "LIVE_KEEP_AT", "LIVE_DEFAULT_KEEP", "PAPER_PUSH_LINES")}
    tmp = base / "_sel" / "selected_mentors.json"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    MS.path = lambda d: tmp
    try:
        tmp.write_text(json.dumps(sel, ensure_ascii=False), encoding="utf-8")
        os.environ.update(LIVE_LINE="1", LIVE_KEEP_AT="09:19:00", LIVE_DEFAULT_KEEP="3", PAPER_PUSH_LINES="")
        L = pk.lines(D)
        check("㊻实盘线: 线按名单动态生成(导师按排名在前 + UP 在后(10/25 起只有桃哥 / 卢本圆), 线号 live_<skill>, UP 标 role=UP)",
              list(L)[:4] == ["live_zhiyingjuexin", "live_liuyiqing", "live_buchitudou0", "live_zuoshoudeirong"] and len(L) == 4 + len(MS.UPS)
              and L["live_taoge"]["role"] == "UP" and all(x["live"] and x["mode"] == "watch" for x in L.values()), str(list(L)))
        check("㊻留下名单: 没挑 = 默认入选导师前 3 位(不含 UP)", pk.keep_of(D) == {"zhiyingjuexin", "liuyiqing", "buchitudou0"}, str(pk.keep_of(D)))
        ids, bad = LV.resolve(D, ["芷影", "桃哥skill", "王五"])
        check("㊻名字认: 前缀 / 带 skill 后缀都认, 不在名单的报出来", ids == ["zhiyingjuexin", "taoge"] and bad == ["王五"], f"{ids} {bad}")
        LV.set_keep(D, ["zhiyingjuexin", "taoge"])
        k1 = pk.keep_of(D)
        LV.set_keep(D, ["zhiyingjuexin", "taoge"], "drop")
        k2 = pk.keep_of(D)
        LV.set_keep(D, ["liuyiqing"], "add")
        check("㊻留下 / 全部收束(= 空, 不回默认) / 加回", k1 == {"zhiyingjuexin", "taoge"} and k2 == set() and pk.keep_of(D) == {"liuyiqing"}, f"{k1} {k2} {pk.keep_of(D)}")
        LV.set_keep(D, ["liuyiqing"])
        CLK["t"] = "09:10:00"
        ez, el = E.V3(L["live_zhiyingjuexin"], D, fake=True), E.V3(L["live_liuyiqing"], D, fake=True)
        d_pre = (ez.dormant(), el.dormant())
        ez.restrategize("开盘前首版策略", counted=False)
        settle(ez)
        CLK["t"] = "09:20:00"
        ez._keep_t = el._keep_t = 0
        n0 = ez.n_all
        ez.restrategize("竞价段正式版(看 09:20 后可信竞价)", counted=False, tag="auction")
        ez.need_re("09:31", [{"side": "BUY", "code": "600000"}])
        check("㊻休眠: 09:19 前都叫模型; 之后没留下的不叫(竞价复核 / 成交都不叫), 留下的照叫",
              d_pre == (False, False) and ez.ver == 1 and ez.dormant() and not el.dormant() and ez.n_all == n0, f"{d_pre} ver={ez.ver} n={ez.n_all}")
        sent, queued = [], []
        orig = E.X.subprocess.Popen
        E.X.subprocess.Popen = lambda *a, **k: sent.append(a[0])
        import os as _os2
        sys.path.insert(0, str(ROOT / "scripts" / "hermes"))
        import push_bus as _PB
        enq0 = _PB.enqueue
        _PB.enqueue = lambda text, src="", urgent=False, key=None, D=None: queued.append((src, urgent, key, text[:40]))
        try:
            _os2.environ["PUSH_BUS"] = "0"   # 旧路径: 直接调 wx_send
            for b in (ez, el):
                b.fake = False
                b.wx("【x v3 执行器 成交 09:31:00】BUY 600000 100@10")
                b.fake = True
            _os2.environ["PUSH_BUS"] = "1"   # 10/25 合并推送总线: 只进队列, 成交 = 急件, 不直接发
            n_direct = len(sent)
            for b in (ez, el):
                b.fake = False
                b.wx("【x v3 执行器 成交 09:31:00】BUY 600000 100@10")
                b.fake = True
        finally:
            E.X.subprocess.Popen = orig
            _PB.enqueue = enq0
            _os2.environ.pop("PUSH_BUS", None)
        check("㊻推送: 09:19 后只推留下的线(不看 PAPER_PUSH_LINES)", n_direct == 1 and "live_liuyiqing" in sent[0], str(sent)[:200])
        check("㊽合并推送总线: PUSH_BUS=1 时留下的线只进队列(成交算急件), 不再直接调 wx_send; 没留下的照样不推",
              len(sent) == n_direct and len(queued) == 1 and queued[0][0] == "live_liuyiqing" and queued[0][1] is True, str(queued)[:200])
        # ---- ㊽ 少重写 ②: 06 机械错误代码自动修 ----
        r_a = {"id": "r1", "side": "买", "op": ">=", "px": 10.0071, "qty": 250}
        r_b = {"id": "r2", "side": "SELL", "op": ">=", "px": 99.0, "qty": 900}
        fa = E.X.autofix_rule("600000", r_a, 0, 11.0, 9.0)
        fb = E.X.autofix_rule("600000", r_b, 500, 11.0, 9.0)
        check("㊽06 自动修: 方向 买→BUY、op 按方向改、价格取到最小价位(买向下)、股数取到 100 的倍数; 卖价超涨停压到涨停价、卖量超可卖压到可卖",
              r_a["side"] == "BUY" and r_a["op"] == "<=" and abs(r_a["px"] - 10.0) < 1e-9 and r_a["qty"] == 200 and len(fa) == 4
              and r_b["px"] == 11.0 and r_b["qty"] == 500, f"{r_a} {fa} | {r_b} {fb}")
        # ---- ㊽ 叫醒只发增量(10/25 用户认可第 1 招) ----
        fx = "头\n## 今日盘前资讯\n早报 A\n## 昨日龙虎榜\n席位 X\n## 市场扫描(09:00)\n涨幅榜 1\n"
        ez._facts_sent_secs = {}
        ez._facts_delta(fx)   # 盘前首跑登记
        d1 = ez._facts_delta(fx.replace("涨幅榜 1", "涨幅榜 2"))
        import chain_steps as CS_
        CS_.LAST_ROWS.clear()
        inc_ = {"600000": (10.0, 1.0, 4.0), "000001": (10.0, 1.0, 4.0)}
        st_ = {"cash": 100000, "positions": {}, "trades": []}
        pool0_ = CS_.pool
        CS_.pool = lambda *a_, **k_: {"600000": "事实包", "000001": "事实包", "600001": "事实包"}
        feat0_ = CS_.feat
        CS_.feat = lambda c, *a_, **k_: {"p": 10.0, "chg": {"600000": 1.2, "000001": 4.0, "600001": 0.5}[c], "amp": 4.0}
        try:
            f01_, *_ = CS_.build_01("zhiyingjuexin", D, "10:00:00", "测试", st_, None, set(), {}, "(事实)", "(开盘)", "", live=False, inc=inc_)
        finally:
            CS_.pool, CS_.feat = pool0_, feat0_
        check("㊽叫醒只发增量: 事实包没变的小节不重发(列出名字); 候选池只列 新进池 / 涨跌变动 ≥ 振幅一半的行, 其余写'另 N 只没明显变化'",
              "早报 A" not in d1 and "席位 X" not in d1 and "涨幅榜 2" in d1 and "今日盘前资讯" in d1.split("不重发")[-1]
              and "| 600001 |" in f01_ and "| 000001 |" in f01_ and "| 600000 |" not in f01_ and "另 1 只" in f01_, d1[-200:] + " || " + f01_[-300:])
        # ---- ㊼ 模块 6 / 7: 计划情景 + 竞价对照 + 电报备注 ----
        pc = E.X.prev_close("600000", D) or 10.0
        up = round(pc * 1.1, 2)
        el.strategy = {"codes": [{"code": "600000", "name": "浦发银行", "band": [round(pc * 0.9, 2), up], "rules": [
            {"id": "r1", "side": "BUY", "op": "<=", "px": round(pc * 1.05, 2), "qty": 100, "auction": True, "why": "高开抢 依据：E1"},
            {"id": "r2", "side": "BUY", "op": "<=", "px": round(pc * 0.98, 2), "qty": 100, "why": "低开等回落 依据：E1"},
            {"id": "r3", "side": "BUY", "op": "<=", "px": round(pc * 0.95, 2), "qty": 100, "why": "兜底 依据：E1"}],
            "scenarios": [{"id": "S1", "when": "竞价涨幅 >= 3 且 未匹配买 > 未匹配卖", "action": "开盘买", "rules": ["r1"]},
                          {"id": "S2", "when": "竞价涨幅 < 3", "action": "等回落买", "rules": ["r2"]}]}]}
        el.fired = set()

        def setq(p, ub, us):
            el.feed.q["600000"] = {"p": round(p, 2), "t": "09:20:30", "b": [(round(p, 2), 1000), (round(p, 2), ub)], "k": [(round(p, 2), 1000), (round(p, 2), us)], "a1": round(p, 2), "b1": round(p, 2)}
        k_ = lambda r: f"{el.ver}:600000:{r}"   # noqa: E731
        setq(pc * 1.04, 5000, 100)
        import os as _os
        _os.environ["LIVE_AUC_SKIP"] = "1"   # 旧口径(全落在情景内就不叫模型)
        n1 = el.n_all
        el.strategy.pop("auc_submitted", None)
        el.restrategize("竞价段正式版(看 09:20 后可信竞价)", counted=False, tag="auction")
        a1 = (k_("r2") in el.fired, k_("r1") in el.fired, k_("r3") in el.fired, el.n_all == n1, bool(el.strategy.get("auc_submitted")))
        _os.environ["LIVE_AUC_SKIP"] = "0"   # 10/25 默认口径 = paper v3: 09:20 照样叫模型, 对照结果附在叫醒原因里
        why_seen = []
        orig_rs = E.V3.__mro__[1].restrategize
        E.V3.__mro__[1].restrategize = lambda self_, why, *a_, **k_: why_seen.append(why)
        try:
            el.strategy.pop("auc_submitted", None)
            el.restrategize("竞价段正式版(看 09:20 后可信竞价)", counted=False, tag="auction")
        finally:
            E.V3.__mro__[1].restrategize = orig_rs
            _os.environ.pop("LIVE_AUC_SKIP", None)
        check("㊽竞价复核默认同 paper v3: 全落在情景内也叫模型(叫醒原因里带'全部落在计划情景内'), 不提前挂竞价单",
              len(why_seen) == 1 and "全部落在计划情景内" in why_seen[0] and not el.strategy.get("auc_submitted"), str(why_seen)[:200])
        setq(pc * 0.99, 100, 5000)
        d2, h2 = el.scen_compare("09:25")
        a2 = (k_("r1") in el.fired, k_("r2") in el.fired)
        setq(pc * 1.04, 100, 5000)
        d3, _ = el.scen_compare("09:25")
        check("㊼竞价对照(LIVE_AUC_SKIP=1 旧口径): 落 S1 → 停用 S2 的单、不叫模型、竞价单照挂; 换到 S2 → r1 停 r2 恢复; 都不落 → 偏离; 没进任何情景的 r3 始终生效",
              a1 == (True, False, False, True, True) and a2 == (True, False) and not d2 and "S2" in h2[0] and d3 and "不在计划任何情景" in d3[0], f"{a1} {a2} {d2} {h2} {d3}")
        tl0 = pk.telegraph_links
        pk.telegraph_links = lambda D_, upto="": {"600000": [("09:31:05", "https://www.cls.cn/detail/1", "x")]}
        try:
            s9, _ = el.check(json.loads(json.dumps({"codes": [{k: v for k, v in el.strategy["codes"][0].items()}]})))
        finally:
            pk.telegraph_links = tl0
        w9 = [r["why"] for x in s9["codes"] for r in x["rules"]]
        check("㊼电报备注: 06 写到电报点名的票, 每张单 why 末尾补 '09:31:05 CLS电报点名 链接'", w9 and all("09:31:05 CLS电报点名 https://www.cls.cn/detail/1" in w for w in w9), str(w9)[:200])
        long = "📋 汇总\n" + "\n".join(f"{i}. 线{i}\n" + "x" * 900 for i in range(1, 6))
        ch = LV.chunks(long)
        check("㊼盘前汇总切条: 每条 ≤ 2800 字 + 序号, 不丢字", all(len(c) <= 2810 for c in ch) and len(ch) >= 2 and ch[0].startswith("(1/") and sum(c.count("x") for c in ch) == 4500, str([len(c) for c in ch]))
        books = {"live_zhiyingjuexin": ez, "live_liuyiqing": el}
        ids7 = list(L)
        T = {"t": dt.datetime(2099, 1, 2, 8, 35)}

        def fsleep(s):
            T["t"] += dt.timedelta(seconds=s)
        os.environ["LIVE_BOOT_GROUP"] = "3"
        w1 = LV.boot_wait(1, ids7, books, now=lambda: T["t"], sleep=fsleep)   # 0 号已回来 → 不等
        os.environ["LIVE_BOOT_WAIT"] = "30"
        w4 = LV.boot_wait(4, ids7, books, now=lambda: T["t"], sleep=fsleep)   # 第 2 组等 1~3 号, 2 / 3 号没建 → 等到上限
        os.environ["LIVE_BOOT_GROUP"] = "99"   # 10/25 用户定: 第 1 条回来后其余全部一起放行
        w4b = LV.boot_wait(4, ids7, books, now=lambda: T["t"], sleep=fsleep)
        os.environ.pop("LIVE_BOOT_WAIT", None)
        os.environ.pop("LIVE_BOOT_GROUP", None)
        check("㊻盘前串行: 第 1 本回来后第 1 组不等; 后一组等前一组(等不到按上限放行); GROUP=99 时第 2 条起只等第 1 条", w1 == 0 and 30 <= w4 <= 66 and w4b == 0, f"{w1} {w4} {w4b}")
        dg = LV.digest_text(D, {"live_liuyiqing": el, "live_zhiyingjuexin": ez}, sel)   # 故意倒序传入
        check("㊻盘前汇总: 每条线一段(<中文名>skill + 近 20 日表现)+ 怎么留下; 编号按盘前名单顺序(不按建本先后)",
              "1. 芷影攫心skill（近20日 +75.4%" in dg and "留下 1、3" in dg and "2. 刘忆青" in dg and dg.index("1. 芷影") < dg.index("2. 刘忆青"), dg[:300])
        import types as _ty
        q2 = []
        sys.path.insert(0, str(ROOT / "scripts" / "hermes"))
        import push_bus as _PB2
        enq_b, on_b = _PB2.enqueue, _PB2.on
        _PB2.enqueue, _PB2.on = (lambda text, src="", urgent=False, key=None, D=None: q2.append((src, text))), (lambda: True)
        late_b = {"live_zhiyingjuexin": ez, "live_liuyiqing": _ty.SimpleNamespace(strategy=None, line=el.line)}
        T2 = {"t": dt.datetime(2099, 1, 2, 9, 13), "n": 0}

        def fsleep2(s_):
            T2["t"] += dt.timedelta(seconds=s_)
            T2["n"] += 1
            if T2["n"] == 2:   # 补发线程第 2 轮时刘忆青盘前版落地
                late_b["live_liuyiqing"] = el
        try:
            LV._late_digest(D, lambda: late_b, ["live_liuyiqing"], now=lambda: T2["t"], sleep=fsleep2)
        finally:
            _PB2.enqueue, _PB2.on = enq_b, on_b
        check("㊽盘前汇总迟到补发: 09:12 没赶上的线, 盘前版落地后进合并推送总线补发一次(编号仍是名单序号)",
              len(q2) == 1 and q2[0][0] == "live_digest" and "补发" in q2[0][1] and "2. 刘忆青" in q2[0][1], str(q2)[:200])
        os.environ["BOOT_MAX_KB"] = "120"
        lnz = L["live_zhiyingjuexin"]
        txt, st = pk.boot_msg(lnz, D, "(01)", {}, {}, {"positions": {}}, "(02)")
        os.environ.pop("BOOT_MAX_KB", None)
        b_ = st.get("budget") or {}
        check("㊻盘前首跑预算: 超上限逐级省(每级不增大), 注明省了什么 + 去哪查全文; 实盘线说明在",
              b_.get("level", 0) >= 1 and all(x >= y for x, y in zip(b_["kb_by_level"], b_["kb_by_level"][1:])) and "盘前首跑材料按上限 120KB 省了" in txt and "本线是**实盘线**" in txt, str(b_))
    finally:
        MS.path = old_path
        for k, v in old_env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        pk._SEL.clear()


def run():
    base = E.LIVE / D   # 10/24: 跟着临时账本根走(不再碰 results/_live)
    shutil.rmtree(base, ignore_errors=True)
    L = E.lines()
    try:
        # ---------- 主线(刘忆青 chain) ----------
        e = E.V3(L["liuyiqing"], D, fake=True)
        e.restrategize("开盘前首版策略", counted=False)
        settle(e)
        vd = latest_vd(e)
        check("①启动落第 1 版策略", e.ver == 1 and bool((e.strategy or {}).get("codes")), f"ver={e.ver}")
        check("①会话已启动", e.sess.booted)
        check("①版本目录齐全", all((vd / f).exists() for f in ("00_boot_msg.md", "01_facts.md", "06.json", "timing.json")), str(list(p.name for p in vd.iterdir())))
        bmsg = (vd / "00_boot_msg.md").read_text(encoding="utf-8") if (vd / "00_boot_msg.md").exists() else ""
        check("㊲拟人线启动材料有 market-skill 规则(M1~M4) + 转债正股表的位置", "盘面共性知识 market-skill" in bmsg and "### M3" in bmsg, bmsg[:80])
        check("②09:00 版是草稿(竞价单没挂)", not e.strategy.get("auc_submitted"))
        CLK["t"] = "09:20:30"
        e.restrategize("竞价段正式版(看 09:20 后可信竞价)", counted=False, tag="auction")
        settle(e)
        vd = latest_vd(e)
        check("②竞价复核落地且竞价单挂出", e.ver == 2 and bool(e.strategy.get("auc_submitted")), f"ver={e.ver} sub={e.strategy.get('auc_submitted')}")
        check("②竞价段跳过 05", not (vd / "05.md").exists())
        check("②竞价复核是触发不是重启", (vd / "00_trigger_msg.md").exists() and not (vd / "00_boot_msg.md").exists())
        fr = (vd / "06_fresh.md").read_text(encoding="utf-8") if (vd / "06_fresh.md").exists() else ""
        check("⑬06 前现取了此刻竞价", "此刻竞价" in fr, fr[:80])
        c = e.strategy["codes"][0]["code"]
        px = e.strategy["codes"][0]["rules"][0]["px"]
        cash0 = e.state["cash"]
        CLK["t"] = "09:25:04"
        e.feed.q[c] = {"p": round(px * 0.99, 3), "t": "09:25:03", "b1": round(px * 0.99, 3), "a1": round(px * 0.991, 3)}
        fills = e.tick("09:25", auction=True)
        pos = e.state["positions"].get(c, {})
        check("③竞价成交", len(fills) == 1 and pos.get("qty", 0) > 0, f"fills={fills}")
        amt = round(px * 0.99, 3) * pos.get("qty", 0)
        check("③现金按成交额 + 费用减少", abs((cash0 - e.state["cash"]) - (amt + max(5.0, amt * 0.00025))) < 0.05, f"{cash0}→{e.state['cash']}")
        check("③股票 T+1 今天不可卖", pos.get("sellable", -1) == (pos.get("qty") if c.startswith(("11", "12", "5", "15")) else 0), str(pos))
        # 盘中触发(成交后必判)
        CLK["t"] = "09:31:00"
        e.restrategize("竞价成交 BUY" + c, counted=False)
        settle(e)
        vd = latest_vd(e)
        check("④盘中触发不重新启动", (vd / "00_trigger_msg.md").exists() and not (vd / "00_boot_msg.md").exists())
        check("④盘中触发 05 = 机械风控(10/24): 写了 05_mech.json、没调模型 05", (vd / "05_mech.json").exists() and not (vd / "05.md").exists(), str([p_.name for p_ in vd.iterdir()]))
        fr = (vd / "06_fresh.md").read_text(encoding="utf-8") if (vd / "06_fresh.md").exists() else ""
        check("⑬盘中 06 前现取了此刻盘口", "此刻盘口" in fr, fr[:80])
        # 结构化失效条件: 时间止损
        v0 = e.ver
        e.feed.q[c] = {"p": round(px, 3), "t": "10:31:00", "b1": px, "a1": px}
        CLK["t"] = "10:31:00"
        e.last_re = E.X.now() - dt.timedelta(minutes=1)   # 冷却中也要叫醒(失效条件 = 必判)
        hits = e.wake_hits("10:31")
        check("⑤时间止损命中", len(hits) == 1, str(hits))
        check("⑤同一条只叫一次", e.wake_hits("10:32") == [])
        e.restrategize("; ".join(hits), counted=False)
        settle(e)
        check("⑤命中后叫醒出新版", e.ver == v0 + 1)
        # 10/22 23:4x 回放桩测出的死循环: 新版原样写回同一条时间止损 / 写进来时已成立的价格条件 → 不许立刻再响
        e.strategy["wake"] = [{"type": "time", "at": "10:30", "why": "同一时刻重写"}, {"type": "price", "code": c, "op": "<=", "px": round(px * 1.01, 3), "why": "写进来时已成立"}]
        check("㉚新版重写同一时间止损 / 已成立的价格条件不再响", e.wake_hits("10:33") == [], str(e.wake_hits("10:33")))
        e.sigma = lambda code_: 0.04 * px   # 固定 σ = 价格 4% → 上膛要退开 0.25σ = 1%(10/23 动态规则)
        e.feed.q[c] = {"p": round(px * 1.025, 3), "t": "10:34:00", "b1": px, "a1": px}
        CLK["t"] = "10:34:00"
        e.wake_hits("10:34")
        CLK["t"] = "10:34:20"
        e.wake_hits("10:34")
        e.feed.q[c] = {"p": round(px, 3), "t": "10:34:23", "b1": px, "a1": px}
        CLK["t"] = "10:34:23"
        check("㉚价格退开够远但不满 30 秒就回来, 不响", e.wake_hits("10:34") == [])
        e.feed.q[c] = {"p": round(px * 1.015, 3), "t": "10:35:00", "b1": px, "a1": px}
        for t_ in ("10:35:00", "10:37:05"):
            CLK["t"] = t_
            e.wake_hits(t_[:5])
        e.feed.q[c] = {"p": round(px, 3), "t": "10:37:10", "b1": px, "a1": px}
        CLK["t"] = "10:37:10"
        check("㉛退开不到 0.25σ(0.5% < 1%)待 2 分钟再回来, 不响(动态距离)", e.wake_hits("10:37") == [])
        e.feed.q[c] = {"p": round(px * 1.025, 3), "t": "10:37:20", "b1": px, "a1": px}
        for t_ in ("10:37:20", "10:37:55"):
            CLK["t"] = t_
            e.wake_hits(t_[:5])
        e.feed.q[c] = {"p": round(px, 3), "t": "10:38:00", "b1": px, "a1": px}
        CLK["t"] = "10:38:00"
        check("㉚价格条件 退开 ≥0.25σ 满 30 秒 → 成立 才响", len(e.wake_hits("10:38")) == 1)
        # 你的例子(冲高同理): 写 ≥25.0 叫醒; 10:00 到 25.0 响 → 新版重写 ≥25.0(此刻成立, 不响) → 跌穿够远(≥0.25σ)并待满 30 秒 → 再站上 = 再响
        e.strategy["wake"] = [{"type": "price", "code": c, "op": ">=", "px": round(px * 1.01, 3), "why": "冲高到位"}]
        e.ver += 1
        e.feed.q[c] = {"p": round(px * 1.012, 3), "t": "10:39:00", "b1": px, "a1": px}
        CLK["t"] = "10:39:00"
        check("㉚冲高: 新版写进来时已站上, 不响", e.wake_hits("10:39") == [])
        e.feed.q[c] = {"p": round(px * 0.995, 3), "t": "10:40:00", "b1": px, "a1": px}
        for t_ in ("10:40:00", "10:40:35"):
            CLK["t"] = t_
            e.wake_hits(t_[:5])
        e.feed.q[c] = {"p": round(px * 1.012, 3), "t": "10:41:00", "b1": px, "a1": px}
        CLK["t"] = "10:41:00"
        check("㉚冲高: 跌穿够远满 30 秒后再站上, 响", len(e.wake_hits("10:41")) == 1)
        del e.sigma
        e.ver -= 1
        e.strategy["wake"] = []
        CLK["t"] = "10:40:00"
        s_, dr_ = e.check({"view": "x", "codes": [], "wake": [{"type": "time", "at": "10:00", "why": "过去"}, {"type": "time", "at": "11:15", "why": "将来"}]})
        check("㉚时间止损写过去的时刻被剔除、将来的保留", [w["at"] for w in s_["wake"]] == ["11:15"] and any("10:00 已经过了" in d for d in dr_), str(dr_))
        # 上限从 10:30 起算
        n0 = e.n_re
        CLK["t"] = "10:05:00"
        e.restrategize("002181 出区间(测上限)")
        settle(e)
        check("⑩10:30 前自由触发不计上限", e.n_re == n0, f"n_re {n0}→{e.n_re}")
        CLK["t"] = "10:45:00"
        e.restrategize("002181 出区间(测上限)")
        settle(e)
        check("⑩10:30 后自由触发计上限", e.n_re == n0 + 1, f"n_re {n0}→{e.n_re}")
        # 满仓 / 06 判"今天不再操作" 不停触发
        v0 = e.ver
        e._rest_stop = True
        cash_bak, e.state["cash"] = e.state["cash"], 1.0
        CLK["t"] = "11:05:00"
        e.restrategize("002181 出区间(测不停触发)")
        settle(e)
        e.state["cash"] = cash_bak
        check("⑪满仓 + 06 判停 仍叫醒", e.ver == v0 + 1, f"ver {v0}→{e.ver}")
        # 收盘
        e.close()
        nav = (e.dir / "nav.csv").read_text(encoding="utf-8").strip().splitlines()
        check("⑧nav.csv 有一行", len(nav) == 1, str(nav))
        check("⑧summary 没有'影子'", "影子" not in (e.dir / "summary.md").read_text(encoding="utf-8"))
        mf = E.MEMDIR / "liuyiqing.md"
        check("㉑收盘写了本线记忆(临时目录)", mf.exists() and f"## {D} 收盘" in mf.read_text(encoding="utf-8") and not (E.PAPER_DIR_REAL / "memory" / "liuyiqing.md").exists() if hasattr(E, "PAPER_DIR_REAL") else mf.exists(), str(mf))
        # ---------- 计划模式账 ----------
        CLK["t"] = "09:00:25"
        k = E.V3(L["liuyiqing_plan"], D, fake=True)
        k.restrategize("开盘前首版策略", counted=False)
        settle(k)
        v0 = k.ver
        CLK["t"] = "10:00:00"
        k.restrategize("本链成交 BUY600000", counted=False)
        k.restrategize("心跳 30 分钟", counted=False)
        time.sleep(0.3)
        check("⑥计划模式: 成交 / 心跳不叫醒", k.ver == v0 and not k.pending)
        cc = k.strategy["codes"][0]
        k.feed.q[cc["code"]] = {"p": round(cc["band"][1] * 1.01, 3), "t": "10:00:00", "b1": 1, "a1": 1}
        k.last_re = E.X.now() - dt.timedelta(minutes=10)
        k.need_re("10:00", [])
        time.sleep(0.3)
        check("⑨出区间不满 60 秒不叫醒(去抖)", k.ver == v0 and not k.pending)
        CLK["t"] = "10:01:05"
        k.need_re("10:01", [])
        settle(k)
        check("⑥计划模式: 出 band 叫醒", k.ver == v0 + 1, f"ver {v0}→{k.ver}")
        check("⑰计划模式 10:30 前出 band 不计上限", k.n_re == 0, f"n_re={k.n_re}")
        CLK["t"] = "10:45:00"
        cc = k.strategy["codes"][0]
        k.strategy["wake"] = []
        k.feed.q[cc["code"]] = {"p": round(cc["band"][1] * 1.01, 3), "t": "10:45:00", "b1": 1, "a1": 1}
        k.last_re = E.X.now() - dt.timedelta(minutes=10)
        k.need_re("10:45", [])
        CLK["t"] = "10:46:05"
        k.need_re("10:46", [])
        settle(k)
        check("⑰计划模式 10:30 后出 band 计上限", k.n_re == 1, f"n_re={k.n_re}")
        k.cap, v1 = 1, k.ver
        CLK["t"] = "11:00:00"
        k.strategy["wake"] = []
        cc = k.strategy["codes"][0]
        k.feed.q[cc["code"]] = {"p": round(cc["band"][1] * 1.01, 3), "t": "11:00:00", "b1": 1, "a1": 1}
        k.last_re = E.X.now() - dt.timedelta(minutes=10)
        k.need_re("11:00", [])
        CLK["t"] = "11:01:05"
        k.need_re("11:01", [])
        time.sleep(0.3)
        check("⑰计划模式到上限后不再叫醒", k.ver == v1 and not k.pending, f"ver {v1}→{k.ver}")
        # ---------- 空仓提醒 ----------
        CLK["t"] = "09:00:45"
        z = E.V3(L["zhiying"], D, fake=True)
        z.restrategize("开盘前首版策略", counted=False)
        settle(z)
        z.D = "2026-10-23"   # 导师持仓统计要真实日期(假日期 2099 前 45 天没有快照)
        ratio, avg, n = z.mentor_hold()
        z.D = D
        check("⑫导师持仓统计有数", n > 0 and ratio is not None, f"{ratio} {avg} {n}")
        z.strategy["wake"] = []   # 去掉桩策略自带的 10:30 时间止损, 只测空仓提醒
        z._mhold = (0.9, 60.0, 20)   # 固定成"导师通常有仓位", 只测触发逻辑
        v0 = z.ver
        CLK["t"] = "10:30:05"
        z.need_re("10:30", [])
        settle(z)
        check("⑫10:30 空仓叫醒一次", z.ver == v0 + 1 and any("空仓提醒" in str(x.get("why")) for x in z._events() if x.get("kind") == "重定"))
        z.strategy["wake"] = []   # 桩 06 每版都带 10:30 时间止损, 去掉
        z.need_re("10:30", [])
        time.sleep(0.3)
        check("⑫同一时刻不重复叫", z.ver == v0 + 1 and not z.pending)
        z._mhold = (0.3, 10.0, 20)
        CLK["t"] = "13:30:05"
        z.strategy["wake"] = []
        z.last_re = E.X.now()   # 盯盘模式隔 3 小时会触发心跳, 把上次重定拨到现在, 只看空仓提醒
        z.need_re("13:30", [])
        time.sleep(0.3)
        check("⑫导师通常空仓 → 不叫", z.ver == v0 + 1 and not z.pending)
        # ---------- 统一叫醒队列(一个进程管多本账) ----------
        g = E.Gate(2)
        order = []

        def worker(pr, name):
            g.acquire(pr, name)
            order.append(name)
            time.sleep(0.15)
            g.release(name)
        ths = []
        for pr, name in ((5, "a5"), (5, "b5"), (1, "c1"), (3, "d3"), (0, "e0"), (2, "f2")):
            th = E.threading.Thread(target=worker, args=(pr, name))
            th.start()
            ths.append(th)
            time.sleep(0.01)
        for th in ths:
            th.join()
        check("⑭队列同时最多 n 个", max(x[4] for x in g.log if x[0] == "in") <= 2, str(g.log[:4]))
        check("⑭排队的按优先级出队", order[2:] == ["e0", "c1", "f2", "d3"], str(order))
        n0, E.GATE.n = E.GATE.n, 1
        E.GATE.log.clear()
        CLK["t"] = "10:40:00"
        bs = [E.V3(L[x], D, fake=True) for x in ("tudou", "liuyiqing_plan", "nasdaq")]
        for b_ in bs:
            b_.restrategize("开盘前首版策略", counted=False)
        for b_ in bs:
            settle(b_)
        E.GATE.n = n0
        check("⑭三本同时叫醒也串行(闸=1)", max(x[4] for x in E.GATE.log if x[0] == "in") <= 1 and sum(1 for x in E.GATE.log if x[0] == "in") == 3, str(E.GATE.log))
        # ---------- 排队单按挂单价成交(星光 10/22 例) ----------
        CLK["t"] = "10:50:00"
        st_ = E.V3(L["zhiying_noise"], D, fake=True)
        st_.feed.q["002076"] = {"p": 2.70, "t": "10:50:00", "b1": 2.70, "a1": 0}   # 封死涨停: 卖一空
        st_._pool = {"002076"}
        s_, _ = st_.check({"view": "x", "codes": [{"code": "002076", "band": [2.0, 3.0], "rules": [{"id": "r1", "side": "BUY", "op": "<=", "px": 2.70, "qty": 1000, "why": "排板"}]}]})
        st_.strategy, st_.ver = s_, 1
        st_.feed.q["002076"] = {"p": 2.58, "t": "10:50:03", "b1": 2.57, "a1": 2.58}
        f_ = st_.tick("10:50")
        check("⑮排板单开板时按 2.70 成交(不是 2.58)", len(f_) == 1 and f_[0]["px"] == 2.70, str(f_[:1]))
        st2 = E.V3(L["zhiying_noise"], D, fake=True)
        st2.feed.q["002076"] = {"p": 2.60, "t": "10:51:00", "b1": 2.59, "a1": 2.60}
        st2._pool = {"002076"}
        s2, _ = st2.check({"view": "x", "codes": [{"code": "002076", "band": [2.0, 3.0], "rules": [{"id": "r1", "side": "BUY", "op": "<=", "px": 2.65, "qty": 1000, "why": "立刻可成交"}]}]})
        st2.strategy, st2.ver = s2, 1
        f2 = st2.tick("10:51")
        check("⑮能立刻成交的单按对手价(卖一 2.60)成交", len(f2) == 1 and f2[0]["px"] == 2.60, str(f2[:1]))
        # ---------- 炸板接(星光 T 字板)+ 按盘口深度吃档 ----------
        CLK["t"] = "10:52:00"
        bd = E.V3(L["zhiying_noise"], D, fake=True)
        bd._pool = {"002076"}
        bd._lim = {"002076": 2.70}
        bd.feed.q["002076"] = {"p": 2.70, "t": "10:52:00", "b1": 2.70, "a1": 0, "b": [[2.70, 79745100]], "k": [[0.0, 0]]}
        sb, _ = bd.check({"view": "x", "codes": [{"code": "002076", "band": [2.0, 3.0], "rules": [
            {"id": "r9", "side": "BUY", "op": "<=", "type": "board_dip", "px": 2.65, "floor": 2.50, "qty": 3000, "why": "T字板回封 依据：R9"}]}]})
        bd.strategy, bd.ver = sb, 1
        f0 = bd.tick("10:52")
        check("⑯封死时炸板接不成交", f0 == [] and "002076" in bd._sealed, str(f0))
        bd.feed.q["002076"] = {"p": 2.58, "t": "10:52:03", "b1": 2.57, "a1": 2.58, "b": [[2.57, 5000]], "k": [[2.58, 800], [2.59, 40000], [2.60, 9000]]}
        f1 = bd.tick("10:52")
        check("⑯开板落在区间 → 按卖二 2.59 接", len(f1) == 1 and f1[0]["px"] == 2.59 and f1[0].get("board_dip"), str(f1[:1]))
        dp = E.V3(L["zhiying_noise"], D, fake=True)
        dp._pool = {"600000"}
        dp.feed.q["600000"] = {"p": 10.00, "t": "10:53:00", "b1": 9.99, "a1": 10.00, "b": [[9.99, 100]], "k": [[10.00, 500], [10.01, 2000], [10.02, 5000]]}
        sd, _ = dp.check({"view": "x", "codes": [{"code": "600000", "band": [9, 11], "rules": [{"id": "r1", "side": "BUY", "op": "<=", "px": 10.05, "qty": 1500, "why": "立刻买"}]}]})
        dp.strategy, dp.ver = sd, 1
        f2 = dp.tick("10:53")
        check("⑯立刻成交按深度吃档(500@10.00 + 1000@10.01)", len(f2) == 1 and f2[0]["qty"] == 1500 and abs(f2[0]["px"] - 10.007) < 0.001, str(f2[:1]))
        # ---------- 03 消融(芷影 + 多空并行分叉) ----------
        E.GATE.log.clear()
        CLK["t"] = "09:00:50"
        z3 = E.V3(L["zhiying_03"], D, fake=True)
        z3.restrategize("开盘前首版策略", counted=False)
        settle(z3)
        vd = latest_vd(z3)
        check("⑲带 03(10/24 一次调用): 启动写了 03.md、没有两个分叉", (vd / "03.md").exists() and not (vd / "03_bull.md").exists(), str([p_.name for p_ in vd.iterdir()]))
        check("⑲带 03(一次调用): 队列只占 1 个名额", any(x[0] == "in" and x[1] == "zhiying_03" and x[4] == 1 for x in E.GATE.log) and not any(x[0] == "in" and x[1] == "zhiying_03" and x[4] >= 3 for x in E.GATE.log), str(E.GATE.log[-2:]))
        CLK["t"] = "09:20:40"
        z3.restrategize("竞价段正式版(看 09:20 后可信竞价)", counted=False, tag="auction")
        settle(z3)
        vd = latest_vd(z3)
        check("⑲竞价复核不跑 03", not (vd / "03.md").exists() and not (vd / "03_bull.md").exists() and not (vd / "05.md").exists())
        CLK["t"] = "09:40:00"
        z3.restrategize("本链成交 BUY600000", counted=False)
        settle(z3)
        vd = latest_vd(z3)
        check("⑲盘中触发(一次调用): 变化 + 03 合成一条, 不再单独交 01", (vd / "03.md").exists() and not (vd / "01.md").exists() and not (vd / "03_bull.md").exists())
        # ---------- 前置条件 after + 决策T 本钱 ----------
        CLK["t"] = "10:55:00"
        af = E.V3(L["zhiying_noise"], D, fake=True)
        af._pool = {"600000"}
        af.state["positions"]["600000"] = {"qty": 1000, "cost": 10.0, "sellable": 1000}
        af.feed.q["600000"] = {"p": 10.00, "t": "10:55:00", "b1": 9.99, "a1": 10.00}
        sa, _ = af.check({"view": "x", "codes": [{"code": "600000", "band": [9, 11], "rules": [
            {"id": "r1", "side": "SELL", "op": ">=", "px": 10.20, "qty": 500, "why": "高抛"},
            {"id": "r2", "side": "BUY", "op": "<=", "px": 9.90, "qty": 500, "after": "r1", "why": "卖完再买回"}]}]})
        af.strategy, af.ver = sa, 7   # 版本号避开前面测试同一本账用过的 1:600000:r1
        af.feed.q["600000"] = {"p": 9.85, "t": "10:55:03", "b1": 9.84, "a1": 9.85}
        g1 = af.tick("10:55")
        check("⑳前置条件: 卖单没成交前买回单不生效", g1 == [], str(g1))
        af.feed.q["600000"] = {"p": 10.25, "t": "10:55:06", "b1": 10.24, "a1": 10.25}
        g2 = af.tick("10:55")
        af.feed.q["600000"] = {"p": 9.85, "t": "10:55:09", "b1": 9.84, "a1": 9.85}
        g3 = af.tick("10:55")
        check("⑳前置条件: 卖出成交后买回单才成交", len(g2) == 1 and g2[0]["side"] == "SELL" and len(g3) == 1 and g3[0]["side"] == "BUY", f"{g2} {g3}")
        bk = E.V3(L["bank"], D, fake=True)
        check("⑳决策T 起始现金 1 万", abs(bk.state["cash"] - 10000) < 1e-6 and abs(af.state["start"]["cash"] - 100000) < 1e-6, f"bank={bk.state['cash']}")
        bk.state["start"]["positions"] = {"601988": {"qty": 1000, "cost": 7.2, "sellable": 1000}}
        bk.state["positions"] = {"601988": {"qty": 700, "cost": 7.2, "sellable": 700}}
        bk.write_memory()
        mt = (E.MEMDIR / "bank.md").read_text(encoding="utf-8")
        check("㉑决策T 记下未完成的 T(少 300 股 = 隔夜反 T 待接回)", "隔夜反 T" in mt and "300" in mt, mt[-200:])
        # ---------- 计划模式 + 成交叫醒 ----------
        CLK["t"] = "09:01:10"
        pf = E.V3(L["zhiying_plan_fill"], D, fake=True)
        pf.restrategize("开盘前首版策略", counted=False)
        settle(pf)
        v0 = pf.ver
        CLK["t"] = "10:40:00"
        pf.last_re = E.X.now() - dt.timedelta(minutes=10)
        pf.strategy["wake"] = []   # 去掉桩策略自带的 10:30 时间止损, 只测成交叫醒
        pf.need_re("10:40", [{"side": "BUY", "code": "600000"}])
        settle(pf)
        check("㉒计划模式+成交叫醒: 成交叫醒且不计上限", pf.ver == v0 + 1 and pf.n_re == 0, f"ver {v0}→{pf.ver} n_re={pf.n_re}")
        k.need_re("10:40", [{"side": "BUY", "code": "600000"}])
        time.sleep(0.3)
        check("㉒普通计划模式: 成交不叫醒", not k.pending)
        # ---------- 穿价 + 成交量(中行 7.11 例) ----------
        CLK["t"] = "11:10:00"
        qb = E.V3(L["zhiying_noise"], D, fake=True)
        qb._pool = {"601988"}
        qb.feed.q["601988"] = {"p": 7.13, "t": "11:10:00", "b1": 7.12, "a1": 7.13, "v": 1000000, "b": [[7.12, 300000], [7.11, 500000]], "k": [[7.13, 200000]]}
        s_q, _ = qb.check({"view": "x", "codes": [{"code": "601988", "band": [6.5, 7.8], "rules": [{"id": "r1", "side": "BUY", "op": "<=", "px": 7.11, "qty": 1000, "why": "低吸"}]}]})
        qb.strategy, qb.ver = s_q, 9
        qb.feed.q["601988"] = {"p": 7.11, "t": "11:10:03", "b1": 7.11, "a1": 7.12, "v": 1100000, "b": [[7.11, 450000]], "k": [[7.12, 100000]]}
        f_a = qb.tick("11:10")
        qb.feed.q["601988"] = {"p": 7.11, "t": "11:10:06", "b1": 7.11, "a1": 7.12, "v": 1300000, "b": [[7.11, 300000]], "k": [[7.12, 100000]]}
        f_b = qb.tick("11:10")
        check("㉔碰到挂单价、成交量(30 万)没超过前面排队(50 万)不成交", f_a == [] and f_b == [], f"{f_a} {f_b}")
        qb.feed.q["601988"] = {"p": 7.11, "t": "11:10:09", "b1": 7.11, "a1": 7.12, "v": 1700000, "b": [[7.11, 100000]], "k": [[7.12, 100000]]}
        f_c = qb.tick("11:10")
        check("㉔累计成交(70 万)超过排队量后按 7.11 成交", len(f_c) == 1 and f_c[0]["px"] == 7.11, str(f_c))
        qb2 = E.V3(L["zhiying_noise"], D, fake=True)
        qb2._pool = {"601988"}
        qb2.feed.q["601988"] = {"p": 7.13, "t": "11:11:00", "b1": 7.12, "a1": 7.13, "v": 1000000, "b": [[7.12, 300000], [7.11, 500000]], "k": [[7.13, 200000]]}
        s_q2, _ = qb2.check({"view": "x", "codes": [{"code": "601988", "band": [6.5, 7.8], "rules": [{"id": "r1", "side": "BUY", "op": "<=", "px": 7.11, "qty": 1000, "why": "低吸"}]}]})
        qb2.strategy, qb2.ver = s_q2, 10
        qb2.feed.q["601988"] = {"p": 7.10, "t": "11:11:03", "b1": 7.09, "a1": 7.10, "v": 1050000, "b": [[7.09, 1000]], "k": [[7.10, 1000]]}
        f_d = qb2.tick("11:11")
        check("㉔价格穿过挂单价(7.10 < 7.11)直接按 7.11 成交", len(f_d) == 1 and f_d[0]["px"] == 7.11, str(f_d))
        # ---------- 停牌保护 ----------
        hs = E.V3(L["nasdaq"], D, fake=True)
        hs._pool = {"159941"}
        hs.feed.q["159941"] = {"p": 1.70, "t": "11:00:00", "b1": 0, "a1": 0}
        s_h, _ = hs.check({"view": "x", "codes": [{"code": "159941", "band": [1.5, 1.9], "rules": [{"id": "r1", "side": "BUY", "op": "<=", "px": 1.75, "qty": 1000, "why": "测停牌"}]}]})
        hs.strategy, hs.ver = s_h, 1
        CLK["t"] = "11:00:00"
        check("㉓停牌(买一卖一都空)不撮合", hs.tick("11:00") == [])
        # ---------- 动态上限 ----------
        caps = {k_: E.dyn_cap(L[k_], "2026-10-23") for k_ in ("zhiying", "liuyiqing", "tudou", "bank")}
        check("⑱动态上限在 [6, 20] 且决策T = 8", all(6 <= v <= 20 for v in caps.values()) and caps["bank"] == 8 and caps["zhiying"] > caps["liuyiqing"], str(caps))
        import math as _m
        pc = E.dyn_cap(L["liuyiqing_plan"], "2026-10-23")
        check("⑱计划模式上限 = 盯盘三位导师上限平均向上取整", pc == _m.ceil((caps["zhiying"] + caps["liuyiqing"] + caps["tudou"]) / 3) and pc == E.dyn_cap(L["tudou_plan"], "2026-10-23"), f"plan={pc} {caps}")
        # ---------- 决策 T 线 ----------
        CLK["t"] = "09:01:00"
        b = E.V3(L["bank"], D, fake=True)
        s, dropped = b.check({"view": "x", "codes": [{"code": "601988", "band": [7, 8], "rules": []}, {"code": "600000", "band": [7, 8], "rules": []}]})
        check("⑦决策 T 线剔掉非本线标的", [x["code"] for x in s["codes"]] == ["601988"] and any("600000" in d for d in dropped), str(dropped))
        # ---------- 必查: 强势股次日 + 导师卖点分位(10/22 晚用户批; 用真实日期, 002076 10/22 收盘三板封死) ----------
        txt, _ = E.pack.must_check(L["zhiying"], "2026-10-23", ["002076"], {"002076": "星光股份"}, {"positions": {"002076": {"qty": 100, "cost": 2.6, "days": 1}}})
        check("㉙必查有强势股次日 + 导师卖点分位(持仓给卖价参考)", "强势股次日: 2026-10-22 收盘 = 三板+" in txt and "导师卖点分位(动态)" in txt and "今天卖价参考" in txt, txt[-400:])
        # ---------- 排队位置沿用(10/23 彩排查出: 新版原样保留同一张排队单, 原来会重新排到队尾) ----------
        qb = E.V3(L["bank"], D, fake=True)
        qb.feed.q["601988"] = {"p": 7.20, "t": "09:31:00", "b1": 7.19, "a1": 7.20, "b": [[7.19, 100000], [7.18, 500000], [7.17, 860000]], "k": [[7.20, 1000]], "v": 1000000}
        rule = {"id": "r2", "side": "BUY", "op": "<=", "px": 7.17, "qty": 300}
        s1, _ = qb.check({"view": "x", "codes": [{"code": "601988", "band": [7.0, 7.4], "rules": [dict(rule)]}]})
        qb.strategy, qb.ver = s1, 2
        s1["codes"][0]["rules"][0].update(_vol=700000, _vlast=1700000)   # 已经推进了 70 万
        qb.feed.q["601988"]["b"] = [[7.19, 100000], [7.18, 500000], [7.17, 990000]]   # 后来又有人排到 7.17
        s2, _ = qb.check({"view": "y", "codes": [{"code": "601988", "band": [7.0, 7.4], "rules": [dict(rule)]}]})
        r2 = s2["codes"][0]["rules"][0]
        check("㉟新版原样保留同一张排队单: 沿用原排队位置(前面 86 万)和已推进量(70 万), 不重排队尾", r2.get("_ahead") == 860000 and r2.get("_vol") == 700000, str({k: r2.get(k) for k in ("_ahead", "_vol")}))
        # ---------- 10/25 条件单: 涨停价回落 3% 按买一卖 + 日内最高回落 2% 按买二卖(移动止盈) ----------
        CLK["t"] = "09:31:00"
        cb = E.V3(L["zhiying"], "2026-10-23", fake=True)
        cb.state = {"cash": 10000.0, "positions": {"002307": {"qty": 1000, "cost": 3.4, "sellable": 1000}}, "trades": [], "start": {}}
        cb.feed.q["002307"] = {"p": 3.73, "t": "09:31:00", "b1": 3.73, "a1": 0, "b": [[3.73, 900000], [3.72, 1000]], "k": []}
        sc, dc = cb.check({"view": "x", "codes": [{"code": "002307", "band": [3.3, 3.8], "rules": [
            {"id": "c1", "side": "SELL", "type": "cond", "ref": "涨停价", "dir": "down", "pct": 3, "book": "b1", "qty": 500, "why": "再炸板走一半 依据：E1"},
            {"id": "c2", "side": "SELL", "type": "cond", "ref": "日内最高", "dir": "down", "pct": 2, "book": "b2", "qty": 500, "why": "移动止盈 依据：E1"},
            {"id": "c3", "side": "SELL", "type": "cond", "ref": "开盘价", "dir": "up", "pct": 1, "book": "b1"}]}]})
        cb.strategy, cb.ver = sc, 1
        n_rules = len(sc["codes"][0]["rules"])
        f0 = cb._cond_tick("09:31")   # 封着: 没触发
        cb.feed.q["002307"] = {"p": 3.65, "t": "09:33:00", "b1": 3.65, "a1": 3.66, "b": [[3.65, 5000], [3.64, 8000]], "k": [[3.66, 3000]]}
        f1 = cb._cond_tick("09:33")   # 3.65 ≤ 3.73×0.97=3.618? 否 → c1 不触发; 日内最高 3.73 回落 2% = 3.655 → c2 触发, 按买二 3.64
        cb.feed.q["002307"] = {"p": 3.61, "t": "09:34:00", "b1": 3.61, "a1": 3.62, "b": [[3.61, 5000], [3.60, 8000]], "k": [[3.62, 3000]]}
        f2 = cb._cond_tick("09:34")   # 3.61 ≤ 3.618 → c1 触发, 按买一 3.61
        check("㊿条件单: 缺字段的剔掉 + 封着不动 + 日内最高回落 2% 按买二卖 + 涨停价回落 3% 按买一卖",
              n_rules == 2 and any("条件单字段不全" in d for d in dc) and not f0 and [(t["rule"][-2:], t["px"], t["qty"]) for t in f1] == [("c2", 3.64, 500)]
              and [(t["rule"][-2:], t["px"], t["qty"]) for t in f2] == [("c1", 3.61, 500)] and cb.state["positions"].get("002307") is None,
              str({"n": n_rules, "dc": dc, "f0": f0, "f1": [(t["rule"], t["px"]) for t in f1], "f2": [(t["rule"], t["px"]) for t in f2]}))
        wk = {"type": "cond", "code": "002307", "ref": "涨停价", "dir": "down", "pct": 2}
        cb.feed.q["002307"] = {"p": 3.60, "t": "09:40:00"}
        w0 = cb._cond(wk)   # 还没碰过涨停(本条叫醒刚建): 不成立
        cb.feed.q["002307"] = {"p": 3.73, "t": "09:41:00"}
        w1 = cb._cond(wk)   # 碰到涨停 → 上膛, 本跳不成立
        cb.feed.q["002307"] = {"p": 3.65, "t": "09:42:00"}
        w2 = cb._cond(wk)   # 3.65 ≤ 3.73×0.98=3.655 → 成立
        check("㊿叫醒条件 cond: 涨停价回落 2% —— 先碰到涨停才算, 之后回落到位才成立", (w0, w1, w2) == (False, False, True), str((w0, w1, w2)))
        # ---------- 10/26 06 选挂法: style + ratio → 规则出价格和数量 ----------
        CLK["t"] = "10:00:00"
        sb = E.V3(L["zhiying"], "2026-10-23", fake=True)
        sb.state = {"cash": 50000.0, "positions": {"002696": {"qty": 1400, "cost": 11.5, "sellable": 1400}}, "trades": [], "start": {}}
        sb.feed.q["002696"] = {"p": 10.30, "t": "10:00:00", "b1": 10.29, "a1": 10.30, "b": [[10.29, 5000]], "k": [[10.30, 5000]]}
        sb.feed.q["002724"] = {"p": 11.00, "t": "10:00:00", "b1": 10.99, "a1": 11.00, "b": [[10.99, 5000]], "k": [[11.00, 5000]]}
        sb._pool = {"002696", "002724"}   # 候选池里有才可以下单(基类校验"可用标的")
        ss, ds = sb.check({"view": "x", "codes": [
            {"code": "002696", "name": "百洋股份", "band_w": "中", "rules": [
                {"id": "s1", "side": "SELL", "style": "移动止盈", "ratio": 0.5, "why": "x 依据：R39"},
                {"id": "s2", "side": "SELL", "style": "追价", "ratio": 1, "px": 9.0, "why": "x 依据：R39"}]},
            {"code": "002724", "name": "海洋王", "band": [10, 12], "rules": [
                {"id": "s3", "side": "BUY", "style": "低吸", "ratio": 0.1, "why": "x 依据：R10"},
                {"id": "s4", "side": "BUY", "style": "瞎写", "ratio": 0.1, "why": "x"}]}]})
        sr = {r["id"]: r for x in ss["codes"] for r in x["rules"]}
        bw = [x for x in ss["codes"] if x["code"] == "002696"][0].get("band")
        check("㊿06 选挂法: 移动止盈→条件单 / 追价按现价算价且模型价只留档 / 低吸价 < 现价且按 ratio 算股数 / 不认识的挂法剔掉 / band_w 算出区间",
              sr["s1"].get("type") == "cond" and sr["s1"].get("qty") == 700 and sr["s2"].get("model_px") == 9.0 and sr["s2"].get("px", 0) > 10.0
              and 0 < sr["s3"].get("px", 99) < 11.0 and sr["s3"].get("qty", 0) >= 100 and "s4" not in sr and any("瞎写" in d for d in ds) and bw and bw[0] < 10.30 < bw[1],
              str({k: {kk: v.get(kk) for kk in ("type", "px", "qty", "model_px", "ttl")} for k, v in sr.items()}) + str(ds) + str(bw))
        # ---------- 10/25 全天守卫: 卖价远低于现价 → 改移动止盈条件单; 写了 now 的 / 条件单不动 ----------
        gb = E.V3(L["zhiying"], "2026-10-23", fake=True)
        gb.line = {**gb.line, "live": True}
        gb.state = {"cash": 10000.0, "positions": {"002696": {"qty": 1400, "cost": 11.5, "sellable": 1400}}, "trades": [], "start": {}}
        gb.wx = lambda *a, **k: None
        gb.strategy, gb.ver = {"codes": [{"code": "002696", "name": "百洋股份", "band": [8, 11], "rules": [
            {"id": "b1", "side": "SELL", "op": ">=", "px": 9.0, "qty": 700, "why": "x"},
            {"id": "b2", "side": "SELL", "op": ">=", "px": 9.0, "qty": 300, "now": True, "why": "止损"},
            {"id": "b3", "side": "SELL", "op": ">=", "px": 10.0, "qty": 400, "why": "离现价 <3% 不动"}]}]}, 3
        gb.feed.q["002696"] = {"p": 10.09, "t": "09:30:00", "b1": 10.08, "a1": 10.09, "b": [[10.08, 5000]], "k": [[10.09, 5000]]}
        gb._guard("09:30")
        rr = {r["id"]: r for r in gb.strategy["codes"][0]["rules"]}
        check("㊿全天守卫: 卖 9.00 vs 现价 10.09 → 改日内最高回落条件单; now 的和偏离 <3% 的不动",
              rr["b1"].get("type") == "cond" and rr["b1"].get("ref") == "日内最高" and 1.5 <= rr["b1"].get("pct", 0) <= 6 and rr["b2"].get("type") is None and rr["b3"].get("type") is None,
              str({k: (v.get("type"), v.get("ref"), v.get("pct")) for k, v in rr.items()}))
        # ---------- 触及概率(10/23 01:4x 用户批: 客观数, 不让模型主观估) ----------
        import fill_prob as FP
        fp = FP.prob("601988", "2026-10-22", "BUY", 7.12, 7.16, 7.25)
        lad = FP.ladder("601988", "2026-10-22", 7.24)
        txt2, _ = E.pack.must_check(L["bank"], "2026-10-23", ["601988"], {"601988": "中国银行"}, {"positions": {}})
        check("㊱触及概率: 单张单给 5 / 15 日 + 此刻口径, 价梯有买卖两边, 必查里有这一项",
              0 <= fp["p15"] <= 1 and fp.get("now_px") is not None and "买−1%→" in lad and "卖+1%→" in lad and "触及概率" in txt2, f"{fp} | {lad[:60]}")
        # ---------- 第一层新五项(10/23 凌晨用户批; 用真实日期 10/23, 关键数据缺了要大声失败) ----------
        D5 = "2026-10-23"
        mr, em, th, vs, cbt = (E.pack.mentor_recent("zhiyingjuexin", D5), E.pack.emotion_table(D5), E.pack.theme_top(D5),
                               E.pack.vs_mentor_yesterday(L["zhiying"], D5), E.pack.cb_turnover_top(D5))
        check("㉝材料包新五项都有内容: 导师近 20 日逐笔到 10/22 / 情绪表 ≥5 天 / 活跃题材 / 昨日对照 / 转债成交额前十",
              "2026-10-2" in mr and em.count("| 2026-") >= 5 and th.count("近 5 日涨停") >= 3 and len(vs) > 10 and cbt.count("转债(") + cbt.count("转2(") >= 10,
              f"mr={len(mr)} em={em.count('| 2026-')} th={th.count('近 5 日涨停')} vs={vs[:40]} cb={cbt[:60]}")
        # ---------- 缓存保温(10/23: 空闲满 50 分钟发一句短话续 1 小时缓存; 不占叫醒名额; 保温期间本账 pending) ----------
        kw = E.V3(L["zhiying"], D, fake=True)
        kw.fake = False
        kw.sess.st["sid"] = "x"
        calls = []
        kw.sess.ask = lambda text, rnd, timeout=0, boot=False: (calls.append(rnd), {"ok": True, "secs": 1, "usd": 0.1, "usage": {}})[1]
        CLK["t"] = "11:00:00"
        kw._last_ask = E.X.now() - dt.timedelta(minutes=49)
        kw._maybe_keepalive("11:00")
        no_early = not calls and not kw.pending
        kw._last_ask = E.X.now() - dt.timedelta(minutes=51)
        busy0 = E.GATE.busy
        kw._maybe_keepalive("11:00")
        for _ in range(50):
            if not kw.pending:
                break
            time.sleep(0.05)
        check("㉞缓存保温: 空闲不满 50 分钟不发; 满 50 分钟发一次、不占叫醒名额、发完放开 pending",
              no_early and calls == ["keep"] and not kw.pending and E.GATE.busy == busy0, f"{calls} pending={kw.pending}")
        # ---------- 推微信(10/23 用户令: 三本主线出现挂单就推; 挂单没变不推; 其他本不推) ----------
        sent, pop0 = [], E.X.subprocess.Popen
        E.X.subprocess.Popen = lambda args, **kw: sent.append(args[4])
        os.environ["PAPER_PUSH_LINES"] = "tudou,liuyiqing,zhiying"
        try:
            for lid in ("zhiying", "zhiying_plan"):
                w = E.V3(L[lid], D, fake=True)
                w.fake = False
                w.strategy = {"codes": [{"code": "002076", "band": [2.5, 2.8], "rules": [{"id": "r1", "side": "BUY", "op": "<=", "px": 2.6, "qty": 1000}]}]}
                w.strategy, sv = {"codes": []}, w.strategy
                w.wx("【zhiyingjuexin v3 执行器 v1 09:00】因: 开盘前首版策略")   # 盘前版没挂单也推
                w.strategy = sv
                w.wx("【zhiyingjuexin v3 执行器 v2 09:31】因: x")
                w.wx("【zhiyingjuexin v3 执行器 v3 09:35】因: y")   # 挂单没变
                w.strategy["codes"][0]["rules"][0]["px"] = 2.55
                w.wx("【zhiyingjuexin v3 执行器 v4 09:40】因: z")   # 挂单变了
                w.state.setdefault("trades", []).append({"t": "09:41:02", "code": "002076", "name": "星光股份", "side": "BUY", "px": 2.55, "qty": 1000, "why": "测试", "rule": "4:002076:r1"})
                w.wx("【zhiyingjuexin v3 执行器 成交 09:41】BUY 002076")
        finally:
            E.X.subprocess.Popen = pop0
            os.environ.pop("PAPER_PUSH_LINES", None)
        check("㉜主线挂单推微信: 盘前版必推 + 只推挂单变了的版本 + 成交; 计划模式那本不推", len(sent) == 4 and sent[0].startswith("📋 芷影") and "挂单" in sent[1] and sent[3].startswith("✅ 芷影"), str([m[:40] for m in sent]))
        # ---------- 10/24 harness: 04 内容闸 / 05 机械风控 / 新材料进必查 ----------
        H = E.H
        mat = "### 600851 海欣股份\n- E7 导师同票: 导师做过 2 次: 10-14 买(连板接力) → ⚠负样本 2026-10-15 卖出盈亏 -6.8%\n- E8 强势股次日: …"
        j4 = {"picks": [{"code": "600851", "action": "建", "why": "按导师 10-14 做海欣的同型手法 E7"}]}
        V = H.gate04(j4, "大概率封板", mat)
        check("㊲04 内容闸: 缺 depth / 缺 market_risk / 无出处的'大概率' 都报", any("depth" in v for v in V) and any("market_risk" in v for v in V) and any("大概率" in v for v in V), str(V))
        j4["picks"][0]["depth"] = {"same_form": "E8 中位 +3%, P10 −4%", "peers": "无数据", "lhb": "未上榜", "telegraph": "无点名",
                                   "after_buy": [{"close": "a", "next": "b", "sell": "c"}, {"close": "a", "next": "b", "sell": "c"}]}
        j4["market_risk"] = {"max_new": 1}
        check("㊲04 内容闸: 负样本(10-14)被写进买入理由 → 报", any("负样本" in v for v in H.gate04(j4, "", mat)), str(H.gate04(j4, "", mat)))
        s5 = {"codes": [{"code": "600001", "rules": [{"id": "r1", "side": "BUY"}]}, {"code": "600002", "rules": [{"id": "r1", "side": "BUY"}]}]}
        check("㊳05 机械风控: 新开超上限的买单被剔、暂停新买全剔", H.enforce05(json.loads(json.dumps(s5)), {"max_new": 1, "pause_buy": False}, set()) == ["600002:r1"]
              and len(H.enforce05(json.loads(json.dumps(s5)), {"max_new": 3, "pause_buy": True}, set())) == 2)
        m5 = H.mech05(L["zhiying"], "2026-10-23", {"start": {"cash": 100000, "positions": {}}, "trades": []}, 96000, 100000)
        check("㊳05 机械风控: 亏到 −4% 暂停新买、文本给 06 看", m5["pause_buy"] and m5["max_new"] == 0 and "暂停新买" in m5["text"], str(m5))
        import pack as PK
        mc, _ = PK.must_check(L["zhiying"], "2026-10-23", ["002307", "600851"], {"002307": "北新路桥", "600851": "海欣股份"}, {"positions": {}})
        check("㊴必查新材料: 同逻辑席位风格 / 题材梯队 / 负样本标签 / 全分布都在, 没有查询失败",
              all(k in mc for k in ("同逻辑·席位风格", "同逻辑·题材梯队", "⚠负样本", "次日最高: n=")) and "查询失败" not in mc, mc[:300])
        mc, _ = PK.must_check(L["tudou"], "2026-10-23", ["111024"], {"111024": "澳弘转债"}, {"positions": {}})
        check("㊴必查新材料: 转债相似日不再撞同名模块 + 有同债近期路径", "同债近期路径" in mc and "查询失败" not in mc, mc[:300])
        check("㊵近期规律: 澳弘 10/23 必查里有'尾盘低点后拉升'且带回测第二天出现率", "近期规律" in mc and "尾盘低点后拉升" in mc and "回测: 近期这样之后第二天出现" in mc, mc[mc.find("近期规律"):][:300])
        import pattern_scan as PS
        bt = PS._bt("cb")
        check("㊵近期规律: 常见事件(收盘低于开盘)回测无预测力 → 不当规律报", not any(p_["事件"] == "收盘低于开盘" and p_["判断"] == "近期常出现"
                                                                   for p_ in PS.scan([dict(f, **{"收/开": -1}) for f in PS.load_code("111024", "2026-10-23")], 10, "cb")[0]) and bt.get("收盘低于开盘"), str(bt.get("收盘低于开盘")))
        # 10/24 步骤边界 v2(用户: harness 约束每步输出 + 已有材料不许忽略)
        mat = ("[M大1] 开盘-09:48 ↓-1.38% | [M小1] 开盘-现在 ↓-3.14%\n"
               "### 111024 澳弘转债 (持仓)\n- E1 关键价位: 260 / 255\n- E2 近期规律: 10-09~10-22: 尾盘低点后拉升≥1.5% 近期 8/10(回测: 第二天出现 53%)\n"
               "- E3 导师同票: 10-20 买 +1.1% 正; 10-21 买 -1.65% ⚠负样本\n- E4 同债近期路径: 30分钟高 中位 +5.12% 最差 -5.28\n"
               "### 600851 海欣股份\n- E5 关键价位: 7.1\n- E6 题材: 机器人 主线 第 3 天\n- E7 同逻辑·席位风格: 打板型 次日最高中位 +2.1% 最差 -6.0%\n- E8 强势股次日: 次日收 中位 -0.5% P10 -5.2%\n")
        g2ok = {"attitude": "偏空", "why": ["小盘单边走弱 M小1"], "directions": [{"theme": "机器人", "ref": "E6", "src": ["涨停分析"], "against": "无"}], "vs_mech": "无",
                "flip_if": [{"type": "index", "code": "sz399303", "op": ">=", "pct": -1.0, "why": "小盘收复"}], "note": "", "up_views": {"桃哥": "T−1 说创业板超跌", "卢本圆": "没提", "趋势天哥": "等右侧大阳"}}
        check("㊶02 闸: 合格的过; 编号不存在 / 翻转条件写成文字 / 态度不在枚举 都拦",
              H.gate02(g2ok, "", mat) == [] and len(H.gate02(dict(g2ok, attitude="谨慎", why=["M小9 走弱"], flip_if=["指数转强就改"]), "", mat)) == 3,
              str(H.gate02(dict(g2ok, attitude="谨慎", why=["M小9 走弱"], flip_if=["指数转强就改"]), "", mat)))
        check("㊽02 UP 判断: up_views 缺任一位 UP(或空着)拦; 写'没提'算合格",
              any("up_views" in v for v in H.gate02(dict(g2ok, up_views={"桃哥": "x", "趋势天哥": "y"}), "", mat)) and H.gate02(g2ok, "", mat) == [], "")
        check("㊽02 方向证据: 方向没写来源(src)拦; why 只写来源标签(导师逆向 / 指数K线)也算出处",
              any("没写支持它的来源" in v for v in H.gate02(dict(g2ok, directions=[{"theme": "机器人", "ref": "E6"}]), "", mat))
              and H.gate02(dict(g2ok, why=["上证回到日线箱体下沿 指数K线"]), "", mat) == [], "")
        try:
            import market02_extra as MX2
            bl = dict(MX2.blocks("2026-10-26", "09:00:00"))
            mtx = next((v for k, v in bl.items() if k.startswith("导师近 3 个交易日")), "")
            ok_ = len(bl) == 5 and all(d in mtx for d in ("2026-10-21", "2026-10-22", "2026-10-23")) and "2026-10-20" not in mtx.split("逐日明细")[-1] \
                and sum(1 for v in bl.values() if "取不到" in v) == 0 and next(v for k, v in bl.items() if k.startswith("指数 K 线")).count("- ") == 4
        except Exception as e:   # noqa: BLE001
            ok_, mtx = False, repr(e)
        check("㊽02 方向证据包: 5 块都取到; 导师逐日明细正好 T−1 / T−2 / T−3 三天(10/26 → 10/21~10/23); 指数 4 个", ok_, mtx[:200])
        try:   # 10/25 用户选 A + B: 必查「电报点名」= 分类 + 这一类历史分布; 04 要回应(只记录不打回)
            import telegraph_now as TGN
            it = TGN.item("300308", "2026-10-23", "14:00:00") or ""
            matg = "### 300308 中际旭创\n- E15 电报点名: " + it + "\n"
            r_ok = H.tg_reply_check({"telegraph_reply": [{"code": "300308", "E": "E15", "选": "不选", "理由": "大涨类次日中位为负"}]}, matg)
            r_miss = H.tg_reply_check({}, matg)
            ok_t = ("这一类(大涨)" in it and "次日收盘" in it and "cls.cn/detail" in it and "telegraph_reply" in H.tg_reply_req(matg)
                    and r_ok["missing"] == [] and r_miss["missing"] == ["300308"] and "300308" in TGN.named("2026-10-23", "14:00:00"))
        except Exception as e:   # noqa: BLE001
            ok_t, it = False, repr(e)
        check("㊽电报点名(A/B): 必查给分类 + 这一类分布 + 链接; 04 要求写 telegraph_reply, 漏写只记 missing 不打回", ok_t, it[:200])
        a3 = lambda c, ty: {"claim": "x", "cite": c, "type": ty}   # noqa: E731
        g3ok = {"bear": {"args": [a3("E3", "样本"), a3("E8", "数据"), a3("M小1", "市况")], "reply_to_bull": "y"}, "bull": {"args": [a3("E2", "数据"), a3("E6", "题材"), a3("E7", "资金")], "reply_to_bear": "y"}}
        g3old = {"bear": {"score": 60, "args": [{"claim": "x", "cite": "E3"}]}, "bull": {"score": 40, "args": []}}
        check("㊶03 闸: 合格的过; 旧写法(打分 / 不够 3 条 / 没类型)拦; 有负样本时空方不引就拦",
              H.gate03(g3ok, mat) == [] and len(H.gate03(g3old, mat)) >= 2
              and any("负样本" in v for v in H.gate03({**g3ok, "bear": {"args": [a3("E2", "数据"), a3("E6", "题材"), a3("M小1", "市况")], "reply_to_bull": "y"}}, mat)), str(H.gate03(g3old, mat)))
        ck = {"价位": {"E": "E1", "影响": "无关", "结论": "持有不挂新单所以无关"}, "近期规律": {"E": "E2", "影响": "支持", "结论": "尾盘常拉升, 尾盘再卖"},
              "导师": {"E": "E3", "影响": "反对", "结论": "10-21 负样本", "回应": "设 255 止损"}, "同形态": {"E": "E4", "影响": "支持", "结论": "30分钟高中位 +5.12%"}}
        hold = {"code": "111024", "action": "持有", "checked": ck}
        check("㊶04 checked: 持仓逐类回应齐全 → 过", H.gate_checked(hold, mat, {"111024"}) == [], str(H.gate_checked(hold, mat, {"111024"})))
        check("㊶04 checked: 持仓没写 checked → 拦", H.gate_checked({"code": "111024", "action": "持有"}, mat, {"111024"}) != [])
        bad = dict(hold, checked={**ck, "同形态": {"E": "E4", "影响": "支持", "结论": "30分钟高中位 +9.9%"}, "近期规律": {"E": "E2", "影响": "无关", "结论": "x"}})
        vb = H.gate_checked(bad, mat, {"111024"})
        check("㊶04 checked: 编造的百分比 / 近期规律写无关 / 反对没回应 都拦",
              any("9.9%" in v for v in vb) and any("近期规律" in v for v in vb)
              and H.gate_checked(dict(hold, checked={**ck, "导师": {"E": "E3", "影响": "反对", "结论": "负样本"}}), mat, {"111024"}) != [], str(vb))
        buy1 = {"code": "600851", "action": "建", "checked": {"价位": {"E": "E5", "影响": "支持", "结论": "x"}, "题材": {"E": "E6", "影响": "支持", "结论": "主线"},
                                                              "龙虎榜": {"E": "E7", "影响": "反对", "结论": "最差 -6.0%", "回应": "小仓"}, "同形态": {"E": "E8", "影响": "无关", "结论": "x"}}}
        ms2 = {"建": 2, "加": 2, "减": 1, "清": 1}
        check("㊶04 证据门槛(函数本身, 门槛 2 时): 建仓只有 1 类支持(价位不算) → 记违规; 2 类支持 → 过",
              any("至少要 2 个类别" in v for v in H.gate_checked(buy1, mat, set(), ms=ms2))
              and H.gate_checked(dict(buy1, checked={**buy1["checked"], "同形态": {"E": "E8", "影响": "支持", "结论": "中位 -0.5% 但已低吸"}}), mat, set(), ms=ms2) == [],
              str(H.gate_checked(buy1, mat, set(), ms=ms2)))
        cf = H.cfg()
        check("㊶10/24 指引模式: 默认证据门槛 0 / on_fail=guide 不打回 / 06 越界按用户定强制剔单(drop)",
              H.gate_checked(buy1, mat, set()) == [] and cf["on_fail"] == "guide" and cf["only06"] == "drop", str((cf["min_support"], cf["on_fail"], cf["only06"])))
        s6w = {"codes": [{"code": "002307", "rules": [{"id": "r2", "side": "BUY"}]}]}
        d6w = H.enforce06(s6w, {"picks": [{"code": "600851", "action": "建"}]}, set(), (), dry=True)
        check("㊶06 越界 warn 模式: 报出来但不剔单", d6w == ["002307:r2(04 没选(建 / 加))"] and s6w["codes"][0]["rules"], str(d6w))
        check("㊶04 指引文字带示例(告诉模型怎么写, 不是只拦)", "示例" in H.req_checked(mat) and "市况联动" in H.req_checked(mat) or "示例" in H.req_checked(mat), H.req_checked(mat)[:200])
        s6 = {"codes": [{"code": "600851", "rules": [{"id": "r1", "side": "BUY"}]}, {"code": "002307", "rules": [{"id": "r2", "side": "BUY"}]},
                        {"code": "111024", "rules": [{"id": "r3", "side": "SELL"}, {"id": "r4", "side": "BUY"}]}, {"code": "300001", "rules": [{"id": "r5", "side": "BUY"}]}]}
        d6 = H.enforce06(s6, {"picks": [{"code": "600851", "action": "建"}, {"code": "111024", "action": "清"}]}, {"111024"}, {"300001"})
        check("㊶06 越界剔单: 04 没选的新开买 / 04 清仓的票再买 被剔; 04 建的、持仓卖、上一版已挂的保留",
              sorted(d6) == ["002307:r2(04 没选(建 / 加))", "111024:r4(04 判清仓)"] and [x["code"] for x in s6["codes"]] == ["600851", "111024", "300001"], str(d6))
        import market_path as MPa
        b22 = MPa.build("2026-10-22", "15:01:00")
        b23 = MPa.build("2026-10-23", "15:01:00")
        b23m = MPa.build("2026-10-23", "10:18:00")
        check("㊷大小盘路径: 10/22 沪深300 单边走弱(原型误判震荡); 10/23 收盘 弱转强@10:33; 10:18 反弹没破前高状态不翻",
              b22["大"]["tag"] == "单边走弱" and b23["大"]["tag"].startswith("弱转强@10:33") and b23m["大"]["tag"] == "单边走弱"
              and b23m["大"]["segs"][0]["from"] == "09:29", f'{b22["大"]["tag"]} / {b23["大"]["tag"]} / {b23m["大"]["tag"]}')
        import auction_path as APa
        S = APa.series("2026-10-23", "09:25:30", ["601988", "002724", "002307"])
        an = {c: APa.analyze(S.get(c), APa.prev_close(c, "2026-10-23")) for c in ("601988", "002724", "002307")}
        check("㊷竞价路径: 中行未匹配从卖翻到买不算撤单; 002724 09:19 撤买单抓到; 002307 09:20 前不在 3 秒名单也补到首价 09:15:09",
              not an["601988"].get("撤单") and any("撤买单" in x for x in an["002724"].get("撤单") or []) and an["002307"]["首价"][0] == "09:15:09",
              json.dumps({c: (a.get("撤单"), a["首价"]) for c, a in an.items()}, ensure_ascii=False)[:300])
        sys.path.insert(0, str(ROOT / "scripts" / "market"))
        import collect_mood as CMd
        dm = "2099-01-05"
        try:
            r0 = {"t": "09:40:02", "dist13": {k: 1 for k in CMd.BINS}, "rise": 3000, "fall": 2000, "flat": 100, "avg": 0.5, "zt": 40, "zb": 10, "dt": 5, "seal": 80,
                  "ladder": {"首板": 30, "2板": 6, "3板": 2, "4板+": 2}, "top": ["甲5板"]}
            CMd.write(dm, r0)
            CMd.write(dm, dict(r0, t="10:12:00", zt=55, zb=20, seal=73))
            b1, b0 = CMd.block(dm, "10:15:00"), CMd.block(dm, "09:30:00")
            check("㊸情绪面板: 13 档 + 涨停 / 炸板 / 封板率 / 梯队 + 30 分钟变化都在; 09:25 前(此刻之前无快照) = 暂无, 不偷看",
                  all(k in b1 for k in ("13 档", "封板率 73%", "涨停 40→55", "梯队", "甲5板")) and "暂无" in b0, b1[:200])
        finally:
            shutil.rmtree(ROOT / "downloads" / "market" / dm, ignore_errors=True)
        oc = (ROOT / "scripts" / "paper_line" / "orchestrator.py").read_text(encoding="utf-8")
        check("㊸08:52 盘前首跑先现做一份事实包(❓13; 周一第一次真跑)", "facts_pack.build(a.date, wait=240)" in oc)
        tq = E.V3(L["tudou"], D, fake=True)
        tq.facts_codes = lambda: {"111024", "601988"}
        tq.state = {"cash": 100000.0, "positions": {}, "trades": []}
        s8 = {"codes": [{"code": "111024", "name": "", "band": [200, 300], "rules": [
                            {"id": "r1", "side": "BUY", "op": "<=", "px": 250.0, "qty": 40, "why": "x"},
                            {"id": "r2", "side": "SELL", "op": ">=", "px": 255.0, "qty": 40, "after": "r1", "why": "x"}]},
                        {"code": "601988", "name": "", "band": [7, 8], "rules": [
                            {"id": "r1", "side": "BUY", "op": "<=", "px": 7.2, "qty": 100, "why": "x"},
                            {"id": "r2", "side": "SELL", "op": ">=", "px": 7.3, "qty": 100, "after": "r1", "why": "x"}]}]}
        out8, dr8 = E.X.SE.check(tq, s8)
        kept = {(x["code"], r["id"]) for x in out8["codes"] for r in x["rules"]}
        check("㊹执行器 after 卖单: 转债(T+0) 先买后卖的卖单不再当超持仓剔; 股票(T+1) 当天买当天卖照旧剔并写明 T+1",
              ("111024", "r2") in kept and ("601988", "r2") not in kept and any("601988 r2" in d and "T+1" in d for d in dr8), str(dr8))
        import samples as SMPa
        sm = dict(SMPa.lines("600851", "2026-10-23"))
        sm2 = dict(SMPa.lines("002307", "2026-10-23"))
        check("㊺全体导师样例: 海欣 10-14 芷影负样例被列出; 北新同情境(前一天首板)含样例导师的负样例和正样例",
              "⚠负样例(1)" in sm.get("全体导师同票样例", "") and "10-14" in sm["全体导师同票样例"]
              and "(样例)" in sm2.get("同情境样例", "") and "⚠负样例(" in sm2["同情境样例"] and "正样例" in sm2["同情境样例"], str(sm)[:200])
        matn = "### 600851 海欣股份\n- E1 关键价位: 7.1\n- E2 全体导师同票样例: " + sm["全体导师同票样例"] + "\n"
        pn = {"code": "600851", "action": "建", "checked": {"价位": {"E": "E1", "影响": "支持", "结论": "x"}, "样例": {"E": "E2", "影响": "支持", "结论": "芷影做过"}}}
        v1 = H.gate_checked(pn, matn, set())
        pn["checked"]["样例"] = {"E": "E2", "影响": "反对", "结论": "负样例 1 笔: 芷影 10-14 -6.8%", "回应": "半仓, 跌破 7.0 走"}
        check("㊺买入前必须回应负样例: 只引正面 → 记违规; 写出负样例笔数 + 最差一例 + 怎么防 → 过",
              any("负样例" in v for v in v1) and H.gate_checked(pn, matn, set()) == [], str(v1))
        live_tests(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(ROOT / "scripts" / "dfcf" / "paper" / "facts" / D, ignore_errors=True)
    print(f"\n通过 {len(OK)} / {len(OK) + len(BAD)}" + (f"; 失败: {BAD}" if BAD else ""))
    return not BAD


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(0 if run() else 1)
