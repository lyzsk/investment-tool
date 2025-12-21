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

# 🌐 Environment

-   Java 17
-   SpringBoot3.3.4
-   MyBatis-Plus 3.5.7
-   MySQL 8.0.28

# ✨ Features

-   [x] 申购/赎回交易自动记账: 根据输入值(买入交易: 基金代码, 金额, 交易申请日, 交易平台; 卖出交易: 基金代码, 份额, 交易申请日, 交易平台), 自动推算交易所属日/交易确认日/交易到账日/手续费/净值/份额/交易状态等
-   [x] 自动更新持仓数据: 合计金额/合计手续费/持仓份额/持有天数, 每日 00:00 更新交易状态和对应数据, 每日 20:00 - 23:00 每小时自动爬取数据更新净值
-   [x] 根据 template 自动导出 excel: 交易账单工作簿, 交易分析工作簿
-   [ ] 交易自动计算收益, 自动分析
-   [x] OCR 识别图片转化为数据和表格

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

# 免责声明

**本程序代码仅供本人学习研究使用，如作他用所承受的法律责任一概与作者无关(下载使用即代表你同意上述观点)。使用者不得干扰或破坏数据来源网站的服务或与服务相连的服务器和网络，且本程序不对您构成任何投资建议，据此操作，风险自担。**
