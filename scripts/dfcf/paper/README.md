# paper/ — 模拟盘实验（2026-10-02 建，设计文档=docs/TODO.md §E）

> 目的：不动真钱证明 skill 可用可靠高收益。多账本归因：谁的决策赚谁的线。
> 隐私：虚拟资金无实盘隐私问题，但 plans/books 是实验状态，统一 gitignore；只有代码和本 README 进 git。

## 账本（各 10 万虚拟金，互相独立，不与实盘共用）

| source | 含义 | 出单方 |
|---|---|---|
| A-taoge / A-cb | 定时链（09:15 预案+稀疏点+午间链，见 TODO §E 时刻表） | claude -p 无头链 |
| B-taoge / B-cb | 盘中临时问 hermes，她临场出的单 | hermes 直落 |
| C-taoge / C-cb | 用户人工裁决（对 hermes 说 "paper 买xxx@数量"） | hermes 代落 |
| （D=实盘） | 真钱成交 txt，在 snapshots/，不进本目录 | 用户 |

## plans 行格式（机器可读，一行一单，写在 plans/<date>_<source>.md）

```
- HH:MM | source | BUY|SELL|CXL | code | price | qty | valid | cond | note
- 09:24 | A-taoge | BUY | 600127 | 12.50 | 800 | day | cancel_below=11.80 | 条件单: 回踩12.50触发
- 09:27 | A-taoge | CXL | 600127 | - | - | - | - | 取代上一行(v2纠偏)
- 14:55 | C-taoge | SELL | 002714 | 43.00 | 600 | day | stop_below=41.5 | 用户原话: paper 卖牧原600股@43
```

- `valid`: `day`=当日有效（EOD 未成交自动作废=废单，废单率是决策质量度量）
- `cond`（C7-②，可省略=旧 9 列格式兼容）：`cancel_below=<价>`=失效哨兵（快照现价跌破即撤单不撮合，任何方向）；`stop_below=<价>`=止损哨兵（**仅 SELL**：跌破即不等挂价按快照市价出）；`;` 组合；`-`=无。matcher 每轮撮合前执行
- CXL 按 code+方向取消该 source 账本的最早一笔未成交单（版本链：新单+CXL 旧单，禁覆盖）
- hermes 落行要求：source 填 B-*（她自己挂的）或 C-*（用户口令 "paper 买/卖xxx@数量"）；note 带用户原话

## 脚本

| 脚本 | 用法 | 说明 |
|---|---|---|
| `matcher.mjs` | `--init` | 建 6 账本各 10 万（books/<source>.json：现金/持仓/挂单/流水/哈希链） |
| | `--import <planfile>` | 解析 plans 行→对应账本挂单（格式校验，坏行显式报错不猜；cond 列解析+stop_below 仅 SELL 校验） |
| | `--once [--dry]` | 单轮撮合：多源快照（snapshot.mjs）→**撮合前四哨兵**（C10 顶一字涨停拒买 / C7-② cancel_below 失效撤单 / stop_below 止损市价出 / C7-① 挂价出当日理论区间拒单）→保守成交（买: 现价≤挂价才成 / 卖: 现价≥挂价；竞价时段 09:25-09:30 不撮合；尾盘 14:57 后按收盘价判）→落账+哈希链 |
| | `--eod --date <d>` | 日终：废单核销→nav 结算→nav_<source>.csv 追加→state_digest.md 更新（次日 facts 用，含哨兵拦截数）；尾挂自动跑 report.mjs 刷新人读视图（失败仅 WARN） |
| `report.mjs` | `[--out <路径>]` | 人读视图（零 token 机械）：books/*.json → report.html 单文件（净值曲线内联 SVG 无 CDN/账本汇总+收益率+回撤+废单率/持仓/挂单/近 80 笔成交），浏览器直接开 |
| `facts.mjs` | `--slot <HHMM> [--date <d>]` | 共享事实包 v2：scan 六榜+持仓/挂单票快照+state_digest+**新到电报**（读当天 md `## 加红电报` 节按 slot 增量，md=唯一真源）→ facts/<date>/<slot>/facts.md+facts.json。桃哥 rules 关键词捞取归 chain 驱动器 |
| `snapshot.mjs` | `--codes a,b,c [--json <f>] [--md <f>]` | 多源行情快照（C7-① 防试错层）：沪深 腾讯→东财→新浪 / 北交所 东财→新浪；残缺数据换源、全灭=显式 error 不编数据；导出 snapMany/limitOf/isSealed 供 matcher 复用；驱动器 04 后拉候选票价格锚→cand_snap.md/.json |

费率参数在 matcher.mjs 头 CONFIG（佣金/印花/滑点），与用户券商实收的对账=待办（09-28 成交表拟合不上标准费率，先用参数化占位）。

## 铁律

1. 账本 A/B 机械执行，任何人手不许改单——人工决策只能走 C 账本
2. 撮合保守规则：触及≠成交，买价须被现价击穿（≤）才计成交——防纸面收益虚高
3. 历史回放只用于工程冒烟，收益数字一律不看（rules.md 从历史学出=训练集考试）
4. 账本状态变更必须落哈希链（附录 D 审计红线同款）
