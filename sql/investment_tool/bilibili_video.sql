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
  `step` varchar(20) NOT NULL DEFAULT 'NEW' COMMENT '状态机: NEW→DOWNLOADED→VISION_DONE→SUMMARIZED→DISTILLED(9/27起直链: 下载后同job内跑process_video.py, ASR_DONE废弃; 10/12 加 DISTILLED=所在 md 日已蒸馏进 persona, 由对账按 distill 账本推进); 失败时 step 原地不动+status=1+retry_count+1; 消费者=下一阶段逻辑',
  `retry_count` int NOT NULL DEFAULT '0' COMMENT '当前 step 的连续失败次数, >=3 停住只告警(防无限重跑); 成功后归零',
  `origin` varchar(10) NOT NULL DEFAULT 'DAILY' COMMENT '来源(10/12 加): DAILY=每日任务 48h 发现, 由 bilibiliVideoHandler 处理 / BACKFILL=补跑登记, 由 bilibiliBackfillHandler 限量处理(不挡当日视频)',
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
