package cn.sichu.ocr.controller;

import cn.sichu.ocr.service.IOcrImageService;
import cn.sichu.ocr.service.IOcrProcessService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import result.Result;

/**
 * @author sichu huang
 * @since 2025/11/22 21:45
 */
@RestController
@RequestMapping("/api/ocr")
@RequiredArgsConstructor
@Slf4j
public class OcrImageController {

    private final IOcrImageService ocrImageService;
    private final IOcrProcessService ocrProcessService;

    /**
     * 同步数据
     * <p/>
     * 读取`file_upload`表中category='ocr'的文件,更新`ocr_image`表
     *
     * @return result.Result<java.lang.Integer>
     * @author sichu huang
     * @since 2025/11/30 08:54:07
     */
    @PostMapping("/sync")
    public Result<Integer> sync() {
        int count = ocrImageService.syncFromFileUpload();
        return Result.success(count);
    }

    /**
     * 处理OCR任务
     * <p/>
     * 读取`ocr_image`表中status='0'的文件,更新`ocr_result`表
     *
     * @return result.Result<java.lang.Integer>
     * @author sichu huang
     * @since 2025/11/23 05:36:07
     */
    @PostMapping("/process")
    public Result<Integer> process() {
        int count = ocrProcessService.processPendingImages();
        return Result.success(count);
    }
}
