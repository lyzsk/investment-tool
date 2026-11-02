# -*- coding: utf-8 -*-
"""受控情境维度：只从行情/涨停/竞价/种子池机械生成，禁止模型自由填标签。"""
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"
LIVE = ROOT / "results" / "_live"
SPEC = json.loads((Path(__file__).parent / "dimensions.json").read_text(encoding="utf-8"))
FIELDS = SPEC["fields"]
STAGES = set(FIELDS["cycle_stage"]["values"])


def _json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _rows(path):
    try:
        return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        return []


def unknown():
    return {"cycle_stage": "无数据", "theme": [], "zibei": {}, "position": "无数据", "auction": "无数据", "pattern": "无数据"}


def validate_dimensions(d):
    if not isinstance(d, dict) or set(d) != set(FIELDS):
        raise ValueError(f"dimensions 字段必须严格为 {list(FIELDS)}")
    for key in ("cycle_stage", "position", "auction", "pattern"):
        if d[key] not in FIELDS[key]["values"]:
            raise ValueError(f"dimensions.{key} 非受控值: {d[key]}")
    if not isinstance(d["theme"], list) or any(not isinstance(x, str) or not x.strip() for x in d["theme"]):
        raise ValueError("dimensions.theme 必须是来源规范化后的非空字符串列表")
    forbidden = set(FIELDS["theme"]["forbidden_free_text"])
    if any(x in forbidden or x != x.strip() for x in d["theme"]):
        raise ValueError(f"dimensions.theme 含自由描述: {d['theme']}")
    if not isinstance(d["zibei"], dict):
        raise ValueError("dimensions.zibei 必须是 {字辈:阶段}")
    for k, v in d["zibei"].items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", k) or v not in STAGES:
            raise ValueError(f"dimensions.zibei 非受控值: {k}:{v}")
    return True


def _canon_theme(x):
    x = re.sub(r"\s+", "", str(x or ""))
    return "" if x in FIELDS["theme"]["forbidden_free_text"] else x


def _stage_from_theme_label(label):
    x = re.sub(r"[（(].*?[）)]", "", str(label or ""))
    if x in ("退潮后回流",):
        return "修复"
    if x in ("疑似退潮", "退潮"):
        return "退潮"
    if x in ("弱发酵",):
        return "发酵"
    if x in ("断档", "今天没出现"):
        return "断档"
    if x in ("无数据", "从未出现"):
        return "无数据"
    return x if x in STAGES else "无数据"


def market_stage(day):
    rows = []
    for d in sorted(MKT.glob("20*")):
        if d.name > day:
            continue
        m = _rows(d / "mood.jsonl")
        if m:
            rows.append((d.name, m[-1]))
    if not rows or rows[-1][0] != day:
        return "无数据", {}
    cur = rows[-1][1]
    prev = [r for d, r in rows[:-1]][-20:]
    med3 = statistics.median([float(r.get("zt") or 0) for r in prev[-3:]]) if prev else 0.0
    p75 = sorted(float(r.get("zt") or 0) for r in prev)[int(0.75 * (len(prev) - 1))] if prev else float(cur.get("zt") or 0)
    rise, fall = float(cur.get("rise") or 0), float(cur.get("fall") or 0)
    ratio = rise / max(1.0, rise + fall)
    zt, avg = float(cur.get("zt") or 0), float(cur.get("avg") or 0)
    prev_avg = float(prev[-1].get("avg") or 0) if prev else avg
    if ratio <= 0.15 and float(cur.get("dt") or 0) >= 10 and zt <= max(10, med3 * 0.6):
        stage = "冰点"
    elif prev and zt < med3 * 0.6 and avg < 0:
        stage = "退潮"
    elif prev and zt >= p75 and ratio >= 0.60:
        stage = "高潮"
    elif prev and zt > med3 * 1.2 and avg > prev_avg and ratio < 0.50:
        stage = "修复"
    elif prev and zt > med3 * 1.2 and ratio >= 0.50:
        stage = "发酵"
    elif prev and ratio < 0.35 and zt >= med3:
        stage = "分歧"
    else:
        stage = "震荡"
    return stage, {"zt": zt, "dt": cur.get("dt"), "rise": rise, "fall": fall, "avg": avg,
                   "prev3_zt_median": med3, "prev20_zt_p75": p75, "up_ratio": round(ratio, 4)}


def _zibei_stage(cur, prev):
    if not prev:
        return "首日"
    n, excess = float(cur.get("n") or 0), float(cur.get("excess") or 0)
    ns = [float(x.get("n") or 0) for x in prev[-3:]]
    med = statistics.median(ns)
    latest = prev[-1]
    prev_was_down = float(latest.get("n") or 0) < statistics.median([float(x.get("n") or 0) for x in prev[:-1][-3:]] or ns) and float(latest.get("excess") or 0) < 0
    if prev_was_down and n > float(latest.get("n") or 0) and excess > 0:
        return "修复"
    sync = float(cur.get("sync3") or 0) / max(1.0, n)
    if float(cur.get("lift") or 0) >= 2 and sync >= 0.6:
        return "高潮"
    if n > med and excess > 0:
        return "发酵"
    if n < med and excess < 0:
        return "退潮"
    if excess < 0 or sync < 0.4:
        return "分歧"
    return "震荡"


def _auction(day):
    doc = _json(MKT / day / "auction_live_open.json", {})
    return doc.get("symbols") or {}


def auction_dimension(s):
    if not s:
        return "无数据", {}
    fin = s.get("fin") or s.get("p2") or {}
    p2 = s.get("p2") or {}
    pct = fin.get("pct")
    change = s.get("d_after920")
    unm = fin.get("unm") if fin.get("unm") is not None else p2.get("unm")
    feat = {"pct": pct, "d_after920": change, "unm": unm, "time": fin.get("t")}
    if pct is None or change is None:
        return "无数据", feat
    if change > 0 and (unm or 0) > 0:
        return ("竞价低吸" if pct < 0 else "竞价抢筹"), feat
    if change < 0 and (unm or 0) < 0:
        return ("竞价高抛" if pct > 0 else "竞价抢跑"), feat
    return ("高开" if pct >= 0.2 else "低开" if pct <= -0.2 else "平开"), feat


def trend_pattern(code, day):
    """非连板票也分型：趋势 / 转强候选只描述均线事实，不预判必然涨停。"""
    k = _json(ROOT / "downloads" / "quotes" / "daily" / f"{code}.json", {}).get("klines") or []
    k = [x for x in k if x.get("d", "") <= day and x.get("c")]
    if len(k) < 60:
        return "普通", {"n": len(k)}
    closes = [float(x["c"]) for x in k]
    ma20 = statistics.fmean(closes[-20:])
    ma60 = statistics.fmean(closes[-60:])
    ma20_prev = statistics.fmean(closes[-25:-5])
    close = closes[-1]
    amount20 = statistics.fmean(float(x.get("a") or 0) for x in k[-20:])
    feat = {"close": close, "ma20": ma20, "ma60": ma60, "ma20_5d_ago": ma20_prev, "amount20": amount20}
    if close > ma20 > ma60 and ma20 > ma20_prev:
        return "趋势", feat
    if close > ma20 and ma20 > ma20_prev:
        return "转强候选", feat
    return "普通", feat


def build(day, code, watch=None):
    watch = watch if watch is not None else _json(LIVE / day / "watch_seed.json", {})
    cycle, market_feat = market_stage(day)
    moods = _rows(MKT / day / "mood.jsonl")
    mood = moods[-1] if moods else {}
    up = next((x for x in mood.get("up") or [] if str(x[0]) == code), None)
    topo = next((x for x in _rows(MKT / day / "topology.jsonl") if x.get("c") == code), {})
    raw_themes = ([up[3]] if up and len(up) > 3 else []) + ([topo.get("main")] if topo.get("main") else [])
    themes = list(dict.fromkeys(t for raw in raw_themes for t in (_canon_theme(x) for x in str(raw or "").split("+")) if t))
    theme_feat = {}
    if themes:
        try:
            sys.path.insert(0, str(ROOT / "scripts" / "paper_line" / "tools"))
            import theme_phase as TP
            for th in themes:
                p = TP.phase(th, day)
                theme_feat[th] = {"stage": _stage_from_theme_label(p.get("标签")), "raw": p}
        except Exception as e:  # 无题材历史时明确无数据，不自由补写
            theme_feat = {th: {"stage": "无数据", "error": type(e).__name__} for th in themes}
    tags = next((x.get("tags") or [] for x in watch.get("seed") or [] if x.get("code") == code), [])
    height = int(up[2]) if up and len(up) > 2 else 0
    position = ("1板" if height == 1 else "2板" if height == 2 else "3板" if height == 3 else "4板+" if height >= 4
                else "断板" if "续板" in tags else "非板" if mood else "无数据")
    zb, zb_feat = {}, {}
    for cur in watch.get("zibei") or []:
        py = cur.get("py")
        if not py:
            continue
        chars = set(cur.get("chars") or [])
        tagged = any(t.startswith("字辈:") and chars & set(t.split(":", 1)[1].split("/")) for t in tags)
        member = bool(topo.get("n") and topo["n"] in (cur.get("members_lu10") or []))
        if not tagged and not member:
            continue
        prev = []
        for d in sorted(LIVE.glob("20*")):
            if d.name >= day:
                continue
            w = _json(d / "watch_seed.json", {})
            old = next((x for x in w.get("zibei") or [] if x.get("py") == py), None)
            if old:
                prev.append(old)
        zb[py] = _zibei_stage(cur, prev[-4:])
        zb_feat[py] = {k: cur.get(k) for k in ("n", "lift", "excess", "sync3", "inds")}
    symbol = ("sh" if code.startswith(("6", "5", "11")) else "sz") + code
    auc = _auction(day).get(symbol) or {}
    auction, auc_feat = auction_dimension(auc)
    trend, trend_feat = trend_pattern(code, day)
    pattern = ("转债" if code.startswith(("11", "12")) else "ETF" if code.startswith(("15", "16", "50", "51", "56", "58"))
               else "连板中" if height >= 2 else "首板" if height == 1 else "断板" if position == "断板" else trend)
    dims = {"cycle_stage": cycle, "theme": themes, "zibei": zb, "position": position, "auction": auction, "pattern": pattern}
    validate_dimensions(dims)
    features = {"market": market_feat, "theme": theme_feat, "zibei": zb_feat, "auction": auc_feat, "height": height, "tags": tags, "trend": trend_feat}
    return dims, features


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("day")
    ap.add_argument("codes")
    a = ap.parse_args()
    for c in a.codes.split(","):
        d, f = build(a.day, c)
        print(c, json.dumps({"dimensions": d, "features": f}, ensure_ascii=False, indent=1))
