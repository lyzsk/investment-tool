-- investment_tool.sys_job definition

CREATE TABLE `sys_job` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `job_name` varchar(255) NOT NULL,
  `job_group` varchar(128) DEFAULT 'default',
  `job_handler_name` varchar(100) NOT NULL COMMENT '任务处理器 Bean 名称',
  `job_handler_param` varchar(500) DEFAULT NULL COMMENT '任务参数',
  `retry_count` int DEFAULT '0' COMMENT '重试次数',
  `retry_interval` int DEFAULT '0' COMMENT '重试间隔（毫秒）',
  `cron_expression` varchar(255) DEFAULT NULL,
  `misfire_policy` tinyint DEFAULT '2' COMMENT '0-立即执行, 1-执行一次, 2-放弃执行',
  `status` tinyint DEFAULT '1' COMMENT '0-运行, 1-暂停',
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
