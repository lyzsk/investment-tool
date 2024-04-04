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

# environment

JDK17 + SpringBoot3.2.3 + MySQL 8.0.28

# Disclaimer

**The program code is provided for my personal learning and research purposes only. The author bears no legal responsibility for any other use (downloading and using it implies your agreement with the above statement). Users are not allowed to interfere with or disrupt the services of the data source website or the servers and networks connected to the service. Additionally, this program does not constitute any investment advice for you. Any actions taken based on it are at your own risk.**

# Quick Start

## step1

create mysql table using: `/sql/tables.sql`

## step2

```cmd
mvn clean install
mvn package spring-boot:repackage
```

run `/start.bat`

> Note: change `start.bat` `JAVA_HOME` to your local path

## step3

enjoy the shit code with no ui design, just postman/browser visit controllers api.

# Features

-   [x] Automatic accounting for purchase/redemption transactions: Based on input values (purchase transaction: fund code, amount, transaction application date, trading platform; redemption transaction: fund code, shares, transaction application date, trading platform), automatically calculate the transaction date/trade confirmation date/funds arrival date/transaction fees/net asset value/shares/trading status/etc.
-   [x] Automatic update of holding data: total amount/total fee/holding share/holding days, update trading status and corresponding data daily at 00:00, automatically crawl data to update net asset value every hour from 20:00 to 23:00 daily.
-   [x] Automatically export Excel based on template: Trading statement workbook, trading analysis workbook.
-   [ ] Automatically calculate profits for transactions, automatic analysis.
