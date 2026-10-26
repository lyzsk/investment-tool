# -*- coding: utf-8 -*-
"""market02_extra.py — 02 共用市况的"方向证据包"(10/25 用户批 TODO ❓7 第一条; 零 token, 只用 ≤ 此刻 / T−1 及以前的数据)

用户 10/25: 02 不基于任何 skill, 但要用有方向的来源: 发哥 / 桃哥 / 天哥 / 卢本圆 / 涨停分析 / 梯队 / 导师逆向 / market-skill(含 K 线) / 指数 K 线;
           导师看 T−1 / T−2 / T−3 一共 3 个交易日
块:
  ①导师近 3 个交易日实际买卖 → 方向: 今天盘前入选的导师(mentor_select, 近 20 日收益门槛同选人)在 T−1 / T−2 / T−3 的逐笔腿(同花顺投资账本 bs_leg),
    每笔按 theme_life 映射到题材; 各导师先按自己 3 天成交额归一(大小账户可比), 再按近 20 日收益加权 → 题材的加权买入 / 卖出占比 + 逐日明细
  ②UP 近 3 日定调: 桃哥 / 趋势天哥 / 卢本圆 T−2、T−3 的「大盘定调」「今日操作」两行(T−1 全文已在"前一天 md 摘要"里)
  ③发哥近 3 日推演要点 + 近 20 日核销命中率(md 里发哥每天收盘后有「核销 当日」命中 / 半命中 / 打脸 计数)
  ④指数 K 线结构: 上证 / 国证2000 / 创业板指 / 科创50 日线 + 15 分钟段式箱体(同个股必查「K线结构」口径, 只用 ≤ 此刻)
  ⑤market-skill 规则全文(rules + kline_rules + user_found)
  UP 方向命中率: 还没建核销(B 站 UP 没有逐日核销记录), 块里写明"待建"
用法: python market02_extra.py D [HH:MM:SS]   → 打印全部块
"""
import collections
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(Path(__file__).resolve().parent), str(ROOT / "scripts" / "paper_line"), str(ROOT / "scripts" / "backfill_bilibili")]
IDX = [("sh000001", "上证"), ("sz399303", "国证2000"), ("sz399006", "创业板指"), ("sh000688", "科创50")]
UPS = [("桃哥", r"桃哥"), ("趋势天哥", r"趋势天哥"), ("卢本圆", r"卢本圆")]


def tdays(D, n):
    import mentor_recent as MR
    return MR.tdays(D, n)


def md_text(d):
    import pack
    return pack.rd(pack.md_path(d)) or ""


def mentor_dirs(D, n=3):
    import manual_backfill as mb
    import mentor_select as MS
    import theme_life as TL
    days = tdays(D, n)
    s = MS.load(D) or MS.select(D)
    ms = [x for x in s.get("ranked") or [] if x.get("role") == "入选" and (x.get("ret20") or 0) > 0]
    if not ms:
        return "(今天没有入选导师)"
    w = {x["id"]: x["ret20"] / sum(y["ret20"] for y in ms) for x in ms}
    c = mb.db().cursor()
    c.execute("select ledger, date(record_time), time(record_time), stock_code, stock_name, side, price, qty from investment_tool.tzzb_record where record_type='bs_leg' and is_deleted=0 "
              "and ledger in (" + ",".join(["%s"] * len(ms)) + ") and date(record_time) >= %s and date(record_time) <= %s order by record_time", (*w, days[0], days[-1]))
    legs = [(led, str(d), str(t)[:5], code, nm, "买" if "买" in str(sd) else "卖", float(px or 0) * float(q or 0)) for led, d, t, code, nm, sd, px, q in c.fetchall()]
    th_c = {}

    def theme(nm, d):
        if (nm, d) not in th_c:
            r = TL.by_stock(nm, d).get("近 20 个交易日挂过的题材") or {}
            th_c[(nm, d)] = next(iter(r), None) or ("转债" if nm.endswith("转债") else "近 20 日没进涨停分析")
        return th_c[(nm, d)]
    tot = collections.Counter()
    for led, d, t, code, nm, sd, amt, in legs:
        tot[led] += amt
    agg = collections.defaultdict(lambda: {"买": 0.0, "卖": 0.0, "who": set(), "票": set()})
    name = {x["id"]: x["name"] for x in ms}
    for led, d, t, code, nm, sd, amt in legs:
        if not tot[led]:
            continue
        k = theme(nm, d)
        a = agg[k]
        a[sd] += amt / tot[led] * w[led]
        a["who"].add(name[led])
        a["票"].add(nm)
    L = [f"今天入选导师 {len(ms)} 位(权重 = 近 20 日收益占比): " + "、".join(f"{x['name']} 近20日 {x['ret20']:+.1f}% 权 {w[x['id']]:.0%}" for x in ms),
         f"统计区间 T−3 ~ T−1 = {days[0]} ~ {days[-1]}; 各导师先按自己 3 天成交额归一, 再乘权重(大小账户可比); 题材 = 这只票近 20 日在涨停分析里挂的第一个题材", "",
         "| 题材 | 加权买入占比 | 加权卖出占比 | 净 | 哪些导师 | 票 |", "|---|---|---|---|---|---|"]
    for k, a in sorted(agg.items(), key=lambda kv: -(kv[1]["买"] - kv[1]["卖"]))[:15]:
        L.append(f"| {k} | {a['买']:.0%} | {a['卖']:.0%} | {a['买'] - a['卖']:+.0%} | {'、'.join(sorted(a['who']))} | {'、'.join(sorted(a['票']))[:80]} |")
    L += ["", "逐日明细(导师 · 时刻 · 买卖 · 票 · 题材):"]
    for d in days[::-1]:
        x = [f"{name[led]} {t} {sd}{nm}({theme(nm, d)})" for led, dd, t, code, nm, sd, amt in legs if dd == d]
        L.append(f"- {d}({'T−' + str(len(days) - days.index(d))}): " + ("；".join(x[:40]) + (f" …(共 {len(x)} 笔)" if len(x) > 40 else "") if x else "无成交"))
    return "\n".join(L)


def _section(t, head_rx):
    m = re.search(r"(?m)^#### [^\n]*(?:" + head_rx + r")[^\n]*\n(.*?)(?=^#{2,4} |\Z)", t, re.S)
    return m.group(1) if m else ""


def up_recent(D):
    """10/25 用户: 桃哥 / 卢本圆 / 趋势天哥 T−1 / T−2 / T−3 每天的市况 / 方向判断逐人逐天列出; 当天没视频或没提市况方向, 也要明写"没提"(不能静默缺)"""
    days = tdays(D, 3)
    L = ["(每人每天一行: 定调 / 操作两行原文摘录; 没视频 / 没提市况方向都明写; UP 方向命中率: 还没建逐日核销, 待建)"]
    for d in days[::-1]:
        t = md_text(d)
        tag = f"T−{len(days) - days.index(d)}"
        for nm, rx in UPS:
            sec = _section(t, rx)
            rows = [l.strip() for l in sec.splitlines() if re.match(r"^- \*\*(大盘|.{0,4}今日操作)", l.strip())]
            if rows:
                L.append(f"- {d}({tag}) {nm}: " + " / ".join(r[:300] for r in rows))
            elif sec:
                L.append(f"- {d}({tag}) {nm}: 有视频, 没提市况 / 方向(没有定调和操作行)")
            else:
                L.append(f"- {d}({tag}) {nm}: 当天没有视频(没提)")
    return chr(10).join(L)


def fage(D, n_rate=20):
    days = tdays(D, n_rate)
    L, hit = [], collections.Counter()
    for d in days:
        sec = _section(md_text(d), "红旗大街发哥")
        m = re.search(r"【核销 当日】命中(\d+) 半命中(\d+) 打脸(\d+)(?: 不可证(\d+))?", sec)
        if m:
            for k, v in zip(("命中", "半命中", "打脸", "不可证"), m.groups()):
                hit[k] += int(v or 0)
        if d in days[-3:]:
            pts = [l.strip()[:200] for l in sec.splitlines() if l.strip().startswith("【推演要点】")]
            if pts:
                L.append(f"- {d}: " + " | ".join(pts[:6]))
    judged = hit["命中"] + hit["半命中"] + hit["打脸"]
    rate = f"近 {n_rate} 个交易日核销 {judged} 条: 命中 {hit['命中']} / 半命中 {hit['半命中']} / 打脸 {hit['打脸']} / 不可证 {hit['不可证']}" + (
        f" → 命中率(半命中算一半) {(hit['命中'] + hit['半命中'] / 2) / judged:.0%}" if judged else "")
    return rate + "\n(T−1 / 今天的全文在 md 摘要 / 今天 md 盘前里; 这里是近 3 日推演要点)\n" + ("\n".join(L) or "(近 3 日没有发哥推演)")


def index_kline(D, at="09:00:00"):
    import kline_struct as KS
    L = []
    for s, nm in IDX:
        try:
            L.append(f"- {nm}({s}): {KS.line(s, D, at=at)}")
        except Exception as e:   # noqa: BLE001
            L.append(f"- {nm}: (取不到 {e!r})"[:120])
    return "\n".join(L)


def blocks(D, at="09:00:00"):
    """→ [(标题, 正文)] 给 market02.material 用"""
    import pack
    out = []
    for title, fn in (("导师近 3 个交易日(T−1 / T−2 / T−3)实际买卖 → 方向(逆向)", lambda: mentor_dirs(D)),
                      ("UP 近 3 日(T−1 / T−2 / T−3)定调: 桃哥 / 卢本圆 / 趋势天哥(没提也写明)", lambda: up_recent(D)),
                      ("发哥近 3 日推演 + 核销命中率", lambda: fage(D)),
                      ("指数 K 线结构(日线 + 15 分钟段式箱体, ATR)", lambda: index_kline(D, at)),
                      ("market-skill 规则全文(市场行为: 统计 / K 线 / 用户发现; 每条带 n / 置信)", pack.market_rules)):
        try:
            out.append((title, fn()))
        except Exception as e:   # noqa: BLE001
            out.append((title, f"(取不到: {e!r})"[:160]))
    return out


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = sys.argv[1:]
    D = a[0] if a else dt.date.today().isoformat()
    at = a[1] if len(a) > 1 else "09:00:00"
    for t, b in blocks(D, at):
        print(f"## {t}\n{b}\n")
