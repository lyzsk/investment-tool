# -*- coding: utf-8 -*-
"""t_knowledge.py — 做 T 知识包(零 token; 10/18 用户定: 决策 T 不只学梅月路, 要学所有 skill 的做 T 技巧, 正反面教材都要)

来源(全部机械抽取, 每晚 check md 重算, 决策 T 每次决策内联读 t_knowledge.md):
  ① 各导师 T 法统计 scripts/dfcf/paper/t_profile/<最新>.json: 做 T 频率 / 正T·倒T 占比 / 胜率 / 每次平均收益 / 显著性 → 谁是"执行T"(正面)谁是"不学T"(反面)
  ② 各 skill rules.md 里和做 T 相关的规则标题(做T / 正T / 反T / 倒T / 日内来回 / 回转 / 高抛 / 底仓), 带时间状态
  ③ 梅月路 银行 / ETF 专题(和本账本标的完全同类, 最贴近)
  ④ 土豆 竞价T(开盘最机械的一种 T)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/t_knowledge.py [--date D]
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import mentors as M   # noqa: E402

KW = re.compile(r"做T|做 T|正T|反T|倒T|日内来回|回转|高抛|底仓|先买后卖|先卖后买")
OUT = HERE / "t_knowledge.md"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    L = [f"# 做 T 知识包(机械抽取, {dt.datetime.now():%m-%d %H:%M}; 正面=统计上做 T 赚钱的导师, 反面=做 T 亏钱 / 不该学的)", ""]
    tp = sorted((HERE / "t_profile").glob("20*.json"))
    tp = [f for f in tp if f.stem <= a.date] or tp
    if tp:
        J = json.loads(tp[-1].read_text(encoding="utf-8")).get("mentors") or {}
        rows = []
        for sk, v in J.items():
            lg = (v or {}).get("long") or {}
            if not lg.get("t_days"):
                continue
            try:
                name = M.get(sk)["name"]
            except StopIteration:
                name = sk
            typ = "/".join(f"{k}{x:.0%}" for k, x in (lg.get("type") or {}).items())
            verdict = (v or {}).get("verdict") or (v or {}).get("label") or ""
            rows.append(((lg["t_days"] >= 10, float(lg.get("t") or 0)), f"- {name}: 做T日 {lg['t_days']}/{lg.get('n')} ({lg.get('freq', 0):.0%}), {typ}, 胜率 {lg.get('win', 0):.0%}, "
                                                          f"每次均 {float(lg.get('ret_mean') or 0) * 100:+.2f}%, t={lg.get('t')}" + (f", {verdict}" if verdict else "")))
        rows.sort(key=lambda x: x[0], reverse=True)
        L += ["## ① 各导师 T 法统计(按显著性 t 排, 做T日 <10 的放最后; 上面=正面教材, 下面=反面教材; 含已退出 paper 的导师, 只当教材)", ""] + [r for _, r in rows] + [""]
    L += ["## ② 各 skill 里和做 T 相关的规则(标题 + 时间状态)", ""]
    for sk in M.active_ids():
        f = ROOT / "skills" / f"{sk}-skill" / "persona" / "rules.md"
        if not f.exists():
            continue
        t = f.read_text(encoding="utf-8")
        heads = []
        for m in re.finditer(r"^(#{3,4} +R\d+ .+)$", t, re.M):
            h = m.group(1)
            if KW.search(h):
                st = re.search(r"\*\*时间状态\*\*: ([^\n]+)", t[m.end():m.end() + 600])
                heads.append(f"  - {h.lstrip('#').strip()[:110]}" + (f" ⏱{st.group(1)[-24:]}" if st else ""))
        if heads:
            L.append(f"- **{M.get(sk)['name']}**")
            L += heads[:6]
    L.append("")
    try:
        t = (ROOT / "skills" / "meiyuelu-skill" / "persona" / "profile.md").read_text(encoding="utf-8")
        i = t.index("## 【专题: 银行股与ETF")
        j = t.find("\n## ", i + 5)
        L += ["## ③ 梅月路111号 银行 / ETF 专题(同类标的, 最贴近; 注意他银行不做 T、纳指基本不做 T——反面也要看)", "", t[i:j if j > 0 else i + 3000][:3000], ""]
    except (OSError, ValueError):
        pass
    L += ["## ④ 不吃土豆0 竞价T(最机械的开盘 T): 每天首笔 09:25 竞价买、09:30:00~09:30:13 卖, 103 天胜率 72%; 正股竞价高开 ≥2% 时胜率 91%; "
          "选债=前一日全市场转债成交额第一。启示: 竞价强弱是开盘 T 最硬的信号。", ""]
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"做T 知识包 {len(''.join(L))} 字 → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
