# -*- coding: utf-8 -*-
"""gen_horizon.py — 决策链持有期表(零 token, 10/16 持有期改造)
口径(与 scripts/tzzb/mentor_scope.py 同一算法, 便于对账):
  downloads/tzzb/<ledger>/day_positions.json 近 120 个交易日, 逐日收盘持仓(position_percent>0, 剔逆回购 204/1318),
  一只票连续出现在收盘持仓里的天数=一段持仓; 中位=sorted[n//2](mentor_scope 同款上中位), 上限=P75=sorted[int(n*0.75)]
  med/cap 以 mentor_scope.json 的 hold_days_med/hold_days_p75 为准(--scope 指定; 缺省=本目录 dev 版输出, 没有则真文件;
  p75 字段缺失=用本脚本重算值; 重算值只做对账, 不一致打 WARN); cap=max(med, P75)
  无统计(3 位 B站 UP/对照组/转债土豆): med/cap=null, src="无统计，按画像", 驱动器按缺省 2 天/上限 5 天给参考但不做"超上限须写理由"校验
输出: scripts/chain/horizon_days.json; 手改该 json 即可调参
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/chain/gen_horizon.py [--out <json>]
"""
import json, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TZ = ROOT / "downloads" / "tzzb"
DEFAULT = {"med": 2, "cap": 5, "src": "无统计，按画像(缺省参考 2 天/上限 5 天, 10/16 用户定)", "stat": False}
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import mentors  # noqa: E402  10/17 二B-4: 导师登记表
NO_STAT = {m: mentors.get(m)["display"] for m in mentors.ids("UP", "对照")}
NO_STAT["buchitudou0"] = "不吃土豆0(转债 T+0)"
LEDGERS = [x for x in mentors.ids("tzzb") if x != "buchitudou0"]   # = 驱动器 TZZB_LEDGERS


def spans_of(dp, window=120):
    dks = sorted(dp)[-window:]
    run, spans = {}, []
    for k in dks:
        lst = [x for x in (dp[k] or {}).get("list") or []
               if float(x.get("position_percent") or 0) > 0 and not str(x.get("code", "")).startswith(("204", "1318"))]
        cur = {x["code"] for x in lst}
        for c in list(run):
            if c not in cur:
                spans.append(run.pop(c))
        for c in cur:
            run[c] = run.get(c, 0) + 1
    return spans, (dks[0], dks[-1]) if dks else (None, None)


def main():
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else ROOT / "scripts" / "chain" / "horizon_days.json"
    here = ROOT / "scripts" / "tzzb" / "mentor_scope.json"
    sp = Path(sys.argv[sys.argv.index("--scope") + 1]) if "--scope" in sys.argv else (here if here.exists() else ROOT / "scripts" / "tzzb" / "mentor_scope.json")
    scope = json.loads(sp.read_text(encoding="utf-8"))
    print(f"scope: {sp}")
    tab = {"_comment": "决策链持有期表(gen_horizon.py 生成, 可手改): med=真人持仓天数中位(注入 02 outlook.horizon_days 默认值), "
                       "cap=拿得住的上限(P75; 04 hold_days 一般不超过); 键=--skill 名, 缺键用 _default",
           "_generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "_default": DEFAULT}
    for led in LEDGERS:
        try:
            dp = json.loads((TZ / led / "day_positions.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(f"WARN {led}: 无 day_positions.json, 用默认")
            continue
        spans, win = spans_of(dp)
        if len(spans) < 5:
            print(f"WARN {led}: 持仓段仅 {len(spans)} 段, 用默认")
            continue
        s = sorted(spans)
        med_re, p75 = s[len(s) // 2], s[min(len(s) - 1, int(len(s) * 0.75))]
        sc = scope.get(led) or {}
        med = sc.get("hold_days_med") if isinstance(sc.get("hold_days_med"), int) else med_re
        q = sc.get("hold_days_p75") if isinstance(sc.get("hold_days_p75"), int) else p75
        if (med, q) != (med_re, p75):
            print(f"WARN {led}: mentor_scope 中位/P75 {med}/{q} != 重算 {med_re}/{p75}(账本已更新? 以 mentor_scope 为准)")
        cap = max(med, q)
        tab[led] = {"med": med, "cap": cap, "stat": True, "src": f"tzzb 真人收盘持仓 {win[0]}~{win[1]} 共 {len(s)} 段: 中位 {med} 天/P75 {q} 天"}
        print(f"{led:24s} 段数 {len(s):4d}  中位 {med:2d}  P75 {p75:2d}  P90 {s[min(len(s) - 1, int(len(s) * 0.9))]:2d}  max {s[-1]}")
    for k, nm in NO_STAT.items():
        tab[k] = {"med": None, "cap": None, "stat": False, "src": f"{nm}: 无统计，按画像"}
    # 10/17 审计高-2: 持仓段太少算不出(如暗里着火 120 天只有 2 段长仓)的导师, 用人工覆盖(horizon_override.json, 带来源说明); 覆盖优先于默认、不覆盖有统计的
    ov = Path(__file__).with_name("horizon_override.json")
    if ov.exists():
        for k, v in json.loads(ov.read_text(encoding="utf-8")).items():
            if k.startswith("_") or (tab.get(k) or {}).get("stat"):
                continue
            tab[k] = {"med": v["med"], "cap": v["cap"], "stat": True, "src": v["src"]}
            print(f"{k:24s} 人工覆盖: 中位 {v['med']} / 上限 {v['cap']}({v['src']})")
    out.write_text(json.dumps(tab, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"→ {out}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
