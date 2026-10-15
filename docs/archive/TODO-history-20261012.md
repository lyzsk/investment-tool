# investment-tool TODO（v4, 2026-10-09 22:3x 用户令: 删没意义的 / 写未来）

> 目标函数: **paper=导师筛选器**(看出 A-xxx 谁收益率高) → 策略收益养活订阅费; 终极= 对齐 TradingAgents 级多 agent 金融决策平台
> 消费约定: 人读=§1-§2, AI 读=§0 起; ✅ 项不存 git; 【PC1】本机 /【PC2✓】笔记本 /【用户】人动手

---

# §0 行为立法（AI 每轮开工先读；无模型绑定, k3/Claude 继任者同守）

补丁①-⑪(10/8-10/9 立法): ①改名必跑 grep_verify.sh ②改 skills/ 必跑 sync_skills.mjs ③先落盘验证再汇报 ④覆盖前必查已有 ⑤新消息追加不清空队列 ⑥活动队列落盘 §0.5 ⑦做了必报(尾三行) ⑧收尾①②二连不等催 ⑨用户忘了→原样重贴不造文件 ⑩开工三问(沉淀在哪/前置数据看了吗/契约对过吗) ⑪DB/不可逆操作需无歧义动词授权。另: ⑫不动 ~/.claude/settings(用户亲管); ⑬实盘隐私=成交/账户只进 snapshots/(gitignore)。

# §0.5 活动队列（⑥载体: 开工先读/收工更新）

- [📝10/12 凌晨 改动清单(用户 00:3x 睡前令: 按优先级做 行情库 → §5.4 对账 → §5.3 结构化输出 → §5.5 链路入库; DB/代码/脚本随便动, 新表留 sql; 用户 08:00 重启)]
  - **⚠ 重启时机**: 07:30 起 15 条 0915 全链在跑(约 2h); IntelliJ 停止应用大概率连子进程树一起杀(未实测) → 8:00 重启可能打断当天盘前链。新代码今天不重启也不缺什么(15:35 收盘任务旧代码照常; 竞价我 09:15 手动跑脚本验证)。建议: 晚上下班后重启; 若 8:00 一定要重启, 先看 0915 链都结束了没
  - **新表(已建, DDL 在 sql/investment_tool/)**: reconcile_result(对账结果, 行情库/B 站共用) / chain_run / chain_step / chain_decision / chain_decision_rule(§5.5); **改表**: bilibili_video 加 `origin varchar(10) DEFAULT 'DAILY'`(DAILY/BACKFILL) + step 注释加 DISTILLED(已执行 ALTER, bilibili_video.sql 已同步)
  - **新 sys_job(已插库, 重启后自动加载)**: 136 行情库-对账补采 16:40 / 137 行情库-开盘竞价 09:14(OPEN) / 138 行情库-收盘竞价 14:56(CLOSE) / 139 B站-UP视频对账 23:50 / 140 B站-补跑(**暂停**, 待用户定 cron 和参数) / 141 行情库-外围收盘 08:30 / 142 链路入库-补导(手动)
  - **行情库第 2 段换源**(用户 00:2x 令弃 baostock): backfill_history.py 默认腾讯日线(翻页全历史)+新浪 hfq 因子, 验证数据见下条旧清单; **00:39 腾讯 ifzq 被我跑封(~1.6 次/秒 6 分钟后整 IP 返 501, qt.gtimg 实时不受影响)** → 已停, 改默认 0.4 次/秒 + 第一轮每只只拉 1 页(最近 2000 根≈8 年, 截断的记 truncated.txt 以后补全); 守候 scripts/temp/history_tx_resume.sh 每 15 分钟探活, 解封自动续跑到 06:30。已完成 492 只并已入库(131 万行)。东财+腾讯同时封时 kline.mjs 只剩新浪不复权(归档会拒混) → 今早 07:30 链读的是已含 10/09 的旧归档, 不受影响; 若腾讯长期不解封需给 kline.mjs 加"新浪不复权×新浪因子=前复权"源(未做, 待议)
  - **第 2b 段 除权检测**: 新 scripts/market/refresh_factors.py(当日快照昨收≠上一日收盘 → 拉新浪因子 → 校验因子比≈收盘/昨收 <0.2% 才落, 不过=factor_pending.json 每日重试 5 天, ETF 只留痕); 4 只真实除权日回放与回补因子逐行一致; Java importDaily 有 DONE_factor 时按标的替换因子
  - **第 5 段 竞价**: 新 scripts/market/collect_auction.py(新浪批量报文, 关注集 ~300 只+3 指数, OPEN 每 15s/CLOSE 每 10s, 原始报文全留档 call_auction_<phase>_raw.jsonl); **竞价字段口径(买一=匹配价/量, 买二卖二量=未匹配)未实测, 10/12 09:15 首测核对**; Java: MarketAuctionHandler + importAuction + CallAuctionMapper(XML 新)
  - **第 6 段 补采/对账**: Java IMarketPipelineService(把"采集→除权→入库→分时"整条流水线从 Handler 抽出, 收盘任务/对账/启动补采共用一把锁) + MarketReconcileHandler + MarketStartupRunner(启动 3 分钟后后台对账一次, 补停机/断电错过的收盘采集); 往日日线快照过期 → backfill_history.py --day 腾讯逐只补采; 结果写 reconcile_result, 有缺口经 hermes 推微信(新 INotifyService/HermesNotifyServiceImpl, 同 daily_digest.mjs 调法)
  - **历史入库归属**: importHistory 只导 reconcile-start-date(2026-10-09)之前的日线, 之后归每日快照(带成交额), 实测 10/09 的 8123 行新浪行未被腾讯行覆盖
  - **§5.4 B 站对账+补跑并入状态机**: BilibiliReconcileService(逐 UP 逐视频: results 齐 → md 有 bvid=已 sum → md 日在 distill 账本=已蒸馏; DB 缺行补登记 origin=BACKFILL、step 落后就推进, 不回退) + BilibiliReconcileHandler(23:50) + BilibiliBackfillHandler(--up X [--enqueue N --from --to] [--process N], 补跑行单独限量处理, 不进每日队列); 每日队列/待 sum 清单只取 DAILY; 30 天原料清理覆盖 DISTILLED。**首跑结果**: 天哥 30/30、卢本圆 22/22 全对齐; 桃哥缺 sum 6 条(9/30、10/06~10/08 周末假期稿)、缺蒸馏 56 条(C2 重做进行中)、孤儿 distill 1 天(2024-07-15); 卢本圆 BV1csbW6LEyj 重试 3 次停住; DB 补登记 150 条、推进 25 条
  - **§5.5 链路入库**: ChainIngestService 解析运行目录(步骤文件 mtime/sha/哨兵/contract, 02 市况/03 胜方/盲审/06 终裁单+规则引用, run_meta.jsonl) → chain_*; PaperChainHandler/PaperReviewHandler 进程结束即入库(失败只记日志不影响任务); ChainIngestHandler 手动补导(空参=全部历史 slot=FINAL)。**已补导 95 个目录: 813 步骤 / 777 终裁单 / 990 规则引用**; token_log.csv 无 skill 列, 成本暂不入库(要改 driver 日志格式, 待议)
  - **第 4 段 外围**: 新 scripts/market/collect_global.py(新浪批量 16 品种: 纳指100/纳综/标普/道指/金龙指数/KWEB/恒指/恒生科技/日经/富时100/A50 期货/标普·纳指期货/黄金/原油/离岸人民币, 按当地交易日; 24h 品种=北京时间减 6h 的日期) + MarketGlobalHandler + importGlobal; sys_job 141 每天 08:30; 10/09 实测 16/16 入库(symbol 口径 us.NDX/hk.HSI/gl.A50)。**链路暂未消费**(要进 01 事实包需改 facts.mjs, 待议)
  - **§5.3 结构化输出公共模块**: 新 scripts/lib/claude_call.py(stdin 按字节传 UTF-8 / --output-format json 信封判 is_error+subtype / 跳网关通知行 / 限流词只在错误文本里匹配+rotation 切 key+有上限的 45min 顺延 / 哨兵整行匹配 / 末个 ```json 块+迷你 JSON Schema 校验 / expect_files mtime 核验 / 成本账本 scripts/lib/claude_cost.csv 含缓存 token, 已 gitignore); 迁移 5 处: backfill_bilibili(md/distill/llm-batch, 前两处原为 cmd /c 传 argv=换行截断 bug) / tzzb/distill_daily.py / backfill_inference.py。离线桩自测全过(含 5 万字多行 prompt); **真机联调待 C2 结束(串行纪律)**。未迁: run_taoge_chain(样板, 自带并发闸+contract 校验, 实盘在用不动) / hermes ask_claude(要 --resume+工具白名单, 低延迟) / tzzb distill_history / gen_taoge_ic.mjs(node)
  - **kline.mjs 加 sina-qfq 兜底源**(东财→腾讯→**新浪不复权×新浪因子**→新浪不复权): 东财+腾讯同封时仍能给前复权档增量; 等比口径(东财/腾讯是等差减分红), 24 只近 250 根实测: 最近一次除权之后逐根一致, 更早老段差 ≤1%; 指数/个股末根与真归档逐字段一致(量统一为手); ETF/转债抛错回落新浪不复权(原行为); 因子按天落盘缓存 downloads/quotes/factors/ 防 15 条链齐打新浪。另: 腾讯 01:1x 已解封
  - **03:51 桃哥 35 天重做 ALL_DONE**(md→distill→rules_index+sync); distill 会话有 15 天**做完了却没记账**: 根因=`claude -p` 只返回最后一条回复, 会话中途逐天打印的 DISTILL_OK 全丢(每会话只剩复述进总结的那 1 天)。证据核实(15 天在 persona 文件都有 10/12 修订行+会话总结写明全部完成)后已补记账本 82→97(备份 distill_state.json.bak-20261012-pre-sentinel-fix); 根治: backfill_bilibili 批量 prompt + tzzb/distill_daily prompt 加'最终回复开头逐行复述全部哨兵'。**新发现待用户定**: 桃哥 4 个旧 BV(BV1UZ4y1N7Bw/BV1XZ4y1G77K/BV12D8q6ZEwF/BV11a411A7Rn, 2020 年编号)在 results 下各有两份内容完全相同的日期目录(9/27~9/29 一份 + 10/06~10/08 一份, 后者 10/07-08 生成, 疑似 10/7 Java 任务误捞历史稿事故的残留), 且 md/2026S4/2026-10-08.md 引用了其中两条——按'bug 残次品整夹删'立法应删 10/06~10/08 那份并清 10-08 md 错挂块, 不可逆, 未动
  - **03:53 claude_call 真机联调通过**(1 次极小调用: json 信封 success/schema 校验/哨兵/成本账本 $0.20 均正确)
  - **06:5x 收尾**: 历史日线全量入库(7992 只/1221 万行, 10/09 新浪行未被覆盖, 因子 5421 只; 8 只转债腾讯无数据, 4019 只截在近 8 年待深翻) / B站 2020 旧稿误捞副本按用户令删(9/08·9/27·9/30·10/06~10/08 共 6 个旧 BV, bilibili_video 逻辑删+去重含已删行防重入队; BV12D8q6ZEwF 真实 08-21 稿挪回 results/2026.08.21, 08-21 新增 1 天蒸馏欠账留今晚) / 周末节假日稿顺延下一交易日(backfill_bilibili md_path_for+只合并不覆盖+顺延块单独蒸馏账本 rolled_pending; Java 对账同步) / **06:58 用户重启应用**, 136~142 全部注册, 启动对账 OK
  - **07:0x 0915 链加速**(用户令): 并发闸 CLAUDE_MAX_CONCURRENCY 默认 6→15(每链一条串行车道, 15 链同时跑; 原 6 时 9 链排队=2h 的主因, 10/09 0915 共 158 次调用/10h claude 时间) / 驱动器加回炉原因落盘 run_dir/retry_log.jsonl + scripts/dfcf/paper/retry_log.jsonl(02/06 约半数回炉, 原因此前不记) / **0915 提前到 07:00 暂缓**(用户 07:0x: 开盘前 md 还在补信息, 提前会降低 01 事实包质量; 先看今天并发 15 跑多久再定) / 并发上限改为读 scripts/claude_profile/max_concurrency.txt(本机配置已 gitignore, 缺省 15; **切回订阅制改成 4~6**, 下次链运行生效不用重启)
  - **07:34 0915 开跑核查**: 15 条链全部起跑(run_taoge_chain 15 对进程, 15 个 live-20261012 目录), 并发槽 14 个在用(新上限 15 生效, 不再排队); 07:36 已有 7 条出 01_facts(~6min); 无回炉记录、无失败日志、无额度窗口顺延; cron 未动(仍 07:30)
  - **08:47 0915 耗时报告**: 完成 2/15(buchitudou0 08:41 用时 71min / control 08:47 用时 77min), 其余 13 条 10 条已到 05、3 条(taoge/qushitiange/gaogailvfuli)到 04, 全部走 gravitex 正常推进, 预计 09:00~09:10 完成; 扣掉 07:41~08:24 的 43min 额度顺延, 单链净耗时≈35min(10/09 并发 6: 桃哥 197min)→ **并发 15 不排队时 0915 全链约 35~45min**。今日至此 107 次调用/6.5h/$98(01 步单次 $1.3~1.9, 输出最高 3.8 万 token=最贵一步)。回炉 5 次(10/09 同期 32 次): 02×4=全是枚举写法(`有主线(注释)`×2/`板块层先行`/`无主线`), 前 3 次 07:52 已修(以枚举开头即归一), 第 4 次 `无主线` 是枚举名本身不唯一(三态叫'无主线退潮', 模型简写)→建议: 归一再加'输入是某枚举值的唯一前缀也认'或把三态改名为互不前缀的短词; 06×1=control 中文在线挂 24.95 超涨停上沿 24.51=校验正确拦截(模型价错, 非 bug)。**根因判断**: 02 回炉=校验器对写法过严(已修大半); 06 今天只 1 次且是真错——10/09 的 06 高回炉更可能来自数字约束矛盾+并发 6 下长等待后的上下文, 待今晚注入算好的约束后再看 **09:10 补: 15/15 全部完成, 无失败**——最早 buchitudou0 08:41(71min) / 最晚 gaogailvfuli 09:08(98min) / 桃哥 09:05(96min) / 平均约 86min; 扣除 07:41~08:24 额度顺延 43min 后净耗时 28~55min(平均约 43min), 15 条全部在 9:15 前完成; 对比 10/09(并发 6): 桃哥 197min → 今天净 53min
  - **15:52 收盘核查: 15:35 收盘任务失败且失败日志丢失, 已修已补**——①collect_daily.mjs 崩在写 manifest.stages(同目录 manifest 先被我昨夜新写的 collect_global/collect_auction 建, 无 stages 键; 我的 bug), 已加 `mf.stages ||= {}` ②**JobHandlerInvoker 老 bug**: 失败时 job_message='执行失败:'+异常消息(带 4000 字脚本输出), 超 varchar(500) → 整条 sys_job_log 插入失败, 失败记录静默丢失(只在 IDEA 控制台); 已改为截断到 500(**需重启应用生效**, 完整内容仍在 exception_message) ③15:57 经应用 runOnce 133 重跑: kline_day 8125 / **除权刷新 16 只全部校验通过**(2b 首日生效) / 分时只成 6/396 → 根因=collect_minute 连到的第一台通达信(上证云成都电信一)收盘后无当日逐笔, 已改为连接时探测该日有逐笔才用; 重采 394/396(2 只北交所)、94948 根, 已入库。16:40 对账本来也会兜底补采
  - **竞价字段口径实测核对(牧原)**: 买一价=卖一价=虚拟匹配价(09:24:57 41.10=当日开盘) ✓ / 买一量=虚拟匹配量 ✓ / 买二·卖二价为 0 时其量=未匹配量, 正=买方剩余 负=卖方剩余 ✓(09:24:57 卖方剩余 71674 股→开盘略低于昨收)。**修 bug**: 撮合后那一行(09:25:00/15:00:00)原先误取连续竞价盘口(41.09×900), 改为取现价+成交量(OPEN=当日累计量 224400=09:30 首根分钟量 ✓; CLOSE=累计量-收盘竞价前累计量 189387 vs 15:00 分钟线 186500, 差 1.5% 来自 14:57 前几笔连续成交), 加 --rebuild 从原始报文重算, 今日两段已重算重导
  - **盘中盯盘 live_watch.mjs**(用户 10/12 午间令: 一分钟内出挂单+复用项目行情层): 个股走 snapshot.mjs 共享缓存(新增 vol/amt/qtTime 字段), 大盘/方向读 paper 最新时段 facts 的 scan 段(零额外请求), 指数暂每分钟 1 次腾讯 qt; 13:00~15:01 实跑无失败。待修: 均价穿越信号贴线反复刷屏(需 0.1% 带宽+持续 2 分钟去抖)
  - **验证方式**: 不碰运行中的应用——javac 用运行中进程的依赖 classpath 把 4 模块整体编到 scripts/temp/javac_out; 临时启动器 scripts/temp/selftest/(调度器不自启/无 Web/不推微信)按 bean 名直跑 handler: marketReconcile/bilibiliReconcile/chainIngest/marketDaily(2026-10-09)/marketHistory 全部 rc=0
- [📝10/11 夜 改动清单(用户睡前授权"代码 DB 都可以改, 做完留可看的改了什么"), 用户 10/12 醒后看]
  - **01:47 巡检**: ①桃哥 35 天重跑 C2 进行中, md-batch 已成 26 天(5 天/会话 ~17min, 当前 2025-08-15..09-12), 最新会话 5/5 无 MD_FAIL; 未成 4 天=2026-09-27/09-30/10-06/10-07(周末/假期, 当日 md 不存在, 与 B站对账 sum 缺口同一批, 非 bug, 待用户定这类稿挂哪天); vision 线 23:32 已 ALL_DONE ②baostock 守候已于 00:2x 按用户令停用(改腾讯源), 腾讯回补 01:15 解封续跑: 1200/8139, 新失败 0, ~24 只/分钟, 预计 06:30 到点前剩少量转债/退市股 ③无需修
  - **06:53 晨检(07:03 执行)**: ①桃哥 35 天重跑 03:51 ALL_DONE, 过程文件 redo_taoge_1011.*/vision_by_claude_1011.* 已删(35 天清单留存于此, 供 N3 核查用: 2025-08-05,2025-08-08,2025-08-13,2025-08-14,2025-08-15,2025-08-22,2025-08-29,2025-09-05,2025-09-12,2025-10-13,2025-10-14,2025-10-15,2025-10-16,2025-10-17,2025-10-20,2025-10-21,2025-10-22,2025-10-23,2025-10-24,2025-10-28,2025-10-29,2025-10-30,2025-10-31,2025-11-03,2025-11-05,2025-11-06,2025-11-07,2025-11-10,2025-11-11,2025-11-12,2025-11-13,2025-11-14,2025-11-25,2026-07-01,2026-08-21); 桃哥 distill 账本 98 天 vs results 99 天, 差 2026-08-21(移回的真实稿, 今晚 check md 补蒸馏); 2026-09-13 周日稿已在 09-14 md 且随 09-14 蒸馏, 已记账 ②scan.mjs 六榜 5/6(涨跌幅/跌幅/板块=新浪, 连板/跌停=东财 push2ex 池; 次新榜东财 push2 仍断连 socket hang up) ③baostock 已弃用, 腾讯回补 06:30 停, 已入库 7992 只 ④应用 06:58 用户重启后在线, sys_job 85 行(84 运行, 140 暂停), 15 条 0915 链 cron 07:30 未动
  - **07:52 链检**: facts 0915 07:30 生成, 六榜 5/6(涨跌/跌幅/板块=新浪, 连板/跌停=东财池, 次新 FAIL); 15 链均有 run_meta.jsonl(N1 首日生效); 进度不一(多数到 02/03, 土豆到 04, 桃哥/高概率只到 01, 大兴 01 未出)。**事故: 07:41 起 15 链全部停在 45min 额度顺延(预计 08:24~08:26 醒)**——①07:30 共享轮换状态 current 仍是 glm(遗留), 15 链全走 glm, 15 并发 07:33:56 撞 glm 限流 ②**rotation.py 竞态 bug**: on_window_limit 标的是'共享状态里的 current'而非本次调用实际用的配置, 15 链同秒失败→先切走的进程把 current 改成 gravitex, 后面的把从没用过的 gravitex/kimi-code 也标耗尽; kimi-xhj 扛到 07:41 也被标 → 4 套全灭整体睡。已修: rotation.py 只标本进程实际用的配置(已被他人标过则直接用新 current 重试); 状态文件撤销 gravitex/kimi-code 的误标、current=gravitex, 实测 gravitex 调用正常(备份 /tmp); 睡眠中的链醒后读共享状态走 gravitex。另: 02 回炉 3 次全是枚举写法(`有主线(修复初段…)`/`板块层先行`)=已证实, v02 改为以枚举值开头即归一(驱动器 --selftest PASS), 只影响之后新起的进程(盘中子链每时段都跑 02, 今天就受益)
  - **行情库第 2 段(复权因子+历史日线) — 10/12 00:3x 按用户令弃 baostock 改可验证源**: `scripts/market/backfill_history.py` 默认 `--source tencent` = 腾讯不复权日线(按日期往前翻页, 上市以来全量, 含已退市股) + 新浪 hfq.js 复权因子(股票) + 昨收按因子推导; 产物格式不变 → **Java 未改**, 跑完 runOnce sys_job 135 入库。
    - 验证(对照 baostock 5 只样本, 存 downloads/market/history_baostock_sample/): 2015 起 OHLC/昨收每只仅 0~3 处差(2016-01-04 熔断日收盘口径等), 2008 起 ≤46 处(多为 0.01~0.02 价差); 2008 前两源互有缺日, 都不权威; 涨停价 1483/1483 一致; 新浪因子 vs baostock 前复权收盘偏差 ≤0.012%, 但**平安银行 baostock 2020-12-31 无事件凭空掉因子(119.96→99.79)=baostock 错**, 新浪对
    - 已知缺: amount/换手率 NULL(腾讯不给, 每日快照段从上线日起有); 主板 + 创业板 2020-08-24 前 涨跌停价 NULL(无历史 ST 区间, 5%/10% 定不了, 宁缺勿错; 科创板/创业板改革后 ST 同 20% 照算); ETF 无因子(新浪 ETF 只给每份分红额, 非累积因子, 可另算); 北交所腾讯无日线 = 未回补; security_basic.jsonl(上市/退市日 6157 条)沿用 10/11 baostock 已拉到的那份
    - 跑法: `scripts/venv/Scripts/python.exe -X utf8 scripts/market/backfill_history.py --until 06:30`(日志 scripts/temp/history_tx_1012.log; 两 host 各 0.6~1.2s 抖动限速, 连续 5 败熔断 10min, 3 次熔断无恢复退出; 断了原样重跑=跳过已有文件续)
    - **baostock = 未来可选**: 代码保留为 `--source baostock`(全历史 amount/换手率/isST 都有, 能补上面的缺), 但 10/11 22:48 起挂死 + 因子有上述错例, 恢复前须先复核; 守候脚本 history_backfill_supervisor.sh 已删
  - **行情库第 3 段(关注集+分时)**: 新 `scripts/market/collect_minute.py`。关注集=HOLD/PLAN/POOL/MENTOR/ZT/DT/MD/FIXED/STICKY(10/09 实测 302 只); 分时=通达信逐笔聚合 1 分钟 OHLC(东财整个 IP 被断连 + 通达信 K 线命令失效后的方案), 10/09 实测 284 只量偏差全 <1%、收盘全吻合, 转债/ETF 已校正 pytdx 10 倍价格缩放; 指数用历史分时(只价量); 北交所暂缺
  - **Java(直接改仓库, JDK17 编译过 + 真实 jsonl 反序列化验证过)**: inv-common `ProcessUtils` 加 `runChecked`/`venvPython`; market 4 个 Mapper 加物理删除+批量插入(+3 个新 XML: AdjustmentFactor/KlineMinute/WatchlistInfo, KlineDay XML 加按标的区间删除); `IMarketImportService` 加 `importMinute`/`importHistory`; `MarketImportServiceImpl` 实现(历史回补每票一个事务, TransactionTemplate); `MarketDailyHandler` 改为 日线 → 分时 串联(分时失败不回滚日线但任务记失败); 新 `MarketHistoryHandler`(bean=marketHistoryHandler, 手动 runOnce)
  - **未做/待用户**: ①重启应用(**别在早上**: 07:30 起 15 条链要跑 2h+, 09:27 起盘中子链; 推荐 15:40~19:50 或 20:30 后, 新代码只在 15:35 任务和手动回补用到, 当天分时可事后从逐笔补) ②~~等 baostock 回补完 runOnce 135~~ → 改为腾讯源跑完后 runOnce 135 ③第 2b 段=每日除权检测+因子增量刷新(未做) ④第 5 段竞价: 通达信逐笔里有 9:15~9:25 记录, 可能能事后补, 待交易日核验
  - **scan.mjs 板块榜加新浪兜底**(10/11 23:2x, 防周一 07:30 facts 缺板块): 东财 push2/push2delay/push2his 整个 IP 被断连(push2ex 涨跌停池仍通), 实测六榜 4/6 → 加兜底后 5/6; 新浪行业(newSinaHy)+概念(newFLJK class) Top8, 输出标注「新浪口径, 划分与东财不同」; 只在东财失败时走, 正常路径不变。次新区间跌幅榜无等价兜底(新浪无 60 日区间涨跌), 仍 FAIL 标缺
  - **10/12 00:10 用户重启应用(新代码生效)**: 新增 sys_job **134 行情库-补导指定日(手动)**(marketDailyHandler, param=yyyy-MM-dd, cron 2099 不自动跑) / **135 行情库-历史回补入库(手动)**(marketHistoryHandler); 134 runOnce 导入 10/09: watchlist_info 302 / kline_minute 69884(p2026 分区), 重跑幂等不翻倍; 133 收盘任务今天 15:35 起 = 日线 + 关注集 + 分时 全自动。**纠正**: 我曾说'用户要收盘后重启'是误述, 用户原话=写完代码我可重启或等用户醒来重启
  - 其他: .gitignore 去 11 行冗余(git status --ignored 全量比对零差异); README.md/README.zh-CN.md 按 §6 草稿更新(草稿节已删); 当日新 Java 注释改新模板(@since 只到日期/**/); Java 解释性 `//` 全改 `/* */` 上一行(33 处, 注掉的旧代码不动)
- [✅10/10 凌晨收官] 10/8 补跑 12/12 完链; 回放入账 10/8(10笔)+10/9(30笔)双日 EOD 重算; **两日战报: xingjianye +11.03% > liuyiqing +3.39% > gaogailvfuli +1.51%**(report.html 粗细虚三层配色已生效); distill 天哥14天+卢本圆15天欠账全清; key 轮换立法(kimi-code↔xhj, 撞5h窗切 AUTH_TOKEN)
- [⏰周一] 9:07 监控 cron → 9:15 十三链首考(周末无链, TradingDayUtils 跳非交易日) → 15:05 EOD → 首份实盘全员 report
- [⏸10/10 23:3x 已停] 9/28-30 补跑**语义错误, 用户令"暂停→修→重跑"**: facts.mjs --date 只改标签(六榜/快照/state_digest 全现场实拉), 链读写实盘账本 → 产出=10/12 生效单(锚 10/9 价, 起点=现持仓), 非 9/28 当日单; 已进账本的 9/28 标签 open 单 6 本(a658/bianbenling/chong5000w/daxing/gaogailvfuli/xuanqiucaijing) 周一由 matcher --once 跨日作废(matcher.mjs:274)自动清, 禁对 9/28-30 跑 --replay; lianghuaxiaohao 9/28 败于 blind(validate_report.md 缺)未 emit; 9/29 lianghuaxiaohao 半截 live-20260929 残留。旧 taoge/cb 9/28-30 plans 也是 10/7 夜补的(同样污染), 13 股票链全需重跑
- [📋10/10 23:5x 用户定序] ①as-of 补跑(建+跑, 同日 3 路并发) → ②桃哥 sum 积压 19 条 → ③distill 0707 断点; 9/28 再败不干预, 9/29/30 照跑, 三天完统一列失败项待裁
- [🏃10/10 23:54 跑着] **as-of 补跑**: `P=3 bash scripts/temp/asof_928_930.sh`(幂等续跑, 断了核进程后原样重跑); 进度=scripts/temp/asof_928_progress.txt, 日志=scripts/temp/asof_logs/, 沙盒=scripts/dfcf/paper/sandbox/asof-0928(已 gitignore), 产物=results/<skill>\_chain/asof-D/。13 股票链(taoge+12 导师; cb 缺转债日线不跑)×3 天, 3 路并发预计 ~8h
    - 已建(代码): snapshot.mjs snapAsof/prevTradeDay+CLI --asof; scan.mjs --asof(东财历史 ZT/DT 池+归档样本涨跌幅榜, 次新/板块标不可得); rotation --digest --asof; facts.mjs PAPER_ROOT/PAPER_ASOF(导师小节改读 D-1 md); matcher/report PAPER_ROOT 沙盒+asof 日线前收/收盘+禁 --once; replay 加一字拒买/开盘破 cancel_below 失效两闸; run_taoge_chain --asof(prompt 头声明生效日=D、禁读未来; 跳 pool_merge)
    - 顺手修: ①scan 跌停池 sort=fbt 致空池→实盘跌停榜此前一直降级新浪, 已改 fund:asc ②matcher SOURCES 10 本重复→replay/eod/once 双副本, 成交统计翻倍(10/8"10 笔"/10/9"30 笔"疑重复计数), 已去重
    - 待用户看: skills/taoge-skill/persona/pools.json 有未提交改动, 疑为作废的 9/28 旧链 pool_merge 写入(未动)
    - 不自信点: persona 规则库/发哥记分/pools.json 均为当前版(含 9/28 后知识, 机械去不掉); LLM 有读文件能力, 禁读未来只靠 prompt+盲审③; 日线为前复权(10 月除权会微偏); 涨跌幅榜仅 ~750 只样本
- [✅10/11 凌晨 matcher 三修, 已测] ①EOD 补算历史日=读日线当日收盘(原用实时快照, 10/8≡10/9 nav 根因); nav 只追加(已有=跳过 exit0, 重算须 --restate, 旧值进 navRestated)——用户认可, 此前 6 个交易日的改写接受不追溯 ②T+1: 可卖=持仓−当日买入(原未实现, 盘中子链可卖当日买的票) ③replay 计数分开成交/拒单。Java/DB 零改动(PaperEodHandler 按当天日期调, 兼容)
- [✅10/11] md/2026S1/2026-03-06.md 末行 59 字节截断重复碎片删除(llm_batch_tzzb 读它 UnicodeDecodeError 崩), 原样在 git fd4df23
- [🏃10/11 00:5x] **正例蒸馏线 §1.2**: 实测 32B 推测层**已近全量**(10 人 0 待跑, 仅 chong5000w 41 天, ~15min 后台跑, 日志 scripts/temp/llm_batch_chong5000w_1011.log)——"全历史 46h"系过时估计。**规则空的真根因=缺"历史回溯蒸馏"**: distill_daily.py 只做当日增量(10/8 起, 仅 2-3 天素材, 样本≥2 门槛过不了), 180+ 天推测层从未被提炼进 rules.md。待用户定: 每导师一个 claude -p 串行 10 人(chong5000w 源停更跳过), 证据序=逐笔成交>cases 双尾>profile 统计>32B 推测(仅作假设, 历史初稿未经 Claude 复核), 五闸门+情境四元组入 rules.md; 建议补跑完(~08:00)再开防抢额度。GPU 让路开关用户令删除(已删, llm_batch 原样)
- [✅10/11 12:5x] ①**多 key 自动轮换**: scripts/claude_profile/rotation.py(公共模块)+rotation.txt(本机顺序 gravitex→kimi-code→kimi-xhj→glm, 不进 git), run_taoge_chain.call_claude 接入: 撞 5h 窗口=标记该套 5h 耗尽并立即切下一套重试, 全耗尽才顺延 45min; 状态多进程共享(.rotation_state.json), 每次调用记 profile_log.csv(查某天是否混用模型); 模拟 4 次撞限切换验证正确 ②**行情共享缓存**: snapshot.mjs 读穿缓存 downloads/quotes/live/snap_cache.json(盘中 20s/盘外 10min 新鲜, 缺的合并腾讯批量请求, 批量缺/北交所逐只多源兜底, 原子写多进程安全, 结果带 age_s); 68 只冷启动 267ms(原逐只 4-5s)、命中 0ms; matcher/facts/cand_snap/report/导入全自动走缓存, 回归全过
- [✅10/11 12:4x] ①**盲审失败=降级照发**(用户定): 驱动器 7 处盲审相关中止改抛 BlindDowngrade, 捕获后用最后一版过机械校验的 06 照发, plans 备注前缀【未过盲审】, run_dir 留 BLIND_FAILED.txt; 日报加「未过盲审照发」「挂单被拒(import_rejects.csv)」两行 ②10/9 上午 reset_books(手动一次性, 无定时)清空 A-cb/A-taoge 订单却留导入哈希→补导被判重复: 土豆 10/8 三张转债单、桃哥 10/8 四张删哈希重导+再重建; 现 A-cb 10/9 累计 +0.14%, A-taoge +2.17%
- [✅10/11 12:xx 午间一轮] ①服务: 我 01:44 脱离会话起的实例占 8888 致用户 IntelliJ 重启失败→已杀, 用户 11:57 IntelliJ 重启(新代码已编进) ②**导入静默丢单 bug**: matcher import 取前收 `snaps[0]`(snapMany 返回 {code:snap})恒 undefined→全靠 ~750 只日线归档, 归档外候选票一律"前收不可用"被拒; 10/8-10/9 链发出 188 张挂单 90 张未入账。已修(取 snaps[code]; 归档缺则补档; 补导历史日用该日日线前收)+被拒行落 import_rejects.csv; 用户令补回: 56 张重新入账(27 张=10/8 补链按 10/9 价定价被正确拒, 1 张买单带 stop_below), rebuild_days 重建 10/8-10/9(备份 books.bak-pre-reimport-202610111231): 星见野 +7.4%/桃哥 +2.2%/刘忆青 +2.8%/边学 +1.5% ③EOD 前一交易日排除节假日占位行(10/7 误算拟人度已删) ④report 加「数据集」切换: 实盘(10/8 起) / 回放 9/28-30(沙盒), 补跑 ALL_FINISHED 后自动重生成主报告 ⑤B站补档 v2: 去时间窗, 只靠 GPU 守卫+scripts/PAUSE(记忆 feedback-gpu-pause-protocol) ⑥多机 Claude 配置: **已移出本项目**(10/11 用户令)→ <dev>/switch-claude-settings/{profiles.json,cs.mjs,cs.cmd,switch-claude-settings.cmd} 4 配置(gravitex/kimi-code/kimi-xhj/glm, 模板无 key, key 读 <dev>/\*.txt=工具目录上一级, 各机 dev 路径不同也通用; 双击「switch-claude-settings.cmd」选序号=改本机 settings.json, 用户亲手执行); 本项目只留 scripts/claude_profile/rotation.py(自动化轮换, 找 <项目上一级>/switch-claude-settings/cs.mjs, 缺则不轮换), `--settings` 叠加不改 settings.json, 三套实测模型切换正确; 待做=链/桥接撞额度自动轮换 ⑦微信补发循环已停(用户: 微信↔Claude 不用研究)
    - 大兴大A/高概率复利 10/8-9 为 0 的原因: 大兴 10/8 两单(一张 10/9 价定价、一张买单带 stop_below)均被拒, 10/9 无任务未跑; 高概率 10/8 唯一买单价格笼子废单, 10/9 链盲审失败未发单(盲审失败策略待用户定, 已解释中)
- [✅10/11 07:5x 额度与输出两修] ①**04:03 周日凌晨即撞 Claude 5h 额度窗口**(蒸馏+补稿+as-of 3 路叠加), as-of 三链 03:38-04:03 起停在 45min 顺延循环里(07:57 探测 API 已恢复; 08:47 核实三链已自动续完: daxing/xingjianye 08:14、bianbenling 08:24 均 exit=0, 无需干预); 防周一 07:30 实盘全链撞窗: 新 `scripts/temp/mon_pause_asof.sh`(后台) 周一 02:30 停 as-of(psutil 精确杀编排/xargs/--asof 链树) → 15:35 用 `asof_928_930_v2.sh` 续跑(v2: 交易日 02:30-15:30 让路 + PYTHONUNBUFFERED 日志实时; 断点续跑), 日志 scripts/temp/mon_pause_asof.log ②**claude -p 经网关(api.gravitex.ai)在 JSON 前打印 auto mode 横幅** → stdout 非纯 JSON: 桥接 ask_claude 拿不到答案(微信转 Claude 全失效)、链 token 记账丢; 加 `_claude_json`(取最后一行 JSON 对象)到 run_taoge_chain/ask_claude/distill_history, 桥接复测 19s 正常
- [✅10/11 03:2x 周一可用性复审(自动, 用户令免裁决)] ①蒸馏 10/10 合并、索引+同步、as-of 已启(control/liuyiqing 9/28 已完, 约 27min/链) ②15 skill 实盘 dry 链全通过 ③selftest+全部 node --check 过 ④sys_job: 15 条 07:30 全链/misfire 全=1/无 14:55、9:15 残留 ⑤服务 8888=pid 15920, 40 threads ⑥TradingDayUtils: 10/12 判交易日✓。**复审中修**: gen_rules_index 只认 "### R1"——天哥/卢本圆(列表式 "- **A1 …**")、量化小号("#### R1")、土豆(persona/buchitudou0/ 子目录)此前无索引(链只能全量读 rules.md), 已兼容三种格式+子目录回落+索引头路径不再写死 taoge; 14 skill 索引全生成(天哥 27/卢本圆 23/量化小号 10/土豆 7…), sync_skills 完成
- [✅10/11 02:36 回溯蒸馏合并] 10/10 导师全 OK(总成本≈$34, 约 1h50m), 已直接并入 skills(用户令免审; 旧版 results/distill_history/<lg>/rules.before.md): 宣秋财经 0→16 / 边学本领 5→13 / ST之狼 0→10 / 高概率复利 0→10 / 星见野 5→10 / A658 4→9 / 刘忆青 5→9 / 冲5000w 0→9 / 大兴大A 0→8 / 量化小号 5→5(核销无新规过五闸门); rules_index 逐 skill 重建+sync_skills 完成; 02:36 as-of 补跑从头开跑(14 链含对照组)
- [🏃10/11 01:5x 排队] **B站倒序 30 天 backfill**(用户令: 所有结束后) `scripts/temp/bili_backfill_after.sh`(后台): 等 asof 补跑 ALL_FINISHED → A 段 `--up qushitiange|lubenyuan --desc --max 30 --stage download`(GPU, 引擎时间窗) → B 段交易日 20:00 后/周末 `--llm-batch`(写 md+distill, 闭环); 日志 scripts/temp/bili_backfill_after.log。待办基数: 天哥 146 条/卢本圆 92 条
- [✅10/11 03:23 自动复审已执行] 结论见下条; 微信结论(388 字, results/reports/wx_review.txt)排在合并报告之后自动发(iLink 限流中, /tmp/wx_retry3.sh 每 10min 重试)
- [✅10/11 01:3x-01:5x 周一可用性审查+修复(子代理只读审查发现 3 阻断)] ①Quartz: QuartzConfig 自建 SchedulerFactoryBean 不吃 yml→默认 10 线程+5s misfire; 改 40 线程+misfire 10min, 61 个链任务 misfire=执行一次; 服务已由我脱离会话重启(pid 见 logs/inv-admin-20261011-0144.log, 启动日志确认 40 threads; IntelliJ 侧显示已终止属正常) ②handler 超时形同虚设(先读 stdout 到 EOF 再 waitFor): 新增 ProcRunner(独立线程读输出+超时杀进程树), 4 个 paper handler 改用; 全链 180min/子链 40min ③驱动器: 429 误判(模型正文金额含 429 即顺延 45min)→仅失败时查错误文本且 429 须独立数字; 全局 claude 并发闸 6(.claude_slots 文件锁, psutil 回收死槽); TimeoutExpired 捕获; 同 skill 互斥锁(全链未完子链跳过); 实盘 facts 同 slot 首链构建其余复用; rules_index 按 --skill 建; selftest plans 改临时目录 ④matcher: 账本互斥锁(.matcher.lock, once/import 不再互相覆盖); EOD 实时价缺回退日线+告警 ⑤sys_job: 15 skill 盘前全链 0915→**07:30** 起跑(原 9:15 起跑 45min+ 才出单), 尾盘 1455→**14:35**(原单永远来不及撮合); 补建大兴大A 0915/1000/1455(原无任何任务) ⑥拟人度 similarity.mjs v2(成交日取 id 前缀/持仓按流水重建/无信号日不计/加对照组 delta/同日覆盖), EOD 自动算前一交易日→similarity.json; report 加拟人度表+「本周以来」区间切换; 新 daily_digest.mjs(EOD 后微信推日报, 实盘才推); 账户元数据抽 accounts.mjs 共用 ⑦as-of 补跑编排加工作日 07:00-15:30 让路实盘
    - ⚠ 未修(低优): TaogePaperSentinel/Settle 两个旧 Windows 计划任务每日失败(脚本目录已不存在), 待用户确认后删
    - ⚠ 微信 iLink 主动消息=服务端 ret -2 限流(非本地冷却): 疑额度挂在用户最近一条消息的 context_token 上, 连发 2 条后 6h 重试全败; 用户给 hermes 发任意消息后恢复。待发队列 /tmp/wx_retry4.sh(合并报告 wx34 → 复审结论 wx_review, 每 15min 最多 24h); 日报(15:05)同受此限, 当天用户问过 hermes 才发得出
- [✅10/11 01:3x 微信「c:」转 Claude] scripts/hermes/ask_claude.py(同日续会话/只读工具/170s 超时→kimi 兜底/问答记 snapshots/hermes) + hermes skill investment-tool/claude-trade-relay(自动识别交易类+「c:」强制/「k:」kimi; 先 hermes send 回执); 本机实测 15s 出答案、追问能续上下文。⚠ 用户 CLAUDE.md「微信问答/盘中决策/做T单归 hermes(kimi-k3) 直连」需用户自改为新分工
- [✅10/11 01:2x 10/8-10/9 账本重建] 根因三处: ①EOD 覆盖(10/8 用了 10/9 价) ②旧回放=碰价即按挂价成交(买贵卖贱, 如冲5000w 挂 22.54 买、当日区间 18.97-20.2 仍按 22.54) ③时间穿越(10/8 回放晚于 10/9 回放, 卖出"未来"才买的票)+链回炉重复 emit 的同键单双份成交。修: matcher replay 对齐实盘(开盘可成交侧按开盘价+价格笼子±2%废单+板限区间闸, 盘中触价按挂价; 先卖后买; 缺日线先补档); EOD 补算历史日跳过建账晚于该日的账本; 新建 rebuild_days.mjs(保留实盘真实成交与哨兵结论, 同键重复只留一张, 其余从 10 万逐日重放→EOD), 拷贝演练两轮后对真账本执行, 备份 scripts/dfcf/paper/books.bak-202610101722(已 gitignore)。结果: 星见野 +11.0%→+6.1%, 刘忆青 +3.4%→+2.4%, 桃哥 −0.2%→+1.8%, 两日曲线不再平
- [🏃10/11 01:2x 自动衔接] `scripts/temp/finalize_1011.sh`(后台): 等回溯蒸馏+补稿 sum/distill 都 ALL_DONE → 有 DONE 的导师 rules.md 直接合并进 skills(用户令免审; 旧版留 results/distill_history/<lg>/rules.before.md)→各 skill rules_index+sync_skills→清 as-of 沙盒/产物/进度→asof_928_930.sh 从头重跑(14 链含对照组)。日志 scripts/temp/finalize_1011.log
- [✅10/11 01:1x 周一预检全过] selftest/实盘 scan(跌停池已走东财)/facts 实盘口径/链 dry(实盘路径)/matcher --once --dry(9/28、10/8 残单跨日作废)/EOD 只追加 全通过; 加固: 驱动器实盘模式清残留 PAPER_ROOT/PAPER_ASOF; book_nav 改用最近 EOD 市值 nav(原=现金+成本≈恒 10 万, 浮盈亏不进仓位帽)。⚠ 次新/板块榜今晚东财 push2 限流 socket hang up(测试打太多), 周一 9:07 监控须核这两榜
- [✅10/11 对照链上线] control-skill(persona 恒空, chain.md 由 liuyiqing 版换名)+驱动器 SKILL_CFG+matcher SOURCES(A-control 已建 10 万)+report 黑点线; sys_job 127/128/129 = control:0915/1000/1455(API 建, 已生效); as-of 编排名单已加 control。顺修: 12 份盖章 chain.md 的 01「导师信号速览逐源回应」名单误把桃哥/天哥换成自身名, 已统一改回 taoge 原版名单
- [✅10/11 report.html 重写] 东财/同花顺式累计收益率走势: 14 skill 线 8 色×实/虚线+对照组黑点线+上证指数灰粗线; 悬停竖线吸附交易日, 浮窗按累计收益降序列全部账户(累计+当日, 红涨绿跌带符号)+当日数据来源(实盘撮合/回放估算/重算); 点图例只看选中; 线尾直标防重叠; 明暗主题; 逐日数据表; 持仓/挂单/成交一律"代码 名称"(名称缓存 scripts/dfcf/paper/names.json); x 轴=交易日且实盘自 10/8 首跑(之前占位 10 万行不画)。headless Chrome 截图验过(含悬停)
- [🏃10/11 01:08] 补稿后续 `scripts/temp/up_sum_1011.sh`(后台): 等天哥 2 稿 VISION_DONE → 单 claude -p: 卢本圆 sum→天哥 sum→卢本圆 distill→天哥 distill; 日志 scripts/temp/up_sum_1011.log。卢本圆 2 稿已 VISION_DONE(01:02 job 手动触发), 天哥 job 34 已手动触发处理中
- [✅10/11 00:5x] B站下载 mid 错配已修+生效: 根因=BilibiliVideoServiceImpl.downloadOne 调 fetch_bilibili.mjs 未传 --mid(脚本缺省按桃哥校验归属); 已加 `--mid v.getAuthorMid()`+mid 对照表注释(625315686=股市-桃哥复盘/550494308=卢本圆复盘/1372241958=趋势天哥, B站 card 接口实核); 用户 00:49 IntelliJ 重启(class 含 --mid 已核); 用户授权重置 10/6 后 4 条沉底行(retry/status→0, remark 留原因)——卢本圆 2 条 07:00 job / 天哥 2 条 16:30 job 自动重下。**之后待补**: 4 稿转写落 md(10/6-10/9 天哥/卢本圆小节)→该几日 UP sum/distill 补跑; 另 10 条卢本圆 9 月历史稿仍沉底(归 backfill 域)
- [⏸10/11 00:45 用户令] **as-of 补跑暂停, 改序=先回溯蒸馏沉淀→再从头重跑补跑**(保证 13 链规则版本一致); 9/28 已跑结果作废, 重跑前清 results/_\_chain/asof-2026092_/ + 沙盒重建(rm sandbox/asof-0928 → --init) + 清 asof_928_progress.txt。已告知用户代价: 新规则含 9/28-10/9 史料, 回放带后见之明, 报告须标注
- [🏃10/11 00:44] **历史回溯蒸馏** `scripts/tzzb/distill_history.py`(新建, 与 distill_daily 同族): 每导师 机械层(gen_tzzb_profile 统计+全历史小节抽取)→单 claude -p 五闸门+情境四元组→产物暂存 results/distill_history/<ledger>/{rules.md,report.md}, 不碰 skills/; 10 人串行(stzhilang 首), 日志 scripts/temp/distill_history_1011.log。完→用户审→合并进 persona(合并后 gen_rules_index+sync_skills)→重跑补跑
- [✅10/11 用户裁] pools.json 10/10 +9 票保留
- [✅10/11 用户问] pools.json=taoge 方向→个股登记簿(低吸池真源; 上游=04 扩池提案 pool_merge 自动落+人工; 下游=facts 在池率/临时池+13 链 04 选股)。10/10 +9 票(算力芯片AI硬件 6/文化传媒出版 3)来自作废的 xuanqiucaijing live-20260928, 但内容=10/9 真实涨停方向, 建议保留(待用户定)
- [📋10/11 用户定方向] ①**正例蒸馏线 §1.2 先走**(填空 rules; 32B 本地零 Claude token 可与补跑并行; 待裁=近 60 日 15h vs 全历史 46h, 建议前者) ②**空 skill 对照链**(同模板 persona 空, 打分=skill 链−对照链, 同时抵消模板改版影响) ③**立法→代码**: 契约校验→run_taoge_chain.py VALIDATORS(py)+selftest 反例; 行情/执行闸→matcher.mjs; 事实层→facts.mjs; Java 只调度不放规则。22 补丁列表逐条判"可代码查?"→转校验器并删 prompt 文字→改 taoge 模板重盖章 13 份→token_log 量化回炉率前后; 周末一次性改+记版本 ④两周选择器打分=拟人度(skill−对照)×导师真人长期表现(tzzb 180 天+), 14 天 paper 收益只做回撤一票否决(收益排名 14 天=噪声); 3UP 无账本→观点-决策一致度(桃哥 IC 起步)
- [🔨在建→重跑] **as-of 补跑**(施工清单, 已完成 1-5, 6=首检 00:41)(10/10 定 A 方案=沙盒独立成段"回放估算"3 日曲线, 实盘 10/8 起账本/两日战报不动; B=连 5 日需重算 10/8-9, 用户未选)。代码零改动, 施工清单:
    1. 沙盒: env `PAPER_ROOT=scripts/dfcf/paper/sandbox/asof-0928` 覆盖 books/plans/facts/nav/state_digest/report 路径(matcher.mjs DIR、report.mjs DIR、facts.mjs DIR、run_taoge_chain PAPER 的数据部分; token_log/params.yaml 仍走真目录; 注意 matcher/report 内 `DIR/../../..` 拼 downloads/md 的相对路径要改锚脚本目录)
    2. facts as-of(env `PAPER_ASOF=yyyy-MM-dd`, 以 D 前一交易日收盘为准): scan.mjs 加 `--asof` = 东财 ZT/DT 池按日期 + 强势股池 QS 代涨幅榜, 涨跌幅/板块/次新榜标"回放不可得"禁编; 快照/一字/日线锚改读 downloads/quotes/daily(753 只, 752 含 9/30; 缺票用 kline.mjs 补档; 前复权偏差列不自信点); rotation --digest 加 --asof 截断 <D; 导师速览当日 md 小节需核是否盘后内容(有则 as-of 改读 D-1)
    3. run_taoge_chain `--asof <sandbox>`: 产物 asof-D/(不覆盖 live-D); cand_snap 走日线(现价=前收=D-1 收); 跳过 pool_merge(不写 persona 池); asof 下 facts/rules_index 由编排脚本每日建一次、链复用(防并发踩同目录+东财封 IP); prompt 头注"当前=D 09:15, 生效日=D, 禁读 D 之后信息"
    4. matcher: import 拒落账闸/eod 收盘价在 asof 下读日线(现走实时 snapMany); replay 不变
    5. 编排 scripts/temp/asof_928_930.sh: 沙盒 --init → 每日[建 facts→13 链(taoge+12 导师, cb 暂缺转债日线不跑)→replay D→eod D] ×3; 串行≈24h, 同日各账本独立可并发(开几路问用户)
    6. 冒烟: 先单链 --dry 走通, 再真跑 1 条核 06 生效日=D 且锚=D-1 收
    - 偶发: lianghuaxiaohao 9/28 blind 未写 validate_report.md(10/8、10/9 同链正常=非模板坏)
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

1. ~~正例蒸馏预算~~ ✅10/11 用户裁: 全历史 46h(已开跑, 见 §0.5)
2. 桃哥 sum 19 条清账时机(任一夜间空档即可, 无需裁决=默认下周某夜)
3. players.json 已建(10/9 晚)——新 5 正例(观察池 top: 东橙西柚13/我在南极拍企鹅/There_1)是否启动 distill 准入观察?

# §3 项目进度快照（10/9 收盘口径）

**已落**: 数据层(tzzb 16 账本/3UP 视频管线/CLS/fage/quotes)/决策层(13 链+03 拆环+05 风控+盲审+负例+否决条款池)/评价层(scorecard+negstats+players.json+相似度 v0)/工程层(调度器修复/replay 模式/幂等三件套/行为立法 13 条)

**TradingAgents 差距**: 分析师团队≈平齐 / 多空辩论雏形(升分层=§1.6) / 风控票级(组合级=§1.7) / 回测估算口径已落(--replay) / 多 LLM 协作已反超(云端+32B 两级)

# §4 持续线（低频维护, 等触发再做）

| #   | 项                                                                                                                                                           | 触发                        |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------- |
| 1   | backfill 历史视频(天哥剩 154/卢本圆 99)                                                                                                                      | 夜间空档, PAUSE 闸管理      |
| 2   | cls wjzt PARSE_FAIL 历史 23 天                                                                                                                               | 低优, 闲时                  |
| 3   | 数据源共享层 scripts/lib(sources.mjs 统一出口)                                                                                                               | PC2 闲时                    |
| 4   | venv→.venv 正名(需重建非 mv)                                                                                                                                 | 待 PC 维护窗口              |
| 5   | hermes 钩子产出核查(snapshots/hermes/ 有文件=生效)                                                                                                           | 明早首次问答后              |
| 6   | liuyiqing-skill 补建 rules_index.md 或 chain 模板剔除该输入项(10/10 盲审: 索引缺失致捞取验证不可执行, 兜底=直读 rules.md 全文, 登记于 live-20261008/06 §0.6) | 下次碰 liuyiqing persona 时 |

# §5 中长期架构（10/11 晚用户提出; 【用户】=用户手写, Claude 出 spec+讲解+review）

0. ✅10/11 20:1x 已上线: N1 链运行记 persona 版本(run_dir/run_meta.jsonl) / N2 report「相对导师真人」口径(无账本退上证) / report 单报告合并 9/28-30 回放+实盘一条时间轴(沙盒不再出独立报告)。待裁: 权重=按相对导师超额排名的具体公式(并入打分公式冻结)

1. **inv-ui【用户】**(10/11 用户定): Vue3 + Vite + TypeScript + Pinia + Vue Router + Element Plus + ECharts, 后端=现 Spring Boot 8888 REST; 用户手做, Claude 按里程碑出 spec/讲解/review, 顺带复习 dev/dev-notes/vue(vue3.md/pinia.md/element)。页面优先序(Claude 建议, 待定): ①链路追踪(01→07 每步输入/输出/契约/重试/耗时/token → 终裁单 → 成交 → 盈亏) ②paper 报告(替代 report.html) ③管线健康与对账看板
2. **行情库 investment_market【用户审 DDL → 建库; 采集脚本 Claude 写, Java 入库层用户抄写】**(10/11 晚定稿 v2; **10/12 凌晨: 第 2 段换腾讯+新浪(回补进行中, 腾讯封 IP 慢速续)/2b 除权/3 分时/4 外围/5 竞价(字段口径待 09:15 实测)/6 对账补采 代码全部完成并自测, 只剩第 7 段读取方接入(见 9)**; **✅第 0+1 段 22:2x 上线**: `scripts/market/collect_daily.mjs` + `cn.sichu.market` + sys_job id=133 cron 15:35, 10/9 已入库 security_master 8151 / kline_day 8123, 周一首次真实采集; 下一段=第 2 段 adjustment_factor+baostock 历史回补): `sql/investment_market/` 6 表=security_master/kline_day/adjustment_factor/kline_minute/call_auction/watchlist_info + `partition/kline_minute_partition.sql`(建表后手动执行); 全 BaseEntity; 主键仅 id(kline_minute 因分区=(id,trade_date)); 大表各 1 普通索引; 幂等=按日先删后插; 范围=A股/转债/ETF/港股通/全指数/东财板块/外围(us.NDX 等), 新三板暂不收; 分时+竞价只存关注集(watchlist_info 记入选原因, 粘滞 10 日); 数据源=东财/新浪/腾讯+通达信(分时主源)+腾讯日线/新浪复权因子(历史回补; baostock 未来可选, 10/12 弃用原因见 §0.5); 时刻=08:30 外围+标的 / 09:15-09:26 开盘竞价 / 15:01 收盘竞价 / 15:35 日线+因子+分时(预计 16:15 完); 断电恢复=分阶段 DONE 标记+补采任务按对账补(竞价不可补=标缺口); 估 7.5GB/年+历史回补 3.5GB
3. **结构化输出公共模块【Claude】**(**✅10/12 凌晨代码完成+离线自测, 真机联调待 C2 结束**, 详见 §0.5): scripts/lib/claude_call.py(stdin 传 prompt + `--output-format json` 信封判 is_error/subtype + 跳过网关通知行 + 末尾 json 块 jsonschema 校验 + 副作用核验 mtime + 成本账本), 迁 backfill_bilibili 3 处/tzzb distill_daily/backfill_inference; 样板=run_taoge_chain(已是 json+contract 校验)
4. **对账 Handler + 补跑并入 bilibili_video 状态机【用户写 Java】**(**✅10/12 凌晨 Claude 已写并自测, 用户授权; 待重启生效**, 详见 §0.5; 余项: B站补跑任务 140 的 cron/参数待用户定, Python 逐视频下载/处理路径停用改走 140, llm-batch 仍用 Python): reconcileHandler 收盘后核 DB 状态 vs results/md(天数对得上=10/11 用户立法), 结果表+hermes 告警; 历史补跑改为插 NEW 行走同一 Handler(消灭 Python json 账本双轨), bilibili_video 加 DISTILLED 态; 加新来源(UP/tzzb/其他高手)时再泛化 content_item+pipeline_step
5. **链路入库【用户写 Java】**(**✅10/12 凌晨 Claude 已写并自测, 历史 95 目录已补导; 待重启后实盘自动入库**; 余项: token/成本按 skill 归属要改 driver 的 token_log 格式): paperChainHandler 进程结束即解析 live-D/ 目录写 chain_run/chain_step/decision/decision_rule(文件仍是唯一事实, DB 是索引); 另加 runOnce 补导入历史(含 as-of); 是 inv-ui ① 的数据底座
10. **paper 链订阅制可交付(用户 10/12 定: 现在纯烧 token, 但最终交付要订阅制能跑; 慢也可能是代码质量/bug)**: 目标=并发 4~6 下 0915 在 07:30→09:15 内跑完 ⇒ 每日 claude 时长从 10.1h 降到 ≤5h(10/09 实测: 159 次调用/10.1h/$84; 按步: 04=2.2h $18, 06=2.2h $18, 02=1.4h, 03 三步合计 1.8h, 01=0.9h, 05=0.8h, 盲审=0.7h; 回炉 32 次=1.5h $14)。顺序: ①**先治回炉**(10/12 起 retry_log.jsonl 记原因; 02 校验只有 3 条却 49% 回炉=疑似 bug(哨兵/mtime/枚举写法), 06 约束互相打架(40% 下限 vs 单票 10% vs 05 批准集)→ 能机械修的由驱动器自动修, 数字约束算好写进 prompt) ②**砍输出**: 04/06 平均输出 1.6 万/1.4 万 token, 只让模型出 contract+短理由, 表格由驱动器从 contract 渲染 ③**01 去重**: 15 条链各自让 LLM 消化同一份市场事实, 改为市场部分机械生成或全链共用一次 ④**03 辩论**: 非桃哥链 3 次调用合并为 1 次(影响决策质量, 需用户拍板) ⑤记录 cache_read token 看提示缓存命中(token_log 目前不记)。每做一项用 token_log 对比前后
11. **01→07 链体检与改造(用户 10/12 07:xx 令: 质量优先+考虑 token 窗口, 未来订阅制要能跑; 03 三调用保留不合并; 今天不动, 15:05 最后一个盘中时段跑完后改, 用 as-of 沙盒回放同一天做改前改后对比, 明早 07:30 用新版)**
   - **结论**: 慢和贵的根子主要在代码/prompt 设计, 不在模型
   - **用户三问的答复**:
     - 03 为什么三次调用: 多方/空方各开独立会话互相看不到=真对抗(10/4 立法: 同会话自问自答无对抗压力), 裁判第三个会话读双方陈词裁决 → 用户定保留
     - 压缩 04/06 是否影响质量: 04 一环环写推导链(方向→板块→概念→个股)本身就是模型的思考过程, 硬砍会降质量; 复述 facts/重复表格删掉无风险 → 只删冗余保留推理, 先回放对比再请用户裁
     - 缓存: 实测 gravitex 网关同一调用隔 4 秒连发两次 cache_read=0(不命中); 订阅制下会命中, 精简后系统提示更稳定更易命中
   - **今早实测问题(按影响)**:
     1. 每次 claude -p 先付约 4 万 token 固定开销(Claude Code 默认系统提示+工具定义+项目 18 个 skill 描述+CLAUDE.md+记忆索引, 链用不到大部分), 问一个字也 $0.20, 10/09 的 $84 约 $30 花在这 → 精简参数 `--exclude-dynamic-system-prompt-sections --disable-slash-commands --strict-mcp-config --tools Read,Write,Edit,Grep,Glob,Bash` 实测 1.5 万 token/$0.077(**-62%**), 只关链用不到的, 零质量风险, 订阅制可用(`--bare` 拒 OAuth 不能用)
     2. **06 回炉主因=数字约束互相矛盾(bug)**: params.yaml regime 退潮总仓≤15%/单票≤10%、普跌总仓≤5%; 测试下限总买仓≥40%(tzzb 系 80%); 04 prompt 却写 50%; 05 看不到下限只按单票 10% 批 2~3 只 → 06 从批准集凑不够 40% 只能回炉(10/09 终裁单'四单 29.8%<40%'即此); tzzb 系 80%÷单票 15% 至少要 6 只批准票
     3. 桃哥 profile.md 180KB(约 5~6 万 token), 02/03×3/04/05/06 七步各读一遍; 其他导师 35~60KB
     4. 01 事实采集重复 15 遍: 15 条链让 LLM 各自消化同一份市场事实
   - **每步作用/问题/改法**:

     | 步骤 | 做什么 | 问题 | 改法 |
     |---|---|---|---|
     | 01 事实 | facts.txt(机械生成)摘成事实摘要, 逐源回应导师信号 | 15 链重复; LLM 摘要可能丢细节 | 市场部分全链共用一次摘要, 各链只机械追加自己的导师信号+持仓(用户定要做) |
     | 02 定市况 | 市况三态/先行层/方向清单 | 只 3 条校验却 49% 回炉, 疑格式或 bug | 等 retry_log 原因再修 |
     | 03 辩论 | 多空各自独立陈词+裁判 | 设计合理 | 保留 |
     | 04 方案 | 两组候选(遗留票+方向推导) | 输出最大(平均约 1.6 万 token); 不知仓位约束 | 注入算好的约束; 去冗余先对比测试 |
     | 05 风控 | 逐票批准/否决 | 看不到测试下限 → 06 凑不够 | 驱动器算好下限/单票上限, 告诉它至少批几只; 不够在 05 当场回炉, 不拖到 06 |
     | 06 终裁 | 出单(价格锚/数量/失效条件/规则引用) | 约束打架; 读 01~05 全文约 70KB | 数字统一以 params.yaml 为唯一源, prompt 不写死数字 |
     | 盲审 | 独立会话只看 01+06 审计 | 设计好 | 保留 |
     | 07 复盘 | 晚上对照当天实际 | — | 暂不动 |

   - **施工顺序**: ①精简调用参数 ②数字约束由驱动器算好注入 04/05/06 + 统一 50%/40% 口径(以 params.yaml 为准, regime 与下限冲突时下限优先) ③01 共享 —— 三项零/低风险, 今晚做完回放验证, 明早上线; ④02 回炉等今天 08:47 retry_log 数据再修; ⑤profile 分层(profile_core.md ≤20KB 给链用, 全量留 distill) 与 ⑥04/06 去冗余: 先回放对比, 拿给用户看了再裁
   - **验证**: 每项用 `--asof` 沙盒回放同一天, 对比改前后 token/耗时/终裁单差异
12. **git 误收编译产物(用户 10/12 发现)**: 75 个 `target/` 文件被纳入 git(inv-admin 11 / inv-common 31 / inv-system 33, 含 .class 与 target/classes/application.yml), 每次编译都出 diff。原因: .gitignore 第 2 行 `/target/` 只匹配仓库根目录, 第 54 行只单独忽略了 `inv-stock/target/`。修法(待执行, 需用户同意后提交): .gitignore 改为 `**/target/`(删掉 inv-stock 那行) → `git rm -r --cached inv-admin/target inv-common/target inv-system/target`(只从索引移除, 本地文件不删, 不影响 IntelliJ 运行) → 提交; PC3 pull 后同样生效。注意 target/classes/application.yml 是编译拷贝, 真源是 src/main/resources/application.yml(含库密码, 确认真源是否也该出 git 另议)
13. **盘中盯盘复用 paper 行情层(用户 10/12 立: 整个项目一体, 高内聚低耦合, 加功能别另起数据)**: scripts/dfcf/live_watch.mjs 个股走 snapshot.mjs 共享缓存, 涨跌停/连板/板块读 paper 最新时段 facts 的 scan 段(零请求)。余项(收盘后做, 盘中不改 paper 依赖): ①snapshot.mjs 支持带前缀的指数代码(sh000001 等, 同一 snap_cache.json), live_watch 改调它, 去掉自带的每分钟腾讯 qt ②scan.mjs 导出各榜函数+结果缓存(TTL 3min), 让 facts.mjs/live_watch/hermes 同读一份 ③交易日 09:15 自动起 live_watch(sys_job), 持仓/关注列表从 snapshots/live_account.md 读
6. 往后放: 知识图谱(先做结构化表如 zt_stock_daily, 将来直接导图) / PostgreSQL 迁移(pgvector RAG、AGE 图、Timescale 时序) / LangChain 不引入
7. ✅10/11 晚 **buchitudou0-skill persona 已拍平**(用户令, 废止 10/6 选手分区立法): 子层文件上移, 两份 profile 合并(v2 为主+9/27 API 实测事实表), 7 处特判全清(facts.mjs/gen_rules_index.mjs/gen_tzzb_cases.py/SKILL.md/chain.md/tzzb SKILL.md+distill.md), rules_index 重建, sync_skills; 验证=残留引用 0 + chain.md 路径全存在 + 0915 链 --dry 通过 + 土豆 7 条规则首次进 facts
8. **[待裁] Quartz 存储方式**(10/11 晚发现): `QuartzConfig` 自建 SchedulerFactoryBean → 实际是内存存储(RAMJobStore), 库里无任何 `qrtz_*` 表; yml 里 `job-store-type: jdbc` / `isClustered: true` 是**不生效的死配置**(会误导)。现状够用(单实例, `sys_job` 是唯一真源, 启动时加载)。代价: 应用停机期间到点的任务**重启后不补跑**(misfire 策略只在调度器活着时生效), 运行史只有 `sys_job_log`。建议(由轻到重): ①删掉/注释 yml 里 quartz jdbc+集群的死配置 ②加启动补跑: ApplicationRunner 比对当日应跑任务 vs sys*job_log, 对幂等任务(marketDaily/paperEod/tzzbFetch)自动补触发——与 §5.4 对账 Handler 合并做 ③只有将来要多实例部署才换 JDBC 存储(建 QRTZ*\* 表 + 把 DataSource 接进 SchedulerFactoryBean)
9. **行情库接入读取方**(10/12 凌晨方案细化: Java 出 REST 接口 /api/market/kline?code=&adj=qfq&beg=(DB 原始价×因子比现算前复权, 量换回手, 库内最新日<最近收盘日就 409 让 kline.mjs 回落网络源), kline.mjs 多源最前加 db 源, 先用环境变量开关灰度、与现有前复权归档逐根比对通过再默认开; 东财+腾讯同封时再加"新浪不复权×新浪因子"兜底源。前提不变: 历史回补跑完——10/12 腾讯封 IP 只回补了 492 只)(10/11 晚用户问"sum+distill 会用 DB 吗"的结论): 现在**不会也不该**——sum 3.5 技术快照要 ≥120 日日线, 库里只有 10/9 一天; distill/check-cls-md 不读行情。接入点=数据层不是 skill: `scripts/quotes/kline.mjs` 多源切换最前面加"DB 源"(读 kline_day+adjustment_factor 现算前复权, 输出与 downloads/quotes/daily JSON 同格式, 缺数再走网络) → indicators.mjs/sum 3.5/matcher/facts/hermes 全部自动受益, skill 文字零改动。前提: 第 2 段(历史回补+复权因子)完成 + 采集稳定一周。tzzb sum 2.5 的分时归档(fetch_quotes --trends-all)在第 3 段 kline_minute 上线后并入(关注集 MENTOR 标签已覆盖)

---

## 10/12 晚 链提速改造(§3-A 1~5 + 0915 产物存档) 实施与 A/B 记录

- **改动**(scripts/taoge-chain/run_taoge_chain.py + 14 份股票链 chain.md, 回滚=git checkout HEAD 该文件):
  1. claude -p 加 `--exclude-dynamic-system-prompt-sections --disable-slash-commands --strict-mcp-config --tools Read,Write,Edit,Grep,Glob,Bash`, prompt 改走 stdin(--tools 可变参数会吞位置参数)。实测"回答一个字"固定开销 45262→20467 token($0.226→$0.102); 项目 .claude/CLAUDE.md 为空文件, 新旧模型所见指令一致
  2. 仓位约束: pos_constraints() 按 params.yaml(test_floor/cap_single/regime)+本链账本算 nav/单票上限/总仓下限/还差多少/至少几只, constraint_text() 注入 04/05/06 及盲审回炉 06; 写 run_dir/pos_constraints.json。持仓估值取 facts.json 的 watch(零新请求)。chain.md 第 170 行"总买仓≥50%"与第 208 行"单票≤1.5 成"改为引用约束块
  3. v06 总仓口径=持仓市值+未成交买单(同票新单会 CXL 旧单, 不重复计)+本次买−本次卖; 05 批准集×单票上限都凑不满=不可达, 放行+WARN。v05 批准+条件批准<need_n 当场回炉, v04 候选<need_n 当场回炉(两者末次尝试放行, 不因凑数中止链)
  4. 01 共享: 14 条股票链(土豆转债链除外)同 date/slot 由首条链跑 taoge chain.md 新增的 step:01m → facts/<D>/<slot>/01_market.md(锁 .01m.lock, 失败留 .01m.failed 其余链立即回落), 各链 assemble_01() 机械拼 01_facts.md=共享摘要+本链账户表+本链导师小节(MENTOR_HEAD 映射); 环境变量 CHAIN_SHARED_01=0 整体关
  5. norm_enum 认"唯一前缀"(无主线→无主线退潮); token_log 末尾追加 skill/cache_read/cache_create/asof 四列(表头已迁移, 旧行 8 列, scorecard.mjs 按位置读不受影响; 备份 scripts/temp/ab_1012/token_log.bak); retry_log 加 asof 字段; 回放用 env PAPER_TOKEN_LOG / CHAIN_RUN_TAG 分账分目录
  6. (用户 22:2x 提)archive_slot(): 每次运行结束(含 sys.exit 中止)把本次写过的产物复制到 run_dir/slots/<slot>/, 治"0915 的 02/04/06 被盘中子链覆盖只剩一版 .prev"; Java ChainIngest 只读顶层固定文件名, 不受子目录影响。10/12 及以前的 0915 正文已无法恢复(chain_step 表只存了 contract)
  - selftest 新增 13 个用例(枚举前缀/持仓口径/空仓 need_n=3/子链 bug 回归/卖后跌破下限/不可达放行/v05 末次放行/v04 候选数/01m 哨兵/assemble_01 拼装), 全过
- **A/B**(as-of 回放 10/12 0915, 沙盒 scripts/temp/ab_1012/{old,new}, 同一份 facts; 桃哥=空白账本, 刘忆青=复制实盘账本含 6 只持仓):

  | | 老版 | 新版 |
  |---|---|---|
  | 两链 claude 调用/回炉 | 22 次/3 | 20 次/2 |
  | 两链成本 | $36.93 | $25.56(-31%; 新版桃哥 $18.3/刘忆青 $7.3) |
  | 01 | 各链各跑 $3.62(含 1 次哨兵回炉) | 01m 一次 $0.75, 本链 0 token |
  | 墙钟 桃哥/刘忆青 | 57.7/43.5 min | 59.4/38.7 min(桃哥两版都走了一轮盲审驳回→06 修订) |
  | 桃哥终裁 | 5 买 ≈40.2k(盲审复审 pass) | 4 买 ≈43.9k 含 创业板ETF/科创50ETF(复审 pass) |
  | 刘忆青终裁 | **卖光 6 只持仓再买 3 只**≈43k(旧口径逼"本次买≥40%"=子链 bug 同源) | 卖 4 留 2, 买 2≈26k, 总仓≈40.5% |

  - 结论: 成本降约三成、回炉略降、终裁合理(刘忆青不再为凑数清仓换股), 10/13 07:30 上线。**墙钟没快**: 单步耗时由输出长度决定, 原先"单链 43→25~30 分钟"的预估不成立, 要提速得砍输出(§2-2 F/G)
  - 不自信点: 每版各 1 个样本; 刘忆青 02 市况新旧不同(有主线 vs 无主线退潮), 分不清是 01 共享失去 persona 视角还是 LLM 本身的随机波动; 网关这次报了 cache_read(单步几十万), 与 10/12 早上"隔 4 秒连发 cache_read=0"的实测不一致, 成本口径待明早实盘再看


## 10/13~ 链改造 F/G 回放验收

- **改动**(scripts/taoge-chain/run_taoge_chain.py + 14 份股票链 chain.md 末尾追加 + scripts/md/gen_profile_index.py 新建 + 14 个 skill 新增 persona/profile_index.md; 转债链 buchitudou0 不动; 开关全部默认关):
  1. **G `CHAIN_COMPACT=1`**: chain.md 末尾新增 `step:04c/05c/06c` 精简模板(只追加, 原 04/05/06 段逐字未动, 14 份 chain.md 前缀与改前逐字节相同已核)。模型只写推理: 04=逐方向推导链(方向→板块→细分→大小票→个股, 每环证据锚/失效/置信度)+遗留组处置+不自信点; 05=否决/条件批准的推理+组合级风险+不自信点; 06=对上游的推翻/维持+竞价确认→早盘触发器+(盘后声明)+不自信点。人看表由驱动器 `render_into()` 在 contract 校验通过后机械渲染, 插在 contract 块之前(`<!-- render:begin/end -->`, 哨兵仍是末行、contract 仍是末块; 幂等; 盲审回炉版 06 重渲染): 04 候选表(含 cand_snap 前收/账本持仓)、05 逐票结论+批准计数+组合约束、06 挂单表+总仓算账(同 v06 口径)。contract 新增可选字段: 04 `pos/conf/why`、05 `portfolio`、06 `why`
  2. **F `CHAIN_PROFILE_INDEX=1`**: `gen_profile_index.py` 把 profile.md 按标题切节(无子标题的超长节按行切片 ≤6KB), 机械算行号/KB/sha8; 「讲什么/适用步骤/优先级/核心摘要」用一次 claude -p 标注(桃哥 55 节 $0.69 / 天哥 17 节 $0.51 / 卢本圆 10 节 $0.44), 画像 ≤8KB 的 11 个 tzzb skill 不调模型、全节全步注入; 增量重跑复用未变节标注; 元指令节机械强制每步注入。驱动器 `profile_block()` 在 02/03b/03s/03j/04/05/06 的 prompt 里拼「核心摘要+适用本步的节原文(按优先级装到 30KB)+其余节目录」, 声明"本步不必再整读 profile.md"; 按(节标题, sha8)在当前 profile.md 重新定位, distill 改过的节自动跳过+告警(不会注入错位原文)。06 contract 可选 `persona_sections`, 仅 F 开启时 v06 校验编号存在。桃哥各步注入量: 02 7.5KB / 03 19KB / 04 20KB / 05 15.5KB / 06 14.6KB(画像全文 182KB, 其中修订记录 128KB 标为不注入)
  3. **默认关闭=逐字节不变的证明**: scripts/temp/ab_fg/identity_check.py — 改造前驱动器备份(run_chain_orig.py) vs 新版, 同一沙盒(10/13 taoge 0915 全链)、假 claude(按 prompt 写合规产物)、固定随机种子: 9 次 claude 调用的 prompt 全文 + 28 个产物/plans/账本/token 台账逐字节相同。唯一差异 run_meta.jsonl 的 chain_md_sha12(chain.md 追加了模板段, 内容哈希必然变)。selftest 新增 F/G 用例全过; taoge/liuyiqing `--dry` 冒烟(沙盒 as-of)通过
  4. **10/13 晚追加(用户令, 协调者转达)**: ①`CHAIN_TRACE_TOOLS=1`(默认关) 工具调用留痕 → run_dir/tool_calls/<step>.jsonl; ②v06 盘前 supersedes 缺字样=归一为"首裁"+WARN, 不再回炉(直接生效); ③assemble_01 名称列空时从 facts.txt「关注票实时快照」补(直接生效)。selftest 加用例全过, identity_check 复跑仍逐字节一致(10/13 sandbox 的 watch 自带票名, 修复③不触发)
- **回放方法**:
  - 沙盒 scripts/temp/ab_fg/base/<D>/(build_sandbox.py): 账本按当日 facts「昨日账本状态」行机械建(现金/持仓/nav, 未成交挂单=空); facts: 10/12、10/13 复制实盘 07:30 盘前包(真盘前, 10/13 连同实盘 01_market.md), **10/09 实盘 facts 被 21:43 重建污染(关注票快照是收盘价)→ 沙盒内 as-of 重建**; 01m 每天只建一次(10/09、10/12 各 $0.8~1.0), 各版本克隆共用 → 01 不参与波动
  - 每 (版本, 日) 一个克隆沙盒, CHAIN_RUN_TAG=fg-<版本>, PAPER_TOKEN_LOG=scripts/temp/ab_fg/tok/<版本>_<链>_<日>.csv; 产物 results/<链>_chain/asof-<日>-fg-<版本>/; 15 并发槽(与实盘同)
  - 版本: old1/old2=开关全关(旧版两次=自然波动); g1=G; gf1=G+F(gf1 tzzb 两条另开 CHAIN_TRACE_TOOLS)
  - 比较脚本 scripts/temp/ab_fg/compare.py → scorecard.md; 相似度=Jaccard(02 市况一致率/02 方向/04 候选代码/05 批准集/06 单(代码+买卖方向)/06 单×价量接近度); 判据: 新-旧 ≥ 旧-旧 −0.05
  - 预算: 实花约 **$332**(回放 $326.6 + 01m $3.6 + 画像标注 $1.6 + 探针 $0.1); 为守预算 G+F 只跑了桃哥 3 天 + 刘忆青/星见野 10/13(原计划 9 次, 实跑 5 次)
- **结果 1: 决策相似度(1=完全相同)**

  | 指标 | 版本(格子数) | 旧-旧(自然波动, 同格) | 新-旧 | 差 | 判定 |
  |---|---|---|---|---|---|
  | 02 市况一致 | G(n=9) | 0.89 | 0.94 | +0.06 | ✅ |
  | 02 方向 Jaccard(字符串, 参考) | G(n=9) | 0.11 | 0.20 | +0.09 | ✅ |
  | 04 候选 Jaccard | G(n=9) | 0.56 | 0.55 | -0.01 | ✅ |
  | 05 批准集 Jaccard | G(n=9) | 0.61 | 0.57 | -0.04 | ✅ |
  | 06 单(代码+方向) Jaccard | G(n=9) | 0.34 | 0.40 | +0.06 | ✅ |
  | 06 单含价量接近度 | G(n=9) | 0.31 | 0.33 | +0.02 | ✅ |
  | 02 市况一致 | G+F(n=5) | 0.80 | 0.70 | -0.10 | ❌ |
  | 02 方向 Jaccard | G+F(n=5) | 0.08 | 0.15 | +0.07 | ✅ |
  | 04 候选 Jaccard | G+F(n=5) | 0.63 | 0.46 | -0.17 | ❌ |
  | 05 批准集 Jaccard | G+F(n=5) | 0.61 | 0.51 | -0.10 | ❌ |
  | 06 单(代码+方向) Jaccard | G+F(n=5) | 0.35 | 0.40 | +0.05 | ✅ |
  | 06 单含价量接近度 | G+F(n=5) | 0.32 | 0.37 | +0.04 | ✅ |

  逐格 [市况/方向/04/05/06/06价量]:
  - taoge 1009: 旧-旧 0.00/0.00/0.43/0.40/0.20/0.17 ; G 0.50/0.17/0.52/0.45/0.40/0.34 ; G+F 0.50/0.23/0.35/0.34/0.40/0.38
  - taoge 1012: 旧-旧 1.00/0.10/0.76/0.73/0.25/0.20 ; G 1.00/0.21/0.66/0.61/0.29/0.24 ; G+F 0.00/0.14/0.65/0.61/0.36/0.31
  - taoge 1013: 旧-旧 1.00/0.06/0.64/0.44/0.60/0.59 ; G 1.00/0.03/0.71/0.54/0.50/0.42 ; G+F 1.00/0.06/0.34/0.47/0.50/0.40
  - liuyiqing 1009: 旧-旧 1.00/0.27/0.57/0.88/0.62/0.58 ; G 1.00/0.24/0.65/0.83/0.35/0.35
  - liuyiqing 1012: 旧-旧 1.00/0.10/0.71/0.82/0.25/0.24 ; G 1.00/0.20/0.57/0.68/0.50/0.38
  - liuyiqing 1013: 旧-旧 1.00/0.15/0.68/0.82/0.70/0.66 ; G 1.00/0.29/0.37/0.50/0.53/0.49 ; G+F 1.00/0.18/0.44/0.64/0.66/0.64
  - xingjianye 1009: 旧-旧 1.00/0.20/0.24/0.20/0.00/0.00 ; G 1.00/0.38/0.38/0.33/0.20/0.18
  - xingjianye 1012: 旧-旧 1.00/0.06/0.41/0.53/0.40/0.34 ; G 1.00/0.13/0.64/0.55/0.63/0.37
  - xingjianye 1013: 旧-旧 1.00/0.07/0.65/0.67/0.00/0.00 ; G 1.00/0.20/0.47/0.65/0.17/0.17 ; G+F 1.00/0.15/0.53/0.50/0.10/0.10
- **结果 2: 成本 / 输出 / 时长 / 回炉 / 盲审**

  | 版本 | 完成 | 每链均$ | 每链均$(剔除会话中断作废调用) | 输出tok 均 | 04/05/06 输出tok 均 | 04+05+06 模型手写字节 均 | claude 累计 min 均 | 回炉 合计(会话未写产物/supersedes 措辞) | 盲审 |
  |---|---|---|---|---|---|---|---|---|---|
  | old1 | 9/9 | 11.65 | 10.88 | 189352 | 39917/37886/32039 | 53799 | 50 | 13(9/4) | 9 pass(1 次驳回 06 后复审 pass) |
  | old2 | 9/9 | 10.12 | 10.08 | 167001 | 36034/32139/24506 | 52709 | 39 | 9(2/7) | 9 pass |
  | G | 9/9 | 9.17 | 8.97 | 152022 | 24755/24518/25292 | 37449 | 36 | 6(2/4) | 9 pass |
  | G+F | 5/5 | 9.64 | 9.64 | 149645 | 30350/24097/20399 | 37912 | 34 | 3(0/2) | 5 pass |

  - 同链同日配对(新版 vs 旧版两次均值): **G n=9: 成本 -16%(剔除作废调用 -14%), 全链输出 -15%, 04+05+06 输出 -26%, claude 累计时长 -20%**; G+F n=5: 成本 -20%(-18%), 全链输出 -22%, 04+05+06 输出 -31%, claude 累计时长 -31%
  - 墙钟不可比: 27 链挤 15 槽, 后启动的排队久(G/old2 的 tzzb 链排队 30 分钟+), 只看 claude 累计时长
  - G 的 06 输出没降(25k vs 24~32k): 06 的推理段(推翻/维持+竞价触发器)本来就是大头; 降幅主要在 04(-35%)和 05(-30%)
  - G+F 的 06 都填了 persona_sections: 桃哥 S27(三态市况)/S41(厌恶追高)/S42(卖飞)/S51·S52(决策节奏/卖出风格); 刘忆青 S10/S11、星见野 S11(10-08/10-12 当日行为节)
- **工具调用留痕(G+F 刘忆青/星见野 10/13, CHAIN_TRACE_TOOLS=1)**: 两链 240 次工具调用; F 下 02~06 **一次都没再读 profile.md**(注入替代了自读); 06 引用规则 7 条, 06 步自己没捞原文的 3 条(星见野 R5/R6/R7, 全链其他步捞过, 但每步是独立会话); 模型读了 ~/.claude 项目记忆里的链笔记 3 次(chain02-pudie-definition-gap.md / chain04-direction-exact-match.md / inrepo-daily-bars-for-amplitude-and-t2.md)= 回放后见之明通道; 04 步还读了实盘 facts 目录的 10-13 scan.json(同日盘前包, 不算后见之明)
- **人工看(10/13 同一天)**: 桃哥 results/taoge_chain/asof-20261013-fg-old1|g1|gf1/{04_plan.md,06_verdict.md}; 刘忆青 results/liuyiqing_chain/asof-20261013-fg-old1|g1|gf1/{04_plan.md,06_verdict.md}
- **结论/建议**: G 质量在自然波动内、省 16% 成本与 20% 模型时长, 建议上线(设 CHAIN_COMPACT=1); F 让 04 选股和 05 批准明显偏离旧版(超出自然波动), 方向上是"画像原文真进了上下文"——旧版桃哥 182KB 画像模型多半读不全(Read 单次读不完, 且前 128KB 是修订记录)——是更像桃哥还是更差, 重合度量不出来, 建议先人工看 10/13 桃哥 04 对比再定; F 上线还需把 gen_profile_index.py 接到 distill 之后
- **不自信点**: ①旧版自己两次的 06 单重合只有 0.34, 判据只能排除大退化 ②F 样本 5 个, 天哥/卢本圆(画像 70KB/45KB, F 真正起作用的另外两条)没测 ③画像/规则用 10/13 晚 distill 后版本, 回放 10/09、10/12 带样本内信息, 模型还读 ~/.claude 记忆里的事后笔记; 新旧同样受影响, 但会压低方差估计 ④13 次"会话没写产物"回炉(old1 9 次/old2 2 次/G 2 次)的上一次调用全部在 20:46~20:48 同一时刻结束=当时在跑的会话一起断(网关/网络瞬断, 与版本无关; 当时没开留痕看不到报错, 现在开 CHAIN_TRACE_TOOLS 能记下), old1 吃亏最多, 成本已给剔除口径 ⑤supersedes 措辞回炉在 27 次里撞了 15 次(新旧同等), 修复后平均每两条链省 1 次 06 回炉
- 沙盒与脚本: scripts/temp/ab_fg/(base/、<日>-<版本>/、tok/、logs/、build_sandbox.py、launch.sh、compare.py、scorecard.md、identity_check.py、trace_stats.py、run_chain_orig.py=改造前驱动器备份、chain_orig_*.md=改造前 chain.md 备份)——你看完可删


## 10/13 动态仓位回放观察

- **对象**: 10/13 晚上线的动态仓位(params.yaml dynamic_position + 驱动器 mentor_pos_params, 10/14 07:50 生效)。旧口径=全链固定单票 15%/总仓下限 40%; 新口径(as-of 只用回放日之前的导师记录, 10/12 与 10/13 算出来相同): 桃哥 25%/40%(默认) / 刘忆青 95%/0% / ST之狼 45%/0% / 量化小号 70%/80%
- **方法**: 照 ab_fg。沙盒 scripts/temp/ab_dyn/base/<D>/=按实盘当日 0915 facts「昨日账本状态」行机械建账本(该日开盘前真实持仓/现金, 未成交挂单=空)+复制 ab_fg/base 的 facts 与 01_market.md(新旧共用, 01 不参与波动); 旧口径=run_chain_old.py(原样加载实盘驱动器后把 DYNAMIC_POS 置 False, 没复制驱动器); CHAIN_COMPACT/CHAIN_PROFILE_INDEX/CHAIN_TRACE_TOOLS 全关(10/13 23:13 起跑的 12 次都在 G/F 默认改开之前启动=关; 之后的 launch.sh 已显式写 =0)
- **实跑 12 次(计划 16)**: 10/13 四条链×新旧 + 10/12 刘忆青/ST之狼×新旧; 10/12 量化小号/桃哥 4 次因预算($120)未跑
- **结果**(06 终裁; "06 后"=假设所有单全部成交, 卖单按股数扣; 百分比都是占 nav)

  | 链 日 | 版本 | 02 市况 | 单票上限/下限 | 开盘前持仓 | 空仓(no_trade) | 买 只/合计/最大 | 卖 只/合计 | 06 后 只数/总仓/最大单票 | 回炉 | 盲审 | $ | claude min |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|
  | 桃哥 1013 | 旧 | 普跌 | 15%/40% | 2只 19% | 否 | 3/35%/14% | 1/11% | 4/43%/14% | 1(02 哨兵, 基础设施) | pass | 14.80 | 43 |
  | 桃哥 1013 | 新 | 普跌 | 25%/40% | 2只 19% | 否 | 1/25%/25% | 0 | 3/44%/25% | 0 | pass | 11.71 | 37 |
  | 刘忆青 1013 | 旧 | 普跌 | 15%/40% | 6只 56% | 否 | 2/26%/14% | 4/41% | 4/41%/14% | 0 | pass | 9.58 | 39 |
  | 刘忆青 1013 | 新 | 无主线退潮 | 95%/0% | 6只 56% | 否 | 2/14%/7% | 6/56%(清光) | 2/14%/7% | 0 | pass | 8.71 | 35 |
  | ST之狼 1013 | 旧 | 无主线退潮 | 15%/40% | 4只 41% | 否 | 4/45%/15% | 4/41% | 4/45%/15% | 0 | pass | 9.25 | 37 |
  | ST之狼 1013 | 新 | 普跌 | 45%/0% | 4只 41% | 否 | 1/10%/10% | 4/27%(1 清 3 减) | 4/24%/10% | 0 | pass | 7.68 | 28 |
  | 量化小号 1013 | 旧 | 有主线 | 15%/40% | 5只 43% | 否 | 4/41%/12% | 5/42% | 4/41%/12% | 0 | pass | 8.50 | 32 |
  | 量化小号 1013 | 新 | 普跌 | 70%/80% | 5只 43% | 否 | 5/84%/**50%** | 5/42% | 5/84%/50% | 0 | pass | 9.61 | 36 |
  | 刘忆青 1012 | 旧 | 无主线退潮 | 15%/40% | 8只 83% | 否 | 1/14%/14% | 3/36% | 6/61%/16% | 0 | pass | 9.62 | 37 |
  | 刘忆青 1012 | 新 | 无主线退潮 | 95%/0% | 8只 83% | 否 | 1/17%/17% | 8/73%(清光) | 2/26%/17% | 0 | pass | 9.63 | 40 |
  | ST之狼 1012 | 旧 | 无主线退潮 | 15%/40% | 4只 38% | 否 | 1/8%/8% | 0 | 5/46%/14% | 0 | pass | 7.46 | 29 |
  | ST之狼 1012 | 新 | 有主线 | 45%/0% | 4只 38% | 否 | 2/20%/10% | 4/38%(清光) | 2/20%/10% | 0 | pass | 9.51 | 36 |

  - 买单明细: 桃哥 1013 旧=掌阅 13.7/新华文轩 13.5/九阳 7.8, 新=掌阅 24.9; 刘忆青 1013 旧=博纳 12.1/浦发银行 14.1(06 自注"依据仅为驱动器总仓下限承载"), 新=新华文轩 6.8/博纳 6.8; ST之狼 1013 旧=远程 14.8/银行ETF 14.9/德生 7.7/长城电工 7.6, 新=工商银行 9.8; 量化小号 1013 旧=上海电影 10.5/远程 8.1/盛视 10.8/银行ETF华宝 12.0, 新=**工商银行 50.0**/博纳 14.6/上海电影 7.9/新华文轩 6.6/远程 5.0; 刘忆青 1012 旧=雄韬 14.4, 新=九阳股份 16.5; ST之狼 1012 旧=丰元 7.9, 新=丰元 9.7/ST万邦 9.9
  - **导师真人当日收盘**(downloads/tzzb/<导师>/day_positions.json): 刘忆青 10/12=九阳股份 100%(1 只), 10/13=时代万恒 40%(1 只); ST之狼 10/12=空仓, 10/13=*ST威领 24%+ST喜临门 18%(2 只 42%); 量化小号 10/13=大有能源 68%+煤炭ETF 32%(2 只 100%)
  - 合计 **$116.06**(旧 6 次 $59.21 / 新 6 次 $56.85); claude 累计时长 旧均 36 min / 新均 35 min; 回炉全场 1 次(旧桃哥 02 哨兵错位, 与口径无关); "总仓不足""超单票上限"回炉 **0 次**(新旧都没有); 盲审 12/12 pass, 无驳回重做 06
- **行为差异**:
  1. 买入只数: 新 12 只 vs 旧 15 只(桃哥 3→1、ST之狼 1013 4→1 少了; 量化小号 4→5、ST之狼 1012 1→2 多了)。单票最大: 下限 0 的两条链(刘忆青/ST之狼)新口径反而更小(7~17% vs 8~15%), **95%/45% 的上限一次都没用到**; 桃哥用满了 25%(1 只代替 3 只); 量化小号单票 50%
  2. 总仓(06 后): 下限 0 的 4 次=14%/24%/26%/20%, 旧=41%/45%/61%/46%; 刘忆青两天都把原持仓清光(6/6、8/8), ST之狼 10/12 清光 4 只——**下限一去掉, 约束块里"regime 总仓上限参考"(params.yaml 桃哥 regime 仓位制: 普跌 5%/无主线退潮 15%/有主线 60%)就成了实际约束**, 刘忆青 1013 新版两张卖单理由直接写"承重=regime 无主线退潮总仓帽 15%, 非人格规则"
  3. 空仓次数: 0/12。下限 0 的 6 次没有一次选 no_trade, 都下了 1~2 张小额买单(都带 cancel_below 开盘过滤); "纯观望=违规"没有被触发
  4. 量化小号(下限 80%)在 02 判普跌时被下限逼到总仓 84%, 其中工商银行 50% 一只; 06 自己写了"普跌帽 5% 对应终仓约 84%, 是下限令强制出来的, 不是本链对市况的判断……用低波票迎合下限, 盲审可能判为凑数, 需要用户裁定普跌日的下限口径"(盲审实际 pass)。旧口径也有同类凑数(三条 tzzb 链都买了银行/银行ETF 当承重单), 新口径只是把凑数集中成一只大单
- **是否更接近导师真人**(只有 5 个导师-日样本):
  - 持仓只数: 新更接近(刘忆青 06 后 2 只 vs 真人 1 只, 旧 4~6 只; 量化小号 5 vs 真人 2, 旧 4)
  - 单票集中度: 只有量化小号更接近(50% vs 真人 68%, 旧 12%); 刘忆青反而更远(7%/17% vs 真人 40%/100%, 旧 14%/16%); ST之狼 10% vs 真人 24%(旧 15%)
  - 总仓: 刘忆青新更远(14%/26% vs 真人 40%/100%, 旧 41%/61%); ST之狼 10/12 新更近(20% vs 真人 0%, 旧 46%)、10/13 旧更近(45% vs 真人 42%, 新 24%); 量化小号新更近(84% vs 100%, 旧 41%)
  - 选股巧合: 刘忆青 10/12 新版买的是九阳股份=真人当天满仓那只(但只买 16.5%); 旧版买雄韬股份
  - 小结: **"少而集中"只在有下限的链上兑现**(桃哥/量化小号); 下限为 0 的链没有往导师的"1 只重仓"靠, 而是退到 regime 帽以下的轻仓
- **异常**: 无 100% 一把梭(最大 50%); 无空仓不给条件单; 有一例为凑 80% 下限的重仓防御股(量化小号 1013 工商银行 50%, 普跌日); 刘忆青新版两天都清空原持仓(其中部分卖单理由是 regime 帽, 不是导师规则)
- **建议**: 维持动态口径上线(没有爆单, 回炉/盲审/成本无退化)。cap_pct 0.75→0.5 不建议: 下限 0 的链上限根本没用到, 改了只影响量化小号这类下限 80% 的链(0.5 → 量化小号 55%, 刘忆青 80%, ST之狼 25%)。真正要动的是两处: ①下限 0 的 tzzb 链约束块不再注入桃哥 regime 总仓帽(或改成"本导师的 regime"), 否则刘忆青/ST之狼会长期 14~26% 轻仓, 和真人 40~100% 背离 ②下限 80% 链在普跌日的凑数问题并入 §3-A 第 8 条(stance 三档: 空=下限 0)一起解决。两处都要改驱动器, 等你定
- **不自信点**: ①每格只有 1 个样本, 而 ab_fg 测过旧版自己两次的 06 单重合只有 0.34; 本次 6 对里 4 对 02 市况新旧不同(02 还没看到仓位约束, 纯随机), regime 帽又跟着市况变, 新旧差异有一部分是 02 的噪声 ②"06 后结构"假设全部成交; 买单都带开盘过滤, 卖单有冲高兑现条件单, 实际成交会少 ③导师真人是 D 日收盘结果, 链是 D 日 09:15 计划, 口径不完全对等; 只有 5 个导师-日 ④10/12 量化小号/桃哥没跑(预算), 无法看下限 80% 链在非普跌日的表现 ⑤画像/规则是 10/13 晚版本(样本内信息), 新旧同样受影响
- 沙盒与脚本: scripts/temp/ab_dyn/(base/、<日>-<old|new>/、tok/、logs/、build_sandbox.py、launch.sh、run_chain_old.py、compare.py、scorecard.md); 产物 results/<链>_chain/asof-<日>-dyn-<old|new>/——你看完可删


## 10/14 晚从 TODO §3-A 移出的已完成条目(原文)

6. **【10/13 已定·收盘后做】决策日志+延迟结算+反思回注**(借 TradingAgents memory/settlement/reflection): 10/13 核实 07_review.md 只写不读, 链不从昨天的错里学。做法=06 每单记待结算 → T+1/T+3 机械算收益与超额 → 便宜模型写 2-4 句反思 → 次日 04/06 注入同票 5 条+ 本 skill 3 条 (只注入已结算的, 防回放偷看)。约 250 行; 风险= 教训把 skill 拉离导师风格 (与拟人度冲突), 建议只许改挂价 / 仓位等执行细节, 先在对照组试
    - **【10/14 凌晨 已做, 只对对照组开, 10/14 07:50 生效】开关**: scripts/claude_profile/chain_flags.txt `CHAIN_REFLECTION=1` + `CHAIN_REFLECTION_SKILLS=control`(逗号白名单, `*`=全部, 空/缺省=无; 环境变量优先, `CHAIN_REFLECTION=0` 强关)。开启的 skill: 06 出单(含盘中子链)后每个 action 记一条到 `scripts/dfcf/paper/decisions/<skill>.jsonl`(已 gitignore; as-of 回放写沙盒 decisions/); 04/06(含盲审回炉的 06)prompt 末尾注入"同票(持仓+未成交挂单, 06 再加 04 候选)每票 ≤5 条、合计 ≤15 条 + 本链其他票 ≤3 条", 只取反思所依据收盘日 < 链运行日的(回放防偷看), 块头写明"只改执行细节, 不得改写/否定导师规则"。关闭或白名单外=驱动器逐字节不变: 假 claude 全链比对, taoge(白名单外)和 control(CHAIN_REFLECTION=0)的 9 个 prompt+16 个产物都和改前备份一致(scripts/temp/refl_1014/identity_check.py); selftest PASS(新增: 关闭不注入/白名单外不注入/只注入运行日前已结算/条数上限/护栏/决策日志); taoge/control --dry 冒烟(ab_1012/new 沙盒, 0915+1000)通过
    - **代码**: `scripts/dfcf/paper/decision_memory.py`(读写+回注+护栏, 驱动器只在开启时才加载) / `scripts/dfcf/paper/settle_decisions.py`(结算+反思+`--backfill` 从 plans 和 06 产物补历史记录+`--selftest`) / 驱动器 reflect_on·reflection_block·log_decisions 三个函数+4 处挂点
    - **结算口径(零 token)**: T+1/T+3 交易日收盘各结一次; 是否成交按账本挂单状态(同日同 slot 同票同向同量同价); 入场价=成交价, 没成交就按挂价算"假如成交"; 卖单收益取反; 超上证=方向×(个股−上证), 上证基准从决策日前一交易日收盘算起; 超对照组=买单收益−A-control nav 同窗收益。行情只读本地(行情库 kline_day.jsonl 原始价 → 次日 preClose → 日线缓存); 拿不到收盘价就等下次, 重复跑幂等。反思: 每个白名单 skill 每批 ≤12 单调一次 claude -p(scripts/lib/claude_call.py, 关工具), 只给 T+1 为止的数, 2~4 句只谈挂价/仓位/时段/止损; 正则护栏拦"规则错了/应改/可突破"一类话, 拦下的不入库也不注入; 每次运行最多 6 次调用
    - **接在哪(【待你定】, Java 没改)**: 要当天收盘价, 必须在 15:35 marketDailyHandler(写 downloads/market/<日>/kline_day.jsonl)之后跑; 15:05 的 matcher --eod 太早。建议新建 sys_job 15:50 `paperSettleHandler`(照 PaperEodHandler 写, 调 `scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/settle_decisions.py`), 或者接到 MarketPipelineService 末尾。没接之前: 晚上 check md 后手动跑一次即可(漏跑的天会自动补结)。时间线: 10/14 control 链开始记日志 → 10/15 收盘后结 T+1 并写反思 → 10/16 07:50 第一次注入
    - **样例(10/08~10/13 真实 plans+06+账本, 只读; 结果在 scripts/temp/refl_1014/sample/summary.md)**: 15 条链补出 531 单, 结了 532 个窗口(T+1 424 个, T+3 108 个, T+3 只覆盖 10/08 的单)。已成交买单 T+1 超上证均值 +1.7%(96 单, 59 单跑赢); **没成交的买单反而涨得更多**(收盘作废 +7.4%/拒单 +7.1%/被后续时段撤 +5.2%/失效撤 +4.9%), 说明保守挂价踏空的多是后来涨的票=挂价偏低是系统性执行问题; 10/08 有 27 单账本里找不到(10/11 账本重建)。control 实跑一次反思(10 单): 10 条全过护栏, 都在谈执行, 最集中的教训是"cancel_below 只比挂价低 0.03 元, 挂单形同撤单"和"成交后没设 stop_below"
    - **成本**: 反思一次调用 $0.22 / 66 秒(10 单, 输出 6k token); control 每天约 5~15 单 → 每天 $0.2~0.4; 15 条链全开约 130 单/天 → 约 11 次调用 ≈ $2.5/天。注入块约 1.5~4k 字(合 1~3k token)加到 04/06, 相对单步成本可以忽略
    - **待你定**: ①结算接 Java 哪个任务(见上) ②要不要把 control 10/12~10/13 的补账记录+已写反思放进实盘 decisions/(一条命令: `settle_decisions.py --backfill 2026-10-12:2026-10-13 --skills control`), 放了 10/14 当天就开始注入, 不放从 10/16 开始 ③其他 skill 是否先只记日志+结算不注入(现在白名单外连日志也不记; 补账能事后补, 但 06 理由/规则引用在 10/13 前的盘中时段可能对不上)
    - **不自信点**: ①样本只有 4 个交易日, 而且小盘偏强, "没成交的涨更多"可能是行情偶然; 反思会自然推向"挂高一点", 这和桃哥"厌恶追高"一类导师规则可能冲突, 护栏只拦明说改规则的话, 拦不住这种隐性冲突——所以先只开 control ②T+1 只有一天, 反思里难免把运气当教训(样例里模型自己会写"T+1 太短, 不足以判断") ③超上证基准从前一交易日收盘算, 盘中时段下的单起点不严格对齐; 跨除权日的窗口会被少算分红(兜底用的日线缓存是前复权价) ④同 slot 手动重跑时只认最后一批记录(按写入时间), 被撤的旧单不另记 ⑤"同票"在 04 步只看持仓和挂单(候选还没出来), 04 看到的多半是跨票条目

7. **【10/14 凌晨 已上线·攒样本】按步归因的等权基准**(借 evotraders baselines/analyst_tracker): 加 "04 全候选等权 T+1 卖" 衡量 05/06 增值、"02 方向板块等权" 衡量 04 选股增值; 命中率按市况×买卖分组= 打分公式冻结的原料。零 token, 基准也须走 matcher 保守成交
    - **做了什么**: 新脚本 `scripts/dfcf/paper/baselines.mjs` → `baselines.json`; report.mjs 在「按市况分组的各线收益」后加「按步归因(等权基准)」卡(每链表+全部链合计+命中率表+逐链日明细); matcher.mjs `--eod` 尾挂在 report 之前先跑 baselines(实盘日带 `--snap-today`), 不改 Java。10/12 的 0915 版 02/04/05/06 从 chain_step 只读导出到 `baselines_0915_backfill.json`(10/13 起读 slots/0915/)
    - **口径**: 持有期统一 D 日买 → D+1 收盘估值, 收益=(D收/买价)×(D+1收/D+1昨收)−1, 扣往返 0.1%(matcher 费率, 最低 5 元忽略)。**06 实际**=账本里当日 09:15 的 BUY 单(=0915 终裁)按下单金额加权, 成交按账本成交价, 没成交/撤/废/拒=现金 0; **06 选股**=06 买的票改成开盘等权买(用来拆"选股"和"挂价执行"); **04 等权**=04 contract 里 group≠遗留、有 6 位代码的候选去重等权, D 开盘买, 开盘涨停没开板=买不到(现金), 开盘涨停但开过板=按涨停价; **02 方向等权**=02 directions(含"回避"的剔除)按关键词表映射到板块 ETF(30 条, 取文本里最先出现的关键词)去重等权, 同买入规则, 映射不到的(福建本地/连板高标/并购重组/航运/纺服等 103/810 条)不计; **命中率**=按该链自己 0915 的 02 市况 × 买/卖: 06 买命中=成交后到 D+1 收盘毛收益>0, 06 卖命中=卖后到 D+1 收盘价更低, 04 候选=开盘买同口径作对照, 未成交不计。行情纯本地: downloads/market/<日>/kline_day.jsonl(不复权+昨收+涨停价) → 行情库 kline_day(只读 SELECT) → 日线归档; 每次全量重算(幂等)
    - **样例结论(10/14 跑, 84 个已结算链日=9/28-30 as-of 42 + 10/8-9 回放估算 27 + 10/12 实盘 15; 10/13 待 10/14 收盘; 只看方向)**: 全部链平均 06 实际 +0.34% / 06 选股 +2.37% / 04 等权 +2.55% / 02 方向 ETF −0.63%。①**05+06 增值 −2.20%(33/84 天跑赢), 15 条链全为负**; 拆开看 选股 −0.18%(≈0, 06 挑的票和 04 全候选差不多) + 挂价执行 −2.02%——06 挂低吸价, 涨的票没成交、跌的票才成交(06 选中的票里, 成交的那些开盘买是 −1.32%, 没成交的那些开盘买是 +5.51%), 0915 买单按金额只成交 38%。有主线日最明显(−3.43%), 普跌日 −0.53%, 退潮日 −0.14% ②**04 增值 +3.18%(65/84), 15 条链全为正**: 04 挑的个股明显强于方向板块 ETF(注意 10/8 节后普涨 04 等权 +8.4% 一天拉高均值) ③**唯一的实盘撮合日 10/12 方向相反**: 06 跑赢 04 13/15 条链、04 跑赢 02 10/15 条链——回放日(日线撮合)和实盘日结论打架, 说明回放撮合口径本身可能偏 ④命中率: 06 买 有主线 57%(67/117) / 普跌 47%(36/76) / 退潮 38%(11/29), 均略低于 04 候选开盘买(61%/53%/41%); 06 卖 有主线 77%(36/47) / 普跌 83%(15/18), 卖点比买点准
    - **待**: 攒到每链 ≥10 个实盘撮合日再看(约 10/27); 如果"挂价执行"持续为负, 再讨论 06 的低吸挂价习惯(要改 chain.md/驱动器, 由你定)
    - **不自信点**: ①样本 84 链日里 69 个是回放(日线撮合: 开盘≤挂价按开盘、盘中触价按挂价, 比实盘分钟撮合乐观或悲观都可能), 真实撮合只有 10/12 一天 15 条, 且两者结论相反 ②"04 等权开盘买"无视了 04 自己写的触发条件(很多候选本来就是"分歧≤X×0.98 低吸"), 这是你定的朴素基准, 不代表 04 的本意 ③06 实际只算 0915 那一版: 盘中子链撤掉重挂(如桃哥 10/12 #023→#027)按没成交记 0, 子链的功劳/过错没算进来 ④02 方向→ETF 是人写的关键词表(风电→新能源ETF、汽车零部件→新能源车ETF、农业→粮食ETF 都是近似), 13% 方向映射不到; ETF 是指数而 04 是个股, 波动大一截, 涨的日子 04 天然占便宜 ⑤持有期 D 开盘→D+1 收盘, 相邻两天重叠, 日均值不是独立样本; 金额加权与等权混用(06 按金额, 04/02 等权) ⑥实盘日 EOD 15:05 时行情库还没今天的价, 用快照补(腾讯/东财多源, 约百来只×0.4 秒); 快照没取到的票该链日显示"—", 次日 EOD 用行情库重算覆盖


11. **【10/13 已定·10/14 试】B站白天流水线补跑**: manual_backfill.py 加白天模式——GPU 段与 LLM 段流水线 (GPU 处理完一批即交 LLM 写 md+distill, LLM 段始终只开 1 个 claude 会话), 不考虑额度; 18:00 后不再开新 claude 会话 (让给 check md, distill 锁三 UP 共用); 规则文件全天可改还是 15:00 后再改待用户定


13. **【10/13 晚 G+F 都已上线·10/14 07:50 生效】链改造 F/G**(开关改读 scripts/claude_profile/chain_flags.txt, 回放用 env=0 强关; F 的画像目录接进 check md 每轮末尾增量更新)(已测完; 含原第 5 条"墙钟没快"=G 砍输出): F= 导师画像加目录 profile_index.md(每节标 "适用步骤"), 驱动器按步骤机械注入对应节原文 (不靠模型自己去读, 防偷懒), 目录仍给模型补读, 06 contract 加 "依据画像哪几节" 校验; G=04/05/06 去冗余 (只出 contract+ 短理由, 人看的表格由驱动器从 contract 渲染, 保留推导链 / 竞价触发器 / 不自信点)。验收=as-of 回放 3 个交易日×3 条链 (桃哥 / 刘忆青 / 一个 tzzb 导师): 旧版跑 2 次量自然波动, 新版跑 1 次, 新旧差异不超过自然波动才算质量不变; 比 02 市况 /04 候选重合 /05 批准集 /06 终裁单 / 盲审 / 回炉 / 成本, 抽 2 条给你人工看。先只测 G, 再加 F。预算约 $100~120, check md 结束后的晚上跑
    - **【10/13 晚 已做完自测, 等你拍板】开关**: G=`CHAIN_COMPACT=1`, F=`CHAIN_PROFILE_INDEX=1`(都默认关; 关闭时驱动器逐字节不变, 已用假 claude 跑原版/新版全链比对 9 个 prompt+28 个产物证明)。上线=在跑链的环境里设这两个变量, 回滚=去掉。完整数据: archive/TODO-history-20261012.md 末节「10/13~ 链改造 F/G 回放验收」
    - **G 结果(3 天×3 链, 旧版 2 次+G 1 次, 27 次回放)**: 决策重合度与旧版两次之间的自然波动持平(02 市况一致 0.94 vs 0.89 / 04 候选 0.55 vs 0.56 / 05 批准集 0.57 vs 0.61 / 06 单 0.40 vs 0.34); 盲审 9/9 pass; 04/05/06 输出 token -26%、模型手写字节 -30%、全链成本 -16%(剔除会话中断的作废调用 -14%)、claude 累计时长 -20%; 06 的"推翻/维持上游"和"竞价确认→早盘触发器"两节都在
    - **G+F 结果(桃哥 3 天+刘忆青/星见野 10/13, 5 次)**: 06 单重合度不降(0.40 vs 0.35), 但 **04 候选重合 0.46 vs 自然波动 0.63、05 批准集 0.51 vs 0.61、02 市况 1/5 翻(桃哥 10/12 判无主线退潮, 旧版两次都是有主线)**——F 让画像原文真进了上下文, 选股变了; 变了不等于变差, 重合度量不出好坏。成本 -20%、04/05/06 输出 -31%、claude 时长 -31%; 06 都填了 persona_sections(桃哥常引 S27 三态/S41 厌恶追高/S52 卖出风格); 留痕显示 F 下 tzzb 链 02~06 一次都没再读 profile.md
    - **建议**: G 可以上线(省钱省时, 质量在噪声内); F 先别上, 请先人工看下面桃哥 10/13 的 04 对比, 觉得 F 版更像桃哥再开。F 上线前还要把 gen_profile_index.py 接到 distill 之后(画像每天改, 改过的节会被自动跳过但不会补标)
    - **人工看(10/13 同一天)**: 桃哥 results/taoge_chain/asof-20261013-fg-{old1,g1,gf1}/04_plan.md 与 06_verdict.md; 刘忆青 results/liuyiqing_chain/asof-20261013-fg-{old1,g1,gf1}/04_plan.md 与 06_verdict.md
    - **不自信点**: ①自然波动本身很大(旧版两次 06 单重合只有 0.34), "不劣于噪声"这个判据灵敏度低, 只能排除大的退化 ②F 只有 5 个样本, F 对 tzzb 链几乎等于把 3KB 画像全文注入, 真正起作用的只有桃哥(天哥/卢本圆没测) ③画像/规则是 10/13 晚 distill 后的版本, 回放 10/09/10/12 有样本内信息; 模型还会读 ~/.claude 记忆里的事后笔记, 旧版新版同样受影响 ④13 次"会话没写产物"回炉全部是 20:46~20:48 同一时刻在跑的会话一起断(网关/网络瞬断, 与版本无关, old1 吃亏最多), 成本给了剔除口径; 墙钟没法比(27 链挤 15 槽排队不同), 只比 claude 累计时长 ⑤回放用的是改造后驱动器, 10/13 晚追加的两处修复(supersedes 归一、01 名称)只影响最后 2 次 tzzb G+F 回放(其中 10/13 的 01 内容与旧版逐字节相同)


16. **【10/13 已定 B·10/14 07:50 生效】单票上限+总仓下限改为按导师真实习惯动态算**(params.yaml dynamic_position; 驱动器 mentor_pos_params; 无账本链 25%/40%, 土豆维持 100%/80%, 下限 0 时纯观望仍违规; 回放观察已完成, 见下) 原:单票上限口径重审**(10/13 你问"为啥 15%, 一般 25% 一仓"): 现 15% 来自 params.yaml(10/5 建, 照桃哥 regime 仓位制的防守基准态); 实测导师真人单票仓位远高于此(最大单票仓位中位: 刘忆青 54% / 量化小号 58% / ST之狼 32% / 星见野 100%, 持仓只数中位多为 1~2 只)——15% 与拟人度目标冲突, 也是"至少要几只票凑总仓下限"逼链分散买 3~4 只的根源。候选: A=统一 25% B=按各导师真人单票仓位分布定(各 skill 不同, 与拟人度一致) C=维持 15%; 我倾向 B, 定了再连同第 3 条一起改
    - **10/14 00:3x 已修(回放发现)**: 下限为 0 的导师链被桃哥 regime 总仓上限(普跌 5%/退潮 15%)压成轻仓 → 按导师真实持仓定仓位的链不再注入 regime 上限; 普跌日为凑 80% 下限乱买(量化小号买工行 50%)并入第 8 条多空三档
    - 【已按 B 上线, 10/14 07:50 生效】回放子代理已跑完(下面是观察结果)
    - **回放观察**(10/13 晚 as-of 回放, 12 次=10/13 四条链+10/12 刘忆青/ST之狼, 每格新旧各 1 次, 花 $116; 完整表格见 archive/TODO-history-20261012.md 末节「10/13 动态仓位回放观察」): 没有爆单, 没有单票 100%(最大 50%), 没有空仓不挂条件单(12 次全都下了单), "总仓不足/超单票上限"回炉 0 次, 盲审 12/12 pass, 成本与时长和旧口径持平。**有下限的链**仓位变得少而集中: 桃哥买 3 只→1 只 25%; 量化小号单票 12%→50%, 总仓 41%→84%, 更接近真人(2 只 100%)。**下限为 0 的链(刘忆青/ST之狼)**95%/45% 的单票上限一次都没用到, 反而清掉原持仓、退到 14~26% 轻仓(旧口径 41~61%), 离真人(刘忆青 40%/100% 单吊)更远。原因: 下限一去掉, 约束块里注入的桃哥 regime 总仓帽(普跌 5%/退潮 15%)就成了实际约束, 刘忆青 06 卖单理由直接写"承重=regime 帽, 非人格规则"
    - **异常**: 量化小号 10/13 判普跌, 为凑 80% 下限买了工商银行 50%(06 自己标注"是下限逼出来的, 请用户裁定普跌日下限"; 旧口径也用银行/银行ETF 凑数, 只是更分散)
    - **建议**: 维持上线; cap_pct 先不改(0.75→0.5 只影响量化小号这类有下限的链, 下限 0 的链上限本来就没用到)。待你定的两处(都要改驱动器): ①下限 0 的 tzzb 链不再注入桃哥 regime 总仓帽 ②下限 80% 的链普跌日凑数问题, 并入第 8 条(stance 分档, 空=下限 0)
    - **不自信点**: 每格只有 1 个样本(旧版自己两次 06 单重合也只有 0.34); 6 对里 4 对 02 市况新旧不同(随机), regime 帽跟着变, 差异有一部分是噪声; "06 后结构"假设全成交; 导师-日样本只有 5 个, 而且真人是收盘结果, 链是 09:15 计划; 10/12 量化小号/桃哥因预算没跑

