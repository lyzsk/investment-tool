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

-   Java 17
-   SpringBoot3.3.4
-   MyBatis-Plus 3.5.7
-   MySQL 8.0.28

# ✨ Features

-   [x] Automatic accounting for purchase/redemption transactions: Based on input values (purchase transaction: fund code, amount, transaction application date, trading platform; redemption transaction: fund code, shares, transaction application date, trading platform), automatically calculate the transaction date/trade confirmation date/funds arrival date/transaction fees/net asset value/shares/trading status/etc.
-   [x] Automatic update of holding data: total amount/total fee/holding share/holding days, update trading status and corresponding data daily at 00:00, automatically crawl data to update net asset value every hour from 20:00 to 23:00 daily.
-   [x] Automatically export Excel based on template: Trading statement workbook, trading analysis workbook.
-   [x] OCR Image-to-Data Conversion  
         Upload screenshots of fund holdings → extract structured data via Tesseract OCR (Chinese support).
-   [x] Quartz-Based Scheduled Task System
    -   Unified job management via database (`sys_job`)
    -   Dynamic Cron expression validation
    -   Configurable misfire policies (ignore/fire/do nothing)
    -   Asynchronous job log recording (`sys_job_log`)
    -   Supports immediate trigger, pause/resume, and update/delete
    -   Example: Auto-cleanup of processed OCR images
-   [x] auto fetch cls telegraphs into `cls_telegraph` and download important daily imgs into disk

# 🚀 Quick Start

1. create mysql table using: `/sql/tables.sql`
2. `mvn clean install` and `mvn package spring-boot:repackage`
3. run `/start.bat`

> Note: change `start.bat` `JAVA_HOME` to your local path

# 🏗️ Project Structure

```
investment-tool
├── inv-admin          # Main application entry: Spring Boot startup class, global configuration, web controllers
├── inv-common         # Shared utilities: helper classes, constants, exception handling, response wrappers, etc.
├── inv-stock          # Stock-related data features
│   ├── cls            # CaiLianShe (CLS) telegraph fetching and parsing
│   └── ocr            # Image OCR recognition (for parsing daily limit-up analysis / market close summaries)
├── inv-system         # System infrastructure services
│   ├── file           # File upload and storage management
│   └── quartz         # Scheduled job execution (e.g., daily automated data fetching)
├── sql                # Database initialization and migration scripts
├── uploads            # User- or system-uploaded files (auto-organized by date)
│   └── category/yyyy-MM-dd
├── downloads          # Automatically downloaded external resources
│   └── cls/yyyy-MM-dd # CLS telegraph images (grouped by date)
├── stock              # Daily auto-generated stock analysis reports (Markdown)
│   └── yyyy-MM-dd.md
└── logs               # Application runtime logs
```

> trained data is from: https://github.com/tesseract-ocr/tessdata

# Disclaimer

**The program code is provided for my personal learning and research purposes only. The author bears no legal responsibility for any other use (downloading and using it implies your agreement with the above statement). Users are not allowed to interfere with or disrupt the services of the data source website or the servers and networks connected to the service. Additionally, this program does not constitute any investment advice for you. Any actions taken based on it are at your own risk.**
