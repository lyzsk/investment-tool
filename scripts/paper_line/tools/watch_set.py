# -*- coding: utf-8 -*-
"""watch_set.py — 必查深查范围(10/24 用户定; 零 token)

来源(去重, 每只票带全部来源标签):
  持仓                         常驻
  发哥提到的                   常驻(spec.md 的【提到的票】行优先; 没有就按 名称 + 昵称表 persona/aliases.json 在 spec / 原文里匹配, 带原话片段)
  盘前提到的(今天 md 盘前节: 财联社早报等)      动态出池
  导师 T−n 持仓 / 操作过的(当时结算入选; n = 各导师回头操作间隔 P50, mentor_recent.py)   动态出池
  (P80 内的进候选池 chain_steps.pool, P90 内的进 3 秒盘口 collect_book —— 同一份 mentor_recent.json)
  3 位 UP(含趋势天哥, 只当市况参考)提到的(前一天 md 的 UP 复盘节)        动态出池
  候选池前 50                  每次触发重算
动态出池(09:25:30 之后, 每次触发): 非常驻的票, 最近一版 04 选票 / 06 挂单 / not_doing / checked 都没出现、也不在当前候选池前 50 → 去掉, 记日志
用法: build(D, positions, pool, skill_ids) → OrderedDict{代码: [标签]};  prune(W, at, last04, last06, pool) → (保留, 去掉清单)
"""
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "lib")]
STICKY = ("持仓", "发哥")
POOL_N = 50
UP_HEADS = {"taoge": "桃哥", "qushitiange": "趋势天哥", "lubenyuan": "卢本圆"}
_C = {}
STOP = {"机器人", "深300ETF"}   # 10/24: 股票简称撞普通说法(UP 说"机器人"板块 ≠ 300024 机器人)
IDX_CODES = {"000300", "000001", "000016", "000905", "000852", "000688"}


def _names():
    """名称 → 代码(股票 / 转债 / 名字带 ETF 的 ETF; 名称 ≥3 字, 去空格)"""
    if "nm" not in _C:
        import manual_backfill as mb
        c = mb.db().cursor()
        c.execute("select symbol, name, sec_type from investment_market.security_master where sec_type in ('STOCK', 'CB', 'ETF') and is_deleted=0")
        m, codes = {}, set()
        for s, n, ty in c.fetchall():
            codes.add(s[-6:])
            n = (n or "").replace(" ", "").replace("Ａ", "A")
            if ty == "ETF" and "ETF" not in n.upper():   # 10/24: ETF 简称"通信设备 / 创业板 / 沪深300 / 半导体 / 保证金"撞普通词 → 只认名字带 ETF 的
                continue
            if len(n) >= 3 and not n.startswith(("XD", "XR", "DR")) and n not in STOP:
                m.setdefault(n, s[-6:])
        _C["nm"], _C["codes"] = m, codes
        _C["re"] = re.compile("|".join(re.escape(k) for k in sorted(m, key=len, reverse=True)))
    return _C["nm"], _C["re"]


def find(text):
    """文本里出现的票 → {代码: (名称, 片段)}"""
    nm, rx = _names()
    out = {}
    t = (text or "").replace(" ", "")
    for mm in rx.finditer(t):
        c = nm[mm.group(0)]
        if c not in out:
            out[c] = (mm.group(0), t[max(0, mm.start() - 30): mm.end() + 30].replace("\n", " "))
    for mm in re.finditer(r"(?<!\d)(00\d{4}|30\d{4}|60\d{4}|68\d{4}|11\d{4}|12\d{4})(?!\d)", t):
        if mm.group(1) in _C["codes"] and mm.group(1) not in IDX_CODES:   # 证券库里查得到才收; 排除常见指数代码(10/24: 304637 / 604622 这种假代码、000300 指数)
            out.setdefault(mm.group(1), ("", t[max(0, mm.start() - 30): mm.end() + 30].replace("\n", " ")))
    return out


def fage(D):
    d = ROOT / "downloads" / "wechat" / "fage" / D
    spec = (d / "spec.md").read_text(encoding="utf-8") if (d / "spec.md").exists() else ""
    raw = (d / "text.md").read_text(encoding="utf-8") if (d / "text.md").exists() else ""
    out = OrderedDict()
    for mm in re.finditer(r"【提到的票】\s*([^\(（\n]+)[\(（](\d{6})[\)）]\s*([^:：\n]*)[:：]\s*(.*)", spec):
        out[mm.group(2)] = f"发哥 {mm.group(1).strip()} {mm.group(3).strip() or '中性'}: {mm.group(4).strip()[:60]}"
    try:
        al = json.loads((ROOT / "skills" / "fage-skill" / "persona" / "aliases.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        al = {}
    for src, t in (("推演要点", spec), ("原文", raw)):
        for k, v in al.items():
            if k.startswith("_") or not isinstance(v, list):
                continue
            i = t.find(k)
            if i >= 0 and v[0] not in out:
                out[v[0]] = f"发哥({src}) {v[1]}(“{k}”): …{t[max(0, i - 25): i + 35].replace(chr(10), ' ')}…"
        for c, (n, snip) in find(t).items():
            if c not in out:
                out[c] = f"发哥({src}) {n}: …{snip}…"
    return out


def md_section(D, pat):
    y, m = D[:4], int(D[5:7])
    p = ROOT / "md" / f"{y}S{(m - 1) // 3 + 1}" / f"{D}.md"
    t = p.read_text(encoding="utf-8") if p.exists() else ""
    mm = re.search(pat, t, re.S | re.M)
    return mm.group(0) if mm else ""


def prev_day(D):
    import manual_backfill as mb
    c = mb.db().cursor()
    c.execute("select max(trade_date) from investment_market.kline_day where symbol='sh000001' and trade_date < %s and is_deleted=0", (D,))
    return str(c.fetchone()[0])


def mentor_t1(D, ids):
    import manual_backfill as mb
    d1 = prev_day(D)
    c = mb.db().cursor()
    out = OrderedDict()
    if not ids:
        return out
    c.execute("select ledger, stock_code, stock_name, side, count(*) from investment_tool.tzzb_record where record_type='bs_leg' and is_deleted=0 and date(record_time)=%s "
              "and ledger in (" + ",".join(["%s"] * len(ids)) + ") group by 1, 2, 3, 4", (d1, *ids))
    for led, code, nm, side, n in c.fetchall():
        if code and re.fullmatch(r"\d{6}", str(code)):
            out.setdefault(str(code), []).append(f"导师T-1 {led} {'买' if '买' in str(side) else '卖'}{n}笔 {nm or ''}".strip())
    return out


def old_mentor(D):
    """10/28 晚用户定: 导师票 T−1 / T−2 都没持有、没操作(mentor_recent k > 2) → 不进必查(只留 3 秒盘口); → {代码: k}"""
    if ("old", D) not in _C:
        try:
            import mentor_recent as MR
            _C[("old", D)] = {c: int(e.get("k") or 1) for c, e in MR.load(D)["codes"].items() if int(e.get("k") or 1) > 2}
        except Exception:   # noqa: BLE001
            _C[("old", D)] = {}
    return _C[("old", D)]


def build(D, positions=(), pool=(), skill_ids=None):
    W = OrderedDict()
    old = old_mentor(D)

    def add(c, tag):
        W.setdefault(c, [])
        if tag not in W[c]:
            W[c].append(tag)
    for c in positions or ():
        add(str(c), "持仓")
    for c, tag in fage(D).items():
        add(c, tag)
    mr = None
    if skill_ids is None:   # 10/24 用户: 导师 T−n 持仓 / 操作(当时结算入选的导师; n 按各导师回头操作间隔 P50 定, mentor_recent.py)
        try:
            import mentor_recent as MR
            mr = MR.load(D)["codes"]
            for c, e in mr.items():
                if e["tier"] == "must" and c not in old:   # 10/28 晚: k > 2 的导师票不进必查(P50 长的导师 must 档也会到 k=12)
                    for t in e["tags"][:3]:
                        add(c, t)
        except Exception:   # noqa: BLE001  算不出来退回旧口径: 今天入选导师 T−1 操作过的
            mr = None
            try:
                import mentor_select as MS
                s = MS.load(D) or MS.select(D)
                skill_ids = [x for x in s["premarket"] if x not in UP_HEADS]
            except Exception:   # noqa: BLE001
                skill_ids = []
    if mr is None:
        for c, tags in mentor_t1(D, skill_ids or []).items():
            for t in tags:
                add(c, t)
    d1 = prev_day(D)
    for uid, head in UP_HEADS.items():
        sec = md_section(d1, rf"^#{{2,4}}[^\n]*{re.escape(head)}.*?(?=^#{{2,4}} |\Z)")
        for c, (n, _) in find(sec).items():
            add(c, f"UP {head} 提到 {n}".strip())
    pre = md_section(D, r"^## 盘前.*?(?=^## |\Z)")
    for c, (n, _) in find(re.sub(r"(?s)#### 红旗大街发哥.*?(?=^#{2,4} |\Z)", "", pre)).items():
        add(c, f"盘前提到 {n}".strip())
    held = {str(c) for c in positions or ()}
    for c in list(pool or ())[:POOL_N]:
        if str(c) in old and str(c) not in held and str(c) not in W:   # 10/28 晚: 候选池里只因导师 T−3 以前操作进来的, 不整批进必查
            continue
        add(str(c), "候选池前50")
    return W


def prune(W, at, mentioned, pool, D=None):
    """动态出池: 09:25:30 后, 非常驻、没被最近一版 04 / 06 提到、不在当前候选池前 50 的去掉 → (保留, 去掉 [(代码, 标签)])"""
    if at < "09:25:30":
        return W, []
    top = set(list(pool or ())[:POOL_N]) - set(old_mentor(D) if D else {})   # 10/28 晚: 导师 k > 2 的票不靠"在候选池前 50"留在必查
    keep, drop = OrderedDict(), []
    for c, tags in W.items():
        if any(t.startswith(STICKY) for t in tags) or c in mentioned or c in top:
            keep[c] = tags
        else:
            drop.append((c, tags))
    return keep, drop


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    D = sys.argv[1]
    W = build(D, positions=sys.argv[2].split(",") if len(sys.argv) > 2 and sys.argv[2] else ())
    from collections import Counter
    print(f"共 {len(W)} 只(不含候选池前 50):", dict(Counter(t.split()[0] for v in W.values() for t in v)))
    for c, tags in W.items():
        print(f"  {c}: {' | '.join(tags)[:160]}")
