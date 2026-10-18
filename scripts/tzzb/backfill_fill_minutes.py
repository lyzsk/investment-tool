# -*- coding: utf-8 -*-
"""backfill_fill_minutes.py — 导师真人成交"当时"的盘中状态(10/16 晚用户指出: 日内位置用全天高低=后见之明, 子链是实时决策, 要还原成交那一刻能看到的)
1) 补分钟线: 对 skills/<导师>-skill/persona/cases_auto.jsonl 里每个(交易日, 股票), 从通达信取当日逐笔→分钟 bar(口径同 scripts/market/collect_minute.py,
   末笔≈日线收盘校验, 不过=重连重取, 仍不过=记缺失), 缓存到 downloads/tzzb/_minutes/<日>.jsonl(可断点续跑, 已取过的不重取)
   日线校验/昨收来自行情库 kline_day(只读)。转债/港股/北交所 10/09 前等无日线的跳过
2) 实时特征: 对每笔成交, 只用成交分钟之前(含该分钟)的 bar 算: 距开盘分钟数、相对昨收/开盘、在"截至当时"的日内区间位置(0=当时最低 1=当时最高)、
   相对截至当时均价、前 5 分钟涨跌(追涨/回落)、截至当时是否触过涨停/是否炸板、距涨停价 → skills/<导师>-skill/persona/fills_rt.jsonl
3) 汇总: 每位导师 × 打法 的实时挂价/位置分布 → 打印 + scripts/tzzb/model_out/reports/fills_realtime_20261016.md
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/backfill_fill_minutes.py [--fetch] [--features] [--report] [--ledger X] [--max-pairs N]
   (三个动作都不给=全做; 通达信请求带 0.15~0.35s 随机间隔)
"""
import argparse, json, random, sys, time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "market"))
sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
import collect_minute as cm   # noqa: E402
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import a_rules as AR   # noqa: E402  10/16 统一交易规则模块(涨跌停/价位按日期)

CACHE = ROOT / "downloads" / "tzzb" / "_minutes"
CACHE5 = ROOT / "downloads" / "tzzb" / "_minutes_5m"   # 10/18: 只有 5 分钟线的(摘牌 *ST baostock / 退市转债新浪尾窗), 1 分钟缺时兜底
SKILLS = ROOT / "skills"


def cases(ledger=None):
    out = {}
    for f in sorted(SKILLS.glob("*-skill/persona/cases_auto.jsonl")):
        sk = f.parts[-3].replace("-skill", "")
        if ledger and sk != ledger:
            continue
        out[sk] = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    return out


def daily_map(pairs):
    from kline_db import db
    conn = db()
    try:
        cur = conn.cursor()
        ds = sorted({d for d, _ in pairs})
        cur.execute("select symbol, trade_date, cast(open as double), cast(high as double), cast(low as double), cast(close as double), cast(pre_close as double) "
                    "from kline_day where trade_date >= %s and trade_date <= %s", (ds[0], ds[-1]))
        m = {}
        for sym, td, o, h, l, c, pc in cur.fetchall():
            m[(str(td)[:10], sym[-6:])] = {"symbol": sym, "open": o, "high": h, "low": l, "close": c, "preClose": pc}
        return m
    finally:
        conn.close()


def cache_load(day):
    f = CACHE / f"{day}.jsonl"
    bars, miss = defaultdict(list), set()
    if f.exists():
        for l in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(l)
            if r.get("miss"):
                miss.add(r["code"])
            else:
                bars[r["symbol"][2:]].append(r)   # 10/16 晚: 港股 hk01952 → 01952(原 [-6:] 截成 k01952)
    return bars, miss


def fetch(C, max_pairs=None):
    pairs = {(c["date"], c["code"]) for cs in C.values() for c in cs
             if (c.get("feat") or {}).get("asset") not in ("CB", "HK") and len(str(c.get("code", ""))) == 6}
    dm = daily_map(pairs)
    todo = defaultdict(list)
    for d, code in sorted(pairs):
        if (d, code) in dm:
            todo[d].append(code)
    CACHE.mkdir(parents=True, exist_ok=True)
    api, n_req, n_ok, n_miss, t0 = None, 0, 0, 0, time.time()
    try:
        for d in sorted(todo):
            have, miss = cache_load(d)
            codes = [c for c in todo[d] if c not in have and c not in miss]
            if not codes:
                continue
            if api is None:
                api = cm.connect(int(d.replace("-", "")))
            with (CACHE / f"{d}.jsonl").open("a", encoding="utf-8") as fh:
                for code in codes:
                    if max_pairs is not None and n_req >= max_pairs:
                        raise StopIteration
                    k = dm[(d, code)]
                    sym, ymd = k["symbol"], int(d.replace("-", ""))
                    unit = 100
                    b = []
                    try:
                        for _ in range(2):
                            ticks = cm.all_ticks(api, sym, ymd)
                            sc = cm.price_scale(ticks, k["close"]) if ticks else 1.0
                            if not ticks or cm.ticks_ok(ticks, k, sc):
                                break
                            api.disconnect(); api = cm.connect(ymd)
                        else:
                            ticks = []
                        b = cm.bars_from_ticks(sym, d, ticks, unit, k["preClose"], sc) if ticks else []
                    except Exception as e:   # noqa: BLE001
                        print(f"失败 {d} {code}: {e}")
                        try:
                            api.disconnect()
                        except Exception:   # noqa: BLE001
                            pass
                        api = cm.connect(ymd)
                    n_req += 1
                    if b:
                        n_ok += 1
                        for r in b:
                            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    else:
                        n_miss += 1
                        fh.write(json.dumps({"code": code, "miss": True}) + "\n")
                    time.sleep(random.uniform(0.15, 0.35))
                    if n_req % 200 == 0:
                        print(f"[{time.strftime('%H:%M:%S')}] 进度 {n_req} 对, 成功 {n_ok} 缺 {n_miss}, {time.time() - t0:.0f}s", flush=True)
    except StopIteration:
        pass
    finally:
        if api is not None:
            try:
                api.disconnect()
            except Exception:   # noqa: BLE001
                pass
    print(f"补分钟线完成: 本轮请求 {n_req} 对, 成功 {n_ok}, 缺 {n_miss}, 用时 {time.time() - t0:.0f}s")


_EXTRA = {}


def cache5_load(day):
    f = CACHE5 / f"{day}.jsonl"
    bars = defaultdict(list)
    if f.exists():
        for l in f.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                bars[r["symbol"][2:]].append(r)
    return bars


def extra_prev_close(sym, d):
    if sym not in _EXTRA:
        try:
            _EXTRA[sym] = {b["date"]: b for b in json.loads((ROOT / "downloads" / "tzzb" / "_daily_extra" / f"{sym}.json").read_text(encoding="utf-8"))["bars"]}
        except (OSError, ValueError, KeyError):
            _EXTRA[sym] = {}
    b = _EXTRA[sym].get(d) or {}
    return b.get("preClose")


def limit_pct(code, name="", date=None):
    """涨幅限制(小数)。10/16 晚改走统一规则模块 scripts/lib/a_rules.py(按日期: 主板 ST 2026-07-06 前 5%、起 10%; 新股前 5 日/北交所首日无限制;
    转债首日 57.3%; 科创/创业 ETF 20%)。无涨跌幅限制(港股/新股)返回 9.99 哨兵(兼容 order_inference 的 pc*(1+x) 写法)。date=None=今天的规则"""
    p = AR.limit_pct(code, date, name=name or None)
    return 9.99 if p is None else p


def limit_up_price(code, date, pre_close, name=""):
    """涨停价(按最小价位四舍五入: 股票 0.01 / 转债·ETF 0.001); 无限制 → None"""
    return AR.limit_prices(code, date, pre_close, name=name or None)[0]


def rt_feat(case, bars, pre_close, gran="1m"):
    """gran=5m(10/18): bar 标签=该 5 分钟末, 只用标签 ≤ 成交分钟标签的 = 已走完的 bar(不偷看); mom5 = 往前 1 根; 结果带 gran 标记"""
    t = (case.get("time") or "")[:5]
    lab = (t if len(str(case.get("code", ""))) == 5 else cm.label_of(t)) if t else None   # 港股: 分钟线标签=实际时刻(交易到 16:00, 无午休 11:30 规则)
    if not lab or not bars or not pre_close:
        return None
    seen = [b for b in bars if b["barTime"][11:16] <= lab]
    if not seen:
        return None
    px = float(case.get("vwap") or seen[-1]["close"])
    o = seen[0]["open"]
    hi, lo = max(b["high"] for b in seen), min(b["low"] for b in seen)
    vol = sum(b.get("volume") or 0 for b in seen)
    amt = sum((b.get("amount") or 0) for b in seen)
    avg = amt / vol if vol and amt else None
    up = limit_up_price(case["code"], case.get("date"), pre_close, case.get("name"))   # 10/16: 按成交日规则(原无日期: ST 一律 5%、转债/ETF 按 2 位小数)
    half = AR.tick(case["code"]) / 2
    prev5 = (seen[-2]["close"] if len(seen) >= 2 else o) if gran == "5m" else (seen[-6]["close"] if len(seen) >= 6 else o)
    h, m = map(int, lab.split(":"))
    mins = (h * 60 + m) - (9 * 60 + 30) - (90 if h >= 13 else 0)
    f = {"lab": lab, "mins_from_open": max(0, mins), "vs_prev_close": round(px / pre_close - 1, 4), "vs_open": round(px / o - 1, 4) if o else None,
         "pos_so_far": round((px - lo) / (hi - lo), 3) if hi > lo else 0.5, "vs_avg_so_far": round(px / avg - 1, 4) if avg else None,
         "mom5": round(seen[-1]["close"] / prev5 - 1, 4) if prev5 else None}
    if gran != "1m":
        f["gran"] = gran
    if up is None:   # 无涨跌幅限制(港股/新股前 5 日/北交所首日等)
        f.update({"touched_limit": False, "broke_limit": False, "at_limit": False, "to_limit": None})
        return f
    touched = hi >= up - half
    f.update({"touched_limit": touched, "broke_limit": bool(touched and seen[-1]["close"] < up - half), "at_limit": px >= up - half,
              "to_limit": round(up / px - 1, 4)})
    return f


def features(C):
    dm_cache, dm5_cache = {}, {}
    for sk, cs in C.items():
        out = []
        for c in cs:
            d, code = c.get("date"), str(c.get("code", ""))
            if d not in dm_cache:
                dm_cache[d] = cache_load(d)[0]
            bars = sorted(dm_cache[d].get(code, []), key=lambda b: b["barTime"])
            gran = "1m"
            if not bars:   # 10/18: 1 分钟缺 → 5 分钟兜底(_minutes_5m)
                if d not in dm5_cache:
                    dm5_cache[d] = cache5_load(d)
                bars = sorted(dm5_cache[d].get(code, []), key=lambda b: b["barTime"])
                gran = "5m"
            pc = None
            if bars:
                pct = (c.get("feat") or {}).get("buy_pct")
                pc = (float(c["vwap"]) / (1 + pct)) if (pct is not None and c.get("vwap")) else None
                if pc is None:   # 10/16 晚: 北交所早期/LOF/港股/转债无 buy_pct → 用 _daily_extra 日线的昨收
                    pc = extra_prev_close(bars[0]["symbol"], d)
            f = rt_feat(c, bars, pc, gran) if bars else None
            out.append({"date": d, "time": c.get("time"), "code": code, "name": c.get("name"), "side": c.get("side"), "play": c.get("play"), "rt": f})
        p = SKILLS / f"{sk}-skill" / "persona" / "fills_rt.jsonl"
        p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n", encoding="utf-8")
        ok = sum(1 for x in out if x["rt"])
        print(f"{sk}: 实时特征 {ok}/{len(out)}")


def report():
    q = lambda a, p: sorted(a)[min(len(a) - 1, int(len(a) * p))] if a else None
    L = ["# 导师真人成交\"当时\"的盘中状态（10/16 晚）", "",
         "> 只用成交那一分钟之前的分钟线算（不看全天高低，防后见之明）；`pos_so_far`=在截至当时的日内区间位置（0=当时最低 1=当时最高）；mom5=成交前 5 分钟涨跌。",
         "> 数据：通达信历史逐笔→分钟线（`downloads/tzzb/_minutes/`），口径同 collect_minute.py；港股=通达信扩展行情 1 分钟；退市转债=新浪分钟 K 尾窗（退市前约 4 日 1 分钟 / 约 21 日 5 分钟）；"
         "只有 5 分钟线的（摘牌 *ST、退市转债较早的日子）rt 带 gran=5m，只用已走完的 5 分钟 bar。脚本 `scripts/tzzb/backfill_fill_minutes.py`。", "",
         "| 导师 | 买入笔(有分钟线) | 距开盘分钟 中位 | 相对昨收 中位 | 当时位置 P25/中/P75 | 前5分钟涨跌 中位 | 买在涨停价 | 买前已触板 |", "|---|---|---|---|---|---|---|---|"]
    by_play = []
    for f in sorted(SKILLS.glob("*-skill/persona/fills_rt.jsonl")):
        sk = f.parts[-3].replace("-skill", "")
        xs = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        B = [x for x in xs if x["side"] == "买" and x["rt"]]
        if len(B) < 10:
            continue
        r = [x["rt"] for x in B]
        pos = [v["pos_so_far"] for v in r]
        L.append(f"| {sk} | {len(B)} | {q([v['mins_from_open'] for v in r], .5)} | {q([v['vs_prev_close'] for v in r], .5):+.1%} | "
                 f"{q(pos, .25):.2f}/{q(pos, .5):.2f}/{q(pos, .75):.2f} | {q([v['mom5'] for v in r if v['mom5'] is not None], .5):+.2%} | "
                 f"{sum(v['at_limit'] for v in r) / len(r):.0%} | {sum(v['touched_limit'] for v in r) / len(r):.0%} |")
        g = defaultdict(list)
        for x in B:
            g[x["play"]].append(x["rt"])
        for play, rr in sorted(g.items(), key=lambda kv: -len(kv[1])):
            if len(rr) >= 8:
                pp = [v["pos_so_far"] for v in rr]
                by_play.append(f"| {sk} | {play} | {len(rr)} | {q([v['vs_prev_close'] for v in rr], .25):+.1%} / {q([v['vs_prev_close'] for v in rr], .5):+.1%} / {q([v['vs_prev_close'] for v in rr], .75):+.1%} | "
                               f"{q(pp, .5):.2f} | {q([v['mins_from_open'] for v in rr], .5)} |")
    L += ["", "## 按打法（≥8 笔）：挂价规则的直接输入", "", "| 导师 | 打法 | 笔数 | 相对昨收 P25/中/P75 | 当时位置 中位 | 距开盘分钟 中位 |", "|---|---|---|---|---|---|"] + by_play
    L += ["", "## 局限", "- 只有成交没有挂单：挂了没成交的看不到，低吸型的挂价深度可能偏浅",
          "- 逐笔时间只到分钟、成交时刻到秒 → 同一分钟内的先后无法区分；成交价用当笔成交均价",
          "- 退市转债离退市日超过约 21 个交易日的、新浪窗口外的，没有分钟线；5 分钟口径的成交（gran=5m）当时位置/前 5 分钟涨跌更粗"]
    out = ROOT / "scripts" / "tzzb" / "model_out" / "reports" / "fills_realtime_20261016.md"   # 10/18 从 docs/research 挪来(脚本产物和脚本放一起)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:8 + 20]))
    print(f"报告: {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--features", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--ledger")
    ap.add_argument("--max-pairs", type=int)
    a = ap.parse_args()
    allp = not (a.fetch or a.features or a.report)
    C = cases(a.ledger)
    if a.fetch or allp:
        fetch(C, a.max_pairs)
    if a.features or allp:
        features(C)
    if a.report or allp:
        report()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
