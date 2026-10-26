# -*- coding: utf-8 -*-
"""keep.py — 实盘线留下哪几条(10/24 模块 5; 用户看完盘前汇总后定, 随时可加回 / 收束; hermes / 主会话都调这个)

用法:
  python keep.py 芷影攫心,刘忆青        只留这几条(09:19 起其余休眠: 不叫模型, 已挂的单照样撮合)
  python keep.py 留 1、3、6             按盘前汇总编号(10/25 用户: 微信 / PC3 CLI 说"留1、3、6 skill""暂停 2""恢复 2、4、5")
  python keep.py +做手德融              加回(09:19 后加回的线会立刻按现在的盘面重想一次)
  python keep.py -宣秋财经              收束掉
  python keep.py --reset                清空 = 回到默认(LIVE_DEFAULT_KEEP, 默认入选导师前 3 位)
  python keep.py                        只看现在的名单
  --date D                              默认今天
名字认: 中文名(芷影攫心 / 桃哥…)/ skill id / 线号 live_xxx / 前缀(芷影); 只在当天盘前名单里找
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import live as LV   # noqa: E402
import pack   # noqa: E402


def show(D):
    import skill_names as SN
    sel = pack.live_sel(D)
    k = pack.keep_of(D)
    src = "你挑的" if sel.get("keep") is not None else f"默认(LIVE_DEFAULT_KEEP={pack.flag('LIVE_DEFAULT_KEEP', '3')})"
    L = [f"实盘线 {D} 盘前名单 {len(sel.get('premarket') or [])} 条; 留下({src}):"]
    for i, s in enumerate(sel.get("premarket") or [], 1):
        L.append(f"  {i}. {'✅' if s in k else '💤 暂停'} {SN.cn(s)}skill")
    return "\n".join(L)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--reset", action="store_true")
    a, extra = ap.parse_known_args()   # "-宣秋财经" 会被 argparse 当成选项 → 收进名字
    D = a.date
    raw = " ".join(extra + a.names).strip()
    raw = re.sub(r"\s*skill\s*$", "", raw, flags=re.I).strip()
    for w, sign in (("留下", ""), ("留", ""), ("恢复", "+"), ("加回", "+"), ("暂停", "-"), ("收束", "-"), ("关掉", "-")):   # 口令词 → 动作
        if raw.startswith(w):
            raw = sign + raw[len(w):].strip()
            break
    if a.reset:
        LV.set_keep(D, [], "reset")
    elif raw:
        how = "add" if raw.startswith("+") else "drop" if raw.startswith("-") else "set"
        names = [x for x in re.split(r"[,，、\s+]+", raw.lstrip("+-")) if x and x != "-"]
        ids, bad = LV.resolve(D, names)
        if bad:
            sys.exit(f"认不出: {'、'.join(bad)}(只在今天盘前名单里找)\n" + show(D))
        if not ids:
            sys.exit("没有名字\n" + show(D))
        keep, added, dropped = LV.set_keep(D, ids, how)
        print(f"已改: 新留下 {added or '无'} / 收束 {dropped or '无'}")
    print(show(D))


if __name__ == "__main__":
    main()
