# -*- coding: utf-8 -*-
"""claude_usage_report.py — claude -p 用量日报(零 token, 10/15 建; TODO §3 A14「监控」条)
数据: scripts/lib/claude_cost.csv(claude_call 统一入口: 蒸馏/写 md/早报/反思/画像目录…) + scripts/dfcf/paper/token_log.csv(决策链)
按 tag 归类(冒号后的 UP/skill 名合并)统计当日: 会话数 / 均写缓存 / 均读缓存 / 均输出 / 官方价合计;
单会话 写缓存 >300k 或 读缓存 >5M(≈轮数过多, 读缓存随轮数平方涨) 标红, 列出明细。
输出: scripts/health/reports/claude_usage_<日>.md + stdout 摘要; 被 daily_health.py 调用取 red 数。
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/lib/claude_usage_report.py [--date yyyy-MM-dd]
"""
import argparse, collections, csv, datetime as dt, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CC_RED, CR_RED = 300_000, 5_000_000


def load(date):
    rows = []
    f = ROOT / "scripts" / "lib" / "claude_cost.csv"
    if f.exists():
        for r in csv.DictReader(open(f, encoding="utf-8")):
            # 10/17 健壮性 L3: ts 是本地时间(claude_call.py:171 datetime.now(), 无时区), 不再 +8h
            try:
                local = dt.datetime.fromisoformat(r["ts"]).date().isoformat()
            except ValueError:
                continue
            if local == date:
                rows.append({"tag": r["tag"].split(":")[0], "who": r["tag"], "cc": int(r["cache_create"] or 0), "cr": int(r["cache_read"] or 0),
                             "out": int(r["out_tokens"] or 0), "cost": float(r["cost_usd"] or 0)})
    f = ROOT / "scripts" / "dfcf" / "paper" / "token_log.csv"
    if f.exists():
        d8 = date.replace("-", "")
        for r in csv.DictReader(open(f, encoding="utf-8")):
            if r["date"] != d8 or (r.get("asof") or "0") not in ("0", ""):
                continue
            tag = "chain-0915" if r["slot"] == "0915" else "chain-盘中"
            rows.append({"tag": tag, "who": f"{tag}:{r.get('skill') or '?'}:{r['slot']}:{r['step']}", "cc": int(r.get("cache_create") or 0),
                         "cr": int(r.get("cache_read") or 0), "out": int(r["out_tokens"] or 0), "cost": float(r["cost_usd"] or 0)})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    rows = load(a.date)
    by = collections.defaultdict(list)
    for r in rows:
        by[r["tag"]].append(r)
    reds = [r for r in rows if r["cc"] > CC_RED or r["cr"] > CR_RED]
    L = [f"# claude -p 用量 {a.date}(官方价, 实付按 key 系数折算)", "",
         f"会话 {len(rows)} 个, 合计 ${sum(r['cost'] for r in rows):.1f}; 超线会话 {len(reds)} 个(写缓存>{CC_RED // 1000}k 或 读缓存>{CR_RED // 1_000_000}M)", "",
         "| 类别 | 会话数 | 均写缓存(k) | 均读缓存(k) | 均输出(k) | 合计$ |", "|---|---|---|---|---|---|"]
    for tag, xs in sorted(by.items(), key=lambda kv: -sum(x["cost"] for x in kv[1])):
        n = len(xs)
        L.append(f"| {tag} | {n} | {sum(x['cc'] for x in xs) / n / 1000:.0f} | {sum(x['cr'] for x in xs) / n / 1000:.0f} | {sum(x['out'] for x in xs) / n / 1000:.1f} | {sum(x['cost'] for x in xs):.1f} |")
    if reds:
        L += ["", "## 超线会话", "| 会话 | 写缓存(k) | 读缓存(k) | 输出(k) | $ |", "|---|---|---|---|---|"]
        for r in sorted(reds, key=lambda x: -x["cost"])[:30]:
            L.append(f"| {r['who']} | {r['cc'] / 1000:.0f} | {r['cr'] / 1000:.0f} | {r['out'] / 1000:.1f} | {r['cost']:.2f} |")
    out = ROOT / "scripts" / "health" / "reports" / f"claude_usage_{a.date}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:4 + 2 + len(by)]))
    print("JSON:" + json.dumps({"sessions": len(rows), "cost": round(sum(r["cost"] for r in rows), 2), "red": len(reds), "report": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
