-- investment_tool.k3inv_signal definition
-- k3-inv 策略: 加红电报催化信号(AI 从 cls_telegraph 蒸馏)
CREATE TABLE `k3inv_signal` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `signal_date` date NOT NULL COMMENT '信号日期',
  `signal_time` datetime(6) NOT NULL COMMENT '电报发布时间(信息可用性以此为界)',
  `cls_id` bigint DEFAULT NULL COMMENT '关联 cls_telegraph.cls_id',
  `sector` varchar(50) DEFAULT NULL COMMENT '板块/主题, 如 航运/液冷',
  `stocks` json DEFAULT NULL COMMENT '点名个股[{code,name}]',
  `direction` varchar(10) NOT NULL COMMENT 'long/short',
  `signal_type` varchar(20) NOT NULL COMMENT 'auction竞价/sector_move板块拉升/policy政策/overnight外围/review收评',
  `summary` varchar(500) DEFAULT NULL COMMENT '一句话逻辑',
  `strength` tinyint DEFAULT '3' COMMENT 'AI 评分 1-5(主线确认>=4)',
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
  KEY `idx_date_time` (`signal_date`, `signal_time`),
  KEY `idx_cls` (`cls_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- investment_tool.k3inv_watch definition
-- 信号 → 个股观察名单(李大霄质量筛 + 威科夫结构状态)
CREATE TABLE `k3inv_watch` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `watch_date` date NOT NULL,
  `signal_id` bigint DEFAULT NULL COMMENT '来源信号 k3inv_signal.id',
  `stock_code` varchar(10) NOT NULL,
  `stock_name` varchar(50) DEFAULT NULL,
  `quality_pass` tinyint DEFAULT NULL COMMENT '李大霄质量筛: 0-不通过(只做情绪参考), 1-通过',
  `quality_reason` varchar(300) DEFAULT NULL COMMENT '通过/否决理由(龙头/业绩/次新/ST...)',
  `wyckoff_phase` varchar(20) DEFAULT NULL COMMENT 'accumulation/markup/distribution/markdown/unknown',
  `watch_state` varchar(10) DEFAULT 'open' COMMENT 'open观察/triggered已触发/expired过期',
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
  KEY `idx_date_code` (`watch_date`, `stock_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- investment_tool.k3inv_strategy definition
-- 策略版本注册表(回测与实盘共用, 版本可追溯)
CREATE TABLE `k3inv_strategy` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `strategy_code` varchar(20) NOT NULL COMMENT '如 k3-v0.1',
  `spec_text` text COMMENT '策略规格全文(STRATEGY.md)',
  `params` json DEFAULT NULL COMMENT '{单票仓位,总仓位,止损,不追高线,手续费...}',
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
  UNIQUE KEY `uk_strategy_code` (`strategy_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- investment_tool.k3inv_run definition
CREATE TABLE `k3inv_run` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `run_code` varchar(40) NOT NULL,
  `strategy_code` varchar(20) NOT NULL COMMENT 'k3inv_strategy.strategy_code',
  `run_type` varchar(10) NOT NULL COMMENT 'backtest/paper(模拟盘)/live(实盘提醒)',
  `start_date` date NOT NULL,
  `end_date` date NOT NULL,
  `init_capital` decimal(14,2) NOT NULL,
  `total_return` decimal(10,4) DEFAULT NULL COMMENT '总收益率%',
  `win_rate` decimal(6,4) DEFAULT NULL,
  `max_drawdown` decimal(10,4) DEFAULT NULL,
  `benchmark_return` decimal(10,4) DEFAULT NULL,
  `report` longtext COMMENT '归因报告 md',
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

-- investment_tool.k3inv_decision definition
CREATE TABLE `k3inv_decision` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `run_id` bigint NOT NULL,
  `trade_date` date NOT NULL,
  `decision_time` datetime(6) NOT NULL,
  `stock_code` varchar(10) DEFAULT NULL,
  `action` varchar(10) NOT NULL COMMENT 'buy/sell/hold/watch',
  `price` decimal(10,3) DEFAULT NULL,
  `qty` int DEFAULT NULL,
  `reason` text COMMENT '三层依据: 电报催化+威科夫结构+李大霄质量',
  `signal_ids` varchar(100) DEFAULT NULL COMMENT '依据的信号 k3inv_signal.id 列表',
  `info_cutoff` datetime(6) NOT NULL COMMENT '信息截止(防未来函数证明)',
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

-- investment_tool.k3inv_trade definition
CREATE TABLE `k3inv_trade` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `run_id` bigint NOT NULL,
  `stock_code` varchar(10) NOT NULL,
  `buy_time` datetime(6) NOT NULL,
  `buy_price` decimal(10,3) NOT NULL,
  `qty` int NOT NULL,
  `sell_time` datetime(6) DEFAULT NULL,
  `sell_price` decimal(10,3) DEFAULT NULL,
  `pnl` decimal(14,2) DEFAULT NULL,
  `pnl_ratio` decimal(10,4) DEFAULT NULL,
  `signal_ids` varchar(100) DEFAULT NULL,
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
