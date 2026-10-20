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
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import a_rules as AR   # noqa: E402  代码 → 带市场前缀 symbol

MARKET = ROOT / "downloads" / "market"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://finance.sina.com.cn"}
PHASES = {"OPEN": (dt.time(9, 15, 0), dt.time(9, 25, 40), 15), "CLOSE": (dt.time(14, 57, 0), dt.time(15, 0, 40), 10)}
# 10/18: 阶段交界加密到 5 秒(9:20 可撤→不可撤、9:25 撮合), 保证两个关键时刻各有快照; 10/12~10/16 实测新浪 5 天 × 44 轮 × 1~3 批零失败
DENSE = {"OPEN": [(dt.time(9, 19, 40), dt.time(9, 20, 10)), (dt.time(9, 24, 45), dt.time(9, 25, 40))], "CLOSE": [(dt.time(14, 59, 45), dt.time(15, 0, 40))]}
DENSE_GAP = 5
INDEXES = ["sh000001", "sz399001", "sz399006"]
BATCH = 300
MAX_SYMS = 1500   # 最多 5 批/轮


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
    """采集名单(10/18 扩: 竞价过程进共享实时层, paper 全链 + 用户实盘共用) = 前一日关注集 ∪ 用户盯盘名单 ∪ paper 各账本持仓/挂单
    ∪ 当日导师候选池(pools/<日>.json) ∪ 当日各链 04 候选快照(cand_snap, 0915 链跑到哪算哪, 每分钟重扫); 北交所新浪竞价报文另一格式, 暂不收"""
    dirs = sorted(p for p in MARKET.glob("20*-*-*") if p.name <= day and (p / "watchlist_info.jsonl").exists())
    syms = [r["symbol"] for r in read_jsonl(dirs[-1] / "watchlist_info.jsonl")] if dirs else []
    codes = []
    try:
        wl = ROOT / "scripts" / "dfcf" / "snapshots" / "live" / "watchlist.txt"
        codes += [c for c in wl.read_text("utf-8").replace(",", " ").split() if len(c) == 6 and c.isdigit()] if wl.exists() else []
    except OSError:
        pass
    for f in (ROOT / "scripts" / "dfcf" / "paper" / "books").glob("*.json"):
        try:
            b = json.loads(f.read_text("utf-8"))
            codes += list((b.get("positions") or {}).keys()) + [str(o.get("code")) for o in b.get("orders") or [] if o.get("status") == "open"]
        except (OSError, ValueError):
            continue
    try:
        pl = json.loads((ROOT / "scripts" / "tzzb" / "pools" / f"{day}.json").read_text("utf-8"))
        codes += [str(x.get("code")) for m in (pl.get("mentors") or {}).values() for x in (m.get("pool") or [])]
    except (OSError, ValueError, AttributeError):
        pass
    for f in (ROOT / "results").glob(f"*_chain/live-{day.replace('-', '')}/cand_snap.json"):
        try:
            codes += [str(s.get("code")) for s in json.loads(f.read_text("utf-8")).get("snaps") or []]
        except (OSError, ValueError, AttributeError):
            continue
    syms += [AR.symbol(c) for c in dict.fromkeys(codes) if len(c) == 6 and c.isdigit()]
    syms = [s for s in syms if s[:2] in ("sh", "sz")]
    # 10/19(TODO 二-5 土豆竞价T, 用户令提前做): 全市场可转债都进竞价采集 —— 土豆 103 天竞价 09:25 买、09:30 卖, 他最可能看的信号是
    #   全市场转债 09:25 的竞价额排名; 原名单只有关注集里的十几只转债。转债放在关注集之后(超 MAX_SYMS 时先截转债, 不挤掉正股)
    cb = []
    try:
        sm = sorted(p for p in MARKET.glob("20*-*-*") if p.name <= day and (p / "security_master.jsonl").exists())
        cb = [r["symbol"] for r in read_jsonl(sm[-1] / "security_master.jsonl") if r.get("secType") == "CB" and str(r.get("symbol", ""))[:2] in ("sh", "sz")] if sm else []
    except (OSError, ValueError, KeyError):
        cb = []
    return list(dict.fromkeys(INDEXES + syms + cb))[:MAX_SYMS], (dirs[-1].name if dirs else None)


def prev_volumes(day):
    """前一交易日全市场日线量(股) → 竞价量比; 拿不到=空"""
    dirs = sorted(p for p in MARKET.glob("20*-*-*") if p.name < day and (p / "kline_day.jsonl").exists())
    if not dirs:
        return {}
    return {r["symbol"]: r.get("volume") for r in read_jsonl(dirs[-1] / "kline_day.jsonl")}


def summarize(rows, meta, prev_vol, phase):
    """10/18: 按票汇总竞价过程 → auction_live_<phase>.json(每轮原子重写; facts.mjs / live_watch.mjs 读, 渲染见 scripts/lib/auction.mjs)
    OPEN 分三段: 09:15~09:20 可撤单(虚报多, 只看区间) / 09:20~09:25 不可撤(真实意图) / 09:25 撮合结果(开盘价+竞价量)"""
    split, fin_at = ("09:20:00", "09:25:00") if phase == "OPEN" else ("15:00:00", "15:00:00")
    by = {}
    for r in rows.values():
        by.setdefault(r["symbol"], []).append(r)
    out = {}
    for sym, rs in by.items():
        rs.sort(key=lambda r: r["snapTime"])
        pc = (meta.get(sym) or {}).get("prev")
        if not pc:
            continue
        pct = lambda p: round((p / pc - 1) * 100, 2)
        pt = lambda r: {"t": r["snapTime"][11:19], "px": r["price"], "pct": pct(r["price"]), "vol": r["matchedVolume"], "unm": r["unmatchedVolume"]} if r else None
        p1 = [r for r in rs if r["snapTime"][11:19] < split]
        p2 = [r for r in rs if split <= r["snapTime"][11:19] < fin_at]
        fin = [r for r in rs if r["snapTime"][11:19] >= fin_at]
        s = {"name": (meta.get(sym) or {}).get("name"), "prev": pc,
             "p1": pt(p1[-1] if p1 else None), "p1_hi": max((pct(r["price"]) for r in p1), default=None), "p1_lo": min((pct(r["price"]) for r in p1), default=None),
             "p2_first": pt(p2[0] if p2 else None), "p2": pt(p2[-1] if p2 else None), "fin": pt(fin[0] if fin else None)}
        last = s["fin"] or s["p2"] or s["p1"]
        tags = []
        b0 = s["p2_first"] or s["p1"]   # 9:20 撤单冻结后的第一张快照为基准(9:19:5x 的价里还有临撤的单)
        if b0 and (s["fin"] or s["p2"]) and (s["fin"] or s["p2"]) is not b0:
            d = round((s["fin"] or s["p2"])["pct"] - b0["pct"], 2)
            s["d_after920"] = d
            if d >= 1.0:
                tags.append(f"9:20后抬价{d:+.1f}点")
            elif d <= -1.0:
                tags.append(f"9:20后压价{d:+.1f}点")
        if s["p1"] and s["p1_hi"] is not None and s["p1_hi"] - s["p1"]["pct"] >= 2.0:
            tags.append(f"9:20前虚高(最高{s['p1_hi']:+.1f}%→9:20 {s['p1']['pct']:+.1f}%)")
        if s["p1"] and s["p1_lo"] is not None and s["p1"]["pct"] - s["p1_lo"] >= 2.0:
            tags.append(f"9:20前虚低(最低{s['p1_lo']:+.1f}%→9:20 {s['p1']['pct']:+.1f}%)")
        if s["p2"] and s["p2"]["unm"] and s["p2"]["vol"]:
            if s["p2"]["unm"] >= 0.2 * s["p2"]["vol"]:
                tags.append("不可撤阶段买单未匹配堆积")
            elif s["p2"]["unm"] <= -0.2 * s["p2"]["vol"]:
                tags.append("不可撤阶段卖单未匹配堆积")
        pv = prev_vol.get(sym)
        if last and last.get("vol") and pv:
            s["vol_ratio"] = round(last["vol"] / pv, 4)
            if s["vol_ratio"] >= 0.05:
                tags.append(f"竞价量=昨日全天{s['vol_ratio']:.0%}")
        s["tags"] = tags
        out[sym] = s
    return out


def write_live(out_dir, phase, rows, meta, prev_vol, state):
    try:
        d = {"phase": phase, "updated": dt.datetime.now().isoformat(timespec="seconds"), "state": state, "symbols": summarize(rows, meta, prev_vol, phase)}
        p = out_dir / f"auction_live_{phase.lower()}.json"
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
        tmp.replace(p)
    except Exception as e:   # noqa: BLE001  汇总失败不影响采集本身
        log(f"汇总写盘失败: {e}")


def poll(sess, syms):
    """一批失败: 1 秒后同批重试一次(新连接); 仍失败只丢这一批, 其余批照常(10/18: 原先一批失败整轮作废)"""
    out, fails = {}, 0
    for i in range(0, len(syms), BATCH):
        url = "https://hq.sinajs.cn/list=" + ",".join(syms[i:i + BATCH])
        r = None
        for k in range(2):
            try:
                r = (sess if k == 0 else requests).get(url, headers=UA, timeout=6)
                r.raise_for_status()
                break
            except Exception:   # noqa: BLE001
                r = None
                time.sleep(1.0)
        if r is None:
            fails += 1
            continue
        for line in r.content.decode("gbk", errors="replace").splitlines():
            if "=\"" not in line:
                continue
            sym = line.split("=")[0].rsplit("_", 1)[-1]
            body = line.split("=\"", 1)[1].rstrip("\";")
            if body:
                out[sym] = body.split(",")
    if fails and not out:
        raise RuntimeError(f"全部 {fails} 批失败")
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
        rows, base, meta = {}, {}, {}
        for r in read_jsonl(raw_f):
            f = r["fields"]
            base.setdefault(r["symbol"], int(float(f[8] or 0)) if len(f) > 8 else None)
            if r["symbol"] not in meta and len(f) > 2:
                meta[r["symbol"]] = {"name": f[0], "prev": float(f[2] or 0) or None}
            row = to_row(r["symbol"], f, day, phase, base.get(r["symbol"]))
            if row:
                rows[(r["symbol"], row["snapTime"])] = row
        recs = sorted(rows.values(), key=lambda x: (x["symbol"], x["snapTime"]))
        write_jsonl(out / f"call_auction_{phase.lower()}.jsonl", recs)
        write_live(out, phase, rows, meta, prev_volumes(day), "final")   # 10/18: 历史日也补出按票汇总(回放读同一份)
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
    rows, rounds, errors, base, meta = {}, 0, 0, {}, {}
    jf, rf = out / f"call_auction_{phase.lower()}.jsonl", out / f"call_auction_{phase.lower()}_raw.jsonl"
    if jf.exists():   # 10/18: 同日被重复拉起(应用重启补触发)时接上前一个进程已写的行, 不覆盖
        for r in read_jsonl(jf):
            rows[(r["symbol"], r["snapTime"])] = r
    prev_vol = prev_volumes(day)
    dense = DENSE.get(phase, [])
    while True:
        t0 = time.time()
        if rounds and rounds % 4 == 0:   # 每分钟重扫名单(0915 链候选快照陆续出来)
            syms = targets(day)[0]
        try:
            snap = poll(sess, syms)
            rounds += 1
            at = dt.datetime.now().isoformat(timespec="seconds")
            with rf.open("a", encoding="utf-8") as fh:   # 10/18: 原始报文每轮追加(原先结束时一次性写, 中途崩溃全丢)
                for sym, f in snap.items():
                    fh.write(json.dumps({"at": at, "symbol": sym, "fields": f}, ensure_ascii=False) + "\n")
            for sym, f in snap.items():
                base.setdefault(sym, int(float(f[8] or 0)) if len(f) > 8 else None)   # 首轮累计量=收盘竞价前的量
                if sym not in meta and len(f) > 2:
                    try:
                        meta[sym] = {"name": f[0], "prev": float(f[2] or 0) or None}
                    except ValueError:
                        pass
                row = to_row(sym, f, day, phase, base.get(sym))
                if row:
                    rows[(sym, row["snapTime"])] = row   # 同一报文时刻重复轮询去重
        except Exception as e:   # noqa: BLE001  单轮失败继续下一轮(竞价只有 10 分钟, 不能整段放弃)
            errors += 1
            log(f"轮询失败: {e}")
        now_t = dt.datetime.now().time()
        done = (a.now and rounds >= 3) or (not a.now and now_t >= end)
        # 10/18: 每轮把按时间排序的行 + 按票汇总原子写盘, 竞价期间 facts / 盯盘就能读到(原先 09:25:40 结束才写)
        write_jsonl(jf, sorted(rows.values(), key=lambda r: (r["symbol"], r["snapTime"])))
        write_live(out, phase, rows, meta, prev_vol, "final" if done else "running")
        if done:
            break
        g = DENSE_GAP if any(s <= now_t < e for s, e in dense) else gap
        time.sleep(max(0.0, g - (time.time() - t0)))
    recs = sorted(rows.values(), key=lambda r: (r["symbol"], r["snapTime"]))
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
