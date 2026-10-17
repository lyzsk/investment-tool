"""collect_auction.py — 行情库第 5 段: 集合竞价过程采集(2026-10-12 建, 字段口径待 10/12 首个竞价时段实测核对)
链路: Quartz MarketAuctionHandler(09:14 OPEN / 14:56 CLOSE) → 本脚本(等到竞价开始, 轮询到结束) → downloads/market/<交易日>/
      call_auction_<phase>.jsonl + call_auction_<phase>_raw.jsonl(原始报文留档, 口径争议可回放) + DONE_auction_<phase> → Java importAuction
标的: 关注集(最近一个交易日 watchlist_info.jsonl, 约 300 只) + 上证/深成/创业板指; 竞价不可事后补, 只能现场采
源: 新浪 hq.sinajs.cn 批量实时报文(每轮 1~2 个请求), OPEN 09:15:00~09:25:40 每 15s / CLOSE 14:57:00~15:00:40 每 10s
口径(新浪竞价时段, 待实测): 买一价=卖一价=虚拟匹配价, 买一量=匹配量(股), 买二量>0 且买二价=0 → 买方未匹配量(+), 卖二量>0 且卖二价=0 → 卖方未匹配量(-)
      matched_amount = 匹配价 × 匹配量(源不给竞价金额, 推算); 价=0 的轮次(9:15 前/无撮合)不出行
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/market/collect_auction.py --phase OPEN|CLOSE [--date yyyy-MM-dd] [--now](不等时刻, 测试用)
出口: 0=完成 1=失败 2=非交易时段(--now 未给且已过结束时刻)"""
import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
MARKET = ROOT / "downloads" / "market"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://finance.sina.com.cn"}
PHASES = {"OPEN": (dt.time(9, 15, 0), dt.time(9, 25, 40), 15), "CLOSE": (dt.time(14, 57, 0), dt.time(15, 0, 40), 10)}
INDEXES = ["sh000001", "sz399001", "sz399006"]
BATCH = 300


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


def targets(day):
    dirs = sorted(p for p in MARKET.glob("20*-*-*") if p.name <= day and (p / "watchlist_info.jsonl").exists())
    syms = [r["symbol"] for r in read_jsonl(dirs[-1] / "watchlist_info.jsonl")] if dirs else []
    syms = [s for s in syms if s[:2] in ("sh", "sz")]   # 北交所新浪竞价报文另一格式, 暂不收
    return list(dict.fromkeys(INDEXES + syms)), (dirs[-1].name if dirs else None)


def poll(sess, syms):
    out = {}
    for i in range(0, len(syms), BATCH):
        r = sess.get("https://hq.sinajs.cn/list=" + ",".join(syms[i:i + BATCH]), headers=UA, timeout=10)
        r.raise_for_status()
        for line in r.content.decode("gbk", errors="replace").splitlines():
            if "=\"" not in line:
                continue
            sym = line.split("=")[0].rsplit("_", 1)[-1]
            body = line.split("=\"", 1)[1].rstrip("\";")
            if body:
                out[sym] = body.split(",")
    return out


MATCH_AT = {"OPEN": "09:25:00", "CLOSE": "15:00:00"}


def to_row(sym, f, day, phase, base_vol=None):
    """新浪 A 股报文: 0名 1今开 2昨收 3现价 4最高 5最低 6买一价 7卖一价 8量(股) 9额 10买一量 11买一价 12买二量 13买二价 ...
    20卖一量 21卖一价 22卖二量 23卖二价 ... 30日期 31时间
    竞价中(10/12 实测核对): 买一价=卖一价=虚拟匹配价, 买一量=虚拟匹配量, 买二/卖二价为 0 时其量=买方(+)/卖方(-)未匹配量
    撮合后(OPEN ≥09:25:00 / CLOSE ≥15:00:00)报文已是连续竞价盘口, 改取 现价=撮合价, 成交量: OPEN=当日累计量, CLOSE=累计量-收盘竞价前累计量(base_vol)
    (10/12 修: 原先撮合后一行误把盘口买一 41.09×900 当竞价, 实际开盘 41.10/224400 股)"""
    if len(f) < 32 or f[30] != day:
        return None
    if f[31] >= MATCH_AT[phase]:
        price, total = float(f[3] or 0), int(float(f[8] or 0))
        if price <= 0:
            return None
        vol = total if phase == "OPEN" else (total - base_vol if base_vol is not None else None)
        return {"symbol": sym, "tradeDate": day, "phase": phase, "snapTime": f"{f[30]}T{f[31]}", "price": price,
                "matchedVolume": vol, "matchedAmount": round(price * vol, 2) if vol is not None else None,
                "unmatchedVolume": None, "source": "sina"}
    price = float(f[11] or 0) or float(f[21] or 0) or float(f[3] or 0)
    if price <= 0:
        return None
    vol = int(float(f[10] or 0))
    unmatched = None
    if float(f[13] or 0) == 0 and float(f[12] or 0) > 0:
        unmatched = int(float(f[12]))
    elif float(f[23] or 0) == 0 and float(f[22] or 0) > 0:
        unmatched = -int(float(f[22]))
    return {"symbol": sym, "tradeDate": day, "phase": phase, "snapTime": f"{f[30]}T{f[31]}", "price": price,
            "matchedVolume": vol, "matchedAmount": round(price * vol, 2), "unmatchedVolume": unmatched, "source": "sina"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=list(PHASES))
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--now", action="store_true", help="不等竞价时刻立即轮询 3 轮(测试报文格式用)")
    ap.add_argument("--rebuild", action="store_true", help="不轮询, 从已存的 call_auction_<phase>_raw.jsonl 按当前口径重算 jsonl(口径修正后补救用)")
    a = ap.parse_args()
    day, phase = a.date, a.phase
    start, end, gap = PHASES[phase]
    out = MARKET / day
    out.mkdir(parents=True, exist_ok=True)
    if a.rebuild:
        raw_f = out / f"call_auction_{phase.lower()}_raw.jsonl"
        rows, base = {}, {}
        for r in read_jsonl(raw_f):
            f = r["fields"]
            base.setdefault(r["symbol"], int(float(f[8] or 0)) if len(f) > 8 else None)
            row = to_row(r["symbol"], f, day, phase, base.get(r["symbol"]))
            if row:
                rows[(r["symbol"], row["snapTime"])] = row
        recs = sorted(rows.values(), key=lambda x: (x["symbol"], x["snapTime"]))
        write_jsonl(out / f"call_auction_{phase.lower()}.jsonl", recs)
        log(f"重算 {phase}: {len(recs)} 行")
        return 0
    syms, wl_from = targets(day)
    if not syms:
        log("无关注集")
        return 1
    log(f"{phase} 竞价采集 {day}: {len(syms)} 只(关注集取自 {wl_from})")
    if not a.now:
        if dt.datetime.now().time() >= end:
            log(f"已过 {end}, 不采")
            return 2
        while dt.datetime.now().time() < start:
            time.sleep(min(5.0, max(0.5, (dt.datetime.combine(dt.date.today(), start) - dt.datetime.now()).total_seconds())))
    sess = requests.Session()
    rows, raw, rounds, errors, base = {}, [], 0, 0, {}
    while True:
        t0 = time.time()
        try:
            snap = poll(sess, syms)
            rounds += 1
            at = dt.datetime.now().isoformat(timespec="seconds")
            for sym, f in snap.items():
                raw.append({"at": at, "symbol": sym, "fields": f})
                base.setdefault(sym, int(float(f[8] or 0)) if len(f) > 8 else None)   # 首轮累计量=收盘竞价前的量
                row = to_row(sym, f, day, phase, base.get(sym))
                if row:
                    rows[(sym, row["snapTime"])] = row   # 同一报文时刻重复轮询去重
        except Exception as e:   # noqa: BLE001  单轮失败继续下一轮(竞价只有 10 分钟, 不能整段放弃)
            errors += 1
            log(f"轮询失败: {e}")
        if (a.now and rounds >= 3) or (not a.now and dt.datetime.now().time() >= end):
            break
        time.sleep(max(0.0, gap - (time.time() - t0)))
    recs = sorted(rows.values(), key=lambda r: (r["symbol"], r["snapTime"]))
    write_jsonl(out / f"call_auction_{phase.lower()}.jsonl", recs)
    write_jsonl(out / f"call_auction_{phase.lower()}_raw.jsonl", raw)
    mf_path = out / "manifest.json"
    mf = json.loads(mf_path.read_text("utf-8")) if mf_path.exists() else {}
    covered = len({r["symbol"] for r in recs})
    coverage = round(covered / len(syms), 4) if syms else None   # 10/17 健壮性 M20: 原先只要有 1 行就写 DONE
    mf[f"auction_{phase.lower()}"] = {"at": dt.datetime.now().isoformat(), "symbols": len(syms), "watchlistFrom": wl_from,
                                      "rounds": rounds, "errors": errors, "rows": len(recs), "test": a.now, "covered": covered, "coverage": coverage}
    if not a.now:
        pf = out / f"PARTIAL_auction_{phase.lower()}"
        if coverage is not None and coverage < 0.9:
            pf.write_text(json.dumps({"covered": covered, "symbols": len(syms), "coverage": coverage}), encoding="utf-8")
            log(f"覆盖率 {coverage:.1%} < 90%: 写 {pf.name}")
        else:
            pf.unlink(missing_ok=True)
    mf_path.write_text(json.dumps(mf, ensure_ascii=False, indent=1), "utf-8")
    if not a.now and recs:
        (out / f"DONE_auction_{phase.lower()}").write_text(dt.datetime.now().isoformat())
    log(f"完成: {rounds} 轮 / {len(recs)} 行 / 失败 {errors} 轮")
    return 0 if recs or a.now else 1


if __name__ == "__main__":
    sys.exit(main())
