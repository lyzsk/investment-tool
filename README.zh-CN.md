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

-   Java 17
-   SpringBoot3.3.4
-   MyBatis-Plus 3.5.7
-   MySQL 8.0.28

# Features

-   [x] 申购/赎回交易自动记账: 根据输入值(买入交易: 基金代码, 金额, 交易申请日, 交易平台; 卖出交易: 基金代码, 份额, 交易申请日, 交易平台), 自动推算交易所属日/交易确认日/交易到账日/手续费/净值/份额/交易状态等
-   [x] 自动更新持仓数据: 合计金额/合计手续费/持仓份额/持有天数, 每日 00:00 更新交易状态和对应数据, 每日 20:00 - 23:00 每小时自动爬取数据更新净值
-   [x] 根据 template 自动导出 excel: 交易账单工作簿, 交易分析工作簿
-   [ ] 交易自动计算收益, 自动分析
-   [x] OCR 识别图片转化为数据和表格

# Quick Start

1. create mysql table using: `/sql/tables.sql`
2. `mvn clean install` and `mvn package spring-boot:repackage`
3. run `/start.bat`

> Note: change `start.bat` `JAVA_HOME` to your local path

# structure

```
investment-tool
│   .gitignore
│   LICENSE
│   pom.xml
│   README.md
│   README.zh-CN.md
│
├───inv-admin
│   │   pom.xml
│   │
│   ├───src
│   │   └───main
│   │       ├───java
│   │       │   └───cn
│   │       │       └───sichu
│   │       │               Application.java
│   │       │
│   │       └───resources
│   │               application.yml
│   │               banner.txt
│
├───inv-common
│   │   pom.xml
│   │
│   ├───src
│   │   └───main
│   │       ├───java
│   │       │   ├───base
│   │       │   │       BaseEntity.java
│   │       │   │
│   │       │   ├───config
│   │       │   │       ProjectConfig.java
│   │       │   │
│   │       │   ├───enums
│   │       │   │       BusinessStatus.java
│   │       │   │       ProcessStatus.java
│   │       │   │       TableLogic.java
│   │       │   │
│   │       │   ├───exception
│   │       │   │       BusinessException.java
│   │       │   │       GlobalExceptionHandler.java
│   │       │   │       UtilException.java
│   │       │   │
│   │       │   ├───result
│   │       │   │       IResultCode.java
│   │       │   │       PageResult.java
│   │       │   │       Result.java
│   │       │   │       ResultCode.java
│   │       │   │
│   │       │   └───utils
│   │       │       │   CollectionUtils.java
│   │       │       │   IdUtils.java
│   │       │       │   StringUtils.java
│   │       │       │
│   │       │       └───file
│   │       │               FileTypeUtils.java
│   │       │               FileUploadUtils.java
│   │       │               FileUtils.java
│   │       │               MimeTypeUtils.java
│
├───inv-stock
│   │   pom.xml
│   │
│   ├───src
│   │   └───main
│   │       ├───java
│   │       │   └───cn
│   │       │       └───sichu
│   │       │           └───ocr
│   │       │               ├───controller
│   │       │               │       OcrImageController.java
│   │       │               │
│   │       │               ├───entity
│   │       │               │       OcrImage.java
│   │       │               │       OcrResult.java
│   │       │               │
│   │       │               ├───init
│   │       │               │       TessdataExtractor.java
│   │       │               │
│   │       │               ├───mapper
│   │       │               │       OcrImageMapper.java
│   │       │               │       OcrResultMapper.java
│   │       │               │
│   │       │               └───service
│   │       │                   │   IOcrImageService.java
│   │       │                   │   IOcrProcessService.java
│   │       │                   │   ITesseractOcrService.java
│   │       │                   │
│   │       │                   └───impl
│   │       │                           OcrImageServiceImpl.java
│   │       │                           OcrProcessServiceImpl.java
│   │       │                           TesseractTesseractOcrServiceImpl.java
│   │       │
│   │       └───resources
│   │           ├───mapper
│   │           │       OcrImageMapper.xml
│   │           │       OcrResultMapper.xml
│   │           │
│   │           └───tessdata
│   │                   chi_sim.traineddata
├───inv-system
│   │   pom.xml
│   │
│   ├───src
│   │   └───main
│   │       ├───java
│   │       │   └───cn
│   │       │       └───sichu
│   │       │           └───system
│   │       │               ├───controller
│   │       │               │       FileUploadController.java
│   │       │               │
│   │       │               ├───entity
│   │       │               │       FileUpload.java
│   │       │               │
│   │       │               ├───mapper
│   │       │               │       FileUploadMapper.java
│   │       │               │
│   │       │               └───service
│   │       │                   │   IFileUploadService.java
│   │       │                   │
│   │       │                   └───impl
│   │       │                           FileUploadServiceImpl.java
│   │       │
│   │       └───resources
│   │           └───mapper
│   │                   FileUploadMapper.xml
|
└───sql ### sql scripts
```

> trained data is from: https://github.com/tesseract-ocr/tessdata

# 免责声明

**本程序代码仅供本人学习研究使用，如作他用所承受的法律责任一概与作者无关(下载使用即代表你同意上述观点)。使用者不得干扰或破坏数据来源网站的服务或与服务相连的服务器和网络，且本程序不对您构成任何投资建议，据此操作，风险自担。**
