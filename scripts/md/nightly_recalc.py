# -*- coding: utf-8 -*-
"""nightly_recalc.py — 夜间重算(10/25 用户批: 等 tzzb 当天全部出齐、数据不会再变之后算; 零 token)

谁调: Java Quartz checkMarkdownHandler, 参数 --only nightly → check_md_daily.py 转到这里
  · 主任务 04:00 每天: 目标日 = 昨天; 昨天不是交易日 → 直接退出(Java / 本脚本两头都判)
  · 兜底任务 05:00 / 06:00 / 07:00 每天: 同一命令; 状态文件里全部步骤已成功 → 秒退; 有失败 / 没跑完的 → 只重跑失败的步骤
算什么(按依赖顺序; 每步记成功 / 失败 / 用时, 失败不挡后面不依赖它的步骤):
  1 fingerprint   导师逐笔事件库 cases_auto + 指纹(含板型买点)        tzzb/mentor_fingerprint.py --all
  2 strong_next   强势股次日溢价库                                    paper_line/tools/strong_next.py --build-if-stale
  3 ontology      事件本体(依赖 1 / 2 / 电报 / 分钟路径)              ontology/build.py
  4 samples       样例库(一次买入 = 一个样例; 待核 n 每晚 −1)        ontology/sample_lib.py build
  5 rule_health   规则体检 → docs/review/rule_suspects.md              ontology/rule_health.py
  6 rules_lint    rules.md 来源检查                                   md/rules_lint.py
  7 user_found    market-skill U 节核销                               market/user_found_check.py
  8 telegraph     电报分类统计(必查「电报点名」用)                    test/telegraph_kind.py
  9 pattern_bt    近期规律回测(转债 / 股票)                           paper_line/tools/pattern_scan.py --backtest
 10 plan_review   计划核销(目标日 + 前一交易日补下一天)              live/plan_review.py
    rule_exam     导师规则样本外拟人体检(四家 × 近 20 日 vs 两个基线)  skills_ver/rule_exam.py → docs/review/rule_exam_<日>.md
    skill_score   C 方案 skill 成绩(日超额 / 部分时段 / 起点检查)    live/skill_score.py
 11 signal_params 下一交易日分时信号动态参数                          live/signal_params.py <下一交易日>
 12 mentor_select 下一交易日盘前名单(近 20 日收益 / 日均; 保留用户已挑的 keep) paper_line/tools/mentor_select.py <下一交易日> --write
 13 mentor_recent 下一交易日导师近期票(必查 / 候选池 / 3 秒盘口分层)  paper_line/tools/mentor_recent.py <下一交易日>
状态: results/_live/<下一交易日>/nightly_status.json {target, next, steps: {名: {ok, secs, at, tail}}, done, at}
用法: python nightly_recalc.py [--date 目标日] [--force(全部重跑)] [--status]
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / "scripts" / "venv" / "Scripts" / "python.exe")
sys.path[:0] = [str(ROOT / "scripts" / "lib")]


def next_trade(d):
    import a_rules as AR
    x = dt.date.fromisoformat(d)
    for _ in range(20):
        x += dt.timedelta(days=1)
        if AR._is_trade_day_fallback(x.isoformat()):
            return x.isoformat()
    return None


def steps(D, N, prevD):
    S = [("fingerprint", [PY, "-X", "utf8", "scripts/tzzb/mentor_fingerprint.py", "--all"], 1200),
         ("strong_next", [PY, "-X", "utf8", "scripts/paper_line/tools/strong_next.py", "--build-if-stale"], 900),
         ("ontology", [PY, "-X", "utf8", "scripts/ontology/build.py"], 1200),
         ("samples", [PY, "-X", "utf8", "scripts/ontology/sample_lib.py", "build"], 1800),
         ("rule_health", [PY, "-X", "utf8", "scripts/ontology/rule_health.py"], 600),
         ("rules_lint", [PY, "-X", "utf8", "scripts/md/rules_lint.py"], 120),
         ("user_found", [PY, "-X", "utf8", "scripts/market/user_found_check.py"], 900),
         ("telegraph", [PY, "-X", "utf8", "scripts/test/telegraph_kind.py"], 2400),
         ("pattern_bt_cb", [PY, "-X", "utf8", "scripts/paper_line/tools/pattern_scan.py", "--backtest", "cb"], 900),
         ("pattern_bt_stock", [PY, "-X", "utf8", "scripts/paper_line/tools/pattern_scan.py", "--backtest", "stock"], 900),
         ("plan_review", [PY, "-X", "utf8", "scripts/live/plan_review.py", "--date", D], 600)]
    if prevD:
        S.append(("plan_review_prev", [PY, "-X", "utf8", "scripts/live/plan_review.py", "--date", prevD], 600))
    S.append(("deviation", [PY, "-X", "utf8", "scripts/live/deviation_review.py", "--date", D], 300))   # 10/28: 备案与链路偏差复盘(用户 10/27 令; 零 token, 「为什么」晚上填)
    S.append(("rule_exam", [PY, "-X", "utf8", "scripts/skills_ver/rule_exam.py", "--skill", "zhiyingjuexin,liuyiqing,zuoshoudeirong,buchitudou0", "--days", "20"], 300))   # 10/26: 规则样本外拟人体检(零 token)
    S.append(("session_growth", [PY, "-X", "utf8", "scripts/live/session_growth.py", "--date", D, "--todo"], 120))   # 10/25: 午后是否变贵变慢 → TODO 一行
    S.append(("skill_score", [PY, "-X", "utf8", "scripts/live/skill_score.py", "--date", D], 900))   # 10/25 C 方案: skill 单日超额 + 部分时段 + 起点检查(内含再跑一次核销)
    S += [("signal_params", [PY, "-X", "utf8", "scripts/live/signal_params.py", N], 900),
          ("mentor_select", [PY, "-X", "utf8", "scripts/paper_line/tools/mentor_select.py", N, "--write"], 300),
          ("mentor_recent", [PY, "-X", "utf8", "scripts/paper_line/tools/mentor_recent.py", N], 600)]
    return S


def prev_trade(d):
    import a_rules as AR
    x = dt.date.fromisoformat(d)
    for _ in range(20):
        x -= dt.timedelta(days=1)
        if AR._is_trade_day_fallback(x.isoformat()):
            return x.isoformat()
    return None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    import a_rules as AR
    D = a.date or (dt.date.today() - dt.timedelta(days=1)).isoformat()
    if not AR._is_trade_day_fallback(D):
        print("JSON:" + json.dumps({"nightly": "跳过", "target": D, "why": "目标日不是交易日"}, ensure_ascii=False))
        return 0
    N = next_trade(D)
    sf = ROOT / "results" / "_live" / N / "nightly_status.json"
    st = {}
    if sf.exists() and not a.force:
        try:
            st = json.loads(sf.read_text(encoding="utf-8"))
        except ValueError:
            st = {}
    if a.status:
        print(json.dumps(st, ensure_ascii=False, indent=1))
        return 0
    st.update(target=D, next=N)
    st.setdefault("steps", {})
    S = steps(D, N, prev_trade(D))
    if all((st["steps"].get(n) or {}).get("ok") for n, _, _ in S):
        print("JSON:" + json.dumps({"nightly": "已全部成功, 跳过", "target": D, "next": N}, ensure_ascii=False))
        return 0
    st["runs"] = int(st.get("runs") or 0) + 1
    sf.parent.mkdir(parents=True, exist_ok=True)
    for name, cmd, tmo in S:
        if (st["steps"].get(name) or {}).get("ok"):
            continue
        t0 = time.time()
        try:
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=tmo,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            ok, tail = r.returncode == 0, [l for l in ((r.stdout or "") + (r.stderr or "")).splitlines() if l.strip()][-2:]
        except subprocess.TimeoutExpired:
            ok, tail = False, [f"超时 {tmo}s"]
        st["steps"][name] = {"ok": ok, "secs": round(time.time() - t0), "at": dt.datetime.now().strftime("%H:%M:%S"), "tail": " / ".join(x[:150] for x in tail)}
        st["at"] = dt.datetime.now().isoformat(timespec="seconds")
        sf.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")   # 每步写一次: 中途被杀也知道做到哪
        print(f"{'✓' if ok else '✗'} {name} {st['steps'][name]['secs']}s", flush=True)
    bad = [n for n, _, _ in S if not (st["steps"].get(n) or {}).get("ok")]
    st["done"] = not bad
    sf.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    print("JSON:" + json.dumps({"nightly": "完成" if not bad else "有失败", "target": D, "next": N, "failed": bad, "runs": st["runs"]}, ensure_ascii=False))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
