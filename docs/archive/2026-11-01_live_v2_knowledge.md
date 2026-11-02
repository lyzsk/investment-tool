# 2026-11-01 live v2 / 知识底座实施记录

## replay_viewer

- 唯一入口：`docs/private/replay_viewer.html`。
- `scripts/knowledge/replay_viewer.py` 已改为调用原 `scripts/paper_line/viewer.py` 并继承 `viewer_tpl.html`，不再使用简化自绘布局。
- 保留原 dark mode、左侧账本导航、chartSVG、BS 颜色及明细；增加日期选择器和公共情境卡。
- 2026-10-29、2026-10-30 两天已嵌入同一 HTML，可实际切换；10/30 含 4 本账、118 版、8 只分时、13 条导师逐笔、15 个公共情境。
- 已替换原模板 `/*__DATA__*/` 并解析断言初始账本数据；两天 DATA、原导航/chartSVG/日期选择器/公共情境均通过检查，全部 JS 经 `node --check` 通过。旧日期 HTML 移至 `docs/archive/replay_viewer/`，`docs/private/` 只留统一入口。

## 原 signal 内新增竞价信号

- 原 S6 竞价抢筹保留；新增 S16 竞价抢跑、S17 竞价低吸、S18 竞价高抛，全部在 `signals.py::_auction` 内共享 09:20 基准、原事件流、signals.jsonl、节流、期望闸和推送总线。
- 动态阈值在 `signal_params.py`：09:20 后抬高/压低幅度按本票历史 P90；不足 8 次用全池 P90；低吸/高抛开幅门槛 = max(0.5%, 0.15 × 本票 30 日振幅中位)。缓存 schema 升为 2，旧缓存自动重算。
- 真实回放发现旧 S6 的“当前未匹配金额”会漏掉撮合消化后的抢筹，因此金额证据改为 max(当前同侧未匹配金额, 五分钟匹配成交额折算)，仍须过本票近 20 日流动性地板，未匹配方向条件保留。
- 构造自测含原套件和新增信号正反例，全部通过；另验证匹配额能补未匹配额、两者都不足时不触发。
- 2026-10-30 09:25 前全池 295 只回放：S6 17 / S16 44 / S17 15 / S18 12。名单内：新华百货、百洋股份 S6+S17；海洋王 S16。S18 有全池真实样本，所选名单内无样本。
- `signal_odds.py` 对 S16/S18 按之后下跌触及率评价，不错用买入上涨盈利率。已重放并合并 2026-10-19～10-27、10-29 共 8 天：S16 stock n=106（次日 -3% 触及 72.6%）、S17 stock n=17（次日 +3% 触及 64.7%，收盘均值 +2.47%）、S17 cb n=10（当日 +1% 触及 90%，但收盘均值 -2.71%）、S18 stock n=41（次日 -3% 触及 75.6%）。仍需与同日同池基准比较，不能只看触及率。

## live v2 真实事件包

- `scripts/live/v2/signal_pack.py` 新增 `event_pack(store, event, day)`，直接消费原 signals.py 事件，保留 stance/action/evidence/context/belief_state/forecast/confidence/invalid_if/next_check。
- 不自动新增模型仓位；持仓处置仍只按原计划单和机械风控。
- 时间语义未放松：2026-10-30 09:24 的事件不能读取当天 15:00 才可见的情境，测试确认会显式失败；2026-11-02 可使用 10/30 收盘情境。
- `scripts/test/knowledge_foundation_test.py` 4 项全部通过，含真实事件包、卖方信号、样本置信和防未来函数。
- `scripts/live/v2/driver.py` 新增 `start_worker` 并接回原 `signals.py`：只处理过原名单/节流/统计期望闸且非 stale 的事件；单队列、同票 180 秒模型冷却、单会话顺序复核。`LIVE_V2_MODEL=1` 且非 dry 才启动，默认 0，不改变现有机械线。
- `scripts/live/v2/session.py` 每天首轮 `--session-id`、后续只 `--resume`，禁用文件/网络/交易工具，校验返回 sid 和 JSON schema；结果只写 candidate/待核案例，不直接升规则或下单。
- `scripts/test/live_v2_driver_test.py` 4 项通过：dry 不调用、回写待核案例、首轮后仅 resume、后台 worker 消费真实事件形状；另测防未来函数。真实 `driver.py` dry-run 已通过，未执行模型。

## 受控情境维度与认识论硬闸（11/1 用户令）

- `scripts/knowledge/dimensions.json` 是受控维度表：周期阶段、题材、字辈、位置、竞价表现、票型；`dimensions.py` 只从 mood/涨停题材、topology、watch_seed、auction_live_open 机械生成。模型自由文本只保留为 prior note，不能进正式维度。
- 字辈按标的真实成员关系过滤：新华百货仅 bai，不再同时挂 yang/jiu。10/30 新华百货维度实测为 `分歧 / 一般零售 / bai=高潮 / 非板 / 竞价低吸 / 普通`。
- `epistemics.py` 定义 verified/candidate/prior。verified 必须有机械来源、n>0、0..1 hit_rate、as_of 和证据；模型蒸馏只能 candidate/prior，active 规则必须已核销。
- `context_pack.py` 对 chain04/chain06/live/signal/order 开启 verified-only 硬闸；distill/viewer 可展示候选但保留标记。旧无标记案例自动迁为 candidate，不伪造命中率。
- `ForecastAdapter` 从 forecast_ledger 的真实 evaluated_at/hit 生成已核销案例；正式库已迁 393 条。chain04 小包里候选被过滤，只剩机械已核销正负例。
- forecast 汇总增加 issued_at/evaluated_at 双时间闸；10/30 viewer 不再偷看 10/31 才核销的结果。
- `distill_contract.json` 和 harness 已升 1.1。知识 5 项、live v2 4 项测试通过；build_distill_pack 实际产物包含 dimensions 与 epistemic；viewer 两日版已重建并验证。

## live v2 主交互真调与血缘（11/1）

- `replay_main.py` 使用 10/30 真实 S17 新华百货、S16 海洋王做收盘后主交互回放，明确标 `post_close_replay_not_live_order`，不伪装成 11/1 盘中信号。
- 两轮真调均成功且共用 sid `fea08d8d-cce7-40f6-bd0f-c7ebcfb42b32`；成本分别 $0.084565、$0.073507，合计 $0.158072。第二轮 cache_read 12,544 tokens，证明 resume 路径真实生效。
- 输出都有 stance/action/evidence/confidence/invalid_if/next_check；没有自动订单。结果分别写 candidate 案例 `live_v2:a0460605314bbf7c`、`live_v2:4b22bc273b5335b6`。
- 缺当时情境统一返回 `pending_context`，只登记待核销，不调用模型、不写假 context/case。
- 新增 `lineage.py` 和复合主键 upsert，规则链为 source→context/dimensions→case/epistemic→knowledge_link→rule version→consumer→outcome；真实规则表当前仍为 0，不把案例数冒充规则数。
- 首次真调发现 evidence 字段导致链接漏写，已修复并补 74 条证据/成员链接；两条决策现有 5、4 条直接证据链接，测试防止复发。
- 模型指出 forecast 重复时间戳问题后，chain04/live 证据改为同票/预测日/票型/方向机械聚合，forecast 总体统计也按独立预测组去重；每组保留全部 member_ids 血缘但只算 `n=1` 次独立核销，命中率取最新核销，避免伪重复扩样。

- 同日同池基准初算暴露 `kline_day` 后六位碰撞：`sh000010` 指数曾覆盖 `sz000010` 股票。`signal_odds.day_hi` 与 MarketAdapter 已改为交易所前缀+代码校验，指数行情也改按完整 symbol 读取；新增真实数据断言后重算 8 天结果，不用剔除异常均值掩盖源头问题。

- 修正后同日同池基准：股票 n=877、转债 n=83。S6 股票/转债 +1% 触及率分别高基准 12.78/36.23 点；S17 分别高 14.95/33.37 点。S16/S18 股票 -1% 触及率只高基准 7.31/9.66 点，说明大部分高触及率来自弱市背景。S17 转债当日 +1% 触及 90%，但收盘均值 -2.71%，比基准还低 0.54 点，不能把盘中摸高当持有收益。

## 不自信点

- 竞价参数历史只有 15 个 `auction_live_open.json` 交易日；部分股票/转债缺日均成交额时金额地板为 0，名单外噪声需靠后续统计与池闸控制。
- S17 与 S6、S18 与 S16 可在同一竞价段先后出现，语义分别是“过程抢单”和“定稿附近仍低/高开”，不是重复去重；后续要看用户是否觉得推送重复。
- 新竞价统计只有 8 个交易日，且市场环境集中；在完成同日同池基准前，不把高触及率外推为稳定 alpha。
- 真实主交互只做两轮收盘回放；生产 `LIVE_V2_MODEL` 仍默认 0，不能把验收成功说成已无人值守上线。
