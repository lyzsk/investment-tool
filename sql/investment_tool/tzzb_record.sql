-- investment_tool.tzzb_record definition

CREATE TABLE `tzzb_record` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `ledger` varchar(50) NOT NULL COMMENT '账本标识',
  `record_type` varchar(20) NOT NULL COMMENT 'trade(调仓流水)/nav_day(日净值)/position_snap(持仓快照)/bs_leg(逐笔买卖腿, change_bs端点撞通后启用)',
  `record_time` datetime NOT NULL COMMENT '业务时间: trade=trans_date, nav_day=净值日15:00, position_snap=抓取时刻, bs_leg=成交时间(响应无时分秒则当日15:00)',
  `stock_code` varchar(10) DEFAULT NULL COMMENT '标的代码',
  `stock_name` varchar(50) DEFAULT NULL COMMENT '标的名称',
  `side` varchar(10) DEFAULT NULL COMMENT 'trade=buy_sell操作类型原值(0=不变 1=加仓 2=减仓 3=建仓 4=清仓 5=小幅加仓 6=小幅减仓 7=大幅加仓 8=大幅减仓 9=做T); bs_leg=买入/卖出',
  `price` decimal(12,4) DEFAULT NULL COMMENT '成交均价(trade=trans_price 4位小数, bs_leg=avg价)',
  `qty` decimal(20,4) DEFAULT NULL COMMENT 'trans_count(分享视图全空→NULL, 原值在 payload)',
  `amount` decimal(20,4) DEFAULT NULL COMMENT 'trans_amount(分享视图全空→NULL, 原值在 payload)',
  `daily_return_pct` decimal(10,4) DEFAULT NULL COMMENT 'nav_day 日收益率%(index链算=当日/前日-1; 原始json无逐日字段)',
  `payload_json` json DEFAULT NULL COMMENT '原始字段兜底: op/market/prePositionPercent/aftPositionPercent/totalCost/asset/szzs 等',
  `status` tinyint DEFAULT '0' COMMENT '0-成功, 1-失败',
  `create_by` bigint DEFAULT NULL,
  `create_time` datetime(6) DEFAULT NULL,
  `update_by` bigint DEFAULT NULL,
  `update_time` datetime(6) DEFAULT NULL,
  `is_deleted` tinyint DEFAULT '0' COMMENT '0-未删除, 1-已删除',
  `delete_by` bigint DEFAULT NULL,
  `delete_time` datetime(6) DEFAULT NULL,
  `remark` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
