# investment-tool 总 TODO（唯一工作清单）

> 目标函数（2026-09-19 用户定）：策略收益至少养活 Claude 订阅费（10 万本金：Pro≈年化 1.8% / Max$100≈9.1% / Max$200≈19%）。
> 在用路线（2026-10-02 终裁）：**taoge-skill + cb-skill** 两条线 + fage-skill（盘前推演第三导师，已建线）；scripts/ 按域分目录见 `scripts/README.md`。
> 核销口径：fage 58 天纯命中 0.553/含半 0.702（`skills/fage-skill/persona/score.json`，`node scripts/md/gen_scorecard.mjs` 重算）。

---

## A. 假期可做（2026 国庆）

1. **桃哥选股 IC/IR 记分**：定义"提及强度"口径（提及次数/语气/仓位动作→分值）→ 次日收益（东财日线，依赖 A2）→ Spearman 秩相关 IC + IR（IC 均值/标准差 rolling）。落点=gen_scorecard.mjs 的 SRCS registry 加 taoge 源。
   - 与"分类命中率分层"区别：命中率=二值方向断言的对错（发哥推演用这种）；IC=连续强度信号与收益的相关性（桃哥提及用这种）。**两者并存**，各服务各的信号形态，不是替代关系。
2. **个股日线 kline 归档**：`scripts/quotes/` 加个股日线（东财 kline 接口，日线无 5 天窗口限制，可回补历史）。用途=支撑/区间/方向机械判断，供 taoge-distill 核销"突破/跌破/区间"类断言 + taoge-skill 01 facts。
3. **fage persona 复审**：rules.md 立法=每 +20 核销样本复审（v1=165 条沉淀，现 175 条，到 ~185 触发）。
4. **git filter-repo 抹 strategy/ 历史**（用户执行，命令已在 10/2 会话给出；先备份 clone）。

## B. taoge-skill 工程化（顺序=用户指定，1-2 已✅）

1. **chain 驱动器重建**：契约=`skills/taoge-skill/workflows/chain.md`（七步+盲审；盘中子链 02→04→06）；原 run_taoge_chain.py 随 plan-a 删除，按契约重新实现（contract JSON 机械校验/单步回炉≤2/全链回溯重验/--steps 子链/--review）。
2. **盘中重跑三定义**：状态=当日 decisions/；监听=sentinel；矛盾=决策版本号+显式"维持/取代"。
3. **上下文分级加载**：rules.md 的 ### Bxx 头→rule_index.md；常驻=元指令+索引+profile；02 定市况后 grep 捞全文。不上向量库。
4. **eval 双轴**：①golden test=md 桃哥小节半自动提取→≤info_cutoff 回放对比；②决策质量=历史回放（m5 次根开盘价口径）。
5. **双轨合并**：rules.md 唯一 canonical；rules_spec.md=纯溯源；机器子集脚本生成禁手写。
6. **小件**：state_digest.md / params.yaml / skills/taoge-skill/CHANGELOG.md。

## C. 持续线（日常/等发令）

1. **backfill 下载层 45 待办**：等用户发令"开始/继续"；PAUSE=`scripts/backfill_taoge/PAUSE`。
2. **夜跑 distill**：断点 2026-07-07（账本=`scripts/backfill_taoge/distill_state.json`，done=88 天）；恢复语义=skill/代码没变读账本续，变过=归零器全量重跑；有 token 才跑；7/29 跳空待补（`--bvid BV1sv3C6tEpN`）。
3. **夜跑疑问**：回放帧 16 例（凡错位以最新 backfill 为准；taoge-sum 待加"回放帧过滤+跨日同值检测"规则）+ distill 产出人工审核。
4. **tzzb 线**：①五闸门 LLM 审议层首跑（漂移触发式，未触发）；②op 字段语义破译；③转债情绪数据（H5 欠定项）；④cb 分时竞价时段字段实盘验证。
5. **cls wjzt 解析器**：23 天 PARSE_FAIL 遗留（误锚"股票名称"表头），Java 侧顺手修。
6. **persona 反问 BUG**（9/29 实录）：persona 头加元指令"任务优先于扮演"+harness 哨兵，修好重跑 live 链路。
7. **fage 权重定级**：2-3 周核销 alpha 验证后定他在 taoge-skill chain 01 facts 的权重（此前只作参考；persona/rules.md v1 已沉淀：风险回避类零打脸权重最高，恐慌段左侧乐观降权）。
8. **牧原做 T**：挂单参数=每次现算近 30 日振幅分布（不建常备卡）；R-PNL-TRUE 口径=账户级，已实现亏损不因股价回来自动恢复。

## D. 后排大活（回测期/阻塞中）

1. **存储层 Phase 1**：Java 实体 cn.sichu.taoge×9 / market×1 / cb×1 + 验证测试 + `sql/taoge_rule_seed.sql`（R1-R14 带 learned_before）。DDL 见附录 A。
2. **TaogeAnalysisController + taogeVerdictBackfillHandler**：AI→DB 唯一事务入口；提及票补日线算 next_day_ret=规则库计分牌（与 A1 的 IC/IR 合流）。
3. **账户感知**：成交 txt→入库格式（等语料攒几次再定，不提前建表）；live_account.md 变化时更新。
4. **高手语料第 5 梯队**：moni 模拟大赛首验 / 淘股吧实盘赛（需 cookie）；未实测：moni 是否需登录、tgb 未登录可见层级。
5. **结构件 P1**：live_state.json 单一账本 / 条件化参数引擎 / 评估管线 / 角色拆分。
6. **hermes 提醒链路**（阻塞在用户给入口）/ **全量验证回测** / **桃哥拟人化**（方向已定：人格画像+辩论流程+延迟结算闭环；先沉淀 2-3 周预案 vs 实际对照再谈人格 prompt）。
7. **遗留小件**：终裁→watchlist 自动桥 / 中国电影票房预测方法论（过渡期=人工搜索+深度思考）。

---

# 附录 A — market_quote_daily DDL（Phase 1 用）

```sql
CREATE TABLE `market_quote_daily` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `trade_date` date NOT NULL,
  `stock_code` varchar(10) NOT NULL COMMENT 'sh600127 格式',
  `stock_name` varchar(50) DEFAULT NULL,
  `open` decimal(10,3) DEFAULT NULL, `close` decimal(10,3) DEFAULT NULL,
  `high` decimal(10,3) DEFAULT NULL, `low` decimal(10,3) DEFAULT NULL,
  `pct_chg` decimal(8,4) DEFAULT NULL COMMENT '涨跌幅%',
  `vol` decimal(16,2) DEFAULT NULL COMMENT '成交量(手)',
  `amount` decimal(18,2) DEFAULT NULL COMMENT '成交额(元)',
  `status` tinyint DEFAULT '0' COMMENT '0-成功, 1-失败',
  `create_by` bigint DEFAULT NULL, `create_time` datetime(6) DEFAULT NULL,
  `update_by` bigint DEFAULT NULL, `update_time` datetime(6) DEFAULT NULL,
  `is_deleted` tinyint DEFAULT '0', `delete_by` bigint DEFAULT NULL,
  `delete_time` datetime(6) DEFAULT NULL, `remark` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`id`), UNIQUE KEY `uk_date_code` (`trade_date`, `stock_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

分钟线（m5）不入库；分时归档走 `downloads/quotes/`。taoge 9 实体要点：json 列用 JacksonTypeHandler；decimal→BigDecimal；唯一自定义 mapper=`TaogeMentionMapper.selectPendingVerdict`。

# 附录 B — ProcessBuilder 要点（Java 调脚本）

1. 工作目录 `directory(new File(项目根))`，脚本相对路径
2. 读干 stdout/stderr 两流防死锁；超时 `waitFor(30, MINUTES)`
3. python 顺序：先 `scripts/venv/Scripts/python.exe` 再 PATH
4. misfire：转写补跑=0 立即；行情=2 丢弃

# 附录 D — 纪律与红线（写代码时别丢）

1. 回测口径三件套：learned_before / info_cutoff / 下一根 m5 bar 开盘价成交
2. AI 活不进 Java；AI 写库走 Controller 事务入口；不提前建表
3. 模拟盘 4 周门槛：未连续 4 周 paper 跑赢基准不出实盘提醒
4. `R-PNL-TRUE`：盈亏=账户级（市值+现金 vs 初始投入）
5. `R-FACTOR`：因子加权一致性<0.6 禁给>50%
6. 审计红线：持仓变动必须有成交记录+哈希链
7. 目标校准：第一年=月度胜率>60%+回撤<10%+跑赢大盘 20-40pt
8. 概率纪律：主剧本>50% 自信；小概率只留单一尾部

# 附录 E — 业界参考摘要（D6 用）

1. **TradingAgents**：多角色辩论→抄辩论制原型，角色砍 2 个
2. **AI Hedge Fund**：人格=可执行规则集非风格 cosplay
3. **AlphaArena/nof1.ai**：盈亏差异在风控不在预测；简单 prompt+好工具>复杂 prompt+差工具；净值是唯一指标
4. **Qlib+RD-Agent**：假设→代码→回测→反馈闭环→穷人版=案例卡→规则→回放→沉淀
