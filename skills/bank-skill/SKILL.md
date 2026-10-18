---
name: bank-skill
description: 银行股 skill(品种 skill, 10/18 建)——A 股国有大行做 T + 长持的规律沉淀: 现标的 中国银行 601988; 低波动、高股息、上证权重、熊市护盘属性; 给决策 T 账本 A-dbank 用, 每天收盘按事后最优 T 追加日卡、每周复核规则进化。
---

# bank-skill · 银行股 skill（2026-10-18 建）

- 定位: 用户计划资产到 12 万后拿 1 万做 T 银行(长持吃分红 + 日内 T 降成本); 先在 paper 验证
- 为什么叫"银行股"不叫"红利": 红利股内部差别太大(煤炭=周期、高速/水电=公用事业、银行=权重护盘), 做 T 参数取决于波动行为, 一个 skill 只管一类行为(高内聚); 以后要做别的红利股再开新 skill

- 结构: SKILL.md 薄路由 + persona/{profile,rules,cases}.md + workflows/distill.md; **品种 skill, 不是导师 skill**: 不进 tzzb_ledgers.json、没有 chain.md、不跑导师链
- 消费方: `scripts/dfcf/paper/t_decide.py` 的 A-dbank 账本每次决策内联读本 skill(profile 数据画像 + rules + cases 最近 10 张) + 共用的 `t_knowledge.md`(全体导师做 T 正反面)
- 三本对照: 决策T A-dbank(花 token) / 机械T A-tbank(t_bot.py 零 token) / 不T A-hbank(只拿底仓); 每天收盘 t_review.py 算事后最优 T → 追加一张日卡进 persona/cases.md
- 进化: persona/profile.md 的 AUTO 数据画像每晚 t_skill.py 重算(零 token); rules.md 每周按 workflows/distill.md 用日卡复核(LLM, 一周一次)
- 版本: 走 persona_versions.py 全 skill 版本流(和导师 skill 同口径)
