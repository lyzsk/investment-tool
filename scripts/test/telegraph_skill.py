# -*- coding: utf-8 -*-
"""telegraph_skill.py — 财联社加红电报 知识 skill 生成器(10/23 用户批: 所有线都能用; 知识没有人格, 按 case 驱动)

每晚 check md 在 telegraph_nextday.py 之后跑(零 token): 用"电报次日"的可成交事件重算统计规则 → skills/telegraph-skill/persona/rules.md(T1~Tn, 每条带 n / 置信 / 截至日)
+ cases.md(次日冲高最多 / 跌最多的点名事件各 5 个, 当正反面案例) + 重建两个索引
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/test/telegraph_skill.py
"""
import statistics as st
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "test"), str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "market")]
SK = ROOT / "skills" / "telegraph-skill" / "persona"
FEE = 0.15


def conf(n):
    return "高" if n >= 300 else "中" if n >= 80 else "低"


def ev(xs, th):
    out = [(r["gap"] if r["gap"] >= th else th if r["hi"] >= th else r["co"]) - FEE for r in xs]
    return st.mean(out), sum(1 for x in out if x > 0) / len(out)


def stat(xs):
    if not xs:
        return None
    hi = sorted(r["hi"] for r in xs)
    return {"n": len(xs), "hi3": sum(1 for r in xs if r["hi"] >= 3) / len(xs), "hi_med": hi[len(hi) // 2], "co_med": sorted(r["co"] for r in xs)[len(xs) // 2],
            "lo_med": sorted(r["lo"] for r in xs)[len(xs) // 2], "ev1": ev(xs, 1), "ev3": ev(xs, 3)}


def line(s):
    return (f"n={s['n']}；次日冲高 ≥+3% 占 {s['hi3']:.0%}，冲高中位 {s['hi_med']:+.2f}%，最低中位 {s['lo_med']:+.2f}%，收盘中位 {s['co_med']:+.2f}%；"
            f"次日挂 +1% 卖期望 {s['ev1'][0]:+.2f}%（胜 {s['ev1'][1]:.0%}）、挂 +3% 卖期望 {s['ev3'][0]:+.2f}%（胜 {s['ev3'][1]:.0%}）")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import telegraph_nextday as TN
    R = TN.collect()
    if not R:
        return print("没有事件")
    rows, pairs, base, sealed, nomin = R
    days = sorted({r["D"] for r in rows})
    asof = days[-1]
    allx, notpk, pk = stat(rows), stat([r for r in rows if not r["peaked"]]), stat([r for r in rows if r["peaked"]])
    am, pm = stat([r for r in rows if str(r.get("t", "")) < "11:30"]), stat([r for r in rows if str(r.get("t", "")) >= "13:00"])
    big = stat([r for r in rows if (r.get("up") or 0) >= 0.05])
    bse = stat([{"gap": (n[0] / e - 1) * 100, "hi": (n[1] / e - 1) * 100, "lo": (n[2] / e - 1) * 100, "co": (n[3] / e - 1) * 100} for e, n in base])
    head = f"> 自动生成（`scripts/test/telegraph_skill.py`，每晚重算，勿手改）；截至 {asof}，{len(days)} 个点名日，可成交事件 {len(rows)} 个（另剔除点名后一分钟封死在板上买不进的 {len(sealed)} 个）。买点 = 点名后下一分钟收盘；次日表现相对买点；扣费 0.15%。"
    L = ["# telegraph-skill 规则（加红电报点名票；统计规则，每条带样本 / 置信 / 截至日）", "", head, ""]
    L += ["### T1 电报点名后追进去，次日平均是亏的（避雷） [教训 · 统计✅]", "",
          "- 规则: 看到加红电报点名就追买，次日大概率只能靠冲高那一下卖，拿到收盘平均亏 → 不要把\"被电报点名\"当买入理由",
          f"- 证据: 全部可成交点名 {line(allx)}",
          f"- 对照: 同期\"当天涨 ≥5% 没封板、收盘买\" {line(bse)} → 和电报点名差不多，电报本身没带来额外信息" if bse else "",
          f"- 置信: {conf(allx['n'])}（截至 {asof}）", ""]
    if notpk and pk:
        L += ["### T2 点名时还没见顶的比已经见顶的好 [画像 · 统计✅]", "",
              "- 规则: 点名那一刻当天最高已经出现过（点名时已见顶）的，次日更差；还没见顶的相对好一些，但也谈不上赚",
              f"- 证据: 还没见顶 {line(notpk)}", f"- 证据: 已见顶 {line(pk)}", f"- 置信: {conf(min(notpk['n'], pk['n']))}（截至 {asof}）", ""]
    if am and pm:
        L += ["### T3 上午点名 vs 下午点名 [画像 · 统计✅]", "", f"- 上午（11:30 前） {line(am)}", f"- 下午（13:00 后） {line(pm)}",
              f"- 置信: {conf(min(am['n'], pm['n']))}（截至 {asof}）", ""]
    if big:
        L += ["### T4 点名时已经涨了 5% 以上的 [画像 · 统计✅]", "", f"- 证据: {line(big)}", f"- 置信: {conf(big['n'])}（截至 {asof}）", ""]
    SK.mkdir(parents=True, exist_ok=True)
    (SK / "rules.md").write_text("\n".join(x for x in L if x is not None) + "\n", encoding="utf-8")
    best = sorted(rows, key=lambda r: -r["hi"])[:5]
    worst = sorted(rows, key=lambda r: r["co"])[:5]
    C = ["# telegraph-skill 案例（自动生成，每晚重算；正反面各 5 个）", "", "<!-- CASES -->", ""]
    for tag, xs in (("次日冲高最多", best), ("次日收盘跌最多", worst)):
        for r in xs:
            C += [f"### {r['D']} {r.get('t')} {r.get('name') or ''} {r['sym']}（{tag}）", "",
                  f"- 点名时已涨 {(r.get('up') or 0) * 100:+.2f}%，{'已见顶' if r['peaked'] else '还没见顶'}；次日 开 {r['gap']:+.2f}% / 高 {r['hi']:+.2f}% / 低 {r['lo']:+.2f}% / 收 {r['co']:+.2f}%（相对买点）", ""]
    (SK / "cases.md").write_text("\n".join(C) + "\n", encoding="utf-8")
    subprocess.run(["node", "scripts/md/gen_rules_index.mjs", "--skill", "telegraph"], cwd=ROOT, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    subprocess.run([sys.executable, "-X", "utf8", "scripts/md/gen_cases_index.py", "--skill", "telegraph"], cwd=ROOT, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    print(f"telegraph-skill: {len(days)} 天 / {len(rows)} 事件, 规则 {sum(1 for x in L if x.startswith('### '))} 条 → {SK}")


if __name__ == "__main__":
    main()
