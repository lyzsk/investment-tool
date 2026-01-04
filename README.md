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

# 🚀 Quick Start

1. create mysql table using: `/sql/tables.sql`
2. `mvn clean install` and `mvn package spring-boot:repackage`
3. run `/start.bat`

> Note: change `start.bat` `JAVA_HOME` to your local path

# 🏗️ Project Structure

```
investment-tool
├── inv-admin          # Main Spring Boot application entry
├── inv-common         # Shared components
├── inv-stock          #
├── inv-system         # Core system services: file upload, Quartz job scheduling
├── sql                # Database initialization scripts
├── uploads/category/yyyy.mm.dd        # Auto generated dirs (organized by date)
└── logs               # Application logs
```

> trained data is from: https://github.com/tesseract-ocr/tessdata

# Disclaimer

**The program code is provided for my personal learning and research purposes only. The author bears no legal responsibility for any other use (downloading and using it implies your agreement with the above statement). Users are not allowed to interfere with or disrupt the services of the data source website or the servers and networks connected to the service. Additionally, this program does not constitute any investment advice for you. Any actions taken based on it are at your own risk.**

TODO:

任务一: https://www.cls.cn/nodeapi/updateTelegraphList 的定时爬虫(先做每天 15:00-15:30 的定时任务, 每 5 分钟爬一次), 如果 title 出现关键词: "收评："和"xx 月 xx 日涨停分析", 则下载图片(收评只有一张图, 涨停分析只要第一张图)到 uploads/cls/yyyy.mm.dd/ 目录下(category 标记为 cls)
任务二: 通过另一个服务作为任务一的扩展, 将下载的图片上传图片到 file_upload 数据库中, 然后添加 category=ocr, 然后走 ocr 服务到 ocr_image 和 ocr_result 中,
