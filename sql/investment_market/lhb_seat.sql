-- investment_market.lhb_seat definition
-- 龙虎榜席位明细(2026-10-15 建): 一行=某条上榜记录买五或卖五里的一个席位(东财原样); 同一席位同时在买五和卖五 = 两行(direction 不同, 买卖额相同)
-- 来源: downloads/lhb/yyyy.MM.dd/detail_<code>.json; 入库: LhbImportServiceImpl(按交易日先物理删除再插入, 幂等)

CREATE TABLE `lhb_seat` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `trade_date` date NOT NULL COMMENT '交易日',
  `symbol` varchar(16) NOT NULL COMMENT '见 security_master.symbol',
  `code` varchar(10) NOT NULL COMMENT '证券代码(6 位)',
  `trade_id` bigint NOT NULL COMMENT '东财上榜记录 ID, 见 lhb_stock.trade_id',
  `direction` varchar(4) NOT NULL COMMENT 'BUY-买五席位, SELL-卖五席位',
  `seat_rank` tinyint DEFAULT NULL COMMENT '该方向内名次(1~5, BUY 按买入额降序/SELL 按卖出额降序)',
  `dept_code` varchar(20) DEFAULT NULL COMMENT '东财营业部编码(OPERATEDEPT_CODE, 跨更名基本稳定; 0/99999 等为多名共用的占位码)',
  `dept_name` varchar(100) NOT NULL COMMENT '营业部全名(东财原文, 如 东方财富证券股份有限公司拉萨团结路第一证券营业部 / 机构专用 / 深股通专用)',
  `amount` decimal(20,2) DEFAULT NULL COMMENT '该方向金额(元): BUY=买入额, SELL=卖出额',
  `buy_amt` decimal(20,2) DEFAULT NULL COMMENT '该席位买入额(元)',
  `sell_amt` decimal(20,2) DEFAULT NULL COMMENT '该席位卖出额(元)',
  `net_amt` decimal(20,2) DEFAULT NULL COMMENT '该席位净额(元)=买入-卖出',
  `buy_ratio` decimal(14,10) DEFAULT NULL COMMENT '买入额占当日总成交比(小数, TOTAL_BUYRIO)',
  `sell_ratio` decimal(14,10) DEFAULT NULL COMMENT '卖出额占当日总成交比(小数, TOTAL_SELLRIO)',
  `is_institution` tinyint NOT NULL DEFAULT '0' COMMENT '1-机构席位(机构专用/机构投资者/机构), 0-否',
  `youzi_alias` varchar(32) DEFAULT NULL COMMENT '游资别名(scripts/lhb/youzi.json 按席位简称对照, 如 章盟主/拉萨天团); 未收录=NULL',
  `source` varchar(10) NOT NULL COMMENT '数据源 em/ths',
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
  KEY `idx_date_symbol` (`trade_date`, `symbol`) COMMENT '普通索引(非唯一): 按日查/按日幂等重导',
  KEY `idx_dept_date` (`dept_code`, `trade_date`) COMMENT '普通索引(非唯一): 按营业部查上榜历史(席位画像)',
  KEY `idx_alias_date` (`youzi_alias`, `trade_date`) COMMENT '普通索引(非唯一): 按游资别名查'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
