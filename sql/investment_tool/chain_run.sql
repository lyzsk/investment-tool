-- investment_tool.chain_run definition
-- 10/12 建(Claude, 用户授权): §5.5 链路入库——paper 链运行目录 results/<skill>_chain/{live|asof}-yyyyMMdd/ 是唯一事实, 这几张表只是索引(inv-ui 链路追踪页的数据底座)
-- 一次链运行(一个 skill 一个时段一行); 同目录每个时段会覆盖步骤文件, 故实盘在进程结束时立即入库=该时段快照; 历史补导只能拿到目录最终状态(slot=FINAL)

CREATE TABLE `chain_run` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `skill` varchar(32) NOT NULL COMMENT '链名=run_taoge_chain.py SKILL_CFG 键: taoge/buchitudou0/qushitiange/.../control',
  `mode` varchar(8) NOT NULL COMMENT 'LIVE(实盘)/ASOF(回放)',
  `run_date` date NOT NULL COMMENT '链日',
  `slot` varchar(10) NOT NULL COMMENT '时段 HHMM(0915=盘前全链, 其余=盘中子链 02/04/06) / review(07 复盘) / FINAL(历史补导, 时段不可考)',
  `run_dir` varchar(200) NOT NULL COMMENT '运行目录(相对项目根)',
  `exit_code` int DEFAULT NULL COMMENT 'driver 退出码: 0 成功 / 1 中止 / 2 用法错 / 3 ESCALATE_FULL_CHAIN; 超时=-1; 历史补导=NULL',
  `started_at` datetime(6) DEFAULT NULL COMMENT '进程开始(历史补导=NULL)',
  `finished_at` datetime(6) DEFAULT NULL COMMENT '进程结束(历史补导=目录内最新文件 mtime)',
  `duration_s` int DEFAULT NULL COMMENT '耗时秒',
  `steps` varchar(100) DEFAULT NULL COMMENT '目录里有产物的步骤, 逗号分隔',
  `market_state` varchar(16) DEFAULT NULL COMMENT '02 市况: 有主线/无主线退潮/普跌',
  `leading_layer` varchar(16) DEFAULT NULL COMMENT '02 先行层: 板块层/资金惯性层',
  `debate_winner` varchar(4) DEFAULT NULL COMMENT '03j 辩论胜方: 多/空(土豆链无 03)',
  `blind_verdict` varchar(8) DEFAULT NULL COMMENT '盲审 pass/fail',
  `blind_failed` tinyint DEFAULT '0' COMMENT '1=盲审终败降级发布(目录有 BLIND_FAILED.txt)',
  `no_trade` tinyint DEFAULT NULL COMMENT '06 终裁 no_trade',
  `action_count` int DEFAULT NULL COMMENT '06 终裁单数',
  `rules_count` int DEFAULT NULL COMMENT 'persona 规则条数(run_meta.jsonl, 10/11 起才有)',
  `chain_md_sha12` varchar(12) DEFAULT NULL COMMENT 'chain.md 版本(run_meta.jsonl)',
  `persona_json` json DEFAULT NULL COMMENT 'persona 各文件 sha12/大小/mtime(run_meta.jsonl 末行)',
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
  KEY `idx_skill_date` (`skill`, `run_date`) COMMENT '普通索引(非唯一): 按链+日期查运行'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
