# investment-tool 总 TODO（唯一工作清单）

> **本文档 = docs/ 唯一入口**。
> 目标函数 (用户定 2026-09-19)：**策略收益必须至少养活 Claude 订阅费**（10 万本金: Pro 档≈月 0.15%/年化 1.8%, Max$100 档≈月 0.73%/年化 9.1%, Max$200 档≈月 1.45%/年化 19%）。
> 在用路线 (2026-10-02 用户终裁)：**taoge-skill（学桃哥）+ cb-skill（转债高手不吃土豆0）** 两条线；scripts/ 按域分目录（见 `scripts/README.md`）。
> 现实参照：桃哥管线 2 周 +6.39%（样本小不可外推但方向已证）。

## 全景图

```
数据层    财联社API ─> cls_telegraph(已有)     B站 ─> 音频 ─> 转写 ─> 纠错(process_video.py)
          东财终端 ─> em.ps1 ─> PNG ─> OCR     同花顺投资账本(tzzb) + 大赛/交割单语料(第5梯队)
存储层      ▼   cls_telegraph/bilibili_video(已有) + taoge_* 回测8表(用时建) + market_quote_daily + tzzb_record
调度层      ▼   Quartz handlers(DB驱动, sys_job插行)
智能层      ▼   Claude/hermes: 信号蒸馏/解读提取/规则核销(AI活不进Java)
产出层      ▼   每日作战卡 / 周报复盘 / hermes提醒
```

---

## 当前优先级（覆盖旧梯队排序）

### Ⅰ. taoge-skill 工程化（顺序=用户指定）

1. **编排** ✅（10/1 实施完，待实盘首跑）：契约=`skills/taoge-skill/workflows/chain.md`（七步+盲审，每步=输入/输出/prompt 模板/哨兵/重跑粒度；盘中子链 02→04→06）。**驱动器 run_taoge_chain.py 已随 plan-a 删除，重建时按 chain.md 契约实现**（多步串行 claude -p/contract JSON 机械校验/失败单步回炉≤2 次/全链回溯重验/06 后独立盲审/--steps 子链/--review 跑 07）。
2. **事实包 `scan.mjs`** ✅（`scripts/scan.mjs`，全局六榜：涨跌幅/连板梯队/跌停/次新/板块）。数据源定论：东财 push2 clist(主)+新浪 getHQNodeData(备)；腾讯排行双源已证破产勿再试；push2 强制 IPv4；连发 ~25 次/5min 会触发 IP 级封禁，榜间抖动 0.8-2s。
3. **盘中重跑三定义**：状态传入=当日 decisions/；监听器=sentinel；矛盾避免=决策版本号+显式"维持/取代盘前 XX 决策"。盘中只跑 02→04→06 子链。
4. **上下文分级加载**：脚本从 rules.md 的 ### Bxx 头自动生成 rule_index.md；常驻=元指令+索引+profile 摘要；02 定市况后关键词 grep 捞相关规则全文。不上向量库。
5. **eval 双轴**：①golden test=md 桃哥小节半自动提取 eval/golden/YYYY-MM-DD.json，≤info_cutoff 回放，对比情绪判断/板块/概念/个股/大小票/操作方向；②决策质量=历史回放（m5 次根开盘价口径）。
6. **双轨合并**：rules.md 唯一 canonical；rules_spec.md=纯溯源档案；机器可执行子集脚本生成，禁手写第二轨。
7. 配套小件：state_digest.md（遗留票机械化=昨日候选+持仓+昨日 md 提及票）/params.yaml（止损/仓位上限/扫描频率抽离，止损是我们策略参数非 persona）/skills/taoge-skill/CHANGELOG.md（distill 顺手写）。

### Ⅱ. tzzb 转债高手线（三棒链已通，转入日常运转）

fetch(Java cron 小时级) ✅ → 900 逐笔腿+178 日汇总入库 ✅ → md 挂载两层制 ✅(gen_tzzb_md.mjs 硬数据 177 天 + tzzb-sum 推测层 144/144 天全齐) → tzzb-distill 机械层 ✅(profile/review/gen_cb_cases 零 token)。五闸门首跑已核销(rules.md R1-R7)。
**待办**：①五闸门 LLM 审议层首跑（漂移触发式，目前未触发）；②op 字段语义破译；③转债市场情绪数据(H5 欠定项)；④cb 分时行情竞价时段字段行为待实盘验证。

### Ⅲ. 持续线

- **backfill+distill 夜跑**：断点 2026-07-07，恢复语义与暂停状态见文末；有 token 才跑；问题记录进「夜跑疑问」人工审核。
- **backfill 下载层 45 待办**：等用户发令"开始/继续"（时间窗/GPU/PAUSE 守卫不动，PAUSE=`scripts/backfill_taoge/PAUSE`）。
- **TaogeAnalysisController / taogeVerdictBackfillHandler**（用户 10/1：可以考虑做）：AI→DB 唯一入口+规则库计分牌，依赖回测表，回测期做。
- **cls 图 wjzt 解析器**：23 天 PARSE_FAIL 遗留（误锚"股票名称"表头），Java 侧改解析器时顺手修。
- **BUG persona 反问不执行**（9/29 实录）：claude -p 加载 persona 后进入角色反问而非执行链路任务。修复待办：①persona 头部加元指令"任务优先于扮演，禁止反问/开场白"；②harness 任务指令压头+末尾强制哨兵；③修好后重跑 live 链路验证。

---

# 梯队档案（排序以「当前优先级」为准）

## 第 1 梯队 — Phase 1 存储层（一切地基）

- [x] **1.1 建表**：`sql/taoge.sql`（8 张回测表，用时拆）+ `market_quote_daily`（DDL 见附录 A）+ `sql/tzzb_record.sql`（已建）
- [ ] **1.2 Java 实体**：`cn.sichu.taoge`×9（回测期）/ `cn.sichu.market`×1 / `cn.sichu.cb`×1（四层×实体；字段要点见附录 A）
- [ ] **1.3 验证**：仿 `ClsTelegraphServiceImplTest`：插一条 taoge_rule + 一条 tzzb_record + 查回
- [ ] **1.4（Claude 交付）**：`sql/taoge_rule_seed.sql`（R1-R14 带 learned_before，给全 14 条）

## 第 2 梯队 — 桃哥管线产品化（目标：发视频→次日开盘前自动产作战卡）

- [x] 视频发现+转写管线（bilibiliVideoHandler 三段直链，状态机走 bilibili_video 表）
- [ ] **2.3 `TaogeAnalysisController`**：`POST /taoge/analysis/save` 主子表一个 @Transactional 写入——AI→DB 唯一入口，禁止手写裸 SQL（依赖 1.1 回测表）
- [ ] **2.4 `taogeVerdictBackfillHandler`**（cron `0 20 15 ? * MON-FRI`）：提及票补抓日线→算 next_day_ret→命中率统计=规则库计分牌（依赖 1.1）
- [x] 视觉管线（process_video.py 抽帧→RapidOCR→Qwen2.5-VL-7B；VLM 代码会错必须 OCR/多帧交叉校验；抽帧=片长自适应 `interval=clamp(dur/120,1s,3s)` 150 帧上限）
- [x] cls 图自动填 md（`scripts/cls/cls_image_ocr.py`，四小节归口=财联社图单一数据源，OCR 覆盖；PARSE_FAIL 不写只告警；分工=裸 OCR 自动填 + `/check-cls-md` 晚间看图复核）
- [x] download 物理删除定时任务（DownloadCleanupHandler：bilibili 原料 30 天/cls 图 90 天，派生路径+磁盘判真幂等，cron 每天 0 点）
- [x] downloads 目录约定：`downloads/bilibili/<mid>/<yyyy.MM.dd>/`=原料可删；`results/bilibili/<mid>/<yyyy.MM.dd>/`=产物永留；`downloads/tzzb/<ledger>/`；`downloads/cls/<yyyy.MM.dd>/`
- [x] 桃哥历史回填（`scripts/backfill_taoge/`，范围=2025-01-07 起；不写 DB 文件驱动；md 写回走 /taoge-sum）
- ProcessBuilder 要点见附录 B

## 第 3 梯队 — 账户感知（2026-10-02 重裁：自动化路线作废，手动贴文本流为正式口径）

em.ps1 已删（DirectUI 实测结论存 Claude 记忆 dfcf-em-ps1-findings，重建先读）。现状口径=用户做 T 后手动贴成交 txt 进 `scripts/dfcf/snapshots/`（9/28-30 牧原三天已在跑，保真度远高于 OCR）。

- [ ] **3.1 持仓快照入库**（轻量版）：用户贴的成交 txt → Claude 解析入表或进 md——等有几次做 T 语料后定格式，不提前建表
- [ ] **3.2 live_account.md 维护**：账户快照有变化时用户说一声，Claude 更新

## 第 4 梯队 — cb-skill 学"不吃土豆0"（已落地，见优先级Ⅱ）

端点字典=`skills/cb-skill/references/api.md`；凭证清单=`scripts/tzzb/tzzb_ledgers.json`。

## 第 5 梯队 — 高手语料采集线（补参考系）

- [ ] **5.1 首验源=同花顺 moni 模拟大赛**（moni.10jqka.com.cn）：比赛列表→每赛 top10→选手主页
- [ ] **5.2 首选语料=淘股吧实盘赛**（tgb.cn/spmatch，完整交割单+高手复盘帖）：需登录 cookie 手动导；用户贴链接+正文也是可行通道
- [ ] **5.3 微信公众号盘前语料**（10/2 用户提）：样例 https://mp.weixin.qq.com/s/rAFtvRXZGVd3A53dqIt0EQ ——盘前视角与桃哥盘后复盘互补；先探抓取通道，定了源后 stock-template 盘前段加锚点 + `migrate_md_template.mjs` 批量铺
- [ ] **5.4 入库约定**：多源 switch-case、抖动 ×0.75~1.25、增量账本、raw/解析分层；模拟盘数据标注来源权重
- ⚠️ 未实测：①moni 选手主页是否需登录 ②tgb.cn 未登录能看到第几层

## TODO 0.4: fage-skill（红旗大街发哥·盘前推演，第三导师）

- 学习对象：微信公众号「红旗大街发哥」每日盘前推演（情绪周期/能量强弱/冰点转暖），定位=盘前情绪周期事实层
- 单篇抓取已验证可行（mp.weixin.qq.com 直抓全文）
- 待解：新文章定时发现机制（搜狗微信/第三方 RSS/PC 微信监听）
- 产物：每日盘前 7:30-8:00 抓→AI 蒸馏→并入盘前事实包
- [ ] 未开始（等 taoge-skill/cb-skill 落地后）

## 第 7 梯队 — 结构件 P1（穿插做）

- [ ] **7.1 单一状态账本**：`live_state.json` 每轮快照，任何会话启动先读它——治"cron 唤起失忆"
- [ ] **7.2 条件化参数引擎代码化**：树形相似日过滤→条件分位数——治"现场拍脑袋参数"
- [ ] **7.3 评估管线**：案例卡+因子快照+分档误差周校准+月度账户归因
- [ ] **7.4 角色拆分**：采集=脚本✓/盯盘=哨兵✓/决策=会话/执行=条件单

## 第 8 梯队 — 后置大活

- [ ] **8.1 hermes 提醒链路**：阻塞在用户给 hermes 入口。三类产出：08:30 作战卡/盘中信号触发/持仓异动
- [ ] **8.2 全量验证**：转写全量 LLM 提取→批量入库→统一口径正式回测，回答"桃哥风格跨周期是否稳定正期望"
- [ ] **8.3 业界参考研究**（附录 E 有摘要）：TradingAgents/AI Hedge Fund/AlphaArena/Qlib+RD-Agent
- [ ] **8.5 桃哥拟人化**（用户定方向）：①人格画像持续更新（认知偏差/情绪周期/语言指纹/决策节奏/交易哲学，原料入口=/taoge-sum 每日合成）②组织流程=分析→辩论→交易→风控→终裁→复盘（计数器终止+recursion_limit+结构化输出）③事实走确定性代码，拟人只做判断评分 ④学习闭环=延迟结算+反思注入 ⑤全链路日志。纪律：风格 cosplay 零 alpha 不追；先沉淀 2-3 周"预案 vs 实际"对照日志再谈人格 prompt；拟人上限=桃哥本人，alpha 在提前量+行为真值校准

## TODO 0.5-C: 遗留小件

- [ ] 终裁→watchlist 触发器自动桥（不再人工转换）
- [ ] 中国电影票房预测方法论（历史国庆档+预售）+互联网语义情感多因子（微博/豆瓣/猫眼想看/短视频热度）；过渡期=人工搜索+深度思考，跑通后固化脚本
- [x] kimi 金融数据 MCP——决策已定：不接（轮询必须直连免费通道；低频深度数据层用户判定不需要）

---

# 附录 A — Phase 1 规格细节

**market_quote_daily DDL**（动机：某日某票收盘价原子数据；只存关注池）：

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

分钟线 (m5) 不入库；转债分时归档走 `downloads/cb_quotes/trends/`。

**taoge 9 实体字段要点**：json 列 `@TableField(typeHandler = JacksonTypeHandler.class)`；longtext→String；decimal→BigDecimal；Mention.stock_code 可空。
**唯一自定义 mapper**：`TaogeMentionMapper.selectPendingVerdict(@Param("beforeDate") LocalDate)`。

# 附录 B — ProcessBuilder 要点

1. 工作目录必须 `directory(new File(项目根))`，脚本用相对路径（scripts/ 下按域子目录，如 `bilibili/process_video.py`）
2. 读干 stdout/stderr 两流，否则缓冲区满死锁
3. 超时 `waitFor(30, TimeUnit.MINUTES)`——transcribe 单视频可能十几分钟
4. python 解析顺序：先 `scripts/venv/Scripts/python.exe`，不存在才退 PATH
5. misfire 口径：转写补跑=0 立即执行；行情任务=2 丢弃

# 附录 D — 纪律与红线（写代码时别丢）

1. **回测口径三件套永远不变**：learned_before / info_cutoff / 下一根 m5 bar 开盘价成交
2. **AI 活不进 Java**；AI 写库必须走 Controller 事务入口，不手写裸 SQL
3. **不提前建表**：先用文件/SQL 手工验证数据形态，稳定才固化
4. **模拟盘 4 周门槛**：未连续 4 周 paper 跑赢基准，不出实盘提醒
5. **所有调度留痕**：handler 返回可读摘要进 sys_job_log
6. `R-PNL-TRUE`：盈亏口径=账户级（市值+现金 vs 初始投入），已实现亏损不因股价回来自动恢复
7. `R-FACTOR`：因子加权可复算，一致性<0.6 禁给>50%
8. **审计红线**：持仓变动必须有成交记录+哈希链——状态变更必须伴随不可篡改日志
9. 目标校准：第一年=月度胜率>60%+回撤<10%+跑赢大盘 20-40pt；一年 10 倍不承诺
10. 概率纪律：主剧本须>50% 自信；小概率只保留单一尾部

# 附录 E — 业界参考摘要（8.3 用，按可借鉴度排序）

1. **TradingAgents**：多角色辩论。**抄**：辩论制输出原型；角色砍成 2，风控简化为一致性阈值
2. **AI Hedge Fund**：大师人格=可执行规则集非风格 cosplay。**抄**：人格矩阵原型
3. **AlphaArena/nof1.ai**：①盈亏差异在风控不在预测 ②爆仓死于过度交易+杠杆 ③简单 prompt+好工具>复杂 prompt+差工具 ④净值是唯一指标。**抄**："先活下来"；规则要精不要多
4. **Qlib+RD-Agent**：假设→代码→回测→反馈全自动闭环。**抄**：案例卡→规则→回放→沉淀=穷人版
5. 架构备忘：多人格矩阵+regime 仲裁器/案例相似度引擎/上下文三层（热<2k token/温/冷只检索）

---

## 夜跑疑问（人工审核队列）

1. **回放帧污染 16 例（系统性任务，用户 10/1 裁决：凡是错位的以最新 backfill 为准）**：教学/复盘类视频内回放的历史帧被采进当日画面列。已实锤三起回放帧（8/28 哈药 / 8/13 中证2000=7/31 帧 / 7/16 德明利=7/15 帧）+多起单条目错配（代码标注错配/字段互换/字段复用），识别法=跨日同值比对/数值关系矛盾/链式验算（ETF 帧链最可信；单条目错配不连坐）。**待办**：taoge-sum 画面节加"回放帧过滤+跨日同值检测"规则；16 例受影响日画面重跑/订正随 backfill 排期。各例详情已在对应日期 md 解读节标注。
2. **待补跑**：`scripts/backfill_taoge/backfill_taoge.py --bvid BV1sv3C6tEpN`（7/29 视频）→ /taoge-sum 合成 → distill。
3. **人工审核**：夜跑 distill 对 rules/cases/profile/language 的改动 + 进入 md 的合成内容。

## 夜跑暂停状态（2026-10-01 用户喊停；等重新发令）

- **账本**：`scripts/backfill_taoge/distill_state.json` done=88 天，断点=下一目标日 **2026-07-07**（7/7 的 md 已合成但 distill 未完成→恢复时 7/7 重做 distill，md 步可省）；7/29 跳空待补（见疑问 2）。
- **恢复语义（用户 10/1 定）**：sum/distill 的 skill 与代码没变→读账本从断点直接续；变过→9/28 铁律"凡新加 skill 内容全量重跑"归零重来（归零器=`scripts/backfill_taoge/reset_for_new_skill.py`）。跑前需用户重新发令；有 token 才跑。
- **md-sweep 批跑命令（备查）**：`scripts/venv/Scripts/python.exe scripts/backfill_taoge/backfill_taoge.py --md-sweep --md-force --md-months <yyyy-MM,...> --md-max-minutes 110 --ignore-pause`；语义=枚举 results 四件套齐备日期倒序，天然不重做视频→results；最新一期 md（格式样板）自动跳过；~2 小时停手等下次发令。
- **锁逻辑（10/1 已改）**：守护 wait_pause 待命期间释放实例锁（一次性 --bvid 可插跑），PAUSE 删除后重新抢锁。
- **pubdate 校验（10/1 已落地）**：process_one 下载后校验产物 json pubdate 与索引目标日期，不一致=FAIL 告警+产物自动隔离到真实日期目录（防 9/21 归档错位复发）。
