package cn.sichu.ocr.controller;

import cn.sichu.ocr.dto.UploadImageDto;
import cn.sichu.ocr.entity.OcrImage;
import cn.sichu.ocr.service.IOcrImageService;
import cn.sichu.ocr.service.IOcrProcessService;
import cn.sichu.ocr.service.ITesseractOcrService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import result.Result;

import java.io.IOException;

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
    private final ITesseractOcrService ocrService;

    /**
     * 上传图片
     *
     * @param uploadImageDto uploadImageDto
     * @return result.Result<cn.sichu.entity.OcrImage>
     * @author sichu huang
     * @since 2025/11/23 00:17:40
     */
    @PostMapping("/upload")
    public Result<OcrImage> upload(UploadImageDto uploadImageDto) throws IOException {
        return Result.success(ocrImageService.uploadImage(uploadImageDto.getFile()));
    }

    /**
     * 处理ocr数据
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

    /**
     * 测试 上传文件单张图片的OCR处理
     * <br/>
     * postman 使用 form-data
     *
     * @param file file
     * @return result.Result<java.lang.String>
     * @author sichu huang
     * @since 2025/11/23 00:20:04
     */
    @PostMapping("/test-ocr")
    public Result<String> recognize(@RequestParam("file") MultipartFile file) throws IOException {
        if (file.isEmpty()) {
            return Result.failed("文件不能为空");
        }
        String text = ocrService.recognize(file.getBytes());
        return Result.success(text);
    }

    /**
     * 测试 将rawText进行后处理
     *
     * @param rawText rawText
     * @return result.Result<java.lang.String>
     * @author sichu huang
     * @since 2025/11/23 04:40:58
     */
    @PostMapping("/test-post-process")
    public Result<String> postProcess(@RequestBody String rawText) {
        if (rawText == null) {
            return Result.failed("原始文本不能为空");
        }
        String cleanText = ocrProcessService.postProcess(rawText);
        return Result.success(cleanText);
    }
}
