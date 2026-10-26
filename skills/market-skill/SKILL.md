---
name: market-skill
description: 盘面共性知识 skill(知识 skill, 10/23 建; 10/25 并入原 kline-skill + 原 order-skill 里的市场观点)——没有人格、按案例驱动: 强势股次日溢价 / 涨停回调 / 情绪分化 / 炸板次日等全市场统计 + K 线 / 量价 / 箱体 / 威科夫 / 波浪的机械定义和统计 + 用户发现的盘面规律(假设, 每晚核销); 每条带样本数 / 置信 / 截至日 / 来源; 06 输出后市看法时和统计概率一起用。
---

# market-skill · 盘面共性知识（2026-10-23 建，用户批）

- 定位: **知识 skill，不是导师 skill**——没有人格、不模仿谁；规则来自全市场统计（行情库日线 + 强势股次日溢价库 + 导师逐笔对照），每条带证据
- 结构: SKILL.md + persona/{profile,rules,cases}.md（+ 自动生成的 rules_index / cases_index）；**不进导师名单**（不在 tzzb_ledgers / mentors 登记表、没有 workflows/chain.md、没有 cases_auto.jsonl），所以导师链 / 做T 知识包 / 逐笔挖掘这些按导师遍历的脚本都不会读到它
- 消费方: paper v3 拟人线材料包第一层（`scripts/paper_line/pack.py` 的「盘面共性知识」节，规则全文）；案例在第二层按需查
- 和导师规则冲突时: 导师规则决定"做什么", 本 skill 给"统计上 / K 线结构上大概率怎么走"; 要偏离导师就写明依据哪条 M / KD / KS / U 编号(记忆: 教训可让 skill 偏离导师, 只要变好)
- **10/25 用户定**: 不是风控刹车(05 是机械的), 是 **06 输出的一环**——06 给每只票的后市看法时, 统计概率 + K 线结构(箱体位置 / 结构 / 事件)一起给; 同时用于沉淀和复盘
- 进化: 规则由统计脚本重算更新（不人工蒸馏），每条写"截至日"；新知识卡（炸板 / 回封、情绪周期）做完后追加

## 文件(10/25 合并后)
- `persona/rules.md` M 系列: 全市场统计(强势股次日 / 涨停回调 / 情绪 / 炸板次日)
- `persona/kline_rules.md` KD 定义(箱体 = 段式, 级别 日线 / 1 / 5 / 15 / 30 / 60 / 120 分钟; 涨跌停; 威科夫事件; 蜡烛图形态; 10/25 并入原 docs/knowledge: KD7 箱体五阶段 / KD8 威科夫区间阶段 / KD9 缠论 / KD10 波浪)+ KS 统计(10/25 用户点头, KS7 仍是假设)
- `persona/kline_cases.md` K 线案例: 学习来源索引 + 用户考题 + 看图收件箱(`scripts/kline_study/kline_inbox.py`)每晚自动对答案追加
- `persona/user_found.md` U 系列: 用户发现的盘面规律(状态 = 假设, 每晚零 token 核销, 够样本升 M / KS)
- `references/kline_study/` K 线研究证据底稿(10/25 从 docs/kline_study 搬来, 用户定 docs/ 只放给人读的和交互衔接): 读书笔记 book_*.md / 回测 backtest*.md / 定义 definitions.md / 统计推断 / 图 img/; KS 结论的「来源」指向这里; `scripts/kline_study/*` 往这里写; **不进实盘线材料**(pack 只读 persona/ 下指定文件)
- 隐私: 只写规律和全市场数据, 不写用户持仓 / 成交
## 工具(零 token)
- `scripts/paper_line/tools/kline_struct.py`: 必查「K线结构」(日线 + 15 分钟段式箱体 / ATR / 近 60 日结构), 盘中每次触发重算
- `scripts/kline_study/`: draw_box(箱体图)/ annotate_shot(截图标注)/ scen_next(次日 + 3 日情景)/ draw_future(原图续画 3 日)/ tape(买卖腿 × 3 秒盘口)/ intake + kline_inbox(截图收件 → 案例 → 三次核销)/ ocr_shot(截图 OCR)
- `scripts/tzzb/board_entry.py`: 导师板型买点(写进各导师 fingerprint.md 第十节)
- `scripts/test/board_knowledge.py`: 炸板 / 回封 / 反包板知识卡(`docs/research/board_reseal_20261023.md`)
