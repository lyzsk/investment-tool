# chain.md — taoge-skill 决策链编排契约（2026-10-01，TODO 0.6 + 0.7-1 合并实施）

> 定位：七步链每一步的**输入/输出/prompt 模板/哨兵/失败重跑粒度**以本文档为唯一定义。
> 驱动器=原 `scripts/plan-a/run_taoge_chain.py`(**2026-10-02 plan-a 废除, 归档已被用户删除不可恢复**;
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

## slot→steps 映射（A 定时链，2026-10-02 用户拍板；驱动器 `--slot <HHMM>` 按此表选步）

| slot | 步 | 说明 |
|---|---|---|
| 0915 盘前 | 01→02→03→04→05→06→盲审 | 全链=竞价预案（预期被开盘推翻，不当全天计划） |
| 0927 竞价纠偏 | 02→04→06 | 子链；产物=条件单，滑到 09:31 也不怕 |
| 0945/1000/1030/1127 | 02→04→06 | 子链+升级规则 |
| 1230 午间 | 02→04→06 | 消化上午全部信息+午间新闻→下午计划（事件驱动并在这，一天一次） |
| 1400/1430 | 02→04→06 | 子链 |
| 1455 尾盘 | 02→04→06 | 尾盘竞价决策，14:57 前落地 |

- 每个 slot 前 5min 由 `scripts/dfcf/paper/facts.mjs --slot <HHMM>` 构建事实包，驱动器复制为 `{run_dir}/facts.txt`（01 的输入；facts.mjs=共享事实层唯一构建者）。
- 盘中子链重跑前旧产物改名 `*.prev.md`（见通用规范）；06 终裁 actions 由驱动器机械转 plans 行（LLM 不直接写 plans，防格式漂移）。
- 决策输出三选一契约（治"永远空仓"bug）：每次 06 必须落地 立即单/条件单/空仓+进场触发条件 之一；`no_trade=true` 时 actions 必须含进场条件单。

## 通用规范（每步都适用）

- **哨兵**：每步产物文件**末行**=`STEP_OK <NN> <yyyymmdd>`；盲审=`REVIEW_OK <yyyymmdd>` / `REVIEW_FAIL <yyyymmdd>`。
  驱动器只判**文件末行**（stdout 末行会被模型闲聊污染，9/30 实测教训）。
- **新鲜度**：产物 mtime 必须晚于本步调用时刻（防上一轮的 stale 哨兵蒙混）。
- **contract 尾块**：每步产物倒数第二块=```contract 围起的 **JSON**，字段见各步契约。
  它是驱动器机械交叉验证的取数口——**模型自声明不算数，驱动器重算比对**。
- **失败重跑粒度=单步**：哨兵缺/contract 校验败 → 带失败原因回炉**本步**（≤2 次），不整链重来；再败=链中止 exit 1。
- **盘中重跑归档**：子链重跑前把被覆盖的旧产物改名 `*.prev.md`（市态对比+溯源用）。
- **B3 分级加载（2026-10-03）**：rules.md 全量（239KB/134 条）**禁进任何步的 context**；常驻=元指令+profile.md+rules_index.md（索引，驱动器每轮起跑前 `node scripts/md/gen_rules_index.mjs` 自动重建防 stale）；需要某条全文 `grep -n "^### <编号>" rules.md` 按行号捞到下一个 ### 前。

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
任务：对 {date} 执行决策链 01 事实采集（元指令已随本任务下发：任务优先，禁反问；读 skills/taoge-skill/persona/profile.md 即可，本步不需要规则）。
读 {run_dir}/facts.txt，按其指示读昨日涨停分析 md 与 paper_state.json，写成事实摘要（只陈述事实，不做判断）。
两条硬规则：①**勘误表跳过**（10/6 立法）：昨日 md 涨停分析中含 `> ⚠️ 勘误` 标记的表是已证伪污染数据，禁止引用其任何内容（9/24 PCB 虚构表先例）；②**导师信号速览逐源回应**（G-1 聚合层， 10/6 立法"确保每个 skill 都别空仓"）：facts.txt 的「导师信号速览」节列出的每个信号源（桃哥/发哥/刘念青/量化实验/A658/边学本领/星见野/土豆/卢本圆/趋势天哥），摘要中必须各给一行"该源当日相关信号或'今日无信号'"——按状态标加权（✅已验证>⏳待验证>❌反例禁用），发哥回避信号单独标"刹车级"，量化实验标"只看不跟(程序化嫌疑)"。只摘录不判断。
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
任务：对 {date} 执行决策链 02 分析。读 {run_dir}/01_facts.md 与 skills/taoge-skill/persona/（只读 profile.md+rules_index.md 索引；定市况后按需 grep -n "^### <编号>" rules.md 捞 2-3 条全文，**禁全量读 rules.md**）。
①市况三态判定（有主线/无主线退潮/普跌）→ 定先行层（有主线=板块层先行；无主线/退潮/普跌=资金惯性层先行，板块层降级为回避清单，9/28 立法）；
**发哥刹车条款（G-1， 10/6 立法）**：01 摘要中发哥信号若含"回避/不追高/控回撤"且当日未被证伪——02 的市况判定必须显式回应（采纳=市况至少降半档或防御兜底方向必启用；不采纳=02 正文给一条具体反驳理由），不许无视；
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
任务：对 {date} 执行决策链 03 多空辩论。读 {run_dir}/01_facts.md、{run_dir}/02_analysis.md 与 skills/taoge-skill/persona/（profile.md+rules_index.md，按需 grep 捞规则全文，禁全量读 rules.md）。
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
- 输出：`04_plan.md`；contract=`{"candidates":[{"name":"票名","code":"002050","direction":"属02某方向","group":"遗留|方向","trigger":"条件价"}...],"断链说明":null}`
- 校验：candidates 非空（B72：禁止空方向组）；group=方向 的 candidate.direction ∈ 02.directions；code 若填必须 6 位数字（04 后驱动器按 code 机械拉候选票价格锚快照 → `{run_dir}/cand_snap.md/.json`，06 挂单价必须锚定它）；两组齐全或"断链说明"写明断在哪环缺什么

````prompt
任务：对 {date} 执行决策链 04 交易方案。读 {run_dir}/01_facts.md、{run_dir}/02_analysis.md、{run_dir}/03_debate.md 与 skills/taoge-skill/persona/（profile.md+rules_index.md，方向→选股时按需 grep 捞规则全文，禁全量读 rules.md）。
候选池两组列齐（9/28 立法，缺组=违规输出）：
①遗留票组=昨日语境遗留（facts 已给 paper_state/昨日候选）；
②桃哥选股方向组=必填推导链：方向→板块→细分概念→大票/小票→个股，每环带三件套（证据锚=沉淀出处/失效条件/置信度）；推不出个股也要推出方向+板块，"暂缺"只允许挂在断链环上写明缺什么；无证据硬凑=学偏，禁止。
每只候选给 6 位代码（从 facts 六榜/电报/state_digest 抄，查不到写 null）+条件价+仓位建议。写入 {run_dir}/04_plan.md，contract 块：
```contract
{"candidates":[{"name":"...","code":"002050","direction":"...","group":"遗留|方向","trigger":"..."}],"断链说明":null}
```
末行只写：STEP_OK 04 {date}
````

<!-- step:05 -->
### 05 风控
- 输入：01..04（**04 候选清单逐票过堂**，harness 信息流强制，0.5-B 立法）
- 输出：`05_risk.md`；contract=`{"verdicts":[{"name":"票名","result":"批准|否决|条件批准","reason":"..."}...]}`
- 校验：verdicts 的 name 集合 **==** 04 candidates 的 name 集合（缺票/多票=回炉）

````prompt
任务：对 {date} 执行决策链 05 风控。读 {run_dir}/01_facts.md 至 {run_dir}/04_plan.md 与 skills/taoge-skill/persona/（profile.md+rules_index.md，按需 grep 捞规则全文，禁全量读 rules.md）。
04 候选清单**逐票过堂**：每只给 批准/否决/条件批准+理由，不许只给组合级约束（04 每只候选都必须出现在你的结论里，少一只=废稿）。
另给组合级约束（总仓位上限/否决项清单）。写入 {run_dir}/05_risk.md，contract 块：
```contract
{"verdicts":[{"name":"...","result":"批准|否决|条件批准","reason":"..."}]}
```
末行只写：STEP_OK 05 {date}
````

<!-- step:06 -->
### 06 终裁
- 输入：01..05 + `{run_dir}/cand_snap.md`（候选票价格锚，04 后驱动器机械拉取；不存在=04 无 code 候选，跳过锚定）
- 输出：`06_verdict.md`；contract=`{"supersedes":"首裁|取代盘前决策:...|维持盘前决策:...","actions":[{"name":"票名","code":"600127","op":"买|卖","trigger_price":"...","qty":800,"cancel_below":6.95,"stop_below":null,"invalid_if":"..."}...],"no_trade":false}`
- 校验：actions.name ⊆ 05 批准∪条件批准；**code 必须 6 位数字、qty 必须正整数**（驱动器转 plans 的取数口，缺=回炉）；trigger_price=数值**或** `Z*系数` 公式（Z=cand_snap 前收，驱动器代换求值成数值才落 plans，其他文法=回炉）；**价格锚（C7-①）**：挂单价落在该票当日理论区间外=编造嫌疑回炉（区间=前收×(1±板限)，板限按代码分档 10/20/30%，主板 ST 同 10%）；cancel_below/stop_below 若填必须>0 且 stop_below 只许卖单；qty 由模型按 paper_state 现金+params 仓位规则换算，驱动器机械复检 qty×trigger_price ≤ 单票仓位上限×nav（超限=回炉）；no_trade=true ⇒ 04 两组已列齐且 actions 含进场条件单；盘中重跑 ⇒ supersedes 必须显式含"维持/取代"（决策版本号，0.7-3 立法）

````prompt
任务：对 {date} 执行决策链 06 终裁。读 {run_dir}/01_facts.md 至 {run_dir}/05_risk.md、{run_dir}/cand_snap.md（候选票价格锚，若存在）与 skills/taoge-skill/persona/（profile.md+rules_index.md，按需 grep 捞规则全文，禁全量读 rules.md）。
①买/卖/不操作+标的+**6 位代码**+条件价+**股数 qty**(按 paper_state.json 的 nav_est×单票≤1.5 成上限自己换算， qty=正整数)+失效条件；②必须含"竞价确认→早盘可执行触发器"（不只午后信号）；
**条件价与失效条件规则（C7 立法，防 9/28 大亚 14.00 型编造价）**：trigger_price 必须锚定 cand_snap.md 的前收/现价（回踩单=低于现价、突破单=高于现价但≤板限上沿，超出当日理论区间=驱动器直接回炉）；表达为前收比例时可写公式如 `Z*0.97`（Z=前收，驱动器代换求值）；失效条件能用单一边界价表达的**必须**填结构化字段——买/卖单 `cancel_below`=跌破即撤（形态破坏不接刀），卖单 `stop_below`=止损哨兵（跌破按市价出），复杂条件另写 invalid_if 文字，两者不互斥；
③若当前为盘后运行，必须声明"盘后版=后见之明污染风险，方向判定含金量打折，以盘前版为准"；
④05 的否决项是硬约束，05 否决的票不许进终裁；**你有权且应当推翻 02-05 的任何判断（方向/候选/价格），推翻上游是终裁的职责而非失误**（10/5 立法：任务独立性不靠上下文独立）；⑤盘中重跑时必须显式声明"维持/取代盘前 XX 决策+理由"；
⑥决策输出三选一：立即单/条件单(主形态)/空仓+进场触发条件——纯观望=违规输出，空仓也必须给进场条件单挂单等。
写入 {run_dir}/06_verdict.md，contract 块：
```contract
{"supersedes":"...","actions":[{"name":"...","code":"002050","op":"买|卖","trigger_price":"12.50","qty":800,"cancel_below":12.0,"stop_below":null,"invalid_if":"..."}],"no_trade":false}
```
末行只写：STEP_OK 06 {date}
````

<!-- step:blind -->
### 盲审（06→01 反向验证 + 二次交叉验证）
- 输入：**只给** 01_facts.md + 06_verdict.md + cand_snap.md（若存在；独立新会话，不给中间环节）
- 输出：`validate_report.md`；contract=`{"verdict":"pass|fail","issues":["..."]}`
- FAIL → 带 issues 回炉 06 一次 → 复审一次；再 FAIL=链中止 exit 1；回炉版若 contract 校验败**再给一次带原因回炉**（C9 修复：9/29 死链——公式价被数值校验器拒后直接 abort 无产出）

````prompt
你是独立审计员（未见中间分析环节，故意如此）。只读 {run_dir}/01_facts.md、{run_dir}/06_verdict.md 与 {run_dir}/cand_snap.md（若存在）。
审计 {date} 的终裁：①矛盾检测（终裁回避的方向事实包里却在涨停潮=矛盾）；②编造证据检测（终裁引用的"事实"在 01 里是否存在）；③后见之明污染（盘后版是否用了盘中不可能知道的信息）；④结论是否被事实支持；
⑤规则漏用抽检（B3 验证口径）：读 skills/taoge-skill/persona/rules_index.md 索引，对照 01 事实找"显然适用而 06 未体现"的规则（特别 C 类负面规则：候选/成交标的撞上祖训禁区却未回避=漏用铁证）——此维度同时验证索引备注是否足以触发捞取，发现"索引行看不出该捞"的条目直接列入 issues；
⑥价格锚核对（C7-③ 立法，防 9/28 大亚挂 14.00 vs 实际 7.6 型编造价）：06 每个 trigger_price/cancel_below/stop_below 必须能在 cand_snap.md（或 01 facts 快照）找到锚——数值超出当日理论区间（前收×(1±板限)）=编造嫌疑直接 FAIL；锚数值合理但语义矛盾（如声称"回踩低吸"却挂得比现价高、声称"突破追入"却挂得比现价低、止损价高于买入价）=列入 issues。
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
任务：对 {date} 执行决策链 07 复盘。读 {run_dir}/ 全部产物（01-06+validate_report）与当日 md（收评/涨停分析/桃哥小节）、paper_state.json 当日成交。
盘前预案 vs 当日实际 逐条对照：候选票命中/漏票/误判各是什么，误判的直接原因，可复用教训。
另附「规则引用审计」一节（B3 验证口径）：列出本日各步决策实际引用的规则编号；对照当日场景找"该引用而未引用"的漏捞嫌疑；评估 rules_index.md 备注是否足以触发正确捞取（不足以触发的条目列出编号+建议备注改写方向）。
写入 {run_dir}/07_review.md，contract 块：
```contract
{"预案对照":[{"项":"...","结果":"命中|漏票|误判","教训":"..."}]}
```
末行只写：STEP_OK 07 {date}
````
