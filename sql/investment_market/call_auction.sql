-- investment_market.call_auction definition

CREATE TABLE `call_auction` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `symbol` varchar(16) NOT NULL COMMENT '见 security_master.symbol',
  `trade_date` date NOT NULL COMMENT '交易日',
  `phase` varchar(6) NOT NULL COMMENT 'OPEN(开盘集合竞价 09:15~09:25)/CLOSE(收盘集合竞价 14:57~15:00)',
  `snap_time` datetime(0) NOT NULL COMMENT '快照时刻(日期+时分秒)',
  `price` decimal(14,4) DEFAULT NULL COMMENT '虚拟匹配价(指示价, 不复权); 每段最后一行=撮合成交价',
  `matched_volume` bigint DEFAULT NULL COMMENT '虚拟匹配量(股; 转债=张), 截至该时刻累计',
  `matched_amount` decimal(20,2) DEFAULT NULL COMMENT '虚拟匹配额(元), 截至该时刻累计',
  `unmatched_volume` bigint DEFAULT NULL COMMENT '未匹配量(股): 正=买方剩余(买盘多), 负=卖方剩余; 方向口径待实测确认',
  `source` varchar(10) NOT NULL COMMENT '数据源 dfcf/tdx/sina/tencent',
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
  KEY `idx_symbol_date` (`symbol`, `trade_date`) COMMENT '普通索引(非唯一): 按标的+日期查竞价; 对增删改写法无影响'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
