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
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/paper_v3/selftest.py
"""
import datetime as dt
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper_v3"))
import executor as E   # noqa: E402
import tempfile   # noqa: E402
E.MEMDIR = E.pack.MEMDIR = Path(tempfile.mkdtemp()) / "memory"   # 本线记忆写临时目录, 不污染明天的启动材料

D = "2099-01-02"
import os   # noqa: E402
os.environ["SE_FULL_PAUSE"] = "0"   # 同 executor.main(v3 不停触发)
CLK = {"t": "09:00:05"}
E.X.now = lambda: dt.datetime.combine(dt.date.fromisoformat(D), dt.time.fromisoformat(CLK["t"]))   # 假钟(se_exec 里所有 now() 都走它)
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


def run():
    base = ROOT / "results" / "_live" / D
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
        check("④盘中触发跑了 05", (vd / "05.md").exists())
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
        check("㉑收盘写了本线记忆(临时目录)", mf.exists() and f"## {D} 收盘" in mf.read_text(encoding="utf-8") and not (E.V3_DIR_REAL / "memory" / "liuyiqing.md").exists() if hasattr(E, "V3_DIR_REAL") else mf.exists(), str(mf))
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
        check("⑲带 03: 启动跑了多空两个分支", (vd / "03_bull.md").exists() and (vd / "03_bear.md").exists(), str([p_.name for p_ in vd.iterdir()]))
        check("⑲带 03: 队列一次占 3 个名额", any(x[0] == "in" and x[1] == "zhiying_03" and x[4] >= 3 for x in E.GATE.log), str(E.GATE.log[-2:]))
        CLK["t"] = "09:20:40"
        z3.restrategize("竞价段正式版(看 09:20 后可信竞价)", counted=False, tag="auction")
        settle(z3)
        vd = latest_vd(z3)
        check("⑲竞价复核不跑 03", not (vd / "03_bull.md").exists() and not (vd / "05.md").exists())
        CLK["t"] = "09:40:00"
        z3.restrategize("本链成交 BUY600000", counted=False)
        settle(z3)
        vd = latest_vd(z3)
        check("⑲盘中触发: 先交 01 再分叉多空", (vd / "01.md").exists() and (vd / "03_bull.md").exists() and (vd / "03_bear.md").exists())
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
        os.environ["V3_PUSH_LINES"] = "tudou,liuyiqing,zhiying"
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
            os.environ.pop("V3_PUSH_LINES", None)
        check("㉜主线挂单推微信: 盘前版必推 + 只推挂单变了的版本 + 成交; 计划模式那本不推", len(sent) == 4 and sent[0].startswith("📋 芷影") and "挂单" in sent[1] and sent[3].startswith("✅ 芷影"), str([m[:40] for m in sent]))
    finally:
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(ROOT / "scripts" / "dfcf" / "paper" / "facts" / D, ignore_errors=True)
    print(f"\n通过 {len(OK)} / {len(OK) + len(BAD)}" + (f"; 失败: {BAD}" if BAD else ""))
    return not BAD


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(0 if run() else 1)
