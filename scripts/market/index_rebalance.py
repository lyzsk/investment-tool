# -*- coding: utf-8 -*-
"""index_rebalance.py — 指数成分 / 行业时点表的动态更新调度(2026-10-17 建, TODO A7; 零 token, 纯机械)

为什么: 指数调样有公告与固定日历, 表(index_constituent / stock_industry / index_constituent_coverage)要跟着生效日更新, 不再手动。
三道触发(任一命中 → 当天收盘后刷新):
  ① 财联社加红电报(库 cls_telegraph, 只读): 含"指数" + "样本/成分" + "调整", 抽出生效日(如"6月12日收市后生效""于9月11日收市后生效"
     "6月15日对深证成指…实施样本股定期调整"); 事件落 downloads/market/index_pit/rebalance_events.json(去重, 带电报原句)
  ② 日历兜底: 中证 / 上证系 6 月、12 月第二个星期五收市后生效; 深证系随后的星期一实施
  ③ 每周六对账: 重抓官网当前名单与库比对(防漏公告/临时调整)
刷新 = index_constituents.py fetch --refresh → build → import --commit --incremental(按自然键增 / 改 / 软删, 一个事务)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/market/index_rebalance.py scan [--days 30] | due [--date D] | run [--date D] [--force] [--dry]
  scan: 只扫电报更新事件表; due: 打印今天该不该刷新及原因; run: scan + 该刷新就刷新(check md --only index_pit 调这个)
出口: 0=正常(刷新成功或今天不用刷新) 1=刷新失败 4=刷新完成但有提醒(增改删异常大)
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVENTS = ROOT / "downloads" / "market" / "index_pit" / "rebalance_events.json"
PY = str(ROOT / "scripts" / "venv" / "Scripts" / "python.exe")
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
KW_RE = re.compile(r"指数")
ADJ_RE = re.compile(r"(样本|成分股?|成份股?)[^。；\n]{0,20}调整|调整[^。；\n]{0,24}(样本|成分|成份)")
DATE_RES = [re.compile(r"(\d{1,2})月(\d{1,2})日收市后生效"), re.compile(r"于(\d{1,2})月(\d{1,2})日(?:收市后|正式)?(?:生效|实施)"),
            re.compile(r"(\d{1,2})月(\d{1,2})日对[^。；\n]{0,40}?实施样本股?定期调整")]


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] {m}", flush=True)


def load_events():
    try:
        return json.loads(EVENTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def scan(days):
    """扫近 N 天加红电报 → 事件表(去重); 返回新增条数"""
    sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
    import manual_backfill as mb   # noqa: PLC0415  (只读查询)
    cur = mb.db().cursor()
    cur.execute("select publish_time, content from cls_telegraph where is_deleted=0 and publish_time >= %s and content like %s",
                (dt.datetime.now() - dt.timedelta(days=days), "%指数%"))
    ev = load_events()
    seen = {(e["effective"], e["sentence"]) for e in ev}
    n = 0
    for pt, content in cur.fetchall():
        for sent in re.split(r"[。；\n]", content or ""):
            if not (KW_RE.search(sent) and ADJ_RE.search(sent)):
                continue
            for rx in DATE_RES:
                m = rx.search(sent)
                if not m:
                    continue
                mo, d = int(m.group(1)), int(m.group(2))
                y = pt.year + (1 if mo < pt.month - 6 else 0)
                try:
                    eff = dt.date(y, mo, d).isoformat()
                except ValueError:
                    continue
                k = (eff, sent.strip()[:200])
                if k in seen:
                    break
                seen.add(k)
                ev.append({"effective": eff, "sentence": k[1], "telegraph_time": pt.isoformat(sep=" ")[:19], "found_at": dt.datetime.now().isoformat(timespec="seconds")})
                n += 1
                break
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    EVENTS.write_text(json.dumps(sorted(ev, key=lambda e: e["effective"]), ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def calendar_dates(year):
    """中证/上证: 6、12 月第二个星期五; 深证: 随后星期一"""
    out = {}
    for mo in (6, 12):
        d = dt.date(year, mo, 1)
        fridays = [d + dt.timedelta(days=i) for i in range(31) if (d + dt.timedelta(days=i)).month == mo and (d + dt.timedelta(days=i)).weekday() == 4]
        f2 = fridays[1]
        out[f2.isoformat()] = f"日历: 中证/上证系 {mo} 月第二个星期五收市后生效"
        out[(f2 + dt.timedelta(days=3)).isoformat()] = f"日历: 深证系 {mo} 月定期调整(第二个星期五后的星期一)"
    return out


def due(day):
    """今天要不要刷新 → (bool, [原因])"""
    why = [f"电报事件: {e['sentence'][:60]}" for e in load_events() if e["effective"] == day.isoformat()]
    cal = calendar_dates(day.year).get(day.isoformat())
    if cal:
        why.append(cal)
    if day.weekday() == 5:
        why.append("每周六对账(防漏公告/临时调整)")
    return bool(why), why


def refresh(dry):
    steps = [["fetch", "--refresh"], ["build"], ["import", "--commit", "--incremental"]]
    out = []
    for s in steps:
        cmd = [PY, "-X", "utf8", str(ROOT / "scripts" / "market" / "index_constituents.py"), *s]
        if dry:
            log("dry: " + " ".join(s))
            continue
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN, timeout=3600)
        tail = [l for l in (r.stdout or "").splitlines() if l.strip()][-4:]
        log(f"{' '.join(s)} rc={r.returncode}: " + " | ".join(tail) + (f" ERR {(r.stderr or '')[-300:]}" if r.returncode else ""))
        if r.returncode != 0:
            return 1, out
        out += tail
    return 0, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["scan", "due", "run"])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--date")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    day = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    if a.action in ("scan", "run"):
        log(f"电报扫描近 {a.days} 天: 新增事件 {scan(a.days)}; 事件表 {EVENTS.relative_to(ROOT)}")
    ok, why = due(day)
    log(f"{day} {'要刷新' if ok else '不用刷新'}: {'; '.join(why) or '无事件/非日历日/非周六'}")
    if a.action != "run" or not (ok or a.force):
        print("JSON:" + json.dumps({"date": day.isoformat(), "due": ok, "why": why}, ensure_ascii=False))
        return 0
    rc, tail = refresh(a.dry)
    warn = 0
    for l in tail:   # "index_constituent: 增 x / 改 y / 软删 z(库里原有效 n 行)" 变动超过 20% 提醒
        m = re.search(r"增 (\d+) / 改 (\d+) / 软删 (\d+)\(库里原有效 (\d+)", l)
        if m and int(m.group(4)) and (int(m.group(1)) + int(m.group(2)) + int(m.group(3))) > 0.2 * int(m.group(4)):
            warn = 4
    print("JSON:" + json.dumps({"date": day.isoformat(), "due": True, "why": why, "rc": rc, "warn": bool(warn)}, ensure_ascii=False))
    return rc or warn


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
