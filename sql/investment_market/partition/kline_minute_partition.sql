-- investment_market.kline_minute 分区(10/11 用户定: 建表后手动执行, 便于溯源每次分区写到哪)
-- 前提: 已执行 ../kline_minute.sql(主键已含 trade_date, 否则 MySQL 拒绝按 trade_date 分区)
-- 本文件=首次分区: 按年 RANGE 分区, 预建 2025~2030 + pmax 兜底(超出 2030 的数据先落 pmax, 不会插入失败)
-- 执行: mysql -uroot -p investment_market < partition/kline_minute_partition.sql
-- 查看现有分区: SELECT partition_name, partition_description, table_rows
--                 FROM information_schema.partitions WHERE table_schema='investment_market' AND table_name='kline_minute';

ALTER TABLE `kline_minute`
PARTITION BY RANGE COLUMNS (`trade_date`) (
  PARTITION p2025 VALUES LESS THAN ('2026-01-01'),
  PARTITION p2026 VALUES LESS THAN ('2027-01-01'),
  PARTITION p2027 VALUES LESS THAN ('2028-01-01'),
  PARTITION p2028 VALUES LESS THAN ('2029-01-01'),
  PARTITION p2029 VALUES LESS THAN ('2030-01-01'),
  PARTITION p2030 VALUES LESS THAN ('2031-01-01'),
  PARTITION pmax VALUES LESS THAN (MAXVALUE)
);

-- ===== 以后追加年份(示例, 2030 年底前执行; 执行后在本文件末尾追加一行执行记录, 便于溯源) =====
-- ALTER TABLE `kline_minute` REORGANIZE PARTITION pmax INTO (
--   PARTITION p2031 VALUES LESS THAN ('2032-01-01'),
--   PARTITION pmax VALUES LESS THAN (MAXVALUE)
-- );
-- ===== 删除整年旧数据(示例, 比 DELETE 快得多且不留碎片) =====
-- ALTER TABLE `kline_minute` DROP PARTITION p2025;

-- 执行记录:
-- (首次执行后在此追加: 日期 / 执行人 / 分区范围)
