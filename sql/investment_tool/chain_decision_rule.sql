-- investment_tool.chain_decision_rule definition
-- 10/12 建(Claude, 用户授权): §5.5 链路入库——paper 链运行目录 results/<skill>_chain/{live|asof}-yyyyMMdd/ 是唯一事实, 这几张表只是索引(inv-ui 链路追踪页的数据底座)
-- 终裁单引用的 persona 规则(actions[].rules[] 每项一行); 规则 id 只在本 skill 内唯一

CREATE TABLE `chain_decision_rule` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `decision_id` bigint NOT NULL COMMENT '关联 chain_decision.id',
  `run_id` bigint NOT NULL COMMENT '冗余 chain_run.id',
  `skill` varchar(32) NOT NULL COMMENT '规则所属 skill(R2 在不同 skill 是不同规则)',
  `rule_id` varchar(16) NOT NULL COMMENT '规则 id, 对应 skills/<skill>-skill/persona/rules.md 的 ### <id> 标题',
  `ctx` text COMMENT '情境判定说明(模型写)',
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
  KEY `idx_decision` (`decision_id`) COMMENT '普通索引(非唯一): 按终裁单查规则'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
