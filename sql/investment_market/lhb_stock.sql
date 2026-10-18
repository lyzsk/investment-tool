-- investment_market.lhb_stock definition
-- 龙虎榜上榜明细(2026-10-15 建): 一行=东财一条上榜记录(TRADE_ID); 一只票一天可多条(当日口径+连续 3 日累计等), is_primary 标主记录
-- 来源: scripts/lhb/fetch_lhb.mjs 落盘的 downloads/lhb/yyyy.MM.dd/list.json; 入库: LhbImportServiceImpl(按交易日先物理删除再插入, 幂等)

CREATE TABLE `lhb_stock` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `trade_date` date NOT NULL COMMENT '交易日',
  `symbol` varchar(16) NOT NULL COMMENT '见 security_master.symbol(sh/sz/bj+代码)',
  `code` varchar(10) NOT NULL COMMENT '证券代码(6 位)',
  `name` varchar(32) DEFAULT NULL COMMENT '证券简称(上榜当日)',
  `trade_id` bigint NOT NULL COMMENT '东财上榜记录 ID(TRADE_ID), 与 lhb_seat.trade_id 关联',
  `is_primary` tinyint NOT NULL DEFAULT '1' COMMENT '1-主记录(当日口径优先, 只有多日累计榜时取它), 0-同票同日的其他上榜记录; 同 md 总表口径',
  `reason` varchar(200) DEFAULT NULL COMMENT '上榜原因(东财原文 EXPLANATION)',
  `close_price` decimal(14,4) DEFAULT NULL COMMENT '收盘价(不复权)',
  `change_rate` decimal(10,4) DEFAULT NULL COMMENT '涨跌幅(%)',
  `buy_amt` decimal(20,2) DEFAULT NULL COMMENT '龙虎榜买入额(元, 买五卖五席位合计买入)',
  `sell_amt` decimal(20,2) DEFAULT NULL COMMENT '龙虎榜卖出额(元, 买五卖五席位合计卖出)',
  `net_amt` decimal(20,2) DEFAULT NULL COMMENT '龙虎榜净额(元)=买入-卖出',
  `deal_net_ratio` decimal(14,6) DEFAULT NULL COMMENT '净额占当日总成交额比(%)',
  `deal_amount` decimal(20,2) DEFAULT NULL COMMENT '当日总成交额(元, ACCUM_AMOUNT; 多日累计榜=累计期成交额)',
  `turnover_rate` decimal(10,4) DEFAULT NULL COMMENT '换手率(%)',
  `trade_market` varchar(20) DEFAULT NULL COMMENT '市场板块(东财 TRADE_MARKET, 如 深交所创业板)',
  `fetched_at` datetime(0) DEFAULT NULL COMMENT '原始数据抓取时刻(list.json fetched_at, 北京时间); 交易日 18:00 前抓的是临时版不入库',
  `source` varchar(10) NOT NULL COMMENT '数据源 em(东财 datacenter-web)/ths',
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
  KEY `idx_date_symbol` (`trade_date`, `symbol`) COMMENT '普通索引(非唯一): 按日查当日榜单/按日幂等重导',
  KEY `idx_symbol_date` (`symbol`, `trade_date`) COMMENT '普通索引(非唯一): 按标的查上榜历史'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
