# -*- coding: utf-8 -*-
"""collect_cb_facts.py — 全市场可转债 每日事实表(10/19 用户口述的转债逻辑落成数据; 每晚 1~2 个请求 + 本地行情库计算)

为什么(用户 10/19 原话整理, 土豆 = 阶段妖债反复套利):
  ① 正股 10cm 涨停 + 情绪好 → 转债可能拉 20cm(转债涨跌幅 ±20%, 正股主板 ±10%, 同一事件转债弹性更大)
  ② 溢价率 + 临赎回: 临期债(强赎公告 / 快触发强赎 / 快到期)要有事实进素材包
  ③ 溢价率为负且偏离大 → 可能拉溢价(负溢价套利: 买债转股卖股, 资金会把负溢价抹平)
  ④ 妖债跟时间热点会有多只, 但会有最强的一支, 资金在里面薅羊毛 / 剥头皮 → 同族里按成交额 / 换手挑最强
数据:
  条款 / 转股价 / 强赎公告 = 东财 datacenter RPT_BOND_CB_LIST(全市场一次 ~2 页, 走 req_guard em_datacenter); 东财字段 TRANSFER_VALUE = 当期转股价(含下修,
    与 INITIAL_TRANSFER_PRICE 对照), EXECUTE_REASON_SH 4=强赎 5=到期 6=不强赎, NOTICE_DATE_SH 公告日, DELIST_DATE 退市日
  价格 = 行情库当日 downloads/market/<D>/kline_day.jsonl(转债 + 正股, 零请求)
  强赎触发计数 = 正股近 30 个交易日收盘 ≥ 当期转股价 × 130% 的天数(本地日线; 条款都是"30 日内 15 日"口径, 少数例外以 REDEEM_CLAUSE 原文为准)
算(每只转债): 转股价值 = 正股收盘 × 100 / 转股价; 溢价率 = 转债收盘 / 转股价值 − 1; 正股当日涨跌 / 是否涨停 / 近 5 日涨停次数; 转债当日涨跌 / 成交额 / 换手;
  强赎相位(已公告强赎 + 距退市日 / 不强赎公告 + 公告日 / 触发计数 n/15 / 距到期天数)
产物: downloads/market/<D>/cb_facts.jsonl(一行一只) + cb_facts.md(给链 / 人看的精选: 成交额前 10、正股涨停的债、负溢价偏离大的、临期 / 临赎回的、同族最强)
消费: run_chain.py tudou_t0_block(土豆链 04/06 注入精选), ctx_index(可扩), 土豆 skill 复盘
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/market/collect_cb_facts.py [--date D] [--no-fetch](只用缓存的条款表)
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import a_rules as AR   # noqa: E402
from req_guard import gfetch   # noqa: E402

MKT = ROOT / "downloads" / "market"
META = ROOT / "downloads" / "quotes" / "cb" / "meta"
URL = ("https://datacenter-web.eastmoney.com/api/data/v1/get?sortColumns=SECURITY_CODE&sortTypes=1&pageSize=500&pageNumber={p}"
       "&reportName=RPT_BOND_CB_LIST&columns=ALL&quoteColumns=&source=WEB&client=WEB")


def fetch_meta(D, use_cache):
    f = META / f"RPT_BOND_CB_LIST_all_{D}.json"
    if f.exists() or use_cache:
        cands = sorted(META.glob("RPT_BOND_CB_LIST_all_*.json"))
        if f.exists() or cands:
            return json.loads((f if f.exists() else cands[-1]).read_text(encoding="utf-8")), (f if f.exists() else cands[-1]).name
        return [], None
    rows = []
    for p in range(1, 6):
        r = gfetch(URL.format(p=p), headers={"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}, timeout=15)
        j = r.json()
        res = (j or {}).get("result") or {}
        rows += res.get("data") or []
        if p >= int(res.get("pages") or 1):
            break
    META.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows, f.name


def kday(D):
    out = {}
    p = MKT / D / "kline_day.jsonl"
    for l in p.open(encoding="utf-8"):
        r = json.loads(l)
        out[r["symbol"]] = r
    return out


def stock_hist(sym, D, n=30):
    """正股近 n 个交易日收盘(行情库: history + 每日目录)"""
    rows = {}
    h = MKT / "history" / "kline_day" / f"{sym}.jsonl"
    if h.exists():
        for l in h.open(encoding="utf-8"):
            r = json.loads(l)
            rows[r["tradeDate"]] = r
    return rows


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args()
    D = a.date
    meta, src = fetch_meta(D, a.no_fetch)
    if not meta:
        print("条款表拿不到(东财 datacenter), 退出")
        sys.exit(2)
    K = kday(D)
    SN = {}
    try:
        smf = sorted(p for p in MKT.iterdir() if (p / "security_master.jsonl").exists() and p.name <= D)[-1] / "security_master.jsonl"
        for l in smf.open(encoding="utf-8"):
            r = json.loads(l)
            SN[r.get("code")] = r.get("name")
    except (IndexError, OSError):
        pass
    days = sorted(p.name for p in MKT.iterdir() if re.fullmatch(r"\d{4}-\d\d-\d\d", p.name) and p.name <= D and (p / "kline_day.jsonl").exists())
    recent = {}   # 每日目录近 30 天(history 文件只到 10/09, 两者合并)
    for d in days[-30:]:
        if d == D:
            recent[d] = K
        else:
            recent[d] = {}
            for l in (MKT / d / "kline_day.jsonl").open(encoding="utf-8"):
                r = json.loads(l)
                if r["symbol"][2:4] not in ("11", "12"):
                    recent[d][r["symbol"]] = r
    out = []
    for m in meta:
        code = str(m.get("SECURITY_CODE") or "")
        if not re.fullmatch(r"1[12]\d{4}", code) or m.get("DELIST_DATE") and str(m["DELIST_DATE"])[:10] < D:
            continue
        csym, ssym = AR.symbol(code), AR.symbol(str(m.get("CONVERT_STOCK_CODE") or ""))
        cb, st = K.get(csym), K.get(ssym)
        if not cb or not cb.get("close"):
            continue
        cp = m.get("TRANSFER_VALUE") or m.get("INITIAL_TRANSFER_PRICE")
        try:
            cp = float(cp)
        except (TypeError, ValueError):
            cp = None
        row = {"code": code, "name": m.get("SECURITY_NAME_ABBR"), "stock": str(m.get("CONVERT_STOCK_CODE") or ""), "stock_name": SN.get(str(m.get("CONVERT_STOCK_CODE") or "")) or "",
               "close": cb["close"], "pct": round(cb["close"] / cb["preClose"] - 1, 4) if cb.get("preClose") else None, "amount": cb.get("amount"),
               "turnover": cb.get("turnoverRate"), "conv_price": cp, "conv_price0": m.get("INITIAL_TRANSFER_PRICE"), "rating": m.get("RATING"),
               "scale": m.get("ACTUAL_ISSUE_SCALE"), "expire": str(m.get("EXPIRE_DATE") or "")[:10]}
        if st and st.get("close") and cp:
            row["stock_close"], row["stock_pct"] = st["close"], (round(st["close"] / st["preClose"] - 1, 4) if st.get("preClose") else None)
            row["stock_limit_up"] = bool(st.get("limitUp") and st["close"] >= float(st["limitUp"]) - 0.005)
            row["conv_value"] = round(st["close"] * 100 / cp, 2)
            row["premium"] = round(cb["close"] / row["conv_value"] - 1, 4)
            # 近 5 日正股涨停次数 / 30 日强赎触发计数
            zt, trig = 0, 0
            H = stock_hist(ssym, D)                      # history(到 10/09 的批量回补) + 每日目录, 合起来取近 30 个交易日
            for d in days:
                s = (recent.get(d) or {}).get(ssym) or (K.get(ssym) if d == D else None)
                if s:
                    H[d] = s
            seq = [H[d] for d in sorted(H) if d <= D][-30:]
            for i, s in enumerate(seq):
                if s.get("close") and s["close"] >= cp * 1.3:
                    trig += 1
                if i >= len(seq) - 5 and s.get("limitUp") and s["close"] >= float(s["limitUp"]) - 0.005:
                    zt += 1
            days_seen = len(seq)
            row["stock_zt5"], row["redeem_trig30"], row["trig_days_seen"] = zt, trig, days_seen
        reason, nd = str(m.get("EXECUTE_REASON_SH") or ""), str(m.get("NOTICE_DATE_SH") or "")[:10]
        row["phase"] = {"4": "已公告强赎", "5": "到期", "6": "不强赎公告"}.get(reason, "")
        row["notice_date"], row["delist_date"] = nd or None, (str(m.get("DELIST_DATE") or "")[:10] or None)
        try:
            row["days_to_expire"] = (dt.date.fromisoformat(row["expire"]) - dt.date.fromisoformat(D)).days if row["expire"] else None
        except ValueError:
            row["days_to_expire"] = None
        out.append(row)
    od = MKT / D
    with (od / "cb_facts.jsonl").open("w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (od / "cb_facts.md").write_text(digest(out, D, src), encoding="utf-8")
    print(f"cb_facts {D}: {len(out)} 只(条款表 {src}) → {od.relative_to(ROOT)}/cb_facts.jsonl / .md")


def fmt(r):
    s = f"{r['name']}({r['code']}) 收 {r['close']}" + (f"({r['pct'] * 100:+.1f}%)" if r.get("pct") is not None else "") + (f" 额 {r['amount'] / 1e8:.1f}亿" if r.get("amount") else "")
    if r.get("premium") is not None:
        s += f" | 正股 {r['stock_name']}{'(涨停)' if r.get('stock_limit_up') else ''} {r['stock_pct'] * 100:+.1f}% | 转股价值 {r['conv_value']} 溢价率 {r['premium'] * 100:+.1f}%"
    if r.get("phase"):
        s += f" | {r['phase']}{(' 退市 ' + r['delist_date']) if r.get('delist_date') else ''}{(' 公告 ' + r['notice_date']) if r.get('notice_date') else ''}"
    if r.get("redeem_trig30") is not None and r["redeem_trig30"] >= 8 and not r.get("phase"):
        s += f" | 强赎计数 {r['redeem_trig30']}/15(近 30 日)"
    return s


def digest(rows, D, src):
    L = [f"# 可转债事实表 {D}(collect_cb_facts.py 机械生成; 条款 {src}, 价格 = 行情库当日日线)", "",
         "> 用户 10/19 口述的转债逻辑: ①正股 10cm 涨停 + 情绪好 → 转债可能拉 20cm ②临赎回 / 临期要有事实 ③溢价率为负且偏离大 → 可能拉溢价 ④妖债同一热点会有多只, 资金在最强的一只里反复做。下面只列事实, 怎么用由 skill 规则裁决。", ""]
    by_amt = sorted([r for r in rows if r.get("amount")], key=lambda r: -r["amount"])
    L += ["## 成交额前 10(土豆 09:25 竞价买的 ≈ 前一日额第 1, 10/18 逆向 103 天 top1 60%)", ""] + [f"{i}. {fmt(r)}" for i, r in enumerate(by_amt[:10], 1)]
    zt = [r for r in rows if r.get("stock_limit_up")]
    L += ["", f"## 正股今天涨停的债({len(zt)} 只; 10cm 正股涨停 → 转债 ±20% 还有空间)", ""] + [f"- {fmt(r)}" + (f" | 正股近 5 日涨停 {r['stock_zt5']} 次" if r.get("stock_zt5") else "") for r in sorted(zt, key=lambda r: -(r.get("amount") or 0))[:15]]
    neg = sorted([r for r in rows if r.get("premium") is not None and r["premium"] < -0.02], key=lambda r: r["premium"])
    L += ["", f"## 负溢价(溢价率 < −2%, {len(neg)} 只; 偏离越大越可能被拉回)", ""] + [f"- {fmt(r)}" for r in neg[:10]]
    red = [r for r in rows if r.get("phase") == "已公告强赎"]
    near = sorted([r for r in rows if not r.get("phase") and (r.get("redeem_trig30") or 0) >= 10], key=lambda r: -r["redeem_trig30"])
    exp = sorted([r for r in rows if r.get("days_to_expire") is not None and 0 <= r["days_to_expire"] <= 120], key=lambda r: r["days_to_expire"])
    L += ["", f"## 临赎回 / 临期(已公告强赎 {len(red)} 只 / 强赎计数 ≥10 {len(near)} 只 / 120 天内到期 {len(exp)} 只)", ""]
    L += [f"- [强赎] {fmt(r)}" for r in red[:10]] + [f"- [快触发] {fmt(r)}" for r in near[:10]] + [f"- [到期 {r['days_to_expire']} 天] {fmt(r)}" for r in exp[:8]]
    # 同族最强: 正股近 5 日有涨停的债里, 按成交额排, 同一正股多只债取额最大
    hot = sorted([r for r in rows if (r.get("stock_zt5") or 0) >= 1], key=lambda r: -(r.get("amount") or 0))
    L += ["", f"## 热点妖债候选(正股近 5 日有涨停, {len(hot)} 只, 按成交额; 同一热点里额最大 / 换手最高的那只通常是资金反复做的'最强一支')", ""]
    L += [f"- {fmt(r)} | 正股近 5 日涨停 {r['stock_zt5']} 次" + (f" | 换手 {r['turnover']:.0f}%" if r.get("turnover") else "") for r in hot[:12]]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
