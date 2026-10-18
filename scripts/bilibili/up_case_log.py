# -*- coding: utf-8 -*-
"""up_case_log.py — B站 UP(桃哥 / 趋势天哥 / 卢本圆)逐日"操作日志卡"(零 token; 10/18 晚用户定: UP 也能像 tzzb 一样做日卡)

为什么: UP 的买卖原来只进 md「今日操作」一段文字 → 统计指纹; 没有逐日卡, 蒸馏 / 解读读不到"当天的画面 + 行情 + 他的原话"。
        UP 比 tzzb 多一样最值钱的东西: 视频里他亲口讲为什么买卖(转写稿) = 真实动机标签。
数据(全部已在盘上, 只读):
  md/**/<日>.md 的 UP 小节「今日操作」           口述 + 抽帧核销后的操作(解析复用 up_fingerprint.parse_items: 方向 / 打法 / 时段 / 卢本圆回顾前几天的按口述日期)
  results/bilibili/<mid>/<YYYY.MM.DD>/*.vision.json  抽帧 Vision 2.0 的 pages: BS买卖点(股票 + "B点在 x 附近") / 持仓快照 / 持仓高亮(紫色名 = 持仓, 像素级)
  results/bilibili/<mid>/<YYYY.MM.DD>/*.txt          转写稿(纠错后): 提到该票的原话, 每票最多 2 句
  行情库 kline_day: 当日开 / 高 / 低 / 收、BS 价位在当日区间的位置; 次日收盘(明确标「结果(次日)」, 唯一后见信息)
校验(宁缺毋错): 画面 BS 价位必须落在当天最低~最高 ±1% 内, 否则标「价位对不上日线, 存疑」; 名称→代码 用 md 操作里出现过的 + scripts/models/stock_dict.json
视频日期 → 交易日: 文件夹日期当天是交易日就用当天, 否则用之前最近的交易日(周末复盘 = 周五)
产物: skills/<up>-skill/persona/case_log/<YYYY-MM>.md + index.md(格式同 tzzb 日卡; 目录只归本脚本, 幂等)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/bilibili/up_case_log.py [--up taoge,lubenyuan,qushitiange] [--dry]
"""
import argparse
import bisect
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
import up_fingerprint as UF   # noqa: E402
import mentors as M           # noqa: E402
import a_rules as AR          # noqa: E402
from kline_db import db       # noqa: E402

MID = {"taoge": "625315686", "qushitiange": "1372241958", "lubenyuan": "550494308"}
WD = "一二三四五六日"
PX = re.compile(r"([BS])点[在于]?\s*([0-9]+(?:\.[0-9]+)?)")


def pc(x, d=1):
    return "?" if x is None else f"{x * 100:+.{d}f}%"


def name_map(rows):
    m = {}
    try:
        m.update({k: v[2:] for k, v in json.loads((ROOT / "scripts" / "models" / "stock_dict.json").read_text(encoding="utf-8")).items()})
    except (OSError, ValueError):
        pass
    for r in rows:
        if r.get("name"):
            m[r["name"]] = r["code"]
    return m


def load_k(codes, d0, d1):
    c = db()
    try:
        cur = c.cursor()
        K = collections.defaultdict(dict)
        syms = {AR.symbol(x): x for x in codes if AR.symbol(x)}
        syms["sh000001"] = "IDX"
        L = list(syms)
        for i in range(0, len(L), 500):
            part = L[i:i + 500]
            cur.execute(f"select symbol, trade_date, cast(open as double), cast(high as double), cast(low as double), cast(close as double), cast(pre_close as double) "
                        f"from kline_day where is_deleted=0 and trade_date between %s and %s and symbol in ({','.join(['%s'] * len(part))})", [d0, d1, *part])
            for s, d, o, h, l, cl, p in cur.fetchall():
                K[syms[s]][str(d)] = (o, h, l, cl, p)
        return K
    finally:
        c.close()


def videos(up, cal):
    """交易日 → [{bvid, bs:[(股票, B/S, 价)], hold:[名称], held:[名称], txt:[行]}]"""
    out = collections.defaultdict(list)
    base = ROOT / "results" / "bilibili" / MID[up]
    if not base.exists():
        return out
    for vf in sorted(base.glob("*/*.vision.json")):
        try:
            fd = dt.date(*map(int, vf.parent.name.split("."))).isoformat()
            doc = json.loads(vf.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        i = bisect.bisect_right(cal, fd) - 1
        if i < 0:
            continue
        D = cal[i]
        p = doc.get("pages") or {}
        bs = []
        for x in p.get("BS买卖点") or []:
            for side, px in PX.findall(str(x.get("描述") or "")):
                k = (x.get("股票"), side, float(px))
                if x.get("股票") and k not in bs:
                    bs.append(k)
        hold = [h.get("名称") for h in ((p.get("持仓快照") or {}).get("明细") or []) if h.get("名称")]
        held = [h.get("名称") for h in (p.get("持仓高亮") or []) if h.get("名称") and (h.get("紫帧") or 0) > (h.get("灰帧") or 0)]
        tf = vf.with_name(vf.name.replace(".vision.json", ".txt"))
        txt = tf.read_text(encoding="utf-8").splitlines() if tf.exists() else []
        out[D].append({"bvid": vf.name.split(".")[0], "bs": bs, "hold": hold, "held": held, "txt": txt})
    return out


def quotes(txt, name, n=2):
    q = [l.strip() for l in txt if name and name[:2] in l and len(l.strip()) >= 6]
    return [l[:90] for l in q[:n]]


def build(up):
    rows, _ = UF.collect(up)
    nm = name_map(rows)
    c = db()
    try:
        cur = c.cursor()
        cur.execute("select trade_date from kline_day where symbol='sh000001' and is_deleted=0 and trade_date>='2025-06-01' order by trade_date")
        cal = [str(r[0]) for r in cur.fetchall()]
    finally:
        c.close()
    V = videos(up, cal)
    ops = collections.defaultdict(list)
    for r in rows:
        ops[r["date"]].append(r)
    days = sorted(set(ops) | set(V))
    if not days:
        return []
    codes = {r["code"] for r in rows} | {nm[n] for v in V.values() for x in v for n in [b[0] for b in x["bs"]] + x["hold"] + x["held"] if n in nm}
    K = load_k(codes, (dt.date.fromisoformat(days[0]) - dt.timedelta(days=10)).isoformat(), (dt.date.fromisoformat(days[-1]) + dt.timedelta(days=10)).isoformat())
    nxt = lambda d: cal[bisect.bisect_right(cal, d)] if bisect.bisect_right(cal, d) < len(cal) else None   # noqa: E731
    cards = []
    for D in days:
        if D not in K["IDX"]:
            continue
        ix = K["IDX"][D]
        L, tags = [f"- 大盘: 上证 收{pc(ix[3] / ix[4] - 1, 2)}"], []
        txt = [l for v in V.get(D, []) for l in v["txt"]]
        N = nxt(D)
        if ops.get(D):
            L.append("- 口述操作(md 今日操作):")
            for r in ops[D]:
                k = K.get(r["code"], {}).get(D)
                kn = K.get(r["code"], {}).get(N) if N else None
                tags.append(f"{r['side']}·{r['play']}" if r["play"] != "未说" else r["side"])
                day = f"开{pc(k[0] / k[4] - 1)} 高{pc(k[1] / k[4] - 1)} 低{pc(k[2] / k[4] - 1)} 收{pc(k[3] / k[4] - 1)}" if k and k[4] else "当日日线缺"
                res = f" | 结果(次日): 收{pc(kn[3] / k[3] - 1)}" if k and kn else ""
                extra = "/".join([r["time"]] + r["subs"]) if r["time"] != "未说" or r["subs"] else ""
                L.append(f"  - {r['side']} {r['name']}({r['code']}) [{r['play']}{('/' + extra) if extra else ''}] | 当日 {day}{res}")
                for q in quotes(txt, r["name"]):
                    L.append(f"    - 原话: 「{q}」")
        bsl, junk = [], 0
        for v in V.get(D, []):
            for name, side, px in v["bs"]:
                code = nm.get(name)
                if not code:   # 画面识别出的"名称"不是股票(如 大单 / 沪D / 博主自己的名字) → 丢弃, 只计数
                    junk += 1
                    continue
                k = K.get(code, {}).get(D)
                if k and k[1] and k[2]:
                    ok = k[2] * 0.99 <= px <= k[1] * 1.01
                    pos = (px - k[2]) / (k[1] - k[2]) if k[1] > k[2] else None
                    if ok and pos is not None:
                        bsl.append(f"{name} {side}@{px:g}(日内位置 {pos:.2f}, 较昨收 {pc(px / k[4] - 1)})")
                        continue
                    # 当天对不上 → 多半是 K 线页回顾前几天的买卖点: 往前 5 个交易日找唯一能落进区间的那天
                    i = bisect.bisect_left(cal, D)
                    hit = [d0 for d0 in cal[max(0, i - 5):i] if (kk := K.get(code, {}).get(d0)) and kk[2] * 0.99 <= px <= kk[1] * 1.01]
                    bsl.append(f"{name} {side}@{px:g}" + (f"(价位对上 {hit[-1][5:]}, 疑似回顾前几日)" if len(hit) == 1 else "(价位对不上日线, 存疑)"))
                else:
                    bsl.append(f"{name} {side}@{px:g}(无日线核对)")
        if bsl:
            L.append("- 画面 BS 点: " + "; ".join(dict.fromkeys(bsl)))
            tags.append("画面BS")
        hold = list(dict.fromkeys(n for v in V.get(D, []) for n in v["hold"] if n in nm))   # 只留能对上股票名的(防 VLM 把打新页等误读成持仓)
        held = list(dict.fromkeys(n for v in V.get(D, []) for n in v["held"] if n in nm))
        if junk:
            L.append(f"- (画面另有 {junk} 处 BS 标记名称不是股票, 已丢弃)")
        if hold:
            L.append("- 画面持仓页: " + "、".join(hold[:12]))
        if held:
            L.append("- 自选股紫色(持仓)高亮: " + "、".join(held[:12]))
        if V.get(D):
            L.append("- 视频: " + " ".join(v["bvid"] for v in V[D]))
        if len(L) == 1:
            continue
        wd = WD[dt.date.fromisoformat(D).weekday()]
        cards.append((D, f"### {D} 周{wd} | " + (" / ".join(dict.fromkeys(tags)) if tags else "—"), L))
    return cards


def render(up, cards, dry):
    d = ROOT / "skills" / f"{up}-skill" / "persona" / "case_log"
    by = collections.defaultdict(list)
    for D, h, L in cards:
        by[D[:7]].append((D, h, L))
    if dry:
        return len(by)
    d.mkdir(parents=True, exist_ok=True)
    keep = set()
    head = (f"> 机械生成(up_case_log.py, 零 token): md「今日操作」+ 视频抽帧(BS 点 / 持仓页 / 紫色持仓高亮)+ 转写原话 + 行情库; "
            "BS 价位不在当日区间 = 标存疑; 「结果(次日)」是唯一后见信息; 原话只截提到该票的句子, 是动机的一手证据。")
    for m, cs in sorted(by.items()):
        f = d / f"{m}.md"
        keep.add(f.name)
        s = f"# {M.get(up)['display']} 操作日志卡 {m}\n\n{head}\n\n" + "\n\n".join(h + "\n" + "\n".join(L) for _, h, L in cs) + "\n"
        if not f.exists() or f.read_text(encoding="utf-8") != s:
            f.write_text(s, encoding="utf-8")
    idx = [f"# {M.get(up)['display']} 日卡索引(倒序)", ""] + [f"- [{D}]({D[:7]}.md) {h.split('| ', 1)[-1]}" for D, h, _ in sorted(cards, reverse=True)]
    (d / "index.md").write_text("\n".join(idx) + "\n", encoding="utf-8")
    keep.add("index.md")
    for f in d.glob("20??-??.md"):
        if f.name not in keep:
            f.unlink()
    return len(by)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--up", default=",".join(M.ids("UP")))
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    for up in a.up.split(","):
        cards = build(up)
        n = render(up, cards, a.dry)
        nbs = sum(1 for _, _, L in cards if any(l.startswith("- 画面 BS") for l in L))
        nq = sum(1 for _, _, L in cards for l in L if "原话" in l)
        nbad = sum(l.count("存疑") for _, _, L in cards for l in L)
        print(f"{up}: 日卡 {len(cards)} 张 / {n} 个月; 有画面 BS 点 {nbs} 天(价位存疑 {nbad} 处); 原话 {nq} 句")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
