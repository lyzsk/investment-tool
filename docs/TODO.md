# investment-tool TODO（v4, 2026-10-09 22:3x 用户令: 删没意义的/写未来）

> 目标函数: **paper=导师筛选器**(看出 A-xxx 谁收益率高) → 策略收益养活订阅费; 终极=对齐 TradingAgents 级多 agent 金融决策平台
> 消费约定: 人读=§1-§2, AI 读=§0 起; ✅ 项不存 git; 【PC1】本机 /【PC2✓】笔记本 /【用户】人动手

---

# §0 行为立法（AI 每轮开工先读；无模型绑定, k3/Claude 继任者同守）

补丁①-⑪(10/8-10/9 立法): ①改名必跑 grep_verify.sh ②改 skills/ 必跑 sync_skills.mjs ③先落盘验证再汇报 ④覆盖前必查已有 ⑤新消息追加不清空队列 ⑥活动队列落盘 §0.5 ⑦做了必报(尾三行) ⑧收尾①②二连不等催 ⑨用户忘了→原样重贴不造文件 ⑩开工三问(沉淀在哪/前置数据看了吗/契约对过吗) ⑪DB/不可逆操作需无歧义动词授权。另: ⑫不动 ~/.claude/settings(用户亲管); ⑬实盘隐私=成交/账户只进 snapshots/(gitignore)。

# §0.5 活动队列（⑥载体: 开工先读/收工更新）

- [✅10/10 凌晨收官] 10/8 补跑 12/12 完链; 回放入账 10/8(10笔)+10/9(30笔)双日 EOD 重算; **两日战报: xingjianye +11.03% > liuyiqing +3.39% > gaogailvfuli +1.51%**(report.html 粗细虚三层配色已生效); distill 天哥14天+卢本圆15天欠账全清; key 轮换立法(kimi-code↔xhj, 撞5h窗切 AUTH_TOKEN)
- [⏰周一] 9:07 监控 cron → 9:15 十三链首考(周末无链, TradingDayUtils 跳非交易日) → 15:05 EOD → 首份实盘全员 report
- [○待拍板] 9/28-30 十一链补跑(36 链≈3-4h, 周末白天挂机正合适; 跑完周一开盘前历史曲线全齐)
- [○欠账] 桃哥 sum 积压 19 条(待额度空档)/distill 0707 断点/3 本 nav 缺口(周一 15:10 fetch 自愈观察)

# §1 主线（按周排）

## 本周(10/12-10/17): 让评价层长出牙

1. **首跑周数据积累**: 十三链全时刻表跑满一周(调度器已修), 每日 EOD+report——收益对比从"只有 taoge 有效"变成全员有效
2. **正例规则蒸馏线**(填 tzzb 导师零规则真空): llm_batch_tzzb 32B 初稿(幂等续跑) → gen_tzzb_cases → 各导师 rules.md → gen_rules_index --embed; 规则带**情境四元组**(行情/阶段/板块/票数行为——用户 10/9 定的渴望目标)
   - ⚠️ chong5000w 特例(10/10 链 06 盲审挂账): 该账本 nav 源僵死止 07-06(7 月起停更), B' 续跑+distill 对本线无增量可提取, 规则库空骨架在源方恢复前无解——期间本线终裁阈值无人格背书, 消费其链产物需知悉折扣
3. **拟人度 v2**: 盘中 facts 注入"导师今晨动仓" + scorer 分型(做T型=核心票覆盖度/计划型=Jaccard+方向) + 负例距离(negstats 已有, 接 scorecard)
4. **user 成长线**: user_trading_cases 三源闭环跑起来(实盘+hermes 钩子+盘面; hermes 钩子待生效后首日合成)

## 下周(10/19+): 对齐 TradingAgents 缺口

5. **消息面 agent**: akshare 资金流/龙虎榜/业绩预告接 facts 公告层(冬测 3/4 通)
6. **03 辩论升分层**: bull/bear 已有 → 加 trader/portfolio manager 层 + 辩论记忆跨日(debate_ledger.md 断言-核销-注入闭环)
7. **组合级风控**: VaP/簇相关性(现只有票级止损)

# §2 等用户裁决（无时效压力, 想到再答）

1. 正例蒸馏预算: 32B 全历史 16 人≈46h vs 近 60 日≈15h?
2. 桃哥 sum 19 条清账时机(任一夜间空档即可, 无需裁决=默认下周某夜)
3. players.json 已建(10/9 晚)——新 5 正例(观察池 top: 东橙西柚13/我在南极拍企鹅/There_1)是否启动 distill 准入观察?

# §3 项目进度快照（10/9 收盘口径）

**已落**: 数据层(tzzb 16 账本/3UP 视频管线/CLS/fage/quotes)/决策层(13 链+03 拆环+05 风控+盲审+负例+否决条款池)/评价层(scorecard+negstats+players.json+相似度 v0)/工程层(调度器修复/replay 模式/幂等三件套/行为立法 13 条)

**TradingAgents 差距**: 分析师团队≈平齐 / 多空辩论雏形(升分层=§1.6) / 风控票级(组合级=§1.7) / 回测估算口径已落(--replay) / 多 LLM 协作已反超(云端+32B 两级)

# §4 持续线（低频维护, 等触发再做）

| # | 项 | 触发 |
|---|---|---|
| 1 | backfill 历史视频(天哥剩 154/卢本圆 99) | 夜间空档, PAUSE 闸管理 |
| 2 | cls wjzt PARSE_FAIL 历史 23 天 | 低优, 闲时 |
| 3 | 数据源共享层 scripts/lib(sources.mjs 统一出口) | PC2 闲时 |
| 4 | venv→.venv 正名(需重建非 mv) | 待 PC 维护窗口 |
| 5 | hermes 钩子产出核查(snapshots/hermes/ 有文件=生效) | 明早首次问答后 |
| 6 | liuyiqing-skill 补建 rules_index.md 或 chain 模板剔除该输入项(10/10 盲审: 索引缺失致捞取验证不可执行, 兜底=直读 rules.md 全文, 登记于 live-20261008/06 §0.6) | 下次碰 liuyiqing persona 时 |
