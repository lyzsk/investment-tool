# -*- coding: utf-8 -*-
"""plan_review.py — 实盘线模块 9: 计划核销 + 你的决策日志(零 token, 每晚跑; 10/24 建)

把每条线(每本模拟账本)当天的各版挂单和实际走势逐条对上:
  ① 每张挂单 → 成交没有 / 成交时刻和价格; 没成交的 → 生效期内离挂价最近差多少、为什么没成
  ② 买入成交 → 当天收盘浮盈、成交后当天最高 / 最低、下一交易日最高 / 收盘(有数据才算)
     卖出成交 → 卖后当天最高(卖飞多少)、收盘、相对成本、下一交易日最高 / 收盘
  ③ 和导师真人当天操作对比(同票同方向的重合); 06 有情景字段(codes[].scenarios[])时核销落在哪个情景
  ④ 汇总: 下单几张 / 成交几张 / 成交单当天盈亏全分布(dist_full)
  ⑤ 你的决策日志: 用户当天微信回"照 / 偏 理由" → 挂到它之前最近的一条 v3_ 推送 → scripts/dfcf/snapshots/decision_log/<D>.jsonl(隐私目录)

数据(只读): <root>/<D>/v3_<线>/(strategies/ = 执行器真正生效的各版策略, versions/ = 06 原文 + timing, state.json, events.jsonl, summary.md)
  行情: MySQL investment_market.kline_day(日线 / 涨跌停价 / 下一交易日) + downloads/market/<D>/book_snap.jsonl(.gz)(3 秒盘口) + kline_minute.jsonl(1 分钟, 3 秒名单外的票)
  导师: investment_tool.tzzb_record(bs_leg); 推送: scripts/hermes/state/wx_sent.jsonl + 各线 wx_send.log
  用户回复: hermes 本地库 %LOCALAPPDATA%/hermes/state.db(只读) → 兜底 hermes logs/gateway.log 的 inbound message 行 → scripts/dfcf/snapshots/hermes/qa-<日>.jsonl
输出: <root>/<D>/review/plan_review.md + plan_review.json(只写模拟账本数据); 决策日志只进 scripts/dfcf/snapshots/decision_log/<D>.jsonl
不发行情请求、不写数据库、不弹窗。

用法:
  scripts/venv/Scripts/python.exe -X utf8 scripts/live/plan_review.py --date 2026-10-23
  scripts/venv/Scripts/python.exe -X utf8 scripts/live/plan_review.py --date 2026-10-23 --root results/_replay/2026-10-23_stub   (回放: 不做决策日志)
"""
import argparse
import bisect
import datetime as dt
import gzip
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import line_dirs as LDS   # noqa: E402  10/25 账本目录命名(live_<skill> / paper_<id>)
sys.path[:0] = [str(ROOT / "scripts" / "lib")]
import dist_full   # noqa: E402
sys.path.insert(0, str(ROOT / "scripts" / "live"))
import line_periods as LP   # noqa: E402  10/25: 每条线叫模型时段(你几点收束 / 定时停)

LIVE = ROOT / "results" / "_live"
MKT = ROOT / "downloads" / "market"
WX_SENT = ROOT / "scripts" / "hermes" / "state" / "wx_sent.jsonl"
DLOG_DIR = ROOT / "scripts" / "dfcf" / "snapshots" / "decision_log"   # 隐私目录(snapshots/ 已 gitignore)
QA_DIR = ROOT / "scripts" / "dfcf" / "snapshots" / "hermes"
HERMES_HOME = Path(os.environ.get("HERMES_HOME") or (Path(os.environ.get("LOCALAPPDATA") or "C:/Users/admin/AppData/Local") / "hermes"))
LINES_JSON = ROOT / "scripts" / "paper_line" / "lines.json"

T_OPEN, T_CONT_END, T_CLOSE = "09:30:00", "14:57:00", "15:00:00"   # 连续竞价 09:30 起; 14:57~15:00 尾盘集合竞价(按收盘价一次撮合)
T_AUC = "09:25:00"
MINUS = "\u2212"   # 术语表: 负号用 −


# ---------------------------------------------------------------- 小工具 ----------------------------------------------------------------
def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def jlines(p):
    out = []
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            for l in f:
                try:
                    out.append(json.loads(l))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def sec(t):
    h, m, s = (int(x) for x in (str(t)[:8] + ":00:00")[:8].split(":")[:3])
    return h * 3600 + m * 60 + s


def hms(x):
    x = int(round(x))
    return f"{x // 3600:02d}:{x % 3600 // 60:02d}:{x % 60:02d}"


def pct(a, b):
    """(a / b − 1) × 100, 保留 2 位; 缺数 → None"""
    try:
        return round((float(a) / float(b) - 1) * 100, 2) if a is not None and b else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def fp(x, nd=2):
    """+2.35% / −1.20%(术语表口径)"""
    if x is None:
        return "—"
    s = f"{x:+.{nd}f}%"
    return s.replace("-", MINUS)


def fnum(x):
    if x is None:
        return "—"
    return (f"{x:.3f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)).replace("-", MINUS)


def symbol(code):
    s = str(code).zfill(6)
    if s.startswith(("4", "8", "92")):
        return "bj" + s
    if s.startswith(("6", "900", "5", "11", "204")):
        return "sh" + s
    return "sz" + s


def db():
    """只读用途: 连接参考 scripts/backfill_bilibili/manual_backfill.py 的 db(); 本脚本只发 SELECT"""
    import pymysql
    yml = (ROOT / "inv-admin/src/main/resources/application.yml").read_text(encoding="utf-8")
    pw = re.search(r"password:\s*\"?([^\"\r\n]+)", yml).group(1).strip()
    return pymysql.connect(host="localhost", port=3306, user="root", password=pw, database="investment_tool", charset="utf8mb4", autocommit=True)


def rel(p):
    p = Path(p)
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def f2(x):
    return None if x is None else float(x)


# ---------------------------------------------------------------- 行情上下文(只读) ----------------------------------------------------------------
class Market:
    """一天的行情: 日线(当天 / 下一交易日) + 3 秒盘口 + 1 分钟线 + 竞价 + 名称; 全部只读。自测可直接构造字段注入"""

    def __init__(self, D, codes=(), load=True):
        self.D = D
        self.day, self.nxt, self.names, self.tape, self.bars, self.auc, self.errors = {}, {}, {}, {}, {}, {}, []
        if load:
            self._load(sorted(set(codes) | {"000001", "399303"}))

    # --- 读 ---
    def _load(self, codes):
        syms = [symbol(c) if c not in ("000001", "399303") else ("sh000001" if c == "000001" else "sz399303") for c in codes]
        try:
            conn = db()
            cur = conn.cursor()
            ph = ",".join(["%s"] * len(syms))
            cur.execute(f"select symbol, trade_date, open, high, low, close, pre_close, limit_up, limit_down from investment_market.kline_day "
                        f"where is_deleted=0 and symbol in ({ph}) and trade_date >= %s and trade_date <= date_add(%s, interval 15 day) order by trade_date", (*syms, self.D, self.D))
            for s, d, o, h, l_, c, pc, up, dn in cur.fetchall():
                row = {"date": d.isoformat(), "open": f2(o), "high": f2(h), "low": f2(l_), "close": f2(c), "pre_close": f2(pc), "up": f2(up), "dn": f2(dn)}
                key = s if s in ("sh000001", "sz399303") else s[2:]
                if row["date"] == self.D:
                    self.day[key] = row
                elif row["date"] > self.D and key not in self.nxt:
                    self.nxt[key] = row
            codes6 = [c for c in codes if c not in ("000001", "399303")]
            if codes6:
                ph = ",".join(["%s"] * len(codes6))
                cur.execute(f"select code, sec_type, name from investment_market.security_master where is_deleted=0 and code in ({ph})", codes6)
                rank = {"STOCK": 0, "CB": 1, "ETF": 2, "LOF": 3}
                best = {}
                for code, sty, nm in cur.fetchall():
                    r = rank.get(sty, 5 if sty == "INDEX" else 4)
                    if code not in best or r < best[code][0]:
                        best[code] = (r, nm)
                self.names = {c: v[1] for c, v in best.items()}
            conn.close()
        except Exception as e:   # noqa: BLE001
            self.errors.append(f"行情库读取失败: {e!r}"[:200])
        self._load_tape(set(codes))
        self._load_bars(set(codes))
        self._load_auction(set(codes))
        for c in codes:   # 日线没有涨跌停价(ETF 等) → a_rules 按规则算
            r = self.day.get(c)
            if r and r.get("up") is None and r.get("pre_close"):
                try:
                    import a_rules
                    r["up"], r["dn"] = a_rules.limit_prices(c, self.D, r["pre_close"])
                except Exception:   # noqa: BLE001
                    pass

    def _load_tape(self, codes):
        f = MKT / self.D / "book_snap.jsonl"
        src = f if f.exists() else f.with_suffix(".jsonl.gz")
        if not src.exists():
            self.errors.append(f"没有 3 秒盘口 {src.name}(改用 1 分钟线)")
            return
        want = {symbol(c): c for c in codes}
        op = open if src.suffix == ".jsonl" else gzip.open
        with op(src, "rt", encoding="utf-8") as fh:
            for l in fh:
                m = re.match(r'\{"s":"(\w+)"', l)
                if not m or m.group(1) not in want:
                    continue
                try:
                    r = json.loads(l)
                except ValueError:
                    continue
                p, t = float(r.get("p") or 0), str(r.get("t") or "")
                if p <= 0 or t < T_AUC or t > "15:00:59":
                    continue
                b1 = ((r.get("b") or [[0]])[0] or [0])[0] or 0
                a1 = ((r.get("k") or [[0]])[0] or [0])[0] or 0
                self.tape.setdefault(want[m.group(1)], []).append((t, p, p, float(b1), float(a1)))
        for v in self.tape.values():
            v.sort()

    def _load_bars(self, codes):
        f = MKT / self.D / "kline_minute.jsonl"
        if not f.exists():
            return
        want = {symbol(c): c for c in codes}
        with f.open(encoding="utf-8") as fh:
            for l in fh:
                m = re.match(r'\{"symbol": "(\w+)"', l)
                if not m or m.group(1) not in want:
                    continue
                try:
                    r = json.loads(l)
                except ValueError:
                    continue
                end = r["barTime"][11:19]
                start = end if end == "09:30:00" else hms(sec(end) - 60)   # 通达信分钟线按收尾时刻标: 09:31 = 09:30~09:31; 09:30 那根 = 开盘价
                self.bars.setdefault(want[m.group(1)], []).append((start, end, float(r["low"]), float(r["high"]), float(r["close"])))
        for v in self.bars.values():
            v.sort()

    def _load_auction(self, codes):
        f = MKT / self.D / "call_auction_open.jsonl"
        if not f.exists():
            return
        want = {symbol(c): c for c in codes}
        with f.open(encoding="utf-8") as fh:
            for l in fh:
                m = re.match(r'\{"symbol": "(\w+)"', l)
                if not m or m.group(1) not in want:
                    continue
                try:
                    r = json.loads(l)
                except ValueError:
                    continue
                if str(r.get("snapTime", ""))[11:19] > T_AUC:
                    continue
                cur = self.auc.setdefault(want[m.group(1)], {})
                cur["price"], cur["vol"], cur["amt"] = r.get("price"), r.get("matchedVolume"), r.get("matchedAmount")
                if r.get("unmatchedVolume") is not None:   # 正 = 未匹配买, 负 = 未匹配卖(定格那一笔常为空, 取最后一个非空)
                    cur["unm"] = r["unmatchedVolume"]

    # --- 查 ---
    def name(self, code, fallback=""):
        return self.names.get(code) or fallback or code

    def close(self, code):
        r = self.day.get(code)
        if r and r.get("close"):
            return r["close"]
        tp = self.tape.get(code)
        return tp[-1][1] if tp else None

    def has_px(self, code):
        return bool(self.tape.get(code) or self.bars.get(code))

    def points(self, code, ws, we):
        """[ws, we) 内的价格点: [(t, lo, hi, 买一, 卖一, 源)]; 有 3 秒盘口用盘口, 否则用 1 分钟线(买一卖一未知)"""
        if ws >= we:
            return []
        tp = self.tape.get(code)
        if tp:   # 区间开头那一刻的价 = 之前最后一笔(价格一直停在那), 否则几秒长的生效期会被误判成"没数据"
            i, j = bisect.bisect_left(tp, (ws,)), bisect.bisect_left(tp, (we,))
            head = [(ws, *tp[i - 1][1:], "3秒")] if i and (i == len(tp) or tp[i][0] > ws) else []
            return head + [(*x, "3秒") for x in tp[i:j]]
        out = []
        for st, en, lo, hi, _c in self.bars.get(code) or []:
            if (st == en and ws <= st < we) or (st < we and en > ws and st != en):
                out.append((st, lo, hi, None, None, "1分"))
        return out

    def limit_up(self, code):
        return (self.day.get(code) or {}).get("up")

    def limit_dn(self, code):
        return (self.day.get(code) or {}).get("dn")


# ---------------------------------------------------------------- 读一本账 ----------------------------------------------------------------
def load_book(ldir):
    """各版生效策略(strategies/) + 精确落地时刻(versions/NN_*/timing.json 的 start + total) + 06 原文 + 成交 + 事件"""
    vdirs = {}
    for vd in sorted((ldir / "versions").glob("*")):
        if vd.name[:2].isdigit():
            t = jl(vd / "timing.json", {}) or {}
            if t.get("result") in (None, "ok") or int(vd.name[:2]) not in vdirs:
                vdirs[int(vd.name[:2])] = (vd, t)   # 同号多个目录(失败后重试) → 取最后一个成功的
    vers = []
    for sp in sorted((ldir / "strategies").glob("*.json")):
        if not sp.name[:2].isdigit():
            continue
        n = int(sp.name[:2])
        S = jl(sp, {}) or {}
        vd, t = vdirs.get(n, (None, {}))
        land = None
        if t.get("start") and t.get("total") is not None:
            land = hms(sec(t["start"]) + float(t["total"]))
            if land[:5].replace(":", "") != sp.stem.split("_")[-1]:   # 和文件名分钟对不上 → 以文件名为准(防 timing 对错目录)
                land = None
        if land is None:
            hm = sp.stem.split("_")[-1]
            land = f"{hm[:2]}:{hm[2:4]}:00"
        vers.append({"v": n, "land": land, "file": sp.name, "why": S.get("why"), "tag": S.get("tag"), "strategy": S.get("strategy") or {},
                     "dropped": S.get("dropped") or [], "fired": S.get("fired") or [], "vdir": vd.name if vd else None, "start": t.get("start"),
                     "raw06": (jl(vd / "06.json", {}) or {}) if vd else {}})
    vers.sort(key=lambda x: x["v"])
    for i, v in enumerate(vers):
        v["end"] = vers[i + 1]["land"] if i + 1 < len(vers) else "15:00:01"
    st = jl(ldir / "state.json", {}) or {}
    ev = jlines(ldir / "events.jsonl")
    summ = (ldir / "summary.md").read_text(encoding="utf-8", errors="replace").split("\n")[0] if (ldir / "summary.md").exists() else ""
    m = re.search(r"模拟账 (\d+)\(开盘 (\d+), ([+-][\d.]+)%\)", summ)
    return {"vers": vers, "state": st, "events": ev, "nav1": int(m.group(1)) if m else None, "nav0": int(m.group(2)) if m else None,
            "ret": float(m.group(3)) if m else None}


def book_codes(B):
    cs = set()
    for v in B["vers"]:
        for x in v["strategy"].get("codes") or []:
            cs.add(str(x.get("code")))
        for x in v["raw06"].get("codes") or []:
            cs.add(str(x.get("code")))
    for t in B["state"].get("trades") or []:
        cs.add(str(t.get("code")))
    cs |= set((B["state"].get("positions") or {}).keys()) | set(((B["state"].get("start") or {}).get("positions") or {}).keys())
    return {c for c in cs if re.fullmatch(r"\d{6}", c)}


# ---------------------------------------------------------------- 核心: 挂单 → 结局 ----------------------------------------------------------------
def _submitted(v, events):
    s = v["strategy"]
    return bool(s.get("auc_submitted")) or any(e.get("kind") == "竞价单按草稿挂出" and e.get("ver") == v["v"] for e in events)


def instances(B):
    """每一版每一条生效规则 = 一个实例(挂单在这一版里的样子)"""
    trades = B["state"].get("trades") or []
    fills = {str(t.get("rule")): t for t in trades}
    nomoney = {str(e.get("rule")) for e in B["events"] if e.get("kind") in ("规则命中但没钱/没可卖", "炸板接命中但没钱")}
    out = []
    for v in B["vers"]:
        s = v["strategy"]
        for x in s.get("codes") or []:
            c = str(x["code"])
            for r in x.get("rules") or []:
                key = f"{v['v']}:{c}:{r['id']}"
                pre = None
                if r.get("after"):
                    pt = fills.get(f"{v['v']}:{c}:{r['after']}")
                    pre = pt["t"] if pt else False
                out.append({"v": v["v"], "land": v["land"], "end": v["end"], "code": c, "name": x.get("name"), "id": r["id"], "side": r["side"], "op": r.get("op"),
                            "px": float(r["px"]), "qty": int(r["qty"]), "type": r.get("type"), "floor": r.get("floor"), "auction": bool(r.get("auction")),
                            "carried": bool(r.get("carried")), "rest": bool(r.get("rest")), "after": r.get("after"), "pre_fill": pre, "why": r.get("why"),
                            "key": key, "fill": fills.get(key), "nomoney": key in nomoney, "submitted": _submitted(v, B["events"]), "tag": v.get("tag"),
                            "chain_start": v.get("start")})
    return out


def merge_orders(insts):
    """连续几版里同票 / 同方向 / 同价 / 同类型、前一版没成交 → 算同一张挂单(柜台里这张单一直挂着); 成交后再出现 = 新的一张"""
    orders, prev_open, by_v = [], {}, {}
    for it in insts:
        by_v.setdefault(it["v"], []).append(it)
    for v in sorted(by_v):
        cur_open = {}
        for it in by_v[v]:
            sig = (it["code"], it["side"], round(it["px"], 4), it.get("type") or "")
            o = prev_open.get(sig)
            if o is None or sig in cur_open:
                o = {"code": it["code"], "name": it["name"], "side": it["side"], "px": it["px"], "type": it.get("type"), "insts": []}
                orders.append(o)
            o["insts"].append(it)
            if not it["fill"]:
                cur_open[sig] = o
        prev_open = cur_open
    return orders


def _segments(it):
    """实例的连续竞价生效区间 [ws, we); 前置单没成交 / 只参加竞价的冻结单 → 无"""
    if it["carried"] or it["pre_fill"] is False:
        return None
    ws = max(it["land"], T_OPEN)
    if it["pre_fill"]:
        ws = max(ws, it["pre_fill"])
    we = min(it["end"], T_CONT_END)
    if it["fill"]:
        we = min(we, it["fill"]["t"])
    return (ws, we) if ws < we else None


def _auc_open(it):
    """是否参加了 09:25 开盘集合竞价撮合"""
    return it["auction"] and it["land"] < T_AUC <= it["end"] and it["submitted"]


def _auc_close(it):
    """是否参加了 15:00 尾盘集合竞价(14:57 时还活着 / 14:57~15:00 落地); 炸板接单、冻结竞价单不参加"""
    if it.get("type") == "board_dip" or it["carried"] or it["pre_fill"] is False:
        return False
    return it["land"] < T_CLOSE and it["end"] > T_CONT_END


def judge(o, M):
    """一张挂单的结局 + 指标; 返回 dict(写进 json)"""
    c, side, px = o["code"], o["side"], o["px"]
    last = o["insts"][-1]
    fill = next((it["fill"] for it in o["insts"] if it["fill"]), None)
    close = M.close(c)
    day = M.day.get(c) or {}
    nx = M.nxt.get(c)
    res = {"code": c, "name": M.name(c, o.get("name")), "side": side, "px": px, "qty": [it["qty"] for it in o["insts"]][-1],
           "qty_hist": sorted({it["qty"] for it in o["insts"]}), "type": o.get("type"), "versions": [it["v"] for it in o["insts"]],
           "rule_keys": [it["key"] for it in o["insts"]], "from": o["insts"][0]["land"], "to": min(last["end"], "15:00:00") if not fill else fill["t"],
           "auction": any(it["auction"] for it in o["insts"]), "after": last.get("after"), "why": str(last.get("why") or "")[:300],
           "close": close, "next_day": ({"date": nx["date"], "high": nx["high"], "close": nx["close"], "open": nx["open"]} if nx else None)}
    # ---------- 成交 ----------
    if fill:
        fpx, ft = float(fill["px"]), fill["t"]
        res.update({"status": "成交", "cat": "成交", "fill_t": ft, "fill_px": fpx, "fill_qty": int(fill["qty"]), "fee": fill.get("fee"),
                    "partial": int(fill["qty"]) < res["qty"], "fill_auction": bool(fill.get("auction"))})
        after = M.points(c, ft, "15:00:59")
        hi = max((p[2] for p in after), default=None)
        lo = min((p[1] for p in after), default=None)
        if side == "BUY":
            res["day_pnl_pct"] = pct(close, fpx)   # 当天收盘浮盈(未扣费)
            res["day_pnl_amt"] = round((close - fpx) * int(fill["qty"]) - float(fill.get("fee") or 0), 2) if close else None
            res["after_high_pct"], res["after_low_pct"] = pct(hi, fpx), pct(lo, fpx)
            if nx:
                res["next_high_pct"], res["next_close_pct"], res["next_open_pct"] = pct(nx["high"], fpx), pct(nx["close"], fpx), pct(nx["open"], fpx)
        else:
            res["day_pnl_pct"] = round((fpx / close - 1) * 100, 2) if close else None   # 卖价相对收盘: 正 = 卖在收盘上方(卖对了)
            res["day_pnl_amt"] = round((fpx - close) * int(fill["qty"]) - float(fill.get("fee") or 0), 2) if close else None
            res["sold_fly_pct"] = pct(hi, fpx)   # 卖后当天最高相对卖价 = 卖飞多少
            res["close_vs_sell_pct"] = pct(close, fpx)
            if nx:
                res["next_high_pct"], res["next_close_pct"] = pct(nx["high"], fpx), pct(nx["close"], fpx)
        res["mfe_t"] = next((p[0] for p in after if p[2] == hi), None) if side == "BUY" else next((p[0] for p in after if p[2] == hi), None)
        return res
    # ---------- 没成交: 找生效期内离挂价最近 ----------
    pts, active, auc_o, auc_c = [], False, False, False
    for it in o["insts"]:
        seg = _segments(it)
        if seg:
            active = True
            pts += M.points(c, *seg)
        if _auc_open(it) and day.get("open"):
            auc_o = True
            pts.append((T_AUC, day["open"], day["open"], None, None, "开盘竞价"))
        if _auc_close(it) and close:
            auc_c = True
            pts.append((T_CLOSE, close, close, None, None, "尾盘竞价"))
    res["active"] = active or auc_o or auc_c
    if any(it["nomoney"] for it in o["insts"]):
        res.update({"status": "命中但没钱 / 没可卖", "cat": "命中没成交(资金 / 可卖)"})
        return res
    if not res["active"]:
        if all(it["auction"] and not it["submitted"] for it in o["insts"]):
            st_ = "竞价草稿没挂出(09:20 前的草稿版, 被竞价复核那版替换)"
            cat = "草稿没挂"
        elif any(it["pre_fill"] is False for it in o["insts"]):
            st_ = f"前置单 {last.get('after')} 没成交, 这张没生效"
            cat = "前置单没成交"
        elif last["end"] <= T_OPEN:
            st_ = f"开盘前就被下一版撤掉({last['end'][:5]}), 没进连续竞价"
            cat = "开盘前被撤"
        else:
            st_ = "生效期是空的(落地就被下一版替换 / 落地时已过 14:57)"
            cat = "没生效"
        if cat in ("草稿没挂", "开盘前被撤"):   # 不撤的话: 竞价单看开盘价, 其余看全天连续竞价有没有穿过挂价(碰到不算, 和执行器排队单口径一致)
            kept = None
            if any(it["auction"] for it in o["insts"]) and day.get("open"):
                if (px >= day["open"]) if side == "BUY" else (px <= day["open"]):
                    kept = f"09:25 开盘价 {fnum(day['open'])} → 竞价就会成交"
            if kept is None:
                allp = M.points(c, T_OPEN, T_CONT_END)
                hit = next((p for p in allp if (p[1] < px if side == "BUY" else p[2] > px)), None)
                touch = next((p for p in allp if abs((p[1] if side == "BUY" else p[2]) - px) < 1e-9), None)
                bx = bar_cross(M, c, T_OPEN, T_CONT_END, side, px)
                if hit:
                    kept = f"{hit[0][:5]} 价格穿过挂价 → 会成交"
                elif bx:
                    kept = f"3 秒快照没穿过, 但 1 分钟线 {bx[0][:5]} {'最低' if side == 'BUY' else '最高'} {fnum(bx[1])} 穿过 → 大概率会成交(瞬间成交)"
                elif touch:
                    kept = f"{touch[0][:5]} 碰到挂价没穿过 → 要排队排到才成交(不确定)"
                else:
                    kept = "全天没穿过挂价 → 也不会成交"
            res["if_kept"] = kept
            st_ += f"; 不撤的话: {kept}"
        res.update({"status": st_, "cat": cat})
        return res
    if o.get("type") == "board_dip":
        up = M.limit_up(c)
        sealed_t = next((p[0] for p in pts if up and p[2] >= up - 1e-6 and (p[4] == 0)), None)
        flo = float(last.get("floor") or 0)
        inzone = [p for p in pts if sealed_t and p[0] > sealed_t and flo <= p[1] <= px and (p[4] or 0) > 0]
        lo = min((p[1] for p in pts), default=None)
        hi = max((p[2] for p in pts), default=None)
        res.update({"status": f"炸板接没触发: 生效期内{'封过板(' + sealed_t[:5] + ')' if sealed_t else '没封过涨停'}; 价格区间 {fnum(lo)}~{fnum(hi)}, 接的区间 {fnum(flo)}~{fnum(px)}"
                    + ("; ⚠ 封板后到过接的区间却没成交, 要细查" if inzone else ""), "cat": "炸板接没触发", "low": lo, "high": hi, "sealed_at": sealed_t})
        return res
    if not pts:
        res.update({"status": "生效期内没有这只票的价格数据(3 秒盘口和分钟线都没有)", "cat": "没数据"})
        return res
    src = "3 秒盘口" if any(p[5] == "3秒" for p in pts) else "1 分钟线"
    if side == "BUY":
        lo = min(p[1] for p in pts)
        t_lo = next(p[0] for p in pts if p[1] == lo)
        res.update({"nearest": lo, "nearest_t": t_lo, "gap_pct": pct(lo, px), "src": src})
        if lo > px + 1e-9:
            res.update({"status": f"价格没下来: 生效期内最低 {fnum(lo)}({t_lo[:5]}) 比买价高 {fp(pct(lo, px))}", "cat": "价格没到"})
        elif abs(lo - px) < 1e-9 and any(it["rest"] for it in o["insts"]):
            res.update({"status": f"只碰到买价 {fnum(px)}({t_lo[:5]}) 没跌穿, 排队量没轮到", "cat": "碰价没排到"})
        elif all(p[4] == 0 for p in pts if p[1] <= px and p[4] is not None) and any(p[4] is not None and p[1] <= px for p in pts):
            res.update({"status": "到价时卖一空(涨停封死)买不进", "cat": "封死买不进"})
        else:
            res.update({"status": f"到过买价(最低 {fnum(lo)} {t_lo[:5]})却没成交, 要细查(盘口断流 / 版本切换 / 停牌保护 / {src}近似)", "cat": "到价没成交(细查)"})
    else:
        hi = max(p[2] for p in pts)
        t_hi = next(p[0] for p in pts if p[2] == hi)
        res.update({"nearest": hi, "nearest_t": t_hi, "gap_pct": pct(hi, px), "src": src})
        if hi < px - 1e-9:
            res.update({"status": f"价格没上去: 生效期内最高 {fnum(hi)}({t_hi[:5]}) 比卖价低 {fp(pct(hi, px))}", "cat": "价格没到"})
        elif abs(hi - px) < 1e-9 and any(it["rest"] for it in o["insts"]):
            res.update({"status": f"只碰到卖价 {fnum(px)}({t_hi[:5]}) 没涨穿, 排队量没轮到", "cat": "碰价没排到"})
        elif all(p[3] == 0 for p in pts if p[2] >= px and p[3] is not None) and any(p[3] is not None and p[2] >= px for p in pts):
            res.update({"status": "到价时买一空(跌停封死)卖不出", "cat": "封死卖不出"})
        else:
            res.update({"status": f"到过卖价(最高 {fnum(hi)} {t_hi[:5]})却没成交, 要细查(可卖不够 / 盘口断流 / {src}近似)", "cat": "到价没成交(细查)"})
    # 3 秒快照可能漏掉瞬间极值: 用 1 分钟线(区间内整根)复核
    if res["cat"] in ("价格没到", "碰价没排到"):
        bx = bar_cross(M, c, pts[0][0], pts[-1][0], side, px)
        if bx:
            res["bar_cross"] = bx[0]
            res["status"] += f"; ⚠ 1 分钟线 {bx[0][:5]} {'最低' if side == 'BUY' else '最高'} {fnum(bx[1])} 穿过挂价(3 秒快照没抓到, 执行器按快照撮合所以没成交)"
    # 链慢了: 这张单的那一版从开跑到落地期间价格已经到过挂价
    it0 = o["insts"][0]
    if res["cat"] in ("价格没到", "碰价没排到") and it0.get("chain_start") and it0["chain_start"] < it0["land"]:
        pre = [p for p in M.points(c, max(it0["chain_start"], T_OPEN), max(it0["land"], T_OPEN)) if (p[1] <= px if side == "BUY" else p[2] >= px)]
        if pre:
            ex = (min if side == "BUY" else max)((p[1] if side == "BUY" else p[2]) for p in pre)
            res["pre_land_hit"] = pre[0][0]
            res["status"] += f"; 这一版 {it0['chain_start'][:8]} 开跑、{it0['land'][:8]} 才落地, 期间 {pre[0][0]} 已到过挂价(极值 {fnum(ex)}) —— 链慢了没赶上"
    # 被替换后价格到过挂价 = 不撤会成交
    if last["end"] < T_CONT_END and res["cat"] in ("价格没到", "碰价没排到"):
        later = M.points(c, last["end"], T_CONT_END)
        hit = next((p for p in later if (p[1] < px if side == "BUY" else p[2] > px)), None)
        if hit:
            res["after_replace_hit"] = hit[0]
            res["status"] += f"; {last['end'][:5]} 被下一版撤掉后 {hit[0][:5]} 价格穿过挂价(不撤会成交)"
    return res


def bar_cross(M, c, ws, we, side, px):
    """[ws, we) 内整根 1 分钟线里第一根穿过挂价的: (收尾时刻, 最低 / 最高); 没有 → None"""
    for st, en, lo, hi, _c in M.bars.get(c) or []:
        if st >= ws and en <= we and st != en and ((lo < px - 1e-9) if side == "BUY" else (hi > px + 1e-9)):
            return en, (lo if side == "BUY" else hi)
    return None


# ---------------------------------------------------------------- 导师对照 ----------------------------------------------------------------
def mentor_legs(D, skills):
    out = {}
    if not skills:
        return out, None
    try:
        conn = db()
        cur = conn.cursor()
        ph = ",".join(["%s"] * len(skills))
        cur.execute(f"select ledger, record_time, stock_code, stock_name, side, price, qty from tzzb_record where record_type='bs_leg' and is_deleted=0 "
                    f"and ledger in ({ph}) and record_time >= %s and record_time < date_add(%s, interval 1 day) order by record_time", (*skills, D, D))
        for led, t, code, nm, side, px, q in cur.fetchall():
            out.setdefault(led, []).append({"t": t.strftime("%H:%M:%S"), "code": str(code).zfill(6), "name": nm,
                                            "side": "BUY" if "买" in (side or "") else "SELL", "px": f2(px), "qty": f2(q)})
        conn.close()
        return out, None
    except Exception as e:   # noqa: BLE001
        return out, f"导师逐笔读取失败: {e!r}"[:200]


def leg_sum(legs):
    if not legs:
        return None
    q = sum(x["qty"] or 0 for x in legs)
    avg = sum((x["px"] or 0) * (x["qty"] or 0) for x in legs) / q if q else None
    return {"n": len(legs), "qty": q, "avg": round(avg, 3) if avg else None, "first": legs[0]["t"], "last": legs[-1]["t"]}


# ---------------------------------------------------------------- 情景核销(06 的 codes[].scenarios[]; 没有就跳过) ----------------------------------------------------------------
_OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, "<": lambda a, b: a < b, "==": lambda a, b: abs(a - b) < 1e-9,
        "=": lambda a, b: abs(a - b) < 1e-9, "!=": lambda a, b: abs(a - b) >= 1e-9}


def scen_vars(code, M):
    """情景条件里代码能判的变量(都按当天全天结果; 盘中某一刻的'现价'类判不了)"""
    d = M.day.get(code) or {}
    pc, o, h, l_, c, up, dn = (d.get(k) for k in ("pre_close", "open", "high", "low", "close", "up", "dn"))
    V = {}
    if pc:
        for k, x in (("开盘涨幅", o), ("竞价涨幅", o), ("最高涨幅", h), ("最低涨幅", l_), ("收盘涨幅", c), ("涨幅", c)):
            if x is not None:
                V[k] = (x / pc - 1) * 100
        if h is not None and l_ is not None:
            V["振幅"] = (h - l_) / pc * 100
    V.update({k: v for k, v in (("昨收", pc), ("开盘价", o), ("最高价", h), ("最低价", l_), ("收盘价", c), ("涨停价", up), ("跌停价", dn)) if v is not None})
    if up and c is not None and h is not None:
        V["封板"] = V["涨停"] = V["收盘涨停"] = float(c >= up - 1e-6)
        V["触板"] = V["摸板"] = float(h >= up - 1e-6)
        V["炸板"] = float(h >= up - 1e-6 and c < up - 1e-6)
        V["一字"] = V["一字板"] = float(o is not None and o >= up - 1e-6 and l_ >= up - 1e-6)
    if dn and c is not None and l_ is not None:
        V["跌停"] = V["收盘跌停"] = float(c <= dn + 1e-6)
        V["触跌停"] = float(l_ <= dn + 1e-6)
    a = M.auc.get(code) or {}
    if a.get("vol") is not None:
        V["竞价量"] = float(a["vol"])
    if a.get("amt") is not None:
        V["竞价金额"] = float(a["amt"])
    if "unm" in a:
        V["未匹配买"], V["未匹配卖"] = float(max(a["unm"], 0)), float(max(-a["unm"], 0))
    for nm, s in (("上证", "sh000001"), ("国证2000", "sz399303")):
        r = M.day.get(s) or {}
        if r.get("pre_close"):
            if r.get("open"):
                V[f"{nm}开盘涨幅"] = (r["open"] / r["pre_close"] - 1) * 100
            if r.get("close"):
                V[f"{nm}收盘涨幅"] = V[f"{nm}涨幅"] = (r["close"] / r["pre_close"] - 1) * 100
    return V


def eval_when(s, V):
    """机械条件串 → True / False / None(判不了); 支持 '且 / and / && / ，' 与 '或 / or / ||', 比较 >= <= > < = == !=(≥ ≤ 也认), 布尔变量前加 未 / 没 / 不 / 非 取反"""
    if not isinstance(s, str) or not s.strip():
        return None, "条件为空"
    t = s.replace("≥", ">=").replace("≤", "<=").replace("＞", ">").replace("＜", "<").replace("％", "%")
    ors = re.split(r"\s*(?:或者|或|\bor\b|\|\|)\s*", t)
    any_none, why = False, []
    for g in ors:
        ands = [a for a in re.split(r"\s*(?:并且|且|\band\b|&&|，|,|、)\s*", g) if a.strip()]
        val = True
        for a in ands:
            a = a.strip()
            m = re.fullmatch(r"(.+?)\s*(>=|<=|!=|==|>|<|=)\s*(.+?)", a)
            r_ = None
            if m:
                l_, op, rt = m.group(1).strip(), m.group(2), m.group(3).strip()

                def num(x):
                    x = x.rstrip("%").strip()
                    try:
                        return float(x.replace(MINUS, "-"))
                    except ValueError:
                        return V.get(x)
                lv, rv = num(l_), num(rt)
                if lv is None or rv is None:
                    why.append(f"认不出 '{l_ if lv is None else rt}'")
                else:
                    r_ = _OPS[op](lv, rv)
            else:
                neg = re.match(r"^(未|没有|没|不|非)\s*(.+)$", a)
                k = neg.group(2) if neg and neg.group(2) in V else a
                if k in V:
                    r_ = bool(V[k]) != bool(neg and neg.group(2) in V)
                else:
                    why.append(f"认不出 '{a}'")
            if r_ is None:
                val = None if val is not False else False
            elif r_ is False:
                val = False
        if val is True:
            return True, ""
        if val is None:
            any_none = True
    return (None, "; ".join(why) or "判不了") if any_none else (False, "")


def scenario_check(B, M):
    """各版(先 strategies 后 06 原文)里出现过的情景, 按 (票, 条件串) 去重; 每条判 落上 / 没落上 / 未能机械判定"""
    seen, out = set(), []
    for v in B["vers"]:
        for src in (v["strategy"], v["raw06"]):
            for x in src.get("codes") or []:
                for i, sc in enumerate(x.get("scenarios") or []):
                    if not isinstance(sc, dict):
                        continue
                    c = str(x.get("code"))
                    k = (c, str(sc.get("when")))
                    if k in seen:
                        continue
                    seen.add(k)
                    ok, why = eval_when(sc.get("when"), scen_vars(c, M))
                    out.append({"v": v["v"], "code": c, "name": M.name(c, x.get("name")), "idx": i, "when": sc.get("when"), "action": sc.get("action"),
                                "prob": sc.get("prob"), "invalid_if": sc.get("invalid_if"), "fear": sc.get("fear"),
                                "hit": ok, "verdict": "落上" if ok else ("没落上" if ok is False else "未能机械判定"), "why": why})
    return out


# ---------------------------------------------------------------- 一条线 ----------------------------------------------------------------
def review_line(ldir, line, M, mlegs):
    B = load_book(ldir)
    insts = instances(B)
    orders = [judge(o, M) for o in merge_orders(insts)]
    trades = B["state"].get("trades") or []
    # 卖出相对成本: 从起点持仓 + 当天成交顺序滚动加权成本
    cost = {c: (int(p.get("qty") or 0), float(p.get("cost") or 0)) for c, p in ((B["state"].get("start") or {}).get("positions") or {}).items()}
    real = {}
    for t in trades:
        c, q, px, fee = str(t["code"]), int(t["qty"]), float(t["px"]), float(t.get("fee") or 0)
        q0, c0 = cost.get(c, (0, 0.0))
        if t["side"] == "BUY":
            cost[c] = (q0 + q, ((q0 * c0) + px * q + fee) / (q0 + q))
        else:
            real[str(t.get("rule"))] = pct(px, c0) if c0 else None
            cost[c] = (max(0, q0 - q), c0)
    for o in orders:
        if o["cat"] == "成交" and o["side"] == "SELL":
            o["vs_cost_pct"] = next((real.get(k) for k in o["rule_keys"] if k in real), None)
    # 06 写了但执行器剔除(strategies/ 的 dropped)
    dropped = [{"v": v["v"], "land": v["land"], "items": v["dropped"]} for v in B["vers"] if v["dropped"]]
    # 导师对照
    legs = mlegs.get(line.get("skill"), []) if line.get("kind") == "mimic" else []
    for o in orders:
        same = [x for x in legs if x["code"] == o["code"] and x["side"] == o["side"]]
        anyside = [x for x in legs if x["code"] == o["code"]]
        o["mentor_same"] = leg_sum(same)
        o["mentor_code_any"] = bool(anyside)
    filled = [o for o in orders if o["cat"] == "成交"]
    per = LP.periods(ldir)
    near = float(os.environ.get("REVIEW_NEAR_PCT") or 0.5)   # 10/25 用户: "差一点"随便定, 反正他复盘看当时的挂单
    for o in orders:   # 没成交的单: 只进过程诊断, 不进成绩(10/25 用户定)
        if not o.get("active") or o["cat"] in ("成交", "命中没成交(资金 / 可卖)") or not o.get("close") or not o.get("px"):
            continue   # 只看真挂在柜台里、价格没走到的单; 命中但没钱 / 草稿 / 开盘前被撤不算"挂高挂低"
        tags = []
        if o["side"] == "BUY" and o["close"] > o["px"]:
            tags.append("挂太低·错过")
        elif o["side"] == "SELL" and o["close"] < o["px"]:
            tags.append("挂太高·该走没走")
        if o.get("gap_pct") is not None and abs(o["gap_pct"]) < near:
            tags.append(f"差一点(<{near:g}%)")
        o["miss_tags"] = tags
    for o in filled:   # 停了之后才成交的 = 之前挂的单机械撮合, 不是模型那一刻的判断
        o["after_off"] = bool(per["off_at"] and str(o.get("fill_t") or "") >= per["off_at"])
    line_fill_sides = {(o["code"], o["side"]) for o in filled}
    m_sides = {}
    for x in legs:
        m_sides.setdefault((x["code"], x["side"]), []).append(x)
    mentor = None
    if line.get("kind") == "mimic":
        mentor = {"skill": line.get("skill"), "n_legs": len(legs),
                  "by_code": [{"code": c, "name": M.name(c, (v_[0] or {}).get("name")), "side": s, **(leg_sum(v_) or {})} for (c, s), v_ in m_sides.items()],
                  "overlap_fill": sorted(f"{c}:{s}" for c, s in line_fill_sides & set(m_sides)),
                  "overlap_order": sorted({f"{o['code']}:{o['side']}" for o in orders} & {f"{c}:{s}" for c, s in m_sides}),
                  "mentor_only_codes": sorted({c for c, _ in m_sides} - {o["code"] for o in orders}),
                  "line_only_fill_codes": sorted({o["code"] for o in filled} - {c for c, _ in m_sides})}
    cats = {}
    for o in orders:
        cats[o["cat"]] = cats.get(o["cat"], 0) + 1
    dist = dist_full.full(filled, key=lambda r: r.get("day_pnl_pct"), tag=lambda r: f"{r['name']} {r['side']} {r.get('fill_t', '')[:5]}")
    pos = []
    for c, p in (B["state"].get("positions") or {}).items():
        cl = M.close(c)
        pos.append({"code": c, "name": M.name(c), "qty": p.get("qty"), "cost": round(float(p.get("cost") or 0), 4), "close": cl, "float_pct": pct(cl, p.get("cost"))})
    return {"id": line["id"], "name": line.get("name"), "mode": line.get("mode"), "kind": line.get("kind"), "skill": line.get("skill"),
            "nav0": B["nav0"], "nav1": B["nav1"], "ret": B["ret"], "n_versions": len(B["vers"]), "n_rule_instances": len(insts),
            "n_orders": len(orders), "n_filled": len(filled), "n_trades_state": len(trades), "cats": cats, "fill_dist": dist,
            "orders": orders, "dropped": dropped, "periods": per, "mentor": mentor, "scenarios": scenario_check(B, M), "positions_close": pos,
            "check": {"state_trades_matched": sum(1 for t in trades if any(str(t.get('rule')) in o["rule_keys"] for o in filled)),
                      "state_trades": len(trades)}}


# ---------------------------------------------------------------- 你的决策日志 ----------------------------------------------------------------
_NOT_DECISION = ("照片", "照相", "照顾", "偏好", "偏偏")


def user_msgs(D):
    """用户当天发给 hermes 的微信消息: [(ts 'YYYY-MM-DDTHH:MM:SS', 文本, 源, 引用文本)]"""
    out, srcs = [], []
    t0 = dt.datetime.fromisoformat(D).timestamp()
    dbp = HERMES_HOME / "state.db"
    if dbp.exists():
        try:
            c = sqlite3.connect(f"file:{dbp.as_posix()}?mode=ro", uri=True, timeout=5)
            rows = c.execute("select m.timestamp, m.content from messages m join sessions s on s.id = m.session_id "
                             "where m.role = 'user' and s.source = 'weixin' and m.timestamp >= ? and m.timestamp < ? order by m.timestamp", (t0, t0 + 86400)).fetchall()
            c.close()
            out += [(dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds"), str(ct or ""), "hermes state.db", "") for ts, ct in rows]
            srcs.append(f"{dbp}(messages, role=user, source=weixin)")
        except Exception as e:   # noqa: BLE001
            srcs.append(f"{dbp} 读失败: {e!r}"[:160])
    gl = HERMES_HOME / "logs" / "gateway.log"
    quotes = []
    if gl.exists():
        rx = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO gateway\.run: inbound message: .*? msg='(.*)' reply_to_id=(\S*) reply_to_text='(.*)'\s*$")
        with gl.open(encoding="utf-8", errors="replace") as f:
            for l in f:
                if not l.startswith(D):
                    continue
                m = rx.match(l.rstrip("\n"))
                if m:
                    quotes.append((m.group(1).replace(" ", "T"), m.group(2), m.group(4)))
        srcs.append(f"{gl}(inbound message 行, 用来补引用文本; state.db 读不到时兜底)")
    if not out:
        out = [(t, msg, "hermes gateway.log", q) for t, msg, q in quotes]
    else:   # 引用文本按时间(±15 秒)+ 前 10 字对上
        res = []
        for ts, txt, src, _ in out:
            q = next((qq for tq, mq, qq in quotes if abs((dt.datetime.fromisoformat(tq) - dt.datetime.fromisoformat(ts)).total_seconds()) <= 15
                      and mq[:10] == txt[:10]), "")
            res.append((ts, txt, src, q))
        out = res
    qa = QA_DIR / f"qa-{D.replace('-', '')}.jsonl"
    if qa.exists():
        srcs.append(str(qa))
        have = {(t[:16], x[:10]) for t, x, _, _ in out}
        for r in jlines(qa):
            if r.get("input") and (str(r.get("ts", ""))[:16], str(r["input"])[:10]) not in have:
                out.append((str(r.get("ts")), str(r["input"]), "qa jsonl", ""))
    ded, last = [], {}
    for r in sorted(out):
        k = r[1].strip()
        if k in last and abs((dt.datetime.fromisoformat(r[0]) - dt.datetime.fromisoformat(last[k])).total_seconds()) <= 3:
            continue
        last[k] = r[0]
        ded.append(r)
    return ded, srcs


def v3_pushes(D, root_day):
    """当天 v3_ 推送(wx_sent.jsonl, 只取发成功的) + 该线 wx_send.log 里同一时刻的首行"""
    heads = {}
    for f in root_day.glob("*_*/wx_send.log"):
        for l in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"\[(\d\d:\d\d:\d\d)\] (.*)", l)
            if m:
                heads.setdefault(f.parent.name, []).append((m.group(1), m.group(2)))
    out = []
    for r in jlines(WX_SENT):
        ts, src = str(r.get("ts", "")), str(r.get("src", ""))
        if not ts.startswith(D) or not src.startswith(("live_", "paper_", "v3_")) or not r.get("ok"):
            continue
        hd = [h for h in heads.get(src, []) if h[0] <= ts[11:19] and sec(ts[11:19]) - sec(h[0]) <= 120]
        out.append({"ts": ts, "src": src, "line": src[3:], "chars": r.get("chars"), "hash": r.get("hash"), "head": hd[-1][1] if hd else None})
    return sorted(out, key=lambda x: x["ts"])


def decision_log(D, root_day, write=True):
    msgs, srcs = user_msgs(D)
    pushes = v3_pushes(D, root_day)
    recs = []
    for ts, txt, src, quote in msgs:
        s = txt.strip()
        s = re.sub(r"^\[(?:Replying to|引用)[^\]]*\]\s*", "", s)   # 微信引用前缀(若有)
        m = re.match(r"^(照|偏)\s*[:：,，。.\s]?\s*(.*)$", s, re.S)
        if not m or s.startswith(_NOT_DECISION):
            continue
        att, how = None, ""
        if quote:
            att = next((p for p in reversed(pushes) if p["ts"] <= ts and p.get("head") and (p["head"][:12] in quote or quote[:12] in (p["head"] or ""))), None)
            how = "按引用文本匹配" if att else ""
        if att is None:
            att = next((p for p in reversed(pushes) if p["ts"] <= ts), None)
            how = "按时间就近(它之前最近的一条 v3_ 推送)" if att else "当天它之前没有 v3_ 推送"
        recs.append({"date": D, "ts": ts, "verdict": m.group(1), "reason": m.group(2).strip(), "raw": txt, "src": src, "quote": quote or None,
                     "push": att, "attach": how, "gap_sec": int((dt.datetime.fromisoformat(ts) - dt.datetime.fromisoformat(att["ts"])).total_seconds()) if att else None})
    out = DLOG_DIR / f"{D}.jsonl"
    if write:
        DLOG_DIR.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            if not recs:
                f.write(json.dumps({"date": D, "n": 0, "note": "当天没有决策回复", "n_user_msgs": len(msgs), "n_v3_pushes": len(pushes), "sources": srcs},
                                   ensure_ascii=False) + "\n")
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"n": len(recs), "照": sum(r["verdict"] == "照" for r in recs), "偏": sum(r["verdict"] == "偏" for r in recs), "n_user_msgs": len(msgs),
            "n_v3_pushes": len(pushes), "sources": srcs, "file": rel(out),
            "attached": [{"ts": r["ts"][11:], "verdict": r["verdict"], "line": (r["push"] or {}).get("line"), "push_ts": (r["push"] or {}).get("ts", "")[11:],
                          "attach": r["attach"]} for r in recs]}   # 进 results 的只有 照 / 偏 + 挂到哪条推送; 理由原文只在隐私目录


# ---------------------------------------------------------------- 输出 ----------------------------------------------------------------
class Namer:
    """术语表: 股票名用全称, 第一次出现带 6 位代码"""

    def __init__(self, M):
        self.M, self.seen = M, set()

    def __call__(self, code, fb=""):
        nm = self.M.name(code, fb)
        if code in self.seen:
            return nm
        self.seen.add(code)
        return f"{nm}({code})"


def side_cn(s):
    return "买" if s == "BUY" else "卖"


def dline(d):
    """dist_full.line 换成术语表负号(−)"""
    return re.sub(r"(?<![\w])-(?=\d)", MINUS, dist_full.line(d))


def md_line(L, N):
    out = [f"## {L['name']}({LDS.ldir(L["id"])} · {'盯盘模式' if L['mode'] == 'watch' else '计划模式'}{' · 决策T' if L['kind'] == 'dt' else ''})", ""]
    nav = f"模拟账本 {L['nav0']} → {L['nav1']}({fp(L['ret'])})" if L.get("nav1") is not None else "模拟账本净值: summary.md 没读到"
    c = L["cats"]
    out.append(f"- {nav}; 共 {L['n_versions']} 版策略, 规则 {L['n_rule_instances']} 条(按版本计) → 去重后挂单 **{L['n_orders']} 张, 成交 {L['n_filled']} 张**"
               + (f"; 没成交的: " + " / ".join(f"{k} {v}" for k, v in c.items() if k != "成交") if L["n_orders"] > L["n_filled"] else ""))
    per = L.get("periods") or {}
    if per.get("partial"):
        out.append(f"- ⏸ **部分时段**(叫模型 {per['on_secs'] // 60} 分钟): {per['text']}")
    if L["n_filled"]:
        out.append(f"- 成交单当天盈亏(买 = 收盘相对成交价, 卖 = 卖价相对收盘): {dline(L['fill_dist'])}")
    if L["check"]["state_trades"] != L["check"]["state_trades_matched"]:
        out.append(f"- ⚠ state.json 成交 {L['check']['state_trades']} 笔, 对上挂单的只有 {L['check']['state_trades_matched']} 笔(规则号对不上, 要细查)")
    if L["orders"]:
        out += ["", "| # | 票 | 挂单 | 版本 / 生效 | 结局 | 之后走势 | 导师同票同向 |", "|---|---|---|---|---|---|---|"]
        for i, o in enumerate(L["orders"], 1):
            kind = " 炸板接" if o.get("type") == "board_dip" else (" 竞价" if o.get("auction") else "")
            q = "→".join(str(x) for x in o["qty_hist"]) if len(o["qty_hist"]) > 1 else str(o["qty"])
            order = f"{side_cn(o['side'])} {fnum(o['px'])} × {q}{kind}" + (f"(等 {o['after']} 成交后)" if o.get("after") else "")
            vv = o["versions"]
            ver = (f"v{vv[0]}" if len(vv) == 1 else f"v{vv[0]}~v{vv[-1]}") + f" · {o['from'][:5]}~{o['to'][:5]}"
            if o["cat"] == "成交":
                res = f"✅ 成交 {o['fill_t']} @{fnum(o['fill_px'])} × {o['fill_qty']}" + (" (部分)" if o.get("partial") else "") + (" (开盘竞价)" if o.get("fill_auction") else "") + (" ⏸停后撮合" if o.get("after_off") else "")
                if o["side"] == "BUY":
                    aft = f"收盘 {fnum(o['close'])} 浮盈 {fp(o.get('day_pnl_pct'))}; 成交后最高 {fp(o.get('after_high_pct'))} 最低 {fp(o.get('after_low_pct'))}"
                else:
                    aft = (f"卖后最高 {fp(o.get('sold_fly_pct'))}(卖飞) · 收盘 {fnum(o['close'])}({fp(o.get('close_vs_sell_pct'))})"
                           + (f" · 相对成本 {fp(o.get('vs_cost_pct'))}" if o.get("vs_cost_pct") is not None else ""))
                nd = o.get("next_day")
                aft += f"; 下一交易日({nd['date'][5:]}) 最高 {fp(o.get('next_high_pct'))} 收盘 {fp(o.get('next_close_pct'))}" if nd else "; 下一交易日: 暂无数据"
            else:
                res, aft = o["status"] + ("".join(f" 〔{t}〕" for t in o.get("miss_tags") or [])), (f"收盘 {fnum(o['close'])}(相对挂价 {fp(pct(o['close'], o['px']))})" if o.get("close") else "—")
            ms = o.get("mentor_same")
            men = "—" if L["kind"] != "mimic" else (f"有: {ms['n']} 笔 均价 {fnum(ms['avg'])} 首笔 {ms['first'][:5]}" if ms else ("同票反向" if o.get("mentor_code_any") else "无"))
            out.append(f"| {i} | {N(o['code'], o.get('name'))} | {order} | {ver} | {res} | {aft} | {men} |")
    else:
        out.append("- 当天一张挂单都没有(只设区间 / 叫醒条件)")
    if L["dropped"]:
        out.append("- 06 写了但执行器剔除: " + "; ".join(f"v{d['v']} " + " / ".join(map(str, d["items"])) for d in L["dropped"])[:600])
    m = L.get("mentor")
    if m is not None:
        if m["n_legs"]:
            bc = "; ".join(f"{side_cn(x['side'])} {N(x['code'], x.get('name'))} {x['n']} 笔 均价 {fnum(x['avg'])}({x['first'][:5]}~{x['last'][:5]})" for x in m["by_code"])
            out.append(f"- 导师真人({m['skill']}) 当天 {m['n_legs']} 笔: {bc}")
            out.append(f"  - 同票同向重合: 成交 {', '.join(m['overlap_fill']) or '无'}; 挂过单 {', '.join(m['overlap_order']) or '无'}; "
                       f"导师做了本线没碰: {', '.join(N(c) for c in m['mentor_only_codes']) or '无'}; 本线成交导师没做: {', '.join(N(c) for c in m['line_only_fill_codes']) or '无'}")
        else:
            out.append(f"- 导师真人({m['skill']}) 当天没有逐笔记录")
    if L["scenarios"]:
        out.append("- 情景核销: " + "; ".join(f"{N(s['code'], s.get('name'))} [{s['when']}] → {s['action']}: **{s['verdict']}**" + (f"({s['why']})" if s["why"] else "")
                                         for s in L["scenarios"]))
    else:
        out.append("- 情景核销: 06 没有情景字段, 跳过")
    if L["positions_close"]:
        out.append("- 收盘持仓(模拟账本): " + "; ".join(f"{N(p['code'])} {p['qty']} 股 成本 {fnum(p['cost'])} 收盘 {fnum(p['close'])}({fp(p['float_pct'])})" for p in L["positions_close"]))
    return out


def render_md(R, M):
    N = Namer(M)
    idx = []
    for nm, s in (("上证指数", "sh000001"), ("国证2000", "sz399303")):
        r = M.day.get(s) or {}
        if r.get("close") and r.get("pre_close"):
            idx.append(f"{nm} {fp(pct(r['close'], r['pre_close']))}")
    L = [f"# 计划核销 {R['date']}", "",
         f"> 零 token 生成 {R['generated_at']} · 账本根 `{R['root']}` · 行情: 日线 kline_day + 3 秒盘口 book_snap(名单外的票用 1 分钟线) · 当天 {' / '.join(idx) or '指数缺'}",
         "> 口径: 挂单 = 连续几版里同票同方向同价的规则合成一张(柜台里一直挂着); 生效期 = 这一版落地(链开始 + 耗时)到下一版落地, 连续竞价 09:30~14:57, 竞价单另看 09:25, 14:57 还活着的另看 15:00 尾盘竞价",
         "> 买入浮盈 = 收盘 ÷ 成交价 − 1(未扣费); 卖出 = 卖价 ÷ 收盘 − 1(正 = 卖在收盘上方); 卖飞 = 卖后当天最高 ÷ 卖价 − 1; 没成交的差多少 = 生效期内最低(买) / 最高(卖) ÷ 挂价 − 1", ""]
    T = R["total"]
    L += ["## 总览", "", f"- {len(R['lines'])} 本模拟账本, 挂单 {T['n_orders']} 张, 成交 {T['n_filled']} 张; 全部成交单当天盈亏: {dline(T['fill_dist'])}",
          "", "| 线 | 模式 | 叫模型时段 | 模拟账本 | 挂单 | 成交 | 没成交主因 | 导师同票同向成交 |", "|---|---|---|---|---|---|---|---|"]
    for x in R["lines"]:
        miss = max(((k, v) for k, v in x["cats"].items() if k != "成交"), key=lambda kv: kv[1], default=None)
        men = "—" if x["mentor"] is None else (", ".join(x["mentor"]["overlap_fill"]) or "无")
        pr = x.get("periods") or {}
        seg = f"⏸ {pr['off_at'][:5]} 起停" if pr.get("partial") else "全天"
        L.append(f"| {x['name']} | {'盯盘' if x['mode'] == 'watch' else '计划'} | {seg} | {fp(x['ret'])} | {x['n_orders']} | {x['n_filled']} | {f'{miss[0]} {miss[1]}' if miss else '—'} | {men} |")
    L.append("")
    for x in R["lines"]:
        L += md_line(x, N) + [""]
    d = R.get("decision_log")
    L.append("## 你的决策日志")
    L.append("")
    if d is None:
        L.append("- 回放账本根, 不做决策日志")
    elif not d["n"]:
        L.append(f"- 当天没有决策回复(用户当天发给 hermes 的微信 {d['n_user_msgs']} 条里没有以\"照 / 偏\"开头的; 当天 v3_ 推送成功 {d['n_v3_pushes']} 条)")
    else:
        L.append(f"- 共 {d['n']} 条: 照 {d['照']} / 偏 {d['偏']}; 理由原文只存隐私目录 `{d['file']}`")
        for a in d["attached"]:
            L.append(f"  - {a['ts'][:5]} {a['verdict']} → 挂到 {LDS.ldir(a["line"])} {a['push_ts'][:5]} 的推送({a['attach']})")
    if R.get("errors"):
        L += ["", "## 数据问题", ""] + [f"- {e}" for e in R["errors"]]
    return "\n".join(L) + "\n"


def run(D, root, write=True, do_dlog=None):
    root = Path(root)
    if not root.is_absolute():
        root = ROOT / root
    day = root / D if (root / D).is_dir() else root
    ldirs = sorted(p for p in LDS.line_dirs(day) if (p / "strategies").is_dir())
    if not ldirs:
        raise SystemExit(f"{day} 下没有 live_* / paper_* 账本目录")
    linecfg = {x["id"]: x for x in (jl(LINES_JSON, {}) or {}).get("lines") or []}
    def _live(lid):   # 10/24 实盘线: 线号 live_<skill>, 不在 lines.json 里
        import skill_names as SN
        sid = lid[5:]
        return {"id": lid, "name": SN.cn(sid) + "skill", "mode": "watch", "kind": "mimic", "skill": sid, "live": True}
    books = {p: linecfg.get(LDS.lid_of(p.name)) or (_live(p.name) if p.name.startswith("live_") else {"id": LDS.lid_of(p.name), "name": LDS.lid_of(p.name), "mode": "?", "kind": "?", "skill": None}) for p in ldirs}
    codes = set()
    for p in ldirs:
        codes |= book_codes(load_book(p))
    mlegs, merr = mentor_legs(D, sorted({ln.get("skill") for ln in books.values() if ln.get("kind") == "mimic" and ln.get("skill")}))
    for legs in mlegs.values():
        codes |= {x["code"] for x in legs}
    M = Market(D, codes)
    lines = [review_line(p, ln, M, mlegs) for p, ln in books.items()]
    allf = [o for x in lines for o in x["orders"] if o["cat"] == "成交"]
    R = {"date": D, "root": rel(day),
         "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
         "total": {"n_orders": sum(x["n_orders"] for x in lines), "n_filled": len(allf),
                   "fill_dist": dist_full.full(allf, key=lambda r: r.get("day_pnl_pct"), tag=lambda r: f"{r['name']} {r['side']} {r.get('fill_t', '')[:5]}")},
         "lines": lines, "errors": M.errors + ([merr] if merr else [])}
    if do_dlog is None:
        do_dlog = day.resolve().parent == LIVE.resolve()
    R["decision_log"] = decision_log(D, day, write=write) if do_dlog else None
    if write:
        od = day / "review"
        od.mkdir(parents=True, exist_ok=True)
        (od / "plan_review.json").write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        (od / "plan_review.md").write_text(render_md(R, M), encoding="utf-8")
    return R, M


def main():
    ap = argparse.ArgumentParser(description="计划核销 + 你的决策日志(零 token)")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--root", default="results/_live", help="账本根: results/_live(默认) 或 results/_replay/<标签>(其下有 <D>/v3_*)")
    ap.add_argument("--no-decision-log", action="store_true", help="不做决策日志(回放根默认就不做)")
    ap.add_argument("--dry", action="store_true", help="只打印摘要, 不写文件")
    a = ap.parse_args()
    R, _ = run(a.date, a.root, write=not a.dry, do_dlog=False if a.no_decision_log else None)
    for x in R["lines"]:
        print(f"{x['id']:<18} 挂单 {x['n_orders']:>2} 成交 {x['n_filled']:>2} 模拟账本 {fp(x['ret'])}  {' / '.join(f'{k} {v}' for k, v in x['cats'].items())}")
    print("全部成交单当天盈亏:", dist_full.line(R["total"]["fill_dist"]))
    d = R.get("decision_log")
    print("决策日志:", "不做(回放)" if d is None else (f"{d['n']} 条(照 {d['照']} / 偏 {d['偏']}) → {d['file']}" if d["n"] else f"当天没有决策回复 → {d['file']}"))
    if R["errors"]:
        print("数据问题:", "; ".join(R["errors"]))
    if not a.dry:
        print("写出:", f"{R['root']}/review/plan_review.md + plan_review.json")


if __name__ == "__main__":
    main()
