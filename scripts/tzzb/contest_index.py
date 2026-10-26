# -*- coding: utf-8 -*-
"""contest_index.py — tzzb 实盘比赛本地索引(10/25 用户: 把热门比赛存在本地某个路径 + 每个选手的来源链接, 方便人工看; 零网络, 只读本地已拉的榜单)

读: scripts/tzzb/match_keys.json(比赛 key 清单 + 用户给的来源说明) + downloads/tzzb/_ranks/<key>.json(总榜快照, rank_screen.py fetch-rank 拉的)
写: docs/tzzb/contests.md —— 每场: key / 用户给的来源 / 本地榜单文件 / 拉取时间 / 人数 / 前 30 名(名次 · 选手 · 总收益 · 仓位 · 入场日 · 主页链接)
    主页链接 = https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=<比赛key>&user_key=<选手key>(手机 / 电脑浏览器都能打开)
用法: python contest_index.py [--top 30]
"""
import argparse
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEYS = ROOT / "scripts" / "tzzb" / "match_keys.json"
RANKS = ROOT / "downloads" / "tzzb" / "_ranks"
OUT = ROOT / "docs" / "tzzb" / "contests.md"
HOME = "https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key={k}&user_key={u}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=30)
    a = ap.parse_args()
    j = json.loads(KEYS.read_text(encoding="utf-8"))
    src = {k: "用户最早给的(10/07 前)" for k in j.get("known", [])}
    for x in j.get("new_1016", []):
        if isinstance(x, dict):
            src[x["key"]] = x.get("from", "")
    L = [f"# tzzb 实盘比赛本地索引（{dt.date.today()} 生成；零网络，读本地已拉的榜单）", "",
         "> 脚本 `scripts/tzzb/contest_index.py`；榜单原文件 `downloads/tzzb/_ranks/<比赛key>.json`（`scripts/tzzb/rank_screen.py fetch-rank` 拉）；比赛 key 清单 `scripts/tzzb/match_keys.json`。",
         "> 选手主页 = 同花顺投资账本网页，点开能看他的持仓 / 调仓 / 净值。**榜单是拉取那天的快照，不是今天的**（见每场的拉取时间）。", "",
         "| 比赛 key | 来源 | 本地文件 | 拉取时间 | 人数 |", "|---|---|---|---|---|"]
    blocks = []
    for k in list(dict.fromkeys(list(src) + [p.stem for p in RANKS.glob("*.json")])):
        f = RANKS / f"{k}.json"
        if not f.exists():
            L.append(f"| {k} | {src.get(k, '')} | （还没拉） | - | - |")
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        rows = d.get("rows") or []
        L.append(f"| {k} | {src.get(k, '')} | `downloads/tzzb/_ranks/{k}.json` | {str(d.get('fetched_at', ''))[:16]} | {len(rows)} |")
        rows = sorted(rows, key=lambda r: int(r.get("show_rank_index") or 10 ** 9))[:a.top]
        blocks += ["", f"## {k}（{src.get(k, '')}）前 {len(rows)} 名", "", "| 名次 | 选手 | 总收益 | 仓位 | 入场日 | 主页 |", "|---|---|---|---|---|---|"]
        for r in rows:
            tp = r.get("total_profit_rate")
            pr = r.get("position_rate")
            blocks.append(f"| {r.get('show_rank_index')} | {r.get('user_name')} | {float(tp) * 100:+.1f}% | {float(pr) * 100:.0f}% | {r.get('enter_date', '')} | "
                          f"[打开]({HOME.format(k=k, u=r.get('user_key'))}) |" if tp not in (None, "") and pr not in (None, "") else
                          f"| {r.get('show_rank_index')} | {r.get('user_name')} | - | - | {r.get('enter_date', '')} | [打开]({HOME.format(k=k, u=r.get('user_key'))}) |")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L + blocks) + "\n", encoding="utf-8")
    print("→", OUT, len(L) - 6, "场")


if __name__ == "__main__":
    main()
