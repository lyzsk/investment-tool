# cb 决策链 · workflows/chain.md（2026-10-04 建，盲区修复⑦：cb-skill 从"有眼睛"补"手脚"）

> 对象 = A-cb 账本（10 万虚拟金）。人格 = 不吃土豆0 纯行为克隆（persona/rules.md R1-R7，全部过五闸门）。
> 图纸与施工队分离：本文件是唯一契约源；驱动器 = scripts/chain/run_chain.py --skill buchitudou0（10/7 键正名，原 cb；同一份驱动器，skill 参数化）。
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
任务：对 {date} 执行 cb 决策链 02 市况判定。读 {run_dir}/01_facts.md 与 skills/buchitudou0-skill/persona/（profile.md+rules.md 全量）。
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
任务：对 {date} 执行 cb 决策链 04 选债方案。读 {run_dir}/01_facts.md、{run_dir}/02_analysis.md 与 skills/buchitudou0-skill/persona/（全量）。
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
任务：对 {date} 执行 cb 决策链 05 风控。读 {run_dir}/04_plan.md 与 skills/buchitudou0-skill/persona/rules.md 全量。
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
- 校验：v06 cb 模式（驱动器按 --skill buchitudou0 切换 code 正则/规则 id 正则/仓位上限=全仓）

````prompt
任务：对 {date} 执行 cb 决策链 06 终裁。读 {run_dir}/04_plan.md、{run_dir}/05_risk.md 与 {run_dir}/paper_state.json。
只许从 05 批准集出单；每个 action 必填：name/code(转债 11 或 12 开头 6 位)/op(买|卖|竞价T)/trigger_price/qty/anchor(该转债当前估算价=取 facts 快照或条件价同源, 禁编)/invalid_if(失效条件)；引用规则进 rules 数组（{"id":"R<n>","ctx":"情境判定≥10字"}）。
无批准票=no_trade=true 且 actions 至少留一条条件单（三选一契约）。
**op="竞价T"（10/18 新增，对应 R8「首笔=竞价买、开盘即卖」）**：只许 0915 盘前单、转债。含义=集合竞价按开盘价买入（trigger_price=你愿付的竞价上限，开盘价高于它=没买到），撮合层在 09:30 开盘后首个价自动全部卖出（不用另写卖单，也不带 cancel_below/stop_below/not_before）。他的历史：103 天竞价首笔，09:25:00 买、09:30:00~09:30:13 卖，胜率 72%（时间外 74%），每笔中位 +0.49%；正股竞价高开 ≥2% 时胜率 91%、中位 +1.17%。熟票 + 正股竞价强 = 首选；盘中子链不能用。
写入 {run_dir}/06_verdict.md，contract 块：
```contract
{"supersedes":"首裁|取代/维持...","no_trade":false,"actions":[{"name":"...","code":"123456","op":"买","trigger_price":"...","qty":10,"anchor":"...","invalid_if":"...","rules":[{"id":"R1","ctx":"..."}]}]}
```
末行只写：STEP_OK 06 {date}
````

<!-- step:blind -->

### 拟人审（10/16 晚用户定：盲审改拟人审——只审"这张单像不像不吃土豆0本人会下的单"）

- 输入：06_verdict.md + 驱动器在 prompt 末尾注入的「导师真实成交统计 / 画像核心摘要 / 本单机械统计」；独立新会话，不给中间环节
- 输出：`validate_report.md`；contract=`{"verdict":"pass|fail","dims":{"仓位":"像|不像|无据","持股数":"…","时段":"…","能力圈":"…","持有预期":"…"},"issues":["..."]}`
- 不审价格、不审对错：价格锚/编造价/撤单线矛盾由机械层管（v06 理论区间 + anchor 3% 废单 + cancel_below 校验）
- FAIL → 带 issues 回炉 06 一次 → 复审一次；再 FAIL=单子照发并标【未过拟人审】

````prompt
你是"拟人审"审计员，只回答一个问题：{date} 这张终裁单，像不像不吃土豆0本人会下的单？不评判对错、不评判能否赚钱、不审价格（价格由机械层管）。
读 {run_dir}/06_verdict.md，再对照本 prompt 末尾驱动器注入的「导师真实成交统计」「画像核心摘要」「本单机械统计」（不必整读 profile.md；摘要确实不够时才按需读 skills/buchitudou0-skill/persona/profile.md 相关段）。逐维判定：
① 仓位：单票金额占比、本单后总仓，与导师单票最大仓位/收盘总仓（中位与近 5 日）是否同一量级；
② 持股数：本单后持股只数 vs 导师持股只数中位与近 5 日；
③ 出手时段：看本单机械统计里每只买单是"开盘即成交"还是"盘中回落才成交"，对照导师真人买入时段分布（导师几乎不在竞价/开盘买而本单开仓全是开盘即成交的追价单=不像，修法是"改低吸价或不开，留给午后时段"）；
④ 能力圈：每只买入票的板块（主板/创业板/科创/北交/ETF/转债/ST）、行业/题材，是否落在导师常做范围（导师几乎没碰过的板块/行业=不像）；
⑤ 持有预期：06 写的持有期/离场条件 vs 导师持股天数（中位=默认看几天，P75=拿得住的上限；隔日走的超短型挂成中线持有=不像，反之亦然）。
每维给 像/不像/无据（统计缺失或本单不涉及=无据，无据不得判 fail）+ 一句证据（引用统计数字）。
只有某一维"不像"且有统计数字或画像原文支撑时才 fail；issues 每条写成 06 能直接照改的指令（例："单票 45% nav 远超导师单票中位 20%，改到 ≤25%"、"导师几乎不碰科创板，撤掉 688xxx"）。空仓/观望/少下在导师风格内是合理选项，修法是"不下/少下"时直接说。
写入 {run_dir}/validate_report.md：先五维表（维度 | 判定 | 证据），再 contract 块：
```contract
{"verdict":"pass|fail","dims":{"仓位":"像|不像|无据","持股数":"像|不像|无据","时段":"像|不像|无据","能力圈":"像|不像|无据","持有预期":"像|不像|无据"},"issues":["..."]}
```
末行只写：REVIEW_OK {date}（pass）或 REVIEW_FAIL {date}（fail）
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

## 盘中子链修复字段（10/14 晚新增；只新增可选字段，驱动器开关见 scripts/claude_profile/chain_flags.txt，开关关=旧行为）

- 本段不是 prompt 模板（无 step 标记），只登记契约新增字段；模型看到的说明由驱动器在开关打开时机械追加到 prompt 末尾「驱动器补充约束」块。
- **06 actions[].exit_kind**（可选，`CHAIN_FIX_FLOOR_EXIT`）：`stop`=止损 / `protect`=保护线·移动止盈 / `invalid`=买入逻辑失效 / `discretionary`=主动调仓（缺省）。前三种只许用于**现有持仓的卖单**：不计入总仓下限口径、不受 05 批准集约束（离场纪律优先于下限）；主动减仓照旧受下限约束。
- **不许交用户**（`CHAIN_FIX_NO_DEFER`）：paper 链没有用户，02/04/06 contract 出现"交用户/待用户/用户裁"类字样=回炉，规则内自己裁决（拿不准取保守一侧）。
- **06 escalate**（可选布尔，`CHAIN_FIX_ESC_RERUN`）：子链 06 判市况变到盘前框架失效时写 `"escalate":true`；驱动器在本 slot 带"市况已重判"提示重跑 02→04→06 一次（02 市况三态变同样触发）；重跑后仍升级=单照发 + exit 3。时间预算见 params.yaml `subchain_gate.esc_rerun_max_elapsed_s`。
- **子链名单**（`CHAIN_FIX_SUB_APPROVED`）：子链没有 05，04/06 标的只能 ⊆ 0915-05 批准∪条件批准 ∪ 持仓 ∪ 未成交挂单（驱动器把名单注入 prompt，v04 校验，名单外=回炉，末次机械剔除）。
- **06 holds / no_trade_reason**（可选，`CHAIN_FIX_HOLDS`）：actions 为空时二选一必填——`"holds":[{"order_id":"挂单号" 或 "code":"6位代码","why":"为何维持"}]` 或 `"no_trade_reason":"一句话"`。报表/入库不依赖它。
- **零 token 触发闸**（`CHAIN_SUBCHAIN_GATE`）：自上一已跑 slot 以来无账本事件/价格指数异动/命中电报且非 1000/1455 → 驱动器不调模型，机械写 06 维持产物（contract 含 `"gate_skipped":true` + holds + no_trade_reason）。
- **子链合并**（`CHAIN_SUBCHAIN_MERGE`）：02/04/06 三段模板拼成一次调用（同会话依次写三个文件），驱动器分块校验，坏块用 `--resume` 同会话只重写那块；产物文件名/契约不变。
