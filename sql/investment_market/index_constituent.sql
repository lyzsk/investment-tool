-- investment_market.index_constituent definition

CREATE TABLE `index_constituent` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `index_symbol` varchar(16) NOT NULL COMMENT '指数 symbol(同 security_master.symbol): sh000300/sz399006/bj899050; 中证官网独有指数用 csi 前缀(csi932000=中证2000)',
  `index_code` varchar(12) NOT NULL COMMENT '指数纯代码 000300/932000',
  `index_name` varchar(32) NOT NULL COMMENT '指数简称(沪深300/中证2000…)',
  `con_symbol` varchar(16) NOT NULL COMMENT '成分股 symbol(sh/sz/bj+6 位, 北交所用 920 新代码, 同 security_master)',
  `con_code` varchar(10) NOT NULL COMMENT '成分股 6 位代码',
  `con_name` varchar(32) DEFAULT NULL COMMENT '成分股简称(该区间首次观测到时的名称, 改名不追)',
  `in_date` date NOT NULL COMMENT '纳入生效日(含)。in_exact=0 时为覆盖起点(真实纳入更早、未知)',
  `out_date` date DEFAULT NULL COMMENT '剔除生效日(当天已不是成分, 不含); NULL=至今仍在。已公告未生效的调出也会预填未来日期',
  `in_exact` tinyint NOT NULL DEFAULT '1' COMMENT '1-in_date 为观测到的真实纳入生效日; 0-左删失(覆盖起点那天已在指数里)',
  `source` varchar(40) NOT NULL COMMENT '区间来源: baostock(周快照差分)/cnindex(国证调样历史)/sina(当前成分纳入日期); +sina_date=纳入日已按新浪精修; +sina_future=新浪已登记未来生效; +csindex_pending_out=中证官网仍在但已公告调出',
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
  KEY `idx_index_in` (`index_symbol`, `in_date`) COMMENT '普通索引: 按指数+日期查当日成分(再过滤 out_date)',
  KEY `idx_con_in` (`con_symbol`, `in_date`) COMMENT '普通索引: 按个股查它在哪些指数里'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
