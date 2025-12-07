package cn.sichu.ocr.service.impl;

import cn.sichu.ocr.entity.OcrImage;
import cn.sichu.ocr.entity.OcrResult;
import cn.sichu.ocr.mapper.OcrImageMapper;
import cn.sichu.ocr.mapper.OcrResultMapper;
import cn.sichu.ocr.service.IOcrCleanupService;
import cn.sichu.system.file.entity.FileUpload;
import cn.sichu.system.file.mapper.FileUploadMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import config.ProjectConfig;
import enums.TableLogic;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.io.File;
import java.time.LocalDateTime;
import java.util.List;

/**
 * @author sichu huang
 * @since 2025/12/07 19:27
 */
@Service("ocrCleanupService")
@RequiredArgsConstructor
@Slf4j
public class OcrCleanupServiceImpl implements IOcrCleanupService {

    private final FileUploadMapper fileUploadMapper;
    private final OcrImageMapper ocrImageMapper;
    private final OcrResultMapper ocrResultMapper;
    // private final ISysJobLogService sysJobLogService;
    private final ProjectConfig projectConfig;

    /**
     * 清理已处理（status=1）且超过7天的 OCR 相关文件
     * - file_upload(category='ocr')
     * - ocr_image(关联 file_upload_id)
     * - ocr_result(关联 file_upload_id)
     * 物理删除文件 + 逻辑删除 DB 记录
     *
     * @author sichu huang
     * @since 2025/12/07 19:27:39
     */
    @Override
    @Async
    public void cleanupProcessedOcrFiles() {
        String rootDir = projectConfig.getFile().getRootDir();
        log.info("开始执行 OCR 已处理文件清理任务...");
        /* 安全校验根目录 */
        File root = new File(rootDir);
        if (!root.exists() || !root.isDirectory()) {
            String msg = "上传根目录无效: " + rootDir;
            log.error(msg);
            // saveJobLog(false, msg);
            return;
        }
        LocalDateTime ago = LocalDateTime.now().minusDays(7);
        List<FileUpload> filesToClean = fileUploadMapper.selectList(
            Wrappers.lambdaQuery(FileUpload.class).eq(FileUpload::getCategory, "ocr")
                .eq(FileUpload::getIsDeleted, TableLogic.NOT_DELETED.getCode())
                .le(FileUpload::getUploadTime, ago).inSql(FileUpload::getId,
                    "SELECT r.file_upload_id FROM ocr_result r WHERE r.file_upload_id = file_upload.id AND r.status = 0 AND r.is_deleted = 0"));
        if (filesToClean.isEmpty()) {
            log.info("无符合条件的 OCR 文件需要清理");
            // saveJobLog(true, "无过期已处理文件");
            return;
        }
        log.info("发现 {} 个可清理的 OCR 文件记录", filesToClean.size());
        int successCount = 0;
        StringBuilder details = new StringBuilder();
        for (FileUpload file : filesToClean) {
            try {
                if (!file.getPath().startsWith("/ocr/")) {
                    log.warn("跳过非标准 OCR 路径（安全拦截）: id={}, path={}", file.getId(),
                        file.getPath());
                    continue;
                }
                /* 物理删除 */
                String absolutePath = rootDir + file.getPath();
                File localFile = new File(absolutePath);
                if (localFile.exists()) {
                    boolean deleted = localFile.delete();
                    if (!deleted) {
                        log.warn("物理删除失败（可能被占用）: {}", absolutePath);
                        continue;
                    }
                    log.debug("物理删除成功: {}", absolutePath);
                } else {
                    log.debug("文件已不存在（可能重复清理）: {}", absolutePath);
                }
                /* 逻辑删除 file_upload, ocr_image, ocr_result */
                LocalDateTime fileUploadNow = LocalDateTime.now();
                file.setUpdateBy(1L);
                file.setUpdateTime(fileUploadNow);
                file.setIsDeleted(TableLogic.DELETED.getCode());
                file.setDeleteBy(1L);
                file.setDeleteTime(fileUploadNow);
                fileUploadMapper.updateById(file);

                LocalDateTime ocrImageNow = LocalDateTime.now();
                LambdaQueryWrapper<OcrImage> ocrImageQuery =
                    Wrappers.lambdaQuery(OcrImage.class).eq(OcrImage::getFileUploadId, file.getId())
                        .eq(OcrImage::getIsDeleted, TableLogic.NOT_DELETED.getCode());
                List<OcrImage> ocrImages = ocrImageMapper.selectList(ocrImageQuery);
                for (OcrImage ocrImage : ocrImages) {
                    ocrImage.setUpdateBy(1L);
                    ocrImage.setUpdateTime(ocrImageNow);
                    ocrImage.setIsDeleted(TableLogic.DELETED.getCode());
                    ocrImage.setDeleteTime(ocrImageNow);
                    ocrImageMapper.updateById(ocrImage);
                }

                LocalDateTime ocrResultNow = LocalDateTime.now();
                LambdaQueryWrapper<OcrResult> ocrResultQuery = Wrappers.lambdaQuery(OcrResult.class)
                    .eq(OcrResult::getFileUploadId, file.getId())
                    .eq(OcrResult::getIsDeleted, TableLogic.NOT_DELETED.getCode());
                List<OcrResult> ocrResults = ocrResultMapper.selectList(ocrResultQuery);
                for (OcrResult ocrResult : ocrResults) {
                    ocrResult.setUpdateBy(1L);
                    ocrResult.setUpdateTime(ocrResultNow);
                    ocrResult.setIsDeleted(TableLogic.DELETED.getCode());
                    ocrResult.setDeleteTime(ocrResultNow);
                    ocrResultMapper.updateById(ocrResult);
                }

                ++successCount;
                details.append("success: ID=").append(file.getId()).append(", path=")
                    .append(file.getPath()).append("\n");
            } catch (Exception e) {
                String errorMsg = String.format("清理异常 - ID=%d, path=%s, error=%s", file.getId(),
                    file.getPath(), e.getMessage());
                log.error(errorMsg, e);
                details.append("failed: ").append(errorMsg).append("\n");
            }
        }
        String summary =
            String.format("清理完成：成功 %d / 总计 %d", successCount, filesToClean.size());
        log.info(summary);
        // saveJobLog(true, summary + "\n" + details);
    }

    // private void saveJobLog(boolean success, String detail) {
    //     try {
    //         SysJobLog sysJobLog = new SysJobLog();
    //         sysJobLog.setJobName("cleanupProcessedOcrFiles");
    //         sysJobLog.setStatus(
    //             success ? BusinessStatus.SUCCESS.getCode() : BusinessStatus.FAILED.getCode());
    //         sysJobLog.setInvokeTarget("ocrCleanupService.cleanupProcessedOcrFiles");
    //         sysJobLog.setJobMessage(detail);
    //         sysJobLog.setCreateTime(LocalDateTime.now());
    //         sysJobLogService.save(sysJobLog);
    //     } catch (Exception e) {
    //         log.error("记录任务日志失败", e);
    //     }
    // }
}
