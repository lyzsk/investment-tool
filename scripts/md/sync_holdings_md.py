# -*- coding: utf-8 -*-
"""md/sync_holdings_md.py — 把当天收盘持仓的股票名补进当天 md 的「## 复盘 / ### 复盘持仓」(10/28 晚用户令; 零 token)

来源: scripts/dfcf/snapshots/<D>_成交_*.txt 的「持仓(收盘):」行(没有就读券商持仓原表: 序 代码 名称 持仓数量 …, 数量 > 0)
写法: 每只一行 `#### <股票名> | ` + 空行(和用户手写同格式; Java inheritHoldingsFromPrevious 认这个格式);
      只补缺的, 用户已写的(含多写的)一律不动不删; **只写名字, 不写数量 / 金额**(隐私立法: md 进 git)
用法: python sync_holdings_md.py [--date yyyy-MM-dd] [--dry]   出口 0 = 成功或无需改 1 = 没快照 / 没 md / 没「### 复盘持仓」节
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAP = ROOT / "scripts" / "dfcf" / "snapshots"
SKIP = ("GC001", "204001", "131810", "SZRQ88")   # 逆回购 = 现金


def held_names(D):
    """→ [股票名](收盘持仓数量 > 0, 按快照里的顺序); 没快照 → None"""
    fs = sorted(SNAP.glob(f"{D}_成交_*.txt"))
    if not fs:
        return None
    t = fs[-1].read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^持仓\(收盘\)[:：](.*)$", t, re.M)
    out = []
    if m:
        for part in m.group(1).split(";"):
            g = re.match(r"\s*(\S+)\s+(\d{6})\s+(\d+)\s+成本", part)
            if g and int(g.group(3)) > 0 and g.group(2) not in SKIP:
                out.append(g.group(1))
        return out
    for l in t.splitlines():   # 券商持仓原表: 序 代码 名称 持仓数量 可用数量 成本价 …
        w = l.split()
        if len(w) >= 5 and w[0].isdigit() and len(w[0]) <= 3 and re.fullmatch(r"\d{6}", w[1]) and w[3].isdigit() and int(w[3]) > 0 and w[1] not in SKIP:
            out.append(w[2])
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    names = held_names(a.date)
    if names is None:
        print(f"{a.date} 没有成交快照, 跳过")
        return 1
    mds = sorted((ROOT / "md").glob(f"*/{a.date}.md"))
    if not mds:
        print(f"{a.date} 没有 md")
        return 1
    p = mds[-1]
    L = p.read_text(encoding="utf-8").split("\n")
    try:
        i0 = next(i for i, l in enumerate(L) if l.strip() == "### 复盘持仓")
    except StopIteration:
        print(f"{p.name} 没有「### 复盘持仓」节")
        return 1
    i1 = next((i for i in range(i0 + 1, len(L)) if L[i].startswith(("### ", "## "))), len(L))
    have = {re.sub(r"\s*\|.*$", "", l[5:]).strip() for l in L[i0 + 1:i1] if l.startswith("#### ")}
    add = [n for n in names if n not in have]
    if not add:
        print(f"{p.name} 复盘持仓已齐: {'、'.join(names) or '(空仓)'}")
        return 0
    last = max([i for i in range(i0 + 1, i1) if L[i].startswith("#### ")], default=i0)
    block = []
    for n in add:
        block += [f"#### {n} | ", ""]
    pos = last + 2 if last > i0 and last + 1 < len(L) and L[last + 1].strip() == "" else last + 1
    if last == i0:   # 节里还没有任何持仓行: 标题后空一行再写
        pos = i0 + 1
        block = [""] + block if L[i0 + 1].strip() != "" else block
        pos = i0 + 2 if L[i0 + 1].strip() == "" else i0 + 1
    L[pos:pos] = block
    if not a.dry:
        p.write_text("\n".join(L), encoding="utf-8")
    print(f"{p.name} 复盘持仓补 {len(add)} 只: {'、'.join(add)}{'(dry)' if a.dry else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
