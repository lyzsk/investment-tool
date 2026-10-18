"""refresh_factors.py — 行情库第 2b 段: 每日除权检测 + 复权因子增量刷新(2026-10-12 建)
链路: Quartz MarketDailyHandler(15:35) collect_daily.mjs 之后 → 本脚本 → downloads/market/<交易日>/adjustment_factor.jsonl + DONE_factor
      → Java importDaily 按标的整体替换 adjustment_factor(脚本不直接写库)
检测: 股票当日快照 preClose(新浪=交易所除权参考价) ≠ 上一交易日 close(前一个快照目录, 无则历史回补文件末行) → 除权除息候选
刷新: 候选拉新浪 hfq.js 全量因子(与第 2 段同源同口径), **校验** F(当日)/F(上一交易日) ≈ 上一日 close / 当日 preClose(相对误差 <0.2%)
      → 通过才输出; 不通过(新浪当天未更新等)记 factor_pending.json, 之后每天重试, 最多 5 个交易日, 超期记 manifest.factorExpired 人工看
不做: ETF 除息(新浪 ETF 只给每份分红额, 非累积因子; 记 manifest.etfExDiv 留痕) / 北交所(第 2 段未回补)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/market/refresh_factors.py --date yyyy-MM-dd [--force]
出口: 0=完成(含 0 候选) 1=失败"""
import argparse
import datetime as dt
import json
import random
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
MARKET = ROOT / "downloads" / "market"
HISTORY = MARKET / "history"
PENDING = MARKET / "factor_pending.json"
MAX_PENDING_DAYS = 5
TOLERANCE = 0.002
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://finance.sina.com.cn"}


def log(*a):
    print(f"[{dt.datetime.now():%H:%M:%S}]", *a, flush=True)


def read_jsonl(path):
    return [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()]


def write_jsonl(path, recs):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


def prev_trade_day(day):
    """10/17 健壮性 M7: 交易日历上的上一交易日(scripts/lib/a_rules: 上证日线归档 + 节假日表兜底)"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
    import a_rules as AR   # noqa: PLC0415
    cal = set(AR.trade_days())
    last = max(cal) if cal else "0000-00-00"
    x = dt.date.fromisoformat(day) - dt.timedelta(days=1)
    for _ in range(30):
        s = x.isoformat()
        if s in cal or (s > last and AR._is_trade_day_fallback(s)):
            return s
        x -= dt.timedelta(days=1)
    return None


def prev_snapshot(day):
    """day 之前最近一个有 kline_day.jsonl 的快照目录; 10/17 M7: 必须正好是上一交易日, 否则返回 None(断档)"""
    dirs = sorted(p for p in MARKET.glob("20*-*-*") if p.name < day and (p / "kline_day.jsonl").exists())
    if not dirs:
        return None
    ptd = prev_trade_day(day)
    if ptd and dirs[-1].name != ptd:
        log(f"前一快照 {dirs[-1].name} ≠ 上一交易日 {ptd}(断档): 不用快照, 逐只用 history 末行且要求末行=上一交易日")
        return None
    return dirs[-1]


PTD = None          # 10/17 M7: 上一交易日(main 里赋值)
MAX_CANDS = 300     # 10/17 M7: 候选上限


def last_bar_from_history(sym, day):
    f = HISTORY / "kline_day" / f"{sym}.jsonl"
    if not f.exists():
        return None
    last = None
    for r in read_jsonl(f):
        if r["tradeDate"] < day:
            last = r
    return last


def sina_factors(sess, sym):
    r = sess.get(f"https://finance.sina.com.cn/realstock/company/{sym}/hfq.js", headers=UA, timeout=20)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    t = r.text
    m = re.search(r"\{.*\}", t[:t.find("/*")] if "/*" in t else t, re.S)
    if not m:
        return []
    data = json.loads(m.group(0)).get("data") or []
    if any("u" in x for x in data):
        return []
    return sorted((x["d"], float(x["f"])) for x in data)


def factor_at(factors, d):
    f = None
    for x, v in factors:
        if x <= d:
            f = v
    return f


def first_bar_date(sym, fallback):
    f = HISTORY / "kline_day" / f"{sym}.jsonl"
    if f.exists():
        with f.open(encoding="utf-8") as fh:
            line = fh.readline()
            if line.strip():
                return json.loads(line)["tradeDate"]
    return fallback


def to_records(sym, fraw, day):
    """与 backfill_history.build_symbol 同口径: 首行=首根 K 线日的基准因子, 之后只在变化日出行, 不含 day 之后的"""
    first = first_bar_date(sym, fraw[0][0] if fraw[0][0] > "1900-01-01" else day)
    recs = []
    base = [f for d, f in fraw if d <= first]
    recs.append({"symbol": sym, "exDate": first, "factor": base[-1] if base else 1.0, "source": "sina"})
    for d, f in fraw:
        if first < d <= day and f != recs[-1]["factor"]:
            recs.append({"symbol": sym, "exDate": d, "factor": f, "source": "sina"})
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    day = a.date
    out = MARKET / day
    if (out / "DONE_factor").exists() and not a.force:
        log(f"{day} 已有 DONE_factor, 跳过")
        return 0
    if not (out / "kline_day.jsonl").exists():
        log(f"{day} 无 kline_day.jsonl, 先跑 collect_daily")
        return 1
    secs = {r["symbol"]: r for r in read_jsonl(out / "security_master.jsonl")}
    today = {r["symbol"]: r for r in read_jsonl(out / "kline_day.jsonl")}
    prev_dir = prev_snapshot(day)
    global PTD
    PTD = prev_trade_day(day)
    prev = {r["symbol"]: r for r in read_jsonl(prev_dir / "kline_day.jsonl")} if prev_dir else {}
    pending = json.loads(PENDING.read_text("utf-8")) if PENDING.exists() else {}

    cands, etf = {}, []
    for sym, k in today.items():
        sec = secs.get(sym) or {}
        if sec.get("exchange") == "BJ" or sec.get("secType") not in ("STOCK", "ETF") or not k.get("preClose"):
            continue
        p = prev.get(sym) or last_bar_from_history(sym, day)
        if p and not prev and PTD and p.get("tradeDate") != PTD:
            continue   # 10/17 M7: history 末行不是上一交易日(本票停牌或 history 也断档), 不拿它比前收
        if not p or abs(k["preClose"] - p["close"]) <= 0.0051:
            continue
        if sec["secType"] == "ETF":
            etf.append(sym)
            continue
        cands[sym] = {"exDate": day, "prevDate": p["tradeDate"], "prevClose": p["close"], "preClose": k["preClose"], "first": day}
    for sym, info in pending.items():
        cands.setdefault(sym, info)
    log(f"{day} 除权候选 {len(cands)} 只(今日新增 {len(cands) - len(pending)} / 待重试 {len(pending)}), ETF 除息 {len(etf)} 只(不出因子)")
    if len(cands) > MAX_CANDS:   # 10/17 M7: 正常每天几十只; 爆量=快照断档/前收口径坏, 按 2~3s/只会打上千次新浪(456 封禁连坐 collect_daily)
        log(f"候选 {len(cands)} > {MAX_CANDS}: 疑快照断档或前收口径异常, 停下不请求、不落 DONE_factor(人工核对后 --force 重跑)")
        return 3

    sess = requests.Session()
    recs, ok, new_pending, expired, failed = [], [], {}, [], []
    for sym, info in cands.items():
        time.sleep(random.uniform(2.0, 3.0))   # 10/17 M7: 原 0.4~0.8s ≈1.7 次/秒, 超项目批量 ≤0.5 次/秒
        try:
            fraw = sina_factors(sess, sym)
        except Exception as e:   # noqa: BLE001  网络失败: 留待明日重试
            fraw = None
            failed.append(f"{sym}: {e}")
        f_ex = factor_at(fraw, info["exDate"]) if fraw else None
        f_prev = factor_at(fraw, info["prevDate"]) if fraw else None
        want = info["prevClose"] / info["preClose"]
        if f_ex and f_prev and abs((f_ex / f_prev) / want - 1) < TOLERANCE:
            recs.extend(to_records(sym, fraw, day))
            ok.append(sym)
            continue
        age = len([d for d in MARKET.glob("20*-*-*") if info["first"] < d.name <= day and (d / "kline_day.jsonl").exists()])
        if age >= MAX_PENDING_DAYS:
            expired.append({"symbol": sym, **info, "sinaRatio": (f_ex / f_prev) if f_ex and f_prev else None, "wantRatio": want})
        else:
            new_pending[sym] = info
    write_jsonl(out / "adjustment_factor.jsonl", recs)
    PENDING.write_text(json.dumps(new_pending, ensure_ascii=False, indent=1), "utf-8")
    mf_path = out / "manifest.json"
    mf = json.loads(mf_path.read_text("utf-8")) if mf_path.exists() else {}
    mf["factor"] = {"at": dt.datetime.now().isoformat(), "prevSnapshot": prev_dir.name if prev_dir else None,
                    "candidates": len(cands), "refreshed": ok, "pending": sorted(new_pending), "expired": expired,
                    "etfExDiv": etf, "errors": failed[:50]}
    mf_path.write_text(json.dumps(mf, ensure_ascii=False, indent=1), "utf-8")
    (out / "DONE_factor").write_text(dt.datetime.now().isoformat())
    log(f"刷新 {len(ok)} 只 / 待重试 {len(new_pending)} / 超期 {len(expired)} / 网络失败 {len(failed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
