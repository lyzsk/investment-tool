-- investment_market.adjustment_factor definition

CREATE TABLE `adjustment_factor` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `symbol` varchar(16) NOT NULL COMMENT '见 security_master.symbol',
  `ex_date` date NOT NULL COMMENT '因子生效日(除权除息日; 首行=上市日)',
  `factor` decimal(24,12) NOT NULL COMMENT '累积复权因子(后复权口径, 单调不减)',
  `source` varchar(10) NOT NULL COMMENT '数据源 baostock/dfcf/tdx',
  `status` tinyint DEFAULT '0' COMMENT '0-成功, 1-失败',
  `create_by` bigint DEFAULT NULL,
  `create_time` datetime(6) DEFAULT NULL,
  `update_by` bigint DEFAULT NULL,
  `update_time` datetime(6) DEFAULT NULL,
  `is_deleted` tinyint DEFAULT '0' COMMENT '0-未删除, 1-已删除',
  `delete_by` bigint DEFAULT NULL,
  `delete_time` datetime(6) DEFAULT NULL,
  `remark` varchar(500) DEFAULT NULL COMMENT '可记除权事由(10送3转5派2 等, 可与巨潮公告核对)',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
