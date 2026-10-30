"""sync_watchlist.py — 用户盯盘名单 watchlist.txt 跟真实持仓走(10/29 建)

10/29 盘前发现 watchlist.txt 还停在 10/26 的持仓, live_watch 09:10 盯的是旧票 → 启动时先用
pack.real_start(和实盘线同一份收盘快照)重写; 中国银行等 LIVE_EXCLUDE 也算(用户盯盘要看), 逆回购不算.
没有快照 / 读失败 → 不动旧文件, 退出码 1. 隐私: watchlist.txt 在 snapshots(已 gitignore).
用法: python -X utf8 scripts/dfcf/sync_watchlist.py [--date yyyy-MM-dd] [--dry]
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "paper_line"), str(ROOT / "scripts"), str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "tzzb")]
WL = ROOT / "scripts" / "dfcf" / "snapshots" / "live" / "watchlist.txt"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    import pack
    pack.LIVE_EXCLUDE = set()   # 实盘线去掉中国银行, 盯盘不去
    rs = pack.real_start(a.date)
    if not rs or not rs.get("positions"):
        print(f"sync_watchlist: {a.date} 之前没有可用的收盘持仓快照, watchlist.txt 不动")
        return 1
    codes = list(rs["positions"])
    old = WL.read_text(encoding="utf-8").strip() if WL.exists() else ""
    new = ",".join(codes)
    if old == new:
        print(f"sync_watchlist: 持仓(快照 {rs['from']})和 watchlist.txt 一致, 不改")
        return 0
    print(f"sync_watchlist: {old or '(空)'} → {new}(快照 {rs['from']})")
    if not a.dry:
        WL.write_text(new + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
