---
name: nasdaq-skill
description: 纳指 skill(品种 skill, 10/18 建)——A 股场内纳指 ETF 做 T 的规律沉淀: 现标的 纳指ETF(广发) 159941; 白天美股休市、价格跟纳指期货 + 溢价走, T+0; 给决策 T 账本 A-dndq 用, 每天收盘按事后最优 T 追加日卡、每周复核规则进化。
---

# nasdaq-skill · 纳指 skill（2026-10-18 建）

- 定位: 用户计划资产再多时拿 1 万做 T 纳指 ETF; 先在 paper 验证

- 结构: SKILL.md 薄路由 + persona/{profile,rules,cases}.md + workflows/distill.md; **品种 skill, 不是导师 skill**: 不进 tzzb_ledgers.json、没有 chain.md、不跑导师链
- 消费方: `scripts/dfcf/paper/t_decide.py` 的 A-dndq 账本每次决策内联读本 skill(profile 数据画像 + rules + cases 最近 10 张) + 共用的 `t_knowledge.md`(全体导师做 T 正反面)
- 三本对照: 决策T A-dndq(花 token) / 机械T A-tndq(t_bot.py 零 token) / 不T A-hndq(只拿底仓); 每天收盘 t_review.py 算事后最优 T → 追加一张日卡进 persona/cases.md
- 进化: persona/profile.md 的 AUTO 数据画像每晚 t_skill.py 重算(零 token); rules.md 每周按 workflows/distill.md 用日卡复核(LLM, 一周一次)
- 版本: 走 persona_versions.py 全 skill 版本流(和导师 skill 同口径)
