-- investment_tool 桃哥管线 DDL
-- 公共字段遵循 BaseEntity: id/status/create_by/create_time/update_by/update_time/is_deleted/delete_by/delete_time/remark

-- 1. 桃哥视频索引
CREATE TABLE `taoge_video` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `bvid` varchar(16) NOT NULL COMMENT 'B站BV号',
  `title` varchar(500) DEFAULT NULL,
  `pubdate` datetime(6) NOT NULL COMMENT '发布时间',
  `trade_date` date NOT NULL COMMENT '归属交易日',
  `duration` int DEFAULT NULL COMMENT '时长(秒)',
  `url` varchar(200) DEFAULT NULL,
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
  UNIQUE KEY `uk_bvid` (`bvid`),
  KEY `idx_trade_date` (`trade_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 2. 语音转写(原文+纠错文, 按模型版本存)
CREATE TABLE `taoge_transcript` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `bvid` varchar(16) NOT NULL,
  `asr_model` varchar(20) NOT NULL COMMENT 'small/medium',
  `raw_text` longtext COMMENT 'ASR原文',
  `fixed_text` longtext COMMENT '股名纠错后文本',
  `corrections` json DEFAULT NULL COMMENT '纠错明细[{from,to,level}]',
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
  UNIQUE KEY `uk_bvid_model` (`bvid`, `asr_model`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 3. 每日提取(#### 解读 的结构化本体)
CREATE TABLE `taoge_analysis` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `trade_date` date NOT NULL,
  `bvid` varchar(16) DEFAULT NULL,
  `market_view` text COMMENT '大盘判断',
  `operations_today` json DEFAULT NULL COMMENT '桃哥今日操作[]',
  `tomorrow_implication` json DEFAULT NULL COMMENT '{关注:[], 避开:[]}',
  `style_rules` json DEFAULT NULL COMMENT '风格规则[]',
  `full_json` json DEFAULT NULL COMMENT '提取完整JSON',
  `confidence` varchar(10) DEFAULT NULL COMMENT 'high/medium/low',
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
  UNIQUE KEY `uk_trade_date` (`trade_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 4. 提及个股(回测主表: 信号层)
CREATE TABLE `taoge_mention` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `trade_date` date NOT NULL COMMENT '提及日期(复盘日)',
  `analysis_id` bigint NOT NULL,
  `stock_name` varchar(50) NOT NULL,
  `stock_code` varchar(10) DEFAULT NULL COMMENT 'sh600127 格式',
  `asr_aliases` json DEFAULT NULL COMMENT '转写别名[]',
  `stance` varchar(20) DEFAULT NULL COMMENT 'bullish/bearish/watch/avoid/neutral/warning',
  `action` varchar(200) DEFAULT NULL COMMENT '建议动作',
  `logic` text COMMENT '逻辑',
  `his_position` varchar(100) DEFAULT NULL COMMENT '桃哥持仓状态',
  `category` varchar(2) DEFAULT NULL COMMENT 'F预测/R规则/H马后炮/N噪音',
  `next_day_ret` decimal(8,4) DEFAULT NULL COMMENT '次日收益%(回测回填)',
  `verdict` varchar(10) DEFAULT NULL COMMENT '命中/未中/待定(回测回填)',
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
  KEY `idx_date_code` (`trade_date`, `stock_code`),
  KEY `idx_analysis` (`analysis_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 5. 规则库(桃哥操盘 skill 的可执行部分)
CREATE TABLE `taoge_rule` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `rule_code` varchar(10) NOT NULL COMMENT 'R1/R2...',
  `title` varchar(200) NOT NULL,
  `category` varchar(2) NOT NULL COMMENT 'F预测/R规则/H马后炮/N噪音',
  `spec` json NOT NULL COMMENT '{前置条件,触发,入场,失效,出场}',
  `evidence` json DEFAULT NULL COMMENT '证据链[{date,结果}]',
  `evidence_strength` tinyint DEFAULT '0' COMMENT '0-5星',
  `learned_before` date NOT NULL COMMENT '学习截止日(防未来函数)',
  `enabled` tinyint DEFAULT '1',
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
  UNIQUE KEY `uk_rule_code` (`rule_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 6. 东财账户快照(资金+持仓, OCR 定时采集)
CREATE TABLE `taoge_position_snapshot` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `snapshot_time` datetime(6) NOT NULL,
  `total_asset` decimal(14,2) DEFAULT NULL COMMENT '总资产',
  `available_cash` decimal(14,2) DEFAULT NULL COMMENT '可用资金',
  `market_value` decimal(14,2) DEFAULT NULL COMMENT '证券市值',
  `position_pnl` decimal(14,2) DEFAULT NULL COMMENT '持仓盈亏',
  `positions` json DEFAULT NULL COMMENT '[{code,name,qty,available,cost,price,pnl_ratio}]',
  `source` varchar(20) DEFAULT 'em_ocr' COMMENT 'em_ocr/manual',
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
  KEY `idx_snapshot_time` (`snapshot_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 7. 回测运行
CREATE TABLE `taoge_backtest_run` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `run_code` varchar(40) NOT NULL COMMENT '运行标识',
  `skill_version` varchar(20) NOT NULL COMMENT '规则库版本',
  `start_date` date NOT NULL,
  `end_date` date NOT NULL,
  `init_capital` decimal(14,2) NOT NULL,
  `config` json DEFAULT NULL COMMENT '{成交口径,出场规则,仓位规则,滑点费率}',
  `total_return` decimal(10,4) DEFAULT NULL COMMENT '总收益率%',
  `win_rate` decimal(6,4) DEFAULT NULL,
  `max_drawdown` decimal(10,4) DEFAULT NULL,
  `benchmark_return` decimal(10,4) DEFAULT NULL COMMENT '同期沪深300%',
  `report` longtext COMMENT '归因分析报告md',
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
  UNIQUE KEY `uk_run_code` (`run_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 8. 回测决策明细(每个决策点一行, 含信息截止证明)
CREATE TABLE `taoge_backtest_decision` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `run_id` bigint NOT NULL,
  `trade_date` date NOT NULL,
  `decision_time` datetime(6) NOT NULL COMMENT '决策时刻(盘中)',
  `stock_code` varchar(10) DEFAULT NULL,
  `action` varchar(10) NOT NULL COMMENT 'buy/sell/hold/watch',
  `price` decimal(10,3) DEFAULT NULL,
  `qty` int DEFAULT NULL,
  `reason` text COMMENT '决策理由',
  `rule_refs` varchar(100) DEFAULT NULL COMMENT '引用规则 R1,R3',
  `info_cutoff` date NOT NULL COMMENT '信息截止日(<=trade_date-1 证明无未来函数)',
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
  KEY `idx_run_date` (`run_id`, `trade_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 9. 回测成交明细
CREATE TABLE `taoge_backtest_trade` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `run_id` bigint NOT NULL,
  `stock_code` varchar(10) NOT NULL,
  `buy_time` datetime(6) NOT NULL,
  `buy_price` decimal(10,3) NOT NULL,
  `qty` int NOT NULL,
  `sell_time` datetime(6) DEFAULT NULL,
  `sell_price` decimal(10,3) DEFAULT NULL,
  `pnl` decimal(14,2) DEFAULT NULL COMMENT '盈亏(扣费后)',
  `pnl_ratio` decimal(10,4) DEFAULT NULL COMMENT '收益率%',
  `rule_refs` varchar(100) DEFAULT NULL,
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
  KEY `idx_run` (`run_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
