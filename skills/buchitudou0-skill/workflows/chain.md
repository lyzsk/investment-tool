# cb 决策链 · workflows/chain.md（2026-10-04 建，盲区修复⑦：cb-skill 从"有眼睛"补"手脚"）

> 对象 = A-cb 账本（10 万虚拟金）。人格 = 不吃土豆0 纯行为克隆（persona/rules.md R1-R7，全部过五闸门）。
> 图纸与施工队分离：本文件是唯一契约源；驱动器 = scripts/taoge-chain/run_taoge_chain.py --skill cb（同一份驱动器，skill 参数化）。
> 与 taoge 链的差集：无 03 多空辩论（v1 砍，TODO 待补拆环）；R1 立法=88% 出手在 09:25-09:35 → 子链时刻集中在早盘；转债标的 code 必须是 11/12 开头。
> 时间纪律（10/2 用户立法，R6）：决策原因只许用 T-1 及更早信息，当日盘前 facts 仅作状态确认，禁未来函数。

## slot→steps 映射（驱动器 SLOT_STEPS 的 cb 镜像，改这里要同步改驱动器）

| slot | steps | 说明 |
|---|---|---|
| 0915 | 01,02,04,05,06,blind | 盘前全链（无 03） |
| 0927 | 02,04,06 | 竞价后重裁（R1 主战场：开盘双通道） |
| 0935 | 02,04,06 | 开盘窗口收尾 |
| 1000 | 02,04,06 | 早盘最后一次（之后不开新仓=R1） |

## 通用规范

- 每步末行哨兵 `STEP_OK <step> <date>`（date=YYYYMMDD 无横线）；盲审 `REVIEW_OK/REVIEW_FAIL <date>`。
- 盘中重跑：旧产物归档 *.prev.md（只留最近一版）；06 contract `supersedes` 首裁含"首裁"，重裁必含"维持/取代"。
- persona 加载：profile.md + rules.md 全文（R1-R7 仅 8 条，全量可读；taoge 的 B3 分级加载不适用 cb）。
- 01 的 facts 由 harness 构建（{run_dir}/facts.txt）：六榜是股票域全景，**转债域数据缺口已知**（转债涨幅榜/溢价率榜未建，TODO）——01 必须显式标注缺口，不许拿股票榜单冒充转债事实。

## 各步契约

<!-- step:01 -->
### 01 事实采集
- 输出：`01_facts.md`；contract=`{"date":"yyyy-MM-dd","sources":["facts"],"digest":"..."}`

````prompt
任务：对 {date} 执行 cb 决策链 01 事实采集。读 {run_dir}/facts.txt（共享事实包：六榜+池子覆盖率+轮动位置+快照+电报）与 {run_dir}/paper_state.json（A-cb 账本状态）。
产出事实摘要 digest（≤500 字）：①T-1 涨停梯队里的热点方向（R6 选债的方向源）②facts 里已出现的转债/正股联动线索 ③显式标注转债域数据缺口（转债涨幅榜未建=只看见正股侧）。只整理事实不做判断。
写入 {run_dir}/01_facts.md，contract 块：
```contract
{"date":"{date_dash}","sources":["facts"],"digest":"..."}
```
末行只写：STEP_OK 01 {date}
````

<!-- step:02 -->
### 02 市况+选债方向
- 输出：`02_analysis.md`；contract=`{"market_state":"有主线|无主线退潮|普跌","leading_layer":"板块层|资金惯性层","directions":["方向1",...]}`
- 校验：同 taoge v02（枚举合法+directions 非空）

````prompt
任务：对 {date} 执行 cb 决策链 02 市况判定。读 {run_dir}/01_facts.md 与 skills/buchitudou0-skill/persona/buchitudou0/（profile.md+rules.md 全量）。
①大盘三态判定（有主线/无主线退潮/普跌）+先行层（口径同 taoge 链 02）；②**转债域适配**：大盘状态→转债情绪推断（R7：深亏全部来自开盘抢筹通道——普跌日 0927 重裁应倾向不开仓）；③输出选债方向清单=按 R6 从 T-1 热点方向取（facts 轮动位置节的方向是首选输入；方向必须能落到"有转债的正股板块"）。
写入 {run_dir}/02_analysis.md，contract 块：
```contract
{"market_state":"...","leading_layer":"...","directions":["..."]}
```
末行只写：STEP_OK 02 {date}
````

<!-- step:04 -->
### 04 选债方案
- 输出：`04_plan.md`；contract=`{"candidates":[{"name":"转债名","code":"11/12开头6位","direction":"属02某方向","group":"方向|遗留","trigger":"条件价"}...],"断链说明":null}`
- 校验：同 taoge v04（direction ∈ 02.directions；断链说明兜底）；code 格式闸在 06 层

````prompt
任务：对 {date} 执行 cb 决策链 04 选债方案。读 {run_dir}/01_facts.md、{run_dir}/02_analysis.md 与 skills/buchitudou0-skill/persona/buchitudou0/（全量）。
按 R6 从 02 方向清单选债：方向→有转债的正股→转债标的（R4 滚动熟票池优先：近期操作过的熟票列依据）。每只候选给：条件价（R1 开盘双通道=竞价强确认价/开盘回踩价）、失效条件、引用规则（结构化 {"id":"R<n>","ctx":"情境判定..."}，引用必须先答该规则情境当前是否满足）。
推不出转债标的就写断链说明（缺什么数据），禁止拿正股冒充转债候选。
写入 {run_dir}/04_plan.md，contract 块：
```contract
{"candidates":[{"name":"...","code":"...","direction":"...","group":"方向","trigger":"..."}],"断链说明":null}
```
末行只写：STEP_OK 04 {date}
````

<!-- step:05 -->
### 05 风控（五闸门执行层）
- 输出：`05_risk.md`；contract=`{"verdicts":[{"name":"...","result":"批准|否决|条件批准","reason":"..."}]}`
- 校验：名单必须=04 候选名单（同 taoge v05）

````prompt
任务：对 {date} 执行 cb 决策链 05 风控。读 {run_dir}/04_plan.md 与 skills/buchitudou0-skill/persona/buchitudou0/rules.md 全量。
逐只过闸：R1（开仓时段：本方案的开仓窗口是否落在 09:25-09:35 主战场/午后不开新仓）、**仓位纪律（10/4 用户拍板，覆盖 R5 纸面适配）**：T+0 转债不做仓位管理——有把握全仓进（日内可解套/获利了结），没把握=半仓+半仓（首半仓+确认后第二半仓）+止损/获利了结/平出；仓位管理只对 T+1 股票有效，转债线不设成数闸、上限=全仓、R7（普跌/退潮日开盘抢筹=深亏源，压仓位或否决）。每只给 批准/否决/条件批准+reason（引用规则编号）。
写入 {run_dir}/05_risk.md，contract 块：
```contract
{"verdicts":[{"name":"...","result":"批准|否决|条件批准","reason":"..."}]}
```
末行只写：STEP_OK 05 {date}
````

<!-- step:06 -->
### 06 终裁
- 输出：`06_verdict.md`；contract 同 taoge 06 骨架（actions[]+no_trade 三选一+supersedes），cb 差集：**code 必须 ^(11|12)\d{4}$（转债）**；rules 引用 id=R<n>；anchor 同立法（取 facts 快照价，禁凭印象编，matcher 锚偏离闸+拒落账闸对转债同样生效，板限 32%）
- 校验：v06 cb 模式（驱动器按 --skill cb 切换 code 正则/规则 id 正则/仓位上限=全仓）

````prompt
任务：对 {date} 执行 cb 决策链 06 终裁。读 {run_dir}/04_plan.md、{run_dir}/05_risk.md 与 {run_dir}/paper_state.json。
只许从 05 批准集出单；每个 action 必填：name/code(转债 11 或 12 开头 6 位)/op(买|卖)/trigger_price/qty/anchor(该转债当前估算价=取 facts 快照或条件价同源, 禁编)/invalid_if(失效条件)；引用规则进 rules 数组（{"id":"R<n>","ctx":"情境判定≥10字"}）。
无批准票=no_trade=true 且 actions 至少留一条条件单（三选一契约）。
写入 {run_dir}/06_verdict.md，contract 块：
```contract
{"supersedes":"首裁|取代/维持...","no_trade":false,"actions":[{"name":"...","code":"123456","op":"买","trigger_price":"...","qty":10,"anchor":"...","invalid_if":"...","rules":[{"id":"R1","ctx":"..."}]}]}
```
末行只写：STEP_OK 06 {date}
````

<!-- step:blind -->
### 盲审（独立会话，不见 06 推理过程，只核产物与证据锚）
- 输出：`validate_report.md`；contract=`{"verdict":"pass|fail","issues":[...]}`

````prompt
任务：对 {date} 的 cb 链产物做独立盲审。读 {run_dir}/01_facts.md、{run_dir}/04_plan.md、{run_dir}/05_risk.md、{run_dir}/06_verdict.md（不看任何推理过程，只核产物）。
核：①06 每个 action 的 anchor 是否在 01_facts/facts 快照里有出处（编锚=fail）②code 是否全为 11/12 开头转债 ③04→05→06 名单链是否一致（掉票=fail）④失效条件是否都可机械执行（"感觉不对就走"=fail）。
写入 {run_dir}/validate_report.md，contract 块：
```contract
{"verdict":"pass|fail","issues":["..."]}
```
末行只写：REVIEW_OK {date}（ verdict=fail 时写 REVIEW_FAIL {date}）
````

<!-- step:07 -->
### 07 复盘（另跑，`--review`）
- 输出：`07_review.md`；contract=`{"预案对照":"..."}`

````prompt
任务：对 {date} 的 cb 链做复盘。读 {run_dir}/ 全部产物 + scripts/dfcf/paper/books/A-cb.json 当日成交/废单。预案对照：每个 action 的触发/失效/成交结果 vs 终裁假设；废单逐笔归因（锚错/时段错/价未到）。产出规则修正提案（不过五闸门不许进 rules.md，只进提案区）。
写入 {run_dir}/07_review.md，contract 块：
```contract
{"预案对照":"..."}
```
末行只写：STEP_OK 07 {date}
````
