package cn.sichu.ocr.service.impl;

import cn.sichu.ocr.entity.OcrImage;
import cn.sichu.ocr.entity.OcrResult;
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
import java.util.ArrayList;
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
    public int processPendingImages() {
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
                String absolutePath =
                    projectConfig.getFileUpload().getRootDir() + fileUpload.getPath();
                File file = new File(absolutePath);
                if (!file.exists()) {
                    throw new BusinessException(ResultCode.FILE_NOT_FOUND + ": " + absolutePath);
                }
                byte[] imageData = Files.readAllBytes(Paths.get(absolutePath));
                if (imageData.length == 0) {
                    throw new BusinessException(ResultCode.FAILED_TO_READ_FILE);
                }
                String rawText = tesseractOcrService.recognize(imageData);
                String processedText = fullPostProcess(rawText);
                result.setRawText(rawText);
                result.setProcessedText(processedText);
                result.setWordCount((long)rawText.length());
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
     * @return java.lang.String 结构化后的文本，字段以 " | " 分隔：股票名 | 现价 | 涨幅 | 时间 | 市值 | 股票代码 | 其他信息
     * @author sichu huang
     * @since 2025/11/23 04:28:37
     */
    private String fullPostProcess(String rawText) {
        String text = simplePostProcess(rawText);
        text = text.replace("%6“", StringUtils.PERCENT).replace("%6 _", StringUtils.PERCENT)
            .replace("%6 ", StringUtils.PERCENT).replace("%6_", StringUtils.PERCENT)
            .replace("%““_", StringUtils.PERCENT);
        /*
         * 关键改进：
         * 1. 涨幅支持任意数字格式（含小数）
         * 2. 时间严格匹配 HH:mm:ss
         * 3. 市值前允许引号/下划线
         * 4. 其他信息结束条件：下一个明显股票头（中文+空格+数字+小数+ +/-）
         */
        String regex =
            /* 股票名：2+ 中文，可含数字 */
            "([\\u4e00-\\u9fa5]{2,}[\\u4e00-\\u9fa5\\d]*)\\s+" +
                /* 现价: 必须是 xx.xx 或 xx，后面紧跟 +/- 或空格+/- */
                "(\\d+(?:\\.\\d+)?)\\s*" +
                /* 涨幅: 必须以 + 开头（避免匹配百分比或普通数字） */
                "([+]\\d*\\.?\\d+)%?\\s*" +
                /* 非贪婪跳过，但不能包含换行或新段落 */
                "[^\\n]*?" +
                /* 时间: 必须匹配 HH:mm:ss, 且前后不是数字 */
                "(?<!\\d)(\\d{1,2}:\\d{2}:\\d{2})(?!\\d)" +
                /* 市值: 数字 + “亿”，前面允许少量符号 */
                "[^\\u4e00-\\u9fa5\\w]*?" + "([\\d.]+\\s*亿)" +
                /* 股票代码前干扰字 */
                "[国回团固囝申图因]?\\s*" +
                /* 股票代码（6位数字），后接空格/中文/结束 */
                "(\\d{6})";

        Pattern stockPattern = Pattern.compile(regex, Pattern.DOTALL);
        List<MatchInfo> matches = getMatchInfos(stockPattern, text);

        if (matches.isEmpty()) {
            return text;
        }

        StringBuilder result = new StringBuilder();
        int lastPos = 0;

        for (int i = 0; i < matches.size(); i++) {
            MatchInfo current = matches.get(i);

            /* 1. 先追加 [lastPos, current.start) 的原始文本（可能是驱动因素、标题等） */
            if (current.start > lastPos) {
                String prefix = text.substring(lastPos, current.start).trim();
                if (!prefix.isEmpty()) {
                    result.append(prefix).append("\n");
                }
            }

            /* 2. 提取当前股票的描述：从 current.end 到 next.start（或 EOF） */
            int descEnd = (i + 1 < matches.size()) ? matches.get(i + 1).start : text.length();
            String otherInfo = text.substring(current.end, descEnd).trim();

            /* 3. 标准化字段 */
            String changeStr = normalizeChange(current.changeRaw);
            String timeStr = normalizeTime(current.timeRaw);

            /* 4. 拼接结构化行 */
            result.append(String.join(" | ", current.stockName, current.price, changeStr, timeStr,
                current.marketValue, current.code, otherInfo)).append("\n");

            lastPos = descEnd;
        }

        /* 5. 追加最后剩余内容（如果有） */
        if (lastPos < text.length()) {
            String suffix = text.substring(lastPos).trim();
            if (!suffix.isEmpty()) {
                result.append(suffix).append("\n");
            }
        }

        return result.toString().trim();
    }

    private List<MatchInfo> getMatchInfos(Pattern stockPattern, String text) {
        Matcher matcher = stockPattern.matcher(text);

        List<MatchInfo> matches = new ArrayList<>();
        while (matcher.find()) {
            String name = matcher.group(1).trim();
            if (name.matches("\\d+"))
                continue;

            matches.add(new MatchInfo(matcher.start(), matcher.end(), name, matcher.group(2).trim(),
                matcher.group(3).trim(), matcher.group(4).trim(),
                matcher.group(5).replace(StringUtils.SPACE, StringUtils.EMPTY).trim(),
                matcher.group(6).trim()));
        }
        return matches;
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
        text = text.replaceAll("\\s*\\+\\s*", StringUtils.PLUS);
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
        String text = rawText.replace("\\n", StringUtils.EMPTY).replace("\n", StringUtils.EMPTY)
            .replace("\r", StringUtils.EMPTY);
        text = text.replaceAll("\\s+", StringUtils.SPACE).replaceAll("\\s*、\\s*", "、")
            .replaceAll("\\s*,\\s*", StringUtils.COMMA)
            .replaceAll("\\s*;\\s*", StringUtils.SEMICOLON).replaceAll("\\s*。\\s*", "。")
            .replaceAll("\\s*-\\s*", StringUtils.MINUS).replaceAll("\\s*“\\s*", "“")
            .replaceAll("”\\s*", "”");
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
        boolean isNegative = changeRaw.startsWith(StringUtils.MINUS);
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
            return (isNegative ? StringUtils.MINUS : StringUtils.PLUS) + String.format("%.2f",
                value) + StringUtils.PERCENT;
        } catch (Exception e) {
            return changeRaw + StringUtils.PERCENT;
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
        String cleaned = timeRaw.replaceAll("\\D", StringUtils.COLON);
        /* 移除首尾冒号 */
        cleaned = cleaned.replaceAll("^:+|:+$", StringUtils.EMPTY);
        /* 分割并取最多3段 */
        String result = getSegment(cleaned);
        if (result.chars().filter(ch -> ch == ':').count() == 1) {
            result += ":00";
        } else if (!result.contains(StringUtils.COLON)) {
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
                sb.append(StringUtils.COLON);
            sb.append(part);
        }
        /* 补足至 HH:mm:ss */
        return sb.toString();
    }

    private record MatchInfo(int start, int end, String stockName, String price, String changeRaw,
                             String timeRaw, String marketValue, String code) {

    }
}
