-- investment_market.index_constituent_coverage definition

CREATE TABLE `index_constituent_coverage` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `index_symbol` varchar(16) NOT NULL COMMENT '同 index_constituent.index_symbol, 一指数一行',
  `index_code` varchar(12) NOT NULL COMMENT '指数纯代码',
  `index_name` varchar(32) NOT NULL COMMENT '指数简称',
  `publisher` varchar(10) NOT NULL COMMENT '编制方 csindex(中证)/cnindex(国证)/bse(北交所)',
  `nominal_count` int DEFAULT NULL COMMENT '名义样本数(300/500/1000…)',
  `pit_from` date DEFAULT NULL COMMENT '完整起点: D >= pit_from 时按 D 查出的成分是完整的',
  `partial_from` date DEFAULT NULL COMMENT '最早有记录日; partial_from <= D < pit_from 只是"当前存活者子集"(缺之后被剔除的样本), 研究慎用',
  `pit_to` date DEFAULT NULL COMMENT '最后一次观测(快照)日; 之后的调整要重跑脚本才有',
  `method` varchar(200) DEFAULT NULL COMMENT '区间重建方法说明',
  `source` varchar(20) DEFAULT NULL COMMENT '主数据源 baostock/cnindex/sina',
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
  KEY `idx_index_symbol` (`index_symbol`) COMMENT '普通索引(非唯一; 整表由脚本重建)'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
