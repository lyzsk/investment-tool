-- investment_tool.bilibili_video definition

CREATE TABLE `bilibili_video` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `bvid` varchar(16) NOT NULL COMMENT 'B站BV号',
  `author_mid` varchar(32) NOT NULL COMMENT 'UP主 mid',
  `title` varchar(500) DEFAULT NULL,
  `publish_time` datetime(6) NOT NULL COMMENT 'B站发布时间',
  `trade_date` date DEFAULT NULL COMMENT '内容归属交易日=md挂载点; 科普视频/解析不出=NULL',
  `duration` int DEFAULT NULL COMMENT '时长(秒);',
  `url` varchar(200) DEFAULT NULL COMMENT 'B站视频页链接',
  `source_files` json DEFAULT NULL COMMENT '下载产物档案 {mp4,m4a,json: 相对路径(正斜杠), meta: 抓取元数据全文(bvid/cid/title/pubdate/desc/duration/page/fetched_at)}; 物理删除后不置空(2026-09-29 用户定: 路径=曾在哪, meta+bvid=去哪重查); 播放页签名URL时效~2h不入库',
  `step` varchar(20) NOT NULL DEFAULT 'NEW' COMMENT '状态机: NEW→DOWNLOADED→VISION_DONE→SUMMARIZED(9/27起直链: 下载后同job内跑process_video.py, ASR_DONE废弃); 失败时 step 原地不动+status=1+retry_count+1; 消费者=下一阶段逻辑',
  `retry_count` int NOT NULL DEFAULT '0' COMMENT '当前 step 的连续失败次数, >=3 停住只告警(防无限重跑); 成功后归零',
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
