---
name: telegraph-skill
description: 财联社加红电报知识 skill(10/23 建, 用户批)——没有人格、按案例驱动: 电报点名票点名后 / 次日怎么走的全市场统计(避雷为主); 规则每晚由统计脚本重算(带样本 / 置信 / 截至日); 给全部 paper 线和实盘问答当刹车用。
---

# telegraph-skill · 加红电报（2026-10-23 建）

- 定位: **知识 skill**，不是导师 skill：没有人格，规则 = 统计结论，案例 = 正反面点名事件
- 结论现状: 能买进的点名票次日平均亏（≈ −0.9%），= **避雷信息**，是刹车不是买入信号；点名时还没见顶的相对好一些
- 生成: `scripts/test/telegraph_validate.py`（逐事件）→ `telegraph_nextday.py`（次日表）→ `telegraph_skill.py`（写 rules / cases + 索引），每晚 check md 跑；历史回溯 `telegraph_backfill.py`（2026-01-14 起，通达信历史分时）
- 消费方: paper v3 第二层资料目录（`./q` 查）+ 必查（候选当天被电报点名时加一行）；实盘问答 order-skill 也可读
- 不进导师名单（不在 mentors 登记表、没有 workflows/chain.md / cases_auto.jsonl）
