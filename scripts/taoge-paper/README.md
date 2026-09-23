# taoge-paper — 无DB过渡期 paper 模拟盘 + 数据代孕层

> 目的： 在 Java/DB 落地前(国庆假期手写代码), 用文件系统跑通 7 个交易日(9/21-9/24, 9/28-9/30)的
> **真实数据 + 真实模拟**, 并把所有"本应进 DB"的数据以**列名=表结构**的 JSONL 存好, 未来一键迁移、可随时清除重来。
>
> 命名纪律： 桃哥只是**策略风格的学习对象**。策略(含竞价模块)是我们自己的、持续迭代的。
> T 日盘中决策只使用 ≤ T-1 晚沉淀的策略内容(桃哥视频只在交易日盘后发)。

## 架构

```
交易日 T-1 晚(手动重会话): 视频→ASR→纠错→注入md→解读→沉淀规则→产出 watchlist/T.json
交易日 T(自动):
  09:12  任务计划程序启动 sentinel.mjs(常驻, 15:10 自退)
  09:15-09:25  竞价段: 10s/次抓批量快照 → raw/auction_*.jsonl
               09:24:50 产出【竞价预期】(策略竞价模块 v0.1)
               09:26    竞价验证 + 唤醒Claude(盘前心跳: k3 regime/隔夜 + 竞价单裁决)
  09:30-15:05  常规段: 批量快照→本地拼bar→触发引擎
               命中触发/异动 → wake_requests.jsonl + headless claude 裁决 → decisions/T/*.json(+哈希链)
  15:06  任务计划程序跑 paper_settle.mjs(纯脚本): 成交断言→记账→equity→market_quote_daily
```

## 目录与数据分层

| 层 | 路径 | 内容 | 归宿 |
|---|---|---|---|
| **db_bound/** | `db_bound/<表名>.jsonl` | 列名与未来 DB 表**完全一致**, 每行一 JSON | 假期迁移 INSERT; `删除本目录+state=清除重来` |
| raw/ | `raw/quotes_*.jsonl` `raw/auction_*.jsonl` | 行情原始流 | 结算后可删(m5权威数据在 kline 缓存) |
| watchlist/ | `watchlist/YYYYMMDD.json` | 前一晚沉淀的触发条件(机械可判) | 留存, 复盘证据 |
| decisions/ | `decisions/YYYYMMDD/*.json` | 每笔决策(含 info_cutoff) | 留存 |
| state | `paper_state.json` | 现金/持仓/净值, **唯一真相源** | 留存 |
| 日志 | `wake_requests.jsonl` `holes.log` `hashchain.log` | 唤醒记录/数据洞/防作伪哈希链 | 留存 |

db_bound 表(现阶段): `taoge_video` `taoge_analysis` `taoge_rule`(均带 learned_before 语义)
`taoge_backtest_run`(run_type='paper') `taoge_backtest_decision` `taoge_backtest_trade` `market_quote_daily`。

## 实时行情方案(限流预算与备选)

**核心手段: 批量快照一票全包**。腾讯 `qt.gtimg.cn/q=code1,code2,...` 单请求最多 ~60 票,
watchlist(≤40票)每个轮询周期只发 **1 个请求**, 本地用快照拼分钟bar, 不逐票拉 mkline。

| 时段 | 轮询间隔 | 请求量 | 目的 |
|---|---|---|---|
| 09:15-09:25 竞价 | 10s | ~60/天 | 竞价轨迹(可撤单段09:15-09:20只看, 09:20-09:24出预期) |
| 09:25-10:30 | 15s | ~260/天 | 早盘高频反应 |
| 10:30-14:00 | 30s | ~420/天 | 信息量下降, 降频 |
| 14:00-15:05 | 15s | ~260/天 | 尾盘 |
| mkline(逐票) | 启动回补+15:05 | ~2×N票 | 权威bar/收盘对账 |

**合计 ~1000 请求/天(单URL), 与财联社电报 handler(30s/次)同量级** — 用户验证过无问题的水平。

备选链(连续失败3次自动切换, 全部失败记 holes.log):
1. `qt.gtimg.cn`(腾讯批量快照, 主)
2. `hq.sinajs.cn`(新浪批量, 需 Referer 头)
3. `push2.eastmoney.com`(东财批量, 限流最狠, 仅兜底)
mkline 仅用 `ifzq.gtimg.cn`(2周m5), 失败则当日 bar 用快照拼的凑合 + 记洞。

竞价数据诚实声明: 09:15-09:25 快照里虚拟撮合价/匹配量的字段行为**尚未在实盘中验证**(只能在交易日验证)。
代码按 best-effort 解析+全量 raw 落盘, 字段不符合预期就记洞跳过, 绝不硬编。

## 触发引擎(watchlist 条目 schema)

```json
{
  "id": "muxi-chase-0918", "strategy": "taoge", "code": "sh688802", "name": "沐曦股份",
  "side": "buy", "valid_date": "20260918",
  "conditions": [
    {"type": "time_window", "from": "09:33", "to": "09:40"},
    {"type": "amount_gt", "value": 500000000},
    {"type": "pct_above", "value": -5}
  ],
  "action": {"type": "buy", "qty": 100, "note": "利空落地承接确认"},
  "source": "analysis/2026-09-17 沐曦: 次日3-4分钟确认承接可追"
}
```
条件(AND): `time_window` `price_above/below` `pct_above/below`(对昨收) `amount_gt`(当日累计额,元)
`vol_ratio_gt`(最近bar量/前5日同序bar均量)。
动作: `buy{qty}` `sell{qty|pct}` `notify`(只唤醒不下单)。
**live 模式 sentinel 绝不自动成交**, 只唤醒 Claude 裁决; `--auto-exec` 仅 replay/测试用。
成交口径: 触发时刻→下一根 m5 bar 开盘价(paper_settle 断言 bar 存在), 买万2.5/卖万7.5, 起点 100,475.40。

## 文件

| 文件 | 作用 |
|---|---|
| `quote.mjs` | 行情源抽象+备选切换+raw落盘 (GBK解码) |
| `sentinel.mjs` | 常驻哨兵: 轮询/拼bar/竞价捕获/触发引擎/唤醒; `--replay YYYYMMDD --no-wake --auto-exec` 回放测试 |
| `paper_settle.mjs` | 日结算: 断言成交→记账→equity→market_quote_daily |
| `dblog.mjs` | db_bound JSONL 写入 + 哈希链 |
| `config.json` / `paper_state.json` / `watchlist/` | 配置/状态/每日触发条件 |

## 清除与迁移(假期)

- **清除重来**: 删 `db_bound/` `raw/` `decisions/` `wake_requests.jsonl` `hashchain.log`, state 重置为初始资金。
- **迁移**: db_bound/*.jsonl 逐行 INSERT 进同名表(列名已对齐); market_quote_daily 同理。
  迁移后 db_bound 可归档删除, 正式切换 DB 写入。
