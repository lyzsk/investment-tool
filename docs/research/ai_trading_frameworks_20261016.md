# 公开的 AI/LLM 交易系统怎么论证，和我们的 01→07 比如何（2026-10-16）

> 范围：只做调研，没有改任何代码。材料包括 arXiv 摘要和部分全文（CLQT、AI-Trader、AMA、Look-Ahead-Bench、InvestLogicBench、TradingAgents 用 curl 拉下全文 grep 过）、ai-hedge-fund v2 源码（README/VISION/signals）、新闻二手源。
> 已在 `agents_compare_20261013.md` 里拆过 TradingAgents 和 evotraders 的源码细节，本文不重复，只引用其结论。
> 我们自己的数字来自 `scripts/dfcf/paper/token_log.csv` 和 `results/*_chain/live-202610xx/` 的 contract，口径是 10/12~10/16 共 5 天、16 条链。成本是 `claude -p` 的账面 total_cost_usd，不是实付（实付要乘 gravitex 系数）。

## 〇、先说结论（6 条）

1. **在真钱或严格样本外的条件下，"LLM 直接当交易决策者"至今没有一个稳定跑赢指数的公开证据。** 真钱赛 Alpha Arena 第一季 6 个模型里 4 个亏损，最差 −62.7%。几个干净的前向/实盘基准也是同样结论：StockBench 里多数模型跑不赢买入持有，AI-Trader 里 A 股没有一个 agent 跑赢上证 50，CLQT 扣成本后跑不赢指数。论文回测里的高收益，大多在控制知识截止泄漏后就消失了（Profit Mirage、FINSABER、Look-Ahead-Bench）。
2. **真钱机构的做法是"LLM 做研究，确定性系统和人做交易"。** Man Group AlphaGPT 的流程是：LLM 提假设、写代码、回测，然后过人工委员会，几十个信号已上实盘。Numerai 是几千个模型按质押加权成 meta model。两家都没有让 LLM 每天直接拍板下单。
3. **辩论这个环节的证据最弱。** NeurIPS 2025 的 Debate or Vote 发现，多 agent 辩论的增益大部分来自多数投票，辩论本身是鞅（期望正确率不变）。交易场景的 210 组受控实验里，推理质量和 Sharpe 的相关系数 r=0.07，主要失败模式是谄媚趋同；只有"保留分歧"的干预能提高 Sharpe。我们 03 裁判 70 次里 68 次判"多"（97%），几乎不携带信息。
4. **"模仿某位投资者"的公开做法都只是 prompt 里写人设，没人量化证明"像"。** 少数几篇真正做了度量的结论都偏负面：MILA 里 LLM 预测"某人明天交不交易"打不过"照他最近活跃度"的延续基线；InvestLogicBench（151 位真实投资者、20 万条决策）里推理看起来合理（约 4/5 分），但事实锚定只有 0.8–2.8/5。另一边，Mimicking Finance 用简单机器学习模型就能从基金经理的历史行为预测 71% 的交易方向。
5. **"说的"和"做的"对不上是系统性的。** CLQT 测到 agent 的仓位系统性不跟随自己的分析结论，两条赛道的偏差分别是 +0.30 和 +0.23。它的消融还显示，单独去掉任何一个模块，Sharpe 的变化都落在重复运行的噪声带里，同一配置重复跑 Sharpe 可以差到 2.3；风险纪律来自硬约束层，扣成本前后差别也主要由成本模型决定。
6. **对我们最直接的启示**：①03 辩论是"最可能白花钱"的一步（约占成本 12%）；②拟人度应该用"分层行为指标 + 延续基线"来量，并且把导师的仓位、换手、持股数这些行为统计从账本里机械算出来当硬约束，不要交给 LLM 推断；③14 个 skill 的权重在样本少于几十个交易日时，应该等权或强收缩，并且奖励"独有贡献"而不是裸收益。

---

## 一、证据分级总表

证据级别：**A**=真钱实盘；**B**=前向纸面实盘，或训练截止之后的严格样本外；**C**=论文回测（窗口可能落在模型训练期内，或窗口很短）；**D**=只有 demo 或框架，没有公开业绩。

| 系统/研究 | 级别 | 决策流程（谁论证谁） | 关键结果 | 出处 |
|---|---|---|---|---|
| Alpha Arena S1（nof1，2025-10-17~11-03，每个模型 1 万美元真钱，Hyperliquid 永续） | A（样本极小） | 单模型、同一 prompt、同一数据，没有多 agent | Qwen3-Max +22.3%，DeepSeek +4.9%，Claude −30.8%，Grok −45.3%，Gemini −56.7%，GPT-5 −62.7%；创始人原话："LLM 处理数值时间序列不好，但我们给的上下文全是这个"；各模型在多轮 prompt 迭代后仍保持固定的"性格"偏差 | [iweaver](https://www.iweaver.ai/blog/alpha-arena-ai-trading-season-1-results/)、[Forklog](https://forklog.com/en/four-out-of-six-ai-models-suffer-losses-in-trading-tournament/)、[SCMP](https://www.scmp.com/tech/tech-trends/article/3331425/alibabas-ai-model-outperforms-us-rivals-crypto-trading-showdown) |
| Alpha Arena S1.5（美股，2 周，四种模式：New Baseline/Monk Mode 保本/Situational Awareness 看对手排名/Max Leverage） | A（样本极小） | 同上，另把 prompt 模式作为变量 | Grok 4.20 平均 +12%，四种模式都赚钱；二手源称多数模型亏损，Qwen 下单 1418 笔、Grok 158 笔（过度交易） | [Forklog](https://forklog.com/en/ai-model-grok-4-2-triumphs-in-trading-tournament/)、[BigGo(二手)](https://finance.biggo.com/news/5BSX_Z0BaoGGrU-ID27J) |
| Numerai（不是 LLM） | A | 几千个外部模型 → 按质押 NMR 加权成 meta model → 基金交易；对模型的奖励看相关性，也看对 meta model 的独有贡献（MMC） | 2024 年净 +25.45%、Sharpe 2.75；2023 年 −17%；2025 年截至 10 月净 +8%；2025-08 摩根大通承诺 5 亿美元 | [Hedgeweek](https://www.hedgeweek.com/quant-hedge-fund-numerai-secures-500m-jpmorgan-allocation/)、[FinTech Global](https://fintech.global/2025/11/24/numerai-lands-30m-to-scale-ai-powered-hedge-fund/) |
| Man Group AlphaGPT | A（已部署，未披露业绩） | Idea Person 提假设 → Code Writer 写代码 → Backtester 回测 → 人工投委会，门槛和人写的信号相同 | 几十个信号已批准上实盘；明确承认"测得越多，伪信号越多" | [Hedgeweek](https://hedgeweek.com/news/man-group-deploys-agentic-ai-for-quant-signal-discovery)、[AI Street](https://www.ai-street.co/p/inside-man-group-s-alphagpt) |
| AI-Trader（港大 HKUDS，2025-10-01~11-07 前向，含 A 股日频） | B（5 周） | 单 agent、"最少信息"范式，agent 自己搜索和验证资讯 | 美股有 3 个模型跑赢 QQQ；**A 股没有一个 agent 跑赢上证 50（+1.65%）**；作者结论：风控能力决定跨市场稳健性，政策市更难拿超额 | [arXiv 2512.10971](https://arxiv.org/abs/2512.10971) |
| Agent Market Arena（2025-08~09 前向） | B（2 个月，4 个标的） | 4 种 agent 框架 × 5 个底座模型 | **行为差异主要由框架决定，底座模型的影响更小**；ai-hedge-fund 型的 HedgeFundAgent 在 GPT-4o/4.1/Gemini 三个底座上结果逐位相同（TSLA 都是 −29.15%） | [arXiv 2510.11695](https://arxiv.org/abs/2510.11695) |
| LiveTradeBench（50 天前向，21 个模型） | B | 单 agent 输出组合权重 | LMArena 分数高不代表交易好；各模型有固定的组合风格 | [arXiv 2511.03628](https://arxiv.org/abs/2511.03628) |
| StockBench（无污染，多个月） | B | 单 agent，每日买/卖/持有 | 多数模型跑不赢买入持有 | [arXiv 2510.02209](https://arxiv.org/abs/2510.02209) |
| CLQT（2026，一年期去污染回测 + 4 周券商纸面实盘，13 组消融） | B | 6-agent 投委会（IA→MSS→MAPC→COE→ALE）与单个自主 agent 对照 | 扣成本后跑赢防御基准、跑不赢指数；6 个模块单独去掉后 ΔSharpe 都在 ±0.42 的噪声带内；"说一套做一套"偏差 +0.30（回测）/+0.23（实盘）；投委会结构不是普遍更好（实盘 6 对全部是自主模式占优）；只有成本模块对 PnL 有干净的影响 | [arXiv 2606.29771](https://arxiv.org/abs/2606.29771) |
| FINSABER（2004–2024，100+ 只股票，含退市股） | B（长样本外） | 检验 FinMem、FinAgent | 两者都没有显著 alpha（p>0.34）；牛市过度保守、熊市过度激进（FinMem 回撤 −75%，基准 −50%）；作者建议做趋势/市况识别和风控，不要继续堆复杂度；FinAgent 回测花了 198 美元 | [arXiv 2505.07078](https://arxiv.org/abs/2505.07078) |
| Profit Mirage / FinLake-Bench | B（专测泄漏） | — | 回测收益在模型知识截止之后"蒸发"；对输入做扰动后预测基本不变，说明是记忆不是推理 | [arXiv 2510.07920](https://arxiv.org/abs/2510.07920) |
| Look-Ahead-Bench（用 ai-hedge-fund 当测试平台） | B | 分析师 + 投资大师 agent → 风控 → PM | 普通模型从训练窗口内到窗口外，alpha 衰减 15~22pp；作者是 PiT 模型厂商，有利益相关 | [arXiv 2601.13770](https://arxiv.org/abs/2601.13770) |
| TradingAgents（Tauric） | C | 分析师 → 多空辩论 → 交易员 → 三方风控 → PM（详见 10/13 文档） | 只测了 2024-01~03 三个月、5 只科技大盘股；**没有任何消融，无法说明辩论是否有用** | [arXiv 2412.20138](https://arxiv.org/abs/2412.20138) |
| Trading-R1（Tauric） | C | 用 SFT+RL 把"写投资论点→按波动调整后决策"训进模型 | 6 只股票/ETF 上风险调整收益更好 | [arXiv 2509.11420](https://arxiv.org/abs/2509.11420) |
| FinMem / FinAgent / FinCon | C（前两个已被 FINSABER 证伪） | FinMem：人设+分层记忆；FinAgent：多模态+双层反思；FinCon：经理-分析师层级，按 CVaR 触发自我批判，再把"信念"定向下发给相关节点 | 论文内回测都很漂亮 | [2311.13743](https://arxiv.org/abs/2311.13743)、[2402.18485](https://arxiv.org/abs/2402.18485)、[2407.06567](https://arxiv.org/abs/2407.06567) |
| GuruAgents（5 位投资大师 persona） | C（疑似泄漏） | prompt 人设 + 工具 + 确定性推理管线 | 巴菲特 agent 在 NASDAQ-100 上 2023Q4~2025Q2 年化 42.2%，窗口落在主流模型训练期内 | [arXiv 2510.01664](https://arxiv.org/abs/2510.01664) |
| ai-hedge-fund v2（virattt，约 6 万星） | D | persona 只是一段 system prompt，输出 JSON（信号/置信度/2~4 句论点）→ 策略分配器按权重混合 → 确定性风控 → 哈希链账本 | README 明写"只供教育，不做真实交易"，没有公开业绩；值得借鉴的是工程：回测用 **blind prompt**（隐藏代码、行业、日期、金额），回测和纸面盘走同一套代码 | [repo](https://github.com/virattt/ai-hedge-fund)、[buffett.py](https://github.com/virattt/ai-hedge-fund/blob/main/hedge_fund/signals/buffett.py) |
| RD-Agent(Q)（微软）/ AlphaAgent | C（A 股 CSI300/500 回测） | LLM 提假设 → 写因子/模型代码 → 回测反馈 → bandit 选方向；AlphaAgent 另加原创性（AST 相似度）和复杂度正则 | 比经典因子库年化高到 2 倍；AlphaAgent 抗衰减 | [2505.15155](https://arxiv.org/abs/2505.15155)、[2502.16789](https://arxiv.org/abs/2502.16789) |

**读表要点**：A 级证据要么样本极小（Alpha Arena 两三周），要么不是让 LLM 每天拍板（Numerai、Man）；B 级证据几乎一致指向"跑不赢指数或买入持有"；正面结论集中在 C 级。

---

## 二、它们的"论证"流程拆成四种范式

| 范式 | 代表 | 出观点 | 挑战 | 拍板 | 防幻觉 | 防前视 | 评估 | 证据 |
|---|---|---|---|---|---|---|---|---|
| ①公司制多角色 | TradingAgents、FinCon、DeepFund、CLQT 投委会 | 多个分析师 | 多空辩论、风控辩论 | PM | 结构化输出、事实锚 | 按发布时间过滤（TA） | 收益、Sharpe、命中率 | C~B；CLQT 显示投委会不是普遍更好 |
| ②单 agent + 记忆/反思 | FinMem、FinAgent、Alpha Arena、AI-Trader | 单模型 | 自我反思 | 单模型 | 工具只能读实时数据 | 前向实盘 | 收益排行 | B 级普遍跑输基准 |
| ③LLM 做研究，系统做交易 | Man AlphaGPT、RD-Agent(Q)、AlphaAgent | LLM 提假设 | **样本外回测和统计门槛** + 人工投委会 | 规则/人 | 代码审查、单测、相同门槛 | 样本外切分；承认多重检验 | 和人写信号用同一套阈值 | **唯一有真钱部署的 LLM 范式** |
| ④LLM 出意图，机械层出价格和仓位 | ai-hedge-fund v2、FCLAgent、CLQT 约束层 | persona 给信号和置信度 | — | 分配器 + 确定性风控 | JSON schema、只许用给定数据 | blind prompt、时点快照 | 哈希账本 | D~B；CLQT 显示风险纪律来自这一层 |

我们的链属于 ①+④ 混合：01~05 是公司制，06 contract 加驱动器机械闸，再加 matcher 保守撮合。外部证据里真正"有效"的部分集中在 ④（约束层）和 ③（统计门槛），① 的多角色论证本身没有被证明能带来收益。

---

## 三、"模仿特定交易员/大师"：做法、效果、怎么量"像不像"

| 研究/项目 | 怎么模仿 | 怎么量"像" | 结果 |
|---|---|---|---|
| ai-hedge-fund v2 | 只有 system prompt（巴菲特清单 6 条 + 输出 schema） | **不量** | 没有业绩；作者在 VISION.md 声明"不是本人" |
| GuruAgents | prompt + 确定性管线 | 只看"行为不同"，不和真人持仓比 | 收益高但疑似泄漏 |
| Agent Market Arena | 测试了 ai-hedge-fund 型 HedgeFundAgent | — | 3 个底座结果逐位相同。我推断它的决策由确定性代码主导，persona 文本对动作几乎没有影响（未读 v1 源码核实） |
| InvestLogicBench（151 位真实投资者，多为 YouTube 频道博主，20 万条决策；和我们的 B 站 UP 主场景同构） | 先给画像 P，再给事件 E，让模型生成推理 R 和决策 D，最后对照结局 O | 过程分（逻辑、事实锚定、画像一致）和收益分开评 | 逻辑合理性约 4/5，**事件锚定只有 0.8–2.8/5**；收益分和过程分不一致（[2608.06108](https://arxiv.org/abs/2608.06108)） |
| MILA（80 人纸面交易，滚动预测次日） | 给 LLM 用户历史和市场信息 | **分层**：交不交易 → 买卖方向 → 哪只票 → 数量 → 组合轨迹 | **在"交不交易"这一层，没有一个 LLM 稳定打赢"最近活跃度延续"基线**；越往细越差（[2609.15727](https://arxiv.org/abs/2609.15727)） |
| Mimicking Finance（Cohen 等，2025-11） | 简单机器学习模型拟合基金经理的历史行为 | 能预测的部分 / 新颖反应的部分 | **71% 的交易方向可以从过去行为预测**，部分经理接近 100%（[PDF](https://www.rotman.utoronto.ca/media/rotman/Mimicking-Finance---Nov-2025.pdf)） |
| 交易风格切换一致性 | prompt 设定 4 种行为金融特质 | 用 Mann-Whitney 检验风格切换是否符合理论 | 只部分符合（[2602.07023](https://arxiv.org/abs/2602.07023)） |
| CLQT | 用"授权书"约束风格 | 风格漂移、换手一致性、信号遵从、授权对齐 | "说一套做一套"偏差 +0.23~+0.30。作者的解释：文本只能给模型陈述性知识，给不了程序性的产生式规则（[2606.29771](https://arxiv.org/abs/2606.29771)） |

**要点**：
- 模型自带"性格"，persona 文本未必压得住：Alpha Arena 创始人说各模型的偏差在多轮 prompt 迭代后依然存在；AMA 发现框架主导行为。我们 10/16 审计里 16 条链 02 全部判成"普跌·资金惯性层"（`paper_audit_20261016.md` #4）是同一现象：共同框架加共同底座模型，压过了 persona。
- 目前能可靠刻画"像"的东西，是行为统计（Mimicking Finance 71%、MILA 的延续基线），不是 LLM 写的论证文字。

---

## 四、多 agent / 多策略怎么组合：有证据的结论

| 结论 | 证据 | 级别 |
|---|---|---|
| 辩论的增益大部分等于多数投票；辩论本身是鞅，不提高期望正确率 | Debate or Vote，NeurIPS 2025（[2508.17536](https://arxiv.org/abs/2508.17536)） | 理论 + 7 个 NLP 基准 |
| 交易辩论里推理质量和 Sharpe 无关（r=0.07，p=0.29）；结构化 prompt 把推理分从 0.72 提到 0.84，收益不涨；用 JS 散度强制保留分歧后 Sharpe +0.14（p=0.028）；4 个 agent 辩 5 轮反而亏损（谄媚趋同） | [2609.29701](https://arxiv.org/abs/2609.29701)，210 组受控模拟 | C（历史模拟） |
| 辩论成败主要取决于个体推理强度和成员多样性；多数压力会压制独立纠错 | [2511.07784](https://arxiv.org/abs/2511.07784) | 逻辑谜题 |
| 用"分歧闸"：多空没有共识就不交易（对比 TA 每次辩论必出裁决） | [CGX, MDPI](https://www.mdpi.com/2079-9292/15/15/3453) | C（加密，弱） |
| 跨底座多数投票（Vote）结果多落在单底座的中间，换来稳健性，不是增益 | AMA Table 1（[2510.11695](https://arxiv.org/abs/2510.11695)） | B（样本小） |
| 估计误差会吃掉"优化权重"：25 个资产时，均值方差要大约 3000 个月数据才能稳定赢 1/N | DeMiguel 等 2009（[RFS](https://academic.oup.com/rfs/article-abstract/22/5/1915/1592901)） | 经典，强 |
| 从 N 个配置里挑样本内最好的那个，很可能在样本外排到中位数以下（PBO） | Bailey 等（[SSRN 2326253](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)） | 经典，强 |
| 同一配置重复跑，Sharpe 能差到 2.3；排名必须先过噪声带 | CLQT §7.7 | B |
| 真钱的多模型组合：按质押加权，奖励"对 meta model 的独有贡献"（MMC），而不是裸相关性 | Numerai（[AI Street](https://www.ai-street.co/p/jpmorgan-invests-500m-in-crowdsourced-ai-hedge-fund)） | A（非 LLM） |
| Hedge/指数加权属于"元学习"类在线组合方法，有 regret 界，但对非平稳、小样本、带成本的情况没有收益保证 | OLPS 综述（[1212.2129](https://arxiv.org/abs/1212.2129)） | 理论 |

---

## 五、被证明没用或有害的做法

| 做法 | 证据 | 和我们的关系 |
|---|---|---|
| 让 LLM 直接预测价格或时间序列 | 把 LLM 组件去掉或换成注意力层，预测不变甚至更好（[2406.16964](https://arxiv.org/abs/2406.16964)）；Alpha Arena 创始人同样承认 | 我们 06 的挂价已经由锚点和板限约束，但 trigger_price 仍由 LLM 拍，`Z*系数` 公式也由 LLM 选 |
| 多轮、多人辩论 | 上一节 2508.17536、2609.29701 | 03 |
| 在模型训练窗口内回测，或给模型看公司名 | Profit Mirage；Look-Ahead-Bench；Glasserman & Lin 发现**隐去公司名**后样本内反而更好，"分心效应"比前视更严重（[2309.17322](https://arxiv.org/abs/2309.17322)） | 实盘前向不受影响；as-of 回放、历史 distill、票名先验（模型"认识"这只票）会受影响 |
| 只靠新闻情绪 | GPT-4 对标题的初始反应命中率约 90%，但这部分**不可交易**；之后的漂移收益随 LLM 普及而下降（[2304.07619](https://arxiv.org/abs/2304.07619)）；A 股政策市更难（AI-Trader） | 01 的电报和早报 |
| 堆模块和复杂度 | FINSABER 建议改做市况和风控；CLQT 单模块消融都在噪声内；FinAgent 回测一次花 198 美元 | 整条链 |
| 追求"推理写得好" | 推理质量和 Sharpe r=0.07；推理"像样"但锚定差（InvestLogicBench） | 03/04/06 的长文、盲审的"推理审查" |
| 不计成本、过度交易 | CLQT：只有成本模块对 PnL 有干净影响；Alpha Arena S1.5 Qwen 下单 1418 笔 | 审计 #6：我们的换手和持股数是真人的 5~10 倍 |
| 用通用能力榜选模型 | LiveTradeBench；AI-Trader | 模型选型 |

---

## 六、对照我们的 01→07

### 6.1 我们自己的数（10/12~10/16，16 条链）

| 步 | 账面成本 | 占比 | 实际产出（contract 统计） |
|---|---|---|---|
| 04 方案 | $321 | 23% | — |
| 06 终裁 | $279 | 20% | 回炉 20/207 次（约 10%，多为机械 contract 校验拦下） |
| 02 市况 | $242 | 17% | stance：多 4 / 中立 24 / 空 14 / 缺省 33；10/16 的 16 条链全判同一市况 |
| sub3（子链合并） | $176 | 13% | — |
| **03 辩论（b+s+j）** | **$169** | **12%** | **裁判判多 68 次、判空 2 次（97% 判多）**；同期 02 只有约 10% 判多，03 的结论和 02、06 的实际动作脱节 |
| 05 风控 | $102 | 7% | 否决 395 / 条件批准 469 / 批准 108（否决率 41%，活跃） |
| 盲审 | $53 | 4% | 首审 75 次，二审 3 次，约 4% FAIL；最终 75/75 通过 |
| 01/01m | $26 | 2% | — |
| 07 复盘 | $17 | 1% | 5 天只跑了 4 次 |
| 合计 | $1387 | | 5 天 |

### 6.2 我们多出来的、缺的、白花钱的

**比外部多（这些是我们的优势，保留）**：
- 驱动器机械闸：价格锚、板限区间、规则情境校验、仓位上限。对应 CLQT "风险纪律来自约束层"、ai-hedge-fund 的确定性风控。外部框架里这部分我们最硬。
- 保守撮合（T+1、涨跌停、一字买不到）和对照组 A-control。外部基准大多没有。
- 实盘前向运行：模型截止日（2026-06）早于运行日期，没有 Profit Mirage 式泄漏。这点比几乎所有 C 级论文都干净。

**缺的**：
1. **拟人度的分层度量和"延续基线"**：没有"照抄导师昨日状态"或"导师行为统计先验"这类零 token 基线，所以无法证明 LLM 链比这些基线更像导师（MILA、Mimicking Finance）。
2. **导师行为先验做硬约束**：仓位、换手、持股数、出手时段现在由 LLM 在 02/04 里推断（`paper_audit_20261016.md` #3/#6），外部证据显示这正是 LLM 最不可靠的一层（说一套做一套）。
3. **噪声带**：没有测过"同一份 facts 跑两遍，结果差多少"。不知道这个，14 个 skill 的排名和权重就分不清信号和运气（CLQT、PBO）。
4. **成本和换手约束**：没有按导师真人分位数设的换手上限。
5. **说一套做一套的一致性分**：02 的 stance、03 的胜方、persona 规则和 06 的净买卖方向是否一致，没有做机械检查。

**最可能白花钱的一步：03 辩论**，约占成本 12%，5 天 $169。三条证据：①内部数据：97% 判多，等于常数；而且 contract 里"看空降权"（空方证据要达到多方 2 倍才能判胜）和"必须分出高下"两条，把唯一有价值的信号——分歧——在设计上抹掉了；②外部：辩论约等于投票，交易辩论的推理质量和 Sharpe 无关，失败模式是趋同；③TradingAgents 本身没有做过辩论消融。
次一级是**盲审**（4%）：FAIL 率约 4%，真正的拦截主要来自机械闸。外部证据指出 LLM 的弱点在"事实锚定"，而这一项大部分可以用字符串比对做成零 token。
**盘中子链的频率**（02 加 sub3 合计约 30%）制造了换手（审计 #6）。这条和"过度交易有害"的外部证据方向一致，但我没有逐 slot 归因，证据中等。

### 6.3 改进建议（按证据强弱排序，每条一句话 + 出处）

1. **【强】拟人度主尺子改成分层行为指标，并且每层都要先赢零 token 延续基线**：分层是交不交易 → 方向 → 标的 → 仓位 → 净值轨迹；基线是"导师昨日持仓与活跃度延续"加"导师行为统计先验"。打不赢基线的 skill，说明它的 LLM 部分是负贡献。（[MILA 2609.15727](https://arxiv.org/abs/2609.15727)、[Mimicking Finance](https://www.rotman.utoronto.ca/media/rotman/Mimicking-Finance---Nov-2025.pdf)、[InvestLogicBench 2608.06108](https://arxiv.org/abs/2608.06108)）
2. **【强】导师的仓位、换手、持股数、出手时段，从 tzzb 账本机械算成硬约束，LLM 只在约束内挑票**：替代 02 的 stance 乘系数。（[CLQT 2606.29771](https://arxiv.org/abs/2606.29771) 约束层与说做偏差；ai-hedge-fund v2 确定性风控；内部 `paper_audit_20261016.md` #3/#6）
3. **【强】14 个 skill 的权重：60 个交易日以内用等权或强收缩，排名必须先过"同 facts 重复跑"的噪声带；加权目标改成对等权组合的独有贡献（类 MMC），不用裸收益**。（[DeMiguel 2009](https://academic.oup.com/rfs/article-abstract/22/5/1915/1592901)、[PBO](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)、CLQT 噪声带、Numerai）
4. **【中强】03 辩论先在 3~4 条链上停掉做 A/B，或改成零 token 的"分歧闸"**：多空 strongest_args 证据强度接近时降仓，不再强制分高下，同时撤掉"看空降权"。（[Debate or Vote 2508.17536](https://arxiv.org/abs/2508.17536)、[2609.29701](https://arxiv.org/abs/2609.29701)、[CGX](https://www.mdpi.com/2079-9292/15/15/3453)；内部 97% 判多）
5. **【中强】加换手和成本闸：每条链每日成交笔数和持股数上限，取导师真人近 20 日的 P80**。（CLQT 成本模块；[Alpha Arena S1.5 过度交易(二手)](https://finance.biggo.com/news/5BSX_Z0BaoGGrU-ID27J)；审计 #6）
6. **【中】加零 token 的"说做一致性分"**：比对 02 stance、03 胜方、persona 规则和 06 净方向，每日入 report，作为拟人度的过程维度。（[CLQT](https://arxiv.org/abs/2606.29771) Coherence 轴）
7. **【中】盲审的"编造证据"项改成机械检查（06 引用的数字和票名必须能在 01/cand_snap 里匹配到），LLM 盲审降到便宜档或只在有新买单时跑**。（[InvestLogicBench](https://arxiv.org/abs/2608.06108) 锚定是短板；内部 FAIL 率约 4%）
8. **【中】LLM 不给价格数字，只给意图和挂法类型（回踩/突破/开盘），挂价由规则从导师真人的挂价偏离分布加 cand_snap 计算**。（[2406.16964](https://arxiv.org/abs/2406.16964)、Alpha Arena 创始人原话、FCLAgent 混合设计（转引自 [rs-9372266](https://www.researchsquare.com/article/rs-9372266/latest.pdf)））
9. **【中】模型分档可以放心推进：框架决定行为、底座影响小，所以 02/04/05 用便宜档的风险可控**。（[AMA 2510.11695](https://arxiv.org/abs/2510.11695)；10/13 文档第 3 条）
10. **【中弱】资讯层只当事件触发器，不当 alpha 来源；as-of 回放和历史 distill 时可以试"隐去票名"做对照**。（[Lopez-Lira 2304.07619](https://arxiv.org/abs/2304.07619)、[Glasserman & Lin 2309.17322](https://arxiv.org/abs/2309.17322)、AI-Trader A 股结果）
11. **【弱】反思回注（10/13 文档第 1 条）改成 FinCon 式：只在回撤或连续失效时触发，并且只改执行参数**；预期对收益是中性，价值在一致性。（[FinCon 2407.06567](https://arxiv.org/abs/2407.06567)、CLQT 记忆消融）
12. **【弱】长期方向：仿 Man/RD-Agent，把"导师规则"变成可回测的代码化信号，过样本外门槛后才进链**，LLM 退到研究位。（[Man AlphaGPT](https://hedgeweek.com/news/man-group-deploys-agentic-ai-for-quant-signal-discovery)、[RD-Agent(Q)](https://arxiv.org/abs/2505.15155)、[AlphaAgent](https://arxiv.org/abs/2502.16789)）

**建议顺序**：1、3 是度量层，零 token，先做；2、5 是约束层，改动小；4 用对照链做消融，先在少数链上试。拿掉 03 后如果拟人度和收益不降，就全量砍掉。

---

## 七、我不确定 / 证据弱的地方

1. **外部的实盘和前向证据都很短**（2 周到 2 个月），A 股专门的只有 AI-Trader（5 周，2025-10~11）和 RD-Agent/AlphaAgent 的回测。"跑不赢指数"同样可能是短窗口噪声；反过来，也没有证据说它们能跑赢。
2. Alpha Arena 各二手源的数字不一致（GPT-5 有说 −58.7% 的，也有说 −62.7% 的）；S1.5 的下单笔数和"整体亏三分之一"只来自二手源（BigGo 页面我没打开）。nof1 官方复盘文章没找到。
3. CLQT 的结论来自单一温和牛市（SPY +27%）、美股大盘、双周调仓，和我们 A 股短线、日内多 slot 差距很大。"模块消融都在噪声内"也可能是因为它的窗口检验力不足（作者自己也承认）。
4. Look-Ahead-Bench 的作者是 PiT 模型厂商，有利益相关；GuruAgents 的 42% 和 TradingAgents 的结果都没有独立复现。
5. "ai-hedge-fund 型 agent 的决策由确定性代码主导"是我从 AMA 表格里三底座结果逐位相同推出来的，没有读 v1 源码核实。
6. MILA 是 80 位志愿者的纸面交易，Mimicking Finance 是基金季度持仓，都不是 A 股短线游资型真人。"71% 可预测"能不能迁移到我们的导师上，需要用 tzzb 账本实测。这正是建议 1 要做的事。
7. 内部数据只有 5 天。03 的 97% 判多取自 run_dir 顶层的 03_debate.md（只有 0915 全链才跑 03）；stance 统计取自顶层 02，可能是最后一个子链 slot 的版本；成本是账面价不是实付。"03 白花钱"的强判断，需要 A/B 消融确认（拿掉后拟人度和收益不降）。
8. Numerai 不是 LLM，Man AlphaGPT 没有披露业绩；"真钱机构不让 LLM 直接拍板"是基于公开信息的归纳，私下做法不可知。国内量化私募（九坤、幻方、明汯）怎么用大模型，没找到一手公开说法（[财联社](https://www.cls.cn/detail/2044324) 只说在布局）。
9. 多数论文我只读了摘要或 grep 了全文的关键段，没有逐篇精读实验细节。
