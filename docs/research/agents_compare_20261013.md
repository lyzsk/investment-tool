# 多智能体交易框架对照：evotraders / TradingAgents vs investment-tool（2026-10-13）

> 只读源码，未安装依赖、未运行任何代码。TA=TradingAgents（`C:\Users\admin\dev\_ref\TradingAgents`，v0.6.0 commit 1394a3f），EVO=evotraders（`C:\Users\admin\dev\agentscope-samples-main\evotraders`）。两个仓库里都没发现针对 agent 的指令性文本（已 grep 过）。

## 一、定位与架构

**TA**：在 LangGraph 上模拟一家投研公司，输入单票+日期，输出 5 档评级。它不撮合，`backtest.py` 里明写了"不做组合模拟器"。
- 流程：4 个分析师并行（每人有私有工具子图，`max_tool_rounds` 用满后强制收尾）。与此同时 Memory Log 节点结算旧决策。之后是 Bull/Bear 交替辩论：共用一份 history，每人都读对方上一轮。Research Manager（deep 档模型）出结构化 `ResearchPlan`。Trader 出 `TraderProposal`（入场价/止损价必须锚在技术报告上）。接着是激进/保守/中立三方风控辩论，最后 PM（deep 档）出 `PortfolioDecision`。
- 记忆：`memory/log.py` 是追加式 md 决策日志，每笔先记成 pending。持有 5 日后，`settlement.py` 算 raw 收益和相对区域基准的 alpha，再由 `reflection.py` 写一段 2-4 句的教训。下次运行时把同票 5 条、跨票 3 条注入 PM，并按 `as_of` 过滤，挡住前视偏差。
- 评估：`backtest.py` 在 ticker×date 网格上跑，按评级统计方向命中率和平均 alpha。
- 测试：86 个测试文件，含脚本化假 LLM 的端到端测试。

**EVO**：基于 AgentScope ReActAgent，一个团队管一个组合，主打"带记忆的自我进化"，有实时 UI。
- 角色：4 个分析师（基本面/技术/情绪/估值，配置在 `personas.yaml`）+ 风控 + PM，全员在一个 MsgHub 里广播。
- 流程（`core/pipeline.py`）：清空短期记忆 → 分析师 → 风控 → N 轮会议（PM 定议程、分析师轮流发言、PM 总结）→ 分析师给出 UP/DOWN 预测 → PM 调 `make_decision` 工具，逐票给 long/short/hold+数量 → 按开盘价成交（`utils/trade_executor.py`，可以做空）→ 收盘结算。
- 记忆：ReMe 长期记忆（`main.py`），把当天完整轨迹+结局存进向量库，打分只看当天 PnL 是否大于 0（1/0），次日检索后注入。
- 评估：`utils/baselines.py` 有等权、市值加权、月调仓动量三条基准；`analyst_tracker.py` 给分析师胜率排行（多/空分开统计）。
- UI：`state_sync.py` 推事件 → `services/gateway.py` 的 websocket → React 前端。
- 测试：3 个文件，以 MagicMock 构造测试为主。

## 二、逐项对照

| 环节 | 我们 | TA | EVO | 差距 |
|---|---|---|---|---|
| 01 事实 | 机械 facts → LLM 摘要，14 链共用 | 4 个分析师各调工具，按发布日期做点时过滤 | 分析师 ReAct 调工具 | 我们更省（共用一次） |
| 02 市况 | 三态+方向清单 | 无 | 无 | 两家都没有市况层 |
| 03 辩论 | 多/空独立会话，互相看不见，裁判裁决 | 交替轮次，能直接反驳对方 | 多轮会议广播 | 我们缺"反驳"轮 |
| 04 方案 | 遗留组+方向推导组 | Trader 单票方案 | PM 统一出 | 我们更细 |
| 05 风控 | 单会话逐票批准/否决+机械闸 | 三方风控辩论 | 单个风控 agent | 我们有机械硬闸，更硬 |
| 06+盲审 | contract+价格锚/仓位/规则引用校验+盲审 | Pydantic 结构化输出，失败退回自由文本 | 工具调用 | 两家都没有盲审 |
| 07 复盘 | 写出 07_review，**不回注次日链** | 反思自动回注 PM | 轨迹进向量库 | **最大短板** |
| 撮合 | 保守成交，T+1，涨跌停/锚偏离闸 | 无 | 开盘价成交，可做空 | 我们最真实 |
| 评估 | 对照组/上证/导师真人 | 按评级算命中率+alpha | 等权/市值/动量基准+分析师胜率 | 缺"候选池等权"基准，无法按步归因 |
| 成本 | 所有步同一默认模型；06 已花 $135、04 已花 $102 | quick/deep 两档模型 | 按 agent 配模型 | 我们没分档 |
| 测试 | 驱动器里一个 `selftest()` | 86 个文件，回归用例对应 issue 编号 | 3 个 | 差距大 |

## 三、值得借鉴（按价值排序）

1. **决策日志+延迟结算+反思回注**（TA `memory/log.py`/`settlement.py`/`reflection.py`）
   - 怎么做：06 每个 action 落一条 pending；T+1 和 T+3 两个窗口机械算 raw 收益，以及相对对照组/上证的 alpha；用便宜模型写 2-4 句反思，反思 prompt 要写明"窗口短不足以否定论点"；次日 04/06 注入"同票 5 条+本 skill 跨票 3 条"，并按 `resolved≤当日` 过滤（我们的 3 天回放必须这样做）。
   - 落点：新建 `scripts/dfcf/paper/memory_log.mjs`；`run_taoge_chain.py` 在 06 后写入、在 01 前结算；chain.md 04/06 模板加 `{past_context}`。
   - 改动量：约 250 行。
   - 风险：教训会把 skill 往偏离导师风格的方向拉，和"拟人度"目标冲突，所以只允许改执行细节（挂价/仓位），不允许改规则；小样本也容易过拟合。

2. **按步归因的等权基准+分组命中率**（EVO `baselines.py`、`analyst_tracker.py`；TA `summarize`）
   - 怎么做：加两条基准。一是"04 全部候选等权、T+1 卖出"，用来衡量 05/06 有没有增值；二是"02 方向板块等权"，用来衡量 04 选股有没有增值。命中率按市况三态×买/卖分组统计。这也正好是冻结打分公式的原料。
   - 落点：`scorecard.mjs`/`report.mjs`，新建 `baselines.mjs`。
   - 改动量：约 150 行，零 token。
   - 风险：基准也必须走 matcher 的保守规则（顶一字买不到），否则基准会虚高；没有代码的候选算不进去。

3. **模型分档+限长**（TA `default_config.py` 的 quick/deep 两档；Reflector prompt 里"every word must earn its place"）
   - 怎么做：03b/03s/05/盲审/反思用便宜档，03j/06 用强档；04/06 正文限 800 字，以 contract 为主。
   - 落点：驱动器加 `STEP_MODEL` 映射，`CLAUDE` 命令加 `--model`；chain.md 加限长条款。
   - 改动量：约 30 行。
   - 风险：便宜档 contract 失败率可能上升，回炉反而更贵；先跑一周 A/B 看回炉率。

4. **单测体系**（TA `tests/`）
   - 怎么做：v01~vblind、`resolve_px`、`limit_of`、matcher 五哨兵逐个做成 pytest/node:test。每个历史事故写一条回归用例，文件头注明出处（大亚 14.00、襄阳 A4、9/29 死链），这是照 TA "docstring 写 issue 号"的做法。再仿 `test_graph_end_to_end.py` 用假 claude（返回固定产物）跑 01→06，把连线钉住。另可借鉴 `test_layering.py`，用 AST 检查分层（例如只有 snapshot 层能访问行情源）。
   - 落点：新建 `scripts/chain/tests/`。
   - 改动量：约 300 行测试，不动业务代码。
   - 风险：低。

5. **辩论加条件反驳轮**（TA 的交替辩论，及 `test_debate_opening.py`："首位发言者不得反驳不存在的论点"）
   - 怎么做：只在 03j 判"证据平衡"时，多/空各读对方陈词反驳一轮，再交裁判。
   - 落点：chain.md 加 03 步契约，驱动器 steps 映射。
   - 改动量：约 60 行。
   - 风险：每次触发 +2 次调用×14 链，需要限频。

6. **组合与仓位**
   - 两家都没有"按市况选导师"的组合层，没有现成方案可抄。EVO 分析师排行榜的形态可以直接套用：14 个 skill 对应它的分析师，按市况分组胜率 → 权重。`report.mjs` 已有 `regimeStats`，在它上面扩展即可。
   - TA `portfolio.py` 把"有仓/空仓/未提供"三态严格分开，值得照抄进 `paper_state`，防止模型把"未提供"当成"空仓"。
   - 我们驱动器的 `pos_constraints` 硬约束已经强于两家。

7. **流式输出与 UI**（EVO `state_sync.py` 的事件流；TA `report_html.py` 单页报告）
   - 怎么做：驱动器每步落盘时追加 `run_dir/events.jsonl`；把 01~07 合成一页带目录的 html，手机上能看。
   - 改动量：约 100 行。
   - 价值：中低，排在最后。

## 四、不建议借鉴

- EVO 的开盘价成交、做空和保证金：A 股是 T+1，有涨跌停，不能裸卖空。我们的保守撮合更真实。
- EVO 的 ReMe 整轨迹记忆：一天全账户的盈亏用 1/0 一刀切地打分，归因太粗；T+1 下当日 PnL 噪声大；还要外部 embedding 和记忆模型，14 链×多步轨迹的成本高。
- EVO 的多轮会议广播：违反我们 9/28"禁多 agent 互聊和稀泥"的立法，token 也随轮数线性膨胀。
- TA 三方风控辩论全量引入：每链 +3 次调用×14 链，05 现在已花 $60；我们的机械闸更可靠。
- TA 的 5 档评级、5 日持有、单票一张图：它面向单票中线，我们是全市场短线选股；alpha 窗口应改成 T+1/T+3。
- 两家都用美股数据源，没有竞价、涨跌停、板块轮动这些概念，数据层不能复用。

## 五、不确定的地方

1. 没运行过任何代码，以上行为都是读源码得出的；ReMe 的检索/压缩逻辑在 agentscope 包里，没读到。
2. TA 的记忆回注有没有带来收益增益，仓库里没有数据（论文早于 memory log 版本）。
3. 本机 `claude -p` 是否支持按步切 `--model`，以及能否用 `--max-turns` 限制 grep 轮数（对应 TA 的 `max_tool_rounds`），需要实测。
4. 反思回注对"拟人度"可能是净负作用，最好先只在对照组 A-control 上做消融实验。
5. 我判断"07 没有回注次日链"，依据是驱动器里搜不到读取 07_review 的代码；如果有别的路径（例如 state_digest）带进了教训，需要再核实。
