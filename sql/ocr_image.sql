-- investment_tool.ocr_image definition

CREATE TABLE `ocr_image` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `file_upload_id` bigint NOT NULL COMMENT '关联 file_upload.id',
  `image_data` longblob,
  `upload_by` bigint DEFAULT NULL,
  `upload_time` datetime(6) DEFAULT NULL,
  `status` tinyint DEFAULT '0' COMMENT '0-未处理, 1-已处理, 2-处理失败',
  `is_deleted` tinyint DEFAULT '0' COMMENT '0-未删除, 1-已删除',
  `delete_by` bigint DEFAULT NULL,
  `delete_time` datetime(6) DEFAULT NULL,
  `remark` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;