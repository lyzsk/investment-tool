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

# 🌐 Environment

- Java 17
- SpringBoot3.3.4
- MyBatis-Plus 3.5.7
- MySQL 8.0.28
- Python 3.10.16

# ✨ Features

- [x] Automatic accounting for purchase/redemption transactions: Based on input values (purchase transaction: fund code, amount, transaction application date, trading platform; redemption transaction: fund code, shares, transaction application date, trading platform), automatically calculate the transaction date/trade confirmation date/funds arrival date/transaction fees/net asset value/shares/trading status/etc.
- [x] Automatic update of holding data: total amount/total fee/holding share/holding days, update trading status and corresponding data daily at 00:00, automatically crawl data to update net asset value every hour from 20:00 to 23:00 daily.
- [x] Automatically export Excel based on template: Trading statement workbook, trading analysis workbook.
- [x] OCR Image-to-Data Conversion  
       Upload screenshots of fund holdings → extract structured data via Tesseract OCR (Chinese support).
- [x] Quartz-Based Scheduled Task System
    - Unified job management via database (`sys_job`)
    - Dynamic Cron expression validation
    - Configurable misfire policies (ignore/fire/do nothing)
    - Asynchronous job log recording (`sys_job_log`)
    - Supports immediate trigger, pause/resume, and update/delete
    - Example: Auto-cleanup of processed OCR images
- [x] auto fetch cls telegraphs and download wuPing, wuJianZhangTingAnalysis, shouPing, zhangTingAnalysis images into disk
- [x] auto generate yyyy-MM-dd.md(tradingday.md) and write red telegraph into md

# 🚀 Quick Start

1. create mysql table using: `/sql/tables.sql`
2. `mvn clean install` and `mvn package spring-boot:repackage`
3. install enviroment for scripts
    ```bash
    cd investment-tool/
    npm init -y
    npm install prettier`
    ```
    requirements for fetch_holidays_cn.py: `pip install requests`
    requirements for cls/cls_image_ocr.py: `pip install -r scripts/requirements-cls.txt`
    requirements for 桃哥管线 ASR+7B(bilibili/process_video.py): create venv at `scripts/venv/`, then `pip install -r scripts/requirements-taoge.txt`(torch cu124 需先装本地 wheel, 见文件头注释)
    download Qwen2.5-VL-7B into `scripts/models/`: `scripts/venv/Scripts/python.exe scripts/bilibili/process_video.py --download-model`
    ```bash
    cd investment-tool/
    python scripts/fetch_holidays_cn.py
    ```
4. run `/start.bat`

> Note: change `start.bat` `JAVA_HOME` to your local path

# 🏗️ Project Structure

```
investment-tool
├── inv-admin          # Main application entry: Spring Boot startup class, global configuration, web controllers
├── inv-common         # Shared utilities: helper classes, constants, exception handling, response wrappers, etc.
├── inv-stock          # Stock-related data features
│   ├── cls            # CaiLianShe (CLS) telegraph fetching and parsing, auto generate yyyy-MM-dd.md(tradingday.md) into md/<year>S<quarter>/ dir and write red telegraph into md
│   ├── ocr            # Image OCR recognition (for parsing daily limit-up analysis / market close summaries)
│   ├── bilibili       # Bilibili video pipeline driver (fetch → ASR → name-correction → VLM vision extraction)
│   └── tzzb           # TongHuaShun investment-ledger fetching and sync (convertible-bond master tracking)
├── inv-system         # System infrastructure services
│   ├── file           # File upload and storage management
│   └── quartz         # Scheduled job execution (e.g., daily automated data fetching)
├── sql                # Database initialization and migration scripts
├── uploads            # User- or system-uploaded files (auto-organized by date)
│   └── category/yyyy-MM-dd
├── downloads          # Automatically downloaded external resources (gitignored)
│   ├── cls/yyyy-MM-dd           # CLS telegraph images (grouped by date)
│   ├── bilibili/<mid>/<yyyy.MM.dd>  # video raw material mp4/m4a (auto cleanup after 30 days)
│   ├── tzzb/<ledger>            # investment-ledger raw JSON (evidence layer)
│   ├── wechat/<account>/<yyyy-MM-dd>  # WeChat article raw html/text/meta/spec (fage line)
│   ├── cls_zaobao/<yyyy-MM-dd>  # CLS morning-report article raw/text/meta/spec
│   └── quotes/{cb/{kline,trends},stock/trends} # quotes archive (cb daily/minute, stock minute)
├── results            # Pipeline outputs (permanent)
│   └── bilibili/<mid>/<yyyy.MM.dd>  # corrected transcript + vision.json
├── scripts            # Domain-organized tool scripts, full-chain usage: scripts/README.md
│   ├── scan.mjs               # market six-board scanner (gainers/ladders/limit-down/...)
│   ├── fetch_holidays_cn.py   # auto generate inv-common/src/main/resources/holiday/year.json for Chinese holidays
│   ├── bilibili/              # taoge video pipeline (fetch_bilibili_taoge.mjs + process_video.py)
│   ├── tzzb/                  # convertible-bond master line (ledger fetch / md-gen / review / profile)
│   ├── quotes/                # quotes fetchers (fetch_cb_quotes.mjs cb daily+minute / fetch_stock_trends.mjs stock minute)
│   ├── cls/                   # CLS image OCR (cls_image_ocr.py, called by Java) + morning-report line (fetch_cls_zaobao.mjs)
│   ├── md/                    # markdown tools (format-markdown.mjs prettier / migrate_md_template.mjs / gen_scorecard.mjs)
│   ├── wechat/                # WeChat official-account pre-market line (fetch_wechat.mjs, manual-link entry)
│   ├── backfill_taoge/        # historical backfill daemon (local only, gitignored)
│   ├── models/                # Qwen2.5-VL-7B + name dictionaries (gitignored)
│   └── venv/                  # python environment (gitignored)
├── skills             # Claude Code skills (双副本, 编辑后同步 .claude/skills/)
│   ├── taoge-skill/   # taoge persona (post-market review rules, distilled from verified samples)
│   ├── taoge-sum/     # daily: results transcript -> md taoge section
│   ├── taoge-distill/ # daily: md taoge section -> persona verification & distillation
│   ├── cb-skill/      # convertible-bond master persona (bchitudou0 behavior rules)
│   ├── tzzb-sum/      # daily: ledger legs -> md tzzb section (【推测】 layer)
│   ├── tzzb-distill/  # daily: legs -> cb-skill mechanical review (zero-token)
│   ├── fage-skill/    # fage pre-market line (hermes distills spec / Claude T+1 verification / persona)
│   └── check-cls-md/  # evening routine: review CLS OCR sections against images
├── md                 # Daily auto-generated stock analysis reports (Markdown)
│   └── <year>S<quarter>/yyyy-MM-dd.md
└── logs               # Application runtime logs
```

> trained data is from: https://github.com/tesseract-ocr/tessdata

# Disclaimer

**The program code is provided for my personal learning and research purposes only. The author bears no legal responsibility for any other use (downloading and using it implies your agreement with the above statement). Users are not allowed to interfere with or disrupt the services of the data source website or the servers and networks connected to the service. Additionally, this program does not constitute any investment advice for you. Any actions taken based on it are at your own risk.**
