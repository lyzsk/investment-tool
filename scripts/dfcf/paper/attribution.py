# -*- coding: utf-8 -*-
"""attribution.py — 归因推导链(10/20 晚用户批 TODO 一-1 ④; 零 token, 只读)

为什么: 07 复盘停在"直接原因 + 一句教训", 不追根因层、不做反事实、不看别的链(10/20 量化 07 写"作废后不重追", 真因是拟人审重跑让出单晚 12 分钟)。
做什么: 对每条在跑的链, 当天每张单 / 每只票沿 数据 → 驱动器 → 规则 → 判断 → 撮合 五层逐层检测, 命中一项记一条"原因 → 结果"(证据 + 金额),
  每条配一个反事实(改了会怎样, 用当天数据算); 再做跨链汇总: 同一检测项 ≥2 条链 = 系统性根因; 并列出当天赚钱的做法(取长补短)。
检测项(第一版, 都是机械判定):
  数据  D1 下单时这只票还不在 3 秒盘口名单(首个快照晚于落单)          D2 当天收盘价拿不到(07 无法归因)
  驱动器 V1 06 落单比时段晚 ≥ 8 分钟(反事实: 按时段 +2 分钟的价格成交)    V2 下限 / 追仓豁免推出来的买单(反事实: 不买)
  规则  G1 买单只引了非"买"方向的规则, 或理由自认情境不满足(反事实: 不买)
  判断  J1 隔夜持仓当天亏 ≥ 1% 且全天没有卖单(反事实: 开盘卖)
  撮合  M1 被锚偏离 / 追价上限作废的买单(反事实: 作废时按现价成交)       M2 竞价T 卖价 = 开盘价(只吃手续费)
产物: results/_attribution/<日>.json + <日>.md; 07 注入 block_07(skill, 日)(每链只给本链明细 + 跨链汇总前几条 + 必答格式)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/attribution.py --date D [--print]
"""
import argparse
import datetime as dt
import gzip
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MKT = ROOT / "downloads" / "market"
OUT = ROOT / "results" / "_attribution"
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import mentors   # noqa: E402

LAYERS = {"D": "数据", "V": "驱动器", "G": "规则", "J": "判断", "M": "撮合"}
NAMES = {"D1": "下单时不在 3 秒盘口名单(无分时)", "D2": "收盘价缺失", "V1": "出单时延 ≥8 分钟", "V2": "下限 / 追仓豁免推出来的买单",
         "G1": "买单没有合格的买入规则", "J1": "隔夜持仓亏 ≥1% 全天没处置", "M1": "被锚偏离 / 追价上限作废的买单", "M2": "竞价T 卖价 = 开盘价"}


def _jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def day_bars(D):
    f = MKT / D / "kline_day.jsonl"
    out = {}
    if f.exists():
        for l in f.open(encoding="utf-8"):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            out[r["symbol"][2:]] = r
    return out


def book_first_seen(D):
    """3 秒盘口: 每只票第一个快照时刻 + 分钟价(做时延反事实)"""
    f, op = MKT / D / "book_snap.jsonl", open
    if not f.exists():
        f, op = MKT / D / "book_snap.jsonl.gz", gzip.open
    first, px = {}, {}
    if f.exists():
        with op(f, "rt", encoding="utf-8") as fh:
            for l in fh:
                try:
                    r = json.loads(l)
                except ValueError:
                    continue
                c, t = str(r.get("s", ""))[2:], r.get("t", "")
                if not c or not r.get("p"):
                    continue
                first.setdefault(c, t)
                if t >= "09:30:00":
                    px.setdefault(c, {}).setdefault(t[:5], r["p"])
    return first, px


def minute_px(D):
    """关注集分钟线(收盘后采): {code: {HH:MM: close}}"""
    out = {}
    for fn in ("kline_minute.jsonl", "kline_minute_extra.jsonl"):
        f = MKT / D / fn
        if not f.exists():
            continue
        for l in f.open(encoding="utf-8"):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            out.setdefault(str(r["symbol"])[2:], {})[r["barTime"][11:16]] = r["close"]
    return out


def price_at(code, hm, mins, book_px):
    for src in (mins.get(code) or {}, book_px.get(code) or {}):
        ks = [k for k in src if k <= hm]
        if ks:
            return src[max(ks)]
    return None


def contracts(skill, D):
    """该链当天各时段 06 contract: {slot: (contract, 06 写出时刻)}"""
    d8 = D.replace("-", "")
    rd = ROOT / "results" / f"{skill}_chain" / f"live-{d8}"
    out = {}
    if not rd.exists():
        return out
    for f in [rd / "slots" / "0915" / "06_verdict.md"] + sorted((rd / "slots").glob("*/06_verdict.md")):
        if not f.exists():
            continue
        slot = f.parent.name
        m = re.findall(r"```contract\s*(\{.*?\})\s*```", f.read_text(encoding="utf-8"), re.S)
        try:
            c = json.loads(m[-1]) if m else {}
        except ValueError:
            c = {}
        out[slot] = (c, dt.datetime.fromtimestamp(f.stat().st_mtime).strftime("%H:%M"))
    return out


def analyze(D):
    bars, (first, book_px), mins = day_bars(D), book_first_seen(D), minute_px(D)
    tags = {}
    names = _jl(HERE / "names.json", {}) or {}
    chains = []
    for e in [mentors.get(x) for x in mentors.active_ids()]:
        skill, bk = e["id"], e["book"]
        b = _jl(HERE / "books" / f"{bk}.json")
        if not b:
            continue
        try:
            tags = (_jl(HERE / "rule_tags" / f"{skill}.json", {}) or {}).get("rules") or {}
        except Exception:   # noqa: BLE001
            tags = {}
        nav = [n for n in b.get("nav") or [] if n.get("date", "") >= "2026-10-08"]
        i = next((k for k, n in enumerate(nav) if n["date"] == D), None)
        prev_nav = (nav[i - 1]["nav"] if i else 100000) if i is not None else None
        dnav = (nav[i]["nav"] - prev_nav) if i is not None else None
        qty = {}
        for t in sorted(b.get("trades") or [], key=lambda x: str(x["id"])):
            if str(t["id"])[:10] >= D:
                continue
            qty[t["code"]] = qty.get(t["code"], 0) + (t["qty"] if t["side"] == "BUY" else -t["qty"])
        todays = [t for t in b.get("trades") or [] if str(t["id"]).startswith(D)]
        orders = [o for o in b.get("orders") or [] if o.get("date") == D]
        per, finds, missing = {}, [], []
        for c in set([k for k, v in qty.items() if v > 0] + [t["code"] for t in todays]):
            r = bars.get(c)
            if not r or not r.get("close") or not r.get("preClose"):
                missing.append(c)
                continue
            pnl = (qty.get(c, 0) if qty.get(c, 0) > 0 else 0) * (r["close"] - r["preClose"])
            for t in todays:
                if t["code"] == c:
                    pnl += (1 if t["side"] == "BUY" else -1) * t["qty"] * (r["close"] - t["price"])
            per[c] = round(pnl, 0)
        if missing:
            finds.append({"id": "D2", "codes": missing, "amt": None, "ev": f"{len(missing)} 只票当日收盘价缺(kline_day 没有)", "cf": None})
        C = contracts(skill, D)
        why_of = {}   # 06 理由: (code, side) → (slot, action)
        for slot, (c, t06) in C.items():
            for a in c.get("actions") or []:
                if a.get("code"):
                    why_of.setdefault((str(a["code"]), "BUY" if a.get("op") == "买" else "SELL"), (slot, a, c, t06))
        for o in orders:
            c, side = o["code"], o["side"]
            r = bars.get(c) or {}
            close = r.get("close")
            fill = next((t for t in todays if t["code"] == c and t["side"] == side and str(t["id"]).startswith(o["id"])), None)
            slot = (o.get("time") or "").replace(":", "")
            sa = why_of.get((c, side))
            # D1 下单时无分时
            placed = o.get("placedAt") or (sa[3] + ":00" if sa else None)
            fs = first.get(c)
            active = max(placed or "", "09:30:00", (o.get("cond") or {}).get("not_before", "") + ":00" if (o.get("cond") or {}).get("not_before") else "")   # 盘前单从 09:30 起算
            if side == "BUY" and o.get("status") != "cxl" and placed and (not fs or fs > active):
                finds.append({"id": "D1", "codes": [c], "amt": None, "ev": f"{c}{names.get(c, '')} {o['time']} 时段单 {placed[:5]} 落单(生效 {active[:5]}), 3 秒盘口首个快照 {fs or '无'}", "cf": None})
            # V1 出单时延
            if sa and slot and slot.isdigit():
                lag = (dt.datetime.strptime(sa[3], "%H:%M") - dt.datetime.strptime(slot, "%H%M")).seconds // 60
                if 8 <= lag <= 120 and side == "BUY" and fill and close:
                    p0 = price_at(c, (dt.datetime.strptime(slot, "%H%M") + dt.timedelta(minutes=2)).strftime("%H:%M"), mins, book_px)
                    cf = round((fill["price"] - p0) * fill["qty"], 0) if p0 else None
                    finds.append({"id": "V1", "codes": [c], "amt": cf, "ev": f"{c}{names.get(c, '')} {slot} 时段 06 {sa[3]} 才出(晚 {lag} 分钟), 成交 {fill['price']}, 时段 +2 分钟价 {p0}",
                                  "cf": (f"晚出单多花 {cf:.0f} 元" if cf > 0 else f"晚出单反而便宜 {-cf:.0f} 元") if cf is not None else "分钟价缺, 算不了"})
            if sa and side == "BUY" and o.get("status") == "filled" and fill and close:
                a, cc = sa[1], sa[2]
                txt = json.dumps(a.get("rules") or [], ensure_ascii=False) + str(a.get("why") or "") + str(cc.get("deviation_reason") or "")
                pnl_b = round((close - fill["price"]) * fill["qty"], 0)
                if re.search(r"下限|追仓豁免|凑仓|凑满", txt):   # V2
                    finds.append({"id": "V2", "codes": [c], "amt": -pnl_b, "ev": f"{c}{names.get(c, '')} {fill['qty']}@{fill['price']} 理由含下限 / 追仓豁免, 当日 {pnl_b:+.0f}",
                                  "cf": f"若不买: {-pnl_b:+.0f} 元"})
                rs = [x if isinstance(x, dict) else {"id": str(x)} for x in a.get("rules") or []]
                okr = [x for x in rs if (tags.get(str(x.get("id"))) or {}).get("dir") == "买" and not re.search(r"不满足|不成立|未满足|不引用", str(x.get("ctx") or ""))]
                if tags and not okr:   # G1
                    finds.append({"id": "G1", "codes": [c], "amt": -pnl_b, "ev": f"{c}{names.get(c, '')} 引用 {[x.get('id') for x in rs]} 没有情境成立的买规则, 当日 {pnl_b:+.0f}",
                                  "cf": f"若不买: {-pnl_b:+.0f} 元"})
            # M1 作废反事实
            m = re.search(r"(锚偏离作废: 锚[\d.]+ vs 前收[\d.]+/现价([\d.]+)|超追价上限作废: 现价([\d.]+))", o.get("note") or "")
            if m and side == "BUY" and close:
                p = float(m.group(2) or m.group(3))
                cf = round((close - p) * o["qty"], 0)
                finds.append({"id": "M1", "codes": [c], "amt": cf, "ev": f"{c}{names.get(c, '')} {o['time']} 买单作废(作废时现价 {p})", "cf": f"若按作废时现价成交, 到收盘 {cf:+.0f} 元"})
            # M2 竞价T 卖价 = 开盘价
            if fill and "竞价T卖" in (fill.get("why") or "") and r.get("open") and abs(fill["price"] - r["open"]) < 1e-6:
                finds.append({"id": "M2", "codes": [c], "amt": None, "ev": f"{c} 竞价T 卖价 {fill['price']} = 开盘价, 只吃手续费", "cf": "10/20 晚已修: 卖价取 3 秒盘口连续竞价首个买一"})
        # J1 隔夜持仓亏 ≥1% 全天没卖单
        for c, q in qty.items():
            r = bars.get(c) or {}
            if q > 0 and r.get("preClose") and r.get("close") and r["close"] / r["preClose"] - 1 <= -0.01 and not any(o["code"] == c and o["side"] == "SELL" for o in orders):
                cf = round((r["close"] - r["open"]) * q, 0)
                finds.append({"id": "J1", "codes": [c], "amt": -cf, "ev": f"{c}{names.get(c, '')} 隔夜 {q} 股, 当日 {(r['close'] / r['preClose'] - 1) * 100:+.2f}%, 全天无卖单",
                              "cf": f"若开盘卖: {-cf:+.0f} 元(开 {r['open']} 收 {r['close']})"})
        best = sorted(((v, c) for c, v in per.items()), reverse=True)
        chains.append({"skill": skill, "book": bk, "name": e.get("display") or e.get("short"), "dnav": dnav, "dnav_pct": (dnav / prev_nav) if dnav is not None and prev_nav else None,
                       "per": per, "finds": finds, "best": best[:2], "worst": best[-2:][::-1] if best else []})
    # 跨链汇总
    agg = {}
    for ch in chains:
        for f in ch["finds"]:
            g = agg.setdefault(f["id"], {"id": f["id"], "layer": LAYERS[f["id"][0]], "name": NAMES[f["id"]], "chains": set(), "n": 0, "amt": 0.0})
            g["chains"].add(ch["skill"])
            g["n"] += 1
            g["amt"] += f["amt"] or 0
    cross = sorted(({**g, "chains": sorted(g["chains"]), "amt": round(g["amt"], 0), "systemic": len(g["chains"]) >= 2} for g in agg.values()),
                   key=lambda g: (not g["systemic"], -abs(g["amt"]), -g["n"]))
    good = []
    for ch in chains:
        for v, c in ch["best"]:
            if v > 300:
                good.append({"skill": ch["skill"], "name": ch["name"], "code": c, "stock": names.get(c, ""), "pnl": v})
    good.sort(key=lambda x: -x["pnl"])
    return {"date": D, "chains": chains, "cross": cross, "good": good[:8], "built": dt.datetime.now().isoformat(timespec="seconds")}


def render(R):
    L = [f"# 归因推导链 {R['date']}(零 token 机械检测; 金额 = 反事实: 改了会多赚(+) / 少亏(−))"]
    L.append("\n## 跨链汇总(同一检测项 ≥2 条链 = 系统性根因)")
    for g in R["cross"]:
        L.append(f"- {'【系统性】' if g['systemic'] else ''}{g['layer']}层 {g['id']} {g['name']}: {g['n']} 次, {len(g['chains'])} 条链({'、'.join(g['chains'])}), 反事实合计 {g['amt']:+.0f} 元")
    if R["good"]:
        L.append("\n## 当天赚钱的做法(取长补短: 别的链能不能借)")
        for x in R["good"]:
            L.append(f"- {x['name']}: {x['code']}{x['stock']} {x['pnl']:+.0f} 元")
    L.append("\n## 各链明细")
    for ch in R["chains"]:
        p = f"{ch['dnav_pct'] * 100:+.2f}%" if ch["dnav_pct"] is not None else "—"
        L.append(f"\n### {ch['name']}({ch['book']}) 当日 {p}; 逐票: " + ", ".join(f"{c} {v:+.0f}" for c, v in sorted(ch["per"].items(), key=lambda kv: kv[1])))
        for f in ch["finds"]:
            L.append(f"- {LAYERS[f['id'][0]]}层 {f['id']} {NAMES[f['id']]}: {f['ev']}" + (f" → 反事实: {f['cf']}" if f.get("cf") else ""))
    return "\n".join(L)


def build(D):
    import os
    R = analyze(D)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, body in ((f"{D}.json", json.dumps(R, ensure_ascii=False, indent=1)), (f"{D}.md", render(R))):   # 07 四条并行时可能同时重算: 写临时文件再替换
        tmp = OUT / f"{name}.{os.getpid()}.tmp"
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, OUT / name)
    return R


def block_07(skill, D):
    """07 注入: 本链明细 + 跨链汇总前 6 条 + 必答格式(没有产物就现场算; 失败 = 空串)"""
    try:
        R = build(D)   # 每次现算(约 1~2 秒): 15:40 首轮时收盘数据可能还没齐, 不用旧缓存
    except Exception as e:   # noqa: BLE001
        return f"\n\n# 驱动器补充: 归因推导链生成失败({e}), 本次 07 自行归因\n"
    ch = next((x for x in R["chains"] if x["skill"] == skill), None)
    if not ch:
        return ""
    L = ["\n\n# 驱动器补充: 归因推导链(10/20 用户批; 零 token 机械算好的逐票盈亏 / 检测项 / 反事实, 你不用再自己找证据)"]
    p = f"{ch['dnav_pct'] * 100:+.2f}%" if ch["dnav_pct"] is not None else "—"
    L.append(f"- 本链当日 {p}; 逐票盈亏: " + (", ".join(f"{c} {v:+.0f}" for c, v in sorted(ch["per"].items(), key=lambda kv: kv[1])) or "无持仓 / 无成交"))
    for f in ch["finds"]:
        L.append(f"- 本链命中 {LAYERS[f['id'][0]]}层 {f['id']} {NAMES[f['id']]}: {f['ev']}" + (f" → 反事实: {f['cf']}" if f.get("cf") else ""))
    if not ch["finds"]:
        L.append("- 本链没有命中任何检测项(检测项是第一版, 没命中不代表没问题)")
    L.append("- 跨链汇总(系统性根因优先): " + "; ".join(f"{g['layer']}层 {g['name']} {len(g['chains'])} 条链 {g['amt']:+.0f} 元" for g in R["cross"][:6]))
    if R.get("good"):
        L.append("- 当天别的链赚钱的做法: " + "; ".join(f"{x['name']} {x['code']}{x['stock']} {x['pnl']:+.0f}" for x in R["good"][:5]) + "(想一想本导师框架下能不能借)")
    L.append("- **07 必答**(写在正文「根因」一节, contract 加 \"root_causes\": [{\"layer\": \"数据|驱动器|规则|判断|撮合\", \"item\": \"哪一项\", \"fix\": \"改哪里(具体到哪一步 / 哪个规则 / 哪个参数)\", "
             "\"affects\": \"会波及哪些链\", \"replay\": \"用今天数据回放, 改了是否更好(用上面的反事实金额)\"}]): 每个亏损来源都要落到一层, 不许只写\"下次注意\"")
    full = OUT / f"{D}.md"
    L.append(f"- 全部链明细: {full.as_posix()}")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--print", action="store_true")
    a = ap.parse_args()
    R = build(a.date)
    print(render(R) if a.print else f"归因推导链 {a.date}: {len(R['chains'])} 条链, 检测项 {sum(len(c['finds']) for c in R['chains'])} 条, 跨链 {len(R['cross'])} 类 → {OUT / (a.date + '.md')}")
