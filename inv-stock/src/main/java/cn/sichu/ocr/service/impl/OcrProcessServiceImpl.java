package cn.sichu.ocr.service.impl;

import cn.sichu.ocr.entity.OcrImage;
import cn.sichu.ocr.entity.OcrResult;
import cn.sichu.ocr.mapper.OcrResultMapper;
import cn.sichu.ocr.service.IOcrImageService;
import cn.sichu.ocr.service.IOcrProcessService;
import cn.sichu.ocr.service.ITesseractOcrService;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import enums.BusinessStatus;
import enums.ProcessStatus;
import enums.TableLogic;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import result.ResultCode;
import utils.CollectionUtils;
import utils.StringUtils;

import java.time.LocalDateTime;
import java.util.List;
import java.util.regex.Pattern;

/**
 * @author sichu huang
 * @since 2025/11/23 00:26
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class OcrProcessServiceImpl implements IOcrProcessService {

    /**
     * 匹配中文字符（包括常见标点）
     */
    private static final Pattern CHINESE_CHAR = Pattern.compile("[\\u4e00-\\u9fa5]");
    private final IOcrImageService ocrImageService;
    private final OcrResultMapper ocrResultMapper;
    private final ITesseractOcrService tesseractOcrService;

    /**
     * 1.替换换行符和回车符
     * <br/>
     * 2.移除多个连续空格 -> 单个空格
     * <br/>
     * 3.处理标点符号, 移除它们前后的空格并修正格式
     * <br/>
     * 4.解决引号配对
     *
     * @param rawText rawText
     * @return java.lang.String
     * @author sichu huang
     * @since 2025/11/23 05:09:29
     */
    private static String getText(String rawText) {
        String text = rawText.replace("\\n", "").replace("\n", "").replace("\r", "");
        text =
            text.replaceAll("\\s+", " ").replaceAll("\\s*、\\s*", "、").replaceAll("\\s*,\\s*", ",")
                .replaceAll("\\s*;\\s*", ";").replaceAll("\\s*。\\s*", "。")
                .replaceAll("\\s*-\\s*", "-").replaceAll("\\s*“\\s*", "“").replaceAll("”\\s*", "”");
        return text;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public int processPendingImages() {
        LambdaQueryWrapper<OcrImage> wrapper = Wrappers.lambdaQuery(OcrImage.class)
            .eq(OcrImage::getStatus, ProcessStatus.UNPROCESSED.getCode())
            .eq(OcrImage::getIsDeleted, TableLogic.NOT_DELETED.getCode());
        List<OcrImage> list = ocrImageService.list(wrapper);
        if (CollectionUtils.isEmpty(list)) {
            log.info("没有待处理的OCR图片");
            return 0;
        }
        int success = 0;
        for (OcrImage image : list) {
            OcrResult result = new OcrResult();
            result.setFileUploadId(image.getFileUploadId());
            try {
                byte[] imageData = image.getImageData();
                if (imageData == null || imageData.length == 0) {
                    throw new BusinessException(ResultCode.OCR_FAILED);
                }
                String rawText = tesseractOcrService.recognize(imageData);
                String processedText = postProcess(rawText);
                result.setRawText(rawText);
                result.setProcessedText(processedText);
                result.setWordCount((long)rawText.length());
                result.setProcessedBy(1L);
                result.setProcessTime(LocalDateTime.now());
                result.setStatus(BusinessStatus.SUCCESS.getCode());
                image.setStatus(ProcessStatus.PROCESSED.getCode());
                ++success;
            } catch (Exception e) {
                result.setStatus(BusinessStatus.FAILED.getCode());
                result.setErrorMessage(StringUtils.maxLength(e.getMessage(), 500));
                image.setStatus(ProcessStatus.PROCESS_FAILED.getCode());
                log.error("OCR失败，imageId={}", image.getId(), e);
            }
            ocrResultMapper.insert(result);
            ocrImageService.updateById(image);
        }

        log.info("本次OCR处理完成，成功{}张，总共{}张", success, list.size());
        return success;
    }

    @Override
    public String postProcess(String rawText) {
        if (StringUtils.isEmpty(rawText)) {
            return rawText;
        }
        String text = getText(rawText);
        /* 5.移除中文字符之间的空格 */
        StringBuilder sb = new StringBuilder();
        char[] chars = text.toCharArray();
        for (int i = 0; i < chars.length; i++) {
            char c = chars[i];
            /* 如果当前是空格，且前后都是中文，则跳过（不添加） */
            if (c == ' ' && i > 0 && i < chars.length - 1) {
                char prev = chars[i - 1];
                char next = chars[i + 1];
                if (CHINESE_CHAR.matcher(String.valueOf(prev)).matches() && CHINESE_CHAR.matcher(
                    String.valueOf(next)).matches()) {
                    /* 跳过中文之间的空格 */
                    continue;
                }
            }
            sb.append(c);
        }
        return sb.toString().trim();
    }
}
