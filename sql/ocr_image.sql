-- investment_tool.ocr_image definition

CREATE TABLE `ocr_image` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `file_name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `file_type` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT 'MIME类型, 例如image/png',
  `file_size` bigint NOT NULL,
  `image_data` longblob NOT NULL COMMENT '图片二进制内容',
  `upload_by` bigint DEFAULT NULL,
  `upload_time` datetime(6) DEFAULT NULL,
  `status` tinyint DEFAULT '0' COMMENT '0-未处理, 1-已处理, 2-处理失败',
  `is_deleted` tinyint DEFAULT '0' COMMENT '0-未删除, 1-已删除',
  `remark` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;