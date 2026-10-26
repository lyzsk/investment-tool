# -*- coding: utf-8 -*-
"""mentor_select.py — 盘前选人(10/24 模块 5; 零 token, 08:30 出名单)

口径(10/24 用户定): 候选 = 导师登记表里全部 tzzb 导师(不看旧的"退出 paper"名单)
  近 20 个交易日收益 > 0 → 入选(盘前全部跑一遍 chain); 按日均收益率从高到低排
  停更(10/24 用户定: 账本连续 ≥ STALE 个交易日没更新 = 最近净值日落在 T−1 之前第 STALE 个交易日或更早) → 样例
  近 20 日收益 ≤ 0 → 样例(正负样例照样进必查, 只是不跑 chain)
  不剔除单日异常收益(用户 10/24 取消)
  2 位 UP(桃哥 / 卢本圆)没有净值, 固定进盘前名单; 趋势天哥不成线(画面没有 BS 点 / 持仓抽帧, 拿不到票和仓位; 和发哥一样只当市况参考: 发哥 = 盘前 T+0 核销蒸馏, 天哥 = 盘后 T+1 核销蒸馏)
产物: results/_live/<D>/selected_mentors.json
  {"D", "ranked": [{id, name, ret20, avg, n, last, role}], "premarket": [盘前要跑的 id(入选导师按排名 + 2 位 UP)],
   "active": [今天的导师 = premarket; 用户盘前挑完后改成留下的几位(keep)], "keep": null | [...]}
净值: tzzb_record nav_day 的 index(单位净值); 收益 = 近 20 个点首尾比; 日均 = 20 个日收益率的均值
用法: python mentor_select.py [D] [--write]
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "lib"), str(ROOT / "scripts" / "backfill_bilibili")]
N, STALE = 20, 20   # 10/24 用户: 停更 = 账本连续 ≥20 个交易日没更新(daily_health 原 30 天、复活检查原 10 天, 取中间统一 20)
FRESH = 5   # 10/25 用户: 盘前选人更严格 —— 账本最近净值日落在 T−1 之前第 5 个交易日或更早(= 连续 ≥5 个交易日没更新) → 不进盘前名单(记"近 5 日没更新"); 和停更(20 日)是两个口径
MIN_AVG, MIN_RET20 = 0.2, 10.0   # 10/24 用户定: 日均收益率 < 0.2% 或 近 20 日收益率 < 10% → 样例(不进实盘线盘前 skill 名单)
UPS = ["taoge", "lubenyuan"]   # 10/25 用户: 趋势天哥没有公布自选 / 持仓、风格是机构大票和短线不匹配 → 不做 live line 的线, 只当市况参考(盘后评盘进事实包公共节, 开关 CHAIN_TIANGE_MARKET), 类似发哥


def _db():
    import manual_backfill as mb
    return mb.db().cursor()


def select(D):
    import mentors as MT
    c = _db()
    c.execute("select distinct trade_date from investment_market.kline_day where symbol='sh000001' and trade_date < %s and is_deleted=0 order by trade_date desc limit %s", (D, STALE + 1))   # tds[0] = T−1 … tds[STALE] = 往前第 STALE 个交易日
    tds = [str(x[0]) for x in c.fetchall()]
    d1, stale_at = (tds[0], tds[STALE] if len(tds) > STALE else None) if tds else (None, None)
    fresh_at = tds[FRESH] if len(tds) > FRESH else None
    c.execute("select distinct trade_date from investment_market.kline_day where symbol='sh000001' and trade_date < %s and is_deleted=0 order by trade_date desc limit 60", (D,))
    tdset = {str(x[0]) for x in c.fetchall()}
    out = []
    for e in MT.all():
        if e["type"] != "tzzb":
            continue
        mid = e["id"]
        c.execute("select record_time, json_unquote(json_extract(payload_json, '$.index')) from investment_tool.tzzb_record where ledger=%s and record_type='nav_day' and is_deleted=0 "
                  "and record_time < %s order by record_time desc limit %s", (mid, D, N + 15))
        raw = [(str(t)[:10], float(v)) for t, v in c.fetchall() if v not in (None, "null")][::-1]
        raw = [p for p in raw if p[0] in tdset][-(N + 1):]   # 只用交易日的点(10/24: 国庆 10-02~10-07 重复行会把日均拉低)
        pts, fix = [], 1.0
        for i, (d, v) in enumerate(raw):   # 单位断点: 相邻比 >50 或 <1/50 → 按 10 的整数次幂换回(10/24: 量化小号 10-16 单位净值 2.18 → 2315, 资产没变)
            if pts and v * fix > 0 and not (1 / 50 < v * fix / pts[-1][1] < 50):
                import math
                fix *= 10 ** -round(math.log10(v * fix / pts[-1][1]))
            pts.append((d, v * fix))
        r = {"id": mid, "name": e.get("display") or e.get("name"), "n": len(pts), "last": pts[-1][0] if pts else None, **({"单位断点已换算": True} if fix != 1.0 else {})}
        if len(pts) >= 2:
            rets = [(b[1] / a[1] - 1) * 100 for a, b in zip(pts, pts[1:])]
            r["ret20"] = round((pts[-1][1] / pts[0][1] - 1) * 100, 2)
            r["avg"] = round(sum(rets) / len(rets), 3)
        if not pts or (stale_at and r["last"] <= stale_at):
            r["role"] = "样例(停更)"
        elif r.get("ret20") is None or r["ret20"] <= 0:
            r["role"] = "样例(近20日≤0)"
        elif (r.get("avg") or 0) < MIN_AVG:
            r["role"] = f"样例(日均<{MIN_AVG}%)"
        elif r["ret20"] < MIN_RET20:
            r["role"] = f"样例(近20日<{MIN_RET20:g}%)"
        elif fresh_at and r["last"] <= fresh_at:
            r["role"] = f"样例(近{FRESH}日没更新)"
        else:
            r["role"] = "入选"
        out.append(r)
    out.sort(key=lambda x: (x["role"] != "入选", -(x.get("avg") or -99)))
    pre = [x["id"] for x in out if x["role"] == "入选"] + UPS
    return {"D": D, "T-1": d1, "ranked": out, "premarket": pre, "active": pre, "keep": None,
            "口径": f"近 {N} 个交易日收益 ≥{MIN_RET20:g}% 且日均 ≥{MIN_AVG}% 入选(按日均收益率排); 最近净值日 ≤ {fresh_at}(连续 ≥{FRESH} 个交易日没更新)→ 不进盘前名单; 最近净值日 ≤ {stale_at}(≥{STALE} 个交易日)= 停更 → 样例; 不加回撤 / 出手次数门槛(10/25 用户定); 不剔单日异常收益; 2 位 UP(桃哥 / 卢本圆)固定进盘前, 趋势天哥只当市况参考",
            "built": dt.datetime.now().isoformat(timespec="seconds")}


def path(D):
    return ROOT / "results" / "_live" / D / "selected_mentors.json"


def load(D):
    f = path(D)
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return None


def write(D):
    s = select(D)
    old = load(D)
    if old and old.get("keep") is not None:   # 用户已经挑过(含全部收束 = []) → 保留他的选择
        s["keep"], s["active"] = old["keep"], old["keep"]
    if old and old.get("keep_log"):
        s["keep_log"] = old["keep_log"]
    f = path(D)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    return s


def text(s):
    L = [f"盘前选人 {s['D']}(净值截至 {s['T-1']}): 盘前跑 {len(s["premarket"])} 位(入选导师 + 2 位 UP: 桃哥 / 卢本圆)"]
    for i, x in enumerate(s["ranked"], 1):
        L.append(f"{i:>2}. {x['name']:<10} {x['role']:<12} 近20日 {x.get('ret20', '-'):>7}% 日均 {x.get('avg', '-'):>6}%  最近净值 {x['last']}")
    return "\n".join(L)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    D = a[0] if a else dt.date.today().isoformat()
    s = write(D) if "--write" in sys.argv else select(D)
    print(text(s))
