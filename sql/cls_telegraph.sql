-- investment_tool.cls_telegraph definition

CREATE TABLE `cls_telegraph` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `cls_id` bigint NOT NULL,
  `title` varchar(500) DEFAULT NULL,
  `brief` text,
  `content` longtext,
  `level` char(1) DEFAULT NULL,
  `publish_time` datetime(6) NOT NULL COMMENT 'ctime 转换',
  `author` varchar(100) DEFAULT NULL,
  `raw_data` json NOT NULL COMMENT '完整的原始JSON对象',
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