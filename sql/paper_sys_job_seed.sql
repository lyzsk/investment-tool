-- paper 模拟盘 Quartz 种子(2026-10-02, 用户手动执行; status=0 直接启用=10/2 用户拍板: 冒烟通过即可注册)
-- handler 代码: inv-stock/cn/sichu/paper/handler/(PaperChainHandler/PaperMatchHandler/PaperEodHandler/PaperReviewHandler=10/6 补 §G-5)
-- 时刻表口径=docs/TODO.md §E; misfire=2 丢弃(错过 slot 不补跑); 非交易日由 handler 代码守门

INSERT INTO `sys_job` (`job_name`, `job_group`, `job_handler_name`, `job_handler_param`, `cron_expression`, `misfire_policy`, `status`, `remark`) VALUES
('paper链-0915盘前全链',  'PAPER_GROUP', 'paperChainHandler', '0915', '0 15 9 * * ?',  2, 0, '全七步=竞价预案(预期被开盘推翻)'),
('paper链-0927竞价纠偏',  'PAPER_GROUP', 'paperChainHandler', '0927', '0 27 9 * * ?',  2, 0, '子链02→04→06, 产物=条件单滑到09:31也不怕'),
('paper链-0945',          'PAPER_GROUP', 'paperChainHandler', '0945', '0 45 9 * * ?',  2, 0, '早盘确认点1'),
('paper链-1000',          'PAPER_GROUP', 'paperChainHandler', '1000', '0 0 10 * * ?',  2, 0, '早盘确认点2'),
('paper链-1030',          'PAPER_GROUP', 'paperChainHandler', '1030', '0 30 10 * * ?', 2, 0, '早盘确认点3'),
('paper链-1127',          'PAPER_GROUP', 'paperChainHandler', '1127', '0 27 11 * * ?', 2, 0, '上午收盘前定位'),
('paper链-1230午间链',    'PAPER_GROUP', 'paperChainHandler', '1230', '0 30 12 * * ?', 2, 0, '消化上午+午间新闻→下午计划(事件驱动一体, 一天一次)'),
('paper链-1400',          'PAPER_GROUP', 'paperChainHandler', '1400', '0 0 14 * * ?',  2, 0, '下午确认点1'),
('paper链-1430',          'PAPER_GROUP', 'paperChainHandler', '1430', '0 30 14 * * ?', 2, 0, '下午确认点2'),
('paper链-1455尾盘',      'PAPER_GROUP', 'paperChainHandler', '1455', '0 55 14 * * ?', 2, 0, '尾盘竞价决策, 14:57前落地'),
-- cb 转债链(10/4 盲区修复⑦): param=cb:HHMM 前缀走 --skill cb; 时刻集中早盘(R1: 88% 出手在 09:25-09:35, 午后不开新仓)
('paper链-cb-0915盘前全链','PAPER_GROUP', 'paperChainHandler', 'cb:0915', '0 15 9 * * ?',  2, 0, '转债链盘前全链(无03拆环): 01→02→04→05→06→盲审'),
('paper链-cb-0927竞价纠偏','PAPER_GROUP', 'paperChainHandler', 'cb:0927', '0 27 9 * * ?',  2, 0, '转债链主战场: 竞价后重裁(开盘双通道)'),
('paper链-cb-0935',        'PAPER_GROUP', 'paperChainHandler', 'cb:0935', '0 35 9 * * ?',  2, 0, '转债链开盘窗口收尾'),
('paper链-cb-1000',        'PAPER_GROUP', 'paperChainHandler', 'cb:1000', '0 0 10 * * ?',  2, 0, '转债链早盘最后一次(之后不开新仓=R1)'),
('paper撮合-每分钟',      'PAPER_GROUP', 'paperMatchHandler', NULL,  '0 * 9-14 * * ?', 2, 0, '保守撮合; 时段窗口(9:30-11:30/13:00-15:00)由代码守门, 非交易日跳过'),
('paper日终-EOD',         'PAPER_GROUP', 'paperEodHandler',   NULL,  '0 5 15 * * ?',   2, 0, '废单→nav→nav_*.csv→state_digest.md(次日facts用)'),
('paper 07 复盘',   'PAPER_GROUP', 'paperReviewHandler', '', '0 0 20 * * ?', '1', '0', 'TODO §G-5 修复: 当晚链产物 vs 实际对照, 误判进 cases; 防呆=无 06_verdict 自动跳过(2026-10-06)');
