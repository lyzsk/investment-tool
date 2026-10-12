-- investment_market.watchlist_info definition

CREATE TABLE `watchlist_info` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `trade_date` date NOT NULL COMMENT '交易日',
  `symbol` varchar(16) NOT NULL COMMENT '见 security_master.symbol',
  `reasons` varchar(100) NOT NULL COMMENT '入选原因标签, 逗号分隔: HOLD,PLAN,POOL,MENTOR,ZT,DT,MD,FIXED,STICKY',
  `reason_detail` varchar(500) DEFAULT NULL COMMENT '原因明细(哪个账户持仓/哪条链候选/哪位导师/哪天 md), 便于溯源',
  `sticky_until` date DEFAULT NULL COMMENT '粘滞保留到哪天(最后命中日 + 10 个交易日)',
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
