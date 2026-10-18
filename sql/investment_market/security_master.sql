-- investment_market.security_master definition

CREATE TABLE `security_master` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `symbol` varchar(16) NOT NULL COMMENT '全库关联键=市场前缀+代码: sh600519/sz000001/bj920985/sh000001(上证指数)/sz399006/sh113052(转债)/hk00700/BK0477(东财板块)/us.NDX/us.HXC/hk.HSI/jp.N225/kr.KS11; 前缀消歧(000001=平安银行 vs 上证指数)',
  `code` varchar(12) NOT NULL COMMENT '纯代码(不带前缀), A股 6 位, 与 investment_tool.tzzb_record.stock_code 等业务表对接',
  `exchange` varchar(8) NOT NULL COMMENT 'SH/SZ/BJ(沪深京)/HK(港股通)/EM(东财板块, 非交易所)/US/JP/KR/GLOBAL(期货·汇率·利率·商品等)',
  `sec_type` varchar(12) NOT NULL COMMENT 'STOCK(股票)/CB(可转债)/ETF/INDEX(指数, 含外围指数)/BOARD(东财行业·概念·地域板块)/OTHER(A50期货·美元指数·美债收益率·原油·黄金等)',
  `board_type` varchar(12) DEFAULT NULL COMMENT 'STOCK: MAIN(沪深主板)/GEM(创业板)/STAR(科创板)/BSE(北交所)/HKC(港股通); BOARD: INDUSTRY(行业)/CONCEPT(概念)/REGION(地域); 其余 NULL',
  `name` varchar(50) NOT NULL COMMENT '当前简称, ST/*ST/N/C 前缀原样保留; 改名不留历史(历史名以当日 md/成交记录为准)',
  `is_st` tinyint DEFAULT '0' COMMENT '当前是否 ST/*ST(风险警示; ST之狼等 skill 选股要用)。涨跌幅现行规则(用户 10/11 校正)只看板块: 主板 10%(含 ST), 创业板/科创板 20%(含 ST), 北交所 30%; 新规前主板 ST 为 5%——回放新规前日期须按旧规则, 历史某日实际涨跌停以 kline_day.limit_up/limit_down 为准',
  `list_date` date DEFAULT NULL COMMENT '上市日',
  `delist_date` date DEFAULT NULL COMMENT '退市日; NULL=在市。退市股不删(回放/统计防幸存者偏差)',
  `underlying_symbol` varchar(16) DEFAULT NULL COMMENT '仅 CB: 正股 symbol(土豆转债线用)',
  `source` varchar(10) DEFAULT NULL COMMENT '数据源 dfcf/sina/tencent/tdx(通达信)/exchange(交易所官网)',
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
