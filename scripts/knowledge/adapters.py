# -*- coding: utf-8 -*-
"""来源适配器：只读现有数据，输出统一 source/context/case。"""
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "paper_line"), str(ROOT / "scripts" / "lib")]
from broker_trades import parse_trade_line
PARSER = "knowledge-v1.1"


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


def sha1(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def manifest(source_id, typ, uri, quality="ok", error=""):
    p = Path(uri)
    source_time = dt.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds") if p.exists() else now()
    return {"source_id": source_id, "type": typ, "uri": str(uri), "sha1": sha1(p) if p.is_file() else "",
            "source_time": source_time,
            "ingest_time": now(), "parser_version": PARSER, "quality_status": quality, "error": error}


def put_manifest(store, rec):
    from schema import validate_source_manifest
    validate_source_manifest(rec)
    store.upsert("source_manifest", rec, "source_id")


def put_context(store, rec):
    from schema import validate_context
    validate_context(rec)
    store.upsert("context_snapshot", rec, "context_id")


def put_case(store, rec):
    from epistemics import candidate
    from schema import validate_case
    rec.setdefault("epistemic", candidate(source="adapter", as_of=rec["available_at"], evidence=[rec["source_id"]]))
    validate_case(rec)
    store.upsert("case_record", rec, "case_id")


def read_status(path):
    last = None
    for _ in range(5):
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError as e:
            last = e
            import time
            time.sleep(0.1)
    raise last


class WatchAdapter:
    def __init__(self, root=ROOT):
        self.root = Path(root)

    def load(self, day):
        f = self.root / "results" / "_live" / day / "watch_seed.json"
        if not f.exists():
            return {}, []
        d = json.loads(f.read_text(encoding="utf-8"))
        return d, [manifest(f"watch:{day}", "watch_seed", f)]


class MarketAdapter:
    def __init__(self, store, root=ROOT):
        self.store, self.root = store, Path(root)

    def _rows(self, day, name):
        f = self.root / "downloads" / "market" / day / name
        return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []

    def ingest_day(self, day, cycle, codes):
        watch, sources = WatchAdapter(self.root).load(day)
        for src in sources:
            put_manifest(self.store, src)
        day_file = self.root / "downloads" / "market" / day / "kline_day.jsonl"
        if day_file.exists():
            put_manifest(self.store, manifest(f"day:{day}", "kline_day", day_file))
        auction_file = self.root / "downloads" / "market" / day / "call_auction_open.jsonl"
        if auction_file.exists():
            put_manifest(self.store, manifest(f"auction:{day}", "call_auction_open", auction_file))
        for name, typ in (("mood.jsonl", "mood"), ("topology.jsonl", "topology"), ("auction_live_open.json", "auction_live_open")):
            f = self.root / "downloads" / "market" / day / name
            if f.exists():
                src = manifest(f"{typ}:{day}", typ, f)
                put_manifest(self.store, src)
                sources.append(src)
        days = self._rows(day, "kline_day.jsonl")
        by_symbol = {r["symbol"]: r for r in days}
        by_code = {}
        for r in days:
            code = r["symbol"][-6:]
            expected = ("sh" if code.startswith(("6", "5", "11")) else "bj" if code.startswith(("4", "8")) else "sz") + code
            if r["symbol"] == expected:
                by_code[code] = r
        auctions = self._rows(day, "call_auction_open.jsonl")
        auc = {}
        for r in auctions:
            if r.get("symbol"):
                auc[r["symbol"][2:]] = r
        zibei = watch.get("zibei") or []
        from dimensions import build as build_dimensions, market_stage
        from epistemics import prior
        global_cycle = market_stage(day)[0]
        n = 0
        for code in codes:
            if code not in by_code:
                continue
            r = by_code[code]
            context_id = f"{day}:{code}"
            tags = next((x.get("tags") for x in watch.get("seed") or [] if x.get("code") == code), [])
            dims, features = build_dimensions(day, code, watch)
            subject_zibei = [z for z in zibei if z.get("py") in dims["zibei"]]
            c = {"context_id": context_id, "subject": code, "as_of": f"{day}T15:00:00", "available_at": f"{day}T15:00:00",
                 "market": {"cycle": dims["cycle_stage"], "prior_cycle_note": ({"text": cycle, "epistemic": prior(source="user_note", as_of=f"{day}T15:00:00", evidence=["user_note"])} if cycle else None), "index": by_symbol.get("sh000001") or {}, "features": features["market"]},
                 "theme": {"zibei": subject_zibei, "tags": tags, "features": features["theme"], "zibei_features": features["zibei"]},
                 "instrument": {"code": code, "day": r, "auction": auc.get(code) or {}, "features": {"auction": features["auction"], "height": features["height"], "trend": features["trend"]}},
                 "dimensions": dims,
                 "evidence": [s["source_id"] for s in sources] + [f"day:{day}", f"auction:{day}"]}
            put_context(self.store, c)
            n += 1
        self.store.upsert("belief_state", {"id": f"belief:{day}", "as_of": f"{day}T15:00:00",
                                           "state": {"cycle": global_cycle, "zibei": zibei}, "evidence": [s["source_id"] for s in sources]}, "id")
        return n


class TzzbAdapter:
    def __init__(self, store, root=ROOT):
        self.store, self.root = store, Path(root)

    def ingest_day(self, day, codes):
        import manual_backfill as mb
        c = mb.db().cursor()
        marks = ",".join(repr(x) for x in codes)
        c.execute("select ledger,time(record_time),stock_code,stock_name,side,price,qty from investment_tool.tzzb_record "
                  f"where record_type='bs_leg' and is_deleted=0 and date(record_time)=%s and stock_code in ({marks}) order by time(record_time)", (day,))
        rows = c.fetchall()
        source = f"tzzb:{day}"
        put_manifest(self.store, {"source_id": source, "type": "tzzb_record", "uri": "investment_tool.tzzb_record", "sha1": "",
                                  "source_time": f"{day}T23:59:59", "ingest_time": now(), "parser_version": PARSER, "quality_status": "ok", "error": ""})
        for i, (ledger, tm, code, name, side, px, qty) in enumerate(rows):
            put_case(self.store, {"case_id": f"trade:{day}:{code}:{ledger}:{i}", "subject": code, "context_id": f"{day}:{code}",
                                  "issued_at": f"{day}T{tm}", "available_at": f"{day}T{tm}", "hypothesis": f"{ledger} {side}",
                                  "action": {"side": side, "price": float(px), "qty": float(qty), "mentor": ledger, "name": name}, "outcome": {},
                                  "label": "待核", "confidence": {"raw": "高", "basis": "真实逐笔"}, "review_state": "active", "source_id": source})
        return len(rows)


class KlineAdapter:
    def __init__(self, store, root=ROOT):
        self.store, self.root = store, Path(root)

    def ingest_day(self, day, status=None):
        f = os.path.join(str(self.root), "results", "kline", day, "_status.json")
        if status is None:
            try:
                status = read_status(f)
            except FileNotFoundError as e:
                print(f"KlineAdapter 状态文件读取失败: {e}")
                return 0
        st = status
        source = f"kline:{day}"
        put_manifest(self.store, manifest(source, "kline_status", f))
        n = 0
        for name, g in st.get("images", {}).items():
            code = str(g.get("case") or "").split("@")[0]
            if not code:
                continue
            issued = str((g.get("预测") or {}).get("时间") or g.get("收件"))
            put_case(self.store, {"case_id": f"image:{day}:{name}", "subject": code, "context_id": f"{day}:{code}",
                                  "issued_at": issued, "available_at": issued, "hypothesis": f"K线截图 {g.get('类型')}",
                                  "action": {"chart_type": g.get("类型"), "file": name}, "outcome": {"prediction": g.get("预测") or {}},
                                  "label": "待核", "confidence": {"raw": (g.get("预测") or {}).get("置信") or "待核"}, "review_state": "active", "source_id": source})
            n += 1
        return n


class ForecastAdapter:
    """真实预测核销结果：只有 evaluated_at 已到达且 hit 非空的记录才能标 verified。"""
    def __init__(self, store, root=ROOT):
        self.store, self.root = store, Path(root)

    def ingest_day(self, day, codes, as_of=None):
        from epistemics import verified
        f = self.root / "results" / "forecast" / "ledger.db"
        if not f.exists():
            return 0
        put_manifest(self.store, manifest(f"forecast:{day}", "forecast_ledger", f))
        c = sqlite3.connect(f)
        marks = ",".join("?" for _ in codes)
        at = as_of or now()   # 核销可能发生在情境日之后；context_pack 再按调用时刻过滤，不能在这里假装当天已核销
        rows = c.execute("select dedupe,kind,code,issued_at,predicted,prob,context,hit,baseline_hit,evaluated_at from predictions "
                         f"where code in ({marks}) and late=0 and hit is not null and issued_at<=? and evaluated_at<=?", [*codes, at, at]).fetchall()
        c.close()
        for dedupe, kind, code, issued, predicted, prob, ctx, hit, baseline, evaluated in rows:
            put_case(self.store, {"case_id": f"forecast:{dedupe}", "subject": code, "context_id": f"{day}:{code}",
                                  "issued_at": issued, "available_at": evaluated, "target_start": None, "target_end": None,
                                  "hypothesis": str(predicted), "action": {"kind": kind, "prob": prob, "context": ctx},
                                  "outcome": {"hit": int(hit), "baseline_hit": baseline}, "label": "正" if hit else "负",
                                  "confidence": {"raw": "已核销", "basis": "forecast_ledger"},
                                  "epistemic": verified(1, int(hit), evaluated, [dedupe]), "review_state": "active", "source_id": f"forecast:{day}"})
        return len(rows)


class UserAdapter:
    def __init__(self, store, root=ROOT):
        self.store, self.root = store, Path(root)

    def ingest_day(self, day):
        source = f"user:{day}"
        put_manifest(self.store, {"source_id": source, "type": "user_trades", "uri": str(self.root / "scripts" / "dfcf" / "snapshots"), "sha1": "",
                                  "source_time": f"{day}T23:59:59", "ingest_time": now(), "parser_version": PARSER, "quality_status": "ok", "error": ""})
        rows = []
        for f in (self.root / "scripts" / "dfcf" / "snapshots").glob(f"{day}_成交_*.txt"):
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                row = parse_trade_line(line)
                if row:
                    rows.append(row)
        rows.sort()
        for i, (tm, code, name, side, px, qty) in enumerate(rows):
            put_case(self.store, {"case_id": f"user:{day}:{code}:{i}", "subject": code, "context_id": f"{day}:{code}",
                                  "issued_at": f"{day}T{tm}", "available_at": f"{day}T{tm}", "hypothesis": "用户实盘",
                                  "action": {"side": side, "price": float(px), "qty": int(qty), "name": name}, "outcome": {},
                                  "label": "待核", "confidence": {"raw": "高", "basis": "用户交割单"}, "review_state": "active", "source_id": source})
        return len(rows)


class UPAdapter:
    def __init__(self, store, root=ROOT):
        self.store, self.root = store, Path(root)

    def ingest_day(self, day):
        base = self.root / "results" / "bilibili"
        n = 0
        for f in sorted(base.glob(f"*/{day.replace('-', '.')}/*.vision.json")):
            up = f.parent.parent.name
            source = f"up:{up}:{f.stem}"
            put_manifest(self.store, manifest(source, "up_vision", f))
            doc = json.loads(f.read_text(encoding="utf-8"))
            pages = doc.get("pages") or {}
            bs = pages.get("BS买卖点") or []
            positions = pages.get("持仓快照") or []
            if not bs and not positions:
                continue
            code = f.stem
            put_case(self.store, {"case_id": f"up:{up}:{code}", "subject": code, "context_id": f"{day}:{code}",
                                  "issued_at": f"{day}T23:59:59", "available_at": f"{day}T23:59:59", "hypothesis": "UP画面操作证据(待核)",
                                  "action": {"bs": bs, "positions": positions}, "outcome": {}, "label": "待核",
                                  "confidence": {"raw": "待核", "basis": "视频抽帧，需连续帧或人工复核"}, "review_state": "watch", "source_id": source})
            n += 1
        return n
