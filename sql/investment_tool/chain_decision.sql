-- investment_tool.chain_decision definition
-- 10/12 建(Claude, 用户授权): §5.5 链路入库——paper 链运行目录 results/<skill>_chain/{live|asof}-yyyyMMdd/ 是唯一事实, 这几张表只是索引(inv-ui 链路追踪页的数据底座)
-- 06 终裁单(contract.actions[] 每项一行)

CREATE TABLE `chain_decision` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `run_id` bigint NOT NULL COMMENT '关联 chain_run.id',
  `skill` varchar(32) NOT NULL COMMENT '冗余 chain_run.skill, 便于按链查',
  `run_date` date NOT NULL COMMENT '冗余 chain_run.run_date',
  `slot` varchar(10) NOT NULL COMMENT '冗余 chain_run.slot',
  `action_idx` int NOT NULL COMMENT 'actions[] 下标(从 0)',
  `name` varchar(64) DEFAULT NULL COMMENT '票名(模型写, 偶有带代码的脏值)',
  `code` varchar(16) DEFAULT NULL COMMENT '代码',
  `op` varchar(8) DEFAULT NULL COMMENT '买/卖/撤 等',
  `trigger_price` varchar(64) DEFAULT NULL COMMENT '触发价(字符串: 可能是公式如 Z*0.97, 由驱动器 resolve_px 解析)',
  `qty` int DEFAULT NULL COMMENT '数量(股/张)',
  `anchor` varchar(64) DEFAULT NULL COMMENT '锚定价(字符串)',
  `cancel_below` decimal(14,4) DEFAULT NULL COMMENT '低于此价撤单',
  `stop_below` decimal(14,4) DEFAULT NULL COMMENT '低于此价止损',
  `invalid_if` varchar(1000) DEFAULT NULL COMMENT '失效条件',
  `action_json` json DEFAULT NULL COMMENT '原始 action(含 rules)',
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
  KEY `idx_run` (`run_id`) COMMENT '普通索引(非唯一): 按运行查终裁单'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
