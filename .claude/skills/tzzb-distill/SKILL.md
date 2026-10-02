---
name: tzzb-distill
description: "Use when tzzb-sum 合成后反向核销/更新 cb-skill rules: 机械层零token重跑画像+复盘+cases, 关键统计漂移或证伪条件触发才 LLM 审议(每日 check md 链条 tzzb 侧第三棒/用户喊核销转债规则时)"
---

# tzzb-distill · 转债高手行为 → cb-skill 规则反向核销

> 建立: 2026-10-02(用户拍板: tzzb 对齐 taoge 三棒链, 但形态不同——桃哥 distill 语言(重 LLM),
> 土豆 distill 行为统计(重机械, LLM 只审漂移))。
> 串行链: tzzb-fetch(Java cron) → **tzzb-sum**(腿→md 小节) → **tzzb-distill**(md/腿→cb-skill rules 核销)。

## 与 taoge-distill 的本质差异

| | taoge-distill | tzzb-distill |
|---|---|---|
| 原料 | 语言(他说了什么) | 行为(他做了什么, 秒级腿) |
| 核销主体 | LLM 逐条读 md 判断 | **机械统计重跑+阈值比对**(零 token) |
| LLM 出场 | 每日 | 仅漂移/新标的/证伪触发时 |
| 目的地 | taoge-skill/persona | cb-skill/persona(rules.md + cases.md) |

## 流程(两步, 顺序不可换)

### 第一步: 机械层(零 token, 每日必跑)

```bash
scripts/venv/Scripts/python.exe scripts/tzzb/profile_bchitudou0.py          # 画像全量重跑(435 腿统计+T-1联动)
scripts/venv/Scripts/python.exe scripts/tzzb/review_cb_daily.py --json scripts/backfill_taoge/review_cb_daily.json
scripts/venv/Scripts/python.exe scripts/tzzb/gen_cb_cases.py                # cases.md 双尾样本库区重生成(curated 保留)
```

比对 rules.md 各 R 的记录值, 漂移阈值(任一命中→第二步):
- 胜率/盈亏比漂移 ±3pp 以上; 首买通道分布(09:25/09:30死窗/追单)漂移 ±5pp
- **新标的首次入场**(滚动熟票池换血=R4 活体信号, 必报)
- 出现 rules.md 任一条"证伪条件"描述的实例(如午后开仓/持仓>5分钟成簇/单笔名义>20万成簇)
- 显著卖飞/逃顶新增样本与既有结论矛盾(如逃顶样本出现在大涨日)

无漂移: 只把 rules.md 各 R 的"验证状态"样本数刷成最新, 收工(静默, 不打扰)。

### 第二步: 核销层(LLM, 仅触发时)

1. 对触发涉及的规则逐条过五闸门(cb-skill/persona/rules.md §五闸门), 结论只许:
   兑现(样本数+1, 追加验证记录行) / 打脸(降级或作废但不删除, 移 cases.md curated 区立案) / 欠定保留
2. 新模式要进 rules.md 必须过完整五闸门模板(竞争假设≥2 + 可证伪条款), 否则只进 cases.md
3. **反例优先**: 他违反自己规则的操作优先记 cases.md curated——反例比正例更校准画像

## 纪律

1. **时间纪律**: 核销=用后见验证前瞻规则, 天然无未来函数; 但写"决策原因"类推断仍只许 T-1 及更早信息
2. 机械层数字禁止手改(要改就改脚本重跑); LLM 只写核销结论与验证记录
3. 双副本: 本文件编辑后 `cp skills/tzzb-distill/SKILL.md .claude/skills/tzzb-distill/SKILL.md`
4. 📜 过程性事件(漂移核销/规则废立)追加到 `skills/tzzb-sum/PROCESS.md`(与 sum 共用一份过程账)
