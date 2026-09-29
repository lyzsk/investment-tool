package cn.sichu.download.handler;

import cn.sichu.bilibili.service.IBilibiliVideoService;
import cn.sichu.cls.service.IClsTelegraphService;
import cn.sichu.system.quartz.handler.JobHandler;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/**
 * downloads 物理删除任务(通用, 按域驱动): 逻辑删除(is_deleted)只是 DB 标记, 本任务管磁盘文件
 * <p>
 * - bilibili 域: SUMMARIZED 且超过 30 天的视频原料(source_files 记录的 mp4+m4a+json 全删),
 * DB 行保留防重复下载, source_files 不置空(2026-09-29 用户定: 路径+meta 留作"去哪重查"线索,
 * 幂等由磁盘判真); 结果文件在 results/ 永久不动
 * - cls 域: downloads/cls/<yyyy.MM.dd>/ 超过 90 天的日期目录整删(目录名日期判定);
 * DB images 字段是远程 URL 不受影响
 * <p>
 * sys_job: job_handler_name=downloadCleanupHandler, cron 每天 0 点(0 0 0 * * ?, 9/27 用户定)
 *
 * @author sichu huang
 * @since 2026/09/27 12:29
 */
@Component("downloadCleanupHandler")
@RequiredArgsConstructor
public class DownloadCleanupHandler implements JobHandler {
    /* 保留天数: 视频原料 30 天, cls 图 90 天 */
    private static final int BILIBILI_RETENTION_DAYS = 30;
    private static final int CLS_RETENTION_DAYS = 90;
    private final IBilibiliVideoService bilibiliVideoService;
    private final IClsTelegraphService clsTelegraphService;

    @Override
    public String execute(String params) {
        String bilibili = bilibiliVideoService.cleanupPhysicalFiles(BILIBILI_RETENTION_DAYS);
        String cls = clsTelegraphService.cleanupLocalImages(CLS_RETENTION_DAYS);
        return String.format("downloads 物理删除完成: %s; %s", bilibili, cls);
    }
}