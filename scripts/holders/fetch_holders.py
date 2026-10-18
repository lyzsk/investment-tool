# -*- coding: utf-8 -*-
"""fetch_holders.py — 十大流通股东 + 个人股东(牛散)协同统计 原料抓取 / 规范化(2026-10-17 建, TODO A5 一期; 零 token)

方案与数据源实测: docs/research/fund_holder_sources_20261017.md
三段(互相独立, 可分别重跑):
  fetch [--kind freeholders,coop] [--periods 8 | --period 2026-06-30] [--codes 603986,...]
        主源 东财 datacenter(按报告期整期分页, 每页 500 行): 逐页落盘 downloads/holders/<kind>/<报告期>/p001.json, 已有的不重拉(断了重跑即续);
        一期完整(实到行数 = 接口 count) 且已过法定披露截止日 + 7 天 → 写 DONE + manifest.json; 未过截止日(还在陆续披露)只写 manifest(PARTIAL), 下次重拉
        --codes: 按股票补抓(备源 新浪 vCI_CirculateStockHolder, 主源整期失败/个别票缺失时用) → downloads/holders/sina_freeholders/<代码>.json
  build 零请求: 原料 → downloads/holders/norm/freeholders_<报告期>.jsonl / coop_<报告期>.jsonl(字段统一, 个人股东名归一)
  status 打印各期完整度(给 check md / daily_health 用); 出口 0=全部完整或在披露期内 4=有缺页/失败(提醒)
健壮性: 全部请求走 scripts/lib/req_guard(源 em_datacenter / sina: 限速+抖动+熔断+日预算+失败分类, 跨进程共享);
        失败分类: BLOCKED/RATE_LIMIT=熔断后本轮停(已落盘的不丢, 下轮续) / NO_DATA=本期未披露(不算失败) / PARSE=原文存 _bad/ 便于排查;
        单页失败不拖垮整期, 记 manifest.missing; 每次请求后 sleep 2.5~3.5s(≤0.4 次/秒), 不碰东财 push2
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/holders/fetch_holders.py fetch|build|status [...]
"""
import argparse
import datetime as dt
import json
import random
import re
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from req_guard import ReqError, gfetch  # noqa: E402

OUT = ROOT / "downloads" / "holders"
API = "https://datacenter-web.eastmoney.com/api/data/v1/get?"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
     "Referer": "https://data.eastmoney.com/"}
PAGE = 500
KINDS = {
    "freeholders": dict(report="RPT_F10_EH_FREEHOLDERS", sort=("UPDATE_DATE,SECURITY_CODE,HOLDER_RANK", "-1,1,1"), extra=""),
    "coop": dict(report="RPT_COOPFREEHOLDERS_ANALYSIS", sort=("STATISTICS_TIMES,COOPERATION_HOLDER_MARK", "-1,-1"),
                 extra='(HOLDNUM_CHANGE_TYPE="001")(HOLDER_TYPE="个人")'),
}


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] {m}", flush=True)


def periods(n, today=None):
    """最近 n 个季末(≤ 今天)"""
    today = today or dt.date.today()
    out, y, q = [], today.year, (today.month - 1) // 3   # q=当前季之前已结束的季数
    while len(out) < n:
        if q == 0:
            y, q = y - 1, 4
        md = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}[q]
        out.append(f"{y}-{md}")
        q -= 1
    return out


def deadline(period):
    """法定披露截止: 一季报 4/30, 中报 8/31, 三季报 10/31, 年报 次年 4/30"""
    y, md = int(period[:4]), period[5:]
    return {"03-31": dt.date(y, 4, 30), "06-30": dt.date(y, 8, 31), "09-30": dt.date(y, 10, 31), "12-31": dt.date(y + 1, 4, 30)}[md]


def page_url(kind, period, page):
    k = KINDS[kind]
    q = {"sortColumns": k["sort"][0], "sortTypes": k["sort"][1], "pageSize": str(PAGE), "pageNumber": str(page), "reportName": k["report"],
         "columns": "ALL", "source": "WEB", "client": "WEB", "filter": f"(END_DATE='{period}')" + k["extra"]}
    return API + urllib.parse.urlencode(q)


def get_json(url, source):
    """一次请求 → (json|None, 失败类型|None); 不抛"""
    try:
        r = gfetch(url, source=source, headers=H, timeout=30)
    except ReqError as e:   # 熔断/限流/日预算: 守卫没发请求
        return None, getattr(e, "kind", "RATE_LIMIT")
    except Exception as e:   # noqa: BLE001
        return None, f"UNAVAILABLE:{str(e)[:80]}"
    finally:
        time.sleep(random.uniform(2.5, 3.5))
    if r.status in (403, 429):
        return None, "BLOCKED"
    if r.status != 200:
        return None, f"UNAVAILABLE:{r.status}"
    try:
        t = r.text()
        return json.loads(t[t.find("{"):t.rfind("}") + 1]), None
    except Exception:   # noqa: BLE001
        bad = OUT / "_bad"
        bad.mkdir(parents=True, exist_ok=True)
        (bad / f"{int(time.time())}.txt").write_text((r.text() or "")[:20000], encoding="utf-8")
        return None, "PARSE"


def fetch_period(kind, period):
    d = OUT / kind / period
    d.mkdir(parents=True, exist_ok=True)
    if (d / "DONE").exists():
        return "DONE(已完整)"
    open_period = dt.date.today() <= deadline(period) + dt.timedelta(days=7)
    first = d / "p001.json"
    j, err = (json.loads(first.read_text(encoding="utf-8")), None) if first.exists() and not open_period else get_json(page_url(kind, period, 1), "em_datacenter")
    if err:
        return f"首页失败 {err}"
    res = (j or {}).get("result") or {}
    if not res or not res.get("count"):
        (d / "manifest.json").write_text(json.dumps({"kind": kind, "period": period, "count": 0, "status": "NO_DATA", "at": dt.datetime.now().isoformat(timespec="seconds")},
                                                    ensure_ascii=False, indent=1), encoding="utf-8")
        return "NO_DATA(本期还没披露)"
    first.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
    pages, count, missing, stop = int(res.get("pages") or 1), int(res["count"]), [], None
    for p in range(2, pages + 1):
        f = d / f"p{p:03d}.json"
        if f.exists() and not open_period:
            continue
        jj, err = get_json(page_url(kind, period, p), "em_datacenter")
        if err:
            missing.append(p)
            if err in ("BLOCKED", "RATE_LIMIT") or err.startswith("UNAVAILABLE"):
                stop = err
                missing += list(range(p + 1, pages + 1))
                break
            continue
        f.write_text(json.dumps(jj, ensure_ascii=False), encoding="utf-8")
    rows = sum(len(((json.loads(f.read_text(encoding="utf-8")).get("result") or {}).get("data")) or []) for f in d.glob("p*.json"))
    status = "PARTIAL_OPEN" if open_period else ("COMPLETE" if rows >= count and not missing else "INCOMPLETE")
    man = {"kind": kind, "period": period, "count": count, "pages": pages, "rows": rows, "missing": missing, "stopped_by": stop, "status": status,
           "deadline": deadline(period).isoformat(), "source": "em_datacenter", "at": dt.datetime.now().isoformat(timespec="seconds")}
    (d / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    if status == "COMPLETE":
        (d / "DONE").write_text(man["at"], encoding="utf-8")
    return f"{status} 行 {rows}/{count} 页 {pages}" + (f" 缺 {len(missing)} 页({stop or '个别失败'})" if missing else "")


def sina_freeholders(code):
    """备源: 新浪个股流通股东页(含历史多期) → [{period, notice, rank, holder, hold_num, ratio, nature}]"""
    url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CirculateStockHolder/stockid/{code}.phtml"
    try:
        r = gfetch(url, source="sina", headers={"User-Agent": H["User-Agent"]}, timeout=20)
    except Exception as e:   # noqa: BLE001
        return None, f"UNAVAILABLE:{str(e)[:60]}"
    finally:
        time.sleep(random.uniform(2.0, 3.0))
    if r.status != 200:
        return None, f"UNAVAILABLE:{r.status}"
    t = r.content.decode("gbk", errors="replace")
    i = t.find("CirculateShareholderTable")
    if i < 0:
        return None, "PARSE"
    import html as _h
    cells = [c.strip() for c in _h.unescape(re.sub(r"<[^>]+>", "|", t[i:t.find("</table>", i)])).split("|") if c.strip() and c.strip() != "-->"]
    out, per, notice = [], None, None
    k = 0
    while k < len(cells):
        c = cells[k]
        nxt = cells[k + 1] if k + 1 < len(cells) else ""
        isd = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", nxt))
        if c == "截止日期":
            per, notice = (nxt if isd else None), None; k += 2 if isd else 1; continue
        if c == "公告日期":
            notice = nxt if isd else None; k += 2 if isd else 1; continue
        if per and c.isdigit() and k + 4 < len(cells) and re.fullmatch(r"[\d.]+", cells[k + 3] or ""):
            out.append({"period": per, "notice": notice, "rank": int(c), "holder": cells[k + 1], "hold_num": float(cells[k + 2]) if re.fullmatch(r"[\d.]+", cells[k + 2]) else None,
                        "ratio": float(cells[k + 3]), "nature": cells[k + 4]})
            k += 5; continue
        k += 1
    return (out, None) if out else (None, "NO_DATA")


def cmd_fetch(a):
    kinds = a.kind.split(",")
    if a.codes:
        d = OUT / "sina_freeholders"
        d.mkdir(parents=True, exist_ok=True)
        for c in a.codes.split(","):
            rows, err = sina_freeholders(c.strip())
            if rows:
                (d / f"{c.strip()}.json").write_text(json.dumps({"code": c.strip(), "source": "sina", "at": dt.datetime.now().isoformat(timespec="seconds"), "rows": rows},
                                                                ensure_ascii=False), encoding="utf-8")
            log(f"新浪备源 {c}: {len(rows) if rows else 0} 行 {err or ''}")
        return 0
    pers = [a.period] if a.period else periods(a.periods)
    bad = 0
    for kind in kinds:
        for p in pers:
            r = fetch_period(kind, p)
            log(f"{kind} {p}: {r}")
            if r.startswith(("首页失败", "INCOMPLETE")) or "缺 " in r:
                bad += 1
                if "BLOCKED" in r or "RATE_LIMIT" in r:
                    log("东财 datacenter 熔断/限流, 本轮停(已落盘的保留, 下轮续)")
                    return 4
    return 4 if bad else 0


def norm_name(s):
    return re.sub(r"\s+", "", str(s or "")).replace("（", "(").replace("）", ")")


def cmd_build(a):
    nd = OUT / "norm"
    nd.mkdir(parents=True, exist_ok=True)
    for kind in KINDS:
        for d in sorted((OUT / kind).glob("*-*-*")):
            rows = []
            for f in sorted(d.glob("p*.json")):
                rows += ((json.loads(f.read_text(encoding="utf-8")).get("result") or {}).get("data")) or []
            if kind == "freeholders":
                keep = [{"period": d.name, "code": r.get("SECURITY_CODE"), "name": r.get("SECURITY_NAME_ABBR"), "rank": r.get("HOLDER_RANK"),
                         "holder": norm_name(r.get("HOLDER_NAME")), "holder_new": norm_name(r.get("HOLDER_NEW") or r.get("HOLDER_NAME")),
                         "holder_type": r.get("HOLDER_TYPE"), "hold_num": r.get("HOLD_NUM"), "free_ratio": r.get("FREE_HOLDNUM_RATIO"),
                         "mkt_cap": r.get("HOLDER_MARKET_CAP"), "change": r.get("HOLDNUM_CHANGE_NAME") or r.get("HOLD_NUM_CHANGE"),
                         "notice": str(r.get("UPDATE_DATE") or "")[:10]} for r in rows]
            else:
                keep = [{"period": d.name, "holder": norm_name(r.get("HOLDER_NAME")), "times": r.get("STATISTICS_TIMES"),
                         **{k.lower(): r.get(k) for k in ("AVG_CHANGE_10TD", "AVG_CHANGE_30TD", "AVG_CHANGE_60TD", "MAX_CHANGE_30TD", "MIN_CHANGE_30TD")},
                         "stocks": r.get("SEAB_JOIN")} for r in rows]
            (nd / f"{kind}_{d.name}.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in keep), encoding="utf-8")
            log(f"build {kind} {d.name}: {len(keep)} 行")
    return 0


def cmd_status(a):
    bad = 0
    for kind in KINDS:
        for p in periods(a.periods):
            m = OUT / kind / p / "manifest.json"
            j = json.loads(m.read_text(encoding="utf-8")) if m.exists() else {"status": "未抓"}
            ok = j["status"] in ("COMPLETE", "PARTIAL_OPEN", "NO_DATA")
            bad += 0 if ok else 1
            log(f"{kind} {p}: {j['status']} 行 {j.get('rows', '-')}/{j.get('count', '-')} 缺页 {len(j.get('missing') or [])}")
    print("JSON:" + json.dumps({"bad": bad}))
    return 4 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["fetch", "build", "status"])
    ap.add_argument("--kind", default="freeholders,coop")
    ap.add_argument("--periods", type=int, default=8)
    ap.add_argument("--period")
    ap.add_argument("--codes")
    a = ap.parse_args()
    return {"fetch": cmd_fetch, "build": cmd_build, "status": cmd_status}[a.action](a)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
