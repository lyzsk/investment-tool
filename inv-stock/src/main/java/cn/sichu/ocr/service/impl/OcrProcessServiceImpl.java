package cn.sichu.ocr.service.impl;

import cn.sichu.ocr.entity.OcrImage;
import cn.sichu.ocr.entity.OcrResult;
import cn.sichu.ocr.enums.OcrProcessMode;
import cn.sichu.ocr.mapper.OcrResultMapper;
import cn.sichu.ocr.service.IOcrImageService;
import cn.sichu.ocr.service.IOcrProcessService;
import cn.sichu.ocr.service.ITesseractOcrService;
import cn.sichu.system.file.entity.FileUpload;
import cn.sichu.system.file.mapper.FileUploadMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import config.ProjectConfig;
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

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.util.List;
import java.util.regex.Matcher;
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
    private final FileUploadMapper fileUploadMapper;
    private final ProjectConfig projectConfig;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public int processPendingImages(OcrProcessMode mode) {
        LambdaQueryWrapper<OcrImage> query = Wrappers.lambdaQuery(OcrImage.class)
            .eq(OcrImage::getStatus, ProcessStatus.UNPROCESSED.getCode())
            .eq(OcrImage::getIsDeleted, TableLogic.NOT_DELETED.getCode());
        List<OcrImage> list = ocrImageService.list(query);
        if (CollectionUtils.isEmpty(list)) {
            log.info("没有待处理的OCR图片");
            return 0;
        }
        int success = 0;
        for (OcrImage image : list) {
            OcrResult result = new OcrResult();
            Long fileUploadId = image.getFileUploadId();
            result.setFileUploadId(fileUploadId);
            LocalDateTime now = LocalDateTime.now();
            try {
                FileUpload fileUpload = fileUploadMapper.selectById(fileUploadId);
                if (fileUpload == null
                    || fileUpload.getIsDeleted() == TableLogic.DELETED.getCode()) {
                    throw new BusinessException("关联的文件上传记录不存在或已删除");
                }
                String absolutePath = projectConfig.getFile().getRootDir() + fileUpload.getPath();
                File file = new File(absolutePath);
                if (!file.exists()) {
                    throw new BusinessException(ResultCode.FILE_NOT_FOUND + ": " + absolutePath);
                }
                byte[] imageData = Files.readAllBytes(Paths.get(absolutePath));
                if (imageData.length == 0) {
                    throw new BusinessException(ResultCode.FAILED_TO_READ_FILE);
                }
                String rawText = tesseractOcrService.recognize(imageData);
                String processedText = mode == OcrProcessMode.FULL ? fullPostProcess(rawText) :
                    simplePostProcess(rawText);
                result.setRawText(rawText);
                result.setProcessedText(processedText);
                result.setWordCount((long)rawText.length());
                result.setProcessedBy(1L);
                result.setProcessTime(now);
                result.setStatus(BusinessStatus.SUCCESS.getCode());
                image.setStatus(ProcessStatus.PROCESSED.getCode());
                ++success;
            } catch (Exception e) {
                result.setStatus(BusinessStatus.FAILED.getCode());
                result.setErrorMessage(StringUtils.maxLength(e.getMessage(), 500));
                image.setStatus(ProcessStatus.PROCESS_FAILED.getCode());
                log.error("OCR失败，imageId={}", image.getId(), e);
            }
            result.setCreateTime(now);
            ocrResultMapper.insert(result);
            ocrImageService.updateById(image);
        }
        log.info("本次OCR处理完成，成功{}张，总共{}张", success, list.size());
        return success;
    }

    /**
     * 对 OCR 原始文本进行后处理，提升可读性
     *
     * @param rawText OCR 原始识别结果
     * @return java.lang.String 移除中文间空格, 合并 '+'
     * @author sichu huang
     * @since 2025/12/23 23:15:56
     */
    private String simplePostProcess(String rawText) {
        if (StringUtils.isEmpty(rawText)) {
            return rawText;
        }
        String text = getText(rawText);
        text = text.replaceAll("\\s*\\+\\s*", "+");
        StringBuilder cleaned = new StringBuilder();
        char[] chars = text.toCharArray();
        for (int i = 0; i < chars.length; i++) {
            char c = chars[i];
            if (c == ' ' && i > 0 && i < chars.length - 1) {
                char prev = chars[i - 1];
                char next = chars[i + 1];
                if (CHINESE_CHAR.matcher(String.valueOf(prev)).matches() && CHINESE_CHAR.matcher(
                    String.valueOf(next)).matches()) {
                    continue;
                }
            }
            cleaned.append(c);
        }
        return cleaned.toString().trim();
    }

    /**
     * 对 OCR 原始文本进行后处理，提升可读性
     *
     * @param rawText OCR 原始识别结果
     * @return java.lang.String 结构化后的文本，字段以 " | " 分隔：股票名 | 现价 | 涨幅 | 时间 | 市值 | 股票代码 | 其他信息
     * @author sichu huang
     * @since 2025/11/23 04:28:37
     */
    private String fullPostProcess(String rawText) {
        String text = simplePostProcess(rawText);

        /*
         * 关键改进：
         * 1. 涨幅支持任意数字格式（含小数）
         * 2. 时间严格匹配 HH:MM:SS
         * 3. 市值前允许引号/下划线
         * 4. 其他信息结束条件：下一个明显股票头（中文+空格+数字+小数+ +/-）
         */
        String regex =
            /* 股票名（至少2个中文） */
            "([\\u4e00-\\u9fa5]{2,}[\\u4e00-\\u9fa5\\d]*)\\s+" +
                /* 现价 */
                "(\\d+\\.\\d+|\\d+)\\s*" +
                /* 涨幅：任意带符号数字 */
                "([+-]?\\d*\\.?\\d+)" +
                /* 任意字符（非贪婪）直到时间出现 */
                ".*?" +
                /* 时间：必须匹配 HH:mm:ss */
                "(\\d{1,2}:\\d{1,2}:\\d{1,2})" +
                /* 市值前噪声 */
                "[^\\d\u4e00-\u9fa5]*?" +
                /* 市值 */
                "([\\d.]+\\s*亿)" +
                /* 股票代码前干扰字 */
                "[回国固团]?\\s*" +
                /* 股票代码（6位数字），后接空格/中文/结束 */
                "(\\d{6})(?=\\s|[\u4e00-\u9fa5]|$)" +
                /* 其他信息：吃到下一个股票头或结束 */
                "(.*?)(?=\\s*[\\u4e00-\\u9fa5]{2,}\\s+\\d+\\.?\\d+\\s*[+-]|$)";

        Pattern pattern = Pattern.compile(regex, Pattern.DOTALL);
        Matcher matcher = pattern.matcher(text);

        StringBuilder result = new StringBuilder();
        int lastEnd = 0;

        while (matcher.find()) {
            /* 添加匹配前的非结构化文本（如开头的说明段落） */
            if (matcher.start() > lastEnd) {
                String prefix = text.substring(lastEnd, matcher.start()).trim();
                if (!prefix.isEmpty()) {
                    if (!result.isEmpty()) {
                        result.append("\n");
                    }
                    result.append(prefix);
                }
            }

            String stockName = matcher.group(1).trim();
            String price = matcher.group(2).trim();
            String changeRaw = matcher.group(3).trim();
            String timeRaw = matcher.group(4).trim();
            String marketValue = matcher.group(5).replace(" ", "").trim();
            String code = matcher.group(6).trim();
            String otherInfo = matcher.group(7).trim();

            /* 处理涨幅：自动补全为 +x.xx% 格式 */
            String changeStr = normalizeChange(changeRaw);

            /* 处理时间：清洗分隔符并标准化为 HH:MM:SS */
            String timeStr = normalizeTime(timeRaw);

            /* 拼接结构化行 */
            String line =
                String.join(" | ", stockName, price, changeStr, timeStr, marketValue, code,
                    otherInfo);

            if (!result.isEmpty()) {
                result.append("\n");
            }
            result.append(line);
            lastEnd = matcher.end();
        }

        /* 添加剩余未匹配的尾部文本 */
        if (lastEnd < text.length()) {
            String suffix = text.substring(lastEnd).trim();
            if (!suffix.isEmpty()) {
                if (!result.isEmpty()) {
                    result.append("\n");
                }
                result.append(suffix);
            }
        }

        /* 若未匹配任何条目，返回原始清洗文本（避免数据丢失） */
        return !result.isEmpty() ? result.toString() : text;
    }

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
    private String getText(String rawText) {
        String text = rawText.replace("\\n", "").replace("\n", "").replace("\r", "");
        text =
            text.replaceAll("\\s+", " ").replaceAll("\\s*、\\s*", "、").replaceAll("\\s*,\\s*", ",")
                .replaceAll("\\s*;\\s*", ";").replaceAll("\\s*。\\s*", "。")
                .replaceAll("\\s*-\\s*", "-").replaceAll("\\s*“\\s*", "“").replaceAll("”\\s*", "”");
        return text;
    }

    /**
     * 将 OCR 识别的涨幅数字（如 998、1005）标准化为 +x.xx% 格式
     *
     * @param changeRaw 原始涨幅字符串（可能含 +/-，不含 %）
     * @return java.lang.String 标准化后的涨幅，如 "+9.98%"
     * @author sichu huang
     * @since 2025/12/23 16:51:19
     */
    private String normalizeChange(String changeRaw) {
        if (StringUtils.isEmpty(changeRaw)) {
            return "+0.00%";
        }
        boolean isNegative = changeRaw.startsWith("-");
        /* 提取第一个连续的数字+小数点序列（支持 .xx 或 xx.xx） */
        Matcher m = Pattern.compile("\\d*\\.?\\d+").matcher(changeRaw);
        if (!m.find()) {
            return "+0.00%";
        }
        String clean = m.group();
        try {
            double value;
            if (clean.contains(".")) {
                value = Double.parseDouble(clean);
            } else {
                int intValue = Integer.parseInt(clean);
                value = intValue >= 100 ? intValue / 100.0 : intValue;
            }
            return (isNegative ? "-" : "+") + String.format("%.2f", value) + "%";
        } catch (Exception e) {
            return changeRaw + "%";
        }
    }

    /**
     * 清洗并标准化时间字符串（如 “14:41:46“_ → 14:41:46）
     *
     * @param timeRaw 原始时间字符串
     * @return java.lang.String 标准化后的时间，格式 HH:mm:ss
     * @author sichu huang
     * @since 2025/12/23 16:51:48
     */
    private String normalizeTime(String timeRaw) {
        if (StringUtils.isEmpty(timeRaw)) {
            return "00:00:00";
        }
        /* 替换所有非数字字符为冒号 */
        String cleaned = timeRaw.replaceAll("\\D", ":");
        /* 移除首尾冒号 */
        cleaned = cleaned.replaceAll("^:+|:+$", "");
        /* 分割并取最多3段 */
        String result = getSegment(cleaned);
        if (result.chars().filter(ch -> ch == ':').count() == 1) {
            result += ":00";
        } else if (!result.contains(":")) {
            result = "00:00:00";
        }
        return result;
    }

    /**
     * @param cleaned cleaned
     * @return java.lang.String
     * @author sichu huang
     * @since 2025/12/23 16:53:27
     */
    private String getSegment(String cleaned) {
        String[] parts = cleaned.split(":+");
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < Math.min(parts.length, 3); i++) {
            String part = parts[i].trim();
            if (part.isEmpty())
                part = "00";
            if (part.length() == 1)
                part = "0" + part;
            if (i > 0)
                sb.append(":");
            sb.append(part);
        }
        /* 补足至 HH:MM:SS */
        return sb.toString();
    }
}
