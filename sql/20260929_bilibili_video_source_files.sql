-- 2026-09-29 source_files 字段升级(用户定): 数组 [mp4,m4a,json 相对路径] → 对象 {mp4,m4a,json,meta}
-- 背景: ①物理删除后不再置空, 留"曾在哪+去哪重查"线索; ②meta=抓取元数据全文(新下载起由 Java 嵌入)
-- 执行顺序(重要): 先跑本 SQL, 再重启后端服务——新代码按对象格式读写, 旧数组格式会反序列化失败
-- 路径可确定性重建(downloads/bilibili/<mid>/<yyyy.MM.dd>/<bvid>.<ext>), 故含已被置空的历史行一起刷新

-- 1) 列注释更新
ALTER TABLE bilibili_video
  MODIFY COLUMN `source_files` json DEFAULT NULL COMMENT '下载产物档案 {mp4,m4a,json: 相对路径(正斜杠), meta: 抓取元数据全文(bvid/cid/title/pubdate/desc/duration/page/fetched_at)}; 物理删除后不置空(2026-09-29 用户定: 路径=曾在哪, meta+bvid=去哪重查); 播放页签名URL时效~2h不入库';

-- 2) 存量内容迁移: 全部未逻辑删除的行统一重建为对象格式(正斜杠); meta 留空(新下载自动带,
--    老行的 meta 在磁盘 downloads/.../<bvid>.json 里, 需要时可另跑脚本回填)
UPDATE bilibili_video
SET source_files = JSON_OBJECT(
  'mp4',  CONCAT('downloads/bilibili/', author_mid, '/', DATE_FORMAT(publish_time, '%Y.%m.%d'), '/', bvid, '.mp4'),
  'm4a',  CONCAT('downloads/bilibili/', author_mid, '/', DATE_FORMAT(publish_time, '%Y.%m.%d'), '/', bvid, '.m4a'),
  'json', CONCAT('downloads/bilibili/', author_mid, '/', DATE_FORMAT(publish_time, '%Y.%m.%d'), '/', bvid, '.json')
)
WHERE is_deleted = 0;

-- 3) 抽查: 应全部返回 json 对象(👀 看一两行确认格式)
-- SELECT bvid, step, source_files FROM bilibili_video WHERE is_deleted = 0 ORDER BY id DESC LIMIT 5;
