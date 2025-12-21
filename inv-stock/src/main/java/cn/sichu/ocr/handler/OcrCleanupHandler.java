package cn.sichu.ocr.handler;

import cn.sichu.ocr.service.IOcrCleanupService;
import cn.sichu.system.quartz.handler.JobHandler;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/**
 * OCR 清理任务处理器
 *
 * @author sichu huang
 * @since 2025/12/21 13:43
 */
@Component("ocrCleanupHandler")
@RequiredArgsConstructor
public class OcrCleanupHandler implements JobHandler {
    private final IOcrCleanupService ocrCleanupService;

    @Override
    public String execute(String params) {
        ocrCleanupService.cleanupProcessedOcrFiles();
        return "OCR 清理任务执行完成";
    }
}
