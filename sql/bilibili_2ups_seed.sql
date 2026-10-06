-- bilibili 两位新 UP 的 quartz job 种子(2026-10-05 建; 10/7 cron 定稿随种子就绪)
-- 用法: 在 PC1 MySQL investment_tool 库执行本文件; status=1(停用)——10/7 插入时改 0 启用(cron 已定稿, 无需再改)
-- 依赖代码: BilibiliVideoHandler 已支持 job_handler_param 透传(10/5);
--   fetch_bilibili.mjs 已支持 --mid/--name(10/5), 发现层加综合排序一路(卢本圆 9/27 后零发布,
--   最近稿 9/16, 窗口 10 天内新稿必被捞到; 首周请留意 sys_job_log 验证首发现)
-- 桃哥 job(既有, cron 0 30 15-23 * * ?)不动; bilibili_video 表 author_mid 区分状态机, 三 UP 共表无冲突

INSERT INTO `sys_job` (`job_name`, `job_group`, `job_handler_name`, `job_handler_param`, `cron_expression`, `misfire_policy`, `status`, `remark`) VALUES
('卢本圆视频发现', 'DEFAULT', 'bilibiliVideoHandler', '--mid 550494308 --name 卢本圆复盘',
 -- 10/7 定稿: 晨报型(近两月 10/10 条全在北京 8 点档), 7:00 起留 1h 缓冲; 更早样本有晚间习惯故尾至 22:30;
 -- 30min 粒度已匹配下游"发现→下载→ASR→合成"链的固有延迟量级, 再密无增益; 恢复发稿后按 sys_job_log 实发收窄
 '0 0/30 7-22 * * ?', '1', '1', '卢本圆复盘 mid=550494308(10/5 建); cron 10/7 定稿, 启用前改 status=0'),
('趋势天哥视频发现', 'DEFAULT', 'bilibiliVideoHandler', '--mid 1372241958 --name 趋势天哥',
 -- 10/7 定稿(用户口径: 发布习惯平均比桃哥晚 1-2 小时): 桃哥窗 15:30 起, 本线 16:30 起步=+1h 下界带缓冲;
 -- 尾同桃哥 23:30; 观察 2 周实发后收窄(若多在 17 点后改 17-23)。已实证最新稿 BV1ZhaJ6eEdk 发现链通
 '0 30 16-23 * * ?', '1', '1', '趋势天哥 mid=1372241958(10/5 建); cron 10/7 定稿, 启用前改 status=0');
