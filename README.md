**[简体中文](README.zh-CN.md) | English**

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

> **_If you like this project or it helps you in some way, don't forget to star._** :star:

A personal A-share research & paper-trading system: Spring Boot + Quartz drives daily data collection (CLS telegraphs, Bilibili review videos, TongHuaShun investment ledgers, market quotes), Claude Code skills distill each mentor's trading rules from that corpus, and a multi-skill decision chain trades paper accounts that are scored against the mentors' real ledgers.

# 🌐 Environment

- Java 17 / Spring Boot 3.3.4 / MyBatis-Plus 3.5.7 / Quartz
- MySQL 8.0 — two databases on one instance: `investment_tool` (business) + `investment_market` (market data)
- Node.js 24 (collectors, chain harness, paper matcher/report)
- Python 3.13 venv at `scripts/venv/` (ASR / VLM / OCR / tzzb tools)
- Claude Code (skills + headless `claude -p` decision chains); optional local ollama (qwen3 / bge-m3)

# ✨ Features

- [x] **Quartz job system** — jobs managed in `sys_job` (cron, misfire policy, run-once, pause/resume), async run log in `sys_job_log`
- [x] **CLS telegraphs** — red telegraphs every 5 min into the daily md; mid-day/close review & limit-up images OCR'd into md sections (`scripts/cls/cls_image_ocr.py`)
- [x] **Daily markdown** — `md/<year>S<quarter>/yyyy-MM-dd.md` generated from template every trading day; it is the information hub every skill reads first
- [x] **Bilibili review-video pipeline** — discover → download → ASR (faster-whisper) → name correction → frame OCR + Qwen2.5-VL-7B vision → `results/bilibili/<mid>/<date>/` (taoge / 趋势天哥 / 卢本圆)
- [x] **TongHuaShun investment ledgers (tzzb)** — 11+ mentors' trades / NAV / positions into `tzzb_record` + `downloads/tzzb/<ledger>/`
- [x] **Mentor skills** — one Claude skill per mentor (`skills/<id>-skill/persona/{rules,cases,profile}.md`), fed by daily `sum` (corpus → md) and `distill` (md → verified rules) workflows
- [x] **Paper trading (A-line)** — 14 skill accounts + 1 control account; 01→06 decision chain + blind review per slot (07:30 pre-market … 14:35 close), per-minute matcher, EOD NAV, similarity score vs. mentors' real positions, `report.html` (absolute / vs control / vs SSE / vs mentor)
- [x] **Market database** — `investment_market`: daily full-market bars (A-share / CB / ETF / index, raw prices) + ex-date adjustment factors + 1-minute bars and opening/closing call-auction process for a ~300-symbol watchlist + 16 overseas instruments (US indices / China ADRs / HK / A50 & US futures / gold & oil / USDCNH); history backfilled from Tencent bars + Sina factors
- [x] **Reconciliation** — the market DB checks bars/minutes/auctions/factors daily and re-collects gaps automatically (including closes missed while the app was down); the UP-video pipeline is checked per video results → md → distill ledger and `bilibili_video` is synced to the files; results go to `reconcile_result`, gaps are pushed to WeChat via hermes
- [x] **Chain ingestion** — every decision-chain run is parsed into `chain_run / chain_step / chain_decision / chain_decision_rule` right after it finishes (step artifact versions, contracts, final orders, cited rules; files stay the source of truth, tables are an index)
- [x] **hermes (WeChat agent)** — intraday Q&A and pre-market distillation via WeChat; transcripts archived locally (privacy zone)
- [x] Legacy: fund purchase/redemption accounting, Excel export, OCR of holding screenshots

# 🚀 Quick Start

1. Create databases and tables
    ```bash
    # business db
    mysql -uroot -p -e "CREATE DATABASE IF NOT EXISTS investment_tool DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
    for f in sql/investment_tool/*.sql; do mysql -uroot -p investment_tool < $f; done
    # market data db (+ yearly partitions of kline_minute, run after the tables)
    mysql -uroot -p -e "CREATE DATABASE IF NOT EXISTS investment_market DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
    for f in sql/investment_market/*.sql; do mysql -uroot -p investment_market < $f; done
    mysql -uroot -p investment_market < sql/investment_market/partition/kline_minute_partition.sql
    ```
2. `mvn clean install` and `mvn package spring-boot:repackage`
3. Script environments
    ```bash
    npm install                                                   # node collectors / paper tools
    python scripts/fetch_holidays_cn.py                           # inv-common holiday/<year>.json
    # python venv (ASR + VLM + OCR); torch cu124 needs the local wheel, see file header
    python -m venv scripts/venv
    scripts/venv/Scripts/pip install -r scripts/requirements-taoge.txt -r scripts/requirements-cls.txt
    scripts/venv/Scripts/python.exe scripts/bilibili/process_video.py --download-model   # Qwen2.5-VL-7B → scripts/models/
    ```
4. Run `/start.bat` (change `JAVA_HOME` in `start.bat` to your local path)

# 🗓️ Daily Pipeline

## Schedule (trading days; Quartz unless noted)

| Time | Job (handler) | What happens |
|---|---|---|
| 00:00 | `tradingDayMarkdownHandler` | create today's `md/<yyyy>S<q>/<date>.md` from template |
| 00:00 / 03:00 | `downloadCleanupHandler` / `ocrCleanupHandler` | purge raw downloads (bilibili 30d, cls 90d) / processed OCR images |
| every 5 min | `clsRedTelegraphHandler` | CLS red telegraphs → `cls_telegraph` + md; review images → OCR → md sections |
| morning (hermes) | WeChat agent | pre-market distillation (fage line), intraday Q&A |
| 07:30 | `paperChainHandler` ×15 (slot 0915) | full 01→06 chain + blind review for every skill account; ingested into `chain_*` on exit |
| 08:30 | `marketGlobalHandler` | `scripts/market/collect_global.py` → overnight overseas closes (by local trade date) into `kline_day` |
| 09:14 / 14:56 | `marketAuctionHandler` (OPEN / CLOSE) | `scripts/market/collect_auction.py` watchlist call-auction process → `call_auction` |
| 09:27 … 14:35 | `paperChainHandler` (slots 0927/0935/0945/1000/1030/1100/1127/1230/1300/1400/1430/1455) | intraday sub-chains (02→04→06) per each mentor's habitual slots |
| 09:00–14:59 every min | `paperMatchHandler` | match open plans against live quotes → books |
| 15:05 | `paperEodHandler` | EOD: void orders, NAV, similarity, `report.html`, state digest for tomorrow |
| 15:10–23:10 hourly | `tzzbFetchHandler` | fetch mentors' ledgers → `downloads/tzzb/` + `tzzb_record` |
| 15:30 / 16:30 … 23:30, 07:00–22:30 /30min | `bilibiliVideoHandler` ×3 | discover & process new review videos (taoge / 趋势天哥 / 卢本圆) |
| 15:35 | `marketDailyHandler` | close pipeline: `collect_daily.mjs` full-market bars → `refresh_factors.py` ex-date check → `collect_minute.py` watchlist minutes → `investment_market` |
| 16:40 (+3 min after app start) | `marketReconcileHandler` / `MarketStartupRunner` | reconcile the last 10 trading days, re-collect missing bars/minutes → `reconcile_result` |
| 20:00 | `paperReviewHandler` | step 07 post-market review |
| 23:50 | `bilibiliReconcileHandler` | UP-video pipeline reconciliation + `bilibili_video` sync → `reconcile_result` |
| evening (manual) | "check md" in Claude Code | check-cls-md → taoge sum → taoge distill → tzzb sum → tzzb distill → fage T+1 verification |

## Call chain (who calls what)

```
Quartz (sys_job) ──► JobHandler (inv-stock) ──► ProcessUtils.run(node|python script) ──► files ──► Java writes DB
  paperChainHandler ─► scripts/chain/run_chain.py --skill <id> --slot <HHMM>
                           ├─ scripts/dfcf/paper/facts.mjs (scan.mjs six boards + snapshot.mjs quotes + md + rules_index)
                           ├─ claude -p × steps 01..06 + blind  (prompts = skills/<id>-skill/workflows/chain.md)
                           └─ plans → scripts/dfcf/paper/plans/<date>/
  paperMatchHandler ─► scripts/dfcf/paper/matcher.mjs (plans × snapshot.mjs quotes → books)
  paperEodHandler   ─► matcher.mjs --eod → nav / similarity.mjs / report.mjs / daily_digest.mjs
  bilibiliVideoHandler ─► scripts/bilibili/fetch_bilibili.mjs → process_video.py (ASR→correct→OCR→VLM→aggregate)
  tzzbFetchHandler  ─► scripts/tzzb/fetch_tzzb.mjs → TzzbRecordService (JSON → tzzb_record)
  clsRedTelegraphHandler ─► CLS API → ClsTelegraphService → md;  images → scripts/cls/cls_image_ocr.py
  marketDailyHandler ─► MarketPipelineService: collect_daily.mjs (sina → eastmoney fallback) → refresh_factors.py → collect_minute.py (tdx ticks)
                        → MarketImportService;  reconcile / startup catch-up share the same pipeline (one lock), past days via backfill_history.py --day
  marketAuctionHandler / marketGlobalHandler ─► collect_auction.py / collect_global.py → MarketImportService
  paperChainHandler exit ─► ChainIngestService (run dir → chain_*);  reconcile handlers ─► reconcile_result + hermes push
Claude Code (evening) ─► skills: check-cls-md / <id>-skill sum & distill / tzzb-skill / fage-skill
```

## Data flow

```
external sources                 raw (downloads/, gitignored)          results / md (permanent)                     knowledge & decisions
CLS API + images      ───────►  downloads/cls/<date>/            ───►  md/<yyyy>S<q>/<date>.md  ─┐
Bilibili videos       ───────►  downloads/bilibili/<mid>/<date>/ ───►  results/bilibili/<mid>/<date>/ (txt + vision.json) ─► sum ─┤
TongHuaShun ledgers   ───────►  downloads/tzzb/<ledger>/  + tzzb_record ──────────────────────────────────────────────► sum ─┤
WeChat articles(hermes)──────►  downloads/wechat/, cls_zaobao/ ────────────────────────────────────────────────────────► spec ┤
                                                                                                                             ▼
                                                              md (daily hub) ─► distill ─► skills/<id>-skill/persona/{rules,cases,profile}.md
                                                                                                                             │
quotes (sina/eastmoney/tencent) ─► downloads/quotes/daily (JSON) ─┐                                                          ▼
                                                                  ├─► facts.mjs ─► chain (claude -p) ─► plans ─► matcher ─► books ─► nav ─► report.html
quotes snapshot ─► downloads/market/<date>/*.jsonl ─► investment_market (security_master / kline_day / adjustment_factor / kline_minute / call_auction / watchlist_info)   (next: kline.mjs reads the DB first)
chain run dirs results/<skill>_chain/{live|asof}-<date>/ ─► investment_tool.chain_* (index; data layer for the inv-ui chain trace page)
```

# 🏗️ Project Structure

```
investment-tool
├── inv-admin          # Spring Boot entry, global config (application.yml)
├── inv-common         # shared: BaseEntity, enums, BusinessException, utils (DateTime/Json/Collection/Process/TradingDay…)
├── inv-system         # infrastructure: file upload, Quartz (sys_job / JobHandler / SchedulerManager), ProjectConfig
├── inv-stock          # business domains (cn.sichu.*)
│   ├── cls            # CLS telegraphs, daily md generation, image OCR hand-off
│   ├── bilibili       # review-video pipeline driver (bilibili_video state machine: DAILY / BACKFILL queues) + reconciliation
│   ├── tzzb           # TongHuaShun ledger fetch & sync
│   ├── paper          # paper-trading handlers (chain / match / EOD / review) + chain ingestion (chain_*)
│   ├── market         # market DB: close pipeline / reconcile & catch-up / auctions / overseas / history import
│   ├── reconcile      # reconciliation results (reconcile_result, shared by market DB and the video pipeline)
│   ├── notify         # hermes WeChat push
│   ├── ocr / download / calc
├── sql
│   ├── investment_tool/     # business tables (one table per file)
│   └── investment_market/   # market tables + partition/kline_minute_partition.sql
├── scripts            # domain-organized scripts — full usage in scripts/README.md
│   ├── market/        # market collectors: collect_daily / refresh_factors / collect_minute / collect_auction / collect_global / backfill_history
│   ├── lib/           # shared modules: claude_call.py (headless claude -p: stdin / json envelope / sentinels / schema / cost ledger)
│   ├── quotes/        # kline.mjs multi-source daily K / indicators.mjs / fetch_quotes.mjs (cb & minute archives)
│   ├── dfcf/paper/    # paper trading: facts / matcher / report / similarity / scorecard (state dirs gitignored)
│   ├── dfcf/snapshots/# real-account & hermes transcripts (privacy zone, gitignored)
│   ├── chain/   # decision-chain harness run_chain.py (+ pre_market.py)
│   ├── bilibili/      # fetch_bilibili.mjs + process_video.py
│   ├── backfill_bilibili/ # historical video backfill engine (local only, gitignored)
│   ├── tzzb/          # ledger fetch / md / review / profile / distill tools
│   ├── cls/           # cls_image_ocr.py + morning-report line
│   ├── md/            # md tools (rules_index, template migration, grep_verify)
│   ├── wechat/ hermes/ claude_profile/   # WeChat line / hermes bridge / multi-key rotation
│   ├── scan.mjs       # market six-board scanner
│   ├── models/ venv/  # local models & python env (gitignored)
├── skills             # Claude Code skills (master copy; sync to .claude/skills/ via scripts/sync_skills.mjs)
│   ├── taoge-skill / qushitiange-skill / lubenyuan-skill            # Bilibili UP mentors
│   ├── buchitudou0-skill / liuyiqing-skill / … (11 tzzb mentors)     # ledger mentors
│   ├── control-skill  # control group (empty persona = bare-model baseline)
│   ├── tzzb-skill / fage-skill / check-cls-md                       # shared workflows
├── md                 # daily hub: <year>S<quarter>/yyyy-MM-dd.md
├── downloads/         # raw external material (gitignored, auto-purged)
├── results/           # permanent pipeline outputs (video transcripts, chain runs)
└── docs/TODO.md       # the single work list
```

> tessdata: https://github.com/tesseract-ocr/tessdata

# Disclaimer

**The program code is provided for my personal learning and research purposes only. The author bears no legal responsibility for any other use (downloading and using it implies your agreement with the above statement). Users are not allowed to interfere with or disrupt the services of the data source website or the servers and networks connected to the service. Additionally, this program does not constitute any investment advice for you. Any actions taken based on it are at your own risk.**
