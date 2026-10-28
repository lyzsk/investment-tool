# -*- coding: utf-8 -*-
"""candidates_daily.py — 每天的「投资账本推荐」(10/25 用户要, 10/27 晚用户提醒: 和 check md 总结一起发微信; 零 token)

门槛(用户 10/25 定, chain_flags 可调): 近 20 日(榜单「月收益」)≥ CAND_X%(10) · 日均(入场以来总收益按交易日折算)≥ CAND_Y%(0.2)
                                      · 近 3 月(榜单「季收益」)> CAND_Q%(30) · 持续报单(榜单更新时间在 CAND_STALE 天内, 5)
不在现有导师库 / 旧候选名单里; 一个人在多场比赛出现只留最好的一场
数据: downloads/tzzb/_ranks/<比赛key>.json(总榜快照); --refresh = 先经 tzzb_guard 额度闸重拉总榜(每天 1 次, 约 11 场 × ≤20 页), 闸不让就用本地快照并标拉取日期
产物: results/_live/<D>/mentor_candidates.json + .md; check md 总结推送时附前几名
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/candidates_daily.py [--date D] [--refresh] [--top 10]
不自信点: 「近 20 日」用的是榜单月收益(自然月口径还是滚动 20 日没核实); 「日均」是入场以来总收益按交易日几何平均, 不是近 20 日日均
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
RANKS = ROOT / "downloads" / "tzzb" / "_ranks"
LIVE = ROOT / "results" / "_live"
HOME = "https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key={k}&user_key={u}"


def _flag(k, d):
    try:
        for l in (ROOT / "scripts" / "claude_profile" / "chain_flags.txt").read_text(encoding="utf-8").splitlines():
            kk, _, v = l.split("#")[0].partition("=")
            if kk.strip() == k and v.strip():
                return float(v.strip())
    except OSError:
        pass
    return d


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def refresh():
    """经 tzzb_guard 重拉全部比赛总榜(rank_monthly.mjs --overall --refresh); 闸不让 → 返回原因, 用本地快照"""
    import rank_screen as RS
    keys = RS.all_keys()
    rc, s = RS.run_side(["--overall", "--refresh", "--keys", ",".join(keys)], 25, 600, False, "rank-overall-daily")
    return f"重拉总榜 rc={rc}" + (f" 请求 {s.get('requests')}" if s else "")


def build(D, top=10):
    import rank_screen as RS
    x, y, qq, stale = _flag("CAND_X", 10) / 100, _flag("CAND_Y", 0.2) / 100, _flag("CAND_Q", 30) / 100, _flag("CAND_STALE", 5)
    have = RS.existing_names()
    best, fetched = {}, {}
    for f in sorted(RANKS.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        k = d.get("match_key") or f.stem
        fetched[k] = str(d.get("fetched_at") or "")[:10]
        for r in d.get("rows") or []:
            nm = str(r.get("user_name") or "").replace(" ", "")
            m, qv, tot = _f(r.get("monthly_profit")), _f(r.get("quarterly_profit")), _f(r.get("total_profit_rate"))
            if not nm or m is None or nm in have:
                continue
            ent = str(r.get("enter_date") or "")[:10]
            try:
                n = max(1, int(np.busday_count(ent, fetched[k] or D)))
            except ValueError:
                n = None
            daily = ((1 + tot) ** (1 / n) - 1) if (tot is not None and n and tot > -1) else None
            try:
                upd = dt.datetime.fromtimestamp(int(r.get("update_time")) / 1000).date()
            except (TypeError, ValueError, OSError):
                upd = None
            age = (dt.date.fromisoformat(fetched[k] or D) - upd).days if upd else None
            row = {"名": nm, "比赛": k, "user_key": r.get("user_key"), "近20日": m, "近3月": qv, "总收益": tot, "入场": ent, "交易日": n, "日均": daily,
                   "仓位": _f(r.get("position_rate")), "最近更新": str(upd) if upd else "", "距拉取天数": age, "主页": HOME.format(k=k, u=r.get("user_key")), "榜单拉取": fetched[k]}
            ok = m >= x and (daily or 0) >= y and (qv or 0) > qq and age is not None and age <= stale
            row["过门槛"] = ok
            if ok and (nm not in best or m > best[nm]["近20日"]):
                best[nm] = row
    rows = sorted(best.values(), key=lambda r: -r["近20日"])
    out = {"D": D, "门槛": f"近20日≥{x:.0%} · 日均≥{y:.2%} · 近3月>{qq:.0%} · 更新≤{stale:g}天", "榜单拉取日": fetched, "候选": rows,
           "built": dt.datetime.now().isoformat(timespec="seconds")}
    d_ = LIVE / D
    d_.mkdir(parents=True, exist_ok=True)
    (d_ / "mentor_candidates.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    old = min((v for v in fetched.values() if v), default="?")
    L = [f"## 投资账本推荐 {D}(门槛 {out['门槛']}; 榜单最早拉取 {old}; 不在现有导师库)", ""]
    for r in rows[:top]:
        L.append(f"- **{r['名']}**: 近20日 {r['近20日']:+.1%} · 近3月 {r['近3月']:+.1%} · 总 {r['总收益']:+.1%}(入场 {r['入场']}, 日均 {r['日均']:+.2%})· 仓位 {(r['仓位'] or 0):.0%} · 最近更新 {r['最近更新']} · {r['主页']}")
    if not rows:
        L.append("- 今天没有过门槛的")
    L += ["", f"共 {len(rows)} 人过门槛; 不自信点: 「近 20 日」= 榜单月收益(口径没核实);「日均」= 入场以来几何日均; 榜单是拉取那天的快照"]
    (d_ / "mentor_candidates.md").write_text("\n".join(L), encoding="utf-8")
    return out, "\n".join(L)


def brief(D, top=5):
    """给 check md 总结推送用的几行"""
    try:
        o = json.loads((LIVE / D / "mentor_candidates.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = o.get("候选") or []
    L = [f"投资账本推荐({o.get('门槛')}; 共 {len(rows)} 人, 前 {min(top, len(rows))}):"]
    for r in rows[:top]:
        L.append(f"· {r['名']} 近20日 {r['近20日']:+.0%} 近3月 {r['近3月']:+.0%} 日均 {r['日均']:+.2%} {r['主页']}")
    return L if rows else [f"投资账本推荐: 今天没有过门槛的({o.get('门槛')})"]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()
    if a.refresh:
        print(refresh())
    _, md = build(a.date, a.top)
    print(md)


if __name__ == "__main__":
    main()
