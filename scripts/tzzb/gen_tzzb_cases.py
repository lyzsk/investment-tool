# gen_tzzb_cases.py — 六人 cases.md 双尾样本库机械重生成(零 token; 2026-10-02 建土豆版, 10/7 泛化六人+直连 gen_tzzb_review)
# 契约(10/7 统一立法, 用户拍板): cases.md 两区共存——
#   机械区"## 执行质量双尾样本库"= 本脚本全量重写(勿手改); 其余区(土豆 curated 手维护 / 五人 LLM 叙事立案)
#   归 tzzb-skill distill 工作流与人维护, 重生成一律保留——数据层机械、归因层 LLM(同事实/推断分层立法)。
# 口径: 全量按日期排序不截断(2026-10-02 用户立法), 阈值=|持收增量|≥5%; 跨日 trip 日期列标"(跨N日)";
#   数据源=gen_tzzb_review.build(六人含跨日; 日涨跌%=卖出日收盘/前收-1, K3 旧 review_cb_daily.json 口径已成历史)。
# 用法: scripts/venv/Scripts/python.exe scripts/tzzb/gen_tzzb_cases.py --ledger <id> | --all
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_tzzb_review import build, LEDGERS  # build(ledger) -> (R, trips); import 时自动载六人日线

ROOT = Path(__file__).resolve().parents[2]
PERSONA_DIR = {lg: ROOT / "skills" / f"{lg}-skill" / "persona" / ("buchitudou0" if lg == "buchitudou0" else ".")
               for lg in LEDGERS}
SEC = "## 执行质量双尾样本库(机械全量, gen_tzzb_cases.py 重生成, 勿手改)"


def row(t):
    cross = "" if t["day"] == t["buy_day"] else \
        f"(跨{(datetime.date.fromisoformat(t['day']) - datetime.date.fromisoformat(t['buy_day'])).days}日)"
    dd = t.get("日涨跌%")
    tail = f"{dd:+.2f}% |" if dd is not None else "— |"
    return (f"| {t['day']}{cross} | {t['name']}({t['code']}) | {t['bt']}→{t['st']} | "
            f"{t['pct'] * 100:+.2f}% | {t['持收增量%']:+.2f}% | {tail}")


def gen(ledger):
    R, trips = build(ledger)
    esc = sorted([t for t in trips if t["持收增量%"] <= -5], key=lambda x: (x["day"], x["code"]))
    fly = sorted([t for t in trips if t["持收增量%"] >= 5], key=lambda x: (x["day"], x["code"]))
    dist = " / ".join(f"{k}×{v}" for k, v in R["持收增量分布"].items())
    sec = f"""{SEC}

口径: 持收增量%=若拿到收盘的增量收益(正=卖飞/负=逃对); 数据源 gen_tzzb_review(六人, 含跨日; 日涨跌%=卖出日收盘/前收-1)。
分布({R['样本']['有日线trip']} 笔): {dist}

### 显著逃顶(持收增量≤-5%, {len(esc)} 笔, 全量)

| 日期 | 标的 | 买→卖 | 单笔 | 持收增量 | 当日涨跌 |
|---|---|---|---|---|---|
{chr(10).join(map(row, esc)) or "(无)"}

### 显著卖飞(持收增量≥+5%, {len(fly)} 笔, 全量)

| 日期 | 标的 | 买→卖 | 单笔 | 持收增量 | 当日涨跌 |
|---|---|---|---|---|---|
{chr(10).join(map(row, fly)) or "(无)"}
"""
    out = PERSONA_DIR[ledger] / "cases.md"
    name = LEDGERS[ledger]
    if ledger == "buchitudou0":
        # 土豆: 全文件模板重生成(curated 区保留)
        m = re.search(r"(## 规则校准反例\(curated 手维护.*?\n)(.*?)(?=\n## )",
                      out.read_text(encoding="utf-8"), re.S) if out.exists() else None
        curated = m.group(2).strip() if m else "(空)"
        body = f"""# {name} · 案例库(反例+执行质量样本)

> 闸门5=五闸门第5条"反例优先"(非 top5 排名)。**全量按日期排序, 阈值口径不截断**(2026-10-02 用户立法)。
> 本文件两区: curated 区手维护(重生成保留); 双尾样本库区由 `scripts/tzzb/gen_tzzb_cases.py` 机械重写(勿手改)。

## 规则校准反例(curated 手维护, 重生成保留)

{curated}

{sec}
"""
        out.write_text(body, encoding="utf-8")
    else:
        # 五人: 只 append/替换机械区, LLM 叙事立案区不动
        old = out.read_text(encoding="utf-8") if out.exists() else f"# {name} cases\n\n(冷启动)\n"
        pat = re.compile(re.escape(SEC) + r".*", re.S)
        new = pat.sub(lambda _: sec, old) if pat.search(old) else old.rstrip() + "\n\n" + sec
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(new, encoding="utf-8")
    print(f"{ledger}: cases.md 双尾区 逃顶{len(esc)}/卖飞{len(fly)} (trips={R['样本']['有日线trip']})")


if __name__ == "__main__":
    if "--all" in sys.argv:
        for lg in LEDGERS:
            gen(lg)
    else:
        i = sys.argv.index("--ledger")
        lg = sys.argv[i + 1]
        if lg not in LEDGERS:
            sys.exit(f"未知 ledger {lg}(可选: {'/'.join(LEDGERS)})")
        gen(lg)
