# -*- coding: utf-8 -*-
"""tudou_deep.py — 不吃土豆0 深度蒸馏的机械底座(零 token, 只读; 10/17 agent③ 建)

补三块画像的"因"所需统计: ①转债 T 法(开盘 scalp 的通道×缺口×持有秒数×出场位置) ②强赎前后(按东财 RPT_BOND_CB_LIST
公告日/退市日给每笔 RT 打相位) ③盘中节奏(当日第几笔、上一笔盈亏对下一笔的影响、换债/同债复做、首笔规模)。
数据: downloads/tzzb/buchitudou0/change_bs_*(逐笔腿) + downloads/quotes/cb/kline/<code>.json(转债日线, 含已退市)
      + 行情库 kline_day 正股日线(只读) + downloads/quotes/cb/meta/RPT_BOND_CB_LIST_tudou51_20261017.json(强赎/不强赎公告, 1 次请求, req_guard 记账)
产物: scripts/temp/tudou_deep_<日>.json(RT 明细+分组表)  stdout=分组表
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/tudou_deep.py [--meta <RPT 文件>]  --selftest
口径: RT=同日同债 FIFO 买→卖配对(土豆全日内, 无隔夜); pnl=卖均/买均-1(不含费用); 通道=首买腿时刻(09:25:00 竞价 / 09:30:00 死窗 / 09:30:01~09:35 追单 / 之后 盘中)。
      强赎相位: EXECUTE_REASON_SH 4=强赎(有赎回价+退市日) 5=到期 6=不强赎公告; 以 NOTICE_DATE_SH 为公告日, 按交易日距离分档。
      正股涨停 = 涨幅 ≥ 板块涨跌幅−0.3pp(主板 10%/创业科创 20%; ST 未区分, 他的正股无 ST)。
"""
import argparse, json, statistics as st, sys
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
META_DEF = ROOT / "downloads" / "quotes" / "cb" / "meta" / "RPT_BOND_CB_LIST_tudou51_20261017.json"


def load_legs():
    from gen_tzzb_profile import load_legs as _ll
    out = []
    for t in _ll("buchitudou0"):
        c = str(t["stock_code"])
        if c.startswith(("204", "1318")) or str(t["trans_date"]).endswith("00:00:00"):
            continue
        q = float(t.get("trans_count") or 0); px = float(t.get("trans_price") or 0)
        if q <= 0 or px <= 0:
            continue
        out.append({"code": c, "name": t.get("stock_name"), "d": t["trans_date"][:10], "t": t["trans_date"][11:19], "side": "B" if str(t["op"]) == "1" else "S", "q": q, "px": px})
    return sorted(out, key=lambda x: (x["d"], x["t"], x["side"] != "B"))


def round_trips(legs):
    """同日同债 FIFO; 返回 RT 列表(一个卖腿可能切成多段, 合并成 '买批→卖腿' 粒度后再按首买时刻聚成 RT)"""
    by = defaultdict(list)
    for l in legs:
        by[(l["d"], l["code"])].append(l)
    rts = []
    for (d, code), L in by.items():
        lots = []
        cur = None
        for l in L:
            if l["side"] == "B":
                if cur is None or cur["closed"]:
                    cur = {"d": d, "code": code, "name": l["name"], "buy_t": l["t"], "bq": 0.0, "bamt": 0.0, "sq": 0.0, "samt": 0.0, "sell_t": None, "closed": False, "nb": 0, "ns": 0}
                    lots.append(cur)
                cur["bq"] += l["q"]; cur["bamt"] += l["q"] * l["px"]; cur["nb"] += 1
            else:
                if cur is None:
                    continue   # 无买腿的卖(窗口前持仓), 土豆几乎没有
                cur["sq"] += l["q"]; cur["samt"] += l["q"] * l["px"]; cur["ns"] += 1; cur["sell_t"] = l["t"]
                if cur["sq"] >= cur["bq"] - 1e-6:
                    cur["closed"] = True
        for x in lots:
            if x["sq"] <= 0:
                continue
            bp, sp = x["bamt"] / x["bq"], x["samt"] / x["sq"]
            hs = (datetime.strptime(x["sell_t"], "%H:%M:%S") - datetime.strptime(x["buy_t"], "%H:%M:%S")).total_seconds()
            if x["buy_t"] < "09:30:00" and x["sell_t"] >= "09:30:00":
                hs -= 0   # 竞价成交到开盘之间不连续交易, 秒数照算(画像口径一致)
            rts.append({"d": d, "code": code, "name": x["name"], "buy_t": x["buy_t"], "sell_t": x["sell_t"], "bp": bp, "sp": sp, "pnl": sp / bp - 1,
                        "hold_s": hs, "notional": x["bamt"], "nb": x["nb"], "ns": x["ns"], "unclosed": x["sq"] < x["bq"] - 1e-6})
    rts.sort(key=lambda r: (r["d"], r["buy_t"]))
    k = Counter()
    for r in rts:
        k[r["d"]] += 1; r["idx"] = k[r["d"]]
    return rts


def channel(t):
    if t < "09:30:00":
        return "竞价"
    if t == "09:30:00":
        return "死窗"
    if t <= "09:35:00":
        return "追单"
    return "盘中"


def load_cb_daily(code):
    try:
        j = json.loads((ROOT / "downloads" / "quotes" / "cb" / "kline" / f"{code}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return j


def stock_daily(symbols):
    sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
    from kline_db import db
    c = db()
    out = defaultdict(dict)
    try:
        cur = c.cursor()
        ph = ",".join(["%s"] * len(symbols))
        cur.execute(f"select symbol, trade_date, open, high, low, close from kline_day where symbol in ({ph}) and trade_date >= '2025-10-01' order by symbol, trade_date", tuple(symbols))
        for s, d, o, h, l, cl in cur.fetchall():
            out[s][d.isoformat()] = (float(o), float(h), float(l), float(cl))
    finally:
        c.close()
    return out


def sym(code):
    return ("sh" if code.startswith(("6", "9")) else "sz") + code


def lim(code):
    return 0.2 if code.startswith(("300", "301", "688", "689")) else 0.1


def phase(meta, code, d, tdays):
    m = meta.get(code)
    if not m:
        return "无元数据", None
    reason, notice, delist = m["reason"], m["notice"], m["delist"]
    if not notice or reason not in ("4", "6"):
        return "无强赎/不强赎公告", None
    try:
        i_d, i_n = tdays.index(d), tdays.index(notice) if notice in tdays else None
    except ValueError:
        return "?", None
    if i_n is None:
        # 公告日非交易日: 取其后第一个交易日
        nxt = [x for x in tdays if x >= notice]
        if not nxt:
            return "?", None
        i_n = tdays.index(nxt[0])
    off = i_d - i_n
    tag = "强赎" if reason == "4" else "不强赎"
    if off >= 0:
        if reason == "4" and delist and d >= delist:
            return f"{tag}:退市后?", off
        return f"{tag}:公告后", off
    if off >= -15:
        return f"{tag}:公告前15日内(触发计数后段)", off
    if off >= -45:
        return f"{tag}:公告前16~45日", off
    return f"{tag}:公告前>45日", off


def grp(rows, key, label):
    G = defaultdict(list)
    for r in rows:
        G[key(r)].append(r)
    out = []
    for k, L in sorted(G.items(), key=lambda kv: str(kv[0])):
        p = [x["pnl"] for x in L]
        out.append({label: k, "n": len(L), "days": len({x["d"] for x in L}), "win": round(sum(1 for x in p if x > 0) / len(p), 3), "pnl_mean": round(st.mean(p), 4),
                    "pnl_med": round(st.median(p), 4), "hold_s_med": st.median([x["hold_s"] for x in L]),
                    "close_vs_buy_med": round(st.median([x["close_vs_buy"] for x in L if x.get("close_vs_buy") is not None]), 4) if any(x.get("close_vs_buy") is not None for x in L) else None})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", default=str(META_DEF))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    legs = load_legs()
    rts = round_trips(legs)
    raw = json.loads(Path(a.meta).read_text(encoding="utf-8"))["result"]["data"]
    meta = {x["SECURITY_CODE"]: {"reason": str(x.get("EXECUTE_REASON_SH") or ""), "notice": (x.get("NOTICE_DATE_SH") or "")[:10] or None, "delist": (x.get("DELIST_DATE") or "")[:10] or None,
                                 "stock": x.get("CONVERT_STOCK_CODE"), "conv0": x.get("INITIAL_TRANSFER_PRICE"), "list": (x.get("LISTING_DATE") or "")[:10]} for x in raw}
    cbd = {c: load_cb_daily(c) for c in {r["code"] for r in rts}}
    stk = stock_daily(sorted({sym(m["stock"]) for m in meta.values() if m.get("stock")}))
    tdays = sorted(stk.get("sh603538", {}).keys() | {d for v in cbd.values() for d in v})
    for r in rts:
        k = cbd.get(r["code"], {})
        days = sorted(k)
        if r["d"] in k:
            i = days.index(r["d"])
            o, h, l, c = k[r["d"]]["o"], k[r["d"]]["h"], k[r["d"]]["l"], k[r["d"]]["c"]
            pc = k[days[i - 1]]["c"] if i else None
            r.update({"gap": o / pc - 1 if pc else None, "buy_vs_open": r["bp"] / o - 1, "sell_pos": (r["sp"] - l) / (h - l) if h > l else None,
                      "close_vs_buy": c / r["bp"] - 1, "day_ret": c / pc - 1 if pc else None, "high_vs_buy": h / r["bp"] - 1, "price_lvl": pc or o})
        m = meta.get(r["code"], {})
        s = stk.get(sym(m.get("stock") or ""), {})
        sd = sorted(s)
        if r["d"] in s:
            j = sd.index(r["d"])
            if j >= 2:
                p1, p2 = s[sd[j - 1]][3], s[sd[j - 2]][3]
                r["stk_prev_ret"] = p1 / p2 - 1
                r["stk_prev_zt"] = r["stk_prev_ret"] >= lim(m["stock"]) - 0.003
                n = 0
                for jj in range(j - 1, 0, -1):
                    if s[sd[jj]][3] / s[sd[jj - 1]][3] - 1 >= lim(m["stock"]) - 0.003:
                        n += 1
                    else:
                        break
                r["stk_boards_prev"] = n
                r["stk_gap"] = s[r["d"]][0] / p1 - 1
                r["stk_day_ret"] = s[r["d"]][3] / p1 - 1
                if m.get("conv0"):
                    r["parity0"] = 100 * p1 / float(m["conv0"])   # 用初始转股价(未计下修/分红调整)的 T-1 转股价值, 粗口径
        r["phase"], r["phase_off"] = phase(meta, r["code"], r["d"], tdays)
        r["channel"] = channel(r["buy_t"])
    # ---- 分组 ----
    def gapb(r):
        g = r.get("gap")
        return "无日线" if g is None else ("a ≤-2%" if g <= -0.02 else "b -2~0%" if g <= 0 else "c 0~+2%" if g <= 0.02 else "d +2~5%" if g <= 0.05 else "e >+5%")

    def lvlb(r):
        p = r.get("price_lvl")
        return "无" if p is None else ("a <130" if p < 130 else "b 130~170" if p < 170 else "c 170~250" if p < 250 else "d ≥250")

    def holdb(r):
        h = r["hold_s"]
        return "a ≤10s" if h <= 10 else "b 11~60s" if h <= 60 else "c 1~5min" if h <= 300 else "d >5min"

    def stkb(r):
        if r.get("stk_prev_zt") is None:
            return "无正股数据"
        return f"T-1 正股涨停(连板{min(r['stk_boards_prev'], 3)}{'+' if r['stk_boards_prev'] >= 3 else ''})" if r["stk_prev_zt"] else (
            "T-1 正股涨 5%~涨停" if r["stk_prev_ret"] >= 0.05 else "T-1 正股涨 0~5%" if r["stk_prev_ret"] >= 0 else "T-1 正股跌")

    def stkgap(r):
        g = r.get("stk_gap")
        return "无" if g is None else ("a 正股低开≤-2%" if g <= -0.02 else "b 正股平开±2%" if g < 0.02 else "c 正股高开2~5%" if g < 0.05 else "d 正股高开≥5%")

    def parb(r):
        p = r.get("parity0")
        return "无" if p is None else ("a 转股价值<100" if p < 100 else "b 100~130" if p < 130 else "c 130~200" if p < 200 else "d ≥200")

    T = {"channel": grp(rts, lambda r: r["channel"], "通道"), "gap": grp(rts, gapb, "转债开盘缺口"), "price": grp(rts, lvlb, "转债价位(昨收)"),
         "hold": grp(rts, holdb, "持有时长"), "idx": grp(rts, lambda r: min(r["idx"], 4), "当日第几笔(4=4+)"), "stk": grp(rts, stkb, "正股 T-1"),
         "stkgap": grp(rts, stkgap, "正股当日开盘"), "phase": grp(rts, lambda r: r["phase"], "强赎相位"), "parity": grp(rts, parb, "T-1 转股价值(初始转股价, 粗)")}
    # 上一笔盈亏 → 下一笔
    prev = {}
    nxt = []
    for r in rts:
        if r["d"] in prev:
            nxt.append({**r, "prev_win": prev[r["d"]]["pnl"] > 0, "same_code": prev[r["d"]]["code"] == r["code"]})
        prev[r["d"]] = r
    T["after_prev"] = grp(nxt, lambda r: ("上一笔赚" if r["prev_win"] else "上一笔亏") + ("·同债" if r["same_code"] else "·换债"), "前一笔")
    # 当日笔数分布 & 当日最后一笔是赚还是亏
    perday = defaultdict(list)
    for r in rts:
        perday[r["d"]].append(r)
    T["rt_per_day"] = dict(Counter(min(len(v), 6) for v in perday.values()))
    last = [v[-1] for v in perday.values() if len(v) >= 2]
    T["last_of_multi_win"] = round(sum(1 for x in last if x["pnl"] > 0) / len(last), 3) if last else None
    T["stop_after_loss"] = {"亏损后当日不再做": sum(1 for v in perday.values() for i, x in enumerate(v) if x["pnl"] <= 0 and i == len(v) - 1),
                            "亏损后继续": sum(1 for v in perday.values() for i, x in enumerate(v) if x["pnl"] <= 0 and i < len(v) - 1),
                            "盈利后当日不再做": sum(1 for v in perday.values() for i, x in enumerate(v) if x["pnl"] > 0 and i == len(v) - 1),
                            "盈利后继续": sum(1 for v in perday.values() for i, x in enumerate(v) if x["pnl"] > 0 and i < len(v) - 1)}
    # 强赎: 每只强赎债 他在公告前/后的出手日
    rd = defaultdict(lambda: {"before": set(), "after": set()})
    for r in rts:
        m = meta.get(r["code"], {})
        if m.get("reason") in ("4", "6") and m.get("notice"):
            rd[(r["code"], r["name"], m["reason"], m["notice"], m.get("delist"))]["after" if r["d"] >= m["notice"] else "before"].add(r["d"])
    T["redeem_bonds"] = [{"code": k[0], "name": k[1], "kind": "强赎" if k[2] == "4" else "不强赎", "notice": k[3], "delist": k[4], "days_before": len(v["before"]), "days_after": len(v["after"]),
                          "last_before": max(v["before"]) if v["before"] else None, "first_after": min(v["after"]) if v["after"] else None} for k, v in sorted(rd.items(), key=lambda kv: kv[0][3])]
    T["meta_reason_count"] = dict(Counter({"4": "强赎", "5": "到期", "6": "不强赎"}.get(m["reason"], "无公告") for m in meta.values()))
    T["n_rt"] = len(rts); T["n_days"] = len(perday); T["window"] = [rts[0]["d"], rts[-1]["d"]]
    # 出场: 卖价在当日区间位置 / 买后当日最高能赚多少 / 拿到收盘
    T["exit"] = {"sell_pos_med": st.median([r["sell_pos"] for r in rts if r.get("sell_pos") is not None]),
                 "high_vs_buy_med": st.median([r["high_vs_buy"] for r in rts if r.get("high_vs_buy") is not None]),
                 "captured_med": st.median([r["pnl"] / r["high_vs_buy"] for r in rts if r.get("high_vs_buy") and r["high_vs_buy"] > 0.002]),
                 "close_vs_buy_med": st.median([r["close_vs_buy"] for r in rts if r.get("close_vs_buy") is not None])}
    out = ROOT / "scripts" / "temp" / f"tudou_deep_{datetime.now():%Y%m%d}.json"
    out.write_text(json.dumps({"tables": T, "rts": rts}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for k, v in T.items():
        if isinstance(v, list):
            print(f"== {k}")
            for x in v:
                print("  ", json.dumps(x, ensure_ascii=False))
        else:
            print(f"== {k}: {json.dumps(v, ensure_ascii=False, default=str)}")
    print(f"产物: {out}")


def _selftest():
    legs = [{"code": "A", "name": "a", "d": "2026-01-02", "t": "09:25:00", "side": "B", "q": 100, "px": 100},
            {"code": "A", "name": "a", "d": "2026-01-02", "t": "09:30:10", "side": "S", "q": 60, "px": 102},
            {"code": "A", "name": "a", "d": "2026-01-02", "t": "09:30:20", "side": "S", "q": 40, "px": 101},
            {"code": "A", "name": "a", "d": "2026-01-02", "t": "10:00:00", "side": "B", "q": 50, "px": 103},
            {"code": "A", "name": "a", "d": "2026-01-02", "t": "10:00:30", "side": "S", "q": 50, "px": 102}]
    r = round_trips(legs)
    assert len(r) == 2 and abs(r[0]["sp"] - 101.6) < 1e-9 and r[0]["hold_s"] == 320 and r[1]["idx"] == 2 and r[1]["pnl"] < 0
    assert channel("09:25:00") == "竞价" and channel("09:30:00") == "死窗" and channel("09:30:43") == "追单" and channel("10:17:56") == "盘中"
    td = ["2026-04-10", "2026-04-13", "2026-04-14", "2026-04-15"]
    meta = {"X": {"reason": "4", "notice": "2026-04-14", "delist": "2026-05-08"}}
    assert phase(meta, "X", "2026-04-15", td) == ("强赎:公告后", 1) and phase(meta, "X", "2026-04-10", td)[1] == -2
    print("tudou_deep selftest PASS")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
