-- investment_tool.ocr_result definition

CREATE TABLE `ocr_result` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `image_id` bigint NOT NULL COMMENT '关联的图片ID',
  `raw_text` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci,
  `processed_text` longtext,
  `word_count` bigint DEFAULT '0',
  `processed_by` bigint DEFAULT NULL,
  `process_time` datetime(6) DEFAULT NULL,
  `status` tinyint DEFAULT '0' COMMENT '0-成功, 1-失败',
  `error_msg` varchar(500) DEFAULT NULL,
  `is_deleted` tinyint DEFAULT '0' COMMENT '0-未删除, 1-已删除',
  `remark` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;