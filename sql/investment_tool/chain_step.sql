-- investment_tool.chain_step definition
-- 10/12 建(Claude, 用户授权): §5.5 链路入库——paper 链运行目录 results/<skill>_chain/{live|asof}-yyyyMMdd/ 是唯一事实, 这几张表只是索引(inv-ui 链路追踪页的数据底座)
-- 链运行的每个步骤产物(内容不入库, 只记路径/哈希/哨兵/contract)

CREATE TABLE `chain_step` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `run_id` bigint NOT NULL COMMENT '关联 chain_run.id',
  `step` varchar(8) NOT NULL COMMENT '01/02/03b/03s/03j/04/05/06/blind/07',
  `file_name` varchar(64) NOT NULL COMMENT '产物文件名(目录见 chain_run.run_dir)',
  `file_mtime` datetime(6) DEFAULT NULL COMMENT '产物最后修改时间(重试/盘中时段会覆盖, 只代表入库时刻的版本)',
  `bytes` int DEFAULT NULL COMMENT '文件字节数',
  `sha12` varchar(12) DEFAULT NULL COMMENT '内容 sha256 前 12 位(比对版本)',
  `sentinel_ok` tinyint DEFAULT NULL COMMENT '末行哨兵: 1=STEP_OK/REVIEW_OK 且日期对, 0=缺或不对',
  `contract_json` json DEFAULT NULL COMMENT '末个 contract 代码块(驱动器契约), 解析失败=NULL',
  `contract_error` varchar(200) DEFAULT NULL COMMENT 'contract 缺失/解析失败原因',
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
  KEY `idx_run` (`run_id`) COMMENT '普通索引(非唯一): 按运行查步骤'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
