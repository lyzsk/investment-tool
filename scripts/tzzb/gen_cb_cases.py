# gen_cb_cases.py — cb-skill cases.md 机械重生成(零 token, 2026-10-02)
# 口径(用户立法): 反例全量进 cases.md 按日期排序, 不搞固定 topN, 阈值=|持收增量|≥5%;
#  curated 区(规则校准反例)手维护, 重生成时保留; 双尾样本库区机械重写, 勿手改。
# 用法: scripts/venv/Scripts/python.exe scripts/gen_cb_cases.py(先跑 review_cb_daily.py --json)
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # investment-tool/(10/2 迁入 scripts/tzzb/)
REVIEW = ROOT / "scripts" / "backfill_taoge" / "review_cb_daily.json"
OUT = ROOT / "skills" / "cb-skill" / "persona" / "cases.md"

r = json.load(open(REVIEW, encoding="utf-8"))["summary"]

def lines(trips, key):
    return [f"| {t['day']} | {t['name']}({t['code']}) | {t['bt']}→{t['st']} | {t['pct']*100:+.2f}% | "
            f"{t['持收增量%']:+.2f}% | {t['日涨跌%']:+.2f}% |" for t in sorted(trips, key=lambda x: (x["day"], x["code"]))]

fly = r["显著卖飞(≥5%)"]; esc = r["显著逃顶(≤-5%)"]
# summary json 里深度区是全量明细, 显著区只有笔数——显著全量从 trips 重取
trips = json.load(open(REVIEW, encoding="utf-8"))["trips"]
fly_all = [t for t in trips if t["持收增量%"] >= 5]
esc_all = [t for t in trips if t["持收增量%"] <= -5]

curated = ""
if OUT.exists():
    m = re.search(r"(## 规则校准反例\(curated 手维护.*?\n)(.*?)(?=\n## )", OUT.read_text(encoding="utf-8"), re.S)
    if m:
        curated = m.group(2).strip()
if not curated:
    curated = "(空)"

dist = " / ".join(f"{k}×{v}" for k, v in r["持收增量分布"].items())
out = f"""# 不吃土豆0 · 案例库(反例+执行质量样本)

> 闸门5=五闸门第5条"反例优先"(非 top5 排名)。**全量按日期排序, 阈值口径不截断**(2026-10-02 用户立法)。
> 本文件两区: curated 区手维护(重生成保留); 双尾样本库区由 `scripts/gen_cb_cases.py` 机械重写(勿手改)。

{curated and ""}## 规则校准反例(curated 手维护, 重生成保留)

{curated}

## 执行质量双尾样本库(机械全量, gen_cb_cases.py 重生成, 勿手改)

口径: 持收增量%=若拿到收盘的增量收益(正=卖飞/负=逃对); 数据源 review_cb_daily.json。
分布(435 笔): {dist}

### 显著逃顶(持收增量≤-5%, {len(esc_all)} 笔, 全量)

| 日期 | 标的 | 买→卖 | 单笔 | 持收增量 | 当日涨跌 |
|---|---|---|---|---|---|
{chr(10).join(lines(esc_all, "esc"))}

### 显著卖飞(持收增量≥+5%, {len(fly_all)} 笔, 全量)

| 日期 | 标的 | 买→卖 | 单笔 | 持收增量 | 当日涨跌 |
|---|---|---|---|---|---|
{chr(10).join(lines(fly_all, "fly"))}
"""
OUT.write_text(out, encoding="utf-8")
print(f"cases.md 重生成: 逃顶 {len(esc_all)} / 卖飞 {len(fly_all)} + curated 保留")
