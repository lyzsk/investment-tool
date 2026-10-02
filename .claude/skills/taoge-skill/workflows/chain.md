# chain.md — taoge-skill 决策链编排契约（2026-10-01，TODO 0.6 + 0.7-1 合并实施）

> 定位：七步链每一步的**输入/输出/prompt 模板/哨兵/失败重跑粒度**以本文档为唯一定义。
> 驱动器=原 `scripts/plan-a/run_taoge_chain.py`(**2026-10-02 plan-a 废除, 已压缩进 `scripts/_graveyard/plans_taoge-paper_2026-10-02.zip`**;
> 本文档的 prompt 模板与契约仍有效, 需要重建驱动器时按本文档实现, 与 plan-a 代码无关)。
> **prompt 纯文本可移植**：hermes(kimi-k3) 与 claude headless 共用同一条链，模板只引用文件路径+占位符，不绑定任何 agent 框架。
> 纪律：单模型多 pass + 落盘契约，**禁多 agent 互聊和稀泥**（9/28 立法）；事实走确定性代码，LLM 只做判断/评分/表态。
> 占位符（驱动器填充，纯字符串替换）：`{date}`=yyyymmdd、`{date_dash}`=YYYY-MM-DD、`{run_dir}`=产物目录（正斜杠）。

## 运行目录与产物

```
run_dir = results/taoge_chain/live-<yyyymmdd>/(10/2 改: 原 plan-a/backtest/runs 已随 plan-a 废除)
facts.txt            # harness 确定性代码写（build_facts；市场扫描段待 Ⅰ.2 scan.mjs 接入）
01_facts.md → 02_analysis.md → 03_debate.md → 04_plan.md → 05_risk.md → 06_verdict.md → validate_report.md
```

07 复盘=另跑（需当日实际结果作输入），驱动器 `--review`。

## 通用规范（每步都适用）

- **哨兵**：每步产物文件**末行**=`STEP_OK <NN> <yyyymmdd>`；盲审=`REVIEW_OK <yyyymmdd>` / `REVIEW_FAIL <yyyymmdd>`。
  驱动器只判**文件末行**（stdout 末行会被模型闲聊污染，9/30 实测教训）。
- **新鲜度**：产物 mtime 必须晚于本步调用时刻（防上一轮的 stale 哨兵蒙混）。
- **contract 尾块**：每步产物倒数第二块=```contract 围起的 **JSON**，字段见各步契约。
  它是驱动器机械交叉验证的取数口——**模型自声明不算数，驱动器重算比对**。
- **失败重跑粒度=单步**：哨兵缺/contract 校验败 → 带失败原因回炉**本步**（≤2 次），不整链重来；再败=链中止 exit 1。
- **盘中重跑归档**：子链重跑前把被覆盖的旧产物改名 `*.prev.md`（市态对比+溯源用）。

## 交叉验证（TODO 0.6 + 用户修正案"至少两次且双向"的落地映射）

| 要求 | 落地点 |
|---|---|
| 正向 A→B（每步产出即验） | 驱动器机械校验：04 方向组.direction ⊆ 02.directions；05 逐票名单 == 04 候选名单；06 标的 ⊆ 05 批准∪条件批准 |
| 每次新步落地回溯到 01 | 机械校验零 token，每步落地后驱动器**重跑 01..当前步全部校验**（成本可忽略，天然满足） |
| 反向 06→01 + 二次盲审 | 06 产出后**独立新会话盲审**（只给 01_facts+06_verdict，不给中间环节）：矛盾检测/编造证据/后见之明污染 → validate_report.md；FAIL 则带意见回炉 06 一次 |

## 盘中子链（02→04→06）设计说明（2026-10-01 用户问"为什么省略其他"）

- **01 没省**：事实采集=harness 确定性代码（build_facts），每次触发都现场重拉（R-FRESH 纪律）——它从来不在 LLM 步骤里，"子链"指的是 LLM 判断步骤的省略范围。
- **03 辩论省的是重跑、不省输入**：盘前 03 的多空论据几小时内不会翻转，触发信号本身就是注入 06 的新证据；盘前 03 产物作为静态输入留在 run_dir 供 06 读。重跑=重复劳动。
- **05 风控同理**：否决项/仓位上限是**约束不是判断**，盘前产出注入 06 作硬约束；"逐票过堂"职能并入子链 06 的校验（06 标的 ⊆ 05 批准集的机械校验在子链模式下照跑）。
- **升级规则（兜底）**：子链 02 重跑后**市况三态与盘前不同** → 盘前 03/05 的框架本身可能失效 → 驱动器立即打印 `ESCALATE_FULL_CHAIN <date>` 并 exit 3，不再继续 04/06。
- 不自信点：极端 V 型反转日的升级规则未实测；子链延迟未实测（TODO 0.7 不自信点 1）。

## 各步契约

<!-- step:01 -->
### 01 事实采集
- 输入：facts.txt（harness 写）+ 其指示的昨日 md 涨停分析 + paper_state.json
- 输出：`01_facts.md`；contract=`{"date":"YYYY-MM-DD","sources":[...],"digest":"<=200字"}`
- 校验：哨兵+date 字段（事实摘要无上游可比对）

````prompt
任务：对 {date} 执行决策链 01 事实采集（先读 skills/taoge-skill/persona/profile.md 与 rules.md 顶部的元指令并遵守：任务优先，禁反问）。
读 {run_dir}/facts.txt，按其指示读昨日涨停分析 md 与 paper_state.json，写成事实摘要（只陈述事实，不做判断）。
写入 {run_dir}/01_facts.md（Write 工具）：正文后接
```contract
{"date":"{date_dash}","sources":["..."],"digest":"<=200字"}
```
末行只写：STEP_OK 01 {date}
````

<!-- step:02 -->
### 02 分析（定市况）
- 输入：01_facts.md + persona/rules
- 输出：`02_analysis.md`；contract=`{"market_state":"有主线|无主线退潮|普跌","leading_layer":"板块层|资金惯性层","directions":["方向1",...]}`
- 校验：market_state/leading_layer 枚举合法；directions 非空

````prompt
任务：对 {date} 执行决策链 02 分析。读 {run_dir}/01_facts.md 与 skills/taoge-skill/persona/（profile.md + rules.md）。
①市况三态判定（有主线/无主线退潮/普跌）→ 定先行层（有主线=板块层先行；无主线/退潮/普跌=资金惯性层先行，板块层降级为回避清单，9/28 立法）；
②方向→板块/概念→情绪周期判定；③输出方向清单（后续 04 方向组必须落在其中；防御兜底方向若启用也必须列进来）。
写入 {run_dir}/02_analysis.md，contract 块：
```contract
{"market_state":"...","leading_layer":"...","directions":["..."]}
```
末行只写：STEP_OK 02 {date}
````

<!-- step:03 -->
### 03 多空辩论
- 输入：01+02
- 输出：`03_debate.md`；contract=`{"winner":"多|空","decisive_reason":"...","follows_leading_layer":true}`
- 校验：winner 枚举合法；decisive_reason 非空（**必须分出高下**，9/28 立法禁和稀泥）

````prompt
任务：对 {date} 执行决策链 03 多空辩论。读 {run_dir}/01_facts.md、{run_dir}/02_analysis.md 与 skills/taoge-skill/persona/。
多空各≥3条论据，然后**必须分出高下并给决定性理由**——禁止各说各话和稀泥收场；证据确实平衡时，裁决跟随 02 定的先行层方向给最小试错仓建议，不许把"分不出高下"当空仓通行证（风控可压仓位，不能习惯性清零决策）。
写入 {run_dir}/03_debate.md，contract 块：
```contract
{"winner":"多|空","decisive_reason":"...","follows_leading_layer":true}
```
末行只写：STEP_OK 03 {date}
````

<!-- step:04 -->
### 04 交易方案
- 输入：01+02+03
- 输出：`04_plan.md`；contract=`{"candidates":[{"name":"票名","direction":"属02某方向","group":"遗留|方向","trigger":"条件价"}...],"断链说明":null}`
- 校验：candidates 非空（B72：禁止空方向组）；group=方向 的 candidate.direction ∈ 02.directions；两组齐全或"断链说明"写明断在哪环缺什么

````prompt
任务：对 {date} 执行决策链 04 交易方案。读 {run_dir}/01_facts.md、{run_dir}/02_analysis.md、{run_dir}/03_debate.md 与 skills/taoge-skill/persona/。
候选池两组列齐（9/28 立法，缺组=违规输出）：
①遗留票组=昨日语境遗留（facts 已给 paper_state/昨日候选）；
②桃哥选股方向组=必填推导链：方向→板块→细分概念→大票/小票→个股，每环带三件套（证据锚=沉淀出处/失效条件/置信度）；推不出个股也要推出方向+板块，"暂缺"只允许挂在断链环上写明缺什么；无证据硬凑=学偏，禁止。
每只候选给条件价+仓位建议。写入 {run_dir}/04_plan.md，contract 块：
```contract
{"candidates":[{"name":"...","direction":"...","group":"遗留|方向","trigger":"..."}],"断链说明":null}
```
末行只写：STEP_OK 04 {date}
````

<!-- step:05 -->
### 05 风控
- 输入：01..04（**04 候选清单逐票过堂**，harness 信息流强制，0.5-B 立法）
- 输出：`05_risk.md`；contract=`{"verdicts":[{"name":"票名","result":"批准|否决|条件批准","reason":"..."}...]}`
- 校验：verdicts 的 name 集合 **==** 04 candidates 的 name 集合（缺票/多票=回炉）

````prompt
任务：对 {date} 执行决策链 05 风控。读 {run_dir}/01_facts.md 至 {run_dir}/04_plan.md 与 skills/taoge-skill/persona/。
04 候选清单**逐票过堂**：每只给 批准/否决/条件批准+理由，不许只给组合级约束（04 每只候选都必须出现在你的结论里，少一只=废稿）。
另给组合级约束（总仓位上限/否决项清单）。写入 {run_dir}/05_risk.md，contract 块：
```contract
{"verdicts":[{"name":"...","result":"批准|否决|条件批准","reason":"..."}]}
```
末行只写：STEP_OK 05 {date}
````

<!-- step:06 -->
### 06 终裁
- 输入：01..05
- 输出：`06_verdict.md`；contract=`{"supersedes":"首裁|取代盘前决策:...|维持盘前决策:...","actions":[{"name":"票名","op":"买|卖","trigger_price":"...","position":"...","invalid_if":"..."}...],"no_trade":false}`
- 校验：actions.name ⊆ 05 批准∪条件批准；no_trade=true ⇒ 04 两组已列齐（两组列齐才允许空仓终裁）；盘中重跑 ⇒ supersedes 必须显式含"维持/取代"（决策版本号，0.7-3 立法）

````prompt
任务：对 {date} 执行决策链 06 终裁。读 {run_dir}/01_facts.md 至 {run_dir}/05_risk.md 与 skills/taoge-skill/persona/。
①买/卖/不操作+标的+条件价+仓位+失效条件；②必须含"竞价确认→早盘可执行触发器"（不只午后信号）；
③若当前为盘后运行，必须声明"盘后版=后见之明污染风险，方向判定含金量打折，以盘前版为准"；
④05 的否决项是硬约束，05 否决的票不许进终裁；⑤盘中重跑时必须显式声明"维持/取代盘前 XX 决策+理由"。
写入 {run_dir}/06_verdict.md，contract 块：
```contract
{"supersedes":"...","actions":[{"name":"...","op":"买|卖","trigger_price":"...","position":"...","invalid_if":"..."}],"no_trade":false}
```
末行只写：STEP_OK 06 {date}
````

<!-- step:blind -->
### 盲审（06→01 反向验证 + 二次交叉验证）
- 输入：**只给** 01_facts.md + 06_verdict.md（独立新会话，不给中间环节）
- 输出：`validate_report.md`；contract=`{"verdict":"pass|fail","issues":["..."]}`
- FAIL → 带 issues 回炉 06 一次 → 复审一次；再 FAIL=链中止 exit 1

````prompt
你是独立审计员（未见中间分析环节，故意如此）。只读 {run_dir}/01_facts.md 与 {run_dir}/06_verdict.md。
审计 {date} 的终裁：①矛盾检测（终裁回避的方向事实包里却在涨停潮=矛盾）；②编造证据检测（终裁引用的"事实"在 01 里是否存在）；③后见之明污染（盘后版是否用了盘中不可能知道的信息）；④结论是否被事实支持。
写入 {run_dir}/validate_report.md，逐条给 通过/存疑+理由，contract 块：
```contract
{"verdict":"pass|fail","issues":["..."]}
```
末行只写：REVIEW_OK {date} 或 REVIEW_FAIL {date}
````

<!-- step:07 -->
### 07 复盘（另跑，`--review`）
- 输入：当日实际结果（当日 md 收评/涨停分析+paper 成交）+ 当日 run_dir 全部产物
- 输出：`07_review.md`；contract=`{"预案对照":[{"项":"...","结果":"命中|漏票|误判","教训":"..."}...]}`
- 误判进 cases.md 候选队列；规则级教训标"单样本，待验证"不进 rules.md

````prompt
任务：对 {date} 执行决策链 07 复盘。读 {run_dir}/ 全部产物（01-06+validate_report）与当日 stocks md（收评/涨停分析/桃哥小节）、paper_state.json 当日成交。
盘前预案 vs 当日实际 逐条对照：候选票命中/漏票/误判各是什么，误判的直接原因，可复用教训。
写入 {run_dir}/07_review.md，contract 块：
```contract
{"预案对照":[{"项":"...","结果":"命中|漏票|误判","教训":"..."}]}
```
末行只写：STEP_OK 07 {date}
````
