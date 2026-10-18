package cn.sichu.ocr.service;

/**
 * @author sichu huang
 * @since 2025/12/07 19:26
 */
public interface IOcrCleanupService {
    /**
     * 清理已处理（status=1）且超过7天的 OCR 相关文件
     * - file_upload(category='ocr')
     * - ocr_image(关联 file_upload_id)
     * - ocr_result(关联 file_upload_id)
     * 物理删除文件 + 逻辑删除 DB 记录
     * <p/>
     * update 2025/12/21 13:46:03 : 删除 @Async, JobHandlerInvoker 已在一个独立线程中执行
     *
     * @author sichu huang
     * @since 2025/12/07 19:27:39
     */
    void cleanupProcessedOcrFiles();
}
