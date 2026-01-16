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

- Java 17
- SpringBoot3.3.4
- MyBatis-Plus 3.5.7
- MySQL 8.0.28
- Python 3.10.16

# ✨ Features

- [x] 申购/赎回交易自动记账: 根据输入值(买入交易: 基金代码, 金额, 交易申请日, 交易平台; 卖出交易: 基金代码, 份额, 交易申请日, 交易平台), 自动推算交易所属日/交易确认日/交易到账日/手续费/净值/份额/交易状态等
- [x] 自动更新持仓数据: 合计金额/合计手续费/持仓份额/持有天数, 每日 00:00 更新交易状态和对应数据, 每日 20:00 - 23:00 每小时自动爬取数据更新净值
- [x] 根据 template 自动导出 excel: 交易账单工作簿, 交易分析工作簿
- [ ] 交易自动计算收益, 自动分析
- [x] OCR 识别图片转化为数据和表格
- [x] 自动抓取财联社电报, 并且下载午评, 午间涨停分析, 收评, 涨停分析图片到本地
- [x] 自动生成 yyyy-MM-dd.md(交易日.md) 并将加红电报写入 md

# 🚀 Quick Start

1. create mysql table using: `/sql/tables.sql`
2. `mvn clean install` and `mvn package spring-boot:repackage`
3. install enviroment for scrips
    ```bash
    cd investment-tool/
    npm init -y
    npm install prettier`
    ```
    ```bash
    cd investment-tool/scripts
    python fetch_holidays_cn.py
    ```
    requirements for fetch_holidays_cn.py: `pip install requests`
4. run `/start.bat`

> Note: change `start.bat` `JAVA_HOME` to your local path

# 🏗️ Project Structure

```
investment-tool
├── inv-admin          # 主应用入口：Spring Boot 启动类、全局配置、Web 控制器
├── inv-common         # 通用模块：工具类、常量、异常处理、响应封装等
├── inv-stock          # 股票数据相关功能
│   ├── cls            # 财联社（CLS）电报抓取与解析, 自动生成yyyy-MM-dd.md(交易日.md)到into investment-tool/stocks/yearAndquarter/ 路径, 自动写入加红电报
│   └── ocr            # 图片 OCR 识别（用于解析涨停分析/收评图片）
├── inv-system         # 系统支撑服务
│   ├── file           # 文件上传、存储管理
│   └── quartz         # 定时任务调度（如每日自动抓取）
├── sql                # 数据库初始化与更新脚本
├── uploads            # 用户或系统上传的文件（按日期自动归档）
│   └── category/yyyy-MM-dd
├── downloads          # 系统自动下载的外部资源
│   └── cls/yyyy-MM-dd # 财联社电报配图（按日期组织）
├── stock              # 每日生成的股票分析 Markdown 报告
├── scripts
│   └── fetch_holidays_cn.py # 自动抓取中国大陆节假日到 inv-common/src/main/resources/holiday/year.json
│   └── format-markdown.mjs # 自动模拟 prettier 格式化 Markdown
│   └── yyyy-MM-dd.md
└── logs               # 应用运行日志
```

> trained data is from: https://github.com/tesseract-ocr/tessdata

# 免责声明

**本程序代码仅供本人学习研究使用，如作他用所承受的法律责任一概与作者无关(下载使用即代表你同意上述观点)。使用者不得干扰或破坏数据来源网站的服务或与服务相连的服务器和网络，且本程序不对您构成任何投资建议，据此操作，风险自担。**
