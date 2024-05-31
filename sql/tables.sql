CREATE DATABASE `investment_tool` /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci */ /*!80016 DEFAULT ENCRYPTION='N' */;

-- investment_tool.fund_eastmoney_jjjz definition

CREATE TABLE `fund_eastmoney_jjjz` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `code` varchar(6) DEFAULT NULL COMMENT '基金代码, 6位',
  `callback` varchar(100) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=31 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='https://fundf10.eastmoney.com/jjjz_{code}.html';


-- investment_tool.fund_history_nav definition

CREATE TABLE `fund_history_nav` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `code` varchar(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '基金代码, 6位',
  `nav_date` date DEFAULT NULL COMMENT '净值日期',
  `nav` varchar(100) DEFAULT NULL COMMENT '单位净值, 4位小数',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=3629 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


-- investment_tool.fund_information definition

CREATE TABLE `fund_information` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `code` varchar(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '基金代码, 6位',
  `short_name` varchar(100) DEFAULT NULL COMMENT '基金简称',
  `full_name` varchar(100) DEFAULT NULL COMMENT '基金全称',
  `company_name` varchar(100) DEFAULT NULL COMMENT '基金公司',
  `purchase_confirmation_process` int DEFAULT NULL COMMENT '买入份额确认T+N',
  `redemption_confirmation_process` int DEFAULT NULL COMMENT '卖出份额确认T+N',
  `redemption_settlement_process` int DEFAULT NULL COMMENT '卖出份额确认T+N',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=24 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


-- investment_tool.fund_position definition

CREATE TABLE `fund_position` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `code` varchar(6) DEFAULT NULL COMMENT '基金代码, 6位',
  `transaction_date` date DEFAULT NULL COMMENT '交易所属日',
  `initiation_date` date DEFAULT NULL COMMENT '开始持仓日期, 即交易表中的到账日期',
  `redemption_date` date DEFAULT NULL COMMENT '赎回交易日',
  `total_principal_amount` decimal(14,2) DEFAULT NULL COMMENT '合计本金金额, 2位小数',
  `total_amount` decimal(14,2) DEFAULT NULL COMMENT '合计金额, 2位小数',
  `total_purchase_fee` decimal(14,2) DEFAULT NULL COMMENT '合计买入手续费, 2位小数',
  `total_redemption_fee` decimal(14,2) DEFAULT NULL COMMENT '合计赎回手续费, 2位小数',
  `held_share` decimal(14,2) DEFAULT NULL COMMENT '合计持仓份额, 2位小数',
  `held_days` int DEFAULT NULL COMMENT '持有天数',
  `update_date` date DEFAULT NULL COMMENT '更新日期, by day',
  `trading_platform` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '交易平台',
  `status` int DEFAULT NULL COMMENT '状态, 0:买入在途purchase_in_transit, 1:持仓held, 2:赎回在途redemption_in_transit, 3:未全额赎回partially_redeemed, 4:已赎回redeemed, 5.现金分红cash_dividend',
  `mark` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '标注, 交易所属日-赎回交易日, 格式: startDate->endDate (yyyy-MM-dd)',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=615 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


-- investment_tool.fund_purchase_fee_rate definition

CREATE TABLE `fund_purchase_fee_rate` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `code` varchar(6) DEFAULT NULL COMMENT '基金代码, 6位',
  `purchase_fee_rate_change_amount` bigint DEFAULT NULL COMMENT '<该金额',
  `purchase_fee_rate` varchar(100) DEFAULT NULL COMMENT '申购费率%, 2位小数',
  `trading_platform` varchar(100) DEFAULT NULL COMMENT '交易平台',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=66 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


-- investment_tool.fund_redemption_fee_rate definition

CREATE TABLE `fund_redemption_fee_rate` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `code` varchar(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '基金代码, 6位',
  `redemption_fee_rate_change_days` int DEFAULT NULL COMMENT '<该天数',
  `redemption_fee_rate` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '赎回费率%, 3位小数',
  `trading_platform` varchar(100) DEFAULT NULL COMMENT '交易平台',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=70 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


-- investment_tool.fund_transaction definition

CREATE TABLE `fund_transaction` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `code` varchar(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '基金代码, 6位',
  `application_date` date DEFAULT NULL COMMENT '交易申请日',
  `transaction_date` date DEFAULT NULL COMMENT '交易归属日',
  `confirmation_date` date DEFAULT NULL COMMENT '交易确认日',
  `settlement_date` date DEFAULT NULL COMMENT '交易到账日',
  `amount` decimal(14,2) DEFAULT NULL COMMENT '交易金额, 2位小数',
  `fee` decimal(14,2) DEFAULT NULL COMMENT '手续费, 2位小数',
  `nav` decimal(16,4) DEFAULT NULL COMMENT '单位净值, 4位小数',
  `share` decimal(14,2) DEFAULT NULL COMMENT '份额, 2位小数',
  `dividend_amount_per_share` decimal(16,4) DEFAULT NULL COMMENT '每股分红金额, 4位小数',
  `trading_platform` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '交易平台',
  `status` int DEFAULT NULL COMMENT '状态, 0:买入在途purchase_in_transit, 1:持仓held, 2:赎回在途redemption_in_transit, 3:未全额赎回partially_redeemed, 4:已赎回redeemed, 5.现金分红cash_dividend',
  `mark` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '标记',
  `type` int DEFAULT NULL COMMENT '交易类型, 0:purchase, 1:redemption, 2:dividend',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=689 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


-- investment_tool.stock_transaction_analysis definition

CREATE TABLE `stock_transaction_analysis` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `code` varchar(6) DEFAULT NULL COMMENT '股票代码, 6位',
  `buy_time` datetime DEFAULT NULL COMMENT '买入时间, yyyy-MM-dd hh:mm:ss',
  `sell_time` datetime DEFAULT NULL COMMENT '卖出时间, yyyy-MM-dd hh:mm:ss',
  `share` bigint DEFAULT NULL COMMENT '份额, 必为100的倍数',
  `buying_price` decimal(15,3) DEFAULT NULL COMMENT '买入价格, 3位小数',
  `buying_fee` decimal(14,2) DEFAULT NULL COMMENT '买入手续费, 2位小数',
  `selling_price` decimal(15,3) DEFAULT NULL COMMENT '卖出价格, 3位小数',
  `selling_fee` decimal(14,2) DEFAULT NULL COMMENT '卖出手续费, 2位小数',
  `total_fee` decimal(14,2) DEFAULT NULL COMMENT '合计手续费, 2位小数',
  `held_days` int DEFAULT NULL COMMENT '持有天数, 仅计算交易日',
  `profit` decimal(14,2) DEFAULT NULL COMMENT '净收益, 2位小数',
  `yield_rate` varchar(7) DEFAULT NULL COMMENT '收益率, 2位小数百分号结尾的字符串',
  `trading_platform` varchar(100) DEFAULT NULL COMMENT '交易平台',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


-- investment_tool.stock_information definition

CREATE TABLE `stock_information` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `code` varchar(6) DEFAULT NULL COMMENT '股票代码, 6位数字',
  `name` varchar(100) DEFAULT NULL COMMENT '股票名称',
  `company_name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '公司名称',
  `industry` varchar(100) DEFAULT NULL COMMENT '所属行业',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;