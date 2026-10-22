**简体中文 | [English](README.md)**

<p align="center">
    <a href="https://github.com/lyzsk/investment-tool/blob/master/LICENSE">
        <img src="https://img.shields.io/github/license/lyzsk/investment-tool.svg?style=plastic&logo=github" />
    </a>
    <a href="https://github.com/lyzsk/investment-tool/members">
        <img src="https://img.shields.io/github/forks/lyzsk/investment-tool.svg?style=plastic&logo=github" />
    </a>
    <a href="https://github.com/lyzsk/investment-tool/stargazers">
        <img src="https://img.shields.io/github/stars/lyzsk/investment-tool.svg?style=plastic&logo=github" />
    </a>
</p>

# investment-tool

> **_喜欢，或者对你有帮助的话，记得点赞哦_** :star:

个人 A 股研究与模拟交易系统: Spring Boot + Quartz 驱动每日数据采集(财联社电报、B 站复盘视频、同花顺投资账本、行情), Claude Code skills 从这些语料里蒸馏每位导师的交易规则, 多 skill 决策链在模拟账户上交易, 再与导师真人账本对照打分。

# 🌐 Environment

- Java 17 / Spring Boot 3.3.4 / MyBatis-Plus 3.5.7 / Quartz
- MySQL 8.0 — 同一实例两个库: `investment_tool`(业务库) + `investment_market`(行情库)
- Node.js 24(采集脚本、决策链驱动、paper 撮合/报告)
- Python 3.13 venv(`scripts/venv/`, ASR / VLM / OCR / tzzb 工具)
- Claude Code(skills + headless `claude -p` 决策链); 可选本地 ollama(qwen3 / bge-m3)

# ✨ Features

- [x] **Quartz 定时任务系统** — 任务统一由 `sys_job` 管理(cron、misfire 策略、立即执行、暂停/恢复), 执行日志异步写入 `sys_job_log`
- [x] **财联社电报** — 每 5 分钟抓加红电报写入当日 md; 午评/收评/涨停分析图片 OCR 后填入 md 对应小节(`scripts/cls/cls_image_ocr.py`)
- [x] **交易日 md** — 每个交易日按模板生成 `md/<年>S<季度>/yyyy-MM-dd.md`, 是所有 skill 优先查阅的信息聚合层
- [x] **B 站复盘视频管线** — 发现 → 下载 → ASR(faster-whisper) → 股名纠错 → 抽帧 OCR + Qwen2.5-VL-7B 画面识别 → `results/bilibili/<mid>/<日期>/`(桃哥 / 趋势天哥 / 卢本圆)
- [x] **同花顺投资账本(tzzb)** — 11+ 位导师的调仓/净值/持仓写入 `tzzb_record` + `downloads/tzzb/<账本>/`
- [x] **导师 skills** — 一位导师一个 Claude skill(`skills/<id>-skill/persona/{rules,cases,profile}.md`), 由每日 `sum`(语料 → md) 和 `distill`(md → 核销/沉淀规则) 两个工作流喂养
- [x] **paper 模拟盘(A 线)** — 14 个 skill 账户 + 1 个对照组; 每个时点跑 01→06 决策链 + 盲审(07:30 盘前全链 … 14:35 尾盘), 每分钟撮合, 收盘 EOD 净值, 与导师真人持仓比对拟人度, `report.html`(绝对收益 / 相对对照组 / 相对上证 / 相对导师真人)
- [x] **行情库** — `investment_market`: 每日收盘全市场日线(A 股 / 转债 / ETF / 指数, 不复权原始价) + 除权日复权因子 + 关注集(~300 只)1 分钟分时与开盘/收盘集合竞价过程 + 外围 16 个品种(美股指数/中概/港股/A50 与美股期货/黄金原油/离岸人民币); 历史日线由腾讯 + 新浪因子回补
- [x] **对账** — 行情库每日核对日线/分时/竞价/因子, 缺了自动补采(含应用重启后补停机期间错过的收盘采集); UP 主视频管线逐视频核对 results → md → distill 账本并把 `bilibili_video` 同步到文件事实; 结果进 `reconcile_result`, 有缺口经 hermes 推微信
- [x] **链路入库** — 每次决策链运行结束即把运行目录解析进 `chain_run / chain_step / chain_decision / chain_decision_rule`(步骤产物版本、契约、终裁单、引用规则; 文件仍是唯一事实, 表是索引)
- [x] **hermes(微信 agent)** — 微信里盘中问答、盘前蒸馏; 对话本地留档(隐私区)
- [x] 早期功能: 基金申购/赎回自动记账、excel 导出、持仓截图 OCR

# 🚀 Quick Start

1. 建库建表
    ```bash
    # 业务库
    mysql -uroot -p -e "CREATE DATABASE IF NOT EXISTS investment_tool DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
    for f in sql/investment_tool/*.sql; do mysql -uroot -p investment_tool < $f; done
    # 行情库(建表后再执行 kline_minute 的按年分区脚本)
    mysql -uroot -p -e "CREATE DATABASE IF NOT EXISTS investment_market DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
    for f in sql/investment_market/*.sql; do mysql -uroot -p investment_market < $f; done
    mysql -uroot -p investment_market < sql/investment_market/partition/kline_minute_partition.sql
    ```
2. `mvn clean install` and `mvn package spring-boot:repackage`
3. 脚本环境
    ```bash
    npm install                                                   # node 采集脚本 / paper 工具
    python scripts/fetch_holidays_cn.py                           # 生成 inv-common holiday/<年>.json
    # python venv(ASR + VLM + OCR); torch cu124 需先装本地 wheel, 见文件头注释
    python -m venv scripts/venv
    scripts/venv/Scripts/pip install -r scripts/requirements-taoge.txt -r scripts/requirements-cls.txt
    scripts/venv/Scripts/python.exe scripts/bilibili/process_video.py --download-model   # Qwen2.5-VL-7B → scripts/models/
    ```
4. 运行 `/start.bat`(先把 `start.bat` 里的 `JAVA_HOME` 改成本机路径)

# 🗓️ Daily Pipeline

## 时刻表(交易日; 未注明的都是 Quartz 任务)

| 时间 | 任务(handler) | 做什么 |
|---|---|---|
| 00:00 | `tradingDayMarkdownHandler` | 按模板生成当日 `md/<yyyy>S<q>/<日期>.md` |
| 00:00 / 03:00 | `downloadCleanupHandler` / `ocrCleanupHandler` | 物理删除过期原料(B 站 30 天, 财联社 90 天) / 清理已处理的 OCR 图片 |
| 每 5 分钟 | `clsRedTelegraphHandler` | 财联社加红电报 → `cls_telegraph` + md; 复盘图片 → OCR → md 小节 |
| 早上(hermes) | 微信 agent | 盘前蒸馏(发哥线)、盘中问答 |
| 07:30 | `paperChainHandler` ×15(0915 时点) | 每个 skill 账户跑完整 01→06 决策链 + 盲审; 结束即入库 `chain_*` |
| 08:30 | `marketGlobalHandler` | `scripts/market/collect_global.py` → 外围隔夜收盘(按当地交易日)入 `kline_day` |
| 09:14 / 14:56 | `marketAuctionHandler`(OPEN / CLOSE) | `scripts/market/collect_auction.py` 关注集开盘/收盘集合竞价过程 → `call_auction` |
| 09:27 … 14:35 | `paperChainHandler`(0927/0935/0945/1000/1030/1100/1127/1230/1300/1400/1430/1455 时点) | 按各导师习惯时点跑盘中子链(02→04→06) |
| 09:00–14:59 每分钟 | `paperMatchHandler` | 挂单 × 实时行情撮合 → 账本 |
| 15:05 | `paperEodHandler` | 日终: 废单、净值、拟人度、`report.html`、次日 facts 用的 state digest |
| 15:10–23:10 每小时 | `tzzbFetchHandler` | 抓导师账本 → `downloads/tzzb/` + `tzzb_record` |
| 15:30 / 16:30 … 23:30, 07:00–22:30 每 30 分钟 | `bilibiliVideoHandler` ×3 | 发现并处理新复盘视频(桃哥 / 趋势天哥 / 卢本圆) |
| 15:35 | `marketDailyHandler` | 收盘流水线: `collect_daily.mjs` 全市场日线 → `refresh_factors.py` 除权检测 → `collect_minute.py` 关注集分时 → `investment_market` |
| 16:40(+ 应用启动 3 分钟后) | `marketReconcileHandler` / `MarketStartupRunner` | 回看 10 个交易日对账, 缺日线/分时自动补采 → `reconcile_result` |
| 20:00 | `paperReviewHandler` | 07 盘后复盘 |
| 23:50 | `bilibiliReconcileHandler` | UP 主视频管线对账 + `bilibili_video` 同步 → `reconcile_result` |
| 晚上(手动) | Claude Code 里说 "check md" | check-cls-md → 桃哥 sum → 桃哥 distill → tzzb sum → tzzb distill → 发哥 T+1 核销 |

## 调用链(谁调用谁)

```
Quartz(sys_job) ──► JobHandler(inv-stock) ──► ProcessUtils.run(node|python 脚本) ──► 文件 ──► Java 写库
  paperChainHandler ─► scripts/chain/run_chain.py --skill <id> --slot <HHMM>
                           ├─ scripts/dfcf/paper/facts.mjs(scan.mjs 六榜 + snapshot.mjs 行情 + md + rules_index)
                           ├─ claude -p × 01..06 步 + 盲审(提示词 = skills/<id>-skill/workflows/chain.md)
                           └─ 计划单 → scripts/dfcf/paper/plans/<日期>/
  paperMatchHandler ─► scripts/dfcf/paper/matcher.mjs(计划单 × snapshot.mjs 行情 → 账本)
  paperEodHandler   ─► matcher.mjs --eod → 净值 / similarity.mjs / report.mjs / daily_digest.mjs
  bilibiliVideoHandler ─► scripts/bilibili/fetch_bilibili.mjs → process_video.py(ASR→纠错→OCR→VLM→聚合)
  tzzbFetchHandler  ─► scripts/tzzb/fetch_tzzb.mjs → TzzbRecordService(JSON → tzzb_record)
  clsRedTelegraphHandler ─► 财联社 API → ClsTelegraphService → md;  图片 → scripts/cls/cls_image_ocr.py
  marketDailyHandler ─► MarketPipelineService: collect_daily.mjs(新浪 → 东财兜底) → refresh_factors.py → collect_minute.py(通达信逐笔)
                        → MarketImportService;  对账补采/启动补采共用同一流水线(一把锁), 往日日线用 backfill_history.py --day
  marketAuctionHandler / marketGlobalHandler ─► collect_auction.py / collect_global.py → MarketImportService
  paperChainHandler 结束 ─► ChainIngestService(运行目录 → chain_*);  reconcile 类 handler ─► reconcile_result + hermes 推送
Claude Code(晚上) ─► skills: check-cls-md / <id>-skill 的 sum 与 distill / tzzb-skill / fage-skill
```

## 数据流

```
外部来源                      原料(downloads/, 不进 git)              结果 / md(永久保留)                            知识与决策
财联社 API + 图片     ───────►  downloads/cls/<日期>/            ───►  md/<yyyy>S<q>/<日期>.md  ─┐
B 站视频              ───────►  downloads/bilibili/<mid>/<日期>/ ───►  results/bilibili/<mid>/<日期>/(txt + vision.json) ─► sum ─┤
同花顺投资账本        ───────►  downloads/tzzb/<账本>/  + tzzb_record ────────────────────────────────────────────────► sum ─┤
微信文章(hermes)      ───────►  downloads/wechat/, cls_zaobao/ ───────────────────────────────────────────────────────► spec ┤
                                                                                                                             ▼
                                                              md(每日枢纽) ─► distill ─► skills/<id>-skill/persona/{rules,cases,profile}.md
                                                                                                                             │
行情(新浪/东财/腾讯) ─► downloads/quotes/daily(JSON) ─┐                                                                     ▼
                                                      ├─► facts.mjs ─► 决策链(claude -p) ─► 计划单 ─► 撮合 ─► 账本 ─► 净值 ─► report.html
行情快照 ─► downloads/market/<日期>/*.jsonl ─► investment_market(security_master / kline_day / adjustment_factor / kline_minute / call_auction / watchlist_info)   (下一步: kline.mjs 以行情库为第一数据源)
决策链运行目录 results/<skill>_chain/{live|asof}-<日期>/ ─► investment_tool.chain_*(索引, inv-ui 链路追踪的数据底座)
```

# 🏗️ Project Structure

```
investment-tool
├── inv-admin          # Spring Boot 启动入口、全局配置(application.yml)
├── inv-common         # 公共: BaseEntity、枚举、BusinessException、工具类(DateTime/Json/Collection/Process/TradingDay…)
├── inv-system         # 基础设施: 文件上传、Quartz(sys_job / JobHandler / SchedulerManager)、ProjectConfig
├── inv-stock          # 业务域(cn.sichu.*)
│   ├── cls            # 财联社电报、交易日 md 生成、图片 OCR 交接
│   ├── bilibili       # 复盘视频管线驱动(bilibili_video 状态机: 每日发现 DAILY / 补跑登记 BACKFILL 分队列) + 对账
│   ├── tzzb           # 同花顺投资账本抓取与同步
│   ├── paper          # paper 模拟盘 handler(决策链 / 撮合 / 日终 / 复盘) + 链路入库(chain_*)
│   ├── market         # 行情库: 收盘流水线 / 对账补采 / 竞价 / 外围 / 历史回补入库
│   ├── reconcile      # 对账结果(reconcile_result, 行情库与 B 站管线共用)
│   ├── notify         # hermes 微信推送
│   ├── ocr / download / calc
├── sql
│   ├── investment_tool/     # 业务表(一表一文件)
│   └── investment_market/   # 行情表 + partition/kline_minute_partition.sql
├── scripts            # 按域分目录的脚本, 完整用法见 scripts/README.md
│   ├── market/        # 行情采集: collect_daily / refresh_factors / collect_minute / collect_auction / collect_global / backfill_history
│   ├── lib/           # 公共模块: claude_call.py(无头 claude -p 统一调用: stdin/json 信封/哨兵/schema/成本账本)
│   ├── quotes/        # kline.mjs 多源日线 / indicators.mjs / fetch_quotes.mjs(转债与分时归档)
│   ├── dfcf/paper/    # paper 模拟盘: facts / matcher / report / similarity / scorecard(状态目录不进 git)
│   ├── dfcf/snapshots/# 实盘与 hermes 对话存档(隐私区, 不进 git)
│   ├── chain/   # 决策链驱动 run_chain.py(+ pre_market.py)
│   ├── bilibili/      # fetch_bilibili.mjs + process_video.py
│   ├── backfill_bilibili/ # B 站历史追溯引擎(只在本机跑, 不进 git)
│   ├── tzzb/          # 账本抓取 / md / 复盘 / 画像 / 蒸馏工具
│   ├── cls/           # cls_image_ocr.py + 财联社早报线
│   ├── md/            # md 工具(rules_index、模板迁移、grep_verify)
│   ├── wechat/ hermes/ claude_profile/   # 微信公众号线 / hermes 桥接 / 多 key 轮换
│   ├── scan.mjs       # 市场六榜扫描
│   ├── models/ venv/  # 本地模型与 python 环境(不进 git)
├── skills             # Claude Code skills(主副本; 用 scripts/sync_skills.mjs 同步到 .claude/skills/)
│   ├── taoge-skill / qushitiange-skill / lubenyuan-skill            # B 站 UP 主导师
│   ├── buchitudou0-skill / liuyiqing-skill / …(11 位 tzzb 导师)      # 账本导师
│   ├── control-skill  # 对照组(persona 为空 = 裸模型基准)
│   ├── tzzb-skill / fage-skill / check-cls-md                       # 公共工作流
├── md                 # 每日枢纽: <年>S<季度>/yyyy-MM-dd.md
├── downloads/         # 外部原料(不进 git, 定期物理删除)
├── results/           # 永久产物(视频转写、决策链运行档)
└── docs/TODO.md       # 唯一工作清单
```

> tessdata 训练数据来自: https://github.com/tesseract-ocr/tessdata

# 免责声明

**本程序代码仅供本人学习研究使用，如作他用所承受的法律责任一概与作者无关(下载使用即代表你同意上述观点)。使用者不得干扰或破坏数据来源网站的服务或与服务相连的服务器和网络，且本程序不对您构成任何投资建议，据此操作，风险自担。**
