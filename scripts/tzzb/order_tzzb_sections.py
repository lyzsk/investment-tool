# -*- coding: utf-8 -*-
"""order_tzzb_sections.py — md「### 同花顺投资账本」下的导师小节: 按登记表补齐 + 按日均收益排序 + 无数据占位(10/17 用户定 A13; 零 token)

规则:
  ① 在册导师(scripts/lib/mentors.py, type=tzzb)每人一个「#### 名字」小节; 已有的小节原样搬(含【推测】), 不改内容
  ② 排序 = 日均收益(比赛记录的区间收益 ÷ 净值天数, downloads/tzzb/<id>/nav_daily.json, 截至 D), 高→低; 算不出的排最后
  ③ 没有内容的小节写一行占位, 让人一眼分清"空仓"还是"没抓到":
       账本最新净值日 < D → 「（当日无数据：账本未更新到当天 / 程序未获取；最近一次抓取 MM-DD HH:MM，最新净值日 MM-DD）」
       账本有 D 的净值记录但小节为空 → 「（账本有当天记录，硬数据层待下一轮 check md 生成）」
       D 不在净值记录里但最新净值日 ≥ D → 「（当日账本无记录：导师当天没上传或比赛暂停）」
     只对"D 在该导师数据窗口内"的日子补(窗口开始前的历史 md 不补, 免得满屏占位)
  ④ 不在册的小节(已移除的导师)保留在末尾, 不删
用法: python order_tzzb_sections.py --date 2026-10-19 [--write] | --all [--write] | --selftest
被 check_md_daily.py tzzb_sum 步在 gen_tzzb_md 之后调用(--date D --write)
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import mentors as M  # noqa: E402

SEC = "### 同花顺投资账本"
canon = lambda s: re.sub(r"^#+\s*", "", s).replace(" ", "").lower()
CST = dt.timezone(dt.timedelta(hours=8))


def md_path(d):
    y, m = int(d[:4]), int(d[5:7])
    return ROOT / "md" / f"{y}S{(m - 1) // 3 + 1}" / f"{d}.md"


def nav_info(lid, d):
    """(日均收益 截至 d, 首个净值日, 最新净值日, 最近抓取时间)"""
    base = ROOT / "downloads" / "tzzb" / lid
    try:
        il = json.loads((base / "nav_daily.json").read_text(encoding="utf-8"))["ex_data"]["index_list"]
        n = [(str(x["date"]), float(x["index"])) for x in il if float(x.get("index") or 0) > 0]
    except Exception:   # noqa: BLE001
        n = []
    d8 = d.replace("-", "")
    upto = [x for x in n if x[0] <= d8]
    dm = ((upto[-1][1] / upto[0][1] - 1) / len(upto)) if len(upto) >= 5 else None
    try:
        st = json.loads((base / "state.json").read_text(encoding="utf-8"))
        lf = dt.datetime.fromisoformat(st["lastFetch"].replace("Z", "+00:00")).astimezone(CST).strftime("%m-%d %H:%M")
        last = str(st.get("lastNavDate") or "")
    except Exception:   # noqa: BLE001
        lf, last = "?", (n[-1][0] if n else "")
    return dm, (n[0][0] if n else None), last, lf, {x[0] for x in n}


def split(lines):
    """同花顺小节的行 → (前导行, [(标题, 正文行)])"""
    head, blocks, cur = [], [], None
    for l in lines:
        if l.startswith("#### "):
            cur = [l.strip(), []]
            blocks.append(cur)
        elif cur is None:
            head.append(l)
        else:
            cur[1].append(l)
    return head, blocks


def rebuild(text, d):
    L = text.split("\n")
    try:
        i = L.index(SEC)
    except ValueError:
        return text, "无同花顺小节"
    j = next((k for k in range(i + 1, len(L)) if L[k].startswith("### ") or L[k].startswith("## ")), len(L))
    head, blocks = split(L[i + 1:j])
    have = {canon(h): (h, body) for h, body in blocks}
    d8 = d.replace("-", "")
    out, used, stat = [], set(), {"补": 0, "占位": 0}
    ms = [e for e in M.all() if e["type"] == "tzzb"]
    info = {e["id"]: nav_info(e["id"], d) for e in ms}
    ms.sort(key=lambda e: (info[e["id"]][0] is None, -(info[e["id"]][0] or 0)))
    for e in ms:
        dm, first, last, lf, navset = info[e["id"]]
        k = canon(e["name"])
        h, body = have.get(k, (f"#### {e['name']}", None))
        if not first or d8 < first:   # 数据窗口开始前的历史 md: 不补也不占位, 已有小节原样留在原处顺序
            if body is not None:
                used.add(k)
                out += [h] + body
            continue
        used.add(k)
        if body is None:
            stat["补"] += 1
            body = [""]
        if not any(x.strip() for x in body):
            stat["占位"] += 1
            if d8 in navset:
                ph = "（账本有当天记录，硬数据层待下一轮 check md 生成）"
            elif last and d8 > last:
                ph = f"（当日无数据：账本未更新到当天 / 程序未获取；最近一次抓取 {lf}，最新净值日 {last[4:6]}-{last[6:]}）"
            else:
                ph = "（当日账本无记录：导师当天没上传或比赛暂停）"
            body = ["", ph, ""]
        out += [h] + body
    for h, body in blocks:   # 不在册的小节放末尾, 原样保留
        if canon(h) not in used:
            out += [h] + body
    while out and not out[-1].strip():
        out.pop()
    new = L[:i + 1] + head + out + [""] + L[j:]
    return "\n".join(new), f"补 {stat['补']} / 占位 {stat['占位']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    days = sorted(p.stem for p in (ROOT / "md").glob("20??S?/20??-??-??.md") if p.stem <= dt.date.today().isoformat()) if a.all else [a.date]   # --all 不碰未来日(预建的空 md)
    n = 0
    for d in days:
        p = md_path(d)
        if not p.exists():
            print(f"{d}: 无 md"); continue
        t = p.read_text(encoding="utf-8")
        t2, msg = rebuild(t, d)
        if t2 != t:
            n += 1
            if a.write:
                p.write_text(t2, encoding="utf-8", newline="")
        if not a.all:
            print(f"{d}: {msg}{'(已写)' if a.write and t2 != t else ''}")
    if a.all:
        print(f"共 {len(days)} 个 md, 有变化 {n} 个" + ("(已写)" if a.write else "(dry)"))
    return 0


def selftest():
    global nav_info
    keep = nav_info
    try:
        ms = [e for e in M.all() if e["type"] == "tzzb"]
        a, b = ms[0], ms[1]
        nav_info = lambda lid, d: ((0.02, "20250101", "20261019", "10-19 15:10", {"20261019"}) if lid == a["id"] else (0.01, "20250101", "20261016", "10-17 08:39", set())
                                   if lid == b["id"] else (None, None, "", "?", set()))
        txt = f"## 复盘\n\n{SEC}\n\n#### {b['name']}\n\n内容B\n\n#### 已移除的人\n\n旧内容\n\n## 加红电报\n"
        t2, msg = rebuild(txt, "2026-10-19")
        ia, ib, ix = t2.index(f"#### {a['name']}"), t2.index(f"#### {b['name']}"), t2.index("#### 已移除的人")
        assert ia < ib < ix, "排序或保留末尾错"
        assert "内容B" in t2 and "旧内容" in t2 and "账本有当天记录" in t2, t2
        t3, _ = rebuild(t2, "2026-10-19")
        assert t3 == t2, "不幂等"
        print("ORDER_TZZB SELFTEST PASS")
    finally:
        nav_info = keep


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
