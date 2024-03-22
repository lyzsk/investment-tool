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

# environment

JDK17 + SpringBoot3.2.3

# Quick Start

no ui design, just postman/browser visit controllers api.

# Features

-   [x] 买入交易自动记账: 根据输入值(基金代码, 金额, 交易申请日, 交易平台), 自动推算交易所属日/交易确认日/交易到账日/手续费/净值/份额/交易状态(日期计算只涵盖中国交易日, 未涉及 QDII 基金)
-   [x] 自动更新持仓数据: 合计金额/合计手续费/持仓份额/持有天数, 每天 09:30 更新交易状态, 20:00 - 23:00 每小时自动爬取数据更新历史净值
-   [ ] 卖出交易自动记账
-   [ ] 交易自动计算收益, 自动分析
-   [ ] 根据 template 自动导出 excel: 所有交易账单, 交易分析
