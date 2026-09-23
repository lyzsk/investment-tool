# investment-tool 总工程 plan（手写代码总纲)

> 目标函数(用户定 2026-09-19): **策略收益必须至少养活 Claude 订阅费**。
> 本文档 = 全部待写代码 + 数据库设计的完整思路。细节模板见 `scripts/k3-inv/docs/落地指南-java-quartz.md`(四层写法/Quartz 接线/坑清单), 本文讲**做什么、分几期、为什么这个顺序**。

## 0. 目标拆解(先把账算清楚)

10 万本金， 订阅费目标(按汇率≈7.25):

| 订阅档 | 月费 | 对应月收益率 | 对应年化 |
|---|---|---|---|
| Pro $20 | ≈145 元 | 0.15% | ≈1.8% |
| Max $100 | ≈725 元 | 0.73% | ≈9.1% |
| Max $200 | ≈1450 元 | 1.45% | ≈19% |

现实参照: 桃哥管线 2 周 +6.39%(样本小, 不可外推, 但方向证明可行); k3 v0.1 两周 -0.70%(不达标, 需 v0.2 修复收益端)。
**结论： 工程优先级 = ①桃哥管线产品化(已验证的利润引擎) ②k3 v0.2 收益修复 ③账户感知+提醒(执行保障)。任何策略都不敢承诺月收益, 所以流程上必须先模拟盘连续验证再谈实盘。**

## 1. 全景图

```
数据层    财联社API ─> cls_telegraph(已有)     B站 ─> 音频 ─> 转写 ─> 纠错(已有脚本)
            东财终端 ─> em.ps1 ─> PNG ─> OCR(已有 Tess4j 域)
              │
存储层        ▼   taoge_* 9 表 + k3inv_* 6 表 + market_quote_daily(新增1表) = 16 表
              │
调度层        ▼   Quartz handlers(DB 驱动, sys_job 插行)
              │   taogeFetch / taogePipeline / k3invSignalCandidate / k3invDailyReport / dfcfSnapshot
              │
智能层        ▼   Claude/hermes: 信号蒸馏、解读提取、威科夫/仲裁、回测裁决(AI 活, 不进 Java)
              │
产出层        ▼   每日作战卡(桃哥信号+k3信号) / 模拟盘 NAV / 周报复盘 / hermes 提醒
```

**分层铁律**: Java = 存储+调度+查询+机械执行(ProcessBuilder 调脚本); AI 判断不进 Java。

---

## Phase 1 — 存储层: 16 表实体化(一切的地基)

### 1.1 建表

```bash
mysql -uroot -proot investment_tool < sql/k3inv.sql    # 6 表(已写好)
mysql -uroot -proot investment_tool < sql/taoge.sql    # 9 表(已写好)
# + 新增 1 张行情表(见下)
```

**新增表: `market_quote_daily`** — 动机: taoge_mention.next_day_ret 回填、k3 信号复盘、模拟盘 NAV, 都需要"某日某票收盘价"这个原子数据; 现在每次现抓腾讯 API 又慢又会限流。只存**关注池**(mention/信号/持仓出现过的票), 几千行/年, 可控:

```sql
-- investment_tool.market_quote_daily definition
-- 关注池个股日线缓存(桃哥提及/k3信号/东财持仓出现过的票才入池)
CREATE TABLE `market_quote_daily` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `trade_date` date NOT NULL,
  `stock_code` varchar(10) NOT NULL COMMENT 'sh600127 格式',
  `stock_name` varchar(50) DEFAULT NULL,
  `open` decimal(10,3) DEFAULT NULL,
  `close` decimal(10,3) DEFAULT NULL,
  `high` decimal(10,3) DEFAULT NULL,
  `low` decimal(10,3) DEFAULT NULL,
  `pct_chg` decimal(8,4) DEFAULT NULL COMMENT '涨跌幅%',
  `vol` decimal(16,2) DEFAULT NULL COMMENT '成交量(手)',
  `amount` decimal(18,2) DEFAULT NULL COMMENT '成交额(元)',
  `status` tinyint DEFAULT '0' COMMENT '0-成功, 1-失败',
  `create_by` bigint DEFAULT NULL,
  `create_time` datetime(6) DEFAULT NULL,
  `update_by` bigint DEFAULT NULL,
  `update_time` datetime(6) DEFAULT NULL,
  `is_deleted` tinyint DEFAULT '0' COMMENT '0-未删除, 1-已删除',
  `delete_by` bigint DEFAULT NULL,
  `delete_time` datetime(6) DEFAULT NULL,
  `remark` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_date_code` (`trade_date`, `stock_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

分钟线(m5)**不入库** — 体积大、时效短(腾讯只给2周), 继续存 `downloads/kline/*.json` 文件, 回测脚本直读。

### 1.2 Java 实体(两个新包, 全部模板复制)

| 包 | 实体数 | 说明 |
|---|---|---|
| `cn.sichu.k3inv`(inv-stock) | 6 | Signal/Watch/Strategy/Run/Decision/Trade, 范例已完整给出(落地指南§2.1) |
| `cn.sichu.taoge`(inv-stock) | 9 | Video/Transcript/Analysis/Mention/Rule/PositionSnapshot/BacktestRun/BacktestDecision/BacktestTrade |
| `cn.sichu.market`(inv-stock) | 1 | QuoteDaily |

**taoge 9 实体的字段要点**(其余照模板):
- json 列全部 `@TableField(typeHandler = JacksonTypeHandler.class)`: Transcript.corrections → `List<Map<String,String>>`; Analysis.operations_today/tomorrow_implication/style_rules → `List<String>`或`Map`; Analysis.full_json → `Map<String,Object>`; Mention.asr_aliases → `List<String>`; Rule.spec/evidence → `Map<String,Object>`/`List<Map<String,Object>>`; PositionSnapshot.positions → `List<Map<String,Object>>`; BacktestRun.config → `Map<String,Object>`
- longtext 列(Transcript.raw_text/fixed_text, BacktestRun.report) → 普通 String, 无 TypeHandler
- decimal 列(Mention.next_day_ret, Trade.pnl/pnl_ratio, Snapshot 四个资金字段) → **BigDecimal**
- Mention.stock_code 可能为空(ASR 只提到名字没对上代码) → 保持可空, 回填时再补

**唯一需要自定义查询的 mapper 方法**(其余 BaseMapper 够用):
```java
// TaogeMentionMapper — 回填次日收益用: 查某日之前所有 verdict='待定' 且 stock_code 非空的提及
List<TaogeMention> selectPendingVerdict(@Param("beforeDate") LocalDate beforeDate);
// MarketQuoteDailyMapper — 批量查某日全池(收盘后回填/NAV)
// (用 LambdaQueryWrapper 即可, 不用自定义)
```

### 1.3 验证
启动不报错 → 仿 `ClsTelegraphServiceImplTest` 写一个测试: 插一条 taoge_rule + 一条 k3inv_signal + 查回。

**工作量**: ~70 个文件, 但 90% 是落地指南§2.1 模板的机械复制, 建议按 "1 个完整 → 验证 → 批量复制"节奏, 一天内可完成。

---

## Phase 2 — 桃哥管线产品化(利润引擎, 最高优先)

现状: 管线脚本(fetch/transcribe/correct/inject)全部就绪且批量验证过 234 天, 但**每日增量靠手动**。目标: 桃哥发视频 → 次日开盘前自动产出"今日作战卡"。

### 2.1 Handler 两个(ProcessBuilder 调脚本, 先例 = MarkdownFormatServiceImpl)

**`taogeFetchHandler`**(cn.sichu.taoge.handler, Bean 名同名):
```
做什么: ProcessBuilder 跑 `node scripts/bilibili-taoge/fetch_taoge.mjs`,
        解析其 stdout 的新视频列表, 新 bvid 插 taoge_video 表
为什么: 轻探测(几秒)和重转写(几分钟~几十分钟)必须拆开, 否则重活拖累调度线程;
        失败重试粒度也完全不同(探测失败无所谓, 转写失败要告警)
cron: 0 0/30 18-23 ? * *   (桃哥复盘视频都在盘后~深夜发, 每30分钟探测)
```

**`taogePipelineHandler`**:
```
做什么: 查 taoge_video 中有视频但 taoge_transcript 无记录的 bvid,
        逐个串行: 下载音频(playurl) → venv python transcribe.py → correct_names.py → inject_md.mjs
        每步检查 exit code, 全成功才插 taoge_transcript(raw_text/fixed_text/corrections 落库)
为什么: 管线四步有严格顺序依赖(标准管线顺序: transcribe → correct_names → inject/extract),
        放同一个 handler 串行执行, @DisallowConcurrentExecution 天然防重入
cron: 0 40 20,22 ? * *   (20:40 和 22:40 各跑一次, 覆盖他发视频的时间窗; 无新视频秒退)
misfire_policy: 0-立即执行(转写补跑有意义, 与行情任务相反!)
```

**ProcessBuilder 要点**(从 MarkdownFormatServiceImpl 抄的时候注意):
1. 工作目录必须 `directory(new File(项目根))`, 脚本里是相对路径;
2. 读干 stdout/stderr 两个流(各起一个线程/或用 redirectErrorStream), 否则缓冲区满死锁;
3. 超时控制 `waitFor(30, TimeUnit.MINUTES)` — transcribe 单视频 medium 模型可能十几分钟;
4. python 要用 venv 的绝对路径: `scripts/bilibili-taoge/venv/Scripts/python.exe`。

### 2.2 解读提取(→ taoge_analysis + taoge_mention): 留在 AI 侧

转写文本 → 结构化解读(大盘判断/操作/明日策略/风格规则)是 LLM 活, **不要试图在 Java 里做**。
流程约定: pipeline handler 跑完在 sys_job_log 里留下"待提取: [日期列表]" → Claude(每日定时会话/hermes)读 fixed_text 做提取, 通过一个小 REST 接口或直接 SQL 写库。
**需要写一个 `TaogeAnalysisController`**(仿 ClsTelegraphTestController): `POST /taoge/analysis/save` 接收提取 JSON 落 taoge_analysis + taoge_mention 两表(一个 @Transactional 方法, 主子表一起写)。这是 AI→DB 的唯一入口, 必须有, 否则 AI 写库只能手写 SQL 容易错。

### 2.3 规则库初始化(taoge_rule 种子数据)

pilot-2week 验证过的规则(R1-R9, 含 learned_before)我整理成 SQL INSERT 提供 — **这是一份独立交付物**, 等你 Phase 1 表建好后我给 `sql/taoge_rule_seed.sql`。规则库的运转方式: 每日提取若发现新风格规则 → AI 提议新 rule(enabled=0 待审) → 你确认后 enabled=1 → 进回测引擎候选。

### 2.4 回填闭环(mention → verdict)

**`taogeVerdictBackfillHandler`**(cron: `0 20 15 ? * MON-FRI` 收盘后):
```
做什么: ①把昨日 mention 涉及的股票代码补抓日线入 market_quote_daily(腾讯日线接口)
        ②selectPendingVerdict → 按今日收盘算 next_day_ret → 命中率统计
为什么: 这是桃哥规则库的"计分牌" — 哪类提及(F预测/R规则)真赚钱、哪些是噪音,
        数据多了才能决定规则取舍; 也是 235 天全量提取后正式回测的数据基础
```

### 2.5 验证
手动触发一次 fetch → sys_job_log 有记录; 插一个测试 bvid 跑 pipeline → transcript 落库 + md 注入; POST 一条假 analysis → 两表有数据。

---

## Phase 3 — k3 v0.2 收益修复(不达标项)

v0.1 诊断: 信号太少(2笔/2周) + 强催化永远买不到 + overnight 是唯一有效信号类型。修复分两步走, **先改规格回测, 有效再代码化**:

### 3.1 策略层(我先做, 不用你写代码)
1. STRATEGY.md → v0.2: 新增"报道即涨停 → 次日竞价观察窗"(竞价强度+板块持续性达标则小仓试错); overnight 信号权重上调; 高价股"最小1手"特殊条款;
2. 同一结算脚本重跑 9/01-09/18 对照 v0.1;
3. 有效 → 更新 k3inv_strategy 表新版本行, 进入 3.2。

### 3.2 信号预筛自动化(你写, 减少 AI 阅读量)
**`k3invSignalCandidateHandler`**(cron: `0 0/15 9-15 ? * MON-FRI` 盘中每15分钟):
```
做什么: 扫 cls_telegraph 新进 level=B 电报, 关键词/模式预筛
        ("板块持续走高/涨停/竞价/隔夜美股映射词表") → 候选行插 k3inv_signal
        (strength=NULL = 待 AI 评分状态; summary 存原文摘要)
为什么: AI 每天读 738 条电报不现实也不必要 — 机械预筛砍掉 90% 噪音,
        AI 只看候选做蒸馏打分(更新 strength/quality 判断), 信号延迟从"日级"变"15分钟级"
```
配套: `K3invSignalController` 提供 `POST /k3inv/signal/score`(AI 回写评分) 和 `GET /k3inv/signal/pending`(AI 拉待评分列表)。

### 3.3 模拟盘日常化(paper run)
每周一个 `k3inv_run`(run_type='paper'), 每日决策落 k3inv_decision(带 info_cutoff), 周五结算回填 total_return/win_rate/max_drawdown + report。**连续 4 周 paper 跑赢指数才允许讨论实盘提醒** — 这个门槛写进流程, 防自己骗自己。

---

## Phase 4 — 账户感知层(dfcf 落库 + 操作检测)

目标: hermes 能回答"你现在持仓什么、今天操作了什么、策略建议和你实际操作差多少"。

### 4.1 `dfcfSnapshotHandler`(cron: `0 5 11,15 ? * MON-FRI` 午盘+收盘各一次)
```
流程: ProcessBuilder → powershell em.ps1 -Action read(资金持仓页, 无需翻页无需 RealClick)
      → 读 JSON 拿 PNG 路径 → Tess4j OCR(项目已有 ocr 域, 复用!)
      → 正则解析 总资产/可用资金/证券市值/持仓盈亏 + 持仓表格行
      → 插 taoge_position_snapshot(source='em_ocr')
铁律继承: 盘中运行=用户不在电脑前(工作日); 用户在场禁止运行 → 开关就是 sys_job.status;
        账号掉线(OCR 出 "--")时正常存一行 remark='logged_out', 不算失败
风险: OCR 数字可能错 → 前两周每次快照同时保留 PNG 路径进 remark, 人工抽查准确率;
        准确率不达标则降级为"只存 PNG, 数据由 Claude 读图后 POST 入库"(同 2.2 的 AI 入口模式)
```

### 4.2 操作检测(持仓 diff, 纯 Java 逻辑)
相邻两次 snapshot 的 positions json 做 diff: 数量变化/新出现/消失 → 推断"用户买入/卖出 X 股 Y 票"(价格用当时 market_quote_daily 近似)。暂不入新表, 结果写 remark 或后续加 `dfcf_operation` 表(等你确认 diff 准确率再建, 不提前建表)。
**价值**: 你的实盘操作 vs 桃哥信号 vs k3 信号三方对照表 — 这是"人为确认可行性"阶段的核心证据, 也是 10/13 同向率那种分析的自动化。

### 4.3 当日成交页(-Page 当日成交 -RealClick)
等你重新登录后先手动复验一次翻页坐标, 确认可行再进 handler; 没复验前 handler 只用默认页。

---

## Phase 5 — 提醒链路(阻塞项: hermes 入口)

等你给 hermes 调用方式。届时所有"产出"接过去:
1. 每日 08:30 作战卡(桃哥昨日信号+k3 候选+今日关注);
2. 盘中信号触发(桃哥规则触发/k3 strength≥4 新信号);
3. 持仓异动(diff 检测到你操作了/或持仓票出反向催化)。
技术上都齐了(数据在库里, 调度在 Quartz), 只差出口。

## Phase 6 — 全量验证(后置大活)

235 天转写文本全量 LLM 提取 → taoge_analysis/mention 批量入库 → 用 Phase 2 的回填机制+统一回测引擎跑全周期 → 回答"桃哥风格跨周期是否稳定正期望"。**这决定最终实盘仓位分配**, 但它依赖 Phase 1/2 的表和接口, 所以排最后。

---

## 附 A — 文件/代码总清单(按 Phase)

| Phase | SQL | Java(新文件数) | 脚本改动 |
|---|---|---|---|
| 1 | k3inv.sql 6 + taoge.sql 9 + market_quote_daily 1 | k3inv×24, taoge×36, market×4 (四层×实体) | 无 |
| 2 | taoge_rule_seed.sql(我出) | taogeFetch/taogePipeline/taogeVerdictBackfill 3 handler + TaogeAnalysisController + 回填 service 方法 | fetch_taoge.mjs 输出 JSON 化(便于 handler 解析) |
| 3 | k3inv_strategy 插 v0.2 行 | k3invSignalCandidateHandler + K3invSignalController | settle 脚本参数化(支持 v0.2 规则重跑) |
| 4 | 无(用 taoge_position_snapshot) | dfcfSnapshotHandler + OCR 解析 service + diff 工具类 | em.ps1 输出加 PNG 路径字段(已有) |
| 5 | 无 | 无(复用现有数据) | hermes 侧接入(等你入口) |
| 6 | 无 | 批量提取的导入接口 | 235天提取脚本(我已具备能力, 届时跑) |

## 附 B — sys_job 插行汇总(按 Phase 顺序执行)

```sql
-- Phase 2
INSERT INTO sys_job (job_name, job_group, job_handler_name, cron_expression, misfire_policy, status, remark)
VALUES ('桃哥新视频探测', 'taoge', 'taogeFetchHandler', '0 0/30 18-23 ? * *', 2, 0, '盘后每30分钟探测新视频落taoge_video');
INSERT INTO sys_job (job_name, job_group, job_handler_name, cron_expression, misfire_policy, status, remark)
VALUES ('桃哥转写管线', 'taoge', 'taogePipelineHandler', '0 40 20,22 ? * *', 0, 0, '转写→纠错→注入→落库, misfire立即补跑');
INSERT INTO sys_job (job_name, job_group, job_handler_name, cron_expression, misfire_policy, status, remark)
VALUES ('桃哥提及回填', 'taoge', 'taogeVerdictBackfillHandler', '0 20 15 ? * MON-FRI', 2, 0, '收盘后抓日线+回填next_day_ret/verdict');
-- Phase 3
INSERT INTO sys_job (job_name, job_group, job_handler_name, cron_expression, misfire_policy, status, remark)
VALUES ('k3信号预筛', 'k3inv', 'k3invSignalCandidateHandler', '0 0/15 9-15 ? * MON-FRI', 2, 0, '盘中扫电报生成候选信号strength=NULL');
INSERT INTO sys_job (job_name, job_group, job_handler_name, cron_expression, misfire_policy, status, remark)
VALUES ('k3信号日报', 'k3inv', 'k3invDailyReportHandler', '0 30 15 ? * MON-FRI', 2, 0, '收盘汇总当日信号与观察名单');
-- Phase 4(默认暂停 status=1, 你在场规则确认后改0)
INSERT INTO sys_job (job_name, job_group, job_handler_name, cron_expression, misfire_policy, status, remark)
VALUES ('东财账户快照', 'dfcf', 'dfcfSnapshotHandler', '0 5 11,15 ? * MON-FRI', 2, 1, 'em.ps1截图+OCR落taoge_position_snapshot; 用户在场时保持暂停');
```

## 附 C — 全局风险与原则

1. **不提前建表**: 每期先用文件/SQL 手工验证数据形态, 形态稳定才固化成表(dfcf_operation 就是例子);
2. **AI 活不进 Java**, 但 AI 写库必须走 Controller 事务入口, 不手写裸 SQL(主子表一致性);
3. **所有调度留痕**: handler 返回可读摘要进 sys_job_log, 这是你唯一的执行回执;
4. **模拟盘 4 周门槛**: 任何策略未连续 4 周 paper 跑赢基准, 不出实盘提醒 — 防过拟合防自嗨;
5. **回测口径三件套永远不变**: learned_before / info_cutoff / 下一根 m5 bar 开盘价 — 任何新策略继承同一诚实标准。

*相关文档: scripts/k3-inv/docs/落地指南-java-quartz.md(写法模板) | scripts/k3-inv/STRATEGY.md | scripts/bilibili-taoge/backtest/runs/pilot-2week/report.md | scripts/k3-inv/backtest/runs/k3-v0.1-20260901_0918/report.md*
