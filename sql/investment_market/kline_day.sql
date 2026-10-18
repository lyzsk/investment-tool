-- investment_market.kline_day definition

CREATE TABLE `kline_day` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `symbol` varchar(16) NOT NULL COMMENT '见 security_master.symbol',
  `trade_date` date NOT NULL COMMENT '交易日(外围品种=当地交易日)',
  `open` decimal(14,4) NOT NULL COMMENT '开盘价(不复权)',
  `high` decimal(14,4) NOT NULL COMMENT '最高价(不复权)',
  `low` decimal(14,4) NOT NULL COMMENT '最低价(不复权)',
  `close` decimal(14,4) NOT NULL COMMENT '收盘价(不复权)',
  `pre_close` decimal(14,4) DEFAULT NULL COMMENT '昨收(不复权)。除权除息日=交易所公布的除权参考价, 不等于上一行 close——涨跌幅/涨跌停一律按它算',
  `volume` bigint DEFAULT NULL COMMENT '成交量: 股票/ETF/指数=股(源给"手"则×100入库, 杜绝手/股混用), 转债=张; 外围品种按源原值',
  `amount` decimal(20,2) DEFAULT NULL COMMENT '成交额(元; 港股=港元, 外围=当地货币)',
  `turnover_rate` decimal(10,4) DEFAULT NULL COMMENT '换手率(%); 指数/板块/外围 NULL',
  `limit_up` decimal(14,4) DEFAULT NULL COMMENT '涨停价(不复权); 指数/板块/港股/外围 NULL; 源不给则采集脚本按 security_master.board_type 与当日规则算',
  `limit_down` decimal(14,4) DEFAULT NULL COMMENT '跌停价(不复权); 同上',
  `source` varchar(10) NOT NULL COMMENT '数据源 dfcf/sina/tencent/tdx/baostock(多源切换留痕, 出问题可追)',
  `status` tinyint DEFAULT '0' COMMENT '0-成功, 1-失败',
  `create_by` bigint DEFAULT NULL,
  `create_time` datetime(6) DEFAULT NULL,
  `update_by` bigint DEFAULT NULL,
  `update_time` datetime(6) DEFAULT NULL,
  `is_deleted` tinyint DEFAULT '0' COMMENT '0-未删除, 1-已删除',
  `delete_by` bigint DEFAULT NULL,
  `delete_time` datetime(6) DEFAULT NULL,
  `remark` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_symbol_date` (`symbol`, `trade_date`) COMMENT '普通索引(非唯一): 按标的+日期查 K 线; 对增删改写法无影响'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
