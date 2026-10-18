# paper/ — 模拟盘实验（2026-10-02 建，设计文档=docs/TODO.md §E）

> 目的：不动真钱证明 skill 可用可靠高收益。多账本归因：谁的决策赚谁的线。
> 隐私：虚拟资金无实盘隐私问题，但 plans/books 是实验状态，统一 gitignore；只有代码和本 README 进 git。

## 账本（各 10 万虚拟金，互相独立，不与实盘共用）

> **10/15 用户定现行口径**: A 线 = skill 沉淀跑模拟盘; **B 线 = 导师真人真实操作**(同花顺投资账本 tzzb, 不建模拟账本, 直接用真人净值/持仓做参照)。
> 早期设计里 B=hermes 临场单、C=用户口令单, 已废弃; books/B-taoge、B-cb、C-* 只留档(B 两本一直零成交)。

| 线 | 含义 | 数据 |
|---|---|---|
| A-<skill> | 14 导师 + 对照组 A-control 各一条定时链(09:15 盘前全链 10/16 起 08:15 开跑 + 盘中子链) | claude -p 无头链 → books/A-*.json |
| B(导师真人) | 有 tzzb 账本的导师真实操作: 当日涨跌=账本 index 日环比, 持仓=day_positions | downloads/tzzb/<ledger>/; 对照表 `real_vs_chain.mjs` → real_vs_chain/<日>.md + 微信日报; 报告「相对导师真人」口径; 拟人度 similarity.mjs |
| （实盘） | 用户真钱成交 txt | snapshots/(隐私区), 不进本目录 |

## plans 行格式（机器可读，一行一单，写在 plans/<date>_<source>.md）

```
- HH:MM | source | BUY|SELL|CXL | code | price | qty | valid | [anchor |] [cond |] note
- 09:24 | A-taoge | BUY | 600127 | 12.50 | 800 | day | 12.40 | cancel_below=11.80 | 条件单: 回踩12.50触发
- 09:27 | A-taoge | CXL | 600127 | - | - | - | - | 取代上一行(v2纠偏)
- 14:55 | C-taoge | SELL | 002714 | 43.00 | 600 | day | - | stop_below=41.5 | 用户原话: paper 卖牧原600股@43
```

- `valid`: `day`=当日有效（EOD 未成交自动作废=废单，废单率是决策质量度量）
- `anchor`（10/3 新增，链单必填/手写单可 `-`）：链自报估算锚=它认为该票现在的真实价位。可写 `12.40@5` 自定义允许偏离%（默认 3）。**撮合前机械校 |前收-锚|与|现价-锚|，双偏超阈=自动废单"需链重锚重裁"**——matcher 永不自动改价，重锚只能链重裁出新单（+CXL 旧单）
- `cond`（C7-②，可省略=旧格式兼容）：`cancel_below=<价>`=失效哨兵（快照现价跌破即撤单不撮合，任何方向）；`stop_below=<价>`=止损哨兵（**仅 SELL**：跌破即不等挂价按快照市价出）；`;` 组合；`-`=无。matcher 每轮撮合前执行
  - 10/16 新增（06 新动词）：`not_before=HHMM`（0930~1459）=此刻前不撮合也不跑哨兵，生效后按连续竞价新报单处理（吃 ±2% 笼子）；`open_sell=1`（**仅 SELL**，不与 stop/cancel 同用）=开盘卖/市价卖，挂价列只是参考（=anchor），--once 09:30 后（或 not_before 后）首次撮合按快照现价成交、不吃笼子，--replay 按开盘价（带 not_before=收盘价近似），--replay-min 按生效后首个分钟 bar 开盘价；`oid=<挂单号>` / `side=BUY|SELL`（**仅 CXL 行**）=只撤这张单 / 只撤该方向
- CXL 按 code 取消该 source 账本的最早一笔未成交单（不分方向；cond 带 `side=` 只撤该方向，带 `oid=` 只撤指定挂单且须与 code 一致）（版本链：新单+CXL 旧单，禁覆盖）
- 旧 8 字段行（无 anchor）向后兼容可解析，但锚守卫不生效（仅新单受保护）
- hermes 落行要求：source 填 B-*（她自己挂的）或 C-*（用户口令 "paper 买/卖xxx@数量"）；note 带用户原话

## 脚本

| 脚本 | 用法 | 说明 |
|---|---|---|
| `matcher.mjs` | `--init` | 建 6 账本各 10 万（books/<source>.json：现金/持仓/挂单/流水/哈希链） |
| | `--import <planfile>` | 解析 plans 行→对应账本挂单（格式校验，坏行显式报错不猜；anchor+cond 列解析、stop_below 仅 SELL 校验、拒落账闸=挂价 vs 前收超板限直接拒） |
| | `--once [--dry]` | 单轮撮合：多源快照（snapshot.mjs）→**撮合前五哨兵**（C10 顶一字涨停拒买 / 锚偏离守卫=自报锚 vs 前收+现价双偏超阈作废 / C7-② cancel_below 失效撤单 / stop_below 止损市价出 / C7-① 挂价出当日理论区间拒单）→保守成交（买: 现价≤挂价才成 / 卖: 现价≥挂价；撮合窗=09:30-15:00，窗外一律不撮合，竞价成交只走 --import-fills 人工核销；尾盘竞价 14:57-15:00 按收盘价判）→落账+哈希链 |
| | `--eod --date <d>` | 日终：废单核销→nav 结算→nav/nav_<source>.csv 同日替换(幂等)→state_digest.md 更新（次日 facts 用，含哨兵拦截数）；尾挂自动跑 report.mjs 刷新人读视图（失败仅 WARN） |
| `scorecard.mjs` | | 账本归因记分卡（零 token）：nav csv×6 账本+token_log 成本+废单率→scorecard.md/json（10/4） |
| `pool_merge.mjs` | （驱动器内部） | 扩池提案机械落账：v04 contract pool_proposals 校验后 merge 进 pools.json，票名→代码走 smartbox，失败记 unresolved（10/4） |
| `report.mjs` | `[--out <路径>]` | 人读视图（零 token 机械）：books/*.json → report.html 单文件（净值曲线内联 SVG 无 CDN/账本汇总+收益率+回撤+废单率/持仓/挂单/近 80 笔成交），浏览器直接开 |
| `facts.mjs` | `--slot <HHMM> [--date <d>]` | 共享事实包 v2：scan 六榜+持仓/挂单票快照+state_digest+**新到电报**（读当天 md `## 加红电报` 节按 slot 增量，md=唯一真源）→ facts/<date>/<slot>/facts.md+facts.json。桃哥 rules 关键词捞取归 chain 驱动器 |
| `snapshot.mjs` | `--codes a,b,c [--json <f>] [--md <f>]` | 多源行情快照（C7-① 防试错层）：沪深 腾讯→东财→新浪 / 北交所 东财→新浪；残缺数据换源、全灭=显式 error 不编数据；导出 snapMany/limitOf/isSealed 供 matcher 复用；驱动器 04 后拉候选票价格锚→cand_snap.md/.json |
| `mix_plans.py` | `--date D --slot HHMM` / `--learn --date D` / `--weights` / `--rollback` / `--selftest` / `--dryrun D0 D1` | 混合 skill 跟跑三本（10/16）：A-mix 主规则 / A-mix-eq 等权消融 / A-mix-lhb 主规则+昨日龙虎榜修正；按权重合成导师链同 slot 挂单→plans/<D>_A-mix*.md→matcher --import；Hedge 学习状态 mix_state.json；规则见脚本文件头 |

费率参数在 matcher.mjs 头 CONFIG（佣金/印花/滑点），与用户券商实收的对账=待办（09-28 成交表拟合不上标准费率，先用参数化占位）。

## 铁律

1. 账本 A/B 机械执行，任何人手不许改单——人工决策只能走 C 账本
2. 撮合保守规则：触及≠成交，买价须被现价击穿（≤）才计成交——防纸面收益虚高
3. 历史回放只用于工程冒烟，收益数字一律不看（rules.md 从历史学出=训练集考试）
4. 账本状态变更必须落哈希链（附录 D 审计红线同款）
5. **时段闸（10/3）**：matcher 只在 09:30-15:00 撮合。竞价（09:15-09:30）成交不走 matcher，只走 `--import-fills` 人工核销，且核销前必须先过锚偏离检查——**锚飞了=废单，禁按开盘价机械成交**（10/3 大亚案：锚 14.00 vs 实际前收 7.6 偏 45%，"按开盘价成交"把它救活了=错误核销）
6. **锚偏离闸（10/3）**：plans 行 anchor 字段=链自报估算锚，|前收-锚|与|现价-锚|双偏超 3%（或 `anchor@pct` 指定）→ matcher 自动废单"需链重锚重裁"。失效条款里一切"偏离重锚/放弃"语义由这道闸结构化执行，note 里的文字只是人读注释
7. **拒落账闸（10/4）**：import 时校 |挂单价-前收|/前收 > 板限（10cm→11%/20cm→21%/30cm→31%/转债→32%，板限+1pt 给"挂跌停价排队出"留活路）→ 直接拒落账（exit 1，取数失败宁可拒）。与铁律 6 分工：进口查挂单价粗筛、撮合查自报锚细校——大亚案（挂 13.40 vs 前收 7.6 偏 76%）在这道闸下根本进不了账本
