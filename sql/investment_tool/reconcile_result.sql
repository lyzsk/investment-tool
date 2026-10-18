-- investment_tool.reconcile_result definition
-- 10/12 建(Claude, 用户授权): 对账结果表, 行情库(MARKET)与 B 站管线(BILIBILI)等各对账 Handler 共用; 每次对账每个检查项一行, 只追加不更新

CREATE TABLE `reconcile_result` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `batch_no` varchar(32) NOT NULL COMMENT '对账批次号(yyyyMMddHHmmss + 业务), 同一次对账的行同号',
  `biz_type` varchar(16) NOT NULL COMMENT '业务: MARKET(行情库)/BILIBILI(UP 主视频管线)',
  `biz_key` varchar(64) NOT NULL COMMENT '对账对象: 交易日 yyyy-MM-dd / UP 名 等',
  `check_item` varchar(32) NOT NULL COMMENT '检查项: kline_day/kline_minute/call_auction/adjustment_factor/results/md/distill 等',
  `expected` varchar(64) DEFAULT NULL COMMENT '应有(行数/天数/状态)',
  `actual` varchar(64) DEFAULT NULL COMMENT '实有',
  `result` varchar(16) NOT NULL COMMENT 'OK(对得上)/MISSING(缺且未补)/FIXED(本次已自动补齐)/FAILED(补采失败)/UNRECOVERABLE(不可补, 如错过的竞价)/WARN(对得上但有异常)',
  `detail` varchar(1000) DEFAULT NULL COMMENT '差异明细/补采结果摘要',
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
  KEY `idx_biz` (`biz_type`, `biz_key`) COMMENT '普通索引(非唯一): 按业务+对象查对账史'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
