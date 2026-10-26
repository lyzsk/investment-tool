# paper v3 资料目录 v1（10/22 晚；第二层：会话里需要细节时自己查）

> 第一层（skill 全文 / 当天和前一天 md / 事实包 / 必查结果）已经在第 1 条消息里，不用再查。
> 下面是第二层：太大放不进上下文的资料，按"要回答什么问题"分类。查法优先用 `./q`（命名查询，比裸 SQL 准）；读文件用 Read / Grep（只读）。
> 仓库根目录：`C:/Users/admin/dev/investment-tool/`（下文路径都相对它）

| 要回答的问题 | 资料 | 在哪 | 时间范围 | 怎么查 | 已知坑 |
|---|---|---|---|---|---|
| 这只转债今天开盘后大概冲多高、收盘强不强 | 相似日库（竞价 / 前日状态 / K 线 / 价位 / 大盘） | `downloads/market/similar/cb_days.jsonl` | 2023 起 19.6 万个转债日 | `./q similar <代码> <D> [竞价开盘%]` | 样本 <15 会逐级放宽，看返回的"按"和 n |
| 最近几天的走势像历史上哪几段、之后怎样 | 滑动窗口日线相似 | 行情库 kline_day | 转债 2019 起；股票 2019 起 | `./q window <代码> <D> [cb\|stock] [N]` | 一次约 6 秒（股票更慢），竞价段别用 |
| 开盘到现在这样走，后来通常怎样 | 分钟路径相似 | `downloads/quotes/cb/minute_path/` | 全市场转债近 120 个交易日（回补中） | `./q wminute <代码> <D> <HH:MM>` | 只有转债 |
| 我拿着的票导师这种状态下卖不卖、怎么卖 | 导师持仓日面板 | `skills/<导师>-skill/persona/cases_auto.jsonl` + 日线 | 各导师账本起始日起 | `./q sells <skill> <D> <昨收浮盈%> <持有天数> [今开%]`；日内 T 用 `./q sellsT` | 账本无数量，成本按卖价/(1+盈亏)反推 |
| 上方压力 / 下方支撑在哪 | 关键价位 | 行情库日线 + 分钟线 | 日线全；分钟线 10/09 起关注集 | `./q levels <代码> <D> [现价] [HH:MM]` | 多来源落在同一价位 = 更强 |
| 这个题材走到第几天、在发酵还是退潮 | 题材生命周期（md 涨停分析） | `md/*/*.md` 的「涨停分析」节 | 1/15 起约 171 天 | `./q theme <题材>` / `./q themeof <股票名>` / `./q themetop <D>` | 大题材（医药等）阶段判断意义不大 |
| 导师以前做过这只票吗、结果如何 | 导师逐笔（合并成事件） | `skills/<导师>-skill/persona/cases_auto.jsonl` | 同上 | `./q same <skill> <代码>` | — |
| 某天市场 / 涨停 / 龙虎榜 / 复盘原文 | md 日记 | `md/<年>S<季>/<日>.md` | 447 天 | `./q md <日> [小节名]`（小节如 涨停分析 / 涨停梯队 / 复盘 / 加红电报） | — |
| 任意行情数字（日线 / 分钟 / 竞价 / 龙虎榜 / 行业） | 行情库 investment_market | 表：kline_day（日线，含 pre_close / limit_up / limit_down）、kline_minute（1 分钟，10/09 起关注集）、call_auction（竞价）、lhb_stock / lhb_seat（龙虎榜）、stock_industry、security_master（代码 / 名称 / 类型） | 日线 1992 起 | `./q sql "select ..."`（只读，自动 limit 200） | symbol 带交易所前缀（sh600000 / sz000001 / sh113xxx） |
| 导师规则 / 案例原文某一条 | skill 文件 | `skills/<导师>-skill/persona/rules.md` / `cases.md` | — | 已在第 1 条消息全文；要定位用 Grep | — |


## 知识 skill（10/23 建；没有人格、按案例驱动的全市场统计规律）

- `skills/market-skill/persona/rules.md`：盘面共性知识 M1~M4（强势股次日溢价 / 涨停回调 / 情绪高位分化 / 炸板次日），**已在第一层全文给你**；证据 `docs/research/strong_next_20261022.md`
- `skills/telegraph-skill/persona/rules.md`：加红电报点名票次日统计 T1~T4（每晚重算，带 n / 置信 / 截至日）；`cases.md` = 次日冲高最多 / 跌最多的点名事件；必查里候选当天被点名时会有「电报点名」一行
