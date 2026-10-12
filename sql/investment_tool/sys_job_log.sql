-- investment_tool.sys_job_log definition

CREATE TABLE `sys_job_log` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `job_name` varchar(255) NOT NULL,
  `job_group` varchar(128) DEFAULT 'default',
  `job_handler_name` varchar(100) NOT NULL COMMENT '任务处理器 Bean 名称',
  `job_handler_param` varchar(500) DEFAULT NULL COMMENT '任务参数',
  `execution_time` bigint DEFAULT NULL COMMENT '执行耗时（毫秒）',
  `job_message` varchar(500) DEFAULT NULL COMMENT '执行结果信息',
  `exception_message` varchar(2000) DEFAULT NULL,
  `status` tinyint DEFAULT '1' COMMENT '0-成功, 1-失败',
  `create_by` bigint DEFAULT NULL,
  `create_time` datetime(6) DEFAULT NULL,
  `is_deleted` tinyint DEFAULT '0' COMMENT '0-未删除, 1-已删除',
  `delete_by` bigint DEFAULT NULL,
  `delete_time` datetime(6) DEFAULT NULL,
  `remark` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;