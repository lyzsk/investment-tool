# -*- coding: utf-8 -*-
"""replay.py — paper v3 放量彩排: 用 10/22 录下的行情把半天重放一遍(10/23 凌晨用户批)

重放什么: 09:00 启动 → 09:20 竞价复核 → 09:25 竞价撮合 → 09:30~11:30 盘中 → (跳过午后) → 14:51 尾盘版 → 15:00 尾盘撮合 + 收盘结算 + 写本线记忆
真实的部分: lines.json 全部账本(11 本)、真调模型(claude -p 会话)、真走叫醒队列(上限 13)、真撮合(排队单穿价 + 成交量 / 盘口深度 / 炸板接 / 停牌保护)
不偷看(只给"那一刻已经知道的"):
  3 秒盘口 / 3 秒指数: 按模拟时钟只放出 ≤ 此刻的行  ·  开盘实况: 只给 ≤ 此刻的判定  ·  事实包: 用当时已生成的那一份(facts/<日>/<时刻>)
  md: 当天只给「## 盘前」一节(收评 / 涨停分析当时还没有)  ·  导师逐笔 / 情绪 / 题材 / 相似日: 本来就只用 D 之前的数据
隔离: 账本写 results/_replay/<日>/v3_*, 本线记忆写 results/_replay/<日>/memory; 不推微信(记进 wx.jsonl); 新浪补价关掉; 事实包不现做
模拟时钟: 没有模型在想(队列空)时快进(每 0.02 秒走 3 秒); 有模型在想时按真实速度走(模型想 2 分钟, 盘面也真的过 2 分钟); 11:30 后跳到 14:50:30
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/paper_v3/replay.py [--date 2026-10-22] [--lines a,b] [--fake]
"""
import argparse
import datetime as dt
import gzip
import json
import re
import shutil
import sys
import threading
import time as _time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "paper_v3"), str(ROOT / "scripts" / "chain"), str(ROOT / "scripts" / "dfcf" / "paper")]
import executor as E   # noqa: E402
import orchestrator as O   # noqa: E402
import pack   # noqa: E402
import se_chain   # noqa: E402
import se_facts   # noqa: E402

MKT = ROOT / "downloads" / "market"


class Clock:
    def __init__(self, t0):
        self.t, self.cv, self.books, self.stop, self.jumped = t0, threading.Condition(), [], False, False
        self.log = []

    def now(self):
        return self.t

    def sleep(self, sec):
        tgt = self.t + dt.timedelta(seconds=sec)
        with self.cv:
            while self.t < tgt and not self.stop:
                self.cv.wait(0.2)

    def busy(self):
        return E.GATE.busy > 0 or bool(E.GATE.wait) or any(b.pending for b in self.books)

    def run(self, feed):
        while not self.stop:
            b = self.busy()
            if b:
                _time.sleep(0.5)
                step = 0.5
            else:
                _time.sleep(0.02)
                step = 3.0
            with self.cv:
                self.t += dt.timedelta(seconds=step)
                hms = self.t.strftime("%H:%M:%S")
                if not self.jumped and hms >= "11:30:30" and not b:
                    self.t = self.t.replace(hour=14, minute=50, second=30)
                    self.jumped = True
                    self.log.append(("跳到 14:50:30", _time.time()))
                feed.advance(self.t.strftime("%H:%M:%S"))
                self.cv.notify_all()
            if hms >= "15:02:00":
                self.stop = True


class TimeShim:
    """se_exec 里的 time.sleep / time.time 走模拟时钟; 其余照真 time"""
    def __init__(self, clk):
        self.c = clk

    def sleep(self, x):
        self.c.sleep(x)

    def time(self):
        return self.c.t.timestamp()

    def __getattr__(self, k):
        return getattr(_time, k)


class ReplayFeed:
    """3 秒盘口 + 3 秒指数按模拟时钟放出: 全局指针推进, LAST[代码] = ≤ 此刻最后一行"""
    def __init__(self, D):
        self.rows, self.i, self.last = [], 0, {}
        f = MKT / D / "book_snap.jsonl"
        op = open if f.exists() else gzip.open
        src = f if f.exists() else f.with_suffix(".jsonl.gz")
        with op(src, "rt", encoding="utf-8") as fh:
            for l in fh:
                k = l.find('"t":"')
                if k > 0:
                    self.rows.append((l[k + 5:k + 13], l))
        self.rows.sort(key=lambda x: x[0])
        self.idx, self.j, self.last_idx = [], 0, {}
        g = MKT / D / "index_snap.jsonl"
        if g.exists():
            for l in g.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(l)
                except ValueError:
                    continue
                self.idx.append((r.get("t", ""), r))
        self.idx.sort(key=lambda x: x[0])
        self.lock = threading.Lock()
        self.mpath, self._open = {}, {}   # 名单外补价: 当天分钟路径(股票 downloads/quotes/stock/minute_path; 转债 downloads/quotes/cb/minute)
        for f in (ROOT / "downloads" / "quotes" / "stock" / "minute_path" / f"{D}.jsonl",):
            if f.exists():
                for l in f.read_text(encoding="utf-8").splitlines():
                    try:
                        r = json.loads(l)
                        if len(r.get("p") or []) >= 240:
                            self.mpath[r["code"]] = r["p"]
                    except ValueError:
                        pass
        self.D = D

    def path(self, c):
        """{HH:MM: 价}: 股票用分钟路径(240 点), 转债用 downloads/quotes/cb/minute/<代码>/<日>.json 的 1 分钟收盘"""
        if not hasattr(self, "_paths"):
            self._paths = {}
        if c not in self._paths:
            out = {}
            if c in self.mpath:
                for i, v in enumerate(self.mpath[c][:240]):
                    m = 571 + i if i < 120 else 781 + (i - 120)
                    out[f"{m // 60:02d}:{m % 60:02d}"] = v
            else:
                f = ROOT / "downloads" / "quotes" / "cb" / "minute" / c / f"{self.D}.json"
                if f.exists():
                    try:
                        out = {b["t"]: b["c"] for b in json.loads(f.read_text(encoding="utf-8")).get("bars") or []}
                    except (ValueError, KeyError):
                        out = {}
            self._paths[c] = out
        return self._paths[c]

    def open_px(self, c):
        """当天开盘价(= 09:25 竞价撮合价), 行情库日线只读"""
        if c not in self._open:
            try:
                sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
                import manual_backfill as mb
                cur = mb.db().cursor()
                cur.execute("use investment_market")
                sym = ("sh" if c.startswith(("6", "5", "11")) else "sz") + c
                cur.execute("select open from kline_day where is_deleted=0 and symbol=%s and trade_date=%s", (sym, self.D))
                r = cur.fetchone()
                self._open[c] = float(r[0]) if r and r[0] else None
            except Exception:   # noqa: BLE001
                self._open[c] = None
        return self._open[c]

    def advance(self, t):
        with self.lock:
            while self.i < len(self.rows) and self.rows[self.i][0] <= t:
                try:
                    r = json.loads(self.rows[self.i][1])
                    self.last[str(r["s"])[2:]] = r
                except ValueError:
                    pass
                self.i += 1
            while self.j < len(self.idx) and self.idx[self.j][0] <= t:
                r = self.idx[self.j][1]
                if r.get("p") and r.get("pc"):
                    self.last_idx[r["s"]] = (float(r["p"]), float(r["pc"]))
                self.j += 1


def install(D, clk, feed, out):
    """把执行器 / 材料包里所有"读此刻 / 读外部 / 读全天文件 / 写真实目录 / 推微信"的地方换成回放版"""
    E.X.now = clk.now
    E.X.time = TimeShim(clk)
    E.LIVE = out
    E.MEMDIR = pack.MEMDIR = out / "memory"
    E.GATE.n = E.gate_n()

    def refresh(self, codes):   # 3 秒盘口: 只放 ≤ 此刻(口径同 se_exec.Feed.refresh)
        with feed.lock:
            items = list(feed.last.items())
        for c, r in items:
            if r.get("p"):
                self.q[c] = {"p": float(r["p"]), "t": r.get("t"), "b1": (r.get("b") or [[0]])[0][0], "a1": (r.get("k") or [[0]])[0][0],
                             "b": r.get("b"), "k": r.get("k"), "v": r.get("v")}
        # 10/23 彩排查出: 名单外的票(10/22 澳弘 09:36 前、百洋全天)彩排里看不到价; 实盘有新浪每 10 秒补 → 回放用当天分钟路径 / 日线开盘补(没有五档, 同新浪补价口径)
        hm = clk.t.strftime("%H:%M")
        for c in codes or []:
            if c in self.q and self.q[c].get("src") != "replay_min":
                continue
            px = None
            if hm >= "09:30":
                path = feed.path(c)
                ks = [k for k in path if k <= hm]
                px = path[max(ks)] if ks else None
            if px is None and "09:25" <= hm < "09:31":
                px = feed.open_px(c)
            if px:
                self.q[c] = {"p": float(px), "t": clk.t.strftime("%H:%M:%S"), "b1": float(px), "a1": float(px), "src": "replay_min"}
    E.X.Feed.refresh = refresh
    E.V3.idx_now = lambda self: dict(feed.last_idx)
    se_chain.sina_snap = lambda codes: {}   # 新浪补价关掉(零外部请求)

    def open_ctx(self):   # 开盘实况: 只给 ≤ 此刻的判定
        o = E.X.jl(MKT / self.D / "open_live.json", {}) or {}
        hm = clk.t.strftime("%H%M")
        J = [j for j in o.get("judgments") or [] if str(j.get("t", "")).replace(":", "")[:4] <= hm]
        if not J:
            return "(今天开盘实况还没出判定)"
        j = J[-1]
        fl = "; ".join(f"{k} {v}" for k, v in sorted(E.X.SX.flips(self.D).items()) if k <= hm) or "无"
        return "\n".join([f"最新判定 {j.get('t')}: {j.get('label')}(分 {j.get('score')})"] + [f"- {x}" for x in j.get("factors") or []] + [f"今日翻转: {fl}"])
    E.V3.open_ctx = open_ctx

    fdir = ROOT / "scripts" / "dfcf" / "paper" / "facts" / D

    def latest(_D):   # 事实包: 当时已生成的那一份
        hm = clk.t.strftime("%H%M")
        fs = sorted(p for p in fdir.glob("*/facts.md") if p.parent.name.isdigit() and p.parent.name <= hm and p.stat().st_size > 0)
        return fs[-1] if fs else None
    se_facts.latest = latest

    rd0, mdD = pack.rd, pack.md_path(D)

    def rd(p):   # 当天 md 只给「## 盘前」
        t = rd0(p)
        if Path(p) == mdD and t:
            m = re.search(r"^## 盘前.*?(?=^## |\Z)", t, re.S | re.M)
            return (m.group(0) if m else "") + "\n(回放: 当天 md 只给盘前一节)"
        return t
    pack.rd = rd

    def halt_status(code, _D, now_hms=None):
        t = clk.t.strftime("%H:%M:%S")
        if t < "09:20:00":
            return "09:20 前还判断不了(竞价前段)"
        r = feed.last.get(code)
        if not r:
            return "3 秒盘口里没有这只票, 判断不了"
        empty = not r.get("p") and not any((x or [0, 0])[0] for x in (r.get("b") or []) + (r.get("k") or []))
        return f"**疑似停牌**(截至 {r.get('t')} 现价 0、买卖五档全空)" if empty else f"正常交易(截至 {r.get('t')} 现价 {r.get('p')})"
    pack.halt_status = halt_status
    tg0 = pack.telegraph_hits   # 电报点名: md 里是全天的电报, 回放只给 ≤ 此刻的(不偷看)
    pack.telegraph_hits = lambda D_: {c: v for c, v in tg0(D_).items() if v[:5] <= clk.t.strftime("%H:%M")}

    wxlog, wxlock = out / "wx.jsonl", threading.Lock()   # 11 个线程同时写, 不加锁会串行(桩回放出过 1 行坏 JSON)

    def wx(self, msg, alert=False):
        with wxlock, wxlog.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": clk.t.strftime("%H:%M:%S"), "line": self.line["id"], "alert": alert, "msg": self._clean(msg)}, ensure_ascii=False) + "\n")
    E.V3.wx = wx


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-10-22")
    ap.add_argument("--lines", default="")
    ap.add_argument("--fake", action="store_true")
    ap.add_argument("--max-usd", type=float, default=0, help="累计花费超过就停; 0 = 不设上限(10/23 用户定: 彩排要测出真实花费)")
    a = ap.parse_args()
    D = a.date
    out = ROOT / "results" / "_replay" / D
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    t_real0 = _time.time()
    feed = ReplayFeed(D)
    clk = Clock(dt.datetime.combine(dt.date.fromisoformat(D), dt.time(8, 59, 0)))
    install(D, clk, feed, out)
    O.common_env()
    L = E.lines()
    want = [x.strip() for x in a.lines.split(",") if x.strip()] or list(L)
    books, ths, errs = [], [], []
    for idx, lid in enumerate(L):
        if lid not in want:
            continue
        b = E.V3(L[lid], D, dry=False, fake=a.fake)
        b.facts_build = False
        books.append((idx, lid, b))
    clk.books = [b for _, _, b in books]

    def run(idx, lid, b):
        E._TL.ov = O.line_ov(L[lid], idx)
        first = (dt.datetime.strptime("09:00:00", "%H:%M:%S") + dt.timedelta(seconds=20 * idx)).strftime("%H:%M:%S")
        try:
            b.run(t_strategy=first)
        except Exception:   # noqa: BLE001
            errs.append((lid, traceback.format_exc()[-800:]))
    for idx, lid, b in books:
        th = threading.Thread(target=run, args=(idx, lid, b), name=f"r-{lid}", daemon=True)
        th.start()
        ths.append(th)
    ct = threading.Thread(target=clk.run, args=(feed,), daemon=True)
    ct.start()
    last_print = 0
    while any(t.is_alive() for t in ths):
        _time.sleep(5)
        if _time.time() - last_print > 60:
            last_print = _time.time()
            spent = 0.0
            for f in out.glob(f"{D}/v3_*/versions/*/timing.json"):
                try:
                    spent += float(json.loads(f.read_text(encoding="utf-8")).get("usd") or 0)
                except (OSError, ValueError):
                    pass
            if a.max_usd and spent > a.max_usd:
                print(f"累计花费 ${spent:.2f} 超过上限 ${a.max_usd}, 强制结束", flush=True)
                errs.append(("_replay", f"花费 ${spent:.2f} 超上限, 中途停"))
                break
            print(f"[花费] 累计 ${spent:.2f}", flush=True)
            print(f"[真实 {dt.datetime.now():%H:%M:%S}] 模拟 {clk.t:%H:%M:%S} 在想 {E.GATE.busy} 排队 {len(E.GATE.wait)} 已收盘 {sum(1 for _, _, b in books if (b.dir / 'summary.md').exists())}/{len(books)}", flush=True)
        if _time.time() - t_real0 > 4 * 3600:
            print("超过 4 小时, 强制结束", flush=True)
            break
    clk.stop = True
    meta = {"date": D, "real_secs": round(_time.time() - t_real0), "lines": want, "gate_log": E.GATE.log, "gate_n": E.GATE.n, "errors": errs, "clock_log": clk.log}
    (out / "replay_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("完成", meta["real_secs"], "秒; 错误", len(errs), flush=True)


if __name__ == "__main__":
    main()
