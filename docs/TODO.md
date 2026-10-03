# investment-tool 总 TODO（唯一工作清单）

> 目标函数（2026-09-19 用户定）：策略收益至少养活 Claude 订阅费（10 万本金：Pro≈年化 1.8% / Max$100≈9.1% / Max$200≈19%）。
> 在用路线（2026-10-02 终裁）：**taoge-skill + cb-skill** 两条线 + fage-skill（盘前推演第三导师，已建线）；scripts/ 按域分目录见 `scripts/README.md`。
> 核销口径：fage 58 天纯命中 0.553/ 含半 0.702（`skills/fage-skill/persona/score.json`，`node scripts/md/gen_scorecard.mjs` 重算）。

---

## 优先级图例（2026-10-03 立法）

- **★★★** = 10/8 paper 首跑前必须落地；**★★** = 窗口期该做；**★** = 等触发/后排
- **【PC2✓】** = 笔记本可干（仅需 git 内容+公网）；**【PC1】** = 绑本机数据/application；**【用户】** = 只能用户动手
- **10/4 9:00→10/7 12:00 PC2 窗口执行序**：①C7 三件套 ②C9 死链 ③C10 matcher 拒买 ④A1 IC/IR ⑤C6 错表 ⑥B6 小件 ⑦A3/B5/C3 捡漏 ⑧§F 会战残留+§G 扩容（有空才动）
- 10/7 回 PC1：`git pull` → 首跑前检查；**10/8 首跑**（§E 待办；10/4 用户更正：节后首个交易日=10/8）

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

1. 【★★★ PC1 巡航中】**backfill 10/4-10/7 巡航模式（10/3 用户发令，10/4 修订）**：每 5h 一轮（00:30 起，cron 5cb42ec7=10/4-6 全天+f53fb63c=10/7 上午），每轮 `backfill_taoge.py --max 15 --ignore-window`（10/4 用户令：单轮 20→15，全程上限 ~150 天）；优先复用素材做 md+沉淀（复用自动硬链优先）再倒序新下；PAUSE 每轮开始删/结束重建；自修失败，连续两轮全败才 hermes 报 BLOCKED；10/7 12:30 截止+TODO 写总账。**API 口径（10/4 用户）**：换回 5h window 套餐后，遇 429/window 限=等 5h 再续不跳过（巡航 5h 节拍天然对齐）。日志=`scripts/backfill_taoge/backfill.log`。
2. 【PC1】**夜跑 distill**：断点 2026-07-07（账本=`scripts/backfill_taoge/distill_state.json`，done=88 天）；恢复语义=skill/ 代码没变读账本续，变过= 归零器全量重跑；有 token 才跑；7/29 跳空待补（`--bvid BV1sv3C6tEpN`）。
3. 【★ PC2✓】**夜跑疑问**：回放帧 16 例（凡错位以最新 backfill 为准；taoge-sum 待加 "回放帧过滤+跨日同值检测" 规则）+ distill 产出人工审核。
4. 【★】**tzzb 线**：①五闸门 LLM 审议层首跑（漂移触发式，未触发）；②op 字段语义破译；③转债情绪数据（H5 欠定项）；④cb 分时竞价时段字段实盘验证（④需交易日=PC1/ 实盘）；⑤**+6 选手扩容=§G（观察池方案，players.json+fetch 参数化）**。
5. 【★ PC1】**cls wjzt 解析器**：23 天 PARSE_FAIL 遗留（误锚 "股票名称" 表头），Java 侧顺手修。
6. 【★★ PC2✓】**md/2026-09-24.md 涨停分析 PCB 表整表错误（10/3 腾讯 kline 铁证）**：表称大亚 5 板 / 中一 2 板 / 金安国纪等 7 只首板，实际 9/24=PCB 炸板分歧日（大亚炸板收+0.26%/ 中一-6.5%/ 金安-7.2%/ 生益-4.3%）；午评电报文本 "PCB 概念走弱" 才是真的。**这张错表毒化了 9/28 链 0915（PCB 方向）+用户 C 线方向**。查：9/24 涨停分析图是否挂错日期 /OCR 错位；评估要不要给涨停分析表加 "与电报文本矛盾检测"。
7. 【★★★ PC2✓】**paper 9/28 回放暴露三修复（10/3 用户令自动修，10/8 首跑前必做①）**：①facts 层加候选票前收 / 现价快照（04 后驱动器机械拉候选票快照写 run_dir），v06 加 "挂单价偏离 facts 前收>10%=回炉"（9/28 大亚锚 14.00 vs 实际 7.6= 编造单三道防线全穿）；②失效条件结构化落 plans 新列+matcher 执行（顶一字拒买 / 破低-3% 止损哨兵），现失效条件只是 note 文字无人执行；③盲审 prompt 加 "价格锚 vs facts 核对" 维度（盲审只看 01+06，01 无价格= 无从证伪）。
8. 【★ 等首跑】**PaperChainHandler exit 3 只 log.warn 不续全链=决策真空**（9/28 回放子链三连 ESCALATE 实证）；首跑看频率再定要不要 "escalate 自动续全链"。
9. 【★★★ PC2✓】**盲审回炉版契约校验败=死链无产出**（两实例：9/29 链=回炉版 trigger_price 写公式价 `P0<=Z*0.97` 校验器只收数值；9/30 链×2=回炉版 supersedes 缺"首裁"——根因=回炉 prompt 不回喂校验错误，LLM 改内容时顺手改坏契约字段）。两修法择一或并行：①回炉版校验败再给一次回炉（现直接 abort）；②校验器支持公式价——前提是 C7①落地后 facts 有候选票前收 Z 可代入求值（与 C7①合流）。另：公式价其实是失效条件结构化的正确方向，别因噎废食禁掉。
10. 【★★★ PC2✓ 剩 matcher 层】**选股层缺"连续顶一字=当日移出候选池"过滤**（9/28-29 链实证：新华传媒四连一字天天霸六榜→天天进候选→天天挂-22% 废单）。✅ facts 层已落地（10/3）：facts.mjs 一字封死检测（开= 高= 低= 现价且达板限 10/20/30cm 分档），六榜行尾打 🔒·禁入候选+facts.md 头部硬过滤规则节；盘前= 昨日一字语义、盘中= 今日迄今一字（盘中开板分歧自动解禁）。**剩=matcher 层"顶一字拒买"（C7② 内）执行层双保险**。配套：B42 边界案例样本+1（9/29 衰竭型恐慌次日= 修复日，祖训空仓 vs 用户满仓赚，用户对）——攒样本到实跑再议 "衰竭型恐慌次日轻仓试错" 反条件。
11. 【★ 等首跑】**persona 反问 BUG**（9/29 实录）：✅ 方案 B 已落地（10/2）= 驱动器 prompt 头注元指令 "任务优先， 禁反问"（01 模板自带，各步 prompt 均在任务框架内）+ 哨兵文件末行校验兜底，SKILL.md 一字不动；待 10/8 首跑实证。
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
> 目录：`scripts/dfcf/paper/`（状态 gitignore、代码可追踪）。**已建**：matcher.mjs（--init/--import/--once[--dry]/--eod 全链冒烟通过：建 6 账本→plans 导入（CXL+ 坏行拒）→保守撮合→EOD nav+state_digest；腾讯快照 GBK 已修）、facts.mjs v3（六榜+ 关注票快照+digest+新到电报+一字封死过滤+**池子覆盖率 WARN**（涨停池 vs pools.json<70% 强制扩池）+**竞价异动临时池**（slot≥0925 接力池取数口）+**轮动位置节**（rotation.mjs digest），10/4 ✅）、report.mjs 人读视图（10/3 ✅）、**scorecard.mjs**（10/4 ✅：nav csv×6 账本归因+token_log 成本+废单率→scorecard.md/json 机械零 token）、matcher 三闸（锚偏离闸+撮合窗闸 10/3 ✅+**拒落账闸**板限自适应 10/4 ✅）、**pools.json 池子登记簿**（10/4 ✅ 盲区修复⑤：池子从 persona 叙事升格机器真源）、**rotation.mjs 轮动图谱**（10/4 ✅：ZT 池 14 日回填+日间转移矩阵+seed.json 先验（用户口述传导链）+digest 位置判定+--belong F10 归属；已知=东财 ZT 池历史深度仅~3 周+9/25 单日数据洞，本地逐日累积）。规范=paper/README.md（plans 行格式 v2 / 铁律 7 条）。**cb 决策引擎**（10/4 ✅ 盲区修复⑦：skills/cb-skill/workflows/chain.md cb 版 01-06（v1 无 03 拆环）+run_taoge_chain.py --skill cb 参数化（转债 code 闸/R 规则 id/3 成上限）+selftest 含 cb 全绿+cb 链 --dry 冒烟过；**真跑未验**）。剩=matcher 真 replay 撮合模式（读归档分时，现 --once 用活快照，回放成交数字不算数）。

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

**前置 blocker（开工顺序）**：全清 ✅（C6→B1→9/28 冒烟→facts v2→Quartz 接线）。**10/8 首跑待办【★★★ PC1 用户】=用户 insert sql/paper_sys_job_seed.sql（status=0 即启用）+ hermes 贴 plans 行格式**。C 线= 用户对话裁决（10/3 立法：回放期 C 线由用户在本会话直接裁决，不走 hermes）；9/28-9/30 回放已记：C-taoge（金安低吸+ 补仓→竞价走→洗霸半仓持有过节，**106,712 +6.71%**）、C-cb（澳弘低吸+ 梯子清仓→翔丰全仓日内，**105,154 +5.15%**）、A-taoge（大亚止损，99,248 -0.75%）；原 57 笔照抄 snapshots 已作废（`_void_C-taoge_57fills_20261003.json`）。**B 线口径（10/3 用户立法）**：B=hermes 盘中临场落盘，A-C 中间点，只在实盘对话有意义，回放不模拟、回放期 B 两账保持空仓。A-cb= 二期未接入（一期只开 A-taoge），空账正确。

**hermes 对接**：plans 行格式规范=`scripts/dfcf/paper/README.md`（可 git 追踪），把「plans 行格式」一节贴给她即可：她自己挂的落 B-_，用户口令 "paper 买/卖xxx@数量" 落 C-_（note 带用户原话）。

**证明节奏**：第 1-2 周单笔记分卡（触发率 / 触及率 / 单笔胜率 / 盈亏比；触发率<30%= 决策层太保守回去调）→ 第 3-4 周净值过 4 周门槛（连续跑赢基准+ 回撤<10%）→ cb 线用土豆真腿做次日对照（账本收盘后才更新：同票同日他的真实成交价 vs 我们纸面成交价→执行差距+ 战术对照，非盘中滑点校准）。

**仓位参数**（params.yaml= 我们的策略参数非 persona；语料实证=regime 仓位制）：基准态（当前地量防守市）总仓≤3 成 / 单票≤1.5 成 / 留≥4 成现金；市况转强加仓，主跌强制极低仓（A1/A2 规则）。**转债线口径（10/3 用户立法）**：转债= 全仓单票进+ 日内止盈止损机械出（梯子+3% 目标 / 回落哨兵 / 尾盘必走），不做半仓；妖债秒单打法（严牌类）=A-cb 疆界，C-cb 不越界。

**未决问题（10/4 用户逐条拍板，已清）**：①A-cb 接入 ✅ 已落（cb:HHMM 前缀进 PaperChainHandler+seed.sql 加 4 job: 0915/0927/0935/1000）②token 日预算=试运行观察，不设死上限（用户 10/4）③facts 刷新=维持 slot 前 5min（实测构建 ~90s 足够；价格漂移已有 matcher 锚偏离闸+拒落账闸双兜底，浮动值二次校验暂不做）④首跑 vs 沉淀时序=非问题（驱动器每轮现读 chain.md+重建 rules_index，rules 变更即生效，无缓存）⑤cb 仓位口径 ✅（10/4 用户立法：T+0 转债不做仓位管理——有把握全仓进/没把握半仓+半仓+止损/获利了结/平出，上限=全仓，v06 cap=1.0 已落；**用户股票风格备忘**：1+1+2=1 持仓+1 动态新增+2 补仓做T；追短线=1+1 半仓+半仓——供 taoge 链 06 仓位建议参考）⑥扩池提案=**自动落** ✅（pool_merge.mjs 零 token：v04 校验后驱动器机械 merge，票名→代码走 smartbox，失败记 unresolved）⑦cb 03 拆环=暂不拆（见 §F.7 解释）。

**已知不自信点（10/4 用户逐条过）**：①cb 纸面收益=上限——**价格笼子已查证**（[深交所细则 2025 修订](https://docs.static.szse.cn/www/lawrules/rule/bond/bonds/trade/W020250327576698646997.pdf)/[上交所细则](https://www.sse.com.cn/lawandrules/sselawsrules2025/bond/trading/currency/c/c_20250606_10781040.shtml)：转债非首日连续竞价有效申报=最新成交价±10%，超笼=废单）→ 实盘 cb 激进买单必能成交（笼内滑点），纸面保守撮合（触及≠成交）低估的是**成交率**不是方向；真腿次日对照校执行差距的口径不变 ②B 线存废=**保留但零投入**（Claude 裁，见 §F.8）③C 线靠自觉贴单，前期不作判决依据 ④~~14:55/14:57 执行窗~~=非问题（尾盘竞价窗口=14:57-15:00，收盘前响应即可；matcher 撮合窗含 15:00 整点档按收盘价判，已覆盖）⑤盘前全链质量验证=方法已建（§E 证明节奏：第 1-2 周单笔记分卡→第 3-4 周净值门槛+scorecard.mjs 账本归因；skill 收益率/成功率=纸面先证，实盘再上）⑥**数据源稳定性=用户 10/4 点名问题**（经常这个不行换下个，没有稳定源）→ 现状+统一客户端方案见 §F.9。

---

## F. 盲区修复会战（2026-10-04 夜间，用户粘贴七块反向审查后执行）

**已完成**（全带机械验证）：①matcher 拒落账闸（板限自适应 11/21/31/32%，挂单价 vs 前收超限直接 exit 1，7 案例测试过）②规则沉淀 A23（高位=情绪周期浮动阈值）/B82（批量一字竞价强确认打先手）/B83（反核晋级=强度确认）③规则引用情境校验（v06+chain.md，引用必答情境、高位类必带周期档位，selftest 9 反例）④03 拆环真对抗（03b 多方/03s 空方独立会话+03j 裁判，编锚方直接判负）⑤盲区修复（pools.json 登记簿+facts 池子覆盖率 WARN+竞价异动临时池+02/04 prompt 立法"方向归市场，手艺归人格"+双池制取数+扩池提案 contract）⑥轮动图谱（rotation.mjs：backfill/matrix/digest/belong 四命令，seed.json 先验，facts 轮动节，02 prompt 轮动位置判定义务）⑦cb 决策引擎（见 §E）⑧scorecard.mjs ⑨本 TODO 收尾。

**会战残留（★★ PC2✓ 可干）**：
1. **跷跷板相关性矩阵**（轮动⑥的中难度件）：板块指数日收益相关矩阵，定期重算；数据源=东财板块 K 线（push2his kline，BK 码）；落点=rotation.mjs --corr + matrix.json 同目录。
2. **seed.json 校对**：board_alias 关键词是拍的（东财 hybk 是行业板块且 4 字截断，如"汽车零部件→汽车零部"），用户按实盘经验改；传导链 edges 待 matrix 窗口攒大后实证校验。
3. **转债域 facts**：转债涨幅榜/溢价率榜未建（cb 链 01 只能显式标注缺口）；东财转债 clist fs 待探（PC2 写码+PC1 验证）。
4. **异构对抗进阶**：kimi 当空方/风控 vs claude 当桃哥（03 拆环已备好接口，换模型=driver CLAUDE 命令参数化）。
5. **facts 覆盖率 2% 实证**（10/4 冒烟）：涨停池 51 只在池仅 1 只（上海洗霸）——池子偏见告警当场触发，10/8 首跑看 04 扩池提案质量。
6. **matcher 竞价时段人工核销流程**：--import-fills 的锚检查 WARN 已有，hermes/用户的核销操作卡没写（首跑前补进 README 或 hermes 指令）。
7. **什么是"拆环"（用户 10/4 问，解释档）**：03 多空辩论原来是**同一次 claude 调用里自问自答**——模型既当多方又当空方，没有对抗压力，容易和稀泥收场。**拆环**=把 03 拆成三个独立会话：03b 多方辩手（看不到空方说什么）→ 03s 空方辩手（看不到多方）→ 03j 裁判（读双方陈词裁决，逐条核证据锚，编锚方直接判负）——TradingAgents 式真对抗。taoge 链 10/4 已拆（0915 全链多跑 2 次独立会话）；**cb v1 根本没有 03 辩论步**（01→02→04→05→06 直落）。Claude 建议 cb 暂不拆：转债日内链路短、R1-R7 硬纪律已覆盖主要风险、拆环成本=每 slot 多 2 次调用；cb 真跑 2 周后若亏损归因显示"该看到的风险没看到"再补。
8. **B 线存废（用户 10/4 质疑"为什么要有 B 线"→Claude 裁决：保留，零投入）**：B=hermes 盘中临场的唯一记分牌，删了就永远没有"她的临场单质量"对照组；"涉及人工反问"不是缺陷是她的工作方式——B 只记录她**最终敢落的单**（反问过程不进账本）。账本成本=两个空 json，零维护零 token；不设目标不考核，纯观测。若 10/8 首跑一个月后 B 账仍全空，再删不迟。
9. **数据源稳定性统一治理（用户 10/4 点名：经常这个不行换下个，一直没有稳定数据源）**：现状=各脚本自带多源 switch-case+抖动+闭环（scan.mjs 涨跌榜=东财主/新浪备，但连板/跌停/次新/板块=东财单源；快照=腾讯单源；轮动=东财 ZT 池单源），已踩坑清单=①push2 系 IPv6 死路由须 family:4 ②emweb F10 强制 gzip ③东财 ZT 池节假日回声（qdate 闸）④9/25 单日数据洞 ⑤东财 clist 偶发 socket hang up ⑥smartbox 名字段 \u 转义。**方案【★★ PC2✓】**：建 scripts/quotes/client.mjs 统一客户端——每端点声明主备源链+自动降级+sources_health.json 健康台账（每源成功率/最近失败原因），健康度差的源自动降权；scan/facts/rotation/matcher 逐步改调客户端（故障逻辑集中一处修，不再各脚本散装）；**Java 侧原则=永不直连数据 API，一律 ProcessBuilder 调 scripts**（附录 B 已立此规，数据可靠性只在客户端一层维护）。

## G. PC2 窗口新增任务（2026-10-04 用户睡前令）+ Claude 的解答

**任务（用户原话）**：PC2 有空就做——①bilibili 趋势天哥复盘（qstg-skill?）②tzzb 投资账本增加 6 个选手 ③bilibili 卢本圆复盘（lby-skill）也放 TODO。10/7 回 PC1 用户自己改 md 模板。

**Q&A（Claude 答，用户醒后裁决）**：

- **Q: bilibili 视频都要 xxx-sum + xxx-distill 吗？** A: **是**。现范式=下载/ASR/守护（scripts/bilibili/ 域）→ md 小节 → sum skill（转写→摘要进 md）→ distill skill（摘要→蒸馏进 persona/rules）。桃哥线=taoge-sum+taoge-distill 现成模板。qstg/lby 各复制一对：新建 skills/qstg-sum+qstg-distill（SKILL.md 改对象名/目录/md 小节名，机械活）；人格沉淀目标文件各建各的（qstg-skill/lby-skill persona/）。
- **Q: tzzb 加 6 选手 skill 要不要动？** A: **观察池阶段不动 skill**。tzzb 域是 API 拉数非视频：①scripts/tzzb/ 根=通用（fetch/画像/API client 全部 --player 参数化），新建 players.json 登记簿（7 选手 key/user_key/别名/状态）——**不要按选手复制脚本**（7 份维护地狱违背高内聚）；②6 个新选手先只拉数+机械画像（profile 脚本复用 profile_bchitudou0.py 参数化），攒 2-3 周数据再裁决谁值得建人格 skill 蒸馏；③cb-skill 保持=不吃土豆0 专属（已接决策链），不动。
- **Q: 目录怎么分？** A: scripts/tzzb/ 根放通用脚本+players.json；scripts/tzzb/data/<player>/ 放数据（gitignore）。scripts/bilibili/ 根放通用下载/ASR/守护模板；backfill_taoge/ 是桃哥专用守护的历史遗留名，新 UP 主不再建 per-UP 文件夹，用 --mid 参数化（顺手时把 backfill_taoge 改名 bilibili/ 根通用守护，非必须）。
- **执行序建议**：①players.json+fetch 参数化（最小，先跑通 6 选手拉数）②qstg 管线（sum/distill 复制+守护参数化）③lby 同理 ④md 模板=用户 10/7 自己改，各 sum skill 的小节名先按 `### 趋势天哥`/`### 卢本圆` 占位。

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
