# 数据采集与处理脚本健壮性审查（2026-10-16 晚）

> 用户 10/16 晚令。本轮**只审查、不改代码**：没改任何现有文件，没调 claude -p，没写库，没做 git，没发网络请求。
> 方法：逐文件读代码，再用本地已落盘的数据（downloads/market、downloads/tzzb、downloads/quotes、paper 账本与 import_rejects.csv）做只读交叉验证。
> 凡标「实证」的条目都有本地数据佐证，标「潜伏」的是代码路径成立、但当前数据里还没触发。

## 0. 摘要

| 级别 | 条数 | 说明 |
|---|---|---|
| 高 | 5 | 会**静默**产出错数据或错成交，且已触发过或一触发就很严重 |
| 中 | 20 | 特定场景下才出错 / 有兜底但兜底本身有洞 / 监控盲区 |
| 低 | 12 | 口径小偏差、潜伏的时区问题、立法不合规但影响小 |
| 已修（对照） | 5 | 今晚已修的 5 条；其中 3 条修复**没有横向推广**，残留问题已拆进 H1/H4/M12 |

**前 5 条（高）**
1. **H1 分钟线"完成"不看完整性，Java 照样入库、对账照样判 OK**：今晚只修了探针，`DONE_kline_minute` 仍然无条件写；Java `importMinute` 只看 DONE 加"非空"，对账只看 `>0`。
2. **H2 6 位代码撞键：上证指数和平安银行混成同一组分钟 bar**：`matcher --replay-min` 若遇卖单，会按"指数几千点"立即成交。`minute_supplement` 会把 88 只深市 000xxx 股票映射成指数。
3. **H3 拒落账闸的"前收"不校验日期**（实证）：10/09 星见野 600241 用的前收是 9/30 收盘 9.72（真实前收 10.69），挂 11.17 被算成偏 14.9%，单子被拒。
4. **H4 转债 20% 只修了一半**：`snapshot.limitOf`（matcher 实时撮合、回放、排板判定、一字判定、baselines 都用它）和 `run_taoge_chain.limit_of` 仍把转债按 10% 算，A-cb/B-cb 首当其冲。
5. **H6 Java 子进程超时形同虚设（5 处）**：代码先把输出读到 EOF 才去 `waitFor`，子进程一挂，Quartz 线程就永远挂住、也不报失败。paper 侧 10/11 已修，但 tzzb/bilibili/cls OCR 这几处没跟上。

---

## 1. 今晚已修（对照）

| # | 位置 | 原问题 | 状态与复核 |
|---|---|---|---|
| F1 | scripts/market/collect_minute.py:177-179 | 探针只要深市或沪市任一有逐笔就放行 → 10/16 关注集 779 只缺 358 只 | **已修**（两市都要有）；10/16 重跑后 manifest 只缺 5 只。**残留**：完成标记本身仍不看缺失率，探针只覆盖 2 只票 → 见 H1 |
| F2 | scripts/market/backfill_history.py:160-164 | 腾讯科创板成交量是"股"，被统一 ×100 | **已修**。本轮补做了**全品类分层抽样**：用 10/09 当天 history 文件与新浪快照逐只比，每类随机抽 40 只。主板/创业/科创/沪深转债/ETF(51/52/53/55/56/58/15)/沪深指数的量比全部是 1.0000，前收一致。**残留**：指数价位 history 只有 2 位小数，快照是 3~4 位（L1） |
| F3 | scripts/md/check_md_daily.py:264 | `md == "已写"` 精确匹配，遇到 "已写+ST股已写" 误判失败 | **已修**（改成 startswith）。**同类残留**：:236 `== "无复盘节(只存json)"`、:315 `"覆盖" in out` → 见 L8 |
| F4 | scripts/cls/fetch_cls_zaobao.mjs:146 + distill_cls_zaobao.py 防线二 | --date 覆盖了页面日期，抓成上一期 | **已修**（--discover 路径）。**同类残留**：`--url` 手贴路径（:133）和发哥公众号 fetch_wechat.mjs:122 仍是 --date 无条件覆盖页面日期 → 见 M12 |
| F5 | collect_daily.mjs:114、backfill_history.py:340、tzzb/backfill_fill_minutes.py:146 | 转债涨跌停按 10% 算 | **只修了一半**：snapshot.mjs:16、run_taoge_chain.py:905、lhb/seat_profile.py:34 仍按 10% → 见 H4、M11 |

---

## 2. 高严重度

### H1 分钟线完成标记 / Java 入库 / 对账三层都不看完整性
- **位置**
  - scripts/market/collect_minute.py:367-368：`write_jsonl` 之后无条件写 `DONE_kline_minute`，缺失数只写进 manifest（:371-373）。
  - inv-stock/.../market/service/impl/MarketImportServiceImpl.java:168-184 `importMinute`：只检查 DONE 文件和"列表非空"。
  - MarketPipelineServiceImpl.java:193 `minuteOk = minuteRows > 0`；:192 `dayOk = dayRows >= 5000`（全市场约 8140 行，缺 38% 也算 OK）。
  - collect_minute.py:178-179 探针固定为 002714 和 600000 两只。7/31 那类"对探针票有数据、对部分票为空"的服务器照样放行；探针票哪天停牌，所有服务器都会被判不可用。
- **触发场景**：连上的通达信服务器只有部分市场或部分票的逐笔；或流错位被丢弃的票（badCount）很多。10/16 就是 779 缺 358。
- **后果**：残缺分时整日入库，对账判 OK、不补采；下游（盯盘回放、matcher --replay-min、拟人度）把"缺分钟线的票"当成没成交或留 open。
- **修法**
  1. collect_minute 结束前算缺失率，并按市场分开算（sh/sz/bj 各自：缺失数 ÷ 应有数）。超阈值（建议 max(10 只, 2%)，任一市场 >5% 也算）时，用**下一台服务器**只重取缺失的票（connect 加 `skip_hosts` 参数）。重试仍不达标就写 `PARTIAL_kline_minute`、不写 DONE，exit 1。
  2. 探针改成从当日关注集里，按「沪主/科创/深主/创业/转债/ETF」各抽 1 只**当日有成交**的票（kline_day volume>0），全过才算合格。
  3. Java `importMinute` 读 manifest.stages.kline_minute.missingCount，超阈值抛异常；对账 `minuteOk` 改为 `distinct symbol 数 ≥ 0.95 × watchlist 数`，`dayOk` 改为 `≥ 0.97 × security_master 中当日应交易数`。

### H2 6 位代码当主键：指数和个股串在一起
- **位置**
  - scripts/dfcf/paper/matcher.mjs:307 `minuteBars` 用 `r.symbol.slice(-6)` 当缓存键。kline_minute.jsonl 每天都有固定指数 sh000001/sh000300/sh000688/sh000852，而 sz000001 平安银行、sz000688 国城矿业、sz000852 石化机械是真实个股。
  - scripts/market/minute_supplement.py:29-30 用 `{r["code"]: r}` 建 sec 和 kl，后写的覆盖先写的。security_master 里指数排在最后，所以 **88 只深市主板 000xxx 个股全部映射成上证系列指数**（实证：10/16 security_master 有 88 处 code 冲突，全是 INDEX vs STOCK）。:23 的 `have` 集合同样按 6 位算，平安银行会被当作"已有分钟线"，永远不补抓。
- **触发场景**：任一账本挂上述 3 只（supplement 场景是 88 只任一）的单，然后跑 `--replay-min`。
- **后果**：同一时刻的 bar 数组里混着指数 bar（low/high 是几千点）。SELL 单遇到 `k.h >= o.price` 立即成交，成交价 `max(挂价, 开盘)` 等于指数点位，凭空制造几百倍的收益。BUY 单则永远不成交。
- **修法**：全链路用带市场前缀的 symbol 当键。订单的 code 先经 security_master 映射（STOCK 优先，与 collect_minute.by_code 的 setdefault 同口径）；minuteBars 按 symbol 读，或至少跳过 `source == "tdx_mt"` 和 INDEX；supplement 改用 `setdefault` 且 STOCK 优先，`have` 也按 symbol 算。
- **验证方法**：在沙盒（PAPER_ROOT）给某账本挂一张 000001 SELL 单，跑 `--replay-min --dry`，看是否按几千点成交。

### H3 拒落账闸取到的"前收"可能是前天收盘（实证）
- **位置**：matcher.mjs:155 `sn.prevClose || sn.last`；:167 日线回退用 `kl.filter(k => k.d < date).pop()`，不校验它是不是上一交易日。
- **触发场景**
  - 0915 链 08:15 盘前 import 时，腾讯 qt 还停在昨天的盘：f[3]=昨收，f[4]=**前天收**，代码取的是 f[4]。
  - 或者日线归档没增量到昨天，pop 出来的是更早的收盘。
- **实证**：import_rejects.csv 2026-10-09 A-xingjianye「600241 挂 11.17 vs 前收 9.72 偏 14.9%」。9.72 是 9/30 收盘，10/08 收盘是 10.69，真实偏离只有 4.5%。打板接力类导师（前一日涨停、次日溢价买）恰好最容易被误拒。
- **修法**：快照带出 qtTime（f[30]）。日期 = 今天才用 f[4]；早于今天（盘前）就用 f[3] 当前收。日线回退要求 `prev.d === prevTradeDay(date)`，否则先补档；补不上就拒，并在拒因里写"前收日期不符"。facts / cand_snap 盘前那份也同样处理（facts.mjs 盘前把"昨日行情"标成现价，口径要标清楚）。

### H4 转债涨跌停 10%（今晚的修复没覆盖到撮合真源）
- **位置**
  - scripts/dfcf/paper/snapshot.mjs:16-20 `limitOf` 没有转债分支，11/12 开头的代码返回 9.7。用到它的地方：
    - matcher.mjs:41 `upLimit`（排板判定）
    - :414（回放板限闸）、:513（实时哨兵 3：挂价超出"前收 ± 板限"即拒单）
    - snapshot.isSealed（一字判定）
    - baselines.mjs:202 `isAtLimitUp`
    - facts 一字标注
  - scripts/taoge-chain/run_taoge_chain.py:905 `limit_of` 是同款拷贝。
- **触发场景**：转债单日涨幅超过 10.5% 时，A-cb/B-cb 追买单被"价格锚越界"拒掉；挂在 +10% 附近的买单被当"排板中"封住不成交；转债 +10% 一字被标成封死。
- **修法**：板限集中到一个真源（见通用清单 G2），转债 ±20%。matcher 的 boardLimit（:91，转债 32%）和 limitOf 也要统一来源。

### H6 Java 子进程"超时"不生效（同类修复没横向推广）
- **位置**（都是"先 readLine 到 EOF，再 waitFor"）
  - inv-stock/.../tzzb/handler/TzzbFetchHandler.java:113→120
  - bilibili/handler/BilibiliVideoHandler.java:60→70
  - bilibili/service/impl/BilibiliVideoServiceImpl.java:368→375（waitAndTail：下载和视觉都走这里）
  - cls/service/impl/ClsTelegraphServiceImpl.java:718→722（cls 图 OCR）
  - cls/service/impl/MarkdownFormatServiceImpl.java:64
- **触发场景**：子进程挂住。比如 fetch_tzzb 的 headless Edge/CDP 卡住、B站流下载卡住、OCR 模型加载卡住。
- **后果**：读循环永远不返回，`waitFor` 的超时永远走不到。Quartz 线程永久占用，任务既不成功也不失败，sys_job_log 没记录，daily_health 的"连续失败"红线也看不到（和 10/14 的 A5「0915 链线程卡死只记 1 条」同一个根）。PaperChain/PaperMatch 在 10/11 已改用 ProcessUtils.run（独立读线程 + 超时杀进程树），这 5 处没跟。
- **修法**：统一改成 `ProcessUtils.run(pb, timeoutMin)`（inv-common 已有，超时会杀子孙进程）。Java 改动按「给用户抄的 Java 规矩」交给用户粘贴。

---

## 3. 中严重度

### M1 open15：完成标记不看缺失，也没有流错位校验
- **位置**：scripts/market/collect_open15.py:60-62 无论缺多少都写 DONE_open15；:38-44 不像 collect_minute 那样核对日线 [最低, 最高]；:52 每只间隔 0.05~0.12s（约 10 次/秒，连打约 7000 次）。
- **触发**：通达信流错位（10/14 实录 184 只里 107 只串票），或服务器只给一个市场。
- **后果**：研究用的"开盘 15 分钟"数据静默串票，DONE 之后永不重做。
- **修法**：复用 collect_minute 的 `ticks_ok` 思路，用分时价和当日日线 [最低, 最高] 做校验；缺失或丢弃超过 2% 不写 DONE；请求间隔提到 ≥0.2s；按市场统计缺失。
- **本轮实证**：10/16 open15 与 kline_minute 在 09:31~09:45 的量比按板块中位数是 1.02~1.04（单位一致），最大 1.94（09:31 是否含竞价量，口径差异，见 L5）。

### M2 指数分钟线成交量和日线对不上（单位或口径未验证）
- **位置**：collect_minute.py:279-289 `bars_from_minute_time`，指数量 ×100。
- **实证**：10/13~10/16 每天分钟量合计 ÷ 日线量：上证 0.15、深成 0.15、创业板指 0.24、沪深300 0.22、中证1000 0.15，科创50 却是 0.94~1.00。个股、转债、ETF 都是 1.000（±0.1%）。
- **后果**：凡用指数分钟量做量能、量比的地方都是错的。价格不受影响。
- **修法**：用日线量做比例校准，或者先把通达信历史分时里指数 vol 的单位确认清楚（可能是"成交额/某基数"或只统计部分成分）。确认前把指数分钟 volume 写 NULL；入库前加"分钟量合计 ÷ 日线量 ∈ [0.97, 1.03]"的闸。

### M3 tzzb 接口返回业务错误时被当成功，好文件被覆盖
- **位置**：scripts/tzzb/fetch_tzzb.mjs:200-207 只把 -100 当失败，其他 error_code≠0 的信封都 `return j`。
  - :315 之后 `nav_daily.json/month.json/position.json` 被错误信封覆盖，`lastNavDate=""` 写进 state.json（:337）。
  - :321-324 day_positions 遇到错误信封会存成 `{list:[], note:"空仓或无数据"}`，**之后永不重抓**。
- **触发**：同花顺返回参数错、视图失效、维护页（JSON 格式、非 403）。
- **后果**：导师当日持仓被永久记成空仓。MENTOR 关注集、gen_tzzb_md、拟人度都受影响；state 回退还会让 health 报红、误导排障。
- **本轮核对**：现有 18 个账本的 day_positions 中，空列表基本都是入场首日（合理）。只有 buchitudou0 20260109、liuyiqing 20260129 两条是"空仓但当天有流水"，可能是当日清仓，**目前未见受损**。
- **修法**：`call()` 统一判 `String(j.error_code ?? "0") === "0"`，否则抛 `LayerFail("NO_DATA"/"AUTH")`；文件先写 .tmp，校验后再改名；day_positions 只有 error_code=0 时才落"空仓"。

### M4 tzzb 分页 A 层中途失败 → B 层只覆盖 p1，新旧两代分页混用
- **位置**：fetch_tzzb.mjs:241-249 逐页边抓边写；A 层中途抛异常后，B 层（:401-404）只重写 position_change_p1.json。
- **后果**：p1 是新的，p2..pN 是旧的或半新的。翻页边界上的行可能重复或丢失（gen_tzzb_md 的 summDates 会读全部分页）。
- **修法**：A 层先写临时目录，整账本成功后再原子替换；B 层写 p1 时把 p2+ 标成 stale（或在 state 里记 `pcGeneration`）。

### M5 Java tzzb 入库去重键太粗，同秒同票同向的拆单被吞（实证）
- **位置**：inv-stock/.../tzzb/service/impl/TzzbRecordServiceImpl.java:60-66，`exists()` 的键是 (ledger, type, time, code, side)，用在 :101 trade 和 :162 bs_leg。
- **实证**：antoo 本地 change_bs 有 377 个键冲突，入库会丢 **462 条腿**、113 条 trade（例：2026-03-13 14:31:21 002426 同秒两笔 4.06×500000 和 4.07×309700）。xuanqiucaijing 的 trans_date 只精确到日，丢 6 条腿。
- **影响面**：目前 scripts 侧只有 gen_tzzb_md 文字提到 tzzb_record，下游主要读 json，所以定"中"。将来任何读库统计都会偏。
- **修法**：键加上 price 和 qty（或 payload 哈希）；库表唯一索引同步改。

### M6 日线归档 downloads/quotes/daily 前复权口径混档（实证）
- **位置**：scripts/quotes/kline.mjs:171-180 增量合并时 `beg = 归档末日`，只重取最后几根，老 bar 保持旧的复权基准。
- **实证**：10/12~10/15 刷新过因子的 18 只票里，sh603678、sh603919 在除权日前的最后 2 根 bar「前复权 ÷ 原价」= 1.000，更早的 bar 是 0.997 和 0.988。同一个文件里两套基准，形成 0.3%~1.2% 的假跳空。
- **另**：:52 db 源成交量统一 ÷100。转债库里是"张"，东财归档是"手(10 张)"，结果差 10 倍；科创板库里已是"股"，÷100 后才是"手"，与东财的科创口径是否一致还没验证。matcher 回放的板限闸、upLimit 都用归档前收（matcher.mjs:340、:389），除权日附近会误判。
- **修法**：增量时比较"新取第一根 bar 与归档同日 bar"的收盘，差异 >0.05% 就整档重取（full）；db 源按品种换算（转债 ÷10）；归档文件记录 `adjBase` 日期。

### M7 refresh_factors：快照断档时候选会爆炸，请求频率超项目阈值
- **位置**：scripts/market/refresh_factors.py:123 `prev_snapshot` 取"前一个有 kline_day 的目录"，不校验它是不是上一交易日；:146 每次请求间隔 0.4~0.8s（约 1.7 次/秒）。
- **触发**：某交易日目录整日缺失（停电、两天都没补采）。之后每只票的前收都不等于"两天前的收盘"，全市场约 5000 只都会成为候选。
- **后果**：约 5000 次新浪请求 × 1.7 次/秒，超过项目「批量 ≤0.5 次/秒」。新浪 456 封禁会连坐 collect_daily 的主源。候选校验必然失败，全部进 pending，5 天后超期，人工告警被淹没。
- **修法**：prev_dir 必须等于交易日历上的上一交易日，否则只用 history 文件末行，或直接 exit 1 报"断档"；间隔改成 2~3s；候选超过 300 只就停下报警。

### M8 importHistory 重跑会回退因子；空因子文件会删光
- **位置**：MarketImportServiceImpl.java:370-372 `replaceFactors` 先按 symbol 物理删除，列表为空就直接 return。
- **触发**：history 回补后又经 refresh_factors 刷进了新除权，此时再手动 runOnce `importHistory`（ALL）。或者新浪 hfq 404、格式变化导致 history 因子文件为空。
- **后果**：新除权因子被历史文件覆盖丢失，或该票因子被清空，前复权全错。
- **修法**：importHistory 只在"库里没有该票因子"或"文件末事件日 ≥ 库末事件日"时替换；空列表不删除。

### M9 backfill_history --day 补采：50% 门槛太松，停牌和源未更新不区分
- **位置**：backfill_history.py:389 `idx is None → continue`（把"源还没更新到该日"也当停牌）；:405 只要求 ≥50%。amount、换手率全是 NULL；昨收依赖本地因子，缺除权事件时昨收偏、涨停价随之偏（manifest.preCloseNoFactor 只记数不拦）。
- **触发**：腾讯部分票未更新，或间歇性返回旧页。
- **后果**：可能缺 49% 的日线照样写 DONE，Java importDaily 不看行数照导，对账 5000 的门槛也能过。
- **修法**：门槛改成 ≥97%（按前一日有成交的票数算）；"无当日行"区分停牌（前一日成交量为 0 或在停牌名单）和源滞后；preCloseNoFactor 超过 20 只就拒写 DONE。

### M10 collect_daily：东财备源在项目阈值下注定会被封，且绕过 req_guard
- **位置**：scripts/market/collect_daily.mjs:78-95 emNode 直接用 https 模块，不走 gfetch；全市场约 80 页 clist，间隔 1.5~3.5s。项目阈值是 push2 约 25 次/5 分钟（req_guard em_clist 窗口 12 次/5 分钟）。
- **触发**：新浪主源失败。
- **后果**：备源跑到一半必然被封 IP，封禁还会连坐 snapshot、live_watch 的东财实时源。多源切换形同虚设。
- **其他缺口**
  - :182 只校验 `rows ≥ minCount`（a_share 5000，实际 5576，缺 10% 也能过）。
  - 不比 rows 和 total，不分交易所计数。
  - 新浪快照行本身不带日期，只靠"上证指数最后一根日线日期"间接保证（是另一个源）。
- **修法**
  - em 路走 gfetch，等窗口（maxWaitMs 设大），或把东财备源降级为"只补缺失节点"。
  - 加 `rows ≥ 0.99 × total` 和 sh/sz/bj 分交易所下限。
  - 用新浪 hs_s 节点里的上证指数收盘去核对 kline.mjs 取到的收盘（同值才认定是当日快照）。

### M11 涨跌停与 ST 口径分裂：至少 4 套规则
- **位置与规则**

| 位置 | ST 口径 | 其他 |
|---|---|---|
| collect_daily.mjs:111 / backfill_history.limit_now / snapshot.limitOf / run_taoge_chain.limit_of | ST 同板块（用户 10/11 校正、"2026-07-06 起"） | |
| lhb/seat_profile.py:34-41 | ST 一律 5% | 创业板 ST 也按 5%（应 20%）；转债按 10% |
| tzzb/backfill_fill_minutes.py:142-153 | 主板 ST 5% | 07-06 之后应为 10% |
| tzzb/mentor_fingerprint.py:122-131 | 用当日成交区间判 5% 或 10% 档 | |

- **实证**：cls 涨停池 10/13 *ST威领 +10.0%、*ST三房 +9.85%，10/14 *ST中迪 +9.96%，说明现行主板 ST 就是 10%。
- **注意**：用户这次的审查口径写的是"ST 5%"，与代码里用户 10/11 的校正以及实盘数据都冲突，以实盘为准。
- **后果**：同一只票在不同模块里被判成"涨停 / 非涨停"，席位画像、导师指纹、分钟特征互相矛盾。
- **修法**：见 G2（统一板限表，带生效日期：主板 ST 2026-07-06 前 5%、之后 10%；创业板 2020-08-24 前 10%、之后 20%；转债 2022-08-01 起 20%；新股前 5 日无限）。

### M12 手贴链接路径：--date 无条件覆盖页面日期（与 F4 同类）
- **位置**：scripts/cls/fetch_cls_zaobao.mjs:133（`--url` 加 `--date` 时直接采用 DATE_IN）；scripts/wechat/fetch_wechat.mjs:122（`DATE_IN ||` 页面 createTime，最后还会退回 UTC 今天）。
- **触发**：hermes 早上贴的是昨天的链接，或在凌晨 0~8 点贴。
- **后果**：旧一期早报或发哥推演挂进当天 md，晚上 fage 核销拿错推演打分。
- **修法**：页面日期存在且不等于 --date 时，exit 6 并提示（加 `--force-date` 才能覆盖）；回退日期一律用北京时间。

### M13 check_md_daily 把"调休上班的周六"当交易日
- **位置**：scripts/backfill_bilibili/backfill_bilibili.py:152-157 `is_off_day`：holiday-cn 的 isOffDay=false（调休上班）直接返回"非休"。check_md_daily.py:74-93 的 target_date 和 prev_trading_day 都用它。
- **实证**：2026 年节假日表里有 2026-10-10、09-20、05-09 等 6 个周末的 isOffDay=false。A 股周末一律休市。（同文件 :369 的 `is_trading_day` 判断是对的，lhb/backfill_lhb.mjs 也注明了"调休周六不开市"。）
- **触发**：调休周六之后的周一（如 10/12）。早上轮的 target_date 和"上一交易日遗留"会算成周六，md 不存在就跳过，**真正的上一交易日（10/09）的遗留步骤被跳过**。check_md 10/13 才上线，本次没撞上，下次遇到调休就会触发。
- **修法**：`is_off_day` 改为 `weekday ≥ 5 or holidays.get(key, False)`。B站时间窗 in_window 用的是"工作日"语义，需要的话单独留一个函数。

### M14 check_md_daily 收尾步骤失败不计入退出码
- **位置**：check_md_daily.py:598 `failed` 只收各天 steps 的结果。profile_index、report、futures、weights、reflect_trigger、open15、related、realvs、persona_snap、lhb_backfill（:604-660）失败只写进 summary，退出码仍是 0。
- **后果**：sys_job_log 记为成功，daily_health 的"任务连续失败"红线看不到。
- **修法**：summary 里值以"失败"开头的项也计入 failed；或者单独给出 exit 3，表示"主步骤成功但有收尾失败"。

### M15 check_md tzzb_sum：生成失败被吞，推测层只认哨兵
- **位置**：check_md_daily.py:310 fetch_quotes 的 rc 被忽略；:313-316 gen_tzzb_md rc≠0 不计失败（只当"无数据"）；:338 LLM 只认 `TZZB_SPEC_DONE`，不核对 todo 名单里每人的小节是否真的出现【推测】。
- **修法**：rc≠0 记入"失败"；LLM 返回后重读 md，逐个 todo 检查有没有【推测】，缺的列出来算部分失败。step_cls 同理：哨兵之后核对四小节仍然 `filled`。

### M16 B站下载截断后永久跳过；ASR 不核对覆盖时长
- **位置**：scripts/bilibili/fetch_bilibili.mjs:59-64 `download()` 不比对 Content-Length；:67 `existsNonEmpty` 只要 size>0 就跳过；process_video.py:36-40 只要 raw.txt 非空就跳过 ASR；Java BilibiliVideoServiceImpl.downloadOne 只看退出码 0。
- **触发**：网络中途断开，留下半截 m4a。
- **后果**：转写只覆盖前半段，sum 和 distill 拿残稿，状态机照样推进。
- **修法**：先写 .part，校验 Content-Length 一致再改名；ASR 之后用 ffprobe 取 m4a 时长和 view.duration 比较，最后一个 segment.end 要 ≥ 0.9 × duration，否则判失败。

### M17 matcher 实时撮合不校验行情新鲜度和停牌
- **位置**：snapshot.mjs:90 `usable` 只要求 last>0 且 prevClose>0；matcher.mjs once() 直接用 q.last 成交。qtTime（f[30]）有值，但没用来校验。
- **触发**：停牌票（腾讯照样返回前收和 last）；或源返回的是上一交易日的数据。
- **后果**：停牌票的买单"成交"了。
- **修法**：qtTime 日期必须是今天，且当日成交量 vol>0 才允许撮合；否则跳过并在 note 里标"停牌/行情陈旧"。

### M18 minute_supplement 的"取不到"名单是永久的
- **位置**：minute_supplement.py:71 写入 kline_minute_extra_miss.json，:24 之后永不重试。
- **触发**：补抓当时连上了一台坏服务器（10/16 那种只有深市的）。
- **修法**：miss 记录带时间戳和服务器，24 小时后或换服务器时允许重试一次。

### M19 daily_health 的盲区（监控覆盖）
- **已覆盖**：DONE 是否存在；分钟缺失率（10/16 新加）；tzzb 新鲜度；请求层熔断；任务失败次数；应用 ERROR。
- **缺的红线（建议新增，都是零网络的本地读）**
  1. kline_day 行数 ≥ 前一日 × 0.98，且 sh/sz/bj 各自达标；manifest.nodes rows/total ≥ 0.99。
  2. 分钟线：manifest.badCount；分市场缺失率；"分钟量合计 ÷ 日线量"按板块的中位数 ∈ [0.97, 1.03]（这条能抓 F2、M2 这类单位错）。
  3. DONE_factor 是否存在；factor.expired/pending 数；factor 候选数 >300 就报红（M7 的信号）。
  4. open15 缺失率；call_auction 覆盖率（有行的 symbol 数 ÷ 关注集数，M20）。
  5. **库与文件一致**：kline_day 和 kline_minute 当日行数等于 jsonl 行数（只读查库）。
  6. paper：import_rejects.csv 当日"拒落账"条数，以及其中前收日期不是上一交易日的（H3）；minute_supplement miss 数。
  7. check_md 本轮 summary 里所有"失败"项（M14）。
  8. Java 任务"开始了但没结束"：sys_job_log 里某 handler 超过 2 倍 TIMEOUT 仍无记录，对应 H6 的线程挂死（参照 0915 那条哨兵的写法推广到所有 handler）。
  9. 财联社早报：比较 meta.json 的 ctime 日期（现在只看目录名）。
  10. 涨停池：cls 涨停只数与东财涨停池只数相差 >10% 报黄（fetch_cls_pool 已经取到东财池，零额外请求）。

### M20 竞价完成标记不看覆盖率
- **位置**：collect_auction.py:160，只要有 1 行就写 DONE；Java importAuction（MarketImportServiceImpl.java:230 起）先删后插，不看行数；对账只看 `>0`。
- **触发**：新浪 10 分钟里大半轮次失败，只拿到指数和少量票。
- **修法**：manifest 记"有行的 symbol 数 ÷ 目标数"，低于 0.9 写 PARTIAL；Java 拒导 PARTIAL。

---

## 4. 低严重度

- **L1 history 指数价位精度**：backfill_history 的指数价只有 2 位（腾讯源），快照段是 3~4 位，同表混精度（实证：sh000001 10/09 history 3811.90 vs 快照 3811.9043）。修法：指数 preClose 和 close 以快照为准，或在表里注明精度。
- **L2 UTC 日期缺省（凌晨 0~8 点运行即错一天）**
  - dfcf/paper/facts.mjs:26（--date 缺省）
  - facts.mjs:49 调 scan.mjs 时**没传 --date**，scan.mjs:268 缺省用 UTC
  - matcher.mjs:471（跨日作废判定）
  - quotes/fetch_quotes.mjs:101、quotes/kline.mjs:119（因子缓存日）
  - tzzb/fetch_tzzb.mjs:147/167/271/396（停更判定）
  - wechat/fetch_wechat.mjs:122
  - 当前主要调用都传了 --date，或在 08:00 之后跑，所以是"潜伏"。修法：统一用 `toLocaleDateString("sv-SE")` 或 `Asia/Shanghai`。
- **L3 claude 用量报告 +8h（已知问题，根因确认）**：scripts/lib/claude_call.py:171 写入的是**本地时间** `datetime.now()`，claude_usage_report.py:23 却当 UTC 再加 8 小时。结果 16:00 之后的会话被算到次日。修法：删掉 +8h（或写入端改成带时区）。
- **L4 ticks_ok 遇到无日线收盘的票直接放行**：collect_minute.py:339 `not k.get("close")`。停牌或不在 kline_day 的票，如果碰上流错位，回包会被当成本票写入。修法：无日线时要求 ticks 为空，否则丢弃。
- **L5 open15 与 kline_minute 的 09:31 口径**：open15 的 09:31 可能含 09:25 竞价量（量比最大 1.94），kline_minute 把竞价放在 09:30 bar。两份文件口径不同，需要在 open15 文档里注明。
- **L6 fetch_quotes 分时"已存不覆盖"**：fetch_quotes.mjs:46 盘中跑过一次，半天的文件就永久锁定；不查 241 根；不走 req_guard。修法：bar 数 <241 且当日已收盘就允许覆盖。
- **L7 futures 存档**：check_md 00:00 轮跑 `futures.mjs --write`，会以新的自然日命名（周六文件装的是夜盘数据）；取数失败也写 "[期货获取失败]" 并 exit 0。修法：文件名用 check_md 的目标日 d，失败时 exit 1。
- **L8 其余字符串精确匹配判成功**：check_md_daily.py:236 `== "无复盘节(只存json)"`；:315 `"覆盖" in out`（依赖 gen_tzzb_md 的 stderr 措辞）；Java BilibiliVideoServiceImpl.hasPages 用 `contains("\"pages\"")`，`"pages": []` 也算通过。修法：脚本输出结构化 JSON 字段（`ok`/`wrote`），调用方读字段。
- **L9 req_guard 跨进程窗口竞态**：scripts/lib/req_guard.mjs `_pre` 读状态、判断、写回之间没加锁，15 条链并发时可能同时放行；`guardLoop>50` 后会失效放行。修法：用 `fs.openSync(lock, "wx")` 加短锁，或改成按文件追加时间戳计数。
- **L10 fill_cls_md.py**：:24-27 `quarter_dir` 写死 "2026S"（2027 年会失效）；只解析 `imgs[0]`；出现 PARSE_FAIL 也是 exit 0。这是离线蓝本，日常走 Java，影响小。
- **L11 CheckMarkdownHandler 超时 240 分钟小于内部最坏耗时**：三个 UP 各 2h 加 tzzb distill 约 67 分钟。Java 杀进程树时 claude 可能正写到一半 md。修法：内部按剩余时间裁剪，或把 Java 超时设成内部上限之和。
- **L12 弹窗立法不合规的调用点**（父进程有隐藏控制台时不会弹；一旦由 pythonw、wscript 或无控制台进程直接拉起就会弹）
  - check_md_daily.py:136、:440
  - taoge-chain/pre_market.py:38、:65、:198、:220
  - run_taoge_chain.py:1363、:2217、:2291、:2363、:3499、:3903
  - backfill_bilibili.py:190、:349、:499
  - backfill_inference.py:36（`cmd /c start` 拉起 Ollama 图形界面）、:61
  - cruise_loop.py:52、manual_backfill.py:91
  - bilibili/process_video.py:44、:371、:380、:392（ffmpeg、ffprobe）
  - tzzb/llm_batch_tzzb.py:46
  - dfcf/paper/facts.mjs:49、:144
  - matcher.mjs:649
  - daily_digest.mjs:92
  - 修法：Python 统一加 `creationflags=CREATE_NO_WINDOW`，Node 统一加 `windowsHide: true`（可以收进 lib 的 run 包装）。

---

## 5. 限流与封禁合规一览（第 6 项）

| 脚本 | 目标源 | 实际节奏 | 项目阈值 | 结论 |
|---|---|---|---|---|
| collect_daily 新浪主路 | 新浪 | 1.5~3.5s/页 ≈0.4/s | ≤0.5/s | 合规（不走 req_guard，计数器看不到） |
| collect_daily 东财备路 | push2 clist | 约 80 页，1.5~3.5s | 约 25 次/5 分钟 | **违规，必封**（M10） |
| backfill_history | 腾讯 ifzq、新浪 | 每个 host 2~3s | ≤0.5/s | 合规 |
| refresh_factors | 新浪 hfq | 0.4~0.8s ≈1.7/s | ≤0.5/s | **超标**（候选少时无事，断档时爆炸，M7） |
| collect_minute / minute_supplement | 通达信 | 无间隔 | 无项目阈值 | 建议 ≥0.05s 加抖动 |
| collect_open15 | 通达信 | 0.05~0.12s，约 7000 次 | 无 | 建议 ≥0.2s（M1） |
| collect_auction | 新浪 hq | 每轮 10~15s，3 个请求 | — | 合规（不走 guard） |
| fetch_quotes（cb/stock trends） | push2his | 约 0.8s | guard 800ms | 绕过 guard（L6） |
| kline.mjs / snapshot / cls_pool / zaobao / lhb / bilibili | 各源 | 走 gfetch | 按 req_guard_sources | 合规 |
| fetch_tzzb | 同花顺 | 1.5~2.5s 加请求耗时，约 0.4/s；日预算 2000；Java 账本间隔 30~60s | ≤0.5/s | 合规（`--rank` 模式直连 fetch，10/14 起会 403，影响小） |
| fetch_wechat | 微信 | 少量，直连 fetch | — | 低风险 |

---

## 6. 做得好的地方（复核过，建议作为样板）

- collect_daily 的 `--expect`：交易日不符直接拒跑，防止把昨天的数据当今天入库。
- refresh_factors：拿 F(当日)/F(前日) 去核对 前收/昨收，误差 <0.2% 才落库，不过的进 pending 重试，超期告警。
- collect_auction：用 `f[30] != day` 剔除陈旧报文。
- LHB 入库（LhbImportServiceImpl）：同时检查"空榜 / 18:00 前临时版 / 缺 detail"，任一不满足就拒导。这是项目里完成判定最完整的一处。
- ProcessUtils.run：独立读线程，超时杀进程树。
- fetch_tzzb：熔断、日预算、单实例锁、A→B→C 三层降级、失败分类。

---

## 7. 通用加固清单

- **G1 完成标记统一走校验函数**：在 scripts/lib 建 `done_gate.py` 和 `done_gate.mjs`，形如 `write_done(dir, stage, *, expected, got, by_group, max_missing_pct, date_field_check)`。
  - 先校验：总量、各分组（sh/sz/bj、板块）覆盖率、记录日期是否全等于目标日；通过才写 DONE（内容为 JSON：时间、计数、缺失、源）。
  - 不通过就写 PARTIAL_\<stage\>，返回非 0。
  - Java 侧只认 DONE，并且读 DONE 的 JSON 复核计数（不只看文件存在）。
- **G2 单位与板限表集中维护**：新建 `scripts/lib/market_rules.json`（Python 和 Node 共读，Java 读同一份或生成常量），把下面这些都收进来，原来的 7 套拷贝全部改成引用它（H4、M11）：
  - 每个品种的量单位（股/手/张；按"源 × 品种"写，例如腾讯日线科创=股、东财转债=手=10 张）；
  - 价格小数位；
  - 涨跌停规则（带生效日期：主板/ST/创业/科创/北交/转债/新股 N、C）；
  - 价格笼子。
- **G3 抽样验证必须分层**：任何"实测 N 只一致"的结论，样本都要覆盖 {沪主, 深主, 创业, 科创, 北交, 沪转债, 深转债, 沪 ETF(51/56/58), 深 ETF(15), 沪指数, 深指数} 每类至少 3 只。建议把本次的分层比对脚本固化成 `scripts/health/unit_check.py`（零网络，只读本地 jsonl），每天由 daily_health 调用，按类输出中位数，偏离 1.0 超过 3% 报红。
- **G4 键一律用带市场前缀的 symbol**：6 位 code 只做展示。所有 dict、缓存、文件名的键都用 symbol；code 转 symbol 只能经过 security_master，STOCK 优先（H2）。
- **G5 数据必须自带日期，消费端必须核对日期**：快照、前收、页面文章、池子都要带源日期，并与目标日比较（H3、M12、M17、F4）。缺省日期一律用北京时间，禁用 `toISOString().slice(0,10)`（L2）。
- **G6 成功判定读结构化字段**：子进程末行输出 `JSON:{ok, wrote, missing...}`，调用方读字段，不做字符串匹配（F3、L8、M15）。LLM 步骤在哨兵之外加"产物复读核对"。
- **G7 多服务器、多源：探针覆盖全集，失败按缺失换源**：探针按分组各取 1 只；主循环结束后对缺失集合换服务器或换源再取一轮。备源也必须遵守同一套 req_guard 阈值，不满足阈值的备源不如不设（M10）。
- **G8 子进程调用统一包装**：Java 一律用 ProcessUtils；Python 和 Node 各一个 `run()`，默认加 CREATE_NO_WINDOW / windowsHide、超时、杀进程树、取末行 JSON（H6、L12）。
- **G9 写文件原子化、按代替换**：多文件产物先写临时目录，整批成功后再替换。分页类数据不要边抓边覆盖（M4）。错误信封不要落成"空数据"（M3）。
- **G10 监控跟着修复走**：每修一个"静默错数据"问题，就在 daily_health 加一条对应红线（M19 清单），防止同类问题复发时又没人发现。

---

## 8. 建议验证方法（本轮未执行：涉及网络、库或沙盒）

1. H2：PAPER_ROOT 沙盒里给某账本挂 000001 SELL 单，跑 `matcher --replay-min --date 2026-10-16 --dry`，看成交价。
2. H3：下个交易日 08:10，只读调用 `snapshot.mjs --codes 600241`，看 qtTime 和 prevClose 是不是前天的。
3. M2：拿一个交易日，把通达信历史分时的指数 vol 合计与东财或新浪的指数日线量对比（需要联网，一次请求）。
4. M3：在 `--root downloads/tzzb_cand` 的冒烟目录里，喂一个 error_code≠0 的假响应（改 transport mock），看 nav_daily.json 和 day_positions 会不会被写坏。
5. M5：只读查库 `select ledger, count(*) from tzzb_record where record_type='bs_leg' group by ledger`，与本地 change_bs 文件腿数（去重后）对比。
6. H6：在测试环境让 fetch_tzzb 卡住（例如 `--layer B` 加断网），确认 TzzbFetchHandler 是否超过 15 分钟仍不返回。
7. M13：用 `check_md_daily.py --dry` 并 mock 当前时间为 2026-10-12 07:30，看 target_date 和遗留日。
8. M6：对 sh603919 用 `kline.mjs --codes 603919 --full` 重取（需联网），与现档对比基准。

## 9. 不自信点

- H2：目前没找到任何账本挂过 000001/000688/000852（grep plans 无命中），属于潜伏问题；"影响极大"是按代码路径推断的。
- H3：600241 那张单是盘前快照路径还是日线回退路径产生的 9.72，无法从 csv 区分。两条路径都有缺陷，修法都覆盖了。
- M2：指数分钟量偏小的原因（单位还是统计口径）没查清，只确认"和日线对不上"。科创50 恰好对得上，原因也不明。
- M5：tzzb_record 目前下游消费很少，"中"是按现在的影响定的；将来要读库做统计时应升为高。
- M6：东财 push2his 对科创板的量单位（股还是手）没有联网核实；db 源 ÷100 之后与东财档是否一致仍待验证。
- M11 的 ST 规则：以代码注释（用户 10/11 校正、"2026-07-06 起"）和 cls 涨停池 3 个样本为据。生效日 07-06 本身没有独立核实。
- tzzb 净值是否会在当天内被修订（如果会，Java `hasNavDay` 一旦命中就短路后续抓取，当天第一个值会被冻结）——没查到证据，未列入问题清单，只在这里记一笔。
- L12 弹窗：实际会不会弹取决于父进程有没有隐藏控制台。Java ProcessBuilder 拉起的链路按记忆不弹，所以定"低"。
