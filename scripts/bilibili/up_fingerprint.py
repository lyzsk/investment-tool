# -*- coding: utf-8 -*-
"""up_fingerprint.py — B站 UP(桃哥/卢本圆)"操作指纹": 从 md「今日操作」统计打法/时段/板块/持有天数/买后表现(零 token; 10/17 agent③ 建)

与 up_ops_stats.py 的分工: up_ops_stats=近 60 期的轻量统计(驱动器拟人审 import, 不动它); 本脚本=全历史深统计, 写进
  skills/<up>-skill/persona/fingerprint.md(给蒸馏/画像/人工看) + scripts/bilibili/up_fingerprint.json(给后续脚本)。
数据: md/**/YYYY-MM-DD.md 的 UP 小节「今日操作」(视频口述 + 抽帧 BS 点/持仓高亮核销后写入) + 行情库 kline_day(只读)
解析口径(正则, 不调模型):
  - 一条操作 = 「今日操作」里 ①②③… 编号项中带 6 位代码的那项; 买/卖由项首 160 字的动词判(买/吸/加仓/跟/打板/上车/建仓/接 vs 卖/出/减仓/清仓/走/止盈/止损/兑现/T 掉/踢)
  - 操作日: 项首括号里出现 "M/D" 且早于 md 日期 → 用那天(卢本圆常回顾前几天的成交); 否则=md 日期
  - 打法(关键词优先级): 打板 > 跌停低吸 > 低吸 > 追涨 > 做T > 未说; 副标签: 竞价/尾盘/加仓/推断(项里带"推断""待核")
  - 时段词: 竞价/开盘(含早盘)/盘中(含上午)/午后/尾盘/未说
  - 持有天数: 同票 买→其后第一次卖 的交易日数(FIFO, 不看股数——口述常不给股数); 没卖出的记"仍持有/未披露卖出"(右删失)
  - 买后表现: 买入日收盘相对开盘、T+1/T+3/T+5 收盘相对买入日收盘(不知道真实成交价, 是"当天买进"的近似)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/bilibili/up_fingerprint.py [--up taoge,lubenyuan] [--no-write]  --selftest
"""
import argparse, json, re, statistics as st, sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from up_ops_stats import UPS, section, ops_block, board  # noqa: E402

BUY = re.compile(r"买|吸|加仓|跟了|跟板|打板|上车|建仓|进场|接回|接了|排板|扫")
SELL = re.compile(r"卖|出了|先出|减仓|清仓|走了|止盈|止损|兑现|T ?掉|踢|割")
HOLDW = re.compile(r"持有|拿着|没动|未动|仍持|继续拿|锁仓")
CODE = re.compile(r"[（(](\d{6})[）)]")
MD_ = re.compile(r"(?<!\d)(1[0-2]|[1-9])/([12]\d|3[01]|[1-9])(?!\d)")
PLAYS = [("打板", r"打板|排板|封板|涨停价买|回封|扫板|板上|跟板"), ("跌停低吸", r"跌停开|核按钮|地板|跌停.{0,6}吸|负十开|-10 ?%?开|反核|跌停价开"),
         ("消息跟随", r"秒跟|消息.{0,8}跟|利好.{0,10}(跟|买)"),
         ("低吸", r"低吸|吸了|吸一|回踩|抄底|低开.{0,8}(吸|接|买)|绿盘.{0,4}买|水下|接回|杀到.{0,8}接|负 ?\d+ ?点.{0,6}(接|加|买)|-\d+ ?%.{0,6}(接|加|买)"),
         ("追涨", r"追|半路|拉升.{0,6}买|冲高.{0,4}买|翻红.{0,4}买|突破|高开.{0,6}买|\+ ?\d+ ?%?.{0,4}(买|进)"),
         ("做T", r"做 ?T|倒 ?T|正 ?T|T 掉|T了")]
NOTOP = re.compile(r"未买|没去|没接到|踏空|没买|没敢|没上车|差一点买到")
TIMEW = [("竞价", r"竞价"), ("开盘", r"开盘|早盘|一开|早上"), ("盘中", r"盘中|上午|10[:：]\d\d|11[:：]\d\d"), ("午后", r"午后|下午|13[:：]\d\d|14[:：][0-4]\d"), ("尾盘", r"尾盘|收盘前|14[:：]5\d")]


def parse_items(blk, md_day):
    first = blk.splitlines()[0] if blk else ""
    if not blk or (re.search(r"今日操作[^:：]*[:：]\s*\**\s*无", first) and not CODE.search(blk.split("仓位口径")[0])):
        return []
    out = []
    for it in re.split(r"(?=[①②③④⑤⑥⑦⑧⑨⑩⑪⑫])", blk):
        m = CODE.search(it)
        if not m or "沉默持仓" in it[:20] or "提及" in it[:10]:
            continue
        head = it[:160]
        if NOTOP.search(head[:120]):
            continue   # "想买没买/踏空"不是操作
        cut = head[:head.find(m.group(0)) + 40]
        if SELL.search(cut) and not BUY.search(cut[:cut.find(m.group(0))] if m.group(0) in cut else cut):
            side = "卖"
        elif BUY.search(head) and not SELL.search(cut):
            side = "买"
        elif SELL.search(head):
            side = "卖"
        elif HOLDW.search(head):
            side = "持有"
        else:
            continue
        name = re.sub(r"[*\\\s]", "", it[:it.find(m.group(0))]).lstrip("①②③④⑤⑥⑦⑧⑨⑩⑪⑫").split("·")[-1][-8:]
        d = md_day
        dm = MD_.search(head)
        if dm:
            try:
                cand = date(md_day.year, int(dm.group(1)), int(dm.group(2)))
                if cand < md_day and (md_day - cand).days <= 20:
                    d = cand
            except ValueError:
                pass
        play = next((k for k, rx in PLAYS if re.search(rx, head)), "未说")
        tw = next((k for k, rx in TIMEW if re.search(rx, head)), "未说")
        subs = [s for s, rx in [("竞价", r"竞价"), ("尾盘", r"尾盘"), ("加仓", r"加仓|加了"), ("推断", r"推断|待核|\[\?\]")] if re.search(rx, it[:400])]
        out.append({"md": md_day.isoformat(), "date": d.isoformat(), "code": m.group(1), "name": name, "side": side, "play": play, "time": tw, "subs": subs})
    # 同日同票同向去重(一段话里重复提到)
    seen, res = set(), []
    for o in out:
        k = (o["date"], o["code"], o["side"])
        if k not in seen:
            seen.add(k); res.append(o)
    return res


def collect(up):
    head = UPS[up][0]
    rows, sec_days = [], []
    for f in sorted((ROOT / "md").rglob("20??-??-??.md")):
        try:
            d = date.fromisoformat(f.stem)
        except ValueError:
            continue
        t = f.read_text(encoding="utf-8", errors="replace")
        blk = ops_block(section(t, head))
        if not blk:
            continue
        sec_days.append(f.stem)
        rows += parse_items(blk, d)
    return rows, sec_days


def kline(codes):
    sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
    from kline_db import db
    sym = lambda c: ("sh" if c.startswith(("6", "9", "5", "11")) else "bj" if c.startswith(("4", "8", "92")) else "sz") + c
    c = db(); K = defaultdict(dict); cal = []
    try:
        cur = c.cursor()
        cur.execute("select trade_date from kline_day where symbol='sh000001' and trade_date>='2025-01-01' order by trade_date")
        cal = [d.isoformat() for (d,) in cur.fetchall()]
        ss = sorted({sym(x) for x in codes})
        for i in range(0, len(ss), 200):
            part = ss[i:i + 200]
            cur.execute(f"select symbol, trade_date, open, close from kline_day where symbol in ({','.join(['%s'] * len(part))}) and trade_date>='2024-12-01'", tuple(part))
            for s, d, o, cl in cur.fetchall():
                K[s[2:]][d.isoformat()] = (float(o or 0), float(cl or 0))
    finally:
        c.close()
    return K, cal


def lim(code):
    return 0.2 if code.startswith(("300", "301", "688", "689")) else (0.3 if code.startswith(("4", "8", "92")) else 0.1)


def enrich(rows, K, cal):
    idx = {d: i for i, d in enumerate(cal)}
    for r in rows:
        k = K.get(r["code"], {})
        d = r["date"]
        if d not in k or d not in idx:
            continue
        i = idx[d]
        o, c = k[d]
        prev = next((k[cal[j]] for j in range(i - 1, max(-1, i - 6), -1) if cal[j] in k), None)
        if prev and prev[1] > 0:
            r["gap"] = o / prev[1] - 1
            r["day_ret"] = c / prev[1] - 1
            p2 = next((k[cal[j]] for j in range(i - 2, max(-1, i - 7), -1) if cal[j] in k and k[cal[j]] is not prev), None)
            if p2 and p2[1] > 0:
                r["prev_ret"] = prev[1] / p2[1] - 1
        r["oc"] = c / o - 1 if o else None
        for n in (1, 3, 5):
            if i + n < len(cal) and cal[i + n] in k and c:
                r[f"r{n}"] = k[cal[i + n]][1] / c - 1
    return rows


def mech_play(r):
    """关键词没说打法时, 用买入日日线兜底(标 '·机械'): 昨涨停=接力; 开盘缺口 ≤-2% 低开买; ≥+2% 高开买; 其余平开买"""
    L = lim(r["code"])
    if r.get("prev_ret") is not None and r["prev_ret"] >= L - 0.003:
        return "接力·机械"
    g = r.get("gap")
    if g is None:
        return "未说"
    return "低开买·机械" if g <= -0.02 else "高开买·机械" if g >= 0.02 else "平开买·机械"


def ctx_tag(r):
    L = lim(r["code"])
    pr, g = r.get("prev_ret"), r.get("gap")
    if pr is not None and pr >= L - 0.003:
        return "昨涨停(接力)"
    if pr is not None and pr <= -L + 0.003:
        return "昨跌停"
    if g is not None and g <= -0.05:
        return "大低开≤-5%"
    if g is not None and g >= 0.05:
        return "大高开≥5%"
    return "其他"


def holds(rows, cal, last_day):
    idx = {d: i for i, d in enumerate(cal)}
    by = defaultdict(list)
    for r in sorted(rows, key=lambda x: x["date"]):
        if r["side"] in ("买", "卖"):
            by[r["code"]].append(r)
    segs = []
    for code, L in by.items():
        open_ = None
        for r in L:
            if r["side"] == "买" and open_ is None:
                open_ = r
            elif r["side"] == "卖" and open_ is not None:
                if open_["date"] in idx and r["date"] in idx:
                    segs.append({"code": code, "name": open_["name"], "buy": open_["date"], "sell": r["date"], "days": idx[r["date"]] - idx[open_["date"]], "closed": True})
                open_ = None
        if open_ is not None and open_["date"] in idx:
            ld = max(x for x in cal if x <= last_day)
            segs.append({"code": code, "name": open_["name"], "buy": open_["date"], "sell": None, "days": idx[ld] - idx[open_["date"]], "closed": False})
    return segs


def pct(c, n):
    return " / ".join(f"{k} {v / n:.0%}" for k, v in c.most_common()) if n else "—"


def q(xs, f="{:+.1%}"):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "—"
    xs = sorted(xs)
    return f"{f.format(st.median(xs))}(P25~P75 {f.format(xs[len(xs) // 4])}~{f.format(xs[(3 * len(xs)) // 4])}, n={len(xs)})"


def render(up, rows, sec_days, segs, now):
    name = UPS[up][1]
    buys = [r for r in rows if r["side"] == "买"]
    sells = [r for r in rows if r["side"] == "卖"]
    act = sorted({r["md"] for r in rows if r["side"] in ("买", "卖")})
    nb = len(buys)
    recent_cut = sorted({r["date"] for r in buys})[-20:][0] if len({r["date"] for r in buys}) >= 20 else None
    rb = [r for r in buys if recent_cut and r["date"] >= recent_cut]
    closed = [s for s in segs if s["closed"]]
    L = [f"# {name}({up}) 操作指纹·机械层（md「今日操作」统计）", "",
         f"> 生成: {now:%Y-%m-%dT%H:%M} | 脚本: scripts/bilibili/up_fingerprint.py(零 token, 只读 md + 行情库) | 窗口: {sec_days[0] if sec_days else '-'} ~ {sec_days[-1] if sec_days else '-'}",
         f"> 有「今日操作」条目的视频 {len(sec_days)} 期, 其中有买卖披露 {len(act)} 期; 解析出 买 {nb} 笔 / 卖 {len(sells)} 笔 / 只说持有 {sum(1 for r in rows if r['side'] == '持有')} 条; 带「推断/待核」的 {sum(1 for r in rows if '推断' in r['subs'])} 条",
         "> 口径: 「今日操作」= 视频口述 + 抽帧 BS 点/持仓高亮核销后写入 md 的本人操作(不是账本, **只有他愿意披露的那部分**; 股数/价格常缺); 正则解析, 买卖方向/打法按关键词, 个别句子会判错。",
         "> 打法关键词优先级: 打板(打板/排板/封板/回封/跟板) > 跌停低吸(跌停开/核按钮/地板/反核) > 消息跟随(秒跟/利好跟) > 低吸(低吸/吸了/回踩/低开接/接回/负N点接) > 追涨(追/半路/突破/高开买) > 做T > 未说(再按买入日日线兜底, 标·机械); 「没买到/踏空」不计。",
         "", "## 一、打法分布(买入)", "",
         f"- 关键词打法: {pct(Counter(r['play'] for r in buys), nb)}",
         f"- 关键词没说的 {sum(1 for r in buys if r['play'] == '未说')} 笔按买入日日线兜底: {pct(Counter(mech_play(r) for r in buys if r['play'] == '未说'), sum(1 for r in buys if r['play'] == '未说'))}",
         f"- 行情环境(买入日, 日线机械): {pct(Counter(ctx_tag(r) for r in buys if r.get('gap') is not None), sum(1 for r in buys if r.get('gap') is not None))}",
         f"- 副标签: 加仓 {sum(1 for r in buys if '加仓' in r['subs'])} / 竞价 {sum(1 for r in buys if '竞价' in r['subs'])} / 尾盘 {sum(1 for r in buys if '尾盘' in r['subs'])} / 推断 {sum(1 for r in buys if '推断' in r['subs'])}(共 {nb})",
         f"- 近 20 个买入日(自 {recent_cut or '-'}) 打法: {pct(Counter(r['play'] for r in rb), len(rb))}",
         "", "## 二、时段(口述时段词, 买入)", "",
         f"- 全期: {pct(Counter(r['time'] for r in buys), nb)}",
         f"- 近 20 个买入日: {pct(Counter(r['time'] for r in rb), len(rb))}",
         "- 注: 「未说」占比高时, 时段分布只代表他说出口的那部分; 视频里画面 BS 点的时刻已在 md 写成分钟线核对(如「09:30 首分钟」), 本脚本只认时段词与 HH:MM。",
         "", "## 三、板块与常做票(买入)", "",
         f"- 板块: {pct(Counter(board(r['code']) for r in buys), nb)}",
         f"- 买得最多: {'、'.join(f'{n}({c})×{k}' for (c, n), k in Counter((r['code'], r['name']) for r in buys).most_common(12))}",
         f"- 回头票(同一只买过 ≥2 次的票占买入笔数): {sum(k for k in Counter(r['code'] for r in buys).values() if k >= 2) / nb:.0%}" if nb else "- 回头票: —",
         "", "## 四、持有天数(同票 买→其后第一次卖, 交易日)", "",
         f"- 已平仓段 {len(closed)} 个: 持有交易日 {q([s['days'] for s in closed], '{:.0f}')}; 当天/次日卖(≤1 日) {sum(1 for s in closed if s['days'] <= 1) / len(closed):.0%}, 2~5 日 {sum(1 for s in closed if 2 <= s['days'] <= 5) / len(closed):.0%}, >5 日 {sum(1 for s in closed if s['days'] > 5) / len(closed):.0%}" if closed else "- 已平仓段: 0",
         f"- 未披露卖出(右删失) {sum(1 for s in segs if not s['closed'])} 段: 至今已过交易日 {q([s['days'] for s in segs if not s['closed']], '{:.0f}')}——多数是**视频里没再提卖出**, 不等于还拿着; 真实持有期介于已平仓段与这个数之间",
         "", "## 五、买后表现(买入日收盘为基准; 不知真实成交价)", "",
         f"- 买入日 收盘相对开盘: {q([r.get('oc') for r in buys])}",
         f"- T+1 收盘: {q([r.get('r1') for r in buys])}; T+3: {q([r.get('r3') for r in buys])}; T+5: {q([r.get('r5') for r in buys])}",
         f"- 按打法 T+1 中位: " + "; ".join(f"{p} {q([r.get('r1') for r in buys if r['play'] == p])}" for p, _ in Counter(r["play"] for r in buys).most_common(5)),
         "", "## 六、卖出(口述)", "",
         f"- 卖出 {len(sells)} 笔; 时段词: {pct(Counter(r['time'] for r in sells), len(sells))}",
         f"- 卖出日 当日涨跌(相对昨收): {q([r.get('day_ret') for r in sells])}; 卖后 T+1: {q([r.get('r1') for r in sells])}",
         "", "## 七、局限", "",
         "- 只统计披露了代码的操作; UP 有「不披露」「事后补说」的选择偏差(赚的更愿意说)。",
         "- 卖出漏记会把持有天数拉长; 买卖方向判错的句子(如「昨天卖的今天又接回」)会混进相反方向。",
         "- 打法是口述关键词, 不是分钟线还原; 与 tzzb 导师 fingerprint 的「统一打法分类器」不同口径, 不能直接横比。"]
    return "\n".join(L) + "\n"


def _selftest():
    blk = "- **桃哥今日操作**（持仓高亮）：\n  ① **星网宇达（002829）跌停开低吸**——\"今天跟着大盘低开了 10 个点，也是吸了一下\"\n  ② **\\*ST 皇庭（000056）卖出 **——\"昨天进的这个皇庭，大部分也是卖在低点了\"\n  ③ **兴森科技（002436）持有、拖后腿**——\"昨天进了\"\n"
    r = parse_items(blk, date(2026, 10, 15))
    assert [(x["code"], x["side"], x["play"]) for x in r] == [("002829", "买", "跌停低吸"), ("000056", "卖", "未说"), ("002436", "持有", "未说")], r
    blk2 = "- **今日操作/持仓**：\n  ① **打野号·中文在线（300364）节后首日（10/8）加仓约 40 万**：画面成交\n  ② **实盘号·中文在线 10/13 T 掉剩余 4000 股**（300364）：\n"
    r2 = parse_items(blk2, date(2026, 10, 14))
    assert r2[0]["date"] == "2026-10-08" and r2[0]["side"] == "买" and "加仓" in r2[0]["subs"], r2
    assert r2[1]["side"] == "卖" and r2[1]["date"] == "2026-10-13", r2
    assert parse_items("- **今日操作**: 无 (口述无买卖持仓)", date(2026, 10, 15)) == []
    r3 = parse_items("- **今日操作**：\n  ① **远东股份（600869）-5% 没接到=踏空**——\n  ② **上工申贝（600843）盘中跟板**——\"我也是跟了一个\"\n", date(2026, 10, 16))
    assert [(x["code"], x["play"]) for x in r3] == [("600843", "打板")], r3
    cal = ["2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13"]
    segs = holds([{"code": "A", "name": "a", "date": "2026-10-08", "side": "买"}, {"code": "A", "name": "a", "date": "2026-10-13", "side": "卖"},
                  {"code": "B", "name": "b", "date": "2026-10-09", "side": "买"}], cal, "2026-10-13")
    assert [(s["code"], s["days"], s["closed"]) for s in segs] == [("A", 3, True), ("B", 2, False)], segs
    print("up_fingerprint selftest PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--up", default="taoge,lubenyuan")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    now = datetime.now()
    js = {}
    for up in a.up.split(","):
        rows, sec_days = collect(up)
        K, cal = kline({r["code"] for r in rows})
        enrich(rows, K, cal)
        segs = holds(rows, cal, sec_days[-1] if sec_days else now.date().isoformat())
        md = render(up, rows, sec_days, segs, now)
        js[up] = {"rows": rows, "segs": segs, "sec_days": len(sec_days)}
        print(md)
        if not a.no_write:
            (ROOT / "skills" / f"{up}-skill" / "persona" / "fingerprint.md").write_text(md, encoding="utf-8")
    if not a.no_write:
        (ROOT / "scripts" / "bilibili" / "up_fingerprint.json").write_text(json.dumps(js, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
