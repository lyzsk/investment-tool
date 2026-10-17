# -*- coding: utf-8 -*-
"""mentor_scope.py — tzzb 导师能力圈逆推(零 token, 10/15 方案 A: 导师链"看哪"由本导师能力圈决定)
数据: downloads/tzzb/<ledger>/position_change_p*.json(逐笔腿, 两融 op 已归一) + day_positions.json(每日持仓) + downloads/f10/<code>.json(东财 F10 行业/概念缓存, 缺的抓, 统一请求层+随机抖动)
统计每位导师(近 120 个有成交的交易日): 板块分布(沪深主板/创业板/科创板/北交所/ST/ETF/转债) / 最常买的 15 只与其行业 / 行业 Top5 / 持仓天数中位 / 同时持股数中位 / 单票最大仓位中位 / 买入时段分布
输出: scripts/tzzb/mentor_scope.json + docs/research/mentor_scope_20261015.md
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/mentor_scope.py [--no-fetch] [--asof YYYY-MM-DD] [--out-json <f>] [--out-md <f>]
10/16 晚 持有期改造: 加 hold_days_p75(持仓天数 P75=拿得住的上限, 与 hold_days_med 同一口径: day_positions 连续收盘持仓段长度);
  --asof D = 只用 D 之前的逐笔/收盘持仓(回放防后见之明); 无账本导师(B站 UP)与转债土豆写占位条目 hold_days_med/p75="无统计，按画像"
"""
import collections, datetime as dt, glob, json, random, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NO_STAT = "无统计，按画像"
NO_LEDGER = {"taoge": "桃哥", "qushitiange": "趋势天哥", "lubenyuan": "卢本圆", "buchitudou0": "不吃土豆0"}   # 无持仓天数统计的导师(B站 UP 无账本; 土豆=转债 T+0 不进统计)
TZ = ROOT / "downloads" / "tzzb"
F10 = ROOT / "downloads" / "f10"
NOISE = ("板块", "风格", "大盘", "中盘", "小盘", "股通", "融资融券", "标准普尔", "富时", "MSCI", "HS300", "深证", "上证", "中证", "深成", "机构重仓",
         "转债标的", "AH股", "券商金股", "中报", "年报", "季报", "预增", "预亏", "首亏", "高市净率", "低价", "昨日", "热股", "破净", "微盘")


def norm_op(t):
    if t.get("op") in ("1", "2"):
        return t["op"]
    if str(t.get("buy_sell")) in ("1", "3", "7"):
        return "1"
    if str(t.get("buy_sell")) in ("2", "4", "8"):
        return "2"
    return "1" if t.get("op") in ("252", "235") else "2" if t.get("op") == "256" else t.get("op")


def board(code, name):
    if "ST" in (name or ""):
        return "ST"
    if code.startswith(("51", "15", "56", "58", "16")):
        return "ETF/基金"
    if code.startswith(("11", "12")):
        return "可转债"
    if code.startswith(("688", "689")):
        return "科创板"
    if code.startswith(("300", "301")):
        return "创业板"
    if code.startswith(("8", "4", "92")):
        return "北交所"
    if code.startswith(("6", "0")):
        return "沪深主板"
    return "其他(港股等)"


def f10(code, fetch):
    f = F10 / f"{code}.json"
    try:
        j = json.loads(f.read_text(encoding="utf-8"))
        return j["boards"]
    except Exception:  # noqa: BLE001
        pass
    if not fetch or not code[:1].isdigit() or len(code) != 6:
        return []
    mkt = "SH" if code[0] in "69" else "BJ" if code[0] in "48" or code.startswith("92") else "SZ"
    time.sleep(1.5 + random.random() * 2.0)   # 随机间隔, 不打固定节拍
    try:
        req = urllib.request.Request(f"https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax?code={mkt}{code}",
                                     headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://emweb.securities.eastmoney.com/"})
        raw = urllib.request.urlopen(req, timeout=10).read()
        if raw[:2] == b"\x1f\x8b":
            import gzip
            raw = gzip.decompress(raw)
        j = json.loads(raw.decode("utf-8"))
        boards = [{"name": x["BOARD_NAME"], "precise": x.get("IS_PRECISE") == "1"} for x in j.get("ssbk") or []]
        F10.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"at": dt.datetime.utcnow().isoformat() + "Z", "code": code, "boards": boards}, ensure_ascii=False), encoding="utf-8")
        return boards
    except Exception:  # noqa: BLE001
        return []


def _arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    fetch = "--no-fetch" not in sys.argv
    asof = _arg("--asof")   # YYYY-MM-DD: 只用该日之前的数据(回放防后见之明); 缺省=全部
    out_json = Path(_arg("--out-json", ROOT / "scripts" / "tzzb" / "mentor_scope.json"))
    out_md = Path(_arg("--out-md", ROOT / "docs" / "research" / "mentor_scope_20261015.md"))
    ledgers = [l for l in json.loads((ROOT / "scripts" / "tzzb" / "tzzb_ledgers.json").read_text(encoding="utf-8"))
               if l.get("kind") != "neg" and l["ledger"] != "buchitudou0"]
    out = {}
    for l in ledgers:
        led = l["ledger"]; d = TZ / led
        legs, seen = [], set()
        for f in glob.glob(str(d / "position_change_p*.json")) + glob.glob(str(d / "change_bs_*.json")):
            try:
                lst = json.loads(Path(f).read_text(encoding="utf-8"))["ex_data"]["change_list"]
            except Exception:  # noqa: BLE001
                continue
            for t in lst:
                k = (t.get("trans_date"), t.get("stock_code"), t.get("trans_count"), t.get("trans_price"), t.get("op"))
                if k in seen or not t.get("trans_date") or (asof and t["trans_date"][:10] >= asof):
                    continue
                seen.add(k); legs.append({**t, "op_n": norm_op(t)})
        buys = [t for t in legs if t["op_n"] == "1" and t.get("stock_code") and not str(t["stock_code"]).startswith(("204", "1318"))]
        days = sorted({t["trans_date"][:10] for t in buys})[-120:]
        buys = [t for t in buys if t["trans_date"][:10] >= (days[0] if days else "9999")]
        bd = collections.Counter(board(t["stock_code"], t.get("stock_name")) for t in buys)
        names = collections.Counter((t["stock_code"], t.get("stock_name")) for t in buys)
        top = names.most_common(15)
        ind = collections.Counter(); con = collections.Counter()
        for (code, nm), n in top:
            bs = f10(code, fetch)
            tags = [b["name"] for b in bs[:3] if not any(x in b["name"] for x in NOISE)]
            if len(tags) >= 2:
                ind[tags[1]] += n
            for b in bs:
                if b.get("precise") and not any(x in b["name"] for x in NOISE):
                    con[b["name"]] += n
        hours = collections.Counter()
        for t in buys:
            hm = t["trans_date"][11:16]
            hours["竞价/开盘(≤09:35)" if hm <= "09:35" else "上午" if hm <= "11:30" else "午后(≤14:30)" if hm <= "14:30" else "尾盘(>14:30)"] += 1
        # 持仓天数/同时持股/单票最大仓位: day_positions
        try:
            dp = json.loads((d / "day_positions.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            dp = {}
        dks = sorted(k for k in dp if not asof or k < asof.replace("-", ""))[-120:]
        run, spans, nhold, mx, tot = {}, [], [], [], []
        for k in dks:
            lst = [x for x in (dp[k] or {}).get("list") or [] if float(x.get("position_percent") or 0) > 0 and not str(x.get("code", "")).startswith(("204", "1318"))]
            cur = {x["code"] for x in lst}
            for c in list(run):
                if c not in cur:
                    spans.append(run.pop(c))
            for c in cur:
                run[c] = run.get(c, 0) + 1
            nhold.append(len(cur)); tot.append(sum(float(x["position_percent"]) for x in lst))
            if lst:
                mx.append(max(float(x["position_percent"]) for x in lst))
        med = lambda a: sorted(a)[len(a) // 2] if a else None
        q75 = lambda a: sorted(a)[min(len(a) - 1, int(len(a) * 0.75))] if a else None   # 10/16 晚: 拿得住的上限(同口径 P75)
        out[led] = {"name": l.get("name"), "buys": len(buys), "days": len(days), "window": [days[0], days[-1]] if days else None,
                    "board": {k: round(v / max(1, len(buys)), 3) for k, v in bd.most_common()},
                    "top": [{"code": c, "name": n, "count": k} for (c, n), k in top],
                    "industry": ind.most_common(6), "concept": con.most_common(6),
                    "hold_days_med": med(spans), "hold_days_p75": q75(spans), "n_hold_med": med(nhold), "max_pos_med": round(med(mx), 2) if mx else None,
                    "total_pos_med": round(med(tot), 2) if tot else None, "buy_time": {k: round(v / max(1, len(buys)), 2) for k, v in hours.most_common()}}
        print(led, out[led]["buys"], "笔", out[led]["board"], out[led]["industry"][:3], "持仓天数中位", out[led]["hold_days_med"], "P75", out[led]["hold_days_p75"], flush=True)
    for k, nm in NO_LEDGER.items():   # 10/16 晚: 无统计导师占位(拟人审按 skill 键读 hold_days_med/p75)
        out.setdefault(k, {"name": nm, "kind": "no_stat", "hold_days_med": NO_STAT, "hold_days_p75": NO_STAT})
    if asof:
        out["_asof"] = {"kind": "meta", "asof": asof, "note": "只用该日之前的逐笔/收盘持仓"}
    out_json.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    L = ["# tzzb 导师能力圈逆推(10/15, 零 token, mentor_scope.py)" + (f" as-of {asof}" if asof else ""), ""]
    for led, v in out.items():
        if v.get("kind") in ("no_stat", "meta"):
            if v.get("kind") == "no_stat":
                L += [f"## {v['name']}({led})", f"- 持仓天数中位/P75: {NO_STAT}", ""]
            continue
        L += [f"## {v['name']}({led})", f"- 样本: 近 {v['days']} 个有买入的交易日 {v['window']}, 买入 {v['buys']} 笔",
              "- 板块: " + " / ".join(f"{k} {p:.0%}" for k, p in v["board"].items()),
              "- 行业 Top: " + "、".join(f"{k}({n})" for k, n in v["industry"]) + " | 精准概念 Top: " + "、".join(f"{k}({n})" for k, n in v["concept"]),
              "- 最常买: " + "、".join(f"{x['name']}×{x['count']}" for x in v["top"][:10]),
              f"- 持仓天数中位 {v['hold_days_med']} 天 / P75(拿得住的上限) {v['hold_days_p75']} 天 / 同时持股中位 {v['n_hold_med']} 只 / 单票最大仓位中位 {v['max_pos_med']} / 收盘总仓中位 {v['total_pos_med']}",
              "- 买入时段: " + " / ".join(f"{k} {p:.0%}" for k, p in v["buy_time"].items()), ""]
    out_md.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
