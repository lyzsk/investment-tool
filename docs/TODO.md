# investment-tool 总 TODO（唯一工作清单）

> 目标函数（2026-09-19 用户定）：策略收益至少养活 Claude 订阅费（10 万本金：Pro≈年化 1.8% / Max$100≈9.1% / Max$200≈19%）。
> 在用路线（2026-10-02 终裁）：**taoge-skill + cb-skill** 两条线 + fage-skill（盘前推演第三导师，已建线）；scripts/ 按域分目录见 `scripts/README.md`。
> 核销口径：fage 58 天纯命中 0.553/ 含半 0.702（`skills/fage-skill/persona/score.json`，`node scripts/md/gen_scorecard.mjs` 重算）。

---

## 优先级图例（2026-10-03 立法）

- **★★★** = 10/9 paper 首跑前必须落地；**★★** = 窗口期该做；**★** = 等触发/后排
- **【PC2✓】** = 笔记本可干（仅需 git 内容+公网）；**【PC1】** = 绑本机数据/application；**【用户】** = 只能用户动手
- **10/4 9:00→10/7 12:00 PC2 窗口执行序**：①C7 三件套 ②C9 死链 ③C10 matcher 拒买 ④A1 IC/IR ⑤C6 错表 ⑥B6 小件 ⑦A3/B5/C3 捡漏
- 10/8 回 PC1：`git pull` → 首跑前检查；10/9 首跑（§E 待办）

---

## A. 假期可做（2026 国庆）

1. 【★★ PC2✓】**桃哥选股 IC/IR 记分**：定义 "提及强度" 口径（提及次数 / 语气 / 仓位动作→分值）→ 次日收益（东财日线，依赖 A2）→ Spearman 秩相关 IC + IR（IC 均值 / 标准差 rolling）。落点=gen_scorecard.mjs 的 SRCS registry 加 taoge 源。
    - 与"分类命中率分层"区别：命中率=二值方向断言的对错（发哥推演用这种）；IC=连续强度信号与收益的相关性（桃哥提及用这种）。**两者并存**，各服务各的信号形态，不是替代关系。
2. 【★★ PC2✓ 写码 / 跑量回 PC1】**个股日线 kline 归档**：`scripts/quotes/` 加个股日线（东财 kline 接口，日线无 5 天窗口限制，可回补历史）。用途= 支撑 / 区间 / 方向机械判断，供 taoge-distill 核销 "突破/跌破/区间" 类断言 + taoge-skill 01 facts。注意：归档目录 gitignored，PC2 跑出的数据不回流，只写码+ 小样本自测。
3. 【★ PC2✓】**fage persona 复审**：rules.md 立法= 每 +20 核销样本复审（v1=165 条沉淀，现 175 条，到 ~185 触发）。
4. 【★ PC1 用户】**git filter-repo 抹 strategy/ 历史**（用户执行，命令已在 10/2 会话给出；先备份 clone）。

## B. taoge-skill 工程化（顺序= 用户指定，1-2 已✅）

1. **chain 驱动器重建**：✅ 已建（10/2）`scripts/taoge-chain/run_taoge_chain.py`（契约源=chain.md 模板机械抽取；contract JSON 重算校验 / 单步回炉≤2/ 回溯重验 /--slot 映射 /--review/06 actions 机械转 plans 行+ 版本链 CXL/token 台账落 paper/token_log.csv；--selftest PASS：正例不误杀+5 反例全抓；--dry 全链冒烟通过）。剩= 真 token 首跑验证。
2. **盘中重跑三定义**：状态= 当日 decisions/；监听=sentinel；矛盾= 决策版本号+ 显式 "维持/取代"。
3. **上下文分级加载**：✅ B3 已落地（10/3）`scripts/md/gen_rules_index.mjs`（134 条 ### Xnn 头→rules_index.md 23.3 KB，带 ✅⏳❌ 状态标+ 前 2 条正文要点备注+ 行号跳转链接）；chain.md 六步 prompt 全改 "索引常驻+grep 按需捞，禁全量读 rules.md（239KB)"；驱动器每轮起跑前自动重建索引防 stale。不上向量库。**验证口径（每次冒烟/首跑必看）**：①盲审第⑤维度= 规则漏用抽检（专盯 C 类祖训撞上未回避）；②07 复盘「规则引用审计」节= 引用清单+ 漏捞嫌疑+ 备注改写建议；③决策质量对照 9/28 冒烟基线（results/taoge_chain/live-20260928/），掉了就回来改提取策略（按 "情境/反条件" 关键词优先捞）。
4. 【★ PC1】**eval 双轴**：①golden test=md 桃哥小节半自动提取→≤info_cutoff 回放对比；②决策质量= 历史回放（m5 次根开盘价口径）。依赖冒烟= 回 PC1 跑。
5. 【★ PC2✓】**双轨合并**：rules.md 唯一 canonical；rules_spec.md= 纯溯源；机器子集脚本生成禁手写。
6. 【★★ PC2✓】**小件**：state_digest.md / params.yaml / skills/taoge-skill/CHANGELOG.md。

## C. 持续线（日常 / 等发令）

1. 【PC1 用户】**backfill 下载层 45 待办**：等用户发令 "开始/继续"；PAUSE=`scripts/backfill_taoge/PAUSE`。
2. 【PC1】**夜跑 distill**：断点 2026-07-07（账本=`scripts/backfill_taoge/distill_state.json`，done=88 天）；恢复语义=skill/ 代码没变读账本续，变过= 归零器全量重跑；有 token 才跑；7/29 跳空待补（`--bvid BV1sv3C6tEpN`）。
3. 【★ PC2✓】**夜跑疑问**：回放帧 16 例（凡错位以最新 backfill 为准；taoge-sum 待加 "回放帧过滤+跨日同值检测" 规则）+ distill 产出人工审核。
4. 【★】**tzzb 线**：①五闸门 LLM 审议层首跑（漂移触发式，未触发）；②op 字段语义破译；③转债情绪数据（H5 欠定项）；④cb 分时竞价时段字段实盘验证（④需交易日=PC1/ 实盘）。
5. 【★ PC1】**cls wjzt 解析器**：23 天 PARSE_FAIL 遗留（误锚 "股票名称" 表头），Java 侧顺手修。
6. 【★★ PC2✓】**md/2026-09-24.md 涨停分析 PCB 表整表错误（10/3 腾讯 kline 铁证）**：表称大亚 5 板 / 中一 2 板 / 金安国纪等 7 只首板，实际 9/24=PCB 炸板分歧日（大亚炸板收+0.26%/ 中一-6.5%/ 金安-7.2%/ 生益-4.3%）；午评电报文本 "PCB 概念走弱" 才是真的。**这张错表毒化了 9/28 链 0915（PCB 方向）+用户 C 线方向**。查：9/24 涨停分析图是否挂错日期 /OCR 错位；评估要不要给涨停分析表加 "与电报文本矛盾检测"。
7. 【★★★ PC2✓】**paper 9/28 回放暴露三修复（10/3 用户令自动修，10/9 首跑前必做①）**：①facts 层加候选票前收 / 现价快照（04 后驱动器机械拉候选票快照写 run_dir），v06 加 "挂单价偏离 facts 前收>10%=回炉"（9/28 大亚锚 14.00 vs 实际 7.6= 编造单三道防线全穿）；②失效条件结构化落 plans 新列+matcher 执行（顶一字拒买 / 破低-3% 止损哨兵），现失效条件只是 note 文字无人执行；③盲审 prompt 加 "价格锚 vs facts 核对" 维度（盲审只看 01+06，01 无价格= 无从证伪）。
8. 【★ 等首跑】**PaperChainHandler exit 3 只 log.warn 不续全链=决策真空**（9/28 回放子链三连 ESCALATE 实证）；首跑看频率再定要不要 "escalate 自动续全链"。
9. 【★★★ PC2✓】**盲审回炉版契约校验败=死链无产出**（9/29 链实证：盲审驳回 06→回炉版 trigger_price 写公式价 `P0<=Z*0.97`→校验器只收数值→链中止未 emit，无 07 无 emit）。两修法择一或并行：①回炉版校验败再给一次回炉（现直接 abort）；②校验器支持公式价——前提是 C7①落地后 facts 有候选票前收 Z 可代入求值（与 C7①合流）。另：公式价其实是失效条件结构化的正确方向，别因噎废食禁掉。
10. 【★★★ PC2✓ 剩 matcher 层】**选股层缺"连续顶一字=当日移出候选池"过滤**（9/28-29 链实证：新华传媒四连一字天天霸六榜→天天进候选→天天挂-22% 废单）。✅ facts 层已落地（10/3）：facts.mjs 一字封死检测（开= 高= 低= 现价且达板限 10/20/30cm 分档），六榜行尾打 🔒·禁入候选+facts.md 头部硬过滤规则节；盘前= 昨日一字语义、盘中= 今日迄今一字（盘中开板分歧自动解禁）。**剩=matcher 层"顶一字拒买"（C7② 内）执行层双保险**。配套：B42 边界案例样本+1（9/29 衰竭型恐慌次日= 修复日，祖训空仓 vs 用户满仓赚，用户对）——攒样本到实跑再议 "衰竭型恐慌次日轻仓试错" 反条件。
11. 【★ 等首跑】**persona 反问 BUG**（9/29 实录）：✅ 方案 B 已落地（10/2）= 驱动器 prompt 头注元指令 "任务优先， 禁反问"（01 模板自带，各步 prompt 均在任务框架内）+ 哨兵文件末行校验兜底，SKILL.md 一字不动；待 10/9 首跑实证。
12. 【★】**fage 权重定级**：2-3 周核销 alpha 验证后定他在 taoge-skill chain 01 facts 的权重（此前只作参考；persona/rules.md v1 已沉淀：风险回避类零打脸权重最高，恐慌段左侧乐观降权）。
13. 【★ PC1 用户】**牧原做 T**：挂单参数= 每次现算近 30 日振幅分布（不建常备卡）；R-PNL-TRUE 口径= 账户级，已实现亏损不因股价回来自动恢复。

## D. 后排大活（回测期 / 阻塞中）【全部 ★】

1. **存储层 Phase 1**：Java 实体 cn.sichu.taoge×9 / market×1 / cb×1 + 验证测试 + `sql/taoge_rule_seed.sql`（R1-R14 带 learned_before）。DDL 见附录 A。
2. **TaogeAnalysisController + taogeVerdictBackfillHandler**：AI→DB 唯一事务入口；提及票补日线算 next_day_ret= 规则库计分牌（与 A1 的 IC/IR 合流）。
3. **账户感知**：成交 txt→入库格式（等语料攒几次再定，不提前建表）；live_account.md 变化时更新。
4. **高手语料第 5 梯队**：moni 模拟大赛首验 / 淘股吧实盘赛（需 cookie）；未实测：moni 是否需登录、tgb 未登录可见层级。
5. **结构件 P1**：live_state.json 单一账本 / 条件化参数引擎 / 评估管线 / 角色拆分。
6. **hermes 提醒链路**（阻塞在用户给入口）/ **全量验证回测** / **桃哥拟人化**（方向已定：人格画像+ 辩论流程+ 延迟结算闭环；先沉淀 2-3 周预案 vs 实际对照再谈人格 prompt）。
7. **遗留小件**：终裁→watchlist 自动桥 / 中国电影票房预测方法论（过渡期= 人工搜索+ 深度思考）。

---

## E. 模拟盘实验（paper）— 🔶 设计中；机械层已建（10/2），LLM 链未开工

> 目的：不动真钱证明 skill 可用可靠高收益；证明框架= 多账本归因（谁的决策赚谁的线）。
> 目录：`scripts/dfcf/paper/`（状态 gitignore、代码可追踪）。**已建**：matcher.mjs（--init/--import/--once[--dry]/--eod 全链冒烟通过：建 6 账本→plans 导入（CXL+ 坏行拒）→保守撮合→EOD nav+state_digest；腾讯快照 GBK 已修）、facts.mjs v2（六榜+ 关注票快照+digest+**新到电报=读当天 md 加红电报节按 slot 增量**（10/2 拍板：不碰 Java/DB/ 重复抓取，md 是唯一真源；09-30 回放增量窗口验证 ✅）+ **一字封死选股层过滤**（10/3 ✅，六榜行尾 🔒·禁入候选+ 头部硬规则节）→facts.md ~4-6k 字）、report.mjs 人读视图（10/3 ✅：净值曲线 SVG 百分比双标+hover 探针+ 全量成交明细）。规范=paper/README.md（plans 行格式 /hermes 落行要求 / 铁律 4 条）。**未建**：~~chain 驱动器~~✅、~~persona 反问修复~~✅、~~slot→steps 映射~~✅、~~token 台账~~✅、~~9/28 回放冒烟~~✅（10/2 真跑 exit 0：七步全一次过+ 盲审 FAIL→回炉 06×2→pass+plans 2 条件单落账本；全链 $5.69/46 万 token/37min；盲审真抓到回放 facts 的 10/2 六榜后见之明污染）、~~Quartz 接线~~✅（inv-stock/cn/sichu/paper/handler/ 3 handler+sql/paper_sys_job_seed.sql 待用户 insert，status=0）。剩=A-cb 二期、matcher 真 replay 撮合模式（读归档分时，现 --once 用活快照，回放成交数字不算数）。

**架构三层**：事实层共用（机械零 token）→ 决策层分账（稀疏 LLM）→ 执行层全自动（纯机械）。

**账本（各 10 万虚拟金互相独立，不与实盘共用）**：2 skill × 3 来源 = 6 账：A-taoge/A-cb（定时链）/B-taoge/B-cb（hermes 临场）/C-taoge/C-cb（人工裁决贴单）；D= 实盘（既有成交 txt）。plans 行带 `source`+`facts_version`，book.json 分账+ 哈希链。

**A 定时链时刻表**（10/2 用户修正版：盘前全链降级= 竞价预案，预期被开盘 30 分钟推翻；事件驱动=12:30 午间链一体，一天一次赶 13:00 前，不单设触发通道）：

| 时间                  | 层         | 内容                                                          |
| --------------------- | ---------- | ------------------------------------------------------------- |
| 09:15                 | LLM 全链   | 竞价预案+ 条件单（预期被推翻，不当全天计划）                   |
| 09:25-09:27           | LLM 纠偏   | 竞价数据落地后第一次纠偏（产物= 条件单，滑到 09:31 也不怕）    |
| 09:30-09:45           | 机械高频   | 开盘混沌期：条件单撮合+ 止损哨兵，LLM 不进场                   |
| 09:45 / 10:00 / 10:30 | LLM        | 早盘三个确认点                                                |
| 11:27-11:30           | LLM        | 上午收盘前定位                                                |
| 12:30                 | LLM 午间链 | 消化上午全部信息+ 午间新闻 / 突发 → 出下午计划（事件驱动并在这） |
| 13:00-13:03           | 机械       | 午间链计划已就位，午后开盘不调 LLM                            |
| 14:00 / 14:30         | LLM        | 下午两个确认点                                                |
| 14:55                 | LLM        | 尾盘竞价决策（隔夜仓 / 尾盘单，14:57 前落地）                   |

一期只开 A-taoge，**直接按全时刻表跑**（10/2 用户拍板：不搞删减版起步）；A-cb 二期接入时 **复用同一时刻表**（cb 链与 taoge 同构= 学人格 / 战术 / 选股，投资账本收盘后才更新、盘中无腿可跟——他的腿= 学习素材+ 次日同票成交价对照基准）。

**决策输出契约**（治 "skill 永远空仓"bug）：每次决策必须三选一落地——立即单 / **条件单**（主形态，观望= 挂单等）/ 空仓+ 进场触发条件；废单率= 决策质量度量。盘中改单= 版本链（v2 取代 v1 不覆盖）。

**facts 层四件套**（全量 md 永远不进 context）：

1. rules_index.md 生成器（扫 rules.md ### Bxx 头→索引；常驻= 元指令+ 索引，市况定后 grep 捞 2-3 条全文）= B3 落地
2. state_digest.md（EOD 顺手生成：昨日候选+ 持仓+ 遗留决策）= B6 小件
3. facts 构建器（slot 前 5min 拼装 scan 六榜+quotes 快照+ 新到电报+state_digest → facts/<date>/<HHMM>/facts.md 2-4k token）
4. facts_version 记账（A/B/C/D 同事实决策= 归因干净前提）

**前置 blocker（开工顺序）**：全清 ✅（C6→B1→9/28 冒烟→facts v2→Quartz 接线）。**10/9 首跑待办【★★★ PC1 用户】=用户 insert sql/paper_sys_job_seed.sql（status=0 即启用）+ hermes 贴 plans 行格式**。C 线= 用户对话裁决（10/3 立法：回放期 C 线由用户在本会话直接裁决，不走 hermes）；9/28-9/30 回放已记：C-taoge（金安低吸+ 补仓→竞价走→洗霸半仓持有过节，**106,712 +6.71%**）、C-cb（澳弘低吸+ 梯子清仓→翔丰全仓日内，**105,154 +5.15%**）、A-taoge（大亚止损，99,248 -0.75%）；原 57 笔照抄 snapshots 已作废（`_void_C-taoge_57fills_20261003.json`）。**B 线口径（10/3 用户立法）**：B=hermes 盘中临场落盘，A-C 中间点，只在实盘对话有意义，回放不模拟、回放期 B 两账保持空仓。A-cb= 二期未接入（一期只开 A-taoge），空账正确。

**hermes 对接**：plans 行格式规范=`scripts/dfcf/paper/README.md`（可 git 追踪），把「plans 行格式」一节贴给她即可：她自己挂的落 B-_，用户口令 "paper 买/卖xxx@数量" 落 C-_（note 带用户原话）。

**证明节奏**：第 1-2 周单笔记分卡（触发率 / 触及率 / 单笔胜率 / 盈亏比；触发率<30%= 决策层太保守回去调）→ 第 3-4 周净值过 4 周门槛（连续跑赢基准+ 回撤<10%）→ cb 线用土豆真腿做次日对照（账本收盘后才更新：同票同日他的真实成交价 vs 我们纸面成交价→执行差距+ 战术对照，非盘中滑点校准）。

**仓位参数**（params.yaml= 我们的策略参数非 persona；语料实证=regime 仓位制）：基准态（当前地量防守市）总仓≤3 成 / 单票≤1.5 成 / 留≥4 成现金；市况转强加仓，主跌强制极低仓（A1/A2 规则）。**转债线口径（10/3 用户立法）**：转债= 全仓单票进+ 日内止盈止损机械出（梯子+3% 目标 / 回落哨兵 / 尾盘必走），不做半仓；妖债秒单打法（严牌类）=A-cb 疆界，C-cb 不越界。

**未决问题（等用户拍板）**：①A-cb 二期接入时机（一期跑稳后；链与 taoge 同构= 学人格 / 战术 / 选股）②token 日预算上限（试运行观察百分比，别大手大脚）③facts 刷新频率（现=slot 前 5min）④模拟盘首跑 vs 假期 backfill 沉淀稳定的时序（rules 还在变= 测的是移动靶）。

**已知不自信点**：①cb 纸面收益= 上限（转债 T+0 秒级游戏，1 分钟撮合保真度最低；真腿次日对照只能校执行差距校不了盘中滑点）②B 线有选择偏差（只在拿不准时问）③C 线靠自觉贴单，前期不作判决依据 ④14:55 决策与 14:57 竞价间仅 2 分钟执行窗 ⑤盘前全链决策质量零实盘验证，第 1-2 周闸门只卡单笔不卡净值。

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
  `create_by` bigint DEFAULT NULL, `create_time` datetime(6) NULL,
  `update_by` bigint DEFAULT NULL, `update_time` datetime(6) NULL,
  `is_deleted` tinyint DEFAULT '0', `delete_by` bigint DEFAULT NULL,
  `delete_time` datetime(6) NULL, `remark` varchar(500) DEFAULT NULL,
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
4. `R-PNL-TRUE`：盈亏= 账户级（市值+ 现金 vs 初始投入）
5. `R-FACTOR`：因子加权一致性<0.6 禁给>50%
6. 审计红线：持仓变动必须有成交记录+ 哈希链
7. 目标校准：第一年= 月度胜率>60%+ 回撤<10%+ 跑赢大盘 20-40pt
8. 概率纪律：主剧本>50% 自信；小概率只留单一尾部

# 附录 E — 业界参考摘要（D6 用）

1. **TradingAgents**：多角色辩论→抄辩论制原型，角色砍 2 个
2. **AI Hedge Fund**：人格= 可执行规则集非风格 cosplay
3. **AlphaArena/nof1.ai**：盈亏差异在风控不在预测；简单 prompt+ 好工具>复杂 prompt+ 差工具；净值是唯一指标
4. **Qlib+RD-Agent**：假设→代码→回测→反馈闭环→穷人版= 案例卡→规则→回放→沉淀

#

场景 技术选型 优势
数据处理 Polars + Ray 比 Pandas 快 10x，内存效率高
实时计算 Flink(Java) 亚秒级延迟，精确一次语义
策略回测 Backtrader(Python) 支持多时间框架事件驱动
前端监控 Vue3 + WebGPU 硬件加速可视化
