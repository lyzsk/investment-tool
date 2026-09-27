# investment-tool 总 TODO（唯一工作清单，2026-09-24 晚合并版）

> **本文档 = docs/ 唯一入口**。原 `总工程-plan.md`、`AI交易智能体-优化待办.md`、`桃哥管线Java化设计.md` 已合并/落地（9/27 起 docs/ 只留本文档，原文件 git 历史可查）。
> 目标函数(用户定 2026-09-19)：**策略收益必须至少养活 Claude 订阅费**（10万本金: Pro档≈月0.15%/年化1.8%, Max$100档≈月0.73%/年化9.1%, Max$200档≈月1.45%/年化19%）。
> 三计划(2026-09-24 用户定)：**plan-a = 学桃哥（收益率最高, scripts/plan-a/）｜ plan-b = 转债（日内最强, scripts/plan-b/ 骨架）｜ plan-c = AI 自学（最弱缺参考系, scripts/plan-c/）**。⚠️9/19 时 "plan-b" 曾短暂是 k3-inv 旧名，读旧记录别混淆。
> 现实参照： 桃哥管线 2 周 +6.39%(样本小不可外推但方向已证); k3 v0.1 -0.70% / v0.2 -0.50%(不达标, 修复中)。

## 全景图

```
数据层    财联社API ─> cls_telegraph(已有)     B站 ─> 音频 ─> 转写 ─> 纠错(plan-a脚本已有)
          东财终端 ─> em.ps1 ─> PNG ─> OCR(Tess4j已有)     大赛/交割单语料(第5梯队, 新)
存储层      ▼   taoge_* 9表 + k3inv_* 6表 + market_quote_daily 1表 = 16表
调度层      ▼   Quartz handlers(DB驱动, sys_job插行)
智能层      ▼   Claude/hermes: 信号蒸馏/解读提取/威科夫仲裁/回测裁决(AI活不进Java)
产出层      ▼   每日作战卡 / 模拟盘NAV / 周报复盘 / hermes提醒
```

---

# ⚠️ 9/27 夜间 Claude 自主代码 — TODO: 人工确认（用户睡觉任务，IDEA 逐项审查）

> 口径：9/27 晚用户睡觉前指令"直接写代码，我睡醒了来看"。以下代码均为本会话新写/改写，**未经编译验证**（本机 shell 无 JDK），IDEA 打开标红处优先看。

- [ ] **A1 `scripts/process_video.py`（新，四合一）**：transcribe.py+correct_names.py+vision_extract.py --dense+aggregate_pages.py 合并。CLI `--bvid --mp4 --m4a --out --stage asr,correct,vision,aggregate`。产物 `<bvid>.raw.txt/.tsv/.txt/.vision.json` 到 `results/bilibili/<作者mid>/<yyyy.MM.dd>/`（目录由 Java 显式传 --out，脚本本身不认约定）。已实测 50s 短片全链路 exit 0。原 4 个 py 已删。
- [ ] **A2 `scripts/fetch_bilibili_taoge.mjs`（新，二合一后挪根）**：fetch_taoge.mjs+fetch_video.mjs 合并，放 `scripts/` 根（不在 plan-a/）。`--list` 发现 / `--bvid` 下载 mp4+m4a+json 三件套（一次 playurl 取双轨），幂等 skip。已实测。fetch_video.mjs 已删。
- [ ] **A3 `BilibiliVideoServiceImpl.processPendingVideos` 能力降级**：detectCapability() 三档（0=无 venv 全跳过+提醒装环境不动 retry_count；1=venv 无 GPU/<15G 只跑 asr,correct 出 txt，step 停 DOWNLOADED；2=全配全链路）。MIN_VRAM_BYTES=15_000_000_000L。
- [ ] **A4 `processOne(v, fullVision)` 双路崩溃恢复**：产物齐（txt+vision.json 含 pages）→不起进程直推 VISION_DONE（孤儿 python 跑完场景）；spring 死在 py 中途→step 停 DOWNLOADED 下轮重捞，py 幂等跳过已完成阶段。
- [ ] **A5 `cleanupPhysicalFiles(retentionDays)`（impl+interface）**：SUMMARIZED+update_time 超期+source_files 非空 → 按数组逐个删（mp4+m4a+json 三件套），source_files 置空+remark 记删除日期，DB 行保留防重下。**9/27 字段变更（用户定）**：`file_path`(mp4 单路径+词干派生）→ `source_files` json 数组三件套（照 cls_telegraph.images 先例，JacksonTypeHandler+autoResultMap=true）；空表直接删了重建（`sql/bilibili_video.sql` 已是新结构）
- [ ] **A6 `ClsTelegraphServiceImpl.cleanupLocalImages(retentionDays)` + 接口方法**：按 `downloads/cls/<yyyy.MM.dd>/` 目录名日期解析，超期目录 Files.walk 倒序递归删。DB images=远程 URL 不动表。
- [ ] **A7 `DownloadCleanupHandler`（新，`cn.sichu.download.handler`，@Component("downloadCleanupHandler")）**：瘦 handler 调 cleanupPhysicalFiles(30)+cleanupLocalImages(90)。sys_job cron=`0 0 0 * * ?` 每天 0 点（9/27 用户定）。
- [ ] **A8 `BilibiliVideoHandler` 三段直链**：发现→downloadPendingVideos(3)→processPendingVideos(3) 同一 job 串行（15-40min 长任务靠 JobHandlerInvoker 已有 @DisallowConcurrentExecution 防重叠）。
- [ ] **A9 README/scripts README/skills taoge-paper 同步**：requirements-taoge.txt 安装指引、四 py 删除标注、batch_vision 两 sh 标 ⚠️历史归档勿重跑、skill 命令改指向 process_video.py。
- [ ] **A10 `BilibiliVideoController.markSummarized`（新，9/27 补）**：`POST /api/bilibili/video/markSummarized`(body=bvid 数组）→ service @Transactional 只推进 step=VISION_DONE 的行→SUMMARIZED（其他状态跳过计数）。**这是 SUMMARIZED 断点的收口**：此前没有代码推进 VISION_DONE→SUMMARIZED，物理删除永远不触发。/taoge-sum skill 合成完成后固化一句 curl 调此端点（AI 写库走 controller，不手写 SQL）。
- [ ] **A11 路径风格统一+目录 mid 化（9/27 用户定）**：bilibili 域全部改用 `projectConfig.getFile().getDownload().getRootDir()`（与 cls 同源），目录从 `bilibili/taoge/<日期>` 改为 **`bilibili/<作者mid>/<日期>`**（通用索引不限桃哥，路径由 DB 行 author_mid 驱动）；downloadOne/processOne 已改。新增 `GET /api/bilibili/video/pendingSummary`（/taoge-sum 发现入口）。
- [ ] **A12 `skills/taoge-sum/SKILL.md`（新，9/27）**：状态机最后一棒——pendingSummary 发现 → 三态判定（产物齐/仅 txt/缺产物不脑补）→ 合成写 `### 桃哥` 小节（小节只可能是 AI 产出，直接整小节覆盖幂等，无标记）→ curl markSummarized 推进。主副本 skills/，镜像 .claude/skills/（已同步）。
- [ ] **用户侧待做**：①空表删了重建（`sql/bilibili_video.sql` 已是 source_files 新结构）②postman 加 sys_job 两行（bilibiliVideoHandler `0 30 15-23 * * ?` + downloadCleanupHandler `0 0 0 * * ?`，附录 C 有现成 SQL，也可走 /api/quartz/add）→ runOnce 验证；首次跑前确认 `scripts/venv` 存在（附录 B 第 4 条）。
- [ ] **未实测不自信点**：①单 job 20-40min quartz 线程占用与应用重启中断行为 ②cls 图删后 /check-cls-md 复核老 md 无本地图（远程 URL 仍可访问）③表里无数据，首次 runOnce 表现未知 ④detectCapability 的 torch import ~10s/轮，未在 4090 实机验证探测输出格式

---

# 执行梯队（按顺序做）

## 第 0 梯队 — 开工前 10 分钟（确认类）

- [x] **0.1 对账**（用户 9/24 晚确认）：9/23 无成交（自报 2700 系误记），2400 → 今日净减 600 → **EOD 1800 股**。⚠️ 遗留：东财导出表持仓行自洽于 1500（疑陈旧未刷新）→ **9/25 早 em.ps1 快照复核定论**。成交明细已迁出 git → `scripts/dfcf/snapshots/live_account.md`
- [ ] **0.1b 隐私新规落地检查**：实盘成交/账户明细只进 dfcf/snapshots/（gitignored）+ Claude 记忆，git 文件（stocks md/push/handoff/决策）一律不写——以后每晚检查一遍
- [x] **0.2 告知 hermes 目录改名**（plan-c/handoff/20260924-claude-to-hermes.md 已留单，微信转一句即可）
- [x] 0.3 桃哥 9/24 视频：16:32《924两周年，低开低走4000多绿》已走管线注入 md ✓

## 第 1 梯队 — Phase 1 存储层（一切地基，~1 天，90% 模板复制）

- [ ] **1.1 建表**：`sql/k3inv.sql`(6 表已写好) + `sql/taoge.sql`(**9/27 注：video/transcript 职能已被 `bilibili_video` 表+results/ 文件取代，taoge.sql 只剩 8 张回测表，用时要按一表一文件拆**) + 新增 `market_quote_daily`（DDL 见附录 A）
- [ ] **1.2 Java 实体**：`cn.sichu.k3inv`×6 / `cn.sichu.taoge`×9 / `cn.sichu.market`×1（四层×实体，模板=`scripts/plan-c/docs/落地指南-java-quartz.md` §2.1；字段要点见附录 A）
- [ ] **1.3 验证**：仿 `ClsTelegraphServiceImplTest`：插一条 taoge_rule + 一条 k3inv_signal + 查回
- [ ] **1.4（Claude 交付）**：表建好后给 `sql/taoge_rule_seed.sql`（R1-R14 带 learned_before——总纲原文写 R1-R9，现规则库已 14 条要给全）

## 第 2 梯队 — Phase 2 plan-a 产品化（利润引擎，最高优先）

现状：管线脚本全就绪且批量验证过 234 天，但每日增量靠手动。目标：桃哥发视频 → 次日开盘前自动产出作战卡。

- [x] **2.1/2.2 视频发现+转写管线**（~~taogeFetchHandler/taogePipelineHandler~~）：**9/27 已被直链方案取代并落地**——`bilibiliVideoHandler` 单 job 三段（发现→下载→process_video.py)，状态机走 `bilibili_video` 表，见 A1-A12。此处保留占位说明设计演进：原"轻探测/重转写拆两个 handler"改为"直链+step 原地不动重试"，崩溃恢复靠 py 幂等+产物校验直推
- [ ] **2.3 `TaogeAnalysisController`**：`POST /taoge/analysis/save` 主子表（taoge_analysis+taoge_mention）一个 @Transactional 写入——AI→DB 唯一入口，禁止手写裸 SQL（依赖 1.1 回测表，回测期才做）
- [ ] **2.4 `taogeVerdictBackfillHandler`**（cron `0 20 15 ? * MON-FRI`）：①提及票补抓日线入 market_quote_daily ②selectPendingVerdict→算 next_day_ret→命中率统计。这是规则库"计分牌"（依赖 1.1）
- [x] **2.6 视觉管线挂接**：**9/27 已并入 `process_video.py`**（抽帧→RapidOCR→Qwen2.5-VL-7B→pages 聚合，直链进 bilibiliVideoHandler)。已证增量：①他没口头说的票②板块异动原文③精确价位④B/S 实际买卖点（行为真值，拟人化原料）。⚠️VLM 股票名稳但代码会错（金健米业→600193，真 600127），代码必须 OCR/多帧投票交叉校验——/taoge-sum 合成时执行此校验。**抽帧口径 9/27 改为片长自适应**（用户拍板放弃回测口径一致性追分辨率）：`interval=clamp(dur/120, 1s, 3s)` 网格∪场景切换，150 帧上限，短视频(1-4min)进 1~2s 区间；9/27 前已处理的 7 个视频保持旧 3s 口径不重跑。遗留：Q3 历史 58 天若要新结构（results/）产物，走 process_video.py 批量补，batch_vision*_q3.sh 已归档勿重跑——**已被回填方案取代：scripts/backfill_taoge.py 全量回填(2025-01-07 起, 229 已写md日期优先), 见 2.10**
- [ ] **2.7 cls 图自动填 md**（9/24 晚 python 侧已交付，`scripts/cls_image_ocr.py`，全本地 OCR 0 token；**9/25 用户开始写 Java**）：sys_job 定时扫 `downloads/cls/yyyy.MM.dd/` 当天 4 种图 → ProcessBuilder 调 `venv/Scripts/python.exe scripts/cls_image_ocr.py <图> --type wp|sp|wjzt|zt`（stdout=UTF-8 md 小节内容，不含 ## 标题）→ 替换 stocks md 对应小节（wp→`## 午评`，wjzt→`## 午间涨停分析`，sp→`## 收评`，zt→`## 涨停分析`）。**小节内容一律以 OCR 为准覆盖（9/25 用户定：四小节归口=财联社图单一数据源）**；脚本非0退出=PARSE_FAIL → 不写 md 只告警（旧内容保留）。python 侧已全量回填 Q3：zt/wjzt 56 天 + wp/sp 123 处已写入 md（9/25 晨）；**遗留：wjzt 23 天 PARSE_FAIL（误锚"股票名称"表头为主题，硬校验拒写）→ Java 侧顺手改解析器**（清单在 `scripts/plan-a/downloads/fill_wp_sp_rerun.log` 尾部；已实证 6/22 zt 两张同因失败=6-8 月旧版式不兼容）。**9/25 定复核分工：裸 OCR 自动填 + Claude 晚间 skill `/check-cls-md` 看图复核**（错字直改、数据以图为准、PARSE_FAIL/缺张列清单；wp/sp 快检、zt/wjzt 全检）。另注意已知漏洞：多图组缺张（zt 只下到 _1 没 _2）硬校验发现不了，Java 侧比对下载张数 vs glob 张数兜底
- [ ] **2.8 download 数据物理删除定时任务**（9/25 用户提，**9/27 夜已实现待人工确认 A5/A6/A7**）：downloads 各表预留了逻辑删除标记，需要 sys_job 定时把逻辑删除的记录物理删除（防 downloads 目录无限膨胀；cls 图/视频都是大文件）。已实现=`DownloadCleanupHandler`：bilibili 视频原料 30 天（DB 驱动，SUMMARIZED+source_files 数组逐个删）、cls 图 90 天（目录名日期驱动整删，DB images=远程 URL 不动）；cron=每天 0 点 `0 0 0 * * ?`（9/27 用户定）
- [ ] **2.9 downloads 目录约定**（9/25 用户定，9/27 扩展+mid 化）：`downloads/bilibili/<作者mid>/<yyyy.MM.dd>/`=每日视频原料 mp4+m4a+json（可物理删除；mid 作段=通用 B 站索引不限桃哥，9/27 用户定）；`results/bilibili/<作者mid>/<yyyy.MM.dd>/`=处理结果 txt+raw.txt+tsv+vision.json（永久保留，目录编码生命周期）；`downloads/tzzb/`=别人投资账本的操作数据（第 5 梯队语料）；`downloads/cls/<yyyy.MM.dd>/`=财联社图（已有）
- [ ] **2.10 桃哥历史回填**（9/27 用户定）：`scripts/backfill_taoge.py`+`backfill_taoge_index.mjs`（分支 agent 编写中）。范围=2025-01-07 起全部桃哥视频（md 统一格式起始日；桃哥共 1507 视频，旧 index.json 639 不全需重爬）；**229 个已写 md 日期优先**（results 原料全缺、语料价值最高）；时间窗=工作日 00:30-18:00/周末节假日 02:00-10:00 + GPU 守卫（>6G 占用让给 cron）；**不写 DB**（文件驱动，results 产物=状态）；md 写回不走脚本=后续 Claude 批量会话；抽帧按 2.6 新口径；老 plan-a/downloads 残留 m4a 复用
- ProcessBuilder 要点（抄 MarkdownFormatServiceImpl 时注意）见附录 B

## 第 3 梯队 — Phase 4 账户感知（提到 Phase 3 前：plan-b/plan-c 都依赖它）

- [ ] **3.1 `dfcfSnapshotHandler`**（cron `0 5 11,15 ? * MON-FRI`，sys_job 默认 status=1 暂停）：em.ps1 read→PNG→Tess4j OCR→正则解析→taoge_position_snapshot(source='em_ocr')。铁律：用户在场禁跑=开关就是 sys_job.status；账号掉线存 remark='logged_out' 不算失败；前两周 PNG 路径进 remark 人工抽查 OCR 准确率，不达标降级为"只存 PNG，Claude 读图 POST 入库"
- [ ] **3.2 持仓 diff 操作检测**：相邻 snapshot positions diff 推断买卖（价格用 market_quote_daily 近似）→ 先写 remark 验证准确率，**不提前建 dfcf_operation 表**。价值：用户实盘 vs plan-a 信号 vs plan-c 信号三方对照
- [ ] **3.3 当日成交页（-Page 当日成交 -RealClick）**：用户重新登录后先手动复验翻页坐标，没复验前 handler 只用默认页
- [ ] **3.4 附带收益**：用户手工贴成交文本退休；plan-b 交割单原料也从这里来

## 第 4 梯队 — plan-b 转债线（数据先行，不写策略代码）

- [ ] **4.1 用户导出转债历史交割单**（东财→历史成交，5 分钟）→ `scripts/dfcf/snapshots/`（交割单=成交明细，按 9/24 隐私立法不进 git）
- [ ] **4.2 交割单解析脚本** → 逐笔 csv：选债/买卖/价差/持有分钟
- [ ] **4.3 规则蒸馏（AI 活）**：反推选债标准与买卖点 → plan-b/rules_seed（先文件不立表）
- [ ] **4.4 行情源验证**：集思录（溢价率/条款）+ 强赎/下修公告日历（事件层，plan-c §8.1 共用）。多源 switch-case+抖动铁律
- ⚠️ 不要做：转债回测引擎（无规则前无意义）、转债模拟盘（等 4.3）
- 待回答（有交割单前不下结论）：①赚的到底是什么钱（正股联动/条款博弈/溢价率摆动/T+0 流动性）②选债标准 ③是否=桃哥情绪周期在 T+0 上的放大器

## 第 5 梯队 — 高手语料采集线（给 plan-c 补参考系，plan-a/b 也能用）

调研结论(9-24)：同花顺"投资账单"无公开页此路不通；可抓=大赛排行榜+选手主页。**用户补充：可手动复制链接给我访问（免登录页我能直接 WebFetch 读内容）**。

- [ ] **5.1 首验源=同花顺 moni 模拟大赛**（moni.10jqka.com.cn，老站 HTML 反爬弱）：比赛列表→每赛 top10（用户原话"热门比赛10个×每赛10人"）→选手主页（持仓/建仓时间/盈亏/交易记录）
- [ ] **5.2 首选语料=淘股吧实盘赛**（tgb.cn/spmatch，完整交割单+高手复盘帖，赵老哥/炒股养家出处）：需登录 cookie 手动导一次；用户贴链接+正文也是可行通道
- [ ] **5.3 补充**：东财杯战报帖（字段少）；雪球组合不建议（风控强）
- [ ] **5.4 入库约定**：沿用 B站管线范式——多源 switch-case、抖动 ×0.75~1.25、增量账本、raw/解析分层；模拟盘选手数据标注来源权重（与实盘有偏差）
- ⚠️ 未实测不确定：①moni 选手主页当前是否需登录/接口是否已改 JSON（写码前先 curl 一页）②tgb.cn 未登录能看到第几层 ③雪球接口变动频繁

## 第 6 梯队 — Phase 3 plan-c 收益修复（v0.2 已定，剩代码化）

- [ ] **6.1 k3inv_strategy 插 v0.2 版本行**（依赖 1.1；v0.2 回测 -0.50% 超额+1.21pct）
- [ ] **6.2 `k3invSignalCandidateHandler`**（cron `0 0/15 9-15 ? * MON-FRI`）：扫 cls_telegraph 新进 level=B 电报，关键词/模式预筛→候选插 k3inv_signal(strength=NULL 待 AI 评分)。AI 每天读 738 条不现实，机械预筛砍 90% 噪音
- [ ] **6.3 `K3invSignalController`**：`POST /k3inv/signal/score` + `GET /k3inv/signal/pending`
- [ ] **6.4 paper 日常化**：每周一 run，连续 4 周跑赢指数才谈实盘提醒（防自嗨门槛）
- [ ] **6.5 v0.3 方向**（留痕不代码化）：事件日历层(9/21 A50 剔除教训)、板块联动维度(9/22 用户批评)、"强势日次日=兑现压力日"剧本

## 第 7 梯队 — 结构件 P1（穿插在 2/3/4 间隙做）

- [ ] **7.1 单一状态账本**：`live_state.json` 每轮快照（paper_state 模式推广到实盘），任何会话启动先读它——治"cron 唤起失忆"（9/23 任务带过期持仓铁证）
- [ ] **7.2 条件化参数引擎代码化**：树形相似日过滤→条件分位数（R-SPEC 雏形已有）——治"现场拍脑袋参数"（42.27 卖区事件）
- [ ] **7.3 评估管线**：案例卡+因子快照+分档误差周校准+月度账户归因（9/22 才建第一张案例卡）
- [ ] **7.4 角色拆分**（P0 但不单独立项）：采集=脚本✓/盯盘=哨兵✓/决策=会话/执行=条件单——后两个随第 2/3 梯队自然成形

## 第 8 梯队 — 后置大活（依赖前面全部）

- [ ] **8.1 Phase 5 hermes 提醒链路**：阻塞在用户给 hermes 入口。三类产出：08:30 作战卡/盘中信号触发/持仓异动
- [ ] **8.2 Phase 6 全量验证**：235 天转写全量 LLM 提取→批量入库→统一口径正式回测，回答"桃哥风格跨周期是否稳定正期望"（决定实盘仓位分配）
- [ ] **8.3 业界参考研究**（用户拍板，附录 E 有摘要）：TradingAgents/AI Hedge Fund/AlphaArena/Qlib+RD-Agent/FinRobot
- [ ] **8.4 quant.md 技术选型**（Polars+Ray/Flink/Backtrader/Vue3，在 stocks/todo/）：远期重构参考，**本期不用**——与 Java+Node 栈冲突，引入=增实体违反奥卡姆
- [ ] **8.5 桃哥拟人化**（9/27 用户定方向，plan-a 精进主线）：①**人格画像**（prompt 层面持续更新）：认知偏差/情绪周期/语言指纹/决策节奏/经验记忆/交易哲学/行为特征/决策规则——从长期沉淀的 stocks md + results/ 提取 ②**组织流程**：分析→辩论→交易→风控→终裁→复盘（TradingAgents 骨架，单人格化）③**可控性**：计数器终止辩论+recursion_limit 硬保险+结构化输出 ④**边界**：股价/指标/财报等事实走确定性代码，拟人只做判断评分 ⑤**学习闭环**：延迟结算+反思注入+向量索引指向历史决策 ⑥**可解释性**：数据采集→分析辩论→最终决策全链路日志。原料入口=/taoge-sum 每日合成；纪律：风格 cosplay 零 alpha 不追（AI Hedge Fund 教训：人格=可执行规则集），先沉淀 2-3 周"预案 vs 实际"对照日志再谈人格 prompt；拟人上限=桃哥本人，alpha 在提前量+行为真值校准（沉默持仓）

---

# 附录 A — Phase 1 规格细节

**market_quote_daily DDL**（动机：mention.next_day_ret 回填/k3 复盘/NAV 都需要"某日某票收盘价"原子数据，现抓腾讯又慢又限流；只存关注池，几千行/年）：

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

分钟线(m5)**不入库**——体积大时效短，继续存 `plan-a/downloads/kline/*.json`。

**taoge 9 实体字段要点**（其余照模板）：json 列全部 `@TableField(typeHandler = JacksonTypeHandler.class)`；longtext 列(raw_text/fixed_text/report)→普通 String；decimal 列→BigDecimal；Mention.stock_code 可空（ASR 没对上代码）。
**唯一自定义 mapper**：`TaogeMentionMapper.selectPendingVerdict(@Param("beforeDate") LocalDate)`（查某日前 verdict='待定' 且 code 非空的提及）；MarketQuoteDaily 用 LambdaQueryWrapper 够。
**工作量**：~70 文件 90% 机械复制，节奏="1 个完整→验证→批量复制"。

# 附录 B — ProcessBuilder 要点（从 MarkdownFormatServiceImpl 抄时）

1. 工作目录必须 `directory(new File(项目根))`，脚本用相对路径
2. 读干 stdout/stderr 两流（各起线程或 redirectErrorStream），否则缓冲区满死锁
3. 超时 `waitFor(30, TimeUnit.MINUTES)`——transcribe medium 单视频可能十几分钟
4. python 解析顺序(9/27 定)：先 `scripts/venv/Scripts/python.exe`（桃哥管线 ASR+7B 环境，requirements-taoge.txt 钉版），不存在才退 PATH 的 python；plan-a/venv 是旧转写环境（pip.exe 坏了，装包需重建 venv）
5. misfire 口径：转写补跑有意义=0 立即执行；行情任务=2 丢弃

# 附录 C — sys_job 插行汇总（按梯队顺序执行）

```sql
-- 第 2 梯队(9/27 桃哥管线 Java 化, 待人工确认 A1-A12)
INSERT INTO sys_job (job_name, job_group, job_handler_name, cron_expression, misfire_policy, status, remark)
VALUES ('桃哥视频发现下载处理', 'bilibili', 'bilibiliVideoHandler', '0 30 15-23 * * ?', 2, 0, '发现→下载mp4/m4a/json→直链process_video.py(ASR+纠错+视觉+聚合), 单job15-40min靠@DisallowConcurrentExecution防重叠');
INSERT INTO sys_job (job_name, job_group, job_handler_name, cron_expression, misfire_policy, status, remark)
VALUES ('downloads物理删除', 'download', 'downloadCleanupHandler', '0 0 0 * * ?', 2, 0, 'bilibili原料30天+cls图90天物理删除, DB行保留');
-- 第 2 梯队(回测期, 依赖 1.1 建表)
INSERT INTO sys_job (job_name, job_group, job_handler_name, cron_expression, misfire_policy, status, remark)
VALUES ('桃哥提及回填', 'taoge', 'taogeVerdictBackfillHandler', '0 20 15 ? * MON-FRI', 2, 0, '收盘后抓日线+回填next_day_ret/verdict');
-- 第 6 梯队
INSERT INTO sys_job (job_name, job_group, job_handler_name, cron_expression, misfire_policy, status, remark)
VALUES ('k3信号预筛', 'k3inv', 'k3invSignalCandidateHandler', '0 0/15 9-15 ? * MON-FRI', 2, 0, '盘中扫电报生成候选信号strength=NULL');
INSERT INTO sys_job (job_name, job_group, job_handler_name, cron_expression, misfire_policy, status, remark)
VALUES ('k3信号日报', 'k3inv', 'k3invDailyReportHandler', '0 30 15 ? * MON-FRI', 2, 0, '收盘汇总当日信号与观察名单');
-- 第 3 梯队(默认暂停 status=1, 用户在场规则确认后改0)
INSERT INTO sys_job (job_name, job_group, job_handler_name, cron_expression, misfire_policy, status, remark)
VALUES ('东财账户快照', 'dfcf', 'dfcfSnapshotHandler', '0 5 11,15 ? * MON-FRI', 2, 1, 'em.ps1截图+OCR落taoge_position_snapshot; 用户在场时保持暂停');
```

# 附录 D — 纪律与红线（写代码时别丢）

1. **回测口径三件套永远不变**：learned_before / info_cutoff / 下一根 m5 bar 开盘价成交——任何新策略继承同一诚实标准
2. **AI 活不进 Java**；AI 写库必须走 Controller 事务入口，不手写裸 SQL（主子表一致性）
3. **不提前建表**：先用文件/SQL 手工验证数据形态，稳定才固化（dfcf_operation 为例）
4. **模拟盘 4 周门槛**：任何策略未连续 4 周 paper 跑赢基准，不出实盘提醒
5. **所有调度留痕**：handler 返回可读摘要进 sys_job_log——唯一执行回执
6. `R-PNL-TRUE`：解套/盈亏口径=账户级（市值+现金 vs 初始投入），禁止只看每股成本——已实现亏损不因股价回来自动恢复
7. `R-FACTOR`：因子加权可复算（权重表在 STRATEGY.md §9），一致性<0.6 禁给>50%
8. **审计红线**：paper_state 持仓变动必须有成交记录+哈希链（9/23 "成交0笔但持仓变化"断链事故）——状态变更必须伴随不可篡改日志，做成硬约束
9. 目标校准：第一年=月度胜率>60%+回撤<10%+跑赢大盘 20-40pt；一年 10 倍不承诺（杠杆+幸存者偏差领域）
10. 概率纪律：主剧本须>50% 自信；小概率只保留单一尾部（除非被对话中突发信息推翻）

# 附录 E — 业界参考摘要（8.3 用，按可借鉴度排序）

1. **TradingAgents**（开源多角色辩论）：4 分析师→多空辩论→交易员→3 风控辩论。**抄**：辩论制输出原型；角色砍成 2（技术面脚本算+新闻面 LLM 判），风控简化为一致性阈值(R-FACTOR)
2. **AI Hedge Fund**（virattt）：大师人格=**可执行规则集**非风格 cosplay；人格冲突由组合经理按规则分配权重。**抄**：桃哥/plan-c/豆神人格矩阵原型；我们 R 系列规则就是对的做法
3. **AlphaArena/nof1.ai**（实盘 AI 竞赛 $10k×各模型）：①盈亏差异在风控不在预测 ②爆仓都死于过度交易+杠杆 ③简单 prompt+好工具>复杂 prompt+差工具 ④净值是唯一说话的指标。**抄**："先活下来"（回撤<10% 目标出处）；规则要精不要多
4. **Qlib+RD-Agent**（微软）：假设→代码→回测→反馈全自动闭环。**抄**：案例卡→规则→回放→沉淀=穷人版；7.2 参数引擎本质=RD-Agent 循环搬到做T参数
5. 附：FinRobot / QuantConnect Lean（成熟量化框架，可嵌 LLM 插件）
架构方向备忘：多人格矩阵+regime 仲裁器(盘前按情绪周期分配权重)/案例相似度引擎(top3 检索+定期消融)/上下文三层(热<2k token/温/冷只检索)/研究维度扩展(H股回购、基金季末行为、北向)。
**暂不决定（等用户研究）**：各人格 prompt 与角色边界；相似度用 LLM 语义还是 embedding；表结构（等 plan-c 工程期）。

*细节模板：`scripts/plan-c/docs/落地指南-java-quartz.md` ｜ 策略规格 `scripts/plan-c/STRATEGY.md` ｜ 回测报告 `scripts/plan-a/backtest/runs/pilot-2week/report.md`、`scripts/plan-c/backtest/runs/k3-v0.2-20260901_0918/report.md`*
