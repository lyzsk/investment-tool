-- investment_market.kline_minute definition

CREATE TABLE `kline_minute` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `symbol` varchar(16) NOT NULL COMMENT '见 security_master.symbol',
  `trade_date` date NOT NULL COMMENT '交易日(分区键)',
  `bar_time` datetime(0) NOT NULL COMMENT '分钟 K 时刻(日期+时分秒, 秒恒为 0): 09:30(含开盘集合竞价撮合量)+09:31~11:30+13:01~15:00 共 241 根; 以采集脚本实测口径为准, 全表统一',
  `open` decimal(14,4) NOT NULL COMMENT '开(不复权)',
  `high` decimal(14,4) NOT NULL COMMENT '高(不复权)',
  `low` decimal(14,4) NOT NULL COMMENT '低(不复权)',
  `close` decimal(14,4) NOT NULL COMMENT '收(不复权)',
  `volume` bigint DEFAULT NULL COMMENT '本分钟成交量(股; 转债=张), 非累计——源给累计量须差分后入库',
  `amount` decimal(20,2) DEFAULT NULL COMMENT '本分钟成交额(元), 非累计',
  `avg_price` decimal(14,4) DEFAULT NULL COMMENT '分时均价线(当日累计额/累计量), 黄线; 指数 NULL',
  `source` varchar(10) NOT NULL COMMENT '数据源 tdx/dfcf/tencent/sina',
  `status` tinyint DEFAULT '0' COMMENT '0-成功, 1-失败',
  `create_by` bigint DEFAULT NULL,
  `create_time` datetime(6) DEFAULT NULL,
  `update_by` bigint DEFAULT NULL,
  `update_time` datetime(6) DEFAULT NULL,
  `is_deleted` tinyint DEFAULT '0' COMMENT '0-未删除, 1-已删除',
  `delete_by` bigint DEFAULT NULL,
  `delete_time` datetime(6) DEFAULT NULL,
  `remark` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`id`, `trade_date`),
  KEY `idx_symbol_date` (`symbol`, `trade_date`) COMMENT '普通索引(非唯一): 按标的+日期取当日分时; 对增删改写法无影响'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
