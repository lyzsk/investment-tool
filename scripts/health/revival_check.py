# -*- coding: utf-8 -*-
"""revival_check.py — 导师停更 / 复活(10/24 用户重定; 零 token; 每晚 check md 末尾跑)

两条业务逻辑分开(10/24 用户):
  停更: 某位导师的同花顺账本连续 ≥ STALE_TD 个交易日没更新(= check md 这么多天没有他的账本可蒸馏) → check md 跑完后单独推 1 条微信; 同一段停更只推一次
  复活: 之前记为停更的导师, 账本又更新了 → 不单独推, 写进 check md 的总结微信(check_md_daily 读本脚本输出的 revived)
  新入选 / 跌出属于实盘链(盘前选人 mentor_select), 不在这里
范围: 导师登记表里的 tzzb 导师(scripts/tzzb/tzzb_ledgers.json 里 kind=pos 且有 book 的)
推送格式: "<中文名>skill: <内容>"(中文名取 SKILL.md, scripts/lib/skill_names.py)
状态: scripts/health/revival_state.json {"stale": {导师: 记停更时的最新净值日}}
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/health/revival_check.py [--dry]
输出末行: JSON:{"stale_new": [...], "revived": [...], "stale_all": [...], "alerts": 推了几条}
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = Path(__file__).with_name("revival_state.json")
STALE_TD = 20   # 10/24 用户: 停更统一 = 连续 ≥20 个交易日没更新(daily_health / 盘前选人同口径)
sys.path[:0] = [str(ROOT / "scripts" / "lib"), str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "hermes")]


def last_td():
    import manual_backfill as mb
    c = mb.db().cursor()
    c.execute("select max(trade_date) from investment_market.kline_day where symbol='sh000001' and is_deleted=0")
    return str(c.fetchone()[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    import a_rules as AR
    import skill_names as SN
    led = json.loads((ROOT / "scripts" / "tzzb" / "tzzb_ledgers.json").read_text(encoding="utf-8"))
    ids = [x["ledger"] for x in led if x.get("kind") == "pos" and x.get("book")]
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    stale = st.get("stale") if isinstance(st.get("stale"), dict) else {}
    td = last_td()
    new, rev, allst = [], [], []
    for sk in ids:
        try:
            nav = str(json.loads((ROOT / "downloads" / "tzzb" / sk / "state.json").read_text(encoding="utf-8")).get("lastNavDate") or "")
        except (OSError, ValueError):
            continue
        if len(nav) != 8:
            continue
        navd = f"{nav[:4]}-{nav[4:6]}-{nav[6:]}"
        lag = AR.count_trade_days(navd, td) - 1
        if sk in stale:
            if nav > stale[sk]:
                rev.append({"id": sk, "name": SN.tag(sk), "nav": navd, "was": stale.pop(sk)})
            else:
                allst.append(f"{SN.tag(sk)}({lag} 个交易日)")
            continue
        if lag >= STALE_TD:
            new.append({"id": sk, "name": SN.tag(sk), "nav": navd, "lag": lag})
            stale[sk] = nav
            allst.append(f"{SN.tag(sk)}({lag} 个交易日)")
    alerts = 0
    if new:
        msg = "导师停更(账本连续 ≥{} 个交易日没更新, check md 没有他的账本可蒸馏)\n".format(STALE_TD) + "\n".join(
            f"{x['name']}: 最新净值 {x['nav'][5:]}, 已 {x['lag']} 个交易日没更新; 盘前选人当天按样例处理, 恢复更新会写进 check md 总结" for x in new)
        print(msg)
        if not a.dry:
            try:
                import wx_send
                wx_send.send(msg, src="revival_check", wait=300, verbose=False)
                alerts = 1
            except Exception as e:   # noqa: BLE001
                print(f"推送失败 {e!r}")
    if not a.dry:
        st["stale"] = stale
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"停更(新): {[x['name'] for x in new] or '无'}; 复活: {[x['name'] for x in rev] or '无'}; 停更中: {allst or '无'}")
    print("JSON:" + json.dumps({"stale_new": new, "revived": rev, "stale_all": allst, "alerts": alerts}, ensure_ascii=False))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
