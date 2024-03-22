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

JDK17 + SpringBoot3.2.3

# Quick Start

no ui design, just postman/browser visit controllers api.

# Features

-   [x] Automatically record purchase transactions:

    based on input values(code, amount, application date, trading platform), automatically calculate the transaction date/trade confirmation date/settlement date/fees/net asset value/shares/trading status (date calculations only cover Chinese trading days, not involving QDII funds)

-   [x] Automatically update position data:

    total amount/total fees/held share/holding days, update trading status at 09:30 every day, automatically crawl data to update historical net asset value every hour from 20:00 to 23:00 every day

-   [ ] Automatically record sale transactions
-   [ ] Automatically calculate profits from transactions, automatic analysis
-   [ ] Automatically export Excel based on a template:

    including all transaction statements, transaction analysis
